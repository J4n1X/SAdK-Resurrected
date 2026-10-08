# Lua scripting surface (SADK.exe)

What the game does with Lua, mapped so that mods can hook into it: the runtime, how scripts are loaded, every
C function registered for Lua, every place the engine calls into Lua, and the hook points that follow from that.

- Binary: the DRM-free `SADK.exe` (Ghidra `/sadk_noav.exe`, image base `0x400000`; static addresses are runtime
  addresses). Declarations are named as in `sadkmod/build/include/sadkmod/game/sadk_noav/fn/*.hpp`, written here
  without the `sadk::game::` prefix: `fn::X` is `sadk::game::fn::X`. "address only" means the header has an
  `Addr<>` (no signature yet), not a callable `Fn<>`.
- Status tags: **[known]** = read in the binary at the given address (decompile, disassembly, data or string);
  **[inferred]** = follows from what was read plus Lua 5.0.2 library semantics or the shipped scripts, not
  observed at run time; **[TODO]** = not established. Nothing here has been checked in the running game.
- Script cross-reference: the decrypted game data (`game/` tree). Only file names and identifiers are quoted.

## 1. Runtime

### 1.1 Version and libraries

| Fact | Evidence | Status |
|---|---|---|
| Lua **5.0.2** is statically linked | version banner string `007ec1a8` ("Lua 5.0.2 Copyright (C) 1994-2004 Tecgraf, PUC-Rio"); `_VERSION` set to "Lua 5.0.2" in `base_open` `005cb5f0` | [known] |
| Only the **base** library (with `coroutine`) and **math** are opened. No `string`, `table`, `io`, `os`, `debug` or `loadlib` | the opener table `007eb930` is `{luaopen_base 005cb6b0, "…"}, {luaopen_math 005ca390, 0}, {0}`, iterated by `LuaScriptHost_ctor` `005c8ef0` | [known] |
| The shipped scripts use none of the missing libraries and never call `dofile` / `require` / `loadfile` / `loadstring` | text search over every `.lua` / `.cfg` of the decrypted data | [known] (data) |
| `base_open` also sets the globals `_G`, `_VERSION`, `newproxy`; `luaopen_base` adds the `coroutine` table and `_LOADED`; `luaopen_math` sets `math.pi` and the global `__pow` | strings and calls in `005cb5f0`, `005cb6b0`, `005ca390` | [known] |

### 1.2 States: one `lua_State`, many coroutine threads

There is exactly **one** `lua_State` in the process. `lua_open` (`005ce3c0`) has a single call site, in
`LuaScriptHost_ctor` [known]. Every script runs in a **coroutine thread** made from that state with
`lua_newthread` (`LuaScriptHost_NewThread` `005c9130`) [known]. In Lua 5.0 a thread shares the global table of
the state it was created from, so every library registered on any thread is visible to every script
[inferred: Lua 5.0.2 `lua_newthread` semantics].

The **lobby** (3D village, `Lobby::*`, `LobbyManager`) does not use Lua: none of the callers of `lua_open`,
`luaL_openlib`, `lua_newthread`, `Lua_RegisterLibrary` or `LuaScriptHost::RegisterLib` is lobby code, and the
lobby data tree contains no `.lua` file [known: xrefs + data]. Lua is used by the game side only: properties,
menus, map scripts, cutscenes, info pages and the map editor.

| Object | Address | sadkmod | Notes | Status |
|---|---|---|---|---|
| Script host singleton `LuaScriptHost *` | `0088b82c` | `var::g_pLuaScriptHost` | created by `LuaScriptHost_CreateInstance` `005c90c0` (`operator new(0x30)`), called from `CApplicationEx::Initialize` `004075d0`; freed by `LuaScriptHost_DestroyInstance` `005c92b0` at shutdown | [known] |
| Main state `lua_State *` | `0088b830` | `var::g_LuaState` | set by `Lua_SetGlobalState` `005c9ab0` in the host ctor; `Lua_RegisterLibrary` registers into it | [known] |
| `LuaScriptHost` | struct | `ai::script::LuaScriptHost` | `+0x00 mainState`; `+0x04..` handle pool of `LuaThreadEntry` (`+0x0c threads`); `+0x1c/+0x20/+0x24` active-id list; `+0x2c` host clock (seconds) | [known] fields used by the functions below; meaning of the pool fields [inferred] |
| `LuaThreadEntry` (12 bytes) | struct | `ai::script::LuaThreadEntry` | `+0 L` (thread), `+4 waitMode` (1 = waiting), `+8 wakeTime` (-1.0 = not waiting) | [inferred] |
| Thread ids | — | — | 1-based handles; `globals[lightuserdata L] = lightuserdata id` is stored on creation so a C function can find its own thread id (`Default.Wait`, `Default.Break`, `Default.WriteToLog` read it) | [known] |
| Map-script thread id | `0087e93c` | `var::g_GameScript_ThreadId` | the long-lived thread of the current map's script | [known] |
| Map-script path `std::string` | `0087e950` | — | empty when the map has no script; its size (`0087e964`) gates every map-script event call | [known] |
| Map-script "UI events enabled" byte | `0088b314` | — | 1 between `GameScript_InitMapScript` and `GameScript_DestroyMapScript`; gates button events | [known] |

### 1.3 Script host functions

| Function | Address | sadkmod | What it does | Status |
|---|---|---|---|---|
| `LuaScriptHost_ctor` | `005c8ef0` | `fn::LuaScriptHost_ctor` | `lua_open`, `lua_checkstack(256)`, base + math, `LuaScript_OpenDefaultLib`, `Lua_SetGlobalState`, `LuaDebugger_AddLuaState` | [known] |
| `LuaScriptHost_GetInstance` | `005c8bd0` | `fn::LuaScriptHost_GetInstance` | returns `g_pLuaScriptHost` | [known] |
| `LuaScriptHost_NewThread` | `005c9130` | `fn::LuaScriptHost_NewThread` (fastcall) | `lua_newthread`, allocates an id, registers the thread with the debugger; returns id or `-1` | [known] |
| `LuaScriptHost::DestroyThread` | `005c9200` | `fn::ai::script::LuaScriptHost::DestroyThread` | removes the thread and its `globals[L]` entry, frees the id | [known] |
| `LuaScriptHost::RunFile` | `005c9690` | `fn::ai::script::LuaScriptHost::RunFile` | reads + decrypts the file (`006e7770`), `LuaDebugger_NewFile`, `luaL_loadbuffer(L, buf, len, path)`, then **`lua_resume(L, 0)`**: the chunk runs as a coroutine and may yield | [known] |
| `LuaScriptHost::RegisterLib` | `005c8cd0` | `fn::ai::script::LuaScriptHost::RegisterLib` | `luaL_openlib(thread L, name, regs, 0)`; pops the table | [known] |
| `LuaScriptHost::CallGlobal` | `005c9780` | `fn::ai::script::LuaScriptHost::CallGlobal` | `globals[name]()` via `lua_pcall(L, 0, nResults, 0)` | [known] |
| `LuaScriptHost::CallGlobal_Number` | `005c9840` | `fn::ai::script::LuaScriptHost::CallGlobal_Number` | `globals[name](number)` | [known] |
| `LuaScriptHost::CallGlobal_XY` | `005c9920` | `fn::ai::script::LuaScriptHost::CallGlobal_XY` | `globals[name](x, y)` | [known] |
| `LuaScriptHost::IsGlobalFunction` | `005c8d20` | `fn::ai::script::LuaScriptHost::IsGlobalFunction` | `type(globals[name]) == "function"` | [known] |
| `LuaScriptHost::ClearGlobalFunction` | `005c8dc0` | `fn::ai::script::LuaScriptHost::ClearGlobalFunction` | sets a global function to nil | [known] |
| `LuaScriptHost::YieldWait` | `005c8c90` | `fn::ai::script::LuaScriptHost::YieldWait` | stores wait mode + wake time (clock + seconds) and `lua_yield`s; only caller `Default.Wait` | [known] |
| `LuaScriptHost::UpdateThreads` | `005c9a10` | `fn::ai::script::LuaScriptHost::UpdateThreads` | per frame: sets the clock, resumes every waiting thread whose time has passed; called from `CApplicationEx::FrameTick_Menu` `00401780` and `FrameTick_InGame` `004018e0` | [known] |
| `LuaScriptHost_DumpScriptError` | `005c9440` | `fn::LuaScriptHost_DumpScriptError` | formats "script failed" + a stack dump into a `stringstream` and **discards it**: script errors are silent in this build | [known] |
| `Lua_RegisterLibrary` | `005c9bd0` | `fn::Lua_RegisterLibrary` | `luaL_openlib(g_LuaState, name, regs, 0)`; pops the table. `name` is an MSVC `std::string *` | [known] |
| `LuaScript_OpenDefaultLib` | `005cdd80` | `fn::LuaScript_OpenDefaultLib` | registers the `Default` table from the static array `007ec370` | [known] |

Binding helpers the game's C functions use (all `__cdecl`, all callable): `Lua_ToInt` `005c9b30`,
`Lua_ToFloat` `005c9b10`, `Lua_ToBool` `005c9b50`, `Lua_PushInt` `005c9b70`, `Lua_PushBool` `005c9b90`,
`Lua_PushFloat` `005c9bb0`, `Lua_IsNumberBool` `005c9ae0` [known: names/signatures from the map].

### 1.4 Lua C API in the binary

All are the unmodified Lua 5.0.2 functions (`__cdecl`) and all are callable through sadkmod as `fn::<name>`.
A mod must use these (the game's own Lua), not a second copy of Lua linked into the mod.

| Function | Address | Function | Address |
|---|---|---|---|
| `lua_open` | `005ce3c0` | `lua_close` | `005ce450` |
| `lua_newthread` | `005cc4c0` | `lua_resume` | `005cc270` |
| `lua_yield` | `005cc050` | `lua_checkstack` | `005cc410` |
| `lua_gettop` | `005cc500` | `lua_settop` | `005cc510` |
| `lua_pushnil` | `005cca60` | `lua_pushnumber` | `005cca80` |
| `lua_pushstring` | `005ccae0` | `lua_pushlstring` | `005ccaa0` |
| `lua_pushboolean` | `005ccc40` | `lua_pushlightuserdata` | `005ccc60` |
| `lua_pushcclosure` | `005ccbb0` | `lua_pushvalue` | `005cc650` |
| `lua_gettable` | `005ccc80` | `lua_settable` | `005cce70` |
| `lua_rawget` | `005cccd0` | `lua_rawset` | `005cceb0` |
| `lua_newtable` | `005ccd70` | `lua_newuserdata` | `005cd240` |
| `lua_type` | `005cc690` | `lua_isnumber` | `005cc720` |
| `lua_isstring` | `005cc770` | `lua_tonumber` | `005cc820` |
| `lua_toboolean` | `005cc870` | `lua_tostring` | `005cc8b0` |
| `lua_strlen` | `005cc920` | `lua_touserdata` | `005cc980` |
| `lua_call` | `005cd010` | `lua_pcall` | `005cd050` |
| `lua_load` | `005cd0c0` | `lua_error` | `005cd170` |
| `lua_next` | `005cd180` | `lua_getstack` | `005ce530` |
| `lua_getinfo` | `005cef90` | `luaL_openlib` | `005cd430` |
| `luaL_loadbuffer` | `005cd900` | `luaL_loadfile` | `005cd740` |
| `luaL_error` | `005cd310` | `luaL_where` | `005cd280` |
| `luaL_checknumber` | `005cdb40` | `luaL_checklstring` | `005cda70` |
| `luaL_optnumber` | `005cdbc0` | `luaL_optlstring` | `005cdae0` |
| `luaL_argerror` | `005cd930` | `luaL_checktype` | `005cd9f0` |

[known: names and signatures from the map, matched to the Lua 5.0.2 sources there.] `lua_register`,
`lua_dofile` and `lua_dostring` are macros or absent in 5.0.2 / not linked: every registration in the binary
goes through `luaL_openlib` (`lua_pushcclosure` is only called from `luaL_openlib`, `base_open`,
`luaopen_math` and `luaB_cowrap`) [known: xrefs].

### 1.5 External Lua debugger hook (`LuaDebugger.dll`)

The game carries thunks to an optional debugger DLL. On first use each thunk calls
`LoadLibraryA("LuaDebugger.dll")` (string `007ec2f4`), looks up its export and jumps to it; when the DLL or the
export is missing it returns silently [known: map comments at the thunks, export strings `007ec304`..`007ec33c`].

| Thunk | Address | Export | Called from | Status |
|---|---|---|---|---|
| `LuaDebugger_AddLuaState` | `005cdc90` | `_AddLuaState@4(L)` | host ctor (main state), `LuaScriptHost_NewThread` (every thread) | [known] |
| `LuaDebugger_RemoveLuaState` | `005cdce0` | `_RemoveLuaState@4(L)` | `LuaScriptHost::DestroyThread` | [known] |
| `LuaDebugger_NewFile` | `005cdc40` | `_NewFile@16(L, chunkName, buffer, size)` | `RunFile` (file path + decrypted source); every `CallGlobal*` (chunk name `""`, buffer = the function name) | [known] |
| `LuaDebugger_Break` | `005cdd30` | `_Break@4(L)` | `Default.Break` | [known] |
| `LuaDebugger_Hide` | `005cdbf0` | `_Hide@0()` | host dtor | [known] |

## 2. Script loading

### 2.1 Reader

`LuaScriptHost::RunFile` reads through `006e7770` (unnamed; no sadkmod declaration), which is
`NBase::gReadFileData(path, &buf, &len)` followed by `NBase::gDecryptData(path, &buf, &len)` (`006e6660`) [known].
Scripts therefore go through the same file layer as other encrypted data: the mod host's `CreateFile` redirect
and its plain-file pass-through in `gDecryptData` apply to them, so a `mods\<name>\data\…\x.lua` in plain text
replaces the game's script [inferred: the redirect is at `CreateFile`, below `gReadFileData`; not tested in the
game]. Paths are written with the `[data]` prefix (e.g. `[data]\scripts\menu.cfg`), resolved by the file layer
[inferred].

The base library's `dofile` / `loadfile` / `require` use `luaL_loadfile` (`005cd740`, C `fopen`), which does
**not** decrypt and does not resolve `[data]`; no shipped script uses them [known: code + data].

The chunk name passed to `luaL_loadbuffer` is the path string itself (no `@` prefix) [known].

### 2.2 Who loads what, and when

| When | Loader (address, sadkmod) | Thread | Script(s) | Status |
|---|---|---|---|---|
| Start-up, `CApplicationEx::Initialize` `004075d0`, right after the host is created and `properties` is registered | `Properties_RunPropertyScript("data")` `0054f8d0` (`fn::Properties_RunPropertyScript`) builds `[data]\scripts\properties\<name>.lua` | temporary (new, run, destroyed) | `scripts\properties\data.lua`, which pulls in the other property scripts with `Default.CallScript` (22 files in `scripts\properties\`) | [known] loader; [inferred] chain via `data.lua` (data) |
| Start-up, `nMenu::System::Initialize` `005dda30` (`fn::nMenu::System::Initialize`), after registering `menu` / `ui` / `txt` | `RunFile` at `005ddfba` | temporary | `[data]\scripts\menu.cfg` (a Lua chunk: `menu.setLanguage`, `menu.setPlayerColor`, …) | [known] |
| Any script calling `Default.CallScript(path)` | `LuaDefault_CallScript` `005cdfb0` (`fn::LuaDefault_CallScript`) | temporary | the path argument; shipped uses: `scripts\properties\*.lua`, `scripts\mapTools\{aiLimiter,quests,spawnDepots,tutorial,tools,questTargets,cinematicFunctions}.lua` | [known] loader; uses from data |
| World build, `nGame::System::BuildWorld` `00784d40` → `GameFile_LoadMap` `005aa7b0` | `GameScript_LoadMapScript` `005b1fe0` (`fn::GameScript_LoadMapScript`) | map-script thread (long-lived) | the map file path with its extension replaced by `.lua` (e.g. `maps\campaignMaps\C01.s2m` → `C01.lua`, `map\Presentation.s2m` → `Presentation.lua`). If the file does not exist the map-script path is cleared and all map-script events become no-ops | [known] `".lua"` + `rfind`/`substr` in `005aa7b0`, `Fs_FileExists` in `005b1fe0`; [inferred] exact path rule |
| Info / encyclopaedia screen, `nMenu::Info::Open` `005f6310` | `GameScript_RunFile` `005b1dc0` (`fn::GameScript_RunFile`) | map-script thread | `[data]\scripts\info\i_<hex>.lua` and `[data]\scripts\info\b_<hex>.lua` (95 `i_`, 29 `b_` shipped) | [known] strings `007ef52c`, `007ef568`; [TODO] what the hex is |
| Cutscene start, `ai::camera::CutsceneCamera::LoadScript` `0078ac10` (callers `PlayAtOffset` `0078aed0`, `0078aeb0`) | `RunFile` at `0078ae2f` | temporary (registers `cutscene` on it first) | `<map dir>\<map name>_<cutscene>.lua` built by `Cutscene_BuildScriptPath` `0078a940` (e.g. `C01_1intro.lua`) | [known] loader, strings `"_"`, `".lua"`; [inferred] exact path form |
| Map editor debug menu, `nMenu::Debug::RefillElementList` `00608160` | `RunFile` at `00608765`, `006088c3` | temporary | `[data]\scripts\editor\scatter.lua`, `[data]\scripts\editor\copypaste.lua` | [known] |

`scripts\graphic_main.lua` is shipped but no string or loader for it was found [TODO]. The `[data]\scripts\effects`
strings belong to the effect system, not Lua [TODO: not checked].

**Checksum:** `GameData_ComputeBuildChecksum` `005ab800` covers every `[data]\scripts\**\*.lua` (and
`settings\**\*.xml`); `menu.cfg` is not matched by `*.lua`. A mod that changes a `.lua` changes the build checksum
that multiplayer peers compare [known: strings `[data]\scripts`, `*.lua` at `005ab880`/`005ab89a`].

### 2.3 Map-script lifecycle

| Step | Function | Status |
|---|---|---|
| Create the map-script thread, clear the path, set `0088b314 = 1`, clear the script-data map (`sd_setValue` store) | `GameScript_InitMapScript` `005b2720`, from `nGame::System::BuildWorld` `00784dae` | [known] |
| Register `logic` and `gfx` on that thread — **only when `NComm_Manager_IsRole0` (`004083d0`, NComm manager `+0x3c8 == 0`) is true** | `GameScript_RegisterLuaLibraries` `005b2990`, from `00784dc5` | [known]; [TODO] what role 0 is (single player / host?) and whether multiplayer clients run map scripts without `logic` |
| Load and start the map script | `GameScript_LoadMapScript` (above) | [known] |
| Call `onStarted()` (new-game map types and type `0x65` only), then `onLoaded()` (always) | `Game_LoadWorldFromDescriptor` `005ac770` → `005ac860`, `005ac865` | [known] |
| Tear down: clear the global `createQuestUi`, destroy the thread, path cleared, `0088b314 = 0` | `GameScript_DestroyMapScript` `005b1ce0`, caller `007834e0` | [known] |

Shipped map scripts exist only for the campaign (`maps\campaignMaps\C*.lua`, 11) and `map\Presentation.lua`; the
free-game maps have none [known: data].

## 3. C functions exposed to Lua

### 3.1 Summary

Every registration goes through `luaL_openlib(L, libname, luaL_reg[], 0)`, either directly (static arrays in
`.rdata`) or through `Lua_RegisterLibrary` / `LuaScriptHost::RegisterLib`, whose callers build the `luaL_reg`
array on the stack immediately before the call [known]. `luaL_openlib` reuses an existing global table of the
same name, so the two `ui` registrations end up in one table [inferred: Lua 5.0.2 `luaL_openlib`]. All names
are fields of a library table; apart from the base library nothing is registered as a bare global.

| Table | Entries | Registered by (address, sadkmod) | Registration call | When | Status |
|---|---|---|---|---|---|
| `Default` | 4 | `005cdd80` LuaScript_OpenDefaultLib (`fn::LuaScript_OpenDefaultLib`) | static `luaL_reg[]` at `007ec370` | start-up (host ctor) | [known] |
| `properties` | 243 | `00550e40` Properties_RegisterLuaLibrary (`fn::Properties_RegisterLuaLibrary`) | call at `0055236e` to `Lua_RegisterLibrary` | start-up | [known] |
| `menu` | 31 | `005dda30` nMenu::System::Initialize (`fn::nMenu::System::Initialize`) | call at `005ddd53` to `Lua_RegisterLibrary` | start-up | [known] |
| `ui` | 14 | `005dda30` nMenu::System::Initialize (`fn::nMenu::System::Initialize`) | call at `005ddee3` to `Lua_RegisterLibrary` | start-up | [known] |
| `txt` | 1 | `005dda30` nMenu::System::Initialize (`fn::nMenu::System::Initialize`) | call at `005ddf4f` to `Lua_RegisterLibrary` | start-up | [known] |
| `ui` | 19 | `004c5ab0` LuaUi_RegisterLibrary (`fn::LuaUi_RegisterLibrary`) | call at `004c5c7e` to `Lua_RegisterLibrary` | first button event (lazy) | [known] |
| `editor` | 13 | `0060a340` nMenu::Debug::OnShow (`fn::nMenu::Debug::OnShow`) | call at `0060a4cf` to `Lua_RegisterLibrary` | editor debug menu shown | [known] |
| `logic` | 102 | `005b2990` GameScript_RegisterLuaLibraries (`fn::GameScript_RegisterLuaLibraries`) | call at `005b328e` to `RegisterLib` | world build (role 0 only) | [known] |
| `gfx` | 1 | `005b2990` GameScript_RegisterLuaLibraries (`fn::GameScript_RegisterLuaLibraries`) | call at `005b3321` to `RegisterLib` | world build (role 0 only) | [known] |
| `cutscene` | 4 | `0078ac10` ai::camera::CutsceneCamera::LoadScript (`fn::ai::camera::CutsceneCamera::LoadScript`) | call at `0078ace5` to `RegisterLib` | each cutscene load | [known] |
| `_G (globals)` | 25 | `005cb5f0` base_open (`fn::base_open` (address only)) | static `luaL_reg[]` at `007ebb38` | start-up (host ctor) | [known] |
| `coroutine` | 5 | `005cb6b0` luaopen_base (`fn::luaopen_base`) | static `luaL_reg[]` at `007ebc08` | start-up (host ctor) | [known] |
| `math` | 24 | `005ca390` luaopen_math (`fn::luaopen_math`) | static `luaL_reg[]` at `007eb988` | start-up (host ctor) | [known] |

**Totals:** 432 game functions in 9 tables (`Default`, `properties`, `menu`, `ui`, `txt`, `editor`,
`logic`, `gfx`, `cutscene`; `ui` counted once per registration) plus 54 standard library entries
(`_G` base, `coroutine`, `math`). Pairing of name and function in the stack-built arrays was read from the
`MOV [ESP+x], imm` sequences of each registering function [known]; table names from the `std::string::assign`
before each call [known].

**Cross-check with the shipped scripts** (every `lib.name(` / `lib:name(` in the decrypted `.lua` / `.cfg`):
every library call in the shipped scripts resolves to a registered name; there are no calls to unregistered
`lib.` names [known: data vs. binary]. Names that no shipped script calls are marked "no" in the tables (several
`ui.*`, `editor.*`, `logic.se_*` NPC functions, etc.). The `ai` table the scripts use is defined in Lua
(`scripts\mapTools\aiLimiter.lua`), not in C. Callbacks such as `onTriggerIsActive` are called from Lua only
(no such string in the binary) [known].

Unnamed functions in the tables (no sadkmod declaration yet): `menu.showSacrificeEffect` `005d9550`,
`menu.showMinimap` `005d9530`, `logic.victory_setupQuests` `005af7e0` [known]. `menu.addDebriefing` and
`menu.addExtro` are both bound to `Generic_ReturnZero` `0072db80`: stubs that do nothing [known].

### 3.2 `Default` (static array `007ec370`)

Registered on the main state by `LuaScript_OpenDefaultLib` `005cdd80` from the host ctor, at start-up.

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `Default.WriteToLog` | `005CDDE0` | LuaDefault_WriteToLog | `fn::LuaDefault_WriteToLog` | yes |
| `Default.Wait` | `005CDE50` | LuaDefault_Wait | `fn::LuaDefault_Wait` | no |
| `Default.Break` | `005CDF10` | LuaDefault_Break | `fn::LuaDefault_Break` | no |
| `Default.CallScript` | `005CDFB0` | LuaDefault_CallScript | `fn::LuaDefault_CallScript` | yes |

- `Default.WriteToLog(msg)` pops its argument and logs nothing: output is compiled out [known: `005cdde0`].
- `Default.Wait(seconds)` suspends the calling thread until `UpdateThreads` resumes it [known].
- `Default.CallScript(path)` runs a file in a new temporary thread (load + `lua_resume`) and destroys the thread
  when `RunFile` returns, i.e. also when the script yielded [known: call sequence; inferred: a yielded script is
  abandoned].

### 3.3 `properties` — `Properties_RegisterLuaLibrary` `00550e40`

Registered at start-up from `CApplicationEx::Initialize` (`0040775c`) before the property scripts run. Prefixes:
`tp_` tribe, `hp_` harbour, `ai_` AI profile, `cfg_` game constants, `sn_` sound, `an_` animal, `sh_` ship,
`mi_` military, `sp_` spawn point, `gp_` good, `bp_` building, `rm_` remains, `dd_` doodad, `dp_` deposit,
`pa_` pattern, `sf_` sacrifice, `si_` sign [inferred from names].

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `properties.tp_create` | `0054ABB0` | LuaProps_tp_create | `fn::LuaProps_tp_create` | yes |
| `properties.tp_setName` | `0054AE30` | LuaProps_tp_setName | `fn::LuaProps_tp_setName` | yes |
| `properties.tp_addGood` | `0054AF00` | LuaProps_tp_addGood | `fn::LuaProps_tp_addGood` | yes |
| `properties.tp_addJob` | `0054AF60` | LuaProps_tp_addJob | `fn::LuaProps_tp_addJob` | yes |
| `properties.tp_addBuilding` | `0054AFC0` | LuaProps_tp_addBuilding | `fn::LuaProps_tp_addBuilding` | yes |
| `properties.tp_setMenuX` | `0054B020` | LuaProps_tp_setMenuX | `fn::LuaProps_tp_setMenuX` | yes |
| `properties.tp_setBuildingsTextureName` | `0054AAE0` | LuaProps_tp_setBuildingsTextureName | `fn::LuaProps_tp_setBuildingsTextureName` | yes |
| `properties.tp_addSacrifice` | `0054B070` | LuaProps_tp_addSacrifice | `fn::LuaProps_tp_addSacrifice` | yes |
| `properties.tp_addAllowedSacrifice` | `0054B0C0` | LuaProps_tp_addAllowedSacrifice | `fn::LuaProps_tp_addAllowedSacrifice` | yes |
| `properties.tp_setSecondCarrierId` | `0054AD40` | LuaProps_tp_setSecondCarrierId | `fn::LuaProps_tp_setSecondCarrierId` | yes |
| `properties.tp_setConstructionGoodId` | `0054ACA0` | LuaProps_tp_setConstructionGoodId | `fn::LuaProps_tp_setConstructionGoodId` | yes |
| `properties.tp_addStartResources` | `0054AA30` | LuaProps_tp_addStartResources | `fn::LuaProps_tp_addStartResources` | yes |
| `properties.tp_addBonusResources` | `0054A980` | LuaProps_tp_addBonusResources | `fn::LuaProps_tp_addBonusResources` | yes |
| `properties.tp_setSoldierUpgradeGoodId` | `0054ADE0` | LuaProps_tp_setSoldierUpgradeGoodId | `fn::LuaProps_tp_setSoldierUpgradeGoodId` | yes |
| `properties.tp_setWorkerToolGoodId` | `0054AD90` | LuaProps_tp_setWorkerToolGoodId | `fn::LuaProps_tp_setWorkerToolGoodId` | yes |
| `properties.tp_setConstructor` | `0054ACF0` | LuaProps_tp_setConstructor | `fn::LuaProps_tp_setConstructor` | yes |
| `properties.hp_setWaterStreetPosition` | `0054B120` | LuaProps_hp_setWaterStreetPosition | `fn::LuaProps_hp_setWaterStreetPosition` | yes |
| `properties.hp_setShipPosition` | `0054B1A0` | LuaProps_hp_setShipPosition | `fn::LuaProps_hp_setShipPosition` | yes |
| `properties.hp_create` | `0054B240` | LuaProps_hp_create | `fn::LuaProps_hp_create` | yes |
| `properties.hp_setName` | `0054B330` | LuaProps_hp_setName | `fn::LuaProps_hp_setName` | yes |
| `properties.hp_setGfxName` | `0054B400` | LuaProps_hp_setGfxName | `fn::LuaProps_hp_setGfxName` | yes |
| `properties.ai_create` | `0054B4D0` | LuaProps_ai_create | `fn::LuaProps_ai_create` | yes |
| `properties.ai_setName` | `0054B610` | LuaProps_ai_setName | `fn::LuaProps_ai_setName` | yes |
| `properties.ai_setStartFrameProducerCount` | `0054B5C0` | LuaProps_ai_setStartFrameProducerCount | `fn::LuaProps_ai_setStartFrameProducerCount` | yes |
| `properties.ai_setMilitaryMode` | `0054B6E0` | LuaProps_ai_setMilitaryMode | `fn::LuaProps_ai_setMilitaryMode` | yes |
| `properties.ai_setMaximumSmithies` | `0054B730` | LuaProps_ai_setMaximumSmithies | `fn::LuaProps_ai_setMaximumSmithies` | yes |
| `properties.ai_setMaximumMints` | `0054B780` | LuaProps_ai_setMaximumMints | `fn::LuaProps_ai_setMaximumMints` | yes |
| `properties.ai_setFactor` | `0054B8A0` | LuaProps_ai_setFactor | `fn::LuaProps_ai_setFactor` | yes |
| `properties.ai_enableStreetOptimizing` | `0054B910` | LuaProps_ai_enableStreetOptimizing | `fn::LuaProps_ai_enableStreetOptimizing` | yes |
| `properties.ai_enableRouteOptimizing` | `0054B960` | LuaProps_ai_enableRouteOptimizing | `fn::LuaProps_ai_enableRouteOptimizing` | yes |
| `properties.ai_enableCatapults` | `0054B9B0` | LuaProps_ai_enableCatapults | `fn::LuaProps_ai_enableCatapults` | yes |
| `properties.ai_enableCoinArrangement` | `0054BF50` | LuaProps_ai_enableCoinArrangement | `fn::LuaProps_ai_enableCoinArrangement` | yes |
| `properties.ai_setBattleCalcRatio` | `0054B830` | LuaProps_ai_setBattleCalcRatio | `fn::LuaProps_ai_setBattleCalcRatio` | no |
| `properties.ai_setRetreatChance` | `0054BA00` | LuaProps_ai_setRetreatChance | `fn::LuaProps_ai_setRetreatChance` | yes |
| `properties.ai_setDestroyLostBuildingChance` | `0054BA50` | LuaProps_ai_setDestroyLostBuildingChance | `fn::LuaProps_ai_setDestroyLostBuildingChance` | yes |
| `properties.ai_setSwordBowRatio` | `0054BAA0` | LuaProps_ai_setSwordBowRatio | `fn::LuaProps_ai_setSwordBowRatio` | no |
| `properties.ai_setSacrificesStartTime` | `0054BAF0` | LuaProps_ai_setSacrificesStartTime | `fn::LuaProps_ai_setSacrificesStartTime` | yes |
| `properties.ai_setSacrificesLimit` | `0054BD20` | LuaProps_ai_setSacrificesLimit | `fn::LuaProps_ai_setSacrificesLimit` | yes |
| `properties.ai_addFavoritSacrifice` | `0054B7D0` | LuaProps_ai_addFavoritSacrifice | `fn::LuaProps_ai_addFavoritSacrifice` | yes |
| `properties.ai_enableWaterStreets` | `0054BFA0` | LuaProps_ai_enableWaterStreets | `fn::LuaProps_ai_enableWaterStreets` | yes |
| `properties.ai_setSpecialAttackMinFactor` | `0054BFF0` | LuaProps_ai_setSpecialAttackMinFactor | `fn::LuaProps_ai_setSpecialAttackMinFactor` | no |
| `properties.ai_setSpecialAttackRandomValue` | `0054C040` | LuaProps_ai_setSpecialAttackRandomValue | `fn::LuaProps_ai_setSpecialAttackRandomValue` | no |
| `properties.ai_setSpecialAttackBestChance` | `0054C090` | LuaProps_ai_setSpecialAttackBestChance | `fn::LuaProps_ai_setSpecialAttackBestChance` | no |
| `properties.ai_setSpecialDefenseFactor` | `0054C0E0` | LuaProps_ai_setSpecialDefenseFactor | `fn::LuaProps_ai_setSpecialDefenseFactor` | no |
| `properties.ai_setSpecialDefenseRandomValue` | `0054C130` | LuaProps_ai_setSpecialDefenseRandomValue | `fn::LuaProps_ai_setSpecialDefenseRandomValue` | no |
| `properties.ai_setBuildCatapultDecreaseFactor` | `0054BD70` | LuaProps_ai_setBuildCatapultDecreaseFactor | `fn::LuaProps_ai_setBuildCatapultDecreaseFactor` | yes |
| `properties.ai_setCatapultAttackFailedFactor` | `0054BDC0` | LuaProps_ai_setCatapultAttackFailedFactor | `fn::LuaProps_ai_setCatapultAttackFailedFactor` | yes |
| `properties.ai_setCatapultEnemyThreatFactor` | `0054BE60` | LuaProps_ai_setCatapultEnemyThreatFactor | `fn::LuaProps_ai_setCatapultEnemyThreatFactor` | yes |
| `properties.ai_setCatapultFriendThreatFactor` | `0054BE10` | LuaProps_ai_setCatapultFriendThreatFactor | `fn::LuaProps_ai_setCatapultFriendThreatFactor` | yes |
| `properties.ai_setConstructCatapultRating` | `0054BEB0` | LuaProps_ai_setConstructCatapultRating | `fn::LuaProps_ai_setConstructCatapultRating` | yes |
| `properties.ai_setCatapultConstructionTime` | `0054BB40` | LuaProps_ai_setCatapultConstructionTime | `fn::LuaProps_ai_setCatapultConstructionTime` | yes |
| `properties.ai_enableAllocation` | `0054BF00` | LuaProps_ai_enableAllocation | `fn::LuaProps_ai_enableAllocation` | yes |
| `properties.ai_setAttackLimiterDelay` | `0054BBE0` | LuaProps_ai_setAttackLimiterDelay | `fn::LuaProps_ai_setAttackLimiterDelay` | yes |
| `properties.ai_setAttackLimiterDelayRandom` | `0054BC30` | LuaProps_ai_setAttackLimiterDelayRandom | `fn::LuaProps_ai_setAttackLimiterDelayRandom` | yes |
| `properties.ai_setAttackLimiterAttackCount` | `0054BC80` | LuaProps_ai_setAttackLimiterAttackCount | `fn::LuaProps_ai_setAttackLimiterAttackCount` | yes |
| `properties.ai_setAttackLimiterAttackCountRandom` | `0054BCD0` | LuaProps_ai_setAttackLimiterAttackCountRandom | `fn::LuaProps_ai_setAttackLimiterAttackCountRandom` | yes |
| `properties.ai_setConstructionTicker` | `0054BB90` | LuaProps_ai_setConstructionTicker | `fn::LuaProps_ai_setConstructionTicker` | yes |
| `properties.cfg_setSettlerSkeletonDoodad` | `0054C220` | LuaProps_cfg_setSettlerSkeletonDoodad | `fn::LuaProps_cfg_setSettlerSkeletonDoodad` | yes |
| `properties.cfg_setSettlerDyingTime` | `0054C250` | LuaProps_cfg_setSettlerDyingTime | `fn::LuaProps_cfg_setSettlerDyingTime` | yes |
| `properties.cfg_setCatapultRotationTimeFactor` | `0054C280` | LuaProps_cfg_setCatapultRotationTimeFactor | `fn::LuaProps_cfg_setCatapultRotationTimeFactor` | yes |
| `properties.cfg_setCatapultFlightTimeFactor` | `0054C2D0` | LuaProps_cfg_setCatapultFlightTimeFactor | `fn::LuaProps_cfg_setCatapultFlightTimeFactor` | yes |
| `properties.cfg_setBowFlightTimeFactor` | `0054C2B0` | LuaProps_cfg_setBowFlightTimeFactor | `fn::LuaProps_cfg_setBowFlightTimeFactor` | yes |
| `properties.cfg_setFishingDistance` | `0054C300` | LuaProps_cfg_setFishingDistance | `fn::LuaProps_cfg_setFishingDistance` | yes |
| `properties.cfg_setSettlerSpeed` | `0054C330` | LuaProps_cfg_setSettlerSpeed | `fn::LuaProps_cfg_setSettlerSpeed` | yes |
| `properties.cfg_setSpawnPointUpdateTime` | `0054C360` | LuaProps_cfg_setSpawnPointUpdateTime | `fn::LuaProps_cfg_setSpawnPointUpdateTime` | yes |
| `properties.cfg_setGameSpeed` | `0054C380` | LuaProps_cfg_setGameSpeed | `fn::LuaProps_cfg_setGameSpeed` | no |
| `properties.cfg_setBorderPattern` | `0054C3B0` | LuaProps_cfg_setBorderPattern | `fn::LuaProps_cfg_setBorderPattern` | yes |
| `properties.cfg_setPickupTime` | `0054C410` | LuaProps_cfg_setPickupTime | `fn::LuaProps_cfg_setPickupTime` | yes |
| `properties.cfg_setDropTime` | `0054C440` | LuaProps_cfg_setDropTime | `fn::LuaProps_cfg_setDropTime` | yes |
| `properties.cfg_setBulldozeTime` | `0054C470` | LuaProps_cfg_setBulldozeTime | `fn::LuaProps_cfg_setBulldozeTime` | yes |
| `properties.cfg_setFlagPackageLimit` | `0054C4A0` | LuaProps_cfg_setFlagPackageLimit | `fn::LuaProps_cfg_setFlagPackageLimit` | yes |
| `properties.cfg_setConstructTime` | `0054C3E0` | LuaProps_cfg_setConstructTime | `fn::LuaProps_cfg_setConstructTime` | yes |
| `properties.cfg_setMaxWaterStreetWaterDepth` | `0054C200` | LuaProps_cfg_setMaxWaterStreetWaterDepth | `fn::LuaProps_cfg_setMaxWaterStreetWaterDepth` | yes |
| `properties.cfg_setChestDoodadId` | `0054C1C0` | LuaProps_cfg_setChestDoodadId | `fn::LuaProps_cfg_setChestDoodadId` | yes |
| `properties.cfg_setOpenChestDoodadId` | `0054C1A0` | LuaProps_cfg_setOpenChestDoodadId | `fn::LuaProps_cfg_setOpenChestDoodadId` | yes |
| `properties.cfg_setChestOwningTime` | `0054C1E0` | LuaProps_cfg_setChestOwningTime | `fn::LuaProps_cfg_setChestOwningTime` | no |
| `properties.cfg_setSacrificeGoodId` | `0054C180` | LuaProps_cfg_setSacrificeGoodId | `fn::LuaProps_cfg_setSacrificeGoodId` | yes |
| `properties.sn_create` | `00550880` | LuaProps_sn_create | `fn::LuaProps_sn_create` | yes |
| `properties.sn_setPercussion` | `00550980` | LuaProps_sn_setPercussion | `fn::LuaProps_sn_setPercussion` | yes |
| `properties.sn_setMusicTribe` | `005509D0` | LuaProps_sn_setMusicTribe | `fn::LuaProps_sn_setMusicTribe` | yes |
| `properties.sn_setName` | `00550A20` | LuaProps_sn_setName | `fn::LuaProps_sn_setName` | yes |
| `properties.sn_addFileName` | `00550AF0` | LuaProps_sn_addFileName | `fn::LuaProps_sn_addFileName` | yes |
| `properties.sn_setType` | `00550C10` | LuaProps_sn_setType | `fn::LuaProps_sn_setType` | yes |
| `properties.sn_setLooping` | `00550BC0` | LuaProps_sn_setLooping | `fn::LuaProps_sn_setLooping` | yes |
| `properties.sn_setVolume` | `00550C60` | LuaProps_sn_setVolume | `fn::LuaProps_sn_setVolume` | yes |
| `properties.sn_setPriority` | `00550CB0` | LuaProps_sn_setPriority | `fn::LuaProps_sn_setPriority` | yes |
| `properties.sn_set3DMinDistance` | `00550D00` | LuaProps_sn_set3DMinDistance | `fn::LuaProps_sn_set3DMinDistance` | yes |
| `properties.sn_set3DMaxDistance` | `00550D50` | LuaProps_sn_set3DMaxDistance | `fn::LuaProps_sn_set3DMaxDistance` | no |
| `properties.sn_set2DDistance` | `00550DF0` | LuaProps_sn_set2DDistance | `fn::LuaProps_sn_set2DDistance` | yes |
| `properties.sn_set3DSound` | `00550DA0` | LuaProps_sn_set3DSound | `fn::LuaProps_sn_set3DSound` | yes |
| `properties.an_create` | `0054C5C0` | LuaProps_an_create | `fn::LuaProps_an_create` | yes |
| `properties.an_setAvoidBuildings` | `0054C570` | LuaProps_an_setAvoidBuildings | `fn::LuaProps_an_setAvoidBuildings` | yes |
| `properties.an_setName` | `0054C6B0` | LuaProps_an_setName | `fn::LuaProps_an_setName` | yes |
| `properties.an_setGfxName` | `0054C780` | LuaProps_an_setGfxName | `fn::LuaProps_an_setGfxName` | yes |
| `properties.an_setRange` | `0054C850` | LuaProps_an_setRange | `fn::LuaProps_an_setRange` | yes |
| `properties.an_setMoveDistance` | `0054C920` | LuaProps_an_setMoveDistance | `fn::LuaProps_an_setMoveDistance` | yes |
| `properties.an_setMovementSpeed` | `0054C970` | LuaProps_an_setMovementSpeed | `fn::LuaProps_an_setMovementSpeed` | yes |
| `properties.an_setIdleTimeFactor` | `0054C9C0` | LuaProps_an_setIdleTimeFactor | `fn::LuaProps_an_setIdleTimeFactor` | no |
| `properties.an_addStackGood` | `0054C510` | LuaProps_an_addStackGood | `fn::LuaProps_an_addStackGood` | yes |
| `properties.an_setRespawn` | `0054C4D0` | LuaProps_an_setRespawn | `fn::LuaProps_an_setRespawn` | yes |
| `properties.an_setDyingTime` | `0054C8A0` | LuaProps_an_setDyingTime | `fn::LuaProps_an_setDyingTime` | yes |
| `properties.an_setDisappearingTime` | `0054C8E0` | LuaProps_an_setDisappearingTime | `fn::LuaProps_an_setDisappearingTime` | yes |
| `properties.sh_setSpeed` | `0054CAA0` | LuaProps_sh_setSpeed | `fn::LuaProps_sh_setSpeed` | yes |
| `properties.sh_setSize` | `0054CAE0` | LuaProps_sh_setSize | `fn::LuaProps_sh_setSize` | yes |
| `properties.sh_setConstructTime` | `0054CB10` | LuaProps_sh_setConstructTime | `fn::LuaProps_sh_setConstructTime` | yes |
| `properties.sh_setStockLimit` | `0054CA70` | LuaProps_sh_setStockLimit | `fn::LuaProps_sh_setStockLimit` | yes |
| `properties.sh_setExpeditionBuilding` | `0054CA30` | LuaProps_sh_setExpeditionBuilding | `fn::LuaProps_sh_setExpeditionBuilding` | yes |
| `properties.sh_setWaitTime` | `0054CA10` | LuaProps_sh_setWaitTime | `fn::LuaProps_sh_setWaitTime` | yes |
| `properties.sh_setSinkingTime` | `0054CB40` | LuaProps_sh_setSinkingTime | `fn::LuaProps_sh_setSinkingTime` | yes |
| `properties.mi_setSoldierId` | `0054CB60` | LuaProps_mi_setSoldierId | `fn::LuaProps_mi_setSoldierId` | yes |
| `properties.mi_setRegenerationRate` | `0054CBF0` | LuaProps_mi_setRegenerationRate | `fn::LuaProps_mi_setRegenerationRate` | yes |
| `properties.mi_setWaitForTacticTime` | `0054CC20` | LuaProps_mi_setWaitForTacticTime | `fn::LuaProps_mi_setWaitForTacticTime` | yes |
| `properties.mi_setActionsInFightDelayTime` | `0054CBC0` | LuaProps_mi_setActionsInFightDelayTime | `fn::LuaProps_mi_setActionsInFightDelayTime` | yes |
| `properties.mi_setHealthExchangeDistance` | `0054CC50` | LuaProps_mi_setHealthExchangeDistance | `fn::LuaProps_mi_setHealthExchangeDistance` | yes |
| `properties.sp_create` | `0054A4D0` | LuaProps_sp_create | `fn::LuaProps_sp_create` | yes |
| `properties.sp_setName` | `0054A5C0` | LuaProps_sp_setName | `fn::LuaProps_sp_setName` | yes |
| `properties.sp_addUniqueId` | `0054A830` | LuaProps_sp_addUniqueId | `fn::LuaProps_sp_addUniqueId` | yes |
| `properties.sp_setRange` | `0054A8E0` | LuaProps_sp_setRange | `fn::LuaProps_sp_setRange` | no |
| `properties.sp_setGfxName` | `0054A690` | LuaProps_sp_setGfxName | `fn::LuaProps_sp_setGfxName` | yes |
| `properties.sp_setParticleName` | `0054A760` | LuaProps_sp_setParticleName | `fn::LuaProps_sp_setParticleName` | yes |
| `properties.sp_setType` | `0054A930` | LuaProps_sp_setType | `fn::LuaProps_sp_setType` | yes |
| `properties.sp_setRate` | `0054A890` | LuaProps_sp_setRate | `fn::LuaProps_sp_setRate` | no |
| `properties.gp_create` | `0054EA60` | LuaProps_gp_create | `fn::LuaProps_gp_create` | yes |
| `properties.gp_setName` | `0054E6D0` | LuaProps_gp_setName | `fn::LuaProps_gp_setName` | yes |
| `properties.gp_setShortName` | `0054E7A0` | LuaProps_gp_setShortName | `fn::LuaProps_gp_setShortName` | no |
| `properties.gp_enableDeposits` | `0054E870` | LuaProps_gp_enableDeposits | `fn::LuaProps_gp_enableDeposits` | yes |
| `properties.gp_enableFields` | `0054E8C0` | LuaProps_gp_enableFields | `fn::LuaProps_gp_enableFields` | yes |
| `properties.gp_setType` | `0054E960` | LuaProps_gp_setType | `fn::LuaProps_gp_setType` | yes |
| `properties.gp_addCost` | `0054E9B0` | LuaProps_gp_addCost | `fn::LuaProps_gp_addCost` | yes |
| `properties.gp_setValue` | `0054E910` | LuaProps_gp_setValue | `fn::LuaProps_gp_setValue` | no |
| `properties.gp_setTransportPriority` | `0054E670` | LuaProps_gp_setTransportPriority | `fn::LuaProps_gp_setTransportPriority` | yes |
| `properties.gp_setAiPriority` | `0054E610` | LuaProps_gp_setAiPriority | `fn::LuaProps_gp_setAiPriority` | yes |
| `properties.gp_setPlantable` | `0054E5C0` | LuaProps_gp_setPlantable | `fn::LuaProps_gp_setPlantable` | yes |
| `properties.gp_setArrangementGoodId` | `0054E580` | LuaProps_gp_setArrangementGoodId | `fn::LuaProps_gp_setArrangementGoodId` | yes |
| `properties.gp_setGfxGoodId` | `0054E4F0` | LuaProps_gp_setGfxGoodId | `fn::LuaProps_gp_setGfxGoodId` | yes |
| `properties.gp_setSettlerType` | `0054E4B0` | LuaProps_gp_setSettlerType | `fn::LuaProps_gp_setSettlerType` | yes |
| `properties.gp_setSoldierType` | `0054E460` | LuaProps_gp_setSoldierType | `fn::LuaProps_gp_setSoldierType` | yes |
| `properties.gp_setHitDamage` | `0054EC00` | LuaProps_gp_setHitDamage | `fn::LuaProps_gp_setHitDamage` | yes |
| `properties.gp_setHealth` | `0054E410` | LuaProps_gp_setHealth | `fn::LuaProps_gp_setHealth` | yes |
| `properties.gp_setAiRandomValue` | `0054EC50` | LuaProps_gp_setAiRandomValue | `fn::LuaProps_gp_setAiRandomValue` | yes |
| `properties.gp_setBlockingChance` | `0054E320` | LuaProps_gp_setBlockingChance | `fn::LuaProps_gp_setBlockingChance` | yes |
| `properties.gp_setArmor` | `0054E370` | LuaProps_gp_setArmor | `fn::LuaProps_gp_setArmor` | yes |
| `properties.gp_setAttackWaitTime` | `0054E3C0` | LuaProps_gp_setAttackWaitTime | `fn::LuaProps_gp_setAttackWaitTime` | yes |
| `properties.gp_setAttackTime` | `0054E2D0` | LuaProps_gp_setAttackTime | `fn::LuaProps_gp_setAttackTime` | yes |
| `properties.gp_setBowRange` | `0054E280` | LuaProps_gp_setBowRange | `fn::LuaProps_gp_setBowRange` | yes |
| `properties.gp_setAINoNeedForCosts` | `0054E240` | LuaProps_gp_setAINoNeedForCosts | `fn::LuaProps_gp_setAINoNeedForCosts` | yes |
| `properties.gp_addHitTime` | `0054EBA0` | LuaProps_gp_addHitTime | `fn::LuaProps_gp_addHitTime` | yes |
| `properties.gp_setProjectileType` | `0054EB50` | LuaProps_gp_setProjectileType | `fn::LuaProps_gp_setProjectileType` | yes |
| `properties.gp_setMiningGood` | `0054E530` | LuaProps_gp_setMiningGood | `fn::LuaProps_gp_setMiningGood` | yes |
| `properties.bp_create` | `0054DA80` | LuaProps_bp_create | `fn::LuaProps_bp_create` | yes |
| `properties.bp_setProductionTime` | `0054CF00` | LuaProps_bp_setProductionTime | `fn::LuaProps_bp_setProductionTime` | yes |
| `properties.bp_setDepot` | `0054D320` | LuaProps_bp_setDepot | `fn::LuaProps_bp_setDepot` | yes |
| `properties.bp_setName` | `0054D090` | LuaProps_bp_setName | `fn::LuaProps_bp_setName` | yes |
| `properties.bp_setCatapult` | `0054D040` | LuaProps_bp_setCatapult | `fn::LuaProps_bp_setCatapult` | yes |
| `properties.bp_setGfxName` | `0054D160` | LuaProps_bp_setGfxName | `fn::LuaProps_bp_setGfxName` | yes |
| `properties.bp_setHealth` | `0054D280` | LuaProps_bp_setHealth | `fn::LuaProps_bp_setHealth` | yes |
| `properties.bp_setWorkingRadius` | `0054D410` | LuaProps_bp_setWorkingRadius | `fn::LuaProps_bp_setWorkingRadius` | yes |
| `properties.bp_setSize` | `0054D230` | LuaProps_bp_setSize | `fn::LuaProps_bp_setSize` | yes |
| `properties.bp_setSpawn` | `0054D2D0` | LuaProps_bp_setSpawn | `fn::LuaProps_bp_setSpawn` | yes |
| `properties.bp_setGoods` | `0054D460` | LuaProps_bp_setGoods | `fn::LuaProps_bp_setGoods` | yes |
| `properties.bp_setSecondGoods` | `0054D4C0` | LuaProps_bp_setSecondGoods | `fn::LuaProps_bp_setSecondGoods` | yes |
| `properties.bp_setConstructionTime` | `0054D720` | LuaProps_bp_setConstructionTime | `fn::LuaProps_bp_setConstructionTime` | yes |
| `properties.bp_setConstructionPosition` | `0054D7E0` | LuaProps_bp_setConstructionPosition | `fn::LuaProps_bp_setConstructionPosition` | yes |
| `properties.bp_addCost` | `0054D570` | LuaProps_bp_addCost | `fn::LuaProps_bp_addCost` | yes |
| `properties.bp_addFrameCost` | `0054D620` | LuaProps_bp_addFrameCost | `fn::LuaProps_bp_addFrameCost` | yes |
| `properties.bp_setStockLimit` | `0054D6D0` | LuaProps_bp_setStockLimit | `fn::LuaProps_bp_setStockLimit` | yes |
| `properties.bp_setWorker` | `0054D850` | LuaProps_bp_setWorker | `fn::LuaProps_bp_setWorker` | yes |
| `properties.bp_setWorkerLimit` | `0054D8A0` | LuaProps_bp_setWorkerLimit | `fn::LuaProps_bp_setWorkerLimit` | yes |
| `properties.bp_setTerritoryRange` | `0054D8F0` | LuaProps_bp_setTerritoryRange | `fn::LuaProps_bp_setTerritoryRange` | yes |
| `properties.bp_setSoldierLimit` | `0054D940` | LuaProps_bp_setSoldierLimit | `fn::LuaProps_bp_setSoldierLimit` | yes |
| `properties.bp_setDoorOffsetDirection` | `0054D990` | LuaProps_bp_setDoorOffsetDirection | `fn::LuaProps_bp_setDoorOffsetDirection` | yes |
| `properties.bp_setRemains` | `0054D9E0` | LuaProps_bp_setRemains | `fn::LuaProps_bp_setRemains` | yes |
| `properties.bp_setExploreRadius` | `0054DA30` | LuaProps_bp_setExploreRadius | `fn::LuaProps_bp_setExploreRadius` | yes |
| `properties.bp_setAiScore` | `0054CFA0` | LuaProps_bp_setAiScore | `fn::LuaProps_bp_setAiScore` | yes |
| `properties.bp_setAiThreat` | `0054CFF0` | LuaProps_bp_setAiThreat | `fn::LuaProps_bp_setAiThreat` | yes |
| `properties.bp_setPlantingDeposit` | `0054CF50` | LuaProps_bp_setPlantingDeposit | `fn::LuaProps_bp_setPlantingDeposit` | yes |
| `properties.bp_setCatapultDamage` | `0054DB70` | LuaProps_bp_setCatapultDamage | `fn::LuaProps_bp_setCatapultDamage` | yes |
| `properties.bp_setRestTime` | `0054D520` | LuaProps_bp_setRestTime | `fn::LuaProps_bp_setRestTime` | yes |
| `properties.bp_setArrangementValue` | `0054DBC0` | LuaProps_bp_setArrangementValue | `fn::LuaProps_bp_setArrangementValue` | yes |
| `properties.bp_setUpgrade` | `0054CEB0` | LuaProps_bp_setUpgrade | `fn::LuaProps_bp_setUpgrade` | yes |
| `properties.bp_setIgnoreGoodCosts` | `0054CE60` | LuaProps_bp_setIgnoreGoodCosts | `fn::LuaProps_bp_setIgnoreGoodCosts` | yes |
| `properties.bp_setWorkingMode` | `0054CD30` | LuaProps_bp_setWorkingMode | `fn::LuaProps_bp_setWorkingMode` | yes |
| `properties.bp_setCasern` | `0054D3C0` | LuaProps_bp_setCasern | `fn::LuaProps_bp_setCasern` | yes |
| `properties.bp_setTerritoryBuilding` | `0054D370` | LuaProps_bp_setTerritoryBuilding | `fn::LuaProps_bp_setTerritoryBuilding` | yes |
| `properties.bp_setProducedSettler` | `0054CCE0` | LuaProps_bp_setProducedSettler | `fn::LuaProps_bp_setProducedSettler` | yes |
| `properties.bp_setArrangementLocked` | `0054CDD0` | LuaProps_bp_setArrangementLocked | `fn::LuaProps_bp_setArrangementLocked` | yes |
| `properties.bp_setGfxBreeding` | `0054CD80` | LuaProps_bp_setGfxBreeding | `fn::LuaProps_bp_setGfxBreeding` | yes |
| `properties.bp_setIdlePosition` | `0054D770` | LuaProps_bp_setIdlePosition | `fn::LuaProps_bp_setIdlePosition` | yes |
| `properties.bp_setNoProductivity` | `0054CE20` | LuaProps_bp_setNoProductivity | `fn::LuaProps_bp_setNoProductivity` | yes |
| `properties.rm_create` | `0054FA80` | LuaProps_rm_create | `fn::LuaProps_rm_create` | yes |
| `properties.rm_setName` | `0054FB80` | LuaProps_rm_setName | `fn::LuaProps_rm_setName` | yes |
| `properties.rm_setGfxName` | `0054FC50` | LuaProps_rm_setGfxName | `fn::LuaProps_rm_setGfxName` | yes |
| `properties.rm_setBurningTime` | `0054FD20` | LuaProps_rm_setBurningTime | `fn::LuaProps_rm_setBurningTime` | yes |
| `properties.rm_setDoodadAfterFinished` | `0054FD70` | LuaProps_rm_setDoodadAfterFinished | `fn::LuaProps_rm_setDoodadAfterFinished` | no |
| `properties.dd_create` | `0054FE10` | LuaProps_dd_create | `fn::LuaProps_dd_create` | yes |
| `properties.dd_setBlocking` | `0054FDC0` | LuaProps_dd_setBlocking | `fn::LuaProps_dd_setBlocking` | yes |
| `properties.dd_setName` | `0054FF10` | LuaProps_dd_setName | `fn::LuaProps_dd_setName` | yes |
| `properties.dd_setGfxName` | `0054FFE0` | LuaProps_dd_setGfxName | `fn::LuaProps_dd_setGfxName` | yes |
| `properties.dd_setLifeTime` | `00550100` | LuaProps_dd_setLifeTime | `fn::LuaProps_dd_setLifeTime` | yes |
| `properties.dd_setOnWater` | `005500B0` | LuaProps_dd_setOnWater | `fn::LuaProps_dd_setOnWater` | no |
| `properties.dd_setDeleteByStreet` | `00550150` | LuaProps_dd_setDeleteByStreet | `fn::LuaProps_dd_setDeleteByStreet` | yes |
| `properties.dd_setType` | `005501A0` | LuaProps_dd_setType | `fn::LuaProps_dd_setType` | yes |
| `properties.dd_setIndestructable` | `005501F0` | LuaProps_dd_setIndestructable | `fn::LuaProps_dd_setIndestructable` | yes |
| `properties.dp_create` | `0054E150` | LuaProps_dp_create | `fn::LuaProps_dp_create` | yes |
| `properties.dp_setNeedForPlantablePattern` | `0054DC60` | LuaProps_dp_setNeedForPlantablePattern | `fn::LuaProps_dp_setNeedForPlantablePattern` | yes |
| `properties.dp_setLifeTime` | `0054DCB0` | LuaProps_dp_setLifeTime | `fn::LuaProps_dp_setLifeTime` | yes |
| `properties.dp_addUndergroundPattern` | `0054DD00` | LuaProps_dp_addUndergroundPattern | `fn::LuaProps_dp_addUndergroundPattern` | yes |
| `properties.dp_setName` | `0054DD50` | LuaProps_dp_setName | `fn::LuaProps_dp_setName` | yes |
| `properties.dp_setGfxName` | `0054DF10` | LuaProps_dp_setGfxName | `fn::LuaProps_dp_setGfxName` | yes |
| `properties.dp_setGood` | `0054DFE0` | LuaProps_dp_setGood | `fn::LuaProps_dp_setGood` | yes |
| `properties.dp_nextDeposit` | `0054DEC0` | LuaProps_dp_nextDeposit | `fn::LuaProps_dp_nextDeposit` | yes |
| `properties.dp_setRandomFinePosOffsetState` | `0054E0B0` | LuaProps_dp_setRandomFinePosOffsetState | `fn::LuaProps_dp_setRandomFinePosOffsetState` | yes |
| `properties.dp_setElevationSize` | `0054E100` | LuaProps_dp_setElevationSize | `fn::LuaProps_dp_setElevationSize` | yes |
| `properties.dp_setGrowingSpeed` | `0054E030` | LuaProps_dp_setGrowingSpeed | `fn::LuaProps_dp_setGrowingSpeed` | yes |
| `properties.dp_setGrowingStartSize` | `0054E070` | LuaProps_dp_setGrowingStartSize | `fn::LuaProps_dp_setGrowingStartSize` | yes |
| `properties.dp_setBlocking` | `0054DE20` | LuaProps_dp_setBlocking | `fn::LuaProps_dp_setBlocking` | yes |
| `properties.dp_setDoodadAfterDestruction` | `0054DE70` | LuaProps_dp_setDoodadAfterDestruction | `fn::LuaProps_dp_setDoodadAfterDestruction` | no |
| `properties.dp_addTreeType` | `0054DC10` | LuaProps_dp_addTreeType | `fn::LuaProps_dp_addTreeType` | yes |
| `properties.pa_setMiniMapColor` | `0054EEF0` | LuaProps_pa_setMiniMapColor | `fn::LuaProps_pa_setMiniMapColor` | yes |
| `properties.pa_setName` | `0054ECA0` | LuaProps_pa_setName | `fn::LuaProps_pa_setName` | yes |
| `properties.pa_setGfxName` | `0054F050` | LuaProps_pa_setGfxName | `fn::LuaProps_pa_setGfxName` | yes |
| `properties.pa_create` | `0054EF60` | LuaProps_pa_create | `fn::LuaProps_pa_create` | yes |
| `properties.pa_setBlocked` | `0054EDB0` | LuaProps_pa_setBlocked | `fn::LuaProps_pa_setBlocked` | yes |
| `properties.pa_setTreeType` | `0054EDF0` | LuaProps_pa_setTreeType | `fn::LuaProps_pa_setTreeType` | yes |
| `properties.pa_setForMining` | `0054EE70` | LuaProps_pa_setForMining | `fn::LuaProps_pa_setForMining` | yes |
| `properties.pa_setForBuilding` | `0054EEB0` | LuaProps_pa_setForBuilding | `fn::LuaProps_pa_setForBuilding` | yes |
| `properties.pa_setForShip` | `0054EE30` | LuaProps_pa_setForShip | `fn::LuaProps_pa_setForShip` | yes |
| `properties.pa_setForPlanting` | `0054ED70` | LuaProps_pa_setForPlanting | `fn::LuaProps_pa_setForPlanting` | yes |
| `properties.sf_create` | `0054F170` | LuaProps_sf_create | `fn::LuaProps_sf_create` | yes |
| `properties.sf_setName` | `0054F260` | LuaProps_sf_setName | `fn::LuaProps_sf_setName` | yes |
| `properties.sf_setGfxName` | `0054F330` | LuaProps_sf_setGfxName | `fn::LuaProps_sf_setGfxName` | yes |
| `properties.sf_setDuration` | `0054F4D0` | LuaProps_sf_setDuration | `fn::LuaProps_sf_setDuration` | yes |
| `properties.sf_addCost` | `0054F520` | LuaProps_sf_addCost | `fn::LuaProps_sf_addCost` | yes |
| `properties.sf_addEffect` | `0054F670` | LuaProps_sf_addEffect | `fn::LuaProps_sf_addEffect` | yes |
| `properties.sf_setAbortable` | `0054F6F0` | LuaProps_sf_setAbortable | `fn::LuaProps_sf_setAbortable` | yes |
| `properties.sf_setCategory` | `0054F120` | LuaProps_sf_setCategory | `fn::LuaProps_sf_setCategory` | yes |
| `properties.sf_setBuffGfxName` | `0054F400` | LuaProps_sf_setBuffGfxName | `fn::LuaProps_sf_setBuffGfxName` | yes |
| `properties.sf_setRegenerationDelay` | `0054F740` | LuaProps_sf_setRegenerationDelay | `fn::LuaProps_sf_setRegenerationDelay` | yes |
| `properties.sf_setTarget` | `0054F790` | LuaProps_sf_setTarget | `fn::LuaProps_sf_setTarget` | yes |
| `properties.sf_addBuildingDependence` | `0054F7E0` | LuaProps_sf_addBuildingDependence | `fn::LuaProps_sf_addBuildingDependence` | no |
| `properties.sf_setResearchDuration` | `0054F830` | LuaProps_sf_setResearchDuration | `fn::LuaProps_sf_setResearchDuration` | yes |
| `properties.sf_setForCampaign` | `0054F880` | LuaProps_sf_setForCampaign | `fn::LuaProps_sf_setForCampaign` | yes |
| `properties.si_addSignDoodadId` | `0054CC80` | LuaProps_si_addSignDoodadId | `fn::LuaProps_si_addSignDoodadId` | yes |

### 3.4 `menu`, `ui`, `txt` — `nMenu::System::Initialize` `005dda30`

Registered at start-up, before `menu.cfg` runs.

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `menu.openBookDialog` | `005DD5E0` | LuaMenu_OpenBookDialog | `fn::LuaMenu_OpenBookDialog` | yes |
| `menu.addPage` | `005DD830` | LuaMenu_AddPage | `fn::LuaMenu_AddPage` | yes |
| `menu.addPicture` | `005DD8E0` | LuaMenu_AddPicture | `fn::LuaMenu_AddPicture` | yes |
| `menu.addDebriefing` | `0072DB80` | Generic_ReturnZero | `fn::Generic_ReturnZero_0072db80` | yes |
| `menu.addExtro` | `0072DB80` | Generic_ReturnZero | `fn::Generic_ReturnZero_0072db80` | no |
| `menu.addCutsceneDebugName` | `005DA8A0` | LuaMenu_AddCutsceneDebugName | `fn::LuaMenu_AddCutsceneDebugName` | yes |
| `menu.createLetter` | `005DA720` | LuaMenu_CreateLetter | `fn::LuaMenu_CreateLetter` | yes |
| `menu.addResource` | `005D9970` | LuaMenu_AddResource | `fn::LuaMenu_AddResource` | yes |
| `menu.clearResources` | `005D9C30` | LuaMenu_ClearResources | `fn::LuaMenu_ClearResources` | yes |
| `menu.lockBuilding` | `005D9C80` | LuaMenu_LockBuilding | `fn::LuaMenu_LockBuilding` | yes |
| `menu.unlockBuilding` | `005D9CE0` | LuaMenu_UnlockBuilding | `fn::LuaMenu_UnlockBuilding` | no |
| `menu.lockJob` | `005D9D40` | LuaMenu_LockJob | `fn::LuaMenu_LockJob` | no |
| `menu.unlockJob` | `005D9DA0` | LuaMenu_UnlockJob | `fn::LuaMenu_UnlockJob` | no |
| `menu.lockSacrifice` | `005DAB40` | LuaMenu_LockSacrifice | `fn::LuaMenu_LockSacrifice` | yes |
| `menu.unlockSacrifice` | `005DABD0` | LuaMenu_UnlockSacrifice | `fn::LuaMenu_UnlockSacrifice` | no |
| `menu.addSacrifice` | `005DAC60` | LuaMenu_AddSacrifice | `fn::LuaMenu_AddSacrifice` | yes |
| `menu.showSacrificeEffect` | `005D9550` | FUN_005d9550 | — (unnamed in Ghidra; not generated) | yes |
| `menu.setPlayerColor` | `005D9E00` | LuaMenu_SetPlayerColor | `fn::LuaMenu_SetPlayerColor` | yes |
| `menu.createBuilding` | `005D9A30` | LuaMenu_CreateBuilding | `fn::LuaMenu_CreateBuilding` | yes |
| `menu.createBuildingWithSettler` | `005D9AC0` | LuaMenu_CreateBuildingWithSettler | `fn::LuaMenu_CreateBuildingWithSettler` | yes |
| `menu.createStreet` | `005DADA0` | LuaMenu_CreateStreet | `fn::LuaMenu_CreateStreet` | yes |
| `menu.setLanguage` | `005DD780` | LuaMenu_SetLanguage | `fn::LuaMenu_SetLanguage` | yes |
| `menu.setVideoVoiceStream` | `005DD6C0` | LuaMenu_SetVideoVoiceStream | `fn::LuaMenu_SetVideoVoiceStream` | yes |
| `menu.addMinimapSymbol` | `005DD990` | LuaMenu_AddMinimapSymbol | `fn::LuaMenu_AddMinimapSymbol` | yes |
| `menu.removeMinimapSymbol` | `005DD9E0` | LuaMenu_RemoveMinimapSymbol | `fn::LuaMenu_RemoveMinimapSymbol` | yes |
| `menu.startCinematic` | `005DD3C0` | LuaMenu_StartCinematic | `fn::LuaMenu_StartCinematic` | yes |
| `menu.addCinematicPage` | `005DD410` | LuaMenu_AddCinematicPage | `fn::LuaMenu_AddCinematicPage` | yes |
| `menu.showMinimap` | `005D9530` | FUN_005d9530 | — (unnamed in Ghidra; not generated) | no |
| `menu.updateCinematic` | `005DD5C0` | nMenu_CallForegroundScreensSlot1 | `fn::nMenu_CallForegroundScreensSlot1` (address only) | yes |
| `menu.allowActions` | `005D9570` | LuaMenu_AllowActions | `fn::LuaMenu_AllowActions` | yes |
| `menu.addTutorialPage` | `005DAA30` | LuaMenu_AddTutorialPage | `fn::LuaMenu_AddTutorialPage` | yes |

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `ui.infoText` | `005DC8C0` | LuaUi_InfoText | `fn::LuaUi_InfoText` | yes |
| `ui.infoLabel` | `005DCBC0` | LuaUi_InfoLabel | `fn::LuaUi_InfoLabel` | yes |
| `ui.infoPicture` | `005DD010` | LuaUi_InfoPicture | `fn::LuaUi_InfoPicture` | yes |
| `ui.infoLabel2` | `005DCDE0` | LuaUi_InfoLabel2 | `fn::LuaUi_InfoLabel2` | yes |
| `ui.createCheckedButton` | `005DBD40` | LuaUi_CreateCheckedButton | `fn::LuaUi_CreateCheckedButton` | yes |
| `ui.createTextBlock` | `005DB990` | LuaUi_CreateTextBlock | `fn::LuaUi_CreateTextBlock` | yes |
| `ui.createLabel` | `005DB700` | LuaUi_CreateLabel | `fn::LuaUi_CreateLabel` | yes |
| `ui.createPicture` | `005DB370` | LuaUi_CreatePicture | `fn::LuaUi_CreatePicture` | yes |
| `ui.createIcon` | `005DBF80` | LuaUi_CreateIcon | `fn::LuaUi_CreateIcon` | no |
| `ui.isDialogCreated` | `005DC880` | LuaUi_IsDialogCreated | `fn::LuaUi_IsDialogCreated` | no |
| `ui.show` | `005DC6A0` | LuaUi_Show | `fn::LuaUi_Show` | yes |
| `ui.enable` | `005DC790` | LuaUi_Enable | `fn::LuaUi_Enable` | no |
| `ui.setContent` | `005DC4D0` | LuaUi_SetContent | `fn::LuaUi_SetContent` | yes |
| `ui.setMarkFlag` | `005DC3D0` | LuaUi_SetMarkFlag | `fn::LuaUi_SetMarkFlag` | yes |

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `txt.isValid` | `005DA660` | LuaTxt_IsValid | `fn::LuaTxt_IsValid` | yes |

### 3.5 `ui` (widget functions) — `LuaUi_RegisterLibrary` `004c5ab0`

Registered lazily: `LuaUi_EnsureRegistered` `004c5cc0` runs it once (guard bit at `00885db8`) the first time a
button fires its Lua event (§4.2) [known]. Adds to the same `ui` table as §3.4 [inferred].

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `ui.enableObject` | `004C4BC0` | LuaUi_enableObject | `fn::LuaUi_enableObject` | no |
| `ui.enableAllButtons` | `004C4480` | LuaCB_CallWithBoolArg1 | `fn::LuaCB_CallWithBoolArg1` | no |
| `ui.setYpos` | `004C4A40` | LuaUi_setYpos | `fn::LuaUi_setYpos` | no |
| `ui.setXpos` | `004C48C0` | LuaUi_setXpos | `fn::LuaUi_setXpos` | no |
| `ui.setHeight` | `004C4750` | LuaUi_setHeight | `fn::LuaUi_setHeight` | no |
| `ui.setWidth` | `004C45E0` | LuaUi_setWidth | `fn::LuaUi_setWidth` | no |
| `ui.setVisible` | `004C44D0` | LuaUi_setVisible | `fn::LuaUi_setVisible` | no |
| `ui.setAlignY` | `004C4E10` | LuaUi_setAlignY | `fn::LuaUi_setAlignY` | no |
| `ui.setAlignX` | `004C4CD0` | LuaUi_setAlignX | `fn::LuaUi_setAlignX` | no |
| `ui.centerCursor` | `004C4F50` | LuaUi_centerCursor | `fn::LuaUi_centerCursor` | no |
| `ui.setName` | `004C5060` | LuaUi_setName | `fn::LuaUi_setName` | no |
| `ui.setFocus` | `004C51D0` | LuaUi_setFocus | `fn::LuaUi_setFocus` | no |
| `ui.bringToFront` | `004C52B0` | LuaUi_bringToFront | `fn::LuaUi_bringToFront` | no |
| `ui.enableClipping` | `004C53C0` | LuaUi_enableClipping | `fn::LuaUi_enableClipping` | no |
| `ui.setAlpha` | `004C54D0` | LuaUi_setAlpha | `fn::LuaUi_setAlpha` | no |
| `ui.setOpacity` | `004C5600` | LuaUi_setOpacity | `fn::LuaUi_setOpacity` | no |
| `ui.fadeOut` | `004C5850` | LuaUi_fadeOut | `fn::LuaUi_fadeOut` | no |
| `ui.fadeIn` | `004C5730` | LuaUi_fadeIn | `fn::LuaUi_fadeIn` | no |
| `ui.setAnchor` | `004C5970` | LuaUi_setAnchor | `fn::LuaUi_setAnchor` | no |

### 3.6 `logic` and `gfx` — `GameScript_RegisterLuaLibraries` `005b2990`

Registered on the map-script thread during world build, only when `NComm_Manager_IsRole0` (§2.3). Prefixes:
`pl_` player, `map_` map, `ai_` computer player, `vi_` buildings ("village"), `na_` ships ("navy"),
`sd_` persistent script data, `q_` quests, `se_` settlers / NPCs [inferred from names].

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `logic.pl_getReachedPlayerPosition` | `005ACB50` | LuaGame_pl_getReachedPlayerPosition | `fn::LuaGame_pl_getReachedPlayerPosition` | yes |
| `logic.pl_clearResource` | `005ACC10` | LuaGame_pl_clearResource | `fn::LuaGame_pl_clearResource` | yes |
| `logic.pl_halfResources` | `005B0D90` | GameScript_Lua_pl_halfResources | `fn::GameScript_Lua_pl_halfResources` | yes |
| `logic.pl_getUser` | `005ACD20` | GameScript_Lua_pl_getUser | `fn::GameScript_Lua_pl_getUser` | yes |
| `logic.pl_getTribe` | `005ACD50` | LuaGame_pl_getTribe | `fn::LuaGame_pl_getTribe` | no |
| `logic.pl_isPlayerSpotted` | `005ACDD0` | LuaGame_pl_isPlayerSpotted | `fn::LuaGame_pl_isPlayerSpotted` | no |
| `logic.pl_changeTeam` | `005AD010` | LuaGame_pl_changeTeam | `fn::LuaGame_pl_changeTeam` | yes |
| `logic.pl_hasReachedPlayer` | `005AD080` | LuaGame_pl_hasReachedPlayer | `fn::LuaGame_pl_hasReachedPlayer` | yes |
| `logic.pl_getBuildingProductivity` | `005AD3A0` | LuaGame_pl_getBuildingProductivity | `fn::LuaGame_pl_getBuildingProductivity` | yes |
| `logic.pl_hasCastle` | `005AD460` | LuaGame_pl_hasCastle | `fn::LuaGame_pl_hasCastle` | yes |
| `logic.pl_changePlayer` | `005AD4E0` | LuaGame_pl_changePlayer | `fn::LuaGame_pl_changePlayer` | yes |
| `logic.pl_getGoodAmount` | `005AD590` | LuaGame_pl_getGoodAmount | `fn::LuaGame_pl_getGoodAmount` | yes |
| `logic.pl_getMobileGoodAmount` | `005AD630` | LuaGame_pl_getMobileGoodAmount | `fn::LuaGame_pl_getMobileGoodAmount` | yes |
| `logic.pl_sendOrderSacrificeMessage` | `005B1000` | GameScript_Lua_pl_sendOrderSacrificeMessage | `fn::GameScript_Lua_pl_sendOrderSacrificeMessage` | yes |
| `logic.pl_getMilitaryStrength` | `005AD120` | LuaGame_pl_getMilitaryStrength | `fn::LuaGame_pl_getMilitaryStrength` | yes |
| `logic.pl_sacrificeStarted` | `005B0340` | GameScript_Lua_pl_sacrificeStarted | `fn::GameScript_Lua_pl_sacrificeStarted` | yes |
| `logic.pl_sacrificeStartedOnContinent` | `005B0430` | GameScript_Lua_pl_sacrificeStartedOnContinent | `fn::GameScript_Lua_pl_sacrificeStartedOnContinent` | yes |
| `logic.pl_removeResource` | `005B05D0` | GameScript_Lua_pl_removeResource | `fn::GameScript_Lua_pl_removeResource` | yes |
| `logic.pl_getBuildingCount` | `005AD260` | LuaGame_pl_getBuildingCount | `fn::LuaGame_pl_getBuildingCount` | yes |
| `logic.pl_getConstructionCount` | `005AD1B0` | LuaGame_pl_getConstructionCount | `fn::LuaGame_pl_getConstructionCount` | yes |
| `logic.pl_getStreetCount` | `005AF8A0` | GameScript_Lua_pl_getStreetCount | `fn::GameScript_Lua_pl_getStreetCount` | yes |
| `logic.pl_getRegionSize` | `005AD310` | LuaGame_pl_getRegionSize | `fn::LuaGame_pl_getRegionSize` | yes |
| `logic.pl_isAttacking` | `005ACF80` | LuaGame_pl_isAttacking | `fn::LuaGame_pl_isAttacking` | yes |
| `logic.pl_isUnderAttack` | `005ACE70` | LuaGame_pl_isUnderAttack | `fn::LuaGame_pl_isUnderAttack` | yes |
| `logic.pl_getPositionUnderAttack` | `005ACEF0` | LuaGame_pl_getPositionUnderAttack | `fn::LuaGame_pl_getPositionUnderAttack` | yes |
| `logic.pl_getSacrificeState` | `005B0210` | GameScript_Lua_pl_getSacrificeState | `fn::GameScript_Lua_pl_getSacrificeState` | yes |
| `logic.pl_setName` | `005B1170` | GameScript_Lua_pl_setName | `fn::GameScript_Lua_pl_setName` | yes |
| `logic.pl_getProducedGoodCount` | `005B0E80` | GameScript_Lua_pl_getProducedGoodCount | `fn::GameScript_Lua_pl_getProducedGoodCount` | yes |
| `logic.map_removeDoodads` | `005AF910` | GameScript_Lua_map_removeDoodads | `fn::GameScript_Lua_map_removeDoodads` | yes |
| `logic.map_exploreArea` | `005AD960` | GameScript_Lua_map_exploreArea | `fn::GameScript_Lua_map_exploreArea` | yes |
| `logic.map_exchangePatternType` | `005B00E0` | GameScript_Lua_map_exchangePatternType | `fn::GameScript_Lua_map_exchangePatternType` | yes |
| `logic.map_getTerritoryPlayerId` | `005B25D0` | GameScript_Lua_map_getTerritoryPlayerId | `fn::GameScript_Lua_map_getTerritoryPlayerId` | yes |
| `logic.map_createChest` | `005AD740` | LuaGame_map_createChest | `fn::LuaGame_map_createChest` | no |
| `logic.map_createDoodad` | `005AD880` | LuaGame_map_createDoodad | `fn::LuaGame_map_createDoodad` | yes |
| `logic.map_forEachDoodad` | `005B1290` | GameScript_Lua_map_forEachDoodad | `fn::GameScript_Lua_map_forEachDoodad` | no |
| `logic.map_searchConstructionPlace` | `005AFAA0` | GameScript_Lua_map_searchConstructionPlace | `fn::GameScript_Lua_map_searchConstructionPlace` | yes |
| `logic.map_createDeposit` | `005AD7E0` | LuaGame_map_createDeposit | `fn::LuaGame_map_createDeposit` | yes |
| `logic.map_killDeposits` | `005AFC80` | GameScript_Lua_map_killDeposits | `fn::GameScript_Lua_map_killDeposits` | yes |
| `logic.ai_setAttackEnable` | `005ADDD0` | GameScript_Lua_ai_setAttackEnable | `fn::GameScript_Lua_ai_setAttackEnable` | no |
| `logic.ai_allowAttack` | `005ADD70` | GameScript_Lua_ai_allowAttack | `fn::GameScript_Lua_ai_allowAttack` | yes |
| `logic.ai_setAllowedAttackCount` | `005ADE50` | GameScript_Lua_ai_setAllowedAttackCount | `fn::GameScript_Lua_ai_setAllowedAttackCount` | yes |
| `logic.ai_enableExpansion` | `005ADEC0` | GameScript_Lua_ai_enableExpansion | `fn::GameScript_Lua_ai_enableExpansion` | yes |
| `logic.ai_enableNeeds` | `005ADF20` | GameScript_Lua_ai_enableNeeds | `fn::GameScript_Lua_ai_enableNeeds` | no |
| `logic.ai_enableCoinProduction` | `005ADF80` | GameScript_Lua_ai_enableCoinProduction | `fn::GameScript_Lua_ai_enableCoinProduction` | no |
| `logic.ai_enableForesting` | `005ADFE0` | GameScript_Lua_ai_enableForesting | `fn::GameScript_Lua_ai_enableForesting` | yes |
| `logic.ai_enableSacrifices` | `005AE0A0` | GameScript_Lua_ai_enableSacrifices | `fn::GameScript_Lua_ai_enableSacrifices` | yes |
| `logic.ai_enableCatapultsLocal` | `005AE040` | GameScript_Lua_ai_enableCatapultsLocal | `fn::GameScript_Lua_ai_enableCatapultsLocal` | no |
| `logic.ai_enableShipConstruction` | `005AE100` | GameScript_Lua_ai_enableShipConstruction | `fn::GameScript_Lua_ai_enableShipConstruction` | yes |
| `logic.ai_isEnabled` | `005ADA40` | GameScript_Lua_ai_isEnabled | `fn::GameScript_Lua_ai_isEnabled` | yes |
| `logic.ai_enable` | `005B2660` | GameScript_Lua_ai_enable | `fn::GameScript_Lua_ai_enable` | yes |
| `logic.ai_disable` | `005ADD10` | GameScript_Lua_ai_disable | `fn::GameScript_Lua_ai_disable` | yes |
| `logic.ai_allowHarborPosition` | `005ADB50` | GameScript_Lua_ai_allowHarborPosition | `fn::GameScript_Lua_ai_allowHarborPosition` | yes |
| `logic.ai_forbidHarborPosition` | `005ADA90` | GameScript_Lua_ai_forbidHarborPosition | `fn::GameScript_Lua_ai_forbidHarborPosition` | yes |
| `logic.ai_forbidAttackingPlayer` | `005ADC10` | GameScript_Lua_ai_forbidAttackingPlayer | `fn::GameScript_Lua_ai_forbidAttackingPlayer` | yes |
| `logic.ai_allowAttackingPlayer` | `005ADC90` | GameScript_Lua_ai_allowAttackingPlayer | `fn::GameScript_Lua_ai_allowAttackingPlayer` | no |
| `logic.vi_destroyBuilding` | `005AE740` | GameScript_Lua_vi_destroyBuilding | `fn::GameScript_Lua_vi_destroyBuilding` | yes |
| `logic.vi_destroyBuildingsInArea` | `005AFE00` | GameScript_Lua_vi_destroyBuildingsInArea | `fn::GameScript_Lua_vi_destroyBuildingsInArea` | yes |
| `logic.vi_changePlayerOfBuilding` | `005AE830` | GameScript_Lua_vi_changePlayerOfBuilding | `fn::GameScript_Lua_vi_changePlayerOfBuilding` | no |
| `logic.vi_isBuildingAtPosition` | `005AE940` | GameScript_Lua_vi_isBuildingAtPosition | `fn::GameScript_Lua_vi_isBuildingAtPosition` | yes |
| `logic.vi_getBuildingPosition` | `005B0860` | GameScript_Lua_vi_getBuildingPosition | `fn::GameScript_Lua_vi_getBuildingPosition` | yes |
| `logic.vi_forEachBuilding` | `005B14C0` | GameScript_Lua_vi_forEachBuilding | `fn::GameScript_Lua_vi_forEachBuilding` | yes |
| `logic.vi_getFirstBuildingPosition` | `005B0780` | GameScript_Lua_vi_getFirstBuildingPosition | `fn::GameScript_Lua_vi_getFirstBuildingPosition` | yes |
| `logic.vi_addGoodsToDepot` | `005AEA40` | GameScript_Lua_vi_addGoodsToDepot | `fn::GameScript_Lua_vi_addGoodsToDepot` | yes |
| `logic.vi_isMilitaryBuildingAtContinent` | `005AEBB0` | GameScript_Lua_vi_isMilitaryBuildingAtContinent | `fn::GameScript_Lua_vi_isMilitaryBuildingAtContinent` | yes |
| `logic.vi_isSacrificeBuildingAtContinent` | `005B0970` | GameScript_Lua_vi_isSacrificeBuildingAtContinent | `fn::GameScript_Lua_vi_isSacrificeBuildingAtContinent` | yes |
| `logic.vi_allBuildingsDestroyed` | `005B0BC0` | GameScript_Lua_vi_allBuildingsDestroyed | `fn::GameScript_Lua_vi_allBuildingsDestroyed` | yes |
| `logic.vi_orderSacrifice` | `005AEDA0` | GameScript_Lua_vi_orderSacrifice | `fn::GameScript_Lua_vi_orderSacrifice` | yes |
| `logic.vi_countMilitaryBuildings` | `005B0AE0` | GameScript_Lua_vi_countMilitaryBuildings | `fn::GameScript_Lua_vi_countMilitaryBuildings` | yes |
| `logic.vi_enableProduction` | `005AEEC0` | GameScript_Lua_vi_enableProduction | `fn::GameScript_Lua_vi_enableProduction` | yes |
| `logic.vi_startSacrifice` | `005AEC70` | GameScript_Lua_vi_startSacrifice | `fn::GameScript_Lua_vi_startSacrifice` | yes |
| `logic.na_isShipAtPosition` | `005AF0C0` | GameScript_Lua_na_isShipAtPosition | `fn::GameScript_Lua_na_isShipAtPosition` | yes |
| `logic.na_isShipAtRoutePosition` | `005AFF90` | GameScript_Lua_na_isShipAtRoutePosition | `fn::GameScript_Lua_na_isShipAtRoutePosition` | yes |
| `logic.na_isShipOnRoute` | `005AEFE0` | GameScript_Lua_na_isShipOnRoute | `fn::GameScript_Lua_na_isShipOnRoute` | yes |
| `logic.na_sendShip` | `005AF390` | GameScript_Lua_na_sendShip | `fn::GameScript_Lua_na_sendShip` | yes |
| `logic.na_getShipCount` | `005B0C90` | GameScript_Lua_na_getShipCount | `fn::GameScript_Lua_na_getShipCount` | yes |
| `logic.na_createShip` | `005AF4A0` | GameScript_Lua_na_createShip | `fn::GameScript_Lua_na_createShip` | yes |
| `logic.na_destroyShip` | `005AF2A0` | GameScript_Lua_na_destroyShip | `fn::GameScript_Lua_na_destroyShip` | no |
| `logic.na_sinkShipOnRoute` | `005AF1A0` | GameScript_Lua_na_sinkShipOnRoute | `fn::GameScript_Lua_na_sinkShipOnRoute` | yes |
| `logic.sd_setValue` | `005B28B0` | GameScript_Lua_sd_setValue | `fn::GameScript_Lua_sd_setValue` | yes |
| `logic.sd_getValue` | `005B24D0` | GameScript_Lua_sd_getValue | `fn::GameScript_Lua_sd_getValue` | yes |
| `logic.q_add` | `005B1670` | GameScript_Lua_q_add | `fn::GameScript_Lua_q_add` | yes |
| `logic.q_remove` | `005AF580` | GameScript_Lua_q_remove | `fn::GameScript_Lua_q_remove` | yes |
| `logic.q_finish` | `005B1850` | GameScript_Lua_q_finish | `fn::GameScript_Lua_q_finish` | yes |
| `logic.q_hide` | `005AF5E0` | GameScript_Lua_q_hide | `fn::GameScript_Lua_q_hide` | yes |
| `logic.q_isVisible` | `005AF640` | GameScript_Lua_q_isVisible | `fn::GameScript_Lua_q_isVisible` | yes |
| `logic.q_reset` | `005B1980` | GameScript_Lua_q_reset | `fn::GameScript_Lua_q_reset` | yes |
| `logic.q_failed` | `005B1AB0` | GameScript_Lua_q_failed | `fn::GameScript_Lua_q_failed` | yes |
| `logic.q_isFinished` | `005AF720` | GameScript_Lua_q_isFinished | `fn::GameScript_Lua_q_isFinished` | yes |
| `logic.q_updateInfo` | `005B1BE0` | GameScript_Lua_q_updateInfo | `fn::GameScript_Lua_q_updateInfo` | yes |
| `logic.q_isValid` | `005AF790` | GameScript_Lua_q_isValid | `fn::GameScript_Lua_q_isValid` | yes |
| `logic.q_isFailed` | `005AF6B0` | GameScript_Lua_q_isFailed | `fn::GameScript_Lua_q_isFailed` | yes |
| `logic.victory_setupQuests` | `005AF7E0` | FUN_005af7e0 | — (unnamed in Ghidra; not generated) | yes |
| `logic.se_createSettler` | `005AE160` | GameScript_Lua_se_createSettler | `fn::GameScript_Lua_se_createSettler` | no |
| `logic.se_moveNPCTo` | `005AE3B0` | GameScript_Lua_se_moveNPCTo | `fn::GameScript_Lua_se_moveNPCTo` | no |
| `logic.se_moveNPCToFine` | `005AE490` | GameScript_Lua_se_moveNPCToFine | `fn::GameScript_Lua_se_moveNPCToFine` | no |
| `logic.se_isSettlerOnPosition` | `005AE570` | GameScript_Lua_se_isSettlerOnPosition | `fn::GameScript_Lua_se_isSettlerOnPosition` | no |
| `logic.se_activateNPC` | `005AE250` | GameScript_Lua_se_activateNPC | `fn::GameScript_Lua_se_activateNPC` | no |
| `logic.se_deactivateNPC` | `005AE300` | GameScript_Lua_se_deactivateNPC | `fn::GameScript_Lua_se_deactivateNPC` | no |
| `logic.se_NPCLookAt` | `005AE660` | GameScript_Lua_se_NPCLookAt | `fn::GameScript_Lua_se_NPCLookAt` | no |
| `logic.getTick` | `005AD6D0` | GameScript_Lua_getTick | `fn::GameScript_Lua_getTick` | yes |
| `logic.getSpeed` | `005AD6F0` | GameScript_Lua_getSpeed | `fn::GameScript_Lua_getSpeed` | yes |
| `logic.getRandom` | `005AD710` | LuaGame_getRandom | `fn::LuaGame_getRandom` | yes |

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `gfx.createParticel` | `005ACA40` | LuaGame_createParticel | `fn::LuaGame_createParticel` | yes |

`logic.map_forEachDoodad` and `logic.vi_forEachBuilding` take the **name** of a global Lua function and call it
back for each hit with `(x, y)` through `CallGlobal_XY` (§4) [known].

### 3.7 `cutscene` — `ai::camera::CutsceneCamera::LoadScript` `0078ac10`

Registered on the cutscene's temporary thread each time a cutscene script is loaded.

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `cutscene.addLookAt` | `0078A660` | LuaCutscene_addLookAt | `fn::LuaCutscene_addLookAt` | yes |
| `cutscene.addPosition` | `0078A5B0` | LuaCutscene_addPosition | `fn::LuaCutscene_addPosition` | yes |
| `cutscene.createLoopAtEnd` | `0078A6F0` | Unk_Cmd_Call0078d1c0OnSub630 | `fn::Unk_Cmd_Call0078d1c0OnSub630` | yes |
| `cutscene.setRelative` | `0078A640` | Unk_Cmd_SetFlag41OnSub630 | `fn::Unk_Cmd_SetFlag41OnSub630` | yes |

### 3.8 `editor` — `nMenu::Debug::OnShow` `0060a340`

Registered when the map-editor debug menu is shown (the function is reached through a vtable at `007f06b4`).

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `editor.scatter_addElement` | `0060A080` | Lua_editor_scatter_addElement | `fn::Lua_editor_scatter_addElement` | yes |
| `editor.scatter_addPattern` | `0060A160` | Lua_editor_scatter_addPattern | `fn::Lua_editor_scatter_addPattern` | yes |
| `editor.scatter_removeElement` | `0060A280` | Lua_editor_scatter_removeElement | `fn::Lua_editor_scatter_removeElement` | no |
| `editor.scatter_setSize` | `0060A240` | Lua_editor_scatter_setSize | `fn::Lua_editor_scatter_setSize` | no |
| `editor.paste_usePattern` | `006098D0` | Lua_editor_paste_usePattern | `fn::Lua_editor_paste_usePattern` | no |
| `editor.paste_useDeposit` | `00609920` | Lua_editor_paste_useDeposit | `fn::Lua_editor_paste_useDeposit` | yes |
| `editor.paste_useAnimal` | `00609970` | Lua_editor_paste_useAnimal | `fn::Lua_editor_paste_useAnimal` | no |
| `editor.paste_useBuilding` | `006099C0` | Lua_editor_paste_useBuilding | `fn::Lua_editor_paste_useBuilding` | no |
| `editor.paste_useDoodad` | `00609A10` | Lua_editor_paste_useDoodad | `fn::Lua_editor_paste_useDoodad` | yes |
| `editor.paste_useAmbient` | `00609A60` | Lua_editor_paste_useAmbient | `fn::Lua_editor_paste_useAmbient` | no |
| `editor.paste_invertX` | `00609AB0` | Lua_editor_paste_invertX | `fn::Lua_editor_paste_invertX` | no |
| `editor.paste_invertY` | `00609B00` | Lua_editor_paste_invertY | `fn::Lua_editor_paste_invertY` | no |
| `editor.paste_heightMode` | `00609B50` | Lua_editor_paste_heightMode | `fn::Lua_editor_paste_heightMode` | yes |

### 3.9 Standard library

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `error` | `005CA600` | luaB_error | `fn::luaB_error` | no |
| `getmetatable` | `005CA6A0` | luaB_getmetatable | `fn::luaB_getmetatable` | no |
| `setmetatable` | `005CA6F0` | luaB_setmetatable | `fn::luaB_setmetatable` | no |
| `getfenv` | `005CA850` | luaB_getfenv | `fn::luaB_getfenv` | no |
| `setfenv` | `005CA8A0` | luaB_setfenv | `fn::luaB_setfenv` | no |
| `next` | `005CAAD0` | luaB_next | `fn::luaB_next` | no |
| `ipairs` | `005CAB50` | luaB_ipairs | `fn::luaB_ipairs` | yes |
| `pairs` | `005CAB10` | luaB_pairs | `fn::luaB_pairs` | no |
| `print` | `005CA400` | luaB_print | `fn::luaB_print` | no |
| `tonumber` | `005CA4C0` | luaB_tonumber | `fn::luaB_tonumber` | no |
| `tostring` | `005CAE70` | luaB_tostring | `fn::luaB_tostring` | no |
| `type` | `005CAAA0` | luaB_type | `fn::luaB_type` | yes |
| `assert` | `005CAD30` | luaB_assert | `fn::luaB_assert` | no |
| `unpack` | `005CAD80` | luaB_unpack | `fn::luaB_unpack` | no |
| `rawequal` | `005CA960` | luaB_rawequal | `fn::luaB_rawequal` | no |
| `rawget` | `005CA990` | luaB_rawget | `fn::luaB_rawget` | no |
| `rawset` | `005CA9C0` | luaB_rawset | `fn::luaB_rawset` | no |
| `pcall` | `005CADD0` | luaB_pcall | `fn::luaB_pcall` | no |
| `xpcall` | `005CAE20` | luaB_xpcall | `fn::luaB_xpcall` | no |
| `collectgarbage` | `005CAA50` | luaB_collectgarbage | `fn::luaB_collectgarbage` | no |
| `gcinfo` | `005CAA00` | luaB_gcinfo | `fn::luaB_gcinfo` | no |
| `loadfile` | `005CACA0` | luaB_loadfile | `fn::luaB_loadfile` | no |
| `dofile` | `005CACE0` | luaB_dofile | `fn::luaB_dofile` | no |
| `loadstring` | `005CAC40` | luaB_loadstring | `fn::luaB_loadstring` | no |
| `require` | `005CB140` | luaB_require | `fn::luaB_require` | no |

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `coroutine.create` | `005CB4B0` | luaB_cocreate | `fn::luaB_cocreate` | no |
| `coroutine.wrap` | `005CB510` | luaB_cowrap | `fn::luaB_cowrap` | no |
| `coroutine.resume` | `005CB3D0` | luaB_coresume | `fn::luaB_coresume` | no |
| `coroutine.yield` | `005CB540` | luaB_yield | `fn::luaB_yield` | no |
| `coroutine.status` | `005CB560` | luaB_costatus | `fn::luaB_costatus` | no |

| Lua name | C function | Ghidra name | sadkmod declaration | used by shipped scripts |
|---|---|---|---|---|
| `math.abs` | `005C9C20` | math_abs | `fn::math_abs` | no |
| `math.sin` | `005C9C50` | math_sin | `fn::math_sin` | no |
| `math.cos` | `005C9C80` | math_cos | `fn::math_cos` | no |
| `math.tan` | `005C9CB0` | math_tan | `fn::math_tan` | no |
| `math.asin` | `005C9CE0` | math_asin | `fn::math_asin` | no |
| `math.acos` | `005C9D10` | math_acos | `fn::math_acos` | no |
| `math.atan` | `005C9D40` | math_atan | `fn::math_atan` | no |
| `math.atan2` | `005C9D70` | math_atan2 | `fn::math_atan2` | no |
| `math.ceil` | `005C9DB0` | math_ceil | `fn::math_ceil` | no |
| `math.floor` | `005C9DE0` | math_floor | `fn::math_floor` | yes |
| `math.mod` | `005C9E10` | math_mod | `fn::math_mod` | no |
| `math.frexp` | `005C9FE0` | math_frexp | `fn::math_frexp` | no |
| `math.ldexp` | `005CA030` | math_ldexp | `fn::math_ldexp` | no |
| `math.sqrt` | `005C9E60` | math_sqrt | `fn::math_sqrt` | no |
| `math.min` | `005CA090` | math_min | `fn::math_min` | no |
| `math.max` | `005CA110` | math_max | `fn::math_max` | no |
| `math.log` | `005C9EE0` | math_log | `fn::math_log` | no |
| `math.log10` | `005C9F10` | math_log10 | `fn::math_log10` | no |
| `math.exp` | `005C9F40` | math_exp | `fn::math_exp` | no |
| `math.deg` | `005C9F80` | math_deg | `fn::math_deg` | no |
| `math.pow` | `005C9E90` | math_pow | `fn::math_pow` | no |
| `math.rad` | `005C9FB0` | math_rad | `fn::math_rad` | no |
| `math.random` | `005CA190` | math_random | `fn::math_random` | no |
| `math.randomseed` | `005CA350` | math_randomseed | `fn::math_randomseed` | no |

## 4. Calls from C++ into Lua

### 4.1 Map-script events

All go to the map-script thread through `LuaScriptHost::CallGlobal*` (`lua_pcall`, errors silently dumped) and do
nothing when no map script is loaded (`0087e964 == 0`) [known]. The function names are pointers in `.data`
(`0087e940`..`0087e94c`) or literals [known].

| Lua global called | Arguments | Wrapper (address, sadkmod) | Fired from | Defined in shipped scripts | Status |
|---|---|---|---|---|---|
| `onStarted` | — | `GameScript_CallOnStarted` `005b2220` (`fn::GameScript_CallOnStarted`) | `Game_LoadWorldFromDescriptor` `005ac770`, new-game map types only | every campaign map script and `map\Presentation.lua` | [known] |
| `onLoaded` | — | `GameScript_CallOnLoaded` `005b2180` (`fn::GameScript_CallOnLoaded`) | `Game_LoadWorldFromDescriptor`, always (new game and loaded save) | every campaign map script | [known] |
| `onLogicTick` | one number (scripts name it `ticks`) | `GameScript_CallOnLogicTick` `005b20d0` (`fn::GameScript_CallOnLogicTick`) via `CallGlobal_Number` | `NLogic::System::Update` `00527070` (`0052724d`) | every campaign map script | [known]; [TODO] tick rate and argument meaning |
| `createQuestUi` | — | `GameScript_CallCreateQuestUi` `005b1f30` | `005fc900` (quest UI) | `scripts\mapTools\quests.lua` | [known] |
| `destroyQuestUi` | — | `GameScript_CallDestroyQuestUi` `005b1e80` | `005fcbc0` | `quests.lua` | [known] |
| `quest_cinematicDone` | — | `GameScript_CallQuestCinematicDone` `005b2360` | `005faee0` | `quests.lua` | [known] |
| `sacrifice_execute` | one number | `GameScript_CallSacrificeExecute` `005b2410` | `00660500` | not defined by any shipped script (the call fails silently) | [known] |
| *(name passed by the script)* | `(x, y)` | `GameScript_CallLuaFunctionXY` `005af860` (`fn::GameScript_CallLuaFunctionXY`), `CallGlobal_XY` | `logic.vi_forEachBuilding` `005b14c0`, `logic.map_forEachDoodad` `005b1290` (direct `CallGlobal_XY`) | e.g. `stopProduction` style callbacks in campaign scripts | [known] |

### 4.2 UI widget events

| Lua global called | Wrapper | Fired from | Status |
|---|---|---|---|
| `<widget name>_isClicked` | `LuaUi_CallScriptFunctionIfDefined` `004c44a0` → `005af810` (`IsGlobalFunction`) → `005af830` (`CallGlobal`) | `nUi::Button::OnClicked` `004b12d0` (button vtable slot 34) for any button with a non-empty name | [known] |
| `<widget name>_isPressed` | same | `nUi::Button::OnPressed` `004b1470` | [known] |

Only when `0088b314` is set (a map script thread exists) and the global is a function; no shipped script defines
an `_isClicked` / `_isPressed` handler [known: code + data]. `005af810` and `005af830` are unnamed (no sadkmod
declaration).

### 4.3 Thread resumption

`LuaScriptHost::UpdateThreads` `005c9a10` resumes threads suspended by `Default.Wait` every frame, in the menus
and in game [known]. Every `RunFile` also starts its chunk with `lua_resume` [known].

## 5. Hook points for mods

All addresses are for the DRM-free `SADK.exe`; mods hook them with `sadk::Hook<…>` on the declarations named
here. Hooks are installed before the game's entry point (`mods/README.md`), i.e. before the script host exists,
so every hook below sees the first call [inferred].

| Goal | Hook | How | Status |
|---|---|---|---|
| **Add new Lua functions** (global, from start-up) | `fn::LuaScript_OpenDefaultLib` (`005cdd80`, cdecl `(lua_State *)`) | call `original(L)`, then `fn::luaL_openlib(L, "mymod", regs, 0)` and `fn::lua_settop(L, -2)`. Runs once on the main state; all threads share its globals. C functions are `int __cdecl f(lua_State *)` and use the game's `fn::lua_*` | [inferred] (registration path [known]) |
| Add functions only while a map is loaded, next to `logic` | `fn::GameScript_RegisterLuaLibraries` (`005b2990`) | after `original()`, `fn::ai::script::LuaScriptHost::RegisterLib(host, *var::g_GameScript_ThreadId, &name, regs)` (name is an `msvc::string`). Note the role-0 condition (§2.3) | [inferred] |
| See or rewrite **every** registration (incl. replacing a game function's entry) | `fn::luaL_openlib` (`005cd430`) | inspect `libname` / `regs`; for a table built on the stack, pass a modified copy to `original` | [inferred] |
| Replace one Lua-visible function | the C function itself (tables in §3) | `Hook<fn::…>` on that address; same `int(lua_State *)` signature | [inferred] |
| **Replace a script file** | none needed | `mods\<name>\data\<path>` in plain text (`scripts\…\*.lua`, `menu.cfg`); goes through the redirect + plain-file pass-through (§2.1). Changes the MP build checksum for `.lua` | [inferred]; host tested under Wine only |
| **Add a script / run code after a script** | `fn::ai::script::LuaScriptHost::RunFile` (`005c9690`, thiscall `(host, threadId, msvc::string *path)`) | after `original`, match the path (e.g. `data.lua`, the map `.lua`, `menu.cfg`) and run an extra file with `RunFile(host, threadId, &extra)` in the same thread. Without code: a data-only mod can replace an existing script that calls `Default.CallScript` (e.g. `scripts\properties\data.lua`) to pull in a new file | [inferred] |
| Observe every script load with its decrypted source | `fn::LuaDebugger_NewFile` (`005cdc40`, stdcall) or a `LuaDebugger.dll` next to `SADK.exe` exporting `_AddLuaState@4`, `_RemoveLuaState@4`, `_NewFile@16`, `_Break@4`, `_Hide@0` | the DLL route needs no hook at all; the game loads it by name on first use | thunks [known]; DLL route [inferred], untested |
| **Observe events** (all C++ → Lua calls by name) | `fn::ai::script::LuaScriptHost::CallGlobal`, `CallGlobal_Number`, `CallGlobal_XY` (`005c9780`, `005c9840`, `005c9920`) | log `funcName` / args before `original`; or hook the named wrappers in §4.1 (`fn::GameScript_CallOnLogicTick`, …) | [inferred] (call paths [known]) |
| Inject own events into the map script | call `fn::ai::script::LuaScriptHost::CallGlobal(host, *var::g_GameScript_ThreadId, &name, 0)` from a game-thread hook, guarded by a non-empty map-script path | [inferred] |
| Per-frame work on the script side | `fn::ai::script::LuaScriptHost::UpdateThreads` (`005c9a10`) | runs every frame in menus and in game | [inferred] |
| **See script errors** | `fn::LuaScriptHost_DumpScriptError` (`005c9440`, `(lua_State *)`) | before `original`, `fn::lua_tostring(L, -1)` is the error message (`lua_pcall` / `lua_resume` leave it on top); log it | [inferred] |
| **Script logging** | `fn::LuaDefault_WriteToLog` (`005cdde0`) | replace: read arg 1 with `fn::lua_tostring` and write it to `sadk::log`; the game's version discards it | [inferred] (no-op [known]) |
| Button events | `fn::LuaUi_CallScriptFunctionIfDefined` (`004c44a0`, `(char *funcName)`) | log or route `<name>_isClicked` / `_isPressed` | [inferred] |

## 6. Open points

- [TODO] Meaning of `NComm_Manager_IsRole0` for map-script registration in multiplayer.
- [TODO] Rate and argument of `onLogicTick`.
- [TODO] What the hex part of `scripts\info\i_<hex>.lua` / `b_<hex>.lua` encodes; who loads `graphic_main.lua`.
- [TODO] Whether `sd_setValue` data is what a save game keeps of the map script (a loaded save gets only
  `onLoaded`, the Lua state itself is not saved) — `GameScript_InitMapScript` clears the store at `0088b340`.
- [TODO] Live confirmation of everything above in the running game (Frida MCP: hook `CallGlobal`, `RunFile`,
  `luaL_openlib`).
