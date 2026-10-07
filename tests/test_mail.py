"""
Mail round trip (offline): 150 completes with AddResult(153), 147 lists full 149 records then
Result(42), 148 marks read, 151 deletes. See sadk_lobby/mail.py and docs/message-catalog.md 147-151.

Run:  python tests/test_mail.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import codec, dispatch, mail, players  # noqa: E402

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


def test_mail_round_trip():
    mail.reset_for_tests()
    alice = FakeConn(players.resolve_by_username("mail_alice"))
    bob = FakeConn(players.resolve_by_username("mail_bob"))

    _send(alice, bob.player.perm_id, "Hallo", b"Wie geht's?\x00")
    assert alice.results == [(0, 1, TICKET)], alice.results        # AddResult, never Result(42)
    assert alice.acked == []

    dispatch.dispatch_lobby(bob, 147, {"delivery_target": bob.player.perm_id, "selection": 0,
                                       "ticket_id": 0x93})
    recs = [f for t, f in bob.sent if t == 149]
    assert len(recs) == 1 and bob.acked == [0x93]
    r = recs[0]
    assert r["message_id"] == 1 and r["creator"] == alice.player.perm_id
    assert r["title"] == "Hallo" and r["message_text"] == b"Wie geht's?\x00" and r["status"] == 0

    dispatch.dispatch_lobby(bob, 148, {"message_id": 1, "status": 1, "ticket_id": 0x94})
    assert mail.inbox(bob.player.perm_id)[0]["status"] == 1
    dispatch.dispatch_lobby(bob, 151, {"message_id": 1, "ticket_id": 0x97})
    assert mail.inbox(bob.player.perm_id) == []
    print("mail round trip OK")


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
