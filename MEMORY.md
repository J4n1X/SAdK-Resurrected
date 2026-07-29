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
  **World-entry DIAL `[PROVEN 2026-06-13]`:** "Betrete Welt" → `LobbyVillageEnterAction_Trigger` →
  `CreateVillageServerConnection@0x463850` (resolve the selected village desc via the ConnectionManager) →
  `VillageServerConnection::OpenUserComm@0x470d50` (vtbl+0x3c). OpenUserComm **reuses the single
  `UserCommConnection`** (`LobbyManager_GetUserCommConnection`, `LM+0x3d8`) and calls
  `UserCommConnection::OpenCommunication(serverHandle)` — it does NOT spin up an independent socket class.
  On failure it fires connection-event `0x91` and logs **`"Can't login to UserComm!"`** → base
  `LobbyBaseConnection::OnLoginFailed@0x48e170` → screen shows **`!LOGIN_FAILED_TEXT`** ("Loginversuch
  fehlgeschlagen"). So a world-entry login failure means the UC-conn re-open to the village server handle
  failed — check the village server-handle resolution + UC-conn state. (Diagnose live on Windows w/ the real
  `tincat_server.log`; the actual login success/fail verdict is decided inside tincat3, not the exe.)
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
  framing (capture in `docs/GAME_JOIN_CAPTURE_decoded.txt`). **Progress (2026-06-13):** the third LobbyManager
  connection `pGameSlotConnection@LM+0x544` is now **identified `[PROVEN]` = `LobbyComm::GameServerConnection`**
  (0x38B, vtbl `0x7deaf0`, ctor `GameServerConnection::ctor@0x48ed50`, from `LobbyGameServerConnection.cpp`).
  But its connection-dispatch handler `vtbl[0x24]` is the **shared no-op stub** (`Stub_NoOpReturnVoid@0x472360`),
  so the room protocol is **NOT** on `GameServerConnection::HandleMessage` — unlike the village conn whose
  `vtbl[0x24]`=`HandleMessage` carries the world protocol. The 3 peer conns (village/gameslot/referee) are
  routed by `LobbyManager::DispatchInboundToConnection@0x462760`. **Redirect `[PROVEN 2026-06-13]`:** the room layer is the
  **village/world conn's** observer+message system (`LM+0x540`), not the game-slot conn — its join-failure
  events are `!MINIGAME_NOTABLELEFT`/`_NOPLAYERSLOTLEFT` (a game is a *table* with *player slots*). All 10
  game-screen observer callbacks are now recovered+named (see `docs/MATCH_START.md`). **Slot DATA model
  mapped `[PROVEN]`:** the SetupGame room is a **6-slot array in the NComm game-session object**
  (`NComm_GetSlotDataPtr(obj,i)=obj+0x10+i*0x4c@0x413100`; `NCommGameSlot`=0x4c B with ownerGuid@+0xd,
  name@+0x1e, kind@+0x3b {0 empty/1 human/2 AI/3 closed}, aiLevel@+0x3c, tribe/color/team bytes @+0x3d-0x3f).
  Match-start reader `…FillMpDescriptor@0x4562d0`; slot accessors named `NComm_Slot_Get*/Set*`. **WIRE PROTOCOL
  MAPPED `[PROVEN]` 2026-06-13 → full ref `docs/NCOMM_GAME_PROTOCOL.md`:** the room/game protocol is the **NComm
  P2P event system**, dispatched by `Manager_HandleNCommEvent@0x40e560`: `0x30001` join (host validates
  version/checksum/pw/MD5→assign slot→broadcast) · `0x30002` slot-config (tribe@+0x3d / color@+0x3e *unique-swap* /
  team@+0x3f / index@+0x3a, staged from `Mgr+0x24/2c/28/30`) · `0x3000a` leave · `0x3000b` host room-broadcast
  (clients apply) · `0x30011` ready · `0x30012` start-loading (sets `Mgr+0x3cc=1` → arms referee). NComm
  Manager=`DAT_00885754`, game object embedded @`Mgr+0xdc` (6 slots + GameSeed). **Transport `[PROVEN]`:** NComm
  rides **TinCat** via `NComm::TinCatNetwork` (`TinCatNetwork.cpp`) @`Mgr+0x340`, created by
  `NComm_Manager_StartUpNetwork@0x40a9a0` (mode @`Mgr+0x3c8`), join sent by `NComm_Manager_ConnectAndJoin@0x40ad60`;
  spun up by `GameServerConnection::OnLoggedIn` — so the stub (TinCat) can sit in this path. **Tribe `[PROVEN]`**
  = 0/1/2 → Bavarian/Scots/Egyptian (`NComm_GetNationIdForTribe@0x4538b0`); color `[PROVEN]` (unique-swap); team
  `[INFERRED]`. `NCommGameSlot` struct (0x4c) created. **Remaining minor `[TODO]`:** hard-prove team, slot tail
  fields `+0x40..0x4b`, host-vs-P2P topology, rest of `0x2002x` events.
- **Entering matches / referee `[TODO]` — MODEL RECOVERED 2026-06-11; see `docs/MATCH_START.md`.**
  Match start is **referee-gated** (that's *why* it's broken — referee removed from the stub). The
  full transition is now reverse-engineered on `sadk_noav.exe` and documented: host
  `Lobby_HostRegisterGameWithReferee@0x432240` sends **`RegisterGame(0xDB6)`** (GameID/MapGUID/MapName/
  MapSettings/Ranked/Wager/AIPlayer/6×AvatarID) → referee **`RegisterGameResult(0xDB8)`** carries the
  **`GameSeed`** (the lockstep determinism seed — no seed, no match). All clients: `NE_StartLoading`
  (NComm 0x30012) sets `NComm+0x3cc`; the referee login is armed later, by the **village-conn LoggedOut** callback `LobbyGameScreen_OnVillageConnectionLoggedOut@0x4316c0` (NOT by NE_StartLoading — corrected 2026-07-25);
  per-frame `LobbyGameScreen_Update@0x435980` pumps `RefereeServerConnection_Login@0x4793f0` (5 retries
  then loads anyway); `LoginSuccess(0xDCA)`/`LoginFailed(0xDCB)` fan out to game-screen observers
  (`refConn+0x80`/`+0x8c`; seed on `+0x50`). The **load kick** = `Game_SetRunMode(game,2)` (game+0xc=2)
  + `Game_PropagateModeToChildren@0x42a640` (walks game+0x3b0 children → each vtbl[0x10]). Full referee
  cat-3 message table + observer-list map in `docs/MATCH_START.md`. **Observer callback bodies + GameSeed
  consumer — DONE 2026-06-13 (statically, no live trace needed — the subscribe side stores the fn-ptrs as
  immediates):** all 10 game-screen observer handlers recovered+named; `LoginSuccess(0x80)→`
  `Lobby_HostRegisterGameWithReferee` (host registers), `RegisterGameResult-success(0x50)→`
  `LobbyGameScreen_OnRefereeRegisterGameResult@0x431800` stores the **GameSeed** into game-session singleton
  **`DAT_00885754+0xdc`**; `LoginFailed(0x8c)→`retry+backoff. `FUN_004624d0`→`LobbyManager_GetVillageServerConnection`.
  `[TODO]` left: confirm the sim RNG reads `DAT_00885754+0xdc`; reverse the granular slot/tribe/team/ready msgs.
  **Stub path to unblock:** referee must accept
  `Login`→`LoginSuccess` and `RegisterGame`→`RegisterGameAck(0xDB7)`+`RegisterGameResult(0xDB8)` with a
  shared `GameSeed`. Named/typed functions also in `docs/REFEREE_FUNCTIONS_TO_NAME.md`.
  **REFEREE STUB RE-IMPLEMENTED 2026-06-13 (offline-tested; `[VERIFY LIVE]`):** new `sadk_lobby/referee.py`
  (LoginSuccess 0xDCA / RegisterGameAck 0xDB7 / RegisterGameResult 0xDB8{GameSeed} builders + 74-envelope
  framing + channel `handle_frame`), referee listener on `config.REFEREE_PORT=5481`, `is_referee` routing in
  `connection.py`. The referee `AssignServer(189)`→`GameServerData(170,subtype=5,REF_SERVER_ID,:5481)` trigger
  (per RE: `RequestRefereeServer@0x468f60` sends `(4,4)` at state>=6, callback `SetRefereeServerAddress@0x4625d0`
  →`LM+0x580`→`InitRefereeServerConnection@0x462910` dials) is **DEFERRED in `dispatch._h_assign_server` — NOT
  sent**: a 170 on every type-4 assign BROKE world-entry (UC/village/referee 189s are ALL type-4, indistinguishable
  here). `dispatch` now logs `server_subtype` to capture the real discriminator live; `REFEREE_SERVER` dict is the
  ready definition to re-enable a GUARDED 170. `tests/test_referee.py` + full suite green; the deferred state is
  wire-inert (only a cosmetic log change vs baseline). **Still needs a live drive (task #8)** for the 189
  discriminator, channel framing, LoginSuccess trigger, and whether the match loads.
  **STATIC RECONCILIATION 2026-06-17 (`docs/MATCH_START_STATIC_RECONCILIATION.md`, `[PROVEN static]`).**
  The host's "Connecting to Game Server" modal lives in **`LobbyMenu_SetupGameDialog_Update@0x457a00`**
  (gate: `NComm_IsHost && villageList+0x9c ∈ {-1,-2}`). The escape (`AssignServer`→`+0x9c=0`) is driven by
  **`WorldScreen` (NOT the same screen)** — note `0x435980` is **`LobbyMenu_WorldScreen_Update`**, mislabelled
  "LobbyGameScreen_Update" in older docs. The AssignServer auto-trigger is **button-free** (arm
  `WorldScreen_ArmGameServerRequest@0x433f60` sets slot-action=8 + deferred flag `[0xd8e]` → `OnLeaveVillage`
  deferred branch → `DispatchSlotAction@0x434230` case6 → `AssignServer`); its **sole precondition is
  `EManagerState==0`** (`NComm_Manager_GetState@0x408430`). The NComm never reaches 0 at match-start (capture:
  `NComm_Manager_Shutdown@0x40b410` 0 hits), so the arm never fires. **The only button-free route to
  `EManagerState 0` is the slot-36 virtual wrapper `0x452d90` (vtbl+0x90) — its dispatcher is unresolved
  statically.** `LeaveButton`(`SetupGameDialog this[0x2de]`) is a player ABORT, not the start. ~17 funcs
  renamed + plate-commented in Ghidra (`decomp/RENAME_LIST.md`). **Next: live test — does EManagerState ever
  leave 2 at all-ready?** (trace `0x40b410`+`0x433f60`, read `0x408430`).
- **In-world content `[TODO]` — full protocol spec derived 2026-07-28 (static, `sadk_noav.exe`);
  avatar spawn/despawn IMPLEMENTED + deployed 2026-07-27, but NEVER SEEN WORKING LIVE.**
  `EntityCreate(1001)` with `dtblcks=1` and `EntityRemove(1003)` are driven off the player registry
  on world entry/exit (`village.entity_create_body`, `dispatch._spawn_world_avatars`, pinned by
  `tests/test_world_presence.py`); everything else below is spec only. The rendered world is
  (last observed) empty — no NPCs/entities; avatar shows
  `<UNNAMED>`. `VillageServerConnection::HandleMessage` was surveyed end-to-end: **corrected model**
  — `EntityCreate/Update/Remove (1001-1003)` carry an `AvatarProxy` player-profile payload
  (name/tribe/colours/level/exp/gold/items) and are almost certainly **the "other players visible"
  path**; `PlayerCreate (1004)`, despite its name, reads an NPC-shaped payload (`npcdesc`/`npctyp`/
  `actChat`) and is `[HYPOTHESIS]` **NPCs, not players** — refutes the prior 2026-07-27 draft's "one
  implementation covers both." All of it is a **bit-packed, MSB-first** LobbyMessage stream
  (non-byte-aligned field widths) sent via `village.BitWriter`. ⭐ **`names` flag SETTLED 2026-07-29
  (static, `sadk_noav.exe`) — must be 0**, correcting the 2026-07-28 survey's `names=1`: field names
  are caller-side C string constants (`FUN_0048f5f0(msg,4,"dtblcks")`) that never ride the wire, and
  `FUN_0048f5f0` always tail-calls the positional bit reader `FUN_0048f0d0` regardless of the flag.
  Setting it makes the finalize `FUN_0048f530` read a **trailing 32-bit hash word** (value discarded,
  not validated) that we do not send ⇒ every body over-read by 4 bytes, silently. Secondary
  subsystems also mapped on the same connection: avatar item/stat re-sync
  (`0xC1C-0xC81`), NPC shop (`0xE11/0xE1B/0xE25`), player-to-player trade (`0xF46/0xF5A`), and a
  low-confidence party/relationship-shaped family (`0xD8-0xDC`/`0x12F`, `[HYPOTHESIS]`, not renamed).
  **[HYPOTHESIS]** the dead in-world chat-text-entry gap (`API.md` known gaps) may share this root
  cause — one candidate world-screen controller is wired directly to the village connection; untested
  whether chat input requires the local player's own `AvatarProxy` to exist first. Full writeup:
  `docs/IN_WORLD_PRESENCE.md`; address table + confidence ratings: `docs/SOURCEMAP.md` §5a. The
  2026-07-28 renames/comments landed on the shared repo via a GUI script replay (see below); a
  **follow-up headless session (same day) then found the this-typing step had actually created the
  duplicate-bare-Global-class trap** (see next section) and fixed it, plus recovered a whole
  parallel serialization family (`LobbyComm::IAvatarDataBlock` + 6 concrete `Avatar*BlockEx`
  classes). Those follow-up fixes are again **headless-working-copy-only** (repo server still
  unreachable from the headless backend even after an MCP transport reconnect) — replay via
  `tools/ghidra_scripts/FixVillageServerConnectionDuplicateClass.java` then
  `tools/ghidra_scripts/ApplyAvatarDataBlockVtables.java` from a GUI session, then File > Check In.

### RE-quality / tooling TODOs (per `HARNESS.md §6` / `decomp/RE_PRACTICES.md`)

- **`LobbyComm::IAvatarDataBlock` family — vtable-bound 2026-07-28 (`sadk_noav.exe`).** Following
  the user's own `VillageServerConnection_vftable` binding, recovered the RTTI-proven interface
  `IAvatarDataBlock` (8-slot vtable: Destructor/ReadFromBuffer/WriteToBuffer/Deserialize/Serialize/
  GetVariant/GetSize/Clear) and its 6 concrete subclasses `AvatarCreationBlockEx`,
  `AvatarAppearanceBlockEx`, `AvatarStyleBlockEx`, `AvatarStatsBlockEx`, `AvatarActiveItemsBlockEx`,
  `AvatarInventoryBlockEx` — the classes `docs/SOURCEMAP.md` flagged `[TODO — RTTI class hygiene]`.
  **This is a separate, parallel avatar-cosmetics serialization path** (NComm::MemoryStream-based,
  fixed 4-byte fields only, no strings) from the already-documented LobbyComm wire readers
  (`AvatarProxy_ReadXBlock`) — most likely the avatar-appearance payload carried inside an NComm
  `PlayerInformation`-style event during an actual match, not the village/lobby wire. Object struct
  field COUNTS/WIDTHS are `[PROVEN]` (read directly off each class's own `Deserialize` body); field
  NAMES are `[HYPOTHESIS]` (generic `fieldN`) since no cross-check against the LobbyComm-side names
  was done (different wire, not provably the same field order). **`AvatarProxy` itself was found to
  inherit `ActorProxy : IActor`** (a distinct, widely-shared actor interface referenced by 4+ other
  class hierarchies) rather than this Block family via composition — deliberately **not** bound this
  session to avoid half-reversing a shared interface; `[TODO]` follow-up. Same session also fixed a
  live duplicate-bare-Global-class instance (see "C++-uniform class consolidation" below) that had
  hit `LobbyComm::VillageServerConnection`'s 8 newly-this-typed avatar/shop/trade handlers, and a
  stale vtable-slot name/signature (`SendWorldLoginReq_2002` → `SendLeaveVillageRequest_2002`,
  matching the already-documented 2026-07-25 correction that had never actually been applied in
  Ghidra). GUI-replay scripts: `tools/ghidra_scripts/FixVillageServerConnectionDuplicateClass.java`,
  `tools/ghidra_scripts/ApplyAvatarDataBlockVtables.java`.
- **Typed vtable structs — STARTED 2026-06-11.** Built `VillageServerConnection_vtable` (17 slots,
  named via the binary) and retyped `pVtable`; checked in (SADK.exe v3). **Important finding:** the doc's
  vtable **base `0x7dc8e0` was WRONG — real base `0x7dc8d4`** (RTTI COL ptr at base-4 `0x7dc8d0`; verified
  by Trigger's `vtbl[0x3c]`=OpenUserComm). All section-2b slot offsets were `0xc` too low; SOURCEMAP fixed.
  `[TODO]` audit the OTHER documented vtables the same way — they may share the off-by-0xc error:
  ServerList `0x7dbf8c`, GameServerInfo `0x7df8b8`, UserComm `0x7dded8`, GameServer `0x7dfafc`. Method:
  read base-4 (RTTI ptr = data, not code) to find the true start; slots are `void*` (upgrade to fn-ptr types later).
- **⚠️ ACTIVE BINARY = `sadk_noav.exe`, not `SADK.exe`.** They are DIFFERENT builds — different
  addresses (SetState @0x462540 in noav vs 0x462700 in SADK) and different struct layouts. Do RE on
  **`sadk_noav.exe`**. `SADK.exe` is a separate (dump-base) build kept for reference. Both are open in
  the backend; always pass the `program` param.
- **Retro-typing sweep — STARTED 2026-06-11 (on `sadk_noav.exe`).** Technique that makes pseudocode
  readable: `set_function_this_type(addr, "Class *")` (moves the fn into the class namespace so the
  __thiscall `this` auto-types — no manual custom-storage needed), then `rename_function_by_address`
  to drop the redundant `Class_`/`Class__` prefix. In noav the **namespaced** method families
  (`VillageServerConnection::*`, `UserCommConnection::*`) were ALREADY this-typed; only the **flat
  `Class_X` helpers** needed it — typed 10 `LobbyManager` + 5 `VillageServerConnection` flat methods.
  **`LobbyManager` struct fleshed out** (deepen, via a parallel read-only agent): resized 1408→**2896**
  (was undersized — methods read to 0xb48), key fields named — notably `pCommLayer@0x4c` (was MISSING)
  and `pConnectionManager@0x50` (was mis-named `pComm`); embedded `userCommConnection@0x3d8`. `StatePump_Tick`
  FSM now fully field-resolved. The **6 embedded sub-objects are now mapped + embedded** (structs
  `LobbyComm_ServerList`@0x54, `LobbyGlobalDataLoader`@0x100, `LobbyServerListLoader`@0x140,
  `LobbyWorldStreamHandler`@0x2f8, `LobbyPostOffice`@0x3bc, `RefereeServerConnection`@0x490) — StatePump
  now reads `&this->postOffice`/`&this->globalDataLoader`/etc. and their vtable calls resolve.
  `[TODO]` remaining: the notifier/observer-list region @0x10–0x4c; scalars @0x584/0x58c/0x5a0; sub-object
  internals are partial (filler-padded). More families: LobbyServerList callbacks, GameServerConnection.
  Naming validator wants PascalCase/verb-first (rejected "SetState" weak-noun → `strict_mode=false`).
- **C++-uniform class consolidation — DONE for the lobby connections 2026-06-11 (`sadk_noav.exe`).**
  `set_function_this_type` had spawned **duplicate Global GhidraClasses** beside the RTTI-proper
  `LobbyComm::*` ones, with members loose in `Global` → two mangled nodes per class. **Procedure +
  reusable script now live in `decomp/RE_PRACTICES.md` → "Class hygiene — make a class look like one
  uniform C++ class"** (consult/run that, don't re-derive). State: checked in —
  **`LobbyComm::VillageServerConnection`** (19 members), **`LobbyComm::UserCommConnection`** (8, RTTI-proven
  `.?AVUserCommConnection@LobbyComm@@`), **`LobbyComm::LobbyBaseConnection`** (4 — *no RTTI descriptor*;
  namespace **inferred** from inheritance: `OnLoggedIn@0x48e050`/`OnLoginFailed@0x48e170` called by both
  LobbyComm connections → shared base. Inference, not `[PROVEN]`). **`Logger` left on purpose:**
  `Logger::vftable@0x7d5028` (`.?AVLogger@@`, real engine logger) vs `LobbyComm::Logger::vftable@0x7daf14`
  are **two distinct classes**, not a dup. (Most same-simple-name classes are legitimate — `NMap::AStar`
  vs `NNavy::AStar`, the 16 `*::System` — only a bare-Global twin / loose Global members is the artifact.)
  `[TODO]` deferred (no RTTI, ambiguous namespace — left in Global, flagged): **`LobbyVillageScreen`** — its
  struct is the `this` type for BOTH `LobbyVillageScreen_*` and `AvatarScreen_*` fns → open RE question
  *are the village screen and avatar screen the same class?*; **`GameLoadDescriptor`** — 1 member
  (`GameConfig_CopyToLoadParams`), name mismatch, no namespace evidence.
- **⚠️ LESSON: do NOT give multiple workflow agents concurrent WRITE access to the SAME struct.**
  `remove_struct_field`/field-adds COLLAPSE a packed (alignment-1) struct, shifting all later offsets —
  so "disjoint span" agents are NOT independent; one agent's remove corrupts another's absolute-offset
  embed. (Hit this 2026-06-11 mapping the sub-objects — caught pre-checkin, rebuilt atomically with
  `recreate_struct` + full field list; this-types SURVIVED because they're namespace-derived.) SAFE pattern:
  fan out **read-only analysis** agents (return field maps), then the orchestrator applies struct edits
  **serially** (prefer `recreate_struct` for a whole-struct rebuild). Per-function `this`-typing across
  *different* functions is fine to parallelize; same-struct field surgery is not.
- **On-demand C-export script `[TODO]`.** Stand up a Ghidra script (run **via the MCP**)
  that re-exports the decompiled C source dumps on request, so an agent can refresh them
  instead of relying on stale offline copies.
- **Symbol-map audit — function layer DONE 2026-06-11; struct layer `[TODO]`.** All 42
  function entries in `docs/SOURCEMAP.md` were reconciled against the live project (via the
  MCP): **every address matched**, 8 had stale *names* (now fixed: `UserCommConnection__X`→`::X`,
  `VillageScreen_RequestEnterVillage`→`CLobby_RequestEnterVillage`; RENAME_LIST `GetChatServerHandle`
  `::`→`_`). The loaded SADK.exe is the **dump-base build** (HandleEnterVillage logic at the
  dump addresses, e.g. `HandleEnterWorld`@0x46f470 — *not* the clean-build 0x46f670). The
  **struct sweep DONE 2026-06-11**: all 9 documented structs (6 SADK.exe + 3 tincat3.dll) **exist and
  are field-exact** against the project. Two SADK class structs were missing their vtable@0 field —
  proven polymorphic and **added + checked in (SADK.exe v2)** (`LobbyManager` pVtable@0 — `FUN_004625c0` calls
  `(**(code**)*singleton)(1)`; `LobbyVillageScreen` pVtable@0 — methods vtable-referenced @0x7d7ed0/
  0x7d831c). `TinCatPropDataConverter` is correctly non-polymorphic (pBuffer@0, no vtable). SOURCEMAP
  updated with both pVtable rows. Still `[TODO]`: reconcile the clean-build address skew.
- **Headless MCP write-back — FIXED 2026-06-11.** The headless server was patched (local clone
  `~/ghidra-mcp`, rebuilt jar) so edits persist to the shared repo: `load_program_from_project` now
  **checks the file out read-write** (non-exclusive) before opening (was read-only → save failed), and a
  new **`checkin_program`** MCP tool saves + `DomainFile.checkin()`s a new repo version. Proven: the two
  `pVtable` fields above were checked in as **SADK.exe version 2** (`mcp@127.0.0.1`). Workflow now:
  load → edit → `checkin_program(comment=...)` → canonical on the repo (Windows GUI sees it on update).
  Patch lives in `HeadlessProgramProvider.java` (+checkout, +checkinProgram) and `HeadlessManagementService.java`
  (+`/checkin_program` endpoint) — see `docs/HEADLESS_SETUP.md`. A fresh clone must re-apply + rebuild.
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
