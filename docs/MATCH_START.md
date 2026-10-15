# Match start — pre-game room → loading the map → playing

How the **client** leaves the pre-game room and starts the match, and what the server must answer. All
addresses are in `sadk_noav.exe` (`S`) unless marked `T` (`tincat3.dll`). Tags: `[PROVEN]` = address plus
live evidence (hosted matches against the stub since 2026-07-27: `lobby/sadk_lobby/referee.py`, and in
`lobby/sadk_lobby/dispatch.py` `_h_assign_server`, `_h_connection_data`, `_h_send_token`,
`_h_send_game_data`); `[known]` = read at the address; `[TODO]` = open.

Match start is **referee-gated**: the load starts in the handler of the referee's
`RegisterGameResult(0xDB8)` (S 00431800). The `GameSeed` that message carries only seeds the chest
contents (Phase 2).

Names: the lobby root object is `LobbyComm::System` (`g_pLobbyManager`; called LobbyManager in older
notes; `LM+0x..` is an offset inside it). The 3D village screen is `LobbyMenu::WorldScreen` (called
LobbyGameScreen in older notes).

---

## The big picture (sequence)

```
  ALL clients (host + joiners):
   NE_StartLoading (NComm 0x30012) sets NComm_Manager.cStartLoading (+0x3cc)
   the client sends village msg 2002 (leave village); the server answers 1006 {0xDEADBEEF};
   the client logs the village transport out; the village conn reports LoggedOut (+0x1c)
        → WorldScreen::OnVillageConnectionLoggedOut@0x4316c0
            ├ observer?                         → Hide (vtbl+0x30), nothing else
            ├ NComm active and cStartLoading?   → ARM referee login
            │                                     (+0x3624=1, +0x3625=1, +0x362c=0, +0x3628=0x10)
            └ otherwise                         → NComm Shutdown, clear the arm flags,
                                                  back to the avatar screen (RequestScreen(2))

   per frame: WorldScreen::Update@0x435980  (the referee-login pump, while +0x3624 is set)
        tries > 4, or NComm state 0 → ABORT: clear the flags, RequestScreen(2), NComm Shutdown
        armed and delay == 0        → RefereeServerConnection::Login(LM+0x490, local perm id); +0x3625 = 0
        armed and delay > 0         → delay -= 1
        LoginSuccess(0xDCA)  → refConn+0x80 → WorldScreen::OnRefereeLoginSuccess_RegisterGame@0x432240
                               sends RegisterGame(0xDB6)            ─────────────► REFEREE
        LoginFailed(0xDCB)   → refConn+0x8c → tries += 1, re-arm, delay = tries*8 + 16
                                              RegisterGameAck(0xDB7), RegisterGameResult(0xDB8) ◄──

   LOAD KICK (success branch of 0xDB8):
     WorldScreen::OnRefereeRegisterGameResult@0x431800 (gameId, GameSeed)
        NComm_Manager::SetGameSeedIfState2(GameSeed)
        SetupGameDialog::SetupSession(game information)   fills the load descriptor
        clear +0x3624 / +0x3625
        Lobby::CLobby vtbl+0x2c RequestModeTransition(1)  starts the match
```

Every client whose WorldScreen is active subscribes these observers (`Activate` has no host check), so
host and joiners both log in to the referee and both send `RegisterGame` `[PROVEN]` (0xDB6 arrived from
both clients in the live run). Neither the arm nor the pump has a ranked branch: ranked and unranked
matches both go through the referee, and `RankedGame` is only a field of `RegisterGame` `[known]`.

---

## What the server must do `[PROVEN]`

The steps in time order. Every failure on this path is silent: the client accepts the frame, keeps the
socket open and logs nothing (the one exception is in step 3). Wire layouts: `docs/message-catalog.md`
("AssignServer routing", "LobbyMessage bodies", "Referee / match arbiter", "Leave").

1. **Assign the referee at lobby login: one `170` with server type 4 / subtype 4, never 4 / 5.** Once the
   lobby state passes 5, `LobbyComm::System::StatePump_Tick` S 00464ee0 sends `189 AssignServer` (4, 4) on a
   ticket of request type 0x108. tincat3's `GameServerManager::OnGameServerAssigned` T 10021520 routes the
   answering `170` by its descriptor: type 4 / subtype 5 goes to the RankingManager (`ConnectRankingServer`
   T 10029a20), which dials but never tells the game; any other pair reaches `ServerList::GameServerAssigned`
   S 00469ad0 → `SetRefereeServerAddress` S 004625d0 (`LM+0x580` = server id, `LM+0x588` = 60000 ms).
   - The sign that the latch worked: the client sends the 189 again exactly every 60 s for the rest of the
     session. `StatePump_Tick` repeats the request only when `LM+0x588` runs out, and only
     `SetRefereeServerAddress` arms it, so after a failed first assign no 189 follows in that process.
   - With 4 / 5, `LM+0x580` stays 0, the `RefereeServerConnection` gets no transport (`refConn+0x34` = 0)
     and its `Login` does nothing at match start (TTD trace of a host, 2026-07-27).
   - Exactly one `170`: the first reply consumes the 0x108 ticket. A 4 / 5 and a 4 / 4 frame on the same
     ticket lost the latch (no 60 s retry followed).
   - Only `server_id` is read from this `170`; keep the id stable (message-catalog H10).
2. **Answer the village leave with `1006 {0xDEADBEEF}`, never with `1000` and never by closing.** At match
   start every client sends `2002 {0xAFFEDEAD}` once (`SendLeaveVillageRequest` S 0046bde0, state 10); the
   room dialog's `Update` S 00457a00 starts it once `cStartLoading` is set while the state is 9 `[known]`.
   State 10 has no timeout. The stub answers with one `1006` at once and a second one when the player's UC
   socket has closed (`village-and-character-protocol.md` §7). The logout ends in `HandleLoggedOut`
   (state 11), whose LoggedOut observers include `OnVillageConnectionLoggedOut`, the arm of Phase 3.
   - `EnterWorld(1000)` instead sets state 9 again (`HandleEnterWorld` S 0046f670): both clients stay in the
     lobby world and the match never loads.
   - Closing the village socket takes the Disconnected exit: `!CONNECTION_LOST_TEXT`, no referee arm, and
     at match start both players are thrown out.
   - No answer leaves the client in state 10.
3. **Give the referee connection its address with `222`.** `InitRefereeServerConnection` S 00462910
   registers the latched id with the ConnectionManager (vtbl `+0x38`, T 100196b0: a new connection keyed by
   the server id at `conn+0x1c`, with an empty address; 0xCD when it exists) and binds it. When `Login`
   opens that connection at match start, the per-server-id handler asks the lobby with
   `221 RequestConnectionData {server_id}` (T 10023af0). The answer `222 ConnectionData` is the only message
   that sets a server-id connection's address: `HandlerLobby` T 10023cc0 finds the connection by server id
   (T 10019570) and fills `conn+0x14` (host) and `conn+0x18` (port), and `ConnectionReal::Connect`
   T 100309d0 dials from those two fields only `[known]`. A `170` does not address a connection, and a `222`
   naming another listener's port makes the client dial that listener. The village connection gets its
   address the same way. Without an address the client's own `LobbyComm.log` shows
   `COMM_LAYER_ERROR_CANNOT_CONNECT - TinCat failed to start connection` from `LobbyManager.cpp` line 907
   (`LobbyComm::System::OnLoginFailed`, line store at S 00464aeb) and `LobbyBaseConnection.cpp` line 119.
4. **Push `LoginSuccess(0xDCA)` after the referee connection's `153`.** The referee connection logs in like
   every server-id connection (188 → 42, 211 → 212, 213 → `153 AddResult`). `RefereeServerConnection::Login`
   S 004793f0 only opens the channel and sends no request, so nothing asks for the login result: the server
   pushes it (the stub 0.5 s after the `153`). `PermID` must be that client's own perm id:
   `LoginSuccessReceived` S 0047ac20 compares it with `LM+0x54c` (S 0047ad09) and returns on a mismatch
   before the `+0x80` fan-out that sends `RegisterGame`. A `LoginSuccess` that arrives while no WorldScreen
   is subscribed (outside a match start) has no effect.
5. **Encode referee and village messages as LobbyMessages.** In the `SendGameData(74)` envelope the
   `msg_type` u32 (little-endian, like every envelope field) carries the type word
   `names<<15 | category<<12 | id` (referee category 3, e.g. `0x3DCA`); the `data` MEMBLOCK carries the
   fields only. The fields are an MSB-first bit stream, so a byte-aligned 32-bit field is big-endian on the
   wire. Both mistakes are silent (live, 2026-07-27, values read at the compare S 0047ad09): with the type
   word repeated at the head of the MEMBLOCK the client read `PermID` 1 as 0x00013DCA, with a little-endian
   `PermID` as 0x01000000. A little-endian `1006` code (`ef be ad de`) is ignored the same way (2026-07-26).
6. **Answer `RegisterGame(0xDB6)` with `0xDB7`, then `0xDB8 {GameID, 0, GameSeed}`,** the same seed for every
   client of the match (Phase 2). The `0xDB8` acts only while the setup dialog exists (`WorldScreen +0x35c8`).
7. **In the match**, answer `GiveUpGame(0xDD4)`, `FinishGame(0xDC0)` and `ClaimChest(0xDAC)`
   (`docs/message-catalog.md`; server log 2026-10-10). Wagers: `lobby/sadk_lobby/wagers.py`.

---

## Actors & key addresses `[known]`

| Thing | Where | Notes |
|---|---|---|
| `RefereeServerConnection` sub-object | `LM+0x490` | getter `LobbyComm::System::GetRefereeServerConnection@0x4624f0` |
| RegisterGame sender | `LobbyMenu::WorldScreen::OnRefereeLoginSuccess_RegisterGame@0x432240` | sole caller of `RefereeServerConnection::RegisterGame` |
| Village-conn **LoggedOut** observer | `LobbyMenu::WorldScreen::OnVillageConnectionLoggedOut@0x4316c0` | villageConn `+0x1c` LoggedOut. The NComm event 0x30012 (NE_StartLoading) is handled by `NComm_Manager::HandleEvent@0x40e560`, which only sets `cStartLoading` (`+0x3cc`) |
| Per-frame pump / login retry | `LobbyMenu::WorldScreen::Update@0x435980` | drives the arm flags below |
| Observer subscribe / unsubscribe | `LobbyMenu::WorldScreen::Activate@0x4351a0` / `Deactivate@0x433d80` | ten delegates; nothing is subscribed while the `LobbyComm::System` state is 1 |
| Load kick | `Lobby::CLobby` vtbl `+0x2c` (slot `RequestModeTransition`, body `Lobby::CLobby::App_RequestStateTransition` S 004f4eb0; names `[inferred]`) with argument 1 | called by `OnRefereeRegisterGameResult` |
| Abort / back to the lobby | `LobbyMenu::System::RequestScreen@0x429900` (screen 2) + `LobbyMenu::System::CloseDialogsOnScreenChange@0x42a640` | `RequestScreen` stores the requested lobby screen index (0 Empty, 1 Account, 2 Avatar, 3 World) in `System+0xc`; it is not a game run-mode setter |

### `WorldScreen` referee-login fields `[known]`

| Offset | Field | Meaning |
|---|---|---|
| `+0x35c8` | `setupGameDialog` | the 0xDB8 success handler acts only while this dialog exists |
| `+0x3624` | `refereeLoginPending` | referee login in progress; `Update` hides the screen while it is set |
| `+0x3625` | `refereeLoginArmed` | call `Login` when the delay has run out (one `Login` per arming) |
| `+0x3628` | `refereeLoginDelay` | frames to wait (first 0x10, then tries × 8 + 16) |
| `+0x362c` | `refereeLoginTries` | `> 4` aborts the match start |

---

## Phase 1 — referee server assignment (at lobby login) `[PROVEN]`

The referee is a separate server, assigned on demand:

1. `LobbyComm::ServerList::RequestRefereeServer@0x468f60`, called by `StatePump_Tick` once the state passes 5
   (latch `LM+0x584`) → tincat3 `GameServerManager::AssignServer` (T 10021830), **NETMSG 189** with
   `server_type=4, subtype=4`.
2. The reply reaches `ServerList::GameServerAssigned@0x469ad0`, which calls the pending callback
   `LobbyComm::System::SetRefereeServerAddress@0x4625d0`: it stores `serverId` to `LM+0x580` and arms the
   60000 ms timer at `LM+0x588`. The reply must be server type 4 / subtype 4 (server duty 1).
3. `LobbyComm::System::InitRefereeServerConnection@0x462910` (pump, gated on `LM+0x580 != 0`) registers the
   serverId with the ConnectionManager and binds the `RefereeServerConnection` at `LM+0x490` to that
   connection. The connection has no address yet; it gets one from `222` when it is opened at match start
   (server duty 3).

## Phase 2 — the game is registered → GameSeed `[PROVEN]`

`WorldScreen::OnRefereeLoginSuccess_RegisterGame@0x432240` harvests the NComm session and sends
**`RegisterGame(0xDB6)`**. Fields (cat 3 LobbyMessage):

`GameID(u32)`, `MapGUID(16-byte buffer)`, `MapName(str)`, `MapSettings(str)`,
`RankedGame(bool)`, `Wager(u32)`, `AIPlayer(u8 flags)`, `AvatarID(u32) ×6` (one per slot).

`MapSettings` is three ASCII digits, `'0'` + the session bytes `+0x225..+0x227` (win condition, start
resources, fog of war). A lobby match stores the WinCondition drop-down index + 1, so the first digit is
1 (destroy all enemies), 2 (conquer) or 3 (coin: the team's coin deliveries are counted), never 0
(endless); the free game stores 0..3 `[known]` (S 00454ad0).

The referee answers **`RegisterGameResult(0xDB8)`**: `GameID`, `Result`; on `Result==0` it
carries **`GameSeed(u32)`** and fires the 2-arg observer list `refConn+0x50`; on failure it
carries `FailReason(str)` and fires `refConn+0x5c`. (Intermediate `RegisterGameAck(0xDB7)`:
`GameID`, `Result`.) The handler does not check the `GameID`.

**What the `GameSeed` seeds `[known]`.** Only the contents of the chests of a network match; it is
not the simulation's random seed. `GetGameSeed` S 004139e0 has two callers:
- `Game_LoadWorldFromDescriptor` S 005ac770 (S 005ac7ed), for new-game map types only
  (`MapType_IsDataDirS2mMap(mapType)` S 0052c270): after `Game_CreatePlayersFromDescriptor`, if `GameSeed != 0` or
  `GameID` (`+0x22a`) `!= 0`, it calls `Game_DistributeChestsForNetworkMatch`.
- `Game_DistributeChestsForNetworkMatch` S 00775dd0 (S 00775e1f): builds a local
  `ai::math::RandomGenerator` (Park-Miller, `Rng_ParkMillerNext` S 006ec350), seeds it with the
  GameSeed (`SetSeed` S 006ec2a0) and draws one number per chest, stored at `LogicChest +0x28`
  (folded setter `Generic_SetDword28` S 00539200). The chest positions are chosen without the generator.

The simulation uses a separate global generator at S 00889b08: constructed with the constant
`0x5432ace0` (static initialiser S 007c07d0), reset from its stored seed in `LogicRandom_SetUp`
S 00538980, advanced by `LogicRandom_Next` S 005389b0, replaced only by `LogicRandom_Load` (from a
game file) and part of the checksum; nothing writes the GameSeed into it.

So the match needs the `0xDB8` message, not its seed value: the handler S 00431800 stores the seed,
fills the load descriptor and starts the game. A seed of 0 is accepted, and chests are still
distributed when `GameID != 0`. Other accesses of session `+0x22f`: `SetGameSeed` S 004139f0 ←
`SetGameSeedIfState2` S 004082e0 ← S 00431800 only; `Serialize` / `Deserialize` (it travels in every
GameInformation / StartLoading / StartGame payload); `AssignGameData` / `CopyFrom`;
`UpdateSettingsCrc` (S 004148c8); `Reset` (0).

**One seed per match** `[live, 2026-10-14]`. Each client seeds its chest pass with the GameSeed of its own
`0xDB8`; the host's payload does not replace it before the pass. With the same seed (0x5EED1234) to both
clients the four chests held identical `+0x28` values on host and joiner. With 0x5EED1294 to the host and
0x5EED1295 to the joiner the four chest cells were the same and the contents differed; the match ran without
desync (476 of 476 `ChecksumLog::VerifyLatest` S 00415a60 results on the joiner were 1), and the simulation
generator S 00889b08 kept its constant seed. An opened chest is claimed by every client (`0xDAC`, each with
its own chest id, all naming the opener as ActorID, `docs/message-catalog.md`), so with different seeds the
server sees one chest as two. The server therefore sends every client the same seed.

## Phase 3 — the referee-login gate `[known]`, chain `[PROVEN]`

The village connection's **LoggedOut** observers (`villageConn+0x1c`, fired by
`BaseConnection::OnLoggedOut@0x48e2a0`) include `WorldScreen::OnVillageConnectionLoggedOut`. The logout
itself follows the leave-village exchange (2002 → 1006 with 0xDEADBEEF → transport logout), see
`docs/SOURCEMAP.md` §2b. For a starting match (NComm manager state != 0 and `cStartLoading` set) the
observer **arms** the login (`+0x3624/+0x3625/+0x362c/+0x3628`); an observing client only hides the
screen; otherwise NComm is shut down and the client returns to the avatar screen.

`WorldScreen::Update` is the per-frame pump: after the delay it calls
**`RefereeServerConnection::Login@0x4793f0`** (opens the referee transport channel via
`transport+0x34->vtbl[0x10]`), one attempt per arming. With **more than 4 tries**, or when the NComm
manager state is 0, it **aborts the match start**: it clears the flags, requests lobby screen 2 and shuts
NComm down.

Referee replies: **`LoginSuccess(0xDCA)`** (`PermID`) fires `refConn+0x80`;
**`LoginFailed(0xDCB)`** (`PermID`) fires `refConn+0x8c`. `LoginSuccessReceived@0x47ac20` drops a `PermID`
that is not the local perm id; the field is big-endian on the wire. Nothing requests `LoginSuccess`: the
server pushes it after the referee connection's `153` (server duty 4).

## Phase 4 — the load kick `[known]`

`WorldScreen::OnRefereeRegisterGameResult@0x431800` stores the seed
(`NComm_Manager::SetGameSeedIfState2` S 004082e0, applied only in session state 2), fills the load
descriptor (`SetupGameDialog::SetupSession@0x4562d0`), clears the arm flags and calls
`Lobby::CLobby` vtbl `+0x2c` `RequestModeTransition(1)`.

---

## Referee protocol reference (`RefereeServerConnection`, LobbyMessage **category 3**)

Router: `RefereeServerConnection::OnReceive@0x47b090` (switch on msg id) `[known]`.
Send/recv follow `send 0xD_6/0xD_0/… → ack +1 → result +2`. All names are in
`LobbyComm::RefereeServerConnection`.

| Dir | ID | Message | Payload | Function |
|---|---|---|---|---|
| C→R | (chan-open) | `Login` | opens transport channel | `Login@0x4793f0` |
| C→R | — | `Logout` | | `Logout@0x479540` |
| C→R | `0xDB6` | `RegisterGame` | GameID, MapGUID[16], MapName, MapSettings, RankedGame, Wager, AIPlayer, 6×AvatarID | `RegisterGame@0x479840` |
| C→R | `0xDAC` | `ClaimChest` | | `ClaimChest@0x479670` |
| C→R | `0xDC0` | `FinishGame` | | `FinishGame@0x479c40` |
| C→R | `0xDD4` | `GiveUpGame` | | `GiveUpGame@0x479ab0` |
| R→C | `0xDCA` | `LoginSuccess` | PermID | `LoginSuccessReceived@0x47ac20` → `+0x80` |
| R→C | `0xDCB` | `LoginFailed` | PermID | `LoginFailedReceived@0x47ad50` → `+0x8c` |
| R→C | `0xDB7` | `RegisterGameAck` | GameID, Result | `RegisterGameAcknowledgeReceived@0x47a3d0` |
| R→C | `0xDB8` | `RegisterGameResult` | GameID, Result, **GameSeed** \| FailReason | `RegisterGameResultReceived@0x47a580` → `+0x50`/`+0x5c` |
| R→C | `0xDC1` | `FinishGameAck` | | `FinishGameAcknowledgeReceived@0x47a810` |
| R→C | `0xDC2` | `FinishGameResult` | | `FinishGameResultReceived@0x47a9c0` |
| R→C | `0xDAD` | `ClaimChestAck` | GameID, Result | `ClaimChestAcknowledgeReceived@0x479fb0` |
| R→C | `0xDAE` | `ClaimChestResult` | AvatarID, ChestID, str | `ClaimChestResultReceived@0x47a160` |
| R→C | `0xDD5` | `GiveUpGameAck` | | `GiveUpGameAcknowledgeReceived@0x47ae80` |

### WorldScreen observer-list map `[known]`

All callbacks are subscribed in `WorldScreen::Activate@0x4351a0` as an 8-byte `{screen, handlerFn}`
struct handed to `ObserverList::Subscribe@0x458860` at `conn+listOffset`; the handler addresses are plain
immediates in the registration code (the `+0x80` one at S 00435269..0043527f), so the handlers have no
direct callers. The screen watches **two** connections: the referee connection
(`LM+0x490`) and the village connection (`LM+0x540`, `LobbyComm::System::GetVillageServerConnection@0x4624d0`).

| Conn list | Fires on | Screen handler (`LobbyMenu::WorldScreen`) | Body |
|---|---|---|---|
| `refConn+0x04` | referee connection logged in | `OnRefereeConnectionLoggedIn@0x431780` | `+0x3624=1, +0x3625=0` |
| `refConn+0x10` | referee connection login failed | `OnRefereeConnectionLoginFailed@0x4317a0` | `+0x362c++, +0x3625=1, +0x3628=tries*8+0x10` |
| `refConn+0x50` | `RegisterGameResult` success — (gameId, **GameSeed**) | `OnRefereeRegisterGameResult@0x431800` | the load kick (Phase 4) |
| `refConn+0x5c` | `RegisterGameResult` failure | `OnRegisterGameFailed@0x432fd0` | `!REGISTER_GAME_FAILED` dialog |
| `refConn+0x80` | `LoginSuccess` | `OnRefereeLoginSuccess_RegisterGame@0x432240` | sends `RegisterGame(0xDB6)` |
| `refConn+0x8c` | `LoginFailed` | `OnRefereeLoginFailed@0x4317d0` | retry with back-off (same body as `+0x10`) |
| `villageConn+0x1c` | **LoggedOut** (via `BaseConnection::OnLoggedOut@0x48e2a0`) | `OnVillageConnectionLoggedOut@0x4316c0` | arm the referee login, or leave to the avatar screen |
| `villageConn+0x28` | Disconnected | `OnVillageConnectionDisconnected@0x432ed0` | `RequestScreen(2)` and propagate; with reason != 0 an `!ERROR_DIALOG` / `!CONNECTION_LOST_TEXT` box |
| `villageConn+0x8c` | minigame: no table left (message 219) | `OnJoinFailedNoTable@0x433280` | `!MINIGAME_NOTABLELEFT` dialog |
| `villageConn+0x98` | minigame: no player slot left (message 220) | `OnJoinFailedNoSlot@0x433380` | `!MINIGAME_NOPLAYERSLOTLEFT` dialog |

The last two lists belong to the minigame tables of the taverns (village messages 219 / 220), not to the
match room.

---

## Connection topology of `LobbyComm::System` `[known]`

`LobbyComm::System` (ctor `0x463fd0`, singleton pointer `g_pLobbyManager@0x885890`) owns four
`LobbyComm::BaseConnection` subclasses, all created in its ctor:

| Field | Off | Class | Bytes | ctor |
|---|---|---|---|---|
| `userCommConnection` | `LM+0x3d8` | `LobbyComm::UserCommConnection` (embedded, vtbl `0x7dcecc`) | 0xb8 | – |
| `refereeServerConnection` | `LM+0x490` | `LobbyComm::RefereeServerConnection` (embedded, vtbl `0x7dc1b0`) | 0xb0 | – |
| `pVillageConnection` | `LM+0x540` | `LobbyComm::VillageServerConnection` (vtbl `0x7db8d4`) | 0x280 | `VillageServerConnection::ctor@0x46eee0` |
| `pGameServerConnection` | `LM+0x544` | `LobbyComm::GameServerConnection` (vtbl `0x7deaf0`, `LobbyGameServerConnection.cpp`) | 0x38 | `GameServerConnection::ctor@0x48ed50` |

**Inbound routing — `LobbyComm::System::DispatchInboundToConnection@0x462760`** (vtable slot 5 of the
`IConnectionCallback` interface): for an inbound `(connId, channel, data, byteLen)` it finds which
connection owns `connId` (`BaseConnection::HasTransport@0x48dd30`), wraps `data` in an `NCore::BitStream`,
and calls `conn->vtbl[0x24](channel, &bitStream)`, the slot the village connection uses for
`HandleMessage`.

`GameServerConnection`'s `vtbl[0x24]` is the shared empty function `Stub_NoOpReturnVoid@0x472360`, so
**the pre-game room protocol does not ride `GameServerConnection`**. The slot, tribe, team, colour and
ready updates travel in the NComm match layer (peer-to-peer events of the `NComm_Manager`), see
`docs/NCOMM_GAME_PROTOCOL.md`.

## Pre-game room — player-slot model `[known]`

The SetupGame dialog's slots are a fixed **6-slot array inside the NComm game information**
(`NComm::EventGameInformation`, embedded in the `NComm_Manager` at `+0xdc`). Slot API:
`EventGameInformation::GetSlot@0x413100` `(i) = this + 0x10 + i*0x4c`,
`EventGameInformation::FindSlotByGuid@0x413300` (matches the 16-byte owner GUID, caps at 6). The match-start
reader is `LobbyMenu::SetupGameDialog::SetupSession@0x4562d0`: it walks the 6 slots, reads each via the
accessors below, and writes a `GameLoadDescriptor` (per-player setters `NLogic::MapInfo::SetPlayerKind`
S 005293b0, `NLogic::MapInfo::SetPlayerTribe` S 005293e0, …).

**`NComm::PlayerInfo` (0x4c = 76 bytes; accessors are methods of this class):**

| Off | Type | Field | Accessor | Note |
|----:|------|-------|----------|------|
| `+0x00` | — | vftable, state (`+0x04`), playerId (`+0x05`), NetGUID vftable (`+0x09`) | — | see `docs/types.md` §2.3 |
| `+0x0d` | byte[16] | ownerGuid | `GetOwnerGuid@0x415200` | `NComm::NetGUID`; the `"ownr"` identity |
| `+0x1e` | std::string | playerName | `GetPlayerName@0x415430` | |
| `+0x3a` | int8 | playerIndex | `GetPlayerIndex@0x414d60` | |
| `+0x3b` | int8 | **kind** | `GetKind@0x414d70` | `0`=empty, `1`=human, `2`=AI, `3`=closed |
| `+0x3c` | int8 | aiLevel | `GetAiLevel@0x414d80` | valid when kind==AI |
| `+0x3d` | int8 | tribe | `GetTribe` S 00414da0 (→ `NComm_GetNationIdForTribe` S 004538b0 → descriptor `+0x68`) | `[known]` |
| `+0x3e` | int8 | colour | `GetColor` S 00414db0 (→ descriptor `+0x88`) | `[known]` |
| `+0x3f` | int8 | team | `GetTeam` S 00414dc0 (→ descriptor `+0xa8` → `Player.team`) | `[known]`; -1 = no team |
| `+0x40` | int8 | readyState | folded setter S 00552f10 | `[known]`; 0 not ready, 1 ready, 2 loaded |
| `+0x41..+0x4b` | — | avatar look, avatar colours, AvatarID, left-notice latch | — | see `docs/NCOMM_GAME_PROTOCOL.md` |

The full slot table, the team chain and the ready-state writers are in `docs/NCOMM_GAME_PROTOCOL.md` and
`docs/types.md` §2.3. The GameSeed lives in the same game information (`g_NCommManager` `0x885754`,
`+0xdc`, field `+0x22f`).

## Open `[TODO]`

1. Answered (Phase 2): **differing seeds inside one match.** Each client stores the seed of its own
   `RegisterGameResult` and then loads; `AssignGameData` copies `+0x22f` from the host's payload
   (S 00414388) in events 0x30003 (GameInformation), 0x30012 (StartLoading) and 0x30005 (StartGame),
   and the host rebroadcasts 0x30003 after every 0x30004 / 0x30011 / 0x30002 it receives `[known]`.
   In a two-player match no such replacement landed before the chest pass: each client seeded its
   chests with its own GameSeed, and different seeds gave different chest contents and ids on the two
   clients without a desync (`LogicChest +0x28` is not in the checksummed state) `[live, 2026-10-14]`.
   The server must send every client of a match the same seed; the stub does.
