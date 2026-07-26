# MP match P2P transition — how the client leaves the lobby and enters the host's game server

Status: 2026-06-14, static RE on the magazine build (`sadk_noav.exe`, base 0x400000). Claims are
`[PROVEN static]` unless tagged `[HYPOTHESIS]`. Companion to `docs/MATCH_START_HOST_WALL.md` and
`docs/MATCH_WORLD_LOGIN.md`.

## TL;DR
The match is a **P2P NComm session**: the HOST runs a **TinCat host** network; the JOINER connects to
it as a **TinCat client**. `EnterWorld(1000)` is the LOBBY-village entry and is **NOT** the match path —
`HandleEnterWorld @0x46f670` reads only `Worldname` (display), a 32-byte `ServerPerm` token (no
connect-use), and chat channels; there is **no game-server address** in it. (That's why the s42 1000
re-send fix unfroze match-start but dropped both clients back into the lobby village = the "clone".)
The real transition runs through the **NComm Manager** + a dedicated **`GameServerConnection`** class.

## The complete match-start state machine — DEFINITIVE [PROVEN static]

The master variable is the **NComm `EManagerState` (Manager+0x1c: 0=None, 1=NetworkStarted, 2=Connected)**,
read via `FUN_00408430`. The per-frame **`LobbyGameScreen_Update @0x435980`** drives the whole transition,
in this order each frame:

1. **Referee pump** (armed by `LobbyGameScreen_OnVillageConnectionLoggedOut` → `this+0x3624`): if armed →
   `RefereeServerConnection_Login` (gated on the StartLoading flag `NComm+0x3cc` + `this+0x3625`, after a
   `this+0x3628` countdown). **ABORTS the match** (`Game_SetRunMode(2)` + `NComm_Manager_Shutdown`) if
   `this+0x362c > 5` (5 tries) **OR `EManagerState == 0`**. This is the s39.5 ~13s abort.
2. **Host match-server arm** (`FUN_00433f60`, per-frame after the referee pump): when
   `EManagerState == 0` (NComm fully torn down) and a village-server is selected, it sets button-0
   state = 8 (`FUN_00432180(states,8,0)`) + the deferred flag (`screen+0x3638`/`[0xd8e]`). Next frame
   `LobbyVillageScreen::OnLeaveVillage` sees flag + button-0==8 → `FUN_00434230(this,0)` → **case6 →
   `FUN_0046aaa0`**: `Shutdown → StartUpNetwork(4, TinCat host) → ConnectAndJoin (BroadcastGameInfo) →
   AssignServer(189 type5/sub1)`; sets `villageList+0x9c=-2`. ⇒ HOST RAISES ITS TINCAT-HOST MATCH SERVER
   (EManagerState 0→1→2) and registers its address with the lobby. **It is state-driven, not a click.**
3. **Joiner connect:** lobby relays the host address (`GameServerAssigned`/170) → a mode-3
   `GameServerConnection` (TinCat client) → connect → **login `NE_UserInformation (0x30001)`** carrying
   BuildVersion + BuildChecksum + static-data MD5; the host KICKS on mismatch (the install-parity gate).
4. **World load:** when `EManagerState == 2` (Connected) the host's Update activates the Game screen
   (`FUN_004ac170(this+0x1f0,4,1)`) → `nMenu_Game::OnEnter → BuildWorldSequence →
   SP_BuildScene_LoadTerrainXml (GameSystem) + SP_LoadMapFile_Orchestrator (the map)`. The P2P
   game-event stream (`Manager_HandleNCommEvent @0x40e560`) carries `NE_GameInformation` (0x30003 →
   `SP_CheckMapExists`; map must exist locally), `NE_StartLoading (0x30012)` → sets StartLoading flag
   `NComm+0x3cc`, `NE_GameLoaded (0x30004)`, `NE_StartGame (0x30005)`.

**So "the game begins loading the login"** = the NComm reaches EManagerState 2 (Connected = P2P match
session up), the joiner logs in via `NE_UserInformation` (checksum-gated), then `NE_StartLoading` flips
the StartLoading flag → `OnEnter` builds the terrain.

**Why ours never starts [the crux]:** the host raises its match server ONLY when EManagerState is driven
to **0** (the `FUN_00433f60` arm). At our match-start the NComm is still **connected to the stub-lobby
village (state != 0)**, so the host never arms `FUN_0046aaa0` → never reaches state 2 → no world load;
`EnterWorld(1000)` (lobby village) is orthogonal. The needed chain: tear the lobby NComm down to state 0
→ host `FUN_0046aaa0` (TinCat host + AssignServer) → stub replies `GameServerAssigned` with the host
addr → joiner `GameServerConnection` (mode 3) → EManagerState 2 → world load. The referee must log in
without the pump observing state 0 (else it aborts). **Open: exactly what should drive the host's lobby
NComm to state 0 at match-start (host CloseSession / a stub-driven village-conn close), and the stub's
AssignServer→GameServerAssigned address relay.**

## NComm Manager — the transport state machine [PROVEN]
`NComm_Manager` = the net driver. `this+0x3c8` = mode/ManagerState; `this+0x340` = transport object;
`this+0x1c` = EManagerState (0 None → 1 NetworkStarted → 2 Connected).

- **`NComm_Manager_StartUpNetwork(mode)` @0x40a9a0**: asserts state==None; stores `mode` at +0x3c8;
  builds the transport by mode → `transport->vtbl[4](isHost, flag)`; on success state→1, max-players
  (`+0x34`/`+0x38`) = 1 (mode 0) or 4 (modes 1-4):
  | mode | transport | (isHost,flag) | role |
  |---|---|---|---|
  | 0 | 4-byte stub (`FUN_0041ed20`) | (1,0) | **loopback/local**, max 1 → SP/skirmish |
  | 1 | TinCat | (0,0) | client |
  | 2 | TinCat | (1,0) | host |
  | 3 | TinCat | (0,1) | **client ← JOINER** |
  | 4 | TinCat | (1,1) | **host ← HOST** |
- **`NComm_Manager_ConnectAndJoin` @0x40ad60**: asserts state==1; builds + sends event
  **`0x30001` (NE_UserInformation = the game-logon)** carrying **`NComm_GetBuildVersion` +
  `NComm_GetBuildChecksum`** (the static-data checksum the P2P join gates on — see
  `[[mp-join-blocker-static-data-checksum]]`); state→2; then for **host modes (0/2/4)** →
  `NComm_BroadcastGameInfo`, for **client modes (1/3)** → connect via `transport->vtbl[0x10]`.
- **`NComm_Manager_Shutdown` @0x40b410**: tear down (state→None).

## The two sides [PROVEN]
- **HOST = `FUN_0046aaa0`**: `Shutdown → StartUpNetwork(4, TinCat host) → ConnectAndJoin`
  (BroadcastGameInfo + logon) → `AssignServer(189 type5/sub1)` registering the host's address with the
  lobby; sets `villageList+0x9c = -2` (pending). ⇒ the host BECOMES the match server. Its only callers
  are **UI/event-gated and none fire in the both-ready auto-start** (3 live captures, 0 hits):
  `LobbyVillageScreen::OnLeaveVillage @0x437760` case0 (leave-village popup confirm),
  `FUN_00434230` slot-dispatch case6, `FUN_004588e0` widget `[0x2d5]`.
- **JOINER = `LobbyComm::GameServerConnection::OnLoggedIn @0x48edf0`** (vtable@0x7deaf0 slot+0x14,
  `LobbyGameServerConnection.cpp`): after the client logs into the host's game server
  (CheckVersion → token → 153, same pattern as every other conn) → `StartUpNetwork(3, TinCat client)`
  → `ConnectAndJoin` (connect + logon). ⇒ the joiner CONNECTS to the match server.

## World-build (terrain) vs transport — an unresolved tension [PROVEN static + open]
The 3D world BUILD (map terrain + `nMenu_Game::OnEnter`) runs through two entries, **both of which call
`StartUpNetwork(0)` = LOOPBACK** (not a TinCat host/client transport):
- `AppState_EnterWorld_FillDescriptorAndCallOnEnter @0x5d9fd0` — the `+0x7c`-gated FramePump build:
  `GameLoadDescriptor_SetMapName` (map from `nMenu_System+0x68`) → `Shutdown → StartUpNetwork(0) →
  ConnectAndJoin` → build player/slot list → active screen = Game (+0x3c) → `nMenu_Game::OnEnter`
  (vtbl[0x84]). Per `[[world-build-model-clean-binary]]` (s38) MP never sets `+0x7c`.
- `FreeGamePanel_TriggerMPWorldBuild @0x5e7350` — also `Shutdown → StartUpNetwork(0) → ConnectAndJoin`
  → OnEnter.

So the world **build** paths use a **loopback** NComm, while the **match** transport is a **TinCat**
host (`FUN_0046aaa0`, mode 4) / client (`GameServerConnection`, mode 3). These are set up by *different*
code. **The key open question:** how does a networked-MP host compose them — build the terrain (loopback
OnEnter) AND keep/raise a TinCat-host NComm so the joiner can connect? (Either the MP build is a
different/parameterized path, or the TinCat transport is (re)established around the loopback build.) This
must be untangled before the match world can come up networked.

## Host game-server assignment — the `+0x9c` gate, delivery PROVEN end-to-end [PROVEN static]

The host's "Connecting to Game Server" dialog spins on `villageList+0x9c` (villageList = LobbyManager+0x54,
a `LobbyVillageServerList`). The full proven lifecycle:

1. **Self-drive to state 0** — `FUN_00468410` (callers `FUN_00457f00` dialog-button + `FUN_00452d90`
   wrapper): if NComm is up (`EManagerState != 0`) but **not host-mode-4** (`FUN_004890b0 != 4`) →
   `NComm_Manager_Shutdown` (EManagerState→0) + `villageList+0x9c = -1`. **No external trigger needed —
   the host tears its own NComm down whenever it isn't already the mode-4 match host.**
2. **Arm** — `FUN_00433f60` (per-frame from `LobbyGameScreen_Update`): `EManagerState == 0` + village
   selected → `FUN_00432180(states,8,0)` (button-8) + deferred flag.
3. **Bring-up** — `OnLeaveVillage` → `FUN_00434230 case6` → **`FUN_0046aaa0`** (gate `+0x9c==-1`):
   `Shutdown → StartUpNetwork(4) → ConnectAndJoin → AssignServer via villageList+0x6c->vtbl[0x20] with
   server_type=5, server_subtype=1` (decompile-confirmed: the literal `…,5,1,…` args); on send-success
   `villageList+0x9c = -2` (pending).
4. **Delivery (PROVEN both sides)** — the lobby's reply is a `GameServerData(170)`. tincat3
   **`GameServerManager_OnGameServerAssigned@0x10021520`** (ticket cat 0x108) discriminates on the
   descriptor: `desc+0x28==4 && desc+0x29==5` (type4/sub5) → REFEREE branch (→ `SetRefereeServerAddress`
   → `LM+0x580`); **everything else → the default sink `this->4->vtbl[0x28]`**. With the
   `LobbyVillageServerList` vtable base `0x7daf8c`, **`vtbl[0x28] = 0x469ad0 = LobbyServerList_GameServerAssigned`**
   (and `+0x2c = 0x469be0 = AssignGameServerResultReceived`).
5. **Clear** — `GameServerAssigned(villageList, serverDesc)`: `assignedId = *serverDesc` (the 170's
   server_id), fires the pending-assign callback `villageList+0xa0(assignedId)`, then
   **`villageList+0x9c = 0`** → dialog completes, host proceeds with the assigned game server.
   (`AssignGameServerResultReceived` is the ACK: on `errorCode!=0` it fires the callback with the failure
   sentinel and clears `+0x9c`; success is silent and the assignment itself arrives via step 5.)

## The gap — why no match [PROVEN] + the precise fix
The host emits `AssignServer(189) server_type=5/server_subtype=1`, but the stub's `_h_assign_server`
**only special-cases the referee (type4/sub4 → 170 type4/sub5)**; for `type5/sub1` it falls through to
`UsercommServerData(192)` — the *UC/chat* server, which does **not** route through
`OnGameServerAssigned`, so `+0x9c` never clears and the host parks on "Connecting to Game Server".

**Fix (exact parallel to the proven referee delivery, `[[referee-delivery-proven-live]]`):** on
`AssignServer(189) type5/sub1`, reply a `GameServerData(170)` for the host's game server — a real
`server_id`, the host's address, `server_type/subtype` **anything but 4/5** (use the game's 5/1),
echoing the request `ticket_id` (→ cat 0x108). tincat3 routes it non-referee → `GameServerAssigned` →
clears `+0x9c`. This is a stub wire-change ⇒ Engagement Record + live verification (the referee fix set
the precedent: `engagement_records/2026-06-13_referee-assign-170.md`).

> `EnterWorld(1000)` is orthogonal: it re-enters the LOBBY village (the "clone"). The match world comes
> up via this assignment → P2P → `EManagerState==2` → `nMenu_Game::OnEnter`, **not** via a village 1000.
> The s42 1000-resend (`force=True`) therefore masks rather than fixes — revisit once the 170 assign lands.

## Next
1. **What is supposed to trigger the host's `FUN_0046aaa0` at match-start** — an NComm/lobby event, or a
   leave-village popup auto-opened by a message? (Maintainer: it's protocol-driven, not a manual click.)
2. The **stub's role**: handle the host's `AssignServer` → reply `GameServerAssigned` with the host's
   address; confirm the joiner then builds a mode-3 `GameServerConnection` to it.
3. Locate the **`GameServerConnection` create/connect** call site + the host-address source; map the
   host↔joiner P2P handshake end to end.
