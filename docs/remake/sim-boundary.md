# Remake: the boundary between simulation and presentation

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). It fixes how the deterministic C#
simulation and the Godot presentation (renderer, audio, UI) talk to each other: the clock, the tick records with
their events and motion samples, the read-only views, the way back through commands, the separation of random
numbers, and what must never cross. The renderer ([renderer.md](renderer.md)) and the Lua layer ([lua.md](lua.md))
build on it.

Tags: **[binding]** = decided by the maintainer; **[draft]** = proposed here; facts about the original carry the tag
of the cited document. Short names: LC = `../sim/logic-core.md`, RE = `../sim/rendering.md`, AM =
`../sim/animation-models.md`, SJ = `../sim/settlers-jobs.md`, GC = `../sim/game-commands.md`, LR =
`../sim/lua-runtime.md`, CI = `../sim/camera-input-cutscenes.md`, MR = `../sim/map-resources.md`, SF =
`../sim/save-format.md`, NS = `../sim/network-session.md`.

## 1. How the original couples them

Single thread. Per frame [known, LC §3.1, §4.1; CI §4]: input (between frames; offline commands execute at once
inside the UI call) → camera → UI (cinematic screen among the dialogs) → network pump → Lua threads woken by wall
time → **0..n logic ticks** of 0.1 simulation seconds (10, 20, 30 per second at speed 1, 2, 3; catch-up without a
cap; a frame over 5 s counts as one tick) → sound → render (picking inside the render step).

The scene mirrors the simulation through two channels [known, LC §3.7, RE §3.2, §5]:

- **push**: 56 synchronous `NLogic::CallbackManager` events plus 5 rectangle events of the map, fired from
  constructors, destructors, state changes and post-load, i.e. **inside** the tick; "added" events are fired again
  after a load so the scene rebuilds;
- **pull**: render objects hold pointers into logic objects and read them every tick (`Scene::SyncLogicTick`, the
  step after the 20 subsystem steps) and every frame (construction progress, hit-point ratio, settler state and
  action timer, movement progress, growth, ship state, cargo, ...).

The renderer shows the world **one tick behind** with `f = 1 − (nextTickTime − now) / 0.1` and never extrapolates
[known, RE §2.2, §3.10]. No simulation function calls render, audio or animation code directly, and the renderer
writes nothing the simulation reads [known, EC §3.7; RE §10 Q18 open for some handlers]. The hazards are in the UI
and script layer: the cinematic screen switches AI, chests and sacrifices at frame time; the UI calls map-script
callbacks that change simulation state; scripts read local values (`getSpeed`, `pl_getUser`); player messages are
aged by frame time inside the tick and removed by the HUD; simulation code branches on "the local player" in
several places (victory quest text, defeat letter, profile writes, quest-log refresh) [known, CI §8, LR §8,
players-victory §3.6].

## 2. Principles [draft]

1. **The simulation is a function of (initial state, command stream).** It reads no frame time, wall time, local
   identity, camera, selection, language or window state, and runs the same with or without a presentation
   attached ([binding] architecture §2: headless tests, replays, checksum comparison against the original).
2. **Two channels out**, both output only: an ordered **event stream** per tick, and **read-only views** plus
   per-tick **motion samples**.
3. **One channel in: `GameCommand`s** [binding] architecture §6. Script callbacks from the UI and the end of a
   cinematic are commands too.
4. **Separate random sources.** The simulation generator is unreachable from presentation code.
5. **Events carry what the consumer needs at emission time**, because consumers run after the tick, when the
   object they describe may be gone (the original's "building removed" handler reads `LeavesRemains` from the
   dying building).
6. **No "local player" inside the simulation.** It addresses players by index; each presentation decides what
   concerns its own player.

## 3. Assemblies [draft]

| Assembly | Godot | Holds |
|---|---|---|
| `Sadk.Engine` | no | registry and load stages, mod loader, virtual file system, Lua host, number model and simulation math, hex grid, tick scheduler, component framework, commands, events, views (interfaces), save framework, checksum |
| `Sadk.Session` | no | the tick driver (`SimHost`), lockstep gate, net tick length, hang state, the original's network protocols, replays |
| `Sadk.Formats` | no | readers of the original's formats (taken over from the testbed viewer) |
| `Sadk.Convert` | no | the first-start conversion ([assets.md](assets.md) §4) |
| `Sadk.Presentation` | yes | renderer, audio, UI framework, input, camera, presentation random streams |
| `Sadk.Game` | yes | the executable: bootstrap, screens, glue |
| `core.game`: its simulation and client assemblies (`Core.Game`, later `Core.Game.Client`) | no / yes | the base game's components, systems, commands, Lua bindings / its presentation handlers and UI sections |
| `Sadk.Headless` | no | command-line runner: conversion, mod validation, replays, checksum comparison |

`Sadk.Presentation` references `Sadk.Engine` only through the view interfaces and event types. Simulation objects are
not public to it; mods reach everything through Harmony anyway ([mods.md](mods.md) §7.3), so the run-time fences of
§10 check the contract.

## 4. Clock and tick driver

### 4.1 The driver [draft]

```csharp
namespace Sadk.Session;

public readonly record struct SimClock(
    int    Tick,            // last executed tick, -1 before tick 0
    double TickInterval,    // 0.1 s (GameConfig; not a const, architecture §5)
    double NextTickTime,    // simulation seconds at which Tick + 1 is due
    double Now,             // accumulated simulation seconds (the original's accumulatedTime)
    double SimDelta,        // this frame's scaled delta; 0 while paused or (refined) stalled
    double RealDelta,       // unscaled frame seconds: UI, camera, audio
    float  TimeScale,       // 0 paused, 1..3, cinematic blend values
    bool   Stalled,         // the lockstep gate refused a due tick this frame
    HangState Hang)
{
    // Interpolation factor between the previous and the current tick sample (RE §2.2).
    public float Alpha(bool faithful) =>
        Stalled && !faithful ? 1f : Math.Clamp((float)(1.0 - (NextTickTime - Now) / TickInterval), 0f, 1f);
}

public interface ISimHost
{
    SimClock Clock { get; }
    IWorldView World { get; }              // valid between Advance calls only
    void Submit(GameCommand command);      // the local player's commands
    FrameTicks Advance(double realSeconds);// runs 0..n ticks: 5 s clamp, catch-up without cap, lockstep gate
}

public sealed class TickRecord             // immutable once published
{
    public int Tick { get; }
    public ReadOnlyMemory<SimEvent> Events { get; }   // emission order (§5)
    public MotionFrame Motion { get; }                // samples at the end of the tick (§6.2)
    public uint? Checksum { get; }                    // on net tick boundaries
}
```

- The accumulator semantics are the original's (they decide the feel of speed changes). The simulation does not
  run in Godot's physics step: a lockstep stall or a pause must not produce physics frames that Godot would
  interpolate across ([godot-capabilities.md](godot-capabilities.md) §6).
- **Speed and pause in Godot** [draft; the maintainer's direction 2026-10-15]: the driver is a pausable node that
  calls `Advance` from `_Process` with Godot's scaled delta, so the game speed is `Engine.TimeScale` (set only from
  simulation state: the speed command's tick and cinematic blends; `SimClock.TimeScale` mirrors it) and an offline
  pause is `SceneTree.Paused` rather than a time scale of 0. Animation players, particles, tweens and the presentation
  time then follow speed and pause without code of their own; `RealDelta` comes from `Time.GetTicksUsec`, since Godot
  exposes no unscaled step ([godot-capabilities.md](godot-capabilities.md) §6). The fixed-tick accumulator stays the
  remake's, so frame timing decides only when a tick runs. Open: whether the original clamps the frame time at 5 s
  before or after applying the speed.
- **Offline commands** execute in the gap between two ticks, with the tick counter of the previous tick, as the
  original executes them inside the UI call (GC §3.1). Network commands execute at the closing tick of net tick
  `N+2`, at the start of that tick before its subsystems (GC §3.2). Both are scheduled by `SimHost`; the UI only
  submits.
- **Stall picture.** The original rolls the accumulator back when the gate refuses, which (inferred, not observed)
  replays the last tick as a 10 Hz saw-tooth. Faithful mode keeps that; refined mode holds `Alpha` at 1 and
  `SimDelta` at 0 while stalled. A switch ([renderer.md](renderer.md) §19).

### 4.2 One presentation frame [draft]

1. Input → UI → `Submit`; camera and UI advance with `RealDelta`.
2. `Advance(realSeconds)`; the time scale changes only through the speed command, pause (offline) and the cinematic
   screen, as in the original.
3. For each `TickRecord` in order: apply its events (create, remove, change render objects, sounds, UI updates),
   then take its motion samples (`prev ← current`, `current ← sample`). This is the original's `SyncLogicTick`, run
   per published tick so catch-up frames keep correct pairs.
4. `Alpha`, interpolation, animation with `SimDelta`, particles with simulation time, audio with `RealDelta`.
5. Render; picking for the next frame's input.

### 4.3 Threading [draft]

The first version runs the simulation on the main thread inside step 2, as the original does. The shape above
allows a simulation thread later without changing consumers: the presentation reads only published tick records
and views; views then go through a snapshot or a tick-boundary lock. CPU-heavy presentation work (terrain region
rebuilds, decal clipping, particle simulation) runs on worker threads and is applied on the main thread.

## 5. The event stream

### 5.1 Types [draft]

Identity: the original's 64-bit unique ids (`NLogic::Unique`, MR §2.6) for everything that has one, so map objects,
deposits, doodads, flags, buildings, settlers and ships already carry the identity the architecture asks for
([binding] §5). Presentation sub-objects (a buoy at either end of a route, a fire point, a pile slot) are
`(EntityId, subIndex)`, never new simulation ids.

| Group | Events (payload) | Replaces in the original |
|---|---|---|
| world | `WorldBuildBegin/End`, `LoadRebuildBegin/End` (bracket around the re-sent "added" events after a load) | callback slots +0x00, +0x04 |
| entities | `EntityAdded(id, kind, typeKey, owner, cell, finePos, reason)` with reason Placed, Loaded, TypeChanged, Transferred, Spawned; `EntityRemoved(id, kind, reason, info)` with `info` = cell, fine position, type, owner, `leavesRemains`, `destroyed` | the 34 add / remove slots (buildings, flags, settlers, streets, deposits, animals, packages, remains, doodads, ships, harbours, routes, projectiles, sacrifices, chests, spawn points) |
| state | `UpgradeStarted(building, targetType)`, `UpgradeCancelled`, `StreetUpgraded`, `DepositShown`, `DepositDepleted(id, depletedTicks)`, `SettlerPathChanged(id)`, `PackagePile(id, flag, attached)`, `ChestOpened(id, player)`, `HarborLinked(flag)`, `FightChanged(id)`, `CarriedPackageChanged(settler)`, `ActionTimerStarted(entity, kind, totalTicks)`, `EntityStateChanged(entity, state)` | slots +0x10..+0x14, +0x44..+0x50, +0x5c, +0x60..+0x6c, +0xc8..+0xd0; the per-tick polling of action timers and states |
| one-shot | `Strike(attacker, target)`, `ProjectileLaunched(id, kind, source, target, launchTick, impactTick)`, `ProjectileEnded(id, impact)`, `SpawnTriggered(id)`, `SacrificeEffect(kind, subject)`, `SacrificeState(building, state)` | slots +0x30, +0x98, +0x9c, +0xa0..+0xc4, +0xdc |
| map | `MapChanged(layer, rect, player)`, layer = Heights, Patterns, Territory, Exploration, ConstructionFlags, GroundResources, Reinitialised; one merged rectangle per layer, player and tick | `NMap::CallbackReceiver`; **new**: territory with a rectangle (the original rebuilds all borders), construction flags (the original recomputes the build overlay per frame) |
| players | `PlayerAdded/Removed`, `MessagePosted(player, messageKey, type, args, cell?)`, `QuestChanged(slot)`, `StatisticsSampled(player)`, `PlayerDefeated(index)`, `MatchDecided(winners)` | player table notifications; message and statistics listeners; the victory code's local-player branches |
| session | `SpeedChanged(speed)`, `CommandResolved(sender, commandType, result)` | the speed command's local effects; the executors' direct calls into the local street placement mode (GC §3.4) |
| script UI | `ScriptUi(player or all, request)`: book pages, tutorial page, minimap symbol, letter, action override, cinematic pages, particle at a cell, lock-map refresh | the UI-only `menu.*`, `ui.*`, `gfx.*` calls of map scripts ([lua.md](lua.md) §6) |
| services | `ChestClaimed(chest, player, value)`, `MatchDecided` | the referee's ClaimChest and FinishGame, the campaign progress and profile writes |
| loading | `LoadProgress(step, of)` | the ten "Finalizing world" progress steps; the simulation never draws a frame |

`SimEvent` is an open base record: a mod's component emits its own event types, and the presentation maps event
types to handlers, so a mod brings render and audio behaviour for its own events ([mods.md](mods.md) §8.2).

### 5.2 Order and consumption [draft]

- Events are appended in emission order: the commands of the boundary first, then the subsystems in the fixed tick
  order (LC §4.2), then `onLogicTick`. Each carries `(tick, seq)`. A removal and a re-creation inside one tick (an
  upgrade's completion: "removed" with the building flagged destroyed, then "added", RE §3.9) keep that order.
- Consumers run after the tick, never inside it. Subscribers run in registration order, but none may depend on
  another's order (the original orders receivers by heap address, LC §8).
- Emission never depends on whether anyone listens, and nothing about events enters the checksum or the save.
- After a load the simulation publishes `LoadRebuildBegin`, an `EntityAdded(reason = Loaded)` for every entity in
  the original's post-load order (navy routes and harbours, resources, doodads, spawn points, buildings, flags,
  streets, ..., chests; SF §3.4), `MapChanged(Reinitialised)` per layer and `LoadRebuildEnd`. The presentation builds
  its mirror the same way for a new game and a load: one code path.

## 6. Views and motion samples

### 6.1 Read-only views [draft]

```csharp
public interface IWorldView
{
    int Tick { get; }
    IMapView Map { get; }          // heights, patterns, territory, exploration(player), constructionFlags(player),
                                   // grid states, ground resources, water level
    IPlayersView Players { get; }  // colour, tribe, team, spotted / reached, stocks, quests, victory progress
    bool TryGet<TView>(EntityId id, out TView view) where TView : IEntityView;
    void Query(EntityKind kind, RectI cells, ICollection<EntityId> into);   // ordered by id
    IQueries Queries { get; }      // pure queries for the UI
}
```

Entity views are component-shaped (`IConstructionView`, `IHitpointsView`, `IProductionView`, `IMovementView`,
`IActionTimerView`, `IMilitaryFlagView`, `IGrowthView`, ...), so a mod's component adds its own view interface and
the panels and render kinds ask for capabilities, not types ([binding] architecture §5).

**`IQueries` rules**: own scratch buffers (the original shares A* instances, the visited grid and flood-fill marks
inside flags between the simulation and the street preview, MR §2.8, §2.9), no random draw, and **no lazy filling
of a cache the checksum covers** (street-net path costs, attack path lengths; LC §3.6). The original already needed
this once: the action panel turns the path-cost cache off around one availability query (`cacheDisabled`,
streets-transport §2.1); the remake makes it structural.

**Stale caches stay stale**: several original queries read per-player caches recounted every 22 ticks
(`pl_getGoodAmount`, building and construction counts; LR notes). Views that compatibility mode needs to match
(script bindings, AI) read the same caches; presentation panels may read the live values.

### 6.2 Motion samples [draft]

```csharp
public readonly record struct MotionSample(
    EntityId Id,
    FinePos  From,       // logic position at the start of the current step
    FinePos  To,         // target of the step (From when not moving)
    float    Progress,   // the interpolator's progress; -1 = not moving (SJ §3.8.1)
    EntityId Street,     // street walked, for the route spline (RE §3.10); None = free walk
    byte     Heading,    // hex direction of the step
    byte     Flags);     // swimming, aboard, dying, ...
```

The simulation publishes **logic** values only: what it stores and saves. The presentation turns them into world
positions per tick (route spline, height snap, evade offset, boat bobbing) and keeps `prev` / `current` per object,
the original's split (RE §3.10, AM §3.17, §3.18). Only entities that moved or changed are in a frame. On
`EntityAdded`, `prev = current = sample` (no glide from the origin). State that the scene samples per tick without
moving (construction progress, growth, `depletedTicks`, hit-point ratio, military flag) is read through the views in
step 3 of §4.2 and kept with a `prev` value where the original interpolates (the construction plane, growth fades).

Animation choice remains a presentation rule over simulation state (AM §3.9: action timer kind → slot; keys from
the carried good, profession, workplace, tribe). The simulation never waits for an animation (AM §8); every duration
it needs is registry data ([mods.md](mods.md) §8.3).

### 6.3 Presentation hints that are simulation state

Values the original draws from the **simulation** generator and only displays stay simulation state, read from
views [known, sources as cited]: the deposit display position (`Deposit::ctor_AtCell`, one draw per deposit, MR
§3.9), randomised walking paths (SJ §3.8.3), the soldier's alternative work clip length (`attackWaitTime + rnd %
10`, SJ §8), carrier parking spots (SJ §3.8.6), sow patterns (MR §3.9), and `lookAtPos` (hashed, SJ §8).

## 7. The way back: commands [draft]

- Every player action is a `GameCommand` carrying ids, cells and registry ids, executed at a tick boundary on every
  machine and validated again there [binding] §6.
- **UI callbacks into map scripts** (`quest_cinematicDone`, `createQuestUi`, `destroyQuestUi`,
  `<widget>_isClicked`, `<widget>_isPressed`) become the command `ScriptCallback(name)`. The end of a cinematic is
  the command `CinematicFinished`, so `EndCinematic` (AI, chests and sacrifices switched back, sacrifice ticks
  shifted) happens at a tick. Offline the timing equals the original's (between two ticks).
- **Local feedback** that the original's executors provide by direct calls (closing the street placement mode,
  refusing a waypoint) comes from `CommandResolved` events; previews come from `IQueries`. Commands travelling
  through the network (up to three net ticks) may show a pending ghost in the UI; nothing is predicted in the
  simulation.
- The selection, the placement modes, the street build mode and the message list are presentation state. The
  original allocates the selection in the logic system and keeps messages (with their remaining time) in the saved
  player object; the remake's save adapter writes the presentation's message list into the original's `Messages`
  record and reads it back, the one place the two meet (compatibility saves only).
- While the session hangs: faithful mode drops commands as the original does (GC §3.1), refined mode refuses them
  with a visible reason.

## 8. Random numbers [draft]

| Stream | Owner | Seed and scope | Used for |
|---|---|---|---|
| `SimRandom` (Park-Miller) | simulation, `internal` | 0x5432ACE0 at every new game; saved | every simulation draw in the original's order (LC §3.3); `logic.getRandom` |
| chest generator | simulation | from the session's game seed | chest contents (LC §2.7) |
| `ScriptRandom` | simulation | from the game seed | `math.random` in scripts that change simulation state ([lua.md](lua.md) §2.6); never used by shipped scripts |
| presentation streams (Park-Miller), one per purpose | presentation | faithful: process-wide, seeded as in the original (0x5432ACE0, 0x400, 0x53a0, 0x7D6, 0x7C0), advanced in creation order; refined: `hash(mapId, entityId, stream)` | map-object yaw and scale, settler palettes, fallback fire points, animal idle choice, idle variations, particles, resource hints, projectile visuals, initial facing |
| UI and audio randomness | presentation | any | sound variants, playlists, UI pulses (the original shares C `rand()` between audio, UI and Lua `math.random`) |

Faithful mode reproduces the original's first map after a start exactly (yaws and palettes depend on creation order
since program start); refined mode gives every peer, every load and every session the same picture. A switch
([binding] rendering §2.3).

## 9. Saves [draft]

- The save holds simulation state only; the presentation rebuilds from the load events (§5.2). An optional
  presentation section (camera, selection, open panels, message timers) is skipped by the simulation.
- Saves and the autosave run at a tick boundary, never mid-tick.
- Compatibility saves (the original's format) carry the original's presentation-flavoured fields (messages with
  remaining time, the victory quest's text for the local player) through the save adapter (§7).

## 10. What must never cross, and the guards

From the presentation into the simulation: any write outside a `GameCommand` (Lua callbacks and cinematics
included); a draw from `SimRandom`; anything that advances the unique id counter; the lazy computation of a hashed
cache; frame time, wall time, the local time scale, the local player's identity, camera, selection, window state,
language; Godot types.

From the simulation into the presentation: live mutable objects or references kept beyond a tick; synchronous calls
into presentation code; "local player" decisions; widget handles; sounds; file, profile or network writes (output
services consume events); drawing a frame; anything whose emission depends on whether a presentation is attached.

Run-time guards, on in debug builds and in the test harness [draft]:

- **random fence**: `SimRandom` counts draws; the count at the end of tick *k* must equal the count at the start of
  tick *k + 1*;
- **id fence**: the same for the unique id counter;
- **state fence** (test harness): hash the whole save stream at the end of tick *k* and at the start of tick *k + 1*
  with a presentation attached;
- **headless equality**: a replay run headless and with the presentation gives the same per-tick checksums.

These matter more in the remake than in the original, because Harmony patches can bypass assembly boundaries.

## 11. Open points

1. Cinematics and map scripts in network matches: refused in compatibility mode (the original never reaches them on
   shipped maps, and a fresh original process has no `logic` table in a network match); in refined mode the
   cinematic ends when every peer has sent `CinematicFinished`, or for everyone when the first does. **Decision for
   the maintainer.**
2. Whether the scene handlers not yet re-read call a logic mutator (RE §10 Q18); the event table assumes not.
3. The unnamed `rand() % 6` caller of `StepDirection` (MR §3.1); if it is simulation code it is a C-runtime draw
   inside the simulation.
4. The stall picture (§4.1) is inferred; one look in a two-player match with a pulled cable settles it.
5. Message ids: the original's counter is not saved and repeats ids after a load (EC §7); the remake keys messages
   by the `(tick, seq)` of the posting event.
