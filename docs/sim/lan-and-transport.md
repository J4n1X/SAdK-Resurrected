# LAN discovery and the TinCat transport under the match session

Binaries: `sadk_noav.exe` (base 0x400000, addresses written S 00xxxxxx) and `tincat3.dll` (base 0x10000000,
addresses written T 10xxxxxx). Tags: **[known]** = read at the given address or in the named data file and key;
**[inferred]** = one step of reasoning from what is visible; **[TODO]** = not established, with what would settle
it. Nothing here was observed in the running game.

Related documents, not repeated here: `docs/sim/network-session.md` (the session layer above this transport:
events, tick packages, join, leave, the manager's reconnect state machine; its §2.1 net ids, §2.7 transport
object, §3.1 send primitives, §3.3 roles, §3.9 reconnect), `docs/LOBBY_PROTOCOL.md` §3.1 (the 28-byte TinCat
frame header as the lobby connection uses it), `docs/s2tftp.md` (file transfer, message 1003),
`docs/sim/match-setup-room.md` (the room that runs on top of a role 3 or 4 session), `docs/subsystems.md`
(library inventory of `tincat3.dll`).

---

## 1. Purpose and scope

Two things live below `NComm_Manager`:

- **LAN discovery** (`BC_*`): a UDP broadcast query and reply that lets a client list the games hosted in its
  broadcast domain. The code is complete in both binaries, but **nothing in this build starts it**: the transport
  slot `BC_Start` has no caller, and the two network roles that would use it (1 and 2) are never requested (§3.1).
  It is specified here so that a remake can offer a LAN list that follows the original layout, and so that the
  open `[TODO]` of `network-session.md` §3.3 is closed.
- **The TinCat transport** of a match: a TCP star with the host as TinCat server. This document specifies what
  `NComm::TinCatNetwork` asks of `tincat3.dll` (creation, values, callbacks), how ids are given out, how a
  message to the host, to all, or to one user travels, the user list, keep-alive and timeouts, the `Reconnector`
  module (host election) and the frame format, each as far as the match depends on it.

Out of scope: the lobby, chat and village connections (they use other TinCat instances through the `CommLayer`
classes of `tincat3.dll`), TinCat's cell, group, property and load-balance modules (not used by the match
transport), the session rules above the transport (`network-session.md`).

---

## 2. Data model

### 2.1 `NComm::TinCatNetwork` fields used here (0xec bytes)

Field table of the whole object: `network-session.md` §2.7. The fields of this document [known, Ghidra struct,
constructor S 0041e310]:

| Offset | Type | Field | Initial value |
|---|---|---|---|
| +0x00 | ptr | vftable of `INetworkHandler` (S 007d58f4, 44 slots) | |
| +0x04 | ptr | vftable of the TinCat callback interface (S 007d58ac, 16 slots, §2.6). TinCat calls it with `this` = object + 4 | |
| +0x08 | ptr | TinCat API object (`TinCat_CTRL`, from `TinCat_CreateAPI`) | 0 |
| +0x0c | ptr | `NComm::TinCatReconnector` (§2.5) | 0 |
| +0x10 | u32 | local net id (§2.2) | `0xEFFFFFEE` |
| +0x14 | std::list | user list, entries `TinCatUserEntry` (§2.4) | empty |
| +0x20 | u32 | LAN mode: 0 off, 1 searching (client), 2 announcing (host) | 0 |
| +0x24 | u32 | LAN active flag (returned by `BC_IsActive` S 00418f70) | 0 |
| +0x28 | std::map&lt;u32, BCGameInfo&gt; | discovered LAN games, key = local server id | empty |
| +0x34 | u32 | next local server id | not written by the constructor |
| +0x48 | BCGameInfo | the host's own LAN record (§2.3) | id -1, strings empty, address -1 |
| +0xd8 | ptr | LAN observer (argument of `BC_Start`; cleared by a successful `BC_Stop`) | 0 |
| +0xdc | ptr | 0x400-byte buffer (`malloc`), holds the serialised own record | allocated |
| +0xe0 | f32 | time (s) of the last LAN list request | 0.0 |

`+0x34` has no initial value: the constructor's instructions write every other field of the table and not this
one, the object comes from a plain `operator new(0xec)` (S 0040a9a0), and the only access met in the functions
of this document is the read-and-increment in the *added* handler (§3.2) [known, disassembly of S 0041e310]. The first id given out is
therefore whatever the allocation held; ids are only unique within one transport object. A remake starts at 0
[inferred: the intent of a counter].

### 2.2 Net ids

Reserved ids (`network-session.md` §2.1) as TinCat itself uses them [known]:

| Value | Meaning in `tincat3.dll` | Evidence |
|---|---|---|
| `0xEFFFFFCC` | the server (host). Source id of everything a server-mode instance sends; destination "deliver to the server" | T 10009c90, T 10005140 |
| `0xEFFFFFDD` | all users (`USR_ALL`), destination only | T 10003cc0, T 10005140 |
| `0xEFFFFFEE` | no id: the id a client carries before logon; "no exclusion" in a broadcast | T 10004660, T 10003bc0 |
| `0xEFFFFF88` | the local instance: a message with this destination goes to the local receive queue, no socket | T 10003b20, T 10003cc0 |

**Per-user ids** are small integers given out by the host at logon: the lowest free id of a pool that counts
from 1 (`SlotTable_Alloc` T 10035880 scans from index 1; called by `NETUSR_AllocUserAddr` T 10006870; pool created by
`NETUSR_InitAddrSystem` T 100067d0) [known]. The first client to log on gets 1, the next 2 [inferred from the
scan]; an id is released when its user is removed (`NETUSR_FreeUserAddr`, called from `KRNL_RemoveUser`
T 10005d30) [known for the call; the release itself is not read]. Id 0 is never given out: 0 is the allocator's
"no free id" result [known].

The client learns its id from the logon reply (§3.4) and TinCat reports it through the `User_LoggedIN` callback.
`TinCat_CTRL::ConnectToIP` returns that id (the `userId` of the connection's address record) or -1 on every
failure [known, disassembly of T 10009670]; `ConnectToServer` S 0041a1b0 stores a result other than -1 as the
local net id [inferred for the destination: the store is decompiled as a stack-relative write]. A client's local
net id is therefore its **own** user id, not an id of the host. The host's local net id is the
constant `0xEFFFFFCC` (S 0041e610) [known].

### 2.3 `ai::network::BCGameInfo` (0x90 bytes; one LAN game)

[known: constructor block in S 0041e310, `Serialize` S 00419330, `Deserialize` S 004194a0]

| Offset | Type | Field | Source on the host | Value on the client |
|---|---|---|---|---|
| +0x00 | i32 | serverId | -1 | replaced by the local map key |
| +0x04 | std::string | gameName | session gameName (`EventGameInformation +0x1d8`) | from the payload |
| +0x20 | std::string | mapName | session mapName (`+0x208`) | from the payload |
| +0x3c | std::string | `string_3c`: not serialised, never written by the functions of this document | empty | empty |
| +0x58 | i32 | `connectedHumans`: human slots with a playerId other than `0xEFFFFFEE`, over the six slots (`CountConnectedHumans` S 004133c0) | computed | from the payload |
| +0x5c | i32 | `maxPlayers` (`GetMaxPlayers` S 00412fc0: session `+0x224`, an i8, sign-extended) | computed | from the payload |
| +0x60..+0x6c | i32[4] | `hostIp`: host IPv4 address, one octet per dword | -1 each | the UDP source address of the reply |
| +0x70 | i32 | `gamePort` (TCP port to connect to); 0 after construction | `gamePort` (`network.ini`) | the record's `value` field |
| +0x74 | std::string | `string_74`: trailing string; never set by the host code | empty | from the payload when present |

`+0x58` is written with the human count by `BC_Start` S 0041aa90 and `BC_Update` S 0041adb0 [known].

### 2.4 `ai::network::TinCatUserEntry` (0x48 bytes; one user of the session)

[known, Ghidra struct; writers S 0041e990, S 0041a720, S 0041d610]

| Offset | Type | Field |
|---|---|---|
| +0x00 | std::string | name |
| +0x1c | u32 | net id |
| +0x20 | NetGUID | GUID (vftable + 4 dwords) |
| +0x34 | i32 | level = the user's connection type (0..4; `docs/sim/frontend-screens.md`, key `cConnectionType`); 0 until the user data is written |
| +0x38 | f32 | 0.0 in an entry made by `UIS_Add`; -1.0 in the host's own entry and whenever the user data is written; no reader met |
| +0x3c | std::list&lt;u32&gt; (head pointer `+0x40`, size `+0x44`) | ping samples in ms, newest first, at most 2 kept |

### 2.5 Reconnector objects

`NComm::TinCatReconnector` (0x24 bytes, game side; implements `TinCatModules::IReconnectorCallbacks`)
[known, S 00418fd0, S 004258e0, S 004259b0, S 00425aa0]:

| Offset | Field | Initial |
|---|---|---|
| +0x00 | vftable (S 007d5290): `+0` deleting destructor, `+4` `cb_BecameServer()`, `+8` `cb_ReconnectTo(ip0, ip1, ip2, ip3, port)` | |
| +0x04 | `TinCatModules::Reconnector*` (4 bytes: one pointer to its implementation) | 0 |
| +0x08 | TinCat API (set when `Reconnector::Init` succeeded) | 0 |
| +0x0c | state: 0 idle, 1 this peer became the host, 2 reconnect to the stored address | 0 |
| +0x10..+0x1c | host IPv4 octets (i32 each) | -1 |
| +0x20 | host port | 0 |

`ReconnectorImpl` (0x44 bytes, inside `tincat3.dll`) [known, T 10010d10, T 100109b0]:

| Offset | Field | Initial |
|---|---|---|
| +0x00 | TinCat API | 0 |
| +0x04 | callbacks (`IReconnectorCallbacks*`) | 0 |
| +0x08 | peer list (ordered; new entries go to the end; entries `ReconnectorPeer`) | empty |
| +0x20 | isHost | 0 |
| +0x24 | own connection id (client: the id given to `HandleAddedConnection`) | `0xEFFFFFEE` |
| +0x28 | user-data list (records `{u32 id, u32 length, bytes}`) | empty |
| +0x40 | local port (third argument of `Init`) | not written by the constructor |

`ReconnectorPeer` (0x1c bytes) [known, T 10010710, T 10010780]: `+0x00` u32 state (1 normal, 2 preferred next
host), `+0x04` u32 connection id, `+0x08..+0x14` u32 × 4 IPv4 octets, `+0x18` u32 port.

### 2.6 TinCat callback interface (vtable S 007d58ac)

What TinCat calls on the transport, and what the transport does [known, vtable bytes and each function]:

| Slot | TinCat event | Handler | Action |
|---|---|---|---|
| +0x04 | `ConnectionEstablished` (T 100088c0) | S 0041b7d0 | none (log scope only) |
| +0x08 | `ConnectionFailed` (T 100087e0) | S 0041b8b0 | none |
| +0x0c | `ConnectionNotEstablished` (T 10008dc0): a client's connection ended before its logon was accepted (§3.7) | S 005657b0 | none: the function is a single `ret` shared by many empty virtuals |
| +0x10 | user logged in (id) | `cb_LoggedIn` S 0041eb10 | reconnector `HandleAddedConnection(id)`, then `UIS_Add(id)` (§3.7) |
| +0x14 | user logged out (id) | `cb_LoggedOut` S 0041b990 | §3.7 removal |
| +0x18 | connection lost (id) | `cb_ConnectionLost` S 0041bb20 | §3.7 removal + abort file transfer |
| +0x1c | connection closed (id) | `cb_ConnectionClosed` S 0041bcc0 | §3.7 removal + abort file transfer |
| +0x20 | data (to, from, module, type, body, size) | `cb_Received_Data` S 0041d720 | §3.6 |
| +0x24 | file received | S 0041beb0 | none |
| +0x28 | notify (message without body) | S 0041bf90 | none |
| +0x2c | LAN server added (record) | `cb_BCast_ServerAdded` S 0041dd70 | §3.3 |
| +0x30 | LAN server removed (record) | `cb_BCast_ServerRemoved` S 0041ce80 | §3.3 |
| +0x34 | LAN server updated (record) | `cb_BCast_ServerUpdated` S 0041c070 | §3.3 |
| +0x38 | LAN list complete | `cb_BCast_ListUpdated` S 0041c340 | none |
| +0x3c | ping answered (id, round trip ms) | `cb_Ping_Received` S 0041d910 | sample stored (§3.8) |

Slot `+0x00` is the face's deleting destructor (S 0041e270). The slot each TinCat event calls is read from the
`TinCat_CTRL` function that fires it: T 100089b0 (`+0x10`), T 10008ab0 (`+0x14`), T 10008ba0 (`+0x18`),
T 10008c90 (`+0x1c`), T 1000aa80 (`+0x20`, `+0x28`), T 10008e50 (`+0x24`), T 100092b0 / T 100093b0 / T 100094b0 /
T 10009580 (`+0x2c`..`+0x38`), T 10009070 (`+0x3c`) [known]. No timer or state of the game is attached to the
three connect events, so a failed connect is seen only through the return value of `ConnectToServer` (§3.4).

### 2.7 TinCat API and value slots used by the transport

`TinCat_CTRL` vtable T 1004cfcc and `TinCat_Values` vtable T 1004cf2c [known, vtable bytes]:

| Object, slot | Function | Used for |
|---|---|---|
| API +0x08 | `TinCatAPI_Init(mode, moduleId, port, valuesArg, usePhase)` T 10007ed0 | start-up |
| API +0x10 | `TinCatAPI_RegisterCallbacks` T 1000a7c0 | start-up |
| API +0x28 | `Process` T 10008420 | every frame |
| API +0x30 | `TinCatAPI_MessagePollCount_Set` T 10008630 | start-up |
| API +0x3c | `NetworkService_Init(values)` T 1000a480 | start-up |
| API +0x40, +0x0c, +0x04 | `NetworkService_Remove`, `TinCatAPI_Remove`, delete | `ShutDown` S 0041cc20, in this order |
| API +0x4c, +0x54 | `LOG_Enable`, `LOG_SetDirectory` | only when the game's log level is above 0 |
| API +0x5c | mode getter (1 server, 2 client) | `Disconnect` S 0041a2e0 |
| API +0x64, +0xe4 | `Mode_UserMaxHandling_Set`, `User_SetMax` | `CloseSession` S 0041a520 |
| API +0x74 | `ConnectToIP(ip0, ip1, ip2, ip3, port)` T 10009670 | `ConnectToServer` |
| API +0x88 | `Disconnect(id)` T 100099b0 (→ API `+0xb8` `User_LogOut` T 1000aed0, §3.7) | `Disconnect`, `KickPlayer` S 0041a620 |
| API +0x98 | `Send_Data(reserved, destId, data, size, moduleId, msgType)` T 10009c90 | send to host; reconnector messages |
| API +0x9c | `Send_DataToServer(destId, data, size, msgType)` T 10007b10 | send to all, to one |
| API +0xb0 | `Send_Ping(destId)` T 1000a2a0 | ping (§3.8) |
| API +0xb4 | `User_GetIP(id, ip0*, ip1*, ip2*, ip3*)` T 1000ae20 | reconnector, host side (§3.10) |
| API +0xdc | `User_GetConnectedCount` T 1000b7c0 | `GetUserCount` S 00418ef0 |
| API +0xf4 | `BCast_Enable(key, port, listTimeoutMs, unused)` T 1000a970 | LAN |
| API +0xf8 | LAN disable (closes the socket, clears the enable flag) T 100073b0 | LAN |
| API +0xfc | `BCast_Client_UpdateList` T 10008720 | LAN |
| API +0x100 | `BCast_Server_SetInfo(name, value)` T 100073d0 | LAN |
| API +0x104 | `BCast_Server_SetData(data, size)` T 10007450 | LAN |
| Values +0x08 | `InitDefaults(preset, mode, arg08, port)` T 1000bef0 | start-up |
| Values +0x28 | set reader batch (`+0x60`) T 10006bf0 | start-up |
| Values +0x30 | set writer batch (`+0x64`) T 10006c10 | start-up |
| Values +0x70 | set "disable Nagle" (`+0x54`) T 10006cc0 | start-up |

The name `Send_DataToServer` describes its default; with a destination argument it is a plain
`Send_Data(ownId, destId, data, size, moduleId given to Init, msgType)` where `ownId` = `0xEFFFFFCC` in server
mode and the client's user id otherwise [known, T 10007b10]. `Send_Data` uses its first argument only as a
non-zero check; the frame's From id is always computed the same way (`0xEFFFFFCC` in server mode, else the
client's user id) [known, T 10009c90].

---

## 3. Rules and algorithms

### 3.1 Which menu path starts which role

The role is the argument of `NComm_Manager::StartUpNetwork` S 0040a9a0 (`network-session.md` §3.3). Every call
site passes a literal [known: the eleven callers listed by the function's cross-references]:

| Role | Meaning | Started from |
|---|---|---|
| 0 | offline, `DummyNetwork` | campaign map (`nMenu::Main::StartCampaignMap` S 005df2c0), continue last savegame (`ContinueLastSavegame` S 005dfef0), main menu buttons (`nMenu::Main::HandleButtonClicks` S 005e27c0, three sites), free game (`nMenu::FreeGamePanel::StartFreeGame` S 005e7350), pending map (`nMenu::System::StartPendingMap` S 005d9fd0), command line `-map` / `-start` (S 00401350, S 00401420) |
| 1 | client without lobby ("LAN client") | no caller |
| 2 | host without lobby ("LAN host") | no caller |
| 3 | client of a lobby game | lobby game browser: `LobbyComm::GameServerInfo::JoinGame` S 0048d030, `JoinGameWithPassword` S 0048d0c0, `LobbyComm::GameServerConnection::OnLoggedIn` S 0048edf0 |
| 4 | host of a lobby game | lobby "create game": `LobbyComm::ServerList::CreateGameServer` S 0046aaa0 |

Roles 1 and 2 are reachable only through the reconnect functions, which map 3 → 3 and 4 → 4 and any other role
to 1 or 2 (`network-session.md` §3.3); a role 0 session has no reconnector, so they are not reached [inferred].
No front-end screen of this build offers a LAN game (`docs/subsystems.md`, "Dormant LAN multiplayer").

What differs between the LAN roles and the lobby roles in the transport: nothing. `StartUpNetwork` calls
`TinCatNetwork::StartUp(isHost, online)` with (0, 0), (1, 0), (0, 1), (1, 1) for roles 1 to 4 [known,
S 0040a9a0], and `StartUp` reads only isHost [known, S 0041e610]. The difference is made above it:

- `BroadcastGameInfo` S 004090e0 (host roles in manager states 2..4): after the GameInformation broadcast, role
  1 or 2 calls `BC_Update`, role 3 or 4 calls `LobbyComm::ServerList::UpdateGameServer` [known]. The outer test
  admits roles 0, 2 and 4 only, so of the first pair only role 2 gets there.
- `BeginGameStarting` S 0040b170 calls `BC_Stop` for role 2 [known].

**`BC_Start` (transport slot `+0x6c`), `BC_IsActive` (`+0x78`) and `BC_GetGameInfo` (`+0x7c`) have no call
site**: the only reference to each function is its vtable entry, and no decompiled function calls those slots of
the transport [known: the cross-references of S 0041aa90, S 00418f70 and S 0041b680 are the vtable data words
S 007d5960, S 007d596c and S 007d5970; inferred for the absence of a call: search of all decompiled functions
for the typed slot names, which finds `BC_Update` only in S 004090e0 and `BC_Stop` only in S 0040b170]. So even a
forced role 2 host would not announce itself: `BC_Update` returns false while the LAN mode is 0 [known,
S 0041adb0].

### 3.2 LAN discovery: the game side

All three functions are methods of the transport; the manager decides "host" and "client" for them with
`NComm_Manager::IsHost` (roles 0, 2, 4) and `IsClient` (roles 1, 3) [known, S 0041aa90].

**`BC_Start(observer)` S 0041aa90.** Stores the observer at `+0xd8`, then:

- *Host*: fills the own record (§2.3: id -1, gameName, mapName, address -1, port = `gamePort`, maxPlayers,
  connected humans), serialises it into the 0x400 buffer (§3.3; fails when the result exceeds 0x400 bytes), then
  `BCast_Server_SetInfo(gameName as C string, gamePort)`, `BCast_Server_SetData(buffer, length)`,
  `BCast_Enable("S2TNG-BC", broadcastPort, broadcastTimeout, 0)`. All succeeded: LAN mode 2, active 1, return
  true. Any failure: active 0, return false, LAN mode unchanged [known].
- *Client*: `BCast_Enable("S2TNG-BC", broadcastPort, broadcastTimeout, 0)`, then `BCast_Client_UpdateList()`;
  both succeeded: `+0xe0` = now, LAN mode 1, active 1, return true. Otherwise false with the state unchanged
  [known]. A peer that is neither (no role has this) returns false as well.

The key string is the 8 characters `S2TNG-BC` (pointer S 00879a78) [known]. `broadcastPort` and
`broadcastTimeout` are the `network.ini` values at config `+0x04` and `+0x08` (§6) [known].

**`BC_Update()` S 0041adb0.**

- LAN mode 2 (host): rebuild the own record as in `BC_Start`; LAN disable (API `+0xf8`); serialise; `SetInfo`;
  `SetData`; `BCast_Enable` with the same arguments. Success logs `BC_Update succeeded!` and returns true; the
  first failing step sets active 0, logs `BC_Update failed!` and returns false [known]. The socket is therefore
  closed and reopened on every update. The only caller is `BroadcastGameInfo`, so the record is refreshed when
  the session description changes, not on a timer [known].
- LAN mode 1 (client): if `now - (+0xe0)` &lt; `broadcastTimeout / 1000.0` seconds, return true and do nothing;
  else `BCast_Client_UpdateList()`; on success `+0xe0` = now, log `BC_Update succeeded!`, true; on failure log
  `BC_Update failed!`, false, with the active flag left as it is [known]. With the shipped value this asks for a
  new list every 10 s [inferred]. No caller reaches this branch (§3.1).
- LAN mode 0: return false [known].

**`BC_Stop()` S 0041b580.** LAN mode 0, active 0, LAN disable; when that succeeds the observer is cleared
[known].

**`BC_GetGameInfo(serverId, out)` S 0041b680.** Copies the map entry with that key into `out`; false when the
key is not in the map [known].

**List maintenance** (TinCat callbacks, `this` = the callback face) [known]:

- *Added* S 0041dd70: build a `BCGameInfo` from the record: gameName = the record's `name` (up to its NUL), then
  `Deserialize(record.data, record.dataLen)` overwrites it with the payload's fields; address = `record.ip[0..3]`;
  port = `record.value`; serverId = the counter at `+0x34`, which is then incremented. Insert into the map under
  that id; observer slot `+0x30` (pointer to the handler's own record, which carries the new serverId) when an
  observer is set.
- *Updated* S 0041c070: build the `BCGameInfo` the same way; walk the map for the **first** entry whose four
  address dwords and port equal the new ones; keep its serverId, overwrite the entry, observer slot `+0x34`
  (pointer to the new value). No matching entry: nothing.
- *Removed* S 0041ce80: find the entry the same way; observer slot `+0x38` (the entry's serverId), then erase it.
  No matching entry: nothing.

A host is thus identified by (IPv4 address, game port). The observer interface has three methods:
`+0x30 OnServerAdded(BCGameInfo*)`, `+0x34 OnServerUpdated(BCGameInfo*)`, `+0x38 OnServerRemoved(serverId)`
[known for the slots and arguments, from the three call sites; the method names are descriptive]. No class
implementing it was found, because nothing calls `BC_Start`.

**What a LAN list row can show**: game name, map name, connected humans / maxPlayers, host address, game port;
the row's identity towards the transport is the serverId, and joining means connecting to address:port (§3.4)
[inferred from the record: these are all the fields a list entry carries]. [TODO] not established: the layout of
a LAN list row, since no screen for it exists in this build; a remake designs its own.

### 3.3 LAN discovery: wire format and the TinCat side

Transport: UDP over IPv4, one socket per instance with `SO_BROADCAST` and `SO_REUSEADDR` set and non-blocking
mode (`NET_BCastOpen` T 10032e10); a failure of any of the three, or of `bind`, closes the socket and fails the
enable [known].

**Ports** [known, disassembly of T 10032e10; `isServer` = TinCat mode 1 = the host, T 1000a970]:

| Side | Binds (`INADDR_ANY`) | Default destination |
|---|---|---|
| host (announcing) | `broadcastPort + 1` (6583) | 255.255.255.255 : `broadcastPort` |
| client (searching) | `broadcastPort` (6582) | 255.255.255.255 : `broadcastPort + 1` |

**Datagram** = 12-byte header + payload, all integers little-endian (`NET_BCastSend` T 10032fd0,
`NET_BCastReceive` T 10033140) [known]:

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 2 | magic | `0xFADE` (bytes `DE FA`) |
| 2 | 2 | channel | the TinCat module id given to `TinCatAPI_Init`: `0x27d9` for the match transport |
| 4 | 4 | payloadLen | number of bytes after the header |
| 8 | 4 | crc | CRC-32 of the whole datagram with this field zero |
| 12 | payloadLen | payload | |

The CRC is the table-driven CRC-32 with the reflected polynomial `0xEDB88320`, **initial value 0 and no final
inversion** (`CRC32_Compute` T 100342a0) [known]; it is not the zlib value.

A received datagram is accepted only when it has at least 12 bytes, `payloadLen` = received length - 12, the
channel equals the local one, the magic matches and the CRC matches; and it must fit the caller's buffer.
Everything else is dropped without a reply [known]. The sender's address is taken from `recvfrom`: four octets
and the port word as received, and a reply is sent to exactly those [known, T 10033140, T 10033090]. The largest
payload either side sends or accepts is 0x45c bytes (`TinCatBCast::Open` T 1000c570 passes 0x45c as the limit;
the receive buffer is 0x45c + 12 bytes) [known].

**Query** (client → broadcast): payload = 32 bytes, the key as a C string in a 32-byte field (`S2TNG-BC`, NUL
terminated, stored by `TinCatBCast::SetQueryKey` T 1000c0b0 with `BL_StrCopySafe(…, 0x20)`)
(`TinCatBCast_ClientRequestList` T 1000c510) [known]. The bytes after the terminator are zero:
`BL_StrCopySafe` T 10034180 is `strncpy(dst, src, 0x20)`, which fills the rest of the field with NULs, plus a
forced NUL in the last byte when the source is too long [known]. Keys are compared with
`strncmp(…, 32)`, which stops at the terminator [known]. A request with an empty key fails [known].

**Reply** (host → the query's source address and source port, unicast; `TinCatBCast_ServerPoll` T 1000c1c0,
`NET_BCastSendTo` T 10033090): payload = 0x45c bytes [known]:

| Offset | Size | Field | Host writes | Client uses |
|---|---|---|---|---|
| 0x00 | 32 | key | the key | must equal the local key |
| 0x20 | 32 | name | gameName, truncated to the field (`BL_StrCopySafe(…, 0x20)`) | initial gameName of the entry |
| 0x40 | 4 | value | `gamePort` | game port; part of the entry's identity |
| 0x44 | 16 | ip[4] | 0 | ignored: replaced by the datagram's source address, one octet per dword |
| 0x54 | 4 | tick | 0 | ignored: replaced by the local `GetTickCount()` at reception |
| 0x58 | 4 | dataLen | length of the serialised `BCGameInfo` (≤ 0x400) | clamped to 0x400 when an existing entry is updated |
| 0x5c | 1024 | data | the serialised `BCGameInfo`, rest zero | passed to `BCGameInfo::Deserialize` with `dataLen` |

The fields from `name` on are a `TinCatBCastRecord` (0x43c bytes; `SetServerInfo` T 1000c100 replaces name,
value, ip and tick and keeps the data, `SetServerData` T 1000c190 replaces dataLen and data) [known]. The API
call `BCast_Server_SetInfo` T 100073d0 builds its record zeroed with only name and value set, which is why ip and
tick are 0 on the wire; `BCast_Server_SetData` T 10007450 ignores a call with more than 0x400 bytes [known]. The
client clamps `dataLen` only when it updates an existing entry: a first reply's `dataLen` is stored as received
and handed to `Deserialize` unchecked [known, T 1000c250]; a remake rejects a reply whose `dataLen` exceeds
0x400.

**`BCGameInfo` serialisation** (`Serialize` S 00419330; strings = u16 length + bytes, no terminator, as in
`network-session.md` §3.2) [known]:

| Order | Field | Size | Host value |
|---|---|---|---|
| 1 | serverId | 4 | `0xFFFFFFFF` |
| 2 | gameName | string | |
| 3 | mapName | string | |
| 4 | connected humans | 4 | |
| 5 | maxPlayers | 4 | |
| 6..9 | address octets | 4 × 4 | `0xFFFFFFFF` each |
| 10 | game port | 4 | `gamePort` |
| 11 | trailing string | string | empty (2 zero bytes) |

`Deserialize` S 004194a0 reads the same order and reads field 11 only when bytes remain; it always returns true
[known]. The receiver then overwrites serverId, address and port (§3.2), so fields 1 and 6..10 of the payload
have no effect [known].

**Host behaviour** (`TinCatBCast_ServerPoll`, once per `TinCat_CTRL::Process`, i.e. once per frame while LAN is
enabled, T 10008420, T 100074e0) [known]: read at most one datagram; if its payload is exactly 32 bytes and
equals the key, send the reply to the sender (nothing is done while the key is empty). The host never sends
unasked: there is no periodic announcement. The poll is chosen by the TinCat mode: mode 1 runs the server poll,
mode 2 the client poll (T 100074e0).

**Client behaviour** [known, `TinCatBCast::ClientPoll` T 1000c250, `TinCatBCast_ClientRequestList` T 1000c510]:

1. `BCast_Client_UpdateList`: if a request is already running, do nothing and succeed; else broadcast the query
   and store `requestTick = GetTickCount()`.
2. While a request is running, once per `Process`:
   - if `GetTickCount() - requestTick > listTimeoutMs` (`broadcastTimeout`, 10000 ms): every list entry whose
     last-seen tick is older than `requestTick` is reported *removed* and deleted; the request ends
     (`requestTick = 0`); the *list complete* event fires;
   - else read at most one datagram; it must have exactly 0x45c payload bytes and the right key. If an entry
     with the same source address and `value` exists: last-seen = now, name and data replaced, event *updated*.
     Otherwise a new entry (a copy of the record with ip and tick replaced) is appended and *added* fires. The
     source port is not part of the comparison.
3. With no request running, incoming replies are not read.

So one refresh cycle lasts `broadcastTimeout` ms, a host that did not answer during a cycle is dropped at its
end, and at most one reply is taken per frame [known]. `GetTickCount()` returning exactly 0 at the moment of a
request would leave the request "not running" [inferred; harmless].

`BCast_Enable` T 1000a970 needs the TinCat state "initialised + callbacks + network service" (flags `0xb`),
opens the socket (closing any earlier one) as host when the TinCat mode is 1 and as client otherwise, stores the
key and routes the list events to the callback interface slots `+0x2c..+0x38` (`TinCatCtrl_BCastEventRouter`
T 1000a930: event 1 added, 2 updated, 3 removed, no record = list complete) [known]. The state bits are
1 = initialised (`TinCatAPI_Init`), 2 = callbacks registered, 4 = connected (set by `NetworkService_Init` in
server mode at once), 8 = network service [known, T 10007ed0, T 1000a7c0, T 1000a480; the client-side setter of
bit 4 is not read].

### 3.4 Creating the TinCat server or client for a match

`NComm::TinCatNetwork::StartUp(isHost, unused)` S 0041e610, in this order [known]:

1. Fail if an API object already exists. `TinCat_CreateAPI()`.
2. If the game's log level is above 0: set the TinCat log directory (when the configured one is not empty) and
   enable logging (API `+0x54`, `+0x4c(0)`).
3. `TinCatAPI_Init(mode, 0x27d9, port, 0, 1)`: host → mode 1 with `gamePort`; client → mode 2 with the
   `ConnectionSettings` port (`network-session.md` §3.1). The last argument asks for TinCat's "PHASE" helper
   library. Failure → `ShutDown`, false. The port given here only fills TinCat's default values object, which
   step 6 replaces [known, T 10007ed0, T 1000a480].
4. `TinCatAPI_RegisterCallbacks(this + 4)`; `TinCat_CreateTinCatValues()`. Failure → `ShutDown`, false.
5. Values: `InitDefaults(0, mode, 0x27d9, gamePort)` (preset 0 of the mode's table, §6.2; **`gamePort` for both
   modes**), "disable Nagle" = 1, reader batch = 500, writer batch = 500.
6. `NetworkService_Init(values)` (registers the values, creates the driver and its threads). Failure →
   `ShutDown`, false.
7. `TinCatAPI_MessagePollCount_Set(500)`: at most 500 received frames are handed to the game per `Process` call
   (T 10008630 stores the count, `PROGFLOW_NET::Process` T 10001800 passes it to `ProcessMessages`; the library
   default is 10 [inferred: last argument of the `Init` call in the constructor T 10006b40]).
8. Host only: local net id = `0xEFFFFFCC`; append the local user to the user list (local player name, net id
   `0xEFFFFFCC`, the manager's local GUID at manager `+0x32c`, connection type = user profile `+0x94`,
   `+0x38` = -1.0).
9. Clear the two reconnect latches (`+0x38`, `+0x39`); `StartReconnector(gamePort)` (vtable `+0x98`,
   S 00418fd0): deletes an earlier `TinCatReconnector`, creates a new one and calls
   `TinCatModules::Reconnector::Init(api, callbacks, gamePort)`. Its result is not checked by `StartUp`.
10. Create the `S2TftpManager` (`docs/s2tftp.md`). Return true.

What TinCat does with it [known unless tagged]:

- The module id `0x27d9` (10201) is stored and prefixed to every application message (§3.5); it is also the
  LAN channel (§3.3). It is not a port.
- `NetworkService_Init` starts a driver (`NETDRV_Init` T 100029d0) with the registered values' port (values
  getter `+0x10` = the port field, T 1000cc60) and user limit (getter `+0x1c` = `usrMax`), i.e. `gamePort` and
  5000 [known]. In both modes the driver has a master thread (`NETDRV_ServerThreadProc` T 100026c0) and one
  reader and one writer thread per connection (`NETDRV_ReaderThreadProc` T 10001fc0, `NETDRV_WriterThreadProc`
  T 10002390). Received frames are queued and handed out on the game thread by `Process` [known].
- **Only a mode 1 driver listens.** Its master thread opens a TCP socket bound to `INADDR_ANY`:`gamePort` with
  `listen` backlog 5 and `SO_REUSEADDR` set to 0 (`NET_CreateListenSocket` T 100327a0), and accepts
  connections; in mode 2 the same thread opens no socket and only watches the reader threads for a lost
  connection [known, T 100026c0]. A client therefore cannot be connected to before it has restarted as a host
  (`network-session.md` §3.9) [inferred].
- `TCP_NODELAY`: the driver's "disable Nagle" flag (`+0xb8`) is 0 after `NETDRV_Init` and is written only by the
  two connect calls (`ConnectToIP` T 10009670, `ConnectAsyncToIP` T 10009870), which a server-mode instance
  refuses. The accept path sets the option only when that flag is 1 (`NETDRV_ServerLookForNewConnection`
  T 10001e70). So the value "disable Nagle" = 1 of step 5 takes effect on a client's socket and **not on the
  host's accepted sockets** [known for the writers of the field: search of all decompiled library functions].
  Both sockets a host accepted in a two-player room (a join and a rejoin, `accept` called from T 10032996) read
  `TCP_NODELAY` = 0 by `getsockopt`, and no `setsockopt(IPPROTO_TCP, TCP_NODELAY)` call was made: Nagle stays
  on for the host's connections [live, 2026-10-14].
- The user limit after start-up is the preset's 5000 (`usrMax`); the six-slot limit is enforced by the session
  layer, not by TinCat [known for the value, §6.2; inferred for the consequence].

**Connecting** (`ConnectToServer(ipOctets, port)` S 0041a1b0 → `TinCat_CTRL::ConnectToIP` T 10009670) [known]:
port -1 means `gamePort`. The call is refused in server mode and needs the TinCat state `0xb`. It opens a
blocking TCP connection, sets `TCP_NODELAY` when "disable Nagle" is 1, sends the logon request and then **blocks
the calling thread**, pumping `Process` and sleeping `connectPollSleepMs` (50 ms) per round, until TinCat's
count of accepted logons has grown or `connectTimeoutMs` (30000 ms) has passed. Every failure (server mode,
wrong state, bad port, connect or send failure, timeout) returns -1; success returns the assigned user id
(§2.2). A result of -1 makes `ConnectToServer` return false; any other result is stored as the local net id.

**Logon exchange** (TinCat kernel frames, §3.9) [known]:

| Step | Frame type | From → To | Payload (0x34 bytes) |
|---|---|---|---|
| client → host | 3 `LOGMEON` | `0xEFFFFFEE` → `0xEFFFFFCC` | u32 `0xDABAFBEF`; u32 id = `0xEFFFFFEE`; char name[32] = `user`; char password[8] = `passwor` (the constant `password` cut to 7 characters); u32 flags (bit 0 set, other bits not initialised) |
| host → client | 5 `LOGONACCEPTED` | `0xEFFFFFCC` → the new id | u32 `0xDABAFBEF`; u32 id = the assigned user id; name[32] = the stored name; password[8] = `-`; u32 flags |

(`KRNL_SendLogonRequest` T 10004660 with the constants at T 1005e150 / T 1005e158; `KRNL_LogClientOn`
T 10005a60; `KRNL_OnLogonAccepted` T 10004d90; record layout `NETUSR_SetUserAddr` T 10006210: name and password
are copied up to their terminator, so the bytes behind it are not initialised either.) The host does not check
name or password; it assigns the id (§2.2), marks the connection logged on and fires *user logged in(id)*
locally. When no id or address record is free it logs `ID System refused Logon` and sends no reply; the
connection is then dropped by the logon check below. The client adopts the id from payload offset 4, starts its
keep-alive timer (§3.8) and fires *user logged in(own id)* [known].

A host drops a TCP connection that has not logged on within `usrLogonCheck` = 10000 ms
(`KRNL_LogonCheckTimer` T 10004130, armed in `KRNL_InitUser` T 10004fb0), and closes a new connection at once
when the user count has reached the user limit [known].

**Closing to newcomers** (`CloseSession` S 0041a520, called by `BroadcastStartLoading` S 0040fe50; nothing
when no API object exists): `User_SetMax(0)` then `Mode_UserMaxHandling_Set(1)` [known]. Both end in
`NETDRV_SetUserMaxHandling` T 10001c70: the first sets the driver's user limit to 0 and leaves the handling mode
alone, the second sets the handling mode to 1 and leaves the limit alone [known, T 1000b6e0, T 10008470]. The
two handling modes differ in where a surplus connection is turned away [known, T 10001b00, T 100026c0,
T 10004fb0]:

- mode 0 (after start-up): the listening socket stays open; a connection that arrives while the user count has
  reached the limit is accepted and closed at once by `KRNL_InitUser` ("maximum reached");
- mode 1: while the user count has reached the limit, `NETDRV_CheckAcceptConnections` is false, and the master
  thread **closes the listening socket**; it opens it again when the check passes.

With limit 0 the check never passes again, so from `CloseSession` on the host no longer listens on `gamePort`
and a connection attempt is refused by the operating system [inferred from the three functions]. The existing
connections are not touched.

**Disconnecting** (`Disconnect(id)` S 0041a2e0) [known]: on the host, id `0xEFFFFFCC` or `0xEFFFFFEE` shuts the
whole transport down (`ShutDown`: reconnector deleted, user list cleared, TinCat removed, local net id
`0xEFFFFFEE`), any other id is passed to TinCat `Disconnect`; on a client, the own id or `0xEFFFFFEE`
disconnects from the host (TinCat `Disconnect(own id)`) and sets the local net id to `0xEFFFFFEE`, other ids are
ignored (true). A failing TinCat call logs `Could not disconnect user!` / `Disconnecting from server failed!`
and returns false. `KickPlayer(id)` S 0041a620 is TinCat `Disconnect(id)` with the result ignored. What TinCat
`Disconnect` does on the wire and which events follow: §3.7.

### 3.5 Application message format and routing

An application message is a TinCat frame of type 2 (`CUSTOMDATA`, §3.9) whose payload is
(`TinCat_BuildModulePayload` T 10006a80) [known]:

| Offset | Size | Field |
|---|---|---|
| 0 | 2 | module id |
| 2 | 2 | message type |
| 4 | n | body |

Module / type pairs on a match connection [known]:

| Module | Type | Body | Handled by |
|---|---|---|---|
| `0x27d9` | 1000..1003 | session data (`network-session.md` §3.1) | the game (`cb_Received_Data`) |
| `0x61` (97) | `0x5e7b` | reconnector message (§3.10) | `Reconnector::HandleReceivedData`, called by the game |
| `0x63` (99) | `0x5a89` | ping (§3.8) | TinCat itself; never reaches the game |

`Send_Data` refuses an empty body (error 2) and a first argument or destination of 0 (error -0x1e), and needs
the TinCat state `0xf` (initialised, callbacks, connected, network service) unless the destination is
`0xEFFFFF88` [known, T 10009c90]. The four game-side send functions return true without sending when the data
pointer is null or the size is 0 [known].

**Routing** is done by the frame header's From and To ids. The session is a star; a client has exactly one
connection [known: `KRNL_SendMessage` T 10003cc0, `KRNL_SendToAllUsers` T 10003bc0, `KRNL_RouteCustomData`
T 10005140]:

| Sender | Destination | What happens |
|---|---|---|
| host | `0xEFFFFFDD` | one frame per logged-on user, From `0xEFFFFFCC`, **To = that user's id**. Not delivered to the host itself |
| host | a user id | one frame to that user; fails when no user has the id |
| client | anything but `0xEFFFFF88` | one frame to the host with From = own id and To = the destination as given |
| either | `0xEFFFFF88` | no socket: the frame goes to the local receive queue and is delivered to the own application |
| host receives To `0xEFFFFFCC` (or `0xEFFFFF88`) | | delivered to the host's application |
| host receives To `0xEFFFFFDD` | | re-sent to every logged-on user **except the sender**, From kept, To = each user's id; then also delivered to the host's application (not when the re-send failed) |
| host receives To = another id | | re-sent to that user, From and To kept; not delivered to the host. An unknown id fails (`distritbute CUSTOMDATA failed` in the log) and the message is lost |
| client receives anything | | delivered to the application with the header's To and From; a client never relays (T 100012f0 routes only in mode 1) |

So a client's message "to all" or "to another client" is **relayed by the host**; there is no connection between
clients. A sender never receives its own broadcast back, which is why `NComm_Manager::BroadcastEvent` handles
the event locally as well (`network-session.md` §3.1). The relay copies the payload and does not inspect it; it
does not check that From is the id of the connection the frame came in on [known: `KRNL_RouteCustomData` passes
the header's From on unchanged].

The transport's four send functions map onto this as follows [known]:

| Transport slot | Function | TinCat call |
|---|---|---|
| +0x18 | `SendToHost` S 0041db50 | `Send_Data(localNetId, 0xEFFFFFCC, data, size, 0x27d9, type)` |
| +0x1c | `SendToAll` S 0041dbb0 | `Send_DataToServer(0xEFFFFFDD, data, size, type)`; skipped (true) on a host with user count 0 |
| +0x20 | `SendTo` S 0041dc30 | `Send_DataToServer(target, data, size, type)` |
| +0x24 | `SendToFirstPeerExcept` S 0041dc90 | `Send_DataToServer(first listed user ≠ except and ≠ 0xEFFFFFCC, …)` |

`SendToFirstPeerExcept` returns false when the user list has no such entry. `GetUserCount` is the length of
TinCat's connection list (`NETUSR_GetUserCount` T 10006390): on the host it does not include the host, and it
does include a connection that has not logged on yet [known for the count; inferred for the two consequences;
the host's own user list entry is separate, §3.7].

### 3.6 Receiving

`TinCat_CTRL::Received_Data` T 1000aa80 (state `0xf` required unless To is `0xEFFFFF88`) splits module and
type, answers pings itself, and calls callback slot `+0x20` with (to, from, module, type, body, body length) for
a body of at least one byte, or slot `+0x28` (to, from, type) for an empty one [known]. Module `0x62` is
diverted to registered extensions and dropped when none matches; the match transport registers none [known for
the diversion; inferred for the absence: `StartUp` calls no `RegisterExtension`].

`cb_Received_Data` S 0041d720 [known]:

1. If a reconnector exists: `Reconnector::HandleReceivedData(to, from, module, type, body, size)`. Its return
   value is compared with 1, but **the function returns 0 on every path** (disassembly T 10010a30), so the
   message always continues to step 2.
2. Module ≠ `0x27d9`: ignored (this drops the reconnector messages after step 1 has processed them).
3. Dispatch by type 1000..1003 (`network-session.md` §3.1; 1003 only while the `S2TftpManager` exists; any other
   type does nothing); then record the traffic (from, to, incoming, size).

Messages are delivered on the game thread, inside `TinCatNetwork::Process` → `TinCat_CTRL::Process`, in the
order the reader threads queued them, at most 500 per call [known, T 100012f0, step 7 of §3.4]. Order between
two different senders is the queueing order of two threads and is not defined beyond that [inferred].

### 3.7 The user list and its events

The user list (`+0x14`) is the transport's own table of who is in the session; it is filled from two sources.

| Event | Function | Effect |
|---|---|---|
| start-up on a host | S 0041e610 | entry for the local user: name, `0xEFFFFFCC`, GUID, connection type |
| TinCat *user logged in(id)* | `cb_LoggedIn` S 0041eb10 → `UIS_Add` S 0041e990 | reconnector first (§3.10; a failure is only logged). If an entry with the id exists it is removed through `UIS_Remove(id, 0)`, with all its effects; then an entry with only the net id is appended (name empty, GUID 0, level 0) |
| session event 0x30001 and its replies | `UIS_SetUserData(id, name, guid, level)` S 0041a720 (transport slot `+0x50`) | entry found by net id: name, GUID, level written, `+0x38` = -1.0; then `NComm_Manager::BroadcastUserListText` (0x30008). False when no entry has the id |
| ping answer | `UIS_AddPingSample` S 0041d610 | §3.8 |
| TinCat *logged out*, *connection lost*, *connection closed* | S 0041b990, S 0041bb20, S 0041bcc0 | below |

On the **host**, *user logged in* fires once per client with the client's id. On a **client** it fires once, with
the client's own id, when its logon is accepted; a client's list therefore holds its own entry, and entries for
the others only if the session layer adds them [known for the callback; the session-level writers are in
`network-session.md` §3.5].

**Removal** [known]: each of the three handlers first calls `Reconnector::HandleRemovedConnection(id)` (when a
reconnector exists):

- returns 1 and the `TinCatReconnector` state (`+0x0c`) is non-zero → nothing else: a host change is under way
  and the list is kept;
- returns 1 and the state is 0 (the normal case on a host) → removal;
- returns anything else → log `Reconnector could not handle LOGGED OUT / LOST / CLOSED connection!`, then
  removal.

Removal = `UIS_Remove(id, flag)` S 0041d4c0 (the flag is not read; *logged out* passes 0, *lost* 1, *closed* 1
when the user's GUID is valid and not yet in the manager's list of left players, else 0), and for *lost* and
*closed* also `CancelFileTransfer(id)` (transport slot `+0xa8`, S 00419130: on a connected client it aborts the
transfer with `0xEFFFFFCC` whatever the id, otherwise the transfer with that id). `UIS_Remove`: on a connected
client (local net id not `0xEFFFFFCC`, `0xEFFFFFEE` or 0) whose own id is the removed one, only the local net id
becomes `0xEFFFFFEE`; otherwise the ping samples of the id are dropped, the GUID is read, and the entry is
erased (`UIS_RemoveUserData` S 0041cd40, which broadcasts the user list text). When no entry has the id the
function stops there and returns false; else `NComm_Manager::HandlePlayerLeft(guid, id, -1, false)` runs
(`network-session.md` §3.10), and a local net id equal to the removed id becomes `0xEFFFFFEE`.

Which TinCat event fires when [known unless tagged]:

- A socket error, a closed socket, a failed allocation or a CRC mismatch seen by a reader thread (§3.9) raises
  a flag that the master thread turns into an internal "remove user" message (`NETDRV_ServerLookForFlags`
  T 10001870, frame type 8). Its handler `KRNL_RemoveUser` T 10005d30 fires *connection closed(id)* if the
  connection had logged on; on a client whose logon was never accepted it fires "not established" instead; on
  the host a connection that never logged on is removed without an event. Then the id is released and the
  connection destroyed.
- The host's dead-connection check (§3.8) fires *connection lost(id)* for a logged-on connection and queues the
  same "remove user" message, so *connection closed(id)* follows on a later `Process`
  (`KRNL_ConnectionLost` T 10004f00, `KRNL_SendUsrRemoveMessage` T 10003a80).
- **TinCat `Disconnect(id)` sends nothing.** It needs state `0xf` and calls `User_LogOut(id)` T 1000aed0, which
  looks the connection up by id and calls `KRNL_RemoveUser` directly: *connection closed(id)* fires on the
  calling side inside the call, and the socket is closed. The other side learns of it through its reader thread
  (first bullet) and fires *connection closed* too [known for the calling side; inferred for the other side].
  So a kick fires `cb_ConnectionClosed(id)` on the host before `KickPlayer` returns, and a client that
  disconnects fires `cb_ConnectionClosed(own id)` on itself.
- *Logged out* belongs to the `LOGMEOFF` exchange: a host that receives frame type 4 fires *logged out(id)*,
  answers with type 6 and stops that connection's reader (`KRNL_LogClientOff` T 10005bd0). No function of
  `tincat3.dll` sends type 4: the two send primitives are called with types 2, 3, 5, 6, `0xB`, `0xC` and `0xE`
  only [known: all call sites of `KRNL_SendSingleMessage` T 10003b20 and `KRNL_SendMessage` T 10003cc0]. Between
  two instances of this library *logged out* therefore never fires, and `cb_LoggedOut` S 0041b990 is not
  reached [inferred].

Queries on the list [known]: `HasUser` S 004197b0, `GetUserNetIdByIndex` S 00419740, `GetUserGUID` S 00419800,
`GetUserLevel` S 00419880, `UIS_GetUserName` S 0041a8d0, `GetMinUserLevel` S 004198e0 (minimum of all levels,
3 when none is lower or the list is empty), `GetUserPing(id, wantMax)` S 004199b0 (newest sample, or the larger
of the stored samples) [known for the lookups by net id]. `GetUserGUID` and `UIS_GetUserName` return an all-zero
GUID and an empty string for an unknown id [known]. `GetUserNetIdByIndex` returns 0 for an index past the end
(not `0xEFFFFFEE`), `GetUserLevel` 0 for an unknown id, `GetUserPing` 0 for an unknown id [known, disassembly
of the three]. For a user without samples `GetUserPing(id, true)` returns 0 (`NCommUserRecord_GetMaxSample`
S 004196e0), while `GetUserPing(id, false)` dereferences the empty list's first node: the checked-iterator
failure routine S 006f2702 is called, which ends the process with exit code 0xC000000D (no invalid-parameter
handler is installed, `military.md` §3.2) [known]. A remake returns 0.

### 3.8 Keep-alive, ping and timeouts

Three mechanisms, at two levels.

**1. Session ping** (`NComm_Manager::Process_MainLoop` S 00410f70) [known]: when more than the ping period has
passed since the last one (manager `+0x24`), the manager calls transport slot `+0x84` (S 00418f80; the map's
name `FlushPending` describes nothing it does). The period is the manager field `+0x370` (`pingFrequencyGame`)
in manager state 4 and `+0x36c` (`pingFrequencyMenu`) otherwise (§6.1). No ping is sent in manager state 3
(game starting) or while the manager's reconnect state (`+0x00`) is not 0: the function returns before the
check. The slot sends a TinCat ping: a host (local net id `0xEFFFFFCC`) with at least one connection pings
`0xEFFFFFDD` (every user); otherwise a connected client (local net id not `0xEFFFFFCC`, `0xEFFFFFEE` or 0)
pings `0xEFFFFFCC` (the host) [known].

Ping message = module 99, type `0x5a89`, 12-byte body (`Send_Ping` T 1000a2a0, `Received_Ping` T 10009070)
[known]:

| Offset | Size | Field | Request | Answer |
|---|---|---|---|---|
| 0 | 2 | magic | `0x5a89` | same |
| 2 | 2 | phase | 0 | 1 |
| 4 | 4 | peer id | the destination id | the answering peer's own id (`0xEFFFFFCC` on the host) |
| 8 | 4 | tick | sender's `GetTickCount()` | echoed |

The receiver of a request rewrites it in place and sends it back with From = the request's To and To = the
request's From. The receiver of an answer computes `GetTickCount() - tick` and reports (peer id from the body,
milliseconds) through callback `+0x3c`. The game stores the value at the front of that user's sample list and
trims the list to 2 (`UIS_AddPingSample` S 0041d610); a peer id without a user list entry is ignored [known].
Because the host's broadcast is sent as one frame per user with To = that user's id (§3.5), each client answers
from its own id; the host's answer to a client carries peer id `0xEFFFFFCC`, so a client stores a sample only
if its list has an entry with that id [known for the ids; the client's list content is the session layer's,
§3.7]. Both directions need the TinCat state `0xf`.
The unit of a sample is milliseconds of `GetTickCount` [known]. The samples are read by the net tick length
adaptation (`docs/sim/logic-core.md`, "latency `L`": the largest sample over all users) and by the network info
panel; this ping is the request that feeds them. Nothing in the transport disconnects on a missing answer
[known: no timer is attached to a ping].

**2. TinCat keep-alive** [known]: after its logon is accepted, a client sends a frame of type `0xB`
(`STAYINGALIVE`, From = own id, To = `0xEFFFFFCC`, 2 payload bytes of no meaning) every `srvSendAlive` =
180000 ms (`KRNL_SendAliveMessage` T 100041b0, armed in T 10004d90 with the driver's `+0x58`). The host's
message loop does nothing with it (a log line at verbose level 2, T 100012f0); like every valid frame it
refreshes the connection's "last received" stamp of mechanism 3.

**3. Dead-connection check** [known]: on the host only (the timer is registered only in driver mode 1,
T 100029d0), every `srvCheckDeadCallTime` = 60000 ms, `KRNL_CheckDeadConnections` T 10005de0 drops every
connection whose last received frame is older than `srvCheckDeadCon` = 400000 ms. "Last received" is stamped by
the reader thread on every valid frame of any type (`NETDRV_UpdateCondataStatistics` T 10001aa0). A dropped
connection gets *connection lost* and then *connection closed* (§3.7). With the session ping answered every 2.5
to 10 s, a healthy peer never comes near that limit; a peer that stops sending without closing its socket is
dropped after 400 to 460 s [inferred from the two periods].

A **client** has no such timer: it notices the loss of the host only when its socket reports an error or the
end of the stream [known: no dead check in mode 2]. The session layer's own waiting rules (hang display, leave
timeout, reconnect timers) are in `network-session.md` §3.9, §3.10 and `docs/sim/logic-core.md` §3.2.

Other TinCat timers that matter [known, values §6.2]: logon check 10000 ms (§3.4), connect timeout 30000 ms
(§3.4), reader, writer and server-loop sleep 20 ms each while idle.

### 3.9 Frame format and message size

Every TCP message is a 28-byte header followed by the payload, little-endian (`NET_SendPacket` T 100325e0,
`NET_ReceivePacket` T 10032670; the same header as on the lobby connection, `docs/LOBBY_PROTOCOL.md` §3.1)
[known]:

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 4 | magic | `0xDABAFBEF` |
| 4 | 4 | From | net id (§2.2) |
| 8 | 4 | To | net id |
| 12 | 4 | type | below |
| 16 | 4 | (unused) | not written by the send path (the envelope allocator T 10032480 leaves it uninitialised) and not read by the dispatcher. The host's relay hands the received value to `KRNL_SendMessage`, which does not use it, so a relayed frame does not carry it on. A remake sends 0 and ignores it |
| 20 | 4 | payloadSize | |
| 24 | 4 | crc | `CRC32_Compute(payload)`: polynomial `0xEDB88320` reflected, initial value 0, no final inversion |

Frame types (`PROGFLOW_NET::ProcessMessages` T 100012f0) [known]: 1 `TIMESYNC` (logged only), 2 `CUSTOMDATA`
(application message, §3.5), 3 `LOGMEON`, 4 `LOGMEOFF`, 5 `LOGONACCEPTED`, 6 `LOGOFFACCEPTED`, `0xB`
`STAYINGALIVE`, `0xC` `FILE`, `0xE` `GROUPDATA`; 8 and 9 exist only inside the library (remove user, new
connection); any other value is logged as unknown and dropped. Types 3 and 4 are accepted only by a server-mode
instance, 5 and 6 only by a client-mode one; the wrong side logs and drops them. The match uses 2, 3, 5 and
`0xB`; a disconnect sends no frame (§3.7).

Receive rules [known, T 10032670, T 10001fc0]: a header of fewer than 28 bytes, a wrong magic or a payload
shorter than announced is logged ("no effect") and the reader goes on (the stream is then out of step); a CRC
mismatch, a socket error, a closed socket or a failed allocation stops the reader and the connection is
removed (§3.7). A frame with payload size 0 cannot be sent as an application message (`Send_Data` refuses it).

**Maximum size.** The frame has a 32-bit length and the receiver allocates exactly `payloadSize` bytes with no
upper bound [known, T 10032670]; a sender's body is copied whole. Payloads are sent and received in chunks of
4096 bytes [known: the driver's `+0xe8` is the chunk argument of `NET_ReceivePacket` (T 10001fc0); it is filled
from the values getter `+0x78` = `bufWriteBlock`, T 10001090, T 100029d0; inferred for the send side, whose
writer thread is not read]. So the transport sets **no limit** a match can hit; the limits are the
session layer's: a tick package grows as needed (`network-session.md` §2.6), an S2TFTP packet has its own block
size (`docs/s2tftp.md`), the LAN payload is at most 0x400 bytes inside a 0x45c-byte datagram payload (§3.3).

Delivery guarantees the session relies on [inferred from TCP plus one writer queue per connection]: frames from
one sender to one receiver arrive complete, unmodified and in sending order; a frame queued for a connection
that is then removed is lost without notice to the sender (`Send_Data` reports only queueing errors).

### 3.10 `TinCatModules::Reconnector`: peer list and host election

The module keeps, on every peer, the list of clients and where each could be reached if it became the host.
The game calls only its constructor, `Init`, `HandleAddedConnection`, `HandleRemovedConnection`,
`HandleReceivedData` and destructor; `SetPreferredNextServer`, `SetUserData` and `GetUserData` exist in the
library but have no caller in the game [known: search of all decompiled game functions for the class's
methods finds only the six].

All its messages are application messages of module `0x61`, type `0x5e7b`, sent through `Send_Data`
(`Reconnector_SendData` T 10010550). The body starts with a u16 subtype [known]:

| Subtype | Sender → destination | Body after the subtype | Receiver |
|---|---|---|---|
| 1 | host → `0xEFFFFFDD` | none (2 bytes in all) | clear the peer list (user data kept) |
| 2 | host → `0xEFFFFFDD` | one `ReconnectorPeer`, 28 bytes: u32 state, u32 connection id, u32 × 4 IPv4 octets, u32 port (30 bytes in all) | append a copy to the peer list |
| 3 | host → `0xEFFFFFDD` | none | nothing |
| 4 | client → `0xEFFFFFCC` | u32 port (6 bytes in all) | set the port of the peer whose connection id is the message's From (no such peer: nothing changes); then publish the list. The receiver does not test that it is the host |
| 5 | any → `0xEFFFFFDD` or one id | u32 data id, u32 length, bytes | store or replace the blob with that id; length 0 deletes it. Not sent by the game |

Body lengths are not checked by the receiver, and the function handles a message only when module and type
match and the module was initialised [known, T 10010a30]. `Reconnector_SendData` passes `0xEFFFFF88` as the
first argument of `Send_Data`, which only has to be non-zero (§2.7).

**Publishing the list** (`Reconnector_BroadcastPeerList` T 10010890): subtype 1, one subtype 2 per peer in list
order, subtype 3 [known]. The host's own list is not sent to itself (§3.5) and the host is not an entry of it.

**Events** [known]:

- `HandleAddedConnection(id)` T 10010ae0. The instance becomes "host" the first time it is called while TinCat
  runs in mode 1. *Host*: append a peer {state 1, id, the address TinCat reports for that user
  (`User_GetIP`, API `+0xb4`), port = the host's own local port}; publish the list; send every stored data blob
  to the newcomer; return 1. Returns 0, with nothing published, when the address cannot be read or the entry
  cannot be stored. *Client*: remember `id` as the own connection id and send subtype 4 with the local port
  (`gamePort`, from `Init`) to the host; return 1. Without `Init` the call returns 0.
- Host receives subtype 4: the sender's port is replaced by the announced one and the list is published again.
  So after a join every client holds, for every client including itself: connection id, the IPv4 address **as
  the host saw it**, and that client's own `gamePort`.
- `HandleRemovedConnection(id)` T 10010b80. *Host*: remove that peer, publish the list, return 1. *Client* (its
  only connection is the one to the host): run the election and return its result. "Host" here is the module's
  own flag, which only `HandleAddedConnection` sets.

**Election** (`Reconnector_ElectNewHost` T 10010930, disassembly) [known]:

1. No peers known → return 0 (no host change; the game logs the failure and removes the user, §3.7).
2. The successor is the first peer in list order with state 2; if none has state 2, the **first peer of the
   list**. Since nothing sets state 2 in this game, the successor is always the first entry: the client that
   has been connected to the lost host longest [inferred from append order and the missing caller].
3. If the successor's connection id equals the own one: callback `+4` (`cb_BecameServer`: state 1, address -1,
   port 0). Otherwise callback `+8` with the successor's four octets and port (`cb_ReconnectTo`: state 2,
   address and port stored, log `Reconnecting to a.b.c.d`). Return 1.

Every client runs the same rule on the same list, so all agree, provided each has received the latest list
[inferred]. The module sends nothing during the election and does not check that the successor is reachable.

**When it triggers**: on a client, whenever TinCat reports the end of its connection (*logged out*, *connection
lost* or *connection closed* with any id), in every manager state, including the pre-game room. That includes
the client's own `Disconnect`, which fires *connection closed(own id)* inside the call (§3.7): unless the
reconnector was deleted first, a client that leaves on its own runs the election too and ends with reconnector
state 1 or 2 [inferred from T 1000aed0 and S 0041bcc0; what the caller does next is the session layer's]. What the game
then does with reconnector state 1 or 2 (polled each frame by `TinCatNetwork::Process` S 00419e10, allowed only
in manager states 3 and 4) is the session layer's state machine, `network-session.md` §3.9. On the host the
module never elects.

The address in the list is the one the old host saw. For peers behind address translation it is their public
address, and the announced port is their local `gamePort`; a rejoin works only if that pair accepts connections
[inferred].

---

## 4. Update order

Per frame, from `NComm_Manager::Process_MainLoop` → `TinCatNetwork::Process` S 00419e10 [known]:

1. `TinCat_CTRL::Process` T 10008420 (does nothing unless the TinCat state has the bits `0xb`), when an API
   object exists:
   1. `PROGFLOW_NET::Process` T 10001800, in this order: finish pending asynchronous connects
      (`KRNL_ProcessPendingConnects` T 10004ad0); run the due timer callbacks
      (`CALL_Process` T 100354c0: logon check, keep-alive, dead-connection check, alive log); hand out up to 500
      queued frames in arrival order (`ProcessMessages` T 100012f0): each either a kernel step (new connection,
      logon, removal) or an application message that ends in a callback of §2.6, executed synchronously on this
      thread. A timer callback that fires *connection lost* therefore runs before the frames of the same call.
   2. If LAN is enabled: one LAN poll (host: answer at most one query; client: at most one reply or the
      end-of-cycle sweep) (T 100074e0).
   3. A getter of the values object (slot `+0x94`, T 10006cd0: the field copied from preset `+0x80`, 0) is the
      tail call; the game ignores the result.
2. If a `TinCatReconnector` with a library module exists, poll its state: 1 → begin the manager's reconnect once
   (`BeginManagerReconnectOnce` S 00419080, latch `+0x38`); 2 → restart as client once with the stored address
   and port (`RestartAsClientOnce` S 004190b0, latch `+0x39`). When the manager refuses, `Process` returns false
   at once, without step 3, and the same step is tried again on the next frame.
3. Prune the traffic statistics (entries older than 120 s, S 00419c60); run the file-transfer queue when the
   `S2TftpManager` exists.

A false result makes `Process_MainLoop` shut the transport down and delete it, set manager state 0 and the
shutdown flag, and log `GetNetworkHandler()->Process failed!` [known, S 00410f70]. After a true result the
manager does, in this order [known, S 00410f70]: the start-loading countdown; execution of the immediate events
received in step 1 (message 1000); the reconnect state machine (manager states 3 and 4 only); and last the ping
period test of §3.8, which is skipped in manager state 3 and while the reconnect state is not 0. Details:
`network-session.md` §4.

Outside the frame [known, T 10001fc0, T 10002390, T 100026c0, T 10001870, T 10001e70]:

- a reader thread per connection blocks in `NET_ReceivePacket`, queues each valid frame for step 1 and stamps
  the connection's "last received" time; after `readerBatch` further rounds it yields once;
- a writer thread per connection sends the frames queued for it, yields after `writerBatch` frames in a row,
  and when its queue is empty waits for its wake event, at most 1 s per round;
- the master thread loops: scan all connections for a reader that reported a failure and queue the internal
  "remove user" message for each, then sleep `srvWaitForFlags` (100 ms); on a host, wait up to `srvNewConnect`
  (500 ms) for a new TCP connection and queue the internal "new connection" message for it; then sleep the
  server-loop sleep (20 ms). A broken connection is thus turned into its event up to about 0.6 s after the
  reader saw it on a host and about 0.1 s on a client, plus the wait for the next `Process` [inferred from the
  three waits].

On events: `BC_Update` after each GameInformation broadcast of a role 2 host; `BC_Stop` when a role 2 host
enters the game screen; `CloseSession` when the host broadcasts StartLoading.

On shutdown (`ShutDown` S 0041cc20): delete the `TinCatReconnector` (slot `+0x9c`, S 00419060), clear the user
list, and when an API object exists `NetworkService_Remove`, `TinCatAPI_Remove`, delete the API; local net id =
`0xEFFFFFEE` [known]. `ShutDown` does not call `BC_Stop` and does not write the LAN mode or the LAN active flag
[known]; the LAN socket goes with the API object [inferred].

---

## 5. Inputs and outputs

Consumes: role and session description from `NComm_Manager`; `network.ini` (§6.1); `ConnectionSettings` (host
address and port of a lobby game, `network-session.md` §3.1; also the TinCat log directory, used when the game's
log level is above 0); the local player name, GUID and connection type.

Produces for the session layer: the local net id; the user list and its queries; the four send functions;
received session messages 1000..1003 (the transport's From id is handed on only with 1001 and 1003, S 0041d720);
the leave notification `NComm_Manager::HandlePlayerLeft` and the user list text broadcast (0x30008) when user
data is set or an entry is erased; ping samples; the reconnector verdict (state 1 or 2 with an address). A new
connection is not reported to the manager: `UIS_Add` only appends the list entry, and the session learns of the
player through event 0x30001 (`network-session.md` §3.5) [known, S 0041e990].

Network traffic of this layer itself:

| Channel | Message | Direction | Section |
|---|---|---|---|
| UDP `broadcastPort + 1` | LAN query, 12 + 32 bytes | client → broadcast | §3.3 |
| UDP `broadcastPort` | LAN reply, 12 + 0x45c bytes | host → client | §3.3 |
| TCP `gamePort`, frame type 3 / 5 | logon | client ↔ host | §3.4 |
| frame type `0xB` | keep-alive | client → host | §3.8 |
| type 2, module 99 / `0x5a89` | ping request and answer | both | §3.8 |
| type 2, module `0x61` / `0x5e7b` | reconnector subtypes 1..4 | host ↔ clients | §3.10 |
| type 2, module `0x27d9` / 1000..1003 | session data | all | `network-session.md` §3.1, `docs/NCOMM_GAME_PROTOCOL.md` |

The lobby server sees none of it; it only supplies the host's address for a role 3 client
(`docs/MATCH_START.md`).

---

## 6. Data-driven parameters

### 6.1 `data/game/settings/network.ini`

The full table with defaults and the config offsets is in `network-session.md` §6. Keys used here, with the
values of the examined install [known, file and S 0041ede0]:

| Section, key | Value | Use |
|---|---|---|
| `[Basics] gamePort` | 5478 (code default 5479) | TCP port the host listens on; default port a client connects to; port announced by the reconnector and in the LAN record |
| `[Broadcast] broadcastPort` | 6582 | UDP base port of the LAN search (client binds it, host binds +1) |
| `[Broadcast] broadcastTimeout` | 10000 | ms: length of one LAN refresh cycle and interval between client requests |
| `[Ping] pingFrequencyMenu` | 10.0 | s between pings in every manager state but 3 and 4 (state 3, game starting: no ping) |
| `[Ping] pingFrequencyGame` | 2.5 | s between pings in manager state 4 (game running) |

The code defaults of the three integer keys are 5479, 6582 and 10000 (`GetPrivateProfileIntA` arguments)
[known, S 0041ede0]. The file of the install is plain text and starts with a UTF-8 byte order mark directly
before `[Basics]`. `GetPrivateProfileIntA` does not find a section line that follows the mark directly, so that
first section (`gamePort = 5478`) is hidden and the effective `gamePort` is 5479, from the file's second `[Basics]`
section or the code default (both 5479) [live, 2026-10-14; `network-session.md` §6].

### 6.2 TinCat values (compiled in, not a file)

The transport takes preset 0 of the server table T 1005e210 (host) or of the client table T 1005e420 (client);
the two presets have identical bytes [known, both read]. The game then changes three values (§3.4). The match
transport does not call `TinCat_Values::LoadFromIni`, so no file overrides them [known: not among the calls of
S 0041e610].

| Value | Preset 0 | After `StartUp` | Use |
|---|---|---|---|
| reader / writer sleep | 20 ms, active | same | sleep per round of a reader or writer thread while it is paused (before its resume signal, after a stop signal); not used while it runs (T 10001fc0, T 10002390) |
| server-loop sleep | 20 ms, active | same | sleep at the end of every master-thread round (T 100026c0) |
| `srvSendAlive` | 180000 ms | same | client keep-alive period; host alive-log period |
| `srvCheckDeadCallTime` | 60000 ms | same | period of the host's dead-connection check |
| `srvCheckDeadCon` | 400000 ms | same | silence after which the host drops a connection |
| `srvSendLogonRequest` | 5000 ms | same | client: `select` timeout for the socket to become ready after `connect` (`NET_Connect` T 10033310, called by `KRNL_SendLogonRequest` T 10004660) |
| `srvSendLogoffTimeout` | 10000 ms | same | host: timeout armed for a connection after its `LOGMEOFF` was answered (`KRNL_LogClientOff` T 10005bd0); not reached in a match (§3.7) |
| `srvNewConnect` | 500 ms | same | host: `select` timeout of the master thread's wait for a new connection (`NETDRV_ServerLookForNewConnection` T 10001e70, `NET_WaitForNewConnection` T 100328f0) |
| `srvWaitForFlags` | 100 ms | same | sleep of the master thread after each scan for failed readers (`NETDRV_ServerLookForFlags` T 10001870) |
| `usrLogoffTimeout` | 10000 ms | same | copied to driver `+0x68`; [TODO] no reader found in the decompiled library functions; a read breakpoint on driver `+0x68` settles whether it is unused |
| `usrLogonCheck` | 10000 ms | same | time a new connection has to log on (`KRNL_InitUser` T 10004fb0) |
| `usrInitNew` | 5000 ms | same | time the new reader and writer thread of a connection have to report "running" (`NETUSR_InitUser` T 100063c0) |
| `usrRemove` | 5000 ms | same | copied to driver `+0x60`; [TODO] no reader found, as for `usrLogoffTimeout` |
| `thrdExit` | 20000 ms | same | time a reader or writer thread has to stop when its connection is removed (T 10001f60, T 10002300) |
| `bufWriteBlock` | 4096 | same | chunk size of every socket send and receive: values getter `+0x78` → `NETDRV_Init` → third argument of `NET_SendPacket` (T 10002390) and second of `NET_ReceivePacket` (T 10001fc0) |
| `bufRw` | 4096 | same | passed to `NETDRV_Init`, which does not use the argument (T 10001090, T 100029d0) |
| reader batch | 10 | **500** | frames a reader thread takes before yielding |
| writer batch | 25 | **500** | frames a writer thread sends before yielding |
| `usrMax` | 5000 | same (0 after `CloseSession`) | user limit |
| `drvRemoveTime` | 20000 ms | same | [TODO] getter T 10006cf0 (values slot `+0x80`); no caller found in the decompiled library functions |
| thread stack sizes (reader, writer, master) | 0 each | same | given to thread creation; 0 = the system default [inferred] |
| preset `+0x80` | 0 | same | returned by the tail call of `TinCat_CTRL::Process` (§4); no other reader |
| `connectTimeoutMs` | 30000 | same | client: longest wait for the logon reply after the logon request was sent (T 10009670); the blocking `connect` before it is not covered by this timer |
| `connectPollSleepMs` | 50 | same | sleep per round while waiting for the logon |
| disable Nagle | 0 | **1** | `TCP_NODELAY` on a client's connection; not on the host's accepted ones (§3.4) [live, 2026-10-14] |
| message poll count (API; not a preset field: the `PROGFLOW_NET` constructor T 10006b40 sets 10) | 10 | **500** | frames handed to the game per `Process` |

The millisecond values from `thrdExit` to `usrLogoffTimeout` reach the driver as one block: the values getter
`+0x7c` (T 10006cb0) returns the address of `thrdExit` (values `+0x0c`), and `NETDRV_Init` copies twelve dwords
from it (`thrdExit`, then driver `+0x40..+0x68`: `srvNewConnect`, `srvSendLogonRequest`, `srvSendLogoffTimeout`,
`srvWaitForFlags`, `srvCheckDeadCon`, `srvCheckDeadCallTime`, `srvSendAlive`, `usrInitNew`, `usrRemove`,
`usrLogonCheck`, `usrLogoffTimeout`) [known, T 10001090, T 100029d0, T 1000b880]. No function of the library
calls `LoadFromIni` (values slot `+0x0c`, T 1000b960) either [known: search of the decompiled library
functions]. None of the `[TODO]` rows is a rule the session layer depends on. A join and a leave in a
two-player room did not settle them live: the getter T 10006cf0 is too short for a Frida hook, and read
watchpoints on driver `+0x60` / `+0x68` stall the game [live, 2026-10-14].

### 6.3 Code constants

[known] LAN key `S2TNG-BC`; LAN magic `0xFADE`; LAN payload limit 0x45c; LAN data limit 0x400; frame magic
`0xDABAFBEF`; match module `0x27d9`; reconnector module `0x61`, type `0x5e7b`; ping module 99, type `0x5a89`;
logon name `user`, password `password`; user ids from 1; ping samples kept 2.

---

## 7. Save and load

Nothing of this subsystem is persisted. The LAN list, the user list, the peer list and the ping samples live
only as long as the transport object [inferred: none of the transport functions read for this document writes
or reads a file]. A savegame written during a network match contains none of it and nothing of the session; the
in-game menu offers no save in a network match, and the save code itself does not depend on the network
(`docs/multiplayer-save.md`, which also records saving in a network match as seen live on 2026-10-12). The only
stored inputs are the `network.ini` keys of §6.1 [known].

---

## 8. Determinism notes

The transport does not touch simulation state. It delivers bytes; what enters the simulation is decided by the
session layer's lockstep (`network-session.md` §3.7, `docs/sim/logic-core.md` §3.2), which executes the same
packages at the same tick on every peer regardless of when they arrived.

Three transport properties are nevertheless load-bearing for determinism and must hold in a replacement:

- **Per-sender order and integrity.** A client's packages reach the host in sending order and unaltered, and the
  host's merged packages reach each client in sending order (§3.9). The session layer has no sequence numbers or
  retransmission of its own for messages 1000..1002 [inferred from `network-session.md` §3.2: a package carries
  its tick but nothing detects a lost one except the gate that waits for it].
- **No self-delivery of broadcasts** (§3.5): the sender applies its own event locally. A replacement that echoes
  a broadcast to its sender would execute immediate events twice.
- **Host relay order.** Everything a client sends to all passes through the host and is re-sent in the order the
  host dequeued it, so all other clients see two clients' messages in the same relative order [inferred from the
  single dispatch loop on the host]. Only message 1000 traffic depends on it (chat, session events).

Ping values, traffic statistics, the LAN list and wall-clock timers (`GetTickCount`, `Timer_GetTotalSeconds`)
are local and differ per machine; ping samples reach the simulation only through the host's tick-length
decision, which is itself distributed to all peers (`docs/sim/logic-core.md`, net tick length adaptation).

---

## 9. Notes for a Godot reimplementation

A remake does not need `tincat3.dll` or its wire format unless it wants to play against original clients. For a
remake-only network, replace the layer by an engine transport (for example `ENetMultiplayerPeer` with a reliable
ordered channel, or a `TCPServer` / `StreamPeerTCP` star) and keep the contract below.

**What the session layer must still be given**

1. **Roles and topology**: one host, clients connected only to the host; start-up as host (listen on
   `gamePort`) or client (connect to address:port, default `gamePort`), failing cleanly; a blocking or awaited
   connect with a timeout (original: a blocking `connect` under the operating system's own timeout, then at
   most 30 s for the logon reply, §6.2).
2. **Ids**: a host id constant, an "all" destination, a "none" value, and per-client ids unique among connected
   peers, assigned by the host and reported to the client on connect. Slots store these ids and the GUID carries
   identity across reconnects, so ids may be reused after a peer has gone, as in the original (lowest free id).
3. **Four sends** with message types 1000..1003 and an opaque body of any size: to host, to all others (never
   back to the sender; on a host with no peers a successful no-op), to one id (relayed by the host when sent by
   a client), and "first peer other than X and the host" (used by file transfer).
4. **Reliable, ordered, intact delivery per connection**, delivered on the main thread during the transport's
   `Process`, before the session's per-frame work. Keep a per-frame cap only if it is generous (original: 500).
5. **Receive callback** with (to, from, type, body). The original transport hands `from` to the session layer
   only with messages 1001 and 1003; for 1000 and 1002 the session layer has only the body's sender fields
   [known, S 0041d720], and the host's relay does not check `from` against the connection (§3.5). A remake's
   host should check `from` against the connection for every type.
6. **User list**: add on connect (host: one entry per client; client: its own), attach name, GUID and connection
   type when the join event arrives, remove on disconnect with the "player left" notification carrying GUID and
   id; lookups by id and by index; the user list text broadcast (0x30008) whenever user data is attached or an
   entry is erased (not on the bare add).
7. **Ping**: a round-trip measurement per peer every `pingFrequencyMenu` / `pingFrequencyGame` seconds (host →
   all clients, client → host), newest two samples kept, queries "latest" and "max".
8. **Loss detection**: report a dropped peer promptly. The original only reacts to socket errors (noticed
   within about 0.1 to 0.6 s, §4) and to 400 s of silence on the host; a remake should use the engine's timeout
   (a few seconds) because the lockstep gate stalls the match meanwhile.
9. **Close to newcomers** when loading starts, and **kick** by id.
10. **Host loss**: either reproduce the reconnector contract — every client knows the ordered list of clients
    with address and port; on loss of the host all pick the first entry; that peer reports "became host", the
    others "reconnect to address:port" — or decide deliberately to end the match on host loss. The session
    layer's reconnect state machine (`network-session.md` §3.9) needs exactly those two verdicts. For play over
    the internet the original scheme needs the successor to be reachable from outside; a remake that relays
    through a server can keep the verdicts and drop the address.

**LAN discovery.** Godot's `PacketPeerUDP` with broadcast enabled covers it. For a remake-only list any format
works; the natural record is the original's: game name, map name, humans / maxPlayers, game port, plus a build
identifier so that incompatible versions can be greyed out (the original record has none; the version check
happens at join, `network-session.md` §3.5). Query-and-reply with a refresh cycle, as in §3.3, avoids periodic
broadcast noise; the host must answer from the session's current data. To be listed by, or to list, original
clients is pointless: no original client ever sends or answers the query (§3.1).

**Must be reproduced exactly only for interoperability with the original client**: the frame of §3.9 including
the CRC variant, the logon exchange of §3.4, the application prefix and routing of §3.5 (including "To = the
recipient's id" on host broadcasts and the unwritten fifth header dword), the ping of §3.8 (the client answers
it inside the library; the host needs the answers only for display and tick length), the reconnector messages of
§3.10 (a host that never sends a peer list makes original clients fail the election and drop out on host loss),
the keep-alive tolerance (accept type `0xB`, never require it).

**A server or converter has to provide** nothing for this layer: there are no assets, and `network.ini` holds
only ports and periods, which a remake keeps in its own settings with the same defaults.

---

## 10. Open questions

| Question | Settled by |
|---|---|
| Whether the remote side of a TinCat `Disconnect` really reports *connection closed* (§3.7: inferred from the reader thread) | a kick observed with a hook on `cb_ConnectionClosed` S 0041bcc0 and `cb_LoggedOut` S 0041b990 |
| Answered (§3.4): the host's accepted sockets run without `TCP_NODELAY` (both read 0 by `getsockopt`, no `setsockopt` call) [live, 2026-10-14] | — |
| Whether `usrRemove`, `usrLogoffTimeout` and `drvRemoveTime` are read at all (§6.2 rows marked `[TODO]`). A join and a leave were run live 2026-10-14 without settling it: the getter T 10006cf0 is too short for a Frida hook, and read watchpoints on driver `+0x60` / `+0x68` stall the game | static: a full search for readers of driver `+0x60`, `+0x68` and callers of T 10006cf0; live: a debugger that can break on them |
| Answered (§6): the effective `gamePort` is 5479; the byte order mark hides the first `[Basics]` section (5478) from `GetPrivateProfileIntA`, and the second section and the code default both give 5479 [live, 2026-10-14] | — |
| Relation of this LAN code to the `CommLayer` LAN classes of `tincat3.dll` (`ConnectionLANLobby`, `ConnectionBC`, `ai::net::LanLobbyHost` T 100276a0), which are a second, lobby-level LAN path | read those classes and their users in the game; not needed for a match |
| Whether the dormant LAN path works end to end (a role 2 host answering a role 1 client) | calling `StartUpNetwork(2)` and `BC_Start` in the running game on two machines |

---

## 11. Function reference

Game (`sadk_noav.exe`):

| Address | Name | Role |
|---|---|---|
| S 0040a9a0 | `NComm_Manager::StartUpNetwork` | role selection, creates the transport |
| S 004090e0 | `NComm_Manager::BroadcastGameInfo` | only caller of `BC_Update` |
| S 0040b170 | `NComm_Manager::BeginGameStarting` | `BC_Stop` for role 2 |
| S 00410f70 | `NComm_Manager::Process_MainLoop` | transport `Process`, ping period |
| S 004100b0 | `NComm_Manager::BroadcastUserListText` | 0x30008 after user data was set or an entry erased |
| S 0041e310 | `NComm::TinCatNetwork::ctor` | initial values |
| S 0041e610 | `NComm::TinCatNetwork::StartUp` | TinCat creation and values |
| S 0041cc20 | `NComm::TinCatNetwork::ShutDown` | teardown |
| S 00419e10 | `NComm::TinCatNetwork::Process` | per-frame pump, reconnector poll |
| S 00419080, S 004190b0 | `BeginManagerReconnectOnce`, `RestartAsClientOnce` | latched reconnect steps of `Process` |
| S 00419060 | `StopReconnector` (slot `+0x9c`) | deletes the `TinCatReconnector` |
| S 00419c60 | `PruneTrafficStats` | drops traffic records older than 120 s |
| S 0041ede0 | `NComm_NetworkConfig_LoadFromIni` | reads `network.ini` |
| S 0041a1b0, S 0041a2e0 | `ConnectToServer`, `Disconnect` | client connect, disconnect |
| S 0041a520, S 0041a620 | `CloseSession`, `KickPlayer` | close to newcomers, kick |
| S 0041db50, S 0041dbb0, S 0041dc30, S 0041dc90 | `SendToHost`, `SendToAll`, `SendTo`, `SendToFirstPeerExcept` | send primitives |
| S 00418f80 | transport slot `+0x84` (map name `FlushPending`) | sends the ping |
| S 0041d720 | `cb_Received_Data` | inbound dispatch |
| S 0041eb10, S 0041b990, S 0041bb20, S 0041bcc0 | `cb_LoggedIn`, `cb_LoggedOut`, `cb_ConnectionLost`, `cb_ConnectionClosed` | connection events |
| S 0041e990, S 0041a720, S 0041d4c0, S 0041cd40 | `UIS_Add`, `UIS_SetUserData`, `UIS_Remove`, `UIS_RemoveUserData` | user list writers |
| S 0041d910, S 0041d610, S 004199b0 | `cb_Ping_Received`, `UIS_AddPingSample`, `GetUserPing` | ping samples |
| S 00419740, S 00419880, S 004196e0 | `GetUserNetIdByIndex`, `GetUserLevel`, `NCommUserRecord_GetMaxSample` | list queries |
| S 0041aa90, S 0041adb0, S 0041b580, S 0041b680, S 00418f70 | `BC_Start`, `BC_Update`, `BC_Stop`, `BC_GetGameInfo`, `BC_IsActive` | LAN discovery |
| S 0041dd70, S 0041c070, S 0041ce80, S 0041c340 | `cb_BCast_ServerAdded`, `…Updated`, `…Removed`, `cb_BCast_ListUpdated` | LAN list maintenance |
| S 00419330, S 004194a0 | `ai::network::BCGameInfo::Serialize`, `Deserialize` | LAN record payload |
| S 00418fd0, S 004258e0 | `StartReconnector`, `NComm::TinCatReconnector::Start` | reconnector creation |
| S 004259b0, S 00425aa0 | `cb_BecameServer`, `cb_ReconnectTo` | election verdicts |

Library (`tincat3.dll`):

| Address | Name | Role |
|---|---|---|
| T 10007ed0 | `TinCat_CTRL::TinCatAPI_Init` | mode, module id, default values |
| T 1000a480 | `TinCat_CTRL::NetworkService_Init` | driver start |
| T 10001090 | `PROGFLOW_NET::NetworkInit` | hands the values to `NETDRV_Init` |
| T 100029d0 | `NETDRV_Init` | driver, master thread, host timers, timing block |
| T 100026c0, T 10001870, T 10001e70 | `NETDRV_ServerThreadProc`, `NETDRV_ServerLookForFlags`, `NETDRV_ServerLookForNewConnection` | master thread |
| T 10004ad0, T 100354c0 | `KRNL_ProcessPendingConnects`, `CALL_Process` | first two steps of `PROGFLOW_NET::Process` |
| T 1000bef0, T 1000b880 | `TinCat_Values::InitDefaults`, `ApplyPreset` | preset tables T 1005e210, T 1005e420 |
| T 10008420, T 10001800, T 100012f0 | `TinCat_CTRL::Process`, `PROGFLOW_NET::Process`, `ProcessMessages` | per-frame pump, frame type dispatch |
| T 10009670, T 10004660 | `ConnectToIP`, `KRNL_SendLogonRequest` | blocking connect and logon request |
| T 10005a60, T 10004d90 | `KRNL_LogClientOn`, `KRNL_OnLogonAccepted` | logon on host and client |
| T 10006870, T 10035880 | `NETUSR_AllocUserAddr`, `SlotTable_Alloc` | user id allocation |
| T 10009c90, T 10007b10, T 10006a80 | `Send_Data`, `Send_DataToServer`, `TinCat_BuildModulePayload` | application send |
| T 10003cc0, T 10003bc0, T 10003b20 | `KRNL_SendMessage`, `KRNL_SendToAllUsers`, `KRNL_SendSingleMessage` | routing on the sender |
| T 10005140, T 100045c0, T 1000aa80 | `KRNL_RouteCustomData`, `KRNL_DeliverReceivedData`, `TinCat_CTRL::Received_Data` | relay on the host, delivery |
| T 1000a2a0, T 10009070 | `Send_Ping`, `Received_Ping` | ping |
| T 100041b0, T 10005de0, T 10004130, T 10005320 | `KRNL_SendAliveMessage`, `KRNL_CheckDeadConnections`, `KRNL_LogonCheckTimer`, `KRNL_AliveLogTimer` | keep-alive and timeouts |
| T 10004fb0, T 100063c0, T 10033310 | `KRNL_InitUser`, `NETUSR_InitUser`, `NET_Connect` | new connection on host and client |
| T 10005d30, T 10004f00 | `KRNL_RemoveUser`, `KRNL_ConnectionLost` | removal and its events |
| T 100325e0, T 10032670, T 100342a0 | `NET_SendPacket`, `NET_ReceivePacket`, `CRC32_Compute` | frame format |
| T 10034180 | `BL_StrCopySafe` | `strncpy` into a fixed field, last byte forced to NUL |
| T 10001fc0, T 10002390 | `NETDRV_ReaderThreadProc`, `NETDRV_WriterThreadProc` | per-connection threads |
| T 1000a970, T 100073b0, T 10008720, T 100073d0, T 10007450 | `BCast_Enable`, LAN disable, `BCast_Client_UpdateList`, `BCast_Server_SetInfo`, `BCast_Server_SetData` | LAN API |
| T 1000c570, T 1000c1c0, T 1000c250, T 1000c510 | `TinCatBCast::Open`, `TinCatBCast_ServerPoll`, `TinCatBCast::ClientPoll`, `TinCatBCast_ClientRequestList` | LAN logic |
| T 10032e10, T 10032fd0, T 10033090, T 10033140 | `NET_BCastOpen`, `NET_BCastSend`, `NET_BCastSendTo`, `NET_BCastReceive` | LAN socket and datagram |
| T 10010d10, T 100109b0 | `TinCatModules::Reconnector` constructor, `Init` | reconnector set-up |
| T 10010ae0, T 10010b80, T 10010a30 | `HandleAddedConnection`, `HandleRemovedConnection`, `HandleReceivedData` | reconnector events |
| T 10010890, T 10010930 | `Reconnector_BroadcastPeerList`, `Reconnector_ElectNewHost` | peer list, election |
| T 10010710, T 10010780, T 100106a0, T 100106d0 | `Reconnector_AddPeer`, `…AddPeerCopy`, `…SendLocalPort`, `…SetPeerPort` | peer records |
