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

## Renames applied 2026-07-25 (`sadk_noav.exe`) — match-start mislabel corrections

Both of these were **wrong names that actively misdirected the match-start analysis** for several
sessions. Verified this session via the Ghidra MCP before renaming; details in the plate comments.

| Addr (noav) | Old name | New name | Evidence |
|---|---|---|---|
| `0x0046bde0` | `LobbyManager_SendWorldLoginReq_2002` | `VillageServerConnection_SendLeaveVillageRequest_2002` | Decompile: builds `LobbyMessage(cat=2, 0x7d2=2002){code=0xAFFEDEAD}` then `SetState(LeavingVillage=10)`. It is a **leave** request, not a world-login. Live vtable slot `+0x40` (base `0x007db8d4`; slot `0x007db914` read = this fn) — the old *"DORMANT (no analyzed caller)"* plate comment was false. |
| `0x004316c0` | `LobbyGameScreen_OnStartLoading` | `LobbyGameScreen_OnVillageConnectionLoggedOut` | Only xrefs are DATA from `LobbyGameScreen_SubscribeConnectionObservers @0x004351fa` / `UnsubscribeConnectionObservers @0x00433de6`. Subscribe attaches the screen observer to villageConn `+0x1c/+0x28/+0x8c/+0x98`; this fn-ptr is the immediate at `0x004351fa`, adjacent to the `+0x1c` subscribe. It is **not** the NComm `NE_StartLoading (0x30012)` handler (that is `Manager_HandleNCommEvent @0x0040e560` case `0x30012`). |

Supporting facts established the same session (all `[PROVEN]` unless marked):

- Village vtable base = `0x007db8d4` in noav; `+0x3c` = `0x470d50` `OpenUserComm` (matches the
  existing documented map, so slot indexing is sound). Vtable **ends at `+0x40`** (next bytes are
  string data).
- `+0x14` `HandleLoggedIn` (src line 0x36c), `+0x18` `HandleLoginFailed` (0x374), `+0x1c`
  `HandleLoggedOut` (0x37f) are all **connection-state observer callbacks** from
  `LobbyVillageServerConnection.cpp`, fired by the transport at `conn+0x34`.
- `VillageServerConnection::HandleMessage` (`+0x24`, `0x00470a90`) dispatches ids `0xd8`–`0xdc`,
  `0x12f`, `1000`–`1006`, `0xc1c`–`0xc1e`, `0xc80/0xc81`, `0xe11/0xe1b/0xe25`, `0xed7`, `0xf46`,
  `0xf5a`. **No 2002, no logout id** → LoggedOut is not a village NETMSG.
- Transport interface (object at `conn+0x34`): `vtbl[0x0c]`=GetState, `[0x10]`=Login/Open,
  `[0x18]`=**Logout**, `[0x1c]`=Send. `RefereeServerConnection_Logout @0x00479540` calls
  `transport->vtbl[0x18]`. The village 2002 sender does **not**.
- `LobbyManager+0x50` = the ConnectionManager (unnamed in Ghidra); `vtbl[0x38]` resolves a server
  id's status (must be `0` or `0xCD`), `vtbl[0x18]` yields the transport.

`[TODO]` **Open question blocking the stub change:** what inbound event drives the transport to fire
the village `LoggedOut` callback. Counterpart is known empirically — `LoggedIn` is driven by the
login handshake completing (`153 AddResult`) — so the same sub-layer (likely `tincat3.dll`, which has
no symbol matching `*ogout*`) decides it. Not settled statically this session.

### Comm-sink discovery (live, 2026-07-25) — how connection callbacks are actually fired

Found by breakpointing `VillageServerConnection::HandleLoggedIn` on a live village login and reading
the caller. **The connection lifecycle callbacks are NOT fired by tincat3 — LobbyManager is the comm
sink and dispatches them.**

| Addr | Name | Evidence |
|---|---|---|
| `0x00464bf0` | `LobbyManager_OnLoggedOut_CommSink` (was `FUN_00464bf0`) | logs `"LobbyComm::System::LoggedOut"` (`LobbyManager.cpp:0x3be`); mirrors OnLoggedIn; dispatches `vtbl[0x1c]` per sub-conn |
| `0x00463710` | `LobbyManager_Logout` (was `FUN_00463710`) | logs `"LobbyComm::System::Logout"` (`LobbyManager.cpp:0x1ea`) |

**Comm-sink vtable @ `0x007dacb0`** (RTTI ptr at base-4 `0x007dacac`), 7 slots — `[PROVEN]`, read from
the binary and cross-checked against two known members:

| Slot | Target | Role |
|---|---|---|
| `+0x00` | `0x00464260` | `[TODO]` |
| `+0x04` | `0x00463a10` | `LobbyManager::OnLoggedIn` |
| `+0x08` | `0x00464a20` | LoginFailed `[INFERRED]` |
| `+0x0C` | `0x00464bf0` | **`LobbyManager::OnLoggedOut`** |
| `+0x10` | `0x004647e0` | ConnectionLost `[INFERRED]` |
| `+0x14` | `0x00462760` | `LobbyManager::DispatchInboundToConnection` (known) |
| `+0x18` | `0x00463bc0` | `LobbyComm::System::StatisticsConnectionReceived` |

`OnLoggedOut(connId, arg)` matches `connId` against main-conn / village `+0x540` / UC `+0x3d8` /
gameSlot `+0x544` / referee `+0x490`, calls that conn's `vtbl[0x1c]`, then its `vtbl[0x08]` (close),
and for the village branch also resets the world-stream handler `+0x140`, server list `+0x54`
(re-running `FUN_00468e80`, which re-registers the type-4/5 server observers) and loader `+0x100`.

**Live-proven chain (2026-07-25):** msg 2002 sent → `LeavingVillage(10)` → *[missing: comm layer must
fire sink `+0x0C`]* → village `vtbl[0x1c]` `HandleLoggedOut` → `SetState(VillageLeft=11)` →
villageConn `+0x1c` observer list → `LobbyGameScreen_OnVillageConnectionLoggedOut` → arms referee login.

`[TODO]` **THE remaining unknown:** what makes the comm layer invoke sink `+0x0C` for a connection.
Ruled out this session: it is not a village NETMSG (`HandleMessage` has no such id), and `msgdefs.ini`
has no server→client logout/logout-result message (`LeaveServer` = 190 is client→server, about game
servers). Next: breakpoint `LobbyManager::OnLoggedIn @0x00463a10` at entry and read `[ESP]` (the exact
caller, no unwinding) on a fresh login — the sink's LoggedIn caller is the same layer that would fire
LoggedOut.

### 2026-07-25 (cont.) — the comm-layer caller, found live; and a decisive NEGATIVE result

**Caller of the sink, caught live** (breakpoint at `LobbyManager::OnLoggedIn @0x00463a10` entry, frame 1
of the stack): `tincat3` **`CommLayer_ServerRecvHandler_StateMachine @0x10023cc0`**, call site `0x10024159`.
The exact sequence `[PROVEN]` (disassembled):

```asm
1002412c  MOV ECX,[EDI+8]              ; EDI+8 = the connection object
1002412f  MOV dword ptr [ECX+8], 0x8   ; ← state := 8  (the field GetState@0x10036bd0 returns)
10024136  MOV ESI,[EBP+8]              ; ESI = the SINK object (LobbyManager); EBP = comm layer
10024147  MOV EBX,[ESI]                ; EBX = sink vtable — live value 0x007DACB0, confirms the base
10024152  MOV EDX,[EBX+0x4]            ; sink vtbl[+0x04] = LobbyManager::OnLoggedIn
10024157  MOV ECX,ESI
10024159  CALL EDX                     ; OnLoggedIn(connId, serverHandle)
```
So the sink is reached as `*(commLayer+0x8)`, and sink calls are always `MOV EBX,[sink]` → `MOV EDX,[EBX+slot]`.

**NEGATIVE RESULT `[PROVEN]` — `OnLoggedOut` is NOT fired by message processing.** Searching both receive
handlers for the sink-call pattern `[EBX + 0xc]` (slot `+0x0C` = `OnLoggedOut`) returns **zero matches**:
- `CommLayer_ServerRecvHandler_StateMachine @0x10023cc0` — 0 hits; its only connection-state writes are
  `[conn+8] := 5, 6, 7, 8` (`0x100242ff`, `0x10023e01`, `0x10023ed2`/`0x10023fe5`, `0x1002412f`).
- `CommLayer_ClientRecvHandler_StateMachine @0x10023460` — 0 hits; state writes `:= 5, 8` only.

⚠️ **Trap for the next reader:** several `MOV EDX,[EAX+0xc]; CALL EDX` sites in the server state machine
(`0x100241ec`, `0x100241fb`, `0x100242bd`) look like sink `+0x0C` calls but are **`GetState` on a transport**
(same slot index, different class) — proven by the adjacent `CMP EAX,0x4` (OnLoggedOut returns void) and by
direct `CALL 0x10036bd0` (=GetState) in the same block. Do not re-derive this false positive.

**Therefore `[INFERRED, strong]`:** the `LoggedOut` callback originates from a **connection teardown/close
path**, not from an inbound message — consistent with `LobbyManager_Logout@0x00463710` driving logout via
`pConnectionManager->vtbl[0x3c]` (disconnect) rather than by sending anything. Corollary: no NETMSG reply can
produce `VillageLeft(11)`; the server most likely has to **close the village connection**. Still `[TODO]`:
locate the exact tincat3 teardown function that calls sink `+0x0C`, and determine whether a peer-initiated
close maps to `OnLoggedOut (+0x0C)` or to `ConnectionLost (+0x10)` — those go to different handlers.

### 2026-07-25 (final) — `OnLoggedOut` mechanism FULLY RESOLVED (static, tincat3)

Chased from the sink slot `+0x0C` backwards. **`OnLoggedOut` is fired by a deferred notification pump,
armed by a per-connection flag, which is set by the connection's own `Logout` virtual.**

New names in `tincat3.dll` (all `[PROVEN]`, decompiled):

| Addr | Name | Body |
|---|---|---|
| `0x1002fa00` | `CommLayerConn_PumpPendingLoginNotifications` | `if (conn+0x24) { conn+0x24=0; sink=*(commLayer+8); sink->vtbl[0x04](conn,h); }` then `if (conn+0x25) { conn+0x25=0; sink->vtbl[0x0c](conn,h); }` — i.e. **`+0x24` → OnLoggedIn, `+0x25` → OnLoggedOut** |
| `0x1002f9e0` | `CommLayerConn_Logout_FlagLoggedOut` | `conn+0x25 = 1; conn+0x08 = 0;` (flag + state reset — `+0x08` is the field `GetState@0x10036bd0` returns) |
| `0x1002f400` | `CommLayerConn_Logout_TeardownSocket_0x28` | socket at `conn+0x28`: `vtbl[0xf8]()`, `FUN_10019090()`, dtor`(1)`, null it → then `FlagLoggedOut` |
| `0x1002fb90` | `CommLayerConn_Logout_TeardownSocket_0x2c` | `FUN_10027710(conn+0x28)`; same teardown on `conn+0x2c` → then `FlagLoggedOut` |

**Connection vtable family `[PROVEN]`** (read at `0x100515c0..0x1005169c`; RTTI ptrs at `0x10051600`,
`0x10051648`, `0x10051690` mark the boundaries). Four sibling classes share a layout; in **every** one,
**slot `+0x18` is `Logout`**, and `+0x0C` is `GetState@0x10036bd0`:

| vtable base | `+0x0C` GetState | **`+0x18` Logout** |
|---|---|---|
| `0x100515bc` | `0x10036bd0` | `CommLayerConn_Logout_TeardownSocket_0x28` |
| `0x10051604` | `0x10036bd0` | `CommLayerConn_Logout_FlagLoggedOut` |
| `0x1005164c` | `0x10036bd0` | `CommLayerConn_Logout_TeardownSocket_0x2c` |
| `0x10051694` (the live village transport) | `0x10036bd0` | *(read `0x100516ac` to confirm)* |

Cross-confirmation: `RefereeServerConnection_Logout@0x00479540` calls `transport->vtbl[0x18]` — matching
slot `+0x18` = Logout exactly. The pump also explains why `LobbyManager::OnLoggedIn` is reachable **two**
ways (direct from `CommLayer_ServerRecvHandler_StateMachine@0x10024159`, and deferred via the pump).

**Full chain, end to end:**
```
[trigger] → conn->vtbl[0x18] Logout → conn+0x25 = 1, conn+0x08 = 0
  → CommLayerConn_PumpPendingLoginNotifications → sink vtbl[0x0C]
  → LobbyManager_OnLoggedOut_CommSink@0x00464bf0 → villageConn->vtbl[0x1c]
  → VillageServerConnection::HandleLoggedOut@0x00470e20 → SetState(VillageLeft=11)
  → villageConn +0x1c observer list → LobbyGameScreen_OnVillageConnectionLoggedOut@0x004316c0
  → arms referee login → RegisterGame → RegisterGameResult{GameSeed} → RequestStateTransition(1) → MATCH LOADS
```

`[TODO]` **The one open link:** what calls `vtbl[0x18]` on the *village* connection after msg 2002. It is
**locally invoked** (no message sets `+0x25`). Most likely a remote socket close makes tincat3's recv path
call Logout — the teardown implementations destroying the socket object are consistent with that — but this
is **`[INFERRED]`, not proven**, and the competing possibility is that a remote close routes to
`ConnectionLost` (sink `+0x10` → `0x004647e0`) instead, which does **not** reach `HandleLoggedOut`.
Next step: find the recv/EOF path that calls `vtbl[0x18]`, then ER + test "stub closes the village
connection on 2002" with breakpoints on both `0x00464bf0` and `0x004647e0` to see which fires.

### 2026-07-26 — static dive into the tincat3 Logout path: narrowed, but NOT closed

Goal was to prove what makes the *village* connection fire sink `+0x0C` (OnLoggedOut). Result: the
connection layer is a multi-class async state machine, and the answer is **not statically settled**.
What is now established:

- The tincat3 connection family is `CommLayer::Connection*` (RTTI-named, found via destructors):
  `ConnectionDummy` (base — its ctor `FUN_1002f990@0x1002f990` zeroes `+0x24`/`+0x25`),
  `ConnectionBC` (dtor `FUN_1002f330`), `ConnectionLANLobby` (dtor `FUN_10030170`).
- Vtable region `0x100515bc`–`0x100516d0` holds four sibling vtables; every one has
  `+0x0C` = `GetState` (`0x10036bd0`), and `+0x18` = that class's **Logout**:
  | vtable base | `+0x18` Logout impl | behaviour |
  |---|---|---|
  | `0x100515bc` | `0x1002f400` `CommLayerConn_Logout_TeardownSocket_0x28` | destroys socket `+0x28`, then flags |
  | `0x10051604` | `0x1002f9e0` `CommLayerConn_Logout_FlagLoggedOut` | `conn+0x25=1; conn+8=0` |
  | `0x1005164c` | `0x1002fb90` `CommLayerConn_Logout_TeardownSocket_0x2c` | destroys socket `+0x2c`, then flags |
  | **`0x10051694`** (the **live village transport**, read from the running client) | **`0x10030510`** | `state := 9`, then net-driver disconnect `FUN_10019130(conn+0x24)`; **does NOT set `+0x25`** |
  (`0x10051604 +0x3C` = the notification pump `CommLayerConn_PumpPendingLoginNotifications`.)

⚠️ **The gap `[PROVEN NEGATIVE]`:** `conn+0x25` is written by exactly two functions —
`0x1002f9e0` (`=1`) and the `ConnectionDummy` ctor (`=0`). Neither is on the village transport class's
Logout path, and there is **no `CMP [reg+8], 9`** anywhere in tincat3 (byte-searched EAX/ESI/EDI forms),
so the `state==9` "logging out" condition is not polled in that idiom. **Conclusion: we cannot yet say
which sink callback a remote close produces for the village connection** — `OnLoggedOut` (`+0x0C`,
reaches `HandleLoggedOut` → `VillageLeft(11)`) or `ConnectionLost` (`+0x10` → `0x004647e0`, which does
**not**). That distinction decides whether "stub closes the village socket" is the fix.

**Decision:** stop the static dive here (diminishing returns against a large async state machine) and
settle it empirically — the two breakpoints `0x00464bf0` (OnLoggedOut) and `0x004647e0` (ConnectionLost)
discriminate the outcomes exactly, in one run. Requires an Engagement Record (stub wire-change).

**Class identified `[PROVEN]`:** the village/lobby transport (vtable `0x10051694`) is
**`CommLayer::ConnectionReal`** — ctor `FUN_100301f0@0x100301f0` (assigns the vftable; sets
`+0x28=-1`, `+0x2c=0xefffffee`, `+0x38=0`, `+0x3c=1`, `+0x24`=socket wrapper `FUN_10018c70(...,2,0x1e61)`,
`+0x30`=`PropertyDataConverter`, `+0x34`=`TinCat_CreatePropertySet()`), dtor `FUN_10030940`.
Siblings: `ConnectionDummy` (base), `ConnectionBC`, `ConnectionLANLobby`.

**`ConnectionReal` per-tick handler = vtbl`+0x3C` = `FUN_10030680`:**
```c
if (conn+0x24) FUN_100190d0(conn+0x24);                     // tick net driver
if (conn+0x38) (**(**(conn+0x38) + 0xc))(*(int*)(conn+8));  // push STATE to observer@+0x38
```
`conn+0x38` is set after construction (live value `0x1BB51658`, in tincat3's heap — so it is an internal
observer, NOT the LobbyManager sink, whose OnLoggedOut takes two args). **Resolving `conn+0x38`'s class
is the remaining blocker**; it is a runtime-installed pointer, i.e. exactly the "purely runtime-virtual"
case HARNESS §6 says to settle with a live read rather than static guessing.

**Also upgraded to `[PROVEN]`:** sink slot `+0x10` = ConnectionLost — `FUN_004647e0@0x004647e0` carries
the string `"LobbyComm::System::ConnectionLost"` (xref from `0x007dadd8`). Previously `[INFERRED]`.

**Reference check (dead end, recorded so it is not repeated):** the AdK emulator
(`~/Downloads/AdK-emulator`, our exact `0x26B6` wire) does **not** implement the village/world
connection — no `0xAFFEDEAD`, no msg 2002 anywhere. Its `UserLoggedOut` is NETMSG **110**
`{type, user_id}`, a presence broadcast to *other* users on disconnect, not a per-connection logout ack.
It therefore says nothing about the village LoggedOut mechanism.

### 2026-07-26 (cont.) — live pointer-walk + the decisive NEGATIVE: OnLoggedOut looks UNREACHABLE for ConnectionReal

Read-only live walk (no breakpoints, no wire change), client in-world at `LobbyManager.state = 9`:
`g_pLobbyManager@0x885890` → `0x0E6598E8` → `+0x540` villageConn `0x0E64FD38` (vtbl `0x007DB8D4` ✓)
→ `+0x34` transport `0x1BBE80A0` (vtbl **`0x10051694` = `CommLayer::ConnectionReal`**, `+0x08` state = 8,
`+0x1c` serverId = 50 ✓) → `+0x38` observer `0x1BB72858` → its vtable **`0x1004F8DC`**
(RTTI ptr at base-4 `0x1005703C`).

Observer vtable `0x1004F8DC`: `+0x00`=`0x100267E0`, `+0x04`=`0x10023BF0`, `+0x08`=`0x1000DC20`,
**`+0x0C`=`0x1000DC20`**, `+0x10`=`CommLayer_ClientRecvHandler_StateMachine@0x10023460`,
`+0x14`=`0x10023AF0`. **`FUN_1000dc20` is `{ return; }` — a shared no-op stub** (hence the same address
in two slots). So `ConnectionReal`'s per-tick state push (`0x10030680`) goes nowhere.

**Therefore, for `CommLayer::ConnectionReal` (the village transport):**
1. tick `vtbl[0x3C]`=`0x10030680` does **not** call the notification pump;
2. `Logout` `vtbl[0x18]`=`0x10030510` sets `state:=9` + net-driver disconnect, never sets `+0x25`;
3. the pump (`CommLayerConn_PumpPendingLoginNotifications`, the ONLY caller of sink `+0x0C`) is invoked
   only from the *other* classes' ticks — `FUN_1002f920`, `FUN_10030110` — and their vtable slot.

⇒ **`OnLoggedOut` is not reachable for this connection class via any path found.** Consequence:
**"stub closes the village connection on msg 2002" would NOT drive `VillageLeft(11)`** — do not implement
it on that premise. (Consistent with the earlier live run where a `LobbyManager::OnLoggedOut` breakpoint
never fired.)

⚠️ **Honest limit of this negative:** the sweep for sink `+0x0C` call sites is **not exhaustive** — it
covered both recv state machines, the two `conn+0x25` writers, and the pump's callers, but not every
`MOV r32,[r32+0x0c]` register encoding program-wide. So this is **`[STRONG, not airtight]`**. The paradox
worth resolving next: the client *does* subscribe a game-screen observer to the village conn's LoggedOut
list and `LobbyManager::OnLoggedOut` has a full village branch (resets world-stream handler, server list,
re-registers type-4/5 observers = exactly "return to the village list"), so the path is clearly *intended*
to run. Either a reachable trigger exists that this sweep missed, or the real village-leave completes by a
different mechanism entirely.

### 2026-07-26 — EXHAUSTIVE sink sweep (in-Ghidra script) + the definitive verdict on "close the village socket"

Ran two in-Ghidra scripts over tincat3 (all 101k instructions, every register encoding — the earlier
byte-pattern and operand-filter attempts were both unreliable; the operand filter silently mangles `+`).

**Sweep 1** — every indirect call through `[reg+0xC]`: **193 sites**.
**Sweep 2** — filtered to the sink-call *shape* (object loaded from `[X+8]`, vtable deref, slot call),
restricted to slots `+0x4`/`+0xc`: **97 candidates**, resolved as follows:
- ~90 are `obj=[EDI+8]`/`[ESI+8]` = the pervasive *"connection at +8 → `GetState` at vtbl+0xc"* idiom;
- 4 are `[EBP+8]` **message-factory** calls (`commLayer+0x20` → `vtbl[0xc]` = create PropertySet), e.g.
  `FUN_10018340`, `FUN_1002ed80` — false positives of the heuristic (register reuse after a call);
- **exactly 2 are real sink calls**, and both were already known:
  `slot +0x4 @0x10024159` in `CommLayer_ServerRecvHandler_StateMachine` (**OnLoggedIn** — the one caught
  live) and `slot +0xc @0x1002fa6e` in `CommLayerConn_PumpPendingLoginNotifications` (**OnLoggedOut**).

⇒ **`[PROVEN]` The pump is the ONLY caller of sink `OnLoggedOut` in tincat3**, and it is unreachable for
`CommLayer::ConnectionReal` (the village transport). The earlier `[STRONG, not airtight]` negative is now
**hardened**. ⚠️ Note slot `+0xc` has **three** distinct meanings in this codebase (sink OnLoggedOut,
connection GetState, property-factory Create) — never identify a sink call by offset alone.

**BUT the socket-close question has a different, decisive answer — via `ConnectionLost`, not `LoggedOut`:**

`LobbyManager::OnConnectionLost @0x004647e0` (sink `+0x10`, `LobbyManager.cpp:0x31e`) routes the village
conn to `villageConn->vtbl[0x20]` = **`VillageServerConnection::HandleDisconnected @0x00470f90`**, which
does the same teardown as HandleLoggedOut, **plus** tears down the UserComm conn, and **does reach
`SetState(VillageLeft = 0xB)`** — then calls `LobbyComm::BaseConnection::Disconnected @0x0048e3c0`
(`LobbyBaseConnection.cpp:0x8f`), which fires the observer list at **`conn+0x28`**
(vs `BaseConnection::LoggedOut @0x0048e2a0`, `.cpp:0x82`, which fires **`conn+0x1c`**).

**Observer registration `[PROVEN]`** (disassembled `LobbyGameScreen_SubscribeConnectionObservers`, the
fn-ptr immediates sit right next to their `ADD ECX,<offset>`):
| villageConn list | fires on | game-screen callback |
|---|---|---|
| `+0x1c` (`0x0043520a`, immediate at `0x004351fa`) | LoggedOut | `LobbyGameScreen_OnVillageConnectionLoggedOut@0x004316c0` — **arms the referee** |
| `+0x28` (`0x004351e5`, immediate at `0x004351d5`) | Disconnected | `LobbyGameScreen_OnGameConnectionResult@0x00432ed0` — `Game_SetRunMode(host,2)` + **`!ERROR_DIALOG` / `!CONNECTION_LOST_TEXT`** |
(This also upgrades the `+0x1c` → `0x004316c0` attribution from `[INFERRED-high]` to `[PROVEN]`.)

## VERDICT `[PROVEN]` — do NOT close the village connection
Closing it **would** clear `LeavingVillage(10)` → `VillageLeft(11)`, but it fires the **Disconnected**
observer, not the LoggedOut one: the player gets a **"connection lost" error dialog** and is bounced to
run-mode 2. The referee is never armed, so the match never loads. The change would have looked partly
right (state advances!) while being wrong — the worst kind of false positive.

`[TODO]` Since `OnLoggedOut` is unreachable for `ConnectionReal`, the "match-start needs a village
LoggedOut" model cannot be how the real flow works. Next line of enquiry: what *else* clears
`LeavingVillage(10)` legitimately — i.e. find the real consumer of the msg-2002 request server-side.

### 2026-07-26 (correction) — the "socket close = error dialog" verdict was WRONG; the dialog is CONDITIONAL

⚠️ **Correcting my own entry above.** I wrote that closing the village connection "fires the Disconnected
observer → `!CONNECTION_LOST_TEXT` → never arms the referee", and labelled it `[PROVEN]`. The error dialog
part is **wrong**: it is guarded. `LobbyGameScreen_OnGameConnectionResult@0x00432ed0` reads:

```c
Game_SetRunMode(host, 2);               // UNCONDITIONAL — return to the lobby/village screen
Game_PropagateModeToChildren(host);
if (param_2 != 0) {                     // CONDITIONAL — only on a non-zero reason code
    ... "!ERROR_DIALOG" / "!CONNECTION_LOST_TEXT" ...
}
```
With reason code **0** (graceful close) there is **no dialog** — the client simply goes to run-mode 2,
i.e. back out of the village. Combined with `HandleDisconnected@0x00470f90` reaching
`SetState(VillageLeft = 0xB)`, that is a **complete, clean leave-village**.

The reason code is threaded through: `LobbyManager::OnConnectionLost(this, connId, ?, reason)` →
`villageConn->vtbl[0x20](reason)` = `HandleDisconnected` → `BaseConnection::Disconnected@0x0048e3c0`
(which logs only `if (reason != 0)`) → fires the `+0x28` observer list **with that same reason**.

**Revised conclusion:** for the *village-leave* itself, the genuine mechanism is very likely that the
server **closes the village connection** after receiving msg 2002, and the client completes via
`ConnectionLost → HandleDisconnected → VillageLeft(11)` + run-mode 2. This also resolves the paradox of
`OnLoggedOut` being unreachable for `ConnectionReal`: the village conn was never meant to use it.

**Open, and the thing to test:** whether a server-side close surfaces with **reason 0** (clean → no
dialog) or non-zero (→ dialog). That is empirical, and the two breakpoints `0x00464bf0` (OnLoggedOut) and
`0x004647e0` (OnConnectionLost, where the reason arrives as an argument) read it directly.

**Also established this session:** the leave is a normal UI flow — `LobbyVillageScreen::OnLeaveVillage`
case 5 raises the `!LEAVE_VILLAGE_QUESTION` / `!LEAVE_VILLAGE` confirm popup; on confirm the callback
`FUN_00431ce0` (param_2 == 2) calls screenHost `vtbl[0x84]` = `CLobbyClient::LeaveVillage@0x00503470`,
which **tail-jumps** into `SendLeaveVillageRequest_2002`. (That tail jump is why the live stack showed the
2002 sender returning to `0x00431CFB` — `[ESP]` held LeaveVillage's caller, not its own.)
