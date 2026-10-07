# SAdK network message catalog

This catalog lists every network message the SAdK client (`SADK.exe` + `tincat3.dll`) speaks with
the lobby side: the lobby, UC/chat, village, referee and ranking connections, plus the NComm
peer-to-peer events that drive the pre-game room. It is built from three sources: the binary
(`S` = sadk_noav.exe, base 0x400000; `T` = tincat3.dll, base 0x10000000; addresses are cited as
`S 00xxxxxx` / `T 10xxxxxx`), the schema in `sadk_lobby/data/msgdefs.ini`, and the working stub in
`sadk_lobby/`. Each message has three layers: the **contract** (what the bytes are), the **required
server behaviour** (what the client needs from the server to make progress), and the **open
decisions** (server-side choices the client does not dictate, with the range it accepts and a
suggested default). Confidence tags: **[known]** = read in code with no ambiguity, or proven live;
**[inferred]** = follows from code that was read but not fully traced; **[guess]** = no direct
evidence; **[PROVEN]** = the working stub demonstrates it against the real client (binary address +
live evidence); **[TODO]** marks a point that is still open. Open decisions carry a family prefix
(`L` login, `H` hosting, `V` village, `T` tincat3) and are collected in [Server decisions](#server-decisions).

## Wire encoding

### Connections

| Connection | Address the client dials | TinCat module(s) | Receive handler | Login completes on | Carries |
|---|---|---|---|---|---|
| Lobby | `LobbySettings.ini` host; the stub listens on 7070 | 0x26B6 | `HandlerLobby::HandleMessage` T 10023cc0, created by `ConnectionManagerINet::LoginUser` T 10030f00 (also RegisterUser T 10030e90 / LoginSupport / LoginServer) | **207 SessionKey** (state 7 -> 8) [known] [PROVEN] | login, account, characters, server list, hosting, every tincat3 manager |
| UC / chat | ip:port of `192 UsercommServerData`; the stub returns 7071 | 0x26B6 (token login, 17, 259) and 0x0062 (CellManager chat cells) | `HandlerUserComm::HandleMessage` T 10027080 (`ConnectionManagerINet` ctor T 10030d50, connType 1); CellManager `Received_Data` T 1000ef30 | **153 AddResult** on the 213 ticket [known] [PROVEN] | chat, channel join/leave, cyclic admin messages, broker |
| Village (world) | ip:port of `222 ConnectionData` for the village server id (T 10023cc0 fills host/port; `ConnectionReal::Connect` T 100309d0 dials only from them). The stub serves `config.WORLD_PORT` = 5477 | 0x26B6 | `HandlerGS::HandleMessage` T 10023460 (`AddConnectionByServerId` T 100196b0 / `ByAddress` T 10019750); 73/74 -> `VillageServerConnection::HandleMessage` S 00470a90 | 153 AddResult on the 213/224 ticket [known] [PROVEN] | LobbyMessages 1000+ inside 73/74 |
| Referee | ip:port of `222` for the referee server id | 0x26B6 | `HandlerGS` T 10023460; 74 -> `RefereeServerConnection::OnReceive` S 0047b090 | 153 AddResult [PROVEN] | referee LobbyMessages (category 3) inside 74 |
| Ranking ("stat-surf") | ip/port of the `170` that answers a `189` with type 4 / subtype 5 (T 10021520 -> `ConnectRankingServer` T 10029a20) | 0x26B6 | `HandlerStatSurf` T 100268e0 | 153 AddResult [inferred] | 252-257; no SADK caller opens it [inferred] |
| NComm P2P | host ip/port from the game's `170` descriptor (`GameServerInfo::JoinGame` S 0048d030) | 0x27d9, msgType 1000 | `NComm_Manager::HandleEvent` S 0040e560 | — | pre-game room and match events; never reaches the lobby server |

The client runs one of three receive machines per lobby-side connection. Each treats Result(42) and
AddResult(153) differently, which is why the connection decides how a login completes. [known]

### TinCat frame

Every lobby-side connection is a TCP stream of frames: a 28-byte header plus a payload.

| Offset | Field | Type | Notes |
|---|---|---|---|
| 0x00 | magic | u32 LE | 0xDABAFBEF [known] |
| 0x04 | from | u32 LE | sender id; the stub uses its server id [known] |
| 0x08 | to | u32 LE | receiver id (the connection id assigned at handshake) [known] |
| 0x0C | type | u32 LE | kernel frame type, table below [known] |
| 0x10 | unk1 | u32 LE | preserved on relay by KRNL_RouteCustomData T 10005140 [inferred]; the stub sends 0 |
| 0x14 | payload size | u32 LE | used unbounded as a malloc size by the reader T 10032670 [known] |
| 0x18 | CRC32 | u32 LE | over the payload only; reflected poly 0xEDB88320, **init 0, no final xor** (not zlib); CRC32_Compute T 100342a0 [known] |

Reader behaviour (T 10032670, NETDRV_ReaderThreadProc T 10001fc0) [known]:
- Bad CRC: reader status 8, "unknown error, STOP!", and the connection is torn down.
- Bad magic: logged as a foreign packet and not consumed; the stream desyncs.
- Unknown kernel type: dropped silently.

Kernel frame types (NETKRNL, board #318) [known]:

| Type | Name | Direction / use |
|---|---|---|
| 1 | TIMESYNC | no client handler, logged only |
| 2 | CUSTOMDATA | every NETMSG rides this (stub `MSG_APPLICATION`) |
| 3 | LOGMEON | C->S handshake, payload 0x34 bytes: {u32 0xDABAFBEF, u32 id 0xEFFFFFEE, name[32], password[8], u32 flags} |
| 4 | LOGMEOFF | C->S logoff |
| 5 | LOGONACCEPTED | S->C handshake reply; the client reads only payload+4 id, +8 name[32], +0x28 password[8] (handler T 10004d90); the real server answered password "-" (KRNL_LogClientOn T 10005a60) |
| 6 | LOGOFFACCEPTED | S->C |
| 0xB | STAYINGALIVE | keepalive, 2 uninitialised bytes; handler T 100041b0 needs no reply (stub `MSG_PING` = this type) |
| 0xC | FILE | not used on the lobby path |
| 0xE | GROUPDATA | Received_GroupData is a state-check stub; group data never reaches the application |

**Required server behaviour.** Answer LOGMEON (3) with LOGONACCEPTED (5) carrying the connection id
in payload+4 and password "-" [PROVEN] (`tincat.build_handshake_payload`, every live session). No
reply to STAYINGALIVE is needed [PROVEN] (the stub ignores it and sessions stay up). Never send a
frame with a wrong CRC: the client disconnects. [known]

**Open decisions.**
- **T1** `from` / `unk1` values on S->C frames: the client does not check them on CUSTOMDATA
  delivery [inferred]. Default: the server id constant, unk1 = 0 (what the stub sends).
- **T2** Connection id in LOGONACCEPTED: any u32 [inferred]. Default: a per-socket counter starting
  at 1.

### Module payload (CUSTOMDATA)

| Offset | Type | Meaning |
|---|---|---|
| 0 | u16 LE | TinCat module id: **0x26B6** = CommLayer / NETMSG layer (lobby, UC NETMSG traffic, village, referee, ranking); **0x0062** = CellManager (chat cells, UC connection only) [known] [PROVEN] |
| 2 | u16 LE | msgType. NETMSG layer: the NETMSG id. CellManager: always 0 [known] |
| 4 | ... | property-bag body, fields in template order |

`TinCat_BuildModulePayload` T 10006a80 writes {moduleId, msgType}; the bag follows, and its first
property is `type` UNSHORT, equal to the NETMSG id (`cPropertyFactory::CreatePropertySet`
T 10013830). The stub's `<HHH` (magic, type, type) produces the same bytes. [known] [PROVEN]

- **0x0062 is a module id, not a payload magic.** CellManager frames (T 1000cde0 / T 1000ef30) carry
  msgType 0, and the first bag field `id` (u16) selects one of the templates 0..11 registered by
  `CellManager::Init` T 1000cde0. [known]
- `CommLayerTinCat::OnReceivedData` T 10018e30 drops every CUSTOMDATA frame whose moduleId is not
  the CommLayer id, without a log. [inferred]
- Inbound module-0x62 frames are dropped while the TinCat link is not fully connected
  (stateFlags != 0xf). Frames whose msgType has no registered extension are dropped silently
  (T 1000aa80, board #818). [known]
- The TinCat application ping is a different module (99, msgType 0x5A89, 12-byte payload
  {u16 0x5A89, u16 phase, u32 peerId, u32 tick}). The client echoes phase 0 itself
  (Received_Ping T 10009070); the server need not send it. [known, board #279]

### Property-bag body (msgdefs field types)

The body is the msgdefs template for the type, field by field in **msgdefs key order**, with no
names and no padding (PropertyDataConverter SerializeProperty T 100112b0 / DeserializeProperty
T 100110e0, widths from Property::GetMaxLength T 10011490). [known] [PROVEN]

| msgdefs type | Wire form | Evidence |
|---|---|---|
| UNBYTE / SIBYTE | 1 byte | T 10011490 [known] |
| LBOOL | **1 byte** (stored as v != 0) | GetMaxLength returns 1 for type 14; SetLBOOL T 10013100 stores one byte [known] |
| UNSHORT / SISHORT | 2 bytes LE | T 10011490 [known] |
| UNLONG / SILONG | 4 bytes LE | T 10011490 [known] |
| 64-bit / double | 8 bytes LE | T 10011490 [known] |
| STRING N | u32 LE length **including the NUL**, then the bytes. The receiver forces the last byte to NUL and clamps the value to N | T 100112b0 / T 100110e0 [known]; NUL convention [PROVEN] (`tests/test_codec_golden.py`, live 170) |
| MEMBLOCK 0 | u32 LE length, then the bytes | T 100112b0 [known] |

Rules [known]:
- A STRING/MEMBLOCK length of 0 leaves the receiver's template value untouched. `None` (length 0)
  and `""` (length 1, a single NUL) are therefore different on the wire. [PROVEN]
- Trailing bytes after the last template field are ignored. A body shorter than the template makes
  Deserialize fail and the message is dropped (board #262).
- The template comes from the client's own msgdefs.ini (LoadMsgDefs T 1001f6e0); duplicate keys and
  section merges follow IniFile_Load T 1000f630 (board #358/#364). A type with no template makes
  CreatePropertySet return NULL and the message is dropped.
- A sender that writes a field that is not in the template (for example `ticket_id` on 252/254/256)
  has no wire effect. [inferred]
- A reader that uses a narrower accessor than the template (for example `keypool` read with the byte
  accessor vtbl+0x5c) still consumes the template width; it only truncates the value.

### Tickets and request completion

Every request a CommLayer manager sends carries `ticket_id` = TicketTable::AllocTicketId T 1002a1c0,
stored with a **request type**: normally the NETMSG id, with a few client-local tags (0x108
AssignServer for referee/game/ranking, 0x109 AssignServer for the UC server, 0x10a/0x10b bulk
property gets, 0x10d RequestConnectionData from GameServerManager). TicketTable::GetRequestType
T 1002a240 returns 0x107 for an unknown ticket, and every switch ignores 0x107. [known]

HandlerLobby T 10023cc0 reads `ticket_id` first, maps it to the request type, then switches on the
message type [known]:
- Data rows (59, 60, 61, 62, 68, 69, 70, 75, 82, 83, 120, 122, 159, 160, 170, ...) are delivered
  only if the row's ticket maps to the matching request type. Otherwise they are parsed and
  dropped, and the ticket is not released.
- **Result(42)** completes the request by request type (jump index table T 10026680) and releases
  the ticket. Request types with no case (including 0x107) do nothing and keep the ticket. The full
  routing table is at [Result (42)](#0x02a-42-result--s-c).
- **AddResult(153)** completes only request types 0x54, 0x55, 0x56, 0x57, 0x96, 0xa8, 0xaf and
  0xb0 (table T 1002677c); any other type is ignored and the ticket kept.
- A ticket is consumed **once**: the first matching reply releases it (T 1002a320). [known]
- Unknown message types are logged as "Invalid message-type %u received from %u" and dropped.

CellManager requests (17, 259, cyclic admin, broker) use a separate ticket and context table
(T 1002a3a0..1002a4e0) that the NETMSG Result(42) switch on the UC handler never consults. [known]

Busy flags: almost every tincat3 manager request latches its own busy flag and returns 4 ("busy") on
the next call until the completing reply arrives. A missing or wrong-kind reply makes that operation
silently unusable for the rest of the session (board #345). The SADK action queues (PostOffice,
CharacterManager, Properties, ServerMessages) also keep **one request in flight**, so one stuck
request blocks every later request of that queue. [known]

Message cases per receive handler:

| Handler | Connection | Cases |
|---|---|---|
| HandlerLobby T 10023cc0 | lobby | everything in the login, hosting and tincat3 sections unless noted |
| HandlerGS T 10023460 | per-server-id (village, referee) | 42 (188/211 tickets), 73/74, 153 (213/224/84 tickets), 212; everything else dropped |
| HandlerUserComm T 10027080 | UC | 42, 73/74, 153, 212 |
| HandlerStatSurf T 100268e0 | ranking | 42, 73/74, 153, 212, 253, 255, 257 |
| CellManager relay -> ChatChannelManager::HandleCellMessage T 10017ba0 | UC (module 0x62) | 2, 3, 5, 6, 13, 35, 38, 42, 45, 47, 76 |

214 (0xD6) is outside the jump-table range of HandlerGS and HandlerUserComm (bound 0xAA after
subtracting 0x2a), so it is logged as 'Invalid message-type' and dropped. [known]

### AssignServer routing: the 4/4 versus 4/5 rule

`189 AssignServer` asks the lobby for a server by (server_type, server_subtype). The UC request
(type 2) has its own sender; the GameServerManager sender T 10021830 refuses types other than 3, 4
and 5. [known]

| Request | Sender | Ticket request type | Completed by |
|---|---|---|---|
| type 2 (UC) | `HandlerUserComm::RequestServerAssign` T 10027630 | 0x109 | `192 UsercommServerData` (dials on every 192) [PROVEN] |
| type 4 / subtype 4 (referee) | `ServerList::RequestRefereeServer` S 00468f60 | 0x108 | one `170 GameServerData` on that ticket [PROVEN] |
| type 4 / subtype 5 (ranking) | RankingManager slot 3 T 10029a00 | 0x108 | one `170` on that ticket [inferred] |

A `170` on a 0x108 ticket is handled by `OnGameServerAssigned` T 10021520, which routes it by the
descriptor's type and subtype [known]:
- **type 4 / subtype 5** is diverted to RankingManager `ConnectRankingServer` T 10029a20. The game is
  never told, so LobbyManager+0x580 never latches. [PROVEN] (silent failure, engagement record
  2026-07-27)
- **Any other pair** reaches `ServerList::GameServerAssigned` S 00469ad0, which calls the pending
  callback with `server_id` -> LM+0x580. [PROVEN] (4/4)

The referee reply must therefore be type 4 / subtype 4. A successful assign arms a 60000 ms retry
timer (S 004625d0), so one 189 every 60 s for the rest of the session is the sign that the latch
worked. [PROVEN] Only `server_id` is used from this descriptor; the referee address comes from
221/222. [PROVEN]

### LobbyMessage bodies (village and referee)

Village and referee messages are **LobbyMessages** carried inside a NETMSG envelope:
`SendGameData(74)` {msg_type u32 LE, data MEMBLOCK} in both directions, or
`SendGameDataBundle(73)` server -> client. msgdefs defines only the envelopes; the bodies come from
the binary. [known] `data` holds the field bitstream **only**; the type word must not be repeated
inside it. [PROVEN]

**Type word** (`msg_type`, `InitFromWire` S 0048fa50) [known]:

| Bits | Meaning |
|---|---|
| 15 | names mode. When set, `FinishRead` S 0048f530 consumes one trailing 32-bit word per message; field names never travel on the wire |
| 12-14 | category: referee 3 (LoginSuccess = 0x3DCA) [PROVEN]; village messages from the client 2 (`0x2000\|id`); minigame actions 5 (`0x5000\|id`) |
| 0-11 | message id |

`VillageServerConnection::HandleMessage` S 00470a90 ignores the category (the stub sends category 0
and the client accepts it [PROVEN]). `RefereeServerConnection::OnReceive` S 0047b090 dispatches on
`typeWord & 0xFFF`. Both drop unknown ids silently and keep the connection up. [known]

**Field bitstream.** No field names and no tags; fields are written in a fixed order. [known]

| Item | Rule | Evidence |
|---|---|---|
| bit order | **MSB-first** bit stream; no alignment between fields; the final byte is zero-padded | S 0048ef70 WriteBits, S 0048f4c0 [known] |
| integers | n bits, MSB first (reader vtbl 007db594: +0x08 byte, +0x10 short, +0x18 int, +0x20 int64). A 32-bit value is big-endian **only when it starts on a byte boundary** | S 0048ef70 / S 0048f0d0 [known]; [PROVEN] for 32-bit (1000, 1006, 0xDCA) |
| bool | **1 bit** (vtbl+0x28) | S 0048f3c0 [known] |
| string | **u8 byte length**, then the bytes; no u32 length and no NUL. vtbl+0x30 converts UTF-8 -> ANSI on read (S 004900a0 -> S 00487620); vtbl+0x34 keeps raw bytes | S 0048fe20 / S 004900a0 [known]; UTF-8 [PROVEN 2026-08-02, "Händler" label] |
| raw buffer | the bytes only, no length | S 0048f440 [known] |
| packed uint | 1 presence bit; 0 = value 0; 1 = u3 (nibbles - 1), then nibbles x 4 value bits | read S 0048fcb0, write S 0048fb90 [known] |
| int64 | the reader S 0048f050 aliases the two 32-bit halves; the high dword on the wire must be 0 | [known] (static) |
| raw-32 | reader vtbl+0x40 (S 0048ff50) reads 32 bits, then byte-reverses them: a little-endian value inside the big-endian stream. Used only by `SellMod` in 0xE11 | [known] |

Consequence: in `RegisterGame 0xDB6`, every field after the 1-bit RankedGame is one bit off byte
alignment, so it must be read with a bit reader (S 00479840). [known]

The property-bag rules (little-endian, u32 lengths) apply to the 73/74 envelope, not to the
LobbyMessage body inside it.

### NComm P2P events

Pre-game room and match events go host to peers over the peers' own TinCat session, module 0x27d9,
msgType 1000. They are not lobby traffic and the stub does not carry them. Each body is a raw
little-endian memory dump: `u32 classSig | u32 typeId | u32 srcNetId | i32 playerIndex | body`.
Strings are a u16 length + bytes with no NUL. A NetGUID is 20 raw bytes, including the in-memory
4-byte vptr. [known] (S 00408b60, board #539/#564)

## Index

Status of each message in the stub:
- **implemented**: the stub sends or answers it as the client needs.
- **differs**: the stub handles it, but not the way the client needs (see [Where the stub differs from the client](#where-the-stub-differs-from-the-client)).
- **missing**: the client sends or consumes it in normal play, and the stub does not answer or send it.
- **optional**: the client handles it, but nothing requires it under the suggested defaults; the stub does not send it.
- **unused**: the SAdK client neither sends it in normal play nor acts on it (no builder, no receive case, or no SADK caller identified).
- **p2p**: peer-to-peer NComm event; never reaches the lobby server.
- **open**: in msgdefs and referenced by tincat3, but not catalogued here; client use is [TODO].

Direction "—" means the message is not on the SAdK wire. "server-id" = the village, referee and ranking
connections. "UC (cell)" = a NETMSG embedded in a CellManager template on the UC connection.
Ids 204, 209, 216-222 appear twice: once as lobby NETMSG ids and once as village LobbyMessage ids
(different connections, different encodings).

| Id hex | Dec | Name | Dir | Connection | Section | Status |
|---|---|---|---|---|---|---|
| 0x02A | 42 | Result | S->C | all | [tincat3](#0x02a-42-result--s-c), [login](#0x02a-42-result--s-c-login-role) | implemented |
| 0x099 | 153 | AddResult | S->C | all | [tincat3](#0x099-153-addresult--s-c), [login](#0x099-153-addresult--s-c-token-completion) | implemented |
| 0x001 | 1 | Simple | — | lobby | [tincat3](#0x001-1-simple--not-handled) | unused |
| 0x0BC | 188 | CheckVersion | C->S | all | [login](#0x0bc-188-checkversion--c-s), [login](#188--42-on-the-uc-connection) | implemented |
| 0x0C9 | 201 | StartAuthenticateSession | C->S | lobby | [login](#0x0c9-201-startauthenticatesession--c-s) | implemented |
| 0x0CA | 202 | AckAuthenticateSession | S->C | lobby | [login](#0x0ca-202-ackauthenticatesession--s-c) | implemented |
| 0x0CB | 203 | SelfRegistration | C->S | lobby | [login](#0x0cb-203-selfregistration--c-s) | implemented |
| 0x0CC | 204 | AuthenticateUser | C->S | lobby | [login](#0x0cc-204-authenticateuser--c-s) | implemented |
| 0x0CD | 205 | AuthenticateSupport | C->S | lobby | [login](#0x0cd-205-authenticatesupport--c-s) | unused |
| 0x0CE | 206 | AuthenticateServer | C->S | lobby | [login](#0x0ce-206-authenticateserver--c-s) | unused |
| 0x0CF | 207 | SessionKey | S->C | lobby | [login](#0x0cf-207-sessionkey--s-c) | implemented |
| 0x004 | 4 | RequestLogin | — | lobby | [login](#0x004-4-requestlogin--c-s-not-sent) | unused |
| 0x047 | 71 | RequestCreateAccount | — | lobby | [login](#0x047-71-requestcreateaccount--c-s-not-sent) | unused |
| 0x0A1 | 161 | PropertyGet | C->S | lobby | [login](#0x0a1-161-propertyget--c-s-login-time-version-gate), [tincat3](#0x0a1-161-propertyget--c-s) | implemented |
| 0x0A2 | 162 | PropertyData | S->C | lobby | [login](#0x0a2-162-propertydata--s-c-version-gate-reply), [tincat3](#0x0a2-162-propertydata--s-c) | implemented |
| 0x0A3 | 163 | PropertySetAbsolute | C->S | lobby | [tincat3](#0x0a3-163-propertysetabsolute--0x0a4-164-propertysetrelative--c-s) | unused |
| 0x0A4 | 164 | PropertySetRelative | C->S | lobby | [tincat3](#0x0a3-163-propertysetabsolute--0x0a4-164-propertysetrelative--c-s) | unused |
| 0x069 | 105 | RequestMOTD | C->S | lobby | [login](#0x069-105-requestmotd--c-s), [tincat3](#0x069-105-requestmotd--c-s-1) | implemented |
| 0x06A | 106 | MOTD | S->C | lobby | [login](#0x06a-106-motd--s-c), [tincat3](#0x06a-106-motd--s-c-1) | implemented |
| 0x0B3 | 179 | ChangeMOTD | C->S | lobby | [tincat3](#0x0b3-179-changemotd--c-s) | unused |
| 0x09E | 158 | RequestUserKeyList | C->S | lobby | [login](#0x09e-158-requestuserkeylist--c-s), [tincat3](#0x09e-158-requestuserkeylist--c-s--0x09f-159-userkeyconn--s-c) | implemented |
| 0x09F | 159 | UserKeyConn | S->C | lobby | [login](#0x09f-159-userkeyconn--s-c), [tincat3](#0x09e-158-requestuserkeylist--c-s--0x09f-159-userkeyconn--s-c) | implemented |
| 0x077 | 119 | RequestSingleCdKey | C->S | lobby | [login](#0x077-119-requestsinglecdkey--c-s), [tincat3](#cd-keys) | unused |
| 0x078 | 120 | CdKeyData | S->C | lobby | [login](#0x078-120-cdkeydata--s-c), [tincat3](#cd-keys) | unused |
| 0x0BD | 189 | AssignServer | C->S | lobby | [login](#0x0bd-189-assignserver-server_type-2--c-s-uc-server-request), [hosting](#0x0bd-189-assignserver--c-s-referee-request), [wire](#assignserver-routing-the-44-versus-45-rule) | implemented |
| 0x0C0 | 192 | UsercommServerData | S->C | lobby | [login](#0x0c0-192-usercommserverdata--s-c) | implemented |
| 0x0D6 | 214 | ValidateToken | — | UC, server-id | [login](#0x0d6-214-validatetoken--s-c-not-consumed) | unused |
| 0x0D3 | 211 | StartValidateTokenSession | C->S | UC, server-id | [login](#0x0d3-211-startvalidatetokensession--c-s) | implemented |
| 0x0D4 | 212 | AckValidateTokenSession | S->C | UC, server-id | [login](#0x0d4-212-ackvalidatetokensession--s-c) | implemented |
| 0x0D5 | 213 | SendToken | C->S | UC, server-id | [login](#0x0d5-213-sendtoken--c-s) | implemented |
| 0x0E0 | 224 | TANLogin | C->S | server-id | [login](#0x0e0-224-tanlogin--c-s-server-id-connections-only) | missing |
| 0x011 | 17 | RequestJoinChannel | C->S | UC | [login](#0x011-17-requestjoinchannel--c-s-netmsg-layer-on-uc) | implemented |
| 0x103 | 259 | RequestLeaveChannel | C->S | UC | [login](#0x103-259-requestleavechannel--c-s-netmsg-layer-on-uc) | differs |
| 0x002 | 2 | ChatMessage | both | UC (cell) | [login](#0x002-2-chatmessage--c-s-relayed-s-c-inside-cellmanager) | implemented |
| 0x01E | 30 | WhisperChatMessage | C->S | UC (cell) | [login](#0x01e-30-whisperchatmessage--c-s-inside-cellmanager) | differs |
| 0x003 | 3 | PrivateChatMessage | S->C | UC (cell) | [login](#0x003-3-privatechatmessage--s-c-inside-cellmanager) | missing |
| 0x005 | 5 | UserJoinedChannel | S->C | UC (cell) | [login](#0x005-5-userjoinedchannel--s-c-inside-cellmanager) | implemented |
| 0x006 | 6 | UserLeftChannel | S->C | UC (cell) | [login](#0x006-6-userleftchannel--s-c-inside-cellmanager) | implemented |
| 0x04C | 76 | BeenKicked | S->C | UC (cell) | [login](#0x04c-76-beenkicked--s-c-inside-cellmanager) | optional |
| 0x06B | 107 | RegObserverGlobalChat | — | lobby | [login](#0x06b-107-regobserverglobalchat--c-s-not-sent) | unused |
| 0x06C | 108 | DeregObserverGlobalChat | — | lobby | [login](#0x06c-108-deregobserverglobalchat--c-s-not-sent) | unused |
| 0x0A5 | 165 | Chat | — | lobby | [login](#0x0a5-165-chat--s-c-not-consumed) | unused |
| 0x0F0-0x0FB | 240-251 | UCRoute ... UCUserInfo | — | UC | [login](#0x0f0-0x0fb-240-251-ucroute--ucuserinfo--not-used) | unused |
| tpl 0 | — | CellManager ChannelInfo / PublishCell | S->C | UC (0x62) | [login](#cellmanager-template-0-channelinfo--publishcell--s-c) | implemented |
| tpl 2 | — | CellManager CellMessage | C->S | UC (0x62) | [login](#cellmanager-template-2-cellmessage--c-s) | implemented |
| tpl 3 | — | CellManager CellMessage relay | S->C | UC (0x62) | [login](#cellmanager-template-3-cellmessage-relay--s-c) | implemented |
| tpl 7 | — | CellManager requestCreateCell | C->S | UC (0x62) | [login](#cellmanager-template-7-requestcreatecell--c-s) | differs |
| tpl 9 / 10 | — | CellManager Joined / Left | S->C | UC (0x62) | [login](#cellmanager-templates-9--10-joined--left--s-c) | implemented |
| tpl 11 | — | CellManager StatusReply | both | UC (0x62) | [login](#cellmanager-template-11-statusreply--both) | differs |
| 0x007 | 7 | ChannelInfo (NETMSG) | — | UC | not catalogued | open |
| 0x010 | 16 | InviteToChannel | — | UC | not catalogued | open |
| 0x012 | 18 | RequestKickFromChannel | — | UC | not catalogued | open |
| 0x106 | 262 | GetChannelByName | — | UC | not catalogued | open |
| 0x0AB | 171 | RegObserverServerList | C->S | lobby | [hosting](#0x0ab-171-regobserverserverlist--c-s) | implemented |
| 0x0AC | 172 | DeregObserverServerList | C->S | lobby | [hosting](#0x0ac-172-deregobserverserverlist--c-s) | differs |
| 0x0A6 | 166 | RequestServers | — | lobby | [hosting](#0x0a6-166-requestservers--c-s-not-used-by-sadk) | unused |
| 0x0AA | 170 | GameServerData | S->C | lobby | [hosting](#0x0aa-170-gameserverdata--s-c) | differs |
| 0x0A8 | 168 | AddGameServer | C->S | lobby | [hosting](#0x0a8-168-addgameserver--c-s) | implemented |
| 0x0B1 | 177 | ChangeGameServer | C->S | lobby | [hosting](#0x0b1-177-changegameserver--c-s) | differs |
| 0x0A9 | 169 | RemoveServer | both | lobby | [hosting](#0x0a9-169-removeserver--c-s-and-s-c-push) | differs |
| 0x0DD | 221 | RequestConnectionData | C->S | lobby | [hosting](#0x0dd-221-requestconnectiondata--c-s) | implemented |
| 0x0DE | 222 | ConnectionData | S->C | lobby | [hosting](#0x0de-222-connectiondata--s-c) | implemented |
| 0x092 | 146 | EnterServer | — | lobby | not catalogued | open |
| 0x0BE | 190 | LeaveServer | — | lobby | not catalogued | open |
| 0x0DF | 223 | TANConnectionRequest | — | lobby | not catalogued | open |
| 0x30001 | 196609 | UserInformation | joiner->host | P2P | [hosting](#0x30001-196609-userinformation--joiner---host) | p2p |
| 0x30002 | 196610 | PlayerInformation | peer->host | P2P | [hosting](#0x30002-196610-playerinformation--peer---host) | p2p |
| 0x30003 | 196611 | GameInformation | host->peers | P2P | [hosting](#0x30003-196611-gameinformation--host---peers-forced-variant-0x3000f) | p2p |
| 0x3000F | 196623 | HostReconnectRestartAndSendGameInformation | host->peers | P2P | [hosting](#0x30003-196611-gameinformation--host---peers-forced-variant-0x3000f) | p2p |
| 0x30004 | 196612 | GameLoaded | peer | P2P | [hosting](#0x30005-196613-startgame--0x30004-196612-gameloaded) | p2p |
| 0x30005 | 196613 | StartGame | host->peers | P2P | [hosting](#0x30005-196613-startgame--0x30004-196612-gameloaded) | p2p |
| 0x30010 | 196624 | Kick | host->peer | P2P | [hosting](#0x30010-196624-kick) | p2p |
| 0x30011 | 196625 | PlayerReady | peer->all | P2P | [hosting](#0x30011-196625-playerready--peer---all) | p2p |
| 0x30012 | 196626 | StartLoading | host->peers | P2P | [hosting](#0x30012-196626-startloading--host---peers) | p2p |
| 0xDCA | 3530 | LoginSuccess | S->C | referee | [hosting](#0xdca-3530-loginsuccess--referee---c-push) | implemented |
| 0xDCB | 3531 | LoginFailed | S->C | referee | [hosting](#0xdcb-3531-loginfailed--referee---c) | optional |
| 0xDB6 | 3510 | RegisterGame | C->S | referee | [hosting](#0xdb6-3510-registergame--c---referee) | implemented |
| 0xDB7 | 3511 | RegisterGameAcknowledge | S->C | referee | [hosting](#0xdb7-3511-registergameacknowledge--referee---c) | implemented |
| 0xDB8 | 3512 | RegisterGameResult | S->C | referee | [hosting](#0xdb8-3512-registergameresult--referee---c) | implemented |
| 0xDC0 | 3520 | FinishGame | C->S | referee | [hosting](#0xdc0-3520-finishgame--c---referee) | missing |
| 0xDC1 | 3521 | FinishGameAcknowledge | S->C | referee | [hosting](#0xdc1-3521-finishgameacknowledge--referee---c) | missing |
| 0xDC2 | 3522 | FinishGameResult | S->C | referee | [hosting](#0xdc2-3522-finishgameresult--referee---c) | missing |
| 0xDD4 | 3540 | GiveUpGame | C->S | referee | [hosting](#0xdd4-3540-giveupgame--c---referee) | missing |
| 0xDD5 | 3541 | GiveUpGameAcknowledge | S->C | referee | [hosting](#0xdd5-3541-giveupgameacknowledge--referee---c) | missing |
| 0xDAC | 3500 | ClaimChest | C->S | referee | [hosting](#0xdac-3500-claimchest--c---referee) | missing |
| 0xDAD | 3501 | ClaimChestAcknowledge | S->C | referee | [hosting](#0xdad-3501-claimchestacknowledge--referee---c) | missing |
| 0xDAE | 3502 | ClaimChestResult | S->C | referee | [hosting](#0xdae-3502-claimchestresult--referee---c) | missing |
| 0x04A | 74 | SendGameData | both | village, referee | [village](#0x04a-74-sendgamedata--both) | implemented |
| 0x049 | 73 | SendGameDataBundle | S->C | village | [village](#0x049-73-sendgamedatabundle--s-c) | optional |
| 0x3E8 | 1000 | EnterWorld | S->C | village | [village](#0x3e8-1000-enterworld--s-c) | implemented |
| 0x3ED | 1005 | WorldTick | S->C | village | [village](#0x3ed-1005-worldtick--s-c) | implemented |
| 0xED6 | 3798 | PingCode | C->S | village | [village](#0xed6-3798-pingcode--c-s-wire-type-0x2ed6) | implemented |
| 0xED7 | 3799 | PongCode | S->C | village | [village](#0xed7-3799-pongcode--s-c) | implemented |
| 0x3E9 | 1001 | AvatarData | S->C | village | [village](#0x3e9-1001-avatardata--s-c) | differs |
| 0x3EA | 1002 | AvatarLoggedIn | S->C | village | [village](#0x3ea-1002-avatarloggedin--s-c) | optional |
| 0x3EB | 1003 | AvatarRemove | S->C | village | [village](#0x3eb-1003-avatarremove--s-c) | implemented |
| 0x7D0 | 2000 | AvatarLocation | C->S | village | [village](#0x7d0-2000-avatarlocation--c-s-wire-type-0x27d0) | implemented |
| 0xF6E | 3950 | AvatarColorChange | C->S | village | [village](#0xf6e-3950-avatarcolorchange--c-s-wire-type-0x2f6e) | missing |
| 0xC80 | 3200 | LevelExpUpdate | S->C | village | [village](#0xc80-3200-levelexpupdate--s-c) | optional |
| 0xC81 | 3201 | StatsUpdate | S->C | village | [village](#0xc81-3201-statsupdate--s-c) | missing |
| 0x3EC | 1004 | NPCData | S->C | village | [village](#0x3ec-1004-npcdata--s-c) | differs |
| 0xBB9 | 3001 | MoveItem | C->S | village | [village](#0xbb9-3001-moveitem--c-s-wire-type-0x2bb9) | missing |
| 0xBBA | 3002 | DeleteItemRequest | C->S | village | [village](#0xbba-3002-deleteitemrequest--c-s-wire-type-0x2bba) | missing |
| 0xC1C | 3100 | ActiveItemsUpdate | S->C | village | [village](#0xc1c-3100-activeitemsupdate--s-c) | missing |
| 0xC1D | 3101 | InventoryUpdate | S->C | village | [village](#0xc1d-3101-inventoryupdate--s-c) | missing |
| 0xC1E | 3102 | ItemsFullSync | S->C | village | [village](#0xc1e-3102-itemsfullsync--s-c) | missing |
| 0xE10 | 3600 | OpenShop | C->S | village | [village](#0xe10-3600-openshop--c-s-wire-type-0x2e10) | missing |
| 0xE11 | 3601 | ShopInventoryData | S->C | village | [village](#0xe11-3601-shopinventorydata--s-c) | missing |
| 0xE1A | 3610 | ShopBuy | C->S | village | [village](#0xe1a-3610-shopbuy--c-s-wire-type-0x2e1a) | missing |
| 0xE1B | 3611 | ShopBuyResult | S->C | village | [village](#0xe1b-3611-shopbuyresult--s-c) | missing |
| 0xE24 | 3620 | ShopSell | C->S | village | [village](#0xe24-3620-shopsell--c-s-wire-type-0x2e24) | missing |
| 0xE25 | 3621 | ShopSellResult | S->C | village | [village](#0xe25-3621-shopsellresult--s-c) | missing |
| 0xF46 | 3910 | TradeRequest | S->C | village | [village](#0xf46-3910-traderequest--s-c) | unused |
| 0xF5A | 3930 | TradeOffer | S->C | village | [village](#0xf5a-3930-tradeoffer--s-c) | unused |
| 0xFA0 | 4000 | ChatCommand | C->S | village | [village](#0xfa0-4000-chatcommand--c-s-wire-type-0x2fa0) | optional |
| 0x7D1 | 2001 | CreateMiniGameTable | C->S | village | [village](#0x7d1-2001-createminigametable--c-s-wire-type-0x27d1) | missing |
| 0x0DA | 218 | MiniGameTableCreate | S->C | village | [village](#0x0da-218-minigametablecreate--s-c) | missing |
| 0x0D9 | 217 | MiniGameTableUpdate | S->C | village | [village](#0x0d9-217-minigametableupdate--s-c) | missing |
| 0x0D8 | 216 | MiniGameTableRemove | S->C | village | [village](#0x0d8-216-minigametableremove--s-c) | missing |
| 0x0DB | 219 | MiniGameNoTableLeft | S->C | village | [village](#0x0db-219-minigamenotableleft--s-c) | missing |
| 0x0DC | 220 | MiniGameNoPlayerSlotLeft | S->C | village | [village](#0x0dc-220-minigamenoplayerslotleft--s-c) | missing |
| 0x0D1 | 209 | JoinTable (cat. 5) | C->S | village | [village](#0x0d1-209-jointable--c-s-category-5-wire-type-0x50d1) | missing |
| 0x0CC | 204 | LeaveTable (cat. 5) | C->S | village | [village](#0x0cc-204-leavetable--c-s-category-5-wire-type-0x50cc) | missing |
| 0x0DE | 222 | Amount (cat. 5) | C->S | village | [village](#0x0de-222-amount--c-s-category-5-wire-type-0x50de) | missing |
| 0x0DC | 220 | Dice PlaceBets (cat. 5) | C->S | village | [village](#0x0dc-220-dice-placebets--c-s-category-5-wire-type-0x50dc) | missing |
| 0x0DD | 221 | Dice Roll (cat. 5) | C->S | village | [village](#0x0dd-221-dice-roll--c-s-category-5-wire-type-0x50dd) | missing |
| 0x12C | 300 | Poker Action (cat. 5) | C->S | village | [village](#0x12c-300-poker-action--c-s-category-5-wire-type-0x512c) | missing |
| 0x12D | 301 | Poker ActionWithWager (cat. 5) | C->S | village | [village](#0x12d-301-poker-actionwithwager--c-s-category-5-wire-type-0x512d) | missing |
| 0x12E | 302 | Poker SitOut (cat. 5) | C->S | village | [village](#0x12e-302-poker-sitout--c-s-category-5-wire-type-0x512e) | missing |
| 0x12F | 303 | MiniGameHand | S->C | village | [village](#0x12f-303-minigamehand--s-c) | missing |
| 0x190-0x193 | 400-403 | PawnChess Move / Capture / PlaceKing / NewGame (cat. 5) | C->S | village | [village](#0x190-0x193-400-403-pawnchess-actions--c-s-category-5-wire-types-0x5190-0x5193) | missing |
| 0x7D2 | 2002 | LeaveVillageRequest | C->S | village | [village](#0x7d2-2002-leavevillagerequest--c-s-wire-type-0x27d2) | implemented |
| 0x3EE | 1006 | WorldLoginAck | S->C | village | [village](#0x3ee-1006-worldloginack--s-c) | implemented |
| 0x093 | 147 | RequestPrivateMessageList | C->S | lobby | [tincat3](#0x093-147-requestprivatemessagelist--c-s) | implemented |
| 0x095 | 149 | PrivateMessage | S->C | lobby | [tincat3](#0x095-149-privatemessage--s-c) | missing |
| 0x094 | 148 | ChangePrivateMessage | C->S | lobby | [tincat3](#0x094-148-changeprivatemessage--c-s) | implemented |
| 0x097 | 151 | RemovePrivateMessage | C->S | lobby | [tincat3](#0x097-151-removeprivatemessage--c-s) | implemented |
| 0x096 | 150 | AddPrivateMessage | C->S | lobby | [tincat3](#0x096-150-addprivatemessage--c-s) | differs |
| 0x01F | 31 | EmailMessage | — | lobby | [tincat3](#0x01f-31-emailmessage--0x02b-43-emailnotification) | unused |
| 0x02B | 43 | EmailNotification | — | lobby | [tincat3](#0x01f-31-emailmessage--0x02b-43-emailnotification) | unused |
| 0x038 | 56 | RequestUserBuddyList | C->S | lobby | [tincat3](#0x038-56-requestuserbuddylist--c-s) | implemented |
| 0x03D | 61 | UserBuddyConn | S->C | lobby | [tincat3](#0x03d-61-userbuddyconn--s-c) | missing |
| 0x062 | 98 | AddUserBuddy | C->S | lobby | [tincat3](#0x062-98-adduserbuddy--0x063-99-removeuserbuddy--c-s) | implemented |
| 0x063 | 99 | RemoveUserBuddy | C->S | lobby | [tincat3](#0x062-98-adduserbuddy--0x063-99-removeuserbuddy--c-s) | implemented |
| 0x0AF | 175 | RegObserverBuddylist | C->S | lobby | [tincat3](#0x0af-175-regobserverbuddylist--0x0b0-176-deregobserverbuddylist--c-s) | differs |
| 0x0B0 | 176 | DeregObserverBuddylist | C->S | lobby | [tincat3](#0x0af-175-regobserverbuddylist--0x0b0-176-deregobserverbuddylist--c-s) | differs |
| 0x09C | 156 | RequestUserBuddyRefs | — | lobby | [tincat3](#0x09c-156-requestuserbuddyrefs--c-s) | unused |
| 0x09D | 157 | RequestUserIgnoreList | C->S | lobby | [tincat3](#0x09d-157-requestuserignorelist--c-s) | implemented |
| 0x0A0 | 160 | UserIgnoreConn | S->C | lobby | [tincat3](#0x0a0-160-userignoreconn--s-c) | optional |
| 0x09A | 154 | AddUserIgnore | C->S | lobby | [tincat3](#0x09a-154-adduserignore--0x09b-155-removeuserignore--c-s) | implemented |
| 0x09B | 155 | RemoveUserIgnore | C->S | lobby | [tincat3](#0x09a-154-adduserignore--0x09b-155-removeuserignore--c-s) | implemented |
| 0x0FC | 252 | GameResultSubmit | C->S | ranking | [tincat3](#0x0fc-252-gameresultsubmit--c-s-ranking-connection) | unused |
| 0x0FD | 253 | GameResultSubmitResult | S->C | ranking | [tincat3](#0x0fd-253-gameresultsubmitresult--s-c-ranking-connection) | unused |
| 0x0FE | 254 | RequestSingleUserRank | C->S | ranking | [tincat3](#0x0fe-254-requestsingleuserrank--c-s-ranking-connection) | unused |
| 0x0FF | 255 | ReceiveSingleUserRank | S->C | ranking | [tincat3](#0x0ff-255-receivesingleuserrank--s-c-ranking-connection) | unused |
| 0x100 | 256 | RequestRankRange | C->S | ranking | [tincat3](#0x100-256-requestrankrange--c-s-ranking-connection) | unused |
| 0x101 | 257 | ReceiveRankRange | S->C | ranking | [tincat3](#0x101-257-receiverankrange--s-c-ranking-connection) | unused |
| 0x102 | 258 | AddRankingServer | — | — | [tincat3](#0x102-258-addrankingserver--not-used) | unused |
| 0x035 | 53 | RequestUsers | C->S | lobby | [tincat3](#0x035-53-requestusers--c-s--0x03b-59-userdata--s-c) | implemented |
| 0x03B | 59 | UserData | S->C | lobby | [tincat3](#0x035-53-requestusers--c-s--0x03b-59-userdata--s-c) | implemented |
| 0x037 | 55 | RequestUserCharList | C->S | lobby | [tincat3](#0x037-55-requestusercharlist--c-s--0x03c-60-usercharconn--s-c) | implemented |
| 0x03C | 60 | UserCharConn | S->C | lobby | [tincat3](#0x037-55-requestusercharlist--c-s--0x03c-60-usercharconn--s-c) | implemented |
| 0x039 | 57 | RequestUserGroupList | C->S | lobby | [tincat3](#0x039-57-requestusergrouplist--c-s--0x03e-62-usergroupconn--s-c) | unused |
| 0x03E | 62 | UserGroupConn | S->C | lobby | [tincat3](#0x039-57-requestusergrouplist--c-s--0x03e-62-usergroupconn--s-c) | unused |
| 0x054 | 84 | AddUser | C->S | lobby | [tincat3](#0x054-84-adduser--c-s) | unused |
| 0x058 | 88 | ChangeUser | C->S | lobby | [tincat3](#0x058-88-changeuser--c-s) | implemented |
| 0x05C | 92 | RemoveUser | — | lobby | [tincat3](#0x05c-92-removeuser-0x013-19---0x01d-29-legacy-usergroup-admin) | unused |
| 0x013-0x01D | 19-29 | legacy user/group admin (RequestUser ... UserMgrResult) | — | lobby | [tincat3](#0x05c-92-removeuser-0x013-19---0x01d-29-legacy-usergroup-admin) | unused |
| 0x060 | 96 | AddUserKey | C->S | lobby | [tincat3](#0x060-96-adduserkey--0x061-97-removeuserkey--c-s) | unused |
| 0x061 | 97 | RemoveUserKey | C->S | lobby | [tincat3](#0x060-96-adduserkey--0x061-97-removeuserkey--c-s) | unused |
| 0x06D-0x074 | 109-116 | UserLoggedIn ... DeregObserverUserLogin | — | lobby | [tincat3](#0x06d-109---0x074-116-0x07b-123-0x07d-125-user-observers) | unused |
| 0x07B, 0x07D | 123, 125 | UserAdded, UserRemoved | — | lobby | [tincat3](#0x06d-109---0x074-116-0x07b-123-0x07d-125-user-observers) | unused |
| 0x07E, 0x080 | 126, 128 | CharAdded, CharRemoved | — | lobby | [tincat3](#0x06d-109---0x074-116-0x07b-123-0x07d-125-user-observers) | unused |
| 0x03A, 0x03F | 58, 63 | RequestPermIDAccess, PermIDAccess | — | lobby | [tincat3](#0x03a-58-requestpermidaccess--0x03f-63-permidaccess-0x090-144-requestpermid--0x091-145-permiddata-0x0b8-184-setuservisible-0x0ba-186-changegroupuser-0x0bb-187-changeuserkey) | unused |
| 0x090, 0x091 | 144, 145 | RequestPermID, PermIDData | — | lobby | [tincat3](#0x03a-58-requestpermidaccess--0x03f-63-permidaccess-0x090-144-requestpermid--0x091-145-permiddata-0x0b8-184-setuservisible-0x0ba-186-changegroupuser-0x0bb-187-changeuserkey) | unused |
| 0x0B8, 0x0BA, 0x0BB | 184, 186, 187 | SetUserVisible, ChangeGroupUser, ChangeUserKey | — | lobby | [tincat3](#0x03a-58-requestpermidaccess--0x03f-63-permidaccess-0x090-144-requestpermid--0x091-145-permiddata-0x0b8-184-setuservisible-0x0ba-186-changegroupuser-0x0bb-187-changeuserkey) | unused |
| 0x048 | 72 | RequestCharacters | C->S | lobby | [tincat3](#0x048-72-requestcharacters--c-s--0x04b-75-characterdata--s-c) | implemented |
| 0x04B | 75 | CharacterData | S->C | lobby | [tincat3](#0x048-72-requestcharacters--c-s--0x04b-75-characterdata--s-c) | implemented |
| 0x056 | 86 | AddCharacter | C->S | lobby | [tincat3](#0x056-86-addcharacter--c-s) | implemented |
| 0x04D | 77 | CreateCharacterFromPreview | both | lobby | [tincat3](#0x04d-77-createcharacterfrompreview--both--0x04f-79-addcharacterfrompreview) | unused |
| 0x04F | 79 | AddCharacterFromPreview | — | lobby | [tincat3](#0x04d-77-createcharacterfrompreview--both--0x04f-79-addcharacterfrompreview) | unused |
| 0x05A | 90 | ChangeCharacter | C->S | lobby | [tincat3](#0x05a-90-changecharacter--c-s) | implemented |
| 0x05E | 94 | RemoveCharacter | C->S | lobby | [tincat3](#0x05e-94-removecharacter--c-s) | implemented |
| 0x040 | 64 | RequestGroups | C->S | lobby | [tincat3](#groups) | unused |
| 0x045 | 69 | GroupData | S->C | lobby | [tincat3](#groups) | unused |
| 0x042 | 66 | RequestGroupUserList | C->S | lobby | [tincat3](#groups) | unused |
| 0x044 | 68 | GroupUserConn | S->C | lobby | [tincat3](#groups) | unused |
| 0x043 | 67 | RequestGroupAccess | C->S | lobby | [tincat3](#groups) | unused |
| 0x046 | 70 | GroupAccess | S->C | lobby | [tincat3](#groups) | unused |
| 0x055 | 85 | AddGroup | C->S | lobby | [tincat3](#groups) | unused |
| 0x059 | 89 | ChangeGroup | C->S | lobby | [tincat3](#groups) | unused |
| 0x05D | 93 | RemoveGroup | C->S | lobby | [tincat3](#groups) | unused |
| 0x064 | 100 | AddGroupUser | C->S | lobby | [tincat3](#groups) | unused |
| 0x065 | 101 | RemoveGroupUser | C->S | lobby | [tincat3](#groups) | unused |
| 0x068 | 104 | SetGroupAccess | C->S | lobby | [tincat3](#groups) | unused |
| 0x04E | 78 | RequestGuilds | C->S | lobby | [tincat3](#guilds) | unused |
| 0x052 | 82 | GuildData | S->C | lobby | [tincat3](#guilds) | unused |
| 0x050 | 80 | RequestGuildCharList | C->S | lobby | [tincat3](#guilds) | unused |
| 0x053 | 83 | GuildCharConn | S->C | lobby | [tincat3](#guilds) | unused |
| 0x057 | 87 | AddGuild | C->S | lobby | [tincat3](#guilds) | unused |
| 0x05B | 91 | ChangeGuild | C->S | lobby | [tincat3](#guilds) | unused |
| 0x05F | 95 | RemoveGuild | C->S | lobby | [tincat3](#guilds) | unused |
| 0x066 | 102 | AddGuildChar | C->S | lobby | [tincat3](#guilds) | unused |
| 0x067 | 103 | RemoveGuildChar | C->S | lobby | [tincat3](#guilds) | unused |
| 0x098 | 152 | ChangeGuildChar | C->S | lobby | [tincat3](#guilds) | unused |
| 0x08C | 140 | AddKey | C->S | lobby | [tincat3](#cd-keys) | unused |
| 0x08D | 141 | RemoveKey | C->S | lobby | [tincat3](#cd-keys) | unused |
| 0x08E | 142 | BanKey | C->S | lobby | [tincat3](#cd-keys) | unused |
| 0x08F | 143 | UnbanKey | C->S | lobby | [tincat3](#cd-keys) | unused |
| 0x079 | 121 | RequestMachines | C->S | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x07A | 122 | MachineData | S->C | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x0A7 | 167 | RequestMachineGameServers | C->S | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x07C | 124 | KickPermIDMachine | C->S | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x08A | 138 | KickPermIDServer | C->S | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x08B | 139 | KickPermID | — | lobby | [tincat3](#machines-and-kicks) | unused |
| 0x0B4 | 180 | RequestServerInfo | C->S | lobby | [tincat3](#0x0b4-180-requestserverinfo--c-s--0x0b5-181-serverinfodata--s-c) | unused |
| 0x0B5 | 181 | ServerInfoData | S->C | lobby | [tincat3](#0x0b4-180-requestserverinfo--c-s--0x0b5-181-serverinfodata--s-c) | unused |
| 0x075 | 117 | RegObserverUptime | C->S | lobby | [tincat3](#0x075-117-regobserveruptime--0x076-118-deregobserveruptime--0x0b6-182-uptimedata) | unused |
| 0x076 | 118 | DeregObserverUptime | — | lobby | [tincat3](#0x075-117-regobserveruptime--0x076-118-deregobserveruptime--0x0b6-182-uptimedata) | unused |
| 0x0B6 | 182 | UptimeData | S->C | lobby | [tincat3](#0x075-117-regobserveruptime--0x076-118-deregobserveruptime--0x0b6-182-uptimedata) | unused |
| 0x0AD | 173 | GetStatisticsConnection | C->S | lobby | [tincat3](#0x0ad-173-getstatisticsconnection--0x0ae-174-statisticsconnection) | unused |
| 0x0AE | 174 | StatisticsConnection | S->C | lobby | [tincat3](#0x0ad-173-getstatisticsconnection--0x0ae-174-statisticsconnection) | unused |
| 0x030-0x034 | 48-52 | Statistics item messages | — | — | [tincat3](#0x030-48---0x034-52-statistics-item-messages) | unused |
| 0x087 | 135 | RestoreUser | C->S | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x089 | 137 | RestoreChar | C->S | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x0B2 | 178 | ChangePatchlevel | — | — | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x0B7 | 183 | CheckLevel | — | — | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x0B9 | 185 | DownloadLogs | — | — | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x0BF | 191 | AddUsercomm | — | — | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x0C1 | 193 | UsercommRequestUserdata | C->S | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | open |
| 0x0C2 | 194 | UsercommUserData | S->C | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | open |
| 0x104 | 260 | CheckPlayerOnServerAndGetInfos | C->S | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x105 | 261 | CheckPlayerOnServerAndGetInfosReply | — | lobby | [tincat3](#backup-patch-level-and-server-side-admin) | unused |
| 0x00A | 10 | AdminRequestAllMessages | C->S | UC (cell) | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x00D | 13 | AdminMessageEntry | S->C | UC (cell) | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x00E | 14 | AdminAddMessageEntry | C->S | UC (cell) | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x00B | 11 | AdminUpdateMessage | C->S | UC (cell) | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x00F | 15 | AdminRemoveMessageEntry | C->S | UC (cell) | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x008, 0x009, 0x00C, 0x020, 0x021 | 8, 9, 12, 32, 33 | AdminRequestMsgList, AdminRequestMessage, AdminMessageList, AdminAddEmailMessageEntry, AdminRequestEmailList | — | — | [tincat3](#cyclic-admin-messages-server-messages) | unused |
| 0x022 | 34 | BrokerAddItem | C->S | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x023 | 35 | BrokerChangePrize | both | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x024 | 36 | BrokerRemoveItem | C->S | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x025 | 37 | BrokerGetItem | C->S | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x026 | 38 | BrokerItem | S->C | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x027 | 39 | BrokerGetItemList | C->S | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x028, 0x029 | 40, 41 | BrokerGetLimit, BrokerLimit | — | — | [tincat3](#broker-auction-house) | unused |
| 0x02C | 44 | BrokerBuyRequest | C->S | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x02D | 45 | BrokerNotification | both | UC (cell) | [tincat3](#broker-auction-house) | unused |
| 0x02E | 46 | BrokerSoldNotification | — | — | [tincat3](#broker-auction-house) | unused |
| 0x02F | 47 | BrokerItemListFinished | S->C | UC (cell) | [tincat3](#broker-auction-house) | unused |

## Login, authentication and the UC/chat connection

### Login sequence at a glance

Lobby connection: [known] [PROVEN]
```
TinCat logon -> C 188 CheckVersion -> S 42 Result(0)              (state 4 -> 5)
             -> C 201 StartAuthenticateSession(key)
             -> S 202 AckAuthenticateSession(cipher)              (state 5 -> 6 -> 7)
             -> C 204 AuthenticateUser | 203 SelfRegistration
             -> S 207 SessionKey(perm_id, cipher)                 (state 7 -> 8, OnConnected)
SADK LobbyManager: Authorized(3) -> C 161 PropertyGet(1,1) -> S 162 PropertyData   (4 -> 5)
             -> 5 -> 6: C 189 AssignServer(type 2) -> S 192 UsercommServerData -> UC dial;
                        C 105 RequestMOTD -> S 106 MOTD; character, buddy and ignore lists
             -> 6 -> 7 once MotD + char + buddy + ignore lists are all done (S 00464ee0)
```
UC connection (and the base login of the village and referee connections): [known] [PROVEN]
```
TinCat logon -> C 188 -> S 42 Result(0) -> C 211 -> S 212(nonce) -> C 213(token) -> S 153(0)  (state 8)
```

### Lobby connection (:7070): version, ECDH/Twofish auth, account, MOTD, CD keys

The lobby connection is `ConnectionManagerINet` connType 0. The handler is `HandlerLobby` in mode
0 (SelfRegistration, from CreateUser S 004633f0), mode 1 (AuthenticateUser, from Login S 004630e0),
mode 2 (Support) or mode 3 (Server). The game only uses modes 0 and 1. [known] Logout (S 00463710)
sends no NETMSG. It only disconnects. [inferred]

#### 0x0BC (188) CheckVersion — C->S

**Contract.** The client sends this on every connection (lobby, UC, server-id) as soon as the
TinCat logon completes. Sender: `HandlerLobby::OnLoggedIn` T 10023bf0, which is ICF-shared slot 1
of the three handlers. [known]

| Field | Type | Value |
|---|---|---|
| type | UNSHORT | 188 |
| version | SISHORT | **27 (0x1B), constant** [known] |
| subversion | SISHORT | never written, so 0 [known] |
| ticket_id | UNLONG | ticket of request type 0xBC |

The sender then sets the connection state to 4. If the send fails, it calls OnError(conn, rc),
releases the ticket and disconnects. [known]

**Required server behaviour.**
- Reply with **Result(42) errorcode 0** and the same ticket_id. [known] [PROVEN]
- Lobby: errorcode 0 in state 4 makes the client send 201 and go to state 5.
- UC: errorcode 0 in state 4 makes the client send 211.
- Server-id connections: errorcode 0 in state 4 makes the client send 211, or 224 TANLogin when
  the connection was opened with ConnectWithData.
- Any errorcode other than 0 makes the client call OnError and close the connection. [known]
- A Result that arrives while the state is not 4 is only logged ('CheckVersion-result received in
  state %u'), and the ticket leaks. [known]
- 188 does **not** carry a patch level. The server cannot see the game's `patchlevel 9212` here.
  [known]

Stub: `_h_check_version` sends `Result(0)`. Matches.

**Open decisions.**
- **L1** Which versions to accept. The client accepts errorcode 0 for any version and closes on
  any other errorcode. Real clients always send 27. Default: accept everything with errorcode 0, or
  reject anything other than 27 if you want to enforce a version.

#### 0x02A (42) Result — S->C (login role)

**Contract.** msgdefs: `errorcode UNBYTE, errormsg STRING 32, ticket_id UNLONG`. During login the
client reads only `errorcode` and `ticket_id`. It never reads `errormsg`. [known]

| Ticket's request type | Lobby (T 10023cc0) | UC (T 10027080) |
|---|---|---|
| 0xBC CheckVersion | 0 -> continue (see 188); non-zero -> close | same |
| 0xCB..0xCE (203..206) | **any** Result, even errorcode 0 -> OnError + close (login failure) | n/a |
| 0xD3 (211) | n/a | **any** Result -> OnError + Disconnect |
| 0x69 (105) | no case: ignored, ticket kept | n/a |

**Required server behaviour.**
- A Result(42) is the only way to reject a credential message. The client treats it as a failure
  whatever the errorcode is. [known]
- Never send Result(42) to 211. [known]

Stub: `Conn.ok` sends errorcode 0 with errormsg=None. Matches.

**Open decisions.**
- **L2** The `errormsg` text and the non-zero errorcode values. The client reads neither for
  login, so it accepts any values. Default: errormsg None, errorcode 1 for a generic failure.

#### 0x0C9 (201) StartAuthenticateSession — C->S

**Contract.** Sent by T 10023cc0 in the case-0x2a/0xBC branch (push 0xC9 @100242b8), after
CheckVersion succeeds in state 4. The state becomes 5. [known]

| Field | Type | Content |
|---|---|---|
| key | MEMBLOCK | DER SEQUENCE{BIT STRING flags, INTEGER keysize 0x41 (65 = P-521), INTEGER x, INTEGER y}: the client's fresh secp521r1 public key (`Authenticator::GenerateKey` T 1002aac0) [known] |
| ticket_id | UNLONG | ticket for 0xC9 |

**Required server behaviour.**
- Run ECDH with this key and reply 202 in the same session. [known] [PROVEN]
- The client keeps the matching private key in `ConnectionManager+0xbc`, and it uses that key only
  for this session's 202. [known]

Stub: `crypto._parse_ec_key` + `handle_login_key`. Matches.

**Open decisions.** None. The client fixes the curve.

#### 0x0CA (202) AckAuthenticateSession — S->C

**Contract.**

| Field | Type | Content |
|---|---|---|
| cipher | MEMBLOCK | An LTC `ecc_encrypt_key` blob (board #514): DER SEQUENCE{ OID of the hash, OCTET STRING server ephemeral public key = SEQUENCE{BIT STRING flags 0, INTEGER keysize 66, INTEGER x, INTEGER y}, OCTET STRING (secret XOR hash(ECDH shared point)) } [known] |
| ticket_id | UNLONG | echo of the 201 ticket [inferred] |

The client handles it in T 10023cc0 case 0xCA:
1. It requires **state 5**. In any other state it logs the message and drops it. [known]
2. It decrypts `cipher` with `Authenticator::DecryptSharedSecret` T 1002ade0 (Authenticator vtable
   slot 3) using its own private key. The secret goes to `ConnectionManager+0x1be` (capacity 0x400
   bytes) with its length at `+0x5be`. [known]
3. If decryption fails, the client calls OnError(conn, **0xCA**) and disconnects. [known]
4. On success it sets state 6 and sends 203/204/205/206 according to the handler mode. It then
   sets state 7. [known]

`ecc_decrypt_key` (T 1003aa20) rejects the blob in these cases: unknown hash OID, secret longer
than the hash output, or a point that is not on the curve. [inferred, LTC source + decompile]

**Required server behaviour.**
- Generate an ephemeral P-521 key and compute ECDH with the 201 key.
- Hash the shared x-coordinate. The stub left-pads it to 66 bytes and uses SHA-512.
- XOR the hash with a server-chosen secret.
- Encode the blob above. [PROVEN] (`crypto.handle_login_key`)
- The secret becomes the Twofish-CTR key for the client's 203/204 blob and for the 207 unwrap.
  Its length must therefore be a valid Twofish key length. [inferred: LTC `twofish_setup` accepts
  16/24/32 bytes]

Stub: 32-byte random secret, SHA-512 OID. Matches.

**Open decisions.**
- **L3** Secret length and content. The client accepts a length up to the hash size (64 for
  SHA-512) that is also a Twofish key size: **16, 24 or 32 bytes** [inferred]. Default: 32 random
  bytes.
- **L4** Hash OID. The client accepts any hash registered in its LTC table whose output is at
  least as long as the secret [inferred]. Default: SHA-512 (2.16.840.1.101.3.4.2.3), which is
  proven.

#### 0x0CB (203) SelfRegistration — C->S

**Contract.** Account creation. The CreateAccountDialog (S 0043e080) calls LobbyManager CreateUser
S 004633f0, which runs `ConnectionManagerINet::RegisterUser` and handler mode 0. [known]

| Field | Type | Content |
|---|---|---|
| cipher | MEMBLOCK | IV(16 random) ‖ Twofish-CTR(202 secret, IV, plaintext) [known] |
| ticket_id | UNLONG | ticket for 0xCB |

Plaintext (`Authenticator::EncryptCreateUserData` T 1002aee0): [known]

| Field | Type |
|---|---|
| nameLen | u8 |
| name | char[nameLen], the plain username with no NUL and no '@s2k8' (that suffix is dead code in S 004633f0) |
| pwLen | u8 |
| password | char[pwLen] |
| keyCount | u8 (the game sends 1) |
| per key: keyType | u8 (the game sends 1) |
| per key: keyLen | u8 (16) |
| per key: key | char[keyLen], the CD key, dashes removed and uppercased (S 0043e080) |
| salt | 128 random bytes |

The account e-mail is **not** in 203. It is sent after login through CharacterManager::UpdateEMail
(S 00464ee0, state 5 -> 6). [inferred]

**Required server behaviour.**
- To accept: send **207 SessionKey**. The creation completes exactly like a login. [known]
- To refuse: send **Result(42)** with any errorcode. The client fails and closes. [known]

Stub: `_h_auth_cipher` decrypts the blob, logs the name and key, and always sends 207. Matches.

**Open decisions.**
- **L5** Registration policy: name uniqueness, password rules, whether the CD key is valid or
  already used. The client accepts any outcome, because it only distinguishes 207 from a Result.
  Default: create the account if the name is free, and refuse with Result(42) errorcode 1
  otherwise.

#### 0x0CC (204) AuthenticateUser — C->S

**Contract.** The normal login. LoginDialog (S 0043cbf0) calls LobbyManager::Login S 004630e0,
which runs `ConnectionManagerINet::LoginUser` T 10030f00 and handler mode 1. [known]

| Field | Type | Content |
|---|---|---|
| cipher | MEMBLOCK | IV(16) ‖ Twofish-CTR(202 secret, IV, plaintext) [known] |
| ticket_id | UNLONG | ticket for 0xCC |

Plaintext (`Authenticator::EncryptCredentials` T 1002b560): [known]

| Field | Type |
|---|---|
| nameLen | u8 |
| name | plain username |
| pwLen | u8 |
| password | char[pwLen] |
| hashLen | u8 = 64 |
| cdKeyHash | SHA-512 over the keys sorted by (keyType, key text), each written as [u8 keyType][key text] (`HashCDKeys` T 1002ba70) |
| salt | 128 random bytes |

**The CD key is never sent in clear here**, only its hash. The game passes one key, of type 1.
[known]

**Required server behaviour.** Same as 203: send 207 to accept, Result(42) to refuse. [known]
[PROVEN]

Stub: `decode_login_blob` looks for a clear `[1][1][16]` key after the password. On 204 that
finds nothing, so only the log is affected (cosmetic). The stub binds the connection to the named
player (`players.resolve_by_username`) and sends 207.

**Open decisions.**
- **L6** Credential policy. Options: compare the password, compare the CD-key hash with
  SHA-512([0x01] + key) for keys stored at registration, and decide whether unknown names are
  auto-created. The client accepts any 207. Default: require a known user and a matching password,
  and keep the CD-key hash check optional.

#### 0x0CD (205) AuthenticateSupport — C->S

**Contract.** Same cipher and plaintext as 204 (handler mode 2, `LoginSupport` T 10030f70). [known]
The game client never selects this mode. [inferred]

**Required server behaviour.** Same as 204.

**Open decisions.**
- **L7** Whether to accept 205/206 at all. Default: refuse with Result(42). The SAdK client never
  sends them, and the stub currently treats 206 like 204.

#### 0x0CE (206) AuthenticateServer — C->S

**Contract.** Same as 204 (handler mode 3, `LoginServer` T 10030fe0). The game does not use it.
[inferred] **Required server behaviour.** Same as 204. **Open decisions.** See L7.

#### 0x0CF (207) SessionKey — S->C

**Contract.**

| Field | Type | Client use |
|---|---|---|
| perm_id | UNLONG | Written to `ConnectionManager+0x24`. This becomes the local perm id (SADK `LobbyManager+0x54c`) and the `perm_id` in 213. [known] |
| cipher | MEMBLOCK | IV(16) ‖ Twofish-CTR(202 secret, IV, sessionKey). `DecryptSessionKey` T 1002bf40 writes the plain session key to `ConnectionManager+0x38`, with capacity 0x80 in its length word `+0xb8` (set @100240b1). [known] |
| ticket_id | UNLONG | Released after handling. Not compared with the request type. [known] |

T 10023cc0 case 0xCF:
1. It requires **state 7**. In any other state it logs the message and releases the ticket. [known]
2. If decryption fails, the client calls OnError(conn, **0xCB**) and disconnects. [known]
3. On success it stores perm_id, sets **state 8**, and calls the listener OnConnected. SADK
   LobbyManager then goes Authorizing(2) -> Authorized(3). [known]

**Required server behaviour.**
- Send exactly one 207 in reply to 203/204, with a decryptable cipher. **This message, not 153,
  completes the lobby login.** [known] [PROVEN]
- The session key becomes the Twofish key for every later 213 token on the UC, village and
  referee connections (T 10027080 passes `+0x38`/`+0xb8` to GenerateToken). It must therefore be
  a valid Twofish key length. [known for the key use; inferred for the length rule]

Stub: a 32-byte random session key, encrypted under the 202 secret. **If the `twofish` module is
missing, the stub sends cipher=None and the client fails with OnError 0xCB.** This is an
environment hazard, not a wire error.

**Open decisions.**
- **L8** perm_id value. The client accepts any u32. Constraints the rest of the system relies on:
  - Keep it unique per account and stable across logins. The referee LoginSuccess check at
    S 0047ac20 compares it with `LobbyManager+0x54c`.
  - Avoid 0, which the server-id 153 path treats as "no overwrite".
  - Avoid the TinCat peer ids 0xEFFFFFxx.
  - Avoid the EnterWorld ServerPerm, because chat from that id is rendered as [SYSTEM]
    (S 00436180, board #1445).

  [inferred] Default: a sequential account id starting at 1.
- **L9** Session key. The client accepts up to 0x80 bytes, but it must be 16, 24 or 32 bytes to
  key Twofish [inferred]. Default: 32 random bytes per login. Keep it on the server if you want to
  verify 213 tokens (L16).

#### 0x004 (4) RequestLogin — C->S (not sent)

**Contract.** msgdefs: `nick STRING 256, password STRING 32, cd_key STRING 128, keypool UNSHORT,
patchlevel UNLONG, ticket_id`. tincat3 has no builder that writes `nick` or `patchlevel`. The
lobby login is only 188 -> 201 -> 203/204. [inferred, board #4781]

**Required server behaviour.** None. A server never needs to handle it.

Stub: `_h_request_login` is unreachable legacy code.

**Open decisions.** None.

#### 0x047 (71) RequestCreateAccount — C->S (not sent)

**Contract.** The same layout as 4. It has no client builder. [inferred]

**Required server behaviour.** None.

Stub: `_h_create_account` is unreachable.

**Open decisions.** None.

#### 0x0A1 (161) PropertyGet — C->S (login-time version gate)

**Contract.** msgdefs: `kategory SILONG, index SILONG, ticket_id UNLONG`. In SADK state
Authorized(3) -> CheckingVersion(4), `StatePump_Tick` S 00464ee0 queues
`Properties::RequestProperty(1, 1, OnVersionChecked_State4to5)` (S 0048ecb0). The request is sent
with **kategory 1, index 1**. [known] The general Properties protocol is in the tincat3 section (Properties). Only the gate is described here.

**Required server behaviour.** Reply with 162 for (1,1). [known] [PROVEN]

**Open decisions.** See L10.

#### 0x0A2 (162) PropertyData — S->C (version gate reply)

**Contract.** msgdefs: `kategory SILONG, index SILONG, value SILONG, ticket_id UNLONG`.
`Properties::PropertyDataReceived` S 0048e920 matches the reply FIFO against the oldest pending
request. A mismatched kategory or index is reported as a failure. [inferred] Then
`OnVersionChecked_State4to5` S 00464e70 handles the result: [known]

| Case | Effect |
|---|---|
| state != CheckingVersion(4) | ignored |
| request failed | DisconnectAll, notify error **0x6F (111)**; the login fails |
| `g_ClientProtocolVersion` (S 0087aed8) != 0 **and** (int)g_ClientProtocolVersion < value | DisconnectAll, notify **0x3E (62)** "client too old" |
| otherwise | state 5 VersionChecked |

`g_ClientProtocolVersion` has the static value **1000** (read_memory S 0087aed8 = e8 03 00 00).
LoginDialog (S 0043cbf0) and CreateAccountDialog (S 0043e080) overwrite it with
`[LobbyClient] ProtocolVersion` (S 00465380) only when that key is present (not -1). [known] The
same value is the server-browser match key (board/stub `LOBBY_PROTOCOL_VERSION`).

This property is the client's real patch-level gate. `network.ini patchlevel=9212` is not
involved. [known for the gate; inferred that 9212 never reaches the lobby wire, since no
login-path writer of `patchlevel` exists. The only tincat3 `patchlevel` reader is ServerInfoData
181, T 1002a080.]

**Required server behaviour.**
- Send 162 with kategory 1, index 1, and a value ≤ the client's ProtocolVersion.
- Without this reply LobbyManager stays in state 4 and the login never finishes. [known]
  [PROVEN] (the stub sends value 0)

**Open decisions.**
- **L10** The minimum protocol version (`value`). The client accepts any value ≤ its
  ProtocolVersion, which is 1000 by default. The client skips the check when its own value is 0.
  Default: 0 to accept every client, or 1000 to enforce the shipped build.

#### 0x069 (105) RequestMOTD — C->S

**Contract.** `ticket_id UNLONG` (request type 0x69). Sent by `MotDManager::RequestMOTD`
T 10029250, which is called from `ServerMessages::RequestMotD` S 004884d0 at state 5 -> 6. [known]

**Required server behaviour.**
- Reply with **106 MOTD** on the same ticket. [known] [PROVEN]
- A Result(42) is ignored: the Result switch has no 0x69 case and the ticket is kept.
- Without 106, ServerMessages stays busy and LobbyManager never leaves state 6, so "GlobalDataLoaded"
  never arrives (S 00464ee0 load mask, board #995/#4791). [known]

Stub: `_h_motd` sends 106 only. Matches.

**Open decisions.** None beyond L11.

#### 0x06A (106) MOTD — S->C

**Contract.** `txt STRING 256, ticket_id UNLONG`. T 10023cc0 case 0x6A reads txt, calls MotDManager
T 100292c0 (observer slot 2, error 0), and releases the ticket. SADK converts the text from UTF-8
to ANSI and stores it (S 00488550). The `!MOTD_ERROR` branch cannot be reached from the wire.
[known]

**Required server behaviour.** Send it once per 105. [PROVEN]

**Open decisions.**
- **L11** The MOTD text. The client accepts any UTF-8 text up to 255 bytes plus NUL (longer text is
  clamped). Stub: the maintainer's welcome text (`dispatch.MOTD`, 245 bytes).

#### 0x09E (158) RequestUserKeyList — C->S

**Contract.** `user_id UNLONG, ticket_id UNLONG`. Sent by `UserManager::RequestUserKeyList`
T 1002d6f0. [inferred] The stub receives it live. [PROVEN as observed]

**Required server behaviour.**
- Send N × **159 UserKeyConn** with the same ticket, then **Result(42) errorcode 0** on that
  ticket. [inferred, board #345]
- Rows on any other ticket are dropped.
- An empty list (Result only) reports observer(NULL, 0, 0).
- Without the Result, the UserManager busy flag stays set and later key-list requests return 4
  forever. [inferred]

Stub: `_h_cdkeys` sends one 159 and then Result(0). Matches.

**Open decisions.** See L12.

#### 0x09F (159) UserKeyConn — S->C

**Contract.** Read by T 10023cc0 case 0x9F, which accepts it only when the ticket's request type is
0x9E. [known]

| Field | Type | Note |
|---|---|---|
| user_id | UNLONG | |
| cd_key | STRING 128 | |
| keypool | UNSHORT on the wire | **read with the byte accessor** (vtbl+0x5c): only the low byte counts [known] |
| ticket_id | UNLONG | the 158 ticket |

**Required server behaviour.** Keep keypool below 256. [known]

**Open decisions.**
- **L12** Which keys to list. The client does not validate the content. Default: the account's
  registered key (from 203) with keypool 1. The stub currently sends a placeholder key.

#### 0x077 (119) RequestSingleCdKey — C->S

**Contract.** `cd_key STRING 128, keypool UNSHORT, ticket_id`. No SADK caller has been mapped, and
the stub has not seen it live. [inferred]

**Required server behaviour.** If it ever arrives, answer with 120 on the same ticket. [inferred]

Stub: no handler, so it falls into the default-ack (Result 0).

**Open decisions.** See L13.

#### 0x078 (120) CdKeyData — S->C

**Contract.** `cd_key STRING 128, keypool UNSHORT (read as u8), banned LBOOL, user_id UNLONG,
ticket_id`. T 10023cc0 case 0x78 accepts it only on a 0x77 ticket. [known]

**Required server behaviour.** Send it only as the reply to 119. [known]

**Open decisions.**
- **L13** The banned flag and user mapping for a queried key. The client accepts any values.
  Default: banned=0, user_id = the owner's perm_id, or 0 if the key is unknown.

#### 0x0BD (189) AssignServer, server_type 2 — C->S (UC server request)

**Contract.** Only the UC role is described here. The referee (4/4) and game (5/1) roles belong to
the hosting section. `HandlerUserComm::RequestServerAssign` T 10027630 sends it on
the lobby connection when the UC connection is opened (S 00464ee0, state 5 -> 6). [known]

| Field | Type | Value |
|---|---|---|
| server_type | UNBYTE | 2 |
| server_subtype | UNBYTE | not written (0) |
| ticket_id | UNLONG | request type **0x109**, not 189 |

**Required server behaviour.** Reply with **192 UsercommServerData**. [PROVEN]

**Open decisions.** See L14.

#### 0x0C0 (192) UsercommServerData — S->C

**Contract.** T 10023cc0 case 0xC0 reads only the fields below. It does not check the ticket. It
calls `ConnectionReal::ConnectToServer` T 10030420, which dials **every time it receives a 192**.
[known]

| Field | Type | Client use |
|---|---|---|
| server_id | UNLONG | stored at UC conn+0x1c |
| ip | STRING 128 | dial address |
| port | UNLONG | dial port |
| server_type | UNBYTE | not read |
| version | STRING 32 | not read |
| data | MEMBLOCK | not read |
| ticket_id | UNLONG | not checked |

**Required server behaviour.**
- Send exactly **one 192 per UC connection that should exist**. [known] [PROVEN]
- Every extra 192 opens another UC socket that the client never closes. With the 60 s referee
  re-assign cadence, a 192 per assign leaks one socket per minute and ends in `bad_alloc`
  (stub log 2026-08-08). [PROVEN]

Stub: sends 192 only when the player has no live UC connection. Matches.

**Open decisions.**
- **L14** The UC endpoint (ip, port, server_id). The client accepts any reachable address and any
  u32 server_id. Default: the advertised IP, port 7071, server_id 1.

#### 0x0D6 (214) ValidateToken — S->C (not consumed)

**Contract.** msgdefs: `perm_id, cipher MEMBLOCK, nonce MEMBLOCK, ticket_id`. 214 (0xD6) is
outside the jump-table range of HandlerGS T 10023460 and HandlerUserComm T 10027080 (bound 0xAA
after subtracting 0x2a). The client logs 'Invalid message-type' and drops it. [known]

**Required server behaviour.** Never send it. [known] [PROVEN] (the stub never sends 214)

**Open decisions.** None.

### UC / chat connection (:7071): token login and chat

The UC connection is `ConnectionManagerINet.ucConnection` (connType 1) with receive handler
`HandlerUserComm` T 10027080. The client dials it after 192. It carries two layers on one socket:
- **NETMSG layer (module 0x26B6):** the token login (188/211/212/213/153) and the channel
  requests 17 and 259.
- **CellManager layer (module 0x0062, msgType 0):** chat cells. The first PropertySet field `id`
  (u16) selects one of the templates registered by `CellManager::Init` T 1000cde0. The receive
  entry is `CellManager::Received_Data` T 1000ef30.

Channel chat (NETMSG 2/3/5/6/30/76/42) travels **inside** CellManager templates 2 and 3 as an
embedded NETMSG PropertySet. [known]

The village and referee connections run the same base login through `HandlerGS` T 10023460. The
differences are noted at 153 and 224 below. Their post-login traffic is in the hosting and village sections.

Inbound module-0x62 frames are dropped while the TinCat link is not fully connected
(stateFlags != 0xf). Frames whose msgType has no registered extension are dropped silently
(T 1000aa80, board #818). [known]

#### 188 / 42 on the UC connection

Same contract as on the lobby (see 188 and 42 above). On UC an errorcode-0 Result in state 4
**always** leads to 211; there is no TANLogin branch. [known] [PROVEN]

#### 0x0D3 (211) StartValidateTokenSession — C->S

**Contract.** `ticket_id UNLONG` (request type 0xD3). Sent by T 10027080 (push 0xD3 @100273c2).
After a successful send the state becomes 5. [known]

**Required server behaviour.**
- Reply with **212**. [known] [PROVEN]
- **A Result(42) on this ticket always fails the connection** (OnError + Disconnect), even with
  errorcode 0. [known]

Stub: `_h_token_start` sends 212. Matches.

**Open decisions.** See L15.

#### 0x0D4 (212) AckValidateTokenSession — S->C

**Contract.** `nonce MEMBLOCK, ticket_id UNLONG`. T 10027080 case 0xD4: [known]
1. Reads nonce. This case has no state check.
2. Calls `Authenticator::GenerateToken` T 1002c090 with key = `ConnectionManager+0x38`, length
   `+0xb8` (the 207 session key), an output buffer of 0x400 bytes, and the local perm id and name.
3. If token generation fails: OnError(conn, **0xCC**) + Disconnect.
4. Otherwise it sends 213 and releases this ticket.

**Required server behaviour.**
- Send a nonce whose length fits the token's u8 length field. [inferred]
- The nonce is carried back **inside** the encrypted token, not in clear. [inferred]

**Open decisions.**
- **L15** Nonce length and content. The client accepts lengths 0..255, because its token length
  field is a single byte. Longer nonces are truncated in the token and could overflow the 0x400
  buffer check. [inferred] Default: 128 random bytes (proven), remembered per connection if L16
  verification is wanted.

#### 0x0D5 (213) SendToken — C->S

**Contract.**

| Field | Type | Content |
|---|---|---|
| perm_id | UNLONG | conn+0x20, the perm id from 207 [inferred source] |
| cipher | MEMBLOCK | IV(16) ‖ Twofish-CTR(207 session key, IV, token) [known] |
| ticket_id | UNLONG | request type 0xD5 |

Token plaintext (GenerateToken T 1002c090, inverse DecryptToken T 1002c430): [inferred]

| Field | Type |
|---|---|
| idA | u32 |
| nameLen | u8 |
| name | plain username |
| hashLen | u8 (64) |
| cdKeyHash | SHA-512, as in 204 |
| idB | u32 |
| pwdLen | u8 |
| serverPassword | char[pwdLen], may be empty |
| nonceLen | u8 |
| nonce | the 212 nonce |
| salt | 128 random bytes |

**Required server behaviour.** Reply with **153 AddResult** on this ticket. [known] [PROVEN]

**Open decisions.**
- **L16** Whether to decrypt and verify the token (perm_id, name, nonce == the 212 nonce) with the
  session key issued to that perm_id. The client does not care. Default: verify when the session
  key is known, and refuse with a non-zero 153 if verification fails. The stub does not verify. It
  binds the connection by `perm_id` (`players.resolve_by_perm`).

#### 0x099 (153) AddResult — S->C (token completion)

**Contract.** `errorcode UNBYTE, errormsg STRING 32, id UNLONG, ticket_id UNLONG`. Only the 0xD5
ticket matters here. A 153 on any other ticket is ignored and that ticket is not released.
[known]

| Connection | errorcode 0 | errorcode != 0 | id |
|---|---|---|---|
| UC (T 10027080) | state 8; then observer vtbl+4 LoggedIn(conn, perm, 0) | OnError(conn, errorcode) + Disconnect; the LoggedIn notify still fires | read and **discarded** [known] |
| Server-id (T 10023460) | state 8 | failure | if != 0, **overwrites ConnectionManager+0x24** (the local perm id) [known] |
| Lobby (T 10023cc0) | not a login message there; 153 only completes Add*/RegObserver* requests | | |

**Required server behaviour.**
- Send errorcode 0 to complete the login. [PROVEN]
- On UC, do not push CellManager ChannelInfo **before** this 153. Pushing channels into the
  half-built chat container before login crashed the client about 215 ms after the 153 (stub s31).
  [PROVEN] Push them right after it.

Stub: `status_with_id(0, perm_id, ticket)`, followed by `chat.send_initial_reply`. Matches.

**Open decisions.**
- **L17** The `id` value: always the **account's** 207 perm_id, also when the token names a character.
  UC ignores it. On server-id connections a different non-zero value overwrites the client's own
  perm id, and the main connection later reports that value as its logout reason: the avatar screen
  goes back to the main menu only when the reason equals the 207 handle (S 00439c20 vs
  LobbyManager+0x548), otherwise "Back" clears the list and opens character creation [PROVEN
  2026-10-07: reason 100000 after a village login answered with the character id, 2 before]. To
  reject a login, send any non-zero errorcode.

#### 0x0E0 (224) TANLogin — C->S (server-id connections only)

**Contract.** `perm_id UNLONG, nonce MEMBLOCK, ticket_id` (request type 0xE0). `nonce` is the blob
the connection was opened with (ConnectWithData, T 10030a30; for example the 222 ConnectionData
nonce). HandlerGS T 10023460 sends it instead of 211 when conn+0x3c == 0. The UC connection never
sends it. [known]

**Required server behaviour.** Complete with 153 AddResult on the 0xE0 ticket. The rules are the
same as for the server-id row of 153. [known] Which connections use this path is in the village and hosting sections.

Stub: no handler, so it falls into the default-ack (Result 0). This is only correct if no
connection ever takes this path. Not settled here.

**Open decisions.**
- **L28** Whether to validate the nonce against the 222 that issued it (same shape as L16).

#### 0x011 (17) RequestJoinChannel — C->S (NETMSG layer on UC)

**Contract.** `ChatChannelManager::JoinChannel` T 10016e00, called from
`UserCommConnection::JoinChannel` S 00480070. [known]

| Field | Type | Value |
|---|---|---|
| cell_id | UNLONG | the channel id. In the world it comes from the EnterWorld(1000) channel map. |
| ticket_id | UNLONG | a **CellManager** ticket (cellMgr vtbl+0x6c), registered as context kind 1 |
| option | UNSHORT | never written (0) |
| password | STRING 32 | empty (S 007d4414) |
| from_id | UNLONG | local perm id (LobbyManager+0x54c) |

**Required server behaviour.** [known for the client logic; PROVEN for the stub sequence]
1. The cell must already be published with CellManager **template 0** on this connection. If it
   is not, the client answers template 9 with StatusReply result 2 and the join has no effect.
2. Send template **9** (joined) {cell_id, ticket_id, option}.
3. Complete the ticket with template **11 StatusReply** {cell_id, ticket_id, result_id}. This
   becomes event 0xE, which `HandleStatusReply` T 10017640 handles. A NETMSG 42 relayed in
   template 3 works the same way. The result codes are:
   - 0: success. The observer gets OnJoinChannel and `JoinChannelReceived` S 00480a70 runs.
   - 1: failure 0x8A.
   - 0x12: failure 0x8F.
   - **Any other code: no callback, and the join stays pending forever.**
4. Send NETMSG 5 UserJoinedChannel (inside template 3) for the joiner and for each existing
   member, and announce the joiner to the existing members.
5. A NETMSG Result(42) on module 0x26B6 does **not** complete a join, because HandlerUserComm
   never consults the CellManager tickets.

The client answers successful joined/status frames with its own template-11 StatusReply. The stub
logs it, and the server needs to do nothing with it. [PROVEN as observed]

Stub: `chat.handle_join_channel` sends 9, then 11(result 0), then 5 fan-out. Matches. A cell_id of
0 is answered as cell 1 and logged as an EnterWorld fault.

**Open decisions.**
- **L18** Join policy (password, capacity, bans). The client accepts result 0, 1 or 0x12, and
  nothing else. Default: 0.
- **L19** Membership fan-out. The client accepts any number of 5 frames. Default: one per member,
  one connection per player (`_live_one_per_player`).

#### 0x103 (259) RequestLeaveChannel — C->S (NETMSG layer on UC)

**Contract.** `cell_id UNLONG, ticket_id UNLONG (CellManager ticket, context kind 2), from_id
UNLONG`. Sender: `ChatChannelManager::LeaveChannel` T 10016f10, called from
S 004801e0 (UserCommConnection) and from the mini-game StopObserving (board #785). [known]

**Required server behaviour.**
- Complete the ticket with **template 11 StatusReply** (or a relayed 42). Result 0 is success,
  result 1 is failure 0x8B, and any other code is dropped silently. [known]
- Optionally send template 10 (left).
- Tell the other members with NETMSG 6.

Stub difference: there is no handler, so the default-ack sends NETMSG Result(42) on module 0x26B6.
HandlerUserComm ignores it (unknown ticket, type 0x107), so the leave never completes on the client
side. [inferred] Report only.

**Open decisions.**
- **L20** Whether a leave can be refused. The client accepts result 0 or 1. Default: 0.

#### 0x002 (2) ChatMessage — C->S, relayed S->C (inside CellManager)

**Contract.**
- **Outbound.** `ChatChannelManager::SendChatMessage` T 10017020 builds NETMSG 2
  {mode UNLONG = 0, or 1 when the emote flag is set; txt STRING 256; ticket_id unset (0); from_id
  = local perm}. It sends it as **template 2** with `cellMgr vtbl+0xa0(cell, 2, ps, self=1,
  except=-1)`. [known] SADK sends the raw untrimmed input line (S 00436860; board #3911), and
  emote lines arrive verbatim. [known]
- **Inbound.** Template 3 with message_id 2. `ChatChannelManager::HandleCellMessage` T 10017ba0
  labels the sender by its nick cache, keyed by the relay's `from_id`, and falls back to 'SERVER'
  if the id is not cached. [inferred]

**Required server behaviour.**
- Relay `data` unchanged as template 3 {message_id 2, data, cell_id, from_id = the speaker's
  perm_id, ispropset 1} to the cell members.
- Include the sender, because `self`=1 asks for an echo. [inferred]
- The client renders only lines from speakers whose nick it learned through NETMSG 5.
- Public channel relay works live between two clients. [PROVEN] (chat.py, 2026-08-01 note)

Stub: `chat._handle_message`. Matches.

**Open decisions.**
- **L21** Moderation and filtering (flood limits, text filters) and whether to honour `self`=0
  (the client always sends 1). The client accepts anything. Default: relay as is.

#### 0x01E (30) WhisperChatMessage — C->S (inside CellManager)

**Contract.** `ChatChannelManager::SendWhisper` T 10017100: {mode 3, or 4 with the emote flag;
txt; cell_id **= 1 always**; from_id = local perm; perm_id = target}. Sent as template 2 to cell 1
with message_id 30. [known]

**Required server behaviour.** Deliver the whisper as **NETMSG 3 PrivateChatMessage** inside
template 3, only to the target's UC socket. The client has no receive case for 30. [inferred]

Stub difference: the stub relays the frame to all cell-1 members as message_id 30. The client
deserializes it and ignores it, so whispers are not delivered. Report only.

**Open decisions.**
- **L22** Behaviour when the target is offline or ignores the sender. The client gets no error
  path for whispers. Default: drop silently, or send a 3 from the server perm with an explanatory
  text.

#### 0x003 (3) PrivateChatMessage — S->C (inside CellManager)

**Contract.** msgdefs: `mode UNLONG, txt STRING 256, cell_id UNLONG, from_id UNLONG, to_id UNLONG,
from_name STRING 256`. T 10017ba0 case 3 passes it to observer+0x14, which is
`UserCommConnection::PrivateChatReceived` S 004810a0. [inferred] That function behaves as
follows:
- It drops the whisper if the sender is ignored (relation 2).
- If from_id equals the local perm, the line is shown as the user's own outgoing whisper, labelled
  with to_id's cached name.
- Otherwise it caches from_id -> name and shows an incoming whisper.

**Required server behaviour.**
- Send it to the target with from_id = sender, to_id = target and from_name = sender's name.
- Echo the same message to the sender, so the outgoing line appears there. [inferred]

**Open decisions.** See L22.

#### 0x005 (5) UserJoinedChannel — S->C (inside CellManager)

**Contract.** `perm_id UNLONG, cell_id UNLONG, nick STRING 256`, carried in template 3 with
message_id 5 and ispropset 1. The client caches nick by perm_id (T 10017ba0) and adds the member
(S 0047fc30). [known] [PROVEN]

**Required server behaviour.** Send it for every member a client should see, before chat from
that member arrives. [PROVEN]

**Open decisions.**
- **L23** The display nick per perm_id. The client accepts any string up to 255 bytes. Default:
  the character name. The stub uses `char_name`.

#### 0x006 (6) UserLeftChannel — S->C (inside CellManager)

**Contract.** `perm_id UNLONG, cell_id UNLONG`. T 10017ba0 case 6 handles it and S 0047fd10 removes
the member. If BeenKicked(76) for the same perm was received first, the leave is reported as a
kick. [inferred]

**Required server behaviour.** Send it to the remaining members when a player's last UC
connection in the cell goes away. [inferred]

Stub: `chat.on_conn_closed`. Matches the intent. Not yet live-confirmed.

**Open decisions.** None beyond L19.

#### 0x04C (76) BeenKicked — S->C (inside CellManager)

**Contract.** `cell_id UNLONG, perm_id UNLONG`. T 10017ba0 latches it, and it is reported only on
the next UserLeftChannel with the same perm_id. If the next leave has a different perm, the client
logs 'Kickflag with wrong user' and the leave is lost. [inferred, board #458]

**Required server behaviour.** If you kick someone, send 76 immediately followed by 6 for the
same perm. [inferred]

**Open decisions.**
- **L24** Whether the server ever kicks. The client accepts kicks in any channel. Default: never.

#### 0x06B (107) RegObserverGlobalChat — C->S (not sent)

**Contract.** `ticket_id`. tincat3 has no builder for it on any connection. [inferred, board #4777]

**Required server behaviour.** None.

Stub: `_h_reg_global_chat` exists but is unreachable.

**Open decisions.** None.

#### 0x06C (108) DeregObserverGlobalChat — C->S (not sent)

Same as 107. [inferred]

#### 0x0A5 (165) Chat — S->C (not consumed)

**Contract.** `txt STRING 256, from_id UNLONG`. HandlerLobby has no case 0xA5, so it is logged as
'Invalid message-type' and dropped. HandlerUserComm drops it the same way, because it has no case
for it. [inferred]

**Required server behaviour.** Do not use it. Global chat goes through a CellManager cell (cell 1).

Stub difference: `_h_chat_message` (NETMSG 2 on module 0x26B6) relays as 165. That path is dead in
both directions. Report only.

**Open decisions.** None.

#### 0x0F0-0x0FB (240-251) UCRoute ... UCUserInfo — not used

**Contract.** These are defined in msgdefs. There is no builder for them, and neither T 10027080
nor the CellManager handles them. The chat protocol is the CellManager plus NETMSG
2/3/5/6/17/30/76/259. [inferred]

**Required server behaviour.** None. **Open decisions.** None.

#### CellManager template 0 ChannelInfo / PublishCell — S->C

**Contract.** Module 0x0062, msgType 0. Template 0 (T 1000cde0): [known]

| Field | Type |
|---|---|
| id | UNSHORT = 0 |
| data | MEMBLOCK: the serialized cell PropertySet |
| cell_id | UNLONG |
| ticket_id | UNLONG |

`ProcessPublishCell` T 1000ee30 behaves as follows: [known]
- It clones the cell template and deserializes `data` into it. A bad blob leaves the template
  defaults.
- A new cell_id creates the local cell (event 3).
- A known cell_id updates the cell's properties (event 4).

The cell PropertySet the stub sends (`chat.channel_data_blob`) is: publish STRING (template
default STRING 25), name, subject, creator, password STRING, protected, persistent, autodelete,
hidden u8, creator_pid u32. [PROVEN accepted; inferred field types]

**Required server behaviour.**
- After the UC 153, publish **every cell** the client may join, including the world zone cells
  16..31. An unpublished cell makes the join fail (StatusReply 2) and its chat is silently lost.
  [PROVEN] (2026-08-02 local-chat fix)

**Open decisions.**
- **L25** The channel set, names, subjects and flags. The client accepts any cell ids it is later
  told to join. Default: the stub's `DEFAULT_CHANNELS + ZONE_CHANNELS`.

#### CellManager template 2 CellMessage — C->S

**Contract.** {id u16 = 2, module_id u16, message_id u16 (the NETMSG id: 2 or 30), except u32 (-1),
data MEMBLOCK (the embedded NETMSG PropertySet), cell_id u32, self LBOOL (1), ispropset LBOOL}.
[known] **Required server behaviour.** See 2 and 30. [PROVEN for 2]

#### CellManager template 3 CellMessage relay — S->C

**Contract.** {id u16 = 3, message_id u16, data MEMBLOCK, cell_id u32, from_id u32, ispropset
LBOOL}. `HandleCellMessageMsg` T 1000df60 accepts it only on a client (this+0x20 == 1). It queues
event 0xD, and `ChatChannelManager::HandleCellMessage` T 10017ba0 deserializes `data` with the
template for message_id. The cases handled are 2, 3, 5, 6, 13, 35, 38, 42, 45, 47 and 76. Other
message ids are deserialized and ignored. [known]

**Required server behaviour.** Set ispropset = 1 and put a full NETMSG PropertySet (starting with
its `type` u16) in `data`. [PROVEN]

#### CellManager template 7 requestCreateCell — C->S

**Contract.** {id u16 = 7, data MEMBLOCK (cell PropertySet), ticket_id u32}. [known]
`ChatChannelManager::CreateChannel` T 10017210 registers context kind 3. [inferred]

**Required server behaviour.**
- Success is reported **only** by publishing the new cell (template 0, cell-added event).
- On the kind-3 ticket, a StatusReply/Result handles only 0x11 (failure 0x8C). Every other code is
  dropped. [inferred, T 10017640]

Stub difference: the stub replies StatusReply(cell 3, ticket, 0). The client ignores that reply,
so it never learns that the channel was created. Report only.

**Open decisions.**
- **L26** Whether players may create channels, and how ids are assigned. The client accepts any
  new cell_id published to it. Default: refuse with 0x11 until a channel-creation feature exists.

#### CellManager templates 9 / 10 Joined / Left — S->C

**Contract.** {id u16, cell_id u32, ticket_id u32, option u16}. `HandleJoinedLeftCellMsg`
T 1000e4a0 handles them: [known]
- A known cell queues event 10 (joined) or 11 (left).
- An unknown cell makes the client reply StatusReply 2.
- A queue failure makes the client reply StatusReply 3.

**Required server behaviour.** See 17 and 259. [PROVEN for 9]

#### CellManager template 11 StatusReply — both

**Contract.** {id u16 = 11, cell_id u32, ticket_id u32, result_id **u32**}. All three are read with
the UNLONG accessor (T 1000ef30 case 11) and become event 0xE, which `HandleStatusReply`
T 10017640 handles. [known] The client also sends its own 12-byte StatusReply. [PROVEN as
observed]

**Required server behaviour.** Use result_id as a u32 with the codes listed at 17 and 259. [known]

Stub difference: `chat.status_reply` packs result_id as u16, so the body is 2 bytes short of the
template (board #825). Joins still complete live with result 0. A non-zero code sent this way may
deserialize wrongly. [inferred] Report only.

**Open decisions.**
- **L27** Result codes for server-side refusals. The client acts on these values and drops
  everything else silently:
  - Join: 0, 1, 0x12.
  - Leave: 0, 1.
  - Create: 0x11.
  - Delete: 0x13.
  - Kick: 1.

## Hosting, server list, pre-game room and referee

### Server list (lobby connection)

The client watches two lists after login: server_type 4 (villages/worlds) and server_type 5 (hosted
games). tincat3 turns each `170` into a 0x5c-byte `GameServerDescriptor` (T 1002f5a0). The game then
routes the descriptor **by server_subtype only** (S 0046a440): subtype 2 = village, subtype 1 = hosted
game, any other subtype is dropped silently. [known]

#### 0x0AB (171) RegObserverServerList — C->S

**Contract.**

| # | Field | Type | Value sent by SAdK |
|---|---|---|---|
| 1 | send_all | LBOOL | 1 (hard-coded in T 10020540) |
| 2 | server_type | UNBYTE | 4, then a second message with 5 |
| 3 | room_id | UNLONG | 0 |
| 4 | level | UNBYTE | 0 |
| 5 | game_mode | UNBYTE | 0 |
| 6 | hardcore | UNBYTE | 0 (tincat3 refuses to send if ≥3) |
| 7 | selection | UNLONG | not written -> 0 |
| 8 | ticket_id | UNLONG | ticket category 0xab |

Sender: `ServerList::StartObservation` S 00468e80 -> T 10020540. It is sent once per lobby login,
from LobbyManager state 5->6 (S 00464ee0). [known]

**Required server behaviour.**
- Answer with zero or more `170 GameServerData` carrying **this ticket_id**, then one `Result(42)`
  `errorcode 0` on the same ticket. The Result completes the subscription
  (`StartObservationResultReceived` S 004693d0). That callback only logs, and a non-zero
  errorcode is never retried. [inferred]
- Register the connection as an observer for that server_type. Every later list change is **pushed**
  with `ticket_id 0` (see 170/169). [PROVEN] (stub `_push_to_obs`; cross-client browser live)
- The client does not use the bulk-list path. `GameServerDataReceived` S 00469700 has an original
  binary bug: it passes a past-the-end pointer. Only per-descriptor delivery
  (`GameServerAdded` S 00469610 -> S 0046a440) produces usable entries. [known]
- Stub difference: none.

**Open decisions.**
- **H1** Which entries to send for each server_type. The client accepts any number, including zero. For a
  type-4 request it needs at least one valid village (subtype 2) to show anything in the world
  switcher. Default: every registered entry of the requested type.
- **H2** Filter semantics for room_id/level/game_mode/hardcore. SAdK always sends 0. The LAN path
  stores level+1 (0 = any) and treats hardcore as tri-state (0 any, 1 only, 2 none) [inferred, board #856].
  Default: 0 = no filter.

#### 0x0AC (172) DeregObserverServerList — C->S

**Contract.** `ticket_id` UNLONG only. Sent by ServerList Reset/Destroy. [known, board #606]

**Required server behaviour.** Remove the observer. Reply `Result(42)` errorcode 0 on the ticket. No
client state depends on the reply. [inferred]
Stub difference: the stub answers with the default Result but keeps the observer registered until the
socket closes. [known]

**Open decisions.** None.

#### 0x0A6 (166) RequestServers — C->S (not used by SAdK)

**Contract.** msgdefs order `server_id, room_id, server_type, server_subtype, selection, ticket_id`.
Ticket category 0xa6 (T 100206d0). No SAdK caller sends it. The client lists through 171. [inferred]

**Required server behaviour.** `170`s with the ticket, then `Result(42)`. Note that tincat3 releases
the ticket after the **first** `170` on the 0xa6 path (T 10023cc0, bytes 10025113..10025196). Later
170s and the closing Result are dropped, so `OnRequestServersResult` T 10020b10 never fires after any
170. A list request with this message cannot complete correctly with more than zero entries. [known for the
code path, inferred for the consequence]

**Open decisions.** None relevant to SAdK.

#### 0x0AA (170) GameServerData — S->C

**Contract.** (msgdefs order; descriptor offset from T 1002f5a0; consumer reads from S 0048da70 for
games and S 00481640 for villages)

| # | Field | Type | Desc off | Read by the game? |
|---|---|---|---|---|
| 1 | server_id | UNLONG | +0x00 | yes: lookup key and assign result [known] |
| 2 | name | STRING 128 | +0x08 | yes: list name [inferred] |
| 3 | owner_id | UNLONG | +0x04 | not read [known] |
| 4 | description | STRING 128 | +0x0c | games: parsed as `build\|s226\|s225\|s227\|wager\|name1[\|name2…]` by S 0048d810. Fewer than 6 tokens fails silently [inferred] |
| 5 | ip | STRING 128 | +0x10 char[16] | games: parsed to 4 octets (+0x78..+0x84). The **joiner dials this address** (S 0048d030) [known] |
| 6 | port | UNLONG | +0x20 | games: +0x88, the joiner's dial port [known] |
| 7 | password_required | LBOOL | +0x24 | games: "Protected" flag, true only when ==1 [known] |
| 8 | server_type | UNBYTE | +0x28 | assign routing only (T 10021520) [known] |
| 9 | server_subtype | UNBYTE | +0x29 | 2 village / 1 game (S 0046a440); 5 diverts an assign reply [known] |
| 10 | version | STRING 32 | +0x2c | not read [known] |
| 11 | max_players | UNSHORT | +0x30 | games: max shown [known] |
| 12 | cur_players | UNSHORT | +0x32 | **not read for games** [known]; village count [inferred] |
| 13 | max_spectators | UNSHORT | +0x34 | games: occupied = max_spectators + ai_players [known] (S 0048db1b) |
| 14 | cur_spectators | UNSHORT | +0x36 | not read [known] |
| 15 | ai_players | UNSHORT | +0x38 | games: see max_spectators [known] |
| 16 | room_id | UNLONG | +0x3c | not read by the game list [known] |
| 17 | level | UNBYTE | +0x40 | not read [known] |
| 18 | game_mode | UNBYTE | +0x41 | not read [known] |
| 19 | hardcore | LBOOL | +0x44 | games: second flag on the "Protected" icon (==1) [known] |
| 20 | map | STRING 128 | +0x48 | games: map name [known] |
| 21 | running | LBOOL | +0x4c | **villages: add/remove opcode** (below); games: ignored [known] |
| 22 | locked_config | LBOOL | +0x50 | not read [inferred] |
| 23 | data | MEMBLOCK 0 | +0x54/+0x58 | villages: ServerDataBlock (below) [PROVEN] |
| 24 | ticket_id | UNLONG | — | routing (below) |

Senders: the server only. Paths by ticket:
- **ticket of a 171 (category 0xab)**: list entry.
- **ticket 0**: observer push, handled by `GameServerAdded` S 00469610.
- **ticket of a 189 (category 0x108)**: assign reply, handled by T 10021520 (see 189).

Village rules [known, S 0046a440; desc+0x4c = `running`, confirmed by the Ghidra struct offset]:
- **Unknown id**: the entry is added only if `running == 1`. Otherwise it is ignored silently.
- **Known id**: `running == 0` removes the entry. Any other value updates it.

Game rules [known]: unknown id -> added; known id -> updated. `running` is not checked, so a 170
cannot remove a game.

Village ServerDataBlock (`data`) = u32 **big-endian** roomId + u8 pending byte (0). The entry is
joinable only when roomId equals the client protocol version, 1000 here (S 00481640, match key
DAT_0087aed8). If the block is missing, the client logs "Invalid Server Data Block" and greys out
Enter. [PROVEN]

**Required server behaviour.**
- For a hosted game, echo what the host reported in 168/177. The browser computes its "occupied"
  count from `max_spectators + ai_players`. The host puts its human count in `max_spectators`. [known]
- Set `password_required = 1` when the host's latest 177 carried a non-empty `cipher`. Echo `hardcore`.
  [inferred]
- Echo the host's `description` verbatim. It carries the wager, settings and player names. [inferred]
- Keep server ids unique across **all** connection kinds. tincat3 looks up connections by server id
  (T 10019570). A village id that equals the UC server id (1) makes the client reuse the UC
  connection instead of dialling. [PROVEN] (stub `FAKE_VILLAGE` note)
- Stub differences:
  - The stub always sends `max_spectators 0` and `password_required False`.
  - Its 177 handler drops `max_spectators`, `ai_players`, `cipher` and `hardcore`.
  - So a hosted game lists as "0 + AI" occupied and never shows as protected. [inferred; boards #4771/#4772]

**Open decisions.**
- **H3** `server_id` values. The client accepts any u32 except 0xFFFFFFFF/0xFFFFFFFE, which are
  its INVALID/PENDING sentinels in ServerList+0x9c [inferred], and the value must be unique across all
  connections. Default: a counter starting at 100.
- **H4** `ip` for a hosted game. The client accepts a dotted IPv4 string of 15 chars or fewer, because
  the descriptor keeps char[16] and the client parses octets. A hostname is not expected to work.
  [inferred] Default: the host connection's public source address, because the client leaves
  168 `ip` unset.
- **H5** `owner_id`, `version`, `cur_spectators`, `level`, `game_mode`, `room_id` (games),
  `locked_config`: not read by the game, so any value is accepted. Default: echo the host's values,
  with `owner_id` = the host's perm_id.
- **H6** Village entries:
  - `name`: any value.
  - `max_players` / `cur_players`: any value (display only).
  - `running`: must be 1 to add the entry, and 0 removes it.
  - `data`: must carry roomId = 1000.

  Default: as the stub sends them.

#### 0x0A8 (168) AddGameServer — C->S

**Contract.** (as SAdK sends it; S 0046aaa0 -> T 10020ca0, ticket category 0xa8)

| # | Field | Type | Value |
|---|---|---|---|
| 1 | name | STRING 128 | `<avatar name><localized !LOBBY_GAME>` |
| 2 | description | STRING 128 | `build\|s226\|s225\|s227\|wager\|names…` (S 0046a850) |
| 3 | ip | STRING 128 | **not written** (NULL) |
| 4 | port | UNLONG | NComm game port (NComm manager+0x360, net-config gamePort) |
| 5 | server_type | UNBYTE | 5 |
| 6 | server_subtype | UNBYTE | 1 |
| 7 | cipher | MEMBLOCK | absent (the create call uses an empty password) |
| 8 | version | STRING 32 | `"1.0"` |
| 9 | max_players | UNSHORT | map max players |
| 10 | max_spectators | UNSHORT | 1 (the host itself) |
| 11 | ai_players | UNSHORT | 0 |
| 12 | room_id | UNLONG | 0 |
| 13 | level, game_mode | UNBYTE ×2 | 0, 0 |
| 15 | hardcore | LBOOL | 0 |
| 16 | map | STRING 128 | the first map file containing `MP_` |
| 17 | running, locked_config | LBOOL ×2 | 0, 0 |
| 19 | automatic_join | LBOOL | never written -> 0 |
| 20 | data | MEMBLOCK | NULL |
| 21 | ticket_id | UNLONG | category 0xa8 |

Before it sends, the host restarts NComm in host mode 4 and starts listening on `port`. It then sets
ServerList+0x9c = PENDING (-2). [inferred, board #1024]

**Required server behaviour.**
- Reply **`AddResult(153)`** `{errorcode 0, errormsg NULL, id = new server_id, ticket_id}`. This
  reaches `CreateResultReceived(id, errorcode)` S 0046a6a0, which latches the id into ServerList+0x9c.
  The host's 177 updates are enabled only after this. [PROVEN] (stub `_h_add_game_server`; host's 177
  stream follows live)
- If the result arrives while no create is pending, it is logged and dropped ("no create pending").
  [known]
- A non-zero errorcode resets +0x9c to INVALID, fires the create-failed list and **shuts down the host's
  NComm network** (S 0046a6a0). [known]
- Push the new game as `170` (ticket 0) to type-5 observers. [PROVEN]
- Whether a `Result(42)` can complete a 0xa8 ticket was not checked. 153 is the known-good reply.
  [inferred]

**Open decisions.**
- **H7** Accept or refuse a host. The client accepts errorcode 0 to succeed, and any non-zero value
  tears down the host network. Default: always accept.
- **H8** The id returned (see H3).

#### 0x0B1 (177) ChangeGameServer — C->S

**Contract.** (S 0046aff0 -> T 10021040, ticket category 0xb1)

| # | Field | Type | Value |
|---|---|---|---|
| 1 | name | STRING 128 | `<avatar name> <localized !LOBBY_GAME>` (with a space) |
| 2 | description | STRING 128 | as in 168, current names |
| 3 | cipher | MEMBLOCK | absent if there is no password. If the game has a password, it is the literal `"PASSWORD"` encrypted by tincat3 (ConnMgr key +0x38). The real password never leaves the client |
| 4 | max_players | UNSHORT | map max minus closed slots |
| 5 | max_spectators | UNSHORT | **human count** (CountHumanSlots) |
| 6 | ai_players | UNSHORT | AI slot count |
| 7 | room_id | UNLONG | 0 |
| 8 | level | UNBYTE | 0 |
| 9 | game_mode | UNBYTE | gameInfo+0x225 |
| 10 | hardcore | LBOOL | ranked flag gameInfo+0x22e |
| 11 | map | STRING 128 | gameInfo+0x208 |
| 12 | running, locked_config | LBOOL ×2 | 0, 0 |
| 14 | data | MEMBLOCK | NULL |
| 15 | property_mask | UNLONG | **never written -> 0** (T 10021040 ignores arg 16) |
| 16 | ticket_id | UNLONG | category 0xb1 |

The host sends this only when it has a real id (+0x9c not -1/-2), NComm state is 2, and the map loads.
It is re-sent on room changes. [inferred] There is no server_type/subtype/port/ip in 177. [known]

**Required server behaviour.**
- Reply `Result(42)` errorcode 0 on the ticket. It goes to `UpdateResultReceived` S 00469870, which
  only logs a non-zero code. [inferred]
- Update the hosted game record and push the updated `170` (ticket 0) to type-5 observers. [PROVEN]
  (push path)
- Treat `property_mask` as absent. All fields arrive every time. [known]
- Stub difference: it does not store `max_spectators`, `ai_players`, `cipher` or `hardcore` (see 170). [known]

**Open decisions.**
- **H9** How to map `cipher` to `password_required`. The client accepts any value. Default:
  non-empty cipher -> 1.

#### 0x0A9 (169) RemoveServer — C->S and S->C push

**Contract.** `server_id` UNLONG, `running` LBOOL (not written by the client -> 0), `ticket_id` UNLONG.
Client->server senders: S 00468410 (host leaves the setup dialog) and S 004683e0. Both use
server_id = ServerList+0x9c and ticket category 0xa9 (T 10021350). [known]

**Required server behaviour.**
- To the sender: `Result(42)` errorcode 0 on the ticket. It goes to `DeleteResultReceived`
  S 00469990, which resets +0x9c to INVALID. With a non-zero code, +0x9c is unchanged. [known]
- Host side of S 00468410: NComm shuts down only after the 169 send succeeds. It does not wait for the
  reply. [inferred]
- To every type-5 observer: push **`169 {server_id, running 0, ticket_id 0}`**. In T 10023cc0 case
  0xa9, a ticket-0 169 goes to listener +0x14 = face slot 5 `ServerList::RemoveServer` S 0046a5e0,
  which erases the game. A non-zero ticket only releases a ticket. [inferred, board #4773]
- When the host's lobby connection closes, push the same 169 for each of its games. [inferred]
- Stub difference: the stub removes the game but never pushes 169, so other browsers keep stale rows. [known]

**Open decisions.** None.

#### 0x0BD (189) AssignServer — C->S (referee request)

**Contract.** `server_type` UNBYTE, `server_subtype` UNBYTE, `ticket_id` UNLONG with category 0x108
and AssignServerTicketData{type, subtype} (T 10021830). tincat3 refuses types other than 3/4/5. The only
SAdK sender is `ServerList::RequestRefereeServer` S 00468f60, with **(4,4)**. [known] No SAdK path sends
(5,1). [inferred, board #4774]

Cadence: `LobbyManager::StatePump_Tick` S 00464ee0 sends it once when the state passes 5. It re-sends
when the +0x588 timer goes negative. A successful assign arms that timer to 60000 ms
(SetRefereeServerAddress S 004625d0). So the client sends one 189 every 60 s for the whole session
**only after the first assign succeeded**. If the first one fails, no 189 is ever sent again in that
process. [PROVEN] (60 s cadence observed live)

**Required server behaviour.**
- Reply exactly **one** `170 GameServerData` with **this ticket_id**. The 0x108 ticket is consumed by the
  first reply. [PROVEN]
- `server_type 4, server_subtype 5` is diverted to tincat3's RankingManager (T 10021520 -> T 10029a20),
  and the game is never told. **Any other pair** reaches `ServerList::GameServerAssigned` S 00469ad0,
  which calls the pending callback with `server_id` -> LM+0x580. [PROVEN] (4/4)
- Only `server_id` is used from this descriptor. The connection's address comes later, from 221/222.
  [PROVEN]
- `Result(42)` with a non-zero errorcode on this ticket means "assign failed". `AssignGameServerResultReceived`
  S 00469be0 calls the callback with 0. [known]
- Never send an unsolicited assign reply. With nothing pending, S 00469ad0 calls a NULL callback. [known]
- Stub behaviour beyond the contract: on the same 189, the stub also sends `192 UsercommServerData` to bring
  up the UC/chat connection, but only while the player has no live UC connection. 192 is handled by a
  generic dial handler that does not check the ticket, and it dials on every 192. [PROVEN] That belongs to the
  login section (192). The 189 itself is completed by the 170.
- Stub difference: the stub has an unreachable `(5,1)` branch. [inferred]

**Open decisions.**
- **H10** Referee server id. The client accepts any non-zero u32 that does not collide with another
  server id (an id of 0 leaves LM+0x580 unlatched). Keep it **stable**: on each 60 s retry, a different id
  closes the existing referee connection (S 004625d0). Default: a fixed id (stub: 77).
- **H11** Descriptor type/subtype for the reply. Any pair except (4,5) is accepted. Default: 4/4.

#### 0x0DD (221) RequestConnectionData — C->S

**Contract.** `perm_id` UNLONG, `server_id` UNLONG, `ticket_id` UNLONG. Two senders:
- `GameServerManager::RequestConnectionData` T 10021420, ticket category 0x10d.
- `HandlerGS` T 10023af0 for server-id connections (village, referee), ticket category 0xdd.

[inferred] In SAdK it is observed for the village world (id 50) and for the referee id. It is **not** used
to join a hosted game, because the joiner dials the 170 ip/port (S 0048d030). [known for S 0048d030;
observed ids PROVEN]

#### 0x0DE (222) ConnectionData — S->C

**Contract.**

| # | Field | Type | Use |
|---|---|---|---|
| 1 | perm_id | UNLONG | echo |
| 2 | server_id | UNLONG | key of the connection to address (T 10019570 matches conn+0x1c) |
| 3 | ip | STRING 128 | -> conn+0x14 (host) |
| 4 | port | UNLONG | -> conn+0x18 |
| 5 | nonce | MEMBLOCK 0 | passed to ConnectToServer T 10030420 |
| 6 | errorcode | UNBYTE | ≠0 -> FailConnect(errorcode) |
| 7 | errormsg | STRING 32 | |
| 8 | ticket_id | UNLONG | echo of the 221 |

[known: T 10023cc0 case 0xde, board #314]

**Required server behaviour.**
- Answer every 221 with a 222 for the requested `server_id`, `errorcode 0`, and the ip/port where that
  server listens. This is the **only** message that gives a server-id connection its address. A 170
  does not do it. [PROVEN] (referee and village live)
- For the referee id, return the referee listener. Answering the referee id with the world address made the
  client dial the wrong listener. [PROVEN]
- With ticket category 0x10d, a non-zero errorcode produces both the "join failed" (+0x34) and the
  "connection data" (+0x30) notifications. [inferred]

**Open decisions.**
- **H12** `ip`/`port` per server. Any reachable endpoint is accepted. Default: the advertised IP and the
  listener port of that server.
- **H13** `nonce`. Any bytes are accepted on the observed login path (211/212/213). The nonce would only be
  echoed on a 224 TANLogin path, which SAdK's referee/village login was not seen to take. [inferred]
  Default: 128 random bytes.

### Pre-game room (NComm P2P, host <-> peers)

**Reachability.** The host must accept inbound TCP on its game port; nothing in the client lets it be
reached any other way [known, static]:
- The host's match transport is a TinCat server: `TinCatNetwork::StartUp` S 0041e610 calls api Init with
  mode 1 when hosting (`CreateGameServer` S 0046aaa0 starts NComm in mode 4 = host).
- A TinCat server cannot dial out: `TinCat_CTRL::ConnectToIP` T 10009670 and `ConnectAsyncToIP`
  T 10009870 return error -0x1d in mode 1, and they are the only callers (via `KRNL_SendLogonRequest`
  T 10004660 / `KRNL_SendAsyncLogonRequest` T 10004980) of tincat3's `connect`.
- UDP (`sendto` / `recvfrom`) is used only by `NET_BCastSend` T 10032fd0 / `NET_BCastReceive`
  T 10033140, i.e. LAN broadcast; there is no hole punching.
- Neither SADK.exe nor tincat3.dll contains UPnP (no CLSID_UPnPNAT / IID_IUPnPNAT bytes, no
  natupnp/hnetcfg/INetFw strings).
So joiners need no forwarding, and the host needs TCP on its game port (5479 observed live). Making an
unreachable host joinable needs something on the host's side that dials out (a tunnel helper or VPN).


The host opens its room with 168. The joiner reads host ip/port from the 170 descriptor and runs
`GameServerInfo::JoinGame` S 0048d030 / `JoinGameWithPassword` S 0048d0c0:
`Shutdown -> StartUpNetwork(3) -> ConnectAndJoin` to that ip:port. A password is MD5-hashed client side
and checked by the host. [known] Everything below goes peer to peer. The lobby server neither sees nor
relays it. Its only duties for the room are the 170 address (H4) and keeping 177 changes visible.

Event router: `NComm_Manager::HandleEvent` S 0040e560 (jump table 0x30002..0x30012). [known]

#### 0x30001 (196609) UserInformation — joiner -> host
**Contract.** (S 00409950): header, then name (u16 len + bytes), NetGUID (20 B), i32 buildVersion,
i32 buildChecksum, u32 cfg94, u32 tribe, u32 tribe<<8|gender<<4|level, u32 colours, u32 avatarId,
MD5 password digest (16 B, or zeros). [known]
**Host behaviour**: kicks with `!VERSION MISMATCH`, `!CHECKSUM MISMATCH` or `!PASSWORD_MISMATCH`.
Otherwise it assigns a slot and broadcasts GameInformation. [known]
**Server**: nothing. **Open decisions.** None.

#### 0x30002 (196610) PlayerInformation — peer -> host
**Contract.** header, NetGUID, i32 tribe, i32 team, u32 colour (0xFFFFFFFF = keep; 0..7), i32
playerIndex. [known] Each change un-readies the player. Colour is made unique by a swap loop. [known]
**Server**: nothing.

#### 0x30003 (196611) GameInformation — host -> peers; forced variant 0x3000F
**Contract.** (S 00413ae0, class tag 0x66660101): the header, then:
- 6 × PlayerInfo: state u8, playerId u32, ownerGuid 20 B, joinFlag u8, name, playerIndex i8, kind u8
  (0 open / 1 human / 2 AI / 3 closed [guess for 3]), aiLevel u8, tribe i8, color i8, team i8,
  readyState u8, u16, u32, avatarId u32.
- Session fields: gameName, mapGuid (20 B), mapName, maxPlayers i8, settings u8×3 (+0x225..+0x227),
  u8×2, **gameId u32 (+0x22a)**, ranked u8, u32 +0x22f, wager u32, u32.

On receipt, when all players are connected, the client checks that the map exists (kick
`!MAP NOT EXISTING`). [known] 0x3000F = `NE_PreGame_HostReconnectRestartAndSendGameInformation`
(name from the event map at S 00421bd0). [known]
**Server**: nothing. `gameId` here is the value later sent to the referee as GameID. [known]

#### 0x30011 (196625) PlayerReady — peer -> all
**Contract.** (S 00408d80): Event1Integer (sig 0x11111010), header + u32 0/1. Sent only in NComm state 2.
[known] On receipt, the host updates the ready UI and re-broadcasts GameInformation. **Server**: nothing.

#### 0x30012 (196626) StartLoading — host -> peers
**Contract.** the handler sets NComm manager+0x3cc = 1 (S 0040e560). [known] This flag arms the referee login
pump on every client's WorldScreen (see Match start). **Server**: nothing directly. It is the trigger for
the referee chain.

#### 0x30005 (196613) StartGame / 0x30004 (196612) GameLoaded
**Contract.**
- 0x30005: host-only, broadcast in manager state 3. It carries the GameInformation session copy with the
  settings CRC (S 0040ff90). [inferred]
- 0x30004: Event1Integer + u32, sent in states 3/4 (S 00408e50). [inferred]

**Server**: nothing.

#### 0x30010 (196624) Kick
Header + u16 len + text (S 00409ac0). Outside a match, the receiver shuts NComm down. [known] **Server**: nothing.

### Referee / match arbiter (referee connection)

The referee is a separate TinCat **server-id connection** (HandlerGS T 10023460, kind 2), addressed
by 189 -> 170 (id) and then 221 -> 222 (ip:port). The connection is created and dialled at match start
(see below). Its base login is the generic server-id login:
`188 CheckVersion -> Result(42) 0 -> 211 -> 212{nonce} -> 213 SendToken -> 153 AddResult errorcode 0`.
On this connection, a non-zero `153.id` overwrites the ConnectionManager perm_id (T 10027080 note), so
send the player's own perm_id there. [PROVEN for the sequence; inferred for the id overwrite]

After the 153, all traffic is referee LobbyMessages in the SendGameData(74) envelope (see [LobbyMessage bodies](#lobbymessage-bodies-village-and-referee)).

Observer lists on `RefereeServerConnection` and the WorldScreen subscribers (S 004351a0) [known]:

| List | Subscriber |
|---|---|
| +0x04 | ArmRefereeLogin S 00431780 |
| +0x10 | RetryRefereeLogin S 004317a0 |
| +0x50 | RegisterGame OK -> S 00431800 |
| +0x5c | RegisterGame failed -> S 00432fd0 |
| +0x80 | LoginSuccess -> S 00432240 |
| +0x8c | LoginFailed -> S 004317d0 |

#### 0xDCA (3530) LoginSuccess — referee -> C (push)

**Contract.**

| # | Field | Bits | Notes |
|---|---|---|---|
| 1 | PermID | 32 (BE) | must equal LobbyManager+0x54c, the user's own perm_id |

Handler `LoginSuccessReceived` S 0047ac20. On a match it fires list +0x80. On a mismatch, including a
little-endian encoded value, it **returns silently**. [PROVEN]

**Required server behaviour.**
- **Push it unprompted** after the referee connection's `153`. `RefereeServerConnection::Login`
  S 004793f0 only opens the transport and sends no request. [PROVEN] (stub `_h_send_token`,
  2026-07-27 live: RegisterGame followed)
- Use **that connection's** player's perm_id. [PROVEN]
- It is useful only while the WorldScreen is subscribed, that is during match start. Pushed at lobby
  login, it reaches an empty observer list and has no effect. [known, ER 2026-07-27 push-after-153]
- Send it once per referee login. Each LoginSuccess makes every subscribed client send RegisterGame again,
  with no guard (S 00432240). [inferred]

**Open decisions.**
- **H14** Delay after the 153. The client accepts any delay inside the retry window. Default: 0.5 s
  (the stub's value; no requirement is known).
- **H15** Admission policy, LoginSuccess vs LoginFailed. The client accepts either. Default: always
  LoginSuccess.

#### 0xDCB (3531) LoginFailed — referee -> C

**Contract.** PermID, 32 bits, with the same guard as 0xDCA. Handler S 0047ad50 fires +0x8c ->
S 004317d0: tries+1, re-arm, backoff = tries×8+16 pump ticks. [known for the body; inferred that the unit is frames]

**Required server behaviour.** Only send it to refuse. After 5 attempts (WorldScreen +0x362c > 4),
the client **aborts match start** (`NComm_Manager_Shutdown`, S 00435980). [inferred]

**Open decisions.** Covered by H15.

#### 0xDB6 (3510) RegisterGame — C -> referee

**Contract.** (S 00479840; values from S 00432240)

| # | Field | Bits | Value |
|---|---|---|---|
| 1 | GameID | 32 | NComm session +0x22a (same on every client of the match) |
| 2 | MapGUID | 128 raw | map GUID |
| 3 | MapName | u8 len + bytes | session map name |
| 4 | MapSettings | u8 len + 3 ASCII digits | `'0'+gi[0x225..0x227]` |
| 5 | RankedGame | **1** | gi+0x22e |
| 6 | Wager | 32 | gi+0x233 (bit-shifted by 1 from here on) |
| 7 | AIPlayer | 8 | **count** of AI slots (not a mask) |
| 8-13 | AvatarID ×6 | 32 each | slot PlayerInfo+0x47 for i < SlotCount, else 0 |

[known for the encoding; inferred for "same GameID on every client"]

Sent by **every** client whose WorldScreen is active, host and joiners, once per LoginSuccess.
[PROVEN: arrived from both clients 2026-07-27]

**Required server behaviour.**
- Reply `0xDB7 RegisterGameAcknowledge`, then `0xDB8 RegisterGameResult`. [PROVEN]
- Read the fields with a bit reader. GameID at byte offset 0 is safe to read as BE u32. Wager and the
  AvatarIDs are not byte-aligned. [known]
- Stub difference: the stub reads only GameID. Its docstring describes u32-length strings, which does not
  match the bitstream. There is no wire effect today. [known]

**Open decisions.**
- **H16** Validation of the registration: slots, wager, ranked, avatar ownership. The client accepts
  Result 0 to proceed. Any non-zero Result shows `!REGISTER_GAME_FAILED` and logs out of the referee.
  Default: accept.

#### 0xDB7 (3511) RegisterGameAcknowledge — referee -> C

**Contract.** GameID 32, Result 32. Handler S 0047a3d0. Result 0 -> log only. Non-zero -> list +0x5c
(gameId, result, "") -> `!REGISTER_GAME_FAILED` dialog -> referee logout + NComm shutdown (S 00432fd0). [known]

**Required server behaviour.** Send `Result 0` before 0xDB8. [PROVEN] Whether 0xDB7 is required for
progress: no, because only 0xDB8 starts the match. It is the faithful sequence. [inferred]

**Open decisions.** Covered by H16.

#### 0xDB8 (3512) RegisterGameResult — referee -> C

**Contract.**

| # | Field | Bits | Condition |
|---|---|---|---|
| 1 | GameID | 32 | always (not compared by the consumer) |
| 2 | Result | 32 | always; 0 = OK |
| 3a | GameSeed | 32 | **only if Result == 0** |
| 3b | FailReason | u8 len + bytes | **only if Result ≠ 0** |

Handler S 0047a580.
- Result 0 -> list +0x50 -> `WorldScreen::OnRefereeRegisterGameResult` S 00431800. If the setup-game
  dialog is still open, it stores GameSeed into the NComm session (dword 0x22F, applied only in session
  state 2), fills the MP descriptor, clears the referee-login arm flags and starts the match
  (`game vtbl+0x2c(1)`). [known]
- If the dialog is closed, the result is dropped silently. [known]
- Non-zero -> list +0x5c (failure dialog). [known]

**Required server behaviour.**
- Send `Result 0` + GameSeed to **each** client that registered. [PROVEN] (stub, two clients)
- Give every client of one match the **same** seed. It is the lockstep RNG seed, and the session field
  +0x22F is also carried in the GameInformation/StartGame session copy. [inferred]
- Never send both GameSeed and FailReason. [known]

**Open decisions.**
- **H17** GameSeed value. The client accepts any u32 and never validates it. Default: one value per
  match, for example derived from GameID (the stub uses the fixed 0x5EED1234).
- **H18** GameID echoed. Not compared on this message. Default: echo the request's GameID.

#### 0xDC0 (3520) FinishGame — C -> referee

**Contract.** (S 00479c40, sender `DeclareWinner` S 00535990)

| # | Field | Bits |
|---|---|---|
| 1 | GameID | 32 |
| 2 | MapGUID | 128 raw |
| 3 | MapSettings | u8 len + 3 digits |
| 4 | Winner | 32 (AvatarID of one winning slot) |

Sent by every lobby client that evaluates victory. Expect N per match. If the winner index has no
NComm slot, nothing is sent. [inferred, boards #447/#2368]

**Required server behaviour.**
- Reply `0xDC1` and then `0xDC2`. [inferred]
- What the client blocks on after FinishGame was not traced. FinishGameResult fires +0x68 (OK) or +0x74
  (fail), and no subscriber of those lists is identified. [TODO]
- Stub difference: the stub logs it and does not reply. [known]

**Open decisions.**
- **H19** How to reconcile N reports: agreement, first report, majority. The client accepts anything.
  Default: accept every report and record the winner when they agree.

#### 0xDC1 (3521) FinishGameAcknowledge — referee -> C
**Contract.** GameID 32, Result 32. Handler S 0047a810. 0 -> log. Non-zero -> list +0x74
(gameId, result, ""). [known]
**Required server behaviour.** Result 0. **Open decisions.** Covered by H19.

#### 0xDC2 (3522) FinishGameResult — referee -> C
**Contract.** GameID 32, Result 32, then FailReason (u8 len + bytes) **only if Result ≠ 0**. Handler
S 0047a9c0. 0 -> list +0x68 (gameId, 0). Non-zero -> +0x74. [known]
**Required server behaviour.** Result 0. Never send FailReason with Result 0. [known]
**Open decisions.** Covered by H19.

#### 0xDD4 (3540) GiveUpGame — C -> referee

**Contract.** (S 00479ab0; sender `Requester_SendRefereeGiveUpGame` S 00600760, in-match "Back to Lobby")

| # | Field | Bits |
|---|---|---|
| 1 | GameID | 32 (NComm session 0x22A) |
| 2 | MapGUID | 128 raw |

The UI shows `!Finalizing...` until a GiveUp OK or Failed observer fires with the matching GameID. It may be
re-sent every frame until answered (S 006008b0). [inferred, board #680]

**Required server behaviour.**
- Reply `0xDD5` with **GameID equal to the request's**. A mismatched GameID is a silent no-op.
  Both outcomes run the same exit: referee logout, then the main screen. [inferred]
- Tolerate repeats. [inferred]
- Stub difference: the stub logs it and does not reply, so the client stays on "Finalizing". [known]

**Open decisions.**
- **H20** Record the give-up as a loss. This is server-side ranking policy, and the client does not care.
  Default: record it.

Match rewards are server-side only: no message carries amounts, there is no knock-out message, and
the client just shows the character's stored XP, level and gold [known]. The stub's rules (maintainer
decisions 2026-10-07, `sadk_lobby/rewards.py`): XP = (500 + 100 per full minute from the player's
RegisterGame to its own FinishGame / GiveUpGame) x (1 + 1.0 if its FinishGame names it the winner +
0.25 per chest it got), nothing for a match under 2 minutes, gold = XP / 10, credited once per player per match into the character save.
Levels follow the client's thresholds 0 / 1000 / 2500 / 5000 / 10000, capped at level 5 and 25000 XP
(the table at 007d8d90 has no level 6, S 0044f800). A referee chest's first claimant also gets a
random item.

#### 0xDD5 (3541) GiveUpGameAcknowledge — referee -> C
**Contract.** GameID 32, Result 32. Handler S 0047ae80. 0 -> list +0x98 (gameId, 0). 1..20 -> maps
to an ERefereeResult name (S 0046b3d0), logs it, then list +0xa4. **≥21 -> NULL name -> client crash.**
[known]
**Required server behaviour.** Result in **0..20**. Echo the GameID. [known]
**Open decisions.**
- **H21** Result code. The client accepts 0..20, and both ok and fail exit the match the same way.
  Default: 0.

#### 0xDAC (3500) ClaimChest — C -> referee

**Contract.** (S 00479670; caller `Referee_OnChestOpened_SendClaimChest` S 00782a60)

| # | Field | Bits |
|---|---|---|
| 1 | GameID | 32 |
| 2 | MapGUID | 128 raw (no length) |
| 3 | ActorID | 32 |
| 4 | ChestID | 32 |

[known]

**Required server behaviour.**
- Reply `0xDAD` and then `0xDAE`. [inferred]
- `0xDAD` must use Result 0. Its failure branch fires list **+0x5c**, the RegisterGame-failure list. With
  the WorldScreen active, that shows `!REGISTER_GAME_FAILED` and tears down the referee session
  (S 00479fb0, disasm 0047a0ff). [known]
- Stub difference: the stub logs it and does not reply. [known]

**Open decisions.**
- **H22** Grant or deny the chest, and the AvatarID / Text returned. See 0xDAE.

#### 0xDAD (3501) ClaimChestAcknowledge — referee -> C
**Contract.** GameID 32, Result 32. 0 -> log "waiting for others". Non-zero -> list +0x5c. [known]
**Required server behaviour.** Result 0 always (see above). **Open decisions.** None.

#### 0xDAE (3502) ClaimChestResult — referee -> C
**Contract.**

| # | Field | Bits | Notes |
|---|---|---|---|
| 1 | AvatarID | 32 | 0 (the invalid sentinel DAT_007db538) = failure |
| 2 | ChestID | 32 | |
| 3 | Text | u8 len + bytes | always present |

There is no Result field. AvatarID ≠ 0 -> list +0x38 (chestId, avatarId, &text) "ClaimChestOK".
AvatarID 0 -> list +0x44. [known] The push order was verified at disasm 0047a2b0. [known]

**Open decisions.** Under H22, which AvatarID wins the chest. The client accepts any non-zero AvatarID
for success and 0 for failure. Text is free; its display use was not traced. Default: the claimant's
AvatarID, empty text.

### Match start: the full chain (who waits for whom)

| Step | Direction | Message | Gate / evidence |
|---|---|---|---|
| 1 | C->S | 171 ×2 at login | S 00468e80 [PROVEN] |
| 2 | C->S | 189 (4,4) at login | S 00464ee0 one-shot [PROVEN] |
| 3 | S->C | 170 type4/sub4 on the 189 ticket | latches LM+0x580, arms the 60 s retry [PROVEN] |
| 4 | C->S | 168 (host opens a room) | S 0046aaa0 [PROVEN] |
| 5 | S->C | 153 AddResult{id}; 170 push to observers | S 0046a6a0 [PROVEN] |
| 6 | P2P | join via 170 ip:port; 0x30001/0x30002/0x30011/0x30003 | S 0048d030, S 0040e560 [PROVEN behaviour] |
| 7 | C->S | 177 per room change | S 0046aff0 [PROVEN] |
| 8 | P2P | host sends StartLoading 0x30012 -> NComm+0x3cc = 1 | S 0040e560 [known] |
| 9 | C | WorldScreen pump calls `RefereeServerConnection::Login` (up to 5 tries, backoff) | S 00435980 [inferred] |
| 10 | C->S / S->C | 221 {referee id} / 222 {referee ip:port} | T 10023af0 [PROVEN] |
| 11 | C<->Ref | dial; 188 / Result / 211 / 212 / 213 / 153 | [PROVEN] |
| 12 | Ref->C | 0xDCA LoginSuccess {own PermID} | S 0047ac20 [PROVEN] |
| 13 | C->Ref | 0xDB6 RegisterGame (every client) | S 00432240 [PROVEN] |
| 14 | Ref->C | 0xDB7 {GameID, 0}; 0xDB8 {GameID, 0, GameSeed} | S 00431800 starts the match [PROVEN] |
| 15 | C->Ref | in match: 0xDAC / 0xDD4 / 0xDC0 | not answered by the stub [TODO] |

Silent failure points, where a frame is accepted and nothing happens:
- a 4/5 assign reply (step 3);
- a 170 instead of a 222 for the referee address (step 10);
- a wrong-endian or wrong PermID (step 12);
- a type word repeated inside the MEMBLOCK (steps 12-14);
- a 0xDB8 that arrives after the setup dialog closed (step 14).

[PROVEN for the first four, ER 2026-07-27; known for the last]

## Village / world connection

### Connection and envelopes

The village (3D lobby world) is the client's third TinCat connection, owned by
`LobbyComm::VillageServerConnection` (vftable 007db8d4). It dials the ip:port the server returns in
`ConnectionData(222)` for the selected village server id (T 10023cc0 fills conn host/port, T 100309d0
`ConnectionReal::Connect` dials only from those fields) [PROVEN, stub `dispatch._h_connection_data`].
The port is the server's choice; the current stub serves it on `config.WORLD_PORT` = 5477. The login
on this connection is the same token flow as the UC connection (188 CheckVersion -> 211/212 -> 213
SendToken -> 153 AddResult errorcode 0 -> transport state 8) and is covered in the login section.

Every village message after login is a **LobbyMessage** carried inside a NETMSG envelope:
`SendGameData(74)` in both directions, or `SendGameDataBundle(73)` server -> client. `msgdefs.ini`
defines only the two envelopes; the bodies are not in msgdefs and come from the binary [known].
Inbound, `ConnectionReal::HandlePacket` T 100307a0 hands `(msg_type, data)` to the village
connection, `VillageServerConnection::HandleMessage` S 00470a90 wraps them in a stack LobbyMessage
(`InitFromWire` S 0048fa50) and dispatches on the 12-bit message id. Outbound, every sender builds a
LobbyMessage and calls `BaseConnection::SendMessage` S 0048dfa0, which lands in
`ConnectionReal::SendGameData` T 10030560 (NETMSG 74) [known]. The body encoding is in
[LobbyMessage bodies](#lobbymessage-bodies-village-and-referee).

Message-id note: id 0xDC (220) is both the client's category-5 Dice PlaceBets and the server's
NoPlayerSlotLeft. The client dispatches inbound 0xDC to NoPlayerSlotLeft whatever the category [known].

#### 0x04A (74) SendGameData — both

**Contract.**

| order | field | type | notes |
|---|---|---|---|
| 1 | type | u16 LE | 74 |
| 2 | msg_type | u32 LE | LobbyMessage type word (see [LobbyMessage bodies](#lobbymessage-bodies-village-and-referee)) |
| 3 | data | MEMBLOCK: u32 LE length + bytes | LobbyMessage body |

TinCat property-bag rules apply to the envelope (little-endian length and scalars, board #262). On the
wire after the 28-byte TinCat header the app payload is `u16 magic 0x26B6 | u16 74 | u16 type=74 |
u32 msg_type | u32 len | data` (stub `village.gamedata_frame`) [PROVEN]. There is no `ticket_id`
field (msgdefs NETMSG_TYPE_74 has three fields; T 10030560 sets only msg_type and data) [known].
Sender T 10030560; receiver T 100307a0 -> S 00470a90.

**Required server behaviour.**
- Every village message must ride a 73 or 74 envelope on the village connection; a bare LobbyMessage
  frame is not routed to `HandleMessage` [PROVEN].
- Only the village connection has the 1000-series handlers; a 74 sent on the lobby or UC connection
  is not processed as a village message [inferred, stub note].
- After dispatch T 100307a0 still looks up `ticket_id` and completes a ticket; with no such property
  in the set the effect is [TODO]. The stub never sends one and nothing breaks [PROVEN].

**Open decisions.**
- **V1** category bits of outbound type words. Client accepts 0..7 (ignored). Default 2 (mirrors the
  client); 0 is live-proven.
- **V2** names mode. Client accepts 0 or 1; 1 obliges a trailing 32-bit word per message. Default 0.

#### 0x049 (73) SendGameDataBundle — S->C

**Contract.**

| order | field | type | notes |
|---|---|---|---|
| 1 | type | u16 LE | 73 |
| 2 | count | u32 LE | number of entries |
| 3 | data | MEMBLOCK | `count x {msg_type u32 LE, len u32 LE, len bytes}` |

Receiver T 100307a0: walks up to `count` entries and hands each to the village connection as if it
were a separate 74; stops silently when an entry header or body would overrun the blob [known]. No
`ticket_id` on the wire [known]. The client never sends 73.

**Required server behaviour.**
- Nothing requires it; 74 alone is sufficient [PROVEN, the stub uses only 74].
- Entries are processed in order, so ordering rules below hold inside a bundle as well [inferred].

**Open decisions.**
- **V3** use bundles at all. Client accepts any count; an overrunning entry ends the walk silently.
  Default: do not use 73.

### World entry and world clock

#### 0x3E8 (1000) EnterWorld — S->C

**Contract.** (handler `HandleEnterWorld` S 0046f670)

| order | field | bits | notes |
|---|---|---|---|
| 1 | Worldname | string (vtbl+0x30) | stored at +0x228; empty -> `<UNNAMED>` |
| 2 | ServerPerm | 32 | stored at +0x160 |
| 3 | ChatChannelsCount | 32 | N |
| 4.. | N x {ChatChannelZone 32, ChatChannelID 32} | 32 + 32 | zone map key = low byte of ChatChannelZone; ID = chat cell id |

Handler order: `LobbyManager::SetState(9 VillageEntered)` before any field is read; map +0x164 is
cleared and rebuilt (duplicate key keeps the first); then `UserCommConnection::JoinChannel(map[0xFF])`,
`PostOffice::RequestMailHeaders`, srand from the world clock, link quality +0x244 = 3, first
`SendPing` (0xED6, random code), +0x160 = ServerPerm, observers +0x104 (CLobbyClient S 00503940
spawns the local avatar) [known]. All of it [PROVEN] by the live world render (s39) and live chat.

**Required server behaviour.**
- The server pushes 1000 unprompted after the village 153; the client sends nothing to ask for it
  and waits in LobbyManager state EnteringVillage(8) until it arrives [PROVEN].
- Include key 0xFF: without it `operator[]` inserts cell 0 and the client joins cell 0 [known].
- Cell id 0 is the invalid sentinel: chat submit on a tab whose key maps to 0 is dropped silently
  (S 00436860) [PROVEN].
- Every advertised cell must also be published on the UC/chat connection (ChannelInfo) before the
  client joins it; tincat3 rejects a join for an unknown cell with StatusReply status 2 [PROVEN 2026-08-02].
- Answer the JoinChannel (NETMSG 17) on the UC connection and the 0xED6 that follows (see below).
- Tab mapping: GLOBAL tab -> key 0xFF, LOCAL tab -> the avatar's current zone byte (+0x225, re-joined
  per zone change by `SetLocalChatZone` S 0046e860), MINIGAME tab -> key 0xFE [PROVEN 2026-08-01].
- Stub: matches, sends 1000 2.0 s after the village 153 (`config.ENTER_WORLD_DELAY`).

**Open decisions.**
- **V4** Worldname. Any string up to 255 bytes; empty shows `<UNNAMED>`. Default the village name
  (stub: "world1").
- **V5** ServerPerm. Any u32. A chat line whose from_id equals it is shown as `[SYSTEM]` plus the modal
  `!LOBBY_IMPORTANT_SYSTEM_MESSAGE` (S 00436180, board #1445) [inferred]. Default: a perm id no
  player or speaker uses (stub sends 0; safe while every speaker id is non-zero).
- **V6** chat cell ids per key. Any non-zero u32 per key; keys 0x00-0x0F zones, 0xFE minigame,
  0xFF global. Default the stub's set: 0xFF -> 1, 0xFE -> 2, zone z -> 16+z.
- **V7** delay after the 153. Client accepts any time after the village transport reaches state 8
  [inferred]. Default a short settle (stub 2.0 s).

#### 0x3ED (1005) WorldTick — S->C

**Contract.** (`HandleWorldTick` S 0046f620)

| order | field | bits | notes |
|---|---|---|---|
| 1 | tick | 64 (vtbl+0x20) | high dword must be 0 (reader aliasing); only the low 16 bits are used |

Notifies observers +0x11c -> `CLobbyClient_OnWorldTick` S 00503590 -> S 0057b910(tick & 0xFFFF, 250):
if the client world clock differs in phase from the tick by 250 ms or more (shorter way round mod
65536), the clock offset is slewed so its low 16 bits equal the tick [PROVEN 2026-08-01, trace].

**Required server behaviour.**
- Send 1005 before the first 1001 location waypoint to each client, from the same millisecond clock
  that stamps the 1001 ticks. Waypoint stamps are fixed at parse time and are not re-anchored by a
  later slew; without 1005 the phase is arbitrary per machine (up to +-32.7 s) and remote avatars
  vanish [PROVEN 2026-08-01].
- Stub: matches (`dispatch._spawn_world_avatars`, 1 Hz ticker).

**Open decisions.**
- **V8** tick cadence. Client accepts any rate; after the first slew, sends within 250 ms of its clock
  are no-ops. Default: once before the first waypoint, then periodically (stub 1 Hz).

### Keepalive

#### 0xED6 (3798) PingCode — C->S, wire type 0x2ED6

**Contract.** (`SendPing` S 0046c150)

| order | field | bits | notes |
|---|---|---|---|
| 1 | PingCode | 32 | `rand()<<16 \| rand()` |

Sent first at the end of `HandleEnterWorld`, then by `PingPongTimerTick` S 0046c360. After a send the
countdown +0x254 = 30 s; on send failure 15 s and no pending ping [known].

**Required server behaviour.**
- Reply with 0xED7 carrying the same 32-bit value [PROVEN, stub echoes the 4 bytes].
- Without a reply the client re-pings every 30 s and sets link quality to 0; nothing in this path
  disconnects [known]. Quality only feeds the world-screen indicator via `GetConnectionQuality`
  S 0046c130 [inferred].

**Open decisions.**
- None (the reply value is dictated).

#### 0xED7 (3799) PongCode — S->C

**Contract.** (`HandlePongCode` S 0046c250)

| order | field | bits | notes |
|---|---|---|---|
| 1 | PongCode | 32 | compared with the pending ping (+0x248) |

On match: countdown +0x254 += 90 s (next ping ~120 s after the previous send), half-RTT graded into
+0x244 (<=0.1 s -> 3, <=0.25 s -> 2, <=2.0 s -> 1, else 0), pending cleared. A non-matching code is
consumed and ignored [known].

**Required server behaviour.**
- Echo the last PingCode promptly. A late or unsolicited pong is harmless [known].
- Stub: matches.

**Open decisions.**
- None.

### Avatars

#### 0x3E9 (1001) AvatarData — S->C

**Contract.** (`HandleAvatarData` S 0046e1d0, body `AvatarProxy::ReadDataBlocks` S 00482c20)

| order | field | bits | notes |
|---|---|---|---|
| 1 | id | 32 | avatar id = the player's perm id; key in the avatar map *(this+0x170) |
| 2 | dtblcks | 4 | mask: bit0 Location, bit1 Style, bit2 ActiveItems, bit3 Stats; blocks follow in bit order |
| 3 | Location block (bit0) | 50 | see table below (S 004824b0) |
| 4 | Style block (bit1) | string + 72 | see table below (S 004825f0) |
| 5 | ActiveItems block (bit2) | 4 x 48 | 4 x item slot record (S 0048abe0); no count prefix |
| 6 | Stats block (bit3) | 4 x 32 | lvl, exp, gold, glod (S 00481da0) |

Location block (also the body of 2000 minus nothing; see 2000):

| field | bits | value |
|---|---|---|
| tick | 16 | low 16 bits of a ms clock; expanded to the nearest wrap of the client clock (S 004f4d10) |
| posx, posy, posz | 11 each | `round((v-min)/(max-min)*2048)`; bounds x -150..150, y -10..30, z -150..150 (0087b700..0087b714) |
| rot | 7 | `round(deg/360*128)` |
| zone | 4 | sub-zone (minigame rooms, hall of fame are separate zones) |
| ghstzne | 4 | ghost zone |
| rnng | 1 | running |
| jmp | 1 | jumping |

Style block: `name` string (vtbl+0x34, raw UTF-8; ANSI copy is the avatar label), `trbgndr` 8
(high nibble body part, clamped < 3; low nibble gender), then 8 x 8-bit colours hrclr, sknclr,
shrtclr, trsrclr, addColor1..4 (stored unmasked at +0x49..+0x50) [known]. Item slot record:
`sltt` 8, `cnt` 8, `itmid` 32 (S 0048ab40) [known]. Stats: wire order lvl, exp, gold, glod [known].

Behaviour: unknown id -> new AvatarProxy inserted; known id -> update in place. For the client's own
id the location fields are consumed and discarded (only tick is stored) [known]. A failed block logs
`Could not read <block> from message.` and aborts; the proxy stays in the map with no notification.
Delivery is queued (+0x1ac) and fires observers +0xbc (`CLobbyClient_UpdateAvatar` S 00503620) only in
state 9 [known]. The first 1001 for an id creates the 3D avatar; each later 1001 pushes a waypoint
(stamp = expanded tick + 2000 ms) into an 8-slot movement ring that is the only source of the remote
avatar's position [PROVEN 2026-08-01, TTD traces].

**Required server behaviour.**
- Send one 1001 per other in-world player to each entrant, and that entrant's 1001 to everyone else
  [PROVEN].
- Keep streaming 1001 location refreshes: with an empty ring the avatar is hidden one frame after the
  spawn. Waypoints older than 3.0 s are hidden; stamps in the future underflow and hide instantly;
  stamp the relay with the server clock about 1 s in the past, not the sender's tick [PROVEN 2026-08-01].
- Never place a waypoint at about (0,0,0): the ring push rejects it [PROVEN, stub note].
- Send 1005 first (see 1005).
- Never send a short body: a truncated 1001 crashed the client about 1.1 s later [PROVEN 2026-07-31].
- The own-avatar branch in S 004824b0 shows the original server also sent each client a 1001 for its
  own id [inferred]. Whether the own avatar is in the +0x170 map without one (needed for 3100-3201
  `ownr` lookups) is [TODO].
- Stub differs: names this message EntityCreate; sends location + style blocks only; never sends a
  1001 for the recipient's own id.

**Open decisions.**
- **V9** which blocks to send (dtblcks 0..15). Client accepts any mask; mask 0 is valid (no blocks).
  Default location+style on spawn, location only on refresh.
- **V10** avatar appearance (trbgndr, 8 colours). Any byte values; body part >= 3 is clamped by the
  model math. Default: the character's stored appearance.
- **V11** refresh cadence. Any; the ring holds 8 waypoints and the stale cut-off is 3.0 s. Default
  relay each 2000 report plus a 1 Hz keepalive refresh (stub).
- **V12** Stats values. Any u32; exp should lie between the XP thresholds at 007d8d90 for lvl and lvl+1
  or the XP bar wraps (board #1175) [inferred]. Default the character's stored values.

#### 0x3EA (1002) AvatarLoggedIn — S->C

**Contract.** (`HandleAvatarLoggedIn` S 0046e390)

| order | field | bits | notes |
|---|---|---|---|
| 1 | id | 32 | new avatar id |

Id already in the map -> log `Avatar already logged in.`, no change. Otherwise an empty AvatarProxy is
inserted and queued (+0x184) for observers +0xa4 (CLobbyClient: no-op S 00472360) [known]. No blocks:
appearance and location come later via 1001.

**Required server behaviour.**
- Not required: 1001 alone creates avatars [PROVEN]. If used, send it before the first 1001 for that
  id, otherwise it only logs an error [known].
- Stub differs: `config.VILLAGE_MSG_ENTITY_UPDATE = 1002 # (movement)` is wrong; movement is a
  repeated 1001. No wire effect (the stub never sends 1002).

**Open decisions.**
- **V13** announce arrivals with 1002. Client accepts it or its absence. Default: do not send.

#### 0x3EB (1003) AvatarRemove — S->C

**Contract.** (`HandleAvatarRemove` S 0046e570)

| order | field | bits | notes |
|---|---|---|---|
| 1 | id | 32 | avatar to remove |

Unknown id -> log `Can't find Avatar`. Known -> queued (+0x198) for observers +0xb0
(`CLobbyClient::OnAvatarRemoved` S 00503170) which removes the 3D object in state 9. The AvatarProxy
stays in the map until world exit; a later 1001 for the same id reuses it [known].

**Required server behaviour.**
- Send to every remaining in-world client when a player's village connection goes away, or they keep
  a frozen avatar [inferred]. Stub matches (`dispatch.on_conn_closed`); live effect not separately
  recorded.

**Open decisions.**
- None.

#### 0x7D0 (2000) AvatarLocation — C->S, wire type 0x27D0

**Contract.** (`SendAvatarLocation` S 0046ca40)

| order | field | bits | notes |
|---|---|---|---|
| 1 | tick | 16 | client tick \| 1 (never 0) |
| 2-6 | posx, posy, posz, rot, zone | 11, 11, 11, 7, 4 | `WriteLocationBlock` S 0048f7e0; out-of-range values wrap mod 2048 |
| 7 | ghstzne | 4 | S 0048f980 |
| 8 | rnng | 1 | |
| 9 | jmp | 1 | latched on Space until a frame is sent |

Sent every 4th frame of the local controller (S 0051ace0), no time throttle: about 15/s at 60 fps
(board #1160) [known]. No reply handler exists [known].

**Required server behaviour.**
- Nothing is expected back. To make other players see the movement, relay it to them as 1001
  location refreshes [PROVEN 2026-08-01].
- Stub matches (`dispatch._h_avatar_location`). Comment drift: the stub says "~3/s".

**Open decisions.**
- **V14** server-side movement validation (speed, bounds, zone). Client accepts any relay. Default:
  relay verbatim, re-stamped with the server clock.

#### 0xF6E (3950) AvatarColorChange — C->S, wire type 0x2F6E

**Contract.** (`SendAvatarColorChange` S 0046c760)

| order | field | bits | notes |
|---|---|---|---|
| 1 | Changes | 8 | bit i set when colour slot i changes: 0 hair, 1 skin, 2 shirt, 3 trouser, 4-7 addColor1..4 |
| 2.. | Color | 4 each | one per set bit, ascending i |

The tailor dialog (S 0045e020) sends Changes = 0xF8 and applies the colours locally first [inferred].
The tailor action (slot code 17) checks avatar gold +0xd0 >= 50 client-side (S 00434230) [inferred].

**Required server behaviour.**
- No reply handler exists [known]. Others see the change only through a 1001 with the style block
  [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V15** tailor price and whether to charge. Client checks gold >= 50 only. Default: charge 50 gold
  and send 3201 plus a style 1001 to everyone.

#### 0xC80 (3200) LevelExpUpdate — S->C

**Contract.** (`HandleAvatarLevelExpUpdate` S 0046c940)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ownr | 32 | avatar id |
| 2 | lvl | 32 | -> +0xcc |
| 3 | exp | 32 | -> +0xc8 |

Unknown ownr -> rest discarded silently. No observer notification [known].

**Required server behaviour.**
- Not required for progress. Send to the owner's client after XP changes if the UI should update
  [inferred].
- Stub differs: not implemented.

**Open decisions.**
- **V16** level/XP rules. Client accepts any u32 pair (see V12 for the XP-bar constraint).

#### 0xC81 (3201) StatsUpdate — S->C

**Contract.** (`HandleAvatarStatsUpdate` S 0046c9c0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ownr | 32 | avatar id |
| 2-5 | lvl, exp, gold, glod | 32 each | -> +0xcc, +0xc8, +0xd0, +0xd4 |

Unknown ownr -> discarded silently; no observer notification [known]. Any avatar's values are kept:
the info view of a selected avatar shows its gold ("credits") and glod ("play money")
(SelectionInfoDialog::RefreshInventoryPanel S 0044f9f0), so other players need the 1001 stats block
and later 3201s too. `glod` is play money ("funnies"): the minigame dialog reads +0xd4 as play money and +0xd0 as credits (S 004447f0) [known]. Default 1000 for a variant-0 stats block (board #7).

**Required server behaviour.**
- Send after any gold change (shop, tailor, minigames) so client-side gold checks stay correct
- Stub rule (maintainer decision, not client-derived): a character gets 500 funnies on its first
  world entry of each calendar day; nothing else earns funnies. Server notices (welcome, allowance,
  rewards, mail) are channel lines in the player's local zone cell, the tab selected by default.
  The client always formats them as `[<name>] <!LOBBY_CHAT_FROM> : <text>` (S 00433480), so the
  "sagt" label is client-side and can't be removed.
- Stub rule: every character gets one introduction mail (funnies, XP/gold, `!fasttrack`, hosting on
  TCP 5479) on its first world entry, from creator id `FROM_SERVER`; a LookUpName (72 by `char_id`)
  of that id is answered with a row named "Server" so the inbox shows a sender.
  [inferred].
- Stub differs: not implemented.

**Open decisions.**
- **V17** economy values (gold, glod). Any u32. Default the stored character values; new characters
  start with gold = glod = 50 (creation path S 00481e60, board #213).

### NPCs

#### 0x3EC (1004) NPCData — S->C

**Contract.** (`HandleNPCData` S 0046f8c0, body `NPCProxy::ReadFromMessage` S 0047b5c0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | id | 32 | NPC id; key in the NPC map *(this+0x174) (= LM+0x564) |
| 2 | npcdesc | string (vtbl+0x34) | raw UTF-8, label |
| 3-7 | posx, posy, posz, rot, zone | 11, 11, 11, 7, 4 | `ReadLocationBlock` S 0048f670; no tick, ghost zone or flags |
| 8-11 | hrclr, sknclr, shrtclr, trsrclr | 4 each | -> +0x49..+0x4c |
| 12 | npcidx | 4 | model selector (+0xc0) |
| 13 | bdyprt | 4 | -> +0x48; not used for NPC models |
| 14 | npctyp | 2 | 1 settler person, 2 letterbox, other = no visual |
| 15 | actcnt | 8 | number of action slots |
| 16.. | actcnt x {act 8, actChat string (vtbl+0x30)} | | act = LobbyAction id = world action-slot code |

Get-or-create; observers +0x38 fire immediately (not queued) [known]. The selected NPC's slots are
copied verbatim into the world screen's action codes by `NPCProxy::GetActionSlots` S 0047b200 and
executed by `DispatchSlotAction` S 00434230: 2..6 minigame matchmaking (search, kind act-2), 7 mailbox,
8 host game, 9 game list toggle, 10 hall of fame, 11 OpenShop (sends 0xE10), 12/13 create table,
14/15 join table, 16 NPC text, 17 tailor, 18 clear setup-game flag [inferred]. NPC slot parameters
are always 0 [known]. NPC records render with per-npcidx models and labels [PROVEN 2026-08-02].

**Required server behaviour.**
- actcnt <= 3: actChat for i >= 3 is written past the 0x120-byte object (heap corruption, S 0047b5c0
  disasm, board #2381) [known].
- Send after 1000 to each entrant; they are static, no refresh stream needed [PROVEN].
- Stub: matches (`village.player_create_body`); NPCs are disabled by the maintainer's flag
  `config.VILLAGE_NPCS_ENABLED = False`. Comment drift: the stub calls this "PlayerCreate"/"player
  record".

**Open decisions.**
- **V18** the NPC cast (ids, positions, npcidx, colours, labels). Any values; npcidx 0..15, npctyp 1/2
  to be visible. Default: the stub's `npcs.make_village_npcs` set. npcidx -> model mapping lives in the
  encrypted game data [TODO].
- **V19** NPC actions. act 0..255 per slot, at most 3 slots; only the codes listed above do anything.
  Default: shop NPCs act 11, mailbox 7, tailor 17, minigame hosts 2..6.
- **V20** NPC ids. Any u32; must not collide with avatar ids used in 1001 or in minigame seats
  (acttype 2 = NPC) [inferred]. Default a reserved high range.

### Inventory

#### 0xBB9 (3001) MoveItem — C->S, wire type 0x2BB9

**Contract.** (`SendMoveItem` S 0046bec0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | srcslt | 8 | source container: 0 backpack, 2..5 equipment [inferred] |
| 2 | srcidx | 8 | index in the source container |
| 3 | dstslt | 8 | destination container |
| 4 | dstidx | 8 | destination index; 0xFF = server picks [inferred] |
| 5 | mvcnt | 8 | count (1 from the UI) |

No local state change: the client waits for the server's item update [known].

**Required server behaviour.**
- Answer with 3102 (or 3100 / 3101) for the owner so the UI reflects the move [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V21** move validation (slot compatibility, stacking). Client accepts whatever the following update
  says. Default: apply legal moves, re-send the current state for illegal ones.

#### 0xBBA (3002) DeleteItemRequest — C->S, wire type 0x2BBA

**Contract.** (`SendDeleteItemRequest` S 0046bff0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | slt | 8 | container |
| 2 | idx | 8 | index |

Sent after an item is dropped on the 3D world and the `!LOBBY_DELETE_ITEM` box is confirmed (S 004320b0)
[inferred]. The client does not remove the item locally [known].

**Required server behaviour.**
- Answer with an inventory update (3101 or 3102) without the item [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V22** whether deletion is allowed for every item. Any. Default allow.

#### 0xC1C (3100) ActiveItemsUpdate — S->C

**Contract.** (`HandleAvatarActiveItemsUpdate` S 0046e660)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ownr | 32 | avatar id |
| 2 | ActiveItems block | 4 x {sltt 8, cnt 8, itmid 32} | exactly 4 records (S 0048abe0) |

Unknown ownr -> discarded silently. Queued (+0x1c0) for observers +0xc8 (CLobbyClient S 005036d0) in
state 9 [known].

**Required server behaviour.**
- Send after equipment changes [inferred]. Requires ownr in the avatar map (see 1001 [TODO]).
- Stub differs: not implemented.

**Open decisions.**
- **V23** item ids and slot types. Game-data ids from the encrypted item tables [TODO]; client accepts
  any u32. Default empty slots (all zero).

#### 0xC1D (3101) InventoryUpdate — S->C

**Contract.** (`HandleAvatarInventoryUpdate` S 0046e6f0, block S 0048ac20)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ownr | 32 | avatar id |
| 2 | sltcnt | 8 | read and discarded |
| 3 | N x {sltt 8, cnt 8, itmid 32} | 48 each | N = the client's own slot count (+0x34), not sltcnt |

Unknown ownr -> discarded silently. Queued (+0x1d4) for observers +0xd4 (no CLobbyClient subscriber;
listener [TODO]) [known].

**Required server behaviour.**
- Send exactly the client's slot count of records: fewer and the reader runs past the end, more are
  ignored (board #1033) [known]. The count is 0 after init and max(20, n) after the character data
  blocks (S 0048af70) [known]; the server must know which applies [inferred].
- Stub differs: not implemented.

**Open decisions.**
- **V24** sltcnt value. Ignored by the client; default the true slot count.

#### 0xC1E (3102) ItemsFullSync — S->C

**Contract.** (`HandleAvatarItemsFullSync` S 0046e780)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ownr | 32 | avatar id |
| 2 | ActiveItems block | 4 x 48 | as 3100 |
| 3 | inventory block | 8 + N x 48 | as 3101 |

Queued (+0x1e8) for observers +0xe0 (CLobbyClient S 005036d0) [known].

**Required server behaviour.**
- Preferred answer to 3001/3002 and to shop buy/sell, since it refreshes both containers [inferred].
- Stub differs: not implemented.

**Open decisions.**
- None beyond V23/V24.

### Shops

#### 0xE10 (3600) OpenShop — C->S, wire type 0x2E10

**Contract.** (`SendOpenShop` S 0046ddf0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | NPCID | 32 | the selected NPC's id |

Only caller: `DispatchSlotAction` S 00434230, slot code 11 (an NPC with act 11) [known]. If a shop
is still open it is cleared first (S 0046dba0) [known].

**Required server behaviour.**
- Reply with 0xE11 whose NPCID equals the request's NPCID [inferred, board #4784].
- Stub differs: `dispatch._h_send_game_data` has no branch for 0x2E10 and `village.py` describes 0xE11
  as server-pushed. A live shop-NPC click put nothing on the wire (2026-08-02); the cause sits before
  the send and is [TODO] (act 11 is copied verbatim to slot code 11 by S 0047b200, so the mapping
  itself is not the cause [inferred]).

**Open decisions.**
- **V25** NPC id -> shop mapping. Any. Default one shop per shop NPC.

#### 0xE11 (3601) ShopInventoryData — S->C

**Contract.** (`HandleShopInventoryData` S 004706b0, stock record S 0046b360)

| order | field | bits | notes |
|---|---|---|---|
| 1 | NPCID | 32 | -> +0x258 |
| 2 | ShopID | 32 | -> +0x25c; used by 0xE1A/0xE24 |
| 3 | ShopName | string (vtbl+0x30) | observer argument only |
| 4 | SellMod | 32 raw-32 (little-endian float) | -> +0x260 |
| 5 | StockCount | 16 | N |
| 6.. | N x {ItemID 32, Buy 32, Sell 32} | 96 each | -> vector +0x264 |

No validation. Always replaces the open-shop state and fires observers +0x128 (NotifyAll5), which
opens the shop dialog [known]. The shop counts as open only when NPCID and ShopID are both non-zero
(S 0046c610) [known]. Arrival opens the dialog even unrequested [PROVEN 2026-08-02].

**Required server behaviour.**
- Send only as the reply to 0xE10; an unrequested 0xE11 pops the dialog open [PROVEN].
- NPCID and ShopID non-zero [known].
- Stub: body layout matches (`village.shop_inventory_body`); not wired to 0x2E10 (see 0xE10).

**Open decisions.**
- **V26** stock (ItemID, Buy, Sell). Item ids are game-data ids [TODO]; prices any u32. Default: a
  curated list per shop.
- **V27** SellMod. Any float; default 0.9 (the client's built-in default at 007db9d0 per prior
  analysis) [inferred], stub uses 1.0.
- **V28** ShopID values. Any non-zero u32. Default a stable id per shop.

#### 0xE1A (3610) ShopBuy — C->S, wire type 0x2E1A

**Contract.** (`SendShopBuyItem` S 0046c400)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ShopID | 32 | open shop (+0x25c), may be 0 (no check) |
| 2 | Slot | 16 | stock index |
| 3 | QTY | 16 | 1 from the UI |
| 4 | Backpack | 16 | target backpack index, 0xFFFF = any free slot |

**Required server behaviour.**
- Reply with 0xE1B [inferred], and update items (3102) and gold (3201) on success [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V29** purchase rules (gold check, full backpack). Client accepts any Result. Default: fail when gold
  or space is short.

#### 0xE1B (3611) ShopBuyResult — S->C

**Contract.** (`HandleShopBuyResult` S 00470990)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ShopID | 32 | |
| 2 | Result | 1 (bool) | true = success [inferred] |

No connection state change; observers +0x134 get (ShopID, Result) [known].

**Required server behaviour.**
- One per 0xE1A [inferred]. Stub differs: not implemented.

**Open decisions.**
- None beyond V29.

#### 0xE24 (3620) ShopSell — C->S, wire type 0x2E24

**Contract.** (`SendShopSellItem` S 0046c510)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ShopID | 32 | open shop |
| 2 | Backpack | 16 | backpack index of the item |
| 3 | QTY | 16 | 1 from both call sites |

Note the order differs from 0xE1A (Backpack before QTY) [known].

**Required server behaviour.**
- Reply with 0xE25, plus 3102 and 3201 on success [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V30** sell price. Client shows Sell and SellMod but does not dictate the credited amount. Default
  `Sell * SellMod`.

#### 0xE25 (3621) ShopSellResult — S->C

**Contract.** (`HandleShopSellResult` S 00470a10)

| order | field | bits | notes |
|---|---|---|---|
| 1 | ShopID | 32 | |
| 2 | Result | 1 (bool) | true = success [inferred] |

Observers +0x140 get (ShopID, Result) [known].

**Required server behaviour.**
- One per 0xE24 [inferred]. Stub differs: not implemented.

**Open decisions.**
- None.

### Trades

The client cannot start or answer a trade: no outbound trade message exists in this build (all
outbound village ids are 2000-2002, 3001, 3002, 3600, 3610, 3620, 3798, 3950, 4000 and the category-5
minigame ids; board #4786) [known]. The two inbound trade messages are vestigial.

#### 0xF46 (3910) TradeRequest — S->C

**Contract.** (`HandleTradeRequest` S 0046d920)

| order | field | bits | notes |
|---|---|---|---|
| 1 | msgprt | 16 | -> +0x27c |
| 2 | rnid | 8 | -> +0x27e |
| 3 | tradeID | 32 | -> +0x278 |
| 4 | playerA | 32 | read and discarded |
| 5 | playerAName | string (vtbl+0x34) | read and discarded |

Accepted only when no trade is active (+0x275) or pending (+0x274); then latches +0x274 = 1. No
observer call [known].

**Required server behaviour.**
- None. Sending it latches a pending flag the client can never clear by itself [inferred].
- Stub: not implemented (correct).

**Open decisions.**
- **V31** send trade messages at all. Default: never.

#### 0xF5A (3930) TradeOffer — S->C

**Contract.** (`HandleTradeOffer` S 0046cd10)

| order | field | bits | notes |
|---|---|---|---|
| 1 | msgprt | 16 | must equal +0x27c |
| 2 | rnid | 8 | must equal +0x27e |
| 3 | tradeID | 32 | must equal +0x278 |
| 4-9 | playerA, playerB, goldA, goldB, funniesA, funniesB | 32 each | |
| 10 | itemsA | sltcnt 8 (ignored) + 6 x {sltt 8, cnt 8, itmid 32} | S 0046c6f0 |
| 11 | itemsB | same | |

Read only while a trade is active and the key matches; otherwise discarded. Parsed values are not
stored or shown [inferred].

**Required server behaviour.**
- None. Stub: not implemented (correct).

**Open decisions.**
- Covered by V31.

### Chat command

#### 0xFA0 (4000) ChatCommand — C->S, wire type 0x2FA0

**Contract.** (`SendChatCommand` S 0046cbf0)

| order | field | bits | notes |
|---|---|---|---|
| 1 | cmd | string | the text after `/ac ` typed in world chat (S 00436860) |

No reply handler exists on the village connection [known].

**Required server behaviour.**
- Nothing required. Any answer would go through chat (UC) [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V32** command set and responses. Client accepts anything. Default: ignore, or reply with a system
  chat line from the ServerPerm id (V5).

### Minigames

Minigame tables (1 Dice, 2 Poker, 3 PawnChess) live in the map +0x178 keyed by `msgprt | rnid << 16`.
Server -> client table messages are category-agnostic; client actions use category 5.

#### Shared sub-records

MiniGameKey (`MiniGameKey::Read` S 00471160), first in 0xD8/0xD9/0xDA:

| order | field | bits | notes |
|---|---|---|---|
| 1 | mngt | 8 | low nibble game type 1/2/3; bit4 table settings present; bit5 currency, 1 play money (`glod`) / 0 credits (`gold`) (S 004712b0); bit6 seat block present; bit7 game state present (S 004712c0, S 00471220, S 00471230) [known] |
| 2 | scntbl | 8 | low nibble -> key+8 = 3D group = scene id of the tavern (2 taverne03, 3 taverne02); high nibble -> key+0xc = table spot `slot:NN_c` in it (0-12 four seats, 13-14 eight). The client's tavernId is low nibble - 2 (S 00471620) [known] |
| 3 | chtid | packed uint | chat cell of the table (observer channel, joined via UC 17/259 by S 00523850) |
| 4 | msgprt | 16 | table key low |
| 5 | rnid | 8 | table key high |

Table settings (mngt bit4; `MiniGameProxy::ReadTableSettings` S 00471490): `psswd` 8 (non-zero =
protected), `psswdcrc` 32, `gmnm` string, `lmtmn` packed, `lmtmx` packed, `mxplyr` 4 [inferred].

Seat block (mngt bit6; `MiniGameProxy::ReadSeats` S 00471f00): `plyrcnt` 4, then per entry `used` 1;
if 1: `sltidx` 4, `acttype` 2 (1 avatar, 2 NPC), `id` packed uint (S 00490e40). Seats not listed are
cleared (removal by omission) [known].

Game state (mngt bit7), per type [inferred]:
- Dice (S 00488e00): `dice` 8 (two nibbles), `dlr` 8, `plyrcnt` 8, `phase` 8, `time` 16 (hundredths of a second elapsed in
  phase), per player {`sltidx` 8, `crdts` packed, `accnt` packed, `bt00..bt10` 11 x packed}. Bets of the
  local seat are ignored while phase == 1 [known].
  - Phases [known] (UpdatePhaseDisplay S 004471d0, CMiniGameControllerDice_Actor::Update S 00524c10,
    CMiniGameControllerDice_Board::Update S 00523c10): 1 betting, with a 15 s countdown computed from
    `time`; 2 roll, where the `dlr` seat shakes the cup and its click sends Roll 221 (IsLocalSeatActive
    S 00488a00 compares `dlr` with the local seat); 3 throw, dice shown after 500 ms and every seat's
    payout computed client-side on entry (ComputeAllPayouts S 00488d60); 4 result, "X credits/funnies
    won/lost" and the board's round-result animation. The client has no timer for phases 2-4.
  - `dlr` must always be a real seat 0..3: the cup is drawn at that seat's node, unchecked [known].
  - `crdts` is the seat's whole stack, bets included: the HUD shows `crdts - sum(bets)` and a chip is
    accepted only while `sum(bets) + chip <= crdts` (UpdateBetting S 00523db0) [known].
  - Payout (ComputeSeatPayout S 00488870): sums form group A {2,4,6,9,11} and group B {3,5,8,10,12}; a
    roll in a group returns every bet of that group 1x and the bet on the exact sum 5x; a 7 returns 3x
    the bet on 7 only [known].
  - Dice has four seat anchors (MiniGameDiceProxy ctor S 00488b50: {0,2,3,1}); seats 0..3 only. The
    dialog offers Dice 1-4 players; Poker up to 8, and 5-8 only at spots 13-14 (S 00444a20) [known].
- Poker (MiniGamePokerProxy::ReadTableState S 004894a0) [known], in order: `dlr` 8, `plyrcnt` 8,
  `crntplyr` 8, `actns` 16, `phase` 8, `round` 8, `egr` 8, `shwcrds` 8, `time` 16, `minwgr` 32, `lstply` 8,
  `lstvl` packed, `mnrs` packed, `lstactn` 16, board `crd0..crd2` (round > 1), `crd3` (round > 2), `crd4`
  (round > 3), `wgrmsk` 8 + one packed `wgr` per set bit (seat ascending; the street's bet pile), per player
  {`sltidx` 8, `trsfcrds` 1, [`crd0` 8, `crd1` 8, `hndval` 32 if trsfcrds], `actn` 16, `crdts` packed
  (stack, without the street bet), `accnt` packed}, `ptncnt` 8 (bit7 = per-pot wagers, bits0-6 count), per
  pot {`pot` 32, `plrmsk` 8, [`wgrplrmsk` 8 + packed `wgr` per set bit if bit7]}. See "Poker game" below.
- PawnChess (MiniGamePawnChessProxy::ReadTableState S 0048a6d0) [known]: `phs` 8, `trnid` 8, `pwchkmt`
  8, `plrstt` 8, `pwnps` 16 x 8 (col | row << 3 | king << 6 | side << 7), `plyrcnt` 8, per player
  {`sltidx` 8, `crdts` packed, `accnt` packed}. See "PawnChess game" below.

Hard client limits on any table message [known]:
- mngt low nibble outside 1..3 in 0xDA crashes the client (NULL proxy dereference, board #153).
- Seat block: plyrcnt <= 8 (larger overflows stack arrays); send only `used` = 1 entries (`used` = 0
  indexes seats out of bounds); sltidx 0..7; every avatar occupant must already exist with a 3D object,
  or the whole block is rejected (board #189).
- Poker pot count <= 8 (larger overwrites the state counter).
- 0xDA must not carry a seat block with occupants. ReadSeats announces the seats (S 00471eb0) and the
  seat-joined observer (S 00503710) calls into the table's 3D object at proxy+0x20, which only the first
  0xD9 creates (+0x68 fires before the 0xD9 state is read). An occupied seat block in 0xDA is a NULL
  read at S 00503717 (crash dump 2026-10-07). Send key + settings in 0xDA, seats and state in 0xD9.
- 2001 carries the creator's buy-in: the client sends 2001 or JoinTable from the stake dialog, never
  both (S 00442f00), so the server seats the creator itself.
- Tables are only announced by 0xDA/0xD9; a client entering the world later knows none until the server
  sends them.

#### Matchmaking dialog and tavern ids

`MiniGameMatchMakingDialog::Open` (S 00444cb0) takes a tavernId, a table spot, a mode (0 browse,
1 create at a spot, 2 join a table) and a table map key. `WorldScreen::DispatchSlotAction`
(S 00434230) opens it from three sources [known]:

| action code | source | tavernId | mode |
|---|---|---|---|
| 2..6 | NPC button | code - 2 | 0, spot 0xFF |
| 12, 13 | click on an empty table spot in scene 2 / 3 | code - 12 | 1, spot = clicked spot |
| 14, 15 | click on an occupied table spot in scene 2 / 3 | code - 14 | 2, key of that table |

`RefreshActionSlots` (S 00433f60) builds codes 12-15 as scene id + 10 / + 12, after
`FindMiniGameProxyByScntbl` (S 0046d240) looks up a table at (scene, spot). The dialog's per-frame
`Update` (S 00445cf0) lists every MiniGameProxy in the world map with `scntbl low nibble - 2 ==
tavernId`, then filters by game type (mode 0/1) or by map key (mode 2). Join is only possible from a
selected row: `OnSetStackResult` (S 00442f00) sends 2001 in create mode, otherwise `SendJoinTable`
for the selected table.

So an NPC that opens matchmaking for a tavern must carry action code = that tavern's scene id (2 or
3), and a table must carry the tavern's scene id in its scntbl low nibble. A mismatch leaves the
dialog list empty, and nobody can join through it [known].

#### Poker game

The client's side of a hand [known] (MinigameDialog_Poker::Update S 0044b3c0, UpdateCards S 00525300,
CMiniGameControllerPoker_Board::Update S 00525550, IsLocalPlayersTurn S 00489b80):

| phase | client |
|---|---|
| 1 | waiting; with round 1 it also hides the last hand's hole cards |
| 5 | deal animation by `round`: 1 hole cards to the occupied seats, 2 flop, 3 turn, 4 river; at round 4, `egr` 1 / 2 runs an all-in board out from the flop / the turn |
| 6 | betting; the only phase that draws the current-player marker |
| 8 | the street's bets fly into the pots: needs ptncnt bit7 with each pot's per-seat wagers, and pot amounts that already include them |
| 9 | payout: for each pot, last to first, the client picks the highest `hndval` among the `plrmsk` seats and splits evenly (integer division); `shwcrds` = seat to reveal, 0xFE = won without showdown |

- `time` is in hundredths of a second since the phase began; Poker applies it on every message, so it
  is the elapsed turn time. The client counts a 15 s turn down; it never acts on a timeout itself.
- The local turn = `crntplyr` == local seat, actn bits 11 and 12 clear, and the state counter moved
  since the last send. The counter moves only when `crntplyr`, `phase` or `round` changes: a rejected
  action answered with the same state leaves the player without buttons.
- Buttons: at most THREE of `actns` bits RAISE 8, BET 0x20, FOLD 4, CALL 2, CHECK 0x10, ALLIN 0x100,
  filled in that order with no bounds check; a fourth crashes the client. SMALLBLIND 0x40 / BIGBLIND 0x80
  are never buttons: the server posts blinds.
- 300 carries CALL/FOLD/CHECK/ALLIN; 301 carries BET/RAISE with `wgr` = the total to bet to on this
  street, between `minwgr` (BET) or `minwgr + mnrs` (RAISE) and stack + street bet; 0xFFFFFFFF when
  the amount box was hidden. CALL's label is `minwgr - own street bet`, so `minwgr` is the highest bet.
- Per-player `actn`: bits 0-10 the last action code; 11 blocks the turn (all-in); 12 sitting out (marker,
  blocks the turn); 13 and 15 show "wait for next round" instead of the hand value.
- `lstply` / `lstactn` / `lstvl`: a speech bubble over that seat, fired when `lstply` or `lstactn` changes.
- Cards: 0..51, rank = c % 13 ('2'..'A'), suit = c / 13 (d h s c); 0x34 = back, 0xFF = none. With
  `trsfcrds` 0 the other seats show backs and the local seat keeps its 303 cards.
- `hndval` = category << 24 | n0 << 16 | n1 << 12 | n2 << 8 | n3 << 4 | n4 (FormatHandValue S 004484f0),
  ranks 0..12: 0 high card (five ranks), 1 pair (pair, 3 kickers), 2 two pair (high, low, kicker), 3 trips
  (trips, 2 kickers), 4 straight (top rank; the wheel tops at 3), 5 flush (five ranks), 6 full house
  (trips, pair), 7 quads (quads, kicker), 8 straight flush (top rank). Category > 8 indexes past the
  name table. Preflop only categories 0 (n0, n1) and 1 (n0) are shown.
- Limits: `sltidx` < 8; `dlr`, `lstply` and `shwcrds` a seat or 0xFF (`shwcrds` also 0xFE); `crntplyr` a
  seat or 0xFF; at most 8 pots. Poker seats are 0-7; the 3D table is pokertable4 at spots 0-12,
  pokertable8 at 13-14.
- SitOut 302 `enbl`: 1 = sit out, 0 = back (the dialog toggle starts at 0) [inferred].

Server decisions (`sadk_lobby/minigames.py`, `poker.py`): big blind = the table's minimum stake, small
blind half; heads-up the button posts the small blind and acts first preflop; the turn times out after
15 s (check if free, else fold); a sitting-out player in a hand is checked/folded after 1 s; a player
who leaves mid-hand folds; odd chips of a split pot go to the first winner after the button.

#### PawnChess game

Rules (maintainer's description, matched to the client's move generator ComputeTargets S 00525d20):
8x8 board, square = col + row * 8. Each side has 7 pawns and 1 king, filling its home column (side 0
column 0, side 1 column 7), so the layout is rotated, not mirrored. At the start each player picks which
square of its home column holds the king. Pawns walk along the columns (side 0 towards column 7, side 1
towards column 0): one square forward onto an empty square, or diagonally forward (row +-1) onto an enemy
piece. The king steps to any neighbour not holding an own piece; attacked squares stay allowed (the client
only tints them). Taking an enemy pawn converts it: the captor places it on an empty square of the column
it was taken in, else of the nearest column towards the captor's home. A game is won by moving onto the
enemy king, by a pawn reaching the enemy home column, or by checkmate.

The client's side [known] (CMiniGameControllerPawnChess_Actor::Update S 00526260, HandleKingPlacementInput
S 005260f0, RefreshMovablePieces S 00525c00, MinigameDialog_PawnChess S 0044caf0 / S 0044cd10):

| phs | client |
|---|---|
| 1 | waiting |
| 2 / 3 | seat 0 / seat 1 places its king: the 8 squares of its home column are offered; 402 sends the row |
| 4 / 5 | seat 0 / seat 1 moves: 400 for a move (also onto the enemy king), 401 to take a pawn (`trgt` = its square, `cppwn` = it, `cptrgt` = where it goes) |
| 6 | game over: "win"/"lose" by the local seat's `plrstt` winner bit; the bets slide to the winner |

- All 16 pieces are always on the board; the client rebuilds a square -> piece table from `pwnps`, so
  the squares must be distinct.
- `trnid`: every 400-402 locks the board until a state with a different `trnid` arrives; phases 1 and 6
  reset the lock to 0xFF. The server answers every action, accepted or not, with a new `trnid`, never
  0xFF.
- `plrstt`: one nibble per seat (seat 0 low, seat 1 high): bit 0 in check, bit 2 winner. In check the
  client lets that side move only the king and the pawn marked by `pwchkmt` (piece index, 0x10 = its
  capture square is row - 1, else row + 1; 0xFF = none), whose only target is that capture.
- NewGame 403 (`plridx` = own seat): the proxy starts with its new-game request already pending (ctor
  S 00489f92 sets +0x2b5 = 1), so the button stays hidden until the first phase 6 clears it (S 0048a774).
  The first game therefore starts without a 403 once both seats are filled; 403 is the rematch request
  after a game over. Each side's bet is drawn as the table minimum (`lmtmn`).
- Seats 0 and 1 are the players (IsPrimarySeat S 004715f0).

Server decisions (`sadk_lobby/pawnchess.py`, `minigames.py`): two seats, no spectators; the stake is the
table minimum from each player, taken at the start, all of it to the winner; the game ends on the position
before the king is taken; a side with no legal move loses; leaving a running game forfeits it; only one
pawn can be marked against a single checker.

#### 0x7D1 (2001) CreateMiniGameTable — C->S, wire type 0x27D1

**Contract.** (`SendCreateMiniGameTable` S 0046cf20)

| order | field | bits | notes |
|---|---|---|---|
| 1 | type | 8 | game type |
| 2 | plyMny | 8 | play-for-money flag |
| 3 | stck | 32 | stake |
| 4 | gmnm | string | table name |
| 5 | lmtmn | 32 | min limit (from a client-side list) |
| 6 | lmtmx | 32 | max limit (always 0x7FFFFFFF, board #1067) |
| 7 | mxplyr | 8 | max players |
| 8 | tvrn | 8 | the dialog's tavernId = scntbl low nibble - 2 [known] |
| 9 | tblidx | 8 | table spot clicked to create (scntbl high nibble); 0xFF when the dialog was opened from an NPC [known] |
| 10 | psswd | 8 | 0 none, 1 set |
| 11 | psswdcrc | 32 | CRC32 of the password, 0 without |

The password itself never travels [inferred].

**Required server behaviour.**
- Success: 0xDA (create) then 0xD9 (first update shows the 3D table) for everyone in the zone
  [inferred]. Failure: 0xDB [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V33** table capacity per tavern and when to refuse (0xDB). Any. Default: one table per tavern slot.
- **V34** msgprt/rnid allocation for new tables. Any u16/u8 pair, unique per world. Default sequential.

#### 0x0DA (218) MiniGameTableCreate — S->C

**Contract.** (`HandleMiniGameTableCreate` S 0046eb70): MiniGameKey, then the type-specific state read
by the new proxy (vtbl slot 3) under the mngt flags.

Not state-gated. Always creates a new proxy and overwrites any existing one with the same key without
freeing it (leak). No observer fires and no UI change [inferred].

**Required server behaviour.**
- mngt low nibble 1..3 (else crash) [known].
- Follow with 0xD9 for the table to appear [inferred].
- Stub differs: not implemented.

**Open decisions.**
- Covered by V34.

#### 0x0D9 (217) MiniGameTableUpdate — S->C

**Contract.** (`HandleMiniGameTableUpdate` S 0046f380): MiniGameKey, then type-specific state.

Read only in state 9. chtid must be non-zero and the key must name a table created by 0xDA, else
silent drop. The first 0xD9 after 0xDA stores chtid and fires +0x68 (CLobbyClient creates the 3D
table); a successful state read fires +0x80 (table updated) [inferred].

**Required server behaviour.**
- Non-zero chtid, existing table, client in state 9 [inferred].
- Every client action (join, leave, amount, bets, moves) is answered through this message; the
  PawnChess board stays locked until an update changes `trnid` (board #713) [inferred].
- Seat-block limits above.
- Stub differs: not implemented.

**Open decisions.**
- **V35** chtid per table. Any non-zero value; it is a chat cell the client joins via UC, so it must
  also be published on the chat connection [inferred]. Default a dedicated cell per table.
- **V36** game rules, timers and payouts per type. The client renders whatever state it receives (Dice
  computes payouts itself). Default: implement each game's rules server-side.

#### 0x0D8 (216) MiniGameTableRemove — S->C

**Contract.** (`HandleMiniGameTableRemove` S 0046f510): MiniGameKey only (trailing data ignored).

Read only in state 9. Found -> all seats cleared, observers +0x74 remove the 3D table, proxy deleted
[inferred].

**Required server behaviour.**
- Send when a table closes [inferred]. Stub differs: not implemented.

**Open decisions.**
- **V37** when tables close (last player leaves, timeout). Any. Default when empty.

#### 0x0DB (219) MiniGameNoTableLeft — S->C

**Contract.** (`HandleMiniGameNoTableLeft` S 0046f4d0): empty body.

Fires +0x8c -> error dialog `!MINIGAME_NOTABLELEFT` (S 00433280) while the game screen is subscribed
[inferred].

**Required server behaviour.**
- Failure answer to 2001 [inferred]. Stub differs: not implemented.

**Open decisions.**
- None.

#### 0x0DC (220) MiniGameNoPlayerSlotLeft — S->C

**Contract.** (`HandleMiniGameNoPlayerSlotLeft` S 0046f4f0): empty body.

Fires +0x98 -> error dialog `!MINIGAME_NOPLAYERSLOTLEFT` (S 00433380) [inferred].

**Required server behaviour.**
- Failure answer to 209 JoinTable [inferred]. Stub differs: not implemented.

**Open decisions.**
- None.

#### 0x0D1 (209) JoinTable — C->S, category 5, wire type 0x50D1

**Contract.** (`MiniGameProxy::SendJoinTable` S 00471720)

| order | field | bits | notes |
|---|---|---|---|
| 1 | msgprt | 16 | table key |
| 2 | rnid | 8 | table key |
| 3 | stck | 32 | stake / buy-in |
| 4 | psswdcrc | 32 | CRC of the typed password |

The client refuses a protected join locally when the typed CRC differs from the table's `psswdcrc`, with
no traffic (board #1067) [inferred].

**Required server behaviour.**
- Success: 0xD9 whose seat block lists the joiner. Failure: 0xDC [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- **V38** buy-in rules (stake vs limits and gold). Any. Default: enforce lmtmn..lmtmx and available gold.

#### 0x0CC (204) LeaveTable — C->S, category 5, wire type 0x50CC

**Contract.** (`MiniGameProxy::SendLeaveTable` S 00471800): `msgprt` 16, `rnid` 8.

**Required server behaviour.**
- Send a 0xD9 whose seat block omits the leaver (removal by omission) [inferred].
- Stub differs: logged and dropped.

**Open decisions.**
- None.

#### 0x0DE (222) Amount — C->S, category 5, wire type 0x50DE

**Contract.** (`MiniGameProxy::SendAmount` S 00471660): `msgprt` 16, `rnid` 8, `amnt` 32 (not
range-checked).

Sent from the amount dialog of all three games; what the server books it as (top-up or bet) is not
visible client-side [inferred].

**Required server behaviour.**
- Reflect the result in the next 0xD9 (`crdts` / `accnt`) [inferred]. Stub differs: dropped.

**Open decisions.**
- **V39** meaning of Amount (chip top-up from gold). Default: move `amnt` gold into table credits.

#### 0x0DC (220) Dice PlaceBets — C->S, category 5, wire type 0x50DC

**Contract.** (`MiniGameDiceProxy::SendPlaceBets` S 00488be0): `msgprt` 16, `rnid` 8, `crdts` packed,
`bt00..bt10` 11 x packed (bet on dice sum k+2) [inferred].

**Required server behaviour.**
- Accept during the betting phase and echo in the next 0xD9 [inferred]. Stub differs: dropped.

**Open decisions.**
- Covered by V36.

#### 0x0DD (221) Dice Roll — C->S, category 5, wire type 0x50DD

**Contract.** (`MiniGameDiceProxy::SendRollDice` S 004887a0): `msgprt` 16, `rnid` 8.

**Required server behaviour.**
- Answer with a 0xD9 carrying `dice` and the result phase [inferred]. Stub differs: dropped.

**Open decisions.**
- Covered by V36 (dice RNG is server-side).

#### 0x12C (300) Poker Action — C->S, category 5, wire type 0x512C

**Contract.** (`MiniGamePokerProxy::SendAction` S 00489110): `msgprt` 16, `rnid` 8, `actn` 16.

Marks the current state as answered; the local turn ends until a state change [inferred].

**Required server behaviour.**
- Answer with 0xD9 that advances `crntplyr`/`phase`/`round` [inferred]. Stub differs: dropped.

**Open decisions.**
- Covered by V36.

#### 0x12D (301) Poker ActionWithWager — C->S, category 5, wire type 0x512D

**Contract.** (`MiniGamePokerProxy::SendActionWithWager` S 004891d0): `msgprt` 16, `rnid` 8, `actn` 16,
`wgr` packed.

**Required server behaviour.**
- As 300 [inferred]. Stub differs: dropped.

**Open decisions.**
- Covered by V36.

#### 0x12E (302) Poker SitOut — C->S, category 5, wire type 0x512E

**Contract.** (`MiniGamePokerProxy::SendSitOut` S 00489340): `msgprt` 16, `rnid` 8, `enbl` 8
(polarity [guess]: 1 = sit out).

**Required server behaviour.**
- Reflect in the player's `actn` flags (bit12 sittingOut) in the next 0xD9 [inferred]. Stub: dropped.

**Open decisions.**
- Covered by V36.

#### 0x12F (303) MiniGameHand — S->C

**Contract.** (`HandleMiniGameHand` S 0046d380 -> `MiniGamePokerProxy::ReadHand` S 00489410)

| order | field | bits | notes |
|---|---|---|---|
| 1 | msgprt | 16 | table key |
| 2 | rnid | 8 | table key |
| 3 | crd0 | 8 | card 0..51, 0x34 = hidden |
| 4 | crd1 | 8 | |
| 5 | hndval | 32 | evaluated hand value |

Unknown table or unseated client -> silent drop [inferred].

**Required server behaviour.**
- Send each seated player's own hole cards privately (only to that client) [inferred]. Stub differs:
  not implemented.

**Open decisions.**
- hndval encoding: see "Poker game" (the client compares it to pick winners) [known].

#### 0x190-0x193 (400-403) PawnChess actions — C->S, category 5, wire types 0x5190-0x5193

**Contract.** (all after `msgprt` 16, `rnid` 8; board #713 / #1032) [inferred]

| id | builder | fields |
|---|---|---|
| 0x190 (400) Move | S 0048a100 | `pwn` 8 (piece 0..15), `trgt` 8 (row*8+col) |
| 0x191 (401) Capture | S 00489fd0 | `pwn` 8, `trgt` 8, `cppwn` 8, `cptrgt` 8 |
| 0x192 (402) PlaceKing | S 0048a360 | `posy` 8 (row 0..7) |
| 0x193 (403) NewGame | S 0048a2a0 | `plridx` 8 (0/1, 0xFF spectator) |

400-402 latch the turn id (+0x2a9 = +0x2a8); input stays locked until a state update changes `trnid`.

**Required server behaviour.**
- Answer every 400-402 with a 0xD9 whose `trnid` differs from the latched one, or the board stays
  locked silently [inferred]. 403 is cleared by a phase-6 update. Stub differs: dropped.

**Open decisions.**
- Covered by V36.

### Leave

#### 0x7D2 (2002) LeaveVillageRequest — C->S, wire type 0x27D2

**Contract.** (`SendLeaveVillageRequest` S 0046bde0, vtbl slot +0x40)

| order | field | bits | notes |
|---|---|---|---|
| 1 | code | 32 | constant 0xAFFEDEAD |

Sent only when the transport is in state 8. LobbyManager state := LeavingVillage(10) before the send;
the transport is not logged out here [known]. Triggered by the leave-village confirm box via
`CLobbyClient::LeaveVillage` S 00503470 and at match start by every client [PROVEN 2026-07-26]. Sent
exactly once, no retry [PROVEN, trace].

**Required server behaviour.**
- State 10 has two exits: `HandleLoggedOut` S 00470e20 -> VillageLeft(11) (the clean exit that arms
  the referee at match start) and `HandleDisconnected` (shows `!CONNECTION_LOST_TEXT`) [PROVEN].
- Closing the socket is not an acceptable answer: it ends in the connection-lost dialog and, at match
  start, kicks both players [PROVEN 2026-07-26].
- The working answer is two 1006 {0xDEADBEEF}: one immediately (UC still open -> UC logout), a second
  once the client's UC socket has closed (-> village transport logout -> VillageLeft) [PROVEN: this is
  the leave step of the live match-entry chain, 2026-07-27]. That the original server answered this
  way is [inferred].
- Stub: matches (`dispatch._h_send_game_data`, `dispatch.on_conn_closed`). Comment drift: the
  `village.py` module docstring and `send_enter_world` / `_h_send_game_data` docstrings still call
  0x27D2 a dormant world-login request answered with 1000; the code answers with 1006.

**Open decisions.**
- **V41** trigger for the second 1006. Client accepts it at any time after the UC transport has left
  state 8. Default: the UC socket close (stub).

#### 0x3EE (1006) WorldLoginAck — S->C

**Contract.** (`HandleWorldLoginAck` S 0046ec50)

| order | field | bits | notes |
|---|---|---|---|
| 1 | code | 32 | acts only on 0xDEADBEEF |

On 0xDEADBEEF: +0x224 = 1, then if the UC connection is open (UC vtbl+0x2c) -> subscribe UC +0x1c and
`UserCommConnection::Logout` S 0047ed70 (acts only when the UC transport is in state 8); else ->
village transport Logout (`ConnectionReal::Logout` T 10030510, state 9) -> on disconnect T 10030ad0
takes the state-9 branch -> `OnLoggedOut` -> VillageLeft(11) [PROVEN 2026-07-26]. Any other code is
ignored silently [known]. Despite its name this is the logout trigger, not a render gate: the world
renders at state 9 without it [PROVEN].

**Required server behaviour.**
- Send only as the answer to 2002 (see above). A 1006 sent while in-world with the UC transport in
  state 8 logs the player out; the stub once did this on the first PingCode and threw players back to
  character select [PROVEN 2026-07-26].
- Big-endian `de ad be ef` on the wire [PROVEN].
- Stub: matches.

**Open decisions.**
- None (value and timing are dictated).

## tincat3 managers

MotD, properties, mail, buddies, ignore list, ranking, users and accounts, characters, groups,
guilds, CD keys, machines, server info and statistics, backup/admin, cyclic admin messages and the
broker, plus the generic Result / AddResult replies every lobby request depends on. Ticket routing
and the receive-handler case lists are in [Tickets and request completion](#tickets-and-request-completion).

### Result, AddResult and Simple

#### 0x02A (42) Result — S->C

**Contract.** Lobby connection, handler T 10023cc0 (also HandlerGS/UserComm/StatSurf).

| # | Field | Type | Read |
|---|---|---|---|
| 1 | errorcode | UNBYTE | vtbl+0x5c [known] |
| 2 | errormsg | STRING 32 | not read by any lobby-side handler [known] |
| 3 | ticket_id | UNLONG | read first [known] |

Result(42) routing on the lobby connection (request type -> effect; all release the ticket) [known]:

| Request type | Completes |
|---|---|
| 0x35 RequestUsers | UserManager::OnRequestUsersResult |
| 0x37 RequestUserCharList | UserManager::OnRequestUserCharListResult |
| 0x38 RequestUserBuddyList | UserManager::OnRequestUserBuddyListResult T 1002de50 |
| 0x39 RequestUserGroupList | UserManager::OnRequestUserGroupListResult |
| 0x40 / 0x42 / 0x43 | GroupManager list / user list / access results |
| 0x48 RequestCharacters | CharacterManager::OnRequestCharactersResult |
| 0x4e / 0x50 | GuildManager list / char list results |
| 0x58 ChangeUser, 0x5a ChangeCharacter | clear busy + notify (errorcode, ticket data) |
| 0x59 / 0x5b / 0x5d / 0x5f | group / guild change and remove results |
| 0x5e RemoveCharacter | CharacterManager::OnRemoveCharacterResult |
| 0x60 / 0x61 | Add/RemoveUserKey results |
| 0x62 / 0x63 | OnAdd/OnRemoveUserBuddyResult T 1002e0b0 / T 1002e1d0 |
| 0x64 / 0x65 / 0x66 / 0x67 / 0x68 / 0x98 | group-user, guild-char, group-access results |
| 0x75 RegObserverUptime, 0xb4 RequestServerInfo | ServerInfoManager::OnResult T 1002a020 |
| 0x77 / 0x8c / 0x8d / 0x8e / 0x8f | CDKeyManager results |
| 0x79 / 0x7c / 0xa7 | MachineManager results |
| 0x87 / 0x89 | BackupManager (errorcode not forwarded) |
| 0x8a KickPermIDServer | GameServerManager listener 0x38 |
| 0x93 / 0x94 / 0x97 | MailManager list / mark-read / remove results |
| 0x9a / 0x9b / 0x9d / 0x9e | ignore add/remove/list, key list results |
| 0xa1 / 0xa3 / 0xa4 / 0x10a / 0x10b | PropertyManager::OnResult T 10029630 |
| 0xa6 / 0xa9 / 0xab / 0xac / 0xb1 / 0x108 | GameServerManager (hosting section) |
| 0xad GetStatisticsConnection | ReportEmptyStatisticsConnection (errorcode) |
| 0xb3 ChangeMOTD | MotD manager listener 0x04 |
| 0xbc / 0xcb..0xce / 0xd6 / 0xc1 / 0x109 | login and token paths (login section) |

Request types **without** a Result case (Result ignored, ticket kept): 0x69 RequestMOTD, 0x96
AddPrivateMessage, 0xaf / 0xb0 buddy observers, 0x54..0x57 Add*, 0xa8 AddGameServer [known].

**Required server behaviour.** Every request in the table above needs exactly one Result(42) with
its own ticket_id, after any data rows. errorcode 0 = success.

**Open decisions.**
- **T3** `errormsg`: never read on the lobby path; any string or None. Default None [known].
- **T4** Non-zero errorcode values: passed to observers as a CommLayer error; each SADK consumer
  only distinguishes 0 / non-zero unless noted per message [inferred]. Default 1 for failures.

#### 0x099 (153) AddResult — S->C

**Contract.** Handler T 10023cc0 case 0x99 (also the login paths of HandlerGS/StatSurf).

| # | Field | Type | Read |
|---|---|---|---|
| 1 | errorcode | UNBYTE | vtbl+0x5c [known] |
| 2 | errormsg | STRING 32 | not read [known] |
| 3 | id | UNLONG | vtbl+0x9c; passed only for 0x56 AddCharacter and 0x96 AddPrivateMessage [known] |
| 4 | ticket_id | UNLONG | |

Routing (table T 1002677c): 0x54 AddUser, 0x55 AddGroup, 0x57 AddGuild -> clear busy + notify;
0x56 AddCharacter -> CharacterManager T 100160e0 (id, errorcode); 0x96 AddPrivateMessage -> MailManager
T 10028fc0 (id, errorcode); 0xa8 AddGameServer; 0xaf / 0xb0 buddy observer reg/dereg. Any other
request type: ignored, ticket kept [known].

**Required server behaviour.** Use 153 (not 42) to complete 84, 85, 86, 87, 150, 168, 175, 176.

**Open decisions.** `id` is per message (see 86 and 150).

#### 0x001 (1) Simple — not handled

**Contract.** {type, data UNLONG}. No sender in T, no case in any lobby-side handler: a received
Simple is logged as an invalid type and dropped [known: T 10023cc0 default].

**Required server behaviour.** None. **Open decisions.** Do not send it.

### MotD

Lobby connection. Client side: tincat3 MotDManager (vftable T 1004fbb8, at CommLayer+0x40) and the
SADK ServerMessages action (S 004884d0 / S 00488550). The MotD is one of the four conditions for
leaving login state 6 (LobbyManager::StatePump_Tick S 00464ee0: MotD done, character list valid,
buddy list valid, ignore list valid) [known, board #995].

#### 0x069 (105) RequestMOTD — C->S

**Contract.** Sender MotDManager::RequestMOTD T 10029250 (no busy flag in tincat3; ServerMessages
is busy until the reply).

| # | Field | Type |
|---|---|---|
| 1 | ticket_id | UNLONG (request type 0x69) |

**Required server behaviour.** Reply with **106 MOTD** on the same ticket. A Result(42) on this
ticket is ignored (no 0x69 Result case) and does not complete it; without 106, ServerMessages stays
busy and login never leaves state 6 [known, board #4791]. Stub sends 106 only [PROVEN: 31 live
logins completed].

**Open decisions.** None beyond 106's text.

#### 0x06A (106) MOTD — S->C

**Contract.** Handler T 10023cc0 case 0x6a -> MotDManager listener T 100292c0 -> observer vtbl+8
(txt, error=0) -> ServerMessages::IMotDObserver_OnMotDReceived S 00488550; ticket released.

| # | Field | Type | Notes |
|---|---|---|---|
| 1 | txt | STRING 256 | UTF-8; converted to ANSI by S 00488550 [inferred] |
| 2 | ticket_id | UNLONG | released; the handler does **not** check the request type [known] |

**Required server behaviour.** Send once per 105, after it. The error path ('!MOTD_ERROR') is
unreachable from the wire because error is always 0 here [known].

**Open decisions.**
- **T5** MotD text: any UTF-8 string up to 255 bytes plus NUL; longer is truncated by the receiver
  [known]. Default: a short welcome line.
- **T6** Unsolicited 106 (ticket 0): accepted and shown, since the ticket is not checked [inferred].
  Default: do not push.

#### 0x0B3 (179) ChangeMOTD — C->S

**Contract.** Admin. Sender MotDManager::ChangeMOTD T 100291c0: {txt STRING 256, ticket_id (0xb3)}.
No SADK caller identified [inferred].

**Required server behaviour.** Result(42) on the ticket -> MotD listener slot 0x04 [known].

**Open decisions.** **T7** Whether to honour admin MotD changes: client imposes nothing. Default:
reject with errorcode 1 unless the account is an admin.

### Properties

Lobby connection. tincat3 PropertyManager (CommLayer+0x20); SADK LobbyComm::Properties
(S 0048e880 / S 0048e920), one request in flight. The **only** SADK caller is the login version
check: StatePump_Tick S 00464f31 -> RequestProperty S 0048ecb0 (kategory 1, index 1) -> callback
LobbyManager::OnVersionChecked_State4to5 S 00464e70 [known: single xref to S 0048ecb0].

#### 0x0A1 (161) PropertyGet — C->S

**Contract.** Senders: PropertyGet T 10029320 (request type 0xa1), RequestAllProperties T 10029860
(kategory 0, index 0, type 0x10a), RequestCategoryProperties T 10029900 (index 0, type 0x10b). No
busy flag in tincat3.

| # | Field | Type |
|---|---|---|
| 1 | kategory | SILONG |
| 2 | index | SILONG |
| 3 | ticket_id | UNLONG |

Live: the client sends (1, 1) during login, state 3->4 [PROVEN].

**Required server behaviour.**
- Type 0xa1: send **162 PropertyData** with the same ticket, then **Result(42)** on that ticket.
  PropertyData only stores the value (T 10029560); the observer callback fires on the Result
  (T 10029630 case 0xa1 -> observer vtbl+4(1, &single, errorcode)) [known; disasm of T 10029630
  shows each case returns, no fall-through]. Stub does 162 + Result [PROVEN].
- Bulk 0x10a / 0x10b: N × 162 with the ticket, then Result(42); the list is delivered on the Result
  [known]. No SADK caller sends bulk requests [inferred].
- SADK checks (S 0048e920): errorcode != 0 -> request failed; entry count != 1 -> -1; kategory
  mismatch -> -2; index mismatch -> -3. Any failure in the version check disconnects with error 0x6f
  (111) [known].
- A Result without a preceding 162 delivers the zeroed triple (0,0,0) -> kategory mismatch -> failure
  [inferred].

**Open decisions.**
- **T8** Value of property (1,1) = server protocol version. Accepted: any int32 **≤ the client's
  ProtocolVersion** (`g_ClientProtocolVersion` S 0087aed8, live 1000), signed compare; any value if
  ProtocolVersion is 0; a larger value disconnects with error 0x3e (62) [known: S 00464e70].
  Default 1000 (stub sends 0, which also passes [PROVEN]).
- **T9** Values for other (kategory, index) pairs: the client never asks [inferred]. Default 0 with
  errorcode 0.

#### 0x0A2 (162) PropertyData — S->C

**Contract.** Handler T 10023cc0 case 0xa2 -> PropertyManager::OnPropertyData T 10029560 (reads the
fields itself; no ticket release).

| # | Field | Type |
|---|---|---|
| 1 | kategory | SILONG |
| 2 | index | SILONG |
| 3 | value | SILONG |
| 4 | ticket_id | UNLONG — must be the request's ticket; other types are dropped |

**Required server behaviour.** Echo kategory and index of the request exactly [known: S 0048e920
compares both]. Follow with Result(42).

**Open decisions.** Value: see T8 / T9.

#### 0x0A3 (163) PropertySetAbsolute / 0x0A4 (164) PropertySetRelative — C->S

**Contract.** Senders T 100293e0 / T 100294a0: {kategory SILONG, index SILONG, value SILONG,
ticket_id (0xa3/0xa4)}. 164's value is a delta (msgdefs name) [inferred]. No SADK sender
identified [inferred].

**Required server behaviour.** Result(42) on the ticket -> observer vtbl+8(errorcode) = SADK
SetPropertyResultReceived S 0048eaf0, which only logs [known].

**Open decisions.** **T10** Whether to persist property writes: client imposes nothing. Default:
persist per account, errorcode 0.

### Mail (private messages)

Lobby connection (sent on the ConnectionManager's current connection, connMgr vtbl+0x48)
[inferred]. tincat3 MailManager (vftable T 1004fb7c, CommLayer+0x3c) holds a cache of 149 records;
SADK PostOffice (S 0047d880 Process) queues one operation at a time and re-requests headers every
60 s after the last successful list [known]. Live: 147 every ~60 s per logged-in client [PROVEN].

MailManager -> PostOffice observer slots (IMailObserver vftable S 007dc93c): 1 headers
(S 0047dce0), 2 mail body (S 0047e0f0), 3 mark-read result (S 0047c290), 4 delete result
(S 0047e590), 5 send result (S 0047c5e0) [known].

#### 0x093 (147) RequestPrivateMessageList — C->S

**Contract.** Sender MailManager::RequestMessageList T 100290e0 (busy +0x24). On send success the
client clears its 149 cache [known].

| # | Field | Type | Value |
|---|---|---|---|
| 1 | delivery_target | UNLONG | local perm id (LobbyManager+0x54c) [PROVEN: live 1 / 2 per account] |
| 2 | selection | UNLONG | always 0 [PROVEN] |
| 3 | ticket_id | UNLONG | request type 0x93 |

**Required server behaviour.**
- Send one **149 PrivateMessage** per mail (any ticket value; see 149), then **Result(42)** on the
  147 ticket. The Result delivers the cached records to PostOffice as headers (T 10028d80 ->
  S 0047dce0) and clears busy; it also restarts the 60-s poll [known].
- A Result alone is a valid empty mailbox [PROVEN: stub default-ack, 371 live requests, cadence
  holds].
- **Send full records with `message_text`.** Opening a mail (PostOffice op 2) is answered locally
  from the 149 cache (MailManager::GetMessage T 10028a30). If the id is not cached the callback gets
  0x92 and PostOffice then marks itself busy with nothing in flight: the whole mailbox queue
  (polls, mark-read, delete, send) stalls until logout [known code path, board #2376].
- No Result: busy +0x24 stays set, no further list requests, PostOffice queue stalls [known].

**Open decisions.**
- **T11** Mailbox storage and retention: client imposes nothing. Default: persist per perm id.
- **T12** Order of 149 records: kept in arrival order; headers are merged by id into PostOffice
  [inferred]. Default: newest first.
- **T13** How many mails per list: no client limit is known; each record allocates heap [inferred].
  Default: cap at 100.

#### 0x095 (149) PrivateMessage — S->C

**Contract.** Handler T 10023cc0 case 0x95 -> MailManager::OnPrivateMessage T 10028e80 (deep copy
appended to the cache). **No ticket check and no ticket release** [known].

| # | Field | Type | Client use |
|---|---|---|---|
| 1 | delivery_target | UNLONG | rec+4 [known] |
| 2 | message_id | UNLONG | rec+0; mail identity [known] |
| 3 | creator | UNLONG | rec+8; sender perm id, name resolved via CharacterManager [known] |
| 4 | creation_time | UNLONG | rec+0xc [known]; unit not traced [TODO] |
| 5 | title | STRING 128 | rec+0x10 [known] |
| 6 | status | UNBYTE | read with GetLBOOL: nonzero = read, 0 = unread [known] |
| 7 | message_text | MEMBLOCK | read twice: NUL-terminated heap copy (rec+0x18) and ptr/len (rec+0x1c/+0x20) [known: push operands 10024e8a / 10024edc] |
| 8 | data | MEMBLOCK | **never read** [known] |
| 9 | ticket_id | UNLONG | not used |

**Required server behaviour.** Send between the 147 and its Result(42). A 149 outside a list
request is still appended to the cache but reaches PostOffice only on the next list Result, and the
next 147 clears the cache first [inferred].

**Open decisions.**
- **T14** `message_id`: any nonzero u32, unique per mailbox; 0 is rejected by every PostOffice
  operation (S 0047d200 / S 0047d390 / S 0047dfc0) [known]. Default: per-server counter from 1.
- **T15** `creation_time`: any u32 [inferred]. Default: Unix seconds.
- **T16** `data`: anything; never read. Default: empty (length 0).
- **T17** `message_text` encoding: the client sends its own text as bytes incl. NUL (150) and copies
  up to the first NUL on receive [known]. Default: echo the sender's bytes unchanged.
- **T18** Mails from ignored senders: the client auto-deletes mails whose creator is on its ignore
  list (CollectNewMails S 0047e930) [inferred]. Default: deliver anyway; filtering is client-side.

#### 0x094 (148) ChangePrivateMessage — C->S

**Contract.** Sender MailManager::MarkMessageRead T 10028b00 (busy +0x2c). PostOffice queues it
after opening a mail and sets its read flag optimistically (S 0047d390, S 0047e0f0) [known].

| # | Field | Type | Value |
|---|---|---|---|
| 1 | message_id | UNLONG | mail id |
| 2 | status | UNBYTE | always 1 (read) [known] |
| 3 | ticket_id | UNLONG | request type 0x94 |

**Required server behaviour.** Result(42) on the ticket -> T 10028f60 -> observer slot 3 with
**(id 0, errorcode)**: PostOffice logs "unknown MailID 0x0" even on success and keeps its
optimistic flag [known, board #4790]. The server-side read state only reaches the client through
the `status` of later 149s. No Result: busy +0x2c stays set and the PostOffice queue stalls.

**Open decisions.** **T19** Persist read state: client relies on it only via later 149 `status`.
Default: persist, report status 1.

#### 0x097 (151) RemovePrivateMessage — C->S

**Contract.** Sender MailManager::RemoveMessage T 10028bc0 (busy +0x30). PostOffice hides the mail
in the UI immediately (S 0047dfc0).

| # | Field | Type |
|---|---|---|
| 1 | message_id | UNLONG |
| 2 | ticket_id | UNLONG (0x97) |

**Required server behaviour.** Result(42) on the ticket -> T 10028f90 -> slot 4 with (id 0,
errorcode). Because the id is 0 the client never erases the mail from its vector; it stays hidden
until the next header list [known, board #4731]. The server must stop listing the mail in later
149s.

**Open decisions.** **T20** Hard vs soft delete: client does not care. Default: hard delete.

#### 0x096 (150) AddPrivateMessage — C->S

**Contract.** Sender MailManager::AddMessage T 10028c60 (busy +0x34); PostOffice op 5 (S 0047d880)
after resolving the recipient name with a 72 RequestCharacters by name when not cached [known].

| # | Field | Type | Value |
|---|---|---|---|
| 1 | delivery_target | UNLONG | recipient id |
| 2 | creator | UNLONG | local perm id (LobbyManager+0x54c) |
| 3 | creation_time | UNLONG | always 0; the server stamps it [known] |
| 4 | title | STRING 128 | subject |
| 5 | message_text | MEMBLOCK | text incl. its NUL [known] |
| 6 | data | MEMBLOCK | empty [known] |
| 7 | ticket_id | UNLONG | request type 0x96 |

**Required server behaviour.** Complete with **AddResult(153)** {errorcode, id, ticket_id} -> T
10028fc0 -> PostOffice::SendMailResultReceived S 0047c5e0 (delegate gets errorcode). A Result(42) is
ignored (no 0x96 Result case): the ticket leaks, busy +0x34 stays 1 (every later send returns 4) and
the PostOffice queue stalls [known, board #4788]. **Stub differs:** 150 falls to the default
Result(42) ack (`dispatch.dispatch_lobby`).

**Open decisions.**
- **T21** AddResult `id`: passed to the observer but unused by SADK [inferred]. Default: the new
  message_id.
- **T22** Unknown recipient: return errorcode != 0; the delegate shows a failure [inferred]. Default
  errorcode 1.
- **T23** Delivery to an online recipient: no push path exists (149 is only consumed via the next
  list); the recipient sees it within 60 s [inferred]. Default: store only.

#### 0x01F (31) EmailMessage / 0x02B (43) EmailNotification

**Contract.** msgdefs: 31 {delivery_target_name STRING 32, body STRING 1024}; 43 {cell_id,
notification_type, target_msg_id} (all UNLONG). No sender in T and no case in any client handler
[known: sender scan; T 10023cc0 / T 10017ba0 case lists].

**Required server behaviour.** None; the client neither sends nor consumes them.
**Open decisions.** Do not send.

### Buddies (friends)

Lobby connection. tincat3 UserManager (CommLayer+0x18, vftable T 1005152c); SADK CharacterManager
action queue (ProcessActions S 00476390) with UserObserverListener (vftable S 007dbb4c). The buddy
list must be received for login to complete (BuddyListValid, S 004722d0) and before Add/Remove
friend is allowed [known, board #995]. `user_id` on every request is the client's chat-server
handle (LobbyManager::GetChatServerHandle) = local perm id [inferred].

Buddy record rules on the client (CharMgrUserEntry::AssignFromBuddyInfo S 0046b540) [known]:
- `perm_id_type` must be **2**, else the record is skipped.
- `status` **3** = online on a server; then `server_id` is stored only if ≥ 2 (unsigned). Any other
  status clears server info (server id -1 = shown offline, S 0046b350).

#### 0x038 (56) RequestUserBuddyList — C->S

**Contract.** Sender UserManager::RequestUserBuddyList T 1002dd00 (busy +0x24); SADK action 2
RefreshFriendList.

| # | Field | Type |
|---|---|---|
| 1 | user_id | UNLONG (local perm id) |
| 2 | ticket_id | UNLONG (0x38) |

**Required server behaviour.** N × **61 UserBuddyConn** with the request ticket, then
**Result(42)**. The Result calls observer vtbl+0x28 (userId, rows, count, errorcode) ->
BuddyListReceived S 00478160, which merges rows and sets BuddyListValid [known]. Result alone =
valid empty list [PROVEN: stub `_h_ack`, 31 live logins]. No Result: login hangs in state 6.

**Open decisions.** **T24** Buddy persistence and whether buddy relations are one-way: client imposes
nothing. Default: one-way list per perm id, persisted.

#### 0x03D (61) UserBuddyConn — S->C

**Contract.** Handler T 10023cc0 case 0x3d.

| # | Field | Type | Client use |
|---|---|---|---|
| 1 | user_id | UNLONG | read only when ticket_id == 0 (push path) [known: push @10025a3d] |
| 2 | buddy_id | UNLONG | record id (first read, @100259a7) [known] |
| 3 | name | STRING 128 | display name, also cached id<->name [known] |
| 4 | perm_id_type | UNSHORT | must be 2 [known] |
| 5 | status | UNBYTE | 3 = online on a server [known] |
| 6 | server_id | UNLONG | stored only if status 3 and ≥ 2 [known] |
| 7 | server_name | STRING 128 | stored with server_id [known] |
| 8 | ticket_id | UNLONG | 0 = push; 56's ticket = list row |

Paths [known]:
- ticket_id == 0: UserManager T 1002dce0 -> observer slot 9 -> BuddyUpdateReceived S 00476f90:
  inserts/overwrites the buddy and fires the buddy-updated observers. No observer registration
  (175) is needed for this to work.
- ticket of a pending 56: appended to the list (T 1002dda0).
- other tickets: dropped.

**Required server behaviour.** For list rows use the 56 ticket. For live presence changes push with
ticket_id 0.

**Open decisions.**
- **T25** When to push presence updates (login, logout, joining a game): client accepts any time
  after login [inferred]. Default: push to every client that lists the user as a buddy on login
  (status 1) and logout (status 0).
- **T26** `status` codes other than 3: all treated as "not on a server" [known], and the friends
  dialog draws such a buddy exactly like an offline one (dim; bright only with a stored server,
  S 004518a0 / S 0046b540). The stub sends 3 + the world's server id/name while the buddy's
  character is in a world, 0 otherwise.
- Entries are **character** ids: the dialog's Add button adds the avatar selected in the 3D world (not
  an NPC, not the own id), Remove needs a selected row, and double-clicking a row pre-fills
  "/tell <name>" (FriendIgnoreListDialog S 00452140 / S 00452400 / S 00451ec0) [known]. The dialog
  stores the server name but shows only the colour; no "follow into that world" action exists in it
  [known].
- **T27** A push for a user who is not yet a buddy adds them to the client's buddy map [known].
  Default: only push for actual buddies.

#### 0x062 (98) AddUserBuddy / 0x063 (99) RemoveUserBuddy — C->S

**Contract.** Senders T 1002dfe0 (busy +0x28) / T 1002e100; ticket data {user_id, buddy_id}.

| # | Field | Type |
|---|---|---|
| 1 | user_id | UNLONG (local perm id) |
| 2 | buddy_id | UNLONG (target perm id) |
| 3 | ticket_id | UNLONG (0x62 / 0x63) |

**Required server behaviour.** Result(42) on the ticket -> T 1002e0b0 / T 1002e1d0 -> observer
(userId, buddyId, errorcode) -> AddBuddyResultReceived S 004770b0 / RemoveBuddyResultReceived
S 00477550. On success the client adds the buddy (offline, server id -1) or removes it [known].
Stub acks with Result [inferred correct; not exercised live].

**Open decisions.**
- **T28** Refusals (self, unknown id, already a buddy, list full): any nonzero errorcode; the client
  just does not change its list [inferred]. Default: errorcode 1, no limit below 100.
- **T29** Follow-up presence push after add: optional; the added entry starts offline [known].
  Default: push one 61 (ticket 0) with the buddy's current status.

#### 0x0AF (175) RegObserverBuddylist / 0x0B0 (176) DeregObserverBuddylist — C->S

**Contract.** Senders T 1002db60 (no busy; nothing sent if user_id 0) / T 1002dc30.

| Msg | Fields |
|---|---|
| 175 | user_id UNLONG, send_all LBOOL, ticket_id UNLONG (0xaf) |
| 176 | user_id UNLONG, ticket_id UNLONG (0xb0) |

No SADK caller identified; the SADK observer slots 7/8 are no-ops [inferred].

**Required server behaviour.** Complete with **AddResult(153)**; Result(42) is ignored and the
ticket leaks (no visible effect beyond that) [known]. **Stub differs:** answers Result(42).

**Open decisions.** **T30** `send_all` semantics (initial dump of all buddies as 61 pushes):
[guess]. Default: if set, push one 61 per buddy with ticket 0 after the AddResult.

#### 0x09C (156) RequestUserBuddyRefs — C->S

**Contract.** msgdefs {user_id, ticket_id}. No sender in T [known: sender scan].
**Required server behaviour / open decisions.** None; never sent.

### Ignore list

Lobby connection, same UserManager / CharacterManager queue as buddies. IgnoreListValid
(S 00472310) is a login-completion condition [known, board #995].

#### 0x09D (157) RequestUserIgnoreList — C->S

**Contract.** Sender T 1002e220 (busy +0x30); SADK action 5. Fields: user_id UNLONG (local perm id),
ticket_id UNLONG (0x9d). It is the last list request of the lobby login [PROVEN: live order].

**Required server behaviour.** N × **160 UserIgnoreConn** with the ticket, then **Result(42)** ->
observer vtbl+0x34 -> IgnoreListReceived S 00478660 (stores id -> name, sets IgnoreListValid) [known].
Result alone = valid empty list [PROVEN: stub `_h_ignore_list`].

**Open decisions.** **T31** Ignore persistence: client imposes nothing. Default: persist per perm id.

#### 0x0A0 (160) UserIgnoreConn — S->C

**Contract.** Handler T 10023cc0 case 0xa0; delivered only for a pending 157 ticket (T 1002e2d0),
otherwise dropped [known].

| # | Field | Type | Client use |
|---|---|---|---|
| 1 | user_id | UNLONG | not read [known] |
| 2 | ignore_id | UNLONG | key [known] |
| 3 | name | STRING 128 | stored [known] |
| 4 | perm_id_type | UNSHORT | read; not checked by IgnoreListReceived [inferred] |
| 5 | status | UNBYTE | read, unused [inferred] |
| 6 | server_id | UNLONG | read, unused [inferred] |
| 7 | server_name | STRING 128 | read, unused [inferred] |
| 8 | ticket_id | UNLONG | the 157 ticket |

**Open decisions.** **T32** perm_id_type/status/server fields: any value. Default: 2 / 0 / 0 / None.

#### 0x09A (154) AddUserIgnore / 0x09B (155) RemoveUserIgnore — C->S

**Contract.** Senders T 1002e520 (busy +0x34) / T 1002e650. Fields: user_id UNLONG (local perm
id), ignore_id UNLONG, ticket_id UNLONG (0x9a / 0x9b).

**Required server behaviour.** Result(42) -> T 1002e600 / T 1002e730 -> AddIgnoreResultReceived
S 00478ae0 / RemoveIgnoreResultReceived S 004779a0 [known]. Stub default-acks with Result, which is
the right kind [inferred; not exercised live].

**Open decisions.** **T33** Refusals: any nonzero errorcode, list unchanged. Default: refuse self.

### Ranking

Ranking traffic does **not** use the lobby connection. tincat3 RankingManager (vftable T 1004fc7c,
CommLayer+0x5c) opens a separate ranking ("stat-surf") server connection, whose receive handler is
HandlerStatSurf T 100268e0 [known]. Connection setup:

1. RankingManager slot 3 T 10029a00 calls GameServerManager AssignServer(4, 5) -> 189 with
   server_type 4, server_subtype 5 (request type 0x108) [inferred: vtbl+0x2c call].
2. The 170 GameServerData reply on that ticket with type 4 && subtype 5 is consumed by
   OnGameServerAssigned T 10021520 -> RankingManager slot 8 ConnectRankingServer T 10029a20, which
   opens the connection to the 170's ip/port; the game is never notified [known].
3. Login on that connection: 188 CheckVersion -> Result(42) errorcode 0 -> 211
   StartValidateTokenSession -> 212 AckValidateTokenSession {nonce} -> 213 SendToken -> **153
   AddResult** errorcode 0 -> state 8 and RankingManager login notify (T 100268e0) [inferred]. A
   Result(42) on the 211 ticket always fails the connection [inferred].

No SADK caller of RankingManager is identified; the Hall of Fame is a web page
(HallOfFame_BuildUrl S 00442640, `HallOfFameURL<n>` in the client ini) [inferred]. This is also why
a 4/5 reply to a referee or game AssignServer is fatal: it is swallowed by this path [known].

| RankingManager slot | Address | Role |
|---|---|---|
| 3 | T 10029a00 | request ranking server (189 4/5) |
| 5 | T 10029aa0 | GameResultSubmit 252 |
| 6 | T 10029b90 | RequestSingleUserRank 254 |
| 7 | T 10029c20 | RequestRankRange 256 |
| 8 | T 10029a20 | ConnectRankingServer |
| 9 / 10 / 11 | T 10029d10 / T 10029d30 / T 10029d50 | 253 / 255 / 257 delivery |

#### 0x0FC (252) GameResultSubmit — C->S (ranking connection)

**Contract.** Sender T 10029aa0, sent on RankingManager+0x14.

| # | Field | Type |
|---|---|---|
| 1 | perm_id_a | UNLONG |
| 2 | perm_id_b | UNLONG |
| 3 | result | UNSHORT |
| 4 | map_id | UNLONG |
| 5 | custom_1 | UNLONG |
| 6 | custom_2 | UNLONG |

The sender also sets `ticket_id` (request type 0xfc), which is not in the template and has no wire
effect [inferred].

**Required server behaviour.** Reply 253 (no ticket correlation exists).

**Open decisions.** **T34** `result` meaning: no client code interprets it; docs say 0 tie / 1 A wins
/ 2 B wins [guess]. Default: store as received.

#### 0x0FD (253) GameResultSubmitResult — S->C (ranking connection)

**Contract.** HandlerStatSurf case 0xfd: reads result_id, perm_id_a, perm_id_b (UNLONG each) ->
RankingManager slot 9 -> observer vtbl+8 (perm_id_a, perm_id_b, result_id) [inferred]. Wire order
per msgdefs: perm_id_a, perm_id_b, result_id.

**Open decisions.** **T35** `result_id`: any u32 [inferred]. Default: stored result row id.

#### 0x0FE (254) RequestSingleUserRank — C->S (ranking connection)

**Contract.** Sender T 10029b90: {ranktable UNSHORT, perm_id UNLONG}; `ticket_id` written but not in
the template [inferred].

**Required server behaviour.** Reply 255.

#### 0x0FF (255) ReceiveSingleUserRank — S->C (ranking connection)

**Contract.** HandlerStatSurf case 0xff -> slot 10 -> observer vtbl+0xc [inferred].

| # | Field | Type | Read |
|---|---|---|---|
| 1 | ranktable | UNSHORT | yes |
| 2 | perm_id | UNLONG | yes |
| 3 | nick | STRING 256 | yes |
| 4 | rank | UNLONG | yes |
| 5 | points | UNLONG | yes |
| 6 | played | UNLONG | **not read**; the handler derives played = won + lost + tie + disconnected [inferred: key strings T 1004ee8c..eeac, 'played' 1004ee9c never pushed] |
| 7 | won | UNLONG | yes |
| 8 | lost | UNLONG | yes |
| 9 | tie | UNLONG | yes |
| 10 | disconnected | UNLONG | yes |

**Open decisions.** **T36** `played`: any value (ignored). Default: the sum, for consistency.

#### 0x100 (256) RequestRankRange — C->S (ranking connection)

**Contract.** Sender T 10029c20: {ranktable UNSHORT, rangestart UNLONG, rangeend UNLONG};
`ticket_id` not in the template [inferred].

**Required server behaviour.** Reply 257.

**Open decisions.** **T37** `ranktable` values (weekly/monthly/yearly per docs) and whether ranges
are 0- or 1-based: client code does not say [guess]. Default: 0 = all-time, 1-based inclusive range.

#### 0x101 (257) ReceiveRankRange — S->C (ranking connection)

**Contract.** HandlerStatSurf case 0x101 -> RankingManager::OnReceiveRankRange T 10029d50 (slot 11) ->
observer vtbl+0x10 (ranktable, start, end, count, entries).

| # | Field | Type |
|---|---|---|
| 1 | ranktable | UNSHORT |
| 2 | rangestart | UNLONG |
| 3 | rangeend | UNLONG |
| 4 | count | UNLONG |
| 5 | rankdata | MEMBLOCK |

`rankdata` = `count` packed records, no padding [known: T 10029d50]:

| Part | Type | Entry slot |
|---|---|---|
| A | u32 LE | entry+8 |
| B | u32 LE | entry+0 |
| nick | bytes, NUL-terminated (variable) | heap copy |
| points | u32 LE | +0xc |
| won | u32 LE | +0x14 |
| lost | u32 LE | +0x18 |
| tie | u32 LE | +0x1c |
| disconnected | u32 LE | +0x20 |

`played` is derived (won + lost + tie + disconnected). Which of A/B is perm_id and which is rank is
not settled [guess: A = perm_id, B = rank, by analogy with 255 field order].

**Required server behaviour.** `count` must match the blob: the parser has no bounds check and reads
past the buffer otherwise [known]. With no observer the message is ignored [known].

**Open decisions.** **T38** Page size: no client limit [inferred]. Default ≤ 50 records.

#### 0x102 (258) AddRankingServer — not used

**Contract.** msgdefs {ip STRING 128, port UNLONG, ticket_id}. No sender in T [known: sender scan].
Server-registration message; nothing to do.

### Users and accounts

Lobby connection, tincat3 UserManager (CommLayer+0x18). Live, the client sends 55, 56, 157 and
(with the login section) 53/158 as part of the login global-data load [PROVEN for 55/56/157].

#### 0x035 (53) RequestUsers — C->S / 0x03B (59) UserData — S->C

**Contract.** Senders RequestAllUsers T 1002ce60, ByName T 1002cee0, ById T 1002cf80, ByKey
T 1002d020 — 53 {user_id UNLONG, cd_key STRING 128, keypool UNSHORT, name STRING 128, selection
UNLONG, ticket_id (0x35)}. Reply rows 59 (T 10023cc0 case 0x3b, delivered only on a 0x35 ticket to
UserManager::OnUserData T 1002d0d0):

| # | Field | Type | Read |
|---|---|---|---|
| 1 | user_id | UNLONG | yes |
| 2 | name | STRING 128 | yes |
| 3 | password | STRING 32 | **not read** [known] |
| 4 | mail | STRING 128 | yes |
| 5 | banned | LBOOL | yes |
| 6 | active | LBOOL | yes |
| 7 | status | UNBYTE | yes |
| 8 | data | MEMBLOCK | split as u32 size[6] + 6 concatenated parts; < 0x18 bytes -> all parts empty; sizes not checked against the blob [known] |
| 9 | created | STRING 32 | yes |
| 10 | last_login | STRING 32 | yes |
| 11 | total_logins | UNLONG | yes |
| 12 | ticket_id | UNLONG | the 53 ticket |

**Required server behaviour.** N × 59 then Result(42) [PROVEN: stub `_h_user_info`].

**Open decisions.** **T39** `selection` semantics (by id / name / key) are implied by the sender
used [inferred]; default: match on the non-empty key. **T40** `password`: never read; send None.
**T41** `data` part sizes must not exceed the blob (parser reads past it) [known]; default: the
account blob the client stored, or empty.

#### 0x037 (55) RequestUserCharList — C->S / 0x03C (60) UserCharConn — S->C

**Contract.** Sender T 1002ea10 {user_id, ticket_id (0x37)}. 60 rows (case 0x3c, only on a 0x37
ticket -> UserManager::OnUserCharConn): char_id, name, owner_id, owner_name, guild_id, guild_name,
guild_role UNBYTE, status UNBYTE, server_id, server_name, data MEMBLOCK (u32 size[6] + parts, as
59), ticket_id [known].

**Required server behaviour.** N × 60 then Result(42) [PROVEN: stub `_h_player_info`].

**Open decisions.** **T42** Whether accounts may hold several characters: the client accepts N rows
[inferred]. Default: list every persisted character.

#### 0x039 (57) RequestUserGroupList — C->S / 0x03E (62) UserGroupConn — S->C

**Contract.** Sender T 1002e780 {user_id, ticket_id (0x39)}; rows 62 {user_id (not read), group_id,
name, level UNBYTE, ticket_id} delivered on a 0x39 ticket [known]. No SADK caller identified
[inferred].

**Required server behaviour.** N × 62 then Result(42). **Open decisions.** Default: empty list.

#### 0x054 (84) AddUser — C->S

**Contract.** Sender UserManager::AddUser T 1002d410 (busy +0x10): name, cipher MEMBLOCK
(encrypted password), mail, banned, active, data, ticket_id (0x54). If password encryption fails it
returns 3 without sending and leaves busy set [inferred, board #345]. Admin path; SADK account
creation uses 203 SelfRegistration instead (login section) [known, board #568].

**Required server behaviour.** AddResult(153) [known]. **Open decisions.** Default: reject (admin
only).

#### 0x058 (88) ChangeUser — C->S

**Contract.** Sender UserManager::ChangeUser T 1002ed80: user_id, name, cipher, mail, banned,
active, data, property_mask, ticket_id (0x58). SADK uses it only for UpdateEMail (CharacterManager
action 10): name/password empty, mail = new address, active 1, property_mask **8** (mail only)
[known: S 00476390].

**Required server behaviour.** Result(42) -> UserManager clear busy + observer 0x0c -> SADK
UserObserverListener::UpdateResultReceived S 00473e90 [known]. Stub acks [PROVEN as handler
`_h_char_ack`; live use not recorded].

**Open decisions.** **T43** `property_mask` bits other than 8: [TODO]; default: apply only the fields
whose bit is set, treat 8 = mail.

#### 0x05C (92) RemoveUser, 0x013 (19) - 0x01D (29) legacy user/group admin

**Contract.** msgdefs 19 RequestUser, 20 RequestGroup, 21 FullUserData, 22 FullGroupData, 23
CreateUser, 24 CreateGroup, 25 UpdateUser, 26 UpdateGroup, 27 RequestRemoveUser, 28
RequestRemoveGroup, 29 UserMgrResult, 92 RemoveUser. No sender in T and no client case [known:
sender scan, T 10023cc0 case list].

**Required server behaviour / open decisions.** None; never sent, do not send.

#### 0x060 (96) AddUserKey / 0x061 (97) RemoveUserKey — C->S

**Contract.** Senders T 1002d980 / T 1002da70: {user_id, cd_key STRING 128, keypool UNSHORT,
ticket_id (0x60/0x61)}. No SADK caller identified [inferred].

**Required server behaviour.** Result(42) -> observer slot 0x14 / 0x18 [known].

#### 0x09E (158) RequestUserKeyList — C->S / 0x09F (159) UserKeyConn — S->C

**Contract.** Sender T 1002d6f0 {user_id, ticket_id (0x9e)}. 159 rows (case 0x9f, only on a 0x9e
ticket): user_id, cd_key STRING 128, keypool UNSHORT read with the **byte** accessor (value
truncated to 8 bits) [known]. Login-time request; see the login section for its place in the
sequence.

**Required server behaviour.** N × 159 then Result(42) [PROVEN: stub `_h_cdkeys`].

**Open decisions.** **T44** `keypool` 0..255 (higher bits are dropped) [known]; default 1. `cd_key`:
any string ≤ 127 bytes; default a dummy key.

#### 0x06D (109) - 0x074 (116), 0x07B (123), 0x07D (125) user observers

**Contract.** msgdefs 109 UserLoggedIn, 110 UserLoggedOut, 111/112 Reg/DeregObserverUserList,
113/114 Reg/DeregObserverCharList, 115/116 Reg/DeregObserverUserLogin, 123 UserAdded, 125
UserRemoved, 126 CharAdded, 128 CharRemoved. No sender in T, no client case [known]. The stub acks
115/116 for safety; the client never sends them [inferred].

**Required server behaviour / open decisions.** None.

#### 0x03A (58) RequestPermIDAccess / 0x03F (63) PermIDAccess, 0x090 (144) RequestPermID / 0x091 (145) PermIDData, 0x0B8 (184) SetUserVisible, 0x0BA (186) ChangeGroupUser, 0x0BB (187) ChangeUserKey

**Contract.** msgdefs only. No sender in T and no client case [known].

**Required server behaviour / open decisions.** None.

### Characters

Lobby connection. tincat3 CharacterManager (CommLayer+0x14, vftable T 1004e930); SADK
CharacterManager action queue S 00476390 (one action in flight). Character `data` blobs are six
sub-blocks: u32 size[6] then the parts (CommLayer::Character); the stub stores and replays the
client's bytes unchanged [PROVEN].

#### 0x048 (72) RequestCharacters — C->S / 0x04B (75) CharacterData — S->C

**Contract.** Senders RequestCharacterByName T 10015d50, ById T 10015df0: {char_id UNLONG, name
STRING 128, selection UNLONG, ticket_id (0x48)}. SADK uses it for its own list and for name<->id
lookups (actions 8/9, used e.g. by mail recipient resolution) [known]. 75 rows (case 0x4b, only on
a 0x48 ticket -> CharacterManager::OnCharacterData T 100163c0) have the same 11 fields as 60 plus
ticket_id [known]; buffered and delivered on the Result (T 10016730).

**Required server behaviour.** N × 75 then Result(42). Zero rows is a supported path: the client
opens character creation (S 00474910) [PROVEN: stub `_h_request_characters`]. A lookup that is not
answered stalls the SADK CharacterManager queue, including buddy/ignore actions [known].

Lookups [known]: LookUpName (CharManAction 8, e.g. a mail's sender name, Mail::UpdateFromRecord
S 0048cce0 shows "???" until it resolves) sends `char_id`; LookUpID (action 9, e.g. a mail recipient
typed by name) sends the lower-cased `name`. CharacterDataReceived S 00473590 takes the **first** 75
row's name / char_id; no row = unknown (empty name / id 0). Mail is addressed from and to characters.

**Open decisions.** **T45** `selection` values for by-id vs by-name: [TODO]; the stub matches whichever
of char_id / name is set and answers the requester's own list when neither is. **T46** Unknown name/id: Result(42) with no rows or errorcode != 0; both end
the lookup [inferred]. Default: no rows, errorcode 0.

#### 0x056 (86) AddCharacter — C->S

**Contract.** Sender T 10015e90, SADK action 0 CreateCharacter: {name STRING 128, user_id UNLONG,
data MEMBLOCK (6 × u32 sizes + parts), ticket_id (0x56)} [known].

**Required server behaviour.** **AddResult(153)** {errorcode, id = new char_id} -> T 100160e0 ->
CreateResultReceived S 00476a40 [known; PROVEN: stub `_store_character` -> `status_with_id`].

**Open decisions.** **T47** Name rules (length, uniqueness, charset): client imposes only STRING 128
[inferred]. Default: unique per server, 3..32 characters. **T48** char_id allocation: any nonzero
u32 distinct from other characters [inferred]; default a store counter.

#### 0x04D (77) CreateCharacterFromPreview — both / 0x04F (79) AddCharacterFromPreview

**Contract.** 77 {name, owner_id, data, ticket_id}: sender T 10016030 (no SADK caller identified
[inferred]); also a **S->C** case in T 10023cc0 (0x4d): reads the fields and, if CommLayer
vtbl+0x2c is set, calls a game callback at CommLayer+0x34; no ticket release [known]. 79: no
sender in T [known]. AddResult routes neither (0x4d/0x4f not in table T 1002677c), so a 153 for them
is ignored [known].

**Required server behaviour.** None required; the stub's 153 answers are harmless no-ops.

#### 0x05A (90) ChangeCharacter — C->S

**Contract.** Sender T 10016550: {char_id, name, data, property_mask, ticket_id (0x5a)}.

**Required server behaviour.** Result(42) -> clear busy + notify (errorcode, ticket data) [known].
Stub acks and persists [PROVEN as handler].

**Open decisions.** **T49** `property_mask` bit meanings: [TODO]; default: apply the fields sent.

#### 0x05E (94) RemoveCharacter — C->S

**Contract.** Sender T 10016120, SADK action 1: {char_id, ticket_id (0x5e)}.

**Required server behaviour.** Result(42) -> OnRemoveCharacterResult T 100161e0 -> DeleteResultReceived
S 00473a50 [known]. Stub deletes by the named char_id [PROVEN as handler].

#### 0x071 (113) / 0x072 (114) / 0x07E (126) / 0x080 (128) / 0x089 (137) character observers and restore

See "user observers" (113/114/126/128: never sent or handled) and "Backup" (137).

### Groups

Lobby connection, tincat3 GroupManager (CommLayer+0x24). No SADK caller identified for any group
request [inferred]. All follow the generic rule: rows with the request ticket, then Result(42), or
AddResult(153) for 85.

| Id | Name | Dir | Fields (msgdefs order) | Sender / handler | Completion |
|---|---|---|---|---|---|
| 0x040 (64) | RequestGroups | C->S | group_id, name S128, selection, ticket_id | T 10021950 / T 100219d0 | 69 rows + Result |
| 0x045 (69) | GroupData | S->C | group_id, name, level u8, ticket_id | case 0x45 -> T 10021a70 (0x40 ticket only) | — |
| 0x042 (66) | RequestGroupUserList | C->S | group_id, ticket_id | T 10021e80 | 68 rows + Result |
| 0x044 (68) | GroupUserConn | S->C | group_id, user_id, name, server_id, server_name, ticket_id; client reads group_id/user_id and name only, server fields not read [known] | case 0x44 -> T 10021f20 (0x42 only) | — |
| 0x043 (67) | RequestGroupAccess | C->S | group_id, access_index u16, ticket_id | T 100222b0 | 70 + Result |
| 0x046 (70) | GroupAccess | S->C | group_id, access_index u16, access, ticket_id | case 0x46 (0x43 only) | — |
| 0x055 (85) | AddGroup | C->S | name, level u8, ticket_id | T 10021c30 | AddResult(153) |
| 0x059 (89) | ChangeGroup | C->S | group_id, property_mask, name, level, ticket_id | T 10021d00 | Result |
| 0x05D (93) | RemoveGroup | C->S | group_id, ticket_id | T 10021de0 | Result |
| 0x064 (100) | AddGroupUser | C->S | group_id, user_id, ticket_id | T 10022100 | Result |
| 0x065 (101) | RemoveGroupUser | C->S | group_id, user_id, ticket_id | T 100221e0 | Result |
| 0x068 (104) | SetGroupAccess | C->S | group_id, access_index u16, access, ticket_id | T 10022370 | Result |

**Open decisions.** **T50** Group model (levels, access indices): entirely server-side; client
imposes nothing [inferred]. Default: reject admin writes, return empty lists.

### Guilds

Lobby connection, tincat3 GuildManager (CommLayer+0x1c). No SADK caller identified [inferred].

| Id | Name | Dir | Fields (msgdefs order) | Sender / handler | Completion |
|---|---|---|---|---|---|
| 0x04E (78) | RequestGuilds | C->S | owner_id, guild_id, name, selection, ticket_id | T 10022510 / T 10022590 / T 10022630 | 82 rows + Result |
| 0x052 (82) | GuildData | S->C | guild_id, name, owner_id, owner_name, data (u32 size[4] + parts; < 0x10 bytes -> empty), ticket_id | case 0x52 -> T 100226d0 (0x4e only) | — |
| 0x050 (80) | RequestGuildCharList | C->S | guild_id, ticket_id | T 10022d60 | 83 rows + Result |
| 0x053 (83) | GuildCharConn | S->C | guild_id, perm_id, name, perm_id_type u16, status u8, server_id, server_name, guild_role u8, ticket_id | case 0x53 -> T 10022e00 (0x50 only) | — |
| 0x057 (87) | AddGuild | C->S | name, owner_id, data, ticket_id | T 10022960 | AddResult(153) |
| 0x05B (91) | ChangeGuild | C->S | guild_id, name, owner_id, data, property_mask, ticket_id | T 10022b00 | Result |
| 0x05F (95) | RemoveGuild | C->S | guild_id, ticket_id | T 10022cc0 | Result |
| 0x066 (102) | AddGuildChar | C->S | perm_id, guild_id, ticket_id | T 10023120 | Result |
| 0x067 (103) | RemoveGuildChar | C->S | perm_id, guild_id, ticket_id | T 100232d0 | Result |
| 0x098 (152) | ChangeGuildChar | C->S | perm_id, guild_id, guild_role u8, ticket_id | T 100231d0 | Result |

Characters carry guild_id / guild_name / guild_role in 60/75; the stub sends 0 / None / 0
[PROVEN accepted].

**Open decisions.** **T51** Guild support: client imposes nothing. Default: no guilds (guild_id 0,
empty lists).

### CD keys

Lobby connection, tincat3 CDKeyManager (CommLayer+0x28). Admin paths; no SADK caller identified
[inferred]. Login-time key handling is in the login section.

| Id | Name | Dir | Fields | Sender / handler | Completion |
|---|---|---|---|---|---|
| 0x077 (119) | RequestSingleCdKey | C->S | cd_key S128, keypool u16, ticket_id | T 100159a0 | 120 + Result |
| 0x078 (120) | CdKeyData | S->C | cd_key, keypool (read as byte), banned LBOOL, user_id, ticket_id | case 0x78 -> T 10015a50 (0x77 only) | — |
| 0x08C (140) | AddKey | C->S | cd_key, keypool, ticket_id | T 10015a90 | Result |
| 0x08D (141) | RemoveKey | C->S | cd_key, keypool, ticket_id | T 10015c30 | Result |
| 0x08E (142) / 0x08F (143) | BanKey / UnbanKey | C->S | cd_key, keypool, ticket_id | SetKeyBanned T 10015b60 | Result |

**Open decisions.** **T52** Key validation policy: server-side only. Default: accept every key,
keypool 0..255.

### Machines and kicks

Lobby connection, tincat3 MachineManager (CommLayer+0x2c). Admin; no SADK caller identified
[inferred].

| Id | Name | Dir | Fields | Sender / handler | Completion |
|---|---|---|---|---|---|
| 0x079 (121) | RequestMachines | C->S | machine_id, ip S128, selection, ticket_id | T 10027ff0 / T 10028070 / T 10028110 | 122 rows + Result |
| 0x07A (122) | MachineData | S->C | machine_id, description S128, ip S128, active LBOOL, ticket_id | case 0x7a -> T 100281b0 (0x79 only) | — |
| 0x0A7 (167) | RequestMachineGameServers | C->S | machine_id, selection, ticket_id | T 100283c0 | 170 rows (each 170 releases the ticket) + Result |
| 0x07C (124) | KickPermIDMachine | C->S | perm_id, machine_id, ticket_id; also sent by KickMachine T 10028780 and KickPermID T 100288d0 | T 10028820 | Result |
| 0x08A (138) | KickPermIDServer | C->S | perm_id, ip, port, ticket_id; the sender also sets `server_id`, not in the template [known, board #898] | T 100215f0 | Result -> GSM listener 0x38 |
| 0x08B (139) | KickPermID | — | perm_id, ticket_id | no sender (KickPermID sends 124) [known] | — |

For 167, each 170 on the 0xa7 ticket is delivered and **releases the ticket** (T 10023cc0 0xaa
branch), so only the first row arrives and the closing Result is dropped [known] — same pattern as
166 in the hosting section.

**Open decisions.** **T53** None useful; default: empty lists / errorcode 1.

### Server info and statistics

Lobby connection. tincat3 ServerInfoManager (CommLayer+0x44) and ConnectionManager statistics
path. No SADK caller identified [inferred].

#### 0x0B4 (180) RequestServerInfo — C->S / 0x0B5 (181) ServerInfoData — S->C

**Contract.** Sender T 10029f30 {ticket_id (0xb4)}. 181 {starttime S32, starttimestamp, time,
patchlevel, txt S256, ticket_id}: case 0xb5 -> ServerInfoManager::OnServerInfoData T 1002a080 for
any ticket [known]. Completion: Result(42) -> OnResult T 1002a020 [known].

**Required server behaviour.** 181 then Result(42) [inferred].
**Open decisions.** **T54** Values: free; default patchlevel 9212.

#### 0x075 (117) RegObserverUptime / 0x076 (118) DeregObserverUptime / 0x0B6 (182) UptimeData

**Contract.** 117 sender T 10029fb0 {ticket_id (0x75)}, completed by Result(42) -> OnResult. 182
{uptime, registered_users, logins, registered_gameservers, started_gameservers, ticket_id}: case
0xb6 -> OnUptimeData T 1002a0f0 for any ticket [known]. 118 has no sender [known].

**Open decisions.** **T55** Push cadence for 182: free; default none.

#### 0x0AD (173) GetStatisticsConnection / 0x0AE (174) StatisticsConnection

**Contract.** 173 sender ConnectionManager::RequestStatisticsConnection T 10019480 {ticket_id
(0xad)}. 174 {ip MEMBLOCK, port, name MEMBLOCK, username MEMBLOCK, password MEMBLOCK, ticket_id}:
case 0xae reads ip and port only; name/username/password are passed as empty strings; forwarded
only on a 0xad ticket; ticket always released [known]. A Result(42) on 0xad reports an empty
statistics connection (T 10019520) [known].

**Open decisions.** **T56** Default: answer Result(42) errorcode 1 (no statistics server).

#### 0x030 (48) - 0x034 (52) Statistics item messages

**Contract.** msgdefs 48 StatisticsRequestItemList, 49 StatisticsGetLiveValue, 50
StatisticsItemInfo, 51 StatisticsLiveValueData, 52 StatisticsResultCode. No sender in T and no case
in any lobby-side handler [known]. Never used.

### Backup, patch level and server-side admin

| Id | Name | Dir | Contract | Behaviour |
|---|---|---|---|---|
| 0x087 (135) | RestoreUser | C->S | user_id, restore_chars LBOOL, filename S256, ticket_id; sender BackupManager::RestoreUser T 100143d0 | Result(42) -> T 10014550 -> listener vtbl+8 with **no arguments** (errorcode not forwarded) [known] |
| 0x089 (137) | RestoreChar | C->S | char_id, filename S256, ticket_id; sender T 10014490 | Result(42) -> T 10014530 -> listener vtbl+0xc, no arguments [known] |
| 0x0B2 (178) | ChangePatchlevel | — | patchlevel, ticket_id | no sender in T [known] |
| 0x0B7 (183) | CheckLevel | — | level u8, ticket_id | no sender in T [known] |
| 0x0B9 (185) | DownloadLogs | — | ticket_id | no sender in T [known] |
| 0x0BF (191) | AddUsercomm | — | ip, port, max_players u16, ticket_id | no sender in T (server registration) [known] |
| 0x0C1 (193) | UsercommRequestUserdata | C->S | perm_id, ticket_id; sender TokenValidator::GetPermIDInfos T 1002a770 (game host validating a joiner) | Result(42) on 0xc1 invokes the callback with an **empty** record {0, "", 0}; the data arrives in 194 [known] |
| 0x0C2 (194) | UsercommUserData | S->C | perm_id, username S32, user_access, ticket_id | case 0xc2 -> TokenValidator::InvokeGetPermIDInfosCallback for any ticket [known] |
| 0x104 (260) | CheckPlayerOnServerAndGetInfos | C->S | ticket_id, connection_pid, user_pid; sender GameServerManager T 10021720 | the reply 261 has **no case** in T 10023cc0: dropped, the registered callback (T 10021700) is never invoked from the wire [known: case list] |
| 0x105 (261) | CheckPlayerOnServerAndGetInfosReply | S->C | perm_id, username S32, user_access, ticket_id, result_id | not handled on the lobby connection [known] |

No SADK caller identified for 135, 137, 260 [inferred]. 193/194 belong to the hosting/token flow;
when the host sends 193 is [TODO].

**Open decisions.** **T57** 194 contents (username, user_access) for a joiner lookup: client accepts
any; default the joiner's account name and access 0.

### Cyclic admin messages (server messages)

These travel through the **CellManager relay on the UC/chat connection** (module 0x62, cell 1), not
the lobby connection. tincat3 CyclicMsgManager; SADK ServerMessages registers an
ICyclicMsgObserver whose slot 1 is empty (S 00488270), so the game ignores the result [inferred].
Senders use the UC send path (connection vtbl+0xa0) and a UC-side ticket with a
RequestContextTable kind (e.g. 7 for RequestAllMessages) [inferred].

| Id | Name | Dir | Contract | Behaviour |
|---|---|---|---|---|
| 0x00A (10) | AdminRequestAllMessages | C->S | cell_id (= 1), ticket_id; sender T 1001ffc0 | rows 13, completion Result(42) via the relay (T 1001fd60) [inferred] |
| 0x00D (13) | AdminMessageEntry | S->C (relayed) | cell_id, msg_id, msg_type, msg_data MB, title S128, usrcom_mode, creation_time, creator, expiration_mode u16, expiration_date, delivery_mode u16, delivery_target, delivery_interval, delivery_date | relay case 13 -> CyclicMsgManager::OnAdminMessageEntry T 1001fbe0, which can build a ChatMessage(2) blob (T 1001fea0) [inferred] |
| 0x00E (14) | AdminAddMessageEntry | C->S | 13's fields + ticket_id; sender T 100200b0 | Result via relay -> T 1001fe40 |
| 0x00B (11) | AdminUpdateMessage | C->S | 13's fields + ticket_id; sender T 100202e0 | Result via relay -> T 1001fe70 |
| 0x00F (15) | AdminRemoveMessageEntry | C->S | cell_id, msg_id, ticket_id; sender T 1001fa40 | Result via relay -> T 1001fb90 |
| 0x008 (8), 0x009 (9), 0x00C (12), 0x020 (32), 0x021 (33) | AdminRequestMsgList, AdminRequestMessage, AdminMessageList, AdminAddEmailMessageEntry, AdminRequestEmailList | — | msgdefs only | no sender in T, no relay case [known] |

**Open decisions.** **T58** Whether to run cyclic server announcements: the game ignores the
observer callback, but 13 entries may surface as chat lines [inferred]. Default: none.

### Broker (auction house)

Also relayed through the **CellManager on the UC/chat connection** (cell 1). Senders call the UC
session send (vtbl+0xa0(1, type, msg, 1, -1)) with a UC-side ticket and a RequestContextTable kind;
replies arrive as relayed 35, 38, 42, 45, 47 handled in T 10017ba0 [inferred]. Result errorcodes
are translated by CommLayer_MapBrokerResultCode T 10014cb0 [known]. No SADK caller identified
[inferred].

| Id | Name | Dir | Fields (msgdefs order) | Sender / receiver |
|---|---|---|---|---|
| 0x022 (34) | BrokerAddItem | C->S | owner (own user id), item_type u16, item_name S128, item_prize, item_values S1024 (always ""), item_data MB, ticket_id | T 100145b0; answered by 38 (kind 10) or Result |
| 0x023 (35) | BrokerChangePrize | both | item_id, item_prize, ticket_id | T 10014720 / relay -> T 10014c40 |
| 0x024 (36) | BrokerRemoveItem | C->S | item_id, ticket_id | T 10014820; Result -> T 10015410 |
| 0x025 (37) | BrokerGetItem | C->S | netzone u16, item_id, ticket_id | T 10014920, T 10014f60 |
| 0x026 (38) | BrokerItem | S->C | item_id, owner, owner_name S32, item_type u16, item_name S128, item_prize, item_values S1024, item_data MB, ticket_id | relay -> T 10015700 |
| 0x027 (39) | BrokerGetItemList | C->S | netzone u16 (= 1), item_type u16, owner_name S32, name_pattern S128, min_prize, max_prize, offset (1-based: page × limit + 1), limit u16, sort_field SIBYTE (0), sort_order LBOOL (0), criterias S1024 (""), ticket_id | T 100151e0; rows 38, end 47 |
| 0x028 (40) / 0x029 (41) | BrokerGetLimit / BrokerLimit | — | ticket_id / limit u16, ticket_id | no sender, no relay case [known] |
| 0x02C (44) | BrokerBuyRequest | C->S | item_id, buyer, ticket_id | T 10014a20; Result -> T 10015510 |
| 0x02D (45) | BrokerNotification | both | item_id, buyer, ticket_id | T 10015070 / relay -> T 100155f0 |
| 0x02E (46) | BrokerSoldNotification | — | msgdefs only | no relay case: dropped [known] |
| 0x02F (47) | BrokerItemListFinished | S->C | items_found, ticket_id | relay -> T 10014b20 |

**Open decisions.** **T59** Broker support: client imposes nothing; default: none (errorcode 1).

### Cross-reference to the other sections

| Ids | Section | Notes |
|---|---|---|
| 2, 3, 5, 6, 7, 16, 17, 18, 30, 76, 107, 108, 165, 240-251, 259, 262 | login/chat (UC) | relayed through the CellManager (module 0x62) |
| 4, 71, 188, 201-207, 211-214, 224 | login | lobby login completes on 207 (T 10023cc0 case 0xcf); UC/server-id connections complete on 153 (T 10023460) |
| 146, 166-172, 177, 189, 190, 221, 222, 223 | hosting | AssignServer 189 reply 170 with type 4/subtype 5 is consumed by the ranking path (T 10021520) |
| 73, 74, 1000+ | village | 73/74 are ignored on the lobby connection (T 10023cc0 cases 0x49/0x4a) |
| 192 | login/hosting | UsercommServerData: case 0xc0 -> ConnectionReal::ConnectToServer T 10030420 |

## Server decisions

Every point where the client leaves the choice to the server. "Accepted range" is what the client
tolerates; the default is a suggestion, not a client requirement. Ids match the per-message
**Open decisions** entries.

### Transport and generic replies

| Id | Message | Decision | Accepted range | Suggested default |
|---|---|---|---|---|
| T1 | TinCat frame | `from` / `unk1` on S->C frames | not checked on CUSTOMDATA delivery [inferred] | server id constant, unk1 = 0 |
| T2 | 5 LOGONACCEPTED | connection id | any u32 [inferred] | per-socket counter from 1 |
| T3 | 42 Result | `errormsg` text | never read on the lobby path | None |
| T4 | 42 Result | non-zero errorcode values | consumers distinguish only 0 / non-zero unless noted [inferred] | 1 for failures |
| L2 | 42 Result (login) | errormsg and non-zero errorcode during login | not read for login | errormsg None, errorcode 1 |

### Login and UC/chat

| Id | Message | Decision | Accepted range | Suggested default |
|---|---|---|---|---|
| L1 | 188 CheckVersion | which versions to accept | errorcode 0 for any version; any other errorcode closes; real clients send 27 | accept all with errorcode 0, or reject anything but 27 |
| L3 | 202 AckAuthenticateSession | secret length and content | up to the hash size and a Twofish key size: 16, 24 or 32 bytes [inferred] | 32 random bytes |
| L4 | 202 | hash OID | any LTC-registered hash whose output is at least the secret length [inferred] | SHA-512 (2.16.840.1.101.3.4.2.3), proven |
| L5 | 203 SelfRegistration | registration policy (name, password, CD key) | 207 = accept, any Result(42) = refuse | create if the name is free, else Result(42) errorcode 1 |
| L6 | 204 AuthenticateUser | credential policy | any 207 accepts; any Result(42) refuses | require a known user and matching password; CD-key hash check optional |
| L7 | 205 / 206 | accept support/server logins | client never sends them | refuse with Result(42) |
| L8 | 207 SessionKey | perm_id | any u32; keep unique and stable, avoid 0, 0xEFFFFFxx and the EnterWorld ServerPerm [inferred] | sequential account id from 1 |
| L9 | 207 | session key | up to 0x80 bytes, must be 16/24/32 to key Twofish [inferred] | 32 random bytes per login, kept server-side |
| L10 | 162 PropertyData (1,1) | minimum protocol version `value` | any int32 <= client ProtocolVersion (1000), signed; any value if the client's is 0 | 0 (accept all) or 1000 (shipped build) |
| T8 | 162 PropertyData (1,1) | same value, tincat3 view | as L10; larger disconnects with error 62 | 1000 (the stub sends 0, which passes) |
| T9 | 162 | values for other (kategory, index) pairs | the client never asks [inferred] | 0 with errorcode 0 |
| L11 | 106 MOTD | MOTD text | UTF-8 up to 255 bytes + NUL; longer is clamped | a short welcome line |
| T5 | 106 MOTD | MOTD text (tincat3 view) | as L11 | a short welcome line |
| T6 | 106 MOTD | unsolicited 106 (ticket 0) | accepted and shown [inferred] | do not push |
| L12 | 159 UserKeyConn | which keys to list | content not validated; keypool < 256 | the account's registered key, keypool 1 |
| T44 | 159 UserKeyConn | keypool / cd_key | keypool 0..255; cd_key <= 127 bytes | keypool 1, dummy key |
| L13 | 120 CdKeyData | banned flag and user mapping | any values | banned 0, user_id = owner perm_id or 0 |
| L14 | 192 UsercommServerData | UC endpoint (ip, port, server_id) | any reachable address, any u32 id | advertised IP, port 7071, server_id 1 |
| L15 | 212 AckValidateTokenSession | nonce length and content | 0..255 bytes (u8 length in the token) | 128 random bytes |
| L16 | 213 SendToken | verify the token | client does not care | verify when the session key is known; non-zero 153 on failure |
| L17 | 153 AddResult (token) | `id` value | UC ignores it; on server-id connections a non-zero id overwrites the local perm id | the 207 perm_id |
| L28 | 224 TANLogin | validate the nonce against the issuing 222 | client does not care | as L16 |
| L18 | 17 RequestJoinChannel | join policy | StatusReply result 0, 1 or 0x12; anything else leaves the join pending | 0 |
| L19 | 5 UserJoinedChannel | membership fan-out | any number of 5 frames | one per member, one connection per player |
| L20 | 259 RequestLeaveChannel | can a leave be refused | result 0 or 1 | 0 |
| L21 | 2 ChatMessage | moderation, `self` echo | anything | relay as is |
| L22 | 30 / 3 whispers | target offline or ignoring | no client error path | drop, or a 3 from the server perm with a text |
| L23 | 5 UserJoinedChannel | display nick per perm_id | any string up to 255 bytes | character name |
| L24 | 76 BeenKicked | does the server kick | any channel | never |
| L25 | CellManager tpl 0 | channel set, names, subjects, flags | any cell ids the client is later told to join | `DEFAULT_CHANNELS + ZONE_CHANNELS` |
| L26 | CellManager tpl 7 | player channel creation, id assignment | any new cell_id published | refuse with 0x11 |
| L27 | CellManager tpl 11 | result codes for refusals | join 0/1/0x12, leave 0/1, create 0x11, delete 0x13, kick 1; others dropped | 0 for success |

### Hosting, server list and referee

| Id | Message | Decision | Accepted range | Suggested default |
|---|---|---|---|---|
| H1 | 171 / 170 | entries per list | any number; type 4 needs one valid village to show anything | every registered entry of that type |
| H2 | 171 | filter semantics (room_id, level, game_mode, hardcore) | SAdK always sends 0 | 0 = no filter |
| H3 | 170 | server_id values | unique u32 across all connections, not 0xFFFFFFFE / 0xFFFFFFFF | counter from 100 |
| H4 | 170 (game) | `ip` | dotted IPv4, <= 15 chars [inferred] | host connection's public source address |
| H5 | 170 | unread fields (owner_id, version, cur_spectators, level, game_mode, room_id, locked_config) | anything | echo the host; owner_id = host perm_id |
| H6 | 170 (village) | name, counts, running, data | running 1 adds, 0 removes; data roomId = 1000 | as the stub sends them |
| H7 | 168 AddGameServer | accept or refuse a host | errorcode 0; non-zero tears down the host network | accept |
| H8 | 168 | returned id | see H3 | see H3 |
| H9 | 177 ChangeGameServer | `cipher` -> password_required | anything | non-empty -> 1 |
| H10 | 189 / 170 (referee) | referee server id | non-zero, unique, **stable** across retries | fixed id (stub 77) |
| H11 | 170 (referee assign) | descriptor type/subtype | any pair except 4/5 | 4/4 |
| H12 | 222 ConnectionData | ip/port per server | any reachable endpoint | advertised IP + that server's listener port |
| H13 | 222 | nonce | any bytes on the observed login path | 128 random bytes |
| H14 | 0xDCA LoginSuccess | delay after the 153 | any, within the retry window | 0.5 s |
| H15 | 0xDCA / 0xDCB | referee admission | either | always LoginSuccess |
| H16 | 0xDB7 / 0xDB8 | RegisterGame validation | Result 0 proceeds; non-zero fails the match | accept |
| H17 | 0xDB8 | GameSeed | any u32, the same for every client of a match [inferred] | one value per match, e.g. from GameID |
| H18 | 0xDB8 | GameID echoed | not compared | echo the request's GameID |
| H19 | 0xDC0 FinishGame | reconcile N reports | anything | accept every report; record when they agree |
| H20 | 0xDD4 GiveUpGame | record a give-up as a loss | anything | record it |
| H21 | 0xDD5 | Result code | 0..20 (>= 21 crashes the client) | 0 |
| H22 | 0xDAC / 0xDAE | grant or deny a chest, AvatarID / Text | AvatarID != 0 = grant, 0 = deny; Text free | claimant's AvatarID, empty text |

### Village / world

| Id | Message | Decision | Accepted range | Suggested default |
|---|---|---|---|---|
| V1 | 74 SendGameData | category bits of outbound type words | 0..7 (ignored) | 2 (0 is live-proven) |
| V2 | 74 | names mode | 0 or 1 (1 needs a trailing 32-bit word) | 0 |
| V3 | 73 SendGameDataBundle | use bundles | any count; an overrunning entry ends the walk | do not use 73 |
| V4 | 1000 EnterWorld | Worldname | any string up to 255 bytes; empty shows `<UNNAMED>` | village name (stub "world1") |
| V5 | 1000 | ServerPerm | any u32; chat from it shows as [SYSTEM] [inferred] | a perm id no speaker uses (stub 0) |
| V6 | 1000 | chat cell ids per key | non-zero u32 per key (0x00-0x0F zones, 0xFE minigame, 0xFF global) | 0xFF -> 1, 0xFE -> 2, zone z -> 16+z |
| V7 | 1000 | delay after the village 153 | any time after transport state 8 [inferred] | short settle (stub 2.0 s) |
| V8 | 1005 WorldTick | tick cadence | any rate | once before the first waypoint, then 1 Hz |
| V9 | 1001 AvatarData | which blocks (dtblcks) | mask 0..15 | location+style on spawn, location on refresh |
| V10 | 1001 | appearance (trbgndr, 8 colours) | any bytes; body part >= 3 clamped | the character's stored appearance |
| V11 | 1001 | refresh cadence | ring of 8 waypoints, 3.0 s stale cut-off | relay each 2000 + 1 Hz keepalive |
| V12 | 1001 | Stats values | any u32; exp within the level's XP thresholds [inferred] | stored character values |
| V13 | 1002 AvatarLoggedIn | announce arrivals | either | do not send |
| V14 | 2000 AvatarLocation | movement validation | any relay | relay verbatim, re-stamped with the server clock |
| V15 | 3950 AvatarColorChange | tailor price | client checks gold >= 50 only | charge 50; send 3201 + style 1001 |
| V16 | 3200 LevelExpUpdate | level/XP rules | any u32 pair (see V12) | stored values |
| V17 | 3201 StatsUpdate | economy (gold, glod) | any u32 | stored values; new characters gold = glod = 50 |
| V18 | 1004 NPCData | NPC cast | npcidx 0..15, npctyp 1/2 to be visible | the stub's `npcs.make_village_npcs` set |
| V19 | 1004 | NPC actions | act 0..255, **at most 3 slots** | shop 11, mailbox 7, tailor 17, minigames 2..6 |
| V20 | 1004 | NPC ids | any u32 not colliding with avatar ids [inferred] | a reserved high range |
| V21 | 3001 MoveItem | move validation | whatever the following update says | apply legal moves, resend state otherwise |
| V22 | 3002 DeleteItemRequest | allow deletion | any | allow |
| V23 | 3100 / 3102 | item ids and slot types | any u32 (ids from encrypted game data [TODO]) | empty slots |
| V24 | 3101 / 3102 | sltcnt | ignored | the true slot count |
| V25 | 3600 OpenShop | NPC id -> shop | any | one shop per shop NPC |
| V26 | 3601 ShopInventoryData | stock (ItemID, Buy, Sell) | any prices; item ids from game data [TODO] | curated list per shop |
| V27 | 3601 | SellMod | any float | 0.9 [inferred client default] (stub 1.0) |
| V28 | 3601 | ShopID | any non-zero u32 | stable id per shop |
| V29 | 3610 ShopBuy | purchase rules | any Result | fail when gold or space is short |
| V30 | 3620 ShopSell | sell price credited | not dictated | `Sell * SellMod` |
| V31 | 3910 / 3930 | send trade messages | client cannot clear a pending trade | never |
| V32 | 4000 ChatCommand | command set | anything | ignore, or a system chat line from ServerPerm |
| V33 | 2001 CreateMiniGameTable | capacity, refusal (0xDB) | any | one table per tavern slot |
| V34 | 2001 / 218 | msgprt/rnid allocation | unique u16/u8 pair per world | sequential |
| V35 | 217 MiniGameTableUpdate | chtid per table | non-zero; must be a published chat cell [inferred] | a dedicated cell per table |
| V36 | 217 + actions | game rules, timers, payouts | client renders any state (Dice computes payouts itself) | implement each game server-side |
| V37 | 216 MiniGameTableRemove | when tables close | any | when empty |
| V38 | 209 JoinTable | buy-in rules | any | enforce lmtmn..lmtmx and available gold |
| V39 | 222 Amount (cat. 5) | meaning of Amount | not visible client-side | move `amnt` gold into table credits |
| V40 | 303 MiniGameHand | hndval encoding | stored and displayed [TODO] | the server's hand-rank value |
| V41 | 2002 / 1006 | trigger for the second 1006 | any time after the UC transport left state 8 | the UC socket close |

### tincat3 managers

| Id | Message | Decision | Accepted range | Suggested default |
|---|---|---|---|---|
| T7 | 179 ChangeMOTD | honour admin MotD changes | nothing imposed | errorcode 1 unless admin |
| T10 | 163 / 164 | persist property writes | nothing imposed | persist per account, errorcode 0 |
| T11 | 147 | mailbox storage and retention | nothing imposed | persist per perm id |
| T12 | 147 / 149 | order of 149 records | arrival order; merged by id [inferred] | newest first |
| T13 | 147 | mails per list | no client limit known | cap at 100 |
| T14 | 149 | message_id | non-zero u32, unique per mailbox (0 rejected) | per-server counter from 1 |
| T15 | 149 | creation_time | any u32 [inferred] | Unix seconds |
| T16 | 149 | `data` | never read | empty |
| T17 | 149 | message_text encoding | bytes up to the first NUL | echo the sender's bytes |
| T18 | 149 | mails from ignored senders | the client auto-deletes them [inferred] | deliver anyway |
| T19 | 148 | persist read state | seen only via later 149 status | persist, report status 1 |
| T20 | 151 | hard vs soft delete | client does not care | hard delete |
| T21 | 150 -> 153 | AddResult `id` | unused by SADK [inferred] | new message_id |
| T22 | 150 | unknown recipient | errorcode != 0 shows a failure [inferred] | errorcode 1 |
| T23 | 150 | delivery to an online recipient | no push path; seen within 60 s [inferred] | store only |
| T24 | 56 | buddy persistence, one-way relations | nothing imposed | one-way list per perm id, persisted |
| T25 | 61 (ticket 0) | when to push presence | any time after login [inferred] | push on login (status 1) and logout (status 0) |
| T26 | 61 | status codes other than 3 | all = not on a server | 1 lobby, 0 offline, 3 in a game |
| T27 | 61 (ticket 0) | push for a non-buddy | adds them to the buddy map | push only for actual buddies |
| T28 | 98 / 99 | refusals | any non-zero errorcode; list unchanged [inferred] | errorcode 1, no limit below 100 |
| T29 | 98 | presence push after add | optional; entry starts offline | push one 61 (ticket 0) |
| T30 | 175 | `send_all` semantics | [guess] | if set, push one 61 per buddy after the AddResult |
| T31 | 157 | ignore persistence | nothing imposed | persist per perm id |
| T32 | 160 | perm_id_type / status / server fields | any | 2 / 0 / 0 / None |
| T33 | 154 / 155 | refusals | any non-zero errorcode | refuse self |
| T34 | 252 | `result` meaning | not interpreted by the client [guess] | store as received |
| T35 | 253 | `result_id` | any u32 [inferred] | stored result row id |
| T36 | 255 | `played` | ignored | the sum, for consistency |
| T37 | 256 / 257 | ranktable values, range base | not said by client code [guess] | 0 = all-time, 1-based inclusive |
| T38 | 257 | page size | no client limit [inferred] | <= 50 records |
| T39 | 53 | `selection` semantics | implied by the sender [inferred] | match on the non-empty key |
| T40 | 59 | `password` | never read | None |
| T41 | 59 | `data` part sizes | must not exceed the blob | the stored account blob, or empty |
| T42 | 55 / 60 | several characters per account | N rows [inferred] | list every persisted character |
| T43 | 88 | property_mask bits other than 8 | [TODO] | apply only fields whose bit is set; 8 = mail |
| T45 | 72 | `selection` by id vs by name | [TODO] | match whichever of char_id / name is set |
| T46 | 72 | unknown name/id | no rows or errorcode != 0 both end the lookup [inferred] | no rows, errorcode 0 |
| T47 | 86 | character name rules | STRING 128 only [inferred] | unique per server, 3..32 characters |
| T48 | 86 | char_id allocation | non-zero, distinct [inferred] | store counter |
| T49 | 90 | property_mask bits | [TODO] | apply the fields sent |
| T50 | groups | group model | nothing imposed [inferred] | reject admin writes, empty lists |
| T51 | guilds | guild support | nothing imposed | no guilds (guild_id 0, empty lists) |
| T52 | CD keys | key validation policy | server-side only | accept every key, keypool 0..255 |
| T53 | machines | — | — | empty lists / errorcode 1 |
| T54 | 181 | server info values | free | patchlevel 9212 |
| T55 | 182 | push cadence | free | none |
| T56 | 173 / 174 | statistics connection | — | Result(42) errorcode 1 (no statistics server) |
| T57 | 194 | username, user_access for a joiner | any | joiner's account name, access 0 |
| T58 | cyclic admin | run cyclic announcements | game ignores the callback; 13 may surface as chat [inferred] | none |
| T59 | broker | broker support | nothing imposed | none (errorcode 1) |

## Where the stub differs from the client

The stub (`sadk_lobby/`) is unchanged by this catalog. Rows marked "not implemented" are messages
the client handles and the stub ignores or only logs.

| Message | What the stub does | What the client needs | Impact | Address |
|---|---|---|---|---|
| 259 RequestLeaveChannel | default NETMSG Result(42) on module 0x26B6 | CellManager tpl 11 StatusReply (or a relayed 42) on the CellManager ticket | the leave never completes on the client [inferred] | T 10016f10, T 10017640, T 10027080 |
| 30 WhisperChatMessage | relays message_id 30 to all of cell 1 | NETMSG 3 PrivateChatMessage to the target only (and an echo to the sender) | whispers are not delivered [inferred] | T 10017100, T 10017ba0, S 004810a0 |
| 2 on 0x26B6 / 107 / 108 / 165 | `_h_chat_message` relays NETMSG 2 as 165; 107/108 handlers | chat through CellManager cells only | dead path in both directions, no wire effect [inferred] | T 10023cc0 (no case 0xA5) |
| CellManager tpl 11 StatusReply | `chat.status_reply` packs result_id as u16 | result_id u32 (body 2 bytes longer) | result 0 works live; non-zero codes may deserialize wrongly [inferred] | T 1000ef30 case 11 |
| CellManager tpl 7 requestCreateCell | replies StatusReply(cell 3, ticket, 0) | success only by publishing the new cell (tpl 0); kind-3 StatusReply handles only 0x11 | the client never learns the channel was created [inferred] | T 10017210, T 10017640 |
| 204 AuthenticateUser | `decode_login_blob` looks for a clear CD key | 204 carries only a SHA-512 key hash | logging only [known] | T 1002b560, T 1002ba70 |
| 4 / 71 | `_h_request_login` / `_h_create_account` | never sent | unreachable code [inferred] | — |
| 206 AuthenticateServer | accepted like 204 | never sent; see L7 | none today [known] | T 10030fe0 |
| 207 SessionKey | cipher=None when the `twofish` module is missing | a decryptable cipher | login fails with OnError 0xCB (environment hazard) [known] | T 10023cc0 case 0xCF |
| 224 TANLogin | no handler; default Result(42) | 153 AddResult on the 0xE0 ticket | matters only if a server-id connection is opened with data [inferred] | T 10023460 |
| 172 DeregObserverServerList | default Result; observer kept until the socket closes | remove the observer | pushes continue to a client that stopped observing [inferred] | — |
| 170 GameServerData / 177 ChangeGameServer | sends max_spectators 0 and password_required False; 177 handler drops max_spectators, ai_players, cipher, hardcore | echo the host's 177 values | hosted games list as "0 + AI" occupied and never as protected [inferred] | S 0048da70 (disasm 0048db1b), T 10021040 |
| 169 RemoveServer | removes the game, never pushes 169 | push `169 {server_id, running 0, ticket 0}` to type-5 observers | other browsers keep stale rows [known] | T 10023cc0 case 0xa9, S 0046a5e0 |
| 189 AssignServer | unreachable `(5,1)` branch | — (no SAdK path sends 5/1) | none [inferred] | S 00468f60 |
| 0xDB6 RegisterGame | reads only GameID; docstring describes u32-length strings | MSB-first bitstream, u8 strings, 1-bit bool | no wire effect today [known] | S 00479840 |
| 0xDC0 FinishGame | logs, no reply | 0xDC1 then 0xDC2 | what the client blocks on is [TODO] | S 00479c40, S 0047a810, S 0047a9c0 |
| 0xDD4 GiveUpGame | logs, no reply | 0xDD5 with the request's GameID, Result 0..20 | client stays on "Finalizing" [known] | S 00479ab0, S 0047ae80 |
| 0xDAC ClaimChest | logs, no reply | 0xDAD Result 0, then 0xDAE | chest claim never resolves [inferred] | S 00479670, S 00479fb0 |
| 1001 AvatarData | named EntityCreate; sends location + style blocks only; never sends a 1001 for the recipient's own id | the original server sent each client its own 1001 [inferred]; whether the own avatar needs it for 3100-3201 `ownr` lookups is [TODO] | server-side item/stat updates for the own avatar may be dropped [TODO] | S 0046e1d0, S 004824b0 |
| 1002 AvatarLoggedIn | `config.VILLAGE_MSG_ENTITY_UPDATE = 1002 # (movement)` | 1002 is AvatarLoggedIn; movement is a repeated 1001 | comment only; the stub never sends 1002 | S 0046e390 |
| 1004 NPCData | body builder matches; disabled by `config.VILLAGE_NPCS_ENABLED = False`; comments call it "PlayerCreate" | NPCs sent after 1000 to each entrant | no NPCs in the world | S 0046f8c0, S 0047b5c0 |
| 2000 AvatarLocation | relays correctly; comment says "~3/s" | the client sends about 15/s at 60 fps | comment only | S 0051ace0 |
| 2002 LeaveVillageRequest | answers with two 1006 (correct); docstrings still call 0x27D2 a world-login request answered with 1000 | two 1006 {0xDEADBEEF} | comment only | S 0046bde0, S 0046ec50 |
| 3950 AvatarColorChange | logged and dropped | 3201 + a style 1001 to everyone (V15) | colour changes are not seen by others; gold not charged | S 0046c760 |
| 3200 / 3201 | not implemented | 3201 after any gold change | client-side gold checks drift [inferred] | S 0046c940, S 0046c9c0 |
| 3001 / 3002 | logged and dropped | an item update (3101/3102) | item moves and deletes never take effect | S 0046bec0, S 0046bff0 |
| 3100 / 3101 / 3102 | not implemented | item state for the owner | inventory and equipment never update | S 0046e660, S 0046e6f0, S 0046e780 |
| 3600 OpenShop / 3601 ShopInventoryData | no branch for 0x2E10; 0xE11 body exists and is described as server-pushed | 0xE11 as the reply to 0xE10 with the same NPCID | no shop opens; a live click put nothing on the wire, cause [TODO] | S 0046ddf0, S 004706b0, S 0047b200 |
| 3601 SellMod | 1.0 | any float | 0.9 is the client default [inferred] | S 004706b0 |
| 3610 / 3620 and 3611 / 3621 | logged and dropped / not implemented | 0xE1B / 0xE25 plus 3102 and 3201 | buying and selling do nothing | S 0046c400, S 0046c510, S 00470990, S 00470a10 |
| 4000 ChatCommand | logged and dropped | nothing required | none | S 0046cbf0 |
| Minigames (2001, 209, 204, 222, 220, 221, 300-302, 400-403; 216-220, 303) | client actions logged and dropped; server messages not implemented | the table protocol (0xDA, 0xD9, 0xD8, 0xDB, 0xDC, 0x12F) | no minigames | S 0046cf20, S 0046f380, S 00471720 |
| 150 AddPrivateMessage | default Result(42) | AddResult(153) | the first send leaks the ticket; all later mail sends and the PostOffice queue stall [known] | T 1002677c entry 0x96 -> T 10028fc0 |
| 175 / 176 buddy observers | Result(42) | AddResult(153) | ticket leak only; SADK does not send them [inferred] | T 1002677c |
| 147 / 149 | Result only (empty mailbox) | 149 records with `message_text` before the Result once mail exists | correct for an empty mailbox; stored mail would never show | T 10028d80, T 10028a30 |
| 162 PropertyData | value 0 | any value <= 1000 | passes; the binary-derived default is 1000 | S 00464e70 |
| 61 UserBuddyConn | no presence pushes | 61 with ticket 0 on presence changes | buddies always show offline | S 00476f90 |

## Corrections to existing docs

Contradictions between this catalog and `docs/LOBBY_PROTOCOL.md`, `docs/NCOMM_GAME_PROTOCOL.md` and
`CLAUDE.md`. This is a report only; those files are not edited here.

### Encoding

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.1: LBOOL is a 4-byte uint32 | LBOOL is **1 byte** on the wire | T 10011490 GetMaxLength returns 1 for type 14; T 10013100 stores one byte; stub `tincat.py` writes 1 byte live |
| LOBBY_PROTOCOL.md §3.1: `STRING N` is a fixed char[N] buffer | u32 LE length (including the NUL) followed by the bytes, clamped to N on receive | T 100112b0 / T 100110e0 |
| LOBBY_PROTOCOL.md §3.1 and CLAUDE.md "chat payload magic 0x0062" | 0x0062 is the TinCat module id of the CellManager, followed by msgType 0 and a template id (0..11). It is not a separate NETMSG payload magic. The UC connection's login and channel requests (188/211/213/17/259) use module 0x26B6 | T 1000cde0 / T 1000ef30 |
| CLAUDE.md "LobbyMessage field scalars are BIG-endian" | The fields are an MSB-first bitstream. 32-bit values read as big-endian only when byte-aligned; strings are u8-length-prefixed, raw buffers have no length, bools are 1 bit. In RegisterGame 0xDB6 every field after RankedGame is 1 bit off byte alignment. Reads through vtbl+0x40 byte-reverse 32 bits: ShopInventoryData 0xE11 `SellMod` is a little-endian float inside the stream | S 00479840, WriteBits S 0048ef70, WriteBool S 0048f3c0, S 0048ff50, S 004706b0 |
| LOBBY_PROTOCOL.md §3.7 / §3.6: `keypool` in 120 CdKeyData and 159 UserKeyConn is UNSHORT | still UNSHORT on the wire, but the client reads it with the byte accessor, so values must stay below 256 | T 10023cc0 @10025d3b, vtbl+0x5c |

### Login and connections

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.3 / §6 and CLAUDE.md "auth ... completing on 153 AddResult" | On the main lobby connection login completes on **207 SessionKey** (state 7 -> 8, OnConnected). 153 completes only the token login on the UC connection and on the server-id connections (village, referee) after 213 | T 10023cc0 case 0xCF; T 10027080; T 10023460 |
| LOBBY_PROTOCOL.md §3.3: 202 is "server ECDH public key, both derive, session key = SHA-512 XOR-folded" | 202 is an `ecc_encrypt_key` blob {hash OID, server ephemeral P-521 key, server-chosen secret XOR hash(ECDH)}; the client decrypts it with DecryptSharedSecret | T 1002ade0; T 10023cc0 case 0xCA |
| LOBBY_PROTOCOL.md §3.3 / §6: "plaintext fallback 4 RequestLogin -> 42 -> 207" | The client has no builder for NETMSG 4 or 71. Every connection starts with 188; the lobby login is 188 -> 201 -> 203/204 -> 207 only | T 10023bf0 |
| LOBBY_PROTOCOL.md §1 / §5: "patchlevel 9212 ... enforced via 183 CheckLevel / 188 CheckVersion" | 188 carries the constant version 27 and no patch level. The lobby-side version gate is PropertyData(162) kategory 1 / index 1 compared with `[LobbyClient] ProtocolVersion` (default 1000). No login-path writer of `patchlevel` exists; 183 has no sender | T 10023bf0 (SetSISHORT "version" 0x1b); S 00464e70; S 0087aed8 |
| LOBBY_PROTOCOL.md §3.17: properties are a general store for resources/XP/unlocks | The only SADK caller is the login version check PropertyGet(1, 1). The value must be <= the client ProtocolVersion (1000 live), compared as signed, or the client disconnects with error 62 | RequestProperty S 0048ecb0, single caller S 00464f31; S 00464e70 |
| CLAUDE.md "Ports: ... 5479 world" and LOBBY_PROTOCOL.md §1 table / §3.2 / §3.21 (":5479 sub-protocol") | The village connection dials the ip:port the server returns in ConnectionData(222); network.ini gamePort is not used for it. The stub currently serves the village on `config.WORLD_PORT` = 5477 | T 10023cc0 (fills host/port); `ConnectionReal::Connect` T 100309d0 |
| LOBBY_PROTOCOL.md §6 item 4: "MOTD ... Result (42)" | 105 RequestMOTD is completed only by 106 MOTD; a Result(42) on the 105 ticket is ignored | no 0x69 case in the Result table T 10026680; 106 at T 10023cc0 case 0x6a -> T 100292c0 |

### Chat

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.5: 240-251 UC* messages, 107/108, 165 Chat | 240-251 are not used: no builder, and neither T 10027080 nor the CellManager handles them. 107/108 have no client builder. 165 is dropped by HandlerLobby (no case 0xA5). Chat runs through the CellManager (module 0x62) carrying NETMSG 2/3/5/6/17/30/76/259 | T 10027080; T 1000ef30; T 10023cc0 |
| LOBBY_PROTOCOL.md §3.15 / §3.18: admin cyclic messages and broker messages on the lobby connection | Admin cyclic messages (10, 11, 13, 14, 15) and broker messages (34-47) travel through the CellManager relay on the UC/chat connection. 46 BrokerSoldNotification, 40/41 and 8/9/12/32/33 are neither sent nor handled by the client | ChatChannelManager::HandleCellMessage T 10017ba0 |

### Hosting, referee and ranking

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.11: "189 AssignServer -> server replies 192 [PROVEN]" | The SAdK 189 for the game is the referee request (4, 4), completed by a 170 GameServerData on the category-0x108 ticket. 192 is the separate UC dial (189 type 2) | S 00468f60; T 10021520 -> S 00469ad0 |
| LOBBY_PROTOCOL.md §3.11 host flow: 168 with "port 5479" | The client sends 168 with `ip` unset and `port` = the NComm game port. The completion is AddResult(153){id}, consumed by CreateResultReceived; a non-zero errorcode shuts the host network down | S 0046aaa0 / T 10020ca0; S 0046a6a0 |
| LOBBY_PROTOCOL.md §3.11 join flow | A joiner reaches a hosted game by dialling the 170 descriptor ip/port directly. 221/222 address server-id connections (village world, referee). 223/224 TAN is not on the SAdK join path (TANConnectionGranted only logs) | GameServerInfo::JoinGame S 0048d030; T 10021420 / T 10023af0; S 00469d20 |
| LOBBY_PROTOCOL.md §3.11 ServerDataBlock note | For village descriptors, 170 `running` (desc+0x4c) is the add/remove opcode: running == 1 is required to add an unknown id, running == 0 removes a known one. For games it is ignored | S 0046a440 |
| LOBBY_PROTOCOL.md §3.11 occupancy | The game browser's occupied count is max_spectators + ai_players; cur_players is not read for games. 177 property_mask and 168 automatic_join are never written by the client | S 0048da70 (disasm 0048db1b); T 10021040; T 10020ca0 |
| LOBBY_PROTOCOL.md §3.19: ranking messages 252-257 on the lobby connection | They use a separate ranking-server connection, opened when AssignServer type 4 / subtype 5 is answered, and are received by HandlerStatSurf | RankingManager T 10029a00 -> ConnectRankingServer T 10029a20; T 100268e0 |
| LOBBY_PROTOCOL.md §3.19 / §7: rankdata (257) layout [TODO] | Each of the `count` records is u32, u32, NUL-terminated nick, then u32 points, won, lost, tie, disconnected. `played` is derived and there is no bounds check. In 255, `played` is not read | OnReceiveRankRange T 10029d50; HandlerStatSurf T 100268e0 |
| NCOMM_GAME_PROTOCOL.md event table | Several NComm ids are mislabelled: 0x30003 = GameInformation, 0x30004 = GameLoaded, 0x30005 = StartGame, 0x3000b = UserLeft, 0x3000f = NE_PreGame_HostReconnectRestartAndSendGameInformation | switch in S 0040e560; senders S 00413ae0, S 00408e50, S 0040ff90; event-name map S 00421bd0 |

### Mail and other tincat3 messages

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.14: 149 PrivateMessage `data` | `data` is never read; `message_text` is read twice instead | HandlerLobby T 10023cc0, push operands at 10024e8a / 10024edc |
| LOBBY_PROTOCOL.md §3.14: 150 AddPrivateMessage completion | 150 must be completed with AddResult(153), not Result(42) | AddResult table T 1002677c, entry 0x96 -> T 10028fc0 |
| LOBBY_PROTOCOL.md §3.20: 261 CheckPlayerOnServerAndGetInfosReply | 261 has no receive case on the lobby connection, so the client drops it and its callback is never invoked from the wire | HandlerLobby T 10023cc0 case list; callback T 10021700 |

### Village

| Existing text | Correction | Settled by |
|---|---|---|
| LOBBY_PROTOCOL.md §3.2 / §3.21: 1001-1006 as an unspecified [TODO] set | The binary fixes all of them (dispatcher S 00470a90). 1002 is AvatarLoggedIn, not an update/movement message; 1006 WorldLoginAck is the logout trigger, not a render gate | S 00470a90; S 0046e390; S 0046ec50 |
