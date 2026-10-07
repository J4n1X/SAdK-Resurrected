"""
Minigame tables (offline): packed-uint coding, the table body read back in the client's reader
order (MiniGameKey::Read, ReadTableSettings, ReadSeats, Dice ReadTableState), the dice payout rule,
and a full create / join / bet / roll / leave cycle with the refusals.

Run:  python tests/test_minigames.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import economy, minigames as mg  # noqa: E402

# Table creation is switched off live (it crashed the client); the logic is still tested with Dice on.
LIVE_PLAYABLE = mg.PLAYABLE
mg.PLAYABLE = (mg.DICE,)
from sadk_lobby.village import BitReader, BitWriter  # noqa: E402

A, B = 5001, 5002


class FakeIo(mg.Io):
    def __init__(self):
        self.log = []          # (conn, msg, body)
        self.cells = []
        super().__init__(send=lambda c, m, b: self.log.append((c, m, b)),
                         everyone=lambda: ["world"],
                         publish_cell=lambda cell, name: self.cells.append((cell, name)))

    def msgs(self):
        out = [(c, m) for c, m, _ in self.log]
        self.log.clear()
        return out

    def last(self, msg):
        return next(b for _, m, b in reversed(self.log) if m == msg)


def decode(body):
    """Read a 0xD9/0xDA body the way the client does."""
    r = BitReader(body)
    mngt = r.read(8)
    out = {"type": mngt & 0xF, "scntbl": r.read(8), "chtid": mg.read_packed(r),
           "key": (r.read(16), r.read(8))}
    if mngt & 0x10:
        out["settings"] = (r.read(8), r.read(32), bytes(r.read(8) for _ in range(r.read(8))).decode(),
                           mg.read_packed(r), mg.read_packed(r), r.read(4))
    if mngt & 0x40:
        seats = []
        for _ in range(r.read(4)):
            assert r.read(1) == 1                       # only used = 1 entries
            seats.append((r.read(4), r.read(2), mg.read_packed(r)))
        out["seats"] = seats
    if mngt & 0x80:
        dice, _dlr, n, phase, _t = r.read(8), r.read(8), r.read(8), r.read(8), r.read(16)
        players = []
        for _ in range(n):
            players.append((r.read(8), mg.read_packed(r), mg.read_packed(r),
                            [mg.read_packed(r) for _ in range(11)]))
        out["dice"], out["phase"], out["players"] = dice, phase, players
    return out


def _create(io, conn, perm, kind=1, tavern=2, index=0, psswd=0, crc=0):
    w = BitWriter().write(kind, 8).write(1, 8).write(100, 32).write_string("Würfeltisch")
    w.write(10, 32).write(0x7FFFFFFF, 32).write(4, 8).write(tavern, 8).write(index, 8)
    w.write(psswd, 8).write(crc, 32)
    mg.handle_create(io, conn, perm, w.bytes())


def _join(io, conn, perm, key, stake=300, crc=0):
    mg.handle_join(io, conn, perm, BitWriter().write(key[0], 16).write(key[1], 8)
                   .write(stake, 32).write(crc, 32).bytes())


def test_packed_round_trip():
    for v in (0, 1, 15, 16, 255, 1000, 0x12345, 0x7FFFFFFF, 0xFFFFFFFF):
        w = BitWriter()
        mg.write_packed(w, v)
        assert mg.read_packed(BitReader(w.bytes())) == v, v
    print("packed uint round trip OK")


def test_payout_rule():
    bets = [0] * 11
    bets[5] = 10                                   # on 7
    assert mg.payout(bets, 7) == 30 and mg.payout(bets, 6) == 0
    bets = [0] * 11
    bets[2], bets[4] = 10, 20                      # on 4 and 6 (group A)
    assert mg.payout(bets, 4) == 10 * 5 + 20 and mg.payout(bets, 3) == 0
    print("dice payout rule OK")


def test_dice_table_cycle():
    mg.reset_for_tests()
    economy.reset_for_tests()
    io = FakeIo()
    _create(io, "a", A)
    assert io.cells == [(1001, "Würfeltisch")]
    t = mg._tables[(1, 0)]
    created = decode(io.last(mg.MSG_CREATE))
    assert created["type"] == 1 and created["chtid"] == 1001 and created["key"] == (1, 0)
    assert created["settings"][2] == "Würfeltisch" and created["seats"] == []
    assert [m for _, m in io.msgs()] == [mg.MSG_CREATE, mg.MSG_UPDATE]
    _create(io, "b", B)                            # same tavern slot → refused
    assert io.msgs() == [("b", mg.MSG_NO_TABLE)]

    _join(io, "a", A, t.key, stake=300)
    _join(io, "b", B, t.key, stake=200)
    upd = decode(io.last(mg.MSG_UPDATE))
    assert upd["seats"] == [(0, 1, A), (1, 1, B)]
    assert [(p[0], p[1]) for p in upd["players"]] == [(0, 300), (1, 200)]
    assert economy.wallet(A).gold == economy.config.START_GOLD - 300
    io.log.clear()

    bets = [0] * 11
    bets[5] = 50                                   # A bets 50 on 7
    w = BitWriter().write(1, 16).write(0, 8)
    mg.write_packed(w, 250)
    for b in bets:
        mg.write_packed(w, b)
    mg.handle_place_bets(io, "a", A, w.bytes())
    assert t.credits[A] == 250 and t.bets[A][5] == 50

    later = []
    mg.random.seed(3)
    mg.handle_roll(io, "a", A, BitWriter().write(1, 16).write(0, 8).bytes(), schedule=later.append)
    res = decode(io.last(mg.MSG_UPDATE))
    total = (res["dice"] >> 4) + (res["dice"] & 0xF)
    assert res["phase"] == mg.PHASE_RESULT
    assert t.credits[A] == 250 + (150 if total == 7 else 0)
    later[0]()                                     # the timer fires: back to betting, bets cleared
    assert t.phase == mg.PHASE_BETTING and t.bets[A] == [0] * 11

    io.log.clear()
    mg.handle_leave(io, "b", B, BitWriter().write(1, 16).write(0, 8).bytes())
    assert economy.wallet(B).gold == economy.config.START_GOLD
    mg.leave_all(io, A)
    assert io.msgs()[-1] == ("world", mg.MSG_REMOVE) and mg._tables == {}
    print(f"dice table create / join / bet / roll ({total}) / leave / remove OK")


def test_full_and_protected_tables():
    mg.reset_for_tests()
    io = FakeIo()
    _create(io, "a", A, kind=2, tavern=4)                          # Poker: refused (crashed the client)
    assert io.msgs() == [("a", mg.MSG_NO_TABLE)]
    _create(io, "a", A, kind=1, tavern=3, psswd=1, crc=0xABCD)
    key = (1, 0)
    io.log.clear()
    _join(io, "b", B, key, crc=0x1111)                            # wrong password CRC
    assert io.msgs() == [("b", mg.MSG_NO_SEAT)]
    _join(io, "b", B, key, crc=0xABCD)
    assert io.msgs()[-1] == ("world", mg.MSG_UPDATE)
    print("protected / non-dice tables OK")


def test_live_refuses_every_table():
    assert LIVE_PLAYABLE == ()
    print("live: every table type refused (0xDB) until the crash is traced OK")


if __name__ == "__main__":
    test_live_refuses_every_table()
    test_packed_round_trip()
    test_payout_rule()
    test_dice_table_cycle()
    test_full_and_protected_tables()
    print("\nAll minigame tests PASSED")
