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

from sadk_lobby import config, economy, village  # noqa: E402
from sadk_lobby.village import BitReader, BitWriter  # noqa: E402

PERM = 4242
NPC = 900001
STOCK = ((7, 100, 60), (8, 5000, 10))
SHOPS = {NPC: (31, "Laden", STOCK)}

sent = []


def _capture(conn, msg_type, body, magic, tag, quiet=False):
    sent.append((msg_type, body))


village._send_village = _capture


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
    assert _backpack()[1][0] == (1, 1, 7)
    sent.clear()
    # too expensive: result false, no state messages
    economy.handle_buy(None, PERM, BitWriter().write(31, 32).write(1, 16).write(1, 16)
                       .write(0xFFFF, 16).bytes())
    assert _msgs() == [economy.MSG_SHOP_BUY_RESULT]
    # sell it back for 60 * 0.9 = 54
    economy.handle_sell(None, PERM, BitWriter().write(31, 32).write(0, 16).write(1, 16).bytes())
    assert _purse()[3] == config.START_GOLD - 100 + 54
    assert _backpack()[1][0] == (0, 0, 0)
    sent.clear()
    print("shop open / buy / refused buy / sell OK")


def test_move_delete_and_tailor():
    economy.reset_for_tests()
    w = economy.wallet(PERM)
    w.backpack[3] = (12, 1)
    # backpack slot 3 → equipment container 3 (active slot 1)
    economy.handle_move_item(None, PERM, BitWriter().write(0, 8).write(3, 8).write(3, 8)
                             .write(0, 8).write(1, 8).bytes())
    active, pack = _backpack()
    assert active[1] == (1, 1, 12) and pack[3] == (0, 0, 0)
    economy.handle_delete_item(None, PERM, BitWriter().write(3, 8).write(0, 8).bytes())
    assert _backpack()[0][1] == (0, 0, 0)
    sent.clear()
    # tailor: change hair (bit 0) and shirt (bit 2) to 5 and 9
    ok = economy.handle_color_change(None, PERM, BitWriter().write(0b101, 8).write(5, 4)
                                     .write(9, 4).bytes())
    assert ok and w.colours[:3] == [5, 0, 9] and _purse()[3] == config.START_GOLD - economy.TAILOR_PRICE
    w.gold = 10
    assert not economy.handle_color_change(None, PERM, BitWriter().write(1, 8).write(2, 4).bytes())
    assert w.colours[0] == 5
    print("move / delete / tailor (paid and refused) OK")


if __name__ == "__main__":
    test_open_buy_sell()
    test_move_delete_and_tailor()
    print("\nAll economy tests PASSED")
