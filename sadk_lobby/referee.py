"""
Referee / match-arbiter sub-protocol — LobbyComm::RefereeServerConnection (.\\LobbyRefereeServerConnection.cpp).

The match-START gate. On every NE_StartLoading the client arms a referee login (LM+0x3625=1) and the
per-frame loop calls RefereeServerConnection::Login (FUN_004793f0) up to 5x ([Reconnector]
timesClientRetries) then ABORTS the match. The referee is the ranked-match arbiter — a trusted third
connection that watches the P2P game so a rage-quitting host can't dodge a loss. Our stub previously ran
lobby/UC/world but NO referee, so every match aborted. Full RE: docs/REFEREE_RE_findings.json +
memory/mp-match-start-needs-referee-server.md (binary-PROVEN, build 34688).

WIRE FORMAT (referee-server-re workflow):
  * The referee rides the SINGLE 0x26B6 TinCat comm layer (28-byte frame header), like lobby/UC/village.
  * Its bodies are BARE LobbyMessages (tincat3 PropertyDataConverter), NOT msgdefs NETMSGs and NOT the
    village SendGameData(74) envelope. The inbound demux routes by connId to the referee router FUN_0047b090,
    which reads a 16-bit TYPE WORD then the fields.
  * TYPE WORD = (names_flag<<15) | (category<<12) | id.  category=3 for all referee msgs.
    LoginSuccess id=0xDCA → 0x3DCA (names off) / 0xBDCA (names on). LoginFail id=0xDCB (NEVER send).
  * Field bodies mirror the village PropertySet convention already in village.py: positional values, all
    32-bit ints byte-aligned LE (names off = no names/tags/end-marker). MEMBLOCK/STRING get a u32 length
    prefix. (LoginSuccess + RegisterGame ack/result are all u32 → byte-aligned, so the BitStream's sub-byte
    packing never bites here.)
  * On the wire each frame mirrors Type1==Type2 (Magic | typeWord | typeWord | body), like every other msg
    on this comm layer; tincat.app_payload(typeWord, body) produces exactly that.

⚠ ONE byte-level UNKNOWN (statically undetermined → see config.REF_LOGIN_SUCCESS_NAMES): the names_flag
(bit15). names-off (default, the client's own send-side convention) = a bare u32 PermID. The genuine
verdict is the MESSAGE ID (0xDCA), not any value — FUN_0047ac20 reads PermID but never validates it. So
LoginSuccess(0xDCA) clears the 5x-retry abort regardless of the PermID value; only the framing must match.
"""
import struct

from . import config
from .log import hex_dump, log
from .tincat import app_payload, bytes_field, build_frame, str_field


def type_word(msg_id, names=False, category=None):
    """16-bit referee LobbyMessage type word = names<<15 | category<<12 | id."""
    cat = config.REF_CATEGORY if category is None else category
    return ((1 if names else 0) << 15) | ((cat & 7) << 12) | (msg_id & 0xFFF)


def _u32(v):
    return struct.pack("<I", v & 0xFFFFFFFF)


def _named_u32(name, value):
    """[UNCONFIRMED FALLBACK] names-ON field encoding: NAME string + type-tag(1) + width(0x20) + value.
    The exact bit-stream form (and the trailing 0xFFF end-marker) is NOT byte-confirmed — used only when
    REF_LOGIN_SUCCESS_NAMES=True, after names-off is observed to fail. names-off is the primary bet."""
    return str_field(name) + struct.pack("<II", 1, 0x20) + _u32(value)


def _end_marker():
    """[UNCONFIRMED] names-ON bodies end with a 0xFFF property-id end-marker (workflow). Best-effort u16."""
    return struct.pack("<H", 0xFFF)


def _frame(tw, body):
    """Build the on-wire app-payload for a referee LobbyMessage with type word `tw` and field `body`.

    DEFAULT (config.REF_USE_GAMEDATA_ENVELOPE): wrap it in a SendGameData(74) envelope so tincat3 deserializes
    the REGISTERED 74 NETMSG (a bare cat-3 frame instead crashed in CreatePropertySet(0x3dca)→NULL, s39.6).
    The referee conn's OnData (referee_conn vtbl[0x24]) builds an NCore::BitStream over the 74's data MEMBLOCK
    and `FUN_0047b090`→`FUN_0048fa50(msg, typeWord)` reads the **type word FIRST from that BitStream, THEN the
    fields** — UNLIKE the village conn, which takes the type word from the 74's msg_type. s39.6 LIVE: a wrap
    with data=MEMBLOCK(fields-only) didn't crash but the client read PermID's low 16 bits as the type word
    (0x0001 → not a referee id) → dropped → 5 Login retries → abort (comm.log Manager.cpp:889). So the LobbyMessage
    on the wire = [type word(u16) + fields] INSIDE the MEMBLOCK. Wire: Magic|74|74|msg_type=tw(u32)|MEMBLOCK([tw_u16|fields]).
    Robust to a u16 OR u32 read of the type word (cat/id are the low 16 bits) and PermID's value is never validated.
    Flag OFF = the old crashing bare form, for diagnostics only."""
    if config.REF_USE_GAMEDATA_ENVELOPE:
        lobbymsg = struct.pack("<H", tw & 0xFFFF) + body   # [type word(u16) | fields] = what OnData/FUN_0047b090 reads
        return app_payload(config.VILLAGE_SENDGAMEDATA, struct.pack("<I", tw) + bytes_field(lobbymsg))
    return app_payload(tw, body)


def build_login_success(perm_id, names=None):
    """LoginSuccess (id 0xDCA) — the message the match-start gate waits for. One field: PermID(u32). The
    client clears the gate on the message ID, not the value."""
    names = config.REF_LOGIN_SUCCESS_NAMES if names is None else names
    body = (_named_u32("PermID", perm_id) + _end_marker()) if names else _u32(perm_id)
    return _frame(type_word(config.REF_LOGIN_OK, names), body)


def build_register_game_ack(game_id, result=0, names=None):
    """RegisterGameAck (0xDB7): GameID(u32), Result(u32; 0=ok)."""
    names = config.REF_LOGIN_SUCCESS_NAMES if names is None else names
    if names:
        body = _named_u32("GameID", game_id) + _named_u32("Result", result) + _end_marker()
    else:
        body = _u32(game_id) + _u32(result)
    return _frame(type_word(config.REF_REGISTER_ACK, names), body)


def build_register_game_result(game_id, result=0, game_seed=None, names=None):
    """RegisterGameResult (0xDB8): GameID(u32), Result(u32; 0=ok), GameSeed(u32). FUN_0047a580 reads
    GameSeed only when Result==0 → success fan-out; non-zero Result reads a FailReason → abort. So we
    always send Result=0 + a fixed GameSeed (the value is never validated)."""
    game_seed = config.REF_GAME_SEED if game_seed is None else game_seed
    names = config.REF_LOGIN_SUCCESS_NAMES if names is None else names
    if names:
        body = (_named_u32("GameID", game_id) + _named_u32("Result", result)
                + _named_u32("GameSeed", game_seed) + _end_marker())
    else:
        body = _u32(game_id) + _u32(result) + _u32(game_seed)
    return _frame(type_word(config.REF_REGISTER_RESULT, names), body)


# ── send + receive ────────────────────────────────────────────────────────────
def _send(conn, frame_payload, tag):
    conn.send_raw(build_frame(config.FROM_SERVER, conn.id, config.MSG_APPLICATION, frame_payload))
    log(f"  → [REFEREE] {tag} on conn #{conn.id} ({len(frame_payload)}B)")


def push_login_success(conn):
    """PUSH LoginSuccess(0xDCA). ⚠ s41.8 — THIS IS A HACK THAT DOES NOT WORK. It lands on a SIDE-EFFECT
    :5481 socket, NOT the match-start gate's RefereeServerConnection. That conn needs LM+0x580, which is
    NEVER set on the client: SetRefereeServerAddress@0x4625d0 (the sole LM+0x580 writer) fires only via
    tincat3 OnGameServerAssigned@0x10021520, reachable only from the SERVER recv handler the game never
    runs. With ARM_REFEREE=True the push fires yet the match STILL aborts (~13s ShutDown) — proof it does
    nothing. Keep ARM_REFEREE=False. See docs/REFEREE_ASSIGN_client_vs_server.md +
    memory/mp-match-start-needs-referee-server.md (s41.8). Idempotent; gated by config.ARM_REFEREE."""
    if not conn.alive or getattr(conn, "_ref_login_pushed", False):
        return
    conn._ref_login_pushed = True
    perm_id = getattr(getattr(conn, "player", None), "perm_id", config.TEST_PERM_ID)
    tw = type_word(config.REF_LOGIN_OK, config.REF_LOGIN_SUCCESS_NAMES)
    _send(conn, build_login_success(perm_id),
          f"*** LoginSuccess(0xDCA, perm_id={perm_id}, typeWord=0x{tw:04x}, "
          f"names={'ON' if config.REF_LOGIN_SUCCESS_NAMES else 'off'}) — should clear the 5x-retry match-start abort ***")


def handle_frame(conn, payload):
    """Capture + parse a referee LobbyMessage (client→referee). Verbatim hex-log (like village.handle_frame
    — this is the Part-A capture that reveals the client's referee framing), then answer the mandatory
    match-start messages. RegisterGame(0xDB6) → Ack(0xDB7,0) + Result(0xDB8,0,GameSeed); end-of-match msgs
    are logged (acks deferred)."""
    if len(payload) < 4:
        log(f"  [REFEREE] ← runt frame ({len(payload)}B)")
        return
    magic, t1 = struct.unpack_from("<HH", payload, 0)
    pos = 4
    if len(payload) >= 6 and struct.unpack_from("<H", payload, 4)[0] == t1:
        pos = 6                                   # mirrored Type2 consumed
    msg_id = t1 & 0xFFF
    cat = (t1 >> 12) & 7
    names = (t1 >> 15) & 1
    log(f"  [REFEREE] ← frame magic=0x{magic:04x} typeWord=0x{t1:04x} "
        f"(cat={cat} id=0x{msg_id:x} names={names}) {len(payload)}B")
    log(hex_dump(payload))
    body = payload[pos:]

    if msg_id == config.REF_REGISTER_GAME:
        game_id = struct.unpack_from("<I", body, 0)[0] if len(body) >= 4 else 0
        log(f"  [REFEREE] RegisterGame(0xDB6) GameID={game_id} → Ack(0xDB7,0) + Result(0xDB8,0,GameSeed=0x{config.REF_GAME_SEED:x})")
        _send(conn, build_register_game_ack(game_id), "RegisterGameAck(0xDB7, Result=0)")
        _send(conn, build_register_game_result(game_id), "RegisterGameResult(0xDB8, Result=0, GameSeed)")
    elif msg_id in (config.REF_FINISH_GAME, config.REF_GIVEUP_GAME, config.REF_CLAIM_CHEST):
        log(f"  [REFEREE] end-of-match msg 0x{msg_id:x} — logged (ack deferred; not on the start path)")
    else:
        log(f"  [REFEREE] msg 0x{msg_id:x} (cat={cat}) — logged, no handler yet")
