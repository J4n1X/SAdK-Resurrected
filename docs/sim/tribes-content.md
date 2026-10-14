# Game content overview: tribes, buildings, goods and production chains

The filled-in picture of the game's rule data: what the three tribes own, what every good is made from, what
every building costs, employs, consumes and produces, and how the chains fit together.

- Binary: `sadk_noav.exe` (base `0x400000`). `S 00xxxxxx` is a static address and only evidence.
- Data: the property scripts in `data/game/scripts/properties/` of the install (encrypted; read with
  `tools/sadk_crypt.py`). Every value in this document is quoted from the named script and key. The remake
  reads these scripts from the player's install; the tables here are a reference for checking a converter and
  for understanding the design, not a substitute for the data.
- Tags: **[known]** = read directly at an address or in a named data file and key; **[inferred]** = one step of
  reasoning from what is visible; **[TODO]** = open. Nothing here was observed in the running game.
- **Data dictionary**: [properties-data.md](properties-data.md) defines every record type, field, default and
  Lua key (`gp_*`, `bp_*`, `tp_*`, `sf_*`, `mi_*`, `sh_*`, `an_*`). Field definitions are not repeated here.
- How the simulation uses the values: [village-buildings.md](village-buildings.md) (construction, production
  cycle, mines, storage), [settlers-jobs.md](settlers-jobs.md) (working modes, worker actions, tools),
  [military.md](military.md) (soldiers, barracks, catapults, territory), [navy.md](navy.md) (ships),
  [map-resources.md](map-resources.md) (deposits, animals, underground resources, geologist),
  [streets-transport.md](streets-transport.md) (carriers, transport ranks), [players-victory.md](players-victory.md)
  (start stock, locks), [ai-player.md](ai-player.md) (the AI's use of the same records),
  [game-commands.md](game-commands.md) (the lockstep commands), [lua-runtime.md](lua-runtime.md) (how the
  scripts are run).
- Time unit: the **logic tick**, 10 per second at game speed 1 ([logic-core.md](logic-core.md) §3.1).
  Distances are hex distances in cells.

---

## 1. Purpose and scope

This document answers "what is in the game": the content that the property database holds after start-up, as
far as the economy and the military are concerned.

Covered: the three tribes and their differences; every good with its id, kind and recipe; every building type
of every tribe with size class, construction cost, worker, inputs, outputs and cycle times; the production
chains as a text graph; settler professions and the tool models they carry; soldier ranks; ships; sacrifices;
the tribe-specific buildings and mechanics; the records that exist in the data but are not reachable.

Not covered: the meaning of the record fields ([properties-data.md](properties-data.md)); the algorithms that
consume them (the sibling documents listed above); map objects (deposits, patterns, doodads, remains, spawn
points: [map-resources.md](map-resources.md)); the AI profiles (`ai.lua`: [ai-player.md](ai-player.md)); sounds;
graphics definitions that share names with the records (`settings/buildings.xml`, `ships.xml`,
`character/settler_config.xml`: [../asset-formats.md](../asset-formats.md), [../data-loading.md](../data-loading.md)).

---

## 2. Data model

### 2.1 Sources, names and how to read the tables

[known: data] The content is built by 22 Lua scripts that call the `properties.*` bindings. `data.lua` runs them
in this order: `defineTribes`, `doodads`, `goods`, `config`, `patterns`, `animals`, `jobs`, `deposits`,
`remains`, `buildings`, `sacrifices` (which runs `sacrifices_goodExchange` and `sacrifices_campaign` first),
`signs`, `military`, `ship`, `sounds`, `ai`, `harbors`, `tribes`, `spawnpoints`. The files on disk are
`Goods.lua` and `Jobs.lua`; `data.lua` asks for `goods` and `jobs` [inferred: the file lookup is
case-insensitive, as on the game's platform].

Record totals [known: data]: 3 tribes, 176 goods (100 in `Goods.lua`, 76 settler goods in `Jobs.lua`),
104 building types, 77 sacrifices, 12 animals, 8 harbour orientations.

Conventions of the tables below:

- The **Lua name** is the script's global variable that holds the record id (`stoneBav =
  properties.gp_create("733f1e03")`). It is the only unique human-readable handle: the record's own `name` string
  (`gp_setName`, `bp_setName`) is shared between tribe variants (`stone`, `stoneBav` and `stoneScots` are all
  named `"Stone"`). The **id** is the 32-bit number that maps, saves and the code use
  ([properties-data.md](properties-data.md) §2.2).
- Tribe variants are separate records. The suffix tells the tribe, but not uniformly [known: data]:
  - goods: no suffix = Egyptian or shared, `…Bav` = Bavarian, `…Scots` = Scottish;
  - buildings: no suffix = **Scottish** or shared (`woodCutter`, `mill`, `tower`), `…Bav` = Bavarian,
    `…Clay` / `…Egypt` = Egyptian; a few have a name of their own (`fisher`, `hunter`, `spring` are Bavarian,
    `fisher2`, `hunterScots`, `springScots` Scottish);
  - settler goods: no suffix = Egyptian, `…Bav`, `…Scots`.
  What belongs to a tribe is decided only by the tribe's lists (`tp_addGood`, `tp_addJob`, `tp_addBuilding`),
  never by the name.
- A **recipe** is the `gp_addCost` list of a good: the inputs consumed per production cycle of the building
  whose first product (`bp_setGoods`) is that good. The building, not the recipe, sets how many units one cycle
  yields ([village-buildings.md](village-buildings.md) §3.7).
- Amounts are units of goods. Times are logic ticks.
- **Tracing a number.** All files are in `data/game/scripts/properties/`. Every table below has a **Source**
  line that names, per column or row, the script and the `properties.*` call the value is the argument of; the
  record is the call's first argument (for `tp_*`, `mi_*`, `sh_*` the tribe), found by the Lua name of the
  row. A column marked *derived* is not a single call: the Source line says which lists were joined. The
  binder behind each call (the reading function) is listed per key in
  [properties-data.md](properties-data.md) §2; the binders are registered by the functions of §11.

### 2.2 The three tribes

[known: `defineTribes.lua`, `tribes.lua`, `military.lua`, `ship.lua`, `buildings.lua`]

Source, per row: id = argument of `tp_create` (`defineTribes.lua`); rows that name a `tp_*` call = that call in
`tribes.lua`; ware, settler-good and building counts = number of `tp_addGood` / `tp_addJob` / `tp_addBuilding`
calls for the tribe (`tribes.lua`); size split, building materials, garrison and health = *derived*: the tribe's
`tp_addBuilding` list joined with `bp_setSize`, `bp_addFrameCost` / `bp_addCost`, `bp_setSoldierLimit` and
`bp_setHealth` of each listed type (`buildings.lua`); soldier levels = the `mi_setSoldierId(tribe, kind, level,
good)` calls (`military.lua`); ship speed and expedition building = `sh_setSpeed`, `sh_setExpeditionBuilding`
(`ship.lua`); sacrifices listed / offered = number of `tp_addSacrifice` / `tp_addAllowedSacrifice` calls
(`tribes.lua`); build menu texture = `tp_setBuildingsTextureName`, `tp_setMenuX` (`tribes.lua`).

| | Bavarians | Egyptians | Scots |
|---|---|---|---|
| Lua name, id | `bavarians` `b0d378a3` | `egyptians` `f5016d33` | `scots` `497ffda3` |
| `tp_setName` | `"Bavarian"` | `"Egyptian"` | `"Scots"` |
| Wares (`tp_addGood`) | 26 | 26 | 26 |
| Settler goods (`tp_addJob`) | 7: `good_oxen`, 3 halberd ranks, 3 crossbow ranks | 4: 1 sword rank, 3 bow ranks | 5: 3 claymore ranks, 2 sling ranks |
| Building types (`tp_addBuilding`) | 37 | 35 | 37 |
| of these Small / Mine / Medium / Large / Ship | 8 / 6 / 12 / 6 / 1 | 7 / 6 / 12 / 5 / 1 | 9 / 6 / 13 / 4 / 1 |
| plus military plots Small / Medium / Large | guard house / tower / fortress | the same | the same |
| plus | `constructionBav` (size 0) | `constructionClay` (size 0) | `construction` (size 0) |
| Building materials | `plank`, `stoneBav` | `clay`, `stone` | `plank`, `stoneScots` |
| `tp_setConstructionGoodId` | `constructionResourcesBav` | `constructionResourcesClay` | `constructionResources` |
| Tool (`tp_setWorkerToolGoodId`) | `toolBav` | `tool` | `toolScots` |
| Coin (`tp_setSoldierUpgradeGoodId`) | `coinBav` | `coin` | `coinScots` |
| Builder (`tp_setConstructor`) | `good_constructorBav` | `good_constructor` | `good_constructorScots` |
| Second carrier (`tp_setSecondCarrierId`) | `good_oxen` (costs 1 `oxen`) | `good_helper` (no cost) | not set |
| Melee soldier, levels | halberd 0..2 | sword 0 | claymore 0..2 |
| Ranged soldier, levels | crossbow 0..2 | bow 0..2 | sling 0..1 |
| Garrison guard house / tower / fortress | 3 / 6 / 9 | 4 / 8 / 12 | 2 / 4 / 6 |
| Health guard house / tower / fortress | 60 / 80 / 100 | 80 / 100 / 120 | 60 / 80 / 100 |
| Ship speed (`sh_setSpeed`) | 0.06 | 0.09 | 0.12 |
| Expedition building | `guardHouseBav` | `guardHouseClay` | `guardHouse` |
| Sacrifices listed / offered by default | 23 / 7 | 24 / 8 | 22 / 7 |
| Build menu texture, `tp_setMenuX` | `uiBuildings0`, 16 | `uiBuildings1`, 184 | `uiBuildings2`, 352 |

Shared by all three tribes [known: `tribes.lua`]: the goods `wood`, `water`, `weapons`, `sacrificeGood`,
`sacrificeGoodOlympicFlame`, and the buildings `castle` (the headquarters) and `sacrificeOlympicFlame`.
Bavarians and Scots also share `plank`, `corn`, `flour` and the building `shipBuilding`.

### 2.3 Goods

Columns: **Kind** is `gp_setType` (ware = 0, the default; ware group = 2; either group = 3). **Made in** and
**Input of** list the tribe's buildings whose first or second product is the good, or whose first product's
recipe names it. **Rank** is the default transport rank for this tribe (`gp_setTransportPriority`; a lower rank
is carried first, [streets-transport.md](streets-transport.md)). **Group** is `gp_setArrangementGoodId`: the
good under which this one is listed in the goods-distribution panel; `foodBav` and `foodScots` name themselves,
the Egyptian `food` does not call the setter. Rows are in `tp_addGood` order, which is also the order in which
the members of a group are enumerated ([properties-data.md](properties-data.md) §3.4; `PropertyGroupIter::Init`
S 007767c0 walks the tribe's goods vector and keeps the goods with a positive amount in the group's cost list
[known]).

Source of §2.3.1 to §2.3.3, per column: **Id** = argument of `gp_create`; **Kind** = `gp_setType`; **Recipe**
= the good's `gp_addCost(good, input, amount)` calls; **Rank** = `gp_setTransportPriority(good, tribe, rank)`
for the table's tribe; **Group** = `gp_setArrangementGoodId(good, group)` (all `Goods.lua`). Row set and order
= the tribe's `tp_addGood` calls (`tribes.lua`). **Made in** and **Input of** are *derived* from three files:
the tribe's `tp_addBuilding` list (`tribes.lua`), each listed type's `bp_setGoods` / `bp_setSecondGoods`
(`buildings.lua`) and the recipe (`gp_addCost`, `Goods.lua`) of that type's first product.

#### 2.3.1 Bavarians [known: `Goods.lua`, `tribes.lua`, `buildings.lua`]

| Good (Lua name) | Id | Kind | Recipe per unit (`gp_addCost`) | Made in | Input of | Rank | Group |
|---|---|---|---|---|---|---|---|
| `toolBav` | `376a3403` | ware | plank 1, ironBav 1 | locksmitheryBav | – | 12 | – |
| `wood` | `cd6ec133` | ware | – | woodCutterBav | sawMillBav, crossbowSmithery, mintBav | 7 | – |
| `weapons` | `0897d1e3` | ware group | – | – | – | 13 | – |
| `foodBav` | `88c0ce93` | either group | fishBav 1, pretzel 1, fleshham 1 | – | ironMineBav, coalMineBav | 5 | foodBav |
| `plank` | `c5c945a3` | ware | wood 1 | sawMillBav | locksmitheryBav, shipBuilding | 3 | – |
| `stoneBav` | `733f1e03` | ware | foodStoneBav 1 | stonePitBav, stoneMineBav | catapultBav | 4 | – |
| `corn` | `17626a03` | ware | – | farmBav | millBav, brauhaus, sauerey | 6 | – |
| `flour` | `e70c72d3` | ware | corn 1 | millBav | bakerypretzel | 8 | – |
| `fishBav` | `15af3083` | ware | – | fisher | saltMineBav | 5 | foodBav |
| `fleshham` | `b48f235d` | ware | weissbeer 1, corn 1 | sauerey | – | 5 | foodBav |
| `pretzel` | `0e3f885d` | ware | saltBav 1, flour 1 | bakerypretzel | – | 5 | foodBav |
| `water` | `a9676263` | ware | – | spring | brauhaus, oxenBreeding | 11 | – |
| `weissbeer` | `959817bd` | ware | water 1, corn 1 | brauhaus | casernHalCross, sauerey | 9 | – |
| `coalBav` | `1d309103` | ware | foodBav 1 | coalMineBav | smelteryBav, halberdSmithy | 15 | – |
| `ironBav` | `58b88923` | ware | ironOreBav 1, coalBav 1 | smelteryBav | locksmitheryBav, halberdSmithy | 14 | – |
| `goldBav` | `de8affb3` | ware | foodGoldBav 2 | goldMineBav | mintBav | 2 | – |
| `coinBav` | `bc28a923` | ware | goldBav 1, wood 1 | mintBav | casernHalCross | 1 | – |
| `halberd` | `ba4503d3` | ware | ironBav 1, coalBav 1 | halberdSmithy | casernHalCross | 13 | – |
| `ironOreBav` | `1a4db6e3` | ware | foodBav 1 | ironMineBav | smelteryBav | 16 | – |
| `oxen` | `37e17d3d` | ware | water 1 | oxenBreeding | – | 18 | – |
| `crossbow` | `c0ec9073` | ware | wood 1, leather 1 | crossbowSmithery | casernHalCross | 13 | – |
| `sacrificeGood` | `a28e592c` | ware group | – | sacrificeBav | – | 1 | – |
| `sacrificeGoodOlympicFlame` | `a40ae6d3` | ware group | wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1 | sacrificeOlympicFlame | – | 1 | sacrificeGood |
| `leather` | `785adec1` | ware | – | hunter | crossbowSmithery | 17 | – |
| `gemstonesBav` | `d8021b93` | ware | foodGoldBav 3 | gemMineBav | – | 0 | – |
| `saltBav` | `550fed33` | ware | fishBav 1 | saltMineBav | bakerypretzel | 10 | – |

#### 2.3.2 Egyptians [known: `Goods.lua`, `tribes.lua`, `buildings.lua`]

| Good (Lua name) | Id | Kind | Recipe per unit (`gp_addCost`) | Made in | Input of | Rank | Group |
|---|---|---|---|---|---|---|---|
| `tool` | `7559c5a4` | ware | wood 1, iron 1 | locksmitheryClay | – | 11 | – |
| `wood` | `cd6ec133` | ware | – | woodCutterClay | locksmitheryClay, bowSmithery, shipBuildingEgypt | 15 | – |
| `weapons` | `0897d1e3` | ware group | – | – | – | 12 | – |
| `food` | `65cd3afe` | either group | cornBread 1, cheese 1, fish 1, goatHam 1 | – | – | 6 | – |
| `clay` | `036f4843` | ware | water 1 | brickyard | – | 3 | – |
| `stone` | `55e952d3` | ware | foodStoneEgypt 2 | stonePitClay, stoneMineClay | catapultClay | 4 | – |
| `goat` | `bb5d0683` | ware | – | goatBreeder | tanneryClay | 10 | – |
| `egyptCorn` | `4a852f49` | ware | water 1 | farmClay | bakeryClay | 9 | – |
| `fish` | `4012e5a3` | ware | – | fisherClay | – | 6 | food |
| `milk` | `be427cd3` | ware | – | goatBreeder | bakeryClay, cheeseDairyClay, casernSwordBow | 7 | – |
| `cheese` | `3df86983` | ware | milk 1, salt 1 | cheeseDairyClay | coalMineClay | 6 | food |
| `goatHam` | `ad0d6c63` | ware | – | hunterClay | – | 6 | food |
| `cornBread` | `9e254203` | ware | milk 1, egyptCorn 1 | bakeryClay | – | 6 | food |
| `water` | `a9676263` | ware | – | springClay | brickyard, farmClay | 5 | – |
| `coal` | `7068dcd3` | ware | cheese 1 | coalMineClay | mintClay | 17 | – |
| `iron` | `8198bf23` | ware | ironOre 1 | smelteryClay | locksmitheryClay, smithyClay | 13 | – |
| `gold` | `4f41c633` | ware | foodGoldEgypt 2 | goldMineClay | mintClay | 2 | – |
| `coin` | `499d4c63` | ware | gold 1, coal 1 | mintClay | casernSwordBow | 1 | – |
| `sword` | `a8483903` | ware | iron 1 | smithyClay | casernSwordBow | 12 | – |
| `ironOre` | `ec5020be` | ware | foodIronOreEgypt 1 | ironMineClay | smelteryClay | 14 | – |
| `bow` | `9a02b8a5` | ware | wood 1, goatLeather 1 | bowSmithery | casernSwordBow | 12 | – |
| `goatLeather` | `8e61ed03` | ware | goat 1, salt 1 | tanneryClay | bowSmithery | 16 | – |
| `sacrificeGood` | `a28e592c` | ware group | – | sacrificeClay | – | 1 | – |
| `sacrificeGoodOlympicFlame` | `a40ae6d3` | ware group | wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1 | sacrificeOlympicFlame | – | 1 | sacrificeGood |
| `gemstones` | `cb98c903` | ware | foodGemstonesEgypt 4 | gemMineClay | – | 0 | – |
| `salt` | `09d2d623` | ware | foodSaltEgypt 1 | saltMineClay | tanneryClay, cheeseDairyClay | 8 | – |

#### 2.3.3 Scots [known: `Goods.lua`, `tribes.lua`, `buildings.lua`]

| Good (Lua name) | Id | Kind | Recipe per unit (`gp_addCost`) | Made in | Input of | Rank | Group |
|---|---|---|---|---|---|---|---|
| `toolScots` | `c2cd5ce3` | ware | wood 1, ironScots 1 | locksmithery | – | 12 | – |
| `wood` | `cd6ec133` | ware | – | woodCutter | sawMill, locksmithery | 7 | – |
| `weapons` | `0897d1e3` | ware group | – | – | – | 13 | – |
| `foodScots` | `ff351463` | either group | fishScots 1, bread 1, sheepHam 1 | – | coalMine | 5 | foodScots |
| `plank` | `c5c945a3` | ware | wood 1 | sawMill | shipBuilding | 3 | – |
| `stoneScots` | `409ed753` | ware | bread 1 | stonePit, stoneMine | casernClayStone, catapult | 4 | – |
| `sheep` | `70dd29e3` | ware | sheepAnimal 1 | hunterScots | kiltSewing, sheepButcher | 10 | – |
| `sheepAnimal` | `feff5df3` | ware group | water 1 | sheepBreeding | hunterScots | 4 | – |
| `kilt` | `7d610a43` | ware | sheep 1 | kiltSewing | casernClayStone | 18 | – |
| `corn` | `17626a03` | ware | – | farm | mill, bakery, whiskyBrewery | 6 | – |
| `flour` | `e70c72d3` | ware | corn 1 | mill | bakery | 9 | – |
| `fishScots` | `5fa2d953` | ware | – | fisher2 | ironMine | 5 | foodScots |
| `sheepHam` | `ca724c43` | ware | sheep 1, saltScots 1 | sheepButcher | goldMine | 5 | foodScots |
| `bread` | `90ab8923` | ware | flour 1, corn 1 | bakery | stonePit, stoneMine | 5 | foodScots |
| `water` | `a9676263` | ware | – | springScots | sheepBreeding, whiskyBrewery | 8 | – |
| `whisky` | `e4e38e83` | ware | water 1, corn 1 | whiskyBrewery | casernClayStone | 17 | – |
| `coalScots` | `9d676ab3` | ware | foodScots 1 | coalMine | smeltery, claymoreSmithy, mint | 15 | – |
| `ironScots` | `e0b386e3` | ware | ironOreScots 1, coalScots 1 | smeltery | locksmithery, claymoreSmithy | 14 | – |
| `goldScots` | `ef032103` | ware | sheepHam 1 | goldMine | mint | 2 | – |
| `coinScots` | `db0c7b23` | ware | goldScots 1, coalScots 1 | mint | casernClayStone | 1 | – |
| `claymore` | `111b6ba3` | ware | ironScots 1, coalScots 1 | claymoreSmithy | casernClayStone | 13 | – |
| `ironOreScots` | `aab683f3` | ware | fishScots 1 | ironMine | smeltery | 16 | – |
| `sacrificeGood` | `a28e592c` | ware group | – | sacrifice | – | 1 | – |
| `sacrificeGoodOlympicFlame` | `a40ae6d3` | ware group | wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1 | sacrificeOlympicFlame | – | 1 | sacrificeGood |
| `gemstonesScots` | `5afd26e3` | ware | foodGemstonesScots 3 | gemMine | – | 0 | – |
| `saltScots` | `a40ef753` | ware | foodSaltScots 1 | saltMine | sheepButcher | 11 | – |

Notes on the three tables [known: data unless tagged]:

- **Input of** lists direct recipe entries only, and leaves out the `construction*` dummy types and the
  Olympic flame. A food good is also eaten by every mine whose recipe names a group it belongs to (§3.4); goods
  used for construction, for settlers and soldiers and by the temple are shown in the graphs of §3.3.
- The stone pits list a recipe (`stoneBav` costs `foodStoneBav`, `stone` costs `foodStoneEgypt`, `stoneScots`
  costs `bread`) but have `bp_setIgnoreGoodCosts` and working mode 1, so they request and consume nothing; the
  recipe applies to the stone **mines** only (§3.4).
- `weapons` is a ware group without members in every tribe list. No script adds a cost to it and no building
  produces or consumes it. [TODO] not established: whether any code reads it (a search for the id `0897d1e3` in
  the function cache found no use; the goods panels of the UI were not read for it).
- `sacrificeGood` is listed without a recipe, but the engine fills its cost list while the sacrifices are
  defined: the binding `sf_addCost` S 0054f520 adds every good it is given, with amount 1, to the cost list of
  the good named by `cfg_setSacrificeGoodId`, and after it that good's `gp_setArrangementGoodId` value when it
  differs from the good itself [known; the details are in [properties-data.md](properties-data.md) §3.2].
- `sacrificeGoodOlympicFlame` has one cost list for all tribes that mixes tribe goods: `wood`, `coinBav`,
  `oxen`, `goat`, `gold`, `halberd`, 1 each.
- `sheepAnimal` (Scots) is a ware group whose recipe is `water` 1: it is the product slot of the sheep breeder
  and never leaves the building as a ware (§3.6).

#### 2.3.4 The same role in the three tribes [known: data]

Source: *derived*, a regrouping of the rows of §2.3.1 to §2.3.3 and §2.4.1 to §2.4.3. "X = a + b" is the
`gp_addCost` list of X (`Goods.lua`); "n per harvest / catch / cycle" is the amount argument of the producing
building's `bp_setGoods(building, good, amount)` (`buildings.lua`); "tribe order" is `tp_addGood` order
(`tribes.lua`); tool, coin and builder are `tp_setWorkerToolGoodId`, `tp_setSoldierUpgradeGoodId`,
`tp_setConstructor` (`tribes.lua`); the recruit costs are the `gp_addCost` lists of the level-0 soldier goods
(`Jobs.lua`).

| Role | Bavarians | Egyptians | Scots |
|---|---|---|---|
| Tool (one per worker) | `toolBav` = plank + ironBav | `tool` = wood + iron | `toolScots` = wood + ironScots |
| Building material 1 | `plank` = wood | `clay` = water | `plank` = wood |
| Building material 2 | `stoneBav` | `stone` | `stoneScots` |
| Grain | `corn`, 2 per harvest | `egyptCorn`, 1 per harvest, 1 water per sowing | `corn`, 1 per harvest |
| Flour | `flour` = corn | none | `flour` = corn |
| Fish | `fishBav`, 1 per catch | `fish`, 1 per catch | `fishScots`, 2 per catch |
| Baked food | `pretzel` = saltBav + flour, 2 per cycle | `cornBread` = milk + egyptCorn | `bread` = flour + corn |
| Further food | `fleshham` = weissbeer + corn | `cheese` = milk + salt; `goatHam` (hunting) | `sheepHam` = sheep + saltScots |
| Food group, members in tribe order | `foodBav`: fishBav, fleshham, pretzel | `food`: fish, cheese, goatHam, cornBread | `foodScots`: fishScots, sheepHam, bread |
| Soldier's drink | `weissbeer` = water + corn, 2 per cycle | `milk` (goat breeder) | `whisky` = water + corn |
| Soldier's clothing | none | none | `kilt` = sheep |
| Animal goods | `oxen` = water; `leather` (hunting) | `goat` (goat breeder); `goatLeather` = goat + salt | `sheep` (herding) |
| Iron | `ironBav` = ironOreBav + coalBav | `iron` = ironOre | `ironScots` = ironOreScots + coalScots |
| Coin | `coinBav` = goldBav + **wood** | `coin` = gold + coal | `coinScots` = goldScots + coalScots |
| Melee weapon | `halberd` = ironBav + coalBav | `sword` = iron | `claymore` = ironScots + coalScots |
| Ranged weapon | `crossbow` = wood + leather | `bow` = wood + goatLeather | none: 3 `stoneScots` per slinger |
| Underground goods | `ironOreBav`, `coalBav`, `goldBav`, `gemstonesBav`, `saltBav`, `stoneBav` | `ironOre`, `coal`, `gold`, `gemstones`, `salt`, `stone` | `ironOreScots`, `coalScots`, `goldScots`, `gemstonesScots`, `saltScots`, `stoneScots` |

Each Bavarian and Scottish underground good and fish names the Egyptian (neutral) good as its
`gp_setMiningGood`; that neutral id is what a map stores as the resource of a cell
([properties-data.md](properties-data.md) §3.7, [map-resources.md](map-resources.md)). The neutral goods
(`stone`, `gemstones`, `coal`, `salt`, `ironOre`, `gold`, `fish`) and `wood`, `corn` and `egyptCorn` name
themselves. No other good calls the setter (24 calls in `Goods.lua`).

#### 2.3.5 Goods outside the tribe lists [known: `Goods.lua`]

Source: ids = `gp_create`, kind = `gp_setType`, content = `gp_addCost`, all `Goods.lua`; "outside the tribe
lists" = no `tp_addGood` call names the good (`tribes.lua`); the roles that name a tribe or building setter
(`tp_setConstructionGoodId`, `bp_setGoods`, `gp_setGfxGoodId`) are those calls in `tribes.lua`, `buildings.lua`
and `Jobs.lua`.

| Goods | Ids | Kind | Content | Role |
|---|---|---|---|---|
| `gripper`, `axe`, `crook`, `saw`, `hammer`, `shovel`, `pot`, `fishingRod`, `scythe`, `pickaxe`, `rollingPin`, `spear`, `hatchet` | `6cc2d2d3`, `e1281613`, `2b259543`, `3788ffc3`, `69c15033`, `67c04e73`, `ed76ae73`, `f3f3dcc3`, `1ceacd43`, `45d899e3`, `c2049323`, `79f34393`, `f2b7453e` | ware group, no members | rank 0 for all tribes | carried models of the professions (`gp_setGfxGoodId`, §2.5). They are never produced, stored or transported; `gripper` is not referenced by any record |
| `sling` | `5b5288a3` | ware (default) | only a name | carried model of the Scottish slingers. It has **no** transport rank and no AI weight for any tribe, so it must never be queried as a ware ([properties-data.md](properties-data.md) §2.4: a missing key is fatal) |
| `foodGoldBav`, `foodStoneBav` | `a1e67023`, `b78bbb13` | either group | pretzel, fleshham / fishBav, pretzel | restricted food of the Bavarian gold and gemstone mines / stone mine |
| `foodStoneEgypt`, `foodSaltEgypt`, `foodGoldEgypt`, `foodIronOreEgypt`, `foodGemstonesEgypt` | `ed97f323`, `885301c3`, `fcd6ed83`, `c214b733`, `19d40e83` | either group | fish, cheese / cornBread, goatHam / cornBread, cheese / fish, goatHam / fish, cheese | restricted food of the Egyptian mines |
| `foodSaltScots`, `foodGemstonesScots` | `b9061e13`, `c055ff03` | either group | fishScots, bread / sheepHam, bread | restricted food of the Scottish salt and gemstone mines. All nine restricted food groups are ranked for their own tribe only (5 for Bavarians and Scots, 6 for Egyptians) and name the tribe's food good (`foodBav`, `food`, `foodScots`) as `gp_setArrangementGoodId` |
| `constructionResourcesBav`, `constructionResourcesClay`, `constructionResources` | `58c225f3`, `e80de5e3`, `0d45f393` | ware group | plank + stoneBav / clay + stone / plank + stoneScots | the tribe's construction goods (`tp_setConstructionGoodId`) and product slot of the `construction*` dummy building |
| `casernGoodHalCross`, `casernGood`, `casernGoodClayStone` | `d4873cd3`, `74a02ce4`, `d31cf3a3` | ware group | weissbeer, halberd, crossbow, coinBav / milk, sword, bow, coin / whisky, claymore, stoneScots, kilt, coinScots (1 each) | product slot of the barracks: the list of goods a barracks takes. The amounts are not the training cost; that is the soldier good's own cost (§2.6) |
| `catapultStoneBav`, `catapultStone`, `catapultStoneScots` | `53de4a13`, `ff368353`, `57387463` | ware group | 1 stone of the tribe | product slot of the catapult. The ammunition is the **first good of this cost list**, the tribe's stone: `Catapult::Fire` S 005678b0 removes one unit of it from the input stock and requests another, except while the game-wide cinematic flag is set (then the shot is free) [known]. The slot good itself is never created [inferred: working mode 5 has no product delivery] ([military.md](military.md) §3.10) |
| `ship`, `shipEgyptCosts` | `1d66b4ae`, `65a7cc73` | ware group | plank 12 / wood 12 | product slot of the ship-building sites; `ship` is ranked for Bavarians and Scots only, `shipEgyptCosts` for Egyptians only |
| `boat` | `f63de553` | ware group | plank 1 | not referenced by any other record; the id does not occur in the image and the code has no string `Boat`; `settings/items.xml` names the good (`good = "Boat"`) (§5) |

### 2.4 Buildings

Columns of the economy tables: **Size** is the plot class (`bp_setSize`; the mask values and the placement test
are in [properties-data.md](properties-data.md) §3.6). **Frame cost + cost** are the two material lists of the
two construction phases (`bp_addFrameCost`, `bp_addCost`). **Worker** is the profession employed; one worker
unless a limit is given. **Mode** is `bp_setWorkingMode` (6 when the script does not set it). **Output per
cycle** is `bp_setGoods` (and `bp_setSecondGoods`). **Input per cycle** is the recipe of the first product; it is
in parentheses when the type has `bp_setIgnoreGoodCosts`, which means the building does not request it through
the production rules (§3.1 says what applies instead). **Work / rest ticks** are `bp_setProductionTime` and
`bp_setRestTime`. **Radius** is `bp_setWorkingRadius`. **Stock limit** is `bp_setStockLimit`, the number of
units of each input kept in the building. **Weight** is `bp_setArrangementValue`, the default share in the goods
distribution. "–" means the script does not call the setter (defaults: radius 4, stock limit -1, weight -1.0,
times 0, working mode 6, worker limit 1 [known: `BuildingProperty` ctor S 00553cf0]). Rows are in
`tp_addBuilding` order, which is the order of the build menu and of the producer search.

Source of §2.4.1 to §2.4.3, per column (all `buildings.lua` unless noted): **Id** = argument of `bp_create`;
**`name`** = `bp_setName`; **Size** = `bp_setSize`; **Frame cost + cost** = `bp_addFrameCost`, `bp_addCost`;
**Worker** = `bp_setWorker` (the good is defined in `Jobs.lua`), "limit n" = `bp_setWorkerLimit`; **Mode** =
`bp_setWorkingMode`; **Output per cycle** = `bp_setGoods(building, good, amount)`, `bp_setSecondGoods`;
**Input per cycle** = *derived*: the `gp_addCost` list (`Goods.lua`) of the first `bp_setGoods` good, in
parentheses when `bp_setIgnoreGoodCosts` is called; **Work / rest ticks** = `bp_setProductionTime`,
`bp_setRestTime`; **Radius** = `bp_setWorkingRadius`; **Stock limit** = `bp_setStockLimit`; **Weight** =
`bp_setArrangementValue`. Row set and order = the tribe's `tp_addBuilding` calls (`tribes.lua`).

#### 2.4.1 Bavarians: economy [known: `buildings.lua`, `tribes.lua`]

| Building (Lua name) | Id | `name` | Size | Frame cost + cost | Worker | Mode | Output per cycle | Input per cycle | Work / rest ticks | Radius | Stock limit | Weight |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `woodCutterBav` | `88928533` | WoodcutterHut | Small | plank 1 + plank 1 | good_woodcutterBav | 1 Mining | wood 1 | – | 55 / 222 | 6 | – | – |
| `foresterBav` | `4eb22743` | ForesterHouse | Small | plank 1 + plank 1 | good_foresterBav | 0 Foresting | – | – | 55 / 222 | 6 | – | – |
| `stonePitBav` | `16d2cb13` | Stone Pit | Small | plank 1 + plank 1 | good_minerBav | 1 Mining | stoneBav 1 | (foodStoneBav 1) | 55 / 55 | 8 | – | – |
| `fisher` | `3ef3bc43` | FisherHut | Small | plank 1 + plank 1 | good_fisherBav | 3 Fishing | fishBav 1 | – | 333 / 770 | 8 | – | – |
| `hunter` | `3c10e223` | HuntingLodge | Small | plank 1 + plank 1 | good_hunterBav | 7 Hunting | leather 1 | – | 55 / 1500 | 8 | – | – |
| `spring` | `c2c7c303` | Spring | Small | plank 1 + plank 1 | good_buildingHelperBav | 6 Producing | water 1 | – | 333 / 55 | – | – | – |
| `scholarHutBav` | `7d25c533` | ScholarHut | Small | plank 1 + plank 1 | good_scholarWorkerBav | 11 Scholar | – | – | 333 / 55 | – | – | – |
| `watchTowerBav` | `d54a5fa3` | WatchTower | Small | plank 1 + plank 1 | good_explorerBav | 8 Idling | – | – | – / – | – | – | – |
| `ironMineBav` | `ede4fe73` | Iron Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | ironOreBav 1 | foodBav 1 | 333 / 55 | 3 | 2 | 0.5 |
| `goldMineBav` | `32319b83` | Gold Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | goldBav 1 | foodGoldBav 2 | 333 / 55 | 3 | 2 | 0.5 |
| `coalMineBav` | `b6e77aa3` | Coal Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | coalBav 1 | foodBav 1 | 333 / 55 | 3 | 2 | 0.8 |
| `stoneMineBav` | `fd1670f3` | Stone Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | stoneBav 1 | foodStoneBav 1 | 333 / 55 | 3 | 2 | 0.6 |
| `gemMineBav` | `c2543aa3` | Gemstone Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | gemstonesBav 1 | foodGoldBav 3 | 333 / 55 | 3 | 3 | 0.4 |
| `saltMineBav` | `b7c95303` | Salt Mine | Mine | plank 2 + plank 2 | good_minerBav | 6 Producing | saltBav 1 | fishBav 1 | 333 / 55 | 3 | 2 | 0.8 |
| `sawMillBav` | `c3361303` | Sawmill | Medium | plank 2 + stoneBav 2 | good_cabinetmakerBav | 6 Producing | plank 1 | wood 1 | 333 / 55 | – | 6 | 0.8 |
| `millBav` | `53775aa3` | Mill | Medium | plank 2 + stoneBav 2 | good_millerBav | 6 Producing | flour 1 | corn 1 | 333 / 55 | – | 6 | 0.5 |
| `smelteryBav` | `fdf84953` | Smeltery | Medium | plank 2 + stoneBav 2 | good_smelterBav | 6 Producing | ironBav 1 | ironOreBav 1, coalBav 1 | 333 / 55 | – | 6 | 0.5 |
| `locksmitheryBav` | `85afab13` | Locksmithery | Medium | plank 2 + stoneBav 2 | good_smithBav | 6 Producing | toolBav 1 | plank 1, ironBav 1 | 333 / 55 | – | 6 | 0.4 |
| `halberdSmithy` | `1a242583` | HalberdSmithy | Medium | plank 2 + stoneBav 2 | good_smithBav | 6 Producing | halberd 1 | ironBav 1, coalBav 1 | 333 / 55 | – | 6 | 0.55 |
| `crossbowSmithery` | `986fc903` | CrossBowSmithery | Medium | plank 2 + stoneBav 2 | good_cabinetmakerBav | 6 Producing | crossbow 1 | wood 1, leather 1 | 333 / 55 | – | 6 | 0.6 |
| `bakerypretzel` | `884c42e3` | Bakerypretzel | Medium | plank 2 + stoneBav 2 | good_bakerBav | 6 Producing | pretzel 2 | saltBav 1, flour 1 | 333 / 55 | – | 6 | 0.5 |
| `brauhaus` | `ef26fb5d` | Brauhaus | Medium | plank 2 + stoneBav 2 | good_brewerBav | 6 Producing | weissbeer 2 | water 1, corn 1 | 333 / 55 | – | 6 | 0.7 |
| `mintBav` | `8a5635f3` | Mint | Medium | plank 2 + stoneBav 2 | good_coinerBav | 6 Producing | coinBav 1 | goldBav 1, wood 1 | 333 / 55 | – | 6 | 0.4 |
| `casernHalCross` | `ff1a11b3` | Casern | Medium | plank 3 + stoneBav 2 | good_buildingHelperBav | 4 SettlerBreeding | casernGoodHalCross 1 | (weissbeer 1, halberd 1, crossbow 1, coinBav 1) | 333 / 55 | – | 6 | 0.4 |
| `catapultBav` | `98a5d013` | Catapult | Medium | plank 3 + plank 1, stoneBav 2 | good_buildingHelperBav | 5 Catapult | catapultStoneBav 1 | stoneBav 1 | 25 / 55 | 12 | 4 | 0.4 |
| `farmBav` | `cea2d303` | Farm | Large | plank 3 + stoneBav 3 | good_farmerBav | 2 Farming | corn 2 | – | 83 / 355 | 2 | – | – |
| `sauerey` | `c3d5a18d` | Butcher | Large | plank 3 + stoneBav 3 | good_buildingHelperBav | 6 Producing | fleshham 1 | weissbeer 1, corn 1 | 333 / 55 | – | 6 | 0.55 |
| `oxenBreeding` | `9e80101d` | Oxen Breeding | Large | plank 3 + stoneBav 3 | good_buildingHelperBav | 4 SettlerBreeding | oxen 1 | water 1 | 333 / 55 | – | 6 | 0.3 |
| `sacrificeBav` | `01dba453` | Sacrifice | Large | plank 3 + stoneBav 2 | good_buildingHelperBav | 9 Sacrifice | sacrificeGood 1 | – | – / – | – | – | 0.5 |
| `shipBuilding` | `318d1529` | ShipConstructionSite | Ship | plank 4 + plank 8 | – (limit 0) | 6 Producing | ship 1 | (plank 12) | – / – | 1 | – | 0.4 |
| `constructionBav` | `c3bbaaf3` | Construction | Invalid (0) | – | – | 6 Producing | constructionResourcesBav 1 | plank 1, stoneBav 1 | – / – | – | – | 0.8 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | good_buildingHelper | 9 Sacrifice | sacrificeGoodOlympicFlame 1 | (wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1) | – / – | – | – | 0.5 |

#### 2.4.2 Egyptians: economy [known: `buildings.lua`, `tribes.lua`]

| Building (Lua name) | Id | `name` | Size | Frame cost + cost | Worker | Mode | Output per cycle | Input per cycle | Work / rest ticks | Radius | Stock limit | Weight |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `woodCutterClay` | `ab6e0143` | WoodcutterHut | Small | clay 1 + clay 1 | good_woodcutter | 1 Mining | wood 1 | – | 55 / 333 | 6 | – | – |
| `stonePitClay` | `31246143` | Stone Pit | Small | clay 1 + clay 1 | good_miner | 1 Mining | stone 1 | (foodStoneEgypt 2) | 55 / 55 | 8 | – | – |
| `fisherClay` | `87456803` | FisherHut | Small | clay 1 + clay 1 | good_fisher | 3 Fishing | fish 1 | – | 333 / 1111 | 8 | – | – |
| `hunterClay` | `0cfbc803` | HuntingLodge | Small | clay 1 + clay 1 | good_hunter | 7 Hunting | goatHam 1 | – | 55 / 1500 | 8 | – | – |
| `springClay` | `9959b4a3` | Spring | Small | clay 1 + clay 1 | good_buildingHelper | 6 Producing | water 1 | – | 333 / 55 | – | – | – |
| `scholarHutEgypt` | `ea725e93` | ScholarHut | Small | clay 1 + clay 1 | good_scholarWorker | 11 Scholar | – | – | 333 / 55 | – | – | – |
| `watchTowerClay` | `9475d8c3` | WatchTower | Small | clay 1 + clay 1 | good_explorer | 8 Idling | – | – | – / – | – | – | – |
| `ironMineClay` | `d4fdc353` | Iron Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | ironOre 1 | foodIronOreEgypt 1 | 333 / 55 | 3 | 2 | 0.8 |
| `goldMineClay` | `9a3b8d03` | Gold Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | gold 1 | foodGoldEgypt 2 | 333 / 55 | 3 | 2 | 0.5 |
| `coalMineClay` | `5e78d5d3` | Coal Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | coal 1 | cheese 1 | 333 / 55 | 3 | 2 | 0.5 |
| `stoneMineClay` | `e6118f13` | Stone Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | stone 2 | foodStoneEgypt 2 | 333 / 55 | 3 | 2 | 0.6 |
| `gemMineClay` | `c87b2fd3` | Gemstone Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | gemstones 1 | foodGemstonesEgypt 4 | 333 / 55 | 3 | 4 | 0.4 |
| `saltMineClay` | `352c5a33` | Salt Mine | Mine | clay 2 + clay 2 | good_miner | 6 Producing | salt 1 | foodSaltEgypt 1 | 333 / 55 | 3 | 2 | 0.8 |
| `brickyard` | `daa4cf13` | Brickyard | Medium | clay 2 + stone 2 | good_buildingHelper | 6 Producing | clay 1 | water 1 | 333 / 55 | – | 6 | 0.5 |
| `bakeryClay` | `2a5e2c23` | Bakery | Medium | clay 2 + stone 2 | good_baker | 6 Producing | cornBread 1 | milk 1, egyptCorn 1 | 333 / 55 | – | 6 | 0.4 |
| `smelteryClay` | `b2f76643` | Smeltery | Medium | clay 2 + stone 2 | good_smelter | 6 Producing | iron 1 | ironOre 1 | 333 / 55 | – | 6 | 0.5 |
| `locksmitheryClay` | `78352ff3` | Locksmithery | Medium | clay 2 + stone 2 | good_smith | 6 Producing | tool 1 | wood 1, iron 1 | 333 / 55 | – | 6 | 0.4 |
| `smithyClay` | `4af27543` | Smithy | Medium | clay 2 + stone 2 | good_smith | 6 Producing | sword 1 | iron 1 | 333 / 600 | – | 6 | 0.6 |
| `bowSmithery` | `dd87a933` | BowSmithery | Medium | clay 2 + stone 2 | good_cabinetmaker | 6 Producing | bow 1 | wood 1, goatLeather 1 | 333 / 55 | – | 6 | 0.7 |
| `tanneryClay` | `e42f35d3` | Tannery | Medium | clay 2 + stone 2 | good_slaughter | 6 Producing | goatLeather 1 | goat 1, salt 1 | 333 / 222 | – | 6 | 0.3 |
| `cheeseDairyClay` | `f17e4f13` | Cheese Dairy | Medium | clay 2 + stone 2 | good_buildingHelper | 6 Producing | cheese 1 | milk 1, salt 1 | 333 / 55 | – | 6 | 0.6 |
| `mintClay` | `54ee6f13` | Mint | Medium | clay 2 + stone 2 | good_coiner | 6 Producing | coin 1 | gold 1, coal 1 | 333 / 55 | – | 6 | 1 |
| `casernSwordBow` | `633e0933` | Casern | Medium | clay 3 + stone 2 | good_buildingHelper | 4 SettlerBreeding | casernGood 1 | (milk 1, sword 1, bow 1, coin 1) | 333 / 55 | – | 6 | 0.6 |
| `catapultClay` | `1a2c38c3` | Catapult | Medium | clay 3 + clay 1, stone 2 | good_buildingHelper | 5 Catapult | catapultStone 1 | stone 1 | 25 / 55 | 12 | 4 | 0.4 |
| `farmClay` | `7a178933` | Farm | Large | clay 3 + stone 3 | good_farmer | 2 Farming | egyptCorn 1 | water 1 | 83 / 1000 | 2 | 6 | 0.5 |
| `goatBreeder` | `ef9bf5d3` | Goat Breeder | Large | clay 3 + stone 3 | good_buildingHelper | 6 Producing | goat 1 and milk 1 | – | 100 / 55 | – | – | 0.3 |
| `sacrificeClay` | `b6bc18c3` | Sacrifice | Large | clay 3 + stone 2 | good_buildingHelper | 9 Sacrifice | sacrificeGood 1 | – | – / – | – | – | 0.5 |
| `shipBuildingEgypt` | `8b7d38b3` | ShipConstructionSite | Ship | wood 4 + wood 8 | – (limit 0) | 6 Producing | shipEgyptCosts 1 | (wood 12) | – / – | 1 | – | 0.6 |
| `constructionClay` | `ca3cc793` | Construction | Invalid (0) | – | – | 6 Producing | constructionResourcesClay 1 | clay 1, stone 1 | – / – | – | – | 0.8 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | good_buildingHelper | 9 Sacrifice | sacrificeGoodOlympicFlame 1 | (wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1) | – / – | – | – | 0.5 |

#### 2.4.3 Scots: economy [known: `buildings.lua`, `tribes.lua`]

| Building (Lua name) | Id | `name` | Size | Frame cost + cost | Worker | Mode | Output per cycle | Input per cycle | Work / rest ticks | Radius | Stock limit | Weight |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `woodCutter` | `5a926fa3` | WoodcutterHut | Small | plank 1 + plank 1 | good_woodcutterScots | 1 Mining | wood 1 | – | 55 / 222 | 6 | – | – |
| `forester` | `3ff43d23` | ForesterHouse | Small | plank 1 + plank 1 | good_foresterScots | 0 Foresting | – | – | 55 / 222 | 6 | – | – |
| `stonePit` | `043185f3` | Stone Pit | Small | plank 1 + plank 1 | good_minerScots | 1 Mining | stoneScots 1 | (bread 1) | 55 / 55 | 8 | – | – |
| `fisher2` | `0ed96c13` | FisherHut | Small | plank 1 + plank 1 | good_fisherScots | 3 Fishing | fishScots 2 | – | 333 / 800 | 8 | – | – |
| `sheepBreeding` | `75ae9fc4` | Sheep Breeding | Small | plank 2 + stoneScots 1 | good_buildingHelperScots | 10 AnimalBreeding | sheepAnimal 1 | water 1 | 333 / 55 | – | 6 | 0.5 |
| `hunterScots` | `e86343f3` | HerdHut | Small | plank 1 + plank 1 | good_sheepherd | 7 Hunting | sheep 1 | (sheepAnimal 1) | 0 / 222 | 8 | – | – |
| `springScots` | `74467c43` | Spring | Small | plank 1 + plank 1 | good_buildingHelperScots | 6 Producing | water 1 | – | 333 / 55 | – | – | – |
| `scholarHut` | `87690013` | ScholarHut | Small | plank 1 + plank 1 | good_scholarWorkerScots | 11 Scholar | – | – | 333 / 55 | – | – | – |
| `watchTower` | `281f0783` | WatchTower | Small | plank 1 + plank 1 | good_explorerScots | 8 Idling | – | – | – / – | – | – | – |
| `ironMine` | `18282bd3` | Iron Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | ironOreScots 1 | fishScots 1 | 333 / 55 | 3 | 2 | 0.7 |
| `goldMine` | `154c1dae` | Gold Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | goldScots 1 | sheepHam 1 | 333 / 55 | 3 | 2 | 0.6 |
| `coalMine` | `9b027dae` | Coal Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | coalScots 1 | foodScots 1 | 333 / 55 | 3 | 2 | 0.8 |
| `stoneMine` | `6222a09e` | Stone Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | stoneScots 1 | bread 1 | 333 / 55 | 3 | 2 | 0.6 |
| `gemMine` | `5b80a913` | Gemstone Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | gemstonesScots 1 | foodGemstonesScots 3 | 333 / 55 | 3 | 3 | 0.4 |
| `saltMine` | `98bb22b3` | Salt Mine | Mine | plank 2 + plank 2 | good_minerScots | 6 Producing | saltScots 1 | foodSaltScots 1 | 333 / 55 | 3 | 2 | 0.4 |
| `sawMill` | `918ff373` | Sawmill | Medium | plank 2 + stoneScots 2 | good_cabinetmakerScots | 6 Producing | plank 1 | wood 1 | 333 / 55 | – | 6 | 0.8 |
| `mill` | `f7e2ed93` | Mill | Medium | plank 2 + stoneScots 2 | good_millerScots | 6 Producing | flour 1 | corn 1 | 333 / 55 | – | 6 | 0.4 |
| `smeltery` | `154551b3` | Smeltery | Medium | plank 2 + stoneScots 2 | good_smelterScots | 6 Producing | ironScots 1 | ironOreScots 1, coalScots 1 | 333 / 55 | – | 6 | 0.8 |
| `locksmithery` | `faada31e` | Locksmithery | Medium | plank 2 + stoneScots 2 | good_smithScots | 6 Producing | toolScots 1 | wood 1, ironScots 1 | 333 / 55 | – | 6 | 0.4 |
| `claymoreSmithy` | `37e98e03` | Claymore Smithy | Medium | plank 2 + stoneScots 2 | good_smithScots | 6 Producing | claymore 1 | ironScots 1, coalScots 1 | 333 / 55 | – | 6 | 0.6 |
| `kiltSewing` | `17d14003` | KiltSewing | Medium | plank 2 + stoneScots 2 | good_buildingHelperScots | 6 Producing | kilt 1 | sheep 1 | 333 / 55 | – | 6 | 0.5 |
| `bakery` | `0af7bb13` | Bakery | Medium | plank 2 + stoneScots 2 | good_bakerScots | 6 Producing | bread 1 | flour 1, corn 1 | 333 / 55 | – | 6 | 0.4 |
| `sheepButcher` | `396dd4c3` | SheepButcher | Medium | plank 2 + stoneScots 2 | good_slaughterScots | 6 Producing | sheepHam 1 | sheep 1, saltScots 1 | 333 / 222 | – | 6 | 0.5 |
| `whiskyBrewery` | `6a5c9d83` | WhiskyBrewery | Medium | plank 2 + stoneScots 2 | good_brewerScots | 6 Producing | whisky 1 | water 1, corn 1 | 333 / 55 | – | 6 | 0.65 |
| `mint` | `bc203663` | Mint | Medium | plank 2 + stoneScots 2 | good_coinerScots | 6 Producing | coinScots 1 | goldScots 1, coalScots 1 | 333 / 55 | – | 6 | 0.4 |
| `casernClayStone` | `1e2fc5d3` | Casern | Medium | plank 3 + stoneScots 2 | good_buildingHelperScots | 4 SettlerBreeding | casernGoodClayStone 1 | (whisky 1, claymore 1, stoneScots 1, kilt 1, coinScots 1) | 333 / 55 | – | 6 | 0.4 |
| `catapult` | `a1445ef3` | Catapult | Medium | plank 3 + plank 1, stoneScots 2 | good_buildingHelperScots | 5 Catapult | catapultStoneScots 1 | stoneScots 1 | 25 / 55 | 12 | 4 | 0.4 |
| `farm` | `07f63873` | Farm | Large | plank 3 + stoneScots 3 | good_farmerScots | 2 Farming | corn 1 | – | 83 / 55 | 2 | – | – |
| `sacrifice` | `5a230bf5` | Sacrifice | Large | plank 3 + stoneScots 2 | good_buildingHelperScots | 9 Sacrifice | sacrificeGood 1 | – | – / – | – | – | 0.5 |
| `shipBuilding` | `318d1529` | ShipConstructionSite | Ship | plank 4 + plank 8 | – (limit 0) | 6 Producing | ship 1 | (plank 12) | – / – | 1 | – | 0.4 |
| `construction` | `4a2ce4de` | Construction | Invalid (0) | – | – | 6 Producing | constructionResources 1 | plank 1, stoneScots 1 | – / – | – | – | 0.8 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | good_buildingHelper | 9 Sacrifice | sacrificeGoodOlympicFlame 1 | (wood 1, coinBav 1, oxen 1, goat 1, gold 1, halberd 1) | – / – | – | – | 0.5 |

Notes on the economy tables [known: data unless tagged]:

- The Egyptians have **no forester and no sawmill**: `good_forester` exists but no Egyptian building employs it,
  and no tree deposit has a `dp_nextDeposit`. [inferred] Egyptian wood comes from the trees a map provides and
  from the two wood exchanges of the temple (§2.8).
- The three barracks (`casernHalCross`, `casernSwordBow`, `casernClayStone`) are `casern` and `spawn` types with
  `bp_setAiThreat` 30; their cycle is the training cycle of §3.5.
- The catapults have `bp_setCatapult`, `bp_setCatapultDamage` 10, `bp_setHealth` 40, `bp_setAiThreat` 100 and
  no productivity statistic. Their 25 "work" ticks are the length of the shot; the radius 12 is the range.
- `sauerey` (name `"Butcher"`), `oxenBreeding` and `goatBreeder` have `bp_setGfxBreeding`. The three farms,
  `sauerey`, `oxenBreeding`, `sacrificeBav` and `goatBreeder` have the door offset `DoorOffsetNorthWest`.
- The temples (`sacrificeBav`, `sacrificeClay`, `sacrifice`) and `sacrificeOlympicFlame` have a locked
  distribution weight (`bp_setArrangementLocked`) and no productivity statistic.
- `sacrificeOlympicFlame` employs the **Egyptian** `good_buildingHelper` for every tribe, and a
  `good_buildingHelper` costs the Egyptian `tool`. [inferred] A Bavarian or Scottish headquarters can supply
  that worker only when it holds an Egyptian `tool`. The sacrifice component does not need the worker [known]:
  `Building::Update` S 0055e2f0 calls `ai::village::VillageSacrifice::Update` S 00561940 for every finished mode-9 building,
  and neither it nor `CheckCanOrder` S 00561240 or `CheckCanStart` S 00560f20 tests the building's workers;
  working mode 9 gives the worker no action (`Worker::ChooseNextWork` S 0065d660).
- `constructionBav`, `constructionClay` and `construction` (name `"Construction"`, graphics `"MediumDummy"`,
  size 0) are not buildings a player places. They carry the product slot `constructionResources*` and the
  weight 0.8. [inferred] They stand for "building sites" as a consumer of the two construction materials. No
  code names them: their ids do not occur as constants in the function cache, so they are reached only by
  walks over the tribe's building list. One such walk [known]: `Economy_CollectConsumerBuildings` S 00534f40
  (the consumer list of the building tooltip) keeps every type of the list with `constructionTime > 0` whose
  product recipe names the good (`BuildingProperty::ConsumesGood` S 00553080, both product slots), which
  includes the dummy type. [TODO] not established: the same for the goods-distribution panel and the AI's
  consumer lists (read their walks over `TribeProperty.buildings`).

#### 2.4.4 Storage, territory and special buildings [known: `buildings.lua`]

Columns: **Flags** are the boolean setters called; **Territory** `bp_setTerritoryRange`; **Garrison**
`bp_setSoldierLimit`; **Sight** `bp_setExploreRadius`; **Health** `bp_setHealth`; **Upgrade** `bp_setUpgrade`.
All of these types have worker limit 0, except the Olympic flame (1).

Source, per column (all `buildings.lua`): **Id** `bp_create`; **`name`** `bp_setName`; **Size** `bp_setSize`;
**Frame cost + cost** `bp_addFrameCost`, `bp_addCost`; **Flags** `bp_setDepot`, `bp_setSpawn`, `bp_setCasern`,
`bp_setTerritoryBuilding`, and `bp_setConstructionTime` for "constructionTime -1"; **AI
threat** `bp_setAiThreat`; worker limit `bp_setWorkerLimit`; the other columns as named above. Row set per
tribe = the tribe's `tp_addBuilding` calls (`tribes.lua`).

Bavarians:

| Building | Id | `name` | Size | Frame cost + cost | Flags | Territory | Garrison | Sight | Health | Upgrade | AI threat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `guardHouseBav` | `56cb3a61` | GuardHouse | Small + Military | plank 1 + plank 2 | territoryBuilding | 9 | 3 | 12 | 60 | towerBav | 30 |
| `depotBav` | `234b01e3` | Depot | Medium | plank 4 + stoneBav 3 | depot, spawn | – | – | – | – | – | – |
| `towerBav` | `3722ff43` | Tower | Medium + Military | plank 3 + stoneBav 5 | territoryBuilding | 10 | 6 | 13 | 80 | fortressBav | 60 |
| `fortressBav` | `b53151c3` | Fortress | Large + Military | plank 4 + stoneBav 7 | territoryBuilding | 11 | 9 | 14 | 100 | – | 90 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | constructionTime -1 | 4 | – | – | 60 | – | 0 |
| `castle` | `f6e26cb3` | Castle | Large | – | depot, spawn, casern, territoryBuilding, constructionTime -1 | 9 | – | 12 | 200 | – | 50 |

Egyptians:

| Building | Id | `name` | Size | Frame cost + cost | Flags | Territory | Garrison | Sight | Health | Upgrade | AI threat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `guardHouseClay` | `0fbff9a3` | GuardHouse | Small + Military | clay 1 + clay 2 | territoryBuilding | 9 | 4 | 12 | 80 | towerClay | 40 |
| `depotClay` | `643e8a13` | Depot | Medium | clay 4 + stone 3 | depot, spawn | – | – | – | – | – | – |
| `towerClay` | `5c967c93` | Tower | Medium + Military | clay 3 + stone 5 | territoryBuilding | 10 | 8 | 13 | 100 | fortressClay | 70 |
| `fortressClay` | `5129bc93` | Fortress | Large + Military | clay 4 + stone 7 | territoryBuilding | 11 | 12 | 14 | 120 | – | 100 |
| `castle` | `f6e26cb3` | Castle | Large | – | depot, spawn, casern, territoryBuilding, constructionTime -1 | 9 | – | 12 | 200 | – | 50 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | constructionTime -1 | 4 | – | – | 60 | – | 0 |

Scots:

| Building | Id | `name` | Size | Frame cost + cost | Flags | Territory | Garrison | Sight | Health | Upgrade | AI threat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `guardHouse` | `12e67603` | GuardHouse | Small + Military | plank 1 + plank 2 | territoryBuilding | 9 | 2 | 12 | 60 | tower | 30 |
| `depot` | `628f2523` | Depot | Medium | plank 4 + stoneScots 3 | depot, spawn | – | – | – | – | – | – |
| `tower` | `7d00b493` | Tower | Medium + Military | plank 3 + stoneScots 5 | territoryBuilding | 10 | 4 | 13 | 80 | fortress | 60 |
| `fortress` | `8c137e93` | Fortress | Large + Military | plank 4 + stoneScots 7 | territoryBuilding | 11 | 6 | 14 | 100 | – | 90 |
| `castle` | `f6e26cb3` | Castle | Large | – | depot, spawn, casern, territoryBuilding, constructionTime -1 | 9 | – | 12 | 200 | – | 50 |
| `sacrificeOlympicFlame` | `287a5c71` | SacrificeOlympicFlame | Large | – | constructionTime -1 | 4 | – | – | 60 | – | 0 |

The guard houses, towers and fortresses also set a stock limit of 2, 4 and 6 (all tribes); they have no product
slot. The limit is read through `Building::GetHpScaledStockLimit` S 0055c200, which has four callers [known]:
`Production::RequestAllInputs` S 00565a70 (returns before reading it for a type without a product),
`Production::AdjustInputRequest` S 00565620, `VillageSoldierTraining_UpdateInputRequests` S 00566ba0 (casern
types) and `Depot::ClampStockToLimit` S 0055b090 (on a hit-point change, cuts every entry of the building's
stock to the limit). [TODO] not established: which goods a military building holds in that stock, and so
whether the limit has any effect for it (read `AdjustInputRequest` and the writers of a military building's
stock).
The watch towers of §2.4.1–2.4.3 are not territory buildings: they only uncover the map (sight 16).

### 2.5 Professions and carried tools

[known: `Jobs.lua`, `buildings.lua`] A profession is a settler good (`gp_setType` 1) with a cost list. Every
worker and builder costs exactly one tool of its tribe; there is no tool per profession. The "tool" a settler
is seen with is the model of the good named by `gp_setGfxGoodId`.

Source: good and id = `gp_create` (`Jobs.lua`); carried model = `gp_setGfxGoodId` (`Jobs.lua`; the model goods
are those of §2.3.5, `Goods.lua`); cost = `gp_addCost` (`Jobs.lua`). **Workplaces** are *derived* from two
files: every type in the tribe's `tp_addBuilding` list (`tribes.lua`) whose `bp_setWorker` (`buildings.lua`)
names the good; the builder is `tp_setConstructor` (`tribes.lua`).

| Profession | Carried model (`gp_setGfxGoodId`) | Bavarians: good, id, workplaces | Egyptians: good, id, workplaces | Scots: good, id, workplaces |
|---|---|---|---|---|
| constructor | hammer | `good_constructorBav` `efd59f73`: builder (`tp_setConstructor`) | `good_constructor` `dd2daebe`: builder (`tp_setConstructor`) | `good_constructorScots` `7d0615e3`: builder (`tp_setConstructor`) |
| woodcutter | axe | `good_woodcutterBav` `b5f54183`: woodCutterBav | `good_woodcutter` `2c50533e`: woodCutterClay | `good_woodcutterScots` `5ea5c2d3`: woodCutter |
| forester | shovel | `good_foresterBav` `6be2f033`: foresterBav | `good_forester` `6eba970e`: *no workplace* | `good_foresterScots` `ffbaf343`: forester |
| hunter | spear | `good_hunterBav` `2d5c0763`: hunter | `good_hunter` `ab43100e`: hunterClay | `good_hunterScots` `0561ff03`: *no workplace* |
| cabinetmaker | saw | `good_cabinetmakerBav` `b4f4c0a3`: sawMillBav, crossbowSmithery | `good_cabinetmaker` `2195bc53`: bowSmithery | `good_cabinetmakerScots` `c8bd6f73`: sawMill |
| baker | rollingPin | `good_bakerBav` `36e66e23`: bakerypretzel | `good_baker` `862797a3`: bakeryClay | `good_bakerScots` `cd82a2d3`: bakery |
| miller | – | `good_millerBav` `bc9cce23`: millBav | `good_miller` `290e6b9e`: *no workplace* | `good_millerScots` `d247d633`: mill |
| farmer | scythe | `good_farmerBav` `4152ad43`: farmBav | `good_farmer` `8d0ba75e`: farmClay | `good_farmerScots` `d60c88b3`: farm |
| miner | pickaxe | `good_minerBav` `c526b403`: stonePitBav, ironMineBav, goldMineBav, coalMineBav, stoneMineBav, gemMineBav, saltMineBav | `good_miner` `59b7633e`: stonePitClay, ironMineClay, goldMineClay, coalMineClay, stoneMineClay, gemMineClay, saltMineClay | `good_minerScots` `cd63fa53`: stonePit, ironMine, goldMine, coalMine, stoneMine, gemMine, saltMine |
| scholarWorker | hammer | `good_scholarWorkerBav` `cbce40a3`: scholarHutBav | `good_scholarWorker` `2355c25e`: scholarHutEgypt | `good_scholarWorkerScots` `8edd1183`: scholarHut |
| explorer | spear | `good_explorerBav` `8f29b113`: watchTowerBav | `good_explorer` `a07bf6fe`: watchTowerClay | `good_explorerScots` `93a244e3`: watchTower |
| fisher | fishingRod | `good_fisherBav` `e54ab7d3`: fisher | `good_fisher` `4ac589ce`: fisherClay | `good_fisherScots` `58e00e93`: fisher2 |
| brewer | – | `good_brewerBav` `6a0096f3`: brauhaus | `good_brewer` `0eaffece`: *no workplace* | `good_brewerScots` `dd95edb3`: whiskyBrewery |
| smith | hammer | `good_smithBav` `2f3e60a3`: locksmitheryBav, halberdSmithy | `good_smith` `03a2b9f3`: locksmitheryClay, smithyClay | `good_smithScots` `6169f473`: locksmithery, claymoreSmithy |
| coiner | pot | `good_coinerBav` `544aeb43`: mintBav | `good_coiner` `fdf21163`: mintClay | `good_coinerScots` `2d4f4ac3`: mint |
| smelter | pot | `good_smelterBav` `78503113`: smelteryBav | `good_smelter` `9c0ae313`: smelteryClay | `good_smelterScots` `eec861f3`: smeltery |
| slaughter | hatchet | `good_slaughterBav` `7c14e393`: *no workplace* | `good_slaughter` `f0622d7e`: tanneryClay | `good_slaughterScots` `883584e3`: sheepButcher |
| buildingHelper | – | `good_buildingHelperBav` `82bc7033`: spring, casernHalCross, catapultBav, sauerey, oxenBreeding, sacrificeBav | `good_buildingHelper` `163e5102`: springClay, brickyard, cheeseDairyClay, casernSwordBow, catapultClay, goatBreeder, sacrificeClay, sacrificeOlympicFlame | `good_buildingHelperScots` `4c72cdb3`: sheepBreeding, springScots, kiltSewing, casernClayStone, catapult, sacrifice |

Further settler goods [known: `Jobs.lua`] (source: id `gp_create`, `settlerType` `gp_setSettlerType`, cost
`gp_addCost`, all `Jobs.lua`; the second carrier is `tp_setSecondCarrierId` in `tribes.lua`):

| Good | Id | `settlerType` | Cost | Role |
|---|---|---|---|---|
| `good_helper` | `7bff15ce` | 2 Carrier | none | the carrier of every tribe; the id is a constant in the code (S 00668be0, S 00668e10, S 0064d020, [streets-transport.md](streets-transport.md)); also the Egyptian second carrier |
| `good_oxen` | `d4157c5f` | 2 Carrier | `oxen` 1 | Bavarian second carrier; no carried model |
| `good_sheepherd` | `afdb7463` | 0 Worker | `toolScots` 1 | Scottish herder of `hunterScots`; carries `crook` |
| `good_scholar` | `3355c25e` | 4 Specialist | `tool` 1 | the only Specialist record. The command that would send it to a flag does nothing in this build ([game-commands.md](game-commands.md), `0x2000B`); the geologist of the game is the worker of the scholar hut |
| `good_cheeser` | `1f5c5a18` | 0 Worker | `tool` 1 | not employed by any building (the cheese dairy employs `good_buildingHelper`) |
| `good_garibaldNPC`, `good_treeMerchantNPC` | `f2a8c1b3`, `e9b4e353` | 5 NPC | none | script-driven characters ([settlers-jobs.md](settlers-jobs.md) §3.10) |

Professions without a workplace in the data [known]: `good_forester` and `good_miller` and `good_brewer`
(Egyptian set), `good_slaughterBav`, `good_hunterScots`, `good_cheeser`. `good_buildingHelper*` is the generic
profession of every building without a craft of its own (springs, breeders, barracks, catapults, temples,
`brickyard`, `cheeseDairyClay`, `kiltSewing`, `sauerey`).

### 2.6 Soldier ranks

[known: `Jobs.lua`, `military.lua`] `mi_setSoldierId(tribe, kind, level, good)` assigns the ranks; kind 0 is
`soldierType_Sword` (melee), 1 `soldierType_Bow` (ranged). Columns are the `gp_set*` values: **Wait**
`AttackWaitTime` (ticks between strikes), **Block %** `BlockingChance`, **Strike** `AttackTime` (ticks),
**Hit at** `gp_addHitTime` (tick of the strike at which the hit lands), **Range** `BowRange` (cells). The fight
rules that use them are in [military.md](military.md) §3.7.

Source, per column: **Tribe**, **Kind, level** and **Good** = the arguments of the 15 `mi_setSoldierId` calls
(`military.lua`); all other columns are calls on that good in `Jobs.lua`: **Id** `gp_create`, **Cost**
`gp_addCost`, **Damage** `gp_setHitDamage`, **Health** `gp_setHealth`, **Armor** `gp_setArmor`, **Wait**
`gp_setAttackWaitTime`, **Block %** `gp_setBlockingChance`, **Strike** `gp_setAttackTime`, **Hit at**
`gp_addHitTime`, **Range** `gp_setBowRange`, **Projectile** `gp_setProjectileType` (ranged ranks only; the kind
is also set on the good by `gp_setSoldierType`).

| Tribe | Kind, level | Good | Id | Cost | Damage | Health | Armor | Wait | Block % | Strike | Hit at | Range | Projectile |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bavarians | sword 0 | `good_soldierHalberd0` | `15e86843` | halberd 1, weissbeer 1 | 10 | 100 | 5 | 19 | 2 | 11 | 4 | – | – |
| bavarians | sword 1 | `good_soldierHalberd1` | `ba0e7f83` | good_soldierHalberd0 1, coinBav 1 | 15 | 150 | 5 | 18 | 3 | 11 | 4 | – | – |
| bavarians | sword 2 | `good_soldierHalberd2` | `466c6c23` | good_soldierHalberd1 1, coinBav 1 | 21 | 250 | 6 | 17 | 5 | 11 | 4 | – | – |
| bavarians | bow 0 | `good_bowSoldierCrossBow0` | `de902463` | crossbow 1, weissbeer 1 | 10 | 50 | 0 | 3 | 0 | 27 | 6 | 6 | 2 bolt |
| bavarians | bow 1 | `good_bowSoldierCrossBow1` | `e4373023` | good_bowSoldierCrossBow0 1, coinBav 1 | 13 | 100 | 0 | 2 | 0 | 27 | 6 | 7 | 2 bolt |
| bavarians | bow 2 | `good_bowSoldierCrossBow2` | `eea36f43` | good_bowSoldierCrossBow1 1, coinBav 1 | 19 | 200 | 0 | 1 | 0 | 27 | 6 | 7 | 2 bolt |
| egyptians | sword 0 | `good_soldierSword0` | `476c6c23` | sword 1, milk 1 | 9 | 50 | 4 | 12 | 1 | 18 | 4, 15 | – | – |
| egyptians | bow 0 | `good_bowSoldier0` | `49f5c9d3` | bow 1, milk 1 | 10 | 50 | 0 | 8 | 0 | 22 | 7 | 6 | 0 arrow |
| egyptians | bow 1 | `good_bowSoldier1` | `12f84603` | good_bowSoldier0 1, coin 1 | 15 | 150 | 1 | 7 | 0 | 22 | 7 | 6 | 0 arrow |
| egyptians | bow 2 | `good_bowSoldier2` | `efa36f43` | good_bowSoldier1 1, coin 1 | 26 | 250 | 2 | 6 | 0 | 22 | 7 | 7 | 0 arrow |
| scots | sword 0 | `good_soldierClaymore0` | `906014f3` | claymore 1, kilt 1, whisky 1 | 10 | 100 | 5 | 19 | 2 | 11 | 5 | – | – |
| scots | sword 1 | `good_soldierClaymore1` | `559ddea3` | good_soldierClaymore0 1, coinScots 1 | 18 | 200 | 7 | 17 | 4 | 11 | 5 | – | – |
| scots | sword 2 | `good_soldierClaymore2` | `359ad5a8` | good_soldierClaymore1 1, coinScots 1 | 24 | 300 | 8 | 15 | 6 | 11 | 5 | – | – |
| scots | bow 0 | `good_bowSoldierStone0` | `755a5023` | stoneScots 3, kilt 1, whisky 1 | 10 | 50 | 0 | 12 | 0 | 18 | 12 | 5 | 3 sling stone |
| scots | bow 1 | `good_bowSoldierStone1` | `7a1f8383` | good_bowSoldierStone0 1, coinScots 1 | 13 | 150 | 0 | 11 | 0 | 18 | 12 | 6 | 3 sling stone |

The cost of a level-0 rank is what the barracks consumes to train one soldier; the cost of a higher rank is the
rank below plus one coin (§3.5). `good_soldierSword0` is the only rank with two hit times.
`mi_setRegenerationRate` 100, `mi_setWaitForTacticTime` 10, `mi_setActionsInFightDelayTime` 300,
`mi_setHealthExchangeDistance` 200 apply to all tribes ([properties-data.md](properties-data.md) §2.10).

### 2.7 Ships and harbours

[known: `ship.lua`, `buildings.lua`, `Goods.lua`, `harbors.lua`] There is one ship class. A ship is not a good
and not a building type: it is built by a ship-building site and then exists as a navy object
([navy.md](navy.md) §3.3).

Source, per row: ship-building site = the tribe's `tp_addBuilding` entry of size `SizeShip` (`tribes.lua`,
`bp_setSize` in `buildings.lua`), id = `bp_create`; site materials = `bp_addFrameCost`, `bp_addCost`
(`buildings.lua`); speed and expedition building = `sh_setSpeed(tribe, value)`,
`sh_setExpeditionBuilding(tribe, building)` (`ship.lua`); the common values below are the named `sh_*` calls
(`ship.lua`, one call each); the harbour records are the `hp_create` calls of `harbors.lua`.

| | Bavarians | Egyptians | Scots |
|---|---|---|---|
| Ship-building site | `shipBuilding` `318d1529` | `shipBuildingEgypt` `8b7d38b3` | `shipBuilding` `318d1529` |
| Site materials (frame + cost) | plank 4 + plank 8 | wood 4 + wood 8 | plank 4 + plank 8 |
| Speed (`sh_setSpeed`, cells per tick: the step progress grows by `speed / distance` per movement update, S 007728d0, S 00774a10, [navy.md](navy.md) §3.4) | 0.06 | 0.09 | 0.12 |
| Expedition building founded by a landing (`sh_setExpeditionBuilding`) | `guardHouseBav` | `guardHouseClay` | `guardHouse` |

Common values: `sh_setSize` 1, `sh_setConstructTime` 30 (hammer strokes per delivered good), `sh_setStockLimit`
12 (cargo units), `sh_setWaitTime` 15, `sh_setSinkingTime` 47. The site has worker limit 0 (the tribe's builder
builds the ship), working radius 1 (the search radius for the launch cell) and is removed when its one ship is
finished [known: [navy.md](navy.md) §3.3]. The eight `harbor_*` records are the eight orientations of a
harbour place on a map, not buildings a player constructs ([properties-data.md](properties-data.md) §2.9).

### 2.8 Sacrifices

Columns: **Cost** `sf_addCost` (goods delivered to the temple). **Effect** the one `sf_addEffect` of the
record, with its first argument; "gives X n" is `Effect_FunctionGoodExchange` (n units of X appear in the
temple). **Target** `sf_setTarget`. **Duration**, **Research** (`sf_setResearchDuration`; 0 = none needed, and
0 is the default shown for the records that do not call the setter: the good exchanges without research, the
campaign records and the four start sacrifices `prodSpeed`, `prodSpeedEgypt`, `carrierSpeed`, `workerPause`
[known: `SacrificeProperty` ctor S 005567e0]) and **Regeneration** (`sf_setRegenerationDelay`) are ticks.
**Category** is the AI trigger class. **Default** =
the sacrifice is in the tribe's `tp_addAllowedSacrifice` list, the default of a map's offer
([properties-data.md](properties-data.md) §2.3). Rows are in `tp_addSacrifice` order. What each effect number
does to the simulation is specified in [properties-data.md](properties-data.md) §3.9.

Source of §2.8.1 to §2.8.4, per column: **Id** `sf_create`; **`name`** `sf_setName`; **Cost** `sf_addCost`;
**Effect** `sf_addEffect`; **Target** `sf_setTarget`; **Duration** `sf_setDuration`; **Research**
`sf_setResearchDuration`; **Regeneration** `sf_setRegenerationDelay`; **Category** `sf_setCategory`. The file
depends on the record: the good exchanges (Lua names `sacrifice_GE_*`) are in `sacrifices_goodExchange.lua`,
where the helper `defaultSacrificeGEProperties(id, rewardType, rewardCount, uiName)` makes the name, effect,
target, duration (20), category and a first regeneration value (3000) and each of the 31 records then calls
`sf_addCost`, `sf_setRegenerationDelay` and, for some, `sf_setResearchDuration` itself; the 10 records created
in `sacrifices_campaign.lua` (three of them call `sf_setForCampaign`; the rows of §2.8.4 are among the ten) have
all their calls there; the other 36 are in `sacrifices.lua`. The file of a row is the one that holds the
`sf_create` of its Lua name. Row set and order per tribe = `tp_addSacrifice`, **Default** = `tp_addAllowedSacrifice`
(`tribes.lua`).

#### 2.8.1 Bavarians [known: `sacrifices.lua`, `sacrifices_goodExchange.lua`, `sacrifices_campaign.lua`, `tribes.lua`]

| Sacrifice (Lua name) | Id | `name` | Cost | Effect (`sf_addEffect`) | Target | Duration | Research | Regeneration | Category | Default |
|---|---|---|---|---|---|---|---|---|---|---|
| `sacrifice_prodSpeed` | `a2f5e32d` | prodSpeed | oxen 5, toolBav 2, leather 5 | ProductionSpeed 75 | owner | 9000 | 0 | 3600 | 0 Economic | yes |
| `sacrifice_minerStarve` | `e004ee9d` | minerStarve | weissbeer 12, goldBav 5 | MinerNeedNoFood | owner | 6000 | 9000 | 5400 | 0 Economic | – |
| `sacrifice_GE_fishBav` | `f383de73` | GE_fish | water 8, stoneBav 3 | gives fishBav 3 | owner | 20 | 0 | 1800 | 4 Exchange | yes |
| `sacrifice_GE_woodBav` | `6fefede4` | GE_wood | gemstonesBav 1 | gives wood 11 | owner | 20 | 0 | 5400 | 4 Exchange | – |
| `sacrifice_GE_cornBav` | `35c4b71d` | GE_corn | leather 1, water 1 | gives corn 4 | owner | 20 | 0 | 1800 | 4 Exchange | – |
| `sacrifice_GE_goldBav` | `d4f78e4d` | GE_gold | gemstonesBav 2, stoneBav 12 | gives goldBav 4 | owner | 20 | 6000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_coinBav` | `1febb7fd` | GE_coin | gemstonesBav 1 | gives coinBav 1 | owner | 20 | 6000 | 1800 | 4 Exchange | – |
| `sacrifice_GE_gemstonesBav` | `bc7b97fd` | GE_gemstones | plank 20, stoneBav 10 | gives gemstonesBav 1 | owner | 20 | 9000 | 5400 | 4 Exchange | yes |
| `sacrifice_GE_stoneBav` | `480a25f4` | GE_stone | gemstonesBav 1 | gives stoneBav 16 | owner | 20 | 6000 | 5400 | 4 Exchange | – |
| `sacrifice_GE_halberdBav` | `323126d4` | GE_halberdBav | gemstonesBav 2, goldBav 5 | gives halberd 5 | owner | 20 | 9000 | 3600 | 4 Exchange | yes |
| `sacrifice_GE_weissbeerBav` | `baabb874` | GE_weissbeerBav | leather 12, oxen 4, wood 6 | gives weissbeer 3 | owner | 20 | 9000 | 3600 | 4 Exchange | – |
| `sacrifice_nilflood` | `7b315faf` | nilflood | toolBav 3, weissbeer 6, oxen 6 | CornDoubleProduction 400 | owner | 9000 | 6000 | 3600 | 0 Economic | – |
| `sacrifice_buildingArmor` | `53b934cd` | buildingArmor | ironBav 2, stoneBav 8, wood 8 | BuildingArmor 400 | owner | 3000 | 6000 | 3600 | 1 Military | – |
| `sacrifice_soldierSpeed` | `735a329d` | soldierSpeed | gemstonesBav 1, corn 10, coalBav 2 | SoldierSpeed 300 | owner | 6000 | 3000 | 1800 | 1 Military | yes |
| `sacrifice_soldierHeal` | `5b539fba` | soldierHeal | gemstonesBav 3, pretzel 3 | SoldierHeal | owner | 20 | 9000 | 9000 | 3 Fight | – |
| `sacrifice_archerHitChance` | `714b081d` | archerHitChance | coalBav 10, saltBav 5 | ArcherHitChance 2 | enemy | 4200 | 9000 | 5400 | 3 Fight | – |
| `sacrifice_shipSpeedUp` | `4b315faf` | shipSpeedUp | fishBav 7, toolBav 1 | ShipSpeed 200 | owner | 6000 | 3000 | 3600 | 2 Navy | – |
| `sacrifice_expandTerritoryBav` | `a2ce1103` | expandTerritory | toolBav 3, pretzel 3 | ExpandTerritory 5 | owner | 6000 | 3000 | 3600 | 1 Military | yes |
| `sacrifice_exploreEnemiesBav` | `7ba91903` | exploreEnemies | goldBav 2, gemstonesBav 1, toolBav 2 | ExploreEnemy | enemy | 20 | 6000 | 5400 | 1 Military | – |
| `sacrifice_peaceTime` | `8958e51d` | peaceTime | saltBav 10, oxen 5, gemstonesBav 3 | PeaceTime | owner | 6000 | 9000 | 5400 | 1 Military | yes |
| `sacrifice_soldierArmorBav` | `5e280c63` | soldierArmor | goldBav 2, ironBav 2 | SoldierArmor 120 | owner | 6000 | 9000 | 6000 | 3 Fight | – |
| `sacrifice_destroyShips` | `2c7fddfd` | destroyShips | gemstonesBav 3, stoneBav 10, coalBav 5 | DestroyShips | enemy | 20 | 9000 | 5400 | 2 Navy | – |
| `sacrifice_archerHitChanceCheap` | `1f183e13` | archerHitChance | water 1 | ArcherHitChance 2 | enemy | 6000 | 0 | 1000 | 3 Fight | – |

#### 2.8.2 Egyptians [known: the same files]

| Sacrifice (Lua name) | Id | `name` | Cost | Effect (`sf_addEffect`) | Target | Duration | Research | Regeneration | Category | Default |
|---|---|---|---|---|---|---|---|---|---|---|
| `sacrifice_prodSpeedEgypt` | `87470603` | prodSpeed | cornBread 5, tool 5, goat 10 | ProductionSpeed 75 | owner | 6000 | 0 | 3600 | 0 Economic | yes |
| `sacrifice_minerStarveEgypt` | `c5af4653` | minerStarve | milk 20, cheese 6, gold 5 | MinerNeedNoFood | owner | 9000 | 9000 | 5400 | 0 Economic | – |
| `sacrifice_GE_fishEgypt` | `b2764844` | GE_fish | water 12, stone 6 | gives fish 3 | owner | 20 | 0 | 1800 | 4 Exchange | yes |
| `sacrifice_GE_woodEgypt2` | `52c3746d` | GE_woodEgypt | clay 3, stone 3, goat 3 | gives wood 6 | owner | 20 | 0 | 1800 | 4 Exchange | yes |
| `sacrifice_GE_woodEgypt` | `4ac6d3c4` | GE_wood | gemstones 1 | gives wood 11 | owner | 20 | 0 | 5400 | 4 Exchange | – |
| `sacrifice_GE_cornEgypt` | `96ab1d94` | GE_corn | goatLeather 1, water 5 | gives egyptCorn 4 | owner | 20 | 0 | 1800 | 4 Exchange | – |
| `sacrifice_GE_goldEgypt` | `6bedea64` | GE_gold | gemstones 2, stone 13 | gives gold 4 | owner | 20 | 6000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_coinEgypt` | `35b39674` | GE_coin | gemstones 1 | gives coin 1 | owner | 20 | 6000 | 1800 | 4 Exchange | – |
| `sacrifice_GE_fleshEgypt` | `7086ed6d` | GE_fleshEgypt | goat 12, egyptCorn 6 | gives goatHam 4 | owner | 20 | 6000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_gemstonesEgypt` | `db9f1aed` | GE_gemstones | clay 20, stone 10 | gives gemstones 1 | owner | 20 | 9000 | 5400 | 4 Exchange | yes |
| `sacrifice_GE_stoneEgypt` | `f97b6124` | GE_stone | gemstones 1 | gives stone 15 | owner | 20 | 6000 | 5400 | 4 Exchange | – |
| `sacrifice_GE_clayEgypt` | `6bf2dc44` | GE_clayEgypt | gemstones 1 | gives clay 8 | owner | 20 | 6000 | 5400 | 4 Exchange | – |
| `sacrifice_GE_bowEgypt` | `737c4144` | GE_bowEgypt | gemstones 2, gold 3 | gives bow 7 | owner | 20 | 9000 | 3600 | 4 Exchange | yes |
| `sacrifice_GE_milkEgypt` | `00daaec4` | GE_milkEgypt | goat 12, clay 2 | gives milk 4 | owner | 20 | 6000 | 2400 | 4 Exchange | – |
| `sacrifice_nilfloodEgypt` | `536137dd` | nilflood | tool 4, milk 12, goat 6 | CornDoubleProduction 400 | owner | 9000 | 6000 | 3600 | 0 Economic | – |
| `sacrifice_strongerSoldierEgypt` | `bbf37663` | strongerSoldier | goatHam 5, milk 5, gemstones 1 | SoldierDamage 120 | owner | 4200 | 6000 | 3600 | 3 Fight | – |
| `sacrifice_soldierArmorEgypt` | `2b884d0d` | soldierArmor | stone 8, gold 1, iron 3 | SoldierArmor 120 | owner | 6000 | 9000 | 3600 | 3 Fight | – |
| `sacrifice_soldierHealEgypt` | `58519ab3` | soldierHeal | gemstones 3, cornBread 3 | SoldierHeal | owner | 20 | 9000 | 9000 | 3 Fight | – |
| `sacrifice_archerAttackSpeedEgypt` | `4c23e453` | archerAttackSpeed | fish 4, salt 3 | ArcherAttackSpeed 80 | owner | 3000 | 9000 | 5400 | 3 Fight | yes |
| `sacrifice_peaceTimeEgypt` | `737c9083` | peaceTime | salt 7, goat 12, gemstones 3 | PeaceTime | owner | 6000 | 9000 | 5400 | 1 Military | yes |
| `sacrifice_expandTerritory` | `5a556ffa` | expandTerritory | tool 5, cheese 4 | ExpandTerritory 5 | owner | 6000 | 3000 | 3600 | 1 Military | yes |
| `sacrifice_exploreEnemies` | `0c3362ad` | exploreEnemies | gold 2, gemstones 1, tool 3 | ExploreEnemy | enemy | 20 | 6000 | 5400 | 1 Military | – |
| `sacrifice_destroyShipsEgypt` | `0635f84d` | destroyShips | gemstones 3, stone 10, coal 5 | DestroyShips | enemy | 20 | 9000 | 5400 | 2 Navy | – |
| `sacrifice_shipSpeedDown` | `2000b053` | shipSpeedDown | fish 4, iron 4 | ShipSpeed 2 | enemy | 4200 | 6000 | 3600 | 2 Navy | – |

#### 2.8.3 Scots [known: the same files]

| Sacrifice (Lua name) | Id | `name` | Cost | Effect (`sf_addEffect`) | Target | Duration | Research | Regeneration | Category | Default |
|---|---|---|---|---|---|---|---|---|---|---|
| `sacrifice_carrierSpeed` | `510391dd` | carrierSpeed | water 20, whisky 3 | CarrierSpeed 300 | owner | 9000 | 0 | 1800 | 0 Economic | yes |
| `sacrifice_workerPause` | `3625fdbd` | workerPause | stoneScots 10, wood 10, coinScots 1 | WorkerPause 300 | enemy | 6000 | 0 | 1800 | 0 Economic | yes |
| `sacrifice_minerStarveScot` | `dd894733` | minerStarve | whisky 12, goldScots 6 | MinerNeedNoFood | owner | 9000 | 9000 | 5400 | 0 Economic | – |
| `sacrifice_GE_fishScots` | `26185ba4` | GE_fish | water 6, stoneScots 3 | gives fishScots 3 | owner | 20 | 0 | 1800 | 4 Exchange | yes |
| `sacrifice_GE_woodScots` | `11e6f6b4` | GE_wood | gemstonesScots 1 | gives wood 9 | owner | 20 | 0 | 5400 | 4 Exchange | – |
| `sacrifice_GE_cornScots` | `da50a154` | GE_corn | wood 2, water 1 | gives corn 4 | owner | 20 | 0 | 1800 | 4 Exchange | – |
| `sacrifice_GE_goldScots` | `e6378a64` | GE_gold | gemstonesScots 2, stoneScots 8 | gives goldScots 4 | owner | 20 | 6000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_coinScots` | `7fa73f44` | GE_coin | gemstonesScots 1 | gives coinScots 1 | owner | 20 | 6000 | 1800 | 4 Exchange | – |
| `sacrifice_GE_gemstonesScots` | `8c7e4874` | GE_gemstones | plank 20, stoneScots 10 | gives gemstonesScots 1 | owner | 20 | 9000 | 5400 | 4 Exchange | yes |
| `sacrifice_GE_stoneScots` | `f4b62dc4` | GE_stone | gemstonesScots 1 | gives stoneScots 11 | owner | 20 | 6000 | 5400 | 4 Exchange | – |
| `sacrifice_GE_claymoreScots` | `3abb0cb4` | GE_claymoreScots | gemstonesScots 2, goldScots 3 | gives claymore 4 | owner | 20 | 9000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_whiskyScots` | `ef8c23f4` | GE_whiskyScots | fishScots 10, sheep 10 | gives whisky 3 | owner | 20 | 9000 | 3600 | 4 Exchange | – |
| `sacrifice_GE_kiltScots` | `a3977964` | GE_kiltScots | saltScots 6, water 12 | gives kilt 3 | owner | 20 | 6000 | 3600 | 4 Exchange | – |
| `sacrifice_strongerSoldierScots` | `335a3c43` | strongerSoldier | whisky 8, sheepHam 5, gemstonesScots 2 | SoldierDamage 140 | owner | 3000 | 9000 | 3600 | 3 Fight | – |
| `sacrifice_soldierHealScots` | `ec961034` | soldierHeal | gemstonesScots 6, bread 6 | SoldierHeal | owner | 20 | 12000 | 10800 | 3 Fight | – |
| `sacrifice_buildingArmorScots` | `43a1346d` | buildingArmor | ironScots 2, stoneScots 8, wood 4 | BuildingArmor 400 | owner | 3000 | 6000 | 3600 | 1 Military | – |
| `sacrifice_peaceTimeScot` | `da0f6d93` | peaceTime | saltScots 10, sheep 5, gemstonesScots 3 | PeaceTime | owner | 6000 | 9000 | 5400 | 1 Military | yes |
| `sacrifice_expandTerritoryScots` | `b3000463` | expandTerritory | toolScots 4, bread 2 | ExpandTerritory 5 | owner | 6000 | 3000 | 3600 | 1 Military | yes |
| `sacrifice_exploreEnemiesScots` | `7e8bf323` | exploreEnemies | goldScots 3, gemstonesScots 1, toolScots 2 | ExploreEnemy | enemy | 20 | 6000 | 5400 | 1 Military | – |
| `sacrifice_destroyShipsScots` | `b2b7e8bd` | destroyShips | gemstonesScots 3, stoneScots 10, coalScots 5 | DestroyShips | enemy | 20 | 9000 | 5400 | 2 Navy | – |
| `sacrifice_shipSpeedDownScots` | `703c5903` | shipSpeedDown | fishScots 4, ironScots 4 | ShipSpeed 2 | enemy | 3000 | 6000 | 3600 | 2 Navy | yes |
| `sacrifice_destroyShipsCheapScots` | `76ffba63` | destroyShips | kilt 1 | DestroyShips | enemy | 20 | 0 | 1000 | 2 Navy | – |

#### 2.8.4 Sacrifices in no tribe list [known: `sacrifices_campaign.lua`]

| Sacrifice (Lua name) | Id | `name` | Cost | Effect (`sf_addEffect`) | Target | Duration | Research | Regeneration | Category | Default |
|---|---|---|---|---|---|---|---|---|---|---|
| `sacrifice_olympicFlame` | `0eaff063` | olympicFlame | halberd 10, coinBav 10 | none | owner | 200000000 | 0 | 200000000 | 0 Economic | – |
| `sacrifice_indianWrestling` | `598903a3` | indianWrestling | oxen 2 | none | owner | 200000000 | 0 | 200000000 | 0 Economic | – |
| `sacrifice_stoneToDust` | `4c8b8e03` | StoneToDust | water 10, tool 2, goatHam 5 | none | owner | 20 | 0 | 200000000 | 0 Economic | – |
| `sacrifice_waterExchange` | `e30eb163` | waterExchange | milk 8, goat 5, coin 1 | gives water 20 | owner | 20 | 0 | 1800 | 0 Economic | – |
| `sacrifice_cursedArrow` | `98fa3447` | cursedArrow | goat 5 | none | owner | 20000000 | 0 | 20000000 | 1 Military | – |
| `sacrifice_woodExchange` | `6940d0f3` | woodExchange | gemstones 1 | gives wood 9 | owner | 20 | 0 | 3600 | 4 Exchange | – |
| `sacrifice_generateBeer` | `63d6fa13` | generateBeer | egyptCorn 6, water 6, gemstones 1 | none | owner | 20 | 0 | 1800 | 0 Economic | – |
| `sacrifice_pacifySachmet` | `fe5841a3` | pacifySachmet | milk 10, gemstones 1 | none | owner | 3000 | 0 | 100 | 0 Economic | – |

Notes [known: data]:

- Every good exchange has duration 20 and gives its goods when the duration has elapsed (threshold 1).
- Not abortable (`sf_setAbortable(false)`): every sacrifice with duration 20 (the exchanges, `soldierHeal`,
  `exploreEnemies`, `destroyShips`, the short campaign records) and the campaign markers `olympicFlame`,
  `indianWrestling`, `cursedArrow`, `pacifySachmet`. All others can be aborted: either the script says so or it
  does not call the setter, and the default is true.
- Three records call `sf_setForCampaign(…, true)`: `sacrifice_archerHitChanceCheap` (Bavarians, cost 1 water),
  `sacrifice_destroyShipsCheapScots` (cost 1 kilt) and `sacrifice_generateBeer` (in no tribe list).
  `tribes.lua` introduces the first two with the comment "ai cheat".
- Effect type 0 (`Effect_NoEffect`) marks records that exist for map scripts: the script reacts to the sacrifice
  itself. Durations of 20000000 and 200000000 ticks mean "never expires".
- The Bavarian list has no `sacrifice_workerPause` (the line is commented out); the Scots have it.
- A value such as `ProductionSpeed 75` is a percentage, `ShipSpeed 2` on an enemy a divisor, `ExpandTerritory 5`
  cells; the arithmetic per type is in [properties-data.md](properties-data.md) §3.9.

### 2.9 Animals and what a hunter gets

[known: `animals.lua`] Twelve animals: `animal_deer` `4a9bef83`, `animal_rabbit` `41797b76`, `animal_elk`
`706e7c94`, `animal_sheep` `62aeca33`, `animal_bear` `101fa572`, `animal_ox` `101fa573`, `animal_goat`
`101fa574`, `animal_polarbear` `101fa575`, `animal_mountainhare` `101fa576`, `animal_boar` `101fa577`,
`animal_camel` `101fa578`, `animal_highlandcattle` `101fa579`.

Source: ids = `an_create`; yields = the three `an_addStackGood(animal, tribe, good)` calls (two in the helper
`addBaseStack(animal)`, which every animal but the sheep goes through, one for the sheep); movement values =
`an_setRange`, `an_setMoveDistance`, `an_setMovementSpeed`; sheep extras = `an_setRespawn`, `an_setDyingTime`,
`an_setDisappearingTime` (all `animals.lua`). The call has no amount argument: it appends one good to the animal's
per-tribe list (`stackGoods`, [properties-data.md](properties-data.md) §2), and each tribe's list has one entry,
hence "1" [inferred].

| Animal | Yield for Bavarians | Yield for Egyptians | Yield for Scots |
|---|---|---|---|
| every animal except the sheep | `leather` 1 | `goatHam` 1 | nothing: not a target |
| `animal_sheep` | nothing: not a target | nothing: not a target | `sheep` 1 |

A hunter only targets animals that have a yield for its owner's tribe ([map-resources.md](map-resources.md),
hunting interface). The sheep also sets `an_setRespawn(false)`, dying time 1 and disappearing time 5. Movement
values: rabbit and mountain hare range 8, move distance 4, speed 0.07; sheep range 8, distance 4, speed 0.03;
all others range 6, distance 2, speed 0.045.

### 2.10 Start stock

[known: `tribes.lua`] `tp_addStartResources` is the default of a map's initial goods (maps store their own
list); `tp_addBonusResources` is the extra headquarters stock that
[players-victory.md](players-victory.md) §3.4 ("Starting stock") grants depending on the start-resources level.
Settler goods in these lists are soldiers standing in the headquarters.

Source: each entry is one `tp_addStartResources(tribe, good, amount)` or `tp_addBonusResources(tribe, good,
amount)` call in `tribes.lua`, in call order.

| Tribe | `tp_addStartResources` | `tp_addBonusResources` |
|---|---|---|
| bavarians | toolBav 25, wood 18, plank 30, stoneBav 20, corn 10, flour 8, fishBav 10, fleshham 8, pretzel 6, water 5, weissbeer 6, coalBav 8, ironBav 5, goldBav 2, halberd 3, ironOreBav 5, oxen 1, crossbow 3, leather 5, gemstonesBav 4, saltBav 5, good_soldierHalberd0 5, good_bowSoldierCrossBow0 5 | toolBav 15, wood 13, plank 18, stoneBav 11, corn 10, flour 12, fishBav 5, fleshham 5, pretzel 6, water 5, weissbeer 9, coalBav 5, ironBav 10, goldBav 6, coinBav 2, halberd 2, ironOreBav 5, oxen 4, crossbow 2, leather 5, gemstonesBav 2, saltBav 10, good_soldierHalberd0 3, good_soldierHalberd1 2, good_soldierHalberd2 1, good_bowSoldierCrossBow0 3, good_bowSoldierCrossBow1 2, good_bowSoldierCrossBow2 1 |
| egyptians | tool 25, wood 11, clay 30, stone 20, goat 5, egyptCorn 10, fish 10, milk 6, cheese 5, goatHam 8, cornBread 6, water 6, coal 8, iron 5, gold 3, sword 4, ironOre 5, bow 4, goatLeather 8, gemstones 4, salt 6, good_soldierSword0 7, good_bowSoldier0 7 | tool 15, wood 4, clay 18, stone 11, egyptCorn 10, fish 5, milk 9, cheese 5, goatHam 3, cornBread 6, water 6, coal 5, iron 10, gold 6, coin 4, sword 2, ironOre 5, bow 2, goatLeather 5, gemstones 2, salt 6, good_soldierSword0 3, good_bowSoldier0 3, good_bowSoldier1 2, good_bowSoldier2 1 |
| scots | toolScots 25, wood 18, plank 30, stoneScots 29, sheep 5, kilt 3, corn 10, flour 8, fishScots 10, bread 6, water 5, whisky 5, coalScots 8, ironScots 5, goldScots 1, claymore 2, ironOreScots 5, gemstonesScots 4, saltScots 5, good_soldierClaymore0 5, good_bowSoldierStone0 5 | toolScots 15, wood 13, plank 18, stoneScots 11, sheep 5, kilt 5, corn 10, flour 12, fishScots 5, sheepHam 8, bread 6, water 5, whisky 5, coalScots 6, ironScots 6, goldScots 3, coinScots 2, claymore 2, ironOreScots 5, gemstonesScots 2, saltScots 8, good_soldierClaymore0 2, good_soldierClaymore1 1, good_bowSoldierStone0 3, good_bowSoldierStone1 2 |

---

## 3. Rules and algorithms

The rules proper are specified in the sibling documents. This section states, per kind of building, which rule
turns a row of §2.4 into behaviour, and collects the content-level consequences.

### 3.1 How a building row becomes behaviour

Source of the table: the **Buildings** column is the grouping of the §2.4 rows by their `bp_setWorkingMode`
value (`buildings.lua`; 6 when the call is absent); every data value named in a cell (`bp_setPlantingDeposit`,
`bp_setProducedSettler`, recipes) is that call in `buildings.lua` or the `gp_addCost` list in `Goods.lua`; the
rules are tagged in the cells with the function they were read in.

| Mode | Buildings | What one cycle is | Specified in |
|---|---|---|---|
| 0 Foresting | `foresterBav`, `forester` | the worker walks to a free cell within the radius, works for the work time and plants the `bp_setPlantingDeposit` (`tree_10`, or a random tree type that fits the ground and the map's tree tag); no goods | [settlers-jobs.md](settlers-jobs.md) §3.5.5 `GoAfforest`; [properties-data.md](properties-data.md) §3.8 |
| 1 Mining | wood cutters, stone pits | the building links the nearest free deposit of the product's mining good within the radius; the worker walks there, works for the work time, harvests it and carries the output home. No input is requested or consumed | [village-buildings.md](village-buildings.md) §3.9; [settlers-jobs.md](settlers-jobs.md) `GoMining` |
| 2 Farming | `farmBav`, `farmClay`, `farm` | harvests (as mode 1) while a field is linked to the building, otherwise sows (as mode 0, planting `field_01` / `field_egypt`) [known: `Worker::StartMiningOrAfforestJob`]. A farm sows only when `Production::CanStartProduction` S 00565bd0 holds, i.e. the whole recipe is in stock: 1 `water` for `farmClay`, nothing for the other two. When the worker starts the sowing at its idle position or at the workplace work cell, `GoAfforest::Start` S 0077bcb0 starts a production cycle and the recipe is consumed and re-requested; when it starts from anywhere else, the field is planted without a cycle and nothing is consumed [known] | the same |
| 3 Fishing | `fisher`, `fisherClay`, `fisher2` | the worker walks to a shore cell within the radius, works for the work time, takes one unit of the fish resource near it and carries the output home | [settlers-jobs.md](settlers-jobs.md) `GoFishing` |
| 4 SettlerBreeding | `oxenBreeding`; the barracks | the produce action of mode 6; instead of carrying the product out, the worker then releases settlers of the `bp_setProducedSettler` good, one whenever the building's spawn cooldown is 0, while the building can supply them, and rests when it cannot (`Worker::Update` S 0065d7f0). A ware that is still in the building when the worker next chooses work is carried out first, as in every mode (`ChooseNextWork` S 0065d660). `oxenBreeding`: 1 water → 1 `oxen` ware → 1 `good_oxen` settler. Barracks (no produced settler): §3.5 | [settlers-jobs.md](settlers-jobs.md) §3.5.2 |
| 5 Catapult | catapults | the worker turns the catapult, and if a target and ammunition are present fires; one shot removes one unit of the tribe's stone (S 005678b0; not while the cinematic flag is set) | [military.md](military.md) §3.10 |
| 6 Producing | workshops, springs, `goatBreeder`, mines | when the input stock holds the whole recipe: consume it, re-request it, work for the work time, add the output to the output stock; the worker carries it to the flag, then rests for the rest time. Mines: §3.4 | [village-buildings.md](village-buildings.md) §3.7, §3.8 |
| 7 Hunting | `hunter`, `hunterClay`, `hunterScots` | the building links the nearest huntable animal within the radius: alive, not reserved, with a yield for the owner's tribe and on a cell the owner has explored (`HuntableAnimalSearch::IsTarget` S 00542c40). The worker walks to it, kills it on arrival, works for the work time (`GoHunting::Update` S 0077cba0) and carries home the animal's yield for the tribe (§2.9), which replaces the product of the row | [map-resources.md](map-resources.md), hunter sequence |
| 8 Idling | watch towers | the worker moves in; nothing else. The building uncovers the map within its sight radius | [village-buildings.md](village-buildings.md) §3.14 |
| 9 Sacrifice | temples, Olympic flame | no worker action; the building runs the sacrifice component (§3.7) | this document §3.7 |
| 10 AnimalBreeding | `sheepBreeding` | the produce action of mode 6 (1 water → 1 `sheepAnimal`) without the carrying trip; then the product entry is removed from the output stock again and an animal of the `bp_setProducedSettler` id (`animal_sheep`) is put on the map at the building cell (`Worker::Update` S 0065d7f0). No cycle starts while 20 or more animals are counted in the area around the building (`CanStartProduction` S 00565bd0) | [village-buildings.md](village-buildings.md) §3.7; [settlers-jobs.md](settlers-jobs.md) §3.5.2 |
| 11 Scholar | scholar huts | the worker (the geologist) makes up to 10 digs per trip around the building (`GoDigging::Start` S 0077b170; the trip ends early when production is switched off), each an animation of 80 ticks (`DigForResources::Start` S 0077e840), and plants a sign for what the cell holds | [settlers-jobs.md](settlers-jobs.md) `GoDigging`; [map-resources.md](map-resources.md) |

[known: `Production::StartProductionCycle` S 005657c0] The recipe is taken from the good in product slot 0
only. The function has two callers: the produce action (`ProduceGood::Start` S 00777460; modes 4, 6, 10 by
`Worker::ChooseNextWork` S 0065d660) and the sowing action (`GoAfforest::Start` S 0077bcb0), the latter only
for a building with a product (`Production::ProducesGoods` S 00565550) and only on the branch described for
mode 2; a forester (mode 0) has no product, so it never reaches the function. For a `casern` type the function
starts the training component instead (§3.5) and reads no recipe. It has no test of `ignoreGoodCosts`: the flag
acts on the request side (`RequestAllInputs` S 00565a70, [village-buildings.md](village-buildings.md) §3.7),
which is why a recipe in parentheses in §2.4 is never delivered. For modes 1 and 7 the function is not reached
at all.

### 3.2 Cycle length

[inferred from the rules above] For a mode-6 building with inputs in stock, one cycle takes

```
work ticks (× the owner's production-speed factor, modes 6 and 10 only)
+ the trip that carries the product(s) to the flag and back
+ trunc(rest ticks × the owner's worker-pause factor)
```

[known] The work time is `bp_setProductionTime` unscaled for every mode but 6 and 10
(`Production::GetProductionDuration` S 00565ed0); the rest counter is set to the truncated product and counted
down by 1 per tick (`Rest::Start` S 0077b6d0, `Rest::Update` S 0077b630). Both factors are 1.0 without
sacrifices ([properties-data.md](properties-data.md) §3.9). With the common values
333 / 55 that is 388 ticks plus the carrying trip, about 40 seconds at speed 1. For the gathering modes (0, 1,
2, 3, 7) the walk to the work place and back is added, and the work time is the time spent at the work place.
The shipped values group as follows [known: `buildings.lua`: `bp_setProductionTime` / `bp_setRestTime` of every
type, grouped by equal pairs; the same numbers as the "Work / rest ticks" column of §2.4]:

| Work / rest | Buildings |
|---|---|
| 333 / 55 | every workshop and mine not listed below, springs, scholar huts, barracks, `oxenBreeding`, `sheepBreeding` |
| 333 / 222 | `tanneryClay`, `sheepButcher` |
| 333 / 600 | `smithyClay` (the Egyptian sword smith) |
| 100 / 55 | `goatBreeder` |
| 55 / 222 | wood cutters and foresters of Bavarians and Scots |
| 55 / 333 | `woodCutterClay` |
| 55 / 55 | stone pits |
| 333 / 770, 333 / 1111, 333 / 800 | fishers: `fisher`, `fisherClay`, `fisher2` |
| 55 / 1500 | `hunter`, `hunterClay` |
| 0 / 222 | `hunterScots` (the herder) |
| 83 / 355, 83 / 1000, 83 / 55 | farms: `farmBav`, `farmClay`, `farm` |
| 25 / 55 | catapults (25 is the shot) |

A field takes its own time to ripen: `field_01` has `dp_setGrowingStartSize` 0.2 and `dp_setGrowingSpeed`
0.00075, `field_egypt` 0.2 and 0.0005, both `dp_setLifeTime` 3000 [known: `deposits.lua`; the growth rule is
in [map-resources.md](map-resources.md)].

### 3.3 The production chains

One line per producing building: `inputs -> [building] -> output per cycle -> consumers`. "(food)" marks a mine
that accepts the good as one alternative of its food group. "construction" means the good is in a cost list of
a building of the tribe; "temple" that at least one sacrifice of the tribe costs it. [known: generated from
`Goods.lua`, `buildings.lua`, `Jobs.lua`, `tribes.lua` and the sacrifice scripts]

Bavarians:

```
[woodCutterBav] -> 1 wood -> sawMillBav; crossbowSmithery; mintBav; temple
[stonePitBav] -> 1 stoneBav -> catapultBav; construction; temple
[fisher] -> 1 fishBav -> ironMineBav (food); coalMineBav (food); stoneMineBav (food); saltMineBav; temple
wild animal -> [hunter] -> 1 leather -> crossbowSmithery; temple
[spring] -> 1 water -> brauhaus; oxenBreeding; temple
1 foodBav -> [ironMineBav] -> 1 ironOreBav -> smelteryBav
2 foodGoldBav -> [goldMineBav] -> 1 goldBav -> mintBav; temple
1 foodBav -> [coalMineBav] -> 1 coalBav -> smelteryBav; halberdSmithy; temple
1 foodStoneBav -> [stoneMineBav] -> 1 stoneBav -> catapultBav; construction; temple
3 foodGoldBav -> [gemMineBav] -> 1 gemstonesBav -> temple
1 fishBav -> [saltMineBav] -> 1 saltBav -> bakerypretzel; temple
1 wood -> [sawMillBav] -> 1 plank -> locksmitheryBav; construction; temple
1 corn -> [millBav] -> 1 flour -> bakerypretzel
1 ironOreBav + 1 coalBav -> [smelteryBav] -> 1 ironBav -> locksmitheryBav; halberdSmithy; temple
1 plank + 1 ironBav -> [locksmitheryBav] -> 1 toolBav -> every worker and builder; temple
1 ironBav + 1 coalBav -> [halberdSmithy] -> 1 halberd -> barracks: good_soldierHalberd0
1 wood + 1 leather -> [crossbowSmithery] -> 1 crossbow -> barracks: good_bowSoldierCrossBow0
1 saltBav + 1 flour -> [bakerypretzel] -> 2 pretzel -> ironMineBav (food); goldMineBav (food); coalMineBav (food); stoneMineBav (food); gemMineBav (food); temple
1 water + 1 corn -> [brauhaus] -> 2 weissbeer -> sauerey; barracks: good_soldierHalberd0, good_bowSoldierCrossBow0; temple
1 goldBav + 1 wood -> [mintBav] -> 1 coinBav -> barracks: promotion
1 stoneBav -> [catapultBav] -> one shot (the slot good catapultStoneBav is never created)
[farmBav] -> 2 corn -> millBav; brauhaus; sauerey; temple
1 weissbeer + 1 corn -> [sauerey] -> 1 fleshham -> ironMineBav (food); goldMineBav (food); coalMineBav (food); gemMineBav (food)
1 water -> [oxenBreeding] -> 1 oxen -> second carrier good_oxen; temple
```

Egyptians:

```
[woodCutterClay] -> 1 wood -> locksmitheryClay; bowSmithery; construction
[stonePitClay] -> 1 stone -> catapultClay; construction; temple
[fisherClay] -> 1 fish -> ironMineClay (food); stoneMineClay (food); gemMineClay (food); temple
wild animal -> [hunterClay] -> 1 goatHam -> ironMineClay (food); saltMineClay (food); temple
[springClay] -> 1 water -> brickyard; farmClay; temple
1 foodIronOreEgypt -> [ironMineClay] -> 1 ironOre -> smelteryClay
2 foodGoldEgypt -> [goldMineClay] -> 1 gold -> mintClay; temple
1 cheese -> [coalMineClay] -> 1 coal -> mintClay; temple
2 foodStoneEgypt -> [stoneMineClay] -> 2 stone -> catapultClay; construction; temple
4 foodGemstonesEgypt -> [gemMineClay] -> 1 gemstones -> temple
1 foodSaltEgypt -> [saltMineClay] -> 1 salt -> tanneryClay; cheeseDairyClay; temple
1 water -> [brickyard] -> 1 clay -> construction; temple
1 milk + 1 egyptCorn -> [bakeryClay] -> 1 cornBread -> goldMineClay (food); saltMineClay (food); temple
1 ironOre -> [smelteryClay] -> 1 iron -> locksmitheryClay; smithyClay; temple
1 wood + 1 iron -> [locksmitheryClay] -> 1 tool -> every worker and builder; temple
1 iron -> [smithyClay] -> 1 sword -> barracks: good_soldierSword0
1 wood + 1 goatLeather -> [bowSmithery] -> 1 bow -> barracks: good_bowSoldier0
1 goat + 1 salt -> [tanneryClay] -> 1 goatLeather -> bowSmithery; temple
1 milk + 1 salt -> [cheeseDairyClay] -> 1 cheese -> goldMineClay (food); coalMineClay; stoneMineClay (food); gemMineClay (food); temple
1 gold + 1 coal -> [mintClay] -> 1 coin -> barracks: promotion
1 stone -> [catapultClay] -> one shot (the slot good catapultStone is never created)
1 water -> [farmClay] -> 1 egyptCorn -> bakeryClay; temple
[goatBreeder] -> 1 goat -> tanneryClay; temple
              -> 1 milk -> bakeryClay; cheeseDairyClay; barracks: good_soldierSword0, good_bowSoldier0; temple
```

Scots:

```
[woodCutter] -> 1 wood -> sawMill; locksmithery; temple
[stonePit] -> 1 stoneScots -> catapult; construction; barracks: good_bowSoldierStone0; temple
[fisher2] -> 2 fishScots -> ironMine; coalMine (food); saltMine (food); temple
1 water -> [sheepBreeding] -> 1 sheepAnimal -> removed again; an animal_sheep is put on the map
animal_sheep -> [hunterScots] -> 1 sheep -> kiltSewing; sheepButcher; temple
[springScots] -> 1 water -> sheepBreeding; whiskyBrewery; temple
1 fishScots -> [ironMine] -> 1 ironOreScots -> smeltery
1 sheepHam -> [goldMine] -> 1 goldScots -> mint; temple
1 foodScots -> [coalMine] -> 1 coalScots -> smeltery; claymoreSmithy; mint; temple
1 bread -> [stoneMine] -> 1 stoneScots -> catapult; construction; barracks: good_bowSoldierStone0; temple
3 foodGemstonesScots -> [gemMine] -> 1 gemstonesScots -> temple
1 foodSaltScots -> [saltMine] -> 1 saltScots -> sheepButcher; temple
1 wood -> [sawMill] -> 1 plank -> construction; temple
1 corn -> [mill] -> 1 flour -> bakery
1 ironOreScots + 1 coalScots -> [smeltery] -> 1 ironScots -> locksmithery; claymoreSmithy; temple
1 wood + 1 ironScots -> [locksmithery] -> 1 toolScots -> every worker and builder; temple
1 ironScots + 1 coalScots -> [claymoreSmithy] -> 1 claymore -> barracks: good_soldierClaymore0
1 sheep -> [kiltSewing] -> 1 kilt -> barracks: good_soldierClaymore0, good_bowSoldierStone0; temple
1 flour + 1 corn -> [bakery] -> 1 bread -> coalMine (food); stoneMine; gemMine (food); saltMine (food); temple
1 sheep + 1 saltScots -> [sheepButcher] -> 1 sheepHam -> goldMine; coalMine (food); gemMine (food); temple
1 water + 1 corn -> [whiskyBrewery] -> 1 whisky -> barracks: good_soldierClaymore0, good_bowSoldierStone0; temple
1 goldScots + 1 coalScots -> [mint] -> 1 coinScots -> barracks: promotion; temple
1 stoneScots -> [catapult] -> one shot (the slot good catapultStoneScots is never created)
[farm] -> 1 corn -> mill; bakery; whiskyBrewery
```

End products per tribe [known: data]:

- **Construction**: plank and stone (Bavarians, Scots); clay and stone (Egyptians). Small buildings and mines
  cost only the first material (2 units, 4 for mines, 3 for the guard house), except `sheepBreeding` (2 planks
  + 1 stone). Medium and large buildings take the first material for the frame and stone for the second phase;
  the catapult takes 1 more unit of the first material in the second phase. Ship-building sites: 12 planks, or
  12 wood for Egyptians.
- **Settlers**: one tool per worker or builder.
- **Soldiers**: weapon and drink (plus a kilt for Scots; three stones instead of a weapon for a slinger), then
  one coin per promotion.
- **Mine food**: §3.4.
- **Temple**: the costs of §2.8.
- **Catapult**: one stone per shot.
- `gemstones*` have no consumer but the temple: 10 Bavarian, 11 Egyptian and 10 Scottish `sf_addCost` lines of
  the tribe's sacrifices name the tribe's gemstones; 3 more name the Egyptian `gemstones` in campaign records
  that are in no tribe list (`woodExchange`, `generateBeer`, `pacifySachmet`). `leather` (Bavarians) feeds only
  the crossbow maker and the temple.

### 3.4 Mines and their food

[known: `Goods.lua`, `buildings.lua`; rule in [village-buildings.md](village-buildings.md) §3.8] A mine is a
mode-6 building of size `SizeMine`. Its radius 3 is the search radius for a cell that holds the product's
mining good; a staffed mine without a linked cell repeats the search every 101 ticks
(`Building::UpdateResourceSearch` S 0055ded0) [known]. The recipe of its product is its food:

Source of the table: *derived* from two files. A cell is the `gp_addCost(product, food, amount)` list
(`Goods.lua`) of the mine's `bp_setGoods` product (`buildings.lua`); "1 of X (a, b)" means the cost names a
good X of kind 3 (`gp_setType`, either-group) and a, b are X's own `gp_addCost` members that are in the tribe's
`tp_addGood` list (`tribes.lua`); "yields n" is the amount argument of `bp_setGoods`.

| Mine | Bavarians | Egyptians | Scots |
|---|---|---|---|
| Iron | 1 of `foodBav` (fishBav, fleshham, pretzel) | 1 of `foodIronOreEgypt` (fish, goatHam) | 1 `fishScots` |
| Gold | 2 of `foodGoldBav` (fleshham, pretzel) | 2 of `foodGoldEgypt` (cheese, cornBread) | 1 `sheepHam` |
| Coal | 1 of `foodBav` | 1 `cheese` | 1 of `foodScots` (fishScots, sheepHam, bread) |
| Stone | 1 of `foodStoneBav` (fishBav, pretzel) | 2 of `foodStoneEgypt` (fish, cheese), yields 2 stone | 1 `bread` |
| Gemstones | 3 of `foodGoldBav` | 4 of `foodGemstonesEgypt` (fish, cheese) | 3 of `foodGemstonesScots` (sheepHam, bread) |
| Salt | 1 `fishBav` | 1 of `foodSaltEgypt` (goatHam, cornBread) | 1 of `foodSaltScots` (fishScots, bread) |
| Stock limit | 2, gemstones 3 | 2, gemstones 4 | 2, gemstones 3 |

The alternatives are written in the order in which the mine tries them. That order is the tribe's `tp_addGood`
order, not the order of the group's own cost list [known: S 005657c0 walks `PropertyGroupIter`, which
enumerates the tribe's goods; [properties-data.md](properties-data.md) §3.4]. For a group input of amount `n`
the mine takes, `n` times, one unit of the first alternative it has in stock, and re-requests that same good;
a unit for which no alternative is in stock is skipped without a request [known: S 005657c0]. The function
takes this branch when the **first** entry of the recipe is an either group (`gp_setType` 3) and then looks
at that entry only; every other recipe is removed and re-requested as a whole list. All shipped group recipes
have one entry. A mine eats only under the "must eat" condition of
[village-buildings.md](village-buildings.md) §3.8 (start-resources level and the `MinerNeedNoFood` sacrifice).

### 3.5 Soldiers: training and promotion

[known: `Jobs.lua`, `military.lua`, `buildings.lua`, `tribes.lua`; rules in [military.md](military.md) §3.4]

Source, per row: the barracks in the header = the tribe's `tp_addBuilding` type with `bp_setCasern`
(`tribes.lua`, `buildings.lua`); recruit cost = the `gp_addCost` list of the level-0 good of the kind
(`Jobs.lua`, the good from `mi_setSoldierId(tribe, kind, 0, good)` in `military.lua`); promotion = the
`gp_addCost` list of the higher rank (previous rank good + the tribe's `tp_setSoldierUpgradeGoodId` coin);
highest level = the largest `level` argument of the tribe's `mi_setSoldierId` calls for the kind.

| | Bavarians (`casernHalCross`) | Egyptians (`casernSwordBow`) | Scots (`casernClayStone`) |
|---|---|---|---|
| Melee recruit | 1 halberd + 1 weissbeer | 1 sword + 1 milk | 1 claymore + 1 kilt + 1 whisky |
| Ranged recruit | 1 crossbow + 1 weissbeer | 1 bow + 1 milk | 3 stoneScots + 1 kilt + 1 whisky |
| Promotion | previous rank + 1 coinBav | previous rank + 1 coin | previous rank + 1 coinScots |
| Highest level melee / ranged | 2 / 2 | 0 / 2 | 2 / 1 |

The barracks has two training slots (melee, ranged; each holds the tribe's level-0 soldier good of that kind)
and one promotion switch; one cycle (333 work, 55 rest) can train one recruit and promote one soldier. The
slots take turns: a cycle begins with the slot after the one the previous cycle ended on (melee in a new
building), then tries the other, and starts the first one that is switched on, has its whole cost in the
input stock and is not locked for the player
[known: `SoldierTraining` ctor S 00566740, `VillageSoldierTraining_StartNext` S 00566920,
`VillageSoldierTrainingSlot_CanStart` S 00569cb0]. The Egyptian swordsman cannot be promoted (level 0 is its
highest). The headquarters is a `casern` type too, but for a type that is both `territoryBuilding` and `depot`
the two slots and the promotion switch are switched off at placement [known: `Building::ctor_Place`
S 0055d980] ([military.md](military.md) §3.4).

### 3.6 Tribe-specific buildings and mechanics

[known: data; the mechanics as specified in the documents named]

**Bavarians**

- `oxenBreeding` (large): 1 water → 1 `oxen`, which the breeder releases as a `good_oxen` settler (the settler
  good costs 1 `oxen`). `good_oxen` is the pack animal that an upgraded street orders as its second carrier
  ([streets-transport.md](streets-transport.md) §3.7; [village-buildings.md](village-buildings.md) §3.11).
- `brauhaus`: 1 water + 1 corn → **2** `weissbeer`; beer is the soldiers' drink and an input of the butcher.
- `sauerey` (large, name `"Butcher"`): 1 weissbeer + 1 corn → 1 `fleshham`. No animal is involved.
- `bakerypretzel`: 1 saltBav + 1 flour → **2** `pretzel`; salt is mined with fish.
- `hunter`: every wild animal yields `leather`, not food; leather goes into crossbows.
- `farmBav` harvests **2** corn per field.
- Coins are minted from gold and **wood**; the tool takes a **plank**, not wood.

**Egyptians**

- `brickyard`: 1 water → 1 `clay`. Clay replaces planks, so water is the base of all construction
  (`water` has AI weight 300, `clay` 500).
- No forester and no sawmill; ships and tools take raw `wood` (§2.4 note).
- `farmClay`: consumes 1 water per sowing, yields 1 `egyptCorn`; stock limit 6; rest time 1000.
- `goatBreeder` (large): the only building with two products, 1 `goat` **and** 1 `milk` per cycle, no input,
  work time 100.
- `tanneryClay`: 1 goat + 1 salt → `goatLeather` (for bows). `cheeseDairyClay`: 1 milk + 1 salt → `cheese`.
  `bakeryClay`: 1 milk + 1 egyptCorn → `cornBread`; there is no mill.
- `hunterClay`: every wild animal yields `goatHam`, the only source of that good besides an exchange.
- `smelteryClay` needs no coal (iron = ore); coal goes only into coins.
- `stoneMineClay` yields 2 stone per cycle for 2 food.
- Second carrier `good_helper`: an upgraded street gets a second ordinary carrier, at no cost.
- Military: larger garrisons (4 / 8 / 12) and sturdier buildings, one sword rank, three bow ranks.

**Scots**

- The sheep cycle: `sheepBreeding` (small; 1 water per cycle) puts live sheep on the map, at most 20 animals in
  its area; `hunterScots` (name `"HerdHut"`, worker `good_sheepherd`, work time 0, rest 222) fetches a sheep
  and delivers 1 `sheep`; `kiltSewing` turns 1 sheep into 1 `kilt`; `sheepButcher` turns 1 sheep + 1 saltScots
  into 1 `sheepHam`. Wild animals yield nothing for Scots.
- Every recruit needs a `kilt`; the slinger needs 3 `stoneScots` and has no weapon good.
- `fisher2` delivers **2** fish per catch.
- `whiskyBrewery`: 1 water + 1 corn → 1 `whisky` (the Bavarian brewery yields 2).
- No second carrier: a Scottish street is never upgraded with one.
- Fastest ships (0.12), smallest garrisons (2 / 4 / 6).

**All tribes**

- Scholar hut (`scholarHutBav`, `scholarHutEgypt`, `scholarHut`): a small building whose worker is the
  geologist. Signs are planted for coal, iron ore, gold, stone, gemstones, salt (four sizes) and water
  ([properties-data.md](properties-data.md) §3.10).
- Watch tower: a small building that only uncovers the map (sight 16).
- Guard house → tower → fortress by upgrade ([village-buildings.md](village-buildings.md) §3.13).
- Catapult: medium building, range 12, damage 10.

### 3.7 The temple

[known: the functions named] A temple is a building of working mode 9 with the `VillageSacrifice` component.
Component states: 0 recharging, 1 a sacrifice of this temple is running, 2 ready, 3 ordered.

1. **Offer.** The panel offers the map's sacrifice list for the owner's tribe; its default is the tribe's
   `tp_addAllowedSacrifice` list ([properties-data.md](properties-data.md) §2.3).
2. **Research.** A sacrifice with a research duration above 0 must be researched once per player before it can
   be ordered. A player has one research record; it is tied to a temple and completes when
   `tick - startTick >= researchDuration` (`SacrificeResearch::Update` S 0065ff00, `ai::logic::SacrificeResearch::Complete` S 0065fde0:
   message `!Sacrifice Researched`, the id is recorded in the player's researched set). The panel and the AI
   start a research only when `VillageSacrifice::GetResearchState` S 005610c0 returns 0: the sacrifice needs
   research, no research of the player is running and it is not researched yet. The lockstep handler
   S 00782700 itself refuses only a temple at which the running research is tied; for another temple it calls
   `SacrificeResearch::Start` S 0065fae0, which overwrites the record (definition, start tick, temple) [known].
   [inferred] Research costs no goods: `Start` only records the definition, the tick and the temple.
3. **Order** (`VillageSacrifice::CheckCanOrder` S 00561240, `Order` S 00561410). Refused when, in this order:
   the temple is not ready (state 2); a research is running at this temple; the sacrifice needs research that
   is not done; it is regenerating for the player; a building dependence is unmet (never the case: the
   dependence lists are empty, [properties-data.md](properties-data.md) §2.7); it targets enemies and the owner
   has none; it is locked for the owner. Ordering files one ware request per unit of the cost list at the
   temple and sets state 3. For a sacrifice against enemies every other player is told (`!Player orders
   sacrifice`, `!Sacrifice ordered`).
4. **Start** (`CheckCanStart` S 00560f20, `ai::village::VillageSacrifice::Start` S 005615e0). Refused when, in this order:
   nothing is ordered; a sacrifice of this temple runs; the temple is in state 0; the input stock does not hold
   the whole cost list (skipped for an order made with a free ticket, which `Order` takes from a per-player
   counter instead of requesting goods); the sacrifice is regenerating; the player already runs a sacrifice of
   the same definition; it targets enemies and there are none; it is locked. The start comes from the player's
   command (with the chosen target player for a sacrifice against enemies), from the AI or from a map script.
   `ai::village::VillageSacrifice::Update` S 00561940 starts an ordered sacrifice by itself, as soon as `CheckCanStart`
   allows it, only for a building type with `constructionTime < 1` that is not at once `depot`, `casern` and
   `territoryBuilding` (the headquarters), which in the data is the Olympic flame. Starting tells the target
   player (`!Player started a sacrifice against you!`, `!A Sacrifice is targeted at you!`) for a sacrifice
   against enemies, creates the running sacrifice, **empties the temple's whole input stock** and sets
   state 1 (`ai::village::VillageSacrifice::Start` S 005615e0).
5. **Running.** Modifier effects hold for the duration; one-shot effects fire at their threshold
   ([properties-data.md](properties-data.md) §3.9). The sacrifice ends when `tick - startTick >= duration`
   (`ai::logic::Sacrifice::IsExpired` S 00660050).
6. **End** (`SacrificePlayerData::RemoveSacrifice` S 006620a0, `VillageSacrifice::OnExpired` S 00561870). The
   definition is entered in the owner's regeneration set with the current tick; the temple goes to state 0 and
   becomes ready again (state 2, the ordered definition cleared) on the first building update at which its
   output stock (`Depot.stockB`, depot `+0x28`) holds no good at all: `ai::village::VillageSacrifice::Update` S 00561940 tests
   the entry count of that stock's map (`Stock +0x10`, [logic-core.md](logic-core.md) §2.5) [known]. An entry leaves the regeneration set when `tick - entryTick >=
   regenerationDelay` (`SacrificeRegenerations_RemoveExpired` S 00662720). Regeneration is per player and
   definition, not per temple.

Lockstep commands: [game-commands.md](game-commands.md), `0x20024`–`0x20027`.

### 3.8 The Olympic flame and the campaign records

[known: `buildings.lua`, `sacrifices_campaign.lua`] `sacrificeOlympicFlame` (`287a5c71`, name
`"SacrificeOlympicFlame"`, graphics `"OlympicFlame"`, large) is in every tribe's building list but has
`bp_setConstructionTime(-1)`: a player cannot build it; it stands on maps (the campaign map scripts `C01`,
`C04` and `C06` refer to the flame or its sacrifice). It is a sacrifice building with territory range 4 and
health 60, without the `territoryBuilding` flag. Its
matching record `sacrifice_olympicFlame` (`0eaff063`) costs 10 `halberd` and 10 `coinBav`, never expires and has
no effect of its own. The other campaign records of §2.8.4 are used the same way: a map script watches for the
sacrifice and reacts. [known] None of the functions on the order and start path reads the building's worker
count (the order command S 00782510, `CheckCanOrder` S 00561240, `Order` S 00561410, `CheckCanStart`
S 00560f20, `ai::village::VillageSacrifice::Update` S 00561940, which `Building::Update` S 0055e2f0 calls for every finished
mode-9 building, and `ai::village::VillageSacrifice::Start` S 005615e0); [inferred] the flame and the temples accept and run a
sacrifice without their worker.

### 3.9 Oddities of the data

[known: data] Facts a faithful conversion must keep and a reader should not mistake for errors of this
document:

- `woodCutter*` set the working radius twice (5, then 6); the later call wins. `stonePit*` set `bp_setAiScore`
  50 twice.
- The stone pits carry a recipe they never use (§2.3 note); `hunterScots` carries the recipe `sheepAnimal` 1 it
  never uses.
- `casernHalCross`, `casernSwordBow`, `casernClayStone`, the temples and the Olympic flame set
  `bp_setWorkerLimit(…, 1)` explicitly; 1 is also the default.
- `spring*`, `scholarHut*` and `watchTower*` have no stock limit and no weight; they are not part of the goods
  distribution.
- Unreachable records: the goods `gripper` and `boat`; the professions listed at the end of §2.5.
- [inferred] The `tp_addSacrifice` lists (the rows of §2.8) have no reader: in the function cache the vector
  `TribeProperty.sacrifices` is touched only by the constructor and by `TribeProperty::AddSacrifice`
  S 00556400 ([properties-data.md](properties-data.md) §2.3). What a temple offers is the map's list, whose
  default is `tp_addAllowedSacrifice` (the rows marked "yes").

---

## 4. Update order

The content is static. It is created once at start-up, when `CApplicationEx::Initialize` S 004075d0 calls
`PropertiesDb::RunPropertyScript("data")` S 0054f8d0 (its only caller) [known]
([../data-loading.md](../data-loading.md) §1), in the script order of §2.1, and is only read afterwards. Nothing
in it changes per tick or per frame.

Order constraints inside the load [known: data and the bindings named]:

1. `defineTribes` first: every later script uses the tribe ids as keys.
2. `goods` before `config`: `cfg_setSacrificeGoodId(sacrificeGood)` passes the Lua global that `Goods.lua`
   assigned; the binding S 0054c180 only stores the number.
3. `goods` and `config` before `sacrifices`: every `sf_addCost(sacrifice, good, n)` S 0054f520, besides adding
   `{good, n}` to the sacrifice's cost list, looks up the record of the configured sacrifice good and adds
   `{good, 1}` to **its** cost list, and also `{arrangementGoodId of good, 1}` when that id differs from `good`
   (it is read from the good's record at that moment). The additions go through the merge rule of
   `GoodAmountList_AddAmount` S 00552aa0, so the amount of an entry of `sacrificeGood` counts the `sf_addCost`
   calls that named the good.
4. `goods` before `jobs` (tool costs, carried models), both before `buildings`, `military`, `ship` and `tribes`.
5. `jobs` before `military`: `mi_setSoldierId` S 00554290 copies the rank's health (`gp_setHealth`, good record
   `+0x88`) into the soldier table at that moment; a later `gp_setHealth` does not reach the table.
6. `tribes` near the end: its lists name goods, jobs, buildings and sacrifices, and `tp_addSacrifice`
   (`TribeProperty::AddSacrifice` S 00556400) looks the sacrifice record up before it appends the id.
   `tp_addAllowedSacrifice` S 0054b0c0 appends the id without a lookup.

The load order itself is in [properties-data.md](properties-data.md) §4; it is repeated here because a converter
that reorders the scripts breaks the content.

---

## 5. Inputs and outputs

Consumes: the property scripts (§6).

Produces: the records of the property database. Who reads which part of the content:

| Content | Reader | Document |
|---|---|---|
| Tribe lists (goods, buildings) | build menu, goods panels, statistics, producer and consumer searches | [properties-data.md](properties-data.md) §3.5; [ingame-ui.md](ingame-ui.md) |
| Building rows | placement, construction, production, storage | [village-buildings.md](village-buildings.md) |
| Worker, working mode, times, radius | worker state machine | [settlers-jobs.md](settlers-jobs.md) |
| Recipes, product slots | production cycle; AI planning of needs | [village-buildings.md](village-buildings.md) §3.7; [ai-player.md](ai-player.md) |
| Soldier ranks, garrisons, territory, catapult | fights, barracks, territory | [military.md](military.md) |
| Ship values, ship sites | navy | [navy.md](navy.md) |
| Sacrifices | temple component, modifier tables, AI | §3.7; [properties-data.md](properties-data.md) §3.9 |
| Start and bonus stock | `tp_addStartResources`: the default of a map's own initial-goods list (§7); `tp_addBonusResources`: read directly when a headquarters is filled (`NVillage::Depot::AddInitialStock` S 0055b020) | [players-victory.md](players-victory.md) §3.4 |
| Transport ranks | default transport priorities of a player | [streets-transport.md](streets-transport.md) |

Ids of the content that the **code names literally**, so that these records cannot be renumbered or left out.
The list is complete for the decompiled function cache, which was searched for the id of every record the 22
scripts create [inferred: an id held in a data table would not show up]. A byte search of the image for the
other two tribe ids and for `weapons`, `boat` and `shipEgyptCosts` finds nothing [known]. For `wood`, `stone` and
`fish` the AI rules compare the id with the **mining good** of a building's product (`gp_setMiningGood`, good
record `+0xbc`: `stoneBav` and `stoneScots` → `stone`, `fishBav` and `fishScots` → `fish`, `wood` → `wood`) or with
the good of the planted deposit, not with the product id itself [known].

| Record | Id | Where |
|---|---|---|
| `corn` | `17626a03` | product amount: a product slot holding exactly this good goes through the corn-doubling modifier (`SacrificePlayerTableRef::GetEntryWithModifiers` S 00661c50); `egyptCorn` (`4a852f49`) does not |
| `wood` | `cd6ec133` | a deposit of this good being worked gets a time-to-live (`NMovie::Working::Start` S 0077eda0); the free-deposit search skips depleted, growing or temporary deposits for the wanted goods wood and stone only (`FreeResourceSearch::IsTarget` S 00542a30); AI: the forester type is the tribe building whose planting deposit holds wood (S 0059f6f0), the cell-clearing rule uses the mode-1 building whose product's mining good is wood (S 0059f9d0), and a building with product `wood` is not demolished while it is the only one in its AI cell (S 0058dae0); graphics: the felling animation of a mode-1 worker (`S2CG::CharacterWorker::Update` S 006c8ab0) |
| `stone` | `55e952d3` | the free-deposit search (S 00542a30, as for wood); AI: the mode-1 building whose product's mining good is stone (S 0059fa60) and the mine (size 8, mode 6) whose product's mining good, or else whose product, is stone (`AiTribe_FindMode6Size8BuildingForResource` S 0059f850, called with this id by `NAI::FoodArrangement` S 0058cc60, S 0058cc80) |
| `fish` | `4012e5a3` | the fishing search counts cells of this resource within `cfg_setFishingDistance` (S 00780300); a map cell can hold this resource only on water and no other resource there (`MapModifier::CanHoldResourceAtCell` S 00674210); AI: the mode-3 building whose product's mining good is fish (S 0059fb80) and two resource-map rules (S 0059c240, S 00587600) |
| `water` | `a9676263` | the geologist's sign and message for a cell with the water flag (S 0077b2f0); the AI resource map leaves it out (S 00587e90) |
| `ship` | `1d66b4ae` | the AI's key for a ship-building site, for every tribe (`NAI::ShipConstruction` S 005a5d00, S 005a59d0) |
| `good_helper` | `7bff15ce` | the carrier: a street spawns or orders it (S 00668be0, S 00668e10) and a building sends a ware out with one (`NTransport::System::SpawnCarrierWithPackage` S 0064d020) |
| `good_oxen` | `d4157c5f` | graphics: a carrier of this good gets the donkey character and type name (S 00695490, S 006c8d60, S 006c8db0) |
| `good_explorer`, `good_scholar` | `a07bf6fe`, `3355c25e` | graphics: character name `Explorer` / `Scholar` of a specialist (S 00693640) |
| `bavarians` | `b0d378a3` | the tribe id substituted when a slot has none: free-game setup and the command-line map start (S 005e8410, S 00401350). The other two tribe ids do not occur in the image; the setup's tribe box finds a tribe by comparing the record `name` (`tp_setName`) with the string table S 0087f328: index 0 `"Bavarian"`, 1 `"Scots"`, 2 `"Egyptian"` (`Tribe_ComboIndexToTribeId` S 005e6be0, initialiser S 007c7b00). A tribe whose name is none of the three cannot be chosen there |

Records outside this document that the code names by id as well [known: the same search]: about 30 sound
records of `sounds.lua` (UI clicks, music tracks, door, tree-fall, catapult and building-collapse sounds;
[audio.md](audio.md)). The map editor's tools name further goods, deposits, doodads and patterns (coal, gold,
iron ore, salt, gemstones, `stone_01`..`06`, `tree_02`..`08`, `doodad_stones_0`..`3`, the meadow, rock, snow and
sea-ground patterns); they are not part of the simulation.

Records reached by **name** from data files [known: data, for the file contents]: `ui/layout/goodinfosets.xml`
lists goods as `<Good name="Wood"/>`; `ui/layout/iconconfig.xml` has elements named after goods
(`<Weapons …/>`); `settings/items.xml` names goods in `good = "…"` attributes (`"Boat"`). The code has two
name lookups for goods, `TribeProperty::FindGoodIdByName` S 005560d0 (within the tribe's goods list; caller
`nMenu::GoodSet::LoadFromXml` S 00629ce0) and `PropertiesDb::FindGoodIdByName` S 00545f50 (callers
`S2CG::CLandscape::ctor`, `AnimationSet::LoadRandomAnimationsXml`) [known]; which file each of them serves is
[inferred] from the names. Renaming a record (`gp_setName`) breaks these links.

---

## 6. Data-driven parameters

Everything in this document is data. The files and the calls that feed it [known: counted from the scripts]:

| File | Records and calls | Example |
|---|---|---|
| `defineTribes.lua` | 3 `tp_create` | `bavarians = properties.tp_create("b0d378a3")` |
| `Goods.lua` | 100 `gp_create`; 5 type constants (`Invalid` -1, `Ware` 0, `Settler` 1, `WareGroup` 2, `EitherGroup` 3); `gp_setName`, `gp_addCost`, `gp_setType`, `gp_setTransportPriority`, `gp_setAiPriority`, `gp_setArrangementGoodId`, `gp_setMiningGood`, `gp_enableDeposits`, `gp_enableFields`, `gp_setPlantable`, `gp_setAiRandomValue`, `gp_setAINoNeedForCosts` | `properties.gp_addCost(bread, flour, 1)` |
| `Jobs.lua` | 76 `gp_create`; constants `settlerType_*` 0..5, `soldierType_Sword` 0 / `_Bow` 1, `projectile_arrow` 0 / `_bolt` 2 / `_slingStone` 3; `gp_setName`, `gp_setType`, `gp_addCost`, `gp_setSettlerType`, `gp_setGfxGoodId`, the soldier setters | `properties.gp_setHealth(good_soldierHalberd0, 100)` |
| `buildings.lua` | 104 `bp_create`; working-mode constants 0..11, `Depot_None` -1 / `_Local` 0 / `_Resources` 1 / `_Stuff` 2, `DoorOffsetWest` 3 / `NorthWest` 4 / `NorthEast` 5; all `bp_*` setters | `properties.bp_setGoods(farmBav, corn, 2)` |
| `config.lua` | the size constants `SizeSmall` 7, `SizeMedium` 6, `SizeLarge` 4, `SizeMine` 8, `SizeShip` 16, `SizeMilitary` 64, `SizeInvalid` 0; seven time constants `ExtremlyShortTime` 50 .. `ExtremlyLongTime` 400; 17 `cfg_*` calls (the game configuration) | `properties.cfg_setFlagPackageLimit(2)` |
| `military.lua` | 15 `mi_setSoldierId`, 4 scalars | `properties.mi_setSoldierId(scots, soldierType_Bow, 1, good_bowSoldierStone1)` |
| `ship.lua` | 3 `sh_setSpeed`, 3 `sh_setExpeditionBuilding`, 5 scalars | `properties.sh_setStockLimit(12)` |
| `sacrifices.lua`, `sacrifices_goodExchange.lua`, `sacrifices_campaign.lua` | 77 `sf_create` (36 + 31 + 10); effect constants 0..14 and 1000, 1001, 1003..1008, `Target_Owner` 0 / `Target_Enemies` 1, `SacrificeCategory_*` 0..4 (all in `sacrifices.lua`, before it loads the other two); the helper `defaultSacrificeGEProperties` | `properties.sf_addCost(sacrifice_carrierSpeed, whisky, 3)` |
| `animals.lua` | 12 `an_create`; the helper `addBaseStack` | `properties.an_addStackGood(animal_sheep, scots, sheep)` |
| `tribes.lua` | 78 `tp_addGood`, 16 `tp_addJob`, 109 `tp_addBuilding`, 69 `tp_addSacrifice` (a 70th is commented out), 22 `tp_addAllowedSacrifice`, 67 `tp_addStartResources`, 78 `tp_addBonusResources` | `properties.tp_addBuilding(scots, sheepBreeding)` |

Graphics that go with the records are found by name [known: data, for the names occurring in the files;
inferred for the lookup]: `bp_setGfxName` → `settings/buildings.xml` (`"WoodcutterHut"`), `gp_setName` / the
tribe name → `character/settler_config.xml` (`"Woodcutter"`, `"Bavarian"`) and the files of §5,
`sf_setGfxName` → `settings/effectMovies.xml` (`"carrierSpeedGfx"`); [TODO] not established: the file that
`sf_setBuffGfxName` refers to ([../data-loading.md](../data-loading.md) §2,
[../asset-formats.md](../asset-formats.md)).

Text encoding [known: data]: the scripts are ASCII except `patterns.lua`, which holds ISO-8859-1 bytes and CRLF
line ends; a loader must not require UTF-8.

---

## 7. Save and load

Saves and maps store **ids** of this content, not the records: tribe ids of the players, building type ids,
good ids in every stock, request and package, settler good ids, sacrifice ids in the running, researched and
regenerating sets, animal ids ([save-format.md](save-format.md), [../map-format.md](../map-format.md) §2.4,
[properties-data.md](properties-data.md) §7). The ids of §2 are therefore part of the file formats: a save refers
to `733f1e03`, not to "Bavarian stone".

Two lists are **copied** into the map information of every map and save, per tribe [known:
`NLogic::MapInfo::Load` S 0052bd40]: the initial goods (`{good id, amount}` pairs, default
`tp_addStartResources`) and the allowed sacrifices (ids, default `tp_addAllowedSacrifice`). The stored copies
are what a match uses (`MapInfo::GetInitialGoods` S 005296e0 in `Depot::AddInitialStock` S 0055b020), so a
change of these two script lists does not reach an existing map. The loader rebuilds the goods copy from the
tribe records only for a stream version below 14 (`ResetInitialGoodsFromTribes` S 0052b550) and the sacrifice
copy only below 13 (`ResetSacrificesFromTribes` S 0052bb40); `MapInfo::Reset` S 0052b8d0 calls the
first of them as well. The bonus list `tp_addBonusResources` is not copied: it is read from the tribe record.

On load the content is already in memory (it is created at program start, before any game) and the loaders
resolve ids against it. A lookup of an id without a record (`PropertiesDb::GetGoodProperty` S 00547560 and its
siblings) runs into the invalid-parameter routine S 006f2702, which ends the program (exit code 0xC000000D, no
handler installed: `military.md` §3.2) [known]
([properties-data.md](properties-data.md) §2.2).

---

## 8. Determinism notes

The content is simulation state in the sense that every peer must hold identical tables: recipes, times,
costs and soldier values enter the lockstep simulation directly. It is constant during a match and uses no
random numbers. Three properties of the data reach the simulation's determinism:

- **List order.** The `tp_addGood` order decides which food a mine eats first (§3.4) and the order of group
  members everywhere: the group iterator walks the tribe's goods list and yields the goods that are in the
  group's cost list (`PropertyGroupIter::Init` S 007767c0, `ai::properties::PropertyGroupIter::Next` S 00776690) [known]. The
  `tp_addBuilding` order is the order of the producer and consumer lists (`Economy_CollectProducerBuildings`
  S 00534d00, `…ConsumerBuildings` S 00534f40) and of the AI's first-match building lookups (§5) [known]. A
  converter must keep script call order.
- **Id order.** A stock iterates in ascending good id ([village-buildings.md](village-buildings.md) §2.5), and
  tables iterate in ascending *signed* id ([properties-data.md](properties-data.md) §2.2), so the numeric ids
  influence which ware leaves a building first.
- **Number types** [known: the bindings]. Read with `Lua_ToFloat` S 005c9b10 and kept as 32-bit floats:
  `bp_setProductionTime`, `bp_setArrangementValue`, `sh_setSpeed`, `sh_setConstructTime`, `cfg_setSettlerSpeed`,
  `cfg_setPickupTime`, `cfg_setDropTime`, `cfg_setBulldozeTime`, `cfg_setConstructTime`,
  `cfg_setSettlerDyingTime` and the three `cfg_set*TimeFactor`. Read with `Lua_ToInt` S 005c9b30 (the Lua number
  truncated toward zero): `bp_setRestTime`, `bp_setStockLimit`, `bp_setConstructionTime`, `gp_setHealth`,
  `sh_setStockLimit`, `sh_setWaitTime`, `sh_setSinkingTime`, `cfg_setSpawnPointUpdateTime`,
  `cfg_setFishingDistance`, `cfg_setFlagPackageLimit`, `cfg_setMaxWaterStreetWaterDepth`, the four `mi_set*`
  scalars and every id and amount.

Peers with different property scripts (a modified install) compute different simulations, and the game
refuses to let them play together [known]: a joining peer sends a build checksum in its `UserInformation`
event (`0x30001`), and the host kicks it with `!CHECKSUM MISMATCH` when the value differs from its own
(`NComm_Manager::HandleEvent` S 0040e560). `GameData_ComputeBuildChecksum` S 005ab800 is the XOR, over every
`*.lua` below `[data]\scripts` and every `*.xml` below `[data]\settings` (both recursive), of the CRC field of
the file's 20-byte encryption header (the CRC-32 of the plain text, [../asset-formats.md](../asset-formats.md));
a file without that header counts as `file size XOR first 4 bytes`, a file shorter than 4 bytes not at all. The
property scripts are all inside this set ([../data-loading.md](../data-loading.md) §3,
[network-session.md](network-session.md)). A remake that wants to play only with peers holding the same
content needs an equivalent comparison over its converted cache.

---

## 9. Notes for a Godot reimplementation

- **Do not transcribe these tables into the remake.** Ship a loader that runs the player's own property scripts and
  fills the same record types. The scripts are plain Lua 5.0 source ([lua-runtime.md](lua-runtime.md)) that only
  assign globals and call `properties.*`; apart from a few helper functions (`loadPropertiesFile`,
  `defaultSacrificeGEProperties`, `addBaseStack`, and the eleven pattern helpers of `patterns.lua`, of which
  `setPattern` uses `if`, `type()` and a table argument) they are flat; `data.lua` and `sacrifices.lua` also call
  `Default.CallScript` through `loadPropertiesFile` [known: data]. Run them with a Lua interpreter against a recording
  `properties` table, in the order of `data.lua`, resolving file names case-insensitively.
- **Converter output.** One resource (or one JSON document) per table, each record keyed by its id as an
  unsigned 32-bit number plus the Lua global name as a debug label. Keep: every list in call order; cost lists
  merged by good with first-appearance order ([properties-data.md](properties-data.md) §3.2); per-tribe maps
  (`transportPriority`, `aiPriority`, positions, ship speed) keyed by tribe id; the last value when a setter is
  called twice. Emit the engine-side side effects too (§4): the cost list of `sacrificeGood` built by `sf_addCost`
  (one unit per call for the good and for its differing arrangement good, merged), the soldier tables with the
  health copied at `mi_setSoldierId` time.
- **Engine mapping.** Records are immutable data: Godot `Resource` objects or plain dictionaries loaded into
  an autoload. Nothing here needs a node. The build menu, goods panels and statistics should be generated from
  the tribe lists, as the original does.
- **Must be reproduced exactly**: the working-mode table of §3.1 (the same row means different behaviour per
  mode); recipes taken from product slot 0 only; group semantics (when the **first** entry of the
  recipe is an either group, only that entry is consumed: `n` single picks, each the first member in tribe list
  order that is in stock, `StartProductionCycle` S 005657c0); the literal ids of §5 (corn doubling, the carrier, wood,
  stone, fish, water, ship) and the three tribe names the setup matches; the quirks of §3.9.
- **Safe to simplify**: the unreachable records can be loaded and ignored. `gp_setShortName` and `gp_setValue`
  are never called by the shipped scripts, and no reader of `gp_setValue` and `gp_setPlantable` was found
  [inferred] ([properties-data.md](properties-data.md) §2.4). `gp_enableFields` is **not** dead: the AI reads
  the flag (good record `+0x51`, through the shared one-instruction getter S 0046b620) next to
  `gp_enableDeposits` (`+0x50`) in `GameQueryHelper::ScoreSite` S 00534830,
  `NAI::ProductionControl::IsGoodControllable` S 0058bad0, `NAI::DestructionSystem::CanDemolishBuilding`
  S 0058dae0, `NAI::NeedsArrangement::InstantiateGroupNeed` S 005943c0, `NAI::Need::PostLoad` S 00596f70 and
  the `NAI::Need` constructor S 00597010 [known]; a remake with the original AI must keep it.
- **Validation.** After conversion, check the totals of §2.1 and a few anchors: 26 `tp_addGood` entries per tribe
  (among them 4 / 4 / 5 groups); 37 / 35 / 37 building types; `bp_setGoods` amounts of 2 for exactly `brauhaus`,
  `bakerypretzel`, `fisher2`, `farmBav`, `stoneMineClay`; one building with a second product (`goatBreeder`: goat 1,
  `bp_setSecondGoods` milk 1); 15 soldier ranks (6 / 4 / 5); 16 `tp_addJob` entries (7 / 4 / 5).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | What uses the ware group `weapons` (`0897d1e3`)? Neither the id nor the string `Weapons` occurs in the image [known]; `ui/layout/iconconfig.xml` has `<Weapons …/>` elements and the language files a `Weapons` entry [known: data] | static: the reader of `iconconfig.xml` and the goods panel code in [ingame-ui.md](ingame-ui.md) (which good names it asks icons for) |
| 2 | What looks up the three `construction*` dummy building types, and how does their weight 0.8 enter the goods distribution? | static: `NPlayer::GoodArrangement` and `Economy_CollectConsumerBuildings` S 00534f40 with a `SizeInvalid` type; the callers that pass a `constructionResources*` good |
| 3 | What does a guard house, tower or fortress keep under its stock limit 2 / 4 / 6? | static: readers of `stockLimit` for types without a product slot ([military.md](military.md), promotion in military buildings) |
| 4 | How do Egyptians obtain wood on a long game: is there any regrowth of trees without a forester? | static: every creator of tree deposits in [map-resources.md](map-resources.md) (spawn points, script functions); or an observation |
| 5 | Which file does `sf_setBuffGfxName` refer to (§6)? | data: search the buff names of `sacrifices.lua` in `settings/*.xml` and `ui/layout/*.xml`; static: the reader of `SacrificeProperty.buffGfxName` |
| 6 | Which reader uses the `good = "…"` attributes of `settings/items.xml` (the only place that names `boat`)? | static: the loader of `items.xml` (`ItemMgr`, [../data-loading.md](../data-loading.md) §2) and the callers of `PropertiesDb::FindGoodIdByName` S 00545f50 |
| 7 | Can a non-Egyptian player supply the Olympic flame's `good_buildingHelper` worker at all (the sacrifice itself does not need it, §3.8)? | static: the worker request of a building whose worker good is not in the owner's job list ([settlers-jobs.md](settlers-jobs.md)) |

---

## 11. Function reference

The content is data; these are the functions through which it is read, to start from.

| Address | Name | Role |
|---|---|---|
| S 0054f8d0 | `PropertiesDb::RunPropertyScript` | runs `[data]\scripts\properties\<name>.lua` on a new Lua thread; called once, with `"data"`, by `CApplicationEx::Initialize` S 004075d0 |
| S 00549a50 | `Properties_CreateGoodProperty` | creates a good record (`gp_create`, 0xc0 bytes) and stores it under its id; a second create for the same id replaces the map entry |
| S 00552aa0 | `GoodAmountList_AddAmount` | merge rule of every cost list: add to the entry of the same good, else append |
| S 0054f520 | `LuaProps_sf_addCost` | sacrifice cost; also adds the good (and its differing arrangement good) to the sacrifice good's cost list, which is that group's member list (§4) |
| S 00554290 | `MilitaryConfig::SetSoldierId` | soldier rank tables: good id and copied health per kind, level and tribe; highest level per kind and tribe |
| S 00552fa0 / 00553080 | `BuildingProperty::ProducesGood` / `ConsumesGood` | producer test (either product slot holds the good) and consumer test (the cost list of either product slot's good contains it, groups expanded) |
| S 00534d00 / 00534f40 | `Economy_CollectProducerBuildings` / `…ConsumerBuildings` | which buildings of a tribe make or take a good, in `tp_addBuilding` order; for an either group the producers of every member; consumers only with `constructionTime > 0` or the headquarters flags |
| S 007767c0 / 00776690 | `PropertyGroupIter::Init` / `ai::properties::PropertyGroupIter::Next` | members of a group in tribe list order |
| S 005657c0 | `NVillage::Production::StartProductionCycle` | consumes the recipe of product slot 0; group picks |
| S 00565bd0 | `NVillage::Production::CanStartProduction` | input test; mines; the 20-animal limit of mode 10 |
| S 00565990 | `NVillage::Production::DeliverProducts` | output of both product slots |
| S 00565a70 | `NVillage::Production::RequestAllInputs` | input requests for the recipe of product slot 0; skipped with `ignoreGoodCosts` (`+0xf0`); `casern` types delegate to the training component |
| S 0065d660 | `NSettlers::Worker::ChooseNextWork` | working mode → action |
| S 0077b6d0 | `NMovie::Rest::Start` | rest time (`bp_setRestTime`, scaled by a sacrifice modifier of the owner) |
| S 00777f80 | `NMovie::PickupProduct::Start` | which good a worker carries out; the hunter's yield |
| S 0077a8e0 | `NMovie::PutDownPackage::Update` | amount delivered by the gathering modes 1, 2, 3 and 7: the product-slot amount with modifiers, the units beyond the first as extra packages at the flag |
| S 00564360 | `SettlerSpawn::ConsumeSettlerGood` | tool → worker: if the settler good is not in the store stock, its cost list is exchanged for it; then one unit is removed |
| S 005668e0 / 00566920 / 00566990 | `VillageSoldierTraining_CanStart` / `StartNext` / `Finish` | barracks cycle |
| S 00561240 / 00561410 | `VillageSacrifice::CheckCanOrder` / `Order` | temple: order |
| S 00560f20 / 005615e0 | `VillageSacrifice::CheckCanStart` / `ai::village::VillageSacrifice::Start` | temple: start |
| S 00561940 | `ai::village::VillageSacrifice::Update` | temple per building update: state 0 → 2, automatic start of the Olympic flame |
| S 00561870 | `VillageSacrifice::OnExpired` | temple after a sacrifice ends |
| S 0065fae0 / 0065ff00 / 0065fde0 | `SacrificeResearch::Start` / `Update` / `ai::logic::SacrificeResearch::Complete` | research |
| S 00782700 / 00561150 | `nGame::System::HandleCommand_20027` / `VillageSacrifice::StartResearch` | research command: no stock and no temple state is read |
| S 006620a0 / 006621f0 | `SacrificePlayerData::RemoveSacrifice` / `UpdateSacrifices` | end of a sacrifice, regeneration entry |
| S 00662720 | `SacrificeRegenerations_RemoveExpired` | regeneration delay |
| S 00660050 | `ai::logic::Sacrifice::IsExpired` | duration test |
| S 00661c50 | `SacrificePlayerTableRef::GetEntryWithModifiers` | product amount, corn doubling |
| S 005ab800 | `GameData_ComputeBuildChecksum` | checksum over the scripts and settings that peers compare (§8) |
| S 0052bd40 / 0052b550 | `NLogic::MapInfo::Load` / `ResetInitialGoodsFromTribes` | the map's copy of the start stock (§7) |
| S 005e6be0 | `Tribe_ComboIndexToTribeId` | tribe by name in the setup (§5) |
| S 005678b0 | `NVillage::Catapult::Fire` | ammunition = first cost entry of the product-slot good: one unit removed and re-requested per shot |
| S 0055b020 | `NVillage::Depot::AddInitialStock` | fills a headquarters: the map's initial goods of the tribe, plus the tribe's bonus list for a player passing `ai::player::Player::IsStateDefault` S 005be350 |
| S 0058dae0 | `NAI::DestructionSystem::CanDemolishBuilding` | example of a literal good id (`wood`) in the AI |
