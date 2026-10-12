# Specifications for a remake (`docs/sim/`)

One document per subsystem of *Die Siedler: Aufbruch der Kulturen*, written so that the subsystem can be reimplemented
without the binary: behaviour, rules with their constants, order of operations, data formats, the parameters that come
from the game's data files, what a save holds, and what must be deterministic. They were derived from the mapped client
(`sadk_noav.exe`, `tincat3.dll`) and the game's data, and are the groundwork for a remake in the Godot engine that
reads the player's own install and ships no original data.

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
| [`game-commands.md`](game-commands.md): Game system and player commands | 1114 | 79 / 17 / 5 | 40 checked, 0 wrong |
| [`players-victory.md`](players-victory.md): Players, teams, diplomacy and victory conditions | 1182 | 172 / 42 / 18 | 40 checked, 1 wrong |
| [`village-buildings.md`](village-buildings.md): Settlement: buildings, construction and production | 1468 | 147 / 19 / 5 | 40 checked, 0 wrong |
| [`settlers-jobs.md`](settlers-jobs.md): Settlers: workers, carriers, jobs and movement | 1694 | 188 / 35 / 3 | 40 checked, 2 wrong |
| [`streets-transport.md`](streets-transport.md): Streets, flags and goods transport | 1513 | 222 / 33 / 2 | 40 checked, 1 wrong |
| [`map-resources.md`](map-resources.md): Map, terrain, resources and doodads | 1436 | 153 / 10 / 6 | 40 checked, 1 wrong |
| [`military.md`](military.md): Military: soldiers, buildings, attacks and fights | 1472 | 148 / 16 / 7 | 40 checked, 0 wrong |
| [`navy.md`](navy.md): Navy: ships, harbours, sea routes and expeditions | 1236 | 121 / 12 / 5 | 40 checked, 2 wrong |
| [`ai-player.md`](ai-player.md): Computer player (AI) | 1700 | 145 / 57 / 12 | 40 checked, 0 wrong |
| [`properties-data.md`](properties-data.md): Property database: goods, buildings, settlers and patterns | 1203 | 91 / 13 / 5 | 40 checked, 0 wrong |
| [`save-format.md`](save-format.md): Save games: the store interface and the file format | 1175 | 147 / 34 / 12 | 40 checked, 0 wrong |

### Session, scripting, data and presentation

| Document | Lines | [known] / [inferred] / [TODO] | Residual sample |
|---|---|---|---|
| [`network-session.md`](network-session.md): Match network session (NComm): lockstep, packages, join, leave and reconnect | 1167 | 75 / 20 / 9 | 55 checked, 1 wrong |
| [`lua-runtime.md`](lua-runtime.md): Lua runtime: what a reimplementation must reproduce | 836 | 68 / 19 / 4 | 49 checked, 0 wrong |
| [`formats-inventory.md`](formats-inventory.md): File formats and assets: inventory and conversion targets | 1215 | 94 / 29 / 14 | 40 checked, 0 wrong |
| [`rendering.md`](rendering.md): Rendering and scene: what the player sees | 1585 | 153 / 108 / 20 | 40 checked, 1 wrong |
| [`animation-models.md`](animation-models.md): Models, skeletons and animation at runtime | 1434 | 178 / 42 / 11 | 40 checked, 1 wrong |
| [`ingame-ui.md`](ingame-ui.md): In-game user interface: HUD, menus, selection and actions | 1548 | 87 / 90 / 11 | 46 checked, 1 wrong |
| [`audio.md`](audio.md): Audio: sound effects, ambience and music | 958 | 92 / 11 / 8 | 40 checked, 0 wrong |
| [`camera-input-cutscenes.md`](camera-input-cutscenes.md): Camera, input and cutscenes | 1124 | 59 / 15 / 8 | 40 checked, 1 wrong |
| [`quests-sacrifices-stats.md`](quests-sacrifices-stats.md): Quests, sacrifices, statistics, chests and messages | 1355 | 114 / 24 / 10 | 40 checked, 0 wrong |
| [`tribes-content.md`](tribes-content.md): Game content overview: tribes, buildings, goods and production chains | 1475 | 23 / 11 / 5 | 40 checked, 0 wrong |
| [`app-shell.md`](app-shell.md): Application shell: start-up, main loop, settings, profiles and game modes | 1236 | 72 / 23 / 13 | 40 checked, 0 wrong |

### Front end, lobby client, tools and engine primitives

| Document | Lines | [known] / [inferred] / [TODO] | Residual sample |
|---|---|---|---|
| [`match-setup-room.md`](match-setup-room.md): Multiplayer match set-up: hosting, browsing, the pre-game room | 1101 | 68 / 5 / 11 | sampled, see the set's total |
| [`frontend-screens.md`](frontend-screens.md): Front end: main menu, free-game set-up, campaign, loading and the other out-of-match screens | 1114 | 86 / 22 / 4 | sampled, see the set's total |
| [`hud-panels.md`](hud-panels.md): HUD panels in detail: statistics, goods, tooltips, messages, overlays | 1140 | 105 / 25 / 11 | sampled, see the set's total |
| [`ui-toolkit.md`](ui-toolkit.md): UI toolkit: widget classes and their behaviour | 785 | 90 / 10 / 4 | sampled, see the set's total |
| [`world-objects-rendering.md`](world-objects-rendering.md): World presentation objects: goods, streets, decals, sky and the render engine layer | 1210 | 148 / 22 / 8 | sampled, see the set's total |
| [`lobby-world-client.md`](lobby-world-client.md): The 3D lobby village on the client | 1159 | 190 / 17 / 10 | sampled, see the set's total |
| [`lobby-screens.md`](lobby-screens.md): Lobby screens and dialogs | 1590 | 240 / 28 / 3 | sampled, see the set's total |
| [`lobby-client-state.md`](lobby-client-state.md): Lobby client state: managers, proxies and observers behind the wire | 1807 | 300 / 66 / 5 | sampled, see the set's total |
| [`minigames-client.md`](minigames-client.md): Tavern minigames on the client: Dice, Poker and Pawn Chess | 1183 | 273 / 26 / 10 | sampled, see the set's total |
| [`lan-and-transport.md`](lan-and-transport.md): LAN discovery and the TinCat transport under the match session | 1174 | 73 / 10 / 8 | sampled, see the set's total |
| [`map-editor-devtools.md`](map-editor-devtools.md): Map editor and developer tools inside the client | 1043 | 82 / 11 / 4 | sampled, see the set's total |
| [`lobby-extras.md`](lobby-extras.md): Lobby extras: physics and collision, web textures, lobby data files | 812 | 53 / 27 / 3 | sampled, see the set's total |
| [`engine-core.md`](engine-core.md): Engine core primitives: streams, serialisation, containers, math and utilities | 1270 | 94 / 17 / 2 | sampled, see the set's total |

## What is not covered

- The original servers' behaviour where the client gives no evidence of it (for example how a wager was paid out in a
  match of more than two players: the client reports one winner and never sends the teams).
- Struct layouts of the in-game menu classes are described by behaviour here; in the Ghidra map many of their fields are
  still unnamed.
- Questions that only the running game can answer are listed in each document's section 10 and collected in
  `docs/live-session-queue.md`.
