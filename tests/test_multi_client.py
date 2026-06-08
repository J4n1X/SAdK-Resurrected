"""
Offline tests for multi-client hosting (s39.5) — multiple players + a global game
registry, so a host and a joiner can be two DISTINCT players and one client's hosted
game is visible to (and joinable by) another.

No live game, no sockets — codec + dispatch + players + registry logic only. Proves:
  1. With config.MULTI_CLIENT_HOSTING OFF (default) every connection serves the
     default test identity and game servers stay per-connection (byte-identical).
  2. Player resolution: lobby by username, UC/village by perm_id, auto-register.
  3. The global registry makes client A's hosted game (168) visible to client B's
     RequestServers(166) and resolvable by RequestConnectionData(221).
  4. Ownership cleanup: dropping the owning connection removes its games.

Run directly:   python tests/test_multi_client.py
Or with pytest: pytest tests/test_multi_client.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, config, dispatch, players, registry  # noqa: E402

TICKET = 0x0BADF00D


class FakeConn:
    """Records what the stub WOULD send; supports the handlers under test."""
    def __init__(self, conn_id, addr=("127.0.0.1", 5000)):
        self.id = conn_id
        self.addr = addr
        self.servers = {}
        self._next_server_id = 100
        self.player = players.default_player()
        self.sent = []     # (type_num, decoded_fields)
        self.acked = []

    def alloc_server_id(self):
        sid = self._next_server_id
        self._next_server_id += 1
        return sid

    def send_app(self, type_num, body):
        self.sent.append((type_num, codec.decode_body(type_num, body)))

    def ok(self, ticket):
        self.acked.append(ticket)

    def status_with_id(self, errorcode, obj_id, ticket):
        self.sent.append(("153", {"errorcode": errorcode, "id": obj_id, "ticket": ticket}))
        return obj_id

    def sent_of(self, type_num):
        return [f for (t, f) in self.sent if t == type_num]


def _add_game(conn, **over):
    fields = {
        "name": "Host Game", "description": "", "ip": "", "port": 5479,
        "server_type": 5, "server_subtype": 1, "max_players": 4,
        "ai_players": 0, "room_id": 9212, "level": 0, "game_mode": 0,
        "hardcore": False, "map": "MP_2P_steinfjord", "running": False, "data": None,
    }
    fields.update(over)
    dispatch._h_add_game_server(conn, fields, TICKET)
    # the new server_id is whatever status_with_id recorded
    return conn.sent[-1][1]["id"]


# ── 1. Default-safe: flag off keeps per-connection isolation ───────────────────
def test_flag_off_games_stay_per_connection():
    saved = config.MULTI_CLIENT_HOSTING
    registry.games.clear()
    try:
        config.MULTI_CLIENT_HOSTING = False
        a = FakeConn(1); b = FakeConn(2)
        _add_game(a, name="A-only")
        # B (a different connection) must NOT see A's game with the flag off.
        b.sent.clear()
        dispatch._send_server_list(b, 5, TICKET)
        names = [f["name"] for f in b.sent_of(170)]
        assert "A-only" not in names, names
        # B sees only the injected demo fallback (flag off → subtype 0 inert).
        assert names == ["Revival Test Game"], names
    finally:
        config.MULTI_CLIENT_HOSTING = saved
        registry.games.clear()


# ── 2. Player resolution ───────────────────────────────────────────────────────
def test_player_resolution_predefined_and_auto():
    saved = config.MULTI_CLIENT_HOSTING
    try:
        config.MULTI_CLIENT_HOSTING = True
        p1 = players.resolve_by_username("test")
        p2 = players.resolve_by_username("test2")
        assert (p1.perm_id, p1.char_name) == (config.TEST_PERM_ID, config.TEST_CHAR_NAME)
        assert (p2.perm_id, p2.char_name) == (2, "Siedler")
        assert p1.perm_id != p2.perm_id
        # case-insensitive match to the same predefined player
        assert players.resolve_by_username("TEST2").perm_id == 2
        # unknown username auto-registers a fresh, distinct perm_id
        auto = players.resolve_by_username("alice")
        assert auto.perm_id >= 1000 and auto.perm_id not in (1, 2)
        assert auto.username == "alice"
        # UC/village conns resolve by the token perm_id back to the same players
        assert players.resolve_by_perm(2).char_name == "Siedler"
        assert players.resolve_by_perm(auto.perm_id).username == "alice"
        # unknown perm_id falls back to the default player (defensive)
        assert players.resolve_by_perm(0xDEAD).perm_id == config.TEST_PERM_ID
    finally:
        config.MULTI_CLIENT_HOSTING = saved


def test_resolution_off_falls_back_to_default():
    saved = config.MULTI_CLIENT_HOSTING
    try:
        config.MULTI_CLIENT_HOSTING = False
        # with the flag off, an unknown username must NOT auto-register; default served
        assert players.resolve_by_username("nobody-xyz").perm_id == config.TEST_PERM_ID
    finally:
        config.MULTI_CLIENT_HOSTING = saved


# ── 3. Cross-client visibility + join resolution ───────────────────────────────
def test_hosted_game_visible_and_joinable_cross_client():
    saved = config.MULTI_CLIENT_HOSTING
    saved_via = config.GAME_CONN_VIA_STUB
    registry.games.clear()
    try:
        config.MULTI_CLIENT_HOSTING = True
        config.GAME_CONN_VIA_STUB = False          # this test asserts the P2P handoff (host address)
        host = FakeConn(1, addr=("10.0.0.5", 4444))
        host.player = players.resolve_by_username("test")          # perm 1
        joiner = FakeConn(2, addr=("10.0.0.9", 5555))
        joiner.player = players.resolve_by_username("test2")        # perm 2

        # Host advertises its IP via 168 (ip="" → falls back to the conn's address).
        sid = _add_game(host, name="Steinfjord Duell", ip="", port=5479)

        # Joiner browses game servers (type 5) and sees the host's game.
        dispatch._send_server_list(joiner, 5, TICKET)
        games = joiner.sent_of(170)
        assert any(g["name"] == "Steinfjord Duell" for g in games), [g["name"] for g in games]
        g = next(g for g in games if g["name"] == "Steinfjord Duell")
        assert g["server_id"] == sid
        assert g["owner_id"] == 1                  # owned by the host player
        assert g["server_subtype"] == 1            # game list (BrowseGameDialog)
        assert g["ip"] == "10.0.0.5"               # host's real address, not advertised default

        # Joiner clicks Join → 221 → 222 carries the host's address (P2P handoff).
        joiner.sent.clear()
        dispatch._h_connection_data(joiner, {"perm_id": 2, "server_id": sid}, TICKET)
        cd = joiner.sent_of(222)[0]
        assert cd["server_id"] == sid
        assert cd["ip"] == "10.0.0.5" and cd["port"] == 5479
        assert cd["perm_id"] == 2                   # the joiner's perm_id
        assert cd["errorcode"] == 0
    finally:
        config.MULTI_CLIENT_HOSTING = saved
        config.GAME_CONN_VIA_STUB = saved_via
        registry.games.clear()


def test_game_conn_via_stub_routes_join_to_stub():
    """With GAME_CONN_VIA_STUB on, the join address is the stub's dedicated game port,
    NOT the host's — so the joiner's GameServerConnection lands on the stub for capture."""
    saved = config.MULTI_CLIENT_HOSTING
    saved_via = config.GAME_CONN_VIA_STUB
    registry.games.clear()
    try:
        config.MULTI_CLIENT_HOSTING = True
        config.GAME_CONN_VIA_STUB = True
        host = FakeConn(1, addr=("10.0.0.5", 4444))
        sid = _add_game(host, name="Captured Game", ip="10.0.0.5", port=5479)
        joiner = FakeConn(2)
        dispatch._h_connection_data(joiner, {"perm_id": 2, "server_id": sid}, TICKET)
        cd = joiner.sent_of(222)[0]
        # routed to the STUB's dedicated game endpoint, not the host's 10.0.0.5:5479
        assert cd["ip"] == config.ADVERTISED_IP
        assert cd["port"] == config.GAME_PORT
        assert config.GAME_PORT != config.WORLD_PORT   # must be a distinct port (no EnterWorld push)
    finally:
        config.MULTI_CLIENT_HOSTING = saved
        config.GAME_CONN_VIA_STUB = saved_via
        registry.games.clear()


# ── 4. Ownership cleanup on disconnect ─────────────────────────────────────────
def test_owner_cleanup_removes_games():
    registry.games.clear()
    try:
        sid_a = registry.games.add(1, {"name": "A", "server_type": 5})
        registry.games.add(1, {"name": "A2", "server_type": 5})
        registry.games.add(2, {"name": "B", "server_type": 5})
        assert len(registry.games.list_by_type(5)) == 3
        dead = registry.games.remove_owner(1)
        assert len(dead) == 2 and sid_a in dead
        remaining = registry.games.list_by_type(5)
        assert [r["name"] for r in remaining] == ["B"]
        # a non-owner cannot remove someone else's game
        assert registry.games.remove(99, remaining[0]["id"]) is False
    finally:
        registry.games.clear()


def test_game_conn_via_stub_does_not_hijack_lobby_world():
    """REGRESSION (s39.5 live bug): GAME_CONN_VIA_STUB must NOT redirect the lobby-world
    entry request (an unregistered server_id like the FAKE_VILLAGE's 50) to the game port —
    only real hosted games. Otherwise the client dials :5480 for the lobby world and never
    enters it."""
    saved = config.MULTI_CLIENT_HOSTING
    saved_via = config.GAME_CONN_VIA_STUB
    registry.games.clear()
    try:
        config.MULTI_CLIENT_HOSTING = True
        config.GAME_CONN_VIA_STUB = True
        joiner = FakeConn(2)
        # server_id 50 is the lobby-world village (never registered) → must NOT be redirected.
        dispatch._h_connection_data(joiner, {"perm_id": 2, "server_id": 50}, TICKET)
        cd = joiner.sent_of(222)[0]
        assert cd["port"] == config.WORLD_PORT, "lobby-world join must stay on WORLD_PORT (:5479)"
        assert cd["port"] != config.GAME_PORT
    finally:
        config.MULTI_CLIENT_HOSTING = saved
        config.GAME_CONN_VIA_STUB = saved_via
        registry.games.clear()


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
    print("All multi-client tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
