"""
Referee server golden + behaviour test (offline — no sockets, no live game).

Proves the referee LobbyMessage builders are byte-stable and that handle_frame answers a host's
RegisterGame with LoginSuccess + Ack + Result, and ignores base-login frames. The assign-server wiring
and the on-wire framing/trigger are [VERIFY LIVE] (see referee.py / config.py) and are NOT asserted here.

Run:  python tests/test_referee.py   (or: pytest tests/test_referee.py)
"""
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))  # never touch the real store
from sadk_lobby import config, players, referee  # noqa: E402

PERM_ID = 7
GAME_ID = 0x1234


def _parse_referee_payload(app_payload):
    """Decode a referee app-payload → (type word, fields).

    Proven framing (referee.referee_payload, live 2026-07-27): Magic|74|74|typeWord(u32 LE)|
    MEMBLOCK(u32 LE length + FIELDS ONLY). The type word is not repeated inside the MEMBLOCK, and
    the fields are BIG-endian."""
    magic, t1, t2, msg_type = struct.unpack_from("<HHHI", app_payload, 0)
    assert magic == config.PAYLOAD_MAGIC, hex(magic)
    assert t1 == config.VILLAGE_SENDGAMEDATA == t2, (t1, t2)
    blen = struct.unpack_from("<I", app_payload, 10)[0]
    return msg_type, app_payload[14:14 + blen]


def test_type_word():
    assert referee.type_word(0xDCA) == 0x3DCA
    assert referee.type_word(0xDB7) == 0x3DB7
    assert referee.type_word(0xDB8) == 0x3DB8
    assert referee.type_word(0xDCA, names=True) == 0xBDCA
    print("type_word OK")


def test_login_success_golden():
    msg_type, inner = _parse_referee_payload(referee.build_login_success(PERM_ID))
    (perm,) = struct.unpack_from(">I", inner, 0)
    assert msg_type == 0x3DCA and len(inner) == 4 and perm == PERM_ID, (hex(msg_type), inner.hex())
    print("LoginSuccess(0xDCA) golden OK")


def test_register_ack_result_golden():
    mt, inner = _parse_referee_payload(referee.build_register_game_ack(GAME_ID))
    gid, res = struct.unpack_from(">II", inner, 0)
    assert mt == 0x3DB7 and len(inner) == 8 and gid == GAME_ID and res == 0

    mt, inner = _parse_referee_payload(referee.build_register_game_result(GAME_ID))
    gid, res, seed = struct.unpack_from(">III", inner, 0)
    assert mt == 0x3DB8 and len(inner) == 12 and gid == GAME_ID and res == 0
    assert seed == config.REF_GAME_SEED, hex(seed)
    print("RegisterGameAck/Result golden OK")


class FakeConn:
    def __init__(self):
        self.id = 1
        self.alive = True
        self.player = players.default_player()
        self.raw = []

    def send_raw(self, data):
        self.raw.append(data)

    def referee_msg_ids(self):
        # raw frame = 28-byte TinCat header + app-payload; recover the referee msg id from each.
        return [referee._inner_msg_id(fr[config.PREFIX_SIZE:])[0] for fr in self.raw]


def test_handle_register_game():
    conn = FakeConn()
    inbound = referee.referee_payload(config.REF_REGISTER_GAME, struct.pack(">I", GAME_ID))
    assert referee.handle_frame(conn, inbound) is True
    # LoginSuccess pushed on the channel open, then Ack + Result for RegisterGame.
    assert conn.referee_msg_ids() == [
        config.REF_LOGIN_OK, config.REF_REGISTER_ACK, config.REF_REGISTER_RESULT
    ], conn.referee_msg_ids()
    print("handle_frame RegisterGame → LoginSuccess + Ack + Result OK")


def test_base_login_frame_falls_through():
    # A non-74 app frame (e.g. a base-login NETMSG like CheckVersion 188) must NOT be consumed here.
    conn = FakeConn()
    not_referee = struct.pack("<HHH", config.PAYLOAD_MAGIC, 188, 188)
    assert referee.handle_frame(conn, not_referee) is False
    assert conn.raw == []
    print("base-login frame falls through OK")


def _guid():
    return bytes(range(16))


def test_giveup_echoes_game_id():
    conn = FakeConn()
    referee.handle_frame(conn, referee.referee_payload(config.REF_GIVEUP_GAME,
                                                       struct.pack(">I", GAME_ID) + _guid()))
    assert conn.referee_msg_ids() == [config.REF_LOGIN_OK, config.REF_GIVEUP_ACK], conn.referee_msg_ids()
    mt, inner = _parse_referee_payload(conn.raw[-1][config.PREFIX_SIZE:])
    assert struct.unpack(">II", inner) == (GAME_ID, 0)
    try:
        referee.build_giveup_ack(GAME_ID, 21)
        raise AssertionError("result 21 must be refused (it crashes the client)")
    except ValueError:
        pass
    print("GiveUpGame → 0xDD5 with the echoed GameID OK")


def test_finish_game_ack_then_result():
    conn = FakeConn()
    body = struct.pack(">I", GAME_ID) + _guid() + bytes([3]) + b"123" + struct.pack(">I", 42)
    referee.handle_frame(conn, referee.referee_payload(config.REF_FINISH_GAME, body))
    assert conn.referee_msg_ids() == [config.REF_LOGIN_OK, config.REF_FINISH_ACK,
                                      config.REF_FINISH_RESULT], conn.referee_msg_ids()
    _, inner = _parse_referee_payload(conn.raw[-1][config.PREFIX_SIZE:])
    assert inner == struct.pack(">II", GAME_ID, 0), inner.hex()      # no FailReason with Result 0
    assert referee._finish_reports[GAME_ID] == {conn.player.perm_id: 42}
    print("FinishGame → 0xDC1 + 0xDC2 OK")


def test_claim_chest_first_claimant_wins():
    referee._chest_owner.clear()
    a = FakeConn()
    b = FakeConn()
    b.player = players.resolve_by_perm(PERM_ID + 1)
    body = lambda actor: struct.pack(">I", GAME_ID) + _guid() + struct.pack(">II", actor, 9)
    referee.handle_frame(a, referee.referee_payload(config.REF_CLAIM_CHEST, body(500)))
    referee.handle_frame(b, referee.referee_payload(config.REF_CLAIM_CHEST, body(501)))
    for conn in (a, b):
        assert conn.referee_msg_ids()[-2:] == [config.REF_CLAIM_ACK, config.REF_CLAIM_RESULT]
        _, ack = _parse_referee_payload(conn.raw[-2][config.PREFIX_SIZE:])
        assert struct.unpack(">II", ack) == (GAME_ID, 0)          # Result is ALWAYS 0
        _, res = _parse_referee_payload(conn.raw[-1][config.PREFIX_SIZE:])
        assert struct.unpack_from(">II", res) == (a.player.perm_id, 9) and res[8] == 0, res.hex()
    print("ClaimChest → 0xDAD(0) + 0xDAE, first claimant keeps the chest OK")


if __name__ == "__main__":
    test_type_word()
    test_login_success_golden()
    test_register_ack_result_golden()
    test_handle_register_game()
    test_base_login_frame_falls_through()
    test_giveup_echoes_game_id()
    test_finish_game_ack_then_result()
    test_claim_chest_first_claimant_wins()
    print("\nALL REFEREE TESTS PASSED")
