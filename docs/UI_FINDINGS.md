# SAdK UI / Screen System — Findings & Early-Spawn Feasibility

**Question:** Can the in-world **server browser / host-game window** be spawned EARLY (from
character-select / "Betrete Welt…") by editing decrypted UI/screen XML, bypassing full world entry?

**Verdict: NO.** Screen flow is a hard-coded C++ state machine; the UI XML is layout-only and
carries no flow/visibility-by-state logic. The server browser lives inside the in-world HUD
(`worldScreen2`) and additionally requires a live **VillageServerConnection**, both of which only
exist once the client reaches state 9 (VillageEntered). A file edit cannot create that state.
Details, evidence, and the one *partial* edit that's possible are below.

---

## 1. AdKEd decrypt workflow (CONFIRMED working this session)

- Tool: `AdKEd.exe` — `AdKEd v1.11 BETA (c) 2008 Trass3r`
  (a third-party SAdK XML (de)coder, not the game's own; works perfectly).
- It is a **two-way toggle**: run it on an *encrypted* file → decrypts in place; run it on a
  *decrypted* file → re-encrypts in place. The game ships files encrypted; re-run to restore.
- Encrypted-file signature: bytes `12 18 09 06 73 61 64 6B …` (offset 4 = ASCII `sadk` magic).
  Decrypted-file signature: `EF BB BF` (UTF-8 BOM) or `3C` (`<`) + `<?xml …`.
- `BatchConv.bat` = `FOR %%i IN (BatchConversion\*.*) DO AdKEd %%i`. **Caveat:** invoking
  `cmd /c BatchConv.bat` failed for me (bare `AdKEd` not found on cmd's PATH). Reliable method:
  call AdKEd with a full path in a loop:
  ```powershell
  $adk = ".\AdKEd.exe"
  foreach ($f in Get-ChildItem ".\BatchConversion" -File) { & $adk $f.FullName }
  ```
- **Always work on copies.** Procedure used: copy game originals → `BatchConversion\`, decrypt,
  move results to `ui_scratch\fresh\`. Game originals were never decrypted in place (verified:
  `lobbyWorldScreen.xml` original still starts `12 18 09 06 73 61 64 6B`).
- **NB on the old `ui_scratch\decrypted\` copies:** their *tails* are garbled (a bad prior run).
  The fresh `ui_scratch\fresh\` copies decrypted this session are clean and complete — use those.
- To test an edit in-game: edit the decrypted copy → run AdKEd on it to re-encrypt → drop it back
  over the game original (back up the original first).

---

## 2. UI / screen file map

### Lobby UI layouts — `data\lobby\ui\layout\*.xml` (32 files, all decrypted → `ui_scratch\fresh\`)

Each XML defines ONE screen/dialog as a tree of widgets (control type, texture mapping,
deployment/position, default `visible`/`enabled`, hotkeys, `!TOKEN` localization keys). The root
element name == the C++ class that loads it (see §3).

| File | Role |
|---|---|
| `lobbyAvatarScreen.xml` | **Character-select / customize-avatar screen.** Key button `StartGameButton` text `!ENTER_VILLAGE_BUTTON`, hotkey 13 (Enter) = "Betrete Welt". This is where the client parks. |
| `lobbyAccountScreen.xml` | **Empty stub** (`<AccountScreen></AccountScreen>`) — container only. |
| `lobbySelectAvatarDialog.xml` | Pick which saved avatar. |
| `lobbyCustomizeAvatarDialog.xml` / `lobbySelectVillageServerDialog.xml` | Avatar customizer / village-server picker ("Suche Server"). |
| `lobbyWorldScreen.xml` | **The in-world 3D HUD** (`worldScreen2`). Owns the chat box, minimap, VillageInfoBar, and the **`MainMenu`** dropdown that contains HOST_GAME / JOIN_GAME (see §4). Only built after world entry. |
| `lobbyBrowseGameDialog.xml` | **The server browser** (game list + Join/Create/Close buttons). |
| `lobbySetupGameDialog.xml` | **Host-game window** (player slots, tribe/type combos, map pick). |
| `lobbySelectMapDialog.xml` | Map picker (used by Host). |
| `lobbyLoginDialog`, `lobbyCreateAccountDialog`, `lobbyGetPasswordDialog`, `lobbySetPasswordDialog`, `lobbyEnterPasswordDialog`, `lobbyConfirmTaylorDialog` | Login / account flow. |
| `lobbyFriendIgnoreListDialog`, `lobbyMailboxDialog`, `lobbyMailDialog`, `lobbyShopDialog`, `lobbyHallOfFameDialog`, `lobbyReportIssueDialog`, `lobbyMotDDialog`, `lobbyMessageBoxDialog`, `lobbyDummyDialog`, `lobbySelectionInfoDialog`, `lobbySetStackDialog` | Social / shop / misc dialogs. |
| `lobbyMiniGame*Dialog*.xml` (Dice/Poker/PawnChess/Observer/MatchMaking/Manual) | Tavern minigames. |

### Lobby world/scene composition — `data\lobby\scene\*.xml` (decrypted → `ui_scratch\fresh\`)
- `world1.xml` → world_scenes list: `scene1`, `scene_taverne02/03`, `scene_townhall`, `scene_ad`,
  **`scene_customizeavatar`**, `scene_skydome`. This is the 3D lobby-world scene graph.
- `scene_customizeavatar.xml` → `obj type="CharSelect"` + `bg_bavaria/bg_scot/bg_egypt/bg_creation`
  — the 3D character-select backdrop (what renders at "entering world").
- `lobbyobj.xml` (`data\lobby\config\`) → a **3D-object catalog** (meshes, avatars, scenery), NOT a
  screen registry. It does define the in-world **building→scene transition** mechanic: townhall /
  taverne / gasthaus each have `scene_trigger`, `transition_area`, `scene="N"` (walking into a
  building swaps the rendered 3D scene). That is the only "data-driven state switch" in the lobby —
  and it switches *3D scenes*, never UI screens.

### In-game (single-player RTS) UI — `data\game\ui\layout\*.xml`
Separate subsystem (`menumain`, `menuingame`, `menunetinfo`, `templates.xml`, etc.). Not the lobby;
irrelevant to the online server browser.

### Settings — `data\lobby\config\LobbySettings.ini`
Plain text: `[LobbyServer] Host/Port`, HallOfFame URLs. No screen-flow data.

---

## 3. How the screen / visibility system actually works

**It is code-driven, not data-driven.** Confirmed three independent ways:

1. **Each screen XML's root element maps 1:1 to a C++ class** that loads it by name and then
   name-binds each child widget. In the Ghidra decomp of `SADK.exe`:
   - `LobbyMenu::AvatarScreen::vftable` is assigned, then the ctor looks up
     `"AvatarScreenTitleLabelBackground"` / `"AvatarScreenCustomizeTools"` (the exact XML node
     names) — `SADK.exe.c` ~line 39278/39519/39558.
   - `LobbyMenu::BrowseGameDialog::vftable` — ~line 58860.
   - The `worldScreen2` ctor binds `"EmoteButton"`, `"MainMenu"`, `"Friends"`, … by name
     (`SADK.exe.c` ~line 38448-38497).
   So the XML supplies *layout only*; **when** a screen is constructed/shown/hidden is entirely C++.

2. **There is no screen-flow / state-machine file anywhere in `data\`.** No XML lists multiple
   screen names as a flow; no `nextScreen`/`state`/`onClick→openScreen` attributes exist in any
   dialog. The `visible`/`enabled` attributes are static initial values for individual widgets,
   not screen-level gating.

3. **The lobby is a numeric state machine inside `LobbyManager` (`CLobby.cpp`/`LobbyClient.cpp`),**
   reverse-engineered in `SOURCEMAP.md`:
   - state 1→7 = login progression (→ LoggedIn / lobby reached, character-select shown)
   - **state 8 = EnteringVillage** — set only after `CreateVillageServerConnection` (`0x463750`)
     opens a *new* TinCat socket to the selected village server (orphan block @`0x47043c`)
   - **state 9 = VillageEntered** — set only when that village server sends village-protocol
     message **1000** → `VillageServerConnection::HandleEnterWorld` (`0x46f470`) parses the
     property bag (`Worldname`, `ServerPerm`, chat channels) → **client loads the 3D world**
   - state 11 = VillageLeft
   The "Suche Server" button itself ungreys only when `IsListReady && HasServerSelected`.

---

## 4. The server-browser / host-game definitions (file + excerpt)

The Host/Join *entry points* are children of the in-world HUD `worldScreen2`, i.e.
`lobbyWorldScreen.xml`:

```xml
<MainMenu controltype="DropDownMenu" template="combobox" size="6"
    string0="!LOBBY_MAIN_MENU_HOST_GAME"   <!-- opens SetupGameDialog -->
    string1="!LOBBY_MAIN_MENU_JOIN_GAME"   <!-- opens BrowseGameDialog -->
    string2="!LOBBY_MAIN_MENU_SETTINGS"
    string3="!LOBBY_MAIN_MENU_OPENSUPPORTWEBSITE"
    string4="!LOBBY_MAIN_MENU_REPORTISSUE"
    string5="!LOBBY_MAIN_MENU_LEAVE" dropdownoffset="32">
  <deployment alignx="right" aligny="top" offset="-560 0" size="124 32" />
  <button><text content="!LOBBY_MAIN_MENU" /></button>
</MainMenu>
```
(Same file also has `VillageInfoBar` → `ServerName` + `SelectServerMenu` server switcher.)

The server browser window — `lobbyBrowseGameDialog.xml` (`<BrowseGameDialog>`): a `GameList`
listbox (columns Protected / Ranked / GameName / PlayerCount / MapName / GameType) plus:
```xml
<CloseButton  ... text="!LOBBY_BROWSEGAME_CLOSE_BUTTON"  hotkey="27" />
<JoinButton   ... text="!LOBBY_BROWSEGAME_JOIN_BUTTON"   hotkey="13" />
<CreateButton ... text="!LOBBY_BROWSEGAME_CREATE_BUTTON" hotkey="c"  />
```

The host-game window — `lobbySetupGameDialog.xml` (`<SetupGameDialog>`): player slots
(`PlayerType` Open/Closed/CPU, `PlayerTribe` Bavarian/Egyptian/Scot), matchmaking combos, map pick.
Backing class string in the binary: `LobbyMenu::SetupGameDialog::SetupSession`.

None of these three files contain any state, trigger, owner, or auto-show attribute. They are
inert layout that the C++ instantiates on demand.

---

## 5. Feasibility verdict + the only edit that's actually possible

**Early-spawn by file edit is NOT possible.** Reasons:

1. The Host/Join menu items are **children of `worldScreen2`**, which the engine only constructs at
   state 9 (VillageEntered). The character-select screen is a *different* C++ object
   (`AvatarScreen`); editing its XML cannot instantiate `worldScreen2` or its `MainMenu`.
2. Even if you could force the dialogs to render, `SetupGameDialog`/`BrowseGameDialog` operate on a
   live **`VillageServerConnection`** (host/join sessions are created against the village server —
   `LobbyMenu::SetupGameDialog::SetupSession`, `CreateVillageServerConnection`). With no village
   connection (which is exactly the parked state), the list is empty and Join/Create are no-ops.
3. The transition AvatarScreen → worldScreen is driven purely by `LobbyManager::SetState(…)` in
   compiled code, reacting to the network handshake (msg 1000 / `HandleEnterWorld`). There is no
   data hook to advance it. (As archived `SESSION_STATUS.md` line 559-561 already concluded: the server
   browser / host / join is *downstream* of world entry.)

**The actual gate is the protocol, not the UI.** To reach the server browser the stub lobby must
drive the client to state 9: advertise a `ServerType=4` village entry (msg 170, "adk" byte format),
accept the 3rd TinCat connection to that entry's Ip/Port, and on the village handshake send
village-message **1000** with the property bag (`Worldname`, `ServerPerm`, chat channels) →
`HandleEnterWorld` → `SetState(9)` → 3D world + working `MainMenu` Host/Join. That is the
documented in `IN_WORLD_PROTOCOL.md` and is the correct path — not a UI edit.

### The one UI edit that *is* possible (and its limit)
Because `lobbyAvatarScreen.xml` is just layout, you *can* add a real, clickable widget to the
character-select screen — e.g. a button bound to hotkey `c` / a `MainMenu`-style dropdown copied
from `lobbyWorldScreen.xml`. **But** a widget only does something if the C++ class that owns the
screen (`LobbyMenu::AvatarScreen`) has a handler that recognises that widget's name and calls
"open BrowseGameDialog". `AvatarScreen` has no such handler (its known children are only
`StartGameButton`, `NameEdit`, `BackButton`, `ResetLoginPosition`). An unrecognised widget is drawn
but **inert** — clicking it calls nothing. So you can add the *button*, but not the *behaviour*;
the open-dialog action lives in code reachable only from the world HUD. This is the empirical
"probably not" the project owner expected, now confirmed.

If you wanted to force it anyway, it would require a **binary patch** (e.g. make `AvatarScreen`'s
handler open `BrowseGameDialog`, and stub out the `VillageServerConnection` requirement) — i.e.
code, not a data-file edit — and you'd still face an empty/non-functional browser without a village
connection. Not worth it: completing the state-9 handshake in the stub is both easier and correct.

---

## Files decrypted this session (all copies; game originals untouched/still encrypted)
`ui_scratch\fresh\` — all 32 `lobby*.xml` layouts + `world1.xml`, `world2.xml`,
`scene1.xml`, `scene1_settings.xml`, `scene2.xml`, `scene2_settings.xml`, `scene_ad.xml`,
`scene_ambient_sounds.xml`, `scene_customizeavatar.xml`, `scene_gasthaus2.xml`,
`scene_skydome.xml`, `scene_taverne02.xml`, `scene_taverne03.xml`, `scene_townhall.xml`,
`lobbyobj.xml`.
