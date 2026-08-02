"""
Persistent player state — identity + character, on disk.

Until now every identity was ephemeral: perm_ids were handed out sequentially per process
and every player wore the same hardcoded appearance blob (`config.NICKNAME_DATA`, lifted
from the AdK emulator — its zlib payload literally contains the name "tester"). A restart
meant a new you.

This module is the store behind `players.py` and the character handlers in `dispatch.py`.

## What is persisted, and why exactly this

* **`perm_id` per username.** ⭐ NOT an implementation detail: the client's own avatar id IS
  its PermID, and `CharacterManager::CharacterObserverListener::CharacterDataReceived
  @0x00474910` keys characters by `char_id`. The own-avatar lookup then searches the
  CharacterManager by avatar id — the failure path logs *"WTF?! There is no avatar with that
  id in the CharacterManager"* and fails the village login. So **`char_id` must equal the
  perm_id we issue**, and a persisted character is therefore only coherent if the perm_id is
  persisted with it. A returning player who got a fresh perm_id would orphan their own
  character.
* **The character's `data` blob, verbatim.** The CLIENT authors this at creation
  (`CreateCharacterFromPreview`, msg 77) — it is a zlib-wrapped record carrying the name in
  UTF-16LE plus appearance/stat fields, and `CommLayer::Character::GetData(i)` shows the
  client splits it into **six** sub-blocks. We deliberately do NOT parse or synthesise it:
  the server's job here is to be a store, and replaying the client's own bytes is both the
  correct protocol behaviour and the only way to be certain we are not corrupting a format
  we have not fully reversed. [TODO] the six-slot inner layout is unreversed.

## Format

A single JSON file (default `sadk_players.json` beside the log, override with
`SADK_STORE_PATH`). Written atomically — temp file + `os.replace` — so a crash or a
concurrent read never sees a half-written file. Blobs are stored hex-encoded because JSON
has no byte type.

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

SCHEMA_VERSION = 1

_lock = threading.RLock()
_state = None          # lazily loaded: {"version", "next_perm_id", "players": {...}}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty():
    return {"version": SCHEMA_VERSION, "next_perm_id": 1, "players": {}}


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
        if version != SCHEMA_VERSION:
            # No migration exists yet; refusing beats silently reinterpreting someone's
            # characters under the wrong schema.
            raise ValueError(f"unsupported store version {version!r} "
                             f"(this build writes {SCHEMA_VERSION})")
        data.setdefault("next_perm_id", 1)
        _state = data
        log(f"  [STORE] loaded {len(data['players'])} player(s) from {STORE_PATH}")
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
def get_or_create_player(username):
    """The persistent record for `username`, creating (and saving) it on first sight.

    Returns a dict: {"perm_id", "username", "character": {...} | None, "created", "last_login"}.
    The perm_id is allocated once and never changes — see the module docstring for why that is
    a protocol requirement and not a convenience."""
    with _lock:
        state = _load_locked()
        key = _key(username)
        rec = state["players"].get(key)
        if rec is None:
            perm_id = int(state.get("next_perm_id", 1))
            # Never hand out an id already in use, even if the counter was tampered with.
            used = {int(r["perm_id"]) for r in state["players"].values()}
            while perm_id in used:
                perm_id += 1
            rec = {"perm_id": perm_id, "username": username,
                   "character": None, "created": _now(), "last_login": _now()}
            state["players"][key] = rec
            state["next_perm_id"] = perm_id + 1
            _save_locked()
            log(f"  [STORE] new player {username!r} → perm_id {perm_id} (no character yet)")
        else:
            rec["last_login"] = _now()
            rec["username"] = username or rec.get("username")   # keep original capitalisation
            _save_locked()
        return dict(rec)


def reserve_perm_id(perm_id, username=None):
    """Record a perm_id we did not allocate (a stale token, or a client reconnecting across a
    restart) so it is never handed to somebody else. Returns the stored record."""
    with _lock:
        state = _load_locked()
        for rec in state["players"].values():
            if int(rec["perm_id"]) == int(perm_id):
                return dict(rec)
        name = username or f"Player {perm_id}"
        rec = {"perm_id": int(perm_id), "username": name,
               "character": None, "created": _now(), "last_login": _now()}
        state["players"][_key(name)] = rec
        state["next_perm_id"] = max(int(state.get("next_perm_id", 1)), int(perm_id) + 1)
        _save_locked()
        return dict(rec)


# ── Characters ───────────────────────────────────────────────────────────────
def get_character(username):
    """The stored character for `username`, or None if they have not created one.

    None is a normal, supported state: the client's `CharacterDataReceived@0x00474910` has an
    explicit count==0 branch ("No characters found.", info severity) which drives the
    character-creation flow."""
    with _lock:
        rec = _load_locked()["players"].get(_key(username))
        if not rec or not rec.get("character"):
            return None
        ch = dict(rec["character"])
        ch["data"] = bytes.fromhex(ch.get("data_hex") or "")
        ch["char_id"] = int(rec["perm_id"])       # char_id IS the perm_id — see module docstring
        return ch


def save_character(username, name, data):
    """Store the character the CLIENT authored. `data` is its blob, kept verbatim."""
    with _lock:
        state = _load_locked()
        rec = state["players"].get(_key(username))
        if rec is None:
            rec = get_or_create_player(username)
            state = _load_locked()
            rec = state["players"][_key(username)]
        existing = rec.get("character") or {}
        rec["character"] = {
            "name": name,
            "data_hex": bytes(data or b"").hex(),
            "created": existing.get("created") or _now(),
            "modified": _now(),
        }
        _save_locked()
        log(f"  [STORE] saved character {name!r} for {username!r} "
            f"(char_id {rec['perm_id']}, {len(data or b'')}B blob)")
        return dict(rec["character"])


def delete_character(username):
    with _lock:
        state = _load_locked()
        rec = state["players"].get(_key(username))
        if not rec or not rec.get("character"):
            return False
        gone = rec["character"].get("name")
        rec["character"] = None
        _save_locked()
        log(f"  [STORE] deleted character {gone!r} for {username!r}")
        return True


# ── Diagnostics / tests ──────────────────────────────────────────────────────
def all_players():
    with _lock:
        return [dict(r) for r in _load_locked()["players"].values()]


def reset_for_tests(path=None):
    """Point the store at a fresh file and drop the cache. Tests only."""
    global _state, STORE_PATH
    with _lock:
        if path is not None:
            STORE_PATH = path
        _state = None
