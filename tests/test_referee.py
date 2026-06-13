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

from sadk_lobby import config, players, referee  # noqa: E402

PERM_ID = 7
GAME_ID = 0x1234


def _parse_referee_payload(app_payload):
    """Decode a referee app-payload (Magic|74|74|msg_type|MEMBLOCK([type word|fields])) → (msg_type, inner)."""
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
    tw, perm = struct.unpack_from("<HI", inner, 0)
    assert msg_type == 0x3DCA and tw == 0x3DCA and perm == PERM_ID, (hex(msg_type), hex(tw), perm)
    print("LoginSuccess(0xDCA) golden OK")


def test_register_ack_result_golden():
    mt, inner = _parse_referee_payload(referee.build_register_game_ack(GAME_ID))
    tw, gid, res = struct.unpack_from("<HII", inner, 0)
    assert mt == 0x3DB7 and tw == 0x3DB7 and gid == GAME_ID and res == 0

    mt, inner = _parse_referee_payload(referee.build_register_game_result(GAME_ID))
    tw, gid, res, seed = struct.unpack_from("<HIII", inner, 0)
    assert mt == 0x3DB8 and tw == 0x3DB8 and gid == GAME_ID and res == 0
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
    inbound = referee.referee_payload(config.REF_REGISTER_GAME, struct.pack("<I", GAME_ID))
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


if __name__ == "__main__":
    test_type_word()
    test_login_success_golden()
    test_register_ack_result_golden()
    test_handle_register_game()
    test_base_login_frame_falls_through()
    print("\nALL REFEREE TESTS PASSED")
