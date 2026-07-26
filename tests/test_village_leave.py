"""
Village LEAVE (msg 2002 / 0x27D2) tests. No live game, no sockets.

Background — the message was mis-named for months. `SendGameData(74){msg_type=0x27D2, code=0xAFFEDEAD}`
is **NETMSG 2002, the LEAVE-VILLAGE request**, sent by
`VillageServerConnection_SendLeaveVillageRequest_2002@0x0046bde0` right after
`LobbyManager::SetState(LeavingVillage=10)`. The client then WAITS. State 10 has exactly two exits
(`HandleLoggedOut` vtbl+0x1c — unreachable for the village transport class `CommLayer::ConnectionReal`;
and `HandleDisconnected` vtbl+0x20, reached via `OnConnectionLost`), and `StatePump_Tick` never touches
state 10 — so the client cannot recover on its own.

Both previous stub behaviours were wrong answers:
  * answering with `EnterWorld(1000)` told the client to ENTER when it asked to LEAVE  → the "clone";
  * answering with nothing (the no-op)                                                 → hung forever.

A third answer — closing the village connection — was implemented and LIVE-TESTED and is also WRONG: it
raises "!CONNECTION_LOST_TEXT" (the disconnect hits while the transport is still in state 8, where
FUN_10030ad0 case 4 raises ConnectionLost with a hardcoded reason 10), and at MATCH START both clients
send 2002, so both get kicked.

The genuine answer [PROVEN 2026-07-26]: **msg 1006 {code=0xDEADBEEF}**. HandleWorldLoginAck@0x0046ecf6
calls ConnectionReal::Logout (UserComm first while it is open, then the VILLAGE transport), which sets
state 9 — so the disconnect then takes the state-9 branch to OnLoggedOut -> HandleLoggedOut ->
SetState(VillageLeft=11) -> the +0x1c observer -> arms the referee.
ER: engagement_records/2026-07-26_leave-answer-worldloginack-1006.md

Proves:
  1. A 2002 on a village conn is answered with WorldLoginAck(1006) — the logout trigger.
  2. It is **never** answered with EnterWorld(1000) (clone regression guard).
  3. EVERY repeated 2002 gets its own 1006 (the teardown is two-phase, so the latch must be bypassed).
  4. A 2002 on a NON-village conn is ignored (never closes a lobby/UC connection).
  5. The in-world PingCode path is unaffected.
  6. `village.send_enter_world` force/one-shot semantics still hold (used by the entry push).

Run:  python tests/test_village_leave.py   (or: pytest tests/test_village_leave.py)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import config, dispatch, village  # noqa: E402


class FakeVillageConn:
    def __init__(self, cid=8, is_village=True):
        self.id = cid
        self.alive = True
        self.is_village = is_village
        self.raw = []            # raw TinCat frames via send_raw
        self.closes = []         # close_graceful() calls

    def send_raw(self, data):
        self.raw.append(data)

    def close_graceful(self, why=""):
        self.closes.append(why)


def _leave_fields():
    # SendGameData(74) inner: msg_type=0x27D2 (=2002), data field "code"=0xAFFEDEAD.
    return {"msg_type": config.VILLAGE_LEAVE_REQUEST_MSGTYPE, "data": bytes.fromhex("affedead")}


def _world_login_ack_frame():
    return village.gamedata_frame(config.VILLAGE_MSG_WORLD_LOGIN_ACK, village.world_login_ack_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def _enter_world_frame():
    return village.gamedata_frame(config.VILLAGE_MSG_ENTER_WORLD, village.enter_world_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def test_leave_does_not_close_the_connection():
    """LIVE-FALSIFIED 2026-07-26: closing the village conn on 2002 completes the leave but raises
    !CONNECTION_LOST_TEXT, and at MATCH START it kicks BOTH players (both send 2002). Reverted to a
    no-op; this test locks that in so the close is not reintroduced without new evidence."""
    c = FakeVillageConn()
    c._enter_world_sent = True                  # already in the village (entry push fired)
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c.closes == [], "msg 2002 must NOT close the village conn (kicks both players at match start)"
    assert c._leave_requests == 1


def test_leave_is_answered_with_worldloginack_1006():
    """[PROVEN 2026-07-26] msg 1006 {code=0xDEADBEEF} is the only message reaching the logout path
    (HandleWorldLoginAck -> ConnectionReal::Logout -> state 9 -> OnLoggedOut -> VillageLeft(11))."""
    c = FakeVillageConn()
    c._enter_world_sent = True
    c._world_login_ack_sent = True              # entry-time ack already latched; force must bypass it
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert len(c.raw) == 1, f"msg 2002 must be answered with exactly one 1006, got {len(c.raw)}"
    assert _world_login_ack_frame() in c.raw[0], "the answer must be the WorldLoginAck(1006) frame"


def test_leave_never_answered_with_enterworld():
    """Clone regression guard: answering 2002 with EnterWorld(1000) told the client to ENTER when it
    asked to LEAVE — that is the origin of the match-start 'clone'. Must never come back."""
    c = FakeVillageConn()
    c._enter_world_sent = True
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    joined = b"".join(c.raw)
    assert _enter_world_frame() not in joined, "msg 2002 must NEVER be answered with EnterWorld(1000)"


def test_repeated_leaves_each_get_an_ack():
    """The client resends 2002 while it waits (live-observed 3x). EVERY one must be answered — the
    teardown is two-phase (UserComm logs out first, the village transport on a later round), so the
    one-shot latch must be bypassed each time via force=True."""
    c = FakeVillageConn()
    for _ in range(4):
        dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c._leave_requests == 4
    assert len(c.raw) == 4, f"every 2002 must get a 1006 (two-phase teardown), got {len(c.raw)}"
    assert c.closes == [], "the leave must not close the connection (that was live-falsified)"


def test_leave_on_non_village_conn_is_ignored():
    """A 0x27D2 arriving on a lobby/UC conn must never tear that connection down."""
    c = FakeVillageConn(is_village=False)
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c.closes == [], "non-village conns must not be closed by a village leave request"
    assert c.raw == []


def test_pingcode_path_unaffected():
    """A 0x2ED6 PingCode still answers Pong (+ once 1006) — no regression to the in-world keepalive."""
    c = FakeVillageConn()
    dispatch._h_send_game_data(c, {"msg_type": config.VILLAGE_PINGCODE_MSGTYPE, "data": b"\x00\x00\x00\x00"}, 0)
    assert len(c.raw) >= 1      # at least the Pong
    assert c.closes == [], "a PingCode must not close the connection"


def test_send_enter_world_force_semantics():
    """Unit: force=False is one-shot (latch); force=True re-sends past it. Still used by the entry push."""
    c = FakeVillageConn()
    village.send_enter_world(c)
    assert len(c.raw) == 1 and c._enter_world_sent is True
    village.send_enter_world(c)
    assert len(c.raw) == 1
    village.send_enter_world(c, force=True)
    assert len(c.raw) == 2


def _run():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {e}")
    print()
    print(f"{failures} test(s) FAILED" if failures else "All village-leave tests PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
