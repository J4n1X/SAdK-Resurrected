# SaDK Reverse-Engineering SOURCEMAP

Named functions, structs, fields, globals and enums from the live Ghidra project (ground-truth).

> **[TODO] Address-base caveat.** Addresses here are from a **pre-magazine (no-CD/dump) build** base.
> The clean magazine build differs: code shifts non-uniformly (re-map by string/xref), `.data` shifts a
> uniform `-0x7660`. Example: `HandleEnterWorld` = `0x46f470` (dump base) vs `0x46f670` (clean build).
> **Struct offsets and logic still transfer 1:1.** Verify any single address against the build you run.

| Program | Image base | Runtime | Notes |
|---------|-----------|---------|-------|
| `SADK.exe` | `0x00400000` | 1:1 (no rebase) | game client; lobby/village protocol |
| `tincat3.dll` | `0x10000000` | — | TinCat networking + property-bag codec (has C++ symbols) |

**Ghidra tip:** the decompiler can't retype the `__thiscall` `this` auto-param, so `this->field` may render
as `*(this+0xN)`. Fix per-function: right-click `this` → **Retype Variable** → e.g. `VillageServerConnection *`.

---

## 1. Structs & enums (exact field layouts) [PROVEN]

### `VillageServerConnection` (SADK.exe, 0x258 bytes) — `this` for all Handle* below
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x000 | VillageServerConnection_vtable* | pVtable | vtable @ `0x7dc8d4` (17 slots; RTTI COL ptr @ `0x7dc8d0`). **NOTE: real base is 0x7dc8d4, not 0x7dc8e0** — verified by Trigger's `vtbl[0x3c]`=OpenUserComm(0x470b50)@0x7dc910 and the RTTI ptr at base-4. |
| 0x158 | LobbyManager* | pLobbyManager | |
| 0x160 | void* | pWorldActiveCtx | |
| 0x164 | — | pChatChannelList_alloc | std::list head (alloc/myHead/mySize @ +0x164/+0x168/+0x16c) |
| 0x170 | void* | pEntityPool_0xE0 | 1001/1002 building/object records |
| 0x174 | void* | pEntityPool_0x120 | 1004 player/settler records |
| 0x184 / 0x198 / 0x1ac | — | pEventQueue_* | change-event ring buffers |
| 0x224 | byte | bLoginAckReceived | set by 1006 iff code==0xDEADBEEF |
| 0x225 | byte | bWasConnected | |
| 0x228 | byte[28] | pWorldName | std::string (0x1C) |
| 0x244 | uint | dwConnState | **3 = in-world** |
| 0x248 | void* | pPingTargetConn | ==this ⇒ ping outstanding; 0x80008000 ⇒ none |
| 0x24c/0x250/0x254 | float | flPing* | ping timing |

### `LobbyVillageEnterAction` (SADK.exe, 34 bytes) — the "BETRETE WELT" action object
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x00 | void* | pVtable | |
| 0x08 | LobbyManager* | pManager | |
| 0x0c | void* | pConn | live village conn (0 = none) |
| 0x10 | bool | fConnNeedsTeardown | one-shot teardown |
| 0x11 | bool | fEnterArmed | armed by the enter button |
| 0x18 | float | flRetryTimer | tick counts down, then re-fires Trigger |
| 0x20 | bool | fImmediate | |
| 0x21 | bool | fSubmitted | |

### `LobbyManager` (SADK.exe, class `LobbyComm::System`; singleton ptr @ `DAT_0088cef0`)
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x000 | void* | pVtable | object vtable — **polymorphic**; `FUN_004625c0` does `(**(code**)*singleton)(1)` (vtable[0] deleting dtor) |
| 0x04c | void* | pCommLayer | the ONE TinCat comm layer (magic 0x26B6) |
| 0x050 | void* | pServerMgr | room/server-list manager (ConnectionManager; factory @ +0x20) |
| 0x054 | void* | pVillageServerList | `LobbyComm::ServerList` (embedded) |
| 0x0d4 | — | (server-list vector) | begin/end @ +0xC8/+0xCC |
| 0x3d8 | void* | pUserCommConnection | the UC/chat sub-connection object |
| 0x540 | void* | pVillageConnection | the VillageServerConnection slot |
| 0x548 | void* | pChatServerHandle | TinCat handle set at main-conn login; reused for every dial |
| 0x550 | void* | pSelectedVillageServer2 | recorded at village sub-login |
| 0x57c | LobbyManagerState | state | see enum |

`GetSelectedVillageServer` = `*(pVillageServerList+0x80)`.

### `LobbyVillageScreen` (SADK.exe, 541 bytes) — char-select / enter screen
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x000 | void* | pVtable | object vtable — **polymorphic**; methods are vtable-referenced (`OnLeaveVillage`@0x7d7ed0, `UpdateEnterButton`@0x7d831c) |
| 0x0c0 | — | (enterAction) | `LobbyVillageEnterAction*` (per RequestEnterVillage) |
| 0x1e8 | int | nViewMode | ==1 required for enter |
| 0x1ec | void* | pField98Owner | sub-object; +0x98 must be !=0 (server selected) |
| 0x1f0 | void* | pServerList | village server list the button checks |
| 0x204 | void* | pButtonContainer | |
| 0x218 | bool | fIdleFlag | enable gate |
| 0x21c | bool | fBusyGuard | enable gate (==0) |

### `UserCommConnection` (SADK.exe, 148 bytes)
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x00 | void* | pVftable | |
| 0x34 | void* | pTransport | dial via `(*pTransport)->vtbl[0x10](handle,0,..)` |
| 0x38 | byte[88] | pBaseConnection | embedded LobbyBaseConnection |
| 0x90 | void* | pSystem | comm system |

### `NetMsgReader` (SADK.exe, 52 bytes) — inbound message / property-bag reader
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x00 | void* | pVtable | getters: +0x18 ReadMemBlock/u32, +0x20 ReadMemBlock(64B), +0x30 ReadString |
| 0x20 | byte | bIsValid | |
| 0x28 | uint | dwMsgType | read by FUN_005025e0 |
| 0x30 | void* | pPropBag | (PropertyReader = same object viewed as a bag) |

### `TinCatProperty` (tincat3.dll, 56 bytes) — one property in a PropertySet
| Off | Type | Field | Note |
|----:|------|-------|------|
| 0x00 | void* | pVftable | |
| 0x04 | char[12] | pName | std::string (SSO) |
| 0x10 | uint | **dwType** | TYPE ENUM (see below) |
| 0x14 | char[12] | pStrval | std::string (type 2) |
| 0x20 | uint | dwSize | byte width / capacity |
| 0x28 | void* | pValue | value bytes / ptr |
| 0x2c | uint | dwValueHi | 64-bit hi / value tail |
| 0x30 | void* | pOwnerSet | back-ptr to PropertySet |
| 0x34 | uint | dwFlag | |

**Property `dwType` enum** (from `SetMemBlock` 0x10011500): `1`=mem/cstring(var), `2`=std::string(var),
`3`=wstring(var) → all **u32 LE length-prefix + bytes**; `4/5`=1B, `6/7`=2B, `8/9`=4B(u32), `0xa/0xb`=8B,
`0xc`=f32, `0xd`=f64, `0xe`=LBOOL(1) → **raw fixed width, no prefix**.

### `TinCatPropertySet` (tincat3.dll, 32 bytes)
`0x00 pVftable · 0x04 pAddFunctor · 0x0c pPropList · 0x1c pIterCursor`.

### `TinCatPropDataConverter` (tincat3.dll, 8 bytes)
`0x00 pBuffer · 0x04 dwLength`. Serialize/Deserialize read/write `pBuffer[0..dwLength)`.

### enum `LobbyManagerState` (SADK.exe, @ LobbyManager+0x57c)
`1 Disconnected · 3 Authorized · 6 LoadingGlobalData · 7 GlobalDataLoaded · 8 EnteringVillage ·
9 VillageEntered · 10 (room/login step) · 11 VillageLeft · 12 ConnectionLost`.

---

## 2. SADK.exe functions

### 2a. World-entry trigger / connection path [PROVEN]
| Addr | Name | Signature / role |
|------|------|------------------|
| 0x503da0 | `LobbyVillageEnterAction_Trigger` | `void __thiscall(this, bool bImmediate)` — CreateVillageServerConnection then tail-jmp conn->vtbl[0x3C] |
| 0x503e10 | `LobbyVillageEnterAction_Tick` | per-frame retry/heartbeat; pumps state machine (FUN_00464c00) |
| 0x4f4ef0 | `CLobby_RequestEnterVillage` | click-side forwarder → Trigger(screen->enterAction@+0xC0) |
| 0x463750 | `LobbyManager_CreateVillageServerConnection` | `void* __thiscall(LobbyManager*, int dwVillageServerId)` — resolve/validate only; **no socket I/O**; returns mgr+0x540 |
| 0x470b50 | `VillageServerConnection_OpenUserComm` | `bool __thiscall(this, int serverHandle)` — **the dial** (vtbl+0x3C); opens UC transport to GetChatServerHandle |
| 0x526ba0 | `VillageConn_GetTransport` | returns `conn+0x34` (transport; the connect gate) |
| 0x46b250 | `LobbyManager::GetSelectedVillageServer` | returns `list+0x80` |
| 0x439e80 | `LobbyVillageScreen_UpdateEnterButton` | button enable/label; needs IsListReady (0x4AD750) |
| 0x4626a0 | `LobbyManager_GetUserCommConnection` | returns mgr+0x3d8 |
| 0x4409d0 | `LobbyManager_HandleRoomServerDescriptor` | fires `"LoadLevel"` when a 170 descriptor is JOINABLE (roomId==g_dwSelectedVillageRoomId & +0x34==0 & +0x35!=0). **Does NOT SetState.** |

Read-only context: `0x462700 SetState`, `0x4626f0 GetState`, `0x4625e0 LobbyManager_GetInstance`,
`0x4AD750 IsListReady_impl`, `0x4640f0 LobbyComm::System::Initialize`
(sole `CreateCommLayer(0,0x26B6,5,name)` @0x46434b).

### 2b. Village / world message receiver (vtable @ `0x7dc8d4`, 17 slots) [PROVEN]

> Typed as struct `VillageServerConnection_vtable` in the project. Key slots (base 0x7dc8d4):
> `+0x0c` Connect · `+0x14` HandleLoggedIn · `+0x18` HandleLoginFailed · `+0x1c` HandleLoggedOut ·
> `+0x20` HandleDisconnected · `+0x24` HandleMessage · `+0x28` TickInWorld · `+0x3c` OpenUserComm ·
> `+0x40` **SendLeaveVillageRequest_2002** (renamed 2026-07-25 — see correction below).

> **⚠️ CORRECTION 2026-07-25 `[PROVEN]` (verified on `sadk_noav.exe`, vtable base `0x007db8d4`;
> slot `0x007db914` read = `0x0046bde0`).** Slot `+0x40` was named `SendWorldLoginReq_2002` and
> carried the plate comment *"DORMANT (no analyzed caller) … Genuine world-entry is server-driven
> (inbound 1000)"*. **Both were wrong**, and the error propagated into the match-start analysis for
> several sessions. The function builds `LobbyMessage(cat=2, msgId=0x7d2=2002){code=0xAFFEDEAD}` and
> calls `SetState(LeavingVillage=10)` — it is a **LEAVE-village request**, and it is *not* dormant
> (this table already documented it as a live vtable slot). Caller: `FUN_00503470`
> (`CLobbyClient::LeaveVillage`) tail-jumps `villageConn->vftable+0x40`.
>
> Consequence: after sending 2002 the client sits in `LeavingVillage(10)` awaiting the connection to
> be driven to **LoggedOut** (`+0x1c` → `SetState(VillageLeft=11)`), which fires the village conn's
> `+0x1c` observer list → `LobbyGameScreen_OnVillageConnectionLoggedOut` (`0x004316c0` in noav; was
> misnamed `LobbyGameScreen_OnStartLoading`) → **arms the referee login**, which is the gate on the
> whole match-load chain. Answering 2002 with `EnterWorld(1000)` re-enters the *lobby* world instead.
>
> `[TODO]` What inbound event makes the transport (`conn+0x34`) fire the LoggedOut observer is **not
> yet determined**. Transport interface so far: `vtbl[0x0c]`=GetState, `[0x10]`=Login/Open,
> `[0x18]`=**Logout**, `[0x1c]`=Send. Note `SendLeaveVillageRequest_2002` does **not** call transport
> Logout. `HandleMessage` (`+0x24`) does **not** dispatch 2002 or any logout id, so LoggedOut is a
> connection-state callback, not a village NETMSG.
| Addr | Name | Msg / role |
|------|------|------------|
| 0x470890 | `VillageServerConnection::HandleMessage` | dispatcher; type via FUN_005025e0 (msg+0x28) |
| 0x46f470 | `VillageServerConnection::HandleEnterWorld` | **msg 1000** `(this, NetMsgReader*)` — SetState(9); reads Worldname/ServerPerm/ChatChannelsCount/N×{Zone,ID}; JoinChannel; connState=3; SendWorldReadyAck. **[TODO]** clean-build addr 0x46f670 |
| 0x46d820 | `VillageServerConnection::HandleLoggedIn` | vtbl+0x14; own-login OK |
| 0x46d910 | `VillageServerConnection::HandleLoginFailed` | vtbl+0x18 `(this,int)` |
| 0x470c20 | `VillageServerConnection::HandleLoggedOut` | vtbl+0x1c → state VillageLeft(11) |
| 0x470d90 | `VillageServerConnection::HandleDisconnected` | vtbl+0x20 `(this,int)` |
| 0x46ddf0 | `VillageServerConnection::HandleEntityCreate` | msg 1001 |
| 0x46dfb0 | `VillageServerConnection::HandleEntityUpdate` | msg 1002 |
| 0x46e190 | `VillageServerConnection::HandleEntityRemove` | msg 1003 |
| 0x46f6c0 | `VillageServerConnection::HandlePlayerCreate` | msg 1004 (0x120 player/settler) |
| 0x46f420 | `VillageServerConnection::HandleWorldTick` | **msg 1005 = WORLD-CLOCK SYNC** — reads 64-BIT field "tick" (reader vtbl+0x20, 0x40 BITS not bytes), fires notify list `+0x11c` → `CLobbyClient_OnWorldTick_Throttled` → `WorldClock_SlewToTick16(tick&0xFFFF, 250ms)`. Clean-build addr **0x46f620**. [PROVEN 2026-08-01] |
| 0x46e8b0 | `VillageServerConnection::HandleWorldLoginAck` | msg 1006; accepts iff `code==0xDEADBEEF` |
| 0x46bd00 | `VillageServerConnection::SendWorldReadyAck` | sends **msg 0xED6 (3798) "PingCode"**, body PropertySet{PingCode:32B} |
| 0x46be00 | `VillageServerConnection::HandlePongCode` | msg 0xED7 (3799); RTT/quality |

### 2c. Token / UserComm login (LobbyUserCommConnection.cpp) [PROVEN]
| Addr | Name | Role |
|------|------|------|
| 0x47ed90 | `UserCommConnection::Initialize` | `(this, int* commSystem)`; base-inits BaseConnection@+0x38 |
| 0x47fb40 | `UserCommConnection::OpenCommunication` | `(this, int serverHandle)` — dial via transport(+0x34) vtbl+0x10 |
| 0x47ef50 | `UserCommConnection::OnLoggedIn` | |
| 0x47f040 | `UserCommConnection::OnLoginFailed` | `(this, int errCode)` |
| 0x47f310 | `UserCommConnection::OnReceivedData` | → no-op stub `FUN_004A0050` (token 211-214 handled inside tincat3) |
| 0x47f400 | `UserCommConnection::OnChatChannelListReceived` | `(this, int count, void* list, int err)` — post-login server push |
| 0x47fca0 | `UserCommConnection::JoinChannel` | `(this, uint channelId)` |
| 0x463910 | `LobbyManager::OnLoggedIn` | login-success router; sets `pChatServerHandle@+0x548`, `state=3` (SetState(3) @ 0x4639d1) |
| 0x4625e0 | `LobbyManager_GetInstance` | singleton @ DAT_0088cef0 |
| 0x4626c0 | `LobbyManager_GetChatServerHandle` | returns mgr+0x548 |
| 0x4626d0 | `LobbyManager_GetCommSystem` | returns mgr+0x54c |

### 2d. ServerList result callbacks (secondary vtable @ 0x7dbf8c) [PROVEN]

> **⚠️ `this` = `ServerList + 8` in every function below.** The ctor installs the primary vtable at
> `[ServerList+0]` and this `CommLayer::IGameServerObserver` table at `[ServerList+8]`, so **all field
> offsets quoted inside these functions are +8 shifted** relative to the ServerList base — e.g. their
> `this+0x94` is `ServerList+0x9c` (the hosting latch) and their `this+0x9c`/`this+0xa0` are
> `ServerList+0xa4`/`+0xa8` (the referee callback pair). Proof: `CreateResultReceived` passes
> `(int)this + -8` as the observer subject. Misreading this produced two wrong "facts" in one session
> — see `docs/LOBBY_SCREEN_VTABLES.md` for the corrected field map and `decomp/RENAME_LIST.md`
> (2026-07-26 night, cont.) for the derivation.
>
> Addresses here are the **original `SADK.exe`** build. On `sadk_noav.exe` the table is at `0x7daf8c`:
> `+0x0c` GameServerAdded `0x00469610` · `+0x1c` **CreateResultReceived `0x0046a6a0`** ·
> `+0x24` DeleteResultReceived `0x00469990` · `+0x28` GameServerAssigned `0x00469ad0` ·
> `+0x2c` AssignGameServerResultReceived `0x00469be0`.

| Addr | Name | Slot |
|------|------|------|
| 0x4695e0 | `LobbyServerList_UpdateResultReceived` | +0x20 (8) |
| 0x469700 | `LobbyServerList_DeleteResultReceived` | +0x24 (9) |
| 0x469840 | `LobbyServerList_GameServerAssigned` | +0x28 (10) |
| 0x469950 | `LobbyServerList_AssignGameServerResultReceived` | +0x2c (11) |
| 0x469a90 | `LobbyServerList_TANConnectionGranted` | +0x30 (12) — bare notification (log only); NOT the world trigger |
| 0x469b70 | `LobbyServerList_RequestTANConnectionResultReceived` | +0x34 (13) — ACK; clears list on error |
| 0x469c90 | `LobbyServerList_KickResultReceived` | +0x38 (14) |

Add/remove dispatch `0x46a000`; `0x469470` GameServerDataReceived; `0x469380` GameServerAdded;
`0x46a1a0` remove-by-id.

> **Referee functions:** parked/removed from project — see `docs/REFEREE_FUNCTIONS_TO_NAME.md` if restarting.

---

## 3. tincat3.dll functions (C++ symbols + annotations) [PROVEN]

### 3a. Property-bag codec + factory (the wire format)
| Addr | Name | Role |
|------|------|------|
| 0x100110e0 | `PropertyDataConverter::DeserializeProperty` | `uint __thiscall(this, IPropertySet* templateSet)` — **DECODER**; NULL templateSet ⇒ +0x6 crash |
| 0x100112b0 | `PropertyDataConverter::SerializeProperty` | **ENCODER** (2-pass; var types get u32 len-prefix) |
| 0x10013710 | `cPropertyFactory::RegisterPropertySet` | `(this, u16 msgType, IPropertySet*)` — **msgType→template registry** (vtbl+0x04) |
| 0x10013830 | `cPropertyFactory_CreatePropertySet_byType` | `IPropertySet* __thiscall(this, ulong type)` — **THE NULL-returner** (vtbl+0x0C); UArray::find(type) |
| 0x100138f0 | `TinCat_CreatePropertyFactory` | factory ctor |
| 0x100139e0 | `PropertySet::CreateProperty` | `(this, char* name, ulong type, ulong initU32)` |
| 0x10013a50 | `PropertySet::AddProperty` | `(this, IProperty*)` |
| 0x10013d00 / 0x10013d80 / 0x10013d90 | `GetProperty / GetFirstProperty / GetNextProperty` | iteration |
| 0x10011500 | `Property::SetMemBlock` | **the TYPE ENUM source** (switch on +0x10) |
| 0x100117c0 / 0x10011980 | `Property::SetString / SetWString` | type 2 / type 3 |
| 0x10010ee0 / 0x1000c760 | `Property::GetU32 / SetU32` | accessor family |

factory vtable @ **0x1004DE84**: `+0x04 Register · +0x08 Unregister · +0x0C CreatePropertySet(type) · +0x10 CloneTo · +0x14 Destroy`.

### 3b. Comm layer / connection manager
| Addr | Name | Role |
|------|------|------|
| 0x10018c20 | `TinCat_CreateCommLayer` | `ICommLayer* __cdecl(eCommLayer type, ulong magic, eLogLevel, char* name)` |
| 0x10018660 | `CommLayer_ctor` | **magic @ this+0x64, type @ this+0x04**; CommLayer vtable @ 0x1004EC6C |
| 0x1001f630 | `ConnectionManager_base_ctor_makesFactory` | creates factory at ConnectionManager+0x20 (starts EMPTY) |
| 0x10030d50 / 0x10031130 / 0x10031260 | `ConnectionManagerINet_ctor` / LAN / LAN_GS | per eCommLayer type |
| 0x1000cd40 | `CellManager_ctor` | embeds factory(+0xF0)/converter(+0xF8)/PropertySet(+0xD0) |
| 0x10017ba0 | (generic property-bag dispatcher) | built-in system types |
| 0x1002f5a0 / 0x1002fda0 | `GameServerData(170) decoders` | use CreatePropertySet(0xAA) on the same factory |

### 3c. Token validator (211-214)
| Addr | Name | Role |
|------|------|------|
| 0x10023460 | (token receiver state machine) | 0xd4(212-recv)→0xd5(213-send); 0x99 authorized→LoggedIn |
| 0x1002cc70 | `TokenValidator_SendValidateToken_214` | builds **214** (perm_id, cipher MEMBLOCK, nonce 128B, ticket) |
| 0x1002cbd0 | `TokenValidator_GenerateNonce` | 128 random bytes (validator slot+8) |
| 0x1002a1c0 | `CommLayer_AllocTicketId` | monotonic per-conn ticket |
| 0x1002a240 | `CommLayer_LookupMsgDescriptor` | |

**Token wire (msgdefs 211-214, confirmed):** 211 `{type,ticket}` · 212 `{type, nonce[128], ticket}` ·
213 `{type, perm_id, cipher MEMBLOCK, ticket}` · 214 `{type, perm_id, cipher MEMBLOCK, nonce[128], ticket}`.

---

## 4. Key globals & vtables [PROVEN]

**SADK.exe:**
- `DAT_0088cef0` — LobbyManager singleton ptr (getter `0x4625e0`)
- `g_dwSelectedVillageRoomId` @ `0x0087d580` (live = 1000)
- `g_dwInvalidVillageServerId` @ `0x007dc51c` (= 0xFFFFFFFF); pending sentinel 0xFFFFFFFE
- Property-name strings (read by HandleEnterWorld): `Worldname/ServerPerm/ChatChannelsCount/`
  `ChatChannelZone/ChatChannelID/PingCode/PongCode/id/code/tick` @ ~`0x7dc918`–`0x7dc964`
- `VillageServerConnection` object vtable @ `0x7dc8d4` (17 slots, RTTI COL @ `0x7dc8d0`; +0x3c = OpenUserComm, +0x14 = HandleLoggedIn) — struct `VillageServerConnection_vtable`
- `ServerList` secondary callback vtable @ `0x7dbf8c`; `GameServerInfo` vtable @ `0x7df8b8`

**tincat3.dll:**
- factory vtable @ `0x1004DE84`; CommLayer vtable @ `0x1004EC6C`
- comm-layer magic literal **0x26B6** is the ONLY one (single layer for the whole client)

---

## 5. Village message map (HandleMessage 0x470890) [PROVEN]

`1000 EnterWorld→0x46f470 · 1001→0x46ddf0 · 1002→0x46dfb0 · 1003→0x46e190 · 1004→0x46f6c0 ·
1005→0x46f420 · 1006→0x46e8b0 · 0xED6/3798 SendWorldReadyAck(out) · 0xED7/3799 HandlePongCode→0x46be00`.

See `sadk_lobby/village.py` and the in-world TODO in `MEMORY.md` for the current protocol flow.

### 5a. Remaining switch cases — surveyed 2026-07-28 (`sadk_noav.exe` addresses; renamed + checked out
in the shared Ghidra project, but the **checkin failed** — "file requires merge, not supported in
headless mode" — so these renames are **local to this session's headless working copy only**. A
GUI session needs to open the project, pull the latest, and re-apply/checkin before they land on the
shared repo. Full field-level writeup: `docs/IN_WORLD_PRESENCE.md`.)

| msg | id | handler (`sadk_noav.exe`) | role | confidence |
|---|---|---|---|---|
| 0xC1C | AvatarActiveItems? | `HandleAvatarActiveItemsUpdate@0x0046e660` | by `ownr` id: re-reads the 4-slot equipped-items block | H |
| 0xC1D | AvatarInventory? | `HandleAvatarInventoryUpdate@0x0046e6f0` | by `ownr` id: re-reads the variable-length (`sltcnt`-prefixed) inventory block | H |
| 0xC1E | — | `HandleAvatarItemsFullSync@0x0046e780` | by `ownr` id: both of the above in one message | H |
| 0xC80 | — | `HandleAvatarLevelExpUpdate@0x0046c940` | by `ownr` id: `lvl`+`exp` only (partial stats) | H |
| 0xC81 | — | `HandleAvatarStatsUpdate@0x0046c9c0` | by `ownr` id: full `lvl`/`exp`/`gold`/`glod` stats | H |
| 0xE11 | ShopData? | `HandleShopInventoryData@0x004706b0` | `NPCID`/`ShopID`/`ShopName`/`SellMod`/`StockCount`+N item entries | H |
| 0xE1B | — | `FUN_00470990` (not renamed) | `ShopID`+1-bit `Result` → `this+0x134`; sibling of 0xE25 | M (mechanics H, which shop action it acks unconfirmed) |
| 0xE25 | — | `FUN_00470a10` (not renamed) | `ShopID`+1-bit `Result` → `this+0x140`; sibling of 0xE1B | M |
| 0xF46 | TradeRequest? | `HandleTradeRequest@0x0046d920` | `tradeID`/`playerA`/`playerAName`; single-trade-in-progress guard (`this+0x274/0x275`) | H |
| 0xF5A | TradeOffer? | `HandleTradeOffer@0x0046cd10` | `playerA`/`playerB`/`goldA`/`goldB`/`funniesA`/`funniesB` + 2×6-slot item vectors | H |
| 0xD8 | — | `FUN_0046f510` (not renamed) | VillageEntered-gated; lookup+`NotifyQueue_FireAndClear`+erase on the `this+0x178` container | L — plate comment records the [HYPOTHESIS] (party/relationship "member left") |
| 0xD9 | — | `FUN_0046f380` (not renamed) | VillageEntered-gated; assigns an NComm net id to a `this+0x178` entry, fires notify twice | L — [HYPOTHESIS] "member joined, network-addressable" |
| 0xDA | — | `FUN_0046eb70` (not renamed) | NOT state-gated; get-or-create on `this+0x178`, no notify | L — [HYPOTHESIS] "request/invite" seed |
| 0xDB | — | `FUN_0046f4d0` (not renamed) | zero-payload; fires observer set at `this+0x8c` | L |
| 0xDC | — | `FUN_0046f4f0` (not renamed) | zero-payload; fires observer set at `this+0x98` | L |
| 0x12F | — | `FUN_0046d380` (not renamed) | reads `msgprt`+`rnid`, routes the raw message to a per-entry sub-handler found via `this+0x178` | L |

**AvatarProxy wire-format readers** (shared by 1001 EntityCreate / 1002 EntityUpdate and the 0xC1x/0xC8x
cases above — this is the "other players visible" payload, distinct from 1004 PlayerCreate's NPC-shaped
body; see `docs/IN_WORLD_PRESENCE.md` for the full field tables):

| Addr (`sadk_noav.exe`) | Name | Role |
|---|---|---|
| 0x00482c20 | `AvatarProxy_ReadDataBlocks` | reads 4-bit `dtblcks` dirty-block mask, dispatches to the 4 sub-blocks below |
| 0x004824b0 | `AvatarProxy_ReadLocationBlock` | `tick`+quantised pos/rot+`rnng`/`jmp` flags (self vs. remote branch) |
| 0x004825f0 | `AvatarProxy_ReadStyleBlock` | `name`+`trbgndr`+hair/skin/shirt/trouser+4×`addColor` |
| 0x0048abe0 | `AvatarProxy_ReadActiveItemsBlock` | 4 fixed equip slots, each via `AvatarProxy_ReadItemSlot@0x0048ab40` |
| 0x00481da0 | `AvatarProxy_ReadStatsBlock` | `lvl`/`exp`/`gold`/`glod` |
| 0x0048ac20 | `AvatarProxy_ReadInventoryBlock` | `sltcnt`-prefixed variable-length item list |
| 0x00481d50 | `AvatarProxy_ReadLevelExpBlock` | `lvl`/`exp` only (used by 0xC80) |
| 0x00481d30 / 0x00481d40 | `AvatarProxy_ReadActiveItemsShim` / `AvatarProxy_ReadInventoryShim` | thin forwarders used by 0xC1C-0xC1E |
| 0x0048f530 | `LobbyMessage_FinishRead` | idempotent stream-finalize, called at the end of every reader above |
| 0x00464300 | `NotifyQueue_FireAndClear` | generic: iterate a per-object callback list, fire each, then clear+free it |
| 0x004780c0 | `LobbyManager_RegisterAvatar` | registers a newly-created AvatarProxy's id with the LobbyManager singleton |

**RTTI class hygiene — DONE 2026-07-28 for 6 of 7; `AvatarProxy` deferred.** All 7 classes are
RTTI-confirmed under `LobbyComm::` (`.?AVAvatarProxy@LobbyComm@@` etc.), plus an 8th discovered in the
same pass: `LobbyComm::IAvatarDataBlock`, the shared base interface of `AvatarCreationBlockEx`,
`AvatarAppearanceBlockEx`, `AvatarStyleBlockEx`, `AvatarStatsBlockEx`, `AvatarActiveItemsBlockEx`,
`AvatarInventoryBlockEx`. **This is a separate, parallel serialization family from the
`AvatarProxy_ReadXBlock` free functions above** — it uses `NComm::MemoryStream` (not the LobbyComm
property-bag wire) via an 8-slot vtable (`Destructor`/`ReadFromBuffer`/`WriteToBuffer`/`Deserialize`/
`Serialize`/`GetVariant`/`GetSize`/`Clear`), most likely the avatar-cosmetics payload inside an NComm
`PlayerInformation`-style event during a match, not the village/lobby wire — so the "which reader
matches which class" question above does not apply; they were never the same functions. Struct
`IAvatarDataBlock` (8B) + `IAvatarDataBlock_vftable` (32B) created; all 27 member functions
this-typed/namespaced/renamed. Field widths `[PROVEN]` (read directly off each class's own
`Deserialize`), field names `[HYPOTHESIS]` (generic `fieldN`). Full slot table, per-class field
layout, and evidence: `decomp/RENAME_LIST.md` "2026-07-28 (cont.)". **`AvatarProxy` itself is
`[TODO]`, deferred on purpose:** its Class Hierarchy Descriptor shows it inherits
`LobbyComm::ActorProxy : LobbyComm::IActor` (a distinct, widely-shared actor interface used by 4+
other class hierarchies), not this Block family — its own 7-slot vtable (`0x007dd038`) needs a
dedicated pass rather than a rushed partial binding.

**Avatar render/observer chain — named 2026-07-31 (late), all `sadk_noav.exe`, applied in Ghidra:**

| Addr | Name | Role |
|---|---|---|
| 0x00458860 | `NotifyList_Subscribe` | generic observer-list subscribe; caller pushes a `{object, fn}` functor |
| 0x004324e0 | `NotifyList_Unsubscribe` | its mirror |
| 0x00503d00 | `CLobbyClient_SubscribeVillageConnObservers` | subscribes the CLobbyClient to ALL 18 village-conn lists (incl. `+0xbc`); only caller = `LobbyVillageEnterAction_Trigger`, right after conn creation |
| 0x00503ab0 | `CLobbyClient_UnsubscribeVillageConnObservers` | mirror; only caller = action `_Tick` on `bDone(+0x10)` |
| 0x00503620 | `CLobbyClient_UpdateAvatar` | dev name `Lobby::CLobbyClient::UpdateAvatar` — the `+0xbc` EntityCreate callback; creates/updates the avatar CLobbyObj |
| 0x00503940 | `CLobbyClient_OnEnterWorld_SpawnOwnAvatar` | `+0x104` callback (fired directly by `HandleEnterWorld`); spawns own avatar, sets run-mode 3 |
| 0x00503800 | `CLobbyClient_OnVillageLoginResult_RetryOrFail` | `+0x10` callback; silent retry when `bServerAssigned`, else `!LOGIN_FAILED_TEXT` dialog; sets `bDone` |
| 0x00503280 | `CLobbyClient_OnVillageLoggedOut` | `+0x1c`/`+0x28` callback; village-left teardown; sets `bDone` |
| 0x00503590 | `CLobbyClient_OnWorldTick_Throttled` | `+0x11c` callback (msg 1005), 250 ms-throttled time sync |
| 0x004704e0 | `VillageConn_OnUserCommLoggedIn_BuildOwnAvatarProxy` | one-shot on `UC+0x4`; fired value = **own avatar ID**; CharacterManager lookup ("WTF?! There is no avatar with that id…" on miss) → own proxy → `LM+0x554`, world login via `conn+0x34 vtbl+0x10`, `SetState(EnteringVillage=8)`, **`LM+0x54c = id` (PermID == own avatar ID)** |
| 0x00470660 | `VillageConn_OnUserCommLoginFailed` | one-shot on `UC+0x10`; fires conn `+0x10` with −1 |
| 0x0046c100 | `VillageConn_GetOwnAvatarProxy` | returns `LM(+0x158)→+0x554` |
| 0x004626c0 | `LobbyManager_SetOwnAvatarProxy` | builds a 0xE0 AvatarProxy from character data into `LM+0x554` (+ registry `+0x558`) |
| 0x004f6fd0 | `CLobby_CreateOwnAvatarObj` | CLobby vtbl+0xec; ⚠️ silent gate: needs `LM+0x554` set OR `CLobby+0x270 != 3` |
| 0x004f6de0 | `CLobby_CreateAvatarObjFromProxy` | remote path; template `"settler"`; logs "Could not create CLobbyObj." only on failed `new` |
| 0x004f6ca0 | `CLobby_CreateLobbyObj` | allocates 0x94 CLobbyObj, ctor, appends to `CLobby+0xa4` vector |
| 0x00502e60 | `CLobbyObj_Construct` | resolves the template's TYPE string: `"customize"`/`"character"`/`"none"` → visual object (or **none, silently**) |
| 0x004ffa80 | `CLobby_FindObjTemplateByName` | linear search of the template table at `CLobby+0x134 → +0x20/+0x28` (stride 0x60); **returns 0 silently if empty/missing** |
| 0x00508090 | `AvatarVisual_RefreshStyleModel` | rebuilds the avatar 3D model from proxy style bytes (`visual+0x760`) |
| 0x00445ac0 | `MiniGameMatchMakingDialog_Construct` | (bust of the old `+0xbc` candidate — it is the minigame dialog, not the avatar observer) |

Full narrative + the wall fork ("is the OWN settler visible?"): `docs/IN_WORLD_PRESENCE.md`.

### World clock + avatar movement ring (clean base `sadk_noav.exe`) [PROVEN 2026-08-01]

The clock the whole avatar-movement system runs on, and how the server's tick stream drives it.
Root-caused the avatar 3-second die-off: the stub never sent WorldTick(1005), so the client
world clock free-ran at an arbitrary phase (±32.7 s per machine/boot) vs our location tick16s.
ER: `engagement_records/2026-08-01_worldtick-clock-sync.md`.

| Addr | Name | Role |
|---|---|---|
| 0x0057b810 | `WorldClock_FrameUpdate` | per-frame: samples `g_dwWorldClock_RawMs` via `g_dwWorldClock_TimerProcAddr`, updates `g_dwWorldClock_FrameDeltaMs` |
| 0x0057b840 | `WorldClock_GetRawMs` | returns the raw sample |
| 0x0057b8d0 | `WorldClock_GetMs` | **the WORLD CLOCK**: `g_dwWorldClock_RawMs − g_dwWorldClock_Offset` |
| 0x0057b8e0 | `WorldClock_GetSeconds` | same, as float seconds |
| 0x0057b910 | `WorldClock_SlewToTick16` | `(tick16, tolMs)` — if phase error ≥ tol (shorter dir mod 65536), adjusts `g_dwWorldClock_Offset` so `GetMs() & 0xFFFF == tick16`; returns "slewed" |
| 0x0057b990 | `WorldClock_Reset` | zeroes; clock restarts at 0 |
| 0x00503590 | `CLobbyClient_OnWorldTick_Throttled` | `+0x11c` cb: `SlewToTick16(*tick, 0xFA=250 ms)`; on slew notifies `CLobbyClient+0x4` subject vtbl+0x18 with the new clock |
| 0x004f4d10 | `WorldClock_ReconstructTick16` | expands a wire tick16 to u64 ms: value ≡ tick16 (mod 65536) NEAREST `GetMs()` (hi dword 0) |
| 0x00519b20 | `AvatarMovement_PushWaypoint` | ring push (8 slots @ visual+0x28, stride 0x28); stamp = reconstructed+2000 ms; ONLY guard = null-position reject (no dedup, no monotonicity) |
| 0x00519d50 | `AvatarMovement_Tick` | per-frame (vtbl+4 of vtable 0x007e70c4): bracket search over the 7 ADJACENT ring pairs, `prev < t <= next`; bracket ⇒ VISIBLE (smooth unless gap > 2.0 s `DAT_007d435c` / dist ≥ 10.0 `DAT_007fa8d8` / prev pos null ⇒ snap-to-next); no bracket ⇒ snap to newest, HIDE iff `t − newest > 3.0 s` (`DAT_007d4360`; u64 ⇒ future-only stamps underflow = instantly hidden). Clock param = `WorldClock_GetMs` (trace-proven) |
| 0x0048f380 | `LobbyMessage_ReadBits64` | reader vtbl+0x20: reads N bits into a u64 (skips name reads when names flag set) |
| 0x0048f050 | `LobbyMessage_ReadBitsCore` | MSB-first positional bit reader. ⚠️ **SHIPPED BUG for >32-bit reads**: 32-bit `SHL` (CL masked &0x1f) + `CDQ` ⇒ the two halves ALIAS into the low dword, hi = sign-smear ⇒ 64-bit wire fields MUST carry a zero high dword (the stub masks the 1005 tick to u32) |
| 0x0088a610–0x62c | `g_dwWorldClock_*` | TimerProcAddr / RawMs / PrevRawMs (+0x624) / FrameDeltaMs (+0x628) / **Offset (+0x62c — the slew target)** |

### In-world chat: render chain + tincat3 CellManager (clean base `sadk_noav.exe`) [PROVEN 2026-08-02]

The full inbound path of a chat line, wire → pixels, mapped root-causing the LOCAL-chat black hole
(fix: `d07f437` — publish the zone cells as ChannelInfo). All claims live-verified (read-only
attach, ring-buffer dump) unless marked.

**SADK.exe side** (observer this = the village screen; chat widget EMBEDDED at `screen+0x1f0`):

| Address | Name | Note |
|---|---|---|
| 0x00480e30 | `UserCommConnection_ChatReceived` | dev name `LobbyComm::UserCommConnection::ChatReceived`; vtbl slot 4 of the `IChatChannelObserver` secondary vftable (`0x7dce94`) on the sub-object at `UC+0x38`. ⚠️ **Logs its scope BEFORE the `(cell, sender, text) != NULL` checks** — the log line does NOT prove processing. Then `LobbyManager_RegisterAvatar(senderId, name)` + fan-out on `UC+0x3c` |
| 0x00480990 | `UserComm_NotifyChatReceivedObservers` | copies the `UC+0x3c` notify list, calls every functor `(name, senderId, cell, text)`; UNCONDITIONAL — no cell gate |
| 0x00436180 | `VillageScreen_OnChatReceived_AppendToTab` | the only screen observer on `UC+0x3c` in-world. Drops iff ignore-list verdict == 2 or `VillageConn_ChatCellToTabId` == 0; `senderId == conn+0x160` ⇒ "[SYSTEM]" + popup path; else "[name] !LOBBY_CHAT_FROM : text" → AppendLine |
| 0x0046d170 | `VillageConn_ChatCellToTabId` | walks the `conn+0x164` map for value == cell: key 0xFF→tab 1, 0xFE→tab 3, **key < 0x0E→tab 2**; ⚠️ zone keys 14/15 fall through (LOCAL unreachable for them); no match ⇒ 0 = drop |
| 0x0046c600 | `VillageConn_GetSystemSenderId` | returns `conn+0x160` (live: 0) |
| 0x004389d0 | `VillageScreen_OnEnter_SubscribeAndBuildChatTabs` | subscribes `{screen,0x436180}`→`UC+0x3c` (+ siblings 0x432930→`+0x48`, 0x432c60→`+0x54`); AddTab 1=GLOBAL 2=LOCAL 3=MINIGAME 4=SETTLERS, DisableTab(3,4), **SelectTab(2)** = LOCAL is entry-active; welcome/help lines land in the ACTIVE tab |
| 0x00439410 | `VillageScreen_OnLeave_UnsubscribeAll` | exact mirror (verified in asm — the `villageConn+0x128` functor is `0x4323d0`, NOT the chat observer) |
| 0x004ae200 | `ChatWidget_AppendLine` | (widget, tabId, senderId, str, color): 0=drop, −1=all tabs, −2/active=active ctx, else find-by-id needing `ctx != 0`; NO enabled check |
| 0x004ae450 | `ChatWidget_AddTab` | entry `{id, ctx, button, enabled@+0xc}` ×0x10 in vector @`widget+0x3338/+0x333c`; first added becomes active (`+0x32d8` ctx, `+0x32dc` id) |
| 0x004ac200 | `ChatWidget_DisableTab` | clears entry `+0xc`; clears active if it was active |
| 0x004ac290 | `ChatWidget_SelectTab` | (id, force): needs `ctx != 0` && (`enabled` \|\| force) |
| 0x004adb20 | `ChatTabCtx_AppendWordWrapped` | wraps via widget fonts, one RING SLOT per segment. Ring (ctx): `+8` slot-ptr array, `+0xc` cap (live: 8), `+0x10` head, `+0x14` count. Slot (0x24 B, heap): `{senderId@+0, color@+4, string@+8: SSO buf@+0xc, size@+0x1c, cap@+0x20}` — layout live-verified |
| 0x004354d0 | `Chat_ParseSlashCommand` | only acts on texts starting `/`; command table @`0x0087a08c` (stride 0x28); ret 4 = emote (ids > 5 append an EMPTY string = invisible); ret 0 = plain text |
| 0x004624b0 | `LobbyManager_GetCharacterManager` | returns `LM+0x140` (embedded) |
| 0x004780c0 | `LobbyManager_RegisterAvatar` | (already named) upserts `CharMgr+0x1a0` id→name and `+0x1ac` lc-name→id |

**tincat3.dll side** (`TinCatModules::CellManager` — the chat-cell wire module):

| Address | Name | Note |
|---|---|---|
| 0x1000aa80 | `Handler_DispatchPayloadByMagic` | payload magic 0x62 → registry at `handler+0x34` keyed by the 2nd u16 (our "type" field, 0) → observer vtbl+0x20 |
| 0x1000ef30 | `CellManager_DispatchInboundMessage` | logs "CellManager: Received message: %d"; switch on chat id: 0=PublishCell 2=Message 3=Reply 9/10=Joined/Left 11=StatusReply |
| 0x1000ee30 | `CellManager_ProcessPublishCell` | our ChannelInfo: unknown cell id ⇒ CREATE cell record (insert into the registry); known ⇒ update props + event 4 |
| 0x1000e4a0 | `CellManager_OnChannelJoinedLeft_RequireKnownCell` | ⭐ **THE LOCAL-CHAT GATE**: looks the cell up in the registry (`this+8`) FIRST; miss ⇒ `StatusReply(status=2)` + NO joined-event. **A cell must be published via ChannelInfo before its join can succeed** — EnterWorld(1000) pairs feed only the SADK-side map, not this registry |
| 0x1000df60 | `CellManager_OnReply_QueueChatEvent` | our chat relay: queues event 0xd `{from, cell, msgid, data, ispropset}` with NO cell lookup — the null args reaching ChatReceived for an unknown cell are built downstream in the event drain [HYPOTHESIS — drain site not yet decompiled; everything else in this section is PROVEN] |
| 0x10038fa0 | `CellManager_FindCellById` | registry lookup used by the join handler |
| 0x1000da20 | `CellManager_QueueEvent` | event-queue append (types seen: 4, 0xd chat, 10/11 joined/left, 0xe status) |
| 0x1000e250 | `CellManager_GetNextEvent` | the drain's pull ("no event was in queue" string) |

⚠️ Two-layer join-confirmation trap: the stub answers a join with ChannelJoined(9) **and** StatusReply(11).
When the manager rejected the 9 (unknown cell), the 11 still queued its own event 0xe — which is what
latched SADK's `conn+0x225` zone byte and made the join LOOK confirmed at the upper layer while the
manager had no cell. "Join confirmed" at the SADK layer therefore proves nothing about the CellManager.

### The NPC system — PlayerCreate(1004) / NPCProxy [PROVEN 2026-08-02]

⛔ **msg 1004 is not "the player record" — it is the NPC spawn.** `HandlePlayerCreate@0x0046f8c0`
allocates a **`LobbyComm::NPCProxy`** (0x120 B, vftable `0x7dc7d8`, ctor `NPCProxy_ctor@0x0047b4d0`)
into the container at `VillageServerConnection+0x174` (distinct from the avatar container +0x170),
parses it with `NPCProxy_ReadRecord@0x0047b5c0`, then fires the `+0x38` observer —
`CLobbyClient_OnPlayerCreate_SpawnNpcObj@0x005031a0` — which builds the visible object at once.
No waypoint stream is involved (contrast the 1001 avatar path).

**Wire layout** (`NPCProxy_ReadRecord`, bit-packed like every LobbyMessage):

    id 32 · npcdesc STRING · [LobbyMessage_ReadLocationBlock@0x0048f670: posx 11 · posy 11 ·
    posz 11 · rot 7 · zone 4] · hrclr 4 · sknclr 4 · shrtclr 4 · trsrclr 4 · npcidx 4 ·
    bdyprt 4 · npctyp 2 · actcnt 8 · actcnt × (act 8 · actChat STRING)

⚠️ No tick / ghost-zone / running / jumping — that is the 1001 AvatarLocation block, not this one.
⚠️ Colours are 4-bit NIBBLES here; the 1001 AvatarStyle block writes the same fields as full BYTES.

**Field semantics:**

| Field | Lands at | Meaning |
|---|---|---|
| `npcdesc` | +0x88, +0x10, lowercased +0x2c | the label / display name |
| `npcidx` | +0xc0 | ⭐ **THE model index for NPCs** — `NPCProxy_GetModelIndex_npcidx` (vtbl+0x1c) |
| `bdyprt` | +0x48 | the AVATAR tribe/gender byte; **the NPC branch never reads it** ⇒ no effect on an NPC's look |
| `npctyp` | +0xc4 | `CLobby_CreateNpcObjFromRecord_byNpcTyp@0x004f6ea0`: **1 = "settler"** person, **2 = "letterbox"**, else **NULL (invisible)** |
| `hrclr`/`sknclr`/`shrtclr`/`trsrclr` | +0x49..+0x4c | model tint (see the style refresh below) |
| `act`×3 | +0xa8/+0xac/+0xb0 | ⭐ **a LobbyAction id** (table below) — the dialog the NPC's button opens |
| `actChat`×3 | +0xc8 + i×0x1c | [TODO] button label or spoken line — `VillageScreen_UpdateActionButtons@0x00433f60` decompiles unreliably and was NOT guessed at |

**⭐ The LobbyAction enum** (`VillageScreen_SetActionButtonToLobbyAction@0x004325b0` — the string
table IS the enum; it fills one of the three village-screen buttons at screen+0x3560/+0x3564/+0x3568):

| `act` | Action | | `act` | Action |
|---|---|---|---|---|
| 0, 19 | `LobbyAction_None` (hidden) | | 8, 18 | `LobbyAction_HostGame` |
| 1 | `LobbyAction_HairColor` | | 9 | `LobbyAction_ListGames` |
| **2–6** | **`LobbyAction_MinigameMatchmaking`** | | 10 | `LobbyAction_HoF` |
| 7 | `LobbyAction_Mailbox` | | 11 | `LobbyAction_OpenShop` |

(Everything else falls through to `None`. Sending emote ids 2/4 as `act` is what made every NPC in
the stub's first cast open the minigame dialog — live-observed 2026-08-02.)

### Actor model + colour selection — `AvatarVisual_RefreshStyleModel@0x00508090` [PROVEN 2026-08-02]

The visual reads its owning proxy (`visual+0x760`) through a shared accessor family and branches on
the **ActorID type discriminator at proxy+8**: **1 = AvatarProxy** (`ActorProxy_AsAvatarOrNull_type1
@0x0046b6c0`), **2 = NPCProxy** (`ActorProxy_AsNpcOrNull_type2@0x0046b6d0`).

- **NPC (type 2):** model index = `npcidx` verbatim (vtbl+0x1c); gender forced 0; the
  tribe/bodypart math is skipped entirely.
- **Avatar (type 1):** `bodypart = proxy+0x48 >> 4` (`ActorProxy_GetBodyPart_hiNibble48`),
  `gender = proxy+0x48 & 0xF` (`ActorProxy_GetGender_loNibble48`, boolean), `tribe` = vtbl+0x18
  clamped to 1..5, then **model = bodypart + (tribe − 1) × 3** (bodypart ≥ 3 ⇒ `(tribe−1)×3 + 2`).
  ⇒ **`trbgndr` packing RESOLVED: high nibble = body part, low nibble = gender.** Sending 0 pins
  every avatar to the same default model — which is exactly what the stub did until now.
- **Colours (8 slots)** feed the tinting calls `FUN_004fcc90`/`FUN_004fcc10`:
  +0x49 hair · +0x4a skin · +0x4b shirt · +0x4c trouser · +0x4d..+0x50 addColor1..4.
  ⚠️ `NPCProxy_ctor` initialises only +0x48..+0x4c, and 1004 carries no addColor fields, so an
  NPC's +0x4d..+0x50 are whatever the raw `malloc(0x120)` left there. [TODO] whether the NPC model
  path consumes those four slots at all.
- The whole refresh is skipped unless the model index, gender or one of the 8 colours CHANGED
  (compared against the cached copy at visual+0x698/+0x69c..+0x6b8).

[TODO] npcidx→appearance and the colour palette indices are not derivable from code — they live in
the (encrypted) game data. Eyeball or asset-decrypt territory.

### Lobby string encoding = UTF-8, and the shop [PROVEN 2026-08-02]

⭐ **Every LobbyMessage string on the wire is UTF-8.** The string reader at LobbyMessage
vtbl+0x30 (`FUN_004900a0`: 8-bit length + N chars) passes its bytes to `FUN_00487620`, which is
exactly `MultiByteToWideChar(0xFDE9 = CP_UTF8, …)` → `WideCharToMultiByte(CP_ACP, …)`. The same
converter is applied to the NPC `npcdesc`, the avatar `name` (`AvatarProxy_ReadStyleBlock`) and
BOTH chat strings (`UserCommConnection_ChatReceived`). Sending ISO-8859-15 put a bare `0xE4` on
the wire for "ä" — invalid UTF-8 ⇒ U+FFFD ⇒ rendered **"H?ndler Hinnerk"** in-game
(live-observed, screenshot 2026-08-02). The 8-bit length prefix counts **bytes**, so multi-byte
characters eat into the 255 limit. [TODO] whether the tincat PropertySet string path
(`tincat.str_field`, still ISO-8859-15) wants UTF-8 too — same converter is applied downstream on
the chat nick, so probably yes; unproven, so unchanged.

**LobbyMessage reader vtable (`0x7db594`) — slots identified so far:**

| Slot | Function | Reads |
|---|---|---|
| +0x10 | `FUN_0048f280` | N bits → **u16** (used for `StockCount`, 16 bits) |
| +0x18 | `FUN_0048f300` | N bits → u32 (the workhorse) |
| +0x20 | `LobbyMessage_ReadBits64` | N bits → u64 (⚠️ shipped >32-bit aliasing bug) |
| +0x30 | `FUN_004900a0` | STRING: 8-bit len + chars, **then the UTF-8→ANSI conversion** |
| +0x34 | `FUN_0048ffc0` | STRING (raw; the caller converts — e.g. npcdesc, avatar name) |
| +0x40 | `FUN_0048ff50` | 32 bits, **then REVERSES the 4 bytes** ⇒ a little-endian **float** inside the big-endian bit stream |

**ShopInventoryData — msg `0xE11`, `HandleShopInventoryData@0x004706b0`:**

    NPCID 32 · ShopID 32 · ShopName STRING · SellMod 32(byte-swapped float) ·
    StockCount 16 · StockCount × { ItemID 32 · Buy 32 · Sell 32 }     (item reader FUN_0046b360)

⭐ **Its ARRIVAL OPENS THE DIALOG — it is a reply, not a stock cache.** The `villageConn+0x128`
observer `FUN_004323d0` (subscribed by `VillageScreen_OnEnter`) builds an `ActorID{type 2, NPCID}`,
passes it with ShopID/ShopName to the ShopDialog at `screen+0x35d4` (`FUN_0045d580`), and on success
calls the dialog's **vtbl+0x2c show** method, snapshots the camera and enables `screen+0x3584`.
⇒ Pushing 0xE11 at world entry pops the shop open unbidden (live-observed 2026-08-02) — a
false-looking "working shop". The real server sent it only in reply to a shop-open request.

⏳ **OPEN BLOCKER:** clicking a shop NPC puts **nothing** on the wire (live-verified twice from the
stub journal — only keepalive Pongs across a click, and one lone leave-village msg 2002 in the whole
session). So the client's request path is never reached, and no server reply can be triggered.
Resolving it needs a LIVE trace of the OpenShop button handler: static reading of
`VillageScreen_UpdateActionButtons@0x00433f60` bottoms out in unreliable decompilation (the
selection-type branches use registers Ghidra cannot track). [TODO] `ItemID` values live in the
encrypted item tables and are not derivable from the binary.

**Hall of Fame is a WEB VIEW, not a protocol feature**: `HallOfFameDialog` reads the config keys
`HallOfFameURL%d`, `HallOfFameURL%d_AppendPermID`, `HallOfFameURL%d_AppendCharname` and opens the
resulting URL. The official URLs are dead, hence the blank/broken panel — nothing the lobby
protocol can fix; it needs those config keys pointed at a live page.
