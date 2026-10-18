# Computer player (AI)

Specification of the computer player of *Die Siedler: Aufbruch der Kulturen* for a reimplementation.

- Binary: `sadk_noav.exe` (base `0x400000`). `S 00xxxxxx` is a static address and only evidence.
- Tags: **[known]** = read directly in the code or the data (address or file and key given); **[inferred]** =
  one step of reasoning from what is visible (this includes rules taken from the analysis comment of a function
  whose body was not re-read line by line); **[TODO]** = open. Nothing here was observed in the running game.
- Related documents, not repeated here: [military.md](military.md) (attacks, fights, garrison, the cached enemy
  distance of military buildings, player military settings), [village-buildings.md](village-buildings.md)
  (buildings, production, upgrade, sacrifices), [players-victory.md](players-victory.md) (players, enemies,
  statistics, the slot's computer level), [logic-core.md](logic-core.md) (tick, random generator, save stream),
  [game-commands.md](game-commands.md), [../navy-and-military.md](../navy-and-military.md),
  [../lua-surface.md](../lua-surface.md) (the `properties.ai_*` and `logic.ai_*` tables),
  [../types.md](../types.md), [../map-format.md](../map-format.md).
- Time units: the **logic tick**, 10 per second at game speed 1 (`logic-core.md` §3.1), and **game time in
  seconds** (`GameSystem.nextTickTime`, a float; 600 s = 10 minutes).
- Distances are hex distances in map cells (`ai::map::MapPos::HexDistance`) unless stated otherwise.

## 1. Purpose and scope

The computer player is a **rule-based planner that plays through the same game systems as a human**: it places
buildings, flags and streets, toggles production, sets military sliders, starts attacks, orders sacrifices and
sends expedition ships. It has no script per map; all behaviour comes from fixed rules in the code, three
difficulty profiles (plus three campaign profiles) in `ai.lua`, and a few per-good and per-building numbers in
the property scripts.

Responsible for:

- dividing the own territory into **cells** (16 x 16 map cells) and keeping per-cell lists of buildings, wanted
  buildings ("needs") and producers;
- deciding **what to build** (needs for goods, turned into producer buildings), **where** (cell choice, then a
  site search inside the cell) and **when** (one construction order at a time, with a back-off);
- connecting buildings with **streets** and improving the street network;
- **expanding** the territory with military buildings (for resources, for room, for pressure on the enemy);
- running the **economy controls**: switching producers on and off by stock, food distribution, storehouse
  balancing, foresters, tools, coins, weapons, ships, catapults, sacrifices, demolition of useless buildings;
- **military decisions**: target choice, attack start, retreat, giving up attacked buildings, soldier kind per
  building, upgrading military buildings;
- its own save state.

Not responsible for (and not specified here): the mechanics it drives (construction, street path rules,
attack and fight resolution, sacrifice effects) and the placement test of a building. The generic site score
`GameQueryHelper::ScoreSite` S 00534830 belongs to the building/map queries, but the AI is its only caller, so
its formula is given in §3.6.

The AI does **not** issue lockstep commands. It calls the simulation directly from inside the logic tick
(`NVillage`, `NNet`, `NMilitary` functions), on every machine identically [inferred: callees of
`BuildingConstruction::Update` S 005a1ac0, `AttackExecution::Update` S 005a0dd0,
`DestructionSystem::DemolishBuilding` S 0058dc60 are simulation functions, not command senders].

## 2. Data model

### 2.1 Object tree

```
NAI::System (0x90, one per game, NLogic::System+0x54)
 ├─ players[8]        NAI::Player*        (+0x10)   one per player slot, active or not
 ├─ militaryMaps[8]   NAI::MilitaryMap*   (+0x30)   one per player slot, for EVERY active player (human too)
 ├─ streetPlanner, streetPathAnalyzer (+0x58), constructionPathAnalyzer (+0x5c)   shared path searches
 ├─ low-res visit grid (+0x60 vector, dims +0x70/+0x74)   scratch for flood fills
 ├─ tick (+0x80, u32)                     AI tick counter
 ├─ resourceMap (+0x84), lowResResourceMap (+0x88)   shared knowledge of resources on the map
 └─ enabled (+0x8c, bool)

NAI::Player (0xd4)
 ├─ gamePlayer, profile (AiProperty*), bActive, bEnabled, startX/startY, start continent id
 ├─ buildings   map<Unique, NAI::Building*>      mirror of every own village building
 ├─ needsA      map<Unique, NAI::Need*>          wanted producers of plain goods
 ├─ needsB      map<Unique, NAI::Need*>          wanted "either" group goods (good type 3)
 ├─ productions map<Unique, NAI::Production*>    per product slot of an own building, one per unit of its amount
 ├─ harbors     map<Unique, NAI::Harbor*>
 ├─ CellSystem  (cells, CellExpansion, CellDepotCreation, CellValidator, CellClearing)
 ├─ TerritoryMap, ResourceMapAdds, LowResResourceMapAdds        per-player annotations of the shared grids
 ├─ NeedCreation, NeedsArrangement, NeedsConstruction, ConstructionSystem
 │     └─ BuildingConstruction, SearchConstructionPlace, StreetConstruction, StreetOptimizer,
 │        StreetRouteOptimizer, ForesterConstruction, ShipConstruction, ConstructionHunter (§7),
 │        SacrificeSitePlanner
 ├─ ResourceSystem, ExpansionSystem (+ Expedition), DestructionSystem
 ├─ LockSmith, FoodArrangement, GoodsArrangement, ProductionControl, ConqueredContinents
 ├─ AiSacrificeManager (+0xac) with AiSacrificeState
 └─ MilitarySystem (0x29c)
       ├─ MilitaryBuildingCreation (+0xc) with MilitaryBuildingRanking
       ├─ MilitarySettings (+0x74), AttackSystem (+0x84: AttackTargetSelection +0xc, AttackExecution +0x6c)
       ├─ SoldierCreation (+0x148), CatapultConstruction (+0x154), WeaponProduction (+0x1bc)
       ├─ CoinProduction (+0x1d0), MilitaryUpgrade (+0x1e4), Casern (+0x204)
       ├─ attackWatches map<Unique, AttackWatch*> (+0x26c), AiFightHistory (+0x278)
       └─ MilitaryLimiter (+0x28c)
```

[known] `NAI::System::CreatePlayers` S 00581830, `NAI::Player::Activate` S 00582870, `NAI::Player::Update`
S 00582af0, `NAI::MilitarySystem::Update` S 00585380, `NAI::Player::Store` S 00583180, struct layout of
`NAI::Player`.

### 2.2 The four grids

| Grid | Cell size (map cells) | Owner | Content |
|---|---|---|---|
| **AI cell** (`CellPosition`) | 16 x 16 | per AI player (`CellSystem`) | `NAI::Cell` objects, only where the player owns land |
| **Low-res grid** (`LowResPosition`) | 8 x 8 | `MilitaryMap` per player slot; `TerritoryMap` per AI player | military weights; AI bookkeeping counters |
| **Resource map** (`ResourcePosition`) | 4 x 4 | shared (`System+0x84`) | list of resource elements per cell |
| **Low-res resource map** | 16 x 16 (4 x 4 resource cells) | shared (`System+0x88`) | merged sums of the 16 resource cells |

Sizes are rounded up: low-res = `(mapW+7)/8`, resource = ceil(`mapW/4`), low-res resource = `(resW+3)/4`
[known] S 00582120, S 005872f0, S 00588aa0, S 00589220. One AI cell covers 2 x 2 low-res elements [known]
`TerritoryMap::OnCellAdded` S 00591260.

`LowResPosition::GetNeighbor(dir)` numbers the 8 neighbours 0=(-1,-1) 1=(0,-1) 2=(+1,-1) 3=(-1,0) 4=(+1,0)
5=(-1,+1) 6=(0,+1) 7=(+1,+1) [known] S 00589ad0.

**MilitaryMapElement** (0x28 bytes, one per low-res cell and player slot) [known]
`MilitaryMap::UpdateCell` S 00586790:

| Offset | Name used here | Meaning |
|---|---|---|
| +0x04 | `threat` ("value[0]") | sum of `bp aiThreat` of the player's buildings in the 8 x 8 block; for a military building (territory building, not a depot, `soldierLimit != 0`) the term is `garrisonCount * (aiThreat / soldierLimit)` (integer division first) |
| +0x08 | `threatUnfinished` ("value[1]") | the part of `threat` from buildings for which the building's construction component (building +0x44) has float +0x70 > 0 or +0x74 > 0 [known as a test]. The two floats are the remaining fractions of the two construction phases (`NVillage::Construction.remainingA` / `remainingB`, both start at 1.0; `village-buildings.md` §2.3, §2.4), so this is the threat of the buildings that are still **construction sites** [inferred]. The same test, negated ("both `<= 0`" = finished), gates every AI rule that touches a building's production (S 0058d130, S 005993c0, S 0059cf60) |
| +0x0c | `threatCatapult` ("value[2]") | the part of `threat` from buildings whose property has the catapult byte (+0xb0) |
| +0x10 | `scoreCatapult` ("value[3]") | sum of `bp aiScore` of catapult buildings |
| +0x14 | `score` ("value[4]") | sum of `bp aiScore` of all the player's buildings in the block |
| +0x18 | `harbors` | vector of {x,y} of the player's harbours in the block |

The loop runs x from bx·8 to bx·8+7 (outer) and y from by·8 to by·8+7 (inner) over in-map cells, one lookup per
cell with `NVillage::System::FindBuildingAtOrNearest(cell, 0)` S 00558890. That lookup reads object layer 1 at the
cell (call at S 005588e0), accepts the id when its high word is > −1 and resolves it with `FindBuildingByUnique`
S 00558250 [known]. Layer 1 holds a building on its **anchor only**: its only writer is
`MapModifier::SetBuildingAtCell` S 006737d0, called from `Building::ctor_Place` S 0055d980, `ctor_Transfer`
S 0055d4e0, `PostLoad` S 0055c260 (set) and `dtor` S 0055ce70 (clear), all with `&this->posX` (+0x20/+0x24); the
other footprint cells carry only grid bit 0x100 (`Blocking::Set`). The other object layers: flag 0 (S 00674040),
street 2 (S 00673820), deposit 3 (S 00673870), dig reservation 4 (S 006738c0) [known]. So a building adds its
`aiScore` and threat **once, in the 8 x 8 block that contains its anchor**; a footprint reaching into a neighbouring
block adds nothing there [known].

**TerritoryMapElement** (0x30 bytes, per AI player and low-res cell): `cellId` (Unique of the AI cell that
covers it, -1 none) and `counters[7]` (u32) [known] struct layout; use of each counter:

| Counter | Raised by | Lowered by | Read by |
|---|---|---|---|
| 0 | failed military-building order at this place (+1) S 0059af60 | halved on order reset / success S 0059a1b0 | site query (divisor) S 005a8cc0, cell threat trigger (divisor) S 00594b20 |
| 1 | attack result 2: a started attack on a building in this area ended without the building changing owner (+1) S 005a8550 | halved when an attack slot is released S 005a8510 | target score divisor S 005a8750, attack threshold S 005a0dd0, catapult score S 00598e60 |
| 2 | catapult construction order ended with "no place found" (+1) S 00599020 | halved when an own catapult building in the cell is removed S 005836d0 | catapult site score divisor `(counters[2] + 1)^2` S 00598e60 |
| 3 | attack result 0 (no candidate building) and result 1 (candidates, no attack) (+1 each) S 005a8550 | halved S 005a8510 | target score divisor S 005a8750 |
| 4 | every own casern-type building added to the AI (+1 at the building's position, `Building::Init` S 00596ba0); barracks order ended with "no place found" (+1) S 00598000 | – | barracks site score divisor S 00597ea0 |
| 5 | attack result 1 (candidates existed but none was attacked) (+1) S 005a8550 | halved S 005a8510 | catapult score S 00598e60 |
| 6 | the building of a slot's secondary attack target still stands, has no fight (any more) and is not within 15 cells of a primary target (+1 on the slot's target area) S 005a0dd0 | – | chance of a secondary attack S 005a0910 |

The writers address the element at +0x14 / +0x1c / +0x24, which are `counters[1]` / `[3]` / `[5]` with the
array at +0x10 [known] struct layout, S 005a8550 (result 0: `[3]` +1; result 1: `[5]` +1 and `[3]` +1; result 2:
`[1]` +1; any other value: none), S 005a8510 (`[1]`, `[3]`, `[5]` each shifted right by one).

**ResourceMapElement** (per resource cell, a list): `{resourceId, sourceKind, amount, areaId}`. `sourceKind` 2 =
a resource object standing on a cell (good id of its deposit property, amount = remaining deposit stages);
`sourceKind` 1 = from the map's per-cell resource table, read only for a map cell without a resource object
(table amount 1000 is stored as 7; ids -1 and `0xA9676263` are skipped). `areaId` = continent id of the cell
[known] S 00587e90. Special resource ids used by fixed rules are good ids [known] `Goods.lua` `gp_create`:
`0xCD6EC133` = `wood`, `0x55E952D3` = `stone`, `0x4012E5A3` = `fish`, `0xA9676263` = `water`, `0x1D66B4AE` = `ship`.

### 2.3 NAI::Cell (0x160)

| Field | Meaning | Evidence |
|---|---|---|
| lowResX/lowResY (+0x24/+0x28) | cell position in AI-cell units | S 0059e1c0 |
| centre (+0x2c/+0x30) | representative map position: the position of the own building or harbour flag nearest (hex distance, strictly nearer replaces) to the geometric centre `(x*16+8, y*16+8)` of the 16 x 16 block, updated only when one is added to the cell, never when one is removed; initially the "connected position" found by the validator | S 00595610, S 0059df90 |
| continentId (+0x10c) | continent of the centre, filled once while it is -1 (unknown): a later change of the centre does not update it. Only `Cell::RefreshContinentId` S 005951b0 (caller `NAI::Player::Refresh` S 005830d0) resets and recomputes it | S 00595150, S 00595610 |
| depots (+0x34) | buildings whose property has `depot` (+0x54) (storehouses, headquarters) | S 005957a0 |
| default buildings (+0x48) | every building in none of the other lists | S 00595820 |
| military (+0x5c) | `soldierLimit != 0` and territory range > 0 | S 005958c0 |
| consumers (+0x70) | planters without a product: no product in slot 0 (`BuildingProperty` +0x44 == -1) and a `plantingDeposit` (+0xd4, `bp_setPlantingDeposit`) whose `DepositProperty.good` (+0x3c) is not -1, i.e. the forester type [known] S 00596700, S 00553040 | S 00595970 |
| kind-7 buildings (+0x120) | property working mode (+0x80) == 7 (Hunting) | S 005958f0 |
| caserns (+0x134) | property casern byte (+0xf1) | S 00595770 |
| kind-9 buildings (+0x148) | property kind (+0x80) == 9 | S 00595930 |
| productions (+0x84), needs (+0x98) | references | S 00595850, S 00595880 |
| harbors (+0xf8) | references | S 005957e0 |
| threat trigger (+0xac: active +0xb0, start time +0xb4, score +0xb8) | "this cell wants a military building" | S 00594b20 |
| no-depot trigger (+0xbc: active +0xc0, start time +0xc4) | armed at creation and when the last depot leaves, disarmed when a depot is added | S 005949e0, S 00594a70, S 005957a0 |
| demolish trigger (+0xe4: active +0xe8, value +0xf4) | "demolish a building in the cell": the first building of the default list whose `BuildingProperty` +0x3c equals the stored value [known]; +0x3c is `size` in the struct layout, so the value is a building size, not a type id [inferred]. Nothing arms it: `NAI::Trigger::Start` S 005a7960 has four callers (cell creation and last-depot removal for +0xbc, the threat trigger, CellFull) and none passes +0xe4; +0xf4 is only zeroed (S 00594780) and loaded. The trigger can therefore only be active when a loaded file says so, and no shipped file can: maps (`.s2m`) hold the map part only and the install has no file with a logic part that the game opens (`save-format.md` §2.6). It is never armed [known for the callers and writers; an untyped store is not excluded] | S 0058de80 |
| CellFull (+0xcc) | map goodId -> {trigger, expireCount}: "no room for this in the cell" | S 005a64e0, S 005a6430 |

A building is filed into exactly one list, by priority: military, depot, casern, consumer, kind 7, kind 9,
default [known] `NAI_AddBuildingToCell` S 005978a0. The castle (headquarters) type has no soldier limit, so it
fails the military test and lands in the **depot** list, not in the military list [known] S 005958c0,
S 005957a0.

**Unique ids drawn for a new building** [known] `OnBuildingAdded` S 00584030, `Building::Init` S 00596ba0: the
`NAI::Building` mirror takes the village building's own Unique (no draw); then, in this order, one Unique per new
production (§2.4), one per new need (missing inputs, consumer need, §3.3), and one for the AI cell when the
building founds a new one. At activation on a computer slot the ids therefore follow: the castle building
(`n`), its AI cell (`n + 1`), its flag (`n + 2`) [known] S 00581c40, S 00584030.

### 2.4 Need, Production, Building

- **`NAI::Building`** mirrors one village building: its cell, its productions, the needs "attached" to it
  [inferred] S 00596ba0, and six flag bytes that are set once and never cleared [known]
  `Building::UpdateTypeFlags` S 00596700: +0x40 military (`NVillage::Military::IsMilitaryBuilding` on the
  building's military component), +0x41 depot (property +0x54), +0x42 consumer (the planter rule of §2.3),
  +0x43 casern (+0xf1), +0x44 kind 9 (working mode 9), +0x45 mine (`size` +0x3c == 8 and working mode 6).
- **`NAI::Production`** = one unit of output of a product slot (0 or 1) of an own building: `Building::Init`
  creates `amount` productions per set slot (`bp_setGoods(b, good, amount)`) [known] S 00596ba0; key field: the
  produced good id (+0x18); references to its cell, its building and the need it serves [inferred] S 00597560,
  S 00595850.
- **`NAI::Need`** (0xd8) = "one more producer of good G is wanted". Fields: Unique, `typeId` = good id (+0x20),
  cell reference, production reference (+0x48, the producer that satisfies it), building reference (+0x68),
  resource position (+0x88, for needs bound to a deposit), `placementPending` (+0x94), two bytes copied from
  the good's property when the need is created: +0x95 = `GoodProperty.enableDeposits` (+0x50,
  `gp_enableDeposits`: harvested from map deposits) and +0x96 = `GoodProperty.enableFields` (+0x51,
  `gp_enableFields`: an underground / water resource field) [known] `Need::ctor_ForType` S 00597010,
  S 0046b620; they are what makes a need "resource-bound" (§3.4) and are not saved (recomputed by the ctor);
  child/parent need for group goods [known] `Need::Store` S 005972a0; [inferred] S 00593ea0.
  The same two property bytes are the "flag +0x50" and the "zone flag" named in §3.9.
  A need of a group good (good type 3 "EitherGroup") lives in `needsB` and is resolved into a child need of one
  member good (§3.4) [inferred] S 005841e0, S 005943c0.

A need and a production in the same cell with the same good are linked to each other as soon as both exist
(`Cell::AddNeed` / `Cell::AddProduction`) [inferred] S 00595880, S 00595850.

### 2.5 Player switches

Bytes of `NAI::Player`, all set to 1 by `Activate` and changeable from map scripts [known] S 00582870,
struct layout; setters in `lua-surface.md`:

| Offset | Name | Lua setter | Gates |
|---|---|---|---|
| +0x94 | expansionEnabled | `logic.ai_enableExpansion` | ExpansionSystem (arbitration and Expedition, S 00590fd0), CellClearing |
| +0x95 | coinProductionEnabled | `logic.ai_enableCoinProduction` | coin need, CoinProduction |
| +0x96 | needsEnabled | `logic.ai_enableNeeds` | NeedCreation |
| +0x97 | sacrificesEnabled | `logic.ai_enableSacrifices` | sacrifice manager (S 00582af0); the site planner only when it has no building type (§3.15) |
| +0x98 | catapultsLocalEnabled | `logic.ai_enableCatapultsLocal` | CatapultConstruction |
| +0x99 | waterStreets | copy of profile `ai_enableWaterStreets` | street and site searches may cross shallow water |
| +0x9a | shipConstructionEnabled | `logic.ai_enableShipConstruction` | ShipConstruction |
| +0x9b | forestingEnabled | `logic.ai_enableForesting` | ForesterConstruction |
| +0x9c | attackAllowed | `logic.ai_allowAttack` | AttackSystem |
| +0xb0 | forbiddenHarborPositions (vector of {x,y}) | `logic.ai_forbidHarborPosition` / `ai_allowHarborPosition` | Expedition, ShipConstruction (sea-route count), the harbour test of attack target selection (§3.12) |
| +0xc0 | enemyExclusions (vector of player index) | `logic.ai_forbidAttackingPlayer` / `ai_allowAttackingPlayer` | `Player::IsEnemy` |
| +0xd0 | bEnabled | cleared when the headquarters is lost | whole `Player::Update` |

`Player::IsEnemy(p)` = not in `enemyExclusions` and the game's `ai::player::Player::IsEnemyOf` [inferred] S 00583620. Adding
an exclusion also sets the flag byte for that player in the game player's military settings [inferred]
S 00584840.

### 2.6 AI profile (`AiProperty`, 0xd0)

See §6.1 for all fields, offsets, defaults and the values of the shipped profiles.

## 3. Rules and algorithms

### 3.1 Activation, deactivation, difficulty

- At game start every slot of kind "computer" is activated with profile key = computer level + 1, i.e. slot
  `aiLevel` 0 / 1 / 2 selects the profiles created as `"1"` (Weak), `"2"` (Normal), `"3"` (Strong) in `ai.lua`
  [known] `Game_CreatePlayersFromDescriptor` S 005abb60 (any other level value also selects `"1"`), `ai.lua`
  `properties.ai_create("1")`..`("3")`.
  Map scripts may activate any other profile with `logic.ai_enable(player, profile)` S 005b2660 (the campaign
  profiles `ai_c2_catapult`, `ai_c5_pirates`, `ai_c6_severin`) and stop an AI with `logic.ai_disable`
  S 005add10.
- `NAI::System::ActivatePlayer(playerEntry, startPos, profileKey)` S 00581c40 [known]: `Player::Activate`,
  then `OnBuildingAdded` for every existing own village building (order of the village building list) and
  `AddHarbor` for every flag of the player's flag list; `Player::AddHarbor` S 00584100 keeps only a flag whose
  reference at +0x17c is set ([inferred] its navy object, as `NNet::Flag::LinkNavyObject` is the other caller).
  On a computer slot the id order is castle building, AI cell (castle + 1), flag (castle + 2) (§2.3) [known].
- `Player::Activate` S 00582870 [known]: stores the start position and its continent id, resolves the profile,
  activates every module, creates the two per-player resource annotation grids, sets all switches of §2.5 to 1
  and `waterStreets` to the profile value.
- **Deactivation** S 005839a0: the AI of a player is deactivated when it owns **no AI cell** at an AI tick
  (`System::Tick` S 00581a30 [known]), on `ai_disable`, and on game reset. All needs, productions, building
  mirrors, cells, harbours and attack watches are dropped. The player's buildings stay in the world.
- **Headquarters lost**: when an own building whose property has depot + casern + territory-building all set
  (the headquarters/castle type) is removed, `bEnabled` is cleared: `Player::Update` does nothing from then
  on, but the player stays "active" [known] S 005836d0, S 00582af0. Nothing sets `bEnabled` again except
  activation and load.
- **Defeat and victory** do not touch the AI: `Player::Deactivate` S 005839a0 has exactly four callers (the
  no-cell test of `System::Tick`, `System::Reset`, `Player::Load`, `logic.ai_disable`) and no AI function reads
  the victory conditions [known for the caller list; `players-victory.md` §3.6 for the victory side]. A
  computer player that is out of the game stops because losing its last castle clears `bEnabled`; a computer
  player on the losing side that still has a castle keeps playing after a winner is declared.

What the **difficulty** changes is exclusively the profile (§6.1). The code reads the profile in these places
[known unless tagged]:

| Profile field | Effect |
|---|---|
| `startFrameProducerCount` | number of first-stage needs for the first construction-good input (§3.3) |
| `maximumSmithies` | cap on producers per weapon good (§3.10) |
| `maximumMints` | cap on coin producers; 0 disables the coin need (§3.3, §3.10) |
| `militaryMode` | attack threshold formula (§3.12); 0 Safe also treats ratios < 0.5 as hopeless |
| `factors[2][2]`, `battleCalcRatio[3]` | fraction of soldiers sent / defence score (§3.12, §3.13) |
| `swordBowRatio` | wanted share of kind-0 soldiers in military buildings (§3.11) |
| `retreatChance`, `destroyLostBuildingChance` | §3.13 |
| `streetOptimizing`, `routeOptimizing` | StreetOptimizer / StreetRouteOptimizer on or off (§3.7) |
| `catapultsEnabled` + catapult factors + `catapultConstructionTime` | §3.14 |
| `waterStreets` | streets and site paths may use shallow water |
| `allocationEnabled` | MilitarySettings tuning (§3.11), catapult score scaling |
| `sacrificesStartTime`, `sacrificesLimit`, favourite sacrifices | §3.15 |
| attack limiter (delay, delayRandom, attackCount, attackCountRandom) | §3.12 |
| `constructionTicker` | period of the site search / placement step (§3.5): Weak 7, Normal 3, Strong 1 ticks |
| special attack/defence fields (+0x8c..+0x9c) | secondary attack (§3.12), ignore-attack roll (§3.13); never set by `ai.lua`, defaults apply |
| `coinArrangement` (+0x2f) | no reader: the decompiled code of the whole binary holds no access to profile +0x2f other than the setter and the ctor default [inferred from a text search of the function cache; a byte read through an untyped pointer could escape it] |
| `factors` index 1 = `factor(Attack, Enemy)` (+0x38) | no reader: the getter S 00555d10 has three callers, which read index 0, 2 and 3 (§3.12, §3.13) [known] |

### 3.2 Cells

`CellSystem::Update` S 0058aac0 [known] runs five sub-steps on their own periods (§4).

**CellValidator** (every 5 ticks, one AI-cell position per call, row-major sweep over the whole map)
[inferred] S 0059df90, S 0059de60, S 0059d950:

1. If no `NAI::Cell` exists at the position and one of the four corner map cells of the 16 x 16 block
   (`x*16, y*16` .. `+16`) is **owned by the player** (`NAI_CellPosition_AnyCornerHasGridValue` S 00596000
   compares a per-map-cell grid with the player index [known for the argument; inferred that the grid is the
   ownership grid]): look at the position itself and its neighbours that already have a cell; for each,
   search the perimeter of the new block (top row, bottom row, left column, right column, in that order) for
   a map cell that is owned by the player and has the **same continent id** as that neighbour cell's centre
   (the per-cell continent grid also read by `Cell::EnsureContinentId`). On the first hit: create the cell and
   set its centre to that map cell.
   The first cell of a player is created by `OnBuildingAdded` (find-or-create the cell under the building)
   S 00584030 [inferred], not by the validator, which needs an existing neighbour cell.
2. If a cell exists, holds no building and no harbour (`Cell::IsEmpty`) and the corner test of step 1 fails
   (the player owns none of the corners any more): remove the cell.

Edge cases of the validator [known]:
- The perimeter search clamps the block's end to `size - 1` of the map, so the map's **last row and last
  column are never tested** S 0059d950.
- `IsInterior` S 005a7dc0 excludes row 0 and column 0, so a neighbour position in the first AI-cell row or
  column is never used as the continent reference of step 1.
- The corner test S 00596000 reads the first corner without a check and only then tests the others.

**CellFull expiry** (every 37 ticks, all cells): a "full for good G" mark is cleared once game time exceeds its
start time + `expireCount * 600` s; `expireCount` is then incremented (linear back-off) [known] S 005a6430.
`expireCount` starts at 0 (`CellFullElement::ctor` S 005a61c0) and is never reset, so the first mark of a good in a
cell is cleared at the next expiry step (at most 37 ticks later), the second lasts 600 s, the third 1200 s, and
so on. `MarkFull` S 005a6fe0 does nothing while the mark is already set [known].

**Threat trigger** (recomputed whenever a building of the default, military, consumer, kind-7 or kind-9 list
is added to or removed from the cell and whenever a harbour is added; not for depots and caserns) [known]
S 00594b20 and its 11 callers:

```
score = ( (E0 - E2) / 100 + (#default buildings - 5 * #military buildings) ) / (territory.counters[0] + 1)
E0 = enemy-minus-allied 3x3 sum of MilitaryMap value[0] at the cell centre   (§3.11)
E2 = enemy-minus-allied 3x3 sum of MilitaryMap value[2]
```

`score > 0` arms the trigger (start time = now, stored score) if it was off; `score <= 0` disarms it.

**CellExpansion** (every 19 ticks) [known] S 0059e1c0: if it has no open request, among cells with an armed
threat trigger pick the maximum of `(now - trigger.startTime) * trigger.score`; restart that trigger and post
an **expansion request of kind 2** at map position `(lowResX*16, lowResY*16)`.

**CellDepotCreation** (every 1423 ticks) [known] S 0059e4c0: if no depot order is pending, among cells whose
no-depot trigger is armed and whose demolish trigger is off, pick the one with the **earliest** trigger time
(the best time starts at "now", and only a strictly earlier one replaces it, so a trigger armed at the current
game time is never picked); request construction of the tribe's plain depot type (first tribe building with `depot`
and not (casern and territory building), S 0059f940) in that cell with priority 15; restart the trigger.

**CellClearing** (every 53 ticks, one AI-cell position per call, the same row-major sweep over the whole map as
the validator; a position without a cell does nothing) [known] S 0059d500, S 005a7d90. The gates below are tested
**before** the cursor advances, so while one fails the sweep stands still [known]. Only if no order of its
own is pending, its own enabled byte (set by its `Activate` S 0059d490) is set, `expansionEnabled`, and the tool
stock is at least 10 (`NAI_IsCountBelow10` S 00582f00 tests the tribe's `workerToolGoodId`). With `count` =
`Cell::CountObjectsOfType(output good of the producer's slot 0)` and `A` = amount, on the cell's low-res resource
element, of the entries of `sourceKind` 2 (resource objects standing on the map) on the continent of the cell
centre (`CellSystem::GetResourceAmountForCell` S 0058a990, `ResourceMapElements::GetAmount` S 0059c240), of the
resource id stored in that output good's `GoodProperty` +0xbc:

- producer type B = first tribe building with working mode 1 producing from resource `0x55E952D3` (`stone`): if
  `count < 2` and `A > 5 * count`, order it (priority 10) and stop;
- producer type A = same for resource `0xCD6EC133` (`wood`): if `count < 2` and `A > 5 * count + 5`, order it
  (priority 10).

Both lookups walk the tribe's building list in script order and return the first type that has a product in
slot 0, working mode 1 (Mining: woodcutter, stone pit) and whose product good has `GoodProperty.miningGood`
(+0xbc, `gp_setMiningGood`: the tribe-neutral resource a tribe good stands for, e.g. `stoneScots` -> `stone`)
equal to the wanted resource [known] `AiTribe_FindMode1ProducerOfResource...` called from S 0059d490;
`properties-data.md` §2.4 for the field. A/B are therefore the tribe's woodcutter and stone gatherer.

### 3.3 Need creation (the build order)

`NeedCreation::Update` S 0058d370 [known], every 47 ticks, only with `needsEnabled`. `depot` = first own
building with the depot flag (normally the headquarters); every need created here is attached to it. The
stage-1 needs for `C[0]` are linked to `depot` without a test that one exists [known].
`C` = the input list of the tribe's `constructionGoodId` (a "WareGroup" good with two inputs, e.g.
Bavarians: `plank`, `stoneBav`, `Goods.lua` `gp_addCost(constructionResourcesBav, ...)`).

| Stage change | Condition | Needs created |
|---|---|---|
| 0 -> 1 | game time > 0 | `max(1, profile.startFrameProducerCount)` needs for `C[0]`, then 1 need for `C[1]` |
| 1 -> 2 | game time > 300 s **and** for every good of `C` the number of productions of that good, summed over the AI cells, is above 0 | if `profile.maximumSmithies != 0`: for soldier kind 0 and 1, one need per input good of the level-0 soldier good (`MilitaryConfig::GetSoldierId(tribe, kind, 0)`); then set `Casern.placementEnabled` (MilitarySystem+0x268) |
| 2 -> 3 | game time >= 800 s | if the tribe has a `secondCarrierId` (!= -1) with a non-empty input list: one need per input good |
| 3 -> 4 | game time > 1200 s | if `coinProductionEnabled` and `profile.maximumMints != 0`: one need for `soldierUpgradeGoodId` |

Independently of the stage, **periodic growth**: whenever game time > `periodMultiplier * 600` s
(`periodMultiplier` starts at 1 and doubles each time: 10, 20, 40, 80 ... minutes), for each of `C[0]` and
`C[1]`: if the stock of the good (gamePlayer+0x34) is below `quota / max(1, number of existing needs of that
good)` (integer division; needs counted over `needsA` and `needsB`, S 00582c90), add one more need, attached to
`depot`. The two tests are independent. [known] disassembly S 0058d815 .. S 0058d9a4, constants at S 007ea010
(1/32), S 007e6248 (1/16), S 007ea018 (600.0):

```
quota(C[0]) = trunc(territory / 32)
quota(C[1]) = trunc(territory / 16)
```

The game time does not enter the quota; it only decides when the test runs. `periodMultiplier` is doubled
whether or not a need was added.

`territory` = `PlayerStatistics.regionSize` (+0xa4 of the player's statistics record,
`NLogic::Statistics::GetPlayerStatistics` S 005370e0): the number of map cells the player owned at the last
territory sample of the statistics system (`players-victory.md` §2.5, §3.11 step 0) [known for the read;
meaning from that document]. It is the same value that is divided by 9216 = 96 x 96, by 128 and by 48 in the
rules of §3.9, §3.10 and §3.11.

Other creators of needs:

- **Missing inputs** [known] S 00596ba0, S 00596af0, S 005969e0: when a building is added whose type has a
  product in slot 0 and either not `ignoreGoodCosts` (`BuildingProperty` +0xf0) or working mode 7, then for
  each set product slot and each input good of that product an existing need without a building, or else a
  new one, is attached to the building. `Building::RequestMissingInputs` (callers: WeaponProduction and
  CoinProduction, §3.10) does the same under the same type condition for every input of the slot-0 product of
  which **the building's own stock holds 0**.
- **Consumers** [known] S 00596ba0: a building with the consumer flag (§2.4, the forester type) gets a need
  (existing without a building, or new) for the good of its planting deposit.
- NeedsArrangement queues a missing input (§3.4), LockSmith (§3.9), CoinProduction / WeaponProduction (§3.10),
  SacrificeSitePlanner and the sacrifice manager (§3.15).

### 3.4 Need arrangement (which cell)

`NeedsArrangement::Update` S 00594650 [known], every 13 ticks: walk `needsB` until one group need was
instantiated, then walk the needs of `needsA` that have no cell until one `TryPlaceNeed` returns true.

**Group needs** S 005943c0 [known]: a need for an "EitherGroup" good is turned into a child need for one
member good chosen by **weighted random**, weight = the member good's `gp_setAiRandomValue` (GoodProperty
+0x8c; e.g. `bread` 6, `fishScots` 10, `sheepHam` 1, `fleshham` 5 in `Goods.lua`): the members of the group
for the player's tribe are laid out as cumulative weights and `rand % totalWeight` picks the first member
whose cumulative weight is above the roll. The members are the tribe's goods list filtered by the group good's
cost list, in tribe list order [known] `PropertyGroupIter` S 007767c0 / S 00776690. The cumulative weights are
the keys of a map keyed by the running total, so a member with weight 0 has the same key as the member before
it and **replaces** it: that earlier member can never be chosen [known] S 005943c0. A group need that already
has a child is left alone unless the child has no cell **and** is queued with the ResourceSystem
(`placementPending`, step 3 below); only then is the child removed and a new one rolled among the members that
have neither `enableDeposits` nor `enableFields`.

**Placement** `TryPlaceNeed` S 00593ea0 [known]:

1. Inputs check (S 00593aa0): unless the good has `gp_setAINoNeedForCosts` (GoodProperty +0xa4 = 0; set for
   the stone goods), every input good must either exist as an object in some AI cell or be in stock with at
   least 6. If not (S 00593b50): for the first such missing input for which no need without a building
   exists, add a need for that input and end this update's walk; when every missing input already has such a
   need, the walk goes on with the next unplaced need. The original need is not placed this round.
2. **Plain needs** (neither `enableDeposits` nor `enableFields`, or the good is the one the tribe's first
   working-mode-2 building plants, `AiTribe_GetPlantedResourceOfMode2Building` S 0059faf0): among cells with
   `Cell::CanAcceptNeed` (S 00594a20: cell not marked full for the good; fewer than 20 needs in the cell,
   a limit that does not apply to a need with `enableFields`) choose the **lowest**

   ```
   cost = 50 * (needs of this good already in the cell)
        + sum over input goods of minDistanceToSupplier(cell centre, input)
        + minDistanceToConsumer(cell centre, good)
   ```

   The two parts are combined with a cut-off: when the first two terms together reach 100000 the cost is the
   consumer distance alone; else when the consumer distance is 100000 it is left out.
   `minDistanceToSupplier`: smallest hex distance to a cell that has a free production of the input (counted
   at half distance, integer division) or any object of that good (full distance); 100000 if none S 00593c20.
   `minDistanceToConsumer` S 00593cd0: over every good `K` of the tribe's good list whose type is not 1 and
   whose cost list contains the good, and every AI cell: `d` = half the hex distance if the cell has a free
   production of `K`, the full distance if it holds an object of `K`, else the best value so far; the value is
   `d * (needs of the wanted good in that cell + 1)`; the minimum counts, 100000 if there is none.
   The first acceptable cell is the choice until a cell with a cost below 100000 and below the best beats it.
   No acceptable cell: post an **expansion request of kind 3** at the start position (if none is open) and
   leave the need unplaced.
3. **Resource-bound needs** (mines, gatherers, planters), only while the need is not queued with the
   ResourceSystem (`placementPending` clear): for every acceptable cell ask
   `ResourceMapAdds::FindBestOwnedCellInLowResCell` for a resource cell (4 x 4) inside the AI cell that holds
   the wanted resource, is not claimed by another need, and whose corners are owned by the player and not
   blocked (map flag bit 5). For `sourceKind` 1 resources at least 2 qualifying corners are required and the
   cell with the largest amount wins; for other kinds the first cell with one qualifying corner S 0058f770.
   Cell cost = first-input distance (input 0 only) + consumer distance, combined with the same cut-off; the
   first cell that yields a resource cell is taken whatever its cost, a later one only with a strictly lower
   cost. The chosen resource cell is **claimed** by the need (a previous claim of the need is released first).
   None found: the need is handed to the **ResourceSystem** (§3.8), which looks for the resource outside the
   territory, and `placementPending` is set (S 00590320).

Ties: the first cell in the cell vector (creation order) wins, because all comparisons are strict [known]
S 00593ea0. The cost terms above are read line by line from S 00593ea0, S 00593aa0, S 00593b50, S 00593c20 and
S 00593cd0 [known].

### 3.5 Construction selection and the order pipeline

**Selection** `NeedsConstruction::SelectConstruction` S 00593190, every 17 ticks, only when its own order slot
is free [known]. For every good `G` that has at least one need of `needsA` with a cell (goods in ascending id
order; the best score starts at 0 and must be beaten strictly):

```
planned  = number of placed needs for G
existing = number of own productions of G
skip G unless ProductionControl::IsProductionWanted(G)       (§3.9)
skip G unless CanStaffProducer(G)                            (below)
score(G) = (planned - existing)
         * aiPriority(G, tribe)                               -- gp_setAiPriority, e.g. stone 300, tool 150
         * max((100 - max(stock(G) + stock2(G), 1)) / 100, 0.001)
         / max(existing, 0.2)
         * max(averageProductivity(G), 0.1)                   -- statistics, 1.0 when no producer exists
```

`averageProductivity(G)` (`GetAverageProductivity`) is the mean over the player's production units of `G`
(§2.4), i.e. a building with an amount of 2 counts twice [known] S 00593190.

`stock` = the player's stock (gamePlayer+0x34, `pStock`: goods stored in the player's buildings), `stock2` =
the second stock object at gamePlayer+0xa0 (`pMobileStock`: goods and units outside buildings). Both are caches
that the player update refills once per 22-tick cycle (`players-victory.md` §3.9), so every stock test of
the AI sees values up to 22 ticks old. The highest score wins. `CanStaffProducer` [known] S 00592df0: the
producer building's worker (job good, BuildingProperty +0x90) must be in stock, or one of the plain goods
(type 0) in the worker's cost list (its tool) must be in stock; it also holds when the good has no producer
type, or when the worker's cost list is empty or names no plain good.

For the winning good, the first need in `needsA` order that has a cell and no production linked (production
reference +0x48 unset) becomes a **construction request** [known] S 00593190, S 00593070: building type = the
tribe's producer of the good, priority 10, position = the cell. The producer comes from two maps good ->
building type built at activation and load (`RebuildTypeMaps` S 005936e0, `FindProducerBuilding` S 00592c40:
first tribe building that produces the good in slot 0 or 1): the normal map holds only types with
`size != 8` and working mode != 3, the "special" map only types with `size == 8` or working mode 3. The
special map is used when the need has a resource cell in which the first entry of the wanted resource has
`sourceKind` 1 and no entry of it has another kind. A need that is not special and has `enableFields`
without `enableDeposits` gets **no request**: its resource claim is released and it is detached from its
cell, so arrangement places it again. The request's target is set with `InitAtCell` S 005a17e0 (by cell) or
`InitAtPos` S 005a1650 (by position and radius); each writes only its own fields and leaves the other target
fields of the order as they were [known].

**Arbitration** `ConstructionSystem::Tick` S 00592210 [known]. Order owners register with the construction
system in this order [known] `ConstructionSystem::Activate` S 00592a20 (called first), then `Player::Activate`
S 00582870: ForesterConstruction, ShipConstruction, ConstructionHunter (§7; it never offers a request),
NeedsConstruction, CellDepotCreation, CellClearing, MilitaryBuildingCreation, CatapultConstruction, Casern.
The sacrifice site planner is not an order owner: it only adds a need, which NeedsConstruction builds (§3.15).
Each owner offers at most one request `{buildingType, position or cell, radius, priority, timestamp}`.
The owner id stored with an order [known]: CellDepotCreation 1, NeedsConstruction 2, MilitaryBuildingCreation 3,
ForesterConstruction 4, CellClearing 6, ShipConstruction 7, ConstructionHunter 8.

- Every 600 ticks: `backoffCounter = backoffLimit = 0`.
- **No active order**, every 50 ticks: if `backoffCounter < backoffLimit`, increment `backoffCounter` and do
  nothing else. Otherwise, only if the stock of the tribe's `workerToolGoodId` is not 0: poll every owner;
  the request with the highest `(now - timestamp) * priority` wins (strictly greater, starting from 0, so a
  request posted at the current game time cannot win; owners in registration order) S 00592070 and is handed to
  `BuildingConstruction`.
- **Active order**, every `profile.constructionTicker` ticks: one step of `BuildingConstruction::Update`:

  | State | Action | Next |
  |---|---|---|
  | 1 CheckCost | does the player's stock hold **twice** the building's two cost lists (`BuildingProperty` +0x58 and +0x68, each added twice to the tested set: frame cost x 2 + cost x 2)? In cell mode with no AI cell at the request position: 5 | 2 (start the place search) / 4 |
  | 2 Searching | one `SearchConstructionPlace::Update` step: up to 10 candidate cells, ending early after the first cell that gets as far as `ScoreSite` (§3.6) | 3 found / 5 none |
  | 3 Place | still placeable: place the building through the village system | 6 / back to 1 |
  | 4 cannot afford, 5 no place | owner callback `OnOrderFinished(arg)` with `arg = (state != 5)`: 1 = could not afford, 0 = no place found; the owners penalise the place only for 0 | idle |
  | 6 placed | owner callback with the result position; `backoffLimit = 2 * backoffLimit + 2` | idle |

  [known] S 005a1ac0 for the state bodies and S 00592210 for the dispatch; [inferred] that the lists +0x58 / +0x68
  are the frame cost and the cost (`bp_addFrameCost`, `bp_addCost`).

`backoffCounter` is not reset by a placement, only every 600 ticks. `backoffLimit` is 2, 6, 14, 30 ... after the
1st, 2nd, 3rd ... placement of a window, so the AI skips `2, 4, 8, 16, ...` polls of 50 ticks before it looks at
requests again: at most 3 placements per 600 ticks (one minute at speed 1) [inferred from the constants]. Orders
that end in state 4 or 5 do not raise the limit.

Priorities used: NeedsConstruction 10, CellClearing 10, ShipConstruction 10, CellDepotCreation 15, military
building 20 (0x14), catapult 20, casern 30 (0x1e), forester 50 (0x32) [known] at the respective call sites.

**Failure handling per owner**: NeedsConstruction, when no place was found (callback argument 0) and both the
AI cell at the order position and the need still exist: if the need is still filed in that cell, the cell is
marked "full" for the need's good (`CellFull::MarkFull(cell, need.typeId)`); a resource-bound
need releases its claim; and in every case the need is detached from its cell, so that arrangement places it
again. When the order could not be afforded (argument 1) it only clears its order slot, and the need stays
where it is [known] S 00592b30. On success its `OnPlaced` S 00592b10 does nothing but reset the order
slot [known]. Military owners: §3.8.

### 3.6 Site search inside a cell

`SearchConstructionPlace` [known] S 005a91e0, S 005a9080, S 005a8e40, S 005a9010:

- Two modes: **cell mode** (request by cell: walk the 16 x 16 block of the AI cell, origin = cell centre,
  radius 8) and **ring mode** (request by map position and radius: hex rings around the position).
- Per candidate cell: off-map, `GameQuery_BuildingTypeFitsCellFlags` false, or no free owned cell around the
  building's flag position (flag = neighbour in direction 1; of the 6 cells around the flag the loop of
  S 005a8ee0 tests five: it starts on the flag's neighbour in direction 4, steps in directions 0..4 and tests
  after each step, so that starting neighbour is never tested [known]) -> rejected cheaply.
- Otherwise `s = GameQueryHelper::ScoreSite(player, type, cell)` S 00534830. If `s` beats the best so far, the
  walking path from the search origin to the candidate is computed (map A*; with `waterStreets` the AI's
  construction path analyzer, where a cell with map state bit 2 costs 1 if it is shallow water and is blocked
  otherwise, and a cell with bit 7 is blocked, S 005893a0); no path counts as 1000000, the origin itself as 0.
  The path length is the step count of the found path (`GetPathStepCount` S 00676a90) [known].
  With `D = maxDistance` (the radius): the candidate is kept only if `pathLength < 2 * D` and
  `s * (2D - pathLength) / (2D)` beats the best.
- The best score starts at 0.0 in both modes and for every owner, so only a site with a positive weighted
  score is taken.
- Budget and order [known] S 005a91e0, S 005a9080, S 005a1820, S 00600e90, S 005a8ad0, S 005a8e40,
  S 005a9010: each `Update` evaluates up to 10 candidates and stops after the first candidate that reached
  `ScoreSite` (a cheap rejection does not count; the path search runs only when `s` beats the best). Cell mode
  walks the block row by row from map cell (16 cx, 16 cy), column fastest, and ends after 16 rows. Ring mode
  starts on the origin itself (ring 0), then ring r = 1..`maxDistance`: the cursor steps once in direction 4
  (to origin + r x dir 4), then r steps in each of the directions 0..5, and the cell after each step is a
  candidate (so origin + r x dir 4 comes last); it ends after the last ring. A candidate
  replaces the best only with a strictly higher weighted score, so the first of equal sites wins.

**`ScoreSite(player, type, pos)`** [known] S 00534830 (the body; the helper terms are [inferred] from one read
of each helper). `bp` = the building property, `R` = `bp.workingRadius` (+0x78). It has two callers: the site
search above and the demolition rule (§3.9). Steps, in this order; "=" replaces the score, "+=" adds, "x"
multiplies:

1. `score = 1.0`.
2. Base term.
   - `bp` has no product in slot 0, or working mode 7 (Hunting): if `bp.plantingDeposit` names a deposit with a
     good: `score = supplier(that good)`.
   - Otherwise, with `G` = the slot-0 product: if `G.enableDeposits` and `bp.size != 8`:
     `score = ` number of deposits of `G.miningGood` in the flood-fill area of radius `R` around `pos`
     (S 00540940; the fill spreads over cells that hold a deposit or are walkable and counts the undepleted
     deposits of the mining good [known] S 00542890 / S 00542900); else if `G.enableFields`: `score = ` sum of the map resource amounts of `G.miningGood` in the
     same kind of flood-fill area of radius `R` (amount 1000 counts as 7, S 005409f0); else if `G` has inputs:
     `score = ` sum over the inputs of
     `supplier(input)`; a product without inputs keeps 1.0.
   - `supplier(g)` S 00532640: the nearest own building of the type that produces `g`
     (`PropertiesDb::FindBuildingProducingGood`; search radius 1000): `max(1, 15 - hexDistance)`, or 0.1 when
     there is none. The type is the **first** producing type of the whole building property map (not
     restricted to the player's tribe), and the nearest building of it counts in any construction state:
     construction sites included (`completedOnly` 0) [known] S 00557830. When no building type produces `g`, the building is instead the nearest own finished
     building of the village's depot list (+0x20), without a distance limit, whose continent is reachable
     from the continent of `pos` (`BuildingList_FindNearestReachable` mode 1: connected for the player by
     sea, or listed in the building's network continent ids) [known] S 005586d0, S 00557fe0.
3. Working mode 7: `score = ` hunting term S 00532540: `(R - distance)` to the nearest huntable animal within
   `R`, plus `(R - distance)` to the **first** animal spawn point within `R` that can give the product (spawn
   point list order, not the nearest) [known] S 0052cae0 / S 00539060; 0 when neither exists.
4. Working mode 2 (Farming): `score += ` number of the 12 cells of the hex ring at distance 2 where the planting
   deposit can be placed or that already hold a resource object of the same good (S 005326e0).
5. `territoryBuilding`: `score = ` territory term S 005345d0 (it walks the village's territory building list,
   +0x3c [known]): 0 when an own territory building is closer than 5 cells; else (number of cells in the hex rings 0..`bp.territoryRange` that lie on the continent of `pos` and
   are not owned by the player) + (distance to the nearest own territory building, 100 when there is none);
   0 when no cell is gained and that distance is below 6.
6. `depot`: `score = ` 0 when an own depot-type building is closer than 11 cells (hex distance <= 10), else 1
   (S 00533760).
7. `casern`: `score = ` 0 when an own building of the village's casern list (+0x74) that is not a depot is
   closer than 11 cells (hex distance <= 10), else the result of `MinDistanceToEnemyMilitaryBuilding(pos, player, 1, 1)` (S 00534230
   calling S 005337e0; 1000 when the player has no such enemy building or harbour): farther from the enemy
   scores higher.
8. Spacing from farms, only if `bp.size != 8`: `d = 4`, or 3 when the type itself has working mode 2; `F` = the
   first building type of the tribe with working mode 2 (S 00533ab0); if an own building of type `F` other than
   one standing exactly on `pos` lies within `d`: a territory building gets `x 0.5`; any other type gets
   `x 0.2` when the distance is above `d / 2` (integer division) and `= 0` otherwise.
9. Blocked surroundings, only if not a territory building and `bp.size != 8`: walk the hex ring of radius 3
   around the flag cell (the neighbour of `pos` in direction 1; 18 cells); the first cell whose map state has
   bit 5 (0x20, **territory border**) set gives `x 0.4` once [known] S 00534830.
10. Site class: `f = ConstructionMap::GetCellFlags(pos, player)` S 00675740; `x 0.5` when (`f & 2` and
    `size & 1`) or (`f & 4` and `size & 1`) or (`f & 4` and `size & 2`). `ConstructionMap_ComputeCellFlags`
    S 00675610 stores 7 / 3 / 1 when a size-4 / size-2 / size-1 building fits, so flag 2 = a medium building
    fits and flag 4 = a large one fits: a small type on a medium or large plot, or a medium type on a large
    plot, is halved [known] S 00534830, S 00675610 (`map-resources.md` §3.5).
11. Each of the 6 neighbours of `pos` whose map state has bit 17 (0x20000, **ship ground**) set: `x 0.4`
    (cumulative) [known] S 00534830.

The bit names are those of the cell state word in `map-resources.md` §2.3 and `../map-format.md` §5.4 [known].

### 3.7 Streets

All street work goes through the shared `StreetPathAnalyzer` (A* cost callback) [known] S 005898a0,
S 005894a0, S 005896d0:

- a step is rejected if the cell is farther from the goal than 4 x the start-goal distance, or in the
  excluded list (the start cell excepted); the target cell must be free and owned by the player
  (`IsOwnedCellFree`); a cell with a street (bit 1) is passable only as the start cell or when it carries the
  street latched by `PlanBetweenFlags` (the first street met that ends at the start flag); a cell with an
  object in layer 0 only as the start cell; step cost = map step cost in both directions summed;
- with the water option of a plan, for a cell with map state bit 2 (0x4 water) (S 005896d0 [known]): the cell
  is allowed only if one of its **6 neighbours** is a cell without bit 2 that holds an object in object layer 0
  or can take a flag of the player; the cell itself must have no street (bit 1), no object in layer 0 (unless
  it is the start cell), bit 5 (0x20 territory border) and bit 16 (0x10000 moving-ship tile) clear, bit 10
  (0x400 logic object) clear unless terrain is ignored, and be owned by the player. Cost 8 when bit 3 (0x8
  shore) is set, else 5 on shallow water, else blocked. The shore pass gives 0x8 only to non-water cells and
  the water pass clears 0x8 first (S 0067b150, S 0067b390), so on a water cell the cost-8 branch is reached
  only when a map file carries an inconsistent bit [inferred]; a reimplementation keeps the test as written.

**StreetConstruction** (every 7 ticks) [known] S 005a3ed0, S 005a3d00, S 005a34a0, S 005a2400, S 005a2950:
- Cursor `step` over the player's flag list (`NNet::System` flags of the player, list order); at the end of
  the list it wraps to 0, clears its map and resets the search. The current source is remembered by the flag's
  64-bit Unique: when the flag at the cursor has that id the search goes on; a lower id ends the update; a higher
  id becomes the new source (after a reset when retries or tried targets are pending), and its cell is put on
  the tried list so the search never finds the source itself.
- Search (S 005a3d00): a flag with neither a building (+0x1c) nor a navy object (+0x17c) advances the cursor.
  Otherwise a breadth-first flood fill from the flag's cell (S 005a2db0) over cells that are walkable or
  shallow water (always allowed here), have map state bit 7 (0x80 deposit) clear and lie within hex distance
  10 of the source (S 005a94e0), stopping at the first cell with a flag of the player whose walking-net
  continent differs from the source flag's, i.e. a flag **not yet connected** to the source (S 005a9580
  [known]). Nothing found: cursor + 1 and reset.
- A source flag that already has a street does not connect to a found flag without one: that flag joins the
  tried list and a retry is counted. A found flag is first only remembered (`lastTarget`: the latch is on
  the found flag, not on the source); while the same flag is found again, each update runs the next strategy
  step 1..7 of `EvaluateStrategy`. When step 7 built something the cursor moves on and the search is reset;
  otherwise the next update puts the target on the tried list and counts a retry. The constructor
  S 005a33e4 starts the strategy step at 7, so the first target found after activation is skipped once
  [known].
  A retry (S 005a2950) clears the strategy state (costs 1000 / 1000, step 0); the 6th retry moves the cursor on
  and resets the search (S 005a2400).
- Strategy steps (S 005a34a0; costs are path lengths, `best` and `best2` start at 1000):
  1 direct plan source -> target, kept if `len < best`; 2 for every street of the target flag of type 0 or 1,
  every inner path cell where a flag may stand: plan source -> cell, kept if `len < best` (the cell is
  remembered); 3 / 4 `PlanBetweenFlags(source, target)` and, if `len1 <= best`, a plan from the target (3) or
  the source (4) flag to that plan's end cell, kept if `len2 < best2` (sets both costs); 5
  `PlanBetweenFlags` and, if `len1 <= best`, for every path cell where a flag may stand a plan from the
  plan's end cell to it, kept if `len2 < best2` (the cell is remembered); 6 direct plan with the player's
  `waterStreets` switch (+0x99), kept if `len < best`. Step 7 builds the best: 1 street to the target; 2 to the
  remembered cell; 3 / 4 remove the street found by `PlanBetweenFlags`, build source -> target, then a street
  from the target (3) or the source (4) to the plan's end cell; 5 remove that street, build source -> target,
  then from the removed street's end flag that is not the target to the remembered cell; 6 plan again with
  water and build in segments. Every street is built through the AI's own street planner
  (`BuildStreetTo` S 005a3050), and each built street draws **2 Uniques** (§8) [known].
- A planned path is accepted only if its number of steps (cells minus one) is at most **twice the hex
  distance** of its two ends [known] S 005a96b0, S 005a97d0, S 005a3050. Both planners walk the search result
  back with the randomised path walk, so among equally cheap routes the choice is random and consumes logic
  random numbers (§8) [known].
- `BuildPathInSegments` S 005a3170: walks the path and, wherever map state bit 2 (0x4 water) changes, puts a
  flag on the first land cell (water -> land) or the last land cell (land -> water), using an existing flag
  or a nearby flag spot when none can be placed, and builds the segment up to it; a segment that ran over
  water is built with street type 2, a land segment with type 0 [known].

**StreetOptimizer** (every 67 ticks, profile byte +0x2c `streetOptimizing`) [known] S 005a4550, S 005a44b0:
cursor over the player's street list (wraps to 0); unless the street's type (+0xe4) is 2 or 3, places a flag
on the first cell of its path, in path order, where `CanPlaceFlagAt` holds; cursor + 1.

**StreetRouteOptimizer** (every 37 ticks, profile byte +0x2d `routeOptimizing`) [known] S 005a5730,
S 005a52c0, S 005a4f30, S 005a47e0: walks the AI building map (key = Unique, ascending) from the current key;
a building with the consumer flag (§2.4) is skipped; a key above the current one is adopted and processed on
the next update; past the end the key restarts at -1. For the current building, `stage` selects one partner
per pass (S 005a52c0):
(Every "connected by road" depot search here runs on the goods net, kind 0 [known].)
- construction site (a remaining construction float > 0), stage 0 only: the nearest depot connected by road
  to the site's flag that holds one of the goods of the input list of the tribe's good +0xb4 (the first good
  of that list for which one is found);
- depot (flag +0x41): the first depot of each of the neighbouring AI cells (3 x 3 around its cell, its own
  cell excluded), one cell per stage;
- other finished building: stage 0 the nearest depot connected by road to its entrance flag; if there is
  none, stage 1 the nearest reachable depot at any distance (`BuildingList_FindNearestReachable` mode 1);
  from stage 2 on, one per stage: the building of the production linked to each of its needs (suppliers),
  then the building of the need served by each of its productions (consumers).
No partner left: the building is done and the key advances. With a partner, `OptimizeRouteBetween`
S 005a4f30 compares the two buildings' flags; flags not in the same road network: done, nothing built.
Otherwise with `oldCost` = road path cost between them:
- `oldCost > 4 x hex distance`: plan along the direct map path (no random draws, §8) and build a street
  towards flags found near it (`OptimizeViaMapPath` S 005a4cc0 [known]);
- otherwise walk the cells of the road path; at path index `i` take an own flag near the cell (`FindFlagNear`
  S 005a4b60, the street flood fill of above; its continent test can never match [known]); if it is in the same road network, plan a street from it to the cell and
  build it if `cost(flag -> partner flag) + len(new) + cost(cell flag -> building flag) < oldCost - 2`.
  More than 2 failures at one index move to the next index; no flag near the cell moves on at once.
A finished pair raises `stage` and clears the path state.

### 3.8 Expansion

Three request producers post an **ExpansionTarget** `{kind, x, y, time}` each; `ExpansionSystem` arbitrates
(every 29 ticks, only with `expansionEnabled`) [known] S 00590fd0:

| Source | Producer | Kind | Position |
|---|---|---|---|
| 1 | ResourceSystem | 1 (towards) | a resource outside the territory |
| 2 | CellExpansion (§3.2) | 2 (at) | the threatened cell |
| 3 | NeedsArrangement (§3.4) | 3 (anywhere) | start position |
| 4 | AttackExecution fallback (§3.12) | 1 (towards) | an enemy building that is too strong |

- If no source is selected: take the open request with the **oldest timestamp** among the four (sources tested
  in the order 1, 2, 3, 4; strict comparison) [inferred] `NAI::ExpansionSystem::ConsiderCandidate` S 00590f80.
- Else, on the next round, promote the candidate to the **current target**, which
  `MilitaryBuildingCreation` consumes.
- When the military building order succeeds or fails, the source is told: ResourceSystem halves / increments
  its per-cell failure counter; the other sources just clear their request [inferred] S 00590c30, S 00590cd0.

**ResourceSystem** (every 23 ticks) [known] S 00590820, S 00590400: for the first queued need, scan every
low-res resource cell (x outer, y inner) and in it every resource element of the need's mining good with
amount > 2 whose area id is in the player's `ConqueredContinents` set (the continent ids of its cells,
rebuilt every 1323 ticks; both periods [known] from the schedule in `Player::Update` S 00582af0). The set is
empty until its first rebuild, so no element qualifies before it [known].

```
C     = the own AI cell nearest to the low-res cell's origin (x * 16, y * 16)
r     = the nearest resource cell (4 x 4) of the good inside the low-res cell not claimed by a need,
        searched from C's centre (ResourceMapAdds::FindNearestUnclaimedCellInLowResCell)
cost  = 6 * (enemy-minus-allied threat at r) + 30 * hexDistance(C centre, r * 4)
        clamped to >= 1;  2 * cost + 720 when the low-res cell's origin already lies inside an AI cell
base  = 1200 - cost,  or -1000 when there is no AI cell C or no unclaimed cell r
score = (base + amount) / (failureCounter(low-res resource cell) + 1)
```

The best element (score above 0, strict, so the first of equal scores) gives the request: kind 1, position =
4 x the first resource cell (x outer, y inner) whose total amount of the good is > 0; no such cell, no request.
That target loop runs over 5 x 5 resource cells from the low-res cell's first one, both bounds inclusive, so
it also looks one row and one column past the low-res cell [known]. It runs only while its own request slot is empty, and the need is taken off
the queue with `placementPending` cleared whether or not a cell was found, so NeedsArrangement tries it again
(§3.4) [known] S 00590820, S 00590340.

**MilitaryBuildingCreation** (every 311 ticks) [known] S 0059abb0:

1. Nothing while its order is pending or `cooldownTicks > 0` (decrement; set to 3 after an order reset). At the
   first update after that, a target it still remembers from its last order is reported to the
   ExpansionSystem as **succeeded** and forgotten.
2. Requires a current target of the ExpansionSystem and at least one soldier of any kind and level in stock.
3. By kind: **1**: breadth-first search over the low-res grid from the start position, steered towards the
   target, order radius 12; **2**: order directly in the AI cell of the target with the type from the site
   rank; **3**: the same search without a target, radius 20. No site -> report failure.
4. **Low-res site query** [known] S 005a8ba0, S 005a8bf0, S 005a8cc0, S 00586000, S 00585f60: a flood fill
   over the low-res grid expands to a cell while its map position `(x * 8, y * 8)` is on the map, on the
   continent of the start position and inside the player's military map grid (the start cell always). A cell
   qualifies if enemy-minus-allied threat < 40 and (one of its **8** neighbours inside the grid has a non-zero
   own `threat` (+0x04), or it has own `score` (+0x14), no own `threatUnfinished` (+0x08), and one of its 8
   neighbours has zero own `score`). `threatUnfinished` is filled from a building's effective construction,
   i.e. the upgrade construction while one runs [known]. Score = `100 / (4 * hexDist((x * 8, y * 8), target) + max(1, own threat))
   / (counters[0] + 1)` (distance 1 when there is no target; `counters` of the `TerritoryMap` element); the
   visitor never stops the fill, the best score starts at 0.0 and only a strictly higher one replaces it, so the
   first maximum in fill order wins; the result is the map position `(x * 8, y * 8)`.
5. **Which military building** `MilitaryBuildingRanking` [known] S 005a8040, [inferred] S 005a8310, S 005a8250:
   the tribe's territory buildings with `soldierLimit` (`BuildingProperty` +0x98) > 0, sorted by that
   limit (two types with the same limit: the later one in the tribe's list replaces the earlier), give
   ranks 0..n-1. Wanted rank at a position:

   ```
   d = MinDistanceToEnemyMilitaryBuilding(position, player, 1, 1)
       (S 005337e0 [known]: hex distance to the nearest territory building of an enemy the player's military
        settings do not ignore, or to the nearest harbour with an enemy route; 1000 when there is none;
        `military.md` §3.1)
   r = (d < 19) ? (aggressive ? +1 : -1) : (d == 24 ? +1 : -1)     -- exactly 24; every other d >= 19 gives -1
   if aggressive and stocked soldiers (both kinds) > 30:               r += 1
   if a map-table resource (sourceKind 1, not 0x4012E5A3) lies in the square of +-4 resource cells:   r += 1
   if aggressive and the nearest reachable own finished building of the village's depot list (+0x20)
      or of its casern list (+0x74) lies at hex distance <= 4 (S 005a7f60):   r += 1
   if stock of the LAST input of the construction good > 40:           r += 1
   if logic tick < 18000 and no enemy has been spotted yet:            r -= 1
   rank = max(r, 0) - bias
   ```

   `aggressive` is false for new buildings and true for upgrades (§3.11); `bias` = the retry index. The type is
   the entry with the first rank >= the wanted rank (clamped to the highest).
6. **Order result** [known] S 0059af60: whenever the order ends in state 4 or 5 the retry index is incremented
   and, while `ComputeSiteRank(position, false, retry index) >= 0`, the order is re-issued with that lower rank
   (radius 16 for an order by cell, the original radius otherwise). When no lower rank is left **and** the last
   attempt ended with "no place" (callback argument 0), the AI tries to **upgrade** the first own, idle,
   affordable territory building around the spot (S 0059adc0, [inferred]); success counts as a successful
   expansion and halves `counters[0]`, failure increments `counters[0]` and reports failure. When the last
   attempt could not be afforded (argument 1) and no rank is left, only the order slot is cleared: the target
   stays remembered, and step 1 of the next update reports it to the ExpansionSystem as **succeeded** [known].

**Expedition** (every 211 ticks) [known] S 005a02c0: only when the stock holds the full cost of the tribe's
expedition building (`ShipConfig::GetExpeditionBuilding` for the tribe; both cost lists of the building
property, +0x58 and +0x68, added together; `Stock::HasAll`). Then, over the AI cells in cell-vector order
and the harbours of each cell (cell +0xfc) whose flag cell is not a forbidden harbour position
(`ai_forbidHarborPosition`, Player +0xb0), for each exit of the harbour with a valid ship route, in exit
order (an AI harbour's Unique is its flag's Unique [known]): if the player has an active expedition on the route, it is told to found a colony when it is waiting
for orders (else nothing happens); otherwise, if the route's far-end harbour cell is unexplored for this
player (exploration grid byte 0) or that harbour has no owner (+0x08 == -1), and `CanAssignShip` allows it,
the nearest idle ship is assigned to the route (`AssignNearestIdleShip`). Details of ships and missions:
`navy-and-military.md`.

### 3.9 Economy controls

**ProductionControl** (every 67 ticks; the cursor over the tribe's good list advances past goods that are not
controllable until one controllable good was handled) [known] S 0058bcb0, S 0058b9e0, S 0058bad0, S 0058bbb0:
for a controllable good, every finished producer building of the good gets production **enabled** while

```
count < 40 + (territory * 60) / 9216        (integer division; territory = statistics field +0xa4, see §3.3)
```

and disabled otherwise. `count` = stock + second stock of the good; for a good that is an input of the tribe's
second-carrier good, the stock (first stock only) of that carrier good is counted instead. Controllable =
plain ware (type 0), without `enableFields` (+0x51), not the coin good, not an input of the construction good;
goods with `enableDeposits` (+0x50) only if they are the first carrier input, the good planted by the tribe's
first working-mode-2 building, or the slot-0 product of the tribe's working-mode-3 producer of `fish`
(`0x4012E5A3`) (S 0058bf30). `IsProductionWanted(G)` = not (controllable and count >= limit); it also
gates SelectConstruction (§3.5). The cursor holds a good id, not a list index; a tribe without any controllable
good makes the advance loop run forever [known] S 0058bcb0.

**LockSmith** (every 337 ticks, not during need stage 1) [known] S 0058d130: tool good = `workerToolGoodId`.
- stock < 20: create one need for the tool good (once), or switch production **on** in the building of the
  production that serves the tool need (S 0058d0c0), without a test that the building is finished;
- stock >= 20: switch production **off** in that building, only if it is finished;
- **stock == 0** and the player has a completed building in the village's list +0x20, which is the list of
  buildings whose type has `depot` (`village-buildings.md` §2.2; lookup
  `NVillage::System::FindCompletedBuildingOfPlayerInList20` S 00558730, first match in list order): **one tool
  is added to that building's stock for free** (§3.16).

**FoodArrangement** (every 643 ticks) [known] S 0058ced0, S 0058ccd0, S 0058cc60, S 0059f850: works on one
group of the player's goods distribution (the per-building-type weights a human sets with the distribution
sliders): the group of the first input of the product of the tribe's **stone mine**. The mine type for a good
`g` (S 0059f850) is the first tribe building with `size == 8` and working mode 6 whose slot-0 product has
`miningGood` `g`; if none, the first such building whose slot-0 product is `g`; -1 otherwise. The stone mine
is the type for `0x55E952D3`, cached on activation (S 0058cc60). The stone mine's entry = 1.0 if the player's
stock of its product < 5, else 0.5. Every other entry of the group whose type is a mine (size 8, working mode
6), with `P` = its slot-0 product, sets the entry of the mine type for `P` (the same type unless two mine
types produce `P`) in the group of the first input of that type's product (S 0058ccd0): 0.3 if stock(`P`) >
4; else 1.0 if some need for `P` in `needsA` has a building (Need +0x7c valid) that has all its needs served,
has workers (`Workers::HasWorkers`), has `P` with a positive amount in the recipe of its slot-0 product and
none of that product in its own stock; else 0.5. The building stock read here is its **input** stock [known].

**GoodsArrangement** (every 643 ticks, 10-step cycle; steps 3-6, 8, 9 do nothing) [known] S 0058cb70,
S 0058c600, S 0058c7e0, S 0058c480. The three "arranged" goods (S 0058c3a0) are the inputs of the tribe's
`constructionGoodId` (+0xb4; in `Goods.lua` `plank` and the tribe's stone) and its `soldierUpgradeGoodId`
(+0xb8, the coin good) as the third. A building's good flag is the collection flag of `goodFlags`
(`Building_SetGoodFlagEnabled` S 00557630 / S 00563980, which **sets** the flag to the given value and does not
toggle it [known]; the flag of command 0x2001e, `village-buildings.md` §2.3); every
flag write skips a building that is still a construction site (+0x44 floats +0x70 / +0x74 > 0).
- Step 0 (S 0058c600): over the finished buildings of every cell's **depot** list, min and max stock of each
  arranged good (min starts at 100000; ties keep the first building in cell and list order). For a good with
  `max > min + 40`: the flag is enabled on every depot and then disabled on the one holding the most
  (S 0058c110, S 0058c180).
- Step 1: the three flags are disabled on every depot (S 0058c550, S 0058c330).
- Steps 2 and 7 (S 0058c7e0): candidates are the finished buildings of every cell's casern list and the
  finished depots whose `NAI::Building` casern byte (+0x43) is set. A candidate is front-line when the
  distance of its cell is < 36 (`Cell::GetMinDistanceToEnemyMilitary` S 005956a0: the smallest cached enemy
  distance, `military.md`, of the cell's military buildings whose territory updater is active, `0x7fffffff`
  when none is active; the distance from the cell centre when the cell has no military building). If at least
  one candidate is front-line, every soldier good (both kinds, every level of the building's tribe,
  S 0058c220) is enabled on the front-line candidates and disabled on the others (S 0058c480).

**ForesterConstruction** (every 3 ticks, one cell per call) [known] S 005a41d0: with `forestingEnabled`, a
forester type in the tribe and no order of its own pending.
`P` = the first frame-cost good of the forester type (`bp_addFrameCost(forester, plank, 1)` in
`buildings.lua`), `Q` = the first input of `P`'s recipe (the tribe's wood good).
`threshold = 10 if stock(P) + stock(Q) >= 40 else 40`. `A` = the cell's amount of `Q` as in CellClearing
(§3.2, resource objects on the centre's continent). If the cell has foresters (its consumer list): every
finished one is disabled when `A > threshold` and enabled otherwise. If the cell has no forester,
`A < threshold` and the cell has an object of `P` (`Cell::CountObjectsOfType(P) != 0`): request a forester
(priority 50) in the cell.

**DestructionSystem** [inferred] S 0058de80, S 0058dae0, S 0058ddb0:
- every 41 ticks, next own building in id order: demolish it if it is not military / depot / consumer / casern
  / kind 9 [known] S 0058de80 and `CanDemolishBuilding` S 0058dae0 holds [known]: its type has a product in
  slot 0 and is not a catapult type (`BuildingProperty` +0xb0), its output good has `enableDeposits` (+0x50)
  or `enableFields` (+0x51) or the building has working mode 7, it is still a construction site (a
  construction float +0x70 / +0x74 > 0, §2.2) or has at least one occupant, and
  `ScoreSite(type, position) <= 0` (for working-mode-3 buildings with a positive score: zero productivity
  instead; the keep test is written `!(s <= 0)`, so a NaN score keeps the building [known]). The demolition
  calls `RemoveBuilding(unique, true)` directly [known]. A working-mode-7 building is kept while its first worker is in a work cycle: the virtual call
  slot +0x28 resolves for a worker to `NSettlers::Worker::IsInWorkCycle` S 0065c7d0 (Worker vftable S 007f84dc
  slot 10), true in the states 0x1d, 0x1e (work movies), 0x20 `BringGoodHome`, 0x21 `ReturnHome`, 0x24 and 0x35
  `BringGoodOut` (`settlers-jobs.md` §2.4) [known]; the test runs only when the building has a worker. A building
  whose product is `wood` (`0xCD6EC133`) is kept if its cell has a forester (consumer list not empty) and
  holds exactly one object of that good;
- every 59 ticks that are not also a 41-tick step: for every cell with an armed demolish trigger, demolish the
  first building of the cell's default list whose property +0x3c equals the stored value (§2.3) and reset the
  trigger. No code arms this trigger (§2.3), so the step does nothing in a game that was not loaded from a save
  with an armed trigger;
- on all other ticks: next own flag (round-robin); remove it if `IsFlagRemovable` [inferred: no building, no
  navy object, no packages, and no street or exactly one street without an active carrier].

**ShipConstruction** (every 673 ticks) [inferred] S 005a5d00: with `shipConstructionEnabled`. For each harbour
of the AI cells whose cell is not marked full for the good `ship` (`0x1D66B4AE`): if the number of usable sea
routes on the harbour's continent exceeds the number of own ships there and the cell has no free production
of that good (`Cell::HasFreeProductionOfType`), request the shipyard type (priority 10) by position: the
harbour flag's cell, radius 16; the first such harbour ends the update [known]. A failed order marks the cell
full for the good.

### 3.10 Soldier, weapon and coin production

**WeaponProduction** (every 631 ticks, not during need stage 1) [known] S 00598950: for both soldier kinds,
for each input good `W` of the level-0 soldier good:
- walk the own productions of `W` (ascending Unique); `n` = their number (counted as a float, +1.0 each). A
  producer is "bad" when its AI building has an unserved need (`Building::AreAllNeedsServed` S 00596d00 false),
  when the village building has no worker (`Workers.workerCount` == 0), or when its productivity
  (`Statistics::GetProductivity`) is < 0.1; only the productivity of a producer that passed the first two tests
  is added to the sum, and only a producer that fails the productivity test is remembered;
- if any producer was bad: `RequestMissingInputs` on the last remembered (low-productivity) building, if there
  is one; nothing else for this good;
- else if `trunc(n) < profile.maximumSmithies` and `now - lastNeedTime > needsAdded * 600` s:
  `lastNeedTime = now - needsAdded * 600`, `needsAdded += 1`; and if average productivity
  (sum of the productivities / `n`) >= 0.9 **or** stocked soldiers (both kinds, all levels) <
  `trunc(territory / 48) / max(1, needs of W)` (integer division; `territory` as in §3.3): `needsAdded += 1`
  again and add a need for `W`, attached to the first depot of the first AI cell.

[known] disassembly S 00598b13 .. S 00598be2; constants S 007df158 (48.0), S 007ea340 (0.9), S 007db630 (0.1).
`needsAdded` and `lastNeedTime` are one pair for the whole module, shared by all weapon goods of both kinds.

**CoinProduction** (every 647 ticks, from need stage 4, with `coinProductionEnabled`) [known] S 00598640: same
pattern for the coin good (`soldierUpgradeGoodId`) with the cap test `trunc(n) < profile.maximumMints` (`n` =
number of own coin productions) and the productivity test only (>= 0.9, no soldier quota); the new need is
attached to the first depot of the first AI cell [known] disassembly S 0059878e .. S 0059880e.

**SoldierCreation** (every 409 ticks) [known] S 00599860, S 00599540, S 00599780: among the finished
buildings of the casern list of cells on the start continent, choose the one with the highest
`2 * MinDistanceToEnemyMilitaryBuilding - cost`. `cost` = sum, over the AI cells, of the flag-path cost from
the candidate's flag to the flag of the **first** building of the cell's default list whose slot-0 product is
an input of a level-0 soldier good (either kind), counted only when the two flags are in the same street
network (a cell whose first such building is not connected adds nothing). The float sum starts at FLT_MAX
and the first connected cost replaces it; the best score starts at -FLT_MAX with a strict comparison, so a
candidate without any connected supplier (score `2d - FLT_MAX`, which rounds to -FLT_MAX) is never chosen
[known] S 00599540, S 00599860.
On every candidate both training slots are disabled and the upgrade switch of its training component is set
to "has an upgradable soldier". Then each slot of the best one is enabled unless an input of the tribe's
**construction good** that is also in the slot's cost list is short: `stock < 40 + margin`, halved (integer)
when an AI cell already holds an object of the good [known] `Player::IsGoodStockBelowMargin` S 005824d0.
`margin` is 0 for an enabled slot and 20 for a disabled one (S 00599780), but the slot was switched off a
moment earlier in the same update (`SetSlotEnabled` S 00566db0 writes the byte that is read), so the margin is
always 20: the test is `stock < 60`, or `< 30` with an object of the good in a cell [known].
In the shipped data the only such
overlap is `stoneScots` (construction input of the Scots and cost of `good_bowSoldierStone0`, `Jobs.lua`);
no weapon good is tested.

**Casern placement** (every 3 ticks, one AI-cell position per call) [known] S 00598110, [inferred] S 00597ea0:
active once need stage 2 is reached, while no casern order is pending and the tool stock is >= 10. After each
full sweep, if a best position exists, request the tribe's casern building there with priority 30 and reset the
best score to FLT_MIN (1.17549e-38), so only positions with a positive score qualify. Position score:
-1 if there is no AI cell or an own casern closer than 25; else
`-(sum of the enemy-minus-allied 3x3 threat sums at the 4 low-res positions of the cell) / (counters[4] + 1)^2`,
halved when enemy military is farther than 48.

### 3.11 Military posture

**Threat sums** [inferred] S 00584d80, S 00584e90, S 00584ff0, S 00585240: "3x3 sum of value[k] at low-res
position p" = sum over the 9 cells around p of the MilitaryMap value, weight 0.5 for every cell except the
cell at offset (+1,+1), which has weight 1.0 (the centre cell also gets 0.5; this is how the code behaves).
"Allied" sums over all active non-enemy players including the AI itself, "enemy" over all active enemies;
`enemy-minus-allied(k, p)` is their difference.

**MilitarySettings** (every 53 ticks) [known] S 00599d60: only with `profile.allocationEnabled` and at least one
cell with a depot. A countdown is decremented on every call; while it is below 1 the two cases below are tested
on every call, and the countdown is set back to 50 only when one of them applies (so a change is followed by a
pause of about 2650 ticks). `S` =
stocked soldiers of both kinds, `v` = the player's current garrison fraction for the **medium** zone
(`NPlayer::Military` +0x08 f32[3]: [0] far, [1] medium, [2] near; `military.md` §2.3):
- `S == 0`: near := clamp(`v * 2.667`, 0.25, 1.0); medium := min(`v * 2.667 * 0.3`, 1.0);
- `S > territory / 128`: `x = min(v * 4.167, 4.0)`; near := clamp(x, 0.25, 1.0); medium :=
  min(0.3 * x, 1.0).

The writes go through `NPlayer::Military::SetDistanceAllocationFactor(pMilitary, idx, value)` S 005c0980, which stores
`pMilitary + 8 + idx * 4`; idx 2 = near, idx 1 = medium, the same fields the human sets with the commands
0x20013 / 0x20014 (`game-commands.md`) [known]. The far-zone fraction (idx 0) is never written by the AI. Because
the new medium value is `0.3 x` a multiple of the old one, the first case shrinks it by 0.8 per application
(`2.667 * 0.3`) and the second grows it by 1.25 (`4.167 * 0.3`) until the cap [inferred from the constants].

**MilitaryUpgrade** (every 37 ticks, one building per call, round-robin over the village's territory-building
list, which holds the buildings of all players) [known] S 005982a0: for an own non-depot building: if its
upgrade component is idle and its rank is below `ComputeSiteRank(position, aggressive = true, bias 0)`, start
the upgrade only if the stock holds **twice** the frame cost + cost of the upgrade target type
(`BuildingProperty` +0xe8). Then, upgrade or not, if the building may switch soldier kind, set it to
`ChooseSoldierKind`.

**ChooseSoldierKind** [known] S 0059f370: over the military buildings of the building's cell list:
`f` = share of buildings currently on kind 0, `n` = their number, `s` = share of kind 0 among stocked
soldiers (all levels; `f` if none stocked):

```
score = battleCalcRatio[0] * swordBowRatio + battleCalcRatio[1] * s + battleCalcRatio[2] * (25 + rand % 50) / 100
score > f + 1/n  -> kind 0;   score < f - 1/n -> kind 1;   else keep the current kind
```

### 3.12 Attacks

**Budget** [known] S 00597c80, S 00599a90, S 005ade50: `AttackSystem.budget` (MilitarySystem+0x144) is -1
(unlimited) after activation. `MilitaryLimiter::Update` (every 53 ticks): if `profile.attackLimiterDelay != 0`
and `tick > nextTick`: `budget = attackLimiterAttackCount + rand % attackLimiterAttackCountRandom` (the random
term only if the range > 0) and `nextTick += attackLimiterDelay + rand % attackLimiterDelayRandom`. `nextTick`
starts at 0, so the first grant comes at the first limiter update. Scripts set the budget directly with
`logic.ai_setAllowedAttackCount(player, n)` and `logic.ai_setAttackEnable(player, bool)` (-1 / 0).

**AttackSystem::Update** (every 141 ticks) [known] S 00599a90: nothing unless `attackAllowed`. If
`budget >= 0`: return when it is 0, else decrement. Then choose a target area and run the execution step. One
budget unit is therefore one evaluation round (141 ticks), not one attack.

**Target area** `AttackTargetSelection::ChooseNewTarget` [known] S 005a8750: three target slots. If one is
free (the last free one is used), scan every low-res cell `c` not already a target and every active enemy
player `e` (index 0..7):

```
require  e.score(c) != 0
require  own threat non-zero in one of the 8 neighbours of c,
         or one of the 8 neighbours of c holds a harbour of e (e's MilitaryMap harbour list) that is not at
         a forbidden harbour position of the AI (§2.5) and for which
         Harbor::EvaluateRouteToPlayer(harbour, AI player, AI player, 0) returns 0  (S 00586160;
         [inferred] a harbour of e the AI can reach by sea)
value = (mapWidth - hexDist(c*8, ownStartLowRes*8)) * 20
      + e.threatUnfinished(c) + e.score(c) + own.score(c)
      - enemy-minus-allied(0, c)
score = value / (0.2 * (counters[3] + counters[1]) + 1)          the area's attack failure counters, §2.2
```

The best (strictly greater, start -100; x outer loop, y, then player) becomes the slot's target
`{cell, radius 12, time, enemy player}`.

**Execution** `AttackExecution::Update` [known] S 005a0dd0, per slot with a target area:

1. *Secondary target* set: if its building still exists and has a fight: skip the slot this round when the
   fight's field +0x24 is non-zero, else continue with step 2 and keep the secondary target. If the building
   exists without a fight and `IsNearAnySlotCell(position, 0)` is false, `counters[6] += 1` on the area's
   element. In the no-fight and the building-gone case clear the secondary target.
   `IsNearAnySlotCell(pos, which)` [known] S 005a07b0: true when `pos` is at hex distance < 16 (15 or less) of
   the stored target position of any of the three slots, the own slot included; `which` 0 compares with the
   **primary** target positions, 1 with the **secondary** ones; unset positions (x = -1) are skipped.
2. *Primary target* set: release the slot if the building is gone or now ours (halves the area's failure
   counters, clears the target area); if the building is no longer under attack, report result 2 and clear
   both targets.
3. *No primary target*: candidates = every building of the village's territory-building list that belongs to
   the target player and is not already an attack target (`NVillage::Military::HasNoAttackTarget`), at hex
   distance <= the area radius (12) from the area's map position (cell x 8), and either on a cell visible to the AI
   player or with cached enemy distance < 13. Candidates are ordered by **descending defensive weight**
   `SumOwnBuildingWeightAround` S 005327f0; equal weights keep the first. The weight walks rings 0..10 in the
   standard spiral (centre; per ring one step in direction 4, then `ring` steps in each of directions 0..5, visiting
   after each step): 331 cells, each once, the loop counter equal to the cell's ring; out-of-map cells are skipped.
   Per in-map cell whose layer-1 lookup (S 00558890, anchor only, see §2.2) finds a building of the argument's owner:
   `sum = (float)aiScore / d + sum`, with `d = (float)(ring - 3)` when that is greater than 1.0 (double 1.0 at
   S 007d8a08, `FCOMP; TEST AH,0x41`), else 1.0, so the divisor is 1 for rings 0–4 and 2–7 for rings 5–10. The sum
   is a float at 24-bit x87 precision starting at 0 and includes the building itself at ring 0; each building counts
   once, at its anchor's ring [known].
   - No candidate: report result 0.
   - For each candidate in order: `fraction` = attackers score (below); `ratio = EstimateStrengthRatio`.
     `ratio < 0` (nothing to send): next. `ratio < 0.25`, or `< 0.5` with military mode Safe: remember as
     fallback, next. Otherwise:

     ```
     mode Safe(0):        k = 1.25 - (rand % 100 - 35) / 100      -> 0.61 .. 1.60
     mode Normal(1):      k = 1.00 - (rand % 60  - 30) / 100      -> 0.71 .. 1.30
     mode Aggressive(2):  k = 0.75 - (rand % 50  - 25) / 100      -> 0.51 .. 1.00
     attack if   0.1 * counters[1](area) + sqrt(enemyStrength / max(ownStrength, 1)) * k  <=  ratio
     ```

     `enemyStrength`, `ownStrength` = `GameStats_ComputePlayerMilitaryStrength` (level-weighted soldiers,
     S 00533960). [inferred] that the square root is taken of that quotient (the decompilation loses the
     operand). If the test passes **and** the game's own attack availability check passes, the primary target
     is set and `NMilitary::Attack::StartAttack(player, building, fraction)` is called. Whether or not the
     availability check passed, **the whole `Update` returns here**: the remaining slots are not processed in
     this round and no result is reported. If the test fails: remember as fallback, next. A profile mode other
     than 0 / 1 / 2 uses `k = 1.0` and draws no random number.
   - If any fallback was recorded: post the fallback position as an expansion request (source 4, kind 1) if
     none is open; then **secondary attack** (S 005a0910): if there is more than one candidate, the best ratio
     seen >= `specialAttackBestChance` (+0x94, default 0.1), the weakest-defended candidate (last in the
     order) is not within 15 cells of any slot's secondary target (`IsNearAnySlotCell(pos, 1)`),
     `Military_GetMinAttackerFraction <=
     specialAttackMinFactor` (+0x8c, default 0.1) and `counters[6] + specialAttackRandomValue (+0x90,
     default 90) < rand % 100`: attack that candidate with the minimum fraction and store it as the secondary
     target; the attack itself is started only if the availability check passes, and in both cases the whole
     `Update` returns without a report. If the secondary test fails: report result 1.
   - Candidates existed but every one had `ratio < 0` (no fallback recorded): nothing is reported and the slot
     keeps its target area.

**How many soldiers** [known] S 0059e930: the `fraction` passed to `StartAttack` (the same quantity as the
human attack slider, `military.md`):

```
fraction = battleCalcRatio[0] * factor(Attack, Own)
         + battleCalcRatio[1] * h
         + battleCalcRatio[2] * (rand % 101) / 100
h = factor(Attack, Own) if no remembered fight; else
    (own soldiers that could attack the building now) / (own soldier count in the nearest remembered
     fight against this opponent in which the AI attacked)
```

With the defaults 0.5 / 0.3 / 0.2 and the shipped factors (Weak 0.4, Normal 0.6, Strong 0.9) a first attack
sends between `0.8 * factor` and `0.8 * factor + 0.2` of the available soldiers. A second score from the
defenders (`factor(Defense, Enemy)`, S 0059e810) is computed for each candidate and **discarded**; it only
consumes one random number [known] S 005a0dd0.

**Strength ratio** [known] S 0059f290, S 0059f0b0, S 0059efe0, S 0059ec60, S 0059e6c0: attackers =
all soldiers the game would dispatch against the target, defenders = all that would respond, each tallied per
soldier kind as `{count, strength}`. Per visited building with the cap `n` the dispatch passes
(`StrengthCounter::CountBuilding` S 0059ec60): a depot adds, per soldier kind and level of its owner's tribe,
its stock count of that soldier good to `count[kind]` and stock x strength at full health to
`strength[kind]` (the cap is not applied); any other building with `p > 0` present soldiers sums the strength
of its eligible soldiers at their current health (of the attacking player: `Soldier::IsAvailableInBuilding`
S 00659370; of any other player: no fight reference and not in a fight) and adds `min(n, p)` to the count and
`min(n, p) * sum / p` to the strength of the kind of its soldier component (+0x68). Soldier strength =
`(health/maxHealth * 0.8 + 0.2) * (blockingChance * C + maxHealth + B + C * maxHealth / attackWaitTime)`
[known] S 0059e6c0, with `B` = `SacrificeModifierQuery::GetHitDamageForProperty` S 00661ae0 and `C` =
`...GetArmorForProperty` S 00661b40 for the soldier's good and owner ([inferred] from the names: the soldier
good's `hitDamage` and `armor` with the player's sacrifice modifiers applied; `military.md` owns them);
stocked soldiers in depots count at full health.
Effective strength of a side = `strength[1] + strength[0] * superiority(count[0] / opponentCount)` where
`opponentCount` = opponent's kind-0 count, else its kind-1 count, else 0.1, and `superiority` is the game's
numeric-superiority curve (`military.md`). `ratio = (ours / theirs)^2`, or 1000 when `theirs <= 0.5`, or -1
when the attacker tally is 0.

### 3.13 Reacting to fights

The fight list notifies every AI player involved when a fight starts or ends
(`AIPlayers_AddAttackWatchForFight` S 0053be90, `...Remove...` S 0053bed0); the AI keeps one `AttackWatch` per
fight [inferred] S 00585cd0.

**When the AI is attacked** (watch creation) [known] S 0059b3f0, S 0059eb70: a defence score is written to the
target building's military component (+0x64 `defenceFraction`: the share of each helping building's soldiers
sent to defend, read by `DispatchDefenders`, `military.md` §2.4, §3.5). The watch is created while
`NMilitary::Attack::StartAttack` S 00576500 links the new fight to its target building, and the next statement
of `StartAttack` copies the owner's player setting (`NPlayer::Military` +0x1c, default 0.5) into the same
field [known: S 00576500; chain `MilitaryLink_LinkFightToTargetBuilding` S 0053cf50 -> `Fight::SetTargetBuilding`
S 00570760 (only while the fight has no defender yet) -> S 0053be90 -> S 00585cd0 -> S 0059b3f0]. `StartAttack`
is the only caller of `FightList::CreateFight` S 00573c30, and the field has no other writer (its users are
S 0059b3f0, S 00576500 and the reader in `Fight::Update` S 005715a0), so the value computed here is always
**overwritten before it is used**; the two random draws below are still made:

```
defence = battleCalcRatio[0] * factor(Defense, Own) + battleCalcRatio[1] * h
        + battleCalcRatio[2] * (rand % 101) / 100
h = factor(Defense, Own), or (current defenders / own count in the nearest remembered defence against this
    opponent) when such a record exists with a non-zero own count
```

Then a roll: `chance = specialDefenseRandomValue (+0x9c, default 50) - 20 * (number of the 3 x 3 low-res cells
around the building that are current attack target areas)`; if `chance < rand % 100` and the neighbourhood
comparison S 0059ee80 is false (weighted own `score` not above 1.5 x the weighted `threat - threatUnfinished`),
the score is replaced by `specialDefenseFactor` (+0x98, default 0.1). The factor read is index
`0 + 2 * 1` = `factor(Defense, Own)` (0.5 in every shipped profile) [known] S 0059ea50, S 00555d10, S 0054b8a0.
`factor(Attack, Enemy)` (+0x38) has no reader among the three callers of the getter [inferred].
In one observed attack on a computer player the watch wrote 0.862, `StartAttack` replaced it with the player
setting 0.5, and `DispatchDefenders` S 00576400 read 0.5 [live, 2026-10-12].

**Every 127 ticks, each watch once** (`AiAttackWatch_Evaluate`) [known] S 0059b2f0: when the fight is running,
has a target and the target building still belongs to the defender, compute the live strength ratio
(S 0059f100, same formula on the soldiers actually in the fight). If `ratio < 0.5`:
- AI is the **attacker** and the attack can still be cancelled: with probability `profile.retreatChance` %
  call `Military_RequestCancel` (retreat);
- AI is the **defender**, the building's self-destruct countdown is not running and the building is not the
  headquarters type: with probability `profile.destroyLostBuildingChance` % start that countdown (the AI burns
  the building it expects to lose);
- the watch is marked handled after a roll, whether it succeeded or not. No roll is made and the watch stays
  unhandled (it is tested again 127 ticks later) when the AI attacks but cannot cancel, or when it defends and
  the countdown already runs or the building is the headquarters type.

**Fight history** [known] S 0059be60, S 0059b5b0, S 0053bf10: when a fight's start countdown runs out in
`NMilitary::Fight::Update` S 005715a0, right after the defenders were dispatched, every AI player that has a
watch for the fight stores a record `{opponent, weDefended, size of the fight's side list +0x78, size of its
side list +0x7c, target position}` ([inferred] the attackers and the defenders at that moment); a record with
the same side flag and position is overwritten. Lookups take the record of the same opponent and side nearest
to the queried position S 0059b800. The history is unbounded.

### 3.14 Catapults

`CatapultConstruction::Update` (every 5 ticks) [inferred] S 00599220, [known] scoring S 00598e60: only with
`profile.catapultsEnabled`, `catapultsLocalEnabled`, a catapult building in the tribe, no pending order, and
the stock checks passing: `IsGoodStockBelowMargin(inputGood, 0)` must be **false** (stock at least 40, or 20
when an AI cell holds an object of that good) and the tool stock at least 10. `inputGood` = the first cost
entry of the good the catapult building produces in slot 0 ([inferred] S 00599110; e.g. `catapultStoneScots`
costs `stoneScots`, so the tribe's stone, `Goods.lua`). It sweeps the low-res grid,
`max(1, w*h / (catapultConstructionTime / 5))` cells per call, so a full sweep takes about
`catapultConstructionTime` ticks (default 3000, campaign profile 300). Per cell:

```
base = own3x3(score) - own3x3(scoreCatapult) - buildCatapultDecreaseFactor * own3x3(scoreCatapult)
        -- must be > 0, else the cell scores -1.  MilitaryMap::SumCellValue3x3(idx) reads element +0x10 + 4*idx
        -- (S 005860a0, same 0.5 / 1.0 weights as §3.11): idx 1 = score (+0x14), idx 0 = scoreCatapult (+0x10)
v = base + catapultEnemyThreatFactor * enemy3x3(value 0)
         - catapultFriendThreatFactor * (allied3x3(value 0) - own3x3(value 2))
if allocationEnabled:  v = v / max(near-zone garrison fraction (pMilitary+0x10, §3.11), 0.01)
v = v + catapultAttackFailedFactor * (territory3x3(counter 5) + territory3x3(counter 1))
score = v / (territory.counters[2](cell) + 1)^2
```

After a full sweep the best cell with score above the running threshold gets a construction order (map
position cell x 8, radius 8, priority 20), and the threshold is reset to `constructCatapultRating`
(default 600; Strong and the catapult campaign profile 200); the reset happens at the end of every sweep, with
or without an order. `Activate` S 005991a0 sets the threshold to FLT_MAX and the scan cursor to the grid size,
so the first step after activation wraps at once (no best cell, no order), sets the threshold to
`constructCatapultRating` and starts the first real sweep at cell (0,0).
An order that ends with "no place found" increments
`counters[2]` of the low-res cell of the order position S 00599020. The comment in `ai.lua` states the
designers' intent: *catapult rating = building score -
catapult score x decrease factor + danger value x danger factor + attack failed count x failed factor*.

`UpdateProductionEnabled` (every 141 ticks) [known] S 005993c0, S 005990a0: for each own finished building of
the village's list of catapult-type buildings (construction floats +0x70 and +0x74 both <= 0): production is
switched **off** when the smaller of the two enemy distances (enemy unit, enemy military building) of the AI
cell nearest to the building is negative or above `2 * workingRadius`, or when
`IsGoodStockBelowMargin(inputGood, 0)` is true (stock of the input good below 40 / 20); it is switched **on**
when an enemy is in range and the stock is not below that margin.

### 3.15 Sacrifices

Every 647 ticks with `sacrificesEnabled` (S 0058a4a0) [inferred]: refresh state, order by score, order by
random, start ready ones.

- **State** [known] S 0059cf60: rebuilt from scratch on every update by walking the village's list of
  working-mode-9 buildings (`NVillage::System` +0x9c) and taking the own, finished ones: ids of sacrifices in
  progress (building sacrifice component +0x10 != -1), the first building whose sacrifice component is idle,
  and four facts: enemy spotted, own ship ready, enemy ship ready, involved in a fight; plus a copy of the
  map's sacrifice list for the player's tribe (empty when the map has none). The manager and its state object
  (0x30 bytes, ctor S 0059cef0) hold nothing that outlives an update, which is why they are not saved (§7).
- **Usable** S 0059ce50: not in progress, and by the sacrifice's category: 0 needs an enemy if it is
  targeted; 1 and 3 need a spotted enemy; 2 needs a ready own/enemy ship by target; 4 is never usable here.
- **OrderBestScoredSacrifice** [known] S 0058a360, S 0059cbc0, S 00589fb0: only when an idle sacrifice
  building exists. Among the map's sacrifices that are not campaign-only and have category 4 (the
  good-exchange sacrifices [inferred]; no "usable" test here): score = `(5 - stock of the good of its
  give-goods effect) + min over cost entries of stock / amount` (float; the minimum starts at 100); the first
  highest score > 0 (strict comparison) is ordered, none when no score is positive.
- **OrderRandomSacrifice** [known] S 0058a250, S 00589c80: only when an idle sacrifice building exists. Pick a
  random usable id from the profile's favourite list (`w` = its favourite weight, 0 when the list has no usable
  id); one roll: if `w < rand % 100`, replace it by a random usable id from the map's list. Order it (nothing
  when the id is -1). A pick from a list draws one logic random number (`rand % count`) only when the filtered
  list is not empty; the roll is always drawn.
- **Ordering** [known] S 0058a0d0, S 0059ccc0: if the sacrifice has a `researchDuration` > 0
  (`SacrificeProperty` +0x98) and is not yet in the player's set of researched sacrifices: start its research
  through the building when the research state is 0 (`VillageSacrifice::CanStartResearch` S 00561130,
  `StartResearch` S 00561150), and do nothing else. Otherwise add a need, attached to the sacrifice building,
  for every cost good for which the player has no need yet, and when the stock holds **twice** the cost (the
  cost list is added to itself for the test) and the building accepts (`CanOrder` S 00561380), place the order.
- **Start** S 00589cd0: every own finished sacrifice building with a chosen, startable sacrifice whose
  category condition holds is started; a targeted sacrifice gets a **random** entry of a candidate list
  (`rand % count`): category 0 every active enemy, 1 every discovered enemy, 3 every enemy in a fight with the
  AI (either side attacking), each once; category 2 one entry **per ready enemy ship** (its owner), so an enemy
  with more ready ships is more likely [known] S 0059d120.
- **Sacrifice building** S 005a1e30 (every 389 ticks) [known]: the planner works on a **good**, the slot-0
  product `T` of the tribe's first working-mode-9 building (-1 when the tribe has none;
  `AiTribe_GetGoodOfWorkingMode9Building` S 0059f670, S 005a1d10). With `T` set **or**
  `sacrificesEnabled` (so the switch does not stop the planner of a tribe that has a sacrifice building), need
  stage 4, tool stock
  >= 10 and game time > `profile.sacrificesStartTime` (default FLT_MAX = never; 0 for Strong and the campaign
  profiles; Weak and Normal do not set it): if the number of needs for `T` equals the number of own productions
  of `T`, is below `profile.sacrificesLimit`, and no own sacrifice building is idle, add a need for `T`, attached
  to the first depot of the first AI cell. The building itself is then ordered by NeedsConstruction (§3.5).
  [inferred] Weak and Normal therefore never build a sacrifice building themselves.

### 3.16 Cheats and bonuses

- **Free tool** [known] S 0058d130: every LockSmith update (337 ticks) with a tool stock of exactly 0 adds one
  tool to a completed own building's stock. This is the only place found where the AI creates goods.
- **Information**: target choice reads every enemy's `MilitaryMap` (all buildings, regardless of fog);
  candidate buildings for an attack must be visible or near (§3.12); `EstimateStrengthRatio` counts the real
  defenders [known] S 005a8750, S 005a0dd0. The resource maps cover the whole map, but the ResourceSystem only
  uses continents the AI occupies.
- No production, combat or start-resource bonus is applied by the AI code; AI players get the same
  `StartResources` as humans (`players-victory.md`) [inferred: no such write in the NAI functions read].
- Two rules **outside** the AI code treat a computer slot (player kind 1) differently, both keyed on the
  match's start-resources level `Player.state` (+0xec: 0 high, 1 medium, 2 low, 3 campaign only) [known]
  S 005be330, S 005be350; owners `players-victory.md` §3.4 and `village-buildings.md` §3.8:
  - the tribe's `bonusResources` (`tp_addBonusResources`) are added to the initial stock of a human's start building
    at level 0 or 1, of a computer player's **only at level 3** (`Depot::AddInitialStock` S 0055b020);
  - mines (`size == 8`, working mode 6) of a human need no food at level 0; the mines of a computer player
    request and consume food at every level except 3.
  So in a skirmish the computer player is worse off than a human on "high" resources, not better.
- The AI's street plans are the only street paths built with the randomised path walk (§8).
- No shipped map gives computer slots extra goods by script [known: data and code]. A map script is only the
  sidecar `<MapInfo name>.lua` beside the map, run if the file exists (`GameScript_LoadMapScript` S 005b1fe0);
  the `.s2m` holds the map part only (`../map-format.md` §1.1) and none of the 31 `.s2m` files of the data tree
  contains Lua text or bytecode. The 20 free-game maps (`game/maps/Freegamemaps`, MapInfo names equal to the
  file names) have no sidecar anywhere in the data tree; sidecars exist only for `C01`..`C11` and
  `Presentation`. `logic.vi_addGoodsToDepot` occurs only in `C04`, `C05`, `C06`, `C08`, `C10` and in
  `mapTools/spawnDepots.lua`, which only campaign scripts include (`C01`..`C11`); the binary names no
  free-game script. None of these calls tests the player kind (§10 Q7).

## 4. Update order

`NLogic::System::Update` calls `NAI::System::Tick` once per logic tick (position 16 of the tick order,
`logic-core.md`). Nothing in the AI runs per frame. [known] S 00581a30:

1. If `System.enabled` is false: nothing. Else `tick += 1`. `enabled` is true from the constructor
   (S 00581e30) and is restored by `Load`; the only other writers are the cinematic pair: showing a cinematic
   saves the flag and clears it (S 00782b60, from `nMenu::Cinematic::OnShow`), `nGame::System::EndCinematic`
   S 00782bb0 writes the saved value back [known; a text search of the function cache for writes to the field
   finds no other]. All computer players, and the military maps of human players, therefore stand still while
   a cinematic is shown, and the AI tick counter does not advance.
2. For slot i = 0..7: if the game player of the slot is active, `militaryMaps[i]->UpdateStep()` (one low-res
   cell per tick, row-major, wrapping); then if `players[i]` is active: deactivate it if it has no cells, else
   `players[i]->Update(tick)`.
3. If the resource map is initialised: `ResourceMap::UpdateStep` (`cellsPerStep = max(1, cells / 600)` cells,
   a full refresh about every 600 ticks); and when `(cellsPerStep * tick) & 15 == 0` one cell of the low-res
   resource map.

`Player::Update(tick)` [known] S 00582af0 does nothing while `bEnabled` (+0xd0) is 0. Otherwise it uses
`t = tick + playerIndex * 5` and runs, in this order (period in ticks; `t % period == 0`):

| # | Period | Step |
|---|---|---|
| 1 | 13 | NeedsArrangement::Update |
| 2 | 17 | NeedsConstruction::SelectConstruction |
| 3 | every | CellSystem::Update: 37 CellFull expiry; 19 CellExpansion; 1423 CellDepotCreation; 5 CellValidator; 53 CellClearing |
| – | | the rest only if the player has at least one cell |
| 4 | 23 | ResourceSystem::UpdateExpansionTarget (not gated by `expansionEnabled`: S 00590820 does not read the switch; its target is only consumed by step 5) |
| 5 | every | ExpansionSystem::Update, only with `expansionEnabled` (tested inside, S 00590fd0): 211 Expedition; 29 arbitration |
| 6 | every | MilitarySystem::Update, in this order: 311 MilitaryBuildingCreation; 53 MilitarySettings; 141 AttackSystem; 409 SoldierCreation; 5 CatapultConstruction; 141 catapult production; 631 WeaponProduction; 647 CoinProduction; 37 MilitaryUpgrade; 3 Casern; 127 attack watches (map order by fight Unique); 53 MilitaryLimiter |
| 7 | every | ConstructionSystem::Tick: 7 StreetConstruction; 67 StreetOptimizer; 37 StreetRouteOptimizer; 3 ForesterConstruction; 673 ShipConstruction; 389 SacrificeSitePlanner; 600 back-off reset; 50 order poll or `constructionTicker` order step |
| 8 | every | DestructionSystem::Update, one branch per tick: `t % 41 == 0` building; else `t % 59 == 0` cell demolish; else one flag |
| 9 | 47 | NeedCreation::Update |
| 10 | 337 | LockSmith::Update |
| 11 | 643 | FoodArrangement::Update, then GoodsArrangement::Update |
| 12 | 67 | ProductionControl::Update |
| 13 | 1323 | ConqueredContinents::Rebuild |
| 14 | 647 | sacrifice manager (with `sacrificesEnabled`) |

All period tests are unsigned (`t` is a u32). The order step of row 7 computes `t % profile.constructionTicker`
without a guard, so a profile with `ai_setConstructionTicker(0)` divides by zero [known] S 00592210.

Observed cadences [live, 2026-10-12, developed save with five computer players, ticks 53,306 to 55,001]:
`NAI::System::Tick` S 00581a30 ran every tick (one object); `MilitaryLimiter::Update` S 00597c80 on three
objects, each every 53 ticks (31 of 31 intervals); `LockSmith::Update` S 0058d130 on three objects, each every
337 ticks (4 of 4), 5 ticks apart from each other (the `playerIndex * 5` offset); `AttackExecution::Update`
S 005a0dd0 at intervals of 141 ticks (6 of 7) and once 1,269 = 9 x 141, so it does not run on every 141-tick
step; `AiStreetPlan::PlanPath` S 005a96b0 in groups of three calls 5 ticks apart, the groups 37 ticks apart
(the StreetRouteOptimizer, one call per computer player; 169 calls). Build order and the free tool were not
watched.

The limiter at position 6 uses `t` as its clock, so `attackLimiterDelay` is in ticks (2400 = 4 minutes at
speed 1) [known] S 00597c80. It does nothing while `attackLimiterDelay == 0` (the constructor default). It is
tested only on the ticks with `t % 53 == 0`, so a new budget arrives up to 52 ticks after `nextTick` has passed
[known] S 00585380.

Event-driven entries (called from other subsystems inside the same tick): building created / transferred /
destroyed (`NVillage::Building` constructors and destructor -> `OnBuildingAdded` / `OnBuildingRemoved`), navy
object linked to / unlinked from a flag (`NNet::Flag::LinkNavyObject` / `UnlinkNavyObject` -> `AddHarbor` /
`RemoveHarbor`), a fight getting its target building / a fight being destroyed
(`NMilitary::Fight::SetTargetBuilding` S 00570760 / `Fight::dtor` S 00571790 -> attack watch added / removed
for both parties)
[known] callers of S 0053bdd0, S 0053bdf0, S 0053be50, S 0053be70, S 0053be90, S 0053bed0. Each forwards only
when the AI player of the owner slot is active. The order callbacks of the construction system are virtual
calls on the registered order owners inside `ConstructionSystem::Tick` [known] S 00592210.

## 5. Inputs and outputs

**Inputs**

- Slot setup: kind "computer" and its level (`players-victory.md` §3, `map-format.md` slot table).
- Map script calls (`logic.ai_*`, see §2.5 and `lua-surface.md`): `ai_enable`, `ai_disable`, `ai_isEnabled`,
  `ai_allowAttack`, `ai_setAttackEnable`, `ai_setAllowedAttackCount`, `ai_enableExpansion`, `ai_enableNeeds`,
  `ai_enableCoinProduction`, `ai_enableForesting`, `ai_enableSacrifices`, `ai_enableCatapultsLocal`,
  `ai_enableShipConstruction`, `ai_allowHarborPosition`, `ai_forbidHarborPosition`,
  `ai_forbidAttackingPlayer`, `ai_allowAttackingPlayer`.
  `data/game/scripts/mapTools/aiLimiter.lua` is a script-side attack limiter for maps: per player it stores a
  delay and a random range in minutes and, when `ticks / 600` passes the stored time, calls
  `logic.ai_setAllowedAttackCount(player, 3)` and schedules the next time [known] file content.
- `map_createDoodad` / `map_removeDoodads` trigger `System::RefreshPlayersAndResourceMap`: for every active
  AI player re-read the start continent, rebuild the conquered continents and refresh the continent id of
  every cell (`Player::Refresh` S 005830d0), then rebuild the whole resource map [known] S 00581960.
- World state read: village buildings and their properties, player stock and statistics, map ownership,
  continents, walk regions, visibility grid, harbours, ship routes, ships, the fight list, the sacrifice state.

**Outputs** (direct calls into the simulation, [inferred] from callee names):

- `NVillage`: place building, remove building, start upgrade, `Production::SetEnabled`, soldier kind switch,
  storage good flags, food distribution priorities, sacrifice research / order / start, self-destruct
  countdown;
- `NNet`: place flag, build street, remove street, remove flag;
- `NMilitary`: `Attack::StartAttack(player, building, fraction)`, `Military_RequestCancel`, player military
  settings 1 and 2, the per-building defence fraction;
- `NNavy`: assign a ship to a route, order an expedition ship to found a colony;
- `NLogic::Stock::AddOne` (the free tool).

The AI raises no events of its own and sends no network messages.

## 6. Data-driven parameters

### 6.1 AI profiles: `data/game/scripts/properties/ai.lua`

Created with `properties.ai_create("<hex id>")`; looked up by `PropertiesDb::GetAiProperty(id)` S 005476e0.
Fields of `AiProperty` [known] ctor S 00555e80, struct layout, the `LuaProps_ai_*` binders S 0054b4d0 ..
S 0054c130:

| Offset | Lua setter (`properties.`) | Type | Default | Weak / Normal / Strong |
|---|---|---|---|---|
| +0x00 | id (the argument of `ai_create`, a string parsed as hex, S 0054b4d0) | int | -1 (S 00556c80) | 1 / 2 / 3 |
| +0x04 | `ai_setName` | string | "unknown" | "Weak" / "Normal" / "Strong" |
| +0x20 | `ai_setMilitaryMode` (0 Safe, 1 Normal, 2 Aggressive) | int | 1 | 0 / 1 / 1 |
| +0x24 | `ai_setMaximumSmithies` | int | 100 | 2 / 2 / 4 |
| +0x28 | `ai_setMaximumMints` | int | 100 | 0 / 1 / 3 |
| +0x2c | `ai_enableStreetOptimizing` | bool | 1 | 1 / 1 / 1 |
| +0x2d | `ai_enableRouteOptimizing` | bool | 1 | 0 / 1 / 1 |
| +0x2e | `ai_enableCatapults` | bool | 1 | 1 / 1 / 1 |
| +0x2f | `ai_enableCoinArrangement` | bool | 1 | 0 / 0 / 1 |
| +0x30 | `ai_setStartFrameProducerCount` | int | 1 | 1 / 2 / 3 |
| +0x34 | `ai_setFactor(battleMode, valueOf, f)`: float[2][2], index `valueOf + 2*battleMode`; battleMode 0 Attack / 1 Defense, valueOf 0 Own / 1 Enemy | float | 0 | A/Own 0.4 / 0.6 / 0.9; D/Own 0.5; A/Enemy 0.8 / 0.6 / 0.6; D/Enemy 0.8 / 0.5 / 0.5 |
| +0x48 | `ai_setBattleCalcRatio(a, b, c)` (weights: profile factor, history, random) | float[3] | 0.5, 0.3, 0.2 | not set |
| +0x54 | `ai_setRetreatChance` (%) | int | 50 | 30 / 40 / 50 |
| +0x58 | `ai_setDestroyLostBuildingChance` (%) | int | 50 | 30 / 40 / 50 |
| +0x5c | `ai_setSwordBowRatio` | float | 0.5 | not set |
| +0x60 | `ai_setSacrificesStartTime` (s) | float | FLT_MAX | – / – / 0 |
| +0x64 | `ai_setSacrificesLimit` | int | 1 | 1 / 2 / 3 |
| +0x68, +0x78 | `ai_addFavoritSacrifice(id, weight)` (parallel vectors) | int | empty | 30 entries each; weights 10..30 / 10..50 / 10..70 |
| +0x88 | `ai_enableWaterStreets` | bool | 1 | not set / not set / 1 |
| +0x8c | `ai_setSpecialAttackMinFactor` | float | 0.1 | not set |
| +0x90 | `ai_setSpecialAttackRandomValue` | int | 90 | not set |
| +0x94 | `ai_setSpecialAttackBestChance` | float | 0.1 | not set |
| +0x98 | `ai_setSpecialDefenseFactor` | float | 0.1 | not set |
| +0x9c | `ai_setSpecialDefenseRandomValue` | int | 50 | not set |
| +0xa0 | `ai_setConstructCatapultRating` | float | 600 | 600 / 600 / 200 |
| +0xa4 | `ai_setCatapultEnemyThreatFactor` | float | 2 | – / – / 2 |
| +0xa8 | `ai_setCatapultFriendThreatFactor` | float | 2 | – / – / 2 |
| +0xac | `ai_setCatapultAttackFailedFactor` | float | 10 | – / – / 200 |
| +0xb0 | `ai_setBuildCatapultDecreaseFactor` | float | 1 | – / – / 2 |
| +0xb4 | `ai_setCatapultConstructionTime` (ticks per sweep) | int | 3000 | not set |
| +0xb8 | `ai_enableAllocation` | bool | 1 | not set / not set / 1 |
| +0xbc | `ai_setAttackLimiterDelay` (ticks) | int | 0 | 3600 / 2400 / 1200 |
| +0xc0 | `ai_setAttackLimiterDelayRandom` | int | 0 | 1200 / 1200 / 1200 |
| +0xc4 | `ai_setAttackLimiterAttackCount` | int | 0 | 1 / 2 / 3 |
| +0xc8 | `ai_setAttackLimiterAttackCountRandom` | int | 0 | 1 / 2 / 3 |
| +0xcc | `ai_setConstructionTicker` (ticks) | int | 1 | 7 / 3 / not set |

The campaign profiles (`ai_c2_catapult` Safe, `ai_c5_pirates`, `ai_c6_severin`) set the same keys; notable
values: catapult profile `catapultConstructionTime` 300 and `catapultEnemyThreatFactor` 4; Severin limiter
3000 + rand 3000 ticks, 1 + rand 2 rounds, retreat and destroy chances 0.

Since the defaults of `waterStreets` and `allocationEnabled` are already 1, Weak and Normal have them on too;
the explicit `true` in Strong changes nothing [known] ctor defaults vs `ai.lua`.

### 6.2 Goods: `Goods.lua`

| Key | Field | Use | Examples |
|---|---|---|---|
| `gp_setAiPriority(good, tribe, n)` | GoodProperty +0x64 map tribe -> int | weight in SelectConstruction (§3.5) | stone 300, tool 150, coal 100, bread 70, coin 50; range 40..500 |
| `gp_setAiRandomValue(good, n)` | +0x8c | weight when a group need picks a member (§3.4) | bread 6, fishScots 10, sheepHam 1 |
| `gp_setAINoNeedForCosts(good)` | +0xa4 := 0 | skip the inputs check when placing (§3.4) | 5 goods: `stone`, `stoneBav`, `stoneScots`, `sacrificeGood`, `sacrificeGoodOlympicFlame` |
| `gp_setType(good, t)` | +0x14 (int, constructor default 0, S 00554da0). The values are Lua globals set at the top of `Goods.lua`: `Invalid` = -1, `Ware` = 0, `Settler` = 1, `WareGroup` = 2, `EitherGroup` = 3 [known] file content. The script passes `WareGroup` (29 goods) and `EitherGroup` (12 goods); 59 of the 100 goods keep the default 0 | type 3 needs go to `needsB`; type 0 is "controllable" | `foodScots` EitherGroup of `fishScots`, `bread`, `sheepHam` |
| `gp_addCost(good, input, n)` | +0x04 list of {good, amount} | the input lists every rule walks | `constructionResourcesBav`: plank 1, stoneBav 1 |

### 6.3 Buildings: `buildings.lua`

| Key | Field | Use | Examples |
|---|---|---|---|
| `bp_setAiScore(b, n)` | BuildingProperty +0xd0 (default 20) | MilitaryMap `score`; defensive weight of a target | woodcutter 50, depot 100, gold mine 180, castle 150, catapult 300 |
| `bp_setAiThreat(b, n)` | +0xcc (default 0, ctor S 00553cf0) | MilitaryMap `threat` | guard house 30-40, tower 60-70, fortress 90-100, casern 30, castle 50, catapult 100, sacrifice 0 |
| flags read | depot +0x54, casern +0xf1, territory building +0xf5, catapult +0xb0, soldier limit / tier +0x98, working mode +0x80, size +0x3c, worker +0x90, working radius +0x78 | classification (§2.3, §3.8) | see `village-buildings.md` |

### 6.4 Tribes: `tribes.lua`

`tp_setConstructionGoodId` (+0xb4), `tp_setSecondCarrierId` (+0xb0), `tp_setSoldierUpgradeGoodId` (+0xb8),
`tp_setWorkerToolGoodId` (+0xbc), the good list (+0x20) and building list (+0x40) in script order. Example
Bavarians: `constructionResourcesBav`, `good_oxen`, `coinBav`, `toolBav` [known] `tribes.lua`, struct layout of
`TribeProperty`. The order of `tp_addBuilding` lines matters: every "first tribe building with property X"
lookup (S 0059f580 .. S 0059fb80, S 00592c40) walks that list.

### 6.5 Fixed constants in code

All periods of §4; cell sizes 16 / 8 / 4; need stage times 0 / 300 / 800 / 1200 s; growth period 600 s
doubling; stock thresholds 6 (inputs), 10 (tool gate), 20 (tool need), 40 (+20 hysteresis; production limit
base), 5 (food); cell need cap 20; cost weight 50 per same need; front-line distance 36; casern spacing 25;
attack area radius 12; near-slot distance 15; visibility-or-distance 13; hopeless ratios 0.25 / 0.5; retreat
ratio 0.5; site rank distances 19 / 24, soldier count 30, stock 40, tick 18000; upgrade reserve x2; street
length limit x2 direct distance; route optimiser x4 and -2; back-off `2n + 2` per 50 ticks, reset 600.

## 7. Save and load

A section tag in a file is the section's version (u32) followed by the CRC accumulator of the section **name**
(`logic-core.md` §7), so a reader of original saves needs the exact name strings. The names below are the
strings of the static initialisers S 007c3250 .. S 007c6120 [known]; they contain a space after the `AI` / `Ai`
prefix and some are misspelt in the binary (`Ai ReferncesNeed` / `Building` / `Harbor` / `Production`,
`AI CellPositionItertator`). The number in brackets after a name is the section's current version (the third
constructor argument in the same initialiser) [known]. A section at version 0 cannot have a version gate in its
`Load` [inferred].

The AI state is part of the save game: `NAI::System::Store` S 00581ad0 writes the section tag `AI System` [2]
and then the sequence below [known]. `NAI::System::StoreBody` S 00581b90 writes the same sequence without the tag;
its only caller is `nGame::System::ComputeChecksum` S 00784080, so the complete AI state also feeds the
lockstep checksum [known for the caller list]. In the save file the AI section follows the street net and
precedes the statistics (`GameFile_SaveLogic` S 005a9ec0); in the checksum stream `StoreBody` is item 9 of 10,
after the street net and before the unique-id counter (`logic-core.md` §3.6, §7). The sequence:

1. bool `initialized`;
2. for i = 0..7: `players[i]` (always), then `militaryMaps[i]` only if the game player of slot i is active
   [known];
3. u32 `tick`;
4. resource map, low-res resource map;
5. bool `enabled`.

`NAI::System::Load` S 005821f0 reads the same sequence with two version gates [known]: a file of version 0
holds no military maps at all; version 1 holds the military map of every slot; from version 2 on only those of
slots whose game player is active.

`NAI::Player::Store` [known] S 00583180: section tag `AI Player` [7]; bool `bActive`; int profile id (-1 when no
profile); and only if active, in this order: start position; ConstructionSystem; NeedsArrangement;
NeedsConstruction; ResourceMapAdds; LowResResourceMapAdds; buildings map; needsA; needsB; productions;
TerritoryMap; CellSystem; ExpansionSystem; MilitarySystem; ResourceSystem; DestructionSystem; NeedCreation;
LockSmith; FoodArrangement; GoodsArrangement; ProductionControl; ConqueredContinents; the nine switch bytes
+0x94..+0x9c in offset order; harbours map; forbidden harbour positions; enemy exclusions (u32 count, then one
int per player index, S 00582710); bool `bEnabled`.

`NAI::Player::Load` S 00584320 reads the three bytes +0x94..+0x96 always and the rest by version `v` of the
section: `sacrificesEnabled` and `catapultsLocalEnabled` if `v >= 1`; `waterStreets` and
`shipConstructionEnabled` if `v >= 2`; the forbidden harbour positions if `v >= 3`; `forestingEnabled` if
`v >= 4`; the enemy exclusions if `v >= 5`; `bEnabled` if `v >= 6` (older: set to 1); `attackAllowed` if
`v >= 7` [known: disassembly of S 00584320, the version is kept in `EBP` and compared with 1, 2, 4, 7, 3, 5, 6
before the bytes +0x97/+0x98, +0x99/+0x9a, +0x9b, +0x9c, the harbour positions, the exclusions and `bEnabled`].

`MilitarySystem::Store` [known] S 00585280: tag `Ai MilitarySystem` [2]; bool active; MilitaryBuildingCreation;
MilitarySettings; AttackSystem; SoldierCreation; CatapultConstruction; WeaponProduction; CoinProduction;
MilitaryUpgrade; Casern; attack watch map; fight history; MilitaryLimiter last (S 00597c00: tag
`AI MilitaryLimiter` [0], bool active, u32 `nextTick`). The sacrifice manager (Player +0xac) is not written by
`Player::Store` and no store function lies among its functions (S 00589c00 .. S 0058a4a0): it has no state to
keep, because `AiSacrificeState::Refresh` rebuilds all of it at the start of every update (§3.15) [known]
S 0058a4a0, S 0059cf60. Its only own byte (+0xc, 0 from the constructor S 00589c00) is set to 1 by
`Player::Load` [known] S 00584320. What a sacrifice round
leaves behind is saved by its owners: the needs it added (the player's need maps), the chosen sacrifice and the
research (village building / `NSacrifice`, `village-buildings.md`).

`NAI::Cell::Store` [known] S 00594d80: tag `Ai Cell` [2]; bool; Unique; cell position (+0x20, the AI-cell
coordinates); centre map position (+0x2c); depots; default buildings;
military; productions; needs; threat trigger; no-depot trigger; CellFull; demolish trigger; int demolish
type; consumers; harbours; int continent id; kind-7 list; caserns; kind-9 list.

`NAI::Need::Store` [known] S 005972a0: tag `Ai Need` [0]; bool; Unique; int good id; cell ref; production ref;
building ref; resource position; bool placementPending; child need ref; parent need ref.

Every map is written as a u32 element count followed by the elements in the tree's iteration order (Unique
ascending [inferred]) [known] `NAI_StoreUniquePtrMap` S 00582600, `NAI_StoreHarborMap` S 00582690,
`NAI_StoreAttackWatchMap` S 00585150. All
cross-object links are stored as Unique references and resolved in `PostLoad` (Player S 00582e10, Cell
S 005947c0, Need S 00596f70, CellSystem S 0058adb0) [inferred].

**Recomputed on load** [known] S 005819a0, S 005821f0, S 00584320: the start continent id
(`CacheStartCellData`), the street planner and both path analyzers (restarted, sized to the map), the low-res
visit grid (resized, zero-filled). The profile pointer is re-resolved from the stored id (left as it is when the
id is -1). `ResourceMapAdds` and `LowResResourceMapAdds` are created anew and then loaded. `Player::PostLoad`
registers six order owners with the construction system again [known] S 00582e10. `Load` first runs `Reset`
(deactivates and destroys all eight players, destroys the eight military maps, S 00581d40) and re-creates them.

Not stored (transient): the candidate map of an attack round, A* results, static scratch vectors.

A reimplementation that does not need to read original saves can store its own AI state freely; one that does
must reproduce the nested order above including every sub-module's fields. Field lists of the sub-modules,
each after its section tag, in stream order [known for the order of the stream calls and for the scalar types,
which are the stream slots called: bool = `WriteBool`, int = `WriteInt`, u32 = `WriteSizeT`, float =
`WriteFloat`, 64-bit = `WriteInt64`; the meaning given to a field is [inferred] from its struct name]:

| Module | `Store` | Tag | Fields |
|---|---|---|---|
| ConstructionSystem | S 00591f70 | `Ai ConstructionSystem` [4] | bool active; the offered order (ConstructionOrder); int active order owner; BuildingConstruction; StreetConstruction; ForesterConstruction; StreetOptimizer; StreetRouteOptimizer; ShipConstruction; ConstructionHunter; sacrifice site |
| ConstructionOrder | S 005a1690 | `Ai ConstructionOrder` [0] | int mode; AI-cell position (+0x08, a `CellPosition`, ctor S 005a17a0); map position; int search argument (radius); int building type; int priority; float timestamp |
| BuildingConstruction | S 005a1900 | `AI BuildingConstruction` [0] | bool active; int state; ConstructionOrder (+0x10); SearchConstructionPlace (+0x3c) (both constructed there by the ctor S 005a19d0); result map position |
| SearchConstructionPlace | S 005a9270 | `AI SearchConstructionPlace` [0] | int building type; bool cell mode; cell iterator (a `CellPositionItertator`, row below); u32 ring index; u32 ring; int ring parameter; u32; three map positions (struct names: ring cursor, best cell, path origin); u32 last fully evaluated ring; float best score; int max distance |
| StreetConstruction | S 005a2280 | `AI StreetConstruction` [2] | bool; u32; two dwords written with one call (stream method +0x54); int retry count; vector of tried target positions; u32 count + per map entry {int, reference}; map position (struct name: via position); int best cost; int second cost; int best variant; int variant step; map position (struct name: last target) |
| CellPositionItertator | S 005a8b00 | `AI CellPositionItertator` [0] | centre (a `CellPosition`); map position; int column; int row |
| MinMaxCellIterator | S 005a7df0 | `AI MinMaxCellIterator` [0] | two `CellPosition` objects, +0x00 (starts at 0, 0) and +0x0c (set by the ctor S 005a7ec0 to the AI cell of map position (width + 15, height + 15), the end of the range) |
| ForesterConstruction | S 005a4030 | `AI ForesterConstruction` [0] | bool active; ConstructionOrder; u32 cell cursor |
| StreetOptimizer | S 005a43f0 | `AI StreetOptimizer` [1] | bool active; u32 street cursor |
| StreetRouteOptimizer | S 005a4680 | `AI StreetRouteOptimizer` [1] | bool active; current building key (one 64-bit write); vector of map positions (+0x18, the path being worked on); u32 stage; int path index; u32 fail count; u32 A* step |
| ShipConstruction | S 005a5860 | `AI ShipConstruction` [0] | bool active; ConstructionOrder |
| ConstructionHunter | S 005a5f10 | `AI ConstructionHunter` [0] | bool; ConstructionOrder; u32 request priority |
| sacrifice site | S 005a1d30 | `AI ConstructionSacrificeSite` [1] | bool |
| CellSystem | S 0058acd0 | `Ai CellSystem` [0] | bool active; CellDepotCreation (+0x48); CellExpansion (+0x28); u32 cell count; every cell (`Cell::Store` above); CellValidator (+0x88); CellClearing (+0xac). The offsets are those `CellSystem::Update` S 0058aac0 passes to the four `Update` functions [known] |
| CellValidator | S 0059d830 | `AI CellValidator` [0] | bool active; MinMaxCellIterator |
| CellClearing | S 0059d630 | `AI CellClearing` [0] | bool active; MinMaxCellIterator (+0x10); ConstructionOrder (+0x28, ctor S 0059d760); bool enabled |
| CellExpansion | S 0059e050 | `Ai CellExpansion` [0] | bool active; ExpansionTarget (+0x0c, ctor S 0059e0d0) |
| CellDepotCreation | S 0059e340 | `Ai CellDepotCreation` [0] | bool active; ConstructionOrder (+0x10, ctor S 0059e3d0) |
| Trigger | S 005a7890 / S 005a78e0 (`Load`) | `Ai Cell` [1] (a second section object with the same name as the cell's, S 007c5d50) | bool active; float start time; float value (read only if the version is >= 1, else set to 1.0) |
| CellFull | S 005a6300 | `AI CellFull` [0] | bool; u32 count; per map entry: int good id, CellFull element |
| CellFull element | S 005a6140 | `AI CellFullElement` [0] | Trigger; u32 expire count |
| ExpansionSystem | S 00590e70 | `Ai ExpansionSystem` [1] | bool active; current target; candidate target (both ExpansionTarget); int source; Expedition |
| ExpansionTarget | S 005a0180 | `Ai ExpansionTarget` [0] | int kind; position; float time |
| Expedition | S 005a0240 | `AI Expedition` [0] | bool active |
| ResourceSystem | S 005905a0 | `Ai ResourceSystem` [0] | bool active; list of need references (reference lists: tag `Ai ReferncesNeed` / `Building` / `Harbor` / `Production` [0], u32 count, the references; S 0059fde0, S 005a7130, S 005a75c0, S 005a79d0); ExpansionTarget; int state |
| DestructionSystem | S 0058d9f0 | `Ai DestructionSystem` [2] | bool; u32 flag cursor (the index of the flag step, S 0058de80); building cursor (the 64-bit id of the building step's key, one 64-bit write without a tag) |
| NeedCreation | S 0058d2d0 | `AI NeedCreation` [0] | bool; int stage; int periodMultiplier |
| LockSmith | S 0058d000 | `AI LockSmith` [0] | bool; reference to its tool need |
| FoodArrangement | S 0058cbf0 | `AI FoodArrangement` [0] | bool active |
| GoodsArrangement | S 0058c1e0 | `AI GoodsArrangement` [0] | bool active; int step of the 10-step cycle |
| ProductionControl | S 0058ba90 | `AI ProductionControl` [0] | bool; int good cursor |
| ConqueredContinents | S 0058b510 | `Ai ConqueredContinents` [0] | bool active; u32 count; int continent id each |
| NAI::Building | S 00596780 | `Ai Building` [1] | bool; Unique; village building reference; cell reference; need references; production references (the type flags of §2.4 are not saved) |
| NAI::Production | S 005976d0 | `Ai Production` [0] | bool; Unique; int good id; cell reference; building reference; served-need reference |
| NAI::Harbor | S 0058a630 | `Ai Harbor` [0] | bool; Unique; harbour reference; cell reference; int ship route exit count; int continent id |
| MilitaryBuildingCreation | S 00599fd0 | `Ai MilitaryBuildingCreation` [0] | bool; ConstructionOrder (+0x10); ExpansionTarget (+0x3c) (ctor S 0059b0c0); int cooldownTicks; int retry index |
| MilitarySettings | S 00599cc0 | `AI MilitarySettings` [0] | bool; int countdown |
| AttackSystem | S 00599ad0 | `Ai AttackSystem` [1] | bool active; AttackTargetSelection; AttackExecution; int budget (§3.12) |
| AttackTargetSelection | S 005a85b0 | `Ai AttackTargetSelection` [1] | bool active; the three target slots, each an AttackTarget |
| AttackTarget | S 005a9a20 | `Ai AttackTarget` [0] | low-res position (a `LowResPosition`, ctor S 005a99f0); int; float time; int target player |
| AttackExecution | S 005a0620 | `Ai AttackExecution` [3] | bool active; per slot the primary and the secondary target position (3 x 2 positions); ExpansionTarget (+0x40, the fallback request; ctor S 005a0880) |
| SoldierCreation | S 005994e0 | `AI SoldierCreation` [0] | bool |
| CatapultConstruction | S 00598cc0 | `AI CatapultConstruction` [0] | bool active; low-res position (+0x14); float best score; low-res position (+0x24); u32 cells per step; ConstructionOrder (+0x34) (types from the ctor S 00598d30) |
| WeaponProduction / CoinProduction | S 00598890 / S 00598560 | `AI WeaponProduction` / `AI CoinProduction` [0] | bool; int needsAdded; float lastNeedTime |
| MilitaryUpgrade | S 005981f0 | `AI MilitaryUpgrade` [1] | bool; u32 (+0x0c, the round-robin building index of S 005982a0) |
| Casern | S 00597d50 | `AI Casern` [0] | bool active; MinMaxCellIterator; ConstructionOrder; bool (struct name: placement enabled) |
| AttackWatch | S 0059b170 | `Ai Fight` [1] | bool; Unique; fight reference; bool handled |
| fight history | S 0059b890 | `Ai FightSettings` [0] | u32 count; the fight records (0x18 bytes each in memory) |
| fight record | S 0059b650 | `Ai FightData` [1] | int; int (struct names: opponent player, "we defend"; meaning [inferred]); two u32 counts; map position |
| MilitaryMap | S 005862c0 | `Ai Military Map` [0] | bool initialized; int width; int height; every element (no count); the update cursor (+0x28, a low-res position) |
| MilitaryMapElement | S 00586370 | `AI Military Map Element` [2] | the int values of §2.2 in offset order (two loops: 3, then 2); vector of harbour positions |
| TerritoryMap | S 005915d0 | `Ai TerritoryMap` [0] | bool initialized; int width; int height; per element (no count): tag `AI TerritoryMap Element` [2], cell Unique, the 7 u32 counters |
| NeedsArrangement | S 005938d0 | `AI NeedsArrangement` [0] | bool active; ExpansionTarget |
| NeedsConstruction | S 00592bf0 | `AI NeedsConstruction` [0] | bool; ConstructionOrder; a Unique (ctor S 00593800) |
| ResourceMap | S 00587750 | `Ai ResourceMap` [1] | bool initialized; int width; int height; every cell's element list (no count); scan position; low-res scan position; int `cellsPerStep` |
| LowResResourceMap | S 00588d90 | `Ai LowResResourceMap` [0] | bool initialized; int width; int height; every cell's element list (no count); the update cursor |
| resource element list | S 0059c1a0 | `AI ResourceMapElements` [0] | u32 count; the elements |
| resource element | S 0059c040 | `AI ResourceMapElement` [0] | int resource id; int source kind; int amount; int area id |
| ResourceMapAdds | S 0058f130 | `Ai ResourceMapAdds` [0] | bool initialized; u32 count; per element: tag `Ai ResourceMapAddsElement` [0], a Unique (struct name: the claim), bool (S 0058ec60) |
| LowResResourceMapAdds | S 0058e3a0 | `Ai LowResResourceMapAdds` [0] | bool initialized; u32 count; per element: tag `Ai LowResResourceMapAddsElement` [1], u32 constant 2, two u32 values (S 0058e200) |

**Encodings of the shared value types** (stream slots: `save-format.md` §2.2; the 12-byte section tag: §2.4;
a bool is 4 bytes):

| Value | Bytes | Layout |
|---|---|---|
| map position (`ai::map::MapPos`) | 20 | tag `PatternCursor` [0], int x, int y [known] S 00675190, S 006751d0 |
| AI grid position (`CellPosition`, `LowResPosition`, `ResourcePosition`, `LowResResourcePosition`) | 8 | int x, int y, no tag: all four vtables (S 007ea24c, S 007e9e04, S 007e9e90, S 007e9dd4) share the `Store` S 00582400 and the `Load` S 00589a70 [known] |
| `NLogic::Unique` | 20 | tag `logic UniqueId` [0], one 64-bit value (low dword first) [known] S 005386e0, S 00538710 |
| reference (to a cell, building, need, production, harbour, fight) | 20 | the `Unique` of the target, both dwords -1 when empty; the pointer is not stored and is looked up again after the load [known] S 0059d3c0, S 0059d470; `save-format.md` §2.1 |
| vector of map positions | 4 + 20 n | u32 count, then each position with its tag [known] S 00529630, S 0052a850 |

**Version gates of the `Load` functions.** Only a section with a current version above 0 can have one. `v` is the
version read from the tag [known, each read in the named `Load`]:

| Section | `Load` | Gate |
|---|---|---|
| `Ai MilitarySystem` [2] | S 00585d60 | attack watch map and fight history only if `v >= 1`; MilitaryLimiter only if `v >= 2`, else the limiter is activated without reading |
| `AI Military Map Element` [2] | S 00586700 | `v <= 1`: three ints, `threat`, `threatUnfinished`, `score` (+0x04, +0x08, +0x14); `v >= 2`: all five; the harbour vector only if `v >= 1` |
| `Ai ResourceMap` [1] | S 00588b70 | `v == 0`: one resource element per cell, appended to the cell's list only when its resource id (element +0x04) is not -1; `v >= 1`: the element list per cell [known: disassembly, the version is tested with `CMP [ESP+0x3c], 0` / `JNZ` and the temporary's +0x04 with `CMP ..., -1`] |
| `Ai LowResResourceMapAddsElement` [1] | S 0058e250 | `v == 0`: one u32 (+0x04); `v >= 1`: u32 count n, then n u32 values written to +0x04, +0x08, ... without a bound check (the writer always stores n = 2) |
| `Ai DestructionSystem` [2] | S 0058da40 | `v <= 1`: a 64-bit value is read and dropped, flag cursor = 0; `v >= 2`: u32 flag cursor. Then the 64-bit building cursor only if `v >= 1` |
| `Ai ExpansionSystem` [1] | S 00590ed0 | Expedition only if `v >= 1`. After the read, Expedition is set active when the AI player is active |
| `AI TerritoryMap Element` [2] | S 005910c0 | number of counters read: 5 (`v == 0`), 6 (`v == 1`), 7 (`v >= 2`) |
| `Ai ConstructionSystem` [4] | S 00592860 | ShipConstruction read if `v >= 1`, ConstructionHunter if `v >= 2`, sacrifice site if `v >= 4`; a module that is not read is activated instead when the AI player is active. If the system is active, the order owners of ForesterConstruction, ShipConstruction and ConstructionHunter are registered again here |
| `Ai Cell` [2] | S 00596130 | consumers: one building reference if `v <= 1` (kept only when it is set), the reference list if `v >= 2`; kind-7 buildings: one reference if `v == 0`, the list if `v >= 1`; the kind-9 list only if `v >= 2` |
| `Ai Cell` [1] (Trigger) | S 005a78e0 | float value only if `v >= 1`, else 1.0 |
| `Ai Building` [1] | S 005967f0 | none (the version is not read) |
| `AI MilitaryUpgrade` [1] | S 00598230 | `v >= 1`: u32 building index; `v == 0`: a 64-bit value is read and dropped, index = 0. Both branches rebuild the building ranking |
| `Ai AttackSystem` [1] | S 00599b30 | int budget only if `v >= 1`, else -1 |
| `Ai Fight` [1] | S 0059b1c0 | bool handled only if `v >= 1` |
| `Ai FightData` [1] | S 0059b6c0 | `v == 0`: after each of the two u32 counts one more int is read and dropped; `v >= 1`: not present [known: disassembly, `CMP [ESP+0x10], 1` / `JGE` inside the two-count loop] |
| `Ai AttackExecution` [3] | S 005a0690 | `v == 0`: nothing after the bool; `v == 1`: the primary position of slot 0, then the ExpansionTarget; `v == 2`: the three primary positions, then the ExpansionTarget; `v >= 3`: per slot primary and secondary position, then the ExpansionTarget (disassembly) |
| `AI ConstructionSacrificeSite` [1] | S 005a1d60 | none (the version is not read). The planner's building type is looked up again from the tribe |
| `AI StreetConstruction` [2] | S 005a3bd0 | `v == 0`: a 64-bit value is read and dropped, the u32 after the bool = 0; `v >= 1`: that u32. The two dwords (one 64-bit read) only if `v >= 2` |
| `AI StreetOptimizer` [1] | S 005a4430 | `v >= 1`: u32 street cursor; `v == 0`: a 64-bit value is read and dropped, cursor = 0 |
| `AI StreetRouteOptimizer` [1] | S 005a4eb0 | u32 A* step only if `v >= 1` |
| `Ai AttackTargetSelection` [1] | S 005a8600 | `v == 0`: one AttackTarget (slot 0); `v >= 1`: three |

**Values of skipped fields.** `NAI::System::Load` runs `Reset` and then constructs every player
(`Player::ctor` S 00584870, which constructs all modules) and every military map (S 005864e0) anew before it
loads them, and the containers resize to fresh default elements; `Activate` is not called by any `Load`. So a
field that an old version does not carry keeps its constructor value, unless the gate table sets it [known]
S 005821f0, S 00584870:

- `Player`: the switch bytes +0x97..+0x9c = 1; forbidden harbour positions and enemy exclusions empty
  (`bEnabled` = 1 is set by `Load`);
- military map of a version-0 `AI System`: not loaded, `initialized` 0, no elements, cursor (-1, -1) S 005864e0;
- `AI Military Map Element` v <= 1: `threatCatapult` (+0x0c) and `scoreCatapult` (+0x10) = 0; v == 0: no
  harbour positions (elements resized from an all-zero element, S 00587380, S 00587270);
- `Ai LowResResourceMapAddsElement` v == 0: +0x08 = 0 (all-zero element, S 0058ebe9);
- `Ai DestructionSystem` v == 0: building cursor = -1 / -1 (S 0058d9d4);
- `AI TerritoryMap Element` v <= 1: the counters not read = 0 (S 00591f49 resizes from a zero element);
- `Ai MilitarySystem` v == 0: no attack watches and an empty fight history (the containers as constructed;
  the `MilitarySystem` ctor was not re-read [inferred]);
- `Ai Fight` v == 0: `handled` = 0 (S 0059b230);
- `Ai AttackExecution` v <= 2: the positions not read = (-1, -1); v == 0: the ExpansionTarget as constructed,
  kind 0, cell (-1, -1), time 0.0 (S 005a08b3, S 005a0227);
- `AI StreetConstruction` v <= 1: the two dwords (struct name `posA`) = -1 / -1 (S 005a33e4);
- `AI StreetRouteOptimizer` v == 0: A* step = 0 (S 005a4c7f);
- `Ai AttackTargetSelection` v == 0: slots 1 and 2 empty: low-res position (-1, -1), kind 0, time 0.0, target
  player -1 (S 005a99f7);
- `Ai Cell` v <= 1: no kind-9 buildings.

All of this matters only for saves older than the shipped version.

`ConstructionHunter` is a module of the construction system that is constructed, registered as an order owner,
saved and loaded, but `ConstructionSystem::Tick` never calls an update for it and no update function exists
among its functions (S 005a5ec0 .. S 005a60c0: activate, deactivate, `Store`, `Load`, ctor, dtor, the owner id
getter that returns 8, the order callback) [known]. Its order callback halves
a counter of the player's low-res resource annotation at the order position (S 005a60c0). Its request getter
(slot 0 of its order-owner vtable at S 007ea810, S 005a5960) returns the address of its own ConstructionOrder
[known], and `ConsiderNeedRequest` S 00592070 takes a request only when its building type is not -1 [known].
None of the module's functions writes that order except the ctor, `Load` and the two that invalidate it, so
the module offers an order only if a loaded save carries a valid one [inferred from the function list; a write
through the owner pointer from another module is not excluded].

## 8. Determinism notes

- The whole AI state is written into the lockstep checksum stream (`StoreBody`, §7), so any divergence of AI
  state between machines is detected as a desync, not only its effects on the world.
- The AI runs inside the logic tick on every machine and must produce identical calls. It uses the **logic
  random generator** (`LogicRandom_Next`, `logic-core.md`) and no other source. Draws, each exactly one call
  unless noted:
  - MilitaryLimiter: 1 draw for the count (only if `attackCountRandom > 0`), 1 for the delay (only if
    `delayRandom != 0`);
  - per attack candidate that is evaluated: 1 (attackers score), 1 (discarded defenders score), then 1 for
    the mode factor if the candidate is not hopeless (also when `ratio < 0`, the two score draws are made);
    1 for the secondary-attack roll when its preconditions hold; a candidate that passes the threshold ends
    the whole attack round, so later slots draw nothing;
  - attack watch creation when attacked: 1 (defence score) + 1 (ignore roll); watch evaluation: 1 when the
    ratio is below 0.5 and the action is possible;
  - ChooseSoldierKind: 1 per call with at least one building;
  - group need member choice (weighted), sacrifice choice (`AI_PickRandomIdFromVector`, the favourite roll),
    sacrifice target player;
  - **street plans**: the two AI street planners (`PlanPath` S 005a96b0, `PlanBetweenFlags` S 005a97d0) turn a
    finished A* search into a cell path with `NMap::AStar::BuildPath(randomize = true)` S 00676d10 [known]:
    when start and goal are not adjacent, 1 draw (`% 6`) for the first direction, then 1 draw
    (`% number of descending neighbours`) at every path cell where the current direction no longer descends.
    The count therefore depends on the shape of the path. `PlanPath` has two callers,
    `StreetConstruction::EvaluateStrategy` S 005a34a0 and `StreetRouteOptimizer::OptimizeRouteBetween`
    S 005a4f30, and `PlanBetweenFlags` one (`EvaluateStrategy`), so both the street builder and the route
    optimiser draw [known] caller lists. Only the route optimiser's direct map path
    (`OptimizeViaMapPath` S 005a4cc0) passes `randomize = false` and draws nothing, as do the streets a human
    plans (`streets-transport.md` §8).
  The **order and count** of draws must match, because the generator is shared with the rest of the
  simulation.
- **Unique ids** come from the shared logic id counter, so their order is part of the state as well: per new
  building its productions, then its new needs, then a new AI cell (§2.3; the mirror reuses the building's
  id); 2 per street the AI builds (§3.7); a harbour mirror reuses its flag's id (§3.8) [known].
- `PickRandomTargetPlayer` computes `rand % candidateCount` and divides by zero with an empty list; callers
  pre-check the category condition [inferred] S 0059d120.
- **Iteration orders** that decide ties: cells in creation order (vector); buildings, needs, productions,
  harbours, attack watches in ascending Unique (maps); players 0..7; low-res scans x outer, y inner in target
  choice, row-major cursors elsewhere; tribe goods and buildings in script order; the village building list in
  creation order (attack candidates, MilitaryUpgrade round-robin).
- All "best of" selections use strict comparisons, so the first candidate in iteration order wins ties. The
  attack candidate map is keyed by a float weight in descending order; a second building with exactly the same
  weight is dropped.
- **Floating point**: scores are single-precision floats computed with x87/SSE code; `game time` is a float.
  A reimplementation that only has to agree with itself can use any consistent arithmetic. Results feed
  discrete choices (argmax, threshold tests), so cross-implementation equality is not achievable without
  bit-exact float evaluation order.
- `Player::Update` offsets the tick by `5 * playerIndex`; this only staggers load but changes which tick a
  rule fires on, hence the order of world mutations between players.
- The incremental maps (military map 1 cell per tick, resource map `cells/600` per tick) mean the AI acts on
  **stale** data; the staleness pattern is part of the behaviour.
- The 3x3 weighting quirk (weight 1.0 at offset (+1,+1) instead of the centre) affects every threat sum.

## 9. Notes for a reimplementation

- Nothing here has to be bit-exact for compatibility with maps. Compatibility with **original save games**
  needs the full store layout (§7); compatibility with **original clients in multiplayer** would need the AI
  to be bit-identical including random draws and float results, which is not a realistic goal. Treat the AI as
  replaceable behind the interface "per tick, per player: read the world, call simulation functions".
- Keep the structure: (1) needs for goods -> (2) cell choice -> (3) one construction order at a time with
  back-off -> (4) site search; a separate expansion arbiter feeding one military-building planner; a
  target-area chooser feeding an attack executor with three slots. The rates in §4 give the feel of the
  original (slow, staggered decisions); they can be kept as a table.
- Things worth keeping exactly because players notice them: the build order of §3.3, the difficulty table
  (§6.1), the attack threshold and fraction formulas (§3.12), the limiter (a new attack budget every 2-4
  minutes for Strong, 4-6 for Normal, 6-8 for Weak: `attackLimiterDelay` + rand `attackLimiterDelayRandom`
  ticks, §6.1),
  the retreat / burn-building rolls, `maximumSmithies` / `maximumMints`, the `constructionTicker` slowdown.
- Things that can be simplified: the two-level resource maps (a direct query for "nearest free deposit of
  resource R near territory" replaces ResourceMap + LowResResourceMap + both Adds grids); the six-variant
  street strategy search (any planner that connects each new flag to the nearest own flag with a path no
  longer than twice the direct distance and occasionally adds flags and shortcuts); the CellFull back-off;
  the fight history (a single remembered ratio per opponent).
- Quirks to decide on deliberately: the 3x3 weight at (+1,+1); the discarded defenders score (it consumes a
  random number); budget units counting evaluation rounds, not attacks; Weak/Normal never building a
  sacrifice building because `sacrificesStartTime` stays at FLT_MAX; buildings counted once, at their anchor
  only, in the military map and the defensive weight; the free tool.
- The AI never repairs `bEnabled` after the headquarters is lost: a computer player without headquarters
  stops planning entirely but its soldiers and buildings keep working through the normal simulation.
- The profile is data: keep `ai.lua` semantics (keys of §6.1) so that the shipped file and mods load
  unchanged.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered for the cadences (§4, after the period table): `System::Tick` every tick, `MilitaryLimiter` every 53, `LockSmith` every 337 (players 5 ticks apart), `AttackExecution` on 141-tick steps but not on every one, street `PlanPath` every 37 per player [live, 2026-10-12]. Open: build order and the free tool in a real match | observation in the running game: build order and LockSmith's free tool |
| 2 | Answered (§3.13): the defence fraction the AI computes on attack-watch creation is never effective; `StartAttack` S 00576500 replaces it with the player setting in its next statement, every fight is created there, and `DispatchDefenders` reads the field 10 ticks later | static: S 00576500, S 0053cf50, S 00570760, S 00573c30, S 005715a0 |
| 3 | Answered (§2.3): the cell demolish trigger is never armed. No code arms it and no shipped file carries AI cells (33 `.s2m` maps, map part only; no `.a2m`, no `.aav`) | static: callers of S 005a7960 (S 005949e0, S 00594a70, S 00594b20, S 005a6fe0), S 005a7940, S 005a78e0, S 005a9fa0 / S 005a9ec0; file list of the data tree |
| 4 | Answered (§3.6): without a producing building type the supplier is the nearest own finished depot of the village's depot list, any distance, on a reachable continent (S 00532640, S 005586d0, S 00557fe0); map state bit 5 = 0x20 territory border, bit 17 = 0x20000 ship ground; construction flags 2 / 4 = a medium / a large building fits (S 00675610) | — |
| 5 | Answered for the listed functions, each re-read line by line and the rules corrected where they differed: streets (§3.7: S 005a3ed0, S 005a3d00, S 005a34a0, S 005a3170, S 005a4550, S 005a5730), placement costs (§3.4: S 00593ea0, S 00593c20, S 00593cd0), site search loop (§3.6: S 005a91e0, S 005a9080, S 005a8ee0), ResourceSystem scoring (§3.8: S 00590820, S 00590400), low-res site query (S 005a8bf0, S 005a8cc0), Expedition (S 005a02c0), FoodArrangement / GoodsArrangement (§3.9: S 0058ced0, S 0058cb70), SoldierCreation (§3.10: S 00599860), strength ratio (§3.12: S 0059ec60, S 0059e6c0), sacrifice ordering (§3.15: S 0058a360, S 0058a250, S 0058a0d0). `OptimizeViaMapPath` S 005a4cc0 and the 23- and 1323-tick periods (schedule in S 00582af0) are answered [known]; the found-flag test S 005a9580 accepts an own flag on another walking-net continent (§3.7). [TODO] residue, still [inferred]: "holds the good" of the depot search of `StreetRouteOptimizer` (from the callee name `FindNearestConnectedWithGood`; the search runs on the goods net, kind 0) | static: `FindNearestConnectedWithGood` |
| 6 | Answered (§7): `ResourceMap::Load` takes the single-element branch for `v == 0` and tests the resource id (S 00588b70, disassembly); `AiFightData_Load` drops the extra ints for `v == 0` (S 0059b6c0); the `Player::Load` gates are confirmed from the disassembly; skipped fields keep their constructor values, listed per section | — |
| 7 | Answered (§3.16): no. A map script is only the `<MapInfo name>.lua` sidecar (S 005b1fe0); the 31 `.s2m` files carry no Lua, the 20 free-game maps have no sidecar, and `vi_addGoodsToDepot` occurs only in campaign scripts and `mapTools/spawnDepots.lua` (included only by campaign scripts), never under a player-kind test | — |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 00581a30 | `NAI::System::Tick` | per-tick entry |
| S 00581830 | `NAI::System::CreatePlayers` | allocate 8 players and military maps |
| S 00581c40 | `NAI::System::ActivatePlayer` | start an AI for a slot, feed existing objects |
| S 00581ad0 / S 005821f0 | `NAI::System::Store` / `Load` | save and load |
| S 00581b90 | `NAI::System::StoreBody` | same stream for the lockstep checksum |
| S 005819a0 / S 00581d40 | `NAI::System::PostLoad` / `Reset` | `PostLoad` of every active player, then restart of the path searches; destroy all players and maps |
| S 00675190 / S 00582400 / S 005386e0 | `ai::map::MapPos::Store` / AI grid position `Store` / `NLogic::Unique::Store` | value encodings of the save (§7) |
| S 00592860 / S 00596130 / S 005a0690 | `ConstructionSystem::Load` / `Cell::Load` / `AttackExecution::Load` | the `Load` functions with the most version gates (§7) |
| S 00581960 / S 005830d0 | `NAI::System::RefreshPlayersAndResourceMap` / `NAI::Player::Refresh` | after a script changed the map |
| S 00583180 / S 00584320 / S 00582e10 | `NAI::Player::Store` / `Load` / `PostLoad` | player save state, version gates |
| S 007c3250 .. S 007c6120 | static initialisers of the AI section objects | section names and versions (§7) |
| S 00582870 / S 005839a0 | `NAI::Player::Activate` / `Deactivate` | lifecycle |
| S 00582af0 | `NAI::Player::Update` | the per-player schedule (§4) |
| S 00584030 / S 005836d0 | `NAI::Player::OnBuildingAdded` / `OnBuildingRemoved` | building mirror; headquarters loss |
| S 00596ba0 / S 00596d70 | `NAI::Building::Init` / `NAI::Building` helper | productions and needs of a new mirror (§2.3, §3.3) |
| S 005841e0 | `NAI::Player::AddNeed` | create a need for a good |
| S 0058aac0 | `NAI::CellSystem::Update` | cell sub-steps |
| S 0059df90 / S 0059de60 / S 0059d950 | `NAI::CellValidator::Update` / position step / perimeter search | create / remove cells; last map row and column untested (§3.2) |
| S 005a7dc0 / S 00596000 | `IsInterior` / `NAI_CellPosition_AnyCornerHasGridValue` | validator neighbour and corner tests |
| S 00594b20 | `NAI::Cell::UpdateThreatTrigger` | when a cell asks for a military building |
| S 0059e1c0 / S 0059e4c0 / S 0059d500 | `CellExpansion` / `CellDepotCreation` / `CellClearing::Update` | per-cell requests |
| S 0058d370 | `NAI::NeedCreation::Update` | build order stages |
| S 00594650 / S 00593ea0 / S 005943c0 | `NeedsArrangement::Update` / `TryPlaceNeed` / `InstantiateGroupNeed` | which cell |
| S 00593aa0 / S 00593b50 / S 00593c20 / S 00593cd0 | inputs check / queue missing input / `minDistanceToSupplier` / `minDistanceToConsumer` | placement terms (§3.4) |
| S 007767c0 / S 00776690 | `PropertyGroupIter` | members of a group good (§3.4) |
| S 00593190 | `NeedsConstruction::SelectConstruction` | what to build next |
| S 00593070 / S 00592b30 / S 00592b10 | `NeedsConstruction` request / `OnOrderFinished` / `OnPlaced` | order owner 2 (§3.5) |
| S 00592df0 / S 00592fa0 / S 005936e0 / S 00592c40 | `CanStaffProducer` / `NeedsConstruction` helper / `RebuildTypeMaps` / `FindProducerBuilding` | producer choice (§3.5) |
| S 00592210 / S 00592070 | `ConstructionSystem::Tick` / `ConsiderNeedRequest` | order arbitration and back-off |
| S 005a1ac0 | `BuildingConstruction::Update` | order state machine |
| S 005a17e0 / S 005a1650 | `ConstructionOrder::InitAtCell` / `InitAtPos` | order target; other fields untouched |
| S 005a91e0 / S 005a9080 | `SearchConstructionPlace::Update` / `EvaluateCell` | site search |
| S 005a8ee0 / S 005a9010 / S 005a8e40 | flag-surroundings test / candidate cursor steps | site search candidates (§3.6) |
| S 00676a90 | `GetPathStepCount` | path length of the site search |
| S 00534830 | `GameQueryHelper::ScoreSite` | site quality (outside NAI) |
| S 00532640 / S 00532540 / S 005326e0 | `ScoreSupplierProximity` / `ScoreHuntingGrounds` / `ScorePlantableRing` | `ScoreSite` terms |
| S 00557830 | nearest own building of a type (`completedOnly` 0 here) | supplier proximity |
| S 00542890 / S 00542900 | deposit-count flood fill | deposit term |
| S 0052cae0 / S 00539060 | spawn-point search | hunting term: first spawn point in range that gives the product |
| S 005345d0 / S 00533760 / S 00534230 | `ScoreTerritoryGain` / `ScoreSpacingFromOwnStockBuildings` / `ScoreEnemyMilitaryDistance` | `ScoreSite` terms |
| S 00596700 | `NAI::Building::UpdateTypeFlags` | classification of a building mirror |
| S 00597010 | `NAI::Need::ctor_ForType` | need creation; resource-bound bytes |
| S 005a07b0 | `AttackExecution::IsNearAnySlotCell` | 15-cell proximity to slot targets |
| S 0059cf60 | `AiSacrificeState::Refresh` | sacrifice state, rebuilt every update |
| S 005a96b0 / S 005a97d0 | street `PlanPath` / `PlanBetweenFlags` | randomised street path |
| S 00782b60 / S 00782bb0 | `nGame::System::BeginCinematic` / `EndCinematic` | clear / restore `NAI::System.enabled` |
| S 005a3ed0 / S 005a34a0 | `StreetConstruction::Update` / `EvaluateStrategy` | streets |
| S 005a9580 / S 005a3050 / S 005a33e4 | found-flag test / `BuildStreetTo` / `StreetConstruction` ctor | target flag (not yet connected), street build, step 7 at start |
| S 005a4b60 / S 005a4cc0 | `FindFlagNear` / `OptimizeViaMapPath` | route optimiser |
| S 005a4550 / S 005a5730 | `StreetOptimizer::Update` / `StreetRouteOptimizer::Update` | street improvement |
| S 005898a0 | `StreetPathAnalyzer::GetStepCost` | street path cost |
| S 00590fd0 | `ExpansionSystem::Update` | expansion arbiter |
| S 00590820 / S 00590400 | `ResourceSystem::UpdateExpansionTarget` / `ScoreLowResCandidate` | expand towards resources |
| S 0059abb0 / S 0059af60 | `MilitaryBuildingCreation::Update` / `OnOrderFinished` | military building planner |
| S 005a8cc0 | `LowResSiteQuery::ScoreCell` | where to put it |
| S 005a8040 / S 005a8310 | `MilitaryBuildingRanking::ComputeSiteRank` / `Build` | which military building |
| S 005a02c0 | `Expedition::UpdateShipRoutes` | expedition ships |
| S 0058bcb0 / S 0058b9e0 | `ProductionControl::Update` / `IsStockBelowLimit` | producers on/off |
| S 0058d130 / S 0058d0c0 | `LockSmith::Update` / production switch of the tool need's building | tools; the free tool |
| S 0058ced0 / S 0058cb70 | `FoodArrangement::Update` / `GoodsArrangement::Update` | distribution |
| S 00557630 / S 00563980 | `Building_SetGoodFlagEnabled` | sets (not toggles) a collection flag |
| S 005a41d0 / S 005a5d00 | `ForesterConstruction::Update` / `ShipConstruction::Update` | foresters, shipyards |
| S 0058de80 / S 0058dae0 | `DestructionSystem::Update` / `CanDemolishBuilding` | demolition |
| S 00585380 | `NAI::MilitarySystem::Update` | military schedule |
| S 00586790 | `NAI::MilitaryMap::UpdateCell` | military map content |
| S 00558890 / S 006737d0 | `FindBuildingAtOrNearest` / `MapModifier::SetBuildingAtCell` | building lookup by object layer 1 (anchor only) |
| S 005327f0 | `GameQueryHelper::SumOwnBuildingWeightAround` | defensive weight of an attack candidate |
| S 00599d60 | `MilitarySettings::Update` | slider tuning |
| S 00597c80 | `MilitaryLimiter::Update` | attack budget |
| S 00599a90 | `AttackSystem::Update` | attack round |
| S 005a8750 / S 005a8550 | `AttackTargetSelection::ChooseNewTarget` / `ReportTargetResult` | target area |
| S 005a0dd0 / S 005a0910 | `AttackExecution::Update` / `ShouldAttackWeakestCandidate` | attack decision |
| S 0059f290 / S 0059f0b0 / S 0059e6c0 | `AiAttack_EstimateStrengthRatio` / `AiStrengthTally_ComputeRatioSquared` / `AiMilitary_ComputeSoldierStrength` | strength estimate |
| S 0059e930 / S 0059ea50 | `AiAttack_ScoreAttackersVsFightHistory` / `AiAttackWatch_ScoreDefenceVsFightHistory` | fraction of soldiers |
| S 0059b2f0 / S 0059b3f0 | `AiAttackWatch_Evaluate` / `AiAttackWatch_InitFromAttack` | retreat, burn building, defence |
| S 0059f370 / S 005982a0 | `AiMilitary_ChooseSoldierKind` / `MilitaryUpgrade::Update` | garrison kind, upgrades |
| S 00599860 / S 00598950 / S 00598640 | `SoldierCreation` / `WeaponProduction` / `CoinProduction::Update` | soldier economy |
| S 00598110 / S 00597ea0 | `Casern::UpdateBestPosition` / `ScorePosition` | barracks placement |
| S 00599220 / S 00598e60 / S 005993c0 | `CatapultConstruction::Update` / `ScoreSite` / `UpdateProductionEnabled` | catapults |
| S 0058a4a0 | sacrifice manager tick | calls S 0059cf60, S 0058a360, S 0058a250, S 00589cd0 |
| S 005a1e30 | `SacrificeSitePlanner::Update` | sacrifice building need |
| S 00555e80 | `AiProperty::ctor` | profile defaults |
| S 0054b4d0 .. S 0054c130 | `LuaProps_ai_*` | profile setters |
| S 005ada40 .. S 005ae100, S 005b2660 | `GameScript_Lua_ai_*` | map script interface |
