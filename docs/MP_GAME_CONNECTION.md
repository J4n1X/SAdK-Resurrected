# MP Game Connection & Hosting Architecture (s39.5 RE verdict)

Read-only RE (Ghidra/offline decompile) of how a hosted game is created, listed, joined,
and how the pre-match room/slot state flows. This is the layer **after** the lobby
matchmaking we already implement. Addresses are **OLD-build VAs** (`decomp/sadk/SADK.exe.c`,
build 34688) unless a clean equivalent is given; logic + struct offsets transfer 1:1 to the
magazine build (`0x46Fxxx–0x470xxx` region: clean = old `+0x200`; `0x456xxx`: delta 0).

> ⚠️ The live Ghidra MCP was down during this RE, so it ran on the OLD offline export, whose
> `0x463xxx–0x470xxx` connection internals are partially gapped. The architecture is solid;
> the exact game-connection slot message IDs are the gap a **live capture** must fill.

## Verdict: lobby = pure matchmaker; the game room runs over a dedicated game connection

The lobby never carries room/slot state. It only: registers the host's game, lists it to
observers, and **assigns** the joiner a connection (an ip:port + nonce). The actual
pre-match room (map/settings/**6 player slots**) and the session run over a **separate,
dedicated game connection** the joiner opens to that ip:port.

### Host side — SetupGameDialog "Create"
- **`SetupSession` `FUN_004563c0`** (`.\LobbySetupGameDialog.cpp`) opens **no socket** and
  sends **no network**. **[PROVEN]** It validates the chosen map **locally**
  (`FUN_005ac7d0` → `"Map not found: '%s'"` / `"Mapnamen unterschiedlich"`) and fills the
  local **GameLoadDescriptor** at `*(*(System+0x3c)+0xffe4)`: map name via
  `GameLoadDescriptor_SetMapNameAndType` (`FUN_005aa130`) + a **6-iteration slot loop**
  (`FUN_00413290` idx 0..5; slot type `FUN_00415180` → 0/3=empty, 1=human, 2=AI). This is
  the host's own client-side match-world descriptor — the SAME build path as lobby-world entry.
- **`AddGameServer(168)` builder = tincat3 `GameServerManager::Create/Update @0x10021040`.**
  **[PROVEN]** Builds a PropertySet (factory type `0xb1`) with the msgdefs-168 fields
  (name/desc/max_players/max_spectators/ai_players/room_id/level/game_mode/hardcore/map/
  running/locked_config/data/cipher/ticket_id) and sends via `serverMgr->vtbl[0x30]`. **No
  `bind`/`listen`** here. 168 carries `ip`/`port` (`msgdefs.ini:1225`), so the host supplies
  an endpoint to the lobby — but whether it's the host's own listen port or lobby-overwritten
  was not isolable statically.

### Host listener — CAPABLE but not statically confirmed as wired
- tincat3 has a **full embedded game server**: `bind`+`listen(…,5)` (`FUN_100327a0`),
  `accept` (`FUN_100328f0`) inside the **"Server thread"** (`FUN_100026c0`, logs
  `"Server thread: running."`), activated by export
  `NetworkService_IncomingConnections_Start` (`FUN_1000a6a0` cmd `0xb`). Plus `Server game
  tick`, `LOGONACCEPTED`/`LOGOFFACCEPTED`, `CellManager Server: New Client connection`,
  `Broadcast_Server`. **[PROVEN capability]**
- BUT SADK creates exactly ONE comm layer and it's a **client** INet manager
  (`TinCat_CreateCommLayer(0,0x26b6,5,…)` → type 0 → `ConnectionManagerINet FUN_10030d50`),
  and **none of the tincat3 server-export name strings appear in SADK.exe** (it calls
  tincat3 by ordinal/vtable). No static host path activates the listener. → **host-listens =
  [HYPOTHESIS: no]; capability exists but is unproven-as-wired. Runtime capture decides.**

### Join side — a NEW, distinct GameServerConnection
- SADK has four `LobbyComm::*Connection` classes, all extending `LobbyComm::BaseConnection`
  (`.\LobbyBaseConnection.cpp`), each with its own vtable and **its own transport at `+0x34`**:
  `VillageServerConnection` (ctor `0x46ece0`, 1000-series lobby world),
  `UserCommConnection` (UC/chat), **`GameServerConnection`** (dtor `0x48e5d0`,
  `.\LobbyGameServerConnection.cpp` — the game session), and `RefereeServerConnection`
  (ctor `0x478bb0`, `.\LobbyRefereeServerConnection.cpp` — ranked arbiter). **[PROVEN]**
- The base dials via `*(this+0x34)→vtbl[0x10](serverHandle,0,…)` and sends via
  `vtbl[0x1c](msgType,data,len)` (confirmed in `RefereeServerConnection::Login FUN_00478d70`).
  **[PROVEN]** So join opens a **new** TinCat connection (a GameServerConnection) — NOT the
  VillageServerConnection path.
- **`ConnectionData(222)`** carries `perm_id, server_id, ip, port, nonce(MEMBLOCK), errorcode,
  …` (`msgdefs.ini:1551`): the **ip:port to dial + the nonce = the connection ticket**. The
  joiner's `BrowseGameDialog::Update FUN_00457af0` shows `"!Connecting to Game Server"` while
  `ServerList(+0x54)+0x9c ∈ {-1,-2}` (assign-pending sentinel); `ServerList::GameServerAssigned
  FUN_00469840` consumes the assigned server and fires `ServerList->vtbl[0xa0]`. **[PROVEN]**

### Room/slot state — over the game connection, not the lobby
- The browse record `GameServerInfo` (size `0x9c`) holds only flat advertised fields — **no
  per-slot occupant/tribe/team/color/ready array**. The lobby is matchmaking-only. **[PROVEN]**
- So after dialing the GameServerConnection, the joiner receives the room/config + 6-slot
  state **over that connection**, almost certainly the **same TinCat PropertySet messages as
  the 1000-series** (but dispatched by GameServerConnection, not VillageServerConnection's
  `HandleMessage FUN_00470890`). **[HYPOTHESIS — high confidence]** Exact slot/config message
  IDs = the capture gap.

## What the revival must provide (either P2P or dedicated)
1. **Lobby matchmaking** — global registry + `168` add / `177` change / `169` remove, `170
   subtype-1` list to observers, `221→222` returning **ip:port + nonce**. ✅ **Built in s39.5**
   (`sadk_lobby/registry.py` + dispatch; 222 already returns a 128-byte nonce).
2. **A game endpoint at that ip:port** the joiner's GameServerConnection can dial + log into
   (153-style ACK — the same base-connection login the stub already answers). ⏳ The one
   genuinely-new networking piece. The `config.GAME_CONN_VIA_STUB` lever points the joiner at
   the stub's `:5479` so the stub IS that endpoint (and captures the handshake).
3. **Room push over the game connection** — PropertySet messages carrying config + 6 slots →
   populate the room → ready-up → start → `EnterWorld`(match map) [reuses the s39 msg-1000
   push]. ⏳ Protocol unknown → **capture next**. Each push = its own Engagement Record.
4. **Referee endpoint** (`RegisterGame`/`FinishGame`/`ClaimChest`) — only if ranked play is in
   scope; not needed for basic unranked host+join+room.

## Decisive next step — read-only live join capture
With two clients (host `test`, join `test2`), `MULTI_CLIENT_HOSTING=True` + `GAME_CONN_VIA_STUB=True`:
1. Host: Create a game → confirm `AddGameServer(168)` reaches the stub (does Create actually emit 168?).
2. Joiner: Browse → see the game → Join → confirm `221→222`.
3. **The capture:** does the joiner open a NEW TCP connection to the 222 ip:port? Is it the
   host or the stub? (`netstat -ano` on the host for a LISTENING owner after Create answers
   host-listens yes/no.) Then **log the first frames on that game connection** — they are the
   room/slot/config PropertySet messages to implement. `tools/lobby_proxy.py` + the stub's own
   `sadk_captures/` + `tincat_server.log` capture it read-only.

---

## RESOLVED (s39.5) — live P2P join captured; the join transport + the kick are now PROVEN

A real join was captured direct, **joiner `192.168.1.134` → host VM `192.168.1.143:5478`**
(`capture_scoped.json`, decoded by `tools/decode_game_join.py` → `docs/GAME_JOIN_CAPTURE_decoded.txt`).
No stub in the path — pure P2P, exactly the architecture above.

**The game-session transport IS plain TinCat** — byte-identical framing to the lobby:
`magic 0xDABAFBEF | srcID | dstID | type | arg | len | crc32`, with `FROM_CLIENT=0xEFFFFFEE`,
`FROM_SERVER=0xEFFFFFCC`, type 3=handshake / 5=handshake-ack / 2=data. `sadk_lobby/tincat.py`
already parses it. Body message magics are a family: `0x0061` (user-list/group records),
`0x0062` (chat, already known), `0x0063`, and **`0x27d9`** (the game-logon — a `0x27Dx`
SendGameData sibling of the village `0x27d2`).

**Captured sequence (everything succeeds up to the kick):**
1. Joiner → type-3 LOGMEON (machine `user` / serial) → host → type-5 ack, assigns **ID 1**.
2. Host → `0x0061` user-list/group records (the room roster sync).
3. Joiner → **`0x27d9` game-logon**: build **34688** (`0x8780`), player name "Testler",
   static-data checksum **`0xe9f65088`**.
4. Host → **RST** (immediate).

**Why the RST — binary PROVEN** (`decomp/sadk/SADK.exe.c`, which IS build 34688 = the host's build):
the logon deserializes to internal message **`0x30001`**, built client-side at **line 12147**
(`version = FUN_0041f520()` = `BuildVersion DAT_0087ba6c`; `checksum = thunk_FUN_01bd0000()` =
the static-data checksum) and validated host-side in `.\Manager.cpp` `FUN_0040e720` at **line 14590**:

```
if (msg == 0x30001) {
    if (joiner.version  != host.BuildVersion)    kick "!VERSION MISMATCH"   // "kicked of version mismatch"
    if (joiner.checksum == host.staticChecksum)  { ...password... "Player joined game" }  // SUCCESS
    else                                         kick "!CHECKSUM MISMATCH"  // "kicked of static data checksum mismatch"
}
```

The version matched (both 34688) → it takes the **checksum** branch = the German
*"Prüfsumme stimmt nicht überein"* dialog. **Conclusion: same build, DIFFERENT static-data files
on the two installs.**

### What this means
- **The stub/protocol side of host+join is DONE and proven**: advertise (`168`/`177` + the new
  observer-push `dispatch._push_to_obs`) → joiner discovers → P2P dial straight from the `170`
  (game join needs **no** `221`/`222` token; that path is village-only) → TinCat handshake →
  host accepts → logon. The only failure is the host's local data-integrity check.
- **The fix is ENVIRONMENTAL, not code**: make both machines' game data identical (same build +
  same `data` dir). The stub cannot and must not bypass this — defeating the host's checksum
  would be a host binary patch (forbidden mutation, not a genuine fix). Cheap confirm: hash-compare
  the two installs' data directories.
