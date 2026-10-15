# Lobby client state: managers, proxies and observers behind the wire

Everything the client keeps in memory about the online lobby, and every transition of that state:
`LobbyComm::System` and its state machine, the five connections, the character manager and its action
queue, the actor proxies, mail, buddies, chat channels, the server list, the observer lists and the
`LobbyMessage` bit stream.

**Conventions.** `S 00xxxxxx` is an address in `sadk_noav.exe`, `T 10xxxxxx` one in `tincat3.dll`.
Offsets such as `LM+0x57c` are relative to the named object (`LM` = `LobbyComm::System`, the lobby manager, `VSC` =
`VillageServerConnection`, `UCC` = `UserCommConnection`, `CM` = `CharacterManager`, `PO` =
`PostOffice`, `SL` = `ServerList`). Tags: **[known]** = read in the decompiled code at the address
given, or in the named data file; **[inferred]** = one step of reasoning from that, or taken from
the function's mapped description without a re-read of every branch; **[TODO]** = open. Message
numbers are decimal NETMSG ids (lobby and chat connections) or decimal `LobbyMessage` ids (village
and referee connections).

Wire layouts are **not** repeated here. They are in:

| Topic | Document |
|---|---|
| Every message, field by field; tickets; server decisions | [`../message-catalog.md`](../message-catalog.md) |
| Flows a server has to run (characters, world entry, presence, NPCs, shops, leave) | [`../village-and-character-protocol.md`](../village-and-character-protocol.md) |
| Endpoints, frame, authentication | [`../message-catalog.md`](../message-catalog.md), "Wire encoding" and "Login, authentication and the UC/chat connection"; the flows in brief: [`../protocol-overview.md`](../protocol-overview.md) |
| Referee chain and match start | [`../MATCH_START.md`](../MATCH_START.md) |
| Hosting, game browser, pre-game room, `GameServerInfo` | [`match-setup-room.md`](match-setup-room.md) |
| The peer-to-peer match session | [`network-session.md`](network-session.md) |
| Struct and vtable tables as mapped in Ghidra | [`../types.md`](../types.md) §1 |
| Main loop that calls the pump | [`app-shell.md`](app-shell.md) §4 |
| The `ChatSystem` widget | [`ui-toolkit.md`](ui-toolkit.md) §3.14 |

---

## 1. Purpose and scope

The lobby client is a set of state holders that sit between the TinCat network library and the
lobby user interface:

- `LobbyComm::System` owns the comm layer and all other objects, and runs the login state machine.
- Four *managers* wrap one TinCat interface each and keep the answers: `ServerList`,
  `ServerMessages` (message of the day), `Properties`, `CharacterManager`, `PostOffice`.
- Five *connections* (`BaseConnection` and four subclasses) each bind one TinCat transport.
- *Proxies* (`AvatarProxy`, `NPCProxy`, `MiniGameProxy`) mirror server-side objects of the 3D
  village.
- *Observer lists* are the only path from this layer to the user interface and to the 3D lobby.

In scope: the fields these objects carry, what writes them, the state machine with its timers and
retries, the request queues, the bit-stream encoding of `LobbyMessage`, the client-side item model,
and what survives a village leave, a match and the return. Out of scope: wire layouts (linked
above), dialog behaviour, the 3D lobby scene, minigame rules.

The whole layer is absent when the game is started with `-nolobby` (`app-shell.md` §3.3 step 11)
[known].

---

## 2. Data model

### 2.1 Ownership

```
LobbyComm::System (singleton g_pLobbyManager S 00885890, 0x5a8 bytes)
 ├─ +0x4c  tincat3 CommLayer            ├─ +0x50  tincat3 ConnectionManager
 ├─ +0x54  ServerList            (embedded)   village servers, hosted games, referee assign
 ├─ +0x100 ServerMessages        (embedded)   message of the day
 ├─ +0x140 CharacterManager      (embedded)   characters, buddies, ignore list, name caches
 │          └─ +0xa0 AvatarProxy (embedded)   working / preview avatar
 ├─ +0x2f8 PostOffice            (embedded)   mail
 ├─ +0x3bc Properties            (embedded)   property requests (version check)
 ├─ +0x3d8 UserCommConnection    (embedded)   chat
 ├─ +0x490 RefereeServerConnection (embedded) match arbiter
 ├─ +0x540 VillageServerConnection* (heap, 0x280)  3D village
 ├─ +0x544 GameServerConnection*    (heap, 0x38)
 ├─ +0x554 AvatarProxy*  local avatar (heap copy of the selected character)
 ├─ +0x558 std::map<actor id, AvatarProxy*>   avatars in the world (VSC+0x170 points here)
 ├─ +0x564 std::map<npc id, NPCProxy*>        NPCs (VSC+0x174 points here)
 └─ +0x570 ItemDatabase  std::map<item id, ItemInfo>
```

[known] constructor S 00463fd0; allocation size S 00464280. Every embedded object and both heap
connections are created once in the constructor and live until shutdown; a "connection exists"
below means "has a transport bound" (§2.5).

### 2.2 `LobbyComm::System`

| Offset | Type | Field | Written by | Tag |
|---|---|---|---|---|
| +0x04 | observer list | connection lost | §2.19 | [known] |
| +0x10 | observer list | global data loaded | §2.19 | [known] |
| +0x1c | observer list | login failed | §2.19 | [known] |
| +0x28 | observer list | logged out | §2.19 | [known] |
| +0x34 | observer list | never fired | §2.19 | [known] |
| +0x40 | observer list | version check failed | §2.19 | [known] |
| +0x4c | ptr | CommLayer, from `TinCat_CreateCommLayer(0, 0x26B6, 5, "<log dir>\commLayer.log")` | `Initialize` S 004643d0 | [known] |
| +0x50 | ptr | ConnectionManager (`CommLayer vtbl+4`); the manager registers itself there as callback sink | `Initialize` | [known] |
| +0x548 | u32 | **account id**: second argument of the lobby login callback. Sent as `user_id` in every account-level request (§5) | `OnLoggedIn` S 00463a10; 0 on login failure and in `Destroy` | [known] store, [inferred] meaning |
| +0x54c | u32 | **local perm id** = id of the character in use. Getter S 00462510. Compared with avatar ids, the referee `PermID`, chat `from_id` | `VSC::OnUserCommLoggedIn` S 004704e0; 0 in `Destroy` | [known] |
| +0x550 | i32 | village server id last logged in to (−1 = none). Preferred server when the client returns from a match | `OnLoggedIn` (village branch); −1 in ctor and `Destroy` | [known] |
| +0x554 | ptr | local `AvatarProxy` | `SetLocalAvatar` S 004626c0, `ClearLocalAvatar` S 00462570 | [known] |
| +0x57c | enum | state (§2.3) | §3.1 | [known] |
| +0x580 | u32 | referee server id (0 = none assigned) | `SetRefereeServerAddress` S 004625d0 | [known] |
| +0x584 | bool | referee assign requested | pump S 00464ee0 | [known] |
| +0x588 | i32 | referee retry timer, milliseconds | S 004625d0 sets 60000; pump counts down | [known] |
| +0x58c | std::string | e-mail address waiting to be sent after a registration | `CreateUser` S 004633f0 in state 1, before the request is issued (it stays stored when the library refuses the request); cleared by the pump | [known] |

The `LobbyComm::System` object is also the `CommLayer::IConnectionCallback` of the ConnectionManager.
Its vtable (S 007dacb0) slots 1 to 6 are `OnLoggedIn`, `OnLoginFailed`, `OnLoggedOut`,
`OnConnectionLost`, `DispatchInboundToConnection`, `OnStatisticsConnectionReceived` [known,
`types.md` §1.2]. A connection is identified in these callbacks by its transport object pointer:
the lobby connection is the one `ConnectionManager vtbl+0xc` returns, the others are matched with
`BaseConnection::HasTransport` S 0048dd30 [known].

### 2.3 `LobbyManagerState` (`LM+0x57c`)

| Value | Name (string in S 00462a00) | Tag |
|---|---|---|
| 0 | (none; `LobbyManagerState: Unknown`): constructed, or destroyed | [known] |
| 1 | `Disconnected` | [known] |
| 2 | `Authorizing` | [known] |
| 3 | `Authorized` | [known] |
| 4 | `Checkking Version` (spelling as in the binary) | [known] |
| 5 | `Version Checked` | [known] |
| 6 | `Loading Global Data` | [known] |
| 7 | `Global Data loaded` | [known] |
| 8 | `Entering Village` | [known] |
| 9 | `Village Entered` | [known] |
| 10 | `Leaving Village` | [known] |
| 11 | `Village Left` | [known] |
| 12 | `Connection Lost` | [known] |

The transitions are in §3.1.

### 2.4 `ASyncAction` (0x8 bytes): base of every manager

`ServerList`, `ServerMessages`, `CharacterManager`, `PostOffice` and `Properties` derive from it
[known, vtable layouts in the type cache].

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x4 | bool | **changed**: set when the manager's data changed, cleared by the consumer. Slot 1 reads, slot 2 sets, slot 3 clears | [inferred] |
| +0x5 | bool | **busy**: one request is on the wire | [known] S 0048ee90 |

| Slot | Offset | Method | Tag |
|---|---|---|---|
| 4 | +0x10 | `IsBusy` S 0048ee90 | [known] |
| 5 | +0x14 | `TryBeginBusy` S 0048eea0: false if already busy, else sets it | [known] |
| 6 | +0x18 | `TryEndBusy` S 0048eeb0: false if not busy, else clears it | [known] |
| 7 | +0x1c | `ProcessActions`: the per-tick pump of the manager (empty in the base) | [known] |
| 8 | +0x20 | `Reset` | [known] |

Rule common to all managers: **one request in flight per manager**. A request is sent only when
`IsBusy` is false; a successful send sets busy; the result callback clears it. There is no timeout:
a request whose answer never arrives leaves the manager busy until `Reset` [known for each pump
below; the absence of a timer is [inferred] from the pumps' bodies].

### 2.5 `BaseConnection` (0x38 bytes) and the five connections

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x04 | observer list | logged in (connection, id) | [known] S 0048e050 |
| +0x10 | observer list | login failed (connection, error) | [known] S 0048e170 |
| +0x1c | observer list | logged out (connection, id) | [known] S 0048e2a0 |
| +0x28 | observer list | disconnected (connection, reason) | [known] S 0048e3c0 |
| +0x34 | ptr | transport: a tincat3 connection object; 0 = not bound | [known] |

Transport interface as the client uses it [known at the call sites]:

| vtbl | Call | Use |
|---|---|---|
| +0x04 | `()` | unique id of the connection (logged only) |
| +0x0c | `GetState()` | see the state list below |
| +0x10 | `Login(permId, 0)` | log in to the server behind the transport with a perm id |
| +0x18 | `Logout()` | start the logout |
| +0x1c | `Send(u16 typeWord, data, byteLength)` | send one `LobbyMessage` (the library wraps it in NETMSG 74) |

Transport states the client tests: **8** = logged in (`IsLoggedIn` S 0048dce0, `SendLeaveVillageRequest`,
`UserCommConnection::Logout`); **0**, **8** and **9** are "not pending", every other value is
"connecting or logging in" (`IsConnectionPending` S 0048dd00); **2** on the lobby connection makes
`Logout` synthesise the logged-out callback itself (S 00463710) [known]. The meaning of the other
values is tincat3-internal (`message-catalog.md`, "Login sequence at a glance").

`Initialize(transport)` S 0048de70 fails with a log line if a transport is already bound;
`Destroy()` S 0048dec0 clears the pointer [known]. `SendMessage(msg)` S 0048dfa0 returns false
without a transport; otherwise it finalises the message if needed and calls
`Send(header & 0xffff, data, byteLength)`; a non-zero result is logged and returns false [known].

| Connection | Class, location | Transport bound | Transport released | Login | Inbound data |
|---|---|---|---|---|---|
| **Lobby** | none: owned by tincat3; managers use CommLayer interfaces | `Login` / `CreateUser` (state 1 only) | disconnect | NETMSG 204 or 203 | tincat3 managers → observer callbacks of §2.9 to §2.13 |
| **User comm (chat)** | `UserCommConnection`, `LM+0x3d8` | pump, state 5 → 6; again right after a chat connection loss | lobby logout; chat connection loss | `OpenCommunication(id)`: transport `Login(id, 0)` when the village is entered | tincat3 `ChatChannelManager` → `IChatChannelObserver` callbacks; the raw-data slot is an empty stub (S 0047f6e0) and the inbound dispatcher S 00462760 routes only to the village, game server and referee connections |
| **Village** | `VillageServerConnection`, `LM+0x540` | `CreateVillageServerConnection(serverId)` S 00463850 | village logout, login failure or loss (`Destroy`) | transport `Login(characterId, 0)` after chat login | `HandleMessage` S 00470a90 |
| **Game server** | `GameServerConnection`, `LM+0x544` | [TODO] no caller of its `Initialize` (S 0048eda0) is in the decompiled code; not called while hosting [live, 2026-10-14] | – | – | no-op slot |
| **Referee** | `RefereeServerConnection`, `LM+0x490` | pump, state ≥ 6, once a referee server id is latched | referee logout; a different referee id; lobby logout | `Login(localPermId)` at match start (`MATCH_START.md`) | `OnReceive` S 0047b090 |

[known] for every cell with an address in §3. The chat connection is bound with the results of
`CommLayer vtbl+0x30()` and `ConnectionManager vtbl+0x10(…)`; the village and referee transports
come from `ConnectionManager vtbl+0x38(serverId)` (result 0 or 0xCD accepted) then
`vtbl+0x18(serverId)` [known] S 00464ee0, S 00463850, S 00462910.

`GameServerConnection::OnLoggedIn` S 0048edf0 would start the peer-to-peer network
(`NComm_Manager::StartUpNetwork(3)`, `ConnectAndJoin`) without firing the logged-in list [known];
hosting a room and leaving it called neither `Initialize` S 0048eda0 nor `OnLoggedIn` [live, 2026-10-14];
whether joining a room takes this path is [TODO] (§10).

### 2.6 `VillageServerConnection` (0x280 bytes)

| Offset | Type | Field | Initial | Tag |
|---|---|---|---|---|
| +0x38 … +0x14c | 24 observer lists | world events (§2.19) | empty | [known] ctor S 0046eee0 |
| +0x158 | ptr | owning `LobbyComm::System` | ctor arg | [known] |
| +0x15c | i32 | village server id | −1 | [known] S 0046dac0 |
| +0x160 | u32 | `ServerPerm` from EnterWorld: the perm id under which the village server itself speaks in chat | 0 | [known] S 0046f670 |
| +0x164 | std::map&lt;u8, u32&gt; | chat channel per zone key (§3.12) | empty | [known] |
| +0x170 | ptr | avatar map (`LM+0x558`) | | [known] |
| +0x174 | ptr | NPC map (`LM+0x564`) | | [known] |
| +0x178 | std::map | minigame tables, key `msgprt \| rnid << 16` (the three bytes at table key `+2`) → `MiniGameProxy*` | empty | [known] S 0046eb70, S 00471290 |
| +0x184, +0x198, +0x1ac, +0x1c0, +0x1d4, +0x1e8, +0x1fc, +0x210 | 8 × std::deque&lt;proxy*&gt; | deferred events (§3.6) | empty | [known] |
| +0x224 | bool | leave acknowledged (1006 with the magic code seen); written by the constructor and by S 0046ec50 only, no reader in the decompiled code [inferred] | 0 | [known] S 0046ec50 |
| +0x225 | u8 | zone whose chat channel is joined; 0x0F = none | 0x0F | [known] |
| +0x226 | bool | zone channel join pending | 0 | [known] S 0046e860 |
| +0x228 | std::string | world name; `<UNNAMED>` when the server sent an empty one | empty | [known] |
| +0x244 | i32 | link quality 0 (worst) … 3 (best) | 3 | [known] S 0046c250 |
| +0x248 | u32 | code of the ping awaiting its pong; `0x80008000` = none | 0x80008000 | [known] |
| +0x24c | f32 | time the ping was sent, seconds; −1 = none | −1 | [known] |
| +0x250 | f32 | time the pong arrived; −1 = none | −1 | [known] |
| +0x254 | f32 | countdown to the next ping, seconds | −1 | [known] |
| +0x258, +0x25c, +0x260, +0x264 | u32, u32, f32, vector | open shop: NPC id, shop id, sell modifier, stock `{ItemID, Buy, Sell}` | 0 | [inferred] S 004706b0 |
| +0x274 | bool | trade request pending | 0 | [inferred] S 0046d920 |
| +0x275 | bool | trade active | 0 | [inferred] |
| +0x278, +0x27c, +0x27e | u32, u16, u8 | trade id and trade message key | 0, 0xFFFF, 0xFF | [known] ctor |

### 2.7 `UserCommConnection` (0xb8 bytes), `ChatChannelInfo`, `PrivateChatRequest`

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x38 | interface | `IChatChannelObserver` face (callbacks run with `this = UCC+0x38`) | [known] |
| +0x3c … +0x84 | 7 observer lists | chat events (§2.19) | [known] |
| +0x90 | ptr | tincat3 `ChatChannelManager`; 0 = chat not attached | [known] |
| +0x94 | std::vector&lt;ChatChannelInfo&gt; | channels the client was told about | [inferred] |
| +0xa4 | std::deque&lt;PrivateChatRequest&gt; | whisper queue | [inferred] |

`ChatChannelInfo` (0x28): `+0x04` channel id; `+0x08` name; `+0x24 … +0x27` four bools copied from
the tincat3 channel descriptor (`descriptor +0x18`, `+0x14`, `+0x1c`, `+0x20` each compared with 1)
[known, type cache]. [TODO] the meaning of the four bools (§10).

`PrivateChatRequest` (0x40): `+0x00` target name; `+0x1c` target perm id (0 until resolved); `+0x20`
text; `+0x3c` state: **0** name unresolved, **1** lookup running, **2** id known, ready to send
[inferred].

### 2.8 `RefereeServerConnection` (0xb0 bytes)

`BaseConnection` plus ten observer lists (§2.19). It keeps no other state: the referee login gate
and its retry counters live in the world screen (`MATCH_START.md`, "arm-state fields") [known,
type cache; ctor S 004792a0].

### 2.9 `ServerList` (0xac bytes) and `VillageServerInfo` (0x38 bytes)

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x08 | interface | `IGameServerObserver` face | [known] |
| +0x0c, +0x18, +0x24 | observer lists | village server added, updated, removed | [inferred] |
| +0x30, +0x3c, +0x48 | observer lists | hosted game added, updated, removed | [inferred] |
| +0x54, +0x60 | observer lists | game create succeeded, failed | [inferred] |
| +0x6c | ptr | tincat3 `GameServerManager` | [known] |
| +0x70 | std::vector&lt;VillageServerInfo*&gt; | village servers | [known] |
| +0x80 | u32 | selected village server id; −1 = none | [known] S 00468380 |
| +0x84 | std::vector&lt;GameServerInfo*&gt; | hosted games (`match-setup-room.md` §2.4) | [known] |
| +0x94 | u32 | selected game id; −1 = none | [known] S 0046a160, S 0046a5e0 |
| +0x9c | u32 | hosted game id: −1 none, −2 create pending, else the id (`match-setup-room.md` §2.5) | [known] |
| +0xa0 | bool | **keep list**: set while the player switches village server; makes `Reset` and `StartObservation` do nothing | [known] S 00468c50, S 00468e80, S 00440690 |
| +0xa4, +0xa8 | ptr, fn | pending referee-assign callback (context, function) | [known] S 00468f60 |

`VillageServerInfo`, one per village server, filled from a game-server descriptor of message 170
[known] S 00481640, defaults S 00481790; the 170 field names are those of `message-catalog.md`:

| Offset | Type | Field | Source in 170 |
|---|---|---|---|
| +0x04 | i32 | server id (−1 default) | `server_id` |
| +0x08 | std::string | name | `name` |
| +0x24 | u32 | port (no reader found) | `port` |
| +0x28 | u32 | current players | `cur_players` |
| +0x2c | u32 | maximum players; 0 = no limit | `max_players` |
| +0x30 | i32 | protocol key (−1 default); must equal the client protocol version | `data` block: u32, MSB first |
| +0x34 | bool | excluded flag (1 default) | `data` block: next bit |
| +0x35 | bool | valid (0 default): `running != 0`; forced 0 when the `data` block is missing. `running` (descriptor `+0x4c`) is the same field §3.13 uses as add/remove opcode | `running` |

The `data` block is parsed with a `LobbyMessage` reader over the raw bytes (type word 0): a 32-bit
integer then one bit. The block is taken when its size is 5 or its pointer is non-null; otherwise
the entry logs `Invalid Server Data Block` and is invalid [known] S 00481640, S 0048f9a0.

### 2.10 `ServerMessages` (0x3c bytes) and `Properties` (0x1c bytes)

`ServerMessages`: `+0x10` initialised; `+0x14` tincat3 MotD manager; `+0x18` cyclic-message
manager; `+0x1c` **motdReceived** (the first of the four load flags of §3.3); `+0x20` MotD text in
ANSI, or the localised `!MOTD_ERROR` text formatted with the error code [known] S 004884d0,
S 00488550. The cyclic-message observer callbacks are empty [inferred, vtable in the type cache].

`Properties`: `+0x0c` tincat3 property manager; `+0x10` `std::list` of pending requests
`{i16 kategory, i16 index, callback object, callback function}` [known] S 0048ecb0.

### 2.11 `CharacterManager` (0x1b8 bytes)

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x08 … +0x50 | 7 observer lists | character and buddy events (§2.19) | [inferred] |
| +0x5c | ptr | tincat3 character interface (create, delete, look-up) | [known] |
| +0x60 | ptr | tincat3 user interface (character list, buddies, ignore list, account change) | [known] |
| +0x64, +0x6c | listeners | `CharacterObserverListener`, `UserObserverListener` (8 bytes each: vtable, owner) | [known] |
| +0x74 | std::deque&lt;CharManAction&gt; | action queue (count at +0x84) | [known] |
| +0x88 | bool | character list valid | [known] |
| +0x8c | std::map&lt;u32, AvatarProxy*&gt; | the account's characters | [known] |
| +0x98 | u32 | selected character id; 0 = none | [known] S 00472200 |
| +0xa0 | AvatarProxy (0xe0) | working avatar: edited in the creation and tailor dialogs | [known] S 00472350 |
| +0x180 | bool | buddy list valid | [known] |
| +0x184 | std::map&lt;u32, CharMgrUserEntry&gt; | buddies | [known] |
| +0x190 | bool | ignore list valid | [known] |
| +0x194 | std::map&lt;u32, std::string&gt; | ignored users: id → name | [known] |
| +0x1a0 | std::map&lt;u32, std::string&gt; | name cache: id → name | [known] |
| +0x1ac | std::map&lt;std::string, u32&gt; | id cache: lower-case name → id | [known] |

`CharManAction` (0x3c):

| Offset | Type | Field |
|---|---|---|
| +0x00 | enum | type (below) |
| +0x04 | u32 | account id (`LM+0x548`) for the types that send it, else 0 |
| +0x08 | u32 | target id (character or user) |
| +0x0c | std::string | name (character name, user name or e-mail address) |
| +0x28, +0x2c | ptr, u32 | heap copy of the creation data block and its size (create only) |
| +0x30, +0x34, +0x38 | ptr, fn, ptr | completion delegate: object, function `(result, targetId, &name, context)`, context |

[known] type cache, S 00476390.

| Type | Name (log string) | Sends | Tag |
|---|---|---|---|
| 0 | `CreateCharacter` | 86 AddCharacter | [known] |
| 1 | `DeleteCharacter` | 94 RemoveCharacter | [known] |
| 2 | `RefreshFriendList` | 56 RequestUserBuddyList | [known] |
| 3 | `AddToFriendList` | 98 AddUserBuddy | [known] |
| 4 | `RemoveFromFriendList` | 99 RemoveUserBuddy | [known] |
| 5 | `RefreshIgnoreList` | 157 RequestUserIgnoreList | [known] |
| 6 | `AddToIgnoreList` | 154 AddUserIgnore | [known] |
| 7 | `RemoveFromIgnoreList` | 155 RemoveUserIgnore | [known] |
| 8 | `LookUpName` | 72 RequestCharacters by id, or nothing (cache hit) | [known] |
| 9 | `LookUpID` | 72 RequestCharacters by name, or nothing (cache hit) | [known] |
| 10 | `UpdateEMail` | 88 ChangeUser, property mask 8 | [known] |

The enum values and names are [known] from the switch in S 00476390; the message numbers are
[inferred] from the tincat3 interface slot each type calls (`message-catalog.md`, "Characters",
"Buddies", "Ignore list", "Users and accounts").

`CharMgrUserEntry` (0x40), one buddy: `+0x00` user id; `+0x04` name; `+0x20` server id the buddy
is on, −1 when not on a server; `+0x24` that server's name [inferred] S 0046b540.

### 2.12 Actors: `ActorID`, `ActorProxy`, `AvatarProxy`, `NPCProxy`

`ActorID` (0xc): `+0x04` type (1 avatar, 2 NPC; 0 = empty in a seat), `+0x08` id [known]
S 00490e40. Type 1 for an avatar is [known] S 004818d0, 2 for an NPC S 0047b4d0, 0 for a cleared seat
S 00471c40.

`ActorProxy` (0x88) is the common base; it embeds its `ActorID` at `+0x04` (so the id is at
`+0x0c`).

| Offset | Type | Field | Default | Tag |
|---|---|---|---|---|
| +0x10 | std::string | name as received (UTF-8) | `" "` | [known] |
| +0x2c | std::string | name converted to ANSI (the displayed name) | `" "` | [known] |
| +0x48 | u8 | avatar: tribe in the high nibble, gender in the low nibble. NPC: body part | 0 | [known] |
| +0x49 … +0x4c | u8 × 4 | hair, skin, shirt, trouser colour index | 0 | [known] |
| +0x4d … +0x50 | u8 × 4 | additional colours 1 to 4 (avatar only) | 0 | [known] |
| +0x51 | u8 | zone | 0x0F | [known] |
| +0x52 | u8 | ghost zone | 0x0F | [known] |
| +0x54 | f32 × 3 | position x, y, z | global default vector | [known] |
| +0x60 | f32 × 4 | orientation quaternion, built from the heading about the fixed axis S 00882864 | identity global | [known] |
| +0x70 | f32 | heading, radians | 0 | [known] |
| +0x78 | u64 | last world tick of a location update (16-bit wire tick, widened) | 0 | [known] S 004824b0 |
| +0x80 | ptr | `MiniGameProxy` the actor sits at | 0 | [inferred] |
| +0x84 | ptr | the 3D lobby object created for this actor | 0 | [inferred] |

`AvatarProxy` (0xe0) adds:

| Offset | Type | Field | Default | Tag |
|---|---|---|---|---|
| +0x8c | AvatarItemContainer (0x3c) | equipment and backpack (below) | empty | [known] |
| +0xc8 | u32 | experience | 0 | [known] S 00481da0 |
| +0xcc | u32 | level | 1 | [known] |
| +0xd0 | u32 | gold (credits) | 0 | [known] S 004818d0 |
| +0xd4 | u32 | "glod": play money used by the minigames (wire name verbatim) | 0 | [known] store, [inferred] meaning |
| +0xd8 | bool | running | 0 | [known] |
| +0xd9 | bool | jumping | 0 | [known] |

`AvatarItemContainer` (0x3c): `+0x00` owner id; `+0x04`, `+0x10`, `+0x1c`, `+0x28` the four
equipment slots; `+0x34` backpack slot count; `+0x38` heap array of backpack slots. One slot
(`TradeItemSlot`, 0xc) is `{u32 slotType, u32 itemId, u32 count}` [known] S 0048acf0, S 0048af70.

`NPCProxy` (0x120) adds: `+0x88` description as received; `+0xa8` three action ids; `+0xb4` three
action parameters (written 0 with every action id); `+0xc0` NPC index (model selector); `+0xc4` NPC
type; `+0xc8` three action chat strings [known] S 0047b5c0 for the writes, offsets from the type
cache; wire in `village-and-character-protocol.md` §5.1. Only the first three actions of a record
store an id [known].

**Character data blocks.** The `data` blob of a character record carries six parts
(`village-and-character-protocol.md` §1.4). The parsers derive from `IAvatarDataBlock` (vtable, then
`u32 variant` at `+0x04`). Part 0 is read by `AvatarCreationBlockEx` (0x30) or by
`AvatarAppearanceBlockEx` (0x10), depending on the rule of §3.15; part 1 by `AvatarStyleBlockEx`
(0x28); part 2 by `AvatarActiveItemsBlockEx` (0x38: 4 slots of 12 bytes at `+0x08`); part 3 by
`AvatarInventoryBlockEx` (0xfc: `u32 count` at `+0x08`, 20 slots of 12 bytes at `+0x0c`); part 4 by
`AvatarStatsBlockEx` (0x2a). Part 5 has no parser: only its size is tested [known] S 00481e60; sizes
from the type cache. These objects are temporary: `ApplyCharacterDataBlocks` S 00481e60 copies their
values into the `AvatarProxy` and drops them.

### 2.13 `PostOffice` (0xc4 bytes), `Mail` (0x70 bytes), `PostOfficeRequest` (0x70 bytes)

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x08 | interface | `IMailObserver` face | [known] |
| +0x0c | ptr | tincat3 `MailManager`; 0 after `Destroy` | [known] |
| +0x10 | std::vector&lt;Mail&gt; | mailbox | [inferred] |
| +0x20 | Mail | copy of the mail whose body arrived last | [inferred] |
| +0x90 | std::deque&lt;PostOfficeRequest&gt; | request queue | [inferred] |
| +0xa8 | f32 | time the last header list arrived, seconds; −1 = no polling | [known] S 0047d880 |
| +0xac | observer list | mail received (PostOffice, Mail*) | [inferred] |
| +0xb8 | observer list | mail deleted (PostOffice, mail id) | [inferred] |

`Mail`:

| Offset | Type | Field | Source (record of message 149) |
|---|---|---|---|
| +0x04 | u32 | message id; 0 is invalid | `message_id` |
| +0x08 | u32 | delivery target | `delivery_target` |
| +0x0c | u32 | sender character id | `creator` |
| +0x10 | std::string | sender name; `???` until resolved | name cache or a look-up |
| +0x2c | u32 | creation time | `creation_time` |
| +0x30 | bool | read on the server | `status == 1` |
| +0x34 | std::string | subject | `title` |
| +0x50 | std::string | body | `message_text` (absent in header lists) |
| +0x6c | bool | new: not yet shown by the mailbox dialog | set on construction |
| +0x6d | bool | has content: subject and body both non-empty | computed |
| +0x6e | bool | read (local view) | `status == 1`, or `MarkRead` |
| +0x6f | bool | delete pending | `DeleteMail` |

[inferred] S 0048cce0, S 0048ced0; the record field order is [inferred] from the message
definition.

`PostOfficeRequest`: `+0x00` opcode (**0** none, **1** request headers, **2** request mail body,
**3** mark read, **4** delete, **5** send); `+0x04` send state (1 = recipient name must be
resolved, 2 = recipient id known); `+0x08` mail id; `+0x0c` recipient name; `+0x28` subject;
`+0x44` body; `+0x60` recipient id; `+0x64`, `+0x68` result delegate `(PostOffice*, result)`;
`+0x6c` retry count [inferred] S 0047d880.

### 2.14 `ItemDatabase` and `ItemInfo` (0x84 bytes)

`std::map<u32 itemId, ItemInfo>` at `LM+0x570`, loaded once from `ItemsClient.txt` (§6). The
fields of `ItemInfo` and the meaning of each token are in `village-and-character-protocol.md` §4.3
("`itmid` values …"). The fields this document relies on: `+0x00` id, `+0x04` name, `+0x40` slot
mask, `+0x44`, `+0x80` base value. An item is **valid** when its id is not 0 and its name is not
empty, or when `+0x44` is ≥ 1 [known] S 0048b100; offsets from the type cache.

### 2.15 `MiniGameProxy` (0x248 bytes)

One per minigame table in the village; subclasses for dice, poker and pawn chess add the rules
state. Base fields: `+0x04` table key (`mngt`, `scntbl`, `chtid`, `msgprt`, `rnid`); `+0x18` new
(not yet shown); `+0x1c` owning village connection; `+0x20` 3D table object; `+0x24` eight seats of
0x3c bytes `{occupant name, AvatarProxy*, ActorID, 3D object, seat index (0xFF empty), is local
player, stack, committed money}`; `+0x204` seats announced; `+0x208` local seat (−1 none);
`+0x20c` lowest occupied seat; `+0x210` occupied count; `+0x23c`, `+0x240` limits (0x7fffffff
default); `+0x244` maximum players (0xFF default) [inferred, type cache]. Wire and rules:
`village-and-character-protocol.md` §6.4, `message-catalog.md` "Minigames".

### 2.16 `LobbyMessage` (0x3c bytes)

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x04 | ByteBuffer (0x10) | `{vtable, data, size, ownsData}`. Sending: owned, zero-filled, `reservedSize` bytes. Receiving: borrows the received bytes | [known] S 0048fb00, S 0048fa50 |
| +0x14 | u8 | byte under construction, or the byte being read | [known] |
| +0x18 | u32 | bit cursor: bits written or read so far | [known] |
| +0x1c | i32 | byte index: next byte of the buffer | [known] |
| +0x20 | bool | names mode (type word bit 15) | [known] |
| +0x24 | u32 | category | [known] |
| +0x28 | u32 | message id | [known] |
| +0x2c | bool | finished (finalised, read to the end, or discarded) | [known] |
| +0x30 | u32, u32 | schema checksum accumulator: running CRC-32, byte count | [known] S 00762320 |
| +0x38 | i32 | 1 for a message built to send, 0 for a received one [known] S 0048fb00, S 0048fa50; no reader found [inferred] | |

### 2.17 Chat window data (`nUi::ChatSystem` in the world screen)

The world screen creates four channel tabs when it is shown [known] S 004389d0:

| Tab id | Text key | State on show | Fed by |
|---|---|---|---|
| 1 | `!CHATCHANNEL_GLOBAL` | enabled | village-wide chat channel (zone key 0xFF) |
| 2 | `!CHATCHANNEL_LOCAL` | enabled, **active** | chat channel of the current zone |
| 3 | `!CHATCHANNEL_MINIGAME` | disabled | chat channel of the minigame table (zone key 0xFE) |
| 4 | `!CHATCHANNEL_SETTLERS` | disabled | the pre-game room and match chat over the peer-to-peer session |

Reserved ids of `ChatSystem::AddText` S 004ae200: **0** ignored, **−1** every tab, **−2** the
active tab [known]. Each stored line keeps the sender's id as its tag (0 for system lines) and
returns it when the line is clicked [inferred]. The widget itself (line limit, wrapping, layout) is in `ui-toolkit.md`
§3.14.

### 2.18 `Lobby::CLobbyClient` (0x38 bytes): the glue to the 3D lobby

| Offset | Type | Field | Tag |
|---|---|---|---|
| +0x0c | ptr | the village connection it is subscribed to, or 0 | [known] S 00503f50 |
| +0x10 | bool | release the connection on the next update | [known] S 00503fc0 |
| +0x11 | bool | re-enter pending (village switch) | [known] S 00503560 |
| +0x14 | u32 | perm id to log in with on a re-enter (`LM+0x54c` at the time of the request) | [known] |
| +0x18 | f32 | re-enter timer, seconds | [known] |
| +0x1c | i32 | re-enter login retries | [known] S 00503800 |
| +0x20 | bool | use the default spawn point | [known] |
| +0x21 | bool | a saved position exists | [known] S 00503470 |
| +0x24, +0x30, +0x34, +0x35 | f32 × 3, f32, u8, u8 | saved position, heading, zone, ghost zone | [known] |

### 2.19 Observer lists

An observer list (0xc bytes) is an MSVC `std::list` of `{context, function}` pairs (`+4` head,
`+8` count). `Subscribe(list, context, function)` S 00458860 looks the pair up first and appends
only when it is not in the list yet, so a pair is never stored twice; the notify functions call
every entry with the context as `this` and the event arguments; they iterate over a copy, so a
callback may subscribe or unsubscribe [known] S 00458860, S 00464300; `types.md` §1.3.

The subscriber column lists every `Subscribe` call found in the decompiled code.

**`LobbyComm::System`**

| List | Fired when (arguments) | Subscribers |
|---|---|---|
| +0x04 | lobby connection lost (manager, error code) S 004647e0 | `AvatarScreen::OnConnectionLost` |
| +0x10 | state 6 → 7 (manager, account id) S 00464ee0 | `LoginDialog::OnLoginSucceeded`, `CreateAccountDialog::OnAccountCreated` |
| +0x1c | lobby login failed (manager, error code) S 00464a20; lobby logout in a state below 7 other than 1 (manager, 0x5479) S 00464bf0 | `LoginDialog::OnLoginFailed`, `CreateAccountDialog::OnCreateAccountFailed` |
| +0x28 | lobby logout in a state ≥ 7 (manager, reason) S 00464bf0 | `AvatarScreen::OnLobbyServerLoggedOut` |
| +0x34 | never | a no-op of `AvatarScreen` |
| +0x40 | version check failed (manager, 0x6f or 0x3e) S 00464e70 | `LoginDialog::OnVersionCheckFailed` |

[known]

**`BaseConnection` part of the village connection** (lists +0x04 … +0x28 of §2.5)

| List | Fired when | Subscribers |
|---|---|---|
| +0x10 login failed | chat login could not be started (0x91), chat login failed (−1), the selected character is not in the character map (−1), village login call failed (its error), or the transport reports a failed login | `CLobbyClient::OnVillageLoginFailed` |
| +0x1c logged out | village logout completed (§3.7) | `CLobbyClient::OnVillageConnectionClosed`, `WorldScreen::OnVillageConnectionLoggedOut` |
| +0x28 disconnected | village connection lost | `CLobbyClient::OnVillageConnectionClosed`, `WorldScreen::OnVillageConnectionDisconnected` |

[known] S 00470d50, S 004704e0, S 00470660, S 00503d00, S 004351a0

**`VillageServerConnection`** (arguments: connection, then the object named)

| List | Fired when | Subscribers | Tag |
|---|---|---|---|
| +0x38 | 1004 NPC record read (NPCProxy), at once | `CLobbyClient::OnNPCAdded` | [known] |
| +0x44 | world exit, once per NPC (NPCProxy) | `CLobbyClient::OnNPCRemoved` | [inferred] |
| +0x50 | a seat of an announced table was taken (table, seat) | `CLobbyClient` → table object | [inferred] |
| +0x5c | a seat of an announced table was left (table, seat) | `CLobbyClient` → table object | [inferred] |
| +0x68 | first 217 for a table that 218 created (table); 216 and 217 are handled only in state 9 | `CLobbyClient::OnMiniGameTableShown` | [known] |
| +0x74 | 216, or world exit (table) | `CLobbyClient` (destroys the table object) | [known] |
| +0x80 | 217 state read (table) | `CLobbyClient` → table object | [known] |
| +0x8c | 219 (connection) | `WorldScreen::OnJoinFailedNoTable` | [known] |
| +0x98 | 220 (connection) | `WorldScreen::OnJoinFailedNoSlot` | [known] |
| +0xa4 | 1002 avatar logged in (AvatarProxy), queued; also a placeholder avatar for an NPC seat, at once | a no-op of `CLobbyClient` | [known] |
| +0xb0 | 1003 avatar removed (AvatarProxy), queued; world exit, once per avatar | `CLobbyClient::OnAvatarRemoved` | [known] |
| +0xbc | 1001 avatar data (AvatarProxy), queued; placeholder avatar, at once | `CLobbyClient::UpdateAvatar` | [known] |
| +0xc8 | 3100 active items (AvatarProxy), queued | `CLobbyClient::OnAvatarItemsChanged` | [known] |
| +0xd4 | 3101 inventory (AvatarProxy), queued | none found | [known] |
| +0xe0 | 3102 all items (AvatarProxy), queued | `CLobbyClient::OnAvatarItemsChanged` | [known] |
| +0xec, +0xf8 | drained from the deques `+0x1fc`, `+0x210`; nothing fills those deques | none found | [known] |
| +0x104 | 1000 EnterWorld (connection) | `CLobbyClient::OnEnterWorld` | [known] |
| +0x110 | never | `CLobbyClient` S 005037a0 | [known] |
| +0x11c | 1005 world tick (connection, &tick, 0) | `CLobbyClient::OnWorldTick` | [inferred] |
| +0x128 | 3601 shop inventory (NPC id, shop id, &name, sell modifier, &stock) | `WorldScreen::OnShopInventoryReceived` | [known] |
| +0x134 | 3611 shop buy result (shop id, result) | none found | [known] |
| +0x140 | 3621 shop sell result (shop id, result) | none found | [known] |
| +0x14c | never | none | [known] |

Fire sites: S 0046f8c0, S 0046fc10, S 00471d10, S 00471c40, S 0046f380, S 0046f510, S 0046fd10,
S 0046f4d0, S 0046f4f0, S 0046fde0, S 0046f9b0, S 0046fab0, S 0046f670, S 0046f620, S 004706b0,
S 00470990, S 00470a10. Subscriptions: S 00503d00, S 004351a0, S 004389d0.

The three "never" lists (`LM+0x34` above, `VSC+0x110`, `VSC+0x14c`) did not fire through a login, a village
entry and exit, a hosted room and a lost lobby connection, with both notify bodies (S 00464300, S 0045f620) and
the subscriber S 005037a0 hooked [live, 2026-10-14].

**`UserCommConnection`**

| List | Fired when (arguments) | Subscribers |
|---|---|---|
| +0x04 | chat login succeeded | `VSC::OnUserCommLoggedIn` (only during a village entry) |
| +0x10 | chat login failed | `VSC::OnUserCommLoginFailed` (only during a village entry) |
| +0x1c | chat logged out | `VSC::OnUserCommLoggedOut` (only during a village leave) |
| +0x3c | channel chat line (sender name, sender id, channel id, text) | `WorldScreen::OnChatChannelMessage`, `CLobbyClient::OnChatMessage` |
| +0x48 | incoming whisper (sender name, sender id, text) | `WorldScreen::OnPrivateChatReceived` |
| +0x54 | own whisper echoed by the server (target name, target id, text) | `WorldScreen::OnPrivateChatSent` |
| +0x60 | channel joined (ChatChannelInfo*) | `VSC::OnChatChannelJoined` |
| +0x6c | channel join failed (info, error) | none |
| +0x78 | channel left (info) | a no-op of the village connection |
| +0x84 | channel leave failed (info, error) | none |

[known] subscriptions S 00470d50, S 004704e0, S 0046ec50, S 004389d0, S 00503940; fire sites
[known] S 00480e30, S 004810a0, S 00480a70, S 00480c50.

**`RefereeServerConnection`**: `+0x04` logged in, `+0x10` login failed (`BaseConnection`); `+0x38`
/ `+0x44` claim chest ok / failed; `+0x50` / `+0x5c` register game ok (game id, game seed) / failed;
`+0x68` / `+0x74` finish game ok / failed; `+0x80` / `+0x8c` referee login success / failed (no
arguments); `+0x98` / `+0xa4` give up ok / failed. Subscribers: the world screen (`+0x04`, `+0x10`,
`+0x50`, `+0x5c`, `+0x80`, `+0x8c`, S 004351a0) and the in-match requester (`+0x98`, `+0xa4`,
S 00600760) [known for the subscriptions; list meanings in `types.md` §1.6].

**`CharacterManager`**

| List | Fired when (arguments) | Subscribers |
|---|---|---|
| +0x08 | character created (AvatarProxy*) | `AvatarScreen::OnCharacterCreated`; `SelectAvatarDialog::OnCharacterCreated` |
| +0x14 | character creation failed (error code, or −1) | `AvatarScreen::OnCharacterCreateFailed` |
| +0x20 | buddy status push (id, entry*) | `FriendIgnoreListDialog` |
| +0x2c | buddy added (id, entry*) | `FriendIgnoreListDialog` |
| +0x38 | buddy removed (id) | `FriendIgnoreListDialog` |
| +0x44 | ignore added (id, &name) | `FriendIgnoreListDialog` |
| +0x50 | ignore removed (id) | `FriendIgnoreListDialog` |

[known] subscriptions S 0043be30, S 0043f9e0, S 00452860; fire sites [known] S 00476a40,
S 00476f90, S 004770b0, S 00477550, S 00478ae0, S 004779a0, S 00476390. There is no list for "character list
arrived", "buddy list arrived" or "ignore list arrived": consumers poll the valid flags and the
changed flag [inferred].

**`ServerList`**: `+0x0c` / `+0x18` / `+0x24` → `SelectVillageServerDialog`; `+0x30` … `+0x60` →
`BrowseGameDialog` (`match-setup-room.md` §3.2) [known] S 00440d70, S 00459970.

**`PostOffice`**: `+0xac` → `MailDialog`; `+0xb8` → `MailboxDialog` [known] S 0045ace0, S 004515f0.

---

## 3. Rules and algorithms

### 3.1 The state machine

`SetState(new)` S 00462540 does nothing when the state is 12; only the village connection calls it.
`LobbyComm::System`'s own handlers write the field directly [known].

| From | To | Trigger | Code |
|---|---|---|---|
| 0 | 1 | `Initialize` succeeded: item database loaded, comm layer created, managers attached | S 004643d0 |
| 1 | 2 | `Login(host, port, user, password, cdKey)` or `CreateUser(…, email)` and the library accepted the request. Both first call `Reset` on `ServerList`, `CharacterManager`, `Properties`, `ServerMessages`, `PostOffice`. In any other state both do nothing | S 004630e0, S 004633f0, S 00462440 |
| 2 | 3 | lobby login callback: store the account id in `LM+0x548` | S 00463a10 |
| 2 | 1 | lobby login failed: `LM+0x548 = 0`; fire `LM+0x1c` with the error code | S 00464a20 |
| 3 | 4 | pump: queue `Properties::RequestProperty(1, 1)` | S 00464ee0 |
| 4 | 5 | property answer accepted (§3.2) | S 00464e70 |
| 5 | 6 | pump: start the global data load (§3.3) | S 00464ee0 |
| 6 | 7 | pump: all four load flags set; fire `LM+0x10` with the account id | S 00464ee0 |
| 7 or 11 | 8 | chat login succeeded during a village entry (§3.4) | S 004704e0 |
| 8 | 9 | message 1000 EnterWorld | S 0046f670 |
| 9 | 10 | leave request built (§3.7); the state changes before the message is sent | S 0046bde0 |
| any (in practice 8, 9, 10) | 11 | village logged out, or village connection lost | S 00470e20, S 00470f90 |
| any but 1 | 1 | lobby logged out (§3.8). Written directly, so this also leaves state 12 | S 00464bf0 |
| any | 12 | lobby connection lost; fire `LM+0x04` with the error code | S 004647e0 |
| any | 0 | `Destroy` at shutdown | S 00462f70 |

[known]. Remarks:

- **No state has a timeout.** States 2, 4, 6, 8 and 10 wait for a callback and stay for ever if it
  does not come [inferred: the pump has no timer for them].
- State 7 has no code of its own: it is "logged in, on the avatar screen". State 11 behaves like
  state 7 for a new village entry; nothing moves 11 back to 7 [known: no writer]. The avatar
  screen's "enter village" handler S 0043abc0 and the 8-writer S 004704e0 do not test the state.
- `Initialize` returns early, leaving state 0, when `ItemsClient.txt` cannot be opened; `Login`
  then never acts [known].
- `Login` builds the string `<user>@s2k8` and does not use it [known] S 004630e0.
- `Logout()` S 00463710: false in state 0 or 1; otherwise `ConnectionManager vtbl+0x3c`
  (disconnect all); if the lobby transport was in state 2 it calls its own logged-out handler with
  reason 0. No logout message is sent [known].

### 3.2 Version check (states 3 to 5)

The pump queues one property request, kategory 1, index 1, with `OnVersionChecked` as delegate.
`Properties::ProcessActions` S 0048e880 sends the oldest queued request (message 161) and sets
busy; if the send fails, the delegate gets the error at once and the request is dropped [known].

`PropertyDataReceived` S 0048e920 completes the **oldest** request (strict first in, first out),
erases it and ends busy [known]:

| Answer | Delegate gets |
|---|---|
| error code ≠ 0 | `(kategory, index, error, ok = false)` |
| entry count ≠ 1 | error −1 |
| kategory differs | error −2 |
| index differs | error −3 |
| match | `(kategory, index, value, ok = true)` |

`OnVersionChecked_State4to5` S 00464e70 acts only in state 4 [known]:

1. not ok → disconnect all, fire `LM+0x40` with **0x6f** (111); the state stays 4.
2. client protocol version ≠ 0 and (signed) lower than `value` → disconnect all, fire `LM+0x40`
   with **0x3e** (62); the state stays 4.
3. otherwise state 5.

The client protocol version is the global S 0087aed8: 1000 in the image. The login dialog and the
create-account dialog read `[LobbyClient] ProtocolVersion` of `LobbySettings.ini` (default −1) just
before they call `Login` / `CreateUser` and store the value unless it is −1
(`message-catalog.md`, "Lobby connection", version check) [known] S 00465380, S 0043cbf0,
S 0043e080.

### 3.3 Global data load (states 5 to 7)

On 5 → 6, in this order [known] S 00464ee0:

1. `ServerList::StartObservation` (§3.13).
2. `ServerMessages::RequestMotD` S 004884d0: if attached and not busy, call the MotD manager; on
   success clear `motdReceived` and set busy.
3. Bind the chat transport: `UserCommConnection::Initialize(transport, chatChannelManager)`
   S 0047f160. This does **not** log in to the chat server.
4. `CharacterManager::Initialize(characterInterface, userInterface)` S 00473460: store both and
   register the two listeners. A second call logs `Already initialized.` and changes nothing.
5. If the pending e-mail string is not empty: queue `UpdateEMail`, clear the string.
6. `CharacterManager::RequestCharacterList` S 00472f00 (§3.10).
7. `PostOffice::Initialize(mailManager)` S 0047cd70: register the observer, empty mailbox and
   queue.

In state 6 the pump computes a mask every frame [known]:

| Bit | Flag |
|---|---|
| 1 | `ServerMessages.motdReceived` (set by the MotD answer, success **or** error) |
| 2 | `CharacterManager.characterListValid` |
| 4 | `CharacterManager.buddyListValid` |
| 8 | `CharacterManager.ignoreListValid` |

- mask = 15 → state 7, fire `LM+0x10`.
- mask = 3 and the character manager is not busy → queue `RefreshFriendList`.
- mask = 7 and the character manager is not busy → queue `RefreshIgnoreList`.
- any other mask → wait.

So the order on the wire is: MotD and character list (in parallel), then the buddy list, then the
ignore list. Because the queue is checked only through `IsBusy`, a refresh action is queued again
on every frame in which the manager is idle and the flag is still clear; in practice the action is
sent in the same pump tick and makes the manager busy [inferred]. When the send returns an error
the action is popped and the manager stays idle, so one action is queued and dropped per frame
until a send succeeds; a failed call sends nothing [known] S 00476390. A character list that arrives
with an error leaves bit 2 clear for ever: the client stays in state 6 [inferred] S 00474910.

### 3.4 Entering the village (states 7 or 11 → 8 → 9)

1. The user interface selects a character (`CharacterManager::SelectCharacter(id)` S 00472200: the
   id must be in the character map, else the selection becomes 0) and a village server
   (`ServerList::SelectVillageServer(id)`, §3.13), then calls `CLobby::RequestEnterVillage(reset
   position)` → `CLobbyClient::EnterVillage` S 00503f50 [known].
2. `LobbyComm::System::CreateVillageServerConnection(-1)` S 00463850: only when the village connection
   has no transport; −1 means the selected village server. Registers the server id with the
   ConnectionManager, gets the transport, `InitializeForServer(transport, serverId)` S 0046dac0
   (stores the id at `VSC+0x15c`). Failures are logged only [known].
3. `CLobbyClient` subscribes to the village connection (§2.19) and calls
   `VSC::OpenUserComm(id)` S 00470d50 with the selected character id (`CM+0x98`), or on a re-enter
   with the saved perm id. An id of 0 is replaced by the account id `LM+0x548` [known].
4. `OpenUserComm` subscribes `OnUserCommLoggedIn` / `OnUserCommLoginFailed` to the chat connection
   and calls `UserCommConnection::OpenCommunication(id)` S 0047ff10 → chat transport `Login(id, 0)`
   [known]. (The chat login exchange is `message-catalog.md`, "UC / chat connection".)
5. Chat login succeeded → `OnUserCommLoggedIn(connection, avatarId)` S 004704e0 [known]:
   1. unsubscribe the two login delegates; subscribe `OnChatChannelJoined` to `UCC+0x60` and a
      no-op to `UCC+0x78`;
   2. find `avatarId` with `CharacterManager::FindCharacter` S 004721b0, which needs the character
      list to be **valid** and the id to be in the character map; otherwise log, fire `VSC+0x10`
      with −1 and stop;
   3. `LobbyComm::System::SetLocalAvatar(character)` S 004626c0: delete the previous local avatar, make
      a **copy** of the character's `AvatarProxy` (0xe0), clear its 3D object pointer, insert it in
      the avatar map;
   4. village transport `Login(avatarId, 0)`; a non-zero result is logged and fires `VSC+0x10`;
   5. `SetState(8)`; `LM+0x54c = avatarId`. Steps 5.4 and 5.5 run even when the login call failed.
6. Chat login failed → `OnUserCommLoginFailed` S 00470660: unsubscribe both, fire `VSC+0x10` with
   −1 [known].
7. Village login callback → `LobbyComm::System::OnLoggedIn` (village branch): fire `VSC+0x04`; store the
   selected village server id in `LM+0x550`; clear the keep-list flag `SL+0xa0` [known] S 00463a10.
8. The server pushes **1000 EnterWorld** → `HandleEnterWorld` S 0046f670 [known]:
   1. `SetState(9)`;
   2. read world name, `ServerPerm`, the list of (zone key, chat channel id); the zone map is
      cleared first;
   3. `UserCommConnection::JoinChannel(map[0xFF])`: join the village-wide channel;
   4. `PostOffice::RequestMailHeaders()`;
   5. seed the C random generator with the current millisecond timer; link quality = 3; send the
      first ping with the code `rand() << 16 | rand()` (§3.6);
   6. store `ServerPerm`; fire `VSC+0x104`.
9. `CLobbyClient::OnEnterWorld` S 00503940 spawns the local avatar: default spawn (−31.24, 2.71,
   −8.28), heading 0, zone 0, ghost zone 0x0F; replaced by position, heading, zone and ghost zone
   of the selected character (from its data blob) when one is selected; position and zone put back
   to the default when "use default spawn" is set (the flag is then cleared); all of it replaced by
   the position saved at the last leave if one exists (used once). `EnterVillage` clears that saved
   position on every entry that is not a re-enter, so it only applies to a village switch (§3.17).
   Outside a re-enter it requests lobby screen 3 (the world screen). It subscribes `OnChatMessage`
   to `UCC+0x3c` and clears the re-enter state [known] S 00503940, S 00503f50.

### 3.5 While in the village (state 9)

Per pump tick, in this order [known] S 00464ee0, S 00471110:

1. `PostOffice::ProcessActions` (§3.11).
2. `UserCommConnection::Process` (§3.12, the whisper queue).
3. `VSC::TickInWorld`: `DrainEventQueues` then `PingPongTimerTick`.
4. `Properties` and `CharacterManager` pumps (these run in every state above 2).
5. Referee upkeep (§3.9; runs in every state above 5).

Mail requests and whispers are therefore sent **only in state 9** [known].

### 3.6 Event queues and keep-alive

**Deferred events.** Six handlers only append a proxy pointer to a deque; `DrainEventQueues`
S 0046fde0 delivers each deque to its observer list and empties it, in this fixed order [known]:

| Order | Deque | Filled by | Observer list |
|---|---|---|---|
| 1 | +0x184 | 1002 avatar logged in | +0xa4 |
| 2 | +0x1ac | 1001 avatar data | +0xbc |
| 3 | +0x198 | 1003 avatar removed | +0xb0 |
| 4 | +0x1c0 | 3100 active items | +0xc8 |
| 5 | +0x1d4 | 3101 inventory | +0xd4 |
| 6 | +0x1e8 | 3102 all items | +0xe0 |
| 7 | +0x1fc | nothing | +0xec |
| 8 | +0x210 | nothing | +0xf8 |

`TickInWorld` does nothing unless the state is 9, so events that arrive in state 8 wait for
EnterWorld. The 1001 handler calls `TickInWorld` itself after queueing, so in state 9 an avatar is
delivered within the message handler [known] S 0046e1d0. Everything else (NPC records, minigame
tables, shop, world tick) is delivered at once; 216 and 217 are dropped outside state 9 [known]
S 0046f510, S 0046f380.

**Ping.** [known] S 0046c150, S 0046c250, S 0046c360.

- `SendPing(code)`: send 3798 `{PingCode = code}`. Sent: pending code = `code`, send time = now,
  pong time = −1, countdown = **30 s**. Not sent: pending = none, both times −1, countdown =
  **15 s**.
- `HandlePongCode` (3799): if the code equals the pending code: countdown **+= 90 s**; pong time =
  now; `h = (now − send time) / 2`; link quality = 3 if `h ≤ 0.1 s`, 2 if `h ≤ 0.25 s`, 1 if
  `h ≤ 2.0 s`, else 0; pending = none. A non-matching code changes nothing.
- `PingPongTimerTick` (every frame in state 9): countdown −= frame time; when it is ≤ 0: send a new
  ping with a random code; if the send time or the pong time of the previous ping was not positive
  (no pong arrived), link quality = 0.

With a server that answers, a ping goes out about every 120 s (30 + 90); without an answer every
30 s with quality 0 [inferred]. A missing pong never disconnects.

### 3.7 Leaving the village (9 → 10 → 11)

1. `CLobby::RequestExitVillage` S 004f5090: when the lobby's current mode is 2 it requests mode 0
   and does nothing else ([TODO] not established: what mode 2 is; `CLobby::ProcessModeTransition`
   S 004f5950 enters it without any lobby state check); otherwise → `CLobbyClient::LeaveVillage`
   S 00503470: if the 3D lobby returns a local avatar (`CLobby vtbl+0x90`), save its position, zone,
   ghost zone and heading (§2.18), else clear "a saved position exists"; then
   `VSC::SendLeaveVillageRequest`. Callers: the "leave village" confirmation box, the pre-game room
   at match start, a village switch [known] S 00431ce0, S 00457a00, S 00503560.
2. `SendLeaveVillageRequest` S 0046bde0: only when the village transport is in state 8; build 2002
   `{code = 0xAFFEDEAD}`, `SetState(10)`, send [known].
3. Server answers **1006** `{code}` → `HandleWorldLoginAck` S 0046ec50. Only `code == 0xDEADBEEF`
   acts [known]:
   - set `VSC+0x224`;
   - chat connection logged in → subscribe `OnUserCommLoggedOut` to `UCC+0x1c`, then
     `UserCommConnection::Logout()` (chat transport `Logout()`);
   - chat connection not logged in → unsubscribe from `UCC+0x60` / `+0x78`, village transport
     `Logout()`.
4. Chat logged out → `OnUserCommLoggedOut` S 0046db30: unsubscribe the three chat delegates,
   village transport `Logout()` [known].
5. Village logged out → `LobbyComm::System::OnLoggedOut` (village branch) S 00464bf0 [known]:
   1. `VSC::HandleLoggedOut` S 00470e20: delete all minigame tables (firing `+0x74`), delete the
      local avatar, delete all NPCs (firing `+0x44`), delete all avatars (firing `+0xb0`) and empty
      the eight deques, clear the zone map and the world name, current zone = 0x0F, `ServerPerm` =
      0, `SetState(11)`, fire `VSC+0x1c`;
   2. `VSC::Destroy` S 0046da60: world name, zone map and `ServerPerm` cleared again, village
      server id = −1, release the transport;
   3. `CharacterManager::Reset`, then `RequestCharacterList`, `RefreshFriendList`,
      `RefreshIgnoreList`;
   4. `ServerList::Reset` and `StartObservation` (both skipped while the keep-list flag is set);
   5. `ServerMessages::Reset` and `RequestMotD`;
   6. `PostOffice::Reset`.

So every village leave **reloads the account data** (characters, buddies, ignore list, server list,
MotD) and empties the mailbox, while the state stays 11.

The server side of this exchange, including why 1006 is sent twice, is
`village-and-character-protocol.md` §7.

### 3.8 Connection events, per connection

`OnLoggedIn(connection, id)` S 00463a10 [known]:

| Connection | Effect |
|---|---|
| lobby | `LM+0x548 = id`; state 3 |
| village | `VSC::HandleLoggedIn` (fires `+0x04`); `LM+0x550` = selected village id; `SL+0xa0 = 0` |
| chat | `UCC::OnLoggedIn` (fires `+0x04`) |
| game server | `GameServerConnection::OnLoggedIn` |
| referee | `BaseConnection::OnLoggedIn` (fires `+0x04`) |

`OnLoginFailed(connection, error)` S 00464a20 [known]:

| Connection | Effect |
|---|---|
| lobby | `LM+0x548 = 0`; state 1; fire `LM+0x1c` |
| village | `VSC::HandleLoginFailed` S 0046dcf0: chat `Logout()` if logged in, fire `VSC+0x10`; then `VSC::Destroy` |
| chat, game server, referee | the connection's handler (fires its `+0x10`) |

`OnLoggedOut(connection, reason)` S 00464bf0 [known]:

| Connection | Effect |
|---|---|
| lobby, state 1 | nothing |
| lobby, state below 7 other than 1 | fire `LM+0x1c` with **0x5479** (21625) |
| lobby, state ≥ 7 | fire `LM+0x28` with the reason |
| lobby, both cases | `CharacterManager::ResetOnLogout` (release both tincat3 interfaces, delete the characters, end busy), `UCC::Destroy`, referee `Destroy`, `PostOffice::Destroy`; state 1 |
| village | §3.7 step 5 |
| chat | fire `UCC+0x1c` |
| game server | its handler |
| referee | fire its `+0x1c`, then `Destroy` (the pump binds it again, §3.9) |

`OnConnectionLost(connection, -, error)` S 004647e0 [known]:

| Connection | Effect |
|---|---|
| lobby | log `LobbyConnection lost!!!`; state 12; fire `LM+0x04` |
| village | `VSC::HandleDisconnected` S 00470f90: the same teardown as a logout, plus chat `Logout()`; `SetState(11)`; fire `VSC+0x28`. Then `VSC::Destroy`. The account data is **not** reloaded on this path |
| chat | fire `UCC+0x28`; `UCC::Destroy`; bind a new chat transport at once (same calls as on 5 → 6). No login is started |
| game server, referee | fire the connection's `+0x28` |

`ResetOnLogout` leaves the buddy map, the ignore map and both name caches in place; `Login` clears
the buddy and ignore maps through `Reset` before the next session, the name caches are never
cleared [known] S 00472b30, S 00476020.

After a lobby logout the character manager's interfaces are 0, and `CharacterManager::Initialize`
runs again on the next 5 → 6 [inferred].

### 3.9 Referee upkeep (every pump tick in a state above 5)

[known] S 00464ee0, S 004625d0, S 00462910, S 00468f60, S 00469ad0:

1. If "assign requested" is clear: set it, call `ServerList::RequestRefereeServer(manager,
   SetRefereeServerAddress)`, timer = 0. The request sends 189 AssignServer (type 4, subtype 4)
   only when no callback is pending in the server list; on success it stores the callback.
2. If the timer is negative: clear "assign requested", timer = 0 (so step 1 runs on the next
   tick). If it is positive: subtract the frame time in milliseconds.
3. If the referee connection is not logged in: `InitRefereeServerConnection`: when it has no
   transport and a referee id is latched, register that id with the ConnectionManager (result 0 or
   0xCD accepted), get the transport, `Initialize`.

The assign answer calls `SetRefereeServerAddress(serverId)`: if an id was latched and the new one
differs, `Destroy` the referee connection; latch the id; timer = **60000 ms**. A failed assign
calls the callback with 0: that unlatches the id (and releases a bound referee transport) and also
arms the 60 s timer. Consequences:

- with an answer the client asks again every 60 s, for the whole session, in the village and in a
  match;
- **without any answer the request is never repeated**: the timer stays 0, which is neither
  negative nor positive. A countdown that lands exactly on 0 stops the repetition in the same way
  [known];
- the referee *login* is not part of this: it is started by the world screen at match start
  (`RefereeServerConnection::Login(localPermId)` S 004793f0: transport `Login(id, 0)` when the id
  is non-zero and a transport is bound) [known], with a delay of 16 frames, then
  `16 + 8 × tries` frames after each failure, and an abort after more than 4 tries
  (`MATCH_START.md`, phase 3) [inferred] S 00435980, S 004317a0.

Referee messages are dispatched by id in `OnReceive` S 0047b090: 3501 / 3502 claim chest
acknowledge / result, 3511 / 3512 register game acknowledge / result, 3521 / 3522 finish game
acknowledge / result, 3530 login success, 3531 login failed, 3541 give up acknowledge; any other id
is discarded. Login success and login failed fire their list only when the message's `PermID`
equals `LM+0x54c` [known] S 0047ac20, S 0047ad50.

### 3.10 Character manager: the action queue

**Character list** is not a queued action. `RequestCharacterList` S 00472f00: needs both
interfaces and not busy; delete all characters, clear the changed flag, selection = 0, send 55 with
the account id; on success `characterListValid = false`, set busy [known].

`CharListReceived(userId, count, records, error)` S 00474910 [known]:

- `userId` ≠ account id → ignored (the manager stays busy);
- error → log, end busy; the list stays invalid;
- no error, count 0 → end busy, valid = true;
- no error, count > 0 → for each record: new `AvatarProxy(id, name)`, `ApplyCharacterDataBlocks`,
  insert into the map by id (the first of two equal ids wins); a record whose blocks do not parse
  is dropped; then valid = true, end busy, set changed.

`Reset` S 00476020 does not touch the valid flag of the character list: it deletes the characters,
sets the selection to 0, empties the action queue, clears the buddy and ignore maps with their
valid flags, ends busy and clears changed. The flag is cleared only by an accepted
`RequestCharacterList`; `ResetOnLogout` S 00472b30 leaves it, the selection and the action queue as
they are [known].

**Queued actions.** The public methods only append to the deque and return true (exceptions
below). `ProcessActions` S 00476390 runs while the manager is not busy and the queue is not empty
[known]:

1. Take the head action (it stays in the queue) and log its type name.
2. Issue the tincat3 call of its type.
3. Result 0 → set busy and stop; the result callback pops the action later.
4. Result ≠ 0 → pop the action and continue with the next. `CreateCharacter` also fires `CM+0x14`
   with the error; the look-ups call their delegate with the error.

Look-ups are answered locally when the cache has the entry: `LookUpName` copies the cached name,
`LookUpID` the cached id; the delegate is called with result 0, the action is popped, the manager
does not become busy [known].

Result callbacks all follow one pattern [inferred] S 00473590, S 00473a50, S 00473e90, S 00476a40,
S 004770b0, S 00477550, S 00478160, S 00478660, S 00478ae0, S 004779a0:

- queue empty → log `No action to process!`, nothing else;
- head action is of another type → log only; the action is **not** popped and the manager stays
  busy: one stray result blocks the queue until the expected one arrives;
- head matches → apply the result (table), pop, end busy.

| Type | On success | On error |
|---|---|---|
| CreateCharacter | new `AvatarProxy(new id, queued name)` built from the **client's own** queued creation block (the server does not echo the data); insert; fire `CM+0x08`; set changed | fire `CM+0x14` with the error (or −1 if the block does not parse); set changed |
| DeleteCharacter | erase the id from the map; set changed | character kept; set changed; no notification |
| RefreshFriendList | for each record: `buddies[id]` = record, cache id ↔ name; `buddyListValid = true`. The map is **not** cleared first | pop only; flag stays clear |
| AddToFriendList | `buddies[target]` = `{target, queued name, server −1}`; fire `CM+0x2c` | pop only |
| RemoveFromFriendList | erase; fire `CM+0x38` | pop only |
| RefreshIgnoreList | `ignored[id] = name` for each record; `ignoreListValid = true`. Not cleared first; names are not cached | pop only |
| AddToIgnoreList | `ignored[target]` = queued name; fire `CM+0x44` | pop only |
| RemoveFromIgnoreList | erase; fire `CM+0x50` | pop only |
| LookUpName | name = first record's name, or empty when there is none; call the delegate | delegate gets the error and an empty name |
| LookUpID | id = first record's id, or 0; call the delegate | delegate gets the error and id 0 |
| UpdateEMail | nothing | nothing (logged) |

Rules of the entry points [known]:

- `CreateCharacter(name, block, size)` S 004750f0: name converted to UTF-8; the block is copied.
- `AddToFriendList(id)` / `RemoveFromFriendList(id)`: refused (false) while the buddy list is not
  valid. `AddToIgnoreList` / `RemoveFromIgnoreList`: refused while the ignore list is not valid.
- `AddToFriendList` and `AddToIgnoreList` take the name from the name cache; when it is not cached
  they first queue a `LookUpName` with a no-op delegate, and the add action carries an empty name.
- `LookUpID(name, delegate, context)` lower-cases the name.
- `UpdateEMail(address)` carries the account id and the address; the request is
  `ChangeUser(account, 0, 0, address, 0, 1, 0, 0, mask 8)`.

**Buddy status push** (message 61 without a ticket) → `BuddyUpdateReceived` S 00476f90: create
`buddies[id]` if absent, assign from the record, fire `CM+0x20` (also when the record was not
applied). A record is applied only when its `perm_id_type` is 2: id and name are copied; with
`status == 3` the server id and server name are copied when the server id is above 1 and left as
they were otherwise; with any other status they become −1 and empty [known] S 00476f90,
S 0046b540.

`GetUserRelation(id)` S 00472a00: **1** if the id is in the buddy map, else **2** if in the ignore
map, else **0** [known]. Users: chat line colour (buddy), dropping whispers and mails of ignored
users.

**Name caches.** `CacheUserName(id, name)` S 004780c0 writes both caches (the id cache under the
lower-cased name). Sources: every 1001 avatar record, every chat line's sender, every whisper's
sender, every buddy list record [known call sites S 0046e1d0, S 00480e30, S 004810a0, S 00478160].
Look-up results are **not** written to the caches by the manager [known] S 00473590.

### 3.11 Mail

Entry points (all only append a request) [inferred] S 0047d140, S 0047d200, S 0047d390, S 0047d4a0,
S 0047dfc0:

| Call | Rule |
|---|---|
| `RequestMailHeaders()` | queue opcode 1; poll time = −1 |
| `RequestMail(id)` | false for id 0 or a mail pending deletion; true without queueing when the mail already has content; else queue opcode 2 |
| `MarkRead(id)` | false for id 0, unknown id, pending deletion; true without action when already read; else set the local read flag and queue opcode 3 |
| `DeleteMail(id)` | false for id 0 or unknown; true without action when already pending; else set delete pending, queue opcode 4 and fire `PO+0xb8` at once |
| `SendMail(recipient, subject, body, delegate)` | false when any string is empty or the delegate is null; queue opcode 5 with send state 2 when the id cache has the recipient, else send state 1 |

`Process` S 0047d880, once per pump tick in state 9 [known for the constants; branches inferred]:

1. If poll time ≠ −1 and `now − poll time ≥ 60 s`: `RequestMailHeaders()`.
2. While not busy and the queue is not empty, by opcode of the head:
   - 0: pop.
   - 1 (147), 3 (148), 4 (151): send. Sent → set busy, stop. Not sent → log, pop, continue.
   - 2: ask tincat3 for the message (`MailManager::GetMessage` T 10028a30). It searches its cached
     list and answers inside the call through `MailReceived`, with the record and error 0 or, for
     an id it does not have, with error 0x92; `MailReceived` pops the request. Back in `Process`:
     a non-zero call result → log, pop, continue; result 0 and `PO+0x20` now holds that mail with
     content → stop without setting busy; result 0 otherwise (the message was not cached) → set
     busy, stop: the post office stays busy with nothing in flight [known] S 0047d880, T 10028a30.
   - 5, send state 1: `CharacterManager::LookUpID(recipient, FindByNameCallback)`; accepted → set
     busy, stop. Refused: retry count < **3** → increment and move the request to the back; else
     the delegate gets **−10000** and the request is popped. `LookUpID` S 004752a0 always returns
     true, so the refused branch is never taken [known].
   - 5, send state 2: send 150 `(sender = LM+0x54c, recipient id, subject, body)`. Sent → set busy,
     stop. Not sent → the delegate gets the error, pop.

Callbacks [inferred] S 0047dce0, S 0047e0f0, S 0047c290, S 0047e590, S 0047c5e0, S 0047d5d0:

| Callback | Effect |
|---|---|
| headers (count, records, error) | pop, end busy. No error: per record update the mail with that id or append a new one (new = 1); set changed when count > 0; poll time = now. Error: log; poll time stays −1, so polling stops. Mails missing from the list are **not** removed |
| mail (record, error) | pop, end busy. Known id: update, copy to `PO+0x20`, fire `PO+0xac`, `MarkRead(id)`, set changed. Unknown id: append, set changed, no notification |
| mark read result (id, error) | pop, end busy. No error: the mail with that id gets read = 1 (both flags), set changed; an unknown id is logged. tincat3 always passes id 0 (T 10028f60), so only the log line happens [known] |
| delete result (id, error) | pop, end busy. No error: fire `PO+0xb8`, erase the mail with that id, set changed; an unknown id is logged. tincat3 always passes id 0 (T 10028f90), so the mail is **not** erased here: it stays in the vector with delete pending set [known] |
| send result (-, error) | pop, end busy, call the request's delegate with the error |
| recipient look-up (error, id) | pop, end busy. Success: recipient id = id, send state 2, push the request to the **front**. Error: the delegate gets the error |

Sender names: a mail whose sender is not in the name cache shows `???` and queues a `LookUpName`;
the answer writes the name when the mail still has the same sender and id [inferred] S 0048cce0,
S 0048cea0.

`CollectNewMails(out)` S 0047e930 (called every frame by the mailbox dialog): returns the mails
with new = 1 and delete pending = 0 and clears their new flag; a mail of that kind whose sender
(`Mail+0x0c`, the argument of `GetUserRelation`) is on the ignore list is not returned but deleted
(`DeleteMail`) [known].

`Reset` empties mailbox and queue and stops polling; `Destroy` also detaches from tincat3 but
leaves the poll time [inferred] S 0047ce60, S 0047cdf0.

### 3.12 Chat

**Channel map.** `VSC+0x164` maps a zone key to a chat channel id [known] S 0046f670, S 0046d610,
[inferred] S 0046d170:

| Key | Meaning | Channel kind |
|---|---|---|
| 0xFF | village-wide channel; joined on EnterWorld | 1 |
| below 0x0E | channel of one zone of the village | 2 |
| 0xFE | channel of the minigame table the player sits at; written by `SetMiniGameChatChannel` S 0046e820; `ClearMiniGameChatChannel` S 0046e840 writes the "no channel" constant S 007db53c (= 0) into the entry (the key stays in the map) | 3 |

`GetChatChannelKind(channelId)` returns the kind of the key the channel is stored under, 0 when it
is not in the map or stored only under a key from 0x0E to 0xFD [known] S 0046d170.
`GetChatChannelByKind(kind)` S 0046d5d0 returns `map[0xFF]`, the channel of the current zone
(`VSC+0x225`; none while it is 0x0F), or `map[0xFE]` [known]; the value for a missing entry is
[inferred] 0, the "no channel" constant S 007db53c the callers compare with.

**Zone switch.** `JoinZoneChatChannel(zone)` S 0046e860 (called from the 3D lobby with the local
avatar's zone) [known]: nothing when a join is pending or `zone == 0x0F` or `zone` equals the
current zone. Otherwise: if a zone is current, `LeaveChannel(map[current])` and current = 0x0F;
then `JoinChannel(map[zone])` and pending = true. `OnChatChannelJoined(info)` S 0046d610: find the
key whose channel id equals the joined one; if the key is neither 0xFF nor 0xFE, current = key and
pending = false. A join that never completes leaves pending set: no further zone switch happens
[inferred].

**Requests** S 00480070, S 004801e0, S 0047ede0: `JoinChannel(id)` calls the chat manager with
`LM+0x54c`, the channel id and an empty password (17); `LeaveChannel(id)` with `LM+0x54c` and the
channel id (259); `SendChatMessage(channel, text)` converts to UTF-8 and sends with `LM+0x54c` as
sender (2). All three do nothing without a chat manager; errors are only logged; there is no local
echo [known for the calls; the message numbers are [inferred]].

**Channel vector.** Join result and leave result both insert the channel into `UCC+0x94` when its
id is not there yet (a known entry is left as stored and is the one handed to the observers; a left
channel is **not** removed), then fire the success list (error 0) or the failure list. Channel list
(only without error) and channel created insert or overwrite by id, channel removed erases the
entry; none of the three fires anything. User-joined and user-left notifications are ignored: the
client keeps no member lists [known] S 00480a70, S 00480c50, S 0047f7d0, S 0047f950, S 0047fac0,
S 0047fc30, S 0047fd10, S 004903e0, S 00490da0, S 00490830.

**Incoming line** (`ChatReceived` S 00480e30): convert name and text to ANSI, cache sender id ↔
name, fire `UCC+0x3c` [known]. The world screen then [known] S 00436180; the command words are
[inferred] (the parser's word table was not read):

1. drops the line when the sender is ignored;
2. drops it when the channel's kind is 0;
3. sender id = `ServerPerm` → `[SYSTEM] ` line and a modal box `!LOBBY_IMPORTANT_SYSTEM_MESSAGE`;
4. text is one of the emote commands (`/laugh`, `/dance`, `/applaud`, `/cry`, `/bow`, `/monkey`) →
   the localised emote text;
5. otherwise `[<name>] <!LOBBY_CHAT_FROM> : <text>`, coloured by buddy or not;
6. appends it to the tab whose id is the channel kind, tagged with the sender id (0 for a system
   line).

The 3D lobby shows the same line as a speech bubble over the sender's avatar when the village
connection is logged in, the channel is the village-wide or the current zone channel and the sender
is an avatar with a 3D object [known] S 00503200.

**Outgoing line** (`WorldScreen::SendChatInput` S 00436860) [known for the branches; the command
words are [inferred]]: empty after trimming → nothing. Server command (`/ac <text>`) → village
message 4000, only with exactly one non-empty argument. Whisper (`/w`, `/whisper`, `/tell <name>
<text>`) → `QueuePrivateMessage`, only with exactly two non-empty arguments. Help (`/help`,
`/hilfe`) → the local text `!LOBBY_CHAT_HELP` on the active tab. Anything else, emotes included, is
sent as typed (the untrimmed input): on tab 4 through the peer-to-peer session, otherwise
`SendChatMessage(GetChatChannelByKind(tab), text)`; a channel id equal to the "no channel" constant
drops the line.

**Whispers.** `QueuePrivateMessage(name, text)` S 004808a0: false without a chat manager; state 2
with the cached id, else state 0 [known]. `Process` S 00480630 looks at the head only [known]:

| Head state | Action |
|---|---|
| 0 | `CharacterManager::LookUpID(name, OnWhisperTargetLookedUp)`; accepted (it always is) → state 1 |
| 1 | wait |
| 2 | `SendPrivateMessage(id, text)` (message 30); sent → pop; not sent → retry on the next tick, without limit |

`OnWhisperTargetLookedUp(error, id)` S 00480340: no error and id ≠ 0 → store the id, state 2;
error → drop the head; no error and id 0 → nothing (the head stays in state 1: the queue stalls)
[known].

`PrivateChatReceived(from, to, text)` S 004810a0 [known]: dropped when `from` is ignored. `from`
is the local perm id (the server's echo of an own whisper): fire `UCC+0x54` when the target's name
is in the name cache, else nothing. Otherwise cache `from` id ↔ name and fire `UCC+0x48`; the world
screen remembers the sender as reply target.

### 3.13 Server list

`StartObservation` S 00468e80: with a manager, not busy and the keep-list flag clear, send 171
RegObserverServerList twice, for server type 4 and server type 5. `Reset` S 00468c50 (skipped
entirely while the keep-list flag is set): end busy, clear changed, selected village = −1, delete
all village and game entries; in a state above 2 also call the manager's deregistration (172)
[known for the calls; the message numbers are [inferred]].

Every pushed descriptor (message 170) goes to `AddOrUpdateDescriptor` S 0046a440 [known]. `opCode`
is the 170 field `running` (descriptor `+0x4c`):

| Subtype | Known id | opCode | Effect |
|---|---|---|---|
| 2 (village) | yes | 0 | `RemoveServer(id)` S 0046a5e0: set changed, fire `SL+0x24`; selected village = −1 if it was this one; erase. The same call also removes a hosted game with that id (fire `SL+0x48`, selected game = −1 if it was this one) |
| 2 | yes | ≠ 0 | update the entry; set changed; fire `SL+0x18` |
| 2 | no | 1 | new `VillageServerInfo`; set changed; fire `SL+0x0c` |
| 2 | no | other | ignored |
| 1 (hosted game) | yes | any | update; set changed; fire `SL+0x3c`. A remove is **not** honoured on this path |
| 1 | no | any | new `GameServerInfo`; set changed; fire `SL+0x30` |
| other | | | ignored |

The bulk answer path `GameServerDataReceived` S 00469700 passes the same pointer, `records +
count × 0x5c` (one past the end of the record array), to the sink for every record, so it never
reads the real records [known, as decompiled]; only the pushed descriptors work [inferred].

`SelectVillageServer(id)` S 00468380: true and `SL+0x80 = id` when the id is in the village
vector, else false [known].

**Choice of a village server**: `FindBestVillageServer(protocol, preferredId)` S 00469010 [known].
`load = cur × 100 / max` (integer; `max = 0` counts as load 0). An entry is *eligible* when its
protocol key equals `protocol` and its valid byte is set.

1. Pass 1, in list order: the preferred entry, if eligible and (`max = 0` or load < **85**), is
   returned at once. Otherwise remember the eligible entry with `max ≠ 0`, load < **70** and the
   **highest** load above the best so far (start 0, strict).
2. If pass 1 remembered one, return it.
3. Pass 2: among eligible entries with (`max = 0` or load < **90**): the preferred one is returned
   at once; otherwise remember the one with the **lowest** load below the best so far (start 100,
   strict).
4. Return the remembered id, or −1.

So the client fills servers up to 70 % before it opens the next one, and spreads evenly above
that. Callers: the "enter village" button (preferred −1) and the return from a match (preferred
`LM+0x550`) [known] S 0043abc0, S 004f5950. `HasJoinableServerForProtocol(protocol)` S 00468560
(enables that button): any eligible entry with `max = 0` or a load below 90 % [known].

Hosting (`CreateGameServer`, `UpdateGameServer`, `DestroyGameServer`) is `match-setup-room.md`
§3.3.

### 3.14 `LobbyMessage`: building and parsing

**Type word** (16 bits, the `msg_type` of the NETMSG 74 envelope) [known] S 0048eec0, S 0048fa50:

```
bit 15      names flag
bits 12-14  category        (send side: (category & 0xF) << 12, so a category >= 8 would set bit 15)
bits 0-11   message id
```

Categories the client builds: **2** village requests, **3** referee requests, **5** minigame table
requests [known, all 27 constructor calls]. The receive side dispatches on the id only; the
category is stored and never tested [known] S 00470a90, S 0047b090. Unknown ids are dropped without
a log.

**Bit stream** [known] S 0048ef70, S 0048f0d0:

- Bits are packed **most significant bit first**, with no alignment between fields: the *n*-th bit
  of the stream is bit `7 − (n mod 8)` of byte `n div 8`.
- `WriteBits(value, count)` writes the low `count` bits of `value`, highest of them first. So
  multi-byte integers appear big-endian when the stream happens to be byte-aligned.
- `ReadBits(count)` is the mirror. **There is no end-of-buffer check**: a short message is read
  past its end and never reports an error.
- A message built for sending is written into a zero-filled buffer of the `reservedSize` given to
  the constructor; writes are not bounds-checked either. The length sent is the number of bytes
  completed [known] S 0048dfa0.

**Typed accessors** (virtual; every one returns true unconditionally, so the "could not read"
branches of the callers are dead) [known]:

| vtbl | Accessor | Wire |
|---|---|---|
| +0x04 / +0x08 | `WriteByte` / `ReadByte(value, bits)` | `bits` bits |
| +0x0c / +0x10 | `WriteShort` / `ReadShort(value, bits)` | `bits` bits |
| +0x14 / +0x18 | `WriteInt` / `ReadInt(value, bits)` | `bits` bits |
| +0x1c / +0x20 | `WriteInt64` / `ReadInt64(value, bits)` | `bits` bits. In the reader the bit mask is `1 << (n & 31)` (a 32-bit `SHL EAX,CL`) and the high word receives its sign extension (`CDQ`), so the upper 32 stream bits alias onto the low word and a set bit 31 turns the high word into 0xFFFFFFFF: a 64-bit field reads back unchanged only when its upper 33 bits are 0 [known] S 0048f050 (instructions at S 0048f0aa to S 0048f0b6) |
| +0x24 / +0x28 | `WriteBool` / `ReadBool` | 1 bit |
| +0x2c | `WriteString(ansi)` | convert ANSI → UTF-8; 8-bit byte length; the bytes. A string over 255 bytes writes a truncated length and all bytes |
| +0x30 | `ReadString(out)` | 8-bit length; the bytes; convert UTF-8 → ANSI |
| +0x34 | `ReadStringRaw(out)` | 8-bit length; the bytes, stored unconverted |
| +0x38 | `WriteBuffer(data, len, tag)` | `len` bytes of 8 bits; **no length on the wire** |
| +0x3c / +0x40 | `WriteRaw32LE` / `ReadRaw32LE` | 32 bits whose byte order is reversed against the rest: the value's little-endian memory bytes in stream order. Used for 32-bit floats (the shop's `SellMod`) |

Non-virtual helpers [known]:

- `ReadNamedBits(bits, name)` / `WriteNamedBits(value, bits, name)` S 0048f5f0, S 0048f570: plain
  `bits`-bit fields.
- **Packed unsigned** S 0048fb90, S 0048fcb0: one presence bit; 0 means the value 0. If 1: a 3-bit
  field `n − 1`, then the value in `4 × n` bits (`n` = the number of 4-bit groups needed, 1 to 8).
- **Location block** S 0048f670, S 0048f7e0: `posx`, `posy`, `posz` 11 bits each, `rot` 7 bits,
  `zone` 4 bits. Read: `value = q × (max − min) / 2048 + min`, `rotation° = q × 360 / 128`. Write:
  `q = trunc((value − min) / (max − min) × 2048)`, `q = trunc(rotation° / 360 × 128)` (the FPU is
  switched to round-toward-zero around each conversion); the value is cut to the field width, so
  the maximum wraps to 0. The bounds are the six floats at S 0087b700
  (min x, y, z) and S 0087b70c (max x, y, z): x and z in [−150, 150], y in [−10, 30]
  (`village-and-character-protocol.md` §4.2).
- Ghost zone: 4 bits (`ghstzne`). Move flags: `rnng` 1 bit, `jmp` 1 bit.
- `ActorID`: `acttype` 2 bits, `id` packed unsigned S 00490e40.
- Item slot: `sltt` 8 bits, `cnt` 8 bits, `itmid` 32 bits S 0048ab40.

**Field names.** Every accessor call in the client is preceded by `SelectField(name, 0)` or uses a
named helper. Names are never on the wire. They matter only in names mode [known] S 0048f490:

- names mode off (every message the client builds, and every received message whose type word has
  bit 15 clear): `SelectField` does nothing; `Finalize` only pads the last byte with zero bits;
  `FinishRead` consumes nothing.
- names mode on: the message keeps a running CRC-32, started at the CRC of nothing. Each
  `SelectField` mixes in the CRC-32 of the name (as a little-endian 32-bit value); each accessor
  mixes in a type tag and a width, both as 32-bit values: **1** then the bit count for byte, short,
  int, 64-bit int, bool (count 1) and named bits; **2** then the caller's width argument for raw
  32-bit; **3** alone for a string; **4** then the value width in bits (0 for the value 0) for a
  packed unsigned; **1** alone for a buffer written with its tag argument set (a string's bytes
  are written with it clear). The named helpers mix in the CRC-32 of their name themselves, before
  the tag. Field **values** never enter the checksum.
- `Finalize` S 0048f4c0 (once): in names mode mix in 0xFFF and the bit cursor, then append the
  32-bit checksum; then pad to a byte boundary.
- `FinishRead` S 0048f530 (once): in names mode mix in 0xFFF and the bit cursor and **read 32 bits
  that are thrown away**. The checksum is never compared.
- `Discard` S 0048ef00 marks a message finished without reading the rest.

For a server this means: send bit 15 clear and no trailer; or bit 15 set and any 32 trailing bits.

### 3.15 Actor proxies

**Avatars** (map `LM+0x558`, key = avatar id) [known] S 0046e390, S 0046e1d0, S 0046e570,
S 0046e660, S 0046e6f0, S 0046e780, S 0046c940, S 0046c9c0, S 00471d10, S 0046f9b0, S 0046fab0:

| Event | Effect |
|---|---|
| village login of the local player | a copy of the selected character is inserted (§3.4) [known] |
| 1002 | new empty `AvatarProxy(id)`; an id already in the map is an error (`Avatar already logged in.`) |
| 1001 | get or create the proxy; read the blocks named by the 4-bit mask `dtblcks` in the order Location (1), Style (2), ActiveItems (4), Stats (8) [known] S 00482c20; cache id ↔ name |
| 1003 | the proxy is queued for `+0xb0` but **stays in the map**; a later 1001 for the id reuses it. An id that is not in the map is logged and nothing is queued |
| 3100 / 3101 / 3102 | re-read equipment / backpack / both of the avatar named by `ownr`; an unknown `ownr` discards the message |
| 3200 / 3201 | overwrite level and experience / level, experience, gold and play money; unknown `ownr` discarded; no notification |
| minigame seat with an actor that is not a known avatar | a placeholder `AvatarProxy` with a random look (`tribe = rand % 3`, `gender = rand & 1`, four colours `rand & 7`) is inserted and announced; the seat is named `npc %d` |
| world exit (§3.7) | every proxy is announced as removed and deleted; the map is emptied |

Location block rule [known] S 004824b0: the 16-bit `tick` is always stored (widened into the
64-bit last tick). If the proxy's id equals `LM+0x54c` (the player's own avatar) the position,
rotation, zone, ghost zone and move flags are **read and thrown away**: the server cannot move the
local avatar with 1001. For every other avatar they are stored, heading = `rotation° × π / 180`,
and the orientation quaternion is rebuilt.

Style block [known] S 004825f0: name (raw string; ANSI copy made), then nine 8-bit values: tribe
and gender, hair, skin, shirt, trouser, additional colours 1 to 4.

Equipment block [known] S 0048abe0: exactly four item slots. Backpack block [known] S 0048ac20: an
8-bit `sltcnt` that is read and **ignored**, then exactly as many item slots as the container
currently has (`+0x34`), which is 0 for a proxy created by 1001 / 1002 and max(20, stored count)
for a proxy built from character data.

**Character data** (`ApplyCharacterDataBlocks` S 00481e60) [known]: a character counts as
*freshly created* when part 0 is present, its size is not that of an appearance block (12 bytes
[inferred], `village-and-character-protocol.md` §1.4), and parts 1 to 5 are empty; it then gets
the look of the creation block, an empty equipment and a backpack of 20 empty slots, level 1,
experience 0, gold 50, play money 50, position (−31.24, 2.71, −8.28), heading 0, zone 0, ghost
zone 0x0F. Otherwise parts 0 to 4 are parsed (appearance, style, active items, inventory, stats).
The stats block starts from level 1, experience 0, gold 1000, play money 1000, position (−31.24,
2.71, +8.28), heading 0, zone 0, ghost zone 0x0F (S 00486c80) and what the avatar takes depends on
the block's variant: play money is 1000 for variant 0; position, heading, zone and ghost zone are
those defaults for a variant below 2. The four additional colours are 0 when the block they come
from has variant 0. `tribeGender = tribe << 4 | gender & 0xF`; colour values are cut to 4 bits.
The backpack gets max(20, count) slots [known] S 0048af70.

**NPCs** (map `LM+0x564`): 1004 gets or creates the `NPCProxy`, re-reads it in place and fires
`+0x38` at once, also outside state 9 [known] S 0046f8c0. NPCs are removed only at world exit
(`village-and-character-protocol.md` §5.1) [known: `ClearNPCs` S 0046fc10 is the only remover].

**Local avatar** (`LM+0x554`): a separate object from the character in the character map. Stats
and item updates in the village change the local avatar (through the avatar map), not the
character-list entry; the character list is brought up to date by the reload at the next village
leave (§3.7) [inferred].

### 3.16 Items and inventory on the client

- Item ids index the item database; an id that is not in it shows as an empty slot [inferred].
- Containers S 0044d390, S 0046bec0: **0** = backpack; **2**, **3**, **4**, **5** = the four
  equipment slots (head, right hand, left hand, pet, as assigned by the shipped item file; see
  `village-and-character-protocol.md` §4.3) [inferred]. An item fits an equipment container when it
  is valid (§2.14) and its slot mask has bit 0, 1, 2 or 3 set for container 2, 3, 4 or 5; the item
  is not looked at for container 0 [known] S 0044d390.
- The client **never changes an inventory locally**. Move (3001 `{srcslt, srcidx, dstslt, dstidx,
  mvcnt}`, index 0xFF = "server chooses"), delete (3002), buy (3610) and sell (3620) are requests;
  the visible change comes only with 3100 / 3101 / 3102 from the server [inferred].
  `Village_TrySendMoveItem` S 0048acc0 sends only in state 9 [known].
- Sell price shown for an item S 0046d6d0: the third value of the open shop's stock entry for that
  item id (`Sell`); without such an entry and for a valid item `trunc(baseValue × SellMod)`, 0
  when the product is below 1. For an item that is neither in the stock nor valid the code
  dereferences the end of the stock vector behind a failing checked-iterator test
  (`_invalid_parameter_noinfo`): a caller must not ask for such an item [known].
- The player's gold (`localAvatar+0xd0`) and play money (`+0xd4`) are read by the dialogs every
  frame; they gate the tailor, the minigame stake and the match wager [inferred].

### 3.17 What is kept across village leave, match and return

| Data | Village leave (logout) | Village connection loss | Match | Lobby logout |
|---|---|---|---|---|
| State | 11 | 11 | 11 (the village is left at match start) | 1 |
| Account id `LM+0x548` | kept | kept | kept | kept until the next login |
| Local perm id `LM+0x54c` | kept | kept | kept (the referee and the return use it) | kept |
| Last village server `LM+0x550` | kept | kept | kept | kept |
| Local avatar, avatar map, NPC map, minigame tables | deleted | deleted | – | – |
| Zone map, world name, `ServerPerm` | cleared | cleared | – | – |
| Characters, selection | deleted, selection 0, list requested again | kept | – | characters deleted; selection, list-valid flag and action queue kept until the next login |
| Buddy and ignore maps | cleared, requested again | kept | – | kept until the next login |
| Name caches | kept | kept | kept | kept (until the process ends) |
| Village server list, hosted games | cleared and observed again, unless a village switch is running | kept | kept up to date by pushes | cleared at the next login |
| MotD | requested again | kept | – | cleared at the next login |
| Mailbox | emptied; polling stops | kept; not pumped outside state 9 | – | emptied |
| Whisper queue | kept (not pumped outside state 9) | kept | kept | kept |
| Chat channel vector `UCC+0x94` | kept | kept | kept | kept |
| Referee id and 60 s timer | kept; the assign keeps repeating | kept | kept | kept; referee transport released |
| Saved position in `CLobbyClient` | written at the leave; consumed by a re-enter, cleared by any other `EnterVillage` | not written | cleared by the entry that follows the match | kept |
| Item database | kept for the life of the process | | | |

[known] for the deletes and resets of §3.7 and §3.8; "kept" entries are [inferred] from the absence
of a writer on that path.

**Return from a match** (`CLobby::ProcessModeTransition` S 004f5950, mode "match" → "3D lobby")
[known]:

- state 1 → login screen;
- state 3 or 11, coming from a match → `id = FindBestVillageServer(protocol version, LM+0x550)`.
  Found: `SelectCharacter(LM+0x54c)`, `SelectVillageServer(id)`, `RequestEnterVillage(false)`: the
  client logs straight back into a village with the same character. This is not a re-enter, so the
  position saved in `CLobbyClient` is cleared and the avatar spawns at the position of the
  character's data blob as the reloaded character list delivered it (§3.4 step 9). Not found:
  `SelectCharacter(LM+0x54c)` and lobby screen 2 (the avatar screen [inferred]);
- state 3 or 11, coming from the main menu → lobby screen 2;
- any other state → `Logout()` and the login screen.

`SelectCharacter` needs the character list, which was requested again when the village was left;
if the character is not in the map the selection becomes 0, the chat login is made with the
account id, and the entry fails with `There is no avatar with that id` (§3.4 step 5.2). The same
failure follows when the list is still not valid at the moment the chat login completes
[inferred]. After a two-player match the return worked: in state 11 the transition from mode 1 to 3 called
`SelectCharacter(100000)` S 00472200 8 ms after it began, and the village was entered again [live, 2026-10-14];
the order against the character list (message 60) was not compared.

**Village switch** (`CLobbyClient::RequestReenterVillage` S 00503560) [known]: the world screen's
server menu (S 00437760) or the village server dialog opened from the world screen (S 00440690,
only when the chosen server differs from the current one) selects the new server, sets the
keep-list flag `SL+0xa0`, and requests a re-enter: re-enter pending = true, saved perm id =
`LM+0x54c`, timer = **2.5 s**, retries = 0, then a normal leave.
`CLobbyClient::Update` S 00503fc0, once the old connection is released and the character manager
is not busy, counts the timer down and calls `EnterVillage(false)`, which on a re-enter logs in
with the saved perm id and keeps the saved position. A failed village login during a re-enter is
retried silently (timer 2.5 s again) while the retry count is below **3**; after that, and on any
failure outside a re-enter, lobby screen 2 is requested, the error dialog `!LOGIN_FAILED_TEXT` is
shown and the re-enter state is cleared [known] S 00503800, S 00503f50.

---

## 4. Update order

### 4.1 On start

`CApplicationEx::Initialize` (`app-shell.md` §3.3 step 11), unless `-nolobby`: create the
`LobbyComm::System` (constructor of §2.1), then `Initialize` S 004643d0 in this order [known]:

1. load `ItemsClient.txt` into the item database; on failure stop (state stays 0);
2. `TinCat_CreateCommLayer(0, 0x26B6, 5, "<log dir>\commLayer.log")`: connection manager type 0
   (internet), payload magic, log level, log file [known] T 10018660. If the manager already has a
   comm layer, or none is returned, log and stop (state stays 0);
3. get the ConnectionManager (`CommLayer vtbl+0x04`) and register the manager as its callback
   sink (`vtbl+0x04(this)`); a null ConnectionManager logs and stops (state stays 0);
4. `ServerList::Initialize(gameServerManager)` (`CommLayer vtbl+0x08`);
5. `ServerMessages::Initialize(motdManager, cyclicMessageManager)` (`vtbl+0x38`, `vtbl+0x40`);
6. `Properties::Initialize(propertyManager)` (`vtbl+0x18`);
7. state = 1.

The slot → manager mapping is [known] from the tincat3 vtable T 1004ec6c and the member order of
its constructor T 10018660.

`CharacterManager`, `PostOffice` and the chat connection are attached later, on the 5 → 6
transition (§3.3).

### 4.2 Per frame: `LobbyComm::System::StatePump_Tick` S 00464ee0

Called once per frame from `CLobbyClient::Update` S 00503fc0 (its only caller is
`CLobby::Tick` S 004fb230) while the 3D lobby runs, and from `CApplicationEx::FrameTick_InGame`
S 004018e0 (main menu and match) when the menu system's "world active" flag is clear or no lobby
object exists, provided a `LobbyComm::System` exists [known]. Order inside one call [known]:

1. `CommLayer vtbl+0x54`: the library's tick (`CommLayer::Update` T 10018630). All callbacks of
   §3 (login results, list records, village and referee messages) run inside this call
   [inferred].
2. The state's own step: 3 → 4, 5 → 6, the load mask of state 6, or (state 9) `PostOffice` pump
   then whisper pump. The other states have no step.
3. `VillageServerConnection::TickInWorld`, when a village connection object exists (does nothing
   outside state 9): event queues, then ping. The 1001 handler calls the same function from
   inside step 1 (§3.6).
4. State above 2: `Properties::ProcessActions`, then `CharacterManager::ProcessActions`.
5. State above 5: referee assign request and timer; then bind the referee transport if the
   referee connection is not logged in (§3.9). The state is tested after step 2, so on the tick
   of the 5 → 6 transition the referee request is sent in the same call.

After the pump, `CLobbyClient::Update` releases a village connection marked for release and runs
the re-enter timer (§3.17) [known].

### 4.3 Per logic tick

Nothing. No part of this subsystem is called from the simulation tick [known: the callers of
S 00464ee0 are the two frame functions].

### 4.4 On events

| Event | Order of effects | Section |
|---|---|---|
| lobby login result | account id, state 3; the pump continues on the following frames | §3.1 |
| property answer | the oldest request's delegate gets the value or an error code, the request is erased, end busy | §3.2 |
| chat login during a village entry | swap delegates, copy the character to the local avatar, village login, state 8, `LM+0x54c` = character id | §3.4 |
| 1000 EnterWorld | state 9, world data, join the village-wide channel, request mail headers, seed `rand`, link quality 3, first ping, notify | §3.4 |
| 1006 with the magic code | set leave acknowledged; chat logged in: chat logout, and the village logout follows on the chat logged-out event; chat not logged in: village logout at once | §3.7 |
| village logged out | tear down the world, state 11, notify, release the transport, then reset and request again: character list, buddy list, ignore list, server list observation, MotD; reset the mailbox | §3.7 |
| lobby logged out (state not 1) | notify (state below 7: the login-failed list with 0x5479; else the logged-out list), reset characters, release chat and referee transports, detach mail, state 1 | §3.8 |
| lobby connection lost | state 12, notify | §3.8 |

[known] S 00463a10, S 0048e920, S 004704e0, S 0046f670, S 0046ec50, S 0046db30, S 00464bf0,
S 00470e20, S 004647e0.

---

## 5. Inputs and outputs

### 5.1 Messages

Lobby connection (NETMSG, built and parsed inside tincat3; the client calls interface methods and
gets callbacks). Layouts: `message-catalog.md`, sections "Lobby connection", "Server list",
"tincat3 managers".

| Purpose | Client sends | Client handles | Owner |
|---|---|---|---|
| login / registration | 204 / 203 (after the session set-up of `message-catalog.md`, "Login sequence at a glance") | login callbacks | `LobbyComm::System` |
| version check | 161 PropertyGet (1, 1) | 162 PropertyData | `Properties` |
| message of the day | 105 | 106 (a 42 does not complete the request) | `ServerMessages` |
| chat server address | 189 (type 2) | 192 | tincat3 (`HandlerUserComm` T 10027630) |
| server list | 171 (type 4, then type 5), 172 | 170 rows + 42, later 170 pushes | `ServerList` |
| referee assignment | 189 (type 4, subtype 4) | 170 as assign answer, or an error result | `ServerList` → `LobbyComm::System` |
| hosted game | create / update / remove (`match-setup-room.md` §5.1) | results | `ServerList` |
| character list | 55 | 60 rows + 42 | `CharacterManager` |
| create / delete character | 86 / 94 | 153 / 42 | `CharacterManager` |
| name ↔ id look-up | 72 | 75 rows + 42 | `CharacterManager` |
| e-mail after registration | 88 | 42 | `CharacterManager` |
| buddies | 56, 98, 99 | 61 rows, 61 pushes, 42 | `CharacterManager` |
| ignore list | 157, 154, 155 | 160 rows, 42 | `CharacterManager` |
| mail | 147, 148, 150, 151 | 149 records, 42; 153 as the answer to 150 | `PostOffice` |

Chat connection (NETMSG; `message-catalog.md`, "UC / chat connection"):

| Purpose | Client sends | Client handles |
|---|---|---|
| login with the character id | token exchange inside tincat3 | logged-in / failed callbacks |
| channels | 17 join, 259 leave | 42 results; channel list, created, removed notifications |
| chat line | 2 | 2 |
| whisper | 30 | 3 |

Village connection (`LobbyMessage` in NETMSG 74; `message-catalog.md`, "Village / world
connection"):

| Client sends (category 2) | Client handles |
|---|---|
| 2000 avatar location; 2001 create minigame table; 2002 leave | 1000 EnterWorld; 1001 avatar data; 1002 avatar logged in; 1003 avatar removed; 1004 NPC; 1005 world tick; 1006 leave acknowledge |
| 3001 move item; 3002 delete item | 3100 active items; 3101 inventory; 3102 all items; 3200 level and experience; 3201 stats |
| 3600 open shop; 3610 buy; 3620 sell | 3601 shop inventory; 3611 buy result; 3621 sell result |
| 3798 ping | 3799 pong |
| 3950 avatar colour change | 3910 trade request; 3930 trade offer |
| 4000 chat command | |
| category 5: 204 leave table, 209 join table, 222 amount; dice 220, 221; poker 300, 301, 302; pawn chess 400 to 403 | 216 table remove; 217 table update; 218 table create; 219 no table left; 220 no player slot left; 303 poker hand |

Referee connection (`LobbyMessage`, category 3; `MATCH_START.md`, "Referee protocol reference"):

| Client sends | Client handles |
|---|---|
| 3500 claim chest; 3510 register game; 3520 finish game; 3540 give up | 3501 / 3502; 3511 / 3512; 3521 / 3522; 3530 login success; 3531 login failed; 3541 |

[known] for the ids (constructor calls and the two dispatch switches S 00470a90, S 0047b090).
NETMSG numbers of the lobby connection: [known] for the character, buddy, ignore and e-mail rows
(the interface slots called in S 00472f00 and S 00476390, resolved through the tincat3 vtables
T 1005152c and T 1004e930 to the senders named in `message-catalog.md`) and for 189 type 2
(T 10027630); the other rows and the chat table are [inferred] from `message-catalog.md`.

### 5.2 Other subsystems

| Subsystem | Interface |
|---|---|
| Lobby user interface (`LobbyMenu::*`) | subscribes to the observer lists of §2.19; calls the entry points of §3; polls valid, changed and busy flags, the proxies' fields, the link quality |
| 3D lobby (`Lobby::CLobby`, `CLobbyClient`) | creates and destroys the 3D objects for proxies; writes the proxy's 3D object pointer; sends the local avatar's location (2000); drives village entry and exit |
| Peer-to-peer session (`network-session.md`) | chat tab 4; the pre-game room destroys the hosted game and leaves the village at match start; `WorldScreen::OnShow` shuts the session down when the world screen appears again |
| Match (`quests-sacrifices-stats.md` for chests; `MATCH_START.md`) | calls `RefereeServerConnection::ClaimChest`, `GiveUpGame`, `FinishGame` and subscribes to the result lists |
| Application shell (`app-shell.md`) | creates, pumps and destroys the manager; supplies the log directory and the lobby profile |

---

## 6. Data-driven parameters

| File (in the install) | Keys / format | Example values | Used for |
|---|---|---|---|
| `data\lobby\config\ItemsClient.txt` (plain text) | one item per line; a line whose first character after trimming is `#` is skipped; exactly 9 tokens separated by `;` (`"` quotes, `\` escapes), any other count is logged as an invalid line and skipped: id; name key; description key; unsigned integer; signed integer; slot mask; mesh name; icon name; base value | `2;"!LOBBY_ITEM_CROWN";"!LOBBY_ITEM_CROWN_DESC";4;1;1;"Crown";"CrownIcon";250`. 36 items; slot mask 1 on 8 items, 2 on 13, 4 on 2, 8 on 13; tokens 3 and 4 are always 4 and 1 | item database (§2.14) |
| `data\lobby\config\LobbySettings.ini` (plain) | `[LobbyServer]` `Host`, `Port`; `[LobbyClient]` `ProtocolVersion` (optional), `HallOfFameURL<n>`, `HallOfFameURL<n>_AppendPermID`, `HallOfFameURL<n>_AppendCharname` | `Port = 7070`; no `ProtocolVersion` key in the install; `HallOfFameURL0` to `2`, each with `_AppendPermID=1` and no `_AppendCharname` key. Defaults in the code: `Port` 7070, `ProtocolVersion` −1 (= keep the built-in value), URL empty, both append flags 0 | login target; version check and village list filter; hall-of-fame pages (`lobby-extras.md`) |
| text tables | keys named in this document | `!CHATCHANNEL_GLOBAL`, `!CHATCHANNEL_LOCAL`, `!CHATCHANNEL_MINIGAME`, `!CHATCHANNEL_SETTLERS`, `!MOTD_ERROR`, `!LOBBY_CHAT_WELCOME`, `!LOBBY_CHAT_HELP`, `!LOBBY_CHAT_FROM`, `!LOBBY_IMPORTANT_SYSTEM_MESSAGE`, `!LOGIN_FAILED_TEXT` | user-visible text |

[known] file contents; item loader S 0048bfd0; settings readers S 00465450 (`Port`), S 00465380
(`ProtocolVersion`), S 00465960 (hall-of-fame keys); the text keys are string constants in
S 004389d0, S 00436180, S 00436860, S 00488550 and S 00503800. Format details of both files:
`formats-inventory.md` §3.10.

Constants in the code [known unless tagged]:

| Constant | Value | Where |
|---|---|---|
| payload magic of the comm layer | 0x26B6 | S 004643d0 |
| comm layer type / log level | 0 (internet) / 5 | S 004643d0, T 10018660 |
| client protocol version (default) | 1000 | data at S 0087aed8; replaced by `ProtocolVersion` when the key exists, S 0043cbf0 |
| version-check property | kategory 1, index 1 | S 00464ee0 |
| error codes passed to the UI | 0x6f, 0x3e (version check); 0x5479 (logout before login completed); 0x91 (chat open failed); −1 (chat login failed, character missing); −10000 (mail recipient not resolvable) | §3 |
| referee retry timer | 60000 ms | S 004625d0 |
| leave request / acknowledge codes | 0xAFFEDEAD / 0xDEADBEEF | S 0046bde0, S 0046ec50 |
| ping countdown | 30 s after a send, 15 s after a failed send, +90 s on the pong | S 0046c150, S 0046c250 |
| link quality thresholds (half round trip) | 0.1 s, 0.25 s, 2.0 s | S 0046c250 |
| "no pending ping" | 0x80008000 | S 0046eee0 |
| mail header poll | 60 s | S 0047d880 |
| mail recipient look-up retries | 3 | S 0047d880 |
| village load thresholds | 85 %, 70 %, 90 % | S 00469010 |
| re-enter timer / retries | 2.5 s / 3 (a failed village login re-arms the timer while fewer than 3 retries were made) | S 00503560, S 00503800 |
| default spawn | (−31.24, 2.71, −8.28), heading 0, zone 0, ghost zone 0x0F | S 00503940; the same position and zone for a new character S 00481e60, whose ghost zone is the proxy default S 0046bb10 |
| new character | level 1, experience 0, gold 50, play money 50 | S 00481e60 |
| backpack size | at least 20 slots | S 0048af70 |
| location range | x, z ∈ [−150, 150]; y ∈ [−10, 30] (six floats at S 0087b700); 11 bits per axis (value / 2048 of the range); heading 7 bits (value × 360 / 128 degrees); zone 4 bits | S 0048f670, S 0048f7e0 |
| zone "none" | 0x0F | S 0046bb10 |
| chat zone keys | 0xFF village-wide, 0xFE minigame table | S 0046f670, S 0046e820 |

---

## 7. Save and load

- **Nothing in this subsystem is written to disk by the client**, apart from logs: the lobby log
  (`LobbyComm::Logger`, global at S 008858b8; when it is opened, the file is deleted first if it
  is larger than a size cap; the cap's constructor default −1 disables the test [known]
  S 00466c40, S 00466ba0, S 004669e0) and tincat3's `commLayer.log` [inferred].
- After a successful login or account creation the dialogs store the user name and the CD key in
  the per-user lobby file, section `[User]`, keys `Name` and `CDKey` [known] S 00465530,
  S 00465620 (file: `<My Documents>\SAdK\lobby\<profile>.ini`, `app-shell.md` §3.3 step 10
  [inferred]). That file belongs to the dialogs, not to the manager.
- **All persistent state is on the server.** The character `data` blob (look, equipment, backpack,
  level, experience, gold, play money, last position, heading, zone) is the character's save; the
  client receives it with the character list and rebuilds the `AvatarProxy` from it
  (`village-and-character-protocol.md` §1.4). Buddies, ignore list and mail are fetched after each
  login.
- Within one process run, the name caches, the chat channel vector, the last village server id,
  the local perm id and the position saved at the last village leave survive across logins
  (§3.17).

---

## 8. Determinism notes

This subsystem is **front end only**. It does not read or write simulation state:

- it is pumped per rendered frame, with frame time, not per logic tick (§4.2, §4.3);
- its timers use the wall clock (`Timer_GetTotalSeconds`, `Timer_GetFrameDeltaMs`);
- it seeds and uses the C library's `rand` (ping codes, placeholder avatar looks), which is not the
  simulation's generator [inferred: the simulation uses its own generator, `logic-core.md`];
- nothing in it is part of the match checksum or the save game.

Its only inputs **to** a match arrive through other subsystems: the referee's `GameSeed` (register
game result) is handed to the match set-up by the world screen (`MATCH_START.md`, phase 2), and the
wager and the player names come from the pre-game room (`match-setup-room.md`). During a match the
pump keeps running (referee assign repetition, property and character queues) without touching the
simulation [known] S 004018e0.

---

## 9. Notes for a Godot reimplementation

**What maps onto engine features**

- Observer lists → signals. Keep the argument lists of §2.19; several consumers rely on getting
  the proxy object, not an id.
- Managers and connections → autoload singletons or one node with child nodes; the pump → one
  `_process` callback that keeps the order of §4.2.
- The request queues → plain arrays with a "busy" flag. A remake that talks to its own server can
  add timeouts; the original has none (§2.4).
- `LobbyMessage` → a small bit reader / writer class; §3.14 is the complete rule set.

**What must be reproduced exactly to talk to an original-compatible server**

- The state numbers are not on the wire, but the **order** of requests after login is observable:
  version check; then, in one pump call, server-list observation (type 4, then 5), MotD, character
  list and the first referee assign; then buddy list; then ignore list; the referee assign is
  repeated 60 s after each answer (§3.9).
- Village entry is chat login first, village login second, both with the **character id**; leaving
  is 2002, then on 1006 chat logout, then village logout (§3.4, §3.7).
- Bit packing: most significant bit first, no alignment, 8-bit string lengths, UTF-8 on the wire,
  the packed unsigned format, the reversed byte order of the raw 32-bit accessor, the 11/11/11/7/4
  location block and its bounds.
- The client ignores the location of its own avatar in 1001, never edits inventories locally, and
  needs exactly its own slot count in a backpack block (§3.15, §3.16).
- The character blob layout, since it is the save (`village-and-character-protocol.md` §1.4).

**What a server has to provide** (summary; details in `village-and-character-protocol.md` §8 and
`message-catalog.md`, "Server decisions")

- an answer to every request the client waits on without a timeout: login, property (1, 1), MotD,
  character list, buddy list, ignore list, EnterWorld after the village login, 1006 after 2002;
- village server descriptors with a `data` block of 5 bytes (32-bit protocol key equal to the
  client's version, then the flag bit; the client reads any block whose pointer is non-null, §2.9)
  and a non-zero `running`, or the "enter village" button stays disabled;
- message ids of mails that are never 0;
- no names flag (bit 15) on `LobbyMessage`s, or 32 extra bits at the end.

**What need not be reproduced**

- the unused pieces: the observer lists that never fire (`LM+0x34`, `VSC+0x110`, `VSC+0x14c`), the
  two event deques nothing fills, the leave-acknowledged flag `VSC+0x224` (written, never read),
  the `<user>@s2k8` string, the schema checksum (the original never verifies it), the game-server
  connection (nothing in the decompiled code binds it to a transport, §10 item 1);
- the defects listed in §3 (the bulk server-list path, the mail result callbacks that get id 0,
  the stalls of the mail and whisper queues): a remake should implement the intended behaviour
  (erase a mail on a successful delete, time out a look-up).

**Converter**: nothing to convert for this subsystem except `ItemsClient.txt` (plain text, read
from the player's install; the remake must not ship it) and the text keys of §6.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Is `GameServerConnection` (`LM+0x544`) ever bound to a transport? Its `OnLoggedIn` S 0048edf0 starts the peer-to-peer network, but statically nothing binds it: the only reference to `Initialize` S 0048eda0 is its vtable slot S 007deaf4; `LM+0x544` is used only by the constructor, the destructor and the five connection callbacks of `LobbyComm::System`, none of which calls that slot; the manager has no accessor for the field [inferred: a search of the decompiled code]. Hosting a room and leaving it called neither `Initialize` nor `OnLoggedIn` [live, 2026-10-14]; joining was not part of that run | live: hook S 0048eda0 while joining |
| 2 | Meaning of the four bools of `ChatChannelInfo` (`+0x24 … +0x27`) | static read of the tincat3 channel descriptor builder (which message field feeds descriptor `+0x14`, `+0x18`, `+0x1c`, `+0x20`) |
| 3 | Answered: nothing consumes `VSC+0xd4` (inventory changed), `+0x134` and `+0x140` (shop buy / sell result). `ObserverList::Subscribe` S 00458860 is the only subscribe function; its calls on the village connection are in S 00503d00 and S 004351a0 and name none of the three lists | static: the list argument of every call of S 00458860 |
| 4 | Who fills the event deques `VSC+0x1fc` and `VSC+0x210` and subscribes to `+0xec` / `+0xf8`? | static: search for pushes on those two offsets program-wide |
| 5 | Answered (§2.19): `LM+0x34`, `VSC+0x110` and `VSC+0x14c` never fire in the decompiled code, and hooks on both `ObserverList_NotifyAll` bodies (S 00464300, S 0045f620) and on the subscriber S 005037a0 saw no call for them through a login, a village entry and exit, a hosted room and a lost lobby connection [live, 2026-10-14]. A match start was not in that window | — |
| 6 | Answered (§3.17): after a two-player match `ProcessModeTransition` S 004f5950 went from mode 1 to 3 in state 11, called `SelectCharacter(100000)` 8 ms later and the village was entered again [live, 2026-10-14]; the order against the character list (message 60) was not compared | — |
| 7 | Transport states other than 0, 2, 8, 9: exact meaning of 1, 3, 4, 5 | static read of the tincat3 connection classes (`message-catalog.md` lists the login steps) |
| 8 | Under which conditions does the tincat3 send of a list refresh return an error (§3.3 describes what the client does then)? | static: the failure codes of T 1002dd00 and of the ignore-list sender in the tincat3 user manager |
| 9 | Tokens 3 and 4 of `ItemsClient.txt` (always 4 and 1): token 4 (`ItemInfo+0x44`) ≥ 1 is enough to make an item valid (S 0048b100), its only reader; token 3 (`+0x3c`) is stored and copied and has no reader (users of both fields: S 0048b120, S 0048b200, S 0048b2e0, the loader S 0048bfd0, S 0048b100) [known]. Stack size and a validity count? | live: an item file with other values, then stack, split and sell (`docs/live-session-queue.md`) |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 00464280 | `LobbyManager_CreateInstance` | creates the singleton (0x5a8 bytes) |
| S 00463fd0 | `LobbyComm::System::ctor` | builds every manager, connection and map |
| S 004643d0 | `LobbyComm::System::Initialize` | item database, comm layer, manager attachment, state 1 |
| S 00462f70 | `LobbyComm::System::Destroy` | shutdown, state 0 |
| S 004630e0 / S 004633f0 | `LobbyComm::System::Login` / `CreateUser` | start of a session (state 1 → 2) |
| S 00463710 | `LobbyComm::System::Logout` | disconnect all |
| S 00464ee0 | `LobbyComm::System::StatePump_Tick` | the per-frame pump and state machine |
| S 00464e70 | `LobbyComm::System::OnVersionChecked_State4to5` | version check result |
| S 00463a10 / S 00464a20 / S 00464bf0 / S 004647e0 | `LobbyComm::System::OnLoggedIn` / `OnLoginFailed` / `OnLoggedOut` / `OnConnectionLost` | connection events, routed per connection |
| S 00462760 | `LobbyComm::System::DispatchInboundToConnection` | raw data to village, game-server or referee connection |
| S 00462540 / S 00462a00 | `LobbyComm::System::SetState` / `GetStateName` | state latch; the state names |
| S 00463850 | `LobbyComm::System::CreateVillageServerConnection` | binds the village transport |
| S 00462910 / S 004625d0 | `InitRefereeServerConnection` / `SetRefereeServerAddress` | referee transport; referee id and 60 s timer |
| S 004626c0 / S 00462570 | `SetLocalAvatar` / `ClearLocalAvatar` | local avatar proxy |
| S 00462440 | `LobbyComm::System::ResetSubManagers` | reset of five managers before a login |
| S 0048dd80 … S 0048e3c0 | `BaseConnection::*` | transport binding, send, the four event lists |
| S 0048dce0 / S 0048dd00 | `BaseConnection::IsLoggedIn` / `IsConnectionPending` | transport state tests |
| S 0048ee90 / S 0048eea0 / S 0048eeb0 | `ASyncAction::IsBusy` / `TryBeginBusy` / `TryEndBusy` | the busy flag |
| S 0046eee0 | `VillageServerConnection::ctor` | initial values of §2.6 |
| S 00470d50 | `VillageServerConnection::OpenUserComm` | village entry step: chat login |
| S 004704e0 / S 00470660 | `OnUserCommLoggedIn` / `OnUserCommLoginFailed` | village login; state 8 |
| S 00470a90 | `VillageServerConnection::HandleMessage` | dispatch by message id |
| S 0046f670 | `HandleEnterWorld` | state 9 and the world set-up |
| S 0046bde0 / S 0046ec50 / S 0046db30 | `SendLeaveVillageRequest` / `HandleWorldLoginAck` / `OnUserCommLoggedOut` | the leave sequence |
| S 00470e20 / S 00470f90 / S 0046da60 | `HandleLoggedOut` / `HandleDisconnected` / `Destroy` | world teardown, state 11 |
| S 00471110 / S 0046fde0 | `TickInWorld` / `DrainEventQueues` | per-frame delivery of queued events |
| S 0046c150 / S 0046c250 / S 0046c360 | `SendPing` / `HandlePongCode` / `PingPongTimerTick` | keep-alive and link quality |
| S 0046e860 / S 0046d610 / S 0046d170 | `JoinZoneChatChannel` / `OnChatChannelJoined` / `GetChatChannelKind` | zone chat channels |
| S 0046e1d0 / S 0046e390 / S 0046e570 / S 0046f8c0 | `HandleAvatarData` / `HandleAvatarLoggedIn` / `HandleAvatarRemove` / `HandleNPCData` | proxy creation and update |
| S 0046fab0 / S 0046fc10 / S 0046fd10 | `ClearAvatarsAndEventQueues` / `ClearNPCs` / `ClearMiniGameTables` | world exit |
| S 0047f160 / S 0047ff10 / S 0047ed70 | `UserCommConnection::Initialize` / `OpenCommunication` / `Logout` | chat transport |
| S 00480070 / S 004801e0 / S 0047ede0 | `JoinChannel` / `LeaveChannel` / `SendChatMessage` | chat requests |
| S 004808a0 / S 00480630 / S 00480340 | `QueuePrivateMessage` / `Process` / `OnWhisperTargetLookedUp` | whisper queue |
| S 00480e30 / S 004810a0 / S 00480a70 / S 00480c50 | `ChatReceived` / `PrivateChatReceived` / `JoinChannelReceived` / `LeaveChannelReceived` | chat callbacks |
| S 004793f0 / S 00479540 / S 0047b090 | `RefereeServerConnection::Login` / `Logout` / `OnReceive` | referee login and dispatch |
| S 00468e80 / S 00468c50 | `ServerList::StartObservation` / `Reset` | server list subscription |
| S 0046a440 / S 0046a5e0 | `ServerList::AddOrUpdateDescriptor` / `RemoveServer` | descriptor sink |
| S 00469010 / S 00468380 / S 00468560 | `FindBestVillageServer` / `SelectVillageServer` / `HasJoinableServerForProtocol` | village server choice |
| S 00468f60 / S 00469ad0 / S 00469be0 | `RequestRefereeServer` / `GameServerAssigned` / `AssignGameServerResultReceived` | referee assignment |
| S 00481640 | `VillageServerInfo::UpdateFromDescriptor` | village entry from message 170 |
| S 004884d0 / S 00488550 | `ServerMessages::RequestMotD` / `IMotDObserver_OnMotDReceived` | message of the day |
| S 0048ecb0 / S 0048e880 / S 0048e920 | `Properties::RequestProperty` / `ProcessActions` / `PropertyDataReceived` | property queue |
| S 00478f80 / S 00473460 | `CharacterManager::ctor` / `Initialize` | set-up |
| S 00476390 | `CharacterManager::ProcessActions` | the action queue pump |
| S 00472f00 / S 00474910 | `RequestCharacterList` / `CharListReceived` | character list |
| S 004750f0 / S 004751e0 / S 00472200 | `CreateCharacter` / `DeleteCharacter` / `SelectCharacter` | character entry points |
| S 00476a40 / S 00473a50 / S 00473590 / S 00473e90 | `CreateResultReceived` / `DeleteResultReceived` / `CharacterDataReceived` / `UpdateResultReceived` | result callbacks |
| S 00475430 … S 00475990 | `RefreshFriendList`, `AddToFriendList`, `RemoveFromFriendList`, `RefreshIgnoreList`, `AddToIgnoreList`, `RemoveFromIgnoreList` | buddy and ignore entry points |
| S 00478160 / S 00478660 / S 00476f90 | `BuddyListReceived` / `IgnoreListReceived` / `BuddyUpdateReceived` | list callbacks and the status push |
| S 004752a0 / S 00475370 / S 004780c0 | `LookUpID` / `LookUpName` / `CacheUserName` | name ↔ id |
| S 00472a00 | `CharacterManager::GetUserRelation` | 0 none, 1 buddy, 2 ignored |
| S 00476020 / S 00472b30 | `CharacterManager::Reset` / `ResetOnLogout` | the two resets |
| S 00481e60 | `AvatarProxy::ApplyCharacterDataBlocks` | character blob → proxy |
| S 00482c20 / S 004824b0 / S 004825f0 / S 00481da0 | `AvatarProxy::ReadDataBlocks` / `ReadLocationBlock` / `ReadStyleBlock` / `ReadStatsBlock` | 1001 blocks |
| S 0048abe0 / S 0048ac20 / S 0048af70 | `AvatarItemContainer::ReadActiveItemsBlock` / `ReadInventoryBlock` / `InitFromDataBlocks` | equipment and backpack |
| S 0047b5c0 | `NPCProxy::ReadFromMessage` | 1004 body |
| S 0047cd70 / S 0047cdf0 / S 0047ce60 | `PostOffice::Initialize` / `Destroy` / `Reset` | mail set-up |
| S 0047d880 | `PostOffice::Process` | mail pump |
| S 0047d140 / S 0047d200 / S 0047d390 / S 0047dfc0 / S 0047d4a0 | `RequestMailHeaders` / `RequestMail` / `MarkRead` / `DeleteMail` / `SendMail` | mail entry points |
| S 0047dce0 / S 0047e0f0 / S 0047c290 / S 0047e590 / S 0047c5e0 | mail callbacks | headers, body, mark read, delete, send |
| S 0047e930 | `PostOffice::CollectNewMails` | new mails for the dialog; auto-delete of ignored senders |
| S 0048cce0 / S 0048ced0 | `Mail::UpdateFromRecord` / `ctor_fromRecord` | record → mail |
| S 0048bfd0 / S 0048b770 / S 0048b100 | `ItemDatabase::LoadFromFile` / `GetItemInfo` / `ItemInfo::IsValid` | item catalogue |
| S 0048fb00 / S 0048fa50 / S 0048f9a0 | `LobbyMessage::ctor` / `InitFromWire` / `InitFromBuffer` | build; parse |
| S 0048eec0 | `LobbyMessage::GetHeaderWord` | type word |
| S 0048ef70 / S 0048f0d0 | `LobbyMessage::WriteBits` / `ReadBits` | the bit packing |
| S 0048fb90 / S 0048fcb0 | `WriteNamedPackedUInt` / `ReadNamedPackedUInt` | packed unsigned |
| S 0048fe20 / S 004900a0 / S 0048ffc0 | `WriteString` / `ReadString` / `ReadStringRaw` | strings |
| S 0048fef0 / S 0048ff50 | `WriteRaw32LE` / `ReadRaw32LE` | byte-reversed 32-bit |
| S 0048f670 / S 0048f7e0 | `ReadLocationBlock` / `WriteLocationBlock` | quantised location |
| S 0048f490 / S 0048f4c0 / S 0048f530 / S 0048ef00 | `SelectField` / `Finalize` / `FinishRead` / `Discard` | names mode, trailer, end of message |
| S 00503f50 / S 00503fc0 / S 00503470 / S 00503560 | `CLobbyClient::EnterVillage` / `Update` / `LeaveVillage` / `RequestReenterVillage` | entry, pump call, leave, village switch |
| S 00503d00 / S 00503940 / S 00503280 / S 00503800 | `CLobbyClient::SubscribeVillageConnection` / `OnEnterWorld` / `OnVillageConnectionClosed` / `OnVillageLoginFailed` | observer wiring |
| S 004f5950 | `CLobby::ProcessModeTransition` | return from a match into the village |
| S 004351a0 / S 004389d0 | `WorldScreen::Activate` / `OnShow` | world-screen subscriptions; chat tabs |
| S 00436180 / S 00436860 | `WorldScreen::OnChatChannelMessage` / `SendChatInput` | chat line in and out |
| S 00458860 | `ObserverList::Subscribe` | observer registration |
