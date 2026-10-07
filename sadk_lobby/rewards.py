"""
Match rewards: experience, gold and chests for networked matches (maintainer rules 2026-10-07).

What the client gives us [known]:
  * The match protocol carries no reward data: FinishGame (0xDC0) names one winning avatar, GiveUpGame
    (0xDD4) and ClaimChest (0xDAC) carry no amounts, and the referee answers only result codes. There
    is no knock-out message, so per-kill bonuses cannot be computed. Rewards were server-side: the
    client shows what the character holds (XP bar, level, gold) from its save and 3200/3201.
  * XP thresholds (SelectionInfoDialog::UpdateXpProgress S 0044f800, table at 007d8d90): level 1 = 0,
    2 = 1000, 3 = 2500, 4 = 5000, 5 = 10000, and the level-5 bar ends at 25000; the table has no
    level 6+, and the outfit model also stops at level 5 (CGfxObjAvatar::UpdateAppearance S 00508090).
  * Referee chests (content kind 0) are claimed by every client that sees one open
    (Referee_OnChestOpened_SendClaimChest S 00782a60); the client grants nothing itself.

Server rules (maintainer decisions 2026-10-07):
  * XP = (BASE_XP + XP_PER_MINUTE per full minute played) x multiplier, each player timed from its own
    RegisterGame to its own FinishGame / GiveUpGame; a match shorter than MIN_MINUTES gives nothing.
    Gold = XP / 10.
  * multiplier = 1 + WIN_BONUS if its FinishGame names it the winner + CHEST_BONUS per chest it got
    in that match.
  * A chest (a referee chest's first claimant) also puts a random item into the backpack.
  * Level rises with the thresholds above, capped at MAX_LEVEL / MAX_EXP.
"""
import random
import threading
import time

from . import economy
from .log import log

BASE_XP = 500
XP_PER_MINUTE = 100
GOLD_DIVISOR = 10
MIN_MINUTES = 2                               # shorter matches give 0 XP / 0 gold
WIN_BONUS = 1.0                               # +100 %
CHEST_BONUS = 0.25                            # +25 % per chest
LEVEL_XP = (0, 1000, 2500, 5000, 10000)       # start of levels 1..5 (client table 007d8d90)
MAX_LEVEL = 5
MAX_EXP = 25000                               # end of the level-5 bar

_lock = threading.Lock()
_started = {}                                 # (game_id, avatar_id) -> monotonic start
_chests = {}                                  # (game_id, avatar_id) -> chests got in that match


def reset_for_tests():
    with _lock:
        _started.clear()
        _chests.clear()


def level_for(exp):
    return max(i + 1 for i, need in enumerate(LEVEL_XP) if exp >= need)


def match_started(game_id, avatar_id, now=None):
    with _lock:
        _started[(game_id, avatar_id)] = time.monotonic() if now is None else now


def match_xp(minutes, won, chests=0):
    if minutes < MIN_MINUTES:
        return 0
    multiplier = 1 + (WIN_BONUS if won else 0) + CHEST_BONUS * chests
    return int((BASE_XP + XP_PER_MINUTE * int(minutes)) * multiplier)


def _random_item():
    item_id = random.choice([i for i, _n, _m, _p in economy.ITEMS])
    return (item_id, 1, economy.ITEM_SLTT[item_id])


def grant_chest(avatar_id, reason, game_id=None):
    """A chest: a random item into the first free backpack slot of the character's save, and +25 % on
    that match's XP and gold (counted when the match ends)."""
    if game_id is not None:
        with _lock:
            _chests[(game_id, avatar_id)] = _chests.get((game_id, avatar_id), 0) + 1
    w = economy.load(avatar_id)
    free = next((i for i, r in enumerate(w.backpack) if r is None), None)
    if free is None:
        log(f"  [REWARD] chest for {avatar_id} ({reason}): backpack full — nothing added")
        return None
    item = _random_item()
    w.backpack[free] = item
    economy.persist(avatar_id)
    log(f"  [REWARD] chest for {avatar_id} ({reason}): item {item[0]} into backpack slot {free}")
    return item


def match_finished(game_id, avatar_id, won, now=None):
    """Credit one player once for one match (its own FinishGame or GiveUpGame). Returns (xp, gold)
    or None when there is no running match for it (a repeat, or no RegisterGame seen)."""
    with _lock:
        start = _started.pop((game_id, avatar_id), None)
    if start is None:
        return None
    with _lock:
        chests = _chests.pop((game_id, avatar_id), 0)
    minutes = ((time.monotonic() if now is None else now) - start) / 60.0
    xp = match_xp(minutes, won, chests)
    gold = xp // GOLD_DIVISOR
    w = economy.load(avatar_id)
    w.exp = min(w.exp + xp, MAX_EXP)
    w.level = min(max(w.level, level_for(w.exp)), MAX_LEVEL)
    w.gold += gold
    economy.persist(avatar_id)
    log(f"  [REWARD] match {game_id}: {avatar_id} {'WON' if won else 'played'} {int(minutes)} min, "
        f"{chests} chest(s) → +{xp} XP (now {w.exp}, level {w.level}), +{gold} gold (now {w.gold})")
    return xp, gold
