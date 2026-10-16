# Streets, flags and goods transport

Reference for the street network (`NNet`), the package and need systems (`NTransport`, `ai::transport`,
`ai::logistics`, `ai::nnet`) and the street carrier (`NSettlers::Carrier`) of `sadk_noav.exe`.

Tags: **[known]** = read directly in the code or data (address as `S 00xxxxxx`, or data file and key),
**[inferred]** = one step of reasoning from what is visible, **[TODO]** = open. Nothing in this document has been
observed in the running game.

Related documents (not repeated here): `docs/sim/game-commands.md` (the street and flag commands and the per-player
street planner), `docs/sim/village-buildings.md` (buildings, stocks, settler orders, entrance flags),
`docs/sim/logic-core.md` (tick, random generator, checksum, save container), `docs/sim/players-victory.md` (good
priorities), `docs/map-format.md` (cells, GridStates bits, slope classes), `docs/navy-and-military.md` (harbours,
ship routes, sea streets), `docs/types.md`, `docs/lua-surface.md`.

---

## 1. Purpose and scope

The subsystem owns:

- the **graph** of flags (nodes) and streets (edges) of every player, its registration on the map, and the
  connected-component ids ("net continents") used by every "is A connected to B" question in the game;
- the **rules for placing** flags and streets (cell tests, the street search and its step costs) and for removing
  them (commands, lost territory);
- **packages**: one object per unit of a good that is outside a building stock; where a package lies (flag stack,
  carrier, ship cargo) and where it must go;
- the **flag stacks** (capacity of a flag) and the hand-over protocol between carrier and flag;
- **routing**: shortest path search over the flag graph, the edge cost, the next-hop cache and its refresh;
- the **street carrier** state machine (first carrier and second carrier / pack animal), the street upgrade by
  traffic, package choice by good priority, congestion handling;
- **matching** of good requests of buildings and ships ("needs") with free packages and supplier buildings.

It does not own: the command layer and the planner object (`game-commands.md`); what a building requests and what
it does with a delivered good (`village-buildings.md`); settler orders that bring a carrier to a street
(`village-buildings.md` §3.12); settler movement on a cell path, speeds and animation timers; ships and harbours
beyond being nodes and edges of this graph (`navy-and-military.md`); the computer player's street planning
(`NAI::Street*`); rendering (`ai::gfx::StreetRenderer`, `S2CG::CStreet`, `S2CG::WaterStreet`).

---

## 2. Data model

Conventions: a *reference* is an `NLogic::Reference*` object (0x20 bytes) holding a 64-bit `NLogic::Unique` id and
a cached pointer; it is *valid* when the high dword of the id is in `0..0x7fffffff` [known, the test
`-2 < hi && hi < 0x80000000` is in every function below]. A cell is `{i32 x, i32 y}` (8 bytes). Player index is
0..7.

### 2.1 `NNet::System` (0x294 bytes, `NLogic::System+0x4c`)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `initialised` (byte) | saved; cleared by `Clear` [known] S 006640d0, S 00667ce0 |
| +0x08 | `streetsByPlayer[8]` | `vector<Street*>` per owner, in creation order [known] S 00666210 |
| +0x88 | `flagsByPlayer[8]` | `vector<Flag*>` per owner, in creation order [known] S 006661d0 |
| +0x108 | `streetById[8]` | `map<Unique, Street*>` per owner [known] S 00666210 |
| +0x168 | `flagById[8]` | `map<Unique, Flag*>` per owner [known] S 006661d0 |
| +0x1c8 | `pPathFinder` | the one `ai::nnet::StreetPathFinder` (§2.7) [known] S 00663d10 |
| +0x1cc | `cacheDisabled` (byte) | non-zero: path costs are searched every time and never stored [known] S 00667f30. 0 from the constructor and `InitPathFinder` (S 006685f0, S 00663d10); the only other writer is the user interface, which sets it to 1 around the availability query of flag action 10 and back to 0 (`nMenu::ActionButton::RefreshAvailability` S 00623da0), so it is 0 whenever the simulation runs [known for the writers found in the typed decompilation] |
| +0x1d0 | `pathCostCache[16]` | `map<Unique fromFlag, map<Unique toFlag, int cost>>`, index `player*2 + netKind` [known] S 00667f30 |
| +0x290 | `pNetContinentIds` | `ai::nnet::NetContinentIds` (§2.8) [known] S 006685f0 |

Erasing an element of `streetsByPlayer` / `flagsByPlayer` is a stable erase (elements behind move down) [known]
S 006652d0, S 00665c10.

### 2.2 `NNet::Flag` (0x1b8 bytes)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `pOwnerPlayer` | player entry; first dword = player index [known] S 0066b010 |
| +0x08 | `buildingRef` | the building whose entrance flag this is (may be invalid) [known] S 0066a8d0 |
| +0x28 | `cell` | map cell [known] |
| +0x30 | `unique` | the flag's id (id lo/hi at +0x38/+0x3c) [known] |
| +0x40 | `netContinent[2]` | one `Unique` per net kind (ids at +0x48/+0x4c and +0x58/+0x5c): the id of the connected component the flag belongs to (§3.5) [known] S 00667a30 |
| +0x60 | `searchMark` | scratch of flood fill and path search: −1 = not visited, else distance [known] S 0066cc30 |
| +0x64 | `links` | `vector<FlagLink>` (0x48 each), one per attached street, in attach order [known] S 0066b400 |
| +0x74 | `packageStacks` | `ai::nnet::FlagPackageStacks` (§2.4) [known] |
| +0x138 | `specialists` | `NNet::Specialists`: references to settlers attached to the flag by a settler order (specialist kind) [known] S 0066cec0. The settler is `NSettlers::Specialist` (walk to the flag, dig, return; `settlers-jobs.md` §3.10); the player command that orders one, `0x2000B`, does nothing in this build (`game-commands.md`) |
| +0x150 | `orders` | `NVillage::OrderContainer`: pending settler orders targeting the flag [known] S 0066a8d0 |
| +0x164 | `lastServedTicket` | int, −1 = none; admission ticket of the hand-over protocol (§3.9) [known] S 0064dae0 |
| +0x168 | `harborRef` | reference to a harbour (`ai::navy::Harbor`) when the flag is a harbour flag [known] S 00669e60 |
| +0x188 | `waitingSettlers` | references to settlers queued at this flag (arrived at a flag that is their route target, or waiting for a ship, §3.13) [known] S 00657b80 |
| +0x19c | `parking` | `ai::nnet::FlagParking`: owner flag + `vector<fine position>` of occupied waiting spots [known] S 0066d390 |
| +0x1b0 | `bDying` (byte) | set at the start of the destructor [known] S 0066a8d0 |

`NNet::FlagLink` (0x48): +0x08 reference to the flag at the other end, +0x28 reference to the street (cached
`Street*` at +0x40) [known] S 006712c0. Two flags may be joined by several streets (parallel links) [known]
S 0066a1f0.

### 2.3 `NNet::Street` (0x108 bytes)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `owner` | player entry [known] |
| +0x08 | `unique` | street id (lo/hi at +0x10/+0x14) [known] |
| +0x18 | `path` | `vector<cell>`: every cell from the start flag cell to the end flag cell, both included [known] S 006695a0 |
| +0x28 | `mid` | `path[size / 2]` (integer division) [known] S 006695a0 |
| +0x30 | `usable[2]` (bytes) | per net kind: may the street be used. `[0]` (goods) = a carrier reference is valid or type is 3; `[1]` (walking) = always 1 [known] S 00669cd0, S 00668ba0, S 00668ce0 |
| +0x38 | `startFlagRef` | flag on `path[0]` [known] S 00669050 |
| +0x58 | `endFlagRef` | flag on the last path cell [known] |
| +0x78 | `carrierRef` | first carrier [known] S 0053ca20 |
| +0x98 | `secondCarrierRef` | second carrier (pack animal or second helper) [known] S 0053cb20 |
| +0xb8 | `orders` | `NVillage::OrderContainer`: pending settler orders for a carrier of this street [known] S 00668e10 |
| +0xcc | `mapUpdater` | `NNet::StreetMapUpdater` (back pointer to the street) [known] |
| +0xd4 | `length` | int, edge weight (§3.4) [known] S 00668f90 |
| +0xd8 | `trafficCount` | int, deliveries in the current measuring period [known] S 0065b200 |
| +0xdc | `tickCounter` | int, ticks in the current measuring period [known] S 00668e10 |
| +0xe0 | `avgTraffic` | float32 [known] S 00668e10 |
| +0xe4 | `streetType` | enum below [known] |
| +0xe8 | `shipRouteRef` | reference to the ship route; only used and saved when type = 3 [known] S 00669090 |

`streetType` values:

| Value | Meaning | Evidence |
|---|---|---|
| 0 | land street, one carrier | [known] default of commands and of `PlaceFlag` splits S 00666900 |
| 1 | upgraded land street: a second carrier is ordered | [known] S 00668e10 |
| 2 | water street (over shallow water, §3.2) | [known] S 00776180, S 0052f5c0 |
| 3 | sea street: the street-graph image of a ship route between two harbour flags of one player; no map registration, no carrier | [known] S 005b71d0, S 006695a0 |

A street is *attached* when both flag references are valid; only attached streets are updated and announced to the
presentation layer [known] S 00665ef0, S 006695a0.

### 2.4 Flag package stacks

`ai::nnet::FlagPackageStacks` (0xc4, `Flag+0x74`): byte `active`, then 6 × `ai::logistics::PackageStack` at
stride 0x20 [known] S 0066b640.

`PackageStack`: +0x00 `capacity` (u32), +0x04 `goodsFilter` (good id, −1 = empty stack accepts any good), +0x08
`NTransport::PackageContainer` holding a `vector<ReferencePackage>` in push order [known] S 006713a0, S 00671400.

- `capacity` of every stack = `GameConfig+0x20` = `cfg_setFlagPackageLimit` [known] S 0066b640, S 0054c4a0. Shipped
  value 2, so a flag holds at most 6 × 2 = 12 packages [known, `config.lua`].
- A stack holds one good type at a time: pushing sets `goodsFilter` to the package's good id; removing the last
  package resets it to −1 [known] S 006713a0, S 00671400.
- Iteration over the packages of a flag (`NNet_FlagPackageStacks_IterNext` S 0066cdd0) is stack 0..5, inside a stack
  in push order [known].
- [inferred] The six stacks are plain slots; nothing in the logic ties stack *i* to hex direction *i* (the label
  "direction stack" in the type database comes from the count 6 only).

### 2.5 `NTransport::Package` (0x108 bytes)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `owner` | player entry [known] S 00651670 |
| +0x08 | `unique` | package id [known] |
| +0x18 | `goodId` | the good; a package is always exactly one unit [known] S 0064d020 |
| +0x20 | `movement` | `ai::transport::TransportMovement` (0x98), below |
| +0xb8 | `target` | `ai::transport::TransportTarget` (0x48), below |
| +0x100 | `ticket` | int, waiting priority at a full flag (§3.9) [known] S 006513b0 |
| +0x104 | `blockedCount` | int, number of failed put-down attempts (§3.9) [known] S 006513b0 |

`TransportMovement` (offsets relative to the package in brackets):

| Offset | Field | Meaning |
|---|---|---|
| +0x04 (+0x24) | `hasTarget` (byte) | 1 while a delivery target is set [known] S 0064f350, S 0064f380 |
| +0x05 (+0x25) | `hasNextWaypoint` (byte) | 1 while `nextWaypoint` is a valid next-hop flag cell [known] S 0064f470 |
| +0x08 (+0x28) | `carrierRef` | the settler that carries the package **or has claimed it** on a flag [known] S 0077ac50 |
| +0x28 (+0x48) | `flagRef` | the flag the package is registered on (id hi at package+0x5c) [known] S 0053c980 |
| +0x48 (+0x68) | `nextWaypoint` | cell of the next flag on the route, −1,−1 = none [known]. Every reader goes through `ai::transport::TransportMovement::GetNextWaypoint` S 0064ef90, which returns this cell only while `hasNextWaypoint` = 1; otherwise the cell of the flag in `flagRef` if that is valid; otherwise the cell of the settler in `carrierRef` if that is valid and his movement is not busy; otherwise an invalid cell [known]. "Next waypoint" in §3 always means this value |
| +0x50 (+0x70) | `placedOnFlag` (byte) | 1 = physically lying on a flag; 0 = in a hand or in cargo [known] S 0064f4c0, S 0064cd10 |
| +0x54 (+0x74) | `revalidateCount` | int, §3.6 [known] S 0064f510 |
| +0x58..+0x74 | next-hop cache | `cachedHop` cell, `cachedFrom` cell, `cachedFromNet` Unique (§3.6) [known] S 0064f3a0 |
| +0x78 (+0x98) | `shipRef` | ship whose cargo holds the package [known] S 0064f1d0 |

`TransportTarget`: +0x08 building reference (id hi at package+0xd4), +0x28 ship reference (id hi at package+0xf4).
Exactly one is valid when the package has a target [known] S 0064edb0. The **target flag**
(`TransportTarget::GetTargetFlag` S 0064ef20) is the building's entrance flag (`Building+0xa0`), or for a ship
target the flag of the harbour the ship is docked at or heading for: ship `+0x24` movement → `+0x60`
`targetHarbor` → harbour `+0x38` `flagRef` ([navy.md](navy.md) §2.2, §2.4, §2.6) [known]. A carrier counts as at
the package's destination only for a **building** target (`IsCarrierAtPackageDestinationFlag` S 0064d280 tests
the building reference, id hi at package +0xd4), so a package for a ship is put down on the harbour flag (§3.8,
state 0x12) and loaded from there (`navy.md` §3.10, `GatherCargo`) [known].

A package is in exactly one of these states [inferred from the functions that move it]:

| State | `flagRef` | `carrierRef` | `placedOnFlag` |
|---|---|---|---|
| lying on a flag, unclaimed | valid | invalid | 1 |
| lying on a flag, claimed by a carrier | valid | valid | 1 |
| carried | invalid (or valid for an instant during the drop) | valid | 0 |
| in ship / expedition cargo | invalid | invalid | 0 |

**Life cycle** [known]. `PackageSystem::CreatePackage` S 0064fb10 constructs the package (S 00651670: owner,
good, empty movement and target, `ticket = blockedCount = 0`, then one `Unique` drawn, then "package created",
slot 0x60) and appends it to `packages` and `packagesByPlayer`. The "created" notice is raised inside the
constructor, while the package lies nowhere: `CreateCarriedPackage` S 0064cce0 links it to the settler's hand
(S 0053c880) only after `CreatePackage` returns, and the other callers attach it to a flag afterwards; the
observer reads the position later from the package's movement. `PackageSystem::RemovePackage(id)` S 0064f780
finds it in `packages`, stable-erases it from `packagesByPlayer`, destroys it and stable-erases it from
`packages`. The destructor S 006514b0 raises "package destroyed" (slot 0x64) **first**; then
`TransportMovement::Destruct` S 0064f270 detaches it from its flag when `flagRef` is valid (stacks, "detached"
slot 0x6c, the flag's `lastServedTicket = −1`, §3.9) and, only in that case, unlinks a carrier reference; a ship
cargo link is unlinked in any case. The destructor does not unlink the carrier of a package that is in a hand
and on no flag; the callers that destroy such a package unlink him first (`DiscardPackage` S 0064cc90,
`NTransport::System::DeliverPackage` S 0064cc60 → `NeedSystem::DeliverPackage(pkg, keepCarrierLink = 0)`
S 00651bc0, §3.11).

### 2.6 `NTransport::System` (0x454 bytes, `NLogic::System+0x1c`)

| Offset | Part | Content |
|---|---|---|
| +0x04 | `initialised` (byte) | 0 from the constructor and `Reset`, 1 from `Init`; saved; no other reader found [known] S 0064cf20, S 0064cbb0, S 0064cb80, S 0064cdd0 |
| +0x08 | `PackageSystem` (0x98) | `packages`: `vector<Package*>` of all packages in creation order; `packagesByPlayer[8]` [known] S 0064fb10 |
| +0xa0 | `PackageNeedSystem` (0x28) | the **free packages** (no need assigned): `targets` = `vector<PackageNeedTarget*>` in registration order, and `byGood` = `map<goodId, vector<PackageNeedTarget*>>` [known] S 00651180 |
| +0xc8 | `NeedSystem` (0x38c) | the **needs**: +0x0c `GoodOrderStore` (open needs, indexed), +0x354 `GoodOrderIterator`, +0x37c `vector<NeedGood*>` of all needs in creation order [known] S 00652420 |

`PackageNeedTarget` (0x48): +0x08 package reference, +0x28 building reference = the building a free package is
being returned to (invalid until assigned) [known] S 0064fd80.

`NTransport::NeedGood` (0x70), one per requested unit: base `NLogic::Need` with +0x08 building reference, +0x28
ship reference (exactly one valid), +0x48 `goodId`, +0x4c `stamp` (tick of creation, later tick of last selection);
+0x50 `servingPackage` reference (valid = a package is on its way) [known] S 006528b0, S 00652e00.

`NTransport::NeedGoods` (0x18) is the per-building (or per-ship) list of requests, `Depot+0x44`: `owner`, and a
`vector<NeedGoodElement*>`; an element is `{goodId, packageRef}` and mirrors one `NeedGood` [known] S 0064eb80.

`ai::logistics::GoodOrderStore` (0x348): 8 `GoodOrderPlayerBlock` (0x68). A block has, per **category** 0..2, a
vector of bucket entries (0x18 each: `vector<NeedGood*>` at +4/+8, `goodId` at +0x10, `category` at +0x14) in order
of first use, and a `sortedIdx` vector giving the order in which the entries are visited [known] S 00652740,
S 006538f0.

Entries are never removed while the world runs [known]: `GoodOrderStore::AddNeed` S 00652740 creates the entry
of (category, good) on first use and appends the need; `RemoveNeed` S 006527a0 only erases the need pointer from
its entry (stable erase, `OrderBucketEntry::RemoveFirstValue` S 00568770), so an emptied entry keeps its place. The
creation order of the entries is therefore the order in which each (category, good) was first needed since the
world was built; after a load it is rebuilt from the open needs (§7), so a save and load can change the order in
which goods of equal rank are visited [inferred]. Both functions compute the category (`GoodOrder_GetCategory`
S 006541e0) from the building's state at the time of the call; `RemoveNeed` does not check the entry it finds
(`FindBucketForGood` S 006533c0 returns null when the category has no entry for the good) [known]. Whether a
need's category can change while it is in the index (a finished `depot` building whose construction values
become positive again) was not followed [TODO].

Need category (`GoodOrder_GetCategory` S 006541e0) [known]:

| Category | Condition |
|---|---|
| 1 | the need has no valid building reference (ship / expedition target) |
| 2 | target building's type has `depot` (`BuildingProperty+0x54`) and the building is finished (both construction `remaining` values ≤ 0) |
| 0 | every other building target (production input, construction material, ...) |

### 2.7 `ai::nnet::StreetPathFinder` (0x40 bytes)

+0x04 `bActive`, +0x05 `bFound`, +0x08 `netKind`, +0x0c start flag, +0x10 target flag, +0x14 open list
(`std::deque<Flag*>`), +0x28 `bCarrierPenalty`, +0x38/+0x3c preferred street id [known] S 0066cd20. One instance
exists; every search resets it afterwards (`NetPathFinder_Reset`).

**Net kind** [known] S 00669cd0, S 0066cc30:

| Kind | Edges that count | Used for |
|---|---|---|
| 0 | streets with `usable[0]` = 1: at least one carrier reference valid, or type 3 | goods, and every supplier / reachability test |
| 1 | all streets | settlers walking along streets |

### 2.8 `ai::nnet::NetContinentIds` (0x2c bytes)

Index between net continents (kind 0 and 1 share it) and the **map** continents (`NMap::Continents`, land masses)
their flags stand on: `map<mapContinentId, set<netContinentUnique>>`, `map<netContinentUnique, set<mapContinentId>>`
and `map<netContinentUnique, cell>` (cell of the first collected flag) [known] S 006705c0. Queried by
`NNet::System::ContinentIdsContain` S 00664f40 from `BuildingList_FindNearestReachable` S 00557fe0 [known].
The byte at +0x04 is an "in use" mark: 0 from the constructor, set by `NNet::System::InitPathFinder` S 00663d10
and by `NNet::System::Load` for saves older than section version 3, saved, and read only by `Load`, which clears
the index first when it is set [known] S 00670ac0, S 00668050, S 006707f0.

### 2.9 `NSettlers::Carrier` (0x200 bytes, derives from `NSettlers::Settler`)

Fields used here: settler +0x28 player entry, +0x30 carried/claimed package reference (id hi +0x44, cached pointer
+0x48), +0x50 `SettlerMovement*` (its +0x128 = current cell, +0xa0 street reference with id hi at +0xb4 and cached
`Street*` at +0xb8), +0x54 state [known] S 0065b200. Carrier +0x1b8 `notYetOnStreet` (1 until assigned to a
street), +0x1c0 building reference, +0x1e0 `reservedPackage` reference (the exchange partner, id hi +0x1f4, cached
pointer +0x1f8) [known] S 0065ab20, S 0064dae0. The eight embedded "movies" (sub state machines) are listed in
`docs/types.md` / the type database.

A first carrier and a second carrier are the same class; only the slot differs [known] S 0065a6f0.

Carrier overrides of the settler vtable (S 007f847c) used here [known]: slot 11 (+0x2c, "working position") =
S 0065ab00, which returns the address of `Street.mid` of the carrier's street; slot 14 (+0x38, "release links
before going home") = the empty stub S 005657b0, so a carrier that is sent home keeps his street slot until he
is deleted (§3.8).

---

## 3. Rules and algorithms

### 3.1 Placing a flag

`GameQuery::CanPlaceFlagAt(cell, player, allowBorder)` S 0052f8a0 [known]. All of:

1. `IsOwnedCellFree(cell, player, allowBorder)` S 0052f3d0: the cell is inside the map, its territory owner is the
   player, GridStates has none of water 0x4, cliff 0x40, logic object 0x400, blocked 0x1, deposit 0x80, building
   footprint 0x100, and (unless `allowBorder`) not territory border 0x20;
2. no flag-layer object on the cell or on one of its six neighbours (`ObjectLayers::AnyObjectInHexRange(layer 0,
   maxRadius 1, ...)` S 00672580: the cell itself, then ring 1);
3. none of the six neighbours has the harbour bit 0x2000.

`NNet::System::PlaceFlag(player, cell)` S 00666900 [known]; it performs **no** validity test itself, callers do:

1. Look up the street id on map object layer 2 at the cell.
2. **Split.** If there is a street and it is attached:
   a. copy its path; unlink its first carrier without discarding the carrier's package (only the first slot is
      looked at; in batch-editing mode the carrier is not taken over);
   b. `RemoveStreet` (the destructor releases what is left, §3.3);
   c. `pathA` = the old path from its start up to and including the cell; `pathB` = the old path from its **end
      backwards** down to and including the cell (so `pathB` starts at the old end flag);
   d. create the flag at the cell and register it;
   e. `BuildStreet(player, pathA, type 0)` then `BuildStreet(player, pathB, type 0)`. Both halves are type 0 with
      fresh traffic statistics, whatever the old type was;
   f. if a carrier was taken over: he is linked to street A (first slot) when his current cell is on A's path, or
      when A's start flag has a valid building reference and his current cell equals that building's cell
      (`Building+0x20`); otherwise to street B (`StreetNet_AssignCarrierToSplitStreet` S 00664fb0). His current
      cell is the cell at `SettlerMovement+0x28` when the movement float at `+0x04` is > 0 and the mode at `+0x44`
      is 2 ([inferred] the cell he is stepping to on a street walk), else his cell (`+0x128`).
3. **No split.** If there is a street but it is not attached (a street under construction): remove it from the map
   registration, create and register the flag, register the street again (so cell ownership is recomputed). With
   no street: create and register the flag.
4. Notify the map-change router for the cell (`MapUpdateBatch::RemoveObstructedDoodadsAtCell`, `MapUpdateBatch::InvalidateConstructionAroundCell`).
   [inferred] this is what removes doodads flagged `dd_setDeleteByStreet` and refreshes the construction map; it is
   local simulation code, not a network message.

`NNet::Flag::ctor` S 0066b010 [known]: sets `searchMark = 0` and `lastServedTicket = −1`; draws three `Unique`s
in this order: the flag's id, its kind-0 continent id, its kind-1 continent id (**a new id for each of its two net
continents**); initialises the stacks (every capacity from `GameConfig+0x20`, `active = 1`, S 0066b640), flattens
the terrain around the cell (`MapModifier::FlattenAroundCell`), raises `NetObjectAdded`, writes the flag id into
object layer 0 of the cell (`MapModifier::SetFlagAtCell`). The two fresh continent ids are not entered into
`NetContinentIds` (§2.8); a flag enters that index only when a recomputation (§3.5) collects it.
`FlattenAroundCell(cell)` S 00673bd0 [known]: the cell's centre vertex is `(4x (+2 on odd rows), 4y)` on the
vertex grid; the six vertices of vertex ring 1 around it are set to the centre vertex's height (integer copy, no
averaging), inside an elevation batch. GridStates water, shore and cliff bits are not refreshed by it
(`map-resources.md` §3.4).

### 3.2 Building a street

The command flow (start at a flag, extend by clicks, finish on a flag or on a free cell with a new flag) is in
`game-commands.md` §2.6 and commands `0x20006..0x20008`. This section gives what a valid street is.

**Search.** `StreetPlanner::ExtendTo(cell)` S 00663bf0 runs `NMap::AStar::FindPath(from = current path end,
to = clicked cell)` with the `NLogic::AStarStreet` cost functions, then `BuildPath(randomize = false)` [known]. If
`from` and `to` are hex neighbours the path is accepted without evaluating a step cost [known] S 00676900. A
clicked cell that already lies on the planned path starts no search (`StreetPlanner::CommitPathTo` S 00663a00)
[known]. Inside one map-update batch it cuts the path back to end on that cell, cancels the street under
construction (planner state 6), starts a new one at `path[0]` (`StreetPlanner::BuildStreet` → `CreateStreetAtFlag`,
which draws a new street id), adds the cut path with `AddPoints` and sets state 2.

The cell search itself is `NMap::AStar` (owner: `map-resources.md` §3.12); what decides *which* street is found
[known] S 00676700, S 0067bef0, S 0067c560, S 0067c0e0, S 00676d10:

- the open list starts with `to` (`g = 0`); `Step` pops the **front** node and visits its neighbours in direction
  order 0..5; a neighbour with step cost `c ≥ 0` gets `g = g(current) + c`, `h = HexDistance(neighbour, from)`,
  `f = g + h`; the search **stops the moment `from` is given a `g`**, not when `from` is popped;
- a neighbour is taken only if it was never reached or the new `g` is smaller than its best `g`; a cell that is
  improved while on the open list is re-inserted with its old `h`, a closed one is reopened;
- the open list is sorted ascending by `f`; a node goes before the first node with a greater `f`, i.e. behind all
  nodes with equal `f` (first in, first out among equals);
- `BuildPath` starts at `from` with direction 0. At each cell the *descent set* is the set of directions whose
  in-map neighbour has the smallest best `g` among the neighbours with `0 ≤ g ≤ g(cell) − 1`. The current
  direction is kept while it is in the set; otherwise the lowest-numbered direction of the set is taken. The walk
  ends on `to`.

Because the search ends when `from` is first reached, the result is a good path, not always the cheapest
[inferred].

**Endpoint test** (`AStarStreet::CanSearch` S 00776180, once per search) [known]:

| Type | Test |
|---|---|
| 0, 1 | `CanStreetPassCell(to)` S 0052fb10: `to` is a free owned cell (§3.1 item 1, border not allowed); and if `to` carries the street bit 0x2 without a flag and the street there is not the one being built, a flag must be placeable into that street (`CanSplitStreetWithFlagAt`, below) |
| 2 | `CanStreetStepTo(from, to)` S 0052f5c0, below |
| 3 | `IsHarborExitTransition(from, to)` S 0052e3c0: harbour→exit, exit→exit or exit→harbour cells (bits 0x2000 / 0x4000) |

**Step cost, types 0 and 1** (`AStarStreet::GetStepCost(a, b)` S 00776500; the cell tested is `b`; −1 = blocked)
[known]:

1. `b` must be a free owned cell (§3.1 item 1, border not allowed).
2. Unless `b` is the search's `from` cell (the current path end): if `b` has the street bit 0x2, the layer-2 street
   id there must be valid and equal to the street being built (so a foreign street can only be *ended on*, never
   crossed); and `b` must not already be in the path built so far.
3. `b` must not carry a flag-layer object, unless it is the `from` cell.
4. cost = `base(a→b) + base(b→a)`, where `base(x→y)` (`NMap::AStar::GetStepCost` S 00676840) is −1 if `y` is not
   walkable (GridStates blocked 0x1, water 0x4, cliff 0x40, footprint 0x100, logic object 0x400) and `y` is not
   the `from` cell; else 3, or 4 / 5 / 7 when the slope class from `x` to `y` is −1 / −2 / −3, plus 2 if `y` has
   GridStates bit 0x80.

   So a level step costs 6, a step with slope class magnitude 1 / 2 / 3 costs 7 / 8 / 10 [inferred: one direction
   is always the negative class]. Slope class 4 is not in the table and costs like level ground [known]; cells
   with such slopes normally carry the cliff bit and are excluded by walkability [inferred, `map-format.md` §5.7].
   Slope classes: `map-format.md` §5.3. The `+2` for bit 0x80 cannot apply to `b` (item 1 rejects such a cell);
   it can only apply to the reverse term when `a` carries the bit [inferred].

There is **no length limit and no slope limit** in the search other than the above [inferred: none is tested in
S 00776500, S 00676840, S 0052fb10, S 005300e0].

**Type 2 (water street)** [known] S 0052f5c0, S 00776330:

- It can only be started at an own flag that stands on a shore cell (GridStates 0x8) and has no harbour link
  (`Flag::GetWaterStreetBlockReason() == 0` S 0066a020, tested in `StreetPlanner::BuildStreet` S 006636e0).
- Endpoint test `CanStreetStepTo(from, to)`: both cells in the map; `to` has none of logic object 0x400, border
  0x20, moving-ship tile 0x10000; `from` is not border; once the path has 2 or more cells `from` must be a water
  cell; if `to` is not water and (`from` is not water or `to` is not a free owned cell), then hex distance
  `from`–`to` must be ≥ 2 and `from` must carry a flag; `to` must be shallow water or a shore cell; both cells
  must be owned by the player; if `to` has the street bit: with a flag on it the flag must pass
  `GetWaterStreetBlockReason() == 0`, without a flag the street there must be the one being built.
- Step cost `(a, b)`: `b` (unless it is `from`) must not carry another street, must not be in the path so far and
  must not carry a flag; then all of: `b` is `from`, or (`b` is water and (`a` is the search target or `a` is
  water)); `b` or `a` is water; `b` has none of border 0x20, logic object 0x400, ship tile 0x10000; `b` is owned by
  the player. Cost 2 if `b` has the shore bit, else 1 if `b` is shallow water, else blocked.
- *Shallow water* (`Map_IsShallowWaterCell` S 0052e550): `0 < waterLevel − height(cell centre vertex) ≤
  GameConfig+0x40` = `cfg_setMaxWaterStreetWaterDepth` (shipped 4000) [known].

**Type 3 (sea street)** is built by the navy code along a ship route: `NavyShipRoute::UpdateSeaStreet`
S 005b71d0 starts the navy's planner with type 3 and calls `BuildStreet(..., 3)` [known]; no other caller with
type 3 was found [inferred, caller list of `BuildStreet`]. (`NNavy::Expedition::Update` S 005b8ac0 uses the same
planner for a **type 0** street from the harbour flag to the entrance flag of the expedition building [known].)
Its search state and step cost: `PrepareSearch` S 00776260 acts in mode 3 only. When the target cell (`to`) has
the harbour-exit bit 0x4000, `mode3State` = the exit bit of the start cell (`from`: 0 or 1); else, when the target
has the harbour bit 0x2000, `mode3State` = 2; otherwise the state is left as the previous search set it [known].
`GetStepCostMode3` S 007761f0: if the target cell is a harbour exit, steps are free (cost 1) when the start cell is
not an exit and restricted to ship-route cells (bit 0x8000) when it is; if the target is a harbour cell, cost 1
everywhere [known]. Details: `navy-and-military.md`.

**A street may be completed** (`GameQuery::CanCompleteStreet` S 005300e0) when: `path[0]` carries a flag; the last
cell carries a flag, or `CanSplitStreetWithFlagAt(lastCell, type, player)`; and first and last flag differ [known].
It reads only the object-layer-0 ids of the two end cells and tests no owner: either end may hold another
player's flag. The owner tests are made by `BuildStreet` (steps 1 and 4 below), which then refuses the street
[known] S 005300e0, S 00666d00.

`CanSplitStreetWithFlagAt(cell, type, player)` S 0052f980 [known]: type is 0 or 1; layer 2 at the cell holds a
street; that street is attached; and `CanPlaceFlagAt(cell, player, allowBorder = false)`.

**Validity while planning.** Each tick every active planner is tested with `StreetPlanner::IsPathValid` S 00663900
(the planner's own validity query; every path cell inside the map, owned by the player and without border 0x20,
cliff 0x40, logic object 0x400, deposit 0x80 or footprint 0x100, `IsOwnedCellFree_AllowWater` S 0052f340; blocked
cells 0x1 and water 0x4 only allowed for type 2; own flag still on the first cell); an invalid plan is cancelled
[known], see `game-commands.md`.

**`NNet::System::BuildStreet(player, path, type)`** S 00666d00 [known]:

1. `path[0]` must be in the map and carry a flag of the player; else return null. From here on the function runs
   inside a map-update batch, closed on both exits.
2. Create the `Street` with `path[0]` (constructor S 00669cd0: draws the street's id, `AppendCell(path[0],
   notify = true)`, `usable[1] = 1`, `usable[0] = (type == 3)`; it is not attached, so no event is raised).
3. If `CanSplitStreetWithFlagAt(lastCell, type, player)`: `PlaceFlag(player, lastCell)` (this splits the street
   that passes there). Its `Unique` draws (§8) therefore come after the new street's id.
4. The last cell must now carry a flag of the player different from the start flag; else delete the new street
   (its id stays drawn) and return null.
5. Register the street (`streetsByPlayer`, `streetById`); append `path[1..n−1]` cell by cell with
   `Street::AppendCell(cell, notify = false)` (§3.4: no street events, terrain change deferred to the batch),
   reporting each of these cells to the map-update batch (`RemoveObstructedDoodadsAtCell` and
   `InvalidateConstructionAroundCell`). `path[0]` is not reported here; for a player's street,
   `CreateStreetAtFlag` reported it when the construction started.
6. `AttachStreetToFlags` S 006662f0: start flag = the flag-layer object on `path[0]` if it is a flag of the
   street's owner, end flag likewise on the last cell; a missing one is created with the flag constructor directly
   (no split, no harbour link) and appended to `flagsByPlayer` / `flagById` (its only caller is `BuildStreet`,
   where both flags exist by steps 1 and 4); then `StreetLink_LinkFlags(startFlag, endFlag, street)` (§3.5). In
   batch-editing mode (`NLogic::Edit` query, vtable +4) a carrier is spawned at once on the street's `mid` cell
   (`Street::SpawnCarrier` S 00668be0) [known]; in a normal game the carrier comes by settler order (§3.7).
7. Raise "street added" (slot 0x3c) once, now that the street is attached [known] S 00666d00.

The street under interactive construction (`NNet::StreetConstructorStreet`, S 00668830, S 006688d0) is a real
`Street` object created at the start flag by `CreateStreetAtFlag` S 00666590 and grown with `AppendCell`; it is not
attached (no end flag reference), so it is neither updated nor usable until `BuildPlannedStreet` hands its path to
`BuildStreet` [known]. `CreateStreetAtFlag` needs a flag of the player on the cell, constructs the street (one id
drawn), registers it in `streetsByPlayer` / `streetById` like a finished street (so it is saved, §7, and removed by
`PostLoad` for its missing flag references) and reports its cell (`path[0]`) to the map-update batch
(`RemoveObstructedDoodadsAtCell`, `InvalidateConstructionAroundCell`); `AddPoints` appends with
`notify = false` inside one batch [known] S 00666590, S 006688d0. It never becomes the finished street:
`BuildPlannedStreet` S 005289b0 takes its path out of the planner, which cancels it (`RemoveStreet`; its
destructor unlinks no flags and raises no event, since it is not attached, S 00669210), and then `BuildStreet`
creates a new street. So a street built by the player costs one id per start or restart of its construction
(command `0x20006`, the restart in `CommitPathTo`) plus the ids of `BuildStreet` [known].

### 3.3 Removing flags and streets

- **`RemoveStreet(id)`** S 006652d0 [known]: clear a selection of it; open a map-update batch of its own;
  `InvalidateConstructionAroundCell` for every path cell (no doodad report); stable-erase from `streetsByPlayer`;
  delete (the destructor below runs inside the batch); erase from `streetById`; close the batch. Callers [known,
  caller list]:
  the player command `0x20009` (`HandleRemoveStreet` S 00781290: street id → `RemoveStreet`, no owner check,
  `game-commands.md`); cancelling a street under construction (`StreetConstructorStreet::Cancel` S 00668880);
  `PlaceFlag` (split) and `RemoveFlag`; the two territory functions below; `PostLoad` (§7); the navy
  (`NavyShipRoute::UpdateSeaStreet` S 005b71d0); the computer player (`NAI::StreetConstruction` S 005a34a0); Lua
  `map_createDoodad` (below).
- **`Street` destructor** S 00669210 [known], in this order: raise "street removed" if attached and not type 3;
  for each valid carrier slot (first, then second): in a normal game unlink the carrier **and discard the package
  he carries** (a package he only claimed on a flag is released, not discarded, S 0064ced0), in batch-editing mode
  remove the settler; unlink both flags (§3.5) when the start flag reference is valid; unregister from the map
  (not type 3); remove every pending settler order of the street; unlink the ship route (type 3). The `Unique`
  draws this causes in a normal game [inferred from S 0053ca80, S 0053cb40, S 0053c720]: the carrier unlink that
  empties the street re-floods both end flags for kind 0 (2 draws; with two carriers only the second unlink does),
  the flag unlink re-floods the start flag for kind 1 (1 draw, plus 1 for kind 0 on a type-3 street); an unmanned
  attached land street draws 1, a street under construction none. An unlinked carrier has no street reference any more, so his next
  `Carrier::Update` S 0065b710 calls `Settler::StopAndSetState3` and he goes home (§3.8, "Losing the job")
  [known].
- **`RemoveFlag(id)`** S 00665c10 [known]: clear a selection of it; open a map-update batch of its own; remove
  every street attached to the flag (repeatedly the first link; each `RemoveStreet` nests its batch inside this
  one); stable-erase from `flagsByPlayer`; delete the flag; erase from `flagById`;
  `InvalidateConstructionAroundCell` for the flag's cell; if the flag had a building reference,
  `NVillage::System::RemoveBuilding(building, spill = true)` for that building, still inside the batch; close the
  batch. Callers [known, caller list]: the player command `0x20005` (`HandleRemoveFlag`
  S 007813d0); the per-tick territory test below; `NVillage::System::RemoveBuilding` S 00559db0, which removes
  the flag on the cell one step in direction 1 from the removed building's position (any owner; [inferred] its
  entrance flag) when that flag has no remove block reason, all six stacks are empty and
  it has no street link; `TransferBuildingOwnership` S 0055a210 and `TransferPlayerAssets` S 00529040; the
  computer player (`NAI::DestructionSystem::Update` S 0058de80).
- **`Flag` destructor** S 0066a8d0 [known], in this order: `bDying = 1`; raise `NetObjectRemoving`; clear layer 0
  of the cell; unlink the building; unlink every street link (§3.5); for every package on the flag's stacks: discard
  it if `placedOnFlag` is set, else only detach it (a package registered on the flag but still in a settler's hand:
  a drop in progress, §3.9); remove all pending settler orders of the flag; unlink all queued settlers; unlink the
  harbour.
- **Block reasons** for the player command: `Flag::GetRemoveBlockReason` S 00669f70, listed in
  `game-commands.md` (`0x20005`).
- **Lost territory, per tick.** `NNet::System::Update` removes every flag whose cell fails
  `IsPlayerTerritoryCell(cell, owner, allowWater = false, allowBorder = false)` S 0052f270, i.e. is no longer
  owned by the flag's owner, or has become water, border, cliff or logic object [known] S 00665ef0, S 00669e30.
  Removing a flag removes its streets and its building (above).
- **Lost territory, on territory change.** `RemoveForeignStreetsInRadius(pos, radius)` S 00665930 visits every
  cell within the radius and removes a street registered on layer 2 there when the cell is a border cell or its
  owner differs from the street's owner [known] S 00665690; its only caller is
  `MapModifier::OnTerritoryChangedAt` S 00673a50. `RemoveStreetsOutsideTerritory` S 00665750 (full refresh,
  only caller `MapModifier::RefreshTerritoryAll` S 00672eb0) removes every street except type 3 that has at
  least one path cell not owned by its player [known].
- Lua `map_createDoodad(x, y, type)` S 005ad880 [known]: when the created doodad's property has its blocking
  byte (`DoodadProperty+0x48`) set, the street registered on that cell (`GetStreetAtPos`) is removed.

### 3.4 Street geometry, length, map registration

`Street::AppendCell(cell, notify)` S 006695a0 [known]:

1. unless type 3: unregister the street from the map;
2. if `notify` and attached and not type 3: raise "street removed";
3. push the cell; unless type 3: register the street on the map;
4. `UpdateLength`; `mid = path[size / 2]`;
5. if the path has ≥ 2 cells and type is 0: reshape the terrain along the new segment
   (`MapModifier::SetElevationAlongStreet(prevCell, cell, skipFirst = (size == 2), skipLast = (cell carries a
   flag), deferNotify = !notify)` S 00673370). Types 1, 2, 3 never reshape; a type-1 street was reshaped when it
   was type 0;
6. if `notify` and attached and not type 3: raise "street added".

**Heights under a street segment** (`SetElevationAlongStreet(A, B, skipFirst, skipLast, defer)` S 00673370)
[known, disassembly; constants 0.25 at S 007e5df8 and 0.5 at S 007d4a90]. The centre vertices of two
neighbouring cells are 4 vertex steps apart in one hex direction `d` (vertex of a cell: `(4x (+2 on odd rows),
4y)`). If `d` is not 2, 3 or 4 the call is repeated with A and B swapped and the two skip flags swapped. Then:

```
hA = height[vertex(A)];  hB = height[vertex(B)]          # ints, read once before any write
delta = float32((hB - hA) * 0.25)
prev = cur = float32(hA);  v = vertex(A);  k = 1
if skipFirst:  cur = prev = float32(hA + delta);  v = step(v, d);  k = 2
for k in k..3:
    cur = float32(cur + delta);  v = step(v, d)
    if not (skipLast and k == 3):  height[v] = trunc(cur)                 # centre vertex
    s = trunc((prev + cur) * 0.5)                                         # computed in x87 from the float32s
    height[step(v, (d + 2) % 6)] = s;  height[step(v, (d - 2) % 6)] = s   # the two side vertices
    prev = cur
```

`trunc` is `__ftol2_sse` (toward zero). So the three vertices between the two cell centres are interpolated
linearly in quarter steps from A's height to B's height, and each pair of side vertices gets the mean of the
interpolated height at its step and at the step before. `skipFirst` leaves the whole first step (centre and
sides) unwritten; `skipLast` leaves only the centre vertex of the third step unwritten. The two end vertices are
never written. Only vertex heights change: the GridStates water, shore and cliff bits are not refreshed here
(`map-resources.md` §3.4). A changed vertex joins the elevation dirty rectangle when `defer` is set or a batch is
open; otherwise `ElevationRectChanged` is raised for the rectangle of A and B at the end.

**Length** (`Street::UpdateLength` S 00668f90) [known]: sum over consecutive path cells of
`1 / f(a→b) + 1 / f(b→a)`, accumulated in x87 floating point and truncated to int once at the end.
`f(x→y)` (`Movement_GetSlopeSpeedFactorOnLand` S 0052e250) = 1.0 if either cell is water, else by the slope class
from `x` to `y`: class 1 → 0.8, 2 → 0.6, 3 and 4 → 0.4, every other value (level and downhill) → 1.0
(S 0052d9e0). A level step therefore adds 2.0; a step of class 1 / 2 / 3 adds 2.25 / 2.6667 / 3.5 [inferred].

**Map registration** (`NNet::StreetMapUpdater` S 006710a0, S 00670fe0) [known]. For every path cell:

- the GridStates street bit 0x2 is set (cleared on removal) when `ShouldUpdateCellGridState` S 00670d40 holds:
  on the first cell not when the start flag has another street of type ≠ 3 or belongs to another player (with no
  start flag the predicate returns the cell's current bit: registering leaves the bit as it is, unregistering
  clears it if it was set); on the last cell not when the end flag has another street of type ≠ 3; and
  never when layer 2 at the cell holds a different valid street id;
- the street id is written into object layer 2 (cleared on removal) when `ShouldOwnStreetLayerCell` S 00670e80
  holds: never on the first cell; always on inner cells; on the last cell only while there is no end flag and no
  other street holds the cell.

"Start flag" and "end flag" in these two predicates are `StreetMapUpdater::GetStartFlag` S 00670cb0 and
`GetEndFlag` S 00670d00 [known]: the street's flag reference when it is valid; otherwise a lookup by cell: for the
start the flag-layer object on `path[0]` whoever owns it (`GetFlagAtPos`), for the end the **street owner's**
flag on the last path cell (`FindFlagAt(owner, cell, 0, 0)`). A street under construction has no flag
references, so both ends are resolved by cell: its first cell is treated like an attached start, and when its
open end reaches a cell with an own flag, that flag's other streets decide the bit as for an attached end.
"Another street of type ≠ 3" is `NNet_Flag_HasOtherNonState3Link` S 00670bd0: the flag has more links than its
type-3 links plus (one if this street is linked to it) [known].

So flag cells carry bit 0x2 while at least one land or water street ends there, layer 2 names the street only on
its inner cells (and on the open end of a street under construction), and type 3 streets leave no trace on the
map [inferred]. A street under construction counts: started at a flag with no other street, it passes the
first-cell rule and sets bit 0x2 on that flag's cell while it is planned [known: S 00670d40, S 006710a0].

### 3.5 Connectivity: links and net continents

`StreetLink_LinkFlags(flagA, flagB, street)` S 0053c6a0 [known]: add a `FlagLink` to both flags; set the street's
start / end flag reference by position; if the two flags' kind-1 continent ids differ → `RecomputeFlagContinent(
flagA, 1)`; if the street is type 3 and the kind-0 ids differ → `RecomputeFlagContinent(flagA, 0)`.

`StreetLink_UnlinkFlags` S 0053c720 [known]: remove both links, clear the street's flag references,
`RecomputeFlagContinent(flagA, 1)` and, for type 3, also kind 0. Note that only `flagA`'s side is re-flooded;
`flagB` keeps its old id, which is then no longer shared with `flagA` if the removal disconnected them [inferred].

Carrier link changes (kind 0 only) [known]:

- link a carrier to slot 1 (S 0053ca20, S 00668ba0): `usable[0] = 1`; if the two end flags' kind-0 ids differ
  → `RecomputeFlagContinent(startFlag, 0)`;
- link a carrier to slot 2 (S 0053cb20, S 00668bc0): `usable[0] = 1` only; **no** continent recomputation. The
  settler order system uses slot 2 only when slot 1 is occupied (S 00561e20), where the continents are already
  merged. The street swap (§3.10) can link slot 2 of a street whose slot 1 is empty: an upgraded street that
  lost its first carrier keeps only its second one (§3.7), and when two such second carriers swap, each unlink
  empties its street and re-floods both end flags, while the slot-2 links that follow set `usable[0]` without
  re-flooding. If the street was the only goods connection, its end flags then carry different kind-0 ids
  although the street is usable, and goods are not routed over it until a later kind-0 recomputation starts
  from a flag of either part [inferred from the three functions; not observed]. The kind-0 recomputations are
  exactly [known, caller list of S 00667a30]: a slot unlink that empties a street (S 0053ca80 / S 0053cb40,
  start and end flag), a first-slot link whose end flags differ (S 0053ca20), and `StreetLink_LinkFlags` /
  `UnlinkFlags` of a type-3 street. Any of these on a street touching either part re-floods that part through
  the swapped street and merges the ids again, so the gap lasts until the next carrier change (or type-3
  street change) of that player in either part [inferred];
- unlink (S 0053ca80, S 0053cb40): clear the slot; `usable[0]` = the other slot is valid; both end flags'
  `lastServedTicket = −1`; if the other slot is empty → `RecomputeFlagContinent` for the start flag and then for the
  end flag, kind 0 (two `Unique` draws); then, if requested by the caller, discard the package the carrier holds.

`RecomputeFlagContinent(flag, kind)` S 00667a30 [known] (no-op while the system is being cleared):

1. empty `pathCostCache[player*2 + kind]` of the flag's owner;
2. set `searchMark = −1` on all flags of that owner;
3. depth-first collect every flag reachable from `flag` through links whose street has `usable[kind]`, in link
   order (`NNet_CollectConnectedFlags` S 00666250): a pre-order recursion in which an unvisited flag
   (`searchMark < 0`) gets `searchMark = 1`, is appended to the list, and then has its links followed;
4. draw a **new** `Unique`; for every collected flag remove its old continent from `NetContinentIds` and store the
   new id in `netContinent[kind]`;
5. `NetContinentIds::AddNetContinent(newId, collectedFlags)` S 006705c0: for every collected flag, the map
   continent id of its cell joins the new id's set (and the new id joins that map continent's set); the cell of
   the first collected flag (`flag` itself) is stored as the new id's cell.

"Remove its old continent" is `NetContinentIds::RemoveNetContinent(oldId)` S 006706e0, which erases the id
entirely (its set of map continents, its entry in every map continent's set, its cell) when it is present and
does nothing otherwise [known]. The old id is shared by the whole old component, so the first collected flag
removes it for all of them. After `StreetLink_UnlinkFlags` re-floods only `flagA`'s side, the flags of a part that
the removal cut off keep the old id, which is no longer in the index; they still compare equal among themselves,
so connectivity tests (below) are unaffected, but `NNet::System::ContinentIdsContain` S 00664f40 is false for that
id until a recomputation reaches the part [known for the functions; inferred consequence]. The same holds for a
new flag (§3.1). The index's only reader in the simulation is mode 1 of `BuildingList_FindNearestReachable`
S 00557fe0 (a settler's home search, `settlers-jobs.md` §3.2, net kind 1): a building of the player counts when
the map continents of the settler's cell and of the building are equal or joined by one of the player's sea
routes (`Navy_AreContinentsConnectedForPlayer` S 0052eba0, true at once for equal ids), or else when the index
lists the kind-1 net continent of the building's entrance flag under the settler's map continent [known]. So only
a settler on another land mass than the building can be affected [inferred].

Two flags are *connected for kind k* iff their `netContinent[k]` ids are equal (`NLogic_UniqueArray40_IsEqualAt`
S 00663d90) [known]. This test is the gate of every search below and of all supplier queries.

Consequence [inferred]: a street takes part in goods transport from the tick its carrier reference is set. A
settler order links the carrier to the street when the settler is *spawned* at the supplier
(`village-buildings.md` §3.12, "Arrival"), so the street counts as manned while the carrier is still walking to it.

### 3.6 Path search over the flag graph

`StreetPathFinder::Search(start, target, kind, bCarrierPenalty, preferredStreetId)` S 0066cd20 [known]:

1. if `start.netContinent[kind] != target.netContinent[kind]`: not found;
2. `searchMark = −1` on all flags of the start flag's owner; `start.searchMark = 0`; insert `start` into the open
   list;
3. loop `Step` S 0066cc30: pop the front flag; if it is the target → found; else for each link in link order whose
   street has `usable[kind]`: `d = current.searchMark + GetLinkCost(link)`; neighbour unvisited → set and insert;
   `d <` neighbour's mark → set and re-insert;
4. the open list is kept sorted ascending by `searchMark`; an element is inserted **behind** all elements with an
   equal mark (`OpenListInsert` S 0066c9a0), so equal distances are served first-in first-out.

This is Dijkstra's algorithm with early exit at the target (no heuristic).

**Edge cost** (`GetLinkCost` S 0066b9e0) [known]:

```
if preferredStreetId is valid and link.street.id == preferredStreetId: return 1
cost = street.length
if kind == 0 and bCarrierPenalty:
    if first carrier valid and he is not carrying a package:  return cost
    if second carrier valid and he is not carrying a package: return cost
    cost = cost * 3
return cost
```

"Carrying a package" = the carrier's package reference is valid and that package has `placedOnFlag == 0`
(S 0065a770). So a goods street whose every carrier has a package in hand costs three times its length; so does a
sea street, which has no carriers at all [inferred]. This is the load-balancing rule of goods routing.

**Route reconstruction** (`CollectPathCells` S 0066cb40, `GetPathCost` S 0066be20) [known]: from the target, with
`best = current.mark`, scan the links in link order (usable for the kind): a neighbour qualifies when
`0 ≤ neighbour.mark < best` and `GetLinkCost(link) == best − neighbour.mark`; it becomes the predecessor and
`best = neighbour.mark`. The comparison uses the **running** `best`, not `current.mark`, so in the code a later
link could replace the first qualifying one [known]. It never does [inferred]: a second link would need
`cost₂ = mark₁ − mark₂` with `mark₂ < mark₁ < current.mark`; that neighbour was popped before `current` (smaller
mark, every edge cost ≥ 1) and relaxed the same link, which gives `current.mark ≤ mark₂ + cost₂ = mark₁`, a
contradiction. The predecessor is therefore the **first** qualifying link in link order, it lies on a shortest
path, and the walk ends at the start flag (mark 0). Repeat from the predecessor until the start flag.
`GetLinkCost` is evaluated again here, with the carrier
state of that moment (same tick as the search). The cell list is target first, start last. `GetPathCost` sums
`current.mark − best` over the steps.

**Callers and their parameters** [known]:

| Caller | kind | penalty | preferred street | Result used |
|---|---|---|---|---|
| `GetFlagPathCost(from, to, kind)` S 00667f30 | given: 0 from the supplier and free-package searches (S 00557da0, S 00652170, S 006506a0); 1 from the carrier give-up search (§3.9, S 0065b200 → S 00557fe0 → S 00557ef0). The penalty flag is always passed but only has an effect for kind 0 (S 0066b9e0). Further direct callers: the village supplier queries S 00558330 and S 00558510, the settler order supplier search S 00562280 and the computer player (S 00599540, S 005a4cc0, S 005a4f30) [known, caller list; the kind they pass was not read] | yes | none | summed cost, −2 = not connected |
| `GetNextHopFlagCell(start, target, kind, penalty)` S 006666d0 | 0 | yes | none | cell of the flag after `start` on the route; (−1,−1) if none; if the route has a single cell, that cell: with `start == target` the path is the one flag, so a package on its target flag gets that flag's own cell as next hop [known] |
| `StreetRoutePlan::Plan` S 007735b0 (walking settlers) | 1 | no | the street the settler is on | next flag cell |

**Cost cache** (`GetFlagPathCost`) [known]: look up `pathCostCache[player*2 + kind][from][to]`, then `[to][from]`;
on a miss search and store under `[from][to]` (also the value −2). The cache of a player and kind is emptied only
by `RecomputeFlagContinent` for that player and kind (§3.5) and by `Clear`. It is **not** invalidated when a
carrier picks up or puts down a package, so the ×3 factor in a cached cost is the one of the tick the pair was
first asked for [inferred]. The cache is saved and is part of the checksum (§7, §8). The cache is keyed by the
owner of `from`; `GetNextHopFlagCell` S 006666d0 neither reads nor fills it [known].

**Next hop of a package** (`TransportMovement::ComputeNextHop(fromCell, force)` S 0064f3a0) [known]: one-entry
cache keyed by `fromCell` and the kind-0 continent id of the flag there; on a miss or with `force`,
`GetNextHopFlagCell(flag at fromCell, targetFlag, 0, penalty = true)`. `SetNextHop` (S 0064f470) calls it with
`force`, stores the result in `nextWaypoint`, sets `hasNextWaypoint = (x != −1)` and clears the cache.

**When a package's route is (re)computed** [known]:

| Event | Action |
|---|---|
| a target is set (`TransportTarget::Set` S 0064edb0) | `hasTarget = 1`, `hasNextWaypoint = 0`, waypoint and cache cleared; no search yet |
| the package is put on a flag (`OnPlacedOnFlag` S 0064f4c0) | `placedOnFlag = 1`, waypoint cleared; if it has a target: `SetNextHop(flag cell)`; `revalidateCount = 0` |
| a free package is assigned a return building (S 0064fd80) | target set to the building, then `SetNextHop(cell)`; if the package has a carrier reference to a settler of type Carrier with an exchange reservation, that reservation is dropped |
| every 3rd tick, for every package with `hasTarget` that is registered on a flag (`flagRef` valid) and has no carrier reference (`RevalidateNextHop` S 0064f510) | if it has a waypoint, `revalidateCount < 200`, the owner's flag on the waypoint cell exists, is in the target flag's kind-0 continent and is directly linked to the package's flag (`Flag::FindLinkToFlag` S 0066a170: any link, whatever its street's `usable`): `revalidateCount += 1`; otherwise `revalidateCount = 0` and `SetNextHop(flag cell)` |
| the target is cleared (S 0064eee0) | `hasTarget = 0`, cache cleared (the waypoint is left as it is) |

So a waiting package re-plans on the check after 200 successful ones (about every 600 ticks), and on the next
check (within 3 ticks) when it has no waypoint, when its waypoint flag is gone or no longer in the target flag's
kind-0 continent, or when no street joins its flag to the waypoint flag any more. A next street that only loses
its last carrier does **not** trigger it: the unlink re-floods both end flags (§3.5), the waypoint flag lies on
the target's side of that street and keeps sharing the target's kind-0 id, and the link is still there; the
package keeps its waypoint and waits for the street's next carrier (`Street::Update` orders one, §3.7) or for the
200th check [inferred from S 0064f510, S 0066a170, S 0053ca80]. A claimed or carried package is
not re-planned by this rule. The check only runs for packages with `hasTarget` (S 006513a0) whose `flagRef` is
valid and whose `carrierRef` is invalid; `placedOnFlag` is not tested [known].

### 3.7 Street update: carriers and upgrade

`NNet::Street::Update` S 00668e10, once per tick for every attached street [known]:

```
tickCounter += 1
if tickCounter > 6000:
    n = trafficCount; tickCounter = 0; trafficCount = 0
    avgTraffic = (avgTraffic + float(length * n)) * 0.5          # float32
    if tribe.secondCarrierId != -1 and streetType == 0 and avgTraffic > 130.0:
        streetType = 1; raise "street upgraded" (CallbackManager slot 0x44)
if streetType == 0 or streetType == 2:
    if carrierRef invalid and orders is empty:
        order = OrderSystem.CreateOrder(good 0x7bff15ce); link order to this street
elif streetType == 1:
    if secondCarrierRef invalid and orders is empty:
        order = OrderSystem.CreateOrder(tribe.secondCarrierId); link order to this street
```

- 0x7bff15ce is the settler good `good_helper` ("Helper", settler type Carrier) [known, `Jobs.lua`].
- `tribe.secondCarrierId` = `TribeProperty+0xb0` = `tp_setSecondCarrierId` [known] S 0054ad40: Bavarians
  `good_oxen` (a settler good that costs one `oxen` good), Egyptians `good_helper`; the Scots have no call, so
  their streets never upgrade [known, `tribes.lua`; the unset value is −1, written by the `TribeProperty`
  constructor S 00556300].
- `trafficCount` is incremented by the street's carriers: once when a package is delivered into a building and once
  after every put-down on a flag (§3.8) [known] S 0065b200.
- A measuring period is 6001 ticks. With constant traffic `avgTraffic` converges to `length × deliveries per
  period`; from 0, one period needs `length × deliveries > 260` to upgrade [inferred].
- A type-1 street never orders a first carrier again (the branch is exclusive). The settler that arrives for a
  street order takes the first slot if it is empty, else the second (`VillageOrder_LinkSettlerToDestination`
  S 00561e20) [known]. A type-1 street that lost only its first carrier orders nobody and goes on with its
  second carrier alone [known]: unlinking slot 1 leaves `usable[0]` = "slot 2 valid" (S 00668ce0), and the
  second carrier's state machine reads nothing of slot 1 (S 0065b200). Consequence [inferred]: one that lost
  both orders the second-carrier good twice, one after
  the other, and the first arrival takes the first slot.
- `streetType` is written by the constructors (the type given, 0 for the load constructor), by `Load` and by
  the upgrade above; no code path sets a type-1 street back to 0 [known for the writers found in the typed
  decompilation: S 00669cd0, S 006694a0, S 00669b30, S 00668e10].
- Type 3 streets order nobody.
- The order is served by the settler order system (supplier = nearest connected `depot` building holding the
  settler good or its cost, `village-buildings.md` §3.12).

### 3.8 The street carrier

`Carrier::Update` S 0065b710, per tick in the settler update [known]: base settler update; if the settler is in an
idle-like state do nothing; if `notYetOnStreet` → `UpdateDropOffAfterSpawn`; else if he has a street →
`UpdateStreetTransport`; else stop.

**State machine `UpdateStreetTransport`** S 0065b200 (settler state at +0x54) [known]:

| State | Running | On completion / per tick |
|---|---|---|
| 1 | (start) | start *LeaveBuilding* → 0x11 |
| 0x11 | LeaveBuilding | → 0x16 |
| 0x16 | WaitForPackage | done with no claimed package → stop. Claimed package's next waypoint not on my street's path → release the claim. Standing on the package's flag → *Pickup* → 0x18. Else, if my cell is on my street's path → walk to the package's flag (*MoveToStreetPosition*) → 0x17 |
| 0x17 | MoveToStreetPosition | arrived and the claimed package still lies on a flag: on its flag → *Pickup* → 0x18; else release the claim. → 0x16 |
| 0x18 | Pickup | no package any more → 0x16. Package's next waypoint not on my street → *PutDownPackage* → 0x19. Else *GoToPackageTarget* → 0x12 (if that cannot start → 0x16) |
| 0x12 | GoToPackageTarget | done: package has a **building** target and I stand on its destination flag (next waypoint = target flag = my cell; `IsCarrierAtPackageDestinationFlag` S 0064d280, so a package for a ship is put down at the harbour flag) → *EnterBuilding* → 0x13; else *PutDownPackage* → 0x19. Not done but waiting at the flag with `blockedCount > 360`: **give up** (§3.9) → 0x16 |
| 0x13 | EnterBuilding | → 0x14 |
| 0x14 | (instant) | if the package has a target: `street.trafficCount += 1`, `NTransport::System::DeliverPackage`. Start *LeaveBuilding* → 0x15 |
| 0x15 | LeaveBuilding | carrying a package → *PutDownPackage* → 0x19; else → 0x16 |
| 0x19 | PutDownPackage | On completion `street.trafficCount += 1` (also when nothing was put down). Not carrying any more → 0x16. Still carrying (an exchange happened, or the movie ended without a drop because no flag stands on his cell or the flag refused, S 0077a8e0): if the carried package's next waypoint is not my cell → *GoToPackageTarget* → 0x12; if it is my cell, step one cell onto the street (path index 1, or `size − 2` when standing on the last cell) → 0x1a |
| 0x1a | (walking one cell) | movement finished → *GoToPackageTarget* → 0x12 |

`IsInWorkCycle` (S 0065a800) is true in states 0x12..0x15 and 0x17..0x1a.

**WaitForPackage** S 0077ac50 [known]: the carrier waits at his working position (settler vtable +0x2c =
S 0065ab00: the `mid` cell of his street, §2.9). While he stands there he looks for work only
when `(tickCounter + settler.unique.idLo) % 20 == 0` [known; `Settler.unique` is the `NLogic::Unique` at
settler+8, whose `idLo` is at +8, S 00656c20]; when displaced he looks every tick. If his cell is on his street's path and
`CarrierChoosePackageOnStreet` returns a package, he **claims** it (package `carrierRef` = him) and the movie ends.
Otherwise, when displaced: if `ai::settlers::SettlerMovement::StopAndIsCellCentered` holds and the walk back to the working
position can be started, he walks back (movie step 0x15, then waiting again); if not, the movie **ends without a
package**, which in state 0x16 leads to `Settler::StopAndSetState3` (table above) [known].

**Losing the job** (`Settler::StopAndSetState3` S 00656740; owner of the details: `settlers-jobs.md` §3.2–§3.4)
[known]: call settler vtable +0x38 (empty for a carrier, §2.9), `state = 3`, start the `LeaveMap` movie
(settler +0x78), whose `Start` S 00776d00 **discards a package in his hand**
(`Transport_DiscardHeldPackage`) and cancels his route. State 3 is one of the states {0, 2, 3, 5, 6} in which
`Carrier::Update` does nothing after the base update (S 006567f0); the base update only leads from 3 to 2 or to
dying, so a carrier never returns to work. When the movie is done, the base update S 00656ec0 looks for the
owner's building near his cell (list `NVillage::System+0x20` for a carrier, search of `settlers-jobs.md` §3.4);
found and within hex distance 1 → state 2, and the settler system
then books him into that building and deletes him; otherwise he dies. Consequences for this subsystem:

- a carrier whose street was removed is already unlinked (§3.3);
- a carrier sent home **while his street still exists** (WaitForPackage ended without a package; the checks of
  `UpdateStreetTransport`) stays in the street's carrier slot until he is deleted: `Carrier::dtor` S 0065afb0
  releases his packages and unlinks the slot (§3.5). Until then the street counts as manned (`usable[0]`, no new
  order from `Street::Update`) although nobody carries on it [known]: the two slot unlinks S 0053ca80 /
  S 0053cb40 are called only from the carrier destructor, the street destructor S 00669210, the street split
  in `PlaceFlag` S 00666900 and the street swap S 0077a2f0. He holds no package (discarded by `LeaveMap`), so
  the path search charges the street its plain length, not the ×3 of §3.6. The movie ends that way only when
  he is displaced from `mid`, found no package, and either his fine position is not the centre of his cell
  (S 00657ea0) or `StartStreetMoveTo(mid)` S 00657f50 returns false [known]. `StopAndIsCellCentered` first
  halts any fine or rough move and then compares the fine position with the cell centre, so a carrier caught
  between two cells fails it. The walk back is `MoveToWorkingPlace` (slot 3 S 007775a0 → `StartMove`
  S 007780e0, a tail jump to `StartStreetMoveTo`, whose result is the movie's start result); it is false when
  he is not on `mid` and `AdvanceStreetRoute` S 00657b80 starts nothing: a route end is requested, the
  street stop distance equals his distance to `mid`, `PlanStreetRoute` leaves no next waypoint, or
  `StartRoughMove` fails [known]. In which play situations a waiting carrier is off his cell centre or has no
  street route to `mid` is not established [TODO, §10 Q1: live];
- the helper that brought a good out of a building (below) goes home the same way.

**Choosing a package** (`CarrierChoosePackageOnStreet` S 0064d8d0, `FindBestPackageToCarry` S 0064d7e0) [known]:

`FindBestPackageToCarry(flag, otherFlag)`: among the packages on `flag` (stack 0..5, push order) that await pickup
(`hasTarget`, `hasNextWaypoint`, no carrier reference) and whose next waypoint is `otherFlag`'s cell:
`score = rank(good)`; `+50` if `otherFlag` is full for that good and there is no exchange partner on `otherFlag`
for it (`FindBestSwapPackageOnFlag`); the lowest score below 100 wins, the first found on a tie.

`rank(good)` = the owner's `NPlayer::GoodPriorities` rank, 0 if the good is not in the list (S 005c2620); default
ranks come from `gp_setTransportPriority` (0..18 in the shipped data); **a lower rank is carried first** [known].
The rank is read only by `CarrierChoosePackageOnStreet`, `FindBestPackageToCarry`, `FindBestSwapPackageOnFlag`,
`AddFlagFullWaitTick` S 006513b0 and the need-index sort S 006538f0 (caller list of S 005c2620); no package
creator consults the list [known]. A player can therefore own packages of goods outside it [known]:
`NVillage::System::ConquerBuilding` S 0055a890 moves both stocks of the old building into the new owner's
replacement building, which keeps the old building type, with no good filter; its callers are the script
functions `vi_changePlayerOfBuilding` S 005ae830 and `pl_changePlayer` (`TransferPlayerAssets` S 00529040 →
`TransferAllBuildingsOfPlayer` S 0055aac0). Between players of different tribes the goods (which are
tribe-specific ids except `wood`, `plank`, `corn`, `flour`, `water`, `weapons` and the sacrifice goods,
`tribes.lua`) then leave that building as the new owner's packages through needs of its own type, the supplier
search or the removal spill, at rank 0. A `0x20021` list that omits goods does the same for the omitted goods
(the executor validates nothing, `game-commands.md`); the settings panel sends the whole list. Military
capture (`Military_SoldierCaptureTargetBuilding` S 00571af0) calls `TransferBuildingOwnership` S 0055a210
directly, whose replacement is built from owner, type and cell only, so it moves no stock [inferred]. The
shipped campaign maps C01, C04 and C06 call `pl_changePlayer`; whether the two players' tribes differ there was
not checked.

`CarrierChoosePackageOnStreet`: if the carrier stands on one of the two end flags, first try that flag towards the
other end; if that gives a package, take it. Otherwise `A = best(start→end)`, `B = best(end→start)`;
`scoreA = rank(A) (+50 if the end flag is full for A's good)`, `scoreB` likewise against the start flag; 100 if
there is no candidate; choose B if `scoreB <= scoreA`, else A [known].

**GoToPackageTarget** S 0077a260, S 0077a2f0 [known]: the walk target is the package's next waypoint and must be on
the carrier's street path, else the movie fails to start. `Start` S 0077a260 starts the walk and, when the street
path of his movement is active (`SettlerMovement+0x80`) and he stands on his street, calls `CancelRoute` right after
[known].

- *Walking* (step 0x16): each tick, if his cell is on the street and a flag of his player stands on the cell at
  `SettlerMovement+0x38` (`rough.finalTarget`, the target cell of his current rough move, written by
  `NMovement::Rough::StartMoveTo` S 00773c10, the only writer in the movement classes, set to (−1, −1) by the
  constructor S 00773d80 and restored by `Rough::Load` S 00773b80 [known]; [inferred] the destination flag of
  his walk, the package's next waypoint, not the next step cell): if `ShouldKeepWalkingToFlag` → go on; else if
  `Transport_CarrierTryPlacePackageOnFlag(flag)` fails he is held ([inferred] `SettlerMovement` stop distance 1,
  S 00657640) and the test repeats next tick (so `blockedCount` and `ticket` of §3.9 grow **every tick** in this
  phase); when it succeeds the hold is cleared. When the walk sub-movie finishes: if he is still held, the hold is
  cleared and the movie goes to step 0x14 (waiting); otherwise the movie is done.
- `ShouldKeepWalkingToFlag(carrier, flag)` S 0064d1a0 [known]: with an exchange reservation →
  `CanSwapPackagesAtFlag(carried, partner, flag)`; else true when the carried package has a **building** target,
  `hasNextWaypoint`, its next waypoint is its target flag and equals `flag`'s cell (final destination); else true
  when the package is already registered on a flag (`flagRef` valid, i.e. admission was granted earlier); else
  false.
- *Waiting at the target* (step 0x14): when `(tickCounter + settler.unique.idLo) % 10 == 0`: take the flag at the
  package's next waypoint (or at his own cell if the waypoint is not on his street) and
  `Transport_CarrierTryPlacePackageOnFlag`; on success the movie ends if he stands there, else it restarts.
  On failure, when `(tickCounter + settler.unique.idLo) % 200 == 0`, try the **street swap** (§3.10).

**Pickup / Drop** (S 007781e0, S 00777e00, S 00777d10, S 00777d50) [known]: each movie arms the settler action
timer (`NSettlers::Animation`, settler +0x18) twice. In **both** movies the first phase (before the hand-over) is
timer kind 2 with duration `GameConfig+0x10` = `cfg_setDropTime` (S 0054c440), and the second phase (after the
hand-over) is timer kind 3 with duration `GameConfig+0x0c` = `cfg_setPickupTime` (S 0054c410); both are 3.3 in
`config.lua`. The timer is a float that is decremented by 1.0 per logic tick in the settler update and expires
when it is ≤ 0 (S 0065f040), so the unit is ticks and 3.3 lasts 4 ticks per phase [known; the tick count is
inferred arithmetic]. Pickup hand-over: detach the claimed package from the flag, `placedOnFlag = 0`
(S 0064cd10). Drop start: `CarrierBeginDropAtFlag`; drop hand-over: `PutDownCarriedPackage` (§3.9).

**Carrier created with a package** (`UpdateDropOffAfterSpawn` S 0065ad70) [known]: this is how a good leaves a
building. `NTransport::System::SpawnCarrierWithPackage` S 0064d020 spawns a `good_helper` carrier inside the
supplier building holding a new package (stock −1). State 1: if he holds no package (or it already lies on a
flag) → *LeaveBuilding* (0x11) at once; else find the flag near his position
(`FindFlagNearPos` S 00664c50: the cell one step in direction 1 from the position, else that cell's neighbours in
directions 0, 1, 2); if none → stop; if `Transport_CarrierTryPlacePackageOnFlag` succeeds → *LeaveBuilding*
(0x11); else stay in state 1 and retry next tick. After leaving: no package in hand → stop; a flag stands on his
cell → *Drop* (0x19), else stop. In 0x19: no flag on his cell → stop; when the drop completes and he carries
nothing → stop, else the *Drop* movie is started again. "Stop" is `Settler::StopAndSetState3`: the helper walks
home, is booked into a building and deleted ("Losing the job" above).

**Destruction** (`Carrier::ReleasePackages` S 0065aec0) [known]: a carried package is discarded, a merely claimed
one is only unlinked from him (released, not discarded), the exchange reservation is unlinked; the street slot is
cleared (§3.5).

### 3.9 Hand-over at a flag, flag capacity, congestion

**Stack tests** [known]:

| Function | True when |
|---|---|
| `PackageStack::IsFullOrRejectsType(good)` S 006713c0 | filter set and ≠ good, or count ≥ capacity |
| `PackageStack::CannotAccept(pkg)` S 00671530 | not (pkg already on it), and (filter set and ≠ pkg.good, or count ≥ capacity) |
| `FlagPackageStacks::IsFullForGood(good)` S 0066b6f0 | all 6 stacks `IsFullOrRejectsType` |
| `FlagPackageStacks::CannotAcceptPackage(pkg)` S 0066b6b0 | all 6 stacks `CannotAccept` |
| `FlagPackageStacks::CannotTakePackage(pkg)` S 0066b970 | scanning stacks 0..5: return false at the first empty stack, at a stack containing pkg, or as soon as two stacks accept pkg; true otherwise |

`CannotTakePackage` is the admission test for a carrier: once all six stacks are in use, a package is admitted
only while **two** stacks could still take it, so the last free place of a flag is held back [known]. It is what
the carrier and worker code asks; `IsFullForGood` is what suppliers and the spill code ask.

**Choosing the stack** (`FlagPackageStacks::AddPackage` S 0066b730) [known]: scan stacks 0..5 with
`CannotAcceptReserveLast` S 00671590 (like `CannotAccept`, but when exactly one place is left on the stack and the
package is routed (`hasTarget`, `hasNextWaypoint`), the place is refused if every routed package already on the
stack has the same next waypoint as this package's *following* hop computed from its waypoint; it is granted if one
differs). The first stack that passes takes the package, unless two earlier stacks passed plain `CannotAccept` (and
failed only the reserve rule), in which case the first of those takes it. If no stack passes the reserve rule, the
first stack passing `CannotAccept` takes it. If none, the package is **not stored on any stack** although its
`flagRef` is set [known]. The attach function tests nothing itself; of its six callers [known, caller list]:
`CreatePackageAt` S 0064cd90 (aborted construction; its only caller `Construction::AbortAndReturnGoods`
S 0055ed30 tests `IsFullForGood` per unit) and `SpillGoodsOntoFlag` attach only when the flag is not
`IsFullForGood`; `UnloadPackageFromCargo` S 0064d0b0 (a ship unloading at its harbour flag; its only caller
`NavyCargo::UnloadOnePackage` S 005bcea0), `Transport_CarrierTryPlacePackageOnFlag` and the unregistered case of
`CarrierBeginDropAtFlag` attach only after `CannotTakePackage` = false. Each of these tests implies that one
stack accepts the package [inferred]. Two paths attach without a stack test: `CarrierBeginDropAtFlag` when it
moves a package that is registered on a different flag, and `PutDownCarriedPackage` for a settler that is not of
type Carrier (and for a carrier after an exchange, where the partner's place has just been freed) [known]; the
stack-less case can only arise there [inferred]. **Fate of a stack-less package** [known]: every
code that finds packages *on a flag* walks the stacks (`NNet_FlagPackageStacks_IterNext` S 0066cdd0; callers
`FindBestPackageToCarry` S 0064d7e0, `FindBestSwapPackageOnFlag` S 0064d2f0, the ship loaders `GatherCargo`
S 005b8470, `LoadAtHarbor` S 005bd4e0 and `NavyHarbor_HasPendingCargoFor` S 005bb420, the flag destructor, a
debug draw), so no carrier and no ship ever picks it up; it stays in the package list with `flagRef` and
`placedOnFlag` set. The code that walks the package list does not test the stacks: as a free package it gets
a return building from `PackageNeedSystem::Update` S 006506a0 (§3.12) and keeps it, since the assignment is
dropped only without a next waypoint, which the 3-tick revalidation keeps setting; `FindNearestFreePackage`
S 006502d0 may hand it to a need at another flag (§3.11), which then stays served without the good ever moving
(`SettleIdlePackages` S 00651f10 releases a serving package only when it has no next waypoint). It leaves only
without a carrier: stock +1 when its flag is the entrance flag of the nearest connected building (§3.12),
delivery when it lies on its need's target flag, or a discard. The flag destructor S 0066a8d0 detaches only
the packages of its stacks, and `RemoveBuilding` asks only whether the six stacks are empty, so the flag can
be removed under it; the package then keeps the id and the cached pointer of the deleted flag (nothing in the
transport code clears them).

`TransportLink_AttachPackageToFlag` S 0053c980 / `DetachPackageFromFlag` S 0053c9d0 [known]: set / clear the
package's `flagRef`, add to / remove from the stacks, `ticket = 0`, `blockedCount = 0`, flag
`lastServedTicket = −1`, raise the attached / detached callback.

**May I put it down?** `Transport_CarrierTryPlacePackageOnFlag(carrier, flag)` S 0064dae0 [known]. Returns true
when the settler may walk on and drop; evaluated in this order:

1. Carrier with an exchange reservation: if `CanSwapPackagesAtFlag(carried, partner, flag)` → true; else drop the
   reservation and continue.
2. If the package has `hasNextWaypoint`:
   a. it has a **building** target (building reference valid; a ship target alone does not qualify), its next
      waypoint is its target flag and that is this flag's cell → true (final destination: it will be carried into
      the building, no stack place needed);
   b. the settler is a carrier and `FindSwapPackageAtStreetEnd(carrier, flag)` finds a partner → reserve it → true.
3. If `flag.CannotTakePackage(package)`: `blockedCount += 1`, `ticket += 19 − rank(good)`; if
   `blockedCount % 180 == 0` send player message type 3 `"!flag blocked"` at the flag's cell to the package owner;
   return false.
4. If the package is not registered on a flag: if `flag.lastServedTicket < ticket` → `lastServedTicket = ticket`,
   return false; if `ticket != lastServedTicket` → return false; else attach the package to the flag now.
5. Return true.

Step 4 is a two-phase admission: the first try after a place became free announces the ticket, the next try with
the same ticket is admitted; a waiting package with a higher ticket that announces in between takes precedence,
and any attach, detach or carrier unlink at the flag resets the announcement [inferred]. Tickets grow faster for
goods with a low rank number. The function is also used by other settlers that carry a package to a flag, e.g.
production workers (`NMovie::WaitForFreeFlag::Update` S 00777be0, [inferred] called every tick while the worker
waits inside; `PutDownPackage`; `MoveOnMapToWorkingPlace`; `MoveAwayFromDeposit`) [known caller list].
In play a workshop whose flag is full stops with the finished product and its worker puts it on the flag when a
place becomes free (maintainer, 2026-10-12); the product's package is tried every tick (one increment of
`blockedCount` per tick, `ticket` + 14 per tick for a rank-5 good) and is not discarded at 360: one product waited
more than 7,000 ticks [live, 2026-10-12, hook on S 006513b0].

**Exchange.** `CanSwapPackagesAtFlag(carried, partner, flag)` S 0064d120 [known]: true if both are the same good;
true if the flag is not full for the carried good; otherwise true only if the partner is the only package on its
stack. `FindBestSwapPackageOnFlag(flag, nextFlag, carried)` S 0064d2f0: among the packages on `flag` that pass
`CanSwapPackagesAtFlag`, await pickup and have `nextFlag` as next waypoint: `rank(good)`, `+50` if `nextFlag` is
full for the good; lowest below 100 wins. `FindSwapPackageAtStreetEnd` S 0064d750 applies it with `nextFlag` = the
other end of the carrier's street.
In normal play the exchange is common [live, 2026-10-12, developed save]: `CanSwapPackagesAtFlag` ran 17,218 times
and `FindSwapPackageAtStreetEnd` 8,286 times in 1,700 ticks; over a longer run 255 of 5,216 searches found a
package, and one player's jams at full flags resolved after at most 261 attempts. The set-up of §10 Q4 (two
crossing streets with full flags) was not built.

**Drop start** (`CarrierBeginDropAtFlag` S 0064d410) and **drop hand-over** (`PutDownCarriedPackage` S 0064d590)
[known], condensed:

0. Drop start, registration of the carried package (flag = the owner's flag on the settler's cell): a package
   that is registered on a **different** flag is detached from that flag and attached to this one. A package
   registered on no flag is attached at drop start only when the settler is a carrier without a reservation, the
   package is not at its final destination (no building target, or its next waypoint is not its target flag) and
   the flag passes `CannotTakePackage` = false; otherwise attaching is left to the hand-over (item 3).
1. With a reservation: if the swap is still allowed and the partner still lies on this flag, the partner is
   detached from the flag at hand-over; otherwise the reservation is dropped (at drop start also when the partner
   is registered on another flag), and at hand-over, for a settler of type Carrier, if the flag
   `CannotAcceptPackage(carried)`, **nothing happens** (the carrier keeps the package and tries again).
2. The carried package is unlinked from the settler. With a live reservation the partner becomes the carried
   package (`placedOnFlag = 0`).
3. If a flag stands on the settler's cell (and, for a settler of type Constructor, his building reference is
   valid): attach the package if it is not registered on a flag yet; if it has **no target**, register it as a free
   package (`PackageNeedSystem::AddPackage`) unless already registered; `OnPlacedOnFlag` (§3.6).
4. Without a flag there: the package is removed from the package system (destroyed).

**Giving up** [known] S 0077a0c0, S 0065b200: a carrier whose GoToPackageTarget movie is in the waiting step
(0x14) and whose package has `blockedCount > 360` looks for a building with
`BuildingList_FindNearestReachable(list = NVillage::System+0x20, player, his cell, 100, mode 0, netKind 1)`
S 00557fe0. In mode 0 the constant 100 is **not used**: the function takes the player's flag on the carrier's
cell (none → no building) and returns `BuildingList_FindNearestConnected(list, flag, 1)` S 00557ef0, i.e. the
finished building of the list whose entrance flag is in the same kind-**1** (walking) continent with the lowest
`GetFlagPathCost(flag, entranceFlag, 1)`, first in list order on a tie. If one is found, one unit of the good is
added to that building's output stock (`Depot+0x28`) [known] S 0065b200; the package is discarded either way; the
carrier returns to waiting (0x16).
`blockedCount` grows by one per failed admission test: once per 10 ticks in the waiting step, once per tick while
he is held during the walk (§3.8), so 360 is reached after at most 3600 ticks of waiting [inferred].
`PutDownPackage::Update` S 0077a8e0 simply ends when no flag stands on the settler's cell or the flag refuses.

**Extra units of a worker's product** [known] S 0077a8e0: when the *Drop* inside `PutDownPackage` completes for a
settler of type Worker who holds no package any more, and the type of the building referenced at settler
`+0x120` ([inferred] his workplace) has `workingMode` (`BuildingProperty+0x80`) 1, 2, 3 or 7 (Mining, Farming,
Fishing, Hunting in `village-buildings.md` §2.1), `{good, count}` is asked from
`SacrificePlayerTableRef::GetEntryWithModifiers(building, 0)` on `GameSystem.sacrifice+0x0c` (S 00661c50
[known]: entry 0 of the building type's goods list, `BuildingProperty::GetGoods(0)`, a `{good, count}` pair;
only when its good id is 0x17626a03 can the owner's sacrifice modifiers change the amount; entry 0 is
product slot 0, `{goodId0, goodAmount0}` at `BuildingProperty+0x44`: `GetGoods` S 00552f30 returns
`this + 0x44 + slot × 8`, and its writer `SetGoods` S 00552ef0 is called with slot 0 only by `bp_setGoods`
S 0054d460 (slot 1 by `bp_setSecondGoods`) [known]; the function is described in
`village-buildings.md` §3.7); for a valid good, `count` is added to the statistics and, if the owner's flag
stands on his cell, `count − 1` further packages of that good are created in his hand one after another, each
put on the flag with `PutDownCarriedPackage` if `Transport_CarrierTryPlacePackageOnFlag` succeeds on the first
or the second try, else discarded. So a product amount above 1 leaves such a building as one carried package
plus `count − 1` packages that appear on the flag.

**Spilling** (`SpillGoodsOntoFlag(flag, goods)` S 0064d9d0) [known]: round-robin over the goods in ascending good
id, one package per good per pass, each created on the flag, attached, routed and registered as a free package;
stops at the first good for which the flag `IsFullForGood` (the rest stays in the caller's map). Used when a
building is removed and when an upgrade is cancelled. `CreatePackageAt` S 0064cd90 does the same for one unit
(aborted construction).

### 3.10 Street swap between two carriers

Tried by a carrier that waits at his target flag with a package he cannot put down, when
`(tickCounter + settler.unique.idLo) % 200 == 0` (`GoToPackageTarget::Update` S 0077a2f0) [known]:

1. the carried package has a ship or building target (`ai::transport::TransportTarget::HasTarget` S 005b7b40 on the `TransportTarget`: true
   when the building or the ship reference is valid [known]);
   `hop = ComputeNextHop(flag cell)`; `hop` valid and ≠ the flag cell;
2. `other` = the street of the first link from this flag to the flag at `hop` (`Flag::FindLinkToFlag`); it must not
   be his own street, and both streets must be water streets or both not (`(type == 2)` equal);
3. `partner` = the carrier in the same slot (first / second) of `other`; he must exist and either
   a. be free: no package, state 0x16, not moving, not standing on a flag (S 0077a0f0), or
   b. be loaded and stuck symmetrically: has a package, state 0x12 with his GoToPackageTarget at step 0x14, his
      package has a target, its following hop is an end flag of my street and its next waypoint is the other end of
      my street (`CanSwapWithLoadedPartner` S 0077a150);
4. set my package's next waypoint to `hop`; unlink me, then the partner, from the streets (packages kept), then
   link me to `other` and the partner to my street, in the same slot kind (§3.5: each unlink that empties a street
   re-floods both end flags, each first-slot link re-floods when the ids differ; second-slot links do not); drop
   both exchange reservations; reset `ticket` and `blockedCount` of my package; for a loaded partner also set his
   package's waypoint to its following hop (computed before the relinking), reset its `ticket` and
   `blockedCount` and restart his GoToPackageTarget movie; restart my GoToPackageTarget movie. A free partner's
   movie is not restarted.

Effect [inferred]: the loaded carrier walks on over the next street with his package instead of waiting for a
place on the full flag, and the two carriers trade streets.

### 3.11 Needs: who gets which good

**Creating and cancelling** [known]: `NeedGoods::AddRequest(good)` S 0064eb80 / `AddRequests(list)` S 0064ea00
create one element and one `NeedGood` per unit (`NeedSystem::CreateNeed` S 00652420: stamp = current tick, pushed
to the need vector and into the open index). `CancelRequest(good)` S 0064e3a0 removes an open (unserved) request
first; if none, the **last** request of that good with a package, whose package is released to the free packages.
The callers (production, construction, sacrifice, training, expedition, catapult) are in `village-buildings.md`.

**`NeedSystem::Update`** S 00652170, every 11th tick (§4) [known]:

1. `SettleIdlePackages` S 00651f10: for every need with a serving package that has neither a carrier nor a ship:
   if the package has no next waypoint → release it (need becomes open again, package becomes a free package);
   else if it lies (`placedOnFlag`) on the need's target flag and the need has a building target → deliver it
   (below). Releases are executed before deliveries, each list back to front.
2. Iterate the open index: players 0..7; per player categories 0, 1, 2; per category the bucket entries (one per
   good) in the order of `sortedIdx`; per entry the **distinct nodes** of its needs in order of first occurrence.
   - `sortedIdx` is rebuilt whenever the iterator enters a player: entries sorted ascending by `rank(good)`
     (§3.8), equal ranks in bucket creation order (`std::multimap` insertion, S 006538f0). The rebuild is
     skipped for a player-table entry (`PlayerTable::GetEntry`) whose byte `+0x50` is clear (`bActive`, slot
     in use, `players-victory.md` §2.2); its
     `sortedIdx` vectors then keep their old content [known].
   - Within a player a category is left when its entries are exhausted; within an entry the node list is
     collected with `AddUniqueNode` S 00652fd0 and reset when the iterator moves to the next entry
     (`NextNodeInPlayer` S 00653180, `ai::logistics::GoodOrderIterator::NextNode` S 00653250) [known].
   - The *node* of a need is its target flag (need vtable +0xc). Two nodes are the same when their flags have the
     same kind-0 net continent (S 00652fd0). So **one node per connected goods network** is visited per good and
     category, represented by the first need's flag [known].
3. For each (entry, node), with `good` = the entry's good and `ignoreGoodFlags = (category != 2)`:

```
if PackageNeedSystem.HasFreePackageInNetwork(good, node):            # a free package lying on a flag of the network
    need = SelectOrderForNode(entry, node)
    if need:
        T   = need.targetFlag
        pkg = FindNearestFreePackage(good, T)
        if pkg:
            B = NearestConnectedSupplier(T.owner, T.cell, good, ignoreGoodFlags)
            if B == null or PathCost(T, pkg.flag) <= PathCost(B.entranceFlag, T):
                take pkg for need;  continue
            if B.settlerSpawn.IsReadyToSpawn(): DispatchFromBuilding(B, need)
            continue
# no free package (or none usable):
B = NearestConnectedSupplier(node.owner, node.cell, good, ignoreGoodFlags)
if B and B.settlerSpawn.cooldown == 0 and not B.entranceFlag.IsFullForGood(good):
    need = SelectOrderForNode(entry, node)
    if need and FindSupplierBuilding(need.targetFlag, good, requireReady = true, ignoreGoodFlags) != null:
        DispatchFromBuilding(B, need)
```

   In the last branch the building dispatched is `B` (nearest to the node's representative flag); the supplier
   found for the need's own flag only gates the dispatch: its result is tested for null at S 00652352 and not
   used again, and the building pushed for the call at S 0065235a is the register that holds `B` [known].

   The second block is also entered from the first one when `SelectOrderForNode` returned no need or no free
   package was found. In that case `SelectOrderForNode` runs **twice** in the same visit, and each call that
   returns a need sets its `stamp` to the current tick (and, for category 0 with an arrangement group, advances
   the rotation), so the second call can return a different need than the first [known] S 00652170, S 00652e00.
   `B.settlerSpawn.IsReadyToSpawn()` (first block; the `SettlerSpawn` is at `Building+0xc0`) and
   `cooldown == 0` (second block, dword at `SettlerSpawn+8`) are two different tests. `IsReadyToSpawn`
   S 00564580 is the stronger one: `spawnCooldown == 0` **and** fewer than 2 settler references in the building's
   depot (`Depot+0x74` `settlerRefs`, vector at `+0x7c/+0x80`) [known]. A reference is added only by
   `SpawnCarrierWithPackage` S 0064d020 (`VillageLink_LinkSettlerToDepot` S 0053d2b0, which also sets
   `Carrier+0x1c0`) and removed only when that carrier is destroyed (`Carrier::dtor` S 0065afb0) or the depot
   detaches all its settlers (S 0055b250) [known, caller lists]: these are the helpers sent out with a package
   of this building that still exist, so a supplier has at most two of them out at a time.
   The second block gets the stronger test
   through `FindSupplierBuilding(requireReady = true)`, but for the supplier of the need's own flag, which need
   not be `B` [known].

- `NearestConnectedSupplier` = `BuildingList_FindNearestConnectedWithGood` S 00557da0 over the village building
  list at `NVillage::System+0x20` (every building whose type has `depot`, `BuildingProperty+0x54`, in the order
  the buildings were indexed; `NVillage::System::IndexBuilding` S 00559940 [known]): finished buildings whose
  entrance flag is in the same kind-0 continent as the flag at
  the given cell, whose stock has the good, and (unless `ignoreGoodFlags`) whose good flag for the good is **not**
  enabled; minimum `GetFlagPathCost(fromFlag, building.entranceFlag, 0)`, taken when `cost < best || best == −1`,
  so ties keep the earlier list element; the building's owner is not tested [known].
- `FindSupplierBuilding(..., requireReady)` S 006517d0: the same search, then the building's settler spawn must be
  ready and its entrance flag not full for the good [known].
- `HasFreePackageInNetwork` S 006501d0: any free package of the good registered on a flag in the node's kind-0
  continent [known].
- `FindNearestFreePackage(good, T)` S 006502d0: among free packages of the good (registration order) that are
  registered on a flag in T's kind-0 continent, excluding packages that lie (`placedOnFlag`) on T itself: minimum
  **hex distance** between T's cell and the package's flag cell, below 100000, first found on a tie [known].
- *Take pkg* [known]: remove it from the free packages (not destroyed), set its target to the need's building or
  ship (§3.6 event 1), link it into the owner's `NeedGoods` element, `need.servingPackage = pkg`, remove the need
  from the open index. [inferred] the package's next hop is then computed by the 3-tick revalidation (§3.6), since
  setting a target clears the waypoint (`TransportLink_LinkPackageToOrder` S 0053c8c0 calls no route search).
  The removal (`UnregisterPackage` S 00650990 → `PackageNeedSystem::RemovePackage(pkg, destroy = false)`
  S 006505d0 → `EraseTarget` S 00650430) [known]: a return building assigned to it is unlinked; it is erased from
  the per-good vector and from the registration vector (both stable erases); and when it lies on a flag
  (`placedOnFlag`) with a carrier reference, that carrier's claim is dropped, or his exchange reservation when it
  is his `reservedPackage`, so the carrier that chose it waits again. A package in a hand keeps its carrier (it
  cannot be chosen here: `FindNearestFreePackage` only returns packages registered on a flag).
- *DispatchFromBuilding* (S 00651770, S 0064d020) [known]: if the supplier's entrance flag `IsFullForGood` → nothing.
  Else spawn a carrier with a package (§3.8), stock −1, then as *take pkg*. Order inside
  `SpawnCarrierWithPackage`: the carrier is spawned through `SettlerSpawn::SpawnCarrier` S 005644f0, whose
  `ConsumeSettlerGood` S 00564360 sets the building's `spawnCooldown` to 10 and takes one `good_helper` from its
  output stock (one is first made from the helper's empty cost list when the stock has none, so the stock is
  then unchanged; `village-buildings.md` §3.11) and creates the settler, whose `Unique` draws therefore come
  before the package's; the carrier is linked to the building's depot; one unit of the good is removed from the
  output stock; the package is created (one id) and put into the carrier's hand [known].

**Which need of an entry is served at a node** (`GoodOrderIndex_SelectOrderForNode` S 00652e00) [known]; only
needs whose target flag is in the node's kind-0 continent are candidates:

| Category | Rule |
|---|---|
| 2 (finished `depot` building) | maximum of `(now − need.stamp) − 10 × (units of the good in the target building's output stock)`, the stock read through the depot (`Building+0x3c` → `Depot+0x28`); the best score starts at `INT_MIN` and a later need replaces the pick only when strictly greater, so the first found wins a tie (`GoodOrderStockAgeScorer::ConsiderNeed` S 00651330) |
| 1 (ship) | smallest `stamp`; first found on a tie (S 005691f0) |
| 0 | if the player's `NPlayer::GoodArrangement` has a group for the good (`FindGroupForGood` S 005c10f0: the group whose id equals the good's `GoodProperty+0x78`): distribution by the arrangement (`GoodOrderBucket_SelectByArrangement` S 00652b70, below). Without a group: smallest `stamp` |

The chosen need's `stamp` is set to the current tick.

**Distribution by the arrangement** (category 0 with a group; S 00652e00, S 00652b70, S 005c30c0) [known]. A group
is a list of entries `{float weight, float accumulator, int buildingTypeId, byte used}` (layout and defaults:
`players-victory.md` §2.6). `defaultType` = the first building type in the tribe's building list whose product
slot 0 is the good `TribeProperty+0xb4` (`constructionGoodId`; `Player_FindBuildingTypeProducingTribeGoodB4`
S 00533b20, called with the owner of the node's flag; −1 if none). A target building is a *site* when a
construction `remaining` value is > 0 and its size is not the ship site (`size != 0x10`) [known] S 00652b70.

1. `MarkAllUsed`: every entry `used = 1`.
2. For every need of the bucket entry whose target flag is in the node's kind-0 continent: `ReleaseId(id)`
   clears `used` of the first group entry with that type id, where `id` = `defaultType` for a site, else the
   building's own type id.
3. Up to (number of group entries) rounds: `PickNext`: add each entry's weight to its accumulator; take the
   first entry in list order with `used == 0` and the strictly largest accumulator (start value −1.0), or the
   first entry of the group if all are `used`; set its accumulator to 0; the result is its type id. Then scan
   the needs of the bucket entry in order: a need at the node matches when its building's own type id equals
   the picked id, or when the picked id is `defaultType` and the building is a site; among the matches the
   smallest `stamp` wins (strict `<`, so the first on a tie). A round that finds a need ends the selection; a
   round in which no need at the node was seen at all ends it with no need.
4. `ClearUsedFlags`: every entry `used = 0`.

Accumulators persist between calls and are saved with the player, so the rotation state is simulation state
[inferred from the save layout in `players-victory.md` §7]. A round whose picked type has no need at the node
still consumes that type's accumulator [known].

Rate limits that follow [inferred]: per 11 ticks at most one unit per (player, category, good, connected network);
a supplier building dispatches again only when its settler spawn is ready (`spawnCooldown`, 10 ticks,
`village-buildings.md` §3.11).

**Delivery** (`NTransport::System::DeliverPackage` S 0064cc60) [known]: if a need is served by the package
(`NeedSystem::DeliverPackage` S 00651bc0): unlink the carrier, clear target and `servingPackage`, put the need
back into the open index (the owner removes it when it accepts the good), `NVillage::Depot::CollectGoods(package)`
on the target building, destroy the package. Otherwise, if it is a free package with a return building
(`PackageNeedSystem::DeliverPackage` S 006509a0): stock +1 in that building, destroy the package.

**Discard** (`NTransport::System::DiscardPackage` S 0064cc90) [known]: a serving package: unlink carrier (or
exchange reservation), clear target, reopen the need, destroy the package. A free package: unregister and destroy.
Else: unlink the carrier and destroy.

### 3.12 Free packages: returning goods to a storehouse

A package without a target is a *free package*: products put on a flag by a worker, spilled goods, released
packages. `PackageNeedSystem::Update` S 006506a0, every 5th tick, for every registered free package in
registration order [known]:

- **Has a return building**: if it has no carrier reference and no next waypoint (the route is gone), drop the
  assignment.
- **Has none, and lies on a flag** (`placedOnFlag`): `B` = nearest connected finished building of the village list
  +0x20 by `GetFlagPathCost` from the package's flag, kind 0 (`BuildingList_FindNearestConnected` S 00557ef0). None
  → wait. If `B`'s entrance flag is the package's flag: stock +1 in `B`, destroy the package (no carrier needed).
  Else assign `B` (target set, `SetNextHop(flag cell)`).
- **Has none, and is in a carrier's hand**: `F` = the flag at the cell the carrier is heading for
  (`SettlerMovement+0x140`); `B` = nearest connected building from `F`; assign `B` only if the next hop from `F`
  towards `B` (or, failing that, from the far end flag of the carrier's street) lies on the carrier's street path.

[inferred] Free packages therefore drift to the nearest storehouse unless a need takes them first (§3.11 prefers a
free package whenever its path cost is not higher than the nearest supplier's).

### 3.13 Settlers walking the street network

Settlers that walk "by street" (not carriers on duty) plan one leg at a time with `StreetRoutePlan::Plan(player,
fromCell, toCell, currentStreet)` S 007735b0 [known]:

- each end resolves to the player's flag on the cell, or to the attached street on the cell (layer 2), represented
  by its start flag;
- same flag at both ends: on the same street → walk along it; start on a street → walk to the flag; end on a
  street → walk from the flag to the cell; both on the flag → no route;
- else path search with kind 1, no carrier penalty, the current street preferred (cost 1); the next flag of the
  route is the leg's goal; between two flags joined by several streets the **shortest** one is walked, unless the
  current street already leads there (`Flag::FindShortestLinkToFlag` S 0066a1f0, `StreetPath::ComputeRoute`
  S 007741e0). `FindShortestLinkToFlag` has no preferred-street parameter: it returns the link to that flag
  whose street has the strictly smallest `length`, so among equal lengths the first in link order wins; the
  exception for the current street is made by its caller [known].

`ai::settlers::SettlerMovement::AdvanceStreetRoute` S 00657b80 [known]: at a flag with a harbour link, when the next
flag of the route also has a harbour link and the shortest street between them is a sea street with a valid ship
route, the settler is linked into the flag's `waitingSettlers` and waits for the ship (the test on the street is
that its `shipRouteRef` is valid). The same link is made when a settler arrives on the cell that is his route
target, a flag stands there and his vtable slot 1 answers true (`settlers-jobs.md` §2.3) [known]. He takes a waiting
spot from `FlagParking::FindFreeSpot` S 0066d390 (flood fill over walkable cells within hex distance 10 of the flag,
fine grid positions on rings 0..2 around a free cell, not already occupied; the n-th candidate is taken with
`n = (random % 4) × 3 + (tickCounter & 7)` with the C signed remainder of the generator's int result, S 00671730)
[known]. In detail (`FloodFillSearch::Run_FreeSpot` S 0066d190, `FreeSpotSearch::IsInRange` S 006716e0, `VisitCell`
S 00671790) [known]: breadth-first from the flag's cell, neighbours in direction order 0..5; a cell is entered when
it is walkable (§3.2) and within hex distance 10 of the flag; only cells that pass
`GameQuery::IsCellFreeOfObjectsAndStreets` S 0052e090 (nothing in object layer 0, and none of the grid bits 0x1,
0x2, 0x4, 0x40, 0x80, 0x100, 0x400, 0x20000) yield candidates. `VisitCell` walks a spiral of 19 fine-grid positions
around the cell: the centre vertex; ring 1 = one step in direction 4, then one step in each of the directions 0..5;
ring 2 = one more step in direction 4, then two steps in each of the directions 0..5. The position is tested after
each of the steps in directions 0..5 (each ring ends on its first position, which the direction-4 step reached
untested); it counts when it lies inside the fine grid and is not in the flag's occupied list. Candidates are
counted from 0 over the whole search and the search ends as soon as more than `n` have been counted, returning
candidate `n`. If the flood fill ends with `n` or fewer candidates, **no** spot is returned, although candidates
existed: the fine position becomes the invalid (−1, −1), the parking cell out-parameter is not written, and
`OccupySpot` still pushes (−1, −1) onto the flag's occupied list. Sea transport itself: `navy-and-military.md`.

`NNet::System::FindNearestFlagWithLink` S 00663f50 (used by `MoveToHome`) returns the player's flag nearest by hex
distance whose net continent of the given kind equals a given id [known for the code; inferred for the purpose].
The flags are visited in vector order and only a strictly nearer one replaces the best, so the first of equally
near flags wins. The map-continent filter applies only when the position's map continent id is not −1: then the
flag's cell must lie on the same map continent; with −1 at the position every flag qualifies [known]
(`settlers-jobs.md` §3.4).

---

## 4. Update order

Per logic tick (0.1 s of game time at speed 1, `logic-core.md` §3.1), inside `NLogic::System::Update` S 00527070;
the numbering is that of `logic-core.md` §4.2 [known]:

| Step | Call | What happens here |
|---|---|---|
| 2 | `AdvanceNetTick` | executes player commands: place / remove flag, start / extend / cancel street, priorities (`game-commands.md`) |
| 3 | street planners 0..7 | cancel a plan that became invalid (§3.2) |
| 6 | `NVillage::System::Update` | buildings add / cancel needs; then the settler order system serves carrier orders |
| 7 | `NNet::System::Update` S 00665ef0 | (a) players 0..7, flags in vector order: remove flags on lost territory (§3.3), inside a map-update batch that encloses (a) only; after a removal the scan goes on with the flag that moved into the freed slot (`RemoveFlag` returns the erase position); (b) players 0..7, streets in vector order: `Street::Update` for attached streets (§3.7), outside the batch [known] |
| 9 | `NSettlers::System::Update` | every carrier: `Carrier::Update` (§3.8); iteration order is the settler system's |
| 10 | `NTransport::System::Update` S 0064cbe0 | with `tick` unsigned: `if tick % 11 == 0` `NeedSystem::Update` (§3.11); `if tick % 3 == 0` `PackageSystem::Update` (route revalidation, §3.6, packages in creation order); `if tick % 5 == 0` `PackageNeedSystem::Update` (§3.12); in this order |
| 14 | navy (`NNavy::System::Update` S 005b39d0) | every ship in vector order (`Ship::Update`: loads and unloads packages at harbour flags, `docs/sim/navy.md`); then the harbour list places harbour flags through `Logic_PlaceFlag` (S 005b5670) [known]. Sea streets are built and removed by `NavyShipRoute::UpdateSeaStreet` S 005b71d0, whose callers are the attaching of a flag to a harbour (S 005b49f0) and the adding / removing of a ship movement on a ship route (S 005b73a0, S 005b73d0) [known, caller list]: it runs in whichever step such an event happens (`docs/sim/navy.md` §3.12) |

Staggered work inside the carrier movies uses `(tickCounter + settler +0x10) % N` (unsigned) with N = 20 (idle
look for work, only while the carrier stands on his working position; a displaced carrier looks every tick),
10 (retry put-down), 200 (street swap; tested only on a tick that passed the % 10 test and whose put-down
failed) [known] S 0077ac50, S 0077a2f0. `settler +0x10` is `unique.idLo`, the low dword of the settler's id
(`NSettlers::Settler.unique` at +0x08, `NLogic::Unique.idLo` at +0x08 of it) [known: typed layout].

Per frame only (no simulation state): the street placement preview (`ai::game::StreetBuildMode`, which runs its own
planner on a `StreetConstructorPoints` object that only records cells, S 00668a50), slope markers
(`nGame::Cursor::DrawStreetSlopeMarkers` S 00788f90), street and flag rendering, the flag debug overlay
(`nMenu::Game::DrawFlagDebugInfo` S 00619ad0) [known].

---

## 5. Inputs and outputs

**Player commands** (executed in step 2; details in `game-commands.md`): `0x20004` flag create, `0x20005` flag
destroy, `0x20006` street start (payload has the water flag → type 2), `0x20007` street cancel, `0x20008` street
build-to-position, `0x20009` street destroy (street id; no owner check in the executor S 00781290), `0x20021` /
`0x20022` good priority list set / reset (`0x20021` replaces the whole `{goodId, rank}` list without
validation), `0x2001F` / `0x20020` goods distribution change / reset (the arrangement weights of §3.11) [known
for `0x20009`; the others as listed in `game-commands.md`]. `0x2000B` (send a specialist to a flag) has an
executor that does nothing in this build (`game-commands.md`).

**Called by other subsystems** [known unless marked]:

| Caller | Entry point | Purpose |
|---|---|---|
| village: place building, building ownership transfer (S 0055a210) | `Building_AttachEntranceFlag` S 00557660 → `Logic_PlaceFlag` S 00538cd0 | entrance flag at anchor + direction 1; an own flag already on that cell is reused, else one is placed |
| village: building removed / upgrade cancelled / construction aborted | `SpillGoodsOntoFlag`, `CreatePackageAt` | goods back onto the flag |
| village: requests | `NeedGoods::AddRequest(s)`, `CancelRequest`, `ClearAll`, `CancelAllRequestsOfGood` | needs |
| village: supplier and settler-order searches | `GetFlagPathCost`, `NLogic_UniqueArray40_IsEqualAt` | distance and connectivity |
| village: order system | `StreetLink_LinkCarrierSlot78` / `StreetLink_LinkCarrierSlot98` (slot 2) | carrier arrives for a street |
| production workers | `Transport_CarrierTryPlacePackageOnFlag`, `PutDownCarriedPackage`, package creation S 0064cce0 (also called by the ship-building movie S 0077d6c0) | product onto the flag |
| navy | `BuildStreet(type 3)` (S 005b71d0), `BuildStreet(type 0)` (expedition, S 005b8ac0), `RemoveStreet`, `Logic_PlaceFlag` (harbour flag, S 005b5670), `Flag::LinkNavyObject / UnlinkNavyObject`, `Transport_LoadPackageIntoHolder` S 0064cd60, `UnloadPackageFromCargo` S 0064d0b0 | sea streets, harbour flags, cargo |
| map / territory | `RemoveForeignStreetsInRadius`, `RemoveStreetsOutsideTerritory` | territory changes |
| AI | `Logic_PlaceFlag`, `BuildStreet`, `RemoveStreet`, `RemoveFlag`, `GetFlagPathCost`, path finder | computer player |
| Lua | `logic.pl_getStreetCount(player)` S 005af8a0 (number of streets of a player); `menu.createStreet(player, x1, y1, x2, y2)` S 005dada0; `pl_changePlayer` → `TransferPlayerAssets` S 00529040 (re-places flags and rebuilds streets for the new owner, spawning a carrier on each) | scripts |

`UnloadPackageFromCargo` [known]: the package is put on the harbour's flag (attached, routed) when the ship's
harbour state allows it, else destroyed. The function makes no flag capacity test itself; its only caller
`NavyCargo::UnloadOnePackage` S 005bcea0 calls it only for a package the harbour flag's stacks can take
(`CannotTakePackage` false, §3.9). Cargo rules (capacity counted in
packages, all packages discarded when a ship is destroyed) are in `docs/sim/navy.md` §3.9; sea streets and
reachability in `docs/sim/navy.md` §3.12.

Other users of this subsystem's distance [pointers]: settler orders of the soldier exchange limit
`GetFlagPathCost` by `mi_setHealthExchangeDistance` (`village-buildings.md`); a carrier's walking speed is the
settler base speed times the owner's sacrifice modifier for carriers (`settlers-jobs.md`).

**Callbacks raised** (`NLogic::CallbackManager`, `logic-core.md` §3.7) [known]: `NetObjectAdded` (slot 0x18) /
`NetObjectRemoving` (slot 0x1c) for a flag: at creation, after a load and at destruction, and as a
removing-then-added pair when a harbour is linked to or unlinked from the flag (S 00669e60, S 00669eb0); street
added (slot 0x3c) / removed (slot 0x40) / upgraded (slot 0x44); package created (slot 0x60, also after a load)
and destroyed (slot 0x64); package attached to (slot 0x68) / detached from (slot 0x6c) a flag; the settler
movement callback (slot 0x5c) when a carrier is assigned to a street (`Carrier::AssignToStreet` S 0065b150; the
same slot is raised by the settler movement code). Per-cell map changes are reported to the map-update batch
(`logic-core.md` §4.2): S 00532280 (`MapUpdateBatch::RemoveObstructedDoodadsAtCell`; outside a batch it removes the obstructed
doodads of the cell at once, inside a batch it adds the cell to the dirty rectangle) and S 00532400
(`MapUpdateBatch::InvalidateConstructionAroundCell`; invalidates the construction map around the cell).

**Player message**: type 3, text key `!flag blocked`, at the flag cell (§3.9) [known].

---

## 6. Data-driven parameters

| Key (file) | Read by / stored | Shipped value | Effect |
|---|---|---|---|
| `properties.cfg_setFlagPackageLimit(n)` (`scripts/properties/config.lua`) | S 0054c4a0 → `GameConfig+0x20`; S 0066b640 | 2 | capacity of each of the 6 stacks of a flag |
| `properties.cfg_setMaxWaterStreetWaterDepth(n)` (`config.lua`) | S 0054c200 → `GameConfig+0x40`; S 0052e550 | 4000 | maximum water depth (height units) of a water-street cell |
| `properties.cfg_setPickupTime(t)`, `cfg_setDropTime(t)` (`config.lua`) | S 0054c410 → `GameConfig+0x0c` (float), S 0054c440 → `GameConfig+0x10` (float); S 007781e0, S 00777e00, S 00777d10, S 00777d50 | 3.3, 3.3 | in ticks: `DropTime` = first phase, `PickupTime` = second phase of **both** the pickup and the drop movie (§3.8) |
| `properties.tp_setSecondCarrierId(tribe, settlerGood)` (`tribes.lua`) | S 0054ad40 → `TribeProperty+0xb0`; S 00668e10 | Bavarians `good_oxen`, Egyptians `good_helper`, Scots unset | second carrier of an upgraded street; unset = no upgrade |
| `properties.gp_setTransportPriority(good, tribe, n)` (`Goods.lua`, 141 calls) | S 0054e670 → `GoodProperty+0x58` map; default of `NPlayer::GoodPriorities` | 0..18; e.g. Bavarians: gemstones 0, coin 1, gold 2, plank 3, stone 4, food 5, tool 12, weapons 13, coal 15, iron ore 16, oxen 18. Group goods (`gp_setType` `WareGroup` / `EitherGroup`) carry values too: some are in the tribe's good list and so in the player's list (Bavarians: `weapons` 13, `foodBav` 5, `sacrificeGood` 1), the others (e.g. the construction-resources, ship and tool-icon groups with 0, `foodStoneBav` with 5) are not tribe goods | default rank; lower = carried first, visited first by the need dispatcher. The default list of a player (`GoodPriorities::InitFromGoodTable` S 005c2bf0) has one entry per good of the tribe's good list (`tp_addGood`, 26 per tribe) whose good type is not 1 (Settler); every such good has a value for its tribe in the shipped data, and a missing (good, tribe) key is a fatal error in the getter (`properties-data.md`). A good that is not in the player's list has rank 0 (S 005c2620) |
| `good_helper = gp_create("7bff15ce")`, `gp_setSettlerType(good_helper, settlerType_Carrier)` (`Jobs.lua`) | constant 0x7bff15ce in S 00668e10, S 00668be0, S 0064d020 | — | the carrier settler good; the id is hard-coded |
| `good_oxen = gp_create("d4157c5f")`, `gp_addCost(good_oxen, oxen, 1)` (`Jobs.lua`) | via `tp_setSecondCarrierId` | — | the Bavarian pack animal costs one `oxen` good |
| `properties.hp_setWaterStreetPosition(harbor, index, x, y)` (`harbors.lua`) | S 0054b120 → `HarbourProperty+0x20+index*8` | e.g. `(harbor_sw, 0, -2, -3)` | cell offsets used by the navy for the sea street through a harbour (`navy-and-military.md`) |
| `properties.dd_setDeleteByStreet(doodad, bool)` (`doodads.lua`, 26 calls) | S 00550150 → `DoodadProperty+0x41`; `NDoodads::Object::ShouldBeRemoved` S 005454f0 | `false` for the 26 sign doodads (`doodad_emptySign`, `doodad_waterSign`, the resource signs); not set for any other doodad (default in `properties-data.md`) | a doodad with the flag set is removed by the obstructed-doodad pass when its cell has the street bit 0x2 (unless the doodad is indestructible) [known] |
| `properties.ai_enableStreetOptimizing`, `ai_enableWaterStreets` (`ai.lua`) | AI properties | per AI profile | computer player only |
| `<Street .../>` (`settings/graphics.xml`) | `ai::gfx::StreetRenderer::LoadConfigXml` S 006c3f10 | textures, colours, buoy | presentation only |

Constants in code, not data [known]: measuring limit 6000 (a period is 6001 street updates, §3.7) and upgrade
threshold 130.0 (S 00668e10); ×3 busy
factor (S 0066b9e0); 100 / 50 score sentinel and penalty (S 0064d7e0); 19 − rank ticket increment (S 006513b0);
180 message period and 360 give-up limit (S 0064dae0, S 0077a0c0); the argument 100 of the give-up search, which
its mode 0 ignores (S 0065b200, S 00557fe0);
revalidation limit 200 (S 0064f510); update periods 11 / 3 / 5 (S 0064cbe0); stagger moduli 20 / 10 / 200; parking
radius 10 (S 0066d390); 100000 distance sentinel (S 006502d0); step costs 3 / 4 / 5 / 7 / +2 (S 00676840); speed
factors 0.8 / 0.6 / 0.4 (S 0052d9e0).

---

## 7. Save and load

Stream primitives: section tag (stream vtable +0x40), byte (+0x58), i32 (+0x5c), u32 (+0x64), float32 (+0x4c);
a `Unique` or reference stores its 64-bit id; a cell stores two i32 (`ai::map::MapPos::Store`). The container and
the order of the systems are in `logic-core.md` §7 (transport is saved before the street net).

Section tag texts are the strings of the log categories [known, string table S 007f81f8..007f88f4; `Flag`
S 007f5e70, `Logic Need` S 00834348]; section versions written by this build (third argument of each category's
static constructor) [known]: `Net System` 3, `Flag` 3, `SettlersCarrier` 1, all others of this subsystem 0
(`save-format.md`).

**`NNet::System::Store`** S 006640d0, tag `Net System` [known]:

1. byte `initialised`;
2. u32 total flag count; then players 0..7, flags in vector order: i32 owner index, `Flag::Store`;
3. u32 total street count; then players 0..7, streets in vector order: i32 owner index, `Street::Store`;
4. the 16 path-cost caches in index order (`player*2 + kind`): u32 count; per outer entry (ascending `Unique`):
   `Unique`, u32 inner count, per inner entry (ascending `Unique`): `Unique`, i32 cost;
5. `NetContinentIds::Store` S 0066d8e0, tag `Net StreetNetContinentIds`: byte (+0x04, §2.8); u32 count; per net
   continent (ascending `Unique`): `Unique`, u32 n, n × i32 map continent id (ascending), cell (looked up in the
   third map by the same `Unique`). `Load` S 006707f0 rebuilds all three maps from these records.

**`Flag::Store`** S 0066a370, tag `Flag` [known]: building reference; `unique`; cell; i32 link count, per link
`FlagLink::Store` (tag `Net FlagLink`: other-flag reference, street reference); 2 × `netContinent`;
`FlagPackageStacks::Store` (tag `Net Package Stock`: byte `active`; 6 × stack with tag `Net Package Stack`: u32
`capacity`, i32 `goodsFilter`, `PackageContainer::Store`: tag, byte `active`, i32 count, per package reference);
`specialists` (tag `Net Specialist`, settler references); `orders`; i32 `lastServedTicket`; `harborRef`;
`waitingSettlers`; `parking` (tag `Net Parking`, vector of fine positions).

**`Street::Store`** S 00669090, tag `NetStreet` [known]: `unique`; u32 path count, cells; i32 `length`;
`startFlagRef`; `endFlagRef`; `carrierRef`; `secondCarrierRef`; `mapUpdater` (only its section tag
`Net Street Map Updater`, no data, S 00670b90); `orders`; i32 `trafficCount`; i32
`tickCounter`; float32 `avgTraffic`; 2 bytes `usable`; i32 `streetType`; if type 3: `shipRouteRef`.

**`NNet::System::Load`** S 00668050 [known; version compares at S 0066820b, S 00668320, S 00668447]: `Clear`;
section version `v`; byte `initialised`; flags (each created with the load constructor for the saved owner
index, loaded, appended to `flagsByPlayer` and entered into `flagById`); streets likewise, and per street, if
`v < 2`, one extra i32 is read after the owner index and dropped; a new path finder is created; the caches are
read if `v ≥ 1`, else emptied; `NetContinentIds` is read if `v ≥ 3`, else its byte +0x04 is set.
`Flag::Load` S 0066b470 [known, disassembly S 0066b593, S 0066b5bc]: with `fv` = the `Flag` section version,
`harborRef` and `waitingSettlers` are read only if `fv ≥ 2` and `parking` only if `fv ≥ 3`.
`Street::Load` S 00669b30 recomputes `mid`.

**Post-load** [known]: `NNet::System::PostLoad` S 006654f0 runs `PostLoad` on every flag (resolve references, raise
`NetObjectAdded`, write layer 0; S 0066a5f0) and every street (S 00668d60: resolve references; raise "street
added" if attached and not type 3; for a street that is not type 3 `StreetMapUpdater::PostLoad` S 00670f40
rewrites object layer 2 but not the GridStates bit 0x2, which is
saved with the grid), then removes every street with an invalid start or end flag reference. Object layers are not
saved (`map-format.md` §5.5).

**`NTransport::System::Store`** S 0064cdd0, tag `Transport System` [known]: byte `initialised`; then the three
parts in member order (+0x08, +0xa0, +0xc8):

1. `PackageSystem::Store` S 0064f640 (tag `Package System`): byte `initialized`; u32 count; per package in creation
   order: i32 owner index, `Package::Store` S 00651530 (tag `Transport Package`; `unique`; i32 `goodId`;
   `TransportMovement::Store` S 0064f060: tag `Transport Movement`, byte `hasTarget`, byte `hasNextWaypoint`,
   carrier reference, flag reference, `nextWaypoint` cell, byte `placedOnFlag`, i32 `revalidateCount`,
   `cachedHop` cell, `cachedFrom` cell, `cachedFromNet` Unique, ship reference; target store S 0064ee00: tag
   `Transport Target`, building reference, ship reference; i32 `ticket`; i32 `blockedCount`);
2. `PackageNeedSystem::Store` S 00650080: tag `Transport PackageNeedSystem`, byte, u32 count, per free package:
   tag `Transport PackageNeedTarget`, package reference, building reference (S 00652610);
3. `NeedSystem::Store` S 00651840: tag `Transport BuildingNeedSystem`, byte, u32 count, per need in creation
   order (S 00652900): tag `Transport NeedGood`, `servingPackage` reference, `NLogic::Need::Store` S 00775740 (tag
   `Logic Need`, building reference, ship reference, i32 good id, u32 stamp).

Recomputed on load [known]: `packagesByPlayer`; `PackageNeedSystem.byGood` (rebuilt by `RebuildGoodIndex`
S 00651220); the open-need index (rebuilt in `NeedSystem::ResolveReferences` S 00651dd0 from all needs without a
serving package, in need-vector order, so bucket creation order after a load is the order of the need vector).
Not saved: `Flag.searchMark`, the path finder state, the need iterator.

The carrier: `Carrier::Store` S 0065a840, tag `SettlersCarrier`: the eight movies in member order, byte
`notYetOnStreet`, `reservedPackage`, building reference, then the `Settler` base [known]. `Carrier::Load`
S 0065a930 reads the building reference only if the `SettlersCarrier` section version is ≥ 1 [known].

---

## 8. Determinism notes

**Details that matter for a byte-exact port** [known]:
- The reserve-last rule of `AddPackage` (S 00671590) compares only stacked packages that have a next waypoint: a stack
  whose only package has no waypoint refuses its last place to a routed newcomer (all compared packages are vacuously
  "the same").
- A street's upgrade and its second-carrier order happen in the same `Street::Update`.

- **Checksum.** `NNet::System::StoreForChecksum` S 00664550 (only caller `nGame::System::ComputeChecksum`
  S 00784080) writes the same fields in the same order as `Store` without the `Net System` tag; flags, streets
  and `NetContinentIds` go through their normal `Store` [known]. The transport system's normal `Store` is used;
  section tags contribute nothing to the CRC stream (`logic-core.md` §3.6). Hence flag and street order
  in the per-player vectors, the content of the **path-cost caches**, the net-continent `Unique` values, every
  package's waypoint, cache, `ticket` and `blockedCount`, and the order of the need and free-package vectors all
  enter the desync checksum [known / inferred from the field lists in §7].
- **Unique ids** come from one global counter (`logic-core.md` §2.3). A flag draws 3 ids at creation (own id, then
  the kind-0 and the kind-1 continent id), a street 1, a package 1, every `RecomputeFlagContinent` 1. The number
  and order of these draws must match, because ids order the maps and are saved [known] S 0066b010, S 00667a30.
  The order inside the composite operations: `BuildStreet` §3.2 (the street's id before a split at its end),
  `PlaceFlag` §3.1 (carrier unlink, `RemoveStreet`, the new flag, street A, street B, the carrier's relink), the
  street destructor §3.3, the interactive construction §3.2, a dispatch from a building §3.11 (settler before
  package). Counts that follow [inferred from §3.1–§3.5]: a street the player starts once (`0x20006`) and ends
  with `0x20004` on a free cell draws 6 ids: the street under construction; then the new flag (own id, kind 0,
  kind 1), the finished street and the kind-1 re-flood of `StreetLink_LinkFlags`. Splitting a manned street with
  a flag draws 11, in this order: [kind 0 at the start flag, kind 0 at the end flag] (the carrier unlink that
  empties the street), [kind 1] (the destructor's flag unlink), [flag, kind 0, kind 1], [street A, kind 1],
  [street B, kind 1], [kind 0] (the carrier relinked to his half). A street that ends inside another draws its
  own id first, then the ids of the split.
- **Container orders that decide outcomes** [known]: flag links in attach order (search tie-breaks, flood-fill
  order); `flagsByPlayer` / `streetsByPlayer` in creation order with stable erase; packages on a flag by stack
  index then push order; the free-package vector in registration order; the need vector in creation order; bucket
  entries in creation order, re-sorted by rank with a stable sort; `std::map` iteration ascending by `Unique`
  (high dword signed, then low dword unsigned, as in the lookups of S 006652d0).
- **Random generator.** The simulation generator (`LogicRandom_Next`) is drawn once per
  `FlagParking::FindFreeSpot` (S 00671730: skip count = `(rand mod 4) * 3 + (tickCounter & 7)`) [known]. The
  street search itself does not draw (`BuildPath` is called with `randomize = false` by the planner,
  S 00663bf0); the AI's street planning does (`AiStreetPlan::PlanPath` S 005a96b0 calls `BuildPath` with
  `randomize = true`) [known].
- **Floating point.** Street length: per step `1/f(a→b) + 1/f(b→a)` with f ∈ {1.0, 0.8, 0.6, 0.4} loaded as
  float32 constants; the first quotient and the step sum are each stored as float32 (S 0052e320), and the
  running total is stored as float32 after every step (S 00668fbe, S 00669023), then truncated to int
  (S 00668f90) [known, disassembly]. So the length is a float32 sum of float32 step terms: 2.0 (flat), 2.25
  (slope class 1), 3.5 (class 3 or 4) are exact, the class-2 term is the float32 `0x402AAAAA`
  = 2.6666665077…, **below** 8/3 [inferred: IEEE float32 evaluation of the instructions read; the x87
  precision setting does not change these four terms]. A reimplementation must reproduce the truncated length
  exactly (it is an edge weight and is saved) and must use float32 arithmetic: exact rational arithmetic gives
  a different length whenever the exact sum is an integer reached through class-2 steps (three class-2 steps:
  7, not 8; six: 15, not 16; thirty: 79, not 80). `avgTraffic`: float32 `(a + float(len*n)) * 0.5`, compared
  with 130.0 (S 00668e10); terrain reshaping converts floats to int heights (S 00673370). Everything else in
  this subsystem is integer.
- **Stale cache as state.** Because cached path costs keep the busy factor of the moment they were computed
  (§3.6), the supplier chosen for a need can depend on history. Two machines stay in sync only because both fill
  the cache at the same ticks; a call to `GetFlagPathCost` from presentation code would desynchronise
  [inferred]. The callers read are all simulation or AI code. The one user-interface query that could reach the
  cache switches it off for its duration with `cacheDisabled` (§2.1, S 00623da0) [known].
- **Single path finder.** One finder and one `searchMark` per flag are shared by all searches and by the flood
  fill; searches never nest [inferred].
- **Local-only data touched from the simulation**: selection clearing in `RemoveStreet` / `RemoveFlag`
  (`ai::game::Selection`) is presentation state, not checksummed [inferred].

---

## 9. Notes for a reimplementation

Can be simplified without changing behaviour:

- the reference objects (id + cached pointer) can be plain handles;
- the two-sided "link" helpers (`StreetLink_*`, `TransportLink_*`, `RefLink_*`) are bookkeeping; keep the side
  effects listed in §3.5 and §3.9 (continent recomputation, ticket resets, callbacks);
- the path-cost cache can be dropped **only** if original saves and lockstep with the original are not goals; its
  staleness changes supplier choice (§8);
- `NetContinentIds` is an index that can be recomputed from flags and the map continents, under the same
  condition as the cache: it is saved and part of the checksum (§7, §8);
- `StreetConstructorPoints` / `StreetBuildMode` are UI.

Must be exact for compatibility with original saves, maps and lockstep:

- the cell rules of §3.1–§3.2 and the step costs (they decide which paths exist and which is chosen);
- the length formula in float32 and its truncation (§3.4, §8);
- the edge cost with the ×3 rule, FIFO tie-break of the open list and the predecessor rule (§3.6);
- iteration orders listed in §8 and the update periods and stagger moduli of §4;
- the admission rules of flags (reserve of the last place, ticket protocol, exchange rule) and all constants of §6;
- the need iteration (players, categories, rank-sorted goods, one node per network) and the three selection rules;
- the number of `Unique` draws per operation.

Behavioural summary for a designer: goods move one unit per package from flag to flag; each street has one carrier
who shuttles between its two flags and picks the highest-priority waiting package (lowest rank number), a package
whose far flag has no room for its good counting 50 ranks worse unless he can take a package in exchange there.
Routes are shortest by street length, where a
street whose carriers all have their hands full counts three times as long. Busy streets (length × deliveries per
10 game minutes above 130 on average) get a second carrier if the tribe has one. A flag holds 12 packages in 6
single-good stacks of 2 and keeps its last place in reserve; a carrier who cannot put a package down for up to
about 6 game minutes (more than 360 failed tries) has the good booked into the stock of the nearest building of
the searched list that is connected by streets (§3.9), without walking there, and the package disappears; it
disappears without being booked when there is no such building.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.8, "Losing the job"): the street keeps the carrier in its slot, stays usable and orders nobody until the carrier object is destroyed. The code conditions are known (§3.8: displaced and off the cell centre after the stop, or `AdvanceStreetRoute` S 00657b80 starts no walk back to `mid`). Open: in which play situations a waiting carrier meets them | a hook of S 00656740 logging caller, cell and fine position over a long run |
| 2 | Answered (§3.7): yes; the street stays usable through slot 2, orders nobody, and the second carrier works without reading slot 1 | static: S 00668ce0, S 00668e10, S 0065b200 |
| 3 | Answered (§3.9, "Fate of a stack-less package"): no carrier or ship ever finds it (all flag-side searches walk the stacks, S 0066cdd0); it stays in the package list, can hold a return building or a need without moving, and leaves only by stock +1 at its own flag's building, delivery on its need's target flag or a discard; the flag destructor S 0066a8d0 does not see it. Reachable only through the two attach paths without a stack test; a production worker at a full flag does not reach it [live, 2026-10-12] | — |
| 4 | After a street swap of two second carriers on streets without first carrier the end flags keep different kind-0 ids (§3.5). How long: answered (§3.5) as far as code goes, until the next kind-0 recomputation from a flag of either part (the only triggers are carrier slot changes and type-3 street links, caller list of S 00667a30). Open: does it happen in play | observe two neighbouring upgraded streets that both lost their first carrier, with a blocked flag between them |
| 5 | Answered (§3.8, after `rank(good)`): yes. No package creator consults the priority list; `ConquerBuilding` S 0055a890 (script functions `vi_changePlayerOfBuilding`, `pl_changePlayer`) keeps the old building's stocks for a new owner of another tribe, and a forged `0x20021` may omit goods. Military capture moves no stock | — |
| 6 | Answered (§3.9, "Extra units of a worker's product"): index 0 is product slot 0 (`bp_setGoods`, `BuildingProperty+0x44`); `GetGoods` S 00552f30 indexes `+0x44 + slot × 8`, written only by `SetGoods` S 00552ef0 from `bp_setGoods` (slot 0) and `bp_setSecondGoods` (slot 1) | — |
| 7 | Answered (§3.8 GoToPackageTarget, §4): `SettlerMovement+0x38` is `rough.finalTarget`, the target cell of the current rough move (writer `Rough::StartMoveTo` S 00773c10; constructor and load besides), not the next step cell; settler `+0x10` is `unique.idLo` | — |
| 8 | Can an open need change its category (§2.6) between `AddNeed` and `RemoveNeed`, which would make `RemoveNeed` use a null entry? Candidates: a `depot` building whose construction values change sign while a need of it is open (the shipped upgrade chains hold no `depot` type) | static: the writers of `Construction+0x70/+0x74` against the callers of `NeedGoods::CancelRequest` / `ClearAll` |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00665ef0 | `NNet::System::Update` | per tick: flags on lost territory, `Street::Update` |
| 00666900 | `NNet::System::PlaceFlag` | create a flag, split a street |
| 00666d00 | `NNet::System::BuildStreet` | create a street from a cell path |
| 006662f0 | `NNet::System::AttachStreetToFlags` | resolve / create end flags, link |
| 00666590 | `NNet::System::CreateStreetAtFlag` | street under construction |
| 006652d0 / 00665c10 | `NNet::System::RemoveStreet` / `RemoveFlag` | removal |
| 00665930 / 00665750 | `RemoveForeignStreetsInRadius` / `RemoveStreetsOutsideTerritory` | territory loss |
| 00667a30 | `NNet::System::RecomputeFlagContinent` | connected components |
| 00666250 | `NNet_CollectConnectedFlags` | flood fill |
| 00667f30 | `NNet::System::GetFlagPathCost` | cached distance between two flags |
| 006666d0 | `NNet::System::GetNextHopFlagCell` | next flag on a route |
| 0066cd20 / 0066cc30 | `StreetPathFinder::Search` / `Step` | Dijkstra over flags |
| 0066b9e0 | `StreetPathFinder::GetLinkCost` | edge cost, ×3 rule |
| 0066cb40 / 0066be20 | `CollectPathCells` / `GetPathCost` | route reconstruction |
| 006640d0 / 00668050 / 006654f0 | `NNet::System::Store` / `Load` / `PostLoad` | save format |
| 0066b010 / 0066a8d0 | `NNet::Flag::ctor` / `dtor` | flag life cycle |
| 00669f70 / 0066a020 | `Flag::GetRemoveBlockReason` / `GetWaterStreetBlockReason` | gate of the flag-destroy command (0 = removable) / flag test of water-street placement (1 = harbour-linked, 2 = not a shore cell, 0 = usable) |
| 0066b730 / 0066b970 / 0066b6f0 | `FlagPackageStacks::AddPackage` / `CannotTakePackage` / `IsFullForGood` | flag capacity |
| 00671590 / 00671530 / 006713c0 | `PackageStack::CannotAcceptReserveLast` / `CannotAccept` / `IsFullOrRejectsType` | stack tests |
| 00669cd0 / 00669210 | `NNet::Street::ctor` / `dtor` | street life cycle |
| 006695a0 / 00668f90 | `Street::AppendCell` / `UpdateLength` | geometry, length |
| 00668e10 | `NNet::Street::Update` | carrier orders, upgrade |
| 006710a0 / 00670fe0 / 00670d40 / 00670e80 | `StreetMapUpdater::AddToMap` / `RemoveFromMap` / cell rules | map registration |
| 0053c6a0 / 0053c720 | `StreetLink_LinkFlags` / `UnlinkFlags` | flag–street links |
| 0053ca20 / 0053ca80 / 0053cb20 / 0053cb40 | carrier slot link / unlink | carrier–street links |
| 0052f8a0 | `GameQuery::CanPlaceFlagAt` | flag placement rule |
| 0052fb10 / 0052f5c0 / 0052f980 / 005300e0 | `CanStreetPassCell` / `CanStreetStepTo` / `CanSplitStreetWithFlagAt` / `CanCompleteStreet` | street placement rules |
| 0052f3d0 / 0052f270 / 0052e550 | `IsOwnedCellFree` / `IsPlayerTerritoryCell` / `Map_IsShallowWaterCell` | cell predicates |
| 00776180 / 00776500 / 00776330 / 007761f0 | `AStarStreet::CanSearch` / `GetStepCost` / `...Mode2` / `...Mode3` | street search costs |
| 00676840 / 00676900 / 00676d10 | `NMap::AStar::GetStepCost` / `FindPath` / `BuildPath` | base cell search |
| 00663bf0 / 006636e0 / 00663900 | `StreetPlanner::ExtendTo` / `BuildStreet` / `IsPathValid` | planner |
| 0064cbe0 | `NTransport::System::Update` | periods 11 / 3 / 5 |
| 0064cc60 / 0064cc90 | `NTransport::System::DeliverPackage` / `DiscardPackage` | end of a package |
| 0064d020 | `NTransport::System::SpawnCarrierWithPackage` | a good leaves a building |
| 0064d9d0 / 0064cd90 | `SpillGoodsOntoFlag` / `CreatePackageAt` | goods onto a flag |
| 0064dae0 | `Transport_CarrierTryPlacePackageOnFlag` | admission, ticket, blocked message |
| 0064d410 / 0064d590 | `CarrierBeginDropAtFlag` / `PutDownCarriedPackage` | drop |
| 0064d8d0 / 0064d7e0 | `CarrierChoosePackageOnStreet` / `FindBestPackageToCarry` | package choice |
| 0064d120 / 0064d2f0 / 0064d750 | `CanSwapPackagesAtFlag` / `FindBestSwapPackageOnFlag` / `FindSwapPackageAtStreetEnd` | exchange |
| 0053c980 / 0053c9d0 | `TransportLink_AttachPackageToFlag` / `DetachPackageFromFlag` | package–flag link |
| 0064f3a0 / 0064f470 / 0064f510 / 0064f4c0 | `TransportMovement::ComputeNextHop` / set next hop / `RevalidateNextHop` / `OnPlacedOnFlag` | package routing |
| 0064ef20 / 0064ef90 | `ai::transport::TransportTarget::GetTargetFlag` / `ai::transport::TransportMovement::GetNextWaypoint` | target flag (a ship's: its `targetHarbor`'s flag), waypoint |
| 0064d280 | `NTransport::System::IsCarrierAtPackageDestinationFlag` | carrier at the destination flag of a building target |
| 00652170 | `NTransport::NeedSystem::Update` | need dispatcher |
| 00651f10 | `NeedSystem::SettleIdlePackages` | release / deliver idle serving packages |
| 00652420 / 00651bc0 / 00651cb0 | `NeedSystem::CreateNeed` / `DeliverPackage` / `DiscardAssignedPackage` | need life cycle |
| 006541e0 / 00652e00 / 00651330 / 00652b70 | `GoodOrder_GetCategory` / select order / `GoodOrderStockAgeScorer::ConsiderNeed` (stock-and-age score) / arrangement | need selection |
| 005c10f0 | `NPlayer::GoodArrangement::FindGroupForGood` | group whose id equals `GoodProperty+0x78` |
| 006538f0 / 00653250 / 00653180 | sorted entries / `ai::logistics::GoodOrderIterator::NextNode` / `NextNodeInPlayer` | need iteration |
| 006506a0 | `NTransport::PackageNeedSystem::Update` | free packages to storehouses |
| 006501d0 / 006502d0 | `HasFreePackageInNetwork` / `FindNearestFreePackage` | free package lookup |
| 00557da0 / 00557ef0 / 006517d0 | nearest connected supplier (with good / any) / `Transport_FindSupplierBuilding` | supplier search |
| 0065b710 / 0065b200 / 0065ad70 | `Carrier::Update` / `UpdateStreetTransport` / `UpdateDropOffAfterSpawn` | carrier state machines |
| 0077ac50 / 0077a2f0 / 0077a8e0 | `WaitForPackage::Update` / `GoToPackageTarget::Update` / `PutDownPackage::Update` | carrier movies |
| 0077a260 | `GoToPackageTarget::Start` | walk start, `CancelRoute` on his own street |
| 0065aec0 | `Carrier::ReleasePackages` | carried package discarded, claim and reservation unlinked |
| 0077a0f0 / 0077a150 | free / loaded partner tests | street swap |
| 0064d1a0 | `NTransport::System::ShouldKeepWalkingToFlag` | walk-on test of a loaded carrier |
| 0077a0c0 / 00557fe0 / 00557ef0 | give-up test / `BuildingList_FindNearestReachable` / `FindNearestConnected` | giving up a blocked package |
| 007781e0 / 00777e00 / 00777d10 / 00777d50 / 0065f040 | `Pickup::Start` / `Update`, `Drop::Start` / `Update`, `Animation::Tick` | hand-over timers |
| 00664fb0 | `StreetNet_AssignCarrierToSplitStreet` | carrier after a split |
| 007735b0 / 007741e0 / 00657b80 | `StreetRoutePlan::Plan` / `StreetPath::ComputeRoute` / `ai::settlers::SettlerMovement::AdvanceStreetRoute` | settlers walking by street |
| 0066d390 / 00671730 | `FlagParking::FindFreeSpot` / `FreeSpotSearch::Init` | waiting spots, random draw |
| 00671790 / 0052e090 | `FreeSpotSearch::VisitCell` / `GameQuery::IsCellFreeOfObjectsAndStreets` | the 19-position spiral, the free-cell test |
| 005c2620 | `NPlayer::GoodPriorities::GetRankOfGood` | rank of a good |
| 005c2bf0 | `NPlayer::GoodPriorities::InitFromGoodTable` | default priority list |
| 00656740 / 006567f0 / 00656ec0 / 00776d00 | `Settler::StopAndSetState3` / `IsStateNotIdleLike` / `Settler::Update` / `LeaveMap::Start` | a carrier losing his job |
| 0065ab00 / 0065afb0 | Carrier working position (vtable +0x2c) / `Carrier::dtor` | waiting cell, slot release |
| 00676700 / 0067bef0 / 0067c560 / 0067c0e0 | `NMap::AStar::Step` / `PushOrImprove` / open-list insert / `GetDescentDirections` | cell search order and tie-breaks |
| 00673370 / 00673bd0 | `MapModifier::SetElevationAlongStreet` / `FlattenAroundCell` | terrain under streets and flags |
| 00670cb0 / 00670d00 / 00670bd0 | `StreetMapUpdater::GetStartFlag` / `GetEndFlag` / `NNet_Flag_HasOtherNonState3Link` | end flags for map registration |
| 00781290 / 005ad880 / 00559db0 | `HandleRemoveStreet` / Lua `map_createDoodad` / `NVillage::System::RemoveBuilding` | removal callers |
| 00564580 / 00559940 | `SettlerSpawn::IsReadyToSpawn` / `NVillage::System::IndexBuilding` | supplier readiness, the `depot` list |
| 00652b70 / 005c30c0 / 00533b20 | `GoodOrderBucket_SelectByArrangement` / `ArrangementBase::PickNext` / default building type | goods distribution |
| 00652fd0 | `GoodOrderIterator::AddUniqueNode` | one node per network |
| 00623da0 | `nMenu::ActionButton::RefreshAvailability` | the only writer of `cacheDisabled` = 1 |
| 0066b470 / 006707f0 / 00664550 | `Flag::Load` / `NetContinentIds::Load` / `NNet::System::StoreForChecksum` | load gates, checksum |
| 00651530 / 0064f060 / 0064ee00 / 00652900 / 00775740 | `Package::Store` / `TransportMovement::Store` / target store / `NTransport::NeedGood::Store` / `NLogic::Need::Store` | transport records |
| 0054c4a0 / 0054c200 / 0054ad40 / 0054e670 | Lua property setters | data keys of §6 |
| 0054c410 / 0054c440 / 0054b120 / 00550150 | Lua property setters (`cfg_setPickupTime`, `cfg_setDropTime`, `hp_setWaterStreetPosition`, `dd_setDeleteByStreet`) | data keys of §6 |
| 005454f0 | `NDoodads::Object::ShouldBeRemoved` | reader of `deleteByStreet` (street bit 0x2) |
| 0052e320 / 0052e250 / 0052d9e0 | `Movement_GetRoundTripCostBetweenCells` / slope speed factor on land / slope class to factor | float32 step term of the street length |
| 0066a370 / 00669090 / 0066d8e0 / 00670b90 | `Flag::Store` / `Street::Store` / `NetContinentIds::Store` / `StreetMapUpdater::Store` | net records |
| 0066a5f0 / 00668d60 / 00670f40 | `Flag::PostLoad` / `Street::PostLoad` / `StreetMapUpdater::PostLoad` | post-load |
| 0064cdd0 / 0064f640 / 00650080 / 00651840 | `NTransport::System::Store` / `PackageSystem::Store` / `PackageNeedSystem::Store` / `NeedSystem::Store` | transport save format |
| 00651220 / 00651dd0 | `PackageNeedSystem::RebuildGoodIndex` / `NeedSystem::ResolveReferences` | indexes rebuilt after a load |
| 0065a840 / 0065a930 | `Carrier::Store` / `Load` | carrier record, version gate |
| 0064d0b0 / 005bcea0 / 0064cd60 | `UnloadPackageFromCargo` / `NavyCargo::UnloadOnePackage` / `Transport_LoadPackageIntoHolder` | cargo to and from a harbour flag |
| 0053d2b0 / 0053d2d0 | `VillageLink_LinkSettlerToDepot` / `UnlinkSettlerFromDepot` | the depot's `settlerRefs` |
| 00669e60 / 00669eb0 | `Flag::LinkNavyObject` / `UnlinkNavyObject` | harbour link of a flag, callbacks |
| 00532280 / 00532400 | `MapUpdateBatch::RemoveObstructedDoodadsAtCell` / `MapUpdateBatch::InvalidateConstructionAroundCell` (map-update batch) | per-cell map change reports |
| 00668be0 / 0065b150 | `Street::SpawnCarrier` / `Carrier::AssignToStreet` | carrier created on a street / assigned to one |
| 005a96b0 | `AiStreetPlan::PlanPath` | AI street search with `randomize = true` |
| 005b39d0 / 0055a640 / 00654ce0 | `NNavy::System::Update` / `NVillage::System::Update` / `NSettlers::System::Update` | tick steps 14, 6, 9 |
| 006705c0 / 006706e0 / 00664f40 | `NetContinentIds::AddNetContinent` / `RemoveNetContinent` / `NNet::System::ContinentIdsContain` | the continent index |
| 0052eba0 | `Navy_AreContinentsConnectedForPlayer` | map continents joined by a sea route (mode 1 home search) |
| 0066a170 | `NNet::Flag::FindLinkToFlag` | first link to a flag, any street |
| 00652740 / 006527a0 / 006533c0 / 00568770 | `GoodOrderStore::AddNeed` / `RemoveNeed` / `GoodOrderPlayerBlock::FindBucketForGood` / `OrderBucketEntry::RemoveFirstValue` | open-need index |
| 00650990 / 006505d0 / 00650430 | `PackageNeedSystem::UnregisterPackage` / `RemovePackage` / `EraseTarget` | free package taken or removed |
| 0064fb10 / 00651670 / 0064f780 / 006514b0 / 0064f270 | `PackageSystem::CreatePackage` / `Package::ctor` / `PackageSystem::RemovePackage` / `Package::dtor` / `TransportMovement::Destruct` | package life cycle |
| 0064cce0 / 0053c880 | `CreateCarriedPackage` / hand link | a carried package is linked to the hand after the "created" notice |
| 0053c8c0 | `TransportLink_LinkPackageToOrder` | target set for a need |
| 005644f0 / 00564360 | `SettlerSpawn::SpawnCarrier` / `ConsumeSettlerGood` | carrier spawned with a package |
| 0066b640 / 005289b0 | `FlagPackageStacks::Init` / `NLogic::System::BuildPlannedStreet` | flag stacks / finishing a planned street |
| 00776260 | `NLogic::AStarStreet::PrepareSearch` | mode-3 search state from the harbour bits |
| 00663a00 | `StreetPlanner::CommitPathTo` | a click on the planned path: cut, restart, re-add |
| 0066a1f0 / 00663f50 | `NNet::Flag::FindShortestLinkToFlag` / `NNet::System::FindNearestFlagWithLink` | parallel streets; nearest flag of a net continent |
| 00532960 | `Entity_IsIdle_88_Flags` | block reason 4 of `GetRemoveBlockReason`: `constructionTime < 1` and not the headquarters type |
