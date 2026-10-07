"""
Character save (offline): the six-part blob read back exactly as ApplyCharacterDataBlocks
(S 00481e60) and the block deserializers read it, and the server's own saves round-trip.

Run:  python tests/test_savegame.py
"""
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import savegame as sg  # noqa: E402


def test_round_trip():
    s = sg.Save(body=1, gender=1, colours=[1, 2, 3, 4, 5, 6, 7, 8],
                active=[(17, 1, 2), None, (30, 1, 4), None],
                inventory=[(5, 3, 0), None, (7, 1, 1)] + [None] * 17,
                level=3, exp=42, gold=1234, glod=99, pos=(10.5, 2.5, -7.25), heading=0x40490fdb,
                zone=3, ghost_zone=15)
    blob = sg.build(s)
    sizes = struct.unpack_from("<6I", blob, 0)
    assert sizes == (0xC, 0x24, 0x34, 8 + 20 * 12, 38, 0), sizes   # the client's block sizes
    assert len(blob) == 0x18 + sum(sizes)
    r = sg.parse(blob)
    assert not r.fresh
    for f in ("body", "gender", "colours", "active", "inventory", "level", "exp", "gold", "glod",
              "heading", "zone", "ghost_zone"):
        assert getattr(r, f) == getattr(s, f), f
    assert all(abs(a - b) < 1e-5 for a, b in zip(r.pos, s.pos))
    assert r.trbgndr == 0x11
    # Empty equipment slots keep the client's default slot types 2..5.
    active = sg.split(blob)[2]
    assert struct.unpack_from("<3I", active, 4 + 12)[0] == 3
    print("full save round-trips with the client's block sizes OK")


def test_creation_form():
    """What the client sends when creating a character: part 0 = Creation block, parts 1-5 empty."""
    creation = struct.pack("<11I", 1, 2, 1, 3, 4, 5, 6, 7, 8, 9, 10)
    s = sg.parse(sg.join([creation, b"", b"", b"", b"", b""]))
    assert s.fresh and s.body == 2 and s.gender == 1
    assert s.colours == [3, 4, 5, 6, 7, 8, 9, 10] and s.gold == s.glod == 50 and s.level == 1
    s0 = sg.parse(sg.join([struct.pack("<7I", 0, 0, 0, 1, 2, 3, 4), b"", b"", b"", b"", b""]))
    assert s0.colours == [1, 2, 3, 4, 0, 0, 0, 0]               # variant 0: no addColors
    print("creation form read like the client OK")


def test_defaults_and_short_blobs():
    assert sg.parse(b"").gold == 1000 and sg.parse(b"\x00" * 3).level == 1
    # Stats variant 0: glod stays 1000, the position stays at the default spawn.
    stats = struct.pack("<4I", 0, 2, 5, 77)
    s = sg.parse(sg.join([struct.pack("<3I", 0, 0, 0), b"", b"", b"", stats, b""]))
    assert (s.level, s.exp, s.gold, s.glod, s.pos) == (2, 5, 77, 1000, sg.DEFAULT_POS)
    # The legacy emulator blob (part 1 = 'a2000000' + zlib bytes) parses without raising.
    from sadk_lobby import config
    sg.parse(config.NICKNAME_DATA)
    print("defaults and short / odd blobs OK")


if __name__ == "__main__":
    test_round_trip()
    test_creation_form()
    test_defaults_and_short_blobs()
    print("\nAll savegame tests PASSED")
