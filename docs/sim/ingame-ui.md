# In-game user interface: HUD, menus, selection and actions

Binary: `sadk_noav.exe` (image base 0x400000). `S 00xxxxxx` is a static address in that binary.

Tags: **[known]** = read directly in the decompiled code at the given address, or in the named data file and
key. **[inferred]** = one step of reasoning from what is visible; this includes statements that rest on the
mapped description of a function whose body was read only in part. **[TODO]** = not established, with what
would settle it. Nothing in this document was observed in the running game.

Related documents: [game-commands.md](game-commands.md) (every command the UI issues, the action table and
its availability rules), [lua-runtime.md](lua-runtime.md) (the `menu.*` / `ui.*` script functions and button
events), [players-victory.md](players-victory.md) (messages, quests, victory state),
[save-format.md](save-format.md) (the load and save panel's file handling),
[network-session.md](network-session.md) (hang state, chat), [hud-panels.md](hud-panels.md) (the HUD panels in
detail: statistics, in-game settings, messages, tooltips), [ui-toolkit.md](ui-toolkit.md) (the widget toolkit
in detail), [frontend-screens.md](frontend-screens.md) (the front end: main menu, options, free game, campaign),
[lobby-screens.md](lobby-screens.md) (the lobby screens), [match-setup-room.md](match-setup-room.md) (the match
set-up room), [`../subsystems.md`](../subsystems.md) §2.9,
[`../data-loading.md`](../data-loading.md), [`../asset-formats.md`](../asset-formats.md).

---

## 1. Purpose and scope

Two namespaces:

- **`nUi`**, the widget toolkit: a tree of `nUi::Object` widgets below one `nUi::Root`, a layout record
  (`Deployment`) per widget, sprites (`Shape`), text (`Text`), buttons, sliders, lists, tab controls, tooltips,
  the cursor, the key state table, and the loader that builds a widget tree from a layout XML file.
- **`nMenu`**, the screens built with it: the menu system with its screens and dialogs, and inside the game
  screen (`nMenu::Game`) the HUD: selection panel with info boxes, the round action buttons, build menu,
  minimap, messages, quest lines and quest log, goods bar, sacrifice bar, world overlays, statistics, in-game
  settings (military, transport priority, goods distribution, diplomacy view), options, load/save, requester.

The UI is the only producer of player commands. It never changes the simulation itself: every change goes
through `NComm_Manager::QueueGameCommand` ([game-commands.md](game-commands.md) §3.1), with the exceptions
listed in §8.

Out of scope: the lobby screens (`LobbyMenu::*`: [lobby-screens.md](lobby-screens.md); the match set-up room:
[match-setup-room.md](match-setup-room.md)), the front-end screens `nMenu::Main`,
`Splash`, `FreeGamePanel`, `SelectMapDialog`, `Campaigns` ([frontend-screens.md](frontend-screens.md); they use
the same toolkit; only their place in the screen table is given here), the camera rules (`nGame::Camera`), the debug screens (`nMenu::Debug`, the debug
toggles), the renderer.

---

## 2. Data model

### 2.1 `nUi::Object` (0x198 bytes) [inferred: field list from the mapped struct, cross-checked on the readers named]

Every widget is an `nUi::Object` or derives from it. Three vtables: primary at +0, `NCore::IUpdateable` at +4,
`nUi::Event` (which is also the `Configurable`, i.e. the XML-loadable face) at +8.

| Offset | Field | Meaning | Evidence |
|---|---|---|---|
| +0x28 / +0x2c | user data (i64) | XML `data`; code stores per-widget ids here (action number, good id, quest index, building id) | S 004a76c0 |
| +0xc8 | name (`std::string`) | XML `name`, else the element name | S 004a76c0 |
| +0xe4 | enabled (u8) | XML `enabled` | S 004a76c0, S 0049fdd0 |
| +0xe8 | `nUi::Focus` | state 0 idle, 1 hovered, 2 pressed; `canReceiveFocus` (u8 at Focus +0x18, default 1) | S 004c1c30, S 004a3b30, S 004a0020 |
| +0x114 | render id (i32) | draw order stamp of the current frame; decides which of two overlapping widgets is "under the cursor" | S 004a0500, S 004a1b00 |
| +0x118 | forwardEvents (u8) | XML `forwardEvents`: input is offered to the children first; constructor default 1 | S 004a07a0, S 004a3cc0 |
| +0x119 | click latch (u8) | set by a completed left click or by the hotkey; polled and cleared by the owner | S 0049ff60, S 0049ffc0 |
| +0x11c | unique id (i32) | process-wide widget id; code compares ids to recognise a sender | S 004a3cc0 |
| +0x120 | clipping (u8) | XML `clipping`: children are clipped to the widget rectangle | S 004a58a0 |
| +0x124 | layout dirty (i32) | 2 = changed, 1 = re-evaluate mouse-over next update, 0 = clean | S 004a0500, S 004a3920 |
| +0x128 | deployment stack (`std::list<Deployment>`) | front = base layout; animations push temporary copies at the back; the back entry is the one in effect (hit test, clip, draw) | S 004a4050, S 004a2490, S 004a1820 |
| +0x134 | owned animations (`std::list<Animation*>`) | ticked in `Update`, deleted when finished | S 004a3920 |
| +0x140 | opacity (f32) | multiplied into text and sprite alpha | S 004a0630 |
| +0x144 | hovered (u8) | set by `OnMouseEnter`, cleared by `OnMouseLeave` | S 004a3b30, S 004a1c80 |
| +0x148 | kind (i32) | widget type number, §2.3 | S 004c28a0 |
| +0x14d | visible (u8) | XML `visible` | S 004a1090 |
| +0x150 | parent | | S 004a40c0 |
| +0x158..+0x15c | children (`std::vector<Object*>`) | sorted ascending by z-order (`qsort` on +0x178); updated in that order, offered input in the reverse order (last = topmost first) | S 004a0550, S 004a3920, S 004a07a0 |
| +0x178 | z-order (i32) | XML `zorder` | S 004a0ad0 |
| +0x17c | hotkey (i32) | XML `hotkey`; −1 = none | S 0049ffc0 |
| +0x181 | owned child (u8) | set for widgets created by the XML factory; they are deleted before a reload | S 004c21d0, S 004a3840 |
| +0x184 | intersection type (i32) | XML `intersectionType`: 0 rectangle (its height reduced by one pixel), 1 ellipse inscribed in the rectangle; any other value never hits | S 004a1820 |
| +0x188 / +0x18c / +0x190 | local 4×4 matrix, cached world matrix, dirty flag | XML `transform`; scale animations | S 004a0930, S 004a0b60 |

### 2.2 `nUi::Deployment` (0x70 bytes) and `nUi::Position` [known] S 004bcb80, S 004bc0b0, S 004bc570, S 004aae00

A `Position` is two values, each `{f32 value, u8 isRelative}` (x at +4/+8, y at +0xc/+0x10). **All stored
lengths are fractions of the screen**: x of the back-buffer width, y of its height (`nUi_PixelsToRelativeX/Y`
S 004aaae0, S 004aab10 divide by the device resolution). The flag only records whether the XML wrote a
percentage.

| Offset | Field |
|---|---|
| +0x10 | owner widget |
| +0x14 | absolute position (screen fraction; value x +0x18, y +0x20) |
| +0x28 | relative position, i.e. relative to the parent's origin (x +0x2c, y +0x34) |
| +0x3c | offset (x +0x40, y +0x48) |
| +0x50 | size (width +0x54, height +0x5c) |
| +0x64 | alignX: 0 none, 1 left, 2 center, 3 right |
| +0x68 | alignY: 0 none, 1 top, 2 center, 3 bottom |
| +0x6c | dock (XML `anchor`): 0 none, 1 top, 2 right, 3 bottom, 4 left, 5 center |

The constructor `Deployment::ctor` S 004bc030 starts the size at 0 × 0 [known]; a widget that neither its XML nor
its code gives a size keeps 0 × 0 (the fight overlay, §3.8.6).

### 2.3 Widget kinds [known] S 007bf5f0 (name table, 39 entries), S 004c28a0 (factory switch)

`controltype` values are matched without regard to case against this table; the index is the kind.

| Kind | `controltype` | Created class (bytes) | Kind | `controltype` | Created class (bytes) |
|---|---|---|---|---|---|
| 0 | Item | `Item` 0x2d8 | 20 | DropDownMenu | `DropDownMenu` 0xb90 |
| 1 | Slider | `Slider` 0x560 | 21 | Listbox | not creatable |
| 2 | Slider2 | `Slider2` 0x1380 | 22 | ListBox2 | `ListBox2` 0x1848 |
| 3 | StackedSlider | `StackedSlider` 0x2b8 | 23 | Dialog | not creatable |
| 4 | SliderEx | `SliderEx` 0xef0 | 24 | TextBlock | `TextBlock` 0x1a0 |
| 5 | Grabber | `Grabber` 0x1a0 | 25 | Chart | `Chart` 0x1a8 |
| 6 | Edit | `Edit` 0x330 | 26 | Video | not creatable |
| 7 | EditEx | `EditEx` 0x12a8 | 27 | TextScroller | `TextScroller` 0x228 |
| 8 | Icon | `Icon` 0x3f8 | 28 | ChatSystem | `ChatSystem` 0x3358 |
| 9 | Label | `Label` 0x228 | 29 | Table | not creatable |
| 10 | Button | `Button` 0x468 | 30 | Serverlist | not creatable |
| 11 | ButtonEx | `Button` 0x468 (kind 10) | 31 | Scroller | `Scroller` 0x400 |
| 12 | PictureButton | `PictureButton` 0x500 | 32 | ShapedObject | `ShapedObject` 0x230 |
| 13 | OverlayButton | `OverlayButton` 0x790 | 33 | Container | plain `Object` 0x198 |
| 14 | Picture | `Picture` 0x288 | 34 | ProgressBar | `ProgressBar` 0x768 |
| 15 | AlphaFanPicture | `AlphaFanPicture` 0x2f8 | 35 | Root | not creatable |
| 16 | Desktop | not creatable | 36 | Graph | `Graph` 0x298 |
| 17 | Bar | `Bar` 0x350 | 37 | TabControl | `TabControl` 0x2f0 |
| 18 | ComboBox | `ComboBox` 0x930 | 38 | InventoryButton | `InventoryButton` 0x5d8 |
| 19 | ComboBoxNew | `ComboBoxNew` 0xb88 | | | |

"Not creatable": the factory logs `Object type <n> is not a known ui object type` and returns null; the
element is skipped. An unknown name logs the same with the name [known] S 004c2730.

`nMenu::Factory::CreateObjectByName` S 0060c880 [known] is the factory installed while the game runs. It
tests these names first (case-insensitive) and passes everything else to the table above:

| `controltype` | Class (bytes) | Use |
|---|---|---|
| mainmenubutton | `nMenu::MainMenuButton` 0x598 | front-end buttons |
| goodbutton | `nMenu::GoodButton` 0x1bd0 | one good, settler or soldier with count and state icons |
| timedgoodbutton | `nMenu::TimedGoodButton` 0x1bd8 | a good button with a fan-shaped timer |
| sacrificebutton | `nMenu::SacrificeButton` 0xd98 | one sacrifice in the temple info box |
| clocksymbol | `nMenu::ClockSymbol` 0x1818 | 8-frame animated clock with a counter |
| roundingamebutton | `nMenu::RoundIngameButton` 0xa18 | round HUD button with green/red hover highlight |
| avatar | `nMenu::Avatar` 0x1d0 | player portrait |

### 2.4 `nUi::Shape` (0x94 bytes): the sprite of a widget [known] S 004aa700, S 004aa5a0

| Offset | Field | Default |
|---|---|---|
| +0x14 | texture | none |
| +0x18 | mapping: source rectangle x, y, w, h in texture pixels | |
| +0x38 | flipped (u8): mirrored | 0 |
| +0x3c / +0x44 | width / height, each with a "relative" byte (+0x40 / +0x48) | 0; the widget's own draw (S 004aa310) does not read them, it uses the owner's rectangle [known] |
| +0x4c | color (f32[4]): RGBA multiplier | 1, 1, 1, 1 |
| +0x5c | disabledColor (f32[4]): used while the owner or any of its ancestors is disabled (`IsFlagE4SetInHierarchy` S 0042e330, read by S 004aa310) [known] | 0.4667, 0.4667, 0.4667, 1 (`Shape::ctor` S 004aa5a0) |
| +0x6c mask texture, +0x70 maskUV0, +0x78 maskUV1 | second texture whose alpha masks the sprite; its UV corners | none; (0,0)..(1,1) |
| +0x80..+0x8c | borders top, right, bottom, left (pixels) | 0 |
| +0x90 | stretch (u8) | 1 |
| +0x92 | rotation (u16): the quad is turned about its centre by −value ÷ 65536 × the constant at S 00882840 [known] S 004a88a0; [TODO] the constant's value (a read of the float settles whether a full turn is 65536) | 0 |

The shape is drawn only if it has a texture and the mapping's width or height is not 0 [known] S 004aa310.

### 2.5 `nUi::Text` (0x8c bytes) [known] S 004b46d0; [inferred] S 004b3ed0, S 004b43c0

font (+0x10), position (+0x14) and offset (+0x28) as `Position`, string (+0x3c), align (+0x58: 4 left, 8 center,
0x10 right), contentHidden (+0x60), upperCase (+0x61), lowerCase (+0x62), color RGBA (+0x64, default white),
wrap width and height in pixels (+0x74, +0x78).

### 2.6 Singletons and globals

| Object | Where | Role | Evidence |
|---|---|---|---|
| `nUi::Root` | function-local static S 00885a88, `GetInstance` S 00491970 | root widget, kind 0x23 (35), size 1.0 × 1.0; input entry; device-change listener | [inferred] S 00491810 |
| `nUi::Cursor` | `g_pCursor` S 00885c98 (0x90 bytes) | position (+0x24 x, +0x2c y, screen fraction), previous position (+0x38, +0x40), visible (+0x70), wheel delta (+0x74), cursor table (+0x7c), current index (+0x8c) | [inferred] S 00492be0 |
| `nUi::GameAction` | `g_pGameAction` S 00885a00 (0xd08 bytes); active map `g_pActiveAction` S 008859fc | per virtual key: `keyState[256]` (+4), `pressedThisFrame[256]` (+0x404), `asyncHoldFrames[256]` (+0x804), `asyncDown[256]` (+0xc04), ctrlDown (+0xd04), shiftDown (+0xd05), asyncPollEnabled (+0xd06) | [inferred] S 00490f50, S 00490e90 |
| input capture | `g_pUiInputCapture` S 00885cb4 | widget that receives all mouse events while set (sliders, grabbers) | [known] S 004913f0 |
| mouse-over widget, hovered list | S 00885cb0, S 00885cb8 | result of the per-frame mouse-over arbitration | [inferred] S 004a1b00 |
| templates document | `g_pUiTemplatesXml` S 00885d64 | parsed `templates.xml` | [known] S 004ab6f0 |
| widget factory | S 00885dac | `nMenu::Factory` | [known] S 004a76c0 |
| XML handler registry | S 00885c8c, reload flag S 00885c88 | map handler → file name, for the hot reload | [inferred] S 00491c90 |
| `ai::ui::Localization` | S 00885ca0 (0x2c bytes) | key → text map, language code (+0xc, default `de`) | [inferred] S 00496070, S 004955a0 |
| `nMenu::System` | `g_pNMenuSystem` S 0088b83c (0xb8 bytes) | screen table, §2.7 | [known] S 005dda30 |
| `nMenu::IconConfig` | S 0088b908 | icon atlas rectangles per good, building, sacrifice | [inferred] S 00611320 |
| script button events gate | S 0088b314 | 1 while a map script is loaded | [lua-runtime.md](lua-runtime.md) §4.4 |

### 2.7 `nMenu::System` (0xb8 bytes) [known] S 005dda30, S 005d9650, S 005d97a0; offsets [inferred]

| Offset | Field |
|---|---|
| +0x08 | quit flag |
| +0x0a | "a dialog with focus was updated this frame" |
| +0x0c | current top-level screen (Main, Game, Splash or Exit) |
| +0x10 | dialog slots 0..8 (below) |
| +0x34 | `Info` (encyclopaedia / help popup) |
| +0x09 | initialised |
| +0x38 / +0x3c / +0x40 / +0x44 | `Main` (0x9a8 bytes), `Game` (0x11038), `Splash` (0x15d8), `Exit` (0xb58) [known] S 005dda30 |
| +0x48 | minimap symbol list (script markers and message markers) |
| +0x4c | language string |
| +0x68 | pending map or save path (`std::string`); non-empty starts that map on the next update |
| +0x84 | current music index (−1 none); +0x88 seven music sound ids |
| +0xa4 | UI suppressed (set only by the constructor to 0, see `subsystems.md`) |
| +0xb4 | one-shot "enter the lobby" request |
| +0xb5 | 3D world active behind the screen (XML `BG_3D` of a screen root) |

Dialog slots (index used by `ActivateScreenById`, `ToggleScreen`, `IsScreenAttached`):

| Slot | Class | Opened by |
|---|---|---|
| 0 | `Report` | map completed, map type other than 1 and 0x65 (§3.9) |
| 1 | `Debug` | no opener in the shipped flow (`subsystems.md`) |
| 2 | `Book` | `menu.openBookDialog` |
| 3 | `Victory` | map completed, map type 1 or 0x65 (§3.9) |
| 4 | `Requester` | menu items "Main Menu" and "Quit" |
| 5 | `Defeat` | local player defeated (§3.9) |
| 6 | `MsgBox` | file errors (`!FILENOTFOUND`, `!INVALID_SAVEGAME`) |
| 7 | `NetInfo` | key `x` in a network match |
| 8 | `Cinematic` | `menu.startCinematic` |

All nine derive from `nMenu::Overlapped` (a draggable framed dialog: frame +0x1c0, grabber +0x428, title label
+0x5c8, close button +0x7f0) [inferred] S 0062e530.

### 2.8 `nMenu::Game` (0x11038 bytes): the game screen [inferred: offsets from the mapped struct and the readers named]

| Offset | Member |
|---|---|
| +0x20 | `nUi::Desktop` face: the screen's root widget (name of the XML root, `menuingame`) |
| +0x1b8 | owning `nMenu::System` |
| +0x1c4 | NComm message callbacks; +0x1c8 `NLogic::CallbackReceiver` (building, soldier, fight, sacrifice events) |
| +0x968 | `MenuGameRootObject`: the HUD root; hiding it hides the HUD |
| +0x29a8 | `MiniMap` |
| +0x7ff8 | `MenuSelection` (§2.9) |
| +0x8000 | `ActionButtonPanel` (4 × `ActionButton` 0xa28 at panel +0x288, `AttackSlider` at panel +0x2b30, confirmation `MessageBox2*` at panel +0x2b28, override map at panel +0x2dd0) |
| +0xae04 | `OverlayPanel` (world overlays) |
| +0xae10 | pause panel |
| +0xb098 / +0xb09c | chatFadeOutTime / chatFadeInTime (XML) |
| +0xb0a0 | "sacrifice started" effect picture |
| +0xb328 / +0xb32c | `QuestLog*` / `Tutorial*` |
| +0xbf20 | an `nUi::Slider` (0x560 bytes) that the constructor builds (S 005eeb2b) and the destructor S 005ed340 destroys; nothing creates, loads or reads it: an unused member of the screen, no simulation state [known for the two writes; inferred for the absence of any other use] |
| +0xb330 | deferred "leave the match" flag |
| +0xcc70 | `LoadingPanel*` |
| +0xcc74 | `StatisticPanel*` |
| +0xcc78 | `OptionsPanel*` |
| +0xcc7c | `IngameSettingsPanel*` |
| +0xcc80 / +0xcc84 | `LoadSavePanel*` in load mode / in save mode |
| +0xcc88 | in-game `nUi::ChatSystem` |
| +0xffe0 | team-chat modifier (Shift held) |
| +0xffe4 | `GameLoadDescriptor*` |
| +0xffe8 | `nGame::System*` (cursor at +0x10 with the hovered cell at +0x24 / +0x28, camera at +0x2d0, state at +0x2d8) |
| +0xfff0 | info-map overlay mode (0 / 1) |
| +0xfff4 | local player entry (`*entry` = player index) |
| +0x11010 / +0x11020 | two `NLogic::Unique` members: the constructor S 005ee5d0 and `OnEnter` S 005eed00 set their ids to -1; no function assigns or reads them: unused members of the screen, no simulation state [known for the writes; inferred for the absence of a reader] |
| +0xfff9 | paused |
| +0x10000.. | four debug toggles |
| +0x11030 | game speed saved while paused |

### 2.9 `nMenu::MenuSelection` [known] S 00617c70 (constructor defaults), S 00617910, S 00616f40

| Offset | Field | Values |
|---|---|---|
| +0x10 | parent `Game` | |
| +0x14 | preview picture (`selectionPicture`) | |
| +0x18 | `NLogic::Unique` of the target (id at +0x20 / +0x24, −1 = none) | |
| +0x28 | resolved render instance of the target | |
| +0x2c | preview "update every frame" (u8) | |
| +0x30 | preview render size | 256 (constructor S 00617c70) |
| +0x34 | map selection kind → `InfoBox*` | §3.6 |
| +0x40 | current selection kind | −1 = none |
| +0x44 | active info box | |
| +0x48 | renderMarker (XML) | |
| +0x49 | preview dirty (u8) | |
| +0x4c | noSelectionTexture (XML), +0x68 noSelectionMapping (XML, 4 floats) | shipped `ui_ingame3`, `464 433 184 184` [known: data] |
| +0x88 | mode | 1 normal, 2 build placement, 3 street placement, 4 reset pending |
| +0x8c / +0x90 | cell of the last click (−1 = none) | |

**Preview picture** [known] `UpdatePreviewImage` S 00615990, `RenderObjectPreview` S 0068cae0,
`RenderPreviewTexture` S 00681300: the selected object is rendered into a 256 px texture by a `MapCamera`
(`MapCamera::ctor` S 00680ef0): look-at = the centre of the object's box, distance = max(box size) × 1.725 (double
S 007f9030) ÷ tan(fov), fov = 50° (the full horizontal angle), near 0.1, far 200. `Shape::BindTexture` S 004a86d0
maps the 256 px picture into the 244 × 244 `selectionPicture` through the mask `ui_mask.tga`.
`MenuSelection::Update` S 006163f0 re-renders it every frame while `+0x2c` is set and once while `+0x49` is set
(then clears it). The constructor sets both to 0; `+0x49` is set only by `Game::OnDeviceReset` (through
`Object_SetFlag49` S 00615640, its only caller at 005eabbf), so the picture is redrawn once after a device reset
[known] (presentation only); no writer of `+0x2c` other than the constructor's 0 (S 00617ce9) was found by an
instruction search for constant byte stores, but register-valued stores through other base registers were not
ruled out one by one [inferred: never set]. `LoadFromXml` and `RefreshFromGameSelection` render it directly.

The object that is selected lives in `nGame::System` (`Selection`, [game-commands.md](game-commands.md) §2.4:
kind 0 None, 1 Building, 2 Flag, 3 Settler, 4 Street, 5 Ship, 6 ShipRoute). `MenuSelection` derives the
**selection kind** (§3.6) from it.

### 2.10 Player messages as the HUD sees them [inferred] S 005f75a0, S 005f73e0

Record fields read by the HUD: id (+0x10 / +0x14), remaining time (+0x18, f32; a new message starts at 600.0),
cell x / y (+0x1c / +0x20, −1 = no place), read flag (+0x78), type (+0x7c, 1..8). The record itself belongs to
`NPlayer::Messages` ([players-victory.md](players-victory.md) §2.7).

| Type | Filter entry (`cbMessages`) | Icon x in `ui_ingame5` (y 800, 40 × 37) | New-message sound | Minimap symbol |
|---|---|---|---|---|
| 1 | `!Military` | 240 | `uiMessage1` | 1 |
| 2 | `!Scholar` | 280 | `uiMessage0` | 0 |
| 3 | `!Economic` | 360 | `uiMessage0` | 0 |
| 4 | `!Sacrifice` | 160 | `uiMessage0` | 0 |
| 5 | `!Chest` | 200 | `uiMessage0` | 5 |
| 6 | `!Navy` | 320 | `uiMessage0` | 0 |
| 7 | `!Misc` | 80 | `uiMessage0` | 0 |
| 8 | none (letters, autosave notice) | 0 | `uiMessage0` | 0 |

The pairing of filter entries with types follows from the numbering in S 005ecaf0 (`cbMessages` item *i* gets
user data *i* + 1 [known]) and from the filter array indexed by type (S 005f8e80) [inferred]. A type outside the
table gets the icon at x 80 (`SetupSlot` S 005f75a0) [known].

---

## 3. Rules and algorithms

### 3.1 The layout XML

#### 3.1.1 Files and loading [known] S 00491ac0, S 004ab3e0, S 0060cbd0, S 005ee5d0

A layout file is an XML document (encrypted on disk like every game XML, `data-loading.md`). Each file is owned
by one `nUi::XMLHandler`, constructed with the file name; `LoadFromFile` opens and parses the file and calls
the handler's "document loaded" method with the document. For a screen (`nMenu::Object`) that method loads the
**root element** into the screen's desktop widget, so the root element's children are the screen's top-level
widgets. A panel created later (statistics, in-game settings, options, load/save) is an `XMLHandler` of its own
with its own file. The root element name is free: the shipped `menurequester.xml` has the root `menuLoadSave`
[known: data] and loads.

Handlers register in a global map; when the reload flag S 00885c88 is set, `ReloadAll` S 00491c90 first reloads
`templates.xml` and then every registered file. A widget that is reloaded deletes its XML-created children
first (the "owned child" flag) and keeps the children that code created [inferred] S 004a3b00, S 004a3840.

#### 3.1.2 Elements: how a tree is built [known] S 004a76c0, S 004c21d0

An element is processed by the widget that it describes:

1. `nUi::Object::LoadFromXml` reads the common attributes (§3.1.4) and, between them, the child elements
   `deployment` (before the attribute `pos`), `description` and `focus` if present, and as its last step calls
   the factory for the element's children. `<description>` has the format of `<text>` (§3.1.7) and fills the
   `nUi::Text` every widget owns; the base draw shows it whenever it is not empty [known] S 004a0500.
2. `Factory::CreateChildrenFromXml`: **every child element that has a non-empty `controltype` attribute**
   creates a new widget of that type as a child, marks it as owned, and loads it from that element (with
   template resolution, §3.1.3). Child elements **without** `controltype` create nothing by themselves. The
   attribute is read from the child's own element only, before any template is applied, so a `controltype`
   that an element would get through its `template` creates nothing: `overlayBuilding/clocksymbol`, whose
   `controltype="picture"` comes only from the template `clock`, is never created [known] S 004c21d0.
3. A child element without `controltype` is meaningful only if the parent's class asks for it by name: a class
   loads its fixed members with `member.LoadChildFromXml(doc, parentNode, "<name>")`. Examples: every widget
   reads `<deployment>`; a `ShapedObject` reads `<shape>`; a `Label` and a `Button` read `<text>`; a `Picture`
   and a `Button` read `<tip>`; a `PictureButton` reads `<background>`; `nMenu::Game` reads `<miniMap>`,
   `<btBack>`, `<cbMenu>`, `<selection>` and so on (§3.4).

So the element name is either the name of a fixed member of the enclosing class (binding by name, in code), or,
with `controltype`, the name of a free widget that code may later find with
`Object::FindObjectByName` (case-insensitive, recursive over the subtree [known] S 004a7530, so the code's
`clockSymbol` finds the XML's `clocksymbol`; a miss logs `Object with name <n> not found!`). An element that neither the class asks for nor
carries `controltype` is ignored; that is what makes it usable as a local template (§3.1.3).

#### 3.1.3 Templates [known] S 004ab6f0, S 004ab9f0, S 004ab530

`template="X"` on an element applies another element first, then the element itself (so the element's own
attributes win, and child elements of both are loaded: first the template's, then the element's):

1. If `templates.xml` (root element `templates`) has a top-level element named `X`, that one is used.
2. Otherwise the loader searches for a sibling scope: starting at the element's parent and walking up to the
   document root, the first ancestor that has a child element named `X` supplies it (name comparison is exact,
   case-sensitive).
3. If neither exists the attribute has no effect.

A template may itself carry `template`. While a template is applied, the `{document, node}` of the element
being loaded is kept on a list in the object; the factory uses that list to load an XML-created child a second
time from the same-named child of the outer element (§3.1.2 step 2, the loop over the created widget's list)
[known] S 004c21d0. Code applies templates by name too: `Configurable::ApplyTemplate(name)` looks only in
`templates.xml` (used for `overlayBuilding`, `overlaySoldier`, `overlayFight`, `overlaySettler`, `tipDefault`,
`tipGood`, `tipBuilding`, `tipSacrifice`, `tipSoldier`, `tipInfoboxBuilding`, `graph`) [inferred] S 0063f550,
S 006464c0, S 00642970.

Shipped local templates are recognisable by their names: `t_sacrificebutton`, `t_infoboxclosebutton`,
`t_headline`, `t_slider`, `t_slot` [known: `menuingame.xml`, `menuIngameSettings.xml`].

#### 3.1.4 Common attributes (every widget) [known] S 004a76c0, S 004ab250

| Attribute | Type | Effect |
|---|---|---|
| `controltype` | name | on a child element: create a widget (§2.3) |
| `template` | name | §3.1.3 |
| `name` | string | widget name; without it the element name is used, but only if the widget has no name yet and no template is being applied to it |
| `enabled` | bool | disabled widgets take no press and draw with the shape's disabled colour |
| `visible` | bool | initial visibility |
| `clipping` | bool | clip children to the rectangle |
| `intersectionType` | int | 0 rectangle, 1 ellipse (hit test) |
| `data` | int | user data (sign-extended to 64 bit) |
| `pos` | two ints, pixels | relative position; same field as `<deployment pos>` but integers only |
| `zorder` | int | order among siblings (ascending = later drawn = on top); the parent re-sorts |
| `debugColor` | four ints 0..255 | debug tint (÷ 255) |
| `hotkey` | one character, or exactly two decimal digits | character code that clicks the widget; `hotkey="27"` = Esc, `"13"` = Enter, `"s"` = 0x73. Any other length is ignored |
| `forwardEvents` | bool | offer input to the children |
| `pointfiltering` | bool | texture sampling without filtering |
| `receiveEvents` | bool | default true; false makes the widget transparent to input |
| `transform` | 16 floats | local 4×4 matrix |

The shipped layouts contain `pointfilering` (two places); that spelling is not read [known: data + S 004a76c0].

#### 3.1.5 `<deployment>`: position, size, anchoring [known] S 004bcb80, S 004aae00, S 004aac10

Attributes, applied in this order: `pos`, `offset`, `size`, `anchor`, `alignx`, `aligny`.

`pos`, `offset` and `size` hold exactly two tokens. A token is `N%` (N ÷ 100, a fraction of the screen axis),
`Npx` or a bare number (pixels; converted at load time to a screen fraction by dividing by the current
back-buffer width or height). An attribute with another token count or an unparsable token is ignored.

- `pos`: position relative to the parent's top-left corner.
- `size`: width and height.
- `anchor` (the dock), values `none top right bottom left center`, case-insensitive:

  | anchor | x | y | width | height |
  |---|---|---|---|---|
  | top | offset.x | offset.y | parent width | own |
  | bottom | offset.x | parent height − own height + offset.y | parent width | own |
  | left | offset.x | offset.y | own | parent height |
  | right | parent width − own width + offset.x | offset.y | own | parent height |
  | center | offset.x | offset.y | parent width | parent height |

- `alignx` (`none left center right`) and `aligny` (`none top center bottom`), each axis independently and with
  its own words only (case-insensitive, `__stricmp`; `top` on `alignx` is unrecognised):
  left/top → offset; center → (parent − own) × 0.5 + offset; right/bottom → (parent − own) + offset. With `none`
  on an axis that axis keeps `pos`.
- Priority when the layout is re-applied (parent resized, size changed): dock, else alignment, else the plain
  relative position [inferred] S 004bc870. A widget without a parent uses 1.0 × 1.0 as the parent size.

An unrecognised value string leaves the field unchanged. The absolute position is the parent's absolute
position plus the relative one [inferred] S 004bbed0. A size or position change notifies children and parent
(`NotifySizeChanged`, `NotifyPositionChanged`), which re-apply their own docks and alignments.

**Resolution.** There is no virtual UI resolution: pixels in the XML are real pixels. On a resolution change
`CGraphicDevice::UpdateViewport` S 004d6650 hands every listener the old and the new size, and
`nUi::Root::OnViewportChanged` S 004914a0 rescales every widget by old ÷ new per axis (`Object::OnViewportChanged`
S 004a0860 → `ApplyViewportToStates` S 004a1f70 → `Deployment::ApplyScale` S 004bd0d0). `Position::GetScaled`
S 004aabb0 multiplies only the components stored as screen fractions (pixel-born values), so a value given in
pixels keeps its pixels; dock and alignment are re-applied [known]. A progress bar also scales its full width
(+0x748) by the same factor (`ProgressBar::ApplyViewportToStates` S 004bd1e0). The options
panel lists only video modes of at least `minResolutionX` × `minResolutionY` (1024 × 720 in `menuoptions.xml`)
[known: data; inferred S 005e64b0]. The HUD is therefore corner-anchored groups of fixed pixel size.

#### 3.1.6 `<shape>` [known] S 004aa700

| Attribute | Type | Meaning |
|---|---|---|
| `texture` | name | looked up or loaded from `[data]\gfx\` by the UI resource manager [inferred] S 00494000; `menuStatistics.xml`'s tech tree pictures name it with the extension (`techtree_bavaria.dds`), every other layout texture is a bare name; the code also loads interface textures by names with the extension (`ui_ingame4.dds` S 007e5b20), so both forms resolve [inferred] |
| `mapping` | 4 numbers | source rectangle x y w h in texture pixels |
| `flipped` | bool | mirror |
| `width`, `height` | number | draw size; default the owner's size |
| `color`, `disabledcolor` | 4 floats | RGBA 0..1 |
| `border` | float | sets all four borders; if absent `bordertop`, `borderright`, `borderbottom`, `borderleft` |
| `stretch` | bool | with borders: stretch (true) or tile (false) edges and centre |
| `mask` | name | mask texture; with it `maskUV0`, `maskUV1` (2 floats each) are read |

Drawing [known] S 004a8f70, S 004a88a0: with all borders 0 one quad; otherwise a nine-slice (four fixed corners,
edges and centre tiled or stretched). `UiSprite_RenderToOwnerRect` S 004aa310 takes the owner deployment's screen
fractions (position x/y at the list node's +0x20/+0x28, size w/h at +0x5c/+0x64), multiplies each by the back buffer's width or height
(`RelativeToPixelsX` S 004aab50 / `RelativeToPixelsY` S 004aab80: `(float)((double)W * f)`, rounded to float32) and
truncates each toward zero with `__ftol2_sse` S 006f2af0. There is no +0.5. Four independent truncations: the right
edge is `trunc(x) + trunc(w)`, not `trunc(x + w)`. `Shape::DrawSliced` S 004a8f70 then works on that integer
rectangle: inner edges `ftol(x + left)`, `ftol(x + w - right)`, `ftol(y + top)`, `ftol(y + h - bottom)` (corner sizes
are the differences, so the right and bottom corners absorb rounding); `DrawQuad` S 004a88a0 puts every quad at
(x − 0.5, y − 0.5) .. (x + w − 0.5, y + h − 0.5) (constants 0xBF000000 at S 0087c50c / S 0087c510), UV = source rect /
created texture size without a half-texel shift. Stretched edges and centre are one quad each; unstretched ones tile
at integer tile sizes `ftol(srcR − srcL)` while `pos + tile < end`, the remainder quad keeps the full source tile
(squeezed, not cropped). Twelve callers (button backgrounds S 004b3a60, `Icon::Draw` S 004ce780, S 004be2b0,
S 004b5200, S 004bd690, S 004c6940, S 004cc480, S 004d11c0, S 00630fc0, S 007684b0, the in-world markers S 00788f90 /
S 007885e0); text does not go through it. Vertex colour = colour × widget opacity.

`mapping` is in pixels of the texture **as created** [known]: `CTexture::CreateD3DTexture` (S 004e7a9e) creates
UI textures with `D3DX_DEFAULT` sizes, so an image whose sides are not powers of two is rounded up and
stretched, and `Shape::DrawQuad` S 004a88a0 divides the mapping by the created size. So `ui_loadingscreen`
(1024 × 768) with the mapping `0 0 1024 1024` fills the screen (`menuLoading.xml`, `menusplash_dev.xml`).

#### 3.1.7 `<text>` [known] S 004b46d0

`uppercase`, `lowercase` (bool; applied with the system locale), `pos` and `offset` (two integer pixels),
`align` (`left` 4, `center` 8, `right` 0x10), `contenthidden` (bool: every character except `|` is drawn as
`*`), `content` (the text; localised if its first character is `!`, §3.10), `font` (font name, §3.10), `color`
(4 floats), `wrapSize` (two integer pixels: wrap box; the text wraps inside it, the first line centred
vertically on the text's point, and lines past the box height are cut, `BuildTextInBox` S 004e3270,
[ui-toolkit.md](ui-toolkit.md) §3.1). The shipped `visible` on `<text>` is not read.

#### 3.1.8 `<tip>` and `<focus>` [inferred] S 004b5d80; [known] S 004c1be0

`<tip description="…" data="…" align="…" hidden="…">`: tooltip text (localised if it starts with `!`), a tip
id (int), the corner of the popup placed at the cursor (`topleft` 0, `topright` 1 = default, `bottomright` 2,
`bottomleft` 3), and `hidden="true"` to disable the tip. `<focus canReceiveFocus="false"/>` excludes the widget
from hover arbitration.

#### 3.1.9 Type-specific attributes and children

Read in the named loaders; the attribute lists are [known] from the string references of each function, the
meanings [inferred] from its mapped description unless a section below reads the code.

| Type | Attributes | Named child elements |
|---|---|---|
| Label S 004b1d50 | | `text` |
| TextBlock S 004b7e90 | `content`, `font` | |
| Picture S 004b16f0 | | `shape`, `tip` |
| Button S 004afed0 | `type` (style, default 12), `checkbutton`, `marked`, `mapping`, `mapping_cursorover`, `mapping_cursoroverandpressed`, `mapping_marked`, `texture_selected`, `texture_not_selected`, `texture_pressed`, `font`, `font_cursorover` | `shape`, `text`, `tip`, `focus` |
| PictureButton S 004b3a90 | as Button | `background` (a shape drawn over the button: the icon) |
| OverlayButton S 004b2280 | `onhover` | `highlight` |
| RoundIngameButton S 00622b60 | as PictureButton | `highlightGreen`, `highlightRed` |
| ComboBoxNew S 004cbf90 / DropDownMenu S 004b36e0 | `size` (item count), `string0`…`string<n>`, `dropdownoffset`, `selection` (ComboBoxNew) | `button` (with `text`), `item` |
| ComboBox S 004bfa70 | `string%u`, `data%u` | `button` |
| Slider2 S 004d04b0 | `mapping`, `mapping_cursorover` (source rectangles; `mapping` is first copied into the cursor-over one), `useText`, `textValMin`, `textValMax`, `textFormat`, `value`, `snapCount`, read in this order | `throttle`, `leftUp`, `rightDown`, `text` (loaded after `textFormat`) |
| SliderEx S 004b94c0 | `SnapCount`, `Value`, `vertical` / `horizontal` | `Throttle`, `Increase`, `Decrease` |
| Slider S 004d0950 | `throttle`, `snapcount`, `speed` | `shape`, `focus` |
| StackedSlider S 004bbc10 | `stackCount`, `value`, `mapping`, `mappingMouseOver` | |
| ListBox2 S 004b8c00 | `markSingleItem`, `itemSpacing` | `container`, `item` (row template), `slider` |
| Item S 004c78c0 | `columns` | `shape`, `focus` |
| TabControl S 004bad00 | `count`, `defaultTab`, `fadetime`, `mappingTabActive`, `mappingTabInactive` | `tab0`…, `tabButton0`… |
| ProgressBar S 004bd470 | | `bar` |
| Graph S 004c9940 | `color`, `texture`, `mappingX`, `mappingY`, `scale`, `offset`, `lineThickness`, `displayMin`, `displayMax`, `smoothingStrength`, `smoothingIterations`, `lineani`, `alphaani` | |
| AlphaFanPicture S 004cd370 | `reverse`, `invert`, `timedtexture`, `timedtexturemapping` | |
| Scroller S 004c9ca0 | `clipping`, `smoothing`, `bigchild` | |
| TextScroller S 004ca9b0 | `fadeBorder`, `fontDefault`, `fontGatter`, `fontPercent`, `spacing{Default,Gatter,Percent}{Before,After}` | |
| EditEx S 0049ebd0 | `maxLength`, `allowedChars`, `readOnly`, `isPassword`, `multiline`, `breakonedge`, `clearonesc`, `autohide`, `padding`, `mapping`, `mapping_cursorover`, `mapping_cursoroverandpressed` | `VScroll` |
| ChatSystem S 004ad150 | | `ChatOutput` (`x`, `y`, `width`, `height`, `lineSpacing`), `ChatInput`, `ChatScrollbar`, `ChatMinimize`, `ChatMaximize` (`MinHeight`, `MaxHeight`) |
| tip popup `tipDefault` S 004c6320 | `border`, `minsize` (positions) | children named `textblock`, `picture` |

[TODO] not established: the exact semantics of each Slider / Slider2 / SliderEx / ListBox2 / Graph attribute
(value ranges, snapping rule, smoothing formula). A static read of the loaders and `Update` functions listed
settles each.

### 3.2 Widget behaviour

#### 3.2.1 Button [inferred] S 004b12d0, S 004b1470, S 004aeca0, S 004aecf0, S 004af080, S 004afd10

- States: normal, hover (Focus state 1), pressed (state 2), marked. With style 12 (the only style the shipped
  in-game layouts use, written `type="12"` or left as default) the sprite's source rectangle is `mapping`,
  `mapping_cursorover`, `mapping_cursoroverandpressed` or `mapping_marked`; a state without its own rectangle
  uses `mapping` (the loader copies `mapping` into all four and then reads the overrides) [known] S 004afed0.
  The numbered styles 0..11 are fixed sprites in the atlas `uiElements0` with fixed pixel sizes, width × height
  (0: 208 × 32, 1: 152 × 22, 2: 224 × 19, 3: 152 × 20, 4 and 5: 224 × 24, 7: 32 × 208, 8: 136 × 22,
  9 and 10: 64 × 20, 11: 288 × 20 [known] S 004b0280; style 6 sets no size there), used by widgets that code
  creates (message box and requester buttons) [inferred].
- Press (left button down on an enabled button whose ancestors are enabled): `OnPressed` → press observers,
  parent notification, script event `<name>_isPressed`.
- Click (left button up while the cursor is still over the widget that took the down, or the hotkey):
  `OnClicked` → a `checkbutton` toggles `marked`; sound `uiClick0`; the parent's `OnChildClicked(button)` (which
  bubbles up the tree until a class handles it); click observers; script event `<name>_isClicked`
  ([lua-runtime.md](lua-runtime.md) §4.4). Independently the click latch (+0x119) is set; several panels poll
  it instead of overriding `OnChildClicked`.
- A double click on a button counts as a press and notifies a separate observer list [inferred] S 004b1270.
- Caption font with style 12: `font_cursorover` while hovered or pressed, else `font` (fallback `Body_Arial`);
  the attribute `font` sets both the caption font and the hover font, `font_cursorover` only the hover font
  [known] S 004b01a1 (in `Button::LoadFromXml`). The fonts, shifts and colours of the other styles (1–3 and
  7–11 `Subline_Garamond`, 4 and 5 `Subline_Garamond` left at x = 32, 0 `Body_Arial`, 6 no caption):
  [ui-toolkit.md](ui-toolkit.md) §3.4 (`LayoutCaption` S 004afa10, `Draw` S 004afd10).

#### 3.2.2 Tooltips [known] S 004b5a70, S 004b5a20, S 004b5960, S 004b5910, S 004b54b0, S 004b6030, S 004c5e30

**Widget tips** (`nUi::Tip::Update` S 004b5a70, state 1): nothing happens while the tip has neither a text nor
data. The popup opens when the owner has been hovered with a motionless cursor for more than **0.07 s**, fades in
over **0.2 s** with smoother-step easing, and is placed at the cursor every frame (S 004b54b0: the `align` corner
at the cursor, default TopRight from `Tip::ctor` S 004b6180, the align strings compared case-insensitively, the
popup clamped to the screen). Only one widget is hovered at a time: `UpdateMouseOver` S 004a1b00 enters only
visible widgets under the cursor whose `canReceiveFocus` is set, and entering a higher one makes the lower one
leave (`OnMouseEnter` S 004a3b30 sets +0x144). So the tip shown is that of the topmost focusable widget; a
`Picture` (its constructor S 004b1590 clears `canReceiveFocus`) never shows its tip, and an ancestor's tip shows
only when no focusable descendant is hit [known]. The delay test is strict (0.07f at S 007e0724 < hover time),
and the popup does not open while a mouse button is down (`Ui_IsAnyMouseButtonDown` S 004b5450); hover time is
reset to 0 while the owner is not hovered or the cursor moves. `Tip::Update` closes the popup with a 0.2 s eased
fade-out when any mouse button is down or, in state 1, when the cursor moves with the owner not hovered;
`UiHoverTooltip_Cancel` S 004b5a20 resets the hover time and closes a popup in any state but 0 and 3. A new provider (`Tip::SetProvider` S 004b5960) closes the
popup but keeps the hover time; `HidePopup` S 004b5910 closes it when the owner goes away, in state 1 only: it
starts the eased fade-out and then hides the popup at once (vtable +0x28), so no fade is seen, and it keeps the
hover time [known].

**World tip** (`Tip::SetDescriptionAndShowNow` S 004b6030, state 2): no hover delay; the popup is recreated only
when the text changes or it is not shown, never while a mouse button is down, and `ClearAnimations` runs before
`FadeIn`, so every reopening fades from 0. Presentation quirk: hovering a second soldier straight after the first
keeps the first one's tip, because the description `!Soldier` does not change (§3.4).

The default popup (template `tipDefault`, `TipListenerDefault::CreatePopup` S 004c5e30, S 004c6320) sizes a
text block of 200 × 10000 px to the text and the background to max(`minsize`, text + 2 × `border`) per axis,
then resizes the text block to the text + 1 px; with an empty description it makes no popup; one popup
object serves the world tip and every widget tip. `nMenu` adds
five rich popups selected per widget: 0 Building (`tipBuilding`: name, 4 cost slots, 4 product slots, 5 input
slots), 1 Sacrifice (`tipSacrifice`: name, description, 4 cost slots, running and research time), 2 Good
(`tipGood`: name, producing buildings, 4 ingredient slots), 3 Soldier (`tipSoldier`: name, health `cur | max`,
armour, damage `base + bonus`, rank), 4 InfoboxBuilding (`tipInfoboxBuilding`, the help button of an info box)
[known] S 0062bc70 (`Tooltip::CreateByKind`), S 00647150, S 00647740, S 00647d20, S 00648070, S 00648700. A rich
popup opens through `Tooltip::Open` S 006464c0 with a linear 0.2 s fade-in, which `Tip::Update`'s eased fade
replaces at once; the rich tips' listener slot 1 is `Generic_NoOp` S 0064b9c0 [known]. Which widgets carry which
kind: [hud-panels.md](hud-panels.md) §2.5.

#### 3.2.3 Animations [inferred] S 004c3c30, S 004c3d50, S 004d2220

Owned by the widget, ticked in its `Update`: alpha fade (linear, optional smoother-step easing), alpha pulse,
mover (between two positions), scaler, transform fade. `FadeIn(t)` = make visible + fade to 1; `FadeOut(t)` =
fade to 0, then hide. Panels use 0.2 s, hover highlights 0.1 s (constants in the callers). `Hide` does not stop
a running animation, and `ClearAnimations` acts on the widget itself, not on its children [known]
([ui-toolkit.md](ui-toolkit.md) §3.15).

#### 3.2.4 Cursor [known: `cursors.xml`; inferred S 00493190, S 00492d80, S 00492370]

`cursors.xml` (root `cursors`) holds `cursor0`, `cursor1`, … up to the first missing index. Each: `name` (image
path, e.g. `[data]\gfx\Mousecursors_MainCursor.tga`) and `hotSpot` (two ints); or `animated="true"` with `fps`
and `name0`…`name<n>` (frame duration 1 ÷ fps). Shipped: 0 main, 1 clock (8 frames, 5 fps), 2 main (selected
when the cursor is over a building or an own settler, S 005ef740), 3 build. The images become device cursors (hardware cursor).
The pending wheel delta is halved every 83 ms and zeroed below 0.0001 [known] S 00492370.

### 3.3 Input

#### 3.3.1 From the window to the tree [known] S 004913f0, S 004ab060; producers [inferred] S 00401f30

The window procedure calls `nUi::Root::HandleInputEvent(type, arg1, arg2)`:

| Type | Event | arg1 |
|---|---|---|
| 0 | mouse button down | button: 0 left, 1 right, 2 middle, 3 / 4 X buttons |
| 1 | mouse button double click | button |
| 2 | mouse button up | button |
| 3 | mouse move | x, y in pixels (stored in the cursor; the handlers get no arguments) |
| 4 | mouse wheel | notches (delta ÷ 120) |
| 5 | key down | virtual key |
| 6 | key up | virtual key |
| 7 | character (`WM_CHAR`) | character code |
| 8 | hotkey | character code |

1. Type 3 first updates the cursor position.
2. Types 0..4 go to the input-capture widget if one is set, else (like all other types) into the tree at the
   root.
3. In the tree (`Object::DispatchEvent` S 004a07a0): an invisible widget returns "not handled". A widget with
   `forwardEvents` (the constructor default) offers the event to its children from the last vector entry to
   the first, i.e. highest z-order first, and stops at the first that returns 1; if no child returned 1, or
   without `forwardEvents`, the widget's own handler for the type runs. A widget with `receiveEvents="false"`
   handles nothing.
4. A mouse-down is delivered only to a widget that is hovered (or holds the capture); a mouse-up only to the
   widget that got the matching down [inferred] S 0049ff00, S 0049ff40.
5. If nothing handled it: key down / key up are recorded in the active key table (`BaseAction::OnKeyEvent`,
   1 = down, 2 = up); **a character is dispatched a second time as type 8**, which is what triggers `hotkey`
   attributes (`Object::HandleHotkey`: hotkey equals the code, widget enabled and visible, ancestors enabled →
   click latch, return 1).

Consequences: hotkeys are character codes, so they depend on the keyboard layout and shift state (`hotkey="s"`
does not fire for `S`) [live, 2026-10-12: the letter hotkeys work neither with Caps Lock on nor with Shift held;
`HandleHotkey` S 0049ffc0 handled code 115 (`s`) and never code 83 (`S`)]; space (`btInfoMap1`) works with Shift
and Caps Lock, since the character code of space does not change [live, 2026-10-12]; a text field with focus consumes characters before they become hotkeys; Esc
and Enter work as hotkeys because `WM_CHAR` delivers 27 and 13.

#### 3.3.2 Mouse-over [inferred] S 004a1b00

Once per frame per widget whose layout was marked dirty in the last draw: if the widget is visible and the
cursor hits it (rectangle or ellipse, §2.1), it becomes the mouse-over widget unless the current one is still
hit and was drawn later (higher render id). Widgets that can receive focus get `OnMouseEnter` /
`OnMouseLeave`; a widget covered by a later-drawn focusable widget gets `OnMouseLeave`.

#### 3.3.3 In-game keys and mouse (`nMenu::Game` handlers)

While `NComm_Manager::IsGameHanging()` is true ([game-commands.md](game-commands.md) §3.1) left clicks on the
world and all character keys except `p` are swallowed [known] S 005eaae0, S 005eb180.

| Input | Effect | Evidence |
|---|---|---|
| Left click on the world (not on a HUD widget) | select what is under the cursor, then `MenuSelection::HandleClick` (§3.5) | [known] S 005eaae0 |
| Right click on the world | `MenuSelection::HandleRightClick` S 00617bc0 (§3.5) | [known] S 005eab40 |
| Middle button down (on the world or on the action panel) | close the action button panel unless a confirmation is open (`CloseUnlessConfirming` S 005f0510) | [known] S 005eab80, S 005f0720 |
| Wheel over the world | camera zoom in (positive) / out; never consumed | [inferred] S 005eb140 |
| Wheel over the minimap | minimap zoom by (15 − notches) ÷ 15 around the cursor, not closer than 1/10 of the texture | [known constants] S 005f2390, S 005f1af0 |
| `p` | pause toggle; nothing in a network match (roles 1..4), nothing while the game screen is not active or the cinematic dialog is. Pausing stores the speed scale (user profile +0x24), sets it to 0, pauses all sounds, brings the `pause` panel to the front and fades it in over 1.0 s; if a session exists and its role is not 0 the localised text of `!Pause` is first sent as chat to all. Unpausing restores the stored speed (at least 1), resumes the sounds and fades the panel out over 1.0 s | [known] S 005eb180, S 005da400, S 005ea9b0 |
| `h` | camera to the local player's home building (only in camera state 0) | [known] S 005eb180 |
| `x` | toggle the `NetInfo` dialog (slot 7), network roles 1..4 only | [known] S 005eb180 |
| Enter | chat input not focused and tutorial hidden: open the chat line. Focused: send the line (to the team while Shift is held, else to all) and close the input. Offline, the cheat strings of §8 are tested first | [inferred] S 005ec340 |
| Shift | held: team chat modifier | [inferred] S 005ec340, S 005eb230 |
| Arrow keys (0x25..0x28), Shift, Insert, Delete | `nGame::Camera::HandleKeyDown`, tried before Enter and only while no text field and no widget has focus: arrows and Shift are entered in the camera's held-key map; Delete sets the rotation rate target to 1.5 (to 0 if it is −1.5), Insert to −1.5 (to 0 if it is 1.5). All of them are consumed | [known] S 00787790, S 005ec340 |
| Any key, `1`..`4` included | closes the action button panel (0.2 s fade) unless a confirmation is open; the key still propagates, so the hotkeys still press their buttons | [known] S 005f0770 |
| Right click on the action panel | fade the confirmation box out and `ResetSelection` (S 00615d10), then return 0 (not handled): `Object::DispatchEvent` S 004a07a0 stops only at a return of 1, so the click goes on to `nMenu::Game::OnMouseButton1Down` S 005eab40 and `HandleRightClick` S 00617bc0 on the reset selection; no sound | [known] S 005f06f0 |
| Right click on an info box | `InfoBox::OnMouseButton1Down` S 00631450 (slot 15 of the event face of every box): `buttonPressed[1]` = 1, `ResetSelection` S 00615d10, return 1 (consumed); unlike the action panel it does not fade the message box | [known] S 00631450 |
| Right click in the build menu | leave build placement: `InfoBoxCreateBuilding`'s override S 00634040 sets `MenuSelection` mode 1, then runs S 00631450 | [known] S 00634040 |
| Right click on the tutorial panel | close it | [inferred] S 005f9720 |
| Esc | Camera in cinematic mode: back to standard. Otherwise the hotkey 27 of whichever visible widget has it: info box `closeButton`, the `closeButton` of statistics / settings / load / save / quest log; in the requester "No"; in the sacrifice target chooser close. Street placement (§3.5) resets the selection, so no info box is visible and Esc does not end it [inferred] | [known: data]; [inferred] S 00787790, S 005ffc70, S 00626d60 |

Hotkeys set in the shipped `menuingame.xml` [known: data]:

| Key | Widget | Function |
|---|---|---|
| `1` `2` `3` `4` | `btAction1`..`btAction4` | the action buttons of the selection (§3.7) |
| `,` / `.` | `btBack` / `btForward` | previous / next object of the selected type |
| `l` | `btSettings` | in-game settings panel |
| `s` | `btStatistics` | statistics panel |
| space | `btInfoMap1` | info-map overlay |
| `e` | `btInfoMap2` | overlay layer 0 on / off |
| `m` | `btInfoMap3` | overlay layer 1 on / off |
| `v` | `btSpeed` | cycle game speed |
| `o` | `btOptions` | options panel |
| `q` | `btQuests` | quest log |
| `t` | `btTutorial` | tutorial panel (button hidden until a page exists) |
| Esc (27) | `closeButton` of the info box and of the quest log | close |

Other files: `menuLoadSave.xml` `btLoad` 13 (Enter), `btDelete` `d`; the load/save list gives its first ten
rows the hotkeys `0`..`9` in code ('0' + index into item +0x17c) [known] S 0060da50; message box buttons get Enter / Esc / `i` by mode
(§3.8.7).

No key opens the build menu: it opens only by a left click on a buildable cell (§3.5, §3.8.10) [known].

### 3.4 The game screen: construction and HUD inventory

`nMenu::Game` is constructed once at start-up with `menuingame.xml` [known] S 005ee5d0. `LoadFromXml`
S 005ecaf0 first loads `iconconfig.xml` into `IconConfig`, reads the root attributes `chatFadeInTime`,
`chatFadeOutTime`, `zoomInTime`, then loads each fixed member from the same-named child [known for the names
listed in the code's string references; shipped values in §6]:

| Element | Class | Place (shipped) | Shows | Interaction |
|---|---|---|---|---|
| `chat` | `nUi::ChatSystem` (template `LobbyChat`) | bottom left | chat lines, input line; fades out after `chatFadeOutTime` | Enter (§3.3.3) |
| `selectionPicBG`, `selectionPicture`, `selectionBorder` | pictures | bottom left, 244 × 244 | render-to-texture preview of the selected object, or `noSelectionTexture` | |
| `btBack`, `btForward` | round buttons | on the selection frame | enabled only while a building is selected | cycle the selection to the previous / next object of the same type, re-centre |
| `btSettings` | round button | | | opens `IngameSettingsPanel` (§3.8.2) |
| `btStatistics` | round button | | | toggles `StatisticPanel` (§3.8.1) |
| `miniMap`, `miniMapBorder` | `MiniMap` | bottom right, 188 × 188, round mask | §3.8.5 | |
| `btQuests` (in `miniMapBorder`) | round button | | | toggles the quest log |
| `btInfoMap1` | round button | | | toggles info-map mode (Game +0xfff0) with a 0.2 s colour fade of the scene; in that mode the ground shows what can be built where (flag, small, medium, large building, harbour, nothing) and no overlay is hidden [live, 2026-10-12, maintainer]. The fade is the tint of the build-placement icons, which draw only while its alpha is > 0, so this button is the player's only switch for them [known] S 005eabd0, S 00688c40 ([rendering.md](rendering.md) §3.14) |
| `btInfoMap2`, `btInfoMap3` | round buttons | | | toggle overlay layers 0 and 1 of the `OverlayPanel` (§3.8.6) |
| `btSpeed` with pictures `x2`, `x3` | round button | | `x2` visible at speed 2, `x3` at speed 3 | **`0x20023` GE_Logic_SpeedUp** via `SendCycleGameSpeedCommand` |
| `btOptions` | round button | | | shows `OptionsPanel` |
| `questInfo` | `QuestInfoPanel` with `quest` lines | | active quests (§3.8.4) | |
| `cbMessages` | `nUi::DropDownMenu` (constructed in `Game::ctor` S 005ee5d0), 7 check entries | top right | message type filters (§2.10) | toggling a filter rebuilds the message list |
| `cbMenu` | `nUi::DropDownMenu`, 5 entries | top right | `!Save`, `!Load`, `!Options`, `!Main Menu`, `!Quit` | §3.8.8 |
| `goodInfoPanel` | `GoodInfoPanel`: `selector` + `goodInfo0..3` | top right, 420 × 32 | four goods of the current good set (§3.8.3) | `selector` cycles the set |
| `sacrificePanel` | `SacrificePanel` with `buff` / `antibuff` templates | | own and incoming sacrifices (§3.8.9) | click selects the building |
| `selection` | holds `actionbuttonpanel`, `actionbuttons`, `infoboxes`, `infobox<Kind>` | bottom centre | §3.5–§3.7 | |
| `overlayPanel` | `OverlayPanel` with `alphaPlane`, `overlay` | full screen | world overlays (§3.8.6) | |
| `pause` | picture with `bar` | | shown while paused, pulsing | |
| `sacrificestartedeffect` | picture | | shown at alpha 1 and faded out over 1.1 s when a sacrifice that concerns the local player starts | |
| `sacrificetargetpanel` | `SacrificeTargetPanel` with template button `entry` | at the cursor | enemy players as targets | §3.8.9 |
| `messages` | `Messages` with `last`, `up`, `down` | top left: `pos="-26 -4"` without alignment, child of the HUD root | message slots (§3.8.5) | |
| `questlog` | `QuestLog` | centre, 370 × 492 | quest list and description | |
| `tutorial` | `Tutorial` | | tutorial pages (`menu.addTutorialPage`) | `btPrev` / `btNext`, slider |
| `cutsceneDebug` | `ListBox2`, hidden | | debug list | |

In this order [known] S 005ecaf0: the seven `cbMessages` items get user data 1..7 and are all marked (every
filter on); `cbMenu` is loaded; in a network role 1..4 its item 3 is relabelled
`!Surrender and back to Lobby`; the `cbMenu` items get user data 0..n; **outside the offline role (role ≠ 0)
item 0 is removed twice, i.e. `!Save` and `!Load` leave the menu** and the remaining items keep the user data
2, 3, 4. Later an alpha pulse animation (min 0.7, max 1.0, 1 Hz) is attached to the child `text` of the pause
panel; it writes the label's text colour alpha (`Label::SetAlpha` S 004b1d90), not its opacity, and the text is
drawn with colour alpha × panel opacity (`Text::Draw` S 004b43c0, opacity +0x140), so the pause text fades with
the panel while it pulses; `SetPaused`'s `ClearAnimations` on the panel does not remove the child's pulse
[known] S 004a23a0. A root
attribute `zoomInTime` > 0 attaches a scale-in animation to the HUD root (shipped value 0: none).

`SetupHud` S 005ed700 runs on entering a match: creates overlay, sacrifice and message panels, wires the two
drop-downs, adds and activates the chat channel `Chat` (id 1), calls `MenuSelection::CreateInfoBoxes`, creates
goods bar, quest lines, minimap, quest log and tutorial [inferred]. `DestroyHudWidgets` S 005ea650 undoes it
on leaving and deletes the panels at +0xcc70..+0xcc84.

The parents `SetupHud` gives the fixed members [known: disassembly of S 005ed700]: `selectionBorder` →
`selectionPicture`; `btBack`, `btForward`, `btSettings`, `btStatistics` → `selectionBorder` (005ee2c6..005ee322;
`selectionBorder`'s `<deployment anchor="center"/>` without offset or size is dock 5, which takes the parent's
rectangle, §3.1.5, so it covers `selectionPicture` [inferred]); `miniMapBorder` →
`miniMap`; `btInfoMap1`, `btInfoMap2`, `btInfoMap3`, `btSpeed`, `btOptions` → `miniMapBorder`; the pause panel
(`pause`) → the desktop (Game +0x20); every other member → the HUD root (Game +0x968). So the `pos` values of
these buttons in `menuingame.xml` are relative to the selection frame and the minimap frame [inferred: §3.1.5,
positions relative to the parent]. `btQuests` is an XML child of `miniMapBorder` and stands at the same
`pos="128 199"` as `btOptions`. `Game::OnEnter` S 005eed00 runs `SetupHud` (which attaches `btOptions`) before
the XML load creates `btQuests`, so `btQuests` gets the higher sort key and is drawn on top of `btOptions`
[known] S 004a56d0, S 004a1370; no layout sets a z-order. [TODO] not established: whether code hides one of the two
(a read of the writers of their visibility settles it).

**World hover tooltip** [inferred] S 005efd60 for the gate; [known] S 005ef740 for the rules: only when the
world is not in state 3, the cursor is visible, the hovered cell is explored by the local player and no dialog has
focus. Priority: picked object: a building of any owner (no owner test), a settler only if it is the
local player's own, which also ends the search (property name; carrier: `!Carrier`; soldier: provider kind 3,
the soldier tooltip, with the description `!Soldier`); a flag on the cell: `!Flag`; a building's text is the
localised name plus `NN%` productivity (clamped at 0), or `name (Under construction)` / `name (Construction
stopped)` by the construction's paused byte (+0x78); a resource sign is the temporary type-1 doodad of the cell
(`FindDoodadAtCell(cell, 1)`); else the resource or deposit name of the cell. Cursor 2 over a picked building
(any owner) or own settler, else cursor 0. The text goes through `Tip::SetDescriptionAndShowNow` (§3.2.2). Ships
[known] S 005ef740: a ship of the local
player under the mouse (S 00787a30) shows its name key; another player's ship shows nothing, and the resource sign
is then not looked for.

**Network hang notice** [inferred] S 005ebf90: in a network session, while not paused, the hang reason text of
the NComm manager is drawn at the screen centre in `Subline_Garamond` on a `uiTip` background.

### 3.5 Clicks on the world: `MenuSelection` [known] S 00617910, S 00617bc0, S 006176d0, S 00617770, S 00617800

**What a left click selects** (`nGame::Cursor::SelectAtCursor` S 00788370, only while the cursor is active)
[known]: the game selection is cleared, then the first hit wins:

1. a flag of the local player on the cursor cell (`FindLocalPlayerFlagAtCell` S 00787bf0) → Flag;
2. the entity under the mouse (`PickVisibleEntityAtMouse` S 00787cc0) → Building: the ray tests the map-object
   layer's objects of kinds 6 and 8 in list order (box, then the object's own ray test, slot 9), the first hit
   ends the search, and it counts only when it is kind 6 (a building) and its slot 1 (+4) returns 0, so a ship
   route buoy (kind 8) in front of a building hides it; it drops a building whose anchor
   cell is unexplored, testing the exploration of the building's owner (`+8`), not the local player's
   [known] S 00787cc0 ([camera-input-cutscenes.md](camera-input-cutscenes.md), click selection; [rendering.md](rendering.md)
   §3.7);
3. a building on or next to the cursor cell (`PickSelectableEntityAtCell` → `NVillage::System::
   FindBuildingAtOrAdjacentCell` S 00558990): grid bit 0x1 = a building is anchored on the cell; else grid bit
   0x100 = a neighbour in directions 0..2 has bit 0x1 and holds a large type (size mask bit 2 set, bit 1
   clear) → Building;
4. a ship under the mouse (S 00787a30) → Ship; a ship route under the mouse (S 00787b00) → ShipRoute;
5. a street on the cell that has both flags and belongs to the local player → Street.

**The ray picks** [known]: the map-object pick (`Pick_MapObjectAtScreenPos` S 0068c920) walks one object list in its
order and takes the first object of kind 6 (`S2CG::Building`, its constructor S 006ac810 writes 6) or kind 8 (a
`RouteBuoy` S 006dbb90, map-object type `routeBuoy` → kind 8 at S 0068f4b2) whose box (slot 2, +8) the ray meets
and whose own ray test (slot 9, +0x24) then passes; a buoy's own
ray test, vftable slot 9, is `return true` (S 0041eca0). Removing any map object can move a later building or buoy
earlier in that list (S 0068cff0), which decides only which one wins when the ray meets both. A route's start buoy
is placed by S 00683040; its end buoy only once both harbours are set. The ship pick (`PickShip` S 00697db0) takes
the nearest ship whose bounding sphere the ray enters at a distance ≥ 0 and whose mesh it crosses (nearest by the
sphere's entry distance, `Ray::IntersectSphere` S 006ec570 with the table root `Math_FastSqrt`; a tangent ray
misses; the mesh test runs only for a ship nearer than the best so far; [engine-core.md](engine-core.md)): the sphere is
the mean of the scaled vertices, placed at the ship's ground point and not turned (S 006a5020); the mesh test
(S 0076ff90 → S 006ec8a0) does not test the distance along the ray.

Nothing hit → nothing selected. `MenuSelection` then derives the selection kind (§3.6).

**Left click** (`HandleClick`). First the clicked cell is copied from the game cursor (system +0x24 / +0x28)
into +0x8c / +0x90. Then by mode:

- **Mode 1 (normal).** `RefreshFromGameSelection(refreshPanel = true)`: push the selection to the scene's
  highlight (`PushSelectionToScene` S 00615bb0, so the scene marks the ship itself), build the target id from the
  game selection (`MenuSelection_MakeUniqueFromState` S 00615a10: a ship that sails a route selects the route; a
  ship on its slipway selects its site, and this changes the game's selection), resolve its render instance, update
  the preview picture,
  compute the selection kind (§3.6) and call `SetSelectionKind`. If afterwards no info box is active and no
  object is selected, the cell's build flags for the local player are read
  (`nGame::Cursor::GetBuildFlagsAtCell`): if `flags & 0x1f != 0` (some building fits) → `BeginBuildPlacement`:
  store the flags in the create-building box (+0x1638) and its "direct" flag (+0x1634 = 1), mode = 2, selection
  kind 0xc, and mark the cell in the scene (marker x = cellX × 4, +2 on odd rows, y = cellY × 4, size 4). Else
  if `flags == 0x20` (only a flag fits) → `SelectCell`: selection kind 0x13 and the same marker. The result is
  "an info box is open".
- **Mode 2 (build placement).** If the create-building box has a chosen building type (+0x1630 ≠ −1):
  `SendPlaceBuildingAtCursorCell(type)` → **`0x20002` GE_Building_Create**; consumed. Otherwise mode = 1, the
  selection is reset and the click is processed again as a mode-1 click.
- **Mode 3 (street placement).** With no street mode active: consumed. Else
  `StreetBuildMode::HandleClick(cell)` ([game-commands.md](game-commands.md) §3.4 `0x20006` / `0x20008`) and
  its result: 0 → sound `uiClick0`, close the action panel unless confirming; 1 → sound `uiCancel`; 2 → reset
  the selection and `SelectCell` (selection kind 0x12 because the mode is still 3); 3 → `Cancel` (mode 1,
  `0x20007` if a planned path exists, reset). Always consumed.
- **Mode 4.** mode = 1, reset, close the action panel unless confirming; then processed again as mode 1.
- **Mode 0.** Reset, then processed again with the mode unchanged; no writer of mode 0 was found (the
  constructor sets 1) [inferred].

**Right click** (`HandleRightClick`): mode 2 → if the create-building box is not visible, show it and return
"consumed"; else mode = 1 and reset. Mode 3 → with no street mode active: consumed, nothing else; else the test
S 0078b180 on the active street mode: `planner0` (street mode +0x10) `IsConstructionActive() &&
CanComplete()` [known] S 0078b180 (read as: the planned street can already be completed). True →
keep mode 3, false → `Cancel` and consumed. Mode 4 → mode = 1, reset. Any other mode → reset. The
paths that do not return "consumed" then close the action panel unless confirming and return "not consumed".

A right click in street placement therefore never steps back a segment: in the one state where it keeps mode 3
(test true), `MenuSelection::Update` (below), which requires the test to be false, ends the mode itself
[known] S 00617bc0, S 006163f0.

**Street placement start** (`BeginStreetBuild` S 00615e30, action 9): mode = 3,
`nGame::System::BeginStreetBuildMode(position of the selected flag)`, selection reset. `MenuSelection::Update`
S 006163f0 [known] stays in mode 3 only while all of these hold: a street mode exists, its point vector
(+0x24 / +0x28, 8-byte entries) is not empty, `ai::game::StreetBuildMode::IsValid` is true, the test S 0078b180 above is
false and its byte +0x39 (`cancelled`) is 0; otherwise it calls `Cancel` (not silent).

**Cancel** (S 006162e0) [known]: plays `uiCancel` unless silent, mode = 1, calls `StreetBuildMode::Cancel` with
`deferred` = `silent` if a street mode with a non-empty point vector and byte +0x39 = 0 exists, then resets the
selection.

**The street build mode** `ai::game::StreetBuildMode` (0x3c bytes) [known] S 0078b850, S 0078b4a0,
S 0078b1d0, S 0078b220, S 0078be80; the two planners and their point recorders are in
[world-objects-rendering.md](world-objects-rendering.md) §3.6:

- Fields: waypoint vector +0x20 (begin +0x24, end +0x28, 8-byte cells), `planner0` +0x10, `planner1` +0x14,
  `pendingRemove` +0x38, `cancelled` +0x39, `valid` +0x3a.
- `Begin(startCell)` S 0078b850: clears `pendingRemove` and `cancelled`, sets `valid`, pushes the start cell,
  switches the cursor to placement mode (true, 2) with the start cell as anchor.
- `IsValid` S 0078b4a0: the start waypoint still holds a flag of the player (`NNet::System::FindFlagAt`); the
  player's shared planner (`g_pGameSystem` per-player table), if its construction is active, has a valid path
  (`IsPathValid`); and `valid` is set.
- `Cancel(deferred)` S 0078b1d0: switches the cursor's placement mode off and sets `cancelled`. Deferred: sets
  `pendingRemove` and nothing else. Otherwise, with one waypoint the mode is ended without a command
  (`EndStreetBuildMode`); with more it sends **`0x20007`** (`SendCancelStreetCommand`).
- `PlanSegment(planner, target, fullSearch, ref)` S 0078b220, the plan of one click. The first segment
  (`fullSearch`): water (kind 2) is a candidate when the start waypoint is an unlinked shore flag of the player
  (`GameQuery::IsPlayerUnlinkedShoreFlagAt` S 0052daa0) and `CanStreetStepTo(start, target, player, no path)`
  passes ([streets-transport.md](streets-transport.md) §3.2: the start flag and the target are tested as one
  step, so a land shore target one hex from the start flag fails the distance rule, although a water search
  through water cells could reach it); land (kind 0) when
  `CanStreetPassCell(target)` passes (the land search tests every entered cell, the target included, with the
  same function, `AStarStreet::CanSearch` S 00776180). With both, both are planned and land wins only if its path is strictly
  shorter (a failed water plan counts as endless). Neither → 1. The chosen kind is planned
  (`BuildStreet`, `ExtendTo`); a failed water plan is retried as land from the first waypoint, also when
`CanStreetPassCell(target)` failed; result 0 when a
  path was found, else 1. Later segments: 4 when the planner can already complete, else `ExtendTo(target)`
  and 1 when the planner's state (+8) is 1 (no route), else 0 [known].
- `OnPlannerCommand` S 0078be80, after a street command of the player: when the player's shared planner is
  active and its path valid, `RebuildPath` S 0078b510 rebuilds `points0` and the preview is refreshed;
  otherwise the mode is ended (`EndStreetBuildMode`).

**Street actions in mode 3** (`ExecuteAction` S 00623730) [known]: action 29 (create flag) sends `0x20004` at
the remembered cell and then, in mode 3, calls `Cancel(silent = true)`: no sound, and the street mode is only
marked (`deferred`), so no `0x20007` is sent. Action 28 (destroy street) in mode 3 sends nothing itself and
calls `Cancel(false)`: `uiCancel`, and `0x20007` when the street has more than one waypoint. Outside mode 3,
action 28 sends the street removal.

**Reset** (`ResetSelection` S 00615d10) [known]: hide the active box, target id = −1, kind = −1, hide the
confirmation box and close the action panel unless confirming, set the four action buttons to action 0, show
`noSelectionTexture` / `noSelectionMapping` in the preview picture if a texture name is set, clear the cell
marker in the scene (cell −1, −1), cell = −1. The game's own `Selection` is not changed here: the call through
`g_pScene` vtable +0x60 only clears the scene's cell. The confirmation box is hidden by `HideConfirmationBox`
S 005f0610.

**Reset and refresh** (`ResetAndRefresh(refreshPanel)` S 00617db0) [known]: `ResetSelection`, then, only when
the menu selection is in mode 1 (+0x88), `RefreshFromGameSelection(refreshPanel, focusCell = 0)` S 00617800,
which recomputes the selection kind from the game selection and opens its box (the action panel only with
`refreshPanel`); the camera does not move. The info boxes call it
when their object stops fitting the box (§3.6), the sacrifice bar after selecting a building (§3.8.9), the attack
slider after sending an attack (§3.7).

**Cycling** (`btBack` / `btForward`): `Game::OnButtonClick` S 005eb850 calls S 005354c0 (step back) for `btBack`
and `Selection::CycleSameTypeBuilding` S 00535300 for `btForward` (when the game selection is a building, it selects
the next building of the same owner and type), then `Selection::GetMapPosition` and
`RefreshFromGameSelection(0, focusCell = 1)` S 00617800, so the camera is focused on the new object [known]. It
checks no menu-selection mode: the buttons cycle from the game selection in every mode, also in modes 2 and 3.

The game selection is held apart from the menu selection: the sacrifice bar's `SacrificePanel::OnItemClicked`
S 00624bd0 sets the game selection, then calls `ResetAndRefresh(true)`, then sets the cell, in that order [known].
Its other readers are the cycling above and `RemoveBuilding` S 00559db0 (at S 00559e00, through S 005350e0 and
S 00535220), which clears a selection showing the removed building ([village-buildings.md](village-buildings.md) §3.5).

### 3.6 Selection kinds, info boxes and their action buttons

`MenuSelection_ComputeSelectionKind` S 006156a0 [known]. "Own" = owner index equals the local player's.

| Game selection | Condition (first match) | Kind |
|---|---|---|
| None | | −1 |
| Building, property `territoryBuilding` set | owner is an enemy and the building's fight is active with the local player as attacker | 7 |
| | owner is an enemy | 6 |
| | not own | −1 |
| | own, not a depot, upgrade running (byte at `*(building+0x104)+8`) | 4 |
| | own, not a depot, no construction pending | 3 |
| Building (others, and territory buildings not caught above) | not own | −1 |
| | construction pending (`+0x70 > 0` or `+0x74 > 0` on the object at building +0x44) | 4 |
| | property byte +0xb0 set (catapult) | 0xe |
| | property `casern` set and not `depot` | 2 |
| | working mode (+0x80) = 9 (sacrifice site) | 8 if the building's sacrifice is idle, else 9 |
| | mine: property `size` (+0x3c) = 8 (`SizeMine`) and working mode = 6 (S 0055bf60) | 0xb, or 0xf if the owner test below is true |
| | property has goods (`HasGoods(0)`) | 0xa, or 0xb if `stockLimit` (+0x84) < 1 |
| | `plantingDeposit` (+0xd4) names a deposit whose `good` (+0x3c) ≠ −1 (S 00553040) | 0xb |
| | `depot` set | 0xd |
| | else | 0x10, or 0x11 if working mode = 0xb |
| Flag | own | 5, else −1 |
| Settler | a soldier that is in a fight with a building reference: the selection becomes that building and is evaluated again; any other settler | −1 |
| Street | own | 0x12, else −1 |
| Ship | own | 1, else −1 |
| ShipRoute | the route's building or its second reference belongs to the local player | 0, else −1 |

Owner test of the mine row (`ai::player::Player::IsStateNotDefault` S 005be330) [known]: with the owner's `kind` (+0x08)
equal to 1 it is `level ≠ 3`, otherwise `level ≠ 0`, where `level` is the player field +0xec, the match's
start-resources / difficulty level 0..3 ([players-victory.md](players-victory.md) §2). So a mine opens the
`Mine` box (0xf) unless that level is 0 (3 for a kind-1 owner), in which case it opens the plain production
box (0xb). The same pair (size 8, working mode 6, player level) gates the miners' food rule
([properties-data.md](properties-data.md), sacrifice flag 7). The building fields used above: owner +0x08,
property +0x0c, construction object +0x44, production +0x48, fight reference at `*(building+0xe0)+0x70`,
upgrade object +0x104, sacrifice +0x128; property bytes `depot` +0x54, `casern` +0xf1, `territoryBuilding`
+0xf5 [known] S 006156a0.

Info boxes created by `CreateInfoBoxes` S 006167b0 [known: key → constructor] and the actions `SetSelectionKind`
S 00616f40 [known] puts on buttons 1..4 (action numbers of [game-commands.md](game-commands.md) §5.1):

| Kind | Info box class (XML element) | Button 1 | Button 2 | Button 3 | Button 4 |
|---|---|---|---|---|---|
| 0 | `InfoBoxShipRoute` (`infoboxShipRoute`) | 1 start expedition | 2 stop expedition | 3 finish expedition | |
| 1 | `InfoBoxShip` (`infoboxShip`) | | | | |

Availability of the route actions (`RefreshAvailability` S 00623da0) [known]: action 1 takes the code of
`GetAssignShipBlockReason` S 005ba970 (1..4, [navy.md](navy.md) §3.10); action 2 is available while the player has
an active expedition on the route, else code 1; action 3 takes `GetFoundColonyBlockReason` S 005baa50 (codes 1, 2).
They read the game's selection, so a route reached by clicking its ship works the same.

| Kind | Info box class (XML element) | Button 1 | Button 2 | Button 3 | Button 4 |
|---|---|---|---|---|---|
| 2 | `InfoBoxCasern` (`infoboxCasern`) | 4 destroy | 15 / 16 training sword on / off | 17 / 18 training bow on / off | 19 / 20 upgrading on / off |
| 3 | `InfoBoxTerritoryBuilding` (`infoboxTerritoryBuilding`) | 4 destroy | 5 upgrade | 13 set to swordsmen if the military component's kind (+0x68) is 1, else 14 set to bowmen | |
| 4 | `InfoBoxConstruction` (`infoboxConstruction`) | 4 destroy | 6 pause construction (7 resume, swapped by the button) | 30 cancel upgrade, only when an upgrade is running | |
| 5 | `InfoBoxFlag` (`infoboxFlag`) | 8 destroy flag | 9 build street | | |
| 6 | none | 11 attack; the attack slider is shown and bound to the building | | | |
| 7 | `InfoBoxFight` (`infoboxFight`) | 12 retreat | | | |
| 8 | `InfoBoxSacrificeSelect` (`infoboxSacrificeSelect`) | 4 destroy | 23 abort sacrifice | 22 start sacrifice | 21 abort research |
| 9 | `InfoBoxSacrificeRunning` (`infoboxSacrificeRunning`) | 4 | 23 | 22 | 21 |
| 0xa, 0xb, 0xf | `InfoBoxProduction` (`infoboxProduction`; 0xf is named `Mine`: `infoboxMine`) | 4 destroy | 24 pause production if enabled, else 25 resume | | |
| 0xc | `InfoBoxCreateBuilding` (`infoboxCreateBuilding`) | 29 create flag, only if the clicked cell is inside the map | | | |
| 0xd | `InfoBoxDepot` (`infoboxDepot`) | 4 destroy | | | |
| 0xe | `InfoBoxCatapult` (`infoboxCatapult`) | 4 destroy | 26 pause catapult if its target cell is inside the map, else 27 resume | | |
| 0x10, 0x11 | `InfoBoxBuildingDefault` (`infoboxBuildingDefault`) | 4 destroy; 0x11 also: 24 / 25 on button 2 | | | |
| 0x12 | `InfoBoxStreet` (`infoboxStreet`) | 28 destroy street | 29 create flag | | |
| 0x13 | `InfoBoxCreateFlag` (`infoboxCreateFlag`) | 29 create flag | | | |
| 0x14 | `InfoBoxSacrificePanelSelect` | 23 | 22 | 21 | |

`SetSelectionKind` in order: all four buttons to action 0 (hidden) and the attack slider hidden; the per-kind
assignment; if a building is selected and the script override (`menu.allowActions`,
[game-commands.md](game-commands.md) §5.1) has an entry for its building type, every button whose action is
neither 0 nor 4 is made unavailable with the override's failure code; if the box for the kind differs from the active one, the old box
is hidden and the new one initialised, refreshed and shown (a kind without a box leaves none active); the box's
`focusedActionButton` (XML, −1 = none) selects which button the cursor is warped to; with `refreshPanel` the
action panel is opened (fade 0.2 s) and positioned at the cursor (§3.7).

**Info box frame** (`nMenu::InfoBox`, a `Picture`) [inferred] S 00631820, S 00631310, S 00631a50, S 00631bc0:
children `headline` (label), `closeButton`, `helpButton` (its tip is the rich tooltip kind 4 for the selected
object's type, or a fixed help text); attributes `focusedActionButton`, `zoomTime` (default 0.3), `zoomInAngle`
/ `zoomOutAngle` (+40 / −40), `moveInTime` / `moveOutTime` (0.3), `fadeInTime` / `fadeOutTime` (0.2). The
defaults are the constructor's [known] S 00631820 (disassembly 006318cd..00631938: 0.3 the float at S 007e2a70,
0.2 at S 007d7090, +40 at S 007e2a4c, −40 at S 007f4ef0; obj +0x4c4 zoomTime, +0x4c8 / +0x4cc the angles, +0x4d0 /
+0x4d4 fadeIn / fadeOut, +0x4d8 / +0x4dc moveIn / moveOut), and `LoadFromXml` S 00631310 reads each attribute
with `XmlDoc::GetAttrFloat` S 006e7bd0, which keeps the field when the attribute is absent, so a layout that leaves
one out keeps the default (the shipped `<infoboxes>` gives the same values). The element
`infoboxes` is loaded into every box first (common frame), then the box's own element. Show: move in from the
deployment offset, fade in, scale in; hide (`InfoBox::Hide` S 00631bc0): z-order −1 (the old key is saved; `Object::SetSortKey` S 004a0ad0 re-sorts the
parent's children ascending by +0x178 and they draw first to last, so the hidden box draws behind its siblings,
[ui-toolkit.md](ui-toolkit.md) §4), move out (an
`AnimationMover` with easing 1), fade out, scale out. A click on `closeButton` resets the selection
(`InfoBox::OnChildClicked` S 006314b0 → `ResetSelection`) [known]. Every box's per-frame update closes the box
(selection reset and refresh) when the selected object is gone.

**Box objects and texts** [known] S 006167b0, S 00616f40, S 006312f0: every info box is one object per kind for the
whole game. `SetSelectionKind` re-initialises a box only when the kind's box changes: it calls `Hide` (vtable
+0x8c) on the old box and `UpdateDescription` (+0x94), `Update` (+0x90) and `Show` (+0x88) on the new one (for
example the running-sacrifice box, vtable S 007f5824: `Show` S 00631a50, `Update` S 00636d80,
`UpdateDescription` S 00636950, `UpdateHelpText` (+0x98) S 006316e0). A text that a box does not rewrite
therefore keeps what that box showed last, or the layout's text if the box never wrote one. The headline is
rewritten every frame from the selected building's name (`SetHeadlineFromBuilding` S 006312f0) by the updates
of BuildingDefault S 00631d80, Catapult S 006329f0, Depot S 00633b60, Production S 00635c50, TerritoryBuilding
S 0063a4b0 and Casern S 0063b590. The base `UpdateHelpText` S 006316e0 serves 15 box classes; CreateBuilding
S 00634a90 (its filter +0x1638: 0x10 gives the anchor help, 0x08 the mine help), Flag S 00638a20, Ship S 0063c4e0 and
ShipRoute S 0063d1f0 override it.

**Keep rules** [known]: besides the "object gone" test, some updates call `ResetAndRefresh` (§3.5) when the
object no longer fits the box, so the box of the new kind opens: Construction S 006397e0 keeps the box only while
remainingA > 0, remainingB > 0 or an upgrade is active (`*(building +0x104) +8`), so a finished site switches
to its building's box; TerritoryBuilding S 0063a4b0 resets when an upgrade becomes active; Catapult S 006329f0
when the property's catapult byte (+0xb0) is clear; Production S 00635c50 when the type has neither
`HasGoods(0)` nor a planting deposit.

What each box shows, and which commands its own controls send:

| Box | Content | Controls → command |
|---|---|---|
| ShipRoute S 0063cb70 (ctor S 0063d280, binder S 0063c8a0) | the local player's first ship on the route, or `!NO SHIP` without one; state `!LOADING` / `!UNLOADING` while lying still in ship state 2 / 3, empty while lying still in any other state, `!EXPEDITION` / `!TRANSPORT` while moving; 128 × 128 ship preview, drawn once per ship (`RenderShipPreview` S 0068cb60); three parts, each with its own box width: transport (tabs goods and settlers, 14 buttons each; width 518), sea attack (`militarySoldiers`, 6 buttons) and expedition (3 goods buttons filled by S 00649900, plus the crew button), both 418 = the box's width − `tabControl` + `expCont` (or `militaryCont`) | good buttons close the action panel and focus the camera on the unit or package (`GoodButton::OnClicked` S 0062fe50 → `nMenu_FocusCameraOnUnique` S 00648de0); commands only through action buttons 1..3 |
| Ship S 0063c100 (ctor S 0063c360, binder S 0063c090) | ship name; two tabs, goods and settlers aboard, 20 counting buttons each | none |
| Casern S 0063b590, S 0063abc0 (ctor S 0063aec0, vtable S 007f63bc; `BindChildControls` S 0063a8c0) | for the tribe of the local player (`FindLocalPlayer`): 2 × 3 soldier buttons (`compStd0..2`, `compBow0..2`, levels from `SoldierLevelRange` S 005703d0 ascending, 0..max): stock, queued, accept flag; `Player::IsLocked(3)` is called but its result is dropped, so no lock state is shown; recruit costs per class (`costStd`, `costBow`, shared `costBoth0/1` as `have/need`, need = the raw `stockLimit` (+0x84) × the cost amount; `costBoth1` hidden unless there are two shared goods); upgrade cost with the text input count / (`stockLimit` × amount). Parents [known] S 0063aec0: `contCompany`, `contCosts` and `contUpgrade` on the box, each with its text; the six company `GoodButton`s under `contCompany` (vtable +8 = `GoodButton::Create` S 00630370), `costStd`, `costBow`, `costBoth0`, `costBoth1` under `contCosts` and `upgrade` under `contUpgrade`; these five are plain `PictureButton`s (kind 0xc), not good buttons. A sixth `PictureButton` at +0xc7f0 is constructed but never created or bound | the button poll S 0063abc0: click on a soldier button → **`0x2001E` GE_Depot_ToggleFlags_UID** (building, that soldier good) |
| TerritoryBuilding S 0063a4b0 (ctor S 0063a050, binding S 00639d30) | soldier slots: `settlerList`, 12 buttons under `contSoldiers` (`GoodList::InitWithItemCount` S 0064ab20, vtable +0x84), capacity scaled by health, filled with the garrison (`SetFromSoldiers` S 00649c00, `InitFromSettler` S 0062fed0; an empty slot shows `iconconfig.xml` `<Goods><EmptyGood>`); border-distance icon (3 classes, `<BorderDist><dist0..2>`); health bar and `"%.0f%%"` (100.0 at S 007d8ff0). The soldier count line `!IS BEING ATTACKED BY %u SOLDIERS` never shows: its format (`soldierCountFormat`, +0x271c) is written only by the constructor (empty) and the destructor [known]; [inferred] it was meant to count the attackers (the list `Military +0x30`, read by S 006312d0). Presentation bug | none (action buttons) |
| Construction S 006397e0 (ctor S 00639210) | progress = ((1 − a) + (1 − b)) ÷ 2 of the two remaining-work fractions of the effective construction (+0x70, +0x74; the +0x74 term is added first) as bar and `N%` (the float progress × 100.0 through `"%.0f%%"`: the VS2005 `__fptostr` S 00710d2c rounds half away from zero, and the product has float precision because `Fpu_SetDefaultControlWord` S 0057b9b0 sets `_PC_24` every in-game frame [known]); for a ship site (kind-1 ship reference) the two fractions are the ship's +0x4c and +0x48, +0x4c first; building icon; missing and delivered material, one button per unit (`SetFromBuildingConstruction` S 0064b240 = `SetFromCountMapAndPendingGoods(construction stock, depot pending, no filter)`, list below) in 12 buttons (`InitWithItemCount(12, contMaterial)` at S 0063974b, counts off); the builder as one entry built like a worker button (S 00639a0f..S 00639ac7, from the builder reference +0x30 / +0x34, unique at +0x40 / +0x44 of the effective construction). Parents set by the constructor: `iconHammers` under `progress`, `textInProgress` under `picBuilding`, `textWorkers` and `picWorker` under `contWorkers`, `listMaterial` and `textMaterial` under `contMaterial`. [TODO] the kind-5 branch (a selected ship under construction) | none |
| Flag S 00638b10 (ctor S 00638850) | goods lying at the flag: the constructor makes 12 buttons (`GoodList::InitWithItemCount` S 0064ab20) and switches `aggregate` off; one button per package lying on the flag (package +0x70 `placedOnFlag`), stacks 0..5 in order and within a stack in the push order of its package vector ([streets-transport.md](streets-transport.md) §2.4), unsorted (the list's `sort` is 0 and the layout sets none) (`SetFromFlagGoods` S 0064a9b0; layout `GoodList::LayoutItems` S 00649370); an empty slot shows `iconconfig.xml` `<Goods><EmptyGood>` (`536 712 40 40`; `GoodButton::Clear` S 006309b0, name string S 007f13bc); help text `!Infobox_Flag_Help` or `!Infobox_Harbor_Help` (flag with a harbour) | none |
| Fight S 006382e0 (ctor S 00637d60, `BindChildControls` S 00637a10, `Show` S 00637cc0, `PulseSoldierCount` S 00638180) | local player's name (`Player_GetDisplayName`) `VS` the defender's name; per side `invisibleL` / `invisibleR` holding the name label and a `container` with `soldier0` / `soldier1` (swords, bows), `textVS` on the box; the defenders show `?` while the fight's start countdown runs; the cached counts start at −1 in the constructor and an unknown side caches −1; a changed count pulses (the `flash` widget and an `AnimationScaler` 1.4 → 1.0 over 0.5 s with easing 1, about the centre); `Update` hides both tactic buttons every frame. The box closes with `ResetAndRefresh` once its fight is gone or inactive. Parents [known] S 00637d60: `tacticButtons[side]` (+0xdb0 + side × 0x500) under `invisiblePics[side]` (+0x17b0 + side × 0x288) through vtable +0x90; `flash[2 × side + k]` under `soldier[2 × side + k]` through the flash's vtable +8 (S 0064b760, `Picture::Create(…, parent)`). During the pulse a soldier button's caption is not re-laid: its `Text` position is set only by `Button::LayoutCaption` S 004afa10 at creation, and `AnimationScaler::ApplyScale` S 004d2390 moves the button's top-left corner (relPos = base + half × (1 − s)), so the caption shifts with that corner by size × (1 − s) ÷ 2; the flash re-centres at every step (`SetSize` S 004bca30 notifies the children, whose relayout re-applies the template's centre alignment) | none (action 12) |
| SacrificeSelect S 00637340 | up to 2 × 8 `sacrificebutton`s (`sacrifice_<row>_<col>`): the player's available sacrifices; row 1 = those whose `researchDuration` is > 0, row 0 the others | click → **`0x20024` GE_Sacrifice_Order** if the sacrifice can be ordered, else **`0x20027` GE_Sacrifice_StartResearch** if research is possible, else nothing (S 0062f390) |
| SacrificeRunning S 00636d80 (ctor S 006369e0) | the sacrifice, its cost goods in 3 buttons (`InitWithItemCount(3, contGoods)` at S 00636cab; counts blanked while running), remaining time `m:ss`, progress bar, description. The headline is written in three cases only: the ordered sacrifice can start (`CheckCanStart` S 00560f20 == 0, via S 00561040) → `!SACRIFICE READY`; state 1 (running, S 005352e0) → `!SACRIFICE` and the time; state 3 (ordered, S 00560c10) → `!PREPARING SACRIFICE`. In state 0 (spent) and state 2 (ready, S 00560c20) it keeps its last text, which is the layout's `xxx` while the box has never written one. The bar is written only in the `!SACRIFICE` branch; a bar never written shows its layout (full) width ([ui-toolkit.md](ui-toolkit.md) §3.13). Parents [known] S 006369e0: `contSacrifice`, `contGoods`, `contDesc` and `time` on the box; `sacrifice` (`SacrificeButton::Create` S 0062f8e0) and `arrow` under `contSacrifice`; `goods` (`GoodList::InitWithItemCount` S 0064ab20) under `contGoods`; `descLong` under `contDesc`; `progress` under the `time` label (`ProgressBar` vtable +8, S 004bd220), so its deployment is relative to that label | none (action buttons) |
| Production / Mine S 00635c50 (ctor S 00635710) | input goods incl. those in the production slots, one button per unit (list below) in 12 buttons (`entryGoods`, sort on, counts off), of which the first `stockLimit` × (number of input entries) are used: an either-group cost is expanded into one entry per alternative with the summed amount (`GoodAmountList` `RemoveAmount` S 005525b0 swap-pop, `AddList` S 00552bb0, `AddAmount` S 00552aa0), so `goldBav` (food × 2 of {pretzel 1, ham 1}) gives the entries pretzel 2 and ham 2, and a good is "lacking" by `LacksGood` S 00649050; the worker; up to two products with the good tooltip (kind 2): `product0` / `product1` are `AlphaFanPicture`s (`Create` S 004cdbe0: texture `timedGoodButton.png`, 50 % black, clipping on; `invert` set by the constructor) whose progress is 1, or the worker's work progress while `Production::ProducesGoods` S 00565550 (`HasGoods(0)` and not a catapult) and `IsWorkerInWorkCycle` S 00565740 (the worker's virtual; `Worker::IsInWorkCycle` S 0065c7d0: states 0x1d, 0x1e, 0x20, 0x21, 0x24, 0x35; progress `Worker::GetWorkProgress` S 0065ce80); `product1` shows the first product again when slot 0's amount is above 1 (S 00636384 reads `GetGoods(0)` stored at S 00635d15: `farmBav`, `brauhaus`, …), else the second product, else it is hidden; productivity bar and percent: the building's entry of `Statistics::GetProductivity` S 005373b0, which returns −1.0 for a building without an entry, the percent text truncated (`__ftol2`) after the product is stored as a float (0.57 → 57 %); members' parents: `entryGoods` → `contEntry`, `worker` → `contWorker`, `product0/1` → `contProduct`, `productivity` → `percent`, `miniIcon` → `productivity`; buildings without inputs hide the input column, use the `noEntryPercentPos` / `noEntryPercentOffset` layout and the box width `width − contWorker.x + contEntry.x` (computed in `LoadFromXml` S 006350f0 at S 00635312) | none (action buttons) |
| CreateBuilding | §3.8.10 | **`0x20002`** |
| Depot S 00633b60, S 00632e40 (ctor S 00633460, `LoadFromXml` S 00632d50) | tab 0 (`goods`, 22 buttons = 0x16, cleared by `ClearItems` S 00648f90 and then filled from the first free button): the tribe's goods of type `Ware` only, in tribe order (`GoodList::SetFromGoodIdVector` S 0064a150 with type filter 0), each with its stock count and `+N` = `NTransport::NeedGoods::CountRequestedByAssignment` over the requests of the depot component (building +0x3c, its +0x44) for that good (`CountRequestedByAssignment(needGoods, good, true)` S 0064e280: the requests for the good whose package reference +0x18 / +0x1c is valid, i.e. a package is on its way [known]); the entry of the tribe's second-carrier cost good instead shows `+N` = the second carriers referenced by the building (+0x108); arrow = accept flag; tab 1 (its tab button shown only for buildings whose property bytes `depot` +0x54, `casern` +0xf1 and `territoryBuilding` +0xf5 are all set, i.e. the headquarters; otherwise hidden and page 0 selected): the lists `soldiers0` / `soldiers1` (3 buttons each, counts on) with `textSoldiers0/1` under them, one entry per level of `SoldierLevelRange` ascending, count = the store's stock plus the garrison soldiers of that level and kind that are present (`CountSoldiersOfLevelAndKind` S 00566380, fights not counted), `+N` = the settlers of that soldier good referenced by the building, arrow = the good's accept flag | click on any good button that carries a good id, the soldier lists included → **`0x2001E`** (building, good id) (`OnChildClicked` S 00632e40) |
| Catapult S 006329f0 (ctor S 00632500, `LoadFromXml` S 00632060) | preview of the target, the building referenced by `Catapult +0x08` (not the aim cell), and its owner; stones in stock (input and output units) and on the way (`stones`, 4 buttons per the layout `count`, no sort, no counts); the worker; health bar and `N%` = trunc(ratio × 100.0) computed in double without a float store (0.57 → 56 %); parents as in the production box (`health` → `percent`). The bound preview keeps the target's nine-slice border: `Shape::BindTexture` S 004a86d0 resets only the texture, the mapping (the whole picture) and the size, and `Shape::DrawSliced` S 004a8f70 draws the corners at their source size from the picture and tiles the edges and centre (the layout's `target` shape has `border=16` and no `stretch`) [known] | none (action buttons) |
| BuildingDefault S 00631d80 (ctor S 00631ed0) | headline and the worker; `contWorker` on the box, `textWorker` and `worker` (`GoodButton::Create` S 00630370) under `contWorker` [known] S 00631ed0 | none |
| Street, CreateFlag, SacrificePanelSelect | frame only | none |

**Flash** (`nMenu::Flash`, the fight box's `flash0` / `flash1`; template `goodFlashIcon` S 00637c00, S 0064b740,
S 0064b760, S 0064b7b0, S 0064b880) [known]: `Create` defaults min 0, max 1, `scalePerFrame` 0.99
(S 007dee78), overridden by the layout's `minScale`, `maxScale`, `scalePerFrame`; `StartPulse` sets the pulse
to 1 and shows it; every drawn frame scale = (max − min) × pulse + min, then pulse ×= `scalePerFrame`, and the
flash hides once the pulse is below 0.0001. The decay is per frame, so it depends on the frame rate
(presentation only). The "first child" the loader and `Update` read is the flash's own deployment (the list at
object +0x12c, `GetFrontDeployment` S 00446cf0): `LoadFromXml` keeps its layout size as the base, and `Update`
sets the flash's size to scale × base and re-applies its own `alignx` / `aligny` in the parent (`ApplyAlignment`
S 004bc0b0). The flash widget itself grows and shrinks, its bounds with it; `goodFlashIcon` (centred, 62 × 54)
therefore pulses about its centre [known].

**Sacrifice buttons** (`SacrificeButton::SetSacrifice` S 0062f4e0) [known]: the button's enabled state, its
question mark and the rules of its fans; icon and tooltip are keyed by the sacrifice's `sf_setName`. The fan
(`AlphaFanPicture`) takes a value 0..1024 in 5 segments. The running time is shown as
`trunc(remaining ÷ 10.0)` seconds while `remaining` ≤ 100000. Enabled (disassembly 0062f756..0062f7b6): always
when the button's `focus.canReceiveFocus` (+0x100) is off; else when `CanOrder` S 00561380, else when
`CanStartResearch` S 00561130, else, when the definition's dependency list (+0x8c) is non-empty,
`SacrificeDependencies::IsSet` S 00662970, else when the sacrifice is regenerating. Fans (from 0062f7b8, reverse
0): research running at this building for this sacrifice → the research fan at the research progress
(S 0065fb40), alpha `questionmarkAlpha`; else regenerating and the button enabled (+0xe4) with every ancestor
enabled (`IsFlagE4SetInHierarchy` S 0042e330) → the regeneration progress (S 006626a0); else state 1 (running,
S 005352e0) → the progress of the building's running sacrifice (S 00660090), reversed. When either fan is
visible the icon shape's disabled colour is set to 1, so the icon is not greyed (0062f878). `MenuSelection::ResetAndRefresh` S 00617db0
recomputes the selection kind. The question mark is shown when the sacrifice needs research (S 00556510), is
not researched (S 00662660) and its research does not run at this building (S 00561210 → S 0065fb80); it is
attached last, over the icon (`Create` S 0062f8e0), at the alpha `questionmarkalpha` (`LoadFromXml` S 0062f310,
slot 5 of the vtable at +8, S 007f47e4, so `this` = object + 8; constructor default 0.5, S 0062f9c0). Like every
shape it draws its disabled colour (the `Shape` default 0.4667) while the button or an ancestor is disabled
([ui-toolkit.md](ui-toolkit.md) §3.3), so on a greyed button the question mark is greyed too; the fans' quads
use a white vertex colour × alpha and never the disabled colour (S 004cd4a0) [known]. Button offsets [known]:
`alphafan` +0x518, `alphafanResearch` +0x810, `questionmark` +0xb08, `questionmarkAlpha` +0xd90.
The fans [known]: the constructor builds them with `AlphaFanPicture::ctor` S 004ce490 (mapping 0 0 128 128);
`Create` (slot 2, S 004cdbe0) sets the texture `timedGoodButton.png` and clipping, and `LoadFromXml` S 004cd370
replaces it only with a `timedtexture` attribute (the shipped `alphafan` has none; `alphafanResearch` sets
`ui_buffs 4 268 41 41`). Their `<deployment anchor="center"/>` is dock 5, the same as Fill: the fan takes the
button's whole rectangle and follows it on every resize (`Deployment::LoadFromXml` S 004bcb80, `ApplyDock`
S 004bc570). `BuildFanVertices` S 004cd4a0 centres the fan in that rectangle with radius max(width, height) in
pixels, so it covers the corners; the centre is the widget position + 0.5 × size (disassembly 004cd5c1..004cd5de:
the larger of the two full sizes, not the half). The texture coordinate per unit of direction is
(half the mapping in pixels) ÷ (texture size ÷ 2) on each axis (004cd79e..004cd7ef), so the texture is scaled
with the radius max(w, h) on both axes; on a non-square widget it is not stretched per axis [known]. The button's
state pictures lie over the icon: the `PictureButton` draw S 004b3a60
renders the icon shape (+0x468, set by `SetSacrifice`) and then `Button::Draw` S 004afd10 the button's own shape
(+0x198), whose mapping `Button::UpdateMapping` S 004af080 picks per state (style 0xc: marked > pressed > hovered >
normal). The fans and the question mark are child objects, drawn after the whole draw slot (state shape and
caption included) by `Object::RenderRecursive` S 004a1370, so they lie over the state picture [known].

Good buttons everywhere: a click on one that carries a unit or package id closes the action panel (unless confirming) and
focuses the camera on that unit or package [inferred] S 0062fe50.

**Good lists** (`nMenu::GoodList`, buttons `nMenu::GoodButton`) [known]:

- Defaults (`GoodList::ctor` S 006494d0): `sort` 0, `aggregate` 1, `append` 0. The XML attributes `collapse`
  (→ `aggregate`), `sort`, `append` and `count` override them (`GoodList::LoadFromXml` S 0064b270, at
  S 0064b2bd); the construction and production box constructors switch `aggregate` off. `aggregate` is the
  "show count" argument every button gets.
  `append` is stored at +0x1ae (start at the first free button). `count` → `SetItemCount` S 00649630; a box
  constructor makes its buttons with `InitWithItemCount(n, parent)`. `LayoutItems` S 00649370 places item k at
  (offsetX + column × spreadX, offsetY + row × spreadY), wrapping after `itemsPerLine`, only when
  `itemsPerLine` > 0; otherwise each button loads its own element `item<i>` after the shared `items` element and
  keeps that position. Buttons that `SetItemCount` adds later are bare (constructor and attach, no `items`
  element applied); with its layout argument set it runs `LayoutItems` again [known] S 00649630.
- `GoodList::SetEntries` S 00649100: sorts the entries when `sort` is set, starts at the first free button when
  `append` is set, writes entry `i` into the next button and stops when the buttons run out; the remaining
  buttons are cleared. It never adds buttons: entries beyond the list's `count` are not shown. `ClearItems`
  S 00648f90 clears every button.
- Sort order (`qsort` with `nMenu_GoodList_CompareEntries` S 00648d10): good id (signed), then amount
  ascending (a "not available" entry of amount 0 first), then the arrow flag, off first. The CRT's `_qsort`
  S 006f7130 (VS2005) is not stable but deterministic: median-of-three, a partition that skips elements equal to
  the pivot, an explicit stack that takes the smaller part first, and partitions of 8 or fewer elements sorted by
  `shortsort` S 006f70a0, a selection sort that moves the first maximum to the end and so reverses runs of
  equal entries. The order of ties follows from the code and the input order [known]. Entry layout: +0x10 / +0x14 unique id, +0x18 amount,
  +0x1c max, +0x20 extra, +0x24 arrow, +0x25 moving, +0x28 not available, +0x29 working.
- Worker buttons (`GoodButton::SetFromBuildingWorker` S 006308b0): max 1; moving = the worker's virtual
  vtable +0x24 (picture slot 9), working = vtable +0x28 (slot 10); without a settler the entry is "not
  available".
- `SetFromCountMapAndPendingGoods` S 0064a3b0 (construction, production and catapult boxes): first one entry
  of amount 1 per unit of every good in the count map; then one entry per open need: amount 1 with the arrow
  and the serving package's unique id (the button can focus it) when a package serves the need, else amount 0
  with the "not available" mark.
- Count text (`GoodButton::SetEntry` S 00630530), only with "show count": `%u/%u` (amount / max) when a
  maximum is set, coloured `full` when amount = max, else `empty`; else `%u` in `normal`, or `empty` when the
  amount is below 1; with an extra amount `%u%s%u` with `+` for a positive extra, `empty` when amount + extra
  is below 1. Colours from the constructor S 0062fff0: full (0, 1, 0, 1), empty (1, 0, 0, 1), normal
  (1, 0.81, 0.62, 1). The six indicator pictures (arrow, not available, upgrading, moving, fighting, working)
  follow the entry's flags; the arrow hides "not available" and "fighting" hides "moving"; a non-negative
  progress shows the health bar. The tooltip is kind 2 (good) or, for kind 3 with a valid unit, the soldier
  tooltip.

### 3.7 Action buttons [known] S 006243c0, S 005f05c0; [inferred] S 00623600, S 00623470, S 00624430, S 005f0880

The panel (`actionbuttonpanel`) holds `btAction1..4` (templates `bt_action1..4`, hotkeys `1`..`4`), the
`attackslider` and a `messagebox`.

- **Assigning an action** (`SetAction`): action 0 hides the button. Otherwise the highlight colour is red for
  actions {2, 4, 8, 12, 21, 23, 28, 30} and green for the others; the icon rectangle comes from a table built
  from the XML element `actionbuttons` (attributes `start`, `size`, `spacing`, `mouseoveroffset`: shipped
  `576 288`, `44 45`, `48 48`, `0 96`): rectangle x = start.x + column × spacing.x, y = start.y + row ×
  spacing.y, w × h = size, with the fixed (column, row) per action below; the tooltip is the action's command
  name from the table `g_IngameCommandNames` S 0087fb10 (31 strings, one per action 0..30; read by `SetAction`
  and `SetAvailability` S 00623470) [known]; availability is evaluated. Icon and tooltip are rewritten only
  when the action number changes.
  The table is built in the `MenuSelection` constructor and again at the end of its `LoadFromXml`
  [known] S 00622f40, S 006164f0. [TODO] not established: how `mouseoveroffset` is applied (it is only stored
  by S 00624470; a read of the readers of `g_ActionButtonMouseOverOffset` settles it).

  | Action | col, row | Action | col, row | Action | col, row | Action | col, row |
  |---|---|---|---|---|---|---|---|
  | 0 | 8, 4 | 8 | 8, 1 | 16 | 4, 4 | 24 | 6, 1 |
  | 1 | 5, 2 | 9 | 2, 2 | 17 | 5, 4 | 25 | 5, 1 |
  | 2 | 6, 2 | 10 | 1, 2 | 18 | 6, 4 | 26 | 0, 3 |
  | 3 | 7, 2 | 11 | 3, 3 | 19 | 7, 4 | 27 | 1, 3 |
  | 4 | 8, 2 | 12 | 2, 3 | 20 | 8, 4 | 28 | 3, 2 |
  | 5 | 8, 3 | 13 | 5, −1 | 21 | 7, 6 | 29 | 7, 1 |
  | 6 | 1, 0 | 14 | 6, −1 | 22 | 8, 5 | 30 | 7, 3 |
  | 7 | 0, 0 | 15 | 3, 4 | 23 | 8, 6 | | |

- **Availability** (`RefreshAvailability`, rules in [game-commands.md](game-commands.md) §5.1): an unavailable
  button is disabled and marked, and its tooltip is the failure text for the action's failure code
  [known] S 00623470. On a change of state `SetAvailability` sets the shape's disabled colour to white
  (1, 1, 1, 1) and calls `SetMarked(!enabled)`, so an unavailable button shows its `mapping_marked` picture
  (`roundingamebutton`: `ui_ingame` 530 284 44 45 [known: data]) at full brightness rather than greyed. The texts are the `tag`
  attributes of the elements `<ActionName>_<code>` under `actionfailurecodes` in the XML (the element is a
  child of `btAction4` in the shipped file, read once into a global table) [inferred] S 00624470. The shipped
  list also has `Action_Flag_BuildWaterStreet_0..2` (`!ConnectWaterStreetFailure_None` / `_isHarbor` /
  `_noWaterNear`), but no action number carries that name: a leftover of a removed water-street action
  [known: data and the 31-entry action tables].
- **Order of a click** [known] `ActionButton::OnClick` S 006243c0: a confirm action sets the pending flag and
  opens the confirmation box; any other action runs `ExecuteAction` S 00623730 first. Then
  `RoundIngameButton::OnClick` S 00622d10 → `Button::OnClicked` S 004b12d0 plays `uiClick0` and calls the panel's
  `OnChildClicked` S 005f0550, which fades the panel out unless the confirmation box is visible and unanswered.
  So a direct action closes the panel right after it executes, and a confirm action leaves it open. A hotkey
  goes through `ActionButton::OnKeyDown` S 00623d20 → `ExecuteAction` without `OnChildClicked`.
- **Click or hotkey**: actions {4, 8, 12, 21, 23, 28} (destroy building, destroy flag, retreat, abort research,
  abort sacrifice, destroy street) set a pending flag and open the confirmation box: title `!Execute Action`,
  text `!Are you sure you want to execute this action?`, message box mode 1 (Yes / No, §3.8.7) [known]
  `ShowExecuteConfirmation` S 005f0c80; when the box reports result 0 (Yes) the action is executed once. All
  other actions execute at once (`ExecuteAction` S 00623730, [game-commands.md](game-commands.md) §5.1). Note
  that the red-highlight set and the confirmation set differ (2 and 30 are red without confirmation) [known].
  `ExecuteAction` repeats two tests for itself [known] S 00623730: action 4 sends `0x20003` only for a building
  of the local player whose `Building::CanDestroy` S 0055cdc0 holds (`GetDestroyBlockReason` S 0055cd40 is 0),
  and otherwise does nothing; actions 28 and 29 in street placement behave as in §3.5.
- **Child order** [known] `ActionButtonPanel::Create` S 005f0620: the attack slider is created first, then
  `btAction1..4`, so the children are in that order (creation order is child order, `InitAndAttachToParent`
  S 004a56d0) and the buttons are offered events before the slider; the message box is created under the panel's
  parent. The load order of `LoadFromXml` S 005f0f00 (buttons, slider, message box) does not change it.
- **Icon and marked picture** [known] S 004b3a60: the action icon is the mapping of the background shape (+0x480 =
  shape +0x468 + 0x18, written by `SetAction` S 00623600), drawn first; `Button::Draw` S 004afd10 then draws the
  state shape +0x198 (normal, cursor-over or marked mapping) over it.
- **Panel picture** [known] `LayoutVisibleButtons` S 005f0df0: the panel's shape (`actionbuttonpanel`, mapping
  `0 496 96 131` in `ui_ingame3`) is one of four strips side by side in the atlas with 4, 3, 2 and 1 circles; a
  jump table (S 005f0ef0) sets its x to 0x120, 0xc0, 0x60 or 0 for 1, 2, 3 or 4 visible buttons. With no button
  visible the panel is hidden. The visible buttons fill the circles from `btAction1` on, without gaps.
- **Placement** (`PositionAtCursor` S 005f0880): the panel is centred on the cursor, clamped to the screen; with
  the "smart cursor" option (user profile byte +0x31, [camera-input-cutscenes.md](camera-input-cutscenes.md)
  §2.7) the mouse is warped to the centre of the focused button (`WarpToWidgetCenter` S 004927b0), enabled or
  not [known]. The focused button is the active info box's `focusedActionButton`, which comes from the layout
  only: the `InfoBox` constructor sets −1 (S 00631a15), only `InfoBox::LoadFromXml` (S 0063136e) writes it, it is
  read only at S 006175ec and S 0061763d, and `SetSelectionKind` S 00616f40 passes it on [known]. In the shipped
  `menuingame.xml` (common frame `<infoboxes>`: −1) [known: data]: the flag box 1 (build street), the street
  box 1 (create flag), `infoboxCreateBuilding` 0 (create flag), the create-flag box 0; the other boxes none.
- **Opening and closing** [known] S 005f04e0, S 005f0510, S 005f0550: `Open` hides the message box, clears the
  panel's animations and fades it in over 0.2 s (linear). Any key, a middle click, the cursor entering the world,
  a click on a good button, and a click on any child of the panel (`OnChildClicked` S 005f0550, which fades
  before it forwards the click to the base handler S 004a00c0) run `CloseUnlessConfirming` S 005f0510: clear
  the animations and fade out in 0.2 s (linear), unless the confirmation box is visible and unanswered
  (result −1).
- **Attack slider** (kind 6; `nMenu::AttackSlider`, ctor S 005ebd30, a `Picture` holding the `Slider2` named
  `slider` and the labels `textL` / `textR`) [known] S 00624ac0, S 00624ab0, S 006247a0, S 00624700,
  S 00616f40: `SetSelectionKind` hides it on every call and, for kind 6, binds it to the selected building,
  updates its labels and shows it. `UpdateLabels` S 006247a0 writes `textL` = swordsmen and `textR` = bowmen of
  `Military_CountAttackersByKind(target, local player, false, max(GetMinAttackerFraction, value), out, true)`
  S 00575fd0 ([military.md](military.md) §3.5 for the count); an earlier call with the fraction 1.0 is never
  read. The labels change only in `LoadFromXml`, `OnSliderChanged` and at kind 6, never per frame, and the
  slider's value is never reset (the layout's `value` 0.5 at first). Action 11 runs `ExecuteAttack`
  S 00624700: fraction = max(`Military_GetMinAttackerFraction`, value), **`0x2000D` GE_Military_Attack**
  through `SendStartAttack` S 00781a00, which takes the game selection's building, not the slider's own target
  ([game-commands.md](game-commands.md) §3.4), then `ResetAndRefresh(0)`.
- **Attack and retreat availability** [known] S 00623da0, S 00623730: action 11 is available when
  `GetAttackAvailability` S 005759f0 is 0 (`Military_IsAttackAvailable` S 00575b50); otherwise its code selects
  the failure text `Action_Attack_Begin_<code>`. Action 12 (retreat) is available when the box's fight is
  valid, active and in phase 0 (`Military_IsField8A0Zero` S 00570d10); the failure code is the phase. It
  confirms (above) and sends `0x2000E`. `Military_IsField24Zero` S 00570700 tests the fight's start countdown
  (+0x24) for 0.
- **Unused**: `iconconfig.xml` `<Tactic>` `tacticIcon0..2` are named only by `IconConfig`'s constructor
  S 00612b50, destructor S 00612990 and `LoadFromXml` S 00611320; nothing draws them [known].

### 3.8 Panels

#### 3.8.1 Statistics (`menuStatistics.xml`, `nMenu::StatisticPanel`) [inferred] S 006225d0, S 00621910; [known] S 00621820

Created on first use, toggled by `btStatistics`; fade 0.2 s. Four tabs. Content:

- **Players**: `playerInfo0..5`: name in player colour, state text `textFriendly` (colour `colGreen`) or
  `textInWar` (`colRed`), avatar; a player not yet met by the local player shows `textEmpty`. Each row's button
  shows / hides that player's curve.
  **Six rows are a hard limit of the panel**: the constructor creates exactly six row objects and gives row
  `i` the player slot `i` (0..5); there is no paging and no remapping [known] S 00621d20, and the click handler
  searches the same six rows [known] S 00621910. The simulation has eight player slots and the graph handles
  all eight; the curve switch of every slot starts on [known] S 00642f00. So the players in slots 6 and 7 have
  a curve (under the same conditions as the others) but no row, and their curves cannot be switched off
  [inferred]. Details: [hud-panels.md](hud-panels.md) §3.1.4, §3.1.6.
- **Player graph** (`graphPlayers`, `graph0..7`): one curve per player for the category chosen in the combo box
  `filter`: `!Regions`, `!Buildings`, `!Settlers`, `!Goods`, `!Military Strength`, `!Coin Amount`,
  `!Productivity`, `!Defeated Enemies` [known: data; index → per-player history vector `category × 0x10`,
  [players-victory.md](players-victory.md)]. Points: x = i ÷ (n − 1), y = value ÷ max; a curve is drawn only for
  an active player known to the viewer.
- **Inventory**: `goods` (22 rows) and `soldiers` (6 rows): icon, stock in depots (red when 0), signed change
  outside (red when negative); clicking a row adds / removes that good's curve in `graphInventory` (curve
  colour from `IconConfig`, alpha 0.9).
- **Buildings**: one `building` row per building type of the tribe in a grid (`bldOffset`, `bldSpread`,
  `numBldPerLine` = `26 22`, `128 128`, 7): icon, name, count and count under construction (row alpha 0.4 when
  both are 0), average productivity or average health as a bar; a click selects one building of that type and
  moves the camera there. A tribe-specific child `techtree<Tribe>` is shown.
- **Time axis**: slider `timeScaling` (0..1) per graph: range in game minutes =
  `floor(round(v × 900 + 60) ÷ 6) × 6`, i.e. 60..960 in steps of 6; seven x labels from "now − range" to "now",
  two y labels (max ÷ 2, max).

No command is sent. When the panel was opened from the game-ended popup with "end", closing it leaves the match
(§3.9).

#### 3.8.2 In-game settings (`menuIngameSettings.xml`, `nMenu::IngameSettingsPanel`) [inferred] S 00621480, S 00620970, S 00641ab0, S 006412f0

Opened by `btSettings`. Two tabs. A new panel object is made at every opening (`OpenIngameSettingsPanel`
S 005eaf00; ctor S 00620df0, `OnXmlLoaded` S 00621480): the layout's `defaultTab`, the first goods group
selected (below), the
sliders set from the player's values and a fresh copy of the priority list; it fades in over 0.2 s (linear) and
closes with a 0.2 s linear fade-out (S 0060e390) [known]. The layout has no reset buttons.

- **Military** (`contSettings`): sliders `sliderNear`, `sliderMedium`, `sliderFar` (garrison share by border
  distance) and `sliderDefense`, initialised from the local player's values.
- **Transport priority**: 19 slots `goodprioslot<N>` in rank order with the good's icon; an unused rank shows
  `texturePrioNotUsed` / `mappingPrioNotUsed` and is disabled. Click a slot to pick it up (`dragslot` follows
  the cursor), click another slot to move the good to that rank (local copy of the priority list); a click
  elsewhere drops it back, cancelling plays `uiCancel`.
- **`btConfirm`** sends, in this order, the values of `sliderNear`, `sliderMedium`, `sliderFar`
  (**`0x20013`**, **`0x20014`**, **`0x20015`** GE_Military_Set{Near,Medium,Far}DistanceAllocationFactor), the
  whole priority list (**`0x20021` GE_Good_MoveTransportPriority**) and `sliderDefense` (**`0x20011`
  GE_Military_SetDefenseFactor**), whether or not they changed; then the panel closes. Nothing is sent before
  the confirm [known] S 00620970; ids per sender from [game-commands.md](game-commands.md) §3.4.
- **Diplomacy view** (`MilitaryPanel`, rows `player0..5`; bound by `MilitaryPanel::LoadFromXml` S 00641d00,
  refilled every frame by S 00641a60 → `UpdatePlayerRow` S 00641ab0) [known]: a row is shown when the player
  is active, `IsShownInPlayerLists` S 005be7a0, of `kind` ≠ 0 and spotted by the local player; enemy =
  `IsEnemyOf` S 005be280 of the row's player towards the local player. Ally or enemy shape, the name
  (`Player_GetDisplayName` S 00645da0: on a campaign map, type 1 / 0x65, the name key is translated; the
  offline own row falls back to `!Player`, the last case of S 00645ca0; else the raw name) in the player's UI
  colour (the table S 0087f8c8 of `iconconfig.xml` `<PlayerColors>`, §3.8.6), `!FRIENDLY` (RGB 0, 255, 138)
  or `!ENEMY` (255, 144, 0) with the alpha kept, avatar (S 0060eac0); else `lbEmpty` (`!Empty`). Display
  only: the game has no diplomacy command ([game-commands.md](game-commands.md) §3.4 lists none) [inferred].
- **Tabs** [known] S 00621480: `OnXmlLoaded` attaches the `MilitaryPanel` to `tab0` (it loads `contSettings`) and
  the `GoodArrangementPanel` to `tab1` (it loads `contGoodSpreading`).
- **Goods distribution** (tab 1, `contGoodSpreading`, `GoodArrangementPanel`): up to 10 `waregroup<N>` buttons,
  one per good that more than one building type consumes; selecting one shows up to 6 pairs
  `building<N>` + `slider<N>` with the current weights. The pairs are filled only on a group click (S 006413c0,
  sliders set without notification), not per frame. The panel is created anew at every opening
  (`OpenIngameSettingsPanel` S 005eaf00, ctor S 00620df0), and `GoodArrangementPanel::LoadFromXml` S 006415f0 ends
  with `RefreshWaregroupButtons` S 006410e0 and `HandleWaregroupClick(waregroupButton0)` S 00641570, so the first
  group is marked and its pairs shown at once [known]. With every group button hidden, button 0 (good id 0) is
  still clicked. Moving a slider sends **`0x2001F` GE_Good_SetModifier**
  (good id, entry index, new weight) at once, without confirm.

#### 3.8.3 Goods bar (`goodInfoPanel`) [inferred] S 006460d0, S 006287b0, S 0062a820

Four `goodInfo<N>` entries: icon, text `amount / delta` with the delta signed, red (`textColRed`) when
`amount < −delta` (the stock would run out), else green; tooltip kind 2. The four goods come from the current
**good set** of the local player's tribe; `selector` advances to the tribe's next set cyclically. Sets are
defined in `goodinfosets.xml` (§6). The XML attribute `good` (a hex good id) presets an entry.

#### 3.8.4 Quests [inferred] S 00627650, S 00627ee0, S 005ea100, S 005e9f40

- **Quest lines** (`questInfo`, seven `quest` children in the shipped file): while the game is not paused,
  quests that are active, not in state 2 and started more than 10 ticks ago are bound to the lines in start
  order. A line shows the localised title and, for a quest with progress, ` (<progress>)` with the parts before
  and after `/` coloured `finishedColor` / `unfinishedColor`. After `inactiveDelay` without hovering the line
  fades to `inactiveOpacity` over 1 s. That fade (`nMenu::AnimationAlphaFade`, ctor S 006278b0, `Update`
  S 006278f0, target the line alpha +0x37c, duration 1.0) lerps v = from + (to − from) × t and stores the
  smoother-step of the lerped value, ((6v − 15)v + 10)v³, not of t: a fade to 0.4 ends at 0.31744, and the fade
  back starts there [known]. The line's opacity fade-in (`nUi_FadeInObject` S 004c3d50 from `SetQuestIndex`
  S 00627510) is the toolkit's linear fade. `inactiveOpacity` is read with `GetAttrFloat` S 006e7bd0 (CRT
  `atof` S 006f5820) and `inactiveDelay` with `GetAttrInt` S 006e7b20 (`atol`), each only when the attribute is
  present (a present, non-numeric value gives 0); the constructor S 00627ab0 sets the defaults 0.4 and 300. It
  leaves the colours `color` +0x33c, `finishedColor` +0x34c and `unfinishedColor` +0x35c unset, and the line comes
  from `operator new` (not zeroed, `QuestInfoPanel::LoadFromXml` S 00627c30), so a layout without them has
  undefined colours; the shipped template `l_quest` sets all three [known]. The line text is built as `<color><right>title` plus, with progress,
  ` (<flag-24 colour>before/<color>/<finishedColor>after<color>)` with the colour tags of
  [ui-toolkit.md](ui-toolkit.md) §3.2, and its alpha is the line's alpha × the widget opacity [known] S 00627ee0,
  `AppendColorTag` S 00627e30; a quest is bound once start + 10 < now [known] S 00627650. The line is drawn by the
  rich-text layout, which top-aligns it at its rectangle's y (`RichTextLayout::Render` S 004e3d20, align Left), not
  centred on a point as a plain `Text` (ui-toolkit §3.1) [known].
- **Quest log** (`questlog`): list of all visible quests, main quests first, then by the tick at which the quest
  was filled in (+0x54) (`QuestLog::RebuildList` S 005ea100 [known]; `std::_Sort` S 005e9bc0 with a comparator
  that tests only kind 0 against any other kind, then +0x54 unsigned: up to 32 entries it is an insertion sort,
  which is stable over the slot-ordered input, so ties stay in slot order; above 32 the partition / heap path
  orders ties differently [known]), with header rows `!MAIN QUESTS` /
  `!SUB QUESTS`. A row (`QuestLog_FillQuestItem` S 005e9c90 [known]): red text for a failed quest, green for a
  finished one, with the icon `iconFailed` (template `t_x`) or `iconFinished` (template `t_v`) [known: data];
  selecting a row shows the text of the key `<title key>_desc`. The list is rebuilt only when the log is shown
  (vtable slot 34, S 005ea3a0) and once by its `LoadFromXml`; while it is visible `QuestLog::Update` S 005e9ef0
  re-fills each existing row every frame (`RefreshQuestItem` S 005e9e80: colour and icons) without adding,
  removing or reordering rows, so a quest that appears while the log is open is listed only at the next opening
  [known]. The child `Difficulty<N>` matching the player's
  difficulty (0..3, Player +0xec [known] S 005ea3e0) is shown. Rows are `ListBox2` items (S 004b8880); the
  normal picture of `questitemtemplate`, `ui_menus 10 10 11 11`, is an opaque navy cell with a light left column,
  drawn stretched [known: data]. The log fades in and out over 0.2 s (S 0060e350, S 0060e390) and a right click
  closes it like any dialog (S 0060e440: not while one of its animations, such as that fade, still runs; the
  click is then returned unhandled, [hud-panels.md](hud-panels.md) §3.3).
- **Quest log button** `btQuests` (template `bt_bag`, its background the `!` icon at `912 624 44 45`, hotkey `q`
  [known: data]): `Game::OnButtonClick` S 005eb850 hides the quest log (Game +0xb328) when it is visible, else
  shows it [known]. No code that changes the button's look on a quest event was found [inferred].

#### 3.8.5 Messages and minimap

**Messages** [inferred] S 005f86a0, S 005f8b90, S 005f75a0; constants [known] S 005f86a0

- Eight slot rows are created, seven are filled: the filtered list (types whose filter is on) from the scroll
  index (`Messages::Refresh` S 005f8b90: nine filter bytes, a window of 7 rows, stick to the newest). A row =
  type icon button (§2.10) + label (title, or `title (extra)`), read messages grey (200, 200, 200) and pressed,
  unread white.
- Row geometry [known] `InitAndAttachToParent` S 005f8fa0, run by `SetupHud` on every match entry: the first row
  at (36, 36) px, the rows 28 px apart; the icon button a 32 × 32 `ui_ingame` shape from (8, 344) until
  `SetupSlot` sets the type icon; the label at (+32, +12) from the row's origin in `Subline_Garamond`. The row
  text (`SetupSlot` S 005f75a0) is `GetText(text)`, followed by `" (" + GetText(arg) + ")"` when `arg` is not
  empty [known]. The same call makes the `up`, `down` and `last` buttons in code at (10, 35), (10, 60) and
  (10, 85) px with the tooltips `!Scroll up.`, `!Scroll down.`, `!Jump to last one.` [known]; the shipped
  layout's children give `up` (160, 20) and `down` (160, 234), 19 × 16, and hide `last` [known: data].
  [TODO] not established: which of the two positions the screen shows (a read of whether the layout is applied
  to the buttons after `InitAndAttachToParent` settles it).
- Row alpha: `alphaMin + (1 − alphaMin) × timeRemaining ÷ 600` with the record's float at +0x18, which starts
  at 600.0 for a new message (§2.10): a new row is opaque and fades towards `alphaMin` (shipped 0.4) as the
  message's time runs down [known] S 005f86a0; the rate at which `timeRemaining` falls is in
  [players-victory.md](players-victory.md) §2.7.
- Left click on a row: mark read and move the camera to the message's cell. Right click: delete the message,
  sound `uiRemove`. Tooltip `!Left Click for go to, right click for delete.`
- `up` / `down`: scroll with 0.05 s auto-repeat; `last`: jump to the newest and stick to it. A new message while
  the list is visible plays the sound of §2.10 and, if it has a cell, adds the minimap symbol of §2.10.
- A listener callback from the player's message store pulses the row of a new message: only the type icon
  scales from `scaleMax` to 1 in `scaleTime` (shipped 6 → 1 over 0.5 s) about its centre
  (`PulseSlotForMessage` S 005f8c30); the label has no size (made by `Label::CreateWithText` S 004b2040), so the
  same animation leaves it unchanged and its text appears at once [known].

**Minimap** (`nMenu::MiniMap`) [inferred] S 005f3dd0, S 005f3fc0, S 005f4390, S 005f5bb0, S 005f2130

- Base image: the scene renders the map into a 512 × 512 target; a copy masked by the local player's explored
  cells is the widget's texture. That texture has no alpha channel, so unexplored land is opaque black inside
  the round mask [known] ([hud-panels.md](hud-panels.md) §3.7). Refreshed after a device reset and on a delayed
  request.
- Overlay 0 (256 × 256, half resolution): territory. Each cell in the owner's colour (`Player::GetColorEntry`,
  the table the military flags use, [hud-panels.md](hud-panels.md) §3.7); interior cells alpha
  0x99, border cells (grid-state bit 0x20) opaque; unexplored cells transparent.
- Overlay 1: objects. Building 0xffaaaaaa; a building whose property byte +0xf5 is set 0xffffffff or 0xffff8888
  (by property +0x54); a sacrifice site (working mode 9) `sacrifices_color`; a chest `chests_color`; nothing
  on unexplored cells. Both overlays are rebuilt when a building is created or removed or a sacrifice starts.
- Symbols (on top): the local player's finished ships at their movement cell (symbol 3), fights of the local player at
  their target building's anchor cell (4), other fights at half alpha unless both sides are enemies of the local player,
  the camera frustum as a clipped trapezoid (if `renderfrustrum`), and the script / message symbols with their lifetime
  ([hud-panels.md](hud-panels.md) §3.7).
- Input: left click or left drag moves the camera to the map point (y flipped; `FocusCameraOnCursor` S 005f1520 from the
  press S 005f18e0 and from every move S 005f2130 while button 0 is held); dragging with the middle mouse button (button
  index 2, `WM_MBUTTONDOWN` S 00401f30; its pressed byte is Event face +0x11 + 2, read by S 005f2130) [known] pans the
  minimap view inside the texture; the wheel zooms (§3.3.3). Every recapture of the base image resets the zoom and the pan
  ([hud-panels.md](hud-panels.md) §3.7) [inferred].
- Symbol definitions: `mapSymbols.xml` (§6).

#### 3.8.6 World overlays (`overlayPanel`) [known] S 0061fc60, S 0061f980, S 0061f770, S 0061f830, S 0063d870, S 006403c0, S 0063dd30

**Which overlays exist** [known], created and destroyed from the simulation's callbacks to the game screen:

| Overlay (template) | Created by | Destroyed by | Category | Owner filter |
|---|---|---|---|---|
| Building (`overlayBuilding`) | `CreateBuildingOverlay` S 0061f980 from `Game::OnBuildingCreated` S 005ead80 (callback slot 2) | building removed: S 005eadb0 → `DestroyByKey` S 0063d840 | 1 if the property is a `casern` (+0xf1) or has `health` (+0x8c) > 0, else 0 | only buildings whose owner has `kind` (+0x08) = 2, the local human (`PlayerTable::FindLocalPlayer` S 005bdda0); AI and remote players' buildings get none |
| Soldier (`overlaySoldier`) | `CreateSoldierOverlay` S 0061f770 from `Game::OnSoldierEnteredFight` S 005eae00 (slot 10), fired by `SoldierFightState::EnterFight` S 0065b840 and its `PostLoad` S 0065b9c0 | the soldier leaves the fight (`LeaveFight` S 0065be90 → slot 11 → `DestroyByKey`) | 1 (the disassembly stores 1 into the argument slot before the `EnableCategory` call S 0063d7b0) | none: every player's soldiers in a fight get one |
| Fight (`overlayFight`) | `CreateFightOverlay` S 0061f830 from `OnFightAdded` S 005eade0 (slot 13) | slot 14 | 4 | none |

A soldier overlay therefore exists only while its soldier fights. **Settler overlays never exist on their
own**: the only caller of `OverlaySettler::ctor` S 0064b960 (kind 2) is `OverlaySoldier::ctor` S 0063de90,
which overrides the kind to 3, so the `overlaySettler` template is dead [known]. The owner test of a building
overlay happens only at creation; [TODO] not established: what happens to it when the building changes hands
or a save is loaded (a read of the ownership-change and load paths settles it).

**Layers and the `alphaPlane`** [known]. An overlay carries five category flags (bytes at +0x1b0); the panel
has five layer switches. The panel constructor S 0061fb10 zeroes `activeLayerCount` (+0x510) and
`layerEnabled[0..4]` (+0x514). `OverlayPanel::LoadFromXml` S 0061fc60 loads the child `alphaPlane`, re-applies
the template `overlayBuilding`, `overlaySettler` or `overlaySoldier` to every live overlay by its kind 1, 2 or
3 (fight overlays are skipped), resets the count to 0 and switches layers 2, 3 and 4 on: that fades the
`alphaPlane` in once and leaves the count at 3. So **fight overlays are always shown** while on screen,
independent of the two buttons. `ToggleLayer` S 0061faf0 is `SetLayerEnabled(idx, layerEnabled[idx] == 0)`
S 0061fa40; it is the only caller of `SetLayerEnabled`, and only with index 0 or 1. The count therefore moves
between 3 and 5 and never reaches 0: **the `alphaPlane` never fades out**, and toggling never fades it in
again. Quirk (presentation only): a reload of the XML resets the count but not `layerEnabled[0..1]`.

- The fade is `FadeIn` or `FadeOut` over 0.5 s, after which the caller sets the animation's byte +0x30 to 1;
  `AnimationAlphaFade::Update` S 004d2220 then applies smootherstep `((6a − 15)a + 10)a³` to the interpolated
  alpha, from the current opacity to 1 (or 0), recursively.
- The `alphaPlane` is a plain `nUi::Picture` (kind 0xe) created at (0, 0) under the panel (S 0061f920). Code
  sets no texture, colour or size: everything visible comes from the XML. The overlays are children of the
  panel, not of the `alphaPlane` (every `Create…` passes the panel as parent), so its opacity does not reach
  them. [inferred] Without a shape in the XML it draws nothing.
- `FadeIn` returns null when the `alphaPlane` is not attached yet. [TODO] not established: whether the panel's
  creation in `SetupHud` (S 005ee0c4) runs before the game screen's XML load (S 005ed034 in `LoadFromXml`);
  a read of the order of the two settles whether the one fade-in at load takes effect.

**Buttons** [known] `Game::OnButtonClick` S 005eb850: `btInfoMap2` (Game +0x3650) calls `ToggleLayer(0)`,
`btInfoMap3` (Game +0x4068) `ToggleLayer(1)` (§3.4). Each click latch is read and cleared
(`Widget_ReadClearClickLatch`); there is no return between the two tests, and `btBack`, `btForward` and
`btQuests` are tested afterwards. Both are `nMenu::RoundIngameButton`s (ctor S 005ebbc0) whose only behaviour
of their own is the hover highlight (green or red at +0x508 / +0x790, faded in over 0.1 s by S 00622bc0,
hidden again on a click by S 00622d10); no game code writes a toggled state to them. `nUi::Button::OnClicked`
S 004b12d0 toggles `marked` (+0x2ec) only for a `checkbutton` (+0x2ed), so a latched look could come from the
XML alone and would never follow the panel's state. Every click plays `uiClick0` and fires `<name>_isClicked`.
The hotkeys are `e` and `m` (`menuingame.xml`) [known: data]; [inferred] they take the same click path (the
hotkey dispatch is not traced). `btInfoMap1` is independent: it flips Game +0xfff0 and calls
`StartOverlayColorFade` S 005eabd0 (the terrain info-map tint, §3.4), then the handler returns early; it never
touches the `OverlayPanel`.

**Positioning** [known]. Per frame the overlay's `IUpdateable` update first refreshes the content, only if
the overlay and its parent are visible (buildings S 00641030, soldiers S 0063de50, fights S 0063e2d0); then
`ProcessPendingAndNotify_thunk` S 0063d790 calls the position slot (vftable +0x84), then
`nUi::Object::Update`.

- **Building point**: `SetWorldCellWithSizeOffset` S 0063e770 → `SetWorldCell` S 0063da50 →
  `TerrainGrid::CellToWorldPos` S 00687790 of the building's cell (+0x20): x = cell.x × 4 (+2 on odd rows),
  z = cell.y × 4, y = the terrain elevation at that vertex × `g_MapHeightScale`; no further 3D height.
- **Lift**: screen y gets `−offset`, chosen by the property's `size` mask (+0x3c), first match: bit 0 →
  `offsetSmall`, bit 1 → `offsetMedium`, bit 2 → `offsetLarge`, else 0 (mine, ship). The unit is a fraction of
  the screen height (pixels are divided by the device height, S 004aab10). Constructor defaults (S 0063ed74
  onwards): large 0.09, medium 0.06, small 0.04; the XML attributes of those names override them (loader
  S 0063ef50). x has no offset.
- **Soldier point**: `UpdatePositionFromSettler` S 0064ba40 (the soldier overlay's position slot, vtable +0x84
  = S 0064bb40, run every frame; slot +0x88 is a no-op) takes the character's movement position (+0x58 ..
  +0x60) plus (0, AABB size.y, 0), the top of the character, where the box spans the translations of the posed
  bone matrices in model space (KModel +0x18, `ComputeBoneMatrix` S 0072bf20) [known]; screen offset 0; the overlay's visibility test is
  the character's `visible`; without a character the overlay is hidden.
- **Fight point**: S 0063e310 takes the fight cell (fight +0x48), lifted by the attacked building's size with
  the same three offsets; hidden when the cell is −1 or the target reference is invalid.
- **Projection and centring** (`SetWorldPosition` S 0063d870): `ProjectToScreen` S 004d45b0
  (`D3DXVec3Project`) counts as on screen only when `0 < x ≤ viewport width`, `0 < y ≤ viewport height` and
  `0 < z ≤ 1`; only the anchor point is tested. The pixels are converted to fractions and
  `pos = projected − 0.5 × own deployment size + offset` is set as the relative position every frame. When the
  anchor is on screen, the visibility test passes and one of the overlay's categories has its panel layer on,
  a hidden overlay with no running animation fades in (0.2 s, linear); otherwise a visible idle one fades out
  (0.2 s). A fade that runs is always finished first: an immediate hide (fight without cell or target, soldier
  without character) does not stop it (`Object::Hide` S 004a1130), so a new fade-in waits until it ends; a
  fade-out ends with the hide and the opacity reset to 1 (`AnimationAlphaFade::Stop` S 004d22c0) [known].
- No distance, zoom or LOD culling and no scaling: only the position changes; sizes are those of the
  templates (`overlayBuilding`, `overlaySoldier` 100 × 100 px [known: data, `templates.xml`]).
- Draw order [known]: the overlays are attached to the panel when they are created (S 0061f980, S 0061f770,
  S 0061f830) and drawn in that order (S 004a56d0, S 004a1370); no layout has a z-order. `SetupHud` S 005ed700
  attaches the panel to the HUD root before every visible HUD widget (only the hidden debug icons come before
  it), so every HUD widget draws over the overlays.
- Visibility at creation: `Overlay::InitAndAttachToParent` S 0063d770 hides building and fight overlays.
  `OverlaySoldier::InitAndAttachToParent` S 0063e030 calls `nUi::Object::InitAndAttachToParent` directly, so a
  new soldier overlay is kept hidden only by the template's `visible="false"` until `SetWorldPosition` fades it
  in.

**Content.**

- **Building**: name, construction progress, garrison counts and hit-point bar, warning icons, up to 10
  pulsing icons of missing goods, the name coloured by productivity (> 66 green, > 33 orange, else red:
  `textColGreen` / `textColOrange` / `textColRed`); the full rule of `OverlayBuilding::UpdateFromBuilding`
  S 006403c0 is in [hud-panels.md](hud-panels.md) §3.6.1.
- **Soldier** (`UpdateHealthAndColor` S 0063dd30): `r = soldier +0x1ec ÷ SettlerProperty(soldier +0x58)
  +0x88`, nothing updated when the maximum is 0 ([inferred] r is the fraction of hit points left). All three
  bars get the value r (`healthBars[0..2]` = `progressRed`, `progressYellow`, `progressGreen`, bound in
  S 0063dcb0); exactly one is shown: green if r > 0.6, yellow if r > 0.3, else red (float thresholds 0.6
  S 007e7ad0 and 0.3 S 007e2a70, strict comparisons). `colorIcon` gets the RGBA
  of the soldier's owner (soldier +0x28) from the 16-byte-stride table S 0087f8c8 (S 0060ed40), filled from the
  `iconconfig.xml` node `PlayerColors` (S 00611320; attributes `blue`, `red`, `green`, `yellow`, `white`,
  `black`, `magenta`, `grey` for indices 0..7); built-in defaults (0, 0, 1), (1, 0, 0), (0, 1, 0), (1, 0.9, 0),
  (1, 1, 1), (0.4, 0.4, 0.4), (1, 0, 1), (0.1, 0.7, 0.7).
- **Fight**: the child `clockSymbol` is bound by name in S 0063e450 (the child `label` only when it has
  `controltype="label"`) and driven by `UpdateDisplay` S 0063e190 [known]: the label gets the target's name, the
  `swords` are shown; ticks from fight +0xb4 when the local player is the attacker and `Military_GetFlagB8`
  (the fight is ending, +0xb8) is set, else from the target building's `Military` +0x90 when the target is
  local and that value is ≥ 0; the clock shows `(ticks + 9) ÷ 10` (so an ending fight whose +0xb4 is −1 shows
  0) and is hidden when neither case applies. `nMenu::ClockSymbol` (ctor S 0062ee50, `Create` S 0062f010,
  S 0062f070, S 0062ecd0): eight frame pictures `pic0..7` and a number label, `aniSpeed` 1.0, `numberDuration`
  100.0, `blendPics` 0 by default.

#### 3.8.7 Message boxes

`nMenu::MessageBox2` (template `messagebox`; inside panels; the action panel's confirmation box is created under
the HUD root, S 005f06ca) [known] `LoadFromXml` S 0062cd50, `SetupButtons` S 0062c610, `Show` S 0062c0d0,
`GetClickedResult` S 0062c150, `OnButtonClicked` S 0062c290, S 0062c320: attributes `type` (mode), `fadeInTime`,
`fadeOutTime`, `buttonspread`; children `title`, `text`, `buttoncontainer`, `button` (template for up to three
buttons). Result values: −1 none (open), 0 Yes or OK, 1 No, 2 Cancel, 3 Abort, 4 Retry, 5 Ignore; `Show` resets
only the result (+0x2ac). The caller's pending action is kept in the box's widget user data (+0x28), which
`Object::ctor` S 004a3cc0 starts at 0 and nothing else resets ([frontend-screens.md](frontend-screens.md) §3.6
for the load / save panel's consequence).

| Mode | Buttons → result | Hotkeys | Enter gives |
|---|---|---|---|
| 0 YesNoCancel | 0 / 1 / 2 | Enter / – / Esc | 0 |
| 1 YesNo | 0 / 1 | Enter / – | 0 |
| 2 AbortRetryIgnore | 3 / 4 / 5 | Esc / Enter / `i` | 4 |
| 3 Abort | 3 | Enter | 3 |
| 4 OK | 0 | Enter | 0 |
| 5 OKCancel | 0 / 2 | Enter / – | 0 |
| 6 RetryAbort | 4 / 3 | Enter / Esc | 4 |

Results and the Enter column are [known] S 0062c150, S 0062c320; the hotkeys are the values `SetupButtons`
S 0062c610 writes (13, 27, 0x69) [known]: it writes none for `!No` in mode 1 and none for `!Cancel` in mode 5,
so Esc answers neither unless the `button` template itself carries a hotkey [inferred]. Button captions:
`!Yes`, `!No`, `!Cancel`, `!Abort`, `!Retry`, `!Ignore`, `!OK`. Result −1 = open. Showing it warps the cursor to button 0 (smart cursor option). Listeners
(`IMessageBoxListener`) get the result. `nMenu::MsgBox` (dialog slot 6) is the stand-alone variant with
code-created style-8 buttons at x = 0 / 146 / 292 px [inferred] S 005ff150.

#### 3.8.8 Game menu `cbMenu` and the requester [inferred] S 005eb310, S 00600300, S 006009b0, S 006008b0

| Item | Label | Effect |
|---|---|---|
| 0 | `!Save` | offline role only: close load and options, toggle the save panel. Outside the offline role the entry is not in the menu (§3.4) |
| 1 | `!Load` | offline role only: toggle the load panel; removed likewise |
| 2 | `!Options` | close save / load, toggle `OptionsPanel` (`menuoptions.xml`; 27 option controls bound by name; closing writes the user settings) |
| 3 | `!Main Menu` (network: `!Surrender and back to Lobby`) | close all panels, open the requester (slot 4) with type 2: text `!Back to Lobby` in a network role, else `!Exit to title?` |
| 4 | `!Quit` | requester type 1: `!Exit to desktop?` |

The panels are kept per mode: `Game::OnMenuComboSelected` S 005eb310 holds a save panel (+0xcc84) and a load
panel (+0xcc80), made at their first opening; another entry hides the other panel at once (vtable +0x28; +0x2c
is `IsVisible`) [known].

Requester (`menurequester.xml`: `yes`, `no`, `title`, `autosave`; its text label is `Subline_Garamond`): Enter =
Yes, Esc = No. In a match an `!Autosave...` check box is shown (choice stored in the user profile). The shipped
layout has `<autosave visible="false"/>`, and `OnLoadXml` S 005ffb90 loads that element only while the box is
shown [inferred]; [TODO] not established: whether the box is ever visible in the shipped game (a read of the
writers of its visibility settles it). Yes: the buttons are disabled, the text
becomes `!Finalizing...`, in a match the session event "user leaves" is sent
([network-session.md](network-session.md)); when the session allows it the action runs: type 1 → autosave if
ticked, log out, quit; type 2 → in a lobby match send the referee "give up" and return when it answers, else
autosave if ticked and return to the main screen.

Load and save panel (`menuLoadSave.xml`, `nMenu::LoadSavePanel`, mode 0 load / 1 save): see
[save-format.md](save-format.md) §3.7 and [frontend-screens.md](frontend-screens.md) §3.6. UI rules: Enter =
confirm; clicking a row copies its name into the edit field; save over an existing name asks `!Overwrite file?`;
delete asks `!Remove this file?`; a chosen file is handed to `nMenu::System` (+0x68) and started on the next
update.

#### 3.8.9 Sacrifice bar and target chooser [known] S 006264d0, S 00625300, S 00625d90; [inferred] S 00627210, S 00626ea0, S 00626c20

- **Bar** (`sacrificePanel`, 15 + 15 `SacrificePanelButton`s made by `InitAndAttachToParent` S 006269b0)
  [known]: `SacrificePanel::Update` S 006264d0 refills both rows every frame. Row 1, left to right: the source
  buildings of running own sacrifices (S 00624dc0); then the own sacrifice buildings whose sacrifice is ordered
  or can start, in the village's building order (+0x9c, S 00624c90); then the building of the running research
  (S 00624ef0, written without a bound on the slot index). A site that is merely ready (state 2, nothing
  ordered) is **not** listed. Row 2 holds the sacrifices aimed at the local player ("antibuffs", S 00625200,
  buttons filled by `UpdateAntibuffButtons` S 00625d90) with countdown `mm:ss`. The panel is shown when either
  row has a visible button, else hidden (its size is kept).
- **Row-1 button states** (`UpdateSacrificeButtons` S 00625300, first match) [known]: ordered and not
  startable, by `CheckCanStart` code: 3 → `!ordered`, the cost progress on the bar, plus the regeneration fan
  while regenerating; 6 → `!blocked` with the regeneration fan; 5 → `!samestillrunning`; 7 → `!noEnemy`; any
  other code sets only the icon and an empty text (the bar and fans keep their previous look). Startable
  (code 0) → `!ready`. State 1 (running): the running sacrifice (vs +0x18), text `%u:%02u` (minutes ≤ 60, else
  `-`) with `!running`, or `!paused` with the text kept while the sacrifice system's byte +0x05 is set.
  Research at the building → `!researching` with the research fan. Otherwise the button is hidden.
- **Layout** (`LoadFromXml` S 006265d0) [known]: item (5, 5), 40 × 40, padding (10, 21), antibuff origin
  (5, 90), spread 50. Row 1: width 40 + 50 (n − 1) + 10, height 61. Row 2 runs right to left from
  W − 5 − 40; width max(10 + 40 + 50 (n − 1), W), height 2 × 40 + 2 × 21 + 21 ÷ 1.5 = 136. Quirk
  (presentation only): a row 2 longer than a non-empty row 1 hangs out to the left of the panel.
- **Buttons** (`SacrificePanelButton`, ctor S 00645b70, S 00645aa0..S 00645c20) [known]: `questionmarkalpha`
  defaults to 0.5; the shipped `questionmarkalpha="0.6"` sits on `alphafanResearch`, where it is not read. The
  regeneration fan has no `timedtexture`, so it gets `timedGoodButton.png` (`AlphaFanPicture` slot 2,
  S 004cdbe0). `ApplyGoodIconToButton` S 0060f120 puts the icon on all four button states, so there is no hover
  look. A fresh button's progress bar and both fans start visible (fans 0): `Object::ctor` S 004a3cc0 sets
  visible, nothing in the constructors or the layout hides them, and the first `UpdateSacrificeButtons` (from
  `LoadFromXml`) hides only the buttons, whose `OnParentHidden` S 004a11c0 leaves the children's flags alone.
  The bar's value is 0 from `ProgressBar::ctor` S 004bd280, but its fill is computed only by `UpdateFill`
  S 004bd580, which in this panel is reached only through `SacrificePanelButton::SetProgress` S 00645b50 (called
  from `UpdateSacrificeButtons` at S 0062556c, its only call), so until then the bar keeps its layout width
  ([ui-toolkit.md](ui-toolkit.md) §3.13). Code 4
  cannot occur for an ordered site (`CheckCanStart` S 00560f20 returns it only in state 0) [known].
- **Row-2 buttons** (antibuffs) [known]: their primary vtable S 007f3414 differs from the normal button's
  S 007f77ec only in slot 34, the empty S 005657b0 in place of `Button::OnClicked` S 004b12d0, so a click on an
  incoming sacrifice does nothing at all: no `uiClick0`, no `OnItemClicked`, no observers, no Lua event.
- **Click** (`OnItemClicked` S 00624bd0, slot 25 of the panel's vtable S 007ee6d0) [known]: find the building by
  the button's id (any owner; the low dword at button +0x28 with the high dword taken as its sign, the button's
  +0x2c is ignored);
  `Selection::ResetHandles` and `SelectBuilding`; `MenuSelection::ResetAndRefresh(1)` (§3.5: the box of the
  building's kind opens, the camera does not move); then the selection cell is set to the building's cell
  (+0x20 / +0x24). `ResetAndRefresh` runs `RefreshFromGameSelection` S 00617800 only in mode 1, so in placement
  modes 2 and 3 only the reset and the cell take effect on the menu side, while the game selection holds the
  building in every mode [known]. It is read later by `InfoBox::UpdateHelpText` S 006316e0,
  `RefreshFromGameSelection`, `SendStartAttack` S 00781a00 and `SendToggleGoodFlag` S 00781720. A world left
  click replaces it first (`nGame::Cursor::SelectAtCursor` S 00788370 starts with `ResetHandles`), but
  `MenuSelection::Cancel` S 006162e0 (right click, back to mode 1) does not, so the building stays selected
  until the next refresh path; whether any reader sees it in modes 2 and 3 before it is replaced is [TODO]
  (a read of the paths from those modes to the four readers).
- **Start effect** (`sacrificestartedeffect`, `Game::OnSacrificeStarted` S 005eae20) [known]: plays when the
  event's owner or target is the local player, or always when Lua `menu.showSacrificeEffect` (S 005d9550) asks;
  the picture is brought to the front, set to alpha 1, shown, and faded out over 1.1 s (linear). The callback
  S 005eb2e0 updates the minimap first (§3.8.5). A loaded game plays no start effect for the sacrifices its
  `PostLoad` restarts: the event (`ReattachSacrifices` S 00661e60 → `NotifySacrificeStarted` S 00531620) is raised
  inside `BuildWorld` S 00784d40 (`GameFile_FinishLoad` S 005aa1b0 → `PostLoad` S 005273d0 → S 0065f540), after
  `BuildScene` S 007842e0 has registered the Game's callback face (Game +0x1c8, disassembly 0078432b..0078434e)
  but before `Game::OnEnter` S 005eed00 sets the local player entry (Game +0xfff4; the constructor S 005ee5d0 and
  `OnLeave` S 005eb030 null it),
  and `OnSacrificeStarted` returns while that entry is null; the minimap still receives it [known].
- **Target chooser** (`sacrificetargetpanel`): opened by action 22 when the sacrifice needs a target. One
  button (clone of `entry`) per enemy player that is active, eligible and not yet eliminated
  (`victoryConditions +0xe8 + i × 4 == 0`), labelled and tinted with the player's name and colour, in a column
  centred on the cursor. Click → **`0x20026` GE_Sacrifice_StartOrdered** (building id, target player index),
  fade out. Esc (S 00626d60) or a cancel input closes it.

#### 3.8.10 Build menu (`infoboxCreateBuilding`) [inferred] S 00634db0, S 006343f0; [known] S 00617910, S 006176d0; S 006340b0

- **Content**: for every building id of the local player's tribe whose property `constructionTime` (+0x88) > 0 and
  whose `size` mask (+0x3c, [properties-data.md](properties-data.md) §3.6) is not 0, one `BuildingButton` (clone of
  the template child `buildingButton`, icon from `IconConfig`, tooltip kind 0 with the building's name,
  `BuildingButton::CreateForBuilding` S 0064b610) on the tab of the lowest set bit among bits 0..4: 0 `!SMALL`
  (size 7), 1 `!MEDIUM` (6), 2 `!BIG` (4), 3 `!MINE` (8), 4 `!SHIP_SIZE` (16) [known] S 00634db0; captions [known:
  `menuingame.xml` `tabButton0..4`]. `IconConfig` keys a building's icon per tribe by the building's name in lower
  case with spaces replaced by underscores [known] S 0061236d (inside `IconConfig::LoadFromXml` S 00611320). A
  button is enabled (button vtable slot 8, `SetEnabled`) unless the filter stored at +0x1638 is not 0 and
  `Building_TypeFitsConstructionFlags(filter, type)` (S 0052e510) fails, or the type is locked for the player
  (`ai::player::Player::IsLocked`, `menu.lockBuilding`); a disabled button draws its shape in `disabledColor`
  (0.4667 grey, alpha 1, §2.4). **A tab without an enabled button is hidden**, not disabled: S 00634db0 calls
  vtable slot 9, `nUi::Object::SetVisible` S 004a1090 (read at 0x00634fce–0x00634fe5 against the `nUi::Button`
  vtable S 007dff14). The tab of the filter's highest bit among bits 0..4 is selected; then
  `EnsureEnabledTabSelected` S 00634160 keeps the selected tab if it is visible (slot 11, `IsVisible`
  S 004a0100) and otherwise selects the first visible one, so with a filter of none of those bits the previously
  selected tab stays when it is still visible [known] S 00634db0, S 00634160.
  `TabControl::LayoutTabButtonsHorizontally` S 004ba3f0 packs the visible tab buttons from the first tab's x,
  each advanced by its width (82 px): x = 5, 87, 169, … [known]. Every rebuild starts
  with `ClearBuildingButtons` S 00634210, which also resets the chosen type (+0x1630) to −1 [known].
- **Layout**: grid from `itemsOffset`, `itemsSize`, `itemsSpread`, `numItemsPerLine` (shipped `6 6`, `56 56`,
  `71 64`, 7; constructor defaults 0 0, 80 80, 85 85). The row wrap happens once per tab, at index =
  `numItemsPerLine`: the column counter is not reset after the wrap [inferred] S 006343f0. A remake that wants
  identical layouts needs at most two rows per tab.
- **Opening**: a left click on an empty cell where something can be built (§3.5); the box is opened in
  "direct" mode with the clicked cell remembered. Help text: `!Infobox_Anchor_Help` (filter bit 0x10),
  `!Infobox_Mine_Help` (bit 0x8), else `!Infobox_CreateBuilding_Help` [known] `UpdateHelpText` S 00634a90. The
  filter +0x1638 is the clicked cell's build flags, written only by `MenuSelection::BeginBuildPlacement` S 006176d0,
  and 0 from the constructor (at 00634d6c), which gives the general key.
- **Choosing** [known] S 006340b0: a click on a building button stores the type (+0x1630); a type id of 0 is
  ignored. In direct mode with the remembered cell (`MenuSelection +0x8c`) inside the map it sends **`0x20002`
  GE_Building_Create** (type, cell) immediately, sets mode 1 and resets the selection. With the direct flag clear
  the clicked button is marked instead and the next left click on the world sends `0x20002` for the cell under the
  cursor (§3.5 mode 2). The only writer of the direct flag is `BeginBuildPlacement` S 006176d0, which always sets
  it to 1, so that "choose a type, then click cells" mode exists but cannot be reached [known].
- **No build key**: the menu opens only by a left click on a buildable cell (§3.5, S 00617910); choosing a type
  sends the command at once and closes the menu (S 006340b0). No hotkey of `menuingame.xml` and no key handler
  of §3.3.3 opens it [known].
- Action button 1 = 29 "create flag" at the clicked cell (**`0x20004` GE_Flag_Create**).

### 3.9 Screen flow

Top-level screens: `Splash` (at start, if enabled) → `Main` (`menumain.xml`) → `Game`; `Exit`. The flow is
code ([`../game-data-files.md`](../game-data-files.md) §5 for the general finding). In-game:

1. A map or save path placed in `System +0x68` (free-game panel, load panel, campaign, lobby) is consumed by
   `System::Update`: `StartPendingMap` S 005d9fd0 closes all screens, makes `Game` current and calls its
   `OnEnter` S 005eed00, which shows the `LoadingPanel` (`menuLoading.xml`; progress bar with a glow at the bar
   tip, redrawn synchronously on every progress call), builds the world, then `SetupHud` [inferred].
2. While playing, `Game::Update` S 005efea0 [known for this block] checks, when the world is not in state 3,
   no `Victory` / `Report` / `Defeat` dialog is open and no cinematic is open:
   - local player eliminated (`victoryConditions +0xe8 + player × 4 ≠ 0`) → open **`Defeat`** (slot 5);
   - else the current map's completion is pending in the user profile → mark it, then open **`Victory`**
     (slot 3) if the map type (`MapInfo +0x1d0`) is 1 or 0x65 (campaign), else **`Report`** (slot 0).
3. The three end dialogs derive from `GameEnded` (`menugameend.xml`; attributes `wonTitle` / `wonDesc`,
   `reportTitle` / `reportDesc`, `defeatTitle` / `defeatDesc`; in a network role the text key gets the suffix
   `MP`). `btContinue` closes the popup and opens the statistics; `btEnd` does the same and marks the
   statistics panel "leave on close"; `Defeat` disables `btContinue` [inferred] S 0061ff50, S 006201f0,
   S 005fe6c0.
4. Closing that statistics panel sets `Game +0xb330`; the next `Game::Update` detaches dialogs 5, 3, 0 and
   leaves the match: campaign map → main screen; otherwise log out of the referee (if a lobby exists) and main
   screen or back to the 3D lobby [inferred] S 005eae90, S 0061fea0.
5. Leaving through the requester: §3.8.8.

Dialogs (`Overlapped`): opening one closes the others (`ToggleScreen` S 005ea960 [known]); the requester is
drawn again after the whole tree so it is always on top [inferred] S 005d9800.

### 3.10 Localisation and fonts

**Text tables** [inferred] S 004966d0, S 00496b80, S 00496070; [known: data]. On start and on a language
change, these files are read from `[data]\language\<lang>\` in this order, later files overriding earlier keys:
`briefings.txt`, `ui.txt`, `credits.txt`, `lobby_ui.txt`, `lobby_items.txt`. Format: plain text, single-byte
code page (the German files are Windows-1252), one entry per line, lines separated by CR LF, LF or CR. A line
starting with `//`, `;` or `#` is a comment. Otherwise **key = text before the first TAB, value = text after
the last TAB**, with `\n` in the value turned into a line break. The keys in the files include the leading
`!` (e.g. `!1 Hour` → `1 Stunde`) [known: `ui.txt`].

**Lookup** (`Localization::GetText`): empty key → empty string; a known key → its value; an unknown key → the
key itself (and it is inserted, so it stays that way). `Localization_FormatText` uses the value as a `printf`
format; its lookup variant returns `(MBT)<key>` for a missing key [inferred] S 004965a0.

**When a string is localised**: `nUi::Text::SetText(str, localize)`; the XML loaders pass
`localize = (first character == '!')` for `content`, `string<N>`, tip `description` [known] S 004b46d0. Code
passes `!`-keys explicitly. The names of buildings (and of goods) are keys without `!`: the key is the
property's name itself (`Bakery` → `Bäckerei`, `Wood` → `Baumstamm` in the German `ui.txt`; 468 of its keys
have no `!`) [known: data], localised by code that passes the name with `localize` set. Colour markup inside texts: `<r g b a>` tags and `<right>`, `<c>` are interpreted
by the text block renderer [inferred] S 00627e30; [TODO] the full markup grammar (a read of `nUi::TextBlock`
draw, S 004b7dc0 onwards, settles it).

**Fonts** [known: data]; [inferred] S 004946c0, S 004941a0. A font name (case-insensitive) maps to
`[data]\language\<lang>\fonts\<name>.fnt` plus its page image `<name>_00.tga`. The `.fnt` files are AngelCode
BMFont **text** descriptors (`info face="Arial" size=13 … / common lineHeight=15 base=11 scaleW=256 scaleH=256
pages=1 / char id=…`), not encrypted. Shipped: `Body_Arial` (default of every widget), `Subline_Garamond`,
`Chapter_Garamond`, `Head_Garamond`, `Gamertags_Garamond`, `Mini_Silk`, `mini`, `title`, `system`,
`light_system`, `dark_system`, `light_system_outlined`, `font_big_white`, `small_no_alias_white`, `editor`.
Fonts are bitmap fonts drawn at their native size; there is no scaling attribute.

Roles in the in-game layouts [known: data, `menuingame.xml`, `menuIngameSettings.xml`, `templates.xml`,
`menuStatistics.xml`, `menuLoadSave.xml`, `menumain.xml`]:

| Font | Look of the page image | Used for |
|---|---|---|
| `Body_Arial` | Arial at about an 11 px em, cream face, gold-brown 1 px edge, dark shadow | the default of every widget: settings labels, button captions, `cbMessages` entries, the save edit line, info box counts |
| `small_no_alias_white` | the same glyph shapes as `Body_Arial`, white face with a grey edge and shadow | the top bar's goods numbers (`menuingame.xml`, label `pos 0 13`), the diplomacy names and states, health texts, statistics |
| `Mini_Silk` | a 5 × 7 pixel font (face `fixed_v01`), white with a dark-brown edge; a fixed `xadvance` of 6, drawn 7 px apart with the `spacing` the loader adds ([formats-inventory.md](formats-inventory.md) §3.6) [inferred] | slider `MIN` / `MAX`, `!Empty`, timers `0:00`, statistics `1H` / `16H`, chat buttons |
| `Subline_Garamond` | Garamond | sublines, tabs, tooltips, the message rows, quest lines, code-made labels |
| `Chapter_Garamond` | Garamond | info box headlines (`menuingame.xml`), menu entries |
| `Head_Garamond` | Garamond | dialog titles (`!Save`), the main-menu title |
| `light_system_outlined` | | the start-up logo sequence: `menusplash_dev.xml`, which `Splash::OnShow` S 0060bbd0 loads at every start (`bShowSplash` is always true, S 004075d0 → S 005dda30), and the code label `!SplashText2` ([frontend-screens.md](frontend-screens.md) §3.1) |

`system`, `title`, `mini`, `editor`, `dark_system`, `light_system`, `font_big_white` and `Gamertags_Garamond` are
named only by code or not at all [known: string references]: `system` by `GetSystemFont` S 004948d0 for the
debug and editor overlays (for example S 006066d0, `InitWithFont` S 00763960) and the legacy `Edit` (S 00497710,
which replaces it with `Subline_Garamond` at once); `editor` by `nMenu::Debug::OnShow` S 0060a340; `light_system`
and `dark_system` by the preloads of S 005dda30 and the lobby (S 0042ac13); `gamertags_garamond` by the lobby
avatars (`CGfxObjAvatar` S 005084b0; only as the lower-case path `[data]\language\de\fonts\gamertags_garamond`,
S 007e63dc, so a case-sensitive search for `Gamertags_Garamond` finds nothing); `mini` and `font_big_white` appear nowhere in `SADK.exe`; `title` occurs
only as an object name. The page `title_00.tga` is the only
24-bit page (no alpha); the other font pages are 32-bit [known: data].

**Default fonts** [known]: a widget's text without a `font` is `Body_Arial`
(`Object::InitAndAttachToParent` S 004a56d0), centred on its point (`Text::ctor`, alignment 8 at S 004b3eee).
The exception is `controltype="label"`: the factory's kind 9 (`Factory::CreateObject` S 004c28a0, name table
S 007bf5f0) runs `Label::Create` S 004b2170 → `CreateWithText` S 004b2040, which gives the label
`Subline_Garamond`, white, left-aligned. Button captions follow the button's style (§3.2.1).

**Localised textures**: `[data]\language\<lang>\<name>.dds` (e.g. `ui_s2logo.dds`) [inferred] S 00494470.

---

## 4. Update order

Per frame (`CApplicationEx::FrameTick_InGame` S 004018e0; the calls below are in the order of that function)
[known] unless tagged:

1. Window messages arrive outside the frame function → `nUi::Root::HandleInputEvent` (§3.3.1); handlers run
   immediately, including `QueueGameCommand` (offline: the command executes inside the click,
   [game-commands.md](game-commands.md) §3.1). Exceptions are the three round buttons polled in step 4.
2. Frame timer update; layout hot reload if one was requested (`XMLHandler::ReloadAllIfRequested`); the key
   table is told whether the window is active and not minimised.
3. Only if the game screen is open: `nGame::System` update (cursor, camera; S 00780d20) and then
   `nMenu::Messages::Update` S 005f86a0, both called directly from the frame function, before the menu system
   [inferred: the two virtual targets are taken from the member types, not from the vftables].
4. `nMenu::System::Update` S 005da500:
   1. reload the text tables if the language changed; `Cursor::Update`;
   2. if the UI is not suppressed (System +0xa4 = 0): every open dialog of the nine slots is updated with
      argument 0; then the topmost open dialog that accepts focus (slots searched from the last to the first)
      is updated once more with argument 1 and System +0xa is set; text input is disabled while the message
      box (slot `msgBox`) is open; then the **`nUi::Root` update** (recursive `Object::Update` S 004a3920: tick
      the widget's animations and delete finished ones, mouse-over arbitration if the widget's dirty value is
      1, then, only if the widget is visible, update every child whose virtual slot +0x10 returns true, over a
      copy of the child list). [TODO] not established: the Root virtual slot +0x84 called right after the tree
      update; a read of the Root vftable settles it;
   3. `MinimapSymbolList_TickExpire` S 005f2690: every symbol with a positive counter loses 1, a symbol at 0
      is deleted, a negative counter is permanent. The `lifetime` of `mapSymbols.xml` is therefore a number of
      menu updates (frames), not seconds or logic ticks [inferred: the counter is taken as the copy of
      `lifetime`];
   4. start of a pending map (`StartPendingMap`, when the pending path is not empty).
5. NComm pump (if a manager exists), Lua threads, `NLogic::System::Update` (0..n logic ticks), sound update.
6. Render (`App_RenderWorldFrame` S 00401260; not while minimised; while the 3D lobby world is active the
   lobby object's update runs instead [inferred]): the scene, then `nMenu::System::Render`
   S 005d9800 → `nUi::Root::Render` S 00491660: the widget tree in child order unless the debug variable
   `ui.Hide UI` is set (per widget: nothing if invisible, else pre-render, draw, children, post-render,
   S 004a1370; the base draw S 004a0500 stamps the widget with the next value of a global render counter, the
   render id of §2.1), then the item widgets of an open combo box on top of the tree; after that
   `System::Render` draws the requester once more if it is open.

`nMenu::Game::Update` S 005efea0 is the game screen's override of the widget update and runs inside step 4.2
[inferred: reached through the tree]. Its order [known]:

1. Nothing if the screen is not open. If the deferred-leave flag (Game +0xb330) is set: clear it, leave the
   match (`PerformDeferredLeave`), return.
2. Base `Object::Update` (animations, mouse-over, all HUD children).
3. Everything below is skipped while the game is paused (Game +0xfff9).
4. Delete closed panels: the loading panel (+0xcc70, hidden first), then +0xcc7c, +0xcc80, +0xcc84, +0xcc78,
   each when it is no longer visible.
5. Scene colour fade (0.2 s linear interpolation of four floats, started by `btInfoMap1` and the cinematic
   screen through `StartOverlayColorFade` S 005eabd0): the tint of the build-placement icons, which draw only
   while its alpha is > 0 ([rendering.md](rendering.md) §3.14).
6. `btBack` / `btForward` enabled when `Selection_IsKind1` of the game selection is true; the children
   `x2` / `x3` of `btSpeed` are shown when the profile's speed scale truncates to 2 / 3.
7. `MenuSelection::Update`; the four debug toggles.
8. Only if the `nGame::System` state (+0x2d8) is not 3:
   - if the cursor is visible, the click latches of `btSettings` (open the settings panel), `btSpeed` (send
     `0x20023`) and `btOptions` (open the options panel) are read in this order; the first one found set ends
     the update for this frame;
   - if menu screen slot 1 is attached or the UI is suppressed: one more `nGame::System` update, nothing else;
   - otherwise: the world hover tooltip (`UpdateHoverTooltipIfCellVisible`), only if no focus dialog was
     updated this frame (System +0xa = 0), the byte at Game +0x164 is set (+0x144 of the screen's root
     widget, the hover flag [inferred]) and the message list's byte +0x42e9 is clear;
     then the end-of-game checks, only while neither the victory nor the report dialog is open and screen
     slots 5 and 0 are not attached: if the victory state of the local player
     (`victoryConditions + 0xe8 + 4 × player`) is not 0 and slot 8 is not attached → `ToggleScreen(5)`; else if
     the user profile reports a pending map completion and slot 8 is not attached → mark it handled and
     `ToggleScreen(3)` for map types 1 and 0x65, `ToggleScreen(0)` for the others.

Per logic tick the UI does nothing; it is called back by the simulation through `NLogic::CallbackReceiver`
(building created / removed, soldier, fight, sacrifice started) and the message listener, at whatever point of
the tick those events occur [inferred].

On entering a match: §3.9 step 1; `ActivateGameScreen` S 005d9f10 hides the message slots, makes the game
screen current, calls its enter hook and clears the minimap symbol list [known]. On leaving: `Game::OnLeave`
S 005eb030 unregisters the callback receiver (unless the UI is suppressed), clears the two NComm sinks, shuts
NComm down, calls `DestroyHudWidgets`, shuts `nGame::System` down, resets the load descriptor, resumes the
sounds if the game was paused, clears the local player entry and the minimap symbol list [known].

---

## 5. Inputs and outputs

**Consumes**

- Window input (§3.3.1); `GetAsyncKeyState` polling for the key table.
- Layout XML, `templates.xml`, `iconconfig.xml`, `goodinfosets.xml`, `mapSymbols.xml`, `cursors.xml`, text
  tables, fonts, UI textures (§6).
- Read-only simulation state: the game selection, the hovered cell and its build flags, buildings (type,
  owner, construction, production, stock, garrison, hit points, sacrifice), flags, ships and routes, players
  (colour, name, relations, lock maps, statistics histories), quests, messages, victory state, the explored
  mask, game speed, pause, NComm role and hang reason.
- Lua: `menu.*`, `ui.*`, `txt.*` ([lua-runtime.md](lua-runtime.md) §3.7), registered by
  `nMenu::System::Initialize` S 005dda30.

**Produces**

- Game commands ([game-commands.md](game-commands.md)). Complete list of UI senders:

  | Control | Command |
  |---|---|
  | Action buttons 1..30 | table in [game-commands.md](game-commands.md) §5.1 (`0x20003`, `0x20005`, `0x20009`, `0x2000A`, `0x2000B`, `0x2000D`, `0x2000E`, `0x2000F`, `0x20010`, `0x20012`, `0x20018`, `0x20019`, `0x2001A`..`0x2001C`, `0x20025`, `0x20026`, `0x20028`, `0x20029`, `0x2002A`, `0x20004`); action 9 sends nothing (it starts street placement) [known] S 00623730 |
  | Build menu button / world click in build placement | `0x20002` |
  | World clicks in street placement (`ai::game::StreetBuildMode::HandleClick` S 0078bed0, `Cancel` S 0078b1d0) | `0x20006`, `0x20008`; cancel `0x20007` |
  | Depot good button, casern soldier button | `0x2001E` |
  | Sacrifice button in the temple box | `0x20024` or `0x20027` |
  | Sacrifice target button | `0x20026` |
  | Settings confirm | `0x20013`, `0x20014`, `0x20015`, `0x20021`, `0x20011` |
  | Goods distribution slider | `0x2001F` |
  | Speed button (click latch polled in `Game::Update`, §4) | `0x20023` |

  Not sent by any shipped control: `0x20016` (military reset), `0x20017` (ignore distance), `0x20020`,
  `0x20022` (goods resets) [known: every `nGame::System::Send…` function has only the callers of the table;
  the four ids have no `Send…` function; game-commands.md §3.4].
- Session events: chat to all / to team, "user leaves", referee "give up" (§3.8.8).
- Local effects: camera focus, scene selection marker, sounds (`uiClick0`, `uiCancel`, `uiMessage0`,
  `uiMessage1`, `uiRemove`, also preloaded `uiClick1`, `uiDialog0`, `uiKey0`), user profile (options, autosave
  choice, smart cursor), save files through `GameFile_Save`.
- Script events `<name>_isClicked`, `<name>_isPressed`.

---

## 6. Data-driven parameters

All under `[data]\ui\layout\` (game data folder `data\game\ui\layout`), encrypted XML; `templates.xml` is shared
with the lobby.

| File | Root | Feeds |
|---|---|---|
| `menuingame.xml` | `menuingame` (`chatFadeOutTime="15.0"`, `chatFadeInTime="0.1"`, `zoomInTime="0"`) | the game screen (§3.4) |
| `templates.xml` | `templates` (289 top-level elements) | templates: `roundingamebutton`, `bt_action1..4`, `combobox`, `goodList`, `goodIngameButton`, `progressbar*`, `tabControl`, `container`, `overlayBuilding`, `tip*`, `messagebox`, `slider`, `graph`, `NormalDialog_*`, … |
| `menuStatistics.xml` | `menuStatistics` (`bldOffset`, `bldSpread`, `numBldPerLine`) | §3.8.1 |
| `menuIngameSettings.xml` | `menuIngameSettings` (`colRed="1 0 0 1"`, `colGreen="0 1 0 1"`, `textFriendly="!FRIENDLY"`, `textInWar="!IN WAR"`, `mappingPrioNotUsed="688 856 40 40"`, `texturePrioNotUsed="ui_ingame.dds"`) | §3.8.2 |
| `menuoptions.xml` | `menuoptions` (`minResolutionX="1024"`, `minResolutionY="720"`) | options panel |
| `menuLoadSave.xml` | `menuLoadSave` (`textLoad="!Load"`, `textSave="!Save"`) | load / save panel |
| `menurequester.xml` | `menuLoadSave` | requester |
| `menugameend.xml` | `menuGameEnd` (`wonTitle="!TitleWon"`, `wonDesc`, `reportTitle`, `reportDesc`, `defeatTitle`, `defeatDesc`) | end dialogs |
| `menuLoading.xml`, `menucinematic.xml`, `menunetinfo.xml` | `menuLoading` (`tipOfTheDayCount="51"`, `loadingScreenCount="1"`, `loadingScreen0="ui_loadingscreen"`), `menucinematic`, `menuNetInfo` | loading panel, cinematic, net info |
| `menumain.xml`, `menufreegame.xml`, `menuselectmapdialog.xml`, `menucampaign.xml`, `campaigns.xml`, `menusplash.xml`, `menusplash_dev.xml` | | front end (out of scope) |
| `iconconfig.xml` | `IconConfig` | every icon is `<Name texture pos="x y" size="w h"/>`, e.g. `<Wood texture="ui_ingame" pos="8 712" size="40 40"/>`. Top-level groups read by S 00611320 [known]: `Goods`, `SmallGoods`, `SmallRedGoods` (for every good of the property database the child named like the good, spaces as `_`; 93 / 62 / 39 children shipped, the surplus ones such as `Food_Bav`, `Halberd0`, `Woodcutter` are not goods names; the name is not lower-cased, and `XmlDoc::FindChild` S 006e7980 takes the first child of equal length whose bytes match (`Mem_Compare3Way` S 00408080), so the lookup is case-sensitive [known]; the `Sacrifices` group uses the same
`FindChild`; only the `Buildings` group lower-cases its names, `_strlwr_s`); `Goods/EmptyGood` and `Goods/ForesterTree` (fixed icons); `Sacrifices` (one child per sacrifice name, 47 shipped, e.g. `carrierSpeed`, texture `ui_buffs`; stored in the same map as the large good icons [inferred]); `Tactic/tactic0..2`; `BorderDist/dist0..2`; `Buildings` (one group for all tribes, 50 children: for every building of every tribe the child named like the building in lower case, spaces as `_`, e.g. `claymore_smithy`, texture `ui_buildings2008`, 56 × 56; a missing child prints `no building config for '<name>' found` and a default icon is stored); `GoodColors` (per good `color="r g b"`, 0..255, 36 shipped); `PlayerColors` (attributes `blue`, `red`, `green`, `yellow`, `white`, `black`, `magenta`, `grey`, each `r g b a` 0..1; the eight global player colours). In the data but not named in S 00611320: `Good_NotAvailable`, `Good_MovingToConstructionSite` ([TODO] reader not established; a string search for the two names settles it) |
| `goodinfosets.xml` | `GoodSets` | `<Set name="constructionWares" tribe="Bavarian"><Good name="Wood"/>…`: four goods per set; five sets (`constructionWares`, `foodWares`, `minerWares`, `militaryWares`, `miscWares`) for each of `Bavarian`, `Egyptian`, `Scots`; only children named `Set` (any case) are read [known: data, S 0062a820] |
| `mapSymbols.xml` | `mapSymbols` | `<symbol type="N" name texture mapping lifetime center>`: 0 Message, 1 Military, 2 Quest, 3 Ship, 4 Fight, 5 Chest; `lifetime` 100 for 0, 1, 5 and −1 (permanent) for 2, 3, 4, counted in menu updates, i.e. frames (§4); `center` (`2 3` everywhere) is in the data but not read by S 005f4c90, which reads `texture`, `name`, `mapping`, `lifetime` [known: data, S 005f5400, S 005f4c90] |
| `cursors.xml` | `cursors` | §3.2.4 |

Textures named by the in-game layouts [known: data]: `ui_ingame`, `ui_ingame2`..`ui_ingame6`, `ui_menus`,
`ui_menubar`, `ui_buildings2008`, `ui_buffs`, `uiElements0`, `opferung_frame`, `ui_loadingscreen`,
`techtree_bavaria.dds` / `techtree_egypt.dds` / `techtree_scots.dds`, and the masks `ui_mask.tga`,
`ui_mask_minimap.tga`. Named by code: `uiElements3` (debug icon row of `SetupHud` S 005ed700) [inferred].
All are in `[data]\gfx\` (`GetOrLoadTexture` S 00494000; see `asset-formats.md`). `uiTip.dds` exists there
too; [TODO] not established: what names it (no in-game layout does).

Attributes that hold several numbers (`pos`, `size`, `offset`, `mapping`, colours) are split at any of the
characters space, LF, CR, VT, TAB (the delimiter string `" \n\r\v\t"` at S 0087bf34, set by S 007bfe80)
[known]; the other three tokenizer arguments are the string at S 0087bf18, which has no initialiser and is
used elsewhere as the empty string [inferred]. The data pads with several spaces (`pos="8   712"`).

Action icons [known] S 00622f40, S 00623600: the icon of action *k* is the atlas rectangle
`x = start.x + col × spacing.x`, `y = start.y + row × spacing.y`, `w h = size`, with `start`, `spacing`, `size`
from `actionbuttons` (shipped `576 288`, `48 48`, `44 45`) and the cell (col, row) fixed in the code per action
number of [game-commands.md](game-commands.md) §5.1:

| Action | Cell | Action | Cell | Action | Cell | Action | Cell |
|---|---|---|---|---|---|---|---|
| 0 | 8, 4 | 8 | 8, 1 | 16 | 4, 4 | 24 | 6, 1 |
| 1 | 5, 2 | 9 | 2, 2 | 17 | 5, 4 | 25 | 5, 1 |
| 2 | 6, 2 | 10 | 1, 2 | 18 | 6, 4 | 26 | 0, 3 |
| 3 | 7, 2 | 11 | 3, 3 | 19 | 7, 4 | 27 | 1, 3 |
| 4 | 8, 2 | 12 | 2, 3 | 20 | 8, 4 | 28 | 3, 2 |
| 5 | 8, 3 | 13 | 5, −1 | 21 | 7, 6 | 29 | 7, 1 |
| 6 | 1, 0 | 14 | 6, −1 | 22 | 8, 5 | 30 | 7, 3 |
| 7 | 0, 0 | 15 | 3, 4 | 23 | 8, 6 | | |

Row −1 is one row above `start` (y = 240 with the shipped values). `SetAction` copies the rectangle into the
button when its action changes. [TODO] not established: which texture the rectangle is cut from and how
`mouseoveroffset` (shipped `0 96`) is applied; a read of the action button's draw / mapping refresh settles
it. The failure texts are the children `<ActionName>_<n>` of `actionfailurecodes` with attribute `tag`, read
for *n* = 0, 1, … until the first missing child, for each of the 31 action names [known] S 00624470.

Layout values of the shipped HUD that a remake needs as defaults (all pixels) [known: `menuingame.xml`]:
selection picture 244 × 244 at bottom left, offset 0 −6; minimap 188 × 188 at bottom right, offset −35 −38;
`cbMessages` 124 × 32 at top right, offset −560 0; `cbMenu` 124 × 32, offset −428 0; goods bar 420 × 32 at top
right; info box 518 × 198 at bottom centre, offset 0 −3, nine-slice border 16; action panel 96 × 131; quest log
370 × 492 centred; messages at `pos="-26 -4"` without alignment (top left of the HUD root), `scaleMax="6"`,
`scaleTime="0.5"`, `alphaMin="0.4"`, `scaleOnRefresh="false"`.

User profile values used by the UI: game speed scale (+0x24, f32; read and written by pause, S 005ea9b0,
S 005da400), smart cursor (+0x31, S 005f0880), autosave choice (+0x34, written by S 006009b0) [known for
the three accesses; the offsets' names inferred].

---

## 7. Save and load

Nothing of the UI is in a save game [inferred: no `nUi` / `nMenu` class is among the sections listed in
[save-format.md](save-format.md) Appendix A; the member with the `NCore::IStoreable` vftable at
`nMenu::Overlay` +0x1a0 is the key under which the overlay is entered in the overlay registry S 0088c1a4
(S 0063dc50), taken to be the `NLogic::Unique` of the overlay's object]. Rebuilt on every match start: all HUD
widgets (`SetupHud`), info boxes, overlays (from the creation callbacks fired while the world loads), the
minimap textures, the statistics panel [inferred].

State that the UI shows and that **is** saved by its owner: player messages (type 8 messages are dropped on
load), quests, statistics histories, military and goods settings, sacrifice state
([save-format.md](save-format.md) §7, [players-victory.md](players-victory.md) §7). The lock maps behind the
build-menu filter are **not** saved; the map script's `onLoaded` sets them again
([players-victory.md](players-victory.md) §7).

Lost on save / load: the selection, the selection mode (a running street placement is cancelled by leaving the
screen), minimap zoom and pan, message filters and scroll position, the chosen good set, statistics graph
choices, tutorial pages and the tutorial button, script minimap symbols (`ActivateGameScreen` clears the
symbol list, S 005d9f10 [known]; so does `Game::OnLeave` S 005eb030), panel positions [inferred for the
rest of the list: none of it is in a saved section].

Outside the save: options and the autosave choice in the user settings file.

---

## 8. Determinism notes

The UI is presentation and command entry. Evidence that it does not touch simulation state:

- Every control handler that changes the world ends in `NComm_Manager::QueueGameCommand`, either through a
  `Send…` function of `nGame::System` or with an event built in the handler itself (`ExecuteAction`
  S 00623730, `SacrificeButton::OnClicked` S 0062f390, `SacrificeTargetPanel::OnChildClicked` S 00626c20)
  (§5 table; [game-commands.md](game-commands.md) §3.1). The sender's own simulation changes only when the
  event comes back through the tick stream (offline: at once, inside the call).
- The per-frame updates only read the simulation [inferred]. UI time is wall-clock time
  (`Timer_GetTotalSeconds`, frame delta); the UI does not call the simulation's random generator [inferred].
  The one random use found is the C runtime `rand()` in `OverlayBuilding::InitAndAttachToParent` S 0063f550:
  each of the ten good icons of a building overlay gets an alpha pulse animation (min 0.8, max 1.0, not
  recursive) whose frequency is `1 + ((rand() & 0x3f) − 32) × 0.03125 × 0.1` (0.9 .. 1.097), and
  `AnimationAlphaPulse::Update` S 00763510 sets `alpha = min + (max − min) × (0.5 + 0.5 × sin(2π × elapsed ×
  frequency))` [known]; [inferred] it runs continuously. It runs when an
  overlay is created, so the number of `rand()` calls differs between machines; a remake must not let the
  simulation share that generator.

Exceptions, all local-only or offline-only:

| What | Effect | Guard |
|---|---|---|
| Pause (`p`) | `TogglePause` S 005da400: saves the profile's speed scale and sets it to 0 (unpause restores it, at least 1.0), pauses all sounds, fades in the pause panel; the HUD logic of `Game::Update` stops (§4) | no effect in network roles 1..4, when the game screen is not open or while the cinematic dialog is open; the key works while the session hangs [known] |
| Chat cheats on Enter: `WhatTheHell` (speed scale 20), `WhatCanEyeSee` (explore the whole map for the local player), `DontWantToLose` (records the current map as completed in the user profile and saves it; `Game::Update` then opens the end screen, §4), `ThatsANiceView` (camera state 0 ↔ 2), `ItsLikeAJackpot` (adds 10 of every entry of the tribe's goods and jobs lists, soldiers included, whose good type is neither 2 nor 3 to `stockB` of the local player's first completed depot, S 00558730; [camera-input-cutscenes.md](camera-input-cutscenes.md) §3.12) | the first, second and last change simulation state directly | offline role (role 0) only; the line is still sent as chat afterwards [known] S 005ec340, S 005eba50 |
| `ComputeSelectionKind` on a soldier in a fight, `MakeUniqueFromState` on a ship | change the **local selection** (not simulation state) | – |
| Lua `menu.*` world edits | [lua-runtime.md](lua-runtime.md) §3.7 | map scripts run identically on all peers |
| Emergency save, autosave notice | file output | – |

Hotkeys and tooltips depend on frame timing and resolution; none of that reaches a command's content except
the cell under the cursor at the moment of the click.

---

## 9. Notes for a Godot reimplementation

**Maps onto engine features**

- Widget tree, visibility, z-order, clipping, nine-slice sprites, bitmap fonts, tab containers, sliders,
  scroll lists, tooltips with delay: `Control` nodes, `NinePatchRect` / `AtlasTexture`, `FontFile` (Godot
  imports AngelCode `.fnt` text files with their page images directly), `TabContainer`, `Tween`.
- Anchoring: the original has only "dock to an edge and stretch along it", "fill", and per-axis
  left / center / right alignment with a pixel offset, all relative to the parent. Each maps to Godot anchors
  (0, 0.5 or 1 per side) plus pixel offsets. Percent tokens map to fractional anchors.
- Elliptic hit areas (`intersectionType="1"`, used by the round buttons and the minimap): override
  `_has_point`.
- Masked sprites (`mask`, `maskUV0/1`): a two-texture shader; needed for the round minimap and the selection
  preview.

**Reproduce exactly**

- The click → command mapping (§3.5–§3.8, [game-commands.md](game-commands.md) §5.1), including which actions
  ask for confirmation, the order of the five commands of the settings confirm, the immediate send of the
  distribution sliders, and "nothing is predicted locally".
- The selection-kind classification (§3.6): it decides which commands a player can issue for an object.
- The build-menu filter by the cell's build flags and by the lock map; the direct-mode send.
- Input swallowing while the session hangs (otherwise commands are dropped silently and the player sees no
  reason), and the hang notice.
- Message type → icon / sound / minimap symbol, left click = go to, right click = delete.
- The statistics time range formula if graphs are to match.
- Localisation lookup: missing key → key shown; `!` prefix convention; key = before first TAB, value = after
  last TAB.

**Free to change**: fade times, the hover highlight, cursor warping, the icon-grid wrap quirk of the build
menu, pixel-exact layout (a remake should scale the HUD with the resolution, which the original does not),
the layout-dependent character hotkeys (map them to physical keys and make them configurable).

**Converter output** (from the player's install, into the cache)

| Source | Output |
|---|---|
| layout XML + `templates.xml` | either scenes (`.tscn`) generated per screen with templates expanded by the rules of §3.1.3, or a neutral JSON tree `{name, type, deployment{pos,size,offset,anchor,alignx,aligny}, shape{…}, text{…}, tip, hotkey, children[]}` with lengths kept as `{value, unit: px|percent}`; the second keeps the data inspectable and lets the remake apply its own scaling |
| `iconconfig.xml` | atlas regions (`AtlasTexture` resources or one JSON `{good|building|sacrifice → texture, x, y, w, h}`) |
| `goodinfosets.xml`, `mapSymbols.xml`, `cursors.xml` | JSON; cursor images as PNG with hot spots |
| `language\<lang>\*.txt` | a translation resource (CSV or `.po`), keys kept verbatim including `!`; decode Windows-1252 to UTF-8 |
| `language\<lang>\fonts\*.fnt` + `*_00.tga` | `.fnt` is AngelCode BMFont text (`info face="Arial" size=13 … charset="ANSI"`), not encrypted; copy it and convert the `.tga` page to PNG, adjusting the page file name in the `.fnt` [known: data] |
| UI textures (`.dds` / `.tga`) | PNG or kept as DDS; atlas pixel coordinates in the layouts refer to the original texture sizes, so textures must not be resized |
| `actionfailurecodes` in `menuingame.xml` | table `{action name, code → text key}` |

The action icon cells and the action names are in the binary, not in the data; a remake ships its own table
of 31 action names (they are listed in [game-commands.md](game-commands.md) §5.1) with the cells of §6 and
reads the icon grid parameters from `actionbuttons`.

---

## 10. Open questions

| # | Question | What settles it |
|---|---|---|
| 1 | Texture of the action icons and how `mouseoveroffset` is applied (the cell per action is in §6) | static read of the draw / mapping refresh of `nMenu::ActionButton` (the reader of button +0x480..+0x49c) |
| 2 | Exact attribute semantics of Slider, Slider2, SliderEx, StackedSlider, ListBox2, Graph, TextScroller, EditEx | static read of each `LoadFromXml` and `Update` (§3.1.9) |
| 3 | Text markup grammar of `TextBlock` (`<r g b a>`, `<right>`, `<c>`, others) | static read of `nUi::TextBlock` layout / draw |
| 4 | Meaning of building property +0x3c = 8 and of the owner test behind selection kinds 0xb / 0xf; of property +0xb0 (taken as "catapult" from the box it selects) and +0xf5 / +0x54 (minimap colours, depot soldier tab) | static read of the `BuildingProperty` loader ([properties-data.md](properties-data.md)) |
| 5 | Answered for the layers (§3.8.6): building overlays are category 0 or 1, soldier overlays 1, fight overlays 4 (always on); `btInfoMap1` never touches the overlay panel. Open: what `btInfoMap1`'s mode changes besides the colour fade (it also enables a per-cell debug text when the local player entry flag +0x50 is set, S 005ef060). Seen in the game: the mode shows the building sites and hides no overlay [live, 2026-10-12]; the colour fade is itself what shows the build-placement icons, which draw only while its alpha is > 0 (§3.4, [rendering.md](rendering.md) §3.14) [known] S 00688c40, S 005eabd0 | static read of the readers of Game +0xfff0 |
| 6 | Answered (§3.5): a right click never steps back. The test S 0078b180 is `planner0.IsConstructionActive() && CanComplete()`; when it holds, the right click keeps mode 3 and `MenuSelection::Update` S 006163f0, which needs the test to be false, ends the mode; otherwise the right click cancels | — |
| 7 | Answered (§3.3.1): the letter hotkeys fail with Caps Lock or Shift (character-code comparison) [live, 2026-10-12] | — |
| 8 | The front-end screens (`Main`, `FreeGamePanel`, `SelectMapDialog`, `Campaigns`), `Book`, `Cinematic`, `Info`, `NetInfo`, `Tutorial` layout details | separate static pass; they use the mechanisms of §3.1–§3.3 |
| 9 | The Root virtual slot +0x84 called after the tree update in `nMenu::System::Update` (§4) | read of the `nUi::Root` vftable |
| 10 | Reader of `Good_NotAvailable` / `Good_MovingToConstructionSite` in `iconconfig.xml`; what names `uiTip.dds` (§6) | string search in the binary |
| 11 | Whether `nMenu::Messages::Update` also runs through the widget tree (it is called directly by the frame function, §4). Partly answered (§3.4): `SetupHud` attaches the panel to the HUD root (Game +0x968), S 005ed700 | read of the Messages vftable |
| 12 | Answered (§3.5 item 2): buildings only. The ray tests the map-object layer's objects of kinds 6 and 8, counts a kind-6 hit and drops a building whose anchor cell its owner has not explored | static: S 00787cc0 ([camera-input-cutscenes.md](camera-input-cutscenes.md), click selection) |
| 13 | What the depot box's `+N` counts: `NTransport::NeedGoods::CountRequestedByAssignment` (§3.6) | static read of that function |
| 14 | Where the message panel's `up`, `down`, `last` buttons stand: at the code positions of S 005f8fa0 or at the layout's (§3.8.5) | read of whether the layout is applied to the buttons after `InitAndAttachToParent` |
| 15 | Whether code hides `btOptions` or `btQuests`, which share `pos="128 199"` in `miniMapBorder` (§3.4) | read of the writers of the two buttons' visibility |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004913f0 | `nUi::Root::HandleInputEvent` | input entry, capture, char → hotkey |
| 00491660 | `nUi::Root::Render` | draws the tree (unless `ui.Hide UI`), then an open combo box's items |
| 004a1370 / 004a0500 | `nUi::Object::RenderRecursive` / `Render` | tree walk; render id stamp |
| 00491ac0 | `nUi::XMLHandler::LoadFromFile` | open, parse, hand to the owner |
| 00491c90 | `nUi::XMLHandler::ReloadAll` | hot reload |
| 004ab3e0 | `nUi_Templates_Load` | loads `templates.xml` |
| 004ab6f0 / 004ab9f0 | `nUi::Configurable::LoadFromXmlWithTemplate` / `LoadChildFromXml` | template resolution |
| 004ab530 | `nUi::Configurable::ApplyTemplate` | template by name from code |
| 004c21d0 | `nUi::Factory::CreateChildrenFromXml` | `controltype` children |
| 004c2730 / 004c28a0 | `nUi::Factory::CreateObjectByName` / `CreateObject` | type name → class |
| 007bf5f0 | initializer of the widget type-name table | 39 names |
| 0060c880 | `nMenu::Factory::CreateObjectByName` | seven `nMenu` widget types |
| 004a76c0 | `nUi::Object::LoadFromXml` | common attributes |
| 004bcb80 | `nUi::Deployment::LoadFromXml` | `pos`, `offset`, `size`, `anchor`, `alignx`, `aligny` |
| 004bc0b0 / 004bc570 | `nUi::Deployment::ApplyAlignment` / `ApplyDock` | layout formulas |
| 004aae00 / 004aac10 | `nUi::Position::LoadFromXml` / `nUi_ParseLengthValue` | `%`, `px`, bare number |
| 004aa700 | `nUi::Shape::LoadFromXml` | sprite attributes |
| 004a8f70 | `nUi::Shape::DrawSliced` | nine-slice draw |
| 004b46d0 / 004b3fe0 | `nUi::Text::LoadFromXml` / `SetText` | text attributes, localisation, case |
| 004afed0 | `nUi::Button::LoadFromXml` | button attributes |
| 004b12d0 / 004b1470 | `nUi::Button::OnClicked` / `OnPressed` | click chain, script events |
| 0049ffc0 | `nUi::Object::HandleHotkey` | hotkey match |
| 004a07a0 / 004ab060 | `nUi::Object::DispatchEvent` / `nUi::Event::DispatchEvent` | routing, event types |
| 004a1b00 / 004a1820 | `nUi::Object::UpdateMouseOver` / `HitTest` | hover arbitration, rectangle / ellipse |
| 004a3920 | `nUi::Object::Update` | per-frame widget update |
| 004b5a70 / 004b5d80 | `nUi::Tip::Update` / `LoadFromXml` | tooltip timing, `<tip>` |
| 00493190 / 00492d80 | `nUi::Cursor::LoadFromXml` / `nUi::StyleData::LoadCursorFromXml` | `cursors.xml` |
| 00490f50 / 00490e90 | `nUi::BaseAction::OnKeyEvent` / `PollAsyncKeys` | key state table |
| 004966d0 / 00496b80 / 00496070 | `ai::ui::Localization::LoadTextFile` / `LoadAllTextFiles` / `GetText` | text tables |
| 004946c0 / 00494000 | `ai::ui::UiResourceManager::GetFont` / `GetOrLoadTexture` | fonts, textures |
| 005dda30 | `nMenu::System::Initialize` | creates all screens, Lua libraries, sounds |
| 004018e0 / 00401260 | `CApplicationEx::FrameTick_InGame` / `App_RenderWorldFrame` | frame order (§4) |
| 005da500 / 005d9800 | `nMenu::System::Update` / `Render` | frame pump |
| 005f2690 | `MinimapSymbolList_TickExpire` | symbol lifetime, one step per menu update |
| 005d9f10 / 005eb030 | `nMenu::System::ActivateGameScreen` / `nMenu::Game::OnLeave` | enter / leave the game screen |
| 005da400 / 005ea9b0 | `nMenu::System::TogglePause` / `nMenu::Game::SetPaused` | pause |
| 005d97a0 / 005d9650 | `nMenu::System::ActivateScreenById` / `CloseAllDialogs` | dialog slots |
| 005d9fd0 | `nMenu::System::StartPendingMap` | enters a match |
| 005ee5d0 / 005ecaf0 | `nMenu::Game::ctor` / `LoadFromXml` | game screen, HUD binding |
| 005ed700 / 005ea650 | `nMenu::Game::SetupHud` / `DestroyHudWidgets` | HUD lifetime; the parents of the fixed members |
| 005efea0 | `nMenu::Game::Update` | per-frame HUD logic, end-of-game checks |
| 005eaae0 / 005eab40 | `nMenu::Game::OnMouseButton0Down` / `nMenu::Game::OnMouseButton1Down` | world clicks |
| 005eb180 / 005ec340 / 005eb230 | `nMenu::Game::OnChar` / `OnKeyDown` / `OnKeyUp` | `p`, `h`, `x`, Enter, Shift, cheats |
| 005eba50 | `nMenu::Game::Cheat_FillStoreWithGoods` | `ItsLikeAJackpot` |
| 005eb850 / 005eb310 | `nMenu::Game::OnButtonClick` / `OnMenuComboSelected` | HUD buttons, game menu |
| 005ef740 | `nMenu::Game::UpdateWorldHoverTooltip` | world tooltip, cursor choice |
| 00617910 / 00617bc0 | `nMenu::MenuSelection::HandleClick` / `HandleRightClick` | click state machine |
| 006156a0 | `MenuSelection_ComputeSelectionKind` | selection kind |
| 00616f40 | `nMenu::MenuSelection::SetSelectionKind` | actions per kind, info box switch |
| 006167b0 | `nMenu::MenuSelection::CreateInfoBoxes` | kind → info box class |
| 006176d0 / 00617770 / 00615e30 | `BeginBuildPlacement` / `SelectCell` / `BeginStreetBuild` | modes 2, 3 |
| 006163f0 / 006162e0 / 00615d10 | `nMenu::MenuSelection::Update` / `Cancel` / `ResetSelection` | mode 3 watch, cancel, reset |
| 00788370 / 00787bf0 / 00787cc0 / 00787a30 / 00787b00 | `nGame::Cursor::SelectAtCursor` / `FindLocalPlayerFlagAtCell` / `PickVisibleEntityAtMouse` / `PickShipAtMouse` / `PickShipRouteAtMouse` | what a left click selects |
| 00558990 | `NVillage::System::FindBuildingAtOrAdjacentCell` | building on the cell or a large neighbour |
| 0078b180 | `Unk_Member10_Vslot2ThenVslot5` | `planner0.IsConstructionActive() && CanComplete()` |
| 0078b850 / 0078b4a0 / 0078b1d0 | `ai::game::StreetBuildMode::Begin` / `IsValid` / `Cancel` | street build mode |
| 0078b220 / 0078be80 / 0078b510 | `StreetBuildMode::PlanSegment` / `OnPlannerCommand` / `RebuildPath` | segment plan, re-plan after a command |
| 0055cdc0 / 0055cd40 | `NVillage::Building::CanDestroy` / `GetDestroyBlockReason` | action 4 gate |
| 0087fb10 | `g_IngameCommandNames` | 31 action command names (tooltips) |
| 00639210 / 00635710 / 00633460 | `nMenu::InfoBoxConstruction::ctor` / `InfoBoxProduction::ctor` / `InfoBoxDepot::ctor` | box constructors |
| 006397e0 / 00635c50 / 00633b60 | `InfoBoxConstruction::Update` / `InfoBoxProduction::Update` / `InfoBoxDepot::Update` | box contents |
| 006350f0 | `nMenu::InfoBoxProduction::LoadFromXml` | width without inputs (S 00635312) |
| 005373b0 | `NLogic::Statistics::GetProductivity` | −1.0 without an entry |
| 006494d0 / 0064b270 / 00649100 | `nMenu::GoodList::ctor` / `LoadFromXml` / `SetEntries` | list defaults, XML overrides, entries into buttons |
| 0064a150 / 0064a3b0 | `GoodList::SetFromGoodIdVector` / `SetFromCountMapAndPendingGoods` | depot list (type filter); per-unit and per-need entries |
| 0062fff0 / 00630530 | `nMenu::GoodButton::ctor` / `SetEntry` | count colours, count formats, indicators |
| 00623600 / 00623da0 / 00623730 | `nMenu::ActionButton::SetAction` / `RefreshAvailability` / `ExecuteAction` | action buttons |
| 006243c0 / 005f05c0 | `nMenu::ActionButton::OnClick` / `IsActionKindInSet_4_8_C_15_17_1C` | confirm rule (actions 4, 8, 12, 21, 23, 28) |
| 00624470 | `nMenu::ActionButton::LoadFromXml` | icon grid parameters, failure texts |
| 00622f40 | `ActionButton_BuildIconRectTable` | icon cell per action (§6) |
| 005f0880 / 005f0c80 | `nMenu::ActionButtonPanel::PositionAtCursor` / `ShowExecuteConfirmation` | panel placement, confirmation |
| 005f0df0 / 005f0ef0 | `nMenu::ActionButtonPanel::LayoutVisibleButtons` / its jump table | panel strip by the number of visible buttons |
| 00638850 / 0064a9b0 / 006309b0 | `nMenu::InfoBoxFlag::ctor` / `GoodList::SetFromFlagGoods` / `GoodButton::Clear` | flag box goods |
| 00615990 / 0068cae0 / 00681300 / 00680ef0 | `MenuSelection::UpdatePreviewImage` / `RenderObjectPreview` / `RenderPreviewTexture` / `MapCamera::ctor` | selection preview picture |
| 006247a0 / 00624700 | `nMenu::AttackSlider::UpdateLabels` / `ExecuteAttack` | attack |
| 00631820 / 00631310 | `nMenu::InfoBox::ctor` / `LoadFromXml` | info box frame |
| 00634db0 / 006340b0 | `nMenu::InfoBoxCreateBuilding::RebuildBuildingButtons` / `OnChildClicked` | build menu |
| 00634160 / 00634210 | `InfoBoxCreateBuilding::EnsureEnabledTabSelected` / `ClearBuildingButtons` | tab kept or first visible; chosen type reset to −1 |
| 004ba3f0 / 004a1090 / 004a0100 | `nUi::TabControl::LayoutTabButtonsHorizontally` / `nUi::Object::SetVisible` / `IsVisible` | visible tabs packed by width; tabs without an enabled button hidden |
| 0064b610 / 0052e510 | `nMenu::BuildingButton::CreateForBuilding` / `Building_TypeFitsConstructionFlags` | button icon and name tooltip; filter test |
| 005eabd0 | `nMenu::Game::StartOverlayColorFade` | info-map tint fade, the build icons' only switch |
| 00632e40 / 0063abc0 | `nMenu::InfoBoxDepot::OnChildClicked` / `nMenu::InfoBoxCasern::IUpdateable_Update` | `0x2001E` senders |
| 0062f390 | `nMenu::SacrificeButton::OnClicked` | `0x20024` / `0x20027` |
| 0062f4e0 / 00617db0 | `nMenu::SacrificeButton::SetSacrifice` / `nMenu::MenuSelection::ResetAndRefresh` | sacrifice button state and fans; selection kind recomputed |
| 0063aec0 / 0063a8c0 | `nMenu::InfoBoxCasern::ctor` / `BindChildControls` | casern box |
| 0063a050 / 00639d30 / 0063a4b0 | `nMenu::InfoBoxTerritoryBuilding::ctor` / binding / fill | territory building box; the dead attacker line |
| 0064ab20 / 00649c00 / 0062fed0 | `nMenu::GoodList::InitWithItemCount` / `SetFromSoldiers` / `GoodButton::InitFromSettler` | soldier slots |
| 0055fe50 | `NVillage::Military::GetToggleSoldierKindBlockReason` | failure codes 1..3 of actions 13 / 14 |
| 00626c20 / 00627210 | `nMenu::SacrificeTargetPanel::OnChildClicked` / `ShowTargetChoice` | `0x20026` |
| 00620970 / 00621480 | `nMenu::IngameSettingsPanel::OnButtonClick` / `OnXmlLoaded` | settings confirm |
| 006412f0 | `nMenu::GoodArrangementPanel::OnSliderValueChanged` | `0x2001F` |
| 00641ab0 | `nMenu::MilitaryPanel::UpdatePlayerRow` | diplomacy view |
| 006225d0 / 00621820 | `nMenu::StatisticPanel::OnXmlLoaded` / `OnSliderChanged` | statistics |
| 005f86a0 / 005f75a0 / 005f73e0 | `nMenu::Messages::Update` / `SetupSlot` / `PollNewMessages` | message HUD |
| 005f8fa0 / 005f7000 / 005f8b90 | `nMenu::Messages::InitAndAttachToParent` / `Detach` / `Refresh` | message rows and buttons; filters and the 7-row window |
| 005f49e0 / 005f3fc0 / 005f4390 / 005f5bb0 | `nMenu::MiniMap::Render` / `UpdateTerritoryOverlay` / `UpdateObjectOverlay` / `RenderSymbols` | minimap |
| 006403c0 / 0063dd30 | `nMenu::OverlayBuilding::UpdateFromBuilding` / `nMenu::OverlaySoldier::UpdateHealthAndColor` | world overlays |
| 0061fb10 / 0061fc60 / 0061faf0 / 0061fa40 / 0061f920 | `nMenu::OverlayPanel::ctor` / `LoadFromXml` / `ToggleLayer` / `SetLayerEnabled` / `alphaPlane` creation | overlay layers; layers 2..4 on at load |
| 0061f980 / 0061f770 / 0061f830 | `OverlayPanel::CreateBuildingOverlay` / `CreateSoldierOverlay` / `CreateFightOverlay` | categories 0 / 1, 1, 4 |
| 005ead80 / 005eae00 / 005eade0 | `nMenu::Game::OnBuildingCreated` / `OnSoldierEnteredFight` / `OnFightAdded` | overlay creation callbacks (slots 2, 10, 13) |
| 0063d870 / 0063e770 / 0064ba40 / 0063e310 | `nMenu::Overlay::SetWorldPosition` / `SetWorldCellWithSizeOffset` / `UpdatePositionFromSettler` / fight overlay position | projection, lift, fade in and out |
| 0064b960 / 0063de90 | `nMenu::OverlaySettler::ctor` / `nMenu::OverlaySoldier::ctor` | the settler overlay only as a base of the soldier overlay |
| 00627650 / 005ea100 | `nMenu::QuestInfoPanel::Update` / `nMenu::QuestLog::RebuildList` | quests |
| 0062c610 / 0062c150 | `nMenu::MessageBox2::SetupButtons` / `GetClickedResult` | message box modes |
| 00600300 / 006009b0 / 006008b0 | `nMenu::Requester::Open` / `Update` / `ExecuteConfirmed` | leave / quit |
| 0060d000 / 0060d430 | `nMenu::LoadSavePanel::Confirm` / `OnButtonClick` | load / save |
| 0061ff50 / 0061fea0 | `nMenu::GameEnded::OnButtonClick` / `nMenu_Game_LeaveMatchToMainMenu` | end of match |
| 00611320 | `nMenu::IconConfig::LoadFromXml` | `iconconfig.xml` |
| 0063f550 | `nMenu::OverlayBuilding::InitAndAttachToParent` | overlay widgets, `rand()` pulse rate |
| 007bfe80 | initializer of the attribute delimiter string S 0087bf34 | `" \n\r\v\t"` |
| 0062a820 / 005f5400 | `nMenu::GoodSetsReader::OnXmlLoaded` / `nMenu::MapSymbolDatas::LoadFromXml` | `goodinfosets.xml`, `mapSymbols.xml` |
