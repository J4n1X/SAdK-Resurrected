# docs/ — the reference

Reverse-engineering reference for *Die Siedler: Aufbruch der Kulturen*, heavily AI-assisted. Every claim carries
its evidence tag (`HARNESS.md` §4): `[PROVEN]` = binary address + live evidence, `[known]` = read in the binary,
`[inferred]`, `[TODO]`. Addresses are those of `sadk_noav.exe` (`S 00xxxxxx`), the Ghidra program byte-identical to
the DRM-free `SADK.exe` on disk (image base `0x400000`, the same as at runtime), and of `tincat3.dll`
(`T 10xxxxxx`, base `0x10000000`). The compact current state is `MEMORY.md` in the repository root.

## Protocol

| File | Contents |
|------|----------|
| `protocol-overview.md` | Flow-level overview for outside readers: the four connections, base login, lobby, chat, village entry and exit, hosting and joining, the referee chain, with sequence diagrams. Defers to the catalog for details. |
| `message-catalog.md` | **The protocol reference**: every message the client sends or handles, what it expects back and why, with binary addresses and the server's decisions. |
| `village-and-character-protocol.md` | Characters, the village connection, avatars, NPCs, shops, tailor, minigames: the server-side flows. |
| `IN_WORLD_PRESENCE.md` | The village connection's avatar and NPC records (1001–1004) and the client's inbound API. |
| `MATCH_START.md` | From the pre-game room to a running match: the referee chain and its silent failure modes. |
| `NCOMM_GAME_PROTOCOL.md` | The pre-game room and the in-game peer-to-peer layer (NComm events on TinCat). |
| `NCOMM_LAYER.md` | `NComm::Manager`, its transports, events and state machine. |
| `s2tftp.md` | The game's file transfer between match players (map fetch), which the assetshare mod builds on. |
| `GAME_JOIN_CAPTURE_decoded.txt` | A decoded capture of a peer-to-peer game join (artifact). |

The host bridge's protocol is in the lobby submodule: `lobby/docs/bridge-protocol.md`.

## The client

| File | Contents |
|------|----------|
| `subsystems.md` | Map of the client's subsystems: what each does, main classes, entry points, how much is mapped. |
| `types.md` | Recovered classes and structs, how types are organised in Ghidra, naming conventions, open gaps. |
| `SOURCEMAP.md` | Names and roles of the lobby, village and match-network code (functions, structs, globals, vtable slots). |
| `LOBBY_SCREEN_VTABLES.md` | The `LobbyMenu::ScreenBase` screen and dialog family and its vtables. |
| `lua-surface.md` | The Lua runtime, how scripts load, every registered C function, every call into Lua, hook points. |
| `data-loading.md` | Which data files are read once at start-up and which per match (what a mod can change, and when). |
| `navy-and-military.md` | Attacks, defence, fights, sea transport and expeditions; what the navalcombatfix mod changes. |
| `multiplayer-save.md` | Saving and continuing a network match; the design of the mpsave mod. |

## Files and formats

| File | Contents |
|------|----------|
| `game-data-files.md` | How to read and change the game's data files today: decryption tools, mods, what a data change can do. |
| `asset-formats.md` | The encrypted containers and the `.KEX` scene format (implemented by `tools/sadk_crypt.py`, `tools/kex.py`). |
| `map-format.md` | The `.s2m` map format, section by section; the old prototype layout and its conversion. |
| `BINARY_PATCHES.md` | What the project changes in `SADK.exe`: the SecuROM boot fix, the developer (CVar) patch, each mod's in-memory changes. |

## The remake

| File | Contents |
|------|----------|
| `sim/` | One specification per subsystem, written so the remake can be built without the binary (behaviour, rules, constants, update order, formats, determinism). Start with `sim/README.md`, which also gives the reliability figures. |
| `remake-architecture.md`, `remake-rendering.md` | The remake's binding decisions (maintainer, 2026-10-14): code layout, the base game as a mod, registry, components, commands, determinism; the renderer. |
| `remake/` | The draft design set (2026-10-15, to be confirmed): Godot capabilities, the simulation/presentation boundary, renderer, assets, mods, Lua. Start with `remake/README.md`. |

## Working on the live game and the map

| File | Contents |
|------|----------|
| `LIVE_DEBUG_RUNBOOK.md` | Live work through the Frida MCP: setup, tools, main-thread calls, standing probes and hook sets, unattended runs. |
| `live-session-queue.md` | The open checks that need the running game, each settling one `[inferred]` / `[TODO]` statement. |
| `live-checks/` | Raw measurement records of live runs (artifacts cited by the specifications). |
| `HEADLESS_SETUP.md` | The Ghidra MCP on the Linux server: Ghidra Server, headless backend, install and update, working rules, troubleshooting, a Windows GUI client. |

How the map is made: `decomp/RE_PRACTICES.md` and `mapping/README.md`.
