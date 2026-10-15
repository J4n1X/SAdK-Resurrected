# Remake: the Lua surface for map scripts (and the data stage)

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). What the remake's Lua layer must
provide so that:

1. `core.game` runs the original's property scripts in the data stage and gets the original's registry
   ([binding] architecture §8);
2. the original's map scripts (the campaign, its tool libraries, the cutscene paths) run unchanged and produce the
   original's results;
3. new maps and mods can script against a surface that is safe in lockstep.

It maps the original's surface onto the remake: the runtime and its number model, the converter, the script states
and when each piece runs, every function table with its class and the remake service behind it, the callbacks, the
save contract, and the extension points. It does not repeat what is already specified: the function lists with
addresses are in [`../lua-surface.md`](../lua-surface.md), the behaviour of every binding in
[`../sim/lua-runtime.md`](../sim/lua-runtime.md), the property setters in
[`../sim/properties-data.md`](../sim/properties-data.md).

Tags: **[binding]**, **[draft]**, the source tags of the cited documents; **[data]** = counted in the decrypted
scripts of the reference installation on 2026-10-15; **[binary]** = read in the binary for this design (Ghidra,
2026-10-15). LS = `../lua-surface.md`, LR = `../sim/lua-runtime.md`.

## 1. What is fixed [binding]

- A pure C# Lua implementation from a package, not a native library (architecture §10).
- A converter rewrites the original's Lua 5.0.2 scripts once, at the first start, for the package's dialect; map
  scripts when the map is first loaded.
- Lua numbers round like the original's: every arithmetic result in single precision, at least for scripts that
  change simulation state.
- Simulation scripts see ordered iteration only (architecture §3, §7).
- The engine owns the runtime and the API mechanism; `core.game` defines the `logic.*` functions (architecture §4).

## 2. The runtime

### 2.1 Package: MoonSharp, in a fork of our own [draft]

**MoonSharp** (Lua 5.2 dialect, pure C#, BSD 3-clause) fits best:

| Need | MoonSharp |
|---|---|
| deterministic iteration | a table keeps one insertion-ordered linked list behind all its keys; `pairs` and `next` walk it, so the order does not depend on .NET's per-process string hashing [checked in its source, `Table.cs`] |
| the original's one 5.0-only construct, `for k, v in t do` | not accepted at run time: the 2.0.0 package fails with "attempt to call a table value" [tested 2026-10-15], so the converter rewrites it (§3.2) |
| run-time evaluation of constant expressions, as Lua 5.0 does | no constant folding [checked, `BinaryOperatorExpression`] |
| a place to round arithmetic to single precision | the seven arithmetic instructions `ExecAdd`, `ExecSub`, `ExecMul`, `ExecDiv`, `ExecMod`, `ExecPower`, `ExecNeg` of the VM, plus `BinaryOperatorExpression.Eval` for dynamic expressions [checked] |
| sandbox | core modules are chosen per script (no `io`, `os`, `debug`, `loadlib`) |
| coroutines, yielding from C# | yes |

It has to change in four places, so the remake uses it **as source in a fork** (`Sadk.Lua`) instead of the binary
package; its upstream is dormant, so a fork costs little:

1. the number model hook in the arithmetic instructions (§2.5);
2. number-to-string conversion: MoonSharp formats with .NET's `double.ToString`, and one path (`CastToString`) uses
   the **current culture** (a German Windows would print `20,4`) [checked]; the fork uses the original's `%.14g`
   everywhere (§2.5);
3. string literals: MoonSharp rejects unknown escapes (`\s` is a syntax error) while Lua 5.0 drops the backslash
   [checked]; handled by the converter (§3.2), the fork only reports the original line;
4. `tostring` of tables and functions gives a stable per-object number instead of an address.

The `original` profile must also provide what 5.0 has and MoonSharp lacks: the global `__pow` (the converter's
target for `^`), and, for third-party scripts, `table.getn`, `math.mod`, `loadstring`, `gcinfo`, `string.gfind` and
`setfenv`, which no shipped script calls [tested 2026-10-15]. The converter's `arg` prologue calls `select`, which 5.0
does not have; a 5.0 script that defines a global `select` of its own would break it.

Alternatives considered: **Lua-CSharp** (Lua 5.2, active, async-based; its table iteration order would need the
same check and probably the same change) and **a port of Lua 5.0.2 to C#** (exact, even the original's hash order
for `pairs`, but the most work; the fallback if third-party scripts ever depend on the original's hash order, §8.4).
**Decided by the maintainer 2026-10-15: MoonSharp in a fork of our own.**

### 2.2 Script states [draft]

| State | Lives | Runs | Libraries |
|---|---|---|---|
| **data stage** | one per data-stage run | the converted property scripts (`data.lua` and the 21 it loads), mods' `data*.lua` | `properties`, `registry`, `Default`, base, `math` (original profile) |
| **match** | one per match, created at world build | the map script, its tool libraries (`mapTools`), every callback, every UI-raised script callback (as commands, [sim-boundary.md](sim-boundary.md) §7) | `logic`, `gfx`, `menu`, `ui`, `txt`, `Default`, base, `coroutine`, `math`; the remake profile adds `sadk`, `string`, `table` (§2.4) |
| **recording** | short-lived | cutscene paths, `menu.cfg`, info pages, editor brushes: scripts that only describe data | a recording table per kind (`cutscene`, `menu`, `ui`) |

The original runs everything in one `lua_State` for the whole process; globals of one match survive into the next
(LR §2.1). The remake gives every match a fresh state, because a replay, a reload and a peer joining must all start
from the same script state.

**The vocabulary.** Map scripts pass the ids and enum values that the property scripts assign to globals
(`woodCutter`, `SizeLarge`, `Ware`, `doodad_chest`; LR §6.2), and may call the helper functions those scripts
define. A new match state therefore **replays the data stage's scripts**: it runs them again with a `properties`
table in replay mode, where every `*_create` returns the id recorded for that call in the data stage and every other
call does nothing. The replay checks that the sequence of create calls matches the recording; a difference stops
the match (the data stage was not deterministic). It costs milliseconds and reproduces the vocabulary exactly,
helper functions included.

### 2.3 Profiles [draft]

A script runs in one of two profiles, chosen per map (`scriptApi` in `map.xml`, [assets.md](assets.md) §7) and per
mod library:

| | `original` (default for converted maps and for the property scripts) | `remake-1` |
|---|---|---|
| language | Lua 5.0 as converted (§3) | MoonSharp's Lua 5.2 dialect |
| standard libraries | base, `coroutine`, `math` with the 5.0 names (`math.mod`, the global `__pow`) | plus `string`, `table`; `math` without `random` / `randomseed` (use `sadk.random`) |
| game tables | the original's, with the original's semantics (§5, §6) | the same, plus `sadk` (§9) |
| `pairs` order | insertion order (the original's hash order is not reproduced, §8.4) | insertion order |
| number model | single precision (§2.5) | single precision |

### 2.4 Sandbox [draft]

No `io`, `os`, `debug`, `loadlib`, `dofile`, `loadfile`, `require` of files outside the virtual file system. The
original has `dofile`, `loadfile` and `require` but they use C `fopen` without the `[data]` resolution, so no game
file can be loaded with them (LS §2.1); the remake's `original` profile keeps them as functions that log and fail.
`collectgarbage` and `gcinfo` return constants in the match state (memory figures differ per machine). `print` and
`Default.WriteToLog` go to the log, with the script's file and line.

### 2.5 Numbers [draft]

The original runs scripts with the x87 control word at 24-bit precision (`0xA001F` at `onLoaded` and in the world
build [live, 2026-10-14]; LR §8): every arithmetic result is rounded to 24 significant bits and stored as a double.
The remake reproduces that in the data-stage and match states:

- **Arithmetic**: `+ − * / %` and `^` produce the exact result rounded **once** to a 24-bit significand, with the
  double's exponent range (the x87 keeps its wide exponent while rounding the significand). C#'s `(float)(a * b)`
  rounds twice (to double, then to float) and differs where the double result falls exactly on a float midpoint; the
  hook computes the double result together with its exact error term (`Math.FusedMultiplyAdd` for `*` and `/`, the
  two-sum for `+` and `−`) and uses the error's sign to break such ties. Unary minus is exact.
- **Literals**: decimal → double, as the original's `strtod`; whether `strtod` itself depends on the precision
  control is open (LR notes; a literal used without arithmetic would show it).
- **At the C boundary**: `Lua_ToInt` truncates toward zero; out of range gives `int.MinValue` (the x86 "integer
  indefinite"); `Lua_ToFloat` is `(float)`; `Lua_PushFloat` widens float to double; `Lua_ToBool` makes the number 0
  true (LR §2.2).
- **Formatting**: `%.14g` of the C runtime, integers without a decimal point; quest progress texts and `sd_` keys
  built with `..` depend on it (LR §3.1). .NET's `"G14"` gives the same digits; the exponent form differs
  (`1e+015` in the original's runtime, `1E+15` in .NET), which no shipped value reaches.
- **Consequences in the shipped data** [data]: five hidden sub-quest amounts differ between double and single
  precision (C02 `× 0.34` and `× 0.67`, C03 `× 0.3`, `× 0.4`, `× 0.9`): the saved progress text reads
  `…/20.39999961853` in the original; no threshold changes. `showBookDelay − 1/speed` with the only value ever set,
  2 000 000 000, rounds back to 2 000 000 000, so the stored value never falls (LR §3.9 describes the double
  behaviour). Integers are exact only up to 2²⁴ in computed results.

### 2.6 Random numbers [draft]

- `logic.getRandom(max)`: one draw from the simulation generator, `value % (max + 1)` with signed division (LR
  §3.6); `max = −1` is a Lua error instead of the original's division by zero.
- `math.random` in the `original` profile: a separate deterministic stream seeded from the game seed
  (`ScriptRandom`, [sim-boundary.md](sim-boundary.md) §8), so the simulation generator's sequence stays the
  original's. The original uses C `rand()`, unseeded and shared with audio; no shipped script calls it [data].
- `remake-1`: `sadk.random(n)` draws from the simulation generator, explicitly.
- Script-caused simulation draws in the shipped data come only from `logic.map_createDeposit` (one per call; C04
  once, C09 every 1800 ticks); `logic.getRandom` has one call site, in the AI limiter, whose setup is commented out
  in every map [data].

### 2.7 Errors [draft]

The original's model, reproduced exactly, and logged (the original discards every message, LR §3.4):

- every call into Lua is protected; an error aborts the running callback **at the failing statement**; effects made
  before stay; the next call starts normally;
- an error inside a `forEach` callback ends that invocation only; the C loop continues;
- an error in a file run by `Default.CallScript` ends that file; the including script continues;
- a compile error leaves every callback undefined; each call then fails silently, every tick.

Where the original **crashes** instead (`nil` where a string is needed, `menu.addResource` for a player without a
finished depot, an index ≥ 8, `ui.show` with an unknown name, more than 20 book pages, `pl_getProducedGoodCount` for
a good outside the tribe's lists, a negative spiral radius, which hangs [binary]), the remake raises a Lua error with
the same abort semantics and logs it. Shipped scripts do not take these paths in a normal game (LR §9).

The log line names the script, the converted and the original line, the callback and the tick. The debug overlay
counts errors per callback.

### 2.8 Waits and coroutines [draft]

`Default.Wait(seconds)` waits by wall clock in the original, resumed between ticks (LR §3.3): not reproducible even
by the original itself. No shipped script calls it [data]. The remake waits by **ticks**:
`ceil(seconds × 10)` ticks at the tick rate of speed 1; resumed inside the tick, right before `onLogicTick`, in
the order the waits began. Only the map script's top-level chunk and coroutines the script made itself can yield;
inside a callback a wait is a Lua error, as in Lua 5.0.2 (LR §3.3).

## 3. Converting the original's scripts

### 3.1 What [draft]

All 355 `.lua` files and `menu.cfg` (20 913 lines, all CRLF) [data], at the first start, into the converted tree
([assets.md](assets.md) §6.1); map scripts and cutscene paths into their map packages. The original text is kept
beside the converted one (`<path>.orig`) for error reports.

Implemented (sadk-remake `Sadk.Formats/Lua`, `Sadk.Convert/Jobs/LuaJob.cs`, 2026-10-15): all 356 chunks convert;
the 159 the map packages do not take go into the converted tree, the 197 map scripts and cutscene paths into the map
packages; every converted chunk compiles on MoonSharp 2.0.0; 354 come out byte for byte unchanged.

### 3.2 How [draft, implemented]

A real Lua 5.0 lexer, never regular expressions: 41 string literals contain `--`; 98 comments sit directly against a
call's `)`, 91 of them in `buildings.lua` [data]. Behind the lexer a parser of the whole 5.0 grammar (no code
generation) rejects what 5.0 rejects (`return` or `break` not last in a block, `break` outside a loop, assignment to
a call, a call whose `(` starts a new line, nesting deeper than 200), so a chunk the original could not have run fails
its conversion with 5.0's message and line. Rewrites, all token-level so that every line keeps its number:

| Construct | Shipped data [data] | Rewrite |
|---|---|---|
| `for k, v in t do` over a table | 1 (`tools.lua:19`, in `getn`; order-independent: it computes a maximum) | `for k, v in next, t do` when the expression list is one expression that is not a call (5.0 decides at run time; a table is what such an expression yields); required, MoonSharp fails on the bare form |
| string escapes | only `\\` and 13 `\n` | every literal decoded with 5.0's rules (an unknown escape drops the backslash, `\ddd` decimal) and re-emitted with `\ddd` escapes where needed |
| bytes above 0x7F | 7 literals in `patterns.lua` | files are read as bytes and decoded as Latin-1 (one byte, one character); bindings that take names pass them back as the same bytes |
| `a ^ b` | 0 | a call of the global `__pow(a, b)`: in 5.0 `^` calls that global |
| `%`, `#`, `...` as an expression | 0 (syntax errors in 5.0) | reported as errors; MoonSharp would accept them |
| long strings `[[ ]]` | 0 | kept, with `=` levels added where 5.0's nesting puts a `]]` inside; one that holds a CR or a byte above 0x7F becomes a short string with `\` + line feed at each line break |
| a table constructor starting with `;` (`{;}`) | 0 | the `;` becomes a space |
| a numeral directly followed by a name (`0x10` is `0` and `x10` in 5.0) | 0 | a space between them |
| comments whose brackets mean something else in 5.2 (a nested `--[[ ]]`, a line comment starting `--[=[`) | 0 | adjusted |
| names that are keywords in 5.2 (`goto`) | 0 | renamed with a fixed prefix |
| `arg`, `...` | 0 | in a vararg function that reads `arg`: `local arg = {...}; arg.n = select("#", ...);` after its `)` |

Nothing else in the shipped data is specific to Lua 5.0 [data]: no `pairs`, `next`, metatables, coroutines, closures
(all 414 functions are global functions at file top level), method calls, long strings, hex literals,
`string` / `table` library calls. The standard functions used are `ipairs` (55), `type` (4), `math.floor` (1).

The same converter runs on third-party scripts written for the original (maps from the community, sadkmod property
mods); it reports constructs it had to rewrite.

### 3.3 The property scripts in the data stage [draft]

- `core.game`'s definitions sub-stage runs `data.lua`, which loads the 21 others with `Default.CallScript` in their fixed
  order (`defineTribes`, `doodads`, `goods`, `config`, `patterns`, `animals`, `jobs`, `deposits`, `remains`,
  `buildings`, `sacrifices` with `_goodExchange` and `_campaign`, `signs`, `military`, `ship`, `sounds`, `ai`,
  `harbors`, `tribes`, `spawnpoints`; LR §4.1). File names resolve case-insensitively by name (`goods` →
  `Goods.lua`).
- The 243 `properties.*` bindings (224 of them called by the shipped scripts, 7 739 call sites [data]) are C# in
  `core.game` (`Core.Game`), with the original's conventions (LR §3.5): `X_create("hex")` parses up to 32 hex digits, creates the
  record with the original's defaults (`../sim/properties-data.md`) and returns the id as a signed number; setters and
  adders return nothing; `pa_create` over an existing id replaces the record, losing every earlier value, as the
  original does; a setter on an id that was never created is a Lua error (the original crashes or silently creates a
  default record, depending on the table).
- **Registry keys** come from the globals ([mods.md](mods.md) §6.4): during the data stage the globals table has a
  `__newindex` hook; the first global that is assigned the id of a create call not yet named gives the entry its
  key (`brauhaus = properties.bp_create("...")` → key `brauhaus`). An entry no global names gets `<kind>_<hex id>`.
- The order of create calls is recorded for the vocabulary replay (§2.2) and for the registry's definition order.
- Property mods for the original run unchanged as `data-updates.lua` of a remake mod that requires `core.game`; they see its globals, as
  they do under sadkmod today (`../data-loading.md` §1).

## 4. Map scripts: when what runs

### 4.1 World build [draft]

The original's order (LR §4.2), with the remake's state handling:

1. A new match state; the vocabulary replay (§2.2); the libraries registered (§5, §6); the `sd_` store emptied.
2. The map's world part is loaded (map info, terrain, resources, doodads, ambients, navy, spawn points).
3. The map script is located (`script/<name>.lua` in the map package; for an original map the `.lua` with the map's
   internal name) and its **top-level chunk runs**, before any player exists and, for a save, before the saved
   players and `sd_` values are read. A map without a script skips every callback.
4. New game: players created from the match setup; then **`onStarted()`**. Save: the logic part read, the `sd_` store
   and the 40 quest slots restored.
5. Always: **`onLoaded()`**. Both run before tick 0 with `logic.getTick() == −1` for a new game, so `q_add` posts
   no message there.

### 4.2 Every tick [draft]

`ScriptTickSystem` is the **last** system of the tick, after the victory update [binding] architecture §7; LR §4.3:
first the waits that are due (§2.8), then `onLogicTick(tick)` with the number of the tick just executed. Everything
it does is part of the tick on every machine. Script calls that `forEach` functions make by name run synchronously
inside the binding, with the global looked up at each hit (LR §9.4).

### 4.3 Callbacks raised by the UI [draft]

`createQuestUi`, `destroyQuestUi`, `quest_cinematicDone`, `<widget>_isClicked`, `<widget>_isPressed` (LR §4.3, §4.4)
arrive as the command `ScriptCallback(name, player)` and run between two ticks in the match state, on every machine
([sim-boundary.md](sim-boundary.md) §7). Offline this is when the original runs them. In multiplayer every peer runs
them at the same point, so script globals they change (`questDialogOpen`, `questCinematicRunning`) stay equal on every
machine. UI functions they call produce `ScriptUi` events for the player who raised the callback.

The end of a cinematic is the command `CinematicFinished`; it runs `EndCinematic` (AI, chests, sacrifices back on,
sacrifice ticks shifted) and then `quest_cinematicDone`.

### 4.4 Teardown [draft]

The match state is dropped. The original only clears `createQuestUi` and keeps every other global for the next map
(LR §4.2); the fresh state per match makes that moot.

### 4.5 Multiplayer [draft]

| Session | Libraries | Map scripts |
|---|---|---|
| offline (any mode) | all | run as specified |
| compatibility mode with original clients | **no `logic`, no `gfx`**, as in a freshly started original process (the original registers them only offline; a leftover table from an earlier offline game would make peers diverge by process history [binary]) | the top-level chunk and the callbacks run; every `logic.x` call fails as in the original; the unguarded `menu.*` world edits run. The remake warns before such a match starts. **Or refuse scripted maps there: decision for the maintainer** |
| remake peers only (refined or not) | all | run on every peer inside the tick; the map script is part of the map's content hash ([assets.md](assets.md) §7); `pl_getUser` and `getSpeed` follow §5.1; cinematics end by the rule of [sim-boundary.md](sim-boundary.md) §11 item 1 |

The original's map scripts are single-machine logic (LR §8): quest targets evaluate `pl_getUser()` (37 call sites
[data]), the quest machine waits for the local cinematic, scenario victory declares the local player the winner.

### 4.6 Path resolution [draft]

- `Default.CallScript(path)` and the cutscene names of `menu.addCinematicPage` take the original's `[data]\...` paths
  (also `[data]\game\scripts\...`, a folder that does not exist, and cutscene paths into the wrong folder; LR §3.2).
  The compatibility resolver applies the original's rule: lower-case, `/` = `\`, the file name looked up in a
  file-name index over all layers of the virtual file system; the folders decide only between equal names; a missing
  file runs an empty chunk ([assets.md](assets.md) §5.4).
- `remake-1`: `require("quests")` resolves module names in the map package's `script/` folder, then the mods'
  `scripts/` folders in load order, then the converted installation's `scripts/mapTools/`.
- An included file runs in the same state, with the same globals (the original: a new thread of the same
  `lua_State`, LR §3.2).

## 5. The simulation tables

### 5.1 Conventions for every binding [draft]

From LR §2.2 and §2.3, implemented once in the binding helpers so no binding gets them wrong:

- arguments: `Int` (truncation toward zero; `nil`, booleans, tables and non-numeric strings are 0), `Float`
  (`(float)`), `Bool` (only `nil` and `false` are false; **0 is true**), `String` (numbers converted with `%.14g`;
  `nil` is a Lua error where the original crashes); extra arguments are ignored;
- results: **no value** on a failed guard (`nil` in an expression, so `x == false` is not satisfied), never `false`
  or 0; positions as two integers `x, y`; players 0-based slot indices 0..7; types as the original's signed 32-bit ids
  (resolved through the id table `core.game` keeps, [mods.md](mods.md) §6.4);
- guards: player `(uint)p < 8` and active; AI player active; cell inside the map; quest slot `< 40` and in use.

**Classes** of the tables below:

| Class | Meaning |
|---|---|
| SIM | changes simulation state; runs inside the tick on every machine |
| Q | deterministic read |
| Q/cache | read of a cache the simulation refreshes on a phase (the per-player recount every 22 ticks, statistics samples): the staleness is part of the behaviour and is kept in compatibility mode |
| RNG | draws from the simulation generator |
| LOCAL | depends on the machine in the original; defined deterministically in the remake |
| MSG | posts player messages (presentation, saved per player) |
| UI | presentation only: the binding emits a `ScriptUi` event |

### 5.2 `logic` and `gfx` [draft]

102 + 1 functions (LS §3.6); the semantics are LR §3.6 and §3.7. The remake implements them in `core.game` over
the simulation's services. "Calls" counts the call sites in the shipped scripts [data], comments included; a
function without calls is implemented with the same guards and results, but tested only by unit tests.

**Time, random, local values**

| Function | Class | Remake | Calls |
|---|---|---|---|
| `getTick()` → int | Q | the tick counter; −1 before tick 0 | 4 |
| `getSpeed()` → number | LOCAL | offline: the game speed as the original (0 paused, 1..3, cinematic blend); multiplayer: the speed set by the speed command | 1 |
| `getRandom(max)` → int | RNG | §2.6 | 1 (inert) |
| `pl_getUser()` → int | LOCAL | offline: the local human's slot (first active slot with a human controller, else 0), as the original; multiplayer: the human player who raised the current UI callback, otherwise the lowest-index human slot, with a warning once per map | 37 |
| `victory_setupQuests()` | SIM | victory mode 5 (the main quests decide the match); in multiplayer evaluated per player instead of for the local player only | 1 |

**Players** (`pl_`; service `IPlayers`, `IStatistics`, `IFights`, `ISacrifices`, `IVillage`, `IPlayerAssets`)

| Function | Class | Notes for the remake | Calls |
|---|---|---|---|
| `pl_getGoodAmount`, `pl_getMobileGoodAmount`, `pl_getBuildingCount`, `pl_getConstructionCount` | Q/cache | read the 22-tick recount caches (phase `index × 2`; stocks at phase 0, building counts at phase 1): a script's own stock change is invisible until the next recount | 7, 3, 2, 2 |
| `pl_getRegionSize`, `pl_getMilitaryStrength` | Q/cache | statistics samples | 1, 3 |
| `pl_getStreetCount`, `pl_getProducedGoodCount`, `pl_getBuildingProductivity` | Q | the produced count of a good outside the tribe's lists is a Lua error (the original aborts the process) [binary]; productivity × 100 in single precision, truncated | 1, 1, 1 |
| `pl_hasCastle`, `pl_hasReachedPlayer`, `pl_getReachedPlayerPosition`, `pl_isPlayerSpotted`, `pl_getTribe`, `pl_isAttacking`, `pl_isUnderAttack`, `pl_getPositionUnderAttack` | Q | as LR §3.6; positions push nothing when absent | 2, 2, 1, 0, 0, 2, 1, 2 |
| `pl_getSacrificeState` | Q | the delivered fraction of an ordered sacrifice; **nothing** when no building has it in delivery state (scripts compare with `>= 1` and abort there) | 2 |
| `pl_sacrificeStarted`, `pl_sacrificeStartedOnContinent` | Q | the second pushes `true` or nothing, never `false` | 2, 1 |
| `pl_changeTeam`, `pl_changePlayer`, `pl_setName` | SIM | `pl_changePlayer` moves buildings, flags, roads and ships and removes the old owner's settlers in the original's step order (unique ids are drawn in that order) | 17, 3, 2 |
| `pl_clearResource`, `pl_halfResources`, `pl_removeResource` | SIM | the first finished depot of the player in village list order; `halfResources` divides every entry, integer division | 4, 22, 11 |
| `pl_sendOrderSacrificeMessage` | MSG | to every player except `p` | 1 |

**Map** (`map_`; `ITerritory`, `IExploration`, `IConstructionMap`, `IDoodads`, `IDeposits`, `IChests`)

| Function | Class | Notes for the remake | Calls |
|---|---|---|---|
| `map_getTerritoryPlayerId` | Q | the owner of the cell | 3 |
| `map_exploreArea` | SIM | reveals for `p` and its allies; never column 0, the last two columns, row 0, the last two rows | 4 |
| `map_exchangePatternType` | SIM | pattern `from` → `to` in the bounding rectangle; construction flags and obstructed doodads follow | 6 |
| `map_createDoodad`, `map_removeDoodads`, `map_forEachDoodad` | SIM | a blocking doodad rebuilds continents and refreshes the AI; the spiral order of LR §3.6.1; a negative radius is a Lua error (the original hangs) [binary] | 4, 10, 0 |
| `map_searchConstructionPlace` | Q | first spiral cell matching the size mask (LR §3.6.2) | 2 |
| `map_createDeposit` | SIM, RNG | one draw; growth 1.0 when `full`, else the deposit's start size [binary, confirming LR §3.6] | 2 |
| `map_killDeposits`, `map_createChest` | SIM | rectangle x outer, y inner, ascending | 2, 0 |

**Computer players** (`ai_`; `IAiPlayers`; all switches are saved and hashed)

| Function | Class | Calls |
|---|---|---|
| `ai_isEnabled` | Q | 1 |
| `ai_enable`, `ai_disable` | SIM | 4, 4 |
| `ai_allowAttack`, `ai_setAllowedAttackCount`, `ai_setAttackEnable` | SIM | 5, 1, 0 |
| `ai_enableExpansion`, `ai_enableForesting`, `ai_enableSacrifices`, `ai_enableShipConstruction`, `ai_enableNeeds`, `ai_enableCoinProduction`, `ai_enableCatapultsLocal` | SIM | 8, 1, 4, 12, 0, 0, 0 |
| `ai_forbidHarborPosition`, `ai_allowHarborPosition`, `ai_forbidAttackingPlayer`, `ai_allowAttackingPlayer` | SIM | 2, 1, 6, 0 |

**Buildings** (`vi_`; `IVillage`, components `IStorage`, `IProduction`, `IVillageSacrifice`)

| Function | Class | Notes for the remake | Calls |
|---|---|---|---|
| `vi_isBuildingAtPosition`, `vi_getBuildingPosition`, `vi_getFirstBuildingPosition`, `vi_countMilitaryBuildings`, `vi_allBuildingsDestroyed`, `vi_isMilitaryBuildingAtContinent`, `vi_isSacrificeBuildingAtContinent` | Q | the village's all-buildings vector in creation order (conquered buildings at the end) | 4, 7, 4, 1, 1, 4, 1 |
| `vi_forEachBuilding` | depends on the callback | iterates a **copy** of the matching buildings, so a callback that removes buildings cannot invalidate the walk (the original keeps a raw iterator, LR §10 Q3); the shipped callbacks remove nothing, so results are the same | 14 |
| `vi_destroyBuilding`, `vi_destroyBuildingsInArea`, `vi_changePlayerOfBuilding` | SIM | immediate removal (C05's `destroySprings` loops until the building is gone) | 8, 3, 0 |
| `vi_addGoodsToDepot`, `vi_enableProduction`, `vi_orderSacrifice`, `vi_startSacrifice` | SIM | `vi_enableProduction` is the same toggle as the command `0x2000A` | 11, 4, 5, 1 |

**Ships** (`na_`; `INavy`)

| Function | Class | Calls |
|---|---|---|
| `na_getShipCount`, `na_isShipAtPosition`, `na_isShipOnRoute`, `na_isShipAtRoutePosition` | Q | 1, 1, 1, 2 |
| `na_createShip`, `na_sendShip`, `na_sinkShipOnRoute`, `na_destroyShip` | SIM | 7, 2, 1, 0 |

**Script data and quests** (`sd_`, `q_`; `IScriptData`, `IQuestLog`)

| Function | Class | Notes for the remake | Calls |
|---|---|---|---|
| `sd_setValue(key, value)`, `sd_getValue(key)` | SIM, Q | an ordered map string → int32 (byte-wise key order); the value is truncated; no delete; absent key → nothing | 5, 4 |
| `q_add`, `q_remove`, `q_finish`, `q_failed`, `q_reset`, `q_hide`, `q_updateInfo` | SIM + MSG | 40 slots (LR §2.5); messages go to every human player (the original: to the local player); `q_add` keeps a reused slot's old text | 1, 1, 1, 1, 1, 1, 3 |
| `q_isValid`, `q_isVisible`, `q_isFinished`, `q_isFailed` | Q | | 3, 1, 9, 2 |

**Settlers and NPCs** (`se_`): seven functions, every shipped call commented out (LR §3.6); implemented with their
guards over `ISettlers` and the NPC component.

**`gfx.createParticel(effect, x, y [, dx, dy, dz])`** — UI: a `ScriptUi` particle event at the cell's world position
(3 calls; C08 starts its sabotage fires every tick from `vi_forEachBuilding` callbacks). Not saved: scripts restart
looping effects in `onLoaded`.

### 5.3 `menu` functions that change the simulation [draft]

Registered in every session in the original and unguarded (LR §3.7; a wrong player index or a player without a
finished depot crashes it). The remake guards them and raises a Lua error instead.

| Function | Class | Notes | Calls |
|---|---|---|---|
| `menu.addResource`, `menu.clearResources` | SIM | the first finished depot of the player | 2, 1 |
| `menu.createBuilding`, `menu.createBuildingWithSettler` | SIM | placed and completed; with settler: worker, or three soldiers for territory buildings; territory source first | 2, 9 |
| `menu.createStreet` | SIM | planner then build | 1 |
| `menu.lockBuilding`, `unlockBuilding`, `lockJob`, `unlockJob`, `lockSacrifice`, `unlockSacrifice` | SIM (not saved) | the player lock maps; scripts re-apply them in `onLoaded` | 3, 0, 0, 0, 1, 0 |
| `menu.addSacrifice(p, s, notify)` | SIM + MSG | offer list (not saved); the campaign passes `true` from quest callbacks, so the message is sent, and `false` from `onLoaded` [data] | 5 |
| `menu.startCinematic` | UI + SIM | opens the cinematic screen and runs `BeginCinematic` (AI, chests off, `cinematicActive`, sacrifices paused) inside the calling tick; the end comes back as `CinematicFinished` (§4.3) | 1 |

## 6. The presentation tables

### 6.1 How they work [draft]

The simulation never draws. Each presentation binding emits a `ScriptUi` event addressed to a player (the player who
raised the current UI callback, else every human player); the presentation of that player shows it. In a headless
run they do nothing. They are cheap to call and never fail for presentation reasons; what the original does with a
wrong widget name (crash) becomes a logged warning.

| Table, functions | Remake | Calls |
|---|---|---|
| `menu.createLetter(text)` | a letter message | 1 |
| `menu.addMinimapSymbol`, `removeMinimapSymbol` | minimap markers (not saved; re-added after a load by the scripts) | 2, 1 |
| `menu.allowActions(type, allow [, code])` | action-button override per building type (not saved, UI only: no executor tests it) | 6 |
| `menu.openBookDialog`, `addPage`, `addPicture` | the book screen; pages beyond 20 are dropped with a warning | 2, 1, 1 |
| `menu.addCinematicPage`, `updateCinematic` | the cinematic screen; `updateCinematic` runs one page step at once (`nMenu::Cinematic::Update`, synchronously inside the calling tick [binary]) | 1, 1 |
| `menu.addTutorialPage`, `showSacrificeEffect`, `showMinimap`, `addCutsceneDebugName` | tutorial page, HUD effect, minimap, debug list | 1, 1, 0, 1 |
| `menu.addDebriefing`, `addExtro` | do nothing, as in the original (bound to a function returning 0) | 1, 0 |
| `txt.isValid(key)` | LOCAL in the original (the installation's language table; S 005da660, registered at S 005dda30); the remake answers from the **map's base language** for simulation-relevant uses, so every peer gets the same page count (the quest machine counts briefing pages with it, which decides when `quest_cinematicDone` arrives). Registered by `core.game` for match states [implemented] | 3 |
| `ui.createPicture`, `createLabel`, `createTextBlock`, `createCheckedButton`, `createIcon`, `show`, `enable`, `setContent`, `setMarkFlag`, `isDialogCreated` | widgets in a dialog's script list. The first argument indexes the menu system's dialogs; the scripts pass `BOOKDIALOG = 24`, which in the original does not point at the book [binary]; the remake treats 24 as the book, the scripts' intent. In shipped play these calls never run: the quest list opens only through `openBriefing()`, which nothing calls [binary] | 4, 2, 1, 1, 0, 5, 0, 1, 3, 0 |
| `ui.setVisible`, `enableObject`, `enableAllButtons`, `setXpos` .. `setAnchor`, `fadeIn`, `fadeOut` (second registration) | widgets by name anywhere in the UI tree; an unknown name gives no value (the original returns −1 results, a stale stack value [binary]) | 0 |
| `ui.infoText`, `infoLabel`, `infoLabel2`, `infoPicture` | info pages: recorded once into encyclopedia data (§6.2) | 124, 220 (both labels), 64 |
| `menu.setLanguage`, `setVideoVoiceStream`, `setPlayerColor` | `menu.cfg` only: recorded into presentation settings (default language, player colour table) | — |

### 6.2 Recording states [draft]

- **Cutscene paths** (186 files plus `cutscene_circle.lua`; 1 162 `addPosition` and 1 162 `addLookAt` calls,
  `setRelative` in 40 files [data]): run once against a recording `cutscene` table, which writes two key lists
  `{time, vec3}` with cumulative times, the loop flag and the anchor rule into a track file next to the map script.
  The camera plays the tracks with the original's Hermite rule (`../sim/camera-input-cutscenes.md` §3.7).
- **Info pages** (`scripts\info\i_<id>.lua`, `b_<id>.lua`): never run by the original (LR §6.1). Their file names
  carry the `*_create` id of the object they describe (`i_12e67603` = `guardHouse`) [data]; recorded into
  encyclopedia entries keyed by registry entry, for an optional info screen.
- **`menu.cfg`**: recorded at the data stage.
- **Editor brushes** (`scripts\editor\*.lua`): recorded when the map editor exists.

## 7. Callbacks from the engine into Lua

| Global | When | Remake | Defined by shipped scripts |
|---|---|---|---|
| top-level chunk | world build, §4.1 step 3 | same | every map |
| `onStarted()` | new game, before tick 0 | same | every campaign map, `Presentation.lua` |
| `onLoaded()` | every world build, after `onStarted` | same | every campaign map |
| `onLogicTick(tick)` | last step of every tick | `ScriptTickSystem` | every campaign map |
| `createQuestUi()`, `destroyQuestUi()` | the book's story / quest toggle | `ScriptCallback` command | `quests.lua` |
| `quest_cinematicDone()` | the cinematic screen's hide | after `CinematicFinished` | `quests.lua` |
| `sacrifice_execute(id)` | a sacrifice effect of kind 1006 | same, inside the tick | none |
| `<fn>(x, y)` | inside `vi_forEachBuilding`, `map_forEachDoodad` | same | C08, `tools.lua` |
| `<widget>_isClicked()`, `_isPressed()` | button events of named widgets | `ScriptCallback` command | none: the quest buttons define `_isPushed`, which the engine never calls |

Defined but never called by the original (and therefore not called by the remake in the `original` profile):
`onTriggerIsActive`, `openBriefing`, `dbg_addCinematics`, `dbg_playCinematic`, the `_isPushed` handlers (LR §4.3).

## 8. Saves and determinism

### 8.1 What is saved [draft]

The original's contract, kept exactly for the `original` profile (LR §7):

- saved: the `sd_` store (int32 values in key order), the flag "script events enabled", the 40 quest slots, the
  victory mode, and everything scripts changed through the simulation's own state;
- not saved: the Lua state (globals, tables, pending waits), the lock maps, action overrides, minimap symbols,
  tutorial pages, book pages, particles;
- on load: the script runs again from the top, then the store and the quests are restored (**added** to whatever the
  top-level chunk stored, not replacing the store), then `onLoaded`.

Shipped scripts that this contract hurts, kept as they are [data]: C04's top-level chunk reads the `sd_` store before
a save's store is loaded; Lua-only flags (`strikeIsStopped` in C09, `questCinematicRunning`, ...) are lost on load.

The `remake-1` profile adds `sadk.state`: a table of numbers, strings, booleans and nested tables of those, saved in
insertion order and restored before `onLoaded`.

### 8.2 Determinism rules for bindings [draft]

- Every SIM binding runs in the tick on every machine and creates objects in the original's internal order (unique
  ids are drawn in that order and hashed).
- Iteration orders come from the simulation: village vectors in creation order, the hex spiral, rectangles x outer
  and y inner ascending, stocks by ascending good id, the `sd_` store by byte-wise key order.
- No binding reads frame time, wall time, the language of the installation, the camera or the selection.
- Presentation bindings never change simulation state; the only exceptions of the original (`menu.startCinematic`,
  the cinematic end) are routed as described in §4.3 and §5.3.

### 8.3 Hazards in the shipped scripts [data]

| Hazard | Where | Remake |
|---|---|---|
| quest evaluation waits for the local cinematic | `quests.lua` | `CinematicFinished` command |
| `pl_getUser` as the player of quest targets and exploration | `questTargets.lua`, `quests.lua` | §5.2 |
| `getSpeed` in a simulation path | `quests.lua` | §5.2 (no effect under single precision, §2.5) |
| `txt.isValid` decides the number of briefing pages | `quests.lua` | §6.1 |
| saved `sd_` keys written from the C08 particle timers | C08 | deterministic in the remake (the timers run in the tick) |
| a comparison with a possibly missing result | C05 `pl_getSacrificeState(...) >= 1` | the error model of §2.7 (it is the last statement of `onLogicTick`, so nothing is lost) |
| `destroyAllBuildings` never ends for a player without buildings (inverted `until`) | `tools.lua` (unused) | a loop guard in the `original` profile: a callback that runs more than a set number of VM instructions in one call is aborted with an error |
| undefined globals read (`unlockFarm`, `name` / `questType` in `quest_addToLogic`, `triggers`) | C09, `quests.lua`, `Presentation.lua` | `nil`, as in the original; the converter logs them |

### 8.4 `pairs` order

No shipped script iterates with `pairs` or `next` [data]. Insertion order is deterministic on every machine, but it
is not Lua 5.0.2's hash order; a third-party script that depends on the original's order would run differently. If
such scripts appear, the port of Lua 5.0.2 (§2.1) is the way to match them.

## 9. The remake's own surface: `sadk` [draft]

For maps and mods written for the remake (`remake-1`); versioned (`sadk.apiVersion`); safe in lockstep by
construction.

| Area | Functions (sketch) |
|---|---|
| players | `sadk.players()` (ordered), `sadk.humans()`, `sadk.player(i)` with `tribe`, `team`, `isHuman`, `isActive` |
| registry | `sadk.entry(kind, key)` (read-only view by name), `sadk.id(kind, key)` / `sadk.key(kind, id)` (names ↔ the original's ids) |
| events | `sadk.on(name, fn)` for simulation events (`BuildingFinished`, `BuildingRemoved`, `SettlerAdded`, `GoodProduced`, `QuestChanged`, a mod's own events); handlers run in the script system of the tick, in registration order |
| time | `sadk.after(ticks, fn)`, `sadk.every(ticks, fn)`, `sadk.tick()` |
| random | `sadk.random(n)`: the simulation generator, explicit |
| commands | `sadk.command(player, command, args)`: a game command executed for a player inside the tick (scripted opponents, tutorials) |
| messages and UI | `sadk.message(player or "all", key, args)`, `sadk.ui.*` addressed to players; a per-player quest log |
| state | `sadk.state` (§8.1) |

The `original` tables stay available in `remake-1`, so a new map can reuse the campaign's tool libraries.

## 10. How bindings are written and extended [draft]

```csharp
[LuaLibrary("logic", States = ScriptState.Match)]
public sealed class LogicPlayers : LuaLibrary
{
    [LuaFunction("pl_getGoodAmount", Class = BindingClass.QueryCached)]
    public LuaResult GetGoodAmount(LuaArgs a)
    {
        if (!Guards.ActivePlayer(a.Int(0), out var player)) return LuaResult.None;   // no value
        if (!Ids.TryGood(a.Int(1), out var good)) return LuaResult.Of(0);
        return LuaResult.Of(player.CachedStock.Count(good));
    }
}
```

- The helpers (`a.Int`, `a.Float`, `a.Bool`, `a.String`, `LuaResult.None`) implement §5.1 once.
- Libraries are registered per state at the runtime registration step ([mods.md](mods.md) §6.7). A later
  registration of the same table and name replaces the function, with a log line: a mod can fix a binding (for
  example `pl_getProducedGoodCount`) without Harmony, or add a table of its own. Harmony reaches the C# methods
  behind them like any other method.
- The class attribute drives the checks: a SIM binding called outside the match state's tick or a world build is an
  error; a UI binding never touches simulation services.
- The Lua API reference for mod authors is generated from these attributes and their doc comments, one page per
  table ([mods.md](mods.md) §11).

## 11. Tests [draft]

- **Binding unit tests** for the conventions: no value on every failed guard, truncation, `0` is true, `%.14g`,
  single-precision results (`60 * 0.34` → `20.39999961853`), the spiral order.
- **Number model tests** against values computed with the x87 at 24-bit precision; a vector file of operations and
  results recorded once from the original's Lua in the running game (the Frida MCP) covers the rounding hook.
- **Campaign runs**: every campaign map runs headless for a fixed number of ticks with recorded commands; quest
  slots, `sd_` store and per-tick checksums are compared with traces recorded from the original through hooks on its
  `CallGlobal` and binding functions. A live session item: it needs the running game.
- **Converter round trip**: every shipped script converts, compiles and keeps its line numbers.

## 12. Open points

1. MoonSharp in a fork, Lua-CSharp, or a port of Lua 5.0.2 (§2.1). **Decision for the maintainer.**
2. Scripted maps in compatibility-mode matches with original clients: run without `logic` as the original does, or
   refuse (§4.5). **Decision for the maintainer.**
3. Whether the original's `strtod` depends on the precision control (§2.5).
4. Whether any HUD path opens the book other than `menu.openBookDialog` (§6.1); if none, the quest-list widgets are
   dead code in the original.
5. The unguarded `menu.createBuilding`: whether construction completes when placement failed.
6. Generator draws inside `pl_changePlayer`, `menu.createBuildingWithSettler`, `menu.createStreet`,
   `map_killDeposits`, `map_createDoodad` and `ai_enable` (each subsystem document lists its draws).
7. `map_getTerritoryPlayerId` for an unowned cell.
