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

The stub now completes the leave the genuine way: it closes the village connection (FIN).
ER: engagement_records/2026-07-26_village-leave-close-connection.md

Proves:
  1. A 2002 on a village conn closes the connection gracefully.
  2. It sends NO application frame — in particular **never** an EnterWorld(1000) (clone regression guard).
  3. Repeated 2002s stay safe (the client resends while waiting) and keep an honest counter.
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


def _enter_world_frame():
    return village.gamedata_frame(config.VILLAGE_MSG_ENTER_WORLD, village.enter_world_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def test_leave_closes_the_connection():
    """The genuine completion: msg 2002 → graceful close, so the client reaches
    OnConnectionLost → HandleDisconnected → SetState(VillageLeft=11)."""
    c = FakeVillageConn()
    c._enter_world_sent = True                  # already in the village (entry push fired)
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert len(c.closes) == 1, f"msg 2002 must close the village conn once, got {len(c.closes)}"
    assert c._leave_requests == 1


def test_leave_sends_no_frames_and_never_enterworld():
    """Clone regression guard: answering 2002 with EnterWorld(1000) is what re-entered the LOBBY world.
    The leave path must emit no application frame at all."""
    c = FakeVillageConn()
    c._enter_world_sent = True
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c.raw == [], f"msg 2002 must not send any frame, got {len(c.raw)}"
    joined = b"".join(c.raw)
    assert _enter_world_frame() not in joined, "msg 2002 must NEVER be answered with EnterWorld(1000)"


def test_repeated_leaves_are_safe_and_counted():
    """The client resends 2002 while it waits (live-observed 3x in one session). Each is handled and the
    counter stays honest — the close itself is idempotent at the socket layer."""
    c = FakeVillageConn()
    for _ in range(4):
        dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c._leave_requests == 4
    assert len(c.closes) == 4
    assert c.raw == []


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
