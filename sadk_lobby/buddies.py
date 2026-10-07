"""
Buddy list and presence (docs/message-catalog.md, tincat3: buddies 56/61/98/99).

  56 RequestUserBuddyList {user_id}   -> N x 61 UserBuddyConn on the 56 ticket, then Result(42)
  98 AddUserBuddy {user_id, buddy_id}    -> Result(42) errorcode 0 (client adds it, offline) / 1 refused
  99 RemoveUserBuddy {user_id, buddy_id} -> Result(42) errorcode 0
  61 UserBuddyConn with ticket 0 = a presence PUSH: inserts/overwrites the buddy in the client's map
     (UserManager T 1002dce0 -> BuddyUpdateReceived S 00476f90). perm_id_type must be 2.

Server decisions (T24–T29):
  * One-way lists per perm_id, in memory for the process lifetime (perm_ids are not stable across
    restarts). At most MAX_BUDDIES each.
  * Refusals (self, unknown id, already a buddy, full list) get errorcode 1 (T28).
  * Presence status (T26): 1 = online in the lobby, 0 = offline. Status 3 ("on a server") is not used yet.
  * Pushes go only to players who list the user as a buddy (T27), on lobby-login completion and on
    lobby disconnect (T25), plus one after a successful add (T29).
"""
import threading

from . import codec, players
from .log import log

MAX_BUDDIES = 100
PERM_ID_TYPE = 2
STATUS_OFFLINE, STATUS_ONLINE = 0, 1

_lock = threading.Lock()
_lists = {}            # owner perm_id -> list of buddy perm_ids (insertion order)
_online = set()        # perm_ids with a logged-in lobby connection


def reset_for_tests():
    with _lock:
        _lists.clear()
        _online.clear()


def _name(perm_id):
    p = next((p for p in players.all_players() if p.perm_id == perm_id), None)
    return p.char_name if p else f"Player {perm_id}"


def row(owner, buddy_id, ticket):
    status = STATUS_ONLINE if buddy_id in _online else STATUS_OFFLINE
    return codec.encode_body(61, {"user_id": owner, "buddy_id": buddy_id, "name": _name(buddy_id),
                                  "perm_id_type": PERM_ID_TYPE, "status": status, "server_id": 0,
                                  "server_name": None, "ticket_id": ticket})


def send_list(conn, owner, ticket):
    with _lock:
        mine = list(_lists.get(owner, ()))
    for b in mine:
        conn.send_app(61, row(owner, b, ticket))
    conn.ok(ticket)
    if mine:
        log(f"  [BUDDY] list of {owner}: {len(mine)} buddy(ies) + OK")


def add(owner, buddy_id):
    """Returns 0 on success, else the errorcode (T28)."""
    known = any(p.perm_id == buddy_id for p in players.all_players())
    with _lock:
        mine = _lists.setdefault(owner, [])
        if buddy_id == owner or not known or buddy_id in mine or len(mine) >= MAX_BUDDIES:
            return 1
        mine.append(buddy_id)
        return 0


def remove(owner, buddy_id):
    with _lock:
        mine = _lists.get(owner, [])
        if buddy_id in mine:
            mine.remove(buddy_id)
    return 0


def push_presence(perm_id, online, lobby_conn_of):
    """Tell every online player who lists `perm_id` as a buddy about its new status (ticket 0).
    `lobby_conn_of(perm_id)` returns that player's live lobby connection or None."""
    with _lock:
        if online:
            _online.add(perm_id)
        else:
            _online.discard(perm_id)
        watchers = [o for o, lst in _lists.items() if perm_id in lst and o in _online]
    told = 0
    for o in watchers:
        c = lobby_conn_of(o)
        if c is None:
            continue
        try:
            c.send_app(61, row(o, perm_id, 0))
            told += 1
        except Exception:  # noqa: BLE001
            pass
    if told:
        log(f"  [BUDDY] {_name(perm_id)!r} is now {'online' if online else 'offline'} — told {told} player(s)")


def push_one(conn, owner, buddy_id):
    """A single presence push of `buddy_id` to `owner` (after a successful add, T29)."""
    conn.send_app(61, row(owner, buddy_id, 0))
