"""
PawnChess (offline): the rules as the client's move generator has them, and whole games through the
table flow with every 0xD9 read back in the client's order (MiniGamePawnChessProxy::ReadTableState
S 0048a6d0) and checked against what the client needs (trnid never 0xFF and changed after every
answered action, 16 distinct squares).

Run:  python tests/test_pawnchess.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))
from sadk_lobby import economy, minigames as mg, pawnchess as pc  # noqa: E402
from sadk_lobby.village import BitReader, BitWriter  # noqa: E402

A, B = 7001, 7002
P = pc.Piece


def board(*pieces):
    """Pad to 16 pieces with pawns parked on free squares far from the action (row 7 / 6)."""
    pieces = list(pieces)
    used = {p.square for p in pieces}
    spare = [s for s in range(63, -1, -1) if s not in used]
    while len(pieces) < 16:
        side = 0 if sum(p.side == 0 for p in pieces) < 8 else 1
        pieces.append(P(spare.pop(0), side))
    return pieces


# ── rules ─────────────────────────────────────────────────────────────────────
def test_rules():
    b = pc.initial_board()
    assert [p.square for p in b[:8]] == [pc.sq(0, r) for r in range(8)]
    assert [p.square for p in b[8:]] == [pc.sq(7, r) for r in range(8)]
    assert pc.targets(b, 0) == [pc.sq(1, 0)]                      # side 0 pawns walk towards column 7
    assert pc.targets(b, 8) == [pc.sq(6, 0)]
    # Diagonal capture only onto an enemy; forward only onto an empty square.
    b = board(P(pc.sq(3, 3), 0), P(pc.sq(4, 3), 1), P(pc.sq(4, 4), 1), P(pc.sq(4, 2), 0))
    assert sorted(pc.targets(b, 0)) == [pc.sq(4, 4)]
    # King: 8 neighbours, not onto own pieces, attacked squares allowed.
    b = board(P(pc.sq(3, 3), 0, king=True), P(pc.sq(4, 3), 0))
    assert len(pc.targets(b, 0)) == 7
    # Taking a pawn converts it into the captor's column-local reserve.
    b = board(P(pc.sq(3, 3), 0), P(pc.sq(4, 4), 1))
    spots = pc.relocation_squares(b, 4, 0)
    assert pc.sq(4, 0) in spots and pc.sq(4, 4) not in spots
    assert pc.apply(b, 0, pc.sq(4, 4), spots[0]) is None
    assert b[1].side == 0 and b[1].square == spots[0] and b[0].square == pc.sq(4, 4)
    # A full column pushes the relocation towards the captor's home.
    b = [P(pc.sq(5, r), 1) for r in range(8)] + [P(pc.sq(4, 3), 0)] + \
        [P(pc.sq(c, 7), 0) for c in range(7)]
    assert all(pc.col_row(s)[0] == 4 for s in pc.relocation_squares(b, 5, 0))
    # Edge win.
    b = board(P(pc.sq(6, 2), 0))
    assert pc.apply(b, 0, pc.sq(7, 2)) == "edge"
    print("moves, captures with conversion, relocation, edge OK")


def test_check_mark_and_mate():
    # Side 1 pawn at (2,3) attacks (1,2) and (1,4): the side-0 king on (1,4) is in check; the side-0 pawn
    # on (1,2) can take the checker on (2,3) = its row + 1 -> mark without the 0x10 direction bit.
    b = board(P(pc.sq(1, 4), 0, king=True), P(pc.sq(1, 2), 0), P(pc.sq(2, 3), 1),
              P(pc.sq(7, 0), 1, king=True))
    in_check, marked, mark = pc.check_mark(b, 0)
    assert in_check and marked == 1 and mark == 1
    pieces, m = pc.movable(b, 0)
    assert sorted(pieces) == [0, 1] and pc.targets(b, 1, m) == [pc.sq(2, 3)]
    assert not pc.is_mated(b, 0)
    # Mate: side-0 king in the corner (0,0), checked by a side-1 pawn on (1,1); (1,0) is covered by the
    # side-1 king on (2,1), (0,1) by the side-1 pawn on (1,2); taking the checker leaves the king next to
    # the enemy king. No side-0 pawn can take the checker.
    b = board(P(pc.sq(0, 0), 0, king=True), P(pc.sq(2, 1), 1, king=True), P(pc.sq(1, 1), 1),
              P(pc.sq(1, 2), 1))
    assert pc.checkers(b, 0) and pc.check_mark(b, 0)[1] is None
    assert pc.is_mated(b, 0)
    # Same, but the (0,1) cover is gone: the king escapes.
    b = board(P(pc.sq(0, 0), 0, king=True), P(pc.sq(2, 1), 1, king=True), P(pc.sq(1, 1), 1))
    assert not pc.is_mated(b, 0)
    print("check, marked pawn, mate detection OK")


# ── table flow ────────────────────────────────────────────────────────────────
class FakeIo(mg.Io):
    def __init__(self):
        self.log, self.timers = [], []
        super().__init__(send=lambda c, m, b: self.log.append((c, m, b)), everyone=lambda: ["world"],
                         publish_cell=lambda cell, name: None, zone_of=lambda perm_id: 3,
                         stats=lambda perm_id: None, schedule=lambda d, fn: self.timers.append((d, fn)))

    def state(self):
        return read_state(next(b for _, m, b in reversed(self.log) if m == mg.MSG_UPDATE))


def read_state(body):
    r = BitReader(body)
    mngt = r.read(8)
    assert mngt & 0xF == mg.PAWNCHESS
    r.read(8), mg.read_packed(r), r.read(16), r.read(8)
    if mngt & 0x10:
        r.read(8), r.read(32), bytes(r.read(8) for _ in range(r.read(8))), mg.read_packed(r), \
            mg.read_packed(r), r.read(4)
    if mngt & 0x40:
        for _ in range(r.read(4)):
            r.read(1), r.read(4), r.read(2), mg.read_packed(r)
    out = {"phase": r.read(8), "trnid": r.read(8), "pwchkmt": r.read(8), "plrstt": r.read(8)}
    out["pieces"] = [r.read(8) for _ in range(16)]
    assert out["trnid"] != 0xFF, "trnid 0xFF equals the client's reset latch: its board would stay locked"
    squares = [p & 0x3F for p in out["pieces"]]
    assert len(set(squares)) == 16, "two pieces on one square"
    players = {}
    for _ in range(r.read(8)):
        s = r.read(8)
        assert s < 8
        players[s] = (mg.read_packed(r), mg.read_packed(r))
    out["players"] = players
    return out


def _key(t):
    return BitWriter().write(t.key[0], 16).write(t.key[1], 8)


def _send(io, t, perm, msg, *fields):
    w = _key(t)
    for f in fields:
        w.write(f, 8)
    before = io.state()["trnid"] if any(m == mg.MSG_UPDATE for _, m, _ in io.log) else None
    mg.handle_game_action(io, None, perm, msg, w.bytes())
    after = io.state()
    if msg != mg.MSG_CHESS_NEWGAME:
        assert after["trnid"] != before, "an answered action must change trnid"
    return after


def _game(io):
    mg.reset_for_tests()
    economy.reset_for_tests()
    w = BitWriter().write(mg.PAWNCHESS, 8).write(0, 8).write(500, 32).write_string("Bauernschach")
    w.write(50, 32).write(0x7FFFFFFF, 32).write(2, 8).write(1, 8).write(0xFF, 8).write(0, 8).write(0, 32)
    mg.handle_create(io, "a", A, w.bytes())
    t = next(iter(mg._tables.values()))
    mg.handle_join(io, "b", B, _key(t).write(500, 32).write(0, 32).bytes())
    # The first game starts by itself: a freshly seated client's new-game request is already pending
    # (proxy ctor S 00489f92), so it cannot press NewGame before the first game over.
    st = io.state()
    assert st["phase"] == 2 and t.credits[A] == 450 and t.credits[B] == 450
    return t


def test_game_flow_and_edge_win():
    io = FakeIo()
    t = _game(io)
    st = _send(io, t, B, mg.MSG_CHESS_KING, 4)                    # not B's turn: rejected, board unlocked
    assert st["phase"] == 2
    st = _send(io, t, A, mg.MSG_CHESS_KING, 3)
    assert st["phase"] == 3 and st["pieces"][3] & 0x40            # piece 3 (col 0, row 3) is the king
    st = _send(io, t, B, mg.MSG_CHESS_KING, 4)
    assert st["phase"] == 4 and st["pieces"][12] & 0x40
    st = _send(io, t, A, mg.MSG_CHESS_MOVE, 0, pc.sq(1, 0))
    assert st["phase"] == 5 and st["pieces"][0] & 0x3F == pc.sq(1, 0)
    st = _send(io, t, B, mg.MSG_CHESS_MOVE, 8, pc.sq(5, 0))      # illegal (two squares): rejected
    assert st["phase"] == 5
    st = _send(io, t, B, mg.MSG_CHESS_MOVE, 8, pc.sq(6, 0))
    assert st["phase"] == 4
    # Shortcut to the end: a side-0 pawn one step from column 7 next to an empty square.
    t.chess[9].square = pc.sq(5, 1)
    t.chess[1].square = pc.sq(6, 1)
    st = _send(io, t, A, mg.MSG_CHESS_MOVE, 1, pc.sq(7, 1))
    assert st["phase"] == 6 and st["plrstt"] == 0x04               # seat 0 wins
    assert t.credits[A] == 450 + 100 and t.credits[B] == 450
    # Rematch: phase 6 clears the clients' pending flag; both must press NewGame (403).
    _send(io, t, A, mg.MSG_CHESS_NEWGAME, 0)
    assert io.state()["phase"] == 6
    st = _send(io, t, B, mg.MSG_CHESS_NEWGAME, 1)
    assert st["phase"] == 2 and t.credits[A] == 500 and t.credits[B] == 400
    print("auto start, king placement, moves, rejected moves still unlock, edge win, rematch OK")


def test_capture_conversion_and_king_capture():
    io = FakeIo()
    t = _game(io)
    _send(io, t, A, mg.MSG_CHESS_KING, 0)
    _send(io, t, B, mg.MSG_CHESS_KING, 7)
    t.chess[2].square = pc.sq(3, 3)                                # side-0 pawn
    t.chess[10].square = pc.sq(4, 4)                               # side-1 pawn diagonally ahead
    spots = pc.relocation_squares(t.chess, 4, 0)
    st = _send(io, t, A, mg.MSG_CHESS_CAPTURE, 2, pc.sq(4, 4), 10, spots[0])
    assert st["phase"] == 5 and st["pieces"][10] >> 7 == 0 and st["pieces"][10] & 0x3F == spots[0]
    st = _send(io, t, B, mg.MSG_CHESS_CAPTURE, 9, pc.sq(6, 0), 1, 0)   # nonsense capture: rejected
    assert st["phase"] == 5
    # Side 1 takes the side-0 king with its king.
    t.chess[15].square = pc.sq(1, 1)
    st = _send(io, t, B, mg.MSG_CHESS_MOVE, 15, pc.sq(0, 0))
    assert st["phase"] == 6 and st["plrstt"] == 0x40
    print("capture converts and relocates, king capture wins, bogus 401 rejected OK")


def test_leave_forfeits():
    io = FakeIo()
    t = _game(io)
    mg.handle_leave(io, None, A, _key(t).bytes())
    assert t.phase == 6 and t.plrstt == 0x40 and t.credits[B] == 450 + 100
    print("leaving mid-game forfeits the stakes OK")


if __name__ == "__main__":
    test_rules()
    test_check_mark_and_mate()
    test_game_flow_and_edge_win()
    test_capture_conversion_and_king_capture()
    test_leave_forfeits()
    print("\nAll pawnchess tests PASSED")
