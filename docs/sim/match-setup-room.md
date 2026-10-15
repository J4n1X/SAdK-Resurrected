# Multiplayer match set-up: hosting, browsing, the pre-game room

Binaries: `sadk_noav.exe` (base 0x400000, addresses written S 00xxxxxx) and `tincat3.dll` (T 10xxxxxx). Tags:
**[known]** = read at the given address or in the named data file and key; **[inferred]** = one step of reasoning
from what is visible; **[TODO]** = not established, with what would settle it. Nothing here was observed in the
running game, except where a dated live observation of another document is cited as such.

Related documents, not repeated here:

- `docs/sim/network-session.md` — the NComm session below the room: roles, manager states, the join handshake
  (0x30001), all `0x3000x` events and their wire format, kicks, leave, host loss, file transfer.
- `docs/NCOMM_GAME_PROTOCOL.md` — the slot record `NComm::PlayerInfo` field by field, ready-state writers.
- `docs/MATCH_START.md` — the referee steps between "room complete" and "map loads".
- `docs/message-catalog.md` — the lobby messages 168, 169, 170, 171, 177, 153 field by field, with the required
  server behaviour.
- `docs/sim/players-victory.md` §2.4 — what start resources, win condition and fog of war do in the match.
- `docs/map-format.md` §1.3 — map types, folders, `MapInfo`.

---

## 1. Purpose and scope

This is the client side of setting up a network match inside the lobby world:

- the **game browser** (`LobbyMenu::BrowseGameDialog`): the list of hosted games, the detail panel, Join and
  Create;
- the **server list model** behind it (`LobbyComm::ServerList`, `LobbyComm::GameServerInfo`) as far as it feeds the
  two dialogs: how a game is registered, updated and removed at the lobby server;
- the **pre-game room** (`LobbyMenu::SetupGameDialog`): six player rows, the settings panel, map choice through
  `LobbyMenu::SelectMapDialog`, password, wager, ready and the start condition;
- how the room becomes a running match (the hand-over to `docs/MATCH_START.md`).

The room is a **view and editor of the NComm session description** (`NComm::EventGameInformation`, manager
`+0xdc`). It owns no game state of its own: every value shown is read from the session each frame, every edit is
a call into `NComm_Manager` (host) or an event to the host (client) [known, S 004573c0, S 00455fd0, S 00452e40].

All three dialogs are children of the lobby's `LobbyMenu::WorldScreen` (the 3D village screen). There is no
separate "room screen": the player keeps walking and chatting in the village while the room dialog is open or
minimised [known, S 004389d0, S 00435980].

Out of scope: the free-game panel of the offline menu (frontend-screens document); it shares only the helpers
listed in §5.4.

---

## 2. Data model

### 2.1 `LobbyMenu::SetupGameDialog` (0xbc0 bytes; vftable S 007d931c)

Allocated with `operator new(0xbc0)` by `LobbyMenu::System::OpenSetupGameDialog` S 0042bc40; layout file
`lobbySetupGameDialog.xml` (constructor S 004549b0) [known]. `+0x00..+0xb47` is the base `LobbyMenu::DialogBase`.

| Offset | Type | Field | Meaning | Evidence |
|---|---|---|---|---|
| +0xb48 | widget (kind 0xe) | `MapPreview` | map preview picture, child of `GameSettingsPanel` | S 00456c70 |
| +0xb4c | button (0xc) | `SelectMapButton` | opens the map picker | S 00456c70 |
| +0xb50 | button (0xc) | `BetGame` | shows the wager (text at widget `+0x254`), opens the stake dialog | S 00456c70 |
| +0xb54 | label (9) | `MapName` | | S 00456c70 |
| +0xb58 | label (9) | `MapSize` | | S 00456c70 |
| +0xb5c | label (9) | `MaxPlayer` | | S 00456c70 |
| +0xb60 | button (0xc) | `PrivateGame` | shows the password text, opens the password dialog | S 00456c70 |
| +0xb64 | drop-down (0x14) | `StartResources` | | S 00456c70 |
| +0xb68 | drop-down (0x14) | `WinCondition` | | S 00456c70 |
| +0xb6c | drop-down (0x14) | `FogOfWar` | | S 00456c70 |
| +0xb70 | drop-down (0x14) | `RankedGame` | | S 00456c70 |
| +0xb74 | button (0xc) | `MinimizeButton` | looked up in the dialog root, hotkey `m` (XML `hotkey="m"`) | S 00456c70 |
| +0xb78 | button (0xc) | `LeaveButton` | hotkey 27 (Esc) | S 00456c70 |
| +0xb7c | button (0xc) | `ReadyButton` | | S 00456c70 |
| +0xb80 | ptr | selectMapDialog | child `SelectMapDialog`, created hidden in `OnShow` | S 00455f20 |
| +0xb84 | ptr | setStackDialog | open wager dialog or 0 | S 00457d50, S 00457900 |
| +0xb88 | ptr | setPasswordDialog | open password dialog or 0 | S 00457d50, S 00452d00 |
| +0xb8c | std::string | previewMapName | map whose preview texture is loaded | S 00454fc0 |
| +0xba8 | bool | minimized | set by `MinimizeButton`; cleared by Join / Create / the restore action and when the room is complete | S 00457f00, S 00457c7e |
| +0xbac | i32 | settingsChangedMs | countdown in ms, restarted at **3500** (0xdac) whenever the session's `settingsCrc` changes; only use: the minimised indicator blinks while it is > 0 | S 00457b32, S 00435980 |
| +0xbb0 | u32 | lastSettingsCrc | last seen `settingsCrc`; initial -1 | S 00457b1d, S 004549b0 |
| +0xbb4 | bool | rowsBound | the six rows' callbacks are registered (once) | S 00456790 |
| +0xbb8 | ptr | connectingMsgBox | the "connecting to game server" box or 0 | S 00457a75 |

A widget whose kind does not match the expected one is stored as NULL [known, S 00456c70]. The Ghidra struct
names `+0xbac` / `+0xbb0` `countdownMs` / `cachedSession237`.

**Player rows.** Six containers named `PlayerOne`, `PlayerTwo`, `PlayerThree`, `PlayerFour`, `PlayerFive`,
`PlayerSix` (table S 0087a720, built by the static initialiser S 007bec50), row *i* = slot *i* of the session.
Children of a row [known, S 00456790, S 00453a20, S 00454560, S 00454cf0]:

| Child | Kind | Role |
|---|---|---|
| `PlayerPreview` | 0xe | rendered avatar / AI portrait |
| `PlayerStatus` | 9 | ready text |
| `NotAvailable` | 9 | shown instead of the status for a slot the map does not have |
| `PlayerType` | 0x14 drop-down | occupant: name, open, closed, CPU level |
| `PlayerTribe` | 0x14 drop-down | tribe |
| `PlayerTeam` (+ `PlayerTeamIcon`, kind 0xe) | 0xd button | team, cycles on click |
| `PlayerHQ` | 0xd button | start position, cycles on click |
| `PlayerColor` (+ `PlayerColorBlob`, kind 0xe) | 0xd button | colour, cycles on click |

Each of the five interactive widgets carries its row index at widget `+0x28` (i64) [known, S 00456790].

### 2.2 `LobbyMenu::SelectMapDialog` (0xb78 bytes; vftable S 007d9b7c)

Layout `lobbySelectMapDialog.xml` (constructor S 00459cd0) [known].

| Offset | Type | Field |
|---|---|---|
| +0xb48 | observer list | map chosen (args: dialog, `std::string*` file name) |
| +0xb54 | list box (kind 0x16) | `MapList` |
| +0xb58 | vector&lt;std::string&gt; | map file names, index = row user value |
| +0xb68 | button | `OkayButton` |
| +0xb6c | button | `AbortButton` |
| +0xb70 | i32 | selected index, -1 = none |

### 2.3 `LobbyMenu::BrowseGameDialog` (0xb60 bytes; vftable S 007d9834)

Layout `lobbyBrowseGameDialog.xml` (constructor S 00457ff0) [known, Ghidra struct, S 004580a0].

| Offset | Type | Field |
|---|---|---|
| +0xb48 | list box (0x16) | `GameList` |
| +0xb4c | button | `CloseButton` |
| +0xb50 | button | `JoinButton` |
| +0xb54 | button | `CreateButton` |
| +0xb58 | i32 | selectedServerId, -1 = none |
| +0xb5c | ptr | open `GetPasswordDialog` or 0 |

Two text blocks (kind 0x18) are looked up by name on use: `PlayerList` and `GameSettings` [known, S 00458ac0].
A list row (XML template `item`) has the children `Protected` (picture), `RankedGame` (picture), `GameName`,
`PlayerCount`, `MapName`, `GameType` (labels); the row stores the server id at row `+0x28` [known, S 004593c0].

### 2.4 `LobbyComm::GameServerInfo` (0x9c bytes): one hosted game as the browser sees it

Built and refreshed from a TinCat game-server descriptor (lobby message 170) by `UpdateFromDescriptor`
S 0048da70 [known, Ghidra struct].

| Offset | Type | Field | Source in message 170 (`docs/message-catalog.md`) |
|---|---|---|---|
| +0x04 | u32 | serverId | `server_id` |
| +0x08 | std::string | name | `name` |
| +0x24 | std::string | mapName | `map` |
| +0x40 | std::string | category | always the literal `Multiplayer` |
| +0x5c | bool | passwordRequired | `password_required == 1` |
| +0x5d | bool | hardcore (= the host's ranked flag) | `hardcore == 1` |
| +0x60 | i32 | wager | description token 4 |
| +0x64 | i32 | startResources | description token 1 |
| +0x68 | i32 | winCondition | description token 2 |
| +0x6c | i32 | fogOfWar | description token 3 |
| +0x70 | u32 | occupied | `max_spectators + ai_players` (u16 + u16) |
| +0x74 | u32 | maxPlayers | `max_players` |
| +0x78 | u32[4] | ipOctets | `ip`, parsed as dotted IPv4 |
| +0x88 | u32 | port | `port` |
| +0x8c | vector&lt;std::string&gt; | playerNames | description tokens 5.. |

`cur_players`, `owner_id`, `version`, `running` and the other fields of 170 are not read for a game [known,
S 0048da70].

**Description string** (ASCII, separator `|`), written by the host (`LobbyServerList_BuildGameDescription`
S 0046a850) and parsed by every browser (`ParseDescriptionData` S 0048d810) [known]:

```
<buildVersion>|<startResources>|<winCondition>|<fogOfWar>|<wager>|<name 1>|<name 2>...
```

- `buildVersion`: decimal `NComm_GetBuildVersion()` (34688 in this build, `docs/sim/network-session.md` §3.5);
  the parser ignores this token: the browser does not filter by version.
- the three settings: decimal session bytes `+0x226`, `+0x225`, `+0x227` (§2.6); `wager`: decimal u32.
- names: the player name of every slot 0..5 that is human and filled, in slot order.
- The builder writes a `|` after every element and then drops the last character of the string, so a
  description without names is `<buildVersion>|<startResources>|<winCondition>|<fogOfWar>|<wager>` (5 tokens)
  [known, S 0046a850].
- The parser needs **at least 6 tokens** (so at least one name); with fewer it changes nothing and returns
  false, and the caller ignores the result. Numbers are read with `atol` (non-numeric text gives 0).

### 2.5 `LobbyComm::ServerList` (0xac bytes; `LobbyComm::System +0x54`, getter S 0046b610)

Fields used here [known, Ghidra struct, constructor S 0046a160]:

| Offset | Type | Field |
|---|---|---|
| +0x08 | interface | TinCat game-server observer face (its methods run with `this = ServerList + 8`) |
| +0x30 | observer list | game added (args: list, `GameServerInfo*`) |
| +0x3c | observer list | game updated |
| +0x48 | observer list | game removed |
| +0x54 | observer list | create succeeded (args: list, new server id) |
| +0x60 | observer list | create failed (args: list, error code) |
| +0x6c | ptr | TinCat `GameServerManager` (vtable `+0x20` create, `+0x24` update, `+0x28` delete) |
| +0x84 | vector&lt;GameServerInfo*&gt; | the known games (first element pointer at `+0x88`) |
| +0x9c | u32 | **hostedGameId**: id of the game this client hosts |

`hostedGameId` values [known, constants S 007db520 / S 007db524, S 0046aaa0, S 0046a6a0, S 00469990,
S 00468410]:

| Value | Meaning |
|---|---|
| `0xFFFFFFFF` | none (initial; after a failed create; after a delete result with error 0 while a real id is held (`DeleteResultReceived` S 00469990; a delete error keeps the id); after leaving) |
| `0xFFFFFFFE` | create sent, answer pending |
| other | the server-assigned id |

### 2.6 The session values the room edits

The session description is specified in `docs/sim/network-session.md` §2.5 and the slot in
`docs/NCOMM_GAME_PROTOCOL.md`. Value ranges as the room produces them:

| Session field | Offset | Values | Evidence |
|---|---|---|---|
| maxPlayers | +0x224 | number of start positions of the map (2, 4 or 6 with the shipped maps) | S 00454c3a (`OnMapSelected`) |
| winCondition | +0x225 | 1 destroy all enemies · 2 conquer · 3 coin; drop-down index + 1. 0 (endless) cannot be chosen in the room | S 00454ad0; `lobbySetupGameDialog.xml` `WinCondition` `string0..2` |
| startResources | +0x226 | 0 high · 1 medium · 2 low; drop-down index | `StartResources` `string0..2` |
| fogOfWar | +0x227 | 0 enabled · 1 disabled; drop-down index | `FogOfWar` `string0..1` |
| fetchMapFromHost | +0x228 | always 0 in the game; the assetshare mod's hook of `SetGameSettings` passes 1 for every online host (read 1 for two stock maps with the mod active [live, 2026-10-12]) | S 00454ad0, S 0046aaa0; `lobby/mods/assetshare` |
| mapFileType | +0x229 | the map type under which `GameFile_LoadMapInfo` found the map (`MapInfo +0x1d0`): a map found in `freeGameMaps` keeps the `mapType` stored in its own `MapInfo` (0 in every shipped map); the function overwrites it only on a fallback, 3 for a file in the Documents folder, 10 for a `.sav` [known, `docs/live-checks/2026-10-12_read-from-code.md`]. The assetshare mod passes 3 for every online host (read 3 for two stock maps [live, 2026-10-12]); without it a stock map gives 0 | S 00454ad0, S 005aaa30 |
| gameId | +0x22a | the lobby server id of the game; 0 until the create answer arrived | S 00457f90, S 0040c320 |
| rankedGame | +0x22e | 0 / 1; drop-down index (`!No`, `!Yes`) | `RankedGame` `string0..1` |
| wager | +0x233 | 0 .. the host's gold at the time of choosing; a wager set through the bet button read 100356 with the host's gold (`AvatarProxy +0xd0`) at 100357, and `settingsCrc` (+0x237) changed with the map and with the wager [live, 2026-10-12]. Whether the stake dialog stops at the host's gold was not seen (the maintainer's impression with a balance of about 100,000 was "unlimited") | S 00457d50, S 00457900 |
| passwordMd5 | +0x23b | MD5 of the password text; all zero = none, also stored for the empty text; host only (not on the wire) | S 00413c60; `docs/sim/network-session.md` §3.5 |

Slot values the room produces [known]:

| Slot field | Values | Evidence |
|---|---|---|
| kind (+0x3b) | 0 open · 1 human · 2 AI · 3 closed | S 004550f0, S 00453030 |
| aiLevel (+0x3c) | 0 `!CPU Easy` · 1 `!CPU Medium` · 2 `!CPU Hard` | S 004550f0 (menu item `+0x450`) |
| tribe (+0x3d) | 0 Bavarian · 1 Scots · 2 Egyptian; -1 is shown as `!TRIBE_NAME_RANDOM` but no menu entry sets it | S 004556c0, S 00454400, table S 0087a9d8 |
| colour (+0x3e) | 0..7 | S 00453630 |
| team (+0x3f) | -1 (none) or 0 .. humans + AIs - 1 | S 00453290 |
| playerIndex (+0x3a) | start position: -1 (random, shown `?`) or 0 .. maxPlayers - 1 (shown `1`..`6`) | S 00453460, table S 0087a890 |
| readyState (+0x40) | 0 not ready · 1 ready · 2 loaded | `docs/NCOMM_GAME_PROTOCOL.md` |

Static tables [known]:

- **Room colour swatches**, RGBA float, S 0087a958, index = slot colour: 0 `(0,0,1,1)` · 1 `(1,0,0,1)` ·
  2 `(0,1,0,1)` · 3 `(1,1,0,1)` · 4 `(1,1,1,1)` · 5 `(0,0.4,0.4,1)` · 6 `(1,0,1,1)` · 7 `(0.1,0.7,0.7,1)`.
  The only readers are in `UpdateRowTeamColorHQ` (xrefs S 00454934, S 00454946): this is the room's display
  table; the in-match player colours are specified in `docs/sim/players-victory.md`.
- **Team icons**, template names, S 0087a7c8 (initialiser S 007bed70), index = team, 6 = no team:
  `t_freegamebuttoniconcaro`, `...heart`, `...moon`, `...pik`, `...star`, `...cross`, `...none`.
- **AI portrait NPC index**, i32[9], S 0087a6f8, index = `tribe * 3 + aiLevel`: Bavarian 7, 8, 9 · Scots 13, 14,
  15 · Egyptian 16, 11, 12. No bounds check on the index (S 00455fd0).
- **Browser setting texts** (index = the value from the description): start resources S 0087aa78
  `!LOBBY_MATCHMAKING_STARTRESOURCES_HIGH / _MEDIUM / _LOW`; win condition S 0087aad0
  `!LOBBY_MATCHMAKING_WINCONDITION_ENDLESS / _DESTROYALLENEMIES / _CONQUER / _COIN`; fog of war
  `!LOBBY_MATCHMAKING_FOW_ENABLED / _DISABLED` (initialisers S 007bf0f0, S 007bf1a0, S 007bf280).

---

## 3. Rules and algorithms

Terms: **host** = `NComm_Manager::IsHost` S 00408410 (role 0, 2 or 4; in the lobby: role 4); **client** =
`IsClient` S 004083b0 (role 1 or 3; in the lobby: role 3); **own row** = the slot whose owner GUID equals the
local GUID (four dwords compared); **gold** = `AvatarProxy +0xd0` of the local lobby avatar
(`LobbyComm::System::GetLocalAvatar` S 004625c0).

### 3.1 Where the dialogs live and when they are visible

`WorldScreen::OnShow` S 004389d0 calls `NComm_Manager::Shutdown(false)` (drops any old session), then creates
the setup dialog (`WorldScreen +0x35c8`) and the browser (`+0x35cc`), both anchored (1, 1) and hidden [known].
`WorldScreen::Update` S 00435980, every frame [known unless noted]:

```
if NComm manager state == 2 (SessionStarted, the room):
    setup dialog visible = not minimized                     (S 0043605c..00436070)
    browser hidden
    MatchmakingIndicator button visible = minimized
    if minimized: indicator marked = (settingsChangedMs > 0) and (elapsed ms mod 1000 < 500)
    chat channel 4 (SETTLERS) enabled
else:
    setup dialog hidden, indicator hidden, chat channel 4 disabled
```

So the room dialog appears by itself as soon as a session exists (after Create or Join) and disappears as soon
as the session ends (leave, kick, host loss, match start). The blinking indicator is the only use of the
3500 ms settings-change timer: it tells a player with a minimised room that the host changed something.

Ways to open things [known]:

| Player action | Effect | Evidence |
|---|---|---|
| Main menu item 0 | `ServerList::CreateGameServer`, minimized = false | S 00437760 |
| Main menu item 1 | show the browser (if hidden) | S 00437760 |
| World action code 8 (offered when nothing or the own avatar is selected and NComm state = 0) | `CreateGameServer`; minimized = false if it returned true | S 00433f60, S 00434230 |
| World action code 9 (same condition) | toggle the browser | S 00434230 |
| World action code 18 (offered instead of 8 / 9 when a session exists and the room is minimised) | minimized = false | S 00433f60, S 00434230 |
| World action code 19 (offered with 18) | no case in the dispatcher: does nothing | S 00434230 |
| Click on `MatchmakingIndicator` | minimized = false | S 00437760 |
| Browser `CreateButton` | `CreateGameServer`; minimized = false when the active lobby screen is the world screen (screen index 3), whatever `CreateGameServer` returned | S 004588e0 |

### 3.2 The game browser

**Feeding the list.** The lobby pushes one message 170 per hosted game and per change; TinCat turns it into a
descriptor and calls `ServerList::AddOrUpdateDescriptor` S 0046a440. For `server_subtype == 1` [known]:

- unknown `server_id`: a `GameServerInfo` is built and appended; "game added" fires;
- known id: `UpdateFromDescriptor`; "game updated" fires. The `running` field is not looked at: a 170 cannot
  remove a game.

A game disappears only through `ServerList::RemoveServer(id)` S 0046a5e0 (the pushed message 169 with ticket 0,
`docs/message-catalog.md`): "game removed" fires, then the entry is erased [known].

The browser subscribes to the five lists `+0x30 .. +0x60` in its `OnShow` S 00459970 (virtual `+0x14`, which
`OpenBrowseGameDialog` S 0042bd10 calls once when it creates the object) and unsubscribes in `OnLeave`
S 00459a70; `BuildWidgets` S 004580a0 asks the list to re-announce every known game
(`RenotifyAllGameServers` S 0046a3c0, which fires "game updated" once per known game) [known].

"Game added" and "game updated" share one handler (`OnGameServerAddedOrUpdated` S 004598b0): the row whose
stored id equals the game's id is refilled; if there is none, a row is appended from the template and filled.
"Game removed" (`OnGameServerRemoved` S 00458300) removes that row; if the game was the selected one,
selectedServerId = -1 and both text blocks are cleared [known].

**A row** (`FillGameRow` S 004593c0) [known]:

| Widget | Content |
|---|---|
| `GameName` | `name`, not localised |
| `PlayerCount` | `<occupied>/<maxPlayers>` |
| `MapName` | `mapName`, passed through the localisation (a map file name is its own key) |
| `GameType` | `category` = `Multiplayer`, localised |
| `Protected` | shown or hidden twice in a row: first by `passwordRequired`, then by `hardcore`. The second call wins, so the lock icon shows the **ranked** flag |
| `RankedGame` | looked up, never touched: always as the layout draws it |

Rows are kept in arrival order; there is no sorting and no filter (not by build version, fullness, password or
map availability) [known: no such code in S 004598b0, S 004593c0, S 00458ac0].

**The detail panel** (`BrowseGameDialog::Update` S 00458ac0, every frame) [known]. Selected row = the first row
whose selected flag (row `+0x2ec`) is set; none → selectedServerId = -1, both text blocks cleared, Join disabled.
With a selection whose id is still in the server list:

- `PlayerList`: the player names, one per line (set only when the text is not empty);
- `GameSettings`: three lines `<label> <value>` with the labels `!LOBBY_START_RESOURCES_LABEL`,
  `!LOBBY_WIN_CONDITION_LABEL`, `!LOBBY_FOG_OF_WAR_LABEL` and the values from the tables of §2.6, plus a fourth
  line `!LOBBY_BETGAME_LABEL <wager>` when the wager is not 0;
- **Join enabled** = `occupied < maxPlayers` and `gold >= wager`.

The local avatar is fetched from the village connection before the selection is evaluated; if that fails the
function returns at once: selectedServerId, the text blocks and the Join button all keep their state [known].

**Join** (`HandleButtonClicks` S 004588e0) [known]: needs a selected row whose game is known and
`occupied < maxPlayers`; otherwise nothing happens (no message).

- No password flag: `GameServerInfo::JoinGame` S 0048d030, then minimized = false (when the active lobby screen
  is the world screen, screen index 3).
- Password flag: a `GetPasswordDialog` opens. On its OK (`OnJoinPasswordEntered` S 00458600, result 0) the
  selected row is looked up again: full → message box `!ERROR` / `!LOBBY_MATCHMAKING_GAMEISFULL`; no longer
  password-protected → nothing; else `JoinGameWithPassword(text)` S 0048d0c0 and minimized = false (under the
  same screen index 3 condition). Any other result (abort = 1) only closes the dialog; the dialog is closed and
  `+0xb5c` cleared in every case.

`JoinGame` / `JoinGameWithPassword` [known]:

1. NComm connection settings (`ai::ncomm::ConnectionSettings`): IP octets = `GameServerInfo +0x78..+0x84`,
   port = `+0x88`, password string (`+0x18`) = empty or the typed text.
2. `NComm_Manager::Shutdown(false)`; `StartUpNetwork(3)`; `ConnectAndJoin()` (`docs/sim/network-session.md`
   §3.3, §3.5). The first failure returns false.

The return value is not used by either caller: a failed connect shows nothing [known]. On success the manager is
in state 2 and the room appears (§3.1); it stays empty until the host's first GameInformation arrives, because
`RefreshSettingsView` skips everything while the session's map name is empty [known, S 0045744f].

The gold test is made only here and in the room (§3.6); the join handshake itself carries no gold value
[known, `docs/sim/network-session.md` §3.5].

**Close** hides the dialog [known].

### 3.3 Hosting: registering the game

`ServerList::CreateGameServer` S 0046aaa0 [known]:

1. Return false unless `hostedGameId == 0xFFFFFFFF` and the local avatar exists.
2. List the files of map type 0 (`[data]\maps\freeGameMaps\`, pattern `*`, names without extension), drop every
   name that does not contain `MP_`. Empty → return false. The **first** remaining name is the initial map; its
   `MapInfo` is loaded (the load result is not checked). The list is not sorted here: "first" is the order in
   which `FileScanHolder::FindFilesByPattern` S 006e4f00 returns the names. Neither that function nor
   `FindFilesInDataPath` S 006e4c10 sorts; `FindFilesInDirectory` S 006e4310 appends the names in the order
   `FindFirstFileA` / `FindNextFileA` return them [known]. Which map that is in practice is open (§10 item 2).
3. `Shutdown(false)`, `StartUpNetwork(4)`, `ConnectAndJoin()`; any failure → return false.
4. `SetGameSettings(map, map GUID, maxPlayers = number of start positions, startResources 2 (low),
   winCondition 1 (destroy all enemies), fogOfWar 0 (enabled), mapFileType, fetchMapFromHost 0, ranked 0)`.
5. `SetSlotSetup(slot 0, kind human, tribe = the avatar's tribe, team 0, colour 0, start position 0)`.
6. Send lobby message **168 AddGameServer** through the TinCat manager (`+0x20`): name = `<avatar name>` directly
   followed by the localised `!LOBBY_GAME`, description (§2.4), empty password, port = `gamePort` of
   `network.ini` (the first dword of the manager's config block `+0x360`), `server_type` 5, `server_subtype` 1,
   version `1.0`, `max_players` = start positions, next count 1; the remaining arguments are in
   `docs/message-catalog.md`.
7. Send accepted → `hostedGameId = 0xFFFFFFFE`, return true. Send refused → `Shutdown(false)`, return false.

The answer (`CreateResultReceived(id, error)` S 0046a6a0, from message 153) [known]:

- not pending → logged (`CreateResult received for GameServerID %u, but no create pending.`) and dropped;
- error 0 → `hostedGameId = id`; "create succeeded" fires → `BrowseGameDialog::OnCreateGameSucceeded` S 00457f90:
  the browser hides and `NComm_Manager::SetGameIdAndBroadcast(id)` S 0040c320 stores the id as the session's
  **gameId** and broadcasts the session;
- error ≠ 0 → `hostedGameId = 0xFFFFFFFF`; "create failed" fires → message box `!ERROR` /
  `!COULD_NOT_CREATE_GAME` (S 00458520); `Shutdown(false)`, so the room disappears.

While the dialog is visible, the local peer is host and the id is `0xFFFFFFFF` or `0xFFFFFFFE`, the room dialog
shows the message box `!PLEASE WAIT` / `!Connecting to Game Server` (type 5; created once and kept at
`+0xbb8`), disables its input (`SetInputEnabled(0)`) and does nothing else that frame (§4.1) [known,
S 00457a53..00457ae8].

**Keeping the lobby entry current.** `ServerList::UpdateGameServer` S 0046aff0 sends message **177
ChangeGameServer**. It is called after every GameInformation broadcast of a role 4 host
(`BroadcastGameInfo` S 004090e0) and at the end of every row edit handler (§3.5) [known]. It sends only when
`hostedGameId` is a real id, the local avatar exists, the manager state is 2, and the session's map name is not
empty and its `MapInfo` loads. Content [known]: name = `<avatar name>`, a space, the localised `!LOBBY_GAME`;
description (§2.4); password text = the literal `PASSWORD` when the session's digest is not zero, else empty (the
real password never leaves the host); `max_players` = start positions − closed slots; `max_spectators` =
human slots; `ai_players` = AI slots; `game_mode` = winCondition; `hardcore` = rankedGame; `map` = the map name
(argument order read at the call, S 0046b28f..0046b2ad).
The two create / update names differ by that one space.

Consequence for the browser: `occupied` = humans + AIs and `maxPlayers` = slots that are not closed, so Join is
offered exactly while an open slot exists [inferred from S 0046aff0 and S 0048da70].

### 3.4 The settings panel

`RefreshSettingsView` S 004573c0 runs every frame while the dialog is visible and the session has a map name
[known]:

- `MapName` = the localised map name, cut before the first `(` when one occurs at a position > 0;
- map preview: `UpdateMapPreviewImage` S 00454fc0 loads the preview picture of the map (resource path kind
  `FreeGameMapPreview`; `docs/sim/formats-inventory.md` lists the folders) when the name changed and the file
  exists; `MapPreview_PlaceStartMarkers` S 005e7cc0 shows the markers `start0..start7` at the map's start
  positions (x scaled by the map width, y flipped: `height - y - 1`), numbered from 1, and hides the rest;
- `MapSize` = `<width> x <height>` (`MapInfo +0x40`, `+0x44`); `MaxPlayer` = maxPlayers;
- the four drop-downs show the session values (win condition as value − 1);
- `BetGame` text = the wager as a decimal number;
- client: `BetGame`, `PrivateGame`, `RankedGame` disabled; the `PrivateGame` text is `!DUMMY_PASSWORD_STARS`
  when the session digest is zero and `!EMPTY_STRING` otherwise (S 00457712: the zero branch takes the string at
  S 007d969c). A client's digest is always zero (it is not serialised), so a client always gets
  `!DUMMY_PASSWORD_STARS`, whether or not a password is set [inferred];
- host: those three enabled (the final word on `RankedGame` is `Update`, below);
- if the own slot's playerIndex + 1 > maxPlayers (the map got smaller): the own start position is set to the own
  **slot index** through `ApplySlotSettings` (§3.5).

`Update` S 00457a00 then sets, every frame, with `h` = host [known, S 00457ca1..00457d39]:

| Widget | Enabled when |
|---|---|
| `SelectMapButton`, `BetGame`, `PrivateGame`, `StartResources`, `WinCondition`, `FogOfWar` | `h` |
| `RankedGame` | `h` and maxPlayers == 2 and connected humans == 2 (`CountConnectedHumans` S 004133c0) |

Clicks (`HandleSettingsClicks` S 00457d50) [known]:

- **A setting drop-down** (any of the four): the clicked item becomes the drop-down's value, then
  `OnMapSelected("")` re-applies map and settings.
- **`SelectMapButton`**: refresh and show the map picker (if it exists and is hidden).
- **`BetGame`**: unless a stake dialog is open, open `SetStackDialog` with minimum 0, maximum = gold, initial
  value 1 (`OpenSetStackDialog(cb, 0, gold, false, 1)`).
- **`PrivateGame`**: unless a password dialog is open, open `SetPasswordDialog`, pre-filled with the button's
  current text.

`OnMapSelected(name)` S 00454ad0 — host only; a client returns at once [known]:

1. Empty name → use the session's map name; still empty → return.
2. Load the `MapInfo` (type 0, with fallback to other types).
3. ranked = the `RankedGame` drop-down value ≠ 0 **and** the map has exactly 2 start positions.
4. `NComm_Manager::SetGameSettings(name, GUID from MapInfo, maxPlayers = start positions, startResources =
   drop-down value, winCondition = drop-down value + 1, fogOfWar = drop-down value, mapFileType =
   MapInfo +0x1d0, fetchMapFromHost = 0, ranked)`.
5. Place the start markers.

`SetGameSettings` S 0040bfd0 [known]: stores each value that differs; if anything differed, **every human slot's
readyState becomes 0** (the host's included); then always `RefreshSlots` and `BroadcastGameInfo`. A smaller
maxPlayers makes `RefreshSlots` kick the occupants of the slots that fell away with `!GAME FULL` and clear those
slots (`docs/sim/network-session.md` §3.5).

**Map picker** (`SelectMapDialog`) [known]: `RefreshMapList` S 0045a300 clears the list and adds, for map type 0
only, every file whose name contains `MP_` (`SelectMapDialog_AppendMapFiles` S 00459f40): row text = the
localised file name, row colour (0.8, 1.0, 0.8, 1.0), user value = index into the name vector. Each frame the
first selected row sets the selected index and `OkayButton` is enabled only with a selection (S 00459bb0).
`OkayButton`, or a double click on a row (`ConfirmSelectedMap` S 00459ed0), hides the picker and fires "map
chosen" with the file name → `OnMapSelected(name)`. `AbortButton` and the frame's close button hide it. User
maps (type 3) are never listed.

**Wager** (`OnWagerChosen(amount, cancelled)` S 00457900) [known]: the stake dialog clamps the typed number to
[0, gold] and reports it on OK (S 00441560; Cancel reports `cancelled`). Not cancelled: the button text is set
and, on the host, `NComm_Manager::SetWager(max(amount, 0))` S 0040c1b0: if the value differs, it is stored and
every human slot's readyState becomes 0; always `RefreshSlots` + `BroadcastGameInfo`.

**Password** (`OnPasswordInputClosed(result, text)` S 00452d00) [known]: the password dialog reports 0 = OK with
the text, 1 = abort, 2 = clear (S 0045dab0). Result 0: button text = the text (in clear), host:
`NComm_Manager::SetGamePassword(text)`. Result 2: the same with the empty string. Result 1: nothing. The dialog
is closed in every case. `SetGamePassword` S 0040c220 computes MD5(text) and compares it with the stored
digest; only when they differ it stores the new digest (all zero for the empty text, S 00413c60), calls
`RefreshSlots` and broadcasts. Because MD5 of the empty text is never all zero, clearing a password, or
confirming an empty one, always broadcasts. The players already in the room are not affected, and their ready
states are kept.

### 3.5 The player rows

`RefreshPlayerRows(previewMode)` S 00455fd0 runs every frame while the dialog is visible (mode 0) and once more
at the match start (mode 1) [known]:

1. Build six preview actors: human slot → an avatar with the slot's `avatarTribeGenderLevel` (tribe, gender,
   level nibbles) and the eight colour nibbles of `avatarColors`; AI slot → the NPC of the table in §2.6; other
   → none. The lobby renders them (`CLobby` vtable `+0xcc`, arguments: actors, mode, the six playerIndex values)
   and returns one texture handle [known for the call; the renderer is not part of this document].
2. `UpdatePlayerRow` S 00454cf0 for each slot, with `local` = own row and `h` = host:

**Status** (`UpdateRowReadyStatus` S 00453a20) [known]:

- slot state 5 (not part of the map): `PlayerStatus` hidden, `NotAvailable` shown;
- else `PlayerStatus` shown: `!LOBBY_PLAYER_READY` in colour bytes (0, 255, 0) when the slot `IsReady(false)`
  **and** all assigned start positions are distinct **and** all human / AI colours are distinct; otherwise
  `!LOBBY_PLAYER_NOT_READY` in (255, 0, 0). `IsReady(false)` S 00414f50: a human needs readyState 1 or 2, an AI
  or closed slot is always ready, an open slot never. So every row turns red while two players share a start
  position or a colour.

**Occupant** (`UpdateRowPlayerType` S 00453c80; label text, item value, selectable) [known]. While the drop-down
is open it is left alone, except that it is closed and emptied when it shows a human (value 1) and the slot is no
longer human.

| Viewer | Slot | Label | Value | Selectable |
|---|---|---|---|---|
| own row | — | the player's name | 1 | no |
| host | state 5 | `!LOBBY_SLOT_DISABLED`, then the widget is hidden | -1 | no |
| host | human | the name | 1 | yes |
| host | open | `!LOBBY_SLOT_OPEN` | 0 | yes |
| host | AI level 0 / 1 / 2 | `!CPU Easy` / `!CPU Medium` / `!CPU Hard` | 2 | yes |
| host | closed | `!LOBBY_SLOT_CLOSED` | 3 | yes |
| client | state 5 | `!LOBBY_SLOT_DISABLED`, hidden | -1 | — |
| client | open / human / AI / closed | as above | 0 / 1 / 2 / -1 | no |

A host row whose kind is none of the four gets the label `!!!`, value -1, not selectable; an AI slot whose
level is not 0..2 leaves the label unchanged [known].

Opening the drop-down fills it (`PopulatePlayerTypeMenu` S 004550f0) [known]: own row → only the own name;
host on another row → (the occupant's name, value 1, when a human sits there), `!CPU Easy`, `!CPU Medium`,
`!CPU Hard` (value 2, AI level 0 / 1 / 2 in the item), `!LOBBY_SLOT_CLOSED` (3), `!LOBBY_SLOT_OPEN` (0); a
state 5 slot → only `!LOBBY_SLOT_DISABLED`; client → one entry describing the current occupant.

Choosing an entry (`OnPlayerTypeSelected` S 00453030) [known]:

- value 2: `ApplySlotSettings(slot, kind 2, tribe = slot mod 3, team = slot, colour = slot, start = slot,
  aiLevel = the item's level)`;
- any other value: `ApplySlotSettings(slot, kind = value, everything else unchanged)`.

**Tribe** (`UpdateRowTribe` S 00454400) [known]: shown for human and AI slots, hidden otherwise; label =
`!TRIBE_NAME_BAVARIAN` / `_SCOTS` / `_EGYPTIANS`, or `!TRIBE_NAME_RANDOM` for -1; selectable on the own row, and
for the host on AI rows. The menu offers the three tribes with values 0, 1, 2 (`PopulateTribeMenu` S 004556c0);
`OnPlayerTribeSelected` S 004530d0 applies the value.

**Team, colour, start position** (`UpdateRowTeamColorHQ` S 00454560) [known]: the three buttons are shown for
human and AI slots, hidden otherwise.

- Team: icon of the table in §2.6. The team button and its icon are **enabled only while the game is not ranked
  and the wager is 0** (flag computed in S 00454e96 from the `RankedGame` drop-down value and `wager > 0`, the
  same for all six rows).
- Colour: the blob gets the RGBA of the swatch table.
- Start position: text `1`..`6` or `?`, drawn in the slot's colour.

Clicks [known]:

| Button | New value | Evidence |
|---|---|---|
| team | team + 1; when that is ≥ human slots + AI slots: -1 | S 00453290 |
| start position | playerIndex + 1; when that is ≥ maxPlayers: -1 | S 00453460 |
| colour | colour + 1; 8 becomes 0 | S 00453630 |

**Applying an edit** (`ApplySlotSettings` S 00452e40; the tribe and the three cycle handlers contain the same
logic inline) [known]:

```
if not own row and not host: return                         (nothing sent)
if no kind and no other value was passed: return            (not even the lobby update)
unchanged arguments take the slot's current values
if own row:
    client: send 0x30002 EventPlayerInformation(tribe, team, colour, playerIndex) to the host
    host:   NComm_Manager::SetSlotSetup(slot, kind 1, tribe, team, colour, playerIndex)
else (host, another row), by the kind to apply (the slot's current kind when none was chosen):
    0 open, 3 closed: SetSlotSetup(slot, kind, -1, -1, -1, -1)
    1 human:          only when "human" was explicitly chosen in the occupant menu:
                      SetSlotSetup(slot, 1, tribe, team, colour, playerIndex); otherwise nothing
    2 AI:             SetSlotSetup(slot, 2, tribe, team, colour, playerIndex); SetSlotAiLevel(slot, aiLevel)
ServerList::UpdateGameServer()                               (message 177; a no-op on a client)
```

Consequences [known from the branches above]:

- A player edits only its own tribe, team, colour and start position. The host edits in addition the kind of
  every other slot and all values of AI slots.
- The host **cannot** change another human's tribe, team, colour or start position: with the slot's kind 1 and no
  kind chosen, nothing is applied.
- Nobody can change the kind of its own slot (its menu holds only the own name).

`NComm_Manager::SetSlotSetup` S 0040bcd0 — needs a host role, manager state 2 and slot < maxPlayers; otherwise it
does nothing [known]:

1. Kind differs from the slot's: a human occupant is **kicked** with reason `!SLOT TYPE CHANGED`
   (`KickPlayer(netId, reason, true)`); the slot is cleared; then kind 0 → `ResetToOpen(slot)`, name `!OPEN`;
   kind 2 → `SetupAi(tribe 0, level 1, colour, playerIndex = team = -1)`, readyState 2, name `!AI`, with
   colour = the lowest of 0..7 that none of the six slots stores (`FindFreeColor` S 00413670; an open slot
   stores its own slot index as colour and team, `ResetToOpen` S 004153d0, and counts here);
   kind 3 → `SetupClosed` (tribe, team, colour, playerIndex -1, readyState 2), name `!CLOSED`; kind 1 → the
   slot stays cleared.
2. Colour (skipped when the requested colour is -1, which is stored as it is):
   ```
   c = requested colour
   loop:
       s = first human or AI slot holding colour c, or none   (FindSlotByColor S 00413720)
       none           -> take c
       s is this slot -> keep the colour (no write)
       s is human     -> c = (c + 1) mod 8, loop
       s is AI        -> the AI slot gets this slot's old colour; take c
   ```
   Open and closed slots are not looked at by `FindSlotByColor`, so their stored colour never blocks a
   requested one.
3. tribe, team, playerIndex = the arguments; `RefreshSlots`; `BroadcastGameInfo`.

`SetSlotAiLevel` S 0040bf40: same gate; for an AI slot whose level differs, store it, `RefreshSlots`,
`BroadcastGameInfo` [known].

On the host the handler of **0x30002** (S 0040e560) applies a client's request with the same colour rule and
sets that slot's readyState to 0 when tribe, team or colour changed (not for a start position change)
[known]. `SetSlotSetup` itself does not touch readyState: the host changing its own row, or an AI row, keeps
everybody's ready state [known].

So "kick" has no button of its own: the host removes a player by giving the slot another occupant type (open,
closed or CPU) [known].

Start positions may be chosen twice (nothing in the editor compares them); the start condition (§3.6), not the
editor, enforces distinct values [known].

### 3.6 Ready, the start condition, the hand-over

**Ready button.** Enabled state, recomputed every frame from the own row (`UpdatePlayerRow` S 00454ef7..00454f8d;
skipped when there is no local avatar) [known]:

```
ReadyButton enabled =
        all assigned start positions are distinct           (ArePlayerIndicesUnique S 00413540; -1 is ignored)
    and gold >= wager
    and connected humans >= 2                               (kind human and a connected net id, S 004133c0)
    and parties > 1                                         (CountParties S 00414b50)
    and session gameId != 0
    and (AI slots == 0 or wager == 0)
```

`CountParties`: over the six slots in state 1 (humans and AIs): the number of distinct team values, where every
slot with team -1 counts as a party of its own [known].

So: a match needs two humans; all players in one team cannot start; a game with a wager cannot contain an AI;
nobody can ready up before the lobby has acknowledged the game.

A click sends **0x30011 PlayerReady(1)** (`SendPlayerReadyEvent(true)` S 00408d80, manager state 2; target =
the network handler's `GetBroadcastNetId`, the constant `0xEFFFFFCC`, S 00418f40; the host applies it,
`docs/sim/network-session.md` §3.6) [known, S 00457f00]. There is **no un-ready click**: the button always
sends 1. The host sets readyState 1 only
if the start positions are distinct at that moment (`docs/sim/network-session.md` §3.6).

A ready state is lost again by [known]:

| Cause | Who | Evidence |
|---|---|---|
| the player changed its tribe, team or colour | that player (clients only, see §3.5) | S 0040e560 case 0x30002 |
| map or any setting changed | all humans | S 0040bfd0 |
| wager changed | all humans | S 0040c1b0 |
| own gold < wager while ready: the dialog sends PlayerReady(0) every frame until the state is cleared | that player | S 00457c13..00457c4a |

**Start condition.** Every frame, on every peer (`Update` S 00457c4f..00457c9c) [known]:

```
if AreAllSlotsReady and ArePlayerIndicesUnique and AreColorsUnique and StartLoading not yet received:
    minimized = false
    if host: NComm_Manager::BroadcastStartLoading()         (0x30012)
```

- `AreAllSlotsReady` S 00413400: every slot below maxPlayers is `IsReady(false)` and at least one of them is
  human. An **open slot blocks the start**: the host has to close it or fill it with an AI.
- `AreColorsUnique` S 004135c0: no colour (other than -1) is used by two human / AI slots.

There is no start button and no countdown: the match starts in the frame in which the last condition becomes
true. What `BroadcastStartLoading` does (closing the session to new logins, replacing start position -1 by a
random free one and team -1 by `rand() % maxPlayers`) is in `docs/sim/network-session.md` §3.8. Note that "no
team" therefore does **not** survive into the match: each such player gets a random team number, which can
equal another player's.

**Hand-over.** Every frame, on every peer (`Update` S 00457bc8..00457c11) [known]:

```
if StartLoading received (manager +0x3cc) and LobbyComm::System state == 9 (VillageEntered):
    ServerList::DestroyGameServer()       host: message 169 RemoveServer for hostedGameId; clients: nothing
    CLobby virtual +0x84                  starts leaving the village
```

From `StartLoading` on the dialog's input is disabled (§4.1). The rest of the chain is in
`docs/MATCH_START.md`: the village connection logs out, the referee login is armed, every client sends
`RegisterGame 0xDB6` on `LoginSuccess`, and on `RegisterGameResult 0xDB8` `WorldScreen` S 00431800 stores the
GameSeed and calls `SetupGameDialog::SetupSession`, then starts the game screen. That handler does nothing when
the world screen has no setup dialog [known].

`RegisterGame` takes from the room (`WorldScreen::OnRefereeLoginSuccess_RegisterGame` S 00432240) [known]:
gameId; the map GUID; the map name; **MapSettings** = a 3-character string `'0' + winCondition`,
`'0' + startResources`, `'0' + fogOfWar` (`GetSettingsDigitString` S 004145f0); rankedGame; wager; the number of
AI slots; and the `avatarId` of the slots below maxPlayers (others 0).

`SetupSession(session)` S 004562d0 fills the load descriptor of the game (`GameLoadDescriptor`,
`docs/sim/players-victory.md` §2.4) [known]:

1. `RefreshPlayerRows(1)`.
2. Find the local map by the session's map GUID (`GameFile_FindMapByGuidAnyType`). Not found → log
   `Map not found: '%s'`; local name ≠ session map name → log `Mapnamen unterschiedlich: '%s' != '%s'`. Both
   only log; the fill continues.
3. Map name = the **local** name found by the GUID (empty when the map was not found), map type 0 whatever
   type the search reported; start resources (`+0x20`) = session startResources; win condition (`+0x244`) =
   session winCondition; random start positions (`+0x24`) = 0; fog of war (`+0x28`) = session fogOfWar.
4. For each of the six slots, keyed by its playerIndex (when that is -1 and the slot index ≥ maxPlayers: the slot
   index): colour, controller, nation (`NComm_GetNationIdForTribe` S 004538b0: the nation whose name is
   `Bavarian` / `Scots` / `Egyptian` for tribe 0 / 1 / 2, -1 otherwise), team, AI level and, when not empty, the
   name. Controller: open or closed → 0; AI → 1; human with the local GUID → 2; other human → 3.
5. The descriptor's network flag (`+0x1ec` of the player block) = the manager's role is not 0.

### 3.7 Leaving, being kicked, losing the host

**Leave** — `LeaveButton` (Esc) and the frame's close button (dialog virtual `+0x90` = vftable slot 36,
S 00452d90, which returns false) both call
`ServerList::DestroyGameServerAndShutdown` S 00468410 [known]:

```
if manager state == 0: nothing
role != 4 (client): NComm_Manager::Shutdown(false); hostedGameId = 0xFFFFFFFF
role == 4 (host):   if hostedGameId is a real id and message 169 RemoveServer was sent:
                        Shutdown(false); hostedGameId = 0xFFFFFFFF
                    otherwise nothing (the host stays in the room)
```

The dialog is not closed by either button; it is hidden by `WorldScreen::Update` once the manager state is no
longer 2 (§3.1). No leave event is sent in the room: the transport is shut down, and the host learns of it
through the lost connection, reopens the slot and broadcasts (`docs/sim/network-session.md` §3.10) [known for
the missing event: `Shutdown` is the only call].

**Kicked** (0x30010, `docs/sim/network-session.md` §3.6): the client shows the text
`<!You were kicked!> - <reason>`, disconnects and shuts the session down, so the room disappears. In the lobby
the text goes to `WorldScreen`'s message callbacks: join and leave notices are appended to the chat
(`MessageCallbacks_AddChatText` S 00431ba0), the third callback shows a message box titled `!ERROR`
(`ChatSink_ShowError` S 004330c0) [known for the two functions; that the kick text uses the third one is
inferred from its slot position, `docs/sim/network-session.md` §2.3]. Reasons a player in or entering a room can
meet: `!VERSION MISMATCH`, `!CHECKSUM MISMATCH`, `!PASSWORD_MISMATCH`, `!GAME FULL`, `!SLOT TYPE CHANGED`,
`!MAP NOT EXISTING`.

**Host leaves or is lost.** The host's own leave sends 169 and shuts its transport down. On a client the
connection loss in the room ends the session (manager state 0 with the error latch;
`docs/sim/network-session.md` §3.9 [inferred there]); the room dialog then disappears. There is no host migration
in the room: it needs manager state 3 or 4. The game's row vanishes from every browser when the lobby pushes 169.

**Map missing on a joiner.** The check is the joiner's, on every GameInformation
(`docs/sim/network-session.md` §3.6): the map is looked up by GUID; without it the client kicks itself with
`!MAP NOT EXISTING`, because the room always sends `fetchMapFromHost = 0` (§2.6). The transfer branch
(`fetchMapFromHost` set and `mapFileType == 3`: request `SAdK\maps\<name>.s2m` and `.bmp` from the host) exists
but no room code path reaches it, and the picker offers no type 3 maps [known, S 00454ad0, S 0046aaa0,
S 0045a300].

---

## 4. Update order

### 4.0 The frame around the dialogs

`LobbyMenu::System::Update(handleInput)` S 0042a860 runs, per frame and in this order [known]:

1. `UpdateMessageBoxes` S 0042a6b0;
2. the current screen's `Update` (vtable `+0x20`); in the village that is `WorldScreen::Update`, which sets the
   room's and the browser's visibility (§3.1);
3. `UpdateDialogs` S 0042a1c0: for every dialog of the list `System +0x3ac` that is active (vtable `+0x44`):
   a dialog marked for closing (vtable `+0x80`, flag `+0xb40`) gets `OnLeave(0)` if it is shown, `Deactivate(0)`
   and is deleted; every other dialog gets `Update` (vtable `+0x20`). Visibility is not tested here: the room's
   `Update` runs while the dialog is hidden or minimised;
4. if `handleInput`: `DispatchButtonClicks` S 0042a020. While no message box is open (list `System +0x390`
   empty): the current screen's `HandleButtonClicks` (vtable `+0x24`), then that of every dialog that is active
   and shown (vtable `+0x1c`), in list order. While a message box is open, only the message boxes get the click
   pass.

A dialog is appended to the list by its `Open...` function after its `OnShow` returned. The setup dialog
creates its map picker inside `OnShow`, so among these three the list order is map picker, setup dialog,
browser [known, S 0042bc40, S 00455f20, S 004389d0].

### 4.1 `SetupGameDialog::Update` S 00457a00 (per frame, called for the dialog object whether visible or not)

1. Visible, host, and `hostedGameId` is none or pending → ensure the "connecting" message box exists, disable
   input, **return** (steps 2..8 do not run in that frame).
2. Close the "connecting" box if one is open.
3. Settings-change timer: `settingsCrc` ≠ last seen → remember it, timer = 3500; else if timer > 0: timer −=
   frame milliseconds (`Timer_GetFrameDeltaMs` S 0057b890), else timer = 0.
4. If visible: input enabled = no password dialog, no stake dialog, map picker absent or hidden, and
   `StartLoading` not received; `RefreshSettingsView`; `RefreshPlayerRows(0)` (which also sets the Ready button).
5. Hand-over test (§3.6). There is no once-only latch: both calls repeat in every frame in which the test
   holds.
6. Wager test: own player ready (`IsLocalPlayerReady` S 00413470), a local avatar exists and gold < wager →
   send PlayerReady(0).
7. Start condition (§3.6).
8. Host-only enables of the settings widgets and `RankedGame` (§3.4).

Steps 3 and 5..8 run also while the dialog is hidden or minimised [known: only steps 1 and 4 are inside a
visibility test]. A host whose create is still pending therefore passes the gate of step 1 while the room is
minimised.

The dialog's `SetVisible` (vtable `+0x2c`) is overridden (S 00452dd0): hiding the dialog closes the
"connecting" box and clears `+0xbb8`; showing it calls the dialog's relayout [known].

### 4.2 `SetupGameDialog::HandleButtonClicks` S 00457f00 (per frame input pass)

Base dialog handling (`DialogBase::HandleButtonClicks` S 004608d0: returns false at once when the dialog is not
visible; close button → the cancel hook, §3.7) → `MinimizeButton` → settings clicks (§3.4, in the order:
the four drop-downs `StartResources`, `WinCondition`, `FogOfWar`, `RankedGame`, then `SelectMapButton`,
`BetGame`, `PrivateGame`) → `ReadyButton` → `LeaveButton`. The first click found ends the pass [known]. Row
edits arrive through the widgets' own callbacks (§3.5), not through this function.

Because the pass is not dispatched while a message box is open (§4.0), no button of the room, `LeaveButton`
included, reacts while the "connecting" box of step 1 is shown [inferred from S 0042a020 and S 00457a00].

### 4.3 Events

| Event | Reaction |
|---|---|
| dialog created (`OnShow` S 00455f20, called once by `OpenSetupGameDialog` S 0042bc40) | create the map picker hidden, subscribe to its "closed" and "map chosen" lists, load the layout |
| dialog closed (`OnLeave` S 00455e70, called by `UpdateDialogs` before the object is deleted) | unsubscribe, close the picker, release the preview texture and clear `previewMapName` |
| widgets built (`BuildWidgets` S 00456c70, vftable slot 1) | bind the widgets of §2.1, then bind the six rows once (`BindPlayerRowWidgets` S 00456790, latched by `+0xbb4`) |
| vftable slot 24 (`+0x60`, S 00455e60) | jumps to `UnbindPlayerRowWidgets` S 00455800: removes the row callbacks and clears `+0xbb4`. [TODO] not established: who calls slot 24 (read the callers of `DialogBase` vtable `+0x60`) |
| lobby message 170 / 169 | server list changes → browser rows (§3.2) |
| lobby message 153 for the create | §3.3 |
| NComm events | change the session; the dialogs pick the result up in the next frame |
| NComm kick text (0x30010) | `NComm_Manager::NotifyObservers_Slot2` S 0040e370 → observer list manager `+0x3d4` → `WorldScreen` message face slot 2 (vftable S 007d6e98, `+8`) = `ChatSink_ShowError` S 004330c0: message box `!ERROR` with the text `<!You were kicked!> - <reason>` [known, S 0040e560 case 0x30010, S 004389d0] |
| NComm notification texts (player joined / left) | `SendUINotification` S 0040e3d0 → list `+0x3ec` → face slot 0 = `MessageCallbacks_AddChatText` S 00431ba0: a chat line [known] |

### 4.4 Order of a hosted match, end to end

```
Create            -> NComm role 4, state 2; session seeded; 168 sent; room visible with "connecting" box
153 (id)          -> gameId set; GameInformation broadcast; 177 sent after every broadcast
joiner: Join      -> NComm role 3; 0x30001 to the host; host checks version, checksum, password, free slot
host              -> slot assigned; GameInformation to all; 177 (new name list, counts)
edits             -> 0x30002 (client) or direct (host); GameInformation; 177
Ready             -> 0x30011(1); GameInformation
all conditions    -> host: 0x30012 StartLoading
every peer        -> 169 (host), leave village, referee login, 0xDB6, 0xDB8, SetupSession, game screen
```

The host's join checks run in the order build version (`!VERSION MISMATCH`), build checksum
(`!CHECKSUM MISMATCH`), password (`!PASSWORD_MISMATCH`), slot assignment [known, S 0040e560 case 0x30001].
"Leave village" is `Lobby::CLobby::RequestExitVillage` S 004f5090 (`CLobby` vtable `+0x84`): when the lobby's
mode (`CLobby +0x270`) is 2 it requests mode 0 through its own vtable `+0x2c` (a request is latched only while
none is pending, S 004f4eb0); otherwise, when the lobby client object exists, it calls
`CLobbyClient::LeaveVillage`; otherwise it does nothing [known]. `SetupGameDialog::Update` calls it, and
`DestroyGameServer` before it, in every frame in which `StartLoading` is set and the `LobbyComm::System` state is
9: the host sends one more 169 per such frame as long as `hostedGameId` is still a real id (`DestroyGameServer`
S 004683e0 does not change the id itself) [known]. "Game screen" is the same `CLobby` vtable `+0x2c` with
argument 1, called by `OnRefereeRegisterGameResult` S 00431800 after `SetupSession` [known].

---

## 5. Inputs and outputs

### 5.1 Lobby server (TinCat lobby connection) — `docs/message-catalog.md`, "Server list (lobby connection)"

| Id | Name | Direction | Sent / handled by |
|---|---|---|---|
| 168 | AddGameServer | C→S | `ServerList::CreateGameServer` S 0046aaa0 → TinCat `GameServerManager` vtable `+0x20` (T 10020ca0) |
| 153 | AddResult (answer to 168) | S→C | `ServerList::CreateResultReceived` S 0046a6a0 |
| 177 | ChangeGameServer | C→S | `ServerList::UpdateGameServer` S 0046aff0 → vtable `+0x24` (T 10021040) |
| 169 | RemoveServer | C→S | `DestroyGameServer` S 004683e0 (match start), `DestroyGameServerAndShutdown` S 00468410 (leave, role 4 only) → vtable `+0x28` (T 10021350) |
| 169 | RemoveServer (push, ticket 0) | S→C | `ServerList::RemoveServer` S 0046a5e0 |
| 170 | GameServerData | S→C | `ServerList::AddOrUpdateDescriptor` S 0046a440 → `GameServerInfo::UpdateFromDescriptor` S 0048da70 |

The list subscription itself (171 / 172) belongs to the lobby login (`docs/message-catalog.md`).

### 5.2 Peer to peer (NComm) — `docs/sim/network-session.md` §3.5, §3.6

| Id | Name | Sent from here by |
|---|---|---|
| 0x30001 | NE_UserInformation | `JoinGame` / `JoinGameWithPassword` / `CreateGameServer` → `ConnectAndJoin` S 0040ad60 (host and joiner alike) |
| 0x30002 | NE_PlayerInformation | client row edits (§3.5): `SendEventPlayerInformation` S 00408c70 |
| 0x30003 | NE_GameInformation | host, through `BroadcastGameInfo` S 004090e0: every accepted `SetSlotSetup`, every `SetGameSettings`, `SetWager` and `SetGameIdAndBroadcast`; `SetSlotAiLevel` and `SetGamePassword` only when the value changed; also after an applied 0x30002 or 0x30011 (S 0040e560) |
| 0x30010 | NE_System_UserShouldKickHimself | host: slot type change (`!SLOT TYPE CHANGED`), smaller map (`!GAME FULL`) |
| 0x30011 | NE_PlayerReady | Ready click (1), wager test (0) |
| 0x30012 | NE_StartLoading | host: start condition |
| 0x30006 | NE_Chat_ToAll | chat channel 4 (SETTLERS) while a session exists: `WorldScreen::SendChatInput` S 00436860 → `SendChatToAll` |

### 5.3 Referee — `docs/MATCH_START.md`

`RegisterGame 0xDB6` carries the room values listed in §3.6; `RegisterGameResult 0xDB8` triggers `SetupSession`.

### 5.4 Other subsystems

- **Lobby avatar**: gold (`+0xd0`) for the wager rules, name and tribe for the host's slot and game name.
- **Map files**: `GameFile_LoadMapInfo` S 005aaa30 (name, GUID, start positions, size, type),
  `GameFile_FindMapByGuidAnyType` at match start (`docs/map-format.md` §1.3).
- **Lobby 3D renderer**: the six row portraits, `Lobby::CLobby::RenderAvatarSnapshotGrid` S 004f82a0 (`CLobby`
  vtable `+0xcc`; arguments: six actor pointers, the preview mode, a vector of the six playerIndex values)
  [known]. It draws the actors into a 3 × 2 grid of one render target (cell edge = target size / 3; cell of
  row *i*: column *i* mod 3, line *i* / 3; a slot without actor gets its cell cleared) and returns that target's
  texture, which every row's `PlayerPreview` then shows. While the graphics device is in state 1 it only tries
  to restore the device and returns 0.
- **Avatar files**: with preview mode 1 (only from `SetupSession`) each drawn actor is also written by
  `CGfxObjAvatar::SaveAvatarFile(name, user = true)` S 00506a40, name = `slot_<playerIndex>` (format `slot_%d`):
  the file `<My Documents>\SAdK\users\slot_<playerIndex>.avo` [known, S 004f82a0, S 004f7fd0 (call at
  S 004f819e), S 00506a40]. [TODO] not established: the reader of these files in the match; settle by the
  references to the string `%s\%s.avo` and to `slot_`.
- **Game start**: the `GameLoadDescriptor` (`nMenu::System` → game → `gameSetupInfo`) written by
  `SetupSession`.
- **Offline free game** shares, and only shares: the row names `PlayerOne`..`PlayerSix` (the room's table
  S 0087a720 is read by the room only; `nMenu::FreeGamePanel::BindWidgets` S 005e8820 has its own table), the
  team icon template names, `MapPreview_PlaceStartMarkers` S 005e7cc0 (third caller: `FreeGamePanel::SetMap`
  S 005e8410), and the session setters in role 0: `NComm_Manager::SetSlotSetup` (callers
  `nMenu::FreeGamePanel::StartFreeGame` S 005e7350 and `nMenu::System::StartPendingMap` S 005d9fd0) and
  `SetGameSettings` (caller `StartPendingMap` only) [known, caller lists]. The preview loader of the room
  (`UpdateMapPreviewImage`) has a twin in the panel (S 005e7220).

---

## 6. Data-driven parameters

| File (install, encrypted) | Keys | Feeds | Example values |
|---|---|---|---|
| `data\lobby\ui\layout\lobbySetupGameDialog.xml` | templates `PlayerSetupTemplate`, `MatchmakingCombobox`; elements `PlayerOne`..`PlayerSix`, `GameSettingsPanel`, `MapPreview` with `start0`..`start7`, `StartResources`, `WinCondition`, `FogOfWar`, `RankedGame` (`string0..n` = the drop-down entries in value order), `MinimizeButton` (`hotkey="m"`), `LeaveButton` (`hotkey="27"`), `ReadyButton` | the room | `WinCondition string0="!LOBBY_MATCHMAKING_WINCONDITION_DESTROYALLENEMIES"`; `RankedGame string0="!No" string1="!Yes"`; title `!LOBBY_SETUP_GAME_DIALOG` |
| `data\lobby\ui\layout\lobbyBrowseGameDialog.xml` | `GameList` with row template `item` (`Protected`, `RankedGame`, `GameName`, `PlayerCount`, `MapName`, `GameType`), `PlayerList`, `GameSettings`, `CloseButton`, `JoinButton`, `CreateButton` | the browser | row size `560 20`; `CloseButton hotkey="27"`, `JoinButton hotkey="13"`, `CreateButton hotkey="c"` |
| `data\lobby\ui\layout\lobbySelectMapDialog.xml` | `MapList`, `OkayButton`, `AbortButton` | the map picker | |
| `data\lobby\ui\layout\lobbySetStackDialog.xml`, `lobbySetPasswordDialog.xml`, `lobbyGetPasswordDialog.xml` | | wager input, the host's password input, the joiner's password input | |
| `data\game\maps\Freegamemaps\MP_*.s2m` | file name contains `MP_` | maps that can be hosted | 15 maps: `MP_2P_fata_morgana`, `MP_4P_icicles`, `MP_6P_ship_ahoi`, ... (6 for two, 6 for four, 3 for six players) |
| map preview pictures | `<map name>.bmp` next to the map | `MapPreview` | `docs/sim/formats-inventory.md` |
| `data\game\settings\network.ini` | `gamePort` | the port announced in 168 and listened on | `gamePort = 5478` in the examined install; `docs/sim/network-session.md` §6 |
| `data\game\language\de\lobby_ui.txt`, `ui.txt` (one `key<TAB>text` per line) | the `!...` keys named in §3 | all texts | `lobby_ui.txt`: `!LOBBY_SLOT_OPEN` = `Frei`, `!LOBBY_PLAYER_READY` = `BEREIT`, `!LOBBY_GAME` = `will spielen`, `!DUMMY_PASSWORD_STARS` = `******`, `!EMPTY_STRING` = one space; `ui.txt`: `!CPU Medium` = `KI (mittel)`, `!PLEASE WAIT`, `!Connecting to Game Server`, `!You were kicked!`, `!GAME FULL`, `!SLOT TYPE CHANGED` |

Constants in the code [known]: 3500 ms settings-change blink window (S 00457b32); blink period 1000 ms, 500 ms
on (S 00435980); initial host settings low resources / destroy all enemies / fog enabled (S 0046aaa0); stake
dialog minimum 0, initial value 1 (S 00457d50); 8 colours (S 0040bcd0, S 00413670); 6 rows; AI defaults
tribe = slot mod 3, team = colour = start = slot (S 00453030); "connecting" message box type 5 (S 00457aa2);
message box type 1 for `!COULD_NOT_CREATE_GAME` (S 00458520).

With the texts above, the `PrivateGame` button of §3.4 reads `******` when the session digest is zero and a
blank otherwise, i.e. the stars appear exactly when no password is known to the viewer [known for the texts and
the branch; that the two cases are swapped by mistake is inferred].

---

## 7. Save and load

No setting of the room is persisted [known: the functions of §11 read maps, previews and layouts and write no
file themselves]:

- the last map, settings, password and wager are not remembered; every Create starts from the defaults of §3.3;
- the dialogs' positions come from the layout and `SetAnchoredPosition(1, 1)` at creation;
- the password exists only as an MD5 in the host's session and as clear text on the host's button widget.

The one file output on this path is made by the lobby renderer at the match start: `SetupSession` →
`RefreshPlayerRows(1)` writes one avatar file `<My Documents>\SAdK\users\slot_<playerIndex>.avo` per human or
AI slot (§5.4) [known]. The same names are used at every match start, so a later match replaces them
[inferred: the open mode of the writer was not read].

Gold is the lobby character's (server side, `docs/village-and-character-protocol.md`); the room only reads it.
A network match itself cannot be saved (`docs/multiplayer-save.md`).

---

## 8. Determinism notes

The dialogs are front end only: they run per frame on wall time, outside the logic tick, and touch no simulation
object. What crosses into the simulation is the `GameLoadDescriptor` filled by `SetupSession` from the session
description, which is identical on all peers because it is the host's `StartLoading` payload
(`docs/sim/network-session.md` §3.8). Three points matter for equal matches:

- **Controller values differ per peer on purpose** (2 for the local human, 3 for the others); the map name is
  each peer's local name for the GUID; everything else `SetupSession` writes comes from the session
  [known, S 004562d0].
- **Random start positions and teams** are drawn once, by the host, with the C runtime generator seeded by
  `srand(time(0))`, on the copy of the session that `StartLoading` carries; the clients receive the result
  (`AssignRandomPlayerIndicesAndTeams` S 00413930, called by `BroadcastStartLoading` S 0040fe50) [known]. The
  draw walks the slots below maxPlayers in slot order, whatever their kind: playerIndex -1 becomes
  `free[rand() % freeCount]`, then team -1 becomes `rand() % maxPlayers`. A reimplementation must not draw
  them per peer.
- **The map is matched by GUID, not by name**, and a missing or differently named local map only logs
  (`SetupSession` step 2). Two peers with different files carrying the same GUID would load different worlds;
  the build checksum of the join handshake is the only guard (`docs/sim/network-session.md` §3.5) [inferred].

The row previews, blink timers and enable states have no effect on the match.

---

## 9. Notes for a Godot reimplementation

- **Model first.** Keep one session description object (the NComm one) and make the room a pure view of it,
  refreshed per frame or on a "session changed" signal. All rules of §3.4–§3.6 are functions of
  (session, local identity, is-host, gold); none needs dialog state except the three sub-dialog pointers and
  `minimized`.
- **Authority.** The host is the only writer. A client's edit is a request (0x30002, 0x30011) whose result
  comes back in the next GameInformation; do not apply it locally first. The gates of `ApplySlotSettings` are
  client-side only: the host's 0x30002 handler trusts the sender's GUID, so a remake that wants to stay
  compatible must accept exactly that event and should not rely on the UI gates for security.
- **Reproduce exactly** (peers of the original client depend on it): the description string of §2.4 including
  the 6-token minimum; the 168 / 177 field use (`max_spectators` = humans, `ai_players` = AIs, `max_players` =
  slots not closed); the colour collision rule of §3.5; the ready-reset rules; the start condition of §3.6
  including "open slot blocks" and "at least one human"; the kick-by-type-change; the MapSettings digit order
  win / resources / fog.
- **May be improved without breaking peers**: a browser filter and sort; showing the real password and ranked
  icons (the original shows the ranked flag on the lock icon and never updates the ranked icon); an un-ready
  button (send 0x30011 with 0); a visible reason when Join fails; the client-side password display.
- **Engine mapping.** Dialogs → `Control` scenes built from the converted layout XML or redesigned; drop-downs →
  `OptionButton` with item metadata = the value; row portraits → a `SubViewport` per row or one atlas; the map
  preview → `TextureRect` with marker children positioned by `x / width`, `(height - y - 1) / height`.
- **A converter has to provide**: the list of `MP_` maps with, per map, GUID, size, start positions and preview
  picture (the browser and the room need them before a map is loaded); the localisation keys; the three layout
  files if the original look is wanted.
- **A server has to provide**: the lobby side of 168 / 153 / 177 / 169 / 170 as in `docs/message-catalog.md`
  (echo the host's counts, description and ranked flag, derive `password_required`, push 169 on removal, supply
  the host's public address in 170), the referee messages of `docs/MATCH_START.md`, and the character's gold.
  The wager is only *checked* here; moving gold is the server's business.
- **Known defect not to copy**: `UpdateMapPreviewImage` releases the old preview texture before it knows that
  the new map has one, and does not reset the widget when the file is missing [known, S 00454fc0]; with a map
  without a preview file the widget keeps a destroyed texture (plate note of S 00454fc0, citing a crash dump
  of 2026-10-10).
- **Need not be copied**: the per-frame repetition of the hand-over calls (one 169 per frame until the lobby
  state changes, §4.4): send the removal once. The initial map of a new game depends on the directory order
  (§10 item 2): pick it from a sorted list. The `!ERROR` box for a kick and the unreachable Leave button
  under the "connecting" box (§4.2) are presentation only.
- **Avatar looks at the match start**: the original writes each player's look to a file at the match start
  (§5.4, §7); their reader is open (§10 item 6). A remake that needs the looks in the match can pass the same
  data (tribe, gender, level, eight colour nibbles per human slot; NPC index per AI slot, §3.5) in memory.

---

## 10. Open questions

1. Answered: a client sees no text when the host disappears from the room; the room dialog closes. The
   host's `Shutdown` S 0040b410 only stops its transport. On the client the connection event goes to the
   reconnector first, which elects a successor (the peer list always holds at least this client) and sets
   the reconnect state, so the user removal and its `!Player left game` notice are skipped (S 0041bcc0,
   S 0041b990, S 0041bb20). In the next frame `TinCatNetwork::Process` S 00419e10 fails because a reconnect
   needs manager state 3 or 4, and `Process_MainLoop` S 00410f70 shuts the transport down and sets state 0,
   with a log line only. `WorldScreen::Update` S 00435980 shows the setup dialog only while the state is 2,
   so the dialog is hidden and the settlers chat tab disabled [known]. The kick text goes to an `!ERROR`
   message box (§4.3).
2. [TODO] not established: which `MP_` map a new game starts with. The code does not sort: `FindFilesByPattern`
   S 006e4f00 → `FindFilesInDataPath` S 006e4c10 (game data root, then lobby data root) →
   `FindFilesInDirectory` S 006e4310, which appends the names in the order `FindFirstFileA` / `FindNextFileA`
   return them [known]. So the first map is the file system's first match ([inferred]: alphabetical on NTFS,
   `MP_2P_fata_morgana` in the shipped set). Settle: observe a fresh Create.
3. What the match does with an AI slot whose start position is ≥ maxPlayers after the
   host picked a smaller map. Nothing in the room corrects it [known]: `RefreshSettingsView` corrects only the
   local human's own index and only while the dialog is visible (§3.4); `RefreshSlots` S 0040b5a0 clears only
   the slots whose **slot index** is ≥ maxPlayers; `AssignRandomPlayerIndicesAndTeams` S 00413930 replaces only
   -1; `ArePlayerIndicesUnique` S 00413540 accepts any index 0..5; `SetupSession` writes the player under that
   index. Answered: the seat does not exist in the match. `SetupSession` S 004562d0 writes kind, tribe, colour,
   team, level and name into the setup slot of that index, and `Game_CreatePlayersFromDescriptor` S 005abb60
   creates and activates players only for the indices below the map's number of start positions
   (`players-victory.md` §3.4), so a seat with a higher index gets no player, no castle and no computer
   player [known]. The session slot itself stays as it was.
4. [TODO] not established: whether the lobby server of the original service moved the wager or only the
   referee did, and the pay-out rule for more than two players. Not in the client; the stub's rule is in
   `lobby/sadk_lobby/wagers.py`.
5. Answered: a client with gold < wager that joined through a stale browser entry (the browser's join test uses the
   listed wager) gets no message. Its Ready button is disabled on every frame (`gold >= wager` is one
   term of the enable rule, `UpdatePlayerRow` S 00454cf0), so it cannot become ready and the match cannot
   start; the `PlayerReady(0)` of the wager test is sent only while the own slot is ready (S 00457a00), i.e.
   only if the wager was raised after it had become ready [known].
6. [TODO] not established: who reads the `slot_<playerIndex>.avo` files written at the match start (§5.4), and
   what a start position of -1 would give as a name (the host replaces -1 before `StartLoading`, so every peer
   should see 0..5 there [inferred]). Settle: the references to the `.avo` path format in the game screens.
7. [TODO] not established: who calls the setup dialog's vftable slot 24 (unbinding of the row callbacks, §4.3).

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 0042bc40 / 0042bd10 / 0042bde0 | `LobbyMenu::System::OpenSetupGameDialog` / `OpenBrowseGameDialog` / `OpenSelectMapDialog` | allocate and register the dialogs |
| S 004549b0 | `SetupGameDialog::ctor` | layout name, field reset |
| S 00456c70 | `SetupGameDialog::BuildWidgets` | widget binding |
| S 00456790 / 00455800 | `BindPlayerRowWidgets` / `UnbindPlayerRowWidgets` | row callbacks; the second is reached through vftable slot 24 (S 00455e60) |
| S 00455f20 / 00455e70 | `SetupGameDialog::OnShow` / `OnLeave` | map picker lifetime, layout load, preview texture release |
| S 00452dd0 | `SetupGameDialog` `SetVisible` override (vftable `+0x2c`; Ghidra name `SetConnectingOverlayEnabled`) | hiding closes the "connecting" box |
| S 00457a00 | `SetupGameDialog::Update` | per frame: connecting gate, refresh, hand-over, wager test, start condition, enables |
| S 00457f00 | `SetupGameDialog::HandleButtonClicks` | minimise, ready, leave |
| S 00457d50 | `HandleSettingsClicks` | drop-downs, map, wager, password buttons |
| S 004573c0 | `RefreshSettingsView` | settings panel from the session |
| S 00454ad0 | `OnMapSelected` | host: apply map and settings |
| S 00454fc0 | `UpdateMapPreviewImage` | preview texture |
| S 00457900 | `OnWagerChosen` | stake dialog result |
| S 00452d00 | `OnPasswordInputClosed` | password dialog result |
| S 00455fd0 | `RefreshPlayerRows` | portraits, then all rows |
| S 00454cf0 | `UpdatePlayerRow` | one row; Ready button enable |
| S 00453a20 / 00453c80 / 00454400 / 00454560 | `UpdateRowReadyStatus` / `UpdateRowPlayerType` / `UpdateRowTribe` / `UpdateRowTeamColorHQ` | row parts |
| S 004550f0 / 004556c0 | `PopulatePlayerTypeMenu` / `PopulateTribeMenu` | drop-down contents |
| S 00453030 / 004530d0 | `OnPlayerTypeSelected` / `OnPlayerTribeSelected` | drop-down choices |
| S 00453290 / 00453460 / 00453630 | `OnCycleTeam` / `OnCycleStartPosition` / `OnCycleColor` | button cycles |
| S 00452e40 | `ApplySlotSettings` | who may change what; local or 0x30002 |
| S 004562d0 | `SetupGameDialog::SetupSession` | session → `GameLoadDescriptor` |
| S 00452d90 | dialog cancel hook (vftable slot 36, `+0x90`) | leave through the close button; returns false, so the dialog is not closed |
| S 00459cd0, 0045a390, 0045a300, 00459f40 | `SelectMapDialog::ctor`, `BuildWidgets`, `RefreshMapList`, `SelectMapDialog_AppendMapFiles` | map picker list |
| S 00459bb0, 00459e20, 00459ed0 | `SelectMapDialog::Update`, `HandleButtonClicks`, `ConfirmSelectedMap` | selection and confirm |
| S 00457ff0, 004580a0, 00459970, 00459a70 | `BrowseGameDialog::ctor`, `BuildWidgets`, `OnShow`, `OnLeave` | browser set-up, subscriptions |
| S 00458ac0 | `BrowseGameDialog::Update` | detail panel, Join enable |
| S 004588e0 | `BrowseGameDialog::HandleButtonClicks` | Close, Join, Create |
| S 004593c0, 004598b0, 00458300 | `FillGameRow`, `OnGameServerAddedOrUpdated`, `OnGameServerRemoved` | list rows |
| S 00457f90, 00458520, 00458600 | `OnCreateGameSucceeded`, `OnCreateGameFailed`, `OnJoinPasswordEntered` | create result, protected join |
| S 0048da70, 0048d810 | `GameServerInfo::UpdateFromDescriptor`, `ParseDescriptionData` | 170 → browser entry |
| S 0048d030, 0048d0c0 | `GameServerInfo::JoinGame`, `JoinGameWithPassword` | connect to the host |
| S 0046aaa0, 0046a6a0 | `ServerList::CreateGameServer`, `CreateResultReceived` | host registration |
| S 0046aff0, 0046a850 | `ServerList::UpdateGameServer`, `LobbyServerList_BuildGameDescription` | 177, description string |
| S 004683e0, 00468410 | `ServerList::DestroyGameServer`, `DestroyGameServerAndShutdown` | 169 at start, leave |
| S 0042a860, 0042a1c0, 0042a020, 004608d0 | `LobbyMenu::System::Update`, `UpdateDialogs`, `DispatchButtonClicks`, `DialogBase::HandleButtonClicks` | frame order, dialog update and click dispatch (§4.0) |
| S 004f5090, 004f4eb0, 004f82a0, 004f7fd0, 00506a40 | `Lobby::CLobby::RequestExitVillage`, mode request (vtable `+0x2c`), `RenderAvatarSnapshotGrid`, `RenderAvatarSnapshot`, `CGfxObjAvatar::SaveAvatarFile` | hand-over, row portraits, avatar files |
| S 0040e370, 0040e3d0, 004330c0, 00431ba0 | `NComm_Manager::NotifyObservers_Slot2`, `SendUINotification`, `WorldScreen::ChatSink_ShowError`, `MessageCallbacks_AddChatText` | kick text → `!ERROR` box, notifications → chat |
| S 006e4f00, 006e4c10, 006e4310 | `FileScanHolder::FindFilesByPattern`, `FindFilesInDataPath`, `FindFilesInDirectory` | map file listing, unsorted |
| S 0046a440, 0046a5e0 | `ServerList::AddOrUpdateDescriptor`, `RemoveServer` | list model |
| S 0040bcd0, 0040bf40 | `NComm_Manager::SetSlotSetup`, `SetSlotAiLevel` | host slot edits, kick on type change |
| S 0040bfd0, 0040c1b0, 0040c220, 0040c320 | `SetGameSettings`, `SetWager`, `SetGamePassword`, `SetGameIdAndBroadcast` | host setting edits |
| S 00408c70, 00408d80, 0040fe50 | `SendEventPlayerInformation`, `SendPlayerReadyEvent`, `BroadcastStartLoading` | 0x30002, 0x30011, 0x30012 |
| S 004090e0, 0040b5a0, 00413930, 0040ad60 | `BroadcastGameInfo`, `RefreshSlots`, `AssignRandomPlayerIndicesAndTeams`, `ConnectAndJoin` | 0x30003 (+ 177 in role 4), slot clean-up, random start positions and teams, 0x30001 |
| S 00413400, 00413540, 004135c0, 00414b50, 00413470 | `AreAllSlotsReady`, `ArePlayerIndicesUnique`, `AreColorsUnique`, `CountParties`, `IsLocalPlayerReady` | start predicates |
| S 00413110, 004131b0, 00413160, 004133c0 | `CountHumanSlots`, `CountAiSlots`, `CountClosedSlots`, `CountConnectedHumans` | counts |
| S 00413670, 00413720, 00414f50, 004145f0 | `FindFreeColor`, `FindSlotByColor`, `PlayerInfo::IsReady`, `GetSettingsDigitString` | helpers |
| S 004389d0, 00435980, 00437760, 00434230, 00433f60 | `WorldScreen::OnShow`, `Update`, `HandleButtonClicks`, `DispatchSlotAction`, `RefreshActionSlots` | dialog creation, visibility, entry points |
| S 00432240, 00431800 | `WorldScreen::OnRefereeLoginSuccess_RegisterGame`, `OnRefereeRegisterGameResult` | referee hand-over |
| S 00441650, 00441760, 00441560 | `SetStackDialog::ctor`, `Update`, `HandleButtonClicks` | wager input, clamp |
| S 0045dab0, 0045deb0 | `SetPasswordDialog::HandleButtonClicks`, `GetPasswordDialog::HandleButtonClicks` | password input results |
| S 005e7cc0, 004538b0 | `MapPreview_PlaceStartMarkers`, `NComm_GetNationIdForTribe` | shared helpers |
