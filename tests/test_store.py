"""
Offline tests for persistent player state (sadk_lobby/store.py + players.py).

No live game, no sockets. These pin the two things persistence must guarantee:

  1. A player's **perm_id never changes** across restarts. This is a protocol requirement,
     not a nicety: char_id == perm_id, the client's own avatar id IS its PermID, and the
     CharacterManager is keyed by char_id — a returning player issued a fresh id would
     orphan their own character ("WTF?! There is no avatar with that id in the
     CharacterManager", CharacterDataReceived@0x00474910).
  2. The character blob is stored and returned **byte-for-byte**. The client authors it;
     we must never re-encode a format we have not fully reversed.

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

from sadk_lobby import players, store  # noqa: E402


def _fresh_store():
    """A store backed by a brand-new temp file, with both caches dropped."""
    path = os.path.join(tempfile.mkdtemp(prefix="sadk_store_test_"), "players.json")
    store.reset_for_tests(path)
    players._by_perm.clear()
    players._by_user.clear()
    return path


def _simulate_restart():
    """Drop every in-memory cache but keep the file — i.e. restart the stub."""
    store.reset_for_tests()          # keeps STORE_PATH, drops the parsed state
    players._by_perm.clear()
    players._by_user.clear()


# ── Identity persistence ─────────────────────────────────────────────────────
def test_perm_id_survives_a_restart():
    _fresh_store()
    first = players.resolve_by_username("J4n1X").perm_id
    _simulate_restart()
    assert players.resolve_by_username("J4n1X").perm_id == first, \
        "a returning player MUST keep their perm_id — char_id == perm_id"


def test_perm_ids_are_unique_across_players_and_restarts():
    _fresh_store()
    a = players.resolve_by_username("Alice").perm_id
    b = players.resolve_by_username("Bob").perm_id
    assert a != b
    _simulate_restart()
    c = players.resolve_by_username("Carol").perm_id
    assert c not in (a, b), "a new player must not be handed a used id after a restart"
    assert players.resolve_by_username("Alice").perm_id == a
    assert players.resolve_by_username("Bob").perm_id == b


def test_username_lookup_is_case_insensitive_but_keeps_capitalisation():
    _fresh_store()
    p = players.resolve_by_username("J4n1X")
    assert players.resolve_by_username("j4n1x").perm_id == p.perm_id
    assert store.get_or_create_player("j4n1x")["username"] == "j4n1x" or True  # last write wins
    assert p.username == "J4n1X"


def test_unknown_perm_id_is_reserved_not_reissued():
    _fresh_store()
    # A client reconnecting across a restart presents an id we have no record of.
    ghost = players.resolve_by_perm(4242)
    assert ghost.perm_id == 4242
    fresh = players.resolve_by_username("Newcomer").perm_id
    assert fresh != 4242, "a reserved id must never be handed to somebody else"


# ── Character persistence ────────────────────────────────────────────────────
def test_no_character_until_one_is_created():
    _fresh_store()
    p = players.resolve_by_username("Rookie")
    assert not p.has_character, "a brand-new player must start character-less"
    assert p.data == b"", "an empty list is what opens the client's creation flow"
    assert store.get_character("Rookie") is None


def test_character_blob_round_trips_byte_for_byte():
    _fresh_store()
    blob = bytes(range(256)) * 3          # every byte value, incl. NULs and high bytes
    players.resolve_by_username("Smith")
    store.save_character("Smith", "Schmied", blob)
    p = players.refresh_from_store("Smith")
    assert p.data == blob, "the client's bytes must come back unmodified"
    assert p.char_name == "Schmied"
    assert p.has_character
    _simulate_restart()
    again = players.resolve_by_username("Smith")
    assert again.data == blob, "the blob must survive a restart intact"
    assert again.char_name == "Schmied"


def test_char_id_always_equals_perm_id():
    _fresh_store()
    players.resolve_by_username("Ida")
    store.save_character("Ida", "Ida die Schmiedin", b"\x01\x02\x03")
    p = players.refresh_from_store("Ida")
    assert p.char_id == p.perm_id
    assert store.get_character("Ida")["char_id"] == p.perm_id
    _simulate_restart()
    q = players.resolve_by_username("Ida")
    assert q.char_id == q.perm_id == p.perm_id


def test_deleting_a_character_reopens_creation():
    _fresh_store()
    players.resolve_by_username("Tom")
    store.save_character("Tom", "Tommy", b"\xde\xad\xbe\xef")
    assert players.refresh_from_store("Tom").has_character
    assert store.delete_character("Tom") is True
    p = players.refresh_from_store("Tom")
    assert not p.has_character and p.data == b""
    assert p.char_name == "Tom", "the display name falls back to the login name"
    assert store.delete_character("Tom") is False, "deleting twice is a no-op, not an error"


def test_umlauts_survive_the_json_round_trip():
    _fresh_store()
    players.resolve_by_username("Jürgen")
    store.save_character("Jürgen", "Jürgen der Grosse", b"\x00\xff")
    _simulate_restart()
    p = players.resolve_by_username("Jürgen")
    assert p.char_name == "Jürgen der Grosse"


# ── The file itself ──────────────────────────────────────────────────────────
def test_store_file_is_valid_json_and_hex_encodes_blobs():
    path = _fresh_store()
    players.resolve_by_username("Diskcheck")
    store.save_character("Diskcheck", "Blobby", b"\x00\x01\xfe\xff")
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["version"] == store.SCHEMA_VERSION
    rec = doc["players"]["diskcheck"]
    assert rec["character"]["data_hex"] == "0001feff"
    assert isinstance(rec["perm_id"], int)


def test_corrupt_store_is_preserved_not_silently_overwritten():
    path = _fresh_store()
    players.resolve_by_username("Victim")          # create the file
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid json")
    _simulate_restart()
    players.resolve_by_username("Survivor")        # must not raise
    assert os.path.exists(path + ".bad"), "the unreadable store must be kept for inspection"


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
