# Property database: goods, buildings, settlers and patterns

The data dictionary of the game's rules: every record type of `ai::properties::PropertiesDb`, the Lua key that
fills each field, its type, default and meaning, how records refer to each other, and how the three tribes differ.

- Binary: `sadk_noav.exe` (image base `0x400000`); addresses are written `S 00xxxxxx`.
- Data: the 22 scripts in `data/game/scripts/properties/` of the install (encrypted; read with
  `tools/sadk_crypt.py`). Values quoted here are examples, not the full tables.
- Status tags: **[known]** = read in the code at the given address or in the named data file and key;
  **[inferred]** = one step of reasoning from what is visible; **[TODO]** = not established. Nothing in this
  document has been observed in the running game.
- When the database is loaded, reloaded and cleared is covered by [../data-loading.md](../data-loading.md) §1 and
  is not repeated here. The list of the 243 Lua bindings with their addresses is in
  [../lua-surface.md](../lua-surface.md) §3.3.
- How the simulation uses the values is specified in the sibling documents; this document names the reader and
  links there: [village-buildings.md](village-buildings.md), [settlers-jobs.md](settlers-jobs.md),
  [military.md](military.md), [map-resources.md](map-resources.md), [players-victory.md](players-victory.md),
  [streets-transport.md](streets-transport.md), [logic-core.md](logic-core.md),
  [game-commands.md](game-commands.md), [../navy-and-military.md](../navy-and-military.md).

---

## 1. Purpose and scope

The property database is a process-wide, read-only (after start-up) store of static game rules. It holds:

- one record per **tribe**, **good** (wares, settler professions, soldier ranks and good groups share one table),
  **building type**, **deposit type** (trees, fields, stone piles), **terrain pattern**, **doodad**, **building
  remains**, **animal**, **spawn point type**, **harbour orientation**, **sacrifice**, **AI profile** and
  **sound**;
- three singleton blocks of scalars: **GameConfig**, **MilitaryConfig**, **ShipConfig**;
- the **sign table** (which sign doodad a geologist plants for which resource and amount).

It is responsible for: creating the records from the Lua property scripts, storing them by id, and answering
lookups and a few derived queries (who produces a good, which goods belong to a group, soldier good by tribe,
kind and level, random deposit for a pattern).

It is **not** responsible for: any per-match state (stock, players, buildings: those live in the logic systems
and only hold record ids or record pointers); the graphics definitions that share names with records
(`buildings.xml`, `animals.xml`, `ships.xml`, `settler_config.xml`: [../asset-formats.md](../asset-formats.md),
[../data-loading.md](../data-loading.md) §2); texts (record names are keys or debug names).

There are no settler-type records separate from goods: a profession is a good of type `Settler` (§2.4) [known:
`Jobs.lua` creates them with `gp_create`].

---

## 2. Data model

### 2.1 The container: `ai::properties::PropertiesDb` (0xc4 bytes, singleton pointer S 00889dd8)

Created on first use by `NProperties::StaticAccess::EnsureInstance` S 0054a140 (ctor S 00549dd0) [known]. Every
table is a `std::map<int, T>` keyed by the record id, ordered by **signed** 32-bit comparison of the id
(S 00549040 compares `(int)key`) [known].

| Offset | Table | Value | Record size | Lua prefix | Create function | Records shipped |
|---|---|---|---|---|---|---|
| +0x00 | buildings | `BuildingProperty*` | 0xf8 | `bp_` | S 005498d0 | 104 (`buildings.lua`) |
| +0x0c | deposits | `DepositProperty*` | 0x84 | `dp_` | S 005499d0 | 53 (`deposits.lua`) |
| +0x18 | goods | `GoodProperty*` | 0xc0 | `gp_` | S 00549a50 | 176 (100 `Goods.lua` + 76 `Jobs.lua`) |
| +0x24 | `GameConfig*` | block | 0x60 | `cfg_` | ctor S 00555780 | `config.lua` |
| +0x28 | patterns | `PatternProperty*` | 0x4c | `pa_` | S 00549ad0 | 114 (`patterns.lua`) |
| +0x34 | remains | `RemainsProperty` (inline) | 0x44 | `rm_` | ctor S 005558a0 | 3 (`remains.lua`) |
| +0x40 | doodads | `DoodadProperty` (inline) | 0x4c | `dd_` | ctor S 00555970 | 168 (`doodads.lua`) |
| +0x4c | sign table | map good id → sorted vector of {threshold, doodad id}; byte flag at +0x58 | | `si_` | S 005574f0 | 26 entries (`signs.lua`) |
| +0x5c | `MilitaryConfig*` | block | 0x120 | `mi_` | ctor S 00554380 | `military.lua` |
| +0x60 | `NProperties::StaticAccess` | embedded accessor (vftable S 007e8030, +0x64 back-pointer) | 8 | | | |
| +0x68 | `ShipConfig*` | block | 0x30 | `sh_` | ctor S 005556c0 | `ship.lua` |
| +0x6c | animals | `AnimalProperty*` | 0x68 | `an_` | S 00549b50 | 12 (`animals.lua`) |
| +0x78 | sounds | `SoundProperty` (inline) | 0x5c | `sn_` | ctor S 00555a80 | 156 (`sounds.lua`) |
| +0x84 | AI profiles | `AiProperty*` | 0xd0 | `ai_` | S 00549bd0 | 6 (`ai.lua`) |
| +0x90 | harbours | `HarbourProperty*` | 0x9c | `hp_` | S 00549c50 | 8 (`harbors.lua`) |
| +0x9c | tribes | `TribeProperty*` | 0xc4 | `tp_` | S 00549cd0 | 3 (`defineTribes.lua`) |
| +0xa8 | sacrifices | `SacrificeProperty*` | 0xa4 | `sf_` | S 00549d50 | 77 (`sacrifices*.lua`) |
| +0xb4 | spawn point types | `SpRecord*` | 0x74 | `sp_` | S 00549950 | 12 (`spawnpoints.lua`) |
| +0xc0 | `bLoaded` byte | set to 1 at the end of `Properties_RegisterLuaLibrary` S 00550e40, 0 by ctor and `ClearAll` | | | | |

[known] for offsets, sizes and functions; record counts are counts of `*_create` calls in the scripts [known:
data] and match the live counts quoted in [../data-loading.md](../data-loading.md) for buildings, goods, tribes,
animals, AI profiles and sacrifices.

Each of the thirteen record tables is a 12-byte MSVC `std::map` member (head node at +4 and element count at +8
of the member): `buildingMap`, `depositMap`, `goodMap`, `patternMap`, `remainsMap`, `doodadMap`, `animalMap`,
`soundMap`, `aiMap`, `harbourMap`, `tribeMap`, `sacrificeMap`, `spMap`. The sign table at +0x4c is the 16-byte
member `signDoodads` (`ai::properties::SignDoodadTable`: a map plus the byte flag) [known] S 00549dd0.

Four flags are set to 1 by `Properties_RegisterLuaLibrary` before the bindings are registered:
`GameConfig+0x3c`, the sign table's byte (`PropertiesDb+0x58`), `MilitaryConfig+0x10c`, `ShipConfig+0x00`
[known]. `Properties_Db_ClearAll` S 005494a0 clears all four: `GameConfig+0x3c` (S 00555810),
`MilitaryConfig+0x10c` (S 00553f10), `ShipConfig+0x00` (S 00661ab0), and the sign table's byte as the last store
of the tree clear S 00556f20 (`tree+0xc` = `PropertiesDb+0x58`) [known]. `GameConfig+0x3c` and
`MilitaryConfig+0x10c` have no reader [known]: the property database is reached only through
`StaticAccess::EnsureInstance` S 0054a140, none of its 593 callers accesses either offset, and the only
functions typed on the two blocks are their constructors, setters and (for `MilitaryConfig`) the lookups
S 00553f40..S 00554750, none of which reads them. For `ShipConfig+0x00` and the sign table's byte no reader was
found either, but `NNavy::Ship` keeps the `shipConfig` pointer (its constructors S 005baba0, S 005bad60,
S 005bb290) and the sign table
is used through its own methods, so those two rest on the callers of `EnsureInstance` only [inferred].

`Properties_Db_ClearAll` empties the thirteen record tables and the sign table and sets `bLoaded` to 0; its only
caller is `CApplicationEx::Shutdown` [known]. Its three other callees are the one-instruction flag stores named
above, so the scalars of the three config blocks and the per-tribe maps inside `MilitaryConfig` and `ShipConfig`
keep their script values across it [known: bodies of S 00555810, S 00553f10, S 00661ab0].

`NProperties::StaticAccess` (vftable S 007e8030, 12 slots) is an index-based view for tools. The slots come in
four groups of three, in the order pattern, building, deposit, doodad [known: vftable contents]: the table's
record count (S 00556910, S 00556920, S 00556930, S 00556940 read the map sizes at `+0x30`, `+0x08`, `+0x14`,
`+0x48`), a string of the n-th record, and the id of the n-th record. The n-th record is found by stepping the
map iterator `n` times from `begin`, i.e. **in map order** (S 00556950, S 00556a20, S 00556ae0, S 00556bb0); an
index past the end returns 0 [known: S 00556a20]. The string is the record's `gfxName` (`+0x20`) for patterns
(S 00556a00) and its `name` (`+0x04`) for buildings, deposits and doodads (S 00556ac0, S 00556b90, S 00556c60)
[known: the added offsets; the buildings body was read in full, the three siblings have the same size and
callees]. [inferred] it serves the map editor's element lists (`nMenu::Debug::RefillElementList` calls
`GetBuildingProperty`).

### 2.2 Ids and references

- **An id is a 32-bit integer written in the scripts as a hexadecimal string**: `bavarians =
  properties.tp_create("b0d378a3")`. Every `*_create` binding parses its string argument with
  `Str_ParseHexUInt32` S 005455b0, creates the record with defaults, stores it under that id and returns the id
  to Lua as a number [known] (e.g. `LuaProps_tp_create` S 0054abb0). The script keeps it in a global variable;
  all later calls pass that variable.
- Parser rules [known] S 005455b0: at most 32 characters; characters `0x2a..0x3f` contribute their low nibble
  (so `0`..`9` are 0..9), `a`..`f` and `A`..`F` contribute `(c & 0xf) + 9`; parsing stops at the first other
  character; the digits are combined most significant first. Strings shorter than 8 digits are valid:
  `pa_create("fade0ff")` = 0x0fade0ff, `ai_create("1")` = 1 [known: data].
- Ids are arbitrary constants, not computed from the name [inferred: neighbouring records have sequential ids
  such as `e8cf2e75`..`e8cf2e7a` for `tree_10`..`tree_lava_02`, and `4545fac1`.. for `pattern_meadow1`..].
- The value pushed to Lua and used as the map key is the **signed** interpretation: `b0d378a3` is a negative
  key. Ordered iteration over a table therefore visits ids `0x80000000..0xffffffff` before `0x00000000..
  0x7fffffff` [known: signed compare in S 00549040; inferred for the consequence].
- Each table has its own id space; the same number could exist in two tables. `FindIdByNameAnyTable`
  S 00546100 searches all tables by **name** in the fixed order building, deposit, good, pattern, remains,
  doodad, animal, sound, AI, harbour, tribe, sacrifice, spawn and returns the first hit or -1 [known]; its
  only callers are the debug scatter tool (`nMenu::Debug::Scatter_AddElement`, `Scatter_AddPattern`,
  `Scatter_RemoveElement`) [known: callers]. The loaders of XML files that name records use the per-table
  lookups instead [known: callers]: `PropertiesDb::FindGoodIdByName` S 00545f50 (`CLandscape::ctor`,
  `AnimationSet::LoadRandomAnimationsXml`), `PropertiesDb::FindTribeIdByName` S 00546050 (`GoodSet::LoadFromXml`,
  `ShipMgr::LoadFromXml`), `PropertiesDb::FindSoundIdByName` S 00545f70 (`ProjectileTable::LoadProjectilesXml`,
  `SoundEvent::Desc::LoadFromXml`, `EffectMovieElement::Start`).
- "No record" is `-1` in every reference field [known: ctor defaults below].
- References between records are plain ids resolved at use time by `Get<Type>Property` (S 005474a0 ..
  S 005477a0). These getters have **no not-found path**: an unknown id trips the checked-iterator handler
  (`_invalid_parameter_noinfo`), i.e. the process dies [known]. Maps and saves store the same ids
  ([../map-format.md](../map-format.md) §2.4), so the ids are part of the file formats.

Reference graph (field → table) [known: setters; data for the examples]:

| From | Field | To |
|---|---|---|
| tribe | `goods`, `jobs`, start/bonus resources, `secondCarrierId`, `constructionGoodId`, `soldierUpgradeGoodId`, `workerToolGoodId`, `constructor` | good |
| tribe | `buildings` | building |
| tribe | `sacrifices`, `allowedSacrifices` | sacrifice |
| good | `costs[]`, `gfxGoodId`, `arrangementGoodId`, `miningGood` | good |
| good | `transportPriority`, `aiPriority` (map keys) | tribe |
| building | product slots, cost lists, `worker` | good |
| building | `producedSettler` | good (`good_oxen`) **or animal** (`animal_sheep` for `sheepBreeding`) |
| building | `upgrade` | building; `remains` → remains; `plantingDeposit` → deposit |
| building | keys of `doorOffsetDirection`, `constructionPositions`, `idlePositions` | tribe |
| deposit | `good` → good; `nextDeposit` → deposit; `undergroundPatterns` → pattern; `doodadAfterDestruction` → doodad | |
| deposit / pattern | `treeTypes` / `treeType` | plain numbers, not ids (§2.6) |
| remains | `doodadAfterFinished` | doodad |
| animal | `stackGoods` key → tribe, values → good | |
| spawn point type | `uniqueIds` | animal (type 1) [known: data]; for type 0 the first entry is a map resource type (§2.6); none shipped |
| sacrifice | `costs[]` → good; effect 1001 `arg1` → good | |
| AI profile | `favoriteSacrificeIds` | sacrifice |
| sound | `musicTribe` | tribe |
| GameConfig | `borderPattern` → pattern; `settlerSkeletonDoodad`, `chestDoodadId`, `openChestDoodadId` → doodad; `sacrificeGoodId` → good | |
| MilitaryConfig | `soldierId[kind][level][tribe]` | good |
| ShipConfig | `speed`, `expeditionBuilding` keys → tribe; value → building | |
| sign table | key → good (or -1); value → doodad | |

### 2.3 `TribeProperty` (0xc4), `tp_*`

Ctor S 00556300 [known]. Three records: `bavarians` `b0d378a3`, `egyptians` `f5016d33`, `scots` `497ffda3`.

| Offset | Field | Type | Lua key | Default | Meaning and reader |
|---|---|---|---|---|---|
| +0x00 | `id` | i32 | `tp_create(hex)` | -1 | |
| +0x04 | `name` | string | `tp_setName` | `"Unknown"` | `"Bavarian"`, `"Egyptian"`, `"Scots"`; name lookup `PropertiesDb::FindTribeIdByName` S 00546050 (`GoodSet::LoadFromXml`), computer-player name key ([players-victory.md](players-victory.md) §6) |
| +0x20 | `goods` | vector&lt;i32&gt; | `tp_addGood` | empty | the tribe's wares, in script order. Order matters: group members are enumerated in this order (§3.4), good priorities and statistics are seeded from it |
| +0x30 | `jobs` | vector&lt;i32&gt; | `tp_addJob` | empty | settler goods the tribe owns beyond workers: soldier ranks, `good_oxen`. Read with `goods` by `MapInfo::NormalizeInitialGoodsForTribes` S 0052a670 (§3.7) |
| +0x40 | `buildings` | vector&lt;i32&gt; | `tp_addBuilding` | empty | building types of the tribe (build menu, AI type finders, producer search §3.5) |
| +0x50 | `sacrifices` | vector&lt;i32&gt; | `tp_addSacrifice` | empty | the tribe's sacrifices ([inferred] the full set, including those that need research); `AddSacrifice` S 00556400 looks the sacrifice up first, so the id must exist [known]. The vector has no reader [known]: the property database is reached only through `StaticAccess::EnsureInstance` S 0054a140 (its global S 00889dd8 is read nowhere else), and of the 593 functions that call it only `AddSacrifice` touches the field; the ctor S 00556300 initialises it. The selection panel and the AI take their lists from the map (see `allowedSacrifices`); the list is inert data |
| +0x60 | `menuX` | i32 | `tp_setMenuX` | 0 | UI: x offset in the building icon texture (16 / 184 / 352) [inferred from the name and values] |
| +0x64 | `buildingsTextureName` | string | `tp_setBuildingsTextureName` | `"Unknown"` | UI texture `uiBuildings0..2` |
| +0x80 | `startResources` | vector&lt;{good, amount}&gt; | `tp_addStartResources` | empty | default of a map's initial goods; only for maps older than save format 14 and `MapInfo::Reset` ([../data-loading.md](../data-loading.md) §1) |
| +0x90 | `bonusResources` | vector&lt;{good, amount}&gt; | `tp_addBonusResources` | empty | extra headquarters stock for a player in the default state (`Depot::AddInitialStock` S 0055b020) |
| +0xa0 | `allowedSacrifices` | vector&lt;i32&gt; | `tp_addAllowedSacrifice` | empty | the default of a map's per-tribe sacrifice list (`MapInfo+0x204`, map tribe id → vector of sacrifice ids): `MapInfo::ResetSacrificesFromTribes` S 0052bb40 clears that map and copies this vector for every tribe, and `MapInfo::Load` S 0052bd40 calls it when the stored version is ≤ 12 [known]. Files of version ≥ 10 store the map's own list (§7). The map's list, looked up by the player's tribe id, is what the sacrifice selection panel (`nMenu::InfoBoxSacrificeSelect::Update` S 00637340) and the AI (`AiSacrificeState::Refresh` S 0059cf60) offer; a tribe without an entry gets an empty list [known: `MapInfo::HasMapSacrifices` S 00529760, `GetMapSacrifices` S 00529720 and their two callers] |
| +0xb0 | `secondCarrierId` | good id | `tp_setSecondCarrierId` | -1 | second carrier of an upgraded street ([streets-transport.md](streets-transport.md)); helpers S 00556020, S 00556060 |
| +0xb4 | `constructionGoodId` | good id | `tp_setConstructionGoodId` | -1 | a `WareGroup` good whose cost list names the tribe's construction materials (low-resources warning, [players-victory.md](players-victory.md)) |
| +0xb8 | `soldierUpgradeGoodId` | good id | `tp_setSoldierUpgradeGoodId` | -1 | the coin good (promotion, coin victory counter) |
| +0xbc | `workerToolGoodId` | good id | `tp_setWorkerToolGoodId` | -1 | the tool good (`NAI::LockSmith` keeps it stocked; low-resources warning) |
| +0xc0 | `constructor` | good id | `tp_setConstructor` | -1 | the builder profession of the tribe |

### 2.4 `GoodProperty` (0xc0), `gp_*`

Ctor S 00554da0, copy-assign S 0058bdc0 [known]. One table for four kinds of thing, told apart by `type`.

**`type` values** (`Goods.lua` constants; `GoodProperty+0x14`) [known: data and S 0054e960]:

| Value | Lua name | Meaning |
|---|---|---|
| -1 | `Invalid` | not used by any shipped record |
| 0 | `Ware` | a transportable ware. **Default**: 59 of the 100 `Goods.lua` records never call `gp_setType` |
| 1 | `Settler` | a profession / soldier rank / NPC; all 76 `Jobs.lua` records |
| 2 | `WareGroup` | a list of wares meaning "all of these" (29 records), e.g. `constructionResources` = plank + stoneScots |
| 3 | `EitherGroup` | a list of alternatives meaning "any one of these" (12 records), e.g. `foodScots` = fishScots, bread, sheepHam |

**`settlerType` values** (`Jobs.lua`; `+0x7c`; Ghidra enum `ESettlerType`) [known]: 0 `Worker` (53 records),
1 `Constructor` (3), 2 `Carrier` (2: `good_helper`, `good_oxen`), 3 `Soldier` (15), 4 `Specialist` (1:
`good_scholar`), 5 `NPC` (2: `good_garibaldNPC`, `good_treeMerchantNPC`); -1 for goods that are not settlers.

**`soldierType`** (`+0x80`): 0 `soldierType_Sword` (default), 1 `soldierType_Bow` [known].
**`projectileType`** (`+0xb8`): 0 `projectile_arrow`, 2 `projectile_bolt`, 3 `projectile_slingStone`; -1 none
[known: data]. Value 1 is not set by any script ([military.md](military.md) §2.1 assigns it to the catapult
stone, set in code).

| Offset | Field | Type | Lua key | Default | Meaning and reader |
|---|---|---|---|---|---|
| +0x00 | `id` | i32 | `gp_create(hex)` | -1 | |
| +0x04 | `costs` | vector&lt;{good, amount}&gt; | `gp_addCost(good, input, n)` | empty | **the recipe**. For a ware: inputs consumed per produced unit (`bread` = flour 1 + corn 1). For a settler: goods consumed to create one (`good_soldierHalberd1` = `good_soldierHalberd0` 1 + `coinBav` 1; a worker = tool 1). For a group: its members. Same good added twice merges amounts (§3.2). Readers: `Production::StartProductionCycle` S 005657c0, `Stock::CanAffordGoodCost` S 00539b90, `Stock::ExchangeCostForGood` S 0053a400, `GoodProperty::CostsContainGood` S 00554a60 |
| +0x14 | `type` | i32 | `gp_setType` | 0 | see above |
| +0x18 | `name` | string | `gp_setName` | `"unknown"` | debug / lookup name (`PropertiesDb::FindGoodIdByName` S 00545f50, `TribeProperty::FindGoodIdByName` S 005560d0). Not unique: `stoneScots`, `stoneBav` and `stone` are all `"Stone"` |
| +0x34 | `shortName` | string | `gp_setShortName` | `"?"` | never set by the shipped scripts [known: data] |
| +0x50 | `enableDeposits` | bool | `gp_enableDeposits(good, 0/1)` | false | the good is harvested from map deposits; set for wood, corn, egyptCorn and the three stone goods ([village-buildings.md](village-buildings.md) §3.9) |
| +0x51 | `enableFields` | bool | `gp_enableFields(good, 0/1)` | false | the good exists as an underground / water resource field; 21 goods (ores, coal, salt, gemstones, stone, fish, water). Read by AI code only, through the folded byte getter `Generic_GetByte_51` S 0046b620 (`MOV AL,[ECX+0x51]; RET`, shared with unrelated classes, which is why an operand search finds only the setter S 005549e0, the ctor and the copy-assign S 0058bdc0): `NAI::ProductionControl::IsGoodControllable` S 0058bad0, `DestructionSystem::CanDemolishBuilding` S 0058dae0, `GameQueryHelper::ScoreSite` S 00534830, `NeedsArrangement::InstantiateGroupNeed` S 005943c0, `Need::ctor_ForType` S 00597010 and `Need::PostLoad` S 00596f70 (map-resources.md §10 Q5) [known] |
| +0x54 | `value` | float | `gp_setValue` | 1.0 | never set by the shipped scripts. Not read [known]: written only by the setter S 00554a20 (from `gp_setValue` S 0054e910), the ctor S 00554da0 and the copy-assign S 0058bdc0; no x87 or SSE float access at `+0x54` lies in a user of the good property, and the typed decompilation shows no reader |
| +0x58 | `transportPriority` | map tribe → i32 | `gp_setTransportPriority(good, tribe, rank)` | empty | default rank in the player's transport priority list (`GetTransportPriority` S 00554b70). The key **must exist** for every (good, tribe) pair that is queried: a missing key is a fatal checked-iterator error |
| +0x64 | `aiPriority` | map tribe → i32 | `gp_setAiPriority(good, tribe, weight)` | empty | AI build-score multiplier (`GetAiPriority` S 00554bc0, `NAI::NeedsConstruction::SelectConstruction`); same must-exist rule |
| +0x70 | `plantable` | bool | `gp_setPlantable` | false | set for wood, corn, egyptCorn. Not read [known]: written only by `gp_setPlantable` S 0054e5c0 (setter S 00554a30), the ctor and the copy-assign; of the program's byte tests at `+0x70`, the one in `CanPlaceDepositAt_TerrainCheck` S 0052e150 reads `DepositProperty.needForPlantablePattern` and the one in S 00619ad0 a transport package |
| +0x74 | `gfxGoodId` | good id | `gp_setGfxGoodId` | -1 | settler goods: the ware whose model the settler carries (tool, weapon) |
| +0x78 | `arrangementGoodId` | good id | `gp_setArrangementGoodId` | **the good's own id**: the ctor writes -1, then `Properties_CreateGoodProperty` S 00549a50 stores the id at `+0x00` and at `+0x78` (S 00554a40) [known] | the group under which this good is listed in the goods-distribution panel (`NPlayer::GoodArrangement::FindGroupForGood` S 005c10f0); e.g. bread, fishScots, sheepHam → `foodScots`. A good that never calls the setter is its own group |
| +0x7c | `settlerType` | i32 | `gp_setSettlerType` | -1 | see above; `Settler::GetSettlerType` S 00656820 |
| +0x80 | `soldierType` | i32 | `gp_setSoldierType` | 0 | soldier kind |
| +0x84 | `hitDamage` | i32 | `gp_setHitDamage` | 0 | base damage per strike |
| +0x88 | `health` | i32 | `gp_setHealth` | 0 | maximum life points; cached into `MilitaryConfig` by `mi_setSoldierId` (§3.3) |
| +0x8c | `aiRandomValue` | i32 | `gp_setAiRandomValue` | 0 | AI weight when it instantiates one member of a group need (`NAI::NeedsArrangement::InstantiateGroupNeed` S 005943c0); e.g. bread 6, fishScots 10, sheepHam 1 |
| +0x90 | `armor` | i32 | `gp_setArmor` | 0 | subtracted from every hit taken |
| +0x94 | `attackWaitTime` | i32, ticks | `gp_setAttackWaitTime` | 0 | pause after a strike |
| +0x98 | `blockingChance` | i32, percent | `gp_setBlockingChance` | 0 | see [military.md](military.md) §3.7 |
| +0x9c | `attackTime` | i32, ticks | `gp_setAttackTime` | 17 | length of a strike |
| +0xa0 | `bowRange` | i32, cells | `gp_setBowRange` | 6 | ranged soldiers |
| +0xa4 | `aiNeedsCosts` | bool | `gp_setAINoNeedForCosts(good)` clears it | true | when false the AI does not plan the inputs of this good (5 goods: stone variants and similar). The binding takes no value |
| +0xa8 | `hitTimes` | vector&lt;i32&gt;, ticks | `gp_addHitTime` | empty | moments within the strike at which the hit lands (`HasHitTimeInRange` S 00554ae0: `prev < t <= cur`). `good_soldierSword0` has two (4 and 15) |
| +0xb8 | `projectileType` | i32 | `gp_setProjectileType` | -1 | `ai::settlers::Bow::Shoot` S 0065f270 |
| +0xbc | `miningGood` | good id | `gp_setMiningGood` | -1 | the tribe-neutral resource this tribe good stands for (`stoneScots` → `stone`, `fishBav` → `fish`). Names the map resource a mine or fisher searches, and translates map initial goods between tribes (§3.7) |

Soldier ranks in the shipped data [known: `Jobs.lua`], four of the fifteen as examples:

| Good | costs | damage | health | armor | wait | block | attack | hit at | range | projectile |
|---|---|---|---|---|---|---|---|---|---|---|
| `good_soldierHalberd0` | halberd 1, weissbeer 1 | 10 | 100 | 5 | 19 | 2 | 11 | 4 | | |
| `good_soldierClaymore2` | `good_soldierClaymore1` 1, coinScots 1 | 24 | 300 | 8 | 15 | 6 | 11 | 5 | | |
| `good_soldierSword0` | sword 1, milk 1 | 9 | 50 | 4 | 12 | 1 | 18 | 4, 15 | | |
| `good_bowSoldierCrossBow2` | `good_bowSoldierCrossBow1` 1, coinBav 1 | 19 | 200 | 0 | 1 | 0 | 27 | 6 | 7 | bolt |

Ranges over all fifteen: damage 9..26, health 50..300, armor 0..8, wait 1..19, block 0..6, attack time
11/18/22/27, range 5..7.

### 2.5 `BuildingProperty` (0xf8), `bp_*`

Ctor S 00553cf0, dtor S 00553b90 [known]. Field use is specified in [village-buildings.md](village-buildings.md)
§2.1 and §6; this table is the complete list of fields.

| Offset | Field | Type | Lua key | Default | Meaning |
|---|---|---|---|---|---|
| +0x00 | `id` | i32 | `bp_create(hex)` | -1 | |
| +0x04 | `name` | string | `bp_setName` | `"unknown"` | `"Castle"`, `"Bakery"`, `"WoodcutterHut"`; not unique across tribes |
| +0x20 | `gfxName` | string | `bp_setGfxName` | `"unknown"` | graphics definition name (`buildings.xml`) |
| +0x3c | `size` | bit mask | `bp_setSize` | 1 | plot classes the type fits, §3.6 |
| +0x40 | `spawn` | bool | `bp_setSpawn(b, 0/1)` | false | settlers are created here (castle, storehouses, barracks) |
| +0x44, +0x48 | product slot 0 `{goodId, amount}` | i32, i32 | `bp_setGoods(b, good, n)` | -1, 0 (S 00552c00) | first product and units per cycle; its `costs` are the building's recipe |
| +0x4c, +0x50 | product slot 1 `{goodId, amount}` | i32, i32 | `bp_setSecondGoods(b, good, n)` | -1, 0 | second product; only `goatBreeder` (goat 1 + milk 1) |
| +0x54 | `depot` | bool | `bp_setDepot(b, 0/1)` | false | stores wares and settlers |
| +0x58 | `frameCost` | vector&lt;{good, amount}&gt; | `bp_addFrameCost` | empty | materials of construction phase 1 (scaffold) |
| +0x68 | `cost` | vector&lt;{good, amount}&gt; | `bp_addCost` | empty | materials of phase 2. `GetAllCosts` S 00553460 returns frame cost + cost |
| +0x78 | `workingRadius` | i32, cells | `bp_setWorkingRadius` (Lua number truncated to int) | 4 | search radius of the worker |
| +0x7c | `workerLimit` | i32 | `bp_setWorkerLimit` | 1 | workers employed; 0 for storage and military |
| +0x80 | `workingMode` | i32 enum | `bp_setWorkingMode` | 6 | see below |
| +0x84 | `stockLimit` | i32 | `bp_setStockLimit` | -1 | units per input / output good kept in the building |
| +0x88 | `constructionTime` | i32 | `bp_setConstructionTime` | 500 | only ever set to -1 (castle, Olympic flame) = cannot be built by the player. `Economy_CollectConsumerBuildings` S 00534f40 treats `> 0` as "constructible" [known] |
| +0x8c | `health` | i32 | `bp_setHealth` | 0 | hit points against catapults and attacks (40..200) |
| +0x90 | `worker` | good id | `bp_setWorker` | -1 | profession employed |
| +0x94 | `territoryRange` | i32, cells | `bp_setTerritoryRange` | 0 | 9 / 10 / 11 for guard house / tower / fortress, 9 castle, 4 Olympic flame |
| +0x98 | `soldierLimit` | i32 | `bp_setSoldierLimit` | 0 | garrison size |
| +0x9c | `doorOffsetDirection` | map tribe → i32 | `bp_setDoorOffsetDirection(b, tribe, dir)` | empty | extra step direction to the door; `DoorOffsetWest` 3, `DoorOffsetNorthWest` 4, `DoorOffsetNorthEast` 5; readers S 0055cdd0, S 0055ce20 with key = the building's variant key (owner's tribe) |
| +0xa8 | `remains` | remains id | `bp_setRemains` | -1 | ruin left when destroyed |
| +0xac | `exploreRadius` | i32, cells | `bp_setExploreRadius` | 0 | fog-of-war radius (12..16) |
| +0xb0 | `catapult` | bool | `bp_setCatapult` | false | |
| +0xb4 | `constructionPositions` | map tribe → vector&lt;{x, y} float&gt; | `bp_setConstructionPosition(b, tribe, i, x, y)` | empty | builder standing points, index 0..3 in the data (S 00553a50 grows the vector to `i + 1`; reader S 005532f0). The bindings S 0054d7e0 read `x` and `y` with `Lua_ToInt` and the setter converts the integers to float, so fractions are lost [known]; the data only uses whole numbers |
| +0xc0 | `idlePositions` | map tribe → vector&lt;{x, y} float&gt; | `bp_setIdlePosition(b, tribe, i, x, y)` | empty | idle spots, index 0..1 (S 00553af0; reader S 00553340) |
| +0xcc | `aiThreat` | i32 | `bp_setAiThreat` | 0 | AI: military threat value (30 guard house, 50 castle, 100 catapult) |
| +0xd0 | `aiScore` | i32 | `bp_setAiScore` | 20 | AI: value of owning one (40 bakery, 130 barracks, 300 catapult) |
| +0xd4 | `plantingDeposit` | deposit id | `bp_setPlantingDeposit` | -1 | what a forester / farmer plants (`tree_10`, `field_01`, `field_egypt`) |
| +0xd8 | `productionTime` | float, ticks | `bp_setProductionTime` | 0 | work duration per cycle |
| +0xdc | `catapultDamage` | i32 | `bp_setCatapultDamage` | 0 | 10 |
| +0xe0 | `restTime` | i32, ticks | `bp_setRestTime` | 0 | base of the pause between cycles |
| +0xe4 | `arrangementValue` | float | `bp_setArrangementValue` | -1.0 | default goods-distribution weight (data 0.3..1.0); -1 = not in the distribution |
| +0xe8 | `upgrade` | building id | `bp_setUpgrade` | -1 | guard house → tower → fortress |
| +0xec | `producedSettler` | good or animal id | `bp_setProducedSettler` | -1 | modes 4 and 10 |
| +0xf0 | `ignoreGoodCosts` | bool | `bp_setIgnoreGoodCosts` | false | the product's recipe is not requested as input (hunter, stone pit, temples, barracks, ship yard) |
| +0xf1 | `casern` | bool | `bp_setCasern` | false | trains soldiers (castle, barracks) |
| +0xf2 | `arrangementLocked` | bool | `bp_setArrangementLocked` | false | UI only (temples): the type gets no row in the goods-distribution panel (`IsEntryUnlocked` S 005c0fd0 ← `ShowGoodDistribution` S 006413c0) and does not count toward the "more than one adjustable consumer" rule of a group button (`CountUnlockedEntries` S 005c1000 ← `RefreshWaregroupButtons` S 006410e0); its weight stays in the distribution; no simulation reader [known] |
| +0xf3 | `gfxBreeding` | bool | `bp_setGfxBreeding` | false | graphics only: selects the render class `S2CG::FarmBuilding` (`BuildingRenderer::AddBuilding` S 006a2bf0, test at S 006a2ea6; ctor S 006d59e0), which shows the gfx definition's `<Production>` models (e.g. `FarmOx.KEX` × 5 on the bone links, idle animation at a random time offset); the sacrifice working mode 9 and the catapult take precedence; its only reader [known] |
| +0xf4 | `productivity` | bool | `bp_setNoProductivity(b)` clears it | true | no productivity statistic when false. The binding takes no value |
| +0xf5 | `territoryBuilding` | bool | `bp_setTerritoryBuilding` | false | owns territory; listed with the military buildings |

`+0xa4` and the tail of the three maps are container internals. The position maps are keyed by tribe id so one
building record can serve several tribes with different models [known: S 00553a50 plate and data].

**`workingMode`** (`buildings.lua` constants) [known: data]; number of records that set it:

| Value | Lua name | Data comment | Records |
|---|---|---|---|
| 0 | `BuildingWorkingMode_Foresting` | forester or other planting job | 2 |
| 1 | `BuildingWorkingMode_Mining` | woodcutter and stone cutter | 6 |
| 2 | `BuildingWorkingMode_Farming` | "Farm...planting and foresting" | 3 |
| 3 | `BuildingWorkingMode_Fishing` | fisher | 3 |
| 4 | `BuildingWorkingMode_SettlerBreeding` | "donkey breeder"; also the barracks | 4 |
| 5 | `BuildingWorkingMode_Catapult` | catapult | 3 |
| 6 | `BuildingWorkingMode_Producing` | every building that turns input goods into a product; **default** | (69 by default) |
| 7 | `BuildingWorkingMode_Hunting` | hunting animals | 3 |
| 8 | `BuildingWorkingMode_Idling` | worker moves in and does nothing | 3 |
| 9 | `BuildingWorkingMode_Sacrifice` | sacrifice | 4 |
| 10 | `BuildingWorkingMode_AnimalBreeding` | spawn animals (`sheepBreeding`) | 1 |
| 11 | `BuildingWorkingMode_Scholar` | geologist | 3 |

Mines use the default mode 6 together with `SizeMine` [known: data; `AiTribe_FindMode6Size8BuildingForResource`
names the pair].

`buildings.lua` also defines `Depot_None` -1, `Depot_Local` 0, `Depot_Resources` 1, `Depot_Stuff` 2; no binding
call uses them [known: data].

### 2.6 Map object records: deposits, patterns, doodads, remains, animals, spawn point types

Use of these fields is specified in [map-resources.md](map-resources.md) §2.5 and §3.8–3.11.

**`DepositProperty`** (0x84), `dp_*`, ctor S 005553d0 [known]:

| Offset | Field | Type | Lua key | Default | Meaning |
|---|---|---|---|---|---|
| +0x00 | `id` | i32 | `dp_create` | -1 | |
| +0x04 | `name` | string | `dp_setName` | `"unknown"` | |
| +0x20 | `gfxName` | string | `dp_setGfxName(d, name, 0)` | `"unknown"` | the scripts pass a third argument 0 that the binding does not read [known: S 0054df10, data] |
| +0x3c | `good` | good id | `dp_setGood` | -1 | yield of a harvest (wood 38 records, stone 12, corn 1, egyptCorn 1). One record, `tent`, names the settler good `good_helper` (with growing start size 0.01 and speed 0.1) [known: data]. No other property script refers to `tent` (no `bp_setPlantingDeposit`, no `dp_nextDeposit`), and it has no tree type tags, so §3.8 never picks it: it exists only where a map or a map script places it [known: data]. The harvest step `NResources::System::HarvestDepositAt` S 00540c40 does not read `good` [known]. No worker search selects it [known]: both searches that match deposits by `good`, `Resources_FindNearestFreeDeposit` S 00540870 (sole caller `NVillage::Building::UpdateDepositSearch` S 0055bfb0) and `Resources_CountDepositsInRange` S 00540940 (sole caller the AI site scorer S 00534830), use the `miningGood` (+0xbc) of the wanted good as the key, and no good in `Goods.lua` has `miningGood = good_helper` (the keys are the raw resources wood, stone, corn, egyptCorn, fish and the five mine goods) [known: data] |
| +0x40 | `nextDeposit` | deposit id | `dp_nextDeposit` | -1 | the type this deposit becomes after one harvest; -1 = it disappears. Stone piles form two chains, `stone_06 → … → stone_01` and `med_stone_06 → … → med_stone_01`; `CountChainStages` S 00532480 = 1 + number of links |
| +0x44 | `growingStartSize` | float | `dp_setGrowingStartSize` | 0.1 | growth value after planting (fields 0.2) |
| +0x48 | `growingSpeed` | float per tick | `dp_setGrowingSpeed` | 0.0009 | `field_01` 0.00075, `field_egypt` 0.0005 |
| +0x4c | `randomFinePosOffsetState` | bool | `dp_setRandomFinePosOffsetState` | true | random display offset within the cell |
| +0x50 | `elevationSize` | i32 | `dp_setElevationSize` | 1 | 2 on the stone pile stages 03..06 of both chains (`stone_*`, `med_stone_*`), 1 on stages 01..02 [known: data]. The stop distance of the worker's fine walk onto the deposit: `NMovie::MoveToDeposit::Update` S 007778f0 reads it straight through the record pointer (`deposit +0x1c`, no getter) and passes it to `SetStopDistance` [known] ([settlers-jobs.md](settlers-jobs.md) §3.5.5, [map-resources.md](map-resources.md) §2.5) |
| +0x54 | `blocking` | bool | `dp_setBlocking` | false | the cell is not walkable |
| +0x58 | `undergroundPatterns` | vector&lt;pattern id&gt; | `dp_addUndergroundPattern` | empty | pattern painted under the deposit (`pattern_acre` under fields, `pattern_meadow2` under stone) |
| +0x68 | `doodadAfterDestruction` | doodad id | `dp_setDoodadAfterDestruction` | -1 | never set by the shipped scripts [known: data] |
| +0x6c | `lifeTime` | i32, ticks | `dp_setLifeTime` | -1 | fields 3000 |
| +0x70 | `needForPlantablePattern` | bool | `dp_setNeedForPlantablePattern` | false | fields: only on patterns with `forPlanting` |
| +0x74 | `treeTypes` | vector&lt;i32&gt; | `dp_addTreeType` | empty | tags, see below |

**Tree type tags** are plain numbers shared by `patterns.lua` and `deposits.lua` [known: data]: landscape tags
`None` -1, `CaribbeanFlair` 0, `ConiferousForest` 1, `BlackForest` 2, `Lava` 3, `Snow` 4, `Bavaria` 5, `Desert` 6,
`Highland` 7; map tags `mapTreeType_Bavarian` 100, `mapTreeType_Egyptain` 101, `mapTreeType_Scot` 102. A tree
deposit lists every landscape and map tag it may be planted for (`tree_10`: Desert, 100, 101, 102); a pattern
has exactly one landscape tag. The rule that combines them is §3.8.

**`PatternProperty`** (0x4c), `pa_*`, ctor S 00555c00 [known]:

| Offset | Field | Type | Lua key | Default |
|---|---|---|---|---|
| +0x00 | `id` | i32 | `pa_create` | -1 |
| +0x04 | `name` | string | `pa_setName` | `"unknown"` |
| +0x20 | `gfxName` | string | `pa_setGfxName` | `"?"` |
| +0x3c | `blocked` | bool | `pa_setBlocked` | false |
| +0x3d | `forMining` | bool | `pa_setForMining` | false |
| +0x3e | `forBuilding` | bool | `pa_setForBuilding` | false |
| +0x3f | `forShip` | bool | `pa_setForShip` | false |
| +0x40 | `miniMapColor` | 4 bytes r, g, b, 255 | `pa_setMiniMapColor(p, r, g, b)` | 100, 255, 60, 255 |
| +0x44 | `treeType` | i32 tag | `pa_setTreeType` | -1 |
| +0x48 | `forPlanting` | bool | `pa_setForPlanting` | false |

`patterns.lua` sets the flags through Lua helper functions, one per terrain class [known: data]:

| Helper | blocked | forBuilding | forPlanting | forMining | default tag | default colour |
|---|---|---|---|---|---|---|
| `setMeadow` | no | yes | yes | no | Bavaria | 100, 255, 60 |
| `setEarth`, `setStoneground` | no | yes | no | no | Bavaria | 100, 255, 60 |
| `setSand` | no | no | no | no | Desert | 210, 200, 150 |
| `setRock` | no | no | no | yes | Bavaria | 190, 190, 190 |
| `setSnow` | yes | no | no | no | Bavaria | 255, 255, 255 |
| `setSwamp` | yes | no | no | no | Bavaria | 140, 220, 200 |
| `setLava` | yes | no | no | no | Lava | 255, 90, 20 |
| `setSeaground` | no | no | no | no | None | 100, 255, 60 |
| `setShip` | no | no | no | no (+ `forShip`) | Bavaria | 100, 255, 60 |

A helper call may override tag and colour per pattern; when a table of tags is passed only its first element is
used (the script says `TODO: add additional treetypes`) [known: data].

**`DoodadProperty`** (0x4c, stored inline), `dd_*`, ctor S 00555970 [known]:

| Offset | Field | Type | Lua key | Default |
|---|---|---|---|---|
| +0x00 | `id` | i32 | `dd_create` | -1 |
| +0x04 / +0x20 | `name` / `gfxName` | string | `dd_setName` / `dd_setGfxName` | `"unknown"` |
| +0x3c | `lifeTime` | i32, ticks | `dd_setLifeTime` | -1 (permanent); signs 3000, empty sign 30000 |
| +0x40 | `onWater` | bool | `dd_setOnWater` | false; never set by the shipped scripts |
| +0x41 | `deleteByStreet` | bool | `dd_setDeleteByStreet` | true; false on signs |
| +0x44 | `type` | i32 | `dd_setType` | 0 `doodad_Type_Landscape`; 1 `doodad_Type_Sign` |
| +0x48 | `blocking` | bool | `dd_setBlocking` | false |
| +0x49 | `indestructible` | bool | `dd_setIndestructable(d)` | false; the binding always writes 1 and ignores further arguments (S 005501f0); only `doodad_anchor` |

**`RemainsProperty`** (0x44, inline), `rm_*`, ctor S 005558a0 [known]: `+0x04 name`, `+0x20 gfxName`
(`RuinSmall01`, `RuinMedium01`, `RuinLarge01`), `+0x3c burningTime` i32 ticks (default 500; data 50 for all
three), `+0x40 doodadAfterFinished` doodad id (default -1; the calls are commented out in the data). Readers
`NVillage::Remains::ctor` / `ctor_ForLoad`.

**`AnimalProperty`** (0x68), `an_*`, ctor S 00555190 [known]:

| Offset | Field | Type | Lua key | Default | Example |
|---|---|---|---|---|---|
| +0x04 / +0x20 | `name` / `gfxName` | string | `an_setName` / `an_setGfxName` | `"unknown"` | `"Deer"` |
| +0x3c | `range` | i32, cells | `an_setRange` | -1 | deer 6, rabbit 8 |
| +0x40 | `moveDistance` | i32, cells | `an_setMoveDistance` | 3 | deer 2, rabbit 4 |
| +0x44 | `movementSpeed` | float, cells per tick | `an_setMovementSpeed` | 0.1 | deer 0.045, sheep 0.03 |
| +0x48 | `avoidBuildings` | bool | `an_setAvoidBuildings` | true | |
| +0x4c | `idleTimeFactor` | float | `an_setIdleTimeFactor` | 3.0 | stored as `max(value, 2.0)` (S 00554f20); never set in the data |
| +0x50 | `stackGoods` | map tribe → vector&lt;good id&gt; | `an_addStackGood(a, tribe, good)` | empty | what a hunter of that tribe gets: bavarians leather and egyptians goatHam from every animal except sheep (script helper `addBaseStack`), scots `sheep` from `animal_sheep` only. Readers S 00554f50, S 00554fe0, S 00555070 |
| +0x5c | `respawn` | bool | `an_setRespawn` | true | false for sheep |
| +0x60 | `dyingTime` | i32, ticks | `an_setDyingTime` | 55 | sheep 1 |
| +0x64 | `disappearingTime` | i32, ticks | `an_setDisappearingTime` | 20 | sheep 5 |

**`SpRecord`** (spawn point type, 0x74), `sp_*`, ctor S 00557530 [known]:

| Offset | Field | Type | Lua key | Default |
|---|---|---|---|---|
| +0x04 / +0x20 / +0x3c | `name` / `gfxName` / `particleName` | string | `sp_setName` / `sp_setGfxName` / `sp_setParticleName` | `"unknown"`, `"unknown"`, empty |
| +0x58 | `uniqueIds` | vector&lt;i32&gt; | `sp_addUniqueId` | empty. Type 1: the animal types this point may spawn. Type 0: `NLogic::SpawnResource::Spawn` S 005390e0 uses only the **first** entry, as the resource type it adds (1 unit per cell) with `MapModifier::AddResourceAtCell` on every in-map cell within `range` hex rings; an empty list is a fatal checked access [known]. Rules of the cell update: [map-resources.md](map-resources.md) |
| +0x68 | `range` | i32 | `sp_setRange` | 3; never set in the data. Radius in hex rings of a type-0 spawn (S 005390e0) [known] |
| +0x6c | `type` | i32 | `sp_setType` | -1; `SpawnType_Resource` 0, `SpawnType_Animal` 1. `LogicSpawn_CreateFromProperty` creates `NLogic::SpawnResource` for 0, `NLogic::SpawnAnimal` for 1, nothing otherwise |
| +0x70 | `rate` | i32 | `sp_setRate` | 1; never set in the data ([logic-core.md](logic-core.md) §6) |

All twelve shipped spawn point types are of type 1 [known: data].

### 2.7 `SacrificeProperty` (0xa4), `sf_*`

Ctor S 005567e0 [known]. The rules of ordering, research and running a sacrifice belong to the sacrifice
subsystem (`ai::village::VillageSacrifice`, `ai::logic::Sacrifice`, `ai::logic::SacrificeModifiers`); the part
that interprets the record's effect list is given in §3.9 because no other document covers it yet.

| Offset | Field | Type | Lua key | Default | Meaning |
|---|---|---|---|---|---|
| +0x00 | `id` | i32 | `sf_create` | -1 | |
| +0x04 | `name` | string | `sf_setName` | `"unknown"` | text key stem, e.g. `"carrierSpeed"`; shared by tribe variants |
| +0x20 | `gfxName` | string | `sf_setGfxName` | `"unknown"` | `"carrierSpeedGfx"` on all 77 records |
| +0x3c | `buffGfxName` | string | `sf_setBuffGfxName` | `"unknown"` | `"heal"`, `"explore"`, `"darkCloudsShip"` (13 records) |
| +0x58 | `duration` | i32, ticks | `sf_setDuration` | 1 | data values 20, 3000, 4200, 6000, 9000, 20000000, 200000000: 6000 / 9000 for most buffs, 20 for good exchanges, 200000000 for the campaign markers |
| +0x5c | `costs` | vector&lt;{good, amount}&gt; | `sf_addCost` | empty | goods to deliver to the temple; side effect §3.2 |
| +0x6c | `effects` | vector&lt;SacrificeEffect&gt; | `sf_addEffect` | empty | §3.9 |
| +0x7c | `target` | i32 | `sf_setTarget` | not initialised by the ctor | 0 `Target_Owner`, 1 `Target_Enemies`. Every shipped record sets it (36 + 10 direct calls, 31 through the exchange helper) [known: S 005567e0 has no store to +0x7c; data] |
| +0x80 | `abortable` | bool | `sf_setAbortable` | true | |
| +0x84 | `category` | i32 | `sf_setCategory` | 0 | AI trigger class, below |
| +0x88 | vector&lt;i32&gt; | | (`sf_addBuildingDependence`) | empty | never filled: the binding S 0054f7e0 reads its arguments and calls an empty function, so building dependences are discarded in this build [known] |
| +0x98 | `researchDuration` | i32, ticks | `sf_setResearchDuration` | 0 | 0 = no research needed; e.g. 9000 |
| +0x9c | `regenerationDelay` | i32, ticks | `sf_setRegenerationDelay` | 1 | cool-down in ticks counted from the **end** of a sacrifice (`RemoveSacrifice` S 006620a0 stores the tick, `SacrificeRegenerations_Add` S 00662860): while `(u32)(tick − end) < (u32)delay` the owner can neither order (`CheckCanOrder` S 00561240, code 7) nor start (`CheckCanStart` S 00560f20) that definition at any building; expired entries go each tick (S 00662720) [known]; data 100..10800, and 20000000 / 200000000 on campaign records |
| +0xa0 | `forCampaign` | bool | `sf_setForCampaign` | false | 3 records |

`SacrificeEffect` (16 bytes) = `{ i32 type; i32 arg1; i32 arg2; i32 threshold }` filled by
`sf_addEffect(id, type, arg1, arg2, value)`; the fifth Lua argument is read as a float and truncated to an
integer (S 0054f670) [known].

**`category`** (`sacrifices.lua`) [known: data, with its comments]: 0 `SacrificeCategory_Economic`; 1
`SacrificeCategory_Military` ("AI checks for enemy near"); 2 `SacrificeCategory_Navy` ("AI checks for active
ships"); 3 `SacrificeCategory_Fight` ("AI checks for active fights to start and enemy near for ordering"); 4
`SacrificeCategory_Exchange` ("AI checks for exchange").

**Effect types** (`sacrifices.lua`) [known: data]: 0 `NoEffect`, 1 `CarrierSpeed`, 2 `SoldierArmor`, 3
`SoldierDamage`, 4 `ProductionSpeed`, 5 `ArcherAttackSpeed`, 6 `ArcherHitChance`, 7 `MinerNeedNoFood`, 8
`SoldierSpeed`, 9 `ShipSpeed`, 10 `PeaceTime`, 11 `BuildingArmor`, 12 `CornDoubleProduction`, 13 `WorkerPause`,
14 `ExpandTerritory`, 1000 `FunctionSpawnSoldier`, 1001 `FunctionGoodExchange`, 1003 `FunctionSoldierHeal`, 1004
`FunctionExploreEnemy`, 1005 `FunctionExploreHarbors`, 1006 `FunctionRunScript`, 1007 `FunctionExploreMap`, 1008
`FunctionDestroyShips`. Types 1000, 1005, 1006 and 1007 are not used by any shipped record.

### 2.8 `AiProperty` (0xd0), `ai_*`

Ctor S 00555e80 [known]. One record per computer-player profile: `ai_weak` id 1, `ai_normal` id 2, `ai_strong`
id 3, and three campaign profiles (`ai_c2_catapult`, `ai_c5_pirates`, `ai_c6_severin`). `NAI::Player::Activate`
S 00582870 and `NAI::Player::Load` fetch the record by a profile key through the unchecked getter [known]. The
key reaches `Activate` from `NAI::System::ActivatePlayer` S 00581c40, which has two callers [known]:
`Game_CreatePlayersFromDescriptor` S 005abb60 passes 1, 2 or 3 for a computer slot (computer level 0 / 1 / 2,
[players-victory.md](players-victory.md) §3.4), and the map-script function `logic.ai_enable(player, profile)`
S 005b2660 passes its second argument as given, which is how campaign maps select the other three profiles. The
AI rules that read the fields are in [ai-player.md](ai-player.md).

| Offset | Field | Type | Lua key | Default |
|---|---|---|---|---|
| +0x04 | `name` | string | `ai_setName` | `"unknown"` |
| +0x20 | `militaryMode` | i32 | `ai_setMilitaryMode` | 1; 0 `AI_MilitaryMode_Safe`, 1 `Normal`, 2 `Aggressive` |
| +0x24 | `maximumSmithies` | i32 | `ai_setMaximumSmithies` | 100 |
| +0x28 | `maximumMints` | i32 | `ai_setMaximumMints` | 100 |
| +0x2c | `streetOptimizing` | bool | `ai_enableStreetOptimizing` | true |
| +0x2d | `routeOptimizing` | bool | `ai_enableRouteOptimizing` | true |
| +0x2e | `catapults` | bool | `ai_enableCatapults` | true |
| +0x2f | `coinArrangement` | bool | `ai_enableCoinArrangement` | true |
| +0x30 | `startFrameProducerCount` | i32 | `ai_setStartFrameProducerCount` | 1 |
| +0x34 | `factors[2][2]` | float | `ai_setFactor(ai, battleMode, valueOf, v)` → `[battleMode*2 + valueOf]` | 0; `AI_BattleMode_Attack` 0 / `Defense` 1; `AI_BattleValueOf_Own` 0 / `Enemy` 1; reader S 00555d10 |
| +0x48 | `battleCalcRatio[3]` | float | `ai_setBattleCalcRatio(ai, a, b, c)` | 0.5, 0.3, 0.2; never set in the data |
| +0x54 | `retreatChance` | i32, percent | `ai_setRetreatChance` | 50 |
| +0x58 | `destroyLostBuildingChance` | i32, percent | `ai_setDestroyLostBuildingChance` | 50 |
| +0x5c | `swordBowRatio` | float | `ai_setSwordBowRatio` | 0.5; never set in the data |
| +0x60 | `sacrificesStartTime` | float | `ai_setSacrificesStartTime` | FLT_MAX (= never) |
| +0x64 | `sacrificesLimit` | i32 | `ai_setSacrificesLimit` | 1 |
| +0x68, +0x78 | `favoriteSacrificeIds`, `favoriteSacrificeWeights` | parallel vector&lt;i32&gt; | `ai_addFavoritSacrifice(ai, sacrifice, weight)` | empty; `GetFavoriteSacrificeWeight` S 00555d60 returns the weight or 0 |
| +0x88 | `waterStreets` | bool | `ai_enableWaterStreets` | true |
| +0x8c | `specialAttackMinFactor` | float | `ai_setSpecialAttackMinFactor` | 0.1 |
| +0x90 | `specialAttackRandomValue` | i32 | `ai_setSpecialAttackRandomValue` | 90 |
| +0x94 | `specialAttackBestChance` | float | `ai_setSpecialAttackBestChance` | 0.1 |
| +0x98 | `specialDefenseFactor` | float | `ai_setSpecialDefenseFactor` | 0.1 |
| +0x9c | `specialDefenseRandomValue` | i32 | `ai_setSpecialDefenseRandomValue` | 50 |
| +0xa0 | `constructCatapultRating` | float | `ai_setConstructCatapultRating` | 600.0 |
| +0xa4 | `catapultEnemyThreatFactor` | float | `ai_setCatapultEnemyThreatFactor` | 2.0 |
| +0xa8 | `catapultFriendThreatFactor` | float | `ai_setCatapultFriendThreatFactor` | 2.0 |
| +0xac | `catapultAttackFailedFactor` | float | `ai_setCatapultAttackFailedFactor` | 10.0 |
| +0xb0 | `buildCatapultDecreaseFactor` | float | `ai_setBuildCatapultDecreaseFactor` | 1.0 |
| +0xb4 | `catapultConstructionTime` | i32, ticks | `ai_setCatapultConstructionTime` | 3000 |
| +0xb8 | `allocation` | bool | `ai_enableAllocation` | true |
| +0xbc, +0xc0 | `attackLimiterDelay`, `…DelayRandom` | i32, ticks | `ai_setAttackLimiterDelay`, `…DelayRandom` | 0, 0 (data 1200..3600 and 1200 / 3000) |
| +0xc4, +0xc8 | `attackLimiterAttackCount`, `…CountRandom` | i32 | `ai_setAttackLimiterAttackCount`, `…CountRandom` | 0, 0 (data 1..3 and 1..3) |
| +0xcc | `constructionTicker` | i32 | `ai_setConstructionTicker` | 1 |

The five `ai_setSpecial*` keys are registered but never called by the shipped scripts [known: data].

### 2.9 Harbours and sounds

**`HarbourProperty`** (0x9c), `hp_*`, ctor S 00554900 [known]. Eight records, one per facing: `harbor_sw`,
`_nw`, `_se`, `_ne`, `_n`, `_s`, `_e`, `_w`. A harbour on a map is stored with one of these ids; the id **is**
its orientation ([../map-format.md](../map-format.md)).

| Offset | Field | Type | Lua key |
|---|---|---|---|
| +0x04 | `name` | string | `hp_setName` (`"south west"`) |
| +0x20 | `waterStreetPosition[4]` | {float x, float y} | `hp_setWaterStreetPosition(h, index, x, y)`; no bounds check; `x`, `y` are read with `Lua_ToInt` and converted to float (S 0054b120, S 0054b1a0), so both position tables hold whole numbers [known] |
| +0x40 | `shipPosition[4][2]` | {float x, float y} | `hp_setShipPosition(h, row, col, x, y)` → `[row*2 + col]` |
| +0x80 | `gfxName` | string | `hp_setGfxName` (`"dummy"`) |

All positions default to (0, 0). The values are cell offsets from the harbour cell, e.g. `harbor_sw`: water
street 0 at (-2, -3), ships (-3, -3) and (-3, -4). The data fills 2 or 3 of the 4 indices per harbour (17 water
street positions, 34 ship positions over 8 records). Readers: `GameQuery::IsHarborOrientationValid`,
`ai::navy::Harbor::ctor` ([../navy-and-military.md](../navy-and-military.md)).

**`SoundProperty`** (0x5c, inline), `sn_*`, ctor S 00555a80. Presentation only; not part of the simulation.

| Offset | Field | Type | Lua key | Default |
|---|---|---|---|---|
| +0x04 | `name` | string | `sn_setName` | `"unknown"`; lookup `FindSoundIdByName` S 00545f70 |
| +0x20 | `fileNames` | vector&lt;string&gt; | `sn_addFileName` | empty; several = variants |
| +0x30 | `looping` | bool | `sn_setLooping` | false |
| +0x34 | `type` | i32 | `sn_setType` | 3; 0 `SoundType_Ambient`, 1 `Music`, 2 `GUI`, 3 `Sound`. The setter S 00555a10 also sets `is3D` (+0x48) to false when the type is 1 or 2 (music, GUI) [known]; a later `sn_set3DSound` overrides that |
| +0x38 | `volume` | i32 | `sn_setVolume` | 255 |
| +0x3c | `priority` | i32 | `sn_setPriority` | 0 |
| +0x40 | `minDistance3D` | float | `sn_set3DMinDistance` | 1.0; the setter S 00555a40 also stores `(v * 30)²` at +0x58 [known]. The ctor sets +0x58 to 1.0, not to the value the setter would give for 1.0 |
| +0x44 | `maxDistance3D` | float | `sn_set3DMaxDistance` | 1e9 |
| +0x48 | `is3D` | bool | `sn_set3DSound` | true |
| +0x4c | `distance2D` | float | `sn_set2DDistance` | 10.0 |
| +0x50 | `musicTribe` | tribe id | `sn_setMusicTribe` | -1 |
| +0x54 | `percussion` | bool | `sn_setPercussion` | false |

[known] for offsets and defaults (ctor plate and setters); the Ghidra struct labels `+0x30` differently
(`playAtHighSpeed`); the setter named `sn_setLooping` writes that byte [known: S 00550bc0].

### 2.10 Singleton blocks

**`GameConfig`** (0x60, `PropertiesDb+0x24`), `cfg_*`, ctor S 00555780 [known]:

| Offset | Field | Type | Lua key | Code default | `config.lua` | Reader |
|---|---|---|---|---|---|---|
| +0x00 | `settlerSpeed` | float, cells per tick | `cfg_setSettlerSpeed` | 0.1 | 0.058 | [settlers-jobs.md](settlers-jobs.md); scaled by sacrifice factors in S 00663310 |
| +0x04 | `gameSpeed` | float, seconds per tick | `cfg_setGameSpeed` | 0.1 | not set | [logic-core.md](logic-core.md) §3.1 |
| +0x08 | `borderPattern` | pattern id | `cfg_setBorderPattern` | -1 | not in `config.lua`; `patterns.lua` sets it to `pattern_border` (`76d31873`) | [map-resources.md](map-resources.md) |
| +0x0c | `pickupTime` | float, ticks | `cfg_setPickupTime` | 10 | 3.3 | carriers |
| +0x10 | `dropTime` | float, ticks | `cfg_setDropTime` | 10 | 3.3 | carriers |
| +0x14 | `bulldozeTime` | float, ticks | `cfg_setBulldozeTime` | 10 | 55 | not read [known]: none of the 593 functions that reach the property database (`StaticAccess::EnsureInstance` S 0054a140, the only reader of its global) accesses `gameConfig +0x14`, and no function takes `GameConfig*` besides its setters; ground levelling is instantaneous ([village-buildings.md](village-buildings.md) §3.3) |
| +0x18 | `constructTime` | float, ticks | `cfg_setConstructTime` | 10 | 30 | builder hammer stroke |
| +0x1c | `fishingDistance` | i32, cells | `cfg_setFishingDistance` | 3 | 1 | fisher |
| +0x20 | `flagPackageLimit` | i32 | `cfg_setFlagPackageLimit` | 6 | 2 | capacity of each stack of a flag ([streets-transport.md](streets-transport.md)) |
| +0x24 | `catapultRotationTimeFactor` | float | `cfg_setCatapultRotationTimeFactor` | 10 | 5 | ticks per catapult turn step |
| +0x28 | `catapultFlightTimeFactor` | float | `cfg_setCatapultFlightTimeFactor` | 10 | 5 | ticks per cell of stone flight |
| +0x2c | `settlerDyingTime` | float, ticks | `cfg_setSettlerDyingTime` | 50 | 28 | death animation |
| +0x30 | (no setter) | i32 | – | 30 | – | home search radius ([settlers-jobs.md](settlers-jobs.md) §6) |
| +0x34 | `settlerSkeletonDoodad` | doodad id | `cfg_setSettlerSkeletonDoodad` | -1 | `doodad_deadsettler` | |
| +0x38 | `bowFlightTimeFactor` | float | `cfg_setBowFlightTimeFactor` | 1.0 | 2 | ticks per cell of arrow flight |
| +0x3c | flag byte | | – | 0 | set by the library registration | no reader found (§2.1) |
| +0x40 | `maxWaterStreetWaterDepth` | i32 | `cfg_setMaxWaterStreetWaterDepth` | 100 | 4000 | water streets |
| +0x44 | `chestDoodadId` | doodad id | `cfg_setChestDoodadId` | -1 | `doodad_chest` | |
| +0x48 | `openChestDoodadId` | doodad id | `cfg_setOpenChestDoodadId` | -1 | `doodad_openChest` | |
| +0x4c | (no setter) | i32 | – | 4 | – | written only by the ctor S 00555780 (S 005557e4), never read [known]: none of the 593 functions that reach the property database accesses `gameConfig +0x4c`, and no `GameConfig` method does. A remake can drop it |
| +0x50 | `spawnPointUpdateTime` | i32, ticks | `cfg_setSpawnPointUpdateTime` | 600 | 1200 | [logic-core.md](logic-core.md) §6 |
| +0x54 | `sacrificeGoodId` | good id | `cfg_setSacrificeGoodId` | -1 | `sacrificeGood` | only reader: the binding `sf_addCost` S 0054f520 (§3.2) [inferred from a search of the function cache] |
| +0x58 | (no setter) | u32, ticks | – | 600 | – | idle-outside delay ([settlers-jobs.md](settlers-jobs.md) §6) |
| +0x5c | `chestOwningTime` | i32, ticks | `cfg_setChestOwningTime` | 3000 | not set | [logic-core.md](logic-core.md) §6 |

`config.lua` also defines script-only constants: the size bits (§3.6) and the time names `ExtremlyShortTime` 50,
`VeryShortTime` 100, `ShortTime` 150, `MediumTime` 200, `LongTime` 250, `VeryLongTime` 300, `ExtremlyLongTime`
400 [known: data].

**`MilitaryConfig`** (0x120, `PropertiesDb+0x5c`), `mi_*`, ctor S 00554380 [known]; use in
[military.md](military.md) §2.2:

| Offset | Content | Lua key | Default | `military.lua` |
|---|---|---|---|---|
| +0x00 | `soldierId[kind 0..1][level 0..4]`: map tribe → good id (map at `+kind*0x3c + level*0xc`) | `mi_setSoldierId(tribe, kind, level, good)` | empty | 15 calls |
| +0x78 | `health[kind][level]`: map tribe → i32 | derived (§3.3) | empty | |
| +0xf0 | `maxLevel[kind]`: map tribe → i32 | derived (§3.3) | empty | |
| +0x108 | i32 | – | 20 | no setter; not read [known]: written only by the ctor (S 005543fa); no `MilitaryConfig` method and none of the 593 functions that reach the property database accesses `+0x108` |
| +0x10c | flag byte | – | false | set by the library registration |
| +0x110 | `regenerationRate` | `mi_setRegenerationRate` | not initialised by the ctor | 100; three readers [known]: `NVillage::Hitpoints::Update` S 0055b910 (building hit point regeneration), `NVillage::SettlerSpawn::Update` S 00564780, `NSettlers::Livepoints::UpdateRegeneration` S 0065dbc0 (soldier in a building); rules in [village-buildings.md](village-buildings.md) and [military.md](military.md) |
| +0x114 | `waitForTacticTime` | `mi_setWaitForTacticTime` | 100 | 10 |
| +0x118 | `actionsInFightDelayTime` | `mi_setActionsInFightDelayTime` | 300 | 300 |
| +0x11c | `healthExchangeDistance` | `mi_setHealthExchangeDistance` | 200 | 200 |

`military.lua` also defines `tactic_aggressive` 0, `tactic_normal` 1, `tactic_defensive` 2 (no binding call uses
them) [known: data]. Two functions on the block are constants, not data: `GetDefaultDistanceAllocationFactor`
S 00553f40 (tier 0 far 0.1, 1 medium 0.3, 2 near 1.0, else 0) and `ComputeRatioBonus` S 00553f70
(`max((ratio - 1) * 0.2, 0)`) [known].

**`ShipConfig`** (0x30, `PropertiesDb+0x68`), `sh_*`, ctor S 005556c0 [known]; use in
[../navy-and-military.md](../navy-and-military.md):

| Offset | Field | Type | Lua key | Default | `ship.lua` |
|---|---|---|---|---|---|
| +0x00 | flag byte | | – | 0 | set by the library registration |
| +0x04 | `speed` | map tribe → float: hex cells per simulation tick, times the owner's sacrifice ship-speed factor (`SacrificeModifiers::GetShipSpeed` S 006632d0); the step rate is 1 ÷ (hex distance ÷ speed) (`BeginStep` S 007728d0), advanced once per tick; the key is the owner's tribe (player +0x44), a missing key is fatal (`GetSpeed` S 005554d0) [known] | `sh_setSpeed(tribe, v)` | empty | bavarians 0.06, egyptians 0.09, scots 0.12 |
| +0x10 | `size` | i32 | `sh_setSize` | 1 | 1 |
| +0x14 | `constructTime` | float | `sh_setConstructTime` | 50.0 | 30 |
| +0x18 | `stockLimit` | i32 | `sh_setStockLimit` | 12 | 12 |
| +0x1c | `waitTime` | i32, ticks | `sh_setWaitTime` | 40 | 15 |
| +0x20 | `sinkingTime` | i32, ticks | `sh_setSinkingTime` | 30 | 47 |
| +0x24 | `expeditionBuilding` | map tribe → building id | `sh_setExpeditionBuilding(tribe, b)` | empty | `guardHouseBav`, `guardHouseClay`, `guardHouse` |

`GetSpeed` S 005554d0 and `GetExpeditionBuilding` S 00555510 require the tribe key to exist [known].

**Sign table** (`PropertiesDb+0x4c`), `si_addSignDoodadId(good, threshold, doodad)` S 0054cc80 → S 005574f0
[known]: per good a vector of {threshold, doodad id} kept **sorted by threshold** (sorted insert). Shipped
entries: good -1 → `doodad_emptySign` (threshold 0); `water` → one sign (1); coal, ironOre, gold, stone,
gemstones, salt → four signs each at thresholds 1, 3, 6, 1000 (S, M, L, X).

---

## 3. Rules and algorithms

### 3.1 Creation and lookup

1. `X_create(hexString)`: parse the id (§2.2); allocate a record with the ctor defaults of §2; store it as
   `map[id]`; return the id [known].
2. For the pointer tables a second `X_create` with the same id allocates a new record and overwrites the map
   slot; the old record is neither freed nor reachable, and everything set on it is lost (S 005498d0 and the nine
   siblings) [known]. For the inline doodad table a second `dd_create` with the same id finds the existing record
   through `operator[]`, rewrites only its id and keeps every other value (S 0054fe10) [known]; the same holds
   for `rm_create` S 0054fa80 and `sn_create` S 00550880, which also subscript the inline map and copy the id
   [known].
3. Every `X_set…` / `X_add…` binding looks the record up with `std::map::operator[]` (S 00549040) and writes
   through the result **without a check**. For a pointer table an id that was never created inserts `{id,
   NULL}` and the write faults at address `0 + offset`: an access violation, not a Lua error [known]. For the
   inline tables `operator[]` creates a default record instead [known: the three subscript functions S 0054a1f0,
   S 0054a300, S 00550760 are the only callers of the remains, doodad and sound ctors].
4. Argument conversion [known: binder bodies]: integers through `Lua_ToInt` S 005c9b30 (`lua_tonumber`, then
   the truncating double-to-integer conversion `__ftol2_sse`), floats through `Lua_ToFloat` S 005c9b10
   (`(float)lua_tonumber`), booleans through `Lua_ToBool` S 005c9b50 (`lua_toboolean != 0`, so only `false` and
   `nil` are false and the number 0 counts as true), except `bp_setSpawn`, `bp_setDepot`, `gp_enableDeposits`
   and `gp_enableFields`, which read an integer and store `value != 0` (the scripts pass 1).
   `bp_setWorkingRadius` reads a float and truncates it. The position bindings (`bp_setConstructionPosition`,
   `bp_setIdlePosition`, `hp_setWaterStreetPosition`, `hp_setShipPosition`) read their coordinates as integers
   and store them as floats.
5. Bindings without a value argument: `gp_setAINoNeedForCosts(good)`, `bp_setNoProductivity(building)`,
   `dd_setIndestructable(doodad)` [known].
6. Lookup at run time is by id only (`Get<Type>Property`); an unknown id is fatal (§2.2).

### 3.2 List semantics

- `GoodAmountList_AddAmount` S 00552aa0 (used by `gp_addCost`, `tp_addStartResources`, `tp_addBonusResources`)
  [known]: scan the list in order; if an entry with the same good id exists (and that id is not -1) add the
  amount to it; otherwise append. So a good appears at most once and the list keeps first-appearance order;
  entries with good id -1 never merge, each call appends another one.
- `bp_addCost` / `bp_addFrameCost` go through `ai::properties::BuildingProperty::AddCostAt` S 00552e90 (slot 1 /
  slot 0), which calls the same `GoodAmountList_AddAmount` on the list at `+0x58 + slot*0x10`, so building costs
  merge in the same way [known].
- `tp_addGood`, `tp_addJob`, `tp_addBuilding`, `tp_addAllowedSacrifice`, `dp_addTreeType`,
  `dp_addUndergroundPattern`, `gp_addHitTime`, `sp_addUniqueId`, `sf_addEffect`, `ai_addFavoritSacrifice`: plain
  append, duplicates kept [known].
- **`sf_addCost(sacrifice, good, n)`** S 0054f520 does three things [known]:
  1. adds `{good, n}` to the sacrifice's `costs` with `GoodAmountList_AddAmount` (S 005564c0 forwards to it), so
     a good named twice for one sacrifice merges;
  2. adds `{good, 1}` with `AddAmount` to the `costs` of the good named by `GameConfig.sacrificeGoodId`. The
     amount of an entry in that list therefore counts the `sf_addCost` calls that named the good; it is not 1;
  3. reads the cost good's `arrangementGoodId` and, when it differs from the cost good's own id, adds
     `{arrangementGoodId, 1}` to the same list. A good that never called `gp_setArrangementGoodId` holds its
     own id there (§2.4), so nothing is added for it and no `{-1, 1}` entry can arise; for the 20 goods the
     data gives a different arrangement good (food goods and food sub-groups → `foodScots` / `foodBav` /
     `food`, and `sacrificeGoodOlympicFlame` → `sacrificeGood`) the arrangement good is added as a further
     entry.
  The good `sacrificeGood` (a temple's product, type `WareGroup`) thereby becomes the group of every good any
  sacrifice can cost, plus the food groups (type `EitherGroup`) of the food goods among them. Readers of that
  list: the group-member walk of §3.4, which asks the list for the amount of each tribe good, and
  `CostsContainGood` through `BuildingProperty::ConsumesGood` for the temples (§3.4), where the first food-group
  entry ends the walk of the list [known: S 00554a60]. `GameConfig.sacrificeGoodId` itself has no other reader
  (§2.10). Consequence: `cfg_setSacrificeGoodId` must run before the first `sf_addCost` (`config.lua` is loaded
  before `sacrifices.lua`), and the cost goods must exist by then (the binding looks each one up with the
  unchecked getter).

### 3.3 Soldier tables: `mi_setSoldierId(tribe, kind, level, good)`

`MilitaryConfig::SetSoldierId` S 00554290 [known]:

1. `soldierId[kind][level][tribe] = good`.
2. `health[kind][level][tribe] = GoodProperty(good).health`, read **at that moment**. `Jobs.lua` must therefore
   have set `gp_setHealth` before `military.lua` runs (it does: `jobs` is loaded before `military`). A later
   `gp_setHealth` (for example by a mod script) does not update the cached value.
3. `maxLevel[kind][tribe]` is inserted as `level` if the tribe has no entry, else raised to `level` if larger.

`kind` is 0 sword / 1 bow, `level` 0..4 (five map slots per kind; no bounds check in the binding). Shipped
levels: bavarians sword 0..2 and bow 0..2; egyptians sword 0 only and bow 0..2; scots sword 0..2 and bow 0..1.

Queries [known]: `GetSoldierId(tribe, kind, level)` S 00554090 (key must exist); `FindSoldierLevel(tribe, good)`
S 00553fb0 → level 0..4 over both kinds or -1; `GetMaxSoldierLevel(tribe, kind)` S 005540e0 (tribe key must
exist); `GetSoldierGoodList` S 00554750 → per-tribe list of the soldier goods of one kind, levels 0..max, built
lazily once per process and never rebuilt: two static per-tribe maps guarded by two bits of one static flag
word, one for kind 0 and one for every non-zero kind; the second is built with the kind of the first non-zero
call and then serves all non-zero kinds [known]. With only kinds 0 and 1 this is harmless, but a list reflects
`MilitaryConfig` as it was at the first query.

### 3.4 Goods: groups, recipes, membership

- **Recipe of a building** = `costs` of the good in product slot 0 ([village-buildings.md](village-buildings.md)
  §3.7). `BuildingProperty::ProducesGood(good)` S 00552fa0: either slot equals the good. `ConsumesGood(good)`
  S 00553080: for each non-empty slot, `CostsContainGood(good, expandGroup = true)` on the slot's good [known].
- **`CostsContainGood(good, expandGroup)`** S 00554a60 [known], exactly:
  1. walk `costs` in order; return true on the first entry whose id equals `good`;
  2. if `expandGroup` and an entry's good has `type == 3` (EitherGroup): stop walking this list, continue with
     that group's `costs` with `expandGroup = false` (one level only), and return its result. Entries after the
     group in the original list are **not** examined.
- **Members of a group for a tribe**: `PropertyGroupIter::Init` S 007767c0 / `ai::properties::PropertyGroupIter::Next` S 00776690 walks
  `TribeProperty.goods` in order and yields each good that has a positive amount in the group good's `costs`
  [known]. The group's own list order does not matter; the tribe's `tp_addGood` order does. Used by production
  (`StartProductionCycle`, `RequestAllInputs`) and the AI cells.
- **Settler creation cost**: `Stock::CanAffordGoodCost(good)` S 00539b90 = `costs` empty or fully in stock;
  `Stock::ExchangeCostForGood(good)` S 0053a400 removes the `costs` list and adds one unit of `good` [known].
  A promotion is the same operation on the next rank's good (previous rank + coin).
- **Second carrier**: `TribeProperty::SecondCarrierCostsContainGood(good)` S 00556020 = the tribe has a second
  carrier and `good` has a positive amount in that settler good's `costs`;
  `GetSecondCarrierFirstCostGoodId` S 00556060 = the first cost entry's good or -1 [known]. Bavarians:
  `good_oxen` costs `oxen` 1; egyptians: `good_helper` has no costs; scots: no second carrier.
- **Type 1 goods are settlers** (`Settler = 1` in `Goods.lua`). Code that skips or counts `type == 1` (good
  priorities, the "population" statistic in [players-victory.md](players-victory.md)) is selecting settler
  goods, not `WareGroup` [known: data constant].

### 3.5 Producer and consumer queries

- `PropertiesDb::FindBuildingProducingGood(good)` S 00546070: the id of the **first building in table order**
  (ascending signed id) with `ProducesGood(good)`, else -1; tribe-blind [known].
- `Economy_CollectProducerBuildings(tribe, good)` S 00534d00 [known: plate and code]: if the good's `type == 3`,
  recurse over each member in `costs` and concatenate the results; otherwise walk `TribeProperty.buildings` in
  order and accept a building if `ProducesGood(good)`, or, when the good is a settler good with `settlerType ==
  3` (soldier), if the building is a `casern` that is not both `depot` and `territoryBuilding` (i.e. a barracks,
  not the headquarters).
- `Economy_CollectConsumerBuildings(tribe, good)` S 00534f40: buildings of the tribe with `ConsumesGood(good)`
  that are constructible (`constructionTime > 0`) or are the headquarters (`depot && casern &&
  territoryBuilding`) [known].
- **Headquarters type**: `Properties_FindFirstBuildingWithFlags54F1F5` S 00533bb0 returns the first building in
  table order with `depot`, `casern` and `territoryBuilding` all set, else -1; `Game_CreatePlayersFromDescriptor`
  S 005abb60 uses it as the start building of every player [known]. Only `castle` qualifies in the data, and all
  three tribes list `castle` in `tp_addBuilding`.

### 3.6 Building size mask

`config.lua` [known: data]: `SizeInvalid` 0, `SizeLarge` 4, `SizeMedium` 6, `SizeSmall` 7, `SizeMine` 8,
`SizeShip` 16, `SizeMilitary` 64 (added to a size: `SizeSmall + SizeMilitary`).

`Building_TypeFitsConstructionFlags(cellFlags, type)` S 0052e510 (caller: the build menu,
`nMenu::InfoBoxCreateBuilding::RebuildBuildingButtons`) and `GameQuery_BuildingTypeFitsCellFlags(type, cell,
player)` S 0052eab0 (callers: `Village_CheckBuildingPlacement`, `NAI::BuildingConstruction::Update`,
`NAI::SearchConstructionPlace::EvaluateCell`; it takes `cellFlags` from `ConstructionMap::GetCellFlags(cell,
player)`) apply the same test [known]:

```
if (type.size & 0x40) and not (cellFlags & 0x40): return false      # military types need a military plot
return (cellFlags & type.size & 0x3f) != 0
```

So the low six bits are the set of plot classes on which the type may stand. The cell side is computed by
`ConstructionMap_ComputeCellFlags` S 00675610 [known]: it asks `GameQuery::CanPlaceBuildingAt` S 0052fbe0 with
the size codes 4, 2, 1, 8, 16 in that order and stores 7, 3, 1, 8 or 16 for the first that succeeds (0 if none);
it then adds 0x20 when a flag can be placed on the cell (`GameQuery::CanPlaceFlagAt`), and 0x40 when bit 0 is set
and no building whose type has `territoryRange > 0` is found on the cell itself or within 4 hex rings
(`HasNoTerritoryBuildingWithinRadius4` S 0052dc30; it tests the range, not the `territoryBuilding` flag).
Hence bit 0 = a
small building fits, bit 1 = a medium one fits, bit 2 = a large one fits (a larger plot always carries the
smaller bits), bit 3 mine plot, bit 4 ship (harbour) plot, bit 5 flag possible, bit 6 "military allowed here".
No shipped size value has bit 5, so the flag bit never satisfies the test [known: data]. The placement rules
behind the probes are specified in [map-resources.md](map-resources.md) §3.5 and
[village-buildings.md](village-buildings.md). `SizeInvalid` (the three construction-site pseudo buildings) fits
nowhere. Distribution over the 104 types: Small 24 (+3 military), Medium 37 (+3), Large 11 (+3), Mine 18, Ship 2,
Invalid 3.

### 3.7 Tribe-neutral goods in map files

`MapInfo::NormalizeInitialGoodsForTribes` S 0052a670 [known]. Its only caller is `MapInfo::Load` S 0052bd40,
which runs it only when the stored `MapInfo` version is below 15, after the initial goods are read (or, below
version 14, rebuilt from the tribes' `startResources`); files of version 15 and later are taken as stored. For
each tribe's list (walked over a copy), for each entry whose good is in neither `TribeProperty.goods` nor
`.jobs`:

1. if that good has a `miningGood` and the tribe owns a good whose `miningGood` equals it
   (`GoodIdList_FindGoodByMiningGood` S 00552d20: first match in `tp_addGood` order), add the amount to that
   tribe good;
2. remove the original entry in every case.

Note that the lookup compares the **foreign good's `miningGood`** with the tribe goods' `miningGood`; a foreign
good without `miningGood` is dropped. Example from the data: `stoneScots.miningGood = stone` and
`stoneBav.miningGood = stone`, so scots stone in a list for bavarians becomes `stoneBav`. The neutral goods are
the egyptian ones and name themselves: `gp_setMiningGood(stone, stone)`, likewise gemstones, coal, salt, ironOre,
gold, fish, wood, corn and egyptCorn; the 14 scots and bavarian variants (stone, gemstones, coal, salt, ironOre,
gold, fish, each `…Scots` and `…Bav`) point at them (24 calls in total) [known: `Goods.lua`]. Goods without a
mining good (tool, coin, iron, food groups, weapons, …) are dropped from a foreign tribe's list.

### 3.8 Random deposit for a pattern (tree planting)

`PropertiesDb::PickRandomDepositForPattern(patternId, randomValue, requiredTag)` S 005477e0 [known]:

1. `tag = PatternProperty(patternId).treeType` (unknown pattern id is fatal).
2. Count the deposits, in table order, whose `treeTypes` contains **both** `tag` and `requiredTag`
   (`DepositProperty::TreeTypesContains` S 00547430).
3. If the count is 0 return -1. Otherwise `k = randomValue mod count` (unsigned) and return the id of the k-th
   matching deposit in table order (ascending signed deposit id).

Caller `Afforest_PickRandomDepositForCell` S 0077bb30: `patternId` = pattern of the cell, `requiredTag` =
`NResources::System+0x08` (the map's tree type, 100 / 101 / 102), `randomValue` = one draw of the simulation
random generator [known]. The result depends on the iteration order of the deposit table, so on the deposit ids.

### 3.9 Sacrifice effect lists

Types below 15 are **modifiers** on the target player's `SacrificeModifiers` table while the sacrifice runs;
types above 15 are **one-shot actions** [known: S 00663560 tests `type < 0xf`, S 00660960 tests `0xf < type`].

Each player has one `SacrificeModifiers` table (0xf8 bytes inside the player's 0x188-byte sacrifice record):
`flags[15]` i32 at `+0x00`, `ownBonus[15]` float at `+0x3c`, `hostileDivisor[15]` at `+0x78`, `effective[15]` at
`+0xb4`, the player index at `+0xf4`, each array indexed by effect type [known: S 006634f0, S 006630b0]. The
neutral state is `flags = 0` and 1.0 in the three float arrays (S 00663530, S 006634f0) [known].

The tables are never updated incrementally. `SacrificePlayerTable::RecomputeModifiers` S 00662fb0 resets all
eight tables to neutral and then, for every player in index order and every running sacrifice of that player in
list order, offers the sacrifice to all eight tables (S 00661ec0); it runs after every start, removal and load
of a sacrifice [known: callers]. A table accepts a sacrifice only when the sacrifice's **target player** equals
the table's player (`ApplySacrifice` S 00663630) [known]. The target player is fixed when the sacrifice starts
(`ai::village::VillageSacrifice::Start` S 005615e0): for `target == 0` (`Target_Owner`) it is the owner, for `target == 1`
(`Target_Enemies`) it is the one player chosen with the order [known]. So a sacrifice changes exactly one
table: the owner's with own effects, or one enemy's with hostile effects.

`ApplyEffectList` S 00663560 walks the record's effect list in order and, for types below 15, calls the own
effect S 006630b0 when the sacrifice's owner is the table's player, else the hostile effect S 006631e0 [known].
Every call ends by storing `effective[t] = ownBonus[t] / hostileDivisor[t]`. `a` = the effect's `arg1`
(converted to float):

| Type | As own effect | As hostile effect |
|---|---|---|
| 1, 2, 3, 8, 9, 11 | `ownBonus = max(ownBonus, a / 100)` | `hostileDivisor = max(hostileDivisor, a)` |
| 4, 5 | `ownBonus = min(ownBonus, a / 100)` | `hostileDivisor = max(hostileDivisor, a)` |
| 6 | `ownBonus = max(ownBonus, a)` | `hostileDivisor = max(hostileDivisor, a)` |
| 7, 10, 12 | `flags = 1` | nothing |
| 13 | nothing | `hostileDivisor = min(hostileDivisor, 1 / (a / 100))` |
| 14 | `flags = a` | nothing |

Data examples [known: data]: `CarrierSpeed` 300 (own: carriers × 3.0), `ProductionSpeed` 75 (own: duration ×
0.75), `SoldierArmor` 120, `SoldierDamage` 120 / 140, `BuildingArmor` 400, `ArcherAttackSpeed` 80,
`ArcherHitChance` 2, `ShipSpeed` 200 for the owner and `ShipSpeed` 2 on enemies (divisor 2), `WorkerPause` 300
on enemies (divisor 1/3, i.e. rest × 3), `ExpandTerritory` 5.

Where each value is read [known: the reader bodies, constants 0.5 at S 007d4a90 and 100.0 at S 007d8ff0]. All
readers index the table of the acting unit's or building's owner; "round" is `trunc(x + 0.5)`, "trunc" is the
plain float-to-integer conversion:

| Type | Value | Reader | Rule |
|---|---|---|---|
| 1 `CarrierSpeed`, 8 `SoldierSpeed` | `effective` | S 00663310 | settler speed = `GameConfig.settlerSpeed` × `effective[1]` for settler type 2 (carrier), × `effective[8]` for type 3 (soldier), × 1 otherwise ([settlers-jobs.md](settlers-jobs.md)) |
| 2 `SoldierArmor` | `effective` | S 00663370 (`NSettlers::Soldier::TakeDamage`, AI strength) | armor = round(`GoodProperty.armor` × `effective[2]`) |
| 3 `SoldierDamage` | **`ownBonus`** | S 00663610 (soldier wrapper S 00658f20), S 006632b0 (AI strength S 0059e6c0) | damage = round(`GoodProperty.hitDamage` × `ownBonus[3]`); the hostile divisor of type 3 is not read by these two |
| 4 `ProductionSpeed` | `effective` | S 00663390 | `productionTime` × `effective[4]`, only for working modes 6 and 10 (`Production::GetProductionDuration` S 00565ed0); other modes use `productionTime` unchanged |
| 5 `ArcherAttackSpeed` | `effective` | S 006633b0 via S 00661b80 (`NMovie::Fight::Start`) | strike length = trunc(`attackTime` × `effective[5]`) when the good's `soldierType` is 1 (bow), else `attackTime` |
| 6 `ArcherHitChance` | `effective` | S 006633d0 (`NMovie::Fight::Start`, bow soldiers only) | threshold' = threshold − trunc(`effective[6]` × 100) + 100, applied to the striker's miss threshold of [military.md](military.md) §3.7 |
| 7 `MinerNeedNoFood` | `flags` | S 00663430 (`Production::StartProductionCycle`, `CanStartProduction`) | tested as `flags[7] != 1` for building types with `size == 8` and working mode 6 (mines); together with the player-state test of [players-victory.md](players-victory.md) it decides whether the mine's inputs are requested ([village-buildings.md](village-buildings.md)) |
| 9 `ShipSpeed` | `effective` | S 006632d0 (`NNavy::Movement::GetSpeed`) | ship speed = `ShipConfig.speed[tribe]` × `effective[9]` |
| 10 `PeaceTime` | `flags` | S 00663440 (`NVillage::Military::GetAttackTargetState`, `NMilitary::Fight::Update`, `NMilitary::Attack::GetAttackAvailability`) | tested as `flags[10] > 0`; the consequences are in [military.md](military.md) |
| 11 `BuildingArmor` | `effective` | S 006633f0 (`NVillage::Building::OnCatapultHit` S 0055e080) | damage = trunc(v / `effective[11]`), where v is the integer at `+0xd0` of the projectile object passed to `OnCatapultHit`; the result is compared with the building's hit points and passed to `Hitpoints::ApplyDamage` [known: call site S 0055e1be; the wrapper S 00661bd0 selects the table of the building's owner]. Projectile `+0xd0` is written by `MilitaryProjectile::SetSourceCatapult` S 00572de0 with the `catapultDamage` (`BuildingProperty+0xdc`) of the firing catapult's building type, and by `SetSourceSoldier` S 00572d90 with the soldier's strike value [known] |
| 12 `CornDoubleProduction` | `flags` | S 00663450 via S 00661c50 (`Production::DeliverProducts`, `NMovie::PutDownPackage::Update`) | when the building's product slot holds the good with id `17626a03` (`corn`; the id is a constant in the code) and `flags[12] > 0`, the slot's amount is doubled. `egyptCorn` has another id and is not doubled by this test |
| 13 `WorkerPause` | `effective` | S 00663410 (`NMovie::Rest::Start`) | rest ticks = trunc(`restTime` × `effective[13]`) |
| 14 `ExpandTerritory` | `flags` | S 006634d0 via S 0055fca0 | territory range = `territoryRange` + `flags[14]`, only for types with `territoryRange > 0` |

Because own effects of types 7, 10 and 12 store the constant 1, the `arg1` of those effects in the data (for
example 400 on `CornDoubleProduction`) has no influence [known: S 006630b0].

One-shot actions, `ai::logic::Sacrifice::UpdateTimedEffects` S 00660960, every tick of a running sacrifice [known]:
`progress = (now - startTick) / duration` (floats); effect `i` fires once, the first time `threshold <=
progress`, and is then marked in a per-sacrifice bit vector. `threshold` is the truncated fifth argument, so in
the data it is 0 (fires on the first update) or 1 (fires when the duration has elapsed). `Sacrifice::ApplyEffect`
S 00660500 dispatches:

| Type | Action | Arguments |
|---|---|---|
| 1001 (0x3e9) | add `arg2` units of good `arg1` to the temple's stock and to the statistics (S 0065ffc0) | good id, count |
| 1003 (0x3eb) | heal own units | – |
| 1004 (0x3ec) | reveal the target's buildings | – |
| 1005 (0x3ed) | reveal navy objects | – |
| 1006 (0x3ee) | call the map script's sacrifice-execute function with the sacrifice id | – |
| 1007 (0x3ef) | reveal the map | – |
| 1008 (0x3f0) | sink the target's ships | – |

Type 1000 (`FunctionSpawnSoldier`) has no case in the dispatcher [known]. `SacrificeProperty::AddEffect`
S 005568d0 appends the four integers unchanged as `{type, arg1, arg2, threshold}` [known].
`GetGiveGoodsEffectGoodId` S 005565e0
returns `arg1` of the first type-1001 effect (undefined result when there is none); `HasEffectType` S 00556540
tests for a type [known].

Good-exchange sacrifices are built by the Lua helper `defaultSacrificeGEProperties(id, rewardGood, rewardCount,
uiName)`: duration 20, not abortable, category 4, regeneration delay 3000 (every one of the 31 records then
sets its own: 1800, 3600 or 5400 for ten records each, 2400 for one), target
owner, effect `(1001, rewardGood, rewardCount, 1)` [known: `sacrifices_goodExchange.lua`].

### 3.10 Sign lookup

`ai::properties::SignDoodadTable::GetDoodadId(good, amount)` S 00556d70 → S 00556cb0 [known]: in the good's list (sorted by
threshold) return the doodad of the last entry with `threshold <= amount`; -1 if `amount` is below the first
threshold. A good without a list is a fatal lookup (no end check). With the shipped thresholds: amount 1..2 →
S sign, 3..5 → M, 6..999 → L, ≥ 1000 → X. Caller `NMovie::GoDigging::PlaceResourceSignAndNotify` S 0077b2f0.

### 3.11 How the three tribes differ in data

Everything tribe-specific is expressed by separate records plus the tribe's lists; there is no "tribe" field on
goods or buildings [known: data].

| Aspect | Bavarians `b0d378a3` | Egyptians `f5016d33` | Scots `497ffda3` |
|---|---|---|---|
| Wares (`tp_addGood`) | 26; own variants `…Bav` of tool, stone, ores, coal, salt, gold, iron, coin, food groups | 26; the unsuffixed goods (tool, stone, coal, iron, coin, …) | 26; own variants `…Scots` |
| Construction materials (`constructionGoodId`) | `constructionResourcesBav` | `constructionResourcesClay` (clay instead of planks) | `constructionResources` (plank, stoneScots) |
| Food and drink chain | fishBav, fleshham, pretzel; weissbeer | fish, goatHam, cornBread, milk, cheese; `egyptCorn` | fishScots, sheepHam, bread; whisky; kilt |
| Buildings (`tp_addBuilding`) | 37 | 35 | 37 |
| Soldier ranks (`tp_addJob`, `mi_setSoldierId`) | halberd 0..2, crossbow 0..2 | sword 0 only, bow 0..2 | claymore 0..2, sling 0..1 |
| Second carrier | `good_oxen` (costs one `oxen`) | `good_helper` (no cost) | none |
| Builder (`constructor`) | `good_constructorBav` | `good_constructor` | `good_constructorScots` |
| Tool / coin good | `toolBav` / `coinBav` | `tool` / `coin` | `toolScots` / `coinScots` |
| Garrison limits guard house / tower / fortress | 3 / 6 / 9 | 4 / 8 / 12 | 2 / 4 / 6 |
| Ship speed | 0.06 | 0.09 | 0.12 |
| Expedition building | `guardHouseBav` | `guardHouseClay` | `guardHouse` |
| Hunter's yield (`an_addStackGood`) | leather | goatHam | sheep (from sheep only) |
| Sacrifices listed (`tp_addSacrifice`) / allowed (`tp_addAllowedSacrifice`) | 23 / 7 (a 24th call, `sacrifice_workerPause`, is commented out) | 24 / 8 | 22 / 7 |
| Start / bonus resource entries | 23 / 28 | 23 / 25 | 21 / 25 |
| Map tree tag | 100 | 101 | 102 |
| UI | `menuX` 16, `uiBuildings0` | 184, `uiBuildings1` | 352, `uiBuildings2` |

Shared by all three: the goods `wood`, `water`, `weapons` (group), `sacrificeGood`, `sacrificeGoodOlympicFlame`
and the buildings `castle` and `sacrificeOlympicFlame`. Bavarians and scots also share the goods `plank`, `corn`
and `flour` and the building `shipBuilding` (egyptians: `shipBuildingEgypt`); otherwise each tribe has its own
building records (bavarians `fisher`, `hunter`,
`spring`, …`Bav`; egyptians …`Clay` / …`Egypt`; scots `fisher2`, `hunterScots`, `springScots` and the unsuffixed
names) [known: `tribes.lua`]. The position lists of a building record are keyed by tribe, and the shared `castle`
carries none [known: `buildings.lua`].

---

## 4. Update order

The database has no per-tick and no per-frame behaviour: it is filled once and then only read. `data.lua` is run
by `PropertiesDb::RunPropertyScript` S 0054f8d0, whose only caller is `CApplicationEx::Initialize` [known].
[inferred] nothing else writes records: no function of the properties code has "update" or "tick" in its name,
and the record setters with a name of their own are called only from the `LuaProps_*` bindings; the
one-instruction setters the linker shares between classes (e.g. `Generic_SetByte40`, `Generic_SetDword_50`) also
have callers outside the bindings, and the object type at those call sites was not checked. No write was seen in
play: the hashes of all 565 pointer-table records and of the three config blocks were equal before and after a
save load plus some hundred ticks of play [live, 2026-10-14].

**Load order** matters because bindings dereference records and read other records' values at call time (§3.1,
§3.2, §3.3). `data.lua` runs, in this order [known: data]:

`defineTribes` → `doodads` → `goods` → `config` → `patterns` → `animals` → `jobs` → `deposits` → `remains` →
`buildings` → `sacrifices` (which itself loads `sacrifices_goodExchange` and `sacrifices_campaign` right after
its enum constants, before its own records) → `signs` → `military` → `ship` → `sounds` → `ai` → `harbors` →
`tribes` → `spawnpoints`.

`data.lua` asks for `goods.lua` and `jobs.lua`; the files on disk are `Goods.lua` and `Jobs.lua` (the original
runs on a case-insensitive file system) [known: data]. All scripts share one Lua global table, so a constant or
id variable defined by an earlier script (`bavarians`, `plank`, `doodad_chest`, `SizeSmall`, `Desert`) is used by
later ones.

---

## 5. Inputs and outputs

- **Inputs**: only the property scripts, through the Lua library `properties` (243 bindings,
  [../lua-surface.md](../lua-surface.md) §3.3). The library is registered once in the process's single Lua
  state and stays in its global table, so every script run later (map scripts, menu scripts) can still call
  `properties.*` and change a record ([../lua-surface.md](../lua-surface.md) §1.2). None of the shipped ones
  does: no `.lua` file of the install outside `scripts/properties/` (333 files: campaign map scripts, `info`,
  `mapTools`, `editor` and two single files) contains `properties.` [known: data]. [inferred] no player command or network message
  writes a record (§4).
- **Outputs**: record getters `PropertiesDb::Get<Type>Property` (S 005474a0 buildings, S 00547520 deposits,
  S 00547560 goods, S 005475a0 patterns, S 005475e0 remains, S 00547620 doodads, S 00547660 animals, S 005476a0
  sounds, S 005476e0 AI, S 00547720 harbours, S 00547760 tribes, S 005477a0 sacrifices, S 005474e0 spawn point
  types); name lookups (§2.2); the derived queries of §3.3–3.10; the index-based `StaticAccess` view (§2.1).
- **Main readers** (callers of the getters) [known: call graph]: buildings — placement checks
  (`GameQuery::CanPlaceBuildingTypeAt`, `Village_CheckBuildingPlacement`), `NVillage::Building` ctors,
  `Construction`, `Upgrade`, `Bulldozing`, `Remains`, the AI planners, `NNavy::Expedition`,
  `NPlayer::GoodArrangement`, the build menu; goods — `NLogic::Stock`, `NVillage::Depot`, `OrderSystem`,
  `SettlerSpawn`, soldier training, the AI need system, `ai::player::Player::Update`; tribes — `ai::player::Player::Init` /
  `Load`, `MapInfo`; patterns — `MapModifier::SetCellPattern`, `MapCellUpdater`, `Continents`; sacrifices —
  `VillageSacrifice`, `ai::logic::Sacrifice`, `SacrificeResearch`, the AI sacrifice manager, the map-script
  function `pl_sendOrderSacrificeMessage`.
- It raises no events and has no observers.

---

## 6. Data-driven parameters

Everything in this subsystem is data. Per script, the keys it uses (number of call sites in the script text; a
call inside a Lua helper function counts once) and examples; all from the decrypted install [known: data]. Bindings that exist but are never called by the shipped scripts are listed at
the end.

| Script | Keys (calls) | Examples |
|---|---|---|
| `defineTribes.lua` | `tp_create` (3) | `bavarians = tp_create("b0d378a3")` |
| `doodads.lua` | `dd_create` (168), `dd_setName`, `dd_setGfxName` (168 each), `dd_setType`, `dd_setLifeTime`, `dd_setDeleteByStreet` (26 each: the signs), `dd_setBlocking` (21), `dd_setIndestructable` (1) | `dd_setLifeTime(doodad_coalSignS, 3000)` |
| `Goods.lua` | `gp_create` (100), `gp_setName`, `gp_setType` (41), `gp_addCost`, `gp_setTransportPriority` (141; `Jobs.lua` has none), `gp_setAiPriority` (93), `gp_setArrangementGoodId` (22), `gp_setMiningGood` (24), `gp_enableFields` (21), `gp_enableDeposits` (6), `gp_setPlantable` (3), `gp_setAiRandomValue` (10), `gp_setAINoNeedForCosts` (5) | `gp_addCost(bread, flour, 1)`; `gp_setTransportPriority(coalScots, scots, 15)`; `gp_setAiPriority(stoneScots, scots, 300)` |
| `config.lua` | 17 `cfg_set*` (§2.10); size and time constants | `cfg_setSettlerSpeed(0.058)` |
| `patterns.lua` | `pa_create` (114), `pa_setName`, `pa_setGfxName`, and through the helpers `pa_setBlocked`, `pa_setForBuilding`, `pa_setForPlanting`, `pa_setForMining`, `pa_setTreeType`, `pa_setMiniMapColor`, `pa_setForShip`; `cfg_setBorderPattern` (1) | `pattern_water = pa_create("fe6bd1b3")`; `cfg_setBorderPattern(pattern_border)` |
| `animals.lua` | `an_create` (12), `an_setName`, `an_setGfxName`, `an_setRange`, `an_setMoveDistance`, `an_setMovementSpeed`, `an_setAvoidBuildings` (12 each), `an_addStackGood`, `an_setRespawn`, `an_setDyingTime`, `an_setDisappearingTime` | `an_setMovementSpeed(animal_rabbit, 0.07)` |
| `Jobs.lua` | `gp_create` (76), `gp_setType(…, Settler)`, `gp_setSettlerType` (76), `gp_setGfxGoodId` (62), `gp_addCost`, soldier keys (15 each: `gp_setHitDamage`, `gp_setHealth`, `gp_setArmor`, `gp_setAttackWaitTime`, `gp_setBlockingChance`, `gp_setAttackTime`; `gp_addHitTime` 16; `gp_setSoldierType`, `gp_setBowRange`, `gp_setProjectileType` 8 each) | §2.4 |
| `deposits.lua` | `dp_create` (53), `dp_setName`, `dp_setGfxName`, `dp_setGood` (53 each), `dp_addTreeType` (60 active; 15 more are commented out), `dp_setRandomFinePosOffsetState` (18), `dp_setBlocking` (15), `dp_addUndergroundPattern` (14), `dp_setElevationSize` (12), `dp_nextDeposit` (10), `dp_setGrowingSpeed`, `dp_setGrowingStartSize` (3), `dp_setLifeTime`, `dp_setNeedForPlantablePattern` (2) | `dp_nextDeposit(stone_02, stone_01)` |
| `remains.lua` | `rm_create` (3), `rm_setName`, `rm_setGfxName`, `rm_setBurningTime` | `rm_setBurningTime(remainsSmall, 50)` |
| `buildings.lua` | `bp_create` (104) and 39 further `bp_*` keys; counts in [village-buildings.md](village-buildings.md) §6 | `bp_setGoods(bakery, bread, 1)`, `bp_setProductionTime(bakery, 333)`, `bp_setSize(guardHouse, SizeSmall+SizeMilitary)` |
| `sacrifices.lua`, `sacrifices_goodExchange.lua`, `sacrifices_campaign.lua` | `sf_create` (36 + 31 + 10), `sf_addCost` (165), `sf_setRegenerationDelay` (78), `sf_setResearchDuration` (53), `sf_setName`, `sf_setGfxName`, `sf_setDuration`, `sf_addEffect`, `sf_setCategory`, `sf_setTarget` (47 each: 36 + 10 direct and one inside the exchange helper, which runs for each of the 31 exchange records), `sf_setAbortable` (39, one of them in the helper), `sf_setBuffGfxName` (13), `sf_setForCampaign` (3) | `sf_addCost(sacrifice_carrierSpeed, water, 20)`; `sf_addEffect(sacrifice_carrierSpeed, Effect_CarrierSpeed, 300, 0, 1)`; `sf_setDuration(…, 9000)` |
| `signs.lua` | `si_addSignDoodadId` (26) | `si_addSignDoodadId(coal, 3, doodad_coalSignM)` |
| `military.lua` | `mi_setRegenerationRate(100)`, `mi_setWaitForTacticTime(10)`, `mi_setActionsInFightDelayTime(300)`, `mi_setHealthExchangeDistance(200)`, `mi_setSoldierId` (15) | `mi_setSoldierId(scots, soldierType_Bow, 1, good_bowSoldierStone1)` |
| `ship.lua` | `sh_setSpeed` (3), `sh_setExpeditionBuilding` (3), `sh_setSize`, `sh_setConstructTime`, `sh_setStockLimit`, `sh_setWaitTime`, `sh_setSinkingTime` | §2.10 |
| `sounds.lua` | `sn_create` (156), `sn_addFileName` (311), `sn_setName`, `sn_setType`, `sn_setLooping`, `sn_setPriority`, `sn_set3DMinDistance`, `sn_set3DSound`, `sn_setVolume`, `sn_set2DDistance`, `sn_setMusicTribe` (6), `sn_setPercussion` (3) | `sn_setMusicTribe(music_bavarians, bavarians)` |
| `ai.lua` | `ai_create` (6) and 28 `ai_*` keys; `ai_addFavoritSacrifice` (95), `ai_setFactor` (24) | `ai_setFactor(ai_c5_pirates, AI_BattleMode_Attack, AI_BattleValueOf_Own, 0.8)`; `ai_setAttackLimiterDelay(…, 1200)` |
| `harbors.lua` | `hp_create` (8), `hp_setName`, `hp_setGfxName`, `hp_setWaterStreetPosition` (17), `hp_setShipPosition` (34) | `hp_setShipPosition(harbor_sw, 0, 1, -3, -4)` |
| `tribes.lua` | `tp_setName`, `tp_setMenuX`, `tp_setBuildingsTextureName`, `tp_setConstructionGoodId`, `tp_setWorkerToolGoodId`, `tp_setSoldierUpgradeGoodId`, `tp_setConstructor` (3 each), `tp_setSecondCarrierId` (2), `tp_addGood` (78), `tp_addJob` (16), `tp_addBuilding` (109), `tp_addSacrifice` (69), `tp_addAllowedSacrifice` (22), `tp_addStartResources` (67), `tp_addBonusResources` (78) | `tp_addStartResources(scots, plank, 30)`; `tp_addBonusResources(egyptians, clay, 18)` |
| `spawnpoints.lua` | `sp_create` (12), `sp_setName`, `sp_setGfxName`, `sp_setParticleName`, `sp_setType` (12 each), `sp_addUniqueId` (30) | `sp_addUniqueId(animalspawn, animal_deer)` |

Registered but never called by the shipped scripts [known: data against the binding list]: `gp_setShortName`,
`gp_setValue`, `cfg_setGameSpeed`, `cfg_setChestOwningTime`, `an_setIdleTimeFactor`,
`dd_setOnWater`, `dp_setDoodadAfterDestruction`, `rm_setDoodadAfterFinished` (commented out), `sp_setRate`,
`sp_setRange`, `sf_addBuildingDependence`, `ai_setBattleCalcRatio`, `ai_setSwordBowRatio`, the five
`ai_setSpecial*` keys, `sn_set3DMaxDistance`. Their fields keep the ctor defaults of §2.

---

## 7. Save and load

- The database itself is **not saved**. A save game and a map file store record **ids** (tribe per player, good
  ids in stocks, building type ids, deposit / animal / doodad / pattern / harbour / spawn / sacrifice ids:
  [../map-format.md](../map-format.md) §2.4), and on load every stored id is resolved again through the getters
  [known: `ctor_ForLoad` / `Load` callers of the getters in §5].
- An id in a file that no script created is fatal for the tables read through the unchecked getters (§2.2)
  [known].
- `MapInfo` versions ≥ 10 store the map's per-tribe sacrifice list right after the initial goods
  [known: disassembly of `MapInfo::Load` S 0052bd40 at 0052c028..0052c0a1]: the map at `MapInfo+0x204` is
  cleared, a u32 count is read, and per entry an i32 tribe id followed by a vector of i32 sacrifice ids (u32
  count, then the ids; `StdVector32_Load` S 00552e00, which replaces the vector's content). [inferred]
  `MapInfo::Store` S 00529db0 writes the same block (it writes the map's size and walks the map). For versions
  10 to 12 the list just read is then replaced by the tribes' `allowedSacrifices` (next item).
- A `MapInfo` that was not loaded has an empty sacrifice list: `MapInfo::Reset` S 0052b8d0 (callers: the ctor
  and `GameLoadDescriptor::Reset`) refills the initial goods with `ResetInitialGoodsFromTribes` but neither
  clears nor fills the map at `+0x204`, and `ResetSacrificesFromTribes` is called only from `Load` [known].
  The complete set of code on `MapInfo+0x204` is the ctor S 0052bc10 (empty map), the dtor S 0052b400,
  `Load`, `ResetSacrificesFromTribes`, `Store`, the copy `MapInfo::Assign` S 007849f0 and the two readers
  `GetMapSacrifices` S 00529720 / `HasMapSacrifices` S 00529760 [known: search of the instruction listing for
  `+0x204`..`+0x20c`]. So nothing fills the list of a new map: a map made without loading a file (the editor)
  is saved with an empty list, and its players are offered only the lock-map-2 sacrifices of its script.
- Recomputed on load from properties, not stored: the per-tribe sacrifice lists of old saves
  (`ResetSacrificesFromTribes`, version ≤ 12) and the initial goods of old maps (`ResetInitialGoodsFromTribes`,
  version ≤ 13); initial goods are normalised per tribe only for `MapInfo` versions below 15 (§3.7) [known:
  the three version tests at the end of `MapInfo::Load` S 0052bd40, `version > 13`, `> 12`, `> 14` skip].
- The derived tables of `MilitaryConfig` (health, max level) and the lazily built soldier good lists exist only
  in memory [known].
- A multiplayer match requires identical property scripts on all machines: they are part of the build checksum
  ([../data-loading.md](../data-loading.md) §3).

---

## 8. Determinism notes

- The database never draws random numbers. `PickRandomDepositForPattern` receives a value drawn by its caller
  from the simulation generator (§3.8) [known].
- **Table iteration order is by signed id**, and several rules depend on it: "first building with …" (§3.5),
  the k-th matching deposit (§3.8), `FindIdByNameAnyTable` (first table, then first id), `StaticAccess` indices.
  A reimplementation that stores records in a hash map or in script order must reproduce ascending signed-id
  order for these queries, otherwise tree planting desynchronises against the original.
- **List order is script order** and is used for tie-breaking: group members in `tp_addGood` order (§3.4), the
  first alternative of an EitherGroup that is in stock, the order of construction materials in the warning list,
  `GoodIdList_FindGoodByMiningGood` (first match).
- Per-tribe maps inside records (`transportPriority`, `aiPriority`, `stackGoods`, position maps, ship speed) are
  only looked up by key in the functions read here; no ordered iteration over them was seen [inferred].
- Floats: `productionTime`, `growingSpeed`, `movementSpeed`, `settlerSpeed`, ship speed and the AI factors are
  stored as 32-bit floats converted from Lua doubles (`Lua_ToFloat`) [known]. Values such as 0.058 or 0.00075 are
  not exactly representable; a reimplementation must round the script's double to float32 at load, not keep the
  double.
- Integer keys read with `Lua_ToInt` truncate toward zero (S 005c9b30 converts with `__ftol2_sse`) [known];
  `sf_addEffect`'s fifth argument and `bp_setWorkingRadius` go through float first and are truncated the same
  way (§2.7). Position coordinates are truncated to integers before they are stored as floats (§3.1).
- Load order is fixed by `data.lua` (§4); the cached soldier health and the sacrifice-good group depend on it.

---

## 9. Notes for a reimplementation

- **Keep the ids.** They are stored in maps and saves; use the same 32-bit values (as signed integers) as record
  keys. Names are not unique and must not be used as keys.
- **Keep the scripts as the source of truth.** The simplest faithful loader is a Lua interpreter with a
  `properties` table implementing the 243 bindings and running `data.lua`; the scripts use real Lua (helper
  functions, `type()`, arithmetic like `SizeSmall+SizeMilitary`, globals shared across files). A converter to a
  static format (JSON, Godot resources) is equally valid if it evaluates the scripts the same way, including the
  load order and the side effects of `sf_addCost` and `mi_setSoldierId`.
- Resolve file names case-insensitively (`goods` → `Goods.lua`).
- Can be simplified: the three storage styles (pointer map, inline map, singleton block) are irrelevant; the
  four registration flags, `StaticAccess`, `shortName`, `value`, the unused `Depot_*` / `tactic_*` constants and
  the never-called bindings can be omitted or kept as inert fields; the crash-on-missing-id behaviour should
  become a load-time validation error.
- Must be exact for compatibility with original maps and saves, and for lockstep with identical data: ids;
  signed-id iteration order where §8 lists it; list orders; `GoodAmountList_AddAmount` merging; the
  one-level, first-group-wins search of `CostsContainGood`; float32 storage; ctor defaults for every key a
  script does not set (many records rely on them: `workingMode` 6, `workerLimit` 1, `constructionTime` 500,
  `attackTime` 17, `bowRange` 6, good `type` 0, `deleteByStreet` true, `respawn` true, …).
- Validate at load what the original leaves to crash: every referenced id exists in the right table; every good
  in `tp_addGood` has `transportPriority` and, where the AI needs it, `aiPriority` for that tribe; every tribe
  has ship speed, expedition building and soldier level 0 of both kinds; every good a geologist can find has a
  sign list.
- `producedSettler` holds a good id for mode 4 and an animal id for mode 10; treat it as a tagged reference.
- The building dependence of sacrifices (`sf_addBuildingDependence`) is dead in the original; do not invent
  semantics for it.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§2.6, [map-resources.md](map-resources.md) §2.5 and §10 #5): `DepositProperty.elevationSize` (+0x50) is read by `MoveToDeposit::Update` S 007778f0 as the stop distance of the worker's fine walk onto the deposit [known] | — |
| 2 | Answered (§2.1, §2.10): `GameConfig+0x4c`, `GameConfig.bulldozeTime`, `MilitaryConfig+0x108`, `GameConfig+0x3c` and `MilitaryConfig+0x10c` are never read (the property database is reached only through `EnsureInstance` S 0054a140; none of its 593 callers and none of the typed block methods reads them); `+0x4c` has no meaning in the shipped code. Still `[inferred]` only: `ShipConfig+0x00` and the sign table's byte (the ship keeps the config pointer), and `GoodProperty.value` / `plantable` (no caller of `GetGoodProperty` S 00547560 reads them, but good records are also reached through pointers kept in other objects) | — |
| 3 | Answered (§2.3, §7): `TribeProperty.sacrifices` has no reader (only `AddSacrifice` and the ctor touch it), and nothing but `MapInfo::Load` (with `ResetSacrificesFromTribes`) and the copy `Assign` fills `MapInfo+0x204`; a new map's list stays empty | — |
| 4 | Answered (§2.6): no worker search selects a deposit whose good is a settler good; both good-keyed deposit searches (S 00540870, S 00540940) use the wanted good's `miningGood`, and no good has `miningGood = good_helper`, so a `tent` is never harvested | — |
| 5 | Answered (§4): the game itself never reloads (filled in `Initialize`, emptied in `Shutdown`; no script outside `scripts/properties/` calls a binding), and play does not write into a record: the hashes of all 565 pointer-table records (buildings 104, deposits 53, goods 176, patterns 114, animals 12, AI 6, harbours 8, tribes 3, sacrifices 77, spawn types 12) and of the three config blocks were equal before and after a save load plus some hundred ticks of play [live, 2026-10-14]. For a mod's reload: `ClearAll` S 005494a0 empties all record tables and the sign table; the three config blocks are kept, and every binding on them assigns (`cfg_set*`, `sh_set*`, `mi_set*`), so the values come out the same [inferred]; record addresses change, and the static soldier good lists (§3.3) are not rebuilt | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 0054a140 | `NProperties::StaticAccess::EnsureInstance` | returns the singleton, creating it on first use |
| S 00549dd0 | `Properties_Db_ctor` | builds the empty tables and the three config blocks |
| S 005494a0 | `Properties_Db_ClearAll` | empties every table, clears the flags |
| S 00555810, S 00553f10, S 00661ab0, S 00556f20 | `ai::properties::GameConfig::SetFlag3C_False`, `ai::properties::MilitaryConfig::SetFlag10C_False`, `Generic_ClearByte0`, `ai::properties::SignDoodadTable::Clear` | the four flag clears of `ClearAll` (the last also empties the sign table) |
| S 00550e40 | `Properties_RegisterLuaLibrary` | sets the flags, registers the 243 bindings of `properties` |
| S 0054f8d0 | `PropertiesDb::RunPropertyScript` | runs `[data]\scripts\properties\<name>.lua` |
| S 005455b0 | `Str_ParseHexUInt32` | id parser of every `*_create` |
| S 00549040 | `Stl_Map_Int_Subscript` | `map[id]` used by every setter (inserts NULL for unknown ids) |
| S 005498d0 .. S 00549d50 | `Properties_Create<Type>Property` | allocate a record and store it under its id |
| S 00554a40 | `GoodProperty::SetId` | called by the good create function: id to `+0x00` and to `arrangementGoodId` |
| S 005474a0 .. S 005477a0 | `PropertiesDb::Get<Type>Property` | lookup by id, fatal when missing |
| S 00546100 | `PropertiesDb::FindIdByNameAnyTable` | name → id over all tables in fixed order |
| S 00545f50, S 00546050, S 00545f70 | `PropertiesDb::FindGoodIdByName`, `FindTribeIdByName`, `FindSoundIdByName` | name → id in one table |
| S 00553cf0 | `BuildingProperty::ctor` | building defaults |
| S 00552fa0, S 00553080 | `BuildingProperty::ProducesGood`, `ConsumesGood` | product and recipe tests |
| S 00553460 | `BuildingProperty::GetAllCosts` | frame cost + cost |
| S 00553a50, S 00553af0, S 005532f0, S 00553340 | `Set/GetConstructionPosition`, `Set/GetIdlePosition` | per-tribe position lists |
| S 0055cdd0, S 0055ce20 | `GetEntranceDirection`, `HasEntranceDirection` | door offset per tribe |
| S 0052e510 | `Building_TypeFitsConstructionFlags` | size mask test (build menu) |
| S 0052eab0 | `GameQuery_BuildingTypeFitsCellFlags` | the same size mask test for placement and the AI |
| S 005c9b30, S 005c9b10, S 005c9b50 | `Lua_ToInt`, `Lua_ToFloat`, `Lua_ToBool` | argument conversion of every binding |
| S 0052bd40 | `NLogic::MapInfo::Load` | version gates of the property-derived upgrades (§3.7, §7) |
| S 00533bb0 | `Properties_FindFirstBuildingWithFlags54F1F5` | headquarters type |
| S 00546070 | `PropertiesDb::FindBuildingProducingGood` | first producer in table order |
| S 00534d00, S 00534f40 | `Economy_CollectProducerBuildings`, `…ConsumerBuildings` | producers / consumers of a good for a tribe |
| S 00554da0 | `GoodProperty::ctor` | good defaults |
| S 00554a60 | `GoodProperty::CostsContainGood` | recipe membership with one-level group expansion |
| S 00554b70, S 00554bc0 | `GoodProperty::GetTransportPriority`, `GetAiPriority` | per-tribe values, key must exist |
| S 00554ae0 | `GoodProperty::HasHitTimeInRange` | strike timing |
| S 00552aa0 | `GoodAmountList_AddAmount` | merging append for {good, amount} lists |
| S 00552d20 | `GoodIdList_FindGoodByMiningGood` | tribe good for a neutral resource |
| S 007767c0, S 00776690 | `PropertyGroupIter::Init`, `ai::properties::PropertyGroupIter::Next` | members of a group good for a tribe |
| S 00556300 | `TribeProperty::ctor` | tribe defaults |
| S 00556400 | `TribeProperty::AddSacrifice` | `tp_addSacrifice` backend |
| S 00556020, S 00556060 | `TribeProperty::SecondCarrierCostsContainGood`, `GetSecondCarrierFirstCostGoodId` | second-carrier helpers |
| S 005560d0 | `TribeProperty::FindGoodIdByName` | name → good among the tribe's goods |
| S 0052a670 | `MapInfo::NormalizeInitialGoodsForTribes` | translation of initial goods between tribes |
| S 0052bb40, S 00529720, S 00529760 | `MapInfo::ResetSacrificesFromTribes`, `GetMapSacrifices`, `HasMapSacrifices` | the map's per-tribe sacrifice list and its default |
| S 00552e00 | `StdVector32_Load` | reads one id vector of that list |
| S 00554380, S 00554290 | `MilitaryConfig::ctor`, `SetSoldierId` | soldier tables and derived caches |
| S 00554090, S 00553fb0, S 005540e0, S 00554750 | `GetSoldierId`, `FindSoldierLevel`, `GetMaxSoldierLevel`, `GetSoldierGoodList` | soldier queries |
| S 005556c0, S 005554d0, S 00555510 | `Properties_ShipConfig_ctor`, `ShipConfig::GetSpeed`, `GetExpeditionBuilding` | ship block |
| S 00555780 | `Properties_GameConfig_ctor` | game config defaults |
| S 005553d0, S 00547430, S 00532480 | `DepositProperty::ctor`, `TreeTypesContains`, `CountChainStages` | deposits |
| S 005552a0 | `DepositProperty::GetGoodProperty` | good record of `dp_setGood` (+0x3c); the wood test of `NMovie::Working::Start` S 0077eda0 |
| S 007778f0 | `NMovie::MoveToDeposit::Update` | reader of `elevationSize` (+0x50) |
| S 00553070 | `Global552c30_GetFieldBC` | on a `BuildingProperty`: `miningGood` (+0xbc) of the product slot 0 good; the fisher's resource type without a field connection |
| S 005477e0, S 0077bb30 | `PropertiesDb::PickRandomDepositForPattern`, `Afforest_PickRandomDepositForCell` | random tree type for a cell |
| S 00555c00, S 00555970, S 005558a0 | `ai::properties::PatternProperty::ctor`, `DoodadProperty::ctor`, `RemainsProperty::ctor` | defaults |
| S 00555190, S 00554f50, S 00554fe0, S 00555070 | `AnimalProperty::ctor`, `HasStackGood`, `GetStackGoodCount`, `GetStackGood` | animals |
| S 005574f0, S 00556d70, S 00556cb0 | `ai::properties::SignDoodadTable::Add`, `GetDoodadId`, `Props_SignDoodadList_LookupByAmount` | sign table |
| S 005567e0, S 005568d0, S 00556540, S 005565e0 | `SacrificeProperty::ctor`, `AddEffect`, `HasEffectType`, `GetGiveGoodsEffectGoodId` | sacrifices |
| S 0054f520 | `LuaProps_sf_addCost` | cost entry plus registration in the sacrifice good's group |
| S 00663560, S 006630b0, S 006631e0 | `SacrificeModifiers::ApplyEffectList`, `ApplyOwnEffect`, `ApplyHostileEffect` | modifier effects (reader of the effect list) |
| S 00662fb0, S 00661ec0, S 00663630 | `SacrificePlayerTable::RecomputeModifiers`, `SacrificePlayerData::ApplySacrificesToAllPlayers`, `SacrificeModifiers::ApplySacrifice` | reset of the eight tables and re-application of every running sacrifice to its target |
| S 006634f0, S 00663530 | `ai::logic::SacrificeModifiers::Init`, `Slot_InitFloatDefaults` | neutral values of a table |
| S 00663310, S 00663370, S 00663610, S 006632b0, S 00663390, S 006633b0, S 006633d0, S 00663430, S 006632d0, S 00663440, S 006633f0, S 00663450, S 00663410, S 006634d0 | readers of the modifier table | effect types 1 to 14 in the order of §3.9; types 1 and 8 share the first, type 3 has two (S 00663610, S 006632b0) |
| S 00661bd0, S 00572de0 | `SacrificeModifierQuery::ScaleCatapultDamage`, `MilitaryProjectile::SetSourceCatapult` | owner-table wrapper of the `BuildingArmor` reader; copies `catapultDamage` into the projectile |
| S 0052b8d0 | `NLogic::MapInfo::Reset` | default state of a map description; leaves the sacrifice list empty (§7) |
| S 005615e0 | `ai::village::VillageSacrifice::Start` | fixes the target player of a starting sacrifice |
| S 00660960, S 00660500 | `ai::logic::Sacrifice::UpdateTimedEffects`, `Sacrifice::ApplyEffect` | one-shot effects |
| S 00555e80, S 00555d60 | `AiProperty::ctor`, `GetFavoriteSacrificeWeight` | AI profiles |
| S 00581c40, S 005b2660 | `NAI::System::ActivatePlayer`, `GameScript_Lua_ai_enable` | pass the profile key to `NAI::Player::Activate` |
| S 00675610 | `ConstructionMap_ComputeCellFlags` | cell side of the size mask |
| S 005390e0 | `NLogic::SpawnResource::Spawn` | reader of a type-0 spawn point type |
| S 00554900 | `HarbourProperty::ctor` | harbour defaults |
| S 00555a80 | `SoundProperty::ctor` | sound defaults |
| S 00556950, S 00556a20, S 00556ae0, S 00556bb0 | `StaticAccess::GetNth…` | n-th pattern / building / deposit / doodad in table order |
| S 00556910 .. S 00556940 | `NProperties::StaticAccess::GetIndirect04_30` / `_08` / `_14` / `_48` | record counts of the same four tables |
| S 0054a4d0 .. S 00550df0 | `LuaProps_*` | the bindings; one per key, listed in [../lua-surface.md](../lua-surface.md) §3.3 |
