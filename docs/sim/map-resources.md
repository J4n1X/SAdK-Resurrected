# Map, terrain, resources and doodads

Binary: `sadk_noav.exe` (image base 0x400000). `S 00xxxxxx` is a static address in that binary. Tags: **[known]** =
read directly in the code or the data, **[inferred]** = one step of reasoning from what is visible, **[TODO]** = open.
Nothing in this document has been observed in the running game.

Related documents: `docs/map-format.md` (byte layout of every map and save section named here, the grid-state bit
table in §5.4, the continent and cliff algorithms in §5.6 and §5.7), `docs/sim/logic-core.md` (tick order, random
generator, spawn points, chests), `docs/sim/village-buildings.md` (the building placement predicate in §3.1, the
resource searches of buildings in §3.9, territory sources in §3.14), `docs/sim/players-victory.md` (spotted and
reached flags, territory share), `docs/sim/game-commands.md` (street planning), `docs/navy-and-military.md`,
`docs/lua-surface.md` (the `properties.*` and `map.*` Lua functions), `docs/types.md`, `docs/subsystems.md`.

Game data quoted here comes from the decrypted install (`tools/sadk_crypt.py`): `scripts/properties/patterns.lua`,
`deposits.lua`, `animals.lua`, `doodads.lua`, `signs.lua`, `spawnpoints.lua`, `config.lua`, `Goods.lua` and
`settings/graphics.xml`.

---

## 1. Purpose and scope

This subsystem is the world the simulation runs on. It is responsible for:

- the **cell grid** (hexagonal, W x H cells) and the finer **vertex grid** of terrain heights [known] S 00672430;
- the per-cell layers: terrain pattern, grid-state bits, ground resource, territory owner, exploration per player,
  continent id, per-player construction flags, object references (flag, building, street, deposit, dig reservation)
  [known] S 00672180;
- deriving grid bits from heights and patterns (water, shore, cliff, mining ground, buildable, ship ground, territory
  border) [known] S 0067b150..0067b910;
- all terrain edits made by gameplay: levelling under flags, bulldozing, street shaping, pattern changes (fields)
  [known] `ai::map::MapModifier`;
- **territory** ownership from territory sources [known] S 00679510;
- **exploration** (the fog of war) [known] S 00674800;
- **ground resources** (ore, coal, salt, gems, granite, gold, fish: an amount per cell) and their consumption
  [known] S 006745e0, S 00674650;
- **deposits** (objects standing on a cell: trees, stone piles, grain fields), their growth, harvest stages, expiry
  and removal [known] `NResources::Deposit`;
- wild **animals**: roaming, the per-cell index, the density grid, the states used by hunters [known]
  `NResources::Animal`;
- **doodads** (decoration, resource signs, skeletons, blocking decoration) and when they disappear [known]
  `NDoodads::System`;
- **path-finding** on the cell grid: the A* base class and its cost functions, and the breadth-first "flood fill"
  searches that all nearest-something queries use [known] `NMap::AStar`, `ai::map::FloodFillSearch`.

It is **not** responsible for: the building placement predicate itself (`GameQuery::CanPlaceBuildingAt`, described in
`docs/sim/village-buildings.md` §3.1; this document describes the per-cell flags computed from it), which buildings
give territory and with which radius (`docs/sim/village-buildings.md` §3.14), spawn points
(`docs/sim/logic-core.md` §3.5; their effect on this subsystem is in §3.9 and §3.10 here), harbors and ship routes
(`docs/map-format.md` §6, `docs/navy-and-military.md`), the movement interpolation of walkers (`NMovement`), the
settler work sequences (`NMovie`) beyond the calls they make into this subsystem, and rendering.

There is **no dynamic line of sight**: a cell is either explored for a player or not, and exploration is never taken
back [known: the only writer of the exploration grids during play stores 1, S 00677570; besides it only
`Exploration::Load` S 00677b30 writes cells (the saved bytes); `Clear` runs only on reset, load and map export,
`Init` only on map creation and map export, S 00677930, S 00677af0, S 00672f80].

---

## 2. Data model

### 2.1 Coordinates

| Space | Type | Range | Meaning | Evidence |
|---|---|---|---|---|
| cell | `MapPos {int x, y}` | 0..W-1, 0..H-1 | one hexagon; linear index `y*W + x` | [known] S 00676270 |
| vertex ("fine") | `{int x, y}` | 0..4W, 0..4H | height sample; linear index `y*(4W+1) + x` | [known] S 00672430 |
| low-res | `{int x, y}` | cell / 16 | 16 x 16 cell blocks (animal density, AI) | [known] S 00582430 |
| world | 3 floats | | rendering and movement interpolation | [known] S 00687500 |

- Globals: `g_MapWidth` S 00880fb0, `g_MapHeight` S 00880fb4, `g_MapVertexWidth` = 4W+1 S 00880fa8,
  `g_MapVertexHeight` = 4H+1 S 00880fac, `g_MapCellCount`, `g_MapVertexCount` [known] S 00672430.
- A cell samples its height at vertex `(4x + 2*(y & 1), 4y)` [known] S 00676200.
- Vertex to cell: `cy = vy / 4`, `cx = (vx - 2*(cy & 1)) / 4`, both divisions truncating toward zero
  [known] S 00675160.
- Both grids are hexagonal with **odd rows shifted half a step to the right**; the same direction tables serve cells
  and vertices [known] S 00675000, S 00673910 (the smoothing code steps vertices with the cell step function).
- World position of vertex (vx, vy): `x = vx*stepX + originX (+ stepX/2 on odd vy)`, `y = height*heightScale`,
  `z = vy*stepZ + originZ` [known] S 00687500. The three factors come from `graphics.xml`
  `<Map scaling="1.5 0.001 1.2990375"/>` [known] S 00686f10; so one cell is 6.0 world units wide, rows are 5.196
  apart, and 1000 height units are one world unit [inferred].

### 2.2 `NMap::System` (size 0x58, vtable S 007f890c)

Owned by `NLogic::System` at +0x30 [known] `docs/sim/logic-core.md` §2.1. Members [known] S 00672180:

| Offset | Member | Size | Saved | Content |
|---|---|---|---|---|
| +0x04 | `bInitialized` | byte | yes | |
| +0x08, +0x0c | `width`, `height` | int | yes | cells |
| +0x10 | `Elevations*` | 0x18 | yes | vertex heights |
| +0x14 | `Patterns*` | 0x18 | yes | pattern id per cell |
| +0x18 | `GridStates*` | 0x18 | yes | bit word per cell |
| +0x1c | `Territory*` | 0x20 | yes | owner per cell |
| +0x20 | `ConstructionMap*` | 0xa0 | no | construction flags per player and cell |
| +0x24 | `ObjectLayers*` | 0x54 | no | 5 layers of object ids per cell |
| +0x28 | `Exploration*` | 0x90 | yes | explored byte per player and cell |
| +0x2c | `Continents*` | 0x3c | yes | continent id per cell and the continent list |
| +0x30 | `Resources*` | 0x20 | yes | ground resource per cell |
| +0x34 | `CallbackManager*` | 0x14 | no | listeners for map changes (§5.3) |
| +0x38 | `MapModifier*` | 0x70 | no | the only writer of the grids during play |
| +0x3c | `AStar*` | 0x48 | no | shared base path-finder for free walkers |
| +0x40 | `VisitedGrid` | 0x18 | no | stamp per cell for flood fills (§2.9) |

### 2.3 The per-cell grids

**Elevations** [known] S 006761e0, S 00675db0: `heights` = int32 per vertex, `minHeight` = int32, **the water
level**, default -100. Heights are plain integers; shipped maps use about -10800..15000 (`docs/map-format.md` §4.5).

**Patterns** [known] S 00676270: one int32 pattern property id per cell (a hash from `pa_create`). The pattern
decides ground type flags (§2.5).

**GridStates** [known]: one uint32 per cell. The full bit table with setters is `docs/map-format.md` §5.4; the rules
that derive bits are §3.3 here. Summary:

| Mask | Name | Written by |
|---|---|---|
| 0x1 | blocked | pattern `blocked`; blocking deposits; the position cell (anchor) of a building, of remains and of an upgrade (`NVillage::Blocking::ApplyToMap` S 00566e10, set from S 00566fc0) |
| 0x2 | street | street net (S 006710a0) |
| 0x4 | water | height below water level (§3.3) |
| 0x8 | shore | land cell next to water (§3.3) |
| 0x10 | mining ground | pattern `forMining` |
| 0x20 | territory border | territory recomputation (§3.6) |
| 0x40 | cliff | cliff marker (`docs/map-format.md` §5.7) |
| 0x80 | deposit | deposit creation and removal (§3.9) |
| 0x100 | building footprint | `NVillage::Blocking::ApplyToMap` S 00566e10: every in-map cell of the footprint iterator for the blocking record's position and size value |
| 0x200 | buildable ground | pattern `forBuilding` and neither `forMining` nor `blocked` |
| 0x400 | logic object | spawn points, chests, blocking doodads |
| 0x800, 0x2000, 0x4000, 0x8000, 0x10000 | dock, harbor, harbor exit, ship route, ship tile | navy |
| 0x20000 | ship ground | pattern `forShip` and neither `forBuilding` nor `blocked` |

**Resources** (ground resources) [known] S 006745e0: per cell `{int32 amount, int32 resourceType}`, empty =
`{0, -1}`. `resourceType` is a good id (for example `fish` 0x4012e5a3, `coal` 0x7068dcd3, `ironOre` 0xec5020be,
`gold` 0x4f41c633, `stone` 0x55e952d3, `gemstones` 0xcb98c903; `Goods.lua` `gp_create`) [known for fish
S 00674210; inferred for the others from the sign table and `gp_setMiningGood`]. A building never searches for
its product's own id but for the product's **mining good** (good property +0xbc, `gp_setMiningGood` S 0054e530,
read by S 00540660): `Goods.lua` maps the tribe variants onto the base ids, for example
`gp_setMiningGood(coalBav, coal)`, `(fishScots, fish)`, `(stone, stone)` [known, code and data]. `amount` is
1..7, or **1000 = unlimited** [known] S 00674650.

**Territory** [known] S 00679f20: int32 owner per cell, player index 0..7 or -1.

**Exploration** [known] S 00677af0: 8 byte vectors (one per player slot), each W*H, 0 = unexplored, 1 = explored.

**Continents**: int32 continent id per cell (-1 = none) and a list of continents with cell count, water flag,
bounding box and neighbour ids. Layout and the partition algorithm: `docs/map-format.md` §4.11 and §5.6. Lookup
`GetContinentAt` S 0052deb0 [known].

**ConstructionMap** [known] S 00675740, S 00675610: for each of the 8 player slots a uint32 per cell:

| Mask | Meaning |
|---|---|
| 0x1 | a small building fits |
| 0x2 | a medium building fits |
| 0x4 | a large building fits |
| 0x8 | a mine fits |
| 0x10 | a ship building fits |
| 0x20 | a flag can be placed |
| 0x40 | a military building is allowed (only with 0x1) |

Stored values of the low five bits are exactly 7, 3, 1, 8, 16 or 0 (§3.5). The building `size` masks in
`config.lua` match: `SizeSmall = 7`, `SizeMedium = 6`, `SizeLarge = 4`, `SizeMine = 8`, `SizeShip = 16`,
`SizeMilitary = 64` [known, data]. `GameQuery_BuildingTypeFitsCellFlags(type, cell, player)` S 0052eab0
[known]: false if the building property's `size` has bit 0x40 and the cell's flags do not; otherwise true iff
`cellFlags & size & 0x3f` is not zero.

**ObjectLayers** [known] S 00672d10, S 006737d0..00674040: 5 vectors of `NLogic::Unique` (16 bytes: vtable, pad,
64-bit id), one entry per cell. An entry is **empty** when the high dword of the id is negative (-1, -1).

| Layer | Holds the id of | Written by |
|---|---|---|
| 0 | flag | `NNet::Flag` ctor, dtor, PostLoad |
| 1 | building, on its **position cell (anchor) only**; the other footprint cells carry grid bit 0x100 but no id [known] S 0055d980, S 0055d4e0, S 0055ce70, S 0055c260 | `NVillage::Building` ctors, dtor, PostLoad |
| 2 | street | `NNet::StreetMapUpdater` |
| 3 | deposit | `NResources::Deposit` |
| 4 | dig reservation of a geologist | `NMovie::GoDigging` |

### 2.4 `ai::map::MapModifier` (size 0x70) and `MapUpdateBatch`

`MapModifier` [known] S 00673b50: +0x00 `bEnabled` (1), pointers to the listeners and all grids, +0x2c
`cellDirty` rect (cells, minX = -1 means empty), +0x3c `elevDirty` rect (vertices), +0x4c `MapCellUpdater`
(the bit derivers, with the `CliffMarker` inside), +0x6c `batchDepth` (elevation batch nesting).

`MapUpdateBatch` (the object at `NLogic::System + 0x44`, also named `GameCmdRouter` in the map) [known] S 00532380,
S 00532180, S 005321c0:

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | owner | `NLogic::System*` |
| +0x04 | `fullDoodadRefresh` | byte |
| +0x08 | `doodadDirty` | cell rect, -1 = empty |
| +0x18 | `constructionDirty` | cell rect, -1 = empty |
| +0x28 | `recomputeAll` | byte: recompute the whole construction map |
| +0x29 | `rebuildContinents` | byte; set by S 00532120 while a batch is open (with no batch open that function rebuilds at once through `NMap::Continents::Rebuild` S 00679430); its only callers are in `nMenu::Debug`, so play never requests a rebuild [known for the cached call graph] |
| +0x2c | `counter` | 0 at construction; `Begin` decrements, `End` increments; rest value 1 after `SetUp` |

### 2.5 Property records (static data, filled by the Lua property scripts)

**PatternProperty** [known] S 00555c00 (defaults) and the `pa_*` setters:

| Offset | Field | Setter | Default |
|---|---|---|---|
| +0x00 | id | `pa_create(hash)` | -1 |
| +0x3c | `blocked` | `pa_setBlocked` | false |
| +0x3d | `forMining` | `pa_setForMining` | false |
| +0x3e | `forBuilding` | `pa_setForBuilding` | false |
| +0x3f | `forShip` | `pa_setForShip` | false |
| +0x40 | minimap colour (4 bytes) | `pa_setMiniMapColor` | 100, 255, 60, 255 |
| +0x44 | `treeType` | `pa_setTreeType` | -1 |
| +0x48 | `forPlanting` | `pa_setForPlanting` | false |

**DepositProperty** (size 0x84) [known] S 005553d0 (defaults) and the `dp_*` setters:

| Offset | Field | Setter | Default | Use |
|---|---|---|---|---|
| +0x00 | id | `dp_create(hash)` | -1 | |
| +0x3c | `good` | `dp_setGood` | -1 | the good a harvest yields; search key |
| +0x40 | `nextDeposit` | `dp_nextDeposit` | -1 | deposit type this one turns into when harvested |
| +0x44 | `growingStartSize` | `dp_setGrowingStartSize` | 0.1 | growth value after sowing |
| +0x48 | `growingSpeed` | `dp_setGrowingSpeed` | 0.0009 | growth per tick |
| +0x4c | `randomFinePosOffsetState` | `dp_setRandomFinePosOffsetState` | true | random display offset |
| +0x50 | `elevationSize` | `dp_setElevationSize` | 1 | [TODO] consumer not read |
| +0x54 | `blocking` | `dp_setBlocking` | false | sets grid bit 0x1 on the cell |
| +0x58 | `undergroundPatterns` (vector of int) | `dp_addUndergroundPattern` | empty | pattern set when sown |
| +0x68 | `doodadAfterDestruction` | `dp_setDoodadAfterDestruction` | -1 | doodad left by the last harvest |
| +0x6c | `lifeTime` | `dp_setLifeTime` | -1 | ticks without an owner building |
| +0x70 | `needForPlantablePattern` | `dp_setNeedForPlantablePattern` | false | placement rule |
| +0x74 | `treeTypes` (vector of int) | `dp_addTreeType` | empty | planting filter |

**AnimalProperty** (size 0x68) [known] S 00555190 (defaults) and the `an_*` setters:

| Offset | Field | Setter | Default |
|---|---|---|---|
| +0x3c | `range` (roam radius around home, cells) | `an_setRange` | -1 |
| +0x40 | `moveDistance` | `an_setMoveDistance` | 3 |
| +0x44 | `movementSpeed` | `an_setMovementSpeed` | 0.1 |
| +0x48 | `avoidBuildings` | `an_setAvoidBuildings` | true |
| +0x4c | `idleTimeFactor` (stored as max(value, 2.0)); scales the first idle counter of a new animal and the idle counter after every walk (§3.10) | `an_setIdleTimeFactor` | 3.0 |
| +0x50 | `stackGoods`: map tribe -> vector of goods | `an_addStackGood(animal, tribe, good)` | empty |
| +0x5c | `respawn` | `an_setRespawn` | true |
| +0x60 | `dyingTime` (ticks) | `an_setDyingTime` | 55 |
| +0x64 | `disappearingTime` (ticks) | `an_setDisappearingTime` | 20 |

**DoodadProperty** [known] S 00555970 (defaults) and the `dd_*` setters:

| Offset | Field | Setter | Default |
|---|---|---|---|
| +0x3c | `lifeTime` (ticks; < 1 = permanent) | `dd_setLifeTime` | -1 |
| +0x40 | `onWater` | `dd_setOnWater` | false |
| +0x41 | `deleteByStreet` | `dd_setDeleteByStreet` | true |
| +0x44 | `type` | `dd_setType` | 0 |
| +0x48 | `blocking` | `dd_setBlocking` | false |
| +0x49 | `indestructable` | `dd_setIndestructable` (sets 1, ignores its argument) | false |

**Sign table** [known] S 00556d70, S 00556cb0: `si_addSignDoodadId(good, threshold, doodad)` builds, per good, a
list of (threshold, doodad) kept **sorted by ascending threshold** (signed; an entry with an equal threshold goes
after the existing ones) [known] S 005574f0, S 00556df0; lookup returns the doodad of the last entry whose threshold
is <= the amount, or -1 below the first. The lookup S 00556d70 does not handle a good without any entry (the
map find is dereferenced unchecked) [known].

**GameConfig** fields used here [known]: +0x08 border pattern (`cfg_setBorderPattern` S 0054c3b0), +0x1c fishing
distance (`cfg_setFishingDistance` S 0054c300), +0x40 maximum water depth for water streets
(`cfg_setMaxWaterStreetWaterDepth` S 0054c200), +0x50 spawn point update time. Defaults compiled into the
constructor S 00555780: fishing distance 3, water depth 100, spawn point update time 600; the shipped `config.lua`
replaces them (§6) [known].

### 2.6 `NResources::System` (size 0x64, vtable S 007e7ed8)

[known] S 00541460, S 00540340:

| Offset | Field | Saved | Meaning |
|---|---|---|---|
| +0x04 | map system | no | |
| +0x08 | `mapTreeType` | yes (v > 5) | the tag a plantable deposit type must carry (§3.9): 100 `mapTreeType_Bavarian`, 101 `mapTreeType_Egyptain` (spelling of the game data), 102 `mapTreeType_Scot` [known: `deposits.lua` lines 1-3; reader `Afforest_PickRandomDepositForCell` S 0077bb30]. The constructor stores 100 and `Load` is the only other writer, so another value comes from a map or a save [known] |
| +0x0c | `deposits` (vector of `Deposit*`) | yes | creation order |
| +0x1c | `depositById` (map Unique -> `Deposit*`) | no | |
| +0x28 | `activeDeposits` (vector of `Deposit*`) | no (rebuilt) | deposits that need a per-tick update |
| +0x38 | `animalById` (map Unique -> `Animal*`) | yes | iteration order = ascending id |
| +0x44 | `bInitialized` | yes | |
| +0x48 | `AnimalAStar*` | no | shared path-finder for animals |
| +0x4c | `animalsByCell` (map cell index -> vector of `Animal*`) | no | |
| +0x58 | `AnimalAreas*` | no | density per 16 x 16 block |
| +0x5c | `roamTurn` | yes | scheduling value of the roam searches (§3.10) |
| +0x60 | `roamSearchesThisTick` | yes | reset to 0 every tick |

**`NResources::Deposit`** (size 0x58, vtable S 007e7f48) [known] S 00542f80, S 005431a0:

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x08 | `id` | Unique | |
| +0x18 | `growth` | float32 | -1.0 at construction; 1.0 = full; >= 1.0 = harvestable |
| +0x1c | `property` | `DepositProperty*` | |
| +0x20 | `cell` | MapPos | at most one deposit per cell [inferred from layer 3] |
| +0x28 | `finePos` | vertex | where it is drawn; also the doodad conflict test |
| +0x30 | `reservingBuilding` | ReferenceBuilding | the building that linked it; none = id high dword negative |
| +0x50 | `depletedTicks` | int | 0 = alive; 1..20 = being removed |
| +0x54 | `ttlWithoutOwner` | int | from `lifeTime`; -1 = none |

**`NResources::Animal`** (size 0xb8, vtable S 007e7ef8) [known] S 005418e0, S 005420c0:

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x04 | `owner` | `System*` | |
| +0x08 | `property` | `AnimalProperty*` | |
| +0x10 | `id` | Unique | |
| +0x20 | `timeStamp` | float32 | tick / 10 of the last walk start |
| +0x24 | `home` | MapPos | the spawn cell; never changes [inferred: no writer besides the constructors] |
| +0x2c | `movement` | `NResources::Movement` | `NMovement::Base` first: current cell at Animal +0x30, target cell of the walk +0x38, next cell +0x40 (-1, -1 before the first step), step progress float +0x4c; then the owner animal, the path and the cell it is registered on in `animalsByCell` [known] S 00772ba0, S 005437c0 |
| +0x88 | `state` | int | see §3.10 |
| +0x8c | `counter` | int | meaning depends on the state |
| +0x90 | `hunter` | ReferenceBuilding | reservation by a hunter's building |
| +0xb0 | `stackIndex` | int | how many of its goods have been picked up |

**`NResources::AnimalAreas`** [known] S 00542700, S 005424c0: an int per low-res block
(`(W+15)/16 x (H+15)/16`), counting animals by their **home** cell.

### 2.7 `NDoodads::System` (size 0x44) and `NDoodads::Object` (size 0x30)

System [known] S 00544e00, S 00544480:

| Offset | Container | Content |
|---|---|---|
| +0x04 | map Unique -> `Object*` | **static** doodads: permanent, not blocking |
| +0x10 | map `fineY*(4W+1)+fineX` -> `Object*` | position index of the static doodads (one per vertex) |
| +0x1c | map Unique -> `Object*` | **temporary** doodads: property `lifeTime >= 1` |
| +0x28 | map Unique -> `Object*` | **blocking** doodads: permanent, property `blocking` |
| +0x34 | map fine key -> `Object*` | position index of the blocking doodads |
| +0x40 | byte | initialised |

Object [known] S 00545370, S 00543dc0: +0x08 `id` (Unique, the 64-bit id at +0x10), +0x18 `property`,
+0x1c `finePos`, +0x24 `cell`, +0x2c `lifetime`
(int, ticks left; copied from the property).

### 2.8 `NMap::AStar` (base size 0x48, vtable S 007f89c8)

[known] S 00676cd0: +0x04 `owner` (`NMap::System*`), +0x08 `from`, +0x10 `to`, +0x18 `state`, +0x1c
`AStarNodeLists`: open list (`std::list<AStarNode>`), closed list, and `bestG` (int per cell, -1 = not reached).
`AStarNode` = `{x, y, g, h, f}` (5 ints) [known] S 0067c560.

`state`: 0 = idle (constructor), 1 = grids allocated (set by `NMap::AStar::Init(width, height)` S 006766c0),
2 = path found, 3 = no path, 4 = searching [known] S 00676cd0, S 00676900, S 00676700.

Virtual slots [known] S 00676900, S 00676700: [0] `CanSearch(from, to, arg)`, [1] `GetStepCost(a, b, arg)`,
[2] `PrepareSearch()`. Derived classes: `NResources::AnimalAStar` (+0x48 current animal property),
`NLogic::AStarStreet` (+0x48 state, +0x4c player, +0x50 mode, +0x54 excluded cells, +0x58 own street id),
`NNavy::AStar` (+0x48 `GameQuery*`), `NNavy::ShipRouteAStar`, `NAI::StreetPathAnalyzer`,
`NAI::ConstructionPathAnalyzer`.

### 2.9 `ai::map::FloodFillSearch` (size 0x1c) and `VisitedGrid`

[known] S 0053f080, S 00541ec0: `FloodFillSearch` = `{VisitedGrid*, predicate*, std::deque<MapPos>}`.
`VisitedGrid` (inside `NMap::System` at +0x40) = an int stamp per cell, a generation counter (+0x10) and an in-use
byte (+0x14). A cell is visited when its stamp equals the current generation; each search first increments the
generation, so the grid is never cleared.

---

## 3. Rules and algorithms

### 3.1 Hexagon geometry [known]

**Neighbour step** `MapPos::StepDirection(dir, steps)` S 00675000. Direction table (dx, dy), also in
`docs/map-format.md` §5.1:

| dir | name | even row | odd row |
|---|---|---|---|
| 0 | E | (+1, 0) | (+1, 0) |
| 1 | NE | (0, -1) | (+1, -1) |
| 2 | NW | (-1, -1) | (0, -1) |
| 3 | W | (-1, 0) | (-1, 0) |
| 4 | SW | (-1, +1) | (0, +1) |
| 5 | SE | (0, +1) | (+1, +1) |

The parity is taken from the current row before each single step. The tables (dx at S 00880f28, dy at S 00880f68,
8 ints per parity) carry two more entries, direction 6 = (0, +2) and 7 = (0, -2), for both parities [known, data].
The tables are read by `StepDirection` only [known, xrefs]. The only calls that pass the constant 6 or 7 are in
two map editor tools (S 006021d0, S 006033d0) [known for constant arguments in the cached decompile]; no
gameplay function steps with them [inferred: callers that pass a variable direction were not all traced].

**Distance** `MapPos::HexDistance(a, b)` S 00675040:

```
dx = b.x - a.x;  dy = |b.y - a.y|;  adx = |dx|
if dy is odd:
    if (b.y is even and dx > 0) or (b.y is odd and dx < 0):  adx -= 1
if adx > dy / 2:  return dy - dy / 2 + adx          (integer division)
return dy
```

**Spiral** (used by every "within radius r" loop, for example S 00675f40, S 006746c0, S 00679960): visit the
centre; then for ring = 1..r: step once in direction 4 (SW) from the cell visited last (the centre, later the
south-west corner of the previous ring) without visiting,
then walk `ring` steps in each of the directions 0, 1, 2, 3, 4, 5, visiting the cell after every step. A ring
therefore starts with the cell east of its south-west corner and ends on the south-west corner. Cells outside the
map are skipped but the walk continues.

**Ring only** (for example S 00674ad0): step `r` times in direction 4, then the same six sides.

**Neighbour order of the flood fills** (S 00541ec0): step once SW, then step in directions 0..5 visiting after each
step: the neighbours come in the order **SE, E, NE, NW, W, SW**.

**Neighbour order of A\*** (S 00676700) and of the shore and border tests: directions 0..5 from the cell itself:
E, NE, NW, W, SW, SE.

**Direction between two points** `MapPos::GetHexDirectionTo(from, to)` S 00675090 with `MapPos_GetAngleDegrees`
S 00674f50 [known, disassembly]; it works on grid coordinates (cells or vertices), not on world positions:

```
fx = from.x (+ 0.5 if from.y is odd);  tx = to.x (+ 0.5 if to.y is odd)      (doubles)
if from.y == to.y:  angle = 90 if tx - fx >= 0 else 270
else:
    a = trunc(atan2(from.y - to.y, tx - fx) * 1000 / 3.1415926535 * 180 / -1000)    (toward zero; doubles)
    angle = (90 - a) % 360;  if angle < 0: angle += 360
dir = table[(angle / 60) % 6]      table S 007f8948 = {5, 0, 1, 2, 3, 4}
```

So angle 60..119 gives E, 120..179 NE, 180..239 NW, 240..299 W, 300..359 SW and 0..59 SE; equal points give E.
Callers [known, call graph]: street shaping (§3.4), `NMovement::FinePath::SetTarget`, `NMovie::RotateCatapult::Start`
and three render classes.

### 3.2 Slope class and walking speed [known]

`Elevation_HeightDiffToSlopeClass(d)` S 00675d30, `d` = height(to) - height(from) at the two cell sample vertices:

| d | > 2400 | > 1200 | > 600 | > 200 | -200..200 | < -200 | < -600 | < -1200 | < -2400 |
|---|---|---|---|---|---|---|---|---|---|
| class | 4 | 3 | 2 | 1 | 0 | -1 | -2 | -3 | -4 |

Speed factor of one step from a to b (`Movement_GetSlopeSpeedFactorOnLand` S 0052e250): 1.0 if either cell is
water; otherwise by class(a -> b): 1 -> 0.8, 2 -> 0.6, 3 and 4 -> 0.4, flat or downhill -> 1.0 (S 0052d9e0).
`Movement_GetSlopeSpeedFactorBetweenCells` S 0052dd10 (caller `NMovement::Fine::BeginStep`) is the same table without
the water exemption, but its two arguments are **vertex** coordinates: the heights are read at `y*(4W+1) + x` with no
cell-to-vertex conversion (S 00675f00), so it grades the slope between two fine positions, not between two cells.
Every settler movement owns one cell-grid mover and one fine-grid mover (S 00773450) [known]: a cell step
(`NMovement::Rough::BeginStep` S 00773a40) has the step rate `speed * landFactor(from, to) / HexDistance`, a fine step
(`NMovement::Fine::BeginStep` S 00773ec0) `4 * speed * plainFactor(from, to) / HexDistance`, with `speed` the
value the sacrifice modifier table returns for the settler (S 00663310). When a settler moves on which grid is
`docs/sim/settlers-jobs.md` §3.8. Animals use neither: `NMovement::Base::BeginStep` S 007728d0 takes
`speed / HexDistance` with no slope factor, `speed` being the animal property's `movementSpeed` (virtual slot 10
of `NResources::Movement`, S 00543700) [known]; a step between neighbour cells therefore takes about
`1 / movementSpeed` ticks [inferred].

Round-trip cost of a step (street length, AI path cost): `1/f(a,b) + 1/f(b,a)` as float32 S 0052e320.

**Shallow water** `Map_IsShallowWaterCell` S 0052e550: `depth = minHeight - height(cell)`; true when
`0 < depth <= GameConfig.maxWaterStreetWaterDepth` (`config.lua`: 4000). The limit is read once and cached in a
static.

**Walkable** `Map_IsCellWalkable` S 0052df20: none of the bits 0x1, 0x4, 0x40, 0x100, 0x400.

### 3.3 Deriving grid bits [known]

All in `ai::map::MapCellUpdater`. Whenever one of the bits 0x4, 0x10, 0x200, 0x20000 **changes**, the ground
resource of that cell is reset to `{0, -1}`.

| Bit | Rule | Function |
|---|---|---|
| 0x4 water | set iff `height(cell sample vertex) < minHeight`; the same pass first clears 0x8 on every cell of the rectangle | `RefreshBit2FromElevation` S 0067b390 |
| 0x8 shore | for every water cell of the rectangle: each in-map neighbour (dirs 0..5) that has neither 0x4 nor 0x8 gets 0x8 | `RefreshBit3RingAroundBit2` S 0067b150 |
| 0x10 mining | iff pattern `forMining` | `RefreshBit4FromPattern` S 0067b740 |
| 0x200 buildable | iff pattern `forBuilding` and not `forMining` and not `blocked` | `RefreshBit9FromPattern` S 0067b820 |
| 0x20000 ship ground | iff pattern `forShip` and not `forBuilding` and not `blocked` | `RefreshBit17FromPattern` S 0067b650 |
| 0x1 blocked (whole-map pass only) | made equal to pattern `blocked`, except: a cell with a blocking deposit (bit 0x80 and deposit property `blocking`) is left alone, and the bit is not cleared while a building occupies the cell (layer 1) | `RefreshBit0FromPattern` S 0067b2c0 |
| 0x20 territory border | iff the cell has an owner and at least one of its 6 neighbours is outside the map or has a different owner | `RefreshTerritoryBorderBits` S 0067b910, `IsTerritoryBorderCell` S 0067b5a0 |
| 0x40 cliff | `docs/map-format.md` §5.7 | `CliffMarker` S 0067bdf0 |

Rectangles passed to the water and shore passes are half-open (`x0 <= x < x1`) and clipped per cell.

None of these passes runs on load or at match start; maps carry the bits (`docs/map-format.md` §5.5) [known]. During
play only the following recompute bits [known from the callers in the map]:

- 0x20 after every territory change (§3.6);
- 0x1, 0x10, 0x200, 0x20000 of one cell when its pattern changes (§3.4);
- 0x4 and 0x8 only through `MapModifier::SetVertexElevation` S 006736a0, which is called by the editor paths and
  `NLogic::Edit` only; the gameplay levelling functions of §3.4 write heights directly and **do not** refresh water,
  shore or cliff bits [known for the functions read].

### 3.4 Terrain edits made by gameplay

All edits go through `MapModifier`. Elevation edits inside a batch (`batchDepth > 0`) only grow the elevation dirty
rectangle; when the outermost batch ends, `MapModifier_FlushElevationDirtyRect` S 00672df0 inflates the rectangle by
16 vertices, clamps it and raises `ElevationRectChanged` [known].

**Flag placed** `FlattenAroundCell(cell)` S 00673bd0 (from `NNet::Flag::ctor`): the cell's sample vertex and the 6
vertices around it (vertex ring 1) take the height of the sample vertex [known].

**Level a cell** `LevelVertexDisk(vertex, h)` S 00674100 [known]:

1. every vertex of the vertex spiral of radius 2 around `vertex` is set to `h`;
2. `SmoothElevationRing3` S 00673910: walking vertex ring 3 in ring order, each in-map ring vertex is set to the
   integer average (truncating) of its in-map 6 vertex neighbours. The pass is sequential: a ring vertex sees the
   already smoothed value of the ring vertex before it.

Callers [known]: `LevelCellToAverageHeight(cell, radius)` S 006744f0 (start of bulldozing, `h` =
`Elevations::GetAverageHeightInRadius`) and `LevelCellToCellHeight(cell, refCell)` S 00674560 (bulldozing levels a
neighbour to the height of the building cell). Both then invalidate the construction flags around the cell (§3.5).

`GetAverageHeightInRadius(cell, r)` S 00675f40 [known]: integer mean (truncating; 0 if no cell) over the in-map
cells of the cell spiral of radius `r` of `max(height, minHeight)`, so water counts as the water level.

**Street laid** `SetElevationAlongStreet(cellA, cellB, skipFirst, skipLast, defer)` S 00673370 (from
`NNet::Street::AppendCell`) [known, disassembly]: the two cells are 4 vertices apart; for the up to 3 vertices
between them the centre vertex and its two side vertices (directions `(dir+2) % 6` and `dir-2`) get a height, the
two side vertices the same one; `skipFirst` leaves out the vertex next to A and `skipLast` the centre vertex next
to B (its side vertices are still written); if the direction from A to B (`MapPos::GetHexDirectionTo` on the two
sample vertices, §3.1) is not 2, 3 or 4 the call is repeated with the ends and the two skip flags swapped. With
`dir` in {2, 3, 4} both side directions point back towards A. The heights:

```
hA, hB = heights of the sample vertices of A and B
step = (float32)((hB - hA) * 0.25)
c = (float32)hA;  v = sample vertex of A;  first = 1
if skipFirst:  c += step;  v = v stepped once in dir;  first = 2
for i = first..3:
    prev = c;  c = (float32)(c + step);  v = v stepped once in dir
    if not (skipLast and i == 3):  height[v] = trunc(c)
    s = trunc((prev + c) * 0.5)
    height[v stepped once in (dir+2) % 6] = s;  height[v stepped once in dir-2] = s
```

So the centre line is the linear interpolation `hA + i * (hB - hA) / 4`, accumulated in float32, and each pair of
side vertices takes the mean of its centre vertex and the centre value one step nearer A. The float to int
conversion is the runtime helper `__ftol2_sse` S 006f2af0 (truncation toward zero). Vertices are not tested
against the vertex grid bounds before the write [known for this function]. Each changed vertex joins the elevation dirty rectangle when `defer` is set or a batch
is open; otherwise the function ends by adding both sample vertices to the rectangle, raising
`ElevationRectChanged` with it (no 16-vertex inflation) and emptying it. Water, shore and cliff bits are not
refreshed (§3.3).

**Pattern change** `SetCellPattern(cell, pattern, defer)` S 00674360 [known]: no-op if equal. Otherwise: if the
`blocked` flags of old and new pattern differ, bit 0x1 is set to the new flag; the pattern is stored; bits 0x10,
0x200, 0x20000 are refreshed if the respective pattern flag differs (resetting the ground resource on a change,
§3.3); then either the cell joins the cell dirty rectangle (`defer`) or `CellRectChanged` is raised and the
construction flags around the cell are invalidated. In play the caller is `NMovie::Working::Update` (sowing, §3.9);
Lua has `map.exchangePatternType` -> `ExchangePatternInRect` S 00674470.

`MapModifier_FlushDirtyRects` S 006730e0 (editor, `NLogic::Edit`, `ExchangePatternInRect`) [known]: elevation
rectangle inflated by 16 vertices -> `ElevationRectChanged`, cliff bits re-resolved for the covered cells,
construction flags of the covered cells recomputed; cell rectangle -> `CellRectChanged`, then the rectangle is
extended by the points (minX-4, minY-4) and (maxX-4, maxY-4) (so it grows by 4 cells only towards the origin) and
the construction flags inside are recomputed.

### 3.5 Buildability: the construction flags

`ConstructionMap_ComputeCellFlags(cell, player)` S 00675610 [known]:

1. probe `GameQuery::CanPlaceBuildingAt` with size 4, then 2, then 1, then 8, then 16; the first success stores
   7, 3, 1, 8, 16 respectively; no success stores 0;
2. add 0x20 if `GameQuery::CanPlaceFlagAt(cell, player)`;
3. if bit 0x1 is set and `HasNoTerritoryBuildingWithinRadius4` S 0052dc30 holds, add 0x40. That test walks the
   in-map cells of the spiral of radius 4 and fails on the first cell that is the anchor of a building (layer 1,
   S 00558890 with radius 0) whose property has a base territory radius > 0 (building property +0x94).

The predicate itself is `docs/sim/village-buildings.md` §3.1. `CanPlaceFlagAt` S 0052f8a0 [known]: the cell is a
free owned cell (`IsOwnedCellFree` S 0052f3d0: territory of the player, none of 0x1, 0x80, 0x100), no flag on the
cell or its 6 neighbours (layer 0), and none of the 6 neighbours has the harbor bit 0x2000.
`IsPlayerTerritoryCell(cell, player, allowWater, allowBorder)` S 0052f270 [known]: the cell is inside the map, has
none of the bits 0x40 (cliff) and 0x400 (logic object), not 0x4 (water) unless `allowWater`, not 0x20 (territory
border) unless `allowBorder`, and its territory owner equals the player. `IsOwnedCellFree` passes `allowWater` =
false and its own `allowBorder`; the construction-flag computation passes `allowBorder` = false, so a flag cannot
stand on a border cell.

When the flags are recomputed [known]:

| Trigger | Area | Function |
|---|---|---|
| a map-changing event at a cell (deposit created or removed, flag or street added or removed, building placed or removed, spawn placed, ship tile marked, pattern or level change) | spiral radius 4 around the cell | `MapUpdateBatch::InvalidateConstructionAroundCell` S 00532400 |
| territory source added or removed | spiral radius `radius + 4` | `MapModifier::OnTerritoryChangedAt` S 00673a50 |
| full territory recomputation, editor passes | whole map | `ConstructionMap_RecomputeAll` S 00675790 |
| after a map is loaded for a match | whole map | `MapModifier_InitAfterMapLoad` S 00673000 |

Batching (`MapUpdateBatch::InvalidateConstructionRadius` S 005322b0) [known]: while a batch is open
(`counter < 1`) the cells of the area only grow `constructionDirty`; with no batch open the area is recomputed at
once. `MapUpdateBatch_End` S 005321c0, when the outermost batch closes: remove obstructed doodads inside
`doodadDirty` (or all, if `fullDoodadRefresh`), recompute the construction flags inside `constructionDirty` (or
the whole map, if `recomputeAll`), and rebuild the continents if `rebuildContinents`.

Recomputation always covers **all active players** (slots 0..7, `Player.bActive`) [known] S 00675880. Iteration
order: players outer; rectangle: x outer, y inner; radius: spiral order. The order does not matter for the result
because the predicate does not read the construction map [inferred].

### 3.6 Territory

A **territory source** is `{x, y, player, radius}` [known] S 0067a260. Sources are not stored: they are collected
from the buildings whenever needed.

`Territory_CollectSources(pos, radius)` S 0067a030 [known]: all buildings within `radius * 3` of `pos`
(`NVillage::System::CollectBuildingsInRadius`), except a building whose anchor is exactly `pos`, that have
`Military::GetTerritoryRange() > 0` and an active `TerritoryUpdater`; each contributes its anchor, owner index and
that range. The collector S 00559820 walks the village system's building vector from first to last and keeps
every building with `HexDistance(anchor, pos) <= radius * 3`, so the sources come in the order of that vector
(placement order, `docs/sim/village-buildings.md` §8) [known]; this order decides rule 1 below when two enemy
sources are both nearer than 3.

**Owner of a cell** `Territory_ComputeCellOwner(cell, sources)` S 00679510 [known]:

1. walk the sources in list order; the first source with `HexDistance(source, cell) < 3` wins at once;
2. otherwise, per source: `r = radius`, doubled if `dist < 5`; if `dist <= r`:
   `influence[player] = max(influence[player], (float)r / (float)(dist*dist))` (float32);
3. the owner is the player with the highest influence > 0; on equal influence the lowest player index wins
   (strict `<` while scanning 0..7); nobody -> -1.

**Adding a source** `MapModifier::AddTerritorySource(cell, radius, player, notify)` S 00673af0 [known]: if
`radius != 0`: the list is the new source first, then the collected ones; `Territory::RecalcArea` S 00679960
recomputes the owner of every in-map cell of the spiral of radius `radius` around the cell. Then
`OnTerritoryChangedAt(cell, radius)`:

1. border bits (0x20) in the cell square `[x-(radius+2), x+(radius+2)) x [y-(radius+2), y+(radius+2))`;
2. construction flags within `radius + 4`;
3. `TerritoryChanged` to the listeners;
4. `NNet::System::RemoveForeignStreetsInRadius(cell, radius + 4)`;
5. `NVillage::System::MarkBuildingsOutsideTerritoryNear(cell, radius + 4)` (`docs/sim/village-buildings.md` §3.14).

All five steps are skipped while `MapModifier.bEnabled` (+0x00) is 0; the owner grid itself is recomputed in
either case. The same byte gates `RefreshTerritoryAll` below [known] S 00673a50, S 00672eb0. [TODO] not
established: who clears the byte (the constructor sets 1; find the byte writes at `MapModifier + 0`).

**Removing a source** `RemoveTerritorySource(cell, radius, owner)` S 00673b20 [known]: collect the remaining sources
and recompute the same spiral, without notification; then the same five steps. The building being removed is
skipped by the collector because its anchor equals `pos`.

Only the spiral of radius `radius` is recomputed, although rule 2 lets a source with `radius < 5` reach up to
`2 * radius` at distances below 5; such cells change owner only when another recomputation covers them [inferred].

**Lost territory message** [known] S 006797f0: during a recomputation every player who owned a cell that now has a
different owner is flagged; with `notify` set, each flagged player gets the message `!Lost Territory.` (category 1,
empty text, at the source position) unless an identical message near that position is still pending.

**Full recomputation** `Territory::RecalcAll` S 0067a3b0 -> `RecalcFullMap` S 00679ac0 (x outer, y inner), then
`MapModifier::RefreshTerritoryAll` S 00672eb0: border bits of the whole map, whole construction map,
`TerritoryChanged`, `RemoveStreetsOutsideTerritory`, buildings outside territory. Caller chain [known]:
`ai::map::MapModifier::RecalcTerritoryAll` S 00672f10 <- `Logic_RecalcTerritoryForPlayer(player, enable)` S 00538d10 (anchor =
the player's first building, or (-1, -1)) <- the start and stop of a sacrifice's toggle effects (S 00661cf0,
S 00661d60); S 00672f10 has no other caller. Neither argument changes the source list [known] S 0067a3b0,
S 00679ac0: `RecalcAll` always collects with `pos` = (0, 0) and radius 0x7fffffff, that is every building of every
player with a positive territory range and an active `TerritoryUpdater` (the collector's exclusion then only hits
a building anchored on cell (0, 0)); the anchor is only the position of the lost-territory message and `enable`
is its `notify` flag. The effect of the sacrifice comes from the range itself: the `Effect_ExpandTerritory` value
is part of `Military::GetTerritoryRange` (`docs/sim/village-buildings.md` §3.14). With `enable` set, S 00538d10
afterwards also calls `TerritoryUpdater::Refresh` for every territory building of that player
(`NVillage::System::RefreshTerritoryForPlayer` S 00558800).

**First border contact** `MapModifier::DetectTerritoryContacts(center, radius, player)` S 00674ad0: described in
`docs/sim/players-victory.md` §3.5; it walks ring `radius + 1` twice (count foreign cells per owner, halve, then
mark the contact at the cell where the countdown passes below zero) [known].

### 3.7 Exploration (fog of war)

`MapModifier::ExploreArea(center, radius, player)` S 00674800 [known]:

1. for every active player slot `p` (0..7) that is **not an enemy** of `player` (`!Player::IsEnemyOf`; this includes
   `player`): `Exploration::RevealHexArea(center, radius, p)` and `PlayerRectChanged(rect, p)` with the rectangle
   `center +- (radius + 1)` clamped to the map;
2. then for every in-map cell of the spiral that has a territory owner and a building (layer 1): every active
   player who has that cell explored gets `spotted[owner] = 1` (`ai::player::Player::SetPlayerSpotted`).

`RevealHexArea` S 00677570 [known]: sets the byte of every spiral cell that satisfies `0 < x < W-2` and
`0 < y < H-2`. Column 0, the last two columns, row 0 and the last two rows are never explored.

Queries [known]: `Exploration::IsExplored(cell, player)` S 00542b10; `HasUnexploredInRadius(center, player, r)`
S 00677670 (true if any in-map spiral cell is 0; used by soldiers and ships to decide whether to explore).

Callers of `ExploreArea` [known, call graph]: `NVillage::TerritoryUpdater` (building explore radius, for example
`bp_setExploreRadius(castle, 12)`), `NSettlers::Soldier::Update`, `NNavy::Ship::Update`,
`NNavy::Expedition::Update`, harbors, three sacrifices, `Game_CreatePlayersFromDescriptor`,
`NLogic::System::SetPlayerTeam`, Lua `map.exploreArea`, a debug key.

What exploration gates in the simulation [known]: hunters only target animals standing on a cell their player has
explored (S 00542c40); foresters and geologists only search through explored cells (S 0077e5c0, S 0077e6d0).
Everything else is presentation (§4.3).

### 3.8 Ground resources

**Where a resource may lie** `CanHoldResourceAtCell(cell, type)` S 00674210 [known]: on a water cell only `fish`
(0x4012e5a3), and only if one of the 6 neighbours is a shore cell (0x8); on a land cell never fish, and any other
type only if the cell has the mining bit 0x10.

**Add** `AddResourceAtCell(cell, type, n)` S 006745e0 [known]: if the cell may hold the type: an empty cell takes
the type; if the cell's type equals `type`: `amount = min(7, (amount == 1000 ? 7 : amount) + n)`. A cell with
another type is left alone. Adding to an unlimited cell makes it limited (7).

**Consume one unit** `ConsumeResourceAtCell(cell, type)` S 00674650 [known]: only if the cell holds `type` and the
amount is not 1000: `amount = min(7, amount - 1)` if positive; at 0 the type becomes -1.
`ConsumeAnyResourceAtCell(cell)` S 00674e70: the same with the cell's own type; returns true if a resource remains
afterwards (or it is unlimited), false if the cell was or became empty.
`ConsumeResourceNear(cell, radius, type)` S 006746c0: the first cell in spiral order within `radius` holding `type`
loses one unit; returns whether one was found.

**Mines** [known for the calls; the production side is `docs/sim/village-buildings.md` §3.9]: a mine links the
nearest cell whose resource type equals the **mining good** of its product (good property +0xbc, §2.3) within
its working radius (`Resources_FindNearestMapResourceCell` S 00540660: breadth-first, limited by hex distance
only, not by walkability, S 00542970). Each use calls
`ConsumeAnyResourceAtCell(linked cell)` (S 0055c860, called from `NVillage::Production::OnProductionFinished`
S 00565f80 and from `NMovie::Working::Update` mode 3); when it returns false the link is reset to (-1, -1) and the
building searches again on its next search tick. `OnProductionFinished` [known] S 00565f80: a building whose
property has the training byte +0xf1 finishes a training instead; otherwise, **only** for a building with property
`size == 8` (`SizeMine`) and `workingMode == 6` (`Producing`), one unit is consumed from the linked cell, and
when that returns false the cycle ends **without delivering products**; every other building, and a mine whose
consumption returned true, delivers its products. The function has no food test: whether a cycle starts at all
(food, `MinerNeedNoFood`) is decided earlier (`docs/sim/village-buildings.md`). Because the test is "a resource
remains afterwards", the cycle that takes the last unit of a cell delivers nothing: a mine gets
`min(n, 8) − 1` products out of a cell with amount `n` [known] S 00674e70, S 0055c860, S 00565f80. The fisher's
call in `Working::Update` mode 3 ignores the result [known] S 0077ebf0.

**Fish** [known]: a fisher's `LookForFishing::Start` S 0077f670 flood-fills from the cell north-east of the hut's
anchor through walkable cells within the working radius (measured from that start cell, which must be walkable
itself, S 007802c0) and collects every **shore** cell that has at least one
fish cell (type 0x4012e5a3) within `fishingDistance` (`config.lua`: 1) (S 00780300); one candidate is chosen with
`LogicRandom % count`; then the nearest cell within `fishingDistance` of that spot that holds the mining good of
the hut's first product is stored in the building's field connection. With no candidate, production enabled
and productivity < 0.5: message `!No resources found.`
(category 3). After the work animation (`Working::Update` mode 3, S 0077ebf0): with a linked cell
`ConsumeAnyResourceAtCell(link)`, otherwise `ConsumeResourceNear(settler cell, fishingDistance, mining good of
the product)`.

**Regrowth** [known] S 005390e0: a resource spawn point adds 1 unit of its first resource id to every in-map cell
of the spiral of its radius (`AddResourceAtCell`, so only cells that may hold it and are empty or of that type).
The shipped `spawnpoints.lua` defines only animal spawn types (12 x `SpawnType_Animal`) [known, data].

**Geologist** ("scholar" in the code) [known]:

1. `SearchScholarDiggingPosition::Start` S 007794b0: flood fill from the settler's cell through cells that are
   walkable and explored by the owner; the visitor collects cells accepted by `IsCellDiggableByScholar` and stops
   the search as soon as one candidate exists or a visited cell is farther than 5 from the start. One candidate is
   chosen with `LogicRandom % count` (in practice the first accepted cell).
2. `IsCellDiggableByScholar` S 0052dfa0: mining bit 0x10 set; none of 0x1, 0x80, 0x400; no flag (layer 0) and no
   dig reservation (layer 4) on the cell; and `FindDoodadAtCell(cell, 1)` finds nothing, that is no **temporary**
   doodad whose property `type` is 1 (`doodad_Type_Sign`, `doodads.lua`) stands on the cell's sample vertex. Other
   doodads and the neighbour cells are not tested, so a cell is dug again once its sign has expired.
3. The chosen cell is reserved in layer 4 while the settler walks and digs (`GoDigging` S 0077b0f0, S 0077b130).
4. Result `PlaceResourceSignAndNotify` S 0077b2f0: read the cell's `{amount, type}`; amount 1000 counts as 7; if
   the cell has the buildable bit 0x200 the result is forced to `water` (0xa9676263), amount 1; the sign doodad from
   the sign table for (type, amount) is created on the cell; if a type was found the owner gets the message
   `!Found Resource` (category 2, argument = the good's name), or an identical pending message within 7 cells has
   its timer reset to 600.
5. `digsRemaining` is decremented (forced to 0 when the home building's production is disabled); while it is
   positive the search repeats.

Sign thresholds in `signs.lua` [known, data]: 1 = S, 3 = M, 6 = L, 1000 = X per resource; (-1, 0) = empty sign;
(water, 1) = water sign. Because 1000 is mapped to 7 before the lookup, the X signs cannot result from this path,
and because a diggable cell needs bit 0x10 while a pattern with `forMining` never gets 0x200, neither can the
water sign as long as both bits agree with the cell's pattern [inferred; the bits are stored per cell and
`SetCellPattern` refreshes 0x200 only when `forBuilding` changes, §3.4].
Sign doodads have `lifeTime` 3000 (one has 30000), `deleteByStreet` false and type `doodad_Type_Sign`
[known, `doodads.lua`].

### 3.9 Deposits

**Creation** [known]:

- `System::CreateDeposit(type, cell, full)` S 00540b40 -> `Deposit::ctor_AtCell` S 005432d0: new Unique;
  `ttlWithoutOwner = property.lifeTime`; **one `LogicRandom` draw**: `dir = rnd % 6`, the display position is the
  cell's sample vertex stepped once in `dir`, used only if it is inside the vertex grid and the property has
  `randomFinePosOffsetState`, else the sample vertex itself (the draw happens in both cases); register in layer 3;
  set grid bit 0x80, and 0x1 if the property is `blocking`. `growth` stays -1.0 unless `full` (then 1.0). The deposit
  joins `deposits` and `depositById`, and `activeDeposits` if `depletedTicks != 0 || growth < 1.0 || ttl >= 0`.
  Then: doodads obstructed at the display position are removed (§3.11) and the construction flags around the cell
  are invalidated.
- `System::AddDepositFull(type, cell, finePos)` S 00540aa0 (next harvest stage): explicit display position, no
  random draw, `growth = 1.0`, never put on the active list by this function.
- Destruction (`Deposit::dtor` S 005430a0) clears layer 3, bit 0x80 and, for blocking types, bit 0x1, and unlinks
  the reserving building.

**Placement rule** `GameQuery::CanPlaceDepositAt(cell, property)` S 0052eb10, S 0052e150 [known]: no flag on the
cell; none of the bits 0x2, 0x4, 0x8, 0x40, 0x80, 0x100, 0x400, 0x2000; the cell's pattern is not `blocked`, not
`forMining`, not `forShip`; if the deposit type has tree types the pattern's `treeType` must not be -1; if the type
has `needForPlantablePattern` the pattern must be `forPlanting`. `CanPlaceDepositWithClearance` S 0052ef40 also
requires that neither the cell nor its 6 neighbours is blocked (0x1).

**Per tick** `Deposit::Update` S 005431a0, for the deposits on the active list only [known]:

1. if `growth < 1.0` and `growth >= property.growingStartSize`: `growth += property.growingSpeed` (float32);
2. if `depletedTicks == 0`: if `ttlWithoutOwner > 0` and no building reserves the deposit: decrement it; at 0 the
   deposit is marked depleted (`depletedTicks = 1`, the "disappearing" event is raised if `growth >= 0`);
3. else `depletedTicks += 1`.

`System::Update` S 00540340 then [known]: a deposit whose `depletedTicks == 20` is queued for removal; a deposit
that is not depleted, has `growth >= 1.0` and `ttl < 0` is dropped from the active list; all others stay. After the
pass the queued deposits are removed (`RemoveResource` S 0053f2a0, last queued first), each invalidating the
construction flags around its cell. A depleted deposit therefore lives for 19 more updates [inferred].

**States of a deposit** [known] S 00542a10, S 0053e860:

| Condition | Meaning |
|---|---|
| `growth == -1.0` | just planted, not yet sown; does not grow |
| `growingStartSize <= growth < 1.0` | growing |
| `growth >= 1.0 && depletedTicks == 0` | available (`IsAvailable`) |
| `depletedTicks != 0` | being removed; ignored by every search |

**Finding a deposit** `Resources_FindNearestFreeDeposit(pos, good, radius)` S 00540870 with
`FreeResourceSearch` S 00542a30, S 00542b60 [known]: breadth-first from the building anchor. The key is the
**mining good** of the wanted good (good property +0xbc, §2.3). A cell is a hit when it is within `radius`, holds
a deposit whose property `good` equals that key, no building reserves it, it is available, and, for the keys
`wood` (0xcd6ec133) and `stone` (0x55e952d3), it has no running `ttl` (`ttl < 0`).
The search steps onto a deposit cell (without cliff bit) from a walkable cell or from the start cell; any other
cell must be walkable and within `radius`. The found deposit is linked to the building, which sets
`reservingBuilding`.

**Work result** `NMovie::Working::Update` S 0077ebf0, by the workplace's `workingMode` (building property +0x80)
[known]:

| Mode | Action when the work animation ends |
|---|---|
| 0 | **sow**: if the deposit type has underground patterns, one is chosen with `LogicRandom % count` and set as the pattern of the deposit's cell (`SetCellPattern`); then `growth = growingStartSize` and the "deposit shown" event is raised (`Deposit::ResetAmountFromProperty` S 00542da0, whose only other caller is Lua `map.createDeposit` S 005ad7e0) |
| 1 | **harvest**: unlink the deposit from the building, `HarvestDepositAt(cell)` |
| 2 | **farm**: if the linked deposit is available: as mode 1; otherwise as mode 0 |
| 3 | ground resource (§3.8) |

`Working::Start` S 0077eda0 [known]: if the linked deposit is available and its property's good is `wood`,
`SetDepositTtl(deposit, (int)workDuration + 5)` puts it on the active list with that countdown. The animation is
kind 5 instead of 4 for a mode-2 building whose deposit is not available (sowing instead of reaping).

**Harvest** `System::HarvestDepositAt(cell)` S 00540c40 [known]:

- property has **no** `nextDeposit`: mark depleted and put on the active list (removed 19 updates later); if the
  property has `doodadAfterDestruction`, create that doodad at the deposit's display position;
- otherwise: remove the deposit at once and, inside a map-update batch, create the successor type at the same cell
  and display position with `growth = 1.0`.

**Planting** `NMovie::GoAfforest::Start` S 0077bcb0 [known]: requires production enabled (and, for a building whose
production reports the flag of S 00565550, `Production::CanStartProduction`; the flag is true when slot 0 of the
building property's product list is set and the property is not a catapult, `bp_setCatapult`, property +0xb0,
`docs/sim/properties-data.md`); `LookForEmptyPlace`
S 00779330 flood-fills from the building anchor through walkable, explored cells and collects cells within the
working radius where `CanPlaceDepositWithClearance` holds for the building's planting deposit type; it stops at 11
candidates or when a visited cell is farther than radius + 4; one candidate is chosen with `LogicRandom % count`.
A place is chosen **only when the flood fill was stopped** by one of these two conditions: if the reachable area is
exhausted first (the queue runs empty with fewer than 11 candidates and no cell beyond radius + 4), the search
fails, no random number is drawn and nothing is planted, even if candidates were collected (S 00779330, S 0077e660).
The deposit type is the building's planting type, or, when that type has tree types, a random type for the cell:
`Afforest_PickRandomDepositForCell` S 0077bb30 draws `LogicRandom` once and picks, among all deposit types (in the
iteration order of the deposit property map, S 005477e0: ascending id compared as a **signed** 32-bit int, so the
hashes with the top bit set come first [known for the map's find S 00546c70, which compares the keys as signed
ints; inferred for the insert]) whose `treeTypes` contain both the cell pattern's `treeType` and `mapTreeType`,
the `rnd % count`-th (unsigned modulo); -1 if none. The deposit is created with
`CreateDeposit(type, cell, full = false)` and linked; the worker walks to it and runs `Working` (mode 0 sows it).
If the walk cannot start the deposit is removed again (S 0077bc50).

**Data** [known, `deposits.lua`]: 53 types. Trees: good `wood`, no next stage, default growth 0.1 start and 0.0009
per tick (1000 ticks to full). Stone piles: good `stone`, `stone_06 -> stone_05 -> ... -> stone_01` by
`dp_nextDeposit` (the same for `med_stone_*`), blocking, no random offset, underground pattern `pattern_meadow2`.
Fields: `field_01` (good `corn`, start 0.2, speed 0.00075: 1067 ticks; lifetime 3000; blocking; underground
`pattern_acre`; needs a plantable pattern) and `field_egypt` (good `egyptCorn`, speed 0.0005: 1600 ticks). One
more type, `tent` (good `good_helper`, start 0.01, speed 0.1, blocking). `dp_setDoodadAfterDestruction`
is not used by the shipped data.

### 3.10 Animals

**Creation** `System::SpawnAnimal(type, cell)` S 00540f40 -> `Animal::ctor_Spawn` S 005418e0 [known]: `home` =
cell, state 0, `counter = LogicRandom % n` (one draw, signed division), registered in `animalById`, in
`AnimalAreas` (by home) and through its movement in `animalsByCell`. `n = trunc((float)moveDistance / movementSpeed
* idleTimeFactor)`, computed on the x87 stack from the property's float32 values and truncated toward zero
(S 00541994..005419ac); with the shipped data (idle factor 3.0 by default) a deer gets `2 / 0.045 * 3` -> 133 and a rabbit
`4 / 0.07 * 3` -> 171 [inferred from `animals.lua`].

Callers [known]: animal spawn points (`NLogic::SpawnAnimal::Spawn` S 00538f40: only if the spawn's low-res block
holds at most 4 animals; one `LogicRandom` draw picks the animal type from the spawn's list; the new animal gets
state 6), `NSettlers::Worker::Update` (also state 6) and the editor.

**States** (`Animal::Update` S 005420c0, once per tick; its first statement runs `NMovement::Base::Update` on the
animal's movement, in every state) [known unless noted]:

| State | Behaviour | Left by |
|---|---|---|
| 0 idle | `counter -= 1`; below 0: `counter = -1`, state 1 | |
| 1 wants to roam | see "roam scheduling" below | search success -> 2; failure -> stays 1 with `counter = 100` |
| 2 walking | when the movement's step progress float (Animal +0x4c) is **negative** (the test is `< 0`, not `<= 0`). The movement is then at rest: `NMovement::Base::Update` S 00772950 resets the progress to -1.0 when the last step of the path completes (S 007749f0), while `StartMoveTo` S 00772b00 sets 0 and a running step is >= 0. Then: if it is the only animal on its cell `counter = (int)((float32)(tick/10 - timeStamp) * idleTimeFactor * 10.0)` (property `+0x4c`, 3.0 in the shipped data; the difference is stored as float32 before the two multiplications, truncation toward zero) [known] S 0054231f..0054235e, else `counter = 0`; state 0. The animal then stays in state 0 for `counter + 1` ticks, so with the factor 3.0 it idles three times as long as its walk took: a long walk is followed by a long idle [known: live 2026-10-12, 400 arrivals, 295 with a counter, all matching within 1] | |
| 4 linked by a hunter | no behaviour in `Update` (a step in progress still finishes, the movement is updated in every state); still huntable by the test of `IsAliveAndUnreserved` once the reservation is gone | set by `NVillage::Building::SetHuntedAnimal` S 0055c3a0 (`counter` untouched); no code read sets it back |
| 5 dying | `counter += 1`; at `dyingTime` -> state 7 | set by `NMovie::GoHunting::Update` (S 00541b00, `counter = 0`) |
| 6 just spawned | steps one cell north-east: `StartMoveTo(current + dir 1)` (-> state 2) and `timeStamp += 0.1 / movementSpeed` | |
| 7 dead, waiting for the pickup | no behaviour in `Update` | set from state 5; left only through the pickup (state 8) or by being erased |
| 8 disappearing | `counter += 1`; at `disappearingTime` `Update` returns true and the system erases the animal | set by `NMovie::PickupProduct::Start` (S 00541b30, `counter = 0`) |
| 9 destroyed | none: written by the destructor S 00541a00 as its first statement, so that the unlink it calls sees a dead animal | |

`StartMoveTo(target)` S 00541b50: `timeStamp = (float)tick / 10`, movement target = `target`, state 2.

**Roam scheduling** (state 1) [known]: at most 2 roam searches run per tick, and the animal that waited longest goes
first:

```
if system.roamSearchesThisTick > 1:  counter += 1; return
if system.roamTurn < counter:        system.roamTurn = counter; return
if system.roamTurn != counter:       counter += 1; return
system.roamTurn = 0;  system.roamSearchesThisTick += 1;  run the search
```

**Roam search** (`AnimalRoamSearch` S 00543950, S 00543900, S 005439b0; flood fill S 00541ec0) [known]:

- start = the current cell, or `home` if `HexDistance(home, current) > range`;
- `countdown = LogicRandom % (3 * d * (d + 1)) + 1` with `d = moveDistance` (one draw);
- a cell can be entered if it is within `range` of `home` and walkable (the start cell is exempt from the
  walkability test);
- a visited cell is skipped if it has bit 0x10 (mining ground) or 0x20 (territory border) or already holds an
  animal; with `avoidBuildings` it is remembered as fallback and skipped if any in-map cell of the spiral of
  radius 2 around it (the cell itself included) holds a building in layer 1 (spiral iterator S 00600e90);
  otherwise it becomes the target and `countdown -= 1`; the search stops when `countdown < 1`;
- result = the last target, else the fallback; with neither `counter = 100` and the animal stays in state 1.

The path is found by `NResources::Path::FindPath` S 00543b20 with the shared `AnimalAStar` (§3.12) and built with
`randomize = true`.

**Cell index** [known] S 00543890: whenever the movement reaches a cell the animal is registered on the cell it
occupies (the next cell while a step is in progress, else the current cell).

**Hunting interface** [known]: `FindHuntableAnimalAt(cell)` S 0053ee60 returns the first animal on the cell (vector
order) with state not in {5, 7, 8, 9} and no hunter reservation. `Resources_FindNearestHuntableAnimal` S 005407a0
flood-fills through walkable cells within the radius; a hit also needs a non-empty stack-good list for the hunter's
tribe (`an_addStackGood`) and a cell explored by the hunter's player. The exploration test reads Animal +0x38,
the **target cell of the animal's walk** (`NMovement::Base` +0x0c: the spawn cell at construction, then the
destination of the last started walk, S 00772b00), not the visited cell: an animal standing on or walking through
an explored cell is not a target while its destination is unexplored, and the reverse [known] S 00542c40.
`PopStackGood` S 00541bc0 hands out the goods of the tribe's list one per pickup; `IsStackFull` S 00541ba0 is true
when all were taken.

**Hunter sequence** [known unless noted]:

1. **Link.** `NVillage::Building::UpdateHuntTargetSearch` S 0055c050 (the search timer is
   `docs/sim/village-buildings.md` §3.9): a building with `workingMode == 7` and no linked animal takes the result
   of `Resources_FindNearestHuntableAnimal(owner, anchor, workingRadius)`. `VillageLink_LinkHuntedAnimal`
   S 0053c550: animal state 4, the building's animal reference (+0x70) = the animal, the animal's `hunter`
   reference = the building. The reservation keeps other hunters off it.
2. **Kill.** `NMovie::GoHunting::Update` S 0077cba0 (steps 7 look for the animal, 8 leave the building, 9 walk to
   the animal, 10 work; `docs/sim/settlers-jobs.md`): when the walk of step 9 ends and the building's animal
   reference is no longer valid, the sequence ends there; otherwise the animal gets state 5 with `counter = 0`
   unless it is already dead (state 5, 7, 8 or 9, S 0053bda0 [known]), and step 10 runs the work animation.
3. **Dying.** State 5 turns into 7 after `dyingTime` updates (table above).
4. **Pickup.** `NMovie::PickupProduct::Start` S 00777f80, for a building with `workingMode == 7` whose own stock
   holds no ware: the good is the property's first product, and if the animal reference is valid: unless all
   stack goods were taken already, `PopStackGood` for the tribe of the building's owner replaces the good; then,
   if all are taken, the animal gets state 8 with `counter = 0`. The function does not test the animal's state
   (it may still be 5).
5. **Removal.** State 8 ends after `disappearingTime` updates: `Update` returns true and the system erases the
   animal. The destructor S 00541a00 sets state 9 and, while a hunter reference exists, calls
   `VillageLink_UnlinkHuntedAnimal(building, animal, erase = false)`, which clears both references, so the
   building searches again.
6. **Abort.** `NSettlers::Worker::UpdateHuntingJob` S 0065c610: when the hunting sequence ended on a step other
   than 10 and the building still has an animal reference, and likewise when the building is destroyed
   (S 0055ce70): `VillageLink_UnlinkHuntedAnimal(building, animal, erase = true)` S 0053c580 clears both
   references and **erases** the animal if its state is 5, 7, 8 or 9. An animal still in state 4 is kept and stays
   in state 4: unreserved and huntable again, but it never roams again [inferred: `Update` has no case 4 and the
   only state reset, S 00541ad0 (state 2 if the step progress is >= 0, else 0), is reached with `erase = false`,
   which only the destructor passes].

With the shipped data each animal type yields one good per tribe that has an entry, so the first pickup already
moves the animal to state 8 [inferred from `animals.lua`].

**Data** [known, `animals.lua`]: 12 types; `range` 6 or 8, `moveDistance` 2 or 4, `movementSpeed` 0.03..0.07,
`avoidBuildings` true for all; base stack `bavarians -> leather`, `egyptians -> goatHam`; sheep: `scots -> sheep`,
`respawn` false, `dyingTime` 1, `disappearingTime` 5.

### 3.11 Doodads

**Adding** `System::AddDoodadAtFinePos(type, finePos)` S 00544e00 [known]: the object gets a new Unique; its cell is
the nearest cell to the vertex (`FinePos::ToNearestPatternCursor` S 00675500; fallback: the vertex-to-cell formula
of §2.1 clamped to the map); a `blocking` type is snapped to the cell's sample vertex. Then by property:
`lifeTime >= 1` -> temporary map; else not `blocking` -> static map and index; else -> blocking map and index and
**grid bit 0x400 on its cell**. `AddDoodadAtCell` S 00545150 uses the cell's sample vertex.

**Per tick** `System::Update` S 005446c0 [known]: for every temporary doodad in ascending id order: `lifetime -= 1`
if positive; remove it if `ShouldBeRemoved`.

**`Object::ShouldBeRemoved`** S 005454f0 [known]:

1. `indestructable` -> never;
2. removed if any of: (`deleteByStreet` and the cell has the street bit 0x2); the cell has the building bit 0x100;
   the cell has the deposit bit 0x80 and the deposit's display position equals the doodad's vertex; a flag stands on
   the cell (layer 0);
3. otherwise removed iff `lifetime == 0` (permanent doodads carry -1 and stay).

**When static doodads are checked** [known]: not per tick. `RemoveObstructedInRect(cellRect)` S 00544b70 runs when a
map-update batch closes (the batch's doodad rectangle converted to vertices with a 2-vertex margin: every static
doodad indexed there, then the temporary ones whose **cell** lies in the cell rectangle). The conversion
S 00676620 builds the vertex rectangle from the two corners `(4*minX (+2 if minY is odd) - 2, 4*minY - 2)` and
`(4*maxX (+2 if maxY is odd) + 2, 4*maxY + 2)`; when the first corner has a negative x (a cell rectangle that
starts in column 0) it is dropped and the vertex rectangle is the second corner alone, so only that one vertex
is checked for static doodads [known]. `RemoveObstructedAtFinePos` S 00544ad0 (the static doodad on that vertex,
then the temporary ones on it) is requested when a deposit is created (S 00532140): with no batch open it runs
at once, inside a batch it only sets `fullDoodadRefresh`, so the closing batch checks every doodad
(S 005321c0). Blocking doodads are never removed by these checks [known: neither function looks at the blocking
index].

**Removal** `RemoveDoodad(id)` S 00544480: from whichever map holds it; a blocking doodad clears bit 0x400 [known].

**Lookup** `FindDoodadAtCell(cell, typeOrZero)` S 00543dc0 [known]: every test compares with the cell's **sample
vertex**, so a doodad drawn on another vertex of the cell is not found. The temporary map is always scanned
linearly (ascending id) for a doodad on that vertex whose property `type` (+0x44, `dd_setType`) **equals the
argument**. With 0 the static index is consulted first and the blocking index last, and the scan in between
therefore only finds temporary doodads of type 0 (`doodad_Type_Landscape`); the shipped temporary doodads are all
signs (type 1), which a lookup with 0 does not return [inferred from `doodads.lua`]. With a non-zero type only the
temporary scan runs.

**Sources of doodads in play** [known, call graph of S 00544e00 and S 00545150]: geologist signs, ruins removal
(`NVillage::System::RemoveRemains`), the settler skeleton (`NSettlers::Settler::Update` S 00656ec0, only if no
doodad is on that vertex yet; `cfg_setSettlerSkeletonDoodad`), deposit destruction, Lua `map.createDoodad`. The
chest ids (`cfg_setChestDoodadId`, `cfg_setOpenChestDoodadId`, GameConfig +0x44, +0x48) create no
`NDoodads::Object`: their only readers are the scene's chest handlers S 006819e0, S 00680c80, S 00681aa0, which
use them as model ids [known for the cached decompile].

**Data** [known, `doodads.lua`]: 168 types; 26 with a lifetime (all signs), 19 blocking, 1 indestructible.

### 3.12 Path-finding: A*

`AStar::FindPath(from, to, arg)` S 00676900 [known]:

1. `CanSearch(from, to, arg)` false -> state 3;
2. store `from`, `to`; if `HexDistance(to, from) == 1` -> state 2 without a search;
3. `PrepareSearch()`; reset: `bestG` = -1 everywhere, both lists emptied, open list = the node of **`to`** with
   `g = 0` [inferred: the arguments are garbled in the decompile], `bestG[to] = g`;
4. repeat `Step` until it returns false.

`Step` S 00676700 [known]:

1. open list empty -> state 3, stop;
2. pop the **front** node and append it to the closed list;
3. for `dir` = 0..5: neighbour `n` inside the map; `c = GetStepCost(current, n, arg)`; skip if `c < 0`;
   `g = current.g + c`, `h = HexDistance(n, from)`; `PushOrImprove(n)`; **if `n == from`: state 2, stop at once**.

`PushOrImprove` S 0067bef0 [known]: `bestG[n] < 0` -> insert; `bestG[n] <= g` -> nothing; else if `n` is in the open
list -> remove and re-insert with the new `g` (keeping `h`); else remove it from the closed list and insert. Then
`bestG[n] = g`. Insertion (S 0067c560) keeps the open list sorted by ascending `f = g + h`; a new node goes
**before the first node with a greater `f`**, that is after all nodes with equal `f` (first in, first out among
equals).

The search runs from the destination towards the start and ends the moment the start is first reached, not when it
is popped; the result is a good path, not always the cheapest [inferred].

**Reading the path** [known]: `GetDescentDirections(cell)` S 0067c0e0: `m` = the smallest `bestG` among the in-map
neighbours with `0 <= bestG <= bestG[cell] - 1`; the result is the set of directions whose neighbour has
`bestG == m` (empty if `bestG[cell] <= 0`).

`BuildPath(out, randomize)` S 00676d10 [known]: `out` = [from]; adjacent case: [from, to]. Otherwise `dir = 0`
(or `LogicRandom % 6` when `randomize`), and until `to` is reached: get the descent set; if `dir` is not in it,
take the lowest direction of the set (or, when `randomize`, the `(LogicRandom % count + 1)`-th direction of the
set in ascending order); step and append. A direction is kept as long as it still descends.
`BuildPathReversed` S 00676e80 returns the same cells in the order to..from. `GetPathStepCount` S 00676a90
(1 for adjacent cells) and `GetPathTravelCost` S 00676b50 (the sum of the round-trip costs of §3.2, truncated to
int) walk from `from` to `to` on their own: at every cell they take the **lowest** direction of the descent set
and never keep the previous direction, so the cells they walk can differ from those of `BuildPath` [known].

**Base step cost** `AStar::GetStepCost(a, b, ignoreBlocking)` S 00676840 [known]: -1 if `b` is not walkable and `b`
is not `from` (skipped when `ignoreBlocking`); else 3, or 4 / 5 / 7 when the slope class from `a` to `b` is
-1 / -2 / -3 (the walker travels from `b` up to `a`); +2 if `b` has the deposit bit 0x80. Slope class -4 costs 3
[known as read]. Base `CanSearch` (vtable S 007f89c8 slot 0 = S 0041eca0) always returns true and base
`PrepareSearch` (slot 2 = S 005657b0) is empty; slot 1 is the step cost above [known, vtable bytes].

**Free walkers** `NMovement::FreePath::FindPath(from, to)` S 00775170 [known]: `to` must be inside the map; if one
end is a building and the other end is that building's own flag the path is [to, from]; otherwise the shared
`NMap::AStar` with the path's mode byte as `arg`, and `BuildPathReversed(randomize = true)`. The mode byte is
`FreePath.astarMode` (+0x20, 0 at construction S 007750d0); as `arg` of the base step cost it is `ignoreBlocking`,
so a set byte lets the path cross cells that are not walkable. It is set from the `bool` argument of the settler's
`MoveToCell` S 00658000 [inferred: that function stores the bool in a byte of the settler's movement; that this
byte is `FreePath.astarMode` was not followed here]; which callers pass it is `docs/sim/settlers-jobs.md` §3.8.3.

**Animals** `NResources::AnimalAStar::GetStepCost` S 00543490 [known]: base cost; then +4 if `b` has the mining bit
0x10, +2 if `b` has the street bit 0x2, +2 if an animal is on `b`; and with `avoidBuildings`: +2 if a flag is on
`b`, otherwise +4 more if `b` has the street bit; +10 for every cell of the spiral of radius 1 around `b` (`b`
itself and its 6 neighbours, S 00600e90) that holds a building in layer 1.

**Streets** `NLogic::AStarStreet` S 00776500, S 00776330, S 007761f0 (the planning commands are in
`docs/sim/game-commands.md`) [known]:

- modes 0 and 1 (land streets): -1 unless `b` is a free owned cell of the player (`IsOwnedCellFree`, border
  cells not allowed); then, unless `b` is `from` (which is exempt from all three tests): -1 if `b` has the street
  bit and its layer 2 entry is empty or not the planner's own street, -1 if `b` is in the excluded set, -1 if `b`
  holds a flag; else `base(a, b)`, and if that is not -1, `base(a, b) + base(b, a)`. The second term is not
  tested: when `base(b, a)` is -1 the step costs `base(a, b) - 1`;
- mode 2 (water streets): the same street, excluded-set and flag tests; then the step is allowed only if
  (`b` is `from`, or `b` is water and `a` is water or `a` is `to`) and at least one of `a`, `b` is water, `b` has
  none of the bits 0x20, 0x400, 0x10000 and `b` belongs to the player's territory; cost 2 if `b` is a shore cell,
  else 1 if `b` is shallow water, else -1;
- mode 3 (harbor transition): cost 1, or -1 off the ship-route bit 0x8000 depending on the per-search state.

**Ships** `NNavy::AStar::GetStepCost` S 005bba90 [known]: -1 unless `b` is free water; 12 if `b` is a dock (0x800)
or both harbor exit and ship route (0x4000 and 0x8000); else 2 if any of the 6 neighbours is land, a dock, a logic
object or on the map edge; else 1 (neighbours outside the map are skipped). `CanTraverse` S 005bbbe0: both ends
in the same continent (water body) and the second cell free water.
`ShipRouteAStar` S 005bb9d0 additionally forbids cells with the ship-route bit.

### 3.13 Flood-fill searches

One template (`FloodFillSearch::Run_*`, for example S 00541ec0) [known]:

```
generation += 1
if !pred.CanExpand(start, start): return false
if pred.Visit(start): return true
queue = [start]; mark start
while queue not empty:
    c = pop front
    for n in neighbours of c in the order SE, E, NE, NW, W, SW, inside the map, not marked:
        if pred.CanExpand(c, n):
            if pred.Visit(n): return true
            push n; mark n
return false
```

A cell rejected by `CanExpand` is not marked and may be tested again from another neighbour. The caller sets the
grid's in-use byte before and clears it after the search (S 0053f080).

| Search | Expand rule | Visit / stop rule | Evidence |
|---|---|---|---|
| nearest ground resource cell | within radius | stop at the first cell of the type | S 0053f940, S 00542d50 |
| ground resource amount in range (AI) | within radius | sums amounts (1000 counts 7); never stops | S 00540140, S 00542d00 |
| deposits of a good in range (AI) | deposit cell or walkable, within radius | counts non-depleted deposits; never stops | S 0053ff40, S 00542900 |
| nearest free deposit | §3.9 | §3.9 | S 0053fd40 |
| nearest huntable animal | walkable, within radius | §3.10 | S 0053fb40 |
| animal roam target | §3.10 | §3.10 | S 00541ec0 |
| fishing spot | walkable, within radius (the start cell is not exempt) | collects; never stops | S 0077f470, S 007802c0 |
| geologist dig cell | walkable, explored | §3.8 | S 00779130 |
| empty place for planting | walkable, explored | §3.9 | S 00778f30 |

Other instances exist for the military (S 00572210, S 00572410, S 00572610), streets and flags (S 005a2db0,
S 0066d190), ships (S 005b3e60, S 005b4060) and the AI (S 0059a560); their predicates belong to those subsystems.

---

## 4. Update order

### 4.1 Per logic tick

The position of this subsystem in `NLogic::System::Update` is in `docs/sim/logic-core.md` §4.2. In tick order
[known] S 00527070:

1. (step 5) `MapUpdateBatch_Begin`: construction and doodad dirty state reset.
2. (steps 6, 7) village and street net update: placement, removal, bulldozing, flags and streets mark cells;
   territory sources are added and removed (territory is recomputed immediately, §3.6).
3. (step 8) `MapUpdateBatch_End`: obstructed doodads in the dirty rectangle removed, construction flags of the dirty
   rectangle recomputed, continents rebuilt if requested.
4. (step 9) settlers: work results (sow, harvest, consume, plant, signs), exploration by soldiers, free-walker path
   searches. These run outside a batch, so their construction-flag updates are immediate, except
   `HarvestDepositAt`, which opens its own batch.
5. (step 11) `NResources::System::Update`:
   1. every active deposit, in list order: `Deposit::Update`, then keep, drop or queue (§3.9);
   2. queued deposits removed, last first;
   3. unless `NLogic::Edit` (the object at `NLogic::System + 0x38`, vtable S 007e7c28) reports true from its
      vtable slot 1 S 00538c90, the getter of the batch-editing byte that slot 0 `SetBatchEditing` S 00538a60
      writes (map editor bulk edits, `docs/sim/logic-core.md` §3.1): `roamSearchesThisTick = 0`, then every animal
      in ascending id order: `Animal::Update`; an animal that returns true is erased.
6. (step 12) `NDoodads::System::Update`: temporary doodads age and expire.
7. (step 14) navy: ships explore.
8. (step 18) spawn points: ground resources regrow, animals spawn.

### 4.2 Event driven, inside a tick

Territory recomputation, exploration, every `MapModifier` edit and the construction-flag recomputation of §3.5 run
synchronously inside the call that causes them [known].

### 4.3 Per frame only

Nothing in this subsystem simulates per frame. Presentation reacts to the `NMap::CallbackManager` events (§5.3):
the terrain mesh, the construction-map overlay and the fog texture
(`ai::render::FogOfWarTexture::RevealFromVisibility` S 006aeef0 clears the texel of every cell explored by the
viewing player) [known]. `ai::map::TerrainGrid` (S 00687190..00688050: world positions, normals, triangle picking)
and `ai::terrain::TerrainGenerator` (S 006b24f0: Perlin, fault-line, FBM and multifractal height generation; its only
caller is `S2CG::CMapRenderer::RunTerrainGenerator` S 00688540, a virtual of the map renderer with no direct caller
in the cached call graph) are render and editor code [known for the callers; inferred that S 00688540 is reached
from the editor only].

---

## 5. Inputs and outputs

### 5.1 Inputs

No lockstep player command addresses this subsystem directly [inferred: all callers found are other simulation
subsystems, Lua, or the editor]. It is driven by:

| Caller | Calls |
|---|---|
| buildings (`NVillage`) | layer 1 and bits 0x1 / 0x100, `AddTerritorySource` / `RemoveTerritorySource`, `ExploreArea`, `DetectTerritoryContacts`, levelling, the searches of §3.13 |
| street net (`NNet`) | layers 0 and 2, bit 0x2, `FlattenAroundCell`, `SetElevationAlongStreet` |
| settlers and their work sequences (`NSettlers`, `NMovie`) | deposit harvest, sowing, planting, ground resource consumption, signs, dig reservations, hunting, `SpawnAnimal` (`NSettlers::Worker::Update`), the skeleton doodad, path searches |
| navy | navy bits, `ExploreArea`, ship path-finding |
| spawn points and chests (`ai::logic`) | bit 0x400, `AddResourceAtCell`, `SpawnAnimal`, `RemoveDoodad` (`LogicChest_ClearCellForChest` S 0052d110) |
| sacrifices | `ExploreArea`, the full territory recomputation (`Logic_RecalcTerritoryForPlayer`, §3.6) |
| Lua (`docs/lua-surface.md`) | `map.createDeposit`, `map.killDeposits` (S 00540e60), `map.createDoodad`, `map.removeDoodads`, `map.forEachDoodad`, `map.exploreArea`, `map.exchangePatternType`, `map.searchConstructionPlace` |
| editor / `NLogic::Edit` | `SetVertexElevation`, `SetCellPattern`, `CreateDeposit`, doodad add and remove, the whole-map refresh passes |

### 5.2 Outputs to other simulation subsystems

- Queries: grid bits, heights, slope classes, territory owner, exploration, continent of a cell, construction flags,
  object layers, the searches and path-finders.
- Calls out on territory change: street removal and the marking of buildings outside territory (§3.6).
- Player messages: `!Lost Territory.` (category 1, S 006797f0), `!Found Resource` (category 2, S 0077b2f0),
  `!No resources found.` (category 3; sent by four searches, each only while production is enabled and the
  building's productivity is < 0.5: the fisher search S 0077f670, `NMovie::LookForDeposit::Start` S 00778d50,
  `NMovie::LookForAnimal::Start` S 00778e40 and `NVillage::Building::UpdateResourceSearch` S 0055ded0) [known].
- Player flags: `spotted` (exploration), `reached` and contact positions (territory contact).
- Rules of other subsystems that read these grids every tick: the street net removes flags whose cell is no
  longer a valid territory cell of the owner (`docs/sim/streets-transport.md`); a ship needs a coast of its
  player nearby (`GameQuery::IsWaterCellAtPlayerCoast` S 0052f0c0, `docs/sim/navy.md` §3.5).

### 5.3 Events

`NMap::CallbackManager` [known] S 00677ca0..00677ea0: the listeners are kept in a `std::set` of listener
pointers (+0x08; `AddListener` S 00677f30 -> unique insert S 00531fa0, keys compared as unsigned), so every
event walks them in ascending **address** order, which depends on the heap and is not reproducible. [TODO] not
established: which objects register (S 00677f30 has no direct caller in the cached call graph; the vtable slot
that holds it and its callers would settle whether a simulation object listens). Listener slots 0..4 in table
order:

| Event | Arguments | Raised when |
|---|---|---|
| `ElevationRectChanged` | vertex rectangle | heights changed |
| `CellRectChanged` | cell rectangle | patterns changed |
| `MapInitialized` | width, height | `Init` and `Load` |
| `TerritoryChanged` | none | the follow-up of a territory source change and of the full recomputation (§3.6, both only while `MapModifier.bEnabled`), and `MapModifier_InitAfterMapLoad` S 00673000 |
| `PlayerRectChanged` | cell rectangle, player | `ExploreArea` (per revealed player, §3.7); `MapModifier::ResetPerPlayerGrids` S 00672f80; `MapModifier_InitAfterMapLoad` (whole map, for the local player) |

`NLogic::CallbackManager` (the simulation's general broadcaster, `docs/sim/logic-core.md`) [known]: deposit shown
(receiver vtable offset 0x48: raised by `ResetAmountFromProperty` S 00542da0, `SetAmountFull` S 00542dc0 and by
`Deposit::PostLoad` S 00542f00 when `growth >= 0`), deposit removed (0x4c, destructor), deposit disappearing
(0x50, `MarkDepleted`), animal added (0x54, spawn constructor and `Animal::PostLoad`), animal removed (0x58,
destructor), doodad added (0x78), doodad destroyed (S 005310a0), spawn triggered (0xdc, both spawn kinds).

---

## 6. Data-driven parameters

| File | Keys | Read by | Example values |
|---|---|---|---|
| `scripts/properties/patterns.lua` | `pa_create`, `pa_setBlocked`, `pa_setForBuilding`, `pa_setForPlanting`, `pa_setForMining`, `pa_setForShip`, `pa_setTreeType`, `pa_setMiniMapColor` | §3.3, §3.9 | 114 patterns; helpers: meadow = building + planting; earth and stone ground = building; rock = mining; sand and sea ground = nothing; snow, swamp, lava = blocked; ship = `pattern_pavement` 0xdecade01; `pattern_acre` 0xca56701a = building + planting |
| `scripts/properties/deposits.lua` | `dp_create`, `dp_setGood`, `dp_nextDeposit`, `dp_setGrowingStartSize`, `dp_setGrowingSpeed`, `dp_setBlocking`, `dp_setRandomFinePosOffsetState`, `dp_setElevationSize`, `dp_addUndergroundPattern`, `dp_setLifeTime`, `dp_setNeedForPlantablePattern`, `dp_addTreeType` | §3.9 | see §3.9 "Data"; `mapTreeType_Bavarian = 100`, `_Egyptain = 101`, `_Scot = 102` |
| `scripts/properties/animals.lua` | `an_create`, `an_setRange`, `an_setMoveDistance`, `an_setMovementSpeed`, `an_setAvoidBuildings`, `an_addStackGood`, `an_setRespawn`, `an_setDyingTime`, `an_setDisappearingTime`, (`an_setIdleTimeFactor` is not called by the shipped script, so the default 3.0 applies) | §3.10 | deer: 6, 2, 0.045; rabbit: 8, 4, 0.07 |
| `scripts/properties/doodads.lua` | `dd_create`, `dd_setBlocking`, `dd_setLifeTime`, `dd_setDeleteByStreet`, `dd_setType`, `dd_setIndestructable` | §3.11 | sign lifetime 3000 |
| `scripts/properties/signs.lua` | `si_addSignDoodadId(good, threshold, doodad)` | §3.8 | `(coal, 3, doodad_coalSignM)` |
| `scripts/properties/spawnpoints.lua` | `sp_create`, `sp_addUniqueId`, `sp_setType` (`sp_setRange`, `sp_setRate` unused) | §3.8, §3.10 | `animalspawn`: deer, rabbit, elk |
| `scripts/properties/Goods.lua` | `gp_enableDeposits` (GoodProperty +0x50), `gp_enableFields` (+0x51) | +0x50: building deposit search (`NVillage::Building::UpdateDepositSearch` S 0055bfb0, `docs/sim/village-buildings.md` §3.9) and AI code, through the getter S 005549d0; +0x51: no reader found (§10 #5) | `gp_enableDeposits(wood, 1)`, `gp_enableFields(coal, 1)` |
| `scripts/properties/config.lua` | `cfg_setFishingDistance`, `cfg_setMaxWaterStreetWaterDepth`, `cfg_setBulldozeTime`, `cfg_setSpawnPointUpdateTime` | §3.8, §3.2 | 1, 4000, 55, 1200 |
| `settings/graphics.xml` | `<Map scaling="x h z">` | §2.1 | `1.5 0.001 1.2990375` |
| map file | all grids, `minHeight`, deposits, animals, doodads | §7 | `docs/map-format.md` |

Constants compiled into the code [known]: slope thresholds 200 / 600 / 1200 / 2400; speed factors 0.8 / 0.6 / 0.4;
A* costs 3 / 4 / 5 / 7 and +2; ground resource cap 7 and unlimited marker 1000; deposit removal delay 20; territory
distances 3 and 5; construction invalidation radius 4; elevation notification margin 16 vertices; exploration border
(1 cell at the low side, 2 at the high side); geologist search radius 5; planting candidate limit 11; at most 2 roam
searches per tick; roam retry counter 100; animal block size 16 and crowd limit 4; 8 player slots.

---

## 7. Save and load

Byte layouts: `docs/map-format.md` §4.4..§4.13. A map file and a save use the same sections.

**Order** [known] S 00671930: `MapSystem` (initialised, W, H), then `ElevationMap`, `PatternMap`, `GridStatesMap`,
`Map Resources`, `Map Territory`, `Map Exploration`, `Map Continents`. The resource system (`resources`: init byte,
deposits in vector order, animals in id order, `roamTurn`, `roamSearchesThisTick`, `mapTreeType`) and the doodad
system (`DoodadsSystem`: static, temporary, blocking lists) are separate sections of the logic system.

**Not saved, rebuilt on load** [known] S 00672030, S 00540fd0, S 0053ec60:

| State | How it is rebuilt |
|---|---|
| construction flags | allocated on load (`ConstructionMap::Init` in S 00672030); filled for the whole map by `ConstructionMap_RecomputeAll` in `MapModifier_InitAfterMapLoad` S 00673000, which `Game_LoadWorldFromDescriptor` S 005ac770 calls after the file is read, for a new map and for a save alike. The debug menu's load button calls the file loader directly, without that step [known for the callers in the cached decompile] |
| object layers | each object's `PostLoad` re-registers itself (flag, building, street, deposit, dig reservation) |
| `activeDeposits` | a loaded deposit is active iff `depletedTicks != 0 || growth < 1.0 || ttl >= 0` |
| `depositById`, `animalById` | filled while loading |
| `animalsByCell`, `AnimalAreas` | `AnimalAreas::Init` in `Load`; `System::PostLoad` re-adds each animal; the movement re-registers the cell |
| doodad cell | recomputed from the fine position (`NDoodads::Object::Load` S 00545260) when the `DoodadsObject` section version is not 0; a version 0 record carries the cell |
| A* grids, visited grid | allocated for the loaded size |

**Not recomputed on load** [known, `docs/map-format.md` §5.5]: every grid-state bit, the continents (version >= 1),
territory. In particular loading a deposit, a blocking doodad, a spawn or a navy object does not set its bit; the
saved `GridStatesMap` must already contain it.

`Animal::PostLoad` S 00541bf0 clamps `timeStamp` to at most `tick / 10` [known].

**Section versions of `resources`** (`NResources::System::Load` S 00540fd0) [known]: the animal list is read only
when the section version is > 0; versions 3 and 4 carry 0x20 raw bytes after the animals that are read and
discarded; `roamTurn` and `roamSearchesThisTick` are read when the version is > 3; `mapTreeType` when it is > 5.
`NResources::System::Store` S 0053e960 [known] writes: section `resources`, the init byte, the deposit count, per
deposit (vector order) its property id and the deposit's own `Store`, the animal count, per animal (ascending id)
its property id and the animal's own `Store`, then `roamTurn`, `roamSearchesThisTick`, `mapTreeType`. The section
descriptor is constructed with the number 6 (S 007c0db0), which is the version written [inferred: it matches the
newest field gate, `> 5`]; `Resources Animal` is constructed with 3 (S 007c0e50).

**Doodads** `NDoodads::System::Store` S 00543bf0 / `Load` S 00544ef0 [known]: section `DoodadsSystem` (descriptor
number 0, S 007c1170), the init byte, then three count-prefixed lists in the order static, temporary, blocking,
each in ascending id order, every entry as its property id followed by the object's own record. `Load` clears the
system first and fills the same containers and position indices; it does not set grid bit 0x400.
The object's record (`NDoodads::Object::Store` S 00545210, section `DoodadsObject`, descriptor number 1,
S 007c1210) [known]: the Unique, the fine position, and the remaining `lifetime` **only if the property's
`lifeTime` is >= 0**. `Object::Load` S 00545260 mirrors it: for a section version other than 0 the lifetime is
read under the same condition and is -1 otherwise; a version 0 record holds Unique, fine position, cell and
lifetime unconditionally. The condition uses the property as defined when loading, so a changed `dd_setLifeTime`
sign (permanent <-> temporary) makes old records unreadable [inferred].

---

## 8. Determinism notes

- **Random generator** (`LogicRandom_Next`, `docs/sim/logic-core.md`). Draws made by this subsystem, each exactly as
  listed [known]: deposit creation at a cell (1, always); animal creation (1); animal spawn (1 for the type, only
  when the spawn's block is not crowded, so 2 per spawned animal with the creation draw); roam search (1 per search); sowing (1 if the type has underground patterns); planting (1 for the place, only when the
  place search was stopped with at least one candidate, §3.9; 1 more for a random tree type); geologist cell (1 if
  a candidate exists); fishing spot (1 if a candidate exists);
  `BuildPath` with `randomize` (1 at the start if the ends are not adjacent, plus 1 at every step where the current
  direction stops descending). Free walkers (S 00775170) and animals (S 00543b20) always build the randomised
  path, so **every successful free-walker path search of a settler consumes random numbers**, except between
  adjacent cells and on the building-to-own-flag shortcut of §3.12; a remake that wants replay or save
  compatibility must reproduce the count.
- **Iteration order.** Deposits: vector in creation order; the active list in insertion order with order-preserving
  erase. Animals and doodads: `std::map` keyed by the 64-bit Unique, ascending, so creation order as long as ids
  only grow. Animals on a cell: vector in registration order. Deposit types for planting: the order of the
  property map, ascending property id (the hash from `dp_create`) compared as a signed int (§3.9). Sign lists:
  ascending threshold (§2.5). Players: slot 0..7. Territory sources: the new source first, then the buildings in
  the order of the village system's building vector (§3.6).
- **Desync checksum.** The lockstep checksum does not cover the map grids, the resource system (deposits,
  animals) or the doodads (`docs/sim/save-format.md`, `nGame::System::ComputeChecksum` S 00784080); a divergence
  in this subsystem is only detected once it changes hashed state such as buildings, settlers or the random
  generator [inferred from that list].
- **Tie-breaking.** Territory: lowest player index on equal influence; a source nearer than 3 wins by list order.
  A*: first-in-first-out among equal `f`; neighbours in direction order 0..5; early stop on first reach of the
  start. Flood fills: neighbour order SE, E, NE, NW, W, SW; first hit wins. Spiral searches: the spiral order of
  §3.1.
- **Floating point.** Territory influence is float32 `r / d^2` compared with `<`; deposit growth accumulates a
  float32 per tick and is compared with 1.0 and with the start size; animal `timeStamp` is float32 `tick / 10`;
  street shaping converts floats to ints; the first idle counter of an animal, its idle counter after a walk and
  the `timeStamp` step of state 6 are float32 expressions truncated to int (§3.10); the slope speed factors and
  the round-trip cost are float32 (§3.2). Heights, slope classes, A* costs and amounts are integer.
  The growth sum decides the tick on which a field becomes harvestable, so it must be accumulated in float32 in the
  same order.
- **Shared scratch state.** The visited grid and each A* instance are shared; a search must finish before the next
  one starts (the in-use byte guards the visited grid) [inferred].
- **Order dependence inside one tick.** The roam scheduler (`roamTurn`, `roamSearchesThisTick`) depends on the
  animal iteration order and is saved; the ring smoothing of §3.4 is sequential.
- Static locals: the shallow-water limit is cached on first use; the deposit removal queue is a function-static
  vector cleared at the start of every update [known] S 0052e550, S 00540340.

---

## 9. Notes for a reimplementation

Must be exact for compatibility with original maps and saves:

- the grid indexing, the odd-row hexagon tables, `HexDistance`, the cell-to-vertex relation, and the spiral order
  (it decides which cell a spiral search finds first);
- the grid-state bit positions and the fact that maps deliver them precomputed; the ground resource cell format with
  amount cap 7 and marker 1000;
- the Unique ids of deposits, animals and doodads (map keys and references from buildings);
- the deposit record fields `growth`, `depletedTicks`, `ttlWithoutOwner` and the active-list rule.

Must be exact for lockstep with original clients or for identical replays, otherwise free:

- every random draw count and every tie-break of §8, the A* expansion and path-reading rules, the two-searches-per-
  tick animal scheduler, the float32 growth and territory arithmetic.

Can be simplified in a remake that only needs to play the same rules:

- the dirty-rectangle batching (recompute construction flags lazily or per changed cell set);
- the visited-grid generation trick and the linked-list open list (any priority queue with the same ordering);
- the three doodad containers (one container with a kind field), the fine-position indices;
- `ObjectLayers` as five id grids (any per-cell occupancy record);
- the editor-only whole-map refresh passes, the terrain generator and `TerrainGrid` (engine side).

Behaviour that looks unintended but is what the code does, to be kept or consciously changed:

- levelling terrain in play never updates water, shore or cliff bits (§3.3);
- a territory source recomputes only the spiral of its own radius (§3.6);
- the exploration border is asymmetric (§3.7);
- adding to an unlimited ground resource cell turns it into 7 units (§3.8);
- the X-size and water signs are unreachable through the geologist (§3.8);
- A* stops at the first reach of the start cell (§3.12);
- the cell dirty rectangle grows only towards the origin when flushed (§3.4).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.9): a planter never plants while the flood fill through walkable, explored cells runs empty before it has 11 candidates and before it visits a cell farther than radius + 4; the search returns false, draws no random number and `GoAfforest::Start` creates nothing. With 11 or more plantable cells inside a small reachable area he plants | static: S 00778f30, S 0077e660, S 0077e5c0, S 00779330, S 0077bcb0 (vftable S 0083457c slot +0xc) |
| 2 | Whether an animal that was linked by a hunter (state 4) and then released by an aborted hunt stands still for the rest of the match (§3.10, step 6) | observation in the running game: destroy a hunter's hut while the hunter walks to the animal, then watch the animal |
| 3 | Answered (§3.10, state 2): the idle counter after a walk is `(int)((tick/10 - timeStamp) * idleTimeFactor * 10)`, three times the walk's ticks with the shipped factor; the animal idles `counter + 1` ticks | disassembly S 0054231f..0054235e; live 2026-10-12 (400 arrivals) |
| 4 | Answered (§3.10): yes. The exploration test of the hunter's search reads `Animal +0x38`, the movement's target cell (the cell of the last arrival while the animal is at rest); the roam search does not look at exploration, so such destinations occur | static: S 00542c40, S 005418e0, S 00772b00 |
| 5 | [TODO] Whether anything reads `DepositProperty.elevationSize` (+0x50) or `GoodProperty + 0x51` (`gp_enableFields`). In the cached decompile the typed field `elevationSize` appears only in the constructor S 005553d0 and the setter S 0054e100, and `GoodProperty` has a setter for +0x51 (S 005549e0) but, unlike +0x50, no getter next to it; no one-line getter of a byte at +0x51 exists at all. Both look unused [inferred] | static: instruction search for untyped reads of +0x50 on a `DepositProperty*` and of +0x51 on a `GoodProperty*` |
| 6 | [TODO] Whether any caller passes direction 6 or 7 to `MapPos::StepDirection` through a variable (the calls with a constant 6 or 7 are the two editor tools of §3.1) | static: the callers of S 00675000 whose direction argument is not a constant or a 0..5 loop counter |
| 7 | Whether a shipped map contains resource spawn points although `spawnpoints.lua` defines none (it declares `SpawnType_Resource = 0` but gives it to no type) | scan the `Logic SpawnSystem` sections of all maps for property ids with kind 0 |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00672180 / 00672430 / 00672030 / 00671930 | `NMap::System::ctor` / `Init` / `Load` / `Store` | map root |
| 00675000 / 00675040 | `MapPos::StepDirection` / `HexDistance` | hexagon geometry |
| 00675160 / 00675500 | `MapPos::SetFromFinePos` / `FinePos::ToNearestPatternCursor` | vertex to cell |
| 00675d30 / 00676200 / 00675f40 | `Elevation_HeightDiffToSlopeClass` / `GetSlopeClassBetween` / `GetAverageHeightInRadius` | heights |
| 0052df20 / 0052e550 / 0052e250 / 0052e320 | `Map_IsCellWalkable` / `Map_IsShallowWaterCell` / slope speed factor / round-trip cost | cell predicates |
| 0067b390 / 0067b150 / 0067b740 / 0067b820 / 0067b650 / 0067b2c0 | `MapCellUpdater::RefreshBit*` | derived grid bits |
| 0067b910 / 0067b5a0 | `RefreshTerritoryBorderBits` / `IsTerritoryBorderCell` | border bit |
| 00673bd0 / 00674100 / 00673910 / 006744f0 / 00674560 / 00673370 | flatten, level, smooth, street shaping | terrain edits |
| 00674360 / 00674470 | `SetCellPattern` / `ExchangePatternInRect` | pattern edits |
| 00672df0 / 006730e0 | flush elevation rect / flush both rects | change notification |
| 00532180 / 005321c0 / 005322b0 / 00532400 | `MapUpdateBatch_Begin` / `_End` / `InvalidateConstructionRadius` / radius-4 wrapper | batching |
| 00675610 / 00675790 / 00675880 / 00675980 / 00675740 | construction flags: compute, all, rect, radius, read | buildability |
| 0052f8a0 / 0052f3d0 / 0052f270 | `GameQuery::CanPlaceFlagAt` / `IsOwnedCellFree` / `IsPlayerTerritoryCell` | flag bit |
| 00600e90 | spiral iterator `{maxRadius, ring, dir, step, x, y}` (centre first, then the rings of §3.1) | geometry |
| 00679510 / 0067a030 / 00679960 / 00679ac0 | cell owner / collect sources / recalc area / recalc map | territory |
| 00673af0 / 00673b20 / 00673a50 / 00672eb0 | add source / remove source / local follow-up / full follow-up | territory |
| 006797f0 / 00674ad0 | lost-territory message / border contacts | territory events |
| 00674800 / 00677570 / 00542b10 / 00677670 | `ExploreArea` / `RevealHexArea` / `IsExplored` / `HasUnexploredInRadius` | exploration |
| 00674210 / 006745e0 / 00674650 / 006746c0 / 00674e70 | ground resource: may hold, add, consume, consume near, consume any | ground resources |
| 0067a800 / 00540660 | count cells of type in radius / nearest resource cell | ground resource queries |
| 0077b2f0 / 0052dfa0 / 007794b0 / 00556cb0 | sign placement / diggable cell / dig search / sign lookup | geologist |
| 0077f670 / 00780300 | `LookForFishing::Start` / fishing visitor | fish |
| 00540340 | `NResources::System::Update` | per-tick resources |
| 00540b40 / 00540aa0 / 00540c40 / 00540e60 / 00540740 / 0053f2a0 | create / add full / harvest / kill / set ttl / remove | deposits |
| 005432d0 / 00542f80 / 005431a0 / 00542a10 / 00542de0 / 00542f00 | deposit ctors / update / available / mark depleted / post-load | deposits |
| 0052eb10 / 0052e150 / 0052ef40 | deposit placement rule | deposits |
| 0077ebf0 / 0077eda0 / 0077bcb0 / 00779330 / 005477e0 | work result / work start / planting / empty place / tree type pick | deposits from the settler side |
| 00540f40 / 005418e0 / 005420c0 / 00541b50 / 00543890 | spawn / ctor / update / start move / cell index | animals |
| 00543950 / 00543900 / 005439b0 | roam search init / expand / visit | animals |
| 0053ee60 / 00541c60 / 005407a0 / 00542c40 | huntable at cell / alive test / nearest huntable / target test | hunting interface |
| 0055c050 / 0053c550 / 0055c3a0 / 0053c580 | hunt target search / link / building side of the link / unlink | hunter sequence |
| 0077cba0 / 00777f80 / 0065c610 | `GoHunting::Update` / `PickupProduct::Start` / `Worker::UpdateHuntingJob` | hunter sequence |
| 00541ac0 / 00541b00 / 00541b30 / 00541ad0 / 00541a00 | animal state 4 / 5 / 8 / reset after unlink / destructor (state 9) | animal states |
| 00772950 / 007728d0 / 00772b00 / 007749f0 / 00543700 | `NMovement::Base::Update` / `BeginStep` / `StartMoveTo` / interpolator reset / animal speed | animal movement |
| 00773a40 / 00773ec0 / 00773450 | `Rough::BeginStep` / `Fine::BeginStep` / settler movement ctor | walking speed |
| 00674f50 / 00675090 | `MapPos_GetAngleDegrees` / `MapPos::GetHexDirectionTo` (table S 007f8948) | direction between points |
| 00559820 / 0067a3b0 / 00672f10 / 00538d10 / 00558800 | building collector / `RecalcAll` / full recalc wrapper / per-player trigger / refresh updaters | territory |
| 0053e960 / 00540fd0 / 0053ec60 / 00543bf0 / 00544ef0 | resources `Store` / `Load` / `PostLoad` / doodads `Store` / `Load` | save |
| 00545210 / 00545260 / 00541bf0 / 00542f00 | doodad object `Store` / `Load` / `Animal::PostLoad` / `Deposit::PostLoad` | save |
| 00677f30 / 00531fa0 | `NMap::CallbackManager::AddListener` / listener set insert | events |
| 0053bda0 | `NResources::Animal::IsDead` (state 5, 7, 8 or 9) | hunter sequence |
| 00565f80 / 0055c860 / 00565550 | `OnProductionFinished` / consume linked cell / produces-goods flag | mines, planting |
| 005574f0 / 00556df0 / 00546c70 | sign list add / sorted insert / property map find | data order |
| 0041eca0 / 005657b0 / 007750d0 | base A* `CanSearch` (address-shared "return true" stub) / `PrepareSearch` (shared empty stub) / `FreePath` ctor | path-finding |
| 00542700 / 005424c0 / 00542440 | animal areas init / add / crowded | density |
| 00544e00 / 00545150 / 005446c0 / 005454f0 / 00544480 / 00544b70 / 00544ad0 / 00543dc0 | doodads: add, add at cell, update, removal rule, remove, rect check, vertex check, find | doodads |
| 00676900 / 00676700 / 00676840 / 00676d10 / 00676e80 / 00676a90 | A*: find, step, base cost, build path, reversed, step count | path-finding |
| 0067bef0 / 0067c0e0 / 0067c300 / 0067c560 | node lists: relax, descent directions, reset, sorted insert | path-finding |
| 00543490 / 00776500 / 00776330 / 005bba90 / 005bb9d0 | step costs: animal, street, water street, ship, ship route | path-finding |
| 00775170 / 00543b20 | free-walker path / animal path | path-finding users |
| 0053f080 / 00541ec0 | flood-fill init / template instance | flood fill |
| 005390e0 / 00538f40 | resource spawn / animal spawn | spawn points |
| 006aeef0 | `FogOfWarTexture::RevealFromVisibility` | fog rendering |
| 00555c00 / 005553d0 / 00555190 / 00555970 | property defaults: pattern, deposit, animal, doodad | data |
