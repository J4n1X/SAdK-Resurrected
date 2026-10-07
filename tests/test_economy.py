"""
Village economy (offline): shop open/buy/sell, item move/delete, tailor — the request parsing, the
state changes and the replies (3201 / 3102 / 0xE11 / 0xE1B / 0xE25). See sadk_lobby/economy.py.

Run:  python tests/test_economy.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tempfile  # noqa: E402
os.environ.setdefault("SADK_STORE_PATH", os.path.join(tempfile.mkdtemp(), "players.json"))  # never touch the real store
from sadk_lobby import config, economy, village  # noqa: E402
from sadk_lobby.village import BitReader, BitWriter  # noqa: E402

PERM = 4242
NPC = 900001
STOCK = ((7, 100, 60), (8, 10 ** 8, 10))      # item 8 is never affordable
SHOPS = {NPC: (31, "Laden", STOCK)}

sent = []


def _capture(conn, msg_type, body, magic, tag, quiet=False):
    sent.append((msg_type, body))


village._send_village = _capture
settled = []
economy.settle = settled.append          # collect the delayed second step of an unequip


def _msgs():
    out = [m for m, _ in sent]
    sent.clear()
    return out


def _last(msg):
    return next(b for m, b in reversed(sent) if m == msg)


def _purse():
    r = BitReader(_last(economy.MSG_STATS))
    return [r.read(32) for _ in range(5)]          # ownr, lvl, exp, gold, glod


def _backpack():
    r = BitReader(_last(economy.MSG_ITEMS_FULL))
    assert r.read(32) == PERM
    active = [(r.read(8), r.read(8), r.read(32)) for _ in range(4)]
    assert r.read(8) == economy.INVENTORY_SLOTS
    pack = [(r.read(8), r.read(8), r.read(32)) for _ in range(economy.INVENTORY_SLOTS)]
    return active, pack


def test_open_buy_sell():
    economy.reset_for_tests()
    economy.handle_open_shop(None, PERM, BitWriter().write(NPC, 32).bytes(), SHOPS)
    r = BitReader(_last(village.VILLAGE_MSG_SHOP_INVENTORY))
    assert (r.read(32), r.read(32)) == (NPC, 31)             # NPCID echoes the request
    assert _msgs() == [village.VILLAGE_MSG_SHOP_INVENTORY]
    economy.handle_open_shop(None, PERM, BitWriter().write(12345, 32).bytes(), SHOPS)
    assert _msgs() == []                                      # not a shop NPC: no reply
    # buy stock slot 0 (item 7 for 100) into any free slot
    economy.handle_buy(None, PERM, BitWriter().write(31, 32).write(0, 16).write(1, 16)
                       .write(0xFFFF, 16).bytes())
    assert [m for m, _ in sent] == [economy.MSG_SHOP_BUY_RESULT, economy.MSG_ITEMS_FULL, economy.MSG_STATS]
    r = BitReader(_last(economy.MSG_SHOP_BUY_RESULT))
    assert (r.read(32), r.read(1)) == (31, 1)
    assert _purse()[3] == config.START_GOLD - 100
    assert _backpack()[1][0] == (5, 1, 7)          # item 7 is a pet: sltt 5
    sent.clear()
    # too expensive: result false, no state messages
    economy.handle_buy(None, PERM, BitWriter().write(31, 32).write(1, 16).write(1, 16)
                       .write(0xFFFF, 16).bytes())
    assert _msgs() == [economy.MSG_SHOP_BUY_RESULT]
    # sell it back for 60 * 0.9 = 54
    economy.handle_sell(None, PERM, BitWriter().write(31, 32).write(0, 16).write(1, 16).bytes())
    assert _purse()[3] == config.START_GOLD - 100 + int(340 // 2 * economy.SELL_MOD)   # item 7 lists at 340
    assert _backpack()[1][0] == (0, 0, 0)
    sent.clear()
    print("shop open / buy / refused buy / sell OK")


def test_move_delete_and_tailor():
    economy.reset_for_tests()
    w = economy.wallet(PERM)
    w.backpack[3] = (12, 1, economy.UNKNOWN_SLTT)
    # backpack slot 3 → equipment container 3 (active slot 1)
    economy.handle_move_item(None, PERM, BitWriter().write(0, 8).write(3, 8).write(3, 8)
                             .write(0, 8).write(1, 8).bytes())
    active, pack = _backpack()
    assert active[1] == (3, 1, 12) and pack[3] == (0, 0, 0)   # sltt = the container it is worn in
    economy.handle_delete_item(None, PERM, BitWriter().write(3, 8).write(0, 8).bytes())
    assert _backpack()[0][1] == (3, 0, 0)   # step 1: the emptied slot names its container (clears it)
    settled.pop()()                          # step 2, normally 0.5 s later
    assert _backpack()[0][1] == (0, 0, 0)   # back to sltt 0 so the slot counts as free again
    sent.clear()
    # tailor: change hair (bit 0) and shirt (bit 2) to 5 and 9
    ok = economy.handle_color_change(None, PERM, BitWriter().write(0b101, 8).write(5, 4)
                                     .write(9, 4).bytes())
    assert ok and w.colours[:3] == [5, 0, 9] and _purse()[3] == config.START_GOLD - economy.TAILOR_PRICE
    w.gold = 10
    assert not economy.handle_color_change(None, PERM, BitWriter().write(1, 8).write(2, 4).bytes())
    assert w.colours[0] == 5
    print("move / delete / tailor (paid and refused) OK")


def test_world_entry_loads_and_saves_the_character():
    """The character `data` blob is the game's save (savegame.py): a new character gets the test purse
    and the debug backpack once; after that everything is persistent."""
    import struct
    from sadk_lobby import savegame, store
    store.reset_for_tests(os.path.join(tempfile.mkdtemp(), "players.json"))
    economy.reset_for_tests()
    store.get_or_create_account("Saver")
    creation = savegame.join([struct.pack("<11I", 1, 1, 0, 2, 3, 4, 5, 6, 7, 8, 9), b"", b"", b"", b"", b""])
    cid = int(store.create_character("Saver", "Saver", creation)["char_id"])
    w = economy.load(cid)
    assert w.gold == config.START_GOLD and [r[0] for r in w.backpack] == list(economy.DEBUG_BACKPACK)
    assert w.colours == [2, 3, 4, 5, 6, 7, 8, 9] and w.trbgndr == 0x10
    assert all(r[2] in (2, 3, 4, 5) for r in w.backpack)
    assert not savegame.parse(store.find_character(cid)[0]["data"]).fresh   # saved in full form
    w.gold, w.active[0], w.colours[3] = 777, (2, 1, 2), 11
    w.pose = ((12.5, 2.7, -3.0), 90.0, 3, 15)
    economy.persist(cid)
    economy.reset_for_tests()                         # a server restart
    w = economy.load(cid)
    assert w.gold == 777 and w.active[0] == (2, 1, 2) and w.colours[3] == 11
    assert w.pose[2] == 3 and abs(w.pose[0][0] - 12.5) < 1e-5
    assert len(economy.shop_stock()) == len(economy.ITEMS) == 36
    sent.clear()
    print("world entry loads the character save; changes and position persist OK")


if __name__ == "__main__":
    test_world_entry_loads_and_saves_the_character()
    test_open_buy_sell()
    test_move_delete_and_tailor()
    print("\nAll economy tests PASSED")
