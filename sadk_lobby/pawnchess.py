"""
PawnChess rules for village minigame tables, as the client implements them (docs/message-catalog.md,
village: Minigames, PawnChess). Pure functions; the table flow lives in minigames.py.

Board [known] (MiniGamePawnChessProxy::ReadTableState S 0048a6d0): 8x8, square = col + row * 8.
16 pieces, ALWAYS all on the board (there is no "captured" state). Piece byte `pwnps` =
col | row << 3 | king << 6 | side << 7.

Rules (maintainer's description, matched to the client's own move generator
CMiniGameControllerPawnChess_Actor::ComputeTargets S 00525d20):
  * Each side has 7 pawns and a king. Side 0 starts in column 0, side 1 in column 7, filling it; at the
    start each player turns one piece of its home column into the king (PlaceKing, a row).
  * Pawns move along the columns: side 0 towards column 7, side 1 towards column 0. A pawn steps one
    square forward onto an EMPTY square, or diagonally forward (row +-1) onto an enemy piece.
  * The king steps to any of the 8 neighbours not holding an own piece — attacked squares included
    (the client only tints them).
  * Taking an enemy PAWN converts it: it becomes the captor's and the captor puts it on an empty square
    of the column it was taken in; if that column is full, the nearest column towards the captor's home.
  * Moving onto the enemy KING wins. A pawn reaching the enemy home column wins. Checkmate wins.
  * Check [known]: while a side is in check (plrstt bit 0 of its nibble) the client lets it move only
    the king and the ONE pawn the server marks (pwchkmt), whose only target is the checking piece.
"""

SIDE_HOME = (0, 7)
SIDE_DIR = (1, -1)
KING_STEPS = [(dc, dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if dc or dr]


def sq(col, row):
    return col + row * 8


def col_row(square):
    return square % 8, square // 8


def on_board(col, row):
    return 0 <= col < 8 and 0 <= row < 8


class Piece:
    __slots__ = ("square", "king", "side")

    def __init__(self, square, side, king=False):
        self.square, self.side, self.king = square, side, king

    def byte(self):
        return self.square | (0x40 if self.king else 0) | (self.side << 7)


def initial_board():
    """Pieces 0-7 side 0 in column 0, 8-15 side 1 in column 7, all pawns until the kings are placed."""
    return [Piece(sq(0, r), 0) for r in range(8)] + [Piece(sq(7, r), 1) for r in range(8)]


def at(board, square):
    return next((i for i, p in enumerate(board) if p.square == square), None)


def attacked_by(board, side):
    """Squares the pieces of `side` attack (the client's attack pass in S 0048a6d0)."""
    out = set()
    for p in board:
        if p.side != side:
            continue
        c, r = col_row(p.square)
        steps = KING_STEPS if p.king else [(SIDE_DIR[side], -1), (SIDE_DIR[side], 1)]
        for dc, dr in steps:
            if on_board(c + dc, r + dr):
                out.add(sq(c + dc, r + dr))
    return out


def king_of(board, side):
    return next((i for i, p in enumerate(board) if p.side == side and p.king), None)


def checkers(board, side):
    """Enemy pieces attacking `side`'s king."""
    k = king_of(board, side)
    if k is None:
        return []
    kc, kr = col_row(board[k].square)
    out = []
    for i, p in enumerate(board):
        if p.side == side:
            continue
        c, r = col_row(p.square)
        steps = KING_STEPS if p.king else [(SIDE_DIR[p.side], -1), (SIDE_DIR[p.side], 1)]
        if any((c + dc, r + dr) == (kc, kr) for dc, dr in steps):
            out.append(i)
    return out


def check_mark(board, side):
    """(in_check, marked pawn index or None, pwchkmt byte). The client marks one pawn with the square it
    must capture on: pwchkmt = piece | 0x10 when that square is row - 1 (PawnChess_GetMarkedCaptureSquare
    S 0048a510). Only a single checker can be taken by a pawn."""
    chk = checkers(board, side)
    if not chk:
        return False, None, 0xFF
    if len(chk) == 1:
        target = board[chk[0]].square
        tc, tr = col_row(target)
        for i, p in enumerate(board):
            if p.side != side or p.king:
                continue
            c, r = col_row(p.square)
            if c + SIDE_DIR[side] == tc and abs(r - tr) == 1:
                return True, i, i | (0x10 if tr == r - 1 else 0)
    return True, None, 0xFF


def targets(board, piece, marked=None):
    """Legal target squares for one piece (ComputeTargets S 00525d20)."""
    p = board[piece]
    c, r = col_row(p.square)
    out = []
    if p.king:
        for dc, dr in KING_STEPS:
            if on_board(c + dc, r + dr):
                o = at(board, sq(c + dc, r + dr))
                if o is None or board[o].side != p.side:
                    out.append(sq(c + dc, r + dr))
        return out
    fc = c + SIDE_DIR[p.side]
    if marked == piece:                                  # in check: the marked capture only
        enemy_k = [board[i].square for i in checkers(board, p.side)]
        return [s for s in enemy_k if col_row(s)[0] == fc and abs(col_row(s)[1] - r) == 1]
    if on_board(fc, r) and at(board, sq(fc, r)) is None:
        out.append(sq(fc, r))
    for dr in (-1, 1):
        if on_board(fc, r + dr):
            o = at(board, sq(fc, r + dr))
            if o is not None and board[o].side != p.side:
                out.append(sq(fc, r + dr))
    return out


def movable(board, side):
    """Pieces `side` may pick up (RefreshMovablePieces S 00525c00): all its pieces, or in check only the
    king and the marked pawn."""
    in_check, marked, _ = check_mark(board, side)
    own = [i for i, p in enumerate(board) if p.side == side]
    if in_check:
        own = [i for i in own if board[i].king or i == marked]
    return own, marked


def relocation_squares(board, captured_col, side):
    """Where a pawn taken in `captured_col` by `side` may be put: the empty squares of that column,
    else of the nearest column towards the captor's home (ComputeTargets relocation mode)."""
    col = captured_col
    step = -SIDE_DIR[side]
    while 0 <= col < 8:
        free = [sq(col, r) for r in range(8) if at(board, sq(col, r)) is None]
        if free:
            return free
        col += step
    return []


def legal_moves(board, side):
    """[(piece, target)] the client would offer `side` (captures of pawns need a relocation square too)."""
    pieces, marked = movable(board, side)
    return [(i, t) for i in pieces for t in targets(board, i, marked)]


def apply(board, piece, target, relocate=None):
    """Play a move. Returns the event: 'king' (the enemy king was taken), 'edge' (a pawn reached the enemy
    home column), or None. A captured pawn is converted and put on `relocate`."""
    p = board[piece]
    victim = at(board, target)
    if victim is not None:
        v = board[victim]
        if v.king:
            p.square = target
            v.square = None                               # the caller ends the game before sending
            return "king"
        v.side = p.side
        v.square = relocate
    p.square = target
    if not p.king and col_row(target)[0] == SIDE_HOME[1 - p.side]:
        return "edge"
    return None


def copy(board):
    return [Piece(p.square, p.side, p.king) for p in board]


def is_mated(board, side):
    """`side` is in check and no move it is allowed (king or marked pawn) leaves its king unattacked
    and none takes the enemy king."""
    if not checkers(board, side):
        return False
    for piece, target in legal_moves(board, side):
        b = copy(board)
        victim = at(b, target)
        if victim is not None and b[victim].king:
            return False
        reloc = None
        if victim is not None:
            spots = relocation_squares(b, col_row(target)[0], side)
            reloc = spots[0] if spots else None
        apply(b, piece, target, reloc)
        if not checkers(b, side):
            return False
    return True
