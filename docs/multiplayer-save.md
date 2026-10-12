# Saving and loading a network match

Whether a multiplayer match can be saved and continued, how the game saves and loads today, and the design of the
`mpsave` mod (`mods/mpsave/`), which is built on it.

- Binary: the DRM-free `SADK.exe` (Ghidra `/sadk_noav.exe`). Tags: **[known]** = read in the binary at the given
  address (`S 00xxxxxx`); **[inferred]** = one step of reasoning from what was read; **[open]** = needs the running
  game, with what to observe; **[live]** = seen in the running game, with the date.
- Live, 2026-10-12, two players over the lobby, the maintainer hosting (mod log and the game's crash log):
  - saving in a network match works [live];
  - loading such a save offline from the load menu works, and the other player's seat is an AI player [live];
  - loading a save in the running match works with the mod's present load (teardown and rebuild, session kept): the
    host loaded four times in a row, two different saves, each load about 3 s from offer to "loaded" in the mod log,
    the map reloaded on both players' games, no crash and no `!DESYNC DETECTED` in the game's logs [live]. Not yet
    observed: play continuing in sync for long after a load, commands given just before a load, a third player;
  - the automatic resync works (`AutoResync = true`): a desync was provoked on the host by one extra draw from the
    simulation's random generator (`LogicRandom_Next` S 005389b0, called once through the debugger at net tick
    1284); the game logged `Prüfsumme zwischen Adresse 0xEFFFFFCC und 0x00000001 unterschiedlich` and `Resync`
    (`Manager.cpp` lines 1340 and 1356), the mod saved `mpsave_resync` (499 KB), sent it and both games loaded it
    6 s after the detection; no further checksum error in the following 30 s, the session stayed in state 4 with
    the net tick advancing [live];
  - loading in the network match with `nGame_File_load` into the running world crashed the host at `006B5874`
    [live]; the cause is in "The in-place load", the mod's present load in "Resuming a saved match", point 3.
- The assignment of players by name on a load ("Who plays which player", `AssignByName`) builds and the mod's
  patches match the binary (`make -C mods verify`); it is **not tested in the game**. The live results above were
  made with the seat rule, in which nobody changes players.
- The check of who sent one of the mod's events and the check that a save is of the session's map ("Who may send
  the mod's events", "The same map") were added after those live results and are **not tested in the game**. The
  mod's events and their texts are unchanged (format 2), so a game with the build of the live results and a game
  with the checks understand each other.

## Verdict

**Feasible with limits.** The save code is independent of the network: only the in-game menu keeps a network match
from saving [known], and saving in a network match works [live]. Loading is the limit: the game's load path ends the
network session, and a save cannot be loaded into the populated world (crash [live]; the scene is not prepared for
it [known]). So a network load runs the game's own leave and re-enter of the game screen, without its session calls,
at the same lockstep tick on every player; the binary has the pieces for that (the screen's leave and enter,
lockstep commands, a tick gate), but their combination is [inferred] and untested. Not covered by any save: the
network session itself (slots, pending commands), which is why a save is always loaded *into* a running match.

## How saving works today

| Step | What happens | Tag |
|---|---|---|
| Menu | The in-game menu (`cbMenu` of `nMenu::Game`) has the actions 0 Save, 1 Load, 2 Options, 3 exit to title/lobby, 4 exit to desktop. Save and Load open `nMenu::LoadSavePanel` (mode 1 / 0, `menuLoadSave.xml`). | [known] S 005eb310, S 0060ce40 |
| Save | `LoadSavePanel::Confirm` calls `GameFile_Save(0x6e, name)`; the default name is `<date> <time> <map name>`. Also: autosave (`nGame_Autosave_WriteSave`, timer `nGame::Autosave::Update`) and the battery-low save `_EmergencySave_`. | [known] S 0060d000, S 0060dd90, S 0078af30, S 0078b040, S 005da7d0 |
| File | `<My Documents>\SAdK\saves\<name>.aav` (map type `0x6e`; type 10 is the same folder with `.sav`). Container `NCore::FileStreamCrypt` (`docs/map-format.md` §1.2). | [known] S 0052c320, S 0052c1b0 |
| Content | Map part (`GameFile_SaveMap`: `NLogic::System::Save` with `MapInfo`, logic ids, tick timing and the **tick counter**; map, resources, doodads, ambients, navy, spawn system), then logic part (`GameFile_SaveLogic`): the **logic random generator** (8 bytes of state), player table, village, settlers, transport, military, street net, AI, statistics, game script, quests, sacrifices, chests. | [known] S 005aa260, S 005275c0, S 005a9ec0, S 005389c0; the map part's list of systems is read from the loader `GameFile_LoadMap` S 005aa7b0 [inferred] |
| Load, menu | The load panel hands the name to `nMenu::System::pendingMapPath`; at the end of `nMenu::System::Update`, `StartPendingMap` runs: (1) `DeactivateAllScreens`, which closes the game screen (`nMenu::Game::OnLeave`, next row); (2) `nGame::System::Shutdown` if the game still runs; (3) `GameLoadDescriptor::SetMapName` on the screen's descriptor (type `0x6e`, name); (4) **NComm `Shutdown`, `StartUpNetwork(0)`, `ConnectAndJoin`, `SetGameSettings`, `SetSlotSetup`** (a new offline session, slots from the file's `MapInfo`); (5) the statements of `nMenu::System::ActivateGameScreen`: `DeactivateAllScreens`, hide the message slots, current screen = game screen, `nMenu::Game::OnEnter`, `MinimapSymbolList_Clear`. | [known] S 0060dd30, S 005da500, S 005d9fd0, S 005d9e70, S 005a9c10, S 005d9f10 |
| Load, teardown | `nMenu::Game::OnLeave`: unregisters the screen's logic and map receivers, clears the session's chat and message sinks, **NComm `Shutdown`**, `DestroyHudWidgets` (the load and save panels among them), `nGame::System::Shutdown`, `Scene_DestroyGlobal`, `GameLoadDescriptor::Reset`. `nGame::System::Shutdown`: ends the street-building modes, clears the session's event handler (`NComm_Manager +0x50`), `ShutdownAndDestroyGameSystem`, `GameScript_DestroyMapScript`, stops cursor, camera, autosave and sound. `ShutdownAndDestroyGameSystem`: `NLogic::System::Shutdown` (**switches the logic callbacks off**, `callbacks->notifyEnabled = false`, then `Reset`: every system emptied, the map last; so no object's removal reaches the scene), unregisters the scene's receivers, deletes `g_pGameSystem`, shuts the renderer's scene down. | [known] S 005eb030, S 005ea650, S 007834e0, S 00781cb0, S 00527c40, S 00526f80, S 00526f30 |
| Load, world | `nMenu::Game::OnEnter` (HUD set-up, NComm `BeginGameStarting`, the two sinks, `Scene_CreateGlobal`, loading panel; after the world: local player entry, NComm `SendGameLoadedEvent`, HUD XML, `!START`) → `nGame::System::BuildWorld` (event handler `+0x50`, `BuildScene`: `GameSystem_Construct`, a new `g_pGameSystem`, receivers registered, `terrain_static_data.xml` and `map_objects.xml`; `GameScript_InitMapScript`; Lua libraries only offline) → `Game_LoadWorldFromDescriptor` → `nGame_File_load` → `GameFile_LoadImpl`: types 10/`0x65`/`0x6e` read map and logic part, then `GameFile_FinishLoad` (PostLoad of every system). The file is loaded into an **empty, new world**. A save type is not a "new game" type: no players are created, no chests distributed, `onStarted` is not called. After `nGame_File_load`, `Game_LoadWorldFromDescriptor` calls `MapModifier_InitAfterMapLoad` (`ConstructionMap_RecomputeAll` for every player, whose only other caller is `MapModifier_RecomputeConstructionMapAll` S 00672d90; territory and the local player's map are announced), then `GameScript_CallOnLoaded` (the script's `onLoaded`). `GameFile_LoadImpl` falls back to map types 10 and 3 when `<name>.aav` is missing and runs `GameFile_FinishLoad` even when no file could be opened; its result does not reach the caller of `nGame_File_load`. | [known] S 005eed00, S 00784d40, S 007842e0, S 005ac770, S 005aaed0, S 005aa1b0, S 00673000, S 00675790, S 005b2180 |
| Continue | "Continue" in the main menu loads the last save named in the user profile the same way; it refuses a file whose `MapInfo+0x1f0` is 2 or more (`GameFile_Save` writes 1). | [known] S 005dfef0 |

### The in-place load

The systems' `Load` functions empty themselves first (`NVillage::System::LoadBuildings` → `ClearBuildings`,
`NSettlers::System::Load` → six `ClearSettlerVector`, `PlayerTable::Load` → `RemoveAllPlayers`,
`NResources::System::Load` → `Reset`, `NDoodads::System::Load` → `Clear`) [known] S 00559a10, S 00656430,
S 005be1b0, S 00540fd0, S 00544ef0. That is not enough to load a save into a populated world: **the scene loses its
terrain cells' object lists before the old world's objects are removed from them.** `nGame_File_load(0x6e, name,
false)` in a running match crashes [live 2026-10-12: `EXCEPTION_ACCESS_VIOLATION at 006B5874`, `eax=0 ecx=3c3b2fc8
edx=0 esi=0`].

| Step | What happens | Tag |
|---|---|---|
| 1 | `GameFile_LoadMap` loads `NLogic::System` (MapInfo), then the map: `NMap::System::Load` ends in `NMap::CallbackManager::NotifyMapInitialized(width, height)` (listener slot 2). | [known] S 005aa7b0, S 00672030, S 00677db0 |
| 2 | The scene's listener is `SceneCb_ReinitTerrainGrid` (its only reference is the vftable slot at 007f8f10): `TerrainGrid::Init`, then `FUN_00688d20` → `CMapRenderer::InitForMap` → `Forward_Field20_Rebuild`: `CTerrainCellMgr::DestroyCells`, `CreateTerrainCells`. Every `TerrainCell` is new (`_eh_vector_constructor_iterator_` over the new array); that a new cell has `objectCount` 0 and `objects` NULL is [inferred] from the registers at the fault, `TerrainCell_ctor` was not read. The render objects of the old world still exist and are in no cell's list any more. That 007f8f10 is slot 2 of the scene's `NMap` receiver is [inferred] from the slot the notifier calls. | [known] S 0067efe0, S 00688d20, S 006883e0, S 00689e00, S 006b7170, S 006b73b0 |
| 3 | The next loader, `NResources::System::Load`, calls `Reset`: every old deposit is deleted. `NResources::Deposit::dtor` calls `NotifyDeposit_Slot4C` for a deposit with growth above 0; the callbacks are on. (`NDoodads::System::Load` → `Clear` → `Object::dtor` → `NotifyDoodadDestroyed` is the same for doodads, and follows.) | [known] S 00540fd0, S 0053f0b0, S 005430a0, S 005441e0, S 00545190 |
| 4 | `S2CG::Scene::OnDepositRemoved` (`OnDoodadRemoved`) → `MapObjLayer::RemoveInstance` → `InstanceMeshRenderer::RemoveInstance`: `instanceListener->vtbl[1](instance, &position)`. | [known] S 00681650, S 00681730, S 0068e330, S 006b94c0 |
| 5 | Slot 1 of the `CTerrainCellMgr` vftable 007fad9c is `FUN_006b70c0` (its only reference is that slot): cell from the position, `TerrainCell::RemoveObject`. With `objectCount` 0 the search loop is skipped, `0 < 0 - 1` (unsigned) passes, and `objects[objectCount - 1]` reads through the NULL array: the fault at 006B5874. That the instance listener is the cell manager is [inferred]: `AddInstance` calls the listener's slot 0 and `RemoveInstance` its slot 1 with (object, position), the signatures of the cell manager's slots 0 and 1. | [known] S 006b70c0, S 006b5840, S 006b90a0 |

Which object's removal faulted (the first deposit with growth, or a later doodad) is [open]; the crash log has no
stack. `Notify_Slot00(0)` before the load does not prevent it: `Scene::OnWorldLoadStateChanged(false)` only marks
the map renderer inactive and uninitialised (`CMapRenderer::SetActive`), it removes no object [known] S 0067eed0,
S 00688cd0.

The game's own load never meets this: the old world is destroyed with the logic callbacks switched off and the
scene is shut down as a whole ("Load, teardown" above), and the file is loaded into a new, empty world. The map
editor's load button calls `nGame_File_load(1, name, true)` on the running world [known] S 00609130; whether that
is safe there (a map file, an editor world) is [open].

## Why a network match cannot save

Three checks of `NComm_Manager_IsRole0` (mode `+0x3c8 == 0`, offline) [known] S 004083d0:

| Where | Effect in a network match | Tag |
|---|---|---|
| `nMenu::Game::LoadFromXml` | `DropDownMenu::RemoveItemAt(cbMenu, 0)` twice: the Save and Load entries are removed (the entries' action numbers are assigned before, so the others keep 2, 3, 4). | [known] S 005ecaf0 (call at 005ecfcf) |
| `nMenu::Game::OnMenuComboSelected` | Actions 0 and 1 do nothing. | [known] S 005eb310 (calls at 005eb391, 005eb4b0) |
| `nGame::Autosave::Update`, `nGame_Autosave_WriteSave` | No autosave. | [known] S 0078b040, S 0078af30 |

`GameFile_Save` itself asks only once, to record the name for "Continue" in offline games [known] S 005aa260. **It is
a UI gate; the save code does not depend on single-player state.**

Leftovers of a multiplayer save the developers began: the event class `NComm::EventSaveGame` (wire tag `0x55550808`:
savegame name + GUID) exists only as a deserialiser; nothing creates, sends or handles it [known] S 00420440,
S 00420540. The folder name `mp_saves` is used only for a map preview picture `<name>.mps.bmp` [known] S 004bdc60.
There is no path that starts a network game from a save: `SetupGameDialog::SetupSession` always writes map type 0,
and `GameFile_FindMapByGuidAnyType` does not search the save folder [known] S 004562d0, S 005ac2f0.

## What a multiplayer save must contain

| State | In the save? | Tag |
|---|---|---|
| Simulation (all of the above), logic random generator, tick counter | yes | [known] S 005a9ec0, S 005389c0, S 005275c0 |
| Everything the desync checksum covers (random, players, village, settlers, transport, military, navy, street net, AI, logic ids) | yes: each is also in the save | [known] S 00784080 |
| Per player: index, colour, tribe, team, **kind** (1 AI, 2 local human, 3 remote human) | yes; the kind is the saving player's view, and the checksum leaves it out | [known] S 005be3c0, S 005be6e0, S 005abb60 |
| `MapInfo`: per-player controller (`+0x48`), tribe, colour, team; "is client" byte `+0x1ec` | yes | [known] S 004562d0; who reads `+0x1ec`: [open] |
| NComm game information (slots, owner GUIDs, GameID, GameSeed `+0x22f`, wager) | no | [known] S 005a9ec0 |
| GameSeed | not needed: it only seeds the chest distribution of a new game | [known] S 005ac770 |
| Net tick, sub-tick, queued and pending command packages, checksum log | no; they belong to the session | [known] S 00411990 |
| Map script: the Lua state | no (`docs/lua-surface.md`); a network match registers no Lua libraries | [known] S 00784d40 |

So a save holds the whole deterministic state, and what it lacks is exactly the session. Two players' saves of the
same tick differ only in the player kinds [inferred].

## Resuming a saved match

Loading into a running match needs no session data: the session of the running match is used. What must hold:

1. **The same file on every player.** The host's file is sent; a player's own file of the same name counts only
   with the same CRC-32.
2. **The same tick.** A lockstep game command is executed by every game at the same net tick: commands queued with
   `NComm_Manager::QueueGameCommand` travel in the tick packages and run in `AdvanceNetTick` →
   `ExecuteEventPackage` → `HandleEvent`, at the start of a logic tick [known] S 00408b10, S 00411990, S 00410530,
   S 00527070. At that point the sub-tick counter is 0 on everyone. If every game then stops ticking
   (`NComm_Manager_CanAdvanceTick` false ends the tick loop [known] S 00527070) and loads before its next tick, all
   continue from the file's state at the same net tick [inferred]. What a game still simulates in the tick the
   command arrived in is replaced by the load. The net tick, the sub-tick and the queued commands are the
   manager's and are not touched by the load; the logic tick timing and counter come from the file [known]
   S 00527d60.
3. **The session kept.** The world is replaced the way the game's own load replaces it ("Load, menu", "Load,
   teardown", "Load, world" above), without step (4) and with the three session calls inside the screen's leave and
   enter doing nothing: `NComm_Manager::Shutdown` (in `OnLeave`), `BeginGameStarting` and `SendGameLoadedEvent` (in
   `OnEnter`). What the rest of that path does to the session, and undoes itself: `OnLeave` clears the chat and
   message sinks and `OnEnter` sets them; `nGame::System::Shutdown` clears the event handler `+0x50` and `BuildWorld`
   sets it; `BuildWorld` calls `BroadcastStartGame` only in state 3 [known] S 005eb030, S 005eed00, S 007834e0,
   S 00784d40. `BeginGameStarting` in state 4 would only log an error and return false; `SendGameLoadedEvent` in
   state 4 would broadcast GameLoaded (`0x30004`), on which every game sets the sender's connection state and the
   host broadcasts the game information again [known] S 0040b170, S 00408e50, S 0040e560. Between leave and enter
   no event is executed: both run inside one frame, before the game's own frame [inferred]. `OnEnter` also calls
   slot 1 of the lobby object (`CLobby::ReleaseTextures`) when there is one, as at every match start [known]
   S 005eed00. Every game is stopped for the seconds the world takes to build; whether the session tolerates
   that in state 4 as it does in state 3 at the match's start is [open].
4. **The same players.** A save's player *i* is played by whoever has player index *i* in the session's slots
   after the load command. The host decides that mapping and sends it with the load command ("Who plays which
   player" below). To continue an old match, the same players start a new match on the same map and the host loads
   the save; with `AssignByName` they need not take the start positions they had.
5. **Kinds.** After the load (`GameFile_FinishLoad`) each game makes its own player (the player index of its own
   slot) kind 2 and the file's kind 2 a 3. `OnEnter` then takes the kind-2 player as the screen's local player
   (`PlayerTable_FindLocalPlayer`, chosen because the descriptor has a map name) [known] S 005eed00.

An event that carries the load command exists in the game only as the unused `EventSaveGame`; the mod uses
`NComm::EventText` (the chat event, built by `EventText::ctor` [known] S 00409ea0) with ids of its own. Every event,
lockstep or immediate, passes `NComm_Manager::HandleEvent`, which is where `sadk::events::on_net_event` listens;
events `HandleEvent` does not consume go to `nGame::System::HandleGameCommand`, whose switch ignores unknown ids
[known] S 00410530, S 0040fd80, S 007845a0. That `HandleEvent` returns false for an unknown id is [inferred] from
the game commands (`0x2xxxx`) reaching the sink [open: no "Error Executing Event" line in the log].

**The file.** Two ways:
- *S2TFTP* (`NComm_Manager::RequestFileFromHost`, `docs/s2tftp.md`): the host serves `<My Documents>\<name>`
  unchecked, so `SAdK\saves\<name>.aav` would work in the plain game [known]. But assetshare restricts serving to
  maps and its own files and the landing place to the maps folder, so with assetshare (every lobby player) the
  request is refused on both sides; whether a transfer runs during a match is [open].
- *In the event stream* (what the mod does): the file as base64 pieces in `EventText` events, sent like chat
  (`BroadcastEvent` [known] S 0040fd80). Needs nothing but what chat needs. An event's text is written with a
  16-bit length that is used as a signed number (`NComm::MemoryStream::WriteString` / `ReadString` [known]
  S 004123a0, S 00412400), so a text must stay below 32768 characters. [open: the largest event the
  connection carries; the mod stays below the 4 KB an S2TFTP block has.]

**The same map.** A save of another map loads in a match: the load rebuilds the whole world from the save, so the
map the match was set up on does not matter [live 2026-10-12, maintainer's test with an earlier build]. What then no
longer agrees with the world is the session's own map information (the map GUID and name the game reports to the
referee, e.g. in `FinishGame`) [inferred]. Saves are nevertheless kept to their map by default (`SameMapOnly = true`, maintainer's decision 2026-10-12);
`false` lifts it. With the check on, a load from the menu is refused on the host, before anything is
sent, when the save was made on
another map than the session's (`save_is_of_this_map`; the message names the session's map). The comparison is the
game's own for "does this joiner have the host's map": the session's map GUID
(`EventGameInformation::GetMapGuid`, turned into an `NCore::UUID` by `NetGUID::ToUUID`) against the UUID in the
file's `MapInfo` (`+0x1d4`, through its accessor S 00529520), with `NCore::UUID::Equals`, which compares the 16
bytes [known] S 0040e560, S 005ab3d0, S 00413c20, S 004163e0, S 005a9d00. The session's GUID is the UUID of the map
file the host chose (`SetupGameDialog::OnMapSelected`: `NetGUID::ctor_FromUUID` of that file's `MapInfo` UUID)
[known] S 00454ad0. A save holds the UUID of the map it was made on: `MapInfo::Load` reads it from the map file
into the world's `MapInfo`, and `MapInfo::Store` writes it into the save while it is valid [known] S 0052bd40,
S 00529db0; a load of a save puts the save's UUID into the world again, so saves of a continued match keep it
[inferred]. Two limits:
- A map file from before `MapInfo` version 7 has no UUID; `Load` generates a random one at every load, and `Store`
  writes a new random one for a `MapInfo` whose UUID is not valid [known] S 0052bd40, S 00529db0. For such a map
  the session's GUID, the world's and a save's all differ. The mod therefore applies the check only when the
  running world's own `MapInfo` has the session's GUID; otherwise it logs `map check skipped` and lets the save
  pass. Whether such a map can be played in a network match at all is [open] (the joiners' search by GUID would
  not find it [inferred]).
- Two files with the same UUID are the same map to the check (a copy of a map edited without a new UUID), as they
  are to the game's own join check.

The resync does not ask: its save is of the running match. The map name in `MapInfo` (`+0x24`) is not used: it
has no accessor in the map.

**A player without the save.** The host queues the load only when every connected human has confirmed the file
(120 s after the last piece was sent, then the load is cancelled and nobody loads). A game that executes the load without the file stops ticking
and tells its player to leave; the others see the game's "hanging" notice until that player is gone.

### Who may send the mod's events

**What an event says about its sender** [known]. Every event starts with the sender's net id (`+0x08`) and slot
(`+0x0c`); both are what the *sending game* wrote when it built the event (`EventText::ctor`; chat and the mod pass
`NComm_Manager::GetLocalNetId` and the local slot) S 00409ea0, S 00410410. Nothing on the way checks or replaces
them:

| Path | What happens to the sender | Tag |
|---|---|---|
| Immediate event (TinCat module `0x27d9`, message 1000; chat, the mod's offer, pieces, abort and "have") | `BroadcastEvent` sends the serialised event to every user (`TinCatNetwork::SendToAll`, TinCat id `0xEFFFFFDD`), not through the host. The receiver's `cb_Received_Data` gets the transport's sender id but passes only the bytes on (`AppendReceivedImmediateEvents(len, data)`); the event is built from them with the header as sent. | [known] S 0040fd80, S 0041dbb0, S 0041d720, S 004082c0 |
| Lockstep command (message 1001 joiner → host, 1002 host → all; the mod's LOAD) | The host accepts a joiner's package when the *transport's* sender id has a slot (`FindSlotByPlayerId`), then copies its events byte for byte into the tick package (`TickPackageList::AddReceived` → `TickPackage::AppendEvents`), which goes to everyone. The events' headers are the joiner's. | [known] S 0040e0d0, S 00412ae0, S 00412e80 |
| The slots' player ids | A slot's net id is itself taken from an event's header: the host gives a joining user the slot id `ev->sourceNetId` of its `EventUserInformation` (`AssignSlotToJoiningUser`). | [known] S 0040e560 (case 0x30001) |

So **a sender cannot be proven**: a changed game can put any net id and slot into an event, immediate or lockstep,
and the game's own handlers trust the header in the same way (a leave `0x3000a`, a rejoin `0x3000e` and the
checksum `0x30009` all take `ev->sourceNetId`) [known] S 0040e560.
Whether the transport's sender id (TinCat, or the lobby's bridge) is itself reliable was not looked at; it does not
reach the event in either path.

**The host's id** [known]. A hosting game's own net id is `0xEFFFFFCC` (`TinCatNetwork::StartUp`), which is also
the id joiners send to (`SendToHost`) and the id `NComm::PlayerInfo::IsHost` tests a slot for S 0041e610,
S 0041db50, S 00414eb0. The host's slot gets it like any slot, from the host's own `EventUserInformation` [inferred]; the
slots travel to the joiners with the game information. That a joiner's copy has the host's slot with that id is
[inferred] (`PlayerInfo::Serialize` S 00415060 was not read; `nMenu::NetInfo::RefreshInfo` S 005fd5a0 labels the host by it)
[open: the first load with the check shows it; a joiner whose copy differs logs `ignoring mpsave events of net id
...: its sender is not the host` and never answers the offer]. After a host change (`Reconnector`) the ids were not
followed [open].

**The check** (`net_event`). An event with one of the mod's ids (`0x20f11`..`0x20f15`) is used only when:

1. its vftable is `NComm::EventText`'s (007d43a8, the one both `ctor` and `ctor_Deserialize` write [known]
   S 00409ea0, S 00420340). The generated headers have no constant for that address, so the mod reads it once from
   an `EventText` it lets the game's constructor build. Only then is the event read as a text event;
2. offer, piece, abort and LOAD: its net id is the player id of the slot that `PlayerInfo::IsHost` accepts;
3. "have": this game is the host, the event's slot is a human slot with a connected player other than the host,
   and the event's net id is that slot's player id. On a joiner a "have" is ignored without a word (every game
   receives it).

An event that fails is ignored; the mod log gets one line per sender net id (`ignoring mpsave events of net id
...`) for the session. A LOAD must be decided alike by every game: the event's bytes are the same on all, and the
host's id comes from each game's copy of the slots, which agree while the game information is in sync [inferred].

**What it protects against, and what not.** It keeps out events of games that are honest about themselves: a
joiner's game that offers a file or queues a LOAD (a mod bug, a second mod using the ids), an event of another
class under one of the ids, a "have" for a slot nobody plays. It does **not** protect against a changed game: such
a game can name the host as the sender of an offer, of pieces or of a LOAD, and every game would follow (a forged
LOAD stops and reloads all games, with a file of the forger's choice if a forged offer went before). Closing that
needs something a joiner cannot write, which the event paths do not carry.

### Who plays which player

**Where the game keeps it** [known]. Nothing in the simulation says which human plays a player. The session does:
each of the six slots (`NComm::PlayerInfo`, in the manager's `EventGameInformation`) has a player index (`+0x3a`),
and every use goes through it:

| Use | How | Tag |
|---|---|---|
| A command's player | the event carries the sender's *slot* (`+0x0c`); the executor turns it into a player index with `NComm_Event_GetSenderPlayerIndex` → `EventGameInformation::GetSlotPlayerIndex` (the slot's index, -1 for a slot at or above `maxPlayers`) | [known] S 00412490, S 00413290 |
| The local player's index | the index of the slot whose owner GUID is the local one (`NComm_Manager::GetLocalPlayerIndex` → `GetPlayerIndexByGuid`); used by the street and flag executors and allied chat | [known] S 00408300, S 00413200 |
| The winner's avatar for the referee | `VictoryConditions::DeclareWinner(w)` → `FindSlotByPlayerIndex(w)`: the **first** slot with that index, no test of the slot's kind; `FinishGame` names that slot's avatar id | [known] S 00535990, S 00413380 |
| A leaver's player | the host takes the player index of the leaver's slot for `EventUserLeft` and the command `0x2002B` | [known] S 0040e560 (case 0x3000a); `docs/sim/network-session.md` |
| Allied chat | `ArePlayersAllied(a, b)`: the *team bytes of the slots* found by player index, not the players' teams | [known] S 00413780 |
| The checksum event | identified by slot and GUID; the player index is only tested for "has one" | [known] S 004089c0 |

A new match writes the slots' indices into the world once, at its start (`SetupSession`: kind, name, tribe, colour
and team of each slot go to `MapInfo`'s entry of the slot's player index) [known] S 004562d0. After that the
slots' indices are only read. So **changing the player index of a slot is what changes whom a human plays**, and
it is the only thing: the same slot number is in every command that human sends, and each game looks the index up
in its own copy of the slots [inferred from the table above].

**The names** [known]. `SetupSession` copies each slot's name into `MapInfo`'s name of the slot's player index
(when the name is not empty) and sets the controller to 2 for the slot with the local GUID, 3 for another human, 1
for an AI slot S 004562d0. `MapInfo::Store` writes the eight controllers, and the eight names unless `+0x1f4` is
set, into the save S 00529db0; nothing sets `+0x1f4` (`docs/sim/save-format.md`) [inferred]. A network save
therefore holds, per player index, the name of the human who had it when the match started; a load does not
change the names, so a later save of the continued match has the same ones [inferred]. `GameFile_LoadMapInfo`
reads a file's `MapInfo` through a cache file, which is used only while it is newer than the save and is written
again (with the same `Store`) otherwise S 005aaa30, S 005aa030. The names in a save have not been looked at in a
real file [open: the mod log of a load with swapped seats shows whether the names matched].

**The rule** (`assign_players`, host only, `AssignByName = true`). "Playing human": a human slot with a connected
player. "Human player of the save": controller 2 or 3.

1. A playing human whose name equals the name of a human player of the save gets that player. Names are compared
   byte for byte (case and spaces count). A name is no match for anyone when it is empty, when two playing humans
   have it, or when two human players of the save have it.
2. A playing human without a match keeps the player index of their slot when that is a human player of the save
   and step 1 gave it to nobody.
3. A playing human who is still without a player stops the load: the host is told the names and nothing is sent.
   Two humans on one player cannot result (step 1 is one to one, step 2 gives away only a free player).
4. Every other slot (AI, closed, a human who left) keeps its index. If a human now has that index, the slot gets
   one of the indices the humans gave up (lowest first, in slot order), so that no two slots share an index:
   `FindSlotByPlayerIndex` returns the first slot with an index, and `DeclareWinner` would name the wrong avatar.

Consequences of the rule as it is: a renamed player in the same seat is placed by step 2; a renamed player in a
*swapped* seat is not placed (their seat's player went to the other by name) and the load is refused. With
`AssignByName = false` nobody changes players and the save is refused unless every human slot's index is a human
player of the save. A resync never looks at names: every slot keeps the index it has.

**Human players of the save that nobody takes.** They are loaded as they are, with kind 3 (the saver's own, kind
2, becomes 3 unless the saver's slot has it again). Nothing controls them in a network match: no slot has their
index, so no command reaches them, and the mod activates the AI only offline [known for the mod; that the save's
AI records of these players are inactive is [inferred]: they were humans when it was written]. Their settlement
keeps running by itself (production, transport, soldiers defend) and they still count for the victory conditions.

**Making it the same on every game.** The mapping is in the LOAD command, as the player index of each of the six
slots (`"<crc>|<table>"`, one character per slot, `0`..`7` or `-` for a slot without an index). The command is a
lockstep command, so every game executes it at the same place in the event stream (`AdvanceNetTick` →
`ExecuteEventPackage` → `HandleEvent`) [known] S 00411990, S 00410530. Each game writes the table into its slots
there, with `PlayerInfo::SetPlayerIndex` (the setter of the game's own slot changes) [known] S 00414e20, and stops
ticking. Why this order holds:

- *Not at the next frame.* The rest of the same tick package is still executed after the LOAD command. A command
  in it is mapped through the slots; with the table written at the command, every game maps it the same way. What
  it does to the old world is replaced by the load in any case.
- *Not on the host only, not by each game for itself.* The host computes from its own file, slots and names; the
  others take the result. No game computes anything from data another game might hold differently.
- *Commands sent before the load, executed after it* carry the sender's slot, not a player index, so they act on
  the sender's new player, on every game alike [inferred]. They name objects of the old world by id (point 6 of
  "Risks and open questions").
- *The local player.* `fix_players` runs in the load that follows and takes `GetLocalPlayerIndex`, which reads
  the slot written a frame earlier; the HUD's local player is the kind-2 player it makes.
- *The host's session data.* The host sends its whole `EventGameInformation` to everyone on session changes
  (`BroadcastGameInfo`; in a running match after a player left), and a receiver copies it over its own, slots'
  indices included (`AssignGameData`, events 0x30003, 0x30005, 0x3000f, 0x30012) [known] S 0040e560. After its
  LOAD the host's copy has the table, so later copies agree. One sent *before* the host executed the LOAD and
  handled by a game *after* that game executed it would bring the old indices back; whether the event order
  allows that is [open]. The mod writes the table again right after any of those four events was handled (its
  listener runs after `HandleEvent`, before the next tick) and logs when that changed a slot.
- *A resync* sends the host's present indices, the same table format. It therefore changes nothing when the games
  agree, and makes them agree again if a game's slots differed.

Not changed by the load: a slot's team, tribe and colour bytes. They are the pre-game room's, the players' are the
save's. Only allied chat reads them in a running match (`ArePlayersAllied`), so after a load allied chat goes by
the room's teams [known] S 00413780; it also needs both player indices below 6. A player who rejoins
(`AssignSlotToJoiningUser` sets a slot's index) is not considered [open].

**Versions.** The mod's event ids are the format's version: format 2 uses `0x20f11`..`0x20f15`, format 1
(`0x20f01`..`0x20f05`, LOAD without the table) is not spoken. Every player normally runs the host's copy
(assetshare). If not, a game of the other format does not know the offer's id and never answers "have": the host's
load times out (`TransferTimeoutSeconds`), is cancelled, and nobody loads; a format-2 game that sees a format-1 id
tells its player once.

### Loading a network save offline

The offline load menu lists every `*.aav` in the save folder [known] S 0060da50, and nothing in the load path
checks for a network game [known] S 005d9fd0, S 005dfef0 (`MapInfo+0x1f0` is 1 in every save). `StartPendingMap`
gives the file's kind-2 player the human slot, kind-1 players AI slots and **every other player, kind 3 included, a
closed slot**; the players themselves are loaded from the file with their kinds. A kind-3 player has no controller
offline [inferred]. The game can hand a player to the AI in a running world: `NAI::System::ActivatePlayer` (the Lua
function `ai_enable`) [known] S 00581c40. The mod, with `FormerHumans = ai`, turns kind 3 into kind 1 in the
`MapInfo` that `StartPendingMap` reads (AI slots) and, after the load, in the player table, and activates the AI
with the player's start position (a network match does not shuffle start positions [known] S 004562d0, S 005abb60)
and `AiLevel`. With `FormerHumans = idle` the players stay without a controller. The local player is the one who
saved; a save received from the host makes its receiver play the host's player offline. A network save loaded
offline with `FormerHumans = ai`: the other player's seat is an AI player [live 2026-10-12].

`AiLevel` (1 to 3, default 2; any other value counts as 2) is the last argument of `ActivatePlayer`, which
`NAI::Player::Activate` uses as the id of the AI property record (`PropertiesDb::GetAiProperty`) [known]
S 00581c40, S 00582870. A new game passes 1, 2 or 3 for the setup's AI difficulty 0, 1 or 2 (`MapInfo +0xc8`)
[known] S 005abb60; that 1 is the weakest is [inferred] from that order. The mod does not write `MapInfo +0xc8`.
Whether the three levels play differently was not looked at in the live test [open].

## Resynchronising after a desync

**Detection** [known] S 00411990, S 00784080: at every net tick each game sends `EventUserChecksum` (`0x30009`,
`SendEventUserChecksum`) with the CRC of `nGame::System::ComputeChecksum` (that the event carries this CRC is
[inferred]: `SendEventUserChecksum` S 004089c0 was not read): random generator, player table (without kinds and names),
village, settlers, transport, military, navy, street net, AI and logic ids, serialised into an `NCore::CRCStream`.
`ChecksumLog::VerifyLatest` compares the players' values; the result is the manager's in-sync flag. On the change
to "not in sync" the game shows `!DESYNC DETECTED`, logs the report and writes a dump (`NComm_WriteDesyncDump`,
whose only caller this is); five ticks after the start without sync it shows `!NO SYNC START` and dumps as well; on
the change back, `!RESYNC DETECTED`. **Nothing else happens: the match runs on, out of sync.**

**Resync** (mod, `AutoResync`): the dump call marks the desync; at the next frame the host saves
(`GameFile_Save(0x6e, "mpsave_resync")`) and runs the synchronised load on that file. Nothing has to be paused: the
games keep running, out of sync, until the load command, and the load replaces all of it; the match goes back to
the host's state at the save, by the time the transfer took. At most one resync per minute.

**What could make it diverge again at once:** state the checksum covers but the save restores differently (none
found: every checksummed system is saved [known]); state outside the save that the simulation reads (caches
rebuilt by `PostLoad`) [open]; and the cause of the first desync, if it is a difference in data or code between
the players rather than in state. The map script's Lua state and the HUD are new after the load, as after the
game's own load [known] S 007834e0, S 00784d40.

## Proposed mod design

`mods/mpsave/mpsave.cpp`, a server mod. One operation, `sync_load(name)`, serves the load menu and the resync.

| Who | What | Game functions |
|---|---|---|
| All | Save and Load stay in the menu and open the panel: the three `IsRole0` calls answer true. | `patch_calls` in `nMenu::Game::LoadFromXml`, `OnMenuComboSelected` |
| All | Save: the game's own, on the player who saves. | `GameFile_Save` (not changed) |
| Host | Load: `StartPendingMap` in a network match starts `sync_load` instead of the offline start: refuse a save of another map, assign the players (refuse if someone has none), offer (name, size, CRC), pieces, wait for every "have", assign again, queue LOAD (CRC and slot table). | hook `nMenu::System::StartPendingMap`; `GameFile_LoadMapInfo`, `EventGameInformation::GetMapGuid`, `NetGUID::ToUUID`, `NCore::UUID::Equals`, `PlayerInfo::GetPlayerName`, `EventText::ctor`, `BroadcastEvent`, `QueueGameCommand` |
| Joiner | Offer: own file with that CRC, or collect the pieces, check, write (never over a file of its own), answer "have". Load from the menu: refused with a message. | `events::on_net_event`, `MapPath::CtorWithFileName` |
| All | The mod's events count only as an `EventText` from the host ("have": on the host, from a connected human's slot), by the sender the event names; anything else is ignored, with one log line per sender. | `PlayerInfo::IsHost`, `PlayerInfo::GetPlayerId`, `NComm_Manager::IsHost` |
| All | LOAD (same net tick): write the slot table into the session's slots (`PlayerInfo::SetPlayerIndex`), stop ticking; at the next frame (`events::on_frame`, before the game's own frame) check the file's CRC again, then the game's load without its session part: `DeactivateAllScreens`, `nGame::System::Shutdown` if still running, `GameLoadDescriptor::SetMapName`, `ActivateGameScreen`; kinds after PostLoad; tick on. The mod log has a line before the leave, one before the enter and one after the load. A game that cannot load stays stopped and tells its player to leave. | hook `NComm_Manager_CanAdvanceTick`, `GameFile_LoadLogic`, `GameFile_FinishLoad`; hooks that do nothing during the load: `NComm_Manager::Shutdown`, `BeginGameStarting`, `SendGameLoadedEvent` |
| All, offline | Absent humans become AI players of level `AiLevel`. | hook `GameFile_LoadMapInfo`; `NAI::System::ActivatePlayer` |
| Host | Desync → save → `sync_load` with the slots' present indices. | hook `NComm_WriteDesyncDump` |
| All | The host's session data arrives after a load: the last table is written again. | `events::on_net_event` |

**Lobby server.** Nothing is needed for a load inside a running match: the referee sees one match (`RegisterGame`
→ `FinishGame`, `lobby/sadk_lobby/referee.py`). A match continued in a *new* session is a new GameID to the
referee, so rewards and wagers would be paid for the continuation as for a fresh match; if that matters, the host
bridge could report "continues GameID x" and the referee could carry the registration over. Proposed only.

**Needs mapping first** (the mod uses the accessor or cast named; none of these blocks it). The types the mod
used through casts before (the text and vftable of `EventText`, `GetLocalNetId`, the `std::string *` arguments, the
`MapInfo` player kinds and names, `NLogic::System.playerTable`, `nMenu::Game.gameSetupInfo`,
`GameLoadDescriptor::SetMapName`, the manager's state values) are mapped and the casts are gone. What is left:

| Address | Now | Proposed | Evidence |
|---|---|---|---|
| `NComm::EventText` vftable 007d43a8 | the struct `EventText_vftable` exists, the address has no typed label, so the headers have no constant for it; the mod reads it from a constructed event | label `NComm::EventText::vftable` with the struct as its type | S 00409ea0, S 00420340 |
| `EventText_scalar_deleting_dtor_fn` (and the map's other function types of this form, e.g. `Player_ScalarDtor_fn`) | `void *(__thiscall)(byte flags)`: no `this` parameter, so a call through the typed slot would pass `flags` in ECX; the mod calls the slot's function by its own declaration, `NComm_StringEvent_ScalarDeletingDtor` S 00420b30 | `this` as the first parameter of the function types (or the generator adds it) | slot 0 of 007d43a8 |
| `NComm_Manager::QueueGameCommand(NComm_Event *)`; `NComm_Event`, `NComm::EventBase`, `NComm::EventText` | three flat structs with the same 16-byte header and no relation; the mod casts `EventText *` to `NComm_Event *` to queue and `EventBase *` to `EventText *` to read (after the vftable test) | one base type for the header, `EventText` with it as first member, `QueueGameCommand(EventBase *)` | S 00408b10, S 00409ea0 |
| S 00529520 `GameDesc_GetField_1d4(void *)` → `void *` | generic; the mod casts the result to `NCore::UUID *` | `NCore::UUID *NLogic::MapInfo::GetMapUuid(MapInfo *)` | S 005ab3d0 (`UUID::Equals` on the result), S 00454ad0 |
| `NLogic::MapInfo +0x1d4`, `+0x24` | gaps | `NCore::UUID mapUuid`; `std::string mapName` | `Load` S 0052bd40, `Store` S 00529db0, `SetMapName` S 005299c0 |
| S 005299c0 `NLogic::MapInfo::SetMapName(void *)`, S 0040fd80 `NComm_Manager::BroadcastEvent(void *)`, S 00413c20 `GetMapGuid(void *)`, S 004163e0 `NetGUID::ToUUID(void *)` | `void *` parameters | `std::string *`; `EventBase *`; `NetGUID *`; `NCore::UUID *` | their bodies |
| S 004083d0 `NComm_Manager_IsRole0(void *)`, S 00408430 `NComm_Manager_GetState(void *)`, S 00408330 `NComm_Manager_FindLocalPlayerSlot`, S 004088b0 `NComm_Manager_CanAdvanceTick` | free functions | members of `NComm_Manager` (as `IsHost` and `GetLocalNetId` are now) | `this` = the manager at every call |
| `NComm_Manager +0x4d` | unnamed | "stop after package" [TODO] | S 00411990, S 004088b0 |

Found on the way, not used by the mod:

| Address | Now | Proposed | Evidence |
|---|---|---|---|
| S 006b70c0 `FUN_006b70c0` | unnamed | `S2CG::CTerrainCellMgr::RemoveObject(void *object, uint *hexPos)` | vftable 007fad9c slot 1, next to `AddObject` (slot 0) |
| S 0067efe0 `SceneCb_ReinitTerrainGrid` | free function, no parameters | `S2CG::Scene::OnMapInitialized(int width, int height)`, `this` = the scene's `NMap` receiver face | only reference 007f8f10; called by `NotifyMapInitialized` S 00677db0 [inferred] |
| S 00688d20 `FUN_00688d20` | unnamed, `void *` | `S2CG::CMapRenderer::ReinitForMap(CMapRenderer *)` | resets water, `mapInitialised`, `localPlayer`, then `InitForMap` |
| S 00689e00 `Forward_Field20_Rebuild` | generic | `S2CG::CLandscape::RebuildCells(CLandscape *)` | `cellMgr`: `DestroyCells`, `CreateTerrainCells` |
| S 006b6de0 `FUN_006b6de0` | unnamed, `void *` | `S2CG::CTerrainCellMgr::SetActive(char)` | caller `CMapRenderer::SetActive` |
| `InstanceMeshRenderer::instanceListener` | `void *` | `S2CG::CTerrainCellMgr *` (or its interface) [inferred] | slots 0 and 1 called with (instance, position), S 006b90a0, S 006b94c0 |

## Risks and open questions

Shown by the live test of 2026-10-12 (two players): Save and Load are in the menu of a network match and saving
writes a file [live]; the host's offer went out (mod log: `sending "MPSaveTest-Start" to the other players
(487 KB)`) [live]; a network save loads offline with the former human's seat as an AI player [live]. The host's
log has no line after "sending" (none is written between that and "loaded"), so the test does not show whether the
joiner's "have" arrived and the load command ran; the crash in the loaders two seconds later says the load was
executed on the host [inferred].

What the next live test (two players, then a desync provoked on purpose) has to show, in this order:

1. Saving: the match stays in sync afterwards (`GameFile_Save` sets only `MapInfo+0x1f0`; that serialising changes
   no simulation state is [inferred]).
2. The mod's events arrive: the mod log shows "receiving" and "received the host's save" on the joiner, and the
   game's log has no "Error Executing Event". A joiner's "have" must reach the host (chat from a joiner does;
   whether the host relays unknown ids to third players does not matter).
3. The load command runs on both at the same tick: both mod logs show "leaving the game screen", "entering the
   game screen" and `loaded "<name>"`, in that order, and no crash. A log that ends after "leaving" places a fault
   in the teardown, one that ends after "entering" in the world build.
4. The session survives the load: nobody is dropped while the worlds build (the loading panel shows on both), the
   match ticks on afterwards, chat still works, and no `!DESYNC DETECTED` follows.
5. After the load each player controls their own player (HUD, minimap, fog of war), and the other player is a
   human's player, not an AI.
6. Commands issued before the load and executed after it refer to objects of the old world; the handlers look
   objects up by id [inferred], so they should miss, identically on every player [open].
7. A second load in the same match, and a load of a save from an earlier match on the same map with the same
   players.
7a. Assignment by name: with swapped seats each player gets their own settlement back (HUD, fog of war), a
   command of each acts on their own player on both games (no `!DESYNC DETECTED` after building something), both
   mod logs show the same `load command: players of the slots ...` line, and a resync afterwards changes nobody.
   The winner reported to the referee after such a load (`FinishGame`) is the right avatar.
7b. The sender check: a normal load still works (the joiner's mod log has no `ignoring mpsave events` line, the
   host's none for the joiner's "have"), on the host and on a joiner. That is the test of "the host's slot has the
   host's net id on every game" and of "a joiner's event carries its slot's net id".
7c. The map check: a save of another map is refused on the host with the message naming the session's map and
   nothing is sent; a save of the same map loads; the log has no `map check skipped` line on a current map.
8. Offline load of a network save with `AiLevel` 1 and 3: the mod log names the level ("now an AI player (level
   n)"), and the players build and fight.
9. Resync (`AutoResync = true`): after a provoked desync the host's save is loaded and `!RESYNC DETECTED` appears.

Not determinable from the binary alone: the size of a save late in a match (transfer time: 2 × 2100 bytes per
frame by default), the largest event the bridge passes, and whether a save taken while a cutscene, a pause or a
sacrifice animation runs loads cleanly.

Not done: saves are not offered in the pre-game room (a match cannot *start* from a save; it is loaded after the
start), autosave stays off in network matches, and a player who rejoins (`UserReJoinGame`) is not considered.

## Functions and addresses

| Address | Name | Role |
|---|---|---|
| 005aa260 | `GameFile_Save` | writes map and logic part to `<name>.aav` |
| 005a9fa0 / 005a9ec0 | `GameFile_SaveMap` / `GameFile_SaveLogic` | the two parts |
| 005275c0 / 00527d60 | `NLogic::System::Save` / `Load` | MapInfo, logic ids, tick timing, tick counter |
| 005389c0 | `LogicRandom_Save` | the logic random generator |
| 005bde00, 005be3c0, 005be6e0 | `PlayerTable::Store`, `Player::Store`, `Player::StoreChecksum` | players; kind saved, not checksummed |
| 005ab180 / 005aaed0 | `nGame_File_load` / `GameFile_LoadImpl` | load by type and name; in place |
| 005a9db0 / 005aa1b0 | `GameFile_LoadLogic` / `GameFile_FinishLoad` | logic part / PostLoad |
| 005aaa30 | `GameFile_LoadMapInfo` | a file's MapInfo only |
| 0052c880, 0052c320, 0052c1b0 | `MapPath::CtorWithFileName`, `MapPath_BuildDirectory`, `MapPath_GetFileExtension` | type → folder, extension |
| 005ecaf0 | `nMenu::Game::LoadFromXml` | removes Save/Load in a network match |
| 005eb310 | `nMenu::Game::OnMenuComboSelected` | menu actions; Save/Load offline only |
| 0060ce40, 0060d000, 0060dd30, 0060da50 | `nMenu::LoadSavePanel` ctor, `Confirm`, `Update`, `RefreshFileList` | the save/load panel |
| 005da500 / 005d9fd0 | `nMenu::System::Update` / `StartPendingMap` | offline start from a save |
| 005d9e70 / 005d9f10 | `nMenu::System::DeactivateAllScreens` / `ActivateGameScreen` | close every screen / enter the game screen |
| 005eb030 / 005ea650 | `nMenu::Game::OnLeave` / `DestroyHudWidgets` | leaving the game screen: session, HUD, world, scene |
| 007834e0 / 00781cb0 | `nGame::System::Shutdown` / `ShutdownAndDestroyGameSystem` | the running game's teardown |
| 00527c40 / 00526f80 | `NLogic::System::Shutdown` / `Reset` | callbacks off, every system emptied |
| 007842e0 / 00528910 | `nGame::System::BuildScene` / `GameSystem_Construct` | a new `g_pGameSystem` and scene |
| 005a9c10 | `GameLoadDescriptor::SetMapName` | descriptor = (type `0x6e`, name) |
| 0040b410, 0040b170, 00408e50 | `NComm_Manager::Shutdown`, `BeginGameStarting`, `SendGameLoadedEvent` | the session calls of the screen's leave and enter |
| 00672030 / 00677db0 | `NMap::System::Load` / `NMap::CallbackManager::NotifyMapInitialized` | the map loader; "a map of this size exists now" |
| 0067efe0, 00688d20, 006883e0, 00689e00 | `SceneCb_ReinitTerrainGrid`, `FUN_00688d20`, `CMapRenderer::InitForMap`, `Forward_Field20_Rebuild` | the scene rebuilds its terrain cells |
| 006b7170 / 006b73b0 | `CTerrainCellMgr::DestroyCells` / `CreateTerrainCells` | the cells and their object lists |
| 00540fd0, 0053f0b0, 005430a0 | `NResources::System::Load`, `Reset`, `Deposit::dtor` | old deposits deleted, each notifying the scene |
| 00681650, 0068e330, 006b94c0 | `Scene::OnDepositRemoved`, `MapObjLayer::RemoveInstance`, `InstanceMeshRenderer::RemoveInstance` | the render object's removal |
| 006b70c0 / 006b5840 | `FUN_006b70c0` (cell manager slot 1) / `TerrainCell::RemoveObject` | removal from a cell; faults on an empty list |
| 0067eed0 / 00688cd0 | `Scene::OnWorldLoadStateChanged` / `CMapRenderer::SetActive` | the scene's part of `Notify_Slot00` |
| 005dfef0 | `nMenu::Main::ContinueLastSavegame` | "Continue" |
| 0078b040 / 0078af30 | `nGame::Autosave::Update` / `nGame_Autosave_WriteSave` | autosave, offline only |
| 005eed00, 00784d40, 005ac770 | `nMenu::Game::OnEnter`, `nGame::System::BuildWorld`, `Game_LoadWorldFromDescriptor` | entering a match |
| 00673000 / 00675790 | `MapModifier_InitAfterMapLoad` / `ConstructionMap_RecomputeAll` | after a load: construction maps, territory, the local player's map |
| 005b2180 | `GameScript_CallOnLoaded` | the map script's `onLoaded` after a save is loaded |
| 005abb60 | `Game_CreatePlayersFromDescriptor` | players of a new game; AI activation |
| 00581c40 | `NAI::System::ActivatePlayer` | hands a player to the AI |
| 004562d0 | `LobbyMenu::SetupGameDialog::SetupSession` | network match → load descriptor (type 0); slots → `MapInfo` kinds and names |
| 00412490 / 00413290 | `NComm_Event_GetSenderPlayerIndex` / `EventGameInformation::GetSlotPlayerIndex` | a command's sender slot → player index |
| 00408300 / 00413200 | `NComm_Manager::GetLocalPlayerIndex` / `EventGameInformation::GetPlayerIndexByGuid` | the local player's index, from the slot with the local GUID |
| 00413380 / 00413780 | `EventGameInformation::FindSlotByPlayerIndex` / `ArePlayersAllied` | player index → first slot with it / slots' teams |
| 00414d60 / 00414e20 | `NComm::PlayerInfo::GetPlayerIndex` / `SetPlayerIndex` | a slot's player index |
| 00415430 | `NComm::PlayerInfo::GetPlayerName` | a slot's name |
| 005294a0 / 00529db0 | `NLogic::MapInfo::GetPlayerNamePtr` / `Store` | a save's player names |
| 005aa030 | `GameFile_LoadMapInfoCached` | a file's `MapInfo` through its cache file (by write time) |
| 00535990 | `ai::game::VictoryConditions::DeclareWinner` | winner → slot by player index → referee |
| 004083d0 / 00408410 | `NComm_Manager_IsRole0` / `NComm_Manager::IsHost` | offline? / host? |
| 00408b10 | `NComm_Manager::QueueGameCommand` | lockstep command |
| 0040fd80 / 00408b60 | `NComm_Manager::BroadcastEvent` / `SendEvent` | immediate event |
| 00411990 | `NComm_Manager::AdvanceNetTick` | net tick, checksums, desync detection |
| 004088b0 | `NComm_Manager_CanAdvanceTick` | lockstep gate |
| 00410530 / 0040e560 | `NComm_Manager::ExecuteEventPackage` / `HandleEvent` | event execution / router |
| 00527070 | `NLogic::System::Update` | logic ticks |
| 00784080 / 007845a0 | `nGame::System::ComputeChecksum` / `HandleGameCommand` | desync CRC / game commands |
| 0041f5e0 | `NComm_WriteDesyncDump` | called on a detected desync |
| 00409ea0 / 00420340 | `NComm::EventText::ctor` / `ctor_Deserialize` | the event the mod sends |
| 00420b30 | `NComm_StringEvent_ScalarDeletingDtor` | slot 0 of the `EventText` vftable 007d43a8: frees the text |
| 004089a0 | `NComm_Manager::GetLocalNetId` | this game's net id (the sender id it writes into its events) |
| 0041d720 / 004082c0 | `NComm::TinCatNetwork::cb_Received_Data` / `NComm_Manager::AppendReceivedImmediateEvents` | received immediate events: bytes only, no sender id |
| 0040e0d0, 00412ae0, 00412e80 | `NComm_Manager::AddClientGameEventsToServerGameEvents`, `TickPackageList::AddReceived`, `TickPackage::AppendEvents` | the host merges a joiner's lockstep events byte for byte |
| 0041dbb0 / 0041db50 | `NComm::TinCatNetwork::SendToAll` / `SendToHost` | to every user (`0xEFFFFFDD`) / to the host (`0xEFFFFFCC`) |
| 0041e610 | `NComm::TinCatNetwork::StartUp` | a host's own net id is `0xEFFFFFCC` |
| 00414eb0 / 00414d40 | `NComm::PlayerInfo::IsHost` / `GetPlayerId` | a slot's net id is the host's / a slot's net id |
| 00413c20 / 004163e0 | `NComm::EventGameInformation::GetMapGuid` / `NComm::NetGUID::ToUUID` | the session's map GUID, as an `NCore::UUID` |
| 00529520 / 005a9d00 | `GameDesc_GetField_1d4` / `NCore::UUID::Equals` | a `MapInfo`'s map UUID / 16-byte comparison |
| 005ab3d0 / 00454ad0 | `GameFile_FindMapNameByGuid` / `SetupGameDialog::OnMapSelected` | the game's own map check by GUID / where the session's GUID comes from |
| 00420440 | `NComm::EventSaveGame::ctor_Deserialize` | unused leftover |
