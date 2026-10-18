# Quests, sacrifices, statistics, chests and messages

Binary: `sadk_noav.exe`. Addresses are written `S 00xxxxxx`. Tags: `[known]` = read directly in the code at the
address given or in the named data file and key, `[inferred]` = one step of reasoning from what is visible,
`[TODO]` = open. Nothing in this document has been observed in the running game.

This document is the home of the **sacrifice life cycle** (order, goods, start, effects, expiry, cool-down,
research), of the **quest slots**, and of the **catalogue of player messages**. For statistics, chests and spawn
points it gives the complete rule set in one place and points to the documents that hold the supporting detail.

Related documents (not repeated here):

- [players-victory.md](players-victory.md): `NLogic::Statistics` / `PlayerStatistics` layouts (§2.5), sampling
  formulas (§3.11), `NPlayer::Messages` / `Message` layouts (§2.7), the low-stock warnings (§3.9), the lock maps
  (§3.10), victory mode 5 and the victory quest (§3.6), chest placement of a network match (§3.4).
- [properties-data.md](properties-data.md): `SacrificeProperty` (§2.7), the sacrifice modifier table and the
  readers of every modifier (§3.9), `SpRecord` (§2.6), `GameConfig` (§2.10).
- [military.md](military.md) §3.5, §3.6, §3.9: what peace time and the soldier modifiers do to attacks and fights.
- [game-commands.md](game-commands.md) §3.4: the five sacrifice commands `0x20024`..`0x20028`, their payloads and
  their check codes.
- [logic-core.md](logic-core.md): tick order (§4.2), callback slots (§3.7), the chest and spawn point update (§3.5),
  the checksum (§3.6).
- [lua-runtime.md](lua-runtime.md): the `logic.q_*` bindings (§3.6), the quest machine of the map scripts (§3.9),
  the `sd_` store.
- [ai-player.md](ai-player.md) §3.15: how computer players choose, research, order and start sacrifices.
- [save-format.md](save-format.md): stream primitives, section headers, section order.
- [ingame-ui.md](ingame-ui.md): quest lines and quest log (§3.8.4), statistics panel (§3.8.1), sacrifice bar and
  target chooser (§3.8.9), message HUD, end-of-game dialogs (§3.9).
- [map-resources.md](map-resources.md): animals, ground resources, grid bit `0x400`.
- [map-format.md](../map-format.md): `MapInfo` chest positions (+0x14) and sacrifice lists (+0x204).

---

## 1. Purpose and scope

Seven small systems of the simulation core `NLogic::System` (global `g_pGameSystem`):

| System | Class | Member of `NLogic::System` | What it is |
|---|---|---|---|
| Quests | `NLogic::Quests` (0xdc8) | +0x5c | 40 passive quest slots written by the map script and by the victory code |
| Sacrifices | `NSacrifice::System` (0xc60) | +0x60 | running sacrifices, cool-downs, research and the modifier tables, per player |
| Sacrifice building part | `ai::village::VillageSacrifice` (0x38) | `Building +0x128` | the order / start state machine of one sacrifice building |
| Statistics | `NLogic::Statistics` (0x38) | +0x28 | per-player sampled series, per-good history, building productivity |
| Chests | `ai::logic::LogicChestSystem` (0x28) | +0x64 | map objects opened by holding their cell in one's territory |
| Spawn points | `ai::logic::LogicSpawnSystem` (0x18) | +0x68 | map objects that periodically create animals or ground resources |
| Messages | `NPlayer::Messages` (0x28) | `Player +0x14` | per-player list of notifications raised by simulation events |

Tutorial pages and hints are not a simulation system: they are a HUD panel filled by a Lua helper (§3.7).

Not in scope: the numeric effect of each sacrifice modifier on its reader (properties-data.md §3.9), the
commands that reach the sacrifice building (game-commands.md), the choice logic of computer players
(ai-player.md), the widgets that draw any of this (ingame-ui.md).

---

## 2. Data model

### 2.1 Quests

`NLogic::Quests` (0xdc8 bytes) `[known]` S 00536200: `+0x00` vtable (S 007e7b24), `+0x04` bool `initialized`
(0 in the constructor, 1 after `Reset`), `+0x08` `Quest quests[40]`, stride 0x58.

`NLogic::Quest` (0x58 bytes, vtable S 007e7b10) `[known]` S 00536160, S 00536330, S 00536000:

| Offset | Type | Field | Meaning | Constructor value |
|---|---|---|---|---|
| +0x04 | i32 | `kind` | 0 = main quest, 1 = sub quest, **2 = slot unused** | 2 |
| +0x08 | std::string | `id` | name of the quest; a text key (`!VictoryCond_1`) or the script's quest name | empty |
| +0x24 | bool | `finished` | | false |
| +0x25 | bool | `failed` | | false |
| +0x28 | i32, i32 | `markerPos` | map cell of the quest marker; (-1, -1) = none | (-1, -1) |
| +0x30 | std::string | `text` | progress text shown behind the title | empty |
| +0x4c | bool | `visible` | shown in the quest lines and the quest log | false |
| +0x50 | u32 | `textChangedTick` | logic tick of the last change of `text` | 0 |
| +0x54 | u32 | `startTick` | logic tick at which the slot was filled | 0 |

The engine never interprets `id`, `text` or `markerPos`; they are data for the UI and the script `[inferred]`
(the only readers outside the Lua bindings and `Store` / `Load` are `nMenu::QuestInfoPanel`, `QuestInfo` and
`QuestLog`). The only fields with a simulation meaning are `kind`, `finished` and `failed` (§3.1.3).
`Quests::ctor` S 00536200 constructs the 40 slots with `Quest::ctor` S 00536160; `Quest::Store` S 00536000 writes
`kind`, `id`, `finished`, `failed`, `markerPos`, `text`, `visible`, `startTick`, `textChangedTick` in that order
`[known]`.

### 2.2 Sacrifice system

`NSacrifice::System` (0xc60 bytes, vtable S 007f8690: slot 0 deleting destructor, slot 1 `Update`) `[known]`
S 0065f9b0:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | bool | `initialized` | set by `NSacrifice::System::Init` S 0065f4b0 and `Load`, cleared by `NSacrifice::System::Reset` S 0065f4d0 |
| +0x05 | bool | `paused` | set while a cinematic plays; `Update` does nothing while set |
| +0x08 | u32 | `pauseStartTick` | logic tick at which the pause began |
| +0x0c | `SacrificeModifierQuery` | | accessor object bound to the table at +0x18; the readers of properties-data.md §3.9 go through it |
| +0x18 | `SacrificePlayerTable` (0xc48) | `table` | `+0x00` bool `initialized`, `+0x08` `SacrificePlayerData players[8]` |

So player *p*'s record starts at `System + 0x20 + p * 0x188` `[known]` S 0065f5a0.

`ai::logic::SacrificePlayerData` (0x188 bytes, no vtable) `[known]` S 00662dd0, S 00662ab0:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | `std::vector<Sacrifice*>` | `sacrifices` | the sacrifices this player **owns** that are running, in start order (begin pointer at +0x04, end at +0x08) |
| +0x10 | bool | `hasPlayer` | set by `Init` |
| +0x14 | i32 | `playerHandle` | the player index again; argument of the territory recomputation (§3.2.6) |
| +0x18 | `SacrificeModifiers` (0xf8) | `modifiers` | the table that other systems read: `flags[15]`, `ownBonus[15]`, `hostileDivisor[15]`, `effective[15]`, player index (properties-data.md §3.9) |
| +0x110 | `std::map<i32, u32>` | `regenerations` | sacrifice definition id → logic tick at which its cool-down began |
| +0x120 | `SacrificeResearch` (0x40) | `research` | below |
| +0x160 | `SacrificeDependencies` (0x14) | `dependencies` | `std::map<i32 defId, bool>` at +0x00, bool `hasPlayer` +0x0c, bool +0x0d, i32 player index +0x10 |
| +0x174 | i32 | `freeTickets` | counter, 0 at construction |
| +0x178 | i32 | `playerIndex` | |
| +0x17c | bool | `initialized` | |
| +0x180 | ptr | `ownerTable` | back pointer to the `SacrificePlayerTable` |

A record lists only the sacrifices its player owns. The sacrifices aimed at a player are collected from the
other records: `SacrificePlayerData::CollectIncomingSacrifices` S 00662c70 skips the player's own record, walks
the other records in index order and, in each record's list order, takes every sacrifice whose `targetPlayer` is
the player `[known]`. A sacrifice a player aims at itself (`def.target == 0` sets `targetPlayer` to the owner,
§3.2.4) is therefore never among them. Its only caller is the sacrifice bar's antibuff row
(`nMenu::SacrificePanel::AssignIncomingSacrifices` S 00625200, for the player the game screen holds at
+0xfff4; ingame-ui.md §3.8.9) `[known]`.

`ai::logic::Sacrifice` (0x58 bytes; base `NLogic::Unique`) `[known]` S 00661850, S 00661050 — one running
sacrifice:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x08 | u64 | unique id | from the global id counter (`NLogic::Unique::AssignNew`) |
| +0x10 | `NLogic::ReferenceBuilding` (0x20) | `building` | the sacrifice building it was started at |
| +0x30 | `Player*` | `owner` | the first i32 of the player entry is its index |
| +0x34 | i32 | `targetPlayer` | index of the player whose modifier table it changes (§3.2.4) |
| +0x38 | u32 | `startTick` | logic tick of the start; shifted forward after a cinematic (§3.2.11) |
| +0x40 | `SacrificeProperty*` | `def` | the definition |
| +0x44 | `std::vector<bool>` | `fired` | one bit per entry of the definition's effect list, all 0 at the start |

`ai::logic::SacrificeResearch` (0x40 bytes) `[known]` S 0065ff30, S 0065fae0, S 0065fc10 — one per player, so a
player researches at most one sacrifice at a time:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | `std::map<i32, u32>` | `researched` | definition id → logic tick at which its research completed (`Store` writes the keys only) |
| +0x0c | `SacrificeProperty*` | `def` | the definition being researched |
| +0x10 | u32 | `startTick` | |
| +0x14 | bool | `running` | |
| +0x18 | `NLogic::ReferenceBuilding` (0x20) | `building` | the building the research runs in |
| +0x38 | bool | `hasPlayer` | false in the constructor and after `Reset` S 0065fa80, true after `SetPlayerIndex` S 0065fa40 |
| +0x3c | i32 | `playerIndex` | not written by the constructor; the index after `SetPlayerIndex`, -1 after `Reset`; the building's research reference stores this value as its id |

`ai::village::VillageSacrifice` (0x38 bytes, allocated for every building, used only by buildings of working
mode 9) `[known]` S 00560bd0:

| Offset | Type | Field | Meaning | Constructor value |
|---|---|---|---|---|
| +0x00 | `Building*` | `building` | owner | |
| +0x04 | i32 | `state` | 0 = spent (waiting for the output stock to empty), 1 = sacrifice running, 2 = ready, 3 = ordered (collecting goods or waiting for the start) | 2 |
| +0x08 | bool | `freeTicket` | the current order was placed with a free ticket | false |
| +0x0c | i32 | `targetPlayer` | start parameter, valid only between the start command and the start | -1 |
| +0x10 | i32 | `sacrificeDefId` | ordered or running definition; -1 = none | -1 |
| +0x18 | `NLogic::ReferenceSacrifice` | `active` | unique id (+0x28 / +0x2c) and cached pointer (+0x30) of the running `Sacrifice` | id -1 |

The building's own goods for a sacrifice live in its depot (`Building +0x3c`, village-buildings.md §2.5): the
**input stock** `Depot +0x0c` receives the cost goods, the **output stock** `Depot +0x28` receives goods given by
an effect, the request list `Depot +0x44` (`NTransport::NeedGoods`) holds the open demand `[known]` S 00561410,
S 005615e0, S 0065ffc0. `Building +0x12c` is a 12-byte reference to the owner's `SacrificeResearch` while a
research runs in the building (id at +0x04, -1 = none; cached pointer at +0x08) `[known]` S 0055c3c0, S 007753a0.

Sacrifice definitions (`SacrificeProperty`, 0xa4 bytes) are specified in properties-data.md §2.7. The fields this
document uses: `+0x00` id, `+0x04` name, `+0x58` `duration` (ticks), `+0x5c` `costs` (list of {good, amount}),
`+0x6c` `effects` (list of {type, arg1, arg2, threshold}, 16 bytes each), `+0x7c` `target` (0 owner, 1 enemies),
`+0x80` `abortable`, `+0x88` building dependences (always empty in this build), `+0x98` `researchDuration`
(ticks; 0 = none), `+0x9c` `regenerationDelay` (ticks).

### 2.3 Statistics

`NLogic::Statistics` and `NLogic::PlayerStatistics` are laid out in players-victory.md §2.5. In short `[known]`
S 00538380, S 0053b330: per player eight integer series of at most 960 samples (index 0 territory percent, 1
buildings, 2 population, 3 stored goods, 4 military strength, 5 coin counter, 6 average productivity percent, 7
kills), a map good-or-job id → cumulative history of at most 960 elements, the counters `coinCount` (+0x98),
`killCount` (+0x9c) and `regionSize` (+0xa4), and an `active` flag (+0x04).

The **productivity map** `Statistics +0x0c` is a `std::map<Unique building id, ProductivityItem>`; the item has
a float `productivity` (tree node +0x28) and an i32 idle counter (node +0x2c) `[known]` S 00537ba0, S 005373b0.

### 2.4 Chests

`ai::logic::LogicChestSystem` (0x28) and `ai::logic::LogicChest` (0x30) are laid out in logic-core.md §2.7.
Fields used below `[known]` S 00539240, S 00539360: `+0x08` unique id, `+0x10 / +0x14` cell, `+0x18`
`ownerPlayer` (-1 = none), `+0x1c` `contentKind` (0 = chest of a network match, 1 = goods chest), `+0x20 / +0x24`
`contentGoodId` / `contentGoodCount` (-1 / 0 until set), `+0x28` `contentValue` (kind 0: the chest id sent to
the referee), `+0x2c` `openProgressTicks`. System: `+0x00` observer list, `+0x0c` callback manager, `+0x10` bool
`initialized`, `+0x14` `std::vector<LogicChest*>`, `+0x24` bool `enabled` (1 at construction).

### 2.5 Spawn points

`ai::logic::LogicSpawnSystem` (0x18) `[known]` S 0052cf50, S 0052cb70: `+0x00` callback manager, `+0x04` bool
`initialized`, `+0x08` `std::vector<NLogic::Spawn*>`.

`NLogic::Spawn` (0x28 bytes; subclasses `SpawnAnimal` vtable S 007e7a60 and `SpawnResource` vtable S 007e7a70,
which add no fields) `[known]` S 00538f10, S 0052c990:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | vtable | | slot 0 `Spawn()` (the trigger), slot 1 `Store`, slot 2 `Load` |
| +0x08 | `NLogic::Unique` | | 64-bit id at +0x10 / +0x14; (-1, -1) until `PlaceAt` assigns one |
| +0x18 | `SpRecord*` | `record` | the spawn point type (properties-data.md §2.6): id +0x00, `uniqueIds` vector +0x58, `range` +0x68 (default 3), `type` +0x6c (0 resource, 1 animal), `rate` +0x70 (default 1) |
| +0x1c, +0x20 | i32 | `posX`, `posY` | map cell, (-1, -1) at construction |

### 2.6 Messages

`NPlayer::Messages` (0x28) and `NPlayer::Message` (0x80) are laid out in players-victory.md §2.7. A message has
`[known]` S 005c0740: a unique id, `timeRemaining` (float, 600.0 when created), a cell (`(-1, -1)` = no
position), `text` (a localisation key beginning with `!`), `text2` (letters only), `arg` (a name inserted into
the text: a player name, a building type name, a good name, a sacrifice name, a quest name), `isRead` and
`msgType` 1..8. The message types select the icon, the filter entry and the minimap symbol
(ingame-ui.md §2.10).

---

## 3. Rules and algorithms

### 3.1 Quests

#### 3.1.1 Slot operations

All of them act on a slot index 0..39 and are reached only through the Lua library `logic` and the victory code
`[known]` (callers of S 00536430, S 00536310, S 00536390, S 005363f0, S 00535fd0):

| Operation | Function | Effect |
|---|---|---|
| fill | `Quests::SetQuest(i, name, kind, pos, visible)` S 00536430 → `Quest::Init` S 00536330 | `kind`, `id = name`, `finished = failed = false`, `markerPos = pos`, `visible`, `startTick = textChangedTick = tickCounter`. `text` is **not** cleared |
| free | `Quests::ClearQuestSlot(i)` S 00536310 | `kind = 2`, `id` cleared; every other field keeps its value |
| set text | `Quest::SetText(text)` S 00536390 | only if the new text differs: store it and `textChangedTick = tickCounter` |
| reset all | `Quests::Reset` S 005363f0 | every slot whose `kind != 2`: `kind = 2`, `id` cleared; then `initialized = true` |
| hide all | S 00535fd0 | every slot whose `kind != 2`: `visible = false`. Only caller: the scenario victory (§3.1.3) |

`SetQuest` and `ClearQuestSlot` do not test the index or the slot's `kind`; the tests are in the Lua bindings.

`Quests::Reset` runs in `NLogic::System::InitSubsystems` (world creation) and has no other caller.
`NLogic::System::Reset` S 00526f80 only clears `Quests.initialized`; the slots keep their content until the
next `InitSubsystems` `[known]`.

#### 3.1.2 Lua interface (`logic.q_*`)

The bindings are specified in lua-runtime.md §3.6. Their engine-side rules `[known]` S 005b1670, S 005b1850,
S 005b1980, S 005b1ab0, S 005af580..005af790, S 005b1be0:

- Every binding checks `(unsigned) index < 40`. `q_add` additionally requires the slot to be **unused**
  (`kind == 2`); all others except `q_isValid` require it to be in use. A binding whose test fails does nothing
  and returns no value (the three flag readers and `q_isValid` then return zero results, not `false`).
- `q_add(i, name, kind, x, y, visible)`: fill the slot. If `tickCounter != -1` (the match has started ticking)
  and `visible`: message type 7 `!New main quest` (kind 0) or `!New sub quest` (any other kind) to the **local**
  player, arg = `name`, at (x, y); then the quest log is refreshed and selects the quest. Without `visible`, or
  before the first tick, the slot is filled silently.
- `q_finish(i, notify)`: `finished = true`; with `notify`, message type 7 `!main quest finished` (kind 0) or
  `!sub quest finished`, arg = the quest's `id`, at its marker.
- `q_failed(i, notify)`: `failed = true`; with `notify`, `!main quest failed` / `!sub quest failed`.
- `q_reset(i, notify)`: `finished = failed = false`; with `notify`, `!New main quest` / `!New sub quest`.
- `q_hide(i)`: `visible = false`. `q_remove(i)`: free the slot. `q_updateInfo(i, text)`: set text.
- `q_isValid(i)` → `kind != 2`; `q_isVisible`, `q_isFinished`, `q_isFailed` → the flag.
- `finished` and `failed` are independent bits: nothing clears one when the other is set.

The messages go to `ai::player::PlayerTable::FindLocalPlayer` S 005bdda0 (the first **active** player entry of kind 2, else
entry 0), so on every machine of a network match only that machine's own player gets them `[known]`.

#### 3.1.3 What the simulation reads

Two predicates over the 40 slots, used only in victory mode 5 (scenario; players-victory.md §3.6) `[known]`
S 00535d70:

- `ai::game::GameQuery::AreAllMainQuestsFinished` S 0052da20: false as soon as one slot has `kind == 0` and
  `finished == false`; true otherwise, so a table without main quests counts as finished.
- `ai::game::GameQuery::IsAnyMainQuestFailed` S 0052da60: true as soon as one slot has `kind == 0` and `failed == true`.

`VictoryCond_Update` evaluates them every tick, after the common winner test, only while the local player is
neither a declared winner nor in a victory state other than 0, in this order `[known]` S 00535d70:

1. all main quests finished → `DeclareWinner(local player)`, then **hide all** quests (`visible = false` in every
   used slot, S 00535fd0); the second predicate is not evaluated on that tick;
2. else any main quest failed → the local player's victory state becomes 3.

Sub quests (kind 1) never decide a match. Any `kind` other than 0 and 2 is treated as a sub quest by every reader
(the tests are `kind == 0` and `kind == 2`).

#### 3.1.4 The victory quest (slot 0)

In the victory modes other than 5 the victory code owns slot 0 `[known]` S 0053a8b0, S 0053a730, S 0053a750,
S 0053a9d0:

- at `tickCounter == 0`: `SetQuest(0, "!VictoryCond_<mode>", kind 0, pos (-1, -1), visible = true)`, where
  `<mode>` is the decimal victory mode (`MapInfo +0x1c8`);
- every victory tick: `SetText` with the local player's progress `"<current>/<goal>"` in modes 1, 2 and 3 (goal:
  the record's own goal in mode 1, the constant 75 in mode 2, 100 in mode 3; players-victory.md §3.6.4) and with
  the **empty string** in every other mode;
- then, if the local player has reached the condition: `finished = true` and `visible = false`, written only
  while `finished` is still false;
- else, if the local player's victory state is no longer 0: `failed = true` and `visible = false`, written only
  while `failed` is still false.

The activation at tick 0 runs before the elimination and progress checks of that tick, the three slot updates
after them. Slot 0 is written without a test of its `kind`.

`VictoryCond_Update` S 00535d70, in this order `[known]`: the slot 0 activation (modes other than 5, tick 0 only);
the elimination check of every player whose victory state is 0; the progress update of every such player; the
declaration of the first player (index order) who is neither eliminated nor already a winner and has reached the
condition (`DeclareWinner`, at most one per tick); then the local part. In mode 5 the local part is the scenario
test, run only while the local player is not a winner and its state is 0: all main quests finished
(`AreAllMainQuestsFinished` S 0052da20) → `DeclareWinner(local)` and every quest slot is hidden; else any main
quest failed (`IsAnyMainQuestFailed` S 0052da60) → the local player's victory state becomes 3. In the other modes
the local part is the slot 0 text and the finished / failed flags above.

A map script that uses quests calls `logic.victory_setupQuests()` first, which selects mode 5 and thereby keeps
the engine away from slot 0.

#### 3.1.5 The script side

The quest logic itself (targets, follow-up quests, briefing pages, quest buttons) is Lua, in
`data\game\scripts\mapTools\quests.lua` and `questTargets.lua`; lua-runtime.md §3.9 describes it. What the engine
contributes is exactly the 40 slots, the two predicates and the callbacks `createQuestUi`, `destroyQuestUi`,
`quest_cinematicDone` and `onLogicTick`. The script numbers its quests with a running index, so a map has at
most 40 quests `[known]` data.

### 3.2 Sacrifices

#### 3.2.1 What can be sacrificed

- A sacrifice is a **definition** (`SacrificeProperty`, Lua `properties.sf_*`). The shipped data has 77: 36 in
  `sacrifices.lua`, 31 good exchanges in `sacrifices_goodExchange.lua`, 10 in `sacrifices_campaign.lua` `[known]`
  data.
- A sacrifice is made at a **sacrifice building**: a building whose type has working mode 9
  (`BuildingWorkingMode_Sacrifice`). The shipped types are `sacrifice`, `sacrificeBav`, `sacrificeClay` and
  `sacrificeOlympicFlame` `[known]` data `buildings.lua`.
- Which definitions a player is **offered** at a building `[known]` S 00637340: the list the map stores for the
  tribe id of the building's owner (`MapInfo +0x204`, a map tribe id → list of sacrifice ids; map-format.md
  field `0x50b`), followed by every key of the player's lock map 2 (written by Lua
  `menu.addSacrifice(player, id, notify)`, players-victory.md §3.10) in ascending id order; the stored flag is not
  tested and an id present in both sources appears twice. The panel has two rows of 8 buttons: definitions with
  `researchDuration > 0` fill one row, the others the second, and entries beyond 8 per row are dropped.
  Computer players use the map's list only (ai-player.md §3.15).
  The offer is a matter of the UI and the AI: `CheckCanOrder` itself does not test membership, so a script
  (`logic.vi_orderSacrifice`) can order any definition `[known]` S 00561240.
- A `MapInfo` of version <= 12 has no usable lists; the loader `NLogic::MapInfo::Load` S 0052bd40 then clears the
  map and fills it, for every tribe of the property database, with a copy of the tribe's allowed list
  (`tp_addAllowedSacrifice`, `TribeProperty +0xa0`) `[known]` S 0052bb40. The second tribe list
  (`tp_addSacrifice`, `TribeProperty +0x50`) is only validated and appended, and nothing reads it `[known]`
  (properties-data.md §2.3: of the 593 functions that reach the property database only `AddSacrifice`
  S 00556400 touches the field). Nothing else fills `MapInfo +0x204` either: besides `Load` and
  `ResetSacrificesFromTribes` only the constructor (empty), the destructor, `Store`, the copy `MapInfo::Assign`
  S 007849f0 and the two readers touch it, and `MapInfo::Reset` S 0052b8d0 leaves it alone `[known]`. A map
  that was never loaded from a file therefore has an empty list (properties-data.md §7).
- The **cost** of a sacrifice is its `costs` list: goods delivered to the building by the normal transport
  system. There is no other currency. A sacrifice has no settler cost.

#### 3.2.2 The building state machine

`VillageSacrifice.state` `[known]` S 00560bd0, S 00561410, S 005615e0, S 00561870, S 00561940, S 00560d70,
S 00560e80:

```
            Order                    Start                     removal of the sacrifice
 2 ready ----------> 3 ordered ---------------> 1 running ----------------------------> 0 spent
    ^                    |                           |                                      |
    |                    | cancel order              | abort (AbortActive sets 2            |
    |                    v                           |        directly after the removal)   |
    |                 0 spent                        v                                      |
    +------------------- output stock empty <--------+--------------------------------------+
```

Per logic tick, for every **finished** building of working mode 9 (`NVillage::Building::Update` S 0055e2f0 calls
it only when both construction remainders are <= 0), `ai::village::VillageSacrifice::Update` S 00561940 `[known]`:

1. `state == 0`: if the building's **output stock** holds no good at all (its map has no entry; an entry is
   erased when its count reaches 0, S 00539f00): `state = 2`, `sacrificeDefId = -1`.
2. `state == 3` and the building type is of the automatic class (below) and `CheckCanStart() == 0`:
   `ai::village::VillageSacrifice::Start` (§3.2.4) with the `targetPlayer` currently stored (-1 unless a command set it).

The **automatic class** is the predicate S 00532960 on the building type: `constructionTime < 1` and not (all of
`depot` +0x54, `casern` +0xf1 and the property byte +0xf5 set) `[known]`, i.e. a type that cannot be built by
the player and is not the castle `[inferred]`; the names of the three bytes are those of village-buildings.md
§2.1. `ai::village::VillageSacrifice::Update` tests the same three fields inline. Among the four sacrifice building types of
the shipped data this is `sacrificeOlympicFlame` (`bp_setConstructionTime(sacrificeOlympicFlame, -1)`) `[known]`
data. Buildings of the other three types start only on a start command (player, AI or script).

#### 3.2.3 Ordering

`VillageSacrifice::CheckCanOrder(defId)` S 00561240 returns the first matching code `[known]`:

| Code | Condition |
|---|---|
| 1 | `state != 2` |
| 5 | the owner's research is running **at this building** (S 0065fb80) |
| 4 | `def.researchDuration > 0` and `defId` is not in the owner's `researched` map |
| 7 | `defId` is in the owner's `regenerations` map (cooling down) |
| 3 | `def` has building dependences and the owner's `dependencies` map has no true entry for `defId` |
| 2 | `def.target == 1` and the owner has no enemy (`PlayerTable::HasEnemyOf`) |
| 6 | the owner's lock map 1 has a true entry for `defId` (`Player::IsLocked(owner, 1, defId)` S 005be970) |
| 0 | can be ordered |

"Has an enemy" (`PlayerTable::HasEnemyOf` S 005bdf30): at least one **active** player entry for which
`Player::IsEnemyOf(entry, owner)` holds.

Code 3 cannot occur in this build: no definition has building dependences (the binding
`sf_addBuildingDependence` discards its arguments, properties-data.md §2.7) and no code inserts into a player's
`dependencies` map (its only functions are `SetPlayerIndex`, `Store`, `IsSet` and `Load`) `[inferred]` from the
function list of the class.

`VillageSacrifice::Order(defId, useFreeTicket)` S 00561410 `[known]`:

1. `useFreeTicket == false`: `freeTicket = false`; every entry of `def.costs` is added to the building's request
   list (`NeedGoods::AddRequests`), so carriers start delivering into the input stock. If `def.target == 1`:
   two messages of type 4 to every active player **except the owner**, without position: `!Player orders
   sacrifice` (arg = the owner's name) and `!Sacrifice ordered` (arg = the definition's name).
2. `useFreeTicket == true`: `freeTicket = true` and the owner's `freeTickets -= 1`; no goods are requested and
   no message is sent.
3. `state = 3`, `sacrificeDefId = defId`, callback "sacrifice ordered at a building" (slot +0xb0).

All three callers test `CanOrder(defId)` (`CheckCanOrder == 0`, S 00561380) first and pass
`useFreeTicket = false`: the command executor S 00782510, the AI S 0058a0d0 and Lua `logic.vi_orderSacrifice`
S 005aeda0 `[known]`. `Order` itself tests nothing. Nothing increments `freeTickets` (its only writers are the
constructor, the decrement in `Order`, and `Load`) `[inferred]` from a search of the function cache. The
free-ticket path is therefore unreachable in the shipped game; a remake may omit it but must keep the field for
save compatibility (§7).

While ordered, the delivered fraction shown by the UI and returned by Lua `logic.pl_getSacrificeState(player,
defId)` is `inputStock.totalUnits / (sum of the amounts of def.costs)` as a float `[known]` S 005613a0,
S 005b0210; `totalUnits` (`Stock +0x14`) counts every unit in the input stock, whatever its good. The Lua
binding returns it for the first finished sacrifice building (in the order of the village's sacrifice building
list) of the player in state 3 with that definition, and returns **nothing** (zero results, not a pushed `nil`;
lua-runtime.md §2.3) when there is none or when the player index is >= 8 or inactive.

#### 3.2.4 Starting

`VillageSacrifice::CheckCanStart()` S 00560f20 returns the first matching code `[known]`:

| Code | Condition |
|---|---|
| 1 | `sacrificeDefId == -1` |
| 2 | the reference to an active sacrifice is set |
| 4 | `state == 0` |
| 3 | `freeTicket == false` and the input stock does not hold every entry of `def.costs` (`Stock::HasAll`) |
| 6 | the definition is in the owner's `regenerations` map |
| 5 | the owner already owns a running sacrifice of this definition (S 00662040) |
| 7 | `def.target == 1` and the owner has no enemy |
| 8 | the owner's lock map 1 has a true entry for the definition |
| 0 | can start |

Code 0 does not require `state == 3`; with `sacrificeDefId != -1` the state is 3 in every reachable case
`[inferred]` (states 1 and 0 are excluded by codes 2 and 4, and state 2 always has id -1).

`ai::village::VillageSacrifice::Start` S 005615e0, in this order `[known]`:

1. callback "order ended" (slot +0xb4) for the building;
2. messages of type 4, without position:
   - `def.target == 1`: to the player `targetPlayer` only: `!Player started a sacrifice against you!` (arg = the
     owner's name) and `!A Sacrifice is targeted at you!` (arg = the definition's name);
   - `def.target == 0`: `targetPlayer` is **overwritten with the owner's index**; then, only if the definition
     has an effect of type 10 (`Effect_PeaceTime`; `SacrificeProperty::HasEffectType(10)` S 00556540), the same
     two messages go to every active player except the owner;
   - any other `def.target` value: no message, `targetPlayer` unchanged;
3. `NSacrifice::System::StartSacrifice(building, sacrificeDefId, targetPlayer)` S 0065f5a0 →
   `SacrificePlayerData::StartSacrifice` S 006624f0 on the **owner's** record:
   1. create the `Sacrifice` (owner = the building's player, the definition, the target, a new unique id,
      `startTick = tickCounter`, one cleared `fired` bit per effect);
   2. append it to the owner's `sacrifices`;
   3. link both ways: `sacrifice.building` = the building, `VillageSacrifice.active` = the sacrifice;
   4. callback "sacrifice started" (slot +0xa0);
   5. `SacrificePlayerTable::RecomputeModifiers` (§3.2.5);
   6. `StartToggleEffects`: for every effect of type 14 in the definition, `Logic_RecalcTerritoryForPlayer(owner,
      notify = 1)` (§3.2.6);
4. `targetPlayer = -1`; the building's **input stock is cleared** (the cost goods are consumed here, all at
   once); `state = 1`.

`ai::village::VillageSacrifice::Start` tests nothing itself; its four callers test `CheckCanStart() == 0` first. The target
index is not validated by the command executor S 007825b0 (game-commands.md, `0x20026`) nor by `Start`. With
`def.target == 1` an index outside 0..7 is an out-of-bounds access `[known]` S 005c00e0, S 005bdd50:
`PlayerMessages_SendToPlayer` computes the player entry as `table + index * 0xf0` without a range test and
dereferences its message list. That includes -1, the value the automatic start of §3.2.2 leaves in place. The
shipped scripts order only `Target_Owner` markers at `sacrificeOlympicFlame` buildings (`olympicFlame` in
`C01.lua`, `indianWrestling` in `C04.lua`, `cursedArrow` in `C06.lua`) `[known]` data, so the case does not arise
there. A remake must reject such a start.

Who sends the start: the local player through action 22 (directly for `target == 0`, through the target chooser
for `target == 1`), computer players through `AiSacrificeManager::StartReadySacrifices` S 00589cd0 (for
`target == 1` it stores `AiSacrificeState::PickRandomTargetPlayer` first; ai-player.md §3.15), scripts through
`logic.vi_startSacrifice(player, x, y, targetPlayer)` S 005aec70 (§3.2.12).

#### 3.2.5 While it runs: modifiers

A running sacrifice changes exactly one modifier table: the one of its `targetPlayer`
(`SacrificeModifiers::ApplySacrifice` S 00663630 accepts a sacrifice only when `targetPlayer` equals the table's
player) `[known]`. For effects of type < 15 the table applies the **own** rule when the sacrifice's owner is the
table's player and the **hostile** rule otherwise; the rules, the neutral values and every reader are in
properties-data.md §3.9.

`SacrificePlayerTable::RecomputeModifiers` S 00662fb0 `[known]`: reset all eight tables to neutral, then for
player 0..7 and each of that player's running sacrifices in list order, offer the sacrifice to all eight
tables. It runs after every start, after every removal and after a load. Between those events the tables are
constant; nothing is recomputed per tick.

Effects of the modifiers on other systems, with the owning document:

| Effect type | What changes while the sacrifice runs | Specified in |
|---|---|---|
| 1 `CarrierSpeed`, 8 `SoldierSpeed` | walking speed of carriers / soldiers of the target | settlers-jobs.md §3.8.1, properties-data.md §3.9 |
| 2 `SoldierArmor`, 3 `SoldierDamage` | armor / hit damage of the target's soldiers | military.md §3.7, §3.9 |
| 4 `ProductionSpeed` | production time of the target's buildings (working modes 6 and 10) | village-buildings.md §3.7 |
| 5 `ArcherAttackSpeed`, 6 `ArcherHitChance` | strike length and hit threshold of bow soldiers | military.md §3.7 |
| 7 `MinerNeedNoFood` | the owner's mines request no food | village-buildings.md §3.8 |
| 9 `ShipSpeed` | speed of the target's ships | navy.md §3.4 |
| 10 `PeaceTime` | **peace**: buildings of the owner cannot be attacked (attack target state 5), the owner cannot start attacks, and a fight in its fighting phase in which the attacker or the defender is in peace time ends | military.md §3.5, §3.6 |
| 11 `BuildingArmor` | catapult damage to the target's buildings is divided | military.md §3.10 |
| 12 `CornDoubleProduction` | the amount of the good `corn` produced by the owner is doubled. Only `corn` (id `0x17626a03`, a literal in S 00661c50): Egyptian farms produce `egyptCorn`, so `sacrifice_nilfloodEgypt` costs its goods and has no effect `[known]`; a simulation-state quirk that compatibility mode reproduces and refined mode fixes (the mod `mods/nilfloodfix` doubles `egyptCorn` too) | village-buildings.md §3.7 |
| 13 `WorkerPause` | rest time of the target's workers is multiplied | settlers-jobs.md §3.5.4 |
| 14 `ExpandTerritory` | territory range of the owner's territory buildings is raised by the value | §3.2.6 |

Types 7, 10, 12 and 14 exist only as own effects (their hostile rule does nothing), type 13 only as a hostile
effect `[known]` properties-data.md §3.9.

#### 3.2.6 Territory toggle (effect type 14)

The range bonus itself is read from the table (`flags[14]`). Because territory is stored, not derived per tick,
the start and the removal of a sacrifice with a type-14 effect each call
`Logic_RecalcTerritoryForPlayer(playerHandle, notify)` once per type-14 effect in the definition: with
`notify = 1` after the start (`StartToggleEffects` S 00661cf0), with `notify = 0` after the removal
(`StopToggleEffects` S 00661d60, called after the sacrifice has been deleted and the tables recomputed)
`[known]`. `Logic_RecalcTerritoryForPlayer(player, flag)` S 00538d10 calls
`MapModifier::RecalcTerritoryAll(cell of the player's first building or (-1, -1), flag)` and, only when the flag
is 1, `NVillage::System::RefreshTerritoryForPlayer(player)` afterwards `[known]`. The recomputation itself is
specified in map-resources.md §3.6. The handle is the record's own player, so a
type-14 effect in a sacrifice aimed at another player would recompute the owner's territory while changing the
target's table `[inferred]`; no shipped definition combines them (all three `expandTerritory` records are
`Target_Owner`) `[known]` data.

#### 3.2.7 While it runs: one-shot effects

Per tick, for every running sacrifice, `ai::logic::Sacrifice::UpdateTimedEffects` S 00660960 `[known]`:

```
elapsed  = float(u32(tickCounter - startTick))
progress = elapsed / float(u32(def.duration))
for i, e in def.effects (list order):
    if e.type > 15 and float(e.threshold) <= progress and not fired[i]:
        ApplyEffect(e.type, e.arg1, e.arg2)
        fired[i] = true
```

Both operands are converted as unsigned 32-bit values to single-precision floats before the division. The
threshold is an integer in the definition (the fifth argument of `sf_addEffect`, truncated), so in the data it is
0 (fires in the first update after the start, normally the tick of the start itself, §4) or 1 (fires in the
update in which `elapsed >= duration`, which is also the update that removes the sacrifice, §3.2.8). A
sacrifice that is aborted earlier never fires its threshold-1 effects `[inferred]`. The update returns at once
for a definition without effects; a `duration` of 0 is not guarded (float division by zero).

One-shot effects in the shipped data `[known]` data: `FunctionGoodExchange` (threshold 1, duration 20),
`FunctionSoldierHeal` and `FunctionExploreEnemy` (threshold 1: they act when the sacrifice **ends**),
`FunctionDestroyShips` (threshold 0). Types 1000, 1005, 1006 and 1007 are used by no shipped definition.

`Sacrifice::ApplyEffect` S 00660500 `[known]`:

| Type | Name in the data | Action |
|---|---|---|
| 1001 | `FunctionGoodExchange` | `arg2` times: add one unit of good `arg1` to the **output stock** of the sacrifice building; then `Statistics::AddGoodAmount(owner, arg1, arg2)` (S 0065ffc0). The goods leave the building through its worker, one plain ware per walk to the flag (`Worker::TryStartBringGoodOut` S 0065cc40, `NMovie::BringGoodOut` S 0077c510), and are free packages from there; the transport system does not dispatch from the building (no `depot` flag). A non-positive `arg2` adds nothing but still calls the statistics |
| 1003 | `FunctionSoldierHeal` | every soldier settler of the **owner** gets full life points (callback slot +0xbc per soldier); then, for every occupied building of the owner in the village's casern list, the remembered life points of the soldiers stocked there are cleared (S 00660270) |
| 1004 | `FunctionExploreEnemy` | for every building of the **target** player whose type has `exploreRadius > 0` and whose territory updater is active: callback slot +0xc4, then `MapModifier::ExploreArea(building cell, exploreRadius, owner)` (S 00660190): one exploration call per building, for the sacrifice's owner |
| 1005 | `FunctionExploreHarbors` | for **every** harbor object of the navy system (no owner filter): callback slot +0xc0 with its cell, then `ExploreArea(cell, radius = arg1, owner)` (S 00660100) |
| 1006 | `FunctionRunScript` | call the map script's global `sacrifice_execute(definition id)` if a map script is loaded (S 005b2410) |
| 1007 | `FunctionExploreMap` | `ExploreArea(cell (0, 0), radius 1000, owner)` (S 00660020): the whole map |
| 1008 | `FunctionDestroyShips` | every ship of the **target** player whose construction is complete (both remaining-work values <= 0) is scheduled to sink (`NNavy::Ship::ScheduleSinking`), in the order of the navy system's ship vector; per ship the sinking is scheduled first and the callback slot +0xb8 is raised after it (S 00660360). Ships still on the slipway are spared |
| 1000, 1002, any other | `FunctionSpawnSoldier`, – | nothing; the `fired` bit is still set |

Types 0..15 are never dispatched here; type 15 is neither a modifier (`type < 15`) nor a one-shot (`type > 15`)
`[known]` S 00663560, S 00660960. Type 0 (`Effect_NoEffect`) is the only effect of the six campaign marker
sacrifices (`olympicFlame`, `indianWrestling`, `stoneToDust`, `cursedArrow`, `generateBeer`, `pacifySachmet`)
`[known]` data `sacrifices_campaign.lua`;
they do nothing by themselves and are there for the campaign scripts to test with `logic.pl_sacrificeStarted`
and `logic.pl_getSacrificeState` `[inferred]`.

In the shipped data the hostile one-shots are aimed through `Target_Enemies` definitions (the target player
chosen at the start), and `FunctionGoodExchange` is always `Target_Owner` `[known]` data.

#### 3.2.8 Expiry, abort, cancel

Per tick, per player record, `SacrificePlayerData::UpdateSacrifices` S 006621f0 walks the list in order
`[known]`: `ai::logic::Sacrifice::UpdateTimedEffects`, then `ai::logic::Sacrifice::IsExpired` (`u32(tickCounter - startTick) >=
u32(def.duration)`); an expired sacrifice is removed and the walk continues with the element that moved into its
place.

`SacrificePlayerData::RemoveSacrifice(unique id)` S 006620a0 — the only way a sacrifice ends `[known]`:

1. callback "sacrifice removed" (slot +0xa4);
2. unlink: clear `sacrifice.building`, then `VillageSacrifice::OnExpired(sacrifice)` S 00561870 on the building's
   component: clear `active`, `state = 0`, and send `!Sacrifice expired!` (type 4, arg = the definition's name, at
   the building) to the owner **if** (`IsExpired(sacrifice)` or the building's `markedOutsideTerritory` byte
   `+0x138` is set) **and** `def.abortable` is true. `NVillage::Building::dtor` S 0055ce70 sets that byte before
   it destroys the component, so the message is also sent when the building of a running abortable sacrifice is
   destroyed. A non-abortable definition (in the data: the good exchanges, the heal, explore and destroy-ships
   definitions and every campaign definition except `archerHitChanceCheap`) ends silently, and a manual abort is
   silent unless the building is already marked;
3. start the cool-down: insert `{def.id, tickCounter}` into the owner's `regenerations` (S 00662860). The call
   is the map's unique insert, so an entry that already exists would keep its older tick `[inferred]`; none
   can exist on the paths through `CheckCanStart`, which refuses a definition that is cooling down;
4. destroy the sacrifice, erase it from the list (order of the rest preserved);
5. `RecomputeModifiers`;
6. `StopToggleEffects(def)` (§3.2.6).

Callers `[known]`:

- natural expiry (above);
- **abort** — command `0x20025` on a building in state 1, allowed only when `def.abortable`:
  `ai::village::VillageSacrifice::AbortActive` S 00560d70 removes the sacrifice, then sets `sacrificeDefId = -1` and
  `state = 2`. The building is ready again at once, the cost is not refunded, and the cool-down still starts;
- **destruction of the building**: `ai::village::VillageSacrifice::dtor` S 00560cf0 removes a still-referenced sacrifice.
- **change of owner**: `NVillage::System::TransferBuildingOwnership` S 0055a210 (soldier capture S 00571af0;
  `ConquerBuilding` S 0055a890, reached from `TransferAllBuildingsOfPlayer` and Lua
  `logic.vi_changePlayerOfBuilding`) does not move the building: it removes the old one
  (`RemoveBuilding(…, spill = false)` → `Building::dtor`) and constructs a new one with
  `Building::ctor_Transfer` S 0055d4e0, which allocates a fresh `VillageSacrifice` (state 2, no definition) and
  an empty research reference `[known]`. So a running sacrifice ends as in a destruction (cool-down and, for an
  abortable definition, `!Sacrifice expired!` for the **old** owner), an order is lost (on the soldier-capture
  path together with the goods already in the old input stock), a research running there is dropped without a
  record (§3.2.10), and the new owner gets a building that is ready `[inferred]`. On the two `ConquerBuilding`
  paths the goods are kept
  `[known]` S 0055a890: before the transfer it moves the old depot's output/store stock (`Depot +0x28`) and
  input stock (`Depot +0x0c`) into two static temporary stocks and counts the present soldiers per level; after
  `TransferBuildingOwnership(…, notify = 0)` it spawns one worker if the old building had any, spawns the
  counted soldiers per level on the new building (level range of the new owner's tribe), moves both stocks
  into the new building's stocks and empties the temporaries. So for a sacrifice building conquered this way
  the goods delivered for the lost order stay in the new building's input stock; the soldier-capture path
  S 00571af0 calls `TransferBuildingOwnership` directly and moves no stock itself (its callees contain no
  stock function) `[known]`.
  `logic.pl_changePlayer` (S 005ad4e0 → `NLogic::System::TransferPlayerAssets` S 00529040) takes the
  `ConquerBuilding` path `[known]`: `NVillage::System::TransferAllBuildingsOfPlayer` S 0055aac0 hands over the
  territory buildings (type flag `+0xf5`) in a first pass and all others in a second; a building whose
  construction (`building +0x44`) still has `remainingA` or `remainingB` above 0 is removed
  (`RemoveBuilding(…, spill = false)`) instead, and every finished one, sacrifice buildings included, goes
  through `ConquerBuilding`. Afterwards the old owner's settlers are removed and its flags, streets and ships
  are re-created for the new owner.

The `markedOutsideTerritory` byte is written true only by `NVillage::System::MarkBuildingsOutsideTerritoryNear`
S 00558170 (called from the territory change handler `MapModifier::OnTerritoryChangedAt` S 00673a50: every
building at hex distance < radius for which `Building::IsFootprintOutsideTerritory` holds) and by
`Building::dtor`; nothing clears it. `NVillage::System::Update` S 0055a640
does not update a marked building and removes it on its next pass (step 6 of §4) `[known]`. A manual abort is
therefore answered with `!Sacrifice expired!` only when the abort command executes between the marking and that
pass `[inferred]`; in every other case the message of a marked building comes from its removal.

**Cancelling an order** (command `0x20025` in another state; allowed when something is ordered, `state != 0` and
the building type is not of the automatic class) → `ai::village::VillageSacrifice::CancelOrder` S 00560e80 `[known]`: clear
the request list, move the whole input stock into the output stock, `state = 0`, callback slot +0xb4. The
delivered goods are thus returned to the economy through the building's output, and the building becomes ready
only when they have been carried away (§3.2.2 step 1). No cool-down starts, and `sacrificeDefId` keeps its value
until the state returns to 2.

Check codes of the abort / cancel action (`GetAbortOrCancelBlockReason` S 00560ed0) `[known]`: state 1 → 0 if
`def.abortable`, else 3; otherwise `sacrificeDefId == -1` → 1; `state == 0` → 2; automatic-class building → 3;
else 0.

#### 3.2.9 Cool-down (regeneration)

`regenerations` maps a definition id to the tick at which its last sacrifice ended. Per tick
`SacrificeRegenerations_RemoveExpired` S 00662720 erases every entry with `u32(tickCounter - startTick) >=
u32(def.regenerationDelay)` `[known]`. While an entry exists the definition can be neither ordered (code 7) nor
started (code 6) by that player, at any of the player's buildings. Progress for the UI:
`float(tickCounter - startTick) / float(def.regenerationDelay)` (S 006626a0).

The cool-down runs from the **end** of the sacrifice, so the time between two starts of the same definition is
at least `duration + regenerationDelay` plus the delivery time of the goods. Data examples `[known]`:
`carrierSpeed` 9000 + 1800, `peaceTime` 6000 + 5400, good exchanges 20 + 1800 / 2400 / 3600 / 5400.

#### 3.2.10 Research

A definition with `researchDuration > 0` must be researched once per player before it can be ordered. Research
costs no goods `[known]` (S 0065fae0 touches no stock).

- Gate, `VillageSacrifice::GetResearchState(defId)` S 005610c0 `[known]`: 2 = needs no research; 1 = the
  owner's research is running (any definition, any building); 3 = already researched; 0 = can be started.
  The UI and the AI start a research only on 0. The command executor of `0x20027` applies a weaker test
  (game-commands.md).
- Start, `SacrificeResearch::Start(defId, building)` S 0065fae0 `[known]`: `def`, `running = true`,
  `startTick = tickCounter`, link both ways with the building, callback "research started" (slot +0xa8).
- While it runs, the building cannot take an order (code 5 of §3.2.3); other sacrifice buildings of the player
  can.
- Completion, per tick `SacrificeResearch::Update` S 0065ff00 `[known]`: when `running` and
  `u32(tickCounter - startTick) >= u32(def.researchDuration)` → `ai::logic::SacrificeResearch::Complete` S 0065fde0: message
  `!Sacrifice Researched` (type 4, arg = the definition's name, at the building) to the building's owner;
  insert `{def.id, tickCounter}` into `researched` (the map's unique insert); callback "research ended"
  (slot +0xac); `running = false`; unlink.
- Cancel (command `0x20028`) `ai::logic::SacrificeResearch::Cancel` S 0065fbd0 `[known]`: callback slot +0xac,
  `running = false`, unlink. Nothing is recorded; a later research starts from 0.
- Destruction of the building: `NVillage::Building::dtor` S 0055ce70 calls the unlink S 0053be30 when the
  building's research reference is set (id at `Building +0x130` != -1). The unlink clears the reference and
  `running` (S 0065fa60); no callback is raised and nothing is recorded `[known]`.
- Progress for the UI: `float(u32(tickCounter - startTick)) / float(def.researchDuration)`, 0 when not running
  (S 0065fb40).

Data `[known]`: 53 `sf_setResearchDuration` calls in the three sacrifice scripts, with the values 3000 (5
calls), 6000 (23), 9000 (24) and 12000 (1); `minerStarve` and `peaceTime` use 9000.

#### 3.2.11 Cinematic pause

`nGame::System::BeginCinematic` S 00782b60 (from `nMenu::Cinematic::OnShow`) calls `PauseForCinematic`
S 0065f550: `paused = true`, `pauseStartTick = tickCounter`. `EndCinematic` S 00782bb0 calls
`ResumeAfterCinematic` S 0065f610: `paused = false` and every running sacrifice of every player gets
`startTick += tickCounter - pauseStartTick` `[known]`.

While paused the whole per-tick update of §4 is skipped: no one-shot effect fires, nothing expires, no
cool-down entry is erased, no research completes. Only the running sacrifices are shifted on resume; the
`regenerations` ticks and the research `startTick` are **not**, so cool-downs and research keep counting game
ticks through a cinematic and are settled in the first update after it `[known]` S 00661ff0 (the shift walks
`sacrifices` only). The modifier tables stay in force during the pause, because they are not recomputed.

The end of a cinematic `[known]` S 005fb3e0, S 005faee0: `nMenu::Cinematic::Update` runs the phases FadeIn →
Playing → Ending → RestoreHud → RestoreTimeScale. A page lasts its text length × 0.1 s (at least 0.5 s) and waits
for its voice-over. Ending calls `nGame::System::EndCinematic` (its sole caller), so the sacrifice pause ends there;
0.5 s later the HUD is restored, 1.0 s after that all dialogs are closed, and `Cinematic::OnHide` S 005faee0 calls
the script's `quest_cinematicDone` and then restores the time scale. The game ticks at speed 1 throughout, so the
pause covers the playing time and `quest_cinematicDone` runs at least 1.5 s of game time after `EndCinematic`.

#### 3.2.12 Lua interface

`[known]` at the addresses given; arguments in Lua order:

| Function | Address | Effect |
|---|---|---|
| `logic.vi_orderSacrifice(player, x, y, defId)` | S 005aeda0 | on the player's sacrifice building found at or nearest to the cell: `CanOrder(defId)` → `Order(defId, false)` |
| `logic.vi_startSacrifice(player, x, y, target)` | S 005aec70 | same building lookup; `target` must pass the binding's player-argument check; `CheckCanStart() == 0` → `targetPlayer = target`, `ai::village::VillageSacrifice::Start` |
| `logic.pl_getSacrificeState(player, defId)` | S 005b0210 | delivered fraction of an ordered sacrifice (§3.2.3), or no result |
| `logic.pl_sacrificeStarted(player, defId)` | S 005b0340 | true if the player owns a **running** sacrifice of that definition |
| `logic.pl_sacrificeStartedOnContinent(player, defId, x, y)` | S 005b0430 | true if such a sacrifice's building stands on the continent of the cell; no result otherwise |
| `logic.vi_isSacrificeBuildingAtContinent(player, x, y)` | S 005b0970 | true if a finished sacrifice building of the player stands on the continent of the cell |
| `logic.pl_sendOrderSacrificeMessage(player, defId)` | S 005b1000 | the two "ordered" messages of §3.2.3 to everyone but `player`, whatever the definition's target |
| `logic.ai_enableSacrifices(player, bool)` | S 005ae0a0 | AI switch (ai-player.md) |
| `menu.addSacrifice(player, defId, notify)` | S 005dac60 | lock map 2 entry (offer list, §3.2.1); with `notify`, message `!New Sacrifice available` (type 4, arg = the definition's name, no position) |
| `menu.lockSacrifice` / `menu.unlockSacrifice(player, defId)` | S 005dab40 / S 005dabd0 | lock map 1 entry set / erased (codes 6 and 8) |
| `menu.showSacrificeEffect()` | S 005d9550 | plays the HUD "sacrifice started" picture; presentation only |
| script global `sacrifice_execute(defId)` | S 005b2410 | called by effect 1006 |

#### 3.2.13 Presentation: the sacrifice building's movie

Presentation only; no simulation state `[known]` S 006ace00, S 006acf70, S 006ad050 (particles.md §3.13). The scene's
sacrifice building plays one effect movie at a time (callback slots +0xa0 started, +0xa8 research, +0xb0 waiting
for goods; +0xa4, +0xac, +0xb4 stop it). `StartEffect` back-dates the running sacrifice's movie to
`now − (end − start) · timeInfo[2]`, the ticks already run, so a sacrifice re-announced after a load resumes at
the point it had reached. The research movie is back-dated by the research's **absolute** start tick
(`startTick` of §3.2.10, not the ticks run), so its early keyframes are always past when it starts: the ignite
sound keyframe never plays and the fire burns at once. A remake in compatibility mode need not reproduce it; it is
a look, not a state.

### 3.3 Statistics

The complete sampling rules are in players-victory.md §3.11; this is the rule set a statistics screen and the
Lua readers depend on `[known]` S 00537ba0, S 0053b2c0, S 0053b420, S 00537230, S 00538460:

**What is counted, and when**

| Quantity | Updated | Rule |
|---|---|---|
| produced amount per good / job | at the event | `Statistics::AddGoodAmount(player, good, n)`: `history[good].last += n`. Callers: production delivery, soldier training and soldier upgrade completion, the release of a produced settler (working mode 4, state 0x24, S 0065d7f0: 1 of `BuildingProperty +0xec producedSettler` per spawned settler), a gatherer's harvest put down (`NMovie::PutDownPackage::Update` S 0077a8e0: the full harvest count, added when the first unit's drop completes and before the flag is looked up for the extra units, so extra units that are discarded still count; settlers-jobs.md §3.5.5), the good-exchange sacrifice |
| coin counter | at the event | `+1` per `AddGoodAmount` call whose good is the tribe's `soldierUpgradeGoodId`, whatever `n` |
| kill counter | at the event | `+1` for the attacker's player when a soldier's life points drop below 1 |
| building productivity | at the event | first production event of a building without an entry: 0.5; later events `+0.25`, capped at 1.0 (`RegisterProductionEvent`). Placing a building and transferring it to another owner set 0.5 (`ResetBuildingProductivity` S 00538440). `GetProductivity` S 005373b0 returns -1.0 for a building without an entry |
| the eight series | every 600 ticks | below |

**Schedule** (`tickCounter % 600`, computed on the tick converted to float, players-victory.md §3.11): tick 0 of
the match activates the statistics of every active player, zeroes the three counters and seeds one history entry
`[0]` for every good id and job id of the player's tribe (an id in both lists gets `[0, 0]`). Phase 0:
productivity decay (every entry of a finished building: idle counter `+1`, productivity `-0.05`, floor 0;
entries of vanished buildings are erased), series 0 and `regionSize`, then the period commit (every history gets
a new last element equal to its previous last element, series 7 gets `killCount`). Phase 1: series 3 and 5.
Phase 2: series 1. Phase 3: series 2 and 4. Phase 4: series 6. Every vector is capped at 960 elements by
dropping the oldest. 960 samples × 600 ticks = 576 000 ticks of history.

Consequences `[inferred]`: the histories are **cumulative** counts since the start of the match (each period
starts from the previous total), so "produced in the last period" is the difference of the last two elements;
series 7 is the cumulative kill count; series 5 is the cumulative coin event count.

**Lua readers** `[known]`: `logic.pl_getProducedGoodCount(player, good)` S 005b0e80 = last element of the good's
history (the cumulative total; the good must be one of the tribe's goods or jobs); `logic.pl_getMilitaryStrength`
= latest sample of series 4, 0 while the series is empty (S 0053ad50); `logic.pl_getRegionSize`,
`logic.pl_getBuildingProductivity` (players-victory.md §3.11). The average productivity
(`GetAverageBuildingProductivity` S 00533160) is `(sum / count) × 100` over the productivity map, summed in
ascending unique-id order (the float sum depends on that order).

**The statistics screen and the end of a match.** There is no separate end-of-game data set: the end dialogs
(`Victory`, `Report`, `Defeat`) open the same statistics panel that the HUD button opens during the match, on the
same `PlayerStatistics` objects (ingame-ui.md §3.8.1, §3.9) `[inferred]` from those two sections. The panel
shows: per player a curve of one of the eight series (combo entries `!Regions`, `!Buildings`, `!Settlers`,
`!Goods`, `!Military Strength`, `!Coin Amount`, `!Productivity`, `!Defeated Enemies`, in series order); per good
the history curve; per building type count, count under construction and average productivity. Nothing of the
statistics is sent to the referee: `FinishGame` (0xDC0) carries the game id, map GUID, map settings and the
winner's avatar id only (players-victory.md §3.7) `[known]` S 00479c40.

### 3.4 Chests

#### 3.4.1 Creation and placement

`LogicChestSystem::AddChest(kind, cell)` S 0052d560 `[known]`: remove a resource object on the cell
(`NResources::System::GetResourceAt` / `RemoveResourceAt`) and a doodad on the cell's fine position
(`x*4 (+2 on odd rows), y*4`; S 0052d110); construct the chest (new unique id, owner
-1, kind, content {-1, 0}, value 0, progress 0, **grid bit 0x400 set** on the cell); append it; callback "chest
added" (slot +0xc8). There are three callers:

| Caller | Kind | Content |
|---|---|---|
| `Game_DistributeChestsForNetworkMatch` S 00775dd0 — once at world creation of a new network match | 0 | `contentValue` = one value of a private generator seeded with the match's `GameSeed`; number and sites as specified in players-victory.md §3.4 and logic-core.md §3.5: `activePlayers * (chestPositions / startPositions)` chests (integer division), each on the remaining candidate of `MapInfo.chestPositions` that is farthest from the nearest player start building |
| Lua `logic.map_createChest(x, y, good, amount)` S 005ad740 | 1 | `SetContentGood(good, amount)`; nothing happens when the cell is off the map or `good == -1`. No walkability test |
| the debug map tool S 00604dd0 | 1 | `SetContentGood(good selected in the tool's list, 10)`; guarded by `Map_CanPlaceChestAt` S 0052e710: no chest on the cell and the cell is walkable |

A map file does not contain chests, only candidate cells (`MapInfo +0x14`); chests exist in a save (§7). No
shipped Lua file calls `map_createChest` `[known]` data (355 scripts searched), so in the shipped game chests
appear only in network matches.

#### 3.4.2 Opening

Per tick, only while `enabled`, for every chest in vector order that is **not yet open**
(`ai::logic::LogicChestSystem::Update` S 0052d660, `LogicChest::UpdateOpening` S 00539520) `[known]`:

```
cellOwner = territory owner of the chest's cell            // -1 = nobody
if cellOwner == chest.ownerPlayer:
    chest.openProgressTicks += 1
else:
    chest.openProgressTicks = 0
    if cellOwner != -1:
        message type 5 "!Player is trying to open a chest!", arg = cellOwner's name, at the chest,
                to every active player except cellOwner
        message type 5 "!chest found", no arg, at the chest, to cellOwner
chest.ownerPlayer = cellOwner
```

A chest is **open** when `ownerPlayer != -1` and `openProgressTicks >= GameConfig.chestOwningTime`
(`ai::logic::LogicChest::IsOpenable` S 00539210). `chestOwningTime` is 3000 ticks (compiled default; no shipped script sets
it). On the tick a chest becomes open, in this order `[known]`:

1. the system's observers are called with the chest (below);
2. callback "chest opened" (slot +0xd0): the scene swaps the closed model for the open one;
3. message type 5 `!chest opened!`, no arg, at the chest, to the owner;
4. message type 5 `!chest opened by Player!`, arg = the owner's name, at the chest, to every other active
   player.

An open chest is never updated again and is never removed: it stays on the map with the open model, keeps its
grid bit, and its `ownerPlayer` no longer follows the territory `[known]` (the only remover is
`ai::logic::LogicChestSystem::Reset` S 0052d360). The owning time must be served without interruption by **one** owner:
any change of the cell's owner, including to nobody, resets the counter.

#### 3.4.3 Content

Observers of the opening `[known]`:

- `NVillage::System::AddGoodsToPlayerStoreBuilding` S 005587c0 (subscribed in `InitSubsystems`): for a chest of
  **kind 1**, find the opener's castle (`FindPlayerBuildingWithDefFlags` S 005579a0: the first building of the
  player whose type has `depot`, `casern` and the property byte +0xf5 set; the search of
  players-victory.md §3.6.1) and add `contentGoodCount` units of `contentGoodId` to its **output stock**
  (`Stock::AddEntry`). If the player has no such building the content is lost. `Statistics::AddGoodAmount` is
  not called.
- `Referee_OnChestOpened_SendClaimChest` S 00782a60 (subscribed in `nGame::System::BuildScene`): for a chest of
  **kind 0** whose opener is not a player of kind 1 and has a slot in the NComm game information, send the
  referee message `ClaimChest` (0xDAC) with the game id, the map GUID, the opener's avatar id and
  `contentValue` as chest id. Every machine of the match sends it (no local-player test): in a two-player
  match both clients sent `ClaimChest` in the same moment, both naming the opener as actor `[live, 2026-10-14]`.
  Each client draws `contentValue` from its own `GameSeed` (0xDB8): with the same seed on both clients the four
  chests held identical values, with different seeds the same four cells held different values and the two
  claims carried different chest ids, without a desync `[live, 2026-10-14]`. A server therefore has to send every
  client of a match the same `GameSeed` for the claims to name one chest.

A kind-0 chest changes **nothing in the simulation** when it opens `[known]`: the observer of kind 1 ignores it
and the referee observer only sends. What the opener receives is decided by the lobby server; the
client's handlers of the answers `ClaimChestAcknowledge` (0xDAD) and `ClaimChestResult` (0xDAE) log and notify
observer lists (docs/message-catalog.md). The two lists of the result, `RefereeServerConnection +0x38` (ok) and
`+0x44` (failed), have no subscriber: no call of `ObserverList::Subscribe` S 00458860 names them, so the result
shows no message and plays no sound `[known]` S 0047a160. In an offline game no kind-0 chest exists.

### 3.5 Spawn points

- **Creation.** Spawn points come from the map file (section `Logic SpawnSystem`, §7) or from the debug map
  tool (`LogicSpawnSystem::AddSpawn` S 0052cf50, guarded there by `Map_IsCellFreeForSpawn`). The factory
  `LogicSpawn_CreateFromProperty` S 0052c990 creates
  a `SpawnResource` for a type record with `type == 0`, a `SpawnAnimal` for `type == 1`, and returns null for
  any other value; `Load` and `AddSpawn` use the result without a null test `[known]`.
  `Spawn::PlaceAt` S 00538e10 stores the cell, sets grid bit 0x400, invalidates the construction map around the
  cell and assigns a new unique id. A spawn loaded from a file keeps the id stored in the file and does not set
  the grid bit on load (map-resources.md §7).
- **Trigger** (`LogicSpawnSystem::Update(tick)` S 0052ccc0), per tick, for every spawn in vector order
  `[known]`: `interval = record.rate * GameConfig.spawnPointUpdateTime` (32-bit signed product, sign-extended to
  64 bits); when `(i64(u32 tick) + i64 uniqueId) % interval == 0` (signed 64-bit remainder) the spawn's virtual
  `Spawn()` runs. The unique id is the phase, so spawn points fire on different ticks. With the shipped
  `spawnPointUpdateTime = 1200` and `rate = 1` each spawn fires every 1200 ticks. An interval of 0 divides by
  zero.
- **Animal spawn** (`SpawnAnimal::Spawn` S 00538f40) `[known]`: if the animal area containing the cell is not
  crowded (map-resources.md §3.10), `index = LogicRandom_Next() % count(record.uniqueIds)`, create that animal
  type at the spawn cell (`NResources::System::SpawnAnimal`, which draws once more for the new animal,
  map-resources.md §3.10), set its state to 6 (just spawned), callback "spawn point triggered" (slot +0xdc). A
  crowded area means no draw and no callback.
- **Resource spawn** (`SpawnResource::Spawn` S 005390e0) `[known]`: add one unit of the **first** id of
  `record.uniqueIds` to the centre cell and to every in-map cell of the hexagonal rings up to radius
  `record.range`, each through `MapModifier::AddResourceAtCell` (amount capped at 7), then the callback. No
  random draw. Specified in logic-core.md §3.5 and map-resources.md §3.8.
- **Queries.** `FindAnimalSpawnInRange(cell, good, maxDistance)` S 0052cae0: the first animal spawn within hex
  distance `<= maxDistance` of which at least one animal type yields `good`; used by the hunting-ground score of
  building placement `[known]`. `FindSpawnAt(cell)` S 0052ca70.
- **Removal.** Only the debug map tool removes a spawn (`RemoveSpawnAt` S 0052ce80: callback "removed", grid bit
  cleared, id set to -1, the last vector element is moved into the freed slot — the vector order changes)
  `[known]`. During a match the set of spawn points is constant.

Shipped data `[known]` `spawnpoints.lua`: 12 types, all `SpawnType_Animal`; `sp_setRange` and `sp_setRate` are
never called, so `range` 3 and `rate` 1 everywhere. The map script helper `mapTools\spawnDepots.lua` is unrelated
to this system: it is a Lua routine that places goods into depots on a tick counter (lua-runtime.md §3.9).

### 3.6 Player messages

#### 3.6.1 Mechanics

`[known]` S 005c00e0, S 005c0120, S 005c0270, S 005c01b0, S 005c05b0, S 005c2360, S 005c1bb0, S 005c1c10:

- `SendToPlayer(type, player, text, arg, cell)`: append a new message to that player's list and call every
  listener's "added" method.
- `SendToAllExcept(type, except, text, arg, cell)`: the same for every **active** slot 0..7 other than `except`.
- `SendOrRefreshToPlayer(type, player, text, arg, cell)`: if the player's list already holds a message with the
  same type, text and arg whose cell is within hex distance `< 1` of `cell` (i.e. the same cell; S 005c1e40),
  set its `timeRemaining` back to 600.0 and notify "updated"; otherwise add a new one. Other senders do the same
  by hand with `FindNear...` and their own distance.
- The finders: `Messages::FindMatchingWithArg` S 005c1e40 takes the **first** listed message (oldest first) with
  the same type, text key and arg and `MapPos::HexDistance` S 00675040 (cell, message cell) `< maxDist`, compared
  signed; `Messages::FindMatching` S 005c1fd0 is the same without the arg. A match is refreshed by
  `Timer_ResetTo600AndRegister` S 005c0230 (`timeRemaining = 600.0`, then `NotifyMessageUpdated` S 005c1d80); the
  matched message keeps its cell. Callers and distances `[known]`: `SendOrRefreshToPlayer` S 005c0270 (maxDist 1) from
  `Military::Update` S 005609b0, `Transport_CarrierTryPlacePackageOnFlag` S 0064dae0 (`!flag blocked`, empty
  arg), `LookForDeposit::Start` / `LookForAnimal::Start` (calls at S 00778e09 / S 00778eff) and
  `LookForFishing::Start` S 0077f670; `PlayerMessages_FindNearWithArgForPlayer` S 005c01f0 from `OnCatapultHit`
  S 0055e080 (maxDist 1) and the geologist's `GoDigging::PlaceResourceSignAndNotify` S 0077b2f0 (maxDist 7, the
  `PUSH 0x7` at 0077b430); `NotifyLostTerritory` S 006797f0 uses `FindMatching` (distance `< 1`, arg not
  compared) and refreshes nothing. There is no other memory of what was reported: no per-cell bits, no flood
  fill; a geologist's find posts a new message once it is 7 or more cells from every listed message of that good,
  or after the matching message expired or was removed.
- `SendLetterToPlayer(player, text)`: a message of type 8 made with the two-text constructor, `text2` empty
  (`Messages::AddWithText2` S 005c2440).
- Lifetime: every logic tick `ai::player::Player::Update` subtracts the **frame time in seconds** from `timeRemaining` of
  every message of every active player; the message HUD of the local player removes messages whose
  `timeRemaining <= 0` (`RemoveExpired`, called from `nMenu::Messages::Update`). The lists of the other players
  are aged but only pruned on the machine where that player is local `[inferred]` (the only caller of
  `RemoveExpired` is the HUD). Details and the consequence for determinism: players-victory.md §3.9, §8.
- Messages are created for every recipient on every machine, whether or not the recipient is local. Which
  player's list is shown is the HUD's choice.

#### 3.6.2 Catalogue: which event raises which message

Type 1 military, 2 geologist, 3 economy, 4 sacrifice, 5 chest, 6 navy, 7 miscellaneous, 8 letter. "R" = sent
with `SendOrRefreshToPlayer` (or the equivalent code in `ai::player::Player::Update`); rows that say "no such message
exists" call a finder first and `SendToPlayer` only when it finds nothing. When the finder does find one, the
catapult-hit, mine-search and geologist rows reset its `timeRemaining` to 600 (the same effect as "R"); the
lost-territory and expedition rows leave it untouched. Text key, type, recipient, `arg` and
position are `[known]` at the address given; the full trigger conditions are in the document named.

| Type | Text key | Raised when | To | Arg | Cell | Function | Rules in |
|---|---|---|---|---|---|---|---|
| 1 | `!You are under attack!` | an attack on a building starts | the building's owner | building type name | building | S 00576500 | military.md §3.5 |
| 1 | `!attack failed` | the last attacker is removed from a fight whose target building still exists and is not the attacker's | the attacking player | building type name | building | S 005719b0 | military.md §3.6 |
| 1 | `!attack averted` | same event | the building's owner | building type name | building | S 005719b0 | military.md §3.6 |
| 1 | `!Lost Military Building to enemy.` | a building changes owner (with the transfer's `notify` flag) | the old owner | building type name | building | S 0055a210 | village-buildings.md §3.16, military.md §3.8 |
| 1 | `!Military Building conquered.` | same event | the new owner | building type name | building | S 0055a210 | village-buildings.md §3.16 |
| 1 | `!Castle was destroyed!` | a soldier takes an enemy building of the castle type | every active player except the castle's owner | the owner's name | building | S 00571af0 | military.md §3.8 |
| 1 | `!Military Building Destruction executed` | the delayed destruction of a military building executes | the building's owner | building type name | building | S 00560890 | military.md §3.8 |
| 1 | `!Attack Target has been destructed` | same event, while the building is the target of a fight | the attacking player of that fight | building type name | building | S 00560890 | military.md §3.8 |
| 1 R | `!Building is not connected` | the upkeep of an empty military building with an open soldier order finds, on every 600th tick of that state, that the order system reports supply status 1 for it | the building's owner | building type name | building | S 005609b0 | military.md §3.3 |
| 1 | `!Military building occupied!` | a territory building that is not of the castle type becomes occupied and its territory updater is activated; type has `territoryRange >= 1` | the building's owner | building type name | building | S 005653d0 | village-buildings.md §3.14 |
| 1 | `!Watchtower occupied!` | same event for a type with `territoryRange < 1` and `exploreRadius >= 1` (no message when both are below 1) | the building's owner | building type name | building | S 005653d0 | village-buildings.md §3.14 |
| 1 | `!Building hit by Catapult` | a catapult projectile hits a building and no such message for the same building type exists at the projectile's source cell (distance < 1) | the building's owner | building type name | the projectile's source cell (`MilitaryProjectile +0xc0`, the catapult building's anchor) | S 0055e080 | military.md §3.10 |
| 1 | `!Building destroyed by Catapult` | the hit takes the last hit points | the building's owner | building type name | the projectile's source cell | S 0055e080 | military.md §3.10 |
| 1 | `!Enemy Building destroyed by Catapult` | same event | the projectile's player | building type name | building | S 0055e080 | military.md §3.10 |
| 1 | `!Lost Territory.` | a territory recomputation with `notify` took cells from a player and no such message exists at that cell | that player | empty | see map-resources.md | S 006797f0 | map-resources.md §3.6 |
| 1 R | `!low soldiers` | periodic check: fewer than 5 stocked soldiers | the player | empty | none | S 005bf8a0 | players-victory.md §3.9 |
| 2 | `!Found Resource` | a geologist places a resource sign and no such message for the same good exists within hex distance < 7 (an existing one is refreshed by the caller) | the geologist's owner | good name | the cell | S 0077b2f0 | settlers-jobs.md §3.5.5, map-resources.md §3.8 |
| 3 R | `!low resources` | periodic check: a construction good or the worker tool below its threshold | the player | good name | none | S 005bf8a0 | players-victory.md §3.9 |
| 3 R | `!No resources found.` | a mine's resource search, or a worker's search for a deposit, an animal or a fishing place, fails while the building's productivity is below 0.5 (S 0055ded0 looks for an existing message by type, text and cell only, the three worker paths also compare the arg) | the building's owner | building type name | building | S 0055ded0, S 00778d50, S 00778e40, S 0077f670 | village-buildings.md §3.9, settlers-jobs.md §3.5.5 |
| 3 R | `!flag blocked` | a carrier cannot put its good down on a full flag; every 180th attempt | the package's owner | empty | flag | S 0064dae0 | streets-transport.md §3.9 |
| 4 | `!Player orders sacrifice`, `!Sacrifice ordered` | a hostile sacrifice is ordered with goods; Lua `pl_sendOrderSacrificeMessage` | all active players but the owner | owner name; sacrifice name | none | S 00561410, S 005b1000 | §3.2.3 |
| 4 | `!Player started a sacrifice against you!`, `!A Sacrifice is targeted at you!` | a hostile sacrifice starts; or an own sacrifice with a peace-time effect starts | the target; or all active players but the owner | owner name; sacrifice name | none | S 005615e0 | §3.2.4 |
| 4 | `!Sacrifice expired!` | an abortable sacrifice ends by time, or is removed while its building is marked or being destroyed | the owner | sacrifice name | building | S 00561870 | §3.2.8 |
| 4 | `!Sacrifice Researched` | a research completes | the building's owner | sacrifice name | building | S 0065fde0 | §3.2.10 |
| 4 | `!New Sacrifice available` | Lua `menu.addSacrifice(…, true)` | the named player | sacrifice name | none | S 005dac60 | §3.2.12 |
| 5 | `!Player is trying to open a chest!` | a chest's cell gets a new owner | all active players but that owner | owner name | chest | S 00539520 | §3.4.2 |
| 5 | `!chest found` | same event | that owner | empty | chest | S 00539520 | §3.4.2 |
| 5 | `!chest opened!` | a chest opens | the owner | empty | chest | S 0052d660 | §3.4.2 |
| 5 | `!chest opened by Player!` | same event | all active players but the owner | owner name | chest | S 0052d660 | §3.4.2 |
| 6 | `!Ship constructed` | a ship is finished | the constructor's owner | ship name key | ship cell | S 0077d6c0 | navy.md §3.3 |
| 6 | `!No Place for Ship found!` | a ship-building site finds no place for its ship | the constructor's owner | building type name | building | S 0065e770 | navy.md §3.3 |
| 6 | `!Harbor is not Connected`, `!No Soldier for Expedition found` | an expedition cannot gather its cargo (supply status 1 or 2) and no message of that type and text exists at the ship's cell | the ship's owner | ship name key | ship cell | S 005b8470 | navy.md §3.10 |
| 6 | `!Ship waiting for Orders`, `!Harbor is already captured!`, `!No Valid Position for Building found!` | expedition states 4, 5 and 6 | the ship's owner | ship name key | ship cell | S 005b8ac0 | navy.md §3.10 |
| 7 | `!Building constructed` | a constructor finishes a building | the building's owner | building type name | building | S 0077daf0 | village-buildings.md §3.4 |
| 7 | `!New main quest`, `!New sub quest`, `!main quest finished`, `!sub quest finished`, `!main quest failed`, `!sub quest failed` | Lua `q_add`, `q_reset`, `q_finish`, `q_failed` | the local player | quest name | quest marker | S 005b1670, S 005b1980, S 005b1850, S 005b1ab0 | §3.1.2 |
| 8 | `<localised "!DEFEAT">: <name of i> (<i>)` (letter; the text is composed and already localised, not a key) | the elimination check finds player *i* without a castle-type building, while the local player is not eliminated, *i* is active and of kind 3, and the NComm manager is not in role 0 | the local player | – | none | S 00535b90 | players-victory.md §3.6.1 |
| 8 | free text (letter) | Lua `menu.createLetter`; a network message shown as a letter | the screen's player | – | none | S 005da720, S 005eb120 | lua-runtime.md §3.7, ingame-ui.md |
| 8 | `!Autosave...` | the autosave interval elapsed (wall-clock time, offline games only) | the local player | empty | none | S 0078b040 | save-format.md §4 |

The table lists every function that calls one of the send helpers (`PlayerMessages_SendToPlayer`,
`SendToAllExcept`, `SendOrRefreshToPlayer`, `SendLetterToPlayer`) `[known]` (search of the function cache).

### 3.7 Tutorial pages and hints

There is no tutorial or hint logic in the simulation `[inferred]` (no function of the `NLogic`, `NVillage`,
`NSettlers` or `ai::logic` namespaces carries such a name, and the only tutorial entry point is a menu binding).

- `menu.addTutorialPage(key)` S 005daa30 adds a page with title key `key` and description key `key .. "_desc"`
  to the HUD panel `nMenu::Tutorial` and, when the panel's virtual query at slot +0x2c returns false, shows the
  newest page `[known]`; the HUD button `btTutorial` (hotkey `t`) is hidden until a page exists
  (ingame-ui.md §3.4).
- The helper `mapTools\tutorial.lua` keeps a Lua table `tutorial_data` of `{name, info}` pairs filled by the
  map's `setupTutorial()`, shows a page by name (`tutorial_show`, also wired to quests as
  `quest_showTutorial(quest)`), and records the order of shown pages in the script store under the keys
  `tutorialShowed<n>` so that `tutorial_onLoaded` can replay them after a load `[known]` data.
- The periodic warnings (`!low resources`, `!low soldiers`, `!No resources found.`, `!Building is not
  connected`, `!flag blocked`) are the game's only built-in hints; they are ordinary messages (§3.6.2).

---

## 4. Update order

Per logic tick, inside `NLogic::System::Update` (the full list is logic-core.md §4.2) `[known]`:

| Step | Call | Work of this document |
|---|---|---|
| 2 | `NComm_Manager::AdvanceNetTick` | executes player commands: sacrifice order / start / abort / research (`0x20024`..`0x20028`) |
| 4 | `ai::player::Player::Update` per active player | message timers; every 22 ticks the low-stock warnings |
| 6 | `NVillage::System::Update` | per sacrifice building `ai::village::VillageSacrifice::Update`: state 0 → 2, automatic start |
| 15 | `Statistics::Update` | only if initialised; tick 0 reset; phases 0..4 of every 600 ticks |
| 16 | `NAI::System::Tick` | computer players order, research and start sacrifices (every 647 ticks) |
| 17 | `NSacrifice::System::Update` | unless paused: for player 0..7: (a) each running sacrifice in list order: one-shot effects, then expiry and removal; (b) erase finished cool-downs; (c) complete the research |
| 18 | `LogicSpawnSystem::Update(tick)` | spawn triggers in vector order |
| 19 | `ai::logic::LogicChestSystem::Update` | unless disabled: opening progress in vector order |
| 20 | `VictoryCond_Update` | victory quest (slot 0), scenario predicates |
| last | map script `onLogicTick(tick)` | the script's quest evaluation (`logic.q_*`, `logic.vi_*`) |

Order facts that follow `[inferred]`:

- A sacrifice started by a command (step 2), by the automatic start (step 6) or by a computer player (step 16)
  gets its first update in step 17 of the same tick with `elapsed = 0`: threshold-0 effects fire on the start
  tick. A sacrifice started by a
  script (last step) gets its first update on the next tick with `elapsed = 1`.
- In step 17 player 0's sacrifices are processed completely before player 1's. A threshold-1 effect and the
  removal of the same sacrifice happen in one step, the effect first.
- A cool-down entry created in (a) is examined in (b) of the same step; with `regenerationDelay = 0` it is
  erased at once.
- The modifier tables change only inside `StartSacrifice` and `RemoveSacrifice` (and once per player record in
  `Load`): a start happens in steps 2, 6, 16 or the script step; a removal in step 2 (abort), step 17 (expiry)
  or in whichever step deletes the sacrifice building (`ai::village::VillageSacrifice::dtor`, reached from
  `NVillage::System::RemoveBuilding` S 00559db0: the village update of step 6, a command, a capture in the
  military step, a script) — never between two systems that read them within a step.
- Step 6 skips `Building::Update` for a building whose `markedOutsideTerritory` byte is set and removes that
  building instead (`NVillage::System::Update` S 0055a640) `[known]`; its running sacrifice ends there.
- Steps 16 and 19 do nothing during a cinematic: `BeginCinematic` S 00782b60 clears the AI system's `enabled`
  flag and the chest system's `enabled` flag, `EndCinematic` S 00782bb0 restores both `[known]`.

Per frame: nothing of the simulation. The HUD prunes expired messages and redraws quest lines, the sacrifice
bar and statistics from the objects above.

At world creation (`InitSubsystems` S 00527f70): statistics `Init` (eight `PlayerStatistics`), `Quests::Reset`,
`NSacrifice::System::Init` (eight player records bound to their indices), chest system initialised and the village
subscribed to chest openings, spawn system `[known]`. Afterwards `Game_LoadWorldFromDescriptor` S 005ac770
runs the chest distribution (§3.4.1) after the map file is loaded and the players are created, when the map
type is one that starts a new game (S 0052c270: map types 0, 1, 2, 100 and 102) and the NComm game
information has a non-zero `GameSeed` or a non-zero game id `[known]`.

On load: §7.

---

## 5. Inputs and outputs

**Consumes**

| From | What |
|---|---|
| property database | `SacrificeProperty`, `SpRecord`, `GameConfig.chestOwningTime` (+0x5c), `.spawnPointUpdateTime` (+0x50), `.chestDoodadId` (+0x44), `.openChestDoodadId` (+0x48), `TribeProperty.soldierUpgradeGoodId`, building type bytes (`depot`, `casern`, +0xf5, `constructionTime`, working mode) |
| `MapInfo` | sacrifice lists per tribe (+0x204), chest candidate cells (+0x14), start positions, victory mode (+0x1c8) |
| player table | active flag, name, tribe, kind (local = 2), `IsEnemyOf`, lock maps 1 and 2, the per-player message list |
| map | territory owner grid (chests), continents (two Lua readers), grid bit 0x400, exploration (`ExploreArea`) |
| village | the sacrifice building and its depot stocks and request list; the castle search; building lists |
| commands | `0x20024`..`0x20028` (game-commands.md) |
| NComm game information | `GameSeed`, game id, map GUID, slots and avatar ids (chest placement, `ClaimChest`) |
| map script | `logic.q_*`, `logic.vi_*Sacrifice`, `logic.pl_*`, `menu.*Sacrifice`, `logic.map_createChest` |

**Produces**

| To | What |
|---|---|
| every system that reads a modifier | the eight `SacrificeModifiers` tables (properties-data.md §3.9) |
| transport | goods requests of an ordered sacrifice; goods in output stocks (good exchange, cancelled order, chest content) |
| map | territory recomputation (effect 14), explored areas (effects 1004, 1005, 1007), ground resources and animals (spawn points), removed resource / doodad under a new chest, grid bit 0x400 |
| settlers / navy | healed soldiers (1003), ships scheduled to sink (1008) |
| victory conditions | the two main-quest predicates; slot 0 written by the victory code |
| statistics consumers | AI (`GetProductivity`, military strength), Lua readers, the statistics panel |
| callback manager | slots +0xa0..+0xdc (logic-core.md §3.7): the scene's effects on sacrifice buildings, buffed settlers and buildings, chest models, spawn markers; the HUD's sacrifice bar |
| players | messages (§3.6.2) |
| referee server | `ClaimChest` (0xDAC) for kind-0 chests |

---

## 6. Data-driven parameters

| File | Keys | Feeds | Example values |
|---|---|---|---|
| `data\game\scripts\properties\sacrifices.lua` | `sf_create`, `sf_setName`, `sf_setGfxName`, `sf_setBuffGfxName`, `sf_addCost`, `sf_setDuration`, `sf_addEffect`, `sf_setAbortable`, `sf_setCategory`, `sf_setRegenerationDelay`, `sf_setTarget`, `sf_setResearchDuration`; the constants `Effect_*`, `Target_*`, `SacrificeCategory_*` | definitions | `carrierSpeed`: cost water 20 + whisky 3, duration 9000, `Effect_CarrierSpeed` 300, regeneration 1800, `Target_Owner`. `peaceTime` (Scots): salt 10, sheep 5, gemstones 3; duration 6000; regeneration 5400; research 9000. `workerPause`: `Effect_WorkerPause` 300, `Target_Enemies`, duration 6000 |
| `…\sacrifices_goodExchange.lua` | helper `defaultSacrificeGEProperties(id, rewardGood, rewardCount, uiName)` | 31 good exchanges | `GE_fish` (Bavarians): water 8 + stone 3 → 3 fish; duration 20; regeneration 1800; not abortable |
| `…\sacrifices_campaign.lua` | as above, `sf_setForCampaign` | 10 campaign definitions | `olympicFlame`: halberd 10 + coin 10, `Effect_NoEffect`, duration and regeneration 200000000, not abortable |
| `…\tribes.lua` | `tp_addAllowedSacrifice` (22 calls), `tp_addSacrifice` (70 calls) | default sacrifice lists of a tribe | |
| `…\buildings.lua` | `bp_setWorkingMode(b, BuildingWorkingMode_Sacrifice)` (= 9), `bp_setGoods(b, sacrificeGood, 1)` (`sacrificeGoodOlympicFlame` for the olympic flame), `bp_setConstructionTime` | sacrifice buildings | `sacrificeOlympicFlame`: construction time -1 (automatic class), territory range 4 |
| `…\config.lua` | `cfg_setChestDoodadId`, `cfg_setOpenChestDoodadId`, `cfg_setSpawnPointUpdateTime`, `cfg_setSacrificeGoodId`; (`cfg_setChestOwningTime` not called) | chest models, spawn interval, the cost group good | `doodad_chest`, `doodad_openChest`, 1200 (compiled default 600), `sacrificeGood`; owning time compiled default 3000 (S 00555780) |
| `…\spawnpoints.lua` | `sp_create`, `sp_setName`, `sp_setGfxName`, `sp_setParticleName`, `sp_setType`, `sp_addUniqueId` | spawn point types | `animalspawn`: `SpawnType_Animal`, ids deer, rabbit, elk |
| map file | `MapInfo` fields `0x1e3` (chest cells), `0x50b` (sacrifices per tribe); section `Logic SpawnSystem` | chest candidates, offer lists, spawn points | 12 chest cells in the sample of map-format.md |
| `data\game\scripts\mapTools\quests.lua`, `questTargets.lua` | Lua tables `quests[MAINQUEST = 0]`, `quests[SUBQUEST = 1]`; target functions such as `questTarget_goodsProduced`, `questTarget_sacrificeStarted`, `questTarget_militaryStrength`, `questTarget_regionSize` | quest logic of campaign maps | read through `logic.pl_getProducedGoodCount`, `pl_sacrificeStarted`, `pl_getMilitaryStrength`, `pl_getRegionSize` |
| `data\game\scripts\mapTools\tutorial.lua` | `tutorial_add(name, info)`, `tutorial_show(name)` | tutorial pages | store keys `tutorialShowed<n>` |
| `data\game\ui\layout\menuStatistics.xml`, `mapSymbols.xml` | statistics panel layout; minimap symbol type 5 `Chest`, lifetime 100 | presentation | ingame-ui.md §6 |
| localisation | the text keys of §3.6.2, `!VictoryCond_<n>`, `<tutorial key>`, `<tutorial key>_desc` | texts | |

Compiled constants `[known]`: 40 quest slots; 8 player records; modifier arrays of 15 entries; one-shot
threshold test `type > 15`; statistics period 600 ticks, phases 0..4, cap 960; productivity start 0.5, step
0.25, cap 1.0, decay 0.05; message lifetime 600.0; refresh distance `< 1`; "found resource" refresh distance 7;
reveal-map radius 1000; resource cap 7 per cell; chest generator constructor seed `0x5432ace0` (replaced by the
`GameSeed` before the first draw).

---

## 7. Save and load

Stream primitives, section headers and the order of the sections are specified in save-format.md §3; versions
are the ones this build writes. All integers are little-endian 32-bit unless stated; "ref" is a stored
`NLogic::Reference` (its own record), "unique" a stored `NLogic::Unique`, "cell" a stored `MapPos`.

**Quests** — in the logic part, after the game script store, read only when the logic section version is > 2
(`GameFile_LoadLogic` S 005a9db0) `[known]` S 00535ef0, S 00535f40, S 00536000, S 00536090:

```
"Logic Quests" v3:  bool initialized; i32 count (= 40); count x quest
"Logic Quest"  v5:  i32 kind; string id; bool finished; bool failed; cell markerPos; string text;
                    bool visible; u32 startTick; u32 textChangedTick
```

Loader gates: `Logic Quests` v0 forces `initialized = true`; count is 5 for v < 2, 10 for v2, read for v >= 3
(not checked against 40). `Logic Quest`: `failed` from v1, `markerPos` from v2, `text` from v3, `visible` and
`startTick` from v4, `textChangedTick` from v5 (older: the current tick). The loader does not clear slots it
does not read.

**Sacrifices** — in the logic part, read only when the logic section version is > 4 `[known]` S 0065f500,
S 0065f650, S 00662b40, S 00662ba0:

```
"Sacrifice System" v4:        bool initialized; 8 x player data
"Sacrifices Player Data" v4:  u32 count; count x { i32 ownerPlayerIndex; i32 definitionId; sacrifice }
                              regenerations; research; dependencies; free tickets
"Sacrifice Sacrifice" v2:     unique; u32 startTick; ref building; u32 bitCount; bitCount x bool fired;
                              i32 targetPlayer
"Sacrifice DataRegenerations" v1:  u32 count; count x { i32 definitionId; u32 startTick }
"Sacrifice DataResearch" v3:  bool running; if running { u32 startTick; ref building; i32 definitionId }
                              u32 count; count x i32 researchedDefinitionId; i32 playerIndex
"Sacrifice DataDependencies" v2:  bool (+0x0d); i32 count; count x { i32 definitionId; bool }
"Sacrifices Free Tickets" v0: i32 freeTickets
```

- Maps are written in ascending key order. The completion ticks of the `researched` map are **not** saved: only
  the keys are written, and the loader inserts each key with a value it does not read from the file
  `[known]` S 0065fc10, S 0065fcf0. No code reads those ticks back `[inferred]` (the map is only searched by
  key).
- `Load` first resets and re-initialises the table (all records empty, indices bound), then reads. Gates:
  `Sacrifice System` v < 4 is a flat list `{count; count x {i32 player; i32 definitionId; sacrifice}}` followed
  by `RecomputeModifiers`; `Sacrifices Player Data`: regenerations from v2, research and dependencies from v3,
  free tickets from v4; `Sacrifice Sacrifice`: `fired` from v1, `targetPlayer` from v2;
  `Sacrifice DataResearch`: everything but the last int from v2, the last int from v3;
  `Sacrifice DataDependencies`: content from v2.
- `LoadSacrifices` S 00662390 constructs each sacrifice with its owner and definition in "loading" mode (no new
  id, no start tick, no bits, target -1 until read), calls its `Load` and appends it to the record **being
  loaded** (the stored owner index only selects the `Player*`; the flat list of v < 4 appends to the record of
  the stored index); after the last one it calls `RecomputeModifiers` once `[known]`.
- `Sacrifice DataRegenerations` is read without a version test. A running research is read as
  {startTick, building reference, definition id}; the definition pointer is looked up from the id `[known]`.
- Not saved: `paused` and `pauseStartTick`; the modifier tables (rebuilt); `VillageSacrifice.freeTicket` and
  `.targetPlayer`.
- The building side is saved with the building, only for working mode 9 (village-buildings.md §7):
  `"VillageSacrifice"` v0: i32 state; ref active sacrifice; i32 sacrificeDefId (S 00560c30, S 00560df0); then
  the building's research reference (S 0055c470) `[known]`.
- Post-load (`NSacrifice::System::PostLoad` S 0065f540), per player `[known]`: every running sacrifice resolves its
  building reference and raises "sacrifice started" (slot +0xa0) so the scene and HUD rebuild; a running
  research resolves its building and raises "research started" (slot +0xa8). The territory toggle is not
  replayed; the territory grid is saved.

**Statistics** — logic part, always read `[known]` S 00537280, S 005384f0, S 0053ab60, S 0053bad0, S 00537110,
S 00537150:

```
"LogicStatistics" v2:        i32 count; count x { unique buildingId; productivity item }; 8 x player statistics
productivity item (no tag):  i32 (item +0x04); float productivity; i32 idleCounter
"LogicPlayerStatistics" v4:  bool active;
                             8 x { i32 n; n x i32 sample }                       // series 0..7
                             u32 historyCount; historyCount x { i32 id; u32 n; n x i32 }
                             i32 coinCount; i32 killCount; i32 regionSize
```

Gates: `LogicStatistics` v < 2 has one extra int before the count, v1 a second one after the map (both
discarded). `LogicPlayerStatistics`: v < 4 takes `active` from the player entry; v < 3 has 13 legacy int lists
instead of the history map (skipped; the histories are re-seeded if the player is active); `killCount` from v1,
`regionSize` from v2. A player statistics object that is active is cleared before it is read. The productivity
item has no section tag and no version. Its first int (item +0x04, map node +0x24) is 0 in a new item
(S 00538290) and is written by none of `RegisterProductionEvent`, `ResetBuildingProductivity` and
`Statistics::Update`, so a save of this build carries 0 there `[inferred]`; a writer should emit 0. The loader
does not erase the productivity map first: entries are inserted or overwritten by key `[known]` S 005384f0.

**Chests** — logic part, read only when the logic section version is > 5 `[known]` S 0052d200, S 0052d600,
S 00539360, S 005393e0:

```
"Logic ChestSystem" v1:  bool initialized; u32 count; count x chest; bool enabled        // enabled from v1
"Logic Chest" v0:        unique; cell; i32 ownerPlayer; i32 contentKind;
                         kind 1: i32 goodId, i32 goodCount      else: u32 contentValue
                         i32 openProgressTicks
```

`Load` resets the system first when it is initialised. Loading a chest does not set the grid bit; the grid is
saved with the map. Post-load raises "chest added" for every chest in vector order (S 0052d2c0); the scene
picks the open or closed model from `ai::logic::LogicChest::IsOpenable`.

**Spawn points** — in the **map** part (so present in a map file and in a save) `[known]` S 0052cb70,
S 0052cf90, S 00538ea0:

```
"Logic SpawnSystem" v0:  bool initialized; u32 count; count x { i32 spawnTypeId; spawn }
"Logic Spawn" v0:        unique; cell
```

The type id selects the class to construct before the record is read. Post-load raises "spawn point added" for
every spawn (S 0052cd70).

**Messages** are saved with the player (players-victory.md §7, item 7); letters (type 8) are dropped on load.
**Lock maps** (the sacrifice locks and the offer additions) are not saved; scripts set them again in `onLoaded`
(players-victory.md §3.10). **Tutorial pages** are not saved; the script replays them (§3.7).

---

## 8. Determinism notes

| System | Simulation state? | Uses `LogicRandom`? | In the checksum? |
|---|---|---|---|
| Quests | flags decide victory mode 5 | no | no |
| Sacrifice system | yes: modifier tables, one-shot effects, cool-downs, research | no | no; of a working-mode-9 building the checksum takes `state`, the active-sacrifice reference and the research reference (S 0055c690, S 00560c80), not `sacrificeDefId` |
| Statistics | yes for readers: AI (productivity, strength), scripts; the screen is presentation | no | no |
| Chests | kind 1 adds goods; kind 0 changes nothing in the simulation | no (placement uses a private generator seeded with `GameSeed`) | no |
| Spawn points | yes: animals and ground resources | **yes**: one draw for the type choice of every animal spawn that is not crowded, plus the draw inside the animal's creation (map-resources.md §8) | no (its products are not either; logic-core.md §3.6) |
| Messages | presentation, with one feedback path (below) | no | no |
| Tutorial | presentation only | no | no |

- **Everything here advances on `tickCounter` differences**, compared as unsigned 32-bit values. No frame time
  enters, with one exception: message `timeRemaining` (players-victory.md §8).
- **Local-player dependence.** `q_add`, `q_finish`, `q_failed`, `q_reset` and the victory quest of slot 0 send
  to or test the **local** player, and the scenario predicates are evaluated for the local player only. Quest
  flags are therefore per-machine state in a network match. They do not feed back into the synchronised
  simulation except through what the map script does with `logic.q_isFinished`; shipped scripts with quests are
  campaign maps `[inferred]` from the data (the only scripts including `quests.lua` are under
  `maps\campaignMaps`).
- **Messages feed back in one way**: refresh-or-add looks for an existing message, and messages expire by frame
  time and are pruned only for the local player. The outcome only decides whether a message object is added or
  refreshed; no simulation value depends on it `[inferred]` (the finders' results are used for nothing else in
  the callers read).
- **Cinematic pause** shifts sacrifice start ticks by a tick difference; the cinematic itself is started by a
  script through the local UI (logic-core.md, open question 9). In a network match a pause on one machine only
  would desynchronise the sacrifice system without changing the checksum until an effect differs.
- **Iteration orders that matter**: player index 0..7; within a player the `sacrifices` vector in start order;
  effects in definition order; `regenerations` and `researched` in ascending definition id; chests and spawn
  points in vector order (creation / file order; the debug tool's removal reorders spawns); modifier
  recomputation in the order of §3.2.5 (the own and hostile rules are `max` / `min` and constant stores, so
  the tables do not depend on that order).
- **Float use**: the one-shot progress is a single-precision division of two u32-converted values compared with
  an integer converted to float. With thresholds 0 and 1 the comparison is exact (`elapsed / duration >= 1.0`
  holds exactly when `elapsed >= duration` for values below 2^24; the shipped definitions with longer durations,
  20000000 and 200000000, have only type-0 effects, which are never evaluated). A remake may use the integer
  comparison `elapsed >= threshold * duration` for thresholds 0 and 1.
- **Spawn phase** depends on the unique id assigned when the spawn was placed in the editor, stored in the map
  file. A converter must keep those ids, or animal spawns fire on other ticks and the random stream shifts.
- **`ClaimChest`** is sent by every machine for every opened kind-0 chest `[live, 2026-10-14]` (§3.4.3), so a server
  receives one claim per connected machine for the same chest id.

---

## 9. Notes for a Godot reimplementation

**Reproduce exactly** (synchronised simulation, or visible in saved state):

- the sacrifice building state machine with its four states, both check-code tables in their test order, and the
  order of side effects in `Order`, `Start`, `RemoveSacrifice` and `CancelOrder` (messages before the sacrifice
  exists; cost consumed at the start; cool-down on every removal including abort and destruction; output stock
  must be empty before the building is ready again);
- one-shot timing (`type > 15`, threshold test, effect before expiry in the same step, fire on the start tick
  for command starts), and the exact scope of each one-shot (owner vs target, all harbors, finished ships
  only);
- the modifier recomputation as a full rebuild from the list of running sacrifices, in the stated order;
- the per-tick order of step 17 and the pause rule (sacrifices shifted, cool-downs and research not);
- the statistics schedule (phases, 600-tick period, cap 960, cumulative histories, the 0.5 / 0.25 / 0.05
  productivity rule): the AI and campaign scripts read these values;
- chest opening (reset on any owner change, 3000 ticks, never removed, kind-1 goods into the castle's output
  stock) and the network placement of players-victory.md §3.4;
- the spawn trigger formula with the 64-bit id as phase, and the single random draw of an animal spawn.

**Maps onto engine features:**

- Quests: a plain array of 40 records in the simulation state plus signals for the UI. The quest logic stays in
  the map's Lua scripts (or their translation); keep the `logic.q_*` semantics, including "no result" returns.
- Messages: a per-player queue with an event bus to the HUD. Drive lifetime from simulation ticks or from the
  HUD alone; do not let message existence influence anything but refresh-or-add.
- Statistics screen: a `Control` reading the per-player arrays; the eight series and the histories are small
  enough to keep as `PackedInt32Array`.
- Sacrifice presentation (building effect movies, buff effects on settlers and buildings, the "sacrifice
  started" overlay, the sacrifice bar): listeners on "started / removed / research started / research ended /
  ordered / order ended / effect applied" signals, one per callback slot +0xa0..+0xc4.
- Chest and spawn markers: scene nodes created on "added" and swapped on "opened".
- Tutorial: a HUD panel fed by `menu.addTutorialPage`.

**May be dropped without changing play:** the free-ticket path and the dependency map (unreachable, §3.2.3),
effect type 1000 (no case), the `tp_addSacrifice` list if the open question of §3.2.1 confirms it has no reader.
Keep their fields if original save games are to be read.

**A converter has to output:**

| Source | Output |
|---|---|
| `sacrifices*.lua` (after running the property scripts) | one table of definitions (JSON or a Godot `Resource`): id, name, gfx names, duration, costs, effects `{type, arg1, arg2, threshold}`, target, abortable, category, research duration, regeneration delay, campaign flag |
| `spawnpoints.lua`, `config.lua` | spawn point types (ids, type, range, rate, animal ids, model and particle names); the four config values of §6 |
| `tribes.lua` | the allowed sacrifice list per tribe (default for maps without their own list) |
| each map file | sacrifice ids per tribe, chest candidate cells, start positions, and the spawn points **with their 64-bit unique ids and cells** |
| localisation | the message, quest and tutorial text keys |
| `mapTools\*.lua`, map scripts | kept as scripts; they are the quest and tutorial logic |

A remake that wants desync detection for these systems can add them to its checksum (running sacrifices with
start tick and target, cool-downs, research, chests with owner and progress); the original leaves them out
(logic-core.md §3.6).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.2.1): nothing reads `TribeProperty +0x50` (only `AddSacrifice` S 00556400 and the constructor touch it), and nothing fills a new map's `MapInfo +0x204`: only `Load` / `ResetSacrificesFromTribes` and the copy `MapInfo::Assign` write it, so a map never loaded from a file has an empty list | — |
| 2 | Answered (§3.2.8): `pl_changePlayer` → `TransferPlayerAssets` S 00529040 → `TransferAllBuildingsOfPlayer` S 0055aac0 removes construction sites and sends every finished building, sacrifice buildings included, through `ConquerBuilding` → `TransferBuildingOwnership`; `ConquerBuilding` carries the input and output stocks, one worker and the present soldiers per level into the new building | — |
| 3 | Answered (§3.4): a kind-0 chest's `ClaimChestResult` has no effect inside the match beyond the log line; the observer lists `RefereeServerConnection +0x38 / +0x44` have no subscriber | static: the list argument of every `ObserverList::Subscribe` S 00458860 call |
| 4 | Answered (§3.2.7, effect 1001): the building's own worker carries the output stock to the building's flag, one plain ware per walk (`BringGoodOut`, lowest good id first); `ChooseNextWork` tests the stock first and, for working mode 9, has nothing else to start, so the test repeats every tick. State 0 ends on the first building update with an empty output stock (total units 0). From the flag the wares are free packages. The four sacrifice building types share the rule (mode 9, a worker, no `depot` flag) | static: S 0065d660, S 0065cc40, S 0077c510, S 0055b120, S 0055b1b0, S 0065d7f0, S 00561940; `buildings.lua` |
| 5 | `[TODO]` Which player the two letter senders address: both pass the index of the player entry the game screen holds (`menu.createLetter` S 005da720 reads it at active screen +0xfff4; `nMenu::Game::ShowCommMessageAsLetter` S 005eb120 through its own screen pointer), while the autosave notice S 0078b040 uses `ai::player::PlayerTable::FindLocalPlayer` `[known]`. Not established: that the screen's player is always the local player | static: the writer of the game screen's player pointer (+0xfff4) |
| 6 | `[TODO]` Whether a cinematic, and with it the sacrifice pause, can run in a network match | logic-core.md open question 9 |
| 7 | Answered: effect 1003 sets every soldier settler of the owner to full life points and, for every occupied building of the owner in the casern list, empties the map of remembered life points (`SettlerSpawn +0x10`). A stocked soldier that leaves afterwards finds no remembered value and keeps the full value it is created with (village-buildings.md §3.11) | static: S 00660270, S 00564c40, S 00564c90, S 00564d90 |
---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| **Quests** | | |
| 00536200 / 005363f0 | `NLogic::Quests::ctor` / `Reset` | 40 slots; all unused |
| 00536430 / 00536330 | `Quests::SetQuest` / `Quest::Init` | fill a slot |
| 00536310 / 00536390 | `Quests::ClearQuestSlot` / `Quest::SetText` | free a slot; progress text |
| 0052da20 / 0052da60 | `ai::game::GameQuery::AreAllMainQuestsFinished` / `IsAnyMainQuestFailed` | scenario predicates |
| 0053a8b0 / 0053a730 / 0053a750 | `VictoryCond_ActivateQuest` / `SetQuestFinished` / `SetQuestFailed` | victory quest in slot 0 |
| 00535d70 | `VictoryCond_Update` | slot 0 activation, eliminations, progress, declaration, mode 5 scenario test |
| 005b1670, 005b1850, 005b1980, 005b1ab0, 005b1be0 | Lua `q_add`, `q_finish`, `q_reset`, `q_failed`, `q_updateInfo` | bindings with messages |
| 005af580..005af790 | Lua `q_remove`, `q_hide`, `q_isVisible`, `q_isFailed`, `q_isFinished`, `q_isValid` | bindings |
| 00535ef0 / 00535f40, 00536000 / 00536090 | `Quests::Store` / `Load`, `Quest::Store` / `Load` | save |
| **Sacrifice system** | | |
| 0065f9b0 / 0065f4b0 / 0065f4d0 | `NSacrifice::System::ctor` / `NSacrifice::System::Init` / `NSacrifice::System::Reset` | life cycle |
| 0065f4f0 | `NSacrifice::System::Update` | per tick, skipped while paused |
| 00662c50 | `SacrificePlayerData::Update` | sacrifices, cool-downs, research of one player |
| 006621f0 | `SacrificePlayerData::UpdateSacrifices` | one-shots, expiry |
| 00660960 / 00660500 | `ai::logic::Sacrifice::UpdateTimedEffects` / `Sacrifice::ApplyEffect` | one-shot effects |
| 0065ffc0, 00660270, 00660190, 00660100, 00660020, 00660360 | give goods, heal, reveal buildings, reveal harbors, reveal map, sink ships | the six actions |
| 00660050 / 00660070 / 00660090 | `ai::logic::Sacrifice::IsExpired` / `GetRemainingTicks` / `GetProgress` | timing |
| 0065f5a0 / 006624f0 / 00661850 | `System::StartSacrifice` / `SacrificePlayerData::StartSacrifice` / `Sacrifice::ctor` | start |
| 0065f5c0 / 006620a0 | `System::RemoveSacrifice` / `SacrificePlayerData::RemoveSacrifice` | end |
| 00662fb0 / 00661ec0 / 00663630 | `RecomputeModifiers` / `ApplySacrificesToAllPlayers` / `SacrificeModifiers::ApplySacrifice` | modifier rebuild |
| 00661cf0 / 00661d60 | `StartToggleEffects` / `StopToggleEffects` | territory recomputation for effect 14 |
| 00662860 / 00662660 / 00662720 / 006626a0 | regenerations add / contains / remove expired / progress | cool-down |
| 0065fae0 / 0065ff00 / 0065fde0 / 0065fbd0 / 0065fb80 / 0065fb40 | `SacrificeResearch::Start` / `SacrificeResearch::Update` / `ai::logic::SacrificeResearch::Complete` / `ai::logic::SacrificeResearch::Cancel` / `SacrificeResearch::IsAtBuilding` / `ai::logic::SacrificeResearch::GetProgress` | research |
| 0065f550 / 0065f610 / 00661ff0 | `PauseForCinematic` / `ResumeAfterCinematic` / `ShiftStartTicks` | cinematic pause |
| 005fb3e0 / 005faee0 | `nMenu::Cinematic::Update` / `OnHide` | end phases; `quest_cinematicDone`, time scale |
| 006ace00 / 006acf70 / 006ad050 | `S2CG::SacrificeBuilding::StartEffect` / `StartResearchEffect` / `StartWaitForGoodsEffect` | back-dated movies (presentation) |
| 00662040 / 00661f50 / 00662c70 | `HasSacrificeOfDef` / `FindSacrificeById` / `CollectIncomingSacrifices` | queries; incoming = other records in index order, `targetPlayer` = the player |
| 00625200 | `nMenu::SacrificePanel::AssignIncomingSacrifices` | the only caller of `CollectIncomingSacrifices` (antibuff row) |
| 0065f500 / 0065f650 / 0065f540 | `System::Store` / `Load` / `NSacrifice::System::PostLoad` | save |
| 005a9db0 / 005273d0 | `GameFile_LoadLogic` / `NLogic::System::PostLoad` | version gates of the logic part; post-load order (sacrifices, chests, spawn points) |
| 00662b40 / 00662ba0, 00661dd0 / 00662390 | `SacrificePlayerData::Store` / `Load`, `StoreSacrifices` / `LoadSacrifices` | save |
| 00661050 / 00661990, 0065fc10 / 0065fcf0 | `Sacrifice::Store` / `Load`, `SacrificeResearch::Store` / `Load` | save |
| 006625b0 / 006627e0, 006628b0 / 006629e0, 00663670 / 006636a0 | regenerations, dependencies, free tickets `Store` / `Load` | save |
| **Sacrifice building** | | |
| 00560bd0 / 00560cf0 | `VillageSacrifice::ctor` / `ai::village::VillageSacrifice::dtor` | component |
| 00561940 | `ai::village::VillageSacrifice::Update` | state 0 → 2, automatic start |
| 00561240 / 00561380 / 00561410 | `CheckCanOrder` / `CanOrder` / `Order` | ordering |
| 00560f20 / 005615e0 | `CheckCanStart` / `ai::village::VillageSacrifice::Start` | starting |
| 00561870 | `VillageSacrifice::OnExpired` | end of the running sacrifice |
| 00560ed0 / 00561050 / 00560d70 / 00560e80 | `VillageSacrifice::GetAbortOrCancelBlockReason` / `VillageSacrifice::CanAbortOrCancel` / `ai::village::VillageSacrifice::AbortActive` / `ai::village::VillageSacrifice::CancelOrder` | abort and cancel |
| 005610c0 / 00561130 / 00561150 | `GetResearchState` / `CanStartResearch` / `StartResearch` | research gate |
| 005613a0 | `ai::village::VillageSacrifice::GetCostProgress` | delivered fraction |
| 00532960 | building type predicate | automatic class |
| 00560c30 / 00560df0 / 00560c80 | `StoreSavegame` / `Load` / `StoreForChecksum` | save, checksum |
| 0055a210 / 00559db0 / 0055d4e0 | `NVillage::System::TransferBuildingOwnership` / `RemoveBuilding` / `Building::ctor_Transfer` | owner change replaces the building and its sacrifice component |
| 00558170 / 0055a640 | `MarkBuildingsOutsideTerritoryNear` / `NVillage::System::Update` | marking and removal of buildings outside the territory |
| 00637340 | `nMenu::InfoBoxSacrificeSelect::Update` | the offer list |
| 00529720 / 00529760 / 0052bb40 | `MapInfo::GetMapSacrifices` / `HasMapSacrifices` / `ResetSacrificesFromTribes` | sacrifices per tribe |
| 005aeda0, 005aec70, 005b0210, 005b0340, 005b0430, 005b0970, 005b1000 | Lua `vi_orderSacrifice`, `vi_startSacrifice`, `pl_getSacrificeState`, `pl_sacrificeStarted`, `pl_sacrificeStartedOnContinent`, `vi_isSacrificeBuildingAtContinent`, `pl_sendOrderSacrificeMessage` | bindings |
| 005dac60, 005dab40, 005dabd0, 005d9550, 005b2410 | Lua `menu.addSacrifice`, `lockSacrifice`, `unlockSacrifice`, `showSacrificeEffect`; `sacrifice_execute` call | bindings |
| **Statistics** | | |
| 00537a60 / 00537b50 / 00537ba0 | `Statistics::Init` / `Reset` / `Update` | life cycle, schedule (tick tested as a float) |
| 00537230 / 0053af40 | `Statistics::AddGoodAmount` / `PlayerStatistics::AddGoodAmount` | production counts, coin counter |
| 0065d7f0 / 0077a8e0 | worker state 0x24 (working mode 4) / `NMovie::PutDownPackage::Update` | `AddGoodAmount` callers: produced settler (1 per spawn), gatherer's harvest (full count) |
| 00538460 / 00538440 / 005373b0 | `RegisterProductionEvent` / `ResetBuildingProductivity` / `GetProductivity` | building productivity |
| 0053b2c0 / 0053b420 / 0053b8f0 | `PlayerStatistics::AddSample` / `CommitSamplePeriod` / `InitGoodAndJobHistories` | series and histories |
| 0053ad50 / 0053adc0 / 005b0e80 | `GetLatestValue` / `GetGoodHistory` / Lua `pl_getProducedGoodCount` | readers |
| 00533160 | `GetAverageBuildingProductivity` | `(sum / count) × 100`, ascending unique-id order |
| 00537280 / 005384f0, 0053ab60 / 0053bad0 | `Statistics::Store` / `Load`, `PlayerStatistics::Store` / `Load` | save |
| 00537110 / 00537150 | `ProductivityItem::Store` / `Load` | save of one productivity map value |
| **Chests** | | |
| 0052d560 / 00539240 / 0052d110 | `LogicChestSystem::AddChest` / `LogicChest::ctor` / `LogicChest_ClearCellForChest` | creation |
| 0052d660 / 00539520 / 00539210 | `ai::logic::LogicChestSystem::Update` / `LogicChest::UpdateOpening` / `ai::logic::LogicChest::IsOpenable` | opening |
| 005587c0 / 005579a0 | `NVillage::System::AddGoodsToPlayerStoreBuilding` / `FindPlayerBuildingWithDefFlags` | kind-1 content |
| 00782a60 | `Referee_OnChestOpened_SendClaimChest` | kind-0 claim |
| 00775dd0 / 00775ca0 / 00775d60 | `Game_DistributeChestsForNetworkMatch` and its two helpers | network placement |
| 005ad740 / 0052e710 | Lua `map_createChest` / `Map_CanPlaceChestAt` | script and debug creation |
| 0052d090 / 0052d360 | `LogicChestSystem::Enable` / `ai::logic::LogicChestSystem::Reset` | cinematic, teardown |
| 0052d200 / 0052d600 / 0052d2c0, 00539360 / 005393e0 | system `Save` / `Load` / `PostLoad`, chest `Store` / `Load` | save |
| 006819e0 / 00680c80 / 00681aa0 | `S2CG::Scene::OnChestCreated` / `OnChestOpened` / `OnChestRemoved` | models |
| **Spawn points** | | |
| 0052ccc0 | `LogicSpawnSystem::Update` | trigger |
| 00538f40 / 005390e0 | `SpawnAnimal::Spawn` / `SpawnResource::Spawn` | the two actions |
| 0052c990 / 0052cf50 / 0052ce80 | `LogicSpawn_CreateFromProperty` / `AddSpawn` / `RemoveSpawnAt` | creation, removal |
| 00538e10 / 00538e60 | `Spawn::PlaceAt` / `RemoveFromMap` | cell, grid bit, id |
| 0052cae0 / 00539060 / 0052ca70 | `FindAnimalSpawnInRange` / `SpawnAnimal::CanProvideGood` / `FindSpawnAt` | queries |
| 0052cb70 / 0052cf90 / 0052cd70, 00538ea0 / 00538ed0 | system `Save` / `Load` / `PostLoad`, spawn `Store` / `Load` | save |
| **Messages** | | |
| 005c00e0 / 005c0120 / 005c0270 / 005c05b0 | `PlayerMessages_SendToPlayer` / `SendToAllExcept` / `SendOrRefreshToPlayer` / `SendLetterToPlayer` | senders |
| 005c01b0 / 005c01f0, 005c1fd0 / 005c1e40 | `FindNearForPlayer` / `FindNearWithArgForPlayer`, `Messages::FindMatching` / `FindMatchingWithArg` | duplicate search |
| 005c2360 / 005c0740 | `Messages::AddWithPosition` / `Message::ctor_WithPosition` | creation |
| 005c1bb0 / 005c1c10 | `Messages::UpdateTimers` / `RemoveExpired` | lifetime |
| 005c0300 / 005c0390 | `Message::Store` / `Load` | save |
| **Other** | | |
| 00782b60 / 00782bb0 | `nGame::System::BeginCinematic` / `EndCinematic` | sacrifice pause, chest enable |
| 005daa30 | Lua `menu.addTutorialPage` | tutorial page |
| 00527070 / 00527f70 | `NLogic::System::Update` / `InitSubsystems` | tick order, creation |
