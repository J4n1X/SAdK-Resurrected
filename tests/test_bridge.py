"""
Host bridge (sadk_lobby/bridge.py, docs/bridge-protocol.md), end to end over local sockets with a fake
shim: the lobby preamble, the reachability probe, and a joiner piped to the host through a data channel.

Run:  python tests/test_bridge.py
"""
import os
import socket
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import bridge, config, registry  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _line(sock):
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(1)
        assert chunk, "connection closed before a full line"
        buf += chunk
    return buf.decode().strip()


def _start():
    config.BRIDGE_PORT, config.BRIDGE_RELAY_PORT = _free_port(), _free_port()
    config.ADVERTISED_IP = "203.0.113.7"
    bridge.reset_for_tests()
    bridge.start()
    time.sleep(0.2)


def _hello(token):
    c = socket.create_connection(("127.0.0.1", config.BRIDGE_PORT), timeout=5)
    c.sendall(f"SADKB1 HELLO {token}\n".encode())
    welcome = _line(c)
    assert welcome == (f"WELCOME relay={config.BRIDGE_RELAY_PORT} vbase={config.BRIDGE_VPORT_BASE} "
                       f"vip=203.0.113.7"), welcome
    return c


def test_preamble():
    tok = "a" * 32
    assert bridge.split_preamble(f"SADKB1 LOBBY {tok}\n".encode() + b"\xef\xfb") == (tok, b"\xef\xfb", True)
    assert bridge.split_preamble(b"SADKB1 LOB") == (None, b"SADKB1 LOB", False)        # wait for more
    assert bridge.split_preamble(b"\xef\xfb\xba\xda" + b"x" * 30) == (None, b"\xef\xfb\xba\xda" + b"x" * 30, True)
    assert bridge.split_preamble(b"\xef") == (None, b"\xef", True)                     # no shim: TinCat
    print("lobby preamble split from the first TinCat frame OK")


def test_lobby_connection_reads_preamble():
    from sadk_lobby.connection import Conn
    a, b = socket.socketpair()
    c = Conn(a, ("198.51.100.4", 5000), 1, None)
    c._buf = b"SADKB1 LOB"
    c._process()
    assert c._state == "PREAMBLE" and c.bridge_token is None          # line not complete yet
    c._buf += b"BY tok123\n"
    c._process()
    assert c._state == "PREFIX" and c.bridge_token == "tok123" and c._buf == b""
    plain = Conn(b, ("198.51.100.5", 5001), 2, None)
    plain._buf = b"\xef\xfb\xba\xda"
    plain._process()
    assert plain._state == "PREFIX" and plain.bridge_token is None and plain._buf == b"\xef\xfb\xba\xda"
    a.close()
    b.close()
    print("lobby connection: shim token taken from the preamble, plain clients untouched OK")


def test_probe():
    ctl = _hello("probe-token")
    game = socket.socket()
    game.bind(("127.0.0.1", 0))
    game.listen(1)
    ctl.sendall(f"CHECK {game.getsockname()[1]} n0nce\n".encode())
    game.settimeout(5)
    inbound, _ = game.accept()
    assert _line(inbound) == "SADKB1 PROBE n0nce"
    assert _line(ctl) == "CHECKED ok n0nce"
    closed = _free_port()
    ctl.sendall(f"CHECK {closed} other\n".encode())
    assert _line(ctl) == "CHECKED fail other"
    ctl.close()
    game.close()
    print("reachability probe: connect-back with the nonce, ok / fail reported OK")


def test_relay():
    token = "host-token"
    ctl = _hello(token)
    assert bridge.game_registered(1, token) is None            # reachable host: no bridge
    ctl.sendall(b"BRIDGED\nHOSTING 5479\n")
    time.sleep(0.2)
    sid = registry.games.add(999, {"name": "Bridged", "server_type": 5})
    assert bridge.game_registered(sid, token) == ("203.0.113.7", config.BRIDGE_VPORT_BASE + sid)

    joiner = socket.create_connection(("127.0.0.1", config.BRIDGE_RELAY_PORT), timeout=5)
    joiner.sendall(f"SADKB1 JOIN {sid}\n".encode() + b"LOGMEON")     # TinCat may follow at once
    opened = _line(ctl)
    assert opened.startswith("OPEN "), opened
    data = socket.create_connection(("127.0.0.1", config.BRIDGE_PORT), timeout=5)
    data.sendall(f"SADKB1 DATA {token} {opened.split()[1]}\n".encode())
    got = b""
    while len(got) < 7:
        got += data.recv(64)
    assert got == b"LOGMEON"
    data.sendall(b"LOGONACCEPTED")
    back = b""
    while len(back) < 13:
        back += joiner.recv(64)
    assert back == b"LOGONACCEPTED"

    stranger = socket.create_connection(("127.0.0.1", config.BRIDGE_RELAY_PORT), timeout=5)
    stranger.sendall(b"SADKB1 JOIN 424242\n")                   # no such bridged game: closed
    assert stranger.recv(1) == b""
    for s in (joiner, data, ctl, stranger):
        s.close()
    registry.games.clear()
    print("joiner piped to the host through the shim's data channel OK")


if __name__ == "__main__":
    _start()
    test_preamble()
    test_lobby_connection_reads_preamble()
    test_probe()
    test_relay()
    print("\nAll bridge tests PASSED")
