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
from .log import log

#: msgdefs character-name fields are `STRING 32`; leave room for the terminator. The name also
#: rides the bit-packed AvatarStyle block (`village.avatar_style_block`), whose length prefix is
#: 8 bits — so anything under 255 is safe there, and 31 keeps the NETMSG side happy too.
MAX_NAME_LEN = 31


@dataclass
class Player:
    """One identity in play on a set of connections.

    A player resolved from a LOGIN NAME is the ACCOUNT (perm_id == user_id, no character bound
    yet — the client has not chosen one). A player resolved from a TOKEN perm_id that names a
    character is that CHARACTER (perm_id == char_id), because the client's own avatar id is its
    PermID. Both shapes carry the owning account's `user_id`, which is the `owner_id` on the
    wire."""
    perm_id: int        # the id THIS connection is identified by (user_id or char_id)
    char_id: int        # the bound character's id, or 0 when none is bound
    user_id: int        # the owning ACCOUNT id — CharacterData's `owner_id`
    username: str       # account / login name (the auth-blob username)
    char_name: str      # bound character's name, else the login name
    data: bytes         # the character blob the CLIENT authored, or b"" when none is bound

    @property
    def has_character(self):
        """Whether a specific character is bound to this identity. False is a normal state —
        a fresh account has none, and `dispatch` then answers RequestCharacters with an empty
        list so the client opens its creation flow."""
        return bool(self.char_id)


_lock = threading.RLock()
_by_perm = {}                       # perm_id           -> Player
_by_user = {}                       # username.lower()  -> Player
#: perm_ids whose LOBBY login (204 -> 207) happened in this server process. A token (213/224) is only
#: honoured for these: a client that reconnects its UC/world sockets with a token from an earlier
#: server run would otherwise silently become whoever owns that id now (live 2026-10-07 11:04: the
#: VM's stale token named J4n1X's id, took over J4n1X's chat roster slots and broke chat and presence).
_issued = set()
_guest_seq = 0                      # for logins that arrive without a usable username
_next_perm = 1                      # LEGACY path only: first player logging in becomes perm_id 1


def _clean(name):
    """A login name reduced to something safe to show and to put on the wire."""
    name = "".join(ch for ch in (name or "") if ch.isprintable()).strip()
    return name[:MAX_NAME_LEN]


def _create_legacy(name):
    """The pre-persistence identity shape: char_id == perm_id and the shared `NICKNAME_DATA`
    appearance, used while `config.PERSISTENT_CHARACTERS_ENABLED` is False.

    The perm_id comes from the account store (`store.get_or_create_account`), so it is STABLE per
    login name across server restarts. It used to be an in-memory sequential id: after a restart a
    client that reconnected its UC/world sockets with its old token became a "Player N" placeholder,
    and its next real login got a different id, which sent it into a broken character-creation
    screen (live 2026-10-07 10:17-10:20). Caller holds `_lock`."""
    perm = int(store.get_or_create_account(name)["user_id"])
    p = Player(perm_id=perm, char_id=perm, user_id=perm, username=name,
               char_name=name, data=config.NICKNAME_DATA)
    stale = _by_perm.get(perm)
    if stale is not None:                  # a placeholder made from this id's token: same player
        _by_user.pop(stale.username.lower(), None)
    _by_perm[perm] = p
    _by_user[name.lower()] = p
    return p


def _from_store(name):
    """Build (or rebuild) the in-memory ACCOUNT-level Player for `name`.

    The user_id comes from the store and never changes across restarts — a returning player
    issued a fresh id would no longer own their own characters. No character is bound yet: the
    client has not chosen one at login time. Caller holds `_lock`."""
    rec = store.get_or_create_account(name)
    user_id = int(rec["user_id"])
    p = Player(perm_id=user_id, char_id=0, user_id=user_id, username=name,
               char_name=name, data=b"")
    _by_perm[user_id] = p
    _by_user[name.lower()] = p
    return p


def bind_character(player, char):
    """Bind a stored character to a live identity (or unbind it when `char` is None)."""
    with _lock:
        if char:
            player.char_id = int(char["char_id"])
            player.char_name = char.get("name") or player.username
            player.data = char.get("data") or b""
        else:
            player.char_id = 0
            player.char_name = player.username
            player.data = b""
        return player


def refresh_from_store(username):
    """Re-read the bound character after a create/change/delete, so the live Player object
    stops disagreeing with the disk. A player whose bound character was deleted is unbound."""
    with _lock:
        p = _by_user.get((username or "").lower())
        if p is None:
            return _from_store(username)
        if p.char_id:
            char, _acct = store.find_character(p.char_id)
            bind_character(p, char)          # char is None if it was just deleted → unbind
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
        existing = _by_user.get(name.lower())
        if existing is None:
            existing = (_from_store(name) if config.PERSISTENT_CHARACTERS_ENABLED
                        else _create_legacy(name))
        _issued.add(existing.perm_id)
        return existing


def issued(perm_id):
    """Whether this perm_id logged in through the lobby in this server process."""
    with _lock:
        return perm_id in _issued


def resolve_by_perm(perm_id):
    """UC/village/referee-connection resolution from the token perm_id.

    An id we have not issued (a stale token, or a client reconnecting after a server restart)
    registers a placeholder that KEEPS that id, so the client's avatar id and ours stay in
    agreement instead of silently becoming a different player."""
    with _lock:
        p = _by_perm.get(perm_id)
        if p is not None:
            return p
        if not config.PERSISTENT_CHARACTERS_ENABLED:
            # LEGACY: the id keeps its value, so the client's avatar id and ours stay in agreement.
            # The name comes from the account store when the id is known there (a client that
            # reconnects with its old token after a server restart keeps its name).
            rec = next((a for a in store.all_players() if int(a["user_id"]) == int(perm_id)), None)
            if rec is None:
                rec = store.reserve_user_id(perm_id)
            name = rec.get("username") or f"Player {perm_id}"
            p = Player(perm_id=perm_id, char_id=perm_id, user_id=perm_id,
                       username=name, char_name=name, data=config.NICKNAME_DATA)
            _by_perm[perm_id] = p
            _by_user.setdefault(p.username.lower(), p)
            return p
        # ⭐ DUAL LOOKUP. A token's perm_id may name either a CHARACTER or an ACCOUNT, and which
        # one the client sends is the open question (store.py docstring): the own-avatar id is
        # the PermID and the CharacterManager is keyed by char_id, which says character — but
        # that has not been observed live with the two ids differing. Characters are checked
        # first, and the match KIND is logged, so one login with two characters settles it
        # without a guess having been baked into the wire.
        char, acct = store.find_character(perm_id)
        if char is not None:
            username = acct.get("username") or f"Player {perm_id}"
            p = Player(perm_id=perm_id, char_id=int(char["char_id"]),
                       user_id=int(acct["user_id"]), username=username,
                       char_name=char.get("name") or username, data=char.get("data") or b"")
            log(f"  [PLAYER] token perm_id {perm_id} matched a CHARACTER "
                f"({p.char_name!r} on account {username!r}, user_id {p.user_id})")
        else:
            # Not a character: treat it as an account id, reserving it if we have never issued
            # it (a stale token, or a client reconnecting across a restart).
            rec = store.reserve_user_id(perm_id)
            username = rec.get("username") or f"Player {perm_id}"
            chars = rec.get("characters") or []
            bound = chars[0] if len(chars) == 1 else None
            p = Player(perm_id=perm_id, char_id=int(bound["char_id"]) if bound else 0,
                       user_id=int(rec["user_id"]), username=username,
                       char_name=(bound.get("name") if bound else username) or username,
                       data=(bound.get("data") if bound else b"") or b"")
            log(f"  [PLAYER] token perm_id {perm_id} matched an ACCOUNT ({username!r}, "
                f"{len(chars)} character(s))"
                + (f" — auto-bound its only character {p.char_name!r}" if bound else ""))
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
