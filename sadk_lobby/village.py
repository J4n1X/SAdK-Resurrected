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
     server would answer. In practice that client path is **dormant/dead** (no analyzed caller fires it;
     force_send2002.py was a HACK to poke it) — so the stub does NOT wait for it; it pushes 1000 instead.
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
    return struct.pack("<I", code)                        # bare u32; the gate compares THIS dword to 0xDEADBEEF


def pong_body(token=b"\x00\x00\x00\x00"):
    """Body for PongCode (msg 0xED7): the "PongCode" property is a FIXED u32 (4 raw bytes, NO prefix) — the
    client's PingCode token is itself a 4-byte u32 (capture world_6). HandlePongCode @0x46be00 only times
    the round-trip (value never validated); we echo the 4-byte ping token."""
    return (bytes(token) + b"\x00\x00\x00\x00")[:4]       # bare u32 echo, no prefix


def world_tick_body():
    """Body for WorldTick (msg 1005): a 64-byte "tick" MEMBLOCK (HandleWorldTick @0x46f420 reads via the
    reader's WIDE slot vtable+0x20, len 0x40). A zero clock is fine for a stub heartbeat. OPTIONAL — held
    OFF for the first isolated drive of the 1006 gate (see dispatch._h_send_game_data)."""
    return bytes_field(b"\x00" * 64)


def _send_village(conn, msg_type, body, magic, tag):
    payload = gamedata_frame(msg_type, body, magic=(magic or config.VILLAGE_PAYLOAD_MAGIC))
    conn.send_raw(build_frame(config.FROM_SERVER, conn.id, config.MSG_APPLICATION, payload))
    log(f"  → [VILLAGE] {tag} (msg {msg_type}/0x{msg_type:x}) in SendGameData(74) on conn #{conn.id} ({len(payload)}B)")


def send_enter_world(conn, magic=None):
    """Send EnterWorld (msg 1000) wrapped in a SendGameData(74) envelope on the village conn — exactly
    once. Drives HandleEnterWorld → SetState(VillageEntered=9) → JoinChannel → connState=3; on the clean
    build this alone renders the 3D world (s39, screenshot-confirmed). The client then emits its first
    PingCode (we follow with a best-effort WorldLoginAck(1006); its render role is UNVERIFIED — see above)."""
    if not conn.alive or getattr(conn, "_enter_world_sent", False):
        return
    conn._enter_world_sent = True
    _send_village(conn, config.VILLAGE_MSG_ENTER_WORLD, enter_world_body(), magic,
                  "EnterWorld(1000) — HandleEnterWorld → SetState(9)")


def send_world_login_ack(conn, magic=None):
    """Send WorldLoginAck (msg 1006, code=0xDEADBEEF). ⚠️ [HYPOTHESIS — UNVERIFIED] previously believed to be
    THE loading-screen gate ("without it the client sits on the loading screen forever"); the clean build
    renders at SetState(9) without it, so that claim is NOT verified. Sent once, on the client's first
    in-world PingCode (by which point HandleEnterWorld has fully run: JoinChannel done, connState=3), as a
    best-effort in-world ack — not as a proven render trigger."""
    if not conn.alive or getattr(conn, "_world_login_ack_sent", False):
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


def send_world_tick(conn, magic=None):
    """Send a WorldTick (msg 1005) — the in-world sim heartbeat (NOT one-shot; call periodically). OPTIONAL:
    held OFF for the first isolated drive of the 1006 gate so a render-gate failure isn't conflated with a
    missing clock. Enable once 1006 is confirmed to dismiss the loading screen."""
    if not conn.alive:
        return
    _send_village(conn, config.VILLAGE_MSG_WORLD_TICK, world_tick_body(), magic, "WorldTick(1005)")


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
