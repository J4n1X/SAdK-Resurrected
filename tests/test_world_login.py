"""
Match-start world-login answer tests (s42) — the ANSWER_WORLD_LOGIN_REQUEST fix. No live game, no sockets.

Background: at MATCH start the client RE-SENDS SendGameData(74){msg_type=0x27D2, code=0xAFFEDEAD} on its
EXISTING village conn and waits for EnterWorld(1000). The stub's send_enter_world is one-shot per conn
(_enter_world_sent), already fired by the lobby-entry timer push → it NO-OPS at match-start → the request goes
unanswered → ~80s timeout (live 2026-06-10). The fix answers each 0x27D2 with a fresh 1000 (force=True),
behind config.ANSWER_WORLD_LOGIN_REQUEST. Model + binary review: docs/MATCH_WORLD_LOGIN.md,
engagement_records/2026-06-10_match-world-login.md.

Proves:
  1. Flag OFF (safe baseline): a 0x27D2 on an already-entered conn is a NO-OP — byte-identical to the prior
     one-shot behavior (the bug, deliberately preserved when disarmed).
  2. Flag ON (the fix): the SAME conn is answered with a fresh EnterWorld(1000) in a SendGameData(74) envelope
     (force=True bypasses the latch). The frame is the exact lobby-entry 1000 frame (Worldname display-only).
  3. send_enter_world(force=) semantics: force=False is one-shot; force=True re-sends past the latch.
  4. Ping-pong guard (reviewer risk #3): repeated 0x27D2 are answered up to WORLD_LOGIN_MAX_ANSWERS, then capped.
  5. The in-world PingCode path is unaffected by the flag.

Run:  python tests/test_world_login.py   (or: pytest tests/test_world_login.py)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import config, dispatch, village  # noqa: E402


class FakeVillageConn:
    def __init__(self, cid=8):
        self.id = cid
        self.alive = True
        self.is_village = True
        self.raw = []           # raw TinCat frames via send_raw

    def send_raw(self, data):
        self.raw.append(data)


def _world_login_fields():
    # SendGameData(74) inner: msg_type=0x27D2, data field "code"=0xAFFEDEAD (wire bytes af fe de ad).
    return {"msg_type": config.WORLD_LOGIN_REQUEST_MSGTYPE, "data": bytes.fromhex("affedead")}


def _expected_1000_frame():
    # The app payload village.send_enter_world emits (deterministic): SendGameData(74){1000, enter_world_body}.
    return village.gamedata_frame(config.VILLAGE_MSG_ENTER_WORLD, village.enter_world_body(),
                                  config.VILLAGE_PAYLOAD_MAGIC)


def test_off_is_noop_when_already_entered():
    """Flag OFF: a match-start 0x27D2 on a conn that already got its lobby-entry 1000 (latch set) sends NOTHING
    — exactly the prior behavior we do NOT change when disarmed (the live 80s-timeout bug)."""
    saved = config.ANSWER_WORLD_LOGIN_REQUEST
    try:
        config.ANSWER_WORLD_LOGIN_REQUEST = False
        c = FakeVillageConn()
        c._enter_world_sent = True                 # lobby-entry timer push already fired
        dispatch._h_send_game_data(c, _world_login_fields(), 0)
        assert c.raw == [], "flag OFF must not answer the match-start 0x27D2 (byte-identical to prior no-op)"
    finally:
        config.ANSWER_WORLD_LOGIN_REQUEST = saved


def test_on_answers_with_enterworld_1000():
    """Flag ON: the SAME already-entered conn IS answered with a fresh EnterWorld(1000), force-bypassing the
    one-shot latch. The emitted frame is the exact lobby-entry 1000 envelope (no special match-map name)."""
    saved = config.ANSWER_WORLD_LOGIN_REQUEST
    try:
        config.ANSWER_WORLD_LOGIN_REQUEST = True
        c = FakeVillageConn()
        c._enter_world_sent = True
        dispatch._h_send_game_data(c, _world_login_fields(), 0)
        assert len(c.raw) == 1, "flag ON must answer the match-start 0x27D2 with one 1000"
        assert _expected_1000_frame() in c.raw[0], "the answer must be the EnterWorld(1000) SendGameData(74) frame"
        assert c._world_login_answers == 1
    finally:
        config.ANSWER_WORLD_LOGIN_REQUEST = saved


def test_send_enter_world_force_semantics():
    """Unit: force=False is one-shot (latch); force=True re-sends past the latch — without touching dispatch."""
    c = FakeVillageConn()
    village.send_enter_world(c)                     # first push (force=False) → sends, latches
    assert len(c.raw) == 1 and c._enter_world_sent is True
    village.send_enter_world(c)                     # force=False again → no-op (latched)
    assert len(c.raw) == 1
    village.send_enter_world(c, force=True)         # force=True → re-sends past the latch
    assert len(c.raw) == 2


def test_pingpong_cap():
    """Reviewer risk #3: repeated 0x27D2 are answered up to WORLD_LOGIN_MAX_ANSWERS, then the cap stops
    answering (a visible resend-loop guard — never a silent flood)."""
    saved = config.ANSWER_WORLD_LOGIN_REQUEST
    try:
        config.ANSWER_WORLD_LOGIN_REQUEST = True
        c = FakeVillageConn()
        for _ in range(config.WORLD_LOGIN_MAX_ANSWERS + 3):
            dispatch._h_send_game_data(c, _world_login_fields(), 0)
        assert len(c.raw) == config.WORLD_LOGIN_MAX_ANSWERS, (
            f"answered {len(c.raw)} times; cap is {config.WORLD_LOGIN_MAX_ANSWERS}")
        # the counter keeps counting past the cap (so the WARNING shows the true resend depth)
        assert c._world_login_answers == config.WORLD_LOGIN_MAX_ANSWERS + 3
    finally:
        config.ANSWER_WORLD_LOGIN_REQUEST = saved


def test_pingcode_path_unaffected():
    """A 0x2ED6 PingCode still answers Pong (+ once 1006) regardless of the new flag — no regression to the
    in-world keepalive path."""
    c = FakeVillageConn()
    dispatch._h_send_game_data(c, {"msg_type": config.VILLAGE_PINGCODE_MSGTYPE, "data": b"\x00\x00\x00\x00"}, 0)
    assert len(c.raw) >= 1     # at least the Pong


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
    print(f"{failures} test(s) FAILED" if failures else "All world-login tests PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
