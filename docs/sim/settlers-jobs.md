# Settlers: workers, carriers, jobs and movement

Binary: `sadk_noav.exe` (image base 0x400000). Addresses are written `S 00xxxxxx`. Tags: **[known]** = read
directly in the code or the game data, **[inferred]** = one step of reasoning from what is visible (this includes
behaviour taken from an analyst plate comment whose code was not re-read line by line), **[TODO]** = open.
Nothing in this document has been observed in the running game.

Related documents: [`../subsystems.md`](../subsystems.md) (overview), [`../types.md`](../types.md) (structs),
[`../lua-surface.md`](../lua-surface.md) (Lua bindings), [`../data-loading.md`](../data-loading.md),
[`../navy-and-military.md`](../navy-and-military.md) (soldier combat, ships), [`logic-core.md`](logic-core.md)
(tick loop), [`village-buildings.md`](village-buildings.md) (buildings, production, stock),
[`game-commands.md`](game-commands.md).

---

## 1. Purpose and scope

The settler subsystem owns every walking figure of the simulation:

- `NSettlers::System` — the six lists of settlers, their creation, per-tick update, removal and save/load.
- `NSettlers::Settler` — the base class: identity, owner, state number, action timer, carried package, movement.
- `NSettlers::Worker`, `Carrier`, `Constructor`, `Specialist`, `NPC`, and `Soldier` as far as it is a settler
  (life cycle, walking home, dying). Soldier combat is in `navy-and-military.md`.
- `ai::settlers::SettlerMovement` with `ai::movement::Movement` and `NMovement::*` — walking on the cell grid
  (street routes and free paths), on the fine grid (quarter cells), speeds, queueing at flags.
- `NMovie::*` — the "movies": small scripted action state machines (leave building, go mining, bring good home,
  pick up, put down ...) from which every job is composed.

Not in scope: which settler is ordered to which destination (`NVillage` order system), building production rules
(`NVillage::Production`), package routing and flag stock (`NTransport`, `NNet`), deposits and animals
(`NResources`), the A* searches themselves (`NMap::AStar`, `nnet::StreetPathFinder`), rendering
(`S2CG::Character*`). Those are named where the settler code calls into them.

---

## 2. Data model

### 2.1 Settler types

`ESettlerType` is the field `settlerType` of the settler's property record (`GoodProperty +0x7c`), set from Lua by
`properties.gp_setSettlerType` (S 0054e4b0). **[known]**

| Value | Name (Jobs.lua) | Class | Object size | List in `System` |
|---|---|---|---|---|
| 0 | `settlerType_Worker` | `NSettlers::Worker` | 0x480 | `+0x04` |
| 1 | `settlerType_Constructor` | `NSettlers::Constructor` | 0x208 | `+0x14` |
| 2 | `settlerType_Carrier` | `NSettlers::Carrier` | 0x200 | `+0x24` |
| 3 | `settlerType_Soldier` | `NSettlers::Soldier` | 0x398 | `+0x34` |
| 4 | `settlerType_Specialist` | `NSettlers::Specialist` | 0x1b0 | `+0x44` |
| 5 | `settlerType_NPC` | `NSettlers::NPC` | 0x148 | `+0x54` |

Sizes from the `operator new` calls in the list loaders S 00654ec0..00655550, the list offsets from
`System::RemoveSettler` S 00654c20 and the creators S 006560d0..006563a0. **[known]** Enum values and names from
`game/scripts/properties/Jobs.lua`. **[known]**

A settler *kind* (profession) is a good: every profession is a `GoodProperty` of type `Settler` with a 32-bit id
(for example `good_helper = 0x7bff15ce`, the carrier; `good_woodcutter = 0x2c50533e`). **[known]** (Jobs.lua,
`gp_create`). Each tribe has its own set (`good_woodcutter`, `good_woodcutterBav`, `good_woodcutterScots` ...).

### 2.2 `NSettlers::System` (S 00654dd0 ctor, vftable 007f8394)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04..+0x60` | six `std::vector<Settler*>` | one per settler type, index = `ESettlerType`, 0x10 bytes each |
| `+0x64` | `flag64` (byte) | 0 in the ctor, in `Clear` and at the start of `Load`; set to 1 by S 00654240, called from `NLogic::System::InitSubsystems` S 00527f70 and `GameFile_ResetWorldForMapExport` S 005aa150; stored and loaded. No reader other than `Store` exists in the decompiled code, so it is a "set up" marker without simulation effect **[inferred]** |

**[known]** (S 00654dd0, S 00654420, S 00654b80, S 00656430).
The vectors own the settlers; order inside a vector is creation order
(`push_back`) and survives save/load, removal is an erase that keeps the order of the rest (S 00654a10).
**[known]**

### 2.3 `NSettlers::Settler` base (0x118 bytes, vftable 007f83bc)

| Offset | Field | Type | Meaning |
|---|---|---|---|
| `+0x08` | `unique` | `NLogic::Unique` | id pair at `+0x10` (lo) / `+0x14` (hi); assigned new in the ctor |
| `+0x18` | `animation` | `NSettlers::Animation` | action timer: `+0x1c kind`, `+0x20 remaining`, `+0x24 total` |
| `+0x28` | `ownerPlayer` | player entry* | first dword of the entry is the player index |
| `+0x30` | `package` | `ReferencePackage` | carried package; id hi at `+0x44`, cached pointer at `+0x48` |
| `+0x50` | `movement` | `SettlerMovement*` (0x1d8) | owned, see 2.9 |
| `+0x54` | `state` | int | state number, one shared numbering for all classes, see 2.4 |
| `+0x58` | `property` | `GoodProperty*` | profession record; `+0x00 id`, `+0x7c settlerType`, `+0x88 max health` |
| `+0x5c` | `moveToShip` | `NMovie::MoveToShip` | |
| `+0x70/+0x74` | `lookAtPos` | cell (x,y) | `-1,-1` = none; presentation hint, but saved |
| `+0x78` | `leaveMap` | `NMovie::LeaveMap` | the "go home" script, state 3 |
| `+0xb8` | `leaveBuilding` | `NMovie::LeaveBuilding` | used for state 0 |
| `+0xd8` | `homeBuilding` | `ReferenceBuilding` | id hi at `+0xec` |
| `+0xf8` | `ship` | `ReferenceShip` | id hi at `+0x10c` |

**[known]** (ctor S 00656c20, dtor S 006568b0, Store S 00656a20). A reference is *valid* when its id-hi dword is
in `0..0x7fffffff` (the test `-2 < (int)id && (uint)id < 0x80000000` appears at every use; its unsigned half
excludes `-1`, the value of an empty reference). **[known]**

Virtual slots of `Settler` (Worker vftable 007f84dc read from memory): **[known]** for the slot numbers,
**[inferred]** for the meanings not marked otherwise.

| Slot | Offset | Role |
|---|---|---|
| 0 | `+0x00` | cell where the settler is put down when leaving a ship: takes the ship, returns the address `+0x20` of the object referenced at `(ship +0x24) +0x60` (S 006567b0) **[known]**; that object being the harbour the ship is docked at is **[inferred]**. No class overrides it (the Soldier entry S 00658780 is a jump to the same code) **[known]** |
| 1 | `+0x04` | "may queue at the flag at my route target": the settler's ship reference (`+0xf8`, id hi `+0x10c`) is valid (S 006567d0). No class overrides it **[known]** |
| 3,4,5,6 | `+0x0c..+0x18` | `Store`, `Load`, `PostLoad`, `StoreUntagged` **[known]** |
| 7 | `+0x1c` | `Update` (per tick) **[known]** |
| 8 | `+0x20` | called with the building when `EnterBuilding` completes; no-op except for `Soldier` |
| 9 | `+0x24` | "has not arrived yet": state is one of {0,1,3,4} (Worker and Constructor, S 0065c7b0), {0,1,3,0x11} (Carrier S 0065a7e0), {0,1,3,4,0x11,0x26} (Soldier S 00658830), {0,1,3,8} (Specialist S 0065eae0), {0,1,3} (NPC S 0065dc40); pure virtual in the base **[known]**. Simulation caller: `NVillage::Workers::HasArrivedWorker` S 0055b4d0 (a building counts as occupied once one linked worker returns false) **[known]** |
| 10 | `+0x28` | `IsInWorkCycle` (2.4). Constructor S 0065e2a0: state 0x1b with `ConstructBuilding` step 10, or state 0x1c with `ConstructShip` step 2, 10, 0x13 or 0x18; Specialist S 0065eb00: state 10 or 11; NPC: always false **[known]** |
| 11 | `+0x2c` | target cell of "go to working place": cell `+0x28` of a flag. Worker S 0065cca0: the workplace's flag; Constructor S 0065e450: the flag (`building +0xa0`) of its site `+0x188`; Soldier S 00658e50: the flag of the building referenced at `+0x1c0` if that reference is valid, else of the one at `+0x358`; Specialist S 0065ec60: its target flag `+0x138`; Carrier S 0065ab00: the cell at `Street +0x28` of its street; NPC S 0065dd40: a static `(-1,-1)` **[known]** |
| 12,13 | `+0x30/+0x34` | animation-speed flag / factor used by `Fight::Update`; base returns false / 1.0 (S 0041ecc0, S 00656880); only `Soldier` overrides them (S 00658ea0, S 00658ed0) **[known]** |
| 14 | `+0x38` | release links before going home. Base, Constructor and NPC: empty (S 005657b0). Worker: release the dig reservation. Soldier S 00658f40: unlink from the building at `+0x1c0`, release the ship link, unlink order and pairing. Specialist S 0065eaa0: unlink from its target flag and release the reserved dig cell **[known]** |

Vftables (15 slots each, read from memory): Settler 007f83bc, Soldier 007f842c, Carrier 007f847c, Worker
007f84dc, NPC 007f8544, Constructor 007f8594, Specialist 007f8604. **[known]**

### 2.4 State numbers (`Settler +0x54`)

One numbering is shared by all classes; a number can mean different things in different classes. **[known]** for
every row (the constant appears in the named `Update`), names are descriptive.

| State | Used by | Meaning |
|---|---|---|
| 0 | all | leaving the building it was created in (`LeaveBuilding` movie running); set by the ctor |
| 1 | all | ready, nothing started yet (the class `Update` starts its first movie) |
| 2 | all | entered a building: removed by `System` this tick, value returned to the building |
| 3 | all | no job: going home (`LeaveMap` movie) |
| 4 | Worker, Constructor, Soldier | `GoToWorkingPlace` / `GoToConstructionPlace` |
| 5 | all | dying (death animation) |
| 6 | all | dead: removed by `System` this tick |
| 7 | Soldier | leave building to fight |
| 8 | Specialist | walking to its target flag |
| 10 | Specialist | `GoDigging` |
| 11 | Specialist | `ReturnToWorkingPosition` |
| 0x0c | Worker / Soldier | Worker: `IdleOutside`; Soldier: idle in building |
| 0x0d, 0x0e, 0x0f, 0x21, 0x26, 0x28..0x37 | Soldier | combat and ship states, see `navy-and-military.md` |
| 0x11 | Carrier, Soldier | `LeaveBuilding` |
| 0x12 | Carrier / NPC | Carrier: `GoToPackageTarget`; NPC: walking to a cell |
| 0x13 | Carrier / Worker | Carrier: `EnterBuilding` with the package; Worker: `ReturnFromIdle` |
| 0x14 | Carrier | inside the destination building, deliver |
| 0x15 | Carrier | `LeaveBuilding` after delivery |
| 0x16 | Carrier | `WaitForPackage` |
| 0x17 | Carrier | `MoveToStreetPosition` to the flag holding the chosen package |
| 0x18 | Carrier | `Pickup` |
| 0x19 | Carrier | `PutDownPackage` (street carrier) / `Drop` (unassigned carrier) |
| 0x1a | Carrier / NPC | Carrier: stepping one cell back onto the street; NPC: fine move |
| 0x1b | Constructor | `ConstructBuilding` |
| 0x1c | Constructor | `ConstructShip` |
| 0x1d | Worker | work movie of the workplace's working mode |
| 0x1e | Worker | second work movie (mode 2: planting; mode 5: rest after a catapult shot) |
| 0x20 | Worker | `BringGoodHome` |
| 0x21 | Worker | `ReturnHome` (empty-handed) |
| 0x23 | Worker | `Rest` |
| 0x24 | Worker | production finished, waiting to release the produced settler/animal |
| 0x29, 0x2f | NPC | idle / returning to the grid |
| 0x35 | Worker | `BringGoodOut` |

Helper predicates: **[known]**

- "active" = state not in {0, 2, 3, 5, 6} (S 006567f0). A class `Update` does nothing after the base update when
  the settler is not active.
- `Worker::IsInWorkCycle` = state in {0x1d, 0x1e, 0x20, 0x21, 0x24, 0x35} (S 0065c7d0).
- `Carrier::IsInWorkCycle` = state in {0x12, 0x13, 0x14, 0x15, 0x17, 0x18, 0x19, 0x1a} (S 0065a800).
- "cinematic" states (screensaver camera only, no simulation effect) = {4, 5, 9, 10, 0xd, 0x10, 0x12, 0x13, 0x15,
  0x17, 0x18, 0x19, 0x1d, 0x1e, 0x1f, 0x2e, 0x30} (S 006566d0).

### 2.5 `NSettlers::Animation` — the action timer (S 0065f0a0)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04` | `kind` (int) | 0 = none; which action animation plays |
| `+0x08` | `remaining` (float) | ticks left |
| `+0x0c` | `total` (float) | duration it was started with |

`Start(kind, duration)` sets all three (S 0065f080). `Tick` (S 0065f040): if `kind != 0`, `remaining -= 1.0`; when
the result is `<= 0` set `kind = 0`, `remaining = 0`. `Reset` clears it. **[known]** The timer is simulation state:
movies wait on `remaining <= 0`. A duration of 3.3 therefore lasts 4 ticks: the animation kind is visible for
3 ticks (remaining 2.3, 1.3, 0.3) and the timer runs out in the 4th. **[known: live 2026-10-12, 96 phases]**

Kinds used by the simulation: **[known]** (constants in the named functions)

| Kind | Started by |
|---|---|
| 2 | first half of pick-up and put-down (`Pickup::Start`, `PickupProduct::Start`, `Drop::Start`) |
| 3 | second half of pick-up and put-down (`Pickup::Update`, `Drop::Update`) |
| 4 | work: `Working`, `ProduceGood`, hammering (`Construct`, `ShipConstruct`), `Fight`, `RotateCatapult`, digging |
| 5 | alternative work animation (`Working` on an exhausted/flagged deposit, `ShootCatapult`, digging variant) |
| 6 | dying |

### 2.6 `NSettlers::Worker` (ctor S 0065d080)

| Offset | Field |
|---|---|
| `+0x118` | game system pointer |
| `+0x120` | `workplace` (`ReferenceBuilding`, id hi at `+0x134`) |
| `+0x140` | `GoToWorkingPlace` |
| `+0x168` | `GoMining` (step at `+0x170`) |
| `+0x1b0` | `GoFishing` (step at `+0x1b8`) |
| `+0x1fc` | `GoHunting` (step at `+0x204`) |
| `+0x244` | `BringGoodHome` |
| `+0x2bc` | `BringGoodOut` |
| `+0x32c` | `ReturnHome` |
| `+0x368` | `GoAfforest` |
| `+0x3c0` | `ProduceGood` |
| `+0x3c8` | `SearchCatapultTarget` |
| `+0x3d0` | `CatapultAttack` |
| `+0x3ec` | `Rest` (`+0x3f4` ticks left) |
| `+0x3f8` | `GoDigging` |
| `+0x450` | `lastWorkTick` (uint, logic tick of the last finished work step) |
| `+0x454` | `IdleOutside` |
| `+0x468` | `ReturnFromIdle` |

**[known]**

### 2.7 `NSettlers::Carrier` (ctor S 0065ab20)

| Offset | Field |
|---|---|
| `+0x11c` | `LeaveBuilding` |
| `+0x13c` | `EnterBuilding` |
| `+0x148` | `Drop` |
| `+0x154` | `WaitForPackage` |
| `+0x174` | `MoveToStreetPosition` |
| `+0x17c` | `PutDownPackage` |
| `+0x194` | `GoToPackageTarget` |
| `+0x1a8` | `Pickup` |
| `+0x1b8` | `notYetOnStreet` (byte, 1 in the ctor, 0 once assigned to a street) |
| `+0x1c0` | `building` (`ReferenceBuilding`) — the building that sent this carrier out with a package: set by `NTransport::System::SpawnCarrierWithPackage` through S 0053d2b0, which also adds the carrier to that building's depot settler list (`depot +0x74`); cleared by S 0053d2d0 from `Depot::DetachAllSettlers` S 0055b250 and the carrier dtor. `Carrier::Update` does not read it |
| `+0x1e0` | `reservedPackage` (`ReferencePackage`) |

**[known]** The street a carrier serves is stored in its movement object: `ReferenceStreet` at
`SettlerMovement +0xa0` (id hi `+0xb4`, cached pointer `+0xb8`). **[known]** (S 0065b150, S 0065a690). A street
has two carrier slots: `Street +0x78` (first) and `Street +0x98` (second; id at `+0xa8/+0xac`), and a traffic
counter at `Street +0xd8`. **[known]** (S 0065a6f0, S 0065b200). The good that fills the second slot is the
tribe's `tp_setSecondCarrierId` (`TribeProperty +0xb0`): `good_oxen` for the Bavarians, `good_helper` for the
Egyptians, not set for the other tribes (`tribes.lua`) **[known]**; when a street asks for it is in
[`streets-transport.md`](streets-transport.md).

### 2.8 Constructor, Specialist, NPC

- `Constructor` (S 0065e470): `+0x120` ship reference, `+0x140` `GoToConstructionPlace`, `+0x15c`
  `ConstructBuilding`, `+0x188` building reference (the construction site), `+0x1a8` `ConstructShip`. **[known]**
- `Specialist` (the scholar/geologist, `good_scholar`): holds `MoveToWorkingPlace`, `GoDigging`,
  `ReturnToWorkingPosition` and a `ReferenceFlag` at `+0x138` (id hi `+0x14c`; the flag it was sent to).
  **[known]** (S 0065eec0, S 0065eaa0, S 0065ec60, S 00561e20).
- `NPC`: `+0x11c/+0x120` target cell (`-1` = none), `+0x124/+0x128` target fine position, movies
  `MoveToPosition`, `ReturnToLogicGrid` and `MoveToFinePosition` (`+0x13c`). **[known]** (S 0065ddf0).
  `SetMoveTargetCell` (S 0065df90) and `SetMoveTargetFinePos` (S 0065dfd0) clear a look-at position, set
  `movement.holdStep` when the movement is busy, and store the target. **[known]** Their only callers are the
  mission-script calls `se_moveNPCTo` (S 005ae3b0) and `se_moveNPCToFine` (S 005ae490). **[known]** The NPC
  also has a byte `active` at `+0x144` (0 in the ctor); `NPC::Update` does not read it. **[known]**

### 2.9 Movement objects

`ai::settlers::SettlerMovement` (0x1d8) = `ai::movement::Movement` (0x130) plus settler-specific fields.

`ai::movement::Movement` **[known]** (S 00773450, S 007730e0, S 00773010):

| Offset | Field | Meaning |
|---|---|---|
| `+0x00` | `interpolator` (`NMovement::Interpolator`) | `+0x04 progress`, `+0x08 carryOver`, `+0x0c stepRate` (floats) |
| `+0x10` | `rough` (`NMovement::Rough`) | cell-grid mover; `+0x30/+0x34` its current cell, `+0x38` final target |
| `+0x40` | `rough.path` (`NMovement::Path`) | `+0x44 mode`: 0 none, 1 free path, 2 street path |
| `+0x50` | free path (`NMovement::FreePath`) | A* result, `+0x70` (`Movement`) = `astarMode` byte |
| `+0x78` | street path (`NMovement::StreetPath`) | `+0x80 active`, `+0xa0` current street reference |
| `+0xc8` | `fine` (`NMovement::Fine`) | fine-grid mover; `+0xd4` = "fine move active" byte, `+0xe8` current fine pos |
| `+0x118` | `stopDistance` (uint) | stop when fewer cells than this remain; 0 = walk to the end |
| `+0x11c/+0x120` | `finePos` | position in fine units |
| `+0x124` | `holdStep` (byte) | finish the current step, then stop |
| `+0x128/+0x12c` | `cell` | logic cell the settler is on |

`SettlerMovement` additions **[known]** (Ghidra struct `SettlerMovement`, ctor S 00657a80):

| Offset | Field | Meaning |
|---|---|---|
| `+0x130` | `owner` | the settler |
| `+0x134` | `renderDirty` (byte) | presentation only |
| `+0x138/+0x13c` | `routeTarget` | final cell of a street walk |
| `+0x140/+0x144` | `nextFlag` | next flag on the route (`-1` none) |
| `+0x148/+0x14c` | `nextWaypoint` | cell the current leg walks to |
| `+0x150` | `routeEndRequested` (byte) | stop at the end of the current leg |
| `+0x154` | `streetMode` (int) | 1 = was street-walking when it started to wait at a flag |
| `+0x158` | `waitFlag` (`ReferenceFlag`, id hi `+0x16c`) | flag it is queued at |
| `+0x178` | `ship` (`ReferenceShip`, id hi `+0x18c`) | ship it rides |
| `+0x198` | `WaitForShip` movie | walks to and from the parking spot |
| `+0x1b4` | `ReturnToLogicGrid` movie | |
| `+0x1bc/+0x1c0` | `parkingCell` | cell of the parking place at the flag |
| `+0x1c4/+0x1c8` | `parkingSpot` | fine position of the parking place |
| `+0x1cc` | `flagWaitState` (int) | 0 none, 2 queued, 3 parked, 4 aboard a ship, 5/6 leaving the queue, 7 done |
| `+0x1d0` | `flagWaitTicks` (int) | |
| `+0x1d4` | `streetStopDistance` (int) | stop distance while on a street route |

Coordinate systems: **[known]**

- *Cell*: the logic grid `(x, y)`, hex layout, `0 <= x < g_MapWidth`, `0 <= y < g_MapHeight`.
- *Fine position*: 4 units per cell. Cell centre in fine units = `(x*4 + (y odd ? 2 : 0), y*4)` (S 00657f10,
  S 007730e0). The fine grid uses the same hex stepping functions as the cell grid (`MapPos::StepDirection`,
  `HexDistance`, `GetHexDirectionTo`).
- Hex directions are numbered 0..5. `ai::map::MapPos::StepDirection(dir, steps)` (S 00675000) adds, per step,
  `dx[dir + 8*(y & 1)]` and `dy[dir + 8*(y & 1)]` from the tables at S 00880f28 (dx) and S 00880f68 (dy):
  **[known]**

  | dir | 0 | 1 | 2 | 3 | 4 | 5 |
  |---|---|---|---|---|---|---|
  | `(dx, dy)`, `y` even | (+1, 0) | (0, -1) | (-1, -1) | (-1, 0) | (-1, +1) | (0, +1) |
  | `(dx, dy)`, `y` odd | (+1, 0) | (+1, -1) | (0, -1) | (-1, 0) | (0, +1) | (+1, +1) |

  Odd rows are shifted half a cell toward +x (see the fine centre above), so with `y` growing downward the
  directions are 0 = east, 1 = north-east, 2 = north-west, 3 = west, 4 = south-west, 5 = south-east; `d` and
  `(d + 3) % 6` are opposite. **[inferred]** These compass names are not screen directions: on screen, camera
  unrotated, direction 1 points to the lower side, slightly left (about south-south-west), not to the lower
  right neighbour; a farm at anchor (62, 88) had its door flag at (62, 87) **[live, 2026-10-14]**. The tables
  also hold entries 6 and 7 = `(0, +2)` and `(0, -2)` for both parities **[known]**; settler code does not
  use them.
- The settler code uses direction **1** for "from the building cell to the cell in front of the door" (the
  building's flag cell) and direction **4** for the opposite step. **[known]**

### 2.10 Movies (`NMovie`)

- `NMovie::Object` (S 0077df40): `+0x00` vftable, `+0x04` owner settler. Virtuals: slot 1/2 `Store`/`Load`,
  slot 3 (`+0x0c`) `Start()` → bool "could start", slot 4/5 (`+0x10`/`+0x14`) `Start(arg)` variants taking a
  target position, slot 6 (`+0x18`) `Update()` → bool "finished". **[known]** (S 00656670..006566b0).
- `NMovie::Package` (S 0077de20): an `Object` plus `+0x08 currentStep` (int); a composite movie that embeds
  sub-movies and switches between them with `StartStep(sub, stepId)` = set `currentStep`, call `sub.Start()`
  (S 0077de50). The step id says which sub-movie is running. **[known]**

A settler runs one top-level movie at a time; the settler's `state` says which. `SetStateAndStartMovie(movie,
state)` writes the state first and then calls `Start`, returning its result (S 00656670). **[known]** Note that
the state stays written even when `Start` returns false; callers handle the failure.

Step ids seen across packages (same numbering everywhere): 1 leave from idle spot, 2 walk to working place,
3 enter building, 4 bring good to working place, 7 search, 8 leave building, 9 move to target, 10 work,
0x0b move home, 0x0c enter building, 0x0d be nervous, 0x0e return to logic grid, 0x0f wait until idle,
0x10 wait for free flag, 0x11 put down, 0x12 pick up product, 0x13 drop, 0x14 waiting at target,
0x15 walk back to waiting spot, 0x16 move to position, 0x17 move away from deposit, 0x18 (per package:
`LeaveMap` looks for a home, `ReturnHome` walks back to the working place, `WaitForShip` walks to the flag
cell; `ConstructShip` S 0077d6c0 starts it when `ShipConstruct` (10) ends: `MoveToPosition` back to cell
`+0x28` of the shipyard's entrance flag (`building +0xa0`); at its end, remaining work on the ship
(`NNavy::Construction::HasRemainingWork`) → decision step 7 (fetch the next good), none → message
`!Ship constructed` (kind 6, at the ship's cell) and finished **[known]**), 0x19 stray, 0x1c/0x1d/0x1e catapult
rotate/shoot/rotate back, 0x20/0x21 leave building straight/sideways.
**[known]** (constants in S 00776bd0, S 00776eb0, S 0077c510, S 0077b880 and the other `Update` functions).

---

## 3. Rules and algorithms

### 3.1 Creation

`System::CreateSettler(player, cell, goodId)` (S 00656500) switches on the good's `settlerType` and calls the
matching creator; unknown types create nothing. Each creator allocates the object, runs the ctor and appends it
to its list. **[known]**

The base ctor (S 00656c20) assigns a new `Unique`, stores owner and property, creates the movement object at
`cell`, and sets `state = 1`; if the `leaveBuilding` argument is set it sets `state = 0` and starts the
`LeaveBuilding` movie. **[known]**

| Caller | Type | Start cell | `leaveBuilding` | Follow-up |
|---|---|---|---|---|
| `NVillage::Workers::SpawnWorker` S 0055b6a0 | Worker of the building's `bp_setWorker` good | building `+0xf8` | 0 | linked to the building as its worker; state set to 0x1d if working mode is 8, else 0x23 (S 0065c710) |
| `NVillage::SettlerSpawn::SpawnWorker` S 005644c0 | Worker | building `+0xf8` | 1 | walks out; the order system links it to its workplace |
| `SettlerSpawn::SpawnConstructor/Specialist/Carrier` S 00564460 / 00564490 / 005644f0 | resp. | building `+0xf8` | Constructor and Specialist: 1 (their ctors), Carrier: 0 | |
| `SettlerSpawn::SpawnSettlerOfGood` S 00564e00, good of any other settler type (NPC, unknown) | a `Worker` object | building `+0xf8` | 1 | soldiers (type 3) go through `SpawnSettlerRestoringValue` instead |
| `NNet::Street::SpawnCarrier` S 00668be0 | Carrier `0x7bff15ce` | street midpoint (`Street +0x28`) | 0 | assigned to the street's first slot, state 0x16 `WaitForPackage` started |
| `NTransport::System::SpawnCarrierWithPackage` S 0064d020 | Carrier `0x7bff15ce`, through `SettlerSpawn::SpawnCarrier` | building `+0xf8` | 0 | only when the building's flag stacks are not full for the good; one unit of the good is removed from the building stock and created as a package in the carrier's hands; unassigned carrier that brings it to the flag (3.6.1) |
| Lua `se_createSettler(player, good, x, y)` S 005ae160 | by the good's type; nothing for other types | given cell (player index `< 8`, player active, cell inside the map) | Worker, Constructor, Specialist, NPC: 1; Carrier, Soldier: 0 | |

**[known]** for the calls; "building `+0xf8`" is the building's door/work cell (the cell a worker stands on when
it is "inside"). **[inferred]**

`Workers::SpawnWorker` is used when a building is placed complete and when a building is conquered
(callers `Building::ctor_Place` S 0055d980 and `System::ConquerBuilding` S 0055a890; the third caller is
`LuaMenu_CreateBuildingWithSettler` S 005d9ac0). **[inferred]** In state 0x23 without a started `Rest` movie
the rest counter is 0, so the next update finishes the rest at once and the worker chooses work. **[inferred]**

#### Training (tools)

There is no training time. A profession is a good with a cost list (`properties.gp_addCost(good_woodcutter, tool,
1)`; the Bavarian set uses `toolBav`, the Scots set `toolScots`). When a building releases a settler,
`SettlerSpawn::ConsumeSettlerGood` (S 00564360) does, unless the spawn is flagged busy: **[known]**

1. `spawnCooldown = 10` (ticks; decremented once per tick by `SettlerSpawn::Update`, S 00564780).
2. If the building stock does not hold the profession good, `Stock::ExchangeCostForGood(good)` converts its cost
   (the tool) into one unit of the good.
3. Remove one unit of the profession good from the stock.

`SettlerSpawn::CanSupplyGood` (S 005643c0): a non-soldier good can be supplied when the stock holds it or can
afford its cost; a soldier good when the stock holds any good of the owner's soldier list for that soldier type.
**[known]** The carrier `good_helper` and NPC goods have no cost. **[known]** (Jobs.lua).

When a settler enters a building again (state 2, see 3.3), `SettlerSpawn::OnSettlerEntered` (S 00564eb0) returns
value to the stock. A settler whose profession has an empty cost list returns nothing (this test comes first,
for soldiers too). Otherwise a soldier is added back as its own good and its hit points are remembered for
healing; any other settler adds *its cost list* (the tool), not the profession good. **[known]**

Which settler is released for which need (worker for a new building, carrier for a street, builder for a site) is
decided by the village order system. When an order completes, `VillageOrder_LinkSettlerToDestination`
(S 00561e20) first looks at the order category (`VillageOrder_GetCategory`): 4 → soldier pair link plus military
order slot 1 of the building at `order +0xe0`; 1 → military slot 0; 5 → military slot 2; 3 → the settler's
destination reference is set to the building at `order +0x8`; 6 → the settler is linked to the ship at
`order +0x28`. For every other category it links by settler type: Worker → building worker list, Constructor →
construction site, Carrier → street at `order +0x80` (second slot `+0x98` if the first slot `+0x78` holds a valid
reference, else first), Soldier → building, Specialist → flag at `order +0x60`. **[known]**

`VillageOrder_GetCategory` (S 005686a0) tests in this order: **[known]** 4 = the reference at `order +0xe0`
(id hi `+0xf4`) is valid; 1 = the reference at `+0xa0` (id hi `+0xb4`) is valid; 5 = the reference at `+0x120`
(id hi `+0x134`) is valid; 3 = the building reference at `+0x8` is valid, that building has no construction
work left, and its type is `depot` (`BuildingProperty +0x54`) or it is `casern` (`+0xf1`) and the ordered good
is a soldier; 0 = any other order with a building; 6 = the ship reference at `+0x28` (id hi `+0x3c`) is
valid; 0 otherwise. The three references of categories 4, 1 and 5 are the soldier-exchange slots 1, 0 and 2
of a military building; their rules are in [`village-buildings.md`](village-buildings.md) (order system) and
[`military.md`](military.md). Category 3 is thus "a settler or soldier sent to be stored in a finished
storehouse or barracks". **[inferred]**

### 3.2 Base update (`Settler::Update`, S 00656ec0)

Called first by every class `Update`: **[known]**

1. `animation.Tick()`.
2. `ai::settlers::SettlerMovement::Update(movement)` (3.8).
3. By state:
   - **0**: if `leaveBuilding.Update()` reports finished → `state = 1`.
   - **3**: if `leaveMap.Update()` reports finished: find the owner's building nearest to the current cell with
     `BuildingList_FindNearestReachable(list, owner, cell, maxDist = -2, mode = 1, layer = 1)` (S 00557fe0 through
     S 005586d0 / S 00558700; soldiers use the list at `NVillage::System +0x74`, others the list at `+0x20`;
     `maxDist = -2` means no distance limit; see 3.4 for the modes). That the two lists are the military and
     the storehouse lists is **[inferred]**.
     If one exists and `HexDistance(building cell, settler cell) < 2` → `state = 2`, else `StartDying()`.
   - **5**: if `remaining <= 0` → `state = 6`. Otherwise if `total - remaining == 14.0` exactly and the configured
     skeleton doodad id is not -1 and no doodad is at the settler's fine position: add the skeleton doodad there.

`StartDying()` (S 00656760): `state = 5`; reset a running animation; abort movement if busy; start animation kind
6 for `cfg SettlerDyingTime` ticks. **[known]**

`StopAndSetState3()` (S 00656740) = "lose the job": call virtual slot 14 (release links), `state = 3`, start the
`LeaveMap` movie. **[known]**

### 3.3 Removal (`UpdateSettlerVector`, S 00654a10)

For each list, index `i` from 0: **[known]**

- `state == 2`: look up the owner's nearest building from the settler's cell (the same unlimited-distance search
  as in 3.2, state 3; no distance test here); if found call `building.settlerSpawn.OnSettlerEntered(settler)`.
  Erase and delete the settler; do not advance `i`.
- `state == 6`: erase and delete; do not advance `i`.
- otherwise call `settler->Update()` and advance `i`.

The element count is read once before the loop and decremented on erase, so settlers appended during the loop are
not updated until the next tick. **[inferred]**

Destructors unlink: the base dtor discards a carried package (`NTransport::System::DiscardPackage`), unlinks home
building and ship, and deletes the movement object; `Worker` removes itself from its workplace's worker list;
`Carrier` releases its packages and frees its street slot. **[known]** (S 006568b0, S 0065d220, S 0065afb0).

### 3.4 Going home (`NMovie::LeaveMap`, state 3)

`Start` (S 00776d00): discard a held package; `ai::settlers::SettlerMovement::CancelRoute` if a street route is active
(`StreetPath.active`, `movement +0x80`) or the settler is queued at a flag or aboard a ship (a free or fine
walk is left running; step 0x0f waits for it); clear a set look-at position; `step = 0x0f`;
`strayRetries = 0`. **[known]**

`Update` (S 00776bd0): **[known]**

| Step | Condition | Action |
|---|---|---|
| 0x0f | movement not busy | start `ReturnToLogicGrid` → step 0x0e |
| 0x0e | sub-movie finished | step 0x18 |
| 0x18 | — | start `MoveToHome` (step 0x0b); if it cannot start, start `Stray` (step 0x19) |
| 0x0b | finished | start `EnterBuilding` (step 0x0c) |
| 0x0c | finished | movie finished |
| 0x19 | `Stray` finished | Soldier: lose 1 hit point; if still alive → step 0x18, else finished. Others: if `strayRetries < 26` then `++strayRetries`, step 0x18; else finished |

A non-soldier therefore strays at most 27 times (the 27th `Stray` finds `strayRetries == 26`). **[inferred]**
When the movie finishes away from a building the base update kills the settler (3.2). **[known]**

The building search `BuildingList_FindNearestReachable(list, player, pos, maxDist, mode, layer)` (S 00557fe0) has
two modes: **[known]**

- mode 0 (street-connected): needs a flag of the player on `pos` (else no result) and returns
  `BuildingList_FindNearestConnected(list, flag, layer)` (S 00557ef0); `maxDist` is not used. That callee
  iterates the list front to back; a building qualifies when its two remaining-work floats
  (`(building +0x44) +0x70`, `+0x74`) are both `<= 0` and its flag (`building +0xa0`) has the same
  net-continent id as the start flag for net kind `layer` (`NLogic_UniqueArray40_IsEqualAt`). The result is the
  qualifying building with the smallest `NNet::System::GetFlagPathCost(startFlag, buildingFlag, layer)`; on
  equal cost the earlier list entry wins. The callee has no owner test of its own. The path cost and the net
  kinds (0 goods, 1 walking) are defined in [`streets-transport.md`](streets-transport.md); every settler
  search in this document passes `layer = 1`.
- mode 1 (by distance): iterates the list front to back; a building qualifies when it belongs to the player,
  the two floats at `(building +0x44) +0x70` and `+0x74` are both `<= 0` (expected: no construction work
  left, **[inferred]**), and its continent is connected to the continent of `pos` for the player (by
  `Navy_AreContinentsConnectedForPlayer`, or through the continent id set of the building's flag for `layer`).
  The result is the qualifying building with the smallest `HexDistance(building cell, pos)`, which must be
  `<= maxDist` unless `maxDist == -2` (no limit); on equal distance the earlier list entry wins.

`MoveToHome::Start` (S 007776f0), with `R = gameConfig +0x30` (default 30, no Lua setter found): **[known]**

1. Target building = the home reference if valid; else (soldier that can complete an order where it stands →
   success at once) the mode-0 search from the settler's cell (soldiers: list `+0x74`, others: list `+0x20`;
   `R` is passed but unused in mode 0), layer 1.
2. If a building was found: street-walk to the cell one step in direction 1 from the building cell (its flag
   cell); success ends `Start`. If the street walk cannot start, continue with step 3.
3. Mode-0 search from the cell one step in direction 1 from the settler's cell (so that cell must hold a flag
   of the owner): if it finds a building, free-walk to that cell and return the result of the walk.
4. Otherwise mode-1 search from the settler's cell with `maxDist = 1000`. If the found building's flag reference
   (`building +0xa0`, id hi `+0xb4`) is valid: `NNet::System::FindNearestFlagWithLink(owner, cell, flag +0x50,
   1)`; if that returns a flag with `HexDistance(flag cell, settler cell) <= R`: free-walk to the flag's cell.
5. Otherwise fail.

`NNet::System::FindNearestFlagWithLink(player, pos, id, kind)` (S 00663f50) iterates the player's flag vector
front to back. A flag is a candidate when its net-continent id for `kind` (`Flag +0x48 + kind*0x10`, two
dwords) equals the id passed (here: the walking-net continent of the home building's flag), and it is closer
to `pos` by `HexDistance` than the best so far (strictly; the first candidate always counts). Such a
candidate is taken only if the map continent id of `pos` (`NMap::Continents` grid, index `y*width + x`) is -1
or equals the map continent id of the flag's cell; a rejected candidate does not change the best. Result:
the nearest flag of the home building's street network on the settler's land mass, first in vector order on
equal distance, or none. **[known]**

`MoveToHome::Update` (S 007775f0): when movement is idle, if the building one step in direction 4 accepts this
settler (`SettlerSpawn::CanAcceptSettler`) → finished; else call `Start` again and finish only if that fails.
**[known]** `CanAcceptSettler` (S 00564520): barracks (`casern`) accept soldiers; a casern that is not also depot
and territory building accepts nothing else; otherwise a building with the `spawn` property accepts any
non-soldier. **[known]**

`Stray::Start` (S 0077e0c0): choose a neighbouring cell to wander to. **[known]** The six neighbours are visited
in ring order: start at the neighbour in direction 4, then step in directions 0, 1, 2, 3, 4.

1. Only when the settler stands on free water (`GameQuery::IsFreeWaterCell`): among the in-map neighbours that
   are free water or walkable, and provided the settler's *own* cell is explored by the owner, take the one
   with the greatest vertex height that is strictly higher than the settler's cell (first in ring order on
   equal height).
2. If step 1 chose nothing: draw `n = LogicRandom % 6` (one draw, also when not on water). Visit the ring; a
   neighbour is acceptable when it is in the map, explored by the owner, and either walkable or (free water
   while the current target, i.e. the settler's cell or the last accepted neighbour, is free water). Each
   acceptable neighbour becomes the target and decrements `n`; stop when `n < 0`. So the target is acceptable neighbour number `n + 1`, or the last acceptable one when
   there are fewer; with none the target stays the settler's own cell.
3. Start `MoveToPosition(target)` as step 0x16; `Start` returns whether that could start.

### 3.5 Worker

#### 3.5.1 Working modes

The workplace's `BuildingProperty +0x80 workingMode` (Lua `bp_setWorkingMode`, ctor default 6) selects the job.
Values and names from `buildings.lua`: **[known]**

| Mode | Lua name | Work movie | Example buildings |
|---|---|---|---|
| 0 | `BuildingWorkingMode_Foresting` | `GoAfforest` | forester |
| 1 | `BuildingWorkingMode_Mining` | `GoMining` | woodcutter, stone pit |
| 2 | `BuildingWorkingMode_Farming` | `GoMining` if a deposit is linked, else `GoAfforest` | farm |
| 3 | `BuildingWorkingMode_Fishing` | `GoFishing` | fisher |
| 4 | `BuildingWorkingMode_SettlerBreeding` | `ProduceGood`, then release a settler | oxen breeding, caserns |
| 5 | `BuildingWorkingMode_Catapult` | `CatapultAttack` | catapult |
| 6 | `BuildingWorkingMode_Producing` | `ProduceGood` | all workshops (default) |
| 7 | `BuildingWorkingMode_Hunting` | `GoHunting` | hunter |
| 8 | `BuildingWorkingMode_Idling` | none | watch tower |
| 9 | `BuildingWorkingMode_Sacrifice` | none | sacrifice sites |
| 10 | `BuildingWorkingMode_AnimalBreeding` | `ProduceGood`, then spawn an animal | sheep breeding |
| 11 | `BuildingWorkingMode_Scholar` | `GoDigging` | scholar hut |

#### 3.5.2 `Worker::Update` (S 0065d7f0)

1. Base update. Return if not active.
2. If the workplace reference is invalid → `StopAndSetState3()`; return.
3. By state: **[known]**

| State | Rule |
|---|---|
| 1 | start `GoToWorkingPlace` with state 4; if it cannot start → `StopAndSetState3()` |
| 4 | `HasArrivedAtWorkplace()`: when the movie is finished, if the settler's cell equals the workplace work cell (`building +0xf8/+0xfc`) → `lastWorkTick = tick`, `ChooseNextWork()`; if it finished elsewhere → `StopAndSetState3()` |
| 0x0c, 0x13, 0x23 | when `IdleOutside` / `ReturnFromIdle` / `Rest` finishes → `ChooseNextWork()` |
| 0x20, 0x21 | when `BringGoodHome` / `ReturnHome` finishes → `RestOrIdleOutside()` |
| 0x35 | when `BringGoodOut` finishes: working mode 8 or 9 → `ChooseNextWork()`, else `RestOrIdleOutside()` |
| other | per working mode, table below |

Per-mode handling of the remaining states. In every row "stamp" means `lastWorkTick = tick`, and "count" means
`NLogic::Statistics::RegisterProductionEvent(workplace)`. **[known]**

| Mode | State 0x1d: work movie finished | Other |
|---|---|---|
| 0 | stamp, count, `ReturnHome` (0x21) | |
| 1 | stamp; if `GoMining.step == 10`: count, `BringGoodHome` (0x20); else `ReturnHome` (0x21) | |
| 2 | as mode 1 | state 0x1e: `GoAfforest` finished → stamp, `ReturnHome` (0x21) |
| 3 | stamp; if `GoFishing.step == 10`: count, `BringGoodHome`; else `ReturnHome` | |
| 4 | stamp, `state = 0x24` | state 0x24: see below |
| 5 | stamp, start `Rest` with state 0x1e | state 0x1e: `Rest` finished → `ChooseNextWork()` |
| 6 | stamp, `BringGoodOut` (0x35) | |
| 7 | stamp; if `GoHunting.step == 10`: count, `BringGoodHome`; else unlink a still-linked target animal from the workplace and `ReturnHome` | |
| 8, 9 | nothing (state 0x1d has no movie) | |
| 10 | stamp, `state = 0x24` | state 0x24: see below |
| 11 | stamp, `ReturnHome` (0x21) | |

State 0x24, mode 4 (S 0065d7f0): let `g = BuildingProperty +0xec producedSettler`. If `g == -1` or the building
cannot supply `g` → `RestOrIdleOutside()`. Otherwise, only when the building's `spawnCooldown == 0`:
`SpawnSettlerOfGood(g)` and add 1 of `g` to the owner's statistics; the worker stays in 0x24 (so it keeps
releasing one settler per cooldown until the stock cannot supply another). **[known]** Observed over 1,520 ticks
of a developed game: 8 workers entered 0x24; two released one settler on their first tick in it, stayed one more
tick and went to Rest (0x23), every 390 ticks; the other six spent one tick in 0x24 without a release and went to
Rest. With one unit in stock per production cycle that is one release, then rest; a building with several units in
stock was not seen. **[live, 2026-10-14]**

State 0x24, mode 10: if `producedSettler != -1`: remove entry 0 of the building's goods list (`bp_setGoods`: good
and amount, `Stock::RemoveEntry`) from its stock and spawn an animal of the id `producedSettler` at the building
cell, put into animal state 6. Then `RestOrIdleOutside()`. **[known]**

#### 3.5.3 `ChooseNextWork` (S 0065d660)

In this order: **[known]**

1. `TryStartBringGoodOut()`: if the workplace depot holds any ware: reset the catapult target pair, then start
   `ReturnFromIdle` (state 0x13) if the worker stands at the idle position, else `BringGoodOut` (state 0x35).
   Done.
2. If workplace production is not enabled: reset the catapult target pair; `RestOrIdleOutside()`. Done.
3. By working mode:
   - 0: start `GoAfforest` (0x1d). 1: `GoMining` (0x1d). 3: `GoFishing` (0x1d). 7: `GoHunting` (0x1d).
   - 2: if the workplace has a valid deposit reference (`building +0x50`, id hi `+0x64`) → `GoMining` (0x1d), else
     `GoAfforest` (0x1e).
   - 4, 6, 10: if `Production::CanStartProduction()`: `ReturnFromIdle` (0x13) when at the idle position, else
     `ProduceGood` (0x1d). Otherwise "failed".
   - 5: select a catapult target; if the catapult has ammunition and a target: `ReturnFromIdle` (0x13) when at
     the idle position, else `CatapultAttack` (0x1d). Otherwise "failed".
   - 8: `state = 0x1d`, no movie. Done.
   - 9 and anything else: nothing. Done.
   - 11: if `GoDigging` can start: `ReturnFromIdle` (0x13) when at the idle position, else `GoDigging` (0x1d).
4. If the chosen movie's `Start` returned false ("failed") → `RestOrIdleOutside()`.

`ReturnFromIdle` only walks the worker back in; when it finishes the state-0x13 rule calls `ChooseNextWork` again,
which then starts the work movie. **[inferred]**

#### 3.5.4 `RestOrIdleOutside` (S 0065d3b0)

If `tick - lastWorkTick > gameConfig +0x58` (unsigned compare; default 600, no Lua setter found) and the worker
is not at the idle position → start `IdleOutside` (state 0x0c). Otherwise start `Rest` (state 0x23). **[known]**

`Rest::Start` (S 0077b6d0) sets, through `ai::logic::SacrificeModifierQuery::GetScaledBuildingTimeE0` (S 00661bf0) and S 00663410 (disassembly):
**[known]**

```
restTicksLeft = trunc( restTime * effective[13] )
```

`restTime` = the int at `BuildingProperty +0xe0` of the workplace (`bp_setRestTime`, e.g. 222 for the
woodcutter, 55 for most workshops), converted to float; `effective[13]` = the float at `+0xe8` of the
sacrifice modifiers of the workplace's owner (`NSacrifice::System` at `GameSystem +0x60`, player block
`index * 0x188 + 0x20`, array `effective` at `+0xb4`); the product is truncated toward zero (`__ftol2_sse`).
Effect 13 is `Effect_WorkerPause` in `sacrifices.lua` (`sacrifice_workerPause`, value 300 = three times as
long, applied to the enemy). How the `effective` array is built from running sacrifices is in
[`military.md`](military.md) and [`properties-data.md`](properties-data.md). `Rest::Update` (S 0077b630)
decrements the counter and finishes when it is `< 1`. **[known]**

"At the idle position" (S 0065c740): a fine move is active (`movement +0xd4`) and the fine position equals
`Building_GetIdleFinePosition(workplace, 1)`. **[known]** Idle position `i` (S 0052ddb0) = fine centre of the
cell one step in direction 1 from the building cell, plus the truncated `(x, y)` offset number `i` of the
building property for the owner's tribe (`bp_setIdlePosition(building, tribe, index, x, y)`). **[known]**

#### 3.5.5 Worker movies

All step machines below: **[inferred]** from the function summaries unless marked; the functions were read where
a constant is quoted.

**`GoToWorkingPlace`** (`Start` S 00779e70, `Update` S 00779f20): step 2 = `MoveToWorkingPlace`: a street walk
(`SettlerMovement::StartStreetMoveTo`) to the owner's virtual target cell — for a worker the cell of the
workplace's flag. When it ends: if the settler is not exactly at its stop distance from the route target
(`ai::settlers::SettlerMovement::IsAtStopDistance`, S 006572f0: `HexDistance(routeTarget, cell) == streetStopDistance`, so
with no stop distance: standing on the target) the movie is finished; otherwise step 3 = `EnterBuilding`,
finished when that is. **[known]**

**`LeaveBuilding`** (`Start` S 00776f40, `Update` S 00776eb0): **[known]**
- A worker standing at its idle position uses `LeaveBuildingFromIdle` (step 1; its `Start` is the same code
  as `ReturnFromIdle::Start`, S 0077d3d0; `Update` S 0077e510): clear the look-at, fine-walk to idle
  position 0, then to the fine centre of the cell one step in direction 1 from the building cell.
- Otherwise let `F` = cell one step in direction 1 from the current cell. If the owner has a flag on `F`:
  free-walk to `F` (step 0x20). Else for `d` = 0, 1, 2 in this order: if the owner has a flag on the neighbour of
  `F` in direction `d`, free-walk one step in direction `d` from the *current* cell (step 0x21), and when idle
  walk one more step in direction 1 (step 0x20). If none: walk to `F` (step 0x20).
- Finished when movement is idle in step 0x20.

**`EnterBuilding`** (`Start` S 00777500, `Update` S 00778c20): `Start` fails if a building already stands on the
settler's cell; otherwise free-walk one step in direction 4. `Update`, when idle: state 0 — find the building at
the cell; if its property defines a door offset direction (`bp_setDoorOffsetDirection`), walk one more cell that
way (state 1); else notify the owner (virtual slot 8) and finish; with no building on the cell it finishes
without the notification. State 1 — notify with the building one step in direction 1 if there is one, finish.
Both walks pass `astarMode = true` (3.8.3). **[known]**

**`GoMining`** (modes 1, 2; `Start` S 0077d250, `Update` S 0077d090): `Start` fails when production is disabled;
else step 7 `LookForDeposit`. 7 → `LeaveBuilding` (8) → `MoveToDeposit` (9; if it cannot start the movie ends
with step ≠ 10) → `Working` (10) → finished with step 10 = success.
- `LookForDeposit::Start` (S 00778d50): succeeds iff the workplace already holds a deposit reference (the
  building subsystem assigns deposits). If not, and production is enabled and the building's productivity is
  below 0.5, it posts the player message `!No resources found.` (kind 3).
- `MoveToDeposit` (S 00777990, S 007778f0): free-walk to the deposit's cell with stop distance 1; then clear the
  stop distance, set the stop distance from the deposit property (`DepositProperty +0x50`) and fine-walk to the
  deposit's fine position; finished when idle.

**`Working`** (`Start` S 0077eda0, `Update` S 0077ebf0): **[known]**
- Duration = `BuildingProperty +0xd8` (`bp_setProductionTime`, e.g. 55 for woodcutter and forester), animation
  kind 4. For mode 2 with a deposit whose amount is `< 1.0` or whose flag `+0x50` is set, kind 5 instead.
- If the linked deposit has amount `>= 1.0`, is unflagged and the property record reached from
  `deposit +0x1c` has id `0xCD6EC133`, its time-to-live is set to `trunc(duration) + 5` ticks
  (`NResources::System::SetDepositTtl`). `0xCD6EC133` is the good `wood` (`Goods.lua`,
  `gp_create("cd6ec133")`) **[known]**; that the record is the deposit's product good, so that the rule
  means "a tree being felled", is **[inferred]**. The effect of the TTL on other searchers is in
  [`map-resources.md`](map-resources.md).
- When the animation ends, by working mode:
  - 0: if the deposit property has a product pattern list (`+0x5c`), set the cell pattern at the deposit position
    to entry `LogicRandom % count`; then reset the deposit amount from its property.
  - 1: unlink the deposit from the building and harvest it (`NResources::System::HarvestDepositAt`).
  - 2: if the deposit `IsAvailable()`: unlink and harvest it; otherwise as mode 0.
  - 3: if the building holds a fish reservation (`building +0x94 != -1`) validate/release it; otherwise
    `MapModifier::ConsumeResourceNear(worker cell, cfg FishingDistance, type)` with `type` = the id returned by
    S 00553070 (field `+0xbc` of a global property record). That this id is the fish resource is **[inferred]**.
  - others: nothing.

**`BringGoodHome`** (S 0077c720, S 0077c740): step 4 `BringGoodToWorkingPlace`, then `EnterBuilding` (0x0c).
`BringGoodToWorkingPlace` (S 0077f140, S 0077f270): `PickupProduct` (0x12) → `ReturnToWorkingPlace` (2) →
`PutDownPackage` (0x13), repeated while the worker still carries something.
- `PickupProduct::Start` (S 00777f80) picks the good: one ware from the building depot if it has any; else the
  building's first production good; for mode 7 with a linked animal, a good popped from the animal's stack
  (when the stack is then exhausted the animal goes to state 8). It then runs the pick-up timing of 3.7.
  **[known]**
- `ReturnToWorkingPlace` (S 0077eeb0, S 0077f020): `MoveAwayFromDeposit` (0x17; re-centre on the cell) or, if
  that cannot start, `WaitForFreeFlag` (0x10); then `MoveOnMapToWorkingPlace` (2): free-walk to the workplace's
  flag cell. While it carries a package that the flag cannot take, it stops one cell short (stop distance 1)
  and waits. When the walk ends: finished if it stands on the flag cell, else `WaitForFreeFlag` again. When
  `MoveOnMapToWorkingPlace` cannot start after `WaitForFreeFlag`, the movie sets `astarMode = 1` (3.8.3) and
  starts it once more. **[known]**
- `PutDownPackage` (S 0077a8e0): if the owner's flag is on the cell and can take the package, run `Drop` (3.7).
  After the drop, for a Worker (type 0) with nothing left to carry and working mode 1, 2, 3 or 7:
  `SacrificePlayerTableRef::GetEntryWithModifiers(workplace, 0)` (S 00661c50) returns `{good, count}` =
  entry 0 of the workplace property's goods list (`BuildingProperty::GetGoods`; filled by
  `bp_setGoods(building, good, amount)`, e.g. `(woodCutter, wood, 1)` **[inferred]**). Only when that good
  is `0x17626A03` (`corn` in `Goods.lua`) and the owner's sacrifice flag 12 (`Effect_CornDoubleProduction`,
  int at modifiers `+0x30`) is `> 0`, `count` is doubled (S 00663450). If `good != -1`, `count` is added to
  the statistics and, when the owner's flag is on the cell, `count - 1` extra packages of that good are
  created one by one in the worker's hands: each is put down at once if the flag can take it (the test is
  made up to twice), else discarded. So the number of goods delivered per harvest is the `bp_setGoods`
  amount, doubled for corn under that sacrifice. **[known]** (S 0077a8e0)

**`ReturnHome`** (S 0077bf10, S 0077bed0): `ReturnToWorkingPlace` (0x18) → `EnterBuilding` (0x0c).

**`BringGoodOut`** (mode 6 and step 1 of `ChooseNextWork`; S 0077c3b0, S 0077c510): `PickupProduct` (0x12) →
`WaitForFreeFlag` (0x10; finished once the workplace's flag can take the package) → `LeaveBuilding` (8) →
`PutDownPackage` (0x11, repeated while still carrying) → `EnterBuilding` (3). Back inside: if the depot still
holds a ware, restart from the top; else finished.

**`ProduceGood`** (S 00777460, S 00777430): `Start` calls `Production::StartProductionCycle()` and starts
animation kind 4 for `Production::GetProductionDuration()` (S 00565ed0) = `productionTime`
(`BuildingProperty +0xd8`), and for modes 6 and 10 `productionTime * effective[4]` of the owner's sacrifice
modifiers (float at modifiers `+0xc4`, `Effect_ProductionSpeed`; S 00661b60 → S 00663390, disassembly;
the product is stored as a 32-bit float, not truncated). When the animation ends:
`Production::OnProductionFinished()`; finished. **[known]**

**`GoAfforest`** (modes 0, 2; S 0077bcb0, S 0077be10): `Start` needs production enabled and, when the
building's production produces goods (`Production::ProducesGoods`), `Production::CanStartProduction()`. Step 7
`LookForEmptyPlace` (S 00779330): flood-fill around the building cell with the building's `workingRadius`
(`BuildingProperty +0x78`) for empty cells and pick candidate `LogicRandom % count`. The planted deposit type
is the building's planting deposit, or, when that deposit property has a non-empty list at
`DepositProperty +0x74`, the pick of `Afforest_PickRandomDepositForCell(cell)`; any previously linked deposit
is unlinked, the new deposit is created at the place and linked. Then, if the worker is neither at its idle
position nor on the workplace's work cell: `ReturnToLogicGrid` (0x0e); otherwise `StartProductionCycle()`
when the production produces goods, and `LeaveBuilding` (8). → `MoveToDeposit` (9; on failure the new deposit
is removed, S 0077bc50, and the movie ends) → `Working` (10) → unlink the deposit from the building;
finished. **[known]** That the property key read for the planting deposit is `bp_setPlantingDeposit` and
that list `+0x74` is the tree-type list is **[inferred]** (names of the mapped fields).

**`GoFishing`** (S 0077cda0, S 0077cea0): step 7 `LookForFishing` → `LeaveBuilding` (8) → `MoveToPosition` to the
found cell (9; failure ends the movie) → `Working` (10) → finished with step 10.
`LookForFishing::Start` (S 0077f670): from the cell in front of the building, flood-fill within the building's
`workingRadius` (`BuildingProperty +0x78`) for fishable shore cells; pick `LogicRandom % count`; reserve the fish
resource in `building +0x94/+0x98`. None found: same `!No resources found.` rule as mining; fail.

**`GoHunting`** (S 0077caa0, S 0077cba0): step 7 `LookForAnimal` (succeeds iff the workplace holds a target
animal reference, `building +0x70`) → `LeaveBuilding` (8) → `MoveToAnimal` (9) → on arrival, if the animal
reference is still valid: unless the animal's state is already 5, 7, 8 or 9 set it to 5 (killed); `Working` (10)
→ finished with step 10. An invalid reference or a failed walk ends the movie with step ≠ 10.
`MoveToAnimal` (S 00777a20, S 007785f0): free-walk to the animal's cell with stop distance 1, then fine-walk to
the animal's fine cell centre with stop distance 1, or 2 when the building's `productionTime` is non-zero.
**[known]**

**`GoDigging`** (mode 11 and the Specialist; S 0077b170, S 0077b4b0): `digsRemaining = 10`. Loop:
`SearchScholarDiggingPosition` (7; flood-fill radius 5 around the settler's target, pick `LogicRandom % count`),
reserve the cell → `LeaveBuilding` (1) if still inside → `MoveToPosition` (9) → `DigForResources` (10;
S 0077e840: animation of 80.0 ticks, kind 5 when the cell has neither `GridStates` bit `0x200` nor a resource
entry, else kind 4) → place the resource sign doodad for what the cell holds (S 0077b2f0) and, only when the
cell yields a good id other than -1, send the `!Found Resource` message (kind 2) or refresh an existing one
near the cell (refresh timer 600); release the cell, `--digsRemaining` (forced to 0 when the settler has a
workplace whose production is disabled). Ends when no digs remain or a search fails.

**`IdleOutside`** (S 0077ae80, S 0077aec0): fine-walk to idle position 0, then to idle position 1, then set the
look-at position to the workplace's flag; finished. **`ReturnFromIdle`** (S 0077d3d0, S 0077d420): clear the
look-at, fine-walk to idle position 0, then to the fine centre of the building's work cell (`building +0xf8`);
finished. **[known]**

**`CatapultAttack`** (S 0077b940, S 0077b880): `RotateCatapult` (0x1c; animation kind 4 for `(turns + 1) *
cfg CatapultRotationTimeFactor`, `turns` = minimal number of 60° steps from the current to the target direction)
→ if ammunition: `ShootCatapult` (0x1d; animation kind 5 for `productionTime`, `Catapult::Fire`) → clear target
→ rotate back (0x1e) → finished.

`Worker::GetWorkProgress` (S 0065ce80) derives a 0..1 UI value from state and step (gather step 8/9/10 → 0.1 /
0.2 / 0.5, times 0.75; bringing home adds the last quarter; production = elapsed / total). Presentation only.
**[known]**

### 3.6 Carrier

`Carrier::Update` (S 0065b710): base update; return if not active; if `notYetOnStreet` → 3.6.1; else if the
street reference is valid → 3.6.2; else `StopAndSetState3()`. **[known]**

`AssignToStreet(street)` (S 0065b150): `notYetOnStreet = 0`, store the street reference; if the carrier is
currently street-walking and busy: cancel the route, and if its cell lies on the street's cell list, cut the
remaining route at the next flag and trim the walked part behind the previous flag. **[known]**

#### 3.6.1 Unassigned carrier delivering one package (S 0065ad70)

"Holds a deliverable package" = package reference valid and package byte `+0x70` clear. **[known]**

| State | Rule |
|---|---|
| 1 | no deliverable package → `LeaveBuilding` (0x11). Else find the owner's flag near the cell; none → `StopAndSetState3()`; if the flag can take the package → `LeaveBuilding` (0x11) (else wait in state 1) |
| 0x11 | movie finished: no deliverable package → `StopAndSetState3()`; a flag is on the cell → `Drop` (0x19); else `StopAndSetState3()` |
| 0x19 | no flag on the cell → `StopAndSetState3()`; `Drop` finished: still holding a deliverable package → `Drop` again (0x19), else `StopAndSetState3()` |

#### 3.6.2 Street carrier (S 0065b200)

Terms: `pkg` = carried or chosen package (`Settler +0x30`); `pkg.next` = the package's next routing cell
(`ai::transport::TransportMovement::GetNextWaypoint(pkg +0x20)`, x = -1 when none); "next hop on my street" = `pkg.next` is in
the street's cell list (`Street +0x18`); `pkg.flag` = cell of the flag the package lies on (`pkg +0x48` reference,
`+0x28`). **[known]**

| State | Rule |
|---|---|
| 1 | start `LeaveBuilding` (0x11) |
| 0x11 | finished → `WaitForPackage` (0x16) |
| 0x16 | `WaitForPackage` finished (a package was chosen and linked): package reference invalid → `StopAndSetState3()`. Next hop not on my street → unlink the package, stay. Standing on `pkg.flag` → `Pickup` (0x18). Standing on a street cell → `MoveToStreetPosition(pkg.flag)` (0x17) and request the current route to end. Otherwise stay |
| 0x17 | arrived: if the package is linked and its byte `+0x70` is set: standing on `pkg.flag` → `Pickup` (0x18), else unlink it. Otherwise → `WaitForPackage` (0x16) |
| 0x18 | `Pickup` finished: package reference invalid → `WaitForPackage`. Next hop not on my street → `PutDownPackage` (0x19). Else `GoToPackageTarget` (0x12); if it cannot start → `WaitForPackage` |
| 0x12 | `GoToPackageTarget` finished: if the package has a destination (reference `pkg +0xd4` or `+0xf4` valid) and the carrier stands at the package's destination flag → `EnterBuilding` (0x13); else `PutDownPackage` (0x19). Not finished, but the movie waits at its target (step 0x14) and `pkg +0x104 > 360` (S 0077a0c0): look for a storehouse with the mode-0 search of 3.4 from the carrier's cell (list `+0x20`, layer 1; the `maxDist` argument 100 is unused in mode 0, so the owner's flag must be on the carrier's cell and the storehouse is the nearest by walking-net path cost); if one is found add one unit of the package's good (`pkg +0x18`) to its stock; in either case discard the package, → `WaitForPackage` |
| 0x13 | `EnterBuilding` finished → state 0x14 |
| 0x14 | if the package has a destination: `++street.traffic`; `NTransport::System::DeliverPackage(pkg)`. Then `LeaveBuilding` (0x15) |
| 0x15 | finished: still holding a deliverable package → `PutDownPackage` (0x19), else `WaitForPackage` |
| 0x19 | `PutDownPackage` finished: `++street.traffic`. Not holding a deliverable package → `WaitForPackage`. Else if `pkg.next` differs from the carrier's cell → `GoToPackageTarget` (0x12). Else street-walk one cell back onto the street: target = street cell index 1 if the carrier is not on the last street cell, else index `size - 2`; state 0x1a |
| 0x1a | movement idle → `GoToPackageTarget` (0x12) |

The second half of state 0x19 is the case "the flag was full, I picked up a package in exchange and must carry
it back". **[inferred]**

**The flag test** `Transport_CarrierTryPlacePackageOnFlag(settler, flag)` (S 0064dae0) is called by every
"can the flag take my package" test in this document (carrier state 1, `WaitForFreeFlag`,
`GoToPackageTarget`, `PutDownPackage`, `MoveOnMapToWorkingPlace`, `MoveAwayFromDeposit`). It is not a pure
test: **[known]**

1. Carrier with a valid exchange reference (`+0x1e0`, id hi `+0x1f4`): if
   `NTransport::System::CanSwapPackagesAtFlag(pkg, reserved, flag)` → true. Otherwise the reserved package
   is unlinked from the carrier and the test continues.
2. If package byte `+0x25` is set: when the package's reference `+0xd4` is valid (the `+0xf4` half of the
   test adds nothing: it also requires `+0xd4`), its next waypoint is its target flag and that waypoint is
   this flag's cell → true. Otherwise, for a Carrier, if
   `NTransport::System::FindSwapPackageAtStreetEnd(carrier, flag)` finds a package, it is linked as the
   carrier's reserved package (`+0x1e0`) → true.
3. If the flag's stacks cannot take the package (`FlagPackageStacks::CannotTakePackage`, `Flag +0x74`):
   S 006513b0 does `++pkg(+0x104)` and `pkg(+0x100) += 19 - rank`, `rank` =
   `NPlayer::GoodPriorities::GetRankOfGood` of the package's good for its owner; when the new `pkg +0x104` is
   a multiple of 180 the player message `!flag blocked` (kind 3) is sent or refreshed at the flag's cell;
   → false.
4. Flag has room. If the package already lies on / is attached to a flag (reference `pkg +0x48`, id hi `+0x5c`
   valid) → true. Else compare the ticket `pkg +0x100` with `Flag +0x164`: greater → store it in the flag,
   → false; smaller → false; equal → attach the package to the flag (`TransportLink_AttachPackageToFlag`,
   which makes later calls return true at once) → true.

So `pkg +0x104` counts the failed attempts at a full flag (the only increment found, S 006513b0; it is saved
with the package and zeroed by the street swap below), and `pkg +0x100` is a priority-weighted waiting score
by which the flag admits the longest-waiting, highest-priority package first. Since a waiting carrier calls
the test every 10th tick (below) and a worker in `WaitForFreeFlag` on its own schedule, the 360 limit is
360 attempts, not 360 ticks. **[known: live 2026-10-12]** Measured: a street carrier in state 0x12 first tries on
consecutive ticks (runs of 13 to 42 attempts) and then on every 10th tick. The consecutive run is the walking
step 0x16 of `GoToPackageTarget::Update` S 0077a2f0 **[known]**: on every tick of the walk, while the carrier's
cell is on his street and the owner's flag stands on the walk's final cell (`movement +0x38`), the flag test
`Transport_CarrierTryPlacePackageOnFlag` is called unless `ShouldKeepWalkingToFlag` holds; a failure sets stop
distance 1 and the walk goes on to the cell before the flag. The run therefore lasts as many ticks of that
walk as the flag was full, at most the whole walk; when the walk ends with the stop distance set the movie
enters step 0x14 with its `% 10` schedule;
`!flag blocked` came at the attempt that made the counter 180 (1,493 and 1,644 ticks after the first attempt);
a worker tries every tick and gets the message every 180 ticks. No street carrier reached 360 in the session;
the return of the good is read from the code (state 0x12 above; `IsFlagFullWaitExceeded` S 0077a0c0 tests
`flagFullWaitTicks > 360` in step 0x14 only, so the good goes back once the 361st failed attempt has raised
the counter above 360) **[known]**.

The 360 limit exists only in the street loop: `IsFlagFullWaitExceeded` S 0077a0c0 has one caller,
`Carrier::UpdateStreetTransport` S 0065b200. A carrier that is not yet on a street (`Carrier +0x1b8` set,
`Carrier::UpdateDropOffAfterSpawn` S 0065ad70) calls the flag test in its state 1 on every tick, with no
test of the counter: it keeps trying for as long as the flag is full and never gives the good to a storehouse
**[known]**. Such a carrier counted to 416, with a `!flag blocked` message at 180 and at 360, until the flag
took the good **[known: live 2026-10-12]**. When `Flag +0x164` is reset, the swap helpers of steps 1 and 2 and
`CannotTakePackage` are in [`streets-transport.md`](streets-transport.md) (hand-over protocol).

**`WaitForPackage`** (S 0077ac50), step 0x14: **[known]**
- If the carrier stands on its waiting cell (virtual slot 11) it only checks when
  `(tick + unique.idLo) % 20 == 0`.
- If the carrier's cell is on its street and `NTransport::System::CarrierChoosePackageOnStreet(carrier)` returns
  a package: link it to the carrier; finished.
- If displaced from the waiting cell: stop; if exactly on a cell centre start `MoveToWorkingPlace` back to the
  waiting cell (step 0x15, back to 0x14 on arrival); if that cannot start, or the carrier is not centred, the
  movie reports finished (with no package, which sends the carrier home through the state-0x16 rule).

The waiting cell of a street carrier (Carrier virtual slot 11, S 0065ab00) is the cell stored at `Street +0x28`
of its street, the same field (`midX`/`midY`) on which `Street::SpawnCarrier` creates the carrier. **[known]**
How the street computes it is in [`streets-transport.md`](streets-transport.md).

**`GoToPackageTarget`** (S 0077a260, S 0077a2f0): `Start` needs a valid package; target = `pkg.next`; fails if
that cell is not on the carrier's street; street-walk to it (step 0x16); then, if a street path is active and
the carrier's cell is on its street, `ai::settlers::SettlerMovement::CancelRoute` (3.8.5). **[known]**
- Step 0x16, on arrival: if a stop distance was set, clear it and go to step 0x14; else finished. While walking
  on its own street it looks up the owner's flag on the rough mover's final target (`movement +0x38`): no flag,
  or the flag can take the package → clear a set stop distance; the flag cannot take it → set stop distance 1,
  so the carrier halts on the cell before a full flag. Neither happens while
  `NTransport::System::ShouldKeepWalkingToFlag(carrier, flag)` is true (rule in
  [`streets-transport.md`](streets-transport.md)). **[known]**
- Step 0x14 (waiting next to a full flag): when `(tick + unique.idLo) % 10 == 0` **[known]**, retry: target =
  `pkg.next` if that cell is on the carrier's street, else the carrier's own cell; if the owner's flag on the
  target can now take the package (`Transport_CarrierTryPlacePackageOnFlag`): finished when the carrier stands
  on the target, else `Start` again (walk on). **[known]**
- If the flag still cannot take it and `(tick + unique.idLo) % 200 == 0` **[known]**, try a *street swap*:
  **[known]**
  1. The package must have a transport target: S 005b7b40 on `pkg +0xb8` is true unless both references of
     that record (id hi at `+0x1c` and `+0x3c`, i.e. `pkg +0xd4` and `pkg +0xf4`, the destination pair used
     above) are invalid. And `TransportMovement::ComputeNextHop(pkg, target)` must give a hop beyond the full
     flag that differs from the target.
  2. `other` = the street linking the full flag to the flag on that hop. It must not be the carrier's own
     street, and both streets must agree on `streetType == 2`.
  3. `partner` = the carrier in the same slot of `other` (second slot if this carrier is its street's second
     carrier, else first slot); it must exist and either be free (`Transport_IsCarrierFreeForStreetSwap`,
     S 0077a0f0: carries no package, is in state 0x16, its movement is not busy, and no flag of its owner is
     on its cell) or pass `CanSwapWithLoadedPartner` (S 0077a150):
     partner carries a package, is in state 0x12 with its
     `GoToPackageTarget` at step 0x14, its package has a destination (`+0xd4` or `+0xf4` valid), the hop after
     its package's next waypoint is a flag at one end of this carrier's street, and that next waypoint is the
     cell of the street's other end flag.
  4. Swap: this package's route is advanced to the hop (S 0064ef60 on the package's movement record
     `pkg +0x20`: store the hop cell at record `+0x48/+0x4c`, byte `+5` = "x is not -1", and set the pairs at
     record `+0x58`, `+0x60` and `+0x70` to -1); the two carriers exchange *streets* (each
     is unlinked from its slot and linked into the same slot of the other street); each carrier's reserved
     package is unlinked; `pkg +0x100` and `+0x104` are set to 0; a loaded partner's package is advanced and
     reset the same way and the partner's `GoToPackageTarget` is restarted; then this movie is restarted. Each
     carrier keeps the package it holds.

  Effect (S 0077a2f0, S 0077a260): the restarted `GoToPackageTarget` targets the advanced waypoint, the far
  end of `other`, which is now the carrier's street, and walks there with `StartStreetMoveTo` (3.8.5), whose
  route planner passes flag cells without asking for room. The package thus crosses the full flag without
  being put on it, and the free partner takes over the carrier's old street from its `WaitForPackage`.
  **[known]** for the steps, **[inferred]** for the crossing (the planner was not re-read for this case). The
  swap needs no rare state: an idle carrier on the next street of the package's route is enough.

Package choice, flag capacity (`cfg FlagPackageLimit`) and routing belong to `NTransport` / `NNet`.

### 3.7 Pick-up and put-down timing

`Pickup` (S 007781e0, S 00777e00) and `Drop` (S 00777d10, S 00777d50) are two-phase: **[known]**

| Movie | Phase 0 | At the end of phase 0 | Phase 1 |
|---|---|---|---|
| `Pickup` | animation kind 2 for `gameConfig +0x10` | if no package is linked and a good id is set: create a package of that good in the settler's hands; if a package is linked: take it from the flag on the cell | kind 3 for `gameConfig +0x0c`; finished at its end |
| `Drop` | `CarrierBeginDropAtFlag`, kind 2 for `gameConfig +0x10` | `PutDownCarriedPackage` (package goes onto the flag) | kind 3 for `gameConfig +0x0c`; finished at its end |

`gameConfig +0x0c` is written by `cfg_setPickupTime`, `+0x10` by `cfg_setDropTime`; both are 3.3 in the shipped
data, i.e. 4 ticks per phase. **[known]** Note that both movies use the *drop* time for phase 0 and the *pickup*
time for phase 1.

### 3.8 Movement

#### 3.8.1 Interpolator and speed

`Interpolator` (S 00774ae0): `progress` (-1.0 = not moving), `carryOver`, `stepRate`. **[known]**

- `Reset`: `progress = -1.0`, `carryOver = 0`.
- Starting a step (`BeginStep`): `progress = carryOver` (`SyncValue`, S 00774a00); `stepRate` is set from the
  speed (below).
- `Advance` (per tick, S 00774a10, disassembly): `progress = (float32)(stepRate + progress)`; if
  `progress >= 1.0` (the jump is taken only for `1.0 > progress` or unordered) then
  `carryOver = (float32)(progress - 1.0)`. `carryOver` is not cleared when a step does not complete.
- A step is complete when `progress > 1.0` (strictly) after `Advance`.
- "Moving" tests are `progress >= 0`.

Because the overshoot is carried into the next step, the average speed is exact over a path; the per-step tick
count varies between `floor` and `ceil` of `1/stepRate`. **[inferred]**

Step rate for one cell step (`Rough::BeginStep`, S 00773a40): **[known]**

```
stepRate = 1.0 / ( hexDistance(from, to) / (slopeFactor * baseSpeed) )
```

and for one fine step (`Fine::BeginStep`, S 00773ec0) the same with `baseSpeed * 4.0`. Consecutive path cells are
neighbours, so `hexDistance` is 1. **[inferred]**

- `baseSpeed` = `gameConfig +0x00` (`cfg_setSettlerSpeed`, 0.058 in the data, ctor default 0.1) times a
  per-player factor: `effective[1]` for Carriers, `effective[8]` for Soldiers, 1.0 for all other types
  (`ai::logic::SacrificeModifiers::GetScaledValueForUnitKind`, S 00663310; player slot = owner index). **[known]**
- `slopeFactor` (S 0052d9e0): by slope class of the height difference `from → to`: class 1 → 0.8, class 2 → 0.6,
  class 3 or 4 → 0.4, anything else (flat, downhill) → 1.0. For cell steps it is 1.0 whenever either cell has the
  water bit (`GridStates & 0x4`) (S 0052e250); fine steps always use the slope class (S 0052dd10). **[known]**
- Slope class (`NMap::Elevations::GetSlopeClassBetween` S 00676200 → S 00675d30): `d = height(to) -
  height(from)`, heights taken from the vertex grid at the cell's vertex `(x*4 + (y odd ? 2 : 0), y*4)`;
  `d > 2400` → 4, `> 1200` → 3, `> 600` → 2, `> 200` → 1, `d < -2400` → -4, `< -1200` → -3, `< -600` → -2,
  `< -200` → -1, else 0. **[known]** The height unit (0.001 world units per step, per `graphics.xml`) is in
  [`map-resources.md`](map-resources.md).

With 0.058 a settler needs 17 or 18 ticks per cell on flat ground (1 / 0.058 = 17.2, the overshoot is carried
into the next cell): the first cell of a walk takes 18 advances, later cells mostly 17. At slope factor 0.8
(step rate 0.0464) a cell takes 21 or 22 ticks, at 0.6 (0.0348) 28 or 29. One `Settler::Update` per settler
per logic tick, 10 ticks per second at speed 1, so about 1.7 s per flat cell. **[known: live 2026-10-12,
eight carriers over 1,347 ticks: 59 flat cells of 17 ticks and 2 of 18 after the first; 11 of 21 and 1 of 22;
5 of 28 and 2 of 29]**

#### 3.8.2 Composite update (`Movement_Update`, S 007730e0)

Nothing while `progress < 0`. **[known]**

- Cell mode (`+0xd4 == 0`): `Rough::UpdateStep(holdStep)`; then `cell = rough.currentCell` and
  `finePos = centre(cell)`. If not holding, `stopDistance != 0` and the active path is running and its remaining
  distance `< stopDistance`: stop the rough move.
- Fine mode: `Fine::UpdateStep(holdStep)`; `finePos = fine.current`, `cell` derived from it; stop when the fine
  path's remaining index `< stopDistance`.

The logic cell and fine position therefore change only when a step *completes*; in between only `progress`
changes (the renderer interpolates). **[known]**

`Rough::UpdateStep` (S 00773cd0): advance; if `progress <= 1.0` return. Commit `currentCell = requestedCell`. If
the path can continue (street: `StreetPath::CanAdvance`; free: path valid and index ≠ 0) and not holding: pop the
next cell, `BeginStep`. Otherwise reset interpolator and path (movement ends). `Fine::UpdateStep` (S 007740f0) is
the same on the fine path. **[known]**

Remaining distance (S 00774850 for street paths): cells left on the planned leg when the leg ends at the final
target, otherwise `hexDistance(current leg cell, target) + 10`. **[known]**

#### 3.8.3 Free paths (`MoveToCell`, S 00658000)

Stop any running move. Already on the cell → true. If the `bool` argument is true set `astarMode = 1` (a false
argument does not write the byte). The byte is cleared by the free path's reset (`PathBase::Reset` S 00772d30 →
`FreePath` virtual slot 7, S 007750f0), which runs when a free walk ends or is stopped (`Rough::UpdateStep`,
`Abort`) and when `Rough::StartMoveTo` finds no path; so a `true` lasts for one walk. Path mode 1;
`Rough::StartMoveTo(cell)` → `FreePath::FindPath` (S 00775170): **[known]**

- Target outside the map → fail.
- Special case: a building is looked up on the start cell, else on the target cell (object layer 1), and a
  flag likewise (layer 0); if both exist and the building's flag reference (`building +0xb0/+0xb4`) names that
  flag (`Flag +0x38/+0x3c`) → path = the single step from start to target (no search).
- Otherwise `NMap::AStar::FindPath(from, to, astarMode)`; on success the path is built with
  `NMap::AStar::BuildPathReversed(.., randomize = true)`, stored reversed (target first) and consumed from the
  back. The randomised build draws from the simulation RNG (section 8).

`astarMode` is the `ignoreBlocking` argument of `NMap::AStar::GetStepCost` (S 00676840): when set, the test
"the entered cell must be walkable unless it is the search's start cell" is skipped, so the path may cross
blocked cells; slope and deposit costs are unchanged (cost table in [`map-resources.md`](map-resources.md)).
**[known]** Callers that pass true: `LeaveBuilding` (`Start`, `Update`), `EnterBuilding` (`Start`, `Update`),
the walk back to the flag cell when leaving a flag queue (3.8.6, state 5) and the second walk of
`MoveOnMapToWorkingPlace::Start` (S 00780090, tried when the first, with false, cannot start). Callers that
pass false: `MoveToDeposit`, `MoveToPosition`, `MoveToAnimal`, `MoveToHome`, `ReturnToWorkingPosition`.
Two movies write the byte directly before starting a walk that passes false: `ReturnToWorkingPlace::Update`
(S 0077f020) and `WaitForShip::Update` step 0x0e (S 00777240). **[known]**

`Map_IsCellWalkable` (S 0052df20): a cell is walkable when none of the `GridStates` bits blocked `0x1`, water
`0x4`, cliff `0x40`, building footprint `0x100`, logic object `0x400` is set. **[known]**

#### 3.8.4 Fine paths (`MoveToFinePos`, S 006574d0)

Reset the action animation, stop any move; if not already at the target: build a straight fine path
(`FinePath::SetTarget`, S 00774f10): starting at the target, repeatedly step one fine unit in
`MapPos::GetHexDirectionTo(pos, from)` until `from` is reached; the list is consumed from the source end. No
obstacle test. Fails only when the target is outside the fine grid. **[known]**

#### 3.8.5 Street routes (`StartStreetMoveTo`, S 00657f50)

Stop any move, path mode 2, `routeTarget = cell`, then `ai::settlers::SettlerMovement::AdvanceStreetRoute` (S 00657b80), which
is also called every time a leg ends. `StartStreetMoveTo` returns its result, except that a settler already
standing on `cell` always gets true (when the route call returned false, `routeTarget` is first reset to `-1`
and the path mode to 0). `AdvanceStreetRoute`: **[known]**

1. If the settler is on `routeTarget`, or `routeEndRequested`: if it is on `routeTarget`, the owner's virtual
   slot 1 agrees and a flag is on the cell → queue at that flag (link into the flag's waiter list) and return
   true. Else return false (route over).
2. Else, unless `streetStopDistance != 0` and `hexDistance(cell, routeTarget) == streetStopDistance`:
   - `ai::settlers::SettlerMovement::PlanStreetRoute` (S 00657360) → `nextFlag`, `nextWaypoint` (below).
   - If a flag is on the current cell and has a valid reference at `Flag +0x17c`, and `nextFlag` is set, and the
     flag at `nextFlag` passes the same test, and the shortest link between the two flags is a street with a
     valid reference at `Street +0xe8`: queue at the current flag; return true. `Flag +0x17c` is the id-hi
     dword of the flag's harbour reference (`Flag +0x168`) and `Street +0xe8` is the street's ship-route
     reference, used only by sea streets (street type 3); both fields are defined in
     [`streets-transport.md`](streets-transport.md). So this is the "wait for a ship" case: the settler
     stands on a harbour flag, the next flag of its route is a harbour flag, and the shortest link between
     the two is a sea street with a ship route. **[known]** for the tests, **[inferred]** for the reading.
     Together with rule 1 (which needs a valid ship reference) these are the only two ways into a flag
     queue from this function.
   - If `nextWaypoint` is set: `StartRoughMove(nextWaypoint)` and return its result.
3. Return false.

`StreetRoutePlan::Plan(player, from, to, excludeStreet)` (S 007735b0): **[known]**

- Each end resolves to the owner's flag on that cell, or else to the street occupying the cell (object layer 2)
  if both of that street's end flags are valid, represented by the street's first flag. If either end resolves to
  nothing → fail.
- Same flag at both ends (`PlanSameFlag`, S 00773520): both on the same street → kind 0, next = `to`; only the
  start on a street → kind 1, next = that flag's cell; only the end on a street → kind 2, next = `to`; both
  directly on the flag → fail.
- Otherwise run `nnet::StreetPathFinder::Search(startFlag, endFlag, 1, 0, preferredStreetId)` (the settler's
  current street id, or none); no path → fail. Collect the flag cells of the path; drop a redundant first/last
  flag when an end lies on a street between two path flags; a path collapsing to one flag → same-flag case.
  Result: kind 1 (start on a street; next = the last collected flag) or kind 3 (start on a flag; next = the
  second flag of the path).

`PlanStreetRoute` plans from the flag the settler waits at, or else from its cell. Kinds 1 and 3 set
`nextFlag = nextWaypoint = next`; kinds 0 and 2 set `nextFlag = -1`, `nextWaypoint = next`; failure sets both to
-1. **[known]** So a street walk is replanned at every flag, one leg at a time.

The cells of a leg come from `StreetPath::ComputeRoute` (S 007741e0): kind 0 → sub-path along the shared street;
kind 1 → from the cell along the start street to the planned flag; kind 2 → along the end street from its flag to
the cell; kind 3 → the street from the start flag toward the next flag, preferring the settler's current street
when it connects the two flags, else the shortest link (`NNet::Flag::FindShortestLinkToFlag`). **[known]**

`StreetPath::CanAdvance` (S 007747b0): the route is valid, not finished, and the next cell still has the street
bit (`GridStates & 0x2`); with `noReplanAtFlags` set, additionally no flag of the owner on that cell. A street
that is torn up under a walker therefore stops it at the last intact cell. **[known]**

`ai::settlers::SettlerMovement::CancelRoute` (S 006583d0): when neither queued nor aboard, set `routeEndRequested` and the
rough "stop after this step" byte (`movement +0xc1`); while queued or aboard, `ai::settlers::SettlerMovement::Abort`. `Abort`
(S 00658070) stops the mover; if queued, leaves the flag queue and, with a valid ship reference, the ship's
cargo list; clears a set stop distance, `streetMode`, `routeEndRequested` and `renderDirty`. **[known]**

Stop distance: `SetStopDistance(n)` (S 00657640) writes `streetStopDistance` in street mode (and the base
`stopDistance` as well when the next flag is the route target), else the base `stopDistance`. `ClearStopDistance`
(S 00657680) zeroes the same fields. **[known]**

#### 3.8.6 Per-tick settler movement and queueing at a flag (`ai::settlers::SettlerMovement::Update`, S 00658140)

Not queued (`waitFlag` invalid) and not aboard, while moving: **[known]**

1. `Movement_Update`; when it reports a new step with a changed path, notify the renderer.
2. If the mover has stopped: in street mode call `AdvanceStreetRoute`; if that started something and the next
   flag is the route target and a stop distance is set, copy `streetStopDistance` to the base `stopDistance`.
   Otherwise clear `routeEndRequested`.

Queued at a flag (`waitFlag` valid): finish a running move first, then by `flagWaitState`: **[known]**

| State | Rule |
|---|---|
| 2 | `++flagWaitTicks`; if the flag has more than 1 waiter and `flagWaitTicks > 10`: start the `WaitForShip` movie, state 3 |
| 3 | unless the settler has a ship and the flag is that ship's docking flag: when `(unique.idLo + tick) % 23 == 0`, replan; if there is no next flag any more or it changed: start `ReturnToLogicGrid`, state 5. Else if `WaitForShip.Update()` finished: state 7 |
| 5 | state 6; free-walk to the flag's cell |
| 6 | state 0; `Abort()` |

`BeginWaitAtFlag(flag)` (S 006571e0), called from the flag when the settler is linked into its waiter list: set
`waitFlag`, take a free parking spot from the flag's parking table (`Flag +0x19c`,
`nnet::FlagParking::FindFreeSpot`; its search draws one simulation random number per call,
`FreeSpotSearch::Init` S 00671730, and mixes in `tick & 7`), `flagWaitState = 2`,
`flagWaitTicks = 0`; in street mode (path mode 2) remember `streetMode = 1` and stop the rough move; with path
mode 0 and no fine move active `streetMode = 0`; with path mode 1 `streetMode` is left unchanged. **[known]**

`WaitForShip` (S 00777240): walk to the parking cell with stop distance 1 (0x16), fine-walk to the parking spot
(0x19), wait (0x14) until the parking cell is released, `ReturnToLogicGrid` (0x0e), free-walk to the flag cell
(0x18; `astarMode` is set to 1 for this walk), finished. A parking cell of `-1` at the start (step 0x0f)
finishes the movie at once. **[known]** The movie name says "ship"; the queue is entered through rule 2 of
3.8.5.

Aboard a ship: `EnterShip` (S 00657cd0) stops everything and sets `flagWaitState = 4`; while 4 with a valid ship
the settler counts as busy and is not moved by this code. `DisembarkAt(ship)` (S 00657d90) clears `streetMode`
and `flagWaitState`. If the ship movement's harbour reference (`+0x60`) is valid it puts the settler on the
cell the owner's virtual slot 0 returns and, if `streetMode` had been 1, restarts the street route (path
mode 2, `AdvanceStreetRoute`). With no harbour it puts the settler on the first walkable in-map neighbour of
the ship's cell (the neighbour in direction 4, then stepping in directions 0, 1, 2, 3, 4); if none of the six
is walkable the position is not changed; the street route is not restarted in this branch. **[known]**

`ai::settlers::SettlerMovement::IsBusy` (S 00657570) = queued at a flag, or aboard, or `progress >= 0`. **[known]**

### 3.9 Constructor

`Constructor::Update` (S 0065ea20): base update; return if not active (2.4); if the site reference (`+0x188`,
id hi `< 0x80000000`) is valid: a site whose building
size class (`BuildingProperty +0x3c`) is 0x10 (`SizeShip = 16` in `config.lua`) uses the ship routine, others the
building routine. With no site: unlink from a ship if linked, `StopAndSetState3()`. **[known]**

Building routine (S 0065e1d0): **[known]**

| State | Rule |
|---|---|
| 1 | start `GoToConstructionPlace` (4); failure → `StopAndSetState3()` |
| 4 | finished: on the site's flag cell → `ConstructBuilding` (0x1b); else `StopAndSetState3()` |
| 0x1b | finished → unlink from the site, `StopAndSetState3()` |

Ship routine (S 0065e770): same walk; then link to the shipyard's existing ship, or find a ship placement
(`NNavy::System::FindShipPlacement`) and create the ship; no placement → message `!No Place for Ship found!`
(kind 6) and the shipyard is removed. `ConstructShip` (0x1c) finished → unlink; if the ship's two remaining-work
values are `<= 0` the shipyard is removed; `StopAndSetState3()`. **[known]**

`ConstructBuilding` (S 0077daf0) loops (decision step 7): finished at once when the construction byte `+0x78`
is set; while frame work remains (`site +0x74 > 0`) `Construct` (10) when the site stock holds the first good
of the `frameCost` list, afterwards `Construct` when the site-stock field `construction +0x20` is non-zero
(expected: the stock is not empty, **[inferred]**); else `BeNervous` (0x0d; S 00778250: fine-walk 3 fine steps
in direction 5 from the cell centre, then back to the centre of the site's flag cell). After `BeNervous` it
decides again; after `Construct`, if both remaining-work floats are `<= 0` it sends the player message
`!Building constructed` (kind 7, at the building cell) and is finished, else it decides again. `Construct`
(S 0077fe70, S 0077fb50) consumes one good, walks through the 4 construction positions of the building property
(`bp_setConstructionPosition`) and hammers at each. **[known]** for the following (S 0077fe70, S 0077fb50):

- `Start`: `workPerStroke = (1 / goodsTotal) / (constructTime * 4)`, where `goodsTotal` is the total count of
  the property's good list `+0x68` when `1 - site(+0x74) >= 1`, else of list `+0x58`. In the first case it
  removes one unit of the first good of list `+0x68` that the site stock holds (none held: nothing removed);
  in the second it removes one unit of the first good of list `+0x58`. List `+0x58` is `frameCost`
  (`bp_addFrameCost`, first phase, remaining fraction at site `+0x74`), list `+0x68` is `cost` (`bp_addCost`,
  second phase, site `+0x70`); see [`village-buildings.md`](village-buildings.md).
- `Update` does nothing while the settler moves. With `strokesLeft < 1` and the action timer run out, phase
  `p` = 0..3: reset the timer, fine-walk to (fine centre of the cell one step in direction 1 from the site
  cell) + truncated construction position `p`, set `strokesLeft = trunc(constructTime)` (30 with the shipped
  data), `phase = p + 1`.
- With `strokesLeft > 0`, **every tick**: if the timer has run out start animation kind 4 for `constructTime`;
  `--strokesLeft`; `Construction::AdvanceWork(workPerStroke)`; if both remaining-work floats (`+0x70`, `+0x74`)
  are `<= 0` set `strokesLeft = 0`. A "stroke" is thus one tick, 4 × 30 of them per good.
- Phase 4: one more `AdvanceWork(workPerStroke)`; if no remaining work is positive: `Construction::Complete`
  and clear the site stock. Finished.

`ShipConstruct` (the hammering sub-movie of `ConstructShip`; `Start` S 0077fa30, `Update` S 0077f9c0):
`strokesLeft = trunc(shipConfig constructTime)`; `workPerStroke = 1 / (n * constructTime)` with `n` = total
count of the shipyard property's `frameCost` list while the ship's construction record (`ship +0x20`) has
`+0x4c > 0`, else of its `cost` list. `Update`, every tick: while `strokesLeft > 0`, restart animation kind 4
for `constructTime` when the timer has run out, `--strokesLeft`, `NNavy::Construction::AddWork(workPerStroke)`;
at `strokesLeft == 0` one more `AddWork` and finished. One visit therefore adds `(strokes + 1) * workPerStroke`.
**[known]** The rest of the ship-building visit (fetching the good, walking to the hull) and the ship
construction record are in [`navy.md`](navy.md).

### 3.10 Specialist and NPC

`Specialist::Update` (S 0065eec0): base update; return if not active; target flag reference invalid →
`StopAndSetState3()`. Then by state: **[known]**

| State | Rule |
|---|---|
| 1 | start `MoveToWorkingPlace` (8); failure → `StopAndSetState3()` |
| 8 | finished: settler's cell equals the target flag's cell → start `GoDigging` (10), failure → `StopAndSetState3()`; other cell → `StopAndSetState3()` |
| 10 | `GoDigging` finished → start `ReturnToWorkingPosition` (11; free-walk back to the flag, S 007781b0), failure → `StopAndSetState3()` |
| 11 | finished → `StopAndSetState3()` |

`NPC::Update` (S 0065ddf0): base update; return if not active. **[known]**

| State | Rule |
|---|---|
| 1 | `state = 0x29` |
| 0x29 | cell target set (`x != -1`): stop the movement; if centred on a cell start `MoveToPosition(target)` (0x12), else start `ReturnToLogicGrid` (0x2f); if the start fails clear the cell target and stay in 0x29. No cell target: if the fine target is inside the map start `MoveToFinePosition(target)` (0x1a); if that fails clear the fine target and stay in 0x29 |
| 0x1a | `MoveToFinePosition` finished → clear the fine target, `state = 0x29` |
| 0x2f | `ReturnToLogicGrid` finished → `state = 0x29`; then, in the same call, the state-0x12 rule runs (the case falls through) |
| 0x12 | `MoveToPosition.Update()` finished → clear the cell target, `state = 0x29` |

A cell target has priority over a fine target. The fall-through in state 0x2f calls `MoveToPosition.Update()`
on a movie that was not started for this walk. `MoveToPosition::Update` and `ReturnToLogicGrid::Update` are
the same function (S 00777c50, read from both vftables): "movement not busy". So in the tick in which the
re-centring ends, the state-0x12 rule reports finished too and clears the cell target: an NPC that was not
centred on a cell when the target was set re-centres and then stays, without walking to the target.
**[known]**

---

## 4. Update order

One logic tick (`NLogic::System::Update`, S 00527070) runs, in this order: net tick with the execution of
queued game commands (see [`logic-core.md`](logic-core.md)), street planners, player table,
`NVillage`, `NNet`, **`NSettlers`**, `NTransport`, `NResources`, `NDoodads`, `NMilitary`, `NNavy`, statistics,
`NAI`, sacrifice system, spawn system, chests, victory conditions. **[known]** The tick interval is
`gameConfig +0x04` seconds (ctor default 0.1; `cfg_setGameSpeed` exists but the shipped `config.lua` does not
call it). **[known]** The frame time fed into the tick accumulator is multiplied by a user-profile factor
(`UserProfile +0x24`) and the system's `speedFactor`, so 10 ticks per second holds when both are 1.0.
**[inferred]** A scaled frame time above 5.0 seconds is replaced by one tick interval; ticks run only while the
`NComm` manager is in state 4 and `NComm_Manager::CanAdvanceTick` allows the next one; the statistics step is
skipped while the statistics object is not initialised. **[known]** The tick body is skipped (but the tick
time still advances) while the edit object reports batch editing. **[known]**

`NSettlers::System::Update` (S 00654ce0) processes the lists in the order **Soldier, Constructor, Worker,
Specialist, Carrier, NPC**, each list front to back (3.3). **[known]**

Per settler and tick: `Animation::Tick` → `ai::settlers::SettlerMovement::Update` → base state handling → class state machine,
which calls the `Update` of the one active top-level movie, which may start the next sub-movie in the same tick.
A movie started in a tick is first updated in the next tick. **[inferred]** (every `Update` read here returns
right after starting a sub-movie; not checked for all movies).

Other per-tick callers that touch settler state: `NVillage::SettlerSpawn::Update` (cooldown, healing of stored
soldiers: counter `+= 2` per tick; when it exceeds the int at `militaryConfig +0x110` every stored hit-point
value is raised by 1, a value that reaches the good's `+0x88` health is dropped from the list, and the counter
restarts at 0) runs in the `NVillage` step, before the settlers. **[known]** (S 00564780, virtual slot 1 of
the spawn object, called by `NVillage::Building::Update` S 0055e2f0).

Per frame only (no simulation effect): `S2CG::Character*` rendering, `Worker::IsAwayFromWorkplace`,
`ShouldSpeedUpWorkAnim`, `GetWorkAnimSpeedFactor` (work animation speed = `productionTime /
GetProductionDuration()` when the scaled production is shorter), `GetWorkProgress`,
`System::PickRandomCinematicTarget` (uses the C `rand()`, weights Worker 10, Constructor 3, Carrier 1,
Specialist 3, Soldier 10). **[known]**

---

## 5. Inputs and outputs

No player command addresses a settler directly; settlers react to state changes of buildings, streets, flags and
orders. **[inferred]** (no command handler calls into `NSettlers` except through the systems below).

Inputs:

- Creation: see the table in 3.1.
- Linking: `VillageLink_LinkWorker`, `VillageLink_LinkBuilder`, `StreetLink_LinkCarrierSlot78` / second-slot
  link (→ `Carrier::AssignToStreet`), flag link for the specialist, soldier links.
- Home reference (`Settler +0xd8`, used by `MoveToHome`, 3.4): set by `Settler_LinkDestinationReference`
  (S 0053bf50), which also adds the settler to the building's settler list (`(building +0x108) +4`); its only
  caller is `VillageOrder_LinkSettlerToDestination` for order category 3 (3.1), so the settlers with a valid
  home reference are those ordered into a storehouse or barracks. **[known]** No other writer of the reference
  besides `Load` was found. **[inferred]**
- Unlinking: clearing a workplace / street / site reference makes the next `Update` call `StopAndSetState3()`.
- `NVillage::Workers::ReleaseAllWorkers`, `NVillage::Soldiers::ReleaseAll`, `NavyCargo::ReleaseAll` and
  `NNet::Street::dtor` call `System::RemoveSettler` (immediate delete). `System::RemoveSettlersOfPlayer` is used
  when a player's assets are transferred. **[known]** (callers of S 00654c20, S 00654bd0).
- Flags: `BeginWaitAtFlag` / `DetachFromFlag`. Ships: `EnterShip` / `DisembarkAt`.
- Mission scripts: `se_createSettler`, `se_isSettlerOnPosition(player, good, x, y)` (S 005ae570: no result
  for a player index `> 7` or a cell outside the map; else takes the first settler standing on the cell,
  lists searched in type order 0..5 and front to back (`FindNearestSettlerWithinRadius` S 00654720 with
  radius 0), and returns true only if that one settler belongs to the player and has the given profession
  id) **[known]**, the NPC calls (2.8).

Outputs:

- To `NVillage`: `Production::StartProductionCycle`, `OnProductionFinished`, `CanStartProduction`, `IsEnabled`;
  `Depot::HasAnyWare` / `TakeOneWare`; `SettlerSpawn::SpawnSettlerOfGood`, `OnSettlerEntered`; `Catapult::*`;
  construction progress; `RemoveBuilding` (shipyard).
- To `NTransport`: create / take / put down / deliver / discard packages; `CarrierChoosePackageOnStreet`.
- To `NResources`: harvest and create deposits, deposit TTL, kill and consume animals, spawn animals, consume
  fish.
- To `NDoodads`: skeleton doodad, resource signs.
- To `NLogic::Statistics`: `RegisterProductionEvent(workplace)`, `AddGoodAmount`.
- Player messages: `!No resources found.` (3), `!Found Resource` (2), `!Ship constructed` and `!No Place for Ship
  found!` (6), `!Building constructed` (7).
- To the renderer through `NLogic::CallbackManager`: settler created (slot `+0x20`), destroyed (`+0x24`),
  movement changed (`+0x5c`). Presentation only. **[known]**

---

## 6. Data-driven parameters

Global config (`game/scripts/properties/config.lua` → `GameConfig`, ctor S 00555780): **[known]**

| Lua call | Offset | Type | Data value | Ctor default | Used by |
|---|---|---|---|---|---|
| `properties.cfg_setSettlerSpeed` | `+0x00` | float | 0.058 | 0.1 | base speed, cells per tick |
| `properties.cfg_setGameSpeed` | `+0x04` | float | not set | 0.1 | seconds per logic tick |
| `properties.cfg_setPickupTime` | `+0x0c` | float | 3.3 | 10 | phase 1 of pick-up and drop |
| `properties.cfg_setDropTime` | `+0x10` | float | 3.3 | 10 | phase 0 of pick-up and drop |
| `properties.cfg_setConstructTime` | `+0x18` | float | 30 | 10 | hammer stroke duration of `Construct` (`ShipConstruct` reads the ship config's own construct time instead, 3.9) |
| `properties.cfg_setFishingDistance` | `+0x1c` | int | 1 | 3 | fish radius: around a shore cell when fishing spots are collected (`LookForFishing`), and around the worker when a fish is consumed (`Working`, mode 3) |
| `properties.cfg_setCatapultRotationTimeFactor` | `+0x24` | float | 5 | 10 | `RotateCatapult` duration = `(turn steps + 1) *` this value, in ticks (S 0077e980) |
| `properties.cfg_setSettlerDyingTime` | `+0x2c` | float | 28 | 50 | death animation length |
| (no setter found) | `+0x30` | int | — | 30 | home search radius |
| `properties.cfg_setSettlerSkeletonDoodad` | `+0x34` | id | `doodad_deadsettler` | -1 | remains doodad |
| `properties.cfg_setBowFlightTimeFactor` | `+0x38` | float | 2 | 1.0 | arrow flight ticks per cell of hex distance, product rounded to int (S 0065f270) |
| (no setter found) | `+0x58` | uint | — | 600 | ticks without work before idling outside |

Profession records (`Jobs.lua` → `GoodProperty`): `gp_create(id)`, `gp_setName`, `gp_setType(.., Settler)`,
`gp_setSettlerType` (`+0x7c`), `gp_addCost(good, tool, 1)`, `gp_setGfxGoodId` (carried tool model **[inferred]**),
and for soldiers `gp_setSoldierType` (`+0x80`), `gp_setHealth` (`+0x88`), `gp_setProjectileType` (`+0xb8`),
`gp_setArmor`, `gp_setHitDamage`, `gp_setAttackTime`, `gp_setAttackWaitTime`, `gp_setBlockingChance`,
`gp_setBowRange`, `gp_addHitTime`. **[known]** Tribe record: `tp_setWorkerToolGoodId` (`TribeProperty +0xbc`).
**[known]**

Building records (`buildings.lua` → `BuildingProperty`) read by settler code: **[known]**

| Lua call | Offset | Example | Used for |
|---|---|---|---|
| `bp_setWorkingMode` | `+0x80` | `BuildingWorkingMode_Mining` | job selection |
| `bp_setWorker` | `+0x90` | `good_woodcutterScots` | profession spawned for the building |
| `bp_setWorkerLimit` | `+0x7c` | | number of workers |
| `bp_setWorkingRadius` | `+0x78` | 6 | search radius (Lua float truncated to int): fishing spots (`LookForFishing`), planting places (`LookForEmptyPlace`), the building's deposit and hunt-target searches (S 0055bfb0, S 0055c050) |
| `bp_setProductionTime` | `+0xd8` | 55 | `Working` / `ProduceGood` duration in ticks |
| `bp_setRestTime` | `+0xe0` | 222 | base of the `Rest` duration |
| `bp_setProducedSettler` | `+0xec` | | settler / animal released by modes 4 and 10 |
| `bp_setIdlePosition(b, tribe, i, x, y)` | map at `+0xc0` | `(woodCutter, scots, 0, -1.0, 2.0)` | idle spots 0 and 1 |
| `bp_setConstructionPosition(b, tribe, i, x, y)` | map at `+0xb4` | 4 entries per tribe | builder positions |
| `bp_setPlantingDeposit` | `+0xd4` | `tree_10` (forester), `field_01` (farm) | what a forester or farmer plants |
| `bp_setDoorOffsetDirection(b, tribe, dir)` | map at `+0x9c` | `(farm, scots, DoorOffsetNorthWest)` | extra step when entering |
| `bp_setSpawn`, `bp_setCasern`, `bp_setDepot`, `bp_setTerritoryBuilding` | `+0x40`, `+0xf1`, `+0x54`, `+0xf5` | | which settlers may go home there |

Per-player modifiers (`sacrifices*.lua`, `NSacrifice::System` at `GameSystem +0x60`; per player a
`SacrificeModifiers` block with int flags at `+0x00` and the float array `effective` at `+0xb4`, both indexed
by the effect id of `sacrifices.lua`) read by settler code: **[known]**

| Effect id | Lua name | Field | Used for |
|---|---|---|---|
| 1 | `Effect_CarrierSpeed` | `effective[1]` (`+0xb8`) | carrier base speed (3.8.1) |
| 4 | `Effect_ProductionSpeed` | `effective[4]` (`+0xc4`) | `ProduceGood` duration, modes 6 and 10 (3.5.5) |
| 8 | `Effect_SoldierSpeed` | `effective[8]` (`+0xd4`) | soldier base speed (3.8.1) |
| 12 | `Effect_CornDoubleProduction` | `flags[12]` (`+0x30`) | when `> 0`: amount of goods-list entries whose good is `corn` (id `0x17626a03`) doubled (S 00661c50, S 00663450); read by `PutDownPackage::Update` (3.5.5) and `NVillage::Production::DeliverProducts` S 00565990 |
| 13 | `Effect_WorkerPause` | `effective[13]` (`+0xe8`) | `Rest` duration (3.5.4) |

How the flags and factors are computed from running sacrifices is in [`military.md`](military.md) and
[`properties-data.md`](properties-data.md).

---

## 7. Save and load

Stream primitives (virtual slots of the stream): `+0x40` open write section(tag), `+0x3c` open read section →
version, `+0x14` open read section (version not used by the caller), `+0x58`/`+0x2c` byte,
`+0x5c`/`+0x30` int, `+0x64`/`+0x38` uint,
`+0x4c`/`+0x20` float. A cell or fine position is written as a pair by `ai::map::MapPos::Store` /
`ai::map::FinePos::Store`. **[known]** The `+0x58`/`+0x2c` primitive is the bool writer / reader: on file
streams it transfers 4 bytes (S 00780520, S 00780490), only the checksum stream feeds 1 byte; "byte" in the
lists below names the field, not its width in the file (see [`save-format.md`](save-format.md)).

`System::Store` (S 00654420): section `SettlersSystem`; byte `flag64`; then the six lists in type order 0..5.
Each list (S 00654270): uint count; per settler: int owner player index, int property id, then the settler's
`Store`. `System::Load` (S 00656430) clears the six lists and the flag, opens the section, reads the flag and the
lists in type order 0..4; the NPC list is read only when the section version is `>= 1` (`CMP version, 1` /
`JL` at S 006564da). Per settler the loader reads player and property, constructs with
`ctor_ForLoad` (no new unique id, state 0, cell (0,0)) and calls `Load`. **[known]**

Section tags are the strings of the static log-category objects named in each `Store`; they are quoted here
as they are in the binary (some with a space, some without). **[known]**

`Settler::Store` (S 00656a20), section `Settlers Settler`: unique; movement; animation; package reference; int
state; `LeaveMap`; `LeaveBuilding`; `MoveToShip`; home reference; ship reference; look-at pair (the last only
read when the version is `> 0`). **[known]**

`Animation::Store` (S 0065f0c0), section `SettlersAnimation`: float remaining, float total, int kind. `Load`
(S 0065f110) reads `total` only when the section version is exactly 1; for any other version it sets
`total = remaining`. **[known]**

`Worker::Store` (S 0065c800), section `SettlersWorker`: workplace reference; movies `GoToWorkingPlace`,
`GoMining`, `GoFishing`, `BringGoodHome`, `BringGoodOut`, `ReturnHome`, `GoAfforest`, `ProduceGood`,
`SearchCatapultTarget`, `CatapultAttack`, `GoHunting`; uint `lastWorkTick`; `IdleOutside`; `ReturnFromIdle`;
`Rest`; `GoDigging`; then the base. Load: version `> 0` adds `lastWorkTick`, `IdleOutside`, `ReturnFromIdle`;
`> 1` adds `Rest`; `> 2` adds `GoDigging`. **[known]**

`Carrier::Store` (S 0065a840), section `SettlersCarrier`: movies `LeaveBuilding`, `EnterBuilding`, `Drop`,
`WaitForPackage`, `MoveToStreetPosition`, `PutDownPackage`, `GoToPackageTarget`, `Pickup`; byte
`notYetOnStreet`; reserved package reference; building reference (read only when version `> 0`); then the base.
**[known]**

`SettlerMovement::Store` (S 006576d0), section `Settlers Movement`: base `Movement`; int `streetMode`; only if
path mode is 2 or `streetMode == 1`: `routeTarget`, `nextFlag`, `nextWaypoint`, byte `routeEndRequested`; wait
flag reference; ship reference; `WaitForShip`; `ReturnToLogicGrid`; `parkingCell`; `parkingSpot`; int
`flagWaitState`; int `flagWaitTicks`; uint `streetStopDistance`. `Load` (S 006577e0): `flagWaitTicks` is read
only when the version is `> 0`, `streetStopDistance` only when it is `> 1`; for older versions, if
`stopDistance != 0` and (path mode 2 or `streetMode == 1`), `streetStopDistance = stopDistance`, and
`stopDistance` is then set to 0 when `nextFlag.x != -1` and `routeTarget != nextFlag`. **[known]**

`Movement::Store` (S 00773010), section `MovementMovement`: `Rough`; `Fine`; `Interpolator`; uint
`stopDistance`; `finePos`; byte `holdStep`; `cell`. `Load` (S 00773280) reads `cell` only when the version
is `> 0`; for version 0 it derives it: path mode 0 → (if a fine move is active, `finePos` = the fine mover's
current position) `cell` from `finePos`; other modes → `cell` = the rough mover's current cell and `finePos`
= its centre. **[known]**
- `Rough` (`Movement Rough`): byte moving; step, requested, current, final cells; `Path`.
- `Path` (`Path`): int mode; target cell; `FreePath`; `StreetPath`.
- `FreePath` (`Movement Free Path`): byte `astarMode`; `PathBase` (`Movement Path Base`): byte active; if active:
  cell vector, byte valid, uint index, byte newPath (`PathBase::Load` S 00772e40 reads these four also when
  the section version is 0, whatever `active` is).
- `StreetPath` (`Movement Street Path`): bytes active, valid, arrived; uint index; target cell; cell vector;
  current street reference; bytes replanPending, noReplanAtFlags.
- `Fine` (no tag): byte moving; four fine positions; `FinePath` (`Movement Fine Path`): byte hasPath, position
  vector, byte valid, uint index.
- `Interpolator` (`Movement Interpolator`): floats progress, carryOver, stepRate.

Every movie listed below opens its own section tag (`Movie LeaveBuilding`, `Movie GoMining`, ...: `Movie `
plus the class name, with two exceptions: `GoDigging` uses `MovieGoDigging` and `Rest` uses
`Movie Construct`, the same string as `Construct`) and then writes, in the order given, its
own fields and its sub-movies (each sub-movie through its virtual `Store`, slot 1); a `Package` ends with
`Package::Store` (S 0077dee0) = int `currentStep`. **[known]** for the `Store` functions listed:

| Movie | `Store` | Written after the tag, in order |
|---|---|---|
| `LeaveMap` | 00776af0 | `MoveToHome`, `EnterBuilding`, `ReturnToLogicGrid`, `Stray`, int `strayRetries`, step |
| `Stray` | 0077e040 | `MoveToPosition`, step |
| `EnterBuilding` | 007783c0 | int state |
| `LeaveBuildingFromIdle` | 0077e490 | `MoveToFinePosition`, step |
| `GoToWorkingPlace` | 00779e80 | `EnterBuilding`, `MoveToWorkingPlace`, step |
| `GoToConstructionPlace` | 0077dda0 | `MoveToWorkingPlace`, step |
| `GoMining` | 0077d130 | `LeaveBuilding`, `MoveToDeposit`, `LookForDeposit` (`+0x40`), `Working`, step |
| `GoAfforest` | 0077bb70 | `LookForEmptyPlace`, `LeaveBuilding`, `MoveToDeposit`, `Working`, step |
| `GoFishing` | 0077cdc0 | `LookForFishing`, `LeaveBuilding`, `MoveToPosition`, `Working`, step |
| `GoHunting` | 0077cac0 | `LeaveBuilding`, `MoveToAnimal` (`+0x2c`), `LookForAnimal` (`+0x40`), `Working`, step |
| `GoDigging` | 0077af60 | dig cell (pair), `SearchScholarDiggingPosition`, `MoveToPosition`, `DigForResources`, `LeaveBuilding`, int `digsRemaining`, step |
| `LookForFishing` | 0077f3b0 | target cell (pair) |
| `MoveToDeposit`, `MoveToAnimal` | 00778560, 007786d0 | int state |
| `BringGoodHome` | 0077c790 | `EnterBuilding`, `BringGoodToWorkingPlace` (`+0x18`), step |
| `BringGoodToWorkingPlace` | 0077f150 | `ReturnToWorkingPlace`, `PutDownPackage` (`+0x30`), `PickupProduct`, step |
| `ReturnToWorkingPlace` | 0077eee0 | `WaitForFreeFlag`, `MoveAwayFromDeposit`, `MoveOnMapToWorkingPlace`, step |
| `ReturnHome` | 0077bf20 | `ReturnToWorkingPlace`, `EnterBuilding`, step |
| `BringGoodOut` | 0077c3c0 | `EnterBuilding`, `LeaveBuilding`, `WaitForFreeFlag` (`+0x2c`), `PutDownPackage` (`+0x34`), `PickupProduct`, step |
| `IdleOutside`, `ReturnFromIdle` | 0077ae00, 0077d350 | `MoveToFinePosition`, step |
| `Rest` | 0077b640 | int `restTicksLeft` |
| `CatapultAttack` | 0077b7e0 | `RotateCatapult`, `ShootCatapult`, step |
| `Pickup` | 00778a90 | int state, int good id |
| `Drop` | 007789f0 | int state |
| `PutDownPackage` | 0077a860 | `Drop`, step |
| `WaitForPackage` | 0077ab60 | `MoveToWorkingPlace`, step |
| `GoToPackageTarget` | 0077a040 | `MoveToStreetPosition`, step |
| `ConstructBuilding` | 0077da50 | `BeNervous`, `Construct`, step |
| `Construct` | 0077ffd0 | int `phase`, int `strokesLeft`, float `workPerStroke` |
| `ConstructShip` | 0077d5e0 | `BeNervous`, `LeaveBuilding`, `MoveToPosition`, `Drop`, `ShipConstruct`, step |
| `ShipConstruct` | 0077f910 | int `strokesLeft`, float `workPerStroke` |
| `LeaveBuilding` | 00776e30 | `LeaveBuildingFromIdle`, step |
| `MoveToShip` | 00776900 | `MoveToStreetPosition` (`+0x0c`), step |
| `WaitForShip` | 007771a0 | `MoveToPosition`, `ReturnToLogicGrid`, step |
| `BeNervous` | 007773d0 | int state |
| `LookForEmptyPlace` | 00777b50 | result cell (pair) |
| `SearchScholarDiggingPosition` | 00778120 | result cell (pair) |
| `PickupProduct` | 00778050 | `Pickup` |

The sub-movies with an offset are the ones whose class the `Store` call does not name; their classes come from
the package constructors (`GoMining` S 0077cf70, `GoHunting` S 0077c980, `BringGoodHome` S 0077c640,
`BringGoodToWorkingPlace` S 0077f300, `BringGoodOut` S 0077c270, `MoveToShip` S 00776820). **[known]**

These movies write and read nothing: slots 1 and 2 of their vftables are the empty function S 0064b9c0
(no tag, no field): `MoveToHome`, `MoveToPosition`, `MoveToFinePosition`, `MoveToWorkingPlace`, `LookForDeposit`,
`LookForAnimal`, `MoveToStreetPosition`, `ReturnToLogicGrid`, `Working`, `ProduceGood`, `WaitForFreeFlag`,
`MoveAwayFromDeposit`, `MoveOnMapToWorkingPlace`, `DigForResources`, `SearchCatapultTarget`, `RotateCatapult`,
`ShootCatapult` (and the `NMovie::Object` base). **[known]** (data references to
S 0064b9c0 at `vftable +4` and `+8` of each class.) Their progress lives in the settler's action timer, the
movement object and the parent package's step, which are saved.

Movie `Load` functions read the same fields in the same order. Only three read the section version; all the
others open the section without using it. **[known]**

- `BringGoodHome::Load` (S 0077c810) and `ReturnHome::Load` (S 0077c100), version `< 1`: in place of the
  plain `EnterBuilding`, a nested section `Movie EnterBuildingAndRest` is read, holding `EnterBuilding`, a
  `Rest` and one int; the `Rest` and the int are discarded.
- `BringGoodOut::Load` (S 0077c420), version `< 1`: one `Rest` is read after `PickupProduct` and discarded.
- `Drop::Load` (S 00778a20) has no version test but clamps a stored state `> 1` to 1.

Recomputed after load (`PostLoad`): references are resolved by unique id; `Worker::PostLoad` (S 0065cac0)
re-applies the dig-cell reservation (not stored) and re-registers with the renderer; `Carrier::PostLoad`
(S 0065af50) re-registers and re-announces its street. **[known]** `ai::settlers::SettlerMovement::PostLoad` (S 00657960,
called from the base `PostLoad` S 00656840): when the interpolator progress is `<= 0` it clears
`routeEndRequested`; otherwise it sets `renderDirty`, and for path mode 2 with `routeTarget.x == -1` copies
the rough mover's final target (`+0x38/+0x3c`) into `routeTarget`. **[known]**

`StoreUntagged` (virtual slot 6) is called only from `nGame::System::ComputeChecksum` (S 00784080, through
`System::StoreUntagged` S 00654490): this is the data two machines compare. **[known]** Per list
(S 00654300): uint count; per settler int owner player index, then the settler's `StoreUntagged`. The class
part writes the class `Store` fields without the class section tag (Worker S 0065cb00: all of `Worker::Store`
except `lastWorkTick`; Carrier S 0065aa20: all of `Carrier::Store`; the movies and references are written
through their normal `Store`). The base part (`Settler::StoreUntagged` S 00656b90) writes: unique; package
reference; the movement tail (`SettlerMovement::StoreUntagged` S 006579e0: wait flag reference, ship
reference, `WaitForShip`, `ReturnToLogicGrid`, `parkingCell`, `parkingSpot`, `flagWaitState`,
`flagWaitTicks`, `streetStopDistance`); int property id; int state; home reference; ship reference; look-at
pair. **[known]** Not in the checksum data of a settler: the action timer (`Animation`), the base `Movement`
(interpolator, rough and fine movers, paths, `cell`, `finePos`, `stopDistance`, `holdStep`), `streetMode`
and the route cells, the base movies `LeaveMap`, `LeaveBuilding` and `MoveToShip`, `System.flag64`, and the
worker's `lastWorkTick`. **[known]**

---

## 8. Determinism notes

- **Random numbers.** Simulation code uses `LogicRandom_Next` (S 005389b0, Park-Miller on the global logic seed)
  in: `LookForEmptyPlace::Start` (one draw, only when the search found candidates),
  `SearchScholarDiggingPosition::Start` (one, only with candidates), `Stray::Start` (one, unless the water rule
  already chose a target), `LookForFishing::Start` (one, only with candidates), `Working::Update` (one draw in
  mode 0 and in the not-available branch of mode 2, only when the deposit property has a pattern list),
  `Fight::Start` (one call site), and the per-pattern planting pick `Afforest_PickRandomDepositForCell`
  (S 0077bb30, one draw per call, called from `GoAfforest::Start` S 0077bcb0). **[known]** These are the
  eight call sites in the movie code (S 00776000..00781000). Settler actions also draw
  inside callees: every free-path search that is not the building↔flag shortcut builds its path with
  `randomize = true` (`FreePath::FindPath` S 00775170 → `NMap::AStar::BuildPathReversed`; the number of draws
  per path is in [`map-resources.md`](map-resources.md)), and every entry into a flag queue draws once
  (`FreeSpotSearch::Init` S 00671730, through `BeginWaitAtFlag` → `FlagParking::FindFreeSpot` S 0066d390).
  **[known]** The draw in `Soldier::Update` S 006594a0 (`attackWaitTime + LogicRandom % 10` ticks of
  animation kind 5 on entering state 0x2e; [`military.md`](military.md)) is a further draw outside the movie
  code. Start state and seeding of the generator are in [`logic-core.md`](logic-core.md). The number and
  order of draws must match. In `NSettlers` and the movie code the C `rand()` is used only for the cinematic
  camera target. **[known]**
- **Iteration order.** Type lists in the order Soldier, Constructor, Worker, Specialist, Carrier, NPC; inside a
  list creation order; erase preserves order (3.3). Lookups by unique search the lists in the order Worker,
  Constructor, Carrier, Specialist, Soldier, NPC (S 006546b0). **[known]**
- **Phase offsets.** Periodic checks are spread with the settler's unique id: `(tick + unique.idLo) % 20` (carrier
  looks for a package), `% 10` and `% 200` (carrier at a full flag), `% 23` (replan while parked at a flag).
  Unique ids must therefore be assigned in the same order as the original. **[known]**
- **Floating point.** Movement progress, step rate, carry-over and the action timer are 32-bit floats advanced
  by repeated addition; comparisons are `progress > 1.0`, `progress >= 0`, `remaining <= 0`, and one exact
  equality (`total - remaining == 14.0` for the skeleton). **[known]** None of these floats is written to the
  checksum stream (section 7: `Settler::StoreUntagged` leaves out the action timer and the base `Movement`);
  in the Worker, Carrier, Constructor and NPC parts the only float written is `Construct.workPerStroke` /
  `ShipConstruct.workPerStroke` of a constructor. **[known]** The Soldier part (`Soldier::StoreUntagged`
  S 00658c30, the untagged twin of `Soldier::Store` S 00658960) writes no float either **[known]**: its members
  write ints and bytes only (movie steps through `NMovie::Package::Store` S 0077dee0, `Livepoints::Store`
  S 0065da90, `Bow::Store` S 0065f170, `SoldierFightState::StoreUntagged` S 0065ba40, references and reference
  lists; the `Fight` and `MoveToPosition` movies' `Store` is a no-op), and none of them is among the writers
  of the float slot +0x4c listed in [`logic-core.md`](logic-core.md) section 8 (that list holds every caller
  of the slot in the image). A float difference therefore shows in the compared data only once it has changed
  a state, a step id, a reference or one of the stored cells. **[inferred]**
  A reimplementation that must stay in sync with original clients has to reproduce single-precision arithmetic
  in the same operation order (`1.0 / (dist / (slope * speed))`). **[known]** The x87 control word is set to
  24-bit (single) precision before every logic update (`_controlfp(0x20000, 0x30000)` in S 0057b9b0; call
  sites in [`logic-core.md`](logic-core.md)), so intermediate results are rounded to single as well.
  **[known]** The two float-to-int conversions of this document (`Rest`, strokes) truncate toward zero.
- **Same-tick ordering.** Buildings and the street net update before settlers, transport after (section 4); a
  package put on a flag by a carrier is seen by the transport system in the same tick, by another carrier in the
  next one. **[inferred]**
- Presentation-only fields that are nevertheless saved and part of the checksum data: `lookAtPos`.
  `renderDirty` is neither saved nor part of the checksum. **[known]**

---

## 9. Notes for a reimplementation

- The movie tree is a set of small coroutines. A remake can express each as an explicit state machine or a
  coroutine, as long as "start in tick N, first update in tick N+1" and the failure paths (a `Start` that returns
  false) are kept, because they decide how many ticks a cycle takes.
- Keep the two-level position model: logic cell changes only on step completion; everything else (footprint
  tests, "is at flag", "is at work cell") uses the logic cell. Visual interpolation is free.
- Keep one action timer per settler with integer-tick semantics (`remaining -= 1` until `<= 0`).
- The step ids and the shared state numbers are stored in saves and compared in checksums; for compatibility
  with original saves they must be kept as numbered here. Without that requirement they can be renamed freely.
- Can be simplified without changing behaviour: the `Rough`/`Fine`/`Path` class split (one mover with a mode is
  enough), the "reversed vector + index" path storage, the section tags.
- Must be exact for lockstep with original clients: update order, list order, unique-id assignment order, RNG
  draw order, float arithmetic of movement and timers, the tick phases `% 10/20/23/200`.
- For a stand-alone remake the following numbers reproduce the feel: 10 ticks/s, 0.058 cells/tick, uphill
  factors 0.8 / 0.6 / 0.4, 4 + 4 ticks to pick up or put down, work durations from `bp_setProductionTime`,
  rest from `bp_setRestTime`, idle outside after more than 600 ticks without work, at most 27 stray walks
  before a homeless settler dies, death animation 28 ticks with the skeleton appearing after 14.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.5.2): a worker stays in state 0x24 only while the stock can supply; with one unit per production cycle it releases one settler on its first tick in 0x24, stays one more tick and goes to Rest (0x23), in the observed buildings every 390 ticks. A building with several units in stock was not seen [live, 2026-10-14] | — |
| 2 | Answered (§3.8.1, movie timer): 17 or 18 ticks per flat cell (18 for the first cell of a walk), 21 / 22 at slope factor 0.8, 28 / 29 at 0.6; 4 ticks per pick-up or put-down phase | live 2026-10-12: hook on `Settler::Update` S 00656ec0 |
| 3 | Answered (§3.10): yes, it re-centres and stays; the fall-through and the shared `Update` S 00777c50 decide it. Not observable with the shipped data: the three calls of `se_moveNPCTo` / `se_moveNPCToFine` (C05.lua, C06.lua) are commented out | static: S 0065ddf0, S 0065e010, vftable slots S 008345d4 and S 00834534 |
| 4 | Answered (§3.6.2, effect of the street swap): it takes place whenever the carrier of the package's next street is idle (`Transport_IsCarrierFreeForStreetSwap`) or waits at a full flag the other way; the package is carried across the full flag without being put on it [inferred: the street route planner S 007735b0 was not re-read for this case]. How often this happens in a match does not change the rule | — |
| 5 | Answered (§3.6.2, from the code: `IsFlagFullWaitExceeded` S 0077a0c0, state 0x12 of S 0065b200): after the 361st failed attempt the next step-0x14 check hands the good to the storehouse found by the mode-0 search (none found: the good is lost) and discards the package; an observation would only confirm it. Measured: attempts every 10th tick after an initial run, `!flag blocked` at the 180th attempt (about 150 to 165 s at speed 1); the limit does not apply to a carrier without a street (S 0065ad70) | — |
| 6 | Answered (§2.9): direction 1 points to the screen's lower side, slightly left (about south-south-west) with the camera unrotated; it is not the lower right neighbour [live, 2026-10-14] | — |
| 7 | Answered (section 7, package constructors): `GoMining +0x40` `LookForDeposit`; `GoHunting +0x2c` `MoveToAnimal`, `+0x40` `LookForAnimal`; `BringGoodHome +0x18` `BringGoodToWorkingPlace`; `BringGoodToWorkingPlace +0x30` `PutDownPackage`; `BringGoodOut +0x2c` `WaitForFreeFlag`, `+0x34` `PutDownPackage`; `MoveToShip +0x0c` `MoveToStreetPosition` | — |
| 8 | Answered (section 8): none. The members written by `Soldier::StoreUntagged` S 00658c30 write ints and bytes only; none of their `Store` functions calls the float slot +0x4c (logic-core.md section 8) | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00654ce0 | `NSettlers::System::Update` | per-tick entry, list order |
| 00654a10 | `UpdateSettlerVector` | update / remove loop of one list |
| 00656500 | `NSettlers::System::CreateSettler` | create by settler type |
| 006560d0 / 006561f0 | `System::CreateWorker` / `CreateCarrier` | creators |
| 00654420 / 00656430 | `System::Store` / `Load` | save format |
| 00654270 | `StoreSettlerVector` | per-list save |
| 00654490 / 00654300 | `System::StoreUntagged` / `StoreUntaggedSettlerVector` | checksum data, per list |
| 00656b90 / 006579e0 | `Settler::StoreUntagged` / `SettlerMovement::StoreUntagged` | checksum data of one settler |
| 006576d0 / 006577e0 / 00657960 | `SettlerMovement::Store` / `Load` / `ai::settlers::SettlerMovement::PostLoad` | movement save format, load fix-ups |
| 00773010 / 00773280 | `ai::movement::Movement::Store` / `Load` | base movement save format |
| 0077dee0 / 0064b9c0 | `NMovie::Package::Store` / empty function | step id; `Store` and `Load` of the movies that save nothing |
| 0053bf50 | `Settler_LinkDestinationReference` | sets the home reference `Settler +0xd8` |
| 00654720 | `System::FindNearestSettlerWithinRadius` | settler lookup of `se_isSettlerOnPosition` |
| 00656c20 | `NSettlers::Settler::ctor` | base fields, initial state |
| 00656ec0 | `NSettlers::Settler::Update` | base tick: timer, movement, states 0/3/5 |
| 00656670 | `Settler::SetStateAndStartMovie` | state + movie start |
| 00656740 | `Settler::StopAndSetState3` | lose job, go home |
| 00656760 | `Settler::StartDying` | death |
| 006567f0 | `Settler::IsStateNotIdleLike` | "active" test |
| 0065f040 / 0065f080 | `NSettlers::Animation::Tick` / `Start` | action timer |
| 0065d7f0 | `NSettlers::Worker::Update` | worker state machine |
| 0065d660 | `Worker::ChooseNextWork` | job selection by working mode |
| 0065d3b0 | `Worker::RestOrIdleOutside` | rest vs idle rule |
| 0065c740 | `Worker::IsAtIdlePosition` | idle-spot test |
| 0065c710 | (unnamed) | initial state of a pre-placed worker |
| 0065b710 | `NSettlers::Carrier::Update` | carrier dispatch |
| 0065b200 | `Carrier::UpdateStreetTransport` | street carrier state machine |
| 0065ad70 | `Carrier::UpdateDropOffAfterSpawn` | unassigned carrier |
| 0065b150 | `Carrier::AssignToStreet` | street assignment |
| 0065ea20 / 0065e1d0 / 0065e770 | `Constructor::Update` / building / ship routines | builder |
| 0065eec0 | `NSettlers::Specialist::Update` | scholar |
| 0065ddf0 | `NSettlers::NPC::Update` | scripted NPC |
| 00658140 | `ai::settlers::SettlerMovement::Update` | per-tick movement, flag queue |
| 00657b80 | `ai::settlers::SettlerMovement::AdvanceStreetRoute` | next street leg / queue at flag |
| 00657360 | `ai::settlers::SettlerMovement::PlanStreetRoute` | plan one leg |
| 00657f50 / 00658000 / 006574d0 | `SettlerMovement::StartStreetMoveTo` / `MoveToCell` / `MoveToFinePos` | the three ways to walk |
| 00657570 | `ai::settlers::SettlerMovement::IsBusy` | busy test |
| 00658070 / 006583d0 | `ai::settlers::SettlerMovement::Abort` / `CancelRoute` | stopping |
| 006571e0 | `SettlerMovement::BeginWaitAtFlag` | enter flag queue |
| 007730e0 | `Movement_Update` | composite mover tick |
| 00773a40 / 00773ec0 | `NMovement::Rough::BeginStep` / `Fine::BeginStep` | speed formula |
| 00773cd0 / 007740f0 | `Rough::UpdateStep` / `Fine::UpdateStep` | step completion |
| 00774a10 | `NMovement::Interpolator::Advance` | progress and carry-over |
| 007735b0 / 00773520 | `ai::movement::StreetRoutePlan::Plan` / `PlanSameFlag` | street leg planning |
| 007741e0 | `NMovement::StreetPath::ComputeRoute` | cells of a leg |
| 007747b0 | `NMovement::StreetPath::CanAdvance` | street still there |
| 00775170 | `NMovement::FreePath::FindPath` | free path, building↔flag shortcut |
| 00774f10 | `NMovement::FinePath::SetTarget` | straight fine path |
| 00663310 | `ai::logic::SacrificeModifiers::GetScaledValueForUnitKind` | base speed × player factor |
| 0052d9e0 / 0052e250 / 0052dd10 | slope speed factors | uphill slowdown |
| 0052ddb0 | `Building_GetIdleFinePosition` | idle spots |
| 0077de50 | `NMovie::Package::StartStep` | composite movie step switch |
| 00776f40 / 00776eb0 | `NMovie::LeaveBuilding::Start` / `Update` | walking out |
| 00777500 / 00778c20 | `NMovie::EnterBuilding::Start` / `Update` | walking in |
| 00776d00 / 00776bd0 | `NMovie::LeaveMap::Start` / `Update` | going home |
| 007776f0 / 007775f0 | `NMovie::MoveToHome::Start` / `Update` | home search |
| 00779e70 / 00779f20 | `NMovie::GoToWorkingPlace` start / `Update` | walk to workplace |
| 0077d250 / 0077d090 | `NMovie::GoMining::Start` / `Update` | gather job |
| 0077bcb0 / 0077be10 | `NMovie::GoAfforest::Start` / `Update` | planting job |
| 0077f670 / 0077cea0 | `NMovie::LookForFishing::Start` / `GoFishing::Update` | fishing job |
| 0077cba0 | `NMovie::GoHunting::Update` | hunting job |
| 0077b170 / 0077b4b0 | `NMovie::GoDigging::Start` / `Update` | scholar digging |
| 0077eda0 / 0077ebf0 | `NMovie::Working::Start` / `Update` | work animation and its effect |
| 00777460 / 00777430 | `NMovie::ProduceGood::Start` / `Update` | workshop production |
| 0077c510 | `NMovie::BringGoodOut::Update` | carry product to the flag |
| 0077c740 / 0077f270 / 0077f020 | `BringGoodHome` / `BringGoodToWorkingPlace` / `ReturnToWorkingPlace` `Update` | carry harvest home |
| 00777f80 | `NMovie::PickupProduct::Start` | which good is picked |
| 007781e0 / 00777e00 | `NMovie::Pickup::Start` / `Update` | pick-up timing |
| 00777d10 / 00777d50 | `NMovie::Drop::Start` / `Update` | put-down timing |
| 0077a8e0 | `NMovie::PutDownPackage::Update` | drop at flag, harvest bonus |
| 0077ac50 | `NMovie::WaitForPackage::Update` | carrier idle loop |
| 0077a260 / 0077a2f0 | `NMovie::GoToPackageTarget::Start` / `Update` | carrier walk, full-flag wait, swap |
| 0077b6d0 / 0077b630 | `NMovie::Rest::Start` / `Update` | rest counter |
| 0077ae80 / 0077aec0 / 0077d420 | `IdleOutside` / `ReturnFromIdle` | idling outside |
| 0077e0c0 | `NMovie::Stray::Start` | homeless wandering |
| 00777240 | `NMovie::WaitForShip::Update` | parking at a flag |
| 0077daf0 / 0077fb50 / 0077fe70 | `ConstructBuilding::Update` / `Construct::Update` / `Start` | building work |
| 00564360 / 005643c0 / 00564e00 / 00564eb0 | `NVillage::SettlerSpawn` consume / can-supply / spawn / entered | tool → settler → tool |
| 0055b6a0 | `NVillage::Workers::SpawnWorker` | worker of a pre-built building |
| 00668be0 | `NNet::Street::SpawnCarrier` | carrier of a street |
| 00561e20 | `VillageOrder_LinkSettlerToDestination` | assignment on order completion |
| 005686a0 | `VillageOrder_GetCategory` | order category 0..6 |
| 00557fe0 / 00557ef0 | `BuildingList_FindNearestReachable` / `FindNearestConnected` | home search, modes 1 and 0 |
| 00663f50 | `NNet::System::FindNearestFlagWithLink` | nearest flag of a street network |
| 0064dae0 / 006513b0 | `Transport_CarrierTryPlacePackageOnFlag` / wait accounting | flag test with side effects |
| 0077a0c0 | (unnamed) | `GoToPackageTarget` waits and `pkg +0x104 > 360` |
| 005b7b40 / 0077a0f0 / 0077a150 / 0064ef60 | street swap helpers | target test, free partner, loaded partner, set next hop |
| 0053d2b0 / 0053d2d0 | link / unlink carrier and sending building | `Carrier +0x1c0` |
| 00661bf0 / 00663410 | `ai::logic::SacrificeModifierQuery::GetScaledBuildingTimeE0` / rest time scale | `Rest` duration |
| 00661b60 / 00663390 | `ai::logic::SacrificeModifierQuery::GetProductionTime` / production time scale | `ProduceGood` duration |
| 00661c50 / 00663450 | `GetEntryWithModifiers` / `ApplyAmountDoubling` | harvest count |
| 00774a00 | `NMovement::Interpolator::SyncValue` | progress = carry-over |
| 00675000 | `ai::map::MapPos::StepDirection` | hex direction tables |
| 00676200 / 00675d30 | `NMap::Elevations::GetSlopeClassBetween` / height difference → class | slope classes |
| 00676840 | `NMap::AStar::GetStepCost` | `astarMode` = ignore blocking |
| 00671730 | `ai::nnet::FreeSpotSearch::Init` | RNG draw when entering a flag queue |
| 0077fa30 / 0077f9c0 | `NMovie::ShipConstruct::Start` / `Update` | ship hammering |
| 0065df90 / 0065dfd0 | `NPC::SetMoveTargetCell` / `SetMoveTargetFinePos` | NPC targets |
| 0055b4d0 | `NVillage::Workers::HasArrivedWorker` | caller of virtual slot 9 |
| 00654240 | (unnamed) | sets `System +0x64` |
| 0057b9b0 | `Fpu_SetDefaultControlWord` | 24-bit FPU precision |
| 00555780 | `Properties_GameConfig_ctor` | config defaults |
| 00527070 | `NLogic::System::Update` | tick order |
