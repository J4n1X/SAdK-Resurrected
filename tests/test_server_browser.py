"""
Offline tests for the MP server-browser stub change (s38).

These run with NO live game and NO sockets — they exercise the codec + dispatch
logic only, to prove:
  1. The refactor (village ServerDataBlock now derived from config.LOBBY_PROTOCOL_VERSION)
     produces BYTE-IDENTICAL wire output to the long-standing literal b"\\x00\\x00\\x03\\xe8\\x00".
  2. server_data_block() encodes roomId BIG-ENDIAN + 1 pending byte, and decodes back.
  3. The village 170 still carries subtype 2 + the data block (joinable entry).
  4. The game browser injects NO synthetic entry: with no real games hosted, a
     server_type=5 list is empty (no phantom "0/2" FAKE_GAME). Real hosted games
     flow through the registry loop with their own client-set subtype + real counts.

Run directly:   python tests/test_server_browser.py
Or with pytest: pytest tests/test_server_browser.py
"""
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, config, dispatch  # noqa: E402

TICKET = 0x12345678


class FakeConn:
    """Minimal stand-in for a live connection: records what the stub WOULD send."""
    def __init__(self):
        self.servers = {}
        self.sent = []     # list of (type_num, decoded_fields_dict)
        self.raw = []      # list of (type_num, raw_body_bytes)
        self.acked = []

    def send_app(self, type_num, body):
        self.raw.append((type_num, body))
        self.sent.append((type_num, codec.decode_body(type_num, body)))

    def ok(self, ticket):
        self.acked.append(ticket)


# ── 1. The refactor must not change the wire by default ────────────────────────
def test_village_data_block_default_byte_identical():
    # The literal that lived in dispatch.py for many sessions (s15-confirmed joinable).
    legacy_literal = b"\x00\x00\x03\xe8\x00"
    assert config.LOBBY_PROTOCOL_VERSION == 1000, "default protocol version drifted"
    assert dispatch.server_data_block(config.LOBBY_PROTOCOL_VERSION) == legacy_literal
    assert dispatch.FAKE_VILLAGE["data"] == legacy_literal, "FAKE_VILLAGE wire data changed!"


# ── 2. server_data_block encoding ──────────────────────────────────────────────
def test_server_data_block_encoding():
    assert dispatch.server_data_block(1000) == b"\x00\x00\x03\xe8\x00"  # 0x3E8 BE + pending 0
    assert dispatch.server_data_block(1) == b"\x00\x00\x00\x01\x00"
    assert dispatch.server_data_block(0x12345678) == b"\x12\x34\x56\x78\x00"
    # roundtrip: first 4 bytes BE == roomId, 5th byte == pending(0)
    blk = dispatch.server_data_block(4242)
    assert len(blk) == 5
    assert struct.unpack(">I", blk[:4])[0] == 4242
    assert blk[4] == 0


# ── 3. Village 170 stays joinable (subtype 2 + data block) ─────────────────────
def test_village_170_roundtrip():
    body = codec.encode_body(170, dispatch.server_to_170_values(dispatch.FAKE_VILLAGE, TICKET))
    back = codec.decode_body(170, body)
    assert "_decode_err" not in back, back.get("_decode_err")
    assert back["server_type"] == 4
    assert back["server_subtype"] == 2                       # → village list
    assert back["data"] == b"\x00\x00\x03\xe8\x00"           # ServerDataBlock present
    assert struct.unpack(">I", back["data"][:4])[0] == 1000  # roomId == ProtocolVersion match key


# ── 4. The game browser injects NO synthetic entry ─────────────────────────────
def _emit_game_servers(conn=None):
    """Run the real _send_server_list type-5 path through a FakeConn; return decoded 170s."""
    conn = conn or FakeConn()
    dispatch._send_server_list(conn, 5, TICKET)
    return [f for (t, f) in conn.sent if t == 170]


def test_no_fake_game_injected():
    # With no real games hosted, a server_type=5 list is EMPTY — no phantom "0/2" placeholder.
    from sadk_lobby import registry
    registry.games.clear()                       # isolate from any game a prior test registered
    emitted = _emit_game_servers()
    # No game-list (server_type==5) 170 should be emitted when nothing is hosted.
    game_entries = [f for f in emitted if f.get("server_type") == 5]
    assert game_entries == [], f"expected no synthetic game entry, got {game_entries}"


def test_fake_game_removed_from_source():
    # The wretched fake game is gone from the module entirely.
    assert not hasattr(dispatch, "FAKE_GAME"), "FAKE_GAME must be removed from dispatch.py"
    assert not hasattr(config, "ADVERTISE_GAME_SERVERS"), "vestigial flag must be removed from config.py"


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
    if failures:
        print(f"{failures} test(s) FAILED")
        return 1
    print("All server-browser tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
