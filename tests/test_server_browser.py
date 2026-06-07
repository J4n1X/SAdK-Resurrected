"""
Offline tests for the MP server-browser stub change (s38).

These run with NO live game and NO sockets — they exercise the codec + dispatch
logic only, to prove:
  1. The refactor (village ServerDataBlock now derived from config.LOBBY_PROTOCOL_VERSION)
     produces BYTE-IDENTICAL wire output to the long-standing literal b"\\x00\\x00\\x03\\xe8\\x00".
  2. server_data_block() encodes roomId BIG-ENDIAN + 1 pending byte, and decodes back.
  3. The village 170 still carries subtype 2 + the data block (joinable entry).
  4. The game-browser change is correctly GATED: with config.ADVERTISE_GAME_SERVERS
     OFF (default) the emitted game 170 keeps server_subtype 0 (byte-identical to today);
     only with the flag ON does it become subtype 1 (the BrowseGameDialog entry).

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


def test_advertise_game_servers_off_by_default():
    # Harness: the new game-browser behavior must be opt-in, not on by default.
    assert config.ADVERTISE_GAME_SERVERS is False
    assert config.GAMESERVERDATA_FORMAT == "old"  # sanity: 170 format unchanged


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


# ── 4. The game-browser change is correctly gated ──────────────────────────────
def _emit_game_server():
    """Run the real _send_server_list type-5 fallback through a FakeConn; return decoded 170s."""
    conn = FakeConn()
    dispatch._send_server_list(conn, 5, TICKET)
    return [f for (t, f) in conn.sent if t == 170]


def test_game_server_subtype_gated(monkeypatch=None):
    saved = config.ADVERTISE_GAME_SERVERS
    try:
        # OFF (default): emitted game 170 keeps subtype 0 — byte-identical to today's behavior.
        config.ADVERTISE_GAME_SERVERS = False
        off = _emit_game_server()
        assert len(off) == 1 and off[0]["server_type"] == 5
        assert off[0]["server_subtype"] == 0, "default must stay inert subtype 0"

        # ON: emitted game 170 becomes subtype 1 → routed to the game list → BrowseGameDialog entry.
        config.ADVERTISE_GAME_SERVERS = True
        on = _emit_game_server()
        assert len(on) == 1 and on[0]["server_type"] == 5
        assert on[0]["server_subtype"] == 1, "flag ON must advertise subtype 1 (game list)"
        # Independent-review capacity gate: BrowseGameDialog disables join unless current < max
        # ("!LOBBY_MATCHMAKING_GAMEISFULL"). The advertised entry must have join headroom.
        assert on[0]["cur_players"] < on[0]["max_players"], "game entry must not be full (current < max)"
    finally:
        config.ADVERTISE_GAME_SERVERS = saved


def test_fake_game_default_subtype_unchanged():
    # The source-of-truth dict is untouched; only the per-send copy is upgraded under the flag.
    assert dispatch.FAKE_GAME["server_subtype"] == 0


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
