"""
Referee / match-arbiter server tests (s39.5) — codec golden + dispatch smoke. No live game, no sockets.

Proves:
  1. The referee LobbyMessage codec (type word = names<<15|cat<<12|id; positional u32 bodies) is byte-stable.
  2. With config.ADVERTISE_REFEREE_SERVER OFF (default) every AssignServer(189) still replies 192
     (byte-identical to before) — the referee is fully gated.
  3. With it ON, the SINGLE/only type-4 AssignServer(189) on a conn becomes the referee (170, server_type=4,
     server_subtype=5, REF_SERVER_ID/REFEREE_PORT) — re-RE'd s39.6: that one login 189 IS the referee
     one-shot (SADK has exactly ONE type-4 189 caller, latched; the 2 live runs show exactly ONE 189 per
     client). Chat is preserved by ALSO pushing a 192 (REFEREE_ALSO_PUSH_UC). The referee is advertised on
     the type-4 server list so its id resolves.
  4. push_login_success emits a LoginSuccess(0xDCA) frame; handle_frame answers RegisterGame with Ack+Result.

Run:  python tests/test_referee.py   (or: pytest tests/test_referee.py)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, config, dispatch, players, referee, registry  # noqa: E402
from sadk_lobby.tincat import app_payload  # noqa: E402

TICKET = 0x1234


class FakeConn:
    def __init__(self, cid=1, addr=("10.0.0.5", 4444)):
        self.id = cid
        self.addr = addr
        self.alive = True
        self.player = players.default_player()
        self.servers = {}  # per-conn server store (single-user list path)
        self.sent = []     # (type_num, decoded_fields)  via send_app
        self.raw = []      # raw bytes via send_raw (referee pushes)
        self.acked = []

    def send_app(self, type_num, body):
        self.sent.append((type_num, codec.decode_body(type_num, body)))

    def send_raw(self, data):
        self.raw.append(data)

    def ok(self, ticket):
        self.acked.append(ticket)

    def types(self):
        return [t for t, _ in self.sent]

    def sent_of(self, type_num):
        return [f for (t, f) in self.sent if t == type_num]


import struct  # noqa: E402


def _decode_envelope(frame):
    """Decode a referee SendGameData(74) frame → (msg_type, inner_body). Frame = Magic|74|74|msg_type(u32)|
    MEMBLOCK(body). Asserts the envelope shape."""
    magic, t1, t2, msg_type = struct.unpack_from("<HHHI", frame, 0)
    assert magic == config.PAYLOAD_MAGIC and t1 == config.VILLAGE_SENDGAMEDATA == t2, frame.hex()
    blen = struct.unpack_from("<i", frame, 10)[0]
    body = frame[14:14 + blen]
    return msg_type, body


# ── 1. codec golden ────────────────────────────────────────────────────────────
def test_type_word():
    assert referee.type_word(0xDCA, names=False) == 0x3DCA
    assert referee.type_word(0xDCA, names=True) == 0xBDCA
    assert referee.type_word(0xDB7, names=False) == 0x3DB7
    assert referee.type_word(0xDB8, names=False) == 0x3DB8


def test_login_success_bare_golden():
    """The BARE inner form (REF_USE_GAMEDATA_ENVELOPE=False): Magic|0x3DCA|0x3DCA|PermID(u32). This is the
    pre-s39.6 frame that CRASHED the client (CreatePropertySet(0x3dca)→NULL); kept as a diagnostic toggle."""
    saved = config.REF_USE_GAMEDATA_ENVELOPE
    try:
        config.REF_USE_GAMEDATA_ENVELOPE = False
        assert referee.build_login_success(1, names=False) == bytes.fromhex("b626ca3dca3d01000000")
        assert referee.type_word(config.REF_LOGIN_FAIL, False) == 0x3DCB    # NEVER send the fail id
        assert referee.type_word(config.REF_LOGIN_OK, False) == 0x3DCA
    finally:
        config.REF_USE_GAMEDATA_ENVELOPE = saved


def test_login_success_gamedata_wrapped_golden():
    """DEFAULT (REF_USE_GAMEDATA_ENVELOPE=True): SendGameData(74) — Magic|74|74|msg_type=0x3DCA|
    MEMBLOCK([type word(u16)=0x3DCA | PermID(u32)]). s39.6 fix: the referee conn reads the type word from the
    START of the data, so it must be the first u16 INSIDE the MEMBLOCK (not just the 74's msg_type)."""
    saved = config.REF_USE_GAMEDATA_ENVELOPE
    try:
        config.REF_USE_GAMEDATA_ENVELOPE = True
        frame = referee.build_login_success(1, names=False)
        assert frame == bytes.fromhex("b6264a004a00ca3d000006000000ca3d01000000"), frame.hex()
        msg_type, body = _decode_envelope(frame)
        assert msg_type == 0x3DCA                                  # the 74's msg_type (also the type word)
        assert body == bytes.fromhex("ca3d") + bytes.fromhex("01000000")   # inner: type word(u16) + PermID(u32)
        assert struct.unpack_from("<H", body, 0)[0] == 0x3DCA      # the type word OnData reads first
    finally:
        config.REF_USE_GAMEDATA_ENVELOPE = saved


def test_register_game_builders_wrapped_golden():
    saved = config.REF_USE_GAMEDATA_ENVELOPE
    try:
        config.REF_USE_GAMEDATA_ENVELOPE = True
        mt, body = _decode_envelope(referee.build_register_game_ack(7, names=False))
        assert mt == 0x3DB7 and body == bytes.fromhex("b73d") + bytes.fromhex("0700000000000000")  # tw|GameID|Result
        mt, body = _decode_envelope(referee.build_register_game_result(7, names=False))
        assert mt == 0x3DB8                                        # tw | GameID(7) | Result(0) | GameSeed
        assert body == (bytes.fromhex("b83d") + bytes.fromhex("07000000")
                        + bytes.fromhex("00000000") + bytes.fromhex("ed5e0000"))
    finally:
        config.REF_USE_GAMEDATA_ENVELOPE = saved


def test_login_success_names_on_differs():
    off = referee.build_login_success(1, names=False)
    on = referee.build_login_success(1, names=True)
    assert on != off                                   # names-on body differs (name-keyed + 0xFFF end-marker)


# ── 2. default-OFF: byte-identical AssignServer path ────────────────────────────
def test_referee_assign_off_by_default():
    saved = config.ADVERTISE_REFEREE_SERVER
    try:
        config.ADVERTISE_REFEREE_SERVER = False
        c = FakeConn()
        dispatch._h_assign_server(c, {"server_type": 4, "server_subtype": 4}, TICKET)
        dispatch._h_assign_server(c, {"server_type": 4, "server_subtype": 4}, TICKET)  # 2nd assign
        assert c.types() == [192, 192], c.types()     # both UC, never a referee 170
        assert c.sent_of(170) == []
    finally:
        config.ADVERTISE_REFEREE_SERVER = saved


# ── 3. flag ON: the SINGLE type-4 assign = referee (170); chat preserved by a 192 ──
def test_referee_single_type4_assign_is_referee():
    """CORRECTED model (s39.6): the ONE type-4 189 a client sends IS the referee assign → reply 170
    (type=4, subtype=5, REF id/port, SAME ticket), so tincat3 FUN_10021520 sets LM+0x580. With
    REFEREE_ALSO_PUSH_UC on, a 192 is ALSO pushed so the client still reaches the UC/chat server.
    There is NO 2nd 189 in the live protocol (refutes the old 'first=UC, second=referee' test)."""
    saved = config.ADVERTISE_REFEREE_SERVER
    saved_uc = config.REFEREE_ALSO_PUSH_UC
    try:
        config.ADVERTISE_REFEREE_SERVER = True
        config.REFEREE_ALSO_PUSH_UC = True
        c = FakeConn()
        dispatch._h_assign_server(c, {"server_type": 4, "server_subtype": 4}, TICKET)   # the ONLY 189
        # The referee 170 must be sent, carrying the cat-0x108 ticket (echoes the request ticket).
        assert 170 in c.types(), c.types()
        g = c.sent_of(170)[-1]
        assert g["server_type"] == 4 and g["server_subtype"] == 5
        assert g["server_id"] == config.REF_SERVER_ID
        assert g["port"] == config.REFEREE_PORT
        assert g["ip"] == config.ADVERTISED_IP
        assert g["ticket_id"] == TICKET, "referee 170 MUST echo the 189 ticket so cat 0x108 resolves"
        # Chat preserved: a 192 is ALSO pushed (unsolicited → ticket_id 0).
        assert 192 in c.types(), c.types()
        uc = c.sent_of(192)[-1]
        assert uc["port"] == config.UC_PORT and uc["ip"] == config.ADVERTISED_IP
        assert uc["ticket_id"] == 0, "unsolicited UC advertisement uses ticket 0 (170 consumed cat-0x108)"
    finally:
        config.ADVERTISE_REFEREE_SERVER = saved
        config.REFEREE_ALSO_PUSH_UC = saved_uc


def test_referee_no_uc_push_when_disabled():
    """REFEREE_ALSO_PUSH_UC=False → only the referee 170, no 192 (use after a live capture proves chat
    survives on the lobby transport)."""
    saved = config.ADVERTISE_REFEREE_SERVER
    saved_uc = config.REFEREE_ALSO_PUSH_UC
    try:
        config.ADVERTISE_REFEREE_SERVER = True
        config.REFEREE_ALSO_PUSH_UC = False
        c = FakeConn()
        dispatch._h_assign_server(c, {"server_type": 4, "server_subtype": 4}, TICKET)
        assert c.types() == [170], c.types()
    finally:
        config.ADVERTISE_REFEREE_SERVER = saved
        config.REFEREE_ALSO_PUSH_UC = saved_uc


def test_referee_advertised_on_type4_list():
    saved = config.ADVERTISE_REFEREE_SERVER
    saved_mc = config.MULTI_CLIENT_HOSTING
    registry.games.clear()
    try:
        config.ADVERTISE_REFEREE_SERVER = True
        config.MULTI_CLIENT_HOSTING = False
        c = FakeConn()
        dispatch._send_server_list(c, 4, TICKET)
        refs = [g for g in c.sent_of(170) if g["server_subtype"] == 5]
        assert len(refs) == 1, [g["server_subtype"] for g in c.sent_of(170)]
        assert refs[0]["server_id"] == config.REF_SERVER_ID
        assert refs[0]["port"] == config.REFEREE_PORT
        # type-5 (game) list must NOT carry the referee
        c.sent.clear()
        dispatch._send_server_list(c, 5, TICKET)
        assert [g for g in c.sent_of(170) if g["server_subtype"] == 5] == []
    finally:
        config.ADVERTISE_REFEREE_SERVER = saved
        config.MULTI_CLIENT_HOSTING = saved_mc
        registry.games.clear()


# ── 4. push + inbound handling ──────────────────────────────────────────────────
def test_push_login_success_emits_frame():
    c = FakeConn()
    referee.push_login_success(c)
    assert len(c.raw) == 1
    assert c._ref_login_pushed is True
    # the LoginSuccess app-payload is embedded in the TinCat frame
    assert referee.build_login_success(c.player.perm_id) in c.raw[0]
    # idempotent
    referee.push_login_success(c)
    assert len(c.raw) == 1


def test_handle_register_game_acks():
    c = FakeConn()
    frame = app_payload(referee.type_word(config.REF_REGISTER_GAME, False), referee._u32(42))
    referee.handle_frame(c, frame)
    assert len(c.raw) == 2          # Ack + Result
    assert referee.build_register_game_ack(42) in c.raw[0]
    assert referee.build_register_game_result(42) in c.raw[1]


def _run():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {e}")
    print()
    print(f"{failures} test(s) FAILED" if failures else "All referee tests PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
