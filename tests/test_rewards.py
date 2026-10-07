"""
Match rewards (offline, maintainer rules 2026-10-07): XP = (500 + 100 per full minute) x (1 + 1.0 for
the winner + 0.25 per chest), gold = XP / 10, credited once per player per match into the character
save; levels follow the client's XP thresholds (S 0044f800, table 007d8d90), capped at level 5; a
chest's first claimant also gets a random item.

Run:  python tests/test_rewards.py
"""
import os
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.environ["SADK_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "players.json")

from sadk_lobby import economy, rewards, savegame, store  # noqa: E402


def _char(name):
    store.get_or_create_account(name)
    blob = savegame.build(savegame.Save(gold=100, glod=100))      # a full save: no starter purse
    return int(store.create_character(name, name, blob)["char_id"])


def test_formula_and_levels():
    assert rewards.match_xp(0, False) == 0 and rewards.match_xp(1.99, True, chests=3) == 0   # < 2 min
    assert rewards.match_xp(2, False) == 700 and rewards.match_xp(20.9, False) == 2500
    assert rewards.match_xp(20, True) == 5000                     # winner: +100 %
    assert rewards.match_xp(10, False, chests=2) == 2250          # 1500 x 1.5
    assert rewards.match_xp(10, True, chests=1) == 3375           # 1500 x 2.25
    assert [rewards.level_for(x) for x in (0, 999, 1000, 2500, 9999, 10000, 25000)] == [1, 1, 2, 3, 4, 5, 5]
    print("XP formula, multiplier and level thresholds OK")


def test_match_credit_and_chests():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    economy.reset_for_tests()
    rewards.reset_for_tests()
    win, lose = _char("Sieger"), _char("Verlierer")
    rewards.match_started(100, win, now=0.0)
    rewards.match_started(100, lose, now=0.0)
    rewards.grant_chest(win, "chest 7", 100)                      # found during the match
    assert sum(1 for r in economy.load(win).backpack if r) == 1   # an item in the backpack
    assert rewards.match_finished(100, lose, won=False, now=12 * 60.0) == (1700, 170)
    assert rewards.match_finished(100, lose, won=False, now=13 * 60.0) is None   # resent GiveUp
    assert rewards.match_finished(100, win, won=True, now=12 * 60.0) == (3825, 382)  # 1700 x 2.25
    economy.reset_for_tests()                                     # a server restart: from the save
    w = economy.load(win)
    assert (w.exp, w.level, w.gold) == (3825, 3, 100 + 382)
    assert economy.load(lose).level == 2
    # A rematch with the same GameID starts a fresh clock.
    rewards.match_started(100, win, now=0.0)
    assert rewards.match_finished(100, win, won=False, now=0.0) == (0, 0)        # under 2 minutes
    print("credited once per match into the save, chest item + bonus, rematch OK")


def test_caps():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    economy.reset_for_tests()
    rewards.reset_for_tests()
    c = _char("Veteran")
    rewards.match_started(1, c, now=0.0)
    rewards.match_finished(1, c, won=True, now=600 * 60.0)        # 10 hours
    w = economy.load(c)
    assert w.exp == rewards.MAX_EXP and w.level == rewards.MAX_LEVEL
    print("capped at level 5 / 25000 XP OK")


if __name__ == "__main__":
    test_formula_and_levels()
    test_match_credit_and_chests()
    test_caps()
    print("\nAll reward tests PASSED")
