# Lobby menu screen/dialog vtables — `LobbyMenu::ScreenBase` family

Static reference for `sadk_noav.exe` (image base 0x400000). RTTI is intact: about 41 `LobbyMenu::*`
classes (`.?AV…@LobbyMenu@@`). Vtable contents and slot targets are `[known]` (read from the binary); the
slot names carry the confidence of the Ghidra vtable structs (`[inferred]` unless a row says otherwise).

This maps the screen/dialog UI framework the match-start logic lives in. The two classes that matter
for "Host + Join" are **`WorldScreen`** (the 3D village screen; holds the referee pump and the
game-server request) and **`SetupGameDialog`** (the host's match-setup dialog; shows the "Connecting to
Game Server" modal).

## Class hierarchy (RTTI)
- `nUi::XMLHandler` (+0..+0x1f) → `LobbyMenu::ScreenBase` (ctor `0x45f420`, ctor with an explicit parent
  `0x45f520`, vftable **0x007da504**, 25 slots, struct `/LobbyMenu/ScreenBase` 0x1e8)
  - `LobbyMenu::WorldScreen` (vftable **0x007d6eac**, 25 slots; its `NComm::IMessageCallbacks` part is at
    `+0x1e8`, table `0x007d6e98`, 3 slots; its `LobbyMenu::IDropReceiver` part at `+0x1ec`, table `0x007d6e7c`)
  - `LobbyMenu::AvatarScreen` (vftable **0x007d72fc**, struct 0x220; character select / enter-village
    screen; called LobbyVillageScreen in older notes)
  - `LobbyMenu::AccountScreen`, `LobbyMenu::EmptyScreen` (`0x007d7604`, identical to the base except slot 0)
  - `LobbyMenu::DialogBase` (vftable **0x007da62c**, 38 slots = the 25 of ScreenBase plus 13 dialog
    slots; struct 0xb48)
    - `LobbyMenu::SetupGameDialog` (vftable **0x007d931c**, 38 slots), `LoginDialog`, `BrowseGameDialog`,
      `SelectMapDialog`, `SetStackDialog`, `MailboxDialog`, … (every dialog)

## `LobbyMenu::ScreenBase` vtable (25 slots @ 0x007da504)

Struct `/LobbyMenu/ScreenBase_vftable` (100 bytes, one typed function pointer per slot).

| Slot | vtbl off | Base target | Name | Role |
|---|---|---|---|---|
| 0 | +0x00 | `0x45F360` | `scalar_deleting_dtor` | |
| 1 | +0x04 | `0x45F180` | `BuildWidgets` | calls slot 24, then builds the widgets into the screen container (`this+0x40`) |
| 2 | +0x08 | `0x45F270` | `IsActiveAndShown` | `active` (`+0x1e0`) and `shown` (`+0x1e1`) |
| 3 | +0x0c | `0x45F170` | `Activate` | sets `active` |
| 4 | +0x10 | `0x45F6F0` | `Deactivate` | clears `active`, fires `deactivateObservers` (`+0x20`) |
| 5 | +0x14 | `0x45F380` | `OnShow` | sets `shown`, attaches the screen container to `parentNode` |
| 6 | +0x18 | `0x45F710` | `OnLeave` | clears `shown`, fires `leaveObservers` (`+0x2c`) |
| 7 | +0x1c | `0x45F2E0` | `IsShown` | |
| 8 | +0x20 | `0x5657B0` (empty) | `Update` | base empty; subclasses override |
| 9 | +0x24 | `0x45F2D0` | `HandleButtonClicks` | base returns `inputEnabled`; WorldScreen → `0x437760`, SetupGameDialog → `0x457F00` |
| 10 | +0x28 | `0x5657B0` (empty) | `slot10_Stub` | `[TODO]` no override with a body found |
| 11 | +0x2c | `0x45F1E0` | `SetVisible(bool)` | stores `visible` (`+0x1d9`) |
| 12 | +0x30 | `0x45F200` | `Hide` | clears `visible` |
| 13 | +0x34 | `0x45F220` | `IsVisible` | |
| 14 | +0x38 | `0x45F230` | `SetInputEnabled(bool)` | stores `inputEnabled` (`+0x1d8`) |
| 15 | +0x3c | `0x45F240` | `DisableInput` | |
| 16 | +0x40 | `0x45F250` | `IsInputEnabled` | |
| 17 | +0x44 | `0x45F260` | `IsActive` | |
| 18 | +0x48 | `0x45F2A0` | `GetTag` | returns the caller-assigned `tag` (`+0x1dc`) `[known]` |
| 19 | +0x4c | `0x45F2B0` | `SetTag` | stores `tag` (`+0x1dc`) `[known]` |
| 20 / 21 | +0x50 / +0x54 | `0x45F2C0` | `GetParentNode` | returns `parentNode` (`+0x3c`); both slots hold the same body |
| 22 / 23 | +0x58 / +0x5c | `0x48CFA0` | `GetScreenContainer` | returns `this+0x40`. The body is a folded getter (`Generic_GetAddr_40`); `DialogBase` overrides both with `0x4608A0` (returns the frame, `this+0x1e8`) |
| 24 | +0x60 | `0x5657B0` (empty) | `PreBuildWidgets` | hook that `BuildWidgets` calls before it rebuilds (name `[guess]`) |

### `LobbyMenu::ScreenBase` fields (`/LobbyMenu/ScreenBase`, 0x1e8)
`+0x00 vftable` · `+0x04 fileName` (std::string, the `nUi::XMLHandler` member: the layout file name) ·
`+0x20 deactivateObservers` · `+0x2c leaveObservers` (std::list each) · `+0x38 owner`
(`LobbyMenu::System*`) · `+0x3c parentNode` · `+0x40 screenContainer` (embedded `nUi::Object`, 0x198) ·
`+0x1d8 inputEnabled` · `+0x1d9 visible` · `+0x1dc tag` (caller-assigned: dialog kind, message-box id,
backpack index of a sell confirmation) · `+0x1e0 active` · `+0x1e1 shown`.

## `LobbyMenu::WorldScreen` overrides (vtable 0x007d6eac, 25 slots)

| Slot | Target | Name |
|---|---|---|
| 0 | `0x435180` | `scalar_deleting_dtor` |
| 1 | `0x438050` | `BuildWidgets` (binds about 20 child widgets into `this+0x3550..0x3610`) |
| 3 | `0x4351A0` | `Activate` (subscribes the village / referee connection observers) |
| 4 | `0x433D80` | `Deactivate` (unsubscribes them) |
| 5 | `0x4389D0` | `OnShow` (subscribes NComm / UC / village, builds the cached dialogs, welcome chat) |
| 6 | `0x439410` | `OnLeave` (teardown mirror of `OnShow`) |
| 8 | `0x435980` | `Update` (referee pump, world activation) |
| 9 | `0x437760` | `HandleButtonClicks`: per-frame click dispatcher. MainMenu item 0 "host game" calls `ServerList::CreateGameServer` (call at `0x437899`); the SelectServerMenu calls `ServerList::SelectVillageServer` and sets `ServerList+0xa0`; item 5 opens the leave-village confirmation |
| 11 / 12 | `0x431E30` / `0x431E40` | `SetVisible` / `Hide` overrides |
| 24 | `0x4319F0` | `PreBuildWidgets` |

Slots 2, 7, 10 and 13–23 hold the ScreenBase targets. Related: `WorldScreen::RefreshActionSlots`
`0x433f60`, `WorldScreen::DispatchSlotAction` `0x434230`.

## `LobbyMenu::DialogBase` slots 25–37 (vtable 0x007da62c)

Slots 0–24 follow ScreenBase. Slots 25–37 are `LobbyMenu::DialogBase` methods inherited by every dialog:

| Slot | vtbl off | Target | Name | Role |
|---|---|---|---|---|
| 25 | +0x64 | `0x460BE0` | `SetAnchoredPosition` | (h, v, offX, offY) |
| 26 | +0x68 | `0x460E90` | `SetPosition` | |
| 27 | +0x6c | `0x460AD0` | `GetFrameBounds` | |
| 28 | +0x70 | `0x460ED0` | `SetRect` | |
| 29 | +0x74 | `0x4607F0` | `BringToFront` | `nUi::Object::BringToFront` on the frame (`+0x1e8`) `[known]` |
| 30 | +0x78 | `0x460B00` | `IsCursorOverFrame` | hit-tests the cursor against the frame rectangle |
| 31 | +0x7c | `0x460790` | `Close` | calls slot 37 once, then sets `closeRequested` (`+0xb40`); `System::UpdateDialogs` `0x42a1c0` deletes the dialog once it is set |
| 32 | +0x80 | `0x4607B0` | `IsCloseRequested` | returns `closeRequested` `[known]` |
| 33 / 34 / 35 | +0x84 / +0x88 / +0x8c | `0x4607C0` / `0x4607D0` / `0x4607E0` | `SetAutoClose(bool)` / `ClearAutoClose` / `GetAutoClose` | `autoClose` (`+0xb42`, ctor 1); `System::CloseDialogs` `0x429de0` closes a dialog only when it is set or forced `[known]` |
| 36 | +0x90 | `0x41ECC0` (returns 0) | `OnCancel` | called by the close button before `Close` (name `[guess]`) |
| 37 | +0x94 | `0x5657B0` (empty) | `OnClose` | hook that `Close` calls once; `MailboxDialog` overrides it with `0x450170` |

DialogBase also overrides slots 14 / 15 / 16 (`SetInputEnabled` `0x460880`, `DisableInput` `0x460960`,
`IsInputEnabled` `0x460980`) and slot 13 (`IsVisible` `0x460850`).

## `LobbyMenu::SetupGameDialog` overrides (vtable 0x007d931c, 38 slots)

| Slot | Target | Name | Note |
|---|---|---|---|
| 0 | `0x453890` | `scalar_deleting_dtor` | |
| 1 | `0x456C70` | `BuildWidgets` | builds Map/MaxPlayer/WinCondition/Ready/Leave/… widgets |
| 5 | `0x455F20` | `OnShow` | |
| 6 | `0x455E70` | `OnLeave` | releases child `+0xb80`, deregisters `+0xb8c` |
| 8 | `0x457A00` | `Update` | the **"Connecting to Game Server" modal** gate (`ServerList+0x9c ∈ {-1,-2}`) |
| 9 | `0x457F00` | `HandleButtonClicks` | Minimize/Ready/Leave latches |
| 11 | `0x452DD0` | `SetConnectingOverlayEnabled` (override of `SetVisible`) | creates/destroys the "Connecting…" overlay object at `this+0xBB8` |
| 12 | `0x452E20` | override of `Hide` | |
| 24 | `0x455E60` | override of `PreBuildWidgets` | a jump to `UnbindPlayerRowWidgets` `0x455800`: the six player rows (Type, Tribe, Team, HQ, Color), the room slot model |
| 36 | `0x452D90` | `OnCancel` | |

The other slots hold the DialogBase targets.

## `LobbyComm::ServerList` (`LobbyComm::System+0x54`) — field map

The object the documents call the village list holds the village servers and the game servers. The ctor
`0x0046a160` installs two vtables: `0x7dafcc` at `[ServerList+0]` and `0x7daf8c`
(`CommLayer::IGameServerObserver`, 15 slots) at `[ServerList+8]`. Every function of the `0x7daf8c` table
runs with ECX = `ServerList+8`; in Ghidra its `this` is the offset pointer
`ServerList * __((offset(0x8))) this`, so the decompile shows the fields below under their names. In the
listing an operand `[ECX+N]` of such a function is `ServerList+N+8`: `GameServerAssigned`'s `[ECX+0x9c]` /
`[ECX+0xa0]` are `refereeCbContext` / `refereeCbFn`, not `gameServerId` / `bSelectionLocked`.

From the ctor disassembly (`0046a27a`–`0046a2aa`) `[known]`:

| off | type | name | meaning |
|---|---|---|---|
| `+0x6c` | ptr | `pGameServerManager` | tincat3 `CommLayer::GameServerManager`: `vtbl[0x20]`=AddGameServer(168) · `vtbl[0x24]`=UpdateGameServer · `vtbl[0x28]`=DeleteGameServer · `vtbl[0x2c]`=AssignServer |
| `+0x80` | u32 | `selectedVillageServerId` | -1 = none; set by `SelectVillageServer` `0x468380` |
| `+0x94` | u32 | `selectedGameServerId` | ctor -1; `RemoveServer` `0x46a5e0` resets it to -1 when the removed game id matches `[inferred]` |
| `+0x98`, `+0x99` | byte ×2 | `unk98`, `unk99` | set to 0 by the ctor and touched by nothing else: unused in this build |
| `+0x9c` | u32 | **`gameServerId`** | the hosted game's server id. `0xFFFFFFFF`=INVALID · `0xFFFFFFFE`=PENDING · anything else = the **real assigned id**. Gates the "Connecting to Game Server" modal (`SetupGameDialog::Update` `0x457A00` early-returns while `∈{-1,-2}`) |
| `+0xa0` | byte | **`bSelectionLocked`** | a byte, not a pointer. Set to 1 by `WorldScreen::HandleButtonClicks` `0x437760` right after `SelectVillageServer` (village-server switch) and by `SelectVillageServerDialog::HandleButtonClicks` `0x440690`; cleared by `LobbyComm::System::OnLoggedIn` `0x463a10` when the village connection logs in. While set, `Reset` `0x468c50` does nothing and `StartObservation` `0x468e80` sends nothing |
| `+0xa4` | ptr | `refereeCbContext` | armed only by `ServerList::RequestRefereeServer` `0x468f60` |
| `+0xa8` | fptr | `refereeCbFn` | called with the assigned server id and cleared by `GameServerAssigned` `0x469ad0`: this is the **referee** completion |

**Complete writer set of `+0x9c`: five** (every `[reg+0x9c]` store):
`ctor`→INVALID · `ServerList::CreateGameServer` `0x0046aaa0`→PENDING ·
`CreateResultReceived` `0x0046a6a0`→real id (err 0) / INVALID + `NComm_Shutdown` (err≠0) ·
`DeleteResultReceived` `0x00469990`→INVALID · `DestroyGameServerAndShutdown` `0x00468410`→INVALID +
`NComm_Shutdown`.
