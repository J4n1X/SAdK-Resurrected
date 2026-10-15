# MEMORY.md — compact persistent context

Start here after `CLAUDE.md` + `HARNESS.md`. The short, durable state of the project: what is established, what
is open, and where each is written down. `[PROVEN]` = binary address + live evidence; everything else is
`[TODO]` / `[inferred]` and labelled. Last full revision: 2026-10-12; map figures and map quality 2026-10-13;
locations and tooling 2026-10-15. Update the section a result belongs to; this is not a log.

---

## Where things are

- **This repository** holds the research: `docs/` (the reference; index `docs/README.md`), `decomp/` (RE
  practices, rename list), `mapping/` (the mapping pipeline), `tools/`, and the further mods in `mods/`. Evidence
  lives in the reference docs (`HARNESS.md` §8); the history of how a result was reached is in git.
- **`lobby/`** (submodule, `S2-modders/sadklobby`): the lobby server, the players' mods `gamebridge` /
  `assetshare` / `billboards`, the setup tool.
- **`sadkmod/`** (submodule, `S2-modders/sadkmod`): the modding library, the shim, and `sourcemap/`, the exported
  Ghidra map the library's game declarations are generated from.
- **Binary under study: Ghidra program `/sadk_noav.exe`** = the DRM-free `SADK.exe` on disk (MD5
  `d4832bc5103c14f5445471af29b8d778`). Ghidra's `/SADK.exe` is a different, SecuROM dump-base build with other
  addresses and layouts: do not map it. In the docs, `S 00xxxxxx` is an address in `sadk_noav.exe`, `T` one in
  `tincat3.dll`.
- **The remake** (Godot 4.7.2, simulation in C#): binding decisions in `docs/remake-architecture.md` and
  `docs/remake-rendering.md`, the draft design set in `docs/remake/` (2026-10-15, to be confirmed), the behaviour
  specifications in `docs/sim/`. Its code is a separate repository, `sadk-remake`.

## What is established

Per-feature status is the table in `CLAUDE.md`; the evidence is in the docs named here.

- **Login** `[PROVEN]`: the lobby connection runs 188 → ECDH secp521r1 (201/202) → Twofish-CTR credentials
  (203/204) → completes on **207 SessionKey**; the UC, village and referee connections log in with a token
  (211/213) and complete on **153 AddResult** (the UC path has no 214 handler). `docs/message-catalog.md`,
  flow overview `docs/protocol-overview.md`.
- **Transport** `[PROVEN]`: TinCat 28-byte header; NETMSG module `0x26B6` with the codec driven by the game's own
  `msgdefs.ini` (property-bag fields little-endian); chat as CellManager module `0x0062` templates. LobbyMessage
  bodies (village, referee) are an MSB-first bit stream: 32-bit values big-endian when byte-aligned.
- **Server list and village entry** `[PROVEN]`: `GameServerData(170)` in the ServerInfoOld layout; a village is
  joinable when its data block's room id equals the client's protocol version (1000). Entering the world is the
  server pushing `EnterWorld(1000)` inside a `SendGameData(74)` envelope.
- **The lobby village** `[PROVEN]` for avatars, NPCs, the tailor, the three tavern minigames, accounts and
  persistent characters. `docs/village-and-character-protocol.md`, `docs/message-catalog.md`.
- **Hosting, the pre-game room, entering a match** `[PROVEN]`: the room is the NComm event system on TinCat
  (`docs/NCOMM_GAME_PROTOCOL.md`); match start is referee-gated: `RegisterGame(0xDB6)` → `Ack(0xDB7)` +
  `Result(0xDB8, GameSeed)` (`docs/MATCH_START.md`). The referee assign reply is type 4 / sub 4, never 4 / 5.
- **Host bridge** `[PROVEN]`: `lobby/docs/bridge-protocol.md`. **Map and server-mod sharing**: `docs/s2tftp.md`.
- **Game internals** mapped statically, not yet seen in the running game: `docs/subsystems.md`, `docs/types.md`,
  `docs/lua-surface.md`, `docs/data-loading.md`, `docs/navy-and-military.md`, `docs/map-format.md`,
  `docs/asset-formats.md`.

Ports of the server: 7070 lobby, 7071 chat, **5477 village**, 5481 referee, 7072 / 7073 host bridge. 5479 is the
game port of a *hosting client* (`network.ini` `gamePort`), not a server port.

## How complete the map is (measured 2026-10-13, `sadk_noav.exe` version 71, `tincat3.dll` version 16)

| | |
|---|---|
| Functions with a name | `sadk_noav.exe` 30,443 of 31,183; the 740 without one are compiler-generated (713 exception funclets, 27 CRT internals). `tincat3.dll` 1,733 of 1,733 |
| Functions that still carry an open reason | 0 in both programs (2,509 and 270 on the morning of 2026-10-12; 256 and 33 on the morning of 2026-10-13) |
| Bodies the linker folded for unrelated classes (tag `ICF_SHARED`) | 210 and 30. Each has its users measured (vftable owners, receiver type at every call site) and named in its plate; it has no owning class |
| Methods entered through a secondary vftable (tag `FACE_THIS`) | 666 and 5. Their `this` is an offset pointer into the class struct, so the decompile shows the class's own field names (`ADJ(this)->field`) |
| Mechanical checks (`Verify.java`) | no finding: stack clean-up, placeholder types, vftable owners, duplicate field names. 23 allocation-size findings are read and listed as base-class or temporary constructors in `mapping/work/verify_reviewed.json` |
| Undefined struct bytes | 11,413 of 1,142,408 in `sadk_noav.exe` (1 %; 417,758 = 36 % on the morning of 2026-10-13), 714 of 29,188 in `tincat3.dll`. What is left is alignment padding and bytes no code touches |
| Specifications for the remake | `docs/sim/`: 36 documents, about 45,700 lines, index and reliability figures in `docs/sim/README.md` (residual error after the checks about 1-2 %: 19 wrong in 1,532 sampled claims) |

The mapping pipeline is `mapping/` (README, AGENT_GUIDE, `work/p5/runs.json` for the history; the gap closure of
2026-10-13 is `work/gaps_20261013/`, with its report in `GAP_CLOSURE.md`). Its writer does not protect hand-made
names, fields or types (`PROTECT_PRIOR = false`): evidence decides. Layout and ownership questions are settled from
measurements, not from reading alone: `RefUsers.java` (which vftables and callers use a function), `ReceiverTypes.java`
(the type a method is called on, at every call site), `StructEvidence.java` (member objects and base classes from
constructor calls, typed accesses to undefined struct bytes), `DumpHierarchy.java` (RTTI bases, vftable slots), with
`bin/owners.py` and `bin/struct_fill.py` turning them into change files.

## Open work

### Lobby protocol, static (`docs/message-catalog.md`, "Open decisions" and the gap table at its end)
- `property_mask` bits of 88 and 90 other than 8 (T43, T49): the client sets none, so they are a server decision.
  (`selection` of 72 is never written by the client.)
- Shop: the wire matches; the stub credits a different sell price than the client shows (V30). Item ids are
  `ItemsClient.txt` ids 1..36; the meaning of its tokens 3 and 4 is open.
- NPCs: only a single action in slot 0 is dispatched (on selection); whether a button can fire for an NPC with
  more actions, why the matchmaker NPC does nothing, and the unexplained silent shop click of 2026-08-02.
- `creation_time` unit (no reader found in the client); the `hndval` encoding of 303 (V40).
- Differences between the lobby server and the client: `mapping/work/protocol_gaps/stub_differences.md`.

### Match protocol (`docs/NCOMM_GAME_PROTOCOL.md`, `docs/MATCH_START.md`, `docs/types.md`)
- `NCommGameSlot`: all fields are named (team is `+0x3f`, `[known]`); open are the nibble order of `+0x41`, the
  body parts of the `+0x43` nibbles and the value of the local latch `+0x4b` on a non-host.
- Offset of the embedded `EventGameInformation` in the NComm manager.
- The GameSeed seeds only the chest contents of a network match, not the simulation (`docs/MATCH_START.md`,
  Phase 2). Open: whether differing seeds inside one match desync.
- **Wagers**: the client's side is mapped (message catalog, 0xDB6) and the server's rules are implemented
  (`lobby/sadk_lobby/wagers.py`, offline-tested). Open: a wagered match in the game, the refusal on the wire, and
  matches of more than two players, which need the teams.
- **Team wins**: `FinishGame` names one winner avatar; the stub has no teams, so the winner's team-mates get no
  win bonus. Live 2026-10-12 (four free games, `docs/live-session-queue.md`): `DeclareWinner` is called once
  with the lowest player index of the winning side, also with interleaved sides; allies only get the local
  `won` flag. The referee connection sends nothing else about the result (six outgoing messages in all).
- **TODO, not started — wager pairing mod ("wagermaker", maintainer's design of 2026-10-12)**: team wagers
  without any server-side knowledge of teams. Each client pairs the players itself: it takes itself and its
  team-mate, orders them by id, does the same for the enemy side, and matches higher with higher and lower with
  lower; each pair is then a two-player wager, which the server can already settle. It must work without a
  server-side implementation, and it should go into an existing mod (e.g. assetshare) rather than a new one,
  because the number of mods is already a burden. Open before any code: what the mod sends per pair (the server
  only knows `RegisterGame`, `GiveUpGame`, `FinishGame`), sides of unequal size, free-for-all with three or
  more players, and which id is ordered (player index or avatar id).

### Needs a live session (the maintainer at the game PC, Frida MCP)
- A wagered match and a refused match registration (referee result 9 / 15); shop sell prices; the checks in
  `docs/live-session-queue.md`. Mail, buddies, whispers, the shops and per-match server mods work in live play
  (maintainer, 2026-10-12).
- The checklist of open protocol statements a session can settle: `docs/live-session-queue.md`.
- `Lobby::IPhysicObj` slots 2, 6 and 8 have no caller in the binary (hook 005210c0 and 00523430 in the village, then
  walk, jump, sit at a minigame table, use reset-position). The other live checks of the gap closure were settled by
  reading (`mapping/work/gaps_20261013/live_checks.md`).
- Matches of three or more players: the maintainer has no third tester, so three-player behaviour (leave notice,
  team wagers, a third player in a save) rests on static evidence for now.
- Everything in `lua-surface.md`, `data-loading.md` and `navy-and-military.md`; the mods `oscursor`, `nopreview`,
  `navalcombatfix` in the game.

### Map quality (`HARNESS.md` §6, `decomp/RE_PRACTICES.md`)
The gap closure of 2026-10-13 left no function with an open reason and no `Verify.java` finding; its record and the
list of what stays open are in `mapping/work/gaps_20261013/GAP_CLOSURE.md`. In short:
- `LobbyManager` is the RTTI class `LobbyComm::System` (1448 bytes). The global `g_pLobbyManager`, the enum
  `LobbyManagerState` and four static functions keep the old word.
- A method that runs on a secondary base pointer has an offset-pointer `this` (tag `FACE_THIS`); the decompile shows
  `ADJ(this)->field`. There are no mirror structs any more.
- Left for static work: about 40 Global functions named `<Class>_<Method>` whose receiver no call site types,
  `_TestDefaultLanguage` (needs custom storage), `NxControllerDesc` +8, empty namespaces after class merges, and the
  argument name of `OpenUserComm` / `OpenCommunication` (`chatServerHandle`, but the callers pass a character id).
- `UList` (tincat3.dll) is 24 bytes; every CommLayer manager struct matches its allocation size.

## Lessons that keep paying

- **Every failure in the referee path is silent** (frame accepted, socket open, nothing logged). "No error" is
  not evidence.
- **One writer per struct.** Removing or adding a field in a packed struct shifts every later offset, so parallel
  agents editing one struct corrupt each other. Fan out read-only analysis; apply struct edits serially, with
  `recreate_struct` for a whole-struct rebuild.
- **Measure, then read.** Who owns a method and what a struct holds are measurable: the classes whose vftable
  holds a function, the receiver type at every call site, the constructor that runs on this+offset, the width of
  every access to an undefined byte (`mapping/scripts/RefUsers.java`, `ReceiverTypes.java`, `StructEvidence.java`).
  On 2026-10-13 that settled in minutes what four reading passes had left open, and reading agents only got what
  the measurement could not decide. A measurement can be wrong in a systematic way (a method that runs on a
  secondary base pointer shifts every offset it shows), so sample its output against the code before applying it.
- **Class hygiene.** `set_function_this_type` can create a bare Global twin of an RTTI class; the procedure and
  script are in `decomp/RE_PRACTICES.md`, "Class hygiene".
- **Map before mod code.** A mod uses only mapped fields: Ghidra → check in → re-export `sadkmod/sourcemap/` →
  regenerate sadkmod.
- **Consult the client first.** Audit the whole client code path in Ghidra before writing server behaviour; never
  patch reactively from a live failure.

## Tooling state

- Ghidra MCP: bethington/ghidra-mcp 6.0.0, headless on the Linux server, working on a checkout of the Ghidra
  Server repository `sadk`; installed and registered (Claude Code local scope) by
  `tools/ghidramcp/update-ghidramcp.sh`; the backend lives as long as the session's bridge, and one backend at a
  time can open the shared project (`docs/HEADLESS_SETUP.md`). `checkin_program` writes a new repository version
  and unloads the program: load it again afterwards. `server_status` may say "not connected" while check-in works.
- Live debugging: the Frida MCP (`tools/frida_mcp/`, `docs/LIVE_DEBUG_RUNBOOK.md`). The earlier Ghidra-debugger and
  Time Travel Debugging route is retired.
- All RE and debugging through the MCPs; no standalone RE, memory or patch scripts (`HARNESS.md` §1).
