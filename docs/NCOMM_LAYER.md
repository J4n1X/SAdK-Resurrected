# NComm network layer — `NComm::Manager` + transports + events

Status: **static RE on `sadk_noav.exe`** (base 0x400000) via the Ghidra MCP, 2026-06-17. RTTI intact
(namespace `NComm`, `.?AV…@NComm@@`). All renames/structs/enums applied + saved in the Ghidra project.
`[PROVEN static]` unless marked `[inferred]`. This is the **match transport** — the host's match never
starts because its NComm never leaves `EManagerState_Connected(2)`; see `MATCH_START_STATIC_RECONCILIATION.md`.

NComm is the engine's network abstraction (`Manager.cpp`). A process-global **`NComm::Manager`** singleton
(`NComm_GetManager@0x408290` → `DAT_00885754`) owns one polymorphic **transport** (`INetworkHandler`),
and the game talks to peers by sending **`Event`** objects.

## `NComm::Manager` — the transport state machine [PROVEN static]

Struct **`NComm_Manager`** (973 B modelled; key fields only, gaps undefined):
`+0x1c eManagerState` (`EManagerState`), `+0x20 cShutdownFlag`, `+0x34/0x38 nMaxPlayers`,
`+0xdc` the 6-entry **player-slot table** (room model; `NComm_GetSlotDataPtr(mgr+0xdc, i)`),
`+0x32c` local player name, `+0x340 pNetwork` (`NComm_INetworkHandler*`), `+0x3c8 nMode`,
`+0x3cc fStartLoading`.

**`EManagerState` (mgr+0x1c):** `None=0` → `NetworkStarted=1` → `Connected=2`.

| Method | Addr | Effect |
|---|---|---|
| `NComm_Manager_GetState` | `0x408430` | returns `mgr+0x1c` |
| `NComm_Manager_GetMode` | `0x4890b0` | returns `mgr+0x3c8` |
| `NComm_Manager_StartUpNetwork(mode)` | `0x40a9a0` | asserts state==None; builds transport by mode (table below); state→1 |
| `NComm_Manager_ConnectAndJoin` | `0x40ad60` | asserts state==1; sends **`NE_UserInformation(0x30001)`** w/ BuildVersion+Checksum; state→2; host modes → `BroadcastGameInfo` |
| `NComm_Manager_Shutdown(keep)` | `0x40b410` | `pNetwork->ShutDown()` + `pNetwork->dtor`; state→0 |
| `NComm_Manager_SendEvent` | `0x408b60` | self→local dispatch; else transport `Broadcast`/`SendTo` |
| `NComm_Manager_DispatchEventLocal` | `0x40fd50` | loopback dispatch |
| `NComm_SendPlayerReadyEvent` | `0x408d80` | `Event1Integer(NE_PlayerReady 0x30011)`; requires state==2 |
| `Manager_HandleNCommEvent` | `0x40e560` | inbound event router (per-frame) |

**Transport-by-mode table** (`StartUpNetwork`): mode 0 → `DummyNetwork` (loopback, single-player);
1 → `TinCatNetwork`(client); 2 → `TinCatNetwork`(host); 3 → `TinCatNetwork`(client/joiner);
4 → `TinCatNetwork`(host/match-host). Modes 1-4 set max-players 4; mode 0 sets 1.

## Transport: `INetworkHandler` + `TinCatNetwork` + `DummyNetwork` [PROVEN static]

`INetworkHandler` is the abstract transport interface — **never instantiated** (no own vftable);
realized by `TinCatNetwork` (real, object 0xEC, vftable `0x7d58f4`) and `DummyNetwork` (loopback,
vftable `0x7d5a6c`). Struct **`NComm_INetworkHandler_vftable`** (44 slots) models the interface:

`Destructor, StartUp(isHost,flag), ShutDown, Process, ConnectToServer, Disconnect, Broadcast,
SendToHost, SendTo, SendToAllExcept, CloseSession, KickPlayer, GetLocalNetId, GetUserCount, IsHost,
IsConnected, GetBroadcastNetId, …, SetUserData, GetUserName, GetUserGUID, GetUserLevel, RemoveUser,
BC_Start/Update/Stop/GetGameInfo (LAN "S2TNG_BC" discovery), StartReconnector, GetNetworkName,
LoadNetworkConfig (network.ini), ProcessReceive`. (Full slot→addr table in `RENAME_LIST.md`.)

- **`TinCatNetwork`** logs in on TinCat type **`0x27d9`**; magic net-ids: `0xEFFFFFCC`=broadcast,
  `0xEFFFFFDD`=host, `0xEFFFFFEE`=none/invalid. It has a **second vftable** at `this+0x04`,
  `NComm::ITinCatCallback` (`0x7d58ac`, 16 slots): `cb_Received_Data@0x41d720` is the inbound
  dispatcher (type `0x27d9`, subtypes 1000/0x3e9/0x3ea/0x3eb), plus `cb_LoggedIn/LoggedOut/
  ConnectionLost/Ping_Received` and the LAN-broadcast server-list callbacks.
- **`DummyNetwork`** is mostly compiler-folded no-op stubs (loopback); real methods: `StartUp`,
  `SendStub`, `GetNetId`, `GetNetworkName`("unknown"), `GetUserGUID`(zero).
- **`TinCatReconnector`** (`0x7d5290`): host-migration ("Reconnecting to…").

## Events: the game-protocol payloads [PROVEN static]

Events derive from `EventBase` (`NComm_Event` struct: `+0 vftable`, `+4 nTypeId` (`NE_EventType`),
`+8 nSourceNetId`, `+0xc nPlayerId`; sizeof 0x10). **Two id layers** (key finding):

1. **Outer wire tag** = `GetClassSignature` (vftable[5], a fixed per-class constant). The factory
   **`NComm_Event_CreateFromStream@0x420540`** switches on this tag to pick the deserializer.
2. **Inner `NE_*` opcode** = `Event+4` (`NComm_Event_GetType@0x4901e0`) — the semantic message id,
   set by the *sender*, carried in the body. Enum **`NE_EventType`**: `NE_UserInformation 0x30001`,
   `PlayerInformation 0x30002`, `GameInformation 0x30003`, `GameLoaded 0x30004`, `StartGame 0x30005`,
   `UserChecksum 0x30009`, `UserLeave 0x3000a`, `UserReJoinGame 0x3000e`, `PlayerReady 0x30011`,
   `StartLoading 0x30012`.

### Class → wire-signature → ctor (deserializer) — the factory's switch table
| Class | wire tag | ctor | NE_id (if fixed) |
|---|---|---|---|
| EventBase | `0x00000101` | `0x413a60` | — |
| Event1Integer | `0x11111010` | `0x41f680` | 0x30011 ready / 0x30004 loaded |
| Event2Integer | `0x11110202` | `0x41f6f0` | — |
| Event3Integer | `0x11113030` | `0x41f7d0` | — |
| Event4Integer | `0x11110440` | `0x41f8c0` | — |
| EventInt64 | `0x22220101` | `0x41f9d0` | — |
| EventInt64_1Integer | `0x22222020` | `0x41faa0` | — |
| EventInt64_2Integer | `0x22220303` | `0x41fb80` | — |
| EventInt64_3Integer | `0x22224040` | `0x41fc70` | — |
| EventData | `0x33331010` | `0x41fd80` | — |
| EventText | `0x44440101` | `0x420340` | — |
| EventUserLeave | `0x55550404` | `0x4200e0` | 0x3000a |
| EventPlayerInformation | `0x55550606` | `0x41ff10` | 0x30002 |
| EventSaveGame | `0x55550808` | `0x420440` | — |
| EventUserInformation | `0x55551010` | `0x420230` | **0x30001** |
| EventUserReJoinGame | `0x55550202` | `0x41ffc0` | 0x3000e |
| EventKickUser | `0x55553030` | `0x4203c0` | — |
| EventUserChecksum | `0x55555050` | `0x420050` | 0x30009 |
| EventUserLeft | `0x55557070` | `0x420160` | — |
| EventGameInformation | `0x66660101` | `0x413e00` | **0x30003** |

Serialization primitives: `NComm_MemoryStream_{Write,Read,WriteString}` (`0x4122f0/0x412360/0x4123a0`),
`NComm_EventBase_Serialize@0x4085a0` (writes type/netID/playerID header), `NComm_MD5Digest_*`,
`NComm_NetGUID_*`, `NComm_PlayerInfo_*`.

## Types created (Ghidra)
- enums: `EManagerState`, `NE_EventType`.
- structs: `NComm_Manager`, `NComm_INetworkHandler` + `NComm_INetworkHandler_vftable` (44 slots),
  `NComm_Event`. (`NComm_Manager.pNetwork` typed → `NComm_INetworkHandler*`.)

## Follow-ups
- The class-signature wire tags are documented above; not made into a Ghidra enum (large hex constants;
  add later if useful).
- `set_function_this_type` pass for the NComm classes (deferred — duplicate-GhidraClass trap).
- Model the 6-entry player-slot table at `Manager+0xdc` (the room slot/tribe/team/colour model) — needs
  the per-slot struct mapped; it ties directly to `SetupGameDialog`'s 6 Player{Type,Tribe,Team,HQ,Color}
  slot widgets.
