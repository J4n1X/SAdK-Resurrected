# MEMORY.md — compact persistent context

Start here after `CLAUDE.md` + `HARNESS.md`. The short, durable state of the project: what is established, what
is open, and where each is written down. `[PROVEN]` = binary address + live evidence; everything else is
`[TODO]` / `[inferred]` and labelled. Last full revision: 2026-10-12.

---

## Where things are

- **This repository** holds the research: `docs/` (the reference), `decomp/` (RE practices, rename list),
  `engagement_records/` (dated evidence), `tools/`, and the further mods in `mods/`.
- **`lobby/`** (submodule, `S2-modders/sadklobby`): the lobby server, the players' mods `gamebridge` /
  `assetshare` / `billboards`, the setup tool.
- **`sadkmod/`** (submodule, `S2-modders/sadkmod`): the modding library, the shim, and `sourcemap/`, the exported
  Ghidra map the library's game declarations are generated from.
- **Binary under study: Ghidra program `/sadk_noav.exe`** = the DRM-free `SADK.exe` on disk (MD5
  `d4832bc5103c14f5445471af29b8d778`). Ghidra's `/SADK.exe` is a different, SecuROM dump-base build with other
  addresses and layouts: do not map it. In the docs, `S 00xxxxxx` is an address in `sadk_noav.exe`, `T` one in
  `tincat3.dll`.

## What is established

Per-feature status is the table in `CLAUDE.md`; the evidence is in the docs named here.

- **Login** `[PROVEN]`: ECDH secp521r1 → Twofish-CTR credentials → SessionKey(207) → completes on
  **153 AddResult** (the UC path has no 214 handler). `docs/LOBBY_PROTOCOL.md`.
- **Transport** `[PROVEN]`: TinCat 28-byte header; lobby payload magic `0x26B6`, chat `0x0062`; the codec is driven
  by the game's own `msgdefs.ini`. LobbyMessage field scalars are big-endian.
- **Server list and village entry** `[PROVEN]`: `GameServerData(170)` in the ServerInfoOld layout; a village is
  joinable when its data block's room id equals the client's protocol version (1000). Entering the world is the
  server pushing `EnterWorld(1000)` inside a `SendGameData(74)` envelope.
- **The lobby village** `[PROVEN]` for avatars, NPCs, the tailor, the three tavern minigames, accounts and
  persistent characters. `docs/village-and-character-protocol.md`, `docs/message-catalog.md`.
- **Hosting, the pre-game room, entering a match** `[PROVEN]`: the room is the NComm event system on TinCat
  (`docs/NCOMM_GAME_PROTOCOL.md`); match start is referee-gated: `RegisterGame(0xDB6)` → `Ack(0xDB7)` +
  `Result(0xDB8, GameSeed)` (`docs/MATCH_START.md`, `engagement_records/2026-07-27_referee-*.md`). The referee
  assign reply is type 4 / sub 4, never 4 / 5.
- **Host bridge** `[PROVEN]`: `lobby/docs/bridge-protocol.md`. **Map and server-mod sharing**: `docs/s2tftp.md`.
- **Game internals** mapped statically, not yet seen in the running game: `docs/subsystems.md`, `docs/types.md`,
  `docs/lua-surface.md`, `docs/data-loading.md`, `docs/navy-and-military.md`, `docs/map-format.md`,
  `docs/asset-formats.md`.

Ports of the server: 7070 lobby, 7071 chat, **5477 village**, 5481 referee, 7072 / 7073 host bridge. 5479 is the
game port of a *hosting client* (`network.ini` `gamePort`), not a server port.

## How complete the map is (measured 2026-10-12, `sadk_noav.exe` version 65, `tincat3.dll` version 11)

| | |
|---|---|
| Functions with a name | about 30,000 of 31,349; about 12,000 of them are compiler-generated exception funclets |
| Functions that still carry an open reason, shared generic bodies excluded | 256 in `sadk_noav.exe` (2,509 before the day's passes), 33 in `tincat3.dll` (270) |
| of those in `sadk_noav.exe` | owning class not determined 121 · open point in the plate 116 · failed writer operation 58 · in a vtable but not in its class 22 · unnamed 13 |
| Shared generic (ICF-folded) bodies, named by shape | about 600; not a gap |
| Mechanical checks (`Verify.java`) | stack clean-up mismatches 3 · placeholder types in prototypes 17 (`tincat3.dll` 1) |
| Undefined struct bytes | concentrated in the UI classes: `nMenu` about 330 K, `nUi` 53 K, `Lobby` 41 K, `LobbyMenu` about 26 K after the dialog base class was embedded |
| Specifications for the remake | `docs/sim/`: 36 documents, about 45,700 lines, index and reliability figures in `docs/sim/README.md` (residual error after the checks about 1-2 %: 19 wrong in 1,532 sampled claims) |

The mapping pipeline is `mapping/` (README, AGENT_GUIDE, `work/p5/runs.json` for the history). Since 2026-10-12 its writer
no longer protects hand-made names, fields or types (`PROTECT_PRIOR = false`): evidence decides. What four passes
could not settle carries a `[TODO]` in the function's plate that names the observation in the running game that
would decide it.

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
- Matches of three or more players: the maintainer has no third tester, so three-player behaviour (leave notice,
  team wagers, a third player in a save) rests on static evidence for now.
- Everything in `lua-surface.md`, `data-loading.md` and `navy-and-military.md`; the mods `oscursor`, `nopreview`,
  `navalcombatfix` in the game.

### Map quality (`HARNESS.md` §6, `decomp/RE_PRACTICES.md`)
- Vtable-base audit for `ServerList` (`0x7dbf8c`), `GameServerInfo`, `UserCommConnection`, `GameServerConnection`:
  read base − 4 (the RTTI pointer) to find the true first slot. `VillageServerConnection` was off by 0xc before
  this check.
- `AvatarProxy` inherits `ActorProxy : IActor`, an interface shared by several hierarchies: not bound yet.
- `LobbyVillageScreen`: its struct types `this` for both `LobbyVillageScreen_*` and `AvatarScreen_*` functions.
  Open: are they one class?
- `LobbyManager`: the purpose of the observer list `+0x34` (subscribed with a no-op, never fired).
- `ServerList::FindBestVillageServer` S 00469010 and `WorldScreen::PopulateSelectServerMenu` S 004375a0 iterate
  `VillageServerInfo` rows through locals typed `GameServerInfo`; retype them in the typing sweep.
- `UList` (tincat3.dll) is 24 bytes: every manager embeds it at 24-byte spacing. It had been grown to 68, which
  stopped about a tenth of tincat3.dll from decompiling; repaired 2026-10-12.
- `docs/SOURCEMAP.md` sections 1–2 still carry addresses of the dump-base build; reconcile them to `sadk_noav.exe`.
- Typing sweep by subsystem, lobby classes first.

## Lessons that keep paying

- **Every failure in the referee path is silent** (frame accepted, socket open, nothing logged). "No error" is
  not evidence.
- **One writer per struct.** Removing or adding a field in a packed struct shifts every later offset, so parallel
  agents editing one struct corrupt each other. Fan out read-only analysis; apply struct edits serially, with
  `recreate_struct` for a whole-struct rebuild.
- **Class hygiene.** `set_function_this_type` can create a bare Global twin of an RTTI class; the procedure and
  script are in `decomp/RE_PRACTICES.md`, "Class hygiene".
- **Map before mod code.** A mod uses only mapped fields: Ghidra → check in → re-export `sadkmod/sourcemap/` →
  regenerate sadkmod.
- **Consult the client first.** Audit the whole client code path in Ghidra before writing server behaviour; never
  patch reactively from a live failure.

## Tooling state

- Ghidra MCP: a headless backend started by the MCP bridge, working on a checkout of the shared repository
  (`docs/HEADLESS_SETUP.md`). `checkin_program` writes a new repository version and unloads the program: load it
  again afterwards. `server_status` may say "not connected" while check-in works.
- Live debugging: the Frida MCP (`tools/frida_mcp/`, `docs/LIVE_DEBUG_RUNBOOK.md`).
- All RE and debugging through the MCPs; no standalone RE, memory or patch scripts (`HARNESS.md` §1).
