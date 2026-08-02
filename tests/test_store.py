"""
Offline tests for persistent player state (sadk_lobby/store.py + players.py).

No live game, no sockets. These pin what persistence must guarantee:

  1. An account's **user_id never changes** across restarts — a returning player issued a
     fresh id would no longer own their own characters.
  2. An account owns **many characters**, each with its own globally unique `char_id`.
     `msgdefs.ini` gives CharacterData both `char_id` and `owner_id`; conflating them (as
     the stub used to) only works while an account holds exactly one character.
  3. `char_id` is what the client NAMES when changing or deleting — delete must remove
     exactly that character, never "whatever this account has".
  4. The character blob round-trips **byte-for-byte**. The client authors it; we must never
     re-encode a format we have not fully reversed.

Run directly:   python tests/test_store.py
Or with pytest: pytest tests/test_store.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import config, npcs, players, store  # noqa: E402

# The store is gated behind config.PERSISTENT_CHARACTERS_ENABLED, currently OFF after the
# "login attempt failed" regression (2026-08-02). These tests exercise the store itself, so
# they turn it ON explicitly — otherwise they would pass while testing the legacy path and
# quietly stop covering the thing they are named after.
config.PERSISTENT_CHARACTERS_ENABLED = True


def _fresh_store():
    """A store backed by a brand-new temp file, with every cache dropped."""
    path = os.path.join(tempfile.mkdtemp(prefix="sadk_store_test_"), "players.json")
    store.reset_for_tests(path)
    players._by_perm.clear()
    players._by_user.clear()
    players._next_perm = 1
    return path


def _simulate_restart():
    """Drop every in-memory cache but keep the file — i.e. restart the stub."""
    store.reset_for_tests()          # keeps STORE_PATH, drops the parsed state
    players._by_perm.clear()
    players._by_user.clear()


# ── Identity persistence ─────────────────────────────────────────────────────
def test_user_id_survives_a_restart():
    _fresh_store()
    first = players.resolve_by_username("J4n1X").user_id
    _simulate_restart()
    assert players.resolve_by_username("J4n1X").user_id == first


def test_user_ids_are_unique_across_players_and_restarts():
    _fresh_store()
    a = players.resolve_by_username("Alice").user_id
    b = players.resolve_by_username("Bob").user_id
    assert a != b
    _simulate_restart()
    c = players.resolve_by_username("Carol").user_id
    assert c not in (a, b), "a new account must not be handed a used id after a restart"
    assert players.resolve_by_username("Alice").user_id == a
    assert players.resolve_by_username("Bob").user_id == b


def test_username_lookup_is_case_insensitive():
    _fresh_store()
    p = players.resolve_by_username("J4n1X")
    assert players.resolve_by_username("j4n1x").user_id == p.user_id
    assert p.username == "J4n1X"


def test_unknown_perm_id_is_reserved_not_reissued():
    _fresh_store()
    ghost = players.resolve_by_perm(4242)      # a stale token from before a restart
    assert ghost.perm_id == 4242
    assert players.resolve_by_username("Newcomer").user_id != 4242


# ── Character persistence ────────────────────────────────────────────────────
def test_no_characters_until_one_is_created():
    _fresh_store()
    p = players.resolve_by_username("Rookie")
    assert not p.has_character, "a brand-new account must start character-less"
    assert store.list_characters("Rookie") == [], \
        "an empty list is what opens the client's creation flow"


def test_character_blob_round_trips_byte_for_byte():
    _fresh_store()
    blob = bytes(range(256)) * 3          # every byte value, incl. NULs and high bytes
    players.resolve_by_username("Smith")
    ch = store.create_character("Smith", "Schmied", blob)
    assert ch["data"] == blob, "the client's bytes must come back unmodified"
    _simulate_restart()
    again = store.list_characters("Smith")
    assert len(again) == 1 and again[0]["data"] == blob, "the blob must survive a restart"
    assert again[0]["name"] == "Schmied"


def test_multiple_characters_per_account_get_distinct_ids():
    _fresh_store()
    players.resolve_by_username("Multi")
    ids = [store.create_character("Multi", n, bytes([i]))["char_id"]
           for i, n in enumerate(("Erster", "Zweiter", "Dritter"))]
    assert len(set(ids)) == 3, f"character ids must be unique: {ids}"
    assert all(i >= store.CHAR_ID_BASE for i in ids), "char_ids live in their own id space"
    assert [c["name"] for c in store.list_characters("Multi")] == \
        ["Erster", "Zweiter", "Dritter"], "creation order is preserved"
    _simulate_restart()
    assert [c["char_id"] for c in store.list_characters("Multi")] == ids


def test_char_ids_are_globally_unique_and_below_npc_ids():
    _fresh_store()
    for who in ("Ann", "Ben", "Cai"):
        players.resolve_by_username(who)
        store.create_character(who, f"{who}s Held", b"\x00")
    every = [c["char_id"] for w in ("Ann", "Ben", "Cai") for c in store.list_characters(w)]
    assert len(set(every)) == len(every), "char_ids must be globally unique, not per-account"
    # A char_id also travels as an AVATAR id in the world, where NPC ids start at 1_000_000.
    assert all(i < npcs.NPC_ID_BASE for i in every), "char_ids must not collide with NPC ids"


def test_char_id_and_user_id_are_separate_namespaces():
    _fresh_store()
    p = players.resolve_by_username("Split")
    ch = store.create_character("Split", "Der Held", b"\x07")
    assert ch["char_id"] != p.user_id, "conflating the two is the bug this model fixes"
    assert store.account_of("Split")["user_id"] == p.user_id


def test_find_character_resolves_its_owner():
    _fresh_store()
    players.resolve_by_username("Owner")
    ch = store.create_character("Owner", "Besitz", b"\x09")
    found, acct = store.find_character(ch["char_id"])
    assert found["name"] == "Besitz" and acct["username"] == "Owner"
    assert store.find_character(999999) == (None, None)


def test_token_perm_id_naming_a_character_binds_that_character():
    _fresh_store()
    players.resolve_by_username("Bound")
    a = store.create_character("Bound", "Held A", b"\xaa")
    b = store.create_character("Bound", "Held B", b"\xbb")
    players._by_perm.clear()
    players._by_user.clear()
    p = players.resolve_by_perm(b["char_id"])          # the client selected the SECOND one
    assert p.char_id == b["char_id"] and p.char_name == "Held B" and p.data == b"\xbb"
    assert p.perm_id == b["char_id"]
    assert p.user_id == store.account_of("Bound")["user_id"], "owner must still resolve"
    assert a["char_id"] != b["char_id"]


def test_lone_character_is_auto_bound_when_the_token_names_the_account():
    # Until it is observed live, the token's perm_id may name either kind (store.py docstring).
    _fresh_store()
    p = players.resolve_by_username("Solo")
    ch = store.create_character("Solo", "Einzelkind", b"\x42")
    players._by_perm.clear()
    players._by_user.clear()
    q = players.resolve_by_perm(p.user_id)             # account id, not char id
    assert q.char_id == ch["char_id"] and q.data == b"\x42"


def test_deleting_by_id_removes_only_that_character():
    _fresh_store()
    players.resolve_by_username("Cull")
    a = store.create_character("Cull", "Bleibt", b"\x01")
    b = store.create_character("Cull", "Geht", b"\x02")
    gone = store.delete_character(b["char_id"])
    assert gone is not None and gone["name"] == "Geht"
    assert [c["char_id"] for c in store.list_characters("Cull")] == [a["char_id"]], \
        "only the named character may disappear"
    assert store.delete_character(b["char_id"]) is None, "deleting twice is a no-op, not a crash"
    _simulate_restart()
    assert [c["name"] for c in store.list_characters("Cull")] == ["Bleibt"]


def test_deleting_the_bound_character_unbinds_the_live_player():
    _fresh_store()
    players.resolve_by_username("Unbind")
    ch = store.create_character("Unbind", "Kurzlebig", b"\x05")
    players._by_perm.clear()
    players._by_user.clear()
    p = players.resolve_by_perm(ch["char_id"])
    assert p.has_character
    store.delete_character(ch["char_id"])
    p = players.refresh_from_store("Unbind")
    assert not p.has_character and p.data == b""
    assert p.char_name == "Unbind", "the display name falls back to the login name"


def test_updating_touches_only_the_supplied_fields():
    _fresh_store()
    players.resolve_by_username("Edit")
    ch = store.create_character("Edit", "Alt", b"\x11\x22")
    store.update_character(ch["char_id"], name="Neu")
    got = store.list_characters("Edit")[0]
    assert got["name"] == "Neu" and got["data"] == b"\x11\x22", "data must be left alone"
    store.update_character(ch["char_id"], data=b"\x33")
    got = store.list_characters("Edit")[0]
    assert got["name"] == "Neu" and got["data"] == b"\x33"
    assert store.update_character(999999, name="ghost") is None


def test_umlauts_survive_the_json_round_trip():
    _fresh_store()
    players.resolve_by_username("Jürgen")
    store.create_character("Jürgen", "Jürgen der Grosse", b"\x00\xff")
    _simulate_restart()
    assert store.list_characters("Jürgen")[0]["name"] == "Jürgen der Grosse"


# ── The file itself ──────────────────────────────────────────────────────────
def test_store_file_is_valid_json_and_hex_encodes_blobs():
    path = _fresh_store()
    players.resolve_by_username("Diskcheck")
    store.create_character("Diskcheck", "Blobby", b"\x00\x01\xfe\xff")
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["version"] == store.SCHEMA_VERSION
    rec = doc["players"]["diskcheck"]
    assert rec["characters"][0]["data_hex"] == "0001feff"
    assert isinstance(rec["user_id"], int)


def test_v1_store_is_migrated_forward():
    path = _fresh_store()
    v1 = {"version": 1, "next_perm_id": 5, "players": {"olduser": {
        "perm_id": 3, "username": "OldUser",
        "character": {"name": "Altgedienter", "data_hex": "abcdef",
                      "created": "2026-01-01T00:00:00+00:00"},
        "created": "2026-01-01T00:00:00+00:00", "last_login": "2026-01-01T00:00:00+00:00"}}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v1, fh)
    _simulate_restart()
    assert store.account_of("OldUser")["user_id"] == 3, "the account keeps its id"
    chars = store.list_characters("OldUser")
    assert len(chars) == 1 and chars[0]["name"] == "Altgedienter"
    assert chars[0]["data"] == bytes.fromhex("abcdef"), "the blob must survive migration"
    assert chars[0]["char_id"] >= store.CHAR_ID_BASE, "re-homed onto the new id space"


def test_corrupt_store_is_preserved_not_silently_overwritten():
    path = _fresh_store()
    players.resolve_by_username("Victim")          # create the file
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid json")
    _simulate_restart()
    players.resolve_by_username("Survivor")        # must not raise
    assert os.path.exists(path + ".bad"), "the unreadable store must be kept for inspection"


# ── The rollback path ────────────────────────────────────────────────────────
def test_legacy_path_restores_the_pre_persistence_shape():
    """With persistence OFF the identity must look EXACTLY as it did before the store landed:
    sequential in-memory perm_id, char_id == perm_id == user_id, shared NICKNAME_DATA blob.
    This is the behaviour the "login attempt failed" rollback restores, so it is pinned."""
    _fresh_store()
    config.PERSISTENT_CHARACTERS_ENABLED = False
    try:
        a = players.resolve_by_username("LegacyOne")
        b = players.resolve_by_username("LegacyTwo")
        assert a.perm_id == 1 and b.perm_id == 2, "sequential ids from 1"
        for p in (a, b):
            assert p.char_id == p.perm_id == p.user_id, "the three ids collapse into one"
            assert p.data == config.NICKNAME_DATA, "the shared appearance blob comes back"
            assert p.has_character, "a legacy player always has its implicit character"
        ghost = players.resolve_by_perm(777)
        assert ghost.perm_id == ghost.char_id == 777
        assert ghost.data == config.NICKNAME_DATA
        # Nothing may reach the store while the flag is off.
        assert store.list_characters("LegacyOne") == []
    finally:
        config.PERSISTENT_CHARACTERS_ENABLED = True


def _run():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {e}")
    print()
    if failures:
        print(f"{failures} test(s) FAILED")
        return 1
    print("All store tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
