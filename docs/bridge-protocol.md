# Host bridge protocol

Makes a hosted game joinable when the host cannot accept incoming connections. Two parts:

- **Client** — the mod `mods/gamebridge`, loaded by the shim (`bridge/wsock32_shim/`, a proxy `wsock32.dll`
  placed next to `SADK.exe`). It hooks the shim's `connect`, `send`, `listen` and `closesocket` exports, which carry
  all of TinCat's sockets. Below, "the shim" means this client side.
- **Stub** — `sadk_lobby/bridge.py`.

Neither the game nor TinCat is modified. A client without the mod keeps working.

## Why a bridge is needed [known, static]

See `docs/message-catalog.md`, "Pre-game room → Reachability":

- The host's match transport is a TinCat server, and a TinCat server cannot dial out.
- Joiners dial the ip:port of the game's 170 descriptor directly (`GameServerInfo::JoinGame` S 0048d030).
- Nothing in the client opens NAT: no UPnP, and no hole punching (UDP is LAN broadcast only).

So without a forwarded game port, a host cannot be joined.

## Facts the design rests on [known, static]

| Fact | Evidence |
|---|---|
| tincat3 imports every socket call from `WSOCK32.dll` by ordinal; `SADK.exe` uses `WS2_32.dll` itself | import tables |
| `WSOCK32.dll` is not a KnownDLL, so a copy next to the exe is loaded first | live 2026-10-07: the shim loaded, 74/74 exports resolved |
| The host's match server listens on `network.ini [Basics] gamePort` (default 5479) | `NComm_NetworkConfig_LoadFromIni` S 0041ede0; live: `listen` on 5479 when hosting |
| An accepted peer's address is only used for TinCat's own logs; the game never asks for it (`User_GetIP` and `IsLoopbackAddr127_0_0_1` have no callers) | `NET_WaitForNewConnection` T 100328f0; `KRNL_LogUser*`; TinCat API slots +0xb4 / +0x118 |
| Both TinCat connect paths go through `connect`, and TinCat never calls `getpeername` | `NET_Connect` T 10033310, `NET_Async_Connect` T 10032af0; import table |
| A TinCat client speaks first (`LOGMEON`), so a preamble line can precede it | kernel frame table |

## Messages

Every bridge connection starts with one ASCII line `SADKB1 <verb> ...\n`. TinCat frames start with the
bytes `EF FB BA DA`, so the two cannot be confused.

| Where | Line | Meaning |
|---|---|---|
| stub :7072 (`config.BRIDGE_PORT`) | `SADKB1 HELLO <token>` | the shim's control connection; `<token>` is 32 random hex digits per game start |
| stub :7072 | `SADKB1 DATA <token> <channel>` | a data channel the shim opened for one joiner |
| stub :7073 (`config.BRIDGE_RELAY_PORT`) | `SADKB1 JOIN <game id>` | a joiner, redirected there by its own shim |
| lobby :7070 | `SADKB1 LOBBY <token>` | tags the lobby connection; a 168 on it is paired with that token's bridge |
| client's game port | `SADKB1 PROBE <nonce>` | the stub's connect-back for the reachability test |

Control connection, after `HELLO`:

| Direction | Line | Meaning |
|---|---|---|
| stub → shim | `WELCOME relay=<port> vbase=<base> vip=<ip>` | relay port; bridged games are advertised at `vip : vbase + game id` |
| shim → stub | `CHECK <port> <nonce>` | connect back to me on `<port>` and send the nonce there |
| stub → shim | `CHECKED ok\|fail <nonce>` | informational; only the probe itself counts as success |
| shim → stub | `BRIDGED` | no probe arrived within 10 s: this client hosts only through the bridge |
| shim → stub | `HOSTING <port>` / `STOPPED` | the match server started listening / closed |
| stub → shim | `OPEN <channel>` | a joiner is waiting: open `DATA` and pipe it to `127.0.0.1:<host port>` |

## Flows

**Game start (mod `gamebridge`).**
1. Read `data\lobby\config\LobbySettings.ini [LobbyServer] Host/Port` and `data\game\settings\network.ini [Basics] gamePort`.
2. Connect to the lobby host's bridge port (`gamebridge.ini [Bridge] Port`, default 7072) and send `HELLO`.
   With no answer, the mod changes nothing.
3. Listen on the game port and send `CHECK`. With no matching `PROBE` within 10 s, send `BRIDGED`.
4. `gamebridge.ini [Bridge] ForceBridge = true` skips step 3 and sends `BRIDGED` at once.

**Hosting.**
1. The game's `connect` to the lobby is tagged with `LOBBY <token>`.
2. When the game sends 168, the stub looks the token up (`bridge.game_registered`).
3. If that client sent `BRIDGED`, the game's registry record gets ip = `ADVERTISED_IP` and port = `BRIDGE_VPORT_BASE + game id`. 170 and 222 both advertise that address.
4. A reachable host keeps its own address.

**Joining a bridged game.**
1. The joiner's `connect` to `vip : vbase + id` is redirected to `lobby host : relay port`, and its first `send` is preceded by `JOIN <id>`.
2. The stub assigns a channel and sends `OPEN <channel>` to the host's shim.
3. The host's shim connects `DATA <token> <channel>` to the stub and `127.0.0.1:<host port>` locally, then copies bytes both ways. TinCat's own traffic (still encrypted) passes untouched.
4. The joiner waits up to 10 s for the data channel.

## Limits and open points

- **Ports on the server:** it forwards 7072 and 7073 (TCP) once. The virtual ports are never listened on.
- **No player or game cap from the bridge:** one channel per joiner.
- **Joining a bridged game needs the shim.** A joiner without it dials the virtual port and fails.
- **The test listener occupies the game port for at most 10 s after start.** Hosting within that window would fail to bind; that isn't reachable in practice (login and the village come first).
- [TODO] Live: a bridged match end to end, including several joiners from `127.0.0.1`.
