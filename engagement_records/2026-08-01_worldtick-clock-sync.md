# Engagement Record — WorldTick(1005) world-clock sync (root cause of the avatar die-off)

**Date:** 2026-08-01 (day session) · **Status:** IMPLEMENTED, awaiting live confirmation ·
**Type:** stub wire change (new periodic message 1005; the location stream itself is unchanged)

## The open question this closes

ER `2026-08-01_avatar-location-refresh.md` ended with: the 1 Hz refresh stream is proven sent and
proven to land (81/81 under TTD slowdown), yet at full speed the avatar dies at exactly the 3.0 s
staleness threshold, with an unexplained PC-vs-VM lifetime asymmetry. TTD is structurally blind to
the healthy state, so this was chased statically.

## The model — [PROVEN], every link named in Ghidra + SOURCEMAP

1. **The client has a world clock**: `WorldClock_GetMs@0x0057b8d0` = `g_dwWorldClock_RawMs −
   g_dwWorldClock_Offset` (raw per-frame timer sample minus an offset; starts at ~0 after
   `WorldClock_Reset@0x0057b990`).
2. **The server's tick stream is its timebase.** Village msg **1005 (WorldTick)** →
   `HandleWorldTick@0x0046f620` reads a **64-bit** field `"tick"` (reader vtbl+0x20 = 64 BITS —
   the old "64-byte MEMBLOCK" reading of the 0x40 argument was wrong) and fires conn notify list
   `+0x11c` → `CLobbyClient_OnWorldTick_Throttled@0x00503590` (18th of the birth-subscribed
   observers) → `WorldClock_SlewToTick16@0x0057b910(tick & 0xFFFF, 250)`: if the clock's phase
   differs from the wire tick by ≥250 ms (shorter direction mod 65536), the offset is adjusted so
   `GetMs() & 0xFFFF == tick` exactly. Sole caller; sole writer of the offset besides Reset.
3. **Everything movement hangs off that clock**:
   - `WorldClock_ReconstructTick16@0x004f4d10` expands every avatar-location `tick16` to the u64
     value **nearest `GetMs()`** (±32.7 s window) — waypoint stamp = that + 2000 ms.
   - `AvatarMovement_Tick@0x00519d50`'s time parameter **is `GetMs()`** — trace-proven
     (`avatar_refresh_diag2.run`, position 10DF60:15A5: param u64 = 0x2ea49a =
     `g_dwWorldClock_RawMs − g_dwWorldClock_Offset` read at the same position).
4. **Visibility spec** (completes yesterday's picture; all constants read from the binary):
   bracket search over the 7 *adjacent* ring pairs, `prev < t <= next`. Bracket ⇒ **visible**
   (smooth interp unless waypoint gap > 2.0 s `DAT_007d435c`, distance ≥ 10.0 `DAT_007fa8d8`, or
   prev pos null — those snap to the bracket's next waypoint, still visible). No bracket ⇒ snap to
   newest slot and **hide iff `t − newest > 3.0 s`** (`DAT_007d4360`; u64 math, so future-only
   stamps underflow = instantly hidden). `AvatarMovement_PushWaypoint@0x00519b20` has NO dedup and
   NO monotonicity guard — only the null-position reject.

## Why the stub's stream failed at full speed

The stub never sends 1005. The client clock therefore free-runs from its reset epoch, and the
phase between our `monotonic()`-derived tick16s and that clock is **arbitrary per machine/boot**
(uniform over ±32.7 s). Depending on that phase, our waypoint stamps land far in the past
(> 3.0 s stale ⇒ hidden) or far in the future (underflow ⇒ hidden); the brief spawn-window
visibility came from brackets formed against the primed/zero-stamped ring slots, dying as real
pushes overwrote them. This explains **round 2, round 3 AND the PC-vs-VM asymmetry** (different
machines = different phases) without any additional mechanism. The recorder couldn't see it
because slowdown forces the stale path regardless.

## The wire change

- `village.world_tick_body(tick_ms)` → **8 raw big-endian bytes** (positional 64-bit scalar, no
  length prefix), **high dword forced to 0**: `LobbyMessage_ReadBitsCore@0x0048f050` has a shipped
  engine bug (32-bit `SHL` with x86's CL&0x1f masking + `CDQ`) that aliases the two halves of a
  >32-bit read into the low dword — a non-zero high dword would corrupt the value. Verified
  against the disassembly.
- `village.send_world_tick(conn, tick_ms)` — tick from **the same clock as the location ticks**
  (`dispatch._now_ms` = `int(monotonic()*1000)`), so the slew locks the client to our timebase.
- `dispatch.py`: 1005 sent (a) to all in-world conns **before** the spawn priming — waypoint
  stamps are absolute u64s cut at parse time and are NOT re-anchored by a later slew, so sync must
  come first; (b) every 1 Hz ticker cycle (client-side no-op after the first slew, 250 ms
  tolerance). The location stream itself (1 Hz, tick−1000, priming pair) is unchanged — with the
  phase locked, stamps land ≈now+1000 and brackets sustain indefinitely.

## Harness compliance

- Genuine mechanism: the client carries a dedicated handler + slew function for exactly this
  message; the real server necessarily streamed it (nothing else calls the slew). Nothing forced,
  no flags; default behaviour.
- Expected observable: both settlers visible **indefinitely** (no 3 s die-off), on PC and VM
  alike. Failure observable: unchanged die-off ⇒ the slew didn't land — check the client's
  LobbyComm.log and re-verify the 1005 body against `HandleWorldTick`.
- Tests pass (`test_codec_golden`, `test_server_smoke`, `test_multi_client`).

## Independent review (2026-08-01, separate agent, read-only re-derivation)

All six claims **CONFIRMED** from the binary, including the 1000–1006 jump table at 0x00470d34
(`HandleMessage` is 0x00470a90 on this base) routing 1005 → 0x0046f620, the names=0 no-trailer
FinishRead path, and the absence of any state gate between dispatch and the `+0x11c` fire. Two
additions:
- Reader-bug refinement: the CDQ sign-smear also fires on **bit 31 of the low dword** (remaining
  count 31), so the parsed HIGH dword is garbage whenever wire-low-bit31 is set — harmless here
  (only the low 16 bits are consumed; the low dword itself always parses exactly when the wire
  high dword is 0).
- ⚠️ Operational: **`WorldClock_Reset@0x0057b990` is also called from world-load finalization**
  (`FUN_005273d0`, "!Finalizing world", flag `DAT_0088a614`) — a reset there wipes any slew done
  earlier and invalidates already-stamped waypoints. The 1 Hz 1005 stream re-slews within one
  cycle (post-reset error ≥250 ms), so this self-heals; a spawn burst racing finalization could
  still show a ~1–2 s hidden window. Keep in mind when reading live timing.

## Status

- Model: **[PROVEN]** (static chain complete + trace-proven clock identity + independent
  re-derivation).
- Stub change: implemented; **[TODO]** live confirmation (next play session).
- Loose ends carried forward: `FUN_00510af0`/`FUN_00510c80` interpolator internals (not needed for
  the fix), own-path z-sign cosmetic oddity, stationary-avatar cadence of the real server (any
  cadence ≤ ~64 s now works in principle; 1 Hz is safely inside it).
