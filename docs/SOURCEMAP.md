# SaDK Reverse-Engineering SOURCEMAP

Named functions, structs, fields, globals and enums of the lobby, village and match-network code, as
they stand in the Ghidra project.

All `SADK.exe` addresses in this document are addresses in `sadk_noav.exe`, the Ghidra program that is
byte-identical to the game's `SADK.exe` on disk (image base `0x400000`, the same as runtime).

| Program | Image base | Runtime | Notes |
|---------|-----------|---------|-------|
| `sadk_noav.exe` (= `SADK.exe`) | `0x00400000` | 1:1 (no rebase) | game client; lobby/village protocol |
| `tincat3.dll` | `0x10000000` | 1:1 | TinCat networking + property-bag codec (has C++ symbols) |

Status tags: `[PROVEN]` = binary address plus live evidence (the source of the live evidence is named);
`[known]` = directly visible in the binary (address, constant, string, vtable slot, instruction bytes);
`[inferred]` = strong static evidence from callers, strings and types; `[TODO]` = open.

Functions sit in class namespaces (`LobbyComm::VillageServerConnection::HandleEnterWorld`); the
namespace's struct types `this`. Full field tables of the structs below, and of the types this document
does not cover, are in [types.md](types.md).

---

## 1. Structs & enums

"Ghidra field" is the field name defined in the Ghidra struct. "–" means the offset is not a named field
of that struct yet; its meaning then comes from the code that reads or writes it.

### `LobbyComm::VillageServerConnection` (`/LobbyComm/VillageServerConnection`, 0x280 bytes) — `this` of all `Handle*` in §2b

Allocation size 0x280 `[known]`. Full table: [types.md](types.md) §1.4.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x000 | VillageServerConnection_vftable* | `pVftable` | vtable `0x7db8d4`, 17 slots; the RTTI locator pointer sits at `0x7db8d0` `[known]` |
| 0x004..0x034 | ObserverList ×4, void* | `loggedInObservers`, `loginFailedObservers`, `loggedOutObservers`, `disconnectedObservers`, `pTransport` | `LobbyComm::BaseConnection` part: observer lists at `+0x04`, `+0x10`, `+0x1c`, `+0x28`; `pTransport` `+0x34` (tincat3 connection: vtbl `+0x0c` GetState, 8 = logged in; `+0x18` Logout; `+0x1c` Send) `[known]` |
| 0x038..0x14c | ObserverList ×24 | `npcAddedObservers` … `observers_14c` | 24 world-event observer lists, step 0xc: `+0x104` `enterWorldObservers`, `+0x11c` `worldTickObservers`, `+0x128` `shopInventoryObservers`, `+0xb0` `avatarRemovedObservers`, … `[known]`. `+0x110` `leaveWorldObservers` has a subscriber (`CLobbyClient::OnWorldLeft` `0x5037a0`) and no notifier in the binary; `observers_ec`, `observers_f8` and `observers_14c` have neither `[known]`. Full list: types.md §1.4 |
| 0x158 | LobbyComm::System* | `pSystem` | owning `LobbyComm::System`; `TickInWorld` reads its state `[known]` |
| 0x15c | int | `villageServerId` | village server id, set by `InitializeForServer`; -1 = none `[known]` |
| 0x160 | uint | `serverPermId` | the u32 `ServerPerm` of EnterWorld (1000); cleared by `HandleLoggedOut` `[known]` |
| 0x164 | MsvcTree (0xc) | `zoneChatChannels` | `std::map<u8 zone, u32 channelId>` (head `+0x168`, size `+0x16c`): key 0xFF = main village channel, 0xFE = minigame table channel, below 0x0E = zone `[known]` |
| 0x170 | void* | `pAvatarMap` | `std::map<uint, AvatarProxy*>*`, points at `LobbyComm::System+0x558` `[known]` |
| 0x174 | void* | `pNpcMap` | `std::map<uint, NPCProxy*>*`, points at `LobbyComm::System+0x564` `[known]` |
| 0x178 | MsvcTree (0xc) | `miniGameTables` | minigame-table map (head `+0x17c`, size `+0x180`), value `MiniGameProxy*` `[inferred]` |
| 0x184..0x223 | MsvcDeque ×8 | `avatarLoggedInQueue`, `avatarRemovedQueue`, `avatarDataQueue`, `avatarActiveItemsQueue`, `avatarInventoryQueue`, `avatarItemsFullSyncQueue`, `queue_1fc`, `queue_210` | eight event deques of `AvatarProxy*`, 0x14 bytes each; filled by the 1001–1003 and 0xC1C–0xC1E handlers, drained each frame by `DrainEventQueues` `0x46fde0`. No code fills the last two `[known]` |
| 0x224 | bool | `worldLoginAckReceived` | set to 1 by msg 1006 when `code == 0xDEADBEEF`; no code reads it `[known]` |
| 0x225 | byte | `currentZone` | zone key of the joined zone chat channel, 0x0F = none `[known]` |
| 0x226 | bool | `zoneJoinPending` | set by `JoinZoneChatChannel` `0x46e860`, cleared by `OnChatChannelJoined` `0x46d610` `[known]` |
| 0x228 | std::string (0x1c) | `worldName` | world name (`<UNNAMED>` when EnterWorld sends an empty one) `[known]` |
| 0x244 | int | `connectionQuality` | link quality 0..3: set to 3 by `HandleEnterWorld`, graded from the ping round trip by `HandlePongCode`, 0 when a ping stays unanswered; returned by `GetConnectionQuality` `0x46c130` `[known]` |
| 0x248 | uint | `pendingPingCode` | pending ping code; `0x80008000` = none `[inferred]` |
| 0x24c / 0x250 / 0x254 | float | `pingSentTime` / `pongReceivedTime` / `nextPingCountdown` | ping send time / pong receive time / next-ping countdown `[inferred]` |
| 0x258..0x27f | – | `shopNpcId`, `shopId`, `shopSellMod`, `shopStock`, `tradeRequestPending`, `tradeActive`, `tradeId`, `tradeMsgPrt`, `tradeRnid` | shop state and trade state `[inferred]`, see types.md |

### `Lobby::CLobbyClient` (`/Lobby/CLobbyClient`, 0x38 bytes) — the village-enter client object

vtable `0x7e60d8` (one slot, the deleting destructor `0x503430`) `[known]`. `Lobby::CLobby +0xc0` points
at it.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x00 | void* | `vftable` | `[known]` |
| 0x04 | void* | `pLobby` | owning `Lobby::CLobby` `[inferred]` |
| 0x08 | void* | `pLobbyManager` | the `LobbyComm::System` (`LobbyManager_GetInstance()`), cached in the ctor `[known]` |
| 0x0c | VillageServerConnection* | `pVillageConn` | set by `EnterVillage`; 0 = none `[known]` |
| 0x10 | byte | `bReleaseConnection` | one-shot: `Update` unsubscribes and clears `+0x0c` `[inferred]` |
| 0x11 | byte | `bReenterPending` | set by `RequestReenterVillage` `0x503560`; `Update` re-fires `EnterVillage` after the timeout `[inferred]` |
| 0x14 | void* | `pCommSystem` | value passed to `OpenUserComm` on a re-enter `[inferred]` |
| 0x18 | float | `fReenterTimeout` | 2.5 s, counted down by frame time in `Update` `[known]` |
| 0x1c | int | `nReenterRetries` | fewer than 3 retries after a login failure `[known]` |
| 0x20 | byte | `bUseDefaultSpawn` | argument of `EnterVillage` `[inferred]` |
| 0x21 | byte | `bHasSavedPosition` | set by `LeaveVillage` when a local avatar exists `[known]` |
| 0x24 / 0x30 / 0x34 / 0x35 | float[3] / float / byte / byte | `savedPos` / `savedHeading` / `savedZone` / `savedGhostZone` | the local avatar's place, stored by `LeaveVillage` and reused at the next EnterWorld `[known]` |

### `LobbyComm::System` (`/LobbyComm/System`, 0x5a8 bytes; singleton pointer `g_pLobbyManager` @ `0x885890`; called LobbyManager in older notes)

The RTTI class of the lobby client's root object is `LobbyComm::System` (vtable `0x7dacb0`, source file
`LobbyManager.cpp`). Its methods are in the namespace `LobbyComm::System`. The global `g_pLobbyManager`,
the enum `LobbyManagerState` and the four static functions `LobbyManager_GetInstance` `0x462420`,
`LobbyManager_HasInstance` `0x462430`, `LobbyManager_CreateInstance` `0x464280` and
`LobbyManager_DestroyInstance` `0x462400` keep the older name. `LM+0x..` in this document is an offset
inside this object. Allocation size 0x5a8 = struct size `[known]`. Full table: [types.md](types.md) §1.2.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x000 | System_vftable* | `vftable` | vtable `0x7dacb0` (7 slots, `CommLayer::IConnectionCallback`); slot 0 is the deleting destructor that `LobbyManager_DestroyInstance` `0x462400` calls with 1 `[known]` |
| 0x004..0x04b | MsvcList ×6 | `connectionLostObservers`, `globalDataLoadedObservers`, `loginFailedObservers`, `loggedOutObservers`, `observers34`, `versionCheckFailedObservers` | observer lists `[known]`; no code fires `observers34` |
| 0x04c | void* | `pCommLayer` | the one TinCat comm layer (payload magic 0x26B6) `[known]` |
| 0x050 | CommLayer::ConnectionManager* | `pConnectionManager` | tincat3 ConnectionManager; owns the property factory at its `+0x20`; its `+0x08` holds this object as the application's `IConnectionCallback` `[known]` |
| 0x054 | LobbyComm::ServerList (0xac) | `serverList` | embedded server list (village servers and game servers). Village server vector begin/end at `LM +0xc8 / +0xcc`, selected village server id at `+0xd4` (= ServerList `+0x80`) `[known]` |
| 0x100 | LobbyComm::ServerMessages (0x3c) | `serverMessages` | MotD holder `[known]` |
| 0x140 | LobbyComm::CharacterManager (0x1b8) | `characterManager` | characters, buddies, ignore list `[known]` |
| 0x2f8 | LobbyComm::PostOffice (0xc4) | `postOffice` | mail `[known]` |
| 0x3bc | LobbyComm::Properties (0x1c) | `properties` | property requests (version check) `[known]` |
| 0x3d8 | LobbyComm::UserCommConnection (0xb8) | `userCommConnection` | embedded chat / UC connection `[known]` |
| 0x490 | LobbyComm::RefereeServerConnection (0xb0) | `refereeServerConnection` | embedded referee connection `[known]` |
| 0x540 | VillageServerConnection* | `pVillageConnection` | the village connection (heap, 0x280) `[known]` |
| 0x544 | GameServerConnection* | `pGameServerConnection` | the game-room connection (heap, 0x38) `[known]` |
| 0x548 | int | `nChatServerHandle` | server handle stored when the main connection logs in; reused for the UC dial `[known]` |
| 0x54c | uint | `localPermId` | the local user's id; getter `GetLocalPermId` `0x462510` `[known]` |
| 0x550 | int | `nSelectedVillageServerCached` | selected village server id, recorded when the village connection logs in `[known]` |
| 0x554 | AvatarProxy* | `localAvatar` | the local player's avatar `[inferred]` |
| 0x558 / 0x564 | MsvcTree (0xc) | `avatarMap` / `npcMap` | the maps the village connection's `+0x170` / `+0x174` point at `[known]` / `[inferred]` |
| 0x570 | ItemDatabase (0xc) | `itemDatabase` | `std::map` of item id to `ItemInfo`; `GetItemDatabase` `0x462560` `[known]` |
| 0x57c | LobbyManagerState | `state` | see the enum below `[known]` |
| 0x580 | int | `nRefereeServerId` | `[PROVEN]` (types.md §1.2: the 60 s `189 AssignServer` retry) |

The selected village server id is read with the folded getter `Generic_GetDword_80` `0x4683d0`
(`MOV EAX,[ECX+0x80]; RET`, shared with unrelated classes), called with the ServerList; it returns
ServerList `+0x80` `[known]`. `LobbyComm::ServerList::HasSelectedVillageServer` is `0x4683b0`.

### `LobbyMenu::AvatarScreen` (`/LobbyMenu/AvatarScreen`, 0x220 bytes) — character select / enter-village screen

vtable `0x7d72fc` `[known]`: slot 8 (`0x7d731c`) = `Update` `0x439f30`, slot 9 = `HandleButtonClicks`
`0x43bd50`. The object is allocated once (`operator new(0x220)` in `LobbyMenu::System::Initialize`
`0x42ad80`); bases `LobbyMenu::ScreenBase` (0x1e8, embedded as `base`) and `nUi::XMLHandler`. Older notes
call this class LobbyVillageScreen; there is one class and one struct.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x1e8 | int | `viewMode` | 0 create character, 1 select character, 2 entering village; the enter button needs 1 `[known]` |
| 0x1ec | CharacterManager* | `pCharacterManager` | `LobbyComm::CharacterManager*` (`LobbyComm::System+0x140`); its `+0x98` is the selected character id, which must be set `[known]` |
| 0x1f0 | ServerList* | `pServerList` | the `LobbyComm::ServerList` at `LobbyComm::System+0x54`, which the button checks `[known]` |
| 0x1f4 / 0x1f8 / 0x1fc | SelectAvatarDialog* / SelectVillageServerDialog* / CustomizeAvatarDialog* | `pSelectAvatarDialog` / `pSelectVillageServerDialog` / `pCustomizeAvatarDialog` | sub-dialogs `[known]` |
| 0x204 | void* | `pStartGameButton` | widget `StartGameButton`; its caption text object is at `+0x254` of the widget `[known]` |
| 0x218 | bool | `bButtonsEnabled` | enable gate of the enter button `[inferred]` |
| 0x21c | bool | `bCodersRule` | XML attribute `CodersRule`: developer mode with a manual village-server pick `[known]` |

The leave-village prompt (`!LEAVE_VILLAGE`, `!LEAVE_VILLAGE_QUESTION`) belongs to a different class:
`LobbyMenu::WorldScreen::HandleButtonClicks` `0x437760`, WorldScreen vtable `0x7d6eac` slot 9
(`0x7d6ed0`) `[known]`.

### `LobbyComm::UserCommConnection` (`/LobbyComm/UserCommConnection`, 0xb8 bytes)

vtables `0x7dcecc` (primary) and `0x7dce94` (`CommLayer::IChatChannelObserver` face at `+0x38`) `[known]`.
Embedded at `LobbyComm::System+0x3d8`. Full table: [types.md](types.md) §1.5.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x00 | UserCommConnection_vftable* | `vftable` | `[known]` |
| 0x04 / 0x10 / 0x1c / 0x28 | ObserverList | `loggedInObservers` / `loginFailedObservers` / `loggedOutObservers` / `disconnectedObservers` | BaseConnection part `[known]` |
| 0x34 | void* | `pTransport` | tincat3 connection; the dial is its vtbl `+0x10` `(handle, 0)` `[known]` |
| 0x38 | CommLayer::IChatChannelObserver | `chatChannelObserver` | embedded `IChatChannelObserver` sub-object; its callbacks run with `this = UserCommConnection+0x38` `[known]` |
| 0x3c..0x8f | MsvcList ×7 | `chatReceivedObservers`, `privateChatReceivedObservers`, `privateChatSentObservers`, `channelJoinedObservers`, `channelJoinFailedObservers`, `channelLeftObservers`, `channelLeaveFailedObservers` | chat observer lists `[known]` |
| 0x90 | void* | `pM_ChatChannelManager` | tincat3 ChatChannelManager `[known]` |
| 0x98 / 0x9c / 0xa0 | void* | `channelsBegin` / `channelsEnd` / `channelsCapEnd` | `std::vector<ChatChannelInfo>` (object at `+0x94`) `[inferred]` |
| 0xa4..0xb7 | MsvcDeque (0x14) | `whisperQueue` | `std::deque<PrivateChatRequest>` at `+0xa4` (map, mapSize, offset, size): `QueuePrivateMessage` `0x4808a0` pushes, `Process` `0x480630` works on the head `[known]` |

### `LobbyComm::LobbyMessage` (`/LobbyComm/LobbyMessage`, 0x3c bytes) — inbound / outbound bit-stream message

vtable `0x7db594`, 17 slots `[known]`. The village handlers receive the stack `LobbyMessage` that
`HandleMessage` builds with `InitFromWire`; their parameter is typed `LobbyMessage *`. Reader slots the
handlers call: `+0x18` read N bits into a
u32, `+0x20` read a 64-bit block, `+0x30` read a string `[known]`. Field tables and the key methods:
[types.md](types.md) §1.8.

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x00 | void* | `vftable` | `[known]` |
| 0x04 | NCore::ByteBuffer (0x10) | `buffer` | `[known]` |
| 0x14 / 0x18 / 0x1c | byte / uint / int | `curByte` / `bitCursor` / `byteIndex` | bit accumulator (MSB first) and cursors `[known]` |
| 0x20 | bool | `namesMode` | type-word bit 15 `[known]` |
| 0x24 | uint | `category` | `(typeword >> 12) & 7` `[known]` |
| 0x28 | uint | `msgId` | `typeword & 0xfff`; read by the folded getter `Generic_GetDword_28` `0x48eef0` in the dispatchers `[known]` |
| 0x2c | bool | `finished` | `[inferred]` |
| 0x30 / 0x34 | uint | `crcValue` / `crcLength` | CRC32 accumulator `[known]` / `[inferred]` |
| 0x38 | int | `field_38` | written only: 1 in the send ctor, 0 in `InitFromWire` `[known]` |

### `TinCatProperties::Property` (tincat3.dll, `/TinCatProperties/Property`, 0x38 bytes) — one property in a PropertySet

| Off | Type | Ghidra field | Meaning |
|----:|------|--------------|---------|
| 0x00 | void* | `vftable` | `0x1004e5ac` `[known]` |
| 0x04 | mstring (0xc) | `name` | property name `[known]` |
| 0x10 | ETinCatPropertyType | **`type`** | type enum, see below `[known]` |
| 0x14 | mstring (0xc) | `stringValue` | value for type STRING `[known]` |
| 0x20 | uint | `size` | value byte size / declared maximum `[known]` |
| 0x28 | ulonglong | `value` | scalar storage (1..8 bytes); for MEMBLOCK / WSTRING the heap block pointer in the low dword `[known]` |
| 0x30 | void* | `ownerSet` | back pointer to the PropertySet `[inferred]` |
| 0x34 | uint | `ownedBySet` | 1 for a property the set allocated itself `[known]` |

**`ETinCatPropertyType`** (`/ai/network/ETinCatPropertyType`; switch in `Property::SetMemBlock`
`0x10011500`): `1` MEMBLOCK, `2` STRING, `3` WSTRING → all **u32 LE length prefix + bytes**; `4/5`
UNBYTE/SIBYTE (1 B), `6/7` UNSHORT/SISHORT (2 B), `8/9` UNLONG/SILONG (4 B), `0xa/0xb` UNINT64/SIINT64
(8 B), `0xc` SIFLOAT, `0xd` SIDOUBLE, `0xe` LBOOL (1 B) → **raw fixed width, no prefix** `[known]`.

### `TinCatProperties::PropertySet` (tincat3.dll, `/TinCatProperties/PropertySet`, 0x20 bytes)
`0x00 vftable (0x1004dcac) · 0x04 list_vftable (embedded UList, 0x18 bytes) · 0x0c list_iterator ·
0x1c enumIterator (GetFirst/GetNext cursor)` `[known]`.

### `TinCatProperties::PropertyDataConverter` (tincat3.dll, `/TinCatProperties/PropertyDataConverter`, 0xc bytes)
`0x00 buffer · 0x04 length`. Serialize / Deserialize write / read `buffer[0..length)` `[known]`.

### enum `LobbyManagerState` (`/LobbyManagerState`, 4 bytes; value at `LobbyComm::System+0x57c`) `[known]`
`0 Init · 1 Disconnected · 2 Authorizing · 3 Authorized · 4 CheckingVersion · 5 VersionChecked ·
6 LoadingGlobalData · 7 GlobalDataLoaded · 8 EnteringVillage · 9 VillageEntered · 10 LeavingVillage ·
11 VillageLeft · 12 ConnectionLost`.

---

## 2. SADK.exe functions

### 2a. World-entry trigger / connection path

Addresses and bodies `[known]`. The path as a whole is `[PROVEN]`: the unmodified client enters the 3D
lobby world against the stub (`lobby/sadk_lobby/village.py`).

| Addr | Name | Signature / role |
|------|------|------------------|
| 0x43abc0 | `LobbyMenu::AvatarScreen::OnStartGameClicked_EnterVillage` | click handler of the enter button; calls `CLobby` vtbl `+0x80` |
| 0x4f5070 | `Lobby::CLobby::RequestEnterVillage` | `void __thiscall(CLobby*, bool bUseDefaultSpawn)` — CLobby vtable `0x7e599c` slot 32 (`+0x80`); forwards to `CLobbyClient::EnterVillage` on the client object at `CLobby+0xc0` |
| 0x503f50 | `Lobby::CLobbyClient::EnterVillage` | `void __thiscall(CLobbyClient*, bool bUseDefaultSpawn)` — `CreateVillageServerConnection(-1)`, stores the connection at `+0x0c`, subscribes to it, then tail-jumps to the connection's vtbl `+0x3c` (`OpenUserComm`) |
| 0x503fc0 | `Lobby::CLobbyClient::Update` | per frame: runs `LobbyComm::System::StatePump_Tick` `0x464ee0`, releases a finished connection, counts the re-enter timeout down and re-fires `EnterVillage(false)` |
| 0x463850 | `LobbyComm::System::CreateVillageServerConnection` | `VillageServerConnection* (System*, int villageServerId)` — resolves `-1` to the selected village server, registers it with the ConnectionManager (vtbl `+0x38`), initialises the village connection with the transport (`InitializeForServer` `0x46dac0`); **no socket I/O**. Returns the connection pointer at `+0x540` (`MOV ESI,[ESI+0x540]` at `0x4639d3`, `MOV EAX,ESI` at `0x4639ea`) |
| 0x470d50 | `LobbyComm::VillageServerConnection::OpenUserComm` | `bool __thiscall(this, int chatServerHandle)` — **the dial** (vtbl `+0x3c`): subscribes `OnUserCommLoggedIn` `0x4704e0` / `OnUserCommLoginFailed` `0x470660` and calls `UserCommConnection::OpenCommunication`; a handle equal to `DAT_007db510` (static value 0) selects `LobbyComm::System::GetChatServerHandle()` |
| 0x4704e0 | `LobbyComm::VillageServerConnection::OnUserCommLoggedIn` | UC login continuation: logs into the village transport with the chosen avatar id and sets the `LobbyComm::System` state `EnteringVillage` (8) |
| 0x408480 | `Generic_GetDword_34` | folded getter `return *(this+0x34)`; `CreateVillageServerConnection` calls it on the village connection to read `pTransport` (the connect gate: it proceeds only while the connection has no transport). Shared with unrelated classes |
| 0x4683d0 | `Generic_GetDword_80` | folded getter `return *(this+0x80)`; on the ServerList it returns `selectedVillageServerId`. Shared with unrelated classes |
| 0x439f30 | `LobbyMenu::AvatarScreen::Update` | enter-button enable and caption (`!ENTER_VILLAGE_BUTTON` / `!LOBBY_LOADING_SERVERS`); needs `CharacterManager::HasSelectedCharacter` `0x472270` and `ServerList::HasJoinableServerForProtocol` `0x468560` |
| 0x468560 | `LobbyComm::ServerList::HasJoinableServerForProtocol` | `bool (ServerList*, uint protocol)` — true if a village server entry has `+0x30 == protocol`, load below 90 % and the joinable byte `+0x35` set |
| 0x4624e0 | `LobbyComm::System::GetUserCommConnection` | returns `this+0x3d8` |
| 0x440a50 | `LobbyMenu::SelectVillageServerDialog::OnServerAddedOrChanged` | server-list observer of the manual server-pick dialog: for an entry with `+0x34 == 0` and `+0x30 == g_ClientProtocolVersion` it adds, refreshes or (when `+0x35 == 0`) removes the list row. `"LoadLevel"` is the name of the row's label that shows the server load in percent. UI only: no state change, no message |

Read-only context: `0x462540 LobbyComm::System::SetState` (no-op once the state is 12), `0x462530
LobbyComm::System::GetState`, `0x462420 LobbyManager_GetInstance`, `0x4643d0 LobbyComm::System::Initialize`
(the sole `TinCat_CreateCommLayer(0, 0x26B6, 5, name)` call is at `0x46462b`) `[known]`.

The list-ready predicate that `AvatarScreen::Update` calls is `HasJoinableServerForProtocol` `0x468560`.
Older notes name it `IsListReady_impl` at `0x4AD750`; that was the run-time address of this body in the
copy-protected executable. In `sadk_noav.exe` `0x4ad750` lies inside another function `[known]`.

### 2b. Village / world message receiver (vtable @ `0x7db8d4`, 17 slots)

Vtable contents `[known]` (read from the binary). Slots 0–13 follow the `BaseConnection` layout (14
slots, base vtable `0x7de8cc`). The Ghidra struct `/LobbyComm/VillageServerConnection_vftable` carries
the names below.

| Slot | Off | Addr | Name |
|-----:|----:|------|------|
| 0 | +0x00 | 0x46f360 | `scalar_deleting_dtor` |
| 1 | +0x04 | 0x48de70 | `BaseConnection::Initialize` (inherited) |
| 2 | +0x08 | 0x46da60 | `Destroy` |
| 3 | +0x0c | 0x48dfa0 | `BaseConnection::SendMessage` (inherited) |
| 4 | +0x10 | 0x48df10 | `BaseConnection::SendBuffer` (inherited) |
| 5 | +0x14 | 0x46dc00 | `HandleLoggedIn` |
| 6 | +0x18 | 0x46dcf0 | `HandleLoginFailed` |
| 7 | +0x1c | 0x470e20 | `HandleLoggedOut` |
| 8 | +0x20 | 0x470f90 | `HandleDisconnected` |
| 9 | +0x24 | 0x470a90 | `HandleMessage` |
| 10 | +0x28 | 0x471110 | `TickInWorld` |
| 11 / 12 | +0x2c / +0x30 | 0x48dce0 / 0x48dd00 | `BaseConnection::IsLoggedIn` / `IsConnectionPending` (inherited) |
| 13 | +0x34 | 0x46c130 | `GetConnectionQuality` |
| 14 | +0x38 | 0x46dac0 | `InitializeForServer` |
| 15 | +0x3c | 0x470d50 | `OpenUserComm` |
| 16 | +0x40 | 0x46bde0 | `SendLeaveVillageRequest` |

Leaving the village `[PROVEN]` (live trace of 2026-07-26, `decomp/RENAME_LIST.md`; stub
`village.py send_world_login_ack`):

- `Lobby::CLobbyClient::LeaveVillage` `0x503470` saves the local avatar's place and tail-jumps to slot
  `+0x40`. `SendLeaveVillageRequest` `0x46bde0` requires transport state 8, builds
  `LobbyMessage(category 2, msgId 0x7d2 = 2002){code = 0xAFFEDEAD}`, calls
  `SetState(LeavingVillage = 10)` and sends. It does not log the transport out.
- The server answers with msg 1006 `{code = 0xDEADBEEF}`. `HandleWorldLoginAck` `0x46ec50` then logs the
  UserComm connection out first when it is logged in (`UserCommConnection::Logout` `0x47ed70`; its
  logged-out observer `OnUserCommLoggedOut` `0x46db30` then calls the village transport's vtbl `+0x18`,
  Logout), otherwise it calls the village transport's Logout directly. Msg 1006 is therefore the logout trigger and must only be sent as the answer to 2002.
- The transport's logout arrives as `HandleLoggedOut` `0x470e20` (slot `+0x1c`): world teardown,
  `SetState(VillageLeft = 11)`, then the loggedOut observer list (`+0x1c`). One observer is
  `LobbyMenu::WorldScreen::OnVillageConnectionLoggedOut` `0x4316c0`, which arms the referee login when a
  match is starting. Answering 2002 with EnterWorld (1000) re-enters the lobby world instead.
- `HandleMessage` does not dispatch 2002 or any logout id: LoggedOut is a connection-state callback, not
  a village message.

| Addr | Name | Msg / role |
|------|------|------------|
| 0x470a90 | `LobbyComm::VillageServerConnection::HandleMessage` | `(this, uint typeWord, ByteBuffer* payload)` — dispatcher: `LobbyMessage::InitFromWire` `0x48fa50`, then a switch on the message id (`LobbyMessage+0x28`); unknown ids are dropped silently `[known]` |
| 0x46f670 | `…::HandleEnterWorld` | **msg 1000** `(this, LobbyMessage* msg)` — `SetState(VillageEntered = 9)`; reads `Worldname`, `ServerPerm`, `ChatChannelsCount`, N × {`ChatChannelZone`, `ChatChannelID`}; joins the main channel (zone key 0xFF) on the UC connection; requests the mail headers; `connectionQuality = 3`; sends the first ping; stores `ServerPerm`; fires the EnterWorld observers (`+0x104`) `[PROVEN]` (stub `village.py enter_world_body`, world entry screenshot-confirmed) |
| 0x46dc00 | `…::HandleLoggedIn` | vtbl `+0x14`; own login succeeded `[known]` |
| 0x46dcf0 | `…::HandleLoginFailed` | vtbl `+0x18` `(this, int errorCode)`; also logs the UC connection out `[known]` |
| 0x470e20 | `…::HandleLoggedOut` | vtbl `+0x1c` → state `VillageLeft` (11) `[PROVEN]` (live trace 2026-07-26) |
| 0x470f90 | `…::HandleDisconnected` | vtbl `+0x20`; same teardown, also logs the UC connection out, state 11 `[known]` |
| 0x46e1d0 | `…::HandleAvatarData` | msg 1001: avatar record (creates the `AvatarProxy` when the id is new) `[PROVEN]` (TTD traces 2026-08-01, `village.py`) |
| 0x46e390 | `…::HandleAvatarLoggedIn` | msg 1002: creates an empty `AvatarProxy` for the id `[known]` |
| 0x46e570 | `…::HandleAvatarRemove` | msg 1003: queues the avatar for removal `[PROVEN]` (TTD traces 2026-08-01, `village.py`) |
| 0x46f8c0 | `…::HandleNPCData` | msg 1004: NPC record (`NPCProxy`, 0x120 bytes) `[PROVEN]` (NPCs live, `village.py`) |
| 0x46f620 | `…::HandleWorldTick` | msg 1005: 64-bit `tick`, observers `+0x11c` `[known]` |
| 0x46ec50 | `…::HandleWorldLoginAck` | msg 1006: acts only when `code == 0xDEADBEEF`; sets `+0x224` and starts the logout sequence `[PROVEN]` (live trace 2026-07-26) |
| 0x46c150 | `…::SendPing` | `(this, uint pingCode)` — sends **msg 0xED6 (3798)** with the u32 field `PingCode`; next ping after 30 s, after 15 s when the send failed `[PROVEN]` (stub answers it, `docs/message-catalog.md`) |
| 0x46c250 | `…::HandlePongCode` | msg 0xED7 (3799): matches `PongCode` against the pending ping, grades the round trip into `+0x244` `[PROVEN]` (stub echo, `docs/message-catalog.md`) |
| 0x46c360 | `…::PingPongTimerTick` | per-frame ping scheduler, called from `TickInWorld` in state 9 `[known]` |

### 2c. Token / UserComm login (`LobbyUserCommConnection.cpp`, `LobbyManager.cpp`)

All `[known]`.

| Addr | Name | Role |
|------|------|------|
| 0x47f160 | `LobbyComm::UserCommConnection::Initialize` | `bool (this, void* transport, void* chatChannelManager)`; initialises the BaseConnection part, stores the chat manager at `+0x90` and registers the `+0x38` observer face with it |
| 0x47ff10 | `LobbyComm::UserCommConnection::OpenCommunication` | `(this, int chatServerHandle)` — dial via the transport (`+0x34`) vtbl `+0x10` |
| 0x47f320 | `LobbyComm::UserCommConnection::OnLoggedIn` | `(this, uint userId)` |
| 0x47f410 | `LobbyComm::UserCommConnection::OnLoginFailed` | `(this, int errorCode)` |
| 0x47f6e0 | `LobbyComm::UserCommConnection::OnReceivedData` | vtbl `+0x24`; forwards to the empty stub `Stub_NoOpReturnVoid` `0x472360` (the token messages 211–214 are handled inside tincat3; chat arrives through the `IChatChannelObserver` callbacks) |
| 0x47f7d0 | `LobbyComm::UserCommConnection::ChatChannelListReceived` | `(UserCommConnection* __((offset(0x38))) this, int count, void* descs, int error)` — runs on the `IChatChannelObserver` sub-object, `this = UserCommConnection+0x38`; server push after the login |
| 0x480070 | `LobbyComm::UserCommConnection::JoinChannel` | `(this, uint channelId)` |
| 0x47ed70 | `LobbyComm::UserCommConnection::Logout` | logs the transport out when its state is 8 |
| 0x463a10 | `LobbyComm::System::OnLoggedIn` | `(this, int connId, int serverHandle, int unused)` — login-success router (vtable slot 1). Main connection: stores `nChatServerHandle` (`+0x548`, store at `0x463ad1`) and writes `state = 3` inline (store at `0x463ad7`); otherwise forwards to the matching sub-connection's vtbl `+0x14` |
| 0x462420 | `LobbyManager_GetInstance` | returns `g_pLobbyManager` (`0x885890`) |
| 0x462500 | `LobbyComm::System::GetChatServerHandle` | returns `this+0x548` |
| 0x462510 | `LobbyComm::System::GetLocalPermId` | returns `this+0x54c` (`localPermId`): the local user's id, compared with the referee login reply's PermID and sent as mail `delivery_target` / `creator` |

### 2d. ServerList result callbacks (secondary vtable @ `0x7daf8c`, 15 slots)

> **ECX = `ServerList + 8` in every function below.** The ctor `0x46a160` installs the primary vtable
> `0x7dafcc` at `[ServerList+0]` and this `CommLayer::IGameServerObserver` table at `[ServerList+8]`
> (the embedded sub-object `gameServerObserver`). In Ghidra `this` of these functions is the offset
> pointer `ServerList * __((offset(0x8))) this`, so the decompile shows the ServerList field names at
> their real offsets: `gameServerId` (`ServerList+0x9c`, the hosting latch; `[ECX+0x94]` in the
> listing) and the referee callback pair `refereeCbContext` / `refereeCbFn` (`ServerList+0xa4` / `+0xa8`;
> `[ECX+0x9c]` / `[ECX+0xa0]` in the listing). `[PROVEN]` (live run of 2026-07-26,
> `decomp/RENAME_LIST.md`). Field map: `docs/LOBBY_SCREEN_VTABLES.md`.

Vtable contents `[known]` (read from the binary). All names are in `LobbyComm::ServerList`.

| Slot | Off | Addr | Name | Role |
|-----:|----:|------|------|------|
| 0 | +0x00 | 0x468ac0 | `scalar_deleting_dtor_thunk_m8` | destructor thunk (`this - 8`) |
| 1 | +0x04 | 0x4693d0 | `StartObservationResultReceived` | result of RegObserverServerList (171); log only |
| 2 | +0x08 | 0x4694f0 | `StopObservationResultReceived` | result of DeregObserverServerList (172); log only |
| 3 | +0x0c | 0x469610 | `GameServerAdded` | observer push of one descriptor; forwards to slot 4 |
| 4 | +0x10 | 0x46a440 | `AddOrUpdateDescriptor` | sink for one GameServerData (170) descriptor: adds, updates or removes the cached village / game server entry and fires the matching observer list |
| 5 | +0x14 | 0x46a5e0 | `RemoveServer` | remove by id; resets the selected id when it matched |
| 6 | +0x18 | 0x469700 | `GameServerDataReceived` | bulk server-list reply |
| 7 | +0x1c | 0x46a6a0 | **`CreateResultReceived`** | answer to AddGameServer (168): latches the new id into `ServerList+0x9c` |
| 8 | +0x20 | 0x469870 | `UpdateResultReceived` | log only |
| 9 | +0x24 | 0x469990 | `DeleteResultReceived` | resets `ServerList+0x9c` to -1 on success |
| 10 | +0x28 | 0x469ad0 | `GameServerAssigned` | AssignServer (189) reply: calls the pending referee callback with the server id |
| 11 | +0x2c | 0x469be0 | `AssignGameServerResultReceived` | on error calls the pending callback with 0 |
| 12 | +0x30 | 0x469d20 | `TANConnectionGranted` | bare notification (log only); not the world trigger |
| 13 | +0x34 | 0x469e00 | `RequestTANConnectionResultReceived` | log only; no state change |
| 14 | +0x38 | 0x469f20 | `KickResultReceived` | log only |

Referee connection functions (`LobbyComm::RefereeServerConnection`): [types.md](types.md) §1.6.

---

## 3. tincat3.dll functions (C++ symbols + annotations)

All `[known]`.

### 3a. Property-bag codec + factory (the wire format)
| Addr | Name | Role |
|------|------|------|
| 0x100110e0 | `TinCatProperties::PropertyDataConverter::DeserializeProperty` | `uint __thiscall(this, IPropertySet* templateSet)` — **decoder**; a NULL templateSet faults at `+0x6` |
| 0x100112b0 | `TinCatProperties::PropertyDataConverter::SerializeProperty` | **encoder** (two passes; variable types get the u32 length prefix) |
| 0x10013710 | `TinCatProperties::cPropertyFactory::RegisterPropertySet` | `(this, ulong msgType, IPropertySet* templateSet)` — **msgType → template registry** (vtbl `+0x04`) |
| 0x10013830 | `TinCatProperties::cPropertyFactory::CreatePropertySet` | `IPropertySet* __thiscall(this, ulong msgType)` — vtbl `+0x0c`; **returns NULL for an unregistered type** |
| 0x100138f0 | `TinCat_CreatePropertyFactory` | factory constructor function |
| 0x100139e0 | `TinCatProperties::PropertySet::CreateProperty` | `(this, char* name, ulong type, ulong maxLength)` — PropertySet vtbl `+0x04`; the two-argument form is `0x10013980` |
| 0x10013a50 | `TinCatProperties::PropertySet::AddProperty` | `(this, IProperty*)` |
| 0x10013d00 / 0x10013d80 / 0x10013d90 | `PropertySet::GetProperty / GetFirstProperty / GetNextProperty` | lookup by name / iteration |
| 0x10011500 | `TinCatProperties::Property::SetMemBlock` | switch on the type at `+0x10` (the type enum of §1) |
| 0x100117c0 / 0x10011980 | `Property::SetString / SetWString` | type 2 / type 3 |
| 0x10010ee0 | `TinCatProperties::Property::GetU32` | forwards to the property's vtbl `+0x7c` |
| 0x1000c760 | `TinCatProperties::PropertySet::SetU32` | `(this, char* name, ulong value)` — forwards to the set's vtbl `+0x94` |

Factory vtable @ **`0x1004DE84`**: `+0x04 RegisterPropertySet · +0x08 UnregisterAll ·
+0x0c CreatePropertySet(type) · +0x10 CloneTo · +0x14 DestroyPropertySet`.

### 3b. Comm layer / connection manager
| Addr | Name | Role |
|------|------|------|
| 0x10018c20 | `TinCat_CreateCommLayer` | `ICommLayer* __cdecl(eCommLayer connMgrType, ulong payloadMagic, eLogLevel logLevel, char* logFileName)` |
| 0x10018660 | `CommLayer::CommLayer::ctor` | **payload magic at `this+0x64`, `connMgrType` at `this+0x04`**, ConnectionManager at `this+0x0c`; CommLayer vtable @ `0x1004EC6C` |
| 0x1001f630 | `CommLayer::ConnectionManager::ctor` | creates the property factory at ConnectionManager `+0x20`; it starts empty |
| 0x10030d50 / 0x10031130 / 0x10031260 | `CommLayer::ConnectionManagerINet::ctor` / `ConnectionManagerLAN::ctor` / `ConnectionManagerLAN_GS::ctor` | one per `connMgrType` (0/1 INet, 2 LAN, 3 LAN_GS) |
| 0x1000cd40 | `TinCatModules::CellManager::ctor` | embeds a cell template PropertySet (`+0xd0`), a factory (`+0xf0`) and a converter (`+0xf8`) |
| 0x10017ba0 | `CommLayer::ChatChannelManager::HandleCellMessage` | dispatcher for a NETMSG relayed through the CellManager: builds the template with `CreatePropertySet(msgType)`, deserialises, then routes the built-in system types (chat, presence, kick, mail, Result 42) |
| 0x1002f5a0 / 0x1002fda0 | `CommLayer::ConnectionBC::OnTinCatEvent` / `CommLayer::ConnectionLANLobby::OnTinCatEvent` | LAN server discovery sinks; decode a GameServerData (170) payload with `CreatePropertySet(0xAA)` on the same factory |
| 0x10023cc0 | `CommLayer::HandlerLobby::HandleMessage` | receive handler of the client's main lobby connection. Its `0xAA` case is the internet-lobby decoder of GameServerData (170): it fills a 0x5c-byte descriptor and routes it by the ticket's request type to `GameServerManager::AddKnownServerAndNotify` `0x10020790` / `NotifyServerUpdated` `0x100207d0` (observer push), `QueueServerListEntry` `0x10020990` (RequestServers 166), `MachineManager::OnGameServerData` `0x10028470` (167) or `GameServerManager::OnGameServerAssigned` `0x10021520` (AssignServer 189) |
| 0x10019430 | `CommLayer::ConnectionManager::SetCallback` | vtable slot 1: stores the application's `IConnectionCallback` at ConnectionManager `+0x08`; the game registers its `LobbyComm::System` |
| 0x1001f6e0 / 0x10019ad0 | `CommLayer::ConnectionManager::LoadMsgDefs` / `CommLayer_RegisterBuiltinMsgDefs` | load the message schema from `msgdefs.ini` into the property factory; without an ini path the schema compiled into the DLL is registered: 221 message types (ids 1..262), 1106 fields, identical to the shipped `msgdefs.ini` |
| 0x100268e0 | `CommLayer::HandlerStatSurf::HandleMessage` | receive handler of the ranking connection. Message 255 reaches the RankingManager's slot 10 as (ranktable, perm_id, nick, rank, points, played, won, lost, tie, disconnected), with `played` computed as won + lost + tie + disconnected. Client defect: after a refused token it calls `OnError`, disconnects and still calls `OnLoggedIn` (`0x10026d25`) |

### 3c. Token validator (211–214)
| Addr | Name | Role |
|------|------|------|
| 0x10023460 | `CommLayer::HandlerGS::HandleMessage` | client receive state machine of the UC login: 0xd4 (212 received) → sends 0xd5 (213); 0x99 → authorized → LoggedIn. There is no case for 0xd6 (214) |
| 0x1002cc70 | `CommLayer::TokenValidator::SendValidateToken` | builds **214** (perm_id, cipher MEMBLOCK, nonce 128 B, ticket) |
| 0x1002cbd0 | `CommLayer::TokenValidator::GenerateNonce` | 128 random bytes, kept at validator slot `+8` |
| 0x1002a1c0 | `ai::CommLayer::TicketTable::AllocTicketId` | next ticket id; records the request type for the reply |
| 0x1002a240 | `ai::CommLayer::TicketTable::GetRequestType` | request type of a pending ticket, 0x107 when unknown |

**Token wire (msgdefs 211–214):** 211 `{type,ticket}` · 212 `{type, nonce[128], ticket}` ·
213 `{type, perm_id, cipher MEMBLOCK, ticket}` · 214 `{type, perm_id, cipher MEMBLOCK, nonce[128], ticket}`.

---

## 4. Key globals & vtables

All `[known]` (address and static value read from the binary).

**SADK.exe:**
- `g_pLobbyManager` @ `0x00885890` — `LobbyComm::System` singleton pointer (getter `LobbyManager_GetInstance` `0x462420`)
- `g_ClientProtocolVersion` @ `0x0087aed8` (static value 1000) — compared with a village server
  entry's `+0x30` by `AvatarScreen::Update`, `SelectVillageServerDialog::OnServerAddedOrChanged` and the
  version check (`LobbyComm::System::OnVersionChecked_State4to5` `0x464e70`)
- `DAT_007db51c` (= 0xFFFFFFFF) — "no village server" sentinel: initial `ServerList.selectedVillageServerId`,
  and the `-1` that `CreateVillageServerConnection` resolves to the selected server. `g_dwINVALID_SERVER_ID`
  @ `0x007db520` (= 0xFFFFFFFF) and `0x007db524` (= 0xFFFFFFFE, create pending) are the sentinels of
  `ServerList.gameServerId` (`+0x9c`)
- Property-name strings: `ChatChannelID` `0x7db918`, `ChatChannelZone` `0x7db928`, `ChatChannelsCount`
  `0x7db938`, `ServerPerm` `0x7db94c`, `Worldname` `0x7db964` (all read by `HandleEnterWorld`); `code`
  `0x7db5d8`, `PingCode` `0x7db620`, `PongCode` `0x7db640`, `tick` `0x7db6b4`, `id` `0x7db85c`
- `LobbyComm::VillageServerConnection` vtable @ `0x7db8d4` (17 slots, RTTI locator pointer @ `0x7db8d0`;
  `+0x3c` = OpenUserComm, `+0x14` = HandleLoggedIn) — struct `/LobbyComm/VillageServerConnection_vftable`
- `LobbyComm::System` vtable @ `0x7dacb0` (7 slots, struct `/LobbyComm/System_vftable`)
- `LobbyComm::ServerList` vtables: primary @ `0x7dafcc`, `IGameServerObserver` callbacks @ `0x7daf8c`;
  `LobbyComm::GameServerInfo` vtable @ `0x7de8b8`; `LobbyComm::VillageServerInfo` vtable @ `0x7dcfd4`
- `LobbyComm::LobbyMessage` vtable @ `0x7db594`; `LobbyComm::BaseConnection` vtable @ `0x7de8cc`

**tincat3.dll:**
- factory vtable @ `0x1004DE84`; CommLayer vtable @ `0x1004EC6C`
- the comm-layer payload magic literal **0x26B6** is the only one (a single layer for the whole client)

---

## 5. Village message map (`HandleMessage` `0x470a90`)

`1000 EnterWorld → 0x46f670 · 1001 AvatarData → 0x46e1d0 · 1002 AvatarLoggedIn → 0x46e390 ·
1003 AvatarRemove → 0x46e570 · 1004 NPCData → 0x46f8c0 · 1005 WorldTick → 0x46f620 ·
1006 WorldLoginAck → 0x46ec50 · 0xED6/3798 PingCode (out, SendPing 0x46c150) ·
0xED7/3799 PongCode → 0x46c250 · 0x7D2/2002 LeaveVillageRequest (out, 0x46bde0)`.

The switch itself is `[known]`; status per message is in §2b. Wire layouts and what the stub sends:
`docs/message-catalog.md`, `lobby/sadk_lobby/village.py`.

### 5a. Remaining switch cases

Handler identity `[known]` (visible in the switch). Field layouts and stub status:
`docs/message-catalog.md`; `docs/IN_WORLD_PRESENCE.md`. All names are in
`LobbyComm::VillageServerConnection`.

| msg | dec | handler | role |
|---|---|---|---|
| 0xC1C | 3100 | `HandleAvatarActiveItemsUpdate` `0x0046e660` | by `ownr` id: re-reads the 4-slot equipped-items block |
| 0xC1D | 3101 | `HandleAvatarInventoryUpdate` `0x0046e6f0` | by `ownr` id: re-reads the `sltcnt`-prefixed inventory block |
| 0xC1E | 3102 | `HandleAvatarItemsFullSync` `0x0046e780` | by `ownr` id: both of the above in one message |
| 0xC80 | 3200 | `HandleAvatarLevelExpUpdate` `0x0046c940` | by `ownr` id: `lvl` + `exp` only |
| 0xC81 | 3201 | `HandleAvatarStatsUpdate` `0x0046c9c0` | by `ownr` id: `lvl` / `exp` / `gold` / `glod` |
| 0xE11 | 3601 | `HandleShopInventoryData` `0x004706b0` | `NPCID` / `ShopID` / `ShopName` / `SellMod` / `StockCount` + N item entries |
| 0xE1B | 3611 | `HandleShopBuyResult` `0x00470990` | `ShopID` + 1-bit `Result` |
| 0xE25 | 3621 | `HandleShopSellResult` `0x00470a10` | `ShopID` + 1-bit `Result` |
| 0xF46 | 3910 | `HandleTradeRequest` `0x0046d920` | `tradeID` / `playerA` / `playerAName`; one trade at a time |
| 0xF5A | 3930 | `HandleTradeOffer` `0x0046cd10` | `playerA` / `playerB` / `goldA` / `goldB` / `funniesA` / `funniesB` + 2 × 6-slot item vectors |
| 0xD8 | 216 | `HandleMiniGameTableRemove` `0x0046f510` | acts only in state VillageEntered: clears the table's seats, fires the table-removed observers (`this+0x74`), deletes the proxy and erases it from the map at `this+0x178` |
| 0xD9 | 217 | `HandleMiniGameTableUpdate` `0x0046f380` | acts only in state VillageEntered: on a table's first update assigns its chat channel and fires the table-shown observers (`this+0x68`); then the proxy reads its type-specific state and the table-updated observers (`this+0x80`) fire |
| 0xDA | 218 | `HandleMiniGameTableCreate` `0x0046eb70` | not state-gated: creates a `MiniGameProxy` of the key's type, stores it in the map at `this+0x178` and lets it read its state; fires no observers (the table shows on a later 0xD9) |
| 0xDB | 219 | `HandleMiniGameNoTableLeft` `0x0046f4d0` | no payload; fires the observer list at `this+0x8c` |
| 0xDC | 220 | `HandleMiniGameNoPlayerSlotLeft` `0x0046f4f0` | no payload; fires the observer list at `this+0x98` |
| 0x12F | 303 | `HandleMiniGameHand` `0x0046d380` | reads `msgprt` + `rnid` and routes the hand message (two cards + hand value) to the table's proxy found through `this+0x178` |

**Avatar record readers** (shared by 1001 AvatarData and the 0xC1x / 0xC8x cases above; 1004 NPCData has
its own reader, `NPCProxy::ReadFromMessage` `0x47b5c0`). Field tables: `docs/IN_WORLD_PRESENCE.md`.

| Addr | Name | Role |
|---|---|---|
| 0x00482c20 | `LobbyComm::AvatarProxy::ReadDataBlocks` | reads the 4-bit `dtblcks` block mask and dispatches to the sub-blocks below |
| 0x004824b0 | `LobbyComm::AvatarProxy::ReadLocationBlock` | `tick` + quantised position / rotation + `rnng` / `jmp` flags |
| 0x004825f0 | `LobbyComm::AvatarProxy::ReadStyleBlock` | `name` + `trbgndr` + hair / skin / shirt / trouser + 4 × `addColor` |
| 0x0048abe0 | `ai::village::AvatarItemContainer::ReadActiveItemsBlock` | 4 fixed equip slots, each through `AvatarProxy_ReadItemSlot` `0x0048ab40` |
| 0x00481da0 | `LobbyComm::AvatarProxy::ReadStatsBlock` | `lvl` / `exp` / `gold` / `glod` |
| 0x0048ac20 | `ai::village::AvatarItemContainer::ReadInventoryBlock` | `sltcnt`-prefixed variable-length item list |
| 0x00481d50 | `LobbyComm::AvatarProxy::ReadLevelExpBlock` | `lvl` / `exp` only (used by 0xC80) |
| 0x00481d30 / 0x00481d40 | `LobbyComm::AvatarProxy::ReadActiveItems` / `ReadInventory` | thin forwarders used by 0xC1C–0xC1E |
| 0x0048f530 | `LobbyComm::LobbyMessage::FinishRead` | idempotent end-of-read, called at the end of every reader above |
| 0x00464300 | `ai::std::MsvcList::ObserverList_NotifyAll` | fires every callback of an observer list with `(sender, arg)`; iterates a copy and leaves the list itself unchanged |
| 0x004780c0 | `LobbyComm::CharacterManager::CacheUserName` | records an id ↔ name pair in the CharacterManager lookup caches (`+0x1a0` / `+0x1ac`); called by `HandleAvatarData` |

**Avatar classes.** `LobbyComm::AvatarProxy` (0xe0 bytes, vtable `0x007dd038`) and `LobbyComm::NPCProxy`
(0x120 bytes, vtable `0x007dc7d8`) derive from `LobbyComm::ActorProxy` (vtable `0x007db574`; both
constructors call `ActorProxy::ctor` `0x0046bb10`) `[known]`; `LobbyComm::IActor` (vtable `0x007db558`,
6 pure slots) is the base of `ActorProxy` at displacement 0 in the RTTI `[known]`. Fields and slots:
[types.md](types.md) §1.10.
`LobbyComm::IAvatarDataBlock` (`/LobbyComm/IAvatarDataBlock`, 8 bytes, vtable `0x007de3dc`, 8 slots:
`Destructor` / `ReadFromBuffer` / `WriteToBuffer` / `Deserialize` / `Serialize` / `GetVariant` /
`GetSize` / `Clear`) is the base interface of `AvatarCreationBlockEx`, `AvatarAppearanceBlockEx`,
`AvatarStyleBlockEx`, `AvatarStatsBlockEx`, `AvatarActiveItemsBlockEx` and `AvatarInventoryBlockEx`
`[known]`. This family serialises to and from a byte buffer (`ReadFromBuffer` `0x00486120`,
`WriteToBuffer` `0x004861c0`, per-class `Deserialize(stream)` / `Serialize(stream)`), not through the
`LobbyMessage` readers above: it is a separate serialisation path from the `AvatarProxy::Read*`
functions `[known]`. The stream type is `NComm::MemoryStream` `[known]` (`ReadFromBuffer` and
`WriteToBuffer` build one on the stack and pass it to slots 3 and 4). Its field widths are `[known]` (each class's own `Deserialize`); its field names are generic
(`fieldN`) and where the game uses the family is `[TODO]`.

---

## 6. Data loading: start-up vs per match

Full picture and status tags: `docs/data-loading.md`.

| Address | Name | What |
|---|---|---|
| `0x004075d0` | `CApplicationEx::Initialize` | once: `FileScanHolder::ScanDirectory("data\\")`, the property database (`Properties_RegisterLuaLibrary` `0x00550e40`, `ai::properties::PropertiesDb::RunPropertyScript("data")` `0x0054f8d0`), sound, lobby, menus |
| `0x0054a140` | `NProperties::StaticAccess::EnsureInstance` | the `PropertiesDb` singleton `g_pPropertiesStaticAccess` `0x00889dd8` (0xc4 bytes) |
| `0x005494a0` | `Properties_Db_ClearAll` | empties every property table, `bLoaded` (+0xc0) = 0; only caller `CApplicationEx::Shutdown` `0x00401cb0` |
| `0x0067e7e0` | `Scene_CreateGlobal` | `new S2CG::Scene` into `g_pScene` `0x0088ca60`; caller `nMenu::Game::OnEnter` `0x005eed00` |
| `0x0067e8a0` | `Scene_DestroyGlobal` | frees `g_pScene`; caller `nMenu::Game::OnLeave` `0x005eb030` |
| `0x006824c0` | `S2CG::Scene::Init` | scene vtable `0x007f8f2c` slot 0; per match: `graphics.xml`, `items.xml`, `settler_config.xml`, `settler_animations.xml`, `buildings.xml`, `animals.xml`, `ships.xml` |
| `0x007842e0` | `nGame::System::BuildScene` | from `BuildWorld` `0x00784d40`: `terrain_static_data.xml`, `map_objects.xml`, then `Scene::Init` |
| `0x005ab800` | `GameData_ComputeBuildChecksum` | not cached: `NComm_GetBuildChecksum` `0x0041f240` recomputes on each join |
| `0x006e4310` | `ai::file::FileScanHolder::FindFilesInDirectory` | lists the disk live (`FindFirstFileA` / `FindNextFileA`) |

## 7. S2TFTP, the in-match file transfer

Packets, flow, speed and pitfalls: `docs/s2tftp.md`.

| Address | Name | What |
|---|---|---|
| `0x004190f0` | `NComm::TinCatNetwork::RequestFileFromHost` | vtable `+0xa4`: `RequestFile(host 0xEFFFFFCC, remote, local, queueIfBusy)` |
| `0x004084d0` | `NComm_Manager::RequestFileFromHost` | the joiner's map requests (from `HandleEvent`) |
| `0x0040b410` | `NComm_Manager::Shutdown` | the end of every network session |
| `0x0040b470` | `NComm_Manager::KickPlayer` | host only: `(peer, reason, sendKickEvent)` |
| `0x00427140` | `ai::net::S2TftpManager::RequestFile` | start or queue a ReadRequest; one transfer per peer |
| `0x00427400` | `ai::net::S2TftpManager::ProcessQueue` | starts the next queued request |
| `0x00428110` | `ai::net::S2TftpManager::OnReceive` | all `0x3eb` packets; a ReadRequest serves `<My Documents>\<name>` |
| `0x00426a30` | `ai::net::S2TftpSession::BeginSend` | block size from the connection type: 512 / 1K / 2K / 4K |
| `0x00427f10` | `ai::net::S2TftpSession::OnAck` | stop-and-wait: next block only after the ack |
| `0x00427cf0` | `ai::net::S2TftpSession::OnData` | acks each block; completes on a short block |
| `0x0041f220` | `UserProfile_GetConnectionType` | UserProfile `+0x94`, option `cConnectionType` (0 none … 4 LAN) |

## 8. Match wager

| Address | Name | What |
|---|---|---|
| 0x004625c0 | `LobbyComm::System::GetLocalAvatar` | returns `this +0x554`, the local player's `AvatarProxy` `[inferred]` type |
| 0x00413a00 / 0x00413a10 | `NComm::EventGameInformation::GetWager` / `SetWager` | the wager, game information `+0x233` `[known]` |
| 0x0040c1b0 | `NComm_Manager::SetWager` | host: store, clear the human slots' ready state on change, broadcast `[known]` |
| 0x00457d50 | `LobbyMenu::SetupGameDialog::HandleSettingsClicks` | BetGame opens the stack dialog, 0 .. the host's gold `[known]` |
| 0x00457900 | `LobbyMenu::SetupGameDialog::OnWagerChosen` | clamp >= 0, host calls `SetWager` `[known]` |
| 0x00454cf0 | `LobbyMenu::SetupGameDialog::UpdatePlayerRow` | ready button: wager <= own gold, no AI slot unless wager 0 `[known]` |
| 0x00457a00 | `LobbyMenu::SetupGameDialog::Update` | un-readies the local player when gold < wager `[known]` |
| 0x0046b3d0 | `RefereeResult_GetName` | result code 0..20 → name, table `0x0087aee0` `[known]` |

Fields: `LobbyComm::System +0x54c localPermId`, `+0x554 localAvatar`, `+0x558` avatar map (aliased by
`VillageServerConnection +0x170`) `[known]`, `+0x564` NPC map (aliased by `VillageServerConnection +0x174`)
`[inferred]`; `NComm::EventGameInformation +0x22f gameSeed` (chest contents only,
`Game_DistributeChestsForNetworkMatch` `0x00775dd0`), `+0x233 wager`, `+0x237 settingsCrc`. Protocol side:
`docs/message-catalog.md`, 0xDB6 RegisterGame.
