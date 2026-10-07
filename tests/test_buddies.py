"""
Buddies (offline): 98 add / 99 remove answer a Result with a real errorcode, 56 lists 61 rows before
its Result, presence is pushed (ticket 0) to watchers on login completion and lobby disconnect.

Run:  python tests/test_buddies.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))  # never touch the real store
from sadk_lobby import buddies, codec, dispatch, players  # noqa: E402


class Lobby:
    role = "lobby"

    def __init__(self, name):
        self.player = players.resolve_by_username(name)
        self.alive = True
        self.sent = []
        self.results = []

    def send_app(self, t, body):
        self.sent.append((t, codec.decode_body(t, body)))

    def ok(self, ticket):
        self.results.append((0, ticket))

    def result(self, err, ticket):
        self.results.append((err, ticket))


def test_add_list_presence():
    buddies.reset_for_tests()
    a, b = Lobby("bud_anna"), Lobby("bud_ben")
    for c in (a, b):
        dispatch._live.append(c)
    try:
        dispatch.dispatch_lobby(a, 157, {"ticket_id": 1})          # A finished logging in
        dispatch.dispatch_lobby(a, 98, {"user_id": a.player.perm_id, "buddy_id": b.player.perm_id,
                                        "ticket_id": 0x62})
        assert a.results[-1] == (0, 0x62)
        push = [f for t, f in a.sent if t == 61][-1]
        assert push["buddy_id"] == b.player.perm_id and push["ticket_id"] == 0 and push["status"] == 0
        # refusals: self, duplicate, unknown id
        for bad in (a.player.perm_id, b.player.perm_id, 0x7FFF0001):
            dispatch.dispatch_lobby(a, 98, {"user_id": a.player.perm_id, "buddy_id": bad, "ticket_id": 0x62})
            assert a.results[-1] == (1, 0x62), bad
        # B logs in → A (a watcher, online) gets status 1
        a.sent.clear()
        dispatch.dispatch_lobby(b, 157, {"ticket_id": 2})
        assert [(f["buddy_id"], f["status"]) for t, f in a.sent if t == 61] == [(b.player.perm_id, 1)]
        # list: one row on the 56 ticket, then the Result
        a.sent.clear()
        dispatch.dispatch_lobby(a, 56, {"user_id": a.player.perm_id, "ticket_id": 0x38})
        rows = [f for t, f in a.sent if t == 61]
        assert len(rows) == 1 and rows[0]["ticket_id"] == 0x38 and rows[0]["name"] == "bud_ben"
        assert a.results[-1] == (0, 0x38)
        # B's lobby socket goes away → A gets status 0
        a.sent.clear()
        b.alive = False
        dispatch.on_conn_closed(b)
        assert [(f["buddy_id"], f["status"]) for t, f in a.sent if t == 61] == [(b.player.perm_id, 0)]
        dispatch.dispatch_lobby(a, 99, {"user_id": a.player.perm_id, "buddy_id": b.player.perm_id,
                                        "ticket_id": 0x63})
        assert a.results[-1] == (0, 0x63) and buddies._lists[a.player.perm_id] == []
    finally:
        for c in (a, b):
            if c in dispatch._live:
                dispatch._live.remove(c)
    print("buddy add / refuse / list / presence OK")


if __name__ == "__main__":
    test_add_list_presence()
    print("\nAll buddy tests PASSED")
