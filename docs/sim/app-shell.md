# Application shell: start-up, main loop, settings, profiles and game modes

The frame around every other subsystem of `sadk_noav.exe`: process start, the order in which the engine parts are
created, the frame loop and its timer, the screens that select a run mode, how each mode fills the game load
descriptor, the campaign table and its unlock rule, the user profile files, the command line, language selection,
the log and crash files, and shutdown.

- Binary: `sadk_noav.exe`, image base `0x400000`. `S 00xxxxxx` is a static address in it.
- Tags: **[known]** = read directly at the address given or in the named data file and key; **[inferred]** = one
  step of reasoning from what is visible; **[TODO]** = not established. Nothing here was observed in the running
  game.
- Stream encoding (`str`, `bool`, section tag) is that of `docs/sim/save-format.md` §2.2 and §2.4: little-endian,
  unpadded; `str` = `u32` length + bytes; `bool` = 4 bytes; a section tag = 12 bytes (`i32` version, `u32` CRC-32
  of the section name, `u32` name length).

Related specifications, not repeated here:

| Topic | Where |
|---|---|
| Frame time → logic ticks, game speed, pause | [`logic-core.md`](logic-core.md) §3.1, §4.1 |
| Save container, map types and folders, starting from a save, autosave name | [`save-format.md`](save-format.md) §2.6, §3.8 |
| Offline and network roles, `network.ini` | [`network-session.md`](network-session.md) §3.3, §6 |
| Screens, dialogs, in-game flow | [`ingame-ui.md`](ingame-ui.md) §2.7, §3.9 |
| File index, virtual paths, encrypted container, text tables | [`formats-inventory.md`](formats-inventory.md) §2, §3.9 |
| Lua state, script start order | [`lua-runtime.md`](lua-runtime.md) §4.1 |
| Which files are read once and which per match | [`../data-loading.md`](../data-loading.md) |
| Subsystem map, lobby session flow | [`../subsystems.md`](../subsystems.md) §1.1, §2.1 |

---

## 1. Purpose and scope

In scope:

- `WinMain`, the window, the single-instance rule, the message loop;
- `CApplicationEx` (global `g_App` S 008856a8): initialisation order, per-frame dispatch, shutdown order;
- the frame timer;
- the command line;
- the top-level screens (`Splash`, `Main`, `Game`) as the selectors of a run mode, and what each mode writes into
  the `GameLoadDescriptor` before the world is built;
- the campaign table (`campaigns.xml`), the unlock rule and the per-map states in the user profile;
- the user folder and its files `settings.cfg` and `data.cfg`, and the settings files of the install that the
  shell reads (`engine.ini`, `engine.xml`, `menu.cfg`, `LobbySettings.ini`);
- language selection;
- the log file, the crash report, the benchmark mode;
- exit.

Out of scope: what happens inside a tick (`logic-core.md`), the world build itself (`save-format.md` §3.8), the
online lobby (`../subsystems.md` §2.3 to §2.5), widget layout (`ingame-ui.md`).

---

## 2. Data model

### 2.1 `CApplicationEx` (0xac bytes, global `g_App` S 008856a8)

Constructed by a static initialiser (S 004039e0). Fields [known] S 004039e0, S 00403ac0, S 004075d0, S 00401f30:

| Offset | Type | Field | Meaning | Initial |
|---|---|---|---|---|
| +0x00 | bool | `running` | the frame loop runs while this is set; set at the end of `Initialize` | false |
| +0x04 | HWND | window | | 0 |
| +0x08 | HINSTANCE | instance | | 0 |
| +0x0d | bool | `minimized` | `WM_SIZE` with wParam 1 | false |
| +0x0e | bool | in size-move | set by window message 0x231, cleared by 0x232 | false |
| +0x10 | i32 | shader path | −1 = no override; 3, 2, 0 from `-3_0`, `-2_0`, `-ffp` | −1 |
| +0x14, +0x18 | i32 | window width, height | from `GetWindowRect` at start | 0 |
| +0x1c | bool | no cursor clip | copy of byte +8 of the graphic device's display-mode block; when set the cursor is not confined to the window (windowed mode [inferred]) | false |
| +0x20, +0x24 | i32 | display width, height | copy of ints 0 and 1 of the display-mode block | 0 |
| +0x28 | std::string | `-start` file name | | empty |
| +0x44 | std::string | `-map` map name | | empty |
| +0x60 | i32 | campaign map index to start | no command-line switch writes it [known: the parser S 00403ac0 has no write] | −1 |
| +0x64 | std::string | log directory (`-log_path`) | empty → `<My Documents>\SAdK\dumps` | empty |
| +0x80 | i32 | benchmark level (`-hwlab_*`) | 0..4; 5 = none | −1, then 0..4 or 5 from the parser |
| +0x84 | bool | `active` | window is the active window (`WM_ACTIVATE`) | false |
| +0x88 | `CLobby*` | 3D lobby object | NULL with `-nolobby` | NULL |
| +0x8c | std::string | lobby profile name (`-net`) | | `"default"` |
| +0xa8 | bool | `-localhostmode` | | false |
| +0xa9 | bool | `-lobbyfast` | | false |
| +0xaa | bool | `-nolobby` | | false |

### 2.2 Frame timer (globals) [known] S 0057b790, S 0057b810, S 0057b990

| Global | Type | Meaning |
|---|---|---|
| `g_Timer_GetTimeMsFn` S 0088a610 | function pointer | time source in milliseconds |
| S 0088a614 | bool | timer initialised |
| `g_Timer_FixedStep` S 0088a615 | bool | when set, the frame time is a constant 0.025 s. The image holds one reference to this byte, the read in S 0057b850; nothing writes it, so it is always 0 [known: reference list] |
| S 0088a618 | i64 | counter ticks per millisecond: `QueryPerformanceFrequency / 1000` (integer division) |
| `g_Timer_CurrentMs` S 0088a620 | u32 | time sample of this frame (low 32 bits of the source) |
| `g_Timer_PrevMs` S 0088a624 | u32 | time sample of the previous frame |
| `g_Timer_FrameDeltaMs` S 0088a628 | u32 | duration of the last frame, whole milliseconds |
| `g_Timer_StartMs` S 0088a62c | u32 | sample taken by `Timer_Reset` |

### 2.3 `GameLoadDescriptor` (0x248 bytes)

One instance, owned by the `Game` screen (`nMenu::Game +0xffe4`). It is the only input of the world build
(`nGame::System::BuildWorld` S 00784d40). Fields [known] S 005a9bb0, S 005a9c10, S 005a9c50; the game options and
the per-slot arrays are specified in [`players-victory.md`](players-victory.md) §2.4.

| Offset | Type | Field | Default (`Reset` S 005a9bb0) |
|---|---|---|---|
| +0x00 | i32 | map type (§2.4) | 0 |
| +0x04 | std::string | map or save name, without folder and extension | empty |
| +0x20 | i32 | start resources (free game, network) or campaign difficulty, 0..3 | 2 |
| +0x24 | i32 | non-zero: shuffle start positions | 0 |
| +0x28 | i32 | fog of war option | 0 |
| +0x2c | `NLogic::MapInfo` | embedded map info carrying the per-slot setup (kind, tribe, colour, team, level, name); `+0x1fc` of the descriptor is its map type field (`MapInfo +0x1d0`) | `MapInfo::Reset` |
| +0x23c | i32 | load selector: 0 = load the file named above; 1 = build an empty world without a file | 1 |
| +0x240 | i32 | side length of the empty world when the selector is 1; −1 after a name was set | 80 |
| +0x244 | i32 | win condition | 0 |

Two setters put a name in, and both set selector 0 and `+0x240 = −1` [known]:

- `SetMapName(name)` S 005a9c10: map type **110** (a save);
- `SetMapNameAndType(type, name)` S 005a9c50: the given type.

`Reset` runs in the constructor and in `nMenu::Game::OnLeave` S 005eb030, so after every match the descriptor is
back at "empty 80 × 80 world" until the next start writes a name [known].

### 2.4 Map types

The value in `+0x00` selects folder, extension and what the loader reads (table in `save-format.md` §2.6). Values
the shell writes:

| Type | Written by | Meaning |
|---|---|---|
| 0 | free-game panel, `-map`, lobby game setup | new game on a map from `[data]\maps\freeGameMaps\`; the loader falls back to the user map folder (type 3) |
| 1 | campaign start, map entry `type="map"` | new game on `[data]\maps\campaignMaps\<file>.s2m` |
| 101 (0x65) | campaign start, map entry with any other `type` value | prepared scenario `[data]\maps\campaignMaps\<file>.a2m` (map part and logic part); no such file is in the install |
| 110 (0x6e) | load panel, "Continue", `-start`, every save written | `<My Documents>\SAdK\saves\<name>.aav`, fallback `.sav`, then the user map |

Types 2, 3, 100, 102 and 103 exist in the path table and in the map-info cache refresh (S 005ac880) but no start
path of the shell writes them [inferred: the four callers of `SetMapNameAndType` (S 00401350, S 004562d0,
S 005df2c0, S 005e8410) pass 0, 1 or 0x65, and `SetMapName` (three callers) always writes 110]. Type 10
(`saves\<name>.sav`) is only probed by "Continue" (§3.7). The install has no `tutorialMaps` folder and no `.a2m`
file [known: directory listing].

### 2.5 Campaign table

`nMenu::Campaigns` (0x30 bytes) is an XML handler on `campaigns.xml` holding a vector of `CampaignData`
[known] S 005e4de0, S 005e52a0.

`nMenu::CampaignData` (0x3c bytes) [known] S 005e42a0, S 005e45e0: configurable base, `name` (std::string,
attribute `name`), vector of `nMenu::Map` at `+0x2c`.

`nMenu::Map` (0x78 bytes) [known] S 005e3370:

| Offset | Type | Field | XML attribute |
|---|---|---|---|
| +0x10 | std::string | name: key of the profile's map state, text of the tile | `name` |
| +0x2c | vector of std::string | names of the maps that must be completed first | `prerequisite0`, `prerequisite1`, ... read until one is missing |
| +0x3c | std::string | description key | `desc` |
| +0x58 | std::string | file name without extension | `filename` |
| +0x74 | i32 | kind: 0 when `type` is exactly `map` (compared with case), 1 for any other value; stays at the constructor's −1 (S 005e03a0) when the attribute is missing | `type` |

Element names are compared without case (`campaign`, `map`); children with other names are ignored [known].
The handler's campaign vector is at `Campaigns +0x20`.

### 2.6 User profile (`ai::app::UserProfile`, 0xc0 bytes, singleton `g_pUserProfile` S 0088a594)

Fields, defaults from `UserProfile_ResetSettingsDefaults` S 00579c00 [known]:

| Offset | Type | Field | Default | In `settings.cfg` |
|---|---|---|---|---|
| +0x00 | bool | initialised | set by `Initialize` | no |
| +0x04 | i32 | autosave interval, seconds; 0 = off | 600 | yes |
| +0x08 | std::string | name of the last save written offline | empty | yes |
| +0x24 | f32 | game speed factor (`logic-core.md` §3.1) | 1.0 | written; the reader overwrites it with 1.0 |
| +0x28 | bool | invert scrolling | false | yes |
| +0x2c | f32 | scroll speed | 0.25 | yes |
| +0x30 | bool | border scrolling | true | yes |
| +0x31 | bool | smart cursor (mirrored to global S 0087b808 on load) | true | yes |
| +0x32 | bool | stored only: set by the defaults, read and written by the two settings functions; no other function that obtains the profile touches it [inferred: the decompiled users of `UserProfile_GetInstance` S 00578da0 and of S 0088a594]. [TODO] not established: its original meaning | true | yes |
| +0x33 | bool | free camera | false | yes |
| +0x34 | bool | last state of the `!Autosave...` check box of the quit requester (`nMenu::Requester`; the box exists only when the requester is opened on the in-game screen, S 005ffef0): a click toggles the box and stores its new state here through `UserProfile::SetAutosaveOnLeave` S 00579830 [known] S 006009b0. Write-only: the box is created unmarked every time and the confirmed action reads the box, not the profile (`Requester::ExecuteConfirmed` S 006008b0: autosave before leaving when the box is marked) [known]; no function reads `+0x34` back [inferred, as for `+0x32`] | true | yes |
| +0x38 | i32 | stored only [inferred, as for `+0x32`]; first of the counted values of the file (§3.9). [TODO] not established: its original meaning | 0 | yes |
| +0x3c | i32 | campaign difficulty last chosen, 0..3 | 2 | yes |
| +0x40 | std::string | player name used in an offline session (`NComm_GetLocalPlayerName` S 0041f4e0; an empty name becomes `"default"`) | empty | yes |
| +0x5c | std::string | lobby account name (`SetLobbyUserName` S 00579d80) | empty | yes |
| +0x78 | std::string | stored only [inferred, as for `+0x32`]. [TODO] not established: its original meaning | empty | yes |
| +0x94 | i32 | connection type, 0..4 (`network-session.md` §3.5) | 3 | yes |
| +0x98 | i32 | lobby shadow quality | 0 | yes (version ≥ 1) |
| +0x9c | i32 | lobby mirror quality | 0 | yes |
| +0xa0 | i32 | lobby texture quality | 0 | yes |
| +0xa4 | i32 | lobby object details | 0 | yes |
| +0xa8 | i32 | lobby shader detail | 0 | yes |
| +0xac | bool | lobby invert mouse | false | yes |
| +0xb0 | `UserMapStates` | per-map progress: initialised byte, then `std::map<std::string, MapState>` | empty | `data.cfg` |

`nUser::MapState` [known] S 0057a490, S 00579e80:

| Offset | Type | Field | Default | In `data.cfg` |
|---|---|---|---|---|
| +0x04 | std::string | map name (the map's `MapInfo` name, `MapInfo +0x24`) | empty | yes |
| +0x20 | i32 | state: 2 = started, not completed; 0 = completed, end dialog not yet shown; 1 = completed, end dialog shown | 2 | yes |
| +0x24 | i32 | win condition of the completing match: copy of `MapInfo +0x1c8`, which a new game fills from descriptor `+0x244` (S 00535990, S 005ac770) | 4 | **no** |
| +0x28 | i32 | highest difficulty value the map was completed with | −1 | yes (version ≥ 1) |
| +0x2c | bool | completed | false | yes |

### 2.7 Scene settings (`S2CG::Settings`, 0x4c bytes, static singleton S 0088d7d8)

Two vtables (primary S 007f9c68, in-game interface S 007f9bfc). Fields [known] S 00695b40, S 00696270; the
option names are [inferred] from the options panel, which reads option *n* through the getter that follows the
field's setter in the in-game vtable (`nMenu::OptionsPanel::LoadOptionValue` S 005e55b0).

| Offset | Type | Field | Options control | Constructor value |
|---|---|---|---|---|
| +0x08 | i32 | quality preset 0 (lowest) .. 4 (highest) | | 4 |
| +0x0c | bool | post-processing on: set by `-postFX`; forced to 0 whenever a settings stream is read. `S2CG::Scene::Render` S 006836b0 reads it every frame through primary slot +0x0c (S 00405220): set and no post-processor → shader define `POSTFX` and a new post-processor; clear and a post-processor exists → it is destroyed [known] ([rendering.md](rendering.md)) | | 0 |
| +0x10 | f32 | texture quality 0..1 | `cTextureQuality` | preset |
| +0x14, +0x18 | i32 | display width, height; −1 = take the device's current mode | `cVideoMode` | −1 |
| +0x1c | bool | display mode flag | `cDisplayMode` (index 1 when set) | 0 |
| +0x20 | f32 | ground detail 0..1 | `cGroundDetail` | preset |
| +0x24 | bool | mirrored into bit 0x80 of the scene's render-flag word by `S2CG::Scene::ApplySceneSettings` S 0067f500 (in-game slots +0x08 set S 00695c60, +0x0c get S 00695c70) [known]. None of the options controls of `frontend-screens.md` §3.7 maps to it [inferred]. [TODO] not established: what bit 0x80 draws, and the setter's callers (virtual only) | | 0 |
| +0x25 | bool | the fog-of-war display state the scene last applied: `S2CG::Scene::Update` S 006805e0 compares it with the scene's own show-fog flag, and stores the new value when they differ [known]. A cache, not an option [inferred]; it is still written to the file | | 0 |
| +0x26 | bool | shadows on; derived: `shadowDetail > 1/6` | | derived |
| +0x28 | f32 | shadow quality 0..1 | `cShadowQuality` | preset |
| +0x2c | f32 | shadow detail 0..1 | `cShadowDetail` | preset |
| +0x30 | bool | mirror on; derived: `mirrorQuality > 0` | | derived |
| +0x34 | f32 | mirror quality 0..1; the control shows `(v − 0.25) / 0.75` | `cMirrorQuality` | preset |
| +0x38 | f32 | mirror strength 0..1 | `cMirrorStrength` | preset |
| +0x3c | i32 | level, 2 (presets 0, 1) or 3 (presets 2..4) [known] S 00695860. `Scene::ApplySceneSettings` S 0067f500 copies it to the scene (in-game slot +0x54, S 00695ea0) and, whenever the copy changes, calls `CGraphicDevice::SetMaxShader(2)` [known]. [TODO] not established: what reads the scene's copy | | preset |
| +0x40 | f32 | detail 0..1 | `cDetail` | preset |
| +0x44 | f32 | object details 0..1 | `cObjectDetails` | preset |
| +0x48 | bool | [TODO] not established: stored and loaded (last field of the section), no reader identified | | 1 |
| +0x49 | bool | settings were loaded or auto-detected (not stored) | | 0 |

### 2.8 Crash report context (global `g_CrashReport`) [known] S 006e63d0, S 006e6170

0x138 bytes: the `FILE*` of the open crash log (+0x00), a std::string (+0x04) that collects the call-stack text, a
256-byte line buffer (+0x20), process handle and id (+0x120, +0x124), thread handle and id (+0x128, +0x12c), the
`EXCEPTION_POINTERS*` (+0x130), the context record (+0x134).

---

## 3. Rules and algorithms

### 3.1 Process start: `WinMain` S 00407cf0 [known]

1. `GetModuleFileNameA`; cut the path at the last `\` twice (drop the file name, then the `bin` folder); if both
   cuts succeed, `_chdir` to the result and store it as the game root (`App_SetGameRootDir` S 0057bc90). Every
   relative path of the game (`data\...`) is relative to the **parent of the folder that holds the executable**.
2. Read the process affinity; set the process affinity to the **lowest set bit of the system affinity mask**: the
   whole process runs on one CPU.
3. `CreateMutexA(NULL, FALSE, "sadk")`. If `GetLastError()` is 183 (already exists) return 0: one instance only.
4. From here on a structured exception handler is active (§3.12).
5. Register the window class `S2Class` (class style 0x28 = own DC + double clicks, icon resource 103, no class
   cursor, window procedure `App_WndProc` S 00407c10) S 00407c90. Failure: return −1.
6. Create the window: title `"SAdK Build 34688"` (format `%s Build %d` with the name `SAdK` and the build
   number `g_BuildVersion` S 008793c0 = 34688), style 0x10ca0000 (visible, caption, system menu, minimise box;
   no resize border, no maximise box), position (0, 0), client size 100 × 100 until the engine layer resizes it
   S 00407b70. Failure: return −1.
7. `CApplicationEx::Initialize(cmdLine, hWnd, hInstance)` (§3.3). Failure: return −1 (no shutdown call).
8. Log `Version: 34688` at level 1.
9. Loop (§3.5). After the loop: `CApplicationEx::Shutdown` (§3.13), close the mutex handle, return the `wParam`
   of the last message taken from the queue.

The build number is also what a joining peer sends and the host compares (`network-session.md` §3.5), and the
number in the crash log.

### 3.2 Command line: `CApplicationEx::ParseCommandLine` S 00403ac0 [known]

**Tokens** (`ai::core::CmdLineArgs::Tokenize` S 006e5300): blanks separate tokens. A token that starts with `"`
or `'` runs to the next occurrence of the same quote character (the quotes are not part of the token); text
between that closing quote and the next blank is dropped. There is no escape character.

**Matching** (`FindArg` S 006e5180): a switch is found at the first token for which
`_strnicmp(token, switch, min(len(token), len(switch))) == 0`. So matching ignores case, a token that is a
**prefix** of the switch matches (`-st` finds `-start`), and a token that only **starts with** the switch
matches too (`-lowest` finds `-low`). A switch with a value takes the token after it (`GetArg(index + 1)`); a
missing value leaves the field unchanged. An empty token (`""` on the command line) has length 0, so the
comparison length is 0 and it matches **every** switch [inferred: `_strnicmp` with count 0 returns 0].

| Switch | Effect |
|---|---|
| `-log_disabled` / `-log_error` / `-log_warn` / `-log_info` | log level 0 / 1 / 2 / 3 (first found in this order wins); also sets the word S 0088593c to 0x20 / 0x18 / 0x14 / 0x12, which nothing reads (its only references are these four writes [known: reference list]). Without a switch the level stays at its compiled value **1** (S 00882690) |
| `-log_path <dir>` | directory of the log, crash and dump files (`+0x64`); without it the field is cleared and `Initialize` uses `<My Documents>\SAdK\dumps` |
| `-low` / `-med` | scene quality preset 0 / 2; neither: 4. Applied at once through `Settings::SetQualityPreset`. A stored or auto-detected preset replaces it later (§3.3 steps 9 and 13) [inferred] |
| `-postFX` | `Settings +0x0c` = switch present (the call is made in both cases) |
| `-3_0` / `-2_0` / `-ffp` | shader path 3 / 2 / 0 (`+0x10`), copied into the device's display-mode block when ≥ 0 (§3.3 step 12) |
| `-hwlab_verylow` / `_low` / `_medium` / `_high` / `_veryhigh` | benchmark level 0 / 1 / 2 / 3 / 4; none: 5 (§3.11) |
| `-net <name>` | lobby profile name (`+0x8c`, default `default`): the per-user lobby file is `<My Documents>\SAdK\lobby\<name>.ini` |
| `-localhostmode` | `+0xa8`: the main menu's lobby button requests lobby mode 2 directly instead of mode 3 followed by `SetField80(2)` (S 004018e0) |
| `-lobbyfast` | `+0xa9`; the only use found is its reset on the first lobby request (S 004018e0) [inferred: no effect] |
| `-start <name>` | start the save `<name>` at once (§3.7). **Ignored while the Ctrl key is held** (`GetAsyncKeyState(0x11) != 0`) |
| `-map <name>` | start a new game on the map `<name>` at once (§3.7) |
| `-mptest` | sets the byte S 0088b840, which nothing reads (`../subsystems.md` §5) |
| `-nolobby` | `+0xaa`: the lobby manager, the lobby action and the `CLobby` object are not created |

When both `-start` and `-map` are given, `-start` wins (§3.3 step 19). The parser always returns true.

### 3.3 Initialisation order: `CApplicationEx::Initialize` S 004075d0 [known]

Runs once. The order is binding where later steps read what earlier steps created.

1. Parse the command line (§3.2).
2. Create the user folders (§3.8).
3. Log directory: `-log_path`, or `<My Documents>\SAdK\dumps` when that is empty. The same directory is given to
   the log (`Log_SetDirectory`), the crash report (`Crash_SetOutputDirectory`), the lobby log (opened here,
   truncated) and, in step 17, the network connection settings (`+0x34`).
4. `Fpu_SetDefaultControlWord` S 0057b9b0: `_controlfp(0x9001f, 0xffff)`, then `_controlfp(0x20000, 0x30000)`
   (24-bit precision).
5. Store window and instance handles; `active = true`.
6. **File index**: create the `FileScanHolder` and scan `data\` (`formats-inventory.md` §2.2).
7. Window size into `+0x14` / `+0x18`. **Timer**: `Timer_Init`, `Timer_Reset` (§3.4).
8. **Lua**: create the script host. **Properties**: register the `properties` library and run
   `[data]\scripts\properties\data.lua` (`lua-runtime.md` §4.1, `properties-data.md`).
9. **Sound**: create and initialise the sound system. **User profile**: defaults, then `settings.cfg` and
   `data.cfg` (§3.9); reading `settings.cfg` sets the volumes of the sound system, which is why sound comes first.
10. **Lobby profile**: `LobbyProfile::Init(profileName)` S 00465dd0 stores the profile name, the resolved path of
    `LobbySettings.ini` and `<My Documents>\SAdK\lobby\<profileName>.ini`.
11. Unless `-nolobby`: create and initialise the `LobbyComm::System`, create the lobby action and the `CLobby` object
    (`+0x88`).
12. **Engine layer** `InitEngineLayer` S 00405590: create the `url2tex` instance and the graphic device;
    enumerate display modes and log them at level 3 (`Found %d possible resolutions:`); create the resource
    manager and the animation resource manager; copy the device's display-mode block (9 dwords: width, height,
    byte flag at +8, ...), put the shader path override in at +0x10 when it is ≥ 0, set the dword +0x0c to 0
    and the bytes +0x15 and +0x21 to 1 ([TODO] their meaning); if the window size differs from the
    mode size, `AdjustWindowRect` + `MoveWindow` to the mode size at the old position (a negative left or top is
    raised to 0); `S2CE::CGraphicDevice::Init(mode)` (reads `engine.ini` and `engine.xml`, §6; on the first call
    measures GPU fill rate, CPU frequency and memory speed and logs them). On success: show the UI cursor, create
    the mesh renderer, the particle manager and the decal renderer. On failure `Initialize` returns false.
13. If the scene settings were **not** read from `settings.cfg` (`Settings +0x49 == 0`): auto-detect (§3.10) the
    scene preset and the lobby detail preset.
14. If a `CLobby` exists: start it up (sound manager, graphic device), apply the profile's lobby graphics options
    and invert-mouse flag, load the zone table `world1.xml`.
15. Activate the game input action (`nUi::GameAction`) as the active action.
16. **Menus**: `nMenu::System::Initialize(showSplash = true, initMusicIds = true)` S 005dda30: register the Lua
    libraries `menu`, `ui`, `txt`; run `[data]\scripts\menu.cfg` in a temporary Lua thread; apply the language it
    set and load the text tables (§3.6); register eight UI sounds (`uiClick0`, `uiClick1`, `uiCancel`,
    `uiMessage0`, `uiMessage1`, `uiDialog0`, `uiKey0`, `uiRemove`); create every screen and dialog (§3.7); store
    the seven music sound ids; make `Splash` the current screen.
17. Window title: `<text of !SplashText> (34688)`. Create the network connection settings and the NComm manager
    (idle, state 0). Refresh the map-info caches for the map types 0, 1, 0x65, 2, 3, 100, 0x65, 0x66, 0x67
    (S 005ac880, `save-format.md` §3.11).
18. Benchmark set-up (§3.11) when a start option is present and the benchmark level is not 5.
19. Start option, first match wins: `-start` name not empty → `App_CmdLine_StartGameFile`; else `-map` name not
    empty → `App_CmdLine_StartNewMap`; else campaign index `+0x60` ≠ −1 → main screen, then
    `StartCampaignMap(index, difficulty 0)` (§3.7).
20. `running = true`; confine the cursor to the window rectangle unless `+0x1c` is set.

### 3.4 Timer [known] S 0057b790, S 0057b760, S 0057b810, S 0057b850

- Source: `QueryPerformanceCounter / (QueryPerformanceFrequency / 1000)` as a 64-bit integer division, when a
  performance counter exists; otherwise `GetTickCount` (a jump through import slot S 007d31b4, the slot the
  `GetTickCount` calls of S 00416190 use [known: reference list]). Only the low 32 bits of the result are kept.
- `Timer_Reset`: current, previous and delta = 0; start = source.
- `Timer_UpdateFrame` (once at the top of every frame): `current = source`; if `previous == 0` then `delta = 0`
  else `delta = current − previous`; `previous = current`. The first frame after a reset therefore has delta 0.
- `Timer_GetFrameDeltaSeconds` = `(float)delta / 1000.0` (delta taken as unsigned). **Resolution: 1 ms**; a frame
  shorter than 1 ms yields 0.
- `Timer_GetTotalSeconds` = `(float)current / 1000.0`: time of the source, not time since start. As a `float` its
  resolution degrades as the value grows. The source is `QueryPerformanceCounter` divided by ticks per
  millisecond, low 32 bits, with no start value subtracted (S 0057b790, `Timer_QpcMilliseconds`), and the
  quotient is a single-precision value (the x87 precision control is 24 bits, §3.3 step 4, and the readers
  keep it in `float`s) [known]. Its step is `2^(floor(log2 seconds) − 23)` s: 2 ms from 4.6 h of counter
  time, 7.8 ms from 18 h, 15.6 ms from 36 h, 31 ms from 3 days, 62 ms from 6 days, 0.5 s shortly before the
  32-bit wrap at 49.7 days. On Windows the counter runs from system start [inferred].
- `Timer_GetElapsedSecondsSinceStart` = `(float)(current − start) / 1000.0`.

No frame limiter and no sleep is in the loop (§3.5); the frame rate is bounded only by the device's vertical
sync setting (`engine.ini` `vsync`) [inferred: no wait call in S 00407cf0, S 00401bd0, S 00401780, S 004018e0].

### 3.5 Message loop and frame dispatch [known] S 00407cf0, S 00401bd0

```
while g_App.running and g_App.FrameTick():
    while PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE) == 1:
        r = DispatchMessageA(&msg)
        if msg.message in (0x100, 0x101, 0x104, 0x105) and r != 0:     # key down / up, system key down / up
            TranslateMessage(&msg)
```

One frame is run first, then the whole message queue is drained. `TranslateMessage` (which produces `WM_CHAR`)
is called **after** dispatch and only for key messages the window procedure answered with non-zero.

`FrameTick` S 00401bd0:

1. If there is no `CLobby`, or its current mode is 0 or 1: `FrameTick_InGame` S 004018e0; otherwise
   `FrameTick_Menu` S 00401780. The names are historical: the first one serves the splash, the main menu **and**
   a running match; the second one serves the 3D lobby (modes 2 and 3).
2. If a `CLobby` exists: `ProcessModeTransition(elapsed ms since start)`.
3. Store the cursor's previous position.
4. Return the tick's result; false ends the loop.

The two ticks are listed step by step in §4.

**Window procedure** `App_WndProc` S 00407c10 [known]: while `running`, `HandleWindowMessage` S 00401f30 sees the
message; for the four key messages the procedure returns 1 only when the handler returned exactly 1, for every
other message when it returned non-zero; in all other cases `DefWindowProcA`.

`HandleWindowMessage` [known]:

| Message | Effect |
|---|---|
| 0x02 `WM_DESTROY` | `PostQuitMessage(0)`, `running = false` |
| 0x12 `WM_QUIT` | `running = false` |
| 0x05 `WM_SIZE` | `minimized = (wParam == 1)` |
| 0x06 `WM_ACTIVATE` | `active = (wParam != 0)`; mute the sound manager when not active or minimised; update the cursor clip |
| 0x218 `WM_POWERBROADCAST`, wParam 9 | emergency save (`save-format.md` §2.6), `running = false` |
| 0x231 / 0x232 | size-move flag on / off; on 0x232 update the cursor clip |

After that, and only while `running`: unless the window is minimised or in a size-move, an existing graphic
device sees the message (`S2CE::CGraphicDevice::HandleWindowMessage`); when it answers non-zero nothing more
happens. Input is then forwarded only when `active`, not minimised, and the device consulted in that step was
neither in state 1 (`device +0x10c`; lost [inferred]) nor had its byte +0x514 set. A size-move alone does not
block input: it only skips the device step. Mouse button messages set the UI cursor from the low and high word
of `lParam`, then raise a UI root event and a game-action button event:

| Message | UI root event (phase, button) | Game action (button, state) |
|---|---|---|
| 0x201 / 0x202 / 0x203 left down / up / double | (0,0) / (2,0) / (1,0) | (1,1) / (1,2) / (1,1) |
| 0x204 / 0x205 / 0x206 right down / up / double | (0,1) / (2,1) / (1,1) | (2,1) / (2,2) / (1,1) |
| 0x207 / 0x208 / 0x209 middle down / up / double | (0,2) / (2,2) / (1,2) | (4,1) / (4,2) / (1,1) |
| 0x20b X button 1 / 2 down | (0,3) / (0,4) | (5,1) / (6,1) |
| 0x20c, 0x20d X button 1 / 2 up (the double click 0x20d is handled as an up) | (2,3) / (2,4) | (5,2) / (6,2) |
| 0x20a wheel | `OnMouseWheel(delta / 120)` | |
| 0x200 move | UI root event kind 3 with x, y | |
| 0x100 / 0x101 / 0x102 | `OnKeyDown(wParam)` / `OnKeyUp(wParam)` / `OnChar` | |

A double click sends game action (1,1) for all three buttons, and only when no `CLobby` exists or its vtable slot
`IsWorldActive_22` answers false for that button (argument 1, 2, 4) [known]. After a left button down and after
left or right button up the menu system is updated once more inside the message handler; after the two button-up
messages the in-game message list is updated first when the `Game` screen is active [known]. Phase and
button numbers are the arguments of the calls; their names are in `ingame-ui.md`.

Return value of the handler, which decides `WM_CHAR` generation (the loop above) [known]: 0x100 returns
`not OnKeyDown(wParam)` and 0x101 `not OnKeyUp(wParam)`, so `TranslateMessage` runs only for a key the UI did
**not** consume; 0x105 (system key up) returns true unless `wParam` is 0x11 (Ctrl) and `OnKeyUp(0x11)` answers
true; 0x104 and every other message return false. `OnChar` receives `wParam` as a signed 16-bit value.

**Cursor clip** (`UpdateCursorClip` S 00401310) [known]: `ClipCursor(window rectangle)` when the window is active
and `+0x1c` is clear, else `ClipCursor(NULL)`. Both ticks re-evaluate it when the device's display-mode block
changes.

### 3.6 Language [known] S 005dd780, S 005dda30, S 00495010, S 004955a0, S 00496e60

1. `menu.cfg` calls `menu.setLanguage("<code>")`; the binding stores the string in `nMenu::System +0x4c`. The
   install's file sets `de` and comments the value as an ISO 3166 two-letter code [known: `menu.cfg`].
2. After the script ran, `Localization::SetLanguage(code)` stores the code (`Localization +0x0c`) and registers a
   directory watch on `data\game\language`; a change in that directory sets a reload flag.
3. `LoadAllTextFiles` reads the text tables of `[data]\language\<code>\` (`formats-inventory.md` §3.9).
4. Every `nMenu::System::Update` (and the lobby menu's update S 0042a860) calls `ReloadIfLanguageChanged`: when
   the watch flag is set, the translation map
   is emptied and all text files are read again. This is a developer's hot reload, not a language switch: no code
   path found changes the language code after start [inferred].
5. Language-dependent assets are addressed as `[data]\language\<code>\<file>` (`BuildLanguagePath`). Its four
   callers are the text-table loader, the localised-texture loader (S 00494470), the UI resource path
   constructor (S 004bdc60) and the menu voice-over player (S 005db000) [known: caller list].
6. `menu.setVideoVoiceStream(name, n)` fills a `std::map<std::string, int>` (`nMenu::System +0xa8`). The
   install's `menu.cfg` sets `de → 1`, `gb → 2`, `fr → 3` [known: `menu.cfg`]; [inferred] the audio stream index
   of a video per language. [TODO] not established: the reader of that map (no function of the decompiled image
   reads it through the typed field; only the constructor, the destructor and this binding touch it).

There is no language setting in the user profile and no language switch on the command line [known: neither
`settings.cfg` (§3.9) nor the parser (§3.2) has one]. The install ships one language folder, `de`.

### 3.7 Screens and run modes

`nMenu::System::Initialize` creates four top-level screens, `Main` (0x9a8 bytes), `Game` (0x11038), `Splash`
(0x15d8), `Exit` (0xb58), the `Info` popup and nine dialogs (`ingame-ui.md` §2.7) [known] S 005dda30. One
top-level screen is current (`System +0x0c`).

**Splash** [known] S 0060bbd0, S 0060c5a0, S 0060b9a0, S 0060b7a0: plays the video `Ubisoft`, then `BB_Logo`,
then `funaticsAlpha`, then shows the continue bar (`contBar`) and the start button and selects cursor 1. A state
counter 0..4 advances each time the current video has finished. `Space` skips the current video; `Esc` or a
mouse press skips the current video and sets the state to 2, which skips the remaining videos. While a video
plays and is not fading, the update calls `ShaderPreload_StepUntilDone` each frame, so shaders are compiled
behind the intro. The start button is created hidden. Each frame in which the video object's slot +0x2c
(`IsVisible` of the UI object vtable) answers false, the update runs one more preload step and passes its return
value to the button's `SetVisible` (slot +0x24); when the button's slot +0x2c then answers true the main screen
is activated [known: call sequence S 0060c76a..0060c7b2]. So the main menu follows the videos as soon as the
shader preload reports done, without a click [inferred: the step's return value is its "finished" flag].

**Main** (`menumain.xml`), three panels [known] S 005e27c0:

| Panel | Button key | Action |
|---|---|---|
| 0 | 0 | show panel 1 (single player) |
| 0 | 1 | request the lobby (`System +0xb4 = 1`), music 0 |
| 0 | 2 | options panel |
| 0 | 3 | credits text, music 4 |
| 0 | 4 | close dialogs, open the requester with type "exit to desktop" |
| 1 | 5 | campaign: restart the network layer offline, show panel 2 |
| 1 | 6 | free game: restart the network layer offline, show the free-game panel |
| 1 | 7 | load: restart the network layer offline, open the load panel |
| 1 | 8 | continue the last save |
| 1 | 9 | back |
| 2 | 10, 0x16 | back |
| 2 | 0x0b .. 0x15 | campaign map tile 0 .. 10: start that map with the marked difficulty |

"Restart the network layer offline" is `NComm_Manager::Shutdown(false)` followed by `StartUpNetwork(0)` (role 0,
`network-session.md` §3.3). The assignment of keys 1 to 4 to the named buttons follows the order in which the
screen registers them [inferred].

**Run modes and what they put into the descriptor** [known unless tagged]:

| Mode | Entry | Network role | Descriptor | Players |
|---|---|---|---|---|
| Campaign map | `nMenu::Main::StartCampaignMap(index, difficulty)` S 005df2c0 | 0 | `SetMapNameAndType(type, map.fileName)` with type 1, or 0x65 when the map's kind is 1 (a kind that is neither 0 nor 1 gives 1); `+0x20` = difficulty; `+0x24` = 0; slots 0..7 kind 1 (computer), tribe −1; then slot 0 kind 2 (local human) | from the map file (`players-victory.md` §3.4) |
| Free game | free-game panel: `SetMap` S 005e8410 (type 0), `StartFreeGame` S 005e7350 | 0 | type 0. `SetMap` reads the map's `MapInfo`, makes slot 0 kind 2, turns kind 2 or 3 in slots 1..5 into 0, sets team and start position of row *i* to *i*, the tribe from the row's combo (0xb0d378a3 when it has none) and `+0x20` = 2. `StartFreeGame` re-indexes kind, tribe, colour, team, `MapInfo` per-slot dword +0xc8 and name of the six rows by each row's chosen start position, and registers row *i* as session slot *i* (kind 1 → slot type 2, kind 2 → 1, else 3) | from the descriptor |
| Load | load panel → `System +0x68` → `StartPendingMap` S 005d9fd0 | 0 | `SetMapName(name)` → type 110. The function also reads the save's `MapInfo` and registers its players with the session: if every player has kind 0, player 0 becomes kind 2; the kind-2 player is session slot 0 (type 1), the others take slots 1.. in order (kind 1 → type 2, else 3) | from the save |
| Continue | `ContinueLastSavegame` S 005dfef0, name = profile `+0x08` | 0 | `SetMapName(name)`. Before that: the file must exist as type 110 or else as type 10, otherwise message box `!FILENOTFOUND`; its `MapInfo +0x1f0` must be < 2, otherwise message box `!INVALID_SAVEGAME` | from the save |
| `-start <name>` | `App_CmdLine_StartGameFile` S 00401420 | 0 | `SetMapName(name)` | from the save |
| `-map <name>` | `App_CmdLine_StartNewMap` S 00401350 | 0 | `SetMapNameAndType(0, name)`; `MapInfo` map type = 0; `MapInfo` name = name; slot 0 kind 2, tribe id 0xb0d378a3 | from the descriptor |
| Network game | lobby game set-up dialog, `SetupSession` S 004562d0; start through the session (`network-session.md` §3.8) | 4 for the host (`CreateGameServer` S 0046aaa0), 3 for a joiner (`JoinGame` S 0048d030); no call site of `StartUpNetwork` passes 1 or 2 [inferred: call list of the decompiled image] | type 0 and the host's options | from the descriptor |
| Map editor | the `Debug` dialog (slot 1) holds the editor tools and a load / save of map type 1 into the running world (`save-format.md` §3.8) | | | the dialog has no opener in this build (`../subsystems.md` §5) |

Every offline entry does `NComm_Manager::Shutdown(false)`, `StartUpNetwork(0)`, `ConnectAndJoin` (a fresh
one-machine session), fills the descriptor and ends in `nMenu::System::ActivateGameScreen` S 005d9f10 (the load
path inlines the same steps). The campaign and free-game starts restart the network first and fill the slots
afterwards; load, continue, `-start` and `-map` write the name into the descriptor first and restart the network
after it [known]. The campaign start finally activates the game input action. `ActivateGameScreen`
closes all dialogs and the current screen, hides the in-game message slots, makes `Game` current, calls its
enter hook (`nMenu::Game::OnEnter` S 005eed00 → world build, `save-format.md` §3.8) and clears the minimap
symbol list. The world build is synchronous inside that call: the frame in which a mode is entered lasts as long
as the load [inferred].

**Leaving a match** (`nMenu::Game::OnLeave` S 005eb030) [known]: clear the network chat and message sinks, shut
the network layer down, destroy the HUD widgets, `nGame::System::Shutdown`, destroy the scene, reset the
descriptor (§2.3), resume all sounds when the byte `Game +0xfff9` is set, clear the minimap symbols, detach the
screen. Which screen follows is decided by the caller
(`ingame-ui.md` §3.9).

**Free-game map list** (`nMenu::SelectMapDialog::RefreshMapList` S 00615370) [known]: the maps of type 0, then
the maps of type 3 (user maps), in two row colours.

**The `Exit` screen** shows three full-screen pictures `s2c_demoscreen0` .. `s2c_demoscreen2`, loaded as
localised textures, one per click, and then requests the quit (S 0060b260, S 0060b570) [known]. No code makes it
the current screen: the pointer `System +0x44` is only written at creation and destruction [inferred: field
uses in the decompiled image], so the shipped game quits without it.

### 3.8 Campaign [known] S 005df440, S 005decf0, S 005e27c0, S 005df2c0

- **Table.** `campaigns.xml` (§6) lists campaigns; a campaign lists maps in display order. The main screen
  shows the campaign whose name it holds (`Main +0x20c`). The name is the attribute `campaignName` of the root
  element of `menumain.xml`, read in `nMenu::Main::OnInitLoadXml` S 005e0bb0; the install's file has
  `campaignName = "Main"` and `campaigns.xml` has that one campaign [known: both files].
- **Unlock rule.** A map is selectable when **every** name in its prerequisite list has a profile record with
  `completed` set. A map without prerequisites is always selectable. A locked tile is disabled and its two texts
  are drawn at (0.5, 0.5, 0.5, 1.0); an unlocked one at (1, 1, 1, 1).
- **Tile.** A tile is 0x18 bytes: button, text, four badge objects. The text is set from the map's `name` with
  the text setter's flag true ([inferred] the name is used as a text key); the button's user data is index + 1.
- **Completed badge.** For an unlocked map whose own record is completed, the badge with index
  `record.difficulty` is shown: the badge names the highest difficulty value the map was completed with. The
  index is not range-checked; a completed record always has a value ≥ the winner's difficulty or, read from a
  version 0 record, 2 (§3.9).
- **Difficulty.** Four buttons (`DiffButton` 0..3). A click marks one, stores the index in the profile (`+0x3c`)
  and writes `settings.cfg` at once (S 005ded70). A start takes the marked button with the highest index, or 2
  when none is marked. The fourth button (index 3) is made visible only when the **last map of the campaign's
  list** is completed. The value's effect on the players is in `players-victory.md` §3.4.
- **At most eleven maps** per campaign can be started: tile button keys 0x0b..0x15 [known].
- **Start.** §3.7. The record key is the map's `MapInfo` name (`MapInfo +0x24`), while prerequisites name the
  `name` attribute; the shipped data uses the same string for `name`, `filename` and, [inferred], the name stored
  in the map file.

**Map state transitions** [known]:

| Event | Function | Change |
|---|---|---|
| A world was loaded (any mode, also a save) | `UserMapStates_MarkCurrentMapStarted` S 0057b270, last step of `Game_LoadWorldFromDescriptor` | record created if missing; `mapName` set; `state = 2`. `completed` and `difficulty` are kept |
| The local player won | `UserMapStates::RecordCurrentMapCompleted` S 0057b680 → `RecordMapCompleted` S 0057b330, called from `VictoryConditions::DeclareWinner` S 00535990 (`players-victory.md` §3.7) and from the chat line `DontWantToLose` (S 005ec340); both then write `data.cfg` | record created if missing under the current `MapInfo` name; `completed = true`; `+0x24` = `MapInfo +0x1c8`; `difficulty = max(difficulty, the local player's value at Player +0xec)`; `state = 0` unless it is 1 |
| The in-game screen sees `state == 0` and its screen 8 is not attached | `IsCurrentMapCompletionPending` S 0057a510, then S 0057b450 (`nMenu::Game::Update` S 005efea0) | `state = 1`; then `ToggleScreen(3)` when the map type (`MapInfo +0x1d0`) is 1 or 0x65, else `ToggleScreen(0)` (`ingame-ui.md` §3.9) |

Because loading a world sets `state = 2` again, a completed map that is restarted shows its end dialog again on
the next win, while `completed` stays set [inferred].

Records exist for every map ever loaded, not only campaign maps: a free-game map gets a record under its own
name and can satisfy a prerequisite of that name [inferred].

### 3.9 User folder and profile files

**Folders** (`Fs_CreateUserDataDirectories` S 0057bfb0) [known]: eight `CreateDirectoryA` calls, results ignored:
`<My Documents>\SAdK`, `...\users`, `...\maps`, `...\saves`, `...\dumps`, `...\dumps\lobby`,
`...\screenshots`, `...\lobby`. Called at start and before every profile write, save write, desync dump,
screenshot and avatar file access (eight callers). The folder name is the
literal `SAdK` (S 007d421c), the same literal as the window title name. `<Local AppData>\SAdK` is created on
demand by the cache writers (`formats-inventory.md` §3.12).

**`users\settings.cfg`**: plain `NCore::FileStream`. Written by `UserProfile::StoreSettings` S 00579640, read by
`LoadSettings` S 00579960 [known]:

```
tag    UserSettings, version 2
str    lastSaveName                                        +0x08
f32    gameSpeed                                           +0x24   read, then replaced by 1.0
i32    autosaveIntervalSec                                 +0x04
bool   quit requester's autosave check box                 +0x34   stored, never read back (§2.6)
bool   invertScrolling                                     +0x28
f32    scrollSpeed                                         +0x2c
bool   borderScrolling                                     +0x30
bool   smartCursor                                         +0x31
f32    sound-effect master volume                                  applied on read
f32    volume of sound category 1, 2, 3, 0 (four values)           applied on read (audio.md)
bool   (unused)                                            +0x32   stored only (§2.6)
bool   freeCamera                                          +0x33
i32    n            written as 2
i32    × n          n values into +0x38, +0x3c, ...        +0x38 stored only, +0x3c campaign difficulty
str    offline player name                                 +0x40
i32    connectionType                                      +0x94
str    lobby account name                                  +0x5c
str    (unused)                                            +0x78   stored only (§2.6)
i32    lobbyShadowQuality, lobbyMirrorQuality, lobbyTextureQuality, lobbyObjectDetails, lobbyShaderDetail
bool   lobbyInvertMouse                                    +0xac
tag    SceneSettings, version 1 (the reader ignores its version)
i32    qualityPreset           the reader calls SetQualityPreset(value), which fills every preset field, before
                               the individual values below replace them
bool   postFx                  +0x0c   read, then forced to false
f32    textureQuality          +0x10
bool   displayModeFlag         +0x1c
i32    displayWidth, displayHeight     +0x14, +0x18
f32    groundDetail            +0x20
bool   scene render flag 0x80  +0x24
bool   fog display cache       +0x25
bool   shadows on              +0x26
f32    shadowQuality, shadowDetail     +0x28, +0x2c
bool   mirror on               +0x30
f32    mirrorQuality, mirrorStrength   +0x34, +0x38
i32    shader level            +0x3c
f32    detail, objectDetails           +0x40, +0x44
bool   +0x48                           meaning not established (§2.7)
```

This is the only specification of the file; `formats-inventory.md` §3.11 links here. Field meanings: §2.6
(`UserSettings`) and §2.7 (`SceneSettings`).

Version rules of the reader [known]:

- `UserSettings` version < 2: in place of `n` and the `n` values there is one `i32` (→ `+0x38`), and `+0x3c` is
  set to **0**.
- version < 1: the five lobby values and `lobbyInvertMouse` are absent and read as 0 / false.
- The reader does not bound `n`: it stores `n` values starting at `+0x38`. A file with `n > 2` overwrites the
  string at `+0x40` and what follows. A reimplementation must bound it.

After the scene block is read [known] S 006960a0:

- with no graphic device yet (the normal case at start): width, height and the display mode flag are copied to
  the globals S 0087c408, S 0087c40c, S 0087c410, the start mode of the device [inferred];
- with a device: on a device of capability level < 2 (`device +0xf8`) shadows are switched off (`+0x26 = 0`,
  shadow quality and detail 0); the device's texture detail level is set to
  `clamp(3 − trunc(textureQuality × 3.0), 0, 2)`; the display mode is applied unless the device's mode block has
  its byte +0x20 set;
- `Settings +0x49 = 1`.

`Store` writes the device's current width and height instead of the stored ones when a device exists and its
mode block byte +0x20 is clear, and applies the same "no shadows below capability 2" rule first [known]
S 00696270.

**`users\data.cfg`**: plain `FileStream` [known] S 0057a0b0, S 0057b500, S 00579e80, S 00579ed0:

```
tag    UserMapStates, version 0
u32    count
count × {
    tag    UserMapState, version 1
    str    mapName
    bool   completed
    i32    state          0, 1 or 2 (§2.6)
    i32    difficulty     absent in a version 0 record, then read as 2
}
```

Records are written in ascending order of the map name (byte-wise string order of the `std::map`). On read each
record is inserted under the name **stored in the record**.

**When the files are read and written** [known]:

| File | Read | Written |
|---|---|---|
| `settings.cfg` | once at start (`UserProfile_LoadFromDisk` S 00578fe0); a missing or unopenable file is skipped and the defaults stay | closing the options panel (S 005e5490, its `closeButton` click S 005e5b70, its destructor S 005e61b0); a click on a difficulty button (S 005ded70); shutdown |
| `data.cfg` | once at start, same rule | a win of the local player and the cheat (`players-victory.md` §3.7); shutdown |

At shutdown both writes are skipped when the graphic device exists and its display-mode block has byte +0x20 set
(S 005795d0) [known]; [TODO] not established: what sets that byte. A write that cannot open its file does nothing.
Starting a map does not write `data.cfg`, so a "started" record reaches the disk only with the next write.

**Autosave** (`nGame::Autosave::Update` S 0078b040) [known]: only in network role 0 and when the interval is not
0. While the stored time is 0.0 a call only stores `Timer_GetTotalSeconds()`; later, when `now − last > interval`
(strictly greater; real time of the frame timer, not game time), it posts the message `!Autosave...` to the
local player (message kind 8), stores `now` and writes the save
`Autosave` (`save-format.md` §2.6). The options control `cAutosave` lists minute values; the stored interval is
`minutes × 60` [inferred: the control is matched with `interval / 60`, S 005e55b0].

**Options panel** (`menuoptions.xml`, 27 controls bound by name, index = option number) [known: names from the
initialiser S 007c7570; order inferred from `LoadOptionValue` S 005e55b0]:

| # | Control | Target |
|---|---|---|
| 0 | `cVideoMode` | display size (entries from the device's mode list) |
| 1 | `cDisplayMode` | `Settings +0x1c` |
| 2..8 | `cGroundDetail`, `cShadowQuality`, `cShadowDetail`, `cMirrorStrength`, `cMirrorQuality`, `cObjectDetails`, `cDetail` | `Settings` (§2.7) |
| 9 | `cTextureQuality` | `Settings +0x10` |
| 10..14 | `cLobbyShadowQuality`, `cLobbyMirrorQuality`, `cLobbyShaderDetail`, `cLobbyTextureQuality`, `cLobbyObjectDetails` | lobby graphics; disabled when no `CLobby` exists |
| 15 | `cLobbyInvertMouse` | lobby |
| 16..19 | `masterVol`, `musicVol`, `effectVol`, `interfaceVol` | sound (`audio.md`) |
| 20 | `sScrollSpeed` | profile `+0x2c` |
| 21..24 | `cBorderScrolling`, `cSmartCursor`, `cFreeCamera`, `cInvertScrolling` | profile `+0x30`, `+0x31`, `+0x33`, `+0x28` |
| 25 | `cAutosave` | profile `+0x04` |
| 26 | `cConnectionType` | profile `+0x94` |

### 3.10 Quality presets and first-run detection

`Settings::ApplyQualityPreset` S 00695860 [known]:

| Preset | +0x20 ground | +0x28 shadow q. | +0x2c shadow d. | +0x34 mirror q. | +0x38 mirror s. | +0x40 detail | +0x44 objects | +0x10 texture | +0x3c |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| 1 | 0.25 | 0 | 1/6 | 0.25 | 0.25 | 1/3 | 0.25 | 1/3 | 2 |
| 2 | 0.5 | 0.5 | 1/3 | 0.5 | 0.5 | 2/3 | 0.5 | 2/3 | 3 |
| 3 | 0.75 | 0.75 | 2/3 | 0.75 | 0.75 | 1.0 | 0.75 | 1.0 | 3 |
| 4 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 3 |

Then `+0x26 = (shadow detail > 1/6)` and `+0x30 = (mirror quality > 0)`: presets 0 and 1 have no shadows, preset
0 has no mirror.

**First run** (no `settings.cfg`, §3.3 step 13) [known] S 00695fc0, S 005798a0. The score is the GPU fill rate
the device measured at its first initialisation, in million pixels per second (`device +0xfc`):

| Fill rate | Scene preset | Lobby (shadow, mirror, texture, object details, shader) |
|---|---|---|
| < 500 | 0 | 0, 0, 0, 0, 0 |
| < 700 | 1 | 0, 1, 0, 1, 0 |
| < 1000 | 2 | 0, 1, 0, 1, 0 |
| < 1500 | 3 | 0, 1, 1, 2, 1 |
| ≥ 1500 | 4 | 3, 1, 1, 2, 1 |

The measured CPU frequency and memory speed are passed to the lobby preset function and not used [known].

### 3.11 Benchmark mode ("hwlab") [known] S 004075d0, S 00680b70

Active when a start option is present (§3.3 step 19) **and** a `-hwlab_*` switch set a level 0..4. Set-up: the
scene quality preset is set to the level [inferred: the argument of the call is not visible in the decompiled
code]; flag S 0088ca68 = 1; sample counter S 008810e4 = 15; level S 008810e8; the `-start` name is copied to
S 0088113c. While the flag is set, the scene's debug overlay pass calls `HWLabLogFrameRate` every frame:

1. Count frames. When more than 1.0 s of the scene's real time has passed since the last sample:
   `fps = frames / elapsed`; reset.
2. If `fps > 0`: unless the final latch is set, log at level 3
   `framerate;<start name>;<level>;<computer name>;<fps with two decimals>`; decrement the sample counter.
3. When the counter falls below 0: the first time, request a screenshot and set the latch; the next time,
   `_exit(0)`: the process ends without shutdown.

The lines are written only with `-log_info`. With the counter starting at 15, sixteen lines are logged; the
screenshot is requested on the sixteenth sample and the process ends on the seventeenth [inferred]. The start
name is empty when the start option is `-map` or the campaign index.

### 3.12 Log and crash files

**Log** (`Log_Printf(level, fmt, ...)` S 006e5950, `LogFile_ctor` S 006e5620) [known]:

- A message is written when `level <= g_LogLevel`. The image calls it with levels 1, 2 and 3 (about 230, 2 and
  75 call sites in the decompiled image). With the default level 1 only level-1 messages appear.
- The file is created at the first message that passes the filter: delete `<dir>\Logfile_9.txt`; rename
  `Logfile_8.txt` → `Logfile_9.txt` down to `Logfile_0.txt` → `Logfile_1.txt`; open `Logfile_0.txt` for
  writing. So **ten** logs are kept, `Logfile_0.txt` being the current run.
- First lines: `Date : YYYY-MM-DD hh:mm:ss`, then `User : <Windows user name>` when `GetUserNameA` succeeds.
  Both go through `Log_Printf` at level 1, so they carry the line prefix, and both formats end in a line feed
  of their own, so each is followed by an empty line.
- Line format: `- hh:mm:ss - ` (local time) followed by the formatted text and a line feed (0x0a only). One
  4096-byte buffer is shared by all calls (`_vsnprintf_s` with size and count 0x1000). [TODO] not established:
  what happens to a longer message (settled by the CRT's `_vsnprintf_s` behaviour for count = size).
- `<dir>` is the log directory of §3.3 step 3.

**Crash report** [known] S 00407cf0 (exception scope table S 0084aed0), S 006e63d0:

`WinMain` runs steps 5 to 9 of §3.1 inside a structured exception scope whose filter is
`Crash_HandleException(exceptionPointers)`:

1. Create an unnamed mutex and wait on it.
2. `crashdump.dmp`: `CreateFileA(<dir>\crashdump.dmp, write, share read|write, CREATE_ALWAYS)`, then
   `MiniDumpWriteDump` with dump type 0 and the exception pointers (S 006e6300).
3. `crashlog.txt`: `fopen(<dir>\crashlog.txt, "w")`. If that fails the filter returns 0 and the exception
   continues to the next handler. Else initialise DbgHelp (`SymSetOptions(0x496)`, symbol path
   `<current directory>\Bin`), collect the module list, and write:
   - `BuildVersion: 34688`
   - a block headed `CALLSTACK` between two lines of dashes: `    <exception name> (0x<code>) at <address> : `,
     the registers `eax ebx ecx edx` and `ebp eip esi esp`, then the stack walk;
   - a block headed `MODULE LIST` with the loaded modules.
4. Clean up DbgHelp, release and close the mutex, return 1.

Both names are fixed: a time stamp and the computer name are formatted in `Crash_BuildOutputPath` S 006e6030 but
only directory, name and extension are appended, so each crash overwrites the previous files [known].

When the filter returns 1 the handler in `WinMain` (S 00407f3a) logs `EXCEPTION OCCURED : `, two line feeds and
the collected call-stack text at level 1, closes the instance mutex and returns the `wParam` of the last message. `CApplicationEx::Shutdown` is **not** called
on this path, so `settings.cfg` and `data.cfg` are not written after a crash [known: control flow S 00407f3a].
The scope covers the main thread only [inferred].

`data\game\language\crashmsg.ini` (plain text, section `[msg]`, keys `caption` and `text`, the text holding the
placeholder `[DIR]` and asking the user to mail the folder's content) is not named anywhere in the image
[known: string search]; [inferred] another program of the install shows it. [TODO] not established: which one.

Other files in the log directory: the lobby log (opened at start, truncated, first line
`---------------------------------------------- Log begins on <time> ----...`, S 00466c40; its path is
`<dir>//LobbyComm.log`, the name set by the logger's constructor S 004669e0 and the two slashes by
`GetLogFilePath` S 00466ad0 [known]; the constructor's size cap of −1 means no cap), desync dumps
`*.s2dump.txt` (`save-format.md` §3.10).

### 3.13 Exit and shutdown

Ways the loop ends [known]:

| Cause | Mechanism |
|---|---|
| Quit confirmed in the requester, or another caller of `nMenu::System::RequestQuit` S 005d9ee0 | stops the music, sets `System +0x08`; `FrameTick_InGame` returns false at the end of that frame |
| Window destroyed | `WM_DESTROY` → `PostQuitMessage(0)`, `running = false` |
| Low battery | emergency save, `running = false` |
| The graphic device reports "not ready" at the top of a tick | the tick returns false |
| Benchmark finished | `_exit(0)`, no shutdown |

`FrameTick_Menu` (3D lobby) does not test the quit flag; from there the loop ends through `running` or the
device test [known] S 00401780.

`CApplicationEx::Shutdown` S 00401cb0, in this order [known]:

1. `running = false`.
2. Menu system: stop music, close all screens, delete the screens, destroy the UI cursor and the game action,
   stop the language directory watch, destroy the localisation; destroy the menu system.
3. If a `CLobby` exists: delete it, shut down and destroy the lobby screen host, destroy the lobby action.
4. Destroy the UI resource manager; shut down the debug toggle window if it exists.
5. **User profile**: write `settings.cfg` and `data.cfg` (§3.9), destroy the profile.
6. Sound: shut down if initialised, destroy.
7. Destroy the Lua host.
8. Destroy the render singletons (decal renderer, particle manager, mesh renderer and resource managers;
   [inferred] from the creation list of §3.3 step 12), shut down and destroy the graphic device.
9. `Timer_Shutdown`.
10. Clear and destroy the property database.
11. Destroy the NComm manager and the connection settings.
12. Destroy the file index.
13. Destroy the lobby manager and the lobby profile, if they exist.

Back in `WinMain`: close the instance mutex, return.

---

## 4. Update order

### 4.1 On start

§3.3, steps 1 to 20, in that order.

### 4.2 Per frame, main menu or match: `FrameTick_InGame` S 004018e0 [known]

1. Graphic device not ready → return false.
2. `Timer_UpdateFrame`.
3. Reload UI XML if a reload was requested (developer hot reload).
4. Game input enabled = `active` and not `minimized`.
5. If the `Game` screen answers true from its vtable slot +0x10: `nGame::System::Update` S 00780d20, then the
   in-game message list's update. `nGame::System::Update`, in order: on the host, while the session is in state 3
   and every slot reports loaded, `BroadcastStartGame` (each frame until the state changes); the autosave
   (§3.9) unless the UI is suppressed (`nMenu::System +0xa4`) or the system's cinematic byte is set; the game
   cursor; the camera; and, once the logic tick counter is not −1, the game sound object and, with the UI not
   suppressed, the game music and the cutscene camera.
6. `nMenu::System::Update` S 005da500: language hot reload, UI cursor; unless the UI is suppressed
   (`System +0xa4`): every open dialog, the topmost open dialog that wants the focus, the text-input enable
   flag S 0087c0e5 (= message box not open), the UI root; then minimap symbol expiry and the game action's
   update (slot +4); **if a pending map path is set (`System +0x68`), `StartPendingMap` runs here** and the
   path is cleared.
7. If the NComm manager exists: `Process_MainLoop`.
8. Lua threads: `LuaScriptHost::UpdateThreads(Timer_GetTotalSeconds())`.
9. If the logic system exists: set the FPU control word (§3.3 step 4), then
   `NLogic::System::Update(NULL, true)`: all logic ticks due this frame (`logic-core.md` §3.1, §4.2).
10. `SoundSystem::Update(frame seconds)`.
11. Device-lost check.
12. If the 3D world is not shown behind the screen (`System +0xb5 == 0`) or no `CLobby` exists:
    1. if a lobby manager exists, `LobbyComm::System::StatePump_Tick`;
    2. unless (the game system exists and its byte +0x6c is set) or minimised or in a size-move: if the device
       is in the lost state try to restore it, else `App_RenderWorldFrame(frameDelta, accumulatedTime)` with the
       two values of the logic system (0 when none exists);
    3. if the display-mode block changed, copy it and update the cursor clip.

    Otherwise: `CLobby::Update(elapsed ms since start, active)` (the lobby world renders the frame).
13. If a `CLobby` exists and the enter-lobby request is set (`System +0xb4`, consumed here): clear `-lobbyfast`;
    without `-localhostmode` request mode 3 and call `SetField80(2)`, with it request mode 2.
14. Return `System +0x08 == 0` (quit flag clear).

`App_RenderWorldFrame` S 00401260 [known for the call order; slot meanings inferred]: update the resource
manager's video-memory sink; if a scene exists (`g_pScene` S 0088ca60), read a counter from it (vtable +0x80),
call its slots +0x20(0) and +0x2c, and **skip the frame when the counter is below 5** (unsigned compare); update
the device transforms; `BeginRendering`; only when that answers true: `nMenu::System::Render` S 005d9800, then
`EndRendering(present)`. `nMenu::System::Render` draws the UI root tree and then the requester dialog once more
on top when it is open [known]. The world is drawn from inside that tree: the `Game` screen's draw hook
S 005efdd0 calls the game system's render slot first and its HUD and debug overlays after it [known]; so the
order on screen is world, HUD, other UI, requester [inferred].

"Elapsed ms since start" in this section is `Timer_GetElapsedSecondsSinceStart() × 1000` truncated to a 64-bit
integer, passed by pointer; "start" is the last `Timer_Reset` (§4.6).

### 4.3 Per frame, 3D lobby: `FrameTick_Menu` S 00401780 [known]

1. Graphic device not ready → return false.
2. `Timer_UpdateFrame`; UI XML hot reload.
3. Lua threads.
4. NComm `Process_MainLoop`, if the manager exists.
5. `CLobby::Update(elapsed ms since start, active)`.
6. `SoundSystem::Update(frame seconds)`.
7. Device-lost check.
8. Display-mode block changed → copy it; clip the cursor when active and `+0x1c` is clear, else release it.
9. Return true.

No logic tick and no `nMenu::System::Update` run in this tick.

### 4.4 After either tick: `FrameTick` S 00401bd0 [known]

`CLobby::ProcessModeTransition` (if a lobby exists), then store the cursor's previous position; then the message
queue is drained (§3.5).

### 4.5 Per logic tick

Nothing of the shell runs per logic tick. Its only per-tick influence is the number of ticks a frame executes,
through the frame time and the profile's speed factor (`logic-core.md` §3.1).

### 4.6 On entering and leaving a match

§3.7: restart the network layer, fill the descriptor, `ActivateGameScreen` → world build; `OnLeave` in reverse.

Two timer effects of a world build [known]:

- `NLogic::System::PostLoad` S 005273d0 ends with `Timer_Reset` (when the timer is initialised). It is the
  second caller of `Timer_Reset` besides `Initialize`. So after it the current, previous and delta values are 0
  and the start sample is new: the first frame after the load has frame time 0 (the load time is not fed into
  the tick accumulator), `Timer_GetTotalSeconds` reads 0 until the next `Timer_UpdateFrame`, and "elapsed since
  start" counts from the load. `PostLoad` has no direct caller (a virtual call); [TODO] not established: which
  world-build paths reach it (new map, save, empty world), settled by the vtable slot's call sites in
  `nGame_File_load` and `ResetAndInitSubsystems`.
- `nGame::System::BuildWorld` S 00784d40 sets the autosave's stored time to 0.0 (helper on `System +0x5f8`), so
  the autosave interval starts again with the first update of the new match (§3.9).

---

## 5. Inputs and outputs

**Consumes**

- the process command line; the Ctrl key state at start;
- Windows messages (input, activation, size, power);
- `<install>\data\...` through the file index: `menu.cfg`, `campaigns.xml`, `engine.ini`, `engine.xml`,
  `LobbySettings.ini`, the text tables;
- `<My Documents>\SAdK\users\settings.cfg`, `data.cfg`;
- the performance counter.

**Produces**

- the window and the cursor clip;
- frame time for every subsystem (`Timer_*`), and through it the tick count per frame;
- the filled `GameLoadDescriptor` for the world build;
- `settings.cfg`, `data.cfg`, `Logfile_N.txt`, `crashlog.txt`, `crashdump.dmp`, the user folders;
- the process exit code.

**Interfaces**

| To | Through |
|---|---|
| Simulation | `NLogic::System::Update` once per frame; FPU control word before it; `UserProfile +0x24` speed factor |
| World build / save | `GameLoadDescriptor`; `UserProfile +0x08` last save name; autosave timer |
| Network | `NComm_Manager::Shutdown` / `StartUpNetwork(role)` / `ConnectAndJoin` before every start; `Process_MainLoop` every frame; build number |
| UI | `nMenu::System` (update, render, pending map path, quit flag, enter-lobby request); UI root and game-action events from window messages |
| Players and victory | map states (`RecordMapCompleted`, completion pending); campaign difficulty in `desc +0x20` |
| Rendering | `S2CG::Settings`; device display mode; `App_RenderWorldFrame` |
| Audio | volumes from `settings.cfg`; mute on deactivation; `SoundSystem::Update` every frame; menu music |
| Lua | host creation; `properties`, `menu`, `ui`, `txt` libraries; `menu.cfg`; `UpdateThreads` every frame |

---

## 6. Data-driven parameters

Files of the install that the shell reads. `[data]` resolves to `data\game\` and `data\lobby\`
(`formats-inventory.md` §2.1).

**`[data]\scripts\menu.cfg`** (encrypted; Lua 5.0, run once at start) [known: file content]:

| Call | Example values |
|---|---|
| `menu.setLanguage(code)` | `"de"` |
| `menu.setVideoVoiceStream(name, n)` | `("de", 1)`, `("gb", 2)`, `("fr", 3)` |
| `menu.setPlayerColor(index, r, g, b)` | eight calls, index 0..7, e.g. `(0, 0.01, 0.1, 0.60)`, `(1, 0.60, 0.00, 0.00)` |

**`[data]\ui\layout\campaigns.xml`** (encrypted) [known: file content]: root `Campaigns`, one `Campaign
name="Main"` with eleven `Map` elements `C01` .. `C11`, each with `name`, `desc` (`C01_desc`, ...), `filename`,
`type="map"` and prerequisites:

| Map | Prerequisites |
|---|---|
| C01 | none |
| C02 | C01 |
| C03 | C02 |
| C04 | C03 |
| C05 | C03 |
| C06 | C05 |
| C07 | C06 |
| C08 | C06 |
| C09 | C08 |
| C10 | C09 |
| C11 | C04, C07, C10 |

So after C03 the campaign branches (C04; C05 → C06 → C07; C06 → C08 → C09 → C10) and C11 needs all three branch
ends. Completing C11, the last entry, unlocks the fourth difficulty.

**`[data]\settings\engine.ini`** (plain text, UTF-8 byte order mark, Win32 profile format), section `[Engine]`,
read by `S2CE::CGraphicDevice::Init` S 004da2a0 with `GetPrivateProfileIntA` [known]:

| Key | Default in code | Install | Meaning |
|---|---|---|---|
| `vsync` | 1 | 0 | wait for vertical sync |
| `refreshRate` | 0 | 0 | refresh rate, 0 = default |
| `useMeshCache` | 1 | 1 | use the converted-mesh cache in `<Local AppData>\SAdK` |
| `hardwareCursor` | 1 | 0 | not read when the device runs in an external window |

The examined install is a working copy; its values may differ from the retail defaults. Its file starts with a
UTF-8 byte order mark directly before its only section `[Engine]`, which hides the section from the Win32 reader:
every key takes the code default (so the "Install" column has no effect), and edits to the file have no effect until it is saved without the mark [live, 2026-10-14;
`formats-inventory.md` §3.10]. A remake's reader should strip the mark.

**`[data]\settings\engine.xml`** (encrypted), attributes of the root `Engine`, read in the same function
[known]: `pureDevice` (bool), `specialDepthMap` (bool), `lowresDepthMap` (bool), `mixedDevice` (bool; not in
the install's file), `multiSample` (int, install `0`), `hwCursor` (cursor image path; the code default and the
install's value are both `[data]\gfx\Mousecursors_MainCursor.tga`) and `hotspot` (two ints, install `2 1`,
default 0 0; read only when `hwCursor` is present). The install's three bools are `true`. The file is skipped
when it cannot be opened. It also carries `hardwareCursor` and `vsync` attributes that the function does not
read. Their effect belongs to [`rendering.md`](rendering.md).

**`data\lobby\config\LobbySettings.ini`** (plain): `[LobbyServer]` `Host`, `Port`; `[LobbyClient]`
`HallOfFameURL0..2`, `HallOfFameURL<n>_AppendPermID` (`formats-inventory.md` §3.10).

**`[data]\settings\network.ini`**: read at every network start-up, not by the shell; keys and defaults in
`network-session.md` §6.

**Constants in the image** [known]:

| Constant | Value | Where |
|---|---|---|
| Build number | 34688 | S 008793c0 |
| Instance mutex name | `sadk` | S 007d420c |
| Window class, title name, user folder | `S2Class`, `SAdK`, `SAdK` | S 007d4214, S 007d421c |
| Default log level | 1 | S 00882690 |
| Default autosave interval | 600 s | S 00579c00 |
| Default scroll speed | 0.25 | S 00579c00 |
| Default campaign difficulty | 2 | S 00579c00 |
| Default connection type | 3 | S 00579c00 |
| Benchmark samples | 15 | S 004075d0 |
| Empty world size | 80 | S 005a9bb0 |
| Music sound ids (7) | 0x88795c63, 0xda79b9c3, 0x6b9cd9c3, 0x75274083, 0xafac25d3, 0x38965d63, 0x07b36453 | S 005dda30 |
| Scene-preset thresholds | 500, 700, 1000, 1500 million pixels / s | S 00695fc0 |
| Lobby-preset thresholds | 500, 1000, 1500 million pixels / s | S 005798a0 |
| Autosave save name | `Autosave` | std::string S 0087e920, static initialiser S 007c6310 |
| Lobby log file name | `LobbyComm.log` | S 004669e0 |

---

## 7. Save and load

Nothing of the shell's own state is in a save game. Related facts:

- The descriptor is not saved. A save restores players, options and map type from its `MapInfo` and logic part
  (`save-format.md` §3.8); the descriptor only carries the name and type 110.
- The profile's speed factor is not in a save and not effectively in `settings.cfg`: every match starts at 1.0
  (`logic-core.md` §3.1).
- Writing a save in role 0 stores its name in the profile (`+0x08`); "Continue" uses it. It reaches the disk
  with the next `settings.cfg` write.
- The campaign position is **not** a save: it is the set of `completed` flags in `data.cfg`. Deleting `data.cfg`
  locks every map except those without prerequisites; copying it carries the progress.
- Loading any world sets that map's state to 2 in memory (§3.8).
- The autosave timer is rebuilt: it is primed by the first update after a world build and counts real time.
- Scene settings, volumes and scroll options belong to `settings.cfg`, not to a match.

---

## 8. Determinism notes

The shell holds no simulation state and never calls the simulation's random generator: none of the functions of
§11 references `Rng_ParkMillerNext` or the logic random object, and their writes go to the window, the timer
globals, the profile, the descriptor and files [known: callee lists of the functions read].

It influences the simulation in four ways, none of which may differ between peers in a way that changes state:

1. **How many ticks run in a frame.** Frame time (1 ms resolution, real clock) times the profile's speed factor.
   This changes *when* ticks run, not *what* a tick computes; in a network match the lockstep layer bounds it
   (`logic-core.md` §3.2).
2. **Floating-point mode.** `Fpu_SetDefaultControlWord` has four callers [known: caller list]: `Initialize`,
   `FrameTick_InGame` before every `NLogic::System::Update`, the game command dispatcher
   `nGame::System::HandleGameCommand` S 007845a0 as its first statement, and `Lobby::CLobby::Update` S 004fb460.
   It does `_controlfp(0x9001f, 0xffff)` then 24-bit precision. Simulation code that uses x87
   arithmetic therefore rounds every operation to single precision. A reimplementation must compute simulation
   floats in single precision with round-to-nearest to reproduce results (`logic-core.md` §3.1, §8).
3. **Which world is built.** The descriptor's fields are simulation inputs; in a network match they come from the
   host's session data, not from the local shell (`network-session.md`).
4. **Single CPU.** The affinity rule of §3.1 keeps all threads on one core; the simulation runs on the main
   thread only (`../subsystems.md` §2.1), so this is a timing property, not a correctness one [inferred].

Everything else here (settings, language, campaign table, log, crash files, benchmark) is presentation or
bookkeeping: it is read or written outside `NLogic::System::Update` and is not part of the checksum
(`logic-core.md` §3.6).

One caution: `MapState`, autosave timing and the benchmark use real time and local files; they must stay out of
any state a remake feeds into the lockstep checksum.

Readers of the real clock through `Timer_GetTotalSeconds` S 0057b8a0 [known: the 38 callers in the decompiled
image]: the two frame ticks (Lua thread wake-up), the autosave, the network layer (hang detection, reconnect,
`Process_MainLoop`, `AdvanceNetTick`, traffic statistics, LAN broadcast), the lobby connection (ping, post
office), UI animation (`nUi::Animation`, `Scroller`, `Graph`, `AlphaFanPicture`, `AnimationScaler`), the main
menu, the in-game screen (`nMenu::Game::Update`, overlay colour fade), the clock symbol, the main menu button
and the in-game avatar renderer. No function of the `NLogic`, `NVillage`, `NSettlers`, `NTransport`,
`NMilitary`, `NNavy` or `NAI` namespaces is among them.

---

## 9. Notes for a Godot reimplementation

**Maps onto engine features**

- Window, message loop, input events, activation, minimise: the engine's main loop and `InputEvent`s. Keep the
  rule that game input is dropped while the window is inactive or minimised, and mute audio then.
- Timer: `Time.get_ticks_usec()`. Convert to the game's frame seconds; the 1 ms quantisation need not be kept
  for presentation. For the tick accumulator keep single-precision arithmetic as specified in `logic-core.md`.
- Splash videos, screens, options panel: scenes and `Control` trees.
- Settings: a `ConfigFile` (or a resource) for the remake's own settings; see "Reading the player's files".
- Log: the engine's logger; crash dumps: the platform's facility. The `Logfile_N.txt` rotation is not needed.
- Single instance, CPU pinning, cursor clip: optional conveniences, not behaviour to reproduce.

**Must be reproduced exactly**

- The run-mode table of §3.7: which map type and which slot set-up each mode writes, including "campaign: eight
  computer slots with tribe −1, then slot 0 human" and "`-map`: slot 0 human with tribe id 0xb0d378a3".
- The descriptor defaults (§2.3): start resources 2, no shuffle, fog option 0, win condition 0.
- The campaign unlock rule, the difficulty rule (highest marked index, 2 when none, fourth level after the last
  map) and the map state machine of §3.8, since they decide what the player may start and when the end dialog
  appears.
- Order at start where it has consequences: file index → properties script → sound → profile (volumes) →
  graphics → menus (`menu.cfg`, language, text tables) → network manager.
- One call of the simulation update per frame, after network pump and script threads, before sound and render
  (§4.2).
- Autosave: role 0 only, real-time interval, strict "greater than", file name `Autosave`.

**Reading the player's files**

- `settings.cfg` and `data.cfg` are plain files in the save stream encoding; the layouts of §3.9 are complete
  enough to import them. Importing `data.cfg` gives the remake the player's campaign progress; import
  `settings.cfg` for scroll options, volumes, autosave interval, difficulty and names, and treat the scene block
  as optional hints (resolution, quality fractions).
- Bound the count `n` in `settings.cfg` and every string length (the original does neither).
- `engine.ini` values are device options of the original renderer; a remake only needs `vsync`.

**What a converter outputs**

| Source | Output |
|---|---|
| `campaigns.xml` | a campaign resource (JSON or a Godot `Resource`): per campaign a name and an ordered list of `{name, desc key, file, kind, prerequisites[]}` |
| `menu.cfg` | language code, the eight player colours as RGB floats, the video voice stream table (JSON); evaluate the Lua file rather than pattern-match it |
| `data.cfg` | per map `{name, completed, state, difficulty}` (JSON) |
| `settings.cfg` | key/value settings (`ConfigFile`) |
| text tables, fonts, videos | `formats-inventory.md` §3.9 and its conversion table |

The remake's own language choice should be a setting of the remake: the original fixes it in `menu.cfg`.

---

## 10. Open questions

| # | Question | Settled by |
|---|---|---|
| 1 | Original meaning of the profile fields `+0x32`, `+0x38`, `+0x78`: they are stored and loaded but nothing else uses them (§2.6), so a reimplementation only has to keep them through a read and write | a search of the whole image for instructions that address these offsets through the profile pointer (to confirm that there is no reader outside the decompiled functions); otherwise not recoverable from this binary |
| 2 | Who writes the offline player name `+0x40` | static: writers of `profile + 0x40` (free-game panel `BindWidgets` S 005e8820 is a candidate) |
| 3 | Scene settings (§2.7): what the scene's render flag 0x80 (fed by `+0x24`) draws and who calls its setter; what reads the scene's copy of the level `+0x3c`; the meaning of `+0x48`; whether `+0x1c` set means windowed | static: readers of bit 0x80 of the scene's render-flag word (`S2CG::Scene::UpdateDetailFlagsAndTime` S 0067f6b0 also sets it) and of the scene's level field; in-game vtable S 007f9bfc slot +0x68; the present-parameter code that reads byte +8 of the device's display-mode block |
| 4 | What sets byte +0x20 of the device's display-mode block (it suppresses the profile write at shutdown and the display-mode apply) | static: writers of the block returned by `GraphicDevice_GetField_A8` |
| 5 | Whether the campaign tile text is the map name itself or its localisation (the campaign name `Main +0x20c` is the `campaignName` attribute, §3.8) | static: the text setter called in `RefreshCampaignTiles` S 005df440 and its flag |
| 6 | Reader of the video voice stream map (`nMenu::System +0xa8`) | static: `nUi::Video::Create` and the cinematic dialog |
| 7 | Which program reads `crashmsg.ini`, and whether it is part of the retail flow. No executable or DLL in the examined install's `bin\` nor `Uninstall.exe` holds the name as a plain ASCII or UTF-16 string [known: string search]; the protected `SADK.exe` and packed installers cannot be searched that way | an untouched retail install or its launcher |
| 8 | Whether anything can make the `Exit` screen current, and whether the campaign start index `+0x60` has a writer outside the constructor. Through the typed fields there is none: `System +0x44` is touched by constructor, `Initialize`, `Shutdown` only, and `+0x60` by the constructor (−1) and the two reads in `Initialize` [known: field uses in the decompiled image] | static: raw-offset writes to `System +0x0c` with the `+0x44` pointer and to `g_App + 0x60` in the disassembly |
| 9 | Answered: with `-nolobby` a press of the lobby button sets the request byte `nMenu::System +0xb4` and calls `PlayMusic(0)`, nothing else. The byte's only reader runs under `lobby != NULL` and the lobby pointer is created only without `-nolobby`; the main menu neither hides nor disables the button | static: S 005e27c0, S 005d98d0, S 005d98e0, S 004018e0, S 004075d0 |
| 10 | Answered (§3.4): `Timer_GetTotalSeconds` has a step of `2^(floor(log2 seconds) − 23)` s of counter time, above one 60 Hz frame from about 3 days. What the readers of §8 look like at such a step (UI animations, hang detection) is an observation | static: S 0057b8a0, S 0057b790, S 0057b9b0; observation after long uptime |
| 11 | Retail values of `engine.ini` (the examined install is a working copy) | an untouched install |
| 12 | Whether the key-to-button assignment of the main menu (keys 1 to 4) matches the layout names | static: `nMenu::Main::OnInitLoadXml` S 005e0bb0 against `menumain.xml` |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00407cf0 | `WinMain` | process entry, single instance, window, loop, exception scope |
| 00407c90 / 00407b70 | `App_RegisterWindowClass` / `App_CreateMainWindow` | class `S2Class`, window style |
| 00407c10 | `App_WndProc` | window procedure |
| 00401f30 | `CApplicationEx::HandleWindowMessage` | activation, size, power, input translation |
| 004039e0 | `CApplicationEx::ctor` | field defaults |
| 00403ac0 | `CApplicationEx::ParseCommandLine` | switches |
| 006e5540 / 006e5300 / 006e5180 / 006e5210 | `ai::core::CmdLineArgs::ctor` / `Tokenize` / `FindArg` / `GetArg` | tokens and matching |
| 004075d0 | `CApplicationEx::Initialize` | start-up order |
| 00405590 | `CApplicationEx::InitEngineLayer` | device, display mode, render singletons |
| 004da2a0 | `S2CE::CGraphicDevice::Init` | `engine.ini`, `engine.xml`, hardware measurement |
| 00401bd0 | `CApplicationEx::FrameTick` | per-frame dispatch |
| 004018e0 | `CApplicationEx::FrameTick_InGame` | frame of menu and match |
| 00401780 | `CApplicationEx::FrameTick_Menu` | frame of the 3D lobby |
| 00401260 | `App_RenderWorldFrame` | begin, menu render, end |
| 005d9800 / 005efdd0 | `nMenu::System::Render` / `nMenu::Game::Draw` | UI root then requester; world then HUD |
| 00780d20 | `nGame::System::Update` | per-frame in-game update: start broadcast, autosave, cursor, camera, music |
| 005273d0 | `NLogic::System::PostLoad` | ends a world load; resets the frame timer |
| 007845a0 | `nGame::System::HandleGameCommand` | sets the FPU control word, then dispatches a game command |
| 004669e0 / 00466c40 / 00466ad0 | `LobbyComm::Logger::ctor` / `Open` / `GetLogFilePath` | lobby log `LobbyComm.log` |
| 00401310 | `CApplicationEx::UpdateCursorClip` | cursor confinement |
| 00401cb0 | `CApplicationEx::Shutdown` | teardown order |
| 00401350 / 00401420 | `App_CmdLine_StartNewMap` / `App_CmdLine_StartGameFile` | `-map`, `-start` |
| 0057b790 / 0057b990 / 0057b810 | `Timer_Init` / `Timer_Reset` / `Timer_UpdateFrame` | frame timer |
| 0057b850 / 0057b8a0 / 0057b8e0 | `Timer_GetFrameDeltaSeconds` / `GetTotalSeconds` / `GetElapsedSecondsSinceStart` | timer readers |
| 0057b9b0 | `Fpu_SetDefaultControlWord` | x87 control word |
| 0057bc90 | `App_SetGameRootDir` | game root |
| 0057bfb0 / 0057bdf0 / 00578e20 | `Fs_CreateUserDataDirectories` / `Fs_GetDumpsDirPath` / `Fs_GetUsersDirPath` | user folders |
| 005795b0 / 00578fe0 / 005795d0 | `UserProfile::Initialize` / `UserProfile_LoadFromDisk` / `UserProfile_Shutdown` | profile life cycle |
| 00579c00 | `UserProfile_ResetSettingsDefaults` | defaults |
| 00579640 / 00579960 | `UserProfile::StoreSettings` / `LoadSettings` | `settings.cfg` |
| 005792c0 / 00579430 | `UserProfile_SaveSettings` / `UserProfile_SaveMapStates` | file writers |
| 005798a0 | `UserProfile::ApplyDetailPresetForScore` | lobby preset at first run |
| 0057a0b0 / 0057b500 | `UserMapStates::Store` / `Load` | `data.cfg` |
| 00579e80 / 00579ed0 / 0057a490 | `nUser::MapState::Store` / `Load` / `ctor` | one record |
| 0057b270 / 0057b330 / 0057a510 / 0057b450 | `MarkCurrentMapStarted` / `RecordMapCompleted` / `IsCurrentMapCompletionPending` / set state 1 | map state machine |
| 00695b40 / 00695860 / 00695fc0 | `S2CG::Settings::ctor` / `ApplyQualityPreset` / `AutoDetectQualityPreset` | scene presets |
| 006960a0 / 00696270 | `S2CG::Settings::Load` / `Store` | scene block of `settings.cfg` |
| 005e55b0 / 005e5490 | `nMenu::OptionsPanel::LoadOptionValue` / `CloseAndSaveSettings` | option numbering, settings write |
| 00465dd0 | `ai::lobby::LobbyProfile::Init` | `LobbySettings.ini`, per-user lobby file |
| 005dda30 | `nMenu::System::Initialize` | Lua libraries, `menu.cfg`, language, screens |
| 005da500 | `nMenu::System::Update` | menu frame, pending map start |
| 005d9f10 / 005d9ef0 | `nMenu::System::ActivateGameScreen` / `AppState_ActivateMainScreen` | screen switch |
| 005d9ee0 / 005d98d0 / 005d98e0 | `RequestQuit` / `RequestEnterLobby` / `ConsumeEnterLobbyRequest` | quit and lobby flags |
| 005da2f0 | `nMenu::System::Shutdown` | menu teardown |
| 0060bbd0 / 0060c5a0 | `nMenu::Splash::OnShow` / `Update` | intro videos |
| 005e27c0 / 005e3810 | `nMenu::Main::HandleButtonClicks` / `Update` | main menu |
| 005df2c0 | `nMenu::Main::StartCampaignMap` | campaign start |
| 005df440 / 005decf0 | `nMenu::Main::RefreshCampaignTiles` / `nMenu::Map::ArePrerequisitesCompleted` | unlock rule |
| 005ded70 | `nMenu::Main::OnDifficultyButtonClicked` | difficulty choice |
| 005e4de0 / 005e52a0 / 005e45e0 / 005e3370 | `Campaigns::ctor` / `OnXmlLoaded` / `CampaignData::LoadFromXml` / `Map::LoadFromXml` | `campaigns.xml` |
| 005e7350 / 005e8410 | `nMenu::FreeGamePanel::StartFreeGame` / `SetMap` | free game |
| 00615370 | `nMenu::SelectMapDialog::RefreshMapList` | map list |
| 005eb030 | `nMenu::Game::OnLeave` | leaving a match |
| 005a9bb0 / 005a9c10 / 005a9c50 | `GameLoadDescriptor::Reset` / `SetMapName` / `SetMapNameAndType` | descriptor |
| 005ac880 | `GameFile_RefreshAllMapInfoCaches` | cache refresh at start |
| 0078b040 / 0078af30 | `nGame::Autosave::Update` / `nGame_Autosave_WriteSave` | autosave |
| 005dd780 / 005dd6c0 | `LuaMenu_SetLanguage` / `LuaMenu_SetVideoVoiceStream` | `menu.cfg` bindings |
| 00495010 / 004955a0 / 00496e60 | `Localization::SetLanguage` / `BuildLanguagePath` / `ReloadIfLanguageChanged` | language |
| 006e5950 / 006e5620 / 006e5920 | `Log_Printf` / `LogFile_ctor` / `Log_SetDirectory` | log file |
| 006e63d0 / 006e6300 / 006e6170 / 006e6290 / 006e6030 | `Crash_HandleException` / `Crash_WriteMiniDump` / `Crash_OpenLogAndInitSymbols` / `Crash_WriteReportBody` / `Crash_BuildOutputPath` | crash report |
| 00680b70 | `S2CG::Scene::HWLabLogFrameRate` | benchmark mode |
| 0060b260 / 0060b570 | `nMenu::Exit::OnShow` / `Update` | unused exit screen |
