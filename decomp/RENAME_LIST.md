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
