# Lobby screens and dialogs

Evidence tags: **[known]** = read at the address given (S 00xxxxxx = `sadk_noav.exe`) or in the named data
file and key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open. Nothing in this
document was observed in the running game unless a dated live observation of another document is cited.

---

## 1. Purpose and scope

The online lobby has its own user interface, separate from the offline menu (`nMenu`, see
[frontend-screens.md](frontend-screens.md)). It lives in namespace `LobbyMenu` and consists of

- `LobbyMenu::System`: the manager of four full-screen **screens**, a list of modeless **dialogs**, a list
  of modal **message boxes**, the item icon table and the drag-and-drop state;
- the base classes `ScreenBase` and `DialogBase`;
- the screens `EmptyScreen`, `AccountScreen` (login backdrop), `AvatarScreen` (character selection and
  creation) and `WorldScreen` (the HUD of the 3D village);
- the dialogs opened from them: login, create account, message of the day, avatar selection, avatar
  customisation, village server selection, selection info (inventory), mailbox and mail, friends and ignore
  list, hall of fame, report issue, shop, tailor confirmation, the password and stake dialogs, the generic
  message box;
- the input object `LobbyMenu::LobbyAction` (keys of the village) and the component `LobbyMenu::Minimap`.

Out of scope, specified elsewhere: `SetupGameDialog`, `BrowseGameDialog`, `SelectMapDialog`
([match-setup-room.md](match-setup-room.md)); the widgets themselves ([ui-toolkit.md](ui-toolkit.md)); the
3D village (`Lobby::CLobby`, avatars, camera: [lobby-world-client.md](lobby-world-client.md)); the lobby model
behind the dialogs ([lobby-client-state.md](lobby-client-state.md)); the wire formats
([../message-catalog.md](../message-catalog.md),
[../village-and-character-protocol.md](../village-and-character-protocol.md)). The three minigame table dialogs
(Dice, Poker, PawnChess) are only covered as far as the world screen opens them (§3.17); the dialogs are specified in
[minigames-client.md](minigames-client.md), the wire rules in `../message-catalog.md` section "Minigames".

The dialogs never build network messages themselves. They call the lobby model (`LobbyComm::System` and its
members `CharacterManager`, `ServerList`, `PostOffice`, `VillageServerConnection`, `UserCommConnection`,
`RefereeServerConnection`) and subscribe to its observer lists for the results. The message ids in this
document name the message the called model function sends, as recorded in `../message-catalog.md`.

The vtables of this class family are in [../LOBBY_SCREEN_VTABLES.md](../LOBBY_SCREEN_VTABLES.md); §2.3 and
§2.4 give the current slot names against the names used there.

---

## 2. Data model

### 2.1 `LobbyMenu::System` (0x5d8 bytes, vftable S 007d689c, singleton `g_pLobbyMenuSystem` S 008857bc)

Created by `System::CreateInstance(pLobby)` S 0042a490 (`operator new(0x5d8)`), filled by
`System::Initialize` S 0042ad80, both called once from `Lobby::CLobby::StartUp` S 004f8c90, which then calls
`RequestScreen` once [known]; the requested id is a register value, [inferred] 0 (Empty). `System::Shutdown`
S 0042a520 (from `CApplicationEx::Shutdown`) leaves and deletes the four screens, force-closes all dialogs and
boxes and clears +0x04 and the lobby pointer +0x3b8 [known].

| Offset | Type | Meaning | Tag |
|---|---|---|---|
| +0x04 | u8 | initialised (1 after `Initialize`, 0 after `Shutdown`) | [known] S 0042ad80, S 0042a520 |
| +0x08 | i32 | `currentScreen`, -1 = none | [known] S 0042a3a0 |
| +0x0c | i32 | `requestedScreen`, -1 = no switch pending | [known] S 00429900 |
| +0x10 | i32 | `previousScreen` | [known] S 00429ab0 |
| +0x18 | `LobbyDesktop` | root node of the screens and modeless dialogs (name "LobbyDesktop"); `System::GetRootNode` S 00429a10 | [known] S 0042e720, S 0042e820 |
| +0x1f8 | `nUi::Desktop` | root node of the message boxes (name "MessageBoxDesktop"); `System::GetDialogRootNode` S 00429a20 | [known] S 0042ad80 |
| +0x390 | `std::list<DialogBase*>` | open message boxes (head +0x394, size +0x398) | [known] S 0042c390 |
| +0x39c | `ScreenBase*[4]` | the four screens, index = screen id | [known] S 0042ad80 |
| +0x3ac | `std::list<DialogBase*>` | open dialogs (head +0x3b0, size +0x3b4) | [known] S 0042af70 |
| +0x3b8 | `Lobby::CLobby*` | the 3D lobby (`System::GetLobby` S 00429940) | [known] S 0042a3a0 |
| +0x3bc | `ItemIconDB` | item icons from `itemicons.txt` | [known] S 0042ad80 |
| +0x4f4 | `UiDragState` (0xe0) | drag and drop (§2.6) | [known] S 0042a3a0 |

Screen ids (index into +0x39c) [known] S 0042ad80:

| Id | Class | Size | Layout file | vftable |
|---|---|---|---|---|
| 0 | `EmptyScreen` | 0x1e8 | `lobbyEmptyScreen.xml` | S 007d7604 |
| 1 | `AccountScreen` | 0x1e8 | `lobbyAccountScreen.xml` | S 007d7584 |
| 2 | `AvatarScreen` | 0x220 | `lobbyAvatarScreen.xml` | S 007d72fc |
| 3 | `WorldScreen` | 0x3670 | `lobbyWorldScreen.xml` | S 007d6eac |

`lobbyEmptyScreen.xml` is not among the files of `data/lobby/ui/layout` of the install [known: directory
listing] and is never opened: every vtable slot of `EmptyScreen` except the destructor is the `ScreenBase`
body, and `ScreenBase::OnShow` S 0045f380 only attaches the empty container; the `LoadFromFile` call sits in
the `OnShow` of the derived screens (`AccountScreen` S 0043bfd0, `AvatarScreen`, `WorldScreen`) [known: vtable
bytes at S 007d7604]. Screen 0 is an empty full-screen container.

### 2.2 Dialog classes

All are allocated by a `System::Open…Dialog` function that constructs the object, calls `Activate` (slot 3)
and `OnShow` (slot 5) and appends it to the dialog list +0x3ac (`OpenHallOfFameDialog` then also brings the
frame to the front, slot 29). `MessageBoxDialog` is the exception: its three openers append it to the box list
+0x390 (§3.1). Sizes are the `operator new` arguments, layout names the string in the class constructor,
vftables the constructor's store [known, at the opener and the constructor].

| Class | Opener | Size | Layout file | vftable | Opened by |
|---|---|---|---|---|---|
| `LoginDialog` | S 0042af70 | 0xb70 | `lobbyLoginDialog.xml` | S 007d7684 | CLobby mode switch, `AccountScreen`, create-account Cancel |
| `CreateAccountDialog` | S 0042b040 | 0xb68 | `lobbyCreateAccountDialog.xml` | S 007d7804 | `LoginDialog` |
| `MotDDialog` | S 0042b1e0 | 0x1158 | `lobbyMotDDialog.xml` | S 007d7af4 | `LoginDialog::OnLoginSucceeded` |
| `SelectAvatarDialog` | S 0042b2b0 | 0xb60 | `lobbySelectAvatarDialog.xml` | S 007d7bc4 | `AvatarScreen::OnShow` |
| `SelectVillageServerDialog` | S 0042b380 | 0xb58 | `lobbySelectVillageServerDialog.xml` | S 007d7d2c | `AvatarScreen::OnShow` |
| `CustomizeAvatarDialog` | S 0042b110 | 0xb68 | `lobbyCustomizeAvatarDialog.xml` | S 007d79f4 | `AvatarScreen::OnShow`, `WorldScreen::OnShow` |
| `SelectionInfoDialog` | S 0042b9d0 | 0xbc8 | `lobbySelectionInfoDialog.xml` | S 007d8dcc | `WorldScreen::OnShow` |
| `MailboxDialog` | S 0042baa0 | 0xb68 | `lobbyMailboxDialog.xml` | S 007d900c | `WorldScreen::OnShow` |
| `MailDialog` | S 0042beb0 | 0xb70 | `lobbyMailDialog.xml` | S 007d9c64 | `MailboxDialog::OnShow` |
| `FriendIgnoreListDialog` | S 0042bb70 | 0xb60 | `lobbyFriendIgnoreListDialog.xml` | S 007d91e4 | `WorldScreen::OnShow` |
| `HallOfFameDialog` | S 0042b600 | 0xb70 | `lobbyHallOfFameDialog.xml` | S 007d801c | action code 10 (`WorldScreen::DispatchSlotAction`) |
| `ReportIssueDialog` | S 0042bf80 | 0xb58 | `lobbyReportIssueDialog.xml` | S 007d9d54 | `WorldScreen::OnShow` |
| `ShopDialog` | S 0042c050 | 3000 | `lobbyShopDialog.xml` | S 007d9f24 | `WorldScreen::OnShow` |
| `ConfirmTaylorDialog` | S 0042c2c0 | 0xb50 | `lobbyConfirmTaylorDialog.xml` | S 007da1e4 | `WorldScreen::OnShow` |
| `EnterPasswordDialog` | S 0042b450 | 0xb60 | `lobbyEnterPasswordDialog.xml` | S 007d7e04 | minigame matchmaking |
| `SetStackDialog` | S 0042b520 | 0xb88 | `lobbySetStackDialog.xml` | S 007d7eec | minigame matchmaking, minigame tables, pre-game room |
| `SetPasswordDialog` | S 0042c120 | 0xb68 | `lobbySetPasswordDialog.xml` | S 007da054 | pre-game room |
| `GetPasswordDialog` | S 0042c1f0 | 0xb60 | `lobbyGetPasswordDialog.xml` | S 007da12c | game browser |
| `MessageBoxDialog` | S 0042c390, S 0042c730, S 0042ca30 | 0x1a70 | `lobbyMessageBoxDialog.xml` | S 007da32c | screens, dialogs and `CLobbyClient` (S 0042c390 alone has 21 callers) |
| `MiniGameMatchMakingDialog` | S 0042b7b0 | 0xc58 | `lobbyMiniGameMatchMakingDialog.xml` | S 007d84c4 | `WorldScreen::OnShow` |
| `MiniGameManualDialog` | S 0042b6e0 | 0xb60 | `lobbyMiniGameManualDialog.xml` | S 007d810c | `WorldScreen::OnShow` |
| `MinigameDialog_Observer` | S 0042c660 | 0xb60 | `lobbyMinigameDialog_Observer.xml` | S 007da404 | `WorldScreen::OnShow` |
| `MinigameDialog_Dice` / `_Poker` / `_PawnChess` | S 0042b880 | 0x13c8 / 0xf68 / 0xbf0 | `lobbyMinigameDialog_*.xml` | S 007d879c / 007d8a94 / 007d8ccc | `WorldScreen::EnterMiniGameMode` |

`WorldScreen::OnShow` S 004389d0 also opens `SetupGameDialog` and `BrowseGameDialog` (`match-setup-room.md`)
[known].

Callers of the password and stake openers [known, caller lists of S 0042b450, S 0042b520, S 0042c120,
S 0042c1f0]: `EnterPasswordDialog` ← `MiniGameMatchMakingDialog::OnPhaseAction` S 00444330; `SetStackDialog` ←
`MiniGameMatchMakingDialog::OnPasswordEntered` S 004432a0 / `OnPhaseAction` S 00444330,
`SetupGameDialog::HandleSettingsClicks` S 00457d50, `MinigameDialog::OpenSetStackDialog` S 00461470;
`SetPasswordDialog` ← S 00457d50; `GetPasswordDialog` ← `BrowseGameDialog::HandleButtonClicks` S 004588e0.

### 2.3 `LobbyMenu::ScreenBase` (0x1e8 bytes, vftable S 007da504, 25 slots)

Base `nUi::XMLHandler` (layout file name as `std::string` at +0x04) [known] S 0045f420.

| Offset | Type | Meaning | Tag |
|---|---|---|---|
| +0x20 | observer list | "deactivated" observers, fired by `Deactivate` with (this, arg) | [known] S 0045f6f0 |
| +0x2c | observer list | "left" observers, fired by `OnLeave` / `DialogBase::Leave` with (this, arg) | [known] S 0045f710, S 004612d0 |
| +0x38 | `System*` | owner | [known] S 0045f420 |
| +0x3c | node* | parent UI node: `System+0x18`, or the explicit parent of `ctor_ExplicitParent` S 0045f520 | [known] |
| +0x40 | `nUi::Object` | embedded container, kind 0x21, name "ScreenContainer" | [known] S 0045f420 |
| +0x1d8 | bool | `inputEnabled`, initial 1 | [known] |
| +0x1d9 | bool | `visible`, initial 1 | [known] |
| +0x1dc | i32 | `tag`, initial 0: a number the opener assigns to tell its dialogs and boxes apart | [known] S 0045f2b0 |
| +0x1e0 | bool | `active`, initial 0 (set by `Activate`, cleared by `Deactivate`) | [known] S 0045f170, S 0045f6f0 |
| +0x1e1 | bool | `shown`, initial 0 (set by `OnShow`, cleared by `OnLeave`) | [known] S 0045f380, S 0045f710 |

Vtable, with the names of `../LOBBY_SCREEN_VTABLES.md` in the last column [known: vtable bytes at
S 007da504, function bodies]:

| Slot | Offset | Name | Base body | Name in LOBBY_SCREEN_VTABLES.md |
|---|---|---|---|---|
| 0 | +0x00 | scalar deleting destructor | S 0045f360 | Destructor |
| 1 | +0x04 | `BuildWidgets(xmlDoc, xmlNode)`: the XML layout callback. Returns false unless `IsShown`; else slot 24, delete the container's owned children, load the container from the node | S 0045f180 | RouteInputToContainer |
| 2 | +0x08 | `IsActiveAndShown` | S 0045f270 | IsVisibleAndEnabled |
| 3 | +0x0c | `Activate` | S 0045f170 | SetFlag1e0 |
| 4 | +0x10 | `Deactivate(arg)` | S 0045f6f0 | OnHide |
| 5 | +0x14 | `OnShow`: attach the container to the parent node, dock it, size 1.0 × 1.0, not focusable | S 0045f380 | OnShow |
| 6 | +0x18 | `OnLeave(arg)`: notify the "left" observers, detach the container | S 0045f710 | OnLeave |
| 7 | +0x1c | `IsShown` | S 0045f2e0 | GetFlag1e1 |
| 8 | +0x20 | `Update` (per frame) | empty S 005657b0 | Update |
| 9 | +0x24 | `HandleButtonClicks` → bool | S 0045f2d0 (returns `inputEnabled`) | HandleInput |
| 10 | +0x28 | render hook | empty | vf28 |
| 11 | +0x2c | `SetVisible(bool)`: stores +0x1d9, container vtbl+0x24 | S 0045f1e0 | SetConnectingOverlayEnabled |
| 12 | +0x30 | `Hide`: clears +0x1d9, container vtbl+0x28 | S 0045f200 | ClearConnectingOverlayEnabled |
| 13 | +0x34 | `IsVisible` (returns +0x1d9) | S 0045f220 | GetConnectingOverlayEnabled |
| 14 | +0x38 | `SetInputEnabled(bool)` | S 0045f230 | SetFlag1d8 |
| 15 | +0x3c | `DisableInput` | S 0045f240 | ClearFlag1d8 |
| 16 | +0x40 | `IsInputEnabled` | S 0045f250 | GetFlag1d8 |
| 17 | +0x44 | `IsActive` | S 0045f260 | GetFlag1e0 |
| 18 | +0x48 | `GetTag` | S 0045f2a0 | GetField1dc |
| 19 | +0x4c | `SetTag(int)` | S 0045f2b0 | SetField1dc |
| 20, 21 | +0x50, +0x54 | `GetParentNode` | S 0045f2c0 | GetField3c |
| 22, 23 | +0x58, +0x5c | `GetScreenContainer` (returns this+0x40) | S 0048cfa0 | GetScreenContainer |
| 24 | +0x60 | `PreBuildWidgets`: called by `BuildWidgets` before the old children are deleted | empty | vf60 |

The "connecting overlay" names of that document describe one use of slots 11 to 13 by `SetupGameDialog`; the
slots are the plain visible flag of every screen and dialog [known] S 0045f1e0, S 00460800.

### 2.4 `LobbyMenu::DialogBase` (0xb48 bytes, vftable S 007da62c, 38 slots)

Extends `ScreenBase` [known] S 00460590:

| Offset | Type | Meaning | Tag |
|---|---|---|---|
| +0x1e8 | `nUi::Dialog` | the frame; every widget of the dialog is a child of it | [known] |
| +0x418 | `nUi::Label` | title | [known] |
| +0x640 | `nUi::PictureButton` (kind 0xc) | close button | [known] |
| +0xb40 | u8 | close requested, initial 0; `System` deletes the dialog on its next update | [known] S 00460790, S 0042a1c0 |
| +0xb41 | u8 | initial 0, set by `DialogBase::OnShow`; no reader was found in the functions read | [known] S 00460f50 |
| +0xb42 | u8 | "closed by `System::CloseDialogs(false)`", initial 1 | [known] S 00460590, S 00429de0 |

Slots 0 to 24 are those of `ScreenBase`; the `DialogBase` bodies and the added slots [known: vtable bytes at
S 007da62c]:

| Slot | Offset | Name | Body |
|---|---|---|---|
| 1 | +0x04 | `BuildWidgets` (§3.2); returns false unless `IsActive` | S 004611a0 |
| 3 | +0x0c | `Activate`: a jump to `ScreenBase::Activate` S 0045f170 | S 00460780 [known: code bytes `e9 eb e9 ff ff`] |
| 4 | +0x10 | `Deactivate` → `ScreenBase::Deactivate(this, 0)`, whatever the argument | S 0043bf40 |
| 5 | +0x14 | `OnShow`: create the frame under `GetParentNode()`, the title label and the close button; set +0xb41 and `shown` | S 00460f50 |
| 6 | +0x18 | `Leave(arg)`: notify the "left" observers, detach close button, title and frame, clear `shown` | S 004612d0 |
| 8, 10 | +0x20, +0x28 | `Update`, render hook: a jump to the empty function S 005657b0 | S 0043bf60 [known: code bytes `e9 4b 98 12 00`] |
| 9 | +0x24 | `HandleButtonClicks` (§3.2) | S 004608d0 |
| 11 | +0x2c | `SetVisible(bool)`: frame vtbl+0x24(bool), stores +0x1d9 | S 00460800 |
| 12 | +0x30 | `Hide`: frame vtbl+0x28(), clears +0x1d9 | S 00460830 |
| 13 | +0x34 | `IsVisible`: frame vtbl+0x2c() and +0x1d9 | S 00460850 |
| 14 | +0x38 | `SetInputEnabled`: frame vtbl+0x20(bool) = `nUi::Object::SetEnabled`; +0x1d8 is not written | S 00460880 |
| 15 | +0x3c | `DisableInput`: frame vtbl+0x20(0); +0x1d8 is not written | S 00460960 |
| 16 | +0x40 | `IsInputEnabled`: the frame's `enabled` byte (this+0x2cc = frame+0xe4) is set and the frame's parent (this+0x338 = frame+0x150), if there is one, is enabled through all its ancestors | S 00460980 |
| 22, 23 | +0x58, +0x5c | `GetScreenContainer`: returns the frame (this+0x1e8) | S 004608a0 |
| 25 | +0x64 | `SetAnchoredPosition(hAnchor, vAnchor, offsetX, offsetY)` (§3.2) | S 00460be0 |
| 26 | +0x68 | `SetPosition(nUi::Position*)` | S 00460e90 |
| 27 | +0x6c | `GetFrameBounds` | S 00460ad0 |
| 28 | +0x70 | `SetRect` (moves the frame by the delta in the argument, returns the frame bounds) | S 00460ed0 |
| 29 | +0x74 | `Relayout`: `nUi::Object::BringToFront(frame)` | S 004607f0 |
| 30 | +0x78 | `IsCursorOverFrame` | S 00460b00 |
| 31 | +0x7c | `Close`: if +0xb40 is 0 call slot 37, then +0xb40 = 1 | S 00460790 |
| 32 | +0x80 | `IsCloseRequested` (returns +0xb40) | S 004607b0 |
| 33, 34, 35 | +0x84..+0x8c | set / clear / get +0xb42 | S 004607c0, S 004607d0, S 004607e0 |
| 36 | +0x90 | `OnCancel` → bool: called when the close button is clicked (and by walk-away watches); the base returns false | S 0041ecc0 |
| 37 | +0x94 | hook run once by `Close` before the flag is set; base empty | S 005657b0 |

In `../LOBBY_SCREEN_VTABLES.md` slots 25 to 35 carry a `SetupGameDialog_` prefix and are listed as shared by
about 30 vtables: they are these `DialogBase` slots [known: same addresses in S 007da62c].

No `DialogBase` slot writes +0x1d8 (`inputEnabled`), so for a dialog that byte keeps its initial 1 and the
"input disabled" test of `HandleButtonClicks` never fails on it; a dialog is disabled through its frame
(slots 14 to 16), which stops the widgets from latching clicks [known for the bodies; inferred for the
consequence].

Slot 36 per class [known: the 8 bytes at vftable + 0x90 of each class (slots 36 and 37), and the bodies]. A
false result means the dialog is not closed by `DialogBase::HandleButtonClicks`:

| Class | Slot 36 | Effect of the close button |
|---|---|---|
| `LoginDialog`, `CreateAccountDialog`, `MotDDialog`, `SelectAvatarDialog`, `SelectVillageServerDialog`, `CustomizeAvatarDialog`, `EnterPasswordDialog`, `SetPasswordDialog`, `GetPasswordDialog`, `ConfirmTaylorDialog`, `MessageBoxDialog` | S 0041ecc0 (false) | click is consumed, nothing else happens |
| `HallOfFameDialog` | S 005e4e90 (true) | dialog is closed and deleted |
| `SetStackDialog` | S 00441530 | reports (-1, cancelled = 1) to its callback, drops the callback, dialog is closed |
| `MailboxDialog` | S 004500d0 | clears the three compose fields (slot 37 S 00450170), hides the dialog and the child `MailDialog` |
| `MailDialog`, `FriendIgnoreListDialog`, `MinigameDialog_Observer`, `MiniGameManualDialog` | S 0045ecf0 | `Hide` (slot 12), dialog kept. `MailDialog` alone also overrides slot 37 with S 00457fb0 (a jump to its slot 12) |
| `MiniGameMatchMakingDialog` | S 00443060 | CLobby vtbl+0xd4(1) (world picking on again), `Hide`; dialog kept |
| `ShopDialog` | S 0045b920 | `Hide`, ends a running drag, `VillageServerConnection::ClearShop` |
| `ReportIssueDialog` | S 0045ade0 | clears both description fields, `Hide` |
| `SelectionInfoDialog` | S 0044d210 | if the current screen is 3: `nUi::Button::SetMarked(false)` S 004af720 on `WorldScreen+0x3584` (the `ObjectInspector` toggle, S 00431d00); returns false. The world screen hides the dialog in its next `Update` because the toggle is off (§3.11) |

### 2.5 `MessageBoxDialog` (0x1a70 bytes)

| Offset | Type | Meaning | Tag |
|---|---|---|---|
| +0xb48 | observer list | result listeners, called with (box, result) | [known] S 0045e670, S 0045ebe0 |
| +0xb58, +0xfc0, +0x1428 | `nUi::Button` ×3 | button 1, 2, 3 | [known] S 0045e670 |
| +0x1890 | `nUi::TextBlock` | message text (layout node `Message`), font `body_arial`, style `text` | [known] S 0045e800, S 0045e3a0 |
| +0x1a30 | i32 | button set, 0 after construction | [known] S 0045e670, S 0045e7c0 |
| +0x1a34 | `std::string` | title | [known] S 0045e7c0 |
| +0x1a50 | `std::string` | message | [known] S 0045e7c0 |

`Setup(title, message, buttonSet)` S 0045e7c0 (slot 38, the only slot `MessageBoxDialog` adds) stores the
three values and sets `active` [known].

Button sets and results [known] S 0045e3a0 (XML node bound to each button), S 0045ebe0 (results):

| Set | Name | Button 1 → result | Button 2 → result | Button 3 → result |
|---|---|---|---|---|
| 1 | Ok | `OkayButton` → 1 | hidden | hidden |
| 2 | Yes / No | `YesButton` → 2 | `NoButton` → 3 | hidden |
| 3 | Retry / Ignore / Cancel | `RetryButton` → 4 | `IgnoreButton` → 5 | `CancelButton_A` → 6 |
| 4 | Cancel | `CancelButton_B` → 6 | hidden | hidden |
| 5 | no buttons | hidden | hidden | hidden |

A hidden button is bound to the XML node `HiddenButton`. Any other set value (0 included) makes
`BuildWidgets` fail [known] S 0045e3a0. Result 2 is therefore always "Yes", the confirming answer. A click on
button 2 is ignored outside sets 2 and 3, one on button 3 outside set 3, and one on button 1 in set 5
[known] S 0045ebe0; a box of set 5 can therefore never report a result.

### 2.6 `UiDragState` (0xe0 bytes at `System+0x4f4`)

| Offset | Type | Meaning | Tag |
|---|---|---|---|
| +0x00 | i32 | state: 0 idle, 1 pressed (not moved), 2 dragging, 3 carried (picked up by a click) | [known] S 0042d020, S 0042d0c0, S 0042d320 |
| +0x04 | i32 | payload A = drag kind: 1 inventory item, 2 shop stock item; -1 when idle | [known] S 00429b60, S 00429bd0, S 0042e140 |
| +0x08 | i32 | payload B = the dword at slot widget +0x590: slot index (low 16 bits, i16) and container (high 16 bits, i16); -1 when idle | [known] S 00429b60, S 00429bd0 |
| +0x0c | i32 | payload C = item id (kind 1: the slot widget's data value +0x28; kind 2: the stock entry's item id); 0 when idle | [known] S 00429b60, S 00429bd0, S 0044d430 |
| +0x10 | `nUi::Shape` | the icon drawn at the cursor | [known] S 0042d020 |
| +0xa8..+0xb4 | UI coordinate pair | cursor position at the press | [known] |
| +0xbc..+0xc8 | UI coordinate pair | current cursor position | [known] |
| +0xcc | u8 | "the receiver under the cursor accepts the payload" (computed while drawing) | [known] S 0042df80 |
| +0xd0 | vector of `IDropReceiver*` | registered drop targets | [known] S 0042dd10 |

`IDropReceiver` (vftable S 007d6c50, 6 slots) [known: use in S 0042dda0, S 0042e140, S 0042d740]: slot 1
`ContainsPoint(pos)`, slot 2 `IsAccepting()`, slot 3 `CanDrop(kind, payloadB, payloadC, pos)`, slot 4
`GetPriority()` (the sort key of the receivers under the cursor), slot 5
`OnDrop(kind, payloadB, payloadC, &cursorPos, &icon)` → 1 = accepted. Receivers: `WorldScreen` (face at
+0x1ec), `SelectionInfoDialog` (+0xb48), `ShopDialog` (+0xb48), each registered in its `OnShow`
(`RegisterDropReceiver` S 0042dd10, no duplicates).

`CanDropAt` S 0042dda0 [known]: collect the receivers with `IsAccepting()` and `ContainsPoint(pos)`, sort
them by priority, and ask `CanDrop` of the first one only. `EndDrag(cancel)` S 0042e140: unless cancelled, and
only in state 2 or 3, if `CanDropAt` is true the collected receivers get `OnDrop` in sorted order until one
returns 1; then the state is reset in every case. The world screen's receiver has `ContainsPoint` = always
true and priority 0, and its `CanDrop` needs kind 1, the cursor over no hovered widget and CLobby vtbl+0xd0
false [known] vtable bytes at S 007d6e7c, S 00431bd0. CLobby vtbl+0xd0 is S 004facf0, "the dword at
CLobby+0x60 is not 0" [known: vtable bytes at S 007e599c]; +0x60 is the hovered world object
(`pHoverObj`, [lobby-world-client.md](lobby-world-client.md)), so an item cannot be dropped on the world
while the cursor is over a world object [inferred].

Container ids of a slot widget (i16 at widget +0x592; the index is the i16 at +0x590) come from the layout
attributes `slotType` and `slotIndex` of the `InventoryButton` nodes (S 004bd6c0) [known:
`lobbySelectionInfoDialog.xml` `Pet slotType="5"`, `RightHand slotType="3"`, `LeftHand slotType="4"`,
`InventorySlot0..11 slotType="0" slotIndex="0..11"`; `lobbyShopDialog.xml` `StockSlot0 slotType="6"`]:
0 backpack, 2 head, 3 right hand, 4 left hand, 5 pet, 6 shop stock. An item may go into container 2 / 3 / 4 / 5
only if bit 0 / 1 / 2 / 3 of the flags dword at +0x40 of its item definition is set and the definition is
valid; the backpack accepts everything; any other container refuses [known] S 0044d390.

### 2.7 `AvatarScreen` (0x220 bytes) [known] S 00439e30, S 0043a140

| Offset | Meaning |
|---|---|
| +0x1e8 | `viewMode`: 0 create, 1 select (initial), 2 entering the village |
| +0x1ec | `CharacterManager*` (`LobbyComm::System+0x140`), set in `Activate` |
| +0x1f0 | `ServerList*` (village servers), set in `Activate` |
| +0x1f4, +0x1f8, +0x1fc | `SelectAvatarDialog*`, `SelectVillageServerDialog*`, `CustomizeAvatarDialog*` |
| +0x200 | the open wait box (tag 0x3000), or 0 |
| +0x204 | `StartGameButton` (kind 0xc), child of `AvatarScreenCustomizeTools` |
| +0x208 | `BackButton` (kind 0xc), child of `AvatarScreenTitleLabelBackground` |
| +0x20c | `NameEdit` (EditEx, kind 7) |
| +0x210 | `ResetPositionLabel` (kind 9) |
| +0x214 | `ResetLoginPosition` (toggle, kind 0xc; checked state at widget +0x2ec) |
| +0x218, +0x219 | buttons enabled / visible (all four flags are 0 after construction) |
| +0x21a, +0x21b | dialogs enabled / visible |
| +0x21c | `CodersRule`: boolean attribute of the root node of `lobbyAvatarScreen.xml` |
| +0x21d | latch "create mode was entered automatically once" |

### 2.8 `WorldScreen` (0x3670 bytes) [known] S 00434ab0, S 00438050, S 004389d0

Three vtable faces: `ScreenBase` at +0x00 (S 007d6eac), `NComm::IMessageCallbacks` at +0x1e8 (S 007d6e98),
`IDropReceiver` at +0x1ec (S 007d6e7c). Widget kinds bound by `BuildWidgets` S 00438050: the three action
buttons and `ObjectInspector` are kind 0xd (`OverlayButton`), `Friends` and `MatchmakingIndicator` kind 0xc,
the three menus kind 0x14, labels kind 9, pictures kind 0xe [known].

| Offset | Meaning |
|---|---|
| +0x1f0 | `nUi::ChatSystem` (the chat box; widget node `Chat`) |
| +0x3548 | chat channel id of the minigame table the player sits at, 0 = none |
| +0x354c | chat channel that was active before the table was entered |
| +0x3550..+0x355c | `SelectionBackground`, `SelectionPicture`, `SelectionName`, `SelectionLevel` |
| +0x3560, +0x3564, +0x3568 | `SelectionActionA`, `B`, `C`: the three action buttons |
| +0x356c | `actionSlots.codes[3]` (§3.9) |
| +0x3578 | `actionSlots.params[3]` |
| +0x3584 | `ObjectInspector` (toggle that shows the selection info dialog) |
| +0x3588 | `Minimap` component (§3.10) |
| +0x35bc | `SelectionInfoDialog*` (tag 1) |
| +0x35c0 | `MailboxDialog*` (tag 2) |
| +0x35c4 | `FriendIgnoreListDialog*` (tag 3) |
| +0x35c8 | `SetupGameDialog*` (tag 5) |
| +0x35cc | `BrowseGameDialog*` (tag 6) |
| +0x35d0 | `ReportIssueDialog*` (tag 7) |
| +0x35d4 | `ShopDialog*` (tag 8) |
| +0x35d8 | `MiniGameMatchMakingDialog*` (tag 7) |
| +0x35dc | `MiniGameManualDialog*` (tag 7) |
| +0x35e0 | `CustomizeAvatarDialog*` (tailor) |
| +0x35e4 | `ConfirmTaylorDialog*` (tag 10) |
| +0x35e8 | `MinigameDialog_Observer*` (tag 0xb) |
| +0x35ec | `MainMenu` (DropDownMenu) |
| +0x35f0 | `Friends` (toggle button) |
| +0x35f4 | `SelectServerMenu` (DropDownMenu) |
| +0x35f8, +0x35fc, +0x3600, +0x3604, +0x3608 | `Clock`, `ConnectionQuality`, `MailIndicator`, `MatchmakingIndicator`, `ServerName` |
| +0x360c | `SelectionMiniGameIcons` |
| +0x3610 | `EmoteButton` (DropDownMenu) |
| +0x3614 | vector of `std::string`: chat text of each quick emote |
| +0x3624, +0x3625 | referee login pending / armed |
| +0x3628 | referee login delay, in frames |
| +0x362c | referee login tries |
| +0x3630 | selected actor (`ActorProxy*`, the result of CLobby vtbl+0x9c), 0 when a scene object is selected |
| +0x3634 | key of the selected scene object, -1 = none |
| +0x3638 | latch "the selection changed" |
| +0x363c | float[3]: position of the local avatar (CLobby vtbl+0x94 = `CLobby::GetLocalAvatar` S 004f50f0, the same body as vtbl+0x90 [known: vtable bytes at S 007e599c]) latched when the inspector was switched on or a shop opened |
| +0x3648 | user id waiting in the add-friend / add-ignore confirmation |
| +0x364c | `nMenu::OptionsPanel*` (0x330 bytes), created on first use |
| +0x3650 | `std::string`: name of the last player who whispered to us |

Tags are what `WorldScreen::OnDialogClosed_ForgetDialog` S 00431860 compares (tag and pointer) to clear the
cached pointer when a dialog reports its deactivation [known]; three dialogs share tag 7 and are told apart
by the pointer. The tailor's `CustomizeAvatarDialog` gets tag 9 in `OnShow` (`SetTag(9)` at S 00439160), which
S 00431860 does not test [known]. `OnShow` S 004389d0 creates all these dialogs, clears their +0xb42 flag
(slot 34) and hides all of them except the `SelectionInfoDialog`; initial positions (`SetAnchoredPosition(h,
v, 0, 0)`, both pixel offsets 0 in every call): selection info (1, 2) = bottom centre, friends and tailor
dialog (0, 1) = left edge, mailbox, room, game browser, report issue, shop, minigame manual and matchmaking
(1, 1) = centred; `ConfirmTaylorDialog` and `MinigameDialog_Observer` get no position call [known: the
disassembly of S 004389d0].

---

## 3. Rules and algorithms

### 3.1 Screen switching and the dialog manager

**Requesting a screen.** `System::RequestScreen(id)` S 00429900 only stores `requestedScreen`. The switch
happens at the start of the next `System::Update` [known] S 0042a860, S 00429ab0:

1. `previousScreen = currentScreen; currentScreen = requestedScreen; requestedScreen = -1`.
2. If there was a screen: if it `IsShown`, `OnLeave(0)`; then `Deactivate(0)`; then the screen root node
   (`System+0x18`) vtbl+0x20(0) (`SetEnabled(false)`).
3. If there is a new screen: root node vtbl+0x20(1); `Activate()`; `OnShow()`; `Update()`.

In a frame that switches screens `System::Update` only sweeps the message boxes and dialogs for close
requests (before and after the switch) and returns: no localisation reload, cursor or drag update, no
`Update` of boxes or dialogs, no click dispatch and no `LobbyAction` call [known] S 0042a860. In any other
frame the current screen gets `Update` (and clicks) only while it `IsActive` [known] S 0042a860, S 0042a020.
`DispatchButtonClicks` is also called outside `Update`, by `CLobby::OnMouseButtonDown` S 004f4fd0 and
`OnMouseButtonUp` S 004f5010 while the CLobby mode is 2 or 3 [known].

**Who requests which screen** [known: the 12 calling functions of S 00429900]:

| Request | By | When |
|---|---|---|
| [inferred] 0 Empty | `CLobby::StartUp` S 004f8c90 | once, right after `System::Initialize` (§2.1) |
| 1 Account | `CLobby::ProcessModeTransition` S 004f5950 | entering the lobby (CLobby mode 0 or 1 → 2 or 3, requested mode ≠ 2) while the `LobbyComm::System` state is 1, or in any state other than 3 / 11 after calling `LobbyComm::System::Logout`. The function then runs `System::Update(true)` at once and opens the login dialog centred. State names (1 Disconnected, 3 Authorized, 11 VillageLeft): [lobby-client-state.md](lobby-client-state.md) |
| 2 Avatar | S 004f5950 | entering the lobby in state 3 or 11 without an automatic village entry |
| 2 Avatar | `MotDDialog` Okay; `CreateAccountDialog` success box | §3.4, §3.5 |
| 2 Avatar | `WorldScreen` | village connection logged out or disconnected; referee login given up (§3.16) |
| 2 Avatar | `CLobbyClient::OnVillageLoginFailed` S 00503800 | unless a re-entry is pending with fewer than 3 retries (then only a retry is armed: timeout 2.5, retries + 1): request screen 2, `CloseDialogs(false)`, box `!ERROR_DIALOG` / `!LOGIN_FAILED_TEXT` (Ok) [known] |
| 3 World | S 004f5950 | entering the lobby with requested CLobby mode 2 (followed by `System::Update(true)`) |
| 3 World | `CLobbyClient::OnEnterWorld` S 00503940 | the server pushed EnterWorld (1000) and no re-entry is pending; followed by `CloseDialogs(false)` |
| 0 Empty | `AvatarScreen` | Back in select mode, lobby logged out, connection-lost box closed; together with CLobby vtbl+0x2c(0) = leave the lobby to the main menu |
| 0 Empty | S 004f5950 | leaving the lobby (CLobby mode 2 or 3 → 0 or 1): `CloseDialogs(false)`, request 0, `System::Update(true)` |

On entering the lobby in state 3 / 11 while the current CLobby mode is 1, `ProcessModeTransition` first
tries `ServerList::FindBestVillageServer(g_ClientProtocolVersion, cached village
server id)`; if one is found it selects the character with the local perm id, selects that server and
requests village entry directly (CLobby `RequestEnterVillage(0)`), without requesting a screen; if none is
found it still selects that character and requests screen 2 [known] S 004f5950. The CLobby mode
machine itself is specified in [app-shell.md](app-shell.md).

**Dialogs.** A dialog is in the list +0x3ac from its opener until it is deleted. `System::UpdateDialogs`
S 0042a1c0 walks the list every frame: an active dialog whose `IsCloseRequested` is true gets `OnLeave(0)`
(if shown), `Deactivate(0)`, is deleted and unlinked; every other active dialog gets `Update()`. An inactive
dialog is skipped. `System::CloseDialogs(force)` S 00429de0 handles at once every dialog whose +0xb42 flag
(slot 35) is set, or all if forced: an active one gets `OnLeave(force)` (if shown) and `Deactivate(force)`;
then, if it is inactive, it is deleted and unlinked. It runs unforced (wrapper S 0042a640) when the world
screen falls back to the avatar screen (village logged out or disconnected, referee login given up), on
EnterWorld, on a failed village login and when the lobby is left [known: the six callers of S 0042a640];
forced from `System::Shutdown` S 0042a520. `AvatarScreen` clears the flag on its three dialogs (slot 34) and
requests their close itself (slot 31) in `OnLeave` [known] S 0043b3a0, S 00439870; `WorldScreen` does the
same for all the dialogs it opens in `OnShow` (§2.8) [known] S 004389d0, S 00439410. The unforced call
therefore removes only the remaining dialogs: login, create account, message of the day, hall of fame, mail,
the password and stake dialogs and the minigame table dialogs [inferred: these classes have no slot-34 call
in the functions read].

**Message boxes are modal.** `System::ShowMessageBox(title, message, buttonSet)` S 0042c390 [known]:

1. A title or message that starts with `!` is replaced by the localised text of that key.
2. Construct the box (parent node `System+0x1f8`), `Setup` (slot 38), `OnShow`, `SetAnchoredPosition(1, 1,
   0, 0)` (centred), one `nUi::Object::Update` S 004a3920 of the frame (its second vtable face at frame+4,
   S 007e1254, slot 1 [known: vtable bytes]), append
   to the list +0x390.
3. If the current screen is active: `SetEnabled(false)` on its parent node (slot 20, vtbl+0x20(0)); the same
   on the parent node of every active dialog (`SetDialogsInputEnabled(false)` S 0042a330). For screens and
   dialogs that parent node is the screen desktop `System+0x18` itself.

`ShowMessageBoxWithCallback(…, obj, fn)` S 0042c730 also subscribes a result listener;
`ShowMessageBoxWithCallbackAndTag(…, obj, fn, tag)` S 0042ca30 also stores `tag` in the box (+0x1dc).
While at least one box exists [known] S 0042a020, S 0042a6b0, S 0042a1c0:

- only message boxes (active and shown) receive `HandleButtonClicks`;
- the message-box desktop is visible and enabled, the screen desktop (`System+0x18`) is disabled; without a
  box the message-box desktop is hidden and disabled and the screen desktop enabled (set every frame);
- when the last box is deleted, the parent node of the current screen (if active) and of all active dialogs is
  enabled again.

A click on a box button notifies the listeners with (box, result) and calls `Close`; the box is deleted on
the next update [known] S 0045ebe0. A wait box (set 4 or 5) is closed by its owner through slot 31.

**Size of a message box** [known] S 0045e800: `OnShow` creates the three buttons and the text block, loads
the layout, sets title and text, then: height = max(text height in pixels + 159, 224) pixels; the text block
gets that height minus 159. Every dialog title: font `Head_Garamond`, colour bytes (254, 239, 124), placed at
half the frame width, 14 px from the top [known] S 00460f50; that it is centred there (text property 8) is
[inferred].

### 3.2 Common dialog behaviour

- `DialogBase::BuildWidgets` S 004611a0: only while the dialog is active: slot 24, delete the frame's owned
  children, load the frame from the XML node `Dialog`, the title from `Title` and the close button from
  `DialogCloseButton`; when that node is missing the button gets the template `NormalDialog_CloseButton`
  [known].
- Derived `BuildWidgets` look their widgets up by name under the frame and keep the pointer only if the
  widget kind matches (7 EditEx, 9 Label, 0xc PictureButton / toggle, 0xd OverlayButton, 0xe Picture,
  0x14 DropDownMenu, 0x16 ListBox2, 0x18 TextBlock, 0x22 ProgressBar, 0x26 InventoryButton, 4 SliderEx,
  10 Button; class names as in [ui-toolkit.md](ui-toolkit.md)); a wrong kind gives a null pointer [known,
  e.g. S 0043c380, S 0044ed80, S 00438050].
- `DialogBase::HandleButtonClicks` S 004608d0: returns false (stop) if the dialog is not visible (slot 13),
  +0x1d8 is 0 or a close is already requested. If the close button exists in the tree, is enabled through
  its ancestors and visible, and was clicked: call `OnCancel`; if it returns true call `Close`; return false.
  Otherwise return true and the derived handler looks at its own buttons [known].
- `SetAnchoredPosition(h, v, dx, dy)` S 00460be0, per axis [known]: anchor 0 = position = offset in pixels;
  anchor 1 = centred: (1 − frame size as a fraction of the screen) / 2, converted to pixels, plus the offset;
  anchor 2 = far edge: screen size − frame size + offset; any other anchor value leaves that coordinate 0.
  The function reads the last node of the frame's deployment list (frame+0x12c) and does nothing when
  either of its dwords at node +0x6c / +0x70 is non-zero [known]; these are `alignX` / `alignY` of
  `nUi::Deployment` (+0x64 / +0x68; 0 = none) [inferred from the typed layout], i.e. a frame whose layout
  sets `alignx` or `aligny` cannot be positioned this way.
- Most dialogs load their layout file in `OnShow` (`nUi::XMLHandler::LoadFromFile`), which runs
  `BuildWidgets`. `ReportIssueDialog` reloads it each time it goes from hidden to visible (its `SetVisible`
  S 0045ae40), so it always opens empty; `SetPasswordDialog` is created anew by every opener call and loads
  it in `OnShow` S 0045d720 [known].
- A widget created in code is enabled: `nUi::Object::InitAndAttachToParent` S 004a56d0 sets `enabled`, and
  `nUi::Object::LoadFromXml` S 004a76c0 changes it only when the node has an `enabled` attribute [known].
- **Walk-away watch.** Mailbox, shop and minigame matchmaking register
  `CLobby::AddDistanceWatch(radius 2.0, callback, 0)` (CLobby vtbl+0xdc, S 004fb5f0: the origin is the local
  avatar's position at the call; no avatar → no watch) when they become visible and cancel it (vtbl+0xe0)
  when hidden; the hall of fame registers it in `OnShow`, i.e. once per opened dialog. The callback checks
  the watch id and runs: hall of fame → `Close`; the others → their slot 36 [known] S 00442340, S 004421c0,
  S 004502e0, S 00450100, S 0045bbd0, S 0045b600, S 00444cb0, S 00443090. That the watch fires when the
  avatar is more than the radius from the origin is [inferred] from the stored record; the test itself is in
  [lobby-world-client.md](lobby-world-client.md).

### 3.3 Login dialog (`lobbyLoginDialog.xml`)

Widgets [known] S 0043c380: `Username`, `Password`, `CDKey` (EditEx); `SaveUsername` (toggle); `Okay`,
`CreateAccount`, `RetrieveAccount`, `Close` (buttons, kind 0xc). Field rules come from the layout [known:
`lobbyLoginDialog.xml`]: `Username` `maxLength="20"`, `allowedChars` = a-z A-Z 0-9 ä ö ü Ä Ö Ü ß `+ - _ .`;
`Password` `maxLength="20"`, `isPassword="true"`, no character restriction; `CDKey` `maxLength="19"`,
`allowedChars` = a-z A-Z 0-9 `-`.

On show [known] S 0043d150: subscribes to `LobbyComm::System+0x10` (login succeeded), `+0x1c` (login failed),
`+0x40` (version check failed); fills Username, CDKey and Password from the profile (`LobbyProfile`
`GetUserName` / `GetCDKey` / `GetPassword`); a stored key that normalises to 16 characters is shown in its
dashed form (`Str_FormatKey16WithDashes`; the grouping `XXXX-XXXX-XXXX-XXXX` is [inferred], the formatter was
not read), any other stored key as it is; `SaveUsername` is ticked when both the user name and the key field
are non-empty; the dialog is centred. Normalising (`Str_NormalizeDashedKey16` S 00487f10): split at `-`, join
the parts, upper-case, valid iff the result has exactly 16 characters [known].

| Control | Rule and action | Tag |
|---|---|---|
| `Okay` | Any of the three fields empty → box `!ERROR_DIALOG` / `!UNCKPW_EMPTY_TEXT` (Ok), nothing sent. Otherwise: read the lobby server host and port from the profile (`LobbyProfile::GetLobbyServerHost`, `LobbyProfile_GetLobbyServerPort`; keys `[LobbyServer] Host`, `Port` as in §6) and the configured protocol version (if it is not -1 it replaces `g_ClientProtocolVersion`); normalise the key (if that fails the raw text is used); `LobbyComm::System::Login(host, port, user, password, key)`. True → wait box `!WAIT_DIALOG` / `!LOGGING_IN_TEXT` (set 4 Cancel, tag 2); false → `!ERROR_DIALOG` / `!LOGIN_FAILED_TEXT` (Ok, tag 1). The dialog is hidden in both cases. | [known] S 0043cbf0 |
| `CreateAccount` | opens `CreateAccountDialog`, closes this dialog | [known] S 0043cbf0 |
| `RetrieveAccount` | `ShellExecuteA(open, "http://support.ubisoft.de/home.php")` | [known] S 0043cbf0 |
| `Close` | CLobby vtbl+0x2c: leave the lobby (the argument is not visible in the decompile) | [known] S 0043cbf0 |

The login itself is the sequence 188 CheckVersion, 201 / 202 / 204 / 207 authentication and the global-data
load of `../message-catalog.md` section "Login, authentication and the UC/chat connection".

Results:

| Event | Reaction | Tag |
|---|---|---|
| login succeeded (`+0x10`) | only if the wait box is still active: close it, close the dialog, open `MotDDialog`; if `SaveUsername` is ticked save the Username and CDKey field texts to the profile (the password is not saved) | [known] S 0043c1a0 |
| login failed (`+0x1c`), code 0x5479 (main connection logged out before the global data was loaded: [lobby-client-state.md](lobby-client-state.md)) | box `!ERROR_DIALOG` / `!LOGIN_ABORTED_TEXT` (Ok, tag 4), whether or not a wait box is open; the wait box is not closed by this handler | [known] S 0043c890 |
| login failed, any other code | only if the wait box is active: close it, box `!ERROR_DIALOG` / `!LOGIN_FAILED_TEXT` (Ok, tag 1). The code is not shown and not distinguished. | [known] S 0043c890 |
| version check failed (`+0x40`) | only if the wait box is active: close it, box `!ERROR_DIALOG` / `!VERSIONCHECK_FAILED_TEXT` (Yes / No, tag 3) | [known] S 0043ca60 |

Box results by tag [known] S 0043c790 (the handler first unsubscribes itself from the box): 1 and 4 → show
the login dialog again; 2 (Cancel on the wait box) → forget the wait box, `LobbyComm::System::Logout`; 3 with Yes →
request quit of the game (`nMenu::System::RequestQuit`), open the support URL, leave the lobby (CLobby
vtbl+0x2c(0)); 3 with No → leave the lobby.

There is no client timer on the login: the wait box stays until one of the three events or Cancel [known:
no time source is read in S 0043c1a0..0043d150].

### 3.4 Create-account dialog (`lobbyCreateAccountDialog.xml`)

Widgets [known] S 0043d5c0: `Username`, `Password`, `PasswordRetype`, `CDKey`, `EMailAddress` (EditEx), `Okay`,
`Cancel` (kind 0xc). Layout rules [known: the layout file]: `Username` max 20, a-z A-Z 0-9 ä ö ü Ä Ö Ü ß `+ - _`
(no `.`, unlike the login dialog); passwords max 20, masked; `CDKey` max 19, a-z A-Z 0-9 `-`; `EMailAddress` max
320, a-z A-Z 0-9 and ``.!#$%&'*+-/=?^_`{|}~@``.

`Okay` [known] S 0043e080, S 0043dd10. Host, port and protocol version are read as in the login dialog. The
checks run in this order; the first failure shows one `!ERROR_DIALOG` box (Ok) and sends nothing:

1. user name empty → `!UNCKPWEM_EMPTY_TEXT`;
2. password or retype empty → `!UNCKPWEM_EMPTY_TEXT`;
3. password ≠ retype → `!PW_NOTIDENTICAL_TEXT`;
4. CD key empty → `!UNCKPWEM_EMPTY_TEXT`;
5. user name = password → `!UNPW_MUSTNOTIDENTICAL_TEXT`;
6. e-mail empty → `!UNCKPWEM_EMPTY_TEXT`;
7. e-mail = password → `!EMPW_MUSTNOTIDENTICAL_TEXT`;
8. the key does not normalise to 16 characters → `!CDKEY_INVALID`.

Then `LobbyComm::System::CreateUser(host, port, user, password, normalisedKey, email)` (203 SelfRegistration, see
`../message-catalog.md`). True → the dialog is hidden and a wait box `!WAIT_DIALOG` /
`!CREATING_ACCOUNT_TEXT` (set 5, no buttons, tag 1) is shown; false → `!ERROR_DIALOG` /
`!CREATE_ACCOUNT_FAILED_TEXT` (Ok), the dialog stays visible.

`Cancel`: close, open the login dialog [known] S 0043e080.

Results arrive on the same observer lists as a login (`LobbyComm::System+0x10` / `+0x1c`, subscribed in
`Activate` S 0043e410) and are handled only while the wait box is active:

| Event | Reaction | Tag |
|---|---|---|
| success | close the wait box; box `!SUCCESS_DIALOG` / `!USER_CREATION_SUCCESS_TEXT` (Ok, tag 2); save the user name and the normalised key to the profile | [known] S 0043d960 |
| failure, code 23, 24 or 26 | box `!ERROR_DIALOG` / `!USER_KEY_PROBLEM_TEXT` (Ok, tag 3) | [known] S 0043db90 |
| failure, code 41 | `!USER_ALREADY_EXISTS_TEXT` (tag 3) | [known] S 0043db90 |
| failure, any other code | `!CREATE_ACCOUNT_FAILED_TEXT` (tag 3) | [known] S 0043db90 |

Box results [known] S 0043d490: tag 2 → close the dialog and request screen 2 (the account is logged in;
no message of the day is shown on this path); tag 3 → show the dialog again. A wait box without buttons
cannot be dismissed by the player; there is no timeout [known: set 5; no time source].

### 3.5 Message-of-the-day dialog (`lobbyMotDDialog.xml`)

Embedded `TextBlock` (node `Message`, +0xb48, font `body_arial`) and `Button` (node `Okay`, +0xce8); source
object = `LobbyComm::System+0x100` (stored at +0x1150 in `Activate`) [known] S 0043ecc0, S 0043ef90, S 0043f0d0.

- `RefreshMessage(force)` S 0043eda0: only if the source is valid (byte +0x1c), and then if it reports new
  content (source vtbl+4) or `force`: set the text from the `std::string` at source +0x20 (trimmed),
  acknowledge (source vtbl+0xc) and enable `Okay`. `BuildWidgets` calls it with force; `OnShow` and, every
  frame while visible, `Update` do the same without force [known] S 0043f0d0, S 0043ee90.
- `Okay`: close the dialog and request screen 2 (avatar screen) [known] S 0043ed60.

`Okay` does not start disabled, so the dialog does not block until the MOTD (106) arrives: the button is
created in code (`nUi::Button::CreateStyle0`), neither its layout node `Okay` nor the template
`NormalDialog_Button` carries an `enabled` attribute [known: `lobbyMotDDialog.xml`, `templates.xml`], and no
function of the class disables it [known]; a created widget is enabled (§3.2) [inferred for this button:
`Button::Create` was not followed down to `InitAndAttachToParent`]. Without a message the text stays empty.
The layout hides and disables the close button (`DialogCloseButton enabled="false" visible="false"`) and
gives `Okay` the hotkey 13 (Enter). The request is 105 RequestMOTD, the answer 106 MOTD
(`../message-catalog.md` section "MotD").

### 3.6 Avatar screen (`lobbyAvatarScreen.xml`)

**Activate** S 0043be30 [known]: subscribes to `CharacterManager+0x08` (character created) and `+0x14`
(create failed), `LobbyComm::System+0x28` (lobby logged out), `+0x34` (with an empty handler), `+0x04`
(connection lost); then CLobby vtbl+0x6c (`EnterCustomizeMode`: the 3D view switches to the avatar preview).

**OnShow** S 0043b3a0 [known]: creates the three dialogs hidden, input-disabled and with +0xb42 cleared,
loads the layout, sets buttons enabled and visible and clears the latch; if the character list is loaded
(`CharacterManager+0x88`) and empty, `SetViewMode(0)` and set the latch +0x21d; otherwise `SetViewMode(1)`.
The same "loaded and empty → create mode" test runs at the start of every `HandleButtonClicks` in select mode
while the latch is clear (so a list that arrives late and empty still switches to create mode, once per
`OnShow`) [known] S 0043bd50.

**View modes** (`SetViewMode` S 0043a630, which reloads the layout first and ends with the screen's own
`Update`) [known]:

| Mode | Title | `StartGameButton` caption | Visible |
|---|---|---|---|
| 0 create | `!AVATARSCREEN_CREATE_TITLE` | `!CREATE_AVATAR_BUTTON` | `CustomizeAvatarDialog`, `NameEdit`, Start, Back. The working avatar's look is reset (`AvatarProxy::ResetLook`) and pushed to the preview (CLobby vtbl+0xb8, vtbl+0x78(1)) |
| 1 select | `!AVATARSCREEN_SELECT_TITLE` | `!ENTER_VILLAGE_BUTTON` | `SelectAvatarDialog` (its preview is refreshed), `ResetLoginPosition` with `ResetPositionLabel`, Start, Back; `SelectVillageServerDialog` only if `CodersRule` |
| 2 entering | `!AVATARSCREEN_ENTERWORLD_TITLE` | unchanged | nothing: all buttons and dialogs hidden and disabled |

A dialog that is not visible in a mode is also input-disabled (slot 14) [known].

`CodersRule="false"` in the shipped layout [known: `lobbyAvatarScreen.xml`], so the village server is chosen
automatically.

**Per-frame button state** (`Update` S 00439f30) [known]:

- select mode, `CodersRule` off: Start enabled iff buttons are enabled and a character is selected and
  `ServerList::HasJoinableServerForProtocol(g_ClientProtocolVersion)`. The caption is
  `!ENTER_VILLAGE_BUTTON` while such a server exists, else `!LOBBY_LOADING_SERVERS`.
- select mode, `CodersRule` on: Start enabled iff buttons enabled, a village server is selected and a
  character is selected.
- create mode: Start enabled iff buttons enabled and `NameEdit` is not empty.

**Clicks** (`HandleButtonClicks` S 0043bd50) [known]:

| Click | Action |
|---|---|
| Start, create mode | `OnCreateAvatarClicked` (below) |
| Start, select mode | `OnStartGameClicked_EnterVillage` S 0043abc0, then `DisableButtons` S 00439cc0. In S 0043abc0, `CodersRule` off: `FindBestVillageServer(g_ClientProtocolVersion, -1)` and `SelectVillageServer`; if either fails, the buttons are enabled and `!ERROR` / `!COULDNOT_CONNECT_TO_VILLAGE` (Ok, no callback) is shown. Otherwise (and always with `CodersRule` on) `SetViewMode(2)`, CLobby vtbl+0x80(checked state of the `ResetLoginPosition` toggle, widget +0x2ec) = request village entry [known]. Called with no joinable village server, the handler takes the failure branch: +0x218 is 1 before and after, the buttons are re-enabled for the view mode, the box reads "FEHLER" / "Willkommen im Dorf" (the shipped `language\de\lobby_ui.txt` translates `!COULDNOT_CONNECT_TO_VILLAGE` wrongly as "Willkommen im Dorf"), and the screen stays usable: leaving it works, and Start keeps waiting for a joinable server [live, 2026-10-14; the handler was called directly, since Start cannot be pressed without such a server, so the `DisableButtons` that follows it in `HandleButtonClicks` was not part of the run]. In a real click Start is enabled only while `HasJoinableServerForProtocol` holds (`Update`, above), so the failure branch needs a listed server that `FindBestVillageServer` or `SelectVillageServer` then refuses [inferred] |
| Back, create mode | disable the buttons; box `!WARNING_DIALOG` / `!ABORT_CHARACTER_CREATION_TEXT` (Yes / No, tag 0x2000) (S 0043bc40) |
| Back, select mode | `LobbyComm::System::Logout`; if it returns false: request screen 0 and leave the lobby (CLobby vtbl+0x2c(0)) at once; otherwise the same happens in the logged-out observer when the reported handle equals `LobbyComm::System`'s chat server handle (`LobbyComm::System+0x548`) (S 00439be0, S 00439c20) |

A click on Start or Back in mode 2 does nothing [known].

The village entry chain behind vtbl+0x80 (UC login, village connection, EnterWorld) is in
`../village-and-character-protocol.md` §2.3; EnterWorld (1000) is what requests screen 3. The avatar screen
has no timeout of its own in mode 2 [known: no time source in the class].

**Create a character** (`OnCreateAvatarClicked` S 0043b4d0) [known]:

1. Copy the working avatar's look into an `AvatarCreationBlockEx`: tribe, gender, the bytes +0x49..+0x4c
   (hair, skin, shirt, trousers) and +0x4d..+0x50 (four additional colours; each of these four is stored only
   if the block's variant query returns non-zero).
2. Disable the buttons. The name must be at most 16 bytes and every byte must occur in the `allowedChars`
   set of `NameEdit` (the string at widget +0x328; S 00439d20); otherwise box `!ERROR_DIALOG` /
   `!CREATE_CHARACTER_NAME_INVALID` (Ok, tag 0x1000), buttons re-enabled. The layout gives `NameEdit`
   `maxLength="16"` and `allowedChars` = a-z A-Z 0-9 and seven further single-byte characters ([inferred]
   ä ö ü Ä Ö Ü ß; the file is not valid UTF-8 at that place) [known: `lobbyAvatarScreen.xml`]. An empty name
   passes this check; it is kept out by the disabled Start button only.
3. Serialise the block and call `CharacterManager::CreateCharacter(name, blob, size)` (86 AddCharacter). If
   serialising or queueing fails: box `!ERROR_DIALOG` / `!CREATE_CHARACTER_FAILED_TEXT` (Ok, tag 0x1000),
   buttons re-enabled. Otherwise a wait box `!WAIT_DIALOG` / `!CREATING_CHARACTER_TEXT` (set 5, tag
   0x3000) is stored at +0x200.

| Event | Reaction | Tag |
|---|---|---|
| character created (`CharacterManager+0x08`) | if the wait box pointer is set and its tag is 0x3000: close it, `SelectAvatarDialog::Update`, `SelectCharacter(new id)`, `SetViewMode(1)`, re-enable the buttons | [known] S 0043afc0 |
| create failed (`+0x14`, errorCode) | if the wait box (tag 0x3000) is open: close it; box `!ERROR_DIALOG` with the text `CommLayer_GetErrorString(errorCode)` (S 00486010), Ok, tag 0x1000 | [known] S 0043b0a0 |
| connection lost (`LobbyComm::System+0x04`) | box `!ERROR` / `!CONNECTION_LOST_TEXT`, button set 5 (no buttons), tag 0x500, without any condition | [known] S 0043b1b0 |

Box results by tag [known] S 0043ad90: 0x1000 → re-enable the buttons; 0x2000 → on Yes `SetViewMode(1)`,
then re-enable the buttons; 0x3000 → open a new identical wait box; 0x500 → request screen 0 and leave the
lobby (CLobby vtbl+0x2c(0)). The 0x3000 and 0x500 boxes have button set 5, and a box reports a result only
from a button click (§2.5), so these two branches are unreachable and the connection-lost box cannot be
dismissed by the player [inferred]. The wait box pointer +0x200 is not cleared when the box is closed
[known].

The error codes of 153 AddResult and their texts are listed in `../village-and-character-protocol.md` §2.2.

### 3.7 Avatar selection dialog (`lobbySelectAvatarDialog.xml`)

Widgets: `AvatarList` (ListBox2), `CreateNewAvatar`, `DeleteAvatar` (kind 0xc) [known] S 0043f570.

**List** (`Update` S 0043fa40, when visible and the `CharacterManager` is not busy (vtbl+0x10) and dirty
(vtbl+4); the dirty state is acknowledged with vtbl+0xc after the rebuild) [known]: one row
per character: text = name, row value = character id; child `Level` = localised
`!LOBBY_SELECTAVATAR_LEVEL_LABEL` + " " + level; `Credits` = the character's gold (+0xd0); `Icon` gets the
template `<Tribe><Gender>Small` with tribe 0 `Bavarian`, 1 `Scot`, 2 `Egypt` and gender 0 `Male`, 1 `Female`.
The list is padded to **8 rows** with disabled rows (row value 0) whose `Level`, `Credits` and `Icon`
children are hidden and whose `Empty` child is shown. After a rebuild the first character is selected
(`CharacterManager::SelectCharacter`), or the one just created (id remembered at +0xb58 by the
created-observer S 0043f420); with no character the selection is cleared. Every visible frame:
`CreateNewAvatar` is enabled only while fewer than 8 characters exist, and the row whose value equals the
selected id (+0xb54) is marked.

| Click | Action | Tag |
|---|---|---|
| a row | store the id (+0xb54), CLobby vtbl+0xac(id) (load into the preview), `CharacterManager::SelectCharacter(id)`, show the preview | [known] S 0043f770 |
| `CreateNewAvatar` | if the current screen is 2: `AvatarScreen::SetViewMode(0)` | [known] |
| `DeleteAvatar` | with a selection (+0xb54 ≠ 0): box `!WARNING_DIALOG` / `!LOBBY_CONFIRM_DELETE_AVATAR_TEXT` (Yes / No); on Yes `CharacterManager::DeleteCharacter(id)` (94 RemoveCharacter) and +0xb54 = 0 | [known] S 0043f770, S 0043f3e0 |

The row is removed when the `CharacterManager` marks its list dirty after the server's answer
(`../village-and-character-protocol.md` §2.4); the dialog shows no message for a failed delete [known: no
handler in the class].

### 3.8 Avatar customisation dialog (`lobbyCustomizeAvatarDialog.xml`) and the tailor

The same class serves character creation (avatar screen) and the tailor (world screen). `OnShow` latches
`inVillageMode` (+0xb5c) = "`LobbyComm::System` state is VillageEntered" and positions the dialog with
`SetAnchoredPosition(0, 1, 0, 0)` [known] S 0043e6e0.

Layout attributes on the dialog node [known] S 0043e7f0 and the layout file: `AvatarCount="6"`,
`ColorCount="16"`; widgets `AvatarButton_0..5`, `ColorButton_0..15`, `Randomize`.

| Control | Rule | Tag |
|---|---|---|
| `AvatarButton_i` | attribute `data` = tribe × 256 + gender (shipped: 0, 1, 256, 257, 512, 513). Click: `SetTribeGender(data >> 8, data & 0xff)` on the working avatar, which stores one byte (gender & 0xf) \| (tribe << 4) (S 0046b730). Disabled in village mode. | [known] S 0043e500, layout |
| `ColorButton_i` | `data` (shipped: `ColorButton_i data="i"`, even = left arrow, odd = right arrow): colour slot = (data >> 1) & 0x7f, direction = +1 if bit 0 is set, else −1. Click: `AdjustColor(slot, direction)`. In village mode only buttons with index > 5 (slots 3..7) are enabled. | [known] S 0043e500, S 0043e7f0, layout |
| `Randomize` | for slot 0..7: `AdjustColor(slot, rand() & 0xf)`, i.e. 0..15 is added to the current value; in village mode only slots 3..7 | [known] S 0043e500 |

After every change the look is applied to the 3D preview: CLobby vtbl+0xb8(avatar, !inVillageMode); while
the developer switch byte S 008882c8 is set it is applied on every poll. No message is sent by this dialog.
`AdjustColor(slot, delta)` S 0046b750 adds the signed delta to one byte of the avatar data: slot 0 hair,
1 skin, 2 shirt, 3 trousers, 4..7 the four additional colours (+0x49..+0x50); there is no range check and no
wrap other than that of the byte [known]. How a value outside the number of available colours is mapped
when the look is applied is [TODO] (the look application of `Lobby::CLobby`,
[lobby-world-client.md](lobby-world-client.md)).

**Tailor** (world screen, action code 17) [known] S 00434230, S 00431e50, S 0045e020:

1. If the lobby is already in customise mode (CLobby vtbl+0x74), nothing.
2. No local avatar (CLobby vtbl+0x90) → nothing. Its gold (+0xd0) < 50 → box `!TAYLOR_TITLE` /
   `!TAYLOR_QUESTION_NOMONEY` (Ok).
3. Otherwise box `!TAYLOR_TITLE` / `!TAYLOR_QUESTION` (Yes / No); Yes → CLobby vtbl+0x6c
   (`EnterCustomizeMode`) and vtbl+0xb4 (show a copy of the local avatar).
4. While CLobby vtbl+0x74 is true, `CustomizeAvatarDialog` (in village mode) and `ConfirmTaylorDialog` are
   visible (their `Update` S 0043e460, S 0045dfc0), and the world screen hides itself (§3.11).
5. `ConfirmTaylorDialog`: `ConfirmChangeButton` builds eight values (hair, skin, shirt = -1 "unchanged";
   trousers and the additional colours from the working avatar's bytes +0x4c..+0x50), applies them to the
   local avatar (`ActorProxy::SetColors`) and sends them with `SendAvatarColorChange` = 3950
   AvatarColorChange (`../message-catalog.md`); then, as for `BackButtonTaylor`, CLobby vtbl+0x70 leaves
   customise mode. The decompile shows the first four values being set; the fifth (fourth additional
   colour) is [inferred] from the slot range 3..7.

The price 50 is only a client-side gate; the client sends no amount [known] S 0045e020.

### 3.9 Village server selection

**`SelectVillageServerDialog`** (`lobbySelectVillageServerDialog.xml`, list widget `ServerList`) is visible
only with `CodersRule` (§3.6). Rows: one per village server entry whose secured flag (+0x34) is 0, whose
protocol version (+0x30) equals `g_ClientProtocolVersion` and which is online (+0x35); row text = name, row
value = server id, child `LoadLevel` = load in percent. Rows are added, refreshed and removed by the
server-list observers (`ServerList+0x0c` and `+0x18` add or refresh, `+0x24` remove; an entry that goes
offline loses its row); on show the list is filled if the server list is valid and idle, and the last added
row is marked and selected as village server [known] S 00440d70, S 00440a50, S 004407e0. Click on a row:
`ServerList::SelectVillageServer(id)` if it is not the selected one; if the current screen is 3: when the
selected id differs from the connected village server, set `ServerList+0xa0` (village login pending) and
call CLobby vtbl+0x88 (switch village); then hide the dialog. On any other screen the dialog stays open
[known] S 00440690. The meaning of the bytes +0x34 / +0x35 is that of
[lobby-client-state.md](lobby-client-state.md).

**`SelectServerMenu`** of the world screen is the shipped way to change village. Its fill callback
`PopulateSelectServerMenu` S 004375a0 adds, for every village server that is not the current one
(`LobbyComm::System+0x550`), has the client's protocol version and is online, an item `<name> (<n> Player)` with
the server id as item value (n = the dword at entry +0x28). A pick closes the menu and, without any
further test, selects the server, sets `ServerList+0xa0` and calls CLobby vtbl+0x88 [known] S 00437760.

The entries come from 170 GameServerData after 171 RegObserverServerList (`../message-catalog.md`).

### 3.10 World screen: chat, minimap, HUD

**Chat channels** (set up in `OnShow` S 004389d0) [known]:

| Kind | Title key | Initial state | Carries |
|---|---|---|---|
| 1 | `!CHATCHANNEL_GLOBAL` | enabled | UC channel mapped by `VillageServerConnection::GetChatChannelByKind(1)` |
| 2 | `!CHATCHANNEL_LOCAL` | enabled, **active** | UC channel of kind 2 |
| 3 | `!CHATCHANNEL_MINIGAME` | disabled; enabled while at a minigame table | the table's channel |
| 4 | `!CHATCHANNEL_SETTLERS` | disabled; enabled while the NComm session state is 2 | pre-game room and match chat, through NComm |

`OnShow` also shuts NComm down (`NComm_Manager::Shutdown(false)`) and, at its end, prints the lines
`!LOBBY_CHAT_WELCOME` and `!LOBBY_CHAT_HELP` (channel -2) [known].

**Sending** (`SendChatInput(kind, text)` S 00436860) [known]: the text is trimmed; empty → nothing. It is
parsed as a slash command (S 004354d0: leading `/`, tokens split on the characters space, tab, CR, LF, VT,
quotes `"` `'`, escape `\`; a command matches when the word equals the first token and there are more tokens
than the command needs arguments; the last argument is all remaining tokens joined with single spaces). The
table (static initialiser S 007be820) [known]:

| Word | Kind | Arguments | Action |
|---|---|---|---|
| `ac` | server command (1) | 1 (rest of the line) | `VillageServerConnection::SendChatCommand(rest)`: 4000 ChatCommand |
| `tell`, `whisper`, `w` | whisper (2) | 2 (name, rest of the line) | `UserCommConnection::QueuePrivateMessage(name, text)`: 30 WhisperChatMessage |
| `help`, `hilfe` | help (3) | 0 | prints `!LOBBY_CHAT_HELP` locally |
| `laugh`, `dance`, `applaud`, `cry`, `bow`, `monkey` | emote (4), index 0..5 | 0 | sent as a normal chat line |

Anything else, including a known command with too few tokens, is a normal chat line: kind 4 →
`NComm_Manager::SendChatToAll(text)`; other kinds → `UserCommConnection::SendChatMessage(channelId, text)`
(2 ChatMessage) with the untrimmed text, or nothing when the kind has no channel id [known].

**Receiving** [known unless tagged]:

- Channel line (`OnChatChannelMessage` S 00436180) [known]: dropped when the sender's relation
  (`CharacterManager::GetUserRelation`) is 2 (ignored) or the channel id maps to channel kind 0. A line from
  the village server's own perm id is printed as `[SYSTEM] ` + text (sender id 0) and also shown as a box
  with title `!LOBBY_IMPORTANT_SYSTEM_MESSAGE` and the text as message (Ok). A line that parses as an emote
  command is printed as the localised text `!EMOTE_MSG_LAUGH` / `_DANCE` / `_APPLAUS` / `_CRYING` / `_BOW` /
  `_MONKEY` (index 0..5) formatted with the sender name. Everything else as
  `[` name `] ` + `!LOBBY_CHAT_FROM` + ` : ` + text. The line goes to the tab of the channel kind with the
  sender id attached; its colour is one of four constants of four floats each [known: the image bytes; a
  run-time writer was not searched]: default S 0087af74 = (1, 1, 1, 1); system S 0087af34 = (1, 0.902, 0, 1)
  (230 / 255); relation 1 (friend) S 0087af54 = (1, 1, 1, 1), the same as the default; emote S 0087af94 =
  (0.973, 0.514, 0.314, 1) (248, 131, 80 of 255). An emote overrides the friend colour. Component order:
  §10.
- Private line received (S 00432930): `[` name `] ` + `!LOBBY_PRIVATE_CHAT_FROM` + ` : ` + text; private line
  sent (S 00432c60): `!LOBBY_PRIVATE_CHAT_TO` + ` [` name `] : ` + text; both on channel -1 [known]. The
  sender's name of a received line is kept at +0x3650 [inferred: the store is not visible in the decompile
  read here; the field is read by the `/r` expansion].
- NComm status and sync texts go to the chat with channel -1 (S 00431ba0); an NComm error text opens an
  `!ERROR` box (S 004330c0).

**Chat keys** (`HandleButtonClicks` S 00437760, `LobbyAction` predicates S 00429700..004297c0; virtual-key
codes in §3.18) [known]:

- input not focused: Enter (0x0d) opens the input empty; Shift+7 (0x37) opens it with `/`; Shift+R (0x52)
  prefills `/tell <last whisperer> ` (only if a name is stored);
- input focused: Enter sends the text on the active channel (nothing if it is empty) and clears the input;
  an input that begins with `/r ` is replaced by `/tell <last whisperer> ` (or `/tell ` when none is stored).

**Click on a chat line** (S 00437e20) [known]: nothing happens unless the line's sender id is in the name
cache (`CharacterManager::TryGetCachedName`). No modifier → prefill `/tell <name> `; Shift without Ctrl → if
the relation to that user is 0 (none), box `!LOBBY_ADD_FRIEND_DIALOG` / `!LOBBY_ADD_TO_FRIENDLIST` (Yes / No,
tag 0x10); Ctrl without Shift → the same with `!LOBBY_ADD_IGNORE_DIALOG` / `!LOBBY_ADD_TO_IGNORELIST`
(tag 0x11); both modifiers → nothing. The user id is parked at +0x3648. Yes →
`CharacterManager::AddToFriendList` / `AddToIgnoreList(id)`; any result clears +0x3648 [known] S 00431c20.

**Quick emotes.** `EmoteButton` is filled from `QuickEmotes.txt` (S 00436bc0; format in
[formats-inventory.md](formats-inventory.md) §3.10): lines starting with `#` are skipped, a line is split at
`;` (quote `"`, escape `\`) and used only if it has exactly three tokens with non-empty first and third;
item label = token 1 (localised), tooltip = token 2, chat text = token 3. A pick closes the menu and, unless
the active channel is 4 or the channel kind has no channel id, sends the chat text with
`UserCommConnection::SendChatMessage` on the active channel [known] S 00436bc0, S 00437760.

**Minimap** (`LobbyMenu::Minimap`, vftable S 007da5f0; widgets `Minimap`, `MinimapArrow`, `MinimapCoords`)
[known] S 00460480, S 0045f760, S 0045fd30:

- zoom level 0..7, initial 2 (scale 1.0); Ctrl + numpad minus / plus step it down / up, clamped. Scale
  table (S 0087ad34, eight floats): 0.6667, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0 [known: data bytes].
- Updated only while the widget is visible and the actor of CLobby vtbl+0x94 ([inferred] the local avatar)
  is in zone 0 with ghost zone 0xf (the open village).
- The texture window of the widget is the widget size in pixels divided by the scale, centred on the
  avatar's map position (CLobby vtbl+0xc8 converts world to map; the map position is scaled by 512.0,
  S 0087ad2c).
- Arrow rotation (16-bit angle at arrow widget +0x22a) = heading / S 00882840 × 65536 + 32768.0
  (S 0087ad30); S 00882840 is [inferred] 2π (not read).
- Markers (only those with their visible flag): offset = scale × (marker − avatar map position). If its
  length exceeds `markerRadius` = 88.45 (set in the constructor) the marker is
  drawn on the circle of that radius with the image `MinimapTargetArrow`, rotated by
  ±acos(normalised y component) / 2π × 65535 (negative when the x offset is negative); otherwise at the
  offset with the image `MinimapTarget`. [inferred for which component feeds acos: the register operand
  is not visible in the decompile]
- `MinimapCoords` is hidden every frame in which that actor exists.

Component vtable (S 007da5f0, 14 slots) [known: vtable bytes]: slot 4 `Update` S 0045fd30, slot 5
`HandleZoomKeys` S 0045f760, slot 7 S 0045f7b0 = attach (stores the owning screen at +0x08 and sets the byte
+0x0c; called by `WorldScreen::OnShow`), slot 8 S 0045f950 = detach (destroys the marker widgets; called by
`WorldScreen::OnLeave`), slots 10 / 11 show / hide the `Minimap` widget, slot 12 `BindWidgets` S 00460210.
None of these appends to the marker vector (+0x18); who adds markers is [TODO] (§10): look for writers of
`Minimap+0x1c..+0x24` outside the class.

**HUD, per frame** (`Update` S 00435980) [known]:

- `Clock`: `_strtime_s` (HH:MM:SS, local time).
- `ConnectionQuality`: `VillageServerConnection` quality 0 or 1 → 200, 2 → 180, 3 → 160, other values → 160,
  written as a float to icon +0x1b0; icon +0x1b8 is set to 947.0. With the `nUi::Shape` of a `Picture` at
  +0x198 these are the x and y of the texture mapping rectangle (shape +0x18, +0x20) [inferred from the typed
  layout]: the icon shows the atlas cell at (200 | 180 | 160, 947). The layout node maps
  `texture="ui_menus" mapping="160 947 16 13"`, size `16 13` [known: `lobbyWorldScreen.xml`], so the cells
  are 16 × 13 pixels of `ui_menus`, 20 pixels apart.
- `MailIndicator`: visible while `PostOffice` byte +0xa4 is set.
- `ServerName`: `VillageServerConnection::GetWorldName()`.
- `SelectionName` / `SelectionLevel`: name of the selected actor (CLobby vtbl+0x9c; "???" if none); level
  as `!LOBBY_SELECTAVATAR_LEVEL_LABEL` + " " + level, hidden (and set to 0) when there is no actor or its
  level is 0. CLobby vtbl+0xa4 = `GetSelectionSnapshotTexture(&texture, &valid)` S 004f51b0: valid = 1 and
  texture = snapshot render target 0 while a world object is selected, else 0 / 0. Only when valid is 1 the
  texture is bound to `SelectionPicture`, and only then, if the selection record of CLobby vtbl+0xa0 exists
  and has type 1 (an avatar), the two labels are refreshed [known: the disassembly of S 00435980 at
  S 00435ca6..00435cf2, S 004f51b0].
- `Friends` toggle is kept in sync with the visibility of the friends dialog; the dialog itself is re-set
  each frame to "visible and CLobby vtbl+0x8c is false" (the same value that hides the whole screen at the
  top of `Update`) [known: S 00435c20..00435c4a].
- NComm session state 2 (in a pre-game room): `SetupGameDialog` visible unless minimised (its byte +0xba8;
  [inferred]: the argument of the `SetVisible` call is not visible in the decompile), `BrowseGameDialog`
  hidden, `MatchmakingIndicator` visible iff +0xba8 is set and blinking (marked while
  elapsed milliseconds mod 1000 < 500) when the dialog's value at +0xbac is positive; chat channel 4
  enabled. Any other state: `SetupGameDialog` and the indicator hidden, channel 4 disabled. A click on the
  indicator clears +0xba8 (restores the room dialog) [known] S 00437760. The fields +0xba8 / +0xbac belong
  to `match-setup-room.md`.

**Mouse in the 3D view** [known] S 00431d30..00431e00: the world screen subscribes in `OnShow` to four
observer lists of the `LobbyDesktop` (+0x1c8 move, +0x198 button down, +0x1a4 button up, +0x1b0 click). A
move goes to CLobby vtbl+0x48(x, y); a button down / up of any button to vtbl+0x50 / +0x54 with the button
mapped through a table (S 00879fd4 / S 00879fec), and for buttons 1 and 2 the desktop also takes /
releases the input capture (its vtbl+0x88 / +0x8c); a click of button 0 to vtbl+0xa8(x, y) (pick the object
under the cursor).

### 3.11 World screen: action buttons and LobbyAction codes

`RefreshActionSlots` S 00433f60 rebuilds the three codes every frame [known]:

1. Clear the codes.
2. If a **scene object** is selected (CLobby vtbl+0x98 returns true and gives two values, kind and scene
   id): kind 1 (letterbox) → code 7 in the first free slot; any other kind is a minigame table spot
   (spot = kind − 100) → code scene + 10 with param = spot if no table exists at (scene, spot)
   (`FindMiniGameProxyByScntbl`), else scene + 12 with param = the table's map key. A changed kind value
   (+0x3634) sets the selection latch; +0x3630 is cleared. All three buttons get the template
   `LobbyAction_None` and are hidden (`SetVisible(false)`, vtbl+0x24(0)).
3. Else if another **actor** is selected (CLobby vtbl+0x9c ≠ local avatar, CLobby vtbl+0x90): the actor fills
   the codes (actor vtbl+0x14: an NPC copies the `act` ids of its record, a player gives none [inferred:
   the two bodies are in [lobby-client-state.md](lobby-client-state.md)]). A changed actor pointer sets the
   latch; +0x3634 = -1. Buttons as in step 2.
4. Else (nothing or the own avatar): NComm session state 0 → codes 8 and 9; otherwise, if the room dialog is
   minimised (+0xba8) → codes 0x12 and 0x13; in both cases `SetActionButton` sets up the three buttons. In a
   room that is not minimised no code is set and the buttons are hidden as in step 2.

The codes scene + 10 / scene + 12 land on 12, 13 / 14, 15 of the table below, i.e. the two taverns have the
scene ids 2 and 3 [inferred].

Codes [known] S 004325b0 (template), S 00434230 (action):

| Code | Button template | Action when dispatched |
|---|---|---|
| 0 | `LobbyAction_None`, button hidden | none |
| 1 | `LobbyAction_HairColor` | none (no case in the dispatcher) |
| 2..6 | `LobbyAction_MinigameMatchmaking` | sound 0x63c3110f; CLobby vtbl+0xd4 (argument not visible; [inferred] 0 = world picking off, as slot 36 of the matchmaking dialog calls it with 1); `MiniGameMatchMakingDialog::Open(show, code − 2, -1, mode 0, 0)` = search mode; then the NPC text |
| 7 | `LobbyAction_Mailbox` | if the mailbox dialog exists, is shown (slot 7) and not visible: sound 0x63c3110d, make it visible, `SetAnchoredPosition(1, 1, 0, …)`, `PostOffice::RequestMailHeaders()` (147) |
| 8 | `LobbyAction_HostGame` | `ServerList::CreateGameServer()` (168 AddGameServer); if it returns true, clear the room dialog's minimised flag |
| 9 | `LobbyAction_ListGames` | toggle `BrowseGameDialog` |
| 10 | `LobbyAction_HoF` | sound 0x63c3110e; open `HallOfFameDialog`; NPC text |
| 11 | `LobbyAction_OpenShop` | sound 0x63c3110c; `SendOpenShop(id of the actor at +0x3630)` (3600 OpenShop), without a null check of +0x3630; NPC text |
| 12, 13 | none | CLobby vtbl+0xd4; `Open(show, code − 12, spot = low byte of params[slot], mode 1, 0)` = create mode |
| 14, 15 | none | CLobby vtbl+0xd4; `Open(show, code − 14, -1, mode 2, table key = params[slot])` = join mode |
| 16 | none | only the NPC text |
| 17 | none | tailor (§3.8) |
| 18 (0x12) | `LobbyAction_HostGame` | clear the room dialog's minimised flag (bring the room back) |
| 19 (0x13) | `LobbyAction_None`, button hidden | none |

"NPC text": if the selected actor (CLobby vtbl+0x9c) is an NPC, `NPCProxy::GetActionChat(slot)` is shown
through `ShowNpcSlotText` S 004337f0 [known for the call; the display itself was not read]. "None" in the
template column: `SetActionButton` maps every other code to `LobbyAction_None` (button visible), and is not
reached for a selected NPC or object anyway (step 2 / 3). Codes 0, 1 and anything above 18 have no case in
the dispatcher.

**Dispatch** (`HandleButtonClicks` S 00437760) [known]: nothing is dispatched while CLobby vtbl+0x8c is true.
If the selection latch is set it is cleared, and if slot 0 holds a code while slots 1 and 2 are 0,
`DispatchSlotAction(0)` runs at once and the selection returns to the own avatar (CLobby vtbl+0xc0). After
that a click on button A / B / C dispatches slot 0 / 1 / 2. So an object or NPC with exactly one action
acts when it is clicked. For a selected NPC or object the three buttons are hidden (step 2 / 3), so an NPC
with two or three actions has no way established here to run one [inferred]; see
`../village-and-character-protocol.md` §5.2.

**Main menu** (`MainMenu` drop-down, six items in the layout) [known] S 00437760:

| Item | Layout text | Action |
|---|---|---|
| 0 | `!LOBBY_MAIN_MENU_HOST_GAME` | `ServerList::CreateGameServer()`; clear the room's minimised flag whatever the result |
| 1 | `!LOBBY_MAIN_MENU_JOIN_GAME` | show `BrowseGameDialog` if hidden |
| 2 | `!LOBBY_MAIN_MENU_SETTINGS` | create the `nMenu::OptionsPanel` (parent = the screen's parent node) on first use, `FadeIn(0.2)` |
| 3 | `!LOBBY_MAIN_MENU_OPENSUPPORTWEBSITE` | open `http://support.ubisoft.de/home.php` |
| 4 | `!LOBBY_MAIN_MENU_REPORTISSUE` | show `ReportIssueDialog` if hidden |
| 5 | `!LOBBY_MAIN_MENU_LEAVE` | box `!LEAVE_VILLAGE` / `!LEAVE_VILLAGE_QUESTION` (Yes / No); Yes → CLobby vtbl+0x84 `RequestExitVillage` (2002 LeaveVillageRequest) |

The options panel is the one of the offline menu ([frontend-screens.md](frontend-screens.md)).

**Selection info toggle** (`ObjectInspector`) [known] S 00435980. Only while the `SelectionInfoDialog`
exists and is active, each frame:

1. If the actor A of CLobby vtbl+0x94 ([inferred] the local avatar) exists and the toggle was clicked and
   is now marked: latch A's position (+0x363c).
2. show = not (CLobby vtbl+0x8c) and not (customise mode, vtbl+0x74).
3. If CLobby vtbl+0xa0 returns no selection record: show = false. Otherwise: record type (+4) = 2 (an NPC) →
   show = false; minigame channel set (+0x3548 ≠ 0) → show = false; toggle not marked → show = false;
   toggle marked, A exists and |latched position − A's position| > 2.0 → show = false and the toggle is
   unmarked.
4. `SelectionInfoDialog::SetVisible(show)`.

The record of vtbl+0xa0 is an actor id (type at +4: 1 avatar, 2 NPC; id at +8) [inferred from its other
readers S 00429b60, S 00452140].

**Visibility of the whole screen** [known] S 00435980: set every frame: hidden while CLobby vtbl+0x8c or
vtbl+0x74 (customise mode) is true, and while the referee login is pending (§3.17); visible otherwise.

### 3.12 Selection info dialog (inventory, `lobbySelectionInfoDialog.xml`)

Widgets [known] S 0044ed80: `XPLabel`, `XPProgress`, `ToolTipProvider`, `LevelLabel`; equipment slots `Pet`,
`Head`, `RightHand`, `LeftHand` (InventoryButton); `PersonalAvatarInfo` with `InventoryBackground`,
`InventorySlot0..11`, `ButtonLeft`, `ButtonRight`, `Credits`, `PlayMoney`; `AvatarPreviewMale` /
`AvatarPreviewFemale`.

Per frame while visible (`Update` S 0044fe40) [known]: nothing changes while no actor is selected (CLobby
vtbl+0x9c). Otherwise title = name of the selected actor. For an avatar (actor type 1): equipment slots,
`!LEVEL_LABEL` + " " + level (S 0044fc80), the preview picture of its gender (gender 0 → `AvatarPreviewMale`
shown and `AvatarPreviewFemale` hidden, else the reverse), `Credits` = gold (+0xd0), `PlayMoney` = +0xd4,
the XP bar; the backpack only when the actor's id is the local perm id. For any other actor these parts are
hidden.

- **Backpack paging**: 12 visible slots; `page` 0..4 (+0xbb8); slot i shows backpack entry `page × 2 + i`
  (so the pages overlap and 20 entries are reachable); `ButtonLeft` enabled iff page > 0, `ButtonRight` iff
  page < 4 [known] S 0044f9f0, S 0044d2a0.
- **XP bar** [known] S 0044f800 and the bytes at S 007d8d90..007d8db3: value = (exp − low) / (high − low)
  with exp = the dword at actor +0xc8, low = dword at S 007d8d90 + 4 × level and high = dword at
  S 007d8d94 + 4 × level. The table T at S 007d8d94 holds six values, T = {0, 1000, 2500, 5000, 10000,
  25000}, so for level L (levels start at 1, `AvatarProxy::ResetLook` S 00482ad0): low = T[L − 1],
  high = T[L]: level 1 = 0..1000, 2 = 1000..2500, 3 = 2500..5000, 4 = 5000..10000, 5 = 10000..25000. The
  table ends there: at level 6 `high` is the unrelated dword that follows (0x00837504), and at level 0 `low`
  is 108, the tail bytes of the string `lobbyMinigameDialog_PawnChess.xml` in front of the table. Both
  differences are converted as unsigned 32-bit values. Tooltip of `ToolTipProvider` (only while its own
  description is unset): `<exp − low>/<high − low> (<percent, fixed notation, one decimal>%)`.
- **Slot icon**: item id ≠ 0 and count > 0 and a known item definition with an icon name → that icon from
  the `ItemIconDB`, and the item id becomes the slot widget's data value (+0x28); otherwise the empty icon
  and data value 0 [known] S 0044d430.
- **Tooltip** of a slot: for a slot with an item whose definition is valid and has a non-empty name, the
  name (localised) [known] S 0044d610.

Drag and drop and double click [known]:

| Gesture | Rule | Request |
|---|---|---|
| press on an inventory or equipment slot | starts a drag of kind 1 only if no drag is active, the slot holds an item (data value ≠ 0) and the id of the selection record (CLobby vtbl+0xa0) is the local perm id (S 00429b60) | — |
| press on a shop stock slot | starts a drag of kind 2 only if no drag is active, the slot's container is 6, its stock index is not -1 and the stock entry's item id is not the empty id (S 00429bd0, code bytes) | — |
| drop of an inventory item (kind 1) on a backpack slot, or on an equipment slot the item's flags allow (`CanDrop` S 0044d690) | `RequestMoveItem(src, dst, 1)`; sent only if source ≠ destination and the selected actor is an avatar with the local perm id (S 0044d7f0, S 0044d310) | 3001 MoveItem |
| drop of a shop item (kind 2) on a backpack slot | buy into that backpack index | 3610 ShopBuy |
| drop of a shop item elsewhere on the dialog, not on an equipment slot | buy with backpack index 0xFFFF (any) | 3610 ShopBuy |
| activation of a slot (`OnSlotActivated` S 0044e0f0; [inferred] a double click), no shop open, item in equipment (container 2..5) | a running drag is cancelled; if the item definition is valid: `SendMoveItem(container, index, 0, 0xff, 1)` = to the backpack, any slot | 3001 MoveItem |
| the same, item in the backpack | `SendMoveItem(0, index, dst, 0xff, 1)` with dst from the item's flags; with several bits the last match of bit 0 → 2, bit 3 → 5, bit 1 → 3, bit 2 → 4 wins (left hand over right hand over pet over head); no bit → nothing | 3001 MoveItem |
| the same on a backpack slot while a shop is open (other containers: nothing) | sell price ≠ 0 → box `!LOBBY_SELL_ITEM_CAPTION` / `!LOBBY_SELL_ITEM_QUESTION` formatted with the item name (Yes / No, tag = the slot's packed position); Yes → `SendShopSellItem(tag, 1)` (S 0044d520). Price 0 → box `!LOBBY_CANT_SELL_ITEM_CAPTION` with `!LOBBY_TRADER_NOT_WANTS_ITEM` (valid item definition) or `!LOBBY_CANT_SELL_ITEM` | 3620 ShopSell |
| drop of an inventory item on the 3D world (`WorldScreen` receiver, §2.6) | box `!LOBBY_DELETE_ITEM_TITLE` / `!LOBBY_DELETE_ITEM_TEXT` (Yes / No, tag = payload B); Yes → `SendDeleteItemRequest(container = byte 2 of the tag, index = low byte)` (S 00433160, S 004320b0) | 3002 DeleteItemRequest |

The dialog never changes the inventory itself; it redraws from the avatar's item container, which the server
updates with 3100 / 3101 / 3102 (`../village-and-character-protocol.md` §6.2).

### 3.13 Shop dialog (`lobbyShopDialog.xml`)

Widgets: `StockSlot0..24` (InventoryButton), `ItemName`, `ItemBuyPrice`, `ItemSellPrice` (Label),
`ItemDescription` (TextBlock) [known] S 0045d180. State: NPC `ActorID`, shop id, shop name, sell modifier
(float), stock vector of {item id, buy price, sell price} [known] S 0045d580.

- **Opening**: action code 11 sends 3600 OpenShop. The arrival of 3601 ShopInventoryData calls
  `WorldScreen::OnShopInventoryReceived` S 004323d0 → `ShopDialog::SetShop`; it refuses only when the
  dialog is already visible for another NPC or shop id. On acceptance the dialog is shown, the avatar
  position is latched and the `ObjectInspector` toggle is switched on (so the inventory opens beside it)
  [known]. No reply → no dialog; there is no client timeout [known: no time source].
- **Stock**: 25 slots show stock entries 0..24 (12-byte entries; no paging); a slot whose entry exists and
  names a known item gets the item icon, slot index = entry index, and is enabled iff the entry's buy price ≤
  the local avatar's gold; any other slot gets the empty icon and slot index -1. The slots are rebuilt after
  `SetShop` and whenever the local avatar's gold differs from the cached value [known] S 0045b790, S 0045b9f0.
- **Hover**: name and description of the item (localised when they start with `!`), buy and sell price of
  the stock entry; an empty slot shows `!LOBBY_SHOP_STOCK_EMPTY`, `!LOBBY_SHOP_NO_DESCRIPTION` and `---`
  [known] S 0045bea0.
- **Buying**: drag a stock slot (drag kind 2) onto the inventory dialog (§3.12), or double-click it: the
  activate handler S 0045b990 cancels a running drag and, for a slot of container 6, calls
  `SendShopBuyItem(stock index, 1, 0xFFFF)` = 3610 ShopBuy, quantity 1, any backpack slot [known: code
  bytes at S 0045b990; the call target is S 0046c400]. A disabled slot (price > gold) takes no input
  [inferred].
- **Selling**: the shop dialog accepts a drop only of kind 1 whose payload container is 0 (backpack)
  (`CanDrop` S 0045b740): sell price (`VillageServerConnection::GetShopSellPrice`) 0 → box
  `!LOBBY_CANT_SELL_ITEM_CAPTION` with `!LOBBY_TRADER_NOT_WANTS_ITEM` (valid item definition) or
  `!LOBBY_CANT_SELL_ITEM`; otherwise box `!LOBBY_SELL_ITEM_CAPTION` / `!LOBBY_SELL_ITEM_QUESTION` formatted
  with the item name (Yes / No, tag = payload B); Yes → 3620 ShopSell(backpack index, 1) [known] S 0045c560,
  S 0045b960. The price rule is in `../village-and-character-protocol.md` §6.1.
- **Closing**: walk-away watch (§3.2) or the close button → hide, end any drag, `ClearShop`. Nothing is sent
  [known] S 0045b920.

Neither 3611 ShopBuyResult nor 3621 ShopSellResult has a handler in the `LobbyMenu` classes; the dialogs
show the outcome only through the inventory and gold updates the server pushes [known: no subscription in
`ShopDialog` or `SelectionInfoDialog`; inferred for the consequence].

### 3.14 Mail: mailbox and mail dialog

**Mailbox** (`lobbyMailboxDialog.xml`): `Tabs`, `Inbox` (ListBox2), `MessageReceiver`, `MessageSubject`,
`MessageText` (EditEx), `MessageSend`, `MessageAbort` [known] S 004504e0. Opened by action code 7 (the
letterbox), which also requests the headers (147 RequestPrivateMessageList).

| Element | Rule | Tag |
|---|---|---|
| inbox | each frame while visible: every newly arrived mail of the `PostOffice` (`CollectNewMails`) gets a row (text = subject, row value = mail id, child `Sender` = sender name); if a row with that id exists only its `Sender` text is refreshed | [known] S 00450e10 |
| click on a row | show the child `MailDialog` at `SetAnchoredPosition(1, 1, +its width / 2, 0)`, move the mailbox to `(1, 1, −its width / 2, 0)` (the two dialogs side by side) and `MailDialog::OpenMail(id)` | [known] S 004509d0 |
| `MessageSend` | receiver empty → `!ERROR` / `!LOBBY_MAIL_NEED_RECIPIENT`; subject empty → `!LOBBY_MAIL_NEED_SUBJECT`; text empty → `!LOBBY_MAIL_NEED_TEXT`; else `PostOffice::SendMail(receiver, subject, text, callback)` (150 AddPrivateMessage) | [known] S 004509d0 |
| send result 0 | box `!LOBBY_MAIL_SEND_CAPTION` / `!LOBBY_MAIL_SEND_TEXT`; the three fields are cleared | [known] S 00450800 |
| send result ≠ 0 | box `!LOBBY_MAIL_NOTSEND_CAPTION` / `!LOBBY_MAIL_NOTSEND_TEXT`; fields kept | [known] S 00450800 |
| `MessageAbort` | clear the fields and hide | [known] S 004509d0 |
| mail deleted (`PostOffice+0xb8`) | the row with that id is removed at once, before the server confirms | [known] S 00450230 |

**Mail dialog** (`lobbyMailDialog.xml`): `From`, `Subject`, `Text` (EditEx), `Delete`, `Reply` [known]
S 0045a6e0.

- `OpenMail(id)` S 0045ab40: `PostOffice::RequestMail(id)`; if that fails nothing is shown or parked. If the
  mail is complete (id ≠ 0, subject and body non-empty, not pending deletion, content flag set) it is shown
  at once, otherwise the id is parked and shown when the mail-arrived observer (`OnMailArrived` S 0045ac70)
  reports it [known for `OpenMail`; the observer body was not read].
- `ShowMail` S 0045a990: From = sender name, Subject, Text; window title = `!MAIL_DIALOG_LABEL` + " " +
  sender [known].
- `Delete` (only while a mail is shown): `PostOffice::DeleteMail(id)` (151 RemovePrivateMessage), hide
  [known] S 0045ad40.
- `Reply` (only while a mail is shown) notifies the mailbox, which fills receiver = sender; subject =
  `RE: ` + subject unless the subject already contains `RE:` or `AW:` anywhere; text = every body line
  (split at `\n`) as `> ` + line + `\n`; hides the mail dialog, centres itself, selects tab 0 of the tab
  control `Tabs` and focuses the text field [known] S 00451160.

Wire details: `../message-catalog.md` section "Mail (private messages)".

### 3.15 Friends and ignore list, hall of fame, report issue

**Friends / ignore** (`lobbyFriendIgnoreListDialog.xml`; `FriendList`, `IgnoreList`, `AddToFriendList`,
`RemoveFromFriendList`, `AddToIgnoreList`, `RemoveFromIgnoreList`) [known] S 00452960:

- Friend rows: name, row value = user id; text colour (255, 209, 213) when the buddy entry's value at +0x20
  is not -1, else (101, 74, 71) [known] S 004518a0; the meaning "online" of that value is [inferred].
  Ignore rows: colour (255, 224, 224) [known] S 004519b0.
- The rows follow the `CharacterManager` observers (+0x20 / +0x2c buddy added or updated, +0x38 buddy
  removed, +0x44 ignore added, +0x50 ignore removed); a click never edits the lists directly [known]
  S 00452860, S 00451aa0..00451de0.
- `AddToFriendList` / `AddToIgnoreList`: enabled only while a selection record exists (CLobby vtbl+0xa0)
  that is not an NPC (type ≠ 2) and not the local perm id; click → `CharacterManager::AddToFriendList(id)` /
  `AddToIgnoreList(id)` unless a row with that id is already in that list (98 AddUserBuddy / 154
  AddUserIgnore) [known] S 00452400, S 00452140.
- `RemoveFrom…`: enabled only while a row of that list is selected; click → `RemoveFromFriendList(id)` /
  `RemoveFromIgnoreList(id)` (99 / 155) [known].
- A friend-row event of the `ListBox2` observer list at list +0x182c, received while Shift is held
  (`LobbyAction` vtbl+0x24), prefills `/tell <name> ` in the chat and hides the dialog, both only if the
  name is cached; without Shift nothing happens [known] S 00451ec0, S 00452960. The list +0x182c is the
  "row selected" list, notified with (list, row) by `nUi::ListBox2::OnItemSelected` S 004b90d0 for the row
  that becomes marked (single-mark mode); double clicks go to the list at +0x1838 (S 004b9180) [known]. So
  the event is a Shift + click on a friend row.
- The dialog is toggled by the `Friends` button and positioned with `SetAnchoredPosition(0, 1, …)` (left
  edge, vertically centred) [known] S 004389d0, S 00437760.

**Hall of fame** (`lobbyHallOfFameDialog.xml`; `WebPage`, `Slider`, `Button_0..2`) [known] S 004427a0,
S 00442230, S 004428f0: an embedded web view, texture 1024 × 512, shown through a 768 × 512 source
rectangle. `Button_i` (i = 0..2) navigates to URL i = `HallOfFameURL<i>` of `LobbySettings.ini`
(`LobbyProfile::GetHallOfFameUrl`), with `&permid=<local perm id>` appended when
`HallOfFameURL<i>_AppendPermID` is set and `&char=<character name>` when `_AppendCharname` is set
(S 00442640). Shipped values [known: `data/lobby/config/LobbySettings.ini`]: three URLs on
`http://sadk.funatics.de:7012/rankingMaster/ranking.php` with `ranking=weekly`, `monthly`, `yearly`
(`&limit=20&offset=0`), each with `_AppendPermID=1`. The slider range is the page's scroll extent and scrolls the
page. HTTP only; no lobby message. The web texture class was not read (§10).

**Report issue** (`lobbyReportIssueDialog.xml`; `IssueType` drop-down, `IssueShortDescription`,
`IssueLongDescription`, `SendButton`) [known] S 0045af30, S 0045b320: picking an issue type copies the row text
into the drop-down caption and closes the menu. Send: short description empty → `!ERROR` /
`!REPORT_ISSUE_NEED_SUBJECT`; long description empty → `!REPORT_ISSUE_NEED_TEXT`; else
`PostOffice::SendMail("CrashBot", "<drop-down caption> - <short>", long, callback)` (150 AddPrivateMessage).
Result 0 → box `!REPORT_ISSUE_SEND_CAPTION` / `!REPORT_ISSUE_SEND_TEXT`, fields cleared, dialog hidden;
otherwise `!REPORT_ISSUE_NOTSEND_CAPTION` / `!REPORT_ISSUE_NOTSEND_TEXT` and the form is kept [known] S
0045b160.

### 3.16 Password and stake dialogs

| Dialog | Widgets | Rule | Tag |
|---|---|---|---|
| `EnterPasswordDialog` | `EditExPassword`, `OkButton`, `CancelButton` | Ok: callback(checksum of the typed text from `ai::core::Crc32Acc`, or 0 when empty; cancelled = 0), then `Close`. Cancel: callback(0xFFFFFFFF, 1), then `Close`. The plain text never leaves the dialog. That the checksum is the standard CRC-32 is [inferred] from the class name. | [known] S 00441100 |
| `SetStackDialog` | `editWager`, `stackDec`, `stackInc` (kind 10), `LabelStack`, `LabelDisplayCredits`, `currency` (picture), `OkButton`, `CancelButton` | Per frame while visible: label = `!SETSTACKDLG_STACK` formatted with the minimum; stake = `atol`(edit text), below min → min, above max → max; `stackInc` enabled iff stake < max, `stackDec` iff stake > min. The edit text itself is rewritten only when Enter is pressed while the edit has the focus (clamped stake) and after `stackDec` / `stackInc` (stake ∓ 1). Ok: stake parsed and clamped again, callback(stake, 0), `Close`; Cancel: callback(-1, 1), `Close`; close button (slot 36): callback(-1, 1), callback dropped, closed. The constructor arguments (limits, currency, initial stake) are in [minigames-client.md](minigames-client.md). | [known] S 00441560, S 00441760, S 00441530 |
| `SetPasswordDialog` (host sets the game password) | `PasswordEdit`, `OkayButton`, `AbortButton`, `ClearButton` | all four widgets must exist; listeners get (0, text) / (1, "") / (2, "") = set / cancel / remove; the edit is cleared after any button. The opener prefills the current password (`SetPasswordText` S 0045d710). | [known] S 0045dab0 |
| `GetPasswordDialog` (joiner types the game password) | `PasswordEdit`, `OkayButton`, `AbortButton` | listeners get (0, text) or (1, ""); the edit is cleared. Neither password dialog closes itself in these handlers. | [known] S 0045deb0 |

What the callers do with the results (wager limits, password digests, messages) is in
`match-setup-room.md` and in `../message-catalog.md` section "Minigames".

### 3.17 Match start supervision and minigame dialogs on the world screen

**Referee login pump** (the world screen is the client of the referee handshake; the full chain is in
[../MATCH_START.md](../MATCH_START.md)) [known]:

- Village connection logged out (S 004316c0): if CLobby vtbl+0x8c is true, only hide the screen. Else if the
  NComm state is not 0 and its StartLoading flag is set: tries = 0, pending = 1, armed = 1, delay = 16
  frames. Else: `NComm_Manager::Shutdown(false)` if the NComm state is not 0, clear pending and armed, and,
  if the event source is the local perm id or the chat server handle, request screen 2 and
  `CloseDialogs(false)`.
- Each frame while pending (S 00435980): hide the screen; if tries > 4 or the NComm state is 0 → clear
  pending and armed, request screen 2, `CloseDialogs(false)`, `NComm_Manager::Shutdown(false)`. Else, if
  StartLoading is set and armed: delay 0 → `RefereeServerConnection::Login(local perm id)` and armed = 0;
  otherwise delay −= 1.
- Referee connection logged in (S 00431780): pending = 1, armed = 0.
- Referee login failed, on either failure list (S 004317a0, S 004317d0): tries += 1, armed = 1,
  delay = tries × 8 + 16 frames.
- Referee LoginSuccess (S 00432240): `RefereeServerConnection::RegisterGame(game id, map GUID, map name,
  settings digit string, ranked flag, wager, number of AI slots, the avatar ids of the slots (array of 6))`,
  all taken from the NComm game information = 3510 RegisterGame. RegisterGameResult (S 00431800): only if
  the room dialog exists: store the game seed (`NComm_Manager::SetGameSeedIfState2`),
  `SetupGameDialog::SetupSession`, clear pending and armed, CLobby vtbl+0x2c(1) (leave the lobby into the
  match). RegisterGame failed (S 00432fd0): box `!ERROR` / `!REGISTER_GAME_FAILED` (Ok); its result handler
  logs out of the referee and shuts NComm down (S 00431f70).

The delays are frame counts, not times: the logins are attempted after 16, 24, 32, 40 and 48 frames and the
fifth failure gives up [inferred from the two rules above].

**Village connection lost** (S 00432ed0) [known]: request screen 2, close the dialogs; if a reason is given,
box `!ERROR_DIALOG` / `!CONNECTION_LOST_TEXT` (Ok).

**Minigame tables** [known] S 00431a00, S 00431ac0, S 00431e90, S 00431f00, S 00433280, S 00433380:

- Matchmaking dialog modes and the tavern rule: `../message-catalog.md` "Matchmaking dialog and tavern ids".
- `EnterMiniGameMode(table)`: remember the active chat channel, register the table's channel
  (`SetMiniGameChatChannel`), select and clear chat tab 3, hide five selection widgets (`SelectionBackground`,
  `SelectionPicture`, the three action buttons) and the minimap, open the table dialog by game type (1 Dice,
  2 Poker, 3 PawnChess; other types open nothing, S 0042b880). Its callers are the Dice and Poker table views
  (S 0051b670, S 0051bd90) [known: caller list]; how a Pawn Chess table reaches it is in
  [minigames-client.md](minigames-client.md).
- `LeaveMiniGameMode`: clear the table's channel, disable tab 3, reselect channel 1 if it was active before,
  else 2; show the five widgets and the minimap again; enable world picking (CLobby vtbl+0xd4(1)).
- Observer overlay (`MinigameDialog_Observer`, button `leaveMiniGame`): shown while watching a table; the
  selection widgets and the minimap are hidden meanwhile.
- 219 MiniGameNoTableLeft / 220 MiniGameNoPlayerSlotLeft: box `!ERROR_DIALOG` / `!MINIGAME_NOTABLELEFT` or
  `!MINIGAME_NOPLAYERSLOTLEFT`, then world picking is enabled again.
- `MiniGameManualDialog` (`Edit_Manual`, `Button_Prev`, `Button_Next`): pages are the localisation keys
  `!MINIGAME_<id>_MANUAL_PAGE<n>` (format `!MINIGAME_%d_MANUAL_PAGE%d`), counted by probing n = 1, 2, …
  (S 00442dc0, S 00442a40; the end test of the probe was not read).

The Dice, Poker and PawnChess dialogs themselves are specified in [minigames-client.md](minigames-client.md).

### 3.18 Village keys (`LobbyMenu::LobbyAction`, vftable S 007d6824)

Singleton input object, active while the lobby is shown (`CLobby::ProcessModeTransition` swaps it in for the
game's `GameAction`) [known] S 004f5950. Movement keys are ignored while a text field or UI widget has focus
(`g_TextInput_FocusedWidget` ≠ 0 or `UiFocus_HasActiveFocus()`). Held keys are tested with `LobbyAction`
vtbl+0x28(vk, 2), one-shot keys with vtbl+0x2c(vk, 0); Ctrl and Shift are the bytes +0xd04 / +0xd05 (vtbl+0x20
/ +0x24), kept by `nUi::BaseAction::OnKeyEvent` S 00490f50 from the key events of VK 0x11 / 0x10 [known].

| Function | Keys | Tag |
|---|---|---|
| turn left / right | Q or Left (0x51, 0x25) / E or Right (0x45, 0x27) | [known] S 004294a0, S 004294f0 |
| forward | W or Up (0x57, 0x26); mouse X-button 1 (VK 5) works even while typing | [known] S 004295c0 |
| backward | S or Down (0x53, 0x28) | [known] S 00429620 |
| strafe left / right | A (0x41) / D (0x44) | [known] S 00429540, S 00429580 |
| run | Shift (0x10) | [known] S 00429670 |
| space action | Space (0x20) | [known] S 004296c0 |
| mouse look | active while the capture is on and, in mode 0, the middle (VK 4) or right (VK 2) button is held, in mode 1 (set by the dice table view) the middle button only. The capture starts on the key event of such a button and ends on its release event (type 2): the cursor is hidden and moved to the centre of the client area, every mouse move adds its offset from the centre to two accumulators (y negated when "invert Y" is set) and re-centres the cursor. The two scale values are 500.0 | [known] S 00428fd0, S 00429430, S 004290d0, S 00429360, S 00428e10. `GetMouseLookYaw` S 00429030 = accumulator X / (client width / 2, integer division) × scale X, and 0 while mouse look is not active or the client width is ≤ 1; `GetMouseLookPitch` S 00429080 the same with accumulator Y, the client height and scale Y [known] |
| chat | open: Enter (0x0d); open with `/`: Shift + 7 (0x37); whisper reply: Shift + R (0x52); these three only without focus. Send: Enter, only while a text field or UI widget has focus (§3.10) | [known] S 00429700, S 00429740, S 00429780, S 004297c0 |
| minimap zoom | Ctrl + numpad plus (0x6b) = in, Ctrl + numpad minus (0x6d) = out | [known] S 00429840, S 00429880 |
| debug overlay | F7 (0x76), read by `CLobby::DrawDebugOverlay` | [known] S 00429800 |

---

## 4. Update order

Per frame, `Lobby::CLobby::Tick` S 004fb230 calls `System::Update(handleInput)` S 0042a860, only while the
CLobby mode is 2 or 3; `handleInput` is true in a frame in which at least one fixed step of the 3D lobby ran
(or its dirty flag forced one), so clicks and the key poll follow the lobby's step clock
([lobby-world-client.md](lobby-world-client.md)), not the frame rate [known] S 004fb230.
`CLobby::ProcessModeTransition` S 004f5950 calls `Update(true)` directly as well (§3.1) [known: caller list].

1. `nUi::Root` update (root vtbl+4) [known].
2. If a screen switch is pending: `UpdateMessageBoxes(true)`, `UpdateDialogs(true)`, switch (§3.1), the same
   two calls again, return. With `true` the two functions still set the desktop states of steps 4 and 6 and
   delete closed boxes and dialogs, but call no `Update` [known] S 0042a860, S 0042a6b0, S 0042a1c0.
3. Reload the localisation if the language changed; update the cursor; `UiDragState_Update` S 0042d320: in
   every state but 0 store the cursor position (+0xbc..+0xc8); in state 1 go to state 2 once the cursor is
   more than 3 pixels from the press position on the x axis or on the y axis (|dx| > 3 or |dy| > 3, each
   truncated to whole pixels) [known].
4. `UpdateMessageBoxes(false)`: message-box desktop shown and enabled while a box exists, else hidden and
   disabled; every active box whose `IsCloseRequested` is true gets `OnLeave(0)` (if shown) and
   `Deactivate(0)` and is deleted, every other active box gets `Update` [known] S 0042a6b0.
5. Current screen `Update` (slot 8), only if the screen `IsActive` (slot 17) [known].
6. `UpdateDialogs(false)`: screen desktop enabled iff no box exists; closed dialogs deleted, the other active
   ones updated (§3.1) [known] S 0042a1c0.
7. If `handleInput`: `DispatchButtonClicks` S 0042a020 (while a box exists: `HandleButtonClicks` of every
   active and shown box, nothing else; otherwise the current screen if active, then every active and shown
   dialog in list order), then `LobbyAction` vtbl+4 = `LobbyAction::PollAsyncKeys` S 00428f30 (only while its
   byte +0xd06 is set: client size from `GetClientRect`, a per-key held-frames counter from
   `GetAsyncKeyState` for the 256 virtual keys, key states of -1 reset to 0) [known: vtable bytes at
   S 007d6824].

`System::Render` S 0042a650 (from `CLobby::RenderFrame` S 004f9960, in CLobby mode 2 or 3 and only while the
byte S 0087c628 is set; [inferred] the debug switch "Lobby / Show Menu" named in that function): render hook
(slot 10) of every active message box that has no close request, the same for the dialogs, the current
screen's render hook if it is active, the `nUi` root (vtbl+0x1c), and last the dragged icon
(`UiDragState_RenderDragIcon` S 0042df80, state 2 or 3 only): drawn at its natural size at the cursor
position minus 4 pixels on both axes, with the colour floats (1, c, c, 1), c = 1 if `CanDropAt` accepts at
the cursor and 0 otherwise; the result is also stored in +0xcc [known]. Read as r, g, b, a that is white /
red [inferred].

Mouse release on an inventory slot (`System::OnDragSourceReleased` S 00429950): in state 1 → `BeginCarry`
S 0042d0c0 with the same payload and icon = state 3 (the item sticks to the cursor; press and current
position are both set to the cursor); in any other state `EndDrag(false)` S 0042e140: in state 2 or 3, if
`CanDropAt` is true, the receivers under the cursor get `OnDrop` in priority order until one returns 1; the
state is reset in every case (§2.6) [known].

Order inside `WorldScreen::Update`: visibility, referee pump, selection info dialog, `RefreshActionSlots`,
friends toggle, selection labels, clock, connection quality, mail indicator, server name, room dialog /
matchmaking indicator / channel 4, minimap (vtbl+0x10) [known] S 00435980. The frame in which the pump
calls the referee `Login` and the frame in which it gives up end right there, without the later steps
[known]. Inside `WorldScreen::HandleButtonClicks` S 00437760 [known]: base test (`inputEnabled`), then
return true if CLobby vtbl+0x8c is set, then auto-dispatch, action buttons A / B / C, main menu,
matchmaking indicator, server menu, emote menu, friends button, minimap zoom keys (minimap vtbl+0x14, always
run), chat keys. A consumed click ends the handler with false, except main menu items 0 (host game) and 1
(game browser), after which the later tests of the same call still run.

On load: `System::Initialize` S 0042ad80 calls `LobbyMenu_PreloadUiResources` S 0042a940 (registers the nine
UI sounds `uiClick0`, `uiClick1`, `uiCancel`, `uiMessage0`, `uiMessage1`, `uiDialog0`, `uiKey0`, `uiRemove`,
`clock_5sec` and sets the dword +0x240c to 1 in the four fonts `light_system`, `dark_system`,
`light_system_outlined`, `mini_silk`), registers itself as a listener of the graphic device, calls vtbl+0x84
on both desktops, names the second one "MessageBoxDesktop", creates the four screens and loads
`itemicons.txt` [known].

---

## 5. Inputs and outputs

**Consumes**: the lobby layouts and text tables (§6); mouse and keyboard through `nUi` and `LobbyAction`;
model state of `LobbyComm::System` (state, perm id, character list, server list, mail, buddy and ignore maps, item
definitions, local avatar) and of `Lobby::CLobby` (selection, local avatar, customise mode, distance
watches).

**Produces**: calls into the model, listed with the message each call sends. All ids refer to
[../message-catalog.md](../message-catalog.md) (sections named in brackets).

| UI action | Model call | Message |
|---|---|---|
| login Okay | `LobbyComm::System::Login` | 188, 201, 204 and following ["Login, authentication and the UC/chat connection"] |
| create account Okay | `LobbyComm::System::CreateUser` | 203 SelfRegistration |
| cancel login / Back | `LobbyComm::System::Logout` | connection close |
| MOTD dialog | (source `LobbyComm::System+0x100`) | 105 / 106 ["MotD"] |
| create character | `CharacterManager::CreateCharacter` S 004750f0 (queued) | 86 AddCharacter → 153 AddResult ["Characters"] |
| delete character | `CharacterManager::DeleteCharacter` S 004751e0 (queued) | 94 RemoveCharacter |
| enter village | CLobby vtbl+0x80 `RequestEnterVillage` S 004f5070 → `CLobbyClient::EnterVillage` | chain of `../village-and-character-protocol.md` §2.3; answer 1000 EnterWorld |
| leave village | CLobby vtbl+0x84 `RequestExitVillage` S 004f5090 | in CLobby mode 2 only a mode change (vtbl+0x2c(0)), no message; otherwise `CLobbyClient::LeaveVillage` S 00503470 (saves the avatar's position, zone and heading) → 2002 LeaveVillageRequest ["Leave"] [known] |
| switch village | CLobby vtbl+0x88 `RequestReenterVillage` S 004f50c0 → `CLobbyClient` S 00503560 | re-entry pending, timeout 2.5, retries 0, then the same leave (2002); the entry that follows is in [lobby-client-state.md](lobby-client-state.md) [known] |
| chat line | `UserCommConnection::SendChatMessage` | 2 ChatMessage ["UC / chat connection"] |
| whisper | `UserCommConnection::QueuePrivateMessage` | 30 WhisperChatMessage |
| `/ac` | `VillageServerConnection::SendChatCommand` | 4000 ChatCommand |
| room / match chat | `NComm_Manager::SendChatToAll` | NComm text event ([../NCOMM_GAME_PROTOCOL.md](../NCOMM_GAME_PROTOCOL.md)) |
| host game | `ServerList::CreateGameServer` | 168 AddGameServer ["Server list"] |
| open shop | `VillageServerConnection::SendOpenShop` | 3600 → 3601 ["Shops"] |
| buy / sell | `SendShopBuyItem` / `SendShopSellItem` | 3610 / 3620 |
| move / delete item | `VillageServerConnection::SendMoveItem` (directly, or through `Village_TrySendMoveItem` S 0048acc0) / `SendDeleteItemRequest` | 3001 / 3002 ["Inventory"] |
| tailor confirm | village connection | 3950 AvatarColorChange ["Avatars"] |
| mail list / read / send / delete | `PostOffice::RequestMailHeaders` / `RequestMail` / `SendMail` / `DeleteMail`; each only queues an operation that `PostOffice::Process` sends later | list 147 RequestPrivateMessageList (answered by 149 PrivateMessage records); opening a mail sends nothing for the body (`MailManager::GetMessage` T 10028a30 answers at once from the cache of 149 records, error 0x92 when the id is not cached) and then 148 ChangePrivateMessage (mark read, from `PostOffice::MailReceived`); send 150 AddPrivateMessage (after a name lookup when the recipient id is not cached); delete 151 RemovePrivateMessage ["Mail (private messages)"] [known for T 10028a30 and the caller lists; the operation table of `PostOffice::Process` S 0047d880 is taken from `../message-catalog.md`] |
| add / remove friend | `CharacterManager` | 98 / 99 ["Buddies (friends)"] |
| add / remove ignore | `CharacterManager` | 154 / 155 ["Ignore list"] |
| referee login, register game | `RefereeServerConnection::Login` S 004793f0 (opens the connection; builds no message itself) / `RegisterGame` S 00479840 | the referee connection's login, then 3510 RegisterGame ["Referee / match arbiter"] |

**Handles** (through observer lists, not message handlers): login succeeded / failed / version check failed;
character created / create failed; lobby logged out; connection lost; server list entry added, changed,
removed; village connection logged out, disconnected, no table left, no player slot left; shop inventory
received (3601); mail arrived / deleted; buddy and ignore changes; channel and private chat lines; referee
login, login failure, register-game result and failure.

---

## 6. Data-driven parameters

- **Layouts**: `data/lobby/ui/layout/lobby*.xml` (encrypted in the install; XML, ISO-8859-1), one per screen
  and dialog as listed in §2.1 and §2.2, plus the shared `data/game/ui/layout/templates.xml` (the same file
  the offline menu uses; templates such as `LobbyAction_None` / `_HostGame` / `_ListGames` / `_Mailbox` /
  `_OpenShop` / `_HoF` / `_HairColor` / `_MinigameMatchmaking`, `LobbyChat`, `NormalDialog_CloseButton`,
  `NormalDialog_Edit`, `TribeButton`, the icon templates `<Tribe><Gender>Small` for `Bavarian`, `Egypt`,
  `Scot`) [known: the files]. A layout decides positions, textures, texts, `maxLength`, `allowedChars`,
  `isPassword`, hotkeys and initial visibility. Example values [known: the files]:
  `lobbyAvatarScreen.xml` root attribute `CodersRule="false"`, `BackButton hotkey="27"`;
  `lobbyCustomizeAvatarDialog.xml` `AvatarCount="6"`, `ColorCount="16"`, `AvatarButton_2 data="256"`;
  `lobbyWorldScreen.xml` `<Chat template="LobbyChat" MinHeight="112" MaxHeight="384">`, `Minimap` size
  `244 244` (aligned right / bottom, offset `-8 -8`) with texture `Village_Minimap` and mask `ui_mask.tga`,
  `MainMenu size="6" string0="!LOBBY_MAIN_MENU_HOST_GAME"` … `string5="!LOBBY_MAIN_MENU_LEAVE"`,
  `ConnectionQuality` size `16 13` with `texture="ui_menus" mapping="160 947 16 13"`.
- **Component layouts**: `LobbyMenu::ComponentBase::LoadFromXml` S 00462280 looks up a named child node
  (false if it is missing); if it has a `template` attribute and `templates.xml` opens and contains a node of
  that name, the component is first loaded from that template node (its own vtable slot `LoadFromXml`), then
  in every case bound to its own node (slot `BindWidgets`) [known].
- **Texts**: every string starting with `!` is a localisation key (keys named throughout §3).
- **`itemicons.txt`** (item icon atlas; entries `InvalidIcon` and `EmptyIcon` are required) and
  **`QuickEmotes.txt`**: formats in [formats-inventory.md](formats-inventory.md) §3.10.
  Both are plain text in `data/lobby/config` [known: the files; e.g. `InvalidIcon;ui_items;444;224;40;40`].
- **`data/lobby/config/LobbySettings.ini`** (plain text): `[LobbyServer] Host`, `Port` (default 7070 when
  the key is missing, S 00465450); `[LobbyClient] HallOfFameURL0..2` and the `_AppendPermID` /
  `_AppendCharname` switches (key formats `HallOfFameURL%d`, `HallOfFameURL%d_AppendPermID`,
  `HallOfFameURL%d_AppendCharname`, S 00465960); `[LobbyClient] ProtocolVersion`, read by
  `LobbyClient_LoadProtocolVersion` S 00465380 from the login and create-account dialogs [known]. The
  shipped file has only `Host`, `Port` and the three URLs with `_AppendPermID=1` [known: the file]; the
  default of a missing `ProtocolVersion` is in [app-shell.md](app-shell.md).
- **Constants in the binary**: XP thresholds (§3.12), minimap zoom table and marker radius (§3.10), walk-away
  radius 2.0 (§3.2), tailor price gate 50 (§3.8), 8 characters per account (§3.7), 25 stock slots (§3.13),
  12 visible backpack slots and 5 pages (§3.12), message box minimum height 224 px and chrome 159 px (§3.1),
  drag threshold 3 px (§4), support URL `http://support.ubisoft.de/home.php`, report recipient `CrashBot`.

---

## 7. Save and load

The UI persists only, through `LobbyProfile` (the per-user lobby file, [app-shell.md](app-shell.md)):

- user name and CD key (`LobbyProfile::SaveUserName` S 00465530, `SaveCDKey` S 00465620) after a successful
  login with `SaveUsername` ticked, and after a successful account creation without that test; both only
  while the dialog's wait box is still active [known] S 0043c1a0, S 0043d960;
- it reads user name, CD key and password to prefill the login dialog [known] S 0043d150. No function of
  these classes writes the password [known: the caller lists of `SaveUserName` and `SaveCDKey` are the two
  functions above; the generic writer `LobbyProfile::SetUserString` S 00465220 is called by those two only;
  `LobbyProfile::GetPassword` S 00466480 has the one caller S 0043d150]. A stored password can therefore
  only come from a hand-edited per-user file [inferred].

Everything else (characters, inventory, mail, friends, position) is server state. Dialog positions, the
minimap zoom, the active chat channel and the chat history are not saved [known: `SetUserString` has no
other caller].

---

## 8. Determinism notes

Front end only. No function of these classes writes simulation state: the lobby runs outside a match
[inferred]. Its timing: the referee retry delays count calls of `WorldScreen::Update`, i.e. rendered frames;
the matchmaking indicator blinks on the wall clock (marked while elapsed milliseconds mod 1000 < 500);
clicks and the key poll run only in frames in which the 3D lobby stepped (§4) [known] S 00435980,
S 004fb230. The only `rand()` call of the dialog classes is the Randomize button (§3.8) [known: of the
callers of `_rand` S 006f41e2 only S 0043e500 is a `LobbyMenu` function; the others in the lobby are the
minigame table views and avatar code]; that is the C runtime generator, not the simulation generator
`g_LogicRandom`. The one value that crosses into a match is the referee's game seed, stored into the NComm
session by `OnRefereeRegisterGameResult` S 00431800 (`NComm_Manager::SetGameSeedIfState2`, only while the
room dialog exists) [known]; its use is in [network-session.md](network-session.md) and
[players-victory.md](players-victory.md) (chest contents).

---

## 9. Notes for a Godot reimplementation

- **Structure**: one manager node with a screen layer, a dialog layer and a modal layer maps onto
  `System`. Reproduce the deferred screen switch (request now, switch at the start of the next update, right
  after the `nUi` root update) and
  the modal rule (while a box exists, only boxes get clicks and the other layers are input-disabled); several
  flows rely on a box being opened while its dialog is hidden and shown again from the box result.
- **Message boxes**: button sets 1..5 and results 1..6 as in §2.5; the tag is the only way a result handler
  tells its boxes apart, so keep it. Keys starting with `!` are localised at open time.
- **Engine features**: `Control` scenes per dialog built from the converted layouts; `ItemList` or custom
  rows for ListBox2; Godot's drag-and-drop can replace `UiDragState`, but keep the click-to-carry mode
  (press and release without moving picks the item up) and the three receivers with their acceptance rules.
- **Must be reproduced exactly**: the client-side validation order and limits (they define which requests a
  server ever sees): login needs three non-empty fields; create-account checks 1..8; character name ≤ 16
  bytes within the layout's character set, empty name not rejected by the client; 8 characters; tailor gate
  50 gold and "only colour slots 3..7 in the village"; backpack index = page × 2 + slot; shop slot enabled
  iff price ≤ gold; action codes and the auto-dispatch of a single action on selection; chat command table
  and the `/r ` expansion; walk-away radius 2.0.
- **A server has to provide**: every answer the dialogs wait for, because no dialog has a timeout (login
  result, version check, account creation result, AddResult for a character, EnterWorld, 3601 for a shop,
  mail results, referee answers). A missing answer leaves a wait box without buttons (account creation,
  character creation) that the player cannot leave. After a shop transaction or an item move the server
  must push the new inventory and gold, as the client changes nothing locally.
- **A converter has to provide**: the lobby layouts, `templates.xml`, the localisation tables,
  `itemicons.txt`, `QuickEmotes.txt`, the UI textures (named by the lobby layouts themselves: `ui_ingame`,
  `ui_ingame3`, `ui_ingame4`, `ui_ingame5`, `ui_menus`, `pokercards`, `Village_Minimap`, mask `ui_mask.tga`;
  by `itemicons.txt`: `ui_items`; the textures of the templates used come on top) [known: the files], and
  `LobbySettings.ini` values.
- **Replace**: the hall-of-fame web view (an embedded browser on a dead URL), the Ubisoft support links, the
  `CrashBot` report mail and the CD-key field need new decisions; none of them is needed to play.
- **Known quirks to decide on**: the XP bar reads past its table at level 6; the close button of dialogs
  whose slot 36 is the base does nothing; the connection-quality icon and the `CodersRule` server picker are
  development leftovers.

---

## 10. Open questions

1. **Avatar screen after a failed "enter village"**: Answered (§3.6): with no joinable village server the
   handler S 0043abc0 shows "FEHLER" / "Willkommen im Dorf" (the shipped German text of
   `!COULDNOT_CONNECT_TO_VILLAGE`), +0x218 stays 1, the buttons are re-enabled and the player is not stuck
   [live, 2026-10-14]. `HandleButtonClicks` S 0043bd50 still calls `DisableButtons` after the handler
   [known]; that path was not exercised, because Start cannot be pressed without a joinable server.
2. **Unreachable box results**: the wait box (tag 0x3000) and the connection-lost box (tag 0x500) of the
   avatar screen have button set 5; confirm that nothing but `MessageBoxDialog::HandleButtonClicks`
   S 0045ebe0 notifies the result list +0xb48 (xrefs of `ObserverList_NotifyAll` with a box).
3. **Colour values out of range**: `AdjustColor` S 0046b750 only adds to a byte; how the look application
   (CLobby vtbl+0xb8) maps a value beyond the available colours, and how many colours each slot has.
4. **Shop results**: 3611 ShopBuyResult and 3621 ShopSellResult only notify the observer lists
   `VillageServerConnection+0x134` / `+0x140` (S 00470990, S 00470a10) [known]. No subscription to either
   list was found: the code sequences `lea reg, [reg+0x134]` / `[reg+0x140]` or `add ecx, 0x134` / `0x140`
   directly followed by a call occur, on this class, only in the two handlers and in the connection's
   destructor S 0046e8f0 [known: byte search], and no call of `ObserverList::Subscribe` S 00458860, the only
   subscribe function, names either list (its calls on the village connection are in S 00503d00 and
   S 004351a0) [known]. The client shows nothing on a result. Answered.
5. **Minimap markers**: no function of `LobbyMenu::Minimap` appends to the marker vector (+0x18, §3.10);
   find the writers of `Minimap+0x1c..+0x24` and what they mark (friends, selected target, quest marks).
   Which offset component feeds the edge-arrow angle: the disassembly of S 0045fd30 around the `acos` call.
6. **Hall-of-fame web texture**: the class behind +0xb68 (navigate vtbl+0x1c, scroll vtbl+0x18, extent
   vtbl+0x14) is not identified.
7. **NPC with more than one action**, and the matchmaker NPC: answered in
   `../village-and-character-protocol.md` §5.2. An NPC with two or three actions cannot run any of them
   (its buttons are hidden and no automatic dispatch happens) [known; live, 2026-10-12]; the matchmaker
   NPC opens `MiniGameMatchMakingDialog` on selection [live, 2026-10-12].
8. **Colour component order**: the chat line colours (§3.10) and the drag icon tint (§4) are four floats
   passed to `nUi`; that they are r, g, b, a is [inferred] from the layouts' `color="1 1 1 1"` and from red
   being the plausible "cannot drop" tint. Settle: the consumer in `nUi::Shape::DrawAtNaturalSize` /
   `nUi::ChatSystem::AddText` ([ui-toolkit.md](ui-toolkit.md)).
9. **Mouse look units**: what the camera does with the values of `GetMouseLookYaw` / `GetMouseLookPitch`
   (§3.18) is in [lobby-world-client.md](lobby-world-client.md); when the accumulators are reset was not
   read here.

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 0042a490 | `LobbyMenu::System::CreateInstance` | singleton creation |
| S 0042ad80 | `System::Initialize` | screens, desktops, `itemicons.txt` |
| S 0042a860 | `System::Update` | per-frame UI tick (§4) |
| S 0042a650 | `System::Render` | per-frame draw |
| S 00429900 | `System::RequestScreen` | deferred screen request |
| S 00429ab0 | `System::SwitchToRequestedScreen` | the switch |
| S 0042a1c0 / 0042a6b0 | `System::UpdateDialogs` / `UpdateMessageBoxes` | sweep and update |
| S 00429de0 / 00429f00 | `System::CloseDialogs` / `CloseMessageBoxes` | bulk close |
| S 0042a020 | `System::DispatchButtonClicks` | click routing, modality |
| S 0042c390 / 0042c730 / 0042ca30 | `System::ShowMessageBox` / `…WithCallback` / `…WithCallbackAndTag` | modal boxes |
| S 0042af70..0042c660 | `System::Open…Dialog` | dialog factories (§2.2) |
| S 00429b60 / 00429950 | `System::OnDragSourcePressed` / `OnDragSourceReleased` | drag start and end |
| S 0042d320 / 0042dda0 / 0042e140 / 0042df80 | `UiDragState` update / `CanDropAt` / `EndDrag` / render | drag and drop |
| S 0045f420 / 0045f520 | `ScreenBase::ctor` / `ctor_ExplicitParent` | base state |
| S 0045f180 / 0045f380 / 0045f710 | `ScreenBase::BuildWidgets` / `OnShow` / `OnLeave` | base behaviour |
| S 00460590 | `DialogBase::ctor` | frame, title, close button |
| S 004611a0 / 00460f50 / 004612d0 | `DialogBase::BuildWidgets` / `OnShow` / `Leave` | common dialog behaviour |
| S 004608d0 | `DialogBase::HandleButtonClicks` | close button rule |
| S 00460be0 | `DialogBase::SetAnchoredPosition` | positioning |
| S 00460790 | `DialogBase` slot 31 (`Close`) | close request |
| S 0045e3a0 / 0045e800 / 0045ebe0 | `MessageBoxDialog::BuildWidgets` / `OnShow` / `HandleButtonClicks` | button sets, size, results |
| S 0043bf10 | `AccountScreen::Activate` | base `Activate`, then opens the login dialog if `previousScreen` (`System+0x10`) is 2 or 3 |
| S 0043d150 / 0043cbf0 | `LoginDialog::OnShow` / `HandleButtonClicks` | prefill, login |
| S 0043c1a0 / 0043c890 / 0043ca60 / 0043c790 | `LoginDialog` success / failed / version failed / box result | login results |
| S 0043e080 / 0043dd10 | `CreateAccountDialog::HandleButtonClicks` / `ValidateInput` | account creation |
| S 0043d960 / 0043db90 / 0043d490 | `CreateAccountDialog` created / failed / box result | results |
| S 0043eda0 / 0043ed60 | `MotDDialog::RefreshMessage` / `HandleButtonClicks` | MOTD |
| S 0043be30 / 0043b3a0 / 0043a630 | `AvatarScreen::Activate` / `OnShow` / `SetViewMode` | avatar screen modes |
| S 00439f30 / 0043bd50 | `AvatarScreen::Update` / `HandleButtonClicks` | button gating, clicks |
| S 0043b4d0 / 00439d20 | `AvatarScreen::OnCreateAvatarClicked` / name check | character creation |
| S 0043abc0 | `AvatarScreen::OnStartGameClicked_EnterVillage` | enter village |
| S 0043afc0 / 0043b0a0 / 0043b1b0 / 0043ad90 | `AvatarScreen` created / failed / connection lost / box result | results |
| S 0043fa40 / 0043f770 / 0043f3e0 | `SelectAvatarDialog::Update` / `HandleButtonClicks` / delete confirmed | character list |
| S 0043e7f0 / 0043e500 | `CustomizeAvatarDialog::BuildWidgets` / `HandleButtonClicks` | look editor |
| S 0045e020 | `ConfirmTaylorDialog::HandleButtonClicks` | tailor confirm (3950) |
| S 00440d70 / 00440a50 / 00440690 | `SelectVillageServerDialog` show / entry changed / click | server picker |
| S 004351a0 / 00433d80 | `WorldScreen::Activate` / `Deactivate` | connection observers |
| S 004389d0 / 00439410 | `WorldScreen::OnShow` / `OnLeave` | channels, sub-dialogs |
| S 00438050 | `WorldScreen::BuildWidgets` | HUD widget binding |
| S 00435980 | `WorldScreen::Update` | HUD refresh, referee pump |
| S 00437760 | `WorldScreen::HandleButtonClicks` | main menu, buttons, chat keys |
| S 00433f60 / 004325b0 / 00434230 | `RefreshActionSlots` / `SetActionButton` / `DispatchSlotAction` | action codes |
| S 00436860 / 004354d0 | `WorldScreen::SendChatInput` / `LobbyChat_ParseSlashCommand` | chat sending |
| S 00436180 / 00432930 / 00437e20 | channel line / private line / chat line click | chat receiving |
| S 00436bc0 / 004375a0 | `LoadQuickEmotes` / `PopulateSelectServerMenu` | menus |
| S 004323d0 | `WorldScreen::OnShopInventoryReceived` | opens the shop |
| S 00433160 / 004320b0 | world drop receiver / delete-item confirm | 3002 |
| S 004316c0 / 00432ed0 | village logged out / disconnected | fall back to screen 2 |
| S 00431780 / 004317a0 / 00432240 / 00431800 / 00432fd0 | referee observers | match start |
| S 00431a00 / 00431ac0 | `EnterMiniGameMode` / `LeaveMiniGameMode` | minigame HUD mode |
| S 0045f760 / 0045fd30 | `Minimap::HandleZoomKeys` / `Update` | minimap |
| S 0044ed80 / 0044fe40 / 0044f9f0 / 0044f800 | `SelectionInfoDialog` build / `Update` / inventory panel / XP | inventory view |
| S 0044d690 / 0044d7f0 / 0044e0f0 / 0044d390 | `SelectionInfoDialog` can-drop / on-drop / double click / slot rule | item moves |
| S 0045d580 / 0045b790 / 0045bea0 / 0045c560 / 0045b920 | `ShopDialog` set shop / stock / hover / sell drop / close | shop |
| S 004509d0 / 00450e10 / 00450800 / 00451160 | `MailboxDialog` clicks / inbox / send result / reply | mailbox |
| S 0045ab40 / 0045a990 / 0045ad40 | `MailDialog::OpenMail` / `ShowMail` / `HandleButtonClicks` | mail |
| S 00452400 / 00452140 / 004518a0 / 004519b0 | `FriendIgnoreListDialog` clicks / button state / lists | friends, ignore |
| S 004427a0 / 00442230 / 004428f0 / 00442640 | `HallOfFameDialog` ctor / `Update` / clicks / URL | hall of fame |
| S 0045b320 / 0045b160 | `ReportIssueDialog` clicks / result | report issue |
| S 00441100 / 00441560 / 00441760 | `EnterPasswordDialog` clicks; `SetStackDialog` clicks / `Update` | password CRC, stake |
| S 0045dab0 / 0045deb0 | `SetPasswordDialog` / `GetPasswordDialog` clicks | game password |
| S 00428e10 | `LobbyAction::ctor` | village input object |
| S 00462280 | `ComponentBase::LoadFromXml` | component layouts with templates |
| S 004f5950 | `Lobby::CLobby::ProcessModeTransition` | which screen opens on entering the lobby |
| S 004fb230 / 004f9960 | `Lobby::CLobby::Tick` / `RenderFrame` | callers of `System::Update` / `Render` (§4) |
| S 0042a940 | `LobbyMenu_PreloadUiResources` | UI sounds and fonts (§4) |
| S 0042d0c0 | `UiDragState::BeginCarry` | state 3, click-to-carry |
| S 00428f30 | `LobbyAction::PollAsyncKeys` | `LobbyAction` vtbl+4, per-step key poll |
| S 00429030 / 00429080 | `LobbyAction::GetMouseLookYaw` / `GetMouseLookPitch` | mouse-look amounts (§3.18) |
| S 004f5070 / 004f5090 / 004f50c0 | `CLobby::RequestEnterVillage` / `RequestExitVillage` / `RequestReenterVillage` | CLobby vtbl+0x80 / +0x84 / +0x88 (§5) |
| S 004f51b0 / 004f50f0 | `CLobby::GetSelectionSnapshotTexture` / `GetLocalAvatar` | CLobby vtbl+0xa4 / +0x94 (§3.10) |
| S 00465380 / 00465450 / 00465960 | `LobbyClient_LoadProtocolVersion` / `LobbyProfile_GetLobbyServerPort` / `LobbyProfile::GetHallOfFameUrl` | `LobbySettings.ini` readers (§6) |
| S 00465530 / 00465620 / 00465220 | `LobbyProfile::SaveUserName` / `SaveCDKey` / `SetUserString` | the only profile writers (§7) |
