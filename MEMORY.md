# MEMORY.md — compact persistent context

Start here after `CLAUDE.md` + `HARNESS.md`. This is the short, durable state of the
project: proven facts and open TODOs. Keep it honest — `[PROVEN]` = binary address +
live evidence; everything else is `[TODO]`/`[HYPOTHESIS]` and labelled.

---

## What works `[PROVEN]`

- **Login.** ECDH secp521r1 → SHA-512/XOR shared secret → Twofish-CTR credentials →
  SessionKey(207) perm_id → completes on **153 AddResult** (NOT 214; the UC-login
  client state machine has no 214 handler — jump-table bound 0xAA).
- **Transport.** TinCat 28-byte header; one comm layer, lobby magic **0x26B6**, chat
  magic **0x0062**. `msgdefs.ini`-driven codec encodes/decodes ~150 NETMSG types.
- **Server browser.** `GameServerData(170)` ServerInfoOld layout. A village entry is
  joinable iff its `ServerDataBlock` (the 170 `data` MEMBLOCK) carries
  `roomId` (BIG-ENDIAN u32 + 1 pending byte) equal to the client's ProtocolVersion
  `DAT_0087aed8` (live value 1000 → `config.LOBBY_PROTOCOL_VERSION`). `AssignServer(189)`
  → `UsercommServerData(192)` points the client at the UC server (:7071).
- **World entry.** Leaving char-select into the 3D world is driven by the SERVER
  pushing inbound **EnterWorld msg 1000**. The user's "Betrete Welt" click sends no
  network; the client parks at LobbyManager **EnteringVillage(8)** awaiting 1000.
  `HandleEnterWorld` calls `SetState(VillageEntered=9)` first, then the world renders
  (screenshot-confirmed once on the clean build). 1000 MUST ride a **SendGameData(74)**
  envelope — the only framing the inbound bridge routes to
  `VillageServerConnection::HandleMessage`; a bare 1000 frame is dropped.
- **Multi-client.** Two+ clients log in as distinct players (lobby resolves by auth
  username, UC/village by the token perm_id); hosted games live in a process-global
  registry so one client's game is visible/joinable to another. This is the default.

## Open TODOs

- **In-world protocol `[TODO]`.** Everything after EnterWorld (WorldLoginAck 1006,
  PingCode/Pong, WorldTick 1005) was derived on the faulty no-CD build and is
  UNVERIFIED on the clean build. The world renders at `SetState(9)` WITHOUT 1006, so
  1006 is NOT confirmed as a render gate. The stub answers these as best-effort
  replies to client-driven messages; re-confirm live before trusting any of it.
- **Hosting / pre-game room `[TODO]`.** The SetupGame dialog opens but slots are
  empty. The per-slot room protocol (occupant/tribe/team/color/ready) is unreversed —
  it rides the game connection, not a NETMSG. The game-join session uses its own
  framing (capture in `docs/GAME_JOIN_CAPTURE_decoded.txt`).
- **Entering matches / referee `[TODO]`.** Entering matches is **broken**, and what
  the referee/match-arbiter actually does is **unclear**. The referee subsystem was
  **removed from the stub source** (it was flag-gated, unproven, and never cleared the
  match-start abort in testing). If restarting this work: some referee functions are
  **already named** in `docs/REFEREE_FUNCTIONS_TO_NAME.md` — use that as the starting
  point. Do the RE through the Ghidra MCP (HARNESS §1).
- **In-world content `[TODO]`.** The rendered world is empty (no NPCs/entities; avatar
  shows `<UNNAMED>`). Not implemented.

### RE-quality / tooling TODOs (per `HARNESS.md §6` / `decomp/RE_PRACTICES.md`)

- **Retro-typing sweep `[TODO]`.** Every function/struct we have *ever* named still
  carries tons of untyped locals/params. Do a pass to type them properly (and set the
  right calling convention), per the RE practices. Large; do it incrementally + as a
  dedicated sweep.
- **On-demand C-export script `[TODO]`.** Stand up a Ghidra script (run **via the MCP**)
  that re-exports the decompiled C source dumps on request, so an agent can refresh them
  instead of relying on stale offline copies.
- **Symbol-map audit `[TODO]`.** Verify `decomp/RENAME_LIST.md` + `docs/SOURCEMAP.md`
  actually match the current Ghidra project. The map must be kept current at all times.
- **Doc-sufficiency review `[TODO]`.** We purged a lot of stale/referee/narrative docs.
  Review what remains to confirm it provides *sufficient* information — and validate it
  live against Ghidra in the next session rather than assuming the survivors are correct.

## Address-base caveat

Function addresses in the docs come from a pre-magazine (no-CD/dump) build base and
can differ from the clean magazine build (e.g. `HandleEnterWorld` is 0x46f470 in the
dump base, 0x46f670 in the clean build). They identify the LOGIC; confirm exact
addresses against the loaded program via the Ghidra MCP.

## Working method reminders

- All RE/debugging through the **Ghidra MCP**; no standalone RE/memory/patch scripts.
- The stub's wire behaviour is byte-exact; `msgdefs.ini` is authoritative.
- Working features are the default — no flags. No hacks/bypasses without permission.
