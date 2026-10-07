"""
Village minigame tables (docs/message-catalog.md, village: Minigames).

Table lifecycle for all three games (1 Dice, 2 Poker, 3 PawnChess) and the Dice rules. Poker and
PawnChess tables can be created, joined and left, but their game logic is NOT implemented: their
updates carry no game-state block (mngt bit7 clear, which the readers accept), because the per-game
state layouts are only [inferred] and a wrong one desynchronises the stream.

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

Wire rules that would crash or corrupt the client [known]: mngt low nibble must be 1..3; the seat block
lists at most 8 entries, only `used` = 1 entries, sltidx 0..7. Every seated AVATAR must already exist
with a 3D object in the receiving client, or that client rejects the whole seat block (silently).

Server decisions (V33–V39), marked [guess] where the client gives no hint:
  * msgprt from 1 upwards, rnid 0 (V34). One table per (tavern, table index); a second create there
    gets 0xDB (V33).
  * scntbl = tavern in the low nibble, table index in the high nibble [guess].
  * Each table gets its own chat cell (chtid, V35), published on every UC connection.
  * Joining moves `stck` gold into table credits (clamped to the player's gold, V38); Amount moves more
    (V39); leaving returns the credits to gold. A table is removed when its last player leaves (V37).
  * Dice: phase 1 = betting, 3 = result [inferred from the reader]; the server rolls on 221, settles
    with the client's own payout rule (ComputeSeatPayout S 00488870), and returns to betting after
    DICE_RESULT_SECS.
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
MAX_SEATS = 8
FIRST_TABLE_CELL = 1000          # chat cells for tables: 1000, 1001, ... (must not collide with lobby/zone cells)
PHASE_BETTING, PHASE_RESULT = 1, 3
DICE_RESULT_SECS = 5.0
LIMIT_MAX = 0x7FFFFFFF

_lock = threading.RLock()
_tables = {}                     # (msgprt, rnid) -> Table
_next_msgprt = 1


class Table:
    def __init__(self, kind, name, tavern, index, password, crc, lmtmn, lmtmx, mxplyr, chtid, key):
        self.kind, self.name = kind, name
        self.tavern, self.index = tavern, index
        self.password, self.crc = password, crc
        self.lmtmn, self.lmtmx = lmtmn, lmtmx
        self.mxplyr = max(1, min(mxplyr or MAX_SEATS, MAX_SEATS))
        self.chtid, self.key = chtid, key
        self.seats = {}          # sltidx -> perm_id
        self.credits = {}        # perm_id -> table credits
        self.bets = {}           # perm_id -> [11]
        self.dice = 0
        self.phase = PHASE_BETTING
        self.phase_start = time.monotonic()

    def seat_of(self, perm_id):
        return next((s for s, p in self.seats.items() if p == perm_id), None)


def reset_for_tests():
    global _next_msgprt
    with _lock:
        _tables.clear()
        _next_msgprt = 1


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
    mngt = t.kind | (0x10 if settings else 0) | (0x40 if seats else 0) | (0x80 if state else 0)
    w.write(mngt, 8)
    w.write((t.index & 0xF) << 4 | (t.tavern & 0xF), 8)           # scntbl [guess]
    write_packed(w, t.chtid)
    w.write(t.key[0], 16).write(t.key[1], 8)


def table_body(t, settings=True, seats=True):
    """0xDA / 0xD9 body: key, then the blocks the mngt flags announce (settings, seats, game state).
    Game state is only written for Dice."""
    state = t.kind == DICE
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
        elapsed = int((time.monotonic() - t.phase_start) * 1000) & 0xFFFF
        w.write(t.dice, 8).write(0xFF, 8)                         # dice (two nibbles), dealer none
        w.write(len(t.seats), 8).write(t.phase, 8).write(elapsed, 16)
        for sltidx, perm in sorted(t.seats.items()):
            w.write(sltidx, 8)
            write_packed(w, t.credits.get(perm, 0))
            write_packed(w, economy.wallet(perm).gold)            # accnt = the player's gold [guess]
            for b in t.bets.get(perm, [0] * 11):
                write_packed(w, b)
    return w.bytes()


def key_body(t):
    w = BitWriter()
    _key(w, t, False, False, False)
    return w.bytes()


def payout(bets, dice_sum):
    """The client's own settlement (ComputeSeatPayout S 00488870). bets[k] is the bet on sum k + 2."""
    group_a, group_b = (2, 4, 6, 9, 11), (3, 5, 8, 10, 12)
    if dice_sum == 7:
        return bets[5] * 3
    for group in (group_a, group_b):
        if dice_sum in group:
            return sum(bets[s - 2] * (5 if s == dice_sum else 1) for s in group)
    return 0


# ── Handlers. `send(conn, msg, body)` sends one village message; `everyone()` lists the in-world
#    village conns; `publish_cell(chtid, name)` puts a chat cell on every UC connection. ──────────
class Io:
    def __init__(self, send, everyone, publish_cell):
        self.send, self.everyone, self.publish_cell = send, everyone, publish_cell

    def broadcast(self, msg, body):
        for c in self.everyone():
            try:
                self.send(c, msg, body)
            except Exception as exc:  # noqa: BLE001
                log(f"  [MINIGAME] send to conn #{getattr(c, 'id', '?')} failed: {exc}")


def handle_create(io, conn, perm_id, data):
    global _next_msgprt
    r = BitReader(data)
    kind, _money, _stake = r.read(8), r.read(8), r.read(32)
    name = bytes(r.read(8) for _ in range(r.read(8))).decode("utf-8", "replace")
    lmtmn, lmtmx, mxplyr = r.read(32), r.read(32), r.read(8)
    tavern, index, psswd, crc = r.read(8), r.read(8), r.read(8), r.read(32)
    with _lock:
        taken = any((t.tavern, t.index) == (tavern, index) for t in _tables.values())
        if kind not in (DICE, POKER, PAWNCHESS) or taken:
            io.send(conn, MSG_NO_TABLE, b"")
            log(f"  [MINIGAME] create type={kind} tavern={tavern}/{index}: refused (0xDB)")
            return
        key = (_next_msgprt & 0xFFFF, 0)
        _next_msgprt += 1
        t = Table(kind, name, tavern, index, psswd, crc, lmtmn, min(lmtmx, LIMIT_MAX), mxplyr,
                  FIRST_TABLE_CELL + key[0], key)
        _tables[key] = t
    io.publish_cell(t.chtid, name or f"Tisch {key[0]}")
    io.broadcast(MSG_CREATE, table_body(t))
    io.broadcast(MSG_UPDATE, table_body(t))
    log(f"  [MINIGAME] table {key} created: type={kind} {name!r} tavern={tavern}/{index} "
        f"max={t.mxplyr} cell={t.chtid}")


def _table(r):
    return _tables.get((r.read(16), r.read(8)))


def handle_join(io, conn, perm_id, data):
    r = BitReader(data)
    with _lock:
        t = _table(r)
        stake, crc = r.read(32), r.read(32)
        free = [s for s in range(t.mxplyr) if s not in t.seats] if t else []
        if t is None or (t.seat_of(perm_id) is None and not free) or (t.password and crc != t.crc):
            io.send(conn, MSG_NO_SEAT, b"")
            log(f"  [MINIGAME] join by {perm_id}: refused (0xDC)")
            return
        if t.seat_of(perm_id) is None:
            t.seats[free[0]] = perm_id
            w = economy.wallet(perm_id)
            moved = min(stake, w.gold)
            w.gold -= moved
            t.credits[perm_id] = moved
            t.bets[perm_id] = [0] * 11
    io.broadcast(MSG_UPDATE, table_body(t))
    log(f"  [MINIGAME] {perm_id} joined table {t.key} seat {t.seat_of(perm_id)} "
        f"with {t.credits.get(perm_id)} credits")


def leave(io, perm_id, t):
    """Unseat a player, return the credits to gold, remove an empty table."""
    with _lock:
        s = t.seat_of(perm_id)
        if s is None:
            return
        del t.seats[s]
        economy.wallet(perm_id).gold += t.credits.pop(perm_id, 0)
        t.bets.pop(perm_id, None)
        empty = not t.seats
        if empty:
            _tables.pop(t.key, None)
    if empty:
        io.broadcast(MSG_REMOVE, key_body(t))
        log(f"  [MINIGAME] table {t.key} removed (last player left)")
    else:
        io.broadcast(MSG_UPDATE, table_body(t))
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
        w = economy.wallet(perm_id)
        moved = min(amount, w.gold)
        w.gold -= moved
        t.credits[perm_id] = t.credits.get(perm_id, 0) + moved
    io.broadcast(MSG_UPDATE, table_body(t, settings=False))
    log(f"  [MINIGAME] {perm_id} topped up {moved} credits at table {t.key}")


def handle_place_bets(io, conn, perm_id, data):
    r = BitReader(data)
    t = _table(r)
    credits = read_packed(r)
    bets = [read_packed(r) for _ in range(11)]
    if t is None or t.kind != DICE or t.seat_of(perm_id) is None or t.phase != PHASE_BETTING:
        return
    with _lock:
        have = t.credits.get(perm_id, 0) + sum(t.bets.get(perm_id, [0] * 11))
        if sum(bets) > have:                                       # cannot bet more than you hold
            log(f"  [MINIGAME] {perm_id} bets {sum(bets)} > {have}: ignored")
        else:
            t.bets[perm_id] = bets
            t.credits[perm_id] = have - sum(bets)
            if credits != t.credits[perm_id]:
                log(f"  [MINIGAME] {perm_id} reported credits {credits}, server has {t.credits[perm_id]}")
    io.broadcast(MSG_UPDATE, table_body(t, settings=False))


def handle_roll(io, conn, perm_id, data, schedule=None):
    t = _table(BitReader(data))
    if t is None or t.kind != DICE or t.seat_of(perm_id) is None or t.phase != PHASE_BETTING:
        return
    with _lock:
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        t.dice = d1 << 4 | d2
        for perm, bets in t.bets.items():
            t.credits[perm] = t.credits.get(perm, 0) + payout(bets, d1 + d2)
        t.phase, t.phase_start = PHASE_RESULT, time.monotonic()
    io.broadcast(MSG_UPDATE, table_body(t, settings=False))
    log(f"  [MINIGAME] table {t.key} rolled {d1}+{d2}={d1 + d2}")

    def back_to_betting():
        with _lock:
            if t.key not in _tables:
                return
            t.phase, t.phase_start = PHASE_BETTING, time.monotonic()
            for perm in t.bets:
                t.bets[perm] = [0] * 11
        io.broadcast(MSG_UPDATE, table_body(t, settings=False))
    (schedule or (lambda f: threading.Timer(DICE_RESULT_SECS, f).start()))(back_to_betting)


def handle_game_action(io, conn, perm_id, msg_type, data):
    """Poker 300-302 and PawnChess 400-403: game logic not implemented — logged."""
    log(f"  [MINIGAME] action 0x{msg_type:x} from {perm_id} ({data.hex()}) — game logic not implemented")
