# Players, teams, diplomacy and victory conditions

Binary: `sadk_noav.exe`. Addresses are written `S 00xxxxxx`. Tags: `[known]` = read directly in the code or data,
`[inferred]` = one step of reasoning from what is visible, `[TODO]` = open. Nothing in this document has been
observed in the running game.

Related documents (not repeated here): `docs/subsystems.md` (overview), `docs/types.md` (NComm structs),
`docs/NCOMM_GAME_PROTOCOL.md` (pre-game room, slots, team byte, lockstep events), `docs/map-format.md` (MapInfo and
the section-header format), `docs/multiplayer-save.md` (save file and checksum), `docs/lua-surface.md` (Lua
bindings), `docs/data-loading.md` (property scripts, starting goods), `docs/navy-and-military.md` (combat),
`docs/message-catalog.md` (referee messages).

---

## 1. Purpose and scope

This subsystem owns:

- the **player table**: eight player slots plus one neutral entry, each with identity (index, name, colour, kind,
  tribe, team), per-player settings objects and cached counts;
- **teams and hostility**: one integer team per player and a single predicate `IsEnemyOf`; there is no other
  diplomacy state (no treaties, no changing alliances by player command) `[inferred]` (no command handler writes
  `Player.team`; the only writer after match start is the Lua binding `logic.pl_changeTeam`, S 005ad010);
- **match setup → players**: how the three match settings (win condition, start resources, fog of war) and the
  per-slot setup become players, start buildings and starting stock;
- **victory conditions**: elimination, the four win modes, the scenario (quest) mode, winner declaration, and the
  hand-over to the referee server and the user profile;
- **per-player statistics**: eight sampled series, per-good production history, three counters;
- **per-player messages** (in-game notifications) and the periodic "low resources / low soldiers" warnings.

It is not responsible for: combat and capture rules, territory computation, the economy that fills the stocks,
the AI's decisions (`NAI::Player` only reads this subsystem), the pre-game room and the network transport, the
quest system itself, and the statistics screens.

---

## 2. Data model

### 2.1 `ai::player::PlayerTable` (0x874 bytes, member `NLogic::System.playerTable`)

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x000 | `Player[8]` (stride 0xf0) | players | slot i = player index i | `[known]` S 005bdc70, S 005bdd50 |
| +0x780 | `Player` | neutralPlayer | "no owner" entry, see §3.2 | `[known]` S 005be010 |
| +0x870 | u8 | bNeutralInitialized | 0 from the constructor and `Reset` (S 005be190), 1 after `PlayerTable::Init` (S 005be0e0); saved and loaded; no reader found beyond the save code | `[known]` S 005bde00, S 005be1b0 |

The table always has exactly 8 slots; every loop over players is `for i in 0..7` testing `bActive` `[known]`.

### 2.2 `ai::player::Player` (0xf0 bytes, no vtable)

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x00 | i32 | index | 0..7; -1 for an unused entry and for the neutral player | `[known]` S 005bfed0, S 005bea90 |
| +0x04 | i32 | colorIndex | index into the colour table `g_PlayerColors` (S 0087ead8, 0x10 bytes per entry); set to `index` by `Init`, then overwritten with the slot's colour | `[known]` S 005bea90, S 005be2b0, S 005be2c0 |
| +0x08 | i32 | kind | 0 none (neutral / unused), 1 computer, 2 local human, 3 remote human | `[known]` values written at S 004562d0; `[inferred]` names |
| +0x0c | ptr | pGoodPriorities | `NPlayer::GoodPriorities` (0x1c), §2.6 | `[known]` |
| +0x10 | ptr | pGoodArrangement | `NPlayer::GoodArrangement` (0x1c), §2.6 | `[known]` |
| +0x14 | ptr | pMessages | `NPlayer::Messages` (0x28), §2.7 | `[known]` |
| +0x18 | std::string | name | display name | `[known]` S 005beb60 |
| +0x34 | ptr | pStock | `NLogic::Stock`: goods stored in the player's buildings (cache, §3.9) | `[known]` S 005be2f0 |
| +0x38 | map<int, {int,int}> | buildingCounts | per building type id: {count of finished buildings, count of buildings under construction} (cache, §3.9; the split is the test on the two construction floats described there); read as "building count" and "construction count" by the Lua bindings | `[known]` S 00532e70, S 005bf860, S 005bf880 |
| +0x44 | i32 | tribeId | tribe property id (e.g. `0xb0d378a3` Bavarian) | `[known]` |
| +0x48 | ptr | pTribeProperty | resolved from tribeId | `[known]` S 005bea90 |
| +0x4c | ptr | pMilitary | `NPlayer::Military` (0x20), §2.6 | `[known]` |
| +0x50 | u8 | bActive | slot in use | `[known]` |
| +0x54 | i32 | updatePhase | 0..21 staggering counter, §3.9 | `[known]` S 005bf8a0 |
| +0x58 | `NPlayer::ShipNames` | shipNames | embedded; `{vtable, owner, u32 nameIndex}` — next ship name index | `[known]` S 005c1870; `[inferred]` meaning |
| +0x64 | map<int,u8>[4] | lockMaps | four lock maps, 0xc bytes each, §3.10 | `[known]` S 005be970 |
| +0x94 | i32 | team | team number; -1 = no team | `[known]` S 005be280 |
| +0x98 | u8[8] | spotted | spotted[j] = this player has seen player j | `[known]` S 005be2d0 |
| +0xa0 | ptr | pMobileStock | `NLogic::Stock`: goods/units outside buildings (cache, §3.9) | `[known]` S 005be2f0; `[inferred]` meaning |
| +0xa4 | u8[8] | reached | reached[j] = this player's border has touched player j's | `[known]` S 00674ad0 |
| +0xac | i32[8][2] | reachedPos | cell (x,y) of the first border contact with player j; (-1,-1) = none | `[known]` S 005be230 |
| +0xec | i32 | state | **start-resources / difficulty level** 0..3 of the match (same value for every player), §3.4 | `[known]` S 005abb60 passes `desc+0x20`; name `state` is a misnomer |

`ai::player::Player::ctor` S 005bfed0 sets index -1, colour 0, kind 0, name "?", state 2, inactive, and allocates all
sub-objects once for the lifetime of the table `[known]`. The table is a member of `NLogic::System`, which is
constructed for every match (§4), so every match starts with newly constructed players `[known]`.

`g_PlayerColors` S 0087ead8: 8 entries of four floats, read by `ai::player::Player::GetColorEntry` S 005be2c0 as
`table + colorIndex * 0x10`. Bytes in the image, entries 0..7 `[known]`: (0,0,1,1), (1,0,0,1), (0,1,0,1),
(1,1,0,1), (1,1,1,1), (0,0,0,1), (1,0,1,1), (0.5,0.5,0.5,1) — as red, green, blue, alpha `[inferred]`: blue, red,
green, yellow, white, black, magenta, grey. These image values are only the state before start-up: the Lua
binding `menu.setPlayerColor(index, r, g, b)` (S 005d9e00, the only other code that references the table) writes
`table[index] = (r, g, b, 1.0)` without a range check on `index`, and the start-up chunk
`data/game/scripts/menu.cfg` calls it for all eight entries `[known]`. Shipped values, entries 0..7 `[known]`
data: (0.01, 0.1, 0.60), (0.60, 0, 0), (0.20, 0.50, 0), (0.75, 0.46, 0.05), (0.65, 0.65, 0.65),
(0.29, 0.29, 0.29), (0.45, 0, 0.35), (0.20, 0.60, 0.60) — dark blue, dark red, green, ochre, light grey, dark
grey, purple, teal `[inferred]` names. So the colours in a running game are the `menu.cfg` values `[inferred]`
(that the chunk runs before any match: `docs/lua-surface.md`). In a running match the table read exactly these
`menu.cfg` values, and the player on entry 3 showed yellow-orange on screen (entry 4 near white, entry 5 dark
grey), which fits red, green, blue, alpha (the reverse order would make entry 3 blue) `[live, 2026-10-12]`; the
on-screen colours of entries 0, 1 and 6 were not compared.

### 2.3 `ai::game::VictoryConditions` (0x12c bytes, member `NLogic::System.victoryConditions`)

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x00 | `VictoryPlayerEntry[8]` (stride 0x1c) | entries | per-player progress, below | `[known]` S 00535780 |
| +0xe0 | u8[8] | won | 1 = this player is on the winning side | `[known]` S 00535990 |
| +0xe8 | i32[8] | state | 0 playing, 1 eliminated (no headquarters), 2 lost (another side won), 3 quest failed (scenario) | `[known]` S 00535b90, S 00535990, S 00535d70 |
| +0x108 | i32[8] | stateTime | logic tick of the state change (see the indexing quirk in §3.7) | `[known]` |
| +0x128 | u8 | (unnamed) | cleared by the constructor; no other access found | `[known]` S 00535780 |
| +0x129 | u8 | enabled | 1 after `Init`, 0 after `Reset`; no reader found | `[known]` S 005357c0, S 00535840 |

`VictoryPlayerEntry`:

| Offset | Type | Field | Meaning | Tag |
|---|---|---|---|---|
| +0x00 | ptr | player | the `Player` entry of this slot | `[known]` S 0053a710 |
| +0x04 | u8 | active | 1 after `Init`, 0 after `Reset` | `[known]` |
| +0x08 | i32 | mode3Value | this player's coin counter (mode 3) | `[known]` S 0053a770 |
| +0x0c | i32 | mode2Value | this player's latest territory percentage (mode 2) | `[known]` S 0053a770 |
| +0x10 | i32 | enemyCount | number of active enemy players (mode 1) | `[known]` |
| +0x14 | i32 | enemiesWithoutHQ | enemyCount minus the number of enemy headquarters (mode 1) | `[known]` |
| +0x18 | u8 | flag18 | written 0 by init only | `[known]` |

### 2.4 Match settings

**Victory mode** — `NLogic::MapInfo.winCondition` (+0x1c8, i32, enum `EWinCondition`), the value every rule reads
`[known]` S 00535870:

| Value | Name (UI key) | Rule |
|---|---|---|
| 0 | endless (`!LOBBY_MATCHMAKING_WINCONDITION_ENDLESS`) | nobody can win; eliminations are still tracked |
| 1 | destroy all enemies (`..._DESTROYALLENEMIES`) | no enemy owns a headquarters |
| 2 | conquer (`..._CONQUER`) | own side holds at least 75 % of the ownable land |
| 3 | coin (`..._COIN`) | own side has minted at least 100 coins |
| 5 | scenario | the local player wins when all main quests are finished |

Values 0..3 `[known]`: the free-game combo box lists exactly these four strings in this order
(`data/game/ui/layout/menufreegame.xml`, element `WinCondition`, `string0..string3`) and its selected index is
stored unchanged (S 005e8200). Value 5 `[known]`: written only by the Lua binding `logic.victory_setupQuests`
(S 005af7e0; called from `data/game/scripts/mapTools/quests.lua`). Value 4 is used nowhere `[inferred]`. The
value is simulation state: it is stored in `MapInfo` with a save and read by the victory rules; neither set-up
dialog can choose 5.

**The three MapSettings digits** — bytes `NComm::EventGameInformation +0x225/+0x226/+0x227`, sent to the referee
as three ASCII digits `'0'+value` (`GetSettingsDigitString` S 004145f0):

| Digit | Byte | Meaning | Values | Goes to | Tag |
|---|---|---|---|---|---|
| 1 | +0x225 | win condition | 1 destroy all enemies, 2 conquer, 3 coin. The lobby dialog has no "endless" entry (`data/lobby/ui/layout/lobbySetupGameDialog.xml`: three strings) and the host stores popup index + 1 | `GameLoadDescriptor +0x244` → `MapInfo +0x1c8` | `[known]` S 004562d0, S 005ac770; `+1` `[known]` S 00454ad0 (`SetupGameDialog::OnMapSelected` adds 1 to the value of the WinCondition popup before `NComm_Manager::SetGameSettings`) |
| 2 | +0x226 | start resources (shown as the difficulty: German texts `HIGH` = "Unkompliziert", `MEDIUM` = "Leicht", `LOW` = "Normal", and a fourth key `HARDCORE` = "Schwer"; the setup tooltip says "unkompliziert: Bergwerke arbeiten ohne Nahrung", `language/de/lobby_ui.txt`) | 0 high, 1 medium, 2 low (`string0`=`..._STARTRESOURCES_HIGH`, `string1`=`..._MEDIUM`, `string2`=`..._LOW`) | `GameLoadDescriptor +0x20` → every `Player.state` | `[known]` |
| 3 | +0x227 | fog of war | 0 enabled, 1 disabled (`string0`=`..._FOW_ENABLED`, `string1`=`..._FOW_DISABLED`) | `GameLoadDescriptor +0x28` | `[known]` |

`GameLoadDescriptor` (0x248 bytes) fields used here `[known]` S 005a9bb0, S 005abb60:

| Offset | Meaning | Default (`Reset`) |
|---|---|---|
| +0x00 | map type (0, 1, 2, 3, 100, 0x65, 0x66, 0x67) | 0 |
| +0x20 | start resources / campaign difficulty (0..3) | 2 |
| +0x24 | non-zero: shuffle the start positions | 0 |
| +0x28 | fog of war (1 = whole map revealed) | 0 |
| +0x2c | embedded `NLogic::MapInfo` carrying the per-slot setup | reset |
| +0x244 | win condition | 0 |

Per-slot setup inside `MapInfo` (arrays of 8, indexed by player index; layout in `docs/map-format.md` §4.2)
`[known]` S 005abb60: `+0x48` kind (0 closed, 1 computer, 2 local human, 3 remote human), `+0x68` tribe id, `+0x88`
colour, `+0xa8` team, `+0xc8` computer level 0..2, `+0xe8` name (std::string, stride 0x1c).

### 2.5 Statistics

`NLogic::Statistics` (0x38 bytes) `[known]` S 00538380: `+0x04` player table, `+0x08` initialized flag, `+0x0c`
`std::map<Unique, ProductivityItem>` (building productivity, owned by the economy), `+0x18` `PlayerStatistics*[8]`.

`NLogic::PlayerStatistics` (0xb4 bytes) `[known]` S 0053b330:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | bool | active | sampled only while set |
| +0x08 | `vector<int>[8]` (stride 0x10) | series | the eight sampled series below, at most 960 samples each |
| +0x88 | `map<int, vector<int>>` | goodHistory | key = good id or job id of the tribe; one element per 600-tick period |
| +0x98 | i32 | counter98 | coin counter: number of "coin obtained" events (§3.11) |
| +0x9c | i32 | killCount | enemy soldiers killed |
| +0xa0 | ptr | playerEntry | owning `Player` |
| +0xa4 | i32 | regionSize | owned cell count from the last territory sample |
| +0xa8 | list | listeners | UI listeners (`IPlayerStatisticsListener`), not simulation state |

Series index (the "category" of `AddSample`) `[known]` S 00537ba0:

| Index | Content | Source |
|---|---|---|
| 0 | territory share in percent | `ComputeTerritoryShare` S 00532fc0 |
| 1 | number of buildings | `CountBuildingsPerPlayer` S 00532f60 |
| 2 | population: units in four settler lists plus stocked settler goods of the tribe's job list (§3.11) | S 00534110; "population" is `[inferred]` |
| 3 | sum of all goods stored in depot-category buildings | `SumStoredGoodsPerPlayer` S 005334d0 |
| 4 | military strength | `ComputeMilitaryStrengthPerPlayer` S 005335b0 |
| 5 | coin counter (`counter98`) | S 00537ba0 |
| 6 | average building productivity in percent (0..100) | S 005332e0 |
| 7 | kill count | `CommitSamplePeriod` S 0053b420 |

### 2.6 Per-player settings objects (namespace `NPlayer`)

- **`NPlayer::Military`** (0x20) `[known]` S 005c0930: `+0x08` three values, one per distance tier, defaulted from
  `MilitaryConfig::GetDefaultDistanceAllocationFactor(tier)` S 00553f40, which returns compiled constants (tier 0
  → 0.1, tier 1 → 0.3, tier 2 → 1.0, any other → 0.0) and reads no data file; `+0x14` eight bytes, default 0;
  `+0x1c` float, default 0.5. The eight bytes are indexed by another player's index: a set byte makes
  `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` S 005337e0 (called with its diplomacy filter) skip that
  player's buildings `[known]`. The three tier values are the garrison fractions for the zones far / medium /
  near and `+0x1c` is the defence fraction; their rules are in `docs/sim/military.md` §2.3 and the commands that
  change them (0x20013..0x20017) in `docs/sim/game-commands.md`. The object is constructed with the player
  (`Military::ctor` S 005c0ab0 calls `ResetDefaults`), so its values never carry over from an earlier match
  `[known]`.
- **`NPlayer::GoodPriorities`** (0x1c) `[known]` S 005c2bf0, S 005c27c0: `vector<{goodId, rank}>`. Default: every
  good of the tribe (`TribeProperty.goods`) whose `GoodProperty.type != 1` (1 = `Settler` in `Goods.lua`), with rank
  `GoodProperty::GetTransportPriority(tribeId)` (Lua `gp_setTransportPriority`). `MoveRank(from, to)` moves one
  good and shifts the ranks in between by one so the ranks stay a permutation. `GetRankOfGood` returns 0 for a
  good that is not listed.
- **`NPlayer::GoodArrangement`** (0x1c) `[known]` S 005c1370: list of `GoodArrangementGroup` (0x20). Default: for
  every building type of the tribe (in `tp_addBuilding` order) with default weight (`BuildingProperty +0xe4`,
  `bp_setArrangementValue`) >= 0, an entry in production slot 0 and a non-empty input list for it, the building
  is recorded once under the group id (`GoodProperty +0x78`, `gp_setArrangementGoodId`) of each input good; each
  group id consumed by more than one building type becomes a group, and the groups are created in ascending
  group-id order (the collecting container is a `std::map` keyed by the group id). A group holds entries
  `{+0x00 vtable (ArrangementObject), +0x04 float weight, +0x08 float accumulator, +0x0c int buildingTypeId,
  +0x10 u8 used}` (stride 0x14); a new entry has accumulator 0 and `used` 0; weights default to
  `BuildingProperty +0xe4`, minimum 0.001 (S 005c0d40, S 005c38a0). For a player whose `tribeId` is -1 both
  `InitFromTribe` and `GoodPriorities::InitFromGoodTable` create nothing.
  `PickNext` (S 005c30c0): add each entry's weight to its accumulator; choose the first entry in list order with
  `used == 0` and the strictly largest accumulator (start value -1.0); set its accumulator to 0 and return its
  building type id. If all entries are `used`, the first entry is returned and its accumulator is set to 0 as
  well; the accumulators of all entries have still been increased by their weights.
- **`NPlayer::ShipNames`**: one counter, 0 at construction `[known]` S 005c1870. A new ship takes the current
  value as its name number, then the counter is incremented and wraps to 0 when it exceeds 20 (S 005c17f0,
  called from both ship constructors) `[known]`; the name key built from it is in `docs/sim/navy.md` §3.2.

These three settings objects are part of the lockstep checksum (§8), so their values and update rules must match
exactly between machines.

### 2.7 Messages (namespace `NPlayer`)

`NPlayer::Messages` (0x28): owner player at `+0x14`, `vector<Message*>` at `+0x18` (begin pointer `+0x1c`) and a
listener list `[known]` S 005c2250, S 005c2440.
`NPlayer::Message` (0x80) `[known]` S 005c0660, S 005c0300:

| Offset | Type | Field |
|---|---|---|
| +0x08 | Unique | id of the message |
| +0x18 | float | timeRemaining (new messages: 600.0) |
| +0x1c | i32, i32 | position cell; (-1,-1) = none |
| +0x24 | std::string | text (a localisation key such as `!low resources`) |
| +0x40 | std::string | text2 |
| +0x5c | std::string | arg (e.g. a good name) |
| +0x78 | i32 | isRead |
| +0x7c | i32 | msgType 1..8, below; 7 is also the default of a blank message |

Message types by the constant each sender passes `[known]`; the group names are `[inferred]` from the senders:

| msgType | Senders |
|---|---|
| 1 | military: attack started, building captured / destroyed / hit by a catapult, attack failed or averted, building not connected, military building occupied, territory lost, `!low soldiers` |
| 2 | geologist: resource sign placed (S 0077b2f0) |
| 3 | economy: `!low resources`, resource search of a building (S 0055ded0), flag full (S 0064dae0), three job-start warnings (S 00778d50, S 00778e40, S 0077f670) |
| 4 | sacrifices: ordered, started, expired, researched, `!New Sacrifice available` |
| 5 | chests: found, being opened, opened (S 00539520, S 0052d660) |
| 6 | ships: ship building and cargo / expedition messages (S 0065e770, S 0077d6c0, S 005b8470, S 005b8ac0) |
| 7 | quests (`q_add`, `q_finish`, `q_failed`, `q_reset`) and one building notice (S 0077daf0) |
| 8 | letter: `PlayerMessages_SendLetterToPlayer` S 005c05b0 (the `!DEFEAT` notice, Lua `menu.createLetter` S 005da720, `nMenu::Game::ShowCommMessageAsLetter` S 005eb120); also the `!Autosave...` notice of `nGame::Autosave::Update` S 0078b040, sent as an ordinary positional message of type 8 |

---

## 3. Rules and algorithms

### 3.1 Hostility: `Player::IsEnemyOf` S 005be280

```
IsEnemyOf(a, b) = a.index != b.index  AND  (a.team != b.team  OR  a.team == -1)
```

`[known]`. Consequences:

- a player is never its own enemy;
- team -1 makes a player everyone's enemy, including other -1 players;
- the test reads only `a.team` for the -1 case, so it is symmetric whenever teams are equal or different, and
  the asymmetric case cannot arise (`a.team == b.team == -1` gives true both ways) `[inferred]`;
- the neutral player (index -1, team -1) is an enemy of every real player `[inferred]`.

"Allied" everywhere in the code means `!IsEnemyOf`. Uses found: victory rules (§3.6), shared exploration and
spotting (§3.5), attack target validity, catapult targets, sea attack routes, the sacrifice target list, minimap
and selection colouring, the AI (`NAI::Player::IsEnemy` S 00583620, which additionally keeps a per-AI exclusion
list, S 00584840 / S 00583650) `[known]` caller list of S 005be280.

`PlayerTable::HasEnemyOf(p)` S 005bdf30: true if any active slot is an enemy of p; gates sacrifices `[known]`.

### 3.2 The neutral player

`PlayerTable::InitNeutralPlayer` S 005be010 runs `Player::Init` on the entry at `+0x780` with index -1, name
`"Unknown"`, kind 0, tribe = the first entry of the tribe property map, team -1, state 2 `[known]`. It is rebuilt
after every load and never saved. The neutral entry does not occupy a slot, is skipped by every 0..7 loop and is
not updated per tick `[known]` S 005bddd0.

### 3.3 `Player::Init` S 005bea90

Arguments: index, name, kind, tribeId, team, state. In order `[known]`:

1. `index = colorIndex = playerIndex`; name assigned; `kind` stored.
2. `pStock` marked initialised; `buildingCounts` emptied.
3. `updatePhase = playerIndex * 2`.
4. `team` stored.
5. Relation flags cleared (`ai::player::Player::ClearRelationFlags` S 005be230): `spotted[j] = reached[j] = 0`,
   `reachedPos[j] = (-1,-1)` for all j; then, if `index != -1`, `spotted[index] = reached[index] = 1`.
6. `pMobileStock` marked initialised; `state` stored; `bActive = 1`.
7. `tribeId` stored and `pTribeProperty` resolved.
8. `GoodPriorities::InitFromGoodTable`, `GoodArrangement::InitFromTribe` (§2.6).

`Init` does not clear `lockMaps`, `Military`, `Messages` or `ShipNames`; those are cleared by `ai::player::Player::Reset`
S 005bea50 (priorities, arrangement, messages, both stocks, lock maps, `bActive = 0`) when the table is emptied.
`ai::player::Player::Reset` does not reset `Military` or `ShipNames` `[known]`. A later match in the same process does not
inherit them: the whole `NLogic::System`, and with it the player table and these sub-objects, is destroyed when
a match is left and constructed again for the next one (§4) `[known]`. Within one `NLogic::System` (a save
loaded over a running world) `Military` and `ShipNames` are overwritten by the loaded values (§7).

### 3.4 Creating the players of a new match: `Game_CreatePlayersFromDescriptor` S 005abb60

Runs once when a world is built from a map of a "new game" type (0, 1, 2, 100, 0x66; S 005ac770) `[known]`.

1. Copy the map's start position list (`MapInfo.startPositions`). Find the start building type: the first
   building property that has the flags depot, casern and territoryBuilding all set
   (`Properties_FindFirstBuildingWithFlags54F1F5`). In the shipped data only `castle` has all three
   (`buildings.lua`: `bp_setDepot(castle,1)`, `bp_setCasern(castle,true)`, `bp_setTerritoryBuilding(castle,true)`),
   and every tribe lists `castle` (`tribes.lua`: `tp_addBuilding(<tribe>, castle)`) `[known]`. The order of that
   search is described in `docs/sim/properties-data.md`.
2. `ai::player::PlayerTable::RemoveAllPlayers` (notifies the "player removed" observers, then `ai::player::Player::Reset`).
3. Order the start positions. If `desc+0x24 == 0`: keep the map order. Otherwise shuffle: while positions remain,
   `k = LogicRandom_Next() % remaining`, append position k to the result and erase it from the source keeping
   the order of the rest `[known]`. The setter of `desc+0x24` (S 005a9b10) has two callers, the lobby
   `SetupSession` S 004562d0 and `nMenu::Main::StartCampaignMap` S 005df2c0, and both pass 0; `Reset` writes 0
   `[known]`. So the shuffle is never enabled `[known]`: there are two descriptors, the menu's (constructed in
   `nMenu::Game::ctor` S 005ee5d0) and `nGame::System +0x3b0` (constructed in S 00783190), and besides the
   setter and `Reset` the field is written only by `GameLoadDescriptor::Assign` S 00784cd0, which copies the
   menu's descriptor into the system's (sole caller `BuildWorld` S 00784d40). None of the functions that use a
   descriptor (the setter callers, `App_CmdLine_StartNewMap` S 00401350, `FreeGamePanel::SetMap` S 005e8410, the
   combo handler S 005e8200, `nMenu::Game::OnEnter` / `OnLeave`, S 005abb60, S 005ac770) stores to `+0x24`
   of it.
4. Slot setup source: map types 0, 3, 100, 0x67 first copy the descriptor's setup into the world's `MapInfo`
   (`MapInfo::CopySetupFrom`); map types 1 and 0x65 read the setup stored in the map itself; all other
   types read the descriptor `[known]`. Through the caller S 005ac770 only the types 0, 1, 2, 100 and 0x66 reach
   this function (test S 0052c270), so the branches for 3, 0x65 and 0x67 are not taken on that path `[inferred]`.
5. For `i = 0 .. (number of start positions - 1)`: read kind, team, tribe, colour and name of slot i. If
   `kind != 0`: `PlayerTable::CreatePlayer(i, name, kind, tribe, team, state = desc+0x20)` (which calls `Init`
   and notifies the "player created" observers, S 005be100), then `colorIndex = colour`. **A slot beyond the
   number of start positions is never created** `[known]`.
6. `ai::player::PlayerTable::RevealAllies` S 005bdf70: for every ordered pair of distinct active players (a, b) with
   `!IsEnemyOf(a, b)`: `a.spotted[b] = 1` `[known]`.
7. For `i` in the same range, if slot i is active:
   - kind 1 (computer): `NAI::System::ActivatePlayer(player, startPos, level)` with level = computer level + 1
     (0/1/2 → 1/2/3; any other stored value → 1). `ai.lua` creates the profiles with these ids:
     `ai_weak = ai_create("1")`,
     `ai_normal = ai_create("2")`, `ai_strong = ai_create("3")` `[known]` data; that `ActivatePlayer` looks the
     level up as a profile id is described in `docs/sim/ai-player.md`. When the setup came from the descriptor,
     the player is renamed to the localised text of
     the key `"<tribe name>_AI_<computer level>_<i>"` (e.g. `Bavarian_AI_2_3`) `[known]`.
   - place the start building at start position i (`NVillage::System::PlaceBuilding`), then
     `Depot::AddInitialStock` (below), then `Player::RecountStocks`.
   - if `desc+0x28 == 1` (fog of war disabled): `MapModifier::ExploreArea(centre = (W/2, H/2),
     radius = 2 * max(W, H), player)` — the whole map `[known]`.

**Chests of a network match.** Directly after the players are created, still for the new-game types only,
`Game_LoadWorldFromDescriptor` S 005ac770 calls `Game_DistributeChestsForNetworkMatch` S 00775dd0 when the NComm
game seed is not 0 or, with a seed of 0, the game id is not 0 (`EventGameInformation::GetGameSeed` /
`GetGameId`) `[known]`. That function `[known]`:

1. creates a private random generator and seeds it with the game seed (`RandomGenerator::SetSeed`); the logic
   random generator is not used;
2. `total = (number of active players) * (number of chest positions of the map / number of start positions)`,
   the division being an unsigned integer division of the two `MapInfo` list lengths;
3. collects the players' positions (`ChestPlacement_CollectPlayerPositions` S 00775d60: for each active slot
   in index order, the anchor cell (`building+0x20`) of the first building of that player in the village's
   building list, `NVillage::System::FindFirstBuildingOfPlayer` S 00557d40, or the static invalid position when
   the player has none) and copies the map's chest position list as the candidate list. At this point each
   player owns only the start building placed above, so these are the castle cells `[inferred]`;
4. while `total != 0`: for player index 0..7, for each active slot: pick the candidate whose hex distance to
   its nearest player position is the largest (`ChestPlacement_PickFarthestFromPlayers` S 00775ca0: strict
   `>` against a start value of 0, so the first candidate in list order wins a tie, and the first candidate
   is also the result when no candidate has a distance above 0), add a chest there
   (`LogicChestSystem::AddChest(0, position)`), store the next value of the private generator
   (`Rng_ParkMillerNext`) in the chest's field `+0x28` (S 00539200), erase the candidate keeping the order of
   the rest, and `total -= 1`. The player of the inner loop only counts; the chest is not tied to that player.

Every machine must have the same game seed and the same active players for the chests to match. The chest
system itself is described in `docs/sim/logic-core.md` §2.7. `total` is a multiple of the number of active
players, so the loop ends after whole rounds `[inferred]`. The value at chest `+0x28` is the chest's id towards
the referee: when a chest of kind 0 (`chest+0x1c == 0`) is opened, `Referee_OnChestOpened_SendClaimChest`
S 00782a60 sends it as `ChestID` of the referee message ClaimChest (0xDAC) `[known]`. Edge cases `[known]`
(disassembly of S 00775dd0): when the map has fewer chest positions than start positions the quotient is 0, so
`total == 0` and the loop is skipped (`JBE` at S 00775ebc): no chest is placed. There is no guard against a map
without start positions: the divisor is used unchecked (`DIV ECX` at S 00775e5f), so such a map raises the
processor's integer division fault inside this function. The function does not test `total` inside a round
either; that is harmless because `total` is a multiple of the active players.

After this, `MapInfo.winCondition = desc+0x244` for the new-game types and type 0x65 (S 005ac770) `[known]`.

**Starting stock** — `NVillage::Depot::AddInitialStock` S 0055b020 `[known]`:

1. add the map's list for the owner's tribe (`MapInfo::GetInitialGoods`, `MapInfo +0x1f8`; the list is
   normalised per tribe when the map is loaded, `docs/sim/properties-data.md`);
2. if `ai::player::Player::IsStateDefault(owner)` (S 005be350) also add the tribe's bonus list (`TribeProperty.bonusResources`,
   Lua `tp_addBonusResources`).

The function has a second caller: `NVillage::Building::ctor_Place` S 0055d980 calls it for a depot territory
building that is placed while `NLogic::Edit::GetBatchEditing()` is true (`docs/sim/village-buildings.md` §3.2)
`[known]`. Batch editing is off while `Game_CreatePlayersFromDescriptor` places the start buildings, so only
the call above adds the lists, once `[known]`: `Edit::SetBatchEditing` S 00538a60 is slot 0 of the `NLogic::Edit`
vtable S 007e7c28, whose only reference is the constructor S 00538c70 (which starts the flag at 0); every
slot-0 call on the object fetched through the `GameSystem+0x38` getter S 00695ea0 lies in the editor tool
handler `nMenu::Debug::HandleToolClick` S 00604dd0 (S 00604ff0 with 1, S 0060501f with 0, S 00605548 with 1),
and no code reads `GameSystem+0x38` inline to make that call.

| `Player.state` | Human (kind != 1) gets the bonus list | Computer (kind 1) gets the bonus list |
|---|---|---|
| 0 (high) | yes | no |
| 1 (medium) | yes | no |
| 2 (low) | no | no |
| 3 | no | yes |

`[known]` S 005be350. Value 3 cannot be chosen in the free-game or lobby dialogs (three entries). The campaign
passes its difficulty in the same field: `nMenu::Main::HandleButtonClicks` S 005e27c0 starts a campaign map
with the index 0..3 of the marked one of four difficulty buttons (the highest index when several are marked, 2
when none is marked), and the start of a campaign map from `CApplicationEx::Initialize` S 004075d0 passes 0
`[known]`. `nMenu::Main::StartCampaignMap` S 005df2c0 sets, in the descriptor, the kind of all eight slots to
computer and their tribe id to -1, then the kind of slot 0 to local human, and the map type to 1 (or 0x65 when
the campaign map entry's field `+0x74` is 1) `[known]`. With map type 1 the players are created from the setup
stored in the map, not from the descriptor (step 4), so of the descriptor only the difficulty (`+0x20`) reaches
the players; map type 0x65 is not a new-game type (S 0052c270) and does not run the player creation at all
`[inferred]`.

The second reader of `Player.state`, `ai::player::Player::IsStateNotDefault` S 005be330 (computer: `state != 3`; others:
`state != 0`), is consulted by the production code for mines — building types with `BuildingProperty.size`
(`+0x3c`) == 8 (`SizeMine`) and `workingMode` (`+0x80`) == 6 (`Producing`) `[known]` S 00565a70, S 00565bd0,
S 005657c0; constants per `buildings.lua`. With the predicate false a mine files no input requests and does
not need or consume its input goods (food); the full rule, which also involves a sacrifice effect, is in
`docs/sim/village-buildings.md` §3.8. So the mines of a human with start resources "high" (0) and of a computer
player at level 3 work without food `[inferred]`. Net effect `[inferred]`: start resources "high" (0) differs
from "medium" (1) only through this rule, not through the starting stock. The predicate has two more callers,
both presentation: `MenuSelection_ComputeSelectionKind` S 006156a0 and `nMenu::InfoBoxProduction::Update`
S 00635c50 `[known]`.

### 3.5 Spotting and border contact

- `spotted[j]` of player p is set when p (or an ally sharing its view) has explored a cell that is owned
  territory and carries an object in object layer 1: `MapModifier::ExploreArea` S 00674800 reveals the area for
  the exploring player and for every active player that is not its enemy, then walks the hex rings of the area
  and, for each owned cell with an object in layer 1, sets `viewer.spotted[owner] = 1` for every active viewer
  whose exploration grid has that cell `[known]`; that layer 1 holds the buildings is `[inferred]`.
- `reached[j]` and `reachedPos[j]` are set by `MapModifier::DetectTerritoryContacts` S 00674ad0 when territory of
  player p grows around a centre with a radius: on the hex ring at distance radius+1 it counts, per foreign owner
  o with `o.reached[p] == 0`, the ring cells owned by o; halves each count (integer division); walks the ring
  again in the same order and at the cell where owner o's count drops below zero (the middle cell) sets
  `o.reached[p] = 1`, `o.reachedPos[p] = centre`, `p.reached[o] = 1`, `p.reachedPos[o] = that ring cell`, and
  `o.spotted[p] = 1` if it was not set `[known]`. Ring walk: start at centre stepped radius+1 times in direction
  4, then for direction 0..5 step radius+1 times.
- `spotted` and `reached` are in the lockstep checksum; `reachedPos` is not (§8).
- Lua readers: `logic.pl_isPlayerSpotted`, `logic.pl_hasReachedPlayer`, `logic.pl_getReachedPlayerPosition`.

### 3.6 Victory tick: `VictoryCond_Update` S 00535d70

Runs once per logic tick, last of all subsystems (§4). `mode = MapInfo.victoryMode`,
`local = ai::player::PlayerTable::FindLocalPlayer().index`. Steps in order `[known]`:

1. **Victory quest.** If `mode != 5` and `tickCounter == 0`: `Quests::SetQuest(slot 0, "!VictoryCond_<mode>")`
   (S 0053a8b0) — the quest list shows the win condition as quest 0. The counter is -1 in a newly constructed
   `NLogic::System` and is incremented before the subsystems run, so this is the first tick of a new game; it
   does not happen again after loading a save, because the counter is restored from the save (§4).
2. **Elimination.** For `i = 0..7` with `state[i] == 0`: `CheckPlayerEliminated(i)` (§3.6.1).
3. **Progress.** For `i = 0..7` with `state[i] == 0`: `VictoryCond_UpdateProgress(entry i)` (§3.6.2).
4. **Winner search.** Find the lowest `i` in 0..7 with `state[i] == 0`, `won[i] == 0` and
   `IsVictoryReached(i)` (§3.6.3). If found, `DeclareWinner(i)` (§3.7). At most one `DeclareWinner` per tick.
5. **Local outcome.**
   - `mode == 5`: only if `won[local] == 0` and `state[local] == 0`: if every main quest is finished
     (`ai::game::GameQuery::AreAllMainQuestsFinished` S 0052da20: all quest slots of kind 0 have the finished flag; a map
     with no main quest counts as finished) → `DeclareWinner(local)`, then clear the "changed" flag of every
     quest slot whose kind is not 2, and return. Else if any main quest has the failed flag
     (S 0052da60) → `state[local] = 3`.
   - `mode != 5`: write the progress text into quest 0 (§3.6.4). Then, if `IsVictoryReached(local)`: set quest
     0's finished flag (once; S 0053a730). Else if `state[local] != 0`: set quest 0's failed flag (once;
     S 0053a750).

The match is not stopped by the simulation: after a winner is declared the logic keeps ticking, and no code in
this subsystem removes or freezes anything `[inferred]` (none of the functions above calls into the village,
settler or network systems except as listed). What the UI does is in §5.

#### 3.6.1 Elimination: `VictoryConditions::CheckPlayerEliminated` S 00535b90

`NVillage::System::FindPlayerBuildingWithDefFlags(village, i)` S 005579a0 returns the first building in the
village's depot-category list (`NVillage::System +0x20`) whose owner index is i and whose type has depot, casern
and territoryBuilding all set — the castle. If none exists `[known]`:

- `state[i] = 1`, `stateTime[i] = tickCounter`;
- a notice is posted to the local player only if all of these hold: `state[local] != 1`; slot i is active; the
  NComm manager's field `+0x3c8` is not 0 (`NComm_Manager_IsRole0` S 004083d0 false). The field is the network
  mode given to `NComm_Manager::StartUpNetwork` S 0040a9a0: 0 offline, 1 / 2 LAN client / host, 3 / 4 Internet
  client / host (`docs/sim/logic-core.md`), so the test means "a network game" `[inferred]`;
  `player[i].kind == 3` (remote human). The notice is a letter
  (message type 8) with the text `<localised "!DEFEAT">: <name of i> (<i>)`.

Notes:

- **Unused slots become state 1 on the first tick**, because the search finds no building for them and the
  function does not test `bActive` before writing the state `[known]`.
- The search does not look at the building's state. A building enters the category lists when it is placed
  (`NVillage::System::IndexBuilding` S 00559940, called from `PlaceBuilding` S 0055a090, from the ownership
  transfer and after a load) and leaves them only in `RemoveBuilding` S 00559db0 (`UnindexBuilding`
  S 00558f80) `[known]`. So a castle that is still a construction site, and a castle whose destroy countdown is
  running, both keep their owner in the game until the building object is removed `[inferred]`.
- A computer player whose castle is removed stops planning: `NAI::Player::OnBuildingRemoved` S 005836d0 clears
  the AI player's enabled flag when the removed building's type has depot, casern and territoryBuilding set
  `[known]`; details in `docs/sim/ai-player.md`. No AI function reads `VictoryConditions`, so a declared winner
  changes nothing for the computer players that still have a castle `[inferred]`.
- A player who loses the last castle is out even if other buildings, soldiers or harbours remain `[known]`.
- Nothing is done to the eliminated player's remaining buildings, settlers, ships, roads or stock; the player
  stays `bActive`, keeps being updated, and its territory keeps counting in the statistics `[inferred]` (no such
  code in this path).

#### 3.6.2 Progress: `VictoryCond_UpdateProgress` S 0053a770

Only if the entry's player is active `[known]`:

- mode 1: `enemyCount` = number of active slots j with `IsEnemyOf(player[j], this player)`. Then count the
  buildings in the depot-category list whose type has depot + casern + territoryBuilding and whose owner is an
  enemy of this player; `enemiesWithoutHQ = enemyCount - that count`. The count is of buildings, so an enemy
  with two castles makes the value lower than the number of castle-less enemies.
- mode 2: `mode2Value` = latest sample of statistics series 0 of this player (0 if the series is empty).
- mode 3: `mode3Value = PlayerStatistics.counter98`.

#### 3.6.3 `VictoryConditions::IsVictoryReached(i)` S 00535870

False if slot i is inactive `[known]`. Otherwise:

| Mode | True when |
|---|---|
| 1 | `entries[i].enemyCount == entries[i].enemiesWithoutHQ` — no enemy castle exists |
| 2 | sum of `entries[j].mode2Value` over all active j with `!IsEnemyOf(player[j], player[i])` (this includes i itself) `> 74` |
| 3 | sum of `entries[j].mode3Value` over the same set `> 99` |
| other (0, 5) | never |

Remarks `[inferred]`:

- Mode 1 with no enemy at all (`enemyCount == 0`) is true at once. The free-game panel prevents this by enabling
  Start only when at least two sides exist whenever the win condition is not 0 (`CountDistinctTeams` S 005e75e0:
  each team counts once, each team -1 slot counts separately).
- The sums in modes 2 and 3 use the entries of allies whose `state` is no longer 0; those entries are no longer
  refreshed (step 3 skips them) and keep their last value.
- Mode 2 values are sampled once per 600 ticks (§3.11), so the territory condition can only change at those
  ticks. Each percentage is an integer division, so a team's sum can be up to (members - 1) points below the
  true share.

#### 3.6.4 Progress text: `VictoryCond_UpdateQuestText` S 0053a9d0

Quest 0's text for the local player is `"<current>/<goal>"` in decimal `[known]`: mode 1
`enemiesWithoutHQ / enemyCount`; mode 2 `mode2Value / 75`; mode 3 `mode3Value / 100`; any other mode: empty
text. The text shows the local player's own value, not the team sum.

### 3.7 `VictoryConditions::DeclareWinner(w)` S 00535990

In order `[known]`:

1. For `i = 0..7` with slot i active:
   - if `IsEnemyOf(player[i], player[w])`: if `state[i] == 0` then `state[i] = 2`, and
     `stateTime[w] = tickCounter`;
   - else (w itself and its allies): `won[i] = 1` and `stateTime[w] = tickCounter`.
   Quirk: the tick is always written to index **w**, never to index i. An ally of the winner that was already
   eliminated (`state == 1`) still gets `won = 1`.
2. If a lobby manager exists (online match): look up the NComm slot whose player index is w; if found, send the
   referee message `FinishGame` (0xDC0) with GameID, MapGUID, the three MapSettings digits and
   Winner = the avatar id of that single slot (details in `docs/message-catalog.md`). Every client that runs the
   simulation sends it. If w has no NComm slot (a computer player), nothing is sent.
3. If `won[local] == 1`: record the current map as completed in the user profile
   (`UserMapStates::RecordCurrentMapCompleted`, argument = address of `MapInfo.victoryMode`) and save the map
   states file.

`DeclareWinner` is called from exactly two places, both in §3.6 `[known]`.

Observed in free games with two sides of two (`IsEnemyOf` matrix read live) `[live, 2026-10-12]`:

- Mode 1, sides {0 human, 1} and {2, 3}: after `HandleCommand_2002B(2)` the castle was gone and `state[2] = 1`,
  `stateTime[2]` = that tick; players 0 and 1 then showed `enemyCount 2, enemiesWithoutHQ 1` and no winner while
  player 3 kept its castle. Unused slots 4..7 had state 1 from the start. After `HandleCommand_2002B(3)`:
  `state[3] = 1` in that tick and exactly one `DeclareWinner(0)`; then `won = 1,1`, `state[0] = state[1] = 0`,
  `stateTime[0]` = the tick, `stateTime[1] = 0`, and no second call for index 1.
- Mode 1, own side {0, 1} eliminated: one `DeclareWinner(2)` in the tick of the second removal; one tick later
  `state = 1,1,0,0`, `won = 0,0,1,1`, `stateTime = 246,146,246,0`. Eliminated players keep state 1 (they are not
  moved to state 2).
- Mode 1, interleaved sides {0, 2} and {1, 3}: one `DeclareWinner(1)`; `state = 1,0,1,0`, `won = 0,1,0,1`,
  `stateTime = 277,277,177,0`. The logic kept ticking after the local player's elimination and the declaration.
- Mode 0, own side eliminated: `state[1]` and `state[0]` became 1, `won[]` stayed 0 for all, no `DeclareWinner`.

So the named winner is the lowest index of the winning side (not of a team list), the allies get only the `won`
flag, and the tick goes only to index w. Not observed: a network match in which the lower index of the winning
side is on the remote machine, i.e. which avatar each client then puts into `FinishGame` `[TODO]`.

### 3.8 Leaving and giving up

- **Lockstep command 0x2002B "player left game"** — `nGame::System::HandleCommand_2002B(playerIndex)` S 00782910:
  finds that player's castle with the same search as §3.6.1 and removes it
  (`NVillage::System::RemoveBuilding(building, spill = true)`); no castle → nothing `[known]`. The command is
  executed on every machine at the same tick, at the start of that logic tick before any subsystem update
  (`docs/sim/game-commands.md`), and `RemoveBuilding` takes the castle out of the category lists at once
  (§3.6.1). So the victory tick at the end of the same logic tick eliminates the player through the normal
  rule: step 2 sets `state = 1` and, on every machine where that player is a remote human (`kind == 3`, network
  mode not 0) and the local player is not out, posts the `!DEFEAT` letter; step 3 recomputes mode 1's
  `enemiesWithoutHQ` for the others, and step 5 writes the new quest-0 text, or declares the winner in step 4
  when no enemy castle is left `[inferred]` (chain of the `[known]` steps of §3.6). This matches the remaining
  player's `FinishGame` 1.8 s after a give-up `[live, 2026-10-12]`. The command 0x2002B is created only by the
  NComm manager, in three places `[known]`:
  - `NComm_Manager::HandleEvent` S 0040e560, session event 0x3000B "user left": if this machine is the host and
    the network mode (`+0x3c8`) is 1..4 (`NComm_Manager_IsRole1to4` S 004083e0), it creates 0x2002B with the
    leaver's player index and appends it to the outgoing tick package (run at once when the manager's `nMode`
    is 0). In network mode 0 (offline) no 0x2002B is created: leaving a free game through the menu made no
    `HandleCommand_2002B` call `[live, 2026-10-12]`.
  - `NComm_Manager::Process_MainLoop` S 00410f70, reconnect state 2 ("host waiting on clients to join"): once
    all human slots have rejoined or the wait timer (`+4`) has run out, every human slot of the six NComm slots
    that is still not filled is reset and gets a 0x2002B with its player index.
  - `Reconnector_DropRemotePlayers` S 004109b0 (called from `Process_MainLoop`): for the NComm slots 0..4
    whose net id is not 0 and whose owner GUID is not the local one, a 0x2002B with the slot's player index,
    run at once when `nMode` is 0, else appended to the tick package `[known]`. The function does this only
    when the manager state is 3 or 4 and the network handler pointer (`+0x340`) is set; otherwise it returns
    false and creates nothing `[known]`. That this is the path after a failed restart as a client is
    `[inferred]` from the function's name and log texts.
  The session event 0x3000B itself is created in the 0x3000A "user leave" branch of S 0040e560 while a game is
  running (`NComm_Manager::IsInGame`) and appended to the tick package; that branch has no host test of its own
  `[known]`. Outside a running game the same branch resets the leaver's slot, broadcasts the game information
  and sends the 0x3000B directly. More in `docs/sim/game-commands.md`.
- **Leaving through the menu** (`nMenu::Requester`, S 006009b0) `[known]`: a click on "yes" sets the requester
  to "confirmed", and, if an NComm game is running (`NComm_Manager::IsInGame` S 00408440: manager byte `+0x3ac` set and
  state > 3), broadcasts the session event 0x3000A "user leave" (`NComm_SendEventUserLeave` S 00409240), disables
  the buttons and shows "!Finalizing...". While confirmed, each frame: if no NComm game is running or the
  manager byte `+0x3ae` is set, `nMenu::Requester::ExecuteConfirmed` S 006008b0 runs. `NComm_SendEventUserLeave`
  sets byte `+0x3ad = 1`, `+0x3ae = 0` and a timer `+0x3b0 = 3.0`; `+0x3ae` becomes 1 either when this machine
  receives the 0x3000B for its own GUID while `+0x3ad == 1` (S 0040e560), or when the timer, reduced by the
  frame time in `Process_MainLoop` S 00410f70 while `+0x3ad` is set and `+0x3ae` is clear, reaches 0 `[known]`.
  So the leaver goes on after 3 seconds of frame time at the latest. For "back to title / lobby"
  `ExecuteConfirmed` does, in this order `[known]`:
  1. if the `Lobby` object exists and its state (vtable `+0x34`) is 1: `Requester_SendRefereeGiveUpGame`
     S 00600760. With a lobby manager it subscribes the two result callbacks and sends the referee message
     `GiveUpGame` (0xDD4: GameID, MapGUID); the success callback S 006005c0 and the failure callback S 00600690
     do the same when the reported game id equals the session's: unsubscribe, log out of the referee,
     activate the main screen, and, if the `Lobby` object exists with state 1, one call on it (vtable `+0x2c`
     with the result of vtable `+0x30`; `[TODO]` not established: what that call does, read the `Lobby`
     vtable). Without a lobby manager the failure callback is called directly;
  2. only when step 1 did not apply (no `Lobby` object, or its state is not 1; after step 1 the function
     returns): write the autosave if a game is shown and the autosave box is marked, log out of the referee if
     a lobby manager exists, activate the main screen.
  `ExecuteConfirmed` does not change the requester's state, and neither `Requester::Update`,
  `Requester_SendRefereeGiveUpGame` nor `RefereeServerConnection::GiveUpGame` S 00479ab0 has a "sent" latch
  `[known]`. So on the step-1 path the subscription and the 0xDD4 message are repeated on every frame for as
  long as the requester keeps being updated in the confirmed state `[inferred]`; what ends it is the main-screen
  activation in one of the two callbacks. With the stub answering at once, one give-up sent `GiveUpGame` three
  times within 5 ms, each answered `[live, 2026-10-12]`. In a two-player match the remaining player's game then
  declares itself the winner: 1.8 s after the give-up its `FinishGame` named its own avatar `[live, 2026-10-12]`.
  For "exit to desktop" it writes the autosave under the same condition, logs out of the referee and the lobby
  and requests the quit; no `GiveUpGame` is sent on that path.
  The simulation has no "give up" state and the menu path creates no lockstep command: the leaver's castle is
  removed for the remaining players only through 0x3000A → 0x3000B → 0x2002B on the host, which needs a network
  mode other than 0 `[inferred]` (chain of the `[known]` steps above).
- There is no rule that hands a leaver's or loser's assets to anyone. The only asset transfer is the script
  binding in §3.12 `[inferred]`.

### 3.9 Per-tick player update: `ai::player::Player::Update` S 005bf8a0

Called for every active slot, in slot order, at the start of each logic tick (§4) `[known]`:

1. `Messages::UpdateTimers`: every message's `timeRemaining -= Timer_GetFrameDeltaSeconds()` (frame time, not
   tick time — see §8).
2. `updatePhase = (updatePhase < 21) ? updatePhase + 1 : 0` — a 22-tick cycle; `Init` seeds it with
   `index * 2`, so players do the heavy work on different ticks.
3. If `updatePhase == 0`: clear `pStock` and refill it from all of the player's buildings
   (`GameQueryHelper::CollectPlayerBuildingStocks`); clear `pMobileStock` and refill it
   (`GameQueryHelper::CollectPlayerUnitCounts`).
4. If `updatePhase == 1`: for every building property in the property map (map order = ascending id):
   `buildingCounts[id] = CountPlayerBuildingsOfType(player, id)` → {first, second}. The count (S 00532e70) walks
   the village's building list (the vector at `NVillage::System +0x04`) and takes a building of this player
   when its type id
   equals `id`, **or** when its type has territoryBuilding set, the building's field `+0x34` differs from the
   owner's `tribeId`, and its type's `BuildingProperty +0x3c` equals that of type `id` (a territory building of
   another tribe is counted under every type with the same `+0x3c` value). The building goes to `first` when the
   two floats at `building+0x44 → +0x70 / +0x74` are both <= 0, else to `second` `[known]`. Per
   `docs/sim/village-buildings.md` §2.3 / §2.4 and `docs/sim/properties-data.md`: `building+0x44` is the
   `NVillage::Construction` component and the floats are the remaining fractions of its two phases (both start
   at 1.0), so "both <= 0" is a finished building; `building+0x34` is the tribe id of the owner at placement;
   `BuildingProperty +0x3c` is the `size` bit mask (`bp_setSize`).
5. If `updatePhase == 10` and `tickCounter > 50` (unsigned): the two warnings.
   - Required list: for the cost entries of the tribe's construction good (`TribeProperty.constructionGoodId`,
     `gp_addCost` order; Bavarian example: plank, stone) the thresholds are 20 for the first entry, then 10, 0,
     -10, ... (minus 10 per entry); then the tribe's worker tool good (`workerToolGoodId`) with threshold 5.
   - For each required good in that order: if `pStock.count(good) + pMobileStock.count(good) < threshold`: look
     for an existing message of type 3 with text `!low resources`, arg = the good's name and position within
     hex distance < 1 of (-1,-1); if found, reset its timer to 600.0 and notify listeners; else add a new one.
   - Soldiers: sum `pStock.count(soldier good)` over both soldier classes (0, 1) and every level of the tribe
     (`MilitaryConfig::GetSoldierId(tribe, class, level)`); if the sum is `< 5`: same refresh-or-add with a type
     1 message `!low soldiers`, empty arg.

`pStock`, `pMobileStock` and `buildingCounts` are therefore caches up to 22 ticks old. `pStock` is in the
checksum, so the recount tick matters.

A computer player never stays at a tool stock of 0: its `LockSmith` adds a free worker tool
(`docs/sim/ai-player.md`, S 0058d130).

### 3.10 Lock maps

`lockMaps[c]` is a `std::map<int id, u8>`; `IsLocked(c, id)` returns the stored byte or 0 if absent (S 005be970);
`Player::SetLockFlag(c, id)` sets the byte to 1 (S 005bfeb0); `Unlock(c, id)` erases the entry (S 005bf040)
`[known]`. Categories `[known]` from the callers:

| c | Ids | Written by (Lua, `docs/lua-surface.md`) | Read by |
|---|---|---|---|
| 0 | building types | `menu.lockBuilding` / `unlockBuilding` | building placement check, build menu |
| 1 | sacrifices (locked) | `menu.lockSacrifice` / `unlockSacrifice` | sacrifice start / order checks |
| 2 | sacrifices made available | `menu.addSacrifice` | none through `IsLocked`; the sacrifice selection panel walks the keys |
| 3 | job types (queried with soldier types) | `menu.lockJob` / `unlockJob` | soldier training and upgrade |

`IsLocked` has seven callers `[known]`: category 0 from `Village_CheckBuildingPlacement` S 005576e0 and the
build menu S 00634db0; category 1 from `VillageSacrifice::CheckCanStart` S 00560f20 and `CheckCanOrder`
S 00561240; category 3 from `SoldierUpgrade::FindUpgradableSoldier` S 005698a0,
`VillageSoldierTrainingSlot_CanStart` S 00569cb0 and the casern info box S 0063b590. None passes category 2, so
the byte that `menu.addSacrifice` (S 005dac60) sets is written and never tested by this predicate; the binding's
visible effects are a refresh of the info-box tab with key 8 when that is the open one, and, only when its
third argument is true, the `!New Sacrifice available` message (type 4, arg = the sacrifice's name) `[known]`.
The map subscript S 005bf670 has four callers; only the setter S 005bfeb0 addresses the lock maps, the other
three use maps of other objects `[known]`. Map 2 has one reader, and it is UI `[known]`: the sacrifice selection
panel `nMenu::InfoBoxSacrificeSelect::Update` S 00637340 walks the tree directly (`Player +0x7c`, head `+0x80`,
S 0063745d) and offers every key after the map's list (`docs/sim/quests-sacrifices-stats.md` §3.2.1). Besides
that, the lock maps are addressed only as `Player + 0x64 + 12·c` (`IsLocked`, `Unlock`, `SetLockFlag`; no
other instruction computes that address); the only caller passing `c = 2` is `menu.addSacrifice` (to
`SetLockFlag`), the callers of `Unlock` pass 0, 1 and 3, and the only other code on the four maps is
`ai::player::Player::ClearLockMaps` S 005be9e0 (from `Player::Reset`) and the destructor. No simulation code
reads map 2: an id added there changes only what a human player is offered, and `CheckCanOrder` does not test
the offer.

The lock maps are neither saved nor in the checksum (§7, §8). The shipped campaign scripts set their locks again
in the script callback `onLoaded` (e.g. `maps/campaignMaps/C01.lua`: `onLoaded` calls its `lockBuildings()`,
which calls `menu.lockBuilding(player0, casernHalCross)`) `[known]` data.

### 3.11 Statistics

**Events.**

- `Statistics::AddGoodAmount(player, goodId, amount)` S 00537230: if `goodId` equals the tribe's
  `soldierUpgradeGoodId` (the coin: `tp_setSoldierUpgradeGoodId(bavarians, coinBav)`), `counter98 += 1` — one per
  call, regardless of `amount`. Then `goodHistory[goodId].last += amount`. Callers: production delivery, soldier
  training and upgrade completion, worker update, the "give goods" sacrifice, package put-down `[known]`. The
  good must already have a history entry (all goods and jobs of the tribe are seeded).
- Kill: when a soldier's health drops below 1 in `TakeDamage` S 00659260, the attacker's player gets
  `killCount += 1` `[known]`.
- `Statistics::RegisterProductionEvent(building)` S 00538460 (building productivity: first event 0.5, each later
  event +0.25, capped at 1.0) belongs to the economy; listed because series 6 samples it `[known]`.

**Schedule** — `Statistics::Update` S 00537ba0, once per tick while `initialized` `[known]`:

- If `tickCounter == 0`: for every active player slot: `PlayerStatistics.active = 1`, the three counters = 0,
  and `InitGoodAndJobHistories` (one history entry with a single 0 for every good id and every job id of the
  tribe).
- `phase = tickCounter % 600`:

| Phase | Work |
|---|---|
| 0 | Walk the productivity map: drop entries whose building no longer exists; for a building whose two construction floats (`building+0x44 → +0x70 / +0x74`, §3.9) are both <= 0, i.e. a finished building, the entry's counter (node `+0x2c`) +1 and productivity -0.05, set to 0 when the result is below 0. Then sample series 0 = territory percent and set `regionSize` = owned cells. Then `CommitSamplePeriod` for every active player. |
| 1 | series 3 = stored goods sum; series 5 = `counter98` |
| 2 | series 1 = building count |
| 3 | series 2 = population; series 4 = military strength |
| 4 | series 6 = average productivity |
| 5..599 | nothing |

- `AddSample` S 0053b2c0 appends and, if the series then has more than 960 elements, removes the oldest.
- `CommitSamplePeriod` S 0053b420: every good/job history gets a new last element equal to the previous last
  element (the history is cumulative), capped at 960; then `killCount` is appended to series 7, capped at 960.

**Formulas.**

- Territory (S 00532fc0): walk the territory owner grid and the continent cell-index grid together; a cell
  counts for its owner if the owner is not -1, the cell has a continent record, and that record's exclusion
  byte (`+8`) is 0. `percent[p] = cells[p] * 100 / total` (integer division), where `total` is the continent
  system's counter at `+0x38`; if `total == 0` all percentages are 0 `[known]`. The records are 0x30 bytes, in a
  vector whose begin pointer is at `Continents +0x2c`. By the order of the saved fields
  (`docs/map-format.md` §4.11: per continent
  cell count, water flag, id, ...; after the list one `landCellCount`) the byte at `+8` is the continent's
  water flag and `+0x38` is the number of cells of all land continents `[inferred]`. So the share is
  "owned cells on land continents / all land-continent cells"; cells without a continent count on neither
  side.
- Military strength (S 005335b0): for every living soldier, weight `max(1, trunc((level + 1) * 0.8))` added to
  its owner, where level = `MilitaryConfig::FindSoldierLevel`; plus, for every active player, for both soldier
  classes and every level: `stockCount(soldier good) * max(1, trunc((level + 1) * 0.8))`. The factor is the
  double at S 007e7ad8, bytes `00 00 00 a0 99 99 e9 3f` (0.8 as a float widened to double) `[known]`.
  Resulting weights for levels 0..4: 1, 1, 2, 3, 4 `[inferred]` (arithmetic); the shipped `military.lua` defines
  levels 0..2 only (`mi_setSoldierId`), so the weights in use are 1, 1, 2. The living soldiers are taken from
  one settler list (`settlersKind3`) `[known]`.
- Population (S 00534110): number of units per owner in four settler lists (`NSettlers::System +0x34, +0x04,
  +0x14, +0x44`) plus, per active player, the `pStock` count of every id in the tribe's job list (the vector at
  `TribeProperty +0x30`, Lua `tp_addJob`) whose `GoodProperty.type == 1` `[known]`. The tribe's ware list
  (`tp_addGood`) is not walked. Type 1 is the constant `Settler` of `Goods.lua` (`Invalid = -1, Ware = 0,
  Settler = 1, WareGroup = 2, EitherGroup = 3`) `[known]` data. The settler lists are indexed by settler type
  (`docs/sim/settlers-jobs.md` §2.1), which makes the four lists soldiers (+0x34), workers (+0x04),
  constructors (+0x14) and specialists (+0x44); carriers (+0x24) and NPCs (+0x54) are not counted `[inferred]`.
- Average productivity (S 005332e0): for every productivity-map entry whose building still exists,
  `trunc(productivity * 100.0)` is added to the building owner's sum (the productivity float is at node
  `+0x28`, widened to double and multiplied by the double at S 007d8ff0, bytes `00 00 00 00 00 00 59 40` =
  100.0, then `__ftol2_sse`); each sum is then divided by the owner's number of such entries (integer division;
  0 when the owner has none) `[known]` disassembly S 005333d1..005333ec. Truncation is per building, before the
  sum.

Lua readers: `logic.pl_getMilitaryStrength` (latest of series 4), `logic.pl_getRegionSize`,
`logic.pl_getProducedGoodCount`, `logic.pl_getBuildingProductivity`.

### 3.12 Script-driven changes

- `logic.pl_changeTeam(player, team)` → `NLogic::System::SetPlayerTeam` S 00527b30 `[known]`: write
  `Player.team`; for every building of that player in the village's territory-building list (the vector at
  `NVillage::System +0x3c`) whose territory updater is active (`building+0xc4 → byte +8`),
  `ExploreArea(building position, the type's field +0xac as radius, player)` so the new allies share the view;
  buildings of other categories are not walked; then for every active slot j that is
  not an enemy of the player, `player.spotted[j] = 1`. The reverse direction (`j.spotted[player]`) is not set
  here.
- `logic.pl_changePlayer(from, to)` → `NLogic::System::TransferPlayerAssets` S 00529040 `[known]`, inside one
  map-update batch:
  1. remember the positions of `from`'s flags that have no valid building reference or whose building is still
     under construction (one of its two construction floats > 0, §3.9); flags of finished buildings are not
     remembered;
  2. remember the paths of `from`'s roads whose `streetType` (`+0xe4`) is not 2 (2 = water street,
     `docs/sim/streets-transport.md` §2.3);
  3. `NVillage::System::TransferAllBuildingsOfPlayer(from, to)`;
  4. `NSettlers::System::RemoveSettlersOfPlayer(from)`;
  5. remove all of `from`'s flags (last to first);
  6. place the remembered flags for `to` (`Logic_PlaceFlag`), then rebuild the remembered roads for `to`
     (`NNet::System::BuildStreet`) and spawn a carrier directly on each (`NNet::Street::SpawnCarrier`);
  7. `NNavy::System::TransferShipsOfPlayer(from, to)` S 005b44e0: a ship of `from` whose construction component
     (`ship+0x20`) still has remaining work (`+0x48` or `+0x4c` > 0) is deleted; a finished ship is deleted and
     a new ship is created for `to` on the same cell (so it takes a new name number from `to`, §2.6) `[known]`;
     details in `docs/sim/navy.md` §3.2.
  The settlers of `from` are removed, not handed over (step 4) `[known]`.
- `logic.pl_setName`, `logic.pl_hasCastle` (the §3.6.1 search), `logic.pl_getUser` (index of the local player).
- `logic.victory_setupQuests()` sets victory mode 5.

### 3.13 Local player

`ai::player::PlayerTable::FindLocalPlayer` S 005bdda0 returns the first active slot with `kind == 2`; if there is none it
returns slot 0 `[known]`. Because `kind` differs per machine, anything derived from it (the notices in §3.6.1,
the quest flags in §3.6 step 5, the profile write in §3.7) is local presentation and must stay out of the
synchronised state.

---

## 4. Update order

Per logic tick, `NLogic::System::Update` S 00527070, only while the NComm manager is in state 4 and may advance
`[known]`. Steps 1 to 7 are skipped (while the tick time still advances) when the edit object reports batch
editing (`edit->GetBatchEditing()`):

1. `tickCounter += 1`; report the tick to NComm.
2. Street planners (8).
3. **`ai::player::PlayerTable::UpdateAll`** → `ai::player::Player::Update` for active slots 0..7.
4. Village and road net (both inside one map-update batch), then settlers, transport, resources, doodads,
   military, navy.
5. **`Statistics::Update`** (if initialised).
6. AI, sacrifices, spawn system, chests.
7. **`VictoryCond_Update`**.

After the tick: the script's `OnLogicTick` callback (only when the caller's flag allows it and batch editing is
off). The tick interval is the float at `GameConfig +4`, unscaled; what is scaled is the frame time added to the
accumulator: frame seconds × the user profile's float `+0x24` × the system's speed factor, and a product above
5.0 is replaced by one tick interval `[known]` S 00527070. A tick runs for each interval the accumulator has
passed, as long as the NComm manager allows the advance; see `docs/subsystems.md`.

Rates: `ai::player::Player::Update` every tick with a 22-tick stagger; statistics sampling on ticks `600k .. 600k+4`; victory
evaluation every tick.

Per frame only (not simulation): the statistics listeners, message expiry
(`NPlayer::Messages::RemoveExpired` S 005c1c10, polled by the message UI), the victory / defeat screens.

**Tick counter.** `NLogic::System.tickCounter` (`+0x88`) is set to -1 by the constructor S 00528360 and
incremented before the subsystems run, so the first tick of a newly constructed system sees 0 and the
`tickCounter == 0` branches of `Statistics::Update` and `VictoryCond_Update` run on that tick `[known]`. The
counter is written to and read from the save (`NLogic::System::Save` S 005275c0, `Load` S 00527d60, section
version >= 7), so those branches do not run again after a load `[known]`. Neither `Reset` S 00526f80 nor
`InitSubsystems` S 00527f70 writes the counter; the only other writer of -1 is the map-export reset S 005272b0.

**Lifetime of `NLogic::System`.** The object is constructed once per world entry and destroyed when the world
is left `[known]`: `nMenu::Game::OnEnter` S 005eed00 → `nGame::System::BuildWorld` S 00784d40 →
`nGame::System::BuildScene` S 007842e0 → `GameSystem_Construct` S 00528910 (`operator new(0xf4)` + the
constructor, unconditionally; its only caller); `nGame::System::Shutdown` S 007834e0 (callers:
`nMenu::Game::OnLeave` S 005eb030 and `nMenu::System::StartPendingMap` S 005d9fd0) →
`ShutdownAndDestroyGameSystem` S 00781cb0 → `NLogic::System::Shutdown` S 00527c40 and `GameSystem_Destroy`
S 00526f30 (deletes the object, clears the global). So every match, also a second one in the same process,
starts with a tick counter of -1, runs the `tickCounter == 0` branches on its first tick, and has a newly
constructed player table, victory conditions and statistics.

---

## 5. Inputs and outputs

**Inputs.**

| Input | Handler | Effect |
|---|---|---|
| Match setup (descriptor) | S 005abb60 | §3.4 |
| Lockstep command 0x2002B (player index) | S 00782910 | removes that player's castle, §3.8 |
| Lockstep command 0x2001F / 0x20020 (good distribution change / reset) | S 00782000 / S 00781f20, both through `GoodArrangement::FindGroupForGood(sender's arrangement, event +0x10)` S 005c10f0 | 0x2001F: `GoodArrangementGroup::SetEntryWeight(key = event +0x14, float event +0x18)` S 005c0fb0; 0x20020: `GoodArrangementGroup::ResetToDefaults` S 005c0d40 on that group `[known]`; details in the economy document |
| Lockstep commands 0x20022 (reset good priorities) / 0x20016 (reset military defaults) | S 007828d0 → `GoodPriorities::Clear` + `InitFromGoodTable`; S 007823c0 → `Military::ResetDefaults` | restore the sending player's defaults `[known]` (cases of `nGame::System::HandleGameCommand` S 007845a0) |
| Lockstep commands 0x20021 (set good priorities), 0x20013..0x20015 and 0x20017 (military values and flag) | cases of S 007845a0 (`HandleSetGoodPriorities` S 007844b0, `HandleSetMilitaryValue2/1/0`, `HandleToggleMilitaryFlag`) | change the checksummed settings objects of §2.6 `[inferred]` from the handler names; rules in `docs/sim/game-commands.md` |
| Session events 0x3000A / 0x3000B (user leave / user left) | `NComm_Manager::HandleEvent` S 0040e560 | on the host: creates command 0x2002B, §3.8 |
| NComm game seed / game id (network match) | S 005ac770 → S 00775dd0 | seeded chest placement after player creation, §3.4 |
| Lua bindings `logic.pl_*`, `menu.lock*`, `logic.victory_setupQuests` | §3.10, §3.12 | |
| Events from other subsystems | `Statistics::AddGoodAmount`, kill in `TakeDamage`, `ExploreArea`, `DetectTerritoryContacts` | §3.5, §3.11 |

**Outputs.**

| Output | Where | Consumer |
|---|---|---|
| "player created" / "player removed" observer notifications | S 005be100, S 005be150 | renderer and other listeners |
| `IsEnemyOf`, team, spotted / reached | §3.1, §3.5 | military, navy, AI, UI, scripts |
| `pStock`, `pMobileStock`, `buildingCounts` | §3.9 | AI, UI, scripts (`pl_getGoodAmount`, `pl_getMobileGoodAmount`, `pl_getBuildingCount`, `pl_getConstructionCount`) |
| Messages | `PlayerMessages_SendToPlayer` S 005c00e0, `..._SendToAllExcept` S 005c0120, `..._SendOrRefreshToPlayer` S 005c0270, `..._SendLetterToPlayer` S 005c05b0 | message UI through `IMessagesListener` (added / updated / removed) |
| Victory quest 0 (text, finished, failed) | §3.6 | quest UI |
| `state[local] != 0` | read by `nMenu::Game::Update` S 005efea0: when neither the victory nor the report screen is open and screens 5 and 0 are not attached, it opens screen 5 unless screen 8 is attached. Otherwise, when the user profile reports the current map's completion as pending (set by §3.7 step 3) and screen 8 is not attached, it opens screen 3 for map types 1 and 0x65 and screen 0 for all others | `[known]` code. Screen index i is the pointer at `nMenu::System + 0x10 + 4*i` (S 005d97e0) `[known]`; by the slot order of `nMenu::System::Initialize` S 005dda30 the indices are 0 Report, 3 Victory, 5 Defeat, 8 Cinematic `[inferred]`. What the victory, defeat and report screens display is presentation and not read here |
| `state[i] == 0` filter | sacrifice target chooser S 00627210 | players already out are not offered as targets `[known]` |
| Referee `FinishGame` 0xDC0 | §3.7 | lobby / referee server |
| Map completed in the user profile | §3.7 | campaign and map list |
| Statistics series | `PlayerStatistics::GetLatestValue`, `GetGoodHistory`, `Statistics::GetPlayerStatistics` S 005370e0 | statistics screens, scripts, AI: `NAI::ProductionControl::IsStockBelowLimit` S 0058b9e0 reads `regionSize` (limit = `regionSize * 60 / 9216 + 40`) `[known]`; the three other AI functions that fetch the record, `NAI::NeedCreation::Update` S 0058d370, `NAI::WeaponProduction::Update` S 00598950 and `NAI::MilitarySettings::Update` S 00599d60, also read only `regionSize` (`+0xa4`, `FILD` right after each `GetPlayerStatistics` call: S 0058d844, S 00598b70, S 00599dc7) `[known]`. No AI function reads a sampled series, so for the computer players only `regionSize` has to be exact at every tick |

---

## 6. Data-driven parameters

| Source | Key | Feeds | Example |
|---|---|---|---|
| `scripts/properties/defineTribes.lua` | `tp_create("<id>")` | tribe ids | bavarians `b0d378a3`, egyptians `f5016d33`, scots `497ffda3` |
| `scripts/properties/tribes.lua` | `tp_setName` | computer player name key, statistics | `"Bavarian"` |
| | `tp_addBonusResources(tribe, good, n)` | bonus starting stock (§3.4) | `(bavarians, toolBav, 15)`, `(bavarians, plank, 18)` |
| | `tp_addStartResources(tribe, good, n)` | default of the map's initial goods (only for old maps, see `docs/data-loading.md`) | `(bavarians, plank, 30)`, `(bavarians, good_soldierHalberd0, 5)` |
| | `tp_setConstructionGoodId` | low-resources warning list | `constructionResourcesBav` |
| | `tp_setWorkerToolGoodId` | low-resources warning (threshold 5) | `toolBav` |
| | `tp_setSoldierUpgradeGoodId` | coin counter (win mode 3, series 5) | `coinBav` |
| | `tp_addGood`, `tp_addJob`, `tp_addBuilding` | good priorities, history seeding, distribution groups | |
| `scripts/properties/Goods.lua` | `gp_addCost(constructionResources*, good, n)` | order of the warning list | `constructionResourcesBav`: plank, then `stoneBav`; `constructionResources`: plank, `stoneScots`; `constructionResourcesClay`: clay, stone |
| | `gp_setTransportPriority(good, tribe, rank)` | default `GoodPriorities` | `(coinBav, bavarians, 1)`, `(toolBav, bavarians, 12)` |
| | `gp_setType(good, <type>)` | goods of type 1 are excluded from the default priorities and counted in "population" | constants in `Goods.lua`: `Invalid = -1`, `Ware = 0`, `Settler = 1`, `WareGroup = 2`, `EitherGroup = 3`; type 1 is `Settler`, not `WareGroup` `[known]` data |
| `scripts/properties/buildings.lua` | `bp_setDepot`, `bp_setCasern`, `bp_setTerritoryBuilding` | headquarters test (all three) | only `castle` |
| | `bp_setExploreRadius` | re-exploration on team change | `(castle, 12)` |
| `scripts/properties/military.lua` | `mi_setSoldierId(tribe, soldierType, level, good)` | soldier good per tribe / class / level: strength, low-soldiers warning | `(bavarians, soldierType_Sword, 0, good_soldierHalberd0)`; at most levels 0..2, fewer for some classes (egyptians `soldierType_Sword`: level 0 only; scots `soldierType_Bow`: levels 0 and 1). The default distance allocation factors are not in this file: they are compiled constants 0.1 / 0.3 / 1.0 (S 00553f40) `[known]` |
| Map file, `MapInfo` | start positions, per-slot kind / tribe / colour / team / computer level / name, victory mode, initial goods per tribe | §3.4 | `docs/map-format.md` §4.2 |
| `ui/layout/menufreegame.xml`, `lobby/ui/layout/lobbySetupGameDialog.xml` | `StartResources`, `WinCondition`, `FogOfWar` combo boxes | setting values and their order (§2.4) | |
| Localisation (`language/de/briefings.txt`, `ui.txt`) | `!VictoryCond_0` .. `!VictoryCond_3` (in `briefings.txt`, each with a `_desc` key), `!DEFEAT`, `!low resources`, `!low soldiers`, `<Tribe>_AI_<level>_<index>` (in `ui.txt`) | texts | `Bavarian_AI_0_0` .. `Bavarian_AI_2_9`: levels 0..2, indices 0..9 `[known]` data |

Constants compiled into the code `[known]`: 8 player slots; territory goal 75 (test `> 74`); coin goal 100 (test
`> 99`); sampling period 600 ticks; series cap 960; update cycle 22 ticks; low-resources thresholds 20, 10, 0,
... and 5; low-soldiers threshold 5; warning start tick 50; message lifetime 600.0; military weight factor 0.8;
productivity scale 100.0 (series 6); ship name counter range 0..20; chest generator constructor seed
`0x5432ace0` (replaced by the game seed, S 00775dd0).

---

## 7. Save and load

Section headers are the 12-byte tags of `docs/map-format.md` §2.2; the version is the first dword.

**Order in the logic part of a save** (`GameFile_SaveLogic` S 005a9ec0, section `"Game File Logic"` v6)
`[known]`: random generator, **player table**, village, settlers, transport, military, road net, AI,
**statistics**, script, quests, sacrifices, chests. `GameFile_LoadLogic` S 005a9db0 reads the same order with
these version gates `[known]`: random generator only for version >= 1; a navy block between military and road
net only for version < 4; script for version >= 2; quests for version >= 3; sacrifices for version >= 5; chests
for version >= 6. Player table and statistics are read for every version. Of the map types, only 10, 0x65 and
0x6e load the logic part (`GameFile_LoadImpl` S 005aaed0); the others load the map part only.

**`PlayerTable`** — section `"PlayerSystem"` v0 (S 005bde00 / S 005be1b0) `[known]`:

1. u8 `bNeutralInitialized`
2. 8 × { i32 slot index, or -1 for an empty slot; a `Player` record only when not -1 }

Load first removes all players and resets the neutral entry. For each of the 8 records the entry is selected by
the stored index, not by the loop position. The neutral player is rebuilt afterwards.

**`Player`** — section `"PlayerObject"` v1 (S 005be3c0 / S 005be500) `[known]`:

1. u8 bActive
2. string name
3. i32 index, i32 colorIndex, i32 kind, i32 tribeId
4. `GoodPriorities` — `"Good Priorities"` v1: u8 initialized, count, count × `"Good Priority"` v0 {goodId, rank}
5. `GoodArrangement` — `"Good Arrangement"` v4: u8 initialized, count, count × group
   (`"Player GoodArrangementGroup"` v0: u8 initialized, `"Player ArrangementBase"` v0 {count, entries as
   `"Player ArrangementObject"` v0 {float weight, float accumulator, i32 building type id}}, i32 group id). The
   entry's `used` byte (`+0x10`) is not stored (S 005c2e20) `[known]`; after a load it is 0 for every entry
   `[known]`: `ArrangementBase::Load` S 005c3930 fills a temporary entry with weight 0, accumulator 0, type -1
   and `used = 0` (S 005c39a6), reads the three stored fields into it and appends a copy of the whole 0x14 bytes
   (`push_back` S 005c3800). A section version below 4 discards the loaded data and rebuilds the defaults.
6. `Military` — `"Player Military"` v2: 3 × float (the tier values), 8 × u8 (version >= 1), float `+0x1c`
   (version >= 2) (S 005c09d0 / S 005c0a40)
7. `Messages` — `"Messages"` v0: u32 count, count × `"Message"` v2 {float timeRemaining, cell position, string
   text, string text2, i32 msgType, i32 isRead, Unique id, string arg (version >= 1)}. On load, messages of type
   8 (letters) are read and dropped.
8. `pStock` (only when active)
9. i32 updatePhase
10. `ShipNames` — `"Player ShipNames"` v0: u32 nameIndex
11. i32 team
12. 8 × { u8 spotted[i], u8 reached[i], cell reachedPos[i] }
13. `pMobileStock` (written unconditionally, read only when active; only active slots are written at all)
14. i32 state (version >= 1; older saves get 2)

On load `pTribeProperty` is re-resolved from `tribeId` (only when the loaded `bActive` is set). **Not saved**: `buildingCounts` (refilled at phase 1,
up to 22 ticks later), `lockMaps` (re-established by the map script's `onLoaded`, §3.10), the neutral player.

The section versions are the constants of the static initialisers of the section tags `[known]`:
`"PlayerSystem"` 0, `"PlayerObject"` 1, `"Good Priorities"` 1, `"Good Priority"` 0, `"Good Arrangement"` 4,
`"Player GoodArrangementGroup"` 0, `"Player ArrangementBase"` 0, `"Player ArrangementObject"` 0,
`"Player Military"` 2, `"Messages"` 0, `"Message"` 2, `"Player ShipNames"` 0, `"LogicStatistics"` 2,
`"LogicPlayerStatistics"` 4. A `"Message"` section older than version 2 stores its id as a legacy
`NLogic::Unique` that is converted on load (S 005c0390) `[known]`.

The player table, the statistics and the quests have no post-load step: `NLogic::System::PostLoad` S 005273d0
calls the post-load of village, road net, navy, settlers, transport, resources, AI, map info, doodads,
military, map, ambients, sacrifices, chests and spawn system only `[known]`. Everything these three need after
a load is done inside their `Load` functions.

**`Statistics`** — section `"LogicStatistics"` v2 (S 00537280 / S 005384f0): productivity map (count, then key +
item each), then the 8 `PlayerStatistics`. Versions below 2 carry one extra legacy dword before the count and
version 1 one more after the map `[known]`.

**`PlayerStatistics`** — section `"LogicPlayerStatistics"` v4 (S 0053ab60 / S 0053bad0) `[known]`:

1. u8 active (version >= 4; older: taken from the player's `bActive`)
2. 8 × { i32 count, count × i32 } — the series
3. u32 n, n × { i32 id, u32 m, m × i32 } — good / job histories (version >= 3; older saves hold 13 legacy lists
   that are skipped, and the histories are re-seeded if the player is active)
4. i32 counter98; i32 killCount (version >= 1); i32 regionSize (version >= 2)

**`VictoryConditions` is not saved**: it is absent from the save order above and from `NLogic::System::Save`
S 005275c0, which writes only the `MapInfo`, the global logic id, the running flag, three timing floats and the
tick counter `[known]`. None of `state[8]`, `won[8]`, `stateTime[8]` and the eight `VictoryPlayerEntry`
records is stored or restored: the class has no store or load function (its functions are `Init`, `Reset`,
`Update`, `IsVictoryReached`, `DeclareWinner`, `CheckPlayerEliminated` and the quest helpers S 0053a730 ..
S 0053a9d0), and the member `NLogic::System +0xf0` is used only by the system's constructor and destructor,
`InitSubsystems`, `Reset`, `Update` and the two UI readers of §5 `[known: every user in the decompiled
image]`. `VictoryConditions::Init`
S 005357c0 (states, `won` and times to 0) runs from `InitSubsystems` S 00527f70, which `NLogic::System::SetUp`
S 005280a0 calls when the system is constructed for the world entry (`BuildScene` S 007842e0, §4), i.e. before
the file is read `[known]`. The file load itself (`nGame_File_load` S 005ab180 → `GameFile_LoadImpl`
S 005aaed0) calls neither `Init` nor `Reset`; `ResetAndInitSubsystems` S 00528990 is called by
`Game_LoadWorldFromDescriptor` only when the descriptor's load-path selector (`+0x23c`) is 1, the path that
reads no file `[known]`. A save is therefore loaded into victory conditions that are still in their initial
state `[known: live 2026-10-12]` (`nGame_File_load` has one more caller, the debug menu S 00609130, which was not read).
Because the tick counter is restored, the `tickCounter == 0` activation of victory quest
0 is not repeated; the quests themselves are saved. After a load all eight
states are 0 and all `won` flags are 0; the next ticks re-derive eliminations from the castles (posting the
`!DEFEAT` letters again), and if a win condition is already satisfied `DeclareWinner` runs again, sending
`FinishGame` again in an online match. Losers (state 2) and a failed scenario (state 3) are forgotten.

Why the win is declared again: `VictoryCond_Update` S 00535d70 runs `CheckPlayerEliminated` for every slot
whose state is 0, then declares the first slot with state 0 and `won == 0` for which `IsVictoryReached`
holds. After a load every state and `won` flag is 0 while the castles of the eliminated players are still
gone, so the first tick after the load sets their state to 1 again with `stateTime` = that tick (the times
of the original eliminations are lost) and calls `DeclareWinner` for the same winner, which opens the victory
dialog a second time `[known: live 2026-10-12, a save made after a win: second `DeclareWinner(0)` in the first
tick after the load, `stateTime` of both players = that tick]`.

---

## 8. Determinism notes

- **Checksum content.** The lockstep checksum (`nGame::System::ComputeChecksum` S 00784080 →
  `PlayerTable::StoreChecksum` S 005bde70 → `Player::StoreChecksum` S 005be6e0) covers, per slot: slot index or
  -1; then index, colorIndex, tribeId, `GoodPriorities`, `GoodArrangement`, `Military`, `pStock` (if active),
  team, 8 × {spotted, reached}, state `[known]`. Excluded: name, kind, messages, updatePhase, ship names,
  reachedPos, mobile stock, lock maps, building counts, all of `VictoryConditions`, all statistics.
- **Not synchronised but simulation-relevant.** `VictoryConditions.state` feeds back only into UI and local
  messages; the referee message makes a mismatch visible. The coin counter and series 0 decide victory and are
  not in the checksum: a divergence there produces different winners without a checksum alarm `[inferred]`.
  The statistics also feed the computer players: `NAI::ProductionControl::IsStockBelowLimit` S 0058b9e0 and the
  three functions S 0058d370, S 00598950, S 00599d60 read `regionSize` and no other statistics field (§5)
  `[known]`, and the AI state is in the checksum (`NAI::System::StoreBody`, S 00784080), so the 600-tick
  territory sample must be reproduced on the same ticks.
- **`kind` differs per machine** (2 on the owner's machine, 3 elsewhere) and must not influence synchronised
  state. In the code it selects only presentation (§3.13) and, for kind 1, rules that are the same everywhere
  (§3.4) `[inferred]`: of the 26 functions that call `ai::player::PlayerTable::FindLocalPlayer`, the three victory functions
  were read; the others are, by name, UI, camera, cursor, music, renderer, quest and script functions plus
  `MapModifier_InitAfterMapLoad` S 00673000 and `NSettlers::System::PickRandomCinematicTarget` S 006556a0,
  whose use of the local player was not read.
- **Message timers use frame time** (`Timer_GetFrameDeltaSeconds`) inside the logic tick, so message lifetimes
  differ between machines. A message existing or not decides only "refresh or add" in §3.9, and messages are
  not checksummed. Keep messages out of synchronised state.
- **Random generator.** The only use in this subsystem is the start-position shuffle (§3.4 step 3), one
  `LogicRandom_Next()` per position, before any player exists; the shipped game never enables it (§3.4), so
  this subsystem draws nothing from the logic generator. The chest placement of a network match (§3.4)
  uses its own generator seeded with the NComm game seed, one draw per chest, and leaves the logic generator
  untouched. Team and player-index randomisation for the room
  uses C `rand()` on the host and is distributed as data (`docs/NCOMM_GAME_PROTOCOL.md`).
- **Iteration order.** Always slots 0..7 ascending. The winner search takes the lowest index; `PickNext` takes
  the first maximum in list order; property maps iterate by ascending id; the productivity map by `Unique` id.
- **Arithmetic.** Territory percent and average productivity use integer division; military weight truncates
  toward zero after a double multiplication by 0.8 (float-precision constant); distribution weights and
  accumulators are 32-bit floats added in list order — these are in the checksum through `GoodArrangement`, so
  the float operations must be reproduced in single precision and in the same order.
- **Staggering.** `updatePhase = index * 2` at creation; the stock recount happens when the counter wraps to 0.
  A reimplementation must recount on the same ticks because `pStock` is checksummed.

---

## 9. Notes for a reimplementation

Can be simplified:

- The neutral player can be a constant object. `bNeutralInitialized`, `VictoryPlayerEntry.active / flag18`,
  `VictoryConditions.enabled` have no readers `[inferred]` (none in the decompiled code besides the save of
  `bNeutralInitialized`).
- `pStock`, `pMobileStock` and `buildingCounts` can be maintained incrementally if the remake does not need
  checksum compatibility with the original; with compatibility, `pStock` must hold the value of the last
  22-tick recount.
- Messages, statistics listeners and the victory quest text are presentation; drive them from events.
- `stateTime` can be recorded per affected player; `DeclareWinner` writes the winner's index only (the
  elimination check writes the eliminated player's own index).
- Statistics series can be stored in any container; the 960 cap matters only for the graphs.

Must be kept exact for behaviour parity:

- `IsEnemyOf`, including team -1.
- Slot count 8; players are created only for slots below the number of start positions; slot i uses start
  position i.
- The headquarters test (depot + casern + territoryBuilding) for elimination, mode 1 and command 0x2002B; it
  counts a castle from placement to removal, finished or not.
- In a network match: the seeded chest placement of §3.4 (own generator, candidate order, tie rule).
- A leaver's castle is removed by a lockstep command created on the host, never by the leaver's own machine.
- Thresholds `> 74` and `> 99`, team sums over non-enemies including already eliminated allies, and the
  600-tick sampling of territory.
- The coin counter counts events, not amounts.
- The evaluation order within the victory tick and "lowest index wins", because simultaneous victories of two
  sides are resolved by it.
- Starting stock table of §3.4.

Must be bit-exact for compatibility with original saves: the record orders and version gates of §7 and the
section-tag format. For original maps: the `MapInfo` per-slot arrays and `victoryMode`.

Probably worth fixing in a remake (deliberate deviations): persist `VictoryConditions`; do not mark unused slots
as eliminated; decide whether an eliminated ally of the winner should count as a winner; tie message lifetime
to ticks.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered from the code (§3.8): 0x2002B runs at the start of a logic tick and the victory tick of the same logic tick eliminates the player; the remaining machines post `!DEFEAT` (the leaver is `kind == 3` there) and mode 1's quest 0 advances in that tick, not the next one | — |
| 2 | Answered (§3.8): leaving an offline match through the menu makes no `HandleCommand_2002B` call, so no castle is removed `[live, 2026-10-12]` | — |
| 3 | Answered for a referee that answers at once (§3.8): three `GiveUpGame` within 5 ms, each answered `[live, 2026-10-12]`. Open: no latch exists in the sending path (§3.8), so the count depends on when the requester stops being updated (whether the main-screen activation in the result callbacks S 006005c0 / S 00600690 does that, and what happens if the referee never answers) | static read of `AppState_ActivateMainScreen` and of the dialog update loop of `nMenu::System`; or a capture of the referee connection while giving up |
| 4 | Answered: with start resources "high" the mines of a human player work without food (`village-buildings.md` §3.8) | static: S 005be330 and its three callers in `NVillage::Production`; `Player.state` set in S 005bea90 |
| 5 | Answered (§2.2): the component order of the colour table at S 0087ead8 is red, green, blue, alpha, and the values in a running match are those of `menu.cfg` `[live, 2026-10-12]` | — |
| 6 | Answered (§3.10): the only reader of lock map 2 outside `IsLocked` is the sacrifice selection panel S 00637340, which walks the tree to build the offer (UI); no simulation code reads it. It is written only by `menu.addSacrifice` (`SetLockFlag(2, id)`) and emptied by `ClearLockMaps` S 005be9e0 and the destructor | — |
| 7 | Answered (§3.4): no code writes `GameLoadDescriptor +0x24` except the setter (both callers pass 0), `Reset` and the copy `Assign` S 00784cd0; the start-position shuffle never runs | — |
| 8 | Answered (§7): after loading a save in which a side had already won, the win is declared again in the first tick and the victory dialog shows again; no victory state is stored. Open: the second `FinishGame` in a lobby match (same code path, not observed online) | static: S 00535d70, S 005357c0, S 005275c0; live 2026-10-12 |
| 9 | `[TODO]` What the report, victory and defeat screens display (§5) | static read of `nMenu::GameEnded` and the three screen classes; presentation only |
| 10 | Answered (§5): the three AI functions read only `PlayerStatistics.regionSize` (`+0xa4`); no AI function reads a sampled series | — |
| 11 | Answered (§7): the `used` byte is 0 for every entry after a load (`ArrangementBase::Load` S 005c3930 appends a temporary entry with `used = 0`) | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 005bdc70 | `ai::player::PlayerTable::ctor` | 8 slots + neutral entry |
| 005bdd50 | `PlayerTable::GetEntry` | slot by index |
| 005bdda0 | `ai::player::PlayerTable::FindLocalPlayer` | first active kind-2 slot, else slot 0 |
| 005bddd0 | `ai::player::PlayerTable::UpdateAll` | per-tick update of active slots |
| 005bdf30 | `PlayerTable::HasEnemyOf` | any active enemy |
| 005bdf70 | `ai::player::PlayerTable::RevealAllies` | allies start as spotted |
| 005be010 | `PlayerTable::InitNeutralPlayer` | neutral entry |
| 005be100 | `PlayerTable::CreatePlayer` | `Init` + "created" notification |
| 005be150 | `ai::player::PlayerTable::RemoveAllPlayers` | "removed" notification + reset |
| 005bde00 / 005be1b0 | `PlayerTable::Store` / `Load` | save |
| 005bde70 | `PlayerTable::StoreChecksum` | lockstep checksum |
| 005bfed0 | `ai::player::Player::ctor` | allocate sub-objects, defaults |
| 005bea90 | `Player::Init` | activate a slot |
| 005bea50 | `ai::player::Player::Reset` | deactivate a slot |
| 005be280 | `Player::IsEnemyOf` | hostility predicate |
| 005be230 | `ai::player::Player::ClearRelationFlags` | spotted / reached reset |
| 005be2d0 | `Player::SetPlayerSpotted` | `spotted[j] = 1` |
| 005be330 / 005be350 | `ai::player::Player::IsStateNotDefault` / `ai::player::Player::IsStateDefault` | start-resources predicates |
| 005bf8a0 | `ai::player::Player::Update` | caches and warnings |
| 005be2f0 | `Player::RecountStocks` | refill both stock caches |
| 005be970 / 005bf040 / 005bfeb0 | `Player::IsLocked` / `Unlock` / `SetLockFlag` | lock maps |
| 005be3c0 / 005be500 / 005be6e0 | `Player::Store` / `Load` / `StoreChecksum` | save and checksum |
| 005abb60 | `Game_CreatePlayersFromDescriptor` | players, castles, starting stock, fog |
| 005ac770 | `Game_LoadWorldFromDescriptor` | calls the above; sets the victory mode |
| 005a9bb0 | `GameLoadDescriptor::Reset` | setting defaults |
| 004562d0 | `SetupGameDialog::SetupSession` | room settings and slots → descriptor |
| 005e8200 | `FreeGamePanel::OnComboSelectionChanged` | free-game settings → descriptor |
| 005e75e0 | `FreeGamePanel::CountDistinctTeams` | "at least two sides" check |
| 0055b020 | `NVillage::Depot::AddInitialStock` | starting stock |
| 005579a0 | `NVillage::System::FindPlayerBuildingWithDefFlags` | find a player's castle |
| 005357c0 / 00535840 | `VictoryConditions::Init` / `VictoryCond_Reset` | set-up and tear-down |
| 00535d70 | `VictoryCond_Update` | victory tick |
| 00535b90 | `VictoryConditions::CheckPlayerEliminated` | elimination |
| 0053a770 | `VictoryCond_UpdateProgress` | per-player progress values |
| 00535870 | `VictoryConditions::IsVictoryReached` | win test per mode |
| 00535990 | `VictoryConditions::DeclareWinner` | winners, losers, referee, profile |
| 0053a8b0 / 0053a9d0 | `VictoryCond_ActivateQuest` / `VictoryCond_UpdateQuestText` | victory quest |
| 0052da20 / 0052da60 | `ai::game::GameQuery::AreAllMainQuestsFinished` / `ai::game::GameQuery::IsAnyMainQuestFailed` | scenario mode |
| 005af7e0 | Lua `logic.victory_setupQuests` | victory mode 5 |
| 00782910 | `nGame::System::HandleCommand_2002B` | player left: remove castle |
| 00600760 | `Requester_SendRefereeGiveUpGame` | menu give-up → referee |
| 00527b30 | `NLogic::System::SetPlayerTeam` | Lua team change |
| 00529040 | `NLogic::System::TransferPlayerAssets` | Lua asset hand-over |
| 00674800 / 00674ad0 | `MapModifier::ExploreArea` / `DetectTerritoryContacts` | spotted / reached |
| 00537a60 / 00537ba0 | `Statistics::Init` / `Update` | statistics set-up and schedule |
| 00537230 | `Statistics::AddGoodAmount` | production history, coin counter |
| 0053b2c0 / 0053b420 | `PlayerStatistics::AddSample` / `CommitSamplePeriod` | series maintenance |
| 0053ad50 / 0053adc0 | `PlayerStatistics::GetLatestValue` / `GetGoodHistory` | readers |
| 00532fc0 / 005335b0 / 00534110 | `GameQueryHelper::ComputeTerritoryShare` / `ComputeMilitaryStrengthPerPlayer` / `CountUnitsAndStockedKind1GoodsPerPlayer` | samplers |
| 0053ab60 / 0053bad0 | `PlayerStatistics::Store` / `Load` | save |
| 005c00e0 / 005c0120 / 005c0270 / 005c05b0 | `PlayerMessages_SendToPlayer` / `SendToAllExcept` / `SendOrRefreshToPlayer` / `SendLetterToPlayer` | notifications |
| 005c1e40 / 005c1fd0 | `Messages::FindMatchingWithArg` / `FindMatching` | de-duplication |
| 005c2bf0 / 005c27c0 | `GoodPriorities::InitFromGoodTable` / `MoveRank` | transport priorities |
| 005c1370 / 005c30c0 | `GoodArrangement::InitFromTribe` / `ArrangementBase::PickNext` | good distribution |
| 005c0930 | `NPlayer::Military::ResetDefaults` | military setting defaults |
| 005c17f0 | `Counter08_IncrementWrap20` | ship name counter step (0..20) |
| 005be2c0 | `ai::player::Player::GetColorEntry` | colour table entry of a player |
| 00775dd0 / 00775ca0 | `Game_DistributeChestsForNetworkMatch` / `ChestPlacement_PickFarthestFromPlayers` | seeded chests of a network match |
| 00528360 / 00528910 / 00526f30 | `NLogic::System::ctor` / `GameSystem_Construct` / `GameSystem_Destroy` | per-match lifetime of the logic system |
| 007842e0 / 007834e0 / 00781cb0 | `nGame::System::BuildScene` / `Shutdown` / `ShutdownAndDestroyGameSystem` | create / destroy the logic system |
| 005273d0 | `NLogic::System::PostLoad` | post-load steps (none for players, statistics, quests) |
| 00559940 / 00558f80 | `NVillage::System::IndexBuilding` / `UnindexBuilding` | category lists used by the castle search |
| 005836d0 | `NAI::Player::OnBuildingRemoved` | computer player disabled when its castle is removed |
| 0040e560 | `NComm_Manager::HandleEvent` | 0x3000A / 0x3000B → command 0x2002B |
| 00410f70 / 004109b0 | `NComm_Manager::Process_MainLoop` / `Reconnector_DropRemotePlayers` | 0x2002B for players that did not rejoin |
| 00409240 / 00408440 | `NComm_SendEventUserLeave` / `NComm_Manager::IsInGame` | menu leave → 0x3000A |
| 006009b0 / 006008b0 | `nMenu::Requester::Update` / `ExecuteConfirmed` | menu leave flow |
| 006005c0 / 00600690 | `nMenu::Requester::OnRefereeGiveUpGameOk` / `OnRefereeGiveUpGameFailed` | give-up result callbacks |
| 0040a9a0 / 004083d0 / 004083e0 | `NComm_Manager::StartUpNetwork` / `NComm_Manager_IsRole0` / `NComm_Manager_IsRole1to4` | network mode `+0x3c8` |
| 00454ad0 | `SetupGameDialog::OnMapSelected` | host: popups → the three setting bytes (win condition + 1) |
| 005df2c0 / 005e27c0 | `nMenu::Main::StartCampaignMap` / `HandleButtonClicks` | campaign difficulty → `desc+0x20` |
| 005a9b10 | `GameLoadDescriptor::SetRandomStartPositions` | start-position shuffle flag setter |
| 005332e0 | `GameQueryHelper::ComputeAvgProductivityPerPlayer` | series 6 sampler |
| 005337e0 | `GameQueryHelper::MinDistanceToEnemyMilitaryBuilding` | reader of the `Military +0x14` flags |
| 005b44e0 | `NNavy::System::TransferShipsOfPlayer` | ships on asset hand-over |
| 005efea0 / 005d97e0 | `nMenu::Game::Update` / `nMenu_System_IsScreenAttached` | defeat / victory / report screen trigger |
| 005d9c80 / 005d9ce0 / 005d9d40 / 005d9da0 | Lua `menu.lockBuilding` / `unlockBuilding` / `lockJob` / `unlockJob` | lock maps 0 and 3 |
| 005dab40 / 005dabd0 / 005dac60 | Lua `menu.lockSacrifice` / `unlockSacrifice` / `addSacrifice` | lock maps 1 and 2 |
| 00527070 | `NLogic::System::Update` | the logic tick and its subsystem order (§4) |
| 005280a0 / 00527f70 / 00528990 | `NLogic::System::SetUp` / `InitSubsystems` / `ResetAndInitSubsystems` | subsystem initialisation, incl. `VictoryConditions::Init` |
| 005275c0 / 00527d60 | `NLogic::System::Save` / `Load` | tick counter and timing in the save |
| 005a9ec0 / 005a9db0 / 005aaed0 | `GameFile_SaveLogic` / `GameFile_LoadLogic` / `GameFile_LoadImpl` | logic part of a save: order and version gates |
| 00784080 | `nGame::System::ComputeChecksum` | lockstep checksum over the subsystems |
| 007845a0 | `nGame::System::HandleGameCommand` | lockstep command dispatch (0x20013..0x20017, 0x2001F..0x20022, 0x2002B) |
| 00782000 / 00781f20 | `nGame::System::HandleCommand_2001F` / `HandleCommand_20020` | set one distribution weight / reset a distribution group |
| 007828d0 / 007823c0 | `nGame::System::HandleResetGoodPriorities` / `HandleResetMilitaryDefaults` | commands 0x20022 / 0x20016 |
| 005370e0 | `NLogic::Statistics::GetPlayerStatistics` | per-player statistics record; callers include four AI functions |
| 005c09d0 / 005c0a40 | `NPlayer::Military::Store` / `Load` | save of the military settings |
| 005c1c10 | `NPlayer::Messages::RemoveExpired` | per-frame message expiry (called by the message UI S 005f86a0) |
| 00479ab0 | `LobbyComm::RefereeServerConnection::GiveUpGame` | builds and sends 0xDD4, no "sent" latch |
