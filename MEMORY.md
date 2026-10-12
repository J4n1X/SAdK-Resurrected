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

## How complete the map is (measured 2026-10-12, `sadk_noav.exe`)

| | |
|---|---|
| Functions with a name | 29,665 of 31,349 |
| Named functions outside any class or namespace | 19,017 |
| Named functions with an undefined return type | 12,179 |
| Named functions without a plate comment | about 9,700 |
| Structs with unnamed or undefined bytes | about 1,000 of 1,849 |
| `[TODO]` marks in `docs/` | about 145 |
| `[inferred]` / `[HYPOTHESIS]` marks in `docs/` | about 600 (270 in the message catalog, 123 in `types.md`) |

Naming is nearly complete; typing and live confirmation are not.

## Open work

### Lobby protocol, static (`docs/message-catalog.md`, "Open decisions" and the gap table at its end)
- `property_mask` bits of 88 and 90 (T43, T49); `selection` of 72 (T45).
- Shop: `OpenShop(0xE10)` gets no reply in the stub, no shop opens; item ids come from the encrypted item tables
  (V23, V26).
- NPC click with `act = 11` puts nothing on the wire; no message that removes an NPC is known; whether a client
  needs a 1001 for its own id.
- `creation_time` unit; the `hndval` encoding of 303 (V40).

### Match protocol (`docs/NCOMM_GAME_PROTOCOL.md`, `docs/MATCH_START.md`, `docs/types.md`)
- `NCommGameSlot` fields `+0x09`, `+0x1d`, `+0x40..+0x4b`; team is `[inferred]`.
- Offset of the embedded `EventGameInformation` in the NComm manager; the consumer of the GameSeed in the
  simulation.
- **Wagers**: the client's side is mapped (message catalog, 0xDB6) and the server's rules are implemented
  (`lobby/sadk_lobby/wagers.py`, offline-tested). Open: a wagered match in the game, the refusal on the wire, and
  matches of more than two players, which need the teams.
- **Team wins**: `FinishGame` names one winner avatar; the stub has no teams, so the winner's team-mates get no
  win bonus.

### Needs a live session (the maintainer at the game PC, Frida MCP)
- Mail, buddies and presence, whispers, shop and inventory; a wagered match.
- Server mods in a real match: manifest, downloads, mod switching, the kick without assetshare.
- Everything in `lua-surface.md`, `data-loading.md` and `navy-and-military.md`; the mods `oscursor`, `nopreview`,
  `navalcombatfix` in the game.

### Map quality (`HARNESS.md` §6, `decomp/RE_PRACTICES.md`)
- Vtable-base audit for `ServerList` (`0x7dbf8c`), `GameServerInfo`, `UserCommConnection`, `GameServerConnection`:
  read base − 4 (the RTTI pointer) to find the true first slot. `VillageServerConnection` was off by 0xc before
  this check.
- `AvatarProxy` inherits `ActorProxy : IActor`, an interface shared by several hierarchies: not bound yet.
- `LobbyVillageScreen`: its struct types `this` for both `LobbyVillageScreen_*` and `AvatarScreen_*` functions.
  Open: are they one class?
- `LobbyManager`: the observer-list region `+0x10..+0x4c` and scalars `+0x584`, `+0x58c`, `+0x5a0`.
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
