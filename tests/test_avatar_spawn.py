"""
Avatar spawn (offline): an EntityCreate (1001) for another player carries location, style, equipped
items and level, read back in the client's block order (AvatarProxy::ReadDataBlocks S 00482c20:
Location 1, Style 2, ActiveItems 4 — same reader as 3100, S 0048abe0 — Stats 8). Without items and
level a returning player showed up in the default outfit.

Run:  python tests/test_avatar_spawn.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import village  # noqa: E402
from sadk_lobby.village import BitReader  # noqa: E402


def test_spawn_carries_items_and_level():
    style = {"name": "J4n1X", "tribe_gender": 0x10, "colours": (9, 1, 5, 8, 1, 9, 14, 2),
             "active": [(2, 1, 2), None, (30, 1, 4), None], "level": 5}
    r = BitReader(village.entity_create_body(100000, pos=(-31.9, 2.8, 27.5), tick=7, style=style))
    assert r.read(32) == 100000
    assert r.read(4) == 0b1111                                   # location + style + items + stats
    r.read(16), r.read(11), r.read(11), r.read(11), r.read(7), r.read(4), r.read(4), r.read(1), r.read(1)
    name = bytes(r.read(8) for _ in range(r.read(8))).decode()
    assert name == "J4n1X"
    assert [r.read(8) for _ in range(9)] == [0x10, 9, 1, 5, 8, 1, 9, 14, 2]
    slots = [(r.read(8), r.read(8), r.read(32)) for _ in range(4)]
    assert slots == [(2, 1, 2), (0, 0, 0), (4, 1, 30), (0, 0, 0)]   # sltt, cnt, itmid
    assert [r.read(32) for _ in range(4)] == [5, 0, 0, 0]        # lvl, exp, gold, glod
    # Without items/level the old shape stays (NPC walkers, ring refreshes).
    r = BitReader(village.entity_create_body(1, pos=(1.0, 2.7, 1.0), style={"name": "x"}))
    r.read(32)
    assert r.read(4) == 0b0011
    print("spawn 1001 carries style, equipment and level in the client's order OK")


if __name__ == "__main__":
    test_spawn_carries_items_and_level()
    print("\nAll avatar spawn tests PASSED")
