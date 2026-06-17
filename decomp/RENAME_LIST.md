# SADK.exe — proposed labels (apply in Ghidra)

> **⚠️ Predates the magazine-build re-map.** Every `FUN_<addr>` / `DAT_<addr>` below is an
> **old-build VA** (the no-CD/dump base); the clean 2014 magazine build shifted these addresses.
> The logic/struct-offsets still transfer, but for current addresses use **`docs/SOURCEMAP.md`** as
> the firmer reference. Treat this list as historical RE notes, not live addresses.

From tracing the greyed **"Suche Server…" / Enter-Village** button. Addresses are
virtual (the `FUN_<addr>` name). Confidence: **H** = string/file-name confirmed,
**M** = inferred from clear logic, **L** = plausible, verify before trusting.

## Functions

| Address | Proposed name | Conf | Evidence |
|---------|---------------|------|----------|
| `FUN_00439e80` | `LobbyVillageScreen::UpdateEnterButton` | H | Sets enter button to `!ENTER_VILLAGE_BUTTON` (live) or `!LOBBY_LOADING_SERVERS` (greyed); computes enabled state. |
| `FUN_0043a580` | `LobbyVillageScreen::RefreshView` (SetMode/tab) | M | Mutates mode field `+0x1e8` 18×, refreshes the 5 tab/button widgets + enter-button text. NOT the network enter action. |
| `FUN_0043ab10` | `LobbyVillageScreen::OnVillageConnectFailed` | H | Shows `!COULDNOT_CONNECT_TO_VILLAGE` / `!ERROR`; runs when server-list lookup for the selected room fails. |
| `FUN_00462bc0` | `LobbyManager::GetStateName` | H | switch over `this+0x57c` → `"LobbyManagerState: ..."` strings (the lobby state enum). |
| `FUN_00463750` | `LobbyManager::CreateVillageServerConnection` | H | Literal `LobbyComm::System::CreateVillageServerConnection`, from `LobbyManager.cpp`. Opens the village connection at `this+0x540`. |
| `FUN_00468d80` | `LobbyVillageServerList::FindByRoomId` | M | Searches the entry vector (`this+0x70..0x78`), matches `entry+0x30 == key`, returns index or -1. |
| `FUN_0046b250` | `LobbyManager::GetSelectedVillageServer` | L | Returns `*(this+0x80)` (the village server handle/id used as the default connect target). |
| `FUN_00472040` | `*::IsField98Set` (enable-cond #2) | L | Returns `*(this+0x98) != 0`; generic getter — confirm what `+0x1ec` object is. |
| `FUN_00437680` | `LobbyVillageScreen::OnLeaveVillage` | M | References `!LEAVE_VILLAGE` / `!LEAVE_VILLAGE_QUESTION`. |
| `thunk @ 0x4682d0` (`thunk_FUN_01375b50`) | `LobbyVillageServerList::IsListReady` (predicate) | L | The predicate that flips the button text (false → "Loading Servers"). **Unrecovered jump table** — see notes. |

## Globals

| Address | Proposed name | Conf | Evidence |
|---------|---------------|------|----------|
| `DAT_0087d580` | `g_SelectedVillageRoomId` | M | Compared against `serverEntry+0x30` in every list filter (38017, 44083/116, 44250/258); assigned at 41512, 42321. The selected room/LobbyId the village list is filtered by. |
| `DAT_012f161c` | `g_pVillageListReadyFn` (jumptable slot) | L | Indirect target called by `thunk_FUN_01375b50`. Only read, never written in the dump → set via the unrecovered jump table at `0x4682d0`. |

## Struct field offsets (set these as struct members in Ghidra)

**LobbyVillageScreen** (the `this` of `FUN_00439e80` / `FUN_0043ab10`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x1e8` | view mode / selected tab (int; enable needs `== 1`) | M |
| `+0x1ec` | ptr → sub-object, enable needs `*(it+0x98) != 0` | M |
| `+0x1f0` | ptr → `LobbyVillageServerList` | M |
| `+0x204..0x214` | UI widget ptrs (enter button + tab buttons) | M |
| `+0x218` | byte: idle/ready-to-connect (1 = idle; failure handler resets to 1) | L |
| `+0x21c` | byte: busy/guard (proceed only when `== 0`) | M |
| `+0x254` | (inside `+0x204`) the Enter-Village button widget | M |

**LobbyManager** (`this` of `FUN_00463750` / `GetStateName`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x50` | lobby comm / socket object | M |
| `+0x540` | village server connection object | H |
| `+0x57c` | state enum (see `LobbyManagerState` below) | H |
| `+0xd4` | selected village server handle/id (`*(+0x54 +0x80)`) | L |

**ServerListEntry** (elements of `LobbyVillageServerList`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x30` | RoomId / LobbyId (filtered against `g_SelectedVillageRoomId`) | M |
| `+0x34` | flag (checked `== 0` in some filters) | L |

## LobbyManagerState enum (value at `LobbyManager+0x57c`)

```
1 Disconnected   2 Authorizing   3 Authorized   4 CheckingVersion
5 VersionChecked 6 LoadingGlobalData 7 GlobalDataLoaded
8 EnteringVillage 9 VillageEntered 10 LeavingVillage 11 VillageLeft
12 ConnectionLost
```

## Live-confirmed in Ghidra (s4) — already applied + saved

| Address | Name / type | Note |
|---------|-------------|------|
| `004626f0` | `LobbyManager::GetState` | `return this->state` (+0x57c). |
| `00462700` | `LobbyManager::SetState` | `if(state==12) return; state=arg` — latches on ConnectionLost. |
| `00503da0` | (EnterVillage action) | sole caller of `CreateVillageServerConnection`; passes -1 → uses selected server. |
| `00468140` | `LobbyVillageServerList::HasServerSelected` | `selected(+0x80) != -1`. |
| `007dc51c` (data) | `g_dwInvalidVillageServerId` | the -1 "no selection" sentinel. |
| enum | `LobbyManagerState` | created, 12 values. |
| struct | `LobbyManager` (0x580) | fields pComm+0x50, selectedVillageServer+0xd4, pVillageConnection+0x540, state+0x57c. |
| struct | `LobbyVillageScreen` (0x21d) | viewMode+0x1e8, pField98Owner+0x1ec, pServerList+0x1f0, pButtonContainer+0x204, pWidget1-4, idleFlag+0x218, busyGuard+0x21c. |

Login-sequence state writers (set literals 1→7): `FUN_00462fe0` `004632f0` `00463910`
`00464b90` `00464c00` (+ readers `00464910` `00470f10`). `EnteringVillage(8)` is set via
`SetState(8)` (no inline constant) — caller still TBD.

## Connection classes (s9) — applied + saved in Ghidra

The lobby uses 5 `LobbyBaseConnection` subclasses (Connect@0x48d730 shared). Names below are
applied in the project.

| Address | Name | Conf |
|---------|------|------|
| `0x48d730` | `LobbyBaseConnection::Connect` (→ comm `vtable[0x1c]`(port,ip,x)) | H |
| `0x48d8b0` / `0x48d9d0` / `0x48dc20` | `LobbyBaseConnection::On{LoggedIn,LoginFailed,Disconnected}` | H |
| `0x47ed90` | `UserCommConnection::Initialize` (chat/UC conn = LobbyUserCommConnection.cpp) | H |
| `0x47fb40` | `UserCommConnection::OpenCommunication` (opens UC via comm `vtable[0x10]`(handle)) | H |
| `0x47fca0` | `UserCommConnection::JoinChannel` | H |
| `0x47ef50/0x47f040/0x47f130/0x47f220/0x47f310/0x47f400` | `UserCommConnection::On{LoggedIn,LoginFailed,LoggedOut,Disconnected,ReceivedData,ChatChannelListReceived}` | H |
| `0x48e650` | `GameServerConnection::OnLoggedIn` (LobbyGameServerConnection.cpp) | H |
| `0x462fe0` | `LobbyManager::Login` | H |
| `0x463910` | `LobbyManager::OnLoggedIn` (sets chatServerHandle +0x548 = login param_2) | H |
| `0x464740` | `LobbyManager::OnLoginFailed` | H |
| `0x4626c0` | `LobbyManager_GetChatServerHandle` (returns +0x548) | H |

vtables: UserComm `0x7dded8`, GameServer `0x7dfafc`, Village `0x7dc8e0`. `LobbyManager+0x548`
= chat-server handle (set at login).

## Notes / next in Ghidra

- **Recover the jump table at `0x4682d0`** (the `thunk_FUN_01375b50` body — Ghidra warned
  "Could not recover jumptable. Too many branches"). Once recovered, `g_pVillageListReadyFn`
  resolves and confirms the "list ready" predicate. This is the cleanest way to verify the
  text gate.
- The actual button **click → enter** wiring (button widget → `CreateVillageServerConnection`)
  wasn't traced; start from the widget at `LobbyVillageScreen+0x254` / the input handler.

## Match-start screens & game-server-request chain (2026-06-17) — applied + saved in Ghidra

Static RE on `sadk_noav.exe` via the Ghidra MCP. Full write-up + corrections:
`docs/MATCH_START_STATIC_RECONCILIATION.md`. All `[PROVEN static]`.

| Address | Name | Note |
|---------|------|------|
| `0x408290` | `NComm_GetManager` | returns the NComm manager singleton (`DAT_00885754`). |
| `0x408430` | `NComm_Manager_GetState` | returns `mgr+0x1c` = EManagerState (0 None / 1 Started / 2 Connected). |
| `0x4890b0` | `NComm_Manager_GetMode` | returns `mgr+0x3c8` = transport mode (compared to 4 = match host). |
| `0x46b610` | `LobbyManager_GetVillageServerList` | returns `LM+0x54` (the `LobbyVillageServerList`). |
| `0x408d80` | `NComm_SendPlayerReadyEvent` | sends NComm `Event1Integer 0x30011`; requires EManagerState==2. ReadyButton target. |
| `0x457a00` | `LobbyMenu_SetupGameDialog_Update` | vtable `0x7d931c` slot 8. Owns the "Connecting to Game Server" modal early-return (gate = `+0x9c ∈ {-1,-2}`). |
| `0x457f00` | `LobbyMenu_SetupGameDialog_HandleButtonClicks` | slot 9 (vtbl+0x24). Minimize/Ready/Leave click latches. |
| `0x456c70` | `LobbyMenu_SetupGameDialog_BuildWidgets` | slot 1. Buttons: `[0x2dd]`=MinimizeButton, `[0x2de]`=LeaveButton, `[0x2df]`=ReadyButton. |
| `0x460850` | `LobbyMenu_SetupGameDialog_IsConnectingPhaseActive` | slot 13 (vtbl+0x34). `panel->vtbl[0x2c]() && this+0x1d9`(ctor default). |
| `0x460800` | `LobbyMenu_ScreenBase_SetConnectingVisible` | sets `this+0x1d9` + panel `vtbl+0x24`. |
| `0x45f420` | `LobbyMenu_ScreenBase_ctor` | sets `*this=ScreenBase::vftable`, `+0x1d9=1` default. |
| `0x45f520` | `LobbyMenu_ScreenBase_ctor_variant` | variant ctor (same field init). |
| `0x435980` | `LobbyMenu_WorldScreen_Update` | vtable `0x7d6eac` slot 8 (WAS mislabelled `LobbyGameScreen_Update`). Referee pump + arm + world-screen activate. |
| `0x433f60` | `LobbyMenu_WorldScreen_ArmGameServerRequest` | iff EManagerState==0 → slot-action=8 + deferred flag `[0xd8e]`. |
| `0x434230` | `LobbyMenu_WorldScreen_DispatchSlotAction` | `switch(this+0x356c[slot]-2)`; case6 (code==8) → AssignServer `FUN_0046aaa0`. |
| `0x468410` | `LobbyVillageServerList_ShutdownNCommIfNotMatchHost` | gate `EManagerState!=0 && mode!=4` → Shutdown + `+0x9c=-1`. Reached only via LeaveButton or slot-36 wrapper. |
| `0x452d90` | `LobbyVillageServerList_ShutdownNComm_Wrapper` | SetupGameDialog vtbl slot 36 (vtbl+0x90); pure virtual dispatch (no static caller). |

Plate comments added in Ghidra for `0x457a00 0x457f00 0x460850 0x433f60 0x434230 0x468410`.

## ScreenBase screen/dialog vtable family (2026-06-17) — applied + saved in Ghidra

Static RE on `sadk_noav.exe`. Full slot tables + structs: `docs/LOBBY_SCREEN_VTABLES.md`.
RTTI-confirmed classes `LobbyMenu::{ScreenBase,WorldScreen,SetupGameDialog}`. `[PROVEN static]`.

**Structs created:** `LobbyMenu_ScreenBase_vftable` (25 fn-ptr slots, role-named) ·
`LobbyMenu_ScreenBase` (object; proven fields only).
**Struct corrected (mislabels fixed, layout byte-preserved):** `LobbyComm_ServerList`
`+0x9c` `nPendingCreateGameServerId`→`nGameServerAssignState` (int; modal gate −1/−2/0);
`+0xa0` `fVillageLoginPending`(bool)→`pAssignCompleteCallback`(void*, the fn-ptr GameServerAssigned fires).

**ScreenBase base methods (vftable 0x7da504):**
`0x45f360` Destructor · `0x45f180` RouteInputToContainer · `0x45f270` IsVisibleAndEnabled ·
`0x45f170` SetFlag1e0 · `0x45f6f0` OnHide · `0x45f380` OnShow · `0x45f710` OnLeave ·
`0x45f2e0` GetFlag1e1 · `0x45f2d0` GetFlag1d8AsBool · `0x45f1e0` SetConnectingOverlayEnabled ·
`0x45f200` ClearConnectingOverlayEnabled · `0x45f220` GetConnectingOverlayEnabled ·
`0x45f230` SetFlag1d8 · `0x45f240` ClearFlag1d8 · `0x45f250` GetFlag1d8 · `0x45f260` GetFlag1e0 ·
`0x45f2a0` GetField1dc · `0x45f2b0` SetField1dc · `0x45f2c0` GetField3c · `0x48cfa0` GetScreenContainer
(all prefixed `LobbyMenu_ScreenBase_`). `0x5657b0` `Stub_EmptyVoid_5657b0` (shared no-op).
`0x46a160` `LobbyComm_ServerList_ctor`.

**WorldScreen overrides:** `0x435180` ScalarDeletingDestructor · `0x438050` RouteInputAndBindWidgets ·
`0x4389d0` OnShow · `0x439410` OnLeave · `0x4319f0` Slot24_ForwardTo3588 (prefix `LobbyMenu_WorldScreen_`).

**SetupGameDialog overrides/extended (prefix `LobbyMenu_SetupGameDialog_`):** `0x453890` Destructor ·
`0x455f20` OnShow · `0x455e70` OnLeave · `0x43bf40` OnHide · `0x452dd0` SetConnectingOverlayEnabled
(creates/destroys the "Connecting…" overlay @this+0xBB8) · `0x452e20` HideConnectingOverlay ·
`0x4608a0` GetScreenContainer · `0x455e60` DetachSlotWidgetCallbacks (the 6 Player{Type,Tribe,Team,HQ,Color}
slot widgets) · `0x460960` DisableContainer · `0x460980` IsInteractive · plus geometry/flag accessors
`0x460be0/0x460e90/0x460ad0/0x460ed0/0x4607f0/0x460b00` (SetChildPosition/Bounds/Rect/Layout) and
`0x460790/0x4607b0/0x4607c0/0x4607d0/0x4607e0` (init flag +0xb40, flag +0xb42).

**Plate comments** added on `0x457a00 0x457f00 0x460850 0x433f60 0x434230 0x468410 0x46a160` + the
WorldScreen/SetupGameDialog override targets.

**Known follow-ups (see doc):** (1) slots 25–35 targets are shared base-widget helpers (~30 vtables) —
reattribute to `ComponentBase`/`DialogBase`; (2) unify legacy `LobbyGameScreen_*` → `LobbyMenu_WorldScreen_*`;
(3) `set_function_this_type` hygiene pass per class (deferred to avoid duplicate-GhidraClass trap).

## NComm network layer (2026-06-17) — applied + saved in Ghidra

Static RE on `sadk_noav.exe`. Full map: `docs/NCOMM_LAYER.md`. RTTI namespace `NComm`. `[PROVEN static]`.
~120 functions named across Manager + transports + events (all plate-commented in the project).

**Enums:** `EManagerState` {None=0,NetworkStarted=1,Connected=2} · `NE_EventType`
{UserInformation=0x30001, PlayerInformation=0x30002, GameInformation=0x30003, GameLoaded=0x30004,
StartGame=0x30005, UserChecksum=0x30009, UserLeave=0x3000a, UserReJoinGame=0x3000e, PlayerReady=0x30011,
StartLoading=0x30012}.
**Structs:** `NComm_Manager` (973B; +0x1c eManagerState, +0x340 pNetwork, +0x3c8 nMode, +0x3cc fStartLoading,
+0xdc 6-slot player table) · `NComm_INetworkHandler` + `NComm_INetworkHandler_vftable` (44 slots) ·
`NComm_Event` (+0 vtable, +4 nTypeId:NE_EventType, +8 nSourceNetId, +0xc nPlayerId).

**Manager (Manager.cpp):** `0x408290` GetManager · `0x408430` GetState · `0x4890b0` GetMode ·
`0x40a9a0` StartUpNetwork · `0x40ad60` ConnectAndJoin · `0x40b410` Shutdown · `0x408b60` SendEvent ·
`0x40fd50` DispatchEventLocal · `0x408d80` SendPlayerReadyEvent · `0x40e560` Manager_HandleNCommEvent.

**Transport vtable (NComm_INetworkHandler, impl = TinCatNetwork @vftable 0x7d58f4, 44 slots):**
slot0 dtor · 1 StartUp · 2 ShutDown · 3 Process · 4 ConnectToServer · 5 Disconnect · 6 Broadcast ·
7 SendToHost · 8 SendTo · 9 SendToAllExcept · 10 CloseSession · 11 KickPlayer · 12 GetLocalNetId ·
13 GetUserCount · 14 IsHost · 15 IsConnected · 16 GetBroadcastNetId · 18 GetUserNetIdByIndex ·
19 HasUser · 20 SetUserData · 21 GetUserName · 22 GetUserGUID · 23 GetUserLevel · 24 GetMinUserLevel ·
25 RemoveUser · 26 IsActive · 27-31 BC_Start/Update/Stop/IsActive/GetGameInfo (LAN "S2TNG_BC") ·
38 StartReconnector · 40 GetNetworkName · 41 LoadNetworkConfig · 42 ProcessReceive
(prefix `NComm_TinCatNetwork_`). TinCatNetwork 2nd vtable = `NComm::ITinCatCallback` @0x7d58ac (16 slots,
`NComm_TinCatNetwork_cb_*`; `cb_Received_Data@0x41d720` = inbound dispatcher, TinCat type 0x27d9).
DummyNetwork (loopback) @0x7d5a6c: ctor `NComm_DummyNetwork_ctor@0x41ed20` + StartUp/SendStub/GetNetId.
TinCatReconnector @0x7d5290 (host migration). Net-id magics: 0xEFFFFFCC bcast / 0xEFFFFFDD host /
0xEFFFFFEE none.

**Events (NComm::*; ctors + Serialize/Deserialize/GetClassSignature/dtor each):** factory
`NComm_Event_CreateFromStream@0x420540` switches on the per-class wire signature (vftable[5]); the inner
NE_ opcode is `Event+4` (`NComm_Event_GetType@0x4901e0`). Full class→signature→ctor table in the doc.
Primitives: `NComm_MemoryStream_{Write,Read,WriteString}`, `NComm_EventBase_Serialize@0x4085a0`,
`NComm_{MD5Digest,NetGUID,PlayerInfo}_{Serialize,Deserialize}`.

Follow-ups: this-typing pass per NComm class; model the Manager+0xdc 6-slot player table (room model).
