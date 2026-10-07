"""
Buddies (offline): a buddy list belongs to an account and holds CHARACTER ids (the avatar picked in
the world, S 00452400); 98 / 99 answer a Result with a real errorcode, 56 lists 61 rows before its
Result, lists persist, and a buddy is online (status 3 + world id/name, the only state the client
draws bright, S 0046b540) while its character is in a world, pushed with ticket 0.

Run:  python tests/test_buddies.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))  # never touch the real store
from sadk_lobby import buddies, codec, dispatch, players, store  # noqa: E402


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


def _rows(conn):
    return [f for t, f in conn.sent if t == 61]


def test_add_list_presence():
    store.reset_for_tests(os.path.join(tempfile.mkdtemp(), "players.json"))
    buddies.reset_for_tests()
    a, b = Lobby("bud_anna"), Lobby("bud_ben")
    ben_char = int(store.create_character("bud_ben", "Benno", b"\x00" * 24)["char_id"])
    anna_char = int(store.create_character("bud_anna", "Anni", b"\x00" * 24)["char_id"])
    lobby_of = lambda uid: {a.player.perm_id: a, b.player.perm_id: b}.get(uid)   # noqa: E731
    # Anna adds Ben's avatar (a character id) — offline at first.
    dispatch._h_add_buddy(a, {"buddy_id": ben_char}, 0x62)
    assert a.results[-1] == (0, 0x62)
    push = _rows(a)[-1]
    assert push["buddy_id"] == ben_char and push["name"] == "Benno" and push["status"] == 0
    assert push["perm_id_type"] == 2 and push["ticket_id"] == 0
    # Refusals: her own character, an unknown id, a duplicate.
    for bad in (anna_char, 999999, ben_char):
        dispatch._h_add_buddy(a, {"buddy_id": bad}, 0x62)
        assert a.results[-1] == (1, 0x62), bad
    # Ben's character enters the world: Anna is told he is on world 50.
    buddies.set_location(ben_char, (50, "world1"), lobby_of)
    push = _rows(a)[-1]
    assert (push["status"], push["server_id"], push["server_name"]) == (3, 50, "world1")
    # The list (a restart in between: lists are persisted).
    a.sent.clear()
    dispatch._h_buddy_list(a, {}, 0x38)
    rows = _rows(a)
    assert [(r["buddy_id"], r["status"], r["ticket_id"]) for r in rows] == [(ben_char, 3, 0x38)]
    assert a.results[-1] == (0, 0x38)
    assert store.buddies_of(a.player.perm_id) == [ben_char]
    # He leaves the world: offline again.
    buddies.set_location(ben_char, None, lobby_of)
    assert _rows(a)[-1]["status"] == 0
    # Remove.
    dispatch._h_remove_buddy(a, {"buddy_id": ben_char}, 0x63)
    assert a.results[-1] == (0, 0x63) and store.buddies_of(a.player.perm_id) == []
    print("buddies: characters as entries, refusals, world presence, persisted list OK")


if __name__ == "__main__":
    test_add_list_presence()
    print("\nAll buddy tests PASSED")
