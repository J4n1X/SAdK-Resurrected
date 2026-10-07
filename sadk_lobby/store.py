"""
Persistent player state — identity + character, on disk.

Until now every identity was ephemeral: perm_ids were handed out sequentially per process
and every player wore the same hardcoded appearance blob (`config.NICKNAME_DATA`, lifted
from the AdK emulator — its zlib payload literally contains the name "tester"). A restart
meant a new you.

This module is the store behind `players.py` and the character handlers in `dispatch.py`.

## The model: an ACCOUNT owns MANY CHARACTERS

`msgdefs.ini` is explicit — `CharacterData(75)` carries **both** `char_id` and `owner_id`, so
these are two different namespaces, and the stub used to conflate them (both = perm_id), which
only held together while every account had exactly one character.

* **account** — keyed by login name, has a stable `user_id` (the `owner_id` on the wire).
* **character** — has its own globally unique `char_id`, allocated from `CHAR_ID_BASE` so the
  two id spaces never overlap in a log or a lookup. Kept below `npcs.NPC_ID_BASE` (1e6) because
  a character id also travels as an **avatar id** in the world, where NPCs live.

⭐ **Which id becomes the session identity?** The client's own avatar id IS its PermID, and
`CharacterDataReceived@0x00474910` keys the CharacterManager by `char_id`; the own-avatar
lookup then searches that manager by avatar id (miss ⇒ *"WTF?! There is no avatar with that id
in the CharacterManager"* ⇒ failed village login). That says the token's perm_id is the
**selected character's** id, not the account's. [TODO] not yet observed live with a
character id that differs from the account id — so `players.resolve_by_perm` looks up
**characters first, then accounts**, and logs which kind it matched. One live login with two
characters settles it either way without a guess baked into the wire.

* **The character's `data` blob is stored verbatim.** The CLIENT authors it at creation
  (`CreateCharacterFromPreview`, msg 77) — a zlib-wrapped record carrying the name in UTF-16LE
  plus appearance/stat fields, which `CommLayer::Character::GetData(i)` splits into **six**
  sub-blocks. We deliberately do NOT parse or synthesise it: replaying the client's own bytes
  is both correct store behaviour and the only way to be sure we are not corrupting a format we
  have not fully reversed. [TODO] the six-slot inner layout.

## Format

A single JSON file (default `sadk_players.json` beside the log, override with
`SADK_STORE_PATH`). Written atomically — temp file + `os.replace` — so a crash or a
concurrent read never sees a half-written file. Blobs are stored hex-encoded because JSON
has no byte type. A v1 store (one character per account, char_id == user_id) is migrated
forward automatically on load.

⚠️ Deliberately NOT in `config.py`: the deploy server's `config.py` is local-only and must be
merged by hand (see HANDOFF.md), so keeping the path here means deploying this file is a
plain copy.
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

from . import config
from .log import log

#: Where the store lives. Env override so a test or a second instance can point elsewhere.
STORE_PATH = os.environ.get("SADK_STORE_PATH",
                            os.path.join(config.REPO_DIR, "sadk_players.json"))

SCHEMA_VERSION = 2

#: Character ids start well clear of account user_ids (which count from 1) so the two are
#: instantly distinguishable in a log, and stay well below npcs.NPC_ID_BASE (1_000_000)
#: because a char_id also travels as an AVATAR id in the world, where NPC ids live.
CHAR_ID_BASE = 100_000

_lock = threading.RLock()
_state = None          # lazily loaded: {"version", "next_user_id", "next_char_id", "players"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty():
    return {"version": SCHEMA_VERSION, "next_user_id": 1,
            "next_char_id": CHAR_ID_BASE, "players": {}}


def _migrate_v1(doc):
    """v1 (one character per account, char_id == perm_id) → v2 (accounts own character lists).

    Preserves the account's id as `user_id` and re-homes its single character onto a fresh
    char_id, because in v2 the two namespaces are separate."""
    next_char = CHAR_ID_BASE
    players_out = {}
    for key, rec in (doc.get("players") or {}).items():
        char = rec.get("character")
        chars = []
        if char:
            chars.append({"char_id": next_char, "name": char.get("name"),
                          "data_hex": char.get("data_hex") or "",
                          "created": char.get("created") or _now(),
                          "modified": char.get("modified") or _now()})
            next_char += 1
        players_out[key] = {"user_id": int(rec.get("perm_id", 0)) or 1,
                            "username": rec.get("username") or key,
                            "characters": chars,
                            "created": rec.get("created") or _now(),
                            "last_login": rec.get("last_login") or _now()}
    out = {"version": SCHEMA_VERSION,
           "next_user_id": int(doc.get("next_perm_id", 1)),
           "next_char_id": next_char, "players": players_out}
    log(f"  [STORE] migrated store v1 → v2: {len(players_out)} account(s), "
        f"{next_char - CHAR_ID_BASE} character(s) re-homed onto the new char_id space")
    return out


def _load_locked():
    """Read the store from disk, or start an empty one. Caller holds `_lock`."""
    global _state
    if _state is not None:
        return _state
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "players" not in data:
            raise ValueError("not a store document")
        version = data.get("version")
        if version == 1:
            data = _migrate_v1(data)
            _state = data
            _save_locked()
        elif version != SCHEMA_VERSION:
            # Refusing beats silently reinterpreting someone's characters under a schema this
            # build does not understand (e.g. a store written by a NEWER version).
            raise ValueError(f"unsupported store version {version!r} "
                             f"(this build writes {SCHEMA_VERSION})")
        data.setdefault("next_user_id", 1)
        data.setdefault("next_char_id", CHAR_ID_BASE)
        _state = data
        total = sum(len(r.get("characters") or []) for r in data["players"].values())
        log(f"  [STORE] loaded {len(data['players'])} account(s), {total} character(s) "
            f"from {STORE_PATH}")
    except FileNotFoundError:
        _state = _empty()
        log(f"  [STORE] no store yet at {STORE_PATH} — starting empty")
    except Exception as exc:  # noqa: BLE001
        # A corrupt store must not take the lobby down, but it must be LOUD and must not be
        # silently overwritten either — the old file is kept under .bad for inspection.
        _state = _empty()
        log(f"  [STORE] ⚠ COULD NOT READ {STORE_PATH} ({exc}) — continuing with an EMPTY store. "
            f"The old file is being preserved as {STORE_PATH}.bad; players will be re-created "
            f"and will lose their characters until it is repaired.")
        try:
            os.replace(STORE_PATH, STORE_PATH + ".bad")
        except OSError:
            pass
    return _state


def _save_locked():
    """Atomically persist the in-memory state. Caller holds `_lock`."""
    if _state is None:
        return
    directory = os.path.dirname(STORE_PATH) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sadk_players.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(_state, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, STORE_PATH)          # atomic on POSIX and Windows
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:  # noqa: BLE001 — never let a disk problem kill a session
        log(f"  [STORE] ⚠ could not write {STORE_PATH}: {exc} — this session will not persist")


def _key(username):
    return (username or "").strip().lower()


# ── Identity ─────────────────────────────────────────────────────────────────
def get_or_create_account(username):
    """The persistent account record for `username`, creating it on first sight.

    Returns {"user_id", "username", "characters": [...], "created", "last_login"}. The user_id
    is allocated once and never changes."""
    with _lock:
        state = _load_locked()
        key = _key(username)
        rec = state["players"].get(key)
        if rec is None:
            user_id = int(state.get("next_user_id", 1))
            used = {int(r["user_id"]) for r in state["players"].values()}
            while user_id in used:            # never reuse, even if the counter was tampered with
                user_id += 1
            rec = {"user_id": user_id, "username": username, "characters": [],
                   "created": _now(), "last_login": _now()}
            state["players"][key] = rec
            state["next_user_id"] = user_id + 1
            _save_locked()
            log(f"  [STORE] new account {username!r} → user_id {user_id} (no characters yet)")
        else:
            rec["last_login"] = _now()
            rec["username"] = username or rec.get("username")   # keep original capitalisation
            _save_locked()
        return _account_copy(rec)


# ── Passwords ────────────────────────────────────────────────────────────────
# The first login with a new name registers it with the password typed (maintainer rule 2026-10-07);
# afterwards the password must match, and only the in-game "!setpwd" command changes it. Stored as a
# salted PBKDF2-SHA256 hash, never in clear. The client sends the password as raw bytes in the
# AuthenticateUser cipher (Authenticator::EncryptCredentials T 1002b560).
_PBKDF2_ROUNDS = 100_000


def _hash_password(password, salt):
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", password, salt, _PBKDF2_ROUNDS).hex()


def check_password(username, password):
    """True when `password` (bytes) opens the account; an account without a password yet takes it
    (that login is the registration). False on a mismatch."""
    with _lock:
        rec = _load_locked()["players"].get(_key(username))
        if rec is None or not rec.get("password_hash"):
            return True
        return _hash_password(password, bytes.fromhex(rec["password_salt"])) == rec["password_hash"]


def has_password(username):
    with _lock:
        rec = _load_locked()["players"].get(_key(username))
        return bool(rec and rec.get("password_hash"))


def set_password(username, password):
    """Set (or replace) the account's password. Returns False when there is no such account."""
    with _lock:
        state = _load_locked()
        rec = state["players"].get(_key(username))
        if rec is None:
            return False
        salt = os.urandom(16)
        rec["password_salt"] = salt.hex()
        rec["password_hash"] = _hash_password(password, salt)
        _save_locked()
        return True


# ── Buddy lists ──────────────────────────────────────────────────────────────
# One list per ACCOUNT (the client's own id in 56/98/99 is the 207 perm_id); the entries are the
# CHARACTER ids the player picked in the world (FriendIgnoreListDialog::HandleButtonClicks S 00452400
# adds the selected avatar's id).
def buddies_of(user_id):
    with _lock:
        for rec in _load_locked()["players"].values():
            if int(rec["user_id"]) == int(user_id):
                return [int(b) for b in rec.get("buddies") or []]
    return []


def set_buddies(user_id, ids):
    with _lock:
        state = _load_locked()
        for rec in state["players"].values():
            if int(rec["user_id"]) == int(user_id):
                rec["buddies"] = [int(b) for b in ids]
                _save_locked()
                return True
    return False


def owners_listing(char_id):
    """user_ids of every account whose buddy list holds `char_id`."""
    with _lock:
        return [int(r["user_id"]) for r in _load_locked()["players"].values()
                if int(char_id) in [int(b) for b in r.get("buddies") or []]]


def reserve_user_id(user_id, username=None):
    """Record an id we did not allocate (a stale token, or a client reconnecting across a
    restart) so it is never handed to somebody else."""
    with _lock:
        state = _load_locked()
        for rec in state["players"].values():
            if int(rec["user_id"]) == int(user_id):
                return _account_copy(rec)
        name = username or f"Player {user_id}"
        rec = {"user_id": int(user_id), "username": name, "characters": [],
               "created": _now(), "last_login": _now()}
        state["players"][_key(name)] = rec
        state["next_user_id"] = max(int(state.get("next_user_id", 1)), int(user_id) + 1)
        _save_locked()
        return _account_copy(rec)


def _decode(ch):
    out = dict(ch)
    out["data"] = bytes.fromhex(ch.get("data_hex") or "")
    return out


def _account_copy(rec):
    out = {k: v for k, v in rec.items() if k not in ("password_hash", "password_salt")}
    out["characters"] = [_decode(c) for c in (rec.get("characters") or [])]
    return out


def account_of(username):
    with _lock:
        rec = _load_locked()["players"].get(_key(username))
        return _account_copy(rec) if rec else None


# ── Characters ───────────────────────────────────────────────────────────────
def list_characters(username):
    """Every character on this account, in creation order. An EMPTY list is a normal, supported
    state: `CharacterDataReceived@0x00474910` has an explicit count==0 branch ("No characters
    found.", info severity) which is what drives the client's creation flow."""
    with _lock:
        rec = _load_locked()["players"].get(_key(username))
        return [_decode(c) for c in (rec.get("characters") or [])] if rec else []


def find_character(char_id):
    """(character, owning-account) for a char_id, or (None, None). The dual lookup in
    `players.resolve_by_perm` uses this to decide whether a token's perm_id names a character."""
    with _lock:
        for rec in _load_locked()["players"].values():
            for ch in rec.get("characters") or []:
                if int(ch["char_id"]) == int(char_id):
                    return _decode(ch), _account_copy(rec)
    return None, None


def find_character_by_name(name):
    """(character, owning-account) for a character name (case-insensitive), or (None, None)."""
    want = (name or "").strip().lower()
    with _lock:
        for rec in _load_locked()["players"].values():
            for ch in rec.get("characters") or []:
                if (ch.get("name") or "").strip().lower() == want:
                    return _decode(ch), _account_copy(rec)
    return None, None


def create_character(username, name, data):
    """Append a NEW character the client authored, with a freshly allocated char_id."""
    with _lock:
        get_or_create_account(username)                     # ensure the account exists
        state = _load_locked()
        rec = state["players"][_key(username)]
        char_id = int(state.get("next_char_id", CHAR_ID_BASE))
        used = {int(c["char_id"]) for r in state["players"].values()
                for c in (r.get("characters") or [])}
        while char_id in used:
            char_id += 1
        ch = {"char_id": char_id, "name": name, "data_hex": bytes(data or b"").hex(),
              "created": _now(), "modified": _now()}
        rec.setdefault("characters", []).append(ch)
        state["next_char_id"] = char_id + 1
        _save_locked()
        log(f"  [STORE] created character {name!r} on {username!r} → char_id {char_id} "
            f"({len(data or b'')}B blob); account now has {len(rec['characters'])}")
        return _decode(ch)


def update_character(char_id, name=None, data=None):
    """Update a character in place, by id. Only the fields actually supplied are touched."""
    with _lock:
        state = _load_locked()
        for rec in state["players"].values():
            for ch in rec.get("characters") or []:
                if int(ch["char_id"]) != int(char_id):
                    continue
                if name:
                    ch["name"] = name
                if data:
                    ch["data_hex"] = bytes(data).hex()
                ch["modified"] = _now()
                _save_locked()
                log(f"  [STORE] updated character {ch['name']!r} (char_id {char_id})")
                return _decode(ch)
    return None


def delete_character(char_id):
    """Delete a character BY ID. Returns the deleted record, or None if there was no such id."""
    with _lock:
        state = _load_locked()
        for rec in state["players"].values():
            chars = rec.get("characters") or []
            for i, ch in enumerate(chars):
                if int(ch["char_id"]) == int(char_id):
                    gone = chars.pop(i)
                    _save_locked()
                    log(f"  [STORE] deleted character {gone.get('name')!r} "
                        f"(char_id {char_id}) from {rec.get('username')!r}; "
                        f"{len(chars)} left on that account")
                    return _decode(gone)
    log(f"  [STORE] delete requested for unknown char_id {char_id} — nothing removed")
    return None


# ── Diagnostics / tests ──────────────────────────────────────────────────────
def all_players():
    with _lock:
        return [_account_copy(r) for r in _load_locked()["players"].values()]


def reset_for_tests(path=None):
    """Point the store at a fresh file and drop the cache. Tests only."""
    global _state, STORE_PATH
    with _lock:
        if path is not None:
            STORE_PATH = path
        _state = None
