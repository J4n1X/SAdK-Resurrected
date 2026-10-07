"""
Accounts (offline): the first login with a new name registers it with its password, a wrong password
is refused with Result(42) on the auth ticket (the client's login-failure path, T 10023cc0), and
"!setpwd" is the only way to change it.

Run:  python tests/test_accounts.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.environ["SADK_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "players.json")

from sadk_lobby import crypto, dispatch, players, store  # noqa: E402


class FakeConn:
    _next = 1

    def __init__(self):
        self.id, FakeConn._next = FakeConn._next, FakeConn._next + 1
        self.shared, self.sent, self.results, self.player = b"k" * 32, [], [], None
        self.logged_in = False

    def send_app(self, ptype, body):
        self.sent.append(ptype)

    def result(self, errorcode, ticket):
        self.results.append((errorcode, ticket))


def _login(name, password):
    crypto.decrypt_cipher = lambda cipher, shared: b""
    crypto.decode_login_blob = lambda blob, has_cdkey=False: {
        "username": name, "password_raw": password.encode().hex()}
    c = FakeConn()
    dispatch._h_auth_user(c, {"cipher": b"x"}, 7)
    return c


def test_register_then_check():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    c = _login("Neuling", "geheim")
    assert c.logged_in and 207 in c.sent and not c.results          # first login registers
    assert store.has_password("Neuling")
    c = _login("neuling", "falsch")                                  # names are case-insensitive
    assert not c.logged_in and c.results == [(1, 7)] and 207 not in c.sent
    c = _login("Neuling", "geheim")
    assert c.logged_in and 207 in c.sent
    raw = open(os.environ["SADK_STORE_PATH"]).read()
    assert "geheim" not in raw and "password_hash" in raw              # hashed, never in clear
    assert "password_hash" not in store.account_of("Neuling")          # not leaked through copies
    print("first login registers, wrong password refused with Result(42), hashed at rest OK")


def test_setpwd():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    _login("Wanderer", "alt")
    p = players.resolve_by_username("Wanderer")
    assert "Usage" in dispatch._chat_command(None, p, "!setpwd")
    assert "changed" in dispatch._chat_command(None, p, "!setpwd neu")
    assert not _login("Wanderer", "alt").logged_in
    assert _login("Wanderer", "neu").logged_in
    assert "!setpwd" in dispatch._chat_command(None, p, "!help")
    print("!setpwd changes the password, !help lists the commands OK")


if __name__ == "__main__":
    test_register_then_check()
    test_setpwd()
    print("\nAll account tests PASSED")
