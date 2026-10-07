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

from . import economy
from .log import log
from .village import BitReader, BitWriter

DICE, POKER, PAWNCHESS = 1, 2, 3
MSG_REMOVE, MSG_UPDATE, MSG_CREATE = 0xD8, 0xD9, 0xDA
MSG_NO_TABLE, MSG_NO_SEAT = 0xDB, 0xDC
# Dice only: Poker and PawnChess updates would carry no game state, so their dealer seat stays at the
# client's default — the same unchecked node lookup that crashed Dice (see table_body) is the likely
# trap there. They are refused (0xDB) until their state block is implemented.
PLAYABLE = (DICE,)
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
        cap = DICE_SEATS if kind == DICE else MAX_SEATS
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
    state = state and t.kind == DICE
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
    if state:
        elapsed = min(int((time.monotonic() - t.phase_start) * 1000), 0xFFFF)
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
                 stats=lambda perm_id: None, schedule=_timer):
        self.send, self.everyone, self.publish_cell = send, everyone, publish_cell
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


def leave(io, perm_id, t):
    """Unseat a player and return the stack. Bets placed in a round that has been thrown (phase 3/4)
    are settled first; before the throw they are simply part of the stack again [decision]."""
    with _lock:
        s = t.seat_of(perm_id)
        if s is None:
            return
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


def handle_game_action(io, conn, perm_id, msg_type, data):
    """Poker 300-302 and PawnChess 400-403: game logic not implemented — logged."""
    log(f"  [MINIGAME] action 0x{msg_type:x} from {perm_id} ({data.hex()}) — game logic not implemented")
