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

from . import config, rewards
from .log import hex_dump, log
from .tincat import app_payload, bytes_field, build_frame


def type_word(msg_id, names=False, category=None):
    """16-bit referee LobbyMessage type word = names<<15 | category<<12 | id."""
    cat = config.REF_CATEGORY if category is None else category
    return ((1 if names else 0) << 15) | ((cat & 7) << 12) | (msg_id & 0xFFF)


def _u32le(v):
    """TinCat BODY scalar — little-endian. Used for the SendGameData(74) msg_type/type word, which
    tincat3 parses as a normal body field (village.py does the same: struct.pack('<I', msg_type))."""
    return struct.pack("<I", v & 0xFFFFFFFF)


def _u32(v):
    """LobbyMessage FIELD scalar — ⚠️ BIG-endian.

    [PROVEN LIVE 2026-07-27] The fields inside the MEMBLOCK are read big-endian, exactly like the
    village's WorldLoginAck code (village.py: `struct.pack('>I', code)  # bare BIG-ENDIAN u32`).
    This was originally packed little-endian, and it cost a full live drive to find: our PermID=1
    went out as bytes 01 00 00 00 and RefereeServerConnection_OnLoginSuccess read it as
    0x01000000 (16777216). Measured at the guard (0047ad09) in ref_loginok.run:
        eax = 00000001            <- LobbyManager+0x54c, the expected perm id
        [esp+0x10] = 0x01000000   <- what our little-endian field decoded to
        efl 0x246 -> 0x216        <- ZF CLEARED, so the JNZ was taken
    OnLoginSuccess ran (1 call) but returned silently before the +0x80 fan-out, which is why
    RegisterGame(0xDB6) never came and nothing appeared in any log."""
    return struct.pack(">I", v & 0xFFFFFFFF)


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
    body = _u32le(type_word(msg_id)) + bytes_field(fields)   # channel/type word: LITTLE-endian
    return app_payload(config.VILLAGE_SENDGAMEDATA, body)    # fields inside the MEMBLOCK: BIG-endian


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


def build_giveup_ack(game_id, result=0):
    """GiveUpGameAcknowledge (0xDD5): GameID(u32), Result(u32).

    GameID MUST echo the request's — a mismatch is a silent no-op and the client stays on
    "Finalizing". Result 0..20 only: 1..20 index the ERefereeResult name table (S 0046b3d0), and
    ≥21 yields a NULL name the client dereferences (crash). Both 0 and a failure code run the same
    exit (referee logout, then the main screen). [known, S 0047ae80]"""
    if not 0 <= result <= 20:
        raise ValueError(f"GiveUpGameAcknowledge result {result} outside 0..20 crashes the client")
    return referee_payload(config.REF_GIVEUP_ACK, _u32(game_id) + _u32(result))


def build_finish_ack(game_id, result=0):
    """FinishGameAcknowledge (0xDC1): GameID(u32), Result(u32; 0 → logged). [known, S 0047a810]"""
    return referee_payload(config.REF_FINISH_ACK, _u32(game_id) + _u32(result))


def build_finish_result(game_id):
    """FinishGameResult (0xDC2): GameID(u32), Result(u32)=0. A FailReason string follows only when
    Result ≠ 0, so with 0 it must NOT be sent. [known, S 0047a9c0]"""
    return referee_payload(config.REF_FINISH_RESULT, _u32(game_id) + _u32(0))


def build_claim_ack(game_id):
    """ClaimChestAcknowledge (0xDAD): GameID(u32), Result(u32) — ALWAYS 0. A non-zero Result fires
    the RegisterGame-failure list (+0x5c): with the WorldScreen up that shows REGISTER_GAME_FAILED
    and tears the referee session down. [known, S 00479fb0 / disasm 0047a0ff]"""
    return referee_payload(config.REF_CLAIM_ACK, _u32(game_id) + _u32(0))


def build_claim_result(avatar_id, chest_id, text=b""):
    """ClaimChestResult (0xDAE): AvatarID(u32; 0 = denied), ChestID(u32), Text(u8 length + bytes,
    always present). No Result field. [known, S 00479fb0, push order verified at 0047a2b0]"""
    text = text[:255]
    return referee_payload(config.REF_CLAIM_RESULT,
                           _u32(avatar_id) + _u32(chest_id) + bytes([len(text)]) + text)


# ── Match-end state (server decisions, docs/message-catalog.md H19 / H22) ────────
# Chest ownership per game: the FIRST claimant of a chest gets it, and every later claim of the same
# chest is answered with that same winner, so all clients agree on who holds it. (H22; the client
# accepts any non-zero AvatarID as success.)
_chest_owner = {}            # (game_id, chest_id) -> avatar_id
# FinishGame reports per game: every client that evaluates victory sends one. (H19: accept every
# report; the winner is recorded when they agree — the client does not care, this is for the log.)
_finish_reports = {}         # game_id -> {perm_id: winner}


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
def _inner(payload):
    """Split an inbound referee app frame into (msg_id, field bytes). The referee channel rides
    SendGameData(74): Magic|74|74|typeWord(u32)|MEMBLOCK(fields). The id lives in the typeWord u32,
    NOT inside the MEMBLOCK — see referee_payload() for the binary proof. Returns (None, b"") if it
    isn't a referee frame (e.g. a base-login NETMSG the lobby dispatch owns)."""
    if len(payload) < 14:
        return None, b""
    magic, t1, t2 = struct.unpack_from("<HHH", payload, 0)
    if magic != config.PAYLOAD_MAGIC or t1 != config.VILLAGE_SENDGAMEDATA or t2 != t1:
        return None, b""                                    # not a 74 envelope → base-login/other
    tw = struct.unpack_from("<I", payload, 6)[0]             # typeWord = names<<15|cat<<12|id (LE)
    blen = struct.unpack_from("<I", payload, 10)[0]
    return tw & 0xFFF, payload[14:14 + blen]


def _field_u32(inner, byte_off):
    """A byte-aligned 32-bit field of the MSB-first bit stream (= big-endian), or 0 if absent."""
    return struct.unpack_from(">I", inner, byte_off)[0] if len(inner) >= byte_off + 4 else 0


def _inner_msg_id(payload):
    """(msg_id, GameID) of an inbound referee frame; GameID is the first field of every client →
    referee message (RegisterGame, FinishGame, GiveUpGame, ClaimChest)."""
    msg_id, inner = _inner(payload)
    return (None, None) if msg_id is None else (msg_id, _field_u32(inner, 0))


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

    me = getattr(getattr(conn, "player", None), "perm_id", 0)
    if msg_id == config.REF_REGISTER_GAME:
        rewards.match_started(game_id, me)                  # the player's match clock starts
        log(f"  [REFEREE] RegisterGame(0xDB6) GameID={game_id} → Ack(0xDB7,0) + Result(0xDB8,0,"
            f"GameSeed=0x{config.REF_GAME_SEED:x})")
        _send(conn, build_register_game_ack(game_id), "RegisterGameAck(0xDB7, Result=0)")
        _send(conn, build_register_game_result(game_id), "RegisterGameResult(0xDB8, Result=0, GameSeed)")
    elif msg_id == config.REF_GIVEUP_GAME:
        # GiveUpGame: GameID(32), MapGUID(128). The client shows "Finalizing..." and may resend every
        # frame until a matching 0xDD5 arrives, so answering every repeat is correct.
        log(f"  [REFEREE] GiveUpGame(0xDD4) GameID={game_id} → GiveUpGameAcknowledge(0xDD5, Result=0)")
        rewards.match_finished(game_id, me, won=False)      # once; repeats find no running match
        _send(conn, build_giveup_ack(game_id), f"GiveUpGameAcknowledge(0xDD5, GameID={game_id}, Result=0)")
    elif msg_id == config.REF_FINISH_GAME:
        # FinishGame: GameID(32), MapGUID(128), MapSettings(u8 len + 3 digits), Winner(32).
        # Every client that evaluates victory sends one, so N per match (H19: accept all).
        _, inner = _inner(payload)
        settings_len = inner[20] if len(inner) > 20 else 0
        winner = _field_u32(inner, 21 + settings_len)
        perm = getattr(getattr(conn, "player", None), "perm_id", 0)
        reports = _finish_reports.setdefault(game_id, {})
        reports[perm] = winner
        agree = len(set(reports.values())) == 1
        log(f"  [REFEREE] FinishGame(0xDC0) GameID={game_id} from perm {perm}: winner={winner} "
            f"({len(reports)} report(s), {'agreeing' if agree else 'DISAGREEING: ' + str(reports)})")
        _send(conn, build_finish_ack(game_id), f"FinishGameAcknowledge(0xDC1, GameID={game_id}, Result=0)")
        _send(conn, build_finish_result(game_id), f"FinishGameResult(0xDC2, GameID={game_id}, Result=0)")
        rewards.match_finished(game_id, perm, won=(winner == perm))
    elif msg_id == config.REF_CLAIM_CHEST:
        # ClaimChest: GameID(32), MapGUID(128 raw), ActorID(32), ChestID(32) — byte-aligned.
        _, inner = _inner(payload)
        actor_id, chest_id = _field_u32(inner, 20), _field_u32(inner, 24)
        claimant = getattr(getattr(conn, "player", None), "perm_id", 0) or actor_id
        first = (game_id, chest_id) not in _chest_owner
        owner = _chest_owner.setdefault((game_id, chest_id), claimant)
        if first:
            rewards.grant_chest(owner, f"chest {chest_id} in match {game_id}", game_id)
        log(f"  [REFEREE] ClaimChest(0xDAC) GameID={game_id} chest={chest_id} actor={actor_id} "
            f"claimant={claimant} → owner {owner}{' (first claim)' if owner == claimant else ' (already claimed)'}")
        _send(conn, build_claim_ack(game_id), f"ClaimChestAcknowledge(0xDAD, GameID={game_id}, Result=0)")
        _send(conn, build_claim_result(owner, chest_id),
              f"ClaimChestResult(0xDAE, AvatarID={owner}, ChestID={chest_id})")
    else:
        log(f"  [REFEREE] msg 0x{msg_id:x} — logged, no handler yet")
    return True
