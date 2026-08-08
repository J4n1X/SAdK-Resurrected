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

        # Exactly ONE 170 on the assign itself, type4/sub4. [PROVEN 2026-07-27]
        # The 189 allocates a ticket of kind 0x108; the reply is matched to it and only 0x108
        # reaches GameServerManager_OnGameServerAssigned, and a ticket is consumed ONCE — so a
        # second frame here never reaches the assign path at all (that is why the sub5+sub4 twin
        # regressed). type4/sub5 is special-cased to a tincat3-PRIVATE handler that returns without
        # notifying the lobby, so it must NOT be used: only a non-4/5 descriptor takes the default
        # branch → LobbyServerList_GameServerAssigned@0x00469ad0 → SetRefereeServerAddress →
        # LM+0x580 (+0x588 = 60000, the 60 s retry that is present in every 4/4 run and absent from
        # every 4/5 run).
        #
        # The ADDRESS is not carried here — FUN_100196b0 creates the connection address-less. It
        # arrives in a delayed follow-up 170 (_push_referee_address) that must land AFTER
        # StatePump_Tick has created the connection. That frame is on a threading.Timer, so it is
        # deliberately NOT part of this synchronous assertion.
        # ER: engagement_records/2026-07-27_referee-address-via-post-assign-170.md
        refs = [b for t, b in conn.sent if t == 170]
        assert len(refs) == 1, (
            f"expected exactly ONE referee 170 from the assign, got {len(refs)} — the assign "
            "ticket is consumed once, so any extra frame never reaches OnGameServerAssigned"
        )
        assert (refs[0]["server_type"], refs[0]["server_subtype"]) == (4, 4), (
            "referee descriptor must NOT be 4/5 — that is the tincat3-private branch that never "
            "notifies the lobby, so LM+0x580 never latches"
        )
        assert refs[0]["server_id"] == config.REF_SERVER_ID
        assert refs[0]["port"] == config.REFEREE_PORT
    finally:
        config.REPLY_REFEREE_ASSIGN = saved


# ── 5. The 192 must be sent once per UC CONNECTION, not once per assign ────────
def test_192_suppressed_once_a_uc_conn_is_live():
    """Regression: the 60 s referee retry must not re-dial the UC/chat server.

    tincat3's CommLayer 0xc0 handler (FUN_10030420) dials the advertised ip:port on EVERY 192 it
    sees, without checking for an existing UserComm connection. SetRefereeServerAddress arms
    LM+0x588, so the client re-sends AssignServer(189 type4/sub4) every 60 s for the whole session
    — correct and expected. Replying 192 to each retry therefore stood up a new UC socket a minute
    that the client never closed (live 2026-08-08: 48 UC logins for one player, 41 still open), and
    a 32-bit client ends that exactly one way: `operator new`@0x006f2524 throws the static
    std::bad_alloc at DAT_0088f5b0. See memory: client-crashes-are-oom-bad-alloc.
    """
    saved = config.REPLY_REFEREE_ASSIGN
    try:
        config.REPLY_REFEREE_ASSIGN = True

        # First assign, no UC conn yet → the 192 MUST go out or chat never comes up.
        lobby = FakeConn()
        lobby.id = 1
        dispatch._h_assign_server(lobby, {"server_type": 4, "server_subtype": 4}, TICKET)
        assert 192 in [t for t, _ in lobby.sent], "first assign must still dial UC/chat"
        assert 170 in [t for t, _ in lobby.sent], "referee 170 must always go out"

        # The client dials, and that UC socket registers itself as live for the same player.
        uc = FakeConn()
        uc.id = 2
        uc.is_chat = True
        uc.alive = True
        uc.player = dispatch._player(lobby)      # same identity, different socket
        dispatch.register_conn(uc)
        try:
            # The 60 s retry: 170 yes (it is the reply the retry asks for), 192 NO.
            retry = FakeConn()
            retry.id = 3
            retry.player = dispatch._player(lobby)
            dispatch._h_assign_server(retry, {"server_type": 4, "server_subtype": 4}, TICKET)
            types = [t for t, _ in retry.sent]
            assert 170 in types, "the referee 170 must survive — it is what the retry wants"
            assert 192 not in types, "192 on a retry re-dials UC and leaks the socket"
        finally:
            dispatch.on_conn_closed(uc)

        # Once the UC conn is gone, a later assign must dial again (chat must recover).
        after = FakeConn()
        after.id = 4
        after.player = dispatch._player(lobby)
        dispatch._h_assign_server(after, {"server_type": 4, "server_subtype": 4}, TICKET)
        assert 192 in [t for t, _ in after.sent], "UC conn closed → the next assign must re-dial"
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
