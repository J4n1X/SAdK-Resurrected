"""
Village NPCs — ambient, server-driven settlers so the lobby world feels alive.

On the wire an NPC is indistinguishable from a remote player, and that is the whole
design: an EntityCreate(1001) with a synthetic avatar id, a styled body (name +
colours — `AvatarProxy_ReadStyleBlock@0x004825f0`, the name doubles as the label) and
an AvatarLocation, kept visible by the same 1 Hz waypoint refresh that sustains real
remote avatars (`AvatarMovement_Tick@0x00519d50` hides any avatar whose newest
waypoint goes >3.0 s stale). The client builds the body from the "settler" object
template exactly as it does for a player (`CLobby_CreateAvatarObjFromProxy@0x004f6de0`)
— there is no separate NPC mechanism at the 1001 layer, so none is invented here.

Walkers follow a looped path at walking pace: each ticker cycle advances them one step
and the client's interpolator walks the model smoothly between the 1 Hz waypoints
(bracket path; it only snaps at >=10 units or >2.0 s gaps, far above our step size).

IDs live at NPC_ID_BASE and up — far above the sequential player perm_ids handed out
from 1 (players.py) — so they can never collide with a real player.

NPCs are deliberately NOT players: no chat roster entry, no 1004 player record, no
registry presence. They exist only as world entities pushed over the village conn.

[TODO] Colour-byte semantics (palette indices?) and the `trbgndr` tribe/gender packing
are unmapped; values here are small and chosen for variety, validated only by eyeball.
[TODO] rot_deg facing convention (which compass direction 0° means) is unmapped.
"""
import math
import threading
from dataclasses import dataclass, field

#: Synthetic avatar-id floor. Player perm_ids are handed out sequentially from 1
#: (players.py `_next_perm`); one million leaves six orders of magnitude of headroom.
NPC_ID_BASE = 1_000_000

#: Outdoor square values, relayed verbatim for players standing there: zone 0 is the
#: village square, ghost-zone 15 is the neutral "no ghost zone" sentinel (the minimap
#: gates on own zone==0 && ghstzne==0x0F — see dispatch._live_pose).
SQUARE_ZONE = 0
NO_GHOST_ZONE = 15


@dataclass
class Npc:
    perm_id: int
    name: str
    #: (hrclr, sknclr, shrtclr, trsrclr, addColor1..4) — byte-wide wire slots.
    colours: tuple = ()
    tribe_gender: int = 0
    #: Anchor position (absolute world coords). Static NPCs stand here forever.
    anchor: tuple = (0.0, 0.0, 0.0)
    rot_deg: float = 0.0
    #: Looped patrol path of absolute (x, z) waypoints (y stays at anchor height).
    #: Empty = static. The walker steps `speed` units per second along the loop.
    path: tuple = ()
    speed: float = 0.0
    running: bool = False
    #: Walker state: index of the segment start waypoint + units travelled along it.
    _seg: int = field(default=0, repr=False)
    _dist: float = field(default=0.0, repr=False)
    _pos: tuple = field(default=None, repr=False)

    def __post_init__(self):
        if self._pos is None:
            self._pos = self.anchor

    def style(self):
        """The AvatarStyle dict `village.entity_create_body(style=...)` consumes."""
        return {"name": self.name, "tribe_gender": self.tribe_gender,
                "colours": self.colours}

    def pose(self):
        """Kwargs for `village.send_entity_create` — where the NPC is right now."""
        return {"pos": self._pos, "rot_deg": self.rot_deg,
                "zone": SQUARE_ZONE, "ghost_zone": NO_GHOST_ZONE,
                "running": self.running}

    def advance(self, dt):
        """Move a walker `dt` seconds along its loop; no-op for static NPCs."""
        if not self.path or self.speed <= 0.0:
            return
        remaining = self.speed * dt
        y = self.anchor[1]
        while remaining > 0.0:
            ax, az = self.path[self._seg]
            bx, bz = self.path[(self._seg + 1) % len(self.path)]
            seg_len = math.hypot(bx - ax, bz - az)
            if seg_len <= 1e-6:
                self._seg = (self._seg + 1) % len(self.path)
                self._dist = 0.0
                continue
            if self._dist + remaining < seg_len:
                self._dist += remaining
                remaining = 0.0
            else:
                remaining -= seg_len - self._dist
                self._seg = (self._seg + 1) % len(self.path)
                self._dist = 0.0
                continue
            frac = self._dist / seg_len
            self._pos = (ax + (bx - ax) * frac, y, az + (bz - az) * frac)
            # Face the direction of travel. [TODO] 0-degree convention unverified;
            # wrong mapping is purely cosmetic (a sideways-walking settler).
            self.rot_deg = math.degrees(math.atan2(bx - ax, bz - az)) % 360.0


_lock = threading.Lock()


def make_village_npcs(center):
    """The default ambient cast, placed around the village spawn square.

    `center` is dispatch.VILLAGE_SPAWN_POINT — the one spot whose ground height
    (y=2.71) is [PROVEN] (TTD `avatar_spawn_diag.run`). Everything stays within a few
    units of it so nobody stands inside unknown terrain."""
    cx, cy, cz = center

    def at(dx, dz):
        return (cx + dx, cy, cz + dz)

    def loop(*offsets):
        return tuple((cx + dx, cz + dz) for dx, dz in offsets)

    return [
        Npc(NPC_ID_BASE + 1, "Händler Hinnerk", anchor=at(3.5, 2.0), rot_deg=225.0,
            colours=(2, 1, 3, 1)),
        Npc(NPC_ID_BASE + 2, "Magd Mathilde", anchor=at(-4.0, 3.0), rot_deg=135.0,
            colours=(1, 0, 4, 2)),
        Npc(NPC_ID_BASE + 3, "Alter Anselm", anchor=at(0.5, -4.5), rot_deg=0.0,
            colours=(0, 2, 1, 3)),
        Npc(NPC_ID_BASE + 4, "Wächter Wilhelm", colours=(3, 1, 2, 0),
            anchor=at(6.0, 6.0), path=loop((6, 6), (6, -6), (-6, -6), (-6, 6)),
            speed=1.0),
        Npc(NPC_ID_BASE + 5, "Bote Balduin", colours=(4, 0, 5, 1), running=True,
            anchor=at(-8.0, 0.0), path=loop((-8, 0), (0, 8), (8, 0), (0, -8)),
            speed=2.2),
    ]


def advance_all(npc_list, dt):
    """Advance every walker one ticker step. Called only from the location ticker."""
    with _lock:
        for npc in npc_list:
            npc.advance(dt)
