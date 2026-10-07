"""
Village economy — gold, items, shops and the tailor (docs/message-catalog.md, village: Avatars,
Inventory, Shops; docs/village-and-character-protocol.md §6).

Client → server (inside SendGameData 74, MSB-first bit stream; wire type = 0x2000 | id):
  3001 MoveItem          srcslt 8, srcidx 8, dstslt 8, dstidx 8 (0xFF = server picks), mvcnt 8
  3002 DeleteItemRequest slt 8, idx 8
  3600 OpenShop          NPCID 32                         (only from an NPC with act 11)
  3610 ShopBuy           ShopID 32, Slot 16, QTY 16, Backpack 16 (0xFFFF = any free slot)
  3620 ShopSell          ShopID 32, Backpack 16, QTY 16   (order differs from 3610)
  3950 AvatarColorChange Changes 8 (bit i = colour slot i), then one 4-bit colour per set bit

Server → client (all keyed by `ownr` = the avatar id = the player's perm_id; an unknown ownr is
discarded silently by the client, so these are harmless if the own avatar is not in its map):
  3201 StatsUpdate       ownr, lvl, exp, gold, glod            (32 each)
  3100 ActiveItemsUpdate ownr + exactly 4 x {sltt 8, cnt 8, itmid 32}
  3102 ItemsFullSync     ownr + 4 active records + sltcnt 8 + N inventory records
  3601 ShopInventoryData (village.shop_inventory_body), 3611 / 3621 buy / sell results {ShopID 32, Result 1}

Server decisions (catalog V15–V30):
  * State lives in memory per perm_id for the process lifetime (perm_ids are not stable across
    restarts; see mail.py for the same reasoning).
  * Starting purse: config.START_GOLD gold and glod (V17; the client's own default for a fresh
    character is 50, raised here so the shop can be tested).
  * INVENTORY_SLOTS records are ALWAYS sent. The client reads exactly its own slot count (0 before the
    character data blocks, max(20, n) after; our character blob carries no inventory part, so n = 0)
    and ignores extra records, while FEWER records make it read past the end. 20 is safe for both.
  * `sltt` (slot type) meaning is unknown [guess]: 1 for an occupied slot, 0 for empty.
  * Moves are applied as swaps; an illegal move re-sends the current state (V21). Deletes always
    succeed (V22). Buying fails on short gold or a full backpack (V29). Selling credits
    Sell × SellMod (V30). The tailor charges TAILOR_PRICE when the player can pay (V15).
"""
import struct
import threading

from . import config
from .log import log
from .village import BitReader, BitWriter

INVENTORY_SLOTS = 20
ACTIVE_SLOTS = 4                 # Pet, Head, RightHand, LeftHand (S 0048abe0)
CONTAINER_BACKPACK = 0
EQUIP_CONTAINERS = (2, 3, 4, 5)  # [inferred] container ids of the four equipment slots
TAILOR_PRICE = 50
SELL_MOD = 0.9                   # V27: the client's built-in default (007db9d0)

MSG_STATS = 3201
MSG_ITEMS_FULL = 3102
MSG_SHOP_BUY_RESULT = 0xE1B
MSG_SHOP_SELL_RESULT = 0xE25

_lock = threading.Lock()
_state = {}                      # perm_id -> Wallet


class Wallet:
    def __init__(self):
        self.level = 1
        self.exp = 0
        self.gold = config.START_GOLD
        self.glod = config.START_GOLD
        self.active = [None] * ACTIVE_SLOTS          # None or (item_id, count)
        self.backpack = [None] * INVENTORY_SLOTS
        self.colours = [0] * 8                       # hrclr sknclr shrtclr trsrclr addColor1..4
        self.open_shop = None                        # (npc_id, shop_id, stock tuple) after 3600

    def container(self, slt):
        if slt == CONTAINER_BACKPACK:
            return self.backpack
        if slt in EQUIP_CONTAINERS:
            return self.active
        return None


def wallet(perm_id):
    with _lock:
        w = _state.get(perm_id)
        if w is None:
            w = _state[perm_id] = Wallet()
        return w


def reset_for_tests():
    with _lock:
        _state.clear()


# ── Builders ──────────────────────────────────────────────────────────────────
def _slot(bw, rec):
    if rec is None:
        bw.write(0, 8).write(0, 8).write(0, 32)
    else:
        item_id, count = rec
        bw.write(1, 8).write(min(count, 255), 8).write(item_id, 32)   # sltt 1 = occupied [guess]


def _equip_index(slt, idx):
    """Equipment containers 2..5 each hold one item; map (container, index) to the active slot."""
    return slt - EQUIP_CONTAINERS[0] if slt in EQUIP_CONTAINERS else idx


def stats_body(perm_id, w):
    return BitWriter().write(perm_id, 32).write(w.level, 32).write(w.exp, 32) \
        .write(w.gold, 32).write(w.glod, 32).bytes()


def items_full_body(perm_id, w):
    bw = BitWriter().write(perm_id, 32)
    for rec in w.active:
        _slot(bw, rec)
    bw.write(INVENTORY_SLOTS, 8)                     # sltcnt — read and ignored by the client
    for rec in w.backpack:
        _slot(bw, rec)
    return bw.bytes()


def result_body(shop_id, ok):
    return BitWriter().write(shop_id, 32).write_bool(ok).bytes()


# ── Senders (village._send_village is imported lazily to keep the module import order simple) ──
def _send(conn, msg, body, tag):
    from . import village
    village._send_village(conn, msg, body, None, tag, quiet=True)
    log(f"  → [ECON] {tag}")


def send_stats(conn, perm_id):
    w = wallet(perm_id)
    _send(conn, MSG_STATS, stats_body(perm_id, w),
          f"StatsUpdate(3201) ownr={perm_id} gold={w.gold} glod={w.glod} lvl={w.level}")


def send_items(conn, perm_id):
    w = wallet(perm_id)
    used = sum(1 for r in w.backpack if r) + sum(1 for r in w.active if r)
    _send(conn, MSG_ITEMS_FULL, items_full_body(perm_id, w),
          f"ItemsFullSync(3102) ownr={perm_id} ({used} item(s))")


def send_owner_state(conn, perm_id):
    """Gold and items for the owner — sent at world entry so the client's own checks (e.g. the
    tailor's gold >= 50, S 00434230) see the server's values."""
    send_stats(conn, perm_id)
    send_items(conn, perm_id)


# ── Inbound handlers (data = the 74 MEMBLOCK field bytes) ─────────────────────
def handle_move_item(conn, perm_id, data):
    r = BitReader(data)
    srcslt, srcidx, dstslt, dstidx, _cnt = (r.read(8) for _ in range(5))
    w = wallet(perm_id)
    src, dst = w.container(srcslt), w.container(dstslt)
    si, di = _equip_index(srcslt, srcidx), _equip_index(dstslt, dstidx)
    with _lock:
        ok = src is not None and dst is not None and 0 <= si < len(src) and src[si] is not None
        if ok and dstidx == 0xFF and dst is w.backpack:
            di = next((i for i, x in enumerate(dst) if x is None), -1)
        ok = ok and 0 <= di < len(dst)
        if ok:
            src[si], dst[di] = dst[di], src[si]       # swap (moves into an empty slot too)
    log(f"  [ECON] MoveItem {srcslt}/{srcidx} → {dstslt}/{dstidx}: {'applied' if ok else 'refused, re-sync'}")
    send_items(conn, perm_id)


def handle_delete_item(conn, perm_id, data):
    r = BitReader(data)
    slt, idx = r.read(8), r.read(8)
    w = wallet(perm_id)
    c = w.container(slt)
    i = _equip_index(slt, idx)
    with _lock:
        if c is not None and 0 <= i < len(c):
            c[i] = None
    log(f"  [ECON] DeleteItem {slt}/{idx}")
    send_items(conn, perm_id)


def handle_open_shop(conn, perm_id, data, shops):
    """3600 OpenShop {NPCID} → 0xE11 ShopInventoryData with the same NPCID (an unrequested 0xE11
    pops the dialog open, so it is only ever sent as this reply). `shops` maps npc_id →
    (shop_id, name, stock)."""
    from . import village
    npc_id = BitReader(data).read(32)
    shop = shops.get(npc_id)
    if shop is None:
        log(f"  [ECON] OpenShop for NPC {npc_id}: not a shop NPC — no reply")
        return
    shop_id, name, stock = shop
    wallet(perm_id).open_shop = (npc_id, shop_id, tuple(stock))
    village.send_shop_inventory(conn, npc_id, shop_id, name, sell_mod=SELL_MOD, items=stock)
    log(f"  [ECON] OpenShop NPC {npc_id} → shop {shop_id} {name!r} ({len(stock)} item(s))")


def handle_buy(conn, perm_id, data):
    r = BitReader(data)
    shop_id, slot, qty, backpack = r.read(32), r.read(16), r.read(16), r.read(16)
    w = wallet(perm_id)
    ok, why = False, "no shop open"
    with _lock:
        if w.open_shop and 0 <= slot < len(w.open_shop[2]):
            item_id, buy, _sell = w.open_shop[2][slot]
            qty = max(qty, 1)
            cost = buy * qty
            target = backpack if backpack != 0xFFFF else next(
                (i for i, x in enumerate(w.backpack) if x is None), -1)
            if w.gold < cost:
                why = f"needs {cost} gold, has {w.gold}"
            elif not (0 <= target < INVENTORY_SLOTS) or w.backpack[target] is not None:
                why = "backpack full / slot taken"
            else:
                w.gold -= cost
                w.backpack[target] = (item_id, qty)
                ok, why = True, f"item {item_id} x{qty} into slot {target} for {cost} gold"
    log(f"  [ECON] ShopBuy shop={shop_id} slot={slot}: {'OK ' if ok else 'FAILED '}{why}")
    _send(conn, MSG_SHOP_BUY_RESULT, result_body(shop_id, ok), f"ShopBuyResult(0xE1B) ok={ok}")
    if ok:
        send_items(conn, perm_id)
        send_stats(conn, perm_id)


def handle_sell(conn, perm_id, data):
    r = BitReader(data)
    shop_id, backpack, qty = r.read(32), r.read(16), r.read(16)
    w = wallet(perm_id)
    ok, why = False, "nothing in that slot"
    with _lock:
        rec = w.backpack[backpack] if 0 <= backpack < INVENTORY_SLOTS else None
        if rec is not None:
            item_id, count = rec
            qty = min(max(qty, 1), count)
            stock = {i: s for i, _b, s in (w.open_shop[2] if w.open_shop else ())}
            price = int(stock.get(item_id, 0) * SELL_MOD) * qty
            w.gold += price
            w.backpack[backpack] = (item_id, count - qty) if count > qty else None
            ok, why = True, f"item {item_id} x{qty} for {price} gold"
    log(f"  [ECON] ShopSell shop={shop_id} slot={backpack}: {'OK ' if ok else 'FAILED '}{why}")
    _send(conn, MSG_SHOP_SELL_RESULT, result_body(shop_id, ok), f"ShopSellResult(0xE25) ok={ok}")
    if ok:
        send_items(conn, perm_id)
        send_stats(conn, perm_id)


def handle_color_change(conn, perm_id, data):
    """3950 {Changes 8, Color 4 per set bit}. The client applied the colours locally already; the
    server charges the tailor fee and returns the new purse. The caller re-broadcasts the style to the
    other players. Returns True when the change was accepted."""
    r = BitReader(data)
    changes = r.read(8)
    w = wallet(perm_id)
    new = list(w.colours)
    for i in range(8):
        if changes >> i & 1:
            new[i] = r.read(4)
    with _lock:
        paid = w.gold >= TAILOR_PRICE
        if paid:
            w.gold -= TAILOR_PRICE
            w.colours = new
    log(f"  [ECON] AvatarColorChange mask=0x{changes:02x} → {new}: "
        f"{'charged ' + str(TAILOR_PRICE) + ' gold' if paid else 'refused (gold < ' + str(TAILOR_PRICE) + ')'}")
    send_stats(conn, perm_id)
    return paid
