"""
The character save — the `data` blob of CharacterData (75) / UserCharConn (60) / AddCharacter (86) /
CreateCharacterFromPreview (77). It is the game's own persistence format: the client builds the
character's AvatarProxy from it at login (AvatarProxy::ApplyCharacterDataBlocks S 00481e60), so
whatever the server stores here is what the player sees after logging in again.

Envelope [known] (T 100163c0, docs/village-and-character-protocol.md §1.4): six u32 LE part sizes
(0x18 bytes), then the six parts concatenated. Every field inside is little-endian.

Parts, as the client reads them [known — each block's Deserialize]:
  0  Appearance  variant u32, body u32, gender u32                       (0xC bytes; S 00486760)
     or, on a freshly created character, Creation: variant, body, gender, hair, skin, shirt,
     trouser, [addColor1..4 if variant != 0]       (S 004864a0; client: parts 1-5 empty)
  1  Style       variant, hair, skin, shirt, trouser, [addColor1..4 if variant != 0]   (S 004868c0)
  2  ActiveItems variant, 4 x {slotType, itemId, count}      (defaults slotType 2,3,4,5; S 00486a20)
  3  Inventory   variant, count, min(count, 20) x {slotType, itemId, count}            (S 00486b60)
  4  Stats       variant, level, exp, gold, [glod if variant != 0],
                 [x f32, y f32, z f32, heading u32, zone u8, ghost zone u8 if variant > 1]  (S 00486d70)
  5  unused
The creation form (part 0 not 0xC bytes, parts 1-5 empty) starts the character with level 1, gold =
glod = 50 and the default spawn; the full form restores everything above.
"""
import struct
from dataclasses import dataclass, field

N_PARTS = 6
INVENTORY_SLOTS = 20
ACTIVE_SLOT_TYPES = (2, 3, 4, 5)
DEFAULT_POS = (-31.24, 2.71, 8.28)               # Stats ctor defaults (S 00486c80)
CREATION_POS = (-31.24, 2.71, -8.28)             # the creation path's spawn (S 00481e60)


@dataclass
class Save:
    body: int = 0                                # AvatarProxy+0x48 high nibble
    gender: int = 0                              # AvatarProxy+0x48 low nibble
    colours: list = field(default_factory=lambda: [0] * 8)   # hair skin shirt trouser add1..4
    active: list = field(default_factory=lambda: [None] * 4)  # (item_id, count, sltt) or None
    inventory: list = field(default_factory=lambda: [None] * INVENTORY_SLOTS)
    level: int = 1
    exp: int = 0
    gold: int = 1000
    glod: int = 1000
    pos: tuple = DEFAULT_POS
    heading: int = 0                             # raw u32 the client keeps at AvatarProxy+0x70
    zone: int = 0
    ghost_zone: int = 0xF
    fresh: bool = False                          # parsed from a creation-form blob

    @property
    def trbgndr(self):
        return (self.body & 0xF) << 4 | (self.gender & 0xF)


def split(blob):
    """The six parts. A blob shorter than the header has six empty parts (as the client)."""
    if not blob or len(blob) < 4 * N_PARTS:
        return [b""] * N_PARTS
    sizes = struct.unpack_from("<6I", blob, 0)
    parts, pos = [], 4 * N_PARTS
    for n in sizes:
        parts.append(blob[pos:pos + n])
        pos += n
    return parts


def join(parts):
    return struct.pack("<6I", *(len(p) for p in parts)) + b"".join(parts)


def _u32s(b):
    return list(struct.unpack_from(f"<{len(b) // 4}I", b, 0))


def _slot(rec, slot_type):
    if rec is None:
        return struct.pack("<3I", slot_type, 0, 0)
    item_id, count, sltt = rec
    return struct.pack("<3I", sltt, item_id, count)


def _read_slot(words, i):
    slot_type, item_id, count = words[i:i + 3]
    return (item_id, count, slot_type) if item_id else None


def parse(blob):
    """Read a character save the way ApplyCharacterDataBlocks does (S 00481e60)."""
    parts = split(blob)
    s = Save()
    p0 = parts[0]
    if len(p0) not in (0, 0xC) and not any(parts[1:]):
        w = _u32s(p0) + [0] * 11                   # short fields keep the ctor defaults (0)
        s.fresh = True
        s.body, s.gender = w[1] & 0xF, w[2] & 0xF
        s.colours = [c & 0xF for c in w[3:7]] + [c & 0xF if w[0] else 0 for c in w[7:11]]
        s.gold = s.glod = 50
        s.pos, s.zone, s.ghost_zone = CREATION_POS, 0, 0xF
        return s
    if len(p0) >= 4:
        w = _u32s(p0) + [0, 0]
        s.body, s.gender = w[1] & 0xF, w[2] & 0xF
    if len(parts[1]) >= 4:
        w = _u32s(parts[1]) + [0] * 8
        s.colours = [c & 0xF for c in w[1:5]] + [c & 0xF if w[0] else 0 for c in w[5:9]]
    if len(parts[2]) >= 4:
        w = _u32s(parts[2]) + [0] * 12
        s.active = [_read_slot(w, 1 + 3 * i) for i in range(4)]
    if len(parts[3]) >= 8:
        w = _u32s(parts[3])
        n = min(w[1], INVENTORY_SLOTS, (len(w) - 2) // 3)
        s.inventory = [_read_slot(w, 2 + 3 * i) for i in range(n)] + [None] * (INVENTORY_SLOTS - n)
    if len(parts[4]) >= 4:
        b = parts[4]
        variant, s.level, s.exp, s.gold = struct.unpack_from("<4I", b + bytes(16), 0)
        if variant != 0 and len(b) >= 20:
            s.glod = struct.unpack_from("<I", b, 16)[0]
        if variant > 1 and len(b) >= 38:
            x, y, z, s.heading = struct.unpack_from("<3fI", b, 20)
            s.pos = (x, y, z)
            s.zone, s.ghost_zone = b[36], b[37]
    return s


def build(s):
    """A full-form save (Appearance, Style variant 1, items, Stats variant 2) for `s`."""
    appearance = struct.pack("<3I", 0, s.body & 0xF, s.gender & 0xF)
    style = struct.pack("<9I", 1, *[c & 0xF for c in (list(s.colours) + [0] * 8)[:8]])
    active = struct.pack("<I", 0) + b"".join(_slot(r, t) for r, t in zip(s.active, ACTIVE_SLOT_TYPES))
    inv = list(s.inventory)[:INVENTORY_SLOTS] + [None] * (INVENTORY_SLOTS - len(s.inventory))
    inventory = struct.pack("<2I", 0, INVENTORY_SLOTS) + b"".join(_slot(r, 0) for r in inv)
    stats = struct.pack("<5I3fI2B", 2, s.level, s.exp, s.gold, s.glod, *s.pos, s.heading & 0xFFFFFFFF,
                        s.zone & 0xFF, s.ghost_zone & 0xFF)
    return join([appearance, style, active, inventory, stats, b""])
