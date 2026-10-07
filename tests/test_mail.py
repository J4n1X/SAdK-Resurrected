"""
Mail round trip (offline): 150 completes with AddResult(153), 147 lists full 149 records then
Result(42), 148 marks read, 151 deletes. Mail goes from character to character: the client finds the
recipient by name and shows the sender by id through RequestCharacters (72) lookups, taking the first
75 row (CharacterDataReceived S 00473590). See sadk_lobby/mail.py and docs/message-catalog.md 147-151.

Run:  python tests/test_mail.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))  # never touch the real store
from sadk_lobby import codec, dispatch, mail, players, store  # noqa: E402

TICKET = 0x96


class FakeConn:
    def __init__(self, player):
        self.player = player
        self.sent = []
        self.acked = []
        self.results = []

    def send_app(self, type_num, body):
        self.sent.append((type_num, codec.decode_body(type_num, body)))

    def ok(self, ticket):
        self.acked.append(ticket)

    def status_with_id(self, errorcode, obj_id, ticket):
        self.results.append((errorcode, obj_id, ticket))


def _send(conn, to, title, text):
    dispatch.dispatch_lobby(conn, 150, {"delivery_target": to, "creator": conn.player.perm_id,
                                         "creation_time": 0, "title": title, "message_text": text,
                                         "data": b"", "ticket_id": TICKET})


def _lookup(conn, **want):
    conn.sent.clear()
    dispatch.dispatch_lobby(conn, 72, {"char_id": want.get("char_id", 0), "name": want.get("name"),
                                       "selection": 0, "ticket_id": 0x48})
    return [f for t, f in conn.sent if t == 75]


def test_mail_round_trip():
    store.reset_for_tests(os.path.join(tempfile.mkdtemp(), "players.json"))
    mail.reset_for_tests()
    alice = FakeConn(players.resolve_by_username("mail_alice"))
    bob = FakeConn(players.resolve_by_username("mail_bob"))
    a_char = int(store.create_character("mail_alice", "Alicia", b"\x00" * 24)["char_id"])
    b_char = int(store.create_character("mail_bob", "Bobby", b"\x00" * 24)["char_id"])

    rows = _lookup(alice, name="bobby")                   # LookUpID: the recipient, by name
    assert [r["char_id"] for r in rows] == [b_char] and rows[0]["owner_id"] == bob.player.user_id
    assert _lookup(alice, name="nobody") == []            # unknown -> no row (client: id 0)

    _send(alice, b_char, "Hallo", b"Wie geht's?\x00")
    assert alice.results == [(0, 1, TICKET)], alice.results        # AddResult, never Result(42)
    assert alice.acked[-1] == 0x48

    bob.acked.clear()
    dispatch.dispatch_lobby(bob, 147, {"delivery_target": b_char, "selection": 0, "ticket_id": 0x93})
    recs = [f for t, f in bob.sent if t == 149]
    assert len(recs) == 1 and bob.acked == [0x93]
    r = recs[0]
    assert r["message_id"] == 1 and r["creator"] == a_char         # the sender's CHARACTER
    assert r["title"] == "Hallo" and r["message_text"] == b"Wie geht's?\x00" and r["status"] == 0
    rows = _lookup(bob, char_id=a_char)                   # LookUpName: the sender's name, by id
    assert [x["name"] for x in rows] == ["Alicia"]

    dispatch.dispatch_lobby(bob, 148, {"message_id": 1, "status": 1, "ticket_id": 0x94})
    assert mail.inbox(b_char)[0]["status"] == 1
    dispatch.dispatch_lobby(bob, 151, {"message_id": 1, "ticket_id": 0x97})
    assert mail.inbox(b_char) == []
    print("mail round trip between characters, name/id lookups OK")


def test_unknown_recipient_fails():
    mail.reset_for_tests()
    alice = FakeConn(players.resolve_by_username("mail_alice"))
    _send(alice, 0x7FFFFF01, "?", b"x\x00")
    assert alice.results == [(1, 0, TICKET)] and mail.inbox(0x7FFFFF01) == []
    print("unknown recipient → AddResult errorcode 1 OK")


def test_buddy_observers_use_addresult():
    me = FakeConn(players.resolve_by_username("mail_alice"))
    dispatch.dispatch_lobby(me, 175, {"user_id": me.player.perm_id, "send_all": True, "ticket_id": 0xAF})
    dispatch.dispatch_lobby(me, 176, {"user_id": me.player.perm_id, "ticket_id": 0xB0})
    assert [t for _, _, t in me.results] == [0xAF, 0xB0] and me.acked == []
    print("175/176 → AddResult(153) OK")


if __name__ == "__main__":
    test_mail_round_trip()
    test_unknown_recipient_fails()
    test_buddy_observers_use_addresult()
    print("\nAll mail tests PASSED")
