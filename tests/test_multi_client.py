"""
Offline tests for multi-client hosting — multiple players + a global game registry,
so a host and a joiner are two DISTINCT players and one client's hosted game is visible
to (and joinable by) another. This is the default behaviour (no flags).

No live game, no sockets — codec + dispatch + players + registry logic only. Proves:
  1. Player resolution: lobby by username, UC/village by perm_id, auto-register.
  2. The global registry makes client A's hosted game (168) visible to client B's
     RequestServers(166) and resolvable by RequestConnectionData(221).
  3. Ownership cleanup: dropping the owning connection removes its games.

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


# ── 1. Player resolution ───────────────────────────────────────────────────────
def test_player_resolution_login_name_is_identity():
    # The login name IS the identity: no predefined accounts, sequential perm_ids,
    # stable per name (case-insensitive) for the life of the process.
    p1 = players.resolve_by_username("mc_alpha")
    p2 = players.resolve_by_username("mc_beta")
    assert p1.perm_id != p2.perm_id
    assert p1.char_name == "mc_alpha" and p2.char_name == "mc_beta"
    assert players.resolve_by_username("MC_BETA") is p2
    # UC/village conns resolve by the token perm_id back to the same players
    assert players.resolve_by_perm(p2.perm_id) is p2
    # an id we never issued keeps its value (the client's avatar id must not change)
    stray = players.resolve_by_perm(0xDEAD)
    assert stray.perm_id == 0xDEAD and stray.char_id == 0xDEAD


def test_empty_username_gets_own_guest_identity():
    # Undecodable logins must not collapse onto one perm_id (they would be one settler).
    g1 = players.resolve_by_username("")
    g2 = players.resolve_by_username(None)
    assert g1.perm_id != g2.perm_id
    assert g1.username.startswith("Guest ") and g2.username.startswith("Guest ")


# ── 2. Cross-client visibility + join resolution ───────────────────────────────
def test_hosted_game_visible_and_joinable_cross_client():
    registry.games.clear()
    try:
        host = FakeConn(1, addr=("10.0.0.5", 4444))
        host.player = players.resolve_by_username("mc_host")
        joiner = FakeConn(2, addr=("10.0.0.9", 5555))
        joiner.player = players.resolve_by_username("mc_joiner")

        # Host advertises its IP via 168 (ip="" → falls back to the conn's address).
        sid = _add_game(host, name="Steinfjord Duell", ip="", port=5479)

        # Joiner browses game servers (type 5) and sees the host's game.
        dispatch._send_server_list(joiner, 5, TICKET)
        games = joiner.sent_of(170)
        assert any(g["name"] == "Steinfjord Duell" for g in games), [g["name"] for g in games]
        g = next(g for g in games if g["name"] == "Steinfjord Duell")
        assert g["server_id"] == sid
        assert g["owner_id"] == host.player.perm_id   # owned by the host player
        assert g["server_subtype"] == 1            # game list (BrowseGameDialog)
        assert g["ip"] == "10.0.0.5"               # host's real address, not advertised default

        # Joiner clicks Join → 221 → 222 carries the host's address (P2P handoff).
        joiner.sent.clear()
        dispatch._h_connection_data(joiner, {"perm_id": joiner.player.perm_id, "server_id": sid}, TICKET)
        cd = joiner.sent_of(222)[0]
        assert cd["server_id"] == sid
        assert cd["ip"] == "10.0.0.5" and cd["port"] == 5479
        assert cd["perm_id"] == joiner.player.perm_id   # the joiner's perm_id
        assert cd["errorcode"] == 0
    finally:
        registry.games.clear()


def test_lobby_world_join_falls_back_to_world_port():
    """The lobby-world entry request (an unregistered server_id like the FAKE_VILLAGE's 50) must
    resolve to WORLD_PORT (:5479) so the client dials the village world and enters it."""
    registry.games.clear()
    try:
        joiner = FakeConn(2)
        dispatch._h_connection_data(joiner, {"perm_id": 2, "server_id": 50}, TICKET)
        cd = joiner.sent_of(222)[0]
        assert cd["port"] == config.WORLD_PORT
        assert cd["ip"] == config.ADVERTISED_IP
    finally:
        registry.games.clear()


# ── 3. Ownership cleanup on disconnect ─────────────────────────────────────────
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
