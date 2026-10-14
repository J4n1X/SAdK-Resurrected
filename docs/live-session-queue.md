# Live session queue

The open checks that need the running game (Frida MCP `frida-sadk`, server log). Each entry settles one
statement that the docs carry as `[inferred]` or `[TODO]`. Results of done checks live in the specifications
(`docs/sim/*.md`, `docs/message-catalog.md`, `docs/types.md`, ...) and in git history. Addresses: `S` =
sadk_noav.exe, `T` = tincat3.dll. Hooks only observe unless an entry says otherwise. Entries marked **needs
permission** write game memory or change what the server sends, and need the maintainer's explicit go-ahead first
(`HARNESS.md` §2).

**Rule (maintainer, 2026-10-14): a live test may only be asked for when the behaviour cannot possibly be read from
code.** Read the code path to its end first. What qualifies: what the screen or the speaker shows, timing of real
networks and hardware, libraries that cannot be read (packed `fmod.dll`, drivers), the original servers' behaviour.
Confirming a reading is not a reason for a live test.

## Standing notes (maintainer, 2026-10-12)

- Mail, buddy lists, whispers, the shops (they open and list their items) and per-match server mods work in live
  play; they need no check beyond the specific entries below.
- Accounts are created at the first login; the client's registration form is not used, because it needs a CD key
  many players no longer have. A failed login therefore means the name exists with another password.
- There is no third test player. Entries that need three players stay open and rest on static evidence.

## Lobby and account

- [ ] **LobbyMessage `+0x38`.** One outgoing message (`SendPing` S 0046c150) and one incoming
  (`HandleMessage` S 00470a90).
  Observe: read watch on `msg+0x38`.
  Settles: types.md §1.8, `+0x38` (write-only `[inferred]`).

## Shop

- [ ] **ItemsClient.txt tokens 3 and 4.** Stack, split, equip and sell items.
  Observe: read watches on `ItemInfo+0x3c` and `+0x44` of one item.
  Settles: village doc §4.3 (meaning of tokens 3 and 4 `[TODO]`; by reading, token 3 has no reader and token 4's
  only reader is `IsValid` S 0048b100).
- [ ] **Sell price at a shop that does not list the item.** Sell an item at the shop whose stock does not carry it.
  Observe: the price in the confirm box (`GetShopSellPriceByItemId`; expected base value x SellMod 0.9) and the gold
  credited.
  Settles: message-catalog 0xE24 (the client's value for an unlisted item `[TODO]`; the listed case is settled).

## Pre-game room and match start

- [ ] **Map fetch branch.** **Needs permission** (writes game memory on the host). With a user map the
  joiner lacks, set session `+0x228` to 1 on the host.
  Observe: on the joiner, `RequestFileFromHost` S 004084d0 runs and the `.s2m` / `.bmp` arrive instead of
  the kick.
  Settles: types.md §2.2, `+0x228` (name `[inferred]`). Narrowed by reading: `+0x228` / `+0x229` are plain
  arguments of `SetGameSettings`.

## Wager dialog

- [ ] **Maximum of the bet dialog.** The host opens the bet dialog and tries a wager above his own gold.
  Observe: whether the dialog stops at the host's gold (`AvatarProxy +0xd0`; static: its maximum is that value).
  The maintainer's impression with a balance of about 100,000 was "unlimited".
  Settles: `match-setup-room.md` wager row (whether the dialog stops at the host's gold, not seen).

## From the specifications (docs/sim)

Sources: §10 of every `docs/sim/*.md` (§11 in `minigames-client.md`) and the body statements that name an
observation. Most entries need one player alone; the network-match entries need a second player, the three-player
entry a third (none available). **Needs permission** applies to the entries marked so.

### Main menu and settings

- [ ] **Activate-main latch and Info gate.** Use the main menu and drag a dialog by its title bar.
  Observe: write watches on `Main +0x228` and `Overlapped +0xbfc`: no write = both are dead; a write names the
  writer.
  Settles: `frontend-screens.md` §2.1, §3.11, §10 Q4.
- [ ] **Widget drawing details.** Look at a tiled frame whose size is no multiple of the tile, at an edit box
  caret, and at a boxed text with a narrow wrap width.
  Observe (screenshots): last partial tile squeezed or cropped; caret colour; a stale glyph where a break
  candidate overflows the line.
  Settles: `ui-toolkit.md` §10 Q4, Q5 (§3.1).

### A free game alone

#### Settlers and transport

- [ ] **Blocked flag.** Block a flag so that a loaded street carrier cannot put his good down.
  Observe: hook S 006513b0 (the attempt counter `pkg +0x104`): attempts per tick, `!flag blocked` at every 180th
  attempt, the good's return to a storehouse after 360; the real time of both.
  Settles: `settlers-jobs.md` §3.6.2, §10 Q5. Known so far (2026-10-12): a street carrier in state 0x12 tries every
  tick for 13 to 42 ticks, then every 10th tick, with `!flag blocked` at the 180th attempt; no street carrier has
  reached 360 yet. A carrier not yet on a street (state 1) and a worker's product have no limit. Left: a street
  carrier at 360 and the return of his good.
- [ ] **Carrier swap at full flags.** Two crossing streets with full flags.
  Observe: hook `CanSwapPackagesAtFlag` S 0064d120 and `FindSwapPackageAtStreetEnd` S 0064d750; the two
  carriers' street references every 200 ticks; whether the jam resolves. On two upgraded streets that both lost
  their first carrier: the end flags' kind-0 ids afterwards.
  Settles: `settlers-jobs.md` §3.6.2, §10 Q4; `streets-transport.md` §3.5, §10 Q4. In normal play jams resolved
  within 261 attempts; the set-up of this entry has not been built.
- [ ] **Settler release with several units in stock.** Keep a casern or an oxen breeder stocked with more than one
  unit.
  Observe: the worker's state in S 0065d7f0 and the settlers released per stay in 0x24.
  Settles: `settlers-jobs.md` §10 Q1 (one unit per cycle gives one release, then rest; several units not seen).

#### Military

- [ ] **Emptied building: border and capacity limit.** With the default sliders, an occupied far building that
  wants 0 soldiers (guard hut) and one that keeps 1 (tower, fortress).
  Observe: whether the emptied building's border stays; the capacities of the three building types, to find the
  limit that separates a wanted size 0 from 1.
  Settles: `military.md` §3.2, §10 Q1.

#### HUD and statistics

- [ ] **Defeated player.** Lose a free game and stay on the `Defeat` dialog.
  Observe: whether selection still works and whether the explored area changes (the camera still moves, maintainer
  2026-10-12).
  Settles: `hud-panels.md` §3.10, §10 Q4.
- [ ] **Marker on attackable buildings.** Look at enemy military buildings in reach and out of reach.
  Observe: any marker of its own besides the selection and the attack slider.
  Settles: `hud-panels.md` §3.6.2, §10 Q5.

#### Camera and input

- [ ] **Writer of `zoomMax`.** Start or load a match.
  Observe: a write watch on `nGame::Camera +0x1c` (`zoomMax`) during the world build: the writing module (the
  `d3d9.dll` proxy in the install's `bin` folder is the candidate) and the value (6.0 in the reference install).
  Settles: `camera-input-cutscenes.md` `zoomMax` row (`[inferred]` writer).

#### Audio

- [ ] **Loudness over distance.** Record one building sound at several camera distances.
  Observe: the level curve of the recording.
  Settles: `audio.md` §10 Q10.

#### Rendering

- [ ] **Reference screenshots.** Take: a shore at shader level 2; settlers at shadow levels 1 to 3; the sky; one
  walking settler from close up.
  Observe: the look of shallow water; a blob shadow under settlers (none expected); the settler's facing and face
  winding for comparison with a converted model. Sun and moon need no look: their quads are built, but no code
  reads the pass that would draw them (`SkyRenderer.hSunPass`; settled by reading, 2026-10-13).
  Settles: `rendering.md` §10 Q15; `world-objects-rendering.md` §3.9, §10 Q4, Q6; `animation-models.md` §10
  Q1, Q2.

#### Saving and loading

- [ ] **Saves in special states.** Save during a cutscene and during a sacrifice animation; load each.
  Observe: whether the save dialog opens at all while the cinematic screen is up; the first ticks after each
  load.
  Settles: `save-format.md` §10 Q3; `camera-input-cutscenes.md` §7, §10 Q5. The pause half is done (a save made
  during a pause does not come back paused, live 2026-10-14). Narrowed by reading: `nMenu::System::EmergencySave`
  S 005da7d0 and the battery-low message are the other paths that save in a special state.

### The lobby village alone

- [ ] **Limits of the walkable area.** Walk along the inner walls, to the map edge and up the steepest slope.
  Observe: the avatar's position: whether it passes ±125 or sinks below the meshes; the steepest slope it climbs
  (60 degrees as read).
  Settles: `lobby-extras.md` §6.2, §10 Q5 (Q10 is answered by reading, 2026-10-14). Narrowed by reading: whether
  the collision mesh confines the avatar depends on the character library's slope rule; from a flood fill over
  the parsed collision mesh, faces steeper than 48 degrees enclose the origin, faces steeper than 60 do not.
- [ ] **Handedness of the world.** Compare one visibly rotated object with its `orientation` in the scene file.
  Observe: the sense of the three turns.
  Settles: `lobby-world-client.md` §3.1, §10 Q9.
- [ ] **Web board while loading.** Watch a board from the moment the village appears.
  Observe: what the texture shows before the page is complete.
  Settles: `lobby-extras.md` §10 Q9.
- [ ] **Lobby physics object, slots 2, 6 and 8: jump and reset-position.** Jump, and use reset-position.
  Observe: hooks on S 005210c0 and S 00523430 with the return address (walking, standing, sitting down at and
  leaving a minigame table call neither, live 2026-10-14).
  Settles: `Lobby::IPhysicObj` slots 2, 6 and 8 have no caller in the binary (`lobby-extras.md` slot table,
  `mapping/work/gaps_20261013/audit_B.md`, board #5776); a hit names the caller and so the slot.

### The pre-game room

- [ ] **First map of a new game.** Create a game and do not touch the map.
  Observe: the map shown (`MP_2P_fata_morgana` if the file system's first match is alphabetical).
  Settles: `match-setup-room.md` §10 Q2.
- [ ] **Game server connection while joining.** Join a room hosted by the other player.
  Observe: hook `GameServerConnection::Initialize` S 0048eda0 and `OnLoggedIn` S 0048edf0 (hosting and leaving a
  room called neither, live 2026-10-14).
  Settles: `lobby-client-state.md` §10 Q1.
- [ ] **A kick.** Two clients in a room; the host kicks the other.
  Observe: on the kicked client hook `cb_ConnectionClosed` S 0041bcc0, `cb_LoggedOut` S 0041b990 and
  `HandlePlayerLeft` S 00410720: which runs (connection closed as read).
  Settles: `lan-and-transport.md` §3.7, §10 row on the remote side of a TinCat `Disconnect` (`[inferred]`).
- [ ] **Unused transport timeouts.** One join and one leave in a room.
  Observe: read watches on driver `+0x60` and `+0x68`, a hook on T 10006cf0: no hit = `usrRemove`,
  `usrLogoffTimeout` and `drvRemoveTime` are unused.
  Settles: `lan-and-transport.md` §6.2, §10. Partial, live 2026-10-14: one join and one leave in a two-player room
  were run, but the getter T 10006cf0 (`drvRemoveTime`) is too short for a Frida hook, and read watchpoints on
  driver `+0x60` / `+0x68` stall the game. Left to the static reading: no caller of the getter and no reader of the
  two fields in the decompiled library.

### A network match with two players

- [ ] **Winner's avatar when the winning side's lowest index is remote.** Two players on one side against
  computer players, the lower index on the other PC; win.
  Observe: the Winner field of `FinishGame` (0xDC0) each client sends (server log), and on each client
  `DeclareWinner` S 00535990.
  Settles: `players-victory.md` §3.7 (which avatar each client puts into `FinishGame` `[TODO]`).
- [ ] **Save after a win, online.** Win a lobby match, save, load the save.
  Observe: a second `FinishGame` in the server log (offline the load declares the same winner again).
  Settles: `players-victory.md` §7, §10 Q8 (its open part: the second `FinishGame` in a lobby match).
- [ ] **A player leaves through the menu: the other side.** One player leaves mid-match.
  Observe: on the remaining PC the `!DEFEAT` letter and quest 0 of mode 1 advancing on the next tick.
  Settles: `players-victory.md` §3.6.1, §10 Q1 (the host's two 0x2002B calls are settled by reading).
- [ ] **Re-entry after a match: order against the character list.** Finish a match and return to the village.
  Observe: message 60 in the server log against `SelectCharacter` S 00472200 inside `ProcessModeTransition`
  S 004f5950 (the re-entry itself works, live 2026-10-14).
  Settles: `lobby-client-state.md` §3.17, §10 Q6.

### Three or more players

- [ ] **Host loss with two survivors.** The host's process ends mid-match.
  Observe: on both survivors manager `+0x2c`, `+0x48` and the first checksums after 0x3000f; the worlds after
  commands given just before the loss.
  Settles: `logic-core.md` §10 Q4; `network-session.md` §10 Q3; `game-commands.md` §3.2, §10.

### Map editor and developer tools

- [ ] **Editor at work.** **Needs permission** (opens the editor dialog with `nMenu::Game::ToggleScreen(game, 1)`
  S 005ea960 on the main thread). The dialog opens and runs; the Buildings, Elevations and `Infomap` tools run
  without a fault; `!Save Map` writes only over an existing file (`map-editor-devtools.md` §3.9).
  Observe: a read watch on `Scene +0x710` (what it gates); hooks on `TerrainGenerator::Run` S 006b24f0 and
  `CMapRenderer::RunTerrainGenerator` S 00688540 (a call = generator-dependent heights reach the simulation);
  `SetBatchEditing` S 00538a60 while editing; whether a second Enter restores the screen the first one blanked;
  the cause of the end on `!Load Map` (an empty path into `File_ReadAndDecrypt` `[inferred]`); the `editor` Lua
  library.
  Settles: `map-editor-devtools.md` §3.1, §10 Q2, Q3; `engine-core.md` §10 Q5; `navy.md` §10 Q1.
- [ ] **Lobby debug wireframe.** **Needs permission** (starts the CVar server in the running game,
  `map-editor-devtools.md` §10 Q7). Set `Lobby/Show GfxObjStd PhysicDBG` and look at a fence and the terrain.
  Observe: which render meshes the wireframe covers (which meshes collide) and the solid side of the triangles.
  Settles: `lobby-extras.md` §10 Q4, Q6.
- [ ] **Dormant LAN path.** **Needs permission** (calls `StartUpNetwork(2)` S 0040a9a0 and `BC_Start`
  S 0041aa90 on one PC, role 1 on a second).
  Observe: whether the role 1 client finds and joins the role 2 host.
  Settles: `lan-and-transport.md` §10 (last row); `network-session.md` §10 Q6.
- [ ] **Flag with more than 36 goods.** Play with a mod data file that raises `cfg_setFlagPackageLimit` (to 7 or
  more; shipped 2). May end the process.
  Observe: a good that finds no slot in its pile: where it is drawn (`ItemPile::AddItem` S 006cece0,
  `FindItem` S 006ce7a0 returning -1 / -1).
  Settles: `world-objects-rendering.md` §10 Q2.

### Left to reading, not to playing

These §10 questions need no live session; they stay open in their specifications until read.

- `logic-core.md` Q5, Q6: strings in the checksum stream; checksum writers against save writers.
- `logic-core.md` Q7, `players-victory.md` Q7: writers of `GameLoadDescriptor +0x24` (start-position shuffle).
- `logic-core.md` Q8: readers of `Stock::changeStamp`. Q10: render managers of `SyncLogicTick` S 00680550.
- `game-commands.md`: forged `0x2000D` against an own target; second float of a distribution entry; research
  reference `+0x12c` after `0x20027`.
- `players-victory.md` Q6 lock map 2 readers; Q9 result screens; Q10 statistics read by the AI; Q11 `used` byte.
- `village-buildings.md` Q4, Q5, Q9: `System+0xbc`, `Building+0x38`, `Depot+0x08`, served bytes, countdown
  writers. Q6: `FindHuntableAnimalAt` S 0053ee60.
- `settlers-jobs.md` Q7 sub-movie classes; Q8 floats in the soldier checksum.
- `streets-transport.md` Q5 goods outside the priority list; Q6 goods list index 0; Q7 `SettlerMovement+0x38`.
- `map-resources.md` Q5 `elevationSize` and `GoodProperty+0x51`; Q6 directions 6 and 7; Q7 resource spawn
  points in the shipped maps (data scan).
- `military.md` Q3 unnamed fields; Q5 `Player+0x18`; Q6 reach and sea-attack helpers.
- `navy.md` Q2 `ShipConfig.size`; Q6 `HasFreeProductionOfType`.
- `ai-player.md` Q4 `ScoreSite`; Q5 functions not read line by line; Q6 old save versions; Q7 scripts inside
  skirmish maps.
- `properties-data.md` Q1 to Q3 field readers; Q4 deposit of a settler good (or a test map).
- `save-format.md` Q1 AI record layout; Q6 `Relink` bodies; Q7 `MapInfo` fields; Q8 flag-network map order;
  Q9 writers of `UserProfile +0x24`.
- `network-session.md` Q4 virtual calls on a received GUID; Q5 TinCat start-up values; Q6 LAN discovery
  messages; observer lists `+0x3d4` (§2).
- `lua-runtime.md` Q2 cutscene key time unit; Q3 building removal inside `vi_forEachBuilding`; Q5 unused
  `ui.set*` and `editor.*`.
- `quests-sacrifices-stats.md` Q1 `TribeProperty +0x50`, `MapInfo +0x204`; Q2 `pl_changePlayer`; Q5 letter
  addressee.
- `tribes-content.md` Q1 to Q7: ware group `weapons`, construction dummy types, military stock limits, tree
  creators without a forester, `sf_setBuffGfxName`, `items.xml` good attributes, Olympic flame worker.
- `camera-input-cutscenes.md` Q3 option ranges; Q4 untyped writers; Q6 terrain pick; Q7 follow anchor; Q8
  speaker flag; Q9 street overlay; Q10 `FileScan::ResolvePath`.
- `audio.md` Q5 to Q9: `nGame::Sound` byte, `SetHidden` callers, animation sound events, footstep position,
  `nMenu::Game` construction.
- `rendering.md` Q1 to Q10, Q12 to Q14, Q16, Q18 (each names its function).
- `animation-models.md` Q3 to Q14 (each names its function).
- `world-objects-rendering.md` Q1 group goods; Q3 `points0`; Q5 `decals.dds`; Q7, Q8 shader globals; Q9
  animated items.
- `ingame-ui.md` Q1 to Q4, Q6, Q8 to Q11. `hud-panels.md` Q1, Q2, Q7 to Q10.
- `formats-inventory.md` Q1 to Q8, Q10, Q11, Q13.
- `app-shell.md` Q1 to Q6, Q8, Q12. `engine-core.md` Q4, Q7. `frontend-screens.md` Q3. `ui-toolkit.md` Q2, Q3.
- `lan-and-transport.md`: relation to the `CommLayer` LAN classes of `tincat3.dll`.
- `lobby-client-state.md` Q2, Q4, Q7, Q8. `lobby-extras.md` Q2, Q3, Q7, Q8 (PhysX and MSHTML headers, mesh
  loading, class-name case).
- `lobby-screens.md` Q2, Q3, Q5, Q6, Q8, Q9. `lobby-world-client.md` Q4, Q5, Q7, Q10, Q12, Q14, Q15, Q17, Q18.
- `match-setup-room.md` Q6 readers of `slot_<n>.avo`; Q7 caller of vftable slot 24.
- `minigames-client.md` §11 Q3, Q5, Q8, Q9. `map-editor-devtools.md` Q6, Q8.

### Not answerable from the client

- `match-setup-room.md` Q4: which original server moved the wager, and the pay-out rule above two players.
- `minigames-client.md` §11 Q4, Q6: the original use of poker phases 2, 3, 4, 7 and bit 14; the original Pawn
  Chess piece order. Also the original meaning of `accnt` beyond what the client computes.
- `minigames-client.md` §10 rows 6 and 11 cannot arise with the present stub: it acts for a player who sits out
  during his own turn (so "back in" never finds the turn running), and it has no Pawn Chess input timeout (so no
  pending capture is timed out). They need a server that leaves the turn running or times a player out.
- `app-shell.md` Q7, Q11: the reader of `crashmsg.ini` and the retail `engine.ini` (an untouched install).
- `save-format.md` Q5: which build wrote `.sav` (type 10) files (a save of an old installation).
- `formats-inventory.md` Q12: the `.lep` body (the map editor's own binary, not in the install).
- `audio.md` Q11: whether Godot's WAV loader takes the install's ADPCM and float files (a test in Godot).

## Done checks

Done checks: their results are in the specifications; the queue as it was before pruning is in git history
(commit a4ff535).
