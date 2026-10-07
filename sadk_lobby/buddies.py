"""
Buddy list and presence (docs/message-catalog.md, tincat3: buddies 56/61/98/99).

  56 RequestUserBuddyList {user_id}      -> N x 61 UserBuddyConn on the 56 ticket, then Result(42)
  98 AddUserBuddy {user_id, buddy_id}    -> Result(42) errorcode 0 (client adds it) / 1 refused
  99 RemoveUserBuddy {user_id, buddy_id} -> Result(42) errorcode 0
  61 UserBuddyConn with ticket 0 = a presence PUSH: inserts/overwrites the buddy in the client's map
     (UserManager T 1002dce0 -> BuddyUpdateReceived S 00476f90). perm_id_type must be 2.

What the client does with it [known]:
  * FriendIgnoreListDialog (S 00452140 / S 00452400): "Add" adds the AVATAR selected in the 3D world
    (not an NPC, not the own id), so a buddy is a CHARACTER id; "Remove" needs a selected row. The
    list only shows the name, bright when the entry has a server, dim otherwise (S 004518a0).
  * AssignFromBuddyInfo S 0046b540 keeps a server only for status 3 with server_id >= 2; any other
    status clears it. So "online" for the client means status 3 + the id/name of the world the buddy
    is in. Double-clicking a row pre-fills "/tell <name>" (S 00451ec0).

Server decisions (T24-T29):
  * One list per ACCOUNT (the 207 perm_id the client sends as user_id), entries are character ids,
    persisted in the store, at most MAX_BUDDIES.
  * Refusals (one's own character, unknown character, already listed, full) get errorcode 1 (T28).
  * A character is online while it is in a world: status 3 with that world's server id/name.
  * Pushes go to the lobby connection of every account that lists the character, when it enters or
    leaves a world and after a successful add.
"""
import threading

from . import codec, store
from .log import log

MAX_BUDDIES = 100
PERM_ID_TYPE = 2
STATUS_OFFLINE, STATUS_ON_SERVER = 0, 3

_lock = threading.Lock()
_in_world = {}         # char_id -> (server_id, server_name)


def reset_for_tests():
    with _lock:
        _in_world.clear()


def _name(char_id):
    char, _acct = store.find_character(char_id)
    return char.get("name") if char else f"Player {char_id}"


def row(owner, buddy_id, ticket):
    with _lock:
        where = _in_world.get(buddy_id)
    status, server_id, server_name = (STATUS_ON_SERVER, *where) if where else (STATUS_OFFLINE, 0, None)
    return codec.encode_body(61, {"user_id": owner, "buddy_id": buddy_id, "name": _name(buddy_id),
                                  "perm_id_type": PERM_ID_TYPE, "status": status,
                                  "server_id": server_id, "server_name": server_name,
                                  "ticket_id": ticket})


def send_list(conn, owner, ticket):
    mine = store.buddies_of(owner)
    for b in mine:
        conn.send_app(61, row(owner, b, ticket))
    conn.ok(ticket)
    if mine:
        log(f"  [BUDDY] list of {owner}: {len(mine)} buddy(ies) + OK")


def add(owner, buddy_id):
    """Returns 0 on success, else the errorcode (T28)."""
    char, acct = store.find_character(buddy_id)
    mine = store.buddies_of(owner)
    if char is None or int(acct["user_id"]) == int(owner) or buddy_id in mine or len(mine) >= MAX_BUDDIES:
        return 1
    store.set_buddies(owner, mine + [buddy_id])
    return 0


def remove(owner, buddy_id):
    mine = store.buddies_of(owner)
    if buddy_id in mine:
        mine.remove(buddy_id)
        store.set_buddies(owner, mine)
    return 0


def set_location(char_id, server=None, lobby_conn_of=None):
    """`char_id` entered (server = (server_id, name)) or left (None) a world: tell every account that
    lists it, on its lobby connection (`lobby_conn_of(user_id)` -> conn or None)."""
    with _lock:
        if server:
            _in_world[char_id] = server
        else:
            _in_world.pop(char_id, None)
    told = 0
    for owner in store.owners_listing(char_id):
        c = lobby_conn_of(owner) if lobby_conn_of else None
        if c is None:
            continue
        try:
            c.send_app(61, row(owner, char_id, 0))
            told += 1
        except Exception:  # noqa: BLE001
            pass
    log(f"  [BUDDY] {_name(char_id)!r} is now {'in ' + server[1] if server else 'offline'}"
        + (f" — told {told} player(s)" if told else ""))


def push_one(conn, owner, buddy_id):
    """A single presence push of `buddy_id` to `owner` (after a successful add, T29)."""
    conn.send_app(61, row(owner, buddy_id, 0))
