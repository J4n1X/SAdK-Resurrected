"""
Offline tests for the in-world presence wire format (EntityCreate 1001).

No live game, no sockets. These pin the BIT-PACKED encoding derived statically in
docs/IN_WORLD_PRESENCE.md, so a future refactor cannot silently change it:

  1. The bit writer is MSB-first big-endian (a 32-bit field == 4 big-endian bytes).
  2. Non-byte-aligned widths pack correctly and the tail is zero-padded.
  3. Position quantisation round-trips through the real world bounds.
  4. EntityCreate(1001) is exactly 102 bits / 13 bytes with dtblcks=1, and every
     field lands at the bit offset the client reads it from.

Run directly:   python tests/test_world_presence.py
Or with pytest: pytest tests/test_world_presence.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import village  # noqa: E402


def _bits(data):
    """Render bytes as an MSB-first bit string — the order FUN_0048f0d0 consumes them."""
    return "".join(f"{b:08b}" for b in data)


# ── 1. MSB-first packing ──────────────────────────────────────────────────────
def test_u32_is_big_endian():
    w = village.BitWriter()
    w.write(0xDEADBEEF, 32)
    assert w.bytes() == bytes.fromhex("deadbeef"), (
        "a 32-bit field must be 4 BIG-endian bytes — FUN_0048f0d0 assembles values MSB-first. "
        "This is the same convention that made the referee PermID work.")


def test_unaligned_packing_and_zero_pad():
    w = village.BitWriter()
    w.write(0b101, 3)
    w.write(0b11110000, 8)
    assert _bits(w.bytes()) == "10111110" + "000" + "00000"   # 11 bits + zero pad
    assert len(w.bytes()) == 2


# ── 2. Quantisation against the real world bounds ─────────────────────────────
def test_quantise_axis_round_trip():
    # bounds read from the binary: x/z -150..150, y -10..30; 2048 steps (11 bits)
    assert village.quantise_axis(-150.0, "x") == 0
    assert village.quantise_axis(0.0, "x") == 1024          # world centre
    assert village.quantise_axis(0.0, "y") == 512           # ground level
    assert village.quantise_axis(0.0, "z") == 1024
    for axis in ("x", "y", "z"):
        lo, hi = village.WORLD_BOUNDS[axis]
        for val in (lo, (lo + hi) / 2, hi - 0.1):
            q = village.quantise_axis(val, axis)
            assert 0 <= q < village.POS_STEPS
            back = q / village.POS_STEPS * (hi - lo) + lo
            assert abs(back - val) <= (hi - lo) / village.POS_STEPS + 1e-6


def test_quantise_rot_is_128_steps():
    assert village.quantise_rot(0) == 0
    assert village.quantise_rot(90) == 32
    assert village.quantise_rot(180) == 64
    assert village.quantise_rot(270) == 96
    assert village.quantise_rot(360) == 0                   # wraps


# ── 3. EntityCreate(1001) layout ──────────────────────────────────────────────
def test_entity_create_field_offsets():
    body = village.entity_create_body(4242, pos=(0.0, 0.0, 0.0), rot_deg=90.0, tick=7)
    # 32 + 4 + 16 + 11 + 11 + 11 + 7 + 4 + 4 + 1 + 1 = 102 bits -> 13 bytes
    assert len(body) == 13, f"expected 13 bytes, got {len(body)}"
    b = _bits(body)
    off = 0

    def take(n):
        nonlocal off
        v = int(b[off:off + n], 2)
        off += n
        return v

    assert take(32) == 4242          # id      — peeked by HandleEntityCreate
    assert take(4) == 1              # dtblcks — AvatarLocation block only
    assert take(16) == 7             # tick
    assert take(11) == 1024          # posx    — world centre
    assert take(11) == 512           # posy    — ground
    assert take(11) == 1024          # posz
    assert take(7) == 32             # rot     — 90 degrees
    assert take(4) == 0              # zone
    assert take(4) == 0              # ghstzne
    assert take(1) == 0              # rnng
    assert take(1) == 0              # jmp
    assert off == 102


def test_entity_create_id_is_first_four_bytes():
    # HandleEntityCreate peeks "id" as 32 bits before anything else, so it must be the leading
    # big-endian dword or the client logs "Can't peek AvatarID".
    body = village.entity_create_body(0x01020304)
    assert body[:4] == bytes.fromhex("01020304")


# ── 3b. AvatarStyle block (dtblcks bit1) — written, NOT yet sent ─────────────
def test_default_spawn_is_unchanged_by_the_style_option():
    # The live experiment is "does dtblcks=1 alone render?". Adding the style writer must not
    # perturb the default body by a single bit, or that experiment silently changes meaning.
    body = village.entity_create_body(0x11223344, pos=(0.0, 0.0, 0.0))
    assert len(body) == 13                                   # 102 bits -> 13 bytes
    assert _bits(body)[32:36] == "0001"                      # dtblcks == 1, location only


def test_style_sets_dtblcks_bit1_and_appends_after_location():
    style = {"name": "ab", "tribe_gender": 0x12,
             "colours": (1, 2, 3, 4, 5, 6, 7, 8)}
    body = village.entity_create_body(0x11223344, style=style)
    bits = _bits(body)
    assert bits[32:36] == "0011"                             # dtblcks == 3 (location | style)
    # The style block starts right after the 102-bit location body, with no re-alignment.
    tail = bits[102:]
    assert int(tail[0:8], 2) == 2                            # name length
    assert int(tail[8:16], 2) == ord("a")
    assert int(tail[16:24], 2) == ord("b")
    assert int(tail[24:32], 2) == 0x12                       # trbgndr
    for i, expected in enumerate((1, 2, 3, 4, 5, 6, 7, 8)):  # hrclr..addColor4, byte-wide
        assert int(tail[32 + i * 8:40 + i * 8], 2) == expected


def test_style_colours_are_zero_filled_when_short():
    body = village.entity_create_body(1, style={"name": "", "colours": (9,)})
    tail = _bits(body)[102:]
    assert int(tail[0:8], 2) == 0                            # empty name
    assert int(tail[8:16], 2) == 0                           # trbgndr default
    assert int(tail[16:24], 2) == 9                          # hrclr
    assert int(tail[24:32], 2) == 0                          # sknclr zero-filled


# ── 4. String encoding (used by PlayerCreate npcdesc / actChat) ───────────────
def test_write_string_is_len8_plus_chars():
    w = village.BitWriter()
    w.write_string("ab")
    assert w.bytes() == bytes([2, ord("a"), ord("b")])       # 8-bit len, then 8-bit chars
    empty = village.BitWriter()
    empty.write_string("")
    assert empty.bytes() == bytes([0])


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
    print("All world-presence tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
