# docs/ — Documentation index

> Reverse-engineering notes, heavily AI-assisted. `[PROVEN]` = binary address + live
> evidence; `[TODO]` = unverified. Addresses may refer to an older game build — see the
> base caveat in `SOURCEMAP.md`. `MEMORY.md` (repo root) is the compact current state.

| File | Contents |
|------|----------|
| `SOURCEMAP.md` | Named functions, structs, globals, vtable slots (the firmest RE reference). |
| `LOBBY_PROTOCOL.md` | TinCat / NETMSG protocol reference (endpoints + message types, msgdefs-grounded). |
| `BINARY_PATCHES.md` | The two runtime patches that boot the genuine exe past SecuROM on Win10/11. |
| `REVERSE_ENGINEERING_GUIDE.md` | Asset decoding: the KEX/sadk decrypt workflow using AdKEd.exe. |
| `UI_FINDINGS.md` | UI screen-system verdict (no file-edit shortcut) + the AdKEd decrypt workflow. It specifies no screen: the screens are in `sim/`. |
| `sim/` | The specifications a remake (Godot, shipped without the original data) is built from: one document per subsystem of the client, stating behaviour, rules, constants, order of operations and data formats, each tagged `[known]` (read at an address `S 00xxxxxx` / `T 10xxxxxx` or in a named data file and key), `[inferred]` or `[TODO]`; nothing in them was observed in the running game unless a dated live observation is cited. Simulation: `logic-core.md`, `game-commands.md`, `players-victory.md`, `village-buildings.md`, `settlers-jobs.md`, `streets-transport.md`, `map-resources.md`, `military.md`, `navy.md`, `ai-player.md`, `quests-sacrifices-stats.md`. Data and files: `properties-data.md`, `tribes-content.md` (the shipped content tables), `formats-inventory.md` (every file type), `save-format.md`, `lua-runtime.md`. Engine and presentation: `engine-core.md`, `app-shell.md` (start-up, user profile, `settings.cfg`), `rendering.md`, `world-objects-rendering.md`, `animation-models.md`, `audio.md`, `camera-input-cutscenes.md`, `map-editor-devtools.md`. UI: `ui-toolkit.md` (widgets), `ingame-ui.md` and `hud-panels.md` (the HUD), `frontend-screens.md` (main menu, options), `lobby-screens.md`, `match-setup-room.md`. Network and lobby client: `network-session.md`, `lan-and-transport.md`, `lobby-client-state.md`, `lobby-world-client.md`, `lobby-extras.md`, `minigames-client.md`. |
| `GAME_JOIN_CAPTURE_decoded.txt` | Decoded P2P game-join session capture (room/slot protocol is unreversed — `[TODO]`). |
| `live-session-queue.md` | Checklist of open protocol statements that a session at the game PC can settle. |
| `REFEREE_FUNCTIONS_TO_NAME.md` | Already-named referee functions — the starting point if the (removed) referee/match work is ever restarted. |
