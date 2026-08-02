"""
Offline tests for the ambient village NPCs (sadk_lobby/npcs.py).

No live game, no sockets. NPCs are ordinary EntityCreate(1001) avatars with synthetic
ids, so these tests pin (1) the id-space separation from real players, (2) the walker
math against the client interpolator's snap thresholds (>=10 units or >2.0 s gaps
snap instead of walking — AvatarMovement_Tick), and (3) that every NPC style encodes
cleanly through the bit-packed style block, umlauts included (ISO-8859-15 wire chars).

Run directly:   python tests/test_npcs.py
Or with pytest: pytest tests/test_npcs.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import npcs, village  # noqa: E402

CENTER = (-31.24, 2.71, 8.28)         # dispatch.VILLAGE_SPAWN_POINT


def _cast():
    return npcs.make_village_npcs(CENTER)


def test_npc_ids_are_unique_and_far_above_player_perm_ids():
    cast = _cast()
    ids = [n.perm_id for n in cast]
    assert len(ids) == len(set(ids)), "duplicate NPC ids"
    assert all(i >= npcs.NPC_ID_BASE for i in ids)
    # players.py hands out perm_ids sequentially from 1; a million players in one
    # stub session is not a thing, so the spaces can never meet.
    assert npcs.NPC_ID_BASE >= 1_000_000


def test_static_npcs_hold_position():
    cast = [n for n in _cast() if not n.path]
    assert cast, "expected at least one static NPC"
    for npc in cast:
        before = npc.pose()
        npc.advance(1.0)
        assert npc.pose()["pos"] == before["pos"]
        assert npc.pose()["rot_deg"] == before["rot_deg"]


def test_walkers_step_below_the_snap_threshold():
    # The client interpolator snaps (teleports) at >=10 units between waypoints; a
    # walker must stay far below that per 1 s ticker step or it will jitter-teleport.
    cast = [n for n in _cast() if n.path]
    assert cast, "expected at least one walking NPC"
    for npc in cast:
        prev = npc.pose()["pos"]
        for _ in range(50):
            npc.advance(1.0)
            cur = npc.pose()["pos"]
            step = math.dist(prev, cur)
            assert step < 5.0, f"{npc.name}: {step:.2f} units in one tick (snap risk)"
            prev = cur


def test_walkers_stay_near_the_square_and_loop():
    cx, cy, cz = CENTER
    for npc in [n for n in _cast() if n.path]:
        for _ in range(600):                      # 10 simulated minutes
            npc.advance(1.0)
            x, y, z = npc.pose()["pos"]
            assert y == cy, "walkers keep the proven ground height"
            assert abs(x - cx) < 20 and abs(z - cz) < 20, \
                f"{npc.name} wandered off the square: {(x, z)}"


def test_every_npc_encodes_through_the_style_block():
    for npc in _cast():
        body = village.entity_create_body(npc.perm_id, style=npc.style(),
                                          **{k: v for k, v in npc.pose().items()})
        # id is the leading big-endian dword (peeked by HandleEntityCreate).
        assert body[:4] == npc.perm_id.to_bytes(4, "big")
        # dtblcks (bits 32..35) must be 3: location | style.
        assert (body[4] >> 4) == 3
        # The name must survive the 8-bit ISO-8859-15 wire chars — umlauts included.
        assert npc.name.encode("iso-8859-15", "strict"), "name not encodable"


def test_pose_uses_outdoor_zone_values():
    for npc in _cast():
        pose = npc.pose()
        assert pose["zone"] == 0, "NPCs stand on the square (zone 0)"
        assert pose["ghost_zone"] == 15, "15 is the neutral no-ghost-zone sentinel"


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
    if failures:
        print(f"{failures} test(s) FAILED")
        return 1
    print("All NPC tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
