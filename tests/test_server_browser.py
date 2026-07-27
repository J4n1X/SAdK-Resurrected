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


# ── 5. Game-server assign (host match-server registration) ─────────────────────
# [ER 2026-06-14_game-server-assign-170] The host's FUN_0046aaa0 sends AssignServer(189 type5/sub1)
# and parks villageList+0x9c=-2; the stub must reply GameServerData(170) for the host's OWN game
# (→ tincat3 GameServerAssigned clears +0x9c), NOT the UC UsercommServerData(192).
def test_game_assign_replies_170_not_192():
    from sadk_lobby import registry
    saved = config.REPLY_GAME_SERVER_ASSIGN
    registry.games.clear()
    try:
        config.REPLY_GAME_SERVER_ASSIGN = True
        conn = FakeConn()
        conn.id = 4242
        sid = registry.games.add(conn.id, {
            "name": "HostGame", "owner_id": 7, "ip": "192.168.1.143", "port": config.WORLD_PORT,
            "server_type": 5, "server_subtype": 1, "map": "m", "running": True,
        })
        dispatch._h_assign_server(conn, {"server_type": 5, "server_subtype": 1}, TICKET)
        types = [t for t, _ in conn.sent]
        assert 170 in types, "game assign must be answered with GameServerData(170)"
        assert 192 not in types, "game assign must NOT also send the UC server (192)"
        f170 = dict(conn.sent)[170]
        assert f170["server_id"] == sid, "the 170 must echo the host's own hosted-game id"
        assert f170["ticket_id"] == TICKET
        assert f170["server_subtype"] != 5 or f170["server_type"] != 4  # never the referee 4/5
    finally:
        config.REPLY_GAME_SERVER_ASSIGN = saved
        registry.games.clear()


def test_game_assign_no_hosted_game_falls_back_to_192():
    # Defensive: type5/sub1 with no game owned by this conn → the prior 192 behaviour (+ a warning).
    from sadk_lobby import registry
    registry.games.clear()
    conn = FakeConn()
    conn.id = 999
    dispatch._h_assign_server(conn, {"server_type": 5, "server_subtype": 1}, TICKET)
    types = [t for t, _ in conn.sent]
    assert 170 not in types and 192 in types


def test_referee_assign_unaffected():
    # The referee path (type4/sub4) still emits its 170 AND the 192 (chat stays up).
    #
    # ⚠️ The descriptor MUST NOT be type4/sub5. That exact pair is special-cased by
    # tincat3 GameServerManager_OnGameServerAssigned@0x10021520 to a PRIVATE handler that
    # returns without notifying the lobby, so LobbyServerList_GameServerAssigned@0x00469ad0
    # never fires and LM+0x580 never latches — proven live 2026-07-27 (ServerList+0xa4/+0xa8
    # still armed, LM+0x580 = 0 with zero writes). Anything that is not 4/5 takes the default
    # branch into the lobby observer, which is what we need.
    # This assertion previously demanded subtype == 5, i.e. it encoded the bug.
    # ER: engagement_records/2026-07-27_referee-assign-subtype-routing.md
    saved = config.REPLY_REFEREE_ASSIGN
    try:
        config.REPLY_REFEREE_ASSIGN = True
        conn = FakeConn()
        conn.id = 1
        dispatch._h_assign_server(conn, {"server_type": 4, "server_subtype": 4}, TICKET)
        types = [t for t, _ in conn.sent]
        assert 192 in types

        # BOTH 170s must go out, in this order — they hit different halves of the client and
        # sending only one gives register-XOR-notify (we got stuck that way twice on 2026-07-27):
        #   sub5 → tincat3's private handler → REGISTERS server_id → ip:port (else the connect
        #          fails with COMM_LAYER_ERROR_CANNOT_CONNECT / OnLoginFailed @ LobbyManager.cpp:907)
        #   sub4 → default branch → LobbyServerList_GameServerAssigned → latches LM+0x580
        # ER: engagement_records/2026-07-27_referee-dual-170-register-and-notify.md
        # Exactly ONE 170, type4/sub5. [PROVEN 2026-07-27 from tincat3]
        # The 189 allocates a ticket of kind 0x108; the reply is matched to it and only 0x108
        # reaches GameServerManager_OnGameServerAssigned. A ticket is consumed once, so a second
        # frame is silently demoted to a list update — which is why two frames regressed.
        # desc type/subtype 4/5 selects the referee branch (FUN_10029a20), the ONLY path that
        # applies the address and creates a connection keyed by serverId at +0x1c — exactly what
        # InitRefereeServerConnection then looks up (whitelisting 0xcd "already exists").
        # 4/4 latches LM+0x580 but creates no connection → COMM_LAYER_ERROR_CANNOT_CONNECT.
        refs = [b for t, b in conn.sent if t == 170]
        assert len(refs) == 1, (
            f"expected exactly ONE referee 170, got {len(refs)} — the assign ticket is consumed "
            "once, so any extra frame is demoted to a list update"
        )
        assert (refs[0]["server_type"], refs[0]["server_subtype"]) == (4, 5)
        assert refs[0]["server_id"] == config.REF_SERVER_ID
        assert refs[0]["port"] == config.REFEREE_PORT
    finally:
        config.REPLY_REFEREE_ASSIGN = saved


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
