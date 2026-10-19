# Lua runtime: what a reimplementation must reproduce

Tags: **[known]** = read directly at an address (`S 00xxxxxx`, binary `sadk_noav.exe`) or in a named data file;
**[inferred]** = one step of reasoning from what is visible; **[TODO]** = open. Nothing here was observed in the
running game. "Scripts" means the decrypted `.lua` / `.cfg` files of the installed game (`data\game\...`).

## 1. Purpose and scope

The game embeds Lua 5.0.2 and uses it for three jobs: filling the rule database at start-up (the property
scripts), driving campaign missions (map scripts with quests, scripted world changes and cinematics) and a few
presentation lists (camera paths, encyclopaedia pages, menu configuration, editor brushes). This document
specifies the script layer as a **compatibility target**: what a remake's Lua layer has to provide so that the
player's own script files run unchanged and produce the same simulation results.

Not repeated here:

- the list of registered C functions with their addresses, the host object and the loader table:
  [../lua-surface.md](../lua-surface.md) (§1 runtime, §2 loading, §3 function tables, §4 calls into Lua);
- the meaning of each `properties.*` setter and the record layouts: [properties-data.md](properties-data.md);
- the tick loop: [logic-core.md](logic-core.md) §3.1, §4; the save sections: [save-format.md](save-format.md).

This document adds: argument and return conventions, error behaviour, the simulation state each `logic.*` and
`menu.*` function reads or changes, the callbacks and their position in the tick, what persists, and the
determinism rules.

## 2. Data model

### 2.1 Interpreter state

| Object | Meaning | Evidence |
|---|---|---|
| One `lua_State` for the whole process | created at application start, closed at shutdown; never recreated between matches | [known] S 005c8ef0, `../lua-surface.md` §1.2 |
| One global table | every script, in every thread, reads and writes the same globals. Globals set by the property scripts (ids, enum constants) stay visible to menu, map, cutscene and info scripts; globals set by a map script stay set after the match ends | [inferred] Lua 5.0 `lua_newthread` shares the creator's globals; [known] the map scripts use `woodCutter`, `SizeLarge`, `doodad_chest`, ... which only the property scripts define |
| Threads | a script file runs in a coroutine thread of that state (§3.3). `LuaThreadEntry` = { `L`, `waitMode` (1 = waiting), `wakeTime` float seconds, −1.0 = not waiting } | [known] S 005c8c90, S 005c9a10 |
| Map-script thread id | `g_GameScript_ThreadId`; −1 when no world exists | [known] S 005b2720, S 005b1ce0 |
| Map-script path | `g_GameScript_MapScriptPath` (`std::string`); **empty = "no map script"**: every engine callback and `sd_setValue` test its length (S 0087e964) | [known] S 005b20d0, S 005b28b0 |
| Flag S 0088b314 | 1 from `GameScript_InitMapScript` to `GameScript_DestroyMapScript`; gates the button events (§4.4); written to and read from the save (§7) | [known] S 004c44a0, S 005b0f30 |
| Libraries present | base library incl. `coroutine`, `math`; game tables `Default`, `properties`, `menu`, `ui`, `txt` from start-up; `logic`, `gfx` from the first offline world build; `cutscene` from the first cutscene; `editor` from the debug menu. **No** `string`, `table`, `io`, `os`, `debug` | [known] the start-up opener table S 007eb930 holds only `luaopen_base` and `luaopen_math` (S 005c8ef0); `../lua-surface.md` §1.1, §3.1 |

Because library tables are globals of the one state, a table registered "on a thread" stays for the rest of the
process [inferred]: `logic` is still reachable in the menus after a match, and in a network match that follows an
offline one in the same process, although `GameScript_RegisterLuaLibraries` is only called when the session mode
is 0 (offline) [known] S 00784d40, S 004083d0.

### 2.2 Value conversion at the C boundary

Every game binding uses these helpers and no `luaL_check*` (exception: `Default.Wait`), so **no binding raises a
type error** [known]:

| Helper | Rule | Evidence |
|---|---|---|
| `Lua_ToInt(idx)` | `lua_tonumber` then truncation toward zero to int32. A non-number, a missing argument, `nil`, a boolean and a non-numeric string give 0; a numeric string is converted | [known] S 005c9b30 (`__ftol2_sse`); Lua 5.0.2 `lua_tonumber` |
| `Lua_ToFloat(idx)` | `(float)lua_tonumber`: rounded to float32 | [known] S 005c9b10 |
| `Lua_ToBool(idx)` | `lua_toboolean != 0`: only `nil`, `false` and a missing argument are false; **the number 0 is true** | [known] S 005c9b50 |
| `lua_tostring(idx)` | strings; numbers are converted in place (`"%.14g"`); for `nil`/boolean/table it returns NULL and the bindings then run `strlen(NULL)`: an access violation, not a Lua error | [known] e.g. S 005b28b0 has no NULL test; [inferred] crash |
| `Lua_PushInt(v)` | number with the int32 value | [known] S 005c9b70 |
| `Lua_PushFloat(v)` | number with the float32 value widened to double | [known] S 005c9bb0 |
| `Lua_PushBool(v)` | boolean `v == 1` | [known] S 005c9b90 |
| `Lua_IsNumberBool(idx)` | `lua_isnumber`: used for optional arguments | [known] S 005c9ae0 |

Extra arguments are ignored. Positions are passed as two integers `x, y` = map cell column and row
([map-resources.md](map-resources.md) §3.1); a player is the slot index 0..7 of the player table
([players-victory.md](players-victory.md) §2); goods, building types, doodads, deposits, patterns, sacrifices and
AI profiles are the signed 32-bit property ids the `*_create` calls returned ([properties-data.md](properties-data.md)
§2.2).

### 2.3 The "failed guard" return convention

Nearly every `logic.*` function starts with guards and **returns no value** (the script sees `nil`) when a guard
fails; only the success path pushes a result [known: each body below]. The guards, where a function has them:

- player guard: `(unsigned)player < 8` and `PlayerTable entry.bActive != 0` (S 005ac9c0 is the shared form);
- AI guard: `(unsigned)player < 8` and the **computer player's** `NAI::Player.bActive` (+0x10) of slot `player` is
  not 0. It does not test the game player's `bActive` in the player table: a slot whose computer player is inactive
  fails it even when the game player is active [known: the `ai_*` bodies S 005ada40..S 005ae100];
- cell guard: `0 <= x < g_MapWidth` and `0 <= y < g_MapHeight` (S 005ac8f0);
- quest guard: `(unsigned)index < 40` and the slot is in use (`kind != 2`).

Consequence for scripts: a predicate can be `true`, `false` or `nil`. `nil == false` is false in Lua, so
`logic.vi_isBuildingAtPosition(...) == false` is **not** satisfied by a failed guard, and a comparison such as
`logic.pl_getSacrificeState(p, s) >= 1` raises a Lua error when the function returned nothing (§3.4).
Some failed lookups behind a passed guard also push nothing; the tables of §3.6 say so per function. A remake must
return "no value", not `false` or 0, on these paths.

### 2.4 Script data store (`sd_`)

`g_GameScript_ScriptData`: `std::map<std::string, int32>` (S 0088b340..48), ordered by byte-wise string
comparison [known] S 005b28b0, S 005b24d0, S 005b0f30. It is the only script-owned state that is saved (§7).

### 2.5 Quest slots

`NLogic::Quests`: 40 slots of `NLogic::Quest` (0x58 bytes each, first slot at `Quests+8`) [known] S 005b1670
(bound `< 0x28`), S 00536330:

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | int `kind` | 0 = main quest, 1 = sub quest, **2 = slot unused** |
| +0x08 | string `id` | the name given to `q_add`; used as message title and text key |
| +0x24 | bool `finished` | set by `q_finish`, cleared by `q_reset` |
| +0x25 | bool `failed` | set by `q_failed`, cleared by `q_reset` |
| +0x28 | int[2] `markerPos` | cell `x, y` (−1, −1 = none) |
| +0x30 | string `text` | progress text set by `q_updateInfo` |
| +0x4c | bool `visible` | `q_add` argument 6; cleared by `q_hide` |
| +0x50 | u32 `textChangedTime` | tick of the last text change |
| +0x54 | u32 | tick of `q_add` |

Slot 0 is also used by the engine's victory quest unless the victory mode is 5
([players-victory.md](players-victory.md) §3.6); `logic.victory_setupQuests()` selects mode 5.

## 3. Rules and algorithms

### 3.1 Language level a remake's Lua must accept

The scripts are Lua 5.0 source text, compiled at load (`luaL_loadbuffer`); there is no precompiled bytecode
[known: data, S 005c9690]. Lua 5.0 features the shipped scripts rely on, which differ from later versions:

- `for i, _ in t do` (iteration over a table without `pairs`), used once, in `getn` of
  `scripts\mapTools\tools.lua` [known: data]. Lua 5.1 and later fail on it.
- No `string` or `table` library: the scripts build strings only with `..` and compute lengths with their own
  global `getn(t)` (returns `t.n` if it is a number, else the largest positive numeric key) [known: data].
- Number to string conversion by `..` and `lua_tostring` uses `"%.14g"` [known] S 005d0bf0, string S 007ec644.
  Quest progress texts are built this way (`""..count.."/"..data.amount`), and some amounts are fractions
  (`weissBeerAmount*0.34` in `C02.lua`), so the formatting is visible in saved quest text (§8).
- Numbers are C `double`; there is no integer type. `math.mod` exists, the `%` operator does not; the shipped
  scripts use neither, only `math.floor` (once, `C06.lua`) [known: data].
- Standard functions actually called by shipped scripts: `ipairs` (55 calls), `type` (4), `math.floor` (1);
  nothing else from the base, `coroutine` or `math` libraries [known: data search over all 355 `.lua` files and
  `menu.cfg`].
- File names are matched case-insensitively and `/` counts as `\` (the resolver lower-cases the request, §3.2):
  `data.lua` asks for `goods` and `jobs` while the files are `Goods.lua` and `Jobs.lua`; `C02.lua` names
  `C02_13catapult.lua` for the file `C02_13CATAPULT.lua` [known: data, S 006ef8a0].

### 3.2 Running a script file

`LuaScriptHost::RunFile(threadId, path)` S 005c9690 [known]:

1. read the file and decrypt it (`File_ReadAndDecrypt` S 006e7770);
2. `luaL_loadbuffer(L, buffer, size, chunkname = path)`;
3. on success `lua_resume(L, 0)`: the chunk runs as the body of the thread's coroutine;
4. a compile error or a run-time error is passed to `LuaScriptHost_DumpScriptError` S 005c9440, which formats a
   text and discards it. **Nothing is reported and the caller continues.**

`Default.CallScript(path)` S 005cdfb0 is the scripts' only include mechanism: it creates a **new** thread, runs
the file in it as above, destroys the thread and returns nothing (it returns 1 stack value only when no thread
could be created) [known]. Since globals are shared, the included file's globals and functions are available to
the caller afterwards; its locals are not. An error inside the included file stops that file only; the including
script continues after the call [known: no error is propagated]. Including a file twice simply runs it twice.

Paths are virtual `[data]\...` paths. The shipped scripts use `[data]\scripts\...`, `[data]\maps\...` and, in
`quests.lua`, `[data]\game\scripts\mapTools\...` [known: data]. **A script path is resolved by its file name, not
by its directory** (`NBase::gReadFileData` S 006e6d40 → `FileScanHolder::ResolvePath` S 006e3fd0 →
`FileScan::ResolvePath` S 006ef8a0) [known]:

1. `/` becomes `\` and the whole request is lower-cased;
2. the part after the last `\` is looked up in the file index built by the start-up directory scan
   (lower-case file name → list of directories; `../data-loading.md` §1);
3. exactly one directory has a file of that name: that file is opened, whatever directory the request named;
4. several directories have one: `PickCandidateByParentDir` S 006ef680 takes the first candidate (index order)
   whose trailing directory name, lower-cased, occurs in the request; none → no file;
5. no file of that name: the resolved path is empty, the open fails, the buffer stays NULL with size 0 and
   `RunFile` goes on with it ([inferred] an empty chunk: nothing runs and nothing is reported).

No two `.lua` / `.cfg` files of the installed game share a file name [known: data], so every script reference in
the shipped data resolves by rule 3; that is why `[data]\game\scripts\mapTools\tools.lua` and
`[data]\scripts\campaignMaps\C02_11bigBUILD.lua` (the file is in `maps\campaignMaps`) both load. A remake must
resolve script names the same way. Step 4 compares exactly one trailing directory component: the depth loop
of S 006ef680 starts at 1 and returns false as soon as the depth exceeds 1 [known].

`Default.WriteToLog(text)` does nothing; `Default.Break()` calls an optional debugger DLL and otherwise does
nothing; no shipped script calls `Default.Wait` [known] S 005cdde0, S 005cdf10, data.

### 3.3 Coroutines and waiting

- Every `RunFile` starts its chunk with `lua_resume`, so a chunk may yield [known].
- `Default.Wait(seconds)` S 005cde50: `luaL_checknumber` on the last argument (the one binding that can raise an
  argument error), then `YieldWait`: `waitMode = 1`, `wakeTime = hostClock + seconds`, `lua_yield(L, 1)` [known].
- `LuaScriptHost::UpdateThreads(now)` S 005c9a10 runs once per frame (menus and in game, before the logic
  update, [logic-core.md](logic-core.md) §4.1 step 8): it stores `now` as the host clock and, for every live
  thread id in list order, resumes a thread with `waitMode == 1` and `wakeTime < now` (strictly), after resetting
  `wakeTime = −1`, `waitMode = 0`. An error in the resumed code is discarded [known].
- The clock is wall time in seconds (the frame loop's total time), **not** logic ticks [known: caller argument;
  `logic-core.md` §4.1]. A script that waits is therefore not deterministic with respect to the simulation.
- Limits [known/inferred]: a thread created by `Default.CallScript`, a cutscene load or the property loader is
  destroyed as soon as `RunFile` returns, so a yield in such a file abandons the rest of the file. Engine
  callbacks are run with `lua_pcall` on the map-script thread (§4); a `Default.Wait` inside a callback raises
  Lua 5.0's "attempt to yield across metamethod/C-call boundary" error and aborts the callback [inferred from
  Lua 5.0.2 `lua_yield`]. Only the top-level chunk of the map script or of an info script could wait usefully.
- **No shipped script uses `Default.Wait`, `coroutine.*` or any other yield** [known: data]. Timed behaviour in
  the campaign is built from `onLogicTick` plus tick stamps in the `sd_` store (§3.9). A remake can run every
  shipped script as plain function calls; the wait facility is only needed for third-party scripts.

### 3.4 Calls from the engine into Lua, and errors

`LuaScriptHost::CallGlobal` / `CallGlobal_Number` / `CallGlobal_XY` (S 005c9780, S 005c9840, S 005c9920) [known]:
push `globals[name]`, push the arguments (as numbers), `lua_pcall(L, nargs, 0, 0)`.

- If the global is not a function, `lua_pcall` fails ("attempt to call a nil value"); this is treated like any
  other error.
- On an error the message goes to `LuaScriptHost_DumpScriptError` and is dropped. The callback is **aborted at
  the failing statement**: everything it changed before that point (simulation state, `sd_` values, Lua globals)
  stays, the rest of the callback does not run, and the next call starts normally. Example in the shipped data:
  a comparison of `logic.pl_getSacrificeState(...)` with a number while no building has that sacrifice on order
  (§2.3)
  aborts the remaining statements of that tick's `onLogicTick` [known: S 005b0210 returns no value; data
  `>= 1`]. In `C05.lua` that comparison is the last statement of `onLogicTick`, so nothing is skipped there; the
  other comparison of this kind (`questTarget_sacrificeOrderState`) is in a target no map uses [known: data].
- No engine callback uses a return value (`nResults = 0` everywhere) [known].
- After a failed call the error message is **not popped**: `LuaScriptHost_DumpScriptError` only reads the stack
  and the three `CallGlobal*` functions return 0 without a `lua_settop` [known] S 005c9440, S 005c9780. Every
  failed callback therefore leaves one value on the map-script thread's stack until the thread is destroyed at
  teardown; a successful call leaves the stack unchanged (`nResults = 0`). The same holds for a failed
  `UpdateThreads` resume and a failed `RunFile`. [inferred] invisible to scripts; a remake need not reproduce it.

### 3.5 `properties` (start-up rule database)

Conventions, all [known] ([properties-data.md](properties-data.md) §2.2, §3.1):

- `X_create("hexstring")` parses up to 32 hex digits, creates a record with defaults and **returns the id as a
  number** (signed 32-bit interpretation); the script stores it in a global and passes it to every later call.
- `X_set...(id, values...)` / `X_add...(id, values...)` return nothing. The record is found with
  `map::operator[]` without a check: an id that was never created is an access violation for the pointer tables
  and a silently created default record for doodads, remains and sounds.
- `cfg_*`, `mi_*`, `sh_*` setters write the three singleton blocks and take no record id (`mi_*` and several
  `sh_*` take a tribe id first).
- Integers are truncated, floats rounded to float32, booleans follow `lua_toboolean` (0 is true) except the four
  setters listed in `properties-data.md` §3.1 item 4.
- No property function reads or changes match state; they run once, before any world exists (§4.1).

### 3.6 `logic`: reading and changing the simulation

All functions are fields of the global table `logic`. "P" = player guard, "A" = AI guard, "C" = cell guard on the
named arguments (§2.3). "→" gives the pushed results on success. Every row is [known] at the address in
[../lua-surface.md](../lua-surface.md) §3.6 unless tagged otherwise. The last column says whether a shipped
script calls it.

**Time, random, user**

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `getTick()` → int | – | `NLogic::System.tickCounter` (the tick being executed; −1 before the first tick) | yes |
| `getSpeed()` → number | – | the **local** game speed, float at `UserProfile+0x24` (0 while paused, else 1..3; [save-format.md](save-format.md) §7). Not simulation state | yes |
| `getRandom(max)` → int | – | advances the simulation generator once (`LogicRandom_Next`) and returns `value % (max + 1)`, signed division: 0..max for `max >= 0`; `max == −1` divides by zero ([logic-core.md](logic-core.md) §3.3). `max` is truncated; `nil` counts as 0 and still consumes one random number | yes |
| `pl_getUser()` → int | – | index of the first player-table slot whose controller kind is 2 (local human) and that is active; slot 0 if none (S 005bdda0) | yes |

**Players** (`pl_`)

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `pl_getGoodAmount(p, good)` → int | P | `Player.pStock` count of the good (goods in stores, [players-victory.md](players-victory.md) §3.9) | yes |
| `pl_getMobileGoodAmount(p, good)` → int | P | `Player.pMobileStock` count | yes |
| `pl_getBuildingCount(p, type)` → int | P | finished buildings of the type from `Player.buildingCounts`; `type == −1` sums all types | yes |
| `pl_getConstructionCount(p, type)` → int | P | buildings under construction of the type; `−1` sums all | yes |
| `pl_getStreetCount(p)` → int | `p < 8` only | number of entries in the street net's per-player street vector; 0 if empty | yes |
| `pl_getRegionSize(p)` → int | P | `PlayerStatistics.regionSize` | yes |
| `pl_getMilitaryStrength(p)` → int | P | latest value of statistics series 4 | yes |
| `pl_getProducedGoodCount(p, good)` → int | `p < 8` only | last element of the good's statistics history. The history exists only for the tribe's goods and jobs and the body reads the vector's last element with checked iterators and no empty test, so another good id ends the process (`_invalid_parameter_noinfo`) [inferred from S 005b0e80] | yes |
| `pl_getBuildingProductivity(p, type)` → int | P | `GetAverageBuildingProductivity` S 00533160: `(sum / count) × 100`, truncated, over the finished buildings of the type in the statistics' productivity map, summed in ascending unique-id order (the map's key order, which fixes the float rounding); 0 when there is none | yes |
| `pl_hasCastle(p)` → bool | P | the village depot list holds a building of `p`, **finished or not**, whose type has `depot`, `casern` and `territoryBuilding` all set (property bytes +0x54, +0xf1, +0xf5; `FindPlayerBuildingWithDefFlags` S 005579a0) | yes |
| `pl_hasReachedPlayer(p, q)` → bool | P on `p`, `q < 8` | `Player.reached[q]` | yes |
| `pl_getReachedPlayerPosition(p, q)` → x, y | P on `p`, `q < 8` | `Player.reachedPos[q]`; nothing if `reached[q]` is 0 | yes |
| `pl_isPlayerSpotted(p, q)` → bool | P on `p`, `q < 8` | `Player.spotted[q]` | no |
| `pl_getTribe(p)` → int | P | tribe id | no |
| `pl_isAttacking(p, q)` → bool | P on `p`, `q < 8` | fight list: `p` attacks `q` (S 005738c0) | yes |
| `pl_isUnderAttack(p)` → bool | P | fight list (S 00573930) | yes |
| `pl_getPositionUnderAttack(p)` → x, y | P | fight list (S 005739a0); nothing when the x is −1 | yes |
| `pl_getSacrificeState(p, sacrifice)` → number | P | first finished sacrifice building of `p` (list of `workingMode == 9` buildings, list order) whose `VillageSacrifice.state == 3` (ordered, goods being delivered; S 00560c10, [quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.2) and whose ordered id equals `sacrifice`: goods delivered to the building / total cost of the sacrifice, as a float (S 005613a0). **Nothing** when no building is in that state for the id; a sacrifice that was already started (state 1) does not count | yes |
| `pl_sacrificeStarted(p, sacrifice)` → bool | P | the sacrifice system's per-player list of active sacrifices contains the id | yes |
| `pl_sacrificeStartedOnContinent(p, sacrifice, x, y)` → `true` | P, C(x, y) | as above and the sacrifice's building stands on the continent of the cell. Pushes `true` or **nothing** (never `false`) | yes |
| `pl_changeTeam(p, team)` | P | `SetPlayerTeam`: team, shared exploration, spotted flags ([players-victory.md](players-victory.md) §3.12) | yes |
| `pl_changePlayer(from, to)` | P on both | `TransferPlayerAssets` S 00529040 (same section): buildings, flags, roads, ships move; settlers of `from` are removed by `RemoveSettlersOfPlayer` S 00654bd0, which walks the six settler kind vectors in order. The remembered streets are rebuilt for `to`, and each gets its carrier from `Street::SpawnCarrier` S 00668be0: a `good_helper` carrier created on the street's middle cell and put straight into `WaitForPackage`, with no walk from a depot [known] | yes |
| `pl_setName(p, name)` | P | `Player::SetName` | yes |
| `pl_clearResource(p, good)` | P | removes the whole count of the good from the output stock (`Depot +0x28`) of the first finished building of `p` in the village depot list (types with `depot`, list order; `FindCompletedBuildingOfPlayerInList20` S 00558730); other depots untouched; nothing if `p` has none | yes |
| `pl_halfResources(p)` | P | same building, same stock (`Depot +0x28`): every entry becomes `count / 2` (integer division, toward zero) | yes |
| `pl_removeResource(p, good, amount)` | P | walks the depot list in order, finished buildings of `p` only, and removes `min(remaining, count)` from each output stock (`Depot +0x28`) until the remaining amount is `< 1` or the list ends | yes |
| `pl_sendOrderSacrificeMessage(p, sacrifice)` | `p < 8` only | posts two type-4 player messages (`!Player orders sacrifice` with the player's name, `!Sacrifice ordered` with the sacrifice's name) to every player except `p`. Presentation plus message queues | yes |

**Map** (`map_`)

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `map_getTerritoryPlayerId(x, y)` → int | C | owner entry of the territory grid at the cell | yes |
| `map_exploreArea(p, x, y, radius)` | P, C | `MapModifier::ExploreArea` (reveals for `p` and its allies, [navy.md](navy.md) §5.4) | yes |
| `map_exchangePatternType(x1, y1, x2, y2, from, to)` | C on both corners | in the bounding rectangle of the two cells, terrain pattern `from` becomes `to` (S 005b00e0 → `MapModifier::ExchangePatternInRect` S 00674470, flush enabled: deferred per-cell sets, then one `CellRectChanged` and an immediate construction recompute of the changed rectangle grown by 4 cells towards the origin, `map-resources.md` §3.4) [known] | yes |
| `map_createDoodad(x, y, doodad)` | C | `NDoodads::System::AddDoodadAtCell`; if the doodad property's byte +0x48 is set (blocking kind): rebuild continents, refresh AI players and the AI resource map, invalidate the construction map around the cell and remove a street through the cell | yes |
| `map_removeDoodads(x, y, radius, doodad)` | C | removes every doodad of that type on the hex spiral (§3.6.1) of the given radius; if the last removed type is blocking, rebuild continents and refresh the AI once at the end | yes |
| `map_forEachDoodad(x, y, radius, doodad, "fn")` | C | calls the global `fn(x, y)` for each doodad of the type on the spiral, in spiral order; nothing if the name is empty | no |
| `map_searchConstructionPlace(p, x, y, radius, sizeMask)` → x, y | P, then C (S 005afaa0 tests the player before the cell) | first cell on the spiral whose construction flags for `p` match the mask (§3.6.2); nothing if none within the radius | yes |
| `map_createDeposit(x, y, deposit, flag)` | C | `NResources::System::CreateDeposit(type, cell, flag)` S 00540b40: a new deposit at the cell with `growth = 1.0` (fully grown, harvestable) when `flag` is true, and `growth = growingStartSize` of its property (+0x44, S 00542da0) when it is false. `flag` follows `lua_toboolean`. The deposit constructor **draws one number from the simulation generator** (display offset, S 005432d0; [map-resources.md](map-resources.md) §3.9). The data uses both forms (`tent, true` and `tent, false`) | yes |
| `map_killDeposits(x1, y1, x2, y2 [, deposit])` | C on both corners | for every cell of the bounding rectangle, x outer and y inner, ascending: if a deposit is there whose `depletedTicks` (+0x50) is 0, i.e. it is not already being removed ([map-resources.md](map-resources.md) §2.6), and (the 5th argument is not a number, or is −1, or equals the deposit's **own** property id, not a type derived from the cell), `KillDepositAt`. The filter is a deposit type id (the data passes `tent`) | yes |
| `map_createChest(x, y, good, amount)` | C | if `good != −1`: `LogicChestSystem::AddChest(kind 1, cell)` and `SetContentGood(good, amount)` ([logic-core.md](logic-core.md) §2.7) | no |

**Computer players** (`ai_`; the switches are in [ai-player.md](ai-player.md) §2.5)

| Function | Guards | Changes | Used |
|---|---|---|---|
| `ai_isEnabled(p)` → bool | `p < 8` only | S 005ada40: reads the computer player's `NAI::Player.bActive` (+0x10) | yes |
| `ai_enable(p, profile)` | P, and the computer player of slot `p` must be inactive | S 005b2660: `NAI::System::ActivatePlayer` S 00581c40 with the slot's start position (read through the bounds-checked accessor on `mapInfo +0x04`) and the profile key `Lua_ToInt(arg 2)`. The only `ai_*` binding with the player guard. Nothing tests the slot's controller kind, so a **human slot can be taken over** by a computer player | yes |
| `ai_disable(p)` | A | S 005add10: `NAI::Player::Deactivate` | yes |
| `ai_allowAttack(p, bool)` | A | S 005add70: `attackAllowed` | yes |
| `ai_setAllowedAttackCount(p, n)` | A | S 005ade50: the attack limiter of the AttackSystem, military system field +0x144 = n (remaining attacks) | yes |
| `ai_setAttackEnable(p, bool)` | A | S 005addd0: the same field: −1 (unlimited) for true, 0 for false | no |
| `ai_enableExpansion` S 005adec0 / `ai_enableForesting` S 005adfe0 / `ai_enableSacrifices` S 005ae0a0 / `ai_enableShipConstruction` S 005ae100 `(p, bool)` | A | the flag of that name | yes |
| `ai_enableNeeds` S 005adf20 / `ai_enableCoinProduction` S 005adf80 / `ai_enableCatapultsLocal` S 005ae040 `(p, bool)` | A | the flag of that name | no |
| `ai_forbidHarborPosition(p, x, y)` | A, C | S 005ada90 → S 005824b0: **appends** the cell to the computer player's forbidden harbour vector; duplicates are kept | yes |
| `ai_allowHarborPosition(p, x, y)` | A, C | S 005adb50 → S 005824c0 / `Stl_VectorMapPos_EraseValue` S 00674ed0: erases the **first** equal entry. There is no not-found test: a cell that is not listed is erased at the vector's end iterator, past the last element [inferred: undefined behaviour of the erase] | yes |
| `ai_forbidAttackingPlayer(p, q)` | A, `q < 8` | S 005adc10 → `AddEnemyExclusion` S 00584840: appends `q` to the enemy exclusion vector (duplicates kept) and sets the **game** player's ignore-distance flag for `q` through `NPlayer::Military::SetFlag` S 005c09b0 ([players-victory.md](players-victory.md) §7) | yes |
| `ai_allowAttackingPlayer(p, q)` | A, `q < 8` | S 005adc90 → `RemoveEnemyExclusion` S 00583650: erases the first entry equal to `q` and clears the flag; no not-found test (as above) | no |

Every `bool` argument goes through `Lua_ToBool`, so `0` is true (§2.2). Campaign use of the switches [known: data]:
`C02` disables slot 1 and re-enables it with the profile `ai_c2_catapult`; `C04` switches slot 4 off and ship
construction off for slots 1 and 2; `C05` enables slot 1 with `ai_c5_pirates` and switches its sacrifices off;
`C06` enables slot 2 with `ai_c6_severin`, foresting off, sacrifices off and back on at tick 602; `C07` and `C09`
switch ship construction off for slots 1 and 2; `C08` forbids attacks for slots 1 and 3 and ships for slot 3;
`C10` makes slots 1, 2 and 3 exclude each other from attacks.

**Buildings** (`vi_`). "Building at the cell" = the building whose object occupies the cell in object layer 1
(`FindBuildingAtOrNearest(cell, 0)` S 00558890); "finished" = both construction floats `<= 0`.

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `vi_isBuildingAtPosition(p, x, y, type)` → bool | C, P | building at the cell, owned by `p`, of the type | yes |
| `vi_getBuildingPosition(p, type)` → x, y | P | first finished building of the type in the village's all-buildings vector (creation order); nothing if none | yes |
| `vi_getFirstBuildingPosition(p)` → x, y | P | first building of `p` in that vector, finished or not; nothing if none | yes |
| `vi_forEachBuilding(p, type, "fn")` | P | calls the global `fn(x, y)` for every finished building of the type, in vector order; nothing if the name is empty. The callback runs under `lua_pcall` on the map thread while the C loop holds its iterator [inferred: a callback that removes buildings invalidates it; the shipped callbacks only call `vi_enableProduction` and similar] | yes |
| `vi_countMilitaryBuildings(p)` → int | P | entries of `p`, finished or not, in the village's `territoryBuilding` list (`NVillage::System +0x3c`, [village-buildings.md](village-buildings.md) §2.2: building types whose property byte +0xf5 is set) [known] S 005b0b27 | yes |
| `vi_allBuildingsDestroyed(p)` → bool | P | true when that same list has no entry of `p`. Despite the name it does not look at other building kinds | yes |
| `vi_isMilitaryBuildingAtContinent(p, x, y)` → bool | C, P | an entry of `p` in the same list whose territory updater is active (byte +8 of the component at `Building +0xc4`) stands on the continent of the cell (S 00534000) | yes |
| `vi_isSacrificeBuildingAtContinent(p, x, y)` → bool | C, P | a finished sacrifice building of `p` on that continent | yes |
| `vi_destroyBuilding(p, x, y)` | C, P | building at the cell owned by `p`: `NVillage::System::RemoveBuilding(unique, true)` | yes |
| `vi_destroyBuildingsInArea(p, x1, y1, x2, y2)` | P, C both | the same for every cell of the bounding rectangle, x outer, y inner, ascending | yes |
| `vi_changePlayerOfBuilding(x, y, newPlayer)` | C, P on `newPlayer` | S 005ae830; the arguments are `(x, y, player)`, with no owner argument: the finished building at the cell is conquered for `newPlayer` (`ConquerBuilding`) whoever owns it | no |
| `vi_addGoodsToDepot(p, x, y, good, amount)` | C, P | S 005aea40: building at the cell owned by `p` whose type has the `depot` byte (+0x54) set: adds to its stock | yes |
| `vi_enableProduction(p, x, y, bool)` | C, P | finished building at the cell owned by `p` whose production passes `Production::ProducesGoods` S 00565550 (product slot 0 set and the catapult byte +0xb0 clear): `Production::SetEnabled` if the state differs | yes |
| `vi_orderSacrifice(p, x, y, sacrifice)` | C, P | building at the cell owned by `p` with `workingMode == 9`: if `VillageSacrifice::CanOrder(id)`, `Order(id, 0)` | yes |
| `vi_startSacrifice(p, x, y, target)` | C, P, P on `target` | same building test, and `VillageSacrifice::CheckCanStart() == 0` (S 00560f20: a sacrifice is on order, none is active, the goods are complete or the order was free, no cooldown, no running sacrifice of that definition, an enemy exists if the sacrifice targets one, not locked; [quests-sacrifices-stats.md](quests-sacrifices-stats.md) §3.2): sets the target player (field +0x0c) and calls `ai::village::VillageSacrifice::Start` | yes |

**Ships** (`na_`; [navy.md](navy.md))

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `na_getShipCount(p)` → int | P | finished ships of `p` (construction floats +0x48, +0x4c `<= 0`) | yes |
| `na_isShipAtPosition(p, x, y)` → bool | C, P | `FindShipAtPosition(cell)` exists and belongs to `p` | yes |
| `na_isShipOnRoute(p, x, y)` → bool | C, P | the ship route whose path contains the cell has an entry for `p`; **nothing** if no route passes the cell | yes |
| `na_isShipAtRoutePosition(p, x, y)` → bool | C, P | S 005aff90: compares the movement route (`Movement +0x80`) of `p`'s ship with the route through the cell. It is **not** a position test: the ship need not be at the cell, only travelling that route. Nothing if no route passes the cell | yes |
| `na_createShip(p, x, y)` | C, P | `NNavy::System::CreateShip(player, cell)` | yes |
| `na_sendShip(p, x, y, tx, ty)` | C both, P | ship of `p` at the cell: `Movement::MoveToTile(target)` S 005b9920, which inlines `UnmarkTile` (the ship's current tile) before `MarkTileAndMoveTo` | yes |
| `na_sinkShipOnRoute(p, x, y)` | C, P | S 005af1a0: route through the cell with an entry of `p`: that ship is scheduled to sink at once unless its state is 6..8 (S 005ac8d0) | yes |
| `na_destroyShip(p, x, y)` | C, P | ship of `p` at the cell is erased | no |

**Quests** (`q_`), `i` = slot index 0..39

| Function | Guards | Reads / changes | Used |
|---|---|---|---|
| `q_isValid(i)` → bool | `i < 40` | slot in use | yes |
| `q_add(i, name, kind, x, y, visible)` | `i < 40`, slot **unused** | `Quest::Init`: kind, id = name, finished = failed = false, marker, visible, both tick stamps = current tick; the progress text is **not** cleared (`q_remove` clears only the id, so a reused slot keeps its old text until `q_updateInfo`). `kind` is stored unchecked: any non-zero value counts as a sub quest in the messages and 2 leaves the slot unused. If `tickCounter != −1` and `visible`: message type 7 `!New main quest` (kind 0) or `!New sub quest` to the local player with the quest name and marker, and the quest log selects the quest | yes |
| `q_remove(i)` | quest | `kind = 2`, id cleared | yes |
| `q_finish(i, notify)` | quest | `finished = true`; if `notify`: message type 7 `!main quest finished` / `!sub quest finished` | yes |
| `q_failed(i, notify)` | quest | `failed = true`; if `notify`: message type 7 `!main quest failed` / `!sub quest failed` | yes |
| `q_reset(i, notify)` | quest | `finished = failed = false`; if `notify`: message type 7 `!New main quest` / `!New sub quest` | yes |
| `q_hide(i)` | quest | `visible = false` | yes |
| `q_isVisible(i)` / `q_isFinished(i)` / `q_isFailed(i)` → bool | quest | the flag | yes |
| `q_updateInfo(i, text)` | quest | if the text differs: store it and stamp `textChangedTime` | yes |
| `victory_setupQuests()` | – | victory mode (`MapInfo+0x1c8`) = 5: the match is decided by the main quests ([players-victory.md](players-victory.md) §3.6). `VictoryCond_Update` S 00535d70 then runs the local quest test each tick: all main quests finished → `DeclareWinner(local player)` and every quest hidden; any main quest failed → victory state 3. The other modes write their own text and finished / failed flags into quest slot 0, which the victory update activates at tick 0 | yes |

A text beginning with `!` is a localisation key (`!completed`, `!incomplete`, `!failed`), other texts are shown
as they are (`"3/5"`); the scripts use the literal `"invalid"` for "no progress text" [known: data; inferred:
display rule].

**Script data** (`sd_`)

| Function | Rule |
|---|---|
| `sd_setValue(key, value)` | `store[key] = Lua_ToInt(value)`: **the value is truncated to int32**; booleans, `nil` and tables store 0. Does nothing while no map script is loaded [known] S 005b28b0 |
| `sd_getValue(key)` → int | the stored value, or **nothing** when the key is absent [known] S 005b24d0 |

There is no delete; keys live until the next world build clears the store (§4.2).

**Settlers / NPCs** (`se_`): `se_createSettler(p, good, x, y)`, `se_activateNPC`, `se_deactivateNPC`,
`se_moveNPCTo(p, good, x, y, tx, ty)`, `se_moveNPCToFine`, `se_NPCLookAt`, `se_isSettlerOnPosition` take
`(player, settler property id, cell[, target])` and act on the NPC of that property at the cell owned by the
player; `se_createSettler` has guards P and C, the others test only `player < 8` and C; `se_isSettlerOnPosition`
→ bool [known: S 005ae160..S 005ae660]. Every call in the shipped scripts is commented out [known: data]; a
remake can provide them as stubs.

#### 3.6.1 Hex spiral order

`map_removeDoodads`, `map_forEachDoodad` and `map_searchConstructionPlace` visit cells in the same order [known]
S 005af910, S 005b1290, S 005afaa0, with `StepDirection` and the direction numbers of
[map-resources.md](map-resources.md) §3.1 (0 = E, 1 = NE, 2 = NW, 3 = W, 4 = SW, 5 = SE):

```
pos = centre; ring = 0; dir = 6; step = 0
loop:
    visit(pos)                      # only if pos is inside the map
    if dir > 5:                     # ring finished: move out
        pos = step(pos, 4)          # one cell SW
        ring += 1; dir = 0; step = 0
    if ring > radius: stop
    pos = step(pos, dir); step += 1
    if step >= ring: dir += 1; step = 0
```

The centre is visited first; ring `r` is entered by one SW step from the last cell of ring `r − 1` (that cell
itself is not visited a second time) and then walked `r` steps each in directions 0..5, visiting after every
step. Cells outside the map are skipped but the walk continues. The radius is compared as an unsigned number,
so a negative radius makes the walk run for about 2³² rings: the game hangs [known: S 005b1290]. The order decides which cell
`map_searchConstructionPlace` returns and the order of `map_forEachDoodad` callbacks.

#### 3.6.2 Construction place mask

`map_searchConstructionPlace` compares its 5th argument with the construction-map flags of the cell for the
player (`ConstructionMap::GetCellFlags`) by `ConstructionFlags_MatchesPlaceKind` S 0052dd80 [known]:

```
if (cell bit 6 clear) and (mask bit 6 set): no match
else: match = (mask & cell & 0x3f) != 0
```

The scripts pass the `Size*` globals of `scripts\properties\config.lua`: `SizeSmall = 7`, `SizeMedium = 6`,
`SizeLarge = 4`, `SizeMine = 8`, `SizeShip = 16`, `SizeMilitary = 64` [known: data]. The bit meanings are those of
the building size mask ([properties-data.md](properties-data.md) §3.6).

### 3.7 `menu`, `txt`, `gfx` as used by map scripts

Several `menu.*` functions **change simulation state** and have **no guards**: a wrong player index or a player
without a finished depot-type building dereferences a null pointer [known: bodies]. All return nothing.

| Function | Effect | Sim state |
|---|---|---|
| `menu.addResource(p, good, amount)` S 005d9970 | adds to the output stock (`Depot +0x28`) of the first finished depot-type building of `p` | yes |
| `menu.clearResources(p)` S 005d9c30 | empties that stock (`Depot +0x28`) | yes |
| `menu.createBuilding(p, type, x, y)` S 005d9a30 | `NVillage::System::PlaceBuilding`, then `Construction::Complete` **only when the placement succeeded**: a failed placement leaves nothing behind | yes |
| `menu.createBuildingWithSettler(p, type, x, y [, soldierGood])` S 005d9ac0 | one test of the type's `territoryBuilding` byte (+0xf5) decides both branches. Set: `AddTerritorySource(cell, radius 4, player)` first. Place and complete the building. Byte clear: spawn its worker; set: create **three** soldiers of property `soldierGood` at the cell and link them (`CreateSoldier` S 00656310, `VillageLink_LinkSoldier` S 0053c4c0); no state is set afterwards, so they stay in the settler constructor's state 1 (S 00656c20), unlike the military's own spawn `Soldiers::SpawnSoldier` S 00566440, which sets 0x0c (`SetStateInBuilding` S 00658770) [known]. The territory updater's `Activate` then runs unconditionally, for either kind. Nothing after the territory source happens if placement fails. The data passes the 5th argument for `fortress` and `tower` and omits it for temples, a forester and a catapult | yes |
| `menu.createStreet(p, x1, y1, x2, y2)` S 005dada0 | street planner from cell 1 to cell 2, then `NNet::System::BuildStreet` | yes |
| `menu.lockBuilding(p, type)`, `unlockBuilding`, `lockJob`, `unlockJob`, `lockSacrifice(p, s)`, `unlockSacrifice` | player lock maps 0, 3, 1 ([players-victory.md](players-victory.md) §3.10); the sacrifice variants also refresh an open sacrifice tab | yes (not saved) |
| `menu.addSacrifice(p, s, notify)` S 005dac60 | lock map 2 (sacrifice available), refreshes an open sacrifice tab; if `notify` is true a type-4 message `!New Sacrifice available` to `p`. In the campaign the argument is the parameter `sendMessage` of the map's own wrappers (`enableStoneToDustSacrifice`, `enableWaterSacrifice` in `C05.lua`, `addTreeExchange` in `C06.lua`, `addPacifySachmet`, `addGenerateBeer` in `C07.lua`): quest callbacks pass `true`, so the message is sent; `onLoaded` and the player set-up pass `false` [known: data] | yes (not saved) |
| `menu.allowActions(type, allow [, code])` S 005d9570 | action-button override per building type: `allow = false` stores `code`, `true` removes it ([game-commands.md](game-commands.md) §5.1) | UI only |
| `menu.createLetter(text)` S 005da720 | letter message (type 8, the text as passed, not looked up) to the player of the game screen (active screen +0xfff4; `PlayerMessages_SendLetterToPlayer` S 005c05b0 → `AddWithText2(8, text, "")`); whether that is always the local player is open ([quests-sacrifices-stats.md](quests-sacrifices-stats.md) open item 5) | messages |
| `menu.addMinimapSymbol(kind, x, y)` / `removeMinimapSymbol` | list of minimap markers (kind 2 = quest marker in the scripts); x, y read as floats | UI only |
| `menu.openBookDialog(text)` S 005dd5e0 | if the book reports true from its vtable slot +0x10, calls slot +0xc ([inferred] closes an open book), then toggles game screen 2 and adds the first page; `menu.addPage(text)` adds a page; `menu.addPicture(name)` sets the picture | UI only |
| `menu.startCinematic()` S 005dd3c0 | closes all dialogs and opens the cinematic screen; `menu.addCinematicPage(textKey, titleKey, cutscene [, x, y])` appends a page (x, y only if argument 4 is a number, else −1, −1); `menu.updateCinematic()` calls slot 1 of the cinematic screen's `IUpdateable` face, `nMenu::Cinematic::Update` S 005fb3e0 (vtable S 007ef9bc): one page-timer step, synchronously inside the calling tick, which can start the first page and its camera path and write the local game speed [known: S 005dd5c0, S 007ef9bc]. The cutscene name is either a short name (`"1intro"` → `<map dir>\<map name>_1intro.lua`) or a full `[data]\...` path (§3.8) | UI; see §8 |
| `menu.addTutorialPage(key)` S 005daa30 | adds tutorial page `key` with description key `key .. "_desc"` and shows it | UI only |
| `menu.showSacrificeEffect()` | plays the sacrifice screen effect with no event | UI only |
| `menu.showMinimap()` S 005d9530 | calls one method of the game screen's minimap object with argument 1 ([inferred] shows it); not used by the shipped scripts | UI only |
| `menu.addDebriefing(x)`, `menu.addExtro(x)` | **do nothing** (both bound to a function returning 0) | – |
| `menu.addCutsceneDebugName(name)` | adds a row to the debug cutscene list | debug UI |
| `menu.setLanguage(code)`, `menu.setVideoVoiceStream(code, n)`, `menu.setPlayerColor(i, r, g, b)` | `menu.cfg` only: language string, map language → voice stream index, player colour table entry `i` (alpha forced to 1.0) | start-up |
| `txt.isValid(key)` → bool S 005da660 | the localisation table contains the key | read only |
| `gfx.createParticel(effect, x, y [, dx, dy, dz])` S 005aca40 | starts the named particle effect at the world position of the cell, plus the float offset when argument 4 is a number; looping; reseeded from the render clock. Does nothing if the effect name is unknown | presentation only |

**How a cinematic ends** (`nMenu::Cinematic::Update` S 005fb3e0; the phase table is in
[camera-input-cutscenes.md](camera-input-cutscenes.md) §3.8) [known]: the phases run fade-in → playing → ending →
restore HUD → restore speed. A page stays up for its text length × 0.1 s, at least 0.5 s, and then waits for its
voice-over to finish. The ending phase calls `nGame::System::EndCinematic` S 00782bb0 (its only caller), which
switches the AI, chests and sacrifices back on; after 0.5 s the HUD is restored, after 1.0 s more
`CloseAllDialogs` hides the screen, and its `OnHide` S 005faee0 calls `quest_cinematicDone` (§4.3) and then writes
the saved game speed back. Between `menu.startCinematic` and that point the local game speed is 1: the
simulation keeps ticking at normal speed for the whole cinematic. So the simulation switches come back at least
1.5 s of frame time before the script hears that the cinematic is over, and both moments depend on the local frame
clock and the voice-over, not on ticks (§8).

`ui.*` (quest log widgets, first argument = menu screen index, the scripts use `BOOKDIALOG = 24`; the index
selects `nMenu::System + 0x10 + 4 × index`, where the book is index 2, so 24 reads `System + 0x70`, inside the pending
map path string [known: S 005dc40a, S 005db458; inferred: the consequence]. In shipped play these calls do not run:
the quest list is reached only through the book, which only `menu.openBookDialog` opens, and its only shipped caller
chain starts at `openBriefing()`, which the binary never calls):
`ui.createPicture(screen, name, x, y, texture, u, v, w, h)`, `ui.createLabel(screen, name, x, y, textKey, font)`,
`ui.createTextBlock(screen, name, x, y, w, h, textKey, font)`, `ui.createCheckedButton(screen, name, x, y,
caption)`, `ui.show(screen, name, bool)`, `ui.setContent(screen, name, textKey)` (label, button or text block),
`ui.setMarkFlag(screen, name, n)` (button mark = `n != 0`). Coordinates are integer pixels, converted to
relative units by `nUi_PixelsToRelativeX` / `Y` = `pixels / W`, `pixels / H`, where W and H are the two unsigned
ints the graphics device returns from its field +0xa8 [known] S 004aaae0, S 004aab10, S 005db370..S 005dc6a0;
[TODO] not established: whether that pair is the current back-buffer size or a fixed virtual resolution (the
writer of the device field settles it). `ui.show` does not test whether the widget
exists [known] S 005dc6a0: a wrong name is a null dereference.

Info pages (`scripts\info\*.lua`): `ui.infoLabel(x, y, key)` and `ui.infoLabel2(x, y, key)` (two label styles; a
4th argument in the data is not read), `ui.infoPicture(x, y, texture, u, v, w, h, drawW, drawH)`,
`ui.infoText(x, y, w, h, key)` → int, the laid-out text height in pixels (the only one of the four that returns a
value; the shipped pages ignore it) [known] S 005dc8c0..S 005dd010. Presentation only.

### 3.8 `cutscene`

A cutscene file is a list of calls, run once in a temporary thread by `CutsceneCamera::LoadScript(name,
isFullPath)` S 0078ac10, which first replaces the camera spline by a new empty one [known]:

- `cutscene.addPosition(dt, x, y, z)`: appends a position key at time `lastPositionKeyTime + dt` (S 0078a5b0);
- `cutscene.addLookAt(dt, x, y, z)`: the same for the look-at track, which has its own running time (S 0078a660);
- `cutscene.setRelative()`: sets the spline's `relative` byte (`CameraSpline +0x41`, S 0078a640) [known]. No
  function reads that byte, so the call has no effect of its own [inferred, search of the decompiled program].
  Whether the position keys are offsets from a page's anchor cell is decided by the page, not by this call:
  `nMenu::Cinematic::Update` S 005fb3e0 plays the path at the page's cell when the page has one (`x, y` of
  `menu.addCinematicPage`) and unshifted otherwise ([camera-input-cutscenes.md](camera-input-cutscenes.md)
  §3.7). 40 cutscene scripts of the game data call it in their first line, the ones written with small
  coordinates [known: data];
- `cutscene.createLoopAtEnd()`: `CameraSpline::SetLoop(true)` (S 0078a6f0; only `cutscene_circle.lua`).

The two `add` functions read four floats (float32); `setRelative` and `createLoopAtEnd` read no argument; all
return nothing. "Last key time" is the track's time span, last key minus first key, 0 for an empty track
(S 0078c6d0). `dt` values are seconds [inferred: spline time base not read here]. The `cutscene` table is
registered again at every load and stays a global afterwards (§2.1). The path of a short name is
`<directory of the current map><map name>_<name>.lua` (S 0078a940). A file
whose name is in no directory leaves the spline empty and raises no error [inferred: §3.2 rule 5]. Full paths
are resolved by file name (§3.2), so the references that name the wrong directory
(`[data]\scripts\campaignMaps\C02_11bigBUILD.lua` in `C01.lua` and `C05.lua`, two more in `C03.lua`; the files are
under `maps\campaignMaps`) load the intended file; every cutscene path in the shipped scripts names an existing
file [known: data].

### 3.9 Script-side helpers the campaign depends on (Lua, not C)

These are defined by the shipped `scripts\mapTools\*.lua` and need nothing from a remake beyond §3.6/§3.7, but
they fix how the C functions are exercised [known: data]:

- **Timers.** `updateTicker(name, duration, force)` stores `logic.getTick()` under `name` in the `sd_` store and
  returns true when more than `duration` ticks passed. `questTarget_Relativ(quest, ticks)` stores the first tick
  it was evaluated under `<quest>relativStartTime`. `spawnDepot_onLogicTick` counts ticks in
  `SpawningDepot<name>_Timer`. All timing is in logic ticks (10 per second at speed 1, `logic-core.md` §6).
- **AI attack limiter.** `ai.update(ticks)` computes `minute = ticks / 600` and, per player 1..6, when the stored
  minute is passed: `logic.ai_setAllowedAttackCount(player, 3)` and a new time `+ delay +
  logic.getRandom(randomMinutes)`. The stored time passes through `sd_setValue`, so it is truncated to an integer.
  The limiter is inert in the shipped campaign: every `ai.setup` call of the maps is commented out, so no player is
  registered and `logic.getRandom` is never executed [known: data].
- **Quest machine** (`quests.lua`, `questTargets.lua`): quests are Lua tables `quests[MAINQUEST = 0]`,
  `quests[SUBQUEST = 1]`, numbered by a running `questIndex` (the `logic.q_*` slot index, so at most 40 per map).
  Each tick the sub quests, then (if none finished) the main quests are evaluated in definition order; the first
  quest whose target function returns true is finished and evaluation stops for that tick. A quest with briefing
  pages starts a cinematic and its `q_finish` is delayed until the engine calls `quest_cinematicDone` (§4.3).
  The key `showBookDelay` in the `sd_` store pauses quest evaluation while it is positive; winning or losing
  sets it to 2000000000, which stops evaluation for good. The decrement `showBookDelay − 1 / getSpeed()` (the
  script clamps the speed to at most 3) is computed at single precision (§8): the spacing of float32 values at
  2·10⁹ is 128, so `2000000000 − step` rounds back to 2000000000 for every step below 64, and the stored value
  never changes. In double precision it would fall by one unit per tick after the truncation of `sd_setValue`.
  2000000000 is the only positive value the shipped scripts store under this key (the 100-tick delay after
  briefings is commented out in `quests.lua`) [known: data + S 005b28b0; inferred: the rounding].
- `destroyAllBuildings(player)` in `tools.lua` loops `until x ~= nil`: it removes one building and never
  terminates when the player has none [known: data]. `ui.*` quest buttons name handlers `<name>_isPushed`, which
  the engine never calls (§4.4).

## 4. Update order

### 4.1 Application start

1. `LuaScriptHost` created: state, `lua_checkstack(256)`, base + math, `Default` [known] S 005c8ef0.
2. `properties` registered; `PropertiesDb::RunPropertyScript("data")` runs
   `[data]\scripts\properties\data.lua` in a temporary thread [known] S 0054f8d0. `data.lua` defines
   `loadPropertiesFile(name)` (a `Default.CallScript` wrapper) and loads, in this order [known: data]:
   `defineTribes`, `doodads`, `goods`, `config`, `patterns`, `animals`, `jobs`, `deposits`, `remains`,
   `buildings`, `sacrifices` (which loads `sacrifices_goodExchange` and `sacrifices_campaign` after its own enum
   constants and before its records), `signs`, `military`, `ship`, `sounds`, `ai`, `harbors`, `tribes`,
   `spawnpoints`. The order is binding: each file uses id globals and constants of earlier files (§6.2).
3. `menu`, `ui`, `txt` registered; `[data]\scripts\menu.cfg` run [known] S 005dda30.

### 4.2 World build (new game or loaded save)

`nGame::System::BuildWorld` S 00784d40 and `Game_LoadWorldFromDescriptor` S 005ac770 [known]:

1. scene and `NLogic::System` constructed (`tickCounter = −1`, [logic-core.md](logic-core.md) §2);
2. `GameScript_InitMapScript` S 005b2720: new map-script thread; script path = ""; flag S 0088b314 = 1; **the
   `sd_` store is emptied**. Lua globals are not touched;
3. if the session is offline (`NComm_Manager +0x3c8 == 0`, S 004083d0): register `logic` and `gfx`
   (S 005b2990);
4. map file or save loaded (`GameFile_LoadImpl` S 005aaed0): the map part for every type, then the logic part
   only for the types 10, 0x65 and 0x6e ([save-format.md](save-format.md) §3.4). At the end of
   `GameFile_LoadMap` S 005aa7b0, after map info, terrain, resources, doodads, ambients, navy and spawn points
   and **before** the logic part (players, villages, `sd_` store, quests), the map script is located and its
   **top-level chunk runs** (`GameScript_LoadMapScript` S 005b1fe0). The script path is the map path of
   (type, name) with everything from the last `.` replaced by `.lua`; name is the map name in `MapInfo +0x24`
   as read from the file, type is the map type stored in the file (`MapInfo +0x1d0`), except that the type of
   the load request is used when the stored type is 10 or 0x6e or when the request type is 1. A save thus
   finds the script of the map it was started from. If the file does not exist (`Fs_FileExists`) the script
   path is set empty and nothing below is called. A top-level chunk must therefore only define globals and
   functions and include its tool scripts: players do not exist yet for a new game, and for a save neither
   the players nor the `sd_` values have been read;
5. new-game map types (0, 1, 2, 100, 102; S 0052c270) only: AI tables resized, players created from the
   descriptor; chests distributed only if the session's game seed or game id is not 0;
6. map post-load step (`MapModifier_InitAfterMapLoad`), map-update batch closed;
7. new-game types and type 0x65 only: the descriptor's extra start parameter (victory mode, `MapInfo +0x1c8`)
   and the map type (`MapInfo +0x1d0`) written to `MapInfo`, then **`onStarted()`**;
8. always: **`onLoaded()`**. A new game thus gets `onStarted` then `onLoaded`; a save (types 10, 0x6e) gets
   only `onLoaded`. Type 0x65 (`.a2m`, map part plus logic part; no such file is installed) gets both although
   its players come from the file.

Steps 4 to 8 are skipped altogether when the descriptor's load-path selector (`+0x23c`) is 1:
`Game_LoadWorldFromDescriptor` then only resets the logic system to an empty square map and returns, so no
script is located and neither callback runs [known] S 005ac770; [save-format.md](save-format.md) §3.4.

Both callbacks run before the first logic tick, with `tickCounter == −1` for a new game (so `q_add` posts no
"new quest" message there: it tests `tickCounter != −1`) and the saved tick for a save [known] S 005b1670;
`logic-core.md` §2.

Teardown `GameScript_DestroyMapScript` S 005b1ce0 (from `nGame::System::Shutdown` S 007834e0): the global
`createQuestUi` is set to nil if it is a function (S 005c8dc0), the thread is destroyed, the thread id set to
−1, the path cleared, the flag set to 0 [known]. All other globals of the map script survive into the menu
and into the next map; the shipped scripts re-initialise their own state at file top (`quests = {}`,
`setupDone = false`, `spawningDepots = {}`, ...) when the next map script includes the tool files again.

### 4.3 Engine callbacks

All are global functions looked up by name at call time on the map-script thread; all are skipped while the
script path is empty; errors are silent (§3.4).

| Global | Arguments | When | Evidence |
|---|---|---|---|
| `onStarted()` | – | once, new game, §4.2 step 7 | [known] S 005b2220 |
| `onLoaded()` | – | once per world build, §4.2 step 8 | [known] S 005b2180 |
| `onLogicTick(tick)` | `tickCounter` of the tick just executed (0 for the first) | once per pass of the tick loop in `NLogic::System::Update`, **after** all subsystem updates of that tick (the last is the victory-condition update) and after the scene's per-tick hook, before the tick listener; only if the flag argument of `Update` is true (the frame loop S 004018e0 passes true) and the map editor's batch editing is off, in which case no tick is executed either ([logic-core.md](logic-core.md) §3.1) | [known] S 005b20d0, S 00527070 |
| `createQuestUi()` | – | when the book dialog is switched from its story pages to the quest list: the story/quest toggle button is clicked while the page text is visible. `nMenu::Book::ShowQuestView` hides the page buttons, page text and page counter, deletes the book's script-widget list, calls the function, stops the voice-over and sets the toggle caption to `!STORY` | [known] S 005b1f30, S 005fc900, S 005fcbc0 |
| `destroyQuestUi()` | – | when the toggle button is clicked while the quest list is shown: the script-widget list is deleted first, then the function is called, then the page widgets are shown again and the caption becomes `!QUESTS`. It is **not** called when the book is closed while the quest list is shown (the only caller is the toggle branch of `nMenu::Book::Update`) | [known] S 005b1e80, S 005fcbc0 |
| `quest_cinematicDone()` | – | in the hide handler of the cinematic screen (`nMenu::Cinematic::OnHide`), after the cursor and the overlay fade are restored and before the game speed saved by the cinematic is written back to `UserProfile +0x24`. The hide comes from `CloseAllDialogs` at the end of the restore-speed phase, so the callback runs at least 1.5 s of frame time after `EndCinematic` (§3.7) | [known] S 005b2360, S 005faee0, S 005fb3e0 |
| `sacrifice_execute(sacrificeId)` | first dword of the sacrifice's definition ([inferred] its property id) | when a sacrifice effect of kind 1006 (`Effect_FunctionRunScript`) is applied (S 00660500). No shipped sacrifice uses that effect and no shipped script defines the function | [known] S 005b2410; data |
| `<fn>(x, y)` | cell, pushed as two numbers | synchronously inside `logic.vi_forEachBuilding` (through S 005af860) and `logic.map_forEachDoodad` (S 005b1290 calls `CallGlobal_XY` itself, with the same path test) | [known] S 005af860, S 005b1290, S 005c9920 |
| `<widget>_isClicked()`, `<widget>_isPressed()` | – | §4.4 | [known] S 004b12d0, S 004b1470 |

`onLogicTick` runs inside `NLogic::System::Update`, i.e. it is part of the tick: what it changes is seen by the
next tick's subsystem updates, and random numbers it draws come from the simulation sequence between tick `n`'s
last subsystem and tick `n + 1`'s first command.

Functions the shipped map scripts define that **this binary never calls** (no such string in the image)
[known]: `onTriggerIsActive(name)`, `openBriefing()`, `dbg_addCinematics()`, `dbg_playCinematic(name)`, and the
`MainQuestButton<n>_isPushed` / `SubQuestButton<n>_isPushed` handlers.

### 4.4 Button events

`nUi::Button::OnClicked` / `OnPressed`: for a button with a non-empty object name, the engine builds
`<name>_isClicked` / `<name>_isPressed` and, if flag S 0088b314 is set, a global of that name is a function
(looked up on the map-script thread) and the script path is not empty, calls it with no arguments [known]
S 004b12d0, S 004b1470, S 004c44a0, S 005af810, S 005af830. The script call is the last step of both handlers:
on a click a check button first toggles its mark, the sound `uiClick0` plays, the parent widget and the click
observers are notified; on a press the press observers and the parent are notified first. The quest buttons
created by `quests.lua` are named `MainQuestButton<i>` / `SubQuestButton<i>`; the script
defines `..._isPushed`, so clicking them reaches no script function in this build [known: data + code].

### 4.5 Per frame

`LuaScriptHost::UpdateThreads(totalSeconds)` (§3.3), after the game system's and the menu system's per-frame
updates and the network main loop, before the FPU control word is set and the logic update runs [known]
S 004018e0. With the shipped scripts it never has a thread to resume.

## 5. Inputs and outputs

| Direction | Interface |
|---|---|
| Files in | `scripts\properties\*.lua`, `scripts\menu.cfg`, `scripts\mapTools\*.lua`, `<map>.lua`, `<map>_<n><name>.lua`, `scripts\info\{i,b}_<hex>.lua`, `scripts\editor\*.lua`; all through the encrypted-file reader (§6.1) |
| To the rule database | `properties.*` → `PropertiesDb` ([properties-data.md](properties-data.md)) |
| To the simulation | `logic.*` and the state-changing `menu.*` functions (§3.6, §3.7): players, village, street net, navy, AI, map modifier, doodads, resources, quests, chests, sacrifice system, simulation random generator |
| From the simulation | read-only `logic.*` queries; `onLogicTick(tick)` |
| To presentation | messages (types 4, 7, letter), minimap symbols, briefing book, cinematic pages, tutorial pages, quest-log widgets, particle effects, camera splines, info pages |
| From presentation | `createQuestUi`, `destroyQuestUi`, `quest_cinematicDone`, button events; `logic.getSpeed()` (local speed) |
| Save | the `sd_` store and the quest slots (§7) |
| Network | none of its own. Map scripts change the simulation outside the command stream, so they are only safe where every peer runs the same script at the same tick; `logic` is registered only offline (§2.1) |

## 6. Data-driven parameters

### 6.1 Script files by kind

Counts are of the installed game data [known: data]. All `.lua` files under `scripts\` are part of the build
checksum compared between network peers; `menu.cfg` and the map folder's scripts are not matched by its
`[data]\scripts` + `*.lua` pattern ([../lua-surface.md](../lua-surface.md) §2.2).

| Kind | Files | Run by / when | Libraries used | Touches simulation |
|---|---|---|---|---|
| Property scripts | `scripts\properties\`: 22 files (`data.lua` + 21 loaded by it, two of them via `sacrifices.lua`) | start-up, §4.1 | `properties`, `Default.CallScript` | defines the rules; no match state |
| Menu configuration | `scripts\menu.cfg` (a Lua chunk) | start-up | `menu.setLanguage`, `setVideoVoiceStream`, `setPlayerColor` | no |
| Map tool scripts | `scripts\mapTools\`: `quests.lua`, `questTargets.lua`, `tools.lua`, `cinematicFunctions.lua`, `aiLimiter.lua`, `spawnDepots.lua`, `tutorial.lua` | included by map scripts with `Default.CallScript` | `logic`, `menu`, `ui`, `txt`, `gfx` | yes |
| Map scripts | `maps\campaignMaps\C01.lua` .. `C11.lua` (11), `map\Presentation.lua` | world build, §4.2; one per map, same base name as the `.s2m` | as above | yes |
| Cutscene camera paths | `maps\campaignMaps\C<nn>_<n><name>.lua` (186), `scripts\mapTools\cutscene_circle.lua` | each cinematic page with a cutscene name | `cutscene` | no |
| Info pages | `scripts\info\i_<hex>.lua` (95), `b_<hex>.lua` (29; each has an `i_` file of the same number) | `nMenu::Info::Open(owner, mode, index, id)` S 005f6310: mode 1 runs `[data]\scripts\info\i_` + lower-case hex of `index` + `.lua`, mode 2 runs `b_` + lower-case hex of `id` + `.lua`, each on the map-script thread (`GameScript_RunFile` S 005b1dc0); if the file does not exist the page shows `Database file i_<hex> not found!` (`b_` in mode 2) instead. Mode 0 runs no script: it shows the text key `dialog<index>_<id>`. **The only call of `Open` in the image (S 005d9776 in `nMenu::System::ToggleDialogInfo`) passes mode 0** [known: the function has one code reference and the two path strings are referenced only inside it], and `Open` has no data reference (no vftable or function-pointer slot holds it) [known: one `UNCONDITIONAL_CALL` reference], so modes 1 and 2 are unreachable and these files are never run. The number is the `*_create` id of the object the page describes: `i_12e67603` is `guardHouse`, `b_154551b3` the smeltery, `b_154c1dae` the gold mine [known: data] | `ui.infoLabel`, `infoLabel2`, `infoPicture`, `infoText` | no |
| Editor lists | `scripts\editor\scatter.lua`, `copypaste.lua` | map editor debug menu (`nMenu::Debug::RefillElementList` S 00608160 holds both path strings) | `editor` | editor only |
| Unreferenced | `scripts\graphic_main.lua` (one `Default.WriteToLog` line) | no loader found | – | no |

The free-game maps (`maps\Freegamemaps`) have no map script [known: data]; for them every callback is skipped.

### 6.2 Globals the scripts rely on

Property scripts define, as plain global assignments, the vocabulary all later scripts use [known: data]:

| Defined in | Globals (examples) |
|---|---|
| `defineTribes.lua` | `bavarians`, `egyptians`, `scots` = `properties.tp_create("b0d378a3")`, `("f5016d33")`, `("497ffda3")` |
| `config.lua` | `ExtremlyShortTime = 50` .. `ExtremlyLongTime = 400`; `SizeInvalid = 0`, `SizeSmall = 7`, `SizeMedium = 6`, `SizeLarge = 4`, `SizeMine = 8`, `SizeShip = 16`, `SizeMilitary = 64` |
| `Goods.lua` | good type enum `Invalid`, `Ware`, `Settler`, `WareGroup`, `EitherGroup`; one id global per good (`wood`, `corn`, `weissbeer`, ...) |
| `Jobs.lua` | `settlerType_Worker` .. `settlerType_NPC`, `soldierType_Sword`, `soldierType_Bow`, `projectile_*`; one id global per job / soldier rank (`good_soldierHalberd0`, ...) |
| `buildings.lua` | `Depot_*`, `DoorOffset*`, `BuildingWorkingMode_*`; one id global per building type (`woodCutter`, `brauhaus`, `fortressBav`, `castle`, `depot`, ...) |
| `doodads.lua` | `doodad_Type_*` (`doodad_Type_Landscape = 0`, `doodad_Type_Sign = 1`, ...); ids such as `doodad_chest`, `doodad_openChest` |
| `deposits.lua` | `mapTreeType_Bavarian = 100`, `mapTreeType_Egyptain = 101`, `mapTreeType_Scot = 102`; ids such as `tent`, `stone_01`, `tree_10` |
| `patterns.lua` | tree-set enum `None = −1`, `CaribbeanFlair = 0`, `ConiferousForest = 1`, `BlackForest = 2`, `Lava = 3`, `Snow = 4`, `Bavaria = 5`, `Desert = 6`, `Highland = 7`; ids such as `pattern_meadow`, `pattern_meadow3`, `pattern_sand2`, `pattern_water` (`properties.pa_create`) |
| `sacrifices*.lua` | `Effect_*` (e.g. `Effect_FunctionRunScript = 1006`), `Target_*`, `SacrificeCategory_*`; ids `sacrifice_*` |
| `ai.lua` | `AI_MilitaryMode_*`, `AI_BattleMode_*`, `AI_BattleValueOf_*`; profile ids such as `ai_normal`, `ai_c2_catapult` |
| `military.lua`, `sounds.lua`, `spawnpoints.lua` | `tactic_*`, `SoundType_*`, `SpawnType_*` |

Helper functions defined by property scripts, all global and therefore still defined in every later script:
`loadPropertiesFile` (`data.lua`), `addBaseStack` (`animals.lua`), `defaultSacrificeGEProperties`
(`sacrifices_goodExchange.lua`), and in `patterns.lua` `setPattern` with its wrappers `setMeadow`, `setSand`,
`setEarth`, `setRock`, `setStoneground`, `setSnow`, `setSeaground`, `setSwamp`, `setShip`, `setLava` [known:
data]. The goods enum uses bare names (`Invalid = −1`, `Ware = 0`, `Settler = 1`, `WareGroup = 2`,
`EitherGroup = 3`), as does the tree-set enum of `patterns.lua`: a map script that assigns a global of such a
name changes it for the rest of the process.

All script files are plain ASCII except `patterns.lua`, which has raw bytes above 0x7f (not escapes) in seven
string literals, the pattern names on lines 274 and 289 to 314 (two bytes before `Desert …`, probably `0xA7 0xA7`)
[known: data]; a loader must read script files as bytes, not as UTF-8.

Map scripts add their own globals (`player0 = 0`, enemy slot numbers, positions) and the tool-script tables
(`quests`, `ai`, `spawningDepots`, `tutorial_data`). A global that is read but never assigned is `nil` and
behaves as false / 0 at the C boundary; the shipped scripts read four: `unlockFarm` (`C09.lua`, a callback that is
therefore skipped), `name` and `questType` (`quest_addToLogic` in `quests.lua`) and `triggers` (`Presentation.lua`,
dead code) [known: data].

A remake that converts the property scripts to another format must still expose these globals to the map scripts
with the same names and values, because map scripts pass them to `logic.*`.

## 7. Save and load

- **Saved:** the `GameScript` section: flag S 0088b314 (bool), the script path (string; read back into a
  temporary and ignored), count, then per entry key string + int32, in the map's key order; and the 40 quest
  slots ([save-format.md](save-format.md) §3.3 items 10 and 11) [known] S 005b0f30, S 005b2780. The loader
  stores the flag it reads into S 0088b314 and assigns each entry with `store[key] = value`; it does not empty
  the store itself (`GameScript_InitMapScript` did, §4.2 step 2), so values the top-level chunk set with
  `sd_setValue` under keys that the save lacks survive the load [known] S 005b2780; [inferred] for the
  consequence.
- **Not saved:** the Lua state: globals, tables, locals, upvalues, pending waits. Also not saved: the player lock
  maps, action overrides, minimap symbols, tutorial pages shown, AI flags set through `logic.ai_*` unless the AI
  section stores them ([ai-player.md](ai-player.md) §7; [save-format.md](save-format.md) §7) [known for the
  script side: `GameScript_Store` writes nothing else; [inferred] for the rest, from the cross-references].
- **On load** the map script file is run again from the top, the store and quests are read, then `onLoaded()`
  is called (§4.2). The script rebuilds its tables by running its setup code again and re-derives progress from
  the saved state. The shipped `quest_onLoaded` runs `setupQuests()` if `setupDone` is still false (it is after
  a load: the re-run file top resets it), then repeatedly activates the follow-up quests of every active, valid
  quest that `logic.q_isFinished` reports finished until nothing changes, then re-adds the debriefing pages; the
  first
  `quest_onLogicTick` afterwards re-adds minimap symbols; `tutorial_onLoaded` replays the pages recorded under
  `tutorialShowed<n>` [known: data].
- Side effects that `onStarted` applied directly to the simulation (resources, buildings, teams, AI switches)
  are in the save through the subsystems they changed; `onStarted` is not run again.
- A remake that keeps the original scripts must keep this contract: integers only, keyed by string, `nil` for an
  absent key, script re-run plus `onLoaded`.

## 8. Determinism notes

Map scripts are part of the simulation: `onLogicTick` runs inside the logic tick and calls functions that change
simulation state and draw from the simulation random generator.

- **Random.** `logic.getRandom` is the only script access to randomness by name; each call consumes exactly one
  value of the shared sequence ([logic-core.md](logic-core.md) §3.3). Its one call site, in the AI limiter, is never
  executed (§3.9), so the shipped scripts draw from the simulation generator only through `logic.map_createDeposit`
  (one draw per call: `C04.lua` once, `C09.lua` every 1800 ticks). `math.random` (C `rand`) is available but
  unused; it is not seeded by the game and not part of the simulation [known: data; inferred for the seed].
- **Iteration order.** The shipped scripts iterate with `ipairs` (ascending 1..n) and numeric `for` only. The one
  generic `for i, _ in t` (in `getn`) computes a maximum, so its order does not matter. No shipped script uses
  `pairs` or `next`. A remake's Lua may therefore have any hash order **for the shipped scripts**; third-party
  scripts using `pairs` would depend on Lua 5.0.2's table layout.
- **C-side iteration.** `vi_getBuildingPosition`, `vi_getFirstBuildingPosition`, `vi_forEachBuilding`,
  `pl_removeResource`, `pl_clearResource`, `pl_halfResources` and `menu.addResource` depend on the village
  vectors' order (creation order, [village-buildings.md](village-buildings.md) §2.2); the spiral functions on
  §3.6.1; the rectangle functions on x-outer / y-inner ascending order.
- **Integer truncation.** Every integer argument is truncated toward zero; `sd_setValue` truncates what it
  stores. Scripts rely on it (`showBookDelay`, the AI limiter's fractional minutes).
- **Floating point.** Lua numbers are doubles, but the game's Lua is compiled for the x87 FPU (S 005c9f80 uses
  `FMUL`/`FSTP`) and the engine sets the FPU precision control to 24 bits before every logic update
  ([logic-core.md](logic-core.md) §3.1) [known]. [inferred] arithmetic in `onLogicTick` (`ticks / 600`,
  `averageProductivity * 2`, `1 / speed`) is therefore rounded to float32 precision although stored in a double.
  The same control-word call (`Fpu_SetDefaultControlWord` S 0057b9b0) is also made in
  `CApplicationEx::Initialize` S 004075d0 **before** the script host is created and `data.lua` runs, in
  `nGame::System::HandleGameCommand` S 007845a0 and in `Lobby::CLobby::Update` S 004fb460 [known: its four
  callers]. The scripts of a world build run at 24-bit precision: the control word read through `_controlfp(0, 0)`
  on the main thread is `0xA001F` (all exceptions masked, 24-bit precision, round to nearest) at the entry of
  `onLoaded` S 005b2180 and at the entry and exit of `BuildWorld` S 00784d40, which also calls `onStarted`
  [live, 2026-10-14]. [inferred] the property scripts at start-up also run at 24-bit precision, unless a library
  call between `Initialize` and them changes the control word (they run before a debugger can attach and were not
  read live). Inside the executable nothing
  else does [known]: `__controlfp` S 006fa4ab has this one caller, there is no `FNINIT`, and every other `FLDCW`
  is an inline float-to-integer conversion or a runtime math function that restores the word it found; between
  the call in `Initialize` and `RunPropertyScript("data")` only the file scan, `GetWindowRect`, the timer and
  the script host run (S 004075d0). Outside the executable: Direct3D 9 leaves the word alone, because the device
  is created with `D3DCREATE_FPU_PRESERVE` (`behaviorFlags | 2`, `CGraphicDevice::CreateDevice` S 004d5bf0)
  [known]; `tincat3.dll` and `NxCharacter.dll` load a control word only around inline float-to-integer
  conversions and restore it, and `NxCharacter.dll`'s `__control87` has no caller [known]. The word is per
  thread, so FMOD's mixer thread does not matter. `PhysXLoader.dll` contains no `FLDCW` [known]. FMOD's API
  (`fmod.dll` is packed: 162,816 bytes on disk, 618,496 in memory, so it cannot be read statically as shipped),
  D3DX (a Windows library, effect compilation during the splash screen) and the PhysX core were not read; whatever
  they do, the word is `0xA001F` when `onStarted` / `onLoaded` run [live, 2026-10-14]. So
  `weissBeerAmount * 0.34` with `weissBeerAmount = 60` in `C02.lua` gives 20.39999961853 (float32, printed with
  `%.14g`), not the double 20.4 [inferred]. The affected values
  reach the simulation only as quest progress text (saved, displayed) and through comparisons such as
  `goodAmount >= 20.4`, where both roundings give the same integer threshold (21).
- **Number formatting.** `"%.14g"` of the C runtime (S 007ec644); integers print without a decimal point.
- **Local inputs.** `logic.getSpeed()` and `logic.pl_getUser()` are per-machine values; `quest_onLogicTick` uses
  both. Cinematics pause quest evaluation until the local UI reports `quest_cinematicDone`. Map scripts are thus
  single-machine logic: correct offline, not lockstep-safe [inferred]. The engine registers `logic` only in an
  offline session, and only campaign maps and `map\Presentation.s2m` ship a script.
- **Wall-clock waits.** `Default.Wait` is timed by frame time, not ticks (§3.3); unused by shipped scripts.
- Presentation-only parts: `cutscene`, `ui.*`, `txt`, `gfx.createParticel` (it restarts the emitter at a time value
  taken from the scene object and reseeds the emitter's parameters with a truncated float, without a call to
  the simulation generator [known] S 005aca40; [inferred] that value is the render clock),
  `menu` book / cinematic / tutorial /
  minimap functions, `editor`.

## 9. Notes for a Godot reimplementation

- **Embed a real Lua 5.0-compatible interpreter** (Lua 5.0.2 itself is small C and MIT-licensed) rather than
  translating scripts: the scripts are read from the player's install and use 5.0 syntax (`for k, v in t do`).
  If a newer Lua is used, the loader has to accept that form, provide `math.mod`, format numbers with `%.14g`
  and keep doubles (no integer subtype: 5.3+ prints `3.0` where 5.0 prints `3`, which changes quest texts and
  `sd_` keys built by concatenation).
- One interpreter state for the process, or at least the property globals copied into the match state: map
  scripts need every id and constant global of §6.2. If the rule database is converted once into a cache, cache
  the global name → value table as well (name, number).
- Open only the base, coroutine and math libraries plus the game tables, so that scripts written against the
  original behave the same (no `string`, no `table`).
- Implement the C boundary exactly (§2.2, §2.3): truncating integer conversion, `0` is true for booleans, "no
  value" on a failed guard, int32 `sd_` store, float32 for speeds and progress. Where the original would crash
  (null depot in `menu.addResource`, `nil` passed as a string, `ai_allowHarborPosition` / `ai_allowAttackingPlayer`
  for an entry that is not listed, which erases at the vector's end) a remake should fail safely and log; the shipped
  scripts do not hit these paths in a normal game [inferred].
- Reproduce the error model: run every callback protected, drop the rest of the callback on an error, keep the
  partial effects, continue next tick. Logging the error (which the original discards) is harmless.
- Call order to reproduce: top-level chunk during map load (before players exist), `onStarted` (new game) then
  `onLoaded`, both before the first tick; `onLogicTick(tick)` as the last simulation step of each tick; quest UI
  and cinematic callbacks from the UI layer. In Godot terms: `onLogicTick` belongs to the fixed simulation step,
  not to `_process`.
- Case-insensitive, backslash-tolerant resolution of `[data]\...` script paths, including the
  `[data]\game\scripts\...` form; a missing file is a silent no-op.
- Cutscene files can be converted once to a neutral track format (two key lists of `{time, vec3}` with
  cumulative times, a `relative` flag, a `loop` flag) by executing them against a recording `cutscene` table;
  info pages likewise (a list of label / picture / text entries per property id). Engine features fit directly:
  `Curve3D` / an `AnimationPlayer` track for the camera, `Control` nodes for the info pages.
- Keep `logic.getSpeed`, `pl_getUser` and the cinematic gate out of any lockstep path if the remake ever runs
  scripted maps in multiplayer.
- The functions never called by shipped scripts (§3.6 "no", `se_*`, most `ui.set*`, `editor.*` outside the
  editor) can be stubs at first; `menu.addDebriefing` / `addExtro` are no-ops in the original too.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§8): the control word is `0xA001F` (24-bit precision, all exceptions masked, round to nearest) at the entry of `onLoaded` and at the entry and exit of `BuildWorld`, which calls `onStarted`, so the scripts of a world build run at single precision [live, 2026-10-14]. The property scripts at start-up run before an attach and were not read live; inside the executable nothing between `Fpu_SetDefaultControlWord` and them changes the word | — |
| 2 | Time unit of cutscene keys (§3.8). `setRelative` is answered there: it sets a byte that nothing reads; the shift of a path comes from the cinematic page's cell | static read of the `CameraSpline` evaluation |
| 3 | Whether a `vi_forEachBuilding` callback may add or remove buildings (§3.6). The loop S 005b14c0 keeps a raw pointer into the village's building vector across the callback and re-reads only the vector's end each step [known]; [inferred] an erase in front of the pointer skips one building and a reallocation leaves the pointer dangling. Open: whether the removal functions erase from that vector at once or defer it. The shipped callbacks (`C08.lua`: `stopProduction`, `startProduction`, `create...Fire`, `create...Water`) are not meant to remove buildings | static read of the building removal path (`vi_destroyBuilding` → village erase) |
| 4 | Answered (§6.1): the info-page scripts (`scripts\info\*.lua`) never run; `nMenu::Info::Open` S 005f6310 has one reference, the direct call at S 005d9776 with mode 0 | static: references to S 005f6310 |
| 5 | Behaviour of the unused `ui.set*` widget functions and `editor.*`; the pixel reference of the `ui.*` coordinates (§3.7) | static read; low priority, no shipped map script depends on it outside the quest list |
| 6 | Answered: a network session runs a map script. `GameFile_LoadMap` S 005aa7b0 derives `<map path>.lua` and `GameScript_LoadMapScript` S 005b1fe0 runs it when the file exists, with no session test; `BuildWorld` S 00784d40 creates the map-script thread in every session and registers `logic` / `gfx` only when the session is offline (§2.1). So each peer that has the `.lua` next to its copy of the map runs it, with `logic` missing or left over from an earlier offline world. Open: what such a script does to a match (a peer without the file does not run it) | a network test with a scripted map |
| 7 | Answered: a book closed in quest-list view reopens without page text and without quest widgets. Closing deletes every script-made widget of the dialog (`Overlapped::OnHide` S 0062e0a0 clears the list at `+0xbe8`), but nothing shows the page text, the page counter and the two page buttons again (`Book::OnShow` S 005fc310 and `AddPage` S 005fcd50 do not), the toggle still reads `!STORY` and the script's `questDialogOpen` stays true. The first click on the toggle takes the "leave the quest list" branch (the page text is invisible), calls `destroyQuestUi` and shows the pages (§4.3) | static: S 0062e0a0, S 005fc310, S 005fcd50, S 005fc900, S 005fcbc0 |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 005c8ef0 | `LuaScriptHost_ctor` | creates the state, opens base + math + `Default` |
| 005c9690 | `LuaScriptHost::RunFile` | read, decrypt, compile, `lua_resume` |
| 005c9780 / 005c9840 / 005c9920 | `LuaScriptHost::CallGlobal` / `_Number` / `_XY` | protected calls of a global by name |
| 005c9a10 / 005c8c90 | `LuaScriptHost::UpdateThreads` / `YieldWait` | wait and resume by wall time |
| 005c9440 | `LuaScriptHost_DumpScriptError` | error sink (discards) |
| 005c9b30 / 005c9b10 / 005c9b50 | `Lua_ToInt` / `Lua_ToFloat` / `Lua_ToBool` | argument conversion |
| 005c9b70 / 005c9bb0 / 005c9b90 | `Lua_PushInt` / `Lua_PushFloat` / `Lua_PushBool` | result conversion |
| 005cdfb0 / 005cde50 | `LuaDefault_CallScript` / `LuaDefault_Wait` | include; wait |
| 0054f8d0 | `PropertiesDb::RunPropertyScript` | runs `data.lua` |
| 005dda30 | `nMenu::System::Initialize` | registers `menu`, `ui`, `txt`; runs `menu.cfg` |
| 00784d40 / 007834e0 | `nGame::System::BuildWorld` / `Shutdown` | world build order (§4.2); teardown caller |
| 005b2720 / 005b1ce0 | `GameScript_InitMapScript` / `GameScript_DestroyMapScript` | map-script thread lifetime, store reset |
| 005c8dc0 | `LuaScriptHost::ClearGlobalFunction` | sets a global to nil if it is a function (`createQuestUi` at teardown) |
| 005b2990 | `GameScript_RegisterLuaLibraries` | registers `logic`, `gfx` |
| 005b1fe0 / 005b1dc0 | `GameScript_LoadMapScript` / `GameScript_RunFile` | map script; info pages |
| 005aaed0 / 005aa7b0 | `GameFile_LoadImpl` / `GameFile_LoadMap` | map part, then logic part by type; derives the `.lua` path and loads the script |
| 005ac770 / 0052c270 | `Game_LoadWorldFromDescriptor` / map-type predicate | `onStarted` / `onLoaded`; new-game types 0, 1, 2, 100, 102 |
| 005b2220 / 005b2180 / 005b20d0 | `GameScript_CallOnStarted` / `CallOnLoaded` / `CallOnLogicTick` | callbacks |
| 00527070 / 004018e0 | `NLogic::System::Update` / `CApplicationEx::FrameTick_InGame` | position of `onLogicTick` in the tick; of `UpdateThreads` in the frame |
| 005b1f30 / 005b1e80 / 005b2360 / 005b2410 | `GameScript_CallCreateQuestUi` / `CallDestroyQuestUi` / `CallQuestCinematicDone` / `CallSacrificeExecute` | UI and sacrifice callbacks |
| 005fc900 / 005fcbc0 / 005faee0 | `nMenu::Book::ShowQuestView` / `Book::Update` / `nMenu::Cinematic::OnHide` | callers of the three UI callbacks |
| 00660500 | `ai::logic::Sacrifice::ApplyEffect` | effect kind 1006 calls `sacrifice_execute` |
| 005af860 | `GameScript_CallLuaFunctionXY` | `fn(x, y)` callback of `vi_forEachBuilding` |
| 004c44a0 / 004b12d0 / 004b1470 | `LuaUi_CallScriptFunctionIfDefined` / `nUi::Button::OnClicked` / `OnPressed` | button events |
| 005af810 / 005af830 | `GameScript_IsFunctionDefined` / `GameScript_CallFunction` | button-event lookup and call (path test in the second) |
| 005b28b0 / 005b24d0 | `GameScript_Lua_sd_setValue` / `sd_getValue` | script data store |
| 005b0f30 / 005b2780 | `GameScript_Store` / `GameScript_Load` | save section |
| 005ac8f0 / 005ac9c0 | `LuaGame_IsValidMapCellArg` / `LuaGame_IsValidPlayerArg` | shared guards |
| 005ad6d0 / 005ad6f0 / 005ad710 | `getTick` / `getSpeed` / `getRandom` | time, speed, random |
| 005af910 / 005b1290 / 005afaa0 | `map_removeDoodads` / `map_forEachDoodad` / `map_searchConstructionPlace` | hex spiral users |
| 0052dd80 | `ConstructionFlags_MatchesPlaceKind` | size mask test |
| 005b1670, 00536330, 00536390, 00536310 | `q_add`, `Quest::Init`, `Quest::SetText`, `Quests::ClearQuestSlot` | quest slots |
| 005b05d0 / 005acc10 / 005b0d90 | `pl_removeResource` / `pl_clearResource` / `pl_halfResources` | depot stock changes |
| 00558730 / 00558890 | `NVillage::System::FindCompletedBuildingOfPlayerInList20` / `FindBuildingAtOrNearest` | first finished building of the player in the village list at `+0x20` (the depot the resource functions use); building at a cell, or the nearest within a radius |
| 005d9970, 005d9a30, 005d9ac0, 005dada0 | `menu.addResource`, `createBuilding`, `createBuildingWithSettler`, `createStreet` | unguarded world edits |
| 005dd3c0 / 005dd410 / 005dd5c0 | `menu.startCinematic` / `addCinematicPage` / `updateCinematic` | cinematics |
| 005fb3e0 / 00782bb0 | `nMenu::Cinematic::Update` / `nGame::System::EndCinematic` | cinematic phases and page timing; the simulation switches back on (sole caller: the ending phase) |
| 00535d70 | `VictoryCond_Update` | quest 0 at tick 0; mode 5 local quest test |
| 00529040 / 00654bd0 / 00668be0 | `TransferPlayerAssets` / `RemoveSettlersOfPlayer` / `Street::SpawnCarrier` | `pl_changePlayer`: assets moved, settlers removed per kind vector, streets rebuilt with a carrier on the middle cell |
| 00533160 | `GetAverageBuildingProductivity` | `pl_getBuildingProductivity`, ascending unique-id order |
| 005aff90 / 005af1a0 / 005ac8d0 | `na_isShipAtRoutePosition` / `na_sinkShipOnRoute` / ship state 6..8 test | route comparison; sinking skips states 6..8 |
| 005b9920 | `Movement::MoveToTile` | `na_sendShip`; `UnmarkTile` inlined before `MarkTileAndMoveTo` |
| 005ae830 / 005aea40 / 00565550 | `vi_changePlayerOfBuilding` / `vi_addGoodsToDepot` / `Production::ProducesGoods` | conquest by cell; depot byte +0x54; production gate of `vi_enableProduction` |
| 005ada40 / 005b2660 / 005add10 | `ai_isEnabled` / `ai_enable` / `ai_disable` | computer player on / off |
| 00581c40 | `NAI::System::ActivatePlayer` | `ai_enable` back end |
| 005add70 / 005ade50 / 005addd0 | `ai_allowAttack` / `ai_setAllowedAttackCount` / `ai_setAttackEnable` | attack switch and AttackSystem limiter (military system +0x144) |
| 005adec0, 005adf20, 005adf80, 005adfe0, 005ae040, 005ae100, 005ae0a0 | `ai_enableExpansion`, `ai_enableNeeds`, `ai_enableCoinProduction`, `ai_enableForesting`, `ai_enableCatapultsLocal`, `ai_enableShipConstruction`, `ai_enableSacrifices` | computer player switches (`Lua_ToBool`) |
| 005ada90 / 005824b0 | `ai_forbidHarborPosition` / its append | forbidden harbour vector, duplicates kept |
| 005adb50 / 005824c0 / 00674ed0 | `ai_allowHarborPosition` / its erase / `Stl_VectorMapPos_EraseValue` | first equal entry erased, no not-found test |
| 005adc10 / 00584840 / 005c09b0 | `ai_forbidAttackingPlayer` / `AddEnemyExclusion` / `NPlayer::Military::SetFlag` | exclusion appended; the game player's ignore-distance flag set |
| 005adc90 / 00583650 | `ai_allowAttackingPlayer` / `RemoveEnemyExclusion` | first entry erased, flag cleared, no not-found test |
| 0078ac10 / 0078a940 | `CutsceneCamera::LoadScript` / `Cutscene_BuildScriptPath` | cutscene files |
| 0078a5b0 / 0078a660 | `cutscene.addPosition` / `addLookAt` | camera keys |
| 005f6310 / 005d96e0 | `nMenu::Info::Open` / `nMenu::System::ToggleDialogInfo` | info page scripts (modes 1, 2); the only caller (mode 0) |
| 005ab800 | `GameData_ComputeBuildChecksum` | `[data]\scripts` + `*.lua` in the build checksum |
| 005d0bf0 | `luaV_tostring` | `%.14g` number formatting |
| 005c9f80 | `math_deg` | evidence of x87 arithmetic in the Lua build |
| 0057b9b0 | `Fpu_SetDefaultControlWord` | 24-bit precision control (§8) |
