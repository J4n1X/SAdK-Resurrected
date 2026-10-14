# Logic core: ticks, callbacks, random generator, checksum

Binary: `sadk_noav.exe` (image base 0x400000). `S 00xxxxxx` is a static address in that binary. Tags: **[known]** =
read directly in the code or the data, **[inferred]** = one step of reasoning from what is visible, **[TODO]** = open.
Nothing in this document has been observed in the running game.

Related documents: `docs/subsystems.md` (overview of all subsystems), `docs/types.md` (struct reference),
`docs/NCOMM_GAME_PROTOCOL.md` and `docs/NCOMM_LAYER.md` (the match network layer), `docs/multiplayer-save.md` (save
contents and the in-place load idea), `docs/map-format.md` (the `LogicSystem` section of a map file),
`docs/lua-surface.md` (Lua API: `onLogicTick`, `getTick`, `getRandom`, `properties.cfg_*`).

---

## 1. Purpose and scope

The logic core is the fixed-step, deterministic simulation driver of a match. It is responsible for:

- owning every simulation subsystem (`NLogic::System`, the object behind the global `g_pGameSystem` S 0088996c)
  [known] S 00528360;
- turning rendered-frame time into **logic ticks** of a fixed length and running all subsystems once per tick in a
  fixed order [known] S 00527070;
- coupling the logic tick to the **network tick** of the lockstep protocol: a logic tick only runs when the network
  layer allows it, and every logic tick is reported to the network layer [known] S 004088b0, S 00411990;
- the single **simulation random generator** (`LogicRandom_*`) [known] S 00538980..00538a20;
- the 64-bit **unique id counter** for simulation objects (`NLogic::Unique`) [known] S 005386c0;
- the **state checksum** exchanged between the players to detect a desync [known] S 00784080, S 00415a60;
- small shared building blocks: `NLogic::Ticker` (a period counter), `NLogic::Stock` (a multiset of goods), and
  `NLogic::CallbackManager` (the simulation's outgoing event broadcaster);
- two small tick-driven systems in namespace `ai::logic`: map chests (`LogicChestSystem`) and spawn points
  (`LogicSpawnSystem`).

It is **not** responsible for: the content of the subsystems it ticks (village, settlers, transport, military, navy,
street net, AI, sacrifices, victory conditions: see their own documents), the transport of network packets
(`docs/NCOMM_LAYER.md`), rendering, UI or sound. `ai::logic::Sacrifice*` and `ai::logic::StreetPlanner` live in the
same namespace but are separate subsystems; this document only states when the core calls them.

There is **no generic timed-callback scheduler** in the logic core [inferred: no such object is constructed by
`NLogic::System::ctor` S 00528360 and none is called from `Update` S 00527070]. Delayed and periodic behaviour is
built from three primitives described in §3.5: tick stamps compared against the global tick counter, `tick % N`
phase tests (optionally offset by an object's unique id), and per-object `NLogic::Ticker` counters.
`NLogic::CallbackManager` is an *event* broadcaster (object added, removed, changed), not a timer.

---

## 2. Data model

### 2.1 `NLogic::System` (size 0xf4, vtable S 007e7958)

One instance per loaded world, global pointer `g_pGameSystem` S 0088996c. Vtable: [0] deleting destructor, [1] `Save`
S 005275c0, [2] `Load` S 00527d60, [3] `PostLoad` S 005273d0 [known, mapping board #1192].

Fields that carry core state [known] S 00528360 (constructor) unless noted:

| Offset | Type | Name | Meaning |
|---|---|---|---|
| +0x04 | bool | `running` | 0 at construction, 1 after `SetUp` S 005280a0, 0 after `Shutdown` S 00527c40. Saved. |
| +0x6c | bool | `flag6c` | 0 at construction. When set, `FrameTick_InGame` does not render the world S 004018e0. No writer other than the constructor found in the decompiled code, so it stays 0 [inferred]. |
| +0x70 | int | — | Zeroed by `InitSubsystems` S 00527f70; no reader found [inferred]. |
| +0x74 | float32 | `frameDelta` | Scaled time of the last frame in seconds (see §3.1). Saved. |
| +0x78 | float32 | `nextTickTime` | Simulation time (s) at which the next logic tick is due. Saved. |
| +0x7c | float32 | `accumulatedTime` | Simulation time (s) accumulated so far. Saved. |
| +0x80 | float32 | `speedFactor` | 1.0 at construction; multiplies the frame time. No other writer found [inferred]. |
| +0x84 | float32 | `field84` | 0.0 at construction (stored with a float store, S 0052849d); `NLogic::System::ResetState_74_88` S 005272b0 (map export reset) copies the tick interval `GameConfig + 4` into it and also sets +0x74/+0x78/+0x7c to 0 and `tickCounter` to −1. Not read by `Update`; no reader found [inferred]. |
| +0x88 | int32 | `tickCounter` | Logic tick number. −1 at construction, incremented **before** each tick, so the first tick is tick 0. Saved. |
| +0x8c | ptr[8] | `streetConstructors` | One `NNet::StreetConstructorStreet` (0x18) per player slot. |
| +0xac | ptr[8] | `streetPlanners` | One `ai::logic::StreetPlanner` (0x10) per player slot. |
| +0xcc | ptr | `uuid` | `NCore::UUID` (0x18). |
| +0xd0 | `std::string` | `name` | Empty at construction. |
| +0xec | bool | `cinematicActive` (`flagEc`) | 0 at construction. Set when a cinematic is shown (S 00782b60, from `nMenu::Cinematic::OnShow`), cleared by `nGame::System::EndCinematic` S 00782bb0. The same two functions switch the computer players (`NAI::System.enabled`, saved and restored) and chest opening (§2.7) off and on and call `NSacrifice::System::PauseForCinematic` / `ResumeAfterCinematic` [known for the calls; their effect is in the sacrifice document]. Read by `NVillage::Military::Update` S 005609b0, `NMilitary::Fight::Update` S 005715a0 and `NSettlers::Livepoints::UpdateRegeneration` S 0065dbc0, which hold back part of their work while it is set [known for the readers; their rules are in `docs/sim/military.md` and `docs/sim/settlers-jobs.md`]. Not saved and not hashed [inferred from §3.6, §7]. |

Subsystem pointers (all allocated in the constructor, in this order of construction) [known] S 00528360:

| Offset | Subsystem | Size | Offset | Subsystem | Size |
|---|---|---|---|---|---|
| +0x24 | `ai::game::GameQuery` (back pointer) | 4 | +0x40 | `NMilitary::System` | 0x20 |
| +0x38 | `NLogic::Edit` | 0xc | +0x48 | `NNavy::System` | 0x68 |
| +0x3c | `NLogic::CallbackManager` | 0x3c | +0x4c | `NNet::System` (street net) | 0x294 |
| +0x44 | map-update batch ("cmdRouter") | 0x30 | +0x54 | `NAI::System` | 0x90 |
| +0x50 | `ai::game::GameQueryHelper` (back pointer) | 4 | +0x58 | `NLogic::Ambients` | 0x1c |
| +0xf0 | victory conditions (8 × 0x1c + state) | 300 | +0x28 | `NLogic::Statistics` | 0x38 |
| +0x08 | `NVillage::System` | 0xc0 | +0x34 | `NLogic::GameAccess` | 0x10 |
| +0x0c | `NSettlers::System` | 0x68 | +0x5c | `NLogic::Quests` | 0xdc8 |
| +0x14 | `ai::player::PlayerTable` (8 players × 0xf0) | 0x874 | +0x60 | `NSacrifice::System` | 0xc60 |
| +0x18 | `ai::game::Selection` | 0xe0 | +0x64 | `ai::logic::LogicChestSystem` | 0x28 |
| +0x2c | `NLogic::MapInfo` | 0x210 | +0x68 | `ai::logic::LogicSpawnSystem` | 0x18 |
| +0x30 | `NMap::System` | 0x58 | | | |
| +0x10 | `NResources::System` | 100 | | | |
| +0x1c | `NTransport::System` | 0x454 | | | |
| +0x20 | `NDoodads::System` | 0x44 | | | |

The number of player slots in the simulation is **8** (street planners, player table, victory conditions) [known]
S 00528360, S 005bddd0. The match network layer has **6** slots [known] S 004088b0.

### 2.2 Simulation random generator

A single global `ai::math::RandomGenerator` (8 bytes) at S 00889b08 plus a flag byte at S 00889b00 [known]:

| Address | Type | Name | Meaning |
|---|---|---|---|
| 00889b08 | uint32 | `state` | Current Park-Miller state, 1..0x7fffffff. |
| 00889b0c | uint32 | `seed` | Bit-balanced seed stored by `SetSeed` S 006ec2a0. |
| 00889b00 | byte | `initialised` | 1 after `LogicRandom_SetUp`, 0 after `LogicRandom_Shutdown`. |

The static initialiser S 007c07d0 constructs the generator with seed constant **0x5432ACE0** [known]. That value has
13 set bits, so the balancing step of `SetSeed` (§3.3) leaves it unchanged, and `seed` = `state` = 0x5432ACE0 after
the static initialiser [inferred, computed]; the generator read 0x5432ACE0 when a new world appeared
[live, 2026-10-12]. The only code that references the generator is the static initialiser
(and its exit-time destructor S 007ceb00), `LogicRandom_SetUp`, `_Next`, `_Save`, `_Load` and `_Checksum`; `seed`
has no direct reference of its own, so its only writers are the static initialiser and the 8-byte read in
`LogicRandom_Load` [known, cross references of S 00889b08 and S 00889b0c].

### 2.3 Unique id counter

A global 64-bit counter at S 00889ad0 (low) / 00889ad4 (high) [known] S 005386c0. `NLogic::Unique::AssignNew` copies
the counter into the object (`+8` low, `+0xc` high) and increments it by 1. `LogicId_ResetGlobal` S 00538780 zeroes
it at `Shutdown`; it is stored and loaded with the logic system (§7) and is part of the checksum (§3.6). The default
constructor S 005370f0 yields the "invalid" id **0xFFFFFFFFFFFFFFFF** (low and high dword −1) [known].
`NLogic::Unique::Less` S 005370b0 is the ordering predicate used by containers keyed by unique id.

### 2.4 `NLogic::Ticker` (size 0xc, vtable S 00834308)

| Offset | Type | Name | Meaning |
|---|---|---|---|
| +0x4 | int32 | `period` | Constructor argument (S 00775550). The three `NVillage::Building` constructors S 0055c8b0, S 0055d4e0, S 0055d980 pass 100 [known]; they are the only callers of the constructor [known]. |
| +0x8 | int32 | `elapsed` | 0 at construction. |

### 2.5 `NLogic::Stock` (size 0x1c, vtable S 007e7cf8)

A multiset of goods [known] S 00539d40 and the struct comments:

| Offset | Type | Name | Meaning |
|---|---|---|---|
| +0x04 | byte | `flag04` | 0 at construction. Written first by `Store`. When set, `Load` S 00539fa0 clears the map before reading; when 0, `Load` does **not** clear: every loaded unit is added (as by `AddOne`, `changeStamp` included) to what the stock already holds [known]. Only the constructor, `Reset` (both write 0) and `Load` (reads it from the file) write it, so it is 0 unless a file carries 1 [inferred]. |
| +0x08 | `std::map<int,int>` | goods | Key = good id, value = count. Head node pointer at +0x0c, node count at +0x10. Ordered by good id ascending. |
| +0x14 | int32 | `totalUnits` | Sum of all counts: +1 per unit added, −1 per unit removed. |
| +0x18 | int32 | `changeStamp` | +1 on every unit added and on every successful unit removal; never decreases. |

A "good amount" is a pair `{int goodId, int count}` (8 bytes); a "good list" is a vector of such pairs [known]
S 00539a90, S 00539e10.

### 2.6 `NLogic::CallbackManager` (size 0x3c, vtable S 007e79bc)

| Offset | Type | Name | Meaning |
|---|---|---|---|
| +0x04, +0x10, +0x1c | `std::list` ×3 | `listA/B/C` | Empty at construction S 005282a0, destroyed in the destructor S 00532080; no other access found, so they stay empty [inferred]. |
| +0x28 | `NLogic::System*` | `owner` | Constructor argument. |
| +0x2c | `std::set<CallbackReceiver*>` | `receivers` | Ordered by **pointer value**. |
| +0x38 | bool | `notifyEnabled` | 1 at construction. All broadcasters do nothing while 0. |

A receiver is an object with a vtable of **56** slots (+0x00..+0xdc); the base vtable S 007edfbc has every slot
set to one of two empty functions (S 0064b9c0 in 51 slots, the two-argument S 00472360 in slots 12 and 46..49)
[known, vtable read], so a receiver overrides only the events it wants. That S 007edfbc is the receiver base
class's table is taken from the map [inferred].

### 2.7 `ai::logic::LogicChestSystem` (0x28) and `ai::logic::LogicChest` (0x30)

`LogicChestSystem` [known, type comments]: +0x00 observer list, +0x0c `CallbackManager*`, +0x10 byte `initialized`,
+0x14 `std::vector<LogicChest*> chests`, +0x24 byte `enabled` (1 at construction; cleared while a cinematic plays,
board #1728 [inferred]).

`LogicChest` [known/inferred, type comments]:

| Offset | Type | Name | Meaning |
|---|---|---|---|
| +0x08 | uint64 | unique id | From the unique id counter. |
| +0x10, +0x14 | int32 | `posX`, `posY` | Map cell. Cell index = `posY * mapWidth + posX` S 00539520. |
| +0x18 | int32 | `ownerPlayer` | Territory owner of the chest's cell at the last update, −1 = none. |
| +0x1c | int32 | `contentKind` | Constructor argument S 00539240. **0** = chest of a network match, whose content is decided by the lobby referee (§3.5); **1** = goods chest created by Lua `map_createChest` S 005ad740 or the debug tool [known: S 00775dd0 passes 0 and S 00782a60 tests 0; S 005ad740 and S 00604dd0 pass 1 and then call `SetContentGood`]. `AddChest` S 0052d560 has no other caller. The constructor also sets a grid bit on the chest's cell (`MapModifier::SetGridBit10`, the same call `NLogic::Spawn::PlaceAt` makes) [known]. |
| +0x20, +0x24 | int32 | `contentGoodId`, `contentGoodCount` | Initial −1 / 0; set by `SetContentGood` S 005391e0 (kind 1). |
| +0x28 | uint32 | `contentValue` | 0 at construction. For kind 0: the chest id, one raw value of the `GameSeed` generator (§3.5), sent as `ChestID` of the referee message ClaimChest 0xDAC when the chest opens [known] S 00539200, S 00775dd0, S 00782a60. |
| +0x2c | int32 | `openProgressTicks` | Consecutive ticks with an unchanged owner. |

### 2.8 `ai::logic::LogicSpawnSystem` (0x18) and spawn points

`LogicSpawnSystem`: +0x00 `CallbackManager*`, +0x04 byte `initialized`, +0x08 `std::vector<NLogic::Spawn*> spawns`
[known, type comments]. A spawn (`NLogic::Spawn`, subclasses `SpawnAnimal`, `SpawnResource`) has a virtual "fire"
method in vtable slot 0, an `NLogic::Unique` sub-object at +0x08 whose 64-bit id at +0x10/+0x14 is used as phase
offset (`NLogic::Spawn::PlaceAt` S 00538e10 calls `AssignNew` on spawn +8), and a pointer at +0x18 to its
spawn-point property record: id vector at record +0x58 (first/last pointers +0x5c/+0x60), `range` +0x68 (default
3), `type` +0x6c (default −1), `rate` +0x70 (default 1) [known] S 0052ccc0, S 00557530, S 0054a830..0054a930.

### 2.9 Network-side tick state (`NComm_Manager`, global `g_NCommManager` S 00885754)

Only the fields the logic core depends on. The struct in the map still carries placeholder names for some of them;
the meanings below are from the code [known] S 00411990, S 004088b0, S 0040b270, S 0040a530 unless noted.

| Offset | Type | Meaning | Initial value |
|---|---|---|---|
| +0x00 | int | Reconnect state, 0 = none, 1..4 = reconnect phases (§3.2). | 0 |
| +0x04 | float | Reconnect timer (s): host wait countdown in state 2, time stamp in state 3. | 0 |
| +0x08..+0x14 | int[4] | IP octets of the host to reconnect to; all −1 = none (become the host). | −1 |
| +0x20 | bool | Error latch: set when the transport's `Process` fails; `BeginGameRunning` refuses to start while it is set. | 0 |
| +0x1c | int | Manager state. **4 = match running**; logic only ticks in state 4. | 0 |
| +0x24 | float | Time (s) of the last tick-length check; also re-stamped at every net tick boundary during the first 10 net ticks after the base tick (§3.2). | now at match start |
| +0x28 | int | Number of connected human players = number of checksums expected per net tick. | at match start |
| +0x2c | int | **Net tick** number. | −1 (ctor); 0 at match start |
| +0x30 | int | Base net tick (net tick at match start or at the last reconnect). | −1 (ctor S 0040a530); 0 at match start |
| +0x34 | int | **Logic ticks per net tick** = `+0x38 * +0x3c`. | 4 (ctor); 1 offline, 4 networked (`StartUpNetwork` S 0040a9a0) |
| +0x38 | int | Net tick length (base logic ticks per net tick), 1..10. | same as +0x34; 1 to 2 in a two-player LAN match [live, 2026-10-14] |
| +0x3c | int | Game speed multiplier (1..3). | 1 |
| +0x40 | int | Sub-tick counter: logic ticks done inside the current net tick. | −1 (ctor); 0 at match start |
| +0x44 | float | Wall time (s) of the last accepted logic tick. | 0 |
| +0x48 | int | Logic tick number of the last accepted logic tick. | −1 (ctor); 0 at match start |
| +0x4c | bool | "In sync" result of the last checksum comparison. | 0 |
| +0x4d | bool | "Stop after executing the package" flag: when set after `ExecuteEventPackage`, `AdvanceNetTick` returns before the package exchange and the net tick increment [known] S 00411990. Only ever written 0 [inferred from a search]. | 0 |
| +0x50 | ptr | Game listener (`nGame::System` + 8): slot +4 = handle a game event, +8 = start game, +0xc = compute checksum. | 0 |
| +0x54 | TickPackage | Outgoing package of the local player for the current net tick. | |
| +0x80 | TickPackage | Immediate (non-lockstep) event queue. | |
| +0xac | list<TickPackage*> | Host only: packages collected from all players, by net tick. | |
| +0xb8 | list<TickPackage*> | Merged packages to execute, by net tick. | |
| +0xc4 | ChecksumLog | Received checksums (§3.6). | cleared at match start |
| +0x360 | NetworkConfig | Config block: defaults from `NComm_NetworkConfig_InitDefaults` S 0040a390, then `network.ini` (§6). +0x36c `pingFrequencyMenu`, +0x370 `pingFrequencyGame`, +0x374 `timeHostWaitForClients`. | |
| +0x384 | int | Net tick length set after a reconnect. Written only by the defaults function. | **4** |
| +0x388 | float | Latency scale `k` of the net tick length formula. Written only by the defaults function. | **1.0** |
| +0x3c8 | int | Mode: 0 = offline, 1 and 3 = client roles, 2 and 4 = host roles. | |

`TickPackage` is a growable byte stream with an 8-byte header: u16 0x5332 (`"2S"`), u32 net tick, u16 0x4b38
(`"8K"`), little endian, followed by serialised events [known] S 00412b40. It also keeps the list of player ids that
contributed to it and a count of appended event blocks [known, type comments].

---

## 3. Rules and algorithms

### 3.1 Tick rate, game speed and the frame-to-tick conversion

`NLogic::System::Update(pTickListener, bCallScript)` S 00527070 is called once per rendered frame by
`CApplicationEx::FrameTick_InGame` S 004018e0 with `(NULL, true)` [known]. Algorithm [known]:

```
if NComm manager state != 4: return                      # no ticking outside a running match

tickInterval = GameConfig.gameSpeed                      # float32, 0.1 s (see §6)
dt = frameSeconds * userGameSpeed * speedFactor          # float32 products, in this order
frameDelta = dt
if dt > 5.0: frameDelta = tickInterval                   # a frame longer than 5 s counts as one tick

prevAccum = accumulatedTime
accumulatedTime += frameDelta
ticksThisFrame = 0
if nextTickTime <= accumulatedTime:
    loop:
        if not NComm.CanAdvanceTick():                   # lockstep stall
            accumulatedTime = nextTickTime - tickInterval
            frameDelta      = accumulatedTime - prevAccum
            return
        if not edit.GetBatchEditing():
            tickCounter += 1
            NComm.AdvanceNetTick(tickCounter)            # §3.2
            ... subsystem updates, §4 ...
        nextTickTime += tickInterval
        scene.vtbl[+0x18]()                              # render scene, per-tick hook
        if bCallScript and not edit.GetBatchEditing():
            Lua onLogicTick(tickCounter)                 # only when a map script is loaded
        if pTickListener != NULL and ticksThisFrame > 0:
            pTickListener.vtbl[+4]()
        ticksThisFrame += 1
        if accumulatedTime < nextTickTime: return
```

Constants and inputs:

- `frameSeconds` = `Timer_GetFrameDeltaSeconds()` S 0057b850: the last frame's duration in whole milliseconds / 1000;
  a fixed 0.025 s when the timer's fixed-step flag S 0088a615 is set [known]. 0 on the first frame after a timer
  reset [known] S 0057b810.
- `userGameSpeed` = float at `UserProfile + 0x24`: default 1.0 [known] S 00579c00; set to 1, 2 or 3 by the game-speed
  command, and to 0.0 while paused (§5) [known] S 00782a20, S 005ea9b0. All writers (callers of the setter
  S 00579870; its tenth caller, Lua `cfg_setCatapultRotationTimeFactor` S 0054c280, uses the same shared
  "store at +0x24" function on the `GameConfig` object, not on the profile) [known]:
  - `nMenu::Game::SetupHud` S 005ed700 writes **1.0** when the in-game screen is set up, so every match starts at
    speed 1 [inferred: it runs once per entered game];
  - the speed command handler S 00782a20 (1, 2, 3);
  - pause: `TogglePause` S 005da400 / `SetPaused` S 005ea9b0 (0.0, restore);
  - the options panel: its constructor S 005e62f0 saves the value and writes 0.0 when `UserProfile` byte +0 is
    set and the network mode is not 1..4, its destructor S 005e61b0 restores it under the same byte, so opening
    the options pauses an offline game [inferred; meaning of byte +0 not read];
  - cinematics: `nMenu::Cinematic::Update` S 005fb3e0 blends the value between the saved speed and 1.0 while fading
    in and out (fractional values occur), `OnHide` S 005faee0 restores the saved value;
  - the chat cheat `WhatTheHell`, offline (mode 0) only: **20.0** `nMenu::Game::OnKeyDown` S 005ec340.
  The value is written to `settings.cfg` (second field of the `UserSettings` section, S 00579640), but
  `UserProfile::LoadSettings` S 00579960 reads it and then overwrites it with 1.0 [known]. Only the speed command
  also changes the network multiplier (manager +0x3c); the other writers change the time scale alone. Pause, options
  panel and cheat are blocked in network modes 1..4 by the conditions above [known]; whether a cinematic can run
  in a network match is [TODO] (§10).
- `speedFactor` = `NLogic::System + 0x80`, always 1.0 [inferred].
- `tickInterval` = float at `GameConfig + 4` = **0.1 s** (§6).

Resulting **logic tick rate: 10 ticks per second of real time at speed 1, 20 at speed 2, 30 at speed 3**
[inferred from the constants above; measured offline at speeds 1, 2 and 3, with manager `+0x3c` and `+0x34`
reading 1 / 2 / 3, live, 2026-10-12]. All simulation durations in the data are therefore in units of 0.1 s of
normal-speed time when they are tick counts (for example `cfg_setChestOwningTime` default 3000 ticks = 300 s).

Properties of the loop a reimplementation must keep:

- **Catch-up without a cap.** All due ticks run in the same frame; only `CanAdvanceTick` or the frame-time clamp
  (5 s → one tick) limits them [known].
- **Stall handling.** When the network layer refuses a tick, simulation time is rolled back to exactly one tick
  interval before the due time, so no backlog builds up while waiting; `frameDelta` then holds the difference to
  the time before this frame and can be zero or negative [known]. `frameDelta` and `accumulatedTime` are read by
  the renderer for interpolation S 004018e0 [inferred]; they do not influence the simulation state.
- **Batch editing.** While `NLogic::Edit::GetBatchEditing()` is true (map editor bulk edits; the flag is set by
  `NLogic::Edit::SetBatchEditing` S 00538a60), ticks are
  consumed (`nextTickTime` advances) but no tick counter increment, network tick or subsystem update happens, and
  the Lua hook is skipped [known].
- **Tick numbers.** The first executed tick has `tickCounter == 0` [known: −1 at construction, pre-increment;
  the counter read −1 when a new world appeared, live, 2026-10-12].
- The FPU control word is set to 24-bit (single) precision with `_controlfp(0x9001f, 0xffff)` then
  `_controlfp(0x20000, 0x30000)` immediately before every `Update` call S 0057b9b0, S 004018e0 [known].

**Game speed.** `nGame::System::SendCycleGameSpeedCommand` S 00782950 queues game command **0x20023**
(`NComm::Event1Integer`) with value `floor(currentSpeed) % 3 + 1`, i.e. the cycle 1 → 2 → 3 → 1 [known]. When the
command executes on a peer:

1. `NComm_Manager::HandleEvent` S 0040e560 stores the value in manager +0x3c and sets
   `+0x34 = +0x38 * value` (logic ticks per net tick), and reports the event as not consumed [known];
2. the game listener then stores `(float)value` in `UserProfile + 0x24` S 00782a20 [known].

So a higher speed makes time accumulate faster *and* packs proportionally more logic ticks into a net tick; the
real-time length of a net tick stays the same [inferred]. The receiver does no range check on the value [known].

**Pause.** `nMenu::System::TogglePause` S 005da400 does nothing in network modes 1..4, so a network match cannot be
paused [known]. Otherwise, and only while the in-game screen is open and no cinematic is open [known],
`nMenu::Game::SetPaused` S 005ea9b0 saves `UserProfile + 0x24`, sets it to 0.0 and pauses
all sounds; unpausing restores the saved speed, raised to at least 1.0 [known]. With speed 0 the frame delta is 0
and no tick becomes due [inferred]: no tick ran during a 10 s pause, and manager `+0x3c` kept its value 3, so
the pause does not go through the manager's speed field [live, 2026-10-12].

### 3.2 Coupling to the network tick

The logic tick is the fine clock, the **net tick** the coarse one. A net tick consists of `S = netTickLength ×
gameSpeed` logic ticks (manager +0x34). Commands and checksums travel per net tick.

**Gate: `NComm_Manager::CanAdvanceTick`** S 004088b0 [known]:

```
if state != 4 or reconnectState not in {0, 1}: return false
if subTick + 1 < S: return true                    # inside a net tick: always allowed
# the next logic tick would close the net tick:
if reconnectState != 1 and mode in {0, 2, 4} and baseTick + 1 <= netTick:      # host / offline
    p = hostCollected.find(netTick - 1)
    if p == NULL: return false
    for slot in 0..5:
        id = slot.playerId
        if id != 0xEFFFFFEE and not p.hasPlayer(id): return false   # 0xEFFFFFEE = empty slot
if mode in {0..4} and baseTick + 2 <= netTick:
    q = toExecute.find(netTick - 2)
    if q == NULL or q.eventBlockCount < 1: return false
return true
```

In words: the host may only close net tick `N` when it has the package of **every** occupied slot for tick `N−1`;
every peer may only close net tick `N` when the merged package for tick `N−2` has arrived. During the first net tick
after the base tick the first test is skipped, during the first two the second.

**Step: `NComm_Manager::AdvanceNetTick(logicTick)`** S 00411990, called once per executed logic tick, right after
the tick counter increment and before any subsystem update [known]:

```
if state != 4 or not CanAdvanceTick(): return
subTick += 1; lastLogicTick = logicTick; lastTickWallTime = now
if subTick < S: return
subTick = 0                                              # ---- net tick boundary, N = netTick ----
if N - baseTick < 11: tickLengthCheckTime(+0x24) = now; network vtbl[+0x80]()   # see below
reconnectState = manager[+0x00]                          # read here, before the package runs
q = toExecute.find(N - 2)
if q != NULL:
    ExecuteEventPackage(q)                               # 1. run all commands of tick N-2
    if flag +0x4d: return                                # never set in the shipped code (§2.9)
if reconnectState != 1:
    if host and (p = hostCollected.find(N - 1)) != NULL:
        send p to all peers as message type 1002         # 2. host distributes tick N-1
        toExecute.findOrCreate(p.tick).append(localNetId, p)
    if client:
        send own outgoing package to the host as message type 1001     # 3. hand in own tick N
    else if host:
        hostCollected.findOrCreate(outgoing.tick).append(localNetId, outgoing)
netTick = N + 1
SendEventUserChecksum(N + 1)                             # 4. start package N+1 with the checksum (§3.6)
if N + 1 - 5 > 0: erase packages and checksum history older than N + 1 - 5
inSync = checksumLog.VerifyLatest(expectedCount, report) # 5. compare checksums (§3.6)
... desync / resync / no-sync-start reporting (§3.6) ...
```

The two transport calls (vtable of `NComm::TinCatNetwork` S 007d58f4) [known]: message 1002 goes through slot +0x1c
S 0041dbb0, which sends to net id 0xEFFFFFDD (all users; a host without other users sends nothing and reports
success); message 1001 goes through slot +0x18 S 0041db50, which sends to net id 0xEFFFFFCC, the id that
`IsHost` S 00418f10 compares the local net id with. The member names of these two slots in the map
(`pSendToHost` at +0x1c, `pBroadcast` at +0x18) are the wrong way round. The receive side agrees
(`cb_Received_Data` S 0041d720: 1001 → `AddClientGameEventsToServerGameEvents` S 0040e0d0 into `hostCollected`,
1002 → S 004082a0 into `toExecute`) [known].

The call in the first line of the boundary (`NComm_Manager::StampTimeAndVcall_80` S 00408f30) stores the current time
in manager +0x24 and calls the transport's slot +0x80 `ClearUserSamples` S 00419940, which empties the ping sample
list of every user record (the same slot `BeginGameRunning` S 0040b270 calls) [known]. Since +0x24 is the timer of
the net tick length adaptation below, no adaptation can happen during the first 10 net ticks as long as a net tick
is shorter than `pingFrequencyGame`, and the first adaptation after that only sees samples taken after net tick
10 [inferred].

`ExecuteEventPackage` S 00410530 [known]: skips the 8-byte header, then deserialises and handles events until the
read position reaches the package size. An event is first offered to `NComm_Manager::HandleEvent`; when that returns
false it goes to the game listener (slot +4); if no listener is set (manager +0x50 is 0) the function logs
`Error Executing Event - Class: <signature> - Type: <type>` and returns false. If an event cannot be deserialised
the function returns false without a log line. In both cases **the remaining events of the package are not
executed**; `AdvanceNetTick` ignores the return value. Deserialisation (`NComm_Event_CreateFromStream`
S 00420540) fails only for a class signature outside the 20 it knows (`docs/NCOMM_GAME_PROTOCOL.md`) [known];
every event a peer of the same build queues has one of them, so this needs a foreign build or a damaged package
[inferred].

**Host-side merge** [known] S 0041d720, S 0040e0d0, S 00412ae0, S 00412e80: a received 1001 package is accepted
only when the sender's net id owns a slot of the game information (otherwise log `Trying to add packages from user
not in game` and drop) and when it starts with a valid header; it is then **appended to the end** of the host's
package for the header's tick, with the header stripped, the event block count raised by one and the sender
recorded as contributor. The host's own package is appended the same way at its own boundary (pseudocode above).
The order of the players' blocks inside a merged package is therefore the order in which the blocks reached the
host's list (network arrival order, the host's own block at the moment it closes the net tick), **not** slot order.
It is the same on every peer because the merged bytes are what the host distributes [inferred]. A second block
from the same player for the same tick is appended again; there is no duplicate check [known].

Consequences [inferred from the two functions]:

- A command issued by a player while the local net tick is `N` is written into the outgoing package with header
  tick `N`, collected by the host under tick `N`, distributed at the boundary that ends tick `N+1`, and **executed
  by every peer at the boundary that ends net tick `N+2`** (the boundary at which the net tick number is still
  `N+2` and its package `N+2−2 = N` is run). The input delay is two full net ticks plus the rest of the current
  one. The start value `S = 4` does not last: in a two-player match over a LAN at speed 1 the adaptation below
  kept the length at 1, switching between 1 and 2, and the net tick advanced every 98-104 ms at length 1. A
  command took 240-310 ms (3 logic ticks) from `QueueGameCommand` S 00408b10 to `HandleGameCommand` at length 1
  and 440-540 ms (5-6 logic ticks) at length 2, road and building orders alike [live, 2026-10-14]. At the
  start value 4 the same rule would give 0.8 s to 1.2 s.
- Commands always execute on the logic tick that closes a net tick (the `S`-th logic tick of the net tick, where the
  sub-tick counter wraps to 0), before the subsystems of that logic tick run, in the order they appear in
  the merged package: the host's append order of the players' packages (arrival order, see "Host-side merge"
  above), and inside one player's package the order of queueing [inferred].
- Offline (mode 0): `S = 1`, `QueueGameCommand` S 00408b10 dispatches a command locally at once instead of queueing
  it, and the checksum value is 0 [known] S 00408b10, S 004089c0. An offline command therefore takes effect in the
  frame it is issued, between two logic ticks, not at a net tick boundary: a `SendCreateFlag` S 00780e10 at tick
  55,267 ran through `DispatchEventLocal` S 0040fd50 and `HandleGameCommand` (tick 55,267) before the send
  returned [live, 2026-10-14]. In every mode a command queued
  without the `force` argument is dropped (returns false) while `IsGameHanging` is true [known] S 00408b10.
- **`IsGameHanging`** S 00408860 [known] is true when the error latch (+0x20) is set, or a reconnect is in progress
  (reconnect state ≠ 0), or the manager state is 3 (game starting), or the state is 4 and the last accepted logic
  tick (wall time +0x44) is unset (0) or more than **2.0 s** old. In states 0..2 it is false. While it is true:
  commands without `force` are dropped (not queued for later), `nMenu::Game::OnMouseButton0Down` S 005eaae0 and
  `OnChar` S 005eb180 swallow the input (except the pause key `p`), and `nMenu::Game::Draw` S 005efdd0 draws the
  hang notice whose text `GetHangReason` S 0040d260 builds (waiting for start, waiting for packets, waiting for a
  named user, reconnect phase). Because the test only looks at the time of the last tick, it is also true in an
  offline game that has been paused (or stopped by the options panel) for more than 2 s [inferred]. In an
  offline game paused for some time `IsGameHanging` returned true (1,462 of 25,935 calls, the first at tick 1014),
  while `GetHangReason` was not called once and no command reached `QueueGameCommand` S 00408b10: nothing can be
  built while paused, because the input is swallowed before a command is made, and no hang notice text is built
  [live, 2026-10-12].
- A package only counts as "arrived" when it holds at least one event block. Every peer's package contains at least
  its checksum event each net tick, which is what keeps the gate open in an idle game [inferred].

**Net tick length adaptation** (`NComm_Manager::Process_MainLoop` S 00410f70, per frame, not in manager state 3
and not while a reconnect is in progress) [known]: every `pingFrequencyGame` seconds (§6; `pingFrequencyMenu`
in the states other than 3 and 4) the timer +0x24 is re-stamped and transport slot +0x84 S 00418f80 runs, on
every peer; the rest
only in state 4 and when the transport's `IsHost` (slot +0x38) is true. Slot +0x84 (`FlushPending` in the map)
calls the TinCat API function at +0xb0 for net id 0xEFFFFFDD (host with at least one user) or 0xEFFFFFCC
(connected client) [known]; what that API function does is not read: given the period it is the candidate for
the ping request whose answers feed the samples below [TODO] (`docs/NCOMM_LAYER.md`). Then:

- transport slot +0x44 returns a value < 2: event **0x3000d** with value 1 is appended to the outgoing package,
  every period, whether or not the length is already 1. The slot is S 00408430, a shared accessor that returns
  the int at +0x1c of its object, here the transport: the size field of the user list whose head (+0x18)
  `GetMinUserLevel` and `ClearUserSamples` iterate, i.e. the number of user records [inferred from the list
  layout]; whether the local user has a record of its own is [TODO] (§10);
- else read the latency `L` (slot +0x8c S 00419a50: the largest ping sample over all users' sample lists, capped
  at 1000; 0 = no samples → do nothing), `f = L × 0.5`; if mode < 3 or the level `q` < 5: `q` 0 or 1 → `f × 1.7`,
  `q` 2 → `f × 1.4`, `q` 3 → `f × 1.1`; `value = clamp(ceil(k × f × 0.01), 1, 10)` with `k` = float at manager
  +0x388 = **1.0** (§2.9); if `value` differs from the current net tick length, queue 0x3000d with it.

`q` is slot +0x60 `GetMinUserLevel` S 004198e0: the minimum of a per-user level (user list node +0x3c) over all
users, starting from 3, so `q ≤ 3` and one of the three factors always applies (at least × 1.1) [known for the
function, the rest inferred]. What sets a user's level is [TODO] (`docs/NCOMM_LAYER.md`). The samples come from the
transport's ping callback (`cb_Ping_Received` S 0041d910 → S 0041d610), which puts the value at the front of the
sample list of the user with that net id and then cuts the list to **2** entries, so `L` is the largest of the
two newest samples of any user [known]; with `L` in milliseconds the formula reads
"one-way delay in units of 0.1 s logic ticks, rounded up" [inferred from the cap 1000 and the factor 0.01; the
unit itself is not read]. Example under that reading: worst ping 250 ms, `q` = 3 → `ceil(250 × 0.5 × 1.1 × 0.01)`
= 2 logic ticks per net tick.

0x3000d is queued into the outgoing package, so it is applied at the same net tick boundary on every peer:
`+0x38 = value; +0x34 = +0x3c × value` [known] S 0040e560.

**Match start: state 3 → 4 and tick 0** [known unless noted]:

1. `nGame::System::BuildWorld` S 00784d40 stores the game listener (`nGame::System + 8`) in manager +0x50, builds
   the scene (which constructs `NLogic::System`, `tickCounter = −1`, and runs `SetUp`, §3.8) and loads the world.
   No logic tick runs during this time: `Update` returns at once while the manager state is not 4.
2. The host (modes 0, 2, 4) broadcasts event **0x30005** (`NComm_Manager::BroadcastStartGame` S 0040ff90) while the
   manager state is 3: from `BuildWorld` itself when the menu system's UI-suppressed flag is set, otherwise from
   the per-frame `nGame::System::Update` S 00780d20 once every slot reports "loaded"
   (`EventGameInformation::AreAllSlotsLoaded`), repeated every frame until the state changes.
3. Every peer handles 0x30005 (`HandleEvent` S 0040e560): `SendEventUserChecksum(0)` starts the outgoing package of
   net tick 0 with a checksum of the freshly loaded world; the game information of the event replaces the local
   one; +0x28 = number of connected humans; then the listener's start-game slot (+8) is called.
4. That slot is `nGame::System::BeginGameRunningForward` S 00782a50 (listener vtable S 008350c8: +4 `HandleGameCommand`,
   +8 this, +0xc `ComputeChecksum`). It only calls `NComm_Manager::BeginGameRunning` S 0040b270 and does **not**
   touch the logic system: if the error latch is clear and the state is 3, it zeroes net tick, base tick, sub-tick,
   last-tick time and number, sets +0x28 to the number of connected humans again, sets "in sync" false,
   state = **4**, clears the checksum log, stamps +0x24 and clears
   the transport's ping samples and traffic statistics.
5. 0x30005 arrives through the immediate queue (message type 1000), which `Process_MainLoop` executes in step 7 of
   the frame (§4.1). The first logic tick, tick 0, therefore runs in step 9 of the same frame at the earliest, as
   soon as `nextTickTime (0) <= accumulatedTime` [inferred from the frame order].

No peer waits for another before running tick 0; the lockstep gate first bites at the end of net tick 1 (host) and
net tick 2 (all) (§3.2 gate). `IsGameHanging` is true from state 3 until the first logic tick was accepted.

**Reconnect** (reconnect state at manager +0, driven per frame by `Process_MainLoop` S 00410f70 while the manager
state is 3 or 4) [known unless noted]:

| State | Name in the log | What happens |
|---|---|---|
| 1 | `eReconnectStateInitialisedAndWaitingOnExecutingOldPackages` | Entered through `BeginReconnect` S 00408f60 when the transport lost the session (once, S 00419080). Logic ticks continue: the gate allows state 1, skips the host-side test and only asks for the merged package `N−2`. At a boundary nothing is sent or collected (`reconnectState != 1` guards step 2 and 3 of `AdvanceNetTick`), but the net tick still advances. When the gate finally refuses a tick (last sub-tick of a net tick whose package `N−2` never came), the state 4 action runs in the same frame. |
| 4 | `eReconnectStateStartLocalServer` | If a host address is stored (+0x08..+0x14, written by the transport's reconnector, S 00425aa0 [inferred]): `ReconnectAndRejoin` S 004093a0, become a client (mode 3 or 1), → state 3; on failure `Reconnector_DropRemotePlayers` S 004109b0. Otherwise `Reconnector_RestartAsServer_DoAction` S 0040b700, become the host (mode 4 or 2), +0x28 = 1, timer +0x04 = `timeHostWaitForClients`, → state 2; on failure the manager shuts down. |
| 2 | `eReconnectStateHostWaitingOnClientsToJoin` | New host: counts the timer down by frame time. When every human slot is filled again (an unfilled human slot for which `PlayerInfo::IsState3` is true does not hold the wait; that predicate is named by the map and not read [TODO]) or the timer is ≤ 0: each human slot still unfilled is reset and removed with game command 0x2002b (dispatched locally in mode 0, else queued), then `BroadcastGameInfo(true)` S 004090e0 sends event **0x3000f**. |
| 3 | `eReconnectStateClientWaiting` | Rejoined client: waits for 0x3000f. |

Both state 4 actions end with the same reset [known] S 004093a0, S 0040b700: `SendEventUserChecksum(netTick)`
restarts the outgoing package (commands queued in it are discarded), both package lists are cleared (the merged
packages `N−2`, `N−1` that were not executed yet are discarded with their commands) and an empty host package for
`netTick − 1` is created, `baseTick = netTick`, net tick length = manager +0x384 (**4**),
`S = gameSpeed × 4`, `subTick = 0`, last-tick time 0, +0x24 = now, ping samples cleared, "in sync" false, checksum
log cleared. The rejoin event 0x3000e carries the sender's net tick; the new host kicks a peer whose value differs
from its own net tick or whose GUID owns no slot (`!COULD NOT RECONNECT`) [known] S 0040e560.

Event 0x3000f (`NE_PreGame_HostReconnectRestartAndSendGameInformation`) on every peer: replace the game
information, +0x28 = connected humans, reconnect state = 0, timer and address cleared [known] S 0040e560. Human
slots of the new information that are unfilled and whose slot flag read by the getter in that loop is 0 are
announced with `<name> !Player left game`, after which `PlayerInfo::SetField4B(1)` is called on the slot; that the
getter reads the same byte, making the announcement once per slot, is [inferred from the names in the map].

Effect on ticking [inferred from the functions above]: no logic tick runs in states 2, 3 and 4 (the gate requires
state 0 or 1), so the simulation stands still from the stall until 0x3000f; `IsGameHanging` is true for the whole
time. After the reset the gate conditions `baseTick + 1 <= netTick` / `baseTick + 2 <= netTick` are skipped for
one resp. two net ticks, exactly as at match start. The checksum log starts empty, so the first comparison after
the reset reports "not in sync" until all checksums of one net tick are in, and the `!NO SYNC START` test (§3.6)
applies again at `baseTick + 5`. Each peer's tick counter stays equal to the others' only if all peers stalled in
the same net tick: a peer stalls at sub-tick `S − 1` of the first net tick `N` whose package `N − 2` it lacks, and
the reset makes it run `S` more logic ticks before closing `N`. The rejoin check on the net tick number is the
only guard; the logic tick counter itself is never transmitted or compared [known: `AdvanceNetTick` only stores it
in +0x48]. Whether two surviving peers can stall in different net ticks and still pass that check is [TODO] (§10).

### 3.3 Simulation random generator

Algorithm: Park-Miller "minimal standard" generator, multiplier 16807 (0x41a7), modulus 2^31 − 1, in Carta's
overflow-free form [known] S 006ec350:

```
next(state):
    hi = (state >> 16) * 16807
    lo = (state & 0xffff) * 16807 + ((hi & 0x7fff) << 16)        # 32-bit unsigned arithmetic
    if lo > 0x7fffffff: lo = (lo & 0x7fffffff) + 1
    lo += hi >> 15
    if lo > 0x7fffffff: lo = (lo & 0x7fffffff) + 1
    state = lo
    return lo                                                     # 1 .. 0x7ffffffe
```

This equals `state * 16807 mod (2^31 − 1)` [inferred; checked numerically for the first value below].

`SetSeed(seed)` S 006ec2a0 [known]: `s = seed & 0x7fffffff`; count the set bits among bits 0..30; if fewer than 8,
set bits taken from the table below, entries `0 .. 8−count−1`; if more than 24, clear bits from the table, entries
`0 .. 32−count−1`; store `s` as `seed`; `state = s`, or 1 when `s == 0`. Bit-order table S 007fd528 (32 entries):
`12, 23, 10, 25, 8, 27, 6, 29, 4, 30, 1, 22, 9, 13, 21, 0, 17, 26, 5, 15, 18, 28, 11, 2, 14, 3, 24, 7, 19, 16, 20, 31`
[known, as transcribed in `tools/sadk_crypt.py`].

Logic generator interface [known]:

| Function | Behaviour |
|---|---|
| `LogicRandom_SetUp` S 00538980 | `state = seed & 0x7fffffff`, or 1 if `seed == 0`; `initialised = 1`. Called first thing in `NLogic::System::SetUp`. |
| `LogicRandom_Next` S 005389b0 | `return next(state)` (the map's prototype says `void`; the value is returned in EAX). |
| `LogicRandom_Shutdown` S 005389a0 | `initialised = 0`. |
| `LogicRandom_Save` / `Load` S 005389c0 / 00538a20 | §7. |
| `LogicRandom_Checksum` S 00538a00 | Feeds the 8 bytes `state, seed` into the checksum stream. |

Because `seed` is the constant 0x5432ACE0, **every new game starts with state 0x5432ACE0**; the first values
returned are 1257492815, 1295171578, 1054465454, 1365830334, 1057720755 [inferred, computed from the algorithm].
The seed distributed by the lobby referee (`GameSeed`) does **not** seed this generator; it seeds a separate local
generator used once for chest placement in network matches (`Game_DistributeChestsForNetworkMatch` S 00775dd0)
[known from that function's callees].

The first consumer in a new game can be `Game_CreatePlayersFromDescriptor` S 005abb60: when the descriptor's field
+0x24 is non-zero it shuffles the map's start positions by repeatedly taking entry `LogicRandom_Next() % remaining`
out of the remaining list [known]. Because the generator always starts from the same state, that shuffle yields
the same permutation for the same number of start positions in every game, provided nothing draws before it
[inferred]. `SetUp` (and with it `LogicRandom_SetUp`) always runs first: `nGame::System::BuildWorld` S 00784d40
calls `BuildScene` S 007842e0 (→ `SetUp`) and only then `Game_LoadWorldFromDescriptor` S 005ac770, which (unless
the descriptor's load-path selector is 1: then it only resets and re-initialises the subsystems) loads the
map file (`nGame_File_load`), and for new-game map types calls `Game_CreatePlayersFromDescriptor` and, when the
game information carries a `GameSeed` or a game id, `Game_DistributeChestsForNetworkMatch` (§3.5) [known].
Whether loading the map part of a file draws from the generator before the shuffle (objects created by the map
load) and which menu or lobby option sets descriptor +0x24 (`GameLoadDescriptor::Reset` S 005a9bb0 writes 0,
`Assign` S 00784cd0 copies it) are [TODO] (§10).

Callers reduce the value with a plain unsigned modulo: `value % n` picks an index in `0..n−1`
(S 00538f40, S 00676d10 `% 6`, the start position shuffle S 005abb60) [known]. Lua `getRandom(max)` S 005ad710
returns `value % (max + 1)` computed with a **signed** division (`CDQ; IDIV`): the value is always positive, so
the result is `0..max` for `max >= 0`, `value % |max + 1|` for `max < −1`, and `max == −1` divides by zero
[known]. There is no rejection step, so the modulo bias is part of the behaviour.

Callers of `LogicRandom_Next` (complete list from the call graph, 29) [known]: `NLogic::SpawnAnimal::Spawn`,
`NResources::Animal::ctor_Spawn`, `NResources::Deposit::ctor_AtCell`, `ai::game::AnimalRoamSearch::Init`,
`AI_PickRandomIdFromVector`, `AiSacrificeManager::OrderRandomSacrifice`, `NAI::NeedsArrangement::InstantiateGroupNeed`,
`NAI::MilitaryLimiter::Update`, `AiAttackWatch_Evaluate`, `AiSacrificeState::PickRandomTargetPlayer`,
`AiAttack_ScoreDefendersVsFightHistory`, `AiAttack_ScoreAttackersVsFightHistory`,
`AiAttackWatch_ScoreDefenceVsFightHistory`, `AiMilitary_RollChanceMinusMarkedCells`, `AiMilitary_ChooseSoldierKind`,
`NAI::AttackExecution::ShouldAttackWeakestCandidate`, `NAI::AttackExecution::Update`,
`Game_CreatePlayersFromDescriptor`, `LuaGame_getRandom`, `NSettlers::Soldier::Update`,
`ai::nnet::FreeSpotSearch::Init`, `NMap::AStar::BuildPath`, `NMovie::LookForEmptyPlace::Start`,
`NMovie::SearchScholarDiggingPosition::Start`, `NMovie::Fight::Start`, `Afforest_PickRandomDepositForCell`,
`NMovie::Stray::Start`, `NMovie::Working::Update`, `NMovie::LookForFishing::Start`. Other generators in the binary
(particles, animals' visuals, swarms, file encryption) are separate `RandomGenerator` instances and must not touch
this one [known from the callers of S 006ec4a0]. How many values each caller draws and under which condition is
in the caller's document: fights (`docs/sim/military.md`), settler path searches and jobs
(`docs/sim/settlers-jobs.md`), flag parking and street path building (`docs/sim/streets-transport.md`), tree
planting and animals (`docs/sim/map-resources.md`), computer players (`docs/sim/ai-player.md`).

### 3.4 `NLogic::Stock` operations

All amounts move **one unit at a time**; `changeStamp` counts units, not calls [known].

| Function | Rule |
|---|---|
| `GetCount(goodId)` S 005399b0 | Count, 0 when absent; does not insert. |
| `HasGood(goodId)` S 00539b70 | `GetCount > 0`. |
| `HasAll(list)` S 00539a90 | True when every entry's count is available; false at the first shortfall. |
| `HasAny(list)` S 00539be0 | True when at least one unit of any listed good is present; list counts ignored. |
| `CanAffordGoodCost(goodId)` S 00539b90 | Looks up the good's property; true when its cost list is empty or `HasAll(cost)`. |
| `AddOne(goodId)` S 00539de0 | `map[goodId]++`, `totalUnits++`, `changeStamp++`; returns true. |
| `AddEntry({id,n})` / `AddList` S 00539e10 / 00539e60 | `n` times `AddOne`; nothing for `n <= 0`. |
| `RemoveOne(goodId)` S 00539f00 | If the count is < 1: erase the entry (which the lookup may just have created) and return false. Else count−1, `totalUnits−1`, erase the entry when it reaches 0, `changeStamp++`, return true. |
| `RemoveEntry({id,n})` S 0053a2f0 | False if the good is absent or a unit removal fails; a partial removal is not rolled back. |
| `RemoveList(list)` S 0053a380 | Only if the list is non-empty and `HasAll(list)`: remove every entry, return true. Otherwise false and nothing removed. |
| `TransferEntry(dst, {id,n})` S 0053a280 | Up to `n` times: `RemoveOne` here, and only on success `AddOne` in `dst`. |
| `TransferList(dst, list)` S 0053a140 | Per entry, up to its count: move one unit if present. Moves what is available; never fails. |
| `MoveAllTo(dst)` S 0053a0b0 | Moves every unit of every good until the map is empty. |
| `ExchangeCostForGood(goodId)` S 0053a400 | `RemoveList(cost of the good)` with the result **ignored**, then `AddOne(goodId)`. |
| `Clear` / `Reset` S 00539a10 / 00539a50 | Empty the map, `totalUnits = 0`; `Reset` also clears `flag04`. `changeStamp` is not reset [known]. |

An entry with count 0 never stays in the map [inferred from `RemoveOne`], which matters because the entry count is
serialised and hashed.

### 3.5 Timing primitives

1. **Global tick stamps.** Objects store `g_pGameSystem->tickCounter` and later compare against it. Examples
   [known]: sacrifice start tick S 00661850, worker `lastWorkTick` S 0065c320, cached attack path length valid for
   0x6f ticks S 00575b70, player low-resource check only after tick 0x32 S 005bf8a0.
2. **Phase tests.** `tick % N == 0`, often with an object-specific offset so that work is spread over ticks.
   Examples [known]: `NTransport::System::Update` with N = 3, 5 and 11 S 0064cbe0; ships
   `(tick + unique.idLo) % 11` S 005bb500; settler movement `(ownerField + tick) % 0x17` S 00658140; statistics
   every 600 ticks S 00537ba0; spawn points (below). The offset additions are done in 64 bits where the unique id
   is involved (`__allrem`).
3. **`NLogic::Ticker`.** `Tick()` S 00775480: if `elapsed == period` then `elapsed = 0` and return true, else
   `elapsed += 1` and return false [known]. It therefore fires on every **(period + 1)-th** call. Used by
   `NVillage::Building::UpdateWorkerRequest` with period 100 [known, callers].
4. **Per-object counters** that count ticks in a state (chest `openProgressTicks`, building `tickCounter`, street
   `tickCounter` > 6000) [known] S 00539520, S 0055bfb0, S 00668e10.

**Spawn points** (`ai::logic::LogicSpawnSystem::Update(tick)` S 0052ccc0) [known]: for each spawn in vector order,
`interval = record.rate × GameConfig.spawnPointUpdateTime` (int); when
`(tick + spawn.phase64) % interval == 0` (signed 64-bit remainder) the spawn's virtual `Spawn()` runs.
`SpawnAnimal::Spawn` S 00538f40: if the animal area around the spawn is not crowded, pick
`index = LogicRandom_Next() % idCount` from the record's id vector, create that animal at the spawn position, set
its state to 6 and raise `NotifySpawnTriggered` [known]. A crowded area means no draw from the generator at all
[known]. `SpawnResource::Spawn` S 005390e0 [known]: starting at the spawn position it visits the centre cell and
then hexagonal rings outward (6 directions per ring, ring `r` has `r` steps per direction, each ring entered by one
step in direction 4) up to radius `record + 0x68`; on every visited cell inside the map it adds 1 unit of the
**first** id in the record's id vector through `MapModifier::AddResourceAtCell`, then raises
`NotifySpawnTriggered`. It does not use the random generator. `AddResourceAtCell` S 006745e0 [known]: only if the
cell may hold that resource type; an empty cell (type −1) takes the type, a cell of another type is left alone;
the amount is raised by 1 and capped at **7**, and the "unlimited" marker 1000 is first replaced by 7 (details in
`docs/sim/map-resources.md`). The shipped `scripts/properties/spawnpoints.lua` creates 12 spawn point records and
sets every one to `SpawnType_Animal` (= 1; `SpawnType_Resource` = 0 is defined but not used), so resource spawn
points only exist if a map or mod defines them [known, data].

**Chests** (`ai::logic::LogicChestSystem::Update` S 0052d660) [known]: only when `enabled`. For each chest in vector order that
is not yet openable: `UpdateOpening` S 00539520 reads the territory owner of the chest's cell; same owner as stored
→ `openProgressTicks += 1`; different owner → `openProgressTicks = 0` and, if the new owner is a player, message
type 5 `"!Player is trying to open a chest!"` (with the owner's name) to all other players and `"!chest found"` to
the owner; then store the owner. A chest is **openable** when `ownerPlayer != −1` and
`openProgressTicks >= GameConfig.chestOwningTime` S 00539210. On the tick it becomes openable: notify the system's
observers (the village system's `AddGoodsToPlayerStoreBuilding` is subscribed, S 00527f70), raise
`NotifyChest_SlotD0`, post `"!chest opened!"` to the owner and `"!chest opened by Player!"` to everyone else
[known]. Openable chests are not updated again [known]. The "same owner" test does not exclude −1: an unowned
chest also counts ticks, and the counter restarts from 0 when a player's territory first covers the cell, so the
full owning time always runs under one owner [inferred from S 00539520].

One of the observers is `Referee_OnChestOpened_SendClaimChest` S 00782a60, subscribed in `BuildScene` S 007842e0
[known]: for a chest of kind 0 opened by a player whose player kind is not 1 and who has a slot in the game
information, it sends the referee message ClaimChest 0xDAC with the chest's `contentValue` as chest id; what the
chest yields then comes from the server (`docs/LOBBY_PROTOCOL.md`). Every peer of the match runs this observer
[inferred: no local-player test in the function].

**Chest placement in a network match** (`Game_DistributeChestsForNetworkMatch` S 00775dd0, once at world creation,
only when the game information has a `GameSeed` or game id, §3.3) [known]: a local generator is constructed and
seeded with `SetSeed(GameSeed)` (§3.3 rules, including the bit balancing). Number of chests =
`activePlayers × (chestSites / startPositions)` with an integer division, both counts taken from the map info
vectors (unsigned; a map without start positions divides by zero). Then, round after round over player slots
0..7, one chest is placed per active player until the number is reached (the count is only tested between
rounds; the player index is not passed to the pick, so a chest is not tied to the player whose turn it is):
the site is the remaining candidate chosen by `ChestPlacement_PickFarthestFromPlayers` S 00775ca0, a chest of
kind 0 is added there (`LogicChestSystem::AddChest` S 0052d560, which first removes a resource and a doodad on
the cell and whose chest constructor draws a unique id), **one** value is drawn from the local generator and
stored as the chest id, and the site is removed from the candidates. The logic generator is not used.

Pick rule [known] S 00775ca0, S 00775c10, S 00775d60: the reference positions are collected **once**, before the
first pick: for each active player in slot order, the position (building +0x20) of the first building
`NVillage::System::FindFirstBuildingOfPlayer` returns, or a static invalid position if the player has none. For
every remaining candidate, in vector order, the distance is `MapPos::HexDistance` to the nearest reference
position (first minimum in vector order); the candidate with the **largest** such distance wins, the first one
on a tie (strict `>` against a best value that starts at 0, so if every distance is 0 the first candidate is
taken). Chests already placed do not enter the distance, so later picks are not pushed away from earlier ones.

### 3.6 Desync checksum

**Computation: `nGame::System::ComputeChecksum`** S 00784080 (game listener slot +0xc) [known]. A
`NCore::CRCStream` is opened with an empty section name and the following objects write themselves into it, in this
order:

1. `LogicRandom_Checksum`: 8 raw bytes (`state`, `seed`);
2. `ai::player::PlayerTable::StoreChecksum` S 005bde70: for each of the 8 slots, int −1 if inactive, else the slot
   index followed by `Player::StoreChecksum` S 005be6e0: index, colour index, tribe id, good priorities, good
   arrangement, military settings, the goods stock (only if active), team, 8 × (spotted byte, reached byte), state.
   The name, the player kind (differs per peer), messages and ship names are left out [known/inferred];
3. the village system (`NVillage::System::StoreChecksum` S 00557d10, which reaches
   `NVillage::Building::StoreForChecksum` S 0055c690);
4. `NSettlers::System::StoreUntagged`;
5. the transport system (vtable slot +4, i.e. its normal `Store`);
6. `NMilitary::System::StoreUntagged`;
7. `NNavy::System::StoreUntagged`;
8. `NNet::System::StoreForChecksum` S 00664550;
9. `NAI::System::StoreBody`;
10. `LogicId_StoreGlobal`: the 64-bit unique id counter.

The result is the stream's CRC value. Not included: the tick counter and tick timing, map/terrain, resources and
animals, doodads, statistics, quests, sacrifices, chests, spawn points [inferred from the list above]. What each
writer puts into the stream, and what it leaves out, is specified with the subsystem: buildings
(`docs/sim/village-buildings.md`), settlers (`docs/sim/settlers-jobs.md`), street net including its path-cost
caches (`docs/sim/streets-transport.md`), ships (`docs/sim/navy.md`), computer players
(`docs/sim/ai-player.md`), players (`docs/sim/players-victory.md`).

**`NCore::CRCStream`** (vtable S 007e9ccc) implements the save-stream interface by hashing instead of writing
[known, vtable read]:

| Stream slot | Savegame meaning | CRCStream behaviour |
|---|---|---|
| +0x40 | write section tag | **no-op** (tags and versions do not enter the checksum) |
| +0x44 | write raw bytes (ptr, len) | hash `len` bytes |
| +0x48 | write string | hash exactly **4 bytes** from the start of the string buffer, whatever its length S 0057d3d0 |
| +0x4c | write float32 | hash the 4 raw bytes |
| +0x50 | write 16-bit | hash 2 bytes |
| +0x54 | write 64-bit | hash 8 bytes |
| +0x58 | write byte / bool | hash 1 byte |
| +0x5c, +0x60, +0x64 | write 32-bit (signed, other, unsigned) | hash 4 bytes |

Values are hashed in little-endian memory order. The hash is the standard zlib CRC-32 (`crc32` S 007627c0), started
from `crc32(0, NULL, 0)` and updated incrementally; the accumulator also counts bytes but only the CRC is returned
[known] S 00762320, S 00762350, S 0057d390.

**Exchange.** At every net tick boundary `NComm_Manager::SendEventUserChecksum(newNetTick)` S 004089c0 clears the
outgoing package, writes its header for the new net tick and, if a game listener and a local player exist, appends
event **0x30009** (`NComm::EventUserChecksum`, class signature 0x55555050) [known]:

| Field | Type | Value |
|---|---|---|
| type | u32 | 0x30009 |
| source net id | u32 | local net id (no event if it is 0xEFFFFFEE) |
| player slot | i32 | slot of the local GUID |
| tick | u32 | manager +0x2c at the time of the call (equal to the new net tick number when called from `AdvanceNetTick`; the header uses the function argument instead) |
| checksum | u32 | `ComputeChecksum()`; 0 in mode 0 (offline the function is not called at all: a hook on S 00784080 saw no call in a whole free game [live, 2026-10-12]) |
| GUID | NetGUID (4 × u32) | local player GUID |

The event is only appended when the transport exists, the local net id is not 0xEFFFFFEE, the manager state is 2, 3
or 4 and the local GUID is found in the game information; otherwise the package holds the header only [known].

The checksum therefore describes the state **after** the commands of that boundary were executed and **before** the
subsystems of the boundary's logic tick run, on every peer the same logic tick [inferred from the call order in
S 00411990 and S 00527070]. The event travels like a command and is executed two net ticks later on every peer
(`HandleEvent` case 0x30009): unless the GUID belongs to a player who has left, `ChecksumLog::Add(tick, guid,
netId, checksum)` S 00416030 [known]:

- an exact `(tick, GUID)` duplicate is dropped;
- the entry is appended to the history list;
- in the "latest per GUID" list the GUID's entry is replaced when the new tick is higher, or appended when the GUID
  is new.

**Comparison: `ChecksumLog::VerifyLatest(expectedCount, report)`** S 00415a60, at every net tick boundary after the
packages were executed [known]:

| Condition | Result | Report text key |
|---|---|---|
| `expectedCount == 0` | in sync | — |
| latest list empty | not in sync | `!NetworkBasics/ErrorChecksumNoInList` |
| fewer entries than expected | not in sync | `!NetworkBasics/ErrorChecksumNotAllReceived` |
| more entries than expected | not in sync | `!NetworkBasics/ErrorChecksumTooMuchReceived` |
| equal count: any entry's tick differs from the first entry's | not in sync | `!NetworkBasics/ErrorChecksumTimeDiffers` |
| equal count: any entry's checksum differs from the first entry's | not in sync | `!NetworkBasics/ErrorChecksumSumDiffers` |
| otherwise | in sync | — |

`expectedCount` is the number of connected human players (manager +0x28). Several findings are joined with `" - "`.

**Reaction** S 00411990 [known]:

- in sync → not in sync: observers get the localised `!DESYNC DETECTED`, the report is logged, and
  `NComm_WriteDesyncDump` S 0041f5e0 writes `Desync.s2dump.txt` (a text dump of map and logic state,
  `GameFile_WriteDesyncDump` S 005ab220) into the user's dumps directory, but only when the log level global
  S 00882690 is above 1;
- not in sync → in sync and net tick > 4: observers get `!RESYNC DETECTED`, log line `Resync`;
- exactly 5 net ticks after the base tick and still not in sync: `!NO SYNC START`, report logged, dump as above.

No other action follows in this function: the match is not stopped and no state is transferred [known for
S 00411990; whether a listener reacts further is [TODO]]. The in-sync flag starts as false at match start
S 0040b270, so the first agreement is a silent transition when it happens before net tick 5 [inferred].

A separate, static check happens at join time: build version, build checksum (`NComm_GetBuildChecksum` S 0041f240,
`GameData_ComputeBuildChecksum` S 005ab800) and static-data MD5 are compared by the host and a mismatch is answered
with a kick (`!CHECKSUM MISMATCH`) [known, strings in S 0040e560]; see `docs/NCOMM_GAME_PROTOCOL.md`. That check is
outside the tick loop and not described further here.

### 3.7 `NLogic::CallbackManager`

Every broadcaster has the same body [known, e.g. S 005306a0]: if `notifyEnabled`, iterate the `receivers` set in its
order and call one fixed vtable slot of each receiver with the subject object (five of them pass a second
argument: +0x30 and +0xb8..+0xc4). There are 56 broadcasters, one per receiver slot +0x00..+0xdc
(S 005303a0..00531f20). The simulation calls these from constructors, destructors, post-load and state changes.
The receivers
are presentation-side objects (the render scene creates and removes its visual objects from these events
[inferred from the comments on S 00531120 and `S2CG::Scene::OnChestCreated`]); registration is an insert into the
set (`Stl_Tree14_InsertUnique` S 00531fa0) through the manager's own vtable: slot 0 `RegisterReceiver`
S 00532060, slot 1 `UnregisterReceiver` S 00532110 [known]. The only two registrations in the decompiled code are
in `nGame::System::BuildScene` S 007842e0, right after `SetUp` [known]: an object of the menu system (only when
the menu's UI-suppressed flag is clear; `nMenu::Game::OnLeave` S 005eb030 unregisters the face at `Game + 0x1a8`),
and the render scene's `NLogic::CallbackReceiver` face (`S2CG::Scene + 0xc`). Both are presentation objects
[inferred].

Receiver vtable slots and the events that fire them [known for the slot numbers; event meanings inferred from the
callers named in the map]:

| Slot | Event | Slot | Event |
|---|---|---|---|
| +0x00 | world loaded / load finished (arg 1 from `GameFile_FinishLoad`) | +0x6c | package detached from flag |
| +0x04 | subsystems re-init begin (arg 0) / end (arg 1) | +0x70 / +0x74 | building remains added / destroyed |
| +0x08 / +0x0c | building added (placed, transferred, loaded, type set) / removed | +0x78 / +0x7c | doodad added / destroyed |
| +0x10 / +0x14 | building upgrade started / cancelled | +0x80 / +0x84 | ship added / destroyed |
| +0x18 / +0x1c | flag added / removing | +0x88 / +0x8c | navy events [TODO] |
| +0x20 / +0x24 | settler added / removed | +0x90 / +0x94 | ship route added / removing |
| +0x28 / +0x2c | soldier entered / left a fight | +0x98 / +0x9c | projectile launched or retargeted / destroyed |
| +0x30 | strike or projectile impact (2 args) | +0xa0 / +0xa4 | sacrifice started / removed |
| +0x34 / +0x38 | fight added / removed | +0xa8 / +0xac | sacrifice research started / ended |
| +0x3c / +0x40 | street added / removed | +0xb0 / +0xb4 | sacrifice ordered at a building / order ended |
| +0x44 | street changed | +0xb8..+0xc4 | sacrifice effects applied (2 args): sink ships, heal units, reveal navy objects, reveal buildings |
| +0x48 / +0x4c | deposit (re)filled / removed | +0xc8 / +0xcc | chest added / removed |
| +0x50 | deposit depleted | +0xd0 | chest opened |
| +0x54 / +0x58 | animal added / removed | +0xd4 / +0xd8 | spawn point added / removed |
| +0x5c | settler movement started or changed | +0xdc | spawn point triggered |
| +0x60 / +0x64 | package added / removed | | |
| +0x68 | package attached to flag | | |

`notifyEnabled` is switched off during `Shutdown` and back on at its end [known] S 00527c40. After a load the
"added" events are fired again from the objects' post-load code so that receivers can rebuild their side [known
from the caller lists].

### 3.8 Life cycle of the logic system

| Step | Function | What happens |
|---|---|---|
| Construct | `NLogic::System::ctor` S 00528360 | Allocates all subsystems; `speedFactor = 1.0`, `tickCounter = −1`, timing floats 0. |
| Set up | `SetUp(mapA, mapB)` S 005280a0 (from `nGame::System::BuildScene` S 007842e0) | `LogicRandom_SetUp`; close the map-update bracket; `InitSubsystems`; log "Set up process finished."; `running = 1`; `GameAccess::SetUp`. |
| Init | `InitSubsystems(a, b)` S 00527f70 | Zero +0x70, `nextTickTime`, `accumulatedTime`; reset player table; init map; start the 8 street planners; init village, settlers, resources, selection, transport, doodads, military, navy, street-net path finder, AI players, ambients, statistics, quests, sacrifices, chests (and subscribe the village to chest openings), spawn system, victory conditions, in this order. If `a` or `b` is non-zero, receivers get slot +0x04 with 0 before and 1 after. `tickCounter` is **not** reset here [known]. |
| Reset | `Reset` S 00526f80 | Stops the street planners, then resets victory conditions, spawns, chests, statistics, village, settlers, resources, selection, transport, doodads, military, navy, street net, player table, ambients, AI, map, quests, sacrifices, in this order. The map modifier is disabled from the start until after the AI reset and enabled again before the map reset [known]. |
| Post-load | `PostLoad` S 005273d0 | For each street planner: if its street constructor reports active, the cancel call of §4.2 step 3, then `ai::logic::StreetPlanner::Stop`; after that all 8 planners are started again (`StreetPlanner::Start` with the map and the slot's street constructor, as in `InitSubsystems`); post-load of village, street net, navy, settlers, transport, resources, AI (`ResetPlayersAndHelpers`), map info, doodads, military, map, ambients, sacrifices, chests, spawns, in this order; reset the frame timer if requested. |
| Shut down | `Shutdown` S 00527c40 | Callbacks off; `Reset`; log; `LogicRandom_Shutdown`; `running = 0`; open the map-update bracket; `GameAccess::Shutdown`; callbacks on; zero the unique id counter. |

A new `NLogic::System` is constructed per world and destroyed with it (`nGame::System::ShutdownAndDestroyGameSystem`
S 00781cb0) [inferred from the single caller of `Shutdown`]; `NLogic::System::ResetState_74_88` S 005272b0 resets the timing
floats and sets `tickCounter = −1` for a map export [known].

---

## 4. Update order

### 4.1 Per frame (`CApplicationEx::FrameTick_InGame` S 004018e0) [known]

1. Return false if the graphic device is not ready.
2. `Timer_UpdateFrame` (frame delta in ms).
3. Reload UI XML if requested.
4. Enable or disable game input (window active and not minimised).
5. If the menu's game object returns true from its vtable slot +0x10 (in-game screen open [inferred]; the slot's
   function is not read): update the `nGame::System` updateable and the messages object.
6. `nMenu::System` update.
7. `NComm_Manager::Process_MainLoop` (if a manager exists): transport pump, immediate event queue, reconnect state
   machine, net-tick length adaptation (§3.2).
8. Lua script threads (`LuaScriptHost::UpdateThreads(totalSeconds)`).
9. If the logic system exists: set the FPU control word, then **`NLogic::System::Update(NULL, true)`** (§3.1).
10. Sound system update with the frame delta.
11. Device-lost check.
12. Rendering: world frame or the lobby world, cursor clip, lobby state pump (`docs/subsystems.md`).
13. If a lobby object exists and the menu system has an enter-lobby request pending: lobby mode transition.
14. Return true unless the menu system's quit flag is set.

Steps 1..8 and 10..14 run once per frame regardless of how many logic ticks step 9 executes; they must not change
simulation state except through queued commands [inferred].

### 4.2 Per logic tick (`NLogic::System::Update` S 00527070) [known]

In this exact order, once per tick, at the rate given in §3.1:

| # | Call | Notes |
|---|---|---|
| 1 | `tickCounter += 1` | |
| 2 | `NComm_Manager::AdvanceNetTick(tickCounter)` | At a net tick boundary this **executes the player commands** and computes the checksum (§3.2, §3.6). |
| 3 | For each of the 8 street planners, slot 0..7: if its street constructor (`StreetPlanner.constructor` +0xc, interface `NNet::IStreetConstructorStreet`) reports active (`IsActive`, slot +8) and `StreetPlanner::IsPathValid` S 00663900 is false, call `ai::logic::StreetPlanner::CancelConstruction` S 00663740: the constructor's `Cancel` (slot +4) with the planner's search object (`search` +4, an `NLogic::AStarStreet`), planner state (+8) = 6 | The same call is what `Reset` uses to stop the planners (§3.8), so this cancels a street under construction whose path became invalid [inferred]; rules in `docs/sim/streets-transport.md`. |
| 4 | `ai::player::PlayerTable::UpdateAll` S 005bddd0 | `ai::player::Player::Update` for each active player, slot 0..7. It also ages the players' on-screen messages by frame time (§8). |
| 5 | `MapUpdateBatch_Begin` S 00532180 | Opens a bracket that collects terrain/construction-map dirty areas: decrements the nesting counter (batch +0x2c), begins an elevation batch on the map modifier while the system is `running`, and, when the counter reaches 0, clears the collected dirty state. |
| 6 | `NVillage::System::Update` | |
| 7 | `NNet::System::Update` | Street net. |
| 8 | `MapUpdateBatch_End` S 005321c0 | Ends the elevation batch (while `running`) and flushes: removes obstructed doodads in the dirty rectangle (or all), recomputes the construction map for the dirty rectangle (or all). It increments the nesting counter and flushes only when the counter is then > 0; `SetUp` closes one bracket and `Shutdown` opens one (§3.8), so the counter rests at 1 between ticks: a bracket opened by the village or street-net update inside steps 6..7 nests without flushing, while the bracket of a command executed in step 2 flushes at once [known for the two functions; resting value inferred]. |
| 9 | `NSettlers::System::Update` | |
| 10 | `NTransport::System::Update` | |
| 11 | `NResources::System::Update` | |
| 12 | `NDoodads::System::Update` | |
| 13 | `NMilitary::System::Update` | |
| 14 | `NNavy::System` update (vtable slot +4) | |
| 15 | `NLogic::Statistics::Update` S 00537ba0, only if statistics are initialised | Tick 0: reset; every 600 ticks and the 4 ticks after: sampling. |
| 16 | `NAI::System::Tick` S 00581a30 | Computer players. |
| 17 | `NSacrifice::System` update (vtable slot +4) | |
| 18 | `LogicSpawnSystem::Update(tickCounter)` | §3.5. |
| 19 | `ai::logic::LogicChestSystem::Update` | §3.5. |
| 20 | `VictoryCond_Update` S 00535d70 | Eliminations, progress, winner. |

After the subsystems, still inside the tick iteration but outside the simulation proper:

| # | Call | Notes |
|---|---|---|
| 21 | `nextTickTime += tickInterval` | |
| 22 | render scene per-tick hook (`g_pScene` vtable S 007f8f2c +0x18 = `S2CG::Scene::SyncLogicTick` S 00680550) | Presentation: copies `nextTickTime` into the scene's game time and hands it to the render-side managers (map renderer, characters, carried items, animals, ships), passes the scene's float +0x50 to the swarm manager, stores the game time in a render singleton (+0x94), then re-applies the scene settings [known]. No call into a simulation subsystem at this level [inferred]; the managers themselves are not read. |
| 23 | Lua `onLogicTick(tickCounter)` S 005b20d0 | Only if the second argument of `Update` is true (the frame loop passes true) and a map script is loaded (S 0087e964 non-zero); it can call simulation functions and `getRandom`, so it is **part of the deterministic tick**. |
| 24 | optional tick listener, from the second tick of a frame on | Not used by the frame loop (NULL). |

Steps 1..20 are skipped while batch editing is on; steps 21, 22 and 24 still run (§3.1).

---

## 5. Inputs and outputs

**Inputs**

- Frame time from the application timer; user game speed (`UserProfile + 0x24`).
- From the network layer: permission to tick (`CanAdvanceTick`), and at net tick boundaries the execution of
  command events. Events the network manager does not consume are passed to the game listener
  (`nGame::System::HandleGameCommand` S 007845a0), which applies them to the simulation [known] S 00410530.
- Events the core itself reacts to [known]:

| Event | Name | Effect |
|---|---|---|
| 0x20023 | game speed, `GE_Logic_SpeedUp` (name table S 00421bd0) | §3.1 |
| 0x3000d | `NE_InGame_ChangeNetTickLength` | §3.2 |
| 0x30009 | `NE_InGame_SendChecksum` / `EventUserChecksum` | §3.6 |
| 0x30005 | `NE_StartGame` | Writes the first outgoing package (`SendEventUserChecksum(0)`), stores the game information and the player count, calls the listener's start-game slot, which moves the manager to state 4 (§3.2 "Match start"). |
| 0x3000e | `NE_InGame_ClientReconnect` (class `EventUserReJoinGame`) | After a reconnect: if the value the event carries equals the manager's net tick (+0x2c) and its GUID has a slot, rebinds that slot to the sender's net id, else kicks the sender with `!COULD NOT RECONNECT` (§3.2 "Reconnect"). The case itself has no host test [known]. |
| 0x3000f | `NE_PreGame_HostReconnectRestartAndSendGameInformation` | Ends a reconnect: new game information (a `!Player left game` notice for each human slot that is no longer filled), player count +0x28, reconnect state 0 and timer 0, host address −1 (§3.2 "Reconnect"). |
| 0x2002b | `GE_PlayerLeftGame` | Appended to the outgoing package (or dispatched locally) by `Reconnector_DropRemotePlayers` S 004109b0 for a player dropped in a reconnect; executed by the game listener (`docs/sim/players-victory.md`). |

- Lua map scripts: `getTick()` returns `tickCounter` S 005ad6d0; `getRandom(max)` S 005ad710 [known].

**Outputs**

- To the network layer: `AdvanceNetTick(tick)` per logic tick; the checksum on request.
- To presentation: `CallbackManager` events (§3.7); `frameDelta` / `accumulatedTime` for interpolation; the scene's
  per-tick hook.
- To Lua: `onLogicTick(tick)` once per executed tick.
- To the player: the desync, resync and no-sync-start texts through the network manager's observers (shown as
  in-game messages [inferred]); chest messages (message type 5).
- To other subsystems: the tick counter (read directly from `g_pGameSystem->tickCounter` by about 60 functions),
  `LogicRandom_Next`, unique ids, `Stock`, `Ticker`.

---

## 6. Data-driven parameters

| Parameter | Where set | Where read | Value |
|---|---|---|---|
| Logic tick interval (s) | Lua `properties.cfg_setGameSpeed(x)` S 0054c380 → `GameConfig + 4` | `NLogic::System::Update` S 00527070 | Default **0.1** (0x3dcccccd) in `Properties_GameConfig_ctor` S 00555780. No Lua file of the installed game data calls the setter [known: searched all 355 decrypted `.lua` files; `scripts/properties/config.lua` has no such line], so 0.1 is the effective value. |
| Spawn-point base interval (ticks) | `properties.cfg_setSpawnPointUpdateTime` → `GameConfig + 0x50` | `LogicSpawnSystem::Update` | Default 600; `config.lua` sets **1200**. |
| Spawn-point rate (multiplier) | `properties.sp_setRate` S 0054a890 → record +0x70 | `LogicSpawnSystem::Update` | Default 1 S 00557530; `sp_setRate` is called by no Lua file of the installed game data [known]. Effective interval 1200 ticks = 120 s. |
| Chest opening time (ticks) | `properties.cfg_setChestOwningTime` S 0054c1e0 → `GameConfig + 0x5c` | `ai::logic::LogicChest::IsOpenable` S 00539210 | Default **3000**; the setter is called by no Lua file of the installed game data [known]. 300 s at speed 1. |
| User game speed | command 0x20023; pause, options panel, cinematics, cheat (§3.1) | `Update` | 1.0 at every game start; 1, 2, 3; 0 when paused. Stored in `settings.cfg` but reset to 1.0 right after it is read S 00579960, so it is effectively not a data value [known]. |
| Tick-length check period (s) | `data/game/settings/network.ini` `[Ping] pingFrequencyGame` → manager +0x370 | `Process_MainLoop` S 00410f70 | Fallback string of the ini read **"2.5"** S 007d5be0 [known]; shipped 2.5. The value before the ini is read is 3.0 (`NComm_NetworkConfig_InitDefaults` S 0040a390). In manager states other than 3 and 4 `pingFrequencyMenu` (+0x36c, fallback "10.0" S 007d5c00, shipped 10.0) is the period of the same timer; in state 3 the timer is not run [known] S 00410f70. |
| Initial net tick length | code | `StartUpNetwork` S 0040a9a0 | 1 offline, 4 networked. |
| Latency scale `k` | manager +0x388 (config block +0x28), code constant in `NComm_NetworkConfig_InitDefaults` S 0040a390 | `Process_MainLoop` | **1.0** [known]. Not a key of `network.ini` (`NComm_NetworkConfig_LoadFromIni` S 0041ede0 does not write it) and no other write in the network manager code S 00408000..00413000 [known for that range]. |
| Net tick length after a reconnect | manager +0x384 (config block +0x24), same function | `ReconnectAndRejoin` S 004093a0, `Reconnector_RestartAsServer_DoAction` S 0040b700 | **4** [known]; same remarks. |
| Host wait for rejoining clients (s) | `network.ini` `[Reconnector] timeHostWaitForClients` → manager +0x374 | `Reconnector_RestartAsServer_DoAction` | Value before the ini is read 30.0; fallback string of the ini read "30.0" S 007d5bc4; the installed `network.ini` has 30.0 [known]. |
| Hang threshold (s) | code constant S 007d435c | `IsGameHanging` S 00408860 | 2.0. |
| Logic RNG seed | constant in the static initialiser S 007c07d0 | `LogicRandom_SetUp` | 0x5432ACE0. |

Other `properties.cfg_*` keys (`cfg_setSettlerSpeed 0.058`, `cfg_setPickupTime 3.3`, `cfg_setConstructTime 30`, …)
live in the same `GameConfig` object but belong to other subsystems; see `docs/lua-surface.md`.

---

## 7. Save and load

A save is written by `GameFile_Save` S 005aa260 as a map part (`GameFile_SaveMap` S 005a9fa0) followed by a logic
part, for map types 10 and 0x6e (savegames); for any other map type only the map part is written, after
`GameFile_ResetWorldForMapExport` S 005aa150, and only when `MapDesc_IsStandardType` accepts the path [known].
`docs/multiplayer-save.md` and `docs/map-format.md` describe the container. A section tag in a file is the
section's version (u32, the third argument of the section object's constructor S 005816e0) followed by the CRC
accumulator of the section name (`ai::core::Crc32Acc::Write`) [known] S 0057cfc0; the reading call returns the version
(stream slot +0x3c S 0057cf80) or discards it (slot +0x14 S 007804f0). The parts owned by the logic core:

**`NLogic::System::Save`** S 005275c0, section tag `LogicSystem`, current version **8** [known: static initialiser
S 007c01e0]:

1. `MapInfo` stores itself first (own section);
2. section tag `LogicSystem`;
3. unique id counter, 64-bit;
4. `running`, byte;
5. `frameDelta`, `nextTickTime`, `accumulatedTime`, three float32;
6. `tickCounter`, 32-bit.

**`NLogic::System::Load`** S 00527d60 [known]: `MapInfo` loads; read the section version `v`; unique id counter;
`running`; if `1 <= v <= 5` read and discard one 32-bit value; if `v > 3` read the three floats, and if
`nextTickTime <= accumulatedTime` set `accumulatedTime = nextTickTime − 0.01`; if `v < 8` read and discard an
obsolete `TriggerSystem` section (one byte, one 32-bit value); if `v > 6` read `tickCounter`. A file older than
version 7 keeps the constructor's `tickCounter = −1` [inferred].

Widths in the lists below are those of the stream call. On file streams the bool call (stream slots +0x58 write,
+0x2c read) stores **4 bytes** (S 00780520, S 00780490); only the checksum stream feeds 1 byte (S 0057d300)
[known]. A field called "byte" below is therefore 4 bytes in a file; the exact file layout is in
`docs/sim/save-format.md`.

**`GameFile_SaveLogic`** S 005a9ec0, section tag `Game File Logic` (tag text from the static initialiser
S 007c6270), in this order [known]: logic random generator,
player table, village, settlers, transport, military, street net, AI, statistics, game script, quests, sacrifices,
chests. `GameFile_LoadLogic` S 005a9db0 reads the same order with version gates: random generator if `v > 0`; navy
inside this section only if `v < 4`; game script if `v > 1`; quests if `v > 2`; sacrifices if `v > 4`; chests if
`v > 5` [known]. Current version is **6** [known: static initialiser S 007c6270].

**Logic random generator** S 005389c0 / 00538a20: section tag `Logic Random` (version 0, S 007c07f0; the load does
not read the version), the `initialised` byte, then 8 raw bytes (`state` u32, `seed` u32) [known]. Loading restores
both, so a loaded game continues the exact sequence. A load first builds a new world (tick counter −1, generator
at its start state 0x5432ACE0), then restores the tick counter (the tick of the save) and after it the generator:
a game saved with state 1661135933 at tick 2328 entered `LogicRandom_Load` with the start state and the tick
already set, and left it with state 1661135933; the seed word S 00889b0c stayed 0x5432ACE0. The game speed is not
restored: a game saved at speed 3 ran at speed 1 after the load [live, 2026-10-12].

**`NLogic::Stock`** S 00539850 / 00539fa0: section tag `Stock` (current version 1, S 007c09e0); byte `flag04`; u32
entry count; per entry u32 good id, u32 count, in ascending good id order. Load: if the object's `flag04` was set,
clear first (map, `totalUnits = 0`, `flag04 = 0`); read the version;
read `flag04`; if version < 1 read and discard one u32; read the entries and re-add them unit by unit, which also
advances `totalUnits` and `changeStamp` (the stamp itself is not saved) [known]. `StoreContents` S 00539910 writes
count and entries without tag and flag.

**`NLogic::Ticker`** S 007754a0 / 007754e0: section tag `ticker` (lower case, version 0, S 007cbaf0), then
`elapsed`, then `period` (both 32-bit); the untagged variant S 00775520 writes the two values only [known].

**Recomputed or re-fired on load** [known] S 005273d0: street planners are cancelled, stopped and started again
(§3.8); the post-load of each subsystem listed in §3.8 runs (that they resolve references by unique id and re-raise
the "added" callbacks is [inferred]: the post-load functions are not read here); the frame timer is reset when the
timer is initialised (`Timer_IsInitialized` S 0057b800). **Not saved**: network tick state, pending command
packages and the checksum log (`docs/multiplayer-save.md`), `speedFactor`, `cinematicActive`, `CallbackManager` receivers, the user game speed
(§3.1) [inferred]. `PostLoad` has no step for the player table, statistics, quests and victory conditions (they are
absent from the list above) [known]; what that means for them is in `docs/sim/players-victory.md` and
`docs/sim/save-format.md`.

The desync dump (`GameFile_DumpLogic` S 005aa540) writes the marker `---- LOGIK ----` and the same logic part
without game script, quests and sacrifices into a text stream [known].

---

## 8. Determinism notes

- **Lockstep contract.** Two machines stay in sync when they execute the same commands at the same logic tick and
  every per-tick computation is a pure function of the simulation state. Frame rate, frame time and the float
  accumulators only decide *when* a tick runs locally; the tick-to-net-tick mapping is integer (`subTick`, `S`) and
  changes of `S` (events 0x20023, 0x3000d) are themselves executed at a net tick boundary [known/inferred].
- **Equal tick numbers.** The logic tick counter is not hashed, not sent and not compared; peers agree on it
  only by construction [known]: it starts at −1 on every peer, rises by one per accepted logic tick, and the
  number of logic ticks per net tick is `S`. An event that changes `S` is executed inside `AdvanceNetTick` right
  after the sub-tick counter wrapped to 0, on the same net tick number on every peer, so the new `S` applies to
  the same, whole net tick everywhere [inferred from S 00411990]. A reconnect replaces `S` by `gameSpeed × 4`
  and zeroes the sub-tick counter locally on every surviving peer instead of through an event (§3.2); equality
  then rests on all peers having stalled in the same net tick, see §10.
- **Frame-time state inside the tick.** `ai::player::Player::Update` (step 4 of §4.2) ages each on-screen message by the
  frame delta (`NPlayer::Messages::UpdateTimers` S 005c1bb0 → `Timer_GetFrameDeltaSeconds`) [known]. Message
  lifetimes therefore differ between peers; messages are not hashed (§3.6). Nothing in the simulation may depend
  on them (`docs/sim/players-victory.md`).
- **Random generator.** One global sequence shared by everything in §3.3, including computer players and Lua
  `getRandom`. The number and order of calls per tick must match exactly; any presentation code calling it would
  desynchronise. It always starts from the same constant, so a given map with the same inputs replays identically
  [inferred].
- **Subsystem order** (§4.2) and **player slot order** 0..7 inside the per-player loops are fixed [known].
- **Container iteration order.** `Stock` is a `std::map` by good id (ascending) [known]. Chests and spawn points
  are vectors in insertion order [known]. Objects keyed by `NLogic::Unique` iterate in id order, and ids come from
  one global counter, so **the order of object creation is itself simulation state**: it is saved, loaded and hashed
  [known]. Ids are also drawn for things that are not objects of their own, for example the net-continent ids
  of a flag (`docs/sim/streets-transport.md`), so the number of draws per operation must match too.
- **`CallbackManager` receivers are ordered by pointer value**, which differs between machines and runs [known].
  This is harmless only as long as receivers never change simulation state or draw from the logic generator
  [inferred]. A reimplementation should treat these events as output-only. The two registered receivers are the
  render scene and a menu object (§3.7).
- **Caches that are simulation state.** Some cached values are saved and hashed and so must be computed at the
  same tick on every peer; presentation code must never trigger their computation: the street net's path-cost
  caches (`docs/sim/streets-transport.md`) and the military attack path-length cache
  (`docs/sim/military.md`) [inferred: taken from those documents, their writers are not read here].
- **Floating point.** The FPU is forced to 24-bit precision before each `Update` [known] S 0057b9b0; the same call is
  made at the start of `nGame::System::HandleGameCommand` S 007845a0, in `CApplicationEx::Initialize` and in
  `Lobby::CLobby::Update` [known, callers of S 0057b9b0]. Float values
  that are part of the simulation state (they are hashed as raw 4 bytes) must therefore be reproduced with float32
  arithmetic in the original operation order to stay checksum-compatible. Which subsystems hold float state is
  outside this document [TODO per subsystem]. The tick timing floats are not hashed.
- **Float accumulator precision.** `accumulatedTime` and `nextTickTime` are float32 and grow by 0.1 per tick for
  the whole match; float32 spacing reaches 0.0078 at 65,536 s (about 18 h at speed 1). The tick *count* is unaffected
  across peers because of the gate, but local pacing gets coarser [inferred].
- **Checksum coverage is partial** (§3.6): divergence in resources, animals, doodads, sacrifices, chests, spawns or
  the tick counter is only detected once it leaks into a hashed subsystem [inferred].
- **CRCStream string quirk.** A string contributes exactly 4 bytes from its buffer start; for strings shorter than 4
  characters this includes bytes after the terminator [known] S 0057d3d0. If a hashed object stores a short string,
  peers could disagree on garbage bytes; whether any hashed object does is [TODO].
- **Lua `onLogicTick`** runs inside the tick on every peer and may mutate the simulation; campaign scripts use it
  (`maps/campaignMaps/C02.lua`, `C10.lua`: `function onLogicTick(ticks)` → `quest_onLogicTick(ticks)`) [known].
- **Unsigned modulo on the tick counter.** Phase tests cast the signed tick counter to unsigned or widen to 64 bits
  [known, e.g. S 0064cbe0]; with tick ≥ 0 this makes no difference.

---

## 9. Notes for a reimplementation

**Can be simplified**

- The frame-time accumulator: any scheme that runs `ticks = floor(scaledTime / 0.1)` with catch-up and a "frame
  longer than 5 s = one tick" clamp behaves the same from the simulation's view. An integer or double accumulator is
  fine (it also removes the precision issue of §8). For original saves, read and write the three float32 values and
  apply the load clamp.
- The network gate: a remake with its own netcode only needs the contract "commands are applied at a tick boundary
  agreed by all peers, before the subsystems of that tick". Net tick length adaptation and the two-list host scheme
  are transport details. Keep the property that the game-speed change is itself a synchronised command.
- `CallbackManager`: replace by engine signals. Keep the rule that "added" events are re-emitted after a load, and
  keep emission out of the deterministic state.
- `speedFactor`, `field84`, `flag6c`, field +0x70, the three unused lists in `CallbackManager`, the optional tick
  listener and manager flag +0x4d can be dropped.
- The hang test (`IsGameHanging`) is a presentation and input rule; keep "commands issued while the simulation
  is not ticking are dropped, not queued" only if the same feel is wanted.
- `Stock::changeStamp` is a cache-invalidation counter; any dirty marker does the job unless a consumer compares
  exact values; no reader was found through the typed field [inferred, §10].

**Must be exact for compatibility**

- Tick length 0.1 s and the meaning "1 tick = 0.1 s at speed 1": every tick-count constant in the property scripts
  and in the code depends on it.
- The per-tick subsystem order of §4.2, including commands first and the Lua hook last, and slot order 0..7.
- The random generator algorithm (§3.3), its start state 0x5432ACE0, the plain-modulo reduction, and the call order.
  Needed for identical outcomes on the same map and for continuing original saves (state and seed are in the save).
- `Ticker` fires every `period + 1` calls; `RemoveOne` erases empty entries; `ExchangeCostForGood` ignores a failed
  cost removal. Small rules like these change production timing and stock contents.
- Unique ids: one global 64-bit counter, +1 per object, saved with the logic system; references in saves are by
  these ids.
- Save layouts of §7 (field order, version gates) for reading original saves and maps.
- The checksum algorithm and field order (§3.6) matter only for network play **against the original client**; a
  remake that only talks to itself can hash any canonical serialisation, and should hash more of the state.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.2): on a LAN at speed 1 the net tick length is 1 to 2, not 4, so a net tick lasts about 0.1 s to 0.2 s; a command takes 240-310 ms (3 logic ticks) at length 1 and 440-540 ms (5-6 logic ticks) at length 2, which matches "two net ticks plus the rest of the current one" [live, 2026-10-14] | — |
| 2 | What sets a user's level `q`, whether the local user has a record in the transport's user list (slot +0x44 returns the list size; the "< 2" branch forces net tick length 1), and what the TinCat API function at +0xb0 called from slot +0x84 does. Answered: the ping samples are milliseconds of a full round trip, `GetTickCount()` at the reply minus the `GetTickCount()` value the request carried (T 1000a2a0 `Send_Ping`, T 10009070 `Received_Ping`, callback slot `+0x3c` → S 0041d910 → S 0041d610), so their resolution is that of `GetTickCount` | static read of the writers of user list node +0x3c and of the code that adds user records; or observation of 0x3000d values against measured pings |
| 3 | Answered: nothing besides the notice, the log line and the optional dump happens on a desync. `AdvanceNetTick` S 00411990 stores the result of `VerifyLatest` in manager `+0x4c`, which nothing else reads, hands the translated `!DESYNC DETECTED` to the message sink (in a match the game screen, which shows it as a letter, S 005eb120; the observer list `+0x3e0` has no subscriber), logs the report and calls `NComm_WriteDesyncDump` S 0041f5e0 (a file only when the log level is above 1). No message is sent and the match goes on | static: S 00411990, S 00415a60, S 0040e3a0, S 005eb120, S 0041f5e0 |
| 4 | After a host loss, can two surviving peers stall in different net ticks and still pass the rejoin check (their logic tick counters would then differ by up to `S − 1`), and are the discarded packages `N−2`, `N−1` the same on all of them? | Observation: kill the host in a three-client match and compare `tickCounter`, `netTick` and the first checksums after `0x3000f` on the two survivors. |
| 5 | Does any object hashed by `ComputeChecksum` write a string through the CRC stream (4-byte quirk)? | Static read of the `Store`/`StoreUntagged` chains of the hashed subsystems for stream slot +0x48, per subsystem document. |
| 6 | Do the village and settler checksum writers hash the same fields as their save writers (plate comments say "same order, untagged")? | Static read, per subsystem document. |
| 7 | Which lobby or menu option sets `GameLoadDescriptor + 0x24` (start position shuffle), and does loading the map part of a file draw from the logic generator before the shuffle and before tick 0? | Static read of the code that fills the descriptor before `nGame::System::BuildWorld` and of `GameFile_LoadMap` S 005aa7b0 for `LogicRandom_Next` callers on the map-load path (`docs/sim/players-victory.md`, `docs/sim/map-resources.md`). |
| 8 | Is `Stock::changeStamp` read anywhere? No access outside `NLogic::Stock` shows up through the typed field; a raw-offset read (stock +0x18) is not excluded. | Xrefs by offset on the users of `NLogic::Stock`. |
| 9 | Can a cinematic (which blends the user game speed and sets `cinematicActive`, both local) run during a network match? | Static read of the callers of `nMenu::Cinematic::OnShow` S 005fbd30 (Lua quest functions) against the network mode; or a network match on a map whose script starts a cinematic. |
| 10 | Do the render-side managers called from `S2CG::Scene::SyncLogicTick` S 00680550 write anything the simulation reads? | Static read of the five manager functions (render documentation). |
| 11 | Answered (§3.2): in a paused offline game `IsGameHanging` is true, the build input is swallowed before any command reaches `QueueGameCommand`, and `GetHangReason` is never called, so no hang notice text is built [live, 2026-10-12] | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004018e0 | `CApplicationEx::FrameTick_InGame` | Per-frame driver; calls the logic update. |
| 00527070 | `NLogic::System::Update` | Frame time → logic ticks; per-tick subsystem order. |
| 00528360 | `NLogic::System::ctor` | Allocates all subsystems; initial timing state. |
| 005280a0 / 00527c40 | `NLogic::System::SetUp` / `Shutdown` | Start and end of a simulation. |
| 00527f70 / 00526f80 | `NLogic::System::InitSubsystems` / `Reset` | Subsystem init and reset order. |
| 005275c0 / 00527d60 / 005273d0 | `NLogic::System::Save` / `Load` / `PostLoad` | `LogicSystem` section; post-load order. |
| 005272b0 | `NLogic::System::ResetState_74_88` | Resets tick timing and tick counter (map export). |
| 004088b0 | `NComm_Manager::CanAdvanceTick` | Lockstep gate. |
| 00411990 | `NComm_Manager::AdvanceNetTick` | Net tick boundary: execute, distribute, checksum, verify. |
| 004089c0 | `NComm_Manager::SendEventUserChecksum` | Starts the outgoing package with the checksum event. |
| 00410530 | `NComm_Manager::ExecuteEventPackage` | Runs the events of a tick package. |
| 0040e560 | `NComm_Manager::HandleEvent` | Cases 0x20023, 0x3000d, 0x30009, 0x30005, 0x3000e, 0x3000f. |
| 00410f70 | `NComm_Manager::Process_MainLoop` | Per-frame network pump; net tick length adaptation. |
| 0040b270 | `NComm_Manager::BeginGameRunning` | Resets net tick, sub-tick, checksum log at match start. |
| 00408b10 | `NComm_Manager::QueueGameCommand` | Queues a command (or dispatches it offline). |
| 00408860 / 0040d260 | `NComm_Manager::IsGameHanging` / `GetHangReason` | Hang test (error latch, reconnect, state 3, state 4 with no tick for 2 s or none yet) and its notice text. |
| 0040ff90 / 00782a50 | `NComm_Manager::BroadcastStartGame` / `nGame::System::BeginGameRunningForward` | Host sends 0x30005; listener start-game slot → `BeginGameRunning`. |
| 0041d720 / 0040e0d0 / 004082a0 | `NComm::TinCatNetwork::cb_Received_Data` / `NComm_Manager::AddClientGameEventsToServerGameEvents` / `AddReceivedHostTickPackage` | Receive path of messages 1001 and 1002. |
| 00412ae0 / 00412e80 | `ai::ncomm::TickPackageList::AddReceived` / `TickPackage::AppendEvents` | Append a received block to the package of its tick. |
| 0041db50 / 0041dbb0 | `NComm::TinCatNetwork` vtable +0x18 / +0x1c | Send to id 0xEFFFFFCC (clients' package 1001) / to id 0xEFFFFFDD (host's merged package 1002; a host without other users sends nothing) [known for the ids; use from S 00411990]. The map names the two functions `Broadcast` / `SendToHost`. |
| 00419940 / 00419a50 / 004198e0 | `NComm::TinCatNetwork::ClearUserSamples` / `GetMaxUserSample` / `GetMinUserLevel` | Ping samples and user level behind the net tick length formula. |
| 0040a390 / 0041ede0 | `NComm_NetworkConfig_InitDefaults` / `NComm_NetworkConfig_LoadFromIni` | Network config defaults (incl. +0x24 = 4, +0x28 = 1.0) and `network.ini`. |
| 00408f60 / 004093a0 / 0040b700 / 004109b0 | `NComm_Manager::BeginReconnect` / `ReconnectAndRejoin` / `Reconnector_RestartAsServer_DoAction` / `Reconnector_DropRemotePlayers` | Reconnect state machine actions. |
| 00420540 | `NComm_Event_CreateFromStream` | Event factory (20 class signatures). |
| 00412b40 | `ai::ncomm::TickPackage::WriteHeader` | 8-byte tick package header. |
| 00416030 / 00415a60 / 00415740 | `ai::ncomm::ChecksumLog::Add` / `VerifyLatest` / `PruneBefore` | Checksum bookkeeping and comparison. |
| 00784080 | `nGame::System::ComputeChecksum` | State checksum: what is hashed, in which order. |
| 005bde70 / 005be6e0 | `PlayerTable::StoreChecksum` / `Player::StoreChecksum` | Player part of the checksum. |
| 0055c690 / 00664550 | `NVillage::Building::StoreForChecksum` / `NNet::System::StoreForChecksum` | Checksum writers of buildings and the street net. |
| 0057d270..0057d430 | `NCore::CRCStream::*` | Hashing stream (CRC-32). |
| 0041f5e0 / 005ab220 / 005aa540 | `NComm_WriteDesyncDump` / `GameFile_WriteDesyncDump` / `GameFile_DumpLogic` | Desync text dump. |
| 00538980 / 005389b0 / 005389a0 | `LogicRandom_SetUp` / `Next` / `Shutdown` | Simulation random generator. |
| 005389c0 / 00538a20 / 00538a00 | `LogicRandom_Save` / `Load` / `Checksum` | Its persistence and hashing. |
| 006ec350 / 006ec2a0 | `Rng_ParkMillerNext` / `ai::math::RandomGenerator::SetSeed` | Generator step and seeding. |
| 007c07d0 | static initialiser | Seeds the logic generator with 0x5432ACE0. |
| 005386c0 / 00538760 / 00538740 / 00538780 | `NLogic::Unique::AssignNew`, `LogicId_StoreGlobal` / `LoadGlobal` / `ResetGlobal` | Unique id counter. |
| 00775480 / 00775550 | `NLogic::Ticker::Tick` / `ctor` | Period counter. |
| 00539d40, 00539de0, 00539f00, 0053a380, 0053a400, 00539850, 00539fa0 | `NLogic::Stock::ctor`, `AddOne`, `RemoveOne`, `RemoveList`, `ExchangeCostForGood`, `Store`, `Load` | Goods multiset. |
| 005282a0 / 005303a0..00531f20 | `NLogic::CallbackManager::ctor` / `Notify*` | Event broadcaster and its 56 broadcast functions (one per receiver slot). |
| 0052ccc0 / 00538f40 | `ai::logic::LogicSpawnSystem::Update` / `NLogic::SpawnAnimal::Spawn` | Spawn points. |
| 0052d660 / 00539520 / 00539210 | `ai::logic::LogicChestSystem::Update` / `LogicChest::UpdateOpening` / `ai::logic::LogicChest::IsOpenable` | Chests. |
| 00775dd0 / 00782a60 | `Game_DistributeChestsForNetworkMatch` / `Referee_OnChestOpened_SendClaimChest` | Network-match chests: placement from the `GameSeed`, ClaimChest on opening. |
| 00782b60 / 00782bb0 | cinematic begin / `nGame::System::EndCinematic` | Set and clear `cinematicActive`, AI and chest enable. |
| 007842e0 / 00784d40 / 005ac770 | `nGame::System::BuildScene` / `BuildWorld` / `Game_LoadWorldFromDescriptor` | World creation order: construct, `SetUp`, receivers, load, players, chests. |
| 00532060 / 00532110 | `NLogic::CallbackManager::RegisterReceiver` / `UnregisterReceiver` | Receiver set. |
| 00532180 / 005321c0 | `MapUpdateBatch_Begin` / `MapUpdateBatch_End` | Nested map-update bracket. |
| 00680550 | `S2CG::Scene::SyncLogicTick` | Render scene per-tick hook. |
| 00579870 / 00579640 / 00579960 | user game speed setter / `UserProfile::StoreSettings` / `LoadSettings` | Writers and persistence of `UserProfile + 0x24`. |
| 005a9ec0 / 005a9db0 | `GameFile_SaveLogic` / `GameFile_LoadLogic` | Logic part of a save: order and version gates. |
| 00782950 / 00782a20 | `nGame::System::SendCycleGameSpeedCommand` / speed command handler | Game speed 1 → 2 → 3. |
| 005da400 / 005ea9b0 | `nMenu::System::TogglePause` / `nMenu::Game::SetPaused` | Pause (offline only). |
| 0054c380 / 00555780 | `LuaProps_cfg_setGameSpeed` / `Properties_GameConfig_ctor` | Tick interval setter and default. |
| 005b20d0 / 005ad6d0 / 005ad710 | `GameScript_CallOnLogicTick` / `GameScript_Lua_getTick` / `LuaGame_getRandom` | Lua tick hook, tick and random access. |
| 0057b850 / 0057b9b0 | `Timer_GetFrameDeltaSeconds` / `Fpu_SetDefaultControlWord` | Frame time source; FPU precision. |
