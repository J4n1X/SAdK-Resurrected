# Settlement: buildings, construction and production

Reference for the `NVillage` namespace of `sadk_noav.exe` (the RTS settlement of a match; not the 3D lobby
"village"). Addresses are static Ghidra addresses, written `S 00xxxxxx`. Tags: **[known]** = read directly in
the code or data, **[inferred]** = one step of reasoning from what is visible, **[TODO]** = open. Nothing here
was observed in the running game.

Related documents: [../subsystems.md](../subsystems.md) (overview), [../types.md](../types.md) (struct
reference), [../lua-surface.md](../lua-surface.md) (the `properties.*` bindings), [../data-loading.md](../data-loading.md)
(when property scripts run), [../map-format.md](../map-format.md) (cell grid, hex directions),
[../navy-and-military.md](../navy-and-military.md) (attacks, garrisons, harbours, expeditions),
[../NCOMM_GAME_PROTOCOL.md](../NCOMM_GAME_PROTOCOL.md) (command transport). Sibling specifications:
[military.md](military.md) (garrison, fights, catapult), [settlers-jobs.md](settlers-jobs.md) (worker and builder
state machines), [streets-transport.md](streets-transport.md) (ware requests, packages, carriers),
[properties-data.md](properties-data.md) (property records, sacrifice effects), [players-victory.md](players-victory.md)
(player kind and start-resources level), [navy.md](navy.md) (ship-building sites).

---

## 1. Purpose and scope

`NVillage::System` owns every building of every player in a match and the ruins they leave behind.
It is responsible for:

- the building registry and its category indexes (storage, territory, catapult, barracks, sacrifice) [known]
  S 00559940;
- placing a building, preparing the ground, the construction site (material requests, builder, build
  progress), upgrading, aborting and demolishing [known] S 0055a090, S 00568040, S 0055eb50, S 005671a0,
  S 00559db0;
- the production component of a finished building (input stock, input requests, cycle start and end,
  on/off switch) [known] S 005657c0, S 00565f80;
- the building's stock (`Depot`: an input stock, an output stock, the list of ware requests) [known]
  S 0055b340;
- building hit points and their effect on capacity [known] S 0055b8b0;
- the **settler order system** (`NVillage::OrderSystem`): requests for *settlers* (workers, builders,
  carriers, soldiers, specialists) and their matching with a building that can release such a settler [known]
  S 005626c0;
- activating a building's territory and sight source once it is occupied (`TerritoryUpdater`) [known]
  S 005653d0.

It is **not** responsible for:

- transporting wares. A building only *files* ware requests into its `NTransport::NeedGoods` list
  (`Depot+0x44`); matching those with suppliers, carriers and packages belongs to `NTransport` [known]
  S 005654f0 (the call to `NeedGoods::AddRequest`);
- the worker's behaviour (walking, the work animation, picking up products). Workers are `NSettlers::Worker`
  objects driven by `NMovie` actions that *call into* this subsystem (`Production::CanStartProduction`,
  `StartProductionCycle`, `OnProductionFinished`, `Construction::AdvanceWork`) [known] S 0065d480, S 00777460,
  S 0077fb50;
- the territory grid itself, the per-cell construction flags and the placement predicate. They live in
  `ai::map` / `ai::game::GameQuery`; §3.1 summarises the predicate because placement cannot be reimplemented
  without it [known] S 0052fbe0;
- garrisons, fights, soldier training and sacrifices (components `Military`, `Soldiers`, `SoldierTraining`,
  `VillageSacrifice` hang off the building but are military/religion rules; see
  [../navy-and-military.md](../navy-and-military.md)).

---

## 2. Data model

### 2.1 Building type (`ai::properties::BuildingProperty`, 0xf8 bytes)

One record per building type, created by `properties.bp_create("<8 hex digits>")` and filled by `bp_set*`
calls in `data/game/scripts/properties/buildings.lua` (104 types). The id is the 32-bit number of the hex
string. Offsets come from the setter functions (each `S 0054cxxx`/`S 0054dxxx`, see §6) [known].

| off | field | type | meaning |
|---|---|---|---|
| +0x00 | `id` | int | type id, also the key of the property map |
| +0x04 | `name` | string | display/log name, used as the argument of player messages |
| +0x20 | `gfxName` | string | graphics set |
| +0x3c | `size` | int (bit mask) | size and site class, see below; default 1 |
| +0x40 | `spawn` | bool | settlers may be stored in / released from this building |
| +0x44 | `goodId0`, `goodAmount0` | int, int | product slot 0 (`bp_setGoods`); id −1 = none |
| +0x4c | `goodId1`, `goodAmount1` | int, int | product slot 1 (`bp_setSecondGoods`) |
| +0x54 | `depot` | bool | storage building (stores every good and settlers) |
| +0x58 | `frameCost` | vector of {goodId, amount} | materials of the first build phase (`bp_addFrameCost`) |
| +0x68 | `cost` | vector of {goodId, amount} | materials of the second build phase (`bp_addCost`) |
| +0x78 | `workingRadius` | int | search radius in cells for deposits, animals, resources, catapult range; default 4 |
| +0x7c | `workerLimit` | int | number of workers the building wants; default 1 |
| +0x80 | `workingMode` | int enum | see below; default 6 |
| +0x84 | `stockLimit` | int | input stock target per input good; default −1 |
| +0x88 | `constructionTime` | int | default 500; only its sign is tested: `<= 0` = not buildable, completes at once. Readers: S 0055efa0, S 0055cd40, S 00534f40 (economy consumer list), S 00634db0 (build menu buttons), S 00621d20 (UI), and the shared test S 00532960 ("`<= 0` and not a headquarters type", used by the flag removal block reason S 00669f70 and the sacrifice abort checks S 00560ed0, S 00561050); none uses the magnitude [known] |
| +0x8c | `health` | int | maximum hit points; 0 = no hit points |
| +0x90 | `worker` | int | settler good id of the worker type |
| +0x94 | `territoryRange` | int | base territory radius; > 0 makes it a territory source |
| +0x98 | `soldierLimit` | int | garrison capacity |
| +0x9c | `doorOffsetDirection` | map tribe → direction | where the entrance cell lies (§3.2) |
| +0xa8 | `remains` | int | remains property id left after destruction; −1 = none |
| +0xac | `exploreRadius` | int | sight radius revealed when occupied |
| +0xb0 | `catapult` | bool | has the catapult component |
| +0xb4 | `constructionPosition` | map tribe → vector of (x, y) float | 4 builder positions, fine-grid offsets |
| +0xc0 | `idlePosition` | map tribe → vector of (x, y) float | worker idle positions |
| +0xcc | `aiThreat` | int | AI only |
| +0xd0 | `aiScore` | int | AI only; default 20 |
| +0xd4 | `plantingDeposit` | int | deposit type the worker plants; −1 = none |
| +0xd8 | `productionTime` | float | length of one production cycle; default 0. Unit = logic ticks [inferred]: it is the start value of the worker's animation timer, which loses 1.0 per `Animation::Tick` (S 0065f040) |
| +0xdc | `catapultDamage` | int | hit points removed per catapult hit [inferred] |
| +0xe0 | `restTime` | int | worker rest time between cycles (used by the worker, not here) |
| +0xe4 | `arrangementValue` | float | default weight of the type in the player's goods distribution; default −1.0 (owner: [game-commands.md](game-commands.md), economy settings) |
| +0xe8 | `upgrade` | int | type id this building upgrades to; −1 = none |
| +0xec | `producedSettler` | int | produced by the breeding modes: a settler good id for mode 4 (`good_oxen`), an animal id for mode 10 (`animal_sheep`) [known: data]; −1 = none |
| +0xf0 | `ignoreGoodCosts` | bool | the building never requests the inputs of its product |
| +0xf1 | `casern` | bool | barracks (trains and stores soldiers) |
| +0xf2 | `arrangementLocked` | bool | UI |
| +0xf3 | `gfxBreeding` | bool | graphics |
| +0xf4 | `productivity` | bool | default 1; `bp_setNoProductivity` clears it (no productivity statistics) |
| +0xf5 | `territoryBuilding` | bool | military building: has the `Military` state, listed as attack target |

**`size` bits** (constants from `config.lua`) [known]:

| value | name | meaning |
|---|---|---|
| 0 | `SizeInvalid` | used only by the three `construction*` dummy types; "not placeable" is [inferred] from the name: the placement predicate (§3.1) has no test for 0 and would treat it as a four-cell footprint |
| 7 | `SizeSmall` | bits 1+2+4: fits a small, medium or large site |
| 6 | `SizeMedium` | bits 2+4: fits a medium or large site |
| 4 | `SizeLarge` | bit 4: needs a large site |
| 8 | `SizeMine` | mine site |
| 16 | `SizeShip` | ship-building site (shore) |
| 64 | `SizeMilitary` | added to a size: must keep distance from other territory buildings |

A type fits a cell when `(cellFlags & size & 0x3f) != 0`, and if the type has bit 0x40 the cell must have it
too [known] S 0052eab0, S 0052e510.

`bp_addCost` and `bp_addFrameCost` append through `GoodAmountList_AddAmount` (S 00552aa0): a good that is
already in the list gets its amount increased instead of a second entry [known].

**Footprint** [known] S 0055ac80, S 0055ac20: when `size & 0x1b` is non-zero the footprint is the anchor cell
only. Otherwise (sizes 4, 0x44, 0) it is four cells: the anchor, then one step in direction 3 (W), from there
direction 5 (SE), from there direction 0 (E). Directions are those of
[../map-format.md](../map-format.md) §5.1. So only "large" buildings cover four cells.

**`workingMode`** (constants from `buildings.lua`; the code tests the numbers) [known]:

| value | name | what this subsystem does differently |
|---|---|---|
| 0 | Foresting | worker plants `plantingDeposit` |
| 1 | Mining (woodcutter, stone pit) | deposit search (§3.9) |
| 2 | Farming | deposit search (§3.9) |
| 3 | Fishing | – |
| 4 | SettlerBreeding (donkey/ox breeder, barracks) | – |
| 5 | Catapult | – |
| 6 | Producing (default) | production time scaled by a per-player factor; with `size == 8` it is a **mine** (§3.8) |
| 7 | Hunting | animal search (§3.9) |
| 8 | Idling (watchtower) | – |
| 9 | Sacrifice | building has the sacrifice component; indexed in the sacrifice list |
| 10 | AnimalBreeding | cannot start while 20 or more animals are in the area (§3.7); time scaled like mode 6 |
| 11 | Scholar | – |

### 2.2 `NVillage::System` (0xc0 bytes) [known] S 005592c0

| off | field | meaning |
|---|---|---|
| +0x04 | `buildings`: `vector<Building*>`, all buildings | **insertion order**; this is the update and save order |
| +0x14 | `buildingsByUnique`: `map<Unique, Building*>` | lookup by unique id |
| +0x20 / +0x30 | `depotBuildings` / `depotBuildingsByUnique`: vector + map | buildings whose type has `depot` |
| +0x3c / +0x4c | `territoryBuildings` / `territoryBuildingsByUnique`: vector + map | `territoryBuilding` |
| +0x58 / +0x68 | `catapultBuildings` / `catapultBuildingsByUnique`: vector + map | `catapult` |
| +0x74 / +0x84 | `casernBuildings` / `casernBuildingsByUnique`: vector + map | `casern` |
| +0x90 | `remainsByUnique`: `map<Unique, Remains*>` | ruins |
| +0x9c / +0xac | `sacrificeBuildings` / `sacrificeBuildingsByUnique`: vector + map | `workingMode == 9` |
| +0xb8 | `orderSystem`: `OrderSystem*` | settler orders (§2.6) |
| +0xbc | `flagBC`: byte | "initialised": 0 in the constructor S 005592c0 and in `Clear` S 00559020 (called by `NLogic::System::Reset`), 1 in `Init` S 00557610 (called by `NLogic::System::InitSubsystems`); saved and loaded first; never read otherwise [known: §10 Q4]; no behaviour |

Each vector is a 16-byte MSVC `std::vector` member (first / last / end at +4 / +8 / +0xc of the member) and each
map a 12-byte `std::map` member (head node at +4, size at +8) [known] S 005592c0.

A building is in every category list its type flags select (`IndexBuilding` S 00559940, `UnindexBuilding`
S 00558f80) [known].

### 2.3 `NVillage::Building` (0x140 bytes) [known] S 0055d980

| off | field | type | meaning |
|---|---|---|---|
| +0x04 | `gameSystem` | ptr | |
| +0x08 | `ownerPlayer` | ptr | first dword = player index 0..7; +0x44 tribe id; +0x48 tribe property |
| +0x0c | `property` | ptr | the building type; replaced on upgrade |
| +0x10 | `unique` | `NLogic::Unique` | 64-bit id, assigned at placement |
| +0x20 | `posX`, `posY` | int, int | anchor cell |
| +0x28 | `ticker` | `NLogic::Ticker` | period 100, counter starts at 0; `Tick()` returns true when the counter equals the period and resets it, else increments: true on every 101st call (S 00775480); gates the worker request (§3.6) |
| +0x34 | `variantKey` | int | tribe id of the owner at placement; key of the per-tribe maps of the type |
| +0x38 | `reserved38` | int | reserved: the three constructors store 0 (S 0055c93b, S 0055d576, S 0055da15), `Load` reads it from the save (S 0055d33d), the two store functions write it (S 0055c4f6, S 0055c6fe); no other instruction of the program accesses it [known, instruction search for the displacement 0x38]. 0 in a running game unless a loaded save carries another value |
| +0x3c | `depot` | `Depot*` | stock and ware requests (§2.5) |
| +0x40 | `workers` | `Workers*` | up to 10 worker references, `workerCount` at +8 (§3.18) |
| +0x44 | `construction` | `Construction*` | §2.4 |
| +0x48 | `production` | `Production*` | `bEnabled` +8 (init true), `bCycleRunning` +9 |
| +0x4c | `blocking` | `Blocking*` | footprint cursor + size mask; blocks the map cells |
| +0x50 | `depositRef` | reference | linked deposit (modes 1, 2) |
| +0x70 | `animalRef` | reference | linked animal (mode 7) |
| +0x90 | `fieldConnection` | 2 ints | linked map-resource cell of a mine; (−1, −1) = none |
| +0xa0 | `entranceFlagRef` | reference | the road flag in front of the door |
| +0xc0 | `settlerSpawn` | `SettlerSpawn*` | spawn cooldown, wounded-settler values (§3.11) |
| +0xc4 | `territoryUpdater` | `TerritoryUpdater*` | `bActive` at +8 |
| +0xc8 | `bulldozing` | `Bulldozing*` | caches the type being built |
| +0xcc | `orders` | `OrderContainer` | references to this building's open settler orders |
| +0xe0 | `military` | `Military*` | allocated for every building; garrison, fight reference +0x70 (id at +0x84), `cooldownTicks` +0x60, `destroyCountdown` +0x90 (−1 = not running), `unconnectedTicks` +0x94 (starts at 500), three soldier order slots +0x24..+0x2c (S 0055fef0). Layout owner: [military.md](military.md) §2.4 |
| +0xe4 | `goodFlags` | `GoodFlags*` | `map<goodId, enabled>`: goods this building is asked to collect |
| +0xe8 | `initialInputsRequested` | bool | one-shot latch, §3.6 |
| +0xec | `tickCounter` | int | 0..100, deposit/animal search timer |
| +0xf0 | `resourceSearchCounter` | int | 0..100, mine resource search timer |
| +0xf4 | `catapult` | `Catapult*` | allocated for every building; target cell +8/+0xc, aim cell, `targetSeed` ([military.md](military.md) §3.10) |
| +0xf8 | `entranceX`, `entranceY` | int, int | entrance cell, recomputed on load |
| +0x100 | `destroyed` | bool | set while the building is torn down without effects |
| +0x104 | `upgrade` | `Upgrade*` | `bActive` +8, `targetTypeId`, own `Construction` (+0x10) and `Bulldozing` |
| +0x108 | `ordering` | ptr | stock-keeping component of depots and barracks (§3.10) |
| +0x10c | `hitpoints` | `Hitpoints*` | `hitpoints` +8, `maxHitpoints` +0xc, `lastRegenTick` +0x10 |
| +0x110 | `projectileRefs` | references | catapult stones in flight towards this building [inferred] |
| +0x124 | `soldierTraining` | ptr | allocated for every building (0x6c bytes); used by `casern` types |
| +0x128 | `sacrifice`, +0x12c `sacrificeResearchRef` | | allocated for every building (0x38 bytes); updated only for mode 9 |
| +0x138 | `markedOutsideTerritory` | bool | footprint fell outside the owner's territory; removed next tick |

**States.** A building has no state enum. Its state is derived [known] S 0055e2f0, S 0055bf90:

| state | condition |
|---|---|
| under construction | `construction.remainingA > 0` or `construction.remainingB > 0` |
| construction paused | under construction and `construction.aborted` (+0x78) set; no requests and no builder until the continue command clears it (§3.4) |
| finished | both `remaining` values `<= 0` |
| upgrading | finished and `upgrade.bActive`; the *effective* construction is then `upgrade.construction` |
| occupied | finished and `IsOccupied()` (§3.6) |
| doomed | `markedOutsideTerritory` set, or `military.destroyCountdown == 0` |

### 2.4 `NVillage::Construction` (0x80 bytes) [known] S 0055e460, S 0055e720

| off | field | type | meaning |
|---|---|---|---|
| +0x04 | `pBuilding` | ptr | |
| +0x0c | `pBuildingDef` | ptr | type being built: the constructor (S 0055e460) stores the building's current type, `StartWithType(type)` (S 0055efa0) replaces it before requesting materials, so an upgrade's construction holds the target type from `Bulldozing::Begin` on |
| +0x10 | `stock` | `NLogic::Stock` | materials delivered to the site and not yet used |
| +0x30 | `builderRef` | settler reference | the bound builder; invalid = none |
| +0x50 | `shipRef` | reference | for ship-building sites the progress lives in the ship (+0x48/+0x4c) |
| +0x70 | `remainingA` | float | remaining fraction of phase 2 (the `cost` list); starts 1.0 |
| +0x74 | `remainingB` | float | remaining fraction of phase 1 (the `frameCost` list); starts 1.0 |
| +0x78 | `aborted` | bool | site is paused: set by command 0x20029, cleared by 0x2002a (§3.4) |

That B is the frame phase and A the main phase follows from `RequestMaterials`, which pairs list +0x58 with
+0x74 and list +0x68 with +0x70 [known] S 0055eb50 (disassembly 0055ebe2/0055ebe7).

### 2.5 `NVillage::Depot` (0x88 bytes) [known] S 0055b340

| off | field | meaning |
|---|---|---|
| +0x08 | byte | `flag08`: 0 in the constructor S 0055b340, true at placement and transfer (`Generic_SetByte08_True` S 00599cb0 from S 0055d980 / S 0055d4e0, not in the load constructor), saved S 0055ad30, loaded S 0055ada0 (true for old saves); never read otherwise [known: §10 Q4]; no behaviour |
| +0x0c | `stockA` (`NLogic::Stock`) | **input stock**: wares delivered for production |
| +0x28 | `stockB` (`NLogic::Stock`) | **output / store stock**: products, stored wares, stored settlers (as goods) |
| +0x44 | `needGoods` (`NTransport::NeedGoods`) | open ware requests, one entry per requested unit |
| +0x5c | `returningGoods` | references to packages on their way back to this building |
| +0x74 | `settlerRefs` | settlers linked to the building (detached on teardown) |

`Depot::dtor` S 0055af70 works in this order: reset both stocks, the settler references, `ReturningGoodSystem::dtor`
(the returning packages are released and look for a new target, [streets-transport.md](streets-transport.md)),
`NeedGoods::dtor` [known].

Where a delivered ware lands is decided by `Depot::CollectGoods` (§3.19).

A `Stock` is an ordered `map<goodId, count>` plus a running total of units (`totalUnits`, `Stock+0x14`; layout
and operations in [logic-core.md](logic-core.md) §2.5, §3.4). Iteration is in ascending good id compared as a
**signed** 32-bit int: `Stock::GetCount` S 005399b0 looks up through the tree find S 00546c70, which compares the
keys with signed jumps (`JGE` / `JL`), so a good whose hash id has the top bit set (`plank` 0xc5c945a3) comes before
`stone`-type ids below 0x80000000 [known]. The good-flag map (§2.7) is ordered the same way (find S 00562dd0)
[known]. `totalUnits` changes only through the unit operations (`AddOne`, `RemoveOne`, …);
`Depot::ClampStockToLimit` (§3.7) writes the counts without it.

### 2.6 Settler orders

`NVillage::Order` (0x160 bytes, derives from `NLogic::Need`) [known] S 00568b80:

| off | field | meaning |
|---|---|---|
| +0x08 | building reference | requesting building |
| +0x28 | ship reference | requesting ship / expedition |
| +0x48 | `goodId` | settler good wanted (a good whose type is Settler) |
| +0x4c | `tick` | logic tick at which the order was created (field of the `NLogic::Need` base, `Need::Init` S 007756f0); lower = older |
| +0x50 | `unique` | id of the order |
| +0x60 | flag reference | requesting flag (specialists) |
| +0x80 | street reference | requesting street (carriers) |
| +0xa0 | 3 soldier slots × 0x40 | each: military building reference + soldier reference (slots 0..2) |

Exactly one target is linked; `OrderLink_Link*` adds the order to the target's `OrderContainer` and to the
index [known] S 0053cbe0. The constructor `Order::ctor` S 00568b80 draws the order's unique id from the global
counter (§8) [known].

`ai::village::OrderIndex` (`OrderSystem+0x18`): 8 player blocks; each block has 7 **category** buckets; each
bucket is a vector of entries `{goodId, category, vector<Order*>}` in order of first use [known] S 0055fa90,
S 00568620.

**Order category** (`VillageOrder_GetCategory` S 005686a0) [known], tested in this order:

| category | condition |
|---|---|
| 4 | soldier slot 1 linked |
| 1 | soldier slot 0 linked (such an order is also registered under category 2) |
| 5 | soldier slot 2 linked |
| 3 | building linked, building finished, and (type is `depot`, or type is `casern` and the good is a soldier) |
| 0 | building linked otherwise (worker, builder; any unfinished building) |
| 6 | ship linked |
| 0 | everything else (street, flag) |

`ai::village::OrderIterator` (`OrderSystem+0x3e0`): cursor `player`, `category`, `entryIndex`, a list of
**nodes** of the current entry, `selectedOrder` [known] S 00569840. A node is the target flag of an order;
a flag is added to the list only when no flag already in it has the same 64-bit id in entry 0 of the flag's id
array (flag +0x48/+0x4c; `OrderIterator::AddUniqueNode` S 005695b0, compare S 00663d90) [known]. The array is
the flag's `netContinent[2]`: entry 0 is the id of its connected component in the **goods** net (net kind 0:
streets that have a carrier, and sea streets), entry 1 (+0x58/+0x5c) the one in the **walking** net (net kind 1:
every street) ([streets-transport.md](streets-transport.md) §2.2 and its net-kind table). So the list holds
one flag per connected goods network, not one per flag.

Order life cycle [known]:

- **Create** (`OrderSystem::CreateOrder` S 00562940): allocate, construct with the good id, append to the
  order vector (`OrderSystem+0xc`, creation order). The caller then links exactly one target, which also
  registers the order in the index. Callers: building worker request (S 0055ccd0), building orders for a good
  (S 0055c170: builder request, stock keeping, garrison allocation S 00574a00), military order slots
  (S 00568970), expeditions (S 005b8470), streets (S 00668e10).
- **Remove** (`OrderSystem::RemoveOrder(unique)` S 00562140): destroy and erase from the vector. The order's
  destructor (S 00568c40) unlinks it from its one target, tested in this order: building, flag, street, ship,
  else every linked soldier slot; the unlink also takes it out of the target's `OrderContainer` and the index.
- **Target dies**: a building's destructor cancels every order in its container
  (`OrderContainer::CancelAllOrders` S 0055bc10, last to first), so no order outlives its building.
  `Construction::ReleaseBuilder` cancels the orders for the constructor good (`CancelOrdersForGood`
  S 0055bcd0); a military order slot clears its orders the same way (S 005689f0).
- **Served**: the order is deleted when its settler is spawned (§3.12).

### 2.7 Other components

- `NVillage::Remains` (0x48): remains property, building property, unique, position, `burnTicks` (+0x28,
  counts down), a `Blocking` with the dead building's size mask, tribe key (+0x40) [known] S 00564210. The
  constructor (`Remains::ctor` S 00564210) draws the unique id from the global counter (§8) [known].
- `NVillage::GoodFlags`: `map<goodId, bool enabled>`. Before every lookup a good id that appears with a
  positive amount in the cost list of the tribe's **second carrier** good is replaced by that carrier good
  (`TribeProperty+0xb0`, `tp_setSecondCarrierId`, S 0054ad40; test S 00556020) [known] S 00562e40. Data:
  bavarians `good_oxen` (cost `oxen` 1, so the ware `oxen` and the settler good share one flag); egyptians
  `good_helper` (no cost list, nothing is redirected); scots have no `tp_setSecondCarrierId` line.
- `NVillage::Hitpoints`: `hitpoints`, `maxHitpoints` (both start at type `health`), `lastRegenTick` [known]
  S 0055b870.

---

## 3. Rules and algorithms

### 3.1 Where a building may be placed

The command handler calls `GameQuery::CanPlaceBuildingTypeAt(type, cell, player)`, which runs
`CanPlaceBuildingAt` with the type's `size` mask [known] S 00781980, S 005301c0, S 0052fbe0. All of the
following must hold, in this order:

1. The territory grid says the cell belongs to the player [known].
2. If `size & 0x40`: no territory-giving building (`territoryRange > 0`) on the cell or within 4 hex rings
   [known] S 0052dc30. The upgrade check (§3.13), which ignores the centre cell, skips this rule.
3. The **entrance flag cell** (one step in direction 1, NE, from the anchor) is usable: inside the map, has
   the right grid bit (`size == 8`: bit 0x10 set; any other size: bit 0x200 set; `size == 0x10` is also
   accepted when bit 0x10 is clear, whatever bit 0x200 says), and either already holds a layer-0 object that is
   a flag of this player, or holds none and a flag can be placed there [known] S 0052fa00.
4. No cell of the anchor and its 6 neighbours has grid bit 0x1 (blocked) or 0x400 (logic object); cells outside
   the map are skipped, and with `ignoreCentre` (the upgrade check) the anchor is skipped [known].
5. If `size & 1` or `size & 8`: for each of the 6 neighbours that is inside the map and not water (grid bit
   0x4), the slope class (`GetSlopeClassFromHeight` S 00675ec0) relative to the average height
   (`GetAverageHeightInRadius` S 00675f40; radius 2 for `size & 1`, radius 1 for mines) must be within −3..+3
   [known].
6. Mines (`size & 8`): the anchor must be a free owned cell without street carrying grid bit 0x10
   (S 0052f820); nothing else is checked [known]. The ownership test asks the player with `allowBorder` fixed to
   false and the optional second player with the caller's `allowBorder`; `HandlePlaceBuilding` S 00781980 passes no
   `ignoreCentre`, no second player and no border allowance [known].
7. Otherwise every footprint cell must be inside the map, hold no layer-0 object, be a free owned land cell
   (owned, not blocked 0x1, not deposit 0x80, not building footprint 0x100), carry no street (0x2) and carry
   the buildable bit 0x200 (bit 0x20000 when `size == 0x10`) [known] S 0052f460, S 0052f3d0.
8. Large types (bit 4 without bits 1 and 2, S 0052d900; this includes 0x44): every cell of the spiral of radius 2
   (the anchor included, unless `ignoreCentre`) must be inside the map and none of them may hold the anchor of a
   building of a large type (`FindBuildingAtOrNearest` S 00558890 with radius 0). Then the slope class against
   the average height of radius 2 must be within −3..+3 on **hex ring 3**: `HexRing3Iterator` (ctor S 0052db50:
   start at the corner three steps in direction 4; `Next` S 0052db80: one step in direction `d`, three steps
   per direction, `d` = 0..5, false once `d` reaches 6) is advanced once before the loop and tested after each
   further advance (S 0052fff6..00530038), so 17 of the 18 ring cells are tested and the start corner is not.
   A tested ring cell outside the map fails the placement; water is not skipped [known].
9. Types with bit 2 or 4 but not bit 1 (medium and large types; a large type runs rules 8 and 9): the 18 cells
   of radius 1 and 2 around the anchor (the spiral iterator S 0052db20 / S 00600e90, advanced once past the
   anchor) must be inside the map and have a slope class within −3..+3 against the average height of radius 2;
   water is not skipped [known] S 0052fbe0.
10. Ship sites (`size & 0x10`): the cell needs a shore and a free water neighbour [known].

The per-player **construction flags** of a cell are precomputed from the same predicate: probe sizes 4, 2, 1,
8, 16 in that order and store 7, 3, 1, 8 or 16 for the first hit; add 0x20 if a flag can be placed; add 0x40
if bit 1 is set and rule 2 holds [known] S 00675610. A building type locked for the player
(`Player::IsLocked(0, type)`) cannot be placed from the UI [known] S 005576e0; the lockstep handler itself
does not test the lock [known] S 00781980.

### 3.2 Placement (`System::PlaceBuilding` S 0055a090) [known]

Steps 1 to 5 run inside one map-update batch (`MapUpdateBatch_Begin` S 00532180 … `MapUpdateBatch_End`
S 005321c0); there is no "building changed" message:

1. Construct the building (`Building::ctor_Place` S 0055d980), in this order:
   1. create all components (§2.3: ticker period 100, `variantKey` = owner tribe, `reserved38` = 0, both search
      counters 0, entrance (−1, −1)); only then assign a new `Unique` (`Unique::AssignNew`); set `Depot.flag08`;
   2. entrance cell = anchor stepped one cell in `doorOffsetDirection[variantKey]`, or the anchor itself when
      the type has no entry for that tribe (S 0055d1f0). The data has 7 entries, all 4 (§6); 97 of the 104 types
      have none, so their entrance is the anchor for every tribe [known: data]. The stored number is passed unchanged to
      `MapPos::StepDirection` (S 0055cdd0 returns the map value, S 0054d990 stores Lua argument 3 as is)
      [known]. Data values: `DoorOffsetWest` = 3, `DoorOffsetNorthWest` = 4, `DoorOffsetNorthEast` = 5, i.e.
      the step directions that [../map-format.md](../map-format.md) §5.1 labels W, SW and SE. The game's names
      and that table's compass labels disagree about which way y points; the numbers are what counts.
      Direction 4 is the opposite of direction 1 (the flag side) [inferred]. On screen, camera unrotated,
      direction 1 points to the building's bottom side, slightly left (about south-south-west): every entrance
      is centred on the bottom side, and a `farmBav` placed at anchor (62, 88) had its entrance flag at
      (62, 87) [live, 2026-10-14]. Neither the compass labels nor the data names describe screen directions;
   3. block the footprint in the map (`Blocking`: grid bit 0x1 on the anchor, grid bit 0x100 on every footprint
      cell that is inside the map, S 00566e10, S 00673cf0, S 00673da0);
   4. `Bulldozing::Begin(type)` (§3.3), which levels the ground and ends with `Construction::StartWithType`
      (§3.4): the material requests, or at once a finished building when `constructionTime <= 0`;
   5. if the game is in **batch editing** mode (the query is vtable +4 of `NLogic::Edit`, `NLogic::System+0x38`):
      `TerritoryUpdater::Activate` S 00565350 first, then `Construction::Complete`; the construction is already
      complete by then, because `StartWithType` S 0055efa0 completed it in step 4 (it does not request materials
      while batch editing), so the "completed" notification and `Military::SelectInitialSoldierKind` fire inside
      `Bulldozing` [known]. Then: `workerLimit > 0` → spawn the
      worker inside; else if `territoryBuilding`: `depot` → fill the initial stock (`Depot::AddInitialStock`
      S 0055b020: the map's initial goods for the tribe, plus the tribe's `tp_addBonusResources` list,
      `TribeProperty+0x90`, when `ai::player::Player::IsStateDefault(owner)`; the table of who qualifies is in
      [players-victory.md](players-victory.md) §3.4), not `depot` → spawn one soldier of kind 0;
      otherwise (normal play) only `TerritoryUpdater::ActivateIfOccupied`, which does not test the construction
      state: a site of a type with neither soldiers nor workers activates its source at placement [known,
      S 005653d0]. The territory updater runs before the anchor is marked in layer 1 (step 7) and before the
      building joins the village vector (step 2 below), so the building's own `OnTerritoryChangedAt` does not see
      it [known, S 0055d980]. The start castle of a match is
      placed by `Game_CreatePlayersFromDescriptor` S 005abb60 without a placement check and takes the normal
      branch: its `constructionTime` of −1 has completed it in step 4 already, and its initial stock comes from
      that caller, the only other caller of `Depot::AddInitialStock` [known: callers of S 0055b020];
   6. types with `territoryBuilding && depot` (the headquarters): switch off both soldier-training slots and
      the training upgrade (`SetSlotEnabled(0..1, false)`, `SetUpgradeEnabled(false)`);
   7. mark the building on its map cell (`MapModifier::SetBuildingAtCell`, layer 1), raise "building added"
      (callback slot +0x08) and tell the AI players (`AIPlayers_NotifyBuildingAdded`; the destructor calls the
      matching "removed" hook, [ai-player.md](ai-player.md)). By this order, the first soldier spawned in step 5
      raises its "entity added" and "garrison changed" notifications before the building's "building added"
      [known].
2. Insert into the unique map and append to the building vector.
3. Attach the entrance flag (`Building_AttachEntranceFlag` S 00557660): the player's flag at anchor +
   direction 1 if there is one, else a new flag placed there by `Logic_PlaceFlag` (flag id, its two
   net-continent ids, `FlattenAroundCell` over vertex ring 1, callback +0x18; a street passing the cell is
   split, [streets-transport.md](streets-transport.md) §3.1). No street is built. The flag is always at
   direction 1, independent of `doorOffsetDirection`.
4. For every footprint cell, the doodads it obstructs are queued for removal at the batch end
   (`MapUpdateBatch::RemoveObstructedDoodadsAtCell` S 00532280); then the construction flags within hex radius 4
   of the anchor are invalidated once (`MapUpdateBatch::InvalidateConstructionAroundCell2` S 005323b0, which
   ignores its first argument; the same call ends `RemoveBuilding`, `TransferBuildingOwnership`,
   `Upgrade::Start` and the creation and removal of remains).
5. Close the batch: obstructed doodads removed, construction flags recomputed for the dirty area, one elevation
   change for the levelled area ([map-resources.md](map-resources.md) §3.4, §3.5).
6. If the type has `productivity` and (a `plantingDeposit` or a product in slot 0):
   `Statistics::ResetBuildingProductivity` S 00538440 sets the building's productivity entry to 0.5 (creating
   it) [known].
7. Add to the category indexes.
8. Remove every animal standing on a footprint cell (`NResources::System::RemoveAllAnimalsAt` S 0053f840).

**Unique ids drawn by one placement**, in this order [known]: the building (step 1.1); an AI cell when the owner
is an active computer player without a cell at that coarse position (`NAI::Player::OnBuildingAdded` S 00584030 →
`CellSystem::AddCell` S 0058b2b0; `NAI::Building::Init` S 00596ba0 may also create needs for producing or
consuming types, [ai-player.md](ai-player.md)); a new entrance flag; its two net continents. The ware requests
of step 1.4 draw none (`NeedGoods::AddRequest` S 0064eb80, `NeedSystem::CreateNeed` S 00652420, the need and
element constructors and `Need::Init` S 007756f0 call no `AssignNew`) [known].

### 3.3 Ground preparation (`Bulldozing`) [known] S 00568040, S 00567f70, S 00567e90

- "Level" (`IsGroundLevel` S 00567e90): the height of the anchor's sample vertex (vertex
  `(4x + (y odd ? 2 : 0), 4y)`) equals the heights of the sample vertices of the six neighbour cells, visited
  from the neighbour in direction 4 and then stepping in directions 0..5, i.e. the neighbours in directions 4, 5,
  0, 1, 2, 3.
- `Begin` (S 00568040): store the type being built; if not level, `MapModifier::LevelCellToAverageHeight(anchor,
  2)` S 006744f0: every vertex of the vertex spiral of radius 2 around the anchor's sample vertex gets the
  truncating mean of `max(height, minHeight)` over the cell spiral of radius 2, then vertex ring 3 is smoothed in
  ring order, each vertex to the truncating mean of its six neighbours, seeing the vertices already smoothed
  ([map-resources.md](map-resources.md) §3.4).
- Then (S 00567f70, inside a map-update batch of its own) only for `size == 4` and if still not level: each
  neighbour cell, in the order above, is levelled to the anchor's height (`LevelCellToCellHeight` S 00674560,
  the same vertex-disk levelling with the anchor's sample height). The test is for the exact value 4, so a large
  military type (0x44, the fortresses) is not included.
- Then `Construction::StartWithType(type)` on the effective construction (`Building::GetConstruction`
  S 0055bf90: the upgrade's while an upgrade is active, §3.13).

Each levelling invalidates the construction flags around its cell; water, shore and cliff bits are not refreshed;
the elevation change is raised once, when the outermost batch closes, with the dirty rectangle inflated by 16
vertices ([map-resources.md](map-resources.md) §3.3, §3.4) [known].

Levelling is instantaneous at placement: the builder goes straight to building and the ground is level at once;
there is no levelling phase [live, 2026-10-14]. `cfg_setBulldozeTime` (55, `GameConfig+0x14`) is never read
[known]: the property database is reached only through `NProperties::StaticAccess::EnsureInstance` S 0054a140
(the only reader of its global besides the destroy function); in the decompiled bodies of its 593 callers
`gameConfig` is used only for direct field reads of other fields and by the `cfg_*` setters, never stored or
passed on, and no slot of the `StaticAccess` vtable (S 007e8030) reads `PropertiesDb+0x24`. The setter
S 0054c470 is the only access to `+0x14`.

### 3.4 Construction

**Start** (`StartWithType` S 0055efa0) [known]: if `constructionTime > 0` and the game is not batch editing →
`RequestMaterials`; otherwise `Complete` at once (headquarters, Olympic flame: `constructionTime = -1`). There
is no ship-site case: a ship-building site placed while batch editing is completed like any other building, no
constructor is ordered and no ship is made ([navy.md](navy.md) §3.2) [known] S 0055efa0, S 0055d980.

**Material requests** (`RequestMaterials` S 0055eb50) [known]. For list 0 (`frameCost`, phase fraction
`1 − remainingB`) and then list 1 (`cost`, `1 − remainingA`):

```
skip = trunc( phaseDone / (1 / totalUnits(list)) )        // units already built in
for each entry of the list, in order; for each unit of the entry:
    if skip > 0:            skip -= 1
    elif a copy of the site stock still has the good:  take one from the copy
    else:                   depot.needGoods.AddRequest(good)   // one request per unit
```

So a new site requests every unit of both lists at once. The requests are served by `NTransport`; delivered
units land in `construction.stock` (§3.19) [known]. For a ship-building site (`shipRef` valid) the two
fractions are read from the ship instead: `1 − ship+0x4c` for list 0, `1 − ship+0x48` for list 1 [known:
disassembly 0055ebf1..0055ec18].

**Builder request** (each tick while under construction, S 0055ea90, S 0055e970) [known]: if work remains,
no builder is bound, the site is not aborted, and the building has no open order for the tribe's constructor
good (tribe property +0xc0, `tp_setConstructor`) → create one settler order for that good linked to the
building (§3.12).

The builder first walks to the site with `NMovie::GoToConstructionPlace` (ctor S 0077dcb0, `Start` S 0077dd70,
`Update` S 0077dd80), a movie package whose only step, 2, is `MoveToWorkingPlace` [known].

**The builder's work** (actions `NMovie::ConstructBuilding` S 0077daf0 and `NMovie::Construct` S 0077fb50,
S 0077fe70) [known]:

1. Decide (state 7): stop if the site is aborted. If the frame phase is done (`1 − remainingB >= 1`): work when
   the site stock is not empty (its map holds at least one entry: the node count at `Construction+0x20` =
   `stock+0x10` is not 0). Otherwise: work when the site stock holds the **first** `frameCost` good.
   Else play "be nervous" (idle) and decide again. This test reads the `frameCost` list of the building's
   **current** type (`Building+0x0c`), while step 2 reads the lists of the site's type (`pBuildingDef`); they
   differ only during an upgrade.
2. `Construct::Start`: `total` = total units of `cost` if the frame phase is done, else of `frameCost`.
   `workPerStroke = (1 / total) / (constructTime × 4)` with `constructTime` = `cfg_setConstructTime` (30).
   Consume one unit from the site stock: in the frame phase the first `frameCost` good; in the main phase the
   first good of `cost` (list order) that the stock holds.
3. `Construct::Update`, 4 positions `i = 0..3`: walk to fine position
   `(anchorNE.x × 4 + (anchorNE.y odd ? 2 : 0) + trunc(cx_i), anchorNE.y × 4 + trunc(cy_i))` where `anchorNE`
   is the anchor stepped in direction 1 and `(cx_i, cy_i)` = `constructionPosition[variantKey][i]` of the
   building's **current** type (`Building+0x0c`), so during an upgrade the builder works at the positions of
   the type being upgraded, not of the target [known: S 0077fb50]; then `strokes = trunc(constructTime)` = 30.
4. While strokes remain, on every update in which the builder is not walking: (re)start the hammer animation
   (kind 4, duration `constructTime`) when it has ended, `strokes -= 1`, `AdvanceWork(workPerStroke)`; if both
   remaining values are `<= 0`, strokes = 0. The positions not yet visited are still walked afterwards, each
   with one stroke that changes nothing [known] S 0077fb50.
5. After the fourth position, once the hammer animation has ended: one more `AdvanceWork(workPerStroke)`; if
   nothing remains (`IsUnderConstruction` S 00526ed0 false: both values `<= 0`) → `Construction::Complete` and
   clear the site stock. The `Construct` action ends. If both
   phases are now done, `ConstructBuilding` posts the player message `!Building constructed` (category 7, name
   of the site's type `pBuildingDef`, position) and ends; otherwise the decision of step 1 runs again.

One unit of material therefore yields 4 × 30 + 1 = 121 strokes of `1/(total × 120)` each, slightly more than
`1/total`; the last unit of a phase overshoots and is clamped to 0 [inferred from the constants above].
`workPerStroke` is fixed in `Construct::Start` for the whole unit, and `AdvanceWork` switches to `remainingA`
as soon as `remainingB` is 0, so the strokes of the last frame unit that are left after the clamp are taken
from the main phase at the frame phase's rate [inferred].

**`AdvanceWork(amount)`** S 0055eff0 [known]: if `remainingB > 0`: subtract, clamp at 0. Else if
`remainingA > 0`: subtract; when it drops below 0 set 0 and call `OnBuildWorkDone` (S 0055eec0: raise
"building completed" to the observers; for a `territoryBuilding` whose territory is not active yet, set
`military.soldierKind` (+0x68) to 1 when `Player_CountStockedSoldiersOfClass(owner, 0)` (S 005324d0) is 0,
else to 0: `Military::SelectInitialSoldierKind` S 0055fce0, the same call `Complete` makes). Both tests are strict: a value that lands exactly on 0 does not call `OnBuildWorkDone`. In float32
stepping no main-phase total from 1 to 12 lands exactly on 0.0, so for such totals that branch never fires and
completion comes with the drop below 0 [inferred: float32 arithmetic of the constants above, §8].

**`Complete`** S 0055ef00 [known]: clear all ware requests of the building's depot (`NeedGoods::ClearAll`; for
an upgrade this is the same list as the building's own production requests); zero both remaining values (for a
ship site: in the ship); if a remaining value was still above 0 on entry, raise "building completed" and select
the soldier kind as in `OnBuildWorkDone`. The builder calls `Complete` only after `IsUnderConstruction` has
turned false (step 5), so its call never raises the event: the event comes from `AdvanceWork` alone, and a site
whose `remainingA` lands exactly on 0.0 raises it never and keeps the constructor's soldier kind 0. The event
goes to the `ObserverList` at `NLogic::CallbackManager+0x04` (`listA` of [logic-core.md](logic-core.md) §2.6);
none of the in-match `ObserverList::Subscribe` S 00458860 calls (`NLogic::System::InitSubsystems` S 00527f70,
`nGame::System::BuildScene` S 007842e0, `nMenu::Game::SetupHud` S 005ed700, `Messages::InitAndAttachToParent`
S 005f8fa0) names that list [known]; the other callers of `Subscribe` are front-end, lobby and panel widgets
[inferred: their names], so the notification has no effect and the soldier-kind selection beside it is the only
thing that differs. Immediate completion (`StartWithType` with `constructionTime <= 0`, the editor, a
transfer) calls `Complete` on a full site and does notify; the soldier kind is then selected only when the
territory source is not yet active.

**Pause** (command 0x20029, `GE_Construction_Pause` → S 00782fc0 → `AbortAndReturnGoods` S 0055ed30) [known],
allowed only while the effective construction has work left and is not yet paused: clear ware requests;
release the builder (unlink the bound builder, or cancel the open builder order); for each good of the site stock in ascending id, put its units as
packages on the entrance flag until the flag's stack for that good is full (remaining units stay in the site
stock); set `aborted`. Progress (`remainingA/B`) is kept.

**Continue** (command 0x2002a, `GE_Construction_Continue` → S 00782840 → S 0055eeb0) [known]: only when the
effective construction has `aborted` set: `RequestMaterials()` (requests every unit not yet built in and not in
the site stock), then `aborted = false`; the builder request of the next tick brings a builder back. A paused
site that is never continued stays until it is removed through one of the general paths of §3.5 [known]: the
flag `+0x78` is used by S 0055e460, S 0055e720, S 0055e7a0, S 0055ea90, S 0055eeb0, S 0055ed30, S 00567320,
the builder movies S 0077daf0 / S 0077d6c0 and the overlay S 006403c0, and none of them removes the site.

**Ship-building sites** (`size == 0x10`): progress lives in the ship, each builder visit consumes one unit, and
the site is removed when the ship is finished or no launch cell is found (`RemoveBuilding` from S 0065e770
[known as call]); the type's `workingRadius` is the launch-cell search radius. Owner: [navy.md](navy.md).

### 3.5 Demolition and removal

**Player demolish** (command 0x20003 → `HandleDestroyBuilding` S 00781150 → `System::DestroyBuilding`
S 0055a7a0) [known]: ignored when a destroy countdown is already running (`destroyCountdown >= 0`). If the
building is the target of a fight (`military` fight reference valid): set
`destroyCountdown = mi_setActionsInFightDelayTime` (300 ticks). Otherwise `RemoveBuilding(spill = true)`.
No other code starts the countdown: its writers are the constructor (−1), `StartDestroyCountdown` S 0055fc10,
the decrement below and `Military::Load` S 005604d0 [known].

**Countdown** (`Military::Update` S 005609b0, step 7 of §3.6, so only for finished, unmarked buildings)
[known]: headquarters types skip it. Otherwise, when `destroyCountdown > 0` it is decremented by 1 per tick
unless the game-wide flag `GameSystem+0xec` is set; when it is already 0 on entry, `NotifyDestruction`
(S 00560890) posts `!Military Building Destruction executed` to the owner and, if a fight is attached,
`!Attack Target has been destructed` to the fight's player (both category 1). `System::Update` tests the
countdown right after `Building::Update` in the same loop iteration (§4), so a countdown that steps from 1 to
0 removes the building in that tick, before `Military::Update` can see the 0: after a normal 300-tick
countdown the two messages are not posted [known] (`NotifyDestruction` has this one caller, S 005609b0; S 0055a640).
They are posted only when the countdown starts at 0 (`mi_setActionsInFightDelayTime(0)`), in the tick of the
removal. A headquarters type skips the block, so a countdown started on one never runs down. The constructor value is −1
(S 0055fef0). The countdown is started by `Military::StartDestroyCountdown` (S 0055fc10), whose only other
caller is the AI's attack watch (S 0059b2f0: not while one is running, not for a headquarters type, and only
when a random draw `% 100` is below a value of the AI property; [ai-player.md](ai-player.md)) [known]. The rest
of `Military::Update` (soldier exchange, promotion, the `!Building is not connected` message every 600 counted
ticks) is in [military.md](military.md) §3.3.

Observed [live, 2026-10-12]: demolishing a guard house away from enemy territory removed it at once, with no
message and no call of `StartDestroyCountdown` or `NotifyDestruction`; over 70,000 ticks of a developed save
`StartDestroyCountdown` ran twice (the AI) and `NotifyDestruction` never. A military building demolished while
under attack takes about 30 s at speed 1 to go (maintainer, from play), the 300 ticks above. The countdown length
and the removal tick were not captured by a hook.

The UI offers the action only when `GetDestroyBlockReason()` is 0 [known] S 0055cd40: 1 = headquarters type
(`depot && casern && territoryBuilding`); 3 = `constructionTime < 1` and not a headquarters type; 2 = in a
fight with the countdown already running; 0 = allowed. The command executor tests none of these except the
running countdown, so reasons 1 and 3 are enforced only by the sender's UI [known] S 00781150.

**Automatic removal** in `System::Update` [known] S 0055a640: a building with `destroyCountdown == 0` or
`markedOutsideTerritory` is removed with `spill = true`. `markedOutsideTerritory` is set by the map when
territory changes near a building and any footprint cell is no longer owned by its player (S 00558170,
S 0055c0b0). **Hit points** below 1 remove the building at once from within `Hitpoints::OnChanged`
(S 0055b8b0).

Other callers of `RemoveBuilding` [known: call edges of S 00559db0]: `NNet::System::RemoveFlag` (S 00665c10,
`spill = true`: removing a flag removes the building whose entrance it is; the road net removes flags whose
cell is no longer the owner's territory, [streets-transport.md](streets-transport.md)); the capture of a
building by a soldier (S 00571af0); command 0x2002b "player left" (S 00782910: the player's first headquarters
type building, `spill = true`); the ship-building job (S 0065e770); the AI's demolition (S 0058dc60,
`spill = true`); `TransferAllBuildingsOfPlayer` (§3.16, `spill = false`); Lua `vi_destroyBuilding` /
`vi_destroyBuildingsInArea`; the editor (S 00538bb0) and the debug tool (S 00604dd0).

**`RemoveBuilding(unique, spill)`** S 00559db0 [known]:

1. In batch editing mode: `spill = false`, `destroyed = true`.
2. Clear the selection if it shows this building.
3. `leaveRemains` = building finished and type has `remains`.
4. If finished with remains and the type is `depot` or `casern`: when `spill` is false skip step 5;
   otherwise release every stored settler (`SettlerSpawn::ReleaseAllStockedSettlers` S 00564f40: first
   `FillDefaultSettlers`, §3.11, then spawn one settler per unit of every settler good at the entrance).
5. If `spill`, and (type has `remains` or it is a ship site), and the type is not a headquarters type: spill
   goods (below).
6. Remove from indexes, map and vector; destroy the object (its components cancel orders, requests and links). The
   spill of step 5 therefore happens before the destructor. `Building::dtor` S 0055ce70 runs in this order [known]:
   raise "building removed"; set the outside-territory mark; `DetachAllSettlers`; when the sacrifice research
   reference (`Building+0x12c`) is valid, unlink the research (`Building_UnlinkSacrificeResearch`); unlink the
   deposit or animal (an animal is erased); unlink the entrance flag; clear the map mark and the blocking; cancel
   the orders; unlink the projectiles flying at the building (`MilitaryLink_UnlinkProjectileFromTargetBuilding`
   S 0053ce30); notify the AI; destroy the components in the order depot, construction, workers, production, settler
   spawn, territory updater, bulldozing, military, good flags, catapult, upgrade, ordering, hit points, soldier
   training and, last, the sacrifice component. The catapult component's destructor S 005676d0 unlinks the
   catapult's own projectile (S 0053cdd0). Both unlinks turn the projectile into a position projectile at the
   building's anchor and keep its player index (`ProjectileOwner::ClearBuilding` S 005704c0,
   [military.md](military.md) §3.10 step 6).
7. If `leaveRemains && spill`: create `Remains` at the position (blocks the same footprint; burn time from
   the remains property; its tribe key is the building's `variantKey`).
8. Remove the flag at anchor + direction 1 when all three hold: `Flag::GetRemoveBlockReason()` is 0
   (S 00669f70; with the building gone only its reason 1 can still apply: the flag's harbour reference,
   flag +0x168, is valid and the cell is the owner's territory), all its package stacks are empty (flag +0x74),
   and the vector at flag +0x64 is empty (the flag's street links, [streets-transport.md](streets-transport.md)
   §2.2 [inferred]) [known].

**Spilled goods** (`Village_SpillBuildingGoodsOnRemoval` S 005594e0) [known], only when the entrance flag
reference is valid:

1. Refund of built-in materials (`Construction::CollectReturnedGoods` S 0055e510), always computed from the
   building's own construction (`Building+0x44`), not the upgrade's: the first `frameCost` good
   with `trunc(amount × (1 − remainingB) + 0.5)` units; then
   `left = trunc(totalCostUnits × (1 − remainingA) + 0.5)` units distributed over the `cost` entries in order
   (`min(left, entry.amount)` each, `left -= entry.amount`, stop when `left <= 0`). For a finished building
   both fractions are 1, i.e. the full cost. The fractions are stored as float32 before the multiplication;
   0.5 is the double at S 007d4a90 [known: disassembly 0055e54e..0055e679]. A type whose `frameCost` list is
   empty refunds nothing, not even its `cost` list; only the **first** `frameCost` entry is refunded; for a
   ship site the fractions come from the ship (+0x4c / +0x48) [known].
2. Each refunded good that belongs to the owner tribe's goods list (tribe property +0x20, `tp_addGood`) is
   halved, rounded up: `(n + 1) / 2`. Any other good is set to 0.
3. If still under construction (effective construction): add the whole unused site stock.
4. Add every plain ware (good type 0) of the output stock, then of the input stock, in full.
5. `NTransport::System::SpillGoodsOntoFlag` (S 0064d9d0): passes over the goods in ascending id, one package
   per good per pass, until every count is 0. The whole spill stops at the first good for which the flag's
   package stack is full; everything not yet placed, of any good, is lost.

### 3.6 Per-tick logic of a finished building (`Building::Update` S 0055e2f0) [known]

Under construction (the building's own construction, not the upgrade's) only the builder request of §3.4 runs
(`Construction::Update` S 0055ea90); the ticker and the search counters do not advance. For a finished
building, in this order:

1. `Upgrade::Update` (§3.13).
2. `TerritoryUpdater::ActivateIfOccupied` (§3.14).
3. If `initialInputsRequested` is false, `workerLimit > 0` and the building is occupied: if production is
   enabled (`Production::IsEnabled`, §3.7) `Production::RequestAllInputs()`; set the latch.
4. **Worker request**: when the ticker fires (every 101st call, §2.3), `workers.workerCount != workerLimit` and the
   building has **no** open settler order at all: create an order for the `worker` good linked to the building
   (S 0055ccd0).
5. Deposit search, animal search (§3.9).
6. Mines only (`size == 8 && workingMode == 6`): resource search (§3.9).
7. `SettlerSpawn::Update` (§3.11) and `Military::Update`.
8. `depot` or `casern` types: the ordering component (§3.10).
9. `workingMode == 9`: the sacrifice component.
10. `Hitpoints::Update` (§3.15).

**Occupied** (`IsOccupied` S 0055c400) [known]: if `soldierLimit != 0`, a non-empty garrison vector with
`Soldiers::CountPresentSoldiers > 0` or an already active territory updater is required; then, if `workerLimit == 0` the answer is true; otherwise it
needs `workerCount > 0` and at least one worker slot whose settler answers false to its virtual test at
vtable +0x24 (S 0055b4d0). For `Worker` and `Constructor` that test is "state (+0x54) is 0, 1, 3 or 4"
(S 0065c7b0), so a worker counts as present in every other state [known: the slot +0x24 of the `Worker`
vftable S 007f84dc (at S 007f8500) and of the `Constructor` vftable S 007f8594 (at S 007f85b8) both hold
S 0065c7b0]. The four states are: 0 leaving the building it was
created in, 1 ready with nothing started, 3 going home without a job, 4 walking to the workplace
([settlers-jobs.md](settlers-jobs.md) §2.4). A worker spawned inside by `Workers::SpawnWorker` starts in a
work state and counts at once (§3.18).

### 3.7 Production cycle

The recipe is **not** on the building. The inputs of a building are the `gp_addCost` list of the good in
product slot 0 (`GoodProperty+4`, entries {goodId, amount}) [known] S 005657c0. Example from `Goods.lua`:
`bread` costs `flour` 1 and `corn` 1; the bakery has `bp_setGoods(bakery, bread, 1)`.

Good types (`gp_setType`, `GoodProperty+0x14`) [known]: −1 Invalid, 0 Ware, 1 Settler, 2 WareGroup,
3 EitherGroup. An input of type 3 is a set of alternatives: one unit of **any** member satisfies one unit
(example: `foodScots` = `fishScots`, `bread` or `sheepHam`). The members are enumerated by
`PropertyGroupIter` (`Init` S 007767c0, `Next` S 00776690, `Current` S 00776630): it walks the **owner tribe's
goods list** (`tp_addGood`, `TribeProperty+0x20`) in script order and yields each good that has a positive
amount in the group good's own `gp_addCost` list. The order of the alternatives is therefore the tribe list's,
not the group's, and a member that is not in the owner's tribe list is never requested or consumed [known].

**Can a cycle start** (`CanStartProduction` S 00565bd0, asked by the worker when choosing work) [known]:

1. Production enabled (`bEnabled`; for barracks the training component decides) and `workerCount > 0`.
2. Barracks: the training component decides (not covered here).
3. `workingMode == 10`: false when more than 19 animals are counted in the building's low-resolution block:
   `AnimalAreas::GetCountAt` for the 16 × 16-cell block that contains the anchor
   (`LowResResourcePosition::ctor_FromFinePos` S 00582430: `x / 16`, `y / 16`, applied to the anchor cell),
   where every animal counts in the block of its **home** cell (`AnimalAreas::AddAnimal` S 005424c0), not where
   it stands [known].
4. Mines: §3.8.
5. Otherwise: the recipe is empty, or the input stock holds every recipe entry in full
   (`Stock::HasAll`).

**Start** (`StartProductionCycle` S 005657c0, called by the worker action `ProduceGood::Start`) [known]:
`bCycleRunning = true`; barracks start the next training slot; otherwise, if the recipe is not empty (and for
mines only when they must eat, §3.8):

- first input good of type other than 3: remove the whole recipe list from the input stock and immediately
  add one ware request per unit of every recipe entry (`NeedGoods::AddRequests(recipe)`, S 0064ea00);
- first input good of type 3: for each of `amount` units, take the first alternative (group order) that the
  input stock holds, remove one and request one of the same good again. Further recipe entries are neither
  consumed nor requested.

The worker then plays the work animation for `GetProductionDuration()` ticks [known] S 00777460.

**Duration** (S 00565ed0) [known]: `productionTime`, except for `workingMode` 6 and 10 where it is
`productionTime × factor` (S 00661b60 → S 00663390). The factor is the owner's sacrifice modifier
`effective[4]` (`Effect_ProductionSpeed`; modifier block +0xc4 = effective array +0xb4 + 4 × 4), which is 1.0
by default (S 006634f0) and equals `ownBonus[4] / hostileDivisor[4]`; an own effect sets
`ownBonus[4] = min(ownBonus[4], arg1 / 100)` (S 006630b0) [known]. Data: `ProductionSpeed` 75 → cycles take
0.75 of the time. Modifier table and effect list rules: [properties-data.md](properties-data.md) §3.9. For a
catapult the same field (25) is the length of the shoot animation ([military.md](military.md) §3.10).

**End** (`OnProductionFinished` S 00565f80, called when the animation time runs out) [known]:

- barracks: register a production event, finish the training slot;
- mines: first take one unit of the map resource at the linked cell (`FieldConnection::ConsumeFieldResource`
  S 0055c860 → `MapModifier::ConsumeAnyResourceAtCell` S 00674e70). It answers true when the cell has a
  resource type and its amount after the call is not 0; then `DeliverProducts` runs. Otherwise the
  link is reset to (−1, −1) and nothing is delivered (§3.8);
- otherwise `DeliverProducts` (S 00565990): register a production event (productivity statistic,
  S 00538460: a new entry starts at 0.5, each event adds 0.25 up to 1.0. `Statistics::Update` S 00537ba0, on
  every tick with `tick mod 600 == 0`, subtracts 0.05, not below 0, from the entry of every finished building
  and erases the entries of buildings that no longer exist); for product slot 0 and 1 that are set, compute
  {good, amount} through
  `GetEntryWithModifiers` (the amount of `goodAmountN`; for the single good id 0x17626a03, `corn`, the amount
  is doubled while the owner's sacrifice modifier flag 12, `Effect_CornDoubleProduction`, is above 0;
  `egyptCorn` 0x4a852f49 is not, so the Egyptians' `nilflood` sacrifice changes nothing [known];
  S 00661c50, S 00663450), add it to the **output stock** and to the player's good statistics;
- `bCycleRunning = false`.

Products leave the building through the worker (`Depot::HasAnyWare` / `TakeOneWare`: the first plain ware
of the output stock in ascending good id, S 0055b1b0; callers `Worker::TryStartBringGoodOut` S 0065cc40 and
`NMovie::PickupProduct::Start` S 00777f80) [known]; from the flag onward it is transport. Wares that a
storage building supplies to a request leave it differently, with a carrier spawned by the transport system
([streets-transport.md](streets-transport.md), `SpawnCarrierWithPackage` S 0064d020).

**Input stock keeping** [known]:

- `RequestAllInputs` (S 00565a70): skipped when slot 0 is empty, and for mines whose owner fails
  `ai::player::Player::IsStateNotDefault` (§3.8). `casern` types hand over to the soldier-training component here, before
  the next test. Then skipped when `ignoreGoodCosts` is set or the recipe is empty. First input of type 3:
  for every alternative of that first entry, request up to `stockLimit` (unscaled); further recipe entries
  are not looked at. Otherwise for every recipe entry request up to `GetHpScaledStockLimit()`.
- `RequestMissingInput(good, target)` (S 005654f0): `missing = target − inputStock[good] − openRequests[good]`;
  add `missing` single-unit requests.
- `GetHpScaledStockLimit` (S 0055c200): `stockLimit` when the type has no `health`; else
  `max(1, trunc(hitpoints / health × stockLimit))`. A type without `bp_setStockLimit` keeps the default −1, so
  its scaled limit is 1: the Olympic flame (health 60, no stock limit) asks for one unit of each recipe good once
  it is damaged [known].
- On every hit-point change (`RebalanceInputRequests` → `AdjustInputRequest` S 00565620): per recipe good,
  `have = stock + open requests`; if above the scaled limit cancel up to the surplus in open requests, then
  move any remaining surplus from the input stock to the output stock; if below, request the difference.
- Types without `depot` additionally clamp every input stock entry to the scaled limit (`ClampStockToLimit`
  S 0055b090): the count is overwritten with the limit, so the surplus units are destroyed. It runs after the
  rebalancing above, which has already moved the surplus of the recipe goods when production is enabled. The
  function writes the count in the tree node directly and leaves the stock's `totalUnits` unchanged (§2.5), so
  afterwards `totalUnits` is above the sum of the counts by the units destroyed, until a load rebuilds the stock
  from its entries ([logic-core.md](logic-core.md) §7) [known] S 0055b090. Readers of `totalUnits` are the mine
  food test (§3.8) and `VillageSacrifice::GetCostProgress` S 005613a0; it is neither saved nor hashed. Types
  with `health` are the only ones whose hit points change, so in the shipped data this concerns the military
  buildings, the catapults and the Olympic flame.

**Switching production** (command 0x2000a toggles; `SetEnabled` S 00565ff0) [known]: off → clear all ware
requests and move the whole input stock to the output stock (so the wares are carried away). On → for both
product slots move any units of the recipe goods from the output stock back to the input stock
(`ReclaimSurplusInputs`), then `RequestAllInputs`.

**"Enabled"** is `Production::IsEnabled` S 00565580 [known]: for a `casern` type (`BuildingProperty+0xf1`) it is
`SoldierTraining::IsAnyEnabled` S 005668b0 (a training slot or the promotion switched on) and `bEnabled` is not
read; for every other type it is `bEnabled`. Its readers: the worker's `ChooseNextWork`, the 0x2000a executor,
the initial-input latch of `Building::Update` (§3.6 step 3), `Hitpoints::OnChanged` (§3.15) and
`UpdateResourceSearch` (§3.9). The executor (`HandleToggleProduction` S 00780f80) calls
`SetEnabled(!IsEnabled())`, so on a barracks with any training part switched on every 0x2000a calls
`SetEnabled(false)`: requests cleared, input stock moved to the output stock, and the training stays on; the
command never switches such a barracks back on [known]. Nothing files the training inputs again until a
training part is toggled (0x20018 / 0x20019, whose re-synchronisation moves the units back,
[military.md](military.md) §3.4), so in effect the barracks starves rather than pauses [inferred from the
callers of `RequestAllInputs` and `VillageSoldierTraining_UpdateInputRequests`].

### 3.8 Mines (`size == 8 && workingMode == 6`) [known] S 00565bd0, S 005657c0, S 00565a70

- "Must eat" = the owner's sacrifice modifier flag 7 is not 1 **and** `ai::player::Player::IsStateNotDefault(owner)`.
  Flag 7 (modifier block +0x1c, S 00663430) is `Effect_MinerNeedNoFood`; it is 0 by default (S 006634f0) and
  set to 1 by an own effect of that type (S 006630b0) [known].
- `ai::player::Player::IsStateNotDefault` (S 005be330) [known]: player kind (+8) 1 → `state != 3`; any other kind →
  `state != 0`. Kind 1 is a computer player and `state` (+0xec) is the match's start-resources level (0 high,
  1 medium, 2 low, 3 campaign only), the same for every player ([players-victory.md](players-victory.md)
  §2, §3.4). So with start resources "high" the mines of human players work without food and request none; a
  computer player's mines do so only at level 3 [known: `Player.state` is written by `Player::Init` S 005bea90
  from the descriptor's start-resources value (`CreatePlayer` call in S 005abb60) and by the load code only].
- Input requests are filed only when `ai::player::Player::IsStateNotDefault(owner)`.
- A cycle can start when a resource cell is linked (`fieldConnection != −1`) and not (must eat and the input
  stock's `totalUnits`, all goods together (§2.5), is below the amount of the first recipe entry) [known]
  S 00565bd0.
- At cycle start inputs are consumed only when the mine must eat.
- The product's `gp_setMiningGood` (`GoodProperty+0xbc`, read through S 00553070 from the good in product
  slot 0) names the resource type searched on the map [known for the read; the map side S 00540660 is
  inferred]. Data: `coalScots → coal`, `ironOreBav → ironOre`, `stoneScots → stone`.
- One unit of the cell's resource is taken at every cycle end (`ConsumeFieldResource` S 0055c860, called from
  `OnProductionFinished`; its other caller is the work action `NMovie::Working::Update` S 0077ebf0). The link
  is dropped (`fieldConnection = (−1, −1)`) and the cycle delivers nothing when the cell has no resource type
  or its amount after the call is 0 [known] S 00674e70. The call (`ConsumeResourceAtCell` S 00674650) leaves
  an amount of 1000 (unlimited) alone and otherwise sets a positive amount to `min(7, amount − 1)`; at 0 the
  cell loses its type [known]. So the unit that empties a cell yields no product: a cell with amount `n`
  gives `min(n, 8) − 1` products to the mine linked to it (the first use of an amount above 8 sets it to 7;
  1000 never runs out) [known] S 00674650, S 00674e70, S 0055c860, S 00565f80. A mine consumes once per
  cycle: `Working::Update` switches on the working mode 0..3 only and a mine's mode is 6 [known] S 0077ebf0.
  In play 85 of 85 cycles that emptied a cell delivered nothing and 403 of 403 others delivered one product
  [live, 2026-10-12; no cell above 7 and no unlimited cell occurred]. `AddResourceAtCell` S 006745e0 caps a cell at 7, so an amount above 8 can only come from a map file. Owner
  of the amounts: [map-resources.md](map-resources.md).

### 3.9 Resource searches [known]

- **Deposit** (`UpdateDepositSearch` S 0055bfb0): `tickCounter` counts 0..100; on the tick it wraps to 0, a
  building of mode 1 or 2 takes the **mining good** of its slot-0 product (`GoodProperty+0xbc`,
  `gp_setMiningGood`, S 00553070). If that good's byte +0x50 is set (`gp_enableDeposits`, S 0054e870; data:
  `stone`, `wood`, `corn`, `egyptCorn`, `stoneScots`, `stoneBav`) and no deposit is linked, it links the
  nearest free deposit of that mining good within `workingRadius` (`Resources_FindNearestFreeDeposit`
  S 00540870, called with the anchor cell). The search (breadth-first from the anchor, which deposits count as
  free, the time-to-live a woodcutter puts on a tree it is working on) is specified in
  [map-resources.md](map-resources.md) §3.9.
- **Animal** (`UpdateHuntTargetSearch` S 0055c050): runs in the same tick, right after. When `tickCounter` is 0
  (just wrapped) a mode-7 building without linked animal links the animal found within `workingRadius` by
  `Resources_FindNearestHuntableAnimal` (S 005407a0 → S 0053fb40), a breadth-first flood fill from the
  anchor (neighbours of a cell are visited by stepping direction 4 once and then directions 0..5 in turn).
  It spreads only over cells with hex distance `<= workingRadius` from the anchor that pass
  `Map_IsCellWalkable` (S 005429c0; the anchor itself is always accepted). The first cell reached wins on
  which `NResources::System::FindHuntableAnimalAt` returns an animal whose animal property has a non-zero
  stack good count for the owner's tribe (player +0x44) and whose position (animal +0x38) the owner has
  explored (S 00542c40) [known]. `FindHuntableAnimalAt` S 0053ee60 looks the cell (`y × mapWidth + x`) up in
  the per-cell animal index and returns the **first** animal of that cell's vector for which
  `Animal::IsAliveAndUnreserved` S 00541c60 holds (state not 5, 7, 8 or 9, and no hunter reservation; animal
  states in [map-resources.md](map-resources.md)); only that one animal is then tested for goods and
  exploration, so a cell fails when its first free animal fails even if a later animal of the cell would pass
  [known] S 0053ee60, S 00542c40. In every other tick
  this function increments `tickCounter` again.
  The counter therefore
  advances by 2 per tick (0, 2, …, 100, then 0): in the 51st update of the finished branch the deposit search
  finds 100, resets the counter to 0 and searches, the animal search then sees 0, searches and leaves the
  counter at 0; both searches run every 51 ticks, first in the 51st [known] S 0055bfb0, S 0055c050. A building
  whose mode is neither 1, 2 nor 7 runs through the same counter without searching.
- **Mine resource** (`UpdateResourceSearch` S 0055ded0): own counter 0..100, period 101 ticks. With at least
  one worker, no linked cell, a product in slot 0 and not a catapult: breadth-first flood fill from the anchor
  (S 00540660 → S 0053f940, same neighbour order as the animal search) over every cell with hex distance
  `<= workingRadius` (S 00542970; no walkability test) for the first cell whose map resource type equals the
  product's mining good (`GoodProperty+0xbc`; S 00542d50); the amount is not tested [known]; link the cell
  found.
  If none is found, production is enabled and the building's productivity statistic is below 0.5: post or
  refresh the player message `!No resources found.` (category 3) at the building.

### 3.10 Storage and barracks stock keeping (`ordering` component) [known] S 00563f40, S 00563cc0

For `depot` or `casern` types, every 30 ticks (phase `(tick + unique.id) mod 30 == 0`) once the building is
finished, and immediately when a good flag is switched off: for every entry of `goodFlags` in ascending good
id:

| flag | good type | action |
|---|---|---|
| off | Ware | if a request for it exists that is not yet assigned, cancel one |
| off | other (settler) | remove every open settler order of this building for that good |
| on | Ware | if no unassigned request exists, add one ware request |
| on | other | if the building has no open order for that good, create one settler order |

So a storehouse with a good "collected" keeps one **unassigned** request open; requests that already have a
package assigned are not counted, so more than one unit can be on its way [inferred]. The test for "finished"
uses the building's own construction. Command 0x2001e toggles the flag of one good: a good without an entry,
or with a disabled one, becomes enabled; an enabled one becomes disabled [known] S 007817f0, S 00557630.

**Home settlers.** The ordering component (`Building +0x108`) holds at `+0x04` the settlers whose home is this
building: `Settler_LinkDestinationReference` S 0053bf50 adds them (category-3 orders, [settlers-jobs.md](settlers-jobs.md)
§3.1). `BuildingOrderingComp::Destroy` S 00563c10 releases them from the **last** entry first through
`Settler_UnlinkHomeBuilding` S 0053bf80 (the settler's home reference cleared, the first matching id erased);
the settler destructor S 006568b0 unlinks its home too (after the package discard, before the ship unlink and the
movement) [known]. A settler whose home is gone takes the invalid-home branch of `MoveToHome` S 007776f0.

Suppliers: when a requester asks for goods, storage buildings whose `goodFlags` has the good **enabled** are
skipped as suppliers unless the search ignores flags [known] S 00557da0 — a store that collects a good does
not give it away.

### 3.11 Settlers stored in buildings (`SettlerSpawn`) [known]

- A stored settler is one unit of its settler good in the output stock. A settler good the stock lacks can be
  made on the spot from its `gp_addCost` list (`Stock::ExchangeCostForGood`: remove the cost, add one unit;
  example in `Jobs.lua`: a worker costs a tool) S 00564360, S 0053a400.
- Releasing a settler sets `spawnCooldown = 10` ticks; while it is non-zero the building supplies no further
  settler order (S 00562440). `Update` decrements it each tick (S 00564780).
- `FillDefaultSettlers` (S 005646e0): when the tribe has a second carrier good (`TribeProperty+0xb0` != −1,
  §2.7) with a non-empty cost list, exchange its cost for one unit of it in the output stock again and again
  while the stock can afford it. Data: every bavarian `oxen` ware in the stock becomes a `good_oxen` settler;
  nothing happens for egyptians (no cost list) and scots (no second carrier). A busy byte (`bBusy`) is set
  for the duration. Its only caller is `ReleaseAllStockedSettlers` (§3.5), which sets `bBusy` again for its
  own spawns: while it is set, spawning a settler neither starts the cooldown nor touches the stock
  (S 00564360); the caller zeroes the stock entry itself.
- Entering (`OnSettlerEntered` S 00564eb0): nothing happens when the settler's good has an empty cost list.
  Otherwise a soldier becomes one unit of its own good in the output stock, and its value (settler +0x1ec) is
  appended to the per-good memory when it differs from the good's maximum (`gp_setHealth`,
  `GoodProperty+0x88`; S 00564c40); other settlers give back their cost goods.
- Healing: `regenTimer += 2` per tick; when it exceeds `mi_setRegenerationRate` (100) every remembered value
  is incremented and values that reach the kind's maximum (`gp_setHealth`, `GoodProperty+0x88`) are forgotten;
  the timer resets to 0 (S 00564780), i.e. one step every 51 ticks [inferred from the two constants]. A
  leaving soldier (`TakeSettlerValue` S 00564c90) takes the **highest** remembered value of its
  good, which is then forgotten, when the output stock holds fewer units of that good than there are
  remembered values; otherwise it keeps its own value (settler +0x1ec). The count is read after the soldier's
  own unit has left the stock (`SpawnSoldierForOrder` below calls `ConsumeSettlerGood` first), so of two units
  with one remembered value the first to leave is the healthy one [known: S 00565020, S 00564c90].
- **Which soldier a supplier sends** (`SettlerSpawn::SpawnSoldierForOrder(kind)` S 00565020) [known]: it walks
  the levels of the kind from the highest down to 0 (`SoldierLevelRange(tribe, kind, 0)` of the owner's tribe)
  and takes the first soldier good the output stock holds, whatever level the order named (good −1 when none,
  which the supplier tests of §3.12 exclude); `ConsumeSettlerGood`, create the soldier at the entrance cell,
  then `Livepoints::Damage(own value − TakeSettlerValue)` (the new soldier's own value, +0x1ec, is the full
  one), so it leaves with the remembered value.
  [military.md](military.md) §3.2–§3.3 for what this means for garrison, promotion and replacement orders. The heal sacrifice (effect 1003,
  S 00660270) empties the whole memory of every occupied building of its owner in the casern list, so the
  soldiers stocked there leave with full life points afterwards [known].
- Who may enter (`CanAcceptSettler` S 00564520): barracks accept soldiers; a barracks that is not also
  `depot` and `territoryBuilding` accepts nothing else; otherwise a type with `spawn` accepts any non-soldier.

### 3.12 Settler order matching (`OrderSystem::Update` S 005626c0) [known]

Runs once per tick, after all buildings. Iteration order: players 0..7; per player categories 0..6; per
category the bucket entries in creation order; per entry its **nodes** in order of first occurrence: the
target flag of the first order of each distinct goods network (§2.6). The target flag of an order is, tested
in this order: the linked flag; the requesting building's entrance flag; the linked street's flag (street
+0x38); the entrance flag of the first linked military building; else a flag reached through the ship
(S 00568e50). For each (entry, node flag):

1. `supplier = FindSupplierBuilding(owner of the flag, entry.goodId, flag position, category)`.
2. No supplier: only for category 4, an order is selected for the node and, when the `cooldownTicks`
   (`Military+0x60`) of its slot-1 military building is 0, the order's waiting soldier (order +0x100) is
   unlinked from that building and `cooldownTicks` is set to 10 (S 0055fc40) [inferred purpose: give up a
   soldier exchange]. Continue.
3. If the supplier can supply (below) and its `spawnCooldown == 0`: select one order of the entry for this
   flag (below); recompute the supplier for that order's own flag; if it still can supply:
   spawn the settler at the supplier's entrance, link the settler to the order's destination, delete the
   order, and mark the category as served for this player in this pass.

**Supplier search** (`OrderSystem_FindSupplierBuilding` S 00562280) [known]. All searches start from the
player's flag on the target position, consider only finished buildings whose entrance flag is in the same
component of the **walking** net as that flag (id array entry 1, net kind 1: the settler walks, so streets
without carrier count) and pick the lowest `NNet::System::GetFlagPathCost(.., kind 1)`; ties keep the earlier
list element (strict `<`).

- Non-soldier goods: candidate 1 = nearest `depot` building holding the good in its output stock. For
  category 3 a building whose good flag for that good is enabled is skipped; for every other category the
  good flags are ignored (the search's last argument is `category != 3`, and S 00557da0 tests the flag only
  when that argument is 0). S 00557da0 does not test the building's owner, and takes a candidate when
  `cost < best || best == −1` [known]. Candidate 2 (not for category 3 unless the good is the tribe's second
  carrier good, §2.7): if the good has a cost list, the nearest `depot` building holding **all** cost goods
  (S 00558510: one unit of each, `HasGood`; the amounts of the cost list are not compared [known]), else the
  nearest connected `depot` building at all. If both exist and differ, the one with the
  smaller **hex distance** to the target position wins; on a tie candidate 1.
- Soldier goods, category other than 3: nearest `casern` building holding any acceptable soldier good
  (`FindNearestSupplierWithAnyGood` S 00558330; acceptable goods per category from S 005619d0: categories 1/2
  same kind from the requested level upwards, 5 exactly the requested good, 6 any soldier of kinds 0 and 1,
  others the tribe's list for that kind). It is called with `ignoreGoodFlags = (category != 3)`, which is
  always true on this path, so the casern's good flags are not read, and `ignoreSettlerCheck =
  (category != 5)` [known: S 00562280]. For category 5 a building only counts when `SettlerSpawn::HasHealthySettler(good)` holds
  (S 005648d0: no remembered values for the good, or more units in the output stock than remembered values,
  §3.11), and the supplier found is rejected when the path cost is not below `mi_setHealthExchangeDistance`
  (200).
- Soldier goods, category 3: nearest `casern` building holding the good whose good flag for it is not
  enabled.

**Can supply** (`OrderSystem_CanBuildingSupply` S 00562440) [known]: cooldown 0, and: soldier good → output
stock has any acceptable soldier good; category 3 with a good other than the tribe's second carrier good →
output stock has the good; else `SettlerSpawn::CanSupplyGood` (S 005643c0: stock has the good or can afford
its cost; for a soldier good, the stock holds any soldier good of the owner's tribe of that kind, with no cost
exchange). The soldier then spawned is the highest stocked level of the kind (§3.11), not necessarily the
ordered good [known].

**Order selection within an entry** (S 00569430) [known]:

| category | rule |
|---|---|
| 3 | among orders whose building's entrance flag is in the node's goods network (entry 0): highest `(now − order.tick) − 10 × units of the good in that building's output stock`; a later order replaces the pick only when strictly greater; S 00652ab0, S 00651330 |
| 1 | among orders at that flag whose military building is in proximity zone 2: the one whose slot-0 value (float at military order slot +0x2c) is **highest**; a later order replaces the pick only when strictly greater |
| 2 | same with proximity zone 1 |
| 0, 4, 5, 6 | the order with the smallest `tick` (oldest) whose target flag is in the node's network; ties keep the earlier vector element |

"At that flag" / "in the node's network" is the id compare of §2.6: entry 0 of the flag's id array for
categories 0, 3, 4, 5, 6 (S 005691f0, S 00651330), entry 1 for categories 1 and 2 (S 00569290) [known].
Entry 0 is the goods net, entry 1 the walking net (§2.6): the node list and the selection of categories
0, 3, 4, 5, 6 work per goods network, while the supplier search and the selection of categories 1 and 2 use
the walking net.

For categories 1/2 the slot value is a **load weight** (`MilitaryOrderSlot+0x2c`, float) [known] S 00569290:
every candidate's slot first accumulates `weight += (1 / enemyDistanceA²) / openOrders` (S 00560690 →
S 00568910; `enemyDistanceA` = `Military+0x5c`, skipped while it is −1; `openOrders` = number of orders in the
slot's container), then the candidate with the highest weight wins and its weight is set to 0 (S 005606a0 →
S 00568870). A building close to the enemy therefore gains weight faster and is served more often; a slot that
is never served keeps growing. Owner of the surrounding rules: [military.md](military.md) §3.2.

The iterator keeps one "served" byte per category (+0x10..+0x16), cleared when it moves to the next player.
The byte of category 1 is the one the iterator tests before entering category 2: once a category-1 order of a
player was served in a pass, category 2 is skipped for that player in that pass [known: S 005691c0 writes
byte `+0x10 + category`, `NextNodeInPlayer` S 00569760 tests the byte at +0x11 (S 005697b5)]. The other six
bytes are never read [known, §10 Q5].

**Arrival** (`VillageOrder_LinkSettlerToDestination` S 00561e20) [known], by order category first: 4 → the
soldier is paired with the waiting soldier and linked to slot 1 of the military building; 1 and 5 → linked
to military slot 0 or 2; 3 → the building becomes the settler's destination (it walks in and is stored);
6 → the ship. Category 0 goes by settler type: worker → added to the building's worker slots; builder → bound
as the site's builder; carrier → the street (reference at street +0x98 when the one at +0x78 is valid, else
+0x78); soldier → the
building's garrison; specialist → the flag.

`OrderSystem::GetSupplyStatus` (S 00562820): 0 = a supplier exists, 2 = none but some building is reachable,
1 = nothing reachable ("not connected") [known]. The supplier step is `OrderSystem_FindSupplierBuilding`
S 00562280. The fallback always searches the **depot** list (+0x20), for soldier goods too
(`FindNearestReachable_ListDef54_AnyDist` S 005586d0 → `BuildingList_FindNearestReachable` S 00557fe0, mode 0,
layer 1): it needs a flag of the player at the position (none → 1), and then a finished depot (both construction
remainders ≤ 0) whose flag (+0xa0) lies in the same layer-1 net component (`FindNearestConnected` S 00557ef0);
there is no owner test besides the flag [known]. Callers: `Expedition::GatherCargo` S 005b8470 (1 →
`!Harbor is not Connected`, 2 → `!No Soldier for Expedition found`) and the military update S 005609b0.

### 3.13 Upgrade [known]

- Allowed when `Upgrade::GetBlockReason() == 0` (S 005670c0), tested in this order, the first hit returned:
  4 = building's `variantKey` differs from the owner's tribe (a conquered building of another tribe); 3 =
  under construction, builder still bound, or already upgrading; 1 = type has no `upgrade`; 2 = target `size`
  differs and the target type cannot be placed on the anchor ignoring the centre cell; 0 = allowed.
- `Start` (command 0x2000f, S 005671a0): `bActive = true`, `targetTypeId = property.upgrade`; create a second
  `Construction` and `Bulldozing` for the building and run `Bulldozing::Begin(target)` (levels ground, requests
  the **full** cost of the target type, §3.4); re-block the footprint with the target's size; raise "upgrade
  started". While upgrading, the effective construction (builder, site stock, progress) is the upgrade's
  (S 0055bf90). The building keeps working: `Building::Update` still takes the "finished" branch.
- `Update` (S 00567590): while work remains, run the builder request; when none remains and no builder is
  bound → `Complete`.
- `Complete` (S 005672c0): delete the upgrade construction, `bActive = false`, `Building::SetType(target)`
  (S 0055c110: replace the property **first**, then raise "building removed" and "building added", so the
  "removed" observers already see the new type; re-add the territory source if active), rescale hit points:
  `hitpoints = trunc(float32(hitpoints / oldMax) × newHealth)`, `maxHitpoints = newHealth` (S 0055b990, §3.15).
- `Cancel` (command 0x20010, S 00567320): if the upgrade construction is not paused, abort it (§3.4,
  `AbortAndReturnGoods`; unlike the pause command, `Cancel` does not first test that work is left); spill the
  refund computed by `CollectReturnedGoods` for the upgrade construction onto the entrance flag (**no halving**
  here; what does not fit is deleted with the temporary stock); delete the upgrade construction and its
  bulldozing; `bActive = false`, `targetTypeId = −1`; raise "upgrade cancelled". Units of the upgrade's site
  stock that did not fit on the flag during the abort are deleted with the construction [known:
  `Construction::dtor` S 0055e8c0 runs `Stock::Reset` on the site stock first, then `ReleaseBuilder`
  S 0055e850]. `Cancel` does not touch the `Blocking`: the footprint stays blocked with the target type's size
  mask that `Start` set [known: no call in the body].
- Between the builder's last stroke (`Construction::Complete`, both remaining values 0) and the next
  `Upgrade::Update`, which then completes the upgrade, lies one tick in which the upgrade is still active. A
  cancel in that tick aborts the finished site and refunds `CollectReturnedGoods` of fractions 1, i.e. the
  target type's full first `frameCost` entry and full `cost`, unhalved [inferred from S 00567320, S 0055e510,
  S 00567590].
- Readers of the **effective** construction (`Building::GetConstruction` S 0055bf90; an upgrading building
  looks like a site): the builder and delivery paths of this section and §3.19; the transport's goods
  distribution by arrangement (`GoodOrderBucket_SelectByArrangement` S 00652b70: an upgrading building counts as
  a site and takes the tribe's default type, [streets-transport.md](streets-transport.md) §3.11); the AI's
  `MilitaryMap::UpdateCell` S 00586790 and `StreetRouteOptimizer::ProcessEntry` S 005a52c0; the missing-goods
  overlay (S 00640418, S 0063ff9f) and the menu's `RefreshAvailability` (S 006240e6). Readers of the building's
  **own** construction (`Building+0x44`, finished during an upgrade): `GoodOrder_GetCategory` S 006541e0 and
  `BuildingList_FindNearestConnected` S 00557ef0, besides the spill refund of §3.5 and the "finished" tests of
  §3.6 and §3.10 [known].

Data: `guardHouse → tower → fortress` per tribe (6 `bp_setUpgrade` lines) [known]. Their sizes are `0x47`
(`SizeSmall + SizeMilitary`), `0x46` (`SizeMedium + SizeMilitary`) and `0x44` (`SizeLarge + SizeMilitary`)
[known: `buildings.lua`], so every shipped upgrade differs in size and runs the reason-2 placement test: the
tower adds the medium slope rule (§3.1 rule 9), the fortress the large rules 8 and 9 [inferred from §3.1].

### 3.14 Territory and sight [known]

Territory and borders are computed by the map (`NMap::Territory`, `MapModifier`); a building only registers
and removes a **source**.

- `ActivateIfOccupied` (S 005653d0): once, when the finished building first becomes occupied. Non-headquarters
  types post `!Military building occupied!` (`territoryRange >= 1`) or `!Watchtower occupied!`
  (`exploreRadius >= 1`) to the owner (category 1). Then `Activate`.
- `Activate` (S 00565350): if `territoryRange > 0`: `MapModifier::AddTerritorySource(anchor, radius, owner)`
  and detect border contacts with other players at `radius` and at `radius / 2`; then reveal sight; set
  `bActive`.
- `radius` = `Military::GetTerritoryRange` (S 0055fca0): 0 when `territoryRange <= 0`, else
  `territoryRange + flags[14]` of the owner's sacrifice modifiers (S 00661cc0 → S 006634d0, modifier block
  +0x38). Flag 14 is `Effect_ExpandTerritory`: 0 by default, set to the effect's `arg1` by an own effect
  (S 006630b0) [known]. Data: `ExpandTerritory` 5. The radius is read when the source is added.
  `Logic_RecalcTerritoryForPlayer` (S 00538d10) → `System::RefreshTerritoryForPlayer` (S 00558800) calls
  `TerritoryUpdater::Refresh` (S 00565300) for every `territoryBuilding` of a player: an active updater redoes
  the border-contact detection and, when the radius now exceeds `exploreRadius`, explores a disc of the radius
  [known]. S 00538d10 is called when a sacrifice with an effect of type 14 starts
  (`SacrificePlayerData::StartToggleEffects` S 00661cf0, `enable = 1`) and when it is removed
  (`StopToggleEffects` S 00661d60, `enable = 0`), once per such effect. It first has the map recompute all
  territory (`ai::map::MapModifier::RecalcTerritoryAll` S 00672f10 → `NMap::Territory::RecalcAll(anchor of the player's
  first building in the building vector, enable)`, then `MapModifier::RefreshTerritoryAll`), and only for
  `enable = 1` calls `RefreshTerritoryForPlayer` [known]. `RecalcAll` (S 0067a3b0) does not keep radii: it
  collects the sources anew from the buildings (`Territory_CollectSources` S 0067a030 with origin (0, 0) and
  an unlimited radius): every building whose territory updater is active and whose
  `Military::GetTerritoryRange()` is above 0 gives {anchor, owner index, that range}, so each radius is
  recomputed with the owner's current flag 14; a building whose anchor is exactly the origin cell (0, 0) is
  left out. Then `RecalcFullMap` rebuilds the grid from that list [known].
- Sight (S 00565100): only when `exploreRadius > 0`: explore a disc of `max(radius, exploreRadius)` around the
  anchor for the owner.
- Data: guard house 9 / explore 12, tower 10 / 13, fortress 11 / 14, castle 9 / 12, watchtower explore 16,
  expedition landing: an extra source of radius 4 is added before the building is placed (S 0055a820).
- When territory changes, the map calls `MarkBuildingsOutsideTerritoryNear(pos, radius)`: every building
  within hex distance `< radius` with a footprint cell that is no longer a territory cell of its owner is
  marked and removed in the next `System::Update` (§3.5) [known] S 00558170. The footprint test
  (`IsFootprintOutsideTerritory` S 0055c0b0) asks `IsPlayerTerritoryCell(owner, water = false, border = false)`.
- Removal gives the territory back: `TerritoryUpdater::dtor` S 00565270 (in `Building::dtor`, §3.5 step 6, before
  the military component) removes the source through `NMap::Territory::RemoveSource` S 0067a320, which does
  nothing for radius 0 [known]. On a transfer or conquest (§3.16) the old owner's source is therefore removed
  before the new owner's source is added.
- Border contacts (`DetectBorderContacts` S 005651e0 → `DetectTerritoryContacts` S 00674ad0, from `Activate` and
  `Refresh`): with `p` the owner and `o` the foreign player met, `o.reached[p] = true`, `o.reachedPos[p] =` the
  centre, `p.reached[o] = true`, `p.reachedPos[o] =` the ring cell, and `SetPlayerSpotted(o, p)`
  ([players-victory.md](players-victory.md) §3.5) [known].

### 3.15 Hit points [known]

- Regeneration (S 0055b910): when `tick − lastRegenTick >= mi_setRegenerationRate` (100), an **unsigned** compare
  (`rate <= now − last`), and `hitpoints < health`: `lastRegenTick = tick`, and unless the game-wide flag
  `GameSystem+0xec` (a cinematic) is set, `hitpoints += 1`; the timer restarts during a cinematic too [known].
- Damage (S 0055b970, only caller: catapult hit S 0055e080): ignored while `GameSystem+0xec` is set; else subtract.
  The catapult hit posts `!Building hit by Catapult` to the owner, and when the damage is at least the current hit
  points `!Building destroyed by Catapult` (owner) and `!Enemy Building destroyed by Catapult` (attacker). The
  catapult is the only damage source of building hit points. Its rules (target filter and candidate order,
  `candidates[targetSeed mod count]`, ammunition = the first cost (`costs[0]`) of the `bp_setGoods` good, taken from
  the input stock and requested again, projectile flight time, damage divided by the hit owner's
  `Effect_BuildingArmor` factor) are owned by [military.md](military.md) §3.10; the functions are
  `Catapult::SelectTarget` S 00567d20, `HasAmmo` S 00567a30, `Fire` S 005678b0, `OnCatapultHit` S 0055e080.
- Every change (S 0055b8b0): rebalance input requests (if production enabled, `IsEnabled` of §3.7), clamp stock (non-depot types),
  and remove the building when `hitpoints < 1`.
- Capacity scaling: garrison capacity = `max(1, trunc(ratio × soldierLimit))` (S 0055c1a0), stock limit
  as in §3.7. How many soldiers a building then asks for (zone fractions, allocation every 21 ticks) is in
  [military.md](military.md) §3.2.
- Upgrade rescale (S 0055b990) [known: disassembly]: `hitpoints = trunc(float32(hitpoints / maxHitpoints) ×
  newHealth)`, `maxHitpoints = newHealth`, then the change handler above. The instructions are `FILD hp`,
  `FIDIV max`, `FSTP` to a float32, `FLD`, `FIMUL health`, `__ftol2_sse`: the ratio is rounded once to float32,
  the product is not, and the conversion truncates.
- Data: only 14 types have `health` (castle 200, fortress 100, tower 80, guard house 60, catapult 40, …)
  [known].

### 3.16 Ownership change [known]

`TransferBuildingOwnership(old, newOwner, notify)` (S 0055a210), in this order:

1. Remember from the old building: type id, anchor cell, `variantKey`, the id of its entrance flag, the fight
   attached to its `military` (if any), `hitpoints`, and references to all soldiers in its attacker list
   (`Military+0x30`, the soldiers attacking it).
2. If `notify`: post `!Lost Military Building to enemy.` (category 1) to the old owner.
3. Set `destroyed` on the old building and `RemoveBuilding(old, spill = false)`: no stored settlers released,
   no goods spilled, no remains (§3.5). Then remove the remembered entrance flag if it still exists.
4. Construct the new building (`Building::ctor_Transfer` S 0055d4e0): all components fresh, new `Unique`,
   `variantKey` = the old one (not the new owner's tribe), entrance cell computed from it, footprint blocked,
   territory source activated at once (`TerritoryUpdater::Activate` directly, so no `!Military building occupied!`
   is posted), "building added" raised. No ground levelling, no material requests.
5. Insert into the unique map and the building vector (at the end: the building moves to the back of the
   update order); attach the entrance flag (§3.2 step 3); `Construction::Complete`; route the map change;
   index; set the productivity statistic to its start value when the type has a product in slot 0 and is not
   a catapult, or has a `plantingDeposit` whose deposit property names a good. This test differs from §3.2
   step 5: it does not look at `productivity`.
6. If `notify`: post `!Military Building conquered.` to the new owner.
7. Link every remembered soldier to the new building's attacker list (`Military+0x30`); set
   `hitpoints` to the remembered value (`maxHitpoints` stays the type's `health`); re-attach the remembered
   fight to the new building.

Everything else starts from constructor defaults: both stocks empty, no workers, no ware requests, good
flags empty, production enabled, upgrade inactive, ticker and search counters 0, `destroyCountdown` −1,
soldier kind 0.

`ConquerBuilding` (S 0055a890) wraps it with `notify = false` and carries more: before the transfer it moves
the output and the input stock into two temporary stocks, notes whether the building has a worker
(`workerCount != 0`) and counts the present soldiers per level of the building's soldier kind; after it,
`Workers::SpawnWorker` (§3.18) when there was a worker, one `Soldiers::SpawnSoldier` per counted soldier with
the level range taken from the **new** owner's tribe, and both stocks moved back. Its other caller is Lua
`vi_changePlayerOfBuilding`.

`TransferAllBuildingsOfPlayer(fromPlayer, newOwner)` (S 0055aac0, from `NLogic::System::TransferPlayerAssets`)
walks the building vector twice, front to back: the first pass handles only `fromPlayer`'s buildings whose
type has `territoryBuilding`, the second pass all his remaining buildings. A building whose own construction
has work left is removed with `RemoveBuilding(spill = false)`; every other one goes through `ConquerBuilding`.
After either, the walk continues at the element that moved into the place; a conquered building is appended
at the end of the vector under its new owner [known]. The kept `variantKey` is what blocks upgrades with
reason 4 (§3.13).

### 3.17 Remains [known]

`Remains` block the footprint of the dead building. `burnTicks` starts at the remains property's burning time
(`rm_setBurningTime`, 50 for all three sizes), is decremented once per tick in `System::Update`, and the
remains are deleted (footprint unblocked) when it expires (S 0055a640, S 00558ec0). On deletion, a remains
property whose field +0x40 is not −1 leaves a doodad of that id on the cell (`rm_setDoodadAfterFinished`,
S 0054fd70; all three calls are commented out in `remains.lua`, so the shipped data leaves nothing). The
remains expire when `burnTicks < 1` after a decrement, i.e. with the 50th decrement; remains are updated after
the buildings, so those created by a removal inside `System::Update` get their first decrement in the same
tick. Creating (`System::CreateRemains` S 005598a0) and deleting (`System::RemoveRemains` S 00558ec0) each
invalidate the construction flags in hex radius 4 around the cell (§5.2) [known].

### 3.18 Workers (`NVillage::Workers`) [known]

Ten settler references of 0x20 bytes at +0x10 and `workerCount` at +8 (S 0055b5b0).

- **Add** (`AddWorker` S 0055b420, through `VillageLink_LinkWorker` S 0053c410, which also points the
  settler's workplace reference +0x120 at the building): the settler goes into the first empty slot and
  `workerCount += 1`; with all ten slots taken nothing happens. Called when a worker order is served (§3.12
  arrival) and by `SpawnWorker`.
- **Remove** (`RemoveWorker` S 0055b470, through `VillageLink_UnlinkWorker` S 0053c440): the slot whose
  settler has the same unique id is cleared, `workerCount −= 1`, the settler's workplace reference is cleared.
  Called from the worker's destructor (a worker that dies or is deleted) and from `ReleaseAllWorkers`. The slot
  stays empty where it was; slots are not compacted, while the presence test of `Building::IsOccupied` walks
  the first `workerCount` slots (S 0055b4d0) [known; inferred consequence: with more than one worker a hole
  can hide a later worker; `workerLimit` is 0 or 1 in the shipped data]. The save code walks all ten slots
  and writes the valid ones (S 0055b510).
- **Effect of losing the worker**: `workerCount` no longer equals `workerLimit`, so the next firing of the
  worker ticker files a new worker order (§3.6 step 4, at most 101 ticks later, and only when the building has
  no other open order); `IsOccupied` is false until the replacement has arrived; `CanStartProduction` is
  false. A territory source that is already active stays active (§3.14 activates once).
- **`ReleaseAllWorkers`** (S 0055b620; from the destructor and before a load): every referenced settler is
  unlinked, which leaves it without a workplace (it then goes home, [settlers-jobs.md](settlers-jobs.md)
  §3.4 [inferred]); in batch editing mode the settler is deleted instead.
- **`SpawnWorker`** (S 0055b6a0; batch-editing placement §3.2, conquest §3.16, Lua
  `CreateBuildingWithSettler`): create a worker of the type's `worker` good at the entrance cell
  (`Building+0xf8`) for the owner, with `leaveBuilding = 1`, link it, and set its state directly to 0x1d when
  `workingMode == 8`, else 0x23 (S 0065c710). Neither is one of the four "not present" states, so the building is
  occupied at once. Builders (constructors) and carriers are not made here; they have their own creators [known].

### 3.19 Delivered wares (`Depot::CollectGoods` S 0055aca0) [known: disassembly]

Called by `NTransport::NeedSystem::DeliverPackage` (S 00651bc0) on the building of the ware request the
package serves, when the carrier is inside ([streets-transport.md](streets-transport.md), delivery). With
`good` = the package's good (+0x18):

1. If `upgrade.bActive` and the upgrade construction still has work (`remainingA > 0` or `remainingB > 0`):
   add one `good` to the **upgrade's** site stock. Execution continues with step 2.
2. If the building's own construction has work left: add one `good` to its site stock. Otherwise add one to
   the **output stock** when the type is `depot`, else to the **input stock**.
3. Cancel one open request for `good` in `needGoods` (`NeedGoods::CancelRequest` S 0064e3a0).

Step 1 does not skip step 2: during an upgrade every delivered unit is credited twice, once to the upgrade
site and once to the finished building's input (or output) stock, whichever request it was meant for. The
function does not look at which list requested the good. Seen in the running game: each of the 8 deliveries
to an upgrading guard house made two `Stock::AddOne` calls, and the input stock of the finished tower still
held 8 units [known: live 2026-10-12]. The code cuts the entries when the upgrade completes:
`Upgrade::Complete` S 005672c0 (`SetType`, then) → `RescaleToTypeMax` S 0055b990 → `Hitpoints::OnChanged`
S 0055b8b0 → `ClampStockToLimit` S 0055b090, every entry to `max(1, trunc(hitpoints / health × stockLimit))`
of the new type (S 0055c200, ratio from `Hitpoints::GetRatio` S 0055b850). For a `towerBav` at full hit points
(80 / 80, `stockLimit` 4) `plank 3` stays and `stoneBav 5` becomes 4, but the clamp writes the tree node only
and `totalUnits` stays 8 (§2.5, §3.7) [known]. The live count of 8 is that total [inferred: the entries would
sum to 7]; the extra unit vanishes from `totalUnits` at the next load. A reimplementation that wants equal
mine-food tests and sacrifice progress must keep `totalUnits` as a separate counter with this behaviour.

## 4. Update order

`NLogic::System::Update` (S 00527070) calls `NVillage::System::Update` once per **logic tick** [known]. A tick
runs only while the game is not in batch editing mode. Order of one tick [known]: tick counter + 1; the 8
street planners; `ai::player::PlayerTable::UpdateAll`; then, inside one map-update batch, **`NVillage::System::Update`**
and `NNet::System::Update`; then `NSettlers`, `NTransport`, `NResources`, `NDoodads`, `NMilitary`, navy,
statistics (if initialised), AI, sacrifice, spawn system, chests, victory conditions; after that the map
script's logic-tick callback (only when the caller of `Update` passes its second argument non-zero). The
settler actions that call into this subsystem therefore run **after** the buildings and the order matching of
the same tick.

Within `NVillage::System::Update` (S 0055a640):

1. For every building in vector (placement) order: if not `markedOutsideTerritory`, `Building::Update` (§3.6);
   then if `destroyCountdown == 0` or `markedOutsideTerritory`, `RemoveBuilding(spill = true)` and continue
   with the element that moved into its place.
2. For every remains object in ascending unique id: decrement, delete when expired.
3. `OrderSystem::Update` (§3.12).

Rates inside a building: worker request every 101 ticks (per-building ticker starting at 0; it only
advances while the building is finished and not marked); deposit
and animal search every 51 ticks; mine resource search every 101 ticks; stock keeping every 30 ticks with a
per-building phase; hit-point regeneration at most once per 100 ticks (`tick − lastRegenTick >= 100`, and
`lastRegenTick` only moves when a damaged building is found); spawn cooldown 10 ticks.

Called from other subsystems inside the same tick (settler actions): `CanStartProduction`,
`StartProductionCycle`, `OnProductionFinished`, `Construction::AdvanceWork`, `Construction::Complete`,
`Workers::AddWorker` / `RemoveWorker`, `Catapult::SelectTarget` / `Fire`; from the settler system's own
loop (`UpdateSettlerVector` S 00654a10): `SettlerSpawn::OnSettlerEntered`;
from transport: `Depot::CollectGoods`; from the road net (same map batch, right after the buildings):
`RemoveBuilding` through `RemoveFlag`; from the military system: `OnCatapultHit` (projectile impact),
`TransferBuildingOwnership`, `RemoveBuilding` on capture.

Per frame only: nothing in this subsystem. Rendering (`S2CG::Building`) reads `remainingA/B`
(`S2CG::Building::Update` S 006abcf0) and the hit-point ratio (`UpdateFireEffects` S 006abbb0 →
`Hitpoints::GetRatio` S 0055b850) [known]; that it reads the upgrade state is [inferred] (not looked for).

---

## 5. Inputs and outputs

### 5.1 Lockstep commands (`nGame::System::HandleGameCommand` S 007845a0) [known]

| id | handler | payload | effect |
|---|---|---|---|
| 0x20002 | `HandlePlaceBuilding` S 00781980 | type id, cell x, cell y; sender = owner | re-check placement, place |
| 0x20003 | `HandleDestroyBuilding` S 00781150 | building unique (64 bit) | §3.5 |
| 0x2000a | `HandleToggleProduction` S 00780f80 | building unique | toggle `bEnabled` |
| 0x2000f | `HandleStartUpgrade` S 00781540 | building unique | start if block reason 0 |
| 0x20010 | `HandleCancelUpgrade` S 007815d0 | building unique | cancel if active |
| 0x2001e | `HandleToggleGoodFlag` S 007817f0 | building unique, good id | toggle collection of a good |
| 0x20029 | `HandleAbortConstruction` S 00782fc0 | building unique | pause site (effective construction), §3.4 |
| 0x2002a | `HandleCommand_2002A` S 00782840 | building unique | continue a paused site (effective construction), §3.4 |
| 0x2002b | `HandleCommand_2002B` S 00782910 | player index (payload, not the sender) | player left: remove that player's first headquarters type building (first match in the `depot` list, S 005579a0), `spill = true` |

The handlers 0x20003, 0x2000a, 0x2000f, 0x20010, 0x2001e, 0x20029 and 0x2002a look the building up by unique
id, ignore the command when it does not exist, and do not compare its owner with the sender [known] (bodies
read; 0x2002a S 00782840). The game's own names for the ids (`GE_Building_Create`, `GE_Construction_Pause`, …)
and the senders are in [game-commands.md](game-commands.md).
0x20029 acts on the *effective* construction, so during an upgrade it pauses the upgrade's site (materials
back to the flag, `aborted` set) while the upgrade itself stays active until 0x20010 [known] S 00782fc0. Other callers of
`PlaceBuilding` [known: call edges of S 0055a090]: the AI (S 005a1ac0), player creation from the map
(S 005abb60), Lua `CreateBuilding` (S 005d9a30) and `CreateBuildingWithSettler` (S 005d9ac0),
`NLogic::Edit::PlaceBuilding` (S 00538b50), the map editor (S 00601300, S 00602ac0), the debug tool
(S 00604dd0), expeditions (S 0055a820).

### 5.2 Events raised [known]

- `NLogic::CallbackManager` broadcasts (the offset is the slot in each registered receiver's vtable): building
  added (+0x08; also raised after a load and by `SetType`), building removed (+0x0c), upgrade started (+0x10),
  upgrade cancelled (+0x14), remains added (+0x70), remains destroyed (+0x74) (S 005304a0, S 00530620,
  S 00530520, S 005305a0, S 00530f20, S 00530fa0); observer notification "building completed" (S 0055eec0).
- Player messages (text key, category): `!Building constructed` (7), `!No resources found.` (3),
  `!Military building occupied!` (1), `!Watchtower occupied!` (1), `!Building hit by Catapult` (1),
  `!Building destroyed by Catapult` (1), `!Enemy Building destroyed by Catapult` (1),
  `!Military Building Destruction executed` (1), `!Attack Target has been destructed` (1),
  `!Building is not connected` (1), `!Lost Military Building to enemy.` (1),
  `!Military Building conquered.` (1).
- Map-update batch (`MapUpdateBatch` on `g_pGameSystem->cmdRouter`), no message: on place, an
  obstructed-doodad check per footprint cell (S 00532280); on place, removal, ownership transfer, upgrade start
  and the creation and removal of remains, one construction-flag invalidation of hex radius 4 around the anchor
  (`InvalidateConstructionAroundCell2` S 005323b0; callers S 0055a090, S 00559db0, S 0055a210, S 005671a0,
  S 005598a0, S 00558ec0) [known]. The construction flags, doodad removals and elevation changes become
  visible when the outermost batch closes ([map-resources.md](map-resources.md) §3.5).

### 5.3 Asked of other subsystems

| subsystem | what |
|---|---|
| map | territory owner grid, grid state bits, heights, levelling, footprint blocking, territory sources, exploring |
| road net (`NNet`) | flag at a cell, place/remove flag, same-component test, path cost between flags |
| transport | `NeedGoods` requests, packages on a flag, spilling goods |
| settlers | create worker / builder / carrier / soldier / specialist at an entrance cell |
| resources | nearest free deposit, nearest huntable animal, nearest resource cell, animal count of an area |
| statistics | productivity per building, produced goods per player |
| sacrifice | per-player modifiers (`SacrificeModifiers`: 15 flags at +0x00, own bonus +0x3c, hostile divisor +0x78, effective factor +0xb4; S 006634f0): effective[4] production time, flags[14] territory range, flags[12] corn amount, flags[7] mine food rule |
| AI | "building added" / "building removed" hooks from the constructors and the destructor |
| properties | all type data |

### 5.4 Offered to other subsystems

Building lookup by unique, by cell (`FindBuildingAtOrNearest` S 00558890), nearest of type (S 00557830),
first building / headquarters of a player (S 00557d40, S 005579a0), supplier searches (S 00558330, S 00558510,
S 00557da0), the depot stocks, `CanAcceptSettler`, `GetSupplyStatus`.

---

## 6. Data-driven parameters

All keys are Lua calls in `data/game/scripts/properties/*.lua`, run once when the property database loads
([../data-loading.md](../data-loading.md)) [known: the keys, in the named files]; that nothing is re-read
during a match is [inferred] from that document, not re-read here.

**`buildings.lua`** — `properties.bp_*` (setter addresses in [../lua-surface.md](../lua-surface.md)); usage
count over the 104 types and examples:

| key | uses | examples |
|---|---|---|
| `bp_setSize` | 104 | woodcutter `SizeSmall`, bakery `SizeMedium`, farm `SizeLarge`, mines `SizeMine`, guard house `SizeSmall+SizeMilitary` |
| `bp_addFrameCost` / `bp_addCost` | 99 / 102 | woodcutter plank 1 / plank 1; bakery plank 2 / `stoneScots` 2; fortress plank 4 / `stoneScots` 7 |
| `bp_setGoods` / `bp_setSecondGoods` | 83 / 1 | bakery `bread` 1; brewery (`brauhaus`) `weissbeer` 2; goat breeder `goat` 1 + `milk` 1 |
| `bp_setStockLimit` | 65 | 6 in 38 calls (workshops and the three fortresses), 2 in 18 (mines, the three guard houses and others), 4 in 7 (the three catapults, the three towers, `gemMineClay`), 3 in 2 (`gemMine`, `gemMineBav`) |
| `bp_setProductionTime` | 79 | workshops 333, woodcutter 55, farm 83, catapult 25, goat breeder 100, `hunterScots` 0 |
| `bp_setRestTime` | 79 | 55 typical, woodcutter 222, fisher 770, hunter 1500 |
| `bp_setWorker` / `bp_setWorkerLimit` | 86 / 22 | `good_bakerScots`; limit set to 0 in 15 calls and to 1 in 7; unset = 1 (constructor default) |
| `bp_setWorkingMode` | 35 | see §2.1; unset = 6 |
| `bp_setWorkingRadius` | 43 | woodcutter 6 (set twice, 5 then 6; the later call wins), stone pit 8, fisher 8, hunter 8, mine 3, farm 2, catapult 12, ship yard 1 |
| `bp_setPlantingDeposit` | 5 | forester `tree_10`, farm `field_01` |
| `bp_setDepot`, `bp_setSpawn` | 4 / 7 | castle and the three storehouses; barracks have spawn only |
| `bp_setCasern` | 4 | castle and the three barracks |
| `bp_setTerritoryBuilding`, `bp_setTerritoryRange`, `bp_setSoldierLimit`, `bp_setExploreRadius` | 10 / 11 / 9 / 13 | guard house (scots) range 9, soldiers 2, explore 12; soldier limits differ per tribe (guard house 2 / 3 / 4, tower 4 / 6 / 8, fortress 6 / 9 / 12); the castle has range 9 and no soldier limit; `sacrificeOlympicFlame` has range 4 without `bp_setTerritoryBuilding` |
| `bp_setHealth` | 14 | castle 200, catapult 40, Olympic flame 60, guard house 60 (`guardHouseClay` 80), tower 80 (`towerClay` 100), fortress 100 (`fortressClay` 120) |
| `bp_setUpgrade` | 6 | `guardHouse → tower` |
| `bp_setConstructionTime` | 2 | castle −1, Olympic flame −1 (all others keep the default 500) |
| `bp_setRemains` | 99 | `remainsSmall/Medium/Large` |
| `bp_setDoorOffsetDirection` | 7 | all seven `DoorOffsetNorthWest`: the three farms, `sauerey`, `oxenBreeding`, `sacrificeBav`, `goatBreeder`, each for its own tribe only |
| `bp_setConstructionPosition` / `bp_setIdlePosition` | 388 / 158 | per tribe, index 0..3 / 0..1, e.g. (−3.0, 1.0) |
| `bp_setIgnoreGoodCosts` | 15 | hunter, stone pit, temples, barracks, ship yard |
| `bp_setNoProductivity`, `bp_setProducedSettler`, `bp_setCatapult`, `bp_setCatapultDamage`, `bp_setGfxBreeding`, `bp_setArrangementValue`, `bp_setArrangementLocked`, `bp_setAiScore`, `bp_setAiThreat`, `bp_setName`, `bp_setGfxName` | 7 / 2 / 3 / 3 / 3 / 66 / 4 / 82 / 20 / 104 / 104 | catapult damage 10 (all three); produced settler `good_oxen` (`oxenBreeding`), `animal_sheep` (`sheepBreeding`) |

**`Goods.lua` / `Jobs.lua`** — `gp_addCost(good, input, amount)` (recipes and settler costs), `gp_setType`,
`gp_enableDeposits`, `gp_setMiningGood`, `gp_setSettlerType` (0 Worker, 1 Constructor, 2 Carrier, 3 Soldier,
4 Specialist, 5 NPC), `gp_setHealth` [known]. Despite its name, `good_buildingHelperBav` ("Building Helper",
`Jobs.lua` lines 387–390) is a Worker settler costing `toolBav` 1, the worker of `sauerey` and `oxenBreeding`
(`bp_setWorker`); the builders are the `tp_setConstructor` goods (`good_constructorBav`, `good_constructor`,
`good_constructorScots`) [known: data].

**`config.lua`** — `cfg_setConstructTime(30)` (GameConfig+0x18, strokes per builder position and hammer
animation length), `cfg_setBulldozeTime(55)` (GameConfig+0x14, not read by this subsystem) [known].

**`military.lua`** — `mi_setRegenerationRate(100)` (+0x110: building hit-point regeneration period and
wounded-settler healing threshold), `mi_setActionsInFightDelayTime(300)` (+0x118: demolish delay under
attack), `mi_setHealthExchangeDistance(200)` (+0x11c: path-cost limit for category-5 soldier orders) [known].

**`remains.lua`** — `rm_setBurningTime(…, 50)`; `rm_setDoodadAfterFinished` exists as a binding (S 0054fd70)
but is commented out for all three remains [known].

**`tribes.lua`** — `tp_addBuilding(tribe, type)` (build menu, 109 lines), `tp_addGood` (tribe goods; refund
filter of §3.5), `tp_setConstructor` (+0xc0, builder good), `tp_addBonusResources` (+0x90, the extra
headquarters stock of §3.2; `tp_addStartResources`, +0x80, is only the default of a map's initial goods,
[properties-data.md](properties-data.md) §2.3), `tp_setSecondCarrierId` (+0xb0: good-flag redirect §2.7,
`FillDefaultSettlers` §3.11, supplier rule §3.12; 2 lines: bavarians `good_oxen`, egyptians `good_helper`),
`tp_setWorkerToolGoodId` (+0xbc), `tp_setConstructionGoodId` (+0xb4), `tp_setSoldierUpgradeGoodId` (+0xb8)
[known: setters S 0054afc0 (`tp_addBuilding`, list +0x40), S 0054af00 (`tp_addGood`, list +0x20), S 0054acf0,
S 0054a980, S 0054aa30, S 0054ad40, S 0054ad90, S 0054aca0, S 0054ade0]. The last three have
no reader in the functions of this document; their users (AI tool gift, barracks promotion) are in
[ai-player.md](ai-player.md) and [military.md](military.md).

**`sacrifices.lua`** — effect types that reach this subsystem: 4 `ProductionSpeed` (data 75), 7
`MinerNeedNoFood`, 12 `CornDoubleProduction`, 14 `ExpandTerritory` (data 5); record layout and application
rules in [properties-data.md](properties-data.md) §2.7, §3.9 [known: data].

Hard-coded constants (not data): ticker period 100 (fires every 101 ticks); search counters 100; stock-keeping period 30; spawn
cooldown 10; refund halving; animal cap 20; placement slope limits ±3 and radii 1/2/4; expedition radius 4;
order score factor 10; productivity 0.5 threshold for the "no resources" message [known].

---

## 7. Save and load

Stream primitives: section tag (version returned on load), int, count (a writer of its own, stream vtable
+0x64, used for the order, slot, good-flag and wounded-map counts; the building and remains counts are plain
ints), byte/bool, float. Each component is an `IStoreable` with Store (vtable +4), Load (+8), PostLoad (+0xc).

**`NVillage::System::Store`** S 00557cc0 [known]: tag `VillageSystem`; byte +0xbc; buildings; remains;
`OrderSystem`.

- Buildings (S 00557a20): count; per building in vector order: type id, owner player index, building body.
- Remains (S 00557b60): count; per entry two property ids (remains, building), then the object: tag
  `VillageRemains`, unique, position, `burnTicks`, blocking, tribe key (S 005640e0).
- Orders (S 00561f90): tag `Order System`, enabled byte, count, each order: tag `Village Order`, unique, flag
  reference, street reference, slot count (3), per slot building reference + soldier reference, then the
  `NLogic::Need` base (S 00568f00) [known]. Load (`OrderSystem::Load` S 005629c0, `Order::Load` S 00568f90):
  the system is cleared first; orders are recreated in stored order; section version 0 of `Order System` has
  one extra count after the orders; `Village Order` version 1 stores exactly one soldier slot (slot 0) and
  no slot count; versions 2 and above store the count and that many slots; version 0 stores no slot at all;
  the `Need` base follows in every version [known: disassembly 00568fd2..00569056]. `Order::PostLoad`
  (S 00569070) resolves the flag, street and slot references and the base's building and ship references;
  the index is emptied at the end of `Load` and rebuilt in PostLoad (below).

**Building body** (`StoreSavegame` S 0055c470; `Load` S 0055d290 mirrors it) [known], in this order:

1. tag `VillageBuilding` (versions 0..2; this build writes 2), unique, position;
2. ticker; depot; workers; deposit reference; animal reference; construction; production; blocking;
3. int +0x38 (`reserved38`, §2.3); int `variantKey`; entrance flag reference; settler spawn; field connection; territory updater;
   bulldozing; order container; byte `initialInputsRequested`;
4. military — only if `territoryBuilding`;
5. good flags; int `tickCounter`; int `resourceSearchCounter`;
6. catapult — only if `catapult`;
7. upgrade (tag, `bActive`; if active: target type id, the upgrade construction, the upgrade bulldozing,
   S 00567410);
8. ordering — only if `depot` or `casern`;
9. hit points; projectile references;
10. soldier training — only if `casern`;
11. sacrifice and then the sacrifice research reference — both only if `workingMode == 9`; on load the
    reference is read only when the section version is ≥ 2;
12. byte `markedOutsideTerritory` — on load only when the section version is ≥ 1.

`Load` (S 0055d290) reads items 1–10 unconditionally in exactly this order with the same type-flag conditions
as `StoreSavegame`; the two gates above are its only version tests [known]. The conditions use the type the
building was created with (type id stored in front of the body), so a type whose flags differ between the
saving and the loading data set shifts the stream [inferred]. The `military` section has version gates of
its own ([military.md](military.md) §7).

Component layouts [known]: construction = tag, float `remainingA`, float `remainingB`, builder reference,
site stock, type id, ship reference (version ≥ 1), byte `aborted` (version ≥ 2) (S 0055e720, Load
S 0055e7a0). Depot = tag, byte +8, input stock, output
stock, ware requests, returning packages, settler references (the checksum's untagged variant
`Depot::StoreUntagged` S 0055ae70 writes the same order: stockA, stockB, NeedGoods, returning goods, settler
references) (version ≥ 2; version 0 has an extra legacy
byte instead; versions < 3 do not store the byte +8 and default it to true) (S 0055ad30,
S 0055ada0). Production = tag, `bEnabled`, and
`bCycleRunning` from version 1 (S 005655a0, Load S 005655e0). Blocking = tag, active byte, position, size
mask; version 0
stored a legacy size index remapped 0→7, 1→6, 2→4, 3→8, 4→16 (S 00566ee0). Workers = tag, `workerCount`,
then the valid references among the ten slots (S 0055b510); `Load` (S 0055b6f0) first releases the current
workers, then reads `workerCount` references into slots 0..count−1, so holes are closed by a save and load.
Good flags = tag, count, pairs {good id, enabled byte} (S 00562d20). Settler spawn =
tag, cooldown, wounded map (count; per good: good id, value count, values; version ≥ 1), regen timer
(version ≥ 2) (S 005645b0, Load S 00564af0).

**Recomputed on load** [known]: the entrance cell (S 0055d290; it is computed right after the position is
read, when `variantKey` still holds the load constructor's value, the owner's tribe (S 0055c8b0), and is not
computed again after the stored `variantKey` is read: a conquered building of another tribe gets its
entrance cell from the new owner's tribe after a load, from the old tribe before it);
category indexes (`System::PostLoad` calls
`IndexBuilding` per building, S 00559cd0); the building mark on the map cell and the "building added"
callback (S 0055c260); all references are resolved in PostLoad; the order index is rebuilt from the order
vector (S 005625c0). Hit points: `Hitpoints::Save` writes the tag `Village Hitpoints` v0 (with a space; the
log-category object is `g_LogCategory_VillageHitpoints`) and one int, `hitpoints`;
`Load` reads the same (S 0055b7d0, S 0055b800) [known]. `maxHitpoints` and `lastRegenTick` are not stored:
they keep the constructor values (type `health`, 0), so after a load the first regeneration step is due at
once [inferred]. `maxHitpoints` is only read by the upgrade rescale; the ratio and the regeneration cap use
the type's `health` (S 0055b850, S 0055b910) [known]. Not stored either: `destroyed`.

A second writer, `Building::StoreForChecksum` S 0055c690, feeds the same fields in the same order into the
lockstep checksum (`nGame::System::ComputeChecksum` S 00784080) [known]. Differences from `StoreSavegame`:
no `VillageBuilding` tag; military, catapult and ordering are written for every type (the ordering component,
S 00563c00, with its home settlers, after the upgrade and before the hit points), although only `depot` / `casern`
types save it; soldier training and
sacrifice keep their type conditions; unique, position, ticker, depot, blocking, hit points and projectile
references go through untagged variants, the other components through their normal Store.

---

## 8. Determinism notes

**Details that matter for a byte-exact port** [known, the addresses cited]:
- The construction strokes run in float32 (one unit = 4 walks + 121 strokes of `1 / (total · 120)`), so where a phase
  ends depends on the total: for the woodcutter (frame total 1) 6.17e-7 is left after 120 strokes, so the frame phase
  uses all 121 strokes and nothing carries over; a total of 2 ends on stroke 241; totals 4, 6 and 7 end after exactly
  120·T strokes (main total 4: stroke 480, the 117th of the 4th unit, on the drop below 0); the bakery completes on
  the 119th stroke of its 4th unit. No main-phase total from 1 to 12 lands exactly on 0.0 (§3.4). "The last unit
  overshoots" holds only for some totals.
- The skip count of `RequestMaterials` after a pause: a pause after exactly 120·k strokes skips one unit fewer in
  float32 for totals 1, 2, 3, 5, 8 and 9 (bakery: `remainingB` = 0.5000005, skip 0, so 4 requests instead of 3). A
  unit the builder has taken but not finished is no longer in the site stock and is not skipped, so it is requested
  again.
- The productivity decay subtracts the double 0.05 (`FSUB` with a double operand, S 007e6d80): the result is the x87
  result rounded once to float, which a C# `float - float` does not reproduce; the decay also counts a per-entry
  counter (node +0x2c). `RegisterProductionEvent` is called unconditionally in `DeliverProducts` (S 00565990); the
  `productivity` flag only gates the reset to 0.5 at placement, so a type without it still gets an entry at its first
  cycle.
- Four good ids are literals in the executable: corn doubling 0x17626a03 (S 00663450), the wood TTL 0xCD6EC133
  (S 0077eda0), the wood/stone exclusion (S 00542a30) and `good_helper` 0x7bff15ce (S 00668e10, S 00668be0,
  S 0064d020). The remake carries them as good flags set by `core.game`'s data stage.
- One copy of the site stock serves both request lists (S 0055eb50); the removal spill keeps non-tribe refund entries at
  0; the mine start test reads `totalUnits`, so after `ClampStockToLimit` a mine could start without food entries
  (only for types with health; the shipped mines have none).

- **No random numbers** are drawn in any function read for this document [known for the functions listed in
  §11]. `Catapult.targetSeed` is a plain counter, incremented per attack and used as
  `candidates[targetSeed mod count]` ([military.md](military.md) §3.10); `SelectTarget` S 00567d20 passes it
  to the search without drawing a random number [known].
- The entrance cell of a conquered building can differ before and after a load (§7); it is not part of the
  stored state, so a game continued from a save can diverge from one that was never saved where such a
  building's door offset differs between the two tribes [inferred].
- A ware delivered during an upgrade is credited to two stocks (§3.19); a remake must reproduce it for
  identical stock counts.
- **Iteration orders that matter** [known]: buildings in placement order (vector); removal during the update
  shifts later buildings one slot forward without skipping; remains in ascending unique id; order matching by
  player index, category, bucket entry creation order, first-seen network node; stocks and good-flag maps in
  ascending good id compared as signed 32-bit ints (§2.5); cost lists in script order; `EitherGroup`
  alternatives in the owner tribe's goods-list order (§3.7); supplier candidates in category-vector order with
  strict `<` on path cost (first found wins ties).
- A stock's `totalUnits` can exceed the sum of its counts after `ClampStockToLimit` (§3.7) and is rebuilt by a
  load; the mine food test reads it (§3.8).
- A served order sets a per-category "served" byte in the iterator (S 005691c0). The byte of category 1
  makes the iterator skip category 2 for that player in the same pass (§3.12) [known] S 00569760. The other
  six bytes (+0x10, +0x12..+0x16) are only written (mark, per-player reset, constructor) and never read
  [known]: no instruction of the program addresses `OrderSystem+0x3f0..+0x3f6` directly; the iterator's
  address (`OrderSystem+0x3e0`) is taken only by the constructor, the destructor, `OrderSystem::Update` and
  `OrderSystem::FindOrderForSoldier` S 00561cb0, which pass it only to the iterator's functions; among those
  (S 00569170..S 00569840) the only byte read in +0x10..+0x16 is the +0x11 test at S 005697b5.
  `FindOrderForSoldier` (called by `Soldier::TryCompleteOrderAtCurrentPos` S 0065a340) starts with
  `NextPlayer` S 005691d0, which clears all seven bytes, and ends with `Reset` [known] S 00561cb0.
- The worker-request ticker is per building and saved; its phase depends on how many ticks the building has
  spent in the "finished" branch of `Building::Update` [known] S 0055ccd0.
- **Floating point** [known]: `remainingA/B` and `workPerStroke` are 32-bit floats, x87 arithmetic,
  truncation by `_ftol2`. Progress compares against 0 and `1 − remainingB >= 1`. Refund counts are
  `trunc(product + 0.5)` and material-skip counts `trunc(quotient)` with these values, so a remake must
  reproduce float32 stepping to get identical counts mid-construction. The military order-slot load weight
  (§3.12) is a float32 sum of `(1 / d²) / n` terms; its accumulation order is the order vector order of the
  bucket entry. Hit-point ratio and scaled limits are float divisions
  truncated to int. Production duration is a float product.
- The building state that §7 lists as stored is part of the lockstep checksum, so a divergence in it is
  detected. Not in the checksum, because not stored: `Hitpoints.lastRegenTick` and `maxHitpoints`, the
  entrance cell, `destroyed` [known] S 0055c690.
- Unique ids are allocated in creation order from one global 64-bit counter shared by all object kinds
  (`Unique::AssignNew`, counter at S 00889ad0); the stock-keeping phase `(tick + id) mod 30` (64-bit sum)
  depends on it [known] S 00563f40. Besides buildings, every settler order (`Order::ctor` S 00568b80) and every
  remains object (`Remains::ctor` S 00564210) draws one [known].
- The productivity statistics are outside the lockstep checksum: `ComputeChecksum` S 00784080 has no statistics
  section ([game-commands.md](game-commands.md) §8) [known].

---

## 9. Notes for a reimplementation

- Keep the two-stock model (input stock / output stock) and "one request object per unit". Disabling
  production moving inputs to the output stock is what makes wares flow out again.
- The settler order system and the ware request system are separate mechanisms with similar shape; do not
  merge them unless category rules (§2.6) are kept.
- Recipes hang on the product good; a building type only names its product. `EitherGroup` goods are the
  food alternatives of mines.
- Construction progress can be an integer count of strokes instead of floats **if** compatibility with
  original saves and checksums is not needed: phase length = `units × 120` strokes (+1 per unit), refund =
  units fully built in. For bit-exact saves keep float32 `remainingA/B`.
- Must be exact for original maps and saves: type ids (hex ids of `bp_create`), the size bit mask and the
  legacy remap, the store order of §7 with its version gates, direction numbering, the footprint shape of
  large buildings, the entrance flag at direction 1.
- Can be simplified: the five category vector+map pairs (any indexed container with stable insertion order),
  the `OrderIterator` object (a nested loop in the stated order), the static temporary stocks used during
  conquest.
- Levelling at placement is immediate and permanent; a paused or demolished site does not restore the terrain
  [inferred: no restore call in S 0055ed30 / S 00559db0].
- "Abort" in the function names is a pause: the site keeps its progress and resumes with command 0x2002a.
- Ownership change is destroy-and-recreate, not a field update: the new building has a new unique id, sits at
  the end of the update order and starts from defaults except for what §3.16 lists.
- The tick-counter quirk of §3.9 (51-tick search period shared by two functions) only matters for exact
  replay.
- Quirks that change simulation state and that a compatible remake keeps: production off (0x2000a) on a
  barracks with training on only empties its requests and inputs (§3.7); a soldier supplier sends its highest
  stocked level whatever the order names (§3.11); during an upgrade the builder works at the old type's
  positions (§3.4) and the arrangement treats the building as a site (§3.13); a cancel in the tick between an
  upgrade's last stroke and its completion refunds the target's full cost (§3.13).

---

## 10. Open questions

| # | question | what would settle it |
|---|---|---|
| 1 | Answered (§3.8): at start-resources level "high" the mines of a human player work without food and request none; a computer player's mines do so only at level 3 | static: S 005be330, S 00565bd0, S 005657c0, S 00565a70, S 005bea90, S 005abb60 |
| 2 | Answered (§3.2): direction 1 (the entrance flag) points to the building's bottom side, slightly left (about south-south-west) on an unrotated screen; it is not the lower-right neighbour, and neither the data names (`DoorOffsetNorthWest` = 4) nor map-format's compass labels are screen directions [live, 2026-10-14] | — |
| 3 | Answered (§3.3): `cfg_setBulldozeTime` (`GameConfig+0x14`) is never read; its setter S 0054c470 is the only access (the 593 callers of `EnsureInstance` S 0054a140 and the `StaticAccess` vtable checked), and no builder plays a levelling phase [live, 2026-10-14] | — |
| 4 | Answered (§2.2, §2.5): `System+0xbc` is an "initialised" byte (0 in the constructor and `Clear` S 00559020, 1 in `Init` S 00557610) and `Depot+0x08` a byte set at placement and transfer (S 00599cb0); both are only saved and loaded besides that and never read (every function with a byte access at +0xbc / +0x08 below S 006f0000 decompiled; no shared getter of either). `Building+0x38` (§2.3): a reserved field, written 0 by the three constructors and otherwise only saved, loaded and checksummed. A reimplementation keeps all three in the save layouts and gives them no behaviour | — |
| 5 | Answered (§3.12, §8): the served bytes of categories 0 and 2..6 are written and never read; the only reader is the category-1 test S 005697b5 | — |
| 6 | Answered (§3.9): the first animal of the cell's vector that is alive (state not 5, 7, 8, 9) and not reserved by a hunter; only it is tested for goods and exploration | — |
| 7 | Answered (§3.5, §3.4): the two messages are not posted after a countdown that started above 0 (the building is removed in the tick of the last decrement, the 300th building update after the command); a paused site never disappears by itself | static: S 005609b0, S 0055a640, S 00560890, S 0055fc10; users of `Construction +0x78` |
| 8 | Answered (§3.19): every ware delivered during an upgrade is credited twice, and the extra units stay in the finished building's input stock | static: S 0055aca0, S 00539de0, S 005671a0; live 2026-10-12 (8 of 8 deliveries) |
| 9 | Answered (§3.5): `Military.destroyCountdown` is written only by the constructor (−1, S 0055fef0), `StartDestroyCountdown` S 0055fc10, the decrement in `Military::Update` S 005609b0 and `Military::Load` S 005604d0 (every write to and address of `+0x90` below S 006f0000 decompiled; no shared setter) | — |
| 10 | Answered (§3.8): a mine gets `min(n, 8) − 1` products out of a resource cell with amount `n` | static: S 00674650, S 00674e70, S 0055c860, S 00565f80 |
| 11 | Harbours: no building type in `buildings.lua` is a harbour; harbours come from `harbors.lua` and the navy code | see [../navy-and-military.md](../navy-and-military.md) §5 and [navy.md](navy.md) |
| 12 | Answered (§3.19, §3.7): the finished tower's entries are clamped (`stoneBav 5` → 4) while the stock's `totalUnits` stays 8, because `ClampStockToLimit` writes the counts in the tree nodes only | static: S 0055b090, S 005672c0, S 0055b990, S 0055b8b0, S 0055c200 |
| 13 | Answered (§3.7): `EitherGroup` alternatives are the owner tribe's `tp_addGood` goods, in that list's order, that have a positive amount in the group's cost list | static: S 007767c0, S 00776690 |
| 14 | Answered (§3.4): "building completed" is raised only by `AdvanceWork` when `remainingA` drops below 0; the builder's `Complete` never raises it, and no in-match observer is subscribed to its list | static: S 0055eff0, S 0055ef00, S 0077fb50, S 00526ed0, callers of S 00458860 |
| 15 | Answered (§3.1): large types test 17 of the 18 cells of hex ring 3 for slope, not radius 2; medium and large types also test the 18 cells of radius 1 and 2 | static: S 0052fbe0, S 0052db50, S 0052db80, S 00600e90 |

---

## 11. Function reference

| address | name | role |
|---|---|---|
| S 0055a640 | `NVillage::System::Update` | per-tick driver: buildings, removals, remains, orders |
| S 0055a090 | `NVillage::System::PlaceBuilding` | create, register, attach entrance flag |
| S 00559db0 | `NVillage::System::RemoveBuilding` | teardown, spill, remains, flag removal |
| S 0055a7a0 | `NVillage::System::DestroyBuilding` | player demolish (countdown when attacked) |
| S 005594e0 | `Village_SpillBuildingGoodsOnRemoval` | refund and stock spill |
| S 00559940 / 00558f80 | `IndexBuilding` / `UnindexBuilding` | category lists |
| S 0055a210 / 0055a890 / 0055aac0 | `TransferBuildingOwnership` / `ConquerBuilding` / `TransferAllBuildingsOfPlayer` | ownership change |
| S 00558170 | `MarkBuildingsOutsideTerritoryNear` | territory loss marking |
| S 00558330 / 00558510 / 00557da0 | supplier searches | any good (`FindNearestSupplierWithAnyGood`: good-flag and healthy-settler tests switched by arguments) / one unit of every cost good / nearest connected (no owner test) |
| S 00557cc0 / 00559c80 / 00559cd0 | `System::Store` / `Load` / `PostLoad` | savegame |
| S 0055d980 | `NVillage::Building::ctor_Place` | construction of a placed building |
| S 0055e2f0 | `NVillage::Building::Update` | per-tick building logic |
| S 0055c400 | `Building::IsOccupied` | manned test |
| S 0055ccd0 | `Building::UpdateWorkerRequest` | worker order every 101 ticks |
| S 00527070 | `NLogic::System::Update` | order of the subsystems inside one logic tick |
| S 00557da0 | `BuildingList_FindNearestConnectedWithGood` | nearest connected finished building, good-flag test |
| S 00775480 / 0065f040 | `NLogic::Ticker::Tick` / `NSettlers::Animation::Tick` | period semantics; animation timer −1 per tick |
| S 0055bfb0 / 0055c050 / 0055ded0 | deposit / animal / mine resource search | |
| S 0055c200 / 0055c1a0 | hp-scaled stock limit / soldier capacity | |
| S 0055cd40 | `Building::GetDestroyBlockReason` | demolish availability |
| S 0055c110 | `Building::SetType` | type switch on upgrade |
| S 0055c470 / 0055d290 / 0055c690 | `StoreSavegame` / `Load` / `StoreForChecksum` | |
| S 00568040 / 00567f70 / 00567e90 | `Bulldozing::Begin` / `LevelNeighboursAndStartConstruction` / `IsGroundLevel` | ground preparation |
| S 0055efa0 | `Construction::StartWithType` | begin or complete at once |
| S 0055eb50 | `Construction::RequestMaterials` | material requests |
| S 0055e970 | `Construction::RequestBuilder` | builder order |
| S 0055eff0 / 0055eec0 / 0055ef00 | `AdvanceWork` / `OnBuildWorkDone` / `Complete` | progress |
| S 0055ed30 / 0055e510 | `AbortAndReturnGoods` / `CollectReturnedGoods` | abort, refund |
| S 0077daf0 / 0077fe70 / 0077fb50 | `NMovie::ConstructBuilding::Update` / `Construct::Start` / `Construct::Update` | the builder's side |
| S 00565bd0 / 005657c0 / 00565f80 / 00565990 | `Production::CanStartProduction` / `StartProductionCycle` / `OnProductionFinished` / `DeliverProducts` | cycle |
| S 00565a70 / 005654f0 / 00565620 / 00565ff0 | `RequestAllInputs` / `RequestMissingInput` / `AdjustInputRequest` / `SetEnabled` | input stock keeping |
| S 00565ed0 | `Production::GetProductionDuration` | cycle length |
| S 0055b8b0 / 0055b910 / 0055b970 / 0055b990 | `Hitpoints::OnChanged` / `Update` / `ApplyDamage` / `RescaleToTypeMax` | |
| S 005670c0 / 005671a0 / 00567590 / 005672c0 / 00567320 | `Upgrade::GetBlockReason` / `Start` / `Update` / `Complete` / `Cancel` | |
| S 005653d0 / 00565350 / 00565300 | `TerritoryUpdater::ActivateIfOccupied` / `Activate` / `Refresh` | territory source |
| S 00563f40 / 00563cc0 | `ai::village::BuildingOrderingComp::Update` / `SyncGoodRequests` | storage stock keeping |
| S 00564360 / 00564780 / 00564eb0 / 00564f40 / 00564520 | `SettlerSpawn` consume / update / entered / release all / accept | stored settlers |
| S 005626c0 | `NVillage::OrderSystem::Update` | settler order matching |
| S 00562280 / 00562440 / 005624f0 | `OrderSystem_FindSupplierBuilding` / `_CanBuildingSupply` / `_SpawnSettlerForOrder` | |
| S 005686a0 | `VillageOrder_GetCategory` | order category |
| S 00569840 / 00569760 / 00569430 | iterator advance / per-player step / per-category selection | `ai::village::OrderIterator` |
| S 00561e20 | `VillageOrder_LinkSettlerToDestination` | order completion |
| S 00562940 / 00562140 / 00568b80 / 00568c40 | `OrderSystem::CreateOrder` / `RemoveOrder` / `Order::ctor` / `Order::dtor` | order life cycle; the ctor draws a unique id |
| S 0055ce70 | `NVillage::Building::dtor` | teardown order of a building (§3.5) |
| S 0053ce30 / 005676d0 / 0053cdd0 / 005704c0 | `MilitaryLink_UnlinkProjectileFromTargetBuilding` / `Catapult::dtor` / `MilitaryLink_UnlinkProjectileFromCatapult` / `ProjectileOwner::ClearBuilding` | projectiles of a removed building (§3.5) |
| S 005598a0 / 00558ec0 / 00564210 | `System::CreateRemains` / `RemoveRemains` / `Remains::ctor` | remains; radius-4 invalidation; unique id |
| S 0077dcb0 / 0077dd70 / 0077dd80 | `NMovie::GoToConstructionPlace::ctor` / `Start` / `Update` | the builder's walk to the site |
| S 0055bc10 / 0055bcd0 | `OrderContainer::CancelAllOrders` / `CancelOrdersForGood` | orders of a dying target |
| S 00568f00 / 00568f90 / 00569070 / 005629c0 | `Order::Store` / `Load` / `PostLoad` / `OrderSystem::Load` | order savegame |
| S 005695b0 / 00663d90 | `OrderIterator::AddUniqueNode` / `NLogic_UniqueArray40_IsEqualAt` | one node per network |
| S 005691f0 / 00569290 | `VillageOrderBucket_SelectOldestAtNode` / `SelectLeastLoadedSoldierOrder` | selection in an entry |
| S 00568910 / 00568870 | `VillageMilitaryOrderSlot_AccumulateLoad` / `MilitaryOrderSlot::ResetLoadWeight` | load weight of §3.12 |
| S 005609b0 / 00560890 / 0055fef0 | `Military::Update` / `NotifyDestruction` / `ctor` | demolish countdown |
| S 0055b420 / 0055b470 / 0055b4d0 / 0055b620 / 0055b6a0 | `Workers::AddWorker` / `RemoveWorker` / `HasArrivedWorker` / `ReleaseAllWorkers` / `SpawnWorker` | worker slots (§3.18) |
| S 0055aca0 | `Depot::CollectGoods` | where a delivered ware lands (§3.19) |
| S 0055b020 | `Depot::AddInitialStock` | headquarters start stock |
| S 005646e0 / 00556020 / 00562e40 | `SettlerSpawn::FillDefaultSettlers` / `TribeProperty::SecondCarrierCostsContainGood` / `GoodFlags::Contains` | second carrier good |
| S 0055d4e0 | `Building::ctor_Transfer` | constructor used by ownership change |
| S 00782840 / 0055eeb0 / 00782910 | `HandleCommand_2002A` / continue helper / `HandleCommand_2002B` | continue construction, player left |
| S 006634f0 / 006630b0 / 00663390 / 006634d0 / 00663430 / 00663450 | `SacrificeModifiers` init / own effect / production factor / territory sum / miner flag / corn doubling | modifiers read by this subsystem |
| S 00567d20 / 00567a30 / 005678b0 / 0055e080 | `Catapult::SelectTarget` / `HasAmmo` / `Fire` / `Building::OnCatapultHit` | catapult (rules in military.md); `HasAmmo` reads `costs[0]` of the slot good |
| S 00558800 / 00565300 | `System::RefreshTerritoryForPlayer` / `TerritoryUpdater::Refresh` | territory radius change |
| S 0052fbe0 / 0052f460 / 00675610 | `GameQuery::CanPlaceBuildingAt` / `IsBuildingFootprintFree` / `ConstructionMap_ComputeCellFlags` | placement rules (map side) |
| S 0055ac80 / 0055ac20 | `FootprintIter::Next` / multi-cell step | footprint shape |
| S 007845a0 | `nGame::System::HandleGameCommand` | command dispatch (ids in §5.1) |
| S 00781980 / 00781150 / 00780f80 / 00781540 / 007815d0 / 007817f0 / 00782fc0 | `HandlePlaceBuilding` / `HandleDestroyBuilding` / `HandleToggleProduction` / `HandleStartUpgrade` / `HandleCancelUpgrade` / `HandleToggleGoodFlag` / `HandleAbortConstruction` | command executors (§5.1) |
| S 005579a0 / 00557d40 | `System::FindPlayerBuildingWithDefFlags` / `FindFirstBuildingOfPlayer` | first headquarters type building / first building of a player |
| S 00557a20 / 00557b60 / 005640e0 / 00561f90 / 005625c0 | `System::StoreBuildings` / `StoreRemains` / `Remains::Store` / `OrderSystem::Store` / `OrderSystem::PostLoad` | savegame (§7) |
| S 0055e720 / 0055e7a0 / 0055ad30 / 0055ada0 / 005655a0 / 005655e0 / 00566ee0 / 0055b510 / 0055b6f0 / 00562d20 / 005645b0 / 00564af0 / 00567410 / 0055b7d0 / 0055b800 | component `Store` / `Load` pairs: construction, depot, production, blocking (load), workers, good flags (store), settler spawn, upgrade (store), hit points | component layouts (§7) |
| S 0055c8b0 / 0055c260 | `Building::ctor_ForLoad` / `Building::PostLoad` | load constructor (`variantKey` = owner tribe); reference fix-up, map mark, "building added" |
| S 005407a0 / 0053fb40 / 005429c0 / 00542c40 | `Resources_FindNearestHuntableAnimal` / `FloodFillSearch::Run_HuntableAnimal` / `HuntableAnimalSearch::CanExpand` / `IsTarget` | hunt-target search (§3.9) |
| S 00540660 / 0053f940 / 00542970 / 00542d50 | `Resources_FindNearestMapResourceCell` / `FloodFillSearch::Run_MapResourceCell` / `MapResourceCellSearch::CanExpand` / `IsTarget` | mine resource search (§3.9) |
| S 0067a3b0 / 0067a030 | `NMap::Territory::RecalcAll` / `Territory_CollectSources` | territory sources recollected from the buildings (§3.14) |
| S 005691c0 / 005691d0 | `OrderIterator::MarkCategoryAssigned` / `NextPlayer` | served bytes: set, reset |
| S 0052db50 / 0052db80 / 0052db20 / 00600e90 | `HexRing3Iterator::ctor` / `Next` / `HexSpiralIterator::ctor` / `Next` | ring-3 and spiral walks of the placement test (§3.1) |
| S 00557660 / 00532280 / 005323b0 / 00538440 / 0053f840 | `Building_AttachEntranceFlag` / `MapUpdateBatch::RemoveObstructedDoodadsAtCell` / `InvalidateConstructionAroundCell2` / `Statistics::ResetBuildingProductivity` / `NResources::System::RemoveAllAnimalsAt` | placement steps (§3.2) |
| S 0055ea90 / 00526ed0 | `Construction::Update` / `IsUnderConstruction` | builder request tick; "work left" test |
| S 007767c0 / 00776690 / 00776630 / 00776780 | `PropertyGroupIter::Init` / `Next` / `Current` / `HasCurrent` | `EitherGroup` alternatives (§3.7) |
| S 00582430 / 005424c0 | `LowResResourcePosition::ctor_FromFinePos` / `AnimalAreas::AddAnimal` | animal count of the breeding test (§3.7) |
| S 005399b0 / 00546c70 / 00562dd0 | `Stock::GetCount` / tree find of the stock map / tree find of the good-flag map | signed key order (§2.5) |
| S 00565580 / 005668b0 | `Production::IsEnabled` / `SoldierTraining::IsAnyEnabled` | enabled test; a casern reads its training parts (§3.7) |
| S 00565020 / 00564c90 / 005643c0 | `SettlerSpawn::SpawnSoldierForOrder` / `TakeSettlerValue` / `CanSupplyGood` | which soldier a supplier sends, with which value (§3.11, §3.12) |
| S 0055e460 / 0055e8c0 / 0055e850 | `Construction::ctor` / `dtor` / `ReleaseBuilder` | site type at creation; site stock deleted before the builder is released (§2.4, §3.13) |
| S 0055fce0 / 005324d0 | `Military::SelectInitialSoldierKind` / `Player_CountStockedSoldiersOfClass` | soldier kind at completion (§3.4) |
| S 0055bf90 | `Building::GetConstruction` | effective construction: the upgrade's while one is active (§3.13) |
| S 00652b70 / 00586790 / 005a52c0 / 00640418 / 0063ff9f / 006240e6 | arrangement selection / AI `MilitaryMap::UpdateCell` / `StreetRouteOptimizer::ProcessEntry` / missing-goods overlay / overlay / `RefreshAvailability` | other readers of the effective construction (§3.13) |
| S 006541e0 / 00557ef0 | `GoodOrder_GetCategory` / `BuildingList_FindNearestConnected` | readers of the building's own construction (§3.13) |
