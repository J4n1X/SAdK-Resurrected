# Lobby menu screen/dialog vtables — `LobbyMenu::ScreenBase` family

Status: **static RE on `sadk_noav.exe`** (magazine build, base 0x400000), via the Ghidra MCP,
2026-06-17. RTTI is intact: ~41 `LobbyMenu::*` classes (`.?AV…@LobbyMenu@@`). All renames/structs
below are applied + saved in the Ghidra project. `[PROVEN static]` unless marked `[inferred]`.

This maps the screen/dialog UI framework the match-start logic lives in. The two screens that matter
for "Host + Join" are **`WorldScreen`** (the 3D village screen; holds the referee pump + the game-server
request arm) and **`SetupGameDialog`** (the host's match-setup dialog; shows the "Connecting to Game
Server" modal). Both derive from **`LobbyMenu::ScreenBase`** — see `MATCH_START_STATIC_RECONCILIATION.md`.

## Class hierarchy (RTTI-confirmed)
- `LobbyMenu::ScreenBase` (ctor `LobbyComm`-style `LobbyMenu_ScreenBase_ctor@0x45f420`, vftable **0x007da504**, 25 slots)
  - `LobbyMenu::WorldScreen` (ctor `LobbyMenu_WorldScreen_ctor`, vftable **0x007d6eac**, 25 slots)
  - `LobbyMenu::SetupGameDialog` (ctor `LobbyMenu_SetupGameDialog_ctor`, vftable **0x007d931c**, 38 slots — extends the base via a richer intermediate, see "Follow-ups")
- (~35 more sibling dialogs share slots 0–24: AvatarScreen, AccountScreen, DialogBase, LoginDialog,
  BrowseGameDialog, SelectMapDialog, … — all carry the same `0x45Fxxx` base methods at the shared slots.)

## `LobbyMenu::ScreenBase` vtable (25 slots @ 0x007da504) — base interface [PROVEN static]

| Slot | vtbl off | Base target | Role |
|---|---|---|---|
| 0 | +0x00 | `0x45F360` `..._Destructor` | scalar-deleting destructor |
| 1 | +0x04 | `0x45F180` `..._RouteInputToContainer` | routes input to the ScreenContainer child (`this+0x40`) |
| 2 | +0x08 | `0x45F270` `..._IsVisibleAndEnabled` | `GetFlag1e0() && +0x1e1` |
| 3 | +0x0c | `0x45F170` `..._SetFlag1e0` | set `+0x1e0 = 1` |
| 4 | +0x10 | `0x45F6F0` `..._OnHide` | clears `+0x1e0` |
| 5 | +0x14 | `0x45F380` `..._OnShow` | sets `+0x1e1 = 1` |
| 6 | +0x18 | `0x45F710` `..._OnLeave` | clears `+0x1e1` |
| 7 | +0x1c | `0x45F2E0` `..._GetFlag1e1` | get `+0x1e1` |
| 8 | +0x20 | `0x5657B0` `Stub_EmptyVoid_5657b0` | **Update** — base no-op; **subclasses override** |
| 9 | +0x24 | `0x45F2D0` `..._GetFlag1d8AsBool` | **HandleInput** — base trivial; WorldScreen→`OnLeaveVillage`, SetupGameDialog→`HandleButtonClicks` |
| 10 | +0x28 | `0x5657B0` (no-op) | vf28 |
| 11 | +0x2c | `0x45F1E0` `..._SetConnectingOverlayEnabled` | set `+0x1d9` |
| 12 | +0x30 | `0x45F200` `..._ClearConnectingOverlayEnabled` | clear `+0x1d9` |
| 13 | +0x34 | `0x45F220` `..._GetConnectingOverlayEnabled` | get `+0x1d9`; **SetupGameDialog overrides → `IsConnectingPhaseActive`** (panel-visible `&& +0x1d9`) |
| 14 | +0x38 | `0x45F230` `..._SetFlag1d8` | |
| 15 | +0x3c | `0x45F240` `..._ClearFlag1d8` | |
| 16 | +0x40 | `0x45F250` `..._GetFlag1d8` | |
| 17 | +0x44 | `0x45F260` `..._GetFlag1e0` | |
| 18 | +0x48 | `0x45F2A0` `..._GetField1dc` | |
| 19 | +0x4c | `0x45F2B0` `..._SetField1dc` | |
| 20 | +0x50 | `0x45F2C0` `..._GetField3c` | |
| 21 | +0x54 | `0x45F2C0` (dup) | |
| 22 | +0x58 | `0x48CFA0` `..._GetScreenContainer` | returns `this+0x40` |
| 23 | +0x5c | `0x48CFA0` (dup) | |
| 24 | +0x60 | `0x5657B0` (no-op) | vf60 |

### Typed structs created (Ghidra)
- **`LobbyMenu_ScreenBase_vftable`** (100 B, 25 members named by the roles above).
- **`LobbyMenu_ScreenBase`** (object; proven fields only, gaps left undefined): `+0x00 pVftable`
  (→ vftable struct), `+0x38 pOwner`, `+0x3c nId`, `+0x40 screenContainer` (embedded), `+0x1d8 flag1d8`,
  `+0x1d9 fConnectingOverlayEnabled`, `+0x1dc field1dc`, `+0x1e0 flag1e0`, `+0x1e1 flag1e1`.

## `LobbyMenu::WorldScreen` overrides (vtable 0x007d6eac, 25 slots) [PROVEN static]

| Slot | Target | Name |
|---|---|---|
| 0 | `0x435180` | `LobbyMenu_WorldScreen_ScalarDeletingDestructor` |
| 1 | `0x438050` | `LobbyMenu_WorldScreen_RouteInputAndBindWidgets` (caches ~20 child widgets into `this+0x3550..0x3610`) |
| 3 | `0x4351A0` | `LobbyGameScreen_SubscribeConnectionObservers` *(legacy prefix — see Follow-ups)* |
| 4 | `0x433D80` | `LobbyGameScreen_UnsubscribeConnectionObservers` *(legacy prefix)* |
| 5 | `0x4389D0` | `LobbyMenu_WorldScreen_OnShow` (subscribe NComm/UC/Village + build sub-controllers + welcome chat) |
| 6 | `0x439410` | `LobbyMenu_WorldScreen_OnLeave` (teardown mirror of OnShow) |
| 8 | `0x435980` | `LobbyMenu_WorldScreen_Update` (referee pump + `ArmGameServerRequest` + world activate) |
| 9 | `0x437760` | `LobbyVillageScreen__OnLeaveVillage` (input handler; the deferred AssignServer trigger) |
| 11/12 | `0x431E30`/`0x431E40` | thunks → ScreenBase Set/ClearConnectingOverlayEnabled |
| 24 | `0x4319F0` | `LobbyMenu_WorldScreen_Slot24_ForwardTo3588` |

(Slots 2,7,10,13–23 use the ScreenBase base targets.) Related, already-named:
`LobbyMenu_WorldScreen_ArmGameServerRequest@0x433f60`, `..._DispatchSlotAction@0x434230`.

## `LobbyMenu::SetupGameDialog` overrides/extensions (vtable 0x007d931c, 38 slots) [PROVEN static]

| Slot | Target | Name | Note |
|---|---|---|---|
| 0 | `0x453890` | `LobbyMenu_SetupGameDialog_Destructor` | |
| 1 | `0x456C70` | `LobbyMenu_SetupGameDialog_BuildWidgets` | builds Map/MaxPlayer/WinCondition/Ready/Leave/… widgets |
| 5 | `0x455F20` | `LobbyMenu_SetupGameDialog_OnShow` | |
| 6 | `0x455E70` | `LobbyMenu_SetupGameDialog_OnLeave` | releases child `+0xb80`, deregisters `+0xb8c` |
| 8 | `0x457A00` | `LobbyMenu_SetupGameDialog_Update` | the **"Connecting to Game Server" modal** gate (`+0x9c ∈ {-1,-2}`) |
| 9 | `0x457F00` | `LobbyMenu_SetupGameDialog_HandleButtonClicks` | Minimize/Ready/Leave latches |
| 11 | `0x452DD0` | `LobbyMenu_SetupGameDialog_SetConnectingOverlayEnabled` | **creates/destroys the "Connecting…" overlay object at `this+0xBB8`** |
| 12 | `0x452E20` | `LobbyMenu_SetupGameDialog_HideConnectingOverlay` | |
| 13 | `0x460850` | `LobbyMenu_SetupGameDialog_IsConnectingPhaseActive` | `panel->vtbl[0x2c]() && +0x1d9` |
| 14 | `0x460880` | (slot 14 forwarder) | |
| 22/23 | `0x4608A0` | `LobbyMenu_SetupGameDialog_GetScreenContainer` | returns `&this+0x1e8` |
| 24 | `0x455E60` | `LobbyMenu_SetupGameDialog_DetachSlotWidgetCallbacks` | **the 6 Player{Type,Tribe,Team,HQ,Color} slot widgets** — the room slot model |
| 36 | `0x452D90` | `LobbyVillageServerList_ShutdownNComm_Wrapper` | (slot 36, the teardown wrapper) |

Slots 25–35 (`0x460BE0/E90/AD0/ED0`, `0x4607F0/B00/90/B0/C0/D0/E0`) are small geometry/flag accessors
(SetChildPosition/Bounds/Rect, layout, init-flag `+0xb40`, flag `+0xb42`) currently carrying a
`SetupGameDialog_` prefix but **shared across ~30 vtables** — see Follow-ups.

## `LobbyComm_ServerList` (villageList, `LobbyManager+0x54`) — field map [PROVEN static, 2026-07-26]

> **⛔ The 2026-06-17 "correction" recorded here was itself wrong and has been reverted.** It renamed
> `+0x9c` → `nGameServerAssignState` and `+0xa0` → `pAssignCompleteCallback`; **the ORIGINAL names were
> right.** Root cause: `LobbyComm_ServerList_ctor@0x0046a160` installs **two** vtables — `0x7dafcc` at
> `[ServerList+0]` and `0x7daf8c` (`CommLayer::IGameServerObserver`) at `[ServerList+8]` — so every
> function in the `0x7daf8c` table runs on `this = ServerList+8` and **all its offsets are +8 shifted**.
> `GameServerAssigned`'s `this+0x9c`/`this+0xa0` are `ServerList+0xa4`/`+0xa8`, a different pair
> entirely. Proof: `CreateResultReceived` passes `(int)this + -8` as the observer subject.
> Full derivation: `decomp/RENAME_LIST.md`, 2026-07-26 (night, cont.).

Byte-exact from the ctor disassembly (`0046a27a`–`0046a2aa`):

| off | type | name | meaning |
|---|---|---|---|
| `+0x6c` | ptr | `pGameServerManager` | `vtbl[0x20]`=AddGameServer(168) · `vtbl[0x24]`=UpdateGameServer · `vtbl[0x28]`=DeleteGameServer · `vtbl[0x2c]`=AssignServer |
| `+0x94` | u32 | `nVillageServerId` | village-server slot, same sentinels |
| `+0x98`,`+0x99` | bool ×2 | | village-slot flags |
| `+0x9c` | u32 | **`nPendingCreateGameServerId`** | the hosted game's server id. `0xFFFFFFFF`=INVALID · `0xFFFFFFFE`=PENDING · anything else = the **real assigned id**. Gates the "Connecting to Game Server" modal (`Update@0x457A00` early-returns while `∈{-1,-2}`) |
| `+0xa0` | **bool** | **`fVillageLoginPending`** | a **BYTE**, not a pointer. Set `=1` in `LobbyVillageScreen::OnLeaveVillage@0x00437899` right after `SelectServerForRoom` |
| `+0xa4` | ptr | `pPendingRefereeCbCtx` | armed **only** by `LobbyServerList_RequestRefereeServer@0x00468f80` |
| `+0xa8` | fptr | `pPendingRefereeCbFn` | fired+cleared by `GameServerAssigned` — this is the **referee** completion |

**Complete writer set of `+0x9c` — five, no more** (scripted sweep of every `[reg+0x9c]` store):
`ctor`→INVALID · `LobbyServerList_CreateGameServer@0x0046aaa0`→PENDING ·
`CreateResultReceived@0x0046a6a0`→real id (err 0) / INVALID + `NComm_Shutdown` (err≠0) ·
`DeleteResultReceived@0x00469990`→INVALID · `DestroyGameServerAndShutdown@0x00468410`→INVALID +
`NComm_Shutdown`. There is **no unidentified sixth writer** and no need for a hardware watchpoint.

## Follow-ups (not done this session — flagged honestly, no guessing)
1. **`ComponentBase`/`DialogBase` reattribution.** SetupGameDialog vtable slots 25–35 target shared
   UI base methods (appear in ~30 vtables; geometry/flag accessors). They were named with a
   `LobbyMenu_SetupGameDialog_` prefix for now; reattribute to the correct base class once the
   `LobbyMenu::ComponentBase` (`0x0087ad7c`) / `DialogBase` vtable is mapped. The plate comments already
   note "shared across ~30 vtables."
2. **Legacy `LobbyGameScreen_` prefix.** A few WorldScreen methods (`0x4351A0`, `0x433D80`, and the
   `LobbyGameScreen_*` names in `MEMORY.md`) predate the RTTI class name `WorldScreen`; unify under
   `LobbyMenu_WorldScreen_` in a dedicated rename pass.
3. **`set_function_this_type` pass.** The `this`-typing of the ~90 named methods to the RTTI class
   structs (using the class-hygiene script in `RE_PRACTICES.md`) is deferred to avoid the duplicate-
   `GhidraClass` trap; do it as one careful pass per class.
