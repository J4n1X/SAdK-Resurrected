"""
Village / world (third-connection) sub-protocol.

The 3D lobby world ("Betrete Welt…") is entered over a VillageServerConnection — a UserComm-style
TinCat connection on the SAME single 0x26B6 comm layer as the lobby/UC conns (s30/s34). The client
dials it (we advertise 127.0.0.1:5479) and logs in with the SAME flow as the lobby/UC conn
(CheckVersion 188 → token 211/213 → 153 AUTHORIZED), answered by the SAME dispatch handlers.

WORLD ENTRY — the PROVEN core (s39, live screenshot-confirmed): the genuine mechanism is the SERVER
pushing inbound EnterWorld (msg **1000**) UNPROMPTED once the village transport is AUTHORIZED (state 8).
That drives HandleEnterWorld → SetState(VillageEntered=9) → the 3D lobby world RENDERS. This is what the
stub does (dispatch._h_send_game_data / send_enter_world).

  1. [UNVERIFIED / DORMANT] An older model had the client itself send a world-login request as a NETMSG
     SendGameData(74){msg_type=0x27D2, "code"=0xAFFEDEAD} (Village_SendEnterWorld_2002 @0x46b990) which a
     server would answer. In practice that client path is **dormant/dead** (no analyzed caller fires it),
     so the stub does NOT wait for it; it pushes 1000 instead.
  2. msg 1000 MUST be wrapped in a SendGameData(74) envelope: the client's inbound bridge (tincat3
     TinCat_DispatchInboundToSADK) only routes NETMSG 73/74 to VillageServerConnection::HandleMessage,
     using the inner `msg_type` as the dispatch key. A bare 1000 frame is dropped.
  3. HandleMessage → HandleEnterWorld: SetState(VillageEntered=9) → JoinChannel → connState=3 → world.

⚠️ Handler addresses in this file (0x46f470, 0x470890, 0x46b990, 0x46e8b0, 0x46be00, …) are VAs from the
PRE-magazine-build (no-CD/dump) decomp base; the clean magazine build shifted them (e.g. HandleEnterWorld
is 0x46f670 there). They identify the LOGIC, not exact addresses on the current base — see docs/SOURCEMAP.md.

The detection + reply live in dispatch._h_send_game_data (@handler 74); this module builds the frames
and keeps the raw-frame capture log (handle_frame).
"""
import struct

from . import config
from .log import log, hex_dump
from .tincat import app_payload, bytes_field, build_frame, str_field


def gamedata_frame(msg_type, data, magic=None):
    """Wrap a village/world message in a SendGameData(74) NETMSG envelope — the ONLY framing the client's
    inbound bridge routes to VillageServerConnection::HandleMessage. Wire layout (matches the client's own
    outbound world-login request byte-for-byte):
        Magic | 74 | 74 | msg_type:u32 | data:MEMBLOCK(u32 len + bytes)
    `app_payload(74, …)` supplies `Magic | 74 | 74`; the trailing 74 doubles as the msgdef's leading
    `type:u16` field. `magic` = the single 0x26B6 comm-layer magic."""
    body = struct.pack("<I", msg_type) + bytes_field(data)
    return app_payload(config.VILLAGE_SENDGAMEDATA, body, magic=magic)


def enter_world_body(worldname=None, server_perm=None, channels=None):
    """Positional TinCat-PropertySet body for EnterWorld (msg 1000), ground-truthed from
    VillageServerConnection::HandleEnterWorld @0x46f470 (each name is seek'd, then read via the reader
    vtable: +0x30 ReadString / +0x18 ReadMemBlock(dst,0x20)):
        Worldname          : STRING         (str_field; empty => client uses "<UNNAMED>")
        ServerPerm         : MEMBLOCK 0x20   (32-byte world admission token; stored, not validated)
        ChatChannelsCount  : MEMBLOCK 0x20   (read as a 32-byte block; FIRST DWORD = N = channel count)
        repeat N times:
          ChatChannelZone  : MEMBLOCK 0x20
          ChatChannelID    : MEMBLOCK 0x20
    HandleEnterWorld calls SetState(VillageEntered=9) BEFORE parsing, so even a minimal body enters; the
    RE recommends N>=1, so we default to one zero-filled (zone,id) pair. ChatChannelsCount is a 32-byte
    MEMBLOCK (first dword = N) — NOT a bare u32 (that earlier mis-read put the channel loop out of phase)."""
    worldname = config.ENTER_WORLD_WORLDNAME if worldname is None else worldname
    if channels is None:
        channels = [(b"\x00" * 32, b"\x00" * 32)]   # one dummy (zone,id) pair — HandleEnterWorld wants N>=1
    server_perm = b"\x00" * 32 if server_perm is None else (server_perm + b"\x00" * 32)[:32]
    count_blk = struct.pack("<I", len(channels)) + b"\x00" * 28   # 32-byte MEMBLOCK, first dword = N

    body = str_field(worldname)                       # Worldname          : STRING
    body += bytes_field(server_perm)                  # ServerPerm         : MEMBLOCK 0x20
    body += bytes_field(count_blk)                    # ChatChannelsCount  : MEMBLOCK 0x20 (first dword=N)
    for zone, cid in channels:
        body += bytes_field((zone + b"\x00" * 32)[:32])   # ChatChannelZone : MEMBLOCK 0x20
        body += bytes_field((cid + b"\x00" * 32)[:32])    # ChatChannelID   : MEMBLOCK 0x20
    return body


def world_login_ack_body(code=None):
    """Body for WorldLoginAck (msg 1006). ⚠️ [HYPOTHESIS — UNVERIFIED] an older model held 1006 to be
    "THE loading-screen gate." That is CONTRADICTED by the live result: the clean magazine build renders the
    3D world at SetState(9) (after msg 1000) WITHOUT needing 1006 — so 1006 is NOT confirmed to be the render
    gate. Kept as a best-effort in-world ack; do not treat it as load-bearing. The single "code" property is a
    FIXED u32 (4 raw bytes, NO length prefix) — NOT a MEMBLOCK. s35 INDEPENDENT REVIEW (re-derived from the
    tincat3 PropertyDataConverter @0x100112B0 ser / 0x100110E0 deser + the live capture world_6): a property
    gets a 4-byte length prefix ONLY if its type ∈ {MEMBLOCK=1,STRING=2,WSTRING=3}; "code" is a fixed scalar
    (the client's OWN outbound request serialized "code"=0xAFFEDEAD to exactly 4 wire bytes, no prefix).
    HandleWorldLoginAck @0x46e8b0 reads it with ReadMemBlock(&dst, 0x20) where 0x20 is the DEST scratch-buffer
    size, NOT a wire length, and compares only the first dword to 0xDEADBEEF. A 32-byte MEMBLOCK form makes
    the client read the length prefix (0x20) as the value → 0x20 != 0xDEADBEEF → gate NEVER fires (the
    synthesis's bug, caught by the independent review before the drive)."""
    code = config.WORLD_LOGIN_ACK_CODE if code is None else code
    # ⭐ BIG-ENDIAN [PROVEN 2026-07-26] — this was a silent bug that made the 1006 gate NEVER fire, in
    # any session since the message was first implemented. The TinCat PropertyDataConverter serialises
    # integer scalars big-endian ("network order"), so:
    #   * the client's OWN 2002 wrote WriteInt(0xAFFEDEAD, 32) and it appeared on the wire as
    #     `af fe de ad` — captured byte-exact (little-endian would have been `ad de fe af`);
    #   * MEMORY.md independently records the ServerDataBlock roomId as a BIG-ENDIAN u32.
    # Writer and reader share the converter, so HandleWorldLoginAck@0x0046ec50 only sees 0xDEADBEEF if
    # we send `de ad be ef`. We were sending `ef be ad de`, which it read as 0xEFBEADDE — so the whole
    # `if (code == 0xDEADBEEF)` block (both Logout branches) was skipped every time.
    # Live evidence: a trace showed HandleWorldLoginAck ENTERED but ConnectionReal::Logout never fired,
    # while the UC transport was verifiably in state 8 (so its guard would have passed).
    return struct.pack(">I", code)                        # bare BIG-ENDIAN u32, no length prefix


def pong_body(token=b"\x00\x00\x00\x00"):
    """Body for PongCode (msg 0xED7): the "PongCode" property is a FIXED u32 (4 raw bytes, NO prefix) — the
    client's PingCode token is itself a 4-byte u32 (capture world_6). HandlePongCode @0x46be00 only times
    the round-trip (value never validated); we echo the 4-byte ping token."""
    return (bytes(token) + b"\x00\x00\x00\x00")[:4]       # bare u32 echo, no prefix


def world_tick_body(tick_ms):
    """Body for WorldTick (msg 1005): ONE positional field, "tick", read as a **64-BIT scalar**
    (NOT a 64-byte MEMBLOCK — that was a mis-read of the 0x40 argument, which is a BIT count).

    [PROVEN 2026-08-01 static] `HandleWorldTick@0x0046f620` does SelectField("tick") then reader
    vtbl+0x20 = `FUN_0048f380` → `FUN_0048f050(this, 0x40)` — the positional MSB-first bit reader
    pulling 64 bits into an 8-byte stack local. So the wire form is 8 raw big-endian bytes, no
    length prefix (same scalar rule as the proven big-endian u32s).

    ⚠️ CLIENT ENGINE BUG (shipped): `FUN_0048f050` assembles bits with a 32-bit `SHL EAX,CL` (x86
    masks CL & 0x1f) + CDQ, so for a 64-bit read the two 32-bit halves ALIAS into the low dword
    (`lo = hi_half | lo_half`) and the high dword becomes a sign-smear. Consequence: the high
    dword on the wire MUST be zero or it corrupts the value — hence `tick_ms & 0xFFFFFFFF`.
    Only the low 16 bits are consumed anyway (the clock slew, see send_world_tick)."""
    return struct.pack(">Q", int(tick_ms) & 0xFFFFFFFF)


# ── In-world presence: bit-packed LobbyMessage bodies (msgs 1001-1004) ────────────────────────
# [SPEC PROVEN 2026-07-27 static — docs/IN_WORLD_PRESENCE.md]
# The entity/avatar messages do NOT use the positional PropertySet layout the rest of village.py
# sends. They are a BIT-PACKED stream with non-byte-aligned field widths.
#
# Bit order (FUN_0048f0d0): each byte is consumed MSB-first (bit 7 down), and the value is
# assembled MSB-first, i.e. plain big-endian bit packing — the same convention that made the
# referee's 32-bit PermID exactly 4 big-endian bytes.
#
# Field NAMES are only looked up when the LobbyMessage "names" flag is set (bit 15 of the type
# word). We send names=0, so FUN_0048f5f0 skips the name entirely and reads N bits positionally —
# which is why this writer only needs widths, in order.
#
# names=0 IS REQUIRED, not merely convenient (settled statically 2026-07-29, sadk_noav.exe):
#   FUN_0048f5f0(msg, nbits, name)  gates ALL name handling on msg+0x20, then always tail-calls
#                                   FUN_0048f0d0(msg, nbits) — the pure positional bit read.
#   The name is a CALLER-SUPPLIED C string (e.g. "dtblcks"); it is never read from the wire. With
#   the flag set it is folded into a running hash at msg+0x30 (init 0x00762320 / update 0x00762350
#   / mix 0x00762400) — that hash is bookkeeping and consumes no bits.
#   BUT the finalize FUN_0048f530, called at the end of each block group, does this when the flag
#   is set:   FUN_0048f0d0(msg, 0x20)   <-- consumes a trailing 32-bit hash word off the stream.
# So sending names=1 would oblige us to append a 32-bit trailer per message; with names=0 the
# client reads exactly the bits we write and stops. Do not "fix" this to names=1 — a stale draft
# of docs/IN_WORLD_PRESENCE.md claimed that, and it would silently over-read every body by 4 bytes.
class BitWriter:
    """MSB-first bit packer. `write(value, nbits)` appends the low nbits of value, MSB first."""

    def __init__(self):
        self._bits = []

    def write(self, value, nbits):
        value = int(value) & ((1 << nbits) - 1)
        for i in range(nbits - 1, -1, -1):
            self._bits.append((value >> i) & 1)
        return self

    def write_bool(self, flag):
        return self.write(1 if flag else 0, 1)

    def write_string(self, s):
        """8-bit length + one 8-bit char each (FUN_0048ffc0). No NUL, no 32-bit prefix, and NOT
        byte-aligned — it rides the same bit stream."""
        raw = (s or "").encode("iso-8859-15", "replace")[:255]
        self.write(len(raw), 8)
        for ch in raw:
            self.write(ch, 8)
        return self

    def bytes(self):
        """Pad the final partial byte with zero bits (the reader stops at the field count)."""
        out = bytearray()
        for i in range(0, len(self._bits), 8):
            chunk = self._bits[i:i + 8]
            chunk = chunk + [0] * (8 - len(chunk))
            byte = 0
            for bit in chunk:
                byte = (byte << 1) | bit
            out.append(byte)
        return bytes(out)

    def __len__(self):
        return len(self._bits)


class BitReader:
    """MSB-first bit reader — the exact inverse of `BitWriter`, and of the client's own
    `LobbyMessage_ReadBitsCore@0x0048f050` (each byte consumed bit 7 → bit 0, value assembled
    MSB-first). Used to decode the client's inbound avatar location reports."""

    def __init__(self, data):
        self._data = data
        self._pos = 0

    def read(self, nbits):
        value = 0
        for _ in range(nbits):
            byte_i, bit_i = divmod(self._pos, 8)
            if byte_i >= len(self._data):
                raise ValueError(f"bit stream exhausted after {self._pos} bits "
                                 f"({len(self._data)}B body)")
            value = (value << 1) | ((self._data[byte_i] >> (7 - bit_i)) & 1)
            self._pos += 1
        return value

    def read_bool(self):
        return bool(self.read(1))


def dequantise_axis(raw, axis):
    """Inverse of `quantise_axis` — matches `LobbyMessage_ReadLocationBlock@0x0048f670`:
    `value = raw * (max - min) * (1/2048) + min`."""
    lo, hi = WORLD_BOUNDS[axis]
    return raw / float(POS_STEPS) * (hi - lo) + lo


def dequantise_rot(raw):
    """Inverse of `quantise_rot`: `degrees = raw * 360.0 * (1/128)`."""
    return raw * 360.0 / ROT_STEPS


def parse_avatar_location(data):
    """Decode the client's OWN avatar location report — village msg **2000** (wire msg_type 0x27D0).

    [PROVEN 2026-08-01 static] `VillageServerConnection_SendAvatarLocation_2000@0x0046ca40` builds
    a category-2 LobbyMessage id 2000 and writes, in order:
        tick 16 (`LobbyMessage_WriteShort`, value `tick | 1` — bit 0 forced set, so a tick is never 0)
        posx 11 · posy 11 · posz 11 · rot 7 · zone 4   (`LobbyMessage_WriteLocationBlock@0x0048f7e0`)
        ghstzne 4                                      (`LobbyMessage_WriteGhostZone@0x0048f980`)
        rnng 1 · jmp 1
    — i.e. **exactly the AvatarLocation block we already WRITE in `entity_create_body`**, minus the
    `id`/`dtblcks` header (the server knows the sender from the connection). Same quantisation
    constants: the writer's scaling is the mirror of `LobbyMessage_ReadLocationBlock@0x0048f670`.

    Driven by `LobbyPlayerController_Update@0x0051ace0` (the local player controller, which also
    reads the Lobby/ControllerMode·FirstPerson·TurnSpeed settings) →
    `CLobbyClient_ReportOwnAvatarLocation@0x005034e0` → this message, ~3/s while in-world.

    Returns a dict ready to hand to `send_entity_create` (`pos`, `rot_deg`, `running`, `jumping`).
    The client's own `tick` is deliberately NOT reused for the relay: waypoint stamps must straddle
    the receiver's clock, so the relay re-stamps from our own clock (see dispatch)."""
    r = BitReader(data)
    tick = r.read(16)
    pos = (dequantise_axis(r.read(11), "x"),
           dequantise_axis(r.read(11), "y"),
           dequantise_axis(r.read(11), "z"))
    rot_deg = dequantise_rot(r.read(7))
    zone = r.read(4)
    ghost_zone = r.read(4)
    running = r.read_bool()
    jumping = r.read_bool()
    return {"tick": tick, "pos": pos, "rot_deg": rot_deg, "zone": zone,
            "ghost_zone": ghost_zone, "running": running, "jumping": jumping}


# World bounds + quantisation, read from the binary (FUN_0048f670 / 2026-07-27):
#   x = posx/2048 * (BOUND_MAX_X - BOUND_MIN_X) + BOUND_MIN_X      etc.
#   rot_degrees = rot7 * 360.0 / 128
# so 11 bits span each axis and 7 bits span a full turn.
WORLD_BOUNDS = {           # axis: (min, max)  — floats at 0x87b700..0x87b714
    "x": (-150.0, 150.0),
    "y": (-10.0, 30.0),
    "z": (-150.0, 150.0),
}
POS_STEPS = 2048           # 1/2048 scale at 0x7debc8 (11 bits)
ROT_STEPS = 128            # 360.0 (0x7debc0) * 1/128 (0x7debb8) → 7 bits


def quantise_axis(value, axis):
    lo, hi = WORLD_BOUNDS[axis]
    frac = 0.0 if hi == lo else (float(value) - lo) / (hi - lo)
    return max(0, min(POS_STEPS - 1, int(round(frac * POS_STEPS))))


def quantise_rot(degrees):
    return int(round((float(degrees) % 360.0) / 360.0 * ROT_STEPS)) % ROT_STEPS


#: Field order of the AvatarStyle block (`FUN_004825f0`, dtblcks bit1). Widths are FULL BYTES here,
#: unlike PlayerCreate(1004)'s 4-bit colour nibbles — the two are different formats for different
#: kinds of entity, so do not copy widths across.
AVATAR_STYLE_COLOURS = ("hrclr", "sknclr", "shrtclr", "trsrclr",
                        "addColor1", "addColor2", "addColor3", "addColor4")


def avatar_style_block(w, name, tribe_gender=0, colours=()):
    """Append the AvatarStyle block (dtblcks bit1) to an in-progress BitWriter.

    `FUN_004825f0`, in wire order:
        name STRING · trbgndr 8 · hrclr 8 · sknclr 8 · shrtclr 8 · trsrclr 8 · addColor1..4 8 each

    `colours` supplies the eight byte-wide slots in AVATAR_STYLE_COLOURS order; short sequences are
    zero-filled. Failure to parse is reported by the client as "Could not read AvatarStyle from
    message." in LobbyComm.log.

    NOT YET SENT — `entity_create_body` still defaults to dtblcks=1 (location only). This exists so
    that adding it is a one-line change once the location-only spawn has been observed live; adding
    it before then would make a silent failure impossible to attribute to one block or the other.
    """
    vals = list(colours) + [0] * (len(AVATAR_STYLE_COLOURS) - len(colours))
    w.write_string(name)                           # "name"
    w.write(tribe_gender, 8)                       # "trbgndr" — tribe + gender packed in one byte
    for value in vals[:len(AVATAR_STYLE_COLOURS)]:
        w.write(value, 8)                          # hrclr/sknclr/shrtclr/trsrclr/addColor1..4
    return w


def entity_create_body(avatar_id, pos=(0.0, 0.0, 0.0), rot_deg=0.0, tick=0,
                       zone=0, ghost_zone=0, running=False, jumping=False,
                       style=None):
    """Body for EntityCreate (msg 1001) — the message that puts a visible AVATAR in the world.

    `HandleEntityCreate@0x0046e1d0` reads `id` (32 bits), allocates an AvatarProxy (0xE0 bytes) into
    the avatar container at VillageServerConnection+0x170 if unknown, then `FUN_00482c20` parses the
    payload and the observer fan-out tells the world about it.

    `FUN_00482c20` reads a 4-bit `dtblcks` MASK and then only the blocks it selects:
        bit0 AvatarLocation · bit1 AvatarStyle · bit2 ActiveItems · bit3 Avatar Stats
    We send **dtblcks=1** (location only) — the minimal viable avatar. Each block has its own error
    string in LobbyAvatarProxy.cpp, so a malformed one is VISIBLE in the client's LobbyComm.log
    ("Could not read AvatarLocation from message." etc.) rather than failing silently.

    AvatarLocation for a REMOTE avatar (FUN_004824b0, the `this+0xc != GetCommSystem()` branch):
        tick 16 · posx 11 · posy 11 · posz 11 · rot 7 · zone 4 · ghstzne 4 · rnng 1 · jmp 1

    `style`, when given, is a dict passed through to `avatar_style_block` and sets dtblcks bit1. It
    is OFF by default on purpose — see that function. Blocks are written in dtblcks BIT ORDER
    (location, then style), which is the order FUN_00482c20 reads them.
    """
    dtblcks = 1 | (2 if style else 0)
    w = BitWriter()
    w.write(avatar_id, 32)                     # "id"       — peeked by HandleEntityCreate
    w.write(dtblcks, 4)                        # "dtblcks"  — AvatarLocation [+ AvatarStyle]
    w.write(tick, 16)                          # "tick"
    w.write(quantise_axis(pos[0], "x"), 11)    # "posx"
    w.write(quantise_axis(pos[1], "y"), 11)    # "posy"
    w.write(quantise_axis(pos[2], "z"), 11)    # "posz"
    w.write(quantise_rot(rot_deg), 7)          # "rot"
    w.write(zone, 4)                           # "zone"
    w.write(ghost_zone, 4)                     # "ghstzne"
    w.write_bool(running)                      # "rnng"
    w.write_bool(jumping)                      # "jmp"
    if style:
        avatar_style_block(w, style.get("name", ""),
                           style.get("tribe_gender", 0),
                           style.get("colours", ()))
    return w.bytes()


# ⛔ NEVER send a short/truncated EntityCreate(1001) body — IT CRASHES THE CLIENT.
# Established 2026-07-31 by a negative-control probe (ER
# engagement_records/2026-07-31_entitycreate-negative-control.md): a 2-byte body, sent to make the
# 32-bit `id` peek fail loudly, instead killed the game process ~1.1 s later (server saw every
# connection drop at once; the player saw the window vanish with no error).
#
# ⭐ It answered the question anyway, and definitively: **an undelivered frame cannot crash
# anything**, so msg 1001 IS routed to `VillageServerConnection::HandleEntityCreate@0x0046e1d0` and
# IS parsed. Routing is NOT the problem — rendering is.
#
# It also corrects an RE assumption: the peek at stream vtbl+0x18 does **not** bounds-check against
# the buffer length, so `Can't peek AvatarID` fires on some other condition, not on "buffer too
# short". Any future probe must stay well-formed and vary only field VALUES.
def _send_village(conn, msg_type, body, magic, tag, quiet=False):
    payload = gamedata_frame(msg_type, body, magic=(magic or config.VILLAGE_PAYLOAD_MAGIC))
    conn.send_raw(build_frame(config.FROM_SERVER, conn.id, config.MSG_APPLICATION, payload))
    if not quiet:
        log(f"  → [VILLAGE] {tag} (msg {msg_type}/0x{msg_type:x}) in SendGameData(74) on conn #{conn.id} ({len(payload)}B)")


def send_enter_world(conn, magic=None, force=False):
    """Send EnterWorld (msg 1000) wrapped in a SendGameData(74) envelope on the village conn.

    The lobby-entry timer push is one-shot (force=False): it proactively enters the 3D lobby world once
    (s39, screenshot-confirmed) → HandleEnterWorld → SetState(VillageEntered=9) → JoinChannel → connState=3.
    But the client ALSO explicitly re-sends its world-login request (SendGameData(74){0x27D2}) at
    MATCH-START, and that request must ALWAYS be answered with a fresh 1000 (force=True) — otherwise the
    one-shot latch (already tripped by the lobby-entry push) swallows the reply and BOTH clients freeze
    waiting to enter the match world (live-proven match-start wall, s42 MATCH_WORLD_LOGIN; the client then
    spins re-sending 0x27D0/0x27D2). The client emits PingCodes once in-world (best-effort 1006 follows)."""
    if not conn.alive:
        return
    if not force and getattr(conn, "_enter_world_sent", False):
        return
    conn._enter_world_sent = True
    _send_village(conn, config.VILLAGE_MSG_ENTER_WORLD, enter_world_body(), magic,
                  "EnterWorld(1000) — HandleEnterWorld → SetState(9)")


def send_world_login_ack(conn, magic=None, force=False):
    """Send WorldLoginAck (msg 1006, code=0xDEADBEEF).

    [PROVEN 2026-07-26] This message is the **LOGOUT trigger**, not just an ack.
    `VillageServerConnection::HandleWorldLoginAck@0x0046ec50`, on code==0xDEADBEEF, branches on whether
    the UserComm connection is open:
      * UC OPEN   → `FUN_0047ed70` = `UserCommConnection::Logout`
      * UC CLOSED → `this->transport->vtbl[0x18]` = `ConnectionReal::Logout` on the VILLAGE transport
        → transport state 9 → on disconnect `FUN_10030ad0` case 4 takes the **state-9** branch →
        sink `OnLoggedOut` → `HandleLoggedOut` → `SetState(VillageLeft=11)` → the villageConn +0x1c
        observer → arms the referee. (The state-8 branch instead raises ConnectionLost with a
        hardcoded reason 10 = the !CONNECTION_LOST_TEXT dialog.)
    So a full leave needs TWO of these, and `force=True` bypasses the one-shot latch for the re-send.
    ER: engagement_records/2026-07-26_leave-two-phase-worldloginack.md

    ⚠️ The entry-time send (first in-world PingCode) is [VERIFIED HARMLESS 2026-07-26 by trace]: it
    reaches HandleWorldLoginAck but `ConnectionReal::Logout` never fires, because
    `UserCommConnection::Logout` is guarded on `transport->GetState()==8` and UC is not in state 8 then.
    """
    if not conn.alive or (getattr(conn, "_world_login_ack_sent", False) and not force):
        return
    conn._world_login_ack_sent = True
    _send_village(conn, config.VILLAGE_MSG_WORLD_LOGIN_ACK, world_login_ack_body(), magic,
                  f"WorldLoginAck(1006, code=0x{config.WORLD_LOGIN_ACK_CODE:08x}) → loginAckReceived=1 → loading dismissed")


def send_pong(conn, token=b"\x00\x00\x00\x00", magic=None):
    """Answer the client's in-world PingCode with a Pong (msg 0xED7) — closes the keepalive round-trip so
    the client clears its outstanding-ping marker and keeps the session healthy. Echoes the ping token
    (HandlePongCode @0x46be00 doesn't validate it; echoing just matches what a real server would do)."""
    if not conn.alive:
        return
    _send_village(conn, config.VILLAGE_MSG_PONG, pong_body(token), magic, "Pong(0xED7) keepalive")


def send_world_tick(conn, tick_ms, magic=None, quiet=False):
    """Send a WorldTick (msg 1005) — **the world-clock SYNC**, not an optional heartbeat.

    [PROVEN 2026-08-01 static + trace avatar_refresh_diag2.run] The chain:
      `HandleWorldTick@0x0046f620` (village msg 1005) reads the 64-bit "tick" field and fires the
      conn's +0x11c notify list → `CLobbyClient_OnWorldTick_Throttled@0x00503590` (subscribed at
      conn birth) → `FUN_0057b910(tick & 0xFFFF, 250)`: if the client WORLD CLOCK
      (`FUN_0057b8d0` = raw timer − offset @0x88a62c) differs in phase from the wire tick by
      ≥250 ms (shorter direction mod 65536), the offset is slewed so the clock's low 16 bits
      EQUAL the tick. That world clock is the anchor `FUN_004f4d10` reconstructs every avatar
      location tick16 against, AND the `t` the movement-ring interpolator `FUN_00519d50` runs on
      (trace-proven: Tick param == 0x88a620−0x88a62c at the call).

    So WITHOUT this message the phase between our EntityCreate tick stream and the client clock is
    ARBITRARY per machine/boot (up to ±32.7 s) — waypoint stamps land far past (>3.0 s stale →
    hidden) or far future (u64 underflow → instantly hidden). This was the round-2/3 die-off and
    the PC-vs-VM asymmetry. `tick_ms` MUST come from the same clock as the location ticks
    (dispatch._now_ms) so the slew aligns the client to OUR timebase. Call periodically; after the
    first slew the 250 ms tolerance makes further sends client-side no-ops."""
    if not conn.alive:
        return
    _send_village(conn, config.VILLAGE_MSG_WORLD_TICK, world_tick_body(tick_ms), magic,
                  f"WorldTick(1005) tick_ms={int(tick_ms) & 0xFFFFFFFF} — world-clock sync", quiet=quiet)


def send_entity_create(conn, avatar_id, pos=(0.0, 0.0, 0.0), rot_deg=0.0, tick=0, magic=None,
                       label="", style=None, quiet=False, running=False, jumping=False):
    """Spawn OR refresh a visible avatar in the recipient's lobby world (msg 1001).

    PROVEN ON THE WIRE 2026-08-01 (TTD traces avatar_spawn_diag.run / avatar_vanish_diag.run):
    the first 1001 for an id creates the avatar (CLobbyObj + visual + styled model); every LATER
    1001 for the same id takes `CLobbyClient_UpdateAvatar`'s update path, whose location block
    pushes a WAYPOINT (pos+rot+rnng/jmp, stamped tick+2000 ms) into the visual's 8-slot movement
    ring (`FUN_00519b20`). ⚠️ The per-frame interpolator (`FUN_00519d50`) positions the avatar
    EXCLUSIVELY from that ring — without periodic refreshes the ring is empty and the avatar snaps
    to (0,0,0) one frame after spawning. `tick` is the low 16 bits of an advancing ms clock; the
    client re-anchors it against its own local clock (`FUN_004f4d10`), so no absolute sync is
    needed. Waypoints with pos ≈ (0,0,0) are REJECTED by the push — never park an avatar there.

    `running`/`jumping` ride the same location block and drive the remote avatar's animation state;
    they come straight from the mover's own report (`parse_avatar_location`)."""
    if not conn.alive:
        return
    body = entity_create_body(avatar_id, pos=pos, rot_deg=rot_deg, tick=tick, style=style,
                              running=running, jumping=jumping)
    blocks = "location+style" if style else "location"
    _send_village(conn, config.VILLAGE_MSG_ENTITY_CREATE, body, magic,
                  f"EntityCreate(1001) avatar id={avatar_id} {label}"
                  f" pos=({pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f}) rot={rot_deg:.0f}°"
                  f" dtblcks={blocks} {len(body)}B"
                  f" — HandleEntityCreate → AvatarProxy into +0x170", quiet=quiet)


def entity_remove_body(avatar_id):
    """Body for EntityRemove (msg 1003) — despawn an avatar.

    `HandleEntityRemove@0x0046e570` reads **only** `id` (32 bits), looks it up in the avatar
    container at +0x170 and releases the handle. So the whole body is one big-endian dword.
    Logs "Can't read AvatarID" / "Can't find Avatar" on failure."""
    return BitWriter().write(avatar_id, 32).bytes()


def send_entity_remove(conn, avatar_id, magic=None, label=""):
    """Remove a previously spawned avatar from this client's world (msg 1003)."""
    if not conn.alive:
        return
    _send_village(conn, config.VILLAGE_MSG_ENTITY_REMOVE, entity_remove_body(avatar_id), magic,
                  f"EntityRemove(1003) avatar id={avatar_id} {label}")


def handle_frame(conn, payload):
    """Raw-frame capture for the village conn (hex log while we RE the in-world protocol). The actual
    world-entry trigger (SendGameData(74){msg_type=0x27D2} → reply EnterWorld(1000)) is handled in
    dispatch._h_send_game_data after the codec decodes the frame; this is the verbatim capture hook."""
    if len(payload) >= 6:
        magic, t1, t2 = struct.unpack_from("<HHH", payload, 0)
        log(f"  [VILLAGE] ← app frame  magic=0x{magic:04x}  type1={t1}  type2={t2}  ({len(payload)}B)")
    else:
        log(f"  [VILLAGE] ← runt app frame ({len(payload)}B)")
    log(hex_dump(payload))
