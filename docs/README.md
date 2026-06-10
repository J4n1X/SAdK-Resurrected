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
| `UI_FINDINGS.md` | UI screen-system verdict (no file-edit shortcut) + the AdKEd decrypt workflow. |
| `GAME_JOIN_CAPTURE_decoded.txt` | Decoded P2P game-join session capture (room/slot protocol is unreversed — `[TODO]`). |
| `REFEREE_FUNCTIONS_TO_NAME.md` | Already-named referee functions — the starting point if the (removed) referee/match work is ever restarted. |
