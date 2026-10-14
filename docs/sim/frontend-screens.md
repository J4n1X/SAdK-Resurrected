# Front end: main menu, free-game set-up, campaign, loading and the other out-of-match screens

The screens of `sadk_noav.exe` that are shown before and after a match outside the online lobby: the logo
sequence, the main menu with its three panels, the campaign mission list, the free-game panel and its map
chooser, the load / save panel, the options panel, the credits, the loading panel, the end-of-game dialogs, the
network info dialog, the briefing book and the info popup. For each: what it shows, what each control does, what
it writes and where.

- Binary: `sadk_noav.exe`, image base `0x400000`. `S 00xxxxxx` is a static address in it.
- Tags: **[known]** = read directly at the address given or in the named data file and key; **[inferred]** = one
  step of reasoning from what is visible; **[TODO]** = not established. Nothing here was observed in the running
  game.
- Layout files are in `[data]\ui\layout\` (`[data]` = `data\game` of the install). Their element and attribute
  grammar is in [`ingame-ui.md`](ingame-ui.md) §3.1. A widget "name" below is the element name in that file.
- Text keys starting with `!` are looked up in the text tables (`formats-inventory.md` §3.9).

Related specifications, not repeated here:

| Topic | Where |
|---|---|
| Process start, frame loop, run modes, `GameLoadDescriptor`, campaign table, user profile files, quality presets | [`app-shell.md`](app-shell.md) §2.3 to §2.7, §3.7 to §3.10 |
| Widget kinds, layout XML, message boxes, requester, in-game menu, statistics panel, screen flow in a match | [`ingame-ui.md`](ingame-ui.md) §2.3, §2.7, §3.1, §3.8, §3.9 |
| Save container, map types and folders, world build, map-info cache | [`save-format.md`](save-format.md) §2.6, §3.7, §3.8, §3.11 |
| Match options and what they do to players, victory, map states on a win | [`players-victory.md`](players-victory.md) §2.4, §3.4, §3.7 |
| Music table, volume categories, voice-over | [`audio.md`](audio.md) |
| Cinematic screen, cutscene camera | [`camera-input-cutscenes.md`](camera-input-cutscenes.md) §2.6, §3.8 |
| `menu.*` and `ui.*` script bindings (book, cinematic, info pages) | [`lua-runtime.md`](lua-runtime.md) §3.7, §6.1 |
| Offline and network roles, session slots, `EventGameInformation` | [`network-session.md`](network-session.md), [`../NCOMM_GAME_PROTOCOL.md`](../NCOMM_GAME_PROTOCOL.md) |
| Lobby screens (3D village, game set-up dialog of a network match) | [`../LOBBY_SCREEN_VTABLES.md`](../LOBBY_SCREEN_VTABLES.md), [`../MATCH_START.md`](../MATCH_START.md) |

---

## 1. Purpose and scope

In scope, all classes of namespace `nMenu`:

| Screen | Class | Layout file | Kind |
|---|---|---|---|
| Logo sequence | `Splash` | `menusplash_dev.xml` | top-level screen |
| Main menu (three panels, campaign list, credits) | `Main` | `menumain.xml` | top-level screen |
| Free-game set-up | `FreeGamePanel` | `menufreegame.xml` | panel on `Main` |
| Map chooser | `SelectMapDialog` | `menuselectmapdialog.xml` | dialog inside the free-game panel |
| Load / save | `LoadSavePanel` | `menuLoadSave.xml` | panel on `Main` (load) or on `Game` (load, save) |
| Options | `OptionsPanel` | `menuOptions.xml` | panel on `Main`, on `Game`, on the lobby world screen |
| Loading | `LoadingPanel` | `menuLoading.xml` | panel on `Game` while the world is built |
| End of game | `Victory`, `Report`, `Defeat` (base `GameEnded`) | `menuGameEnd.xml` | dialog slots 3, 0, 5 |
| Network info | `NetInfo` | `menunetinfo.xml` | dialog slot 7 |
| Briefing book | `Book` | none (built in code) | dialog slot 2 |
| Help popup | `Info` | none | popup, script pages in `scripts\info\` |

The file names are the literals in the constructors [known] S 0060ba30, S 005e4ea0, S 005e6e30, S 00614410,
S 0060ce40, S 005e62f0, S 0062ae40, S 0061ffe0, S 005fd080. The install also has `menusplash.xml` (an empty
skeleton) and `menucampaign.xml` (one element); the image reads neither [known: a string search of the image
finds `menusplash_dev.xml` and no `menusplash.xml` or `menucampaign`].

Where each panel is created [known: the constructors' callers]: `LoadSavePanel` by
`Main::HandleButtonClicks` S 005e27c0 (mode 0) and `nMenu::Game::OnMenuComboSelected` S 005eb310;
`OptionsPanel` by `Main::ShowOptionsPanel` S 005de830, `nMenu::Game::SetOptionsPanelVisible` S 005eac90 and
`LobbyMenu::WorldScreen::HandleButtonClicks` S 00437760; `FreeGamePanel` only by `Main::ShowFreeGamePanel`
S 005de8e0; `SelectMapDialog` only by `FreeGamePanel::BindWidgets` S 005e8820; `LoadingPanel` only by
`nMenu::Game::OnEnter` S 005eed00. The dialog slot numbers are those of `ingame-ui.md` §2.7.

Out of scope: the `Exit` screen and the run-mode table (`app-shell.md` §3.7), the requester and `MsgBox`
(`ingame-ui.md` §3.8.7, §3.8.8), the cinematic screen (`camera-input-cutscenes.md` §3.8), the statistics panel
(`ingame-ui.md` §3.8.1), every lobby screen.

---

## 2. Data model

### 2.1 `nMenu::Main` (0x9a8 bytes) [known: mapped struct, cross-checked on S 005e4ea0, S 005e0bb0, S 005e3810]

| Offset | Type | Field | Meaning | Constructor value |
|---|---|---|---|---|
| +0x1b8 | `System*` | `menuSystem` | owner | argument |
| +0x1c0 | 3 × 0x10 | `panels[3]` | per panel: the panel widget and a `std::map<int, {widget, name}>` of its buttons, keyed by the button key of §3.2 | empty |
| +0x1f0 | i32 | `activePanel` | 0 main, 1 single player, 2 campaign, 3 none | 3 |
| +0x1f4 | `Campaigns*` | `campaigns` | the parsed `campaigns.xml` (`app-shell.md` §2.5) | new object |
| +0x1f8 | vector, 0x18 per entry | `campaignTiles` | per mission tile: button (+0), `Subline` label (+4), four `PicPlayed<n>` pictures (+8..+0x14) | empty |
| +0x208 | i32 | `hoveredTileIndex` | tile under the mouse, −1 none | −1 |
| +0x20c | std::string | `campaignName` | root attribute `campaignName` | empty |
| +0x228 | bool | activate-main latch: when set, the next update re-activates the main screen and clears it [known] S 005e3810. No instruction of the image sets it: the byte stores (opcodes C6, 88) with displacement 0x228, or 0x208 / 0x204 / 0x200 from the three faces, are the constructor's clear, the update's clear and stores of other classes (`NComm::EventGameInformation`, `S2CG::FarmBuilding`, `LobbyComm::MiniGameProxy`, `nUi::TextScroller`) [known: byte search of the image]; [inferred] the branch never runs (a store through a separately computed pointer is not excluded) | 0 |
| +0x22c | `OptionsPanel*` | created on first use | NULL |
| +0x230 | `FreeGamePanel*` | created on first use | NULL |
| +0x234 | `LoadSavePanel*` | load dialog, created on first use | NULL |
| +0x238 | f32 | `zoomInTime` | root attribute; non-zero starts a scale-in animation of the banner picture | 0.0 |
| +0x240 | `nUi::TextScroller` | credits scroller, element `creditsText` | |
| +0x468 | label | `CampaignDesc` | mission description box | NULL |
| +0x46c | widget | `DiffContainer` | | NULL |
| +0x470 | 4 × ptr | `DiffButton0` .. `DiffButton3` | | NULL |
| +0x480 | label | `legalLines` | | NULL |
| +0x484 | f32 | time (`Timer_GetTotalSeconds`) at which the layout was loaded | |
| +0x488, +0x48c | label | `ButtonDesc`, `ButtonHeadline` | hover help | NULL |
| +0x490 | `nUi::Picture` | title logo, created in code | |
| +0x718 | `nUi::Picture` | element `Banner` | |
| +0x9a0 | bool | when set, the update requests the quit [known] S 005e3810. Cleared after every activation of the screen (the show thunk S 005df2a0) [known]; not written by the constructor. No instruction of the image sets it: the only instructions with displacement 0x9a0, or 0x980 / 0x97c / 0x978 from the three faces, that touch this object are that clear (S 005df2ab) and the update's test (S 005e3838); the other two hits belong to `nMenu::MiniMap::LoadFromXml` S 005f10a0 [known: byte search of the image]; [inferred] the menu never quits through this flag | |

### 2.2 `nMenu::FreeGamePanel` (0x3d8 bytes) [known: mapped struct, S 005e6e30, S 005e8820]

| Offset | Field | Widget name, kind |
|---|---|---|
| +0x288 | XML handler (`menufreegame.xml`) | |
| +0x2a8 | `mapPreview` | `MapPreview`, picture |
| +0x2ac | `selectMapButton` | `SelectMapButton`, button |
| +0x2b0, +0x2b4, +0x2b8 | `mapNameText`, `mapSizeText`, `maxPlayerText` | `MapName`, `MapSize`, `MaxPlayer`, labels |
| +0x2bc, +0x2c0, +0x2c4 | `startResourcesCombo`, `winConditionCombo`, `fogOfWarCombo` | `StartResources`, `WinCondition`, `FogOfWar`, combo boxes |
| +0x2c8, +0x2cc | `leaveButton`, `readyButton` | `LeaveButton`, `ReadyButton` |
| +0x2d0 | `playerRows[6]`, 0x24 bytes each | containers (pictures, kind 0xe) `PlayerOne` .. `PlayerSix` (name table S 0087f280, six strings of 0x1c bytes; the six literals `PlayerSix`, `PlayerFive`, `PlayerFour`, `PlayerThree`, `PlayerTwo`, `PlayerOne` are at S 007d96e4 .. S 007d9720 [known]; their order in the table [inferred] from the layout file) |
| +0x3a8 | bool `closeRequested` | set by Leave; no reader in the image [inferred: the only uses are the constructor and the click handler] |
| +0x3a9 | bool `startRequested` | set by Start; polled by `Main::Update` |
| +0x3ac | `SelectMapDialog*` | |
| +0x3b0 | `GameLoadDescriptor*` | the `Game` screen's descriptor (`app-shell.md` §2.3) |
| +0x3b4 | `MapInfo*` | descriptor + 0x2c: the per-slot set-up |
| +0x3b8 | std::string | name of the map whose preview texture is loaded (empty at construction) |

`FreeGamePlayerRow` (0x24 bytes) [known] S 005e6f50:

| Offset | Field | Child name, kind | State it carries |
|---|---|---|---|
| +0x00 | `typeCombo` | `PlayerType`, combo box | index 0 closed, 1..3 computer level 0..2 (row 0: one entry, the player name) |
| +0x04 | `tribeCombo` | `PlayerTribe`, combo box | index 0..2 → tribe name `Bavarian`, `Scots`, `Egyptian` (table S 0087f328) |
| +0x08 | `teamButton` | `PlayerTeam`, overlay button with children `team0` .. `team6` | team in `MapInfo` |
| +0x0c | `colorButton` | `PlayerColor`, overlay button with child `PlayerColorBlob` | colour index in `MapInfo` |
| +0x10 | `hqButton` | `PlayerHQ`, overlay button | **the chosen start position is the button's user data (+0x28)**, not a `MapInfo` field |
| +0x14 | `avatar` | `avatar` | portrait name |
| +0x18 | container | | |
| +0x1c | owner panel | | |
| +0x20 | i32 `slotIndex` | | row number 0..5 |

A child whose widget kind differs from the expected one is stored as NULL [known] S 005e6f50: combo boxes are
kind 0x13, the three overlay buttons kind 0xd; `avatar` is stored without a kind test. The other widgets of the
panel are looked up below `GameSettingsPanel` (a picture, kind 0xe) with kinds 0xe (`MapPreview`), 0xc
(`SelectMapButton`), 9 (the three labels) and 0x13 (the three option combos); `LeaveButton` and `ReadyButton`
(kind 0xc) are looked up from the panel root [known] S 005e8820.

### 2.3 `nMenu::SelectMapDialog` (0x2d8 bytes) and `MapListEntry` [known] S 00614410, S 00615430, S 00613000

| Offset | Field |
|---|---|
| +0x288 | XML handler (`menuselectmapdialog.xml`) |
| +0x2a8 | observer list "map chosen" (argument: the map name string) |
| +0x2b4 | `MapList` (list box, kind 0x16) |
| +0x2b8 | vector of std::string: the map **file names** in row order |
| +0x2c8, +0x2cc | `OkayButton`, `AbortButton` |
| +0x2d0 | i32 selected row, −1 none |

`ai::ui::MapListEntry` (0x3c bytes), used only while the list is built: file name (std::string, +0x00), display
text (std::string, +0x1c), bool `isMp` (+0x38).

### 2.4 `nMenu::LoadSavePanel` (0x2f0 bytes) [known: mapped struct, S 0060ce40, S 0060d7b0]

| Offset | Field | Widget name, kind |
|---|---|---|
| +0x288 | XML handler (`menuLoadSave.xml`) | |
| +0x2a8 | message box listener face | |
| +0x2b0, +0x2b4 | `btLoad`, `btDelete` | buttons |
| +0x2b8 | `listbox` | list box (kind 0x16) |
| +0x2bc | `editBox` | `edit`, edit box (kind 7) |
| +0x2c0 | `headline` | label |
| +0x2c4 | i32 `mode` | 0 load, 1 save (constructor argument) |
| +0x2c8 | std::string | name chosen for loading; non-empty is handed over by the next update |
| +0x2e4 | `MessageBox2*` | own message box (0x1a58 bytes, element `messagebox`); its widget user data (+0x28, 64 bit) is the pending action: 0 overwrite, 1 delete |
| +0x2e8 | bool `listDirty` | set after a delete; the next update rebuilds the list |

### 2.5 `nMenu::OptionsPanel` (0x330 bytes) [known] S 005e62f0, S 005e6780

An array of 27 control pointers indexed by option number (§3.7), the video mode list (vector of `{i32 width,
i32 height}` at +0x314), `minResolutionX` / `minResolutionY` (i32; defaults 1024 and 720, overridden by the root
attributes of the same names) and `savedProfileValue` (f32, −1.0 = nothing saved; §3.7).

### 2.6 `nMenu::LoadingPanel` (0x1d90 bytes) [known] S 0062ae40, S 0062b4a0; member roles [inferred] from the names loaded

Faces: picture, updateable, configurable, XML handler (+0x288), `S2CG::IProgressCallback` (+0x2a8). Members: a
container picture (+0x2b0, element `contBar`) holding the bar parts `blackBar0`, `blackBar1`, `goldBar0`,
`goldBar1`, `redBar`, `lightBar`, the label `progressText` and the picture `glow` with an alpha pulse
animation; the label `tipHeadline` (child of the panel) and the label `tipText` (child of `tipHeadline`)
[known] S 0062ab00, S 0062b4a0; and

| Field | Type | Meaning |
|---|---|---|
| `progressFraction` | f32 | last fraction received, 0..1 |
| `redBarFullWidth` | f32 | width of `redBar` as laid out (the full bar) |
| glow offset | f32 | x distance between glow and bar start as laid out |
| `tipOfTheDayCount` | i32 | root attribute (+0x1d7c) |
| loading screens | vector of std::string | root attributes `loadingScreen0` .. (+0x1d80) |

`progressFraction` is at +0x1d68, `redBarFullWidth` at +0x1d6c, the glow offset at +0x1d74 [known: mapped
struct].

### 2.7 `ai::core::LoadProgressChannel` (global `g_LoadProgressChannel` S 0088cf18) [known] S 00683b50, S 00784d40

| Offset | Type | Field |
|---|---|---|
| +0x00 | ptr | callback object (the loading panel's `IProgressCallback` face), NULL = none |
| +0x04 | f32 | `accumulated`: sum of all weights emitted since the reset |
| +0x08 | i32 | `total`, 600 |
| +0x0c | f32 | `scale`, 1/600 (the literal 0.0016666667) |

### 2.8 `nUi::Video` [known] S 00768570, S 00768ab0, S 007684b0

A still picture with a timer, not a movie player: a frame shape and a background shape bound to one texture, a
caption text block (+0x2c0), the name (+0x464), and `timer` (f32 at +0x460, seconds left). The start value is
the constant at S 00884a68, 5.0 (the same 5.0 is a literal of `Render`). Object kind 0x1a, 0x4a8 bytes.

### 2.9 `nMenu::GameEnded`, `NetInfo`, `Book`, `Info`

- `GameEnded` [known] S 0061ffe0: an `Overlapped` dialog on `menuGameEnd.xml` plus one bool `closeRequested`.
  `Victory`, `Report` and `Defeat` add no fields.
- `NetInfo` [known] S 005fd080, S 005fdf80: `Overlapped` on `menunetinfo.xml`; six arrays of 8 labels
  (0x228 bytes each) of which five are loaded by name (`id<n>`, `name<n>`, `team<n>`, `controller<n>`, `net<n>`,
  n = 0..7; the fourth array has no element); one label `sync`; one button (+0x75b0, element `exit`); a refresh
  timer (f32 at +0x7a18). Background texture `uiMediumDialog`. 0x7a20 bytes.
- `Book` [known] S 005fc400, S 005fcd50: `Overlapped` without a layout file (background texture `uiBriefing`);
  a text block, next and previous icons, a close button, a page counter label, three pictures, the story / quest
  toggle button, the picture texture name, **an array of 20 std::string pages**, `pageCount`, `currentPage`.
- `Info` [known] S 005f6110, S 005f6310: frame dialog, text block, `mode`, `index`, `id`, `autoCloseTimer` (f32).

---

## 3. Rules and algorithms

### 3.1 Logo sequence (`Splash`)

**Build** (`OnShow` S 0060bbd0) [known]. All positions are pixels relative to an origin at
(`screenWidth / 2 − 512`, `screenHeight / 2 − 384`), i.e. a centred 1024 × 768 area:

| Element | Position (x, y) | Content |
|---|---|---|
| logo picture | (384, 22), source rectangle 256 × 256 | UI texture `ui_s2Logo_addon` (literal of S 0060cb30); the language folder holds `ui_s2logo_addon.dds` |
| start button | (432, 615) | text `!Start`; the cursor is centred on it, then it is hidden |
| label | (210, 520) | `!SplashTextAddOn0` (the text tables of the install have no such key), font `Body_Arial`, colour bytes (0xe5, 0xd1, 0xc4) |
| text block | (210, 540), size 640 × 360 | `!SplashText1`; fonts by tag: `text` → `small_no_alias_white`, `head` → `chapter_garamond`, `s2k8` → `head_garamond` |
| label | (210, 630) | `!SplashText2`, font `light_system_outlined` |
| picture "video" | (0, 0), size = whole screen | `Ubisoft` |

Then the state is set to 0, the cursor is hidden and `menusplash_dev.xml` is loaded over these code-built
widgets: `Splash::LoadFromXml` S 0060b7d0 hands the elements `backdrop`, `logo`, `continue`, `text0`, `text1`,
`text2` and `video` to the seven members [known]; `contBar` exists only in the layout. The install's layout
[known: file] gives `backdrop` the texture `ui_loadingscreen`, `logo`, `text1`, `text2` and `continue`
`visible="false"`, `text0` the content `!SplashText0`, `continue` the text `START` and hotkey Enter. [inferred]
So what the player sees is the backdrop, the line `!SplashText0` and the logo pictures; the code-built logo and
the two code-built texts are hidden by the layout.

**A "video"** (`nUi::Video::Create` S 00768ab0, `Render` S 007684b0) [known]: the name is used as a UI texture
name, so the picture is `[data]\gfx\<name>.dds` (the install has `Ubisoft.dds`, `BB_Logo.dds`,
`funaticsAlpha.dds` there). The function also builds the string `[data]\Video\<name>` and does not use it.
`Create` sizes the widget to the texture's pixel size; the splash then sets the size to the whole screen
(1.0 × 1.0 relative). The same texture is bound to a background shape with colour (0, 0, 0, 1), drawn first
([inferred] a black backdrop under the fading picture). `timer` starts at 5.0 s. Each render of the visible
widget:

```
timer -= frameDeltaSeconds
alpha = 1
if 5.0 - timer < 1.0:  alpha = 5.0 - timer          # first second: fade in
elif timer < 1.0:      alpha = max(timer, 0)         # last second: fade out
draw the texture with colour (1, 1, 1, alpha)
```

- finished: `timer <= 0` (S 00768490);
- fading: not (`timer > 1` and `5.0 − timer > 1`) (S 007683f0);
- skip (S 00768430): `timer <= 1`: nothing; `timer > 1` and `5.0 − timer > 1`: `timer = 1.0`; otherwise (the
  fade-in) `timer −= 4.0` (the fade-out starts at the mirrored alpha).

**State machine** (`Update` S 0060c5a0, state at `Splash +0x15d0`, 0 at construction) [known]:

| When the picture is finished and state is | Action | Next state |
|---|---|---|
| 0 | replace the picture by `BB_Logo` | 1 |
| 1 | replace it by `funaticsAlpha` | 2 |
| 2 | nothing | 3 |
| 3 | hide the picture, show `contBar`, select cursor 1, show the cursor | 4 |

"Replace" = detach the picture, create it again with the new name at (0, 0) and set its size to the whole
screen. While a picture is neither finished nor fading, one `ShaderPreload_StepUntilDone` step runs per frame.
Keys (S 0060b9a0): `Space` skips the current picture (if it is not finished); `Esc` does the same and sets the
state to 2. A mouse press does the same as `Esc` (S 0060b7a0). Both set the state to 2 also when it is already
3 or 4. The hand-over to the main menu is the tail of every update [known] S 0060c76a: while the picture
widget is not visible, one more preload step runs and the start button's slot +0x24 (show) is called; then,
when the start button's slot +0x2c answers true, `AppState_ActivateMainScreen` runs (`app-shell.md` §3.7).

### 3.2 Main menu (`Main`)

**Activation** (`Activate` S 005deee0) [known]: attach to the root; create the title logo at the same centred
origin as the splash (source rectangle 1024 × 768; UI texture `uiTitle_addon`, literal of S 0060cb00; the
install has `gfx\uiTitle_Addon.dds`); create the banner picture and the credits scroller at (0, 0);
`PlayMusic(0)` (`music_main`, `audio.md`); load `menumain.xml`; select cursor 0. The show thunk S 005df2a0 then
clears the quit flag (`Main +0x9a0`).

**Layout load** (`OnInitLoadXml` S 005e0bb0) [known unless tagged]:

1. Root attributes: `zoomInTime` (f32), `campaignName`. The install has `zoomInTime="0"`,
   `campaignName="Main"`, `BG_3D="true"`.
2. Panels `PanelMain`, `PanelSinglePlayer`, `PanelCampaign`, and their buttons, each registered under a key:

   | Panel | Key → widget name |
   |---|---|
   | 0 | 0 `BtSinglePlayer`, 1 `BtLobby`, 2 `BtSettings`, 3 `BtCredits`, 4 `BtExitGame` |
   | 1 | 5 `BtCampaign`, 6 `BtFreegame`, 7 `BtLoad`, 8 `BtContinue`, 9 `BtBack` |
   | 2 | 10 `CampaignBack0`, 0x16 `CampaignBack1`, 0x0b..0x15 `Campaign0` .. `Campaign10` |

   Names and keys are [known]: each key is the constant stored next to its name at the registration site. Each
   button is then looked up by name below its own panel. A name that the layout does not contain leaves a NULL
   widget (the install has no `CampaignBack1`); the panel-2 handler tests for NULL, the others do not.
3. The number of mission tiles = the number of panel-2 widgets found under the keys 0x0b..0x15. Per tile:
   `Campaign<n>` (kind 10, else NULL), its child `Subline` (label, kind 9), its children `PicPlayed0` ..
   `PicPlayed3` (pictures, kind 0xe).
4. `BtContinue` (key 8 of panel 1) is disabled and its text drawn at (0.5, 0.5, 0.5, 1.0) when the user
   profile's last-save name is empty (`UserProfile +0x08`, length at +0x1c) [known] S 005e1dfd.
5. `CampaignDesc` (label), `DiffContainer`, `DiffButton0..3` (kind 0xd): each difficulty button is marked when
   its user data (layout attribute `data`, 0..3) equals the profile's stored difficulty (`UserProfile +0x3c`).
6. `RefreshCampaignTiles` (§3.3; only when the root has a `campaignName` attribute), the credits scroller
   (`creditsText`), `legalLines`, `ButtonDesc`, `ButtonHeadline` (labels, kind 9); store the load time; switch
   to panel 0; start the banner scale-in when `zoomInTime ≠ 0`.

**Buttons** (`HandleButtonClicks` S 005e27c0) [known]. Only the active panel is polled, in this order:

| Panel | Key | Action |
|---|---|---|
| 0 | 4 | close all dialogs; open the requester (dialog slot 4) with type "exit to desktop"; set the world-active flag |
| 0 | 3 | fill the credits (§3.8), fade the scroller in (0.2 s), bring it to the front, `PlayMusic(4)` |
| 0 | 1 | set the "enter the lobby" request (`System +0xb4`), `PlayMusic(0)` |
| 0 | 2 | options panel (§3.7) |
| 0 | 0 | panel 1 |
| 1 | 9 | back |
| 1 | 5 | restart the network layer offline (`Shutdown(false)`, `StartUpNetwork(0)`); panel 2 |
| 1 | 7 | restart the network layer offline; create the load panel (mode 0), or fade it in (0.2 s) when it exists |
| 1 | 6 | restart the network layer offline; create or fade in the free-game panel; set the world-active flag |
| 1 | 8 | clear the world-active flag; `ContinueLastSavegame` (`app-shell.md` §3.7) |
| 2 | 10, 0x16 | back |
| 2 | 0x0b + i, i = 0..10 | start mission i (`StartCampaignMap(i, difficulty)`, `app-shell.md` §3.8) with difficulty = the highest n whose `DiffButton<n>` is marked (`Button +0x2ec`), 2 when none is marked |

The first click found ends the poll of that frame. A click latch is read and cleared by the poll
(`Widget_ReadClearClickLatch`). "Back" (`GoBackPanel` S 005dfc00): from panel 2 to panel 1, otherwise to
panel 0.

The layout gives the buttons these hotkeys [known: `menumain.xml`]: `s`, `l`, `o`, `c`, `q` on panel 0
(`BtMultiplayer`, hotkey `m`, exists with `visible="false"` and is not registered by the code); `c`, `f`, `l`,
Esc on panel 1 (`BtContinue` has none); `1`..`9` for missions 1..9 and Esc for `CampaignBack0`.

**Panel switch** (`SwitchPanel` S 005df8b0) [known]:

1. Fade the old panel out over 0.4 s (unless none).
2. When the new panel is not 0 and `legalLines` is visible: fade it out over 1.0 s.
3. Fade the load dialog out (0.2 s) if it exists. Hide `ButtonDesc`.
4. Leaving panel 2: forget the hovered tile, hide `CampaignDesc`, reset the `CampaignScroller` (kind 0x1f) to its
   start rectangle, fade `blackarea` out (0.2 s).
5. Entering panel 2: forget the hovered tile, fade `blackarea` in (0.2 s).
6. When the credits scroller is visible: `PlayMusic(0)` and fade it out (0.2 s).
7. Fade the new panel in over 0.4 s.
8. Panels 0 and 1 call slot +8 of the 3D lobby object, if one exists, with 0 or 1: `Lobby::CLobby` S 004f54b0
   stores the value (`CLobby +0x80`) and passes it to `CLobbyCamera::SetPresetIndex` [known]; [inferred] the
   camera preset of the 3D backdrop behind the menu (`BG_3D="true"`). Panel 2 makes no such call.

**Per frame** (`Update` S 005e3810) [known], in this order:

1. Quit flag (`Main +0x9a0`) set → `System::RequestQuit`, return.
2. Free-game panel exists, its `startRequested` is set and it has no running animation (its fade-out ended) →
   `FreeGamePanel::StartFreeGame` (§3.4), return.
3. Update the widget tree.
4. Only while the screen is attached and the requester (dialog slot 4) is not open:
   1. `legalLines` visible, without a running animation, and 8.0 s or more since the layout was loaded → fade it
      out over 5.0 s;
   2. campaign hover (§3.3), hover help (below);
   3. the activate-main latch (§2.1);
   4. a button named `btTest`, if the layout has one, opens the options panel (the install's layout has none);
   5. the button table above.

**Hover help** (`UpdateButtonDescription` S 005dfc40) [known]: on panels 0 and 1 the first button of the active
panel, in key order, whose hover byte (widget +0x144) is set; on panel 2 the hovered difficulty button (the
highest-numbered one if several are); it supplies two strings (widget +0x290 and +0x420). When both are
non-empty they are shown in `ButtonHeadline` and `ButtonDesc`, `legalLines` is faded out over 1.0 s if it is
visible and has no running animation, and `ButtonDesc` is shown; otherwise `ButtonDesc` is hidden. The first
string is the button's caption as displayed (the text of its `nUi::Text` at +0x254, string at +0x3c) [known:
mapped struct]. [inferred] The second is its translated `<tip description>` text
(`!lobby_main_singleplayer_tipp`, `!tip_mainmenu_campaign`, `!tooltip_severity_fun` ..
`!tooltip_severity_hardcore` in the layout): `nUi::Tip` (0x58 bytes) keeps its description string at +0x10 and
loads it from the attribute `description` (S 004b5d80), and a tip embedded as the last member of `nUi::Button`
(0x468 bytes) lies at +0x410. `BtBack` and `CampaignBack0` have no tip in the layout. On panel 2 the mission
tiles do not feed this box.

**Close** (`Close` S 005de780) [known]: delete the load dialog, the options panel and the free-game panel (the
last after its own detach, slot +0xc), detach credits, logo and banner, detach the screen.

**Options and free-game panel** (`ShowOptionsPanel` S 005de830, `ShowFreeGamePanel` S 005de8e0) [known]: the
panel is created on first use (the free-game panel is then attached to the screen through its slot +8), faded
in over 0.2 s, and the credits scroller is faded out over 0.2 s.

### 3.3 Campaign panel

The table, the unlock rule, the completed badge, the difficulty buttons and the start are specified in
`app-shell.md` §2.5 and §3.8. Details of the screen itself:

- **Tile text** (`RefreshCampaignTiles` S 005df440) [known]: the `Subline` label gets the map's `name` as a text
  key (`C01` → the mission title in `briefings.txt`); the button's user data is index + 1. An unlocked tile is
  enabled and its two texts white; a locked one disabled and grey (0.5, 0.5, 0.5, 1.0).
- **Completed badge** [known] S 005df440: `PicPlayed<d>` with d = the `difficulty` of the map's state record
  (the highest difficulty the map was completed with, `app-shell.md` §3.8), shown only for an unlocked tile
  whose own map state exists and is completed. The function never hides a badge; the layout creates all four
  hidden and the function runs once per layout load.
- **Fourth difficulty** [known]: `DiffButton3` (layout `visible="false"`) is shown, and the container re-fitted
  to its children, when the last map of the campaign's list has a completed map state.
- **Hover box** (`UpdateCampaignMapHover` S 005e2d30) [known]: the first tile that is hovered, enabled and whose
  parent chain is enabled becomes the hovered tile. When it changes: `CampaignDesc` text = the map's `desc` key
  (`C01_desc`); child `CampaignHeadline` = key `!MISSION <index + 1>` (the key includes the number: `!MISSION 1`
  .. `!MISSION 11` exist in `ui.txt`); child `CampaignSubline` = the map's `name` key; of the pictures
  `CampaignNumberPic<n>` only the one with n = index is visible. `CampaignDesc` is visible while a tile is
  hovered and hidden otherwise. The stored index is not reset when no tile is hovered, so hovering the same
  tile again only shows the box again. Runs only while panel 2 is active.
- **Mission briefing texts** are not part of this screen. They are pages of the briefing book (§3.11) and of
  the cinematic screen, pushed by the map script after the world is built (`lua-runtime.md` §3.7).

### 3.4 Free-game panel

**Controls and their lists** [known: `menufreegame.xml`; binding S 005e8820]:

| Control | Entries (index → text key) | Writes |
|---|---|---|
| `StartResources` | 0 `!LOBBY_MATCHMAKING_STARTRESOURCES_HIGH`, 1 `..._MEDIUM`, 2 `..._LOW` | descriptor +0x20 |
| `WinCondition` | 0 `..._WINCONDITION_ENDLESS`, 1 `..._DESTROYALLENEMIES`, 2 `..._CONQUER`, 3 `..._COIN` | descriptor +0x244 and `MapInfo` win condition |
| `FogOfWar` | 0 `!LOBBY_MATCHMAKING_FOW_ENABLED`, 1 `..._FOW_DISABLED` | descriptor +0x28 |
| `PlayerType`, row 0 | one entry: the profile string at `UserProfile +0x5c`, or the text of `!Player` when it is empty | nothing |
| `PlayerType`, rows 1..5 | 0 `!Closed`, 1 `!CPU Easy`, 2 `!CPU Medium`, 3 `!CPU Hard` (added by code) | kind, computer level |
| `PlayerTribe` | 0 `!Bavarian`, 1 `!Scots`, 2 `!Egyptian` | tribe id |
| `PlayerTeam` | cycles | team |
| `PlayerColor` | cycles | colour index |
| `PlayerHQ` | cycles | start position (button user data) |
| `SelectMapButton` (hotkey `m`) | | opens the map chooser |
| `ReadyButton` (text `!Start`, hotkey Enter) | | `startRequested` |
| `LeaveButton` (hotkey Esc), `closeButton` | | `closeRequested`, fade out |

The meaning of the three option values is in `players-victory.md` §2.4.

**Opening** (`BindWidgets` S 005e8820) [known]: bind the widgets; fill and subscribe the row combos; select
entry 0 of every `PlayerType` combo; set the world-active flag; create the `SelectMapDialog` on the widget
`Dialog` and subscribe `SetMap` to its "map chosen" list; if the dialog's list is not empty, call `SetMap` with
its **first** entry; fade in over 0.2 s.

**Choosing a map** (`SetMap` S 005e8410) [known]:

1. `MapInfo` name = the map name; descriptor: `SetMapNameAndType(0, name)`; read the map's `MapInfo` into the
   descriptor (`GameFile_LoadMapInfo(name, 0, info, allowFallback = true)`, `save-format.md` §3.11).
2. `MapSize` text = `<width> x <height>` (`MapInfo +0x40`, `+0x44`).
3. `MapName` text = the translation of the map name, cut before its first `(` when that is not at position 0
   (`Fata Morgana (2 Spieler)` → `Fata Morgana `).
4. `MaxPlayer` text = the number of start positions (vector of 8-byte entries at `MapInfo +0x08`).
5. Preview picture (below).
6. Slot 0 becomes kind 2 (local human). For rows 0..5: in rows 1..5 a kind of 2 or 3 becomes 0; the row's start
   position = the row index; team of the slot = the row index; tribe = the tribe of the row's tribe combo, or
   the id 0xb0d378a3 when the combo gives none; refresh the row.
7. Descriptor +0x20 = 2. The three option combos are set to the descriptor's fog (+0x28), start resources
   (+0x20) and win condition (+0x244).
8. Start button rule (below). Place the start markers (below).

Colours, the computer levels and the kinds 0 and 1 of slots 1..5 come from the map's `MapInfo` and are not
reset [inferred: no write in S 005e8410]: the map decides which rows start closed and which as computers.
`SetMap` does not write the `MapInfo` win condition; only a change of the `WinCondition` combo does.

**Row controls** (`OnButtonClick` S 005e8050, `OnComboSelectionChanged` S 005e8200) [known]. Clicks are ignored
while the map chooser is visible.

| Control | Rule |
|---|---|
| `PlayerTeam` | `team = team + 1`; 6 becomes −1. Range −1 (no team) .. 5 |
| `PlayerColor` | `colour = (colour + 1) mod 8` |
| `PlayerHQ` | `start = (start + 1) mod startPositionCount` (unsigned; no test for a count of 0) |
| `PlayerType`, rows 1..5 | kind = 0 for entry 0, else 1; entry 1, 2, 3 → computer level 0, 1, 2 (entry 0 leaves the level); the row's start position is reset to the row index |
| `PlayerType`, row 0 | no effect |
| `PlayerTribe` | tribe id = the tribe whose property name equals `Bavarian` / `Scots` / `Egyptian` for entry 0 / 1 / 2, −1 when none (S 005e6be0); written without the default of `SetMap` |
| `SelectMapButton` | opens the map chooser (its slot +0x88) |
| `LeaveButton`, or a button named `closeButton` | `closeRequested = 1`, fade the panel out over 0.2 s |
| `ReadyButton` | `startRequested = 1`, fade the panel out over 0.2 s |

Team, colour and start buttons refresh their row; every click and every combo change ends with the start
button rule. Buttons and combos are matched by widget id (+0x11c), the three row buttons by pointer.

**Row display** (`PlayerRow_Refresh` S 005e7830) [known unless tagged]:

- tribe combo = index of the slot's tribe name in the three names; type combo = 0 for kind 0, 1 + level for
  kind 1 with level 0..2, unchanged otherwise;
- of the team button's children `team0` .. `team6`, only `team<team + 1>` is visible (`team0` = no team; the
  layout gives teams 0..5 the symbols caro, heart, moon, pik, star, cross);
- `PlayerColorBlob` and the start number are drawn in the player colour of the slot's colour index (colour table
  of `nMenu::IconConfig`, S 0087f8c8; values from `menu.setPlayerColor` in `menu.cfg`);
- the start button shows `start + 1`, or `?` when its user data is −1;
- `inRange` = `slotIndex < startPositionCount` (unsigned); the type combo is enabled when `inRange`;
- `active` = `inRange` and (the slot is a computer (kind 1) or the row is row 0): the tribe combo is enabled,
  and the team, colour and start buttons are shown (slot +0x24), exactly when `active`
  [known] S 005e7ba4..005e7c26;
- portrait [known] S 005e7c28..005e7ca4: hidden when the slot's tribe id is −1 or not `inRange`; otherwise
  visible when kind ≠ 0, with the name `<tribe property name><n>`: n = level + 1 for a computer (kind 1), 3
  for any other kind ≠ 0 (`nMenu::Avatar::SetNameFromTribe` S 0060e9a0 called with level 2); kind 0 keeps the
  name.

**Start button rule** (S 005e77c0; the same test in S 005e8410 and S 005e8200) [known]:

```
enabled = no two slots with kind != 0 among rows 0..5 have the same start position
      and no two slots with kind != 0 among rows 0..5 have the same colour index
      and (winCondition == 0  or  sides > 1)
sides   = over slots 0..7 with kind != 0: each slot with team −1 counts 1, each distinct team >= 0 counts 1
```

**Start markers** (`MapPreview_PlaceStartMarkers` S 005e7cc0) [known]: the preview has eight labels `start0` ..
`start7`. Marker i is hidden when i ≥ the number of start positions; otherwise it is placed at

```
x = previewWidth  × startX / mapWidth
y = previewHeight × (mapHeight − startY − 1) / mapHeight
```

shows the number i + 1 and is drawn in the colour of **colour index i** (not of the slot that chose it).

**Preview picture** (`UpdateMapPreviewImage` S 005e7220, path `ai::ui::ResourcePath` kind "free-game map
preview" S 004bdc60) [known]: only when the map differs from the one shown. The old texture is released; the
file is looked for as

1. `[data]\maps\freeGameMaps\<name>.bmp`,
2. `<My Documents>\SAdK\maps\<name>.bmp`,
3. `<My Documents>\SAdK\mp_saves\<name>.mps.bmp`;

each next one only when the previous file does not exist. When the resulting path exists the texture is
loaded, bound to the picture, the picture shown and the name stored. When none exists the stored name stays
empty and the picture keeps its released texture and its visibility [inferred]. The shipped previews are
128 × 128 pixels, 32 bit, one per
map [known: files]; the layout shows the source rectangle (4, 4, 120, 120) in a 120 × 120 box.

**Start** (`StartFreeGame` S 005e7350) [known], run by `Main::Update` after the panel's fade-out:

1. Clear `startRequested` and the world-active flag; `NComm_Manager::Shutdown(false)`, `StartUpNetwork(0)`,
   `ConnectAndJoin`.
2. Copy kind, tribe, colour, team, computer level and name of slots 0..5 out of the `MapInfo`.
3. For each row i = 0..5 with p = the row's start position: write the copies of row i into **slot p** of the
   `MapInfo` (kind, tribe, colour, team, computer level, name), and register session slot i with
   `SetSlotSetup(i, type, tribe as u8, team as u8, colour, p as u8)` where type = 2 for kind 1, 1 for kind 2,
   else 3.
4. `nMenu::System::ActivateGameScreen` (world build, `save-format.md` §3.8).

Rows are processed in order and each write goes to slot p of the same `MapInfo`; a slot that no row names as
its start position keeps what it held [known: the loop writes slot p only]. A closed row (kind 0) always has
its own row index as start position (`SetMap` and every type change set it, and its start button is hidden)
[known] S 005e8410, S 005e8200; the duplicate test skips closed rows, the copy loop does not [known]
S 005e6a70, S 005e7350. The world then creates one player per slot with kind ≠ 0, on the start position of the
slot index (`players-victory.md` §3.4, S 005abb60, which reads this same `MapInfo` at descriptor +0x2c). So
for an active row a that chose the position of a closed row c [known for the slot contents]:

- a < c (always so for the human, row 0): slot c gets row a's data and is then overwritten by the closed row.
  Slot a keeps row a's data unless another row chose position a. The player starts on position a; the choice
  has no effect. If another active row chose position a, that row takes slot a and player a does not exist.
- a > c: slot c is closed first and then gets row a's data; the player starts on position c. Slot a keeps row
  a's data unless another row chose position a, so the same player (name, colour, team, tribe, level) exists
  a second time on position a.

Only an exchange of positions between active rows is carried out as shown. The session slot keeps the chosen
position (`SetSlotSetup`), but the player creation does not read it. A reimplementation should write only rows
with kind ≠ 0 and close every slot that no active row names.

### 3.5 Map chooser (`SelectMapDialog`)

**List** (`RefreshMapList` S 00615370, `MapSelect_FillMapList` S 00614ec0) [known]: cleared, then filled for map
type 0 with row colour (0.8, 1.0, 0.8, 1.0) and for map type 3 (user maps) with (1.0, 1.0, 0.8, 1.0). Per type:

1. Enumerate the files matching the type's path with the name `*` (folder and extension of the type,
   `save-format.md` §2.6), names without folder and extension, not recursive.
2. Per name build an entry: display text = the translation of the name (the name itself is the text key, without
   `!`; `MP_2P_fata_morgana` → `Fata Morgana (2 Spieler)` in `ui.txt`); `isMp` = the name starts with `MP_`
   (case-sensitive).
3. Sort: entries with `isMp` false first, then by display text, byte-wise ascending (`MapListEntry::Less`
   S 00612ec0).
4. Add one text row per entry showing the display text. A row whose name starts with `MP_` (tested without
   case) is drawn in (0.8, 0.8, 1.0, 1.0) instead of the type colour. The row's user data is its index in the
   dialog's name vector, to which the file name is appended.

The two types are sorted separately; user maps always follow the install's maps. The install has 20 free-game
maps, 15 of them with the prefix `MP_` [known: directory listing].

**Controls** [known] S 00612e70, S 00614ac0, S 00614b50: selecting a row stores its index and enables
`OkayButton`; `OkayButton`, and the list's item-activation event (double click), close the dialog and notify
"map chosen" with the selected file name when the index is valid; `AbortButton` and `closeButton` close without
a choice.

**Map info shown**: only the three texts and the preview of §3.4. The dialog itself shows names only: no size,
player count or picture per row [known: no such widget is bound in S 00615430].

**Info cache**: reading a map's `MapInfo` for the panel goes through the cache files
`<Local AppData>\SAdK\<name>.info` and `<name>.usermapinfo` (`save-format.md` §3.11). The caches of all map types
are refreshed once at start (`app-shell.md` §3.3).

### 3.6 Load / save panel

The list contents (every `saves\*.aav`, by name, unsorted in directory order, hotkeys `0`..`9` on the first ten
rows, no date, no thumbnail), the confirm rules and the delete are specified in `save-format.md` §3.7.
Additional rules of the panel:

- **Opening** (S 0060ce40, S 0060e0e0) [known]: the panel fades in over 0.2 s and is brought to the front. The
  root attribute `textLoad` (mode 0) or `textSave` (mode 1) is written to the confirm button and the headline
  (`!Load` / `!Save` in the install). Mode 0 hides the edit box; mode 1 shows it and fills it with the default
  save name.
- **Buttons** (S 0060d430) [known]: `btLoad` (hotkey Enter) confirms; `btDelete` (hotkey `d`) opens the message
  box with text `!Remove this file?`, title `!Delete file` and sets its pending action to 1; a click on any other
  widget, a list row included, copies the marked row's name into the edit box. `closeButton` has hotkey Esc.
  Enter and a double click on a row confirm (S 0060d3f0, S 0060d420).
- **Message box answer** (S 0060d5b0) [known]: only result 0 (yes) acts. Pending action 0: fade out, save under
  the edit box text. Pending action 1: delete `<save folder><marked row>.aav`, mark the list dirty.
- **Overwrite after a delete prompt** [inferred]: the overwrite prompt (S 0060d000) shows the box with
  `!Overwrite file?` / `!Save` and does not write the pending action, and `MessageBox2::Show` S 0062c0d0 resets
  only the result. After a delete prompt in the same panel instance the action is still 1, so "yes" on an
  overwrite prompt deletes the marked row instead of saving. [TODO] not confirmed in the running game.
- **Load hand-over** (S 0060dd30) [known]: a non-empty chosen name → fade out (0.2 s), `System::SetPendingMapPath`,
  clear the name.

### 3.7 Options panel

**Opening and closing** [known] S 005e62f0, S 005e61b0, S 005e5490, S 005e5b70:

- On creation, when the user profile is initialised and the session is not in a network role (1..4), the
  profile's game speed factor (`UserProfile +0x24`) is remembered and set to 0: an offline game stands still
  while the panel exists. The destructor writes the remembered value back.
- `closeButton` (hotkey Esc) fades the panel out over 0.2 s and writes `settings.cfg`
  (`app-shell.md` §3.9). The destructor writes it as well.
- Root attributes `minResolutionX`, `minResolutionY` (1024, 720 in the install and as code defaults).

**Binding** (`BindOptionControls` S 005e6780) [known]: for option number n = 0..26 the widget named by entry n
of the name table (S 0087ef48) is looked up, its user data set to n, and `ApplyOptionValue(n)` subscribed to its
change event (combo box kind 0x13, slider kind 2). Then the video mode list is built (n = 0 only) and the
current value loaded into the control. Every change is applied at once; there is no "apply" or "cancel".

**Value mapping of a combo box with k entries** [known] S 005e5560, S 005e54d0:

```
apply:  fraction = selectedIndex / (k − 1)
show:   index    = min(trunc(fraction × (k − 1) + 0.5), k − 1)
```

**Options** (entries from `menuoptions.xml` [known]; targets from `ApplyOptionValue` S 005e5bd0 and
`LoadOptionValue` S 005e55b0 [known]; the scene fields are those of `app-shell.md` §2.7):

| # | Control | Entries or range | Stored value | Where |
|---|---|---|---|---|
| 0 | `cVideoMode` | built in code, below | width, height | scene settings (`settings.cfg`) |
| 1 | `cDisplayMode` | `!Fullscreen`, `!Windowed` | bool = (index == 1); the setter runs only when the value differs | scene settings +0x1c |
| 2 | `cGroundDetail` | `!Low`, `!Medium`, `!High` | 0, 0.5, 1 | scene settings +0x20 |
| 3 | `cShadowQuality` | same | 0, 0.5, 1 | +0x28 |
| 4 | `cShadowDetail` | same | 0, 0.5, 1 | +0x2c |
| 5 | `cMirrorStrength` | same | 0, 0.5, 1 | +0x38 |
| 6 | `cMirrorQuality` | same | `fraction × 0.75 + 0.25` = 0.25, 0.625, 1; shown through `(v − 0.25) / 0.75` | +0x34 |
| 7 | `cObjectDetails` | same | 0, 0.5, 1 | +0x44 |
| 8 | `cDetail` | same | 0, 0.5, 1 | +0x40 |
| 9 | `cTextureQuality` | same | 0, 0.5, 1 | +0x10 |
| 10 | `cLobbyShadowQuality` | `!Off`, `!Low`, `!Medium`, `!High` | index 0..3 | `UserProfile +0x98` and the lobby |
| 11 | `cLobbyMirrorQuality` | `!Static`, `!Realtime` | index 0..1 | `+0x9c` |
| 12 | `cLobbyShaderDetail` | `!Low`, `!High` | index 0..1 | `+0xa8` |
| 13 | `cLobbyTextureQuality` | `!Low`, `!High` | index 0..1 | `+0xa0` |
| 14 | `cLobbyObjectDetails` | `!Low`, `!Medium`, `!High` | index 0..2 | `+0xa4` |
| 15 | `cLobbyInvertMouse` | `!Off`, `!On` | bool = (index == 1) | `+0xac` and the lobby |
| 16 | `masterVol` | slider 0..1 | sound-effect master volume | sound system (`settings.cfg`) |
| 17 | `musicVol` | slider 0..1 | volume of sound category 1 | sound system |
| 18 | `effectVol` | slider 0..1 | volume of categories 0 and 3 (both set to the value) | sound system |
| 19 | `interfaceVol` | slider 0..1 | volume of category 2 | sound system |
| 20 | `sScrollSpeed` | slider, `snapCount="10"` | the slider value (f32) | `UserProfile +0x2c` |
| 21 | `cBorderScrolling` | `!Off`, `!On` | bool | `+0x30` |
| 22 | `cSmartCursor` | `!Off`, `!On` | bool | `+0x31` |
| 23 | `cFreeCamera` | `!Off`, `!On`; the layout labels it `!INVERT MOUSE` | bool | `+0x33` |
| 24 | `cInvertScrolling` | `!Off`, `!On` | bool | `+0x28` |
| 25 | `cAutosave` | `!Off`, `!5 Minutes`, `!10 Minutes`, `!20 Minutes`, `!30 Minutes`, `!60 Minutes` | seconds = `atol(entry text) × 60` | `+0x04` |
| 26 | `cConnectionType` | `!None`, `!Modem`, `!ISDN`, `!DSL`, `!LAN` | index 0..4 | `+0x94` |

- **Lobby options 10..15**: the control is disabled when no 3D lobby object exists. A change calls the lobby's
  render-option setter (slot +0x24) with all five values (the four others re-read from the lobby through slot
  +0x28) and stores the changed one in the profile even without a lobby; option 15 uses the lobby's slot +0x1c.
  On show, controls 10..14 select the lobby getter's out-arguments 1..5 in this order (shadow, mirror, shader
  detail, texture, object details) [known] S 005e5830..005e58e8; control 15 the lobby's slot +0x20. Without a
  lobby the selection is left as the layout gives it; the profile values are not shown.
- **Volumes on show** [known] S 005e55b0: `effectVol` is set to the average of categories 0 and 3 and then to
  category 0 (`SoundSystem +0xcc`; the categories are four floats from +0xcc on, S 00569f80); the control ends
  at category 0. Both sets notify, so the apply path writes that value to categories 0 and 3. Category
  meanings: `audio.md`.
- **Video mode on show** [known] S 005e5666: after `FillVideoModeCombo`, `LoadOptionValue(0)` selects the
  first list entry whose **width** equals the device's current width (the heights are only tested for
  non-zero). With two modes of the same width the control can show the other one.
- **Autosave**: the stored interval is `atol` of the entry's text string (`Button +0x290`, the text as
  displayed) × 60. [inferred] That is the **translated entry text**: it must begin with the number
  of minutes (`5 Minuten`), and `!Off` must translate to a text without a leading number (`Aus` → 0 = off). On
  show, the entry whose number equals `interval / 60` (integer division) is selected; if none matches the
  selection is left as it is.
- **Video modes** (`FillVideoModeCombo` S 005e64b0) [known]: the device enumerates display modes not smaller
  than `minResolutionX` × `minResolutionY` (`S2CE::CGraphicDevice::EnumerateDisplayModes`, whose filter rule
  is not read here); one entry `<width>x<height>` per mode; the entry equal to the device's current mode
  (width and height) is selected. If the current mode is not in the list an entry for it is appended to the
  combo and selected; the mode vector itself gets no entry for it. The four entries written in the layout
  are discarded.

### 3.8 Credits [known] S 005e2550, S 005e27c0, S 005df8b0

The credits are a `nUi::TextScroller` of the main screen (element `creditsText`, attribute
`scrollSpeed="0.1"`). Opening clears it and appends the translations of the keys `cr000`, `cr001`, ... (`cr` +
the index as three decimal digits, zero filled) until a key is missing from the translation table. The install's
`credits.txt` has 401 lines, `cr000` .. `cr400`. The scroller closes on any panel switch and when the options
or free-game panel opens.

**A line** (`nUi::TextScroller::AddLine` S 004cacb0) [known]: one label per line at x = 100 pixels, y = the
scroller's cursor, text alignment 8. The first character selects the style and is removed:

| First character | Font attribute | Spacing attributes (pixels) | Install values | Extra |
|---|---|---|---|---|
| `%` | `fontPercent` | `spacingPercentBefore`, `spacingPercentAfter` | `Chapter_Garamond`, 40, 25 | upper case |
| `#` | `fontGatter` | `spacingGatterBefore`, `spacingGatterAfter` | `Head_Garamond`, 25, 25 | |
| other | `fontDefault` | `spacingDefaultBefore`, `spacingDefaultAfter` | `Subline_Garamond`, 10, 10 | |

A non-zero "before" value is added to the cursor before the label is placed; the "after" value is added
afterwards. A remaining text that starts with `!` is looked up as a text key. The constructor (S 004cab50) sets the
spacings to 35 / 35 (`%`), 45 / 45 (`#`) and 21 / 21 (other) before the layout overrides them [known for the
three values; their assignment to the six attributes inferred from the mapped field names].

**Scrolling** (`ScrollLine` S 004ca740, `Update` S 004ca8f0) [known]: per frame, for every line with y = its
position before the move:

```
if y < 0:  detach and delete the line
else:
    move the line by −frameDeltaSeconds × scrollSpeed          # relative screen units
    f = fadeBorder converted from pixels to relative height
    a = scroller alpha (Object +0x140)
    if   y < f:  a = a × y / f                                  # upper edge
    elif y > f:  a = a × (H − y) / f                            # everything below the upper band
    text colour = (1, 1, 1, a)
```

`H` is the float at +0x64 of the scroller's layout state ([inferred] its resolved height, relative units). The
second branch has no test against `H − f`: the factor is 0 at the lower edge, 1 at `y = H − f` and larger than
1 above that [known: instructions S 004ca85f..004ca8cd]; [TODO] not established: whether the text colour
setter or the renderer clamps alpha to 1 (settled by `nUi::Text::SetColor` S 004b3ce0 and the text draw).
`fadeBorder` is not set in the install's layout; the constructor default is 100 pixels, that of `scrollSpeed`
0.05 [known] S 004cab50. [inferred] The list is not refilled when the last line has left: only
`FillCreditsText` adds lines.

### 3.9 Loading panel

**Show** (`Show` S 0062ab00) [known]: created by `nMenu::Game::OnEnter` S 005eed00 before the world build,
unless the UI is suppressed (`nMenu::System +0xa4`); builds its parts, attaches an alpha pulse animation to the
glow (parameters 0.8, 1.0, 1.0), loads `menuLoading.xml`, registers its progress face with the scene (slot +8
of the object returned by S `Global_0088ca60_Get`) and calls its own progress callback once, which draws a
frame (status key `!Preparing...`, a string of S 0062ab00).

**Layout load** (`LoadFromXml` S 0062b4a0) [known]:

- The children are bound by name: `contBar`, `blackBar0`, `blackBar1`, `redBar`, `goldBar0`, `goldBar1`,
  `progressText`, `lightBar`, `glow`, `tipHeadline`, `tipText`.
- `loadingScreenCount` names are read from the root attributes `loadingScreen0`, `loadingScreen1`, ...; the
  backdrop texture is `loadingScreen<rand() mod count>` (C runtime `rand`, unsigned remainder; a count of 0 is
  not tested). The install has count 1 and `loadingScreen0="ui_loadingscreen"`.
- `tipOfTheDayCount` (51 in the install). The tip label gets the key

  ```
  r   = ((state × 0xC1C64E6D + 0x00BC614E) >> 16) & 0x7fff      # 32-bit, arithmetic shift; state := r
  key = "!tip" + two decimal digits, zero filled, of ((GetTickCount() + r) mod tipOfTheDayCount)
  ```

  `state` is the global S 0088c138 ([inferred] 0 at process start: no initialiser was read). The remainder is
  unsigned. The install has `!tip00` .. `!tip50`.
- The full width of `redBar` and the x distance `glow.x − redBar.x` are taken from the laid-out widgets.

**Progress** (`SetProgress` S 0062b2e0, `Update` S 0062aa00) [known]: each call sets `progressText` to the status
text (a text key), stores the fraction, and **renders one frame synchronously**: background colour
(0, 0, 0.2509804, 1), begin, update and draw the panel, end and present; then the cursor is updated. The bar:
`redBar` width = `fraction × fullWidth`; glow x = bar width + the stored offset.

**The channel** (`EmitTick(text, weight)` S 00683b50) [known]: `accumulated += weight`; when a callback is set
it gets `clamp(accumulated × scale, 0, 1)`. `BuildWorld` S 00784d40 resets `accumulated` to 0 and sets total
600 and scale 0.0016666667.

**Steps**, in call order [known for texts and weights; order inferred from the call sites]:

| Order | Status key | Weight | Emitted by |
|---|---|---|---|
| 1 | `!Loading scene...` | 50 | `nGame::System::BuildScene` S 007842e0 |
| 2 | `!Loading maprenderer...` | 50 | `S2CG::Scene::Init` S 006824c0 |
| 3 | `!Loading config...` | 50 | same, after the item table |
| 4 | `!Loading characters...` | 100 in total: `100 / childCount` per child element | `CCharacterMgr::LoadCharacterDefs` S 00694c00 |
| 5 | `!Loading building configs...` | 100 in total: `100 / childCount` per child of `buildings.xml` | `Scene_LoadBuildingsXml` S 006821b0 |
| 6 | `!Loading rest...` | 50 | `BuildWorld` S 00784d40, before the map script and the world file |
| 7 | `!Building Elevation Map...` | every 16th vertex row (row index mod 16 = 0) while the mesh's report byte (+0xac, set for the first fill in `TerrainMesh::Create` S 006c0ec0) is set: `(w / rows) × 16`, w = `TerrainMesh +0xb4` = 100, rows = `TerrainMesh +0xb0` | `TerrainMesh::UpdateVertexPositions` S 006bec70 |
| 8 | `!Finalizing world` | 10 × 10 | `NLogic::System::PostLoad` S 005273d0 |
| 9 | `!completed` | fraction 1.0 directly | `nMenu::Game::OnEnter` S 005eed00 |

The fixed weights sum to 500 of 600. The elevation map carries the remaining 100: `TerrainMesh +0xb4` is set to
100 by `ai::render::TerrainMesh::Construct` S 006bebe0 [known], and `+0xb0` is slot +4 of the map interface
(`TerrainMesh::SetLoadProgressTotal` S 006beaa0) [known]. The map interface is the `NLogic::GameAccess` of the
logic system (`NLogic::System +0x34`, passed by `S2CG::Scene::Init` S 006824c0 to
`S2CG::CMapRenderer::CreateInstance` S 00689450); slot +4 of its vtable S 007e7be0 is S 005388e0, which returns
the global S 00880fac, the map height in vertex rows (`map-resources.md`) [known]. A full fill emits
`ceil(rows / 16)` ticks of `1600 / rows` each, so the ticks of a map sum to 100 or slightly more [inferred]. Steps 4 and 5 emit one tick of `100 / childCount` per child element [known].

**Hide**: after `!completed` the panel fades out over 2.0 s while the match already runs; then the HUD layout is
loaded and the chat line `!START` is added (S 005eed00) [known].

### 3.10 End of game and statistics hand-over

Which dialog opens when is in `ingame-ui.md` §3.9. The dialogs themselves [known] S 0061ffe0, S 006200f0,
S 00600c50, S 005fe6c0, S 006201f0, S 0061ff50:

- All three load `menuGameEnd.xml` each time they are shown. Before that the load hides the HUD button
  `btQuests` and closes the statistics panel if it is open.
- **Texts**. `Victory` and `Report` share one loader (the same function is in both vtables, S 007eff54 and
  S 007f0574, both S 00600c50): title = root attribute `wonTitle`, text = `wonDesc`. `Defeat`: `defeatTitle`,
  `defeatDesc`. The attributes `reportTitle` and `reportDesc` of the file are not read: a string search of the
  image finds neither name.
  The title goes to the label `title`, the text to the label `text`; in a network role (1..4) the text key gets
  the suffix `MP` (`!DescWon` → `!DescWonMP`). Install values: `!TitleWon`, `!DescWon`, `!TitleDefeat`,
  `!DescDefeat`. The dialog then fades in over 0.2 s.
- **Buttons**. `btContinue` (`!Continue Game`): toggle the statistics panel (`Game::ToggleStatisticPanel`) and
  fade the dialog out (0.2 s); the match goes on. `btEnd` (`!Quit`): the same, and the statistics panel's
  "leave on close" byte (+0x1028) is set, so closing the statistics leaves the match. A click on any other
  button of the dialog only fades it out. `Defeat` disables `btContinue`.
- **Statistics hand-over**: nothing is copied. The statistics panel reads the live statistics of the still
  loaded world (`ingame-ui.md` §3.8.1, `quests-sacrifices-stats.md`); leaving the match destroys them.
- **Leaving** (`PerformDeferredLeave` S 005eae90, S 0061fea0) [known]: detach dialogs 5, 3, 0. If the map type
  (`MapInfo +0x1d0`) is 1: activate the main screen. Otherwise: log out of the referee connection when a lobby
  manager exists, activate the main screen, and when a 3D lobby object exists and its slot +0x34 returns 1, call
  its slot +0x2c with the value of slot +0x30 ([inferred] the return to the lobby world;
  `../subsystems.md` §2).
- The profile's map state decides whether the win dialog opens (`app-shell.md` §3.8, table of transitions).

### 3.11 Network info, briefing book, help popup

**`NetInfo`** (opened with key `x` in a network role, `ingame-ui.md` §3.3.3) [known] S 005fd350, S 005fd5a0,
S 005fdf00:

- Title `!Game info`. The one button is created in code with the caption `!Cancel` and then configured by the
  layout element `exit` (text `!OK` in the install), because the layout is loaded after it on every show; a
  click on it, or the dialog's own close request, closes the dialog.
- Refreshed in the first update after opening (the timer is zeroed on show) and then every 1.0 s. One row per
  player table entry 0..7 that is active (a row of an inactive entry keeps its texts):

  | Column | Content |
  |---|---|
  | `id<n>` | `Player #<n + 1>: ` |
  | `name<n>` | player name, in the player's colour |
  | `team<n>` | key `!Team <team + 1>` |
  | `controller<n>` | by the session slot's kind: 0 `!OPEN`, 1 `!USER`, 2 `!AI`, 3 `!CLOSED` |
  | `net<n>` | `!Host` or `!Client`; then `, ` + by connection type 0..4: `!NONE`, `!MODEM`, `!ISDN`, `!DSL/CABLE`, `!LAN`; then `(+)` when the slot is filled, else `(-)` |

  The session slot is the one whose player index equals the row (`EventGameInformation`,
  `../NCOMM_GAME_PROTOCOL.md`).
- Line `sync`: `V<build version>` + separator + `Synchron: ` + `!Yes` or `!No` (the session manager's in-sync
  byte, `network-session.md` §2, +0x4c) and, outside role 0, `, <net tick length>` (manager +0x38). The
  separator is `, ` when the global S 00889d84 is 0, else ` - `. The only write to that global stores 0
  (`NDoodads::System::Load` S 00544f1f) [known: references]; [inferred] the separator is always `, `.

**`Book`** (opened by the map script, `menu.openBookDialog(text)`, `menu.addPage(text)`,
`menu.addPicture(texture)`; `lua-runtime.md` §3.7) [known] S 005fc310, S 005fcd50, S 005fcae0, S 005fc9f0,
S 005fcbc0, S 005fc740:

- Title = the map name (`MapInfo +0x24`). Opening resets page count and current page to 0.
- `AddPage(text)`: stores the text key in slot `pageCount` (capacity 20, **not checked**), shows it when it is
  the first, increments the count, sets the current page to 0, enables "next" when there is more than one page.
- Next: enable "previous", `current += 1`, disable "next" when `current == count − 1`. Previous:
  `current −= 1`, disable "previous" when `current == 0`, enable "next". Both then set the text.
- Every page change, every `AddPage` and the return from the quest list set the counter label to
  `<current + 1>/<count>` and start the voice-over named by the current page's text key
  (`Menu_PlayVoiceOver`, `audio.md`).
- Picture: 512 × 512 pixels at (201, 30) inside the dialog, source rectangle 512 × 512.
- The toggle button switches between the story pages and the quest list (`createQuestUi` / `destroyQuestUi`,
  `lua-runtime.md` §4.3); its caption is `!STORY` while the quest list is shown and `!QUESTS` otherwise; entering
  the quest list stops the voice-over.
- Closing (`Book::OnHide` S 005fc160 → `Overlapped::OnHide` S 0062e0a0) stops the music and deletes the
  script-made widgets; it does not restore the story view. A book closed in the quest list therefore opens
  the next time with the page text, counter and page buttons still hidden and the caption `!STORY`, until the
  toggle is clicked once [known].
- The shipped caller is `scripts\mapTools\quests.lua`: first page with `openBookDialog`, the quest's briefing
  picture, further pages with `addPage` [known: data].

**`Info`** [known] S 005f6310, S 005f5f40, S 005d96e0: a popup that an `Overlapped` dialog toggles for itself.
The only caller passes mode 0 and, through `ToggleDialogInfoDefault` S 005d9790, id 0: the text key
`dialog<slot>_<id>` (slot = the dialog's slot number 0..8) in a 285 × 360 text block at (55, 41), font
`Subline_Garamond`; the install's `dialogs.txt` has keys of this form. The frame uses a part of the texture
`uiGame`. The call in `Overlapped::Update` S 0062e240 is gated by a byte of the dialog (+0xbfc) and
by a non-zero focus state of the dialog's title-bar grabber (`Overlapped +0x520`). The only instructions of the
image that write that byte store 0: the `Overlapped` constructor (S 0062e5ee) and `Overlapped::OnShow`
(S 0062ec44); the other instructions with displacement 0xbfc, or 0xbdc / 0xbd8 / 0xbd4 from the three faces,
belong to other classes or address other fields [known: byte search of the image]. [inferred] The popup never
opens in the shipped game. The popup closes itself when its
timer exceeds 0.3 s; the timer advances every frame and is cleared by a repeated toggle with the same id.
Modes 1 and 2 run a page script `[data]\scripts\info\i_<hex of index>.lua` or `b_<hex of id>.lua` (lower-case
hex, no padding) or show `Database file i_<hex> not found!`; no code path passes these modes
(`lua-runtime.md` §6.1). The 124 page scripts (95 `i_`, 29 `b_`) and `info.txt` are therefore unused by the
shipped flow; a page is a list of `ui.infoLabel2(x, y, key)`, `ui.infoLabel`, `ui.infoPicture`,
`ui.infoText(x, y, w, h, key)` calls [known: data].

---

## 4. Update order

No screen of this document runs in the logic tick. Everything is per frame, inside `nMenu::System::Update`
S 005da500 (`app-shell.md` §4.2), or event driven.

**Per frame, `nMenu::System::Update`** [known]:

1. text table reload when the language changed (`Localization::ReloadIfLanguageChanged`), cursor update;
2. unless the UI is suppressed (`System +0xa4`): update every attached dialog slot 0..8 with argument 0 (no
   focus), in slot order; then, from slot 8 down, the first attached slot whose slot +0xc answers true is
   updated once more with argument 1 (focus) and the search ends; text input (global S 0087c0e5) is disabled
   while `MsgBox` (slot 6) is attached and enabled otherwise; the widget root updates (its update face, slot +4)
   and then its slot +0x84 runs ([inferred] the draw). [inferred] The root update runs the update of the
   current top-level screen (§3.1 or §3.2): `nUi::Object::Update` S 004a3920 updates every child whose slot
   +0x10 answers true, and both screens attach themselves to the root;
3. minimap symbol expiry;
4. when the caller's flag argument is set: slot +4 of `nUi::GameAction` (also once inside step 2 while `MsgBox`
   is attached);
5. a non-empty pending map path → `StartPendingMap` S 005d9fd0, then the path is cleared.

**Per frame, `Main::Update`**: the order of §3.2.

**Events**:

| Event | Order of effects |
|---|---|
| Start button of the free-game panel | click: flag + fade-out (0.2 s) → a later frame of `Main::Update`: `StartFreeGame` → `ActivateGameScreen` → `Game::OnEnter` (loading panel, world build, synchronous) |
| Mission tile | same frame (inside `Main::Update` → `HandleButtonClicks`): clear the world-active flag, network restart, descriptor, `ActivateGameScreen`, slot +8 of `nUi::GameAction` (S 005df2c0) |
| Load panel confirm | click: the marked row's name is stored (nothing when no row is marked) → the panel's next update: fade-out (0.2 s), pending path → `System::Update` step 5 of that or the next frame |
| World build | `Game::OnEnter` S 005eed00: select cursor 1, set up the HUD, stop the music, `NComm_Manager::BeginGameStarting`, register the chat and message sinks, loading panel, `BuildWorld` (progress frames of §3.9), `!completed`, fade-out, `SendGameLoadedEvent`, cursor 0, HUD layout, chat line `!START` |
| Win or defeat | `ingame-ui.md` §3.9 → dialog → statistics → leave (§3.10) |

---

## 5. Inputs and outputs

**Consumes**

- Layout files and text tables (§6); the user profile (`UserProfile`: last save name, difficulty, account name,
  options); the map files' `MapInfo` through the info cache; the directory listings of the free-game, user-map
  and save folders; the device's display mode list; the tribe properties (names of the three tribes); the player
  colour table; the live session information (`NetInfo`).
- Mouse and keyboard through the widget tree (`ingame-ui.md` §3.3). Hotkeys are layout attributes.

**Produces**

- The filled `GameLoadDescriptor` and the session slot set-up (free game, campaign: `app-shell.md` §3.7).
- `settings.cfg` (options, difficulty), deleted save files, save files (save panel).
- Requests to `nMenu::System`: enter the lobby, quit, pending map path, activate main / game screen, music index.

**Network**: none of these screens sends a message of its own. Entering a single-player mode restarts the NComm
layer in role 0, a one-machine session (`network-session.md` §3.3) [known: `Shutdown(false)`, `StartUpNetwork(0)`
in S 005e27c0, S 005df2c0, S 005e7350, S 005dfef0]. After the world build `Game::OnEnter` calls
`NComm_Manager::SendGameLoadedEvent(1)` when the UI is not suppressed (`network-session.md` §3.8). `NetInfo`
only reads: the player table, the session's `EventGameInformation` slots, the manager's in-sync byte and tick
length [known] S 005fd5a0. Leaving a match whose map type (`MapInfo +0x1d0`) is not 1 logs out of the referee
connection when a lobby manager exists [known] S 0061fea0 (`../message-catalog.md`, referee messages).

---

## 6. Data-driven parameters

| File | Keys | Example values |
|---|---|---|
| `ui\layout\menusplash_dev.xml` | root `BG_3D`; elements `backdrop`, `logo`, `continue`, `text0`..`text2`, `contBar`, `video` | `BG_3D="false"`; backdrop texture `ui_loadingscreen`, source 1024 × 1024 |
| `ui\layout\menumain.xml` | root `BG_3D`, `campaignName`, `zoomInTime`; the widget names of §3.2 and §3.3; `creditsText scrollSpeed` | `true`, `Main`, `0`; `0.1` |
| `ui\layout\campaigns.xml` | `Campaign name`; `Map name, desc, filename, type, prerequisite<n>` | `C02`, `C02_desc`, `C02`, `map`, `prerequisite0="C01"`; 11 maps |
| `ui\layout\menufreegame.xml` | the widget names of §3.4; combo `size`, `string<n>` | three option combos with 3, 4 and 2 entries |
| `ui\layout\menuselectmapdialog.xml` | `MapList`, `OkayButton`, `AbortButton` | |
| `ui\layout\menuLoadSave.xml` | root `textLoad`, `textSave`; `btLoad`, `btDelete`, `listbox`, `edit`, `headline`, `messagebox` | `!Load`, `!Save` |
| `ui\layout\menuoptions.xml` | root `minResolutionX`, `minResolutionY`; the 27 control names; entry lists | 1024, 720 |
| `ui\layout\menuLoading.xml` | root `loadingScreenCount`, `loadingScreen<n>`, `tipOfTheDayCount`; bar part names | 1, `ui_loadingscreen`, 51 |
| `ui\layout\menugameend.xml` | root `wonTitle`, `wonDesc`, `defeatTitle`, `defeatDesc` (`reportTitle`, `reportDesc` unused); `title`, `text`, `btContinue`, `btEnd` | `!TitleWon`, `!DescWon` |
| `ui\layout\menunetinfo.xml` | `id<n>`, `name<n>`, `team<n>`, `controller<n>`, `net<n>` (n = 0..7), `sync`, `exit` | row 0 at y = 90, 20 pixels per row; columns at x = 50, 120, 240, 310, 420 |
| `scripts\menu.cfg` | `menu.setPlayerColor` (the colour table of rows and markers), `menu.setLanguage` | `app-shell.md` §3.6 |
| `language\<code>\ui.txt` | map names (`MP_2P_fata_morgana`), `!MISSION <n>`, `!tip00`..`!tip50`, option and button texts, `!TitleWon`, `!DescWonMP`, `!<n> Minutes` | `Fata Morgana (2 Spieler)`, `5 Minuten` |
| `language\<code>\briefings.txt` | mission titles `C01`, descriptions `C01_desc`, book pages | |
| `language\<code>\credits.txt` | `cr000` .. `cr400` | 401 keys; a value may be empty (`cr000`), start with `#` or `%` (§3.8) |
| `language\<code>\` | `ui_s2logo_addon.dds`, `ui_s2logo.dds` (localised logo textures) | |
| `gfx\` | `Ubisoft.dds`, `BB_Logo.dds`, `funaticsAlpha.dds` (logo sequence) | |
| `maps\Freegamemaps\` | `<name>.s2m`, `<name>.bmp` (preview, 128 × 128, 32 bit), `<name>.bin` | 20 maps |
| `maps\campaignMaps\` | `C01.s2m` .. `C11.s2m`, previews, scripts | |
| `scripts\info\` | `i_<hex>.lua`, `b_<hex>.lua` (unused, §3.11) | |

Constants in code, not data: the 5.0 s logo time and 1.0 s fades (§3.1); the fade times 0.2, 0.4, 1.0, 5.0 s and
the 8.0 s legal-line delay (§3.2); six free-game rows, eight start markers, eight colours, teams −1..5 (§3.4);
the row colours of the map list (§3.5); the 600-unit progress total and the step weights (§3.9); the 2.0 s
loading fade-out; the 1.0 s `NetInfo` refresh; the 20-page book.

---

## 7. Save and load

| State | Where | Written when |
|---|---|---|
| Campaign difficulty (0..3) | `settings.cfg`, `UserProfile +0x3c` | on the click of a difficulty button (S 005ded70) |
| All options of §3.7 | `settings.cfg` (profile fields, sound volumes, scene settings block) | closing the options panel, its destruction, shutdown (`app-shell.md` §3.9) |
| Name of the last save | `settings.cfg`, `UserProfile +0x08` | the profile field: by `GameFile_Save` S 005aa260 for a save type (10, 110) in role 0 (`UserProfile::SetLastSaveName` S 00579d60, which writes no file); it reaches `settings.cfg` with the next write of that file (rows above). Read by "Continue" and by the main menu's button state |
| Map states (unlocking, badges, fourth difficulty) | `data.cfg` | on a win and at shutdown (`app-shell.md` §3.8, §3.9) |
| Save files | `<My Documents>\SAdK\saves\<name>.aav` | save panel; deleted by `btDelete` |
| Map info caches | `<Local AppData>\SAdK\<name>.info`, `.usermapinfo` | whenever a `MapInfo` is read and the cache is not newer than the file (S 005aa030) |

Not persisted: the free-game set-up (rows, options, chosen map), the active menu panel, the tip generator
state, the book pages (pushed again by the map script after a load). The free-game panel object is created on
the first click of `BtFreegame` and deleted by `Main::Close` S 005de780; its layout load selects the first map
of the list with that map's own `MapInfo` and start resources 2 (§3.4). A later click while the object exists
only fades it in again (`ShowFreeGamePanel` S 005de8e0), so the set-up survives Leave and reopening within one
activation of the main screen [known]; [inferred] it starts fresh after every return to the main screen.

None of these screens is part of a save file.

---

## 8. Determinism notes

Presentation and front end only. No function of this document runs inside the logic tick, and none writes
simulation state while a match runs, with these boundaries:

- **Before the world exists** the free-game panel and the campaign start write the match parameters
  (descriptor, `MapInfo` slots, session slots). They are inputs of the world build; in a network match the same
  parameters come from the host's lobby dialog and are distributed by the session (`network-session.md` §3.8),
  not by these screens.
- **Random numbers**: the loading screen uses the C runtime `rand()`, the tip uses its own generator and
  `GetTickCount()` [known] S 0062b4a0. Neither is the logic random generator (`logic-core.md` §3.3); they
  may differ between machines.
- **Real time**: the logo timers, the `NetInfo` refresh, the credits scroll and the help popup run on the frame
  delta (`Timer_GetFrameDeltaSeconds`); the 8 s legal-line delay compares `Timer_GetTotalSeconds` values
  [known] S 007684b0, S 005fdf00, S 004ca740, S 005f5f40, S 005e3810.
- **Options panel**: offline it sets the local game speed factor to 0 while it exists (§3.7). In a network role
  it leaves the factor alone, so it cannot stall a lockstep match.
- **Progress frames** are drawn from inside the world build and change nothing but the screen.
- The book's story / quest toggle calls the script functions `createQuestUi` / `destroyQuestUi`; whether a map
  script may touch simulation state there is a property of the script (`lua-runtime.md` §4.3). The shipped
  callbacks build widgets only [inferred from `quests.lua`].

---

## 9. Notes for a Godot reimplementation

- **Screens are scenes; the flow is code.** One `Control` scene per screen, a small state machine for
  splash → main (three panels) → loading → match → end dialog → statistics → main. The original layout files
  give positions for a 1024 × 768 centred design area; a converter can turn them into scenes once, or the remake
  can lay the screens out freshly. The widget names matter only to the original code.
- **Reproduce exactly**:
  - the unlock rule, badges and fourth difficulty (`app-shell.md` §3.8) and the keys `!MISSION <n>`,
    `<map>`, `<map>_desc`;
  - the free-game rules of §3.4: option value ranges and their order (index 2 = low start resources is the
    default), the team / colour / start cycles, the start button rule, the re-indexing of rows by start position,
    the tribe default, the mapping of rows to session slots and of kind to slot type;
  - the map list order (non-`MP_` first, then by translated name, install maps before user maps) and the display
    name rule (cut at `(` in the panel, full text in the list);
  - the autosave option's dependence on translated text is an accident of the original: store minutes as data.
- **Do not reproduce**: the unbounded 20-page book array, the overwrite-after-delete message box state (§3.6),
  the write of closed rows in `StartFreeGame` (§3.4) unless a test shows a map depends on it, the synchronous
  render inside the loader (use a threaded or stepped load with a progress signal).
- **Loading progress**: keep the step names as text keys (`!Loading scene...` etc.) and report real progress; the
  weights of §3.9 describe the original's stages, not a requirement.
- **Logo sequence**: three still images, 5 s each with 1 s fades, skippable; no video codec is needed.
- **A converter has to provide**: the three logo textures, the localised logo, the loading backdrop, the map
  previews (`.bmp` next to each map, 128 × 128; show the inner 120 × 120), the text tables (`ui.txt`,
  `briefings.txt`, `credits.txt`), `campaigns.xml`, the player colour table from `menu.cfg`, and per map the
  `MapInfo` fields the panel shows (size, start positions, per-slot kind, colour, level).
- **Persistence**: one settings file and one progress file per user suffice (`app-shell.md` §3.9 for the
  original layouts if the remake wants to import an existing profile). The options map onto engine settings;
  the lobby options 10..15 exist only for the 3D lobby.
- **A server** provides nothing for these screens. The end dialog's `MP` text variant belongs to network roles
  1..4, the referee log-out on leaving to a session with a lobby manager (`../MATCH_START.md`).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | The slot contents when a row chooses the position of a closed row are answered in §3.4 (a lower row stays on its own index; a higher row is copied and can exist twice). Open: what the duplicated player looks like in the match | running game: free game in which row 2 chooses the position of a closed row 1 |
| 2 | Overwrite prompt after a delete prompt deletes instead of saving (§3.6) | running game: in one save panel press Delete, answer No, then save over an existing name and answer Yes |
| 3 | Whether a credits line's alpha factor above 1 is clamped (§3.8) | static: `nUi::Text::SetColor` S 004b3ce0 and the text draw |
| 4 | Whether the activate-main latch (`Main +0x228`) or the `Info` gate (`Overlapped +0xbfc`) is ever set through a pointer the byte search cannot see (§2.1, §3.11). Also searched: no `LEA` forms the address of either byte in a function of the two classes (the `LEA` hits with displacement 0x228 and 0xbfc belong to other classes), and the only store to `+0xbfc` in `Overlapped` is the constructor's 0 (S 0062e5ee). Left: a store through a register computed elsewhere | running game: write watch on the two bytes while using the main menu and dragging a dialog's title bar |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 0060ba30 / 0060bbd0 | `nMenu::Splash::ctor` / `OnShow` | logo screen: layout name, code-built widgets |
| 0060c5a0 / 0060b9a0 / 0060b7a0 | `Splash::Update` / `OnKeyDown` / `OnMouseButton0Down` | state machine, skip keys |
| 00768ab0 / 007684b0 | `nUi::Video::Create` / `Render` | still picture with timer and fades |
| 00768490 / 007683f0 / 00768430 | `Video::IsFinished` / `IsFading` / `SkipTimerToFinalSecond` | |
| 005e4ea0 / 005deee0 | `nMenu::Main::ctor` / `Activate` | main screen |
| 005e0bb0 | `Main::OnInitLoadXml` | panels, button keys, tiles, difficulty buttons |
| 005e3810 / 005e27c0 | `Main::Update` / `HandleButtonClicks` | per-frame order, button actions |
| 005df8b0 / 005dfc00 | `Main::SwitchPanel` / `GoBackPanel` | panel fades |
| 005dfc40 / 005e2d30 | `Main::UpdateButtonDescription` / `UpdateCampaignMapHover` | hover help, mission box |
| 005df440 / 005ded70 / 005df2c0 | `Main::RefreshCampaignTiles` / `OnDifficultyButtonClicked` / `StartCampaignMap` | campaign |
| 005e2550 | `Main::FillCreditsText` | credits keys |
| 005dfef0 | `Main::ContinueLastSavegame` | "Continue" |
| 005e6e30 / 005e8820 | `nMenu::FreeGamePanel::ctor` / `BindWidgets` | free-game panel |
| 005e8410 / 005e7350 | `FreeGamePanel::SetMap` / `StartFreeGame` | map chosen, start |
| 005e8050 / 005e8200 | `FreeGamePanel::OnButtonClick` / `OnComboSelectionChanged` | row and option controls |
| 005e7830 / 005e6f50 | `FreeGamePanel::PlayerRow_Refresh` / `FreeGamePlayerRow::Bind` | row display |
| 005e77c0 / 005e69d0 / 005e6a70 / 005e75e0 | `UpdateStartButtonEnabled` / `HasDuplicateColor` / `HasDuplicateStartPosition` / `CountDistinctTeams` | start rule |
| 005e7220 / 005e7cc0 | `UpdateMapPreviewImage` / `MapPreview_PlaceStartMarkers` | preview |
| 005e6be0 / 005e6cc0 | `Tribe_ComboIndexToTribeId` / `Tribe_TribeIdToComboIndex` | tribe combo |
| 004bdc60 | `ai::ui::ResourcePath::ctor` | preview file search order |
| 00614410 / 00615430 | `nMenu::SelectMapDialog::ctor` / `OnXmlLoaded` | map chooser |
| 00615370 / 00614ec0 | `SelectMapDialog::RefreshMapList` / `MapSelect_FillMapList` | list contents and colours |
| 00613000 / 00612ec0 | `MapListEntry::ctor_FromName` / `Less` | display text, sort order |
| 00614ac0 / 00614b50 / 00612e70 | `SelectMapDialog::OnButtonClick` / `ConfirmSelection` / `OnMapListSelectionChanged` | |
| 0060ce40 / 0060e0e0 / 0060d7b0 | `nMenu::LoadSavePanel::ctor` / `LoadFromXml` / `BindControls` | load / save panel |
| 0060da50 / 0060d000 / 0060d430 / 0060d5b0 / 0060dd30 | `RefreshFileList` / `Confirm` / `OnButtonClick` / `OnMessageBoxResult` / `Update` | |
| 005e62f0 / 005e61b0 | `nMenu::OptionsPanel::ctor` / `dtor` | options: pause while open |
| 005e6780 / 005e64b0 | `OptionsPanel::BindOptionControls` / `FillVideoModeCombo` | |
| 005e55b0 / 005e5bd0 | `OptionsPanel::LoadOptionValue` / `ApplyOptionValue` | the 27 options |
| 005e54d0 / 005e5560 | `OptionsPanel_SelectComboByFraction` / `OptionsPanel_GetComboFraction` | combo ↔ fraction |
| 005e5490 / 005e5b70 | `OptionsPanel::CloseAndSaveSettings` / `OnButtonClicked` | close writes `settings.cfg` |
| 0062ae40 / 0062ab00 / 0062b4a0 | `nMenu::LoadingPanel::ctor` / `Show` / `LoadFromXml` | loading panel, backdrop, tip |
| 0062b2e0 / 0062aa00 / 0062a910 | `LoadingPanel::SetProgress` / `Update` / `Hide` | progress frame, bar |
| 00683b50 | `ai::core::LoadProgressChannel::EmitTick` | progress accumulation |
| 00784d40 / 007842e0 / 006824c0 | `nGame::System::BuildWorld` / `BuildScene` / `S2CG::Scene::Init` | progress steps |
| 00694c00 / 006821b0 / 006bec70 / 005273d0 | `LoadCharacterDefs` / `Scene_LoadBuildingsXml` / `TerrainMesh::UpdateVertexPositions` / `NLogic::System::PostLoad` | progress steps |
| 005eed00 | `nMenu::Game::OnEnter` | creates the loading panel, runs the build, `!completed` |
| 0061ffe0 / 006200f0 / 006201f0 / 0061ff50 | `nMenu::GameEnded::ctor` / `LoadFromXml` / `SetTitleAndText` / `OnButtonClick` | end dialogs |
| 00600c50 / 005fe6c0 | `nMenu::Report::OnLoadXml` (win loader, slot 1 of the `Report` and `Victory` face vtables) / `nMenu::Defeat::LoadFromXml` | texts |
| 005eae90 / 0061fea0 | `nMenu::Game::PerformDeferredLeave` / `nMenu_Game_LeaveMatchToMainMenu` | leaving after the statistics |
| 005fd080 / 005fdf80 / 005fd350 | `nMenu::NetInfo::ctor` / `LoadFromXml` / `OnShow` | network info |
| 005fd5a0 / 005fdf00 | `NetInfo::RefreshInfo` / `Update` | rows, 1 s refresh |
| 005fc400 / 005fc310 / 005fcd50 | `nMenu::Book::ctor` / `OnShow` / `AddPage` | briefing book |
| 005fcae0 / 005fc9f0 / 005fcbc0 / 005fc900 / 005fc740 | `Book::HandlePageButtons` / `RefreshPageCounter` / `Update` / `ShowQuestView` / `SetPicture` | |
| 005f6110 / 005f6310 / 005f5f40 | `nMenu::Info::ctor` / `Open` / `Update` | help popup, page scripts |
| 005d96e0 / 005d9790 | `nMenu::System::ToggleDialogInfo` / `ToggleDialogInfoDefault` | the only caller of `Info::Open`; its only caller, with id 0 |
| 0062e240 / 0062e750 | `nMenu::Overlapped::Update` / `OnShow` | gate of the `Info` popup; clears the gate byte |
| 005da500 / 005d9ef0 / 005d9f10 / 005d9f60 | `nMenu::System::Update` / `AppState_ActivateMainScreen` / `ActivateGameScreen` / `PlayMusic` | flow |
| 005d9fd0 / 005da880 / 005d9ee0 | `nMenu::System::StartPendingMap` / `SetPendingMapPath` / `RequestQuit` | requests of the screens |
| 005de830 / 005de8e0 / 005de780 / 005df2a0 | `Main::ShowOptionsPanel` / `ShowFreeGamePanel` / `Close` / show thunk | panel creation, deletion, quit flag clear |
| 004cab50 / 004ca9b0 / 004cacb0 | `nUi::TextScroller::ctor` / `LoadFromXml` / `AddLine` | credits defaults, attributes, line styles |
| 004ca740 / 004ca8f0 | `nUi::TextScroller::ScrollLine` / `Update` | credits scroll and fade |
| 005aa260 / 00579d60 / 005792c0 | `GameFile_Save` / `UserProfile::SetLastSaveName` / `UserProfile_SaveSettings` | last save name, `settings.cfg` |
| 006beaa0 / 006bebe0 / 005388e0 | `TerrainMesh::SetLoadProgressTotal` / `ai::render::TerrainMesh::Construct` / `NLogic::GameAccess` slot 1 | elevation-map progress total (map height in vertex rows) and weight 100 |
