"""
Poker rules for village minigame tables, in the encodings the client expects (docs/message-catalog.md,
village: Minigames, Poker). Pure functions; the table flow lives in minigames.py.

Cards [known] (AppendCardText S 00448490): 0..51, rank = c % 13 (0 = '2' .. 12 = 'A'), suit = c // 13
in the order d h s c. CARD_BACK 0x34 draws the back, NO_CARD 0xFF draws nothing.

Hand value [known] (FormatHandValue S 004484f0; winners are picked by the client as the highest u32 among
a pot's eligible seats, LogPotResults S 0044a3e0 / AnimatePayout S 005250f0):
  hndval = category << 24 | n0 << 16 | n1 << 12 | n2 << 8 | n3 << 4 | n4      (n = rank 0..12)
  0 high card  n0..n4        1 pair      n0 pair, n1..n3 kickers   2 two pair  n0 high, n1 low, n2 kicker
  3 trips      n0, n1 n2     4 straight  n0 top rank               5 flush     n0..n4
  6 full house n0 trips, n1 pair         7 quads     n0, n1 kicker 8 straight flush  n0 top rank
  Preflop (two cards) the client shows only categories 0 (n0, n1) and 1 (n0).
  A five-high straight (wheel) has top rank 3 ('5').

Action codes [known] (GetActionText S 00449870): the client fills at most THREE buttons from `actns`,
in the order RAISE, BET, FOLD, CALL, CHECK, ALLIN, with no bounds check — a fourth set bit overwrites a
widget pointer and crashes the client (MinigameDialog_Poker::Update S 0044b3c0).
"""
from itertools import combinations

CARD_BACK, NO_CARD = 0x34, 0xFF
CALL, FOLD, RAISE, CHECK, BET, SMALL_BLIND, BIG_BLIND, ALLIN = 2, 4, 8, 0x10, 0x20, 0x40, 0x80, 0x100
BUTTON_ORDER = (RAISE, BET, FOLD, CALL, CHECK, ALLIN)
MAX_BUTTONS = 3
#: Per-player `actn` flags (bits 11-15). Effects [known]: bit 12 draws the sit-out marker, bits 11 and 12
#: block the local turn (IsLocalPlayersTurn S 00489b80), bits 13 and 15 make the status line read
#: "wait for next round" instead of the hand value (S 0044b3c0). Their names are the server's use.
ACTN_ALLIN, ACTN_SITOUT, ACTN_FOLDED, ACTN_OUT_OF_HAND = 1 << 11, 1 << 12, 1 << 13, 1 << 15
CATEGORY_NAMES = ("high card", "pair", "two pair", "trips", "straight", "flush", "full house",
                  "quads", "straight flush")


def rank(c):
    return c % 13


def suit(c):
    return c // 13


def card_text(c):
    return "23456789TJQKA"[rank(c)] + "dhsc"[suit(c)]


def encode(category, nibbles):
    v = category << 24
    for i, n in enumerate(nibbles[:5]):
        v |= (n & 0xF) << (16 - 4 * i)
    return v


def _straight_top(ranks):
    """Top rank of a straight in a set of ranks, or None. A-2-3-4-5 tops at 3 ('5')."""
    rs = set(ranks)
    for top in range(12, 3, -1):
        if all(r in rs for r in range(top - 4, top + 1)):
            return top
    if {12, 0, 1, 2, 3} <= rs:
        return 3
    return None


def _value5(cards):
    ranks = sorted((rank(c) for c in cards), reverse=True)
    flush = len({suit(c) for c in cards}) == 1
    top = _straight_top(ranks) if len(set(ranks)) == 5 else None
    counts = sorted(((ranks.count(r), r) for r in set(ranks)), reverse=True)
    shape = [n for n, _ in counts]
    by_count = [r for _, r in counts]
    if flush and top is not None:
        return encode(8, [top])
    if shape == [4, 1]:
        return encode(7, by_count)
    if shape == [3, 2]:
        return encode(6, by_count)
    if flush:
        return encode(5, ranks)
    if top is not None:
        return encode(4, [top])
    if shape == [3, 1, 1]:
        return encode(3, by_count)
    if shape == [2, 2, 1]:
        return encode(2, by_count)
    if shape == [2, 1, 1, 1]:
        return encode(1, by_count)
    return encode(0, ranks)


def hand_value(cards):
    """The client's hndval for the best hand in `cards` (2 hole cards + 0..5 board cards)."""
    cards = list(cards)
    if len(cards) < 5:
        ranks = sorted((rank(c) for c in cards), reverse=True)
        if len(ranks) >= 2 and ranks[0] == ranks[1]:
            return encode(1, [ranks[0]] + ranks[2:])
        return encode(0, ranks)
    return max(_value5(combo) for combo in combinations(cards, 5))


def describe(value):
    return CATEGORY_NAMES[value >> 24] + " " + "".join(
        "23456789TJQKA"[(value >> (16 - 4 * i)) & 0xF] for i in range(5))


def buttons(to_call, stack, wager, highest, min_raise, min_bet):
    """The `actns` mask for the player to act: at most MAX_BUTTONS of the six button bits."""
    if stack <= 0:
        return 0
    if to_call <= 0:
        opts = [CHECK]
        if highest > 0:
            opts.append(RAISE if stack + wager >= highest + min_raise else ALLIN)
        else:
            opts.append(BET if stack >= min_bet else ALLIN)
        if ALLIN not in opts:
            opts.append(ALLIN)
    elif stack > to_call:
        opts = [FOLD, CALL, RAISE if stack + wager >= highest + min_raise else ALLIN]
    else:
        opts = [FOLD, ALLIN]                    # calling would take everything: the all-in button
    mask = 0
    for b in opts[:MAX_BUTTONS]:
        mask |= b
    return mask


def pot_bands(contrib, live):
    """Pots from each player's total contribution this hand, as contribution bands.

    contrib: perm -> chips put in (folded and departed players included); live: perms still holding
    cards. Returns [(amount, eligible perms, lo, hi)], main pot first: each pot holds every player's
    chips between lo and hi. Consecutive bands with the same eligible set are merged; chips above the
    highest live stake (folded money) belong to the last pot (hi = None, unbounded)."""
    levels = sorted({c for p, c in contrib.items() if p in live and c > 0})
    bands, prev = [], 0
    for level in levels:
        eligible = frozenset(p for p in live if contrib.get(p, 0) >= level)
        if bands and bands[-1][1] == eligible:
            bands[-1] = (None, eligible, bands[-1][2], level)
        else:
            bands.append((None, eligible, prev, level))
        prev = level
    if bands:
        bands[-1] = (None, bands[-1][1], bands[-1][2], None)
    return [(band_amount(contrib, lo, hi), eligible, lo, hi) for _, eligible, lo, hi in bands]


def band_amount(contrib, lo, hi):
    return sum(_slice(c, lo, hi) for c in contrib.values())


def _slice(c, lo, hi):
    return (c if hi is None else min(c, hi)) - min(c, lo)


def side_pots(contrib, live):
    """[(amount, eligible)] — see pot_bands."""
    return [(a, e) for a, e, _, _ in pot_bands(contrib, live)]


def street_wagers(before, after, lo, hi):
    """Each player's chips that went into the band [lo, hi) on this street (phase-8 animation)."""
    return {p: _slice(c, lo, hi) - _slice(before.get(p, 0), lo, hi) for p, c in after.items()}


def split(amount, winners):
    """Shares as the client shows them (integer division); the remainder goes to the first winner in
    the given order [decision — the client's own log drops it]."""
    share = amount // len(winners)
    out = {w: share for w in winners}
    out[winners[0]] += amount - share * len(winners)
    return out
