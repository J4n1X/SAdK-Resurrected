"""
Village LEAVE (msg 2002 / 0x27D2) — the TWO-PHASE logout. No live game, no sockets.

`SendGameData(74){msg_type=0x27D2, code=0xAFFEDEAD}` is **NETMSG 2002, the LEAVE-VILLAGE request**, sent
by `VillageServerConnection_SendLeaveVillageRequest_2002@0x0046bde0` right after
`LobbyManager::SetState(LeavingVillage=10)`. The client then WAITS — and (live-verified by trace,
2026-07-26) it sends 2002 **exactly once**: no retry, no timeout, no self-recovery. State 10's only two
exits are `HandleLoggedOut` (vtbl+0x1c) and `HandleDisconnected` (vtbl+0x20).

Wrong answers already falsified live:
  * `EnterWorld(1000)` — tells the client to ENTER when it asked to LEAVE → the match-start "clone";
  * nothing (no-op)    — hangs in state 10 forever;
  * closing the socket — the disconnect lands while the transport is still in state 8, where
    `FUN_10030ad0` case 4 raises ConnectionLost with a HARDCODED reason 10 → `!CONNECTION_LOST_TEXT`;
    and at match start both clients send 2002, so both get kicked.

The genuine mechanism `[PROVEN]`: **msg 1006 {code=0xDEADBEEF}**. `HandleWorldLoginAck@0x0046ec50`
branches on whether UserComm is open:
    UC OPEN   → `UserCommConnection::Logout`        (phase 1 — the player name goes "default")
    UC CLOSED → `ConnectionReal::Logout` on the VILLAGE transport → state **9** → on disconnect
                `FUN_10030ad0` case 4 takes the state-9 branch → `OnLoggedOut` → `HandleLoggedOut` →
                `SetState(VillageLeft=11)` → the +0x1c observer → **arms the referee**
Since the client never sends a second 2002, the stub must drive phase 2 itself — triggered by the UC
socket actually going away (`dispatch.on_conn_closed`).
ER: engagement_records/2026-07-26_leave-two-phase-worldloginack.md

Proves:
  1. 2002 → phase 1: exactly one WorldLoginAck(1006), and `_leave_phase` latched to 1.
  2. It is **never** answered with EnterWorld(1000) (clone regression guard).
  3. It never closes the connection (that was live-falsified — kicks both players at match start).
  4. UC close → phase 2: a second 1006 on the waiting village conn, `_leave_phase` → 2.
  5. Phase 2 only fires for a UC/chat close, only for a village conn that is actually waiting, and
     only for the SAME player.
  6. The in-world PingCode path and `send_enter_world` semantics are unaffected.

Run:  python tests/test_village_leave.py   (or: pytest tests/test_village_leave.py)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import config, dispatch, players, village  # noqa: E402


class FakeConn:
    def __init__(self, cid=8, is_village=False, is_chat=False, player=None):
        self.id = cid
        self.alive = True
        self.is_village = is_village
        self.is_chat = is_chat
        self.player = player
        self.raw = []            # raw TinCat frames via send_raw
        self.closes = []         # close_graceful() calls

    def send_raw(self, data):
        self.raw.append(data)

    def close_graceful(self, why=""):
        self.closes.append(why)


def _village(cid=8, player=None):
    return FakeConn(cid, is_village=True, player=player)


def _leave_fields():
    return {"msg_type": config.VILLAGE_LEAVE_REQUEST_MSGTYPE, "data": bytes.fromhex("affedead")}


def _ack_frame():
    return village.gamedata_frame(config.VILLAGE_MSG_WORLD_LOGIN_ACK, village.world_login_ack_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def _enter_world_frame():
    return village.gamedata_frame(config.VILLAGE_MSG_ENTER_WORLD, village.enter_world_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def test_1006_code_is_big_endian():
    """REGRESSION GUARD. The 1006 gate never fired in ANY session because the code scalar was written
    little-endian. TinCat's PropertyDataConverter serialises integers BIG-endian: the client's own 2002
    wrote WriteInt(0xAFFEDEAD,32) and it appeared on the wire as `af fe de ad` (captured byte-exact), and
    MEMORY.md independently records the ServerDataBlock roomId as a big-endian u32. If this flips back,
    HandleWorldLoginAck@0x0046ec50 reads 0xEFBEADDE, the `if (code == 0xDEADBEEF)` block is skipped, and
    BOTH Logout branches silently die - which is exactly the bug that cost us a day."""
    assert village.world_login_ack_body() == bytes.fromhex("deadbeef"), (
        f"1006 code must be big-endian de ad be ef, got {village.world_login_ack_body().hex(' ')}")


def test_phase1_answers_with_worldloginack():
    c = _village()
    c._enter_world_sent = True
    c._world_login_ack_sent = True                 # entry-time ack latched; force must bypass it
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert len(c.raw) == 1, f"2002 must be answered with exactly one 1006, got {len(c.raw)}"
    assert _ack_frame() in c.raw[0], "the answer must be the WorldLoginAck(1006) frame"
    assert c._leave_phase == 1, "the conn must latch _leave_phase=1 so phase 2 can find it"


def test_phase1_never_enterworld_and_never_closes():
    """Two regression guards at once: the 'clone' (answering with 1000) and the kick (closing)."""
    c = _village()
    c._enter_world_sent = True
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert _enter_world_frame() not in b"".join(c.raw), "2002 must NEVER be answered with EnterWorld(1000)"
    assert c.closes == [], "2002 must not close the connection (kicks both players at match start)"


def test_phase2_fires_when_the_uc_conn_closes():
    """The client sends 2002 only once, so the stub must drive phase 2 itself when UC goes away."""
    p = players.default_player()
    v = _village(cid=8, player=p)
    uc = FakeConn(cid=9, is_chat=True, player=p)
    dispatch.register_conn(v)
    dispatch.register_conn(uc)
    dispatch._h_send_game_data(v, _leave_fields(), 0)      # phase 1
    before = len(v.raw)
    uc.alive = False
    dispatch.on_conn_closed(uc)                            # UC socket gone → phase 2
    assert len(v.raw) == before + 1, "UC close must trigger a second 1006 on the village conn"
    assert _ack_frame() in v.raw[-1], "phase 2 must also be a WorldLoginAck(1006)"
    assert v._leave_phase == 2


def test_phase2_ignores_non_uc_closes_and_idle_conns():
    p = players.default_player()
    v = _village(cid=8, player=p)
    dispatch.register_conn(v)
    dispatch._h_send_game_data(v, _leave_fields(), 0)
    before = len(v.raw)
    other = FakeConn(cid=11, is_village=True, player=p)     # not a UC/chat conn
    dispatch.on_conn_closed(other)
    assert len(v.raw) == before, "only a UC/chat close may drive phase 2"

    idle = _village(cid=12, player=p)                        # never asked to leave
    dispatch.register_conn(idle)
    uc = FakeConn(cid=13, is_chat=True, player=p)
    dispatch.on_conn_closed(uc)
    assert idle.raw == [], "a village conn that never sent 2002 must not be sent a 1006"


def test_leave_on_non_village_conn_is_ignored():
    c = FakeConn(cid=8, is_village=False)
    dispatch._h_send_game_data(c, _leave_fields(), 0)
    assert c.raw == [] and c.closes == []


def test_pingcode_path_unaffected():
    c = _village()
    dispatch._h_send_game_data(c, {"msg_type": config.VILLAGE_PINGCODE_MSGTYPE, "data": b"\x00\x00\x00\x00"}, 0)
    assert len(c.raw) >= 1      # at least the Pong
    assert c.closes == []


def test_send_enter_world_force_semantics():
    c = _village()
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
