# Recovered types

Reference for the data types recovered in the Ghidra programs `sadk_noav.exe` (the unpacked `SADK.exe`)
and `tincat3.dll`. Network and lobby types come first, then a short overview of the game-side families,
then how the types are organised in Ghidra, then the open gaps.

Wire layouts (field order and bit widths on the wire) are not repeated here. See
[message-catalog.md](message-catalog.md) and [LOBBY_PROTOCOL.md](LOBBY_PROTOCOL.md). For the NComm match
layer, see also [NCOMM_LAYER.md](NCOMM_LAYER.md) and [NCOMM_GAME_PROTOCOL.md](NCOMM_GAME_PROTOCOL.md). For a
flat symbol map, see [SOURCEMAP.md](SOURCEMAP.md).

## Conventions in this document

| Notation | Meaning |
|---|---|
| `S 00xxxxxx` | address in `sadk_noav.exe` (image base `0x400000`, the same as runtime) |
| `T 10xxxxxx` | address in `tincat3.dll` (image base `0x10000000`, the same as runtime) |
| `+0x..` | byte offset inside the object |
| `[known]` | directly visible in code or data (constant, RTTI, vtable slot, string, allocation size) |
| `[inferred]` | strong evidence from callers, strings and types, but not directly visible |
| `[guess]` | plausible, not verified |
| `[PROVEN]` | shown live by the working stub (binary address plus live evidence) |
| `[TODO]` | open |

In the field tables, **conf** is the per-field tag stored in the Ghidra field comment (`[ai:known]` and so
on). Fields with no tag in Ghidra were defined before the mapping run ("PRIOR"). They are marked `prior`
and should be treated as `[guess]` unless a row says otherwise.

Sizes are in hex. "alloc" is the size passed to `operator new` before the constructor runs. It is the
only `[known]` object size. A struct size without an alloc is a lower bound.

---

## 1. Lobby layer (`sadk_noav.exe`, namespace `LobbyComm`)

### 1.1 Overview

```
LobbyComm::System  (singleton g_pLobbyManager S 00885890; called LobbyManager in older notes)
 ├─ ICommLayer*  ──────────────────────────────►  tincat3 CommLayer::CommLayer
 ├─ ServerList           (+0x54, embedded)   village/game server browser, referee lookup
 ├─ ServerMessages       (+0x100, embedded)  MotD / server messages
 ├─ CharacterManager     (+0x140, embedded)  characters, buddies, ignore list, name<->id cache
 ├─ PostOffice           (+0x2f8, embedded)  mail
 ├─ Properties           (+0x3bc, embedded)  PropertyGet/Set requests (version check)
 ├─ UserCommConnection   (+0x3d8, embedded)  chat / UC connection
 ├─ RefereeServerConnection (+0x490, embedded) match arbiter
 ├─ VillageServerConnection* (+0x540, heap 0x280) 3D lobby world
 └─ GameServerConnection*    (+0x544, heap 0x38)  game room server
```

All four connection classes derive from `LobbyComm::BaseConnection`, which wraps one tincat3 connection
object (`pTransport`, +0x34). Messages travel as `LobbyComm::LobbyMessage` bit streams.

### 1.2 `LobbyComm::System` (called LobbyManager in older notes)

| | |
|---|---|
| RTTI class | `LobbyComm::System` (`.?AVSystem@LobbyComm@@`, source file `LobbyManager.cpp`), base `CommLayer::IConnectionCallback` [known] |
| Ghidra struct | `/LobbyComm/System` (`[ai]`, 0x5a8) |
| Class namespace | `LobbyComm::System` (35 methods) |
| Names that keep the word LobbyManager | the global `g_pLobbyManager`, the enum `LobbyManagerState`, and the four static functions `LobbyManager_GetInstance` S 00462420, `LobbyManager_HasInstance` S 00462430, `LobbyManager_CreateInstance` S 00464280, `LobbyManager_DestroyInstance` S 00462400 |
| vtable | S 007dacb0, 7 slots [known] |
| alloc | **0x5a8** [known]: `LobbyManager_CreateInstance` S 00464280, `operator_new(0x5a8)` |
| Singleton | `g_pLobbyManager` S 00885890 [known] |
| Role | Owns the CommLayer, every lobby sub-manager and every connection. Runs the login state machine (`StatePump_Tick`). |

The struct is as long as the allocation; its last member ends at +0x5a8. The table gives the layout from
the ctor S 00463fd0, dtor S 00463df0 and `ResetSubManagers` S 00462440. This document writes `LM+0x..` as
shorthand for an offset inside this object.

| off | type | name | Ghidra name | conf |
|---|---|---|---|---|
| +0x00 | `System_vftable*` | vftable (S 007dacb0) | `vftable` | [known] |
| +0x04 | ObserverList | connection-lost observers (sender, errorCode); fired by `OnConnectionLost` S 00464931; subscriber `AvatarScreen::OnConnectionLost` S 0043b1b0 | `connectionLostObservers` | [known] |
| +0x10 | ObserverList | global data loaded (state 6 -> 7), args (sender, chatServerHandle `+0x548`): the login-complete signal; fired by `StatePump_Tick` S 0046504f; subscribers `LoginDialog::OnLoginSucceeded` S 0043c1a0, `CreateAccountDialog::OnAccountCreated` S 0043d960 | `globalDataLoadedObservers` | [known] |
| +0x1c | ObserverList | login-failed observers (sender, errorCode); fired by `OnLoginFailed` S 00464b3b and by `OnLoggedOut` S 00464cce with the fixed code 0x5479 when the main connection logs out in a state != 1 and < 7; subscribers `LoginDialog::OnLoginFailed` S 0043c890, `CreateAccountDialog::OnCreateAccountFailed` S 0043db90 | `loginFailedObservers` | [known] |
| +0x28 | ObserverList | main-connection logged-out observers (sender, reason), state > 6; fired by `OnLoggedOut` S 00464ce5; subscriber `AvatarScreen::OnLobbyServerLoggedOut` S 00439c20 | `loggedOutObservers` | [known] |
| +0x34 | ObserverList | subscribed once, with the empty function S 00472360, by `AvatarScreen::Activate` S 0043bec5 (unsubscribed in `AvatarScreen::OnHide` S 0043b2fe). No code in the binary fires this list: the seven `ObserverList_NotifyAll` calls of the class use the five other lists. Hooks on both `ObserverList_NotifyAll` bodies (S 00464300, S 0045f620) saw no call for it through a login, a village entry and exit, a hosted room and a lost lobby connection [live, 2026-10-14]. The event it stood for cannot be read from the client | `observers34` | [known] |
| +0x40 | ObserverList | version-check-failed observers (sender, errorCode); fired by `OnVersionChecked_State4to5` with 0x6f (111, property request failed, S 00464e93) or 0x3e (62, client protocol version non-zero and lower than the server value, S 00464ebb); subscriber `LoginDialog::OnVersionCheckFailed` S 0043ca60 (`!VERSIONCHECK_FAILED_TEXT`) | `versionCheckFailedObservers` | [known] |
| +0x4c | ICommLayer* | tincat3 CommLayer | `pCommLayer` | [known] |
| +0x50 | ConnectionManager* | tincat3 connection manager | `pConnectionManager` | [known] |
| +0x54 | LobbyComm::ServerList (0xac) | server list (village servers and game servers) | `serverList` | [known] |
| +0x100 | LobbyComm::ServerMessages (0x3c) | MotD holder | `serverMessages` | [known] |
| +0x140 | LobbyComm::CharacterManager (0x1b8) | characters/buddies | `characterManager` | [known] |
| +0x2f8 | LobbyComm::PostOffice (0xc4) | mail | `postOffice` | [known] |
| +0x3bc | LobbyComm::Properties (0x1c) | property requests | `properties` | [known] |
| +0x3d8 | LobbyComm::UserCommConnection (0xb8) | chat connection | `userCommConnection` | [known] |
| +0x490 | LobbyComm::RefereeServerConnection (0xb0) | referee connection | `refereeServerConnection` | [known] |
| +0x540 | VillageServerConnection* | world connection (new 0x280) | `pVillageConnection` | [known] |
| +0x544 | GameServerConnection* | game-room connection (new 0x38) | `pGameServerConnection` | [known] |
| +0x548 | int | lobby / chat server handle | `nChatServerHandle` | [inferred] |
| +0x54c | uint | the local user's permanent id (`GetLocalPermId` S 00462510) | `localPermId` | [inferred] |
| +0x550 | int | selected village server id (-1 reset) | `nSelectedVillageServerCached` | [inferred] |
| +0x554 | AvatarProxy* | local avatar (`GetLocalAvatar` S 004625c0); +0xd0 of it is the player's gold | `localAvatar` | [inferred] |
| +0x558 | std::map | avatar map (key actor id); the village connection's `+0x170` points here (ctor S 0046f193); holds the local avatar from `SetLocalAvatar` S 004626c0 until `ClearLocalAvatar` S 00462570 | `avatarMap` | [known] |
| +0x564 | std::map | NPC map; the village connection's `+0x174` points here (ctor S 0046f199) | `npcMap` | [inferred] |
| +0x570 | `ai::lobby::ItemDatabase` (std::map of item id to `ai::village::ItemInfo`) | built from `ItemsClient.txt`; returned by `GetItemDatabase` S 00462560; freed by `ItemDatabase_Destroy` S 0048bf90 | `itemDatabase` | [known] |
| +0x57c | `LobbyManagerState` | login state | `state` | [known] |
| +0x580 | int | referee server id | `nRefereeServerId` | **[PROVEN]** |
| +0x584 | u8 | referee server requested: `StatePump_Tick` (state > 5) sets 1 when it calls `ServerList::RequestRefereeServer` (S 00465107) and clears it when the timer +0x588 is negative (S 0046512f), which makes the next tick request again | `refereeServerRequested` | [known] |
| +0x588 | int | referee retry timer, ms (60000) | `nRefereeConnectTimeoutMs` | [inferred] |
| +0x58c | std::string (0x1c) | pending e-mail: written by `CreateUser` (S 004635d1, before the connection attempt, so it stays stored when registration fails), consumed on the 5 -> 6 transition by `CharacterManager::UpdateEMail` (S 00464fa8), then cleared. `+0x590` / `+0x5a0` / `+0x5a4` are this string's buffer, size and capacity, not separate fields | `pendingEmail` | [known] |

`+0x580` is set by `SetRefereeServerAddress` S 004625d0. The stub shows it live: once a type-4/sub-4
assign reply arrives, the client retries `189 AssignServer` exactly every 60 s, which is the +0x588 timer
re-arming. A type-4/sub-5 reply never sets it. Sources: `lobby/sadk_lobby/dispatch.py` `_h_assign_server`
and the 2026-07-27 referee engagement records.

**`LobbyManagerState`** (`/LobbyManagerState`, 4 bytes) [known]: 0 Init, 1 Disconnected, 2 Authorizing,
3 Authorized, 4 CheckingVersion, 5 VersionChecked, 6 LoadingGlobalData, 7 GlobalDataLoaded,
8 EnteringVillage, 9 VillageEntered, 10 LeavingVillage, 11 VillageLeft, 12 ConnectionLost.

**vtable S 007dacb0** (`/LobbyComm/System_vftable`; the `CommLayer::IConnectionCallback` interface S 007da848, which tincat3 calls) [known]:

| slot | addr | method |
|---|---|---|
| 0 | S 00464260 | scalar_deleting_dtor |
| 1 | S 00463a10 | OnLoggedIn(connId, serverHandle, unused), RET 0xc |
| 2 | S 00464a20 | OnLoginFailed |
| 3 | S 00464bf0 | OnLoggedOut |
| 4 | S 004647e0 | OnConnectionLost(connId, unused, err) |
| 5 | S 00462760 | DispatchInboundToConnection |
| 6 | S 00463bc0 | OnStatisticsConnectionReceived |

**Key methods:** ctor S 00463fd0 · Initialize S 004643d0 · Login S 004630e0 · CreateUser S 004633f0 ·
Logout S 00463710 · `StatePump_Tick` S 00464ee0 (state machine) · `OnVersionChecked_State4to5`
S 00464e70 · CreateVillageServerConnection S 00463850 · InitRefereeServerConnection S 00462910 ·
SetRefereeServerAddress S 004625d0 · SetLocalAvatar S 004626c0 · GetStateName S 00462a00.

### 1.3 BaseConnection and its vtable

| | |
|---|---|
| Ghidra struct | `/LobbyComm/BaseConnection` (`[ai]`, 0x38) |
| vtable | S 007de8cc, 14 slots [known] |
| Source file | `LobbyBaseConnection.cpp` (string) [known] |
| Derived | `VillageServerConnection`, `UserCommConnection`, `RefereeServerConnection`, `GameServerConnection` |

`/LobbyComm/LobbyBaseConnection` is an older duplicate of this type (PRIOR, three fields) and is still
present; `/LobbyComm/BaseConnection` is the one in use.

| off | type | name | conf |
|---|---|---|---|
| +0x00 | `BaseConnection_vftable*` | vftable | [known] |
| +0x04 | `/ai/lobby/ObserverList` | loggedInObservers | [known] |
| +0x10 | ObserverList | loginFailedObservers | [known] |
| +0x1c | ObserverList | loggedOutObservers | [known] |
| +0x28 | ObserverList | disconnectedObservers | [known] |
| +0x34 | void* | pTransport: tincat3 connection; vtbl+0xc GetState (8 = logged in), +0x1c Send(u16 header, data, len) | [known] |

`/ai/lobby/ObserverList` (0xc) is an MSVC `std::list` of callbacks: +4 sentinel head, +8 count [inferred].
`ObserverList_NotifyAll` S 00464300 fires it with (sender, arg): it iterates a copy, so a callback may
unsubscribe, and leaves the list itself untouched [known].

**`/LobbyComm/BaseConnection_vftable`** (each slot is typed with a `/ai/lobby/BaseConnection_*_fn` funcdef):

| slot | off | base impl | name | conf |
|---|---|---|---|---|
| 0 | +0x00 | S 0048de20 | scalar_deleting_dtor | [known] |
| 1 | +0x04 | S 0048de70 | Initialize | [known] |
| 2 | +0x08 | S 0048dec0 | Destroy | [known] |
| 3 | +0x0c | S 0048dfa0 | SendMessage (called after `LobbyMessage::Finalize`) | [known] |
| 4 | +0x10 | S 0048df10 | SendBuffer | [known] |
| 5 | +0x14 | S 0048e050 | OnLoggedIn | [known] |
| 6 | +0x18 | S 0048e170 | OnLoginFailed | [known] |
| 7 | +0x1c | S 0048e2a0 | OnLoggedOut | [known] |
| 8 | +0x20 | S 0048e3c0 | OnDisconnected | [known] |
| 9 | +0x24 | S 00472360 (no-op) | OnReceivedData / message dispatcher | [inferred] |
| 10 | +0x28 | S 005657b0 (empty) | Process (per-tick pump) | [inferred] |
| 11 | +0x2c | S 0048dce0 | IsLoggedIn | [known] |
| 12 | +0x30 | S 0048dd00 | IsConnectionPending | [known] |
| 13 | +0x34 | S 0059af50 | GetConnectionQuality: the base is a shared `return 3` body (3 = best), also in the UserCommConnection, RefereeServerConnection and GameServerConnection vtables; VillageServerConnection overrides it with S 0046c130, which returns its +0x244 | [inferred] |

### 1.4 VillageServerConnection (3D lobby world)

| | |
|---|---|
| Ghidra struct | `/LobbyComm/VillageServerConnection` (0x280) |
| alloc | 0x280 [known] (`LobbyComm::System` +0x540) |
| vtable | S 007db8d4, 17 slots [known] |
| Methods | 79 in `LobbyComm::VillageServerConnection` |

The table gives the layout from the ctor S 0046eee0, the dtor S 0046e8f0 and the handlers. The "Ghidra"
column is the field name in the struct.

| off | type | name | Ghidra | conf |
|---|---|---|---|---|
| +0x00 | `VillageServerConnection_vftable*` | vftable S 007db8d4 | `pVftable` | [known] |
| +0x04..+0x34 | – | BaseConnection part (four observer lists, pTransport) | `loggedInObservers` .. `pTransport` | [known] |
| +0x38..+0x14c | 24 × ObserverList | world events, step 0xc; see the list below | see below | [known] offsets |
| +0x158 | LobbyComm::System* | owner: the ctor stores its argument; `SetState`, `SetLocalAvatar` and `GetChatServerHandle` are called on it | `pSystem` | [known] |
| +0x15c | int | village server id (-1 in the ctor and in `Destroy`); `InitializeForServer` S 0046dac0 stores it | `villageServerId` | [known] |
| +0x160 | u32 | ServerPerm from EnterWorld (1000), stored at S 0046f87f; `GetServerPermId` S 0046c600 | `serverPermId` | [known] |
| +0x164 | std::map<u8 zone, uint channel> (head +0x168, size +0x16c) | chat channel per zone; key 0xFF main, 0xFE minigame table, < 0x0E zones; built by `HandleEnterWorld` | `zoneChatChannels` | [known] |
| +0x170 | std::map<uint, AvatarProxy*>* | avatars (= LM+0x558) | `pAvatarMap` | [known] |
| +0x174 | std::map<uint, NPCProxy*>* | NPCs (= LM+0x564) | `pNpcMap` | [known] |
| +0x178 | std::map (head +0x17c, size +0x180) | minigame tables, value `MiniGameProxy*` | `miniGameTables` | [inferred] |
| +0x184..+0x210 | 8 × std::deque<AvatarProxy*>, step 0x14 | event queues, filled by the message handlers and emptied every frame by `DrainEventQueues` S 0046fde0, which hands each entry to the observer list of the same event; see the list below | see below | [known] |
| +0x224 | bool | world-login ack received: 0 in the ctor, 1 in `HandleWorldLoginAck` S 0046ec50 when message 1006 carries 0xDEADBEEF; no code reads it | `worldLoginAckReceived` | [known] |
| +0x225 | u8 | zone key of the joined zone chat channel (0x0F none); set by `OnChatChannelJoined` S 0046d610 | `currentZone` | [known] |
| +0x226 | bool | zone join pending: set by `JoinZoneChatChannel` S 0046e860, cleared by `OnChatChannelJoined` | `zoneJoinPending` | [known] |
| +0x228 | std::string | world name (`<UNNAMED>` default); `GetWorldName` S 0046c120 | `worldName` | [known] |
| +0x244 | int | ping grade 3 (best) .. 0, returned by `GetConnectionQuality` S 0046c130; the ctor and `HandleEnterWorld` set 3, `HandlePongCode` S 0046c250 sets it from the round-trip time | `connectionQuality` | [inferred] |
| +0x248 | u32 | pending ping code (0x80008000 none) | `pendingPingCode` | [inferred] |
| +0x24c / +0x250 / +0x254 | float | ping send time / pong receive time / next-ping countdown | `pingSentTime` / `pongReceivedTime` / `nextPingCountdown` | [inferred] |
| +0x258 | u32 | shop NPCID | `shopNpcId` | [inferred] |
| +0x25c | u32 | ShopID | `shopId` | [inferred] |
| +0x260 | float | SellMod (default 0.9) | `shopSellMod` | [inferred] |
| +0x264 | vector<ShopStockEntry> | shop stock `{ItemID, Buy, Sell}` | `shopStock` | [inferred] |
| +0x274 | bool | trade request pending: set by `HandleTradeRequest` S 0046d920 (message 0xF46) | `tradeRequestPending` | [inferred] |
| +0x275 | bool | trade active | `tradeActive` | [inferred] |
| +0x278 | u32 | tradeID | `tradeId` | [inferred] |
| +0x27c / +0x27e | u16 / u8 | trade message-part key | `tradeMsgPrt` / `tradeRnid` | [inferred] |

The 24 observer lists (`/ai/lobby/ObserverList`, 0xc each) [known]:

| off | Ghidra | fired by | subscriber |
|---|---|---|---|
| +0x38 | `npcAddedObservers` | `HandleNPCData` S 0046f8c0 (this, NPCProxy*) | `CLobbyClient::OnNPCAdded` |
| +0x44 | `npcRemovedObservers` | `ClearNPCs` S 0046fc10, once per NPC | `CLobbyClient::OnNPCRemoved` |
| +0x50 | `miniGameSeatJoinedObservers` | `MiniGameProxy::SetSeat` S 00471d10, `AnnounceSeats` S 00471eb0 (conn, proxy, seat) | `CLobbyClient::OnMiniGameSeatJoined` S 00503710 |
| +0x5c | `miniGameSeatLeftObservers` | `MiniGameProxy::ClearSeat` S 00471c40 | `CLobbyClient::OnMiniGameSeatLeft` S 00503730 |
| +0x68 | `miniGameTableShownObservers` | `HandleMiniGameTableUpdate` S 0046f380 (this, proxy) | `CLobbyClient::OnMiniGameTableShown` |
| +0x74 | `miniGameTableRemovedObservers` | `HandleMiniGameTableRemove` S 0046f510, `ClearMiniGameTables` S 0046fd10 | `MiniGameProxy_DestroyTableObjectCallback` |
| +0x80 | `miniGameTableUpdatedObservers` | `HandleMiniGameTableUpdate` S 0046f380 | `CLobbyClient::OnMiniGameTableUpdated` S 00503780 |
| +0x8c | `miniGameNoTableLeftObservers` | `HandleMiniGameNoTableLeft` S 0046f4d0 (message 219) | subscribed by `WorldScreen::Activate` S 004351a0 |
| +0x98 | `miniGameNoPlayerSlotLeftObservers` | `HandleMiniGameNoPlayerSlotLeft` S 0046f4f0 (message 220) | `WorldScreen::OnJoinFailedNoSlot` S 00433380 |
| +0xa4 | `avatarLoggedInObservers` | `DrainEventQueues` from the queue +0x184 (message 1002), `CreateNpcSeatAvatar` S 0046f9b0 | an empty `CLobbyClient` function |
| +0xb0 | `avatarRemovedObservers` | `DrainEventQueues` from +0x198 (message 1003), `ClearAvatarsAndEventQueues` S 0046fab0 | `CLobbyClient::OnAvatarRemoved` |
| +0xbc | `avatarDataObservers` | `DrainEventQueues` from +0x1ac (message 1001), `CreateNpcSeatAvatar` | `CLobbyClient::UpdateAvatar` |
| +0xc8 | `avatarActiveItemsObservers` | `DrainEventQueues` from +0x1c0 | `CLobbyClient::OnAvatarItemsChanged` |
| +0xd4 | `avatarInventoryObservers` | `DrainEventQueues` from +0x1d4 | none |
| +0xe0 | `avatarItemsFullSyncObservers` | `DrainEventQueues` from +0x1e8 | `CLobbyClient::OnAvatarItemsChanged` |
| +0xec | `observers_ec` | `DrainEventQueues` from +0x1fc, which no code fills | none |
| +0xf8 | `observers_f8` | `DrainEventQueues` from +0x210, which no code fills | none |
| +0x104 | `enterWorldObservers` | `HandleEnterWorld` S 0046f670 (message 1000) | `CLobbyClient::OnEnterWorld` S 00503940 |
| +0x110 | `leaveWorldObservers` (name [inferred]) | no code in the binary: outside the ctor, the dtor and the subscribe / unsubscribe sites S 00503ee1 / S 00503c91, no instruction addresses the list | `CLobbyClient::OnWorldLeft` S 005037a0, the inverse of `OnEnterWorld`; it is never called |
| +0x11c | `worldTickObservers` | `HandleWorldTick` S 0046f620 (message 1005) | `CLobbyClient::OnWorldTick` |
| +0x128 | `shopInventoryObservers` | `HandleShopInventoryData` S 004706b0 (npcId, shopId, name, sellMod, stock) | `WorldScreen::OnShopInventoryReceived` S 004323d0 |
| +0x134 | `shopBuyResultObservers` | `HandleShopBuyResult` S 00470990 | – |
| +0x140 | `shopSellResultObservers` | `HandleShopSellResult` S 00470a10 | – |
| +0x14c | `observers_14c` | none; only the ctor and the dtor touch it | none |

The 8 event deques (`/ai/stl/MsvcDeque`, 0x14 each) [known]: +0x184 `avatarLoggedInQueue`
(`HandleAvatarLoggedIn` S 0046e390, message 1002), +0x198 `avatarRemovedQueue` (`HandleAvatarRemove`
S 0046e570, 1003), +0x1ac `avatarDataQueue` (`HandleAvatarData` S 0046e1d0, 1001), +0x1c0
`avatarActiveItemsQueue` (`HandleAvatarActiveItemsUpdate` S 0046e660), +0x1d4 `avatarInventoryQueue`
(`HandleAvatarInventoryUpdate` S 0046e6f0), +0x1e8 `avatarItemsFullSyncQueue` (`HandleAvatarItemsFullSync`
S 0046e780), +0x1fc `queue_1fc` and +0x210 `queue_210` (no code pushes to either).

**vtable S 007db8d4.** Slots 0–12 follow the BaseConnection layout. Overrides are listed with their own
address.

| slot | addr | name |
|---|---|---|
| 0 | S 0046f360 | scalar_deleting_dtor |
| 1 | S 0048de70 | Initialize (inherited) |
| 2 | S 0046da60 | Destroy |
| 3 | S 0048dfa0 | SendMessage (inherited) |
| 4 | S 0048df10 | SendBuffer |
| 5 | S 0046dc00 | HandleLoggedIn |
| 6 | S 0046dcf0 | HandleLoginFailed |
| 7 | S 00470e20 | HandleLoggedOut |
| 8 | S 00470f90 | HandleDisconnected |
| 9 | S 00470a90 | HandleMessage (village message dispatcher) |
| 10 | S 00471110 | TickInWorld |
| 11 / 12 | S 0048dce0 / S 0048dd00 | IsLoggedIn / IsConnectionPending |
| 13 | S 0046c130 | GetConnectionQuality |
| 14 | S 0046dac0 | InitializeForServer(serverId) |
| 15 | S 00470d50 | OpenUserComm |
| 16 | S 0046bde0 | SendLeaveVillageRequest |

The vtable struct `/LobbyComm/VillageServerConnection_vftable` (0x44) carries these names, one typed
function pointer per slot.

**Key handlers:** HandleWorldLoginAck S 0046ec50 · HandleEnterWorld S 0046f670 · HandleAvatarData
S 0046e1d0 · HandleAvatarLoggedIn S 0046e390 · HandleAvatarRemove S 0046e570 · HandleShopInventoryData
S 004706b0 · HandleTradeOffer S 0046cd10 · SendPing S 0046c150 · SendAvatarLocation S 0046ca40 ·
SendAvatarColorChange S 0046c760 · SendDeleteItemRequest S 0046bff0.

### 1.5 UserCommConnection (chat)

| | |
|---|---|
| Ghidra struct | `/LobbyComm/UserCommConnection` (0xb8) |
| vtables | S 007dcecc (primary), S 007dce94 (`CommLayer::IChatChannelObserver` face) [known] |
| Embedded at | `LobbyComm::System` +0x3d8 |

| off | type | name | conf |
|---|---|---|---|
| +0x34 | void* | pTransport (BaseConnection) | prior |
| +0x38 | `CommLayer::IChatChannelObserver` | embedded sub-object `chatChannelObserver`; its vptr is the override table S 007dce94, and its 12 callbacks run with this = UserCommConnection+0x38 | [known] |
| +0x3c | `/ai/std/MsvcList` | chat line received (senderName, senderId, channelId, text): fired by `ChatReceived` S 00480ff6; subscribers `WorldScreen::OnChatChannelMessage` S 00436180, `CLobbyClient::OnChatMessage` S 00503200 | [known] |
| +0x48 | MsvcList | incoming whisper (fromName, fromId, text): fired by `PrivateChatReceived` S 00481296 when `from_id` is not the local perm id; dropped when `GetUserRelation(from)` == 2; subscriber WorldScreen S 00432930 | [known] |
| +0x54 | MsvcList | own whisper echoed (targetName, targetId, text): fired by `PrivateChatReceived` S 004812eb when `from_id` is the local perm id and the target's name is in the CharacterManager name cache (otherwise the echo is dropped; the id lookup that precedes the send does not fill that cache, S 00473590, S 00480340); subscriber `WorldScreen::OnPrivateChatSent` S 00432c60. | [known] |
| +0x60 | MsvcList | channel joined (ChatChannelInfo*): fired by `JoinChannelReceived` with error 0 (S 00480c3e); subscriber `VillageServerConnection::OnChatChannelJoined` S 0046d610 (records the joined zone at VSC+0x225, clears the zone-join-pending flag +0x226), subscribed in `VSC::OnUserCommLoggedIn`, unsubscribed in `HandleWorldLoginAck` S 0046ec50 | [known] |
| +0x6c | MsvcList | channel join failed (ChatChannelInfo*, error): fired by `JoinChannelReceived` with error != 0 (S 00480bb3); no subscriber in the binary | [known] |
| +0x78 | MsvcList | channel left (ChatChannelInfo*): fired by `LeaveChannelReceived` with error 0 (S 00480e1e); only subscriber is the VSC with the no-op S 0064b9c0 (same subscribe / unsubscribe sites as +0x60) | [known] |
| +0x84 | MsvcList | channel leave failed (ChatChannelInfo*, error): fired by `LeaveChannelReceived` with error != 0 (S 00480d93); no subscriber in the binary | [known] |
| +0x90 | void* | tincat3 ChatChannelManager | prior |
| +0x94 | vector<ChatChannelInfo> | first/last/end at +0x98/+0x9c/+0xa0 | [inferred] |
| +0xa4 | std::deque<`ai::lobby::PrivateChatRequest`> | `whisperQueue` (map +0xa8, map size +0xac, offset +0xb0, count +0xb4): `QueuePrivateMessage` S 004808a0 pushes, `Process` S 00480630 works on the head, `OnWhisperTargetLookedUp` S 00480340 resolves or drops it | [known] |

**Key methods:** Initialize S 0047f160 · OpenCommunication S 0047ff10 · JoinChannel S 00480070 ·
LeaveChannel S 004801e0 · SendChatMessage S 0047ede0 · SendPrivateMessage S 0047ef40 · OnReceivedData
S 0047f6e0 · Process S 00480630 (whisper queue pump) · ChatReceived S 00480e30 ·
PrivateChatReceived S 004810a0.

### 1.6 RefereeServerConnection (match arbiter)

| | |
|---|---|
| Ghidra struct | `/LobbyComm/RefereeServerConnection` (`[ai]`, 0xb0; it absorbed the PRIOR root `/RefereeServerConnection`) |
| vtable | S 007dc1b0, 14 slots [known] |
| Embedded at | `LobbyComm::System` +0x490 |

| off | type | name | conf |
|---|---|---|---|
| +0x00..+0x34 | – | BaseConnection part | [known] |
| +0x38 / +0x44 | ObserverList | claimChestOk / claimChestFailed (0xDAE) | [known] |
| +0x50 | ObserverList | registerGameOk: `RegisterGame` result 0xDB8 (gameId, GameSeed) | [known], **[PROVEN]** path |
| +0x5c | ObserverList | registerGameFailed (0xDB7/0xDB8 failure, also 0xDAD failure) | [known] |
| +0x68 / +0x74 | ObserverList | finishGameOk / finishGameFailed | [known] |
| +0x80 / +0x8c | ObserverList | refereeLoginSuccess / refereeLoginFailed | [known] |
| +0x98 / +0xa4 | ObserverList | giveUpGameOk / giveUpGameFailed | [known] |

The vtable follows BaseConnection. Its overrides are: [0] S 004793d0 sdtor, [1] S 004791c0 Initialize,
[5] S 004791f0 OnLoggedIn, [6] S 00479200 OnLoginFailed, [9] S 0047b090 `OnReceive` (typed with
`/ai/lobby/RefereeServerConnection_OnReceive_fn`).

**Key methods:** Login S 004793f0 · Logout S 00479540 · ClaimChest S 00479670 · RegisterGame S 00479840 ·
GiveUpGame S 00479ab0 · FinishGame S 00479c40 · `LoginSuccessReceived` S 0047ac20 ·
RegisterGameAcknowledgeReceived S 0047a3d0 · RegisterGameResultReceived S 0047a580 ·
FinishGameAcknowledgeReceived S 0047a810 · FinishGameResultReceived S 0047a9c0.

[PROVEN] The stub has driven `RegisterGame 0xDB6` to `Ack 0xDB7` and `Result 0xDB8` live (two matches,
2026-07-27). `LoginSuccessReceived` S 0047ac20 drops a PermID whose bytes are not big-endian (see
`lobby/sadk_lobby/referee.py`).

### 1.7 GameServerConnection

`/LobbyComm/GameServerConnection` (`[ai]`, 0x38, alloc 0x38 [known]). It is a BaseConnection with no
extra data members [inferred]. It absorbed the 1-byte PRIOR root `/GameServerConnection`. vtable S 007deaf0:
[0] S 0048ed70 sdtor, [1] S 0048eda0 Initialize, [5] S 0048edf0 OnLoggedIn, with the other slots inherited
[known]. Source file `LobbyGameServerConnection.cpp` [known].

### 1.8 LobbyMessage (bit-stream message)

| | |
|---|---|
| Ghidra struct | `/LobbyComm/LobbyMessage` (0x3c). It is the only message type: every handler parameter is a `LobbyMessage*`, and `VillageServerConnection::HandleMessage` S 00470a90 is the only producer on the village path |
| vtable | S 007db594, 17 slots [known] |
| Methods | 35 |

| off | type | name | conf |
|---|---|---|---|
| +0x00 | void* | vftable | [known] |
| +0x04 | `NCore::ByteBuffer` (0x10) | buffer | [known] |
| +0x14 | u8 | curByte: bit accumulator, MSB-first | [known] |
| +0x18 | u32 | bitCursor | [known] |
| +0x1c | int | byteIndex | [known] |
| +0x20 | bool | namesMode: type-word bit 15; mixes type tag and width into the CRC | [known] |
| +0x24 | u32 | category = (typeword >> 12) & 7 | [known] |
| +0x28 | u32 | msgId = typeword & 0xfff | [known] |
| +0x2c | bool | finished | [inferred] |
| +0x30 | u32 | CRC32 accumulator value | [known] |
| +0x34 | u32 | CRC32 accumulated length | [inferred] |
| +0x38 | int | direction marker: 1 in the send ctor (S 0048fb66), 0 in InitFromWire (S 0048fad8), the caller's last argument in InitFromBuffer (S 0048fa29; its one caller passes 0) [known]. Write-only: no reader in the lobby-comm range S 00462000..00491000 [inferred] | [inferred] |

Multi-byte scalars written into a LobbyMessage field are big-endian [PROVEN]: the stub packs them with
`struct.pack(">I")` (`lobby/sadk_lobby/village.py`), and a little-endian PermID is dropped by S 0047ac20.

**Key methods:** ctor (send) S 0048fb00 · InitFromWire S 0048fa50 · InitFromBuffer S 0048f9a0 · WriteBits
S 0048ef70 / ReadBits S 0048f0d0 · Write/ReadInt S 0048f2c0 / S 0048f300 · WriteString S 0048fe20 ·
ReadString S 004900a0 · WriteNamedPackedUInt S 0048fb90 · ReadLocationBlock S 0048f670 · Finalize
S 0048f4c0 · FinishRead S 0048f530.

### 1.9 CharacterManager (lobby side)

| | |
|---|---|
| Ghidra struct | `/LobbyComm/CharacterManager` (`[ai]`, 0x1b8) |
| vtable | S 007dc0ac [known]; sub-objects `CharacterObserverListener` (+0x64, vtbl S 007dbb30) and `UserObserverListener` (+0x6c, vtbl S 007dbb4c) |
| Embedded at | `LobbyComm::System` +0x140 |

| off | type | name | conf |
|---|---|---|---|
| +0x08 .. +0x50 | 7 × observer list | onCharacterCreated, onCreateFailed, onBuddyUpdated, onBuddyAdded, onBuddyRemoved, onIgnoreAdded, onIgnoreRemoved | [inferred] |
| +0x5c | void* | tincat3 character interface (vtbl +0x14 Create, +0x20 Delete, +0xc LookUpName, +0x10 LookUpID) | [inferred] |
| +0x60 | void* | tincat3 user interface (friends / ignore) | [inferred] |
| +0x64 | CharacterObserverListener | `ICharacterObserver` face | [known] |
| +0x6c | UserObserverListener | `IUserObserver` face | [known] |
| +0x74 | deque<CharManAction> | action queue (count +0x84) | [inferred] |
| +0x88 | bool | characterListValid | [inferred] |
| +0x8c | std::map<uint, ICharacter*> | characters (count +0x94) | [known] |
| +0x180 | bool | buddyListValid | [known] |
| +0x184 | std::map<uint, CharMgrUserEntry> | buddies | [inferred] |
| +0x190 | bool | ignoreListValid | [inferred] |
| +0x194 | std::map<uint, …> | ignored users | [inferred] |
| +0x1a0 / +0x1ac | std::map | id→name / name→id caches | [inferred] |

**Key methods:** RequestCharacterList S 00472f00 · CreateCharacter S 004750f0 · DeleteCharacter S 004751e0 ·
SelectCharacter S 00472200 · LookUpID S 004752a0 · LookUpName S 00475370 · Add/RemoveFromFriendList
S 004754f0 / S 00475670 · ProcessActions S 00476390 · GetUserRelation S 00472a00.

### 1.10 Actors: ActorProxy, AvatarProxy, NPCProxy

`LobbyComm::ActorProxy` (0x88, vtbl S 007db574) is the abstract base of in-world actors. Its base is the
interface `LobbyComm::IActor` (vtbl S 007db558, 6 pure slots, a vptr only), at displacement 0 in the RTTI
[known]; `NPCProxy` and `AvatarProxy` derive from `ActorProxy` and embed it as `base` (0x88). No other class
in either binary lists `IActor` as a base. +0x04 holds an embedded `LobbyComm::ActorID` (`actorId`, 0xc:
vtbl S 007d6c6c, +4 actorType with 1 = avatar and 2 = NPC, +8 actorId) [known].

Vtables (`/LobbyComm/IActor_vftable` 6 slots, `/LobbyComm/ActorProxy_vftable` 7, `/LobbyComm/NPCProxy_vftable`
8; the AvatarProxy table S 007dd038 has the 7 ActorProxy slots) [known]:

| slot | name | IActor / ActorProxy | AvatarProxy | NPCProxy |
|---|---|---|---|---|
| 0 | scalar_deleting_dtor | pure / S 0046b880 | S 00481e40 | S 0047b4b0 |
| 1 | GetActorType | pure | S 00416490 (returns 1) | S 004f1ea0 (returns 2) |
| 2 | GetID (the dword at +0xc) | pure | S 0047b340 | S 0047b340 |
| 3 | GetActorID (returns this+4) | pure | S 00554a00 | S 00554a00 |
| 4 | `slot4`: no call through this slot is in the decompile cache, so its meaning is not named | pure | S 005e4e90 (returns true) | S 0041ecc0 (returns false) |
| 5 | GetActionSlots | pure | S 00482490 (zeroes 3 dwords) | S 0047b200 (copies actionIds[3] and actionArgs[3]) |
| 6 | GetLevel (introduced by ActorProxy) | – / S 0072db80 (returns 0) | S 00481990 (level, +0xcc) | S 0072db80 |
| 7 | GetNPCIndex (introduced by NPCProxy) | – | – | S 006ab260 |

The bodies of slots 1 to 4 and 7 are shared by the linker with unrelated classes and sit in the Global
namespace with the tag `ICF_SHARED`. `ActorProxy::AsAvatar` S 0046b6c0 returns `AvatarProxy*`,
`ActorProxy::AsNPC` S 0046b6d0 returns `NPCProxy*`.

| off | type | name | conf |
|---|---|---|---|
| +0x10 | std::string | rawName | [known] |
| +0x2c | std::string | displayName | [known] |
| +0x48..+0x50 | u8 × 9 | tribeGender / bodyPart, hair, skin, shirt, trouser, addColor1..4 | [inferred] |
| +0x51 / +0x52 | u8 | zone / ghostZone (0x0F none) | [inferred] |
| +0x54 | float[3] | position | [inferred] |
| +0x60 | float[4] | rotation quaternion | [inferred] |
| +0x70 | float | heading | [inferred] |

**`LobbyComm::NPCProxy`** (0x120, vtbl S 007dc7d8, ctor S 0047b280, `ReadFromMessage` S 0047b5c0 for
message 1004) [known]. Its fields beyond ActorProxy:

| off | type | name | conf |
|---|---|---|---|
| +0x88 | std::string | npcDescRaw (`npcdesc`) | [known] |
| +0xa8 | uint[3] | actionIds (`act`) | [known] |
| +0xb4 | uint[3] | actionArgs: parameters of the three action slots, copied with actionIds to WorldScreen `actionSlotCodes` / `actionSlotParams` by slot 5 (S 0047b200). Always 0 for an NPC: `ReadFromMessage` only zeroes them and message 1004 has no field for them [known]. The WorldScreen array is non-zero for a selected minigame table (`RefreshActionSlots` S 00433f60) and is read by action codes 12..15 (S 00434230) | [inferred] |
| +0xc0 | int | npcIndex (`npcidx`, 4 bits) | [known] |
| +0xc4 | int | npcType (`npctyp`, 2 bits) | [known] |
| +0xc8 | std::string[3] | actionChat (`actChat`). Written without a bound check: `actcnt` ≥ 4 overflows | [known] |

The NPCProxy vtable adds slot 7 `GetNPCIndex` (S 006ab260). Slot 5 is `GetActionSlots` S 0047b200.

**`LobbyComm::AvatarProxy`** (0xe0, vtbl S 007dd038, 30 fields) is the player avatar. It carries level at
+0xcc and gold at +0xd0 [inferred]; +0x8c is `items` (`ai::village::AvatarItemContainer`). Its data blocks
use the `LobbyComm::IAvatarDataBlock` family (vtbl S 007de3dc, 8 slots: `AvatarAppearanceBlockEx`,
`AvatarStyleBlockEx`, `AvatarStatsBlockEx`, `AvatarInventoryBlockEx`, `AvatarActiveItemsBlockEx`,
`AvatarCreationBlockEx`). The stream of that family is `NComm::MemoryStream`: `ReadFromBuffer` S 00486120 and
`WriteToBuffer` S 004861c0 build one on the stack and pass it to slots 3 and 4 (`Deserialize` / `Serialize`)
[known].

### 1.11 PostOffice, Properties, ServerMessages

| class | struct | vtable | notes |
|---|---|---|---|
| `LobbyComm::PostOffice` | 0xc4 | S 007dc958, `IMailObserver` face S 007dc93c at +0x08 | +0x0c tincat3 MailManager*; +0x10 vector<Mail(0x70)>; +0x20 currentMail; +0x90 deque<PostOfficeRequest>; +0xa8 float headersReceivedTime (re-poll after 60 s); +0xac / +0xb8 mailReceived / mailDeleted observers [inferred] |
| `LobbyComm::Properties` | 0x1c | S 007dea50, face S 007dea40 | PropertyGet/Set requests. `RequestProperty` S 0048ecb0 carries the version check (category 1, index 1) [inferred] |
| `LobbyComm::ServerMessages` | 0x3c | S 007de52c plus two faces | MotD / server messages; `Initialize` gets CommLayer vtbl 0x38/0x40 [inferred] |
| `LobbyComm::Mail` | 0x70 | S 007de8b0 | one mail record |

PostOffice key methods: RequestMailHeaders S 0047d140 · RequestMail S 0047d200 · SendMail S 0047d4a0 ·
MailHeadersReceived S 0047dce0 · MailReceived S 0047e0f0 · Process S 0047d880.

### 1.12 Server list and server descriptors

| type | size | role | conf |
|---|---|---|---|
| `LobbyComm::ServerList` | 0xac, vtbl S 007dafcc (+ S 007daf8c face) | village and game server browser; ASyncAction base. Methods: StartObservation S 00468e80, FindBestVillageServer S 00469010, RequestRefereeServer S 00468f60, GameServerAssigned S 00469ad0, CreateGameServer S 0046aaa0, UpdateGameServer S 0046aff0 | [inferred] |
| `LobbyComm::GameServerInfo` | 0x9c, vtbl S 007de8b8 | client view of one hosted game: +0x04 serverId, +0x08 name, +0x24 map name (NETMSG 170 `map`, copied from descriptor +0x48 by `UpdateFromDescriptor` S 0048da70; stored, no reader in the class or the browser dialog [known]), +0x40 "Multiplayer", +0x5c passwordRequired (descriptor +0x24 == 1), +0x5d hardcore (descriptor +0x44 == 1) [known], +0x60 wager, +0x64..+0x6c settings, +0x70 occupied count = `max_spectators` + `ai_players` (u16 descriptor +0x34 + +0x38), +0x74 `max_players` (u16 descriptor +0x30) [known], +0x78 ipOctets[4], +0x88 port, +0x8c vector<string> player names | [inferred] |
| `LobbyComm::VillageServerInfo` | 0x38, vtbl S 007dcfd4 (1 slot) | one village server row: +0x04 serverId, +0x08 name, +0x28 curPlayers, +0x2c maxPlayers, +0x30 roomKey (compared with the protocol version), +0x34 blockFlag, +0x35 isValid | [inferred] |
| `/GameServerDescriptor` | 0x5c (root) | the game's view of the descriptor tincat3 hands over, the same 24 fields at the same offsets as tincat3 `/ai/CommLayer/GameServerInfo` in the next row; read by `VillageServerInfo::UpdateFromDescriptor` S 00481640 and `GameServerInfo::UpdateFromDescriptor` S 0048da70 | [known] for the fields those two functions read, [inferred] for the others |
| tincat3 `/ai/CommLayer/GameServerInfo` | 0x5c | the descriptor tincat3 hands over: +0x00 serverId, +0x08 name, +0x0c description, +0x10 char[16] ip, +0x20 port, +0x24 password_required, +0x28 serverType, +0x29 serverSubtype, +0x2c version, +0x30 max_players (u16), +0x32 cur_players, +0x34 max_spectators, +0x36 cur_spectators, +0x38 ai_players, +0x44 hardcore, +0x48 map (char*), +0x4c running (170 decoder in `ConnectionBC::OnTinCatEvent` T 1002f5a0, descriptor base ESP+0x10) [known], +0x54 data, +0x58 dataLen | [inferred]; +0x28/+0x29 [known] |

`OnGameServerAssigned` T 10021520 checks `serverType == 4` and `serverSubtype == 5` on that descriptor
[known]. That check is the 4/5 special case that keeps the referee latch from being set. The wire form is
in [message-catalog.md](message-catalog.md).

### 1.13 Other lobby-side classes (brief)

| class | size | vtable | role |
|---|---|---|---|
| `LobbyComm::MiniGameProxy` | 0x248 | S 007dba80 | base for minigame tables (seats, chat) |
| `LobbyComm::MiniGamePokerProxy` / `DiceProxy` / `PawnChessProxy` | 0x548 / 0x3f8 / 0x2bc | S 007de740 / S 007de5c0 / – | per-game state |
| `LobbyComm::ChatChannelInfo` | 0x28 | S 007dec0c | one chat channel row |
| `LobbyComm::Logger` | 0x90 | S 007daf14 | lobby log sink |
| `LobbyComm::ASyncAction` | 0x08 | S 007deb84 (9 slots) | async-request base (ServerList, ServerMessages, CharacterManager): +4 `flag04`, +5 `busy` (`IsBusy` S 0048ee90, `TryBeginBusy` S 0048eea0, `TryEndBusy` S 0048eeb0) |
| `Lobby::CLobby` | 0x290 | S 007e599c | 3D lobby world singleton (`g_pLobby` S 008882c4) |
| `Lobby::CLobbyClient` | 0x38 | S 007e60d8 | glue: subscribes to VillageServerConnection observers (S 00503d00) |

---

## 2. Match layer (`sadk_noav.exe`, namespace `NComm`)

### 2.1 NComm_Manager

| | |
|---|---|
| Ghidra struct | `/NComm_Manager` (root, 0x410) |
| alloc | **0x410** [known] (`NComm_CreateManager` S 0040a940) |
| Class namespace | `NComm_Manager` (77 methods; a non-RTTI class namespace mirroring the root struct) |
| vtable | none [known] (+0 is data) |
| Singleton | `g_NCommManager` S 00885754, set by ctor S 0040a530 [inferred] |

The struct is as long as the allocation. +0x34 is `logicTicksPerNetTick` (`ToString` prints it under
"NSpeed") and +0x38 is `netTickLength`.

| off | type | name | conf |
|---|---|---|---|
| +0x00 | int | reconnect sub-state (1 client armed, 2 host waiting, 3 rejoined, 4 start local server) | [inferred] |
| +0x04 | float | reconnect timeout | [inferred] |
| +0x08..+0x18 | – | reconnect IP octets and port | [inferred] |
| +0x1c | `EManagerState` | state | [known] |
| +0x20 | bool | error / shutdown latch | [inferred] |
| +0x28 | int | connected human count (`CountConnectedHumans`) | [inferred] |
| +0x2c / +0x30 | int | current net tick / tick base | [inferred] |
| +0x34 | int | `logicTicksPerNetTick` = `gameSpeedMultiplier` × `netTickLength`, recomputed by `HandleEvent` S 0040e560 on events 0x20023 and 0x3000d; `AdvanceNetTick` S 00411990 resets the sub-tick counter (+0x40) when it reaches this value | [inferred] |
| +0x38 | int | `netTickLength`: base logic ticks per net tick (event 0x3000d; 4 in the ctor) | [inferred] |
| +0x3c | int | `gameSpeedMultiplier` (local event 0x20023; 1 in the ctor) | [inferred] |
| +0x50 | IEventHandler* | game event sink (set by `nGame::System::BuildWorld`) | [inferred] |
| +0x54 | `/ai/ncomm/TickPackage` | `outgoingPackage`: the local player's package for the current net tick | [inferred] |
| +0x80 | `/ai/ncomm/TickPackage` | `immediateQueue`: received immediate events, run by `Process_MainLoop` | [inferred] |
| +0xac / +0xb8 | `/ai/ncomm/TickPackageList` | `collectedPackages` (the host sends the package of netTick-1 to all as message 0x3ea) / `packagesToExecute` (the package of netTick-2 is executed) | [inferred] |
| +0xdc | `NComm::EventGameInformation` (0x24f) | `gameInformation`: the session's game information (`GetGameInformation` returns its address) | [known] |
| +0x32c | NetGUID | local player GUID | [inferred] |
| +0x340 | `NComm_INetworkHandler*` | transport (TinCatNetwork or DummyNetwork) | [inferred] |
| +0x360 | `/ai/network/NCommNetworkConfig` (0x4c) | network config | [inferred] |
| +0x3b4 | std::list<NetGUID> | players who left | [inferred] |
| +0x3c0 | void* | chat sink (vtbl[0] ToAll, [1] ToAllied) | [inferred] |
| +0x3c8 | `ENCommNetMode` | mode | [inferred] |
| +0x3cc | u8 | start-loading flag | prior |

The lists at +0x3d4..+0x404 are five observer lists: `kickNoticeObservers`, `syncStatusObservers`,
`uiNotificationObservers`, `chatToAllObservers`, `chatToAlliedObservers` [inferred].

Enums [known]: **`EManagerState`** 0 None, 1 NetworkStarted, 2 SessionStarted, 3 GameStarting,
4 GameRunning. **`ENCommNetMode`** 0 Offline, 1 LanClient, 2 LanHost, 3 InternetClient, 4 InternetHost.

**Key methods:** StartUpNetwork S 0040a9a0 · ConnectAndJoin S 0040ad60 · AssignSlotToJoiningUser
S 0040bb60 · SetSlotSetup S 0040bcd0 · SetGameSettings S 0040bfd0 · SetGameIdAndBroadcast S 0040c320 ·
BroadcastGameInfo S 004090e0 · BeginGameStarting S 0040b170 · BeginGameRunning S 0040b270 · HandleEvent
S 0040e560 · Process_MainLoop S 00410f70 · AdvanceNetTick S 00411990 · IsGameHanging S 00408860 ·
Shutdown S 0040b410.

### 2.2 EventGameInformation (session / pre-game room)

| | |
|---|---|
| Ghidra struct | `/NComm/EventGameInformation` (`[ai]`, 0x24f) |
| vtable | S 007d4e5c [known] |
| Event type | 0x30003 [known] |
| Methods | 60 |

| off | type | name | conf |
|---|---|---|---|
| +0x00..+0x0c | – | EventBase header (vftable, typeId, sourceNetId, playerId) | [known] |
| +0x10 | `NComm::PlayerInfo[6]` | slots, stride 0x4c (`eh_vector_constructor_iterator(0x4c, 6, PlayerInfo::ctor)`) | [known] |
| +0x1d8 | std::string | game name | [guess] |
| +0x1f4 | NetGUID (0x14) | map GUID → `RegisterGame MapGUID` | [inferred] |
| +0x208 | std::string | map name → `RegisterGame MapName` | [inferred] |
| +0x224 | u8 | maxPlayers (slot loop bound) | [inferred] |
| +0x225 / +0x226 / +0x227 | u8 | `winCondition`, `startResources`, `fogOfWar`: MapSettings digits 1..3 (`'0'` + value, S 004145f0). A lobby match stores the WinCondition drop-down index + 1 (`SetupGameDialog::OnMapSelected` S 00454ad0; the lobby drop-down has three entries), so its value is 1 destroy all enemies, 2 conquer or 3 coin, never 0 (endless). The free game stores its four-entry index unchanged, 0..3. Mode 3 counts deliveries of the tribe's coin: a team wins when its summed counters exceed 99 | [known] |
| +0x228 | bool | fetch-map-from-host flag: on a client whose map lookup by GUID fails in event 0x30003, clear -> self-kick `!MAP NOT EXISTING`; set and +0x229 == 3 -> `RequestFileFromHost` S 004084d0 for `<My Documents>\SAdK\maps\<mapName>.s2m` and `.bmp`; set and +0x229 != 3 -> self-kick (S 0040eeb3 .. S 0040f30d) [known]. Only writer besides Reset (0) and the copies is `SetGameSettings` (S 0040c137), and its three callers (S 00454c87, S 0046ad82, S 005da0e1) pass 0, so this build never sets it locally [known]. Serialized, in the settings CRC. The name is [inferred] from the reader branch. The two values are arguments of `SetGameSettings`, so a hook of that function sets them without a memory write (the assetshare mod does); the fetch with both forced is recorded live in `docs/BINARY_PATCHES.md` | [inferred] |
| +0x229 | u8 | map type of the chosen map: `SetGameSettings` (S 0040c11e) gets `MapInfo +0x1d0` from `OnMapSelected` S 00454ad0 and `CreateGameServer` S 0046aaa0, and the literal 0x6e from `nMenu::System::StartPendingMap` (S 005da0c9); Reset 0xff [known]. `GameFile_LoadMapInfo` S 005aaa30 writes `MapInfo +0x1d0` = the type under which the file was found when it is not the requested one (fallbacks 3, `.usermapinfo`, then 10), so 3 = a user map [inferred]. Only reader: event 0x30003 (== 3, S 0040ef9d). Serialized, in the settings CRC. The values are the `MapPath` types of `docs/sim/save-format.md` §2.6 (0 free game map, 1 campaign, 2 tutorial, 3 `<My Documents>\SAdK\maps`, 10 `.sav`, 100..103 the same four folders, 0x65 `.a2m`, 0x6e `.aav`). The lobby asks for type 0 with fallbacks (S 00454ad0), so a stock map sends the `mapType` stored in its file (0 in the shipped maps) and a map from the Documents folder sends 3 [known] S 005aaa30. A host running the assetshare mod always sends 3, and `+0x228` = 1 (its hook of `SetGameSettings`) | [known] |
| +0x22a | int | gameId → `RegisterGame` / `FinishGame` GameID | [inferred] |
| +0x22e | u8 | rankedGame | [inferred] |
| +0x22f | int | game seed: the referee's GameSeed (`SetGameSeed` S 004139f0 <- `SetGameSeedIfState2` S 004082e0 <- S 00431800 only). Seeds only the chest-content generator of a network match (`GetGameSeed` S 004139e0 <- S 005ac7ed, S 00775e1f), not the simulation generator S 00889b08. Serialized, in the settings CRC, Reset 0 | [known] |
| +0x233 | int | wager, in gold: `GetWager` S 00413a00, `SetWager` S 00413a10; serialized in the game information, sent as `RegisterGame Wager` | [known] |
| +0x237 | u32 | settingsCrc (`GetSettingsCrc`); the setup dialog restarts its 3500 ms countdown when it changes | [inferred] name |
| +0x23b | NComm::MD5Digest (0x14) | password MD5, zero = none; not serialized | [inferred] |

**Key methods:** Serialize S 00413ae0 · ctor_Deserialize S 00413e00 · GetSlot S 00413100 ·
AreAllSlotsReady S 00413400 · AreAllSlotsLoaded S 00413500 · AssignRandomPlayerIndicesAndTeams S 00413930 ·
GetSettingsCrc S 00413a50 · UpdateSettingsCrc S 00414720 · GetSettingsDigitString S 004145f0.

### 2.3 Player slot: `NComm::PlayerInfo`

The slot record is the RTTI class `/NComm/PlayerInfo` (vtbl S 007d4ee0, ctor S 00415230). All three
`EventGameInformation` constructors build the six slots with it, and its accessors (S 00414d10..00415430)
are methods of this class.

| off | type | name | conf |
|---|---|---|---|
| +0x00 | void* | vftable | [known] |
| +0x04 | u8 | state (ctor 5; SetupAi 1, SetupClosed 4, ResetToOpen 0) | [known] |
| +0x05 | u32 | playerId (0xEFFFFFEE none, 0xEFFFFFCC host) | [known] |
| +0x09 | `NComm::NetGUID` (0x14) | owner GUID object: vftable pointer at +0x09 (ctor stores S 007d42b4), data at +0x0d. Serialized raw as 0x14 bytes, pointer included (S 00415084, S 00415154) | [known] |
| +0x0d | u8[16] | owner GUID (the data part of the NetGUID at +0x09) | prior (`pOwnerGuid`) |
| +0x1d | `EConnectionType` (u8) | connection type, 0..4: the joiner's `UserProfile +0x94`, sent in `EventUserInformation +0x48` (S 0040af35) and stored by the host at S 0040e8de; shown by `nMenu::NetInfo::RefreshInfo` S 005fd96c | [known] |
| +0x1e | std::string | player name | [known] |
| +0x3a | u8 | playerIndex (ctor 0xff) | [known] |
| +0x3b | `EPlayerSlotKind` | 0 Open, 1 Human, 2 AI, 3 Closed | [known] |
| +0x3c | u8 | aiLevel | [inferred] |
| +0x3d | u8 | tribe (-> `NComm_GetNationIdForTribe` -> load descriptor +0x68, S 004562d0) | [known] |
| +0x3e | u8 | color (-> load descriptor +0x88) | [known] |
| +0x3f | u8 | team (-> load descriptor +0xa8 -> `Player.team` +0x94, `Player::IsEnemyOf` S 005be280); 0xff = no team | [known] |
| +0x40 | u8 | readyState: 0 not ready, 1 ready (event 0x30011), 2 loaded (event 0x30004; also AI, closed and dropped slots); written through the folded setter S 00552f10 | [known] |
| +0x41 | u16 | avatar look of the joined user, three nibbles (ctor 0xffff = unset): written by `SetAvatarTribeGenderLevel` S 00415000 from `EventUserInformation +0x50`, read by `GetAvatarTribeGenderLevel` S 00414fc0 for the room's avatar preview [known]. Nibble order bits 8..11 tribe, 4..7 gender, 0..3 level [inferred] | [known] |
| +0x43 | u32 | avatar colours of the joined user, eight 4-bit values, low nibble first (S 0041f2f0, S 00456182); -1 unset; from `EventUserInformation +0x54` | [known] |
| +0x47 | u32 | lobby AvatarID of the joined user, 0 none; from `EventUserInformation +0x58`, unchecked by the host. Readers (`GetAvatarId` S 00415050): `RegisterGame` AvatarID list S 004322b0, `FinishGame` Winner S 00535ac9, `ClaimChest` S 00782ae1, chat sender id S 0040e46f / S 0040e520 | [known] |
| +0x4b | u8 | local only, not serialized [known]: latch "the left-game notice was shown for this slot" (set to 1 after the notice, S 004108c5, S 0040fb5b, S 00410c0b, S 00410e40; read through the folded getter S 0046b5f0) | [inferred] |

### 2.4 Event family

`NComm::EventBase` (0x10, vtbl S 007d4274): +0x04 typeId (`NE_EventType`; 0x3000x network, 0x2xxxx game),
+0x08 sourceNetId, +0x0c playerId [known]. **`/NComm/EventBase_vftable`** [known]:
0 sdtor S 00408720 · 1 GetType S 004901e0 · 2 CopyType S 00408210 · 3 Serialize S 004085a0 · 4 ToString
S 0040c680 · 5 GetClassSignature S 00408240 · 6 CopyHeader S 00408220.

| class | size | vtable |
|---|---|---|
| `Event1Integer` .. `Event4Integer` | 0x14 .. 0x20 | S 007d4294, S 007d5c88, S 007d5ca8, S 007d5cc8 |
| `EventInt64`, `EventInt64_1..3Integer` | 0x18 .. 0x24 | S 007d5ce8 .. S 007d5d48 |
| `EventData` | 0x1c | S 007d5d68 |
| `EventText` | 0x2c | S 007d43a8 |
| `EventPlayerInformation` | 0x34 | S 007d42c0 |
| `EventUserInformation` | 0x70 | S 007d4368 |
| `EventUserChecksum` | 0x2c | S 007d4300 |
| `EventUserLeave` / `EventUserLeft` | 0x24 / 0x2c | S 007d4320 / S 007d4340 |
| `EventUserReJoinGame` | 0x28 | S 007d42e0 |
| `EventKickUser` | 0x2c | S 007d4388 |
| `EventSaveGame` | 0x40 | S 007d5d88 |

Supporting types: `NComm::NetGUID` (0x14, vtbl S 007d42b4, four u32 parts; `IsValid` S 004162c0 requires
all four to be non-zero) [known] · `NComm::MD5Digest` (0x14, vtbl S 007d424c) · `NComm::MemoryStream`
(0x1c, vtbl S 007d4dc0).

### 2.5 TinCatNetwork (match transport)

| | |
|---|---|
| Ghidra struct | `/NComm/TinCatNetwork` (0xec) |
| vtables | S 007d58f4 (primary, INetworkHandler-shaped), S 007d58ac (`ITinCatCallback` face at +0x04, 16 `cb_` slots) [known] |
| Alternative | `NComm::DummyNetwork` (vtbl S 007d5a6c), the offline transport |

| off | type | name | conf |
|---|---|---|---|
| +0x08 | TinCat_CTRL* | tincat3 API (vtbl +0x98 Send_Data, +0x9c Send_DataToServer) | [known] |
| +0x0c | void* | reconnector holder (+4 = `TinCatModules::Reconnector*`) | [inferred] |
| +0x10 | u32 | localNetId (0xEFFFFFEE, 0xEFFFFFCC when hosting) | [known] |
| +0x14 | std::list<TinCatUserEntry> | users | [known] |
| +0x20 / +0x24 | u32 | LAN broadcast mode (0 off, 1 client, 2 host) / active | [inferred] |
| +0x28 | std::map<uint, ServerRecord> | LAN servers | [known] |
| +0x48 | `/ai/network/BCGameInfo` (0x90) | own LAN game info | [inferred] |
| +0xdc | void* | receive buffer (0x400) | [known] |
| +0xe4 | void* | file transfer (message type 0x3eb) | [inferred] |
| +0xe8 | HANDLE | mutex | [known] |

**Key methods:** StartUp S 0041e610 · ConnectToServer S 0041a1b0 · Process S 00419e10 · Broadcast S 0041db50 ·
SendToHost S 0041dbb0 · SendTo S 0041dc30 · cb_Received_Data S 0041d720 · cb_LoggedIn S 0041eb10 ·
BC_Start S 0041aa90 · ShutDown S 0041cc20.

**`/ai/network/BCGameInfo`** (0x90) is the payload of the `S2TNG-BC` LAN broadcast record. Fields: +0x00
`serverId`, +0x04 `gameName`, +0x20 `mapName`, +0x3c a std::string that is not serialised, +0x58
`connectedHumans`, +0x5c `maxPlayers`, +0x60 `hostIp` (int[4], one octet per dword), +0x70 `gamePort`, +0x74 a
trailing std::string that no code assigns. Wire order (`Serialize` S 00419330; `NComm::MemoryStream`,
little-endian, string = u16 length + bytes) [known]:

| # | field | width | host value (`BC_Start` S 0041aa90, `BC_Update` S 0041adb0) |
|---|---|---|---|
| 1 | serverId | u32 | 0xFFFFFFFF; the receiver replaces it with its own key of the LAN server map |
| 2 | gameName | string | `EventGameInformation::GetGameNamePtr` |
| 3 | mapName | string | `EventGameInformation::GetMapName` |
| 4 | connectedHumans | u32 | `CountConnectedHumans` S 004133c0 (human slots with a playerId other than 0xEFFFFFEE) |
| 5 | maxPlayers | u32 | `GetMaxPlayers` S 00412fc0 |
| 6..9 | hostIp[0..3] | 4 × u32 | 0xFFFFFFFF each; the receiver writes the source address of the reply |
| 10 | gamePort | u32 | `NCommNetworkConfig.gamePort`; the receiver takes the value field of the TinCat record |
| 11 | trailing string (+0x74) | string | empty; read only when bytes remain |

---

## 3. tincat3.dll

### 3.1 CommLayer::CommLayer (root object)

| | |
|---|---|
| Ghidra struct | `/CommLayer/CommLayer` (0x68) |
| vtable | T 1004ec6c, 23 slots [known] (`ICommLayer` base T 1004eb74) |
| ctor | T 10018660 |

| off | type | name | conf |
|---|---|---|---|
| +0x04 | int | connMgrType: 0/1 INet, 2 LAN, 3 LAN_GS | [known] |
| +0x08 | void* | ticket table | [known] |
| +0x0c | ConnectionManager* | new 0x5c0 INet / 0xbc LAN | [known] |
| +0x10..+0x4c | manager pointers | GameServer (0x50), Character (0x34), User (0xe8), Guild (0x78), Property (0x30), Group (0x60), CDKey (0x1c), Machine (0x4c), Backup, ClosedNet, ChatChannel (0x38), Mail (0x38), MotD, ServerInfo (0x28), CyclicMsg (0x24), Broker (0x24) | [known] |
| +0x50 | TokenValidator* | new 0x28 | [known] |
| +0x54 | Authenticator* | new 0x890 | [known] |
| +0x58 | void* | request-context table | [known] |
| +0x5c | RankingManager* | new 0x18 | [known] |
| +0x60 | BL_Logger* | log | [inferred] |
| +0x64 | u32 | payloadMagic: 0x26B6 for the lobby | [known], value **[PROVEN]** |

**`/CommLayer/CommLayer_vftable`**: slots 1–20 are getters for the managers in field order (ICF-folded
getters such as T 10037c50 for +0x0c) [inferred]. Slot 21 `Process` (`CommLayer::CommLayer::Update` T 10018630) is the tick. Slot 22
`Release` T 10006e80 (a folded body that deletes the object through its vtbl[0]).

### 3.2 Connections

| class | size | vtable | role |
|---|---|---|---|
| `CommLayer::Connection` | 0x24 | T 1004ed44 | base: +0x04 owner, +0x08 state, +0x0c connType (0 lobby, 1 usercomm, 2 game server), +0x10 connectionId, +0x14 host, +0x18 port, +0x1c serverId, +0x20 permId |
| `CommLayer::ConnectionReal` | 0x58 | T 10051694 | TCP connection to a server (below) |
| `CommLayer::ConnectionDummy` | 0x28 | T 10051604 | offline stand-in |
| `CommLayer::ConnectionBC` / `ConnectionLANLobby` | 0x40 / 0x44 | T 100515bc / T 1005164c | LAN |
| `CommLayer::ConnectionManager` | 0xbc | T 1004eddc | holds the lobby (+0x14), UC (+0x18) and game-server (+0x1c) connections. +0x08 `callback` is the application's `CommLayer::IConnectionCallback`, set by slot 1 `SetCallback` T 10019430: the game registers its `LobbyComm::System` there, and the handlers call its vtbl+4 `OnLoggedIn(conn, permId, 0)` and vtbl+8 `OnLoginFailed(conn, code)` [known]. +0x20 `propertyFactory`, +0x24 `permId`, +0x38 `sessionKey` (0x80 bytes), +0xb8 `sessionKeyLen` |
| `CommLayer::ConnectionManagerINet` | 0x5c0 (alloc) | T 1005186c | Internet variant; LoginUser T 10030f00, RegisterUser T 10030e90, EnterServer T 10031050 |
| `CommLayer::CommLayerTinCat` | 0x20 | T 1004eccc | adapter between a Connection and the `TinCat_CTRL` API |

**`/CommLayer/Connection_vftable`** (17 slots) [inferred unless noted]: 0 sdtor · 1 GetConnectionId ·
2 return 0 · 3 GetState · 4 Connect · 5 ConnectWithData · 6 Disconnect · 7 SendGameData [guess] ·
8 SendBroadcast · 9 return 0 · 10 nop · 11 SendRawData · 12 SendData (all managers send through
vtbl+0x30) · 13 OnTinCatEvent · 14 [guess] · 15 Update · 16 return 0.

**ConnectionReal fields:**

| off | type | name | conf |
|---|---|---|---|
| +0x08 | int | state: 0 idle, 1 locating, 2 connecting, 3 connected, 8 logged in [inferred], 9 disconnecting | [known] |
| +0x0c | int | connType | [inferred] |
| +0x14 / +0x18 | int | server IP / port | [guess] |
| +0x1c | u32 | serverId (from NETMSG 192) | [inferred] |
| +0x20 | int | permId | [inferred] |
| +0x24 | void* | transport (CommLayerTinCat) | [known] |
| +0x28 | int | tincat connect handle (-1 none) | [known] |
| +0x2c | u32 | sessionId (0xefffffee invalid) | [known] |
| +0x30 | PropertyDataConverter* | converter | [known] |
| +0x34 | IPropertySet* | scratch set | [known] |
| +0x38 | void* | listener = the CommHandler (vtbl +4 OnLoggedIn, +8 OnLoggedOut, +0x10 OnPacket) | [inferred] |
| +0x40 / +0x44 | void* / u16 | server data blob (the 222 nonce) and its length | [known] |
| +0x54 | ICellManager* | for connType 1 only | [known] |

Key methods: Connect T 100309d0 · ConnectWithData T 10030a30 · SendData T 100306b0 · HandlePacket T 100307a0 ·
OnTinCatEvent T 10030ad0.

### 3.3 Message handlers

All derive from `CommLayer::CommHandlerBase` (0xc, vtbl T 1004eb54, ctor T 10018510). Each handler
has +0x04 `commLayer` (CommLayer*) and +0x08 `connection` (ConnectionReal*) [inferred].

| class | size | vtable | slot 1 | slot 4 HandleMessage | slot 5 |
|---|---|---|---|---|---|
| `HandlerLobby` | 0x10 | T 1004f950 | T 10023bf0 Start (sends 188 CheckVersion) | T 10023cc0 | T 10023be0 returns 5 |
| `HandlerUserComm` | 0x0c | T 1004f9dc | T 10023bf0 OnLoggedIn (188) | T 10027080 | T 10027630 RequestServerAssign (189, server_type 2) |
| `HandlerGS` | 0x0c | T 1004f8dc | T 10023bf0 | T 10023460 | T 10023af0 RequestConnectionData (221) |
| `HandlerStatSurf` | 0x0c | T 1004f9c0 | T 10026820 (188, version 27) | T 100268e0 | T 10023be0 |

Slot 0 is the shared sdtor T 100267e0, and slots 2–3 are nops [known]. `HandlerLobby` +0x0c is authMode:
0 SelfRegistration (203), 1 AuthenticateUser (204), 2 AuthenticateSupport (205), 3 AuthenticateServer
[inferred].

### 3.4 Authenticator

| | |
|---|---|
| Ghidra struct | `/CommLayer/Authenticator` (`[ai]`, 0x890 = alloc [known]) |
| vtable | T 10051444, 18 slots [known]; `IAuthenticator` base T 1004fd04 |

| off | type | name | conf |
|---|---|---|---|
| +0x04 | CommLayer* | owner | [known] |
| +0x08 | u16 | prngIdx (`find_prng("sprng")`) | [known] |
| +0x0a | u16 | hashIdx (`find_hash("sha512")`) | [known] |
| +0x0c | u16 | cipherIdx (`find_cipher("twofish")`) | [known] |
| +0x0e | byte[0x800] | scratch | [inferred] |
| +0x80e | byte[16] | CTR IV | [inferred] |

vtable slots (all [known] except slot 6): 1 GenerateKey T 1002aac0 · 2 GenerateSharedSecret T 1002ac40 ·
3 DecryptSharedSecret T 1002ade0 · 4/5 Encrypt/DecryptCreateUserData · 6 FreeCreateUserData [inferred] ·
7/8 Encrypt/DecryptCredentials T 1002b560 / T 1002b830 · 9 HashCDKeys · 10 HashPassword T 1002bca0 ·
11/12 Generate/DecryptSessionKey · 13/14 Generate/DecryptToken T 1002c090 / T 1002c430 · 15 CreateTAN ·
16/17 Encrypt/DecryptString.

The login handshake is ECDH secp521r1 plus Twofish-CTR over libtomcrypt [PROVEN]: the stub completes login
with it.

### 3.5 Managers (selection)

| class | size | vtable | notes |
|---|---|---|---|
| `CommLayer::CharacterManager` | 0x34 | T 1004e930 | +0x04 listener, +0x08 owner, +0x0c..+0x18 busy flags (request, add, change, remove), +0x1c embedded UList<Character*> [inferred] |
| `CommLayer::Character` | 0x58 | – | record: +0x00 charId, +0x04 name, +0x08 ownerId, +0x10 guildId, +0x20 serverId, +0x28 six data blocks, +0x40 their sizes [known/inferred] |
| `CommLayer::GameServerManager` | 0x50 (alloc) | T 1004f7bc | +0x04 listener, +0x08 commLayer, +0x0c request pending, +0x10 kick pending, +0x4c check-player callback; AssignServer T 10021830, OnGameServerAssigned T 10021520, CreateGameServer T 10020ca0 |
| `CommLayer::UserManager` | 0xe8 (alloc) | T 1005152c | users, buddies, ignore, character lists (37 methods) |
| `CommLayer::MailManager` | 0x38 | T 1004fb7c | +0x04 observer, +0x24..+0x34 busy flags per NETMSG 147/148/151/150 [known] |
| `CommLayer::TokenValidator` | 0x28 | T 1004fd50 | permId token slots; SendValidateToken T 1002cc70 |
| `CommLayer::RankingManager` | 0x18 | T 1004fc7c, `IConnectionCallback` face T 1004fc5c at +0x04 | +0x08 observer, +0x10 `loggedIn`, +0x14 ranking connection. `HandlerStatSurf::HandleMessage` T 100268e0 forwards 253, 255 and 257 to it. Message 255 reaches slot 10 as (ranktable, perm_id, nick, rank, points, played, won, lost, tie, disconnected); `played` is not read from the message, the handler computes it as won + lost + tie + disconnected [known]. Client defect: after a refused token (AddResult 153 with errorcode != 0) the handler calls the face's `OnError` (T 10026cf2), disconnects (T 10026cfc) and then still calls `OnLoggedIn` (T 10026d25, body T 10029cd0), so `loggedIn` becomes 1 on a closed connection [known]. The game installs no ranking observer |
| `CommLayer::ChatChannelManager` | 0x38 | T 1004ea94 | chat channels (UC connection) |
| `TinCatModules::CellManager` | 0x108 | T 1004dea4 | cell messages on the UC connection (55 methods) |

### 3.6 TinCatProperties: PropertySet and Property

Messages inside tincat3 are property sets built from the msgdefs schema (`ConnectionManager +0x20`
property factory, filled by `LoadMsgDefs` T 1001f6e0) [known]. Without an ini path `LoadMsgDefs` falls
back to the schema compiled into the DLL, `CommLayer_RegisterBuiltinMsgDefs` T 10019ad0: 221 message
types (ids 1..262) with 1106 fields, identical to the shipped `msgdefs.ini` in every type, field name,
field order, field type and length [known].

**`TinCatProperties::PropertySet`** (0x20, vtbl T 1004dcac, 66 methods): +0x04 embedded `UList` of
properties, +0x0c list iterator, +0x1c enumeration iterator [known]. Typed accessors come in Set/Get pairs
per wire type: UNBYTE, SIBYTE, UNSHORT, SISHORT, UNLONG, SILONG, UNINT64, SIINT64, SIFLOAT, SIDOUBLE,
LBOOL, STRING, WSTRING, MEMBLOCK (T 10013e00 .. T 10014310). Further methods: CreateProperty T 100139e0,
GetProperty T 10013d00, CloneFrom T 10013ba0.

**`TinCatProperties::Property`** (0x38, vtbl T 1004e5ac, 62 methods):

| off | type | name | conf |
|---|---|---|---|
| +0x04 | `/ai/tincat/mstring` | name | [known] |
| +0x10 | `ETinCatPropertyType` | type | [known] |
| +0x14 | mstring | string value | [known] |
| +0x20 | u32 | size / max length | [known] |
| +0x28 | u64 | scalar value, or heap block pointer for MEMBLOCK/WSTRING | [known] |
| +0x30 | void* | owner set | [inferred] |
| +0x34 | u32 | owned by the set: 0 from `Init` T 10013560 (caller-constructed property), 1 for a property the set allocates itself in `PropertySet::CreateProperty` (T 100139b4, T 10013a20); `RemoveProperty` T 10013aa0 (T 10013b04) and `RemoveAllProperties` T 10013b30 (T 10013b54) delete only properties with it set. Copied by the copy ctor and operator= | [known] |

`/TinCatProperties/Property_vftable` (0xc8) names 24 Set/Get slots [known].
`TinCatProperties::PropertyDataConverter` (0xc) converts between a property set and wire bytes.

### 3.7 TinCat_CTRL (transport API)

`/TinCat_CTRL` (0x514, vtbl T 1004cfcc, 73 slots read; `ITinCatAPI` base T 1004ce04; 87 methods) is the
object `TinCat_CreateAPI` returns. Fields: +0x2c network core, +0x30 user callbacks, +0x34 extension
list, +0x4c `PROGFLOW_NET`, +0x50 mode (1 server, 2 client), +0x54 / +0x58 `TinCat_Values`, +0x5c
moduleId (the payload magic), +0x60 server connection id, +0x4f8..+0x508 synchronous send/wait state
[known/inferred]. The 28-byte TinCat frame header itself is not a Ghidra struct. It is documented in
[LOBBY_PROTOCOL.md](LOBBY_PROTOCOL.md) [PROVEN].

---

## 4. Game-side families (brief)

Roles come from class and method names and are [inferred] unless stated otherwise. "size" is the Ghidra
struct size and "vtable" the primary RTTI vftable. "fn" is the number of functions in the class namespace.

**nGame** (game shell)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `nGame::System` | 0x648 | S 008350e8 | 83 | game session root; `BuildWorld` S 00784d40 wires NComm |
| `nGame::Camera` | 0xe0 | S 00835294 | 31 | in-game camera |
| `nGame::Cursor` | 0x2c0 | S 008352b8 | 21 | map cursor / picking |
| `nGame::Autosave` | 0x10 | S 008353d0 | 2 | autosave timer |

**NLogic** (simulation core, 50 classes)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NLogic::System` | 0xf4 | S 007e7958 | 18 | logic root (absorbed the PRIOR `/GameSystem`) |
| `NLogic::CallbackManager` | 0x3c | S 007e79bc | 60 | game-logic event broadcaster |
| `NLogic::Stock` | 0x1c | S 007e7cf8 | 23 | goods stock |
| `NLogic::MapInfo` | 0x210 | S 007e79f0 | 33 | map metadata |
| `NLogic::PlayerStatistics` | 0xb4 | S 007e7d88 | 16 | per-player stats |
| `NLogic::Quests` | 0xdc8 | S 007e7b24 | 8 | quest state |

**NVillage** (buildings and economy, 22 classes)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NVillage::System` | 0xc0 | S 007e93cc | 51 | building registry |
| `NVillage::Building` | 0x140 | S 007e9504 | 28 | building instance |
| `NVillage::Military` | 0x98 | S 007e95e0 | 33 | military building part |
| `NVillage::OrderSystem` | 0x410 | S 007e9710 | 16 | production / transport orders |
| `NVillage::Depot` | 0x88 | S 007e9434 | 16 | storehouse |
| `NVillage::Construction` | 0x80 | S 007e95a0 | 23 | construction site |

**NSettlers** (units, 11 classes)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NSettlers::System` | 0x68 | S 007f8394 | 30 | settler registry |
| `NSettlers::Settler` | 0x118 | S 007f83bc | 22 | base unit |
| `NSettlers::Worker` | 0x480 | S 007f84dc | 36 | worker |
| `NSettlers::Soldier` | 0x398 | S 007f842c | 39 | soldier |
| `NSettlers::Carrier` | 0x200 | S 007f847c | 27 | carrier |
| `NSettlers::Specialist` | 0x1b0 | S 007f8604 | 13 | specialist (geologist, pioneer …) |

**NNet / NTransport / NMovement** (roads and logistics)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NNet::System` | 0x294 | S 007f8798 | 37 | road network |
| `NNet::Street` | 0x108 | S 007f8814 | 26 | road segment |
| `NNet::Flag` | 0x1b8 | S 007f8848 | 21 | flag node |
| `NTransport::System` | 0x454 | S 007f81d8 | 25 | goods transport |
| `NTransport::NeedSystem` | 0x38c | S 007f831c | 17 | goods demand |
| `NMovement::StreetPath` | 0x4c | S 0083420c | 14 | path on roads |

**NMilitary / NNavy**

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NMilitary::Fight` | 0xd0 | S 007e99cc | 44 | combat resolution |
| `NMilitary::System` | 0x20 | S 007e998c | 10 | military root |
| `NNavy::System` | 0x68 | S 007eb3d0 | 20 | ships root |
| `NNavy::Ship` | 0x50 | S 007eb56c | 16 | ship |
| `NNavy::Expedition` | 0x50 | S 007eb424 | 18 | expeditions |

**NMap / NResources / NPlayer**

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NMap::System` | 0x58 | S 007f890c | 9 | map root |
| `NMap::Continents` | 0x3c | S 007f8a34 | 12 | landmass partition |
| `NMap::AStar` | 0x48 | S 007f89c8 | 11 | path search |
| `NResources::System` | 0x64 | S 007e7ed8 | 29 | natural resources |
| `NResources::Animal` | 0xb8 | S 007e7ef8 | 18 | animals |
| `NPlayer::Messages` | 0x28 | S 007eb744 | 17 | player message log |

**NAI** (computer opponent, 84 classes)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `NAI::System` | 0x90 | S 007e9db4 | 14 | AI root |
| `NAI::Player` | 0xd4 | S 007e9de4 | 36 | per-AI player |
| `NAI::Cell` / `CellSystem` | 0x160 / 0x10c | S 007ea25c / S 007e9f24 | 30 / 16 | map cell analysis |
| `NAI::MilitarySystem` | 0x29c | S 007e9e14 | 17 | AI military planning |

**NMovie** (unit task scripts, 62 classes): small task objects (`GoDigging` 0x58 S 00834944,
`EnterBuilding` 0xc S 0083449c, `Pickup` 0x10 S 008345fc, …), each with a vtable of about 7 slots.

**S2CG / S2CE** (renderer and engine)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `S2CG::Scene` | 0x734 | S 007f8f2c | 94 | game scene |
| `S2CG::CCharacterMgr` | 0x168 | S 007f9a80 | 33 | character rendering |
| `S2CG::CMapRenderer` | 0xf8 | S 007f9504 | 30 | terrain / map rendering |
| `S2CG::BuildingRenderer` | 0x1d8 | – (no RTTI) | 32 | building rendering |
| `S2CE::CGraphicDevice` | 0x530 | – | 79 | D3D device wrapper |
| `S2CE::CShaderProgram` | 0x78 | – | 45 | shaders |

**nUi / nMenu / LobbyMenu** (user interface)

| class | size | vtable | fn | role |
|---|---|---|---|---|
| `nUi::Object` | 0x198 | S 007df5c4 | 88 | widget base |
| `nUi::ChatSystem` | 0x3358 | S 007dfcc4 | 28 | chat UI |
| `nMenu::Game` | 0x11038 | S 007eed48 | 59 | in-game HUD |
| `nMenu::System` | 0xb8 | S 007ed0bc | 34 | menu root |
| `LobbyMenu::System` | 0x5d8 | S 007d689c | 56 | lobby UI root |
| `LobbyMenu::WorldScreen` | 0x3670 | S 007d6eac | 57 | 3D-world screen |
| `LobbyMenu::SetupGameDialog` | 0xbc0 | S 007d931c | 38 | pre-game room dialog |

**NCore** (utilities): `NCore::BitStream` (0x20, S 007da874, 56 fn), `NCore::ByteBuffer` (0x10,
S 007da868), `NCore::CRCStream`, `NCore::FileStreamCrypt`. `NCore::IUpdateable` and `IRenderable` are
vptr-only interfaces (4 bytes); `NCore::UUID` is 0x18 and `NCore::Unique` 0x10 bytes.

---

## 5. How types are organised in Ghidra

### 5.1 Categories

| Category | Contents | Owner |
|---|---|---|
| `/<Namespace>/<Class>` (e.g. `/LobbyComm/PostOffice`) | class structs at the path Ghidra's class mapping looks up | RTTI-created ("PlaceHolder Class Structure"), filled by the run |
| `/<Namespace>/<Class>_vftable` | vtable struct, one typed function pointer per slot | `[ai]` (212 in sadk, 43 in tincat3) |
| `/ai/<subsystem>/<Name>` | non-class structs, enums and funcdefs from the mapping run (e.g. `/ai/lobby/ObserverList`, `/ai/ncomm/ENCommNetMode`) | `[ai]` |
| root `/<Name>` (e.g. `/NComm_Manager`, `/GameServerDescriptor`, `/LobbyManagerState`) | hand-made types from before the run (PRIOR) that are still in use; their fields are corrected like any other type | PRIOR |
| `/Demangler/...` | types the demangler created from symbol names (26 sadk, 23 tincat3) | Ghidra |
| Windows / CRT headers (`/winnt.h`, `/crtdefs.h`, …) | imported library types | Ghidra |

Counts in the final dump [known]:

| | sadk_noav.exe | tincat3.dll |
|---|---|---|
| data types | 2875 (2061 struct, 483 typedef, 230 funcdef, 85 enum, 16 union) | 371 (286 struct) |
| `[ai]`-owned types | 1506 | 157 |
| types under `/ai/` | 896 | 99 |
| class namespaces | 1678 (795 with an RTTI vftable) | 122 (93 with a vftable) |
| `ai::…` class namespaces | 591 | 14 |
| structs ≤ 1 byte | 34 | 6 |

**PRIOR vs `[ai]`.** A PRIOR type is a hand-made type from before the mapping run; an `[ai]`-owned type
carries `[ai]` in its description. Both are edited when the evidence supports it: a PRIOR field name that
is wrong is replaced, and the field comment keeps the old name ("Was ..."). Many `[ai]` types absorbed a
PRIOR duplicate; the description says so and lists the old fields (for example `LobbyComm::System`, which
absorbed `/LobbyManager`, `LobbyComm::ServerList`, `RefereeServerConnection`, `GameServerConnection`,
`NLogic::System`, `nMenu::System`). The duplicates `/LobbyManager`, `/LobbyVillageScreen`,
`/LobbyServerList`, `/NetMsgStream`, root `/LobbyMessage`, `/NCommGameSlot`, `/TinCatProperty`,
`/TinCatPropertySet`, `/TinCatPropDataConverter`, `/SecuredPostOffice`, `/SecuredPostOfficeEntry` and `/CApp`
no longer exist.

### 5.2 Class namespaces mirror struct paths

Ghidra types `this` for a `__thiscall` method from its namespace. A method in class `A::B` gets
`/A/B * this`. The mapping relies on that:

- RTTI classes keep their RTTI namespace (`LobbyComm::PostOffice` → `/LobbyComm/PostOffice`).
- A non-RTTI owner of an `/ai/<sub>/<Name>` struct gets the class namespace `ai::<sub>::<Name>`
  (e.g. `ai::net::TCPtrList` → `/ai/net/TCPtrList`).
- A root PRIOR struct gets a root class namespace of the same name (`NComm_Manager`).

Pitfall: a namespace whose name differs from the struct path does not type `this`. The lobby root object
follows the rule: its methods are in `LobbyComm::System` and its struct is `/LobbyComm/System`. Only its four
static functions (`LobbyManager_GetInstance` and so on, which take no `this`), the global `g_pLobbyManager`
and the enum `LobbyManagerState` keep the older name.

### 5.3 Faces and `CUSTOM_THIS`

If a method runs with `this` = a sub-object at `obj+N` (a secondary vtable, the "face" of a base class),
`this` is typed as an offset pointer into the class: `Class * __((offset(N))) this`. The decompiler then
shows the class's own field names at their real offsets (for example `ServerList::CreateResultReceived`
S 0046a6a0 is `ServerList * __((offset(0x8))) this`). Such a function has custom variable storage and
carries the tags **`FACE_THIS`** and **`CUSTOM_THIS`**. `CUSTOM_THIS` alone marks a function whose `this`
is not a struct pointer. Everything else is typed by namespace only. `sadk_noav.exe` has no separate
"face" mirror struct of a class. tincat3 still holds one, `/ai/commlayer/RankingManager_ConnectionCallbackFace`
(0x14); the two functions of that face (T 10029cd0, T 10029cf0) are typed with the offset pointer
`RankingManager * __((offset(0x4)))`.

| | sadk_noav.exe | tincat3.dll |
|---|---|---|
| functions tagged `FACE_THIS` (offset-pointer `this`) | 666 | 5 |
| functions tagged `CUSTOM_THIS` without `FACE_THIS` | 27 | 0 |

Examples of faces: `ServerList` (`IGameServerObserver` at +0x08, S 007daf8c, 15 slots),
`UserCommConnection` (`IChatChannelObserver` at +0x38, S 007dce94, 12 slots), `PostOffice`
(`IMailObserver` at +0x08), `NComm::TinCatNetwork` (`ITinCatCallback` at +0x04), `CharacterManager`
(listeners at +0x64 / +0x6c), and the `std::basic_iostream` family.

---

## 6. Naming conventions

| Pattern | Meaning |
|---|---|
| `Class::Method` | named method; the name reflects the strongest evidence (`conf` in `state.db`) |
| `Global::Subsystem_Thing` (e.g. `Global::VillageSoldierUpgrade_CanStart`) | a function whose owning class is not determined; the prefix records the suspected owner |
| `Generic_*` | an ICF-folded body shared by unrelated callers (e.g. `Generic_ReturnFalse` S 0041ecc0); named by shape |
| `Stub_*`, `SlotNN_*` | empty or trivial vtable slots; `SlotNN` is the slot index |
| `cb_*` | tincat3 callback slot (`ITinCatCallback`) |
| `…Received` / `…ResultReceived` / `…AcknowledgeReceived` | handler for an inbound NETMSG |
| `field_XX`, `unkXX`, `flagXX`, `settingXXX` | offset-named field whose meaning is open |
| `*_vftable`, `*_fn` | vtable struct, funcdef type for a slot |
| field comment `[ai:<conf>]` | per-field confidence |
| plate `[ai] … conf=… evidence: …` | per-function confidence and evidence |

---

## 7. Known gaps

Counts come from the verify run over the map (`mapping/cache/<prog>/verify/`) and from the type dump.

| Check | sadk_noav.exe | tincat3.dll |
|---|---|---|
| functions whose prototype uses a not-yet-defined struct | 0 findings | 0 findings |
| vtable slot owner | 0 findings over 15296 checked slots | 0 findings over 1419 |
| struct size ≠ allocation | 0 findings over 799 checked allocations | 0 findings over 72 |
| structs of ≤ 1 byte | 34 | 6 |
| functions with a library `FUN_` name | 745, all unwind funclets and CRT internals | 0 |

Specific to the types in this document:

1. **`LobbyComm::System` +0x34** (`observers34`): the event of this observer list is not recoverable from
   the client; no code fires it.
2. **`VillageServerConnection`**: `observers_ec`, `observers_f8`, `observers_14c`, `queue_1fc` and
   `queue_210` have no producer and keep offset names; `leaveWorldObservers` (+0x110) has a subscriber and
   no notifier.
3. **`IActor` slot 4** has no call site in the decompile cache and keeps a shape name.
4. **`ServerList` +0x70 and +0x84**: the two server vectors are three typed pointers each plus an undefined
   first dword, not embedded vector structs.
5. **`UserCommConnection::OpenCommunication`** S 0047ff10 and `VillageServerConnection::OpenUserComm`
   S 00470d50 name their argument `chatServerHandle`, but `CLobbyClient::EnterVillage` S 00503f50 passes
   `CharacterManager.selectedCharacterId` on a first entry and `CLobbyClient +0x14` on a re-entry (0 is
   replaced by `System::GetChatServerHandle()`). [TODO] the tincat3 side of the transport's vtbl+0x10 has to
   be read before the name is settled.
6. **Two server-descriptor types** with one layout: `/GameServerDescriptor` (sadk) and tincat3
   `/ai/CommLayer/GameServerInfo` (both 0x5c, serverId at +0x00).
