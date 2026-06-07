"""
Offline integration smoke test: drive a Conn through a realistic client
conversation with a fake socket and assert the server's responses.

Run directly:   python tests/test_server_smoke.py
"""
import os
import socket  # noqa: F401  (FakeSock mimics its interface)
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, config, log as logmod  # noqa: E402
from sadk_lobby.connection import Conn  # noqa: E402
from sadk_lobby.tincat import app_payload, build_frame, parse_header  # noqa: E402

logmod.set_log_path(os.path.join(os.path.dirname(__file__), "smoke.log"))


class FakeSock:
    def __init__(self, inbound: bytes):
        self._chunks = [inbound]
        self.sent = bytearray()

    def settimeout(self, t):
        pass

    def recv(self, n):
        return self._chunks.pop(0) if self._chunks else b""

    def sendall(self, data):
        self.sent += data

    def close(self):
        pass


def _client_handshake():
    payload = (struct.pack("<II", config.MAGIC, 0)
               + b"machine\x00".ljust(config.HANDSHAKE_USERNAME_SIZE, b"\x00")
               + b"test\x00".ljust(config.HANDSHAKE_PASSWORD_SIZE, b"\x00")
               + struct.pack("<i", 0))
    return build_frame(config.FROM_CLIENT, 0, config.MSG_HANDSHAKE_CONNECT, payload)


def _client_app(type_num, values):
    return build_frame(config.FROM_CLIENT, 0, config.MSG_APPLICATION,
                       app_payload(type_num, codec.encode_body(type_num, values)))


def _split_frames(stream: bytes):
    out = []
    p = 0
    while p + config.PREFIX_SIZE <= len(stream):
        h = parse_header(stream[p:p + config.PREFIX_SIZE])
        p += config.PREFIX_SIZE
        body = stream[p:p + h["PayloadSize"]]
        p += h["PayloadSize"]
        out.append((h, body))
    return out


def _app_frames(frames):
    """Yield (type1, body_after_prefix) for application frames using lobby magic."""
    for h, payload in frames:
        if h["Type"] != config.MSG_APPLICATION:
            continue
        if len(payload) < 6:
            continue
        magic, t1, t2 = struct.unpack_from("<HHH", payload, 0)
        if magic != config.PAYLOAD_MAGIC:
            continue
        yield t1, payload


def test_full_conversation():
    inbound = b"".join([
        _client_handshake(),
        _client_app(188, {"version": 1, "subversion": 0, "ticket_id": 11}),
        _client_app(161, {"kategory": 1, "index": 2, "ticket_id": 12}),
        _client_app(171, {"send_all": True, "server_type": 4, "room_id": 1000,
                          "level": 0, "game_mode": 0, "hardcore": 0,
                          "selection": 0, "ticket_id": 13}),
    ])
    sock = FakeSock(inbound)
    conn = Conn(sock, ("127.0.0.1", 5555), 1, None)
    conn.run()

    frames = _split_frames(bytes(sock.sent))
    assert frames, "server sent nothing"

    # 1) handshake-connected (type 5)
    assert frames[0][0]["Type"] == config.MSG_HANDSHAKE_CONNECTED, "no HandShakeConnected first"

    # 2) collect app message types the server emitted
    emitted = [t1 for t1, _ in _app_frames(frames)]
    assert 162 in emitted, f"no PropertyData(162); got {emitted}"
    assert 42 in emitted, f"no Result OK(42); got {emitted}"
    assert 170 in emitted, f"no GameServerData(170); got {emitted}"

    # 3) the 170 must be our village world, decoded canonically
    body170 = next(p for t1, p in _app_frames(frames) if t1 == 170)
    srv = codec.decode_body(170, body170, 6)
    assert srv["server_type"] == 4, srv
    assert srv["server_subtype"] == 2, srv
    assert srv["room_id"] == 1000, srv
    assert srv["name"] == "world1", srv
    assert srv["map"] == "world1", srv
    assert srv["ticket_id"] == 13, srv


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
    print("\n" + ("FAILED" if failures else "All smoke tests PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
