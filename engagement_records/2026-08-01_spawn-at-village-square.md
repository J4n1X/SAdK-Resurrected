# Engagement Record — move remote-avatar spawn positions to the village square

**Date:** 2026-08-01 · **Status:** PROPOSED, awaiting approval · **Type:** stub wire change
(field values only; message shape unchanged)

## Why — evidence, not a guess

TTD trace `avatar_spawn_diag.run` (see `2026-07-31_ttd-single-client-spawn-diagnostic.md`) proved
the entire EntityCreate chain works: the remote avatar is created, modelled and styled — at
**(0, 0, 6)**, our world-origin ring, while the observing player's own avatar provably spawns at
**(-31.24, 2.71, +8.28)** (visual-ctor argument read from the trace; x/y equal the binary's
default-spawn constants `DAT_007dd028/2c`). The remote settler stands ~31 units away and ~2.7 units
below the square's ground level. The wire position pipeline is proven **pass-through** (sent (0,0,6)
→ ctor received (0,0,6)), so the wire value is the single knob that decides where the avatar stands.

## What changes

`dispatch.py`: `_spawn_spot` keeps its deterministic per-`perm_id` ring (radius
`config.AVATAR_SPAWN_SPREAD` = 6.0) but centers it on the new constant
`VILLAGE_SPAWN_POINT = (-31.24, 2.71, 8.28)` instead of (0,0,0). y = 2.71 puts avatars at the
square's proven ground height. The constant lives in `dispatch.py`, NOT `config.py`, because the
deploy server's `config.py` is local-only and must never be overwritten.

No message-shape change: same `EntityCreate(1001)`, `dtblcks = location|style`, same encoder.

## Expected result

Both clients see each other's settler standing on the village square next to their own avatar.
Residual risks, accepted: the z-sign question on the OWN path (static default −8.28 vs observed
+8.28) does not affect us (remote path proven pass-through, we use the observed value); if 6.0 ring
radius clips into a building, the avatar may be partially occluded — cosmetic, tune later.

## Harness compliance

- Real data via the real message; nothing forced. The values are corrected to the binary's own
  proven spawn location.
- No flag-gating: this replaces the wrong default with the right one.
- Reversible: one constant + one function.

## Result

_(pending live test)_
