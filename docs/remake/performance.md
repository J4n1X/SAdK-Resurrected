# Remake: performance — budgets, the original's techniques, what the remake does

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). How fast the remake has to be, how that
is measured, and every technique the original uses to save CPU, GPU, memory or load time, with what the remake does
with each one: keep it exactly, adopt the idea with modern means, leave it to Godot, or drop it. Rendering details are
in [renderer.md](renderer.md), the simulation interface in [sim-boundary.md](sim-boundary.md).

Tags: **[binding]**, **[draft]**, and the source tags of the cited documents (sections of `../sim/*.md`);
**[measured]** = counted with the testbed viewer on 2026-10-15 (the viewer's map half is retired, so new map measurements use `core.game.mapview` with `stats=true`, or `tools.mapviewer`; Compatibility renderer under a virtual display on the
Linux box: draw calls and triangles are real, times are not). Short names: R = `../sim/rendering.md`, WO =
`../sim/world-objects-rendering.md`, P = `../sim/particles.md`, AM = `../sim/animation-models.md`, LC =
`../sim/logic-core.md`, MR = `../sim/map-resources.md`, ST = `../sim/streets-transport.md`, AI = `../sim/ai-player.md`,
AU = `../sim/audio.md`, PV = `../sim/players-victory.md`, RR = `../remake-rendering.md`.

## 1. Budgets [draft]

- **GPU**: the remake must not load the GPU more than the original for the same picture (maintainer, 2026-10-14;
  RR §4.2). The faithful presets (light shadows, planar mirror at reduced size, no SSAO) are the reference; the
  refined extras cost more by choice and are switches.
- **Simulation**: a headless run of a converted late-game save, eight players, must manage **several hundred ticks
  per second** on one core. The original needs 30 ticks per second at speed 3 on 2008 hardware; the margin covers
  the slowest peer of a lockstep match and fast replays.
- **Frame**: the presentation's own CPU work (applying tick records, interpolation, uploads) stays below a few
  milliseconds at the default zoom; nothing scales with the map's size, only with what is in view.
- **Loading**: a match loads in a few seconds after the first start (the conversion is cached, [assets.md](assets.md)
  §4); nothing is read from disk during play except streamed music and voices.

## 2. Measuring [draft]

- **GPU time per view, not clock speed** (RR §4.2): the debug overlay shows per-view GPU and CPU time, draw calls of
  the visible and shadow passes, triangles and video memory (the viewer's readout), plus the renderer's own counts
  (render objects per kind, batches, instances, uploads per frame).
- **Benchmarks** run unattended:
  1. the same map, the same camera positions, the original against the remake: GPU time per frame, CPU frame time,
     video memory;
  2. the headless simulation on converted late-game saves: ticks per second, allocations per tick (the target is
     none in the steady state);
  3. regression pictures of fixed camera positions, compared within a tolerance.
- With vertical sync on, the frame rate shows only the cap: comparisons are made with vsync off or by GPU time.

What the viewer measured so far [measured], `MP_6P_ship_ahoi`, before and after the optimisations of 2026-10-15
(sadk-remake branch `viewer-perf`):

| View | Before | After |
|---|---|---|
| normal camera (50°): main view / mirror draw calls | 2 572 / 1 447 | 2 199 / 1 119 |
| flat camera (20°): main view draw calls | 3 452 | 2 810 |
| flat camera with the fog on: main view / mirror draw calls | — | 1 410 / 722 |
| flat camera, fog off → on: main view triangles | — | 1 076 k → 683 k |

The changes: blended foliage batched per region instead of per 4 × 4-cell block (1 614 of 2 373 object batches held
four instances or fewer); the far plane, shadow range and mirror range ending at the fog; animals out of view not
animated; foliage as opaque cutouts by default ([renderer.md](renderer.md) §12). The terrain's ~1 400 surfaces per map
are the largest remaining source of draw calls; the block-instanced terrain of [renderer.md](renderer.md) §10.3 removes
most of them.

## 3. The original's techniques

Recommendation codes: **keep** = reproduce exactly (simulation results, saves, the checksum or the faithful look
depend on it); **adopt** = take the idea, implement with modern means; **Godot** = an engine mechanism does it;
**drop**.

### 3.1 Simulation: keep exactly

The original's simulation is cheap by construction, and almost every saving changes **which tick** something happens
on or which stale value a decision reads. Two caches are saved and part of the lockstep checksum. Compatibility mode
reproduces all of this bit for bit; refined mode may change a rule only where the refined rule set says so.

| Technique | Detail | Source |
|---|---|---|
| fixed tick | 0.1 s, unbounded catch-up, a frame over 5 s counts as one tick, single precision throughout | LC §3.1, §8 |
| staggered periodic work | `tick % N` tests offset by the object's unique id or the player index; `Ticker` fires every `period + 1` calls; unsigned / 64-bit remainders | LC §3.5, §8 |
| player recount | 22-tick cycle per player, phase `index × 2`: stocks at phase 0 (hashed), building counts at phase 1, warnings at phase 10 | PV §3.9 |
| statistics | `tick % 600`, work spread over phases 0 to 4, series capped at 960 | PV §3.11 |
| transport | needs every 11 ticks, package revalidation every 3, package needs every 5; one need node per connected network | ST §3.11, §4 |
| carriers, settlers | `(tick + id) % 20` look for work, `% 10` retry put-down, `% 200` street swap, `% 23` replan while parked; street routes planned one leg at a time | ST §4, `../sim/settlers-jobs.md` §3.8 |
| buildings, spawns | worker request 101, deposit search 51, mine search 101, stock keeping `(tick + id) % 30`, regeneration ≥ 100 apart; spawn points `(tick + phase) % (rate × 1200)` | `../sim/village-buildings.md` §4, LC §3.5 |
| military | enemy distances every 11, garrison allocation every 21, promotion `(tick + id) % 20`, one soldier leaves per building every 10; fight assignment only when dirty | `../sim/military.md` §3 |
| navy | `% 3`, `% 5`, `% 11`, `% 111`, `% 1000` (with the id), searches every 101 and 102 | `../sim/navy.md` §4 |
| AI | per player `tick + 5 × index`, mostly prime periods (3 to 1423), incremental sweeps of its maps, at most 10 site candidates per step, placement back-off; it acts on stale data by design | AI §3.5, §4, §8 |
| active lists, early outs | deposits only while growing, depleting or timed; static doodads checked only when a map-update batch closes; at most 2 animal roam searches per tick, the longest waiting first; exploration two-state and reveal-only | MR §3.7, §3.9 to §3.11 |
| caches that are state | street-net path costs (saved, hashed; emptied only when the continent is recomputed, so the ×3 busy factor stays as first computed); net-continent ids; package next hop (revalidated every 3rd tick, replanned after 200 checks); attack path lengths (flushed after 111 ticks, one half saved); street traffic over 6 001-update windows | ST §3.5 to §3.7, `../sim/military.md` §3.5 |
| batched map updates | `MapUpdateBatch` grows dirty rectangles and flushes at tick step 8; construction flags in spiral radius 4 (`r + 4` after territory changes); territory only in the source's spiral of radius `r`; elevation flush with 16 vertices of margin | LC §4.2, MR §3.4 to §3.6 |
| data stored in the map | grid bits, continents and ship routes used as stored; levelling never refreshes water, shore or cliff bits | MR §3.3, `../map-format.md` §5.5 |
| searches | reverse A* that stops when the start is first reached, FIFO among equal costs, random choices during the read-back; fixed spiral and neighbour orders; Dijkstra on the flag graph with early exit | MR §3.12, §3.13, ST §3.6 |
| minimal movement state | the cell changes when a step completes; a single-precision interpolator advances per tick; everything else is presentation | `../sim/settlers-jobs.md` §3.8 |
| network | one package per net tick with the checksum first, the host's merge order, net tick length adapted 1 to 10 from the pings | `../sim/network-session.md` §3.7, LC §3.2 |

Two consequences for the remake's code:

- **Presentation queries can never fill a hashed cache** (the original had to switch the path-cost cache off around
  one UI query; the remake makes it structural, [sim-boundary.md](sim-boundary.md) §6.1).
- **Periods are data**, not constants ([binding] architecture §5: no `const`): a table per subsystem that refined
  mode or a mod may change, and that compatibility mode leaves alone.

Adopted on the simulation side without changing results: the visited grid with a generation counter instead of
clearing (MR §2.9; per-thread scratch if searches ever run off the main thread).

The AI is a special case: a bit-identical AI matters only for crossplay matches with computer players and for
replays compared against the original; AI §9 judges it a large effort and allows a replacement behind the same
interface, which then keeps the periods as a table for the original's staggered feel.

### 3.2 Presentation: adopt

| Technique of the original | In the remake |
|---|---|
| the terrain block (4 × 4 cells) as the unit of culling, LOD, reveal and hiding objects; a quadtree with nearest-first order and a horizon occluder (R §2.5, WO §3.14) | block as the LOD unit, region (4 × 4 blocks) as the batch unit ([renderer.md](renderer.md) §4.3, §10.3); Redot's frustum culling; the visible block rectangle computed once per frame and shared |
| terrain LOD 0 to 2 by distance with stitched edges (R §3.3) | nesting levels, geomorphing, instanced blocks ([renderer.md](renderer.md) §10.3); faithful mode draws the full grid |
| one instanced renderer per map-object kind, batches of 50, instance colour (R §3.11) | MultiMeshes per kind and region with stable slots ([renderer.md](renderer.md) §4.2) |
| objects hidden with their block until it is revealed (R §3.7) | the block reveal mask read in the vertex shader ([renderer.md](renderer.md) §4.5) |
| cosmetic motion in vertex shaders (R §3.11) | the same, the route buoy included (RR §2.2) |
| one evaluated pose per looping animation, shared by every character playing it (AM §3.8) | the shared clip time of the GPU skinning ([renderer.md](renderer.md) §9); it is also the faithful look (walkers in phase) |
| skinning in the vertex shader, LOD meshes on one skeleton, a palette atlas instead of textures (AM §3.6, §3.14, §3.15) | the same ([renderer.md](renderer.md) §9) |
| characters outside the visible block rectangle not updated (AM §4) | only movers in view are interpolated on the CPU; death sinks become time-based |
| baked light maps, shared materials, rigid single-bone building parts; construction by clip plane and frame subsets (R §3.9) | the same ([renderer.md](renderer.md) §13) |
| one fog-of-war texture read by every shader, no fog pass (R §3.7) | the same ([renderer.md](renderer.md) §4.5) |
| closed-form particles from elapsed time, frozen when hidden, sorted in 20 buckets, one atlas (P §3.5 to §3.12) | the same simulation, on worker threads; one MultiMesh per pass ([renderer.md](renderer.md) §16) |
| the mirror view only while water or ice is in view, with reduced content and resolution (R §3.1) | the same, plus the fog-limited range ([renderer.md](renderer.md) §8.3) |
| no shadow pass while the shadow factor is 0 (sun lower than 20°); caster masks per quality preset (R §2.2, §3.13) | the same skip; casters per descriptor; light shadows by default ([renderer.md](renderer.md) §8.4) |
| one global light per frame from the environment spheres at the focus point (R §3.13) | global shader parameters ([renderer.md](renderer.md) §7.3) |
| a short fog range and a small camera envelope (eye at most 84 units, far plane 500) bound everything drawn | fog that follows the zoom, with far plane, shadow and mirror range and LOD bands ending at the fog ([renderer.md](renderer.md) §11.1) |
| the minimap rendered once, overlays rebuilt when dirty (`../sim/hud-panels.md` §3.7) | event-driven overlay textures; the base picture redrawn on height and pattern events |
| meshes for streets, decals and building sites built on events (WO §3.3, §4) | the same, on worker threads, kept on the GPU |
| at most four ambient sounds, a start-time audibility cut-off at 30 × the minimum distance, footsteps only near the camera, one UI sound per frame (AU §3.3 to §3.9) | a voice budget with the same rules |
| mesh cache, compiled effect cache, map-info cache, failed loads cached, first-run preset from a fill-rate test (AM §3.3, WO §3.11, `../sim/app-shell.md` §3.10) | the converter's output and Redot's caches; shaders compiled behind the loading screen; a negative cache for missing mod assets; a short GPU test for the first preset |

### 3.3 Waste the remake does not copy

| Waste | Where | Instead |
|---|---|---|
| particles drawn **and** updated twice per frame with post effects | P §3.11, R §4.3 | once |
| every effect start re-reads and parses its `.pfx` | P §3.2 | parsed once into descriptors |
| a caustics pass over all visible terrain that adds nothing | R §3.5 | dropped (RR §2.4) |
| a bloom term computed and never shown | R §3.13 | dropped |
| every sound sample decoded at start-up | AU §3.1 | loaded per match, on first use |
| the build checksum recomputed (every script and settings file decrypted) on every call | `../data-loading.md` §3 | once per mod set |
| one synchronous present per loading step, waiting for the vertical sync (about 230 per match) | `../sim/frontend-screens.md` §3.9 | the panel drawn once per change of status text and while the world is built on a worker thread; the layers' `Show` and the HUD stay on the main thread [implemented, sadk-remake 2026-10-25] |
| all scene data and models reloaded for every match | `../data-loading.md` §2 | resident across matches, reloaded only when the mod set changes |
| street geometry streamed into a dynamic buffer every frame, for each view | WO §3.8 | static meshes per street |
| all eight players' border lists rebuilt on any territory change | R §3.8 | the changed rectangle only |
| build-placement icons and HUD rows recomputed every frame | R §3.14, `../sim/hud-panels.md` §4 | on events, or a few times a second |
| goods drawn one call each without culling, every item updated every frame | WO §3.4 | MultiMesh per good and region; only moving items updated |
| every map object ticked each logic tick, visible or not | P §3.14 | events (route ships for the buoy fire) |
| a second fog-of-war texture with no known reader | R §3.7 (open) | dropped unless a reader turns up |
| selection decals re-clipped every frame | WO §3.9 | re-projected on change |
| no frame limiter in menus and pauses | `../sim/app-shell.md` §3.4 | a frame cap and low-processor mode there |
| Nagle's algorithm left on for the host's sockets | `../sim/lan-and-transport.md` §3.4 | no delay on every socket (the wire format is unchanged) |
| frame-rate dependent smoothing and sinking | `../sim/camera-input-cutscenes.md` §8, AM §4 | time-based |

## 4. Decisions taken on 2026-10-15 [draft]

From the maintainer's judgement during the viewer work, each recorded where it applies:

| Decision | Where |
|---|---|
| heavy shadow settings improve the picture very little: light shadows by default, heavier presets as options | [renderer.md](renderer.md) §8.4 |
| the visible upgrade is smoother terrain: the Terrain detail setting (Faithful, Smooth, Smoother, Smoothest) | [renderer.md](renderer.md) §10.2 |
| distance LOD per terrain block | [renderer.md](renderer.md) §10.3 |
| fog follows the zoom | [renderer.md](renderer.md) §11.1 |
| foliage as opaque cutouts with alpha to coverage by default; the original's blending as a switch | [renderer.md](renderer.md) §12 |
| the mirror: planar, made cheaper first (the original's detail levels, fog range, resolution, update rate); pixel-projected reflections as a later Forward+ option; a flipped screen picture does not work from above | [renderer.md](renderer.md) §8.3 |

## 5. Open

1. The reader of the original's second fog-of-war texture (R §10 Q10).
2. The original's terrain vertex counts per LOD level (R §10 Q9) and the size of its post-effect targets.
3. The simulation benchmark's exact target, once a headless simulation exists.
