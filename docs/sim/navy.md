# Navy: ships, harbours, sea routes and expeditions

Specification of the navy simulation of *Die Siedler: Aufbruch der Kulturen* for a reimplementation.

- Binary: `sadk_noav.exe` (base `0x400000`). `S 00xxxxxx` is a static address and only evidence.
- Tags: **[known]** = read directly in the code or the data (address or file and key given); **[inferred]** =
  one step of reasoning from what is visible; **[TODO]** = open. Nothing here was observed in the running game.
- Related documents, not repeated here:
  [../navy-and-military.md](../navy-and-military.md) (attacks across water: harbour finders, sending soldiers by
  sea, the ship's military mission, sea streets and harbour ownership, founding requirements of a colony, the
  route buttons), [../map-format.md](../map-format.md) §4.15, §5.4 and §6 (the `Navy System` section byte by
  byte, harbour properties and exit geometry, placement rules, grid bits),
  [settlers-jobs.md](settlers-jobs.md) (waiting at a flag, `EnterShip` / `DisembarkAt`, the constructor job),
  [village-buildings.md](village-buildings.md) (building types, placement, construction stock),
  [military.md](military.md) (fights, soldier states), [game-commands.md](game-commands.md) (lockstep commands),
  [logic-core.md](logic-core.md) (tick, references, save stream), [../lua-surface.md](../lua-surface.md),
  [../types.md](../types.md).
- Time unit: the **logic tick** (10 per second at game speed 1, `logic-core.md`). Distances are **hex distances
  in cells** (`ai::map::MapPos::HexDistance`). A cell index is `y * mapWidth + x`.
- "Water body" and "landmass" both mean a **continent id** from `NMap::Continents` (one int per cell; water
  bodies and land regions share the id space, `../map-format.md` §5.6).

## 1. Purpose and scope

The navy subsystem (`NNavy::System`, namespaces `NNavy` and `ai::navy`) is responsible for:

- the **harbours** of a map (fixed places with water exits and docking cells), who owns them, and the flag that
  activates them;
- the **ship routes** (fixed water paths between two harbours, stored in the map) and which ships serve them;
- **ships**: creation at a ship-building site, idle behaviour, movement over water, cargo (goods packages and
  settlers), condition and sinking, deletion;
- the **ferry service** of a ship on a route whose two harbours belong to one player (the route is then also a
  street of the road network, a "sea street");
- **expeditions**: a ship on a route toward a free harbour collects a soldier and building materials, sails,
  waits for the order and founds a colony;
- the ship side of **sea attacks** (the mission state machine; the rules of the attack itself are in
  `../navy-and-military.md` §5);
- its part of the save file and of the lockstep state hash.

It is **not** responsible for: creating harbours or routes during a match (they come from the map; only the
built-in editor tools create them) [known] `../map-format.md` §6.1; the road network and package routing
(`NNet`, `NTransport`), which treat a sea street like any other street; the settler-side waiting and boarding
movies (`settlers-jobs.md`); fights (`military.md`); rendering of ships, buoys and harbour models (`S2CG::Ship`,
`S2CG::ShipRoute`, `S2CG::Harborplace`), which only read the logic state.

## 2. Data model

### 2.1 `NNavy::System` (0x68 bytes, vftable S 007eb3d0, `g_pGameSystem + 0x48`)

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x04 | `pMap` | pointer | the map system |
| +0x08 | `pOwner` | pointer | passed to the path finders as their game-query object |
| +0x0c | `initialized` | bool | set by `Init`, cleared by `Reset`; saved |
| +0x10 | `pPathfinderA` | `NNavy::AStar*` | free ship movement (§3.4) |
| +0x14 | `pPathfinderB` | `NNavy::ShipRouteAStar*` | used by the editor to draw routes; never crosses another route |
| +0x1c..+0x24 | ships | vector of `Ship*` | **creation order**; all per-tick loops walk it front to back |
| +0x28 | `shipRoutes` | `ai::navy::ShipRouteList` | vector of routes at list +0x10..+0x14 |
| +0x44 | `harbors` | `ai::navy::HarborList` | vector of `Harbor*` at list +0x10..+0x14 |
| +0x60 / +0x64 | street constructor / `StreetPlanner` | pointers | builds sea streets and the colony street; one planner for all players, each call names the player |

[known] S 005b3d70 (ctor), S 005b3360 (`Init`), struct layout in the type database.

### 2.2 Harbour: `ai::navy::Harbor` (0x58)

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x04 | `typeDesc` | `HarbourProperty*` | one of 8 facings (§6.2) |
| +0x08 | `playerIdx` | int | owner, **-1 = nobody**. Copied from the owner of the flag on the harbour cell |
| +0x18 / +0x1c | unique id | 2 × int | `NLogic::Unique` |
| +0x20 / +0x24 | `posX`, `posY` | int | the harbour cell (land). The harbour flag stands exactly here |
| +0x2c..+0x34 | exits | vector of `HarborExit*` | in direction order as stored in the map |
| +0x38 | `flagRef` | `ReferenceFlag` | the flag on the harbour cell; invalid = no flag = no owner |

`ai::navy::HarborExit` (0x40): `+0x00` owning harbour, `+0x08..+0x10` vector of `DockingPosition*` (two per
exit in all shipped data), `+0x18` `ReferenceShipRoute route` (at most one route per exit; invalid = unused
exit), `+0x38/+0x3c` the exit's water cell [known] type database, S 005bc580.

`NNavy::DockingPosition` (0x30): `+0x04` owner, `+0x08` `ReferenceShip` occupant (id at +0x18/+0x1c; invalid =
free), `+0x28/+0x2c` water cell [known] S 005bc130, S 0053c2d0.

A ship **reserves** a docking position the moment it is ordered to the harbour, not when it arrives [known]
S 005b97f0 → S 0053c2d0. Releasing it (`NavyLink_UnlinkMovementDocking` S 0053c300) clears both the position's
occupant and the ship's `targetHarbor` reference (movement +0x60) [known], so a ship whose docking position is
released has no harbour until one is set again.

### 2.3 Ship route: `ai::navy::NavyShipRoute` (0xa0)

| Offset | Field | Meaning |
|---|---|---|
| +0x10 / +0x14 | unique id | the id that the route commands carry |
| +0x18 | `harborA` (`ReferenceHarbor`) | harbour at `path[0]` |
| +0x38 | `harborB` (`ReferenceHarbor`) | harbour at `path[last]` |
| +0x58 (+0x5c..+0x60) | `ReferencesShip` | the ships **assigned** to the route, in assignment order |
| +0x68 (id hi +0x7c) | street reference | the sea street (type 3) while it exists; +0x80 = cached street pointer |
| +0x88 (+0x8c..+0x94) | path | vector of cells (8 bytes each), from A's exit to B's exit, hex-adjacent |
| +0x98 | `selfLink` | pointer to the route itself; `NavyShipRouteBackRef` methods take `route + 0x98` as `this` |

[known] type database; S 005b7120, S 005b6bb0, S 005b71d0.

Invariants of the shipped maps (path rules R1..R10) are in `../map-format.md` §6.4.

**Per player at most one ship per route** [known] `CanPlayerAssignShip` S 005b6d30: true iff the player has no
ship in the route's list **and** owns at least one end harbour. Several players can each have a ship on the
same route.

### 2.4 Ship: `NNavy::Ship` (0x50, vftable S 007eb56c)

| Offset | Field | Type | Meaning |
|---|---|---|---|
| +0x04 | `shipConfig` | `ShipConfig*` | global ship parameters (§6.1) |
| +0x08 | `player` | `Player*` | owner (first dword = player index; +0x44 = tribe id) |
| +0x10 (+0x18/+0x1c) | unique | `NLogic::Unique` | assigned by `AssignNew` at creation |
| +0x20 | `construction` | `Construction*` | §2.5 |
| +0x24 | `movement` | `Movement*` | §2.6 |
| +0x28 | `state` | int | `EShipState`, below |
| +0x2c | `stateCountdown` | int | general counter of the state machine (counts **up** in states 0..2, down in 8) |
| +0x30 | `expedition` | `Expedition*` | §2.8 |
| +0x34 | `shipNumber` | int | name index 0..20 (§3.2) |
| +0x38 | `cargo` | `NavyCargo*` | §2.7 |
| +0x3c | `condition` | `NavyCondition*` | `{ship, int condition}`; condition starts at 100 |
| +0x40 | `military` | `Military*` | §2.9 |
| +0x44..+0x4c | sinking timer | `{id, left, initial}` | `(6, sinkingTime, sinkingTime)` while sinking; `(-1, 0, 0)` from the constructors; `left` (+0x48) is the only field counted down and tested (§3.6). **Not saved** |

[known] S 005bad60, S 005baba0, S 005bb290 (the three constructors), S 005bb060 (`Store`).

All sub-objects always exist; "inactive" is a flag inside them.

`EShipState` (`Ship + 0x28`) [known] S 005bb500; names of 0..4 from the debug overlay strings (S 0061a5c0):

| Value | Name | Meaning |
|---|---|---|
| 0 | SearchShipRoute | idle, no job |
| 1 | WaitForPassengers | docked on a ferry route, waiting for work |
| 2 | Loading | docked, exchanging cargo with the harbour flag |
| 3 | Unloading | sailing to a harbour and then unloading there |
| 4 | Expedition | the expedition object drives the ship |
| 5 | MilitaryMission | the military object drives the ship |
| 6 | Sinking | sinking timer runs |
| 7 | Sunk | deleted by `System::Update` in the same tick |
| 8 | SinkScheduled | doomed; sinks as soon as it lies still and its countdown is over |

### 2.5 `NNavy::Construction` (0x58, vftable S 007eb544)

| Offset | Field | Meaning |
|---|---|---|
| +0x08 | `ReferenceSettler` | the constructor currently working on the ship |
| +0x28 | `ReferenceBuilding` | the ship-building site |
| +0x48 | `remainingWork1` (float) | second phase (planking), 1.0 → 0 |
| +0x4c | `remainingWork2` (float) | first phase (frame), 1.0 → 0; consumed **first** |
| +0x50 / +0x54 | `buildCell` | the shore cell where the constructor hammers; (-1,-1) for ships not built at a site |

A ship is **finished** iff `remainingWork1 <= 0 && remainingWork2 <= 0` [known] S 005bb500, S 0059cae0. Ships
made by `CreateShip` (script, editor, ownership transfer) start with both at 0 [known] S 005bad60.

### 2.6 `NNavy::Movement` (0xa8, vftable S 007eb4ec), derived from `NMovement::Base`

| Offset | Field | Meaning |
|---|---|---|
| +0x04 / +0x08 | `currentCell` | the ship's cell |
| +0x0c / +0x10 | `targetCell` | destination of the current move |
| +0x14 / +0x18 | `nextCell` | cell being sailed to; (-1,-1) initially |
| +0x1c | `Interpolator` | `+0x04 progress` (float, **-1.0 = not under way**, else 0..1+), `+0x08 carryOver`, `+0x0c stepRate` |
| +0x2c | `ship` | owner |
| +0x30 | `NNavy::Path` | cell list of the current move (`NMovement::PathBase`: cells vector +0x0c, `index` +0x18, `bValid` +0x1c, `bNewPath` +0x1d) |
| +0x54 | `bInterrupted` | request to stop at the next cell |
| +0x58 / +0x5c | `markedTile` | the anchorage cell this ship reserved (grid bit 0x10000); (-1,-1) = none |
| +0x60 | `targetHarbor` (`ReferenceHarbor`) | the harbour the ship is docked at or heading for; cleared with the docking reservation (S 0053c300) |
| +0x80 | `route` (`ReferenceShipRoute`) | the route the ship is assigned to; invalid = none |
| +0xa0 | `anchorSearchCooldown` | ticks until the next anchorage search (struct name `field_a0`) |
| +0xa4 | `state` | `ENavyMovementState`, below |

`ENavyMovementState` [known] S 005b99d0, S 005b97f0 (value names are ours):

| Value | Name | Meaning |
|---|---|---|
| 0 | Idle | no route |
| 1 | ToRouteEntry | has to sail to the near end of the route first |
| 2 | AlongRoute | at (or sailing to) the near end; next leg follows the stored route path |
| 3 | ToDock | following the route path; next leg goes to the docking cell |
| 4 | AtHarbor | sailing to the docking cell, or docked, or freshly assigned |

Two derived predicates are used everywhere:

- **under way** = `interpolator.progress >= 0` (the binary tests `progress > 0 || progress == 0`);
- **lying still** = not under way **and** `movement.state` is 0 or 4 [known] S 005bb500, S 005bb010, S 005b3450.

### 2.7 `ai::navy::NavyCargo` (0x30)

`+0x00` ship; `+0x04` `NTransport::PackageContainer` (vector of 0x20-byte `ReferencePackage` at +0x0c..+0x10);
`+0x1c` `ReferencesSettler` (vector of references at +0x24..+0x28) [known] S 005bca90.

The settler list holds every settler **linked** to the ship: those already aboard and those that were told to
take this ship and are still waiting or walking. A settler is **aboard** iff its movement has a valid ship
reference (id hi at movement +0x18c), no waited-at flag (id hi at +0x16c invalid) and `flagWaitState == 4`
[known] S 005b9d00.

**Capacity** [known] `NavyCargo_IsFull` S 005bcc30: full iff `package count >= shipConfig.stockLimit`. Only
goods packages count. No code path limits the number of settlers aboard [inferred: `IsFull` reads the package
vector only and no boarding function calls it].

### 2.8 `NNavy::Expedition` (0x50, vftable S 007eb424)

`+0x04` ship; `+0x08 bActive`; `+0x0c` `NVillage::OrderContainer` (the soldier order); `+0x20`
`NTransport::NeedGoods` (requests for the building materials, owner = the ship); `+0x38` `ReferencesSettler
units` (the soldiers that answered the order); `+0x4c state` [known] S 005b82e0.

`EExpeditionState`: 0 SailToStartHarbor, 2 WaitStartHarborIdle, 3 GatherCargo, 4 SailToTarget,
5 WaitingForOrders, 6 FoundColony, 7 Return, 8 WaitReturnIdle. Value 1 is not used [known] S 005b8ac0.

### 2.9 `NNavy::Military` (0x48, vftable S 007eb520)

`+0x04` ship; `+0x08 bActive`; `+0x0c` `ReferencesSettler soldiers`; `+0x20` `ReferenceFight fight`;
`+0x40 state` (0..7). The state machine is specified in `../navy-and-military.md` §5.3; it was re-read here
and matches S 005ba250 [known].

### 2.10 Properties

`ai::properties::ShipConfig` (0x30, one global object, `PropertiesDb + 0x68`): `+0x04` map tribe → speed
(float), `+0x10 size` (int), `+0x14 constructTime` (float), `+0x18 stockLimit` (int), `+0x1c waitTime` (int),
`+0x20 sinkingTime` (int), `+0x24` map tribe → expedition building type. Constructor defaults: size 1,
constructTime 50.0, stockLimit 12, waitTime 40, sinkingTime 30 [known] S 005556c0. `size` is written by the
constructor and by `sh_setSize` only (through the shared setter S 004712d0, `[ecx+0x10] = v`), so the value has
no effect [known]. Evidence: a whole-binary instruction scan that follows every `PropertiesDb` pointer (result
of `EnsureInstance` S 0054a140 or load of its global S 00889dd8) into a load of `+0x68` finds 18 loads; their
uses are the seven `sh_*` setters, `GetExpeditionBuilding` (4 callers), `GetSpeed` (2), `constructTime` +0x14
(the ship-building movie, S 0077f9c0, S 0077fa30) and the copy into `Ship.shipConfig` (+0x04) in the three ship
constructors; the `PropertiesDb` pointer is never stored outside the stack. The readers of `Ship.shipConfig`
(decompiled text of the 503 navy / ship functions) read `sinkingTime`, `waitTime`, `stockLimit` (S 005bcc30)
and the expedition building map only. A pointer spilled to a stack slot and reloaded is not followed by the
scan; the decompiled text of the navy functions covers those.

`ai::properties::HarbourProperty` (0x9c): `+0x00 id`, `+0x04 name`, `+0x20 waterStreetPosition[4][2]` (exit
offset per direction, floats), `+0x40 shipPosition[4][2][2]` (two dock offsets per direction, floats),
`+0x80 gfxName` [known] type database. Used only when a harbour is created (editor): `Harbor::CreateExits`
S 005b5850 makes one exit for each of the 4 entries whose offset is not (0,0), truncating the offsets to
int and adding them to the harbour cell, and keeps it only if it lies in the map and passes
`HarborExit::IsValid` [known]; a loaded harbour keeps its stored exits (`../map-format.md` §6.3, §6.5).

### 2.11 Grid bits the navy reads

From `GridStates` (`../map-format.md` §5.4): 0x2 street, 0x4 water, 0x8 shore, 0x20 territory border, 0x400
logic object, 0x800 dock, 0x2000 harbour, 0x4000 harbour exit, 0x8000 ship route, 0x10000 ship anchorage,
0x20000 ship ground. **Free water** = 0x4 set and 0x400 clear (`GameQuery::IsFreeWaterCell` S 0052e360) [known].

## 3. Rules and algorithms

### 3.1 Harbours

1. **Activation and ownership.** Every tick, for every harbour without a flag: if the harbour cell is not a
   territory-border cell (bit 0x20) and the territory grid gives it an owner, then (a) a flag is placed on the
   harbour cell for that player unless a flag already stands there (`Logic_PlaceFlag`), and (b) radius 1 around
   every exit that has a route is explored for that player [known] S 005b5670, S 005b61e0. Placing the flag
   links it to the harbour, which copies the flag owner into `playerIdx` and refreshes the sea street of every
   routed exit [known] S 005b49f0. The explore step runs every tick while the harbour has no flag reference.
2. **Loss.** When the flag is removed the harbour's flag reference is cleared, every docked ship **of the
   harbour's owner** is unlinked from its docking position, every ship of that owner is taken off the routes
   through the harbour's exits (expedition ships through `NavyLink_UnlinkExpeditionRoute`, which also
   deactivates the expedition; other ships through `NavyLink_UnlinkMovementRoute`), and `playerIdx` becomes -1
   [known] S 005b5370, S 005bc1c0, S 005b7050. Consequences for sea streets: `../navy-and-military.md` §4.
   The navy never removes the flag itself: the road network removes, every tick, a flag whose cell is no longer
   plain territory of its owner (a border cell counts as lost), `streets-transport.md` (`NNet::System::Update`).
   So a harbour changes hands through territory only.
3. **Docking position for a ship** (`Harbor::FindDockingPositionForShip` S 005b4a90) [known]:
   - if the ship has a route and an exit of this harbour is bound to that route: the result for that exit
     (possibly none). Otherwise (no route, **or the ship's route is not bound to any exit of this harbour**):
     the first exit (list order) that has a route and yields a position (the binary also compares the
     continent id of the ship's cell with itself, which is always true);
   - within the exit (`HarborExit::FindNearestFreeDockingPosition` S 005bc060): walk the docking positions in
     order; if an **occupied** one belongs to a ship of the same player, return none; among the free ones take
     the one nearest to the ship's cell, the first on ties (strict `<`).
   So one exit serves at most one ship per player at a time, and at most two ships in total.
   **"None" is not handled by the caller.** The only caller, `NavyLink_LinkMovementDocking` S 0053c2d0, writes
   the ship reference into `result + 8` without a null test [known, disassembly: `LEA ECX,[EAX+8]` straight
   after the call]. It is itself called from `Movement::MoveToHarbor` and from `Expedition::Finish` (§3.10,
   when the ship goes straight back on the route) [known]. A ship that is ordered to a harbour whose exit for its route already holds a ship of the
   same player, or has both docks taken by other players, or (ship without a route) a harbour without any
   routed exit, therefore writes through a null pointer; the original client crashes there [inferred]. The
   rules of the game do not produce the first case: a route takes one ship per player (every path that puts
   a ship on a route tests `CanPlayerAssignShip` S 005b6d30 or `HasPlayerEntry` S 005b6bb0: S 005b4c50,
   S 005b3450, S 00575510), every `MoveToHarbor` goes to an end of the ship's own route, and a ship that
   leaves a route releases its docking position (`Movement::ClearRoute` S 005b9340) [known]. With two
   docking positions per exit and at most the two end owners on a route, the second case does not arise
   either [inferred]. A reimplementation must still define the case (for example: do not start the move and
   retry later).
4. `Harbor::FindDockingPositionOf(ship)` returns the position reserved by that ship, or a function-static
   empty position (owner = the harbour of the first such call, no occupant, cell (-1,-1)) when the ship has
   none [known] S 005b4da0, S 005bca00. `MoveToHarbor` and `AdvanceRouteLeg` use the result unchecked; because
   they run after a successful reservation (rule 3) the empty position is not reached from there [inferred].

### 3.2 Creating and deleting ships

**Creation paths** [known]:

| Path | Function | Result |
|---|---|---|
| ship-building site | `System::CreateShipAtPlacement(player, waterCell, shoreCell)` S 005b4260 | unfinished ship on `waterCell`, `buildCell = shoreCell` (§3.3) |
| script `na_createShip(player, x, y)`, editor tool, ownership transfer | `System::CreateShip(player, cell)` S 005b42f0 | finished ship on `cell`; no check that the cell is water |

Both append the new ship to the ship vector. The constructor of a new ship works in this order [known]
S 005bad60, S 005c17f0: the movement sub-object marks the start cell as anchorage (below); the ship gets a new
unique id; `shipNumber = player.shipNames.nameIndex`, and that index advances (`nameIndex += 1; if nameIndex > 20
then nameIndex = 0`, so the names wrap after number 20); the "ship added" callback is raised. The display name
key is `"!" + tribeName + "ShipName" + shipNumber` [known] S 005bb8b0.

In `Movement::ctor` the start cell is marked as the ship's anchorage (bit 0x10000, `markedTile`) if it is inside
the map and `IsWaterCellAtPlayerCoast(cell, player, ignoreShipTile = false)` holds (§3.5) [known] S 005b9580.

In `ctor_UnderConstruction`, `Construction::SetBuildPosition` zeroes both work values at once when the
`NLogic::Edit` object (`g_pGameSystem + 0x38`) answers true on its vtable slot 1 [known] S 005ba640. Slot 1
(vftable S 007e7c28, S 00538c90) returns the byte at `Edit + 4`, the flag that slot 0
(`Edit::SetBatchEditing` S 00538a60) sets and whose clearing flushes the map modifier's pending dirty
rectangles [known]. The only `Edit` object is the one the game system's constructor creates (the vftable has
one data reference, S 00538c78 from S 00528360). The only calls of slot 0 are in the debug menu's tool handler
`nMenu::Debug::HandleToolClick` S 00604dd0, tool mode 6 (place / remove a building): it sets the flag to 1,
calls `NVillage::System::PlaceBuilding` or `RemoveBuilding`, and sets it back to 0 in the same call [known]
(whole-binary search of the getter S 00695ea0 on `g_pGameSystem` and of direct `+0x38` loads after
`g_pGameSystem`; an `Edit` pointer reached through another copied game-system pointer would not be found this
way). A ship is created only when the constructor later reaches the site (§3.3), on a later tick. A
ship-building site placed with that tool is not built at all: with the batch flag set,
`Construction::StartWithType` S 0055efa0 completes the site at placement (its `constructionTime` 500 > 0, but
batch editing wins), and neither S 0055efa0 nor `Building::ctor_Place` S 0055d980 has a ship-site case, so no
constructor comes, no ship is created and the site stands as a finished building [known]. The zeroing in
`SetBuildPosition` is therefore not reached by the shipped callers. In a free game with ships `SetBatchEditing` was not called and `Edit +4..+7` read 0
[live, 2026-10-12].

**Deletion paths** [known]: state 7 in `System::Update` (§4); `System::EraseShipByUnique` S 005b3890 (script
`na_destroyShip`, ownership transfer, the debug menu, and the destructor of a building's construction record
`NVillage::Construction::dtor` S 0055e8c0 when it still references a ship: removing a ship-building site
deletes its unfinished ship); `DeleteAllShips` S 005b3c40 on reset (last ship first). `EraseShipByUnique`
destroys the first ship in vector order with that id and closes the gap (order of the others kept); an
unknown id does nothing. `Ship::dtor` S 005baf20, in this order: raise "ship destroyed"; finish an active
military mission; destroy construction, movement, expedition, cargo, condition, military. The movement
destructor S 005b96c0, in this order: release the docking position if a harbour is referenced, take the ship
off its route if it has one (which refreshes the sea street, §3.12), stop the move if the ship is not lying
still, clear the anchorage bit [known]. The cargo destructor
(`NavyCargo::ReleaseAll` S 005bd0f0) **discards every package** (`NTransport::System::DiscardPackage`),
**removes every settler that is aboard from the game** (`NSettlers::System::RemoveSettler`) and merely unlinks
the settlers that were only assigned [known]. So everything aboard a sinking ship is lost.

**Ownership transfer** (`System::TransferShipsOfPlayer(from, to)` S 005b44e0) [known]: for each ship of `from`,
in vector order: an **unfinished** ship is deleted; a finished ship is deleted and a new finished ship is
created for `to` on the same cell (new id, new name number, no cargo, state 0, appended at the end of the
vector). Its only caller is `NLogic::System::TransferPlayerAssets` S 00529040, the Lua function
`pl_changePlayer` (`players-victory.md` §3.12) [known]. The loop goes on past the erased ship, so with
`from == to` it reaches each re-created ship again and never ends [known: the loop of S 005b44e0].

### 3.3 The ship-building site

The site is a normal building type with size flag `SizeShip` (16): `shipBuilding` / `shipBuildingEgypt`
(`buildings.lua`). Placement (ship ground 0x20000, shore, free water neighbour) is in `village-buildings.md`
§3.1; the constructor's job states are in `settlers-jobs.md`. The navy-relevant flow [known] S 0065e770,
S 0077d6c0, S 0077fa30, S 0077f9c0:

1. When the constructor first reaches the site's entrance flag cell and the site has no ship yet:
   `FindShipPlacement(origin = building cell, radius = type.workingRadius, player)` S 005b4370 runs a
   breadth-first flood fill (§8) from the building cell over **walkable** cells within `radius` (hex distance
   to the origin). The first visited cell that has the shore bit 0x8, lies on the origin's continent and has a
   neighbour water cell with `IsWaterCellAtPlayerCoast(nb, player, false)` is the goal: `shoreCell` = that
   cell, `waterCell` = the first such neighbour in this ring order: the neighbour in direction 4 first, then
   the cells reached from it by one step in each of the directions 0, 1, 2, 3, 4 in turn (S 005bbd10; the
   same ring as the flood fill of §8 but starting one cell earlier). The origin itself is tested first.
2. No goal: message `!No Place for Ship found!` (kind 6) to the owner and the site is removed.
3. Else the ship is created unfinished on `waterCell` and linked to the constructor and the site.
4. Work loop of the constructor (`NMovie::ConstructShip::Update` S 0077d6c0, movie steps in brackets), repeated
   while the ship is unfinished:
   a. (step 7) if the site's `construction.aborted` (building +0x44 → +0x78) is set → stop;
   b. (step 7) if the construction's stock (`NLogic::Stock` at construction +0x10) has no entry at all (its
      entry count, construction +0x20, is 0) → wait (`BeNervous`, step 13) and retry;
   c. (step 7) otherwise `Stock::RemoveOne` on the first good of the list `frameCost ++ cost` and create the
      carried package of that good (`NTransport::System::CreateCarriedPackage`), **whether or not the stock
      holds that good**: step b only tests that the stock is not empty [known]. With the shipped data the frame
      and the main cost are one good (planks, or wood for `shipBuildingEgypt`), so the stock holds nothing else
      [inferred]. Then carry the package to `buildCell` (step 2) and drop it (step 19). Here and in §3.10
      `a ++ b` is `GoodAmountList_AddList` S 00552bb0: a copy of `a` to which every entry of `b` is added, an
      entry of a good that is already in the list raising that entry's amount, a new good being appended; so the
      first good is always the first good of `frameCost`, whatever the stock holds [known]. Step 7 and the end
      of step 10 (d below) both set the byte +0x70 of the object at settler +0x50 to 1 [known]; its purpose is
      [TODO] not established (§10);
   d. (step 10) hammer (`NMovie::ShipConstruct`): `strokes = (int)constructTime` (truncated);
      `n` = total good count of `frameCost` if `1 − remainingWork2 < 1` (the test of `ShipConstruct::Start`
      S 0077fa30 [known]; it differs from `remainingWork2 > 0` only for a remainder so small that
      `1 − remainingWork2` rounds to 1 [inferred]), else of `cost`;
      `workPerStroke = 1 / (n * constructTime)`. One stroke per tick for `strokes` ticks, and **one more**
      portion on the tick the movie ends, so a visit adds `(strokes + 1) * workPerStroke`. The stroke is
      counted per call of the movie's `Update`, not per animation: the hammer animation (kind 4, length
      `constructTime`) is only restarted when its timer has run out and gates nothing [known] S 0077f9c0;
      that the movie is updated once per logic tick is stated in `settlers-jobs.md` §3.9;
   e. `Construction::AddWork(amount)` S 005ba450: subtract from `remainingWork2` while it is `> 0`, otherwise
      from `remainingWork1`; clamp at 0. Work is not carried from one phase into the other;
   f. (step 24) walk back to the entrance flag cell; then step 7 again while work remains.
5. When both values are `<= 0`: message `!Ship constructed` (kind 6, with the ship's name key and cell), the
   site is unlinked from the ship and **removed** (`NVillage::System::RemoveBuilding`). A ship-building site
   builds exactly one ship.

With the shipped values (`sh_setConstructTime(30)`; `shipBuilding` frame 4 planks, cost 8 planks;
`shipBuildingEgypt` 4 and 8 wood; `bp_setWorkingRadius` 1 for both): a visit adds 31/120 in the frame
phase and 31/240 in the main phase, so the ship needs 4 + 8 = 12 visits and 12 goods [inferred from the
formulas, `ship.lua` and `buildings.lua`].

While unfinished, `Ship::Update` does nothing at all (no movement, no condition) [known] S 005bb500.

### 3.4 Movement

**Speed.** `speed = ShipConfig.speed[tribe of the owner] * sacrificeFactor` where the factor is the owner's
effective sacrifice modifier index 9 (`SacrificeModifiers::GetShipSpeed` S 006632d0, reached through
`Movement` vtable slot 10, S 005b93b0) [known]. Unit: cells per tick. The factor is
`effective[9] = ownBonus[9] / hostileDivisor[9]`: an own `Effect_ShipSpeed` (effect type 9) sets
`ownBonus[9] = max(ownBonus[9], value / 100)`, a hostile one sets `hostileDivisor[9] = max(hostileDivisor[9],
value)` [known] S 006630b0, S 006631e0. With the shipped values (200 for the owner, 2 on enemies) a ship is
twice as fast or half as fast; both at once give 1.0. The modifier block, its start values and its life
cycle: `properties-data.md` (sacrifice effects), `military.md`.

**One step** (`NMovement::Base`) [known] S 007728d0, S 00772950, S 00774a10:

```
BeginStep(next):   progress = carryOver
                   nextCell = next;  d = HexDistance(next, currentCell)
                   if d == 0: return false
                   stepRate = 1 / (d / speed)            // speed is read here, once per cell
Update (per tick, only while progress >= 0):
                   progress += stepRate
                   if progress >= 1.0: carryOver = progress - 1.0    // inside Advance (S 00774a10)
                   if progress > 1.0:
                       currentCell = nextCell;  path.bNewPath = 0
                       if path.bValid and path.index != 0 and not bInterrupted:
                           next = path.cells[--path.index];  BeginStep(next)
                       else:
                           progress = -1.0; carryOver = 0;  path is cleared (stop)
```

The path is stored **reversed**: `index` starts at `count - 1` (the current cell) and is decremented [known]
S 00772c50, S 00772e20. Consecutive path cells are neighbours, so `d = 1` and a ship advances `speed` cells per
tick with the fraction carried over; a ship changes cell when `progress` exceeds 1.0 strictly.

`StartMoveTo(target)` S 00772b00: nothing if already there; else build the path (clears `bInterrupted`); if it
has cells: `progress = carryOver = 0`, `targetCell = target`, begin the first step with a non-zero distance;
if no path was found: stop [known].

**Path source** (`NNavy::Path::FindPath` S 005bdb30) [known]:
- `movement.state == 3`: the sub-sequence of the route's stored path between the two cells, inclusive
  (`MapPosVector_ExtractSegment` S 005bd900). The function always reports success. If the ship's cell is
  **not** on the stored path, the result is the stored path from the target cell to the path's end (when the
  target comes first in the vector, as `path[1]` does) [known];
- otherwise A* with `pPathfinderA` (`AStar::FindPath(from, to, 0)`), and on success
  `BuildPathReversed(randomize = true)`; a failed search yields no path.

**Ship A\*** (`NNavy::AStar`, vftable S 007eb5a8) [known]: the search core, its tie-breaking and the way the
path is read back are the shared `NMap::AStar` of `map-resources.md` §3.12 (search from the target towards the
start, neighbours in direction order 0..5, open list sorted by `g + HexDistance`, first in first out among
equals, stop the moment the start is reached). The navy supplies two virtuals:

- slot 0, the search precondition (S 005bbbe0, named `CanTraverse` in the map): the start cell and the target
  cell have the same continent id **and the target cell is free water**; otherwise no search runs and there is
  no path. It is asked once per search for the two ends, not per step;
- slot 1, the step cost (S 005bba90): -1 (forbidden) unless `b` is free water, else the table below.

Because the path is read back with `randomize = true`, **every ship A\* path longer than one step draws from
the simulation random generator**: once for the start direction and once at every cell where the current
direction stops descending (`NMap::AStar::BuildPath` S 00676d10, `map-resources.md` §3.12) [known]
S 005bdb30. Among equally good cells the ship's course is therefore random, and the draw count is part of the
lockstep state (§8). Stored route segments draw nothing.

Step cost of entering `b`:

| Condition on `b` (first match) | Cost |
|---|---|
| dock bit 0x800, or both exit 0x4000 and route 0x8000 | 12 |
| any of the 6 neighbours inside the map is not water, or has 0x800, or has 0x400, or lies on the map edge | 2 |
| else | 1 |

The neighbour walk of S 005bba90 steps once in direction 4 and then, for each direction 0..5, steps first and
tests the cell it reached (so the direction-4 neighbour is tested last); neighbours outside the map are skipped,
and "on the map edge" is `MapPos_IsOnMapEdge` S 005bba60 (x or y is 0 or the size minus 1) [known]. The order
does not change the cost.

`ShipRouteAStar` (vftable S 007eb598; editor route drawing) additionally forbids cells with 0x8000 in its
step cost and otherwise returns the ship cost above; its slot 0 is a thunk to the same precondition
[known] S 005bb9d0, S 005bb9a0.

**When no path is found** [known] (S 00772b00, S 005bb500, S 005b99d0, S 005bdb30, S 005bd900, S 00772c50,
S 005436d0, S 007728d0):

- `StartMoveTo` stops the ship and returns false; nobody tests the result. `targetCell` keeps its old value.
- Direct move to a dock (`MoveToHarbor` with movement state 4): the ship stays where it is with movement state
  4, so it **lies still** and counts as arrived. Its docking position stays reserved, and the ship state
  machine goes on as if the ship were docked: `UnloadStep`, `LoadAtHarbor` and `HasPendingCargoFor` use
  `targetHarbor` and never compare the ship's cell with the docking cell (S 005bd4e0, S 005bcfa0, S 005bb420).
  Such a ship exchanges cargo with the harbour flag from a distance.
- Move to the route entry (movement state 1 → 2, A*): the ship stops with movement state 2, which is neither
  under way nor lying still. On the next tick `Movement::Update` calls `AdvanceRouteLeg` again; state 2 → 3
  asks for `path[1]` (the ship is not there), and the path source is now the stored route. With the ship's
  cell not on the route the path is `path[1] .. path[n-1]`, read from its far end: the first step goes from
  the ship's cell **straight to `path[n-2]`** as one step of `d = HexDistance` cells (`stepRate = speed / d`,
  no test of the cells in between), then along the route back to `path[1]`, then A* to the reserved dock.
  A ship that cannot reach the route by water therefore crosses land in a straight line. The one way into
  this sequence is an idle ship that takes an own-to-own route on another water body (§3.8).

**Sailing to a harbour** (`Movement::MoveToHarbor(h)` S 005b97f0) [known]:
1. `state = 4`. If the ship has a valid `targetHarbor` reference: if it is a **different** harbour, `state = 1`;
   release the old docking position.
2. `targetHarbor = h`; reserve a docking position at `h` (§3.1).
3. If the ship already stands on the docking cell → done (returns true).
4. If `state == 1` → `AdvanceRouteLeg`; else `StartMoveTo(docking cell)` (plain A*).

**Route legs** (`Movement::AdvanceRouteLeg` S 005b99d0) [known]; `path` is the route's path with `n` cells:

| State on entry | Action |
|---|---|
| 1 | `state = 2`. If `HexDistance(path[0], cur) < HexDistance(path[n-1], cur)`: go to `path[1]`; else go to `path[n-2]` (A*, because the state is now 2) |
| 2 | `state = 3`. If `cur != path[1]`: go to `path[1]`; else go to `path[n-2]`. The path of this move is the stored route segment |
| 3 | `state = 4`. Go to the docking cell reserved at `targetHarbor` (A*) |
| 0, 4 | nothing |

"Go to" is `MoveToWaypoint` S 005b92a0: if the ship is already there it returns without moving, and the next
tick's `Movement::Update` advances to the next leg. So a crossing is: A* to the second cell of the nearer route
end, the stored route path to the second cell from the other end, A* to the dock. On an exact distance tie in
state 1 the far-end branch (`path[n-2]`) is taken.

`SailToOppositeRouteEnd` S 005b9990: `MoveToHarbor(B if targetHarbor is A, else A)` [known].

**`Movement::Update`** (per tick, finished ships only) S 005b9b90 [known]:

```
if under way:
    if markedTile == none and route invalid: bInterrupted = 1
    Base::Update()
    return
if route valid:
    if bInterrupted: state = 4
    if state != 4: AdvanceRouteLeg()
    return
# no route, lying still
if markedTile != none:
    if (tick + uniqueId) % 111 == 0 and not IsWaterCellAtPlayerCoast(currentCell, player, ignoreShipTile = true):
        clear the anchorage bit; markedTile = none; anchorSearchCooldown = 0
    if markedTile != none: return
if anchorSearchCooldown != 0: anchorSearchCooldown -= 1; return
cell = FloodSearchShipTile(currentCell, radius 30, player)        # §3.5
if cell found: MarkTileAndMoveTo(cell)
anchorSearchCooldown = 100
```

The modulo uses the 64-bit sum of the tick counter and the ship's unique id. `bInterrupted` is **not** cleared
when it turns the state to 4; it is cleared only when the next path is built [known] S 005b9670.

`SetRoute(route)` S 005b92e0: store the reference, release the anchorage (clear bit, `markedTile = none`),
`state = 4`. `ClearRoute` S 005b9340: clear the route reference, release the docking position if a harbour is
referenced, `anchorSearchCooldown = 0`, set `bInterrupted` if the ship is not lying still, `state = 0` [known].

While the ship changes cell, `Ship::Update` explores radius 3 around the new cell for the owner if anything
there is unexplored [known] S 005bb500.

### 3.5 Anchorage

`GameQuery::IsWaterCellAtPlayerCoast(cell, player, ignoreShipTile)` S 0052f0c0 [known]: the cell has the water
bit 0x4, no street bit 0x2, and (unless `ignoreShipTile`) no anchorage bit 0x10000; and one of its 6 neighbours
inside the map has the shore bit 0x8 without the border bit 0x20, is owned by `player` in the territory grid,
and `player` owns, on that neighbour's continent, a **building whose territory source is active**
(`GameQuery_IsMilitaryBuildingOnContinent` S 00534000: it walks the village system's list of buildings whose
type has `territoryBuilding` (vector at `NVillage::System + 0x3c`, filled by `IndexBuilding` S 00559940 from
property byte +0xf5) and takes one of `player` whose `territoryUpdater.bActive` (building +0xc4 → +8) is set
and whose cell has the same continent id; nothing else of the building is tested. When that flag is set:
`village-buildings.md`, `TerritoryUpdater`). The neighbours are tested in the ring order of §3.3 step 1: the
direction-4 neighbour first, then the cell reached after each step in directions 0..4 [known].

`System::FloodSearchShipTile(origin, radius, player)` S 005b4430 [known]: breadth-first flood fill (§8) from
the ship's cell over free water cells within `radius` of the origin; the first cell with
`IsWaterCellAtPlayerCoast(cell, player, false)` wins (the origin is tested first). Result (-1,-1) if none.

`MarkTileAndMoveTo(cell)` S 005b98a0: set `markedTile`, set bit 0x10000 on it, then start moving there. The
reservation exists from the moment of the decision, so two ships never choose the same anchorage [known].

### 3.6 Condition and sinking

`ai::navy::NavyCondition::Update` S 005bdc30, called once per tick **only while the ship lies still and is not in state
8** [known]:

```
if markedTile == none and route invalid: condition -= 1
else if condition < 100:                 condition += 1
```

If `condition < 1` afterwards → `BeginSinking`. A ship with neither anchorage nor route that lies still for 100
ticks sinks; in practice that is a ship whose owner has no reachable coast within 30 cells [inferred].

`BeginSinking` S 005bb010 [known]: `condition = -100`; if lying still: `state = 6`, sinking timer =
`sinkingTime`; else `bInterrupted = 1` (it is retried on the next still tick because the condition stays
negative).

States 6 and 7 (top of `Ship::Update`) [known] S 005bb500, S 00775fd0, S 00775ff0: if the timer id is not -1,
`left -= 1`, and at `left < 1` the id becomes -1 and `left` 0 (the third field, the initial count at +0x4c, is
written only by `BeginSinking` and never read here); then, if `left < 1` → `state = 7`. So state 7 is reached on
the `sinkingTime`-th update after `BeginSinking` (on the first update if `sinkingTime < 2`; `BeginSinking`
itself only sets state 6). `System::Update` deletes a ship in state 7 right after its update.

`ScheduleSinking` S 005bb210 (sacrifice effect "destroy ships", `Sacrifice::ApplySinkTargetShips` S 00660360,
applied to every **finished** ship of the target player): `state = 8`, `stateCountdown = 30`, `bInterrupted`
if not lying still. `ScheduleSinkingNoDelay` S 005bb250 (script `na_sinkShipOnRoute`, skipped for ships already
in state 6, 7 or 8): the same with countdown 0. In state 8, on each still tick: `stateCountdown -= 1`; at `< 1`
→ `BeginSinking` [known]. State 8 freezes all jobs: no expedition, mission or cargo step runs.

### 3.7 `Ship::Update`: the state machine

Per tick, per ship, in vector order (S 005bb500) [known]:

```
if state in {6, 7}: sinking timer (§3.6); return
if not finished: return
if route invalid and state not in {0, 8}:
    cargo.UnassignPendingSettlers()            # linked but not aboard → unlinked
    if expedition.bActive: expedition.ReleaseAndDeactivate()
    if military.bActive:   military.Finish()
    state = 0
prev = movement.currentCell
movement.Update()                               # §3.4
if not lying still:
    if currentCell != prev and something unexplored within 3: explore radius 3 for the owner
    if state == 3 and (tick + uniqueId) % 11 == 0: cargo.AssignWaitingSettlers()
    return
if state == 8: countdown / BeginSinking (§3.6); return
condition update (§3.6); if condition < 1: BeginSinking; return
switch state: (table below)
```

| State | Per still tick |
|---|---|
| 0 | `expedition.bActive` → state 4. Else `military.bActive` → state 5. Else, only if the ship has an anchorage: `cargo.DisembarkOneSettler()`; then if `stateCountdown > 100`: `stateCountdown = 0`, `ReturnToOwnHarbor()` (§3.8); else `stateCountdown += 1` |
| 1 | if `stateCountdown < 101`: `stateCountdown += 1`. Else `stateCountdown = 0`; `here = targetHarbor`, `there = route.opposite(here)`; if `HasPendingCargoFor(here.flag, there.flag)` or the cargo is not empty → state 2; else if `HasPendingCargoFor(there.flag, here.flag)` → `MoveToHarbor(there)`, state 3 |
| 2 | `worked = cargo.LoadAtHarbor()`; if not worked: `worked = cargo.UnloadOnePackage(throttled)`. If worked → stay. Else if `stateCountdown <= waitTime`: add `waitTime + 1` if the cargo is full, else 1. Else: cargo not empty → `SailToOppositeRouteEnd()`, state 3; cargo empty → state 1 |
| 3 | `cargo.UnloadStep()`; when it returns false → state 1, `stateCountdown = 100` |
| 4 | `expedition.Update()`; when it returns true → state 1 if the ship still has a route, else 0 |
| 5 | `military.Update()`; when it returns true → state 0 and `ReturnToOwnHarbor()` |

`HasPendingCargoFor(flagA, flagB)` S 005bb420 [known]: true iff a settler in flagA's waiting list has flagB's
cell as its next flag (settler movement +0x140/+0x144), or a package on flagA's stacks is flagged for
transport (package +0x25) and its next waypoint is flagB's cell.

"Cargo empty" (`ai::navy::NavyCargo::IsEmpty` S 005bcc60) = no package and no settler **aboard** [known].

Timing notes [inferred from the code above]: `LoadAtHarbor` reports "worked" on the two of three ticks it
skips (below), so in state 2 `stateCountdown` advances on every third tick only, and only on phase ticks on
which nothing was loaded or unloaded. A phase tick with work does **not** reset the count, so the wait is the
**total** number of idle phase ticks since state 2 was entered, not a time since the last load: with `waitTime`
15 (the value `ship.lua` sets; the constructor's 40 is never in use) and a hold that is not full, the ship
leaves (or returns to state 1) on the 17th idle phase tick, 49 to 55 ticks after its first call when there is
nothing to load [known: live 2026-10-12, 38 of 39 such stays with exactly 17 idle phase ticks] (16
increments from 0, then the test `stateCountdown <= waitTime` fails); a full hold adds 16 at once and leaves on
the next idle phase tick. `stateCountdown` is not reset when state 2 is entered from state 1 (it is 0 there)
nor when state 1 is entered from state 2 (it is then `> waitTime`; state 1 needs `101 - stateCountdown` more
increments, one per still tick, and runs its check on the still tick after the last of them; entered from
state 3 with 100 that is the second still tick).

### 3.8 Idle ships take up ferry service

`Ship::ReturnToOwnHarbor` S 005bab60 [known]:
1. `HarborList::FindNearestHomeHarborForShip(ship)` S 005b6370: among harbours owned by the ship's player for
   which `Harbor::FindOwnRouteForShip` finds a route, the one whose exit for that route is nearest to the
   ship's cell (first in harbour-list order on ties).
2. `FindOwnRouteForShip` S 005b4c50: the first exit (in order) whose route has **both ends owned by the
   player** and passes `CanPlayerAssignShip` (the player has no ship on it yet). The binary's "same water
   body" test compares the continent id of the ship's cell with itself and is always true [known]; so a ship
   may pick a route on another water body. Its A* to the dock is then refused (§3.4, slot 0), it stays where
   it is and serves the route from there: state 3 → 1 → 2 as if docked (one stay), and its first crossing
   follows the "no path" sequence of §3.4 [known].
3. If found: link the ship to the route (`NavyLink_LinkMovementRoute`: `SetRoute`, add to the route's ship
   list, which creates the sea street), `MoveToHarbor(harbour)`, `state = 3`.

It is called from state 0 every 102nd still tick (anchored ships only) and when a military mission ends.
There is no player command that puts a ship on an own-to-own route: the "assign ship" command refuses such
routes (§5.1) and idle ships serve them by themselves.

### 3.9 Cargo operations

All of these use phase tests `(tick + shipUniqueId) % N` (64-bit sum) [known].

**`AssignWaitingSettlers`** S 005bd270: for each settler in the waiting list of the current harbour's flag
(a copy is iterated): if its next flag is the opposite harbour's cell and it has no ship yet, link it to this
ship (it joins the cargo's settler list, not yet aboard).

**`LoadAtHarbor`** S 005bd4e0, returns "worked":
1. If `(tick + id) % 3 != 0` → return true (no work done).
2. `AssignWaitingSettlers()`.
3. A **copy** of the harbour flag's waiting list (`Flag +0x188` `waitingSettlers`, `streets-transport.md`
   §2.2), in order: every settler bound for the opposite harbour sets `worked`; the **first** such settler whose
   `flagWaitState` is 2 or 7 boards (`SettlerMovement::EnterShip(ship, true)`) and the scan stops.
4. The **same** list again, now the live one (after the boarding of step 3 took that settler out of it): every
   settler bound for the opposite harbour sets `worked`; the first one that is not moving (interpolator
   `progress < 0`), holds a parking cell and has `flagWaitState` 2, 3 or 7 is called out of its parking place
   (`SettlerMovement::RecallFromParkingCell` S 00657330: parking cell released, state 2 → 7) and the scan stops.
   Step 4 runs whether or not step 3 boarded somebody. One settler boards and one is called out per call.
5. Packages on the flag's active stacks, in stack-iterator order, with `pending = 0`. The iterator
   (`NNet_FlagPackageStacks_IterNext` S 0066cdd0) keeps an index per stack: loading a package removes it from
   its stack, the next package moves into its slot, and the iterator's next step passes over that package
   [known]; it is seen again only on a later call.
   - stop if the cargo is full and no package aboard can be unloaded here
     (`HasPackageForCurrentHarbor` S 005bce30);
   - a package that is flagged for transport (+0x25), lies on the flag (+0x70) and has the opposite harbour's
     cell as next waypoint is loaded (`Transport_LoadPackageIntoHolder` S 0064cd60); `worked = true`; then
     `UnloadOnePackage(unthrottled)`: if nothing was unloaded `pending += 1`; if `pending == 0` → return
     (one exchange per call).
   After the loop, call `UnloadOnePackage(unthrottled)` `pending` more times.
   A ship with nothing to unload loads until `stockLimit` in one call. The full-hold stop only applies when no
   package aboard is *addressed* to this harbour; whether the flag can take it is not asked. So while such a
   package is aboard and the flag's stacks refuse it, every matching package of the flag is still loaded and
   the hold can exceed `stockLimit` by more than one [inferred from the loop; no other bound is visible].
   Within one call the bound is the number of matching packages lying on the flag (the flag's 6 stacks,
   `streets-transport.md`) [inferred]; across stays there is none: packages that are not unloaded stay aboard
   and every stay adds more. A ferry with `stockLimit` 12 carried 13 packages and then more at each of 53
   consecutive stays, 39 after 16,800 ticks, still growing [known: live 2026-10-12].

**`UnloadOnePackage(throttled)`** S 005bcea0: if `throttled` and `(tick + id) % 3 != 0` → return "packages
aboard?". Else the first package aboard that is untargeted or targeted at the current harbour's cell
(`Package::IsUntargetedOrAtPosition`) **and** that the harbour flag's stacks can take is handed to the flag
(`NTransport::System::UnloadPackageFromCargo`) → true; none → false. "Can take" is the negation of
`FlagPackageStacks::CannotTakePackage` S 0066b970 [known]: walking the flag's 6 stacks in order, the flag
takes the package as soon as a stack is empty, or already holds this package, or a **second** stack that
accepts it is found; it refuses only when all 6 stacks are in use, none holds the package and at most one
accepts it (the last accepting stack is kept in reserve). What one stack accepts: `streets-transport.md`.

**`UnloadStep`** S 005bcfa0: if `(tick + id) % 3 != 0` → return "any package or linked settler?". Else the
first settler aboard that is homeless (settler state 3) or whose next flag is the current harbour's cell
disembarks (`DisembarkAt`) → true; else `UnloadOnePackage(throttled)`.

**`DisembarkOneSettler(out)`** S 005bcd10 (idle ships, military mission): if `(tick + id) % 5 != 0` → return
"any linked settler?". Else the first settler aboard disembarks regardless of its destination (its movement
is aborted with `ai::settlers::SettlerMovement::Abort`, it is unlinked from the cargo, then `DisembarkAt`) → true; none →
false.

**`UnassignPendingSettlers`** S 005bd3b0: unlink every settler that references this ship and is not aboard.

**Where a disembarking settler appears** (`SettlerMovement::DisembarkAt(ship)` S 00657d90) [known]: its
street mode and `flagWaitState` are cleared; then
- the ship references a harbour (`targetHarbor` valid): the settler is put on the cell returned by slot 0 of
  the vtable of the movement's owner object, called with the ship [known]. That slot is S 006567b0, which
  returns `targetHarbor.pos`, the **harbour cell** [inferred: S 006567b0 computes exactly this from a ship and
  has no direct caller; the vtable was not read. Settle by reading slot 0 of the vtable at
  `*(SettlerMovement.owner)`]; whatever stands there and wherever the ship lies;
  if it was walking a street route before boarding, the route is restarted from there;
- no harbour (idle ship at an anchorage, military mission away from a harbour): the first walkable in-map
  cell among the 6 neighbours of the ship's cell, in the ring order "direction-4 neighbour, then one step in
  each of the directions 0..4"; if none is walkable the settler is not placed at all (it keeps its old
  position and is no longer aboard) [known as read].

With a harbour the street route restarts through `StartMode2_From128` S 00772f90 (`holdStep = 0`, the rough
mover's current cell = the settler's cell, path mode 2) and `AdvanceStreetRoute` S 00657b80, not through
`StartStreetMoveTo`: the route target is kept and nothing is stopped first (`settlers-jobs.md` §3.8.6).

A homeless passenger (settler state 3) continues with the going-home rules of `settlers-jobs.md` §3.4; the
parking call-out of `LoadAtHarbor` step 4 is `RecallFromParkingCell` S 00657330 (parking cell := (-1,-1),
`flagWaitState` 2 → 7). Boarding (`EnterShip`) and the settler-side unlinks are in `settlers-jobs.md` §3.8.6.
Waiting at a harbour flag draws one random number per settler for its parking spot
(`FlagParking::FindFreeSpot`, `streets-transport.md`).

### 3.10 Assigning a ship to a route: expeditions

**Block reasons** (`NavyShipRouteBackRef::GetAssignShipBlockReason(player)` S 005ba970) [known], first match:

| Code | Cause |
|---|---|
| 2 | the player owns both end harbours |
| 1 | the player owns neither end |
| 4 | `CanPlayerAssignShip` false (the player already has a ship on the route) |
| 3 | no idle ship (below) |
| 0 | allowed |

**Nearest idle ship** (`System::FindNearestIdleShipAtHarborExit(player, exitCell)` S 005b3450) [known]: the
exit's route must pass `CanPlayerAssignShip`; candidates are ships of the player that are finished, have no
route, lie still, **hold an anchorage** and stand in the same water body as `exitCell`; the nearest by hex
distance wins (limit 100000, first in ship-vector order on ties). `AssignNearestIdleShip` uses
`exitCell = route.path[0]` (harbour A's exit), whichever end the player owns [known] S 005ba720.

**Assigning** (`Navy_AssignShipToRoute` S 0053c010) [known], in this order: add the ship to the route's list (which
may create the sea street), `Movement::SetRoute`, `expedition.state = 0`, `expedition.bActive = 1`. On its next
still tick the ship goes from state 0 to 4.

**`Expedition::Update`** S 005b8ac0, called on still ticks in ship state 4; returns true when the expedition
is over [known]:

Before the switch, unless the state is 7 or 8: if both route ends now belong to the player → state 7.

| State | Action |
|---|---|
| 0 | `MoveToHarbor(ChooseStartHarbor())` → 2 |
| 2 | `cargo.UnloadStep()`; when false → 3 |
| 3 | `GatherCargo()` (below); when true → `SailToOppositeRouteEnd()` → 4 |
| 4 | explore radius 10 around the target harbour's cell for the owner. Harbour unowned → message `!Ship waiting for Orders` → 5. Owned → `!Harbor is already captured!` → 7 |
| 5 | wait. If the harbour got an owner → `!Harbor is already captured!` → 7 |
| 6 | if the harbour has an owner → back to 5 without a message (state 5 reports `!Harbor is already captured!` on its next run). Else found the colony (below); no building position → `!No Valid Position for Building found!` → 7 |
| 7 | `ReleaseUnitsAndOrders()`; `MoveToHarbor(ChooseStartHarbor())` → 8 |
| 8 | `cargo.UnloadStep()`; when false → `Finish()`, return true |

Messages are player messages of kind 6 with the ship's name key and cell.

`ChooseStartHarbor` S 005b7b80: the route end owned by the player (end A checked first); if both are owned,
the end whose exit is nearer to the ship (end B on ties) [known]. If the player owns neither end the result
is null and `MoveToHarbor` is called with it unchecked [known]. The case is not reached in the original:
losing a harbour takes the owner's ships off its routes and deactivates their expeditions in the same call
(§3.1 rule 2), and a ship without a route drops its expedition at the top of `Ship::Update` (§3.7), so
`Expedition::Update` never runs with a player who owns neither end [inferred]. Guard it anyway.

**`GatherCargo`** S 005b8470, once per still tick in state 3; returns "ready" [known]:

1. Soldier.
   - No unit yet and nobody linked to the cargo: if the expedition has no open order, create a settler order
     for the tribe's basic soldier type (`MilitaryConfig::GetSoldierId(tribe, 0, 0)`) and link it to the ship
     (`NVillage::OrderSystem::CreateOrder`, `OrderLink_LinkShip`). If an order is open, every 1000 ticks
     (`(tick + id) % 1000 == 0`) ask `OrderSystem::GetSupplyStatus` for that soldier type at the harbour flag:
     1 → message `!Harbor is not Connected`, 2 → `!No Soldier for Expedition found` (each only if no such
     message is already pending near the ship).
   - No unit yet but settlers are linked to the cargo: each becomes a unit of the expedition (settler ship
     reference at settler +0xf8, expedition `units`).
   - Units exist, nobody linked to the cargo: every settler in the harbour flag's waiting list whose ship
     reference is this ship is linked to the cargo and boards (`EnterShip`, then `ai::settlers::SettlerMovement::Abort`).
   - Units exist and somebody is linked to the cargo: `ready = true`.
2. Materials. `missing` = `frameCost ++ cost` of the tribe's expedition building, minus one per package aboard (by
   good type; `RemoveAmount` S 005525b0 replaces an entry that reaches 0 with the list's last entry, so the order of
   the remaining entries changes). If `missing` is not empty: `ready = false`; subtract the open `NeedGoods`
   requests; if nothing is left to request, load every package on the harbour flag that is flagged for transport,
   lies on the flag, has a valid target and whose target is this ship (and cancel its request); otherwise add
   requests for the remainder (`NeedGoods::AddRequests`).

How the order finds a soldier and how the requests are served belong to the village order system and the
transport system (`village-buildings.md` §3.12; a goods request whose target is a ship is need category 1 in
`streets-transport.md`).

The soldier and the materials come to the harbour flag over streets, so an expedition whose harbour flag has no
street to the stores stays in state 3 with its soldier order open (and `!Harbor is not Connected` every 1000 ticks)
[inferred from the parts above; the remake's port behaves so on `MP_6P_ship_ahoi`, where a connected expedition
reaches state 5 with 3 packages and 1 soldier aboard].

**One soldier per expedition** [known for the parts, inferred as a whole]: an order is handed to exactly one
settler and then removed (`OrderSystem::AssignOrderToSettler` S 00562580). For an order linked to a ship
(order category 6) the hand-over is `Settler_LinkShip` S 0053bfb0: the settler's ship reference (+0xf8) is
set and the settler joins the expedition's `units` (S 00561e20). From then on `units` is not empty, and a new
order is only created while `units` **and** the cargo's settler list are empty and no order is open. So one
soldier is called, walks to the harbour flag and boards; a second order appears only if that soldier is
unlinked again before the ship is ready (for example it dies). The founding step garrisons every unit, which
is one.

**The order to found** is the lockstep command `0x2001C` (§5.1): state 5 → 6.

**Founding** (state 6) [known] S 005b8ac0, in this order:
1. `FindBuildingPosition` S 005b7e50 (ring walk, rules in `../navy-and-military.md` §6). It calls
   `CanPlaceBuildingAt` with player −1 and the ship's owner as the alternative player, borders allowed [known].
2. `NVillage::System::PlaceExpeditionBuilding(player, cell)` S 0055a820 [known], in this order:
   `MapModifier::AddTerritorySource(cell, radius 4, player, notify = false)` (so that the building can be
   placed on land that was nobody's); `PlaceBuilding` of type `expeditionBuilding[tribe]`;
   `Construction::Complete`; `TerritoryUpdater::Activate`, which adds the building's own territory source
   with its real range (`bp_setTerritoryRange` plus the owner's `Effect_ExpandTerritory`) and reveals its
   sight area. Each `AddTerritorySource` recomputes the owners inside its radius and the border bits at once
   (`map-resources.md`, "Adding a source"), so the territory grid is current when the call returns.
3. `Harbor::PlaceFlagAndRevealExitsForCellOwner` on the target harbour. It places the flag for the **territory
   owner of the harbour cell** and only if that cell is not a border cell (§3.1 rule 1). The building stands
   at most `territoryRange - 1` cells from the harbour (step 1), so the harbour cell lies inside the new
   territory and each of its 6 neighbours is at most `territoryRange` cells from the building, which the
   owner rule (`dist <= range`, `map-resources.md`) still covers. A cell is a border cell iff it has an
   owner and one of its 6 neighbours is outside the map or has another owner
   (`MapCellUpdater::IsTerritoryBorderCell` S 0067b5a0 [known]). So the colonist gets the flag, and with it
   the harbour, in this step unless another player's source wins the harbour cell or one of its neighbours,
   or a neighbour lies outside the map [inferred]. If the flag is not placed here, the per-tick rule of §3.1
   places it for whoever owns the cell later.
4. A street from the harbour cell to the building's entrance flag: `StreetPlanner::BuildStreet(player,
   harbour cell, type 0)`, `ExtendTo(entrance flag cell)`, `TakePath`, `NNet::System::BuildStreet`.
5. `NMilitary::Distances::UpdateBuilding(building)`.
6. For each unit (copy of the list): unlink it from the expedition; if the building wants a garrison
   (`Military_GetDesiredGarrisonSize != 0`): make it a soldier of the building, unlink it from the cargo and
   disembark it.
7. Cost: with `need = frameCost ++ cost` of the building, each package aboard whose good is still needed
   reduces the need by one and is discarded. Surplus packages stay aboard.
8. `Finish()`; return true.

`Finish` S 005b7c30: take the ship off the route (`NavyLink_UnlinkExpeditionRoute`: remove from the route
list, `ClearRoute`, release units and orders, `bActive = 0`); then, if both ends now belong to the player, put
it straight back on the route (`NavyLink_LinkMovementRoute`) and re-reserve the docking position at the harbour
it was at. After a successful founding the ship therefore becomes the ferry of the new sea street (ship state
1); after a return it is idle (state 0) unless the route became own-to-own meanwhile [known].

**Abort** is the command `0x2001B`: `Expedition::Abort` S 005b7d00 sets state 7 and `bInterrupted` if the ship
is not lying still, for the first ship of the player on the route with an active expedition [known]
S 005ba800.

`ReleaseUnitsAndOrders` S 005b8370: remove all open orders from the order system, unlink all units from the
expedition, clear the goods requests [known]. Packages already aboard are unloaded in state 8 only if the
harbour flag takes them.

### 3.11 Sea attacks

Rules, harbour finders, dispatch and the mission table: `../navy-and-military.md` §5. Verified here against
S 005ba250, S 005b9f30, S 005ba190 [known]; additions:

- `Military::Activate` S 005b9cd0: `state = 0`, `bActive = 1`. It happens when the ship is linked to the
  route or to the fight, if not active yet.
- Boarding (`BoardSettlersAtHarbor(returning)` S 005b9f30): returns true only when **all** mission soldiers
  are aboard. Otherwise each soldier that is not aboard, is not busy moving, stands on the harbour cell of
  the ship's current harbour and whose "left the fight" flag equals `returning` boards at once (no per-tick
  limit), and the function returns false. The flag is a byte of the soldier object compared with the
  parameter [known]; its meaning is taken from `../navy-and-military.md` §5.3 [inferred].
- No capacity check applies to soldiers (§2.7) [known].
- Disembarking in mission states 4 and 7 goes through `DisembarkOneSettler` (§3.9), so one soldier leaves on
  each tick with `(tick + id) % 5 == 0`, not on every tick; on the other ticks the call reports "somebody is
  still linked" and the state is kept [known] S 005ba250, S 005bcd10.
- `Finish` S 005ba190: `bActive = 0`; unlink from the fight; unlink every mission soldier (last to first);
  take the ship off its route. The ship then returns to state 0 and calls `ReturnToOwnHarbor` (§3.8).
- Unchecked reads in `Update` S 005ba250 [known]: state 0 sails to `GetEndHarborOwnedBy(route, owner)` S 005b6970
  with no test, and `MoveToHarbor` S 005b97f0 dereferences the harbour, so a mission whose route is gone, or has no
  end of the owner's, crashes. That can happen: a harbour exit takes a non-expedition ship off its route
  (`UnlinkMovementsOfPlayer` S 005b70a0 → `NavyLink_UnlinkMovementRoute` S 0053c3f0) without calling `Finish`, so
  the mission stays active. State 3 reads the fight through its cached pointer unchecked too, but that cannot
  fail while the mission is active: the fight's destructor calls `NavyLink_UnlinkMilitaryFight` S 0053c160, which
  runs `Finish` S 005ba190; state 3 goes to 7 when the defender has no end of the route.
- `HarborList::FindNearestWithPlayerShipRoute` S 005b6090 writes to its `*status` the result of the **last**
  harbour it evaluated, not of the harbour it returns [known].
- The reach test `Military_IsEnemyTerritoryInRange` S 00575850 walks only the hex ring at `R + 1` around the
  target; cells inside the ring are not tested [known].
- `Military_GetAttackOriginCell` S 00576d00 reads the building's anchor without a null test when a harbour
  exists and no building was found (`military.md` §3.5, origin cell) [known].

### 3.12 Sea streets and reachability

`NavyShipRoute::UpdateSeaStreet` S 005b71d0 runs when a ship is added to or removed from the route's list and
when a flag is attached to an end harbour [known]:
- a street exists: if `IsStreetValidForPlayer(street owner)` is false, remove the street and end the call; a
  valid street is left as it is. A street removed here is **not** rebuilt in the same call, even when another
  ship's owner now owns both ends; the next call builds it;
- no street: the first ship in the list whose owner owns both ends → build a type-3 street for that player
  with the navy's street planner (System +0x64): `BuildStreet` from harbour A's cell, `ExtendTo` A's exit for
  this route, `ExtendTo` B's exit, `ExtendTo` harbour B's cell, then `TakePath`.

How the road network treats a type-3 street (as stated there: usable for goods and settlers, no carrier, not
registered in the map grid, not removed with lost territory) and the path search that lays it
(`NLogic::AStarStreet` modes 2 and 3): `streets-transport.md`, `map-resources.md` §3.12. Goods routing charges a street without a free
carrier three times its length (`StreetPathFinder::GetLinkCost` S 0066b9e0 [known]); a sea street never has a
carrier, so a sea crossing always costs 3 × its length in the goods path search [inferred].

`IsStreetValidForPlayer(p)` S 005b6d80: a street exists, both ends belong to `p`, and `p` has a ship in the
list. `Navy_AreContinentsConnectedForPlayer(p, a, b)` S 0052eba0: `a == b`, or some harbour of `p` (harbour
list order) whose cell is on landmass `a` or `b` has a routed exit with a valid sea street for `p` whose
other end harbour's cell is on `a` or `b` and on a different landmass than the first [known]. Only direct
crossings count: two landmasses joined through a third are not connected for this test. Its only caller is
`BuildingList_FindNearestReachable` S 00557fe0 (`village-buildings.md`).

## 4. Update order

`NNavy::System::Update` S 005b39d0 (slot 1 of the system's vtable) is step 14 of the logic tick, after the
military system and before statistics and the AI (`logic-core.md` §4.2) [known] S 00527070:

1. For each ship in vector order: `Ship::Update`; if its state is 7 afterwards, destroy it and erase it from
   the vector (the next ship moves into its slot and is updated in the same pass).
2. `HarborList::PlaceFlagsAndRevealExitsForCellOwners` (§3.1 rule 1) for each harbour in list order.

Rates inside `Ship::Update` [known]: movement, condition and state machine every tick; goods and settler
exchange on `(tick + id) % 3 == 0`; idle and military disembarking on `% 5`; assigning waiting settlers while
sailing on `% 11`; anchorage validity on `% 111`; anchorage search at most every 101 ticks; state 0 and 1
decisions every 102 ticks; expedition supply report on `% 1000`.

Outside the navy tick: ship construction progresses in the settler system (step 9) [inferred: the work is
added by the constructor's movie, §3.3]; route commands are executed in step 2 of the same tick
(`NComm_Manager::AdvanceNetTick`), before every subsystem update; the AI (step 16) assigns ships and orders
foundings (§5.3) [known] S 00527070.

Per frame only (not simulation): `S2CG::ShipMgr` / `S2CG::Ship::Update` (position interpolation from
`progress`, yaw, effects), the info boxes `nMenu::InfoBoxShip` / `InfoBoxShipRoute` [inferred from the
namespaces; not read in detail].

## 5. Inputs and outputs

### 5.1 Lockstep commands

All three carry the route's unique id and a player index (`EventInt64_1Integer`); a route that is not found
makes the command a no-op [known] S 00781ad0, S 00781b70, S 00781c10. Details of the transport:
`game-commands.md`.

| Id | Effect |
|---|---|
| `0x2001A` | if `GetAssignShipBlockReason(player) == 0`: `AssignNearestIdleShip(player)` (starts an expedition, §3.10) |
| `0x2001B` | if the player has an active expedition on the route: abort it |
| `0x2001C` | if the player has an active expedition on the route in state 5: state 6 |

The command handlers take the player index from the event and do not compare it with the sender [known for
these three bodies].

Sea attacks start with the attack command `0x2000D` (`../navy-and-military.md` §4). A ship-building site is
placed and removed with the ordinary building commands.

### 5.2 Script functions (`logic.na_*`, `../lua-surface.md`)

All except `na_getShipCount` take `(player, x, y)` first, check the cell (inside the map) and the player
(index < 8, active) and silently return nothing on bad arguments; `na_getShipCount` checks the player the
same way [known]:

| Function | Behaviour |
|---|---|
| `na_createShip(p, x, y)` | finished ship at the cell (S 005af4a0) |
| `na_destroyShip(p, x, y)` | delete the first ship on the cell if it belongs to `p` (no sinking) (S 005af2a0) |
| `na_sendShip(p, x, y, tx, ty)` | the first ship on the cell, if `p`'s: release its anchorage, reserve `(tx,ty)` as anchorage and sail there (`Movement::MoveToTile` S 005b9920); `(tx,ty)` must pass the map-cell argument check (`LuaGame_IsValidMapCellArg(4,5)`), but nothing tests that it is water or reachable (S 005af390) |
| `na_sinkShipOnRoute(p, x, y)` | route through the cell; if `p` has a ship on it and that ship (the first of `p` in the route's list) is not in state 6..8: `ScheduleSinkingNoDelay` (S 005af1a0, S 005ac8d0) |
| `na_isShipOnRoute(p, x, y)` | bool: `p` has a ship assigned to the route through the cell; no result if no route (S 005aefe0) |
| `na_isShipAtPosition(p, x, y)` | bool: the first ship on the cell belongs to `p` (S 005af0c0) |
| `na_isShipAtRoutePosition(p, x, y)` | bool: the first ship on the cell belongs to `p` and is assigned to the route through that cell; no result if no route passes through the cell (S 005aff90) |
| `na_getShipCount(p)` | number of finished ships of `p` (S 005b0c90) |

"The first ship on the cell" is `System::FindShipAtPosition` S 005b3960: vector order, compares
`currentCell`.

### 5.3 Computer players [known, summary level]

- `NAI::ShipConstruction::Update` S 005a5d00 (every 673 AI ticks, S 00592210; only while it has no order
  pending and `ai_enableShipConstruction` S 005ae100 set the player's flag): for each harbour record in the
  AI's cells, in cell order, whose AI cell is not marked full for the key `1d66b4ae` (the good `ship`, used
  for every tribe): if `CountOwnShipsOnContinent < CountSeaRoutesOnContinent` for the continent stored in
  the record and `NAI::Cell::HasFreeProductionOfType(1d66b4ae)` S 00595750 is false for that cell, start one
  construction order (`ConstructionOrder::InitAtPos(pos, 0x10, type, 10)`; `type` is the tribe's building
  with the ship size as the name of its lookup says, not read) at the position of the harbour's flag and
  stop for this run. The ship count is the player's ships, finished or
  not, whose cell has the given continent id; the route count is routes with two valid end references, an
  end owned by the player, neither `path[0]` nor `path[last]` in the player's forbidden list
  (`ai_forbidHarborPosition`; these are the exit cells, while `UpdateShipRoutes` below compares the harbour
  flag's cell with the same list), and `path[0]` on that continent (S 005a5a80, S 005a5b50). An order that
  ends with a result other than 1 marks the AI cell full for `1d66b4ae` (S 005a59d0).
  `HasFreeProductionOfType(cell, ship)` S 00595750 = `FindFreeProductionOfType(cell, ship, true)` S 00595450
  [known]: true when the cell's production list holds an `NAI::Production` of the good `ship` (+0x18) that
  serves no need (`servedNeed` id unset, Production +0x74) or whose need has no building reference (Need
  +0x7c); a production of a group good (type 3) matches when `ship` is one of its members. The only producer
  of `ship` is the ship-building site `shipBuilding` (`bp_setGoods(shipBuilding, ship, 1)`; `Building::Init`
  S 00596ba0 makes one production per unit). So a Scots or Bavarian AI does not order a second site in a cell
  where its own site still stands; the Egyptian site `shipBuildingEgypt` produces `shipEgyptCosts`
  (65a7cc73, `Goods.lua`), a plain ware group (type 2), so for an Egyptian AI the test is always false and only
  the ship / route count and the full mark limit the orders [known: code and data].
- `NAI::Expedition::UpdateShipRoutes` S 005a02c0 (every 211 ticks, S 00590fd0): only if the player's stock
  holds the full cost (`frameCost ++ cost`) of the expedition building. For each harbour record in the AI's
  cells whose flag cell is not forbidden and each routed exit: if the player has an active expedition on the
  route: order the founding if it waits for orders, else nothing; otherwise, if the far harbour's cell is
  unexplored for the player **or** the far harbour is unowned, and assignment is allowed
  (`GetAssignShipBlockReason == 0`) → `AssignNearestIdleShip`. The AI calls the navy functions directly, not
  through commands.

### 5.4 What the navy asks of other subsystems

- Map: `GridStates`, `Continents`, `Territory`, `Exploration`; `MapModifier::SetShipTileBit`, `ExploreArea`.
  `ExploreArea(cell, radius, player)` S 00674800 reveals the area for `player` **and for every active player
  that is not its enemy** [known], so each "explore for the owner" in this document also explores for allies.
  Every change of an anchorage bit is followed by `MapUpdateBatch::InvalidateConstructionAroundCell(cell)`
  S 00532400 (`InvalidateConstructionRadius(4, 0, 6, 0, x, y)`), the map-change notice that makes the
  construction flags around the cell be recomputed (`map-resources.md`, map update batch) [known: all six
  callers of `SetShipTileBit` in the navy, S 005b9220, S 005b9260, S 005b92e0, S 005b96c0, S 005b98a0,
  S 005b9920].
- Random generator: the path read-back of the ship A* (§3.4).
- Road network: `Logic_PlaceFlag`, `NNet::System::GetFlagAtPos`, `BuildStreet`, `RemoveStreet`, the flag's
  waiting list (+0x18c), settler list and package stacks (+0x74).
- Transport: `Transport_LoadPackageIntoHolder`, `UnloadPackageFromCargo`, `DiscardPackage`, `NeedGoods`.
- Settlers: `EnterShip`, `DisembarkAt`, `RemoveSettler`, the wait states of `SettlerMovement`.
- Village: `OrderSystem` (soldier order), `PlaceExpeditionBuilding`, `RemoveBuilding`, building properties.
- Military: `Distances::UpdateBuilding`, `Fight` (ship list, defender), soldier "left the fight" flag.
- Players: tribe, ship-name counter, messages (`PlayerMessages_SendToPlayer` kind 6), sacrifice modifiers.

### 5.5 What it offers and raises

- Queries: the harbour finders of `../navy-and-military.md` §5.1, `Navy_AreContinentsConnectedForPlayer`,
  `FindShipByUnique`, `FindShipAtPosition`, route lookups by id and by path cell.
- Callbacks (`NLogic::CallbackManager`, `logic-core.md` §3.7): ship added (also once per ship after load), ship
  destroyed, ship route added (also once per route after load) / removing, receiver slot +0x88 with a harbour
  (from the harbour's constructor with a position and once per harbour after load, S 005b5bc0, S 005b5240),
  receiver slot +0x8c with a harbour (from the harbour's destructor S 005b5530), sacrifice "sink ships" per
  ship (receiver slot +0xb8, S 00660360) [known].
- Player messages (text keys): `!Ship constructed`, `!No Place for Ship found!`, `!Ship waiting for Orders`,
  `!Harbor is already captured!`, `!No Valid Position for Building found!`, `!Harbor is not Connected`,
  `!No Soldier for Expedition found`.
- UI availability codes: assign (table in §3.10); found colony (`GetFoundColonyBlockReason` S 005baa50):
  1 = no active expedition of the player on the route, 2 = not waiting for orders, 0 = possible.

## 6. Data-driven parameters

### 6.1 `data/game/scripts/properties/ship.lua` → `ShipConfig`

| Key | Setter | Field | Shipped value |
|---|---|---|---|
| `sh_setSpeed(tribe, v)` | S 0054caa0 | speed map | bavarians 0.06, egyptians 0.09, scots 0.12 (cells per tick) |
| `sh_setSize(n)` | S 0054cae0 | `size` | 1; never read (§2.10) |
| `sh_setConstructTime(v)` | S 0054cb10 | `constructTime` | 30 (strokes per visit and divisor of the work per stroke) |
| `sh_setStockLimit(n)` | S 0054ca70 | `stockLimit` | 12 packages |
| `sh_setExpeditionBuilding(tribe, type)` | S 0054ca30 | building map | bavarians `guardHouseBav`, scots `guardHouse`, egyptians `guardHouseClay` |
| `sh_setWaitTime(n)` | S 0054ca10 | `waitTime` | 15 (loading wait count, §3.7 state 2) |
| `sh_setSinkingTime(n)` | S 0054cb40 | `sinkingTime` | 47 ticks |

### 6.2 `harbors.lua` → `HarbourProperty`

`hp_create(id)` for 8 facings (`harbor_sw` `aaaa1985`, `harbor_nw`, `harbor_se`, `harbor_ne`, `harbor_n`,
`harbor_s`, `harbor_e`, `harbor_w`); `hp_setName` (`"south west"` ...), `hp_setGfxName` (all `"dummy"`),
`hp_setWaterStreetPosition(h, dir, dx, dy)` (exit offset, e.g. sw dir 0 = (-2,-3)),
`hp_setShipPosition(h, dir, slot, dx, dy)` (dock offsets, e.g. sw dir 0 = (-3,-3) and (-3,-4)) [known].
Full table and the rule that offsets are added without row-parity correction: `../map-format.md` §6.3.

### 6.3 `buildings.lua`, `Goods.lua`, `config.lua`, `patterns.lua`

- `SizeShip = 16` (`config.lua`); `shipBuilding` (`318d1529`) and `shipBuildingEgypt` (`8b7d38b3`):
  `bp_setSize(SizeShip)`, `bp_setWorkerLimit(0)`, `bp_addFrameCost(plank | wood, 4)`,
  `bp_addCost(plank | wood, 8)`, `bp_setIgnoreGoodCosts(true)`, `bp_setWorkingRadius(1)` (the placement search
  radius of §3.3), `bp_setGoods(ship | shipEgyptCosts, 1)` [known].
- Goods `ship` (`1d66b4ae`, cost plank 12) and `shipEgyptCosts` (`65a7cc73`, cost wood 12) [known]
  `Goods.lua`. The AI's key for "ship-building site" is `1d66b4ae` for every tribe [known] S 005a5d00,
  S 005a59d0; no use of `65a7cc73` was read in the code.
- Expedition buildings: `guardHouse*` with frame cost 1 and cost 2 of plank (clay for Egyptians),
  `bp_setTerritoryRange(9)` (so the position search walks rings 1..8), soldier limit 2 / 3 / 4 [known].
- `pa_setForShip` on a ground pattern makes ship ground (bit 0x20000) `../map-format.md` §5.4; in
  `patterns.lua` only the helper `setShip` calls it, for `pattern_pavement` (`decade01`) [known].

### 6.4 Sacrifices (`sacrifices.lua`)

`Effect_ShipSpeed` = 9 (e.g. `sacrifice_shipSpeedUp`: value 200, duration 6000, target owner;
`sacrifice_shipSpeedDown*`: value 2, target enemies) feeds the speed factor of §3.4;
`Effect_FunctionDestroyShips` = 1008 (`sacrifice_destroyShips*`, target enemies) calls `ScheduleSinking` on every
finished ship of each target [known for the keys]. The value is a percentage for the owner (200 → factor
2.0) and a plain divisor on enemies (2 → factor 0.5); formula in §3.4.

### 6.5 Constants in code

100 (start and maximum condition; anchor-search cooldown; state 0/1 period), 101 (state 1 threshold), 30
(anchorage search radius; delay of a sacrifice sinking), 3 (explore radius while sailing), 10 (explore radius
on arrival of an expedition), 1 (explore radius at exits), A* costs 12 / 2 / 1, 21 ship names per player,
phase moduli 3, 5, 11, 111, 1000 [known] addresses in §3.

## 7. Save and load

Section order and primitive encodings: `logic-core.md` §7; byte layout of routes and harbours:
`../map-format.md` §6.2. The navy section is `"Navy System"` version 3 [known] S 005b35d0, S 005b4650; tag
texts and current versions are the arguments of the static initialisers S 007c6430 .. S 007c6d20:

```
tag "Navy System"
byte   initialized
u32    shipCount
shipCount × { i32 ownerPlayerIndex ; Ship }
ShipRouteList                      tag "Navy ShipRoutes" (version 0): byte loaded, u32 count, count × route
HarborList                         tag "Navy Harbors" (version 0): byte loaded, u32 count,
                                   count × { i32 harbour type id ; harbour }
```

`Ship` (tag `"Navy Ship"`, current version 2, S 005bb060 / S 005bb0f0):

```
Unique
Construction   tag "NavyConstruction" (version 2): float remainingWork1, float remainingWork2,
               ReferenceSettler, cell buildCell (version > 0), ReferenceBuilding (version > 1)
Movement       tag "Navy Movement" (version 1): Path (tag "Navy Path", version 0, then NMovement::PathBase),
               byte bInterrupted, cell markedTile, ReferenceHarbor targetHarbor, ReferenceShipRoute route,
               i32 anchorSearchCooldown, i32 state (version > 0), then NMovement::Base (cells and
               interpolator)
i32 state ; i32 stateCountdown
Expedition     tag "Navy Expedition" (version 0): byte bActive, OrderContainer, NeedGoods,
               ReferencesSettler units, i32 state
u32 shipNumber
Cargo          tag "Navy Cargo" (version 1): (version 0 only: an NLogic::Stock, read and thrown away)
               PackageContainer, ReferencesSettler
Condition      tag "Navy Condition" (version 0): i32 condition          (ship version > 0)
Military       tag "Navy Military" (version 0): byte bActive, ReferencesSettler soldiers, ReferenceFight,
               i32 state                                                  (ship version > 1)
```

The tag texts are as written here: `"NavyConstruction"` is the only one without a space [known] S 007c6960.

Not saved [known]: the sinking timer (+0x44..+0x4c), the `shipConfig` pointer, cached reference pointers, both
path finders, the docking-position occupant is saved with the harbour (`../map-format.md` §6.2).

On load [known] S 005b4650, S 005b3a90:
1. `Reset` (delete ships last to first, delete both path finders, stop the street planner, clear routes and
   harbours, `initialized = false`), then read as above; ships are created with `ctor_ForLoad` for the
   player of the stored index (start cell (-1,-1), so no anchorage is marked by the constructor; state 0,
   countdown 0, ship number 0, condition 100, sinking timer (-1, 0, 0) before the record is read).
2. `PostLoad`, in this order: each ship resolves the references of construction, movement, expedition, cargo
   and military, and raises "ship added" (S 005bab10); both path finders are rebuilt for the map; the street
   planner is stopped if active and started again; each route resolves its two harbours, its ship list and
   its street and raises "ship route added" (S 005b6af0); each harbour resolves its exits (docking positions
   and route reference) and its flag reference and raises the callback of receiver slot +0x88 (S 005b5240).
3. Grid bits are **not** rewritten on load: the anchorage bit 0x10000 and the navy bits come from the saved
   `GridStates` [known] `../map-format.md` §6.5.

A ship saved while sinking (state 6) is loaded with the timer `(-1, 0, 0)` and reaches state 7 on its first
update [inferred from the unsaved timer and the top of S 005bb500].

`System::StoreUntagged` S 005b36a0 writes the same content without tags and **without the construction
record** into the lockstep state hash: ship count, per ship owner index, unique, movement, state, countdown,
expedition, ship number, cargo, condition (this one with its tag), military; then routes and harbours [known]
S 005bb1a0. The `initialized` byte is not written. The checksum stream ignores section tags and takes only
4 bytes of a string, and the map grids (with the anchorage bits) are not hashed at all: `save-format.md`,
`logic-core.md` (desync checksum).

## 8. Determinism notes

- **Random numbers.** No function of `NNavy` or `ai::navy` calls the random generator directly, but every
  ship path found by A* is read back with `randomize = true` (§3.4): one draw of the simulation generator at
  the start of a path of more than one step and one more at every cell where the direction has to change
  [known] S 005bdb30, S 00676d10. These draws belong to the shared lockstep sequence; a reimplementation that
  must stay in step has to make the same searches at the same moments. Moves along a stored route segment
  draw nothing. Settlers that queue at a harbour flag draw once each (§3.9).
- **Iteration order is state.** Ships are updated in creation order; the nearest-ship, nearest-harbour and
  nearest-dock searches keep the **first** candidate on equal distance (strict `<`). Harbours and routes are
  in map order; exits in stored direction order; a route's ship list in assignment order; flag waiting lists
  and package stacks in their own order (`settlers-jobs.md`, transport), and loading at a harbour skips the
  package that moves into a loaded package's slot (§3.9). Erasing a ship shifts the vector
  (order preserved).
- **Phase offsets use the ship's unique id** (64-bit add, then modulo), so id assignment order must match the
  original for identical timing.
- **Flood fill** (`ai::map::FloodFillSearch`, S 005b3e60 and S 005b4060) [known]: FIFO queue; the start cell
  is tested first, and only if it passes the same "may be visited" test as every other cell (otherwise the
  search fails at once); neighbours are generated in direction order 0..5 by the walk "step once in direction 4,
  then one step in each of the directions 0..5 in turn" (the six ring cells around the centre in that
  order); a neighbour is tested for "goal" before it is enqueued, so the result is the first goal in
  breadth-first, direction-ordered discovery. The direction vectors themselves are in `../map-format.md` §5.1.
- **Floating point.** Movement uses 32-bit floats for `progress`, `carryOver`, `stepRate`; `stepRate` is
  computed as `1 / (d / speed)` in x87 extended precision and then stored as float; the comparison is
  `progress > 1.0`. Construction uses float subtraction and `<= 0`. `speed * factor` is a float product. A
  reimplementation that must stay in step with original clients needs the same rounding; one that is only
  self-consistent should use fixed point.
- **Same-tick ordering inside the navy tick.** A ship erased in state 7 lets its successor run in the same
  pass. Harbour flags are placed after all ships have moved.
- The anchorage bit is a shared map bit: the order in which two ships search in the same tick decides who gets
  the nearer cell (vector order).
- UI and AI read-only helpers (`GetAssignShipBlockReason`, availability codes) have no side effects [known].

## 9. Notes for a reimplementation

- Harbours, exits, docking cells and routes are **map data**. Keep them exactly as stored, including the route
  path order (A's exit first); do not regenerate them. For compatibility with original maps and saves the
  section layout of `../map-format.md` §6.2 and the ship record of §7 must be byte-exact, including the
  version gates.
- The sub-object structure (construction, movement, expedition, cargo, condition, military) can be flattened
  into one ship record; keep the fields and the order of §7 if original saves are to be read.
- The reference classes (`ReferenceHarbor`, `ReferenceShip`, ...) are id-plus-cached-pointer pairs; plain ids
  or handles do the same job. "Valid" means id hi in `0..0x7fffffff`.
- Keep these observable rules: one ship per player per route; docking reserved at departure; at most one ship
  per player per exit; idle ships adopt own-to-own routes by themselves every 102 still ticks; cargo capacity
  counts packages only; everything aboard is lost with the ship; a ship-building site builds one ship and
  disappears; a stranded ship loses 1 condition per still tick.
- Things that look like defects and can be fixed in a remake that does not need lockstep compatibility: the
  self-comparison "water body" tests in `FindOwnRouteForShip` and `FindDockingPositionForShip`;
  `ChooseStartHarbor` returning null when the player owns neither end; `FindDockingPositionOf` returning a
  static dummy; the missing null test after `FindDockingPositionForShip` (§3.1 rule 3); a ship without a
  path counting as docked and the straight-line first step onto a route (§3.4); cargo exchange without a
  position test; `AssignNearestIdleShip` measuring from harbour A's exit even when the player owns end B;
  `bInterrupted` surviving a stop; the unsaved sinking timer; `sh_setSize` without effect; the hold
  exceeding `stockLimit` (§3.9); the ship-building fetch that takes the first cost good without testing that
  the stock holds it (§3.3, no effect with the shipped data); a sea street that is removed and not rebuilt for
  another qualifying player until the next refresh (§3.12).
- The sea attack rules have known gaps that the `navalcombatfix` mod addresses
  (`../navy-and-military.md` §7); decide per rule whether the remake keeps the original behaviour.
- Rendering needs from the logic only: cell, next cell, `progress`, ship state, cargo empty or not, the
  expedition's and the military mission's active bytes, the construction values and `buildCell` [inferred for
  `S2CG::Ship::Update` S 006a54c0 (`ShipConfig::GetSpeed`); `S2CG::Ship::UpdateVisuals` S 006a5cc0 is read: it
  takes the status mesh from the two active bytes and `NavyCargo::IsEmpty`, and the swell from "under way"
  (`progress >= 0`), `animation-models.md` §3.17]. The swell is presentation only.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.2): only the debug menu's building tool (`nMenu::Debug::HandleToolClick` S 00604dd0, tool mode 6) opens a batch edit, for the duration of one `PlaceBuilding` / `RemoveBuilding` call; a ship-building site placed that way is completed at placement by `Construction::StartWithType` S 0055efa0 and never makes a ship | — |
| 2 | Answered (§2.10): no; the whole-binary scan of `PropertiesDb + 0x68` and of the `Ship.shipConfig` copies finds no reader of `+0x10` | — |
| 3 | Answered (§3.1 rule 3): the null write is not reached through the game's own rules (one ship per player and route, `MoveToHarbor` only to ends of the own route, `ClearRoute` releases the docking position). A sea attack next to an own ship of the same route sends nothing by sea (`SendSoldiersBySea` S 00575510). Not covered: a save edited by hand, data with fewer than two docking positions per exit | static: S 005b97f0 and its five callers, S 005b9340, S 005b7050, S 005b4c50, S 005b3450, S 005b6d30, S 00575510 |
| 4 | Answered (§3.4, §3.8): an anchored idle ship takes an own-to-own route on another water body (the continent test of S 005b4c50 compares the ship's cell with itself), and its first crossing starts with one straight step from its cell to `path[n-2]` | static: S 005b4c50 (disassembly), S 005bab60, S 005b99d0, S 005bdb30, S 005bd900, S 00772c50, S 005436d0, S 007728d0 |
| 5 | Answered (§3.4): yes, for the one stay before its first crossing; ship states 3, 1 and 2 run on still ticks (movement state 4, not under way) and use `targetHarbor` only | static: S 005bb500, S 00772b00, S 005bbbe0 |
| 6 | Answered (§5.3): a production of the good `ship` in the cell that serves no need or a need without building, i.e. a standing Scots / Bavarian ship-building site; never true for the Egyptian site (`shipEgyptCosts`) | — |
| 7 | Answered (§3.10 step 3): the founding state calls the flag placement right after the building is placed; the building stands at most `territoryRange - 1` = 8 cells from the harbour cell, so the cell and its 6 neighbours lie inside the new source. No flag in that tick only when a neighbour is outside the map or another player's source wins one of the seven cells | static: S 005b8ac0, S 005b7e50, S 005b5670, S 0067b5a0 |
| 8 | Answered: no. Ship state 1 exists only on a route whose two ends belong to the ship's player, and no other player passes `CanPlayerAssignShip` there; on a route with two owners there are at most two ships and each takes its own docking position (the dock search refuses only an exit that holds a ship of the same player). Ships do not occupy cells for the path search | static: S 005b6d30, S 005ba970, S 005bc060, S 0052e360, S 005bb500 |
| 9 | Answered (§3.7): `LoadAtHarbor` reports "worked" on the two skipped ticks of three; with `waitTime` 15 a ferry with nothing to do leaves on the 17th idle phase tick, 49 to 55 ticks (about 5 s at speed 1) after its first call | live 2026-10-12: 4,883 calls, 120 stays of four ferries; S 005bd4e0 |
| 10 | Answered: a harbour's loss unlinks only the ships of that harbour's owner. A target of another player that is lost again leaves the returning ship untouched (states 7 and 8 do not read the target). If the ship's own player loses the start harbour (or a target he owned), the ship is taken off the route in the same call: expedition deactivated, ship state 0, idle rules | static: S 005b8ac0, S 005b5370, S 005b7050, S 0053c040 |
| 11 | Answered (§3.3): 31 calls of `ShipConstruct::Update` per visit (`strokes = (int)constructTime` = 30, plus the call that ends the movie), one per logic tick; the time between two fetches adds the two walks and the drop | static: S 0077fa30 (disassembly), S 0077f9c0, S 0077d6c0, S 0065e770; settler update per tick: `settlers-jobs.md` §3.9 |
| 12 | Answered (§3.9): the hold is not bounded across stays; 39 packages against `stockLimit` 12 were seen. Open: whether the destination flag of that ferry was full (the condition §3.9 names) | live 2026-10-12; a read of the destination flag's stacks during such a run |
| 13 | What the byte +0x70 of the object at settler +0x50 means, which `ConstructShip` steps 7 and 10 set to 1 (§3.3) | static: the readers of that byte |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 005b39d0 | `NNavy::System::Update` | per-tick entry: ships, then harbours |
| S 005b3360 / 005b3cf0 | `System::Init` / `Reset` | path finders, planner, lists |
| S 005b35d0 / 005b4650 / 005b3a90 | `System::Store` / `Load` / `PostLoad` | save section |
| S 005b36a0 | `System::StoreUntagged` | state hash |
| S 005bb060 / 005bb0f0 / 005bb1a0 / 005bab10 | `Ship::Store` / `Load` / `StoreUntagged` / `ResolveReferences` | ship record, post-load |
| S 005b3810 / 005b3960 | `System::FindShipByUnique` / `FindShipAtPosition` | ship lookups |
| S 005a5a80 / 005a5b50 / 005a59d0 | `NAI::ShipConstruction::CountOwnShipsOnContinent` / `CountSeaRoutesOnContinent` / `OnOrderFinished` | computer player |
| S 0067b5a0 | `MapCellUpdater::IsTerritoryBorderCell` | border cell test (§3.10) |
| S 005b4260 / 005b42f0 | `System::CreateShipAtPlacement` / `CreateShip` | ship creation |
| S 005b3890 / 005b44e0 | `System::EraseShipByUnique` / `TransferShipsOfPlayer` | deletion, ownership change |
| S 005b3450 | `System::FindNearestIdleShipAtHarborExit` | ship choice for routes and attacks |
| S 005b4370 / 005bbd10 | `System::FindShipPlacement` / `ShipPlacementSearch::IsGoal` | launch cell of a new ship |
| S 005b4430 / 005bbf00 | `System::FloodSearchShipTile` / `ShipTileSearch::IsGoal` | anchorage search |
| S 0052f0c0 / 00534000 | `GameQuery::IsWaterCellAtPlayerCoast` / `GameQuery_IsMilitaryBuildingOnContinent` | anchorage / launch predicate |
| S 005bb500 | `NNavy::Ship::Update` | ship state machine |
| S 005bab60 | `Ship::ReturnToOwnHarbor` | idle ship adopts a ferry route |
| S 005bb010 / 005bb210 / 005bb250 | `Ship::BeginSinking` / `ScheduleSinking` / `ScheduleSinkingNoDelay` | sinking |
| S 005bdc30 | `ai::navy::NavyCondition::Update` | condition |
| S 005b9b90 | `NNavy::Movement::Update` | movement per tick, anchoring |
| S 005b97f0 / 005b99d0 / 005b9990 | `Movement::MoveToHarbor` / `AdvanceRouteLeg` / `SailToOppositeRouteEnd` | route following |
| S 005b92e0 / 005b9340 | `Movement::SetRoute` / `ClearRoute` | route link |
| S 007728d0 / 00772950 / 00772b00 | `NMovement::Base::BeginStep` / `Update` / `StartMoveTo` | cell stepping |
| S 005bdb30 | `NNavy::Path::FindPath` | route segment or A* |
| S 005bba90 / 005bbbe0 / 005bb9d0 / 005bba60 | `NNavy::AStar::GetStepCost` / `CanTraverse` (search precondition, slot 0), `ShipRouteAStar::GetStepCost`, `MapPos_IsOnMapEdge` | water path costs |
| S 00676900 / 00676e80 / 00676d10 | `NMap::AStar::FindPath` / `BuildPathReversed` / `BuildPath` | shared A* core, random path read-back (`map-resources.md`) |
| S 005bd900 | `MapPosVector_ExtractSegment` | stored route segment |
| S 0053c2d0 / 0053c300 | `NavyLink_LinkMovementDocking` / `UnlinkMovementDocking` | docking reservation (no null test); the release also clears `targetHarbor` |
| S 0053c3d0 / 0053c3f0 / 0053c040 / 005b7050 | `NavyLink_LinkMovementRoute` / `NavyLink_UnlinkMovementRoute` / `NavyLink_UnlinkExpeditionRoute` / `NavyShipRoute::UnlinkMovementsOfPlayer` | route links |
| S 005baf20 / 005b96c0 / 005b3c40 | `Ship::dtor` / `Movement::dtor` / `System::DeleteAllShips` | destruction order |
| S 0055e8c0 | `NVillage::Construction::dtor` | removing a ship-building site deletes its ship |
| S 00538c90 / 00538a60 | `NLogic::Edit` slot 1 (byte +4) / `SetBatchEditing` | instant ship completion |
| S 00657d90 / 006567b0 / 00657330 | `SettlerMovement::DisembarkAt`, settler slot 0 (harbour cell), `RecallFromParkingCell` | passengers |
| S 00657cd0 / 00772f90 | `SettlerMovement::EnterShip` / `StartMode2_From128` | boarding; the street restart on landing |
| S 0053c010 / 005525b0 | `Navy_AssignShipToRoute` / `RemoveAmount` | expedition start; the missing-materials list |
| S 005b6090 / 00575850 / 00576d00 | `HarborList::FindNearestWithPlayerShipRoute` / `Military_IsEnemyTerritoryInRange` / `Military_GetAttackOriginCell` | sea-attack finders (§3.11) |
| S 00529040 | `NLogic::System::TransferPlayerAssets` | the only caller of `TransferShipsOfPlayer` |
| S 006a54c0 / 006a5cc0 | `S2CG::Ship::Update` / `UpdateVisuals` | ship animation, swell, status mesh (`animation-models.md` §3.17) |
| S 0066b970 | `FlagPackageStacks::CannotTakePackage` | can the harbour flag take a package |
| S 0066cdd0 | `NNet_FlagPackageStacks_IterNext` | index-based package iterator of `LoadAtHarbor` |
| S 0064cd60 / 0064d0b0 | `Transport_LoadPackageIntoHolder` / `NTransport::System::UnloadPackageFromCargo` | cargo load / unload |
| S 00562580 / 00561e20 / 0053bfb0 | `OrderSystem::AssignOrderToSettler`, `VillageOrder_LinkSettlerToDestination`, `Settler_LinkShip` | the expedition soldier |
| S 0055a820 / 00673af0 / 00565350 | `PlaceExpeditionBuilding`, `MapModifier::AddTerritorySource`, `TerritoryUpdater::Activate` | colony territory |
| S 006632d0 / 006630b0 / 006631e0 | `SacrificeModifiers::GetShipSpeed` / `ApplyOwnEffect` / `ApplyHostileEffect` | ship speed factor |
| S 00674800 / 00532400 | `MapModifier::ExploreArea`, `MapUpdateBatch::InvalidateConstructionAroundCell` | exploring, map-change notice |
| S 005bd4e0 / 005bcfa0 / 005bcea0 / 005bcd10 | `ai::navy::NavyCargo::LoadAtHarbor` / `UnloadStep` / `UnloadOnePackage` / `DisembarkOneSettler` | cargo exchange |
| S 005bd270 / 005bd3b0 / 005bb420 | `ai::navy::NavyCargo::AssignWaitingSettlers` / `UnassignPendingSettlers`, `NavyHarbor_HasPendingCargoFor` | passengers, demand test |
| S 005bcc30 / 005bcc60 / 005bd0f0 | `ai::navy::NavyCargo::IsFull` / `IsEmpty` / `ReleaseAll` | capacity, loss of cargo |
| S 005b8ac0 / 005b8470 / 005b7e50 | `NNavy::Expedition::Update` / `GatherCargo` / `FindBuildingPosition` | expedition |
| S 005b7b80 / 005b7c30 / 005b7d00 / 005b8370 | `Expedition::ChooseStartHarbor` / `Finish` / `Abort` / `ReleaseUnitsAndOrders` | expedition helpers |
| S 005ba250 / 005b9f30 / 005ba190 | `NNavy::Military::Update` / `BoardSettlersAtHarbor` / `Finish` | sea attack mission |
| S 005ba970 / 005ba720 / 005ba800 / 005ba8f0 | `NavyShipRouteBackRef::GetAssignShipBlockReason` / `AssignNearestIdleShip` / `AbortPlayerExpedition` / `OrderPlayerExpeditionFoundColony` | route commands |
| S 00781ad0 / 00781b70 / 00781c10 | `nGame::System` handlers of `0x2001A` / `0x2001B` / `0x2001C` | lockstep entry |
| S 005b6d30 / 005b6d80 / 005b71d0 | `NavyShipRoute::CanPlayerAssignShip` / `IsStreetValidForPlayer` / `UpdateSeaStreet` | one ship per player, sea street |
| S 005b49f0 / 005b5370 / 005bc1c0 / 005b5670 | `Harbor::AttachFlag` / harbour flag loss / `NavyHarborExit_UnlinkOwnerShips` / `PlaceFlagAndRevealExitsForCellOwner` | harbour ownership |
| S 005b4a90 / 005bc060 / 005b4da0 | `Harbor::FindDockingPositionForShip`, `HarborExit::FindNearestFreeDockingPosition`, `Harbor::FindDockingPositionOf` | docking |
| S 005b6370 / 005b4c50 | `HarborList::FindNearestHomeHarborForShip`, `Harbor::FindOwnRouteForShip` | home harbour |
| S 0052eba0 | `Navy_AreContinentsConnectedForPlayer` | reachability over sea streets |
| S 0065e770 / 0077d6c0 / 0077fa30 / 0077f9c0 | `Constructor::UpdateShipConstruction`, `NMovie::ConstructShip::Update`, `NMovie::ShipConstruct::Start` / `Update` | ship building |
| S 005ba450 / 005ba640 | `NNavy::Construction::AddWork` / `SetBuildPosition` | build progress |
| S 005a5d00 / 005a02c0 | `NAI::ShipConstruction::Update`, `NAI::Expedition::UpdateShipRoutes` | computer player |
| S 005af4a0 .. 005b0c90 | `GameScript_Lua_na_*` | script functions |
| S 00660360 | `Sacrifice::ApplySinkTargetShips` | sacrifice effect |
| S 005556c0 / 005554d0 / 00555510 | `ShipConfig` ctor / `GetSpeed` / `GetExpeditionBuilding` | parameters |
