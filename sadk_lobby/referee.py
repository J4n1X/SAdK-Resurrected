"""
Referee / match-arbiter sub-protocol — LobbyComm::RefereeServerConnection.

The match-START gate. Reverse-engineered fresh this session on sadk_noav.exe (docs/MATCH_START.md):

  * The referee is a separate TinCat connection (the client dials config.REFEREE_PORT) on the SAME
    single 0x26B6 comm layer as lobby/UC/village. It does the SAME base login as the others
    (CheckVersion 188 → token 211/213 → AddResult 153), answered by the existing dispatch handlers.
  * Inbound is routed by LobbyManager::DispatchInboundToConnection@0x462760 to the referee conn's
    vtbl[0x24] = RefereeServerConnection_OnReceive@0x47b090, which builds a LobbyMessage
    (LobbyMessage_InitFromWire), reads its msg id, and switches — EXACTLY like the village
    HandleMessage@0x470a90. So referee bodies are LobbyMessages, category 3.
  * type word = (names<<15) | (category<<12) | id ; category 3, names off → e.g. LoginSuccess
    0xDCA → 0x3DCA. Fields are positional u32s (no names/tags); MEMBLOCK/STRING get a u32 length prefix.

The two things the stub must do to start a match:
  1. LoginSuccess(0xDCA) — clears the client's 5-retry match-start abort. NEVER send LoginFailed(0xDCB).
     ⚠️ The PermID field IS validated. An earlier version of this note claimed it was not; that was
     wrong and it is load-bearing. RefereeServerConnection_OnLoginSuccess@0x0047ac20:
         0047acbf  MOV EDX,[0x007db510]   ; local = INVALID sentinel (measured 0)
         0047ace1  CALL 0x0048f490        ; SelectField(msg,"PermID")   name string @0x7dc6f0
         0047acf4  CALL EDX               ; read 32 bits into the local
         0047ad04  CALL 0x00462510        ; returns LobbyManager+0x54c (the user's own perm id)
         0047ad09  CMP  [ESP+0x10],EAX
         0047ad0d  JNZ  skip              ; mismatch → returns SILENTLY: no log, no error
         0047ad15  CALL 0x00479ef0        ; +0x80 fan-out → Lobby_HostRegisterGameWithReferee
     So PermID must equal THAT client's perm_id (measured: test=1, test2=2). A constant would work
     for one player and silently fail for the other.
     ⚠️ Nothing on the wire requests this message: RefereeServerConnection::Login@0x004793f0 sends
     NO message, it only opens the channel. The server must PUSH LoginSuccess when the referee
     conn's base login completes (the 153) — see dispatch._h_send_token. The old trigger below (on
     the first inbound referee-channel frame) could never fire, because the client sends none.
  2. For the host's RegisterGame(0xDB6): RegisterGameAck(0xDB7, Result=0) then
     RegisterGameResult(0xDB8, Result=0, GameSeed). OnRegisterGameResult reads GameSeed only when
     Result==0 (else it reads a FailReason and aborts). The GameSeed is the lockstep determinism seed —
     without it the sim cannot start; all clients in a match must get the SAME seed (fixed is fine).

FRAMING [VERIFY LIVE]: like the village conn, the referee LobbyMessage rides a SendGameData(74)
envelope, with the LobbyMessage ([type word(u16) | fields]) carried INSIDE the 74's data MEMBLOCK
(the inbound BitStream reads the type word from there first, then the fields). This is the model the
prior (removed) attempt converged on after live tests; re-confirm it against the real client.
"""
import struct

from . import config
from .log import hex_dump, log
from .tincat import app_payload, bytes_field, build_frame


def type_word(msg_id, names=False, category=None):
    """16-bit referee LobbyMessage type word = names<<15 | category<<12 | id."""
    cat = config.REF_CATEGORY if category is None else category
    return ((1 if names else 0) << 15) | ((cat & 7) << 12) | (msg_id & 0xFFF)


def _u32(v):
    return struct.pack("<I", v & 0xFFFFFFFF)


def referee_payload(msg_id, fields=b""):
    """App-payload for a referee LobbyMessage:
        Magic | 74 | 74 | typeWord(u32) | MEMBLOCK(fields ONLY)

    ⚠️ The MEMBLOCK carries the FIELDS ONLY — the type word must NOT be repeated inside it.
    [PROVEN 2026-07-27] RefereeServerConnection_OnReceive is invoked as vtbl[0x24](channel,
    &bitStream) by LobbyManager::DispatchInboundToConnection@0x00462760, and passes those straight
    to LobbyMessage_InitFromWire@0x0048fa50(this, typeWord, byteBuffer):
        *(this+0x20) = (typeWord >> 15) & 1     ; names flag
        *(this+0x24) = (typeWord >> 12) & 7     ; category
        *(this+0x28) = typeWord & 0xfff         ; ID  <- from the ARGUMENT, not the buffer
        *(this+0x08) = *(byteBuffer+4)          ; field data ptr
        *(this+0x0c) = *(byteBuffer+8)          ; field data length
    i.e. the id comes from the u32 channel and the buffer is pure field data — exactly like the
    village envelope (village.py builds u32(msg_type) + bytes_field(fields)).

    The first implementation duplicated the type word as a u16 at the head of the MEMBLOCK. That
    frame was ACCEPTED and silently ignored: OnLoginSuccess read PermID off the front of the buffer
    and got 0x00013DCA (type word + low half of perm_id 1) instead of 1, so the guard at
    0047ad09 mismatched and returned with no log. Measured live 2026-07-27 — both referee sockets
    stayed open and nothing came back.
    """
    body = _u32(type_word(msg_id)) + bytes_field(fields)
    return app_payload(config.VILLAGE_SENDGAMEDATA, body)


# ── Builders (referee → client) ────────────────────────────────────────────────
def build_login_success(perm_id):
    """LoginSuccess (0xDCA) — one field PermID(u32). The client clears the match-start gate on the
    message ID, not the value."""
    return referee_payload(config.REF_LOGIN_OK, _u32(perm_id))


def build_register_game_ack(game_id, result=0):
    """RegisterGameAck (0xDB7): GameID(u32), Result(u32; 0=ok)."""
    return referee_payload(config.REF_REGISTER_ACK, _u32(game_id) + _u32(result))


def build_register_game_result(game_id, result=0, game_seed=None):
    """RegisterGameResult (0xDB8): GameID(u32), Result(u32; 0=ok), GameSeed(u32). Always Result=0 so the
    client takes the success path and reads the seed."""
    game_seed = config.REF_GAME_SEED if game_seed is None else game_seed
    return referee_payload(config.REF_REGISTER_RESULT, _u32(game_id) + _u32(result) + _u32(game_seed))


# ── Send helpers ────────────────────────────────────────────────────────────────
def _send(conn, payload, tag):
    conn.send_raw(build_frame(config.FROM_SERVER, conn.id, config.MSG_APPLICATION, payload))
    log(f"  → [REFEREE] {tag} on conn #{conn.id} ({len(payload)}B)")


def send_login_success(conn):
    """Push LoginSuccess(0xDCA) once — the message the match-start gate waits for."""
    if not conn.alive or getattr(conn, "_ref_login_sent", False):
        return
    conn._ref_login_sent = True
    perm_id = getattr(getattr(conn, "player", None), "perm_id", config.TEST_PERM_ID)
    _send(conn, build_login_success(perm_id),
          f"LoginSuccess(0xDCA, perm_id={perm_id}) — should clear the 5-retry match-start abort")


# ── Receive (client → referee) ───────────────────────────────────────────────────
def _inner_msg_id(payload):
    """Extract the referee LobbyMessage id from an inbound app frame. The referee channel rides
    SendGameData(74): Magic|74|74|typeWord(u32)|MEMBLOCK(fields). The id lives in the typeWord u32,
    NOT inside the MEMBLOCK — see referee_payload() for the binary proof. Returns (msg_id, game_id),
    or (None, None) if it isn't a referee frame (e.g. a base-login NETMSG the lobby dispatch owns)."""
    if len(payload) < 14:
        return None, None
    magic, t1, t2 = struct.unpack_from("<HHH", payload, 0)
    if magic != config.PAYLOAD_MAGIC or t1 != config.VILLAGE_SENDGAMEDATA or t2 != t1:
        return None, None                                   # not a 74 envelope → base-login/other
    tw = struct.unpack_from("<I", payload, 6)[0]             # typeWord = names<<15|cat<<12|id
    msg_id = tw & 0xFFF
    blen = struct.unpack_from("<I", payload, 10)[0]
    inner = payload[14:14 + blen]
    game_id = struct.unpack_from("<I", inner, 0)[0] if len(inner) >= 4 else 0
    return msg_id, game_id


def handle_frame(conn, payload):
    """Capture + answer referee-channel frames (client → referee). Base-login NETMSGs fall through to
    the lobby dispatch (they return (None,...) here). On the first referee-channel frame the client
    sends after login (the channel open), push LoginSuccess; on RegisterGame(0xDB6) push Ack + Result.

    Returns True if it consumed a referee-channel frame (caller must NOT fall through to the lobby/village
    dispatch), False for a base-login NETMSG (caller falls through so the existing handlers do the login).

    [VERIFY LIVE] The LoginSuccess trigger (when exactly the client opens the referee channel) and the
    inbound framing are not yet live-confirmed on this build — the verbatim hex log below is the capture
    that will show the real sequence on the first hosted-match drive."""
    msg_id, game_id = _inner_msg_id(payload)
    if msg_id is None:
        return False                                        # base login / non-referee frame → dispatch

    log(f"  [REFEREE] ← channel frame msg=0x{msg_id:x} game_id={game_id} ({len(payload)}B)")
    log(hex_dump(payload))

    # The client opening the referee channel is the cue for the verdict. Send LoginSuccess on the first
    # channel frame (idempotent), then handle the specific message.
    send_login_success(conn)

    if msg_id == config.REF_REGISTER_GAME:
        log(f"  [REFEREE] RegisterGame(0xDB6) GameID={game_id} → Ack(0xDB7,0) + Result(0xDB8,0,"
            f"GameSeed=0x{config.REF_GAME_SEED:x})")
        _send(conn, build_register_game_ack(game_id), "RegisterGameAck(0xDB7, Result=0)")
        _send(conn, build_register_game_result(game_id), "RegisterGameResult(0xDB8, Result=0, GameSeed)")
    elif msg_id in (config.REF_FINISH_GAME, config.REF_GIVEUP_GAME, config.REF_CLAIM_CHEST):
        log(f"  [REFEREE] end-of-match msg 0x{msg_id:x} — logged (ack deferred; not on the start path)")
    else:
        log(f"  [REFEREE] msg 0x{msg_id:x} — logged, no handler yet")
    return True
