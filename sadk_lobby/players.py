"""
Multi-user player support — the LOGIN NAME *is* the identity.

Any number of clients can be logged in at once. A "player" is one account identity served
across that client's several connections (lobby / UC-chat / village / referee), resolved by:

  * lobby connection    -> the `username` in the ECDH auth blob (203/204/206)
  * UC + village conns  -> the `perm_id` carried in the token (213 SendToken)

The lobby login completes first and issues the perm_id in SessionKey(207); the client then
presents that perm_id on its other connections, so every socket maps back to the same player.

⭐ **The username becomes the character name.** Whatever a tester types in the game's login box
is the name over their settler, in the chat roster and on their hosted games. Nothing is
predefined — there is no account table, and no "Testler"/"Siedler" mapping.

⭐ **Passwords, serials and CD-keys are NOT checked** — anywhere. `crypto.decode_login_blob`
decodes them so they can be logged, and no code path compares them against anything (the
handshake serial is logged only, `connection._handle_handshake`). So a tester needs no
credentials beyond picking a username nobody else is using.

`perm_id`s are handed out sequentially from 1 in first-seen order and are stable per name (case
insensitive) for the life of the process, so a player who drops and reconnects keeps the same
identity — which matters because **the client's own avatar id IS its PermID**, so a changing
perm_id would orphan their avatar for everyone else.

⚠️ Two clients must use DIFFERENT usernames. Same name = same identity = the second login takes
over the first player's perm_id, and the world cannot tell them apart.
"""
import threading
from dataclasses import dataclass

from . import config, store

#: msgdefs character-name fields are `STRING 32`; leave room for the terminator. The name also
#: rides the bit-packed AvatarStyle block (`village.avatar_style_block`), whose length prefix is
#: 8 bits — so anything under 255 is safe there, and 31 keeps the NETMSG side happy too.
MAX_NAME_LEN = 31


@dataclass
class Player:
    perm_id: int
    char_id: int        # ⭐ ALWAYS == perm_id; the client's own avatar id is its PermID and the
                        # CharacterManager is keyed by char_id (see store.py's docstring).
    username: str       # account / login name (the auth-blob username)
    char_name: str      # in-lobby character name — the created character's name, else the login
    data: bytes         # the character blob the CLIENT authored, or b"" if none exists yet

    @property
    def has_character(self):
        """False until the player has been through character creation. A player without a
        character is a normal state — `dispatch` answers RequestCharacters with an empty list
        and the client opens its creation flow."""
        return bool(self.data)


_lock = threading.RLock()
_by_perm = {}                       # perm_id           -> Player
_by_user = {}                       # username.lower()  -> Player
_guest_seq = 0                      # for logins that arrive without a usable username


def _clean(name):
    """A login name reduced to something safe to show and to put on the wire."""
    name = "".join(ch for ch in (name or "") if ch.isprintable()).strip()
    return name[:MAX_NAME_LEN]


def _from_store(name):
    """Build (or rebuild) the in-memory Player for `name` from the persistent store.

    The perm_id comes from the store and never changes across restarts — that is a protocol
    requirement, not a nicety: char_id == perm_id, and a returning player issued a fresh id
    would no longer match their own stored character (store.py docstring). Caller holds `_lock`.
    """
    rec = store.get_or_create_player(name)
    perm = int(rec["perm_id"])
    char = store.get_character(name)
    p = Player(perm_id=perm, char_id=perm, username=name,
               char_name=(char["name"] if char else name),
               data=(char["data"] if char else b""))
    _by_perm[perm] = p
    _by_user[name.lower()] = p
    return p


def refresh_from_store(username):
    """Re-read a player's character after creation/change/deletion, so the live Player object
    stops disagreeing with the disk."""
    with _lock:
        p = _by_user.get((username or "").lower())
        if p is None:
            return _from_store(username)
        char = store.get_character(username)
        p.char_name = char["name"] if char else p.username
        p.data = char["data"] if char else b""
        return p


def resolve_by_username(username):
    """Lobby-connection resolution: get-or-create the player for this login name.

    An empty or undecodable username gets its own fresh `Guest N` identity rather than sharing a
    common default — otherwise every client whose auth blob failed to decrypt would collapse onto
    one perm_id and appear in the world as the same settler."""
    with _lock:
        name = _clean(username)
        if not name:
            global _guest_seq
            _guest_seq += 1
            name = f"Guest {_guest_seq}"
        return _by_user.get(name.lower()) or _from_store(name)


def resolve_by_perm(perm_id):
    """UC/village/referee-connection resolution from the token perm_id.

    An id we have not issued (a stale token, or a client reconnecting after a server restart)
    registers a placeholder that KEEPS that id, so the client's avatar id and ours stay in
    agreement instead of silently becoming a different player."""
    with _lock:
        p = _by_perm.get(perm_id)
        if p is not None:
            return p
        # Not in memory: the store may still know this id (a client reconnecting across a
        # restart presents the perm_id it was issued last time — that is the whole point of
        # persisting it). Reserve it either way so it is never handed to someone else.
        rec = store.reserve_perm_id(perm_id)
        username = rec.get("username") or f"Player {perm_id}"
        char = store.get_character(username)
        p = Player(perm_id=perm_id, char_id=perm_id, username=username,
                   char_name=(char["name"] if char else username),
                   data=(char["data"] if char else b""))
        _by_perm[perm_id] = p
        _by_user.setdefault(username.lower(), p)
        return p


def of(conn):
    """The player a connection is serving.

    A connection that asks before its login has resolved gets its OWN guest identity, cached on
    the connection — never a shared default, so two un-resolved clients are never the same
    player. The real login (`resolve_by_username` / `resolve_by_perm`) overwrites `conn.player`
    when it arrives."""
    p = getattr(conn, "player", None)
    if p is None:
        p = resolve_by_username(None)
        try:
            conn.player = p
        except Exception:  # noqa: BLE001 — a read-only stand-in conn must not break resolution
            pass
    return p


def default_player():
    """Defensive fallback only: the first identity registered this session, or a fresh guest.
    Nothing on the login path uses this — `of()` mints a per-connection guest instead."""
    with _lock:
        if _by_perm:
            return _by_perm[min(_by_perm)]
        return resolve_by_username(None)


def all_players():
    """Every identity seen this session (for logging / diagnostics)."""
    with _lock:
        return [_by_perm[k] for k in sorted(_by_perm)]
