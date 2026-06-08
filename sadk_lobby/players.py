"""
Multi-user player support (s39.5).

Lazily lets MORE THAN ONE client log in as DISTINCT players (a host + a joiner) so
game hosting and joining can be tested. A "player" is one account identity served
across that client's three connections (lobby / UC-chat / village), resolved by:

  * lobby connection    -> the `username` in the ECDH auth blob (203/204/206)
  * UC + village conns  -> the `perm_id` carried in the token (213 SendToken)

The lobby login completes first and issues the perm_id in SessionKey(207); the
client then presents that perm_id on its UC and village connections, so resolving
those by perm_id maps all three sockets back to the same player.

DEFAULT-SAFE: PLAYERS[0] is byte-identical to the long-standing hardcoded test
identity (config.TEST_*). With one client on the default account the wire output is
unchanged. Per-login resolution and auto-registration only happen when
config.MULTI_CLIENT_HOSTING is True (see config.py / HARNESS.md); otherwise every
connection keeps serving the default player.
"""
import threading
from dataclasses import dataclass

from . import config


@dataclass
class Player:
    perm_id: int
    char_id: int
    username: str       # account / login name (the auth-blob username)
    char_name: str      # in-lobby character / nickname
    data: bytes         # appearance blob (shared NICKNAME_DATA for now — lazy)


_lock = threading.Lock()
_by_perm = {}                       # perm_id           -> Player
_by_user = {}                       # username.lower()  -> Player
_next_auto_perm = 1000              # auto-registered players start well above PLAYERS


def _register(p):
    _by_perm[p.perm_id] = p
    _by_user[p.username.lower()] = p
    return p


def _seed():
    """Populate the table from config.PLAYERS (idempotent)."""
    for spec in config.PLAYERS:
        if spec["perm_id"] not in _by_perm:
            _register(Player(perm_id=spec["perm_id"], char_id=spec["char_id"],
                             username=spec["username"], char_name=spec["char_name"],
                             data=config.NICKNAME_DATA))


# Seed predefined players at import; the default/test account is always present.
_seed()


def default_player():
    """The fallback identity — byte-identical to the old hardcoded test account."""
    return _by_perm.get(config.TEST_PERM_ID) or next(iter(_by_perm.values()))


def of(conn):
    """The player a connection is serving (default until login resolves one)."""
    return getattr(conn, "player", None) or default_player()


def resolve_by_username(username):
    """Lobby-connection resolution. Returns the matching player; with multi-user on,
    auto-registers a fresh player for an unknown username (lazy). Empty/unknown with
    multi-user off falls back to the default player (so the wire is unchanged)."""
    with _lock:
        _seed()
        if username:
            p = _by_user.get(username.lower())
            if p is not None:
                return p
            if config.MULTI_CLIENT_HOSTING:
                global _next_auto_perm
                perm = _next_auto_perm
                _next_auto_perm += 1
                return _register(Player(
                    perm_id=perm, char_id=perm, username=username,
                    char_name=(username[:31] or f"Player{perm}"),
                    data=config.NICKNAME_DATA))
        return default_player()


def resolve_by_perm(perm_id):
    """UC/village-connection resolution from the token perm_id. Falls back to the
    default player for an unknown perm_id."""
    with _lock:
        _seed()
        return _by_perm.get(perm_id, default_player())
