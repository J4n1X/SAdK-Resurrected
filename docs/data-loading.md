# When the game reads its data files

Which data files `SADK.exe` reads once at start-up and which it reads again for every match. This decides what a
mod's replacement files and hooks can change and when: a file read once is only affected by a mod that is active
before the game starts, a file read per match by any mod active when the match is entered.

- Binary: the DRM-free `SADK.exe` (Ghidra `/sadk_noav.exe`, image base `0x400000`; static addresses are runtime
  addresses).
- Status tags: **[known]** = read in the binary at the given address; **[inferred]** = follows from what was read,
  not observed at run time; **[TODO]** = not established. Nothing here has been checked in the running game.
- `[data]` is the game's virtual path for both data roots, `data\game\` and `data\lobby\`: a listing of
  `[data]\x` lists both `data\game\x` and `data\lobby\x` (`FileScanHolder::FindFilesInDataPath` `006e4c10`) [known].

## 1. Once, at start-up

`CApplicationEx::Initialize` `004075d0` (called once from WinMain) [known]:

| What | Where | Status |
|---|---|---|
| Directory scan of `data\` (the data roots for `[data]` paths) | `FileScanHolder::ScanDirectory` | [known] call; [TODO] what the scan keeps beyond the roots |
| The property database (`PropertiesDb`, singleton `00889dd8`): every tribe, good, building, animal, ship, doodad, deposit, pattern, sound, AI and game-config value | `Properties_RegisterLuaLibrary` `00550e40` sets defaults and registers the Lua library `properties` (243 bindings); `Properties_RunPropertyScript("data")` `0054f8d0` runs `[data]\scripts\properties\data.lua`, which pulls in the other property scripts (`docs/lua-surface.md` §2.2) | [known] |
| Sound system, user profile, `LobbyProfile` | `Sound_Init`, `LobbyProfile::Init` | [known] calls |
| The lobby (unless `-nolobby`): `LobbyManager`, the lobby's zone table `world1.xml` | `LobbyManager::Initialize`, `CLobby` vtable `LoadZoneTable` | [known] calls |
| Menus: `[data]\scripts\menu.cfg` | `nMenu::System::Initialize` `005dda30` | [known] |

The property database is filled only there. Its bindings create records (`*_create`) and append to lists
(`*_add*`, e.g. `bp_addCost`), so running `data.lua` a second time would add every entry again [known: binding
names; inferred: append semantics]. The game's own way to empty it is `Properties_Db_ClearAll` `005494a0` (every
property table, the config flags, `bLoaded` `+0xc0` = 0), called only from `CApplicationEx::Shutdown` `00401cb0`
[known]. Whether anything keeps pointers into property records past a match (menus built at start-up, the sound
system, music) is [TODO]; until that is known, reloading the properties between matches is untested.

## 2. Again for every match

| What | Where | Status |
|---|---|---|
| `S2CG::Scene` (global `g_pScene` `0088ca60`) | created by `Scene_CreateGlobal` `0067e800` from `nMenu::Game::OnEnter` `005eed00`, freed by `Scene_DestroyGlobal` `0067e8a0` from `nMenu::Game::OnLeave` `005eb030` | [known] |
| `[data]\settings\graphics.xml` (scene settings), `items.xml` (new `ItemMgr`), `[data]\character\settler_config.xml` and `settler_animations.xml` (new `CCharacterMgr`), `buildings.xml`, `animals.xml` (new `AnimalMgr`), `ships.xml` (new `ShipMgr`) | `S2CG::Scene::Init` `006824c0`, slot 0 of the scene's vtable `007f8f2c`, called by `nGame::System::BuildScene` | [known] |
| Except: tile scaling, map-render and environment settings from `graphics.xml` | parsed on the first `Scene::Init` only (latch byte `0088ca6a`) | [known] |
| `[data]\settings\terrain_static_data.xml`, `map_objects.xml` | `nGame::System::BuildScene` `007842e0`, from `nGame::System::BuildWorld` `00784d40`, which also constructs `g_pGameSystem` | [known] |
| The map's script (`<map>.lua`), info and cutscene scripts | `docs/lua-surface.md` §2.2–2.3 | [known] |

These files are read each time a match's world is built, so a mod active by then changes them [inferred: the
managers are created anew in `Scene::Init`; that the old ones are freed when the scene goes is not checked].

## 3. The build checksum

`GameData_ComputeBuildChecksum` `005ab800` covers every `[data]\scripts\**\*.lua` and `[data]\settings\**\*.xml`
(`docs/lua-surface.md` §2.2). It is not cached: `NComm_GetBuildChecksum` `0041f240` computes it anew on every call,
from `ConnectAndJoin` `0040ad60` (the joiner's `UserInformation 0x30001`) and from `HandleEvent` `0040e560` (the
host comparing it) [known].

The files are found by listing the disk (`FindFilesInDirectory` `006e4310`: `FindFirstFileA` / `FindNextFileA`)
and each one is then opened by name [known]. With the mod host's file redirect (`mods/README.md`), a mod's
**replacement** of an existing file is opened and counted; a file that exists **only** in a mod is never listed, so
it is not counted [inferred from the two facts above].
