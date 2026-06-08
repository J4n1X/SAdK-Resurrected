# Session 39.5 — Intermediary Planning: Game Hosting Implementation

_Date: 2026-06-08 (intermediary session between s39 and s40)_

---

## Context & Review of Prior Sessions

### Where we are now (end of s39)

| Milestone | Status |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list | ✅ working |
| Room-assign → "Suche Server" button lit + clickable | ✅ working |
| Village-enter → 3D lobby world renders | ✅ working (ARM_ENTER_WORLD=True, s39 live-confirmed) |
| Win11 x64 via debugger_loader.py | ✅ working |
| No-CD `je` patch identified + fix ready | ✅ (s38, engagement record staged) |
| Server browser — village list populates + Enter enables | ✅ working (s15/s28) |
| Server browser — GAME list (BrowseGameDialog, subtype-1) | ✅ implemented, awaiting live test (s39, ER staged) |
| Token handshake (211→212→213→153 ACK) | ✅ working |
| **Game HOSTING (create + join + play)** | ❌ **NOT IMPLEMENTED — the next frontier** |

### Key sessions that got us here

- **s15** — Room-assign solved: 170 `data` blob (ServerDataBlock, BE u32 roomId + pending byte)
- **s29–s33** — World-entry flow: village conn login, EnterWorld(1000) on SendGameData(74) envelope, DRM crash solved
- **s38** — No-CD `je` patch; game-server browser RE (GameServerInfo fill @0x48da70, no ServerDataBlock needed)
- **s39** — Server browser engagement record (subtype-1 → game list); EnterWorld push live-confirmed (state 8→9)

---

## ★ ABSOLUTE PRIORITY: Game Hosting Implementation

### What "hosting a game" means in this protocol

The original SAdK multiplayer flow (from the client's perspective):

1. **Host creates a game** → client sends `AddGameServer(168)` to the lobby → lobby stores it, acks with `StatusWithId(153)` returning the new server_id
2. **Lobby advertises the game** → other clients' `RequestServers(166)` / `RegObserverServerList(171)` get the hosted game as a `GameServerData(170)` with `server_subtype=1`
3. **Joiner selects + joins** → joiner clicks Join in BrowseGameDialog → client sends `RequestConnectionData(221)` with the server_id → lobby replies `ConnectionData(222)` with the host's IP/port
4. **Joiner connects to the host** (or to a dedicated game server) → a new TinCat connection opens (the "game server connection"), login handshake, then the game-session protocol (map load, player sync, start)

### What we already have

- ✅ `AddGameServer(168)` handler — stores the game in `conn.servers` per-connection, acks with 153+server_id
- ✅ `RemoveServer(169)` handler — removes from per-connection store
- ✅ `ChangeGameServer(177)` handler — updates fields
- ✅ `RequestConnectionData(221)` handler — replies 222 with the server's IP/port
- ✅ `RequestServers(166)` / `RegObserverServerList(171)` — lists servers including user-created ones
- ✅ Server browser game-list population (subtype-1, pending live test)
- ✅ Village conn login (188/211/213→153) — same flow reusable for game conn

### What's MISSING for functional game hosting

---

## Implementation Plan — Phases

### Phase 1: Multi-client server store (CRITICAL)

**Problem:** `conn.servers` is per-connection — a game created by client A is invisible to client B's `RequestServers`. The lobby must maintain a **global** game registry.

**Tasks:**
- [ ] Create a shared `GameRegistry` (thread-safe dict) in a new module or in `server.py`
- [ ] `AddGameServer(168)` → register in global store (keyed by server_id), tag with owner conn
- [ ] `RemoveServer(169)` → remove from global store
- [ ] `ChangeGameServer(177)` → update in global store
- [ ] `RequestServers(166)` / `RegObserverServerList(171)` → query global store (not just `conn.servers`)
- [ ] On connection drop: remove all servers owned by that connection (cleanup)
- [ ] `RequestConnectionData(221)` → look up in global store (any conn's server)

### Phase 2: Multi-client support (CRITICAL)

**Problem:** The stub assumes a single `test` user. Hosting requires ≥2 clients with distinct identities.

**Tasks:**
- [ ] Support multiple simultaneous connections with unique `perm_id` / `char_id` / `char_name`
- [ ] Auto-assign perm_id per new login (or accept any username as valid)
- [ ] Track which connection owns which character (for player-count updates, observer notifications)

### Phase 3: Server-list observer notifications (IMPORTANT)

**Problem:** When a host creates/removes/updates a game, other connected clients (observers) need to be notified in real-time with a pushed `GameServerData(170)`.

**Tasks:**
- [ ] Track observer registrations (`RegObserverServerList(171)` with `send_all`)
- [ ] On `AddGameServer` / `ChangeGameServer` / `RemoveServer`: push `170` to all observers of that `server_type`
- [ ] Handle the `opCode` field in 170 (1=add/update, 0=remove) for the routing at `AddOrUpdateDescriptor`

### Phase 4: Game connection (the join path) (IMPORTANT)

**Problem:** When a joiner gets `ConnectionData(222)` and dials the host's IP:port, what answers? In original SAdK, it was the host's game instance acting as a P2P server. In our revival, we need to decide the architecture:

**Option A — Relay/proxy (simplest for revival):**
- The lobby stub itself acts as the "game server" on a per-game port (or multiplexes on WORLD_PORT)
- Both host and joiner connect to the stub; the stub relays game-session messages between them
- Advantage: no NAT traversal needed; works over internet
- Disadvantage: more complex stub; latency

**Option B — P2P (original architecture):**
- The host's client IS the game server (the original design)
- The lobby just hands out the host's IP:port in `222`
- Advantage: faithful to original; simpler stub
- Disadvantage: NAT traversal; requires the host's game to actually listen (does it?)

**Decision needed (for the user):** Which architecture? The engagement records suggest the host's IP is stored in `AddGameServer(168)` `ip` field — the original protocol expected P2P. **Recommend starting with Option B** (P2P, original flow) since:
- The client likely already has the game-server listener built in (it's a 2008 LAN game)
- `AddGameServer(168)` already stores the host's IP
- `ConnectionData(222)` already returns it to the joiner
- We just need to confirm the host opens a listener + what handshake it expects

**Tasks:**
- [ ] **RE task:** Determine whether the hosting client opens a TCP listener after `AddGameServer` succeeds (check for `bind`/`listen` calls in the game's MP hosting path)
- [ ] **RE task:** Capture the game-session handshake between host and joiner (what messages flow after the TinCat connection is established?)
- [ ] Ensure `ConnectionData(222)` returns the host's ACTUAL IP (not always `ADVERTISED_IP`)
- [ ] Handle the case where both clients are on the same LAN vs. over internet

### Phase 5: Game-session protocol (THE BIG ONE — post-hosting)

Once two clients can connect, the game-session protocol handles:
- Map selection / validation
- Ready-up / game start
- In-game state sync (units, buildings, resources, combat)
- Game end / disconnect

This is the largest RE task remaining but is **downstream** of getting the hosting connection working.

---

## Recommended Attack Order for s40

1. **Phase 1** first (global game registry) — it's pure Python, no RE needed, unblocks everything
2. **Phase 2** (multi-client) — enables actual testing with 2 clients
3. **Phase 3** (observer push) — makes the browser feel live
4. **Phase 4** (game connection) — the RE-heavy part; needs live capture of a host↔joiner exchange

### Quick wins for s40 (can be done without RE):
- [ ] Global game registry (Phase 1)
- [ ] Multi-client identity (Phase 2, basic version — assign sequential perm_ids)
- [ ] Fix `_send_server_list` to query global registry

### RE tasks for s40 (need live game):
- [ ] Confirm the hosting client opens a listener (BP on `listen`/`bind` after AddGameServer)
- [ ] Capture the joiner's connection to the host — what TinCat frames flow?
- [ ] Determine if the game conn uses the same 0x26B6 magic or a different comm-layer

---

## Open Questions for the Maintainer

1. **P2P vs relay?** The original game was LAN — did hosts open a listener? (Strong yes based on the `ip`/`port` fields in 168.) Should we preserve that or build a relay for internet play?
2. **Port allocation:** Does the host use a fixed port (5479? configurable?) or does it tell the lobby which port it's listening on via `AddGameServer(168).port`?
3. **Do we have a second machine / VM available for 2-client testing?** (Note: `-localhostmode` is a known dead end per CLAUDE.md — two separate machines/VMs are needed.)
4. **Priority within hosting:** Get the browser + join working first (Phase 1–3), or jump straight to the game-session capture (Phase 4)?

---

## Files likely to be modified

| File | Changes |
|---|---|
| `sadk_lobby/server.py` | Global game registry; multi-client tracking |
| `sadk_lobby/dispatch.py` | Rewrite server handlers to use global registry; observer push |
| `sadk_lobby/connection.py` | Per-client identity; cleanup on disconnect |
| `sadk_lobby/config.py` | Multi-user config (remove single-user assumption) |
| NEW: `sadk_lobby/registry.py` | Shared game registry module |
| NEW: `sadk_lobby/game_session.py` | Game-session connection handler (Phase 4+) |

---

## Success Criteria

- **Minimum viable:** Two clients can connect to the stub simultaneously, one hosts a game (`168`), the other sees it in BrowseGameDialog and can click Join → gets `ConnectionData(222)` with the host's IP.
- **Full hosting:** The joiner connects to the host (or relay), the game-session handshake completes, and both clients enter the map-selection / game-setup screen together.

---

## Implementation Log — s39.5 build (2026-06-08)

Built the **Phase 1 (global registry) + Phase 2 (multi-client identity)** scaffolding —
pure Python, no RE needed, default-OFF and harness-compliant. This unblocks two
clients connecting as distinct players and one hosting a game the other sees + joins.

### What landed (all default-OFF; single-client wire output byte-identical)

| File | Change |
|---|---|
| `sadk_lobby/players.py` (NEW) | `Player` + resolution: lobby conn by auth-blob `username`, UC/village by token `perm_id`; auto-registers unknown usernames. `PLAYERS[0]` == old hardcoded test identity. |
| `sadk_lobby/registry.py` (NEW) | Process-global, thread-safe game store keyed by globally-unique `server_id`, tagged with the owning conn; cross-client list/lookup; owner cleanup on disconnect. |
| `sadk_lobby/config.py` | `MULTI_CLIENT_HOSTING` (master gate), `PLAYERS` (test→perm 1, test2→perm 2), `GAME_CONN_VIA_STUB` (capture lever). |
| `sadk_lobby/dispatch.py` | Handlers read `conn.player` + route 168/169/177/221/166/171 through the registry when the flag is on; resolve identity at 204 (lobby) / 213 (UC/village). |
| `sadk_lobby/connection.py` | `conn.player` (defaults to test); drop owned games on disconnect. |
| `sadk_lobby/chat.py` | Chat user-info reflects `conn.player`. |
| `tests/test_multi_client.py` (NEW) | Proves resolution, cross-client visibility+join (221→222 with host address), owner cleanup, and flag-OFF isolation. All pass; golden stays byte-for-byte. |
| `engagement_records/2026-06-08_multi-client-hosting.md` (NEW) | ER for flipping the flag live (matchmaking + join-handoff scope). |

**Harness posture:** with the flags OFF the stub is byte-identical to before (golden +
server-browser tests pass). Flipping `MULTI_CLIENT_HOSTING` is a wire-behaviour change
→ covered by the ER above; flip it (with the user present) for the live 2-client test.

### Two-client test recipe (host + joiner)

1. In `sadk_lobby/config.py` set `MULTI_CLIENT_HOSTING = True` and `ADVERTISE_GAME_SERVERS = True`.
   (Optional, to capture the join handshake at the stub: also `GAME_CONN_VIA_STUB = True`.)
2. Run the stub: `python -m sadk_lobby`. Set `SADK_ADVERTISE_IP` to the stub's IP as seen
   from the client VMs if they aren't on loopback.
3. **Client A (host):** LobbySettings account `test`. Log in → SPIEL ERSTELLEN → pick a
   map → Create.  Watch the stub log for `AddGameServer: id=… owner=1 … [registry]`.
4. **Client B (joiner):** LobbySettings account `test2` (a 2nd machine/VM — two local
   instances is a known dead end). Log in → SPIEL SUCHEN. Expect B's BrowseGameDialog to
   **list A's game** (stub log: a `170` with A's name/map to conn #B). Select it → Beitreten.
5. Stub log shows B's `RequestConnectionData(221)` → `ConnectionData(222) → <addr>`. With
   `GAME_CONN_VIA_STUB`, `<addr>` is the stub, so the joiner's game connection lands on
   `:5479` and is captured (`sadk_captures/world_*.bin` + log).

**Success for THIS step** = two distinct identities, B sees A's game, B gets the join
address (+ the captured game-connection frames). The pre-match ROOM (map/settings/6
slots) opening populated is the **next layer** (see below) — not claimed by this step.

### The next layer (the real unknown): the game-room/slot protocol

The 6 player slots + room config are **not** any lobby NETMSG (verified across the whole
`msgdefs.ini`: 166–177 server-list, 240–251 UC channels, 252–262 ranking — none carry
slots). So the room/slot state rides the **direct host↔joiner game connection** (the
2008-LAN P2P design), like the 1000-series world protocol over `SendGameData(74)`. The
decisive next move is the **read-only join capture** above (what the joiner sends/receives
on the game connection).

A read-only Ghidra RE this session **confirmed the architecture** (verdict in
`docs/MP_GAME_CONNECTION.md`): the lobby is a **pure matchmaker**; on Join the client opens a
**new, distinct `LobbyComm::GameServerConnection`** (`.\LobbyGameServerConnection.cpp`) to the
**ip:port + nonce** from `ConnectionData(222)`; the room/6-slot state then flows over **that
game connection** as PropertySet messages (not any lobby NETMSG). The host's `SetupSession`
(`0x4563c0`) builds its own match world locally + registers via `168`; tincat3 is fully
server-capable but SADK calls it by ordinal, so whether the host opens a listener is the one
thing only a **runtime capture** can settle. The `config.GAME_CONN_VIA_STUB` lever makes the
stub the game endpoint the joiner dials, so that capture lands at the stub. Any room-push is a
separate, ER-gated change.
