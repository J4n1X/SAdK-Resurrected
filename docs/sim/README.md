# Specifications for a remake (`docs/sim/`)

One document per subsystem of *Die Siedler: Aufbruch der Kulturen*, written so that the subsystem can be reimplemented
without the binary: behaviour, rules with their constants, order of operations, data formats, the parameters that come
from the game's data files, what a save holds, and what must be deterministic. They were derived from the mapped client
(`sadk_noav.exe`, `tincat3.dll`) and the game's data, and are the groundwork for a remake in the Godot engine that
reads the player's own install and ships no original data. The remake's simulation is written in C# (Godot .NET), as
a library that runs without Godot; mods are loaded as assemblies and can patch any of its methods (Harmony), so core
systems such as pathfinding stay moddable. Presentation, UI and tools use Godot.

## How to read them

- Every statement of fact carries a tag: **[known]** = read directly at an address (`S 00xxxxxx` in `sadk_noav.exe`,
  `T 10xxxxxx` in `tincat3.dll`) or in a named data file and key; **[inferred]** = one step of reasoning from what is
  visible; **[TODO]** = not established, with what would settle it. A few statements cite a dated observation in the
  running game as **[live]**; everything else has not been seen running.
- Each document has the same eleven sections: purpose, data model, rules and algorithms, update order, inputs and
  outputs, data-driven parameters, save and load, determinism notes, notes for a reimplementation, open questions,
  function reference.
- The protocol references outside this folder are the authority for wire formats: `docs/message-catalog.md`,
  `docs/LOBBY_PROTOCOL.md`, `docs/village-and-character-protocol.md`, `docs/NCOMM_GAME_PROTOCOL.md`; file formats:
  `docs/map-format.md`, `docs/asset-formats.md`; the Lua function lists: `docs/lua-surface.md`.

## How reliable they are (2026-10-12)

Each document was written by one agent and then checked against the binary by others. An *exhaustive check* went
through every concrete claim of a document in two halves and corrected it in place; a *residual sample* afterwards
re-derived 40 or more claims picked by position, to measure what is left.

| Set | Exhaustive check | Residual sample afterwards |
|---|---|---|
| Simulation core (12) | 6,966 claims, 444 corrected (6.4 %) after a first sampled check; the AI player a second time: 855 claims, 24 corrected | 440 claims, 8 wrong (1.8 %); AI player 40, 0 wrong |
| Session, scripting, data, presentation (11) | 5,127 claims, 431 corrected (8.4 %) | 470 claims, 5 wrong (1.1 %) |
| Front end, lobby client, tools, engine (13) | 6,000 claims, 502 corrected (8.4 %) | 582 claims, 6 wrong (1.0 %) |

So a statement in these documents is wrong in roughly one case in fifty to a hundred. A number that a reimplementation
depends on should still be checked against the game before it is built in: nothing here was observed running unless
marked [live]. The checks that need the running game are collected in `docs/live-session-queue.md` (105 entries from
these documents, 85 of them doable by one player).

## The documents

### Simulation core

| Document | Lines | [known] / [inferred] / [TODO] | Residual sample |
|---|---|---|---|
| [`logic-core.md`](logic-core.md): Logic core: ticks, callbacks, random generator, checksum | 1226 | 140 / 36 / 12 | 40 checked, 1 wrong |
| [`game-commands.md`](game-commands.md): Game system and player commands | 1130 | 83 / 16 / 4 | 40 checked, 0 wrong |
| [`players-victory.md`](players-victory.md): Players, teams, diplomacy and victory conditions | 1196 | 172 / 40 / 16 | 40 checked, 1 wrong |
| [`village-buildings.md`](village-buildings.md): Settlement: buildings, construction and production | 1482 | 153 / 19 / 4 | 40 checked, 0 wrong |
| [`settlers-jobs.md`](settlers-jobs.md): Settlers: workers, carriers, jobs and movement | 1716 | 190 / 32 / 3 | 40 checked, 2 wrong |
| [`streets-transport.md`](streets-transport.md): Streets, flags and goods transport | 1520 | 224 / 33 / 2 | 40 checked, 1 wrong |
| [`map-resources.md`](map-resources.md): Map, terrain, resources and doodads | 1438 | 157 / 10 / 6 | 40 checked, 1 wrong |
| [`military.md`](military.md): Military: soldiers, buildings, attacks and fights | 1492 | 148 / 18 / 7 | 40 checked, 0 wrong |
| [`navy.md`](navy.md): Navy: ships, harbours, sea routes and expeditions | 1247 | 124 / 11 / 4 | 40 checked, 2 wrong |
| [`ai-player.md`](ai-player.md): Computer player (AI) | 1702 | 145 / 57 / 10 | 40 checked, 0 wrong |
| [`properties-data.md`](properties-data.md): Property database: goods, buildings, settlers and patterns | 1208 | 92 / 14 / 5 | 40 checked, 0 wrong |
| [`save-format.md`](save-format.md): Save games: the store interface and the file format | 1177 | 151 / 33 / 12 | 40 checked, 0 wrong |

### Session, scripting, data and presentation

| Document | Lines | [known] / [inferred] / [TODO] | Residual sample |
|---|---|---|---|
| [`network-session.md`](network-session.md): Match network session (NComm): lockstep, packages, join, leave and reconnect | 1191 | 81 / 18 / 7 | 55 checked, 1 wrong |
| [`lua-runtime.md`](lua-runtime.md): Lua runtime: what a reimplementation must reproduce | 844 | 69 / 19 / 3 | 49 checked, 0 wrong |
| [`formats-inventory.md`](formats-inventory.md): File formats and assets: inventory and conversion targets | 1215 | 94 / 29 / 14 | 40 checked, 0 wrong |
| [`rendering.md`](rendering.md): Rendering and scene: what the player sees | 1603 | 156 / 107 / 18 | 40 checked, 1 wrong |
| [`particles.md`](particles.md): Particle effects: the `.pfx` format, simulation, drawing and who starts them | 956 | 90 / 22 / 7 | written 2026-10-14, not checked yet |
| [`ambient-swarms.md`](ambient-swarms.md): Ambient swarms (birds, fish, bugs): dormant in this build, the code as it would run | 756 | 92 / 19 / 3 | written 2026-10-14, not checked yet |
| [`animation-models.md`](animation-models.md): Models, skeletons and animation at runtime | 1435 | 178 / 42 / 11 | 40 checked, 1 wrong |
| [`ingame-ui.md`](ingame-ui.md): In-game user interface: HUD, menus, selection and actions | 1550 | 87 / 90 / 11 | 46 checked, 1 wrong |
| [`audio.md`](audio.md): Audio: sound effects, ambience and music | 970 | 94 / 8 / 6 | 40 checked, 0 wrong |
| [`camera-input-cutscenes.md`](camera-input-cutscenes.md): Camera, input and cutscenes | 1137 | 62 / 16 / 8 | 40 checked, 1 wrong |
| [`quests-sacrifices-stats.md`](quests-sacrifices-stats.md): Quests, sacrifices, statistics, chests and messages | 1357 | 115 / 24 / 7 | 40 checked, 0 wrong |
| [`tribes-content.md`](tribes-content.md): Game content overview: tribes, buildings, goods and production chains | 1476 | 23 / 10 / 5 | 40 checked, 0 wrong |
| [`app-shell.md`](app-shell.md): Application shell: start-up, main loop, settings, profiles and game modes | 1241 | 73 / 23 / 13 | 40 checked, 0 wrong |

### Front end, lobby client, tools and engine primitives

| Document | Lines | [known] / [inferred] / [TODO] | Residual sample |
|---|---|---|---|
| [`match-setup-room.md`](match-setup-room.md): Multiplayer match set-up: hosting, browsing, the pre-game room | 1113 | 72 / 5 / 7 | sampled, see the set's total |
| [`frontend-screens.md`](frontend-screens.md): Front end: main menu, free-game set-up, campaign, loading and the other out-of-match screens | 1130 | 89 / 22 / 3 | sampled, see the set's total |
| [`hud-panels.md`](hud-panels.md): HUD panels in detail: statistics, goods, tooltips, messages, overlays | 1140 | 105 / 25 / 11 | sampled, see the set's total |
| [`ui-toolkit.md`](ui-toolkit.md): UI toolkit: widget classes and their behaviour | 786 | 90 / 10 / 4 | sampled, see the set's total |
| [`world-objects-rendering.md`](world-objects-rendering.md): World presentation objects: goods, streets, decals, sky and the render engine layer | 1216 | 149 / 22 / 7 | sampled, see the set's total |
| [`lobby-world-client.md`](lobby-world-client.md): The 3D lobby village on the client | 1159 | 190 / 17 / 10 | sampled, see the set's total |
| [`lobby-screens.md`](lobby-screens.md): Lobby screens and dialogs | 1590 | 241 / 27 / 3 | sampled, see the set's total |
| [`lobby-client-state.md`](lobby-client-state.md): Lobby client state: managers, proxies and observers behind the wire | 1807 | 300 / 66 / 5 | sampled, see the set's total |
| [`minigames-client.md`](minigames-client.md): Tavern minigames on the client: Dice, Poker and Pawn Chess | 1183 | 273 / 26 / 10 | sampled, see the set's total |
| [`lan-and-transport.md`](lan-and-transport.md): LAN discovery and the TinCat transport under the match session | 1174 | 75 / 10 / 8 | sampled, see the set's total |
| [`map-editor-devtools.md`](map-editor-devtools.md): Map editor and developer tools inside the client | 1049 | 82 / 11 / 4 | sampled, see the set's total |
| [`lobby-extras.md`](lobby-extras.md): Lobby extras: physics and collision, web textures, lobby data files | 812 | 53 / 27 / 3 | sampled, see the set's total |
| [`engine-core.md`](engine-core.md): Engine core primitives: streams, serialisation, containers, math and utilities | 1272 | 95 / 17 / 2 | sampled, see the set's total |

## What is not covered

- The original servers' behaviour where the client gives no evidence of it (for example how a wager was paid out in a
  match of more than two players: the client reports one winner and never sends the teams).
- Struct layouts of the in-game menu classes are described by behaviour here. Their fields are named in the
  Ghidra map: of the 2,161 fields of the `nMenu` structs about 20 keep an offset name.
- Questions that only the running game can answer are listed in each document's section 10 and collected in
  `docs/live-session-queue.md`.
