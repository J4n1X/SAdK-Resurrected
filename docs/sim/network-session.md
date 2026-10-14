# Match network session (NComm): lockstep, packages, join, leave and reconnect

Binary: `sadk_noav.exe` (base 0x400000). Tags: **[known]** = read at the given address (S 00xxxxxx) or in the named
data file and key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = not established, with
what would settle it. Nothing here was observed in the running game.

Related documents, not repeated here: `docs/sim/logic-core.md` (the tick loop, the lockstep gate and step, the
desync checksum: §2.9, §3.2, §3.6), `docs/sim/game-commands.md` (the `0x2000x` commands and their event classes:
§2.2, §3.4), `docs/NCOMM_GAME_PROTOCOL.md` (the pre-game room: slot fields, ready states, settings),
`docs/NCOMM_LAYER.md` (class and vtable inventory), `docs/s2tftp.md` (file transfer), `docs/multiplayer-save.md`
(why a network match cannot save), `docs/MATCH_START.md` (the lobby and referee steps around a match start),
`docs/data-loading.md` §3 (the build checksum).

---

## 1. Purpose and scope

NComm ("network communication") is the session layer between the players of one match. It

- keeps the **session description** (`NComm::EventGameInformation`: six player slots, map, settings, game id,
  seed, wager) identical on all peers, with the host as the only writer;
- admits players (version, data checksum and password checks), removes them (leave, kick, connection loss) and
  survives the loss of the host (host migration and rejoin);
- drives the match through the phases *room → loading → running*;
- carries the players' game commands and one state checksum per player in **tick packages**, which the host
  merges and redistributes, so that every peer executes the same commands at the same logic tick (lockstep);
- offers a TFTP-like file transfer between peers (used for a missing map).

The same code runs an offline game: role 0 uses a transport that sends nothing, and commands are executed at once.

In scope: `NComm_Manager` (singleton `g_NCommManager` S 00885754), the transport `NComm::TinCatNetwork` and its
stand-in `NComm::DummyNetwork`, the event classes and their wire format, `TickPackage` / `TickPackageList`, the
manager and reconnect state machines, the four TinCat message types 1000..1003. Out of scope: what a command does
(`docs/sim/game-commands.md`), the checksum's content and comparison (`docs/sim/logic-core.md` §3.6), the room
dialog and slot editing rules (`docs/NCOMM_GAME_PROTOCOL.md`), the TinCat library below the transport
(`tincat3.dll`: sockets, framing, its `Reconnector` module), the lobby and referee servers.

---

## 2. Data model

### 2.1 Net ids

A peer is addressed by a 32-bit TinCat net id. Three values are reserved [known]:

| Value | Meaning | Evidence |
|---|---|---|
| `0xEFFFFFCC` | the **host**. The host's own local net id is this constant; `TinCatNetwork::IsHost` is `localNetId == 0xEFFFFFCC`; `PlayerInfo::IsHost` is `playerId == 0xEFFFFFCC`. The role 0 transport reports it as its local net id as well (`DummyNetwork` vtable slot `+0x30` is S 00418f40) | S 0041e610, S 00418f10, S 00414eb0, S 00418f40, S 007d5a6c |
| `0xEFFFFFDD` | all connected users (destination only) | S 0041dbb0, S 00418f80 |
| `0xEFFFFFEE` | none / not connected: empty slot, transport without a session | S 00415230.., S 00418f50 |

A client's local net id is the value returned by the TinCat connect call (`ConnectToServer` S 0041a1b0)
[inferred: the store is visible only as a write to `this+0x10` in the decompiled code].

The vtable slot the map calls `GetBroadcastNetId` (transport `+0x40`, S 00418f40) returns `0xEFFFFFCC`: it is the
**host id** [known]. The map's names of the send slots match their behaviour: `pSendToHost` (`+0x18`), `pSendToAll`
(`+0x1c`), `pSendTo` (`+0x20`), `pSendToAllExcept` (`+0x24`; it sends to one user only, §3.1) [known, Ghidra struct
`NComm_INetworkHandler_vftable`, vtable S 007d58f4].

### 2.2 `NComm::NetGUID` (0x14 bytes)

`+0x00` vftable pointer (S 007d42b4), `+0x04` four u32 (`data1..data4`) = a Windows GUID from `CoCreateGuid`
(`Generate` S 00416330, S 00416210) [known]. Each client creates one GUID in the manager's constructor
(manager `+0x32c`, S 0040a530) and keeps it for the life of the process: it is the player's identity across
reconnects, where the net id changes [known]. `IsValid` S 004162c0 is true only when **each** of the four dwords
is non-zero [known]; a cleared GUID is all zero.

On the wire a GUID embedded in an event is written as its **0x14 raw bytes, vftable pointer included** (§3.2).
`NetGUID::Serialize` S 004085e0, which writes only the 16 data bytes, is not what the events call [known].

### 2.3 `NComm_Manager` (singleton)

Fields this subsystem owns. The tick fields `+0x24..+0x4d` and the config block are specified in
`docs/sim/logic-core.md` §2.9 and only listed here. Initial values: constructor S 0040a530 and
`NComm_Manager::ResetSession` S 0040a810 (run by `Shutdown(false)`) [known].

| Offset | Type | Meaning | Reset value |
|---|---|---|---|
| +0x00 | i32 | **reconnect state** 0..4 (§3.9) | 0 |
| +0x04 | f32 | reconnect timer (s) | 0 |
| +0x08..+0x14 | i32[4] | IP octets of the host to rejoin; all -1 = none | -1 |
| +0x18 | i32 | port of the host to rejoin | not reset |
| +0x1c | i32 | **manager state** 0..4 (§3.4) | 0 |
| +0x20 | bool | error latch: set when the transport's `Process` fails or by `Shutdown(true)`; while set, `BeginGameRunning` refuses | 0 |
| +0x21 | bool | cleared with the latch and never read: only the constructor S 0040a530 and `ResetSession` S 0040a810 write it (0); no instruction of the functions in 0x408000..0x412fff, of the users of `g_NCommManager` or of the callers of `NComm_GetManager` S 00408290 reads it [known for those functions] | 0 |
| +0x24 | f32 | time of the last ping / tick-length check | 0 |
| +0x28 | i32 | number of connected human players = checksums expected per net tick | 0 |
| +0x2c | i32 | net tick | -1 |
| +0x30 | i32 | base net tick | -1 |
| +0x34 | i32 | logic ticks per net tick (`+0x38 * +0x3c`) | 4 |
| +0x38 | i32 | net tick length | 4 |
| +0x3c | i32 | game speed multiplier | 1 |
| +0x40 | i32 | sub-tick counter | -1 |
| +0x44 | f32 | wall time of the last accepted logic tick | 0 |
| +0x48 | i32 | logic tick number of the last accepted tick | -1 |
| +0x4c | bool | in sync | 0 |
| +0x50 | ptr | game listener: vtable `+4` handle event, `+8` start game, `+0xc` compute checksum | 0 |
| +0x54 | TickPackage | **outgoing package** of the local player for the current net tick | cleared |
| +0x80 | TickPackage | **immediate queue**: events received as message 1000, header tick `0xFFFFFFFF` | header only |
| +0xac | TickPackageList | host: packages **collected** from the players, one per net tick | empty |
| +0xb8 | TickPackageList | packages **to execute** (merged by the host), one per net tick | empty |
| +0xc4 | ChecksumLog | received checksums | empty |
| +0xdc | EventGameInformation | the **session description** (§2.5) | `Reset` |
| +0x32c | NetGUID | local player's GUID | generated once |
| +0x340 | ptr | transport (`INetworkHandler`), 0 when shut down | 0 |
| +0x344 | std::string | user list text of event 0x30008 | |
| +0x360 | NetworkConfig | `network.ini` values (§6) | defaults |
| +0x3ac | bool | joined: set by `ConnectAndJoin`; `IsInGame` = joined and state ≥ 4 (S 00408440) | 0 |
| +0x3ad | bool | leave requested | 0 |
| +0x3ae | bool | leave completed (confirmed by the host or timed out) | 0 |
| +0x3b0 | f32 | leave timeout countdown (s) | 0 |
| +0x3b4 | list&lt;NetGUID&gt; | GUIDs of players who left the running match | empty |
| +0x3c0 | ptr | chat sink (the game screen) | 0 |
| +0x3c4 | ptr | message sink: vtable `+0` join / leave notices (S 0040e3d0), `+8` the kick notice (S 0040e370) | 0 |
| +0x3c8 | i32 | **role** 0..4 (§3.3) | 0 |
| +0x3cc | bool | StartLoading received (polled by the room screen) | 0 |
| +0x3d0 | ptr | file transfer progress listener; never set (`docs/s2tftp.md`) | 0 (constructor only) |
| +0x3d4..+0x40f | 5 × std::list | observer lists (0xc bytes each), notified next to the message sink; [TODO] not established: which list carries which notice and who registers (read S 0040e370, S 0040e3d0 and the list writers) | empty (constructor only) |

`ResetSession` does not touch the GUID (`+0x32c`), the config block (`+0x360`), `+0x18`, `+0x3d0` or the observer
lists [known, S 0040a810].

### 2.4 `NComm::PlayerInfo` (slot, 0x4c bytes)

The field table is in `docs/NCOMM_GAME_PROTOCOL.md`. What the session logic uses [known]:

| Field | Offset | Values |
|---|---|---|
| state | +0x04 u8 | 0 open (`ResetToOpen` S 004153d0) · 1 occupied (`Init` S 00415500, `SetupAi` S 00415300) · 2 dropped, may rejoin (`ResetToState(false)` S 00414d10) · 3 left the match (`ResetToState(true)`; `HasLeftGame` S 00414f40) · 4 closed (`SetupClosed` S 00415370) · 5 cleared, to be initialised by `RefreshSlots` (`Clear` S 004152a0) |
| playerId | +0x05 u32 | net id of the occupant; `0xEFFFFFEE` = nobody connected |
| ownerGuid | +0x09 NetGUID | GUID of the occupant; kept when the player drops (states 2, 3) |
| kind | +0x3b u8 | 0 open · 1 human · 2 AI · 3 closed |
| playerIndex | +0x3a u8 | index in the simulation's player table; 0xff = not assigned |
| readyState | +0x40 u8 | 0 not ready · 1 ready · 2 loaded |

`IsFilled` S 00414ed0 [known]: AI and closed slots count as filled, open slots never; a human slot is filled when
its GUID is valid and state = 1 and, while no reconnect is in progress (manager `+0x00` = 0), its playerId is not
`0xEFFFFFEE`.

### 2.5 `NComm::EventGameInformation` (0x24f bytes; the session description)

It is both an event (ids 0x30003, 0x30005, 0x3000f, 0x30012) and the manager's stored session (`+0xdc`) [known,
Ghidra struct, `Serialize` S 00413ae0].

| Offset | Type | Field | Notes |
|---|---|---|---|
| +0x00..+0x0c | | event header (§3.2) | |
| +0x10 | PlayerInfo[6] | slots | stride 0x4c |
| +0x1d8 | std::string | gameName | set to the host's player name in `ConnectAndJoin` (S 0040ad60) |
| +0x1f4 | NetGUID | mapGuid | |
| +0x208 | std::string | mapName | a client replaces it by its local path of the map (0x30003) |
| +0x224 | i8 | maxPlayers | number of slots in use (`RefreshSlots` clears the rest) |
| +0x225 | i8 | winCondition | setter S 00413080 |
| +0x226 | i8 | startResources | setter S 00413090 |
| +0x227 | i8 | fogOfWar | setter S 004130a0 |
| +0x228 | bool | fetchMapFromHost | |
| +0x229 | u8 | mapFileType | 3 = a map that can be fetched (0x30003) |
| +0x22a | u32 | gameId | lobby game id |
| +0x22e | i8 | rankedGame | |
| +0x22f | u32 | gameSeed | referee value; `SetGameSeedIfState2` S 004082e0 stores it only in manager state 2 |
| +0x233 | u32 | wager | |
| +0x237 | u32 | settingsCrc | written by `UpdateSettingsCrc` S 00414720 before every send |
| +0x23b | MD5Digest | passwordMd5 | vftable + 16 bytes; **not serialised** |

The meaning of the setting values is specified with the room (`docs/NCOMM_GAME_PROTOCOL.md`) and with the game
start (`docs/sim/players-victory.md`).

`AssignGameData` S 00414290 copies everything except the event header, including the password digest [known].
A received event carries a zero digest (it is not on the wire), so on a client the stored digest is always zero
[inferred].

`settingsCrc` is a `NCore::CRCStream` value (CRC-32; a string contributes exactly the first 4 bytes of its buffer,
whatever its length, S 0057d3d0; `docs/sim/logic-core.md` §3.6), stream opened with the section name
`GameInformation`, over, in this order [known, disassembly of S 00414720]: gameName (`+0x1d8`); a string produced
from mapGuid (`+0x1f4`) by S 004098b0, which returns an **empty** string, so the map GUID does not enter the value;
mapName (`+0x208`); then, each sign-extended to 32 bits and hashed as 4 bytes (S 0057d360), maxPlayers,
winCondition, startResources, fogOfWar, fetchMapFromHost, mapFileType, gameId, rankedGame, gameSeed, wager. Slots
and password digest are not part of it. The only reader of the value is `LobbyMenu::SetupGameDialog::Update`
S 00457a00 [known: one caller of `GetSettingsCrc` S 00413a50], which restarts a 3500 ms countdown when the value
differs from the one it saw last; no receive path verifies it.

### 2.6 `TickPackage` (0x2c bytes) and `TickPackageList`

`TickPackage` = an `NComm::MemoryStream` (0x1c bytes: vftable, buffer, size, read/write position, capacity, grow
step, then two flag bytes at `+0x18` and `+0x19`, the second = "buffer is external, do not reallocate"; initial
capacity 0x400, grow step 0x80, S 00412d80, S 004122f0) followed by [known, Ghidra struct]:

| Offset | Type | Field |
|---|---|---|
| +0x1c | i32 | eventBlockCount: number of blocks appended with `AppendEvents` |
| +0x20 | list&lt;u32&gt; | net ids of the players whose block was appended (`AddPlayer` S 00412e20 ignores `0xEFFFFFEE` and duplicates) |

`TickPackageList` = a `std::list<TickPackage*>`, searched linearly by header tick (`FindOrCreate` S 00412a10),
pruned by `EraseOlderThan(tick)` S 004128e0 (removes packages whose tick is lower) [known].

### 2.7 `NComm::TinCatNetwork` (0xec bytes) and `DummyNetwork`

`TinCatNetwork` implements `INetworkHandler` (vtable S 007d58f4, 44 slots) and, at `+0x04`, the TinCat callback
interface [known, Ghidra struct]:

| Offset | Field |
|---|---|
| +0x08 | TinCat API object (`TinCat_CreateAPI`) |
| +0x0c | pointer to an `NComm::TinCatReconnector` (0x24 bytes, allocated by `StartReconnector` S 00418fd0): `+0x04` TinCat `Reconnector` module, `+0x08` TinCat API, `+0x0c` state (0 idle, 1 became server, 2 reconnect to), `+0x10..+0x1c` host IP octets (initially -1), `+0x20` host port |
| +0x10 | local net id |
| +0x14 | user list (`std::list<TinCatUserEntry>`): net id (node `+0x24`), name, GUID, level (connection type), ping samples |
| +0x38, +0x39 | latches "manager reconnect started", "restart as client started" |
| +0x3c | traffic statistics list |
| +0x48 | own LAN broadcast record (`BCGameInfo`) |
| +0xe4 | `ai::net::S2TftpManager` (file transfer) |

`DummyNetwork` (4 bytes, vtable S 007d5a6c) is the role 0 transport. Its `StartUp` S 0041ec80 succeeds only
for (isHost = 1, online ≠ 1); its send functions `Broadcast_Stub` S 0041eca0 (slots `+0x18`, `+0x1c`) and
`SendStub` S 0041ecb0 (slots `+0x20`, `+0x24`) do nothing and return true (`mov al,1; ret`) [known].

### 2.8 Event classes

Every event starts with the header `+0x00` vftable, `+0x04` u32 type id, `+0x08` u32 sender net id, `+0x0c` i32
sender slot (index into the six slots; -1 = unknown). The class decides the payload; the type id decides the
meaning. Class tags (returned by vtable slot `+0x14`, switched on by the factory `NComm_Event_CreateFromStream`
S 00420540) [known: the factory constructs exactly these 20 classes; tag values from `docs/NCOMM_LAYER.md`]:

| Class | Tag | Payload after the header (wire order) | Used by type ids |
|---|---|---|---|
| EventBase | `0x00000101` | none | commands without payload (e.g. 0x20007; `docs/sim/game-commands.md`) |
| Event1Integer | `0x11111010` | i32 | 0x30004, 0x3000d, 0x30011, commands |
| Event2Integer | `0x11110202` | i32, i32 | commands |
| Event3Integer | `0x11113030` | i32 × 3 | commands |
| Event4Integer | `0x11110440` | i32 × 4 | none found |
| EventInt64 | `0x22220101` | u64 | commands |
| EventInt64_1Integer | `0x22222020` | u64, i32 | commands |
| EventInt64_2Integer | `0x22220303` | u64, i32, i32 | none found |
| EventInt64_3Integer | `0x22224040` | u64, i32 × 3 | none found |
| EventData | `0x33331010` | u32 tag, u32 length, bytes | 0x20021 |
| EventText | `0x44440101` | string | 0x30006, 0x30007, 0x30008 |
| EventUserReJoinGame | `0x55550202` | NetGUID raw (0x14), i32 net tick | 0x3000e |
| EventUserLeave | `0x55550404` | NetGUID raw | 0x3000a |
| EventPlayerInformation | `0x55550606` | NetGUID raw, i32 tribe, i32 team, i32 colour, i32 playerIndex | 0x30002 |
| EventSaveGame | `0x55550808` | string name, NetGUID raw | never created (`docs/multiplayer-save.md`) |
| EventUserInformation | `0x55551010` | see §3.5 | 0x30001 |
| EventKickUser | `0x55553030` | string reason | 0x30010 |
| EventUserChecksum | `0x55555050` | i32 tick, u32 checksum, NetGUID raw | 0x30009 |
| EventUserLeft | `0x55557070` | i32 playerIndex, u32 net id, NetGUID raw | 0x3000b |
| EventGameInformation | `0x66660101` | see §3.2 | 0x30003, 0x30005, 0x3000f, 0x30012 |

"none found" = the class is never built for sending: the only reference to each of the three vftables
(S 007d5cc8, S 007d5d28, S 007d5d48) is the class's deserialising constructor (S 0041f8c0, S 0041fb80, S 0041fc70)
[known, xref lists]. A reimplementation needs them only to parse foreign input.

The factory returns false for an unknown class tag and leaves the read position on the tag [known].

Type id spaces [known, the id/name pairs registered by `NComm_InitEventTypeNameMap` S 00421bd0]:
`0x20001..0x2002B` = `GE_*` game commands (`docs/sim/game-commands.md`), `0x30001..0x30012` = `NE_*` session
events (§3.6).

---

## 3. Rules and algorithms

### 3.1 Transport: messages, addressing, topology

The session is a **star**: the host is a TinCat server, every other player a TinCat client connected to it
[known: `TinCatNetwork::StartUp(isHost, online)` S 0041e610 initialises the API with role 1 (host) or 2 (client),
module id `0x27d9`, and a port: `gamePort` on the host, the `ConnectionSettings` port on a client]. The host
listens on `gamePort` (§6); a client connects to the address in
`ai::ncomm::ConnectionSettings` (IP octets `+0x04..+0x10`, port `+0x14`, default 5479; S 00411e20), or, when the
port argument is -1, to `gamePort` (`ConnectToServer` S 0041a1b0) [known].

All session traffic is TinCat data of module `0x27d9` with one of four message types (`cb_Received_Data`
S 0041d720) [known]:

| Type | Payload | Sender → receiver | Receiver action |
|---|---|---|---|
| 1000 (0x3e8) | one serialised event, no package header | any peer → host, all, or one peer | appended to the immediate queue (`+0x80`); executed in the next `Process_MainLoop` |
| 1001 (0x3e9) | a client's tick package | client → host | merged into the host's collected package of that tick, if the sender owns a slot |
| 1002 (0x3ea) | a merged tick package | host → all | stored in the to-execute list |
| 1003 (0x3eb) | an S2TFTP packet | peer → peer | `S2TftpManager::OnReceive` (§3.11) |

Before this dispatch every received message is offered to the TinCat `Reconnector` module
(`Reconnector::HandleReceivedData`); a message it consumes (return value 1) is not processed further. A message of
another module id is dropped; message 1003 is dropped while no `S2TftpManager` exists; an unknown type is ignored
[known].

Send primitives (transport vtable S 007d58f4) [known]:

| Slot | Function | Destination |
|---|---|---|
| +0x18 | S 0041db50 | the host (`0xEFFFFFCC`), with explicit source net id |
| +0x1c | S 0041dbb0 | all users (`0xEFFFFFDD`); a host without users sends nothing and reports success |
| +0x20 | S 0041dc30 | one net id |
| +0x24 | S 0041dc90 | the first user in the list that is neither the given net id nor the host; false when there is none |

Null data or size 0 sends nothing (slots `+0x18..+0x20` then report success, slot `+0x24` failure). Manager-level
wrappers [known]:

- `SendEvent(ev, target)` S 00408b60: if `target` is the local net id, the event is handled locally and nothing is
  sent. Otherwise the event is serialised into a fresh buffer and sent as message 1000: through slot `+0x18` when
  `target` is the host id, else through slot `+0x20`. So on the host an event "to the host" is a local call. The
  function returns true in every case; a failed send is not reported to the caller.
- `BroadcastEvent(ev)` S 0040fd80 (not in manager state 0): message 1000 through slot `+0x1c` (all users), then
  the event is handled locally as well.
- `DispatchEventLocal(ev)` S 0040fd50: `HandleEvent`; if that returns false, the game listener's slot `+4`.

TinCat routes a client's message addressed to `0xEFFFFFDD` through the host to every other client and the host;
one addressed to another client's net id goes to that client through the host (§10 Q1: `KRNL_SendMessage`
T 10003cc0, `KRNL_RouteCustomData` T 10005140) [known]. Chat (0x30006, 0x30007) is the only traffic that depends
on it.

A message 1000 is trusted as it is: the receiver takes the sender net id and slot from the event body, not from
the TinCat source of the message [known: `cb_Received_Data` passes only data and size on]. Only message 1001 is
checked against the TinCat source (§3.7).

### 3.2 Wire format

All integers little-endian, written as raw memory (`MemoryStream::Write` S 004122f0) [known].

**Event** = u32 class tag, then the class's own serialisation (`NComm_Event_WriteToStream` S 004201f0):

| Field | Size |
|---|---|
| class tag | 4 |
| type id | 4 |
| sender net id | 4 |
| sender slot | 4 |
| payload | by class (§2.8) |

**String** = u16 length, then the bytes, no terminator (`WriteString` S 004123a0, `ReadString` S 00412400). The
reader takes the length as a signed 16-bit value, uses 0 when fewer than 2 bytes remain, and does not check the
length against the remaining data [known].

**NetGUID raw** = 0x14 bytes: 4 bytes of the sender's vftable pointer (to be ignored by a reader), then 16 GUID
bytes. The original reader copies all 0x14 bytes over its own object [known: `Write(…, 0x14)` in S 00408640,
S 004086d0, S 00408750, S 004087c0, S 00409950, S 00413ae0, S 00415060].

**EventGameInformation payload** (`Serialize` S 00413ae0, reader S 00413e00) [known]:

| Order | Field | Size |
|---|---|---|
| 1 | six × PlayerInfo (below) | variable |
| 2 | gameName | string |
| 3 | mapGuid | NetGUID raw |
| 4 | mapName | string |
| 5 | maxPlayers, winCondition, startResources, fogOfWar, fetchMapFromHost, mapFileType | 1 each |
| 6 | gameId | 4 |
| 7 | rankedGame | 1 |
| 8 | gameSeed | 4 |
| 9 | wager | 4 |
| 10 | settingsCrc | 4 |

**PlayerInfo** (`Serialize` S 00415060) [known]: state (1), playerId (4), ownerGuid (NetGUID raw), connectionType
(1), name (string), playerIndex (1), kind (1), aiLevel (1), tribe (1), colour (1), team (1), readyState (1),
avatarTribeGenderLevel (2), avatarColors (4), avatarId (4). The byte at `+0x4b` (left notice shown) is not sent.

**Tick package** (messages 1001, 1002) [known, S 00412b40, S 00412e80]:

| Field | Size | Value |
|---|---|---|
| magic | 2 | `0x5332` (bytes `32 53`, "2S") |
| net tick | 4 | |
| magic | 2 | `0x4b38` (bytes `38 4b`, "8K") |
| events | variable | serialised events back to back, no count, no per-player delimiter |

A buffer is a package when it has at least 8 bytes and both magics (`NComm_IsS28KPacket` S 00412b90). There is no
length field: the reader consumes events until the read position reaches the buffer size (S 00410530).

### 3.3 Roles

The role is the argument of `StartUpNetwork(mode)` S 0040a9a0, stored at manager `+0x3c8` [known]:

| Role | Transport | `StartUp` arguments | Use |
|---|---|---|---|
| 0 | DummyNetwork | (1, 0) | offline game (campaign, free game, savegame) [known: literal 0 in the `nMenu` callers S 005d9fd0, S 005df2c0, S 005dfef0, S 005e27c0] |
| 1 | TinCatNetwork | (isHost 0, online 0) | client, LAN [inferred] |
| 2 | TinCatNetwork | (1, 0) | host, LAN [inferred] |
| 3 | TinCatNetwork | (0, 1) | client, lobby game [known: literal 3 in `GameServerInfo::JoinGame` S 0048d030, `JoinGameWithPassword` S 0048d0c0, `GameServerConnection::OnLoggedIn` S 0048edf0] |
| 4 | TinCatNetwork | (1, 1) | host, lobby game [known: literal 4 in `ServerList::CreateGameServer` S 0046aaa0] |

A role above 4 creates no transport and fails like a failed start [known]. No caller passes 1 or 2: all eleven
callers of `StartUpNetwork` pass a literal, and the three not named in the table (the command-line starters
S 00401350, S 00401420 and `FreeGamePanel::StartFreeGame` S 005e7350) pass 0 [known]. The only other writers of
`+0x3c8` are the constructor and `ResetSession` (0) and the two reconnect functions, which turn 3 or 4 into 3
(rejoin) or 4 (become host) and any other role into 1 or 2 [known, instruction search for the field]; a role 0
session has no reconnector, so roles 1 and 2 are not reached in this build [inferred].

`IsHost` S 00408410 = role 0, 2 or 4; `IsClient` S 004083b0 = role 1 or 3. `TinCatNetwork::StartUp` ignores its
second argument; the difference between the LAN and the lobby roles is made by the manager: after a
GameInformation broadcast a role 2 host updates its LAN broadcast record (`BC_Update`) and a role 4 host the lobby
server's game entry (`ServerList::UpdateGameServer`) (S 004090e0) [known]. "LAN" for roles 1 and 2 is
[inferred] from that and from the `BC_*` (broadcast discovery, port `broadcastPort`) functions.

The LAN discovery exchange (`BC_Start` S 0041aa90, `BC_Update` S 0041adb0, `ai::network::BCGameInfo::Serialize`
S 00419330) is specified in `docs/sim/lan-and-transport.md` §3.2 and §3.3; it is not reached in this build
(`BC_Start` has no caller) and is not needed for a lobby match.

`StartUpNetwork` requires manager state 0. It loads `network.ini`, creates and starts the transport (failure: the
transport is destroyed, state stays 0), sets state 1, net tick length and ticks per net tick to 1 (role 0) or 4
(roles 1..4), clears the reconnect fields, clears both package lists, starts the outgoing package for tick 0
(`SendEventUserChecksum(0)`), gives the immediate queue a header with tick `0xFFFFFFFF` and creates an empty
collected package for tick -1 [known].

`TinCatNetwork::StartUp` S 0041e610 additionally [known]: registers the callback interface; applies TinCat values
(role, module `0x27d9`, `gamePort`, and three numeric settings 1, 500, 500 through value slots `+0x70`, `+0x28`,
`+0x30`, plus API slot `+0x30` with 500 — meanings [TODO], they are TinCat's); on a host sets the local net id to
`0xEFFFFFCC` and adds the local user (name, GUID, connection type) to the user list; clears the two reconnect
latches; starts the reconnector (vtable `+0x98`, `StartReconnector` S 00418fd0, argument `gamePort`); creates
the `S2TftpManager`.

### 3.4 Manager state machine

| State | Name | Entered by | Left by |
|---|---|---|---|
| 0 | None | constructor; `Shutdown` S 0040b410; transport `Process` failure | `StartUpNetwork` → 1 |
| 1 | NetworkStarted | `StartUpNetwork` S 0040a9a0 | `ConnectAndJoin` → 2 |
| 2 | SessionStarted (pre-game room) | `ConnectAndJoin` S 0040ad60 | `BeginGameStarting` → 3 |
| 3 | GameStarting (loading) | `BeginGameStarting` S 0040b170, from `nMenu::Game::OnEnter` S 005eed00 | `BeginGameRunning` → 4 |
| 4 | GameRunning | `BeginGameRunning` S 0040b270, from the game listener on event 0x30005 | `Shutdown` → 0 |

The names of states 0..3 are the binary's own, from the log texts of the transition functions
(`m_ManagerState != EManagerState_None`, `..._NetworkStarted`, `..._SessionStarted`, `..._GameStarting`) [known];
the map's enum calls state 2 `Connected`. State 4 is named after the function that enters it [inferred].
Every transition function checks its source state and fails (returns false, logs) otherwise [known].
`BeginGameRunning` first tests the error latch (`+0x20`): when it is set it logs `Major Error Occured!` and changes
nothing [known].

`Shutdown(keepErrorLatch)` S 0040b410: if the state is not 0 and a transport exists, shuts the transport down and
destroys it; sets state 0 and the error latch to the argument; with `false` it also runs `ResetSession` (table in
§2.3), which forgets the session description, role, queues and listener [known]. Callers: every start of a new
offline or network game, leaving the room, leaving the match, a kick before the match, lobby errors (19 callers).

`BeginGameStarting` additionally stops the LAN broadcast (`BC_Stop`) under a nested role test that reduces to
role 2 [known as decompiled, S 0040b170].

Guards by state [known]: `SendEventPlayerInformation`, `SendPlayerReadyEvent`, `BroadcastStartLoading` and
`SetGameSeedIfState2` need state 2; `BroadcastStartGame` needs state 3; `SendGameLoadedEvent` needs 3 or 4;
`BroadcastGameInfo`, `KickPlayer`, `RefreshSlots` need a host role and state 2, 3 or 4; `BeginReconnect` needs
3 or 4.

### 3.5 Joining

`ConnectAndJoin` S 0040ad60 (state 1) [known]:

1. Client roles: `ConnectToServer`; on failure return false (state stays 1).
2. Set joined (`+0x3ac`), reset the session description, set maxPlayers 1, slot 0 to state 0 / kind open.
3. Build **EventUserInformation** (0x30001; sender = local net id, sender slot = the local GUID's slot, which is
   -1 after the reset) and send it to the host (`SendEvent` to the host id; on the host this is a local call, so
   the host joins its own game through the same handler).
4. Slots 1..5: role 0 → `SetupAi(local tribe, level 0, free colour, index = team = slot)`; other roles →
   `ResetToOpen(slot)` (state 0, kind open, colour = team = slot number, playerIndex 0xff).
5. State = 2. Host roles: gameName = local player name, `passwordMd5` = `SetPasswordHash` S 00413c60 of the
   join password string (`ConnectionSettings +0x18`): MD5 of it, or all zero when it is empty; then
   `BroadcastGameInfo`. Step 3 clears that string after hashing it, so at this point it is empty and the session
   digest becomes zero [known as decompiled: both steps use the same string object]. A game password is set
   afterwards from the room dialog: `SetGamePassword(text)` S 0040c220 (caller
   `SetupGameDialog::OnPasswordInputClosed` S 00452d00) hashes the text and, when the digest differs from the
   stored one, stores it (`SetPasswordHash`), runs `RefreshSlots` and `BroadcastGameInfo`.

The MD5 is the plain algorithm over the string's bytes, no salt, no terminator: `ai::crypto::MD5Hasher` =
`MD5Init` S 00428c40 (standard initial state `67452301 efcdab89 98badcfe 10325476`), one `MD5Update` over
(buffer, length) in `UpdateString` S 0041f1d0, `MD5Final` in `GetDigest` S 0041f180 [known for the calls, the
initial state, the additive constants of `MD5Transform` S 004284f0 (RFC 1321's table, `d76aa478 e8c7b756
242070db ...`) and the padding plus 64-bit bit count of `MD5Final` S 00428d40; the shift amounts were not
compared].

EventUserInformation payload, in wire order (`Serialize` S 00409950, reader S 00420230) [known]:

| Field | Type | Struct offset | Source on the joiner |
|---|---|---|---|
| playerName | string | +0x10 | `NComm_GetLocalPlayerName` S 0041f4e0 |
| guid | NetGUID raw | +0x2c | manager `+0x32c` |
| buildVersion | i32 | +0x40 | `NComm_GetBuildVersion` S 0041f230 = global S 008793c0 |
| buildChecksum | i32 | +0x44 | `NComm_GetBuildChecksum` S 0041f240 (`docs/data-loading.md` §3) |
| connectionType | i32 | +0x48 | `UserProfile_GetConnectionType` S 0041f220 = user profile `+0x94` (values 2, 3, 4 select a file transfer block size, §3.11) |
| tribe | i32 | +0x4c | `NComm_GetLocalTribe` S 0041f450 |
| avatarTribeGenderLevel | i32 | +0x50 | S 0041f260 |
| avatarColors | u32 | +0x54 | S 0041f2f0 |
| avatarId | i32 | +0x58 | S 0041f3e0 |
| passwordMd5 | 16 bytes | +0x60 | MD5 of the password typed for this join, or 16 zero bytes when none; the stored password is cleared after hashing |

In roles 3 and 4 the name, tribe and the three avatar values come from the local lobby avatar; while the lobby is
not in the village the tribe and the avatar values are 0 and the name keeps its last value. In the other roles the
name is the user profile's (`+0x40`), the tribe is the first entry of the tribe table and the avatar values are 0.
An empty name becomes `default` [known, S 0041f4e0, S 0041f450, S 0041f260, S 0041f2f0, S 0041f3e0].
avatarTribeGenderLevel packs three nibbles: `tribe << 8 | gender << 4 | level`; avatarColors packs eight nibbles,
from the lowest: four body colours (the map names them hair, skin, shirt, trousers), then four additional colours
[known for the packing; the colour names are the map's].

The build version global S 008793c0 has no writer in the binary: its five references are reads (xref list), and the
image holds the constant `0x00008780` (34688) [known]. It is not read from `network.ini`.

**Host handling of 0x30001** (`HandleEvent` S 0040e560) [known], checks in this order; a failed check ends the
handling:

1. `buildVersion` ≠ own → kick with reason `!VERSION MISMATCH`, then disconnect the sender.
2. `buildChecksum` ≠ own → `!CHECKSUM MISMATCH`, disconnect.
3. `passwordMd5` ≠ session `passwordMd5` (16-byte compare) → `!PASSWORD_MISMATCH`, disconnect.
4. `AssignSlotToJoiningUser` S 0040bb60: walk the six slots; a slot of kind ≠ open whose owner GUID equals the
   joiner's is **reused** (name, kind = human, GUID, playerId = sender net id; other fields, the slot state
   included, kept); otherwise the first slot of kind open is taken: `Init(tribe, senderNetId, guid,
   connectionType 4, name, colour = FindFreeColor, playerIndex = team = first entry of GetFreePlayerIndices)`
   — state 1, kind human, readyState 0, left-notice byte 0; the first entry is the lowest index below maxPlayers
   that no human or AI slot uses, or -1 when there is none (S 004137f0); no open slot → kick `!GAME FULL` and
   disconnect. Then the three avatar fields are stored.
5. Remove the GUID from the left-players list; slot connectionType = event value; `SetUserData(netId, name, guid,
   connectionType)` on the transport's user list; `RefreshSlots`; `BroadcastGameInfo`; notice
   `<name> <!Player joined game>`.

The handler tests neither the role nor the manager state: any peer that receives 0x30001 runs these steps (the
kick itself needs a host role) [known].

"Kick" = `KickPlayer(netId, reason, sendKickEvent = true)` S 0040b470 (host role, state 2, 3 or 4): sends
**EventKickUser** (0x30010; sender = local net id, sender slot 0) with the reason to that net id (never to the
host id). "Disconnect" = transport slot `+0x14` (`Disconnect` S 0041a2e0), which on the host drops that user's
TinCat connection; called with the host id or `0xEFFFFFEE` on the host it shuts the transport down, and on a
client it drops the client's own connection and sets the local net id to `0xEFFFFFEE` [known for the calls; the
API slots `+0x5c` and `+0x88` are TinCat's].

There is no check of the map at join time: the map is checked by the joiner when the first GameInformation
arrives (§3.6, 0x30003) [known].

`RefreshSlots` S 0040b5a0 (host) [known]: for slots below maxPlayers in state 5: role 0 → slot 0 becomes the local
human (`Init`, colour free, index 0), others AI; other roles → `ResetToOpen`. For slots at or above maxPlayers: an
occupant is kicked with `!GAME FULL`, and the slot is cleared (state 5, kind closed).

### 3.6 Session events (0x3000x)

Handler: `NComm_Manager::HandleEvent` S 0040e560. It first logs the event's text form, then switches on the type
id. It returns true (consumed) for every 0x30001..0x30012; for 0x20023 (after copying its value to the speed
multiplier `+0x3c` and recomputing `+0x34`) and every other id it returns false and the event goes to the game
listener [known]. "to host" = `SendEvent` to the host id; "broadcast" = `BroadcastEvent`;
"lockstep" = appended to the outgoing tick package and executed two net ticks later on every peer (§3.7).
Except where a row says "host", the handler does not test the role: the receiver side is defined by who is sent
the event. "Slot found by GUID" (`FindSlotByGuid(guid, true)` S 00413300) finds only a slot whose playerId is not
`0xEFFFFFEE`; the senders fill the sender slot field the same way, so it is -1 while the sender has no connected
slot.

| Id | Name (S 00421bd0) | Class | Sent by, how | Effect on the receiver |
|---|---|---|---|---|
| 0x30001 | NE_UserInformation | EventUserInformation | joiner, to host (`ConnectAndJoin`) | §3.5 |
| 0x30002 | NE_PlayerInformation | EventPlayerInformation | a player changing its own slot, to host (`SendEventPlayerInformation` S 00408c70, state 2) | ignored if the GUID is in the left-players list; slot found by GUID: tribe, team, colour, playerIndex applied, a changed tribe, team or colour also sets readyState 0 (rules in `docs/NCOMM_GAME_PROTOCOL.md`); host: `RefreshSlots` + `BroadcastGameInfo` |
| 0x30003 | NE_GameInformation | EventGameInformation | host, broadcast (`BroadcastGameInfo(false)` S 004090e0) | below |
| 0x30004 | NE_GameLoaded | Event1Integer | every peer after loading, to host (`SendGameLoadedEvent` S 00408e50, from `nMenu::Game::OnEnter` and after a rejoin) | slot[sender slot].readyState = 2 if the value ≠ 0 else 0; host: `RefreshSlots` + `BroadcastGameInfo`. The slot index is not checked |
| 0x30005 | NE_StartGame | EventGameInformation | host, broadcast (`BroadcastStartGame` S 0040ff90, state 3) | §3.8 |
| 0x30006 | NE_Chat_ToAll | EventText | any peer, broadcast (`SendChatToAll` S 00410410; empty text is not sent) | chat sink: `OnChatToAll(sender slot, text)` |
| 0x30007 | NE_Chat_ToAllied | EventText | any peer, one message per filled human slot with the sender's team value, the sender's own slot included (`SendTeamChat` S 00409f60) | shown only if `ArePlayersAllied(sender playerIndex, local playerIndex)` |
| 0x30008 | NE_Text_UserInSessionList | EventText | broadcast (`BroadcastUserListText` S 004100b0): one line per user with a non-empty name, `"* "` before the host's name, `"  "` before the others, `"\n"` after each; sent whenever the transport's user list changes (callers `UIS_SetUserData` S 0041a720, `UIS_RemoveUserData` S 0041cd40) | stored at manager `+0x344` |
| 0x30009 | NE_InGame_SendChecksum | EventUserChecksum | every peer, lockstep, first event of each outgoing package (`SendEventUserChecksum` S 004089c0; conditions in §3.7) | unless the GUID is in the left-players list: `ChecksumLog::Add(tick, guid, netId, checksum)` (`docs/sim/logic-core.md` §3.6) |
| 0x3000a | NE_InGame_PlayerLeavesGame | EventUserLeave | the leaving peer, to host (`NComm_SendEventUserLeave` S 00409240) | §3.10 |
| 0x3000b | NE_InGame_PlayerLeftGame | EventUserLeft | host: lockstep, or broadcast, or to the leaver (§3.10) | §3.10 |
| 0x3000c | NE_InGame_PlayerRemoveLogicData | — | no sender found | consumed, no action |
| 0x3000d | NE_InGame_ChangeNetTickLength | Event1Integer | host, lockstep (`Process_MainLoop` S 00410f70) | net tick length = value; ticks per net tick = speed × value (`docs/sim/logic-core.md` §3.2) |
| 0x3000e | NE_InGame_ClientReconnect | EventUserReJoinGame | rejoining client, to the new host (`ReconnectAndRejoin` S 004093a0) | §3.9 |
| 0x3000f | NE_PreGame_HostReconnectRestartAndSendGameInformation | EventGameInformation | new host, broadcast (`BroadcastGameInfo(true)`) | §3.9 |
| 0x30010 | NE_System_UserShouldKickHimself | EventKickUser | host, to one peer (`KickPlayer`); also built locally by a client without the map | below |
| 0x30011 | NE_PlayerReady | Event1Integer | a player toggling ready, to host (`SendPlayerReadyEvent` S 00408d80, state 2) | if sender slot ≠ -1: readyState = 1 when the value ≠ 0 and all assigned playerIndex values are distinct (`ArePlayerIndicesUnique` S 00413540), else 0; host: `RefreshSlots` + `BroadcastGameInfo` |
| 0x30012 | NE_StartLoading | EventGameInformation | host, broadcast (`BroadcastStartLoading` S 0040fe50, state 2) | §3.8 |

`BroadcastGameInfo(force)` S 004090e0 (host role, state 2..4) builds the event with type 0x30003 (`force` false) or
0x3000f (`force` true), sender = local net id, slot 0, copies the session, recomputes `settingsCrc`, broadcasts it
and then updates the LAN record or the lobby entry (§3.3) [known]. The fresh `settingsCrc` reaches the host's own
session through its local handling of the broadcast. 0x30012 and 0x30005 carry the sender's own slot instead of 0.

**0x30003 on the receiver** [known]:

1. Client not yet in a running match (`IsClient` and not `IsInGame`): for each of the six slots compare the stored
   owner GUID with the event's; changed from valid to invalid → notice `<old name> <!Player left game>`; from
   invalid to valid → `<new name> <!Player joined game>`.
2. The stored session takes the event's data (`AssignGameData`). The host stops here.
3. Client: look the map up by GUID in the local map folders (`GameFile_FindMapByGuidAnyType`); found → mapName =
   the local path. Not found: if `fetchMapFromHost` is set and `mapFileType` = 3, request
   `SAdK\maps\<mapName>.s2m` and `.bmp` (relative to `My Documents` on both sides, `docs/s2tftp.md`) from the
   host (§3.11) and set mapName to the still empty lookup result;
   otherwise dispatch a local EventKickUser with `!MAP NOT EXISTING`. No caller sets `fetchMapFromHost` in this
   build (`docs/NCOMM_GAME_PROTOCOL.md`).

Step 3 runs on a client on every GameInformation, also during the match [known].

**0x30010 on the receiver** [known]: message sink gets `<!You were kicked!> - <reason>`, both localised. In a
running match the peer then sends its own leave (0x3000a, §3.10); otherwise it disconnects
(`DisconnectIfActive` S 00409090) and runs `Shutdown(false)`.

Kick reasons in this function set: `!VERSION MISMATCH`, `!CHECKSUM MISMATCH`, `!PASSWORD_MISMATCH`, `!GAME FULL`,
`!COULD NOT RECONNECT`, `!MAP NOT EXISTING` [known strings].

### 3.7 Per-tick exchange (messages 1001 and 1002)

The gate `NComm_Manager::CanAdvanceTick` S 004088b0 and the step `NComm_Manager::AdvanceNetTick` S 00411990 are
specified in `docs/sim/logic-core.md` §3.2; the pseudocode there matches the code. As a protocol, for net tick
`N` (S = logic ticks per net tick):

```
every peer, while net tick = N:
    local commands are appended to the outgoing package (header tick N), behind its 0x30009 checksum event
every peer, at the logic tick that closes net tick N (the S-th accepted logic tick):
    execute the to-execute package of tick N-2, event by event
    host:    if a collected package for tick N-1 exists: send it to all as message 1002
             and append it to the own to-execute package of tick N-1
    client:  send the outgoing package (tick N) to the host as message 1001
    host:    append the outgoing package to the collected package of tick N
    net tick = N+1; start a new outgoing package: header N+1, then 0x30009
    drop packages and checksum history older than tick N+1-5; compare checksums
host, on message 1001 from net id X:
    if X owns no slot: log "Trying to add packages from user not in game", drop
    if the data is no package: drop
    append the events (header stripped) to the collected package of the header's tick; record X as contributor
any peer, on message 1002:
    append to the to-execute package of the header's tick (created if missing)
```

Gate, in the same terms: a peer may close net tick `N` only when its to-execute package of tick `N-2` exists and
holds at least one block (from `N ≥ base + 2`); the host in addition only when its collected package of tick `N-1`
holds a block of **every** slot whose playerId is not `0xEFFFFFEE` (from `N ≥ base + 1`). While the gate refuses,
no logic tick runs on that peer.

Points a reimplementation must keep [known unless noted]:

- A package is created per tick on demand; `AppendEvents` S 00412e80 refuses a block whose header tick differs
  from the target's and strips the 8-byte header of an appended block. A block without header is appended as it
  is to a target that has one (the immediate queue); a target without header accepts a block only while empty.
- `SendEventUserChecksum(tick)` S 004089c0 restarts the outgoing package: clear, header with `tick`. The 0x30009
  event is added only when a game listener is registered, the local net id is not `0xEFFFFFEE`, the manager state
  is 2, 3 or 4 and the local GUID owns a connected slot with a playerIndex. Its payload tick is the manager's net
  tick (`+0x2c`) at that moment, its checksum the listener's (`+0xc`) or 0 in role 0, its sender slot the local
  slot. Without those conditions the package holds the header only.
- Message 1001 and 1002 data that is no package (magics, 8 bytes) is dropped silently (`AddReceived` S 00412ae0).
- Commands of one tick execute in the byte order of the merged package: players in the order their blocks reached
  the host's collected package (the host's own block is appended when the host closes the tick), each player's
  commands in the order queued. The clients receive the merged bytes, so the order is the same everywhere
  [inferred].
- The host's own to-execute package of tick `N-1` is filled at the moment it sends message 1002, i.e. with
  whatever blocks had arrived by then. The gate guarantees that these are the blocks of all slots.
- `QueueGameCommand(ev, force)` S 00408b10: without `force` a command is dropped while `IsGameHanging`; in role 0
  it is dispatched at once; otherwise appended to the outgoing package.
- `ExecuteEventPackage` S 00410530 offers each event to `HandleEvent`, then to the game listener; it stops at the
  first event it cannot construct (unknown class tag) or cannot deliver (no listener), leaving the rest of the
  package unexecuted.
- The immediate queue (message 1000) is executed once per frame in `Process_MainLoop` with the same function,
  outside the lockstep; then it is cleared and gets its header (tick `0xFFFFFFFF`) again.

Input delay, default tick length and the adaptation of the net tick length to the measured ping (event 0x3000d):
`docs/sim/logic-core.md` §3.2.

### 3.8 Match start

1. **Room complete.** Every frame the room dialog of every peer tests: all slots ready, playerIndex values
   distinct, colours distinct, StartLoading not yet received; when all hold and the peer is the host it calls
   `BroadcastStartLoading` (`LobbyMenu::SetupGameDialog::Update` S 00457a00) [known]. The dialog's other
   conditions belong to `docs/NCOMM_GAME_PROTOCOL.md` and `docs/MATCH_START.md`.
2. **0x30012 StartLoading** (`BroadcastStartLoading` S 0040fe50; host role, state 2) [known]: the transport's
   `CloseSession` (S 0041a520: two TinCat calls, API slots `+0xe4`(0) and `+0x64`(1); [inferred] they stop further
   logins) ; a copy of the session gets `AssignRandomPlayerIndicesAndTeams` S 00413930 — `srand(time)`, then for
   each slot below maxPlayers: a missing playerIndex becomes a random free index, a team of -1 becomes
   `rand() % maxPlayers` — and a fresh `settingsCrc`, and is broadcast. Receiver (host included): session = event
   data, `+0x28` = connected humans (`CountConnectedHumans` S 004133c0: kind human and playerId ≠ none), flag
   `+0x3cc` = 1. The random values therefore reach the host's own session through its local handling of the event
   [inferred from `BroadcastEvent`]. They use the C runtime generator, not the simulation's.
3. **Loading.** The screens react to `+0x3cc` (referee registration: `docs/MATCH_START.md`) and enter the game
   screen. `nMenu::Game::OnEnter` S 005eed00 calls `BeginGameStarting` (state 3), registers the chat and message
   sinks, builds the world (which registers the game listener, `docs/sim/logic-core.md` §3.2) and then sends
   **0x30004 GameLoaded(1)** to the host, unless the menu system's flag `+0xa4` is set (the map names it
   `uiSuppressed`; then no GameLoaded is sent) [known]. The host marks the slot loaded and broadcasts the session
   (0x30003).
4. **0x30005 StartGame.** The host broadcasts it once every slot below maxPlayers is loaded
   (`AreAllSlotsLoaded` S 00413500: human slots need readyState 2; AI and closed slots pass; an open slot blocks),
   every frame until its own state changes (`nGame::System::Update`, `docs/sim/logic-core.md` §3.2). Receiver:
   `SendEventUserChecksum(0)` (outgoing package of tick 0 with the checksum of the loaded world), session = event
   data, `+0x28` = connected humans, then the listener's start slot (`+8`, skipped when no listener is
   registered) → `BeginGameRunning` S 0040b270: net tick, base tick, sub-tick, last tick time (`+0x44`) and last
   logic tick number (`+0x48`) = 0, `+0x28` recounted, in sync = false, state 4, checksum log cleared, ping timer
   (`+0x24`) = now, ping samples and traffic statistics cleared [known]. A second 0x30005 finds state 4 and
   changes nothing but the session copy and the outgoing package [inferred: `BeginGameRunning` refuses in state 4,
   `SendEventUserChecksum(0)` still runs].

No peer waits for the others before running net ticks 0 and 1; the gate applies from the end of net tick 1 on the
host and of net tick 2 everywhere [known, §3.7].

### 3.9 Host loss and reconnect

Detection and election are done by TinCat's `Reconnector` module, which the transport starts in `StartUp` and
feeds with every connection event and every received message. It reports through two callbacks of
`NComm::TinCatReconnector` [known]:

- `cb_BecameServer` S 004259b0 → reconnector state 1, no address: this peer is to become the host;
- `cb_ReconnectTo(ip0..ip3, port)` S 00425aa0 → state 2 with that address: this peer is to rejoin there.

The module fires on a client whenever its connection (the one to the host) is reported removed, and chooses
the first entry of the peer list the host last sent, i.e. the client that connected first; no code marks a
preferred successor (`Reconnector::HandleRemovedConnection` T 10010b80, `Reconnector_ElectNewHost` T 10010930;
§10 item 2) [known].

`TinCatNetwork::Process` S 00419e10 polls the reconnector state every frame [known]: state 1 →
`NComm_Manager::BeginReconnect` S 00408f60 once (manager reconnect state = 1, timer 0, address -1); state 2 →
`Reconnector_RestartAsClient(ip, port)` S 0040a110 once (reconnect state = 1, timer = `timeClientWaits`, address
and port stored). Both need manager state 3 or 4; if the call fails, `Process` returns false and the manager
shuts the transport down, sets state 0 and the error latch (S 00410f70) — this is what happens when the host is
lost in the room [known]: no notice is given, and the lobby's room dialog closes because the state is no
longer 2 (`match-setup-room.md` §10 item 1).

Manager reconnect state machine, run per frame by `Process_MainLoop` S 00410f70 in manager states 3 and 4 [known]:

| State | Log name | Behaviour |
|---|---|---|
| 0 | — | normal |
| 1 | eReconnectStateInitialisedAndWaitingOnExecutingOldPackages | Logic ticks continue as long as the gate allows (only the to-execute package of `N-2` is asked for); at a tick boundary nothing is sent or collected. When the gate refuses, the state 4 action runs in the same frame |
| 4 | eReconnectStateStartLocalServer | Address valid → **rejoin** (below); on failure `Reconnector_DropRemotePlayers`. Address invalid → **become host** (below); on failure `Shutdown(true)` |
| 3 | eReconnectStateClientWaiting | rejoined client waits for 0x3000f |
| 2 | eReconnectStateHostWaitingOnClientsToJoin | new host waits for the others (below) |

**Rejoin** (`ReconnectAndRejoin(addr, port)` S 004093a0) [known]:

1. Shut the transport down; wait `timeClientWaits` seconds while pumping it (`NComm_WaitSecondsPumping`
   S 00416190); `StartUp(isHost = 0, online = role is 3 or 4)`.
2. Up to `timesClientRetries` attempts: `ConnectToServer(addr, port)`; on failure wait `timeClientWaitsFailed`
   seconds and retry.
3. On success send **EventUserReJoinGame** (0x3000e: sender = new local net id, slot -1, own GUID, current net
   tick) and **GameLoaded(1)** (0x30004) to the host; role = 3 (if it was 3 or 4) or 1.
4. All six slots: the slot of the old host (playerId `0xEFFFFFCC`) → state 3 (left), playerId none; the own slot
   (by GUID) → playerId = new local net id; every other slot, whatever its kind → state 2 (dropped), playerId
   none. `ResetToState` also sets readyState 2.
5. Common reset (below); reconnect state = 3, timer = now.

The function returns false, without touching slots, role or tick state, when the manager state is not 3 or 4, when
`StartUp` fails or when all attempts fail; in the last case the transport is left started as an unconnected
client [known as decompiled: the slot loop is entered only from the successful connect]. `Process_MainLoop` then runs
"rejoin failed".

**Become host** (`Reconnector_RestartAsServer_DoAction` S 0040b700) [known]:

1. Shut the transport down; `StartUp(isHost = 1, online)`; role = 4 (if it was 3 or 4) or 2.
2. Slots: the old host's slot and slots already in state 3 → state 3, playerId none; the own slot → playerId =
   local net id (now `0xEFFFFFCC`), state 1; every other human slot → state 2, playerId none.
3. Common reset; `+0x28` (expected checksums) = 1; timer = `timeHostWaitForClients`; reconnect state = 2.

**Common reset** (both paths) [known]: `SendEventUserChecksum(netTick)` (the outgoing package restarts; commands
queued in it are lost), both package lists cleared, an empty collected package for `netTick - 1` created, base
tick = net tick, net tick length = config `+0x24` (4), ticks per net tick = speed × that, sub-tick = 0, last tick
time = 0, ping timer = now, ping samples and traffic statistics cleared, in sync = false, checksum log cleared.

**New host waiting (state 2)** [known]: each frame, "all joined" = no human slot that is neither filled nor in
state 3. When all joined, or the timer has run out: every human slot that is not filled gets state 3 and one
command **0x2002B GE_PlayerLeftGame(playerIndex)** in the outgoing package (role 0: executed at once);
`RefreshSlots`; `BroadcastGameInfo(true)` = event 0x3000f. The timer is decremented by the frame time afterwards.

**0x3000e on the new host** [known]: if the event's net tick ≠ own net tick, or no slot has the GUID (connected
or not, any state): kick with `!COULD NOT RECONNECT`. Otherwise slot.playerId = sender net id, slot.state = 1, and
the user list gets
the name, GUID and connection type of the slot. The GameLoaded(1) that follows makes the host broadcast the
session (0x30003).

**0x3000f on every peer** (the new host included, through its local handling) [known]: for each slot of the event
that is human, not filled and whose left-notice byte is 0: notice `<name> <!Player left game>`, byte = 1. Then
session = event data, `+0x28` = connected humans, reconnect state = 0, timer 0, address -1. Ticking resumes; the
gate skips its two tests for one resp. two net ticks after the new base tick, as at match start.

**Rejoin failed** (`Reconnector_DropRemotePlayers` S 004109b0) [known]: reconnect state = 4 with the address
cleared, so the next frame runs "become host". For slots 0..4 (the loop stops before slot 5) whose playerId is not
0 and whose GUID is not the local one: a valid GUID with a connected playerId is treated as left (in a running
match: expected checksums -1 and GUID to the left-players list unless already there, its checksums removed; then
the notice; on a host role also a broadcast 0x3000b and `RemovePlayerById`, as in `HandlePlayerLeft`, §3.10); the
notice is shown if not yet shown; one 0x2002B command with the slot's playerIndex goes into the outgoing package
(role 0: executed at once). Since "become host" restarts the
outgoing package, these commands are discarded and are issued again by state 2 when its timer runs out
[inferred].

Consequences [inferred]: the simulation stands still on a peer from the stall in state 1 until 0x3000f. The only
consistency check of the rejoin is the equality of net tick numbers; logic tick counters are not compared
(`docs/sim/logic-core.md` §3.2, §10). Players who do not return within `timeHostWaitForClients` lose their
headquarters through 0x2002B (`docs/sim/game-commands.md` §3.4).

### 3.10 Leaving, kicks and connection loss

**Voluntary leave** [known]. The quit requester (`nMenu::Requester::Update` S 006009b0), when confirmed in a
running match, calls `NComm_SendEventUserLeave` S 00409240: **EventUserLeave** (0x3000a: sender net id, sender
slot, own GUID) to the host; leave requested (`+0x3ad`) = 1, completed (`+0x3ae`) = 0, timeout `+0x3b0` = **3.0** s;
a reconnect in progress is cancelled (state 0). The requester shows `!Finalizing...` and waits until `+0x3ae` is
set, then leaves (which ends in `Shutdown`). `Process_MainLoop` counts the timeout down by the frame time and sets
`+0x3ae` when it reaches 0.

**0x3000a on the host** [known]: player index = the sender slot's playerIndex (`NComm_Event_GetSenderPlayerIndex`
S 00412490), or, if that is -1, the index found by GUID.

- Match running (`IsInGame`): build **EventUserLeft** (0x3000b: sender = host net id and slot; payload playerIndex,
  the leaver's net id, the leaver's GUID) and append it to the outgoing tick package (lockstep).
- Otherwise (room, loading), if the index and its slot are found: `ResetToOpen(slot)`, `RefreshSlots`,
  `BroadcastGameInfo`, send 0x3000b to the leaver only, notice `<name> <!Player left game>`.

**0x3000b on a receiver** [known]:

1. Not the host: `HandlePlayerLeft(guid, netId, playerIndex, false)` (below).
2. If the GUID is the local one and leave requested is set: leave completed = 1.
3. Host in role 2 or 4: queue command **0x2002B GE_PlayerLeftGame(playerIndex)** in the outgoing package.

`HandlePlayerLeft` S 00410720 [known]: needs a valid GUID that owns a connected slot (playerId not
`0xEFFFFFEE`). In a running match (joined and state 4): if the GUID is not
yet in the left-players list, expected checksums (`+0x28`) -1 and the GUID is added; its entries are removed from
the checksum log. If the slot's left-notice byte is 0: notice, byte = 1. On a host role: broadcast 0x3000b (with
the slot's playerIndex when -1 was given; its header carries the leaver's net id and slot as sender) and
`RemovePlayerById(netId)` S 00409750 — in a running or loading match (joined and state ≥ 3) the slot gets state 3
with playerId none, otherwise it is reopened (colour and team 0xff) — followed by `BroadcastGameInfo`.

**Connection events** (transport callbacks) [known]: `cb_LoggedOut` S 0041b990, `cb_ConnectionLost` S 0041bb20 and
`cb_ConnectionClosed` S 0041bcc0 first inform the reconnector module (`HandleRemovedConnection`, when the API has
one). If that call returns 1 and the reconnect state is non-zero, nothing more happens: the object tested is
the client's `NComm::TinCatReconnector` (`+0x04` the TinCat `Reconnector`, `+0x0c` state: 0, 1 after
`cb_BecameServer` S 004259b0, 2 after `cb_ReconnectTo` S 00425aa0), so this branch is taken only while a
host change is under way [known]. On the host `Reconnector::HandleRemovedConnection` T 10010b80 removes the
peer, rebroadcasts the peer list and returns 1 with the state still 0, so the removal below always runs. In every other case (a return value other than 1 is also logged as
`Reconnector could not handle ... connection!`) the user is removed (`UIS_Remove` S 0041d4c0, vtable `+0x64`)
and, for the last two, `CancelFileTransfer(netId)` (vtable `+0xa8`, S 00419130) aborts the file transfer with
that peer, or with the host when the local peer is a connected client. `UIS_Remove` [known]: on a connected
client whose own net id is the removed one it only sets the local net id to `0xEFFFFFEE`; otherwise it drops the
user's ping samples and list entry (which broadcasts
0x30008) and calls `HandlePlayerLeft(guid, netId, -1, false)`, and sets the local net id to `0xEFFFFFEE` if the
removed id is the local one. On the host this is the path that turns a vanished client into 0x3000b (broadcast,
immediate) and then 0x2002B (lockstep).

So a leaving player is announced twice on the host when it leaves cleanly: once through its 0x3000a (lockstep
0x3000b) and once through its disconnect (immediate 0x3000b). The left-players list and the notice byte make the
second one change nothing except that the host queues a second 0x2002B [known]: the 0x3000b case of
`HandleEvent` S 0040e560 queues the command on a host in roles 1..4 without looking at the slot, the lockstep
0x3000b does not touch the slot on the host (it calls `HandlePlayerLeft` only on a non-host), and the
disconnect path finds the slot by GUID and broadcasts again (S 00410720). Whether the second command has
an effect is decided by its executor (no headquarters left → nothing, `docs/sim/game-commands.md`).

After a player has left, its GUID stays in the left-players list for the session: its checksum events and its
0x30002 are ignored, and `cb_ConnectionClosed` uses the list to pick the second argument of `UIS_Remove`, which
that function does not read [known]. A later 0x30001 with that GUID removes it from the list again (§3.5).

**Kick** [known]: only the host can kick (`KickPlayer` S 0040b470; callers: the checks of §3.5 and §3.9,
`RefreshSlots`, and the room's `SetSlotSetup` S 0040bcd0). With an event the kicked client removes itself (§3.6,
0x30010). With `sendKickEvent = false` the
transport drops the connection directly (`TinCatNetwork::KickPlayer` S 0041a620).

**Hang display** (`GetHangReason` S 0040d260, shown by `nMenu::Game::DrawNetworkHangNotice` S 005ebf90) [known].
Nothing is returned unless `IsGameHanging` holds (`docs/sim/logic-core.md` §3.2). All texts are localisation keys;
`N` = net tick, `B` = base tick.

| Condition | Text |
|---|---|
| error latch (`+0x20`) set | `!Network - Major Error Occured`, new line; the rows below still apply |
| reconnect state ≠ 0 | `!Network - Reconnecting`, then by state: 1 `!Executing old packages` · 2 `!Waiting for clients` · 3 `!Waiting for restart` · 4 `!Restart as local server` |
| reconnect 0, state 4, `N ≥ B+2`, to-execute package of `N-2` missing or without block | `!Waiting for start` if `N-B < 5`, else `!Waiting on packets` |
| reconnect 0, state 4, host role, `N ≥ B+1`, collected package of `N-1` missing | `!NetworkBasics/MessageStartingGame` (only if `N-B < 5` and `!Waiting for start` was not added), then `!NetworkBasics/MessageHangingServerWaitingOnAllClients` |
| same, collected package of `N-1` present | `!Waiting for game start!` (same condition as above), then for every human slot not in state 3 whose block is missing: `!NetworkBasics/MessageHangingHostWaitingForUser <name> !` |
| reconnect 0, state 3 | the text is replaced by `!Waiting for game start!` |
| nothing added | `!Unknown Hang Reason!` |

The per-user row tests the package's contributor list with the slot's **playerIndex**, while the list holds net
ids (§2.6) [known as decompiled]; with net ids that are never small integers the test fails for every human slot,
so every remaining human is listed [inferred].

### 3.11 File transfer (S2TFTP, message 1003)

Specified in `docs/s2tftp.md`; the packet layouts there match the code [known: `SendRequest` S 00425f00,
`SendData` S 00425d10, `SendAck` S 00425df0, `SendError` S 00425e70, `OnReceive` S 00428110, `OnData`
S 00427cf0, `OnAck` S 00427f10]. Summary as a protocol:

| Opcode (u16) | Rest of the packet | Direction |
|---|---|---|
| 1 WriteRequest | — | never sent; answered with Error 5 `!TFTP_ERROR_NO_WRQ_ALLOWED` |
| 2 ReadRequest | string file name (relative to the owner's `My Documents`) | requester → owner |
| 3 Data | u16 block size, u16 block number (from 1), u16 total blocks, payload | owner → requester |
| 4 Ack | u16 block number | requester → owner |
| 5 Error | u16 code, string message | either |

- One session per peer net id, one transfer per peer at a time; further requests are queued, and one queued
  request is tried per frame from `TinCatNetwork::Process` while the transport's `IsConnected` holds (local net id
  neither host, none nor 0, i.e. on a connected client; `ProcessQueue` S 00427400).
- Stop-and-wait: the owner sends block `n+1` when the Ack of block `n` arrives; it is finished when the Ack of
  block `totalBlocks` arrives. The requester acks every block, re-acks a repeated block number without writing
  it, ignores lower numbers, and is finished when a block is **shorter than the block size**.
- Block size by the owner's connection type: 2 → 0x400, 3 → 0x800, 4 → 0x1000, other → 0x200
  (`BeginSend` S 00426a30). Total blocks = `size / blockSize`, +1 if there is a remainder
  (`S2Tftp_Session_ReadNextBlock` S 00426ac0). A file whose size is a multiple of the block size therefore never
  completes on the requester.
- Error codes: 0 file not found, 1 read error, 2 write error, 5 no write requests, 6 no connection (Data received
  while not receiving).

---

## 4. Update order

**Per frame**, `NComm_Manager::Process_MainLoop` S 00410f70, called from both frame functions
(`CApplicationEx::FrameTick_Menu` S 00401780, `FrameTick_InGame` S 004018e0; position in the frame:
`docs/sim/logic-core.md` §4.1) [known]:

1. No transport: return (true in state 0, false with a log otherwise).
2. Transport `Process` S 00419e10: pump TinCat (API slot `+0x28`), which delivers received messages and
   connection callbacks synchronously [inferred] — messages 1000 fill the immediate queue, 1001 and 1002 the
   package lists, 1003 the file transfer; poll the reconnector; prune traffic statistics; start one queued file
   request. A false result shuts the transport down, sets state 0 and the error latch; return.
3. Leave timeout countdown (§3.10).
4. Execute the immediate queue (`ExecuteEventPackage`), clear it, rewrite its header.
5. In manager state 3 or 4 with reconnect state ≠ 0: the reconnect state machine (§3.9).
6. Not in state 3, reconnect state 0: every `pingFrequencyGame` (state 4) or `pingFrequencyMenu` (other states)
   seconds: transport slot `+0x84` (TinCat API slot `+0xb0`, to all users on a host with users, else to the host
   on a connected client: `TinCat_CTRL::Send_Ping` T 1000a2a0, the ping request [known]), and on a host in state 4 the net tick length adaptation
   (`docs/sim/logic-core.md` §3.2).

**Per logic tick**, from `NLogic::System::Update`: `AdvanceNetTick(logicTick)` after the tick counter increment
and before any subsystem update; at a net tick boundary it executes the package of tick `N-2`, exchanges packages
and compares checksums (§3.7).

**On session start**: `Shutdown(false)` → `StartUpNetwork(role)` → `ConnectAndJoin`, in one function, in nine of
the eleven callers of `StartUpNetwork` (e.g. `nMenu::FreeGamePanel::StartFreeGame` S 005e7350;
`ServerList::CreateGameServer` S 0046aaa0 and the two `GameServerInfo::JoinGame*` functions stop at the first step
that returns false) [known]. The exceptions [known]: `nMenu::Main::HandleButtonClicks` S 005e27c0 runs only
`Shutdown(false)` and `StartUpNetwork(0)` when the campaign, load or free game panel is opened (three call sites;
the session then waits in state 1 until the panel's start function runs the full sequence), and
`GameServerConnection::OnLoggedIn` S 0048edf0 runs `StartUpNetwork(3)` and `ConnectAndJoin` without a `Shutdown`
and without testing either result. **On match start**: §3.8. **On load of a savegame**: the same offline sequence
with role 0; no session state is read from the file (§7).

---

## 5. Inputs and outputs

Consumes:

- from the UI: room actions (`SendEventPlayerInformation`, `SendPlayerReadyEvent`, `SetSlotSetup`,
  `SetGameSettings`, `SetWager`, `SetGamePassword`, `KickPlayer`), chat (`SendChatToAll`, `SendTeamChat`), the quit
  requester (`NComm_SendEventUserLeave`);
- from the game system: commands through `QueueGameCommand` (`docs/sim/game-commands.md` §3.1), the world checksum
  through the listener's slot `+0xc`, `BroadcastStartGame`, `SendGameLoadedEvent`;
- from the lobby layer: the join address and password (`ai::ncomm::ConnectionSettings`), the game id
  (`SetGameIdAndBroadcast` S 0040c320), the referee's game seed (`SetGameSeedIfState2`);
- from the user profile: connection type, and outside the lobby roles the player name; from the local lobby
  avatar (roles 3 and 4): player name, tribe, avatar look, avatar id (§3.5);
- from TinCat: received data, login / logout / connection lost / closed, ping results, reconnector decisions;
- from files: `network.ini` (§6); the build checksum over scripts and settings (`docs/data-loading.md` §3).

Produces:

- to the game listener: every event `HandleEvent` does not consume, i.e. all `0x2000x` commands (0x20023 after the
  manager has taken the speed from it), in package order; the start-game call;
- to the simulation indirectly: command 0x2002B for a player who left or did not return;
- to the UI: the session description (slots, settings) through `GetGameInformation` S 004084b0, the StartLoading
  flag, `IsGameHanging` and its reason text, chat lines (chat sink), notices (message sink: joined, left, kicked,
  desync, resync), the user list text, per-user ping and traffic statistics;
- to the match setup: the six slots are read into the load descriptor
  (`SetupGameDialog::SetupSession`, `docs/NCOMM_GAME_PROTOCOL.md`);
- to the lobby and referee layers: game id, wager, avatar ids, slot data for `RegisterGame` and the server list
  entry (`docs/MATCH_START.md`).

---

## 6. Data-driven parameters

`[data]\settings\network.ini` (`data/game/settings/network.ini`, plain text), read by
`NComm_NetworkConfig_LoadFromIni` S 0041ede0 at every `StartUpNetwork` into manager `+0x360` [known]:

| Section, key | Config offset | Default in code (S 0040a390) | Fallback of the ini read | Value in the examined install |
|---|---|---|---|---|
| `[Basics] gamePort` | +0x00 | 5479 (0x1567) | 5479 | 5478 |
| `[Broadcast] broadcastPort` | +0x04 | 6582 (0x19b6) | 6582 | 6582 |
| `[Broadcast] broadcastTimeout` | +0x08 | 10000 | 10000 | 10000 |
| `[Ping] pingFrequencyMenu` (s) | +0x0c | 10.0 | "10.0" | 10.0 |
| `[Ping] pingFrequencyGame` (s) | +0x10 | 3.0 | "2.5" | 2.5 |
| `[Reconnector] timeHostWaitForClients` (s) | +0x14 | 30.0 | "30.0" | 30.0 |
| `[Reconnector] timeClientWaits` (s) | +0x18 | 3.0 | "3.0" | 3.0 |
| `[Reconnector] timesClientRetries` | +0x1c | 5 | 5 | 5 |
| `[Reconnector] timeClientWaitsFailed` (s) | +0x20 | 4.0 | "4.0" | 4.0 |
| — (no key) net tick length after a reconnect | +0x24 | 4 | — | — |
| — (no key) latency scale | +0x28 | 1.0 | — | — |
| `[Lobby] url` | +0x2c | "81.3.59.139:8777" | same | changed by the maintainer |
| `[Lobby] patchlevel` | +0x48 | -1 | 42 | 9212 |

The examined install is a working copy pointed at the revival server; its `gamePort`, `url` and `patchlevel` need
not be the shipped values (a second file next to it, `network - Copy.ini`, has the same keys with
`gamePort = 5479` and `url = "www.diesiedler2lobby.de:8777"`, quotes included, and otherwise the same values)
[known, both files]. The integer keys are read with `GetPrivateProfileIntA`, the float keys and `url` with
`GetPrivateProfileStringA` (floats through `atof`), so a missing key or section yields the fallback column
[known, S 0041ede0]. The examined `network.ini` starts with a UTF-8 byte order mark (`EF BB BF`) directly before
`[Basics] gamePort = 5478`, and a second `[Basics]` section further down has `gamePort=5479`. `GetPrivateProfileIntA`,
called in the game process on test files, does not find a section whose line follows the mark directly (it
yields the fallback), and with duplicate sections it takes the first one it finds [live, 2026-10-14]. So the
first section of the install's file is hidden and the effective `gamePort` is 5479, from the second section or
the fallback (both 5479), not 5478 [live, 2026-10-14]. A remake's reader should strip the mark.

Code constants [known]: TinCat module id `0x27d9`; message types 1000..1003; package magics `0x5332`, `0x4b38`;
six slots; initial net tick length 4 (1 offline); package and checksum history of 5 net ticks (S 00411990); leave
timeout 3.0 s (S 00409240); hang threshold 2.0 s (S 00408860); package buffer 0x400 bytes, growing by 0x80.

Localisation keys used for notices and kick reasons are listed in §3.5, §3.6 and §3.10; their texts are in the
game's string tables (`docs/data-loading.md`).

---

## 7. Save and load

Nothing of the session is in a save game: not the slots, GUIDs, game id, seed, net tick, queued commands or
checksum log (`docs/sim/save-format.md` §7, `docs/multiplayer-save.md`) [known there]. A network match offers no
save or load (three role-0 checks, `docs/multiplayer-save.md`), and `NComm::EventSaveGame` has a deserialiser but
no creator or handler.

Loading a save starts a fresh role 0 session (`Shutdown(false)`, `StartUpNetwork(0)`, `ConnectAndJoin`), whose
slots are rebuilt by `ConnectAndJoin` / `RefreshSlots` (slot 0 the local human, the rest AI placeholders) and then
overwritten by the match setup [inferred from the callers `nMenu::Main::ContinueLastSavegame` S 005dfef0 and
`nMenu::System::StartPendingMap` S 005d9fd0; the setup itself is not part of this document]. The net tick state
restarts at 0 with tick length 1; commands of an offline game are never queued, so there is nothing to carry over.

---

## 8. Determinism notes

The session layer is the mechanism that keeps simulations identical; it has four contact points with simulation
state:

1. **Command execution order and time.** Commands enter the simulation only through `ExecuteEventPackage` at a net
   tick boundary (network) or directly from `QueueGameCommand` (offline). Order = byte order of the merged package
   (§3.7). A remake must reproduce: one merged, ordered command list per net tick, executed by all peers at the
   same logic tick, before that tick's subsystem updates.
2. **Session values that feed the world.** The slot table (playerIndex, tribe, colour, team, kind, AI level) and
   the settings define the players of the match; `gameSeed` seeds the chest contents of a network match
   (`docs/MATCH_START.md`). All peers take them from the host's 0x30012 / 0x30005, never from local state.
3. **0x3000d and 0x20023** change how many logic ticks form a net tick; they travel in packages, so they apply at
   the same boundary everywhere.
4. **0x2002B** (player left) is a normal lockstep command, but it is issued by the host from non-synchronised
   input (a disconnect, a timer). That is safe because only its position in the package matters.

It does not use the simulation's random generator. The only random draw is the C runtime's `rand()` seeded with
the wall clock in `AssignRandomPlayerIndicesAndTeams`, on the host only, and the result is distributed [known,
S 00413930].

Not synchronised, and harmless for the simulation [inferred]: the immediate queue (message 1000) is executed at
frame time, so room and chat events, GameInformation updates, 0x3000b notices and the expected-checksum count
(`+0x28`) can change at different logic ticks on different peers. The count only affects the desync *report*, not
the simulation; a transient "not all received" / "too much received" report around a leave is possible
[inferred]. Wall-clock values (ping timer, leave timeout, hang threshold, reconnect timers) never enter the
simulation.

The checksum exchange detects divergence but repairs nothing: after `!DESYNC DETECTED` the match continues
(`docs/sim/logic-core.md` §3.6).

---

## 9. Notes for a Godot reimplementation

- **What must be reproduced exactly** for the simulation to behave like the original: the lockstep contract of
  §3.7 (two-net-tick command delay, execution at the closing logic tick of a net tick before the subsystem
  updates, host-defined order), the default of 4 logic ticks per net tick and its change through 0x3000d /
  0x20023, command 0x2002B for leavers, and the rule that offline commands execute immediately. None of this
  depends on the wire format.
- **What may be replaced freely**: TinCat, the class-tag serialisation, raw vftable pointers inside GUIDs, the
  S2/8K magics, the host-migration scheme, S2TFTP. A remake that does not talk to original clients can use
  Godot's `ENetMultiplayerPeer` (reliable ordered channel) with the host as authority: one RPC or packet type
  each for "immediate event", "client tick package", "merged tick package"; `PackedByteArray` or
  `var_to_bytes` for encoding. Keep the three logical channels separate, because their ordering guarantees
  differ.
- **If wire compatibility with the original client is wanted** (mixed matches, or the stub's host bridge): the
  formats of §3.2 are complete for the event classes; a GUID is 20 bytes of which the first 4 are the sender's
  vftable pointer, which the original reader stores as the vftable pointer of its own object (§3.2). Write
  `0x007d42b4` there, the value this build writes (little-endian `b4 42 7d 00`); whether another value is harmless
  is open (§10); strings are
  u16-length byte strings in the game's 8-bit code page [inferred for the code page: the bytes are copied without
  conversion]; the TinCat framing itself is specified in
  `docs/LOBBY_PROTOCOL.md` and is a prerequisite.
- **Session description**: model it as one resource owned by the host and replicated whole on every change (the
  original sends all six slots and all settings every time; it is small). Identify players by a persistent GUID,
  not by the peer id, so that a reconnect can reclaim a slot.
- **Join checks**: reproduce the three gates as (protocol version, content hash, password hash). The content hash
  of the original covers Lua scripts and XML settings (`docs/data-loading.md` §3); a remake should hash its
  converted rule data instead and must include everything that can change simulation results.
- **Hardening the original lacks** and a remake should add: bind the sender of an immediate event to the
  transport peer (the original trusts the id in the body, §3.1); bounds-check slot indices (0x30004) and string
  and blob lengths; reject duplicate blocks of one player for one tick; verify `settingsCrc` or drop it.
- **Stall handling**: expose "waiting for player X" from the gate (which slot's block is missing) and a timeout
  policy. The original has no timeout for a silent but connected client; it relies on TinCat reporting the
  connection loss [inferred].
- **Host migration** is optional. If wanted, the original's contract is: every peer keeps executing what it has,
  stalls, the elected peer reopens the session as host, the others rejoin with (GUID, net tick), the new host
  waits up to `timeHostWaitForClients`, removes the missing players with 0x2002B and broadcasts the session; all
  resume with a fresh package window and net tick length 4. Its weak point is that peers may have stalled in
  different net ticks (§10); a remake should exchange the last executed tick and resend missing packages, or
  transfer state.
- **Desync handling**: keep the per-net-tick checksum (cheap, already specified) and add what the original lacks,
  a state dump on both sides and optionally a resync by state transfer (`docs/multiplayer-save.md`).
- **File transfer**: use Godot's own means (HTTP download or chunked RPC); only the rule "a joiner without the map
  can fetch it from the host" is worth keeping.
- **Converter output**: none. This subsystem reads no asset; `network.ini` values become project settings (ports,
  ping period, reconnect timers).

---

## 10. Open questions

1. Answered: a client's message never reaches another client directly. In client mode the kernel sends every
   message, whatever its destination, over its one connection to the server, i.e. the host (`KRNL_SendMessage`
   T 10003cc0). The host's kernel routes an inbound custom-data frame by its destination
   (`KRNL_RouteCustomData` T 10005140): server or local → delivered to the host only; `0xEFFFFFDD` → sent to
   every logged-on user except the sender (`KRNL_SendToAllUsers` T 10003bc0) and delivered to the host as well;
   any other id → sent to that user. So chat from a client (`SendChatToAll` S 00410410 → `BroadcastEvent`
   S 0040fd80, which also applies the event locally) goes client → host → the other clients [known]. Not read:
   that API slots `+0x98` / `+0x9c` end in `KRNL_SendMessage` with kernel type 2.
2. Answered (the rules; that a migration succeeds across real networks is a live question): the host keeps a
   peer list, one entry per connected client in connection order (`HandleAddedConnection` T 10010ae0), each
   with the client's address as the host sees it and the port the client announced (subtype 4), and sends
   the whole list to all clients after every change (`Reconnector_BroadcastPeerList` T 10010890, module 0x61,
   message 0x5e7b). A client that is told its connection was removed (`HandleRemovedConnection` T 10010b80; a
   client has only the connection to the host) runs `Reconnector_ElectNewHost` T 10010930: the first entry
   with state 2, else the first entry of the list; no entry → no migration. State 2 is set only by
   `SetPreferredNextServer` T 10010be0, which the game never calls, so the successor is always the client
   that joined first. The elected client gets `cb_BecameServer` S 004259b0 (reconnect address -1), every
   other one `cb_ReconnectTo` S 00425aa0 with that entry's address and port. The lobby server takes no part:
   the messages are peer to peer, and the restart as host (`Reconnector_RestartAsServer_DoAction` S 0040b700)
   only restarts the transport and re-arms the session; it registers no game server [known].
3. Answered (`docs/sim/logic-core.md` §3.2, Reconnect; its §10 Q4): two surviving peers that stalled in different
   net ticks cannot both stay. The net tick does not move after the stall, `ReconnectAndRejoin` S 004093a0 sends
   it in 0x3000e, and the new host kicks a sender whose net tick differs from its own (S 0040e560) [known].
4. Whether any virtual call is made through the vftable pointer of a GUID received from the wire (a peer of a
   different build, or one that writes another value there, would crash the receiver). Seen so far [known]: the
   vftable S 007d42b4 has two slots, `Serialize` S 004085e0 (`+0`) and `Deserialize` S 00408530 (`+4`); neither
   has a direct caller, and every event and `PlayerInfo` serialiser writes and reads the 0x14 raw bytes instead of
   calling them (§3.2). `PlayerInfo`'s own first four bytes are not on the wire. Settled by a search for indirect
   calls on a `NetGUID` object (the copy and compare helpers of slots, events and the left-players list).
5. Meaning of the TinCat values set in `TinCatNetwork::StartUp` (value slots `+0x70` = 1, `+0x28` = 500, `+0x30`
   = 500; API slot `+0x30` = 500) and of the two calls in `CloseSession`. `tincat3.dll` read.
6. Answered (`docs/sim/lan-and-transport.md` §3.2, §3.3): the LAN discovery exchange (`BC_*`, `BCGameInfo`) is
   specified there; not reached in this build (roles 1 and 2 are never started, §3.3).
7. Whether the transient checksum-count mismatch around a leave is visible to the player. Observation in a
   running three-player match. Answered (§3.10): a clean leave of a non-host yields two 0x2002B commands on
   the host, one from the lockstep 0x3000b and one from the disconnect.
8. Answered (§6): a section line directly behind a UTF-8 byte order mark is not found by
   `GetPrivateProfileIntA`, so the install's first `[Basics] gamePort = 5478` is hidden and the effective
   `gamePort` is 5479 (second section or fallback) [live, 2026-10-14].

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 0040a530 | NComm_Manager::ctor | initial values, generates the local GUID |
| 0040a810 | NComm_Manager::ResetSession | reset of all session fields |
| 0040a9a0 | NComm_Manager::StartUpNetwork | role, transport creation, state 0 → 1 |
| 0040ad60 | NComm_Manager::ConnectAndJoin | connect, send 0x30001, state 1 → 2 |
| 0040b170 | NComm_Manager::BeginGameStarting | state 2 → 3 |
| 0040b270 | NComm_Manager::BeginGameRunning | state 3 → 4, tick state reset |
| 0040b410 | NComm_Manager::Shutdown | transport down, state → 0 |
| 00410f70 | NComm_Manager::Process_MainLoop | per-frame driver: transport, immediate queue, reconnect, ping |
| 0040e560 | NComm_Manager::HandleEvent | session event router (all 0x3000x) |
| 0040fd50 | NComm_Manager::DispatchEventLocal | HandleEvent, else game listener |
| 00408b60 | NComm_Manager::SendEvent | one event as message 1000 to host or one peer, or local |
| 0040fd80 | NComm_Manager::BroadcastEvent | one event as message 1000 to all, plus local |
| 00408b10 | NComm_Manager::QueueGameCommand | command into the outgoing package (or at once offline) |
| 004089c0 | NComm_Manager::SendEventUserChecksum | restart the outgoing package with 0x30009 |
| 004088b0 | NComm_Manager::CanAdvanceTick | lockstep gate |
| 00411990 | NComm_Manager::AdvanceNetTick | net tick boundary: execute, exchange, compare |
| 00410530 | NComm_Manager::ExecuteEventPackage | deserialise and dispatch a package |
| 0040e0d0 | NComm_Manager::AddClientGameEventsToServerGameEvents | host: message 1001 into the collected list |
| 004082a0 | NComm_Manager::AddReceivedHostTickPackage | message 1002 into the to-execute list |
| 004082c0 | NComm_Manager::AppendReceivedImmediateEvents | message 1000 into the immediate queue |
| 004090e0 | NComm_Manager::BroadcastGameInfo | host: 0x30003 / 0x3000f |
| 0040fe50 | NComm_Manager::BroadcastStartLoading | host: 0x30012 |
| 0040ff90 | NComm_Manager::BroadcastStartGame | host: 0x30005 |
| 0040bb60 | NComm_Manager::AssignSlotToJoiningUser | slot choice for a joiner |
| 0040b5a0 | NComm_Manager::RefreshSlots | host: initialise / clear slots against maxPlayers |
| 0040b470 | NComm_Manager::KickPlayer | host: 0x30010 or transport kick |
| 00409240 | NComm_SendEventUserLeave | 0x3000a and the leave timeout |
| 00410720 | NComm_Manager::HandlePlayerLeft | bookkeeping for a player who left |
| 00409750 | NComm_Manager::RemovePlayerById | host: slot to "left" or open, rebroadcast |
| 00408f60 | NComm_Manager::BeginReconnect | reconnect state 1 (become host) |
| 0040a110 | NComm_Manager::Reconnector_RestartAsClient | reconnect state 1 with a host address |
| 004093a0 | NComm_Manager::ReconnectAndRejoin | rejoin a new host, send 0x3000e |
| 0040b700 | NComm_Manager::Reconnector_RestartAsServer_DoAction | become the new host |
| 004109b0 | NComm_Manager::Reconnector_DropRemotePlayers | rejoin failed: drop the others |
| 00408860 | NComm_Manager::IsGameHanging | stall test for UI and command queue |
| 0040d260 | NComm_Manager::GetHangReason | stall text |
| 00413ae0 / 00413e00 | NComm::EventGameInformation::Serialize / ctor_Deserialize | session description wire format |
| 00415060 / 00415130 | NComm::PlayerInfo::Serialize / Deserialize | slot wire format |
| 00414290 | NComm::EventGameInformation::AssignGameData | copy of the session data |
| 00414720 | NComm::EventGameInformation::UpdateSettingsCrc | settings CRC |
| 00413930 | NComm::EventGameInformation::AssignRandomPlayerIndicesAndTeams | random index / team at StartLoading |
| 00409950 / 00420230 | NComm::EventUserInformation::Serialize / ctor_Deserialize | join request wire format |
| 00420540 | NComm_Event_CreateFromStream | event factory by class tag |
| 004201f0 | NComm_Event_WriteToStream | class tag + serialisation |
| 00421bd0 | NComm_InitEventTypeNameMap | id → name table of all GE_ / NE_ ids |
| 00412b40 | ai::ncomm::TickPackage::WriteHeader | package header |
| 00412e80 | ai::ncomm::TickPackage::AppendEvents | merge of a block into a package |
| 00412a10 | ai::ncomm::TickPackageList::FindOrCreate | package by tick |
| 00412ae0 | ai::ncomm::TickPackageList::AddReceived | received package into a list |
| 0041e610 | NComm::TinCatNetwork::StartUp | TinCat init as host or client, reconnector, file transfer |
| 00419e10 | NComm::TinCatNetwork::Process | per-frame transport work |
| 0041a1b0 | NComm::TinCatNetwork::ConnectToServer | client connect |
| 0041d720 | NComm::TinCatNetwork::cb_Received_Data | dispatch of message types 1000..1003 |
| 0041db50 / 0041dbb0 / 0041dc30 | TinCatNetwork send to host / to all / to one | transport vtable `+0x18` / `+0x1c` / `+0x20` |
| 0041d4c0 | NComm::TinCatNetwork::UIS_Remove | user removed → HandlePlayerLeft |
| 0041bb20 / 0041bcc0 / 0041b990 | cb_ConnectionLost / cb_ConnectionClosed / cb_LoggedOut | connection events |
| 004259b0 / 00425aa0 | NComm::TinCatReconnector::cb_BecameServer / cb_ReconnectTo | host migration decisions from TinCat |
| 0040a390 / 0041ede0 | NComm_NetworkConfig_InitDefaults / LoadFromIni | `network.ini` |
| 00428110 | ai::net::S2TftpManager::OnReceive | file transfer entry (message 1003) |
| 00427140 | ai::net::S2TftpManager::RequestFile | start or queue a download |
| 00782a50 | nGame::System::BeginGameRunningForward | game listener start slot |
| 005eed00 | nMenu::Game::OnEnter | state 3, sinks, GameLoaded |
| 006009b0 | nMenu::Requester::Update | quit: leave event and wait |
| 00457a00 | LobbyMenu::SetupGameDialog::Update | room: StartLoading trigger |
