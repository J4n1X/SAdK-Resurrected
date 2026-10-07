"""
Server notices (offline): match rewards, the daily funnies and "YOU'VE GOT MAIL!" as local-chat lines from the server
(chat.notice_from_server): sent at once when the player's chat connection is live, otherwise kept and
delivered at the next world entry; unread mail is announced at world entry and when new mail arrives
for a player in the world. Mail survives a restart.

Run:  python tests/test_notices.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.environ["SADK_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "players.json")

from sadk_lobby import chat, config, dispatch, economy, mail, players, rewards, store  # noqa: E402


class Conn:
    def __init__(self, perm):
        self.player = players.Player(perm_id=perm, char_id=perm, user_id=perm, username=f"u{perm}",
                                     char_name=f"c{perm}", data=b"")
        self.alive = True


def _setup(online=(), in_world=(), clear=True):
    lines = []
    chat.notice_from_server = lambda conn, text, cell_id=None: lines.append((conn.player.perm_id, text))
    chat._uc_conn_of = lambda perm: Conn(perm) if perm in online else None
    dispatch._in_world_conns = lambda exclude_player=None, exclude_conn=None: [Conn(p) for p in in_world]
    if clear:
        dispatch._pending_notices.clear()
    return lines


def test_reward_notice_kept_until_world_entry():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    mail.reset_for_tests()
    lines = _setup()                                          # in a match: no chat connection
    dispatch._reward_notice(7, 12, 1, True, 3825, 382)
    assert lines == []
    lines = _setup(online={7}, clear=False)                   # back in the world
    dispatch._welcome(Conn(7))
    texts = [t for p, t in lines if p == 7]
    assert texts[0].startswith("Welcome") and "3825 XP and 382 gold (12 min, winner, 1 chest(s))" in texts[1]
    dispatch._reward_notice(7, 1, 0, False, 0, 0)            # live: sent at once
    assert "under 2 minutes" in lines[-1][1]
    print("reward notice kept while away, delivered at world entry OK")


def test_mail_notice():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    mail.reset_for_tests()
    lines = _setup(online={8})
    mail.add(8, 9, "Hallo", b"x\x00")
    dispatch._welcome(Conn(8))
    assert lines[-1] == (8, dispatch.MAIL_NOTICE) == (8, "YOU'VE GOT MAIL!")
    mid = mail.inbox(8)[0]["message_id"]
    mail.mark(mid, 1)
    lines.clear()
    dispatch._welcome(Conn(8))
    assert dispatch.MAIL_NOTICE not in [t for _, t in lines]  # all read: no notice
    # New mail while in the lobby world: told at once; not in the world: nothing now (told at entry).
    lines = _setup(online={8}, in_world={8})
    assert dispatch._notify(8, dispatch.MAIL_NOTICE, only_in_world=True) and lines == [(8, "YOU'VE GOT MAIL!")]
    lines = _setup(online={8})
    assert not dispatch._notify(8, dispatch.MAIL_NOTICE, only_in_world=True) and lines == []
    assert dispatch._pending_notices == {}
    print("YOU'VE GOT MAIL! at world entry and on arrival in the world OK")


def test_mail_survives_restart():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    mail.reset_for_tests()
    mid = mail.add(5, 6, "Bleibt", b"text\x00")
    mail._mails = None                                        # a restart: reload from disk
    assert [m["title"] for m in mail.inbox(5)] == ["Bleibt"] and mail.unread(5) == 1
    assert mail.add(5, 6, "Zwei", b"\x00") == mid + 1         # ids keep counting
    print("mail persisted across a restart OK")


def test_local_cell_choice():
    me, other = object(), object()
    base = config.LOCAL_CHAT_CELL_BASE
    with chat._roster_lock:
        chat._roster.clear()
        chat._roster.update({config.GLOBAL_CHAT_CELL: [me, other], base + 2: [other], base + 3: [me]})
    assert chat.local_cell_of(me, 3) == base + 3              # its zone's cell
    assert chat.local_cell_of(me, 2) == base + 3              # not in that zone's cell: the one it joined
    assert chat.local_cell_of(object()) == config.GLOBAL_CHAT_CELL   # no local cell: global
    with chat._roster_lock:
        chat._roster.clear()
    print("server lines go to the local chat cell OK")


def test_daily_funnies():
    store.reset_for_tests(os.environ["SADK_STORE_PATH"])
    mail.reset_for_tests()
    cid = int(store.create_character("daily", "Taeglich", b"\x00" * 24)["char_id"])
    economy.reset_for_tests()
    before = economy.load(cid).glod
    assert economy.daily_allowance(cid, "2026-10-07") == economy.DAILY_FUNNIES == 500
    assert economy.daily_allowance(cid, "2026-10-07") == 0      # once per day
    assert economy.wallet(cid).glod == before + 500
    assert economy.daily_allowance(cid, "2026-10-08") == 500    # next day again
    lines = _setup(online={cid})
    economy.wallet(cid).allowance_granted = 500
    dispatch._welcome(Conn(cid))
    assert any(t.startswith("Daily allowance: +500 funnies") for _, t in lines)
    assert economy.wallet(cid).allowance_granted == 0
    print("500 funnies once per day, announced at world entry OK")


if __name__ == "__main__":
    test_local_cell_choice()
    test_daily_funnies()
    test_reward_notice_kept_until_world_entry()
    test_mail_notice()
    test_mail_survives_restart()
    print("\nAll notice tests PASSED")
