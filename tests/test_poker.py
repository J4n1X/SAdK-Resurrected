"""
Poker (offline): the hand evaluator in the client's hndval encoding, the button mask limit, side pots,
and whole hands through the table flow, every 0xD9 read back in the client's reader order
(MiniGamePokerProxy::ReadTableState S 004894a0) and checked against the client's crash limits.

Run:  python tests/test_poker.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))
from sadk_lobby import economy, minigames as mg, poker  # noqa: E402
from sadk_lobby.village import BitReader, BitWriter  # noqa: E402

A, B, C = 6001, 6002, 6003
R = {r: i for i, r in enumerate("23456789TJQKA")}
S = {s: i for i, s in enumerate("dhsc")}


def cards(text):
    return [S[c[1]] * 13 + R[c[0]] for c in text.split()]


# ── evaluator ─────────────────────────────────────────────────────────────────
def test_hand_values():
    hv = lambda t: poker.hand_value(cards(t))                     # noqa: E731
    assert hv("Ad Kd Qd Jd Td 2c 3h") == poker.encode(8, [12])
    assert hv("Ad 2d 3d 4d 5d 9c 9h") == poker.encode(8, [3])     # steel wheel tops at '5'
    assert hv("9d 9h 9s 9c Kd 2c 3h") == poker.encode(7, [7, 11])
    assert hv("9d 9h 9s Kc Kd 2c 3h") == poker.encode(6, [7, 11])
    assert hv("2d 7d 9d Jd Kd Ac 3h") == poker.encode(5, [11, 9, 7, 5, 0])
    assert hv("Ac 2d 3h 4s 5d 9c Kh") == poker.encode(4, [3])     # wheel
    assert hv("9d 9h 9s Kc 4d 2c 3h") == poker.encode(3, [7, 11, 2])
    assert hv("9d 9h Ks Kc 4d 2c 3h") == poker.encode(2, [11, 7, 2])
    assert hv("9d 9h Ks Qc 4d 2c 3h") == poker.encode(1, [7, 11, 10, 2])
    assert hv("9d 7h Ks Qc 4d 2c 3h") == poker.encode(0, [11, 10, 7, 5, 2])
    assert hv("Ad Ah") == poker.encode(1, [12])                    # preflop: cat 1, n0
    assert hv("Kd Ah") == poker.encode(0, [12, 11])                # preflop: cat 0, n0 n1
    # Order: the client compares plain u32s.
    order = ["9d 7h Ks Qc 4d 2c 3h", "9d 9h Ks Qc 4d 2c 3h", "9d 9h Ks Kc 4d 2c 3h",
             "9d 9h 9s Kc 4d 2c 3h", "Ac 2d 3h 4s 5d 9c Kh", "6c 2d 3h 4s 5d 9c Kh",
             "2d 7d 9d Jd Kd Ac 3h", "9d 9h 9s Kc Kd 2c 3h", "9d 9h 9s 9c Kd 2c 3h",
             "Ad 2d 3d 4d 5d 9c 9h", "Ad Kd Qd Jd Td 2c 3h"]
    vals = [hv(t) for t in order]
    assert vals == sorted(vals) and len(set(vals)) == len(vals)
    assert all(v >> 24 <= 8 for v in vals)
    print("hand values in the client's encoding, ordered OK")


def test_buttons_never_more_than_three():
    for to_call in (0, 5, 50, 500):
        for stack in (0, 1, 5, 40, 1000):
            for highest in (0, 10, 100):
                m = poker.buttons(to_call, stack, 0, highest, 10, 10)
                assert bin(m & 0x13E).count("1") <= 3, (to_call, stack, highest, hex(m))
                assert not m & (poker.SMALL_BLIND | poker.BIG_BLIND)
    print("never more than 3 button bits OK")


def test_side_pots():
    contrib = {A: 100, B: 300, C: 300}
    assert poker.side_pots(contrib, {A, B, C}) == [(300, frozenset({A, B, C})), (400, frozenset({B, C}))]
    assert poker.side_pots({A: 50, B: 200, C: 200}, {A, B}) == [(150, frozenset({A, B})),
                                                                (300, frozenset({B}))]
    print("side pots OK")


# ── table flow ────────────────────────────────────────────────────────────────
class FakeIo(mg.Io):
    def __init__(self):
        self.log, self.private, self.timers = [], [], []
        super().__init__(send=lambda c, m, b: self.log.append((c, m, b)),
                         everyone=lambda: ["world"],
                         publish_cell=lambda cell, name: None,
                         zone_of=lambda perm_id: 3,
                         stats=lambda perm_id: None,
                         schedule=lambda delay, fn: self.timers.append((delay, fn)),
                         send_to=lambda perm, m, b: self.private.append((perm, m, b)))

    def fire(self):
        delay, fn = self.timers[-1]
        self.timers.clear()
        fn()
        return delay

    def state(self):
        return read_state(next(b for _, m, b in reversed(self.log) if m == mg.MSG_UPDATE))


def read_state(body):
    """MiniGameKey + seats + the Poker state block, in the client's reader order, asserting the
    client's crash limits on the way."""
    r = BitReader(body)
    mngt = r.read(8)
    assert mngt & 0xF == mg.POKER
    out = {"scntbl": r.read(8), "chtid": mg.read_packed(r), "key": (r.read(16), r.read(8))}
    if mngt & 0x10:
        r.read(8), r.read(32), bytes(r.read(8) for _ in range(r.read(8))), mg.read_packed(r), \
            mg.read_packed(r), r.read(4)
    seats = []
    if mngt & 0x40:
        for _ in range(r.read(4)):
            assert r.read(1) == 1
            seats.append((r.read(4), r.read(2), mg.read_packed(r)))
    out["seats"] = seats
    if not mngt & 0x80:
        return out
    occupied = {s for s, _, _ in seats} if seats else None
    dlr, n, cur, actns = r.read(8), r.read(8), r.read(8), r.read(16)
    phase, rnd, egr, shw, _t = r.read(8), r.read(8), r.read(8), r.read(8), r.read(16)
    minwgr, lstply, lstvl, mnrs, lstactn = r.read(32), r.read(8), mg.read_packed(r), mg.read_packed(r), r.read(16)
    board = []
    if rnd > 1:
        board += [r.read(8) for _ in range(3)]
    if rnd > 2:
        board.append(r.read(8))
    if rnd > 3:
        board.append(r.read(8))
    wgrmsk = r.read(8)
    wagers = {s: mg.read_packed(r) for s in range(8) if wgrmsk >> s & 1}
    players = {}
    for _ in range(n):
        s = r.read(8)
        assert s < 8, "sltidx >= 8 writes past the seat array"
        rec = {"trsf": r.read(1)}
        if rec["trsf"]:
            rec["cards"], rec["hndval"] = (r.read(8), r.read(8)), r.read(32)
            assert rec["hndval"] >> 24 <= 8, "hand category > 8 indexes past the name table"
        rec["actn"], rec["crdts"], rec["accnt"] = r.read(16), mg.read_packed(r), mg.read_packed(r)
        players[s] = rec
    ptn = r.read(8)
    assert ptn & 0x7F <= 8, "more than 8 pots overwrites the state counter"
    pots = []
    for _ in range(ptn & 0x7F):
        pot = {"amount": r.read(32), "plrmsk": r.read(8)}
        if ptn & 0x80:
            m = r.read(8)
            pot["wagers"] = {s: mg.read_packed(r) for s in range(8) if m >> s & 1}
        pots.append(pot)
    # The client's crash limits [known]:
    assert bin(actns & 0x13E).count("1") <= 3, "a 4th button bit overwrites a widget pointer"
    assert dlr == 0xFF or dlr in players, f"dealer seat {dlr}"
    # The board gets crntplyr in phase 6 and 0xFF in every other phase (S 00525550), so 0xFF is the
    # value it handles on every non-betting frame; anything else must be a seat.
    assert cur == 0xFF or cur in players, f"crntplyr {cur}"
    assert shw in (0xFE, 0xFF) or shw in players
    assert lstply == 0xFF or lstply in players
    out.update(dlr=dlr, cur=cur, actns=actns, phase=phase, round=rnd, egr=egr, shw=shw, minwgr=minwgr,
               lstply=lstply, lstvl=lstvl, mnrs=mnrs, lstactn=lstactn, board=board, wagers=wagers,
               players=players, pots=pots, per_pot=bool(ptn & 0x80))
    return out


def _create(io, perm, stake=1000, minimum=10, maxp=4):
    w = BitWriter().write(mg.POKER, 8).write(0, 8).write(stake, 32).write_string("Poker")
    w.write(minimum, 32).write(0x7FFFFFFF, 32).write(maxp, 8).write(1, 8).write(0xFF, 8).write(0, 8).write(0, 32)
    mg.handle_create(io, "a", perm, w.bytes())


def _join(io, perm, key, stake=1000):
    mg.handle_join(io, "b", perm, BitWriter().write(key[0], 16).write(key[1], 8)
                   .write(stake, 32).write(0, 32).bytes())


def _act(io, perm, key, code, wgr=None):
    w = BitWriter().write(key[0], 16).write(key[1], 8).write(code, 16)
    if wgr is not None:
        mg.write_packed(w, wgr)
    mg.handle_game_action(io, None, perm, mg.MSG_POKER_WAGER if wgr is not None else mg.MSG_POKER_ACTION,
                          w.bytes())


def _check_all(io):
    """Every table update ever sent decodes cleanly within the client's limits."""
    for _, m, b in io.log:
        if m == mg.MSG_UPDATE:
            read_state(b)


def _table_with(io, *perms):
    mg.reset_for_tests()
    economy.reset_for_tests()
    _create(io, perms[0])
    t = next(iter(mg._tables.values()))
    for p in perms[1:]:
        _join(io, p, t.key)
    return t


def _to_betting(io, t):
    while t.phase != 6:
        io.fire()


def test_heads_up_showdown():
    io = FakeIo()
    t = _table_with(io, A, B)
    st = io.state()
    assert st["phase"] == 1 and st["dlr"] == 0xFF and st["pots"] == []
    io.fire()                                                     # hand starts: blinds, 303s, deal
    assert t.hand is not None and t.phase == 5
    st = io.state()
    assert st["phase"] == 5 and st["round"] == 1 and st["dlr"] == 0
    assert {p for p, m, _ in io.private if m == mg.MSG_HAND} == {A, B}   # hole cards to the owners only
    assert st["wagers"] == {0: 5, 1: 10} and st["lstactn"] == poker.BIG_BLIND and st["lstply"] == 1
    assert all(not p["trsf"] for p in st["players"].values())         # face down for everyone
    io.fire()                                                     # betting: heads-up, the button acts first
    st = io.state()
    assert st["phase"] == 6 and st["cur"] == 0 and st["minwgr"] == 10
    assert st["actns"] == poker.FOLD | poker.CALL | poker.RAISE
    _act(io, B, t.key, poker.CALL)                                # not B's turn: ignored
    assert io.state()["cur"] == 0
    _act(io, A, t.key, poker.CALL)
    st = io.state()
    assert st["cur"] == 1 and st["actns"] & poker.CHECK and st["lstactn"] == poker.CALL
    _act(io, B, t.key, poker.CHECK)
    st = io.state()
    assert st["phase"] == 8 and st["per_pot"] and st["pots"][0]["amount"] == 20
    assert st["pots"][0]["wagers"] == {0: 10, 1: 10} and st["wagers"] == {}
    io.fire()                                                     # flop
    st = io.state()
    assert st["phase"] == 5 and st["round"] == 2 and len(st["board"]) == 3
    io.fire()
    st = io.state()
    assert st["phase"] == 6 and st["cur"] == 1                    # postflop: the big blind first
    assert st["actns"] == poker.CHECK | poker.BET | poker.ALLIN and st["minwgr"] == 10
    _act(io, B, t.key, poker.CHECK)
    _act(io, A, t.key, poker.BET, 50)
    st = io.state()
    assert st["wagers"] == {0: 50} and st["minwgr"] == 50 and st["mnrs"] == 50 and st["lstvl"] == 50
    _act(io, B, t.key, poker.CALL)
    for street in (3, 4):
        io.fire()
        io.fire()
        assert io.state()["round"] == street
        _act(io, B, t.key, poker.CHECK)
        _act(io, A, t.key, poker.CHECK)
    io.fire()                                                     # river collected → showdown
    st = io.state()
    assert st["phase"] == 9 and st["shw"] in (0, 1)
    vals = {s: p["hndval"] for s, p in st["players"].items()}
    assert all(p["trsf"] for p in st["players"].values())
    pot = st["pots"][0]
    assert pot["amount"] == 120 and pot["plrmsk"] == 0b11
    best = max(vals.values())
    winners = [s for s, v in vals.items() if v == best]
    assert t.credits[A] + t.credits[B] == 2000
    for s in winners:
        assert t.credits[t.seats[s]] >= 1000 - 60 + 120 // len(winners)
    io.fire()                                                     # next hand: phase 1, then button moves
    assert t.hand is None and io.state()["phase"] == 1
    io.fire()
    assert io.state()["dlr"] == 1
    _check_all(io)
    print("heads-up hand: blinds, preflop, flop bet/call, showdown, payout OK")


def test_fold_and_timeout():
    io = FakeIo()
    t = _table_with(io, A, B, C)
    io.fire()
    _to_betting(io, t)
    st = io.state()
    assert st["dlr"] == 0 and st["cur"] == 0                       # 3-handed: after the big blind (seat 2)
    _act(io, A, t.key, poker.RAISE, 40)
    assert io.state()["minwgr"] == 40 and io.state()["mnrs"] == 30
    assert io.timers[-1][0] == mg.POKER_TURN_SECS
    io.fire()                                                     # B times out facing a raise: folds
    assert B in t.hand.folded
    _act(io, C, t.key, poker.FOLD)
    st = io.state()
    assert st["phase"] == 8
    io.fire()
    st = io.state()
    assert st["phase"] == 9 and st["shw"] == 0xFE and st["pots"][0]["plrmsk"] == 0b001
    assert t.credits[A] == 1000 + 5 + 10
    io.fire()
    _check_all(io)
    print("raise, timeout fold, fold win (no showdown) OK")


def test_all_in_runout_and_side_pot():
    io = FakeIo()
    t = _table_with(io, A, B, C)
    t.credits[C] = 100                                            # C is short
    io.fire()
    _to_betting(io, t)
    _act(io, A, t.key, poker.ALLIN)
    _act(io, B, t.key, poker.ALLIN)
    _act(io, C, t.key, poker.ALLIN)
    st = io.state()
    assert st["phase"] == 8
    io.fire()
    st = io.state()
    assert st["phase"] == 5 and st["round"] == 4 and st["egr"] == 1 and len(st["board"]) == 5
    io.fire()                                                     # straight to the showdown
    st = io.state()
    assert st["phase"] == 9 and [p["amount"] for p in st["pots"]] == [300, 1800]
    assert st["pots"][1]["plrmsk"] == 0b011
    assert sum(t.credits.values()) == 2100
    _check_all(io)
    print("all-in run-out (egr 1) and side pot OK")


def test_leave_mid_hand_and_sit_out():
    io = FakeIo()
    t = _table_with(io, A, B, C)
    io.fire()
    _to_betting(io, t)
    mg.handle_leave(io, None, A, BitWriter().write(t.key[0], 16).write(t.key[1], 8).bytes())
    assert t.seat_of(A) is None and t.credits.get(A) is None
    io.fire()                                                     # the turn moves on without A
    st = io.state()
    assert st["cur"] in (1, 2) and 0 not in st["players"]
    w = BitWriter().write(t.key[0], 16).write(t.key[1], 8).write(1, 8)
    mg.handle_game_action(io, None, t.seats[st["cur"]], mg.MSG_POKER_SITOUT, w.bytes())
    st2 = io.state()
    assert st2["cur"] != st["cur"] or st2["phase"] != 6
    assert any(p["actn"] & poker.ACTN_SITOUT for p in st2["players"].values())
    _check_all(io)
    print("leave mid-hand folds, sit-out acts for the player OK")


if __name__ == "__main__":
    test_hand_values()
    test_buttons_never_more_than_three()
    test_side_pots()
    test_heads_up_showdown()
    test_fold_and_timeout()
    test_all_in_runout_and_side_pot()
    test_leave_mid_hand_and_sit_out()
    print("\nAll poker tests PASSED")
