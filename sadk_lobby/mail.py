"""
Private mail — the tincat3 MailManager / SADK PostOffice protocol (docs/message-catalog.md, tincat3).

  150 AddPrivateMessage     C->S  completes ONLY on AddResult(153). A Result(42) is ignored: the ticket
                                  leaks, MailManager busy +0x34 stays set and the PostOffice queue stalls.
  147 RequestPrivateMessageList   one 149 per mail, then Result(42) on the 147 ticket. Records carry the
                                  full message_text: opening a mail is answered from the client's 149 cache.
  148 ChangePrivateMessage  C->S  mark read (status 1) -> Result(42).
  151 RemovePrivateMessage  C->S  delete -> Result(42); later lists must not include it.

Server decisions (catalog T11-T23):
  * Mail lives in memory for the life of the server process (T11). perm_ids are handed out per name in
    first-login order (players.py), so they are not stable across restarts; persisting mail by perm_id
    could deliver it to the wrong player after a restart.
  * message_id: a server-wide counter from 1 (T14; 0 is rejected by every PostOffice operation).
  * creation_time: Unix seconds (T15). data: empty (T16). message_text: the sender's bytes unchanged (T17).
  * An unknown recipient gets AddResult errorcode 1 (T22). No push to an online recipient: the client
    picks new mail up on its next 60-s list poll (T23).
  * Lists are newest first, at most 100 records (T12/T13). Deletes are hard (T20).
"""
import threading
import time

from . import codec
from .log import log

MAX_LIST = 100

_lock = threading.Lock()
_next_id = 1
_mails = {}          # message_id -> record dict


def add(delivery_target, creator, title, message_text):
    """Store one mail; returns its message_id."""
    global _next_id
    with _lock:
        mid = _next_id
        _next_id += 1
        _mails[mid] = {
            "delivery_target": delivery_target, "message_id": mid, "creator": creator,
            "creation_time": int(time.time()), "title": title or "", "status": 0,
            "message_text": message_text or b"\x00", "data": b"",
        }
        return mid


def inbox(delivery_target):
    """Copies of the recipient's mails, newest first, capped at MAX_LIST."""
    with _lock:
        mine = [dict(m) for m in _mails.values() if m["delivery_target"] == delivery_target]
    mine.sort(key=lambda m: m["message_id"], reverse=True)
    return mine[:MAX_LIST]


def mark(message_id, status):
    with _lock:
        if message_id in _mails:
            _mails[message_id]["status"] = 1 if status else 0
            return True
        return False


def remove(message_id):
    with _lock:
        return _mails.pop(message_id, None) is not None


def reset_for_tests():
    global _next_id
    with _lock:
        _mails.clear()
        _next_id = 1


def send_inbox(conn, delivery_target, ticket):
    """147 answer: one 149 per mail, then the Result that hands them to PostOffice."""
    mails = inbox(delivery_target)
    for m in mails:
        conn.send_app(149, codec.encode_body(149, {**m, "ticket_id": ticket}))
    conn.ok(ticket)
    if mails:
        log(f"  [MAIL] inbox of {delivery_target}: sent {len(mails)} mail(s) + OK")
