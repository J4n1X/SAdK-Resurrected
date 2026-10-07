"""
Village minigame tables (docs/message-catalog.md, village: Minigames).

Table lifecycle for all three games (1 Dice, 2 Poker, 3 PawnChess) and the Dice game. Poker and
PawnChess are refused (0xDB) until their game-state blocks are implemented (see PLAYABLE).

Client → server (inside SendGameData 74; wire type = category << 12 | id):
  0x27D1 2001 CreateMiniGameTable  type 8, plyMny 8, stck 32, gmnm str, lmtmn 32, lmtmx 32, mxplyr 8,
                                   tvrn 8, tblidx 8, psswd 8, psswdcrc 32
  0x50D1 209  JoinTable            msgprt 16, rnid 8, stck 32, psswdcrc 32
  0x50CC 204  LeaveTable           msgprt 16, rnid 8
  0x50DE 222  Amount               msgprt 16, rnid 8, amnt 32
  0x50DC 220  Dice PlaceBets       msgprt 16, rnid 8, crdts packed, bt00..bt10 packed
  0x50DD 221  Dice Roll            msgprt 16, rnid 8
Server → client (category 0 ids):
  0xDA 218 TableCreate · 0xD9 217 TableUpdate · 0xD8 216 TableRemove (key only)
  0xDB 219 NoTableLeft · 0xDC 220 NoPlayerSlotLeft (empty bodies)

What the client requires [known, all from the client code]:
  * 0xDA carries key + settings only; seats and state come in the 0xD9 right after (create_body).
  * The creator is seated by the server: the stake dialog sends 2001 OR JoinTable, never both
    (MiniGameMatchMakingDialog::OnSetStackResult S 00442f00).
  * mngt bit5 = currency: 1 play money (glod, avatar+0xd4), 0 credits (gold, avatar+0xd0)
    (MiniGameKey_GetCurrencyFlag S 004712b0; the dialog compares them with the table's lmtmn).
  * Seated avatars must exist with a 3D object in the receiving client, or it drops the seat block.
  * Dice has 4 seat anchors (MiniGameDiceProxy ctor S 00488b50: {0,2,3,1}); seats 0..3 only.

Dice round, as the client plays it (UpdatePhaseDisplay S 004471d0, CMiniGameControllerDice_Actor::Update
S 00524c10, CMiniGameControllerDice_Board::Update S 00523c10):
  1 betting  — 15 s countdown from the phase's elapsed time; each chip change sends PlaceBets.
  2 roll     — the `dlr` seat (IsLocalSeatActive S 00488a00) shakes the cup; its click sends Roll.
  3 throw    — dice drawn after 500 ms; the client computes every seat's payout on entering 3
               (ComputeAllPayouts S 00488d60, rule = payout() below).
  4 result   — "X credits/funnies won/lost" and the board's round-result animation.
  `crdts` is the seat's whole stack INCLUDING its bets: the client shows stack - bets and accepts a chip
  only while bets + chip <= stack (UpdateBetting S 00523db0). During phase 1 the client ignores the bet
  echo for its own seat.

Server decisions, marked where the client gives no hint:
  * msgprt from 1 upwards, rnid 0 (V34). The table goes into the dialog's tavern (tvrn + 2) on the
    clicked spot if free, else the first free spot (V33); refused with 0xDB when none is free.
  * Each table gets its own chat cell (chtid, V35), published on every UC connection.
  * Joining moves `stck` from the table's currency into the stack (clamped to the balance, V38); Amount
    moves more (V39); leaving returns the stack. A table is removed when its last player leaves (V37).
  * The roller rotates over the occupied seats each round [decision]. ROLL_TIMEOUT_SECS, THROW_SECS and
    RESULT_SECS are [decisions]: the client has no timer for phases 2-4.
  * Settlement (stack - bets + payout) is booked when the next round starts, so the stack the client
    shows during phases 3-4 still matches the chips on the table.
"""
import random
import threading
import time

from . import economy, pawnchess, poker
from .log import log
from .village import BitReader, BitWriter

DICE, POKER, PAWNCHESS = 1, 2, 3
MSG_REMOVE, MSG_UPDATE, MSG_CREATE = 0xD8, 0xD9, 0xDA
MSG_NO_TABLE, MSG_NO_SEAT = 0xDB, 0xDC
PLAYABLE = (DICE, POKER, PAWNCHESS)
#: Table spots (2026-10-07). A table's key byte `scntbl` is {low nibble = GROUP, high nibble = TABLE}
#: and the client places the table at NodeTagTable[group][table][slot 'c'] (Generic_Grid2D_ApplyTransformAt
#: S 004fbd90 — no NULL check, so an empty cell crashes). The cells are filled from model nodes named
#: "slot:NN_c" (CGfxObjStd::ParseNodeHierarchyTags S 00518e50); group = the object's scene id. Both
#: tavern interiors carry slot:00..14 (taverne02.kex = scene 3, taverne03.kex = scene 2): tables 0-12
#: have 4 seats, 13-14 have 8. Creating with group 0 / table 0 (outdoors) crashed the client twice.
#: The client's own tavern id is group - 2: the matchmaking dialog lists a table only when
#: scntblLo - 2 == its tavernId (S 00445cf0), and 2001 carries that tavernId as `tvrn` and the clicked
#: table spot (scntblHi, 0xFF when opened from an NPC) as `tblidx` (S 00442f00, S 00433f60). [known]
TAVERN_ZONES = (2, 3)
SMALL_TABLES = tuple(range(13))          # 4 seats
BIG_TABLES = (13, 14)                    # 8 seats (the dialog offers 5-8 players only there)
MAX_SEATS = 8
DICE_SEATS = 4
PAWNCHESS_SEATS = 2              # seats 0/1 are the two sides (IsPrimarySeat S 004715f0) [decision: no spectators]
FIRST_TABLE_CELL = 1000          # chat cells for tables: 1000, 1001, ... (must not collide with lobby/zone cells)
MNGT_PLAY_MONEY = 0x20
PHASE_BETTING, PHASE_ROLL, PHASE_THROW, PHASE_RESULT = 1, 2, 3, 4
BET_SECS = 15.0                  # the client's own countdown (15000 ms - elapsed, S 004471d0) [known]
ROLL_TIMEOUT_SECS = 20.0         # the roller does not roll: the server rolls for it [decision]
THROW_SECS = 4.0                 # [decision]
RESULT_SECS = 4.0                # [decision]
LIMIT_MAX = 0x7FFFFFFF

_lock = threading.RLock()
_tables = {}                     # (msgprt, rnid) -> Table
_next_msgprt = 1


class Table:
    def __init__(self, kind, name, tavern, index, password, crc, lmtmn, lmtmx, mxplyr, chtid, key,
                 play_money=False):
        self.kind, self.name = kind, name
        self.tavern, self.index = tavern, index
        self.password, self.crc = password, crc
        self.lmtmn, self.lmtmx = lmtmn, lmtmx
        cap = DICE_SEATS if kind == DICE else PAWNCHESS_SEATS if kind == PAWNCHESS else MAX_SEATS
        self.mxplyr = max(1, min(mxplyr or cap, cap))
        self.chtid, self.key = chtid, key
        self.play_money = bool(play_money)
        self.seats = {}          # sltidx -> perm_id
        self.credits = {}        # perm_id -> stack (bets included)
        self.bets = {}           # perm_id -> [11]
        self.dice = 0
        self.dealer = 0          # the roller's seat; always a real seat index (see table_body)
        self.last_roller = None  # seat that rolled last round (rotation)
        self.phase = PHASE_BETTING
        self.phase_start = time.monotonic()
        self.round = 0           # bumped on every phase change; stale timers check it
        # Poker
        self.hand = None         # PokerHand while a hand runs
        self.button = None       # dealer-button seat of the last hand
        self.sitting_out = set()  # perms that asked to sit out (302 enbl=1)
        # PawnChess
        self.chess = None        # pawnchess board (list of Piece) of the current / last game
        self.trnid = 0           # bumped on EVERY answer to 400-402 (the client's input latch)
        self.plrstt = 0
        self.pwchkmt = 0xFF
        self.ready = set()       # perms that pressed NewGame (403) since the last game
        self.stake_in = {}       # perm -> stake put in for the running game

    def seat_of(self, perm_id):
        return next((s for s, p in self.seats.items() if p == perm_id), None)


def reset_for_tests():
    global _next_msgprt
    with _lock:
        _tables.clear()
        _next_msgprt = 1


# ── Accounts ──────────────────────────────────────────────────────────────────
def _balance(t, perm_id):
    w = economy.wallet(perm_id)
    return w.glod if t.play_money else w.gold


def _book(t, perm_id, delta):
    """Move `delta` into (+) or out of (-) the player's account in the table's currency."""
    w = economy.wallet(perm_id)
    if t.play_money:
        w.glod += delta
    else:
        w.gold += delta


# ── Encoding ──────────────────────────────────────────────────────────────────
def write_packed(w, value):
    """Packed uint (LobbyMessage::ReadNamedPackedUInt S 0048fcb0): one presence bit; if set, a 3-bit
    count n and then (n + 1) * 4 bits of value, MSB first. 0 is a single 0 bit."""
    value = int(value) & 0xFFFFFFFF
    if value == 0:
        return w.write(0, 1)
    nibbles = max(1, (value.bit_length() + 3) // 4)
    return w.write(1, 1).write(nibbles - 1, 3).write(value, nibbles * 4)


def read_packed(r):
    if not r.read(1):
        return 0
    n = r.read(3) + 1
    return r.read(n * 4)


def _key(w, t, settings, seats, state):
    mngt = t.kind | (0x10 if settings else 0) | (MNGT_PLAY_MONEY if t.play_money else 0) \
        | (0x40 if seats else 0) | (0x80 if state else 0)
    w.write(mngt, 8)
    w.write((t.index & 0xF) << 4 | (t.tavern & 0xF), 8)           # scntbl: hi = table, lo = group (scene id)
    write_packed(w, t.chtid)
    w.write(t.key[0], 16).write(t.key[1], 8)


def create_body(t):
    """0xDA body: key and settings only. A seat block here crashes the client: ReadSeats announces
    the seats (AnnounceSeats S 00471eb0), and the seat-joined observer (S 00503710) calls into the
    table's 3D object at proxy+0x20 — which only the first 0xD9 creates (HandleMiniGameTableUpdate
    S 0046f380 notifies +0x68 before reading the state). Crash dump 2026-10-07: NULL read at
    S 00503717 under HandleMiniGameTableCreate -> Dice ReadTableState -> ReadSeats -> AnnounceSeats.
    Seats and game state therefore go in the 0xD9 that follows."""
    return table_body(t, seats=False, state=False)


def table_body(t, settings=True, seats=True, state=True):
    """0xD9 body: key, then the blocks the mngt flags announce (settings, seats, game state).
    Game state is only written for Dice."""
    state = state and t.kind in (DICE, POKER, PAWNCHESS)
    w = BitWriter()
    _key(w, t, settings, seats, state)
    if settings:
        w.write(1 if t.password else 0, 8).write(t.crc, 32).write_string(t.name)
        write_packed(w, t.lmtmn)
        write_packed(w, t.lmtmx)
        w.write(t.mxplyr, 4)
    if seats:
        occupied = sorted(t.seats.items())[:MAX_SEATS]
        w.write(len(occupied), 4)
        for sltidx, perm in occupied:
            w.write(1, 1).write(sltidx, 4)                        # used = 1, seat index
            w.write(1, 2)                                         # acttype 1 = avatar
            write_packed(w, perm)                                 # id = the avatar id = perm_id
    if state and t.kind == POKER:
        _poker_state(w, t)
    elif state and t.kind == PAWNCHESS:
        _chess_state(w, t)
    elif state:
        elapsed = _elapsed(t)
        # dlr MUST be a real seat (0..3): the client draws the dice cup at the dealer seat's node, read
        # unchecked from a 4-entry table (CGfxObjMiniGameDice_Board::DrawRenderItem S 00517264). 0xFF
        # ("none") read past it, got NULL and crashed the client in Generic_Copy16Dwords (crash dump
        # 2026-10-07: EIP 0049fd46, ECX 0, caller 0051727b).
        w.write(t.dice, 8).write(t.dealer, 8)                     # dice (two nibbles), roller seat
        w.write(len(t.seats), 8).write(t.phase, 8).write(elapsed, 16)
        for sltidx, perm in sorted(t.seats.items()):
            w.write(sltidx, 8)
            write_packed(w, t.credits.get(perm, 0))               # the stack, bets included
            write_packed(w, _balance(t, perm))                    # accnt = account balance [inferred]
            for b in t.bets.get(perm, [0] * 11):
                write_packed(w, b)
    return w.bytes()


def _elapsed(t):
    """`time` on the wire: HUNDREDTHS of a second since the phase (Poker: the turn) started —
    SetPhaseStartFromElapsed S 00471540 sets phaseStart = now_ms - time * 10. [known]"""
    return min(int((time.monotonic() - t.phase_start) * 100), 0xFFFF)


def key_body(t):
    w = BitWriter()
    _key(w, t, False, False, False)
    return w.bytes()


def payout(bets, dice_sum):
    """The client's own settlement (ComputeSeatPayout S 00488870). bets[k] is the bet on sum k + 2.
    Returns what comes back to the stack: every bet in the rolled sum's group returns 1x, the bet on
    the exact sum 5x; a 7 returns 3x the bet on 7 only."""
    group_a, group_b = (2, 4, 6, 9, 11), (3, 5, 8, 10, 12)
    if dice_sum == 7:
        return bets[5] * 3
    for group in (group_a, group_b):
        if dice_sum in group:
            return sum(bets[s - 2] * (5 if s == dice_sum else 1) for s in group)
    return 0


# ── Handlers. `send(conn, msg, body)` sends one village message; `everyone()` lists the in-world
#    village conns; `publish_cell(chtid, name)` puts a chat cell on every UC connection;
#    `stats(perm_id)` sends the owner its StatsUpdate (3201); `schedule(delay, fn)` runs fn later. ──
def _timer(delay, fn):
    threading.Timer(delay, fn).start()


class Io:
    def __init__(self, send, everyone, publish_cell, zone_of=lambda perm_id: None,
                 stats=lambda perm_id: None, schedule=_timer, send_to=lambda perm_id, msg, body: None):
        self.send, self.everyone, self.publish_cell = send, everyone, publish_cell
        self.send_to = send_to                    # one player's village connection (Poker hole cards)
        self.zone_of = zone_of                    # perm_id -> the player's current location zone
        self.stats, self.schedule = stats, schedule

    def broadcast(self, msg, body):
        for c in self.everyone():
            try:
                self.send(c, msg, body)
            except Exception as exc:  # noqa: BLE001
                log(f"  [MINIGAME] send to conn #{getattr(c, 'id', '?')} failed: {exc}")


def _update(io, t, settings=False):
    io.broadcast(MSG_UPDATE, table_body(t, settings=settings))


def handle_create(io, conn, perm_id, data):
    global _next_msgprt
    r = BitReader(data)
    kind, play_money, stake = r.read(8), r.read(8), r.read(32)
    name = bytes(r.read(8) for _ in range(r.read(8))).decode("utf-8", "replace")
    lmtmn, lmtmx, mxplyr = r.read(32), r.read(32), r.read(8)
    tvrn, tblidx, psswd, crc = r.read(8), r.read(8), r.read(8), r.read(32)
    with _lock:
        # tvrn is the dialog's tavernId (scene - 2, see TAVERN_ZONES); without one the table goes into
        # the tavern the creator stands in (its zone = the scene id = the group).
        zone = tvrn + 2 if tvrn + 2 in TAVERN_ZONES else io.zone_of(perm_id)
        pool = BIG_TABLES if mxplyr > 4 else SMALL_TABLES
        used = {t.index for t in _tables.values() if t.tavern == zone}
        free = [i for i in pool if i not in used]
        if tblidx in free:                       # created at a clicked table spot: that spot first
            free.insert(0, tblidx)
        if kind not in PLAYABLE or zone not in TAVERN_ZONES or not free:
            io.send(conn, MSG_NO_TABLE, b"")
            log(f"  [MINIGAME] create type={kind} in zone {zone}: refused (0xDB) — "
                f"{'not playable yet' if kind not in PLAYABLE else 'not inside a tavern' if zone not in TAVERN_ZONES else 'no free table'}")
            return
        tavern, index = zone, free[0]
        key = (_next_msgprt & 0xFFFF, 0)
        _next_msgprt += 1
        t = Table(kind, name, tavern, index, psswd, crc, lmtmn, min(lmtmx, LIMIT_MAX), mxplyr,
                  FIRST_TABLE_CELL + key[0], key, play_money=play_money)
        _tables[key] = t
        # The creator sits down at once with the stake from the same dialog JoinTable uses.
        _seat(t, perm_id, stake)
    io.publish_cell(t.chtid, name or f"Tisch {key[0]}")
    io.broadcast(MSG_CREATE, create_body(t))
    io.broadcast(MSG_UPDATE, table_body(t))
    io.stats(perm_id)
    log(f"  [MINIGAME] table {key} created: type={kind} {name!r} tavern={tavern}/{index} "
        f"max={t.mxplyr} {'play money' if t.play_money else 'credits'} cell={t.chtid}; "
        f"creator {perm_id} seated with {t.credits[perm_id]}")
    if kind == DICE:
        _start_betting(io, t)
    elif kind == POKER:
        _poker_idle(io, t)
    elif kind == PAWNCHESS:
        with _lock:
            t.chess = pawnchess.initial_board()
            _enter(t, 1)


def sync_tables(io, conn):
    """Show a player who just entered the world every table that already exists (0xDA, then 0xD9 —
    the first 0xD9 is what builds the 3D table). Tables are otherwise only announced when created."""
    with _lock:
        tables = list(_tables.values())
    for t in tables:
        io.publish_cell(t.chtid, t.name or f"Tisch {t.key[0]}")
        io.send(conn, MSG_CREATE, create_body(t))
        io.send(conn, MSG_UPDATE, table_body(t))
    if tables:
        log(f"  [MINIGAME] sent {len(tables)} existing table(s) to conn #{getattr(conn, 'id', '?')}")


def _seat(t, perm_id, stake):
    """Put a player on the first free seat and move `stake` from the table's currency into the stack
    (clamped to the balance, V38). Returns False when the table is full."""
    if t.seat_of(perm_id) is not None:
        return True
    free = [s for s in range(t.mxplyr) if s not in t.seats]
    if not free:
        return False
    t.seats[free[0]] = perm_id
    moved = max(0, min(stake, _balance(t, perm_id)))
    _book(t, perm_id, -moved)
    t.credits[perm_id] = moved
    t.bets[perm_id] = [0] * 11
    if t.kind == PAWNCHESS:
        t.ready.add(perm_id)                     # its client's new-game request starts pending
    return True


def _table(r):
    return _tables.get((r.read(16), r.read(8)))


def handle_join(io, conn, perm_id, data):
    r = BitReader(data)
    with _lock:
        t = _table(r)
        stake, crc = r.read(32), r.read(32)
        if t is None or (t.password and crc != t.crc) or not _seat(t, perm_id, stake):
            io.send(conn, MSG_NO_SEAT, b"")
            log(f"  [MINIGAME] join by {perm_id}: refused (0xDC)")
            return
    _update(io, t)
    io.stats(perm_id)
    log(f"  [MINIGAME] {perm_id} joined table {t.key} seat {t.seat_of(perm_id)} "
        f"with {t.credits.get(perm_id)}")
    if t.kind == POKER and t.hand is None:
        _poker_idle(io, t)
    if t.kind == PAWNCHESS:
        _chess_try_start(io, t)


def leave(io, perm_id, t):
    """Unseat a player and return the stack. Bets placed in a round that has been thrown (phase 3/4)
    are settled first; before the throw they are simply part of the stack again [decision]."""
    with _lock:
        s = t.seat_of(perm_id)
        if s is None:
            return
        if t.kind == POKER:
            _poker_drop(io, t, perm_id)
            t.sitting_out.discard(perm_id)
        if t.kind == PAWNCHESS:
            _chess_forfeit(io, t, perm_id)
        stack = t.credits.pop(perm_id, 0)
        bets = t.bets.pop(perm_id, [0] * 11)
        if t.kind == DICE and t.phase in (PHASE_THROW, PHASE_RESULT):
            stack += payout(bets, (t.dice >> 4) + (t.dice & 0xF)) - sum(bets)
        del t.seats[s]
        _book(t, perm_id, max(0, stack))
        empty = not t.seats
        if empty:
            _tables.pop(t.key, None)
            t.round += 1                                          # cancels pending phase timers
        elif t.kind == DICE and t.dealer == s:
            t.dealer = min(t.seats)
            if t.phase == PHASE_ROLL:                             # the roller left: next one rolls
                _enter(t, PHASE_ROLL)
                io.schedule(ROLL_TIMEOUT_SECS, _guard(t, lambda: _roll(io, t, None)))
    io.stats(perm_id)
    if empty:
        io.broadcast(MSG_REMOVE, key_body(t))
        log(f"  [MINIGAME] table {t.key} removed (last player left)")
    else:
        _update(io, t)
        log(f"  [MINIGAME] {perm_id} left table {t.key}")


def handle_leave(io, conn, perm_id, data):
    t = _table(BitReader(data))
    if t is not None:
        leave(io, perm_id, t)


def leave_all(io, perm_id):
    """A player's village connection went away: leave every table."""
    for t in [t for t in list(_tables.values()) if t.seat_of(perm_id) is not None]:
        leave(io, perm_id, t)


def handle_amount(io, conn, perm_id, data):
    r = BitReader(data)
    t = _table(r)
    amount = r.read(32)
    if t is None or t.seat_of(perm_id) is None:
        return
    with _lock:
        moved = max(0, min(amount, _balance(t, perm_id)))
        _book(t, perm_id, -moved)
        t.credits[perm_id] = t.credits.get(perm_id, 0) + moved
    _update(io, t)
    io.stats(perm_id)
    log(f"  [MINIGAME] {perm_id} topped up {moved} at table {t.key}")
    if t.kind == POKER and t.hand is None:
        _poker_idle(io, t)
    if t.kind == PAWNCHESS:
        _chess_try_start(io, t)


# ── Dice round ────────────────────────────────────────────────────────────────
def _enter(t, phase):
    t.phase, t.phase_start = phase, time.monotonic()
    t.round += 1


def _guard(t, fn):
    """Run fn only if the table still exists and no phase change happened since scheduling."""
    expected = t.round + 0

    def run():
        with _lock:
            if t.key not in _tables or t.round != expected:
                return
        fn()
    return run


def _start_betting(io, t):
    with _lock:
        _enter(t, PHASE_BETTING)
    _update(io, t)
    io.schedule(BET_SECS, _guard(t, lambda: _start_roll(io, t)))


def _start_roll(io, t):
    with _lock:
        seats = sorted(t.seats)
        if not seats:
            return
        later = [s for s in seats if t.last_roller is not None and s > t.last_roller]
        t.dealer = t.last_roller = (later or seats)[0]            # rotate the roller every round
        _enter(t, PHASE_ROLL)
    _update(io, t)
    log(f"  [MINIGAME] table {t.key}: seat {t.dealer} ({t.seats[t.dealer]}) rolls")
    io.schedule(ROLL_TIMEOUT_SECS, _guard(t, lambda: _roll(io, t, None)))


def _roll(io, t, perm_id):
    with _lock:
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        t.dice = d1 << 4 | d2
        _enter(t, PHASE_THROW)
    _update(io, t)
    log(f"  [MINIGAME] table {t.key} rolled {d1}+{d2}={d1 + d2}"
        f"{'' if perm_id else ' (roll timeout: rolled by the server)'}")
    io.schedule(THROW_SECS, _guard(t, lambda: _show_result(io, t)))


def _show_result(io, t):
    with _lock:
        _enter(t, PHASE_RESULT)
    _update(io, t)
    io.schedule(RESULT_SECS, _guard(t, lambda: _next_round(io, t)))


def _next_round(io, t):
    """Book the round (stack - bets + payout, the client's own rule) and open the next betting phase."""
    total = (t.dice >> 4) + (t.dice & 0xF)
    with _lock:
        for perm in list(t.seats.values()):
            bets = t.bets.get(perm, [0] * 11)
            t.credits[perm] = t.credits.get(perm, 0) - sum(bets) + payout(bets, total)
            t.bets[perm] = [0] * 11
    _start_betting(io, t)


def handle_place_bets(io, conn, perm_id, data):
    r = BitReader(data)
    t = _table(r)
    credits = read_packed(r)
    bets = [read_packed(r) for _ in range(11)]
    if t is None or t.kind != DICE or t.seat_of(perm_id) is None or t.phase != PHASE_BETTING:
        return
    with _lock:
        stack = t.credits.get(perm_id, 0)
        if sum(bets) > stack:                                      # the client checks the same
            log(f"  [MINIGAME] {perm_id} bets {sum(bets)} > stack {stack}: ignored")
            return
        t.bets[perm_id] = bets
        if credits != stack:
            log(f"  [MINIGAME] {perm_id} reported stack {credits}, server has {stack}")
    _update(io, t)


def handle_roll(io, conn, perm_id, data):
    """Roll (221): only the roller, only in phase 2. The client may send it on several frames while the
    button is held (UpdateLocalShaking S 00524420 has no latch); the phase check drops the repeats."""
    t = _table(BitReader(data))
    with _lock:
        if t is None or t.kind != DICE or t.phase != PHASE_ROLL or t.seats.get(t.dealer) != perm_id:
            return
    _roll(io, t, perm_id)


MSG_POKER_ACTION, MSG_POKER_WAGER, MSG_POKER_SITOUT = 0x512C, 0x512D, 0x512E
MSG_HAND = 0x12F                 # 303 MiniGameHand, S->C, to the owner only


def handle_game_action(io, conn, perm_id, msg_type, data):
    """Poker 300-302; PawnChess 400-403 (game logic not implemented — logged)."""
    r = BitReader(data)
    t = _table(r)
    if t is not None and t.kind == POKER and msg_type in (MSG_POKER_ACTION, MSG_POKER_WAGER):
        code = r.read(16)
        wgr = read_packed(r) if msg_type == MSG_POKER_WAGER else None
        _poker_act(io, t, perm_id, code, wgr)
    elif t is not None and t.kind == POKER and msg_type == MSG_POKER_SITOUT:
        _poker_sit_out(io, t, perm_id, bool(r.read(8)))
    elif t is not None and t.kind == PAWNCHESS and msg_type in _CHESS_MSGS:
        _CHESS_MSGS[msg_type](io, t, perm_id, r)
    else:
        log(f"  [MINIGAME] action 0x{msg_type:x} from {perm_id} ({data.hex()}) — game logic not implemented")


# ── Poker ─────────────────────────────────────────────────────────────────────
# The client's hand, as it plays it (MinigameDialog_Poker::Update S 0044b3c0, UpdateCards S 00525300,
# CMiniGameControllerPoker_Board::Update S 00525550) [known]:
#   phase 1 waiting · 5 deal (round 1 hole cards, 2 flop, 3 turn, 4 river; egr 1/2 = all-in run-out from
#   the flop / the turn) · 6 betting (current-player marker) · 8 bets collected into the pots (needs
#   ptncnt bit7 with each pot's wagers of this street) · 9 payout: the CLIENT picks every pot's winners
#   as the highest hndval among its plrmsk seats and splits evenly (AnimatePayout S 005250f0).
#   The client never acts on a timeout; the server does (15 s, the client's own countdown).
#   A turn re-opens only when crntplyr, phase or round changes (stateChangeCounter, S 004894a0), so
#   every action must move the turn on — invalid input is coerced, never re-prompted.
POKER_TURN_SECS = 15.0           # the client counts 15 s down (S 0044b3c0) [known]
POKER_DEAL_CARD_SECS = 0.7       # per hole-card pass; the preflop log waits (seats + 1) * 700 ms [known]
POKER_STREET_SECS = 1.5          # flop/turn/river deal animation [decision]
POKER_COLLECT_SECS = 1.5         # [decision]
POKER_POT_SECS = 1.0             # the payout animation takes 1 s per pot [known]
POKER_SHOW_SECS = 3.0            # result shown before the next hand [decision]
POKER_SITOUT_ACT_SECS = 1.0      # a sitting-out player in the hand checks/folds after this [decision]


class PokerHand:
    def __init__(self, players, button):
        self.players = players               # perms dealt in, seat order
        self.button = button
        deck = list(range(52))
        random.shuffle(deck)
        self.deck = deck
        self.hole = {p: [self.deck.pop(), self.deck.pop()] for p in players}
        self.board = []
        self.folded, self.allin = set(), set()
        self.street = {}                     # perm -> chips put in this street
        self.contrib = {}                    # perm -> chips put in on earlier streets
        self.last_code = {}                  # perm -> last action code (actn bits 0-10)
        self.highest = 0
        self.min_raise = 0
        self.big_blind = 0
        self.to_act = []                     # perms still to act this street, in turn order
        self.current = None
        self.round = 1
        self.egr = 0
        self.shwcrds = 0xFF
        self.last = (0xFF, 1, 0)             # lstply, lstactn, lstvl (client initial lstactn = 1)
        self.collect = None                  # phase 8: [(amount, eligible, {perm: wager})]
        self.showdown = False

    def live(self):
        return [p for p in self.players if p not in self.folded]

    def able(self, t):
        return [p for p in self.live() if p not in self.allin and t.credits.get(p, 0) > 0]


def _order(t, perms, after_seat):
    """perms in turn order, starting with the first seat after `after_seat`."""
    start = -1 if after_seat is None else after_seat
    return sorted(perms, key=lambda p: (t.seat_of(p) - start - 1) % MAX_SEATS)


def _blind(t):
    return max(2, t.lmtmn or 2)              # big blind = the table's minimum stake [decision]


def _poker_state(w, t):
    """The Poker game-state block (MiniGamePokerProxy::ReadTableState S 004894a0)."""
    h = t.hand
    seat = t.seat_of
    in_bet = h is not None and t.phase == 6 and h.current is not None
    cur = h.current if in_bet else None
    actns = 0
    if cur is not None:
        stack, wager = t.credits.get(cur, 0), h.street.get(cur, 0)
        actns = poker.buttons(h.highest - wager, stack, wager, h.highest, h.min_raise, h.big_blind)
    w.write(seat(h.button) if h and seat(h.button) is not None else 0xFF, 8)     # dlr (0xFF hides it)
    w.write(len(t.seats), 8)                                                     # plyrcnt
    w.write(seat(cur) if cur is not None else 0xFF, 8)                           # crntplyr
    w.write(actns, 16)
    w.write(t.phase, 8).write(h.round if h else 1, 8)
    w.write(h.egr if h else 0, 8).write(h.shwcrds if h else 0xFF, 8)
    w.write(_elapsed(t), 16)
    w.write((h.highest or h.big_blind) if h else 0, 32)                          # minwgr
    last = h.last if h else (0xFF, 1, 0)
    w.write(last[0], 8)
    write_packed(w, last[2])                                                     # lstvl
    write_packed(w, h.min_raise if h else 0)                                     # mnrs
    w.write(last[1], 16)                                                         # lstactn
    rnd = h.round if h else 1
    board = (h.board if h else []) + [poker.NO_CARD] * 5
    if rnd > 1:
        for c in board[:3]:
            w.write(c, 8)
    if rnd > 2:
        w.write(board[3], 8)
    if rnd > 3:
        w.write(board[4], 8)
    wagers = {seat(p): a for p, a in (h.street.items() if h else ()) if a > 0 and seat(p) is not None}
    w.write(sum(1 << s for s in wagers), 8)                                      # wgrmsk
    for s in sorted(wagers):
        write_packed(w, wagers[s])
    for s, p in sorted(t.seats.items()):
        w.write(s, 8)
        flags = 0
        if p in t.sitting_out:
            flags |= poker.ACTN_SITOUT
        if h is None or p not in h.players:
            flags |= poker.ACTN_OUT_OF_HAND
            w.write(1, 1).write(poker.NO_CARD, 8).write(poker.NO_CARD, 8).write(0, 32)   # no cards
        elif p in h.folded:
            flags |= poker.ACTN_FOLDED
            w.write(1, 1).write(poker.NO_CARD, 8).write(poker.NO_CARD, 8).write(0, 32)
        elif h.showdown:
            c0, c1 = h.hole[p]
            w.write(1, 1).write(c0, 8).write(c1, 8).write(poker.hand_value(h.hole[p] + h.board), 32)
        else:
            w.write(0, 1)        # cards face down for the others; the owner keeps its 303 values
        if h is not None and p in h.allin:
            flags |= poker.ACTN_ALLIN
        w.write(flags | (h.last_code.get(p, 0) & 0x7FF if h else 0), 16)
        write_packed(w, t.credits.get(p, 0))                                     # crdts = stack
        write_packed(w, _balance(t, p))                                          # accnt
    pots = h.collect if (h and t.phase == 8 and h.collect) else _pots(t)
    per_pot_wagers = bool(h and t.phase == 8 and h.collect)
    w.write((0x80 if per_pot_wagers else 0) | len(pots), 8)                     # ptncnt (<= 8)
    for amount, eligible, wg in pots:
        w.write(amount, 32)
        w.write(sum(1 << seat(p) for p in eligible if seat(p) is not None), 8)  # plrmsk
        if per_pot_wagers:
            seats_w = {seat(p): a for p, a in wg.items() if a > 0 and seat(p) is not None}
            w.write(sum(1 << s for s in seats_w), 8)
            for s in sorted(seats_w):
                write_packed(w, seats_w[s])


def _pots(t):
    h = t.hand
    if h is None or not any(h.contrib.values()):
        return []
    live = set(h.live())
    return [(a, e, {}) for a, e in poker.side_pots(h.contrib, live)][:MAX_SEATS]


def _hand_msg(t, perm):
    h = t.hand
    c0, c1 = h.hole[perm]
    w = BitWriter().write(t.key[0], 16).write(t.key[1], 8).write(c0, 8).write(c1, 8)
    return w.write(poker.hand_value(h.hole[perm] + h.board), 32).bytes()


def _send_hands(io, t):
    """Each live player's own cards and current hand value — 303, to the owner only (ReadHand
    S 00489410 writes them into the local seat)."""
    for p in t.hand.live():
        io.send_to(p, MSG_HAND, _hand_msg(t, p))


def _poker_idle(io, t):
    """No hand running: show the waiting state and start one when two players can play."""
    with _lock:
        if t.hand is not None or t.key not in _tables:
            return
        ready = [p for _, p in sorted(t.seats.items())
                 if p not in t.sitting_out and t.credits.get(p, 0) > 0]
        _enter(t, 1)
    _update(io, t)
    if len(ready) >= 2:
        io.schedule(POKER_SITOUT_ACT_SECS, _guard(t, lambda: _poker_start_hand(io, t)))


def _put(t, h, p, amount):
    amount = max(0, min(amount, t.credits.get(p, 0)))
    t.credits[p] -= amount
    h.street[p] = h.street.get(p, 0) + amount
    if t.credits[p] == 0:
        h.allin.add(p)
    return amount


def _poker_start_hand(io, t):
    with _lock:
        ready = [p for _, p in sorted(t.seats.items())
                 if p not in t.sitting_out and t.credits.get(p, 0) > 0]
        if t.hand is not None or len(ready) < 2:
            return
        seats = [t.seat_of(p) for p in ready]
        later = [s for s in seats if t.button is not None and s > t.button]
        t.button = (later or seats)[0]
        button = t.seats[t.button]
        h = t.hand = PokerHand(_order(t, ready, t.button - 1), button)
        bb = h.big_blind = h.min_raise = _blind(t)
        order = _order(t, ready, t.button)            # first seat after the button first
        if len(ready) == 2:                           # heads-up: the button posts the small blind
            sb_p, bb_p = button, order[0] if order[0] != button else order[1]
        else:
            sb_p, bb_p = order[0], order[1]
        _put(t, h, sb_p, bb // 2)
        h.last_code[sb_p] = poker.SMALL_BLIND
        posted = _put(t, h, bb_p, bb)
        h.last_code[bb_p] = poker.BIG_BLIND
        h.highest = max(h.street.values())
        h.last = (t.seat_of(bb_p), poker.BIG_BLIND, posted)
        first = _order(t, ready, t.seat_of(bb_p))
        h.to_act = [p for p in first if p not in h.allin]
        _enter(t, 1)                                  # phase 1 / round 1 clears the last hand's cards
    _update(io, t)
    _send_hands(io, t)
    with _lock:
        _enter(t, 5)
    _update(io, t)
    log(f"  [POKER] table {t.key}: hand dealt to {h.players}, button seat {t.button}, blinds "
        f"{bb // 2}/{bb}; " + ", ".join(f"{p}: {poker.card_text(a)} {poker.card_text(b)}"
                                         for p, (a, b) in h.hole.items()))
    io.schedule(POKER_DEAL_CARD_SECS * (len(h.players) + 1) + 1.0, _guard(t, lambda: _poker_next_turn(io, t)))


def _poker_next_turn(io, t):
    """Give the turn to the next player in to_act, or close the street."""
    with _lock:
        h = t.hand
        if h is None:
            return
        h.to_act = [p for p in h.to_act if p in h.live() and p not in h.allin and t.seat_of(p) is not None]
        if len(h.live()) <= 1 or not h.to_act:
            done = True
        else:
            done = False
            h.current = h.to_act[0]
            _enter(t, 6)
    if done:
        _poker_end_street(io, t)
        return
    _update(io, t)
    p = h.current
    if p in t.sitting_out:
        io.schedule(POKER_SITOUT_ACT_SECS, _guard(t, lambda: _poker_auto(io, t, p)))
    else:
        io.schedule(POKER_TURN_SECS, _guard(t, lambda: _poker_auto(io, t, p)))


def _poker_auto(io, t, p):
    """Timeout or sitting out: check when free, else fold."""
    h = t.hand
    if h is None or h.current != p:
        return
    free = h.street.get(p, 0) >= h.highest
    log(f"  [POKER] table {t.key}: {p} {'checks' if free else 'folds'} (timeout / sitting out)")
    _poker_act(io, t, p, poker.CHECK if free else poker.FOLD, None)


def _poker_act(io, t, perm, code, wgr):
    with _lock:
        h = t.hand
        if h is None or t.phase != 6 or h.current != perm:
            log(f"  [POKER] table {t.key}: action 0x{code:x} from {perm} out of turn — ignored")
            return
        stack, wager = t.credits.get(perm, 0), h.street.get(perm, 0)
        to_call = h.highest - wager
        if code == poker.CHECK and to_call > 0:
            code = poker.CALL                         # stale button: coerce, never re-prompt
        if code in (poker.BET, poker.RAISE):
            low = h.highest + h.min_raise if h.highest else h.big_blind
            target = low if wgr is None or wgr == 0xFFFFFFFF else wgr
            target = max(low, min(target, wager + stack))
        elif code == poker.ALLIN:
            target = wager + stack
        elif code == poker.CALL:
            target = min(h.highest, wager + stack)
        else:
            target = wager
        if code == poker.FOLD:
            h.folded.add(perm)
            value = 0
        else:
            value = _put(t, h, perm, target - wager)
            if code == poker.CALL and perm in h.allin:
                code = poker.ALLIN
        h.last_code[perm] = code
        new_total = h.street.get(perm, 0)
        if new_total > h.highest:                     # a bet or raise re-opens the action
            h.min_raise = max(h.min_raise, new_total - h.highest)
            h.highest = new_total
            h.to_act = [p for p in _order(t, h.live(), t.seat_of(perm))
                        if p != perm and p not in h.allin]
        else:
            h.to_act = [p for p in h.to_act if p != perm]
        h.last = (t.seat_of(perm), code, new_total if code in (poker.BET, poker.RAISE, poker.ALLIN) else value)
        h.current = None
    log(f"  [POKER] table {t.key}: {perm} {_ACTION_NAMES.get(code, hex(code))}"
        f"{' ' + str(h.last[2]) if h.last[2] else ''} (stack {t.credits.get(perm, 0)})")
    _poker_next_turn(io, t)


_ACTION_NAMES = {poker.CALL: "calls", poker.FOLD: "folds", poker.RAISE: "raises to", poker.CHECK: "checks",
                 poker.BET: "bets", poker.ALLIN: "all-in", poker.SMALL_BLIND: "small blind",
                 poker.BIG_BLIND: "big blind"}


def _poker_end_street(io, t):
    """Phase 8: this street's bets go into the pots (with each pot's per-seat wagers for the animation)."""
    with _lock:
        h = t.hand
        live = set(h.live())
        before = dict(h.contrib)
        for p, a in h.street.items():
            h.contrib[p] = h.contrib.get(p, 0) + a
        h.collect = [(amount, eligible, poker.street_wagers(before, h.contrib, lo, hi))
                     for amount, eligible, lo, hi in poker.pot_bands(h.contrib, live)]
        h.collect = h.collect[:MAX_SEATS]
        h.street = {}
        h.highest = 0
        h.min_raise = h.big_blind
        h.current = None
        _enter(t, 8)
    _update(io, t)
    io.schedule(POKER_COLLECT_SECS, _guard(t, lambda: _poker_after_collect(io, t)))


def _poker_after_collect(io, t):
    with _lock:
        h = t.hand
        h.collect = None
        live = h.live()
        if len(live) <= 1:
            step = "fold"
        elif h.round == 4:
            step = "showdown"
        else:
            step = "deal"
            runout = len(h.able(t)) <= 1
            if runout:
                h.egr = {1: 1, 2: 2}.get(h.round, 0)
                h.round = 4
            else:
                h.round += 1
            need = {2: 3, 3: 4, 4: 5}[h.round]
            while len(h.board) < need:
                h.board.append(h.deck.pop())
            h.to_act = [] if runout else _order(t, h.able(t), t.button)
            _enter(t, 5)
    if step == "fold":
        _poker_payout(io, t, by_fold=True)
        return
    if step == "showdown":
        _poker_payout(io, t, by_fold=False)
        return
    _update(io, t)
    _send_hands(io, t)
    log(f"  [POKER] table {t.key}: board " + " ".join(poker.card_text(c) for c in h.board)
        + (f" (all-in run-out, egr {h.egr})" if h.egr else ""))
    nxt = (lambda: _poker_payout(io, t, by_fold=False)) if not h.to_act else (lambda: _poker_next_turn(io, t))
    io.schedule(POKER_STREET_SECS * (2 if h.egr else 1), _guard(t, nxt))


def _poker_payout(io, t, by_fold):
    """Phase 9. The client splits every pot among the highest hndval of its plrmsk seats; the server
    books exactly that (remainder to the first winner after the button)."""
    with _lock:
        h = t.hand
        live = h.live()
        pots = poker.side_pots(h.contrib, set(live)) if not by_fold else \
            [(sum(h.contrib.values()), frozenset(live))]
        if by_fold:
            h.shwcrds = 0xFE                          # no showdown: winners logged without a hand
            h.showdown = False
        else:
            h.showdown = True
            h.shwcrds = t.seat_of(_order(t, live, t.button)[0])
        won = {}
        values = {p: poker.hand_value(h.hole[p] + h.board) for p in live}
        for amount, eligible in reversed(pots):
            contenders = [p for p in _order(t, eligible, t.button) if t.seat_of(p) is not None] or \
                list(eligible)
            best = max(values[p] for p in contenders)
            winners = [p for p in contenders if values[p] == best]
            for p, share in poker.split(amount, winners).items():
                won[p] = won.get(p, 0) + share
        _enter(t, 9)
    _update(io, t)
    for p, amount in won.items():
        if t.seat_of(p) is not None:
            t.credits[p] = t.credits.get(p, 0) + amount
    log(f"  [POKER] table {t.key}: " + ("won by fold — " if by_fold else "showdown — ")
        + ", ".join(f"{p} wins {a}" + ("" if by_fold else f" ({poker.describe(values[p])})")
                    for p, a in won.items()))
    io.schedule(POKER_POT_SECS * max(1, len(pots)) + POKER_SHOW_SECS, _guard(t, lambda: _poker_end_hand(io, t)))


def _poker_end_hand(io, t):
    with _lock:
        t.hand = None
        for p in list(t.seats.values()):
            if t.credits.get(p, 0) <= 0:
                log(f"  [POKER] table {t.key}: {p} has no chips left — waits for a top-up (Amount)")
    _poker_idle(io, t)


def _poker_sit_out(io, t, perm, on):
    """302 enbl: 1 = sit out, 0 = back in (the dialog's toggle starts at 0, S 004483b0) [inferred]."""
    if t.seat_of(perm) is None:
        return
    with _lock:
        (t.sitting_out.add if on else t.sitting_out.discard)(perm)
        h = t.hand
        acting = h is not None and h.current == perm and on
    log(f"  [POKER] table {t.key}: {perm} {'sits out' if on else 'is back'}")
    if acting:
        _poker_auto(io, t, perm)
    else:
        _update(io, t)
        if t.hand is None:
            _poker_idle(io, t)


def _poker_drop(io, t, perm):
    """A player leaves mid-hand: their cards are folded, their chips in the pot stay there."""
    h = t.hand
    if h is None or perm not in h.players:
        return
    h.folded.add(perm)
    h.to_act = [p for p in h.to_act if p != perm]
    if h.current == perm:
        h.current = None
        io.schedule(0.1, _guard(t, lambda: _poker_next_turn(io, t)))
    elif len(h.live()) <= 1 and t.phase == 6:
        io.schedule(0.1, _guard(t, lambda: _poker_next_turn(io, t)))


# ── PawnChess ─────────────────────────────────────────────────────────────────
# The client's side [known] (CMiniGameControllerPawnChess_Actor::Update S 00526260,
# MinigameDialog_PawnChess S 0044caf0 / S 0044cd10, ReadTableState S 0048a6d0):
#   phs 1 waiting · 2 / 3 seat 0 / 1 places its king (8 squares of its home column; sends 402 with the
#   row) · 4 / 5 seat 0 / 1 moves (400 move or take the king, 401 take a pawn + where to put it) ·
#   6 game over: plrstt bit 0x04 (seat 0) / 0x40 (seat 1) = winner; the bets slide to the winner.
#   Every 400-402 locks the board until a state arrives with a different trnid; phases 1 and 6 reset
#   the lock to 0xFF, so trnid is never 0xFF. NewGame (403) hides its button until phase 6: a game
#   starts when both seated players have pressed it. The bets drawn are the table minimum each.
MSG_CHESS_MOVE, MSG_CHESS_CAPTURE, MSG_CHESS_KING, MSG_CHESS_NEWGAME = 0x5190, 0x5191, 0x5192, 0x5193
CHESS_CHECK = (0x01, 0x10)       # plrstt in-check bit per seat (RefreshMovablePieces S 00525c00) [known]
CHESS_WON = (0x04, 0x40)         # plrstt winner bit per seat (S 0048a490) [known]


def _chess_state(w, t):
    w.write(t.phase, 8).write(t.trnid, 8).write(t.pwchkmt, 8).write(t.plrstt, 8)
    for p in t.chess or pawnchess.initial_board():
        w.write(p.byte(), 8)                                   # pwnps x16
    w.write(len(t.seats), 8)
    for s, p in sorted(t.seats.items()):
        w.write(s, 8)
        write_packed(w, t.credits.get(p, 0))
        write_packed(w, _balance(t, p))


def _chess_bump(t):
    t.trnid = (t.trnid + 1) % 0xFF                             # 0..254: never the latch reset value


def _chess_side(t, perm):
    s = t.seat_of(perm)
    return s if s in (0, 1) else None


def _chess_new_game(io, t, perm, r):
    """403: this player wants a (re)match."""
    if _chess_side(t, perm) is None or t.phase not in (1, 6):
        log(f"  [CHESS] table {t.key}: NewGame from {perm} ignored (phase {t.phase})")
        return
    t.ready.add(perm)
    _chess_try_start(io, t, perm)


def _chess_try_start(io, t, perm=None):
    """Start a game when both seats are ready and can pay the stake. A player counts as ready from the
    moment it sits down: the client's proxy starts with its new-game request already pending (ctor
    S 00489f92 sets +0x2b5 = 1, so the NewGame button stays hidden) until the first phase 6 clears it
    (S 0048a774). So the first game starts by itself and NewGame (403) is the rematch request."""
    if t.phase not in (1, 6):
        return
    with _lock:
        players = [t.seats.get(0), t.seats.get(1)]
        start = None not in players and all(p in t.ready for p in players) and \
            all(t.credits.get(p, 0) >= t.lmtmn for p in players)
        if start:
            for p in players:
                t.credits[p] -= t.lmtmn
                t.stake_in[p] = t.lmtmn
            t.ready.clear()
            t.chess = pawnchess.initial_board()
            t.plrstt, t.pwchkmt = 0, 0xFF
            _chess_bump(t)
            _enter(t, 2)
    _update(io, t)
    if start:
        log(f"  [CHESS] table {t.key}: game starts ({players[0]} vs {players[1]}, stake {t.lmtmn} each)"
            " — seat 0 places its king")
    elif perm is not None:
        log(f"  [CHESS] table {t.key}: {perm} ready, waiting for the other player")


def _chess_place_king(io, t, perm, r):
    row = r.read(8)
    side = _chess_side(t, perm)
    with _lock:
        if side is not None and t.phase == 2 + side and row < 8:
            t.chess[pawnchess.at(t.chess, pawnchess.sq(pawnchess.SIDE_HOME[side], row))].king = True
            _enter(t, 3 if side == 0 else 4)                   # then seat 1 places; then seat 0 moves
            log(f"  [CHESS] table {t.key}: seat {side} places its king on row {row}")
        else:
            log(f"  [CHESS] table {t.key}: PlaceKing row {row} from {perm} out of turn — ignored")
        _chess_bump(t)                                         # always: unlocks the client's board
    _update(io, t)


def _chess_move(io, t, perm, r):
    _chess_play(io, t, perm, r.read(8), r.read(8), None, None)


def _chess_capture(io, t, perm, r):
    pwn, trgt, cppwn, cptrgt = r.read(8), r.read(8), r.read(8), r.read(8)
    _chess_play(io, t, perm, pwn, trgt, cppwn, cptrgt)


def _chess_play(io, t, perm, pwn, trgt, cppwn, cptrgt):
    side = _chess_side(t, perm)
    with _lock:
        b = t.chess
        ok = side is not None and t.phase == 4 + side and pwn < 16 and trgt < 64 and b[pwn].side == side \
            and (pwn, trgt) in pawnchess.legal_moves(b, side)
        victim = pawnchess.at(b, trgt) if ok else None
        if ok and victim is not None and not b[victim].king:
            ok = cppwn == victim and cptrgt in pawnchess.relocation_squares(
                b, pawnchess.col_row(trgt)[0], side)
        elif ok and cppwn is not None:
            ok = False                                          # a 401 that takes nothing
        winner = None
        if ok:
            origin = b[pwn].square
            event = pawnchess.apply(b, pwn, trgt, cptrgt if victim is not None else None)
            other = 1 - side
            if event in ("king", "edge"):
                winner = side
                if event == "king":
                    # All 16 pieces must keep distinct squares on the wire (the client's board is a
                    # square -> piece table): the game ends on the position before the king is taken.
                    b[pwn].square, b[victim].square = origin, trgt
            else:
                in_check, _, mark = pawnchess.check_mark(b, other)
                t.pwchkmt = mark
                t.plrstt = CHESS_CHECK[other] if in_check else 0
                if pawnchess.is_mated(b, other) or not pawnchess.legal_moves(b, other):
                    winner = side
                    event = "checkmate" if in_check else "no moves"
            if winner is None:
                _enter(t, 4 + other)
        _chess_bump(t)
    if not ok:
        log(f"  [CHESS] table {t.key}: illegal move {pwn}->{trgt} ({cppwn}->{cptrgt}) from {perm} — rejected")
        _update(io, t)
        return
    log(f"  [CHESS] table {t.key}: seat {side} piece {pwn} -> {trgt}"
        + (f", takes {cppwn} and puts it on {cptrgt}" if cppwn is not None else "")
        + (f" — seat {winner} wins ({event})" if winner is not None else ""))
    if winner is not None:
        _chess_end(io, t, winner)
    else:
        _update(io, t)


def _chess_end(io, t, winner):
    with _lock:
        t.plrstt = CHESS_WON[winner]
        t.pwchkmt = 0xFF
        pot = sum(t.stake_in.values())
        win_perm = t.seats.get(winner)
        if win_perm is not None:
            t.credits[win_perm] = t.credits.get(win_perm, 0) + pot
        t.stake_in = {}
        t.ready.clear()
        _enter(t, 6)
    _update(io, t)


def _chess_forfeit(io, t, perm):
    """A player leaves during a game: the other side wins the stakes."""
    side = _chess_side(t, perm)
    t.ready.discard(perm)
    if side is not None and t.phase in (2, 3, 4, 5):
        log(f"  [CHESS] table {t.key}: seat {side} left — seat {1 - side} wins")
        _chess_end(io, t, 1 - side)


_CHESS_MSGS = {MSG_CHESS_MOVE: _chess_move, MSG_CHESS_CAPTURE: _chess_capture,
               MSG_CHESS_KING: _chess_place_king, MSG_CHESS_NEWGAME: _chess_new_game}
