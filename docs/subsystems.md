# Client subsystems map

A map of the subsystems inside the SAdK client: what each one does, its main classes, entry points, how it
talks to the others, and how much of it is mapped. It covers `sadk_noav.exe` (the game, image base `0x00400000`)
and `tincat3.dll` (the network middleware, image base `0x10000000`).

- Addresses: **S `00xxxxxx`** = `sadk_noav.exe`, **T `10xxxxxx`** = `tincat3.dll`. They are Ghidra static
  addresses and match runtime (no rebase).
- Tags: **[known]** = read directly from the binary (decompile, disassembly, strings, imports).
  **[inferred]** = follows from known facts through one reasoning step. **[guess]** = plausible, not
  checked. **[PROVEN]** = the working stub (`sadk_lobby/`) shows it live (binary address plus live evidence).
- Wire layouts are not repeated here. See [message-catalog.md](message-catalog.md) for per-message fields
  and [LOBBY_PROTOCOL.md](LOBBY_PROTOCOL.md) for the NETMSG reference.
- Mapping numbers come from a `mapping/state.db` snapshot taken on 2026-10-07 at the end of Phase 6.

Related documents: [NCOMM_LAYER.md](NCOMM_LAYER.md), [NCOMM_GAME_PROTOCOL.md](NCOMM_GAME_PROTOCOL.md),
[MATCH_START.md](MATCH_START.md), [MP_P2P_TRANSITION.md](MP_P2P_TRANSITION.md),
[IN_WORLD_PRESENCE.md](IN_WORLD_PRESENCE.md), [SOURCEMAP.md](SOURCEMAP.md), [UI_FINDINGS.md](UI_FINDINGS.md),
[REVERSE_ENGINEERING_GUIDE.md](REVERSE_ENGINEERING_GUIDE.md).

---

## 1. Overview

| # | Subsystem | One line | Main code |
|---|---|---|---|
| 2.1 | App shell and main loop | Window, start-up, one-thread frame loop | `CApplicationEx` |
| 2.2 | tincat3 middleware | TCP framing, threads, property sets, CommLayer managers | T `PROGFLOW_NET`, `NETDRV_*`, `KRNL_*`, `CommLayer::*`, `TinCatProperties::*` |
| 2.3 | Lobby protocol | Lobby, UC/chat, village and referee connections on top of CommLayer | `LobbyComm::*`, `LobbyManager` |
| 2.4 | Lobby UI and state machine | Login dialogs, screens, server browser, hosting dialog, mini-games | `LobbyMenu::*`, `LobbyManager` FSM |
| 2.5 | Village / character | 3D lobby world, avatars, NPCs, shop, world connection | `Lobby::CLobby`, `LobbyComm::VillageServerConnection`, `CharacterManager` |
| 2.6 | In-match network (NComm) | Pre-game room and lockstep peer-to-peer match transport | `NComm_Manager`, `NComm::TinCatNetwork` |
| 2.7 | Game simulation | The RTS: settlers, economy, military, navy, AI | `NLogic`, `NSettlers`, `NVillage`, `NMilitary`, `NNavy`, `NAI`, `nGame::System` |
| 2.8 | Rendering | Direct3D 9 device, shaders, terrain/water/buildings | `S2CE::*`, `S2CG::*`, `ai::render*` |
| 2.9 | UI | XML-driven widget toolkit and in-game menus | `nUi::*`, `nMenu::*` |
| 2.10 | Physics | PhysX 2.x, used by the 3D lobby | `LobbyPhysics_*`, `NXU::*`, `ai::physics::*` |
| 2.11 | Lua | Lua 5.0.2 VM, script host, game bindings | `lua_*`, `ai::script::LuaScriptHost`, `LuaProps_*` |
| 2.12 | IO / data | Bit streams, files, encrypted containers, XML, maps and saves | `NCore::*`, `NBase::gDecryptData`, `GameFile_*` |
| 2.13 | Crypto and libraries | LibTomCrypt/LibTomMath in tincat3, MD5, MSVC runtime, imported DLLs | see §4 |

### 1.1 Session flow across subsystems

The diagram follows one client from start-up to a running match. The tag at the end of each stage is the
strongest evidence for the whole stage.

```
 [App shell]  WinMain S 00407cf0
   │  CApplicationEx::Initialize S 004075d0
   │    ├─ engine layer (D3D9 device, UI, sound)      S 00405590
   │    ├─ LobbyManager + LobbyComm + CLobby (3D)      (skipped with -nolobby)
   │    └─ NComm manager created (idle, state 0)
   ▼
 Frame loop: CApplicationEx::FrameTick S 00401bd0  ── one thread, every frame:
   │    FrameTick_Menu S 00401780 / FrameTick_InGame S 004018e0
   │    → LuaScriptHost::UpdateThreads, NComm_Manager::Process_MainLoop,
   │      CLobby::Update, LobbyManager::StatePump_Tick S 00464ee0, sound, present
   ▼
 ┌─ [Lobby protocol / tincat3] ── lobby connection (:7070) ─────────────────────── [PROVEN]
 │  188 CheckVersion → 201/202 ECDH P-521 → 204 AuthenticateUser (Twofish-CTR)
 │  → 207 SessionKey (HandlerLobby T 10023cc0)          LobbyManager state 1→3
 │  StatePump: 3→4 version check → 5 → 6 load global data (MotD, character,
 │  buddy and ignore lists; opens UC/chat :7071 with token 211/212/213 → 153) → 7
 └────────────────────────────────────────────────────────────────────────────────
   ▼
 ┌─ [Lobby UI] avatar select → AvatarScreen::OnStartGameClicked_EnterVillage S 0043abc0
 │  → CLobby::RequestEnterVillage S 004f5070 → CLobbyClient::EnterVillage S 00503f50
 │  → LobbyManager::CreateVillageServerConnection S 00463850          state 8
 └────────────────────────────────────────────────────────────────────────────────
   ▼
 ┌─ [Village] world connection (:5479, HandlerGS T 10023460) ───────────────────── [PROVEN]
 │  base login (188 → 211/212/213 → 153) → LobbyMessages in SendGameData(74)
 │  1000 EnterWorld → HandleEnterWorld S 0046f670 → state 9, 3D world renders
 └────────────────────────────────────────────────────────────────────────────────
   ▼
 ┌─ [Hosting] SetupGameDialog / BrowseGameDialog ───────────────────────────────── [PROVEN]
 │  host: 168 AddGameServer → 153; joiner: server list (171/170) → join
 │  NComm StartUpNetwork S 0040a9a0 (mode 4 host / 3 join) → ConnectAndJoin S 0040ad60
 │  pre-game room = NComm events (UserInformation, PlayerInformation, PlayerReady)
 │  referee: 189 AssignServer type 4 → 170 descriptor → SetRefereeServerAddress S 004625d0
 │           → referee connection base login → server pushes LoginSuccess 0xDCA
 └────────────────────────────────────────────────────────────────────────────────
   ▼
 ┌─ [Match start] ──────────────────────────────────────────────────────────────── [PROVEN]
 │  0xDCA → WorldScreen::OnRefereeLoginSuccess_RegisterGame S 00432240
 │  → RegisterGame 0xDB6 → 0xDB7 Ack + 0xDB8 Result{GameSeed} (S 0047a580)
 │  → NE_StartLoading 0x30012 (BroadcastStartLoading S 0040fe50)
 │  → NE_GameInformation 0x30003 load gate → GameFile_LoadMap S 005aa7b0
 │  → host broadcasts StartGame when all slots loaded (nGame::System::Update S 00780d20)
 └────────────────────────────────────────────────────────────────────────────────
   ▼
 [Game simulation] NLogic::System::Update S 00527070: fixed lockstep ticks
   ↔ NComm_Manager::AdvanceNetTick S 00411990 (1001 client→host, 1002 host→clients)
```

The full referee chain and its failure modes are in `sadk_lobby/referee.py`, `sadk_lobby/dispatch.py` and
`engagement_records/2026-07-27_referee-*.md`. Every failure in that chain is silent: the frame is accepted, the
socket stays open, and nothing is logged.

---

## 2. Subsystems

### 2.1 App shell and main loop

| Item | Address | Notes |
|---|---|---|
| `WinMain` | S 00407cf0 | Switches to the parent of the exe directory, pins the process to one CPU, enforces a single instance with a named mutex, creates window class `S2Class`, then runs the `PeekMessage` / `FrameTick` loop [known] |
| `CApplicationEx::Initialize` | S 004075d0 | Parses the command line (S 00403ac0), loads engine data, creates the lobby stack unless `-nolobby`, initialises the engine layer, creates the NComm manager, runs `-start`/`-map` [inferred] |
| `CApplicationEx::InitEngineLayer` | S 00405590 | Display modes, `url2tex`, graphics device init S 004da2a0, UI cursor [inferred] |
| `CApplicationEx::FrameTick` | S 00401bd0 | Calls `FrameTick_InGame` when the lobby mode is 0/1 or there is no lobby, otherwise `FrameTick_Menu`. Then runs `CLobby::ProcessModeTransition`. Returning false ends the loop [inferred] |
| `FrameTick_Menu` | S 00401780 | Timer, UI XML hot reload, Lua threads, NComm pump, `CLobby::Update`, sound, device-lost check, cursor clip [known from decompile] |
| `FrameTick_InGame` | S 004018e0 | Input, `nMenu::System` update, NComm pump, Lua threads, `NLogic::System::Update`, the `LobbyManager::StatePump_Tick` pump while the world is not active, `App_RenderWorldFrame` S 00401260 [inferred] |
| `CApplicationEx::Shutdown` | S 00401cb0 | [inferred] |

**Threads.** All game logic, UI, rendering, lobby and NComm work runs on the main thread inside `FrameTick`
[inferred]. The other threads found are the tincat3 socket threads (§2.2), `DirectoryWatcher::ThreadProc`
S 00581200 (file-change watcher), `CVarServer_ThreadMain` S 0067df40 (debug console server, normally off), and
the `DebugToggleWindow` thread [inferred]. Lua "threads" are coroutines on the main thread
(`LuaScriptHost::UpdateThreads` S 005c9a10) [known].

### 2.2 Network: tincat3 middleware

`tincat3.dll` (Funatics' "TinCat" library) carries every TCP connection the client makes: lobby, UC/chat,
village/world, referee, and the in-match peer-to-peer transport. It still has its C++ symbols, so its
names are much more reliable than the exe's [known].

| Layer | Main code | Role |
|---|---|---|
| Driver (`NETDRV_*`) | `NETDRV_Init` T 100029d0, `NETDRV_ReaderThreadProc` T 10001fc0, `NETDRV_WriterThreadProc` T 10002390, `NETDRV_ServerThreadProc` T 100026c0 | One reader thread and one writer thread per connection, plus a master thread (which listens when in server mode). The reader checks the 28-byte header, magic `0xDABAFBEF` and the CRC32 of the payload, then queues the envelope [known] |
| Kernel (`KRNL_*`, `PROGFLOW_NET`) | `PROGFLOW_NET::Process` T 10001800, `ProcessMessages` T 100012f0, `KRNL_SendLogonRequest` T 10004660, `KRNL_OnLogonAccepted` T 10004d90 | Main-thread pump. Pops up to N envelopes and dispatches on the frame `Type` (1..0xE: timesync, logon, alive, custom data, file...) [known] |
| API (`TinCat_CTRL`) | `TinCat_CreateAPI` T 10007d50, `TinCat_CreateTinCatValues` T 1000bfc0 | The object the exe drives. Slot 10 = Process (T 10008420) [known] |
| Property sets (`TinCatProperties`) | `PropertySet::GetProperty` T 10013d00, `Property::SetMemBlock` T 10011500, factory T 100138f0 | The typed key/value body codec used by all lobby NETMSGs [known] |
| CommLayer | `TinCat_CreateCommLayer` T 10018c20, `CommLayerTinCat` (T 10018c70..), `ConnectionManager`, `ConnectionManagerINet`, `ConnectionReal`, `ConnectionLANLobby`, `ConnectionBC` | Logical connections per server id, login state machines, routing to the handlers below [known] |
| Message handlers | `HandlerLobby::HandleMessage` T 10023cc0, `HandlerUserComm::HandleMessage` T 10027080, `HandlerGS::HandleMessage` T 10023460 | One receive machine per connection kind: lobby, UC/chat, and per-server-id (village, referee) [known] |
| Managers | `GameServerManager` (server list, assign; `OnGameServerAssigned` T 10021520), `UserManager`, `ChatChannelManager`, `MailManager`, `GroupManager`, `GuildManager`, `RankingManager`, `BrokerManager`, `CharacterManager`, `CDKeyManager`, `MachineManager`, `PropertyManager`, `CyclicMsgManager`, `TokenValidator` | One manager per NETMSG family, each with observer callbacks into the exe [known] |
| Auth | `CommLayer::Authenticator` T 1002ac40..1002c940 | ECDH key exchange, credential/CD-key hashing, Twofish-CTR wrapping, built on LibTomCrypt (§4.1) [known] |
| Modules | `TinCatModules::CellManager`, `TinCatModules::Reconnector`, `LoadBalance` | Cell broadcast, host migration and reconnect, load balancing [inferred] |

**Loop and threads.** Socket I/O runs on the driver threads. Everything above the driver runs when the exe
calls the API's Process from its frame loop: `LobbyManager::StatePump_Tick` ticks the CommLayer
(`pCommLayer` vtbl+0x54), and `NComm::TinCatNetwork::Process` S 00419e10 ticks the match API instance
[inferred]. Handler failures are logged and never close the connection [known].

**Talks to.** It exports to the exe only through factories (`TinCat_CreateCommLayer`, `TinCat_CreateAPI`,
`TinCat_CreateTinCatValues`, `Reconnector`) and observer interfaces that the exe implements [known: the exe
imports 11 symbols from TINCAT3.DLL].

### 2.3 Lobby protocol

The client-side protocol objects that sit on top of CommLayer. The lobby, UC/chat and village connections all
use the one comm layer with payload magic `0x26B6` [PROVEN].

| Item | Address | Notes |
|---|---|---|
| `LobbyManager` (`LobbyComm::System`) ctor | S 00463fd0 | Owns the comm layer (+0x4c), server list (+0x54), UC connection (+0x3d8), referee connection (+0x490), village connection (+0x540), game-slot connection (+0x544) and state (+0x57c) [known] |
| `LobbyManager::DispatchInboundToConnection` | S 00462760 | Finds the owning connection for a connection id, wraps the data in an `NCore::BitStream` and calls `conn->vtbl[0x24]` [inferred] |
| `LobbyComm::BaseConnection` | S 0048de70.. | Shared login/logout/disconnect observers for the sub-connections [known] |
| `LobbyComm::UserCommConnection` | S 0047f160.. | Chat and whisper connection, `OnReceivedData` S 0047f6e0 [known] |
| `LobbyComm::VillageServerConnection::HandleMessage` | S 00470a90 | Switch on the 12-bit LobbyMessage id for world messages (§2.5) [known] |
| `LobbyComm::RefereeServerConnection` | `Login` S 004793f0, `OnReceive` S 0047b090, `LoginSuccessReceived` S 0047ac20, `RegisterGame` S 00479840 | Referee / match-arbiter, LobbyMessage category 3 [PROVEN] |
| `LobbyComm::LobbyMessage` | `InitFromWire` S 0048fa50, `ReadBits` S 0048f0d0, `ReadString` S 004900a0 | Bit-packed MSB-first body used by village and referee messages. The type word is `names<<15 \| category<<12 \| id`, and field scalars are big-endian [PROVEN] |
| `LobbyComm::ServerList` | `StartObservation` S 00468e80, `CreateGameServer` S 0046aaa0, `RequestRefereeServer` S 00468f60, `GameServerAssigned` S 00469ad0 | Server browser, hosting, referee assignment [known] |
| Mini-game proxies | `MiniGameProxy`, `MiniGameDiceProxy`, `MiniGamePokerProxy` | In-village dice, poker and pawn-chess tables (category 5 LobbyMessages) [inferred] |

There are two body encodings. Lobby and UC NETMSGs are TinCat property sets with little-endian fixed-width
scalars and u32-length strings. Village and referee messages are LobbyMessages inside a `SendGameData(74)` or
`SendGameDataBundle(73)` envelope, with big-endian bit-packed fields [PROVEN]. Wire details are in
[message-catalog.md](message-catalog.md).

### 2.4 Lobby UI and state machine

**State machine.** `LobbyManager+0x57c`, enum `LobbyManagerState`, set by `LobbyManager::SetState` S 00462540
(state 12 latches) and driven every frame by `LobbyManager::StatePump_Tick` S 00464ee0 [known]:

| Value | Name | Entered by |
|---|---|---|
| 0 / 1 / 2 | Init / Disconnected / Authorizing | start-up, `LobbyManager::Login` S 004630e0 |
| 3 | Authorized | `LobbyManager::OnLoggedIn` S 00463a10 |
| 4 / 5 | CheckingVersion / VersionChecked | pump sends the version PropertyGet, `OnVersionChecked_State4to5` S 00464e70 |
| 6 / 7 | LoadingGlobalData / GlobalDataLoaded | pump: server-list observation, MotD, opens UC/chat, character/buddy/ignore lists, PostOffice |
| 8 / 9 | EnteringVillage / VillageEntered | village entry; 9 is set by `HandleEnterWorld` S 0046f670 |
| 10 / 11 | LeavingVillage / VillageLeft | leave sequence |
| 12 | ConnectionLost | `OnConnectionLost` S 004647e0, terminal |

From state 6 on, the pump also requests a referee server once and retries it on a 60 s timer
[known: S 00464ee0 plate and the stub's live 60 s `189` retry cadence].

**UI.** `LobbyMenu::System` (ctor S 0042a3a0, `Update` S 0042a860, `Render` S 0042a650) owns the dialogs and
opens them through `Open*Dialog` (S 0042af70 login ... S 0042c120). The main screens are `AccountScreen`,
`AvatarScreen`, `WorldScreen` (the in-world and hosting screen; `Update` S 00435980) and `LobbyDesktop`.
Dialogs include `LoginDialog`, `CreateAccountDialog`, `SelectAvatarDialog`, `SelectVillageServerDialog`,
`SetupGameDialog`, `BrowseGameDialog`, `SelectMapDialog`, `ShopDialog`, `MailboxDialog`, `HallOfFameDialog`
and the mini-game dialogs [known by RTTI names]. Screen vtables: [LOBBY_SCREEN_VTABLES.md](LOBBY_SCREEN_VTABLES.md).

**Talks to.** The UI subscribes to the observer lists on the LobbyComm connections (for example
`WorldScreen::OnRefereeRegisterGameResult` S 00431800) and calls into `LobbyManager` and `CLobby`. It renders
through the 3D lobby's `UIRenderer` and `nUi` widgets [inferred].

### 2.5 Village / character

The 3D lobby ("village") and the player's avatar.

| Item | Address | Notes |
|---|---|---|
| `Lobby::CLobby::StartUp` | S 004f8c90 | Builds the 3D lobby: scenes, views, texture/shader/mesh managers, camera, `LobbyPhysics`, body-part databases, pets, snapshot maker, `CLobbyClient`, `LobbyMenu::System` [known] |
| `Lobby::CLobby::Update` / `Tick` / `RenderFrame` | S 004fb460 / S 004fb230 / S 004f9960 | Per-frame lobby world [inferred] |
| `Lobby::CLobbyClient::EnterVillage` | S 00503f50 | Creates the `VillageServerConnection` and opens it [inferred] |
| `VillageServerConnection` handlers | `HandleEnterWorld` S 0046f670, `HandleWorldLoginAck` S 0046ec50, `HandleNPCData` S 0046f8c0, `HandleAvatarData` S 0046e1d0, shop S 004706b0.., trade S 0046cd10, mini-game tables S 0046eb70.. | World connection inbound API [known/inferred per function; see [IN_WORLD_PRESENCE.md](IN_WORLD_PRESENCE.md)] |
| `LobbyComm::CharacterManager` | ctor S 00478f80, `CreateCharacter` S 004750f0 | Avatar list and creation through the lobby connection [inferred] |
| Avatar graphics | `Lobby::CGfxObjAvatar`, `S2CG::CCharacter`, `S2CG::CCharacterMgr`, customize mode (S 004f71d0 ..) | [inferred] |

Entering the world and receiving EnterWorld 1000 work against the stub [PROVEN]. Other players, NPCs and
populated browsers inside the world are not served yet. Note that `NVillage::System` (S 005592c0) is
the RTS settlement logic of a match, not the lobby village. It is tagged `village/character` in the database,
but it belongs to §2.7 [inferred].

### 2.6 In-match network (NComm)

The match transport is separate from the lobby protocol. Its full reference is
[NCOMM_LAYER.md](NCOMM_LAYER.md) and [NCOMM_GAME_PROTOCOL.md](NCOMM_GAME_PROTOCOL.md).

| Item | Address | Notes |
|---|---|---|
| `NComm_GetManager` | S 00408290 | Process-global `NComm_Manager` singleton [known] |
| `StartUpNetwork(mode)` | S 0040a9a0 | 0 = offline `DummyNetwork`; 3 = join Internet game, 4 = host Internet game, both `TinCatNetwork`. Modes 1/2 have no caller (§5) [inferred] |
| `ConnectAndJoin` | S 0040ad60 | Sends `NE_UserInformation 0x30001` (build version and checksum) [inferred] |
| `HandleEvent` | S 0040e560 | Inbound event router, `NE_*` 0x30001..0x30012 [inferred] |
| `Process_MainLoop` | S 00410f70 | Per-frame pump: transport, start-loading delay, reconnect FSM, net-tick length adaptation (0x3000d) [inferred] |
| `AdvanceNetTick` | S 00411990 | Lockstep: client package 1001 to the host, host tick package 1002 to everyone, checksums, `!DESYNC DETECTED` [inferred] |
| `NComm::TinCatNetwork` | `Process` S 00419e10, `cb_Received_Data` S 0041d720 | TinCat module type `0x27d9`, subtypes 1000..1003 [inferred] |
| `NComm_Event_CreateFromStream` | S 00420540 | Event factory keyed on the class wire signature [known] |

**State.** `EManagerState` (`mgr+0x1c`) defines None 0, NetworkStarted 1 and Connected 2 [known]. The game
code also tests states 3 and 4: `nGame::System::Update` broadcasts StartGame "in state 3 when all slots are
loaded", and `NLogic::System::Update` ticks only in state 4 [inferred]. The enum does not name those
values yet ([TODO]).

### 2.7 Game simulation

The Settlers RTS itself. It is the largest tagged subsystem, with about 3,200 functions tagged `game-sim` plus
RTS code tagged under other names.

| Area | Main classes | Entry points |
|---|---|---|
| Logic core | `NLogic::System`, `NLogic::CallbackManager`, `NLogic::Stock` | `Update` S 00527070 (fixed lockstep ticks, reports each tick to NComm), `Load` S 00527d60, `InitSubsystems` S 00527f70 [inferred] |
| Game system | `nGame::System` | `Update` S 00780d20. Player commands are sent and handled as pairs (`SendPlaceBuilding` S 007818b0 / `HandlePlaceBuilding` S 00781980, streets, flags, upgrades, attacks, ship routes; ids 0x2000x..0x2002x) [inferred] |
| Settlers / workers | `NSettlers::System`, `Worker`, `Soldier`, `Settler`, `NMovie::*` (scripted settler actions) | [inferred] |
| Settlement | `NVillage::System` (`Load` S 00559c80, `Update` S 0055a640), `OrderSystem`, `Construction` | [inferred] |
| Military / navy | `NMilitary::System` (S 00570260), `NMilitary::Fight`, `NNavy::System` (S 005b3d70), `ai::navy::*` | [inferred] |
| AI | `NAI::System` (`Tick` S 00581a30), `NAI::Player`, `NAI::Cell` | [inferred] |
| World | `NResources::System`, `NNet` (street network), `NTransport::System`, `NDoodads::System`, `ai::map::*` | [inferred] |
| Sound | `ai::audio::SoundManager` (`Update` S 005c68b0, FMOD) | [inferred] |

**Loop.** `FrameTick_InGame` calls `NLogic::System::Update`, which runs as many fixed ticks as
`NComm_Manager_CanAdvanceTick` allows. Each tick updates all subsystems and calls `AdvanceNetTick`. Player
input becomes command events that travel through NComm and run on every peer in the same tick [inferred]. The
`GameSeed` from the referee seeds this deterministic simulation [PROVEN: match start needs it,
`RegisterGameResultReceived` S 0047a580].

### 2.8 Rendering

| Layer | Main classes | Entry points |
|---|---|---|
| Engine (`S2CE`) | `CGraphicDevice` (ctor S 004d7080, `Init` S 004da2a0, `CreateDevice` S 004d5bf0), `CResourceMgr` (S 004dae40), `CShaderProgram`, `CTexture` | Direct3D 9 device, resources, D3DX effects with a compiled-effect cache (S 004eb8f0) [inferred] |
| Game graphics (`S2CG`) | `WorldRenderer` (ctor S 006a8ff0, water/reflection passes), `BuildingRenderer`, `CTerrainCellMgr`, `ItemMgr`, `SwarmMgr`, `Scene`, `CMapRenderer` | Map, terrain, water, buildings, units [inferred] |
| Lobby graphics (`Lobby::CGfx*`) | `CGfxShaderMgr`, `CGfxTextureMgr` (S 00504650), `CGfxObj*` | The 3D lobby's own renderer [inferred] |
| Frame | `App_RenderWorldFrame` S 00401260 | Begin rendering, `nMenu::System` render, present [inferred] |

Imports: `D3D9.DLL` and `D3DX9_38.DLL` (16 functions) [known]. Lobby billboards render web pages into textures
through an IE control (`url2tex`, §5) [inferred].

### 2.9 UI

| Layer | Main classes | Entry points |
|---|---|---|
| Widgets (`nUi`) | `Object`, `Button`, `ListBox2`, `Text`, `EditEx`, `ChatSystem`, `Cursor`, `XMLHandler` | Every widget has a `LoadFromXml`. `nUi::XMLHandler::ReloadAllIfRequested` runs each frame (layout hot reload) [inferred] |
| Menus (`nMenu`) | `System` (ctor S 005db1e0, `Update` S 005da500, `Render` S 005d9800), `Game` (`SetupHud` S 005ed700), `MiniMap`, `Messages`, `Book`, `Cinematic`, `Debug`, `NetInfo` | In-game and front-end menus. `StartPendingMap` S 005d9fd0 starts a queued map [inferred] |
| XML | `ai::xml::XmlDoc::LoadFromFile` S 006e8210 | expat (`EXPAT.DLL`, 9 imports by ordinal), files decrypted first with `gDecryptData` [known] |

Layouts live in `data/game/ui/layout/*.xml` and `data/lobby/...` (KEX-encrypted). See [UI_FINDINGS.md](UI_FINDINGS.md).
The Phase 6 sample measured a higher error rate here (6.6 %, 5 of 76) than elsewhere, so `ui` plates
need more care [known: VERIFICATION.md].

### 2.10 Physics

| Item | Address | Notes |
|---|---|---|
| `LobbyPhysics_Init` / `_Shutdown` | S 00500410 / S 005002e0 | Creates the PhysX SDK, a scene with gravity −9.8 and the NxCharacter controller manager. If PhysX is missing, it shows a message box and exits [known] |
| `Lobby::CPhysicObj::CreateTriangleMeshActor` | S 00522410 | Cooks lobby collision meshes [known: `NxGetCookingLib` import] |
| NXU (PhysX utility library) | S 00730800..0075fef0 (~480 functions) | Scene serialisation (`NXU::SchemaStream`, `NxuXmlReader`) and a COLLADA physics importer (`NXU::colladaImport` S 007578a0) [known: names, tags `LIBRARY:PhysX-NXU`] |

`NxCreatePhysicsSDK` and `NxCreateControllerManager` are called only from `LobbyPhysics_Init` [known: import
references], so PhysX appears to drive avatar movement and collision in the 3D lobby, not the RTS simulation
[inferred]. Imports: `PhysXLoader.dll` (3), `NxCharacter.dll` (2).

### 2.11 Lua

| Item | Address | Notes |
|---|---|---|
| Lua 5.0.2 VM | S 005c9c20..005d92f0 (378 functions tagged `LIBRARY:lua*`) | `lua_*`, `luaL_*`, `luaV_*`, `luaK_*`, `luaB_*` ... [known] |
| `ai::script::LuaScriptHost` | `LuaScriptHost_GetInstance` S 005c8bd0, `RunFile` S 005c9690, `UpdateThreads` S 005c9a10, `CallGlobal` S 005c9780 | Scripts run as coroutines and are resumed every frame [known] |
| Game bindings | `LuaProps_*` S 0054a4d0..00550df0 (243 functions) | The property/script API exposed to map and property scripts [inferred] |
| Map scripts | `GameScript_LoadMapScript` S 005b1fe0 | The `.lua` beside each map [inferred] |
| Debugger hook | `LuaDebugger_AddLuaState` S 005cdc90 | `LuaDebugger.dll` (delay-loaded) [inferred] |

### 2.12 IO / data

| Item | Address | Notes |
|---|---|---|
| `NCore::BitStream`, `NCore::DumpStream`, `NCore::CRCStream` | — | Serialisation primitives for saves, events and LobbyMessages [inferred] |
| `NCore::FileStream` / `NCore::FileStreamCrypt` | S 0057d140 / S 007807f0 | Plain and encrypted file streams (saves) [inferred] |
| `NBase::gDecryptData` | S 006e6660 | Decrypts a `sadk` container: FCC check, per-file key from the file name, key CRC, descramble + unpack, data CRC. A mismatch forces a crash [known] |
| `FileCrypt_DecryptAndUnpack` / `FileCrypt_PackAndEncrypt` | S 006ee9d0 / S 006ee8e0 | The unpack codec (S 007624a0) is not identified [TODO] |
| `GameFile_*` | `LoadMap` S 005aa7b0, `LoadImpl` S 005aaed0, `Save` S 005aa260, `SaveMap` S 005a9fa0, `LoadMapInfo` S 005aaa30 | Map and save files, map-info caches by GUID, desync dumps [inferred] |
| `DirectoryWatcher` | S 00581200 | Watches data directories for hot reload [inferred] |

The map file format is documented in [map-format.md](map-format.md),
checked against all 22 shipped free-game maps. Data-file decryption for modding is in
[REVERSE_ENGINEERING_GUIDE.md](REVERSE_ENGINEERING_GUIDE.md).

### 2.13 Crypto

| Where | What | Address | Use |
|---|---|---|---|
| tincat3 | LibTomCrypt + LibTomMath (§4.1) | T 10039d20..1004a0e0 | Lobby login: ECDH P-521 (`ecc_make_key` T 10039ea0, `ecc_shared_secret` T 1003ef60, `ecc_encrypt_key`/`ecc_decrypt_key`), Twofish (T 1003b550) in CTR mode (T 1003af30), SHA-384/512 (T 1003c270..), DER, `sprng` [known] |
| tincat3 | `CommLayer::Authenticator` | T 1002ac40..1002c940 | `HashPassword` T 1002bca0, `HashCDKeys` T 1002ba70 (SHA-512 of the sorted CD keys), `EncryptCredentials` T 1002b560, `DecryptSessionKey` T 1002bf40, token handling [known]. Lobby login works end to end against the stub [PROVEN] |
| exe | MD5 | `MD5Init` S 00428c40, `MD5Update` S 00428c70, `MD5Final` S 00428d40, `ai::crypto::MD5Hasher` | Password MD5 (`GetPasswordMd5` S 00413a20) and static-data checksums in NComm `UserInformation` [inferred] |
| exe | CRC32 (zlib style) | `crc32` S 007627c0, `crc32_little` S 00762520 | File and stream checksums [inferred] |
| exe | Data-file descrambling | `gDecryptData` S 006e6660 | §2.12 [known] |

---

## 3. Mapping coverage

### 3.1 Functions per subsystem and confidence

From `select prog, subsystem, conf, count(*) from functions group by 1,2,3`. "untagged" = no confidence
(mostly compiler-generated EH funclets and thunks).

**sadk_noav.exe (31,348 functions)**

| subsystem | total | known | inferred | guess | untagged | open (any reason) | open (excl. decomp-changed only) |
|---|---|---|---|---|---|---|---|
| network | 1,269 | 474 | 748 | 46 | 1 | 364 | 217 |
| lobby-protocol | 61 | 16 | 45 | 0 | 0 | 22 | 15 |
| lobby-ui/state | 1,193 | 348 | 790 | 55 | 0 | 352 | 255 |
| village/character | 3,031 | 928 | 2,035 | 65 | 3 | 852 | 612 |
| game-sim | 3,187 | 902 | 2,185 | 97 | 3 | 939 | 568 |
| rendering | 2,116 | 435 | 1,642 | 39 | 0 | 644 | 435 |
| ui | 2,487 | 700 | 1,735 | 52 | 0 | 723 | 492 |
| physics | 257 | 55 | 198 | 4 | 0 | 93 | 45 |
| lua | 260 | 191 | 61 | 8 | 0 | 32 | 20 |
| io/data | 304 | 74 | 210 | 20 | 0 | 93 | 48 |
| unknown | 3,052 | 735 | 2,255 | 60 | 2 | 670 | 442 |
| crt (MSVC CRT) | 792 | 129 | 141 | 25 | 497 | — | — |
| msvc-eh (EH funclets) | 10,574 | 367 | 377 | 108 | 9,722 | — | — |
| (none: EH funclets, thunks) | 2,765 | 0 | 1,986 | 0 | 779 | — | — |

**tincat3.dll (1,793 functions)**

| subsystem | total | known | inferred | guess | untagged | open (any reason) | open (excl. decomp-changed only) |
|---|---|---|---|---|---|---|---|
| network | 688 | 400 | 275 | 13 | 0 | 197 | 141 |
| lobby-protocol | 75 | 24 | 50 | 0 | 1 | 51 | 22 |
| village/character | 62 | 38 | 15 | 9 | 0 | 34 | 16 |
| ui | 69 | 15 | 54 | 0 | 0 | 50 | 17 |
| io/data | 55 | 15 | 39 | 1 | 0 | 25 | 18 |
| unknown | 784 | 349 | 410 | 25 | 0 | 201 | 98 |
| (none: thunks) | 60 | 0 | 0 | 0 | 60 | — | — |

Open counts come from `mapping/work/p5/reanalysis_p3.json`, the source of
[open_questions.md](../mapping/work/p5/open_questions.md): **4,784** sadk and **558** tincat3 functions have at
least one open reason. The most frequent reasons are `decomp-changed`, `class-undetermined`, `generic` and
`unnamed`. 247 sadk and 312 tincat3 network/lobby functions are still open, and 41 + 8 functions carry an
unresolved board question.

**How to read the subsystem column.** Tags were assigned per cluster (address range), so they are coarse:

- The tincat3 LibTomCrypt range is tagged `unknown`, `HandlerLobby` and `HandlerGS` are tagged `ui`, and
  CommLayer managers are spread over `unknown`, `village/character` and `ui`. For tincat3, use the
  namespaces in §2.2 rather than the tag.
- In the exe, `LuaProps_*` (243) and half of the Lua VM are tagged `unknown`, `GameFile_*` is tagged `lua`,
  `nGame::System` command handlers are tagged `io/data`/`ui`, and `NVillage::System` (RTS) is tagged
  `village/character`.
- There is no `crypto` tag. Crypto code is listed in §2.13.

### 3.2 Quality

From the Phase 6 verification ([VERIFICATION.md](../mapping/work/p6/VERIFICATION.md)) [known]:

- About **2 %** of decided claims were refuted (24 of about 1,060 claim parts). The rate is the same for
  network and other code and for the `known` and `inferred` tiers, so treat the two tiers as equally reliable
  (about 98 %). No sampled struct layout was refuted.
- About **30 %** of sampled claim parts stayed undecided. Prototypes (parameter count and order) are the
  weakest part.
- Remaining mechanical findings: 183 + 56 parameter-count/stack-cleanup mismatches, 167 + 93 placeholder types,
  1,579 + 50 vtable-owner mismatches (mostly shared ICF-folded bodies) for sadk + tincat3.
- 132 protocol messages were cross-checked against `msgdefs.ini`, the binary and the stub. 98 agree, and 22
  differ between the stub and the client; those are reported in `mapping/work/p6/protocol_*.md`.

---

## 4. Third-party libraries

| Library | Where | Evidence | Size |
|---|---|---|---|
| LibTomCrypt (ECC, Twofish, CTR, SHA-384/512, DER, sprng/rng, hash/cipher/prng registries) | tincat3, T 10039d20..~1004a0e0 | Function names (`ecc_*`, `twofish_*`, `ctr_*`, `sha512_*`, `der_*`, `ltc_*`, `register_*`, `rng_*`) [known] | ~105 |
| LibTomMath (through LTC's `ltm_desc` math descriptor) | tincat3, same range | `mp_*`, `s_mp_*`, `fast_*`, `ltm_desc_*` [known] | ~120 |
| MSVC 8 (VS2005) CRT | exe (static), tincat3 (`MSVCR80.DLL`, 74 imports) | `lib = msvc-crt` (792), tags `LIBRARY:msvcrt`, `msvc8-crt`, `msvcrt8`; `__security_check_cookie` [known] | 792 |
| MSVC C++ EH / STL | exe | `lib = msvc-eh` (13,168 incl. funclets), tags `LIBRARY:msvc-eh`, `msvc-stl`, `msvcp`; template instances named `ai::stl::MsvcTree` / `MsvcVector` [known] | 13,168 |
| Lua 5.0.2 | exe, S 005c9c20..005d92f0 | Tags `LIBRARY:lua`, `lua5.0.2` [known] | 378 |
| PhysX 2.x + NXU + NxCharacter | exe (NXU static, SDK via `PhysXLoader.dll`, `NxCharacter.dll`) | Tags `LIBRARY:PhysX-NXU`, `PhysX`; imports [known] | ~480 |
| COLLADA physics importer (part of NXU) | exe, S 0074db80..007578a0 | `NXU::Collada*`, `ai::physics::Collada*` [known] | (in NXU) |
| expat XML parser | `EXPAT.DLL` | 9 ordinal imports used by `XmlDoc::LoadFromFile` S 006e8210 [known] | — |
| FMOD | `FMOD.DLL` | 29 imports; `SoundManager::Update` calls `FSOUND_Update` [known] | — |
| Direct3D 9 / D3DX9 (v38) | `D3D9.DLL`, `D3DX9_38.DLL` | 1 + 16 imports, `ID3DXInclude_Open` S 004ec4a0 [known] | — |
| DbgHelp | `DBGHELP.DLL` | Minidumps and stack walks in the crash reporter (`Crash_WriteCallStack` S 006e5d70) [known] | — |
| COM support / strsafe / dxerr9 | exe (static) | Tags `LIBRARY:comsupp`, `strsafe`, `dxerr9` [known] | ~10 |
| zlib CRC32 | exe | `crc32`, `crc32_little` S 007627c0 / S 00762520 [inferred: zlib naming and table layout] | — |
| WinSock | exe `WS2_32.DLL` (CVar server only), tincat3 `WSOCK32.DLL` (27) | Import references [known] | — |

---

## 5. Curiosities

These are off the critical path, kept for later. Source: [CURIOSITIES.md](../mapping/CURIOSITIES.md).

**In-game debug toolbar.** `nMenu::Game::SetupHud` S 005ed700 builds a row of debug icons in the top right
("Start debug session", "Hide Ui for screenies", "Toggle Camera Mode", "Toggle Game Speed", "Toggle Grabbing
Mode") and AI, harbour, flag and military debug toggles (S 00617f30, S 006197a0, S 0061a290, S 0061aa90)
[inferred]. The only write to its gate (`nMenu::System+0xa4`) is the constructor, which sets it to 0, so the row
is probably created in retail and hidden under the resource overview [inferred]. `HandleDebugKey` S 0061a9c0
switches the AI-debug views with r/m/i/c, but is blocked in multiplayer [inferred]. To test it, move the
resource overview in `data/game/ui/layout/menuingame.xml` with AdKEd (a data change, not a binary patch).

**Remote CVar server.** Console variables (`CVar`, ctors S 005c6270 / S 005c6370 / S 005c64a0) can be
served over a socket by `CVarServer` (thread S 0067df40, singleton `0088ca58`) and shown in a native
`DebugToggleWindow` [inferred]. The server is created only when byte `0088ca50` is non-zero. What sets that byte
is [TODO]; if it is a config or command-line switch, the server would be a legitimate live inspector.

**Developer flags.** `-mptest` sets `0088b840`, and nothing reads it [known]. `-nolobby` skips the online stack,
and the lobby map is still enterable in a dummy state [known, observed live]. `-start <name>` and `-map <name>`
boot straight into a map or save (parser S 00403ac0) [known]. The `nMenu::Debug` screen exists, but no opener
has been found [TODO].

**Dormant LAN multiplayer.** NComm modes 1 and 2 have no caller. tincat3 still has LAN discovery (mode
1 = server, 2 = client), `ConnectionLANLobby` (LAN hosting with a password flag), the `S2TNG_BC` broadcast
callbacks, and the `nMenu::NetInfo` per-slot session panel. No LAN layout XML ships, so this is unreachable from
the shipped UI [inferred]. The mode table is pending on board #595.

**Lobby billboards.** `ad0..ad2.tga` are live web pages from `http://www.funatics.de/sadk/forwarding{1,2,3}.html`
rendered into 1024×512 textures through an IE control (`url2tex`). Because they are plain http, a hosts
override could serve them [inferred]. The Hall of Fame URLs are configurable in `LobbySettings.ini`
(`HallOfFameURL0..2`) [known].

**PhysX only in the lobby.** The only PhysX SDK and character-controller creation is `LobbyPhysics_Init`
S 00500410. The RTS does not appear to use PhysX, while the full NXU/COLLADA importer is linked in [inferred].

**Map editor code still in the binary.** Retail SAdK still contains the `.s2m` writer `GameFile_SaveMap`
S 005a9fa0, the grid-bit and continent derivation (called only from editor or debug paths), a debug ship-route
tool (S 0078d7c0..0078d960), `EditorListItem` and `nMenu::Debug` [inferred]. Whether these pieces are complete
and reachable is unknown.

**The S2DnG editor lead.** *Settlers II: 10th Anniversary* (DnG, the same engine) ships a full map editor, and
its map format is reported to be very similar. The plan is to carry SAdK names, prototypes and structs over to
the DnG binary with Ghidra Version Tracking or function-hash matching, analyse only the editor-specific code,
and first run one decrypted DnG map through `mapping/work/mapdoc/scratch/s2m_parse.py` to measure the format
difference [guess until measured]. The map-format reference is
[map-format.md](map-format.md).

---

## 6. Open points

- The meaning of NComm manager states 3 and 4. The game code tests them, but `EManagerState` only names
  0..2 (§2.6).
- The `StartUpNetwork` mode table for modes 1 and 2 (board #595).
- What sets the CVar-server gate byte `0088ca50`.
- The unpack codec behind `FileCrypt_DecryptAndUnpack` (S 007624a0).
- The lobby connection completes its login on 207 SessionKey in the binary (T 10023cc0). Only the UC path
  completes on 153. This should be confirmed against a capture.
- In the static model, which client event arms the referee login during a real match start.
  `WorldScreen::OnVillageConnectionLoggedOut` S 004316c0 arms it, but the village `LoggedOut` reachability was
  questioned in [MATCH_START.md](MATCH_START.md). The stub's push-after-153 path works live.
- The 1,579 vtable-owner findings (the `NComm_Session_*` and `NComm_Slot_*` accessors are already fixed).
