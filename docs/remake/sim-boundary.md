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
`../sim/save-format.md`, NS = `../sim/network-session.md`, ST = `../sim/streets-transport.md`, VB =
`../sim/village-buildings.md`, PV = `../sim/players-victory.md`, MI = `../sim/military.md`, QS =
`../sim/quests-sacrifices-stats.md`, FS = `../sim/frontend-screens.md`, PA = `../sim/particles.md`, AP =
`../sim/ai-player.md`.

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
| `Sadk.Simulation` | no | the built-in `core.game`'s simulation: components, systems, commands, game rules, Lua bindings |
| `Sadk.Client`, `Sadk.MainMenu` | yes | `core.game`'s presentation handlers, renderer and UI; `core.mainmenu` |
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
  remake's, so frame timing decides only when a tick runs. The 5 s clamp applies after the speed
  (`dt = frameSeconds × speed; if dt > 5`, logic-core §3.1, game-commands §4): at speed 3 a real frame over about
  1.67 s counts as one tick.
- **Built** [implemented, sadk-remake a7a220c]: `Sadk.Session.SimHost.Advance(simSeconds, realSeconds)`,
  fed by the pausable `SimDriver` node (`Sadk.Presentation/Simulation`), which also sets `Engine.TimeScale` from the
  world's speed and back to 1 when it leaves the tree; `Step(n)` and `Flush()` for headless runs. Tick 0 runs in the
  first frame; all due ticks run in one frame without a cap; the tick interval comes from the registry
  (`GameConfig.GameSpeed`). A refused gate puts the accumulator back to one interval before the due time
  (`Alpha(faithful)` follows the saw-tooth, refined holds 1). Hang reasons: the transport's, `NotStarted` (no tick
  yet: the original drops commands before tick 0) and `NoTick` (2 s of real time without a tick); `Submit` drops
  commands while hanging unless forced (`QueueGameCommand`). Net ticks: `S = NetTickLength × GameSpeed`, also offline
  (length 1); on the tick that closes a net tick: the transport's boundary commands, net tick + 1, the checksum hook,
  the transport exchange (`EndNetTick`), then the systems; net tick 0 is the world as built. Random and id fences are
  checked before each tick and before gap commands. `ICommandTransport` (`Start`, `Pump`, `Submit`,
  `TakeGapCommands`, `CanAdvance`, `TakeBoundaryCommands`, `EndNetTick`, `Waiting`, `Hang`) is the seam:
  `OfflineTransport` is the original's DummyNetwork (commands run in the gap before the next tick with the previous
  tick's counter, logged as tick, gap and order, their events published as a record of their own); a lockstep
  transport implements `CanAdvance` as the original's `CanAdvanceTick` and exchanges packages in `EndNetTick`
  without touching `SimHost`'s callers. `CommandLog` (`.sadkreplay`, versioned: registry checksum, mod set, setup,
  the commands with tick, phase and sender, per-net-tick checksums) replays through `ReplayTransport`; the headless
  runner's `replay --log=` compares the checksums.
- **Offline pause** [the maintainer's decision 2026-10-16: as the original; implemented, sadk-remake 57cca2a; known:
  `TogglePause` S 005da400, `SetPaused` S 005ea9b0]: `SceneTree.Paused` stops the world's Godot animations; the tick
  driver keeps processing and gets 0 simulation seconds plus the real delta, so no tick is due. Commands run at once
  inside `Submit`, between ticks, as the original's `QueueGameCommand` runs them inside the UI call. After 2.0 s of real
  time without a tick the session hangs: commands without `force` are dropped, and the game screen swallows character
  keys and left clicks on the world except the pause key (`OnChar` S 005eb180, `OnMouseButton0Down`), while the camera
  (key-down events, wheel, right and middle buttons) stays usable. Pause is allowed only in a local session with the
  game screen open and no cinematic; it keeps the time scale and restores max(kept, 1.0), never touches the
  simulation's speed and never goes through a command; the speed button does not act while paused; leaving the screen
  unpauses. The pause panel (`menuingame.xml <pause>`, read at run time) fades in and out over 1.0 s with smootherstep
  on alpha (`AnimationAlphaFade::Update` S 004d2220); its text pulses at alpha 0.7 to 1.0, 1 Hz (S 005ecaf0), on its
  own, since a widget's opacity is set, not multiplied by its parent's (S 004a0630). The water and the map objects
  freeze while paused: the scene's frame delta is the logic's `frame × speed` (S 0067f6b0), which
  `UpdateWaterAnimation` S 006a65a0 sums. Not reproduced: the original latches a speed click made while paused and
  sends it after unpausing. Open: whether the sky, environment and particles stop as well; the pulse's phase origin.
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

### 4.3 Threading [the maintainer's decision 2026-10-18; draft]

**The simulation runs on a thread of its own, in faithful mode too.** The original runs it on the main thread
between UI and render, so every tick is paid for inside a frame. Determinism does not depend on that: it rests on
the order of work *within* the simulation (the fixed system order, the single random stream, single-precision
floats, commands at fixed ticks and gaps), and one simulation thread keeps that order exactly. Which frame a tick
falls into is presentation. The simulation thread is the only thread that runs ticks; inside a tick it stays
sequential.

What changes against §4.1 and §4.2:
- **Driver.** The simulation thread owns `SimHost`: it advances the accumulator (the original's semantics, 5 s
  clamp, catch-up without cap), runs the due ticks, pumps the transport and publishes each `TickRecord` into a queue.
  `SimDriver` on the main thread only feeds it the scaled time and the real time, and takes the records in step 3.
- **Commands.** `Submit` enqueues; the simulation thread executes offline commands in the next gap between two
  ticks, with the previous tick's counter, the place the original's UI call gives them. The command log records tick,
  gap and order as before, so a replay is the same with or without the thread.
- **Views.** `IWorldView` is no longer "valid between Advance calls": the presentation reads a snapshot published at
  a tick boundary, or takes a tick-boundary lock for rare queries (picking, info boxes). It never reads live state.
  Game rules are pure functions of their query ([mods.md](mods.md) §14 item 7), so the presentation evaluates one
  (the farm's product buff) without the lock.
- **Godot state.** `Engine.TimeScale` and `SceneTree.Paused` are set on the main thread from published records; the
  simulation thread touches no Godot API (godot-capabilities §6).
- **Clock.** `SimClock` is published with each record, so `Alpha` (and faithful mode's stall saw-tooth) is computed
  from published values on the main thread.
- **Frame-time hazards of §1.** The cinematic screen's switches, UI calls into map-script callbacks, frame-aged
  player messages and "local player" branches must reach the simulation as commands or tick-time work, not as calls
  from the main thread. [TODO] list each one and its route; the map script's Lua threads that the original wakes by
  wall time each frame (offline only, `../sim/lua-runtime.md`) need a decision on which thread they run.

CPU-heavy presentation work (terrain region rebuilds, decal clipping, particle simulation) runs on worker threads
and is applied on the main thread. Measured at a god-mode building placement: the terrain costs 2 to 5 ms of main
thread per height change; the simulation's tick 2 to 4 ms (Release, its systems, the command and the events timed one by
one on MP_2P_steinfjord, sadk-remake 1cb6bec), against 1.4 to 1.8 ms for an ordinary tick. The frames of 35 to 74 ms
seen at a placement were the building type's visuals being read and built on first use, which the load now prepares
([renderer.md](renderer.md) §10.5). The thread still takes the tick's few milliseconds off the frame.

**Refined mode** [TODO, later]: parallel work *inside* a tick (path searches, AI evaluation, territory and
visibility maps computed against a read-only view, applied in a fixed order; deadline jobs started at tick N and
applied at N + k). Not designed yet; it may not draw random numbers or combine floats out of order.

## 5. The event stream

### 5.1 Types [draft]

Identity: the original's 64-bit unique ids (`NLogic::Unique`, MR §2.6) for everything that has one, so map objects,
deposits, doodads, flags, buildings, settlers and ships already carry the identity the architecture asks for
([binding] §5). Presentation sub-objects (a buoy at either end of a route, a fire point, a pile slot) are
`(EntityId, subIndex)`, never new simulation ids.

| Group | Events (payload) | Replaces in the original |
|---|---|---|
| world | `WorldBuildBegin/End`, `LoadRebuildBegin/End` (bracket around the re-sent "added" events after a load) | callback slots +0x00, +0x04 |
| entities | `EntityAdded(id, kind, type, owner, cell, finePos, reason)` with reason Placed, Loaded, TypeChanged, Transferred, Spawned; `EntityRemoved(id, kind, reason, info)` with `info` = cell, fine position, type, owner, `leavesRemains`, `destroyed` | the 34 add / remove slots (buildings, flags, settlers, streets, deposits, animals, packages, remains, doodads, ships, harbours, routes, projectiles, sacrifices, chests, spawn points) |
| state | `UpgradeStarted(building, targetType)`, `UpgradeCancelled`, `StreetUpgraded`, `DepositShown`, `DepositDepleted(id, depletedTicks)`, `SettlerPathChanged(id)`, `PackagePile(id, flag, attached)`, `ChestOpened(id, player)`, `HarborLinked(flag)`, `FightChanged(id)`, `CarriedPackageChanged(settler)`, `ActionTimerStarted(entity, kind, totalTicks)`, `EntityStateChanged(entity, state)` | slots +0x10..+0x14, +0x44..+0x50, +0x5c, +0x60..+0x6c, +0xc8..+0xd0; the per-tick polling of action timers and states |
| one-shot | `Strike(attacker, target)`, `ProjectileLaunched(id, kind, source, target, launchTick, impactTick)`, `ProjectileEnded(id, impact)`, `SpawnTriggered(id)`, `SacrificeEffect(kind, subject)`, `SacrificeState(building, state)` | slots +0x30, +0x98, +0x9c, +0xa0..+0xc4, +0xdc |
| map | `MapChanged(layer, rect, player)`, layer = Heights, Patterns, Territory, Exploration, ConstructionFlags, GroundResources, Reinitialised; one merged rectangle per layer, player and tick | `NMap::CallbackReceiver`; **new**: territory with a rectangle (the original rebuilds all borders), construction flags (the original recomputes the build overlay per frame) |
| players | `PlayerAdded/Renamed/Removed`, `MessagePosted(player, messageKey, type, args, cell?)`, `MessagesLoaded(player, messages)`, `QuestChanged(slot)`, `StatisticsSampled(player)`, `PlayerDefeated(index)`, `MatchDecided(winners)` | player table notifications; message and statistics listeners; the victory code's local-player branches |
| session | `SpeedChanged(speed)`, `CommandResolved(sender, commandType, result)` | the speed command's local effects; the executors' direct calls into the local street placement mode (GC §3.4) |
| script UI | `ScriptUi(player or all, request)`: book pages, tutorial page, minimap symbol, letter, action override, cinematic pages, particle at a cell, lock-map refresh | the UI-only `menu.*`, `ui.*`, `gfx.*` calls of map scripts ([lua.md](lua.md) §6) |
| services | `ChestClaimed(chest, player, value)`, `MatchDecided` | the referee's ClaimChest and FinishGame, the campaign progress and profile writes |
| loading | `LoadProgress(step, of)` | the ten "Finalizing world" progress steps; the simulation never draws a frame |

As built (sadk-remake, 2026-10-16): `type` is the registry entry itself, not a key string; `EntityKind` and the map
layers are open names, so a mod adds kinds and layers without touching the engine; `EntityAdded` and `EntityRemoved`
can be subclassed, and a sea route's added event (`ShipRouteAdded`) also carries its path and whether both harbours
are linked. `PlayerAdded` carries the slot kind; a computer's name change at the start is `PlayerRenamed`, and the
name is a text key (`<tribe>_AI_<level>_<slot>`), so the simulation does not depend on the language. An empty world
also emits `WorldBuildBegin` and `WorldBuildEnd`.

Settlers as built (sadk-remake a2bd808): `SettlerPathChanged` is emitted at the start of a walk and at a step on a
changed path, where the original calls callback slot +0x5c (a street step never reports one: `StreetPath +0x48` is
always 0 in the original, SJ §3.8.5, so a replan raises no event either); `ActionTimerStarted`, `EntityStateChanged` and
`CarriedPackageChanged` replace the scene's per-tick polling of timers, states and carried goods. `EntityRemoved`
carries a `RemoveReason` (`Entered`, `Died`) and, for a settler that entered a building, `Into` (that building). A
settler's `EntityAdded` comes before the `LeaveBuilding` walk its constructor starts, with no step between. `Died` is
emitted when the settler is erased, one tick after it reached state 6 (SJ §3.3).

Living map as built (sadk-remake 514d96c): the engine holds the event types (`LivingMap.cs`). `DepositShown(id, type,
cell, finePos, reason, growth)` is the deposit's `EntityAdded`, emitted where the original raises "deposit shown"
(sowing, a deposit made full, a load with growth ≥ 0, MR §5.3): a deposit planted but not yet sown is not announced,
and a field sown anew is shown again with its new growth. `DepositDepleted(id, depletedTicks)` comes from the marking
(growth ≥ 0), `SpawnTriggered(id)` from both spawn kinds. An animal's `EntityRemoved` carries `Obstructed` (erased
under a new building, MR §3.10) or `Destroyed` (a hunt abort).

Messages as built (sadk-remake cc12218): `MessagePosted` carries the original's three posting rules as flags.
`Refresh` is "post or refresh" (`PlayerMessages_SendOrRefreshToPlayer` S 005c0270): a listed message of the same type,
key and argument whose cell lies at a hex distance below `RefreshDistance` only has its time reset to 600 (S 005c0230),
the first match oldest first; `RefreshDistance` is 1 for every poster except the geologist's find, which passes 7
(S 0077b2f0). `UnlessPending` is "post unless pending" (`NotifyLostTerritory` S 006797f0: nothing posted, nothing
reset), and `MatchKeyOnly` leaves the argument out of the match (`Messages::FindMatching` S 005c1fd0 instead of
`FindMatchingWithArg` S 005c1e40). `MessagesLoaded(player, messages)` comes inside the load's re-announcement and
restores a player's list as the save holds it, with no sound and no minimap symbol (`Messages::Load` S 005c2520 pushes
without the listener).

`SimEvent` is an open base record: a mod's component emits its own event types, and the presentation maps event
types to handlers, so a mod brings render and audio behaviour for its own events ([mods.md](mods.md) §8.2).

### 5.2 Order and consumption [draft]

- Events are appended in emission order: the commands of the boundary first, then the subsystems in the fixed tick
  order (LC §4.2), then `onLogicTick`. Each carries `(tick, seq)`. A removal and a re-creation inside one tick (an
  upgrade's completion: "removed" with the building flagged destroyed, then "added", RE §3.9) keep that order.
- The presentation consumes after the tick, never inside it. Subscribers run in registration order, but none may depend
  on another's order (the original orders receivers by heap address, LC §8).
- Simulation code may handle events inside the tick [implemented, sadk-remake 1cb6bec]: `World.On<T>(owner, handler)`
  (`SimSystem.On<T>` in a system's `Start`, which runs in the system order for a new and a loaded world alike). A
  command's events reach the handlers right after the command (`World.Execute`, in a tick or in the gap before one), a
  system's right after its `Update` and before the next system (`World.UpdateSystems`); in emission order, one event's
  handlers in their systems' order; the events a handler emits in the same pass. The build's events reach no handler.
  A handler runs between systems, never inside one, so it may change the world; the order is the same on every machine.
  Nothing is held across a tick, so saves carry nothing new, and a world without handlers ticks byte-identically (the
  base game registers none). This is how mods react to the game (mods.md §14.1).
- Emission never depends on whether anyone listens, and nothing about events enters the checksum or the save.
- After a load the simulation publishes `LoadRebuildBegin`, an `EntityAdded(reason = Loaded)` for every entity in
  the original's post-load order (SF §3.6: buildings, remains and orders, flags and streets, the navy, ..., chests,
  then spawn points; a fresh map has only navy routes and harbours, deposits with growth ≥ 0, animals, doodads and
  spawn points), `MapChanged(Reinitialised)` per layer and `LoadRebuildEnd`. The presentation builds
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

As built (sadk-remake, 2026-10-16): `IWorldView` has `Map` (`IMapView`: sizes, water level, spans of heights,
patterns, grid states and territory, per-cell resources, exploration, continents, construction flags and the five
object layers), `TryGet` and `Query` (ordered by id), and `Rules` (the resolved game rules, [mods.md](mods.md) §14
item 7). The players stay core.game's view (`PlayerTable`); the engine reads them only through small interfaces it
declares, such as `IPlayerContactsView` (`Sadk.Engine/Simulation/PlayerViews.cs`), which the engine's match audio
uses for the tribe music and the battle music [implemented, sadk-remake bed9379]. `IQueries` is not built yet.

Entity views are component-shaped (`IConstructionView`, `IHitpointsView`, `IProductionView`, `IMovementView`,
`IActionTimerView`, `IMilitaryFlagView`, `IGrowthView`, ...), so a mod's component adds its own view interface and
the panels and render kinds ask for capabilities, not types ([binding] architecture §5). As built (sadk-remake
514d96c): `IGrowthView` (growth and removal counter) and `IMotionView` (the last motion sample) are engine
interfaces.

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

As built (sadk-remake a2bd808): `TickRecord.Motion` holds the samples taken after each tick from the systems that
implement `IMotionSource`, in tick order (`World.CollectMotion`). A `MotionSample` carries the from and to fine
positions, the progress, the street, the heading and the flags `FineMode`, `Queued`, `Aboard` and `Dying`. `Street` is
the street the settler serves (`CurrentStreet`), not the street of the leg it walks; which one the route spline needs
is open (§11 item 4). A sample also carries the settler's logic `Cell` (`SettlerMovement +0x128`; the original's
movement +0x04 explored test, S 006c57b0, reads it) [implemented, sadk-remake 9fb619f]; other sources leave it None.
The presentation builds each street's route spline itself and walks a step along it as `StepAlongSpline` S 006c4d90
does ([animation-models.md](../sim/animation-models.md) §3.19). Animals publish the same types: `MotionSample`,
`MotionFlags` and `EntityStateChanged` are
defined once in the engine (`Motion.cs`, `EntityStateEvents.cs`) for settlers and animals (sadk-remake 514d96c).

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

### 6.4 The settler core as built [implemented, sadk-remake a2bd808]

- **Services**: the settler services and job interfaces resolve to the first system that implements them.
- **Debug command** `core.game.debug.spawnsettlers`: no original id; refused in a session that has a game seed.
- **Measured** in the remake's tests, against SJ: ticks per cell on flat ground 18, 17, 17, 17, 18, 17, 17, 17; fine
  steps 5, 4, 4; factor 0.8: 22, 22, 21, 22, 21, 22; 0.6: 29, 29, 29, 28, 29, 29; 0.4: 44, 43, 43, 43, 43, 43; downhill
  and water as flat (all as SJ §3.8.1). A 0.4 cell after flat cells on `MP_2P_steinfjord` took 41 ticks: the carry-over
  of a faster cell can end a slower one early (SJ §3.8.1).
- **Measured, going home**: a homeless settler's strays start at tick 3 + 19k, exactly 27 strays with 27 random draws;
  dying starts at tick 515, the skeleton appears at 529, state 6 at 543, the settler is erased at 544 (`Died`). A
  soldier with 3 hit points dies after 3 strays. A settler that reaches its home is in state 2 at tick 39 and erased at
  40 (`Entered`, with `Into`). The stray count matches SJ §3.4, the dying times SJ §3.2 (dying time 28, skeleton
  after 14) and the removal ticks SJ §3.3.

### 6.5 The street net as built [implemented, sadk-remake fb451d1]

- **Seams**: the village, the settlers and the transport plug into the street net through `IStreetNetHooks`
  (registered with `AddHooks`). Without them nobody carries, nothing is ordered and no building blocks a flag's
  removal. `FlagQueue` is null when no navy is loaded. `StreetType` is an engine type.
- **First carrier**: a street orders its first carrier of the good whose `GoodRulesDef.StreetCarrier` is set
  (`good_helper`); the data stage attaches that rule (§6.7).
- **Scripted sessions**: `Sadk.Headless world --commands=<file>` runs one command per line (tick, command id, the
  fields as JSON) and can log the session; the match mode replays such a log (`replay=`).
- **Measured**: an 18-command script starting at the castle flag (46, 55) built 6 streets and 7 flags, the split at
  (49, 55) included; its replay gave 128 net-tick checksums, none of which differed.

### 6.6 The living map as built [implemented, sadk-remake 514d96c]

- **Presentation**: `AnimalFeed` takes the animals from the motion samples. The render type is the animal type's
  `gfxName`; it plays Walk while moving, Stand1 or Stand2 at rest (chosen from a private presentation stream seeded
  0x5432ACE0, §8), and Dying once. `DepositGrowth` scales a tree by (min(1, 3g), g, min(1, 3g)), raises a field's
  wheat by g and sinks a disappearing deposit by `depletedTicks / 20`; `growthWidth` and `growthHeight` come from
  `visuals/map-objects.xml`.
- **Ambients**: the original's ambient sound emitters and swarms are presentation only (the swarms are dormant,
  `../sim/ambient-swarms.md`), so the living map simulates nothing for them.
- **Measured**: 20 maps run for 2000 ticks, twice, gave equal state hashes; about 0.4 ms per tick on average
  (noisy).

### 6.7 Transport as built [implemented, sadk-remake a9f6762]

- **The original's good rules**: `GoodRulesDef.AttachOriginalRules` attaches, in `core.game`'s data stage, the rules
  to `corn`, `wood`, `stone`, `good_helper` and `fish` by the literal ids the executable compares (each with its
  address: VB §8, MR §3.8). The registry fingerprint changed with it from 22926df0 to 142868c8.
- **Checksum**: the layout of `CarrierMovies` and of the three subsystem bytes is the remake's own.
- **Read as inferred** (the original's code not followed to the end): a claimed package that is not carried is
  released, not discarded, by `ISettlerTransport.DiscardPackage`; a free package in a carrier's hands heads for the
  flag at his `RouteTarget`. **Not yet**: the trimming in `AssignToStreet`.
- **Measured** (`MP_2P_steinfjord`): a woodcutter site at (46, 60) with a street of 5 cells, (46, 59) to the castle
  flag (46, 55), length 10. Tick 0 the street orders a carrier, 1 he is linked, 11 and 22 packages are created at the
  castle, 80 the carrier stands at the street's middle, 120 the first package leaves a flag, 238 and 486 planks are
  delivered. A blocked carrier (blocked from tick 120) got `!flag blocked` at 1791 and 3591 (1,671 ticks after his
  first try, then every 1,800) and gave up at 3601, 3,481 ticks after it (ST §3.9: the message every 180 failed
  tries, the give-up past 360). A free package on a site flag was assigned to the castle at tick 85 and delivered by
  244.

### 6.8 Construction and production as built [implemented, sadk-remake 3adb8f5]

- **Measured, reference for a live check against the original**: from the command to `!Building constructed` takes
  about 668 ticks for a woodcutter 4 cells from the castle. In the remake (`MP_2P_steinfjord`, placed at tick 0 at
  (46, 60), a street of length 10 to the castle flag): builder at 2, carrier 12, helpers 22 and 33, completed 668,
  worker 769. Test session: first package 22, first delivery 257, first stroke 277, completion 666.
- **Measured, float32 construction** (VB §8): with transport, a pause after 120 strokes gives 4 requests on continue
  (`remainingB` = 0.5000005); 121 strokes per unit; completion on the drop below 0 (main total 4: stroke 480, the
  117th of the 4th unit).
- **Statistics** are in the remake's state hash only; the original's checksum has no statistics section
  (`ComputeChecksum` S 00784080).
- **Open**: the AI hooks; save and load (the checksum is written in `StoreForChecksum` order, without section
  tags); `ConstructionChanged` is raised per stroke. The military, the barracks, the sacrifices, the upgrades, the
  gatherer and specialist jobs, the navy and the catapult followed (§6.9 to §6.15).

### 6.9 The military as built [implemented, sadk-remake 848852d]

- **Measured** (`MP_2P_steinfjord`, command script `attack.commands`, the same in two runs): the guard house is
  completed at tick 1147; claymores are ordered at 1155 and spawned at 1176; the first soldier is present at 1352
  (the territory becomes active), the second at 1373; the attack at 1400 posts `!You are under attack!`; the enemy
  castle spawns its 10 stocked soldiers at 1410; the first strikes fall at 1686; `!attack failed` and
  `!attack averted` at 1785; the attacker dies at 1815, the fight is deleted at 1986 and the guard house is refilled
  at 2003.
- **Kept from the original** in both modes: the paired-type comparison that is always false, attacks on own and
  allied buildings, the double kill credit of an overkill (MI).
- **Crash guards in both modes**, where the original reads unchecked: an allocation index of −1; an empty attacker
  list or no path in the gathering and origin steps; an undefined level in `ConquerBuilding`. Kill credit goes only to
  valid slots.
- **Removal reasons**: a captured building leaves with `Transferred`, one destroyed by a catapult with `Destroyed`.
- **Views for the attack menu and the music** [implemented, sadk-remake 8f20eb9, cc0b7e4]: `IFightView` has `Active`,
  `StartCountdown` and `CountByKind` (the fight box and actions 11 / 12); `IAttackQueries.AvailableAttackers`
  (`GetAvailableAttackers` S 00575dc0, with its transient cache) and the per-kind count of
  `Military_CountAttackersByKind` S 00575fd0 (with `GetAttackAvailability` S 005759f0; military §3.5) feed the attack
  slider's labels; the remake's callers all use the transient cache, and the persistent one the computer player's
  caller passes (S 0059e930) is forwarded once the AI's attack half is built ([TODO] S 005a0dd0); the engine view `IFightListView`
  answers `FightList::IsPlayerInvolved` S 00573ad0 for the battle music. Compatibility mode needs the original's x87
  rounding of the attack count in the slider and in both dispatches, `(int)(float)((float)(n·f) + 0.5f)`, not a
  double-precision product ([military.md](../sim/military.md)): the two differ at some fractions.
- **Views for the presentation** [implemented, sadk-remake 9fb619f, b4dbe0c]: `ISoldierView.Opponent` (a standing
  soldier faces it, `CharacterSoldier::Update` S 006c7f80 / `FaceEntity` S 006c7b10) and `IsPresentInBuilding`
  (S 00658f90, the soldier's inside flag); `IMilitaryBuildingView.CatapultFireStamp` (`NVillage::Catapult +0x18`, the
  shot sound).
- **Open**: capture (built, not yet exercised in a run); `FindOrderForSoldier`; the AI hooks; the hook of the heal
  sacrifice 1003. The catapult is in §6.15; the sea branches, the soldiers' ship states and order category 6 are
  in §6.14.

### 6.10 Barracks, statistics and victory as built [implemented, sadk-remake 6860305]

- **Measured**: the barracks trains one soldier per 333-tick cycle. The statistics series are sampled at ticks 0,
  600, 1200 (series 0 and 7), 1 and 601 (3 and 5), 2 (1), 3 (2 and 4) and 4 (6), at most 960 samples per series
  (PV §3.11). The two live victory cases of PV §3.7 replay with the original's `stateTime` (246, 146, 246, 0 and 277,
  277, 177, 0). `0x2002B` eliminates and declares the winner in the same tick.
- **The victory state** is saved in the remake's extension [implemented, sadk-remake 8d0b24a] (§9.1); the original
  loses it on load.
- **`!DEFEAT`** [implemented, sadk-remake 2509f83]: posted only in a network match, as the original's
  `VictoryConditions::CheckPlayerEliminated` S 00535b90 does through `NComm_Manager_IsRole0` S 004083d0, and only for
  an eliminated player of kind 3 (PV). The session's mode is `MatchSetup.Network` (setup form 3, `CommandLog`
  format 3; forms 1 and 2 are still read); offline campaign maps post no `!DEFEAT`. The original saves the letter
  as its composed, localised text (S 00535b90, S 005c05b0; PV §3.6.1), so the message carries
  `MessagePosted.TextFormat` (`VictorySystem.DefeatLetterFormat`, `"{0}: {1} ({2})"`): the message store composes
  the text in the local language and keeps the result as the message's key with an empty argument, so a save holds
  the composed string as the original's does.
- **Victory mode 5 and the quest-0 slot** are built with the map-script host (§6.18).
- **Open**: the lock maps (PV §3.10); `FinishGame` and the profile write. `Player::Update` is in §6.15.

### 6.11 Sacrifices as built [implemented, sadk-remake 322de69]

- **Measured** (QS §3.2.5 to §3.2.8): carriers ×3, production ×0.75, the own damage bonus 1.4, armour 1.2, the worker
  pause aimed at the enemy with divisor 1/3 (effective 3.0); a workshop's 333-tick cycle becomes 250 under
  `sacrifice_prodSpeed` (ceil(333 × 0.75)); the territory expansion range grows by 5; the sacrifice is removed exactly
  at start + duration.
- **Seams**: the effect event is `SacrificeEffectApplied`; `Building.TerritoryBonus` is cached and pushed after each
  territory rebuild.
- **Lua**: `sacrifice_execute` runs through `ISacrificeScript` (§6.18); the cinematics' `EndCinematic` is the command
  `core.game.cinematicfinished`. The save sections are written (§9.1) but no whole-world round trip exercises a
  sacrifice yet.
- **Effects** ([renderer.md](renderer.md) §16.1): the sacrifice movies and the building buffs [implemented,
  sadk-remake 5281ab9].
- **The blessing of the fields** (QS): the original doubles only the good `corn` (the literal compare at S 00661c6f in
  `GetEntryWithModifiers` S 00661c50, `ApplyAmountDoubling` S 00663450 while flag 12 is above 0), so the Bavarian
  `farmBav` gives 4 instead of 2 per harvest and the Egyptian `farmClay` (`egyptCorn`) stays at 1. core.game keeps
  that; the decision is the game rule `production.productAmount` ([mods.md](mods.md) §14 item 7), which the refined
  mod wraps to double every farm's grain. Measured on `MP_2P_fata_morgana`: Bavarian 2 → 4, Egyptian 1 → 1
  (compatibility) or 2 (refined).
- **Grouped goods**: sacrifice sites receive grouped goods only as entries of `InitFromTribe` S 005c1370 groups; a
  temple's product `sacrificeGood` collects every sacrifice cost, the olympic flame's `sacrificeGoodOlympicFlame`
  lists six goods, so a flame never receives milk and never starts such a sacrifice, in the original as in
  compatibility mode. The refined mod's `transport.groupMembership` rule admits the need.
- **Open**: the heal for stocked soldiers; border contact; the navy and script effects.

### 6.12 Upgrades as built [implemented, sadk-remake 8225872]

- **Measured** (a Scots guard house at (51, 56) upgraded to a tower): completed at tick 1032, upgrade started 1200,
  builder 1201, carriers 1221 to 1397, work done 3567, message 3575, type change 3576; input
  plank 3 and `stoneScots` 4. The same upgrade at (52, 56) is blocked with reason 2: the tower fails the medium slope
  rule (VB §3.13).
- **Seams**: the `UpgradeChanged` event carries the upgrade's progress; `IUpgradeQueries` answers the block reason.
  The transport's site test uses the effective construction (S 00652b70, VB §3.13); with the building's own
  construction no upgrade material was ever sent.
- **Open**: the other readers of the effective construction (S 0055bf90): the AI's `MilitaryMap::UpdateCell`
  S 00586790, `StreetRouteOptimizer::ProcessEntry` S 005a52c0, the missing-goods overlay (S 00640418, S 0063ff9f) and
  `RefreshAvailability` (S 006240e6).

### 6.13 Gatherers and specialists as built [implemented, sadk-remake 2540ec0]

- **Measured** (`MP_2P_steinfjord`, a Scots woodcutter): completed at tick 666, deposit linked 717, the worker
  leaves the castle at 767 and arrives at 897; `LeaveBuilding` 898 (44 ticks, an uphill cell), `MoveToDeposit` 942,
  `Working` (kind 4) at 956 for 55 ticks, the tree is depleted at 1011, the wood is in his hands at 1015, put down at
  1038, `EnterBuilding` 1046, then a rest of 222 ticks; the first log reaches the castle at 1202, the next ones at
  1423, 1874, 2358 and 2841. The stone pit makes its first stone at 1043, which reaches the castle at 1282. The fisher
  works in 333-tick cycles. A farm sows at 2832 and 4058 and reaps at 5276. A scholar sets an iron sign at 985 with
  `!Found Resource` (SJ, MR §3.8).
- **Data**: the good flag `FoundOnBuildableGround` names the good a sign on buildable ground reports, in place of the
  water good's literal id 0xa9676263 (`PlaceResourceSignAndNotify` S 0077b2f0, MR §3.8).
- **Open**: `Worker::GetWorkProgress` S 0065ce80; `StreetLink_UnlinkFlagSpecialist`. A new package's
  `EntityAdded` carries its cell (§6.15).

### 6.14 The navy as built [implemented, sadk-remake 71c3954]

- **Measured** (`MP_6P_ship_ahoi`): the harbours link to players 0 to 4 on tick 0; player 5's harbour (id 197897)
  does not link, which is not checked against the original. A shipyard placed at tick 1 at (37, 70) gets its
  constructor at 2 and creates the ship (id 204165) at 162 on (36, 69); a plank arrives about every 359 ticks over
  the one carrier street, a builder's visit takes about 22 ticks of walking plus 31 strokes, and `!Ship
  constructed` comes at 4426. The ship takes 12 visits of 31 strokes (navy §3.3); a Bavarian ship (speed 0.06)
  needs 17 ticks per cell (navy §3.4); an idle anchored ship takes up ferry service after at least 102 still ticks
  (navy §3.7, §3.8).
- **Seams**: one street planner per player in the navy (the original has one for all players, each call naming
  the player, navy §2.1); the ship links to its shipyard through `Ship.Shipyard`, not through the village
  construction record (+0x50) as in the original (navy §3.2). The constructor's job builds the ship, so a ship
  site no longer sends its builder home (§6.8).
- **Crash cases**, where the original writes through a null or dummy docking position (navy §3.1 rules 3 and 4):
  no docking position found, and a search toward the dummy position (−1, −1), reserve nothing and are refused.
- **Checksum**: routes and harbours are hashed in the remake's own form. The navy's `initialized` byte is written
  only by `WriteState` (the save), as the original leaves it out of the state hash (navy §7); the net-tick
  checksums therefore differ from those of earlier remake builds.
- **Cargo**: a package's cell is the ship's cell at loading and is not updated while the ship sails.
- **Part 2** [implemented, sadk-remake 0a8d5b6]: the flag queue (`FlagQueue`, handed out by the street net:
  settlers wait for the ship at a harbour flag, park, are called out, board with the original's `EnterShip`,
  cross and walk on; ST §3.13, SJ §3.8.6, navy §3.9); expeditions (the route commands `0x2001A` / `B` / `C` as
  `core.game.assignship` / `abortexpedition` / `foundcolony`, the soldier order of category 6, the materials as
  need-category-1 requests of the ship, sailing, waiting for orders, founding; navy §3.10); sea attacks (the
  harbour finders, the ship of `SendSoldiersBySea`, the mission, the soldiers' ship states 0x21, 0x28, 0x31 to
  0x34 and 0x37; navy §3.11); `TransferShipsOfPlayer` (navy §3.2; nothing calls it yet, the remake has no
  `TransferPlayerAssets`); goods crossing a sea street to a site behind the far harbour; the ship feed and the
  swell in the character layer (AM §3.17).
- **Measured** (`MP_6P_ship_ahoi`, the expedition script, the same in every run): site at tick 1, ship 162,
  `!Ship constructed` 4398, ship assigned 4500, soldier 4571, `!Ship waiting for Orders` 5929; at 5951 the guard
  house is placed and completed at (46, 55) with the harbours linked, a street and a sea street; garrison 6031. A
  sea-attack mission passes its states 0 to 7 at +1, +2, +69, +71, +72, +480, +502 and +503 ticks after the
  linking.
- **Crash guards** (both modes), where the original reads unchecked or never ends: `ChooseStartHarbor` null → no
  move, the state advances; `FindBuildingPosition` with a range ≤ 0 → no position; `TransferShipsOfPlayer` with
  `from == to` does nothing (the original's loop never ends, navy §3.2); mission state 0 without an own route end
  → state 1; state 3 without a fight or a defender end → 7; `SendSoldiersBySea` without a landing harbour sends
  nobody; an attack origin with a harbour and no building → the soldier's cell (MI §3.5).
- **Views for the selection** [implemented, sadk-remake dd389da]: `IShipView` gained `Route`, `Shipyard`,
  `LyingStill`, `ExpeditionActive`, `ExpeditionState`, `MilitaryActive`, `Packages`, `CargoSettlers`,
  `MilitarySoldiers`, `ExpeditionUnits` and `ExpeditionOrders`; `IShipRouteView`; `INavyQueries` (the block reasons of
  `GetAssignShipBlockReason` S 005ba970 and `GetFoundColonyBlockReason` S 005baa50, a ship's requests, its name key);
  `ISettlerView.AboardShip`. The route actions read the game's selection and send the route commands as the
  original does ([ingame-ui.md](../sim/ingame-ui.md) §3.5, [game-commands.md](../sim/game-commands.md) §5.1).
- **Measured** (`MP_6P_ship_ahoi`, god mode): an expedition reaches state 5 at the far harbour with 3 packages and
  1 soldier; without a street from the stores to the harbour flag it waits in state 3 with its soldier order open,
  the original's rule ([navy.md](../sim/navy.md) §3.10).
- **Open**: why player 5's harbour on `MP_6P_ship_ahoi` does not link; the soldiers' ship states are not tested
  end to end; `TryCompleteOrderAtCurrentPos` is a stub; the unfinished ship's look, the cargo and expedition
  overlays, `ShipFX`.

### 6.15 The catapult, the player update and loose ends as built [implemented, sadk-remake c16efa5]

- **Catapult** (MI §3.10): the target search, the attack movie (rotation, shot, rotation back), `Fire` (the
  ammunition is the first cost of the product slot's good, the tribe's stone, taken out and requested again unless
  a cinematic runs; the stamp is `GameSystem+0x78`; flight `trunc(distance × 5)`), the worker's mode 5 and states
  0x1d / 0x1e, the projectiles of a removed building, the `CatapultAttack` step written at its place in
  `WriteMovies`.
- **Measured** (`MP_2P_steinfjord`): player 0's catapult destroys player 1's guard house in 9 shots; per shot
  a rotation of 15 ticks, a flight of 55 ticks over 11 cells, the shot 25 and a rest of exactly 55 in state 0x1e;
  the first hit takes 10 hit points. Player 1's catapult with production switched off never selects a target; its
  candidates list player 0's catapult twice and the seed cycles through them.
- **`Player::Update`** (PV §3.9) in step 3 of the tick (after the street planners, before the village): the 22-tick
  recount with `CollectPlayerUnitCounts`, the building counts in phase 1, `!low resources` and `!low soldiers` in
  phase 10 after tick 50, posted or refreshed. The strength and population statistics read the stock cache and
  follow it. **Measured**: the warnings come at ticks 53 and 75, for player 0 only.
- **Views**: the building panels read views only ([renderer.md](renderer.md) §15.3).
- **A new package's cell**: `CreatePackage` takes the cell and fine position the package will have (the settler's
  hands, the flag) and sets them before `EntityAdded`, which keeps its place in the order; the original raises
  "created" inside the constructor and its observer reads the position later (ST §2.5).
- **Pattern changes** rebuild the terrain blocks that hold the changed cells ([renderer.md](renderer.md) §10.5).
- **Open**: `Worker::GetWorkProgress` S 0065ce80; a projectile lands at launch + flight − 1, so
  `ProjectileAdded.ImpactTick` is one tick late (presentation only); a catapult site whose production was switched
  off at placement never finished (not investigated); `MapData.Blocks.PatternIds` is not refreshed on pattern
  changes.

### 6.16 The free game as built [implemented, sadk-remake 636da4c]

- **Menu**: `core.game` adds "Free game" to the main menu ([mods.md](mods.md) §11a.1) and opens the overlay
  `core.game.freegame {map?, back?}`; the handlers `.map`, `.row`, `.options`, `.choosemap` and `.start` drive it
  unattended, `core.game.gameend` the end dialog.
- **Panel** (FS §3.4): built from `menufreegame.xml` with the original's rules in `FreeGameSetup`: `SetMap`
  S 005e8410 (every tribe from its combo, Bavarian at first; every team its row number; colours, computer levels
  and closed or computer rows from the map), the row controls S 005e8050 / S 005e8200, the start rule S 005e77c0,
  the start's copy of each row into the slot of its chosen start position S 005e7350, the start markers
  S 005e7cc0.
- **Maps** (FS §3.5): the converted packages whose manifest has `type="free"` (20: 15 `MP_*` and 5 `sp*`), titled
  from each package's `locale/<lang>/map.txt`, with its `preview.png`, in `MapListEntry::Less` order S 00612ec0
  and the row colours of S 00614ec0.
- **Start**: emits `core.game.match` with the slots, start resources, win condition, reveal and `loading=true`;
  the match shows the loading panel of `menuLoading.xml` and loads in steps [implemented, sadk-remake 2026-10-25]: the
  bar moves by the original's stages and weights (`EmitTick` S 00683b50, 600 in all: scene 50, map renderer 50, config
  50, characters 100, building configs 100, rest 50, elevation map 100, finalizing 10 × 10; FS §3.9), a frame is drawn
  whenever the status text changes and while the world is built on a worker thread, then `!completed` at the full bar
  and a 2 s fade-out. The remake's work stands at the original's stages by counterpart [inferred] (`LoadStages`,
  `src/Sadk.Client/MatchLoad.cs`); an unattended start runs the same steps without frames.
- **End**: `GameEndDialog` from `menuGameEnd.xml` (FS §3.10): `!Continue Game` goes on, `!Quit` leaves through
  the statistics to the main menu, as the back button does.
- **UI**: `UiBuilder.Kinds` lets a screen own widget kinds (`UiCombo` for `comboboxnew`, `UiList` for
  `listbox2`); shapes take borders per side.
- **Not built**: the row portraits, the player previews, the picture slider.

### 6.17 The computer player's economy as built [implemented, sadk-remake 8ba0948]

- **Place in the tick**: `ComputerPlayerSystem` (`core.game.ai`, step 16, after the statistics; `NAI::System::Tick`
  S 00581a30). It plays through the simulation's own functions inside the tick, as the original does (AP §1): it
  places buildings, flags and streets directly, not through commands.
- **Activation and ids** (AP §2.3): a new game's computer slots are activated through `INewPlayerHandler`
  (`NAI::System::ActivatePlayer` S 00581c40, `Player::Activate` S 00582870): the castle draws its building id, the
  AI cell (castle + 1) and the flag (castle + 2); every new building then draws its productions, its new needs and,
  at a new coarse position, the new AI cell. The ids of a free game with computer slots follow the original's.
- **Built**: the building mirror, the cells and the cell validator, need creation, the needs arrangement with the
  group needs, the needs construction and its arbitration, the site search and score, the street builder (the AI's
  own street planner), the expansion (resource, territory and military maps, the military building creation) and the
  economy controls (lock smith, production control, cell clearing, depot creation, destruction, food arrangement),
  with the original's order owner ids (AP §3).
- **Measured** (`MP_2P_steinfjord`, a computer Scots player at level 2, 20 000 ticks): the sites come in the order
  sawmill (tick 129), stone pit 290, guard house 529, woodcutter 672, …, locksmithery 7980, …; at the end 44
  buildings (7 of them sites), 60 flags and 76 streets; the territory grows from 271 to 360 within 3000 ticks; a tick
  takes about 3 ms with an active computer.
- **Tests**: the mechanic tests run with `MatchKit.WithoutComputers` (computer slots played as remote humans).
- **Script switches** [implemented, sadk-remake 2509f83]: the scripts' `ai_*` functions drive the computer players
  (§6.18, LR §3.6).
- **Save and load** [implemented, sadk-remake 8db0d0a]: `NAI::System::Store` S 00581ad0 and `Load` S 005821f0 in
  the original's layout, with every section name, version and version gate (AP §7). References are resolved after
  everything is read, as `Player::PostLoad` S 00582e10 does; the values the original does not save are looked up
  again where its Load functions look them up (AP §7). State the original lacks (the construction back-off pair, the
  street builder's source cell) goes into the extension of the tick-less system `core.game.ai.remakestate`, placed
  after the AI and before the sacrifices. A remake save without that extension (written before the AI was saved) is
  repaired at its first tick: the shared grids are rebuilt and each computer slot of the setup is activated again
  (S 00581c40, profile = level + 1). `World.BuiltTick` holds the tick the build ends at, so the AI's game time no
  longer lags one tick in a new game; `ConstructionOrder` starts in mode 1 (S 005a17a0).
- **Measured** (`MP_6P_ship_ahoi`, five medium Bavarian computers): first placements at ticks 210, 229, 236, 271 and
  414; after 20 000 ticks 30 to 38 buildings each. A save at tick 2500 re-saves byte for byte and every system stays
  identical for 144 ticks; at 2644 the village part differs (a castle releases a constructor in the loaded game, a
  carrier in the uninterrupted one), because the load rebuilds the village order index from the order vector as the
  original does (S 005625c0, [village-buildings.md](../sim/village-buildings.md) §7) [inferred as the only cause].
- **Open**: the military half (AP §3.10 to §3.16): its records are written in their activated state and dropped on
  load ([TODO] S 00585280 / S 00585d60), and CatapultConstruction and Casern are not registered as order owners
  after a load ([TODO] S 00582e10); the expedition; `AddHarbor` / `RemoveHarbor` when a navy object links to a flag;
  `RefreshPlayersAndResourceMap` S 00581960.

### 6.18 The map-script host as built [implemented, sadk-remake fcee142]

- **Host**: `MapScriptSystem` (step 23) keeps one MoonSharp state per world, seeded from the game seed. The property
  scripts are replayed into it (the vocabulary, `core.game` only); the map's top-level chunk runs at the `MapScript`
  build phase, `onStarted` and `onLoaded` at tick −1, `onLogicTick` at every tick; `sacrifice_execute` runs through
  `ISacrificeScript`; `Default.CallScript` takes a bare file name. An error aborts the callback and is reported once
  (`ScriptReport`). `logic.getRandom` is one `SimRandom` draw. All 168 functions of `logic`, `gfx`, `menu`, `ui` and
  `txt` exist; one not yet built reports once and returns a neutral value ([lua.md](lua.md)).
- **Quests and victory**: 40 quest slots and the `sd_` store, announced by `QuestChanged`; `VictorySystem` writes
  quest 0 into the real slots and runs mode 5 (`VictoryCond_Update` S 00535d70, PV, QS).
- **Commands**: `core.game.cinematicfinished` (`EndCinematic` and `quest_cinematicDone`) and
  `core.game.scriptcallback` (§7).
- **Presentation**: `ScriptUi` events go to `ScriptUiPresenter` (pages, letters, books and tutorials as entries of
  the message list); the map's own texts are loaded.
- **Save**: the hook `CaptureSection` / `RestoreSection`; a load runs the top-level chunk, then `RestoreSection`,
  then `onLoaded`; `onStarted` does not run again (§9.1).
- **The computer player's switches** [implemented, sadk-remake 2509f83]: the `ai_*` bindings act on the computer
  player as the original's do (LR §3.6), and the campaign maps' use of them runs (C02 to C10).
- **Measured**: C01 to C11 run 5000 ticks with no Lua error. C01's opening: the quests Intro (slot 0) and sawmillInfo
  (18) at the start, the cinematic at tick 0, Start and "1intro" at tick 1, C01_Q01 (slot 8, the temple at 76/65),
  ReachIce (15), EgyptReachPlace (2) and the tutorial chain at tick 2; `onStarted` places the Olympic temple for
  player 3, halves its stock seven times and destroys its castle.
- **Open**: the readers of the lock maps (map 0: `Village_CheckBuildingPlacement` S 005576e0 and the build menu
  S 00634db0; map 3: `SoldierTraining.IsJobLocked`); `map_createChest`; the continent rebuild after blocking doodads;
  the NPC functions `se_*`; the waits ([lua.md](lua.md) §2.8); the cinematic camera paths; the book and tutorial
  screens; the minimap's quest symbols.

### 6.19 God mode, a debug aid, as built [implemented, sadk-remake a5258b9]

Remake-only (no original id): a debug feature put together from three paths of the original.

- **Placement**: the batch-editing branch of `Building::ctor_Place` S 0055d980 / `Construction::StartWithType`
  S 0055efa0 ([village-buildings.md](../sim/village-buildings.md) §3.2), taken per owner through the village's
  seam `IVillageBatchEditing`: a god's buildings are complete at once, their territory active, the worker inside
  or a territory building's first soldier. Ship sites (size 0x10) are left out and built normally, the constructor
  making the ship from the god's stores [the remake's own, sadk-remake cc12218]: the batch branch has no ship-site
  case (S 0055d980, S 0055efa0), so it completes the site without a constructor and no ship is ever made, as the
  original's debug tool leaves it ([navy.md](../sim/navy.md) §3.2).
- **Scope**: god mode is infinite resources (the stock below), instant building (above) and full sight, nothing
  else; work, transport, production, training and garrisons run as for any player, so the god's buildings need
  streets. A god's hunter, for example, keeps the original's first wait of the lodge's `restTime` (1500 ticks),
  because his lodge has no animal linked yet when he is created inside it.
- **Stock**: `ItsLikeAJackpot` (`Cheat_FillStoreWithGoods` S 005eba50,
  [camera-input-cutscenes.md](../sim/camera-input-cutscenes.md) §3.12) made continuous: every tick, before the
  village, the system `core.game.godmode` tops every completed depot of a god up to 100 of each good of the
  tribe's goods and jobs lists.
- **Sight**: `WhatCanEyeSee` (S 005ec340) once at the start.
- **Removal**: the original's `RemoveBuilding` S 00559db0 asks the same batch-editing query and then spills nothing,
  leaves no remains and plays no collapse; god mode answers the query for placement only, so a god's destroyed
  building refunds its full cost halved onto its flag, which then stays (a finished building's normal rule).
- **Setup**: the gods are a field of the match setup, ignored in a network match (in the free-game screen a
  `GodMode` combo of the remake's own at y 202 of `GameSettingsPanel`, the next 48-px slot after the original's
  three options at 58 / 106 / 154; the original has no such element, [frontend-screens.md](../sim/frontend-screens.md)
  §2.2); the debug command
  `core.game.debug.godmode` is refused in network matches; the system has its own save section.

## 7. The way back: commands [draft]

**As built** [implemented, sadk-remake a7a220c]: a command is a record with
`[GameCommand("core.game.speed", Original = 0x20023, Version = 1)]` implementing `IGameCommand` (`Validate` without
side effects, `Execute`). The sender is envelope data (`CommandContext.Sender`, the player index the session fills
in, −1 the session itself), not a field, so a peer cannot act in another's name. `World.Execute` validates, executes
and emits `CommandResolved(sender, id, result)` for every command. `SimulationCatalog` collects commands and systems
(`[SimSystem(id, After, Before)]`, an order that must follow uniquely from the constraints) from the engine and every
mod's simulation assemblies at mod-set load; ids are namespaced, a client assembly declaring one is a load error, the
wire id is the original id or an FNV-1a hash of the id with the top bit set (collisions refused). The codec writes the
record's constructor parameters (little endian, floats as raw bits, varint counts, UTF-8, enums, nullables, lists,
nested record structs); fields may be added at the end with defaults. A command with an original id also maps to the
original's event layout (GC §2.2; verified byte for byte for 0x20023, 0x20011, 0x20013–0x20016). The UI path: a
button emits an intent (`core.game.cyclespeed`), its handler submits the command.

**As built, the transport settings commands** [implemented, sadk-remake 0e3771f]: `core.game.transportpriorities`
(0x20021), `core.game.transportprioritiesreset` (0x20022), `core.game.distributionweight` (0x2001F) and
`core.game.distributionreset` (0x20020) run as the original's executors (GC §3.4, PV §2.6). A list of 32-bit elements
maps to the original's `EventData`: link id (u32, 0), byte count (u32, count × element size), the elements as raw
little-endian values; a ragged or overlong byte count is refused, and 64-bit elements have no mapping. The refusals
are `no-such-player`, `no-such-good`, `no-such-group`, `no-such-entry` and `empty-priorities`, the cases in which the
original does not survive (§11 item 4).


- Every player action is a `GameCommand` carrying ids, cells and registry ids, executed at a tick boundary on every
  machine and validated again there [binding] §6.
- **UI callbacks into map scripts** (`quest_cinematicDone`, `createQuestUi`, `destroyQuestUi`,
  `<widget>_isClicked`, `<widget>_isPressed`) become the command `ScriptCallback(name)`. The end of a cinematic is
  the command `CinematicFinished`, so `EndCinematic` (AI, chests and sacrifices switched back, sacrifice ticks
  shifted) happens at a tick. Offline the timing equals the original's (between two ticks). As built
  [implemented, sadk-remake fcee142]: `core.game.scriptcallback` and `core.game.cinematicfinished`, which runs
  `EndCinematic` and `quest_cinematicDone` in one step (§6.18).
- **Local feedback** that the original's executors provide by direct calls (closing the street placement mode,
  refusing a waypoint) comes from `CommandResolved` events; previews come from `IQueries`. Commands travelling
  through the network (up to three net ticks) may show a pending ghost in the UI; nothing is predicted in the
  simulation.
- The selection, the placement modes, the street build mode and the message list are presentation state. The
  original allocates the selection in the logic system and keeps messages (with their remaining time) in the saved
  player object; the remake's save adapter writes the presentation's message list into the original's `Messages`
  record and reads it back, the one place the two meet. As built [implemented, sadk-remake cc12218]: the engine
  interface `IMessageArchive` hands the presentation's list (oldest first) to the save, F5 and the save panel both
  pass it, and a player whose list no presentation keeps (another machine's, or a headless run) is saved with the
  list it was loaded with; the load restores the local list through `MessagesLoaded` (§5.1). The records are the
  original's (`Message::Store` S 005c0300: `Message` v2, the time left as a float, cell, text, second text, type,
  read flag, unique id, argument); they enter neither the state hash nor the checksum.
- While the session hangs: faithful mode drops commands as the original does (GC §3.1), refined mode refuses them
  with a visible reason.
- **The typed cheats and the chat.** The remake sends `WhatCanEyeSee` and `ItsLikeAJackpot` as commands of the local player
  (`core.game.cheat.explore`, `core.game.cheat.jackpot`, refused in a network match) and `WhatTheHell` as the speed command
  `core.game.speed` (20), so the command log and a replay hold them; chat lines travel through `Sadk.Session.IChatTransport`,
  a session seam beside the command transport, not through the command queue.

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

### 9.1 Save and load as built [implemented, sadk-remake 8d0b24a]

- **File**: the original's container (SF); the map part in the map-file layout; the logic part (`Game File Logic`
  v6: the random generator, players, village, settlers, transport, military, street net, AI, statistics, script and
  quests, sacrifices, chests); then the remake's block (the match identity, the setup, the session values and per-system
  extension sections with their lengths) behind a 16-byte footer the original never reads. `S2mWriter` writes all
  31 shipped maps byte for byte. `tools/sadk_crypt.py` reads the remake's `.aav`. Strings are Latin-1.
- **Sections**: `ISaveSection` (`Save`, `Load`, `Relink`, `PostLoad`, `AfterPostLoad`), ordered by After / Before.
  A load checks each section's name and version.
- **Load** is the normal build, with the logic part read between the map script and the post-load
  (`LoadRebuildBegin` / `LoadRebuildEnd`); a load that takes a unique id or draws a random number fails. Rebuilt as
  the original rebuilds them: the construction flags, the object layers, the indexes, the stock running total; the
  street planners are cancelled. The game speed is not restored, as in the original. The map script runs its chunk,
  `RestoreSection`, then `onLoaded` (§6.18).
- **Entry points**: `SimHost.Save` / `SaveFile`; headless `--save`, `--load` and `--roundtrip`; the match option
  `load=<file>`; **F5** saves into `<user data>/saves/` under the original's default name.
- **Measured**: the round trips are exact (checksum and state hash at every tick, a byte-equal re-save) for the
  construction, fight and upgrade sessions and for all 31 maps at ticks 0 and 3000.
- **Beyond the original**: the remake keeps state the original loses on load: the active deposit order, the animal
  time stamps (the original's post-load clamp changes later checksums on `sp02_perpetual_ice`), the victory state,
  the ship sinking timer, the open-need index and a few appended fields. Ships go into an extension (the map part's
  navy writes 0 ships), and so do the buildings' remake-only fields (the regeneration tick, a sacrifice's free ticket
  and target player), in the "Remake Buildings" section of the tick-less system `core.game.village.remakestate`: the
  `VillageBuilding` record keeps the original's v0–v2 layout (`Building::StoreSavegame` S 0055c470, `Load`
  S 0055d290) [implemented, sadk-remake p0 round]. The messages are written as the original writes them, from the presentation's list (§7);
  the AI is written in the original's layout (§6.17); the chests and the quests are written in empty or default form
  into the original's sections. The remake part (v3) and the command log (format 6) record the match identity
  (`MatchIdentity`): the registry checksum, the match set (mods with their versions), the systems, each game rule's
  layers and the startup settings; a load or replay warns of each part that differs from the running mod set's
  ([mods.md](mods.md) §10, §14 item 7). Older versions are still read with what they record (remake part v2: the
  checksum, the systems, the rules; command log format 5: the checksum, the mods, the rules). The military's transient
  path cache is empty with stamp 0 after a load (the original
  stamps it with the load tick, `Attack::PostLoad` S 00575800, MI §7). The saved next-tick time is the float32 sum.
- **Open**: the AI's military half (§6.17); a loaded game parts from the uninterrupted one where the village order
  index is rebuilt (§6.17, as the original); reading the original's saves of older
  versions (the shipped `C02.sav` is plaintext from an older build, SF); ships, expeditions, the catapult, the
  specialists, fishing, hunting and sacrifices are not yet exercised in a whole-world round trip.

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
3. Settled 2026-10-16 (Ghidra): the military defaults are one source, `NPlayer::Military::ResetDefaults` S 005c0930
   calling `MilitaryConfig::GetDefaultDistanceAllocationFactor` S 00553f40 per tier (0.1 / 0.3 / 1.0; +0x14 and +0x18
   set to 0; +0x1c from the float at 007d877c). The unique id counter (S 00889ad0, 0 in the image) is written only by
   `AssignNew`, by `LogicId_ResetGlobal` at `Shutdown` and by `LogicId_LoadGlobal` from `NLogic::System::Load`, which
   the map part runs too: an empty world starts at 0, a world from a map at the map's stored counter. Still open: a
   reconnect resets `S` to speed × 4 and the sub-tick to 0 on every peer, which the network transport will need a way
   to do in `SimHost`.
4. Decisions the remake took while the maintainer was away, to confirm, per subsystem:
   - **General**: exactness against the original (ids, grids, order) wherever it does not need the AI; the building
     command validated at execution only in the refined look (the original does not check lock, tribe or construction
     time there); no chests offline (as the original); map scripts deferred to campaign maps (the 20 shipped
     free-game maps have none); user maps whose stored ids collide with the counter behave as the original (a
     duplicate within a class replaces the earlier object) with a warning; no start-position shuffle.
   - **The match from a map**: the per-net-tick checksum keeps the original's coverage (map, resources, doodads and
     spawns stay out) and the whole state goes into a separate state hash; a unit type the registry lacks leaves the
     object out with a warning (the original inserts default properties); the whole-map exploration notice goes to
     every player (the original sends it for its local player); a map reference's hash covers the world part's bytes
     including mod overlays.
   - **The placement core**: where the original reads memory unchecked (an anchor or flag cell outside the map, an
     `IsGroundLevel` neighbour outside the vertex grid) the remake returns false or skips; with no batch open the
     construction flags are recomputed over the area's bounding rectangle instead of the original's spiral (same
     result); computer slots draw their AI ids through the computer player (§6.17), so the ids follow the
     original's in free games with computer slots; the refined-mode check of 0x20002 waits for a mode switch.
   - **The settler core** (§6.4): the motion sample's `Street` is the street the settler serves, not the street of
     the leg it walks; the route spline does not read it: the presentation takes the leg's street from the map's
     object layer 2 at the step's cell or its target cell, as `CharacterMovement::SetPath` S 006c5160 does
     (S 00665160); settler services and job interfaces resolve to
     the first system implementing them; the debug command `core.game.debug.spawnsettlers` has no original id and is
     refused in a session with a game seed.
   - **The build mode** ([renderer.md](renderer.md) §15.3): **B** opens the build menu without a cell, the
     original's "choose a type, then click cells" mode, which the original has but never reaches (ingame-ui §3.8.10),
     as the remake's own addition; the cell marker is a translucent hexagon where the original lays the decal
     `buildingselect.dds` (style 1 [inferred], S 006b0d00, [rendering.md](../sim/rendering.md) §3.14); the info box
     has its fade-in only.
   - **The street net** (§6.5): `StreetType` is an engine type; `0x2000B` is always refused (result "no-effect"; the
     original's executor does nothing, GC); no owner check on `0x20005` and `0x20009`, as in the original, until a
     mode switch exists; the hook defaults (nobody carries, nothing is ordered, no building blocks); `Initialised`
     and `NetContinents.InUse` are set at `Start` [inferred]; the checksum writes each record's fields in the
     original's order but the flag cores first rather than interleaved as `StoreForChecksum` does, and the flag-stack
     part leaves out each package container's active byte, so the street net's checksum bytes differ from the
     original's [inferred]; a split whose half cannot be built hands the carrier to the other half (the original
     would crash).
   - **The living map** (§6.6): guards against division by zero (move distance 0, idle quotient 0, spawn interval 0,
     empty spawn list); the roam search refuses a start cell outside the map (the original reads past its grids,
     MR §3.10); the removal reasons `Obstructed` and `Destroyed`; the sowing's `SetCellPattern` takes effect at once,
     as the original's (`defer = 0`, MR §3.4); growth visuals step per tick instead of the original's 0.1 s fade
     [presentation]; the good flag `GroundResourceOnWater` replaces the hard-coded fish id.
   - **The map changes in the presentation** ([renderer.md](renderer.md) §10.5, §12, §15.2): the border posts are
     laid again on a height change (the original keeps their old height until the next territory change, so its posts
     float or sink, RE §3.8; presentation only); `IFlagView.Harbour` added for the harbour flag model. A pattern new
     to the map is not a deviation: it keeps the record and draw order it has had since the map was shown, since the
     original makes records for every pattern property in `CTerrainPatternManager::Init` S 006bb3a0 (RE §3.3).
   - **Transport** (§6.7): the original's good rules attached by their literal ids in the data stage
     (`GoodRulesDef.AttachOriginalRules`; registry fingerprint 22926df0 → 142868c8); the checksum layout of
     `CarrierMovies` and the three subsystem bytes is the remake's own; a claimed package that is not carried is
     released, not discarded, by `ISettlerTransport.DiscardPackage` [inferred]; a free package in a carrier's hands
     heads for the flag at his `RouteTarget` [inferred].
   - **The transport settings commands** (§7): refused only where the original does not survive (a sender outside
     the player table, an unknown good, no group, an entry out of range, an empty priority list, GC §3.4); 64-bit list
     elements get no `EventData` mapping.
   - **Construction and production** (§6.8): an order's category is fixed when it is linked (the original recomputes
     it on removal); commands for a missing building are refused (the original ignores them); `IsOccupied` skips
     empty slots among the first `workerCount` (in the original a hole can hide a later worker, VB §3.18);
     `RebalanceInputRequests` is approximate; remains that name a doodad only warn (none in the shipped data).
   - **Selection and street placement** ([renderer.md](renderer.md) §15.3): **Esc** cancels the street placement
     (the original's Esc reaches only a visible box's close button); the action panel closes only after the cursor
     has been over it and left; the street preview is extended click by click and replaced by the simulation's path
     on its event (the original re-plans the whole chain [inferred]); the first segment's pre-tests are folded into
     the searches; after a street is completed an extra `0x20007` can go out and is refused (as in the original's
     network flow; harmless); no separate water-street mode, the water preview is a plain strip; the marker's look and
     the tints are the remake's own.
   - **Characters** ([renderer.md](renderer.md) §9): the height of a figure doing inside work uses this frame's
     posed box (the original's the previous frame's); its notifier box is the look's bounds, not the original's 10×
     radius; a spline segment past the street's end falls back to the straight step (the original reads out of
     range); a work object whose deposit is gone is let go (the original keeps the pointer); a zero-length direction
     causes no turn and no fall (the original produces not-a-number).
   - **Ships in the selection** ([ingame-ui.md](../sim/ingame-ui.md) §3.5): the pick list holds only buildings and
     route buoys, so removing another map object does not reorder it (in the original it can, S 0068cff0, which
     decides only a tie between a buoy and a building on one ray); `Math_FastSqrt` is not used in the ship pick
     (only which of two ships is nearer can differ).
   - **Goods** ([renderer.md](renderer.md) §14): the spill quirk and the `MergeStacks` transform are reproduced, with
     the refined switch `ItemPile.PlaceMergedItems` (off); carried goods keep their own size (the character scale 1.2
     is in the skeleton and taken out of the attachment rotation); the holder rule runs once per frame (the original's
     per tick); a new held-good key changes the animation at once (the original's a tick later); no notifier per item;
     items cast shadows; `IPackageCargoView` is declared but not implemented.
   - **Military** (§6.9): crash guards in both modes (an allocation index of −1, an empty attacker list or no path in
     the gathering and origin steps, an undefined level in `ConquerBuilding`); the faithful quirks kept (the
     always-false paired-type comparison, attacks on own and allied buildings, the overkill's double kill credit); kill
     credit only for valid slots; the removal reasons `Transferred` (capture) and `Destroyed` (catapult); the
     catapult's fire stamp is the start clock plus one f32 tick interval per tick (the first tick [inferred],
     §6.15).
   - **Barracks, statistics and victory** (§6.10): `!DEFEAT` goes to every other active, not eliminated human slot,
     and only in a network match (`MatchSetup.Network`, the original's `NComm_Manager_IsRole0` test) for an
     eliminated player of kind 3; `PlayerDefeated` is raised
     for unused slots too, on tick 0 (`WasActive` false); `VictoryProgress` per active player, on change only;
     `0x2002B` accepts any sender; index guards on `0x20018` and `0x20017`; crash guards (a good with no history, a
     level gap in the promotion, a slot with no level-0 soldier, a kind with no levels, an owner out of range); the
     victory state is saved in the remake's extension (the original loses it on load, §9.1); `Player::Update` runs in
     the player table's step without a system of its own (§6.15).
   - **Sacrifices** (§6.11): tests place the flame with `PlaceBuilding` (no placement test); the effect event is
     named `SacrificeEffectApplied`; an enemy-aimed start with a target that is not a player is refused (the original
     reads out of bounds); the original's silent ignores are refusals with the check's code; the lock maps live in the
     sacrifice record (not saved, as in the original); `Building.TerritoryBonus` is cached and pushed after each
     rebuild; a full territory recomputation posts no lost-territory messages; the state hash includes unsaved state.
   - **Upgrades** (§6.12): a blocked start is refused as `blocked-<n>`, a cancel without an upgrade as
     `not-upgrading`; the `UpgradeChanged` event for the upgrade's progress; `IUpgradeQueries` for the block reason.
   - **Gatherers and specialists** (§6.13): `GoAfforest` without a planting type fails (the original creates type
     −1); `MoveToDeposit` ends when its deposit vanished; a good with no sign list gets no sign (the original
     crashes); `!Found Resource` refreshes its message within hex distance 7 through `MessagePosted.Refresh` and
     `RefreshDistance` (§5.1); the good flag
     `FoundOnBuildableGround` replaces the hard-coded water good id.
   - **Building panels** ([renderer.md](renderer.md) §15.3): the panels read views only, the productivity through `IStatisticsView.TryGetProductivity`
     (§6.15); parents and layout details are [inferred]; the settings panel opens with **L** or `btSettings`.
   - **The navy** (§6.14): one street planner per player (the original shares one); `Ship.Shipyard` in place of
     the village construction record (+0x50); no docking position and a search toward the dummy (−1, −1) dock
     reserve nothing and are refused (the original writes through them); routes and harbours hashed in the
     remake's own form; the `initialized` byte only in `WriteState`, as in the original, so the net-tick checksums
     changed; a cargo package keeps the ship's cell at loading while it sails. Part 2: the crash guards of §6.14
     (`ChooseStartHarbor` null, a range ≤ 0, `TransferShipsOfPlayer(from == to)`, mission states 0 and 3,
     `SendSoldiersBySea` without a landing harbour, an attack origin without a building); one `NeedGoods` object (the original has two); the ships share one swell phase (the original's per-ship start value at `+0x74` not read), sample their height
     at the water plane and add the original's +π/2 to the heading (AM §3.17).
   - **Fog of war** ([renderer.md](renderer.md) §4.5): no left-over-texel quirk; no separate black `Unexplored`
     pass; the overlay clamped in every shader (the original wraps it, except in `water_shader.fx`); a border post is
     kept or hidden whole; flags follow the block rule; hiding a building's node hides its decal and flag; no refined
     variant. Characters and their carried goods use the settler's logic cell, as the original (`MotionSample.Cell`,
     S 006c57b0, S 006919b0).
   - **HUD frame, minimap and messages** ([renderer.md](renderer.md) §15.5): a message's remaining time falls by
     the tick's simulated time (the original subtracts the frame time once per logic tick, so its lifetime
     depends on the frame rate); the minimap picture is the overview render of the scene from above
     ([renderer.md](renderer.md) §8.5) in the original's 512 × 512 picture, the overlays 256 × 256 as the original's;
     no statistics key (**S** moves the camera); no build or pause button
     (the original has neither); the back button sits where the menu combo box is; unexplored minimap cells are
     transparent as documented, not seen in the original; the message list at the top left, where the layout puts
     it; the statistics curve colours from `menu.cfg` (the original's table S 0087f8c8 not compared); `debug=true`
     shows the developer panel.
   - **The free game** (§6.16): six rows, as the original's; the panel lives in `core.game`; the map's stored player
     names (row 0 shows `!Player`, the human keeps the map's name); plain text at the size of `Body_Arial.fnt`
     (13); the start's copy of rows into slots keeps the original's quirk with closed rows, the cleaner
     `Slots(activeOnly)` is a switch; the layout readings of FS §3.5, §3.9 and §3.10: the map list takes the
     container's width and the list's height [inferred], the chooser frame's label is hidden (whether the original
     draws it is not established), the loading bar's negative-width pictures are drawn mirrored [inferred], the end
     dialog's title and text sit inside the centred 480 × 244 frame [inferred].
   - **Particles** ([renderer.md](renderer.md) §16.1): GPU particles with hash draws, not the original's sequence
     (PA §8 allows it); caps of 192 emitters per effect and 24,000 particles in all at Faithful, 64 and 8,000 at
     Low, a refused start retried at the next state change; `sadk_time` wraps every hour; pass 2's volume uses the
     box fixed at the start; work-clip emitters fade out when the clip stops [inferred]; a one-shot of an endless
     effect stops it at once; one fallback fire-point stream per building layer (the original's is process-wide);
     building attachments (the sacrifice movies) advance per frame, the original's per logic tick (`EffectList::Update`
     inside `Building::Update` S 006abcf0); an emitter takes its link's rotation without scale (a scaled link gives
     the original a non-unit quaternion [inferred]).
     The effects follow-up (5281ab9): the effect and movie names (`sacrificeWaitForGoodsGfx`,
     `sacrificeResearchGfx`, `HitDamage`, `ShipSpeedUp`, `BuildingArmor`, `WorkerPause`) are constants citing the
     exe's strings (they could move to `visuals/particles.xml`); a movie's effects are placed once per keyframe at
     the bone [inferred]; the research back-date quirk is kept; the projectile's launch point is approximated by the
     source box's centre; the buffs ignore `showEffects` (its meaning is open).
   - **The computer player** (§6.17): mechanic tests use `MatchKit.WithoutComputers` (computer slots as remote
     humans); the literal good ids are handled two ways (`AiGoodRolesDef` role flags and `GoodRulesDef` flags), to
     be unified; the construction back-off pair and the street builder's source cell go into the extension of
     `core.game.ai.remakestate` (the original's `Store` lacks them); a remake save written before the AI was saved is
     repaired at its first tick (the computer slots activated anew; script-enabled campaign AI profiles are not
     restored);
     references are `Int64` (the original's are 20-byte `Unique`s); crash guards (a profile ticker of 0, a group
     weight total of 0, stage-1 needs without a depot, the production control's endless loop without a controllable
     good). The grids are sized as the original's `Game_LoadWorldFromDescriptor` S 005ac770 does: in
     `WorldBuildPhase.NewGame` before `core.game.players`, for new-game map types only; a save restores them from
     the AI section (`NAI::System::Load` S 005821f0).
   - **The map-script host** (§6.18): `logic` and `gfx` are registered in every match state (the original only
     offline; the network rule is open, [lua.md](lua.md) §4.5); a cinematic ends in one step (the original's steps are
     at least 1.5 s apart); the vocabulary replay covers `core.game` only; page and tutorial messages are type 7,
     letters type 8 [inferred]; `pl_changePlayer` skips a street it cannot rebuild (the original crashes).
   - **The script switches and the defeat letter** (§6.10, §6.18): removing a harbour position or an enemy exclusion
     that is not listed does nothing (the original runs past the vector's end); offline campaign maps post no
     `!DEFEAT`.
   - **Save and load** (§9.1): the remake keeps state the original loses on load (the active deposit order, the
     animal time stamps, the victory state, the ship sinking timer, the open-need index, a few appended fields); the
     game speed is not restored (as the original); ships and the buildings' remake-only fields go into extensions; the chests and the quests are written
     in empty or default form into the original's sections; a load checks section names and
     versions; strings are Latin-1; the original's rebuilds are kept (construction flags, object layers, indexes,
     cancelled street planners, the stock running total); the military's path cache is empty with stamp 0 after a
     load (the original stamps the load tick); the saved next-tick time is the float32 sum.
5. The unnamed `rand() % 6` caller of `StepDirection` (MR §3.1); if it is simulation code it is a C-runtime draw
   inside the simulation.
6. The stall picture (§4.1) is inferred; one look in a two-player match with a pulled cable settles it.
7. Message ids: the original's counter is not saved and repeats ids after a load (EC §7); the remake keys messages
   by the `(tick, seq)` of the posting event.
