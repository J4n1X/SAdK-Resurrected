"""
Offline tests for the ambient village NPCs (sadk_lobby/npcs.py).

No live game, no sockets. Record NPCs ride PlayerCreate(1004) — layout pinned here
against the record reader FUN_0047b5c0 + LobbyMessage_ReadLocationBlock@0x0048f670 —
and walkers ride EntityCreate(1001) exactly like remote players. The walker math is
tested against the client interpolator's snap thresholds (>=10 units or >2.0 s gaps).

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


def _bits(data):
    return "".join(f"{b:08b}" for b in data)


# ── PlayerCreate(1004) wire layout ────────────────────────────────────────────
def test_player_create_bit_layout():
    body = village.player_create_body(
        0x01020304, "ab", pos=(0.0, 0.0, 0.0), rot_deg=90.0, zone=0,
        colours=(1, 2, 3, 4), npcidx=5, bdyprt=6, npctyp=1,
        actions=((4, "hi"),))
    b = _bits(body)
    off = 0

    def take(n):
        nonlocal off
        v = int(b[off:off + n], 2)
        off += n
        return v

    assert take(32) == 0x01020304    # id
    assert take(8) == 2              # npcdesc length
    assert take(8) == ord("a")
    assert take(8) == ord("b")
    assert take(11) == 1024          # posx — world centre
    assert take(11) == 512           # posy — ground
    assert take(11) == 1024          # posz
    assert take(7) == 32             # rot — 90 degrees
    assert take(4) == 0              # zone (no ghost-zone in this block)
    assert take(4) == 1              # hrclr   — 4-bit NIBBLES, not bytes
    assert take(4) == 2              # sknclr
    assert take(4) == 3              # shrtclr
    assert take(4) == 4              # trsrclr
    assert take(4) == 5              # npcidx
    assert take(4) == 6              # bdyprt
    assert take(2) == 1              # npctyp — settler person
    assert take(8) == 1              # actcnt
    assert take(8) == 4              # act — bow
    assert take(8) == 2              # actChat length
    assert take(8) == ord("h")
    assert take(8) == ord("i")
    # Nothing after the last action but zero padding to the byte boundary.
    assert off <= len(b) < off + 8
    assert all(bit == "0" for bit in b[off:])


def test_player_create_no_actions_is_actcnt_zero():
    body = village.player_create_body(7, "x", npctyp=2)
    b = _bits(body)
    # id 32 + npcdesc(8+8) + loc 44 + colours 16 + npcidx 4 + bdyprt 4 = 116, then
    # npctyp 2 @ 116, actcnt 8 @ 118.
    assert int(b[116:118], 2) == 2   # npctyp — letterbox
    assert int(b[118:126], 2) == 0   # actcnt


# ── The cast ──────────────────────────────────────────────────────────────────
def test_npc_ids_are_unique_and_far_above_player_perm_ids():
    cast = _cast()
    ids = [n.perm_id for n in cast]
    assert len(ids) == len(set(ids)), "duplicate NPC ids"
    assert all(i >= npcs.NPC_ID_BASE for i in ids)
    assert npcs.NPC_ID_BASE >= 1_000_000


def test_cast_split_covers_everyone():
    cast = _cast()
    records, walkers = npcs.record_npcs(cast), npcs.walker_npcs(cast)
    assert records and walkers
    assert len(records) + len(walkers) == len(cast)
    assert all(n.npctyp in (1, 2) for n in records)
    assert all(n.npctyp is None for n in walkers)


def test_record_npc_actions_are_valid_lobby_actions():
    # The v2 bug: emote ids were sent as `act`, and 2..6 all map to MinigameMatchmaking, so
    # every NPC opened the minigame dialog. Pin the real enum (FUN_004325b0) and assert no NPC
    # lands in the minigame band unless it is meant to.
    valid = {npcs.ACT_NONE, npcs.ACT_HAIRCOLOR, npcs.ACT_MINIGAME, npcs.ACT_MAILBOX,
             npcs.ACT_HOST_GAME, npcs.ACT_LIST_GAMES, npcs.ACT_HALL_OF_FAME,
             npcs.ACT_OPEN_SHOP}
    minigame_npcs = set()
    for npc in npcs.record_npcs(_cast()):
        for act, _text in npc.actions:
            assert act in valid, f"{npc.name}: act {act} is not a known LobbyAction"
            if 2 <= act <= 6:
                minigame_npcs.add(npc.name)
    assert minigame_npcs == {"Spielmeister Silas"}, \
        f"only the minigame master should open matchmaking, got {minigame_npcs}"


def test_record_npcs_have_distinct_model_indices():
    # npcidx IS the model selector for type-2 NPCProxy objects; identical values are why the
    # first cast all looked the same.
    persons = [n for n in npcs.record_npcs(_cast()) if n.npctyp == npcs.NPCTYP_SETTLER]
    idxs = [n.npcidx for n in persons]
    assert len(idxs) == len(set(idxs)), f"duplicate npcidx across settler NPCs: {idxs}"


def test_walkers_have_distinct_trbgndr_nibbles():
    # trbgndr 0 on everyone == body part 0 / gender 0 == the identical default avatar.
    walkers = npcs.walker_npcs(_cast())
    assert len({n.tribe_gender for n in walkers}) == len(walkers), "walkers share a trbgndr"
    for npc in walkers:
        assert (npc.tribe_gender >> 4) < 3, "body part must be < 3 or the model math clamps"
        assert 0 <= npc.tribe_gender <= 0xFF


def test_record_npcs_encode_and_fit_the_nibble_fields():
    for npc in npcs.record_npcs(_cast()):
        kwargs = npc.record_kwargs()
        assert all(0 <= c <= 15 for c in kwargs["colours"]), "1004 colours are nibbles"
        assert 0 <= kwargs["npcidx"] <= 15 and 0 <= kwargs["bdyprt"] <= 15
        assert len(kwargs["actions"]) <= 3, "the record stores at most 3 action slots"
        body = village.player_create_body(npc.perm_id, npc.name, **kwargs)
        assert body[:4] == npc.perm_id.to_bytes(4, "big")
        assert npc.name.encode("iso-8859-15", "strict"), "name not encodable"
        for _act, line in kwargs["actions"]:
            assert line.encode("iso-8859-15", "strict"), "actChat not encodable"


def test_walkers_encode_through_the_avatar_style_block():
    for npc in npcs.walker_npcs(_cast()):
        body = village.entity_create_body(npc.perm_id, style=npc.style(), **npc.pose())
        assert body[:4] == npc.perm_id.to_bytes(4, "big")
        assert (body[4] >> 4) == 3          # dtblcks == location | style
        pose = npc.pose()
        assert pose["zone"] == 0 and pose["ghost_zone"] == 15


# ── Walker math vs the client interpolator ────────────────────────────────────
def test_walkers_step_below_the_snap_threshold():
    cast = npcs.walker_npcs(_cast())
    assert cast, "expected at least one walking NPC"
    for npc in cast:
        prev = npc.pose()["pos"]
        for _ in range(50):
            npc.advance(1.0)
            cur = npc.pose()["pos"]
            step = math.dist(prev, cur)
            assert step < 5.0, f"{npc.name}: {step:.2f} units in one tick (snap risk)"
            prev = cur


def test_walkers_stay_near_the_square_and_records_hold_still():
    cx, cy, cz = CENTER
    for npc in npcs.walker_npcs(_cast()):
        for _ in range(600):                  # 10 simulated minutes
            npc.advance(1.0)
            x, y, z = npc.pose()["pos"]
            assert y == cy, "walkers keep the proven ground height"
            assert abs(x - cx) < 20 and abs(z - cz) < 20, \
                f"{npc.name} wandered off the square: {(x, z)}"
    for npc in npcs.record_npcs(_cast()):
        before = npc.anchor
        npc.advance(1.0)
        assert npc.anchor == before


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
