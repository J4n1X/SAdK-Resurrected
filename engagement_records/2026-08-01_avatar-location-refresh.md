# Engagement Record — stream periodic avatar location refreshes (the movement waypoint ring)

**Date:** 2026-08-01 · **Status:** PROPOSED, awaiting approval · **Type:** stub wire change
(new periodic traffic; message shape unchanged)

## Why — the vanish mechanism, proven by TTD trace `avatar_vanish_diag.run`

After the spawn-position fix the avatar appeared **for exactly one frame** and vanished. The trace
names the mechanism precisely:

- The remote avatar's visual was created correctly (position (-31.2, 2.71, 14.21) verbatim from our
  wire values) and was **never destroyed** — its vtable shows only the two construction writes.
- Its CLobbyObj position was then **overwritten with (0,0,0) every frame** by IP `0x0051a155` —
  inside `FUN_00519d50`, the visual's per-frame **movement interpolator** (vtbl+4). It positions
  the avatar exclusively from an 8-slot ring of timestamped WAYPOINTS; with an empty ring it snaps
  to zeroed slots. 17 zeroing events in the trace — one per frame.
- The ring is fed ONLY by `FUN_00519b20` (waypoint push), reached ONLY via
  `CLobbyClient_UpdateAvatar`'s **update** path — i.e. by a **repeat 1001** for an id that already
  has its world object. The create path never pushes a waypoint.
- Each waypoint is stamped `time + 2000 ms` ("walk there over 2 s"); pushes with pos ≈ (0,0,0) are
  **rejected** (the engine's own invalid sentinel).
- Timebase: the wire `tick` is 16 bits; `AvatarProxy_ReadLocationBlock@0x004824b0` expands it via
  `FUN_004f4d10` = **nearest-anchor reconstruction against the client's own local ms clock**
  (observed running at ~0xd67c4 in-trace). No server/client clock sync is required — only that our
  ticks advance like real milliseconds.

⇒ **The real protocol streams location updates.** This is not a workaround; the client's movement
system is built around a waypoint stream, and the maintainer predicted exactly this ("maybe
movement packets are important").

## What changes

- `village.send_entity_create` gains `quiet=` (refresh spam stays out of the log; the ticker logs
  its own presence and a 1-in-30-cycle summary line — the wire artifact record stays honest).
- `dispatch.py`: a daemon ticker (started lazily on first world entry) sends, every **1.0 s**, a
  location-only `EntityCreate(1001)` per (in-world client × other in-world player) with
  `tick = int(monotonic()*1000) & 0xFFFF` and the same `_spawn_spot` position (constant → the
  avatar stands still). Initial spawn frames now also carry a real tick.
- Per-connection send locks (`connection.py send_raw`) make cross-thread sends safe — the same
  pattern the mutual-spawn path already uses.

## Expected result

Both settlers remain visible indefinitely, standing at their ring spots. Positions are constant
until we reverse the client→server movement report (the next frontier — then the same refresh
stream carries real positions and avatars will *walk*).

## Harness compliance

- Real mechanism, real data: we feed the client's own movement system what the original server fed
  it. Nothing is forced or patched.
- No flag-gating: the ticker is default behaviour.
- Reversible: one thread + one call site.

## Result — trace `avatar_refresh_diag2.run` (01:52), **THE MECHANISM WORKS, TTD-PROVEN END-TO-END**

First live test (01:39) was reported "no cigar — same behavior". A 60 s recording with the stream
flowing (both clients idle in-world) showed why that report and the mechanism are BOTH right:

- **81 refreshes arrived → 81 `UpdateAvatar` update-path runs → 81 waypoint pushes.** 1:1:1.
- The ring read back **perfect**: all 8 slots = the correct spot (-31.2, 2.71, 14.21), identity
  rotation, stamps exactly ~1001 ms apart, ring index advancing, interp-mode flag = 1.
- The interpolator (`FUN_00519d50`), at client clock `0x2eb77a`, **wrote (-31.2, 2.71, 14.21) into
  the avatar's world object** — the correct position, out of real bracket interpolation.

⇒ With the stream running, the remote settler stands at the square. What the maintainer saw at
01:39 was the **spawn window**: the create paints one frame, the ring needs ~2-3 s to produce a
bracket (first refresh up to 1 s away, stamps land +2000 ms in the future), and during that window
the interpolator snaps to empty-slot zeros. Appear → vanish → (unwatched) reappear and stay.

### Addendum (same mechanism, timing refinement): ring priming at spawn

Immediately after the styled create, send two quiet location refreshes stamped `tick-2000` and
`tick`. Client-side these become waypoints at ≈now and ≈now+2000 — a valid bracket from the first
tick, eliminating the flicker window entirely. Implemented in `_spawn_world_avatars`; the 1 Hz
ticker then takes over seamlessly.
