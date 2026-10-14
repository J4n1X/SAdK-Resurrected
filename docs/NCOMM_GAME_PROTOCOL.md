# NComm game/room protocol — the pre-game room + in-game P2P layer

How SAdK synchronises the **pre-game room** (player slots: occupant / tribe / color / team / ready)
and drives the match. This is a **separate layer** from the lobby NETMSGs (`msgdefs.ini`) and from the
village/world `LobbyMessage` protocol — it is the engine's **NComm** ("network communication") event system.
All addresses are `sadk_noav.exe`, base `0x400000`.

> Evidence tags: `[PROVEN]` = address + decompiled evidence here (the pre-game room works live against the
> stub: host, join, slot / tribe / team / ready, match start); `[known]` = read at the address;
> `[INFERRED]` = behaviour-supported, not confirmed; `[TODO]` = open.

---

## Architecture

```
  NComm_Manager  (singleton g_NCommManager 0x00885754, 0x410 bytes)
    ├ +0x1c   eManagerState  (0 None · 1 NetworkStarted · 2 SessionStarted · 3 GameStarting · 4 GameRunning)
    ├ +0x28   connectedHumanCount   (CountConnectedHumans; set on 0x30005 / 0x3000f / 0x30012)
    ├ +0x2c   netTick               (the lockstep net tick)
    ├ +0x34   logicTicksPerNetTick  (= gameSpeedMultiplier +0x3c × netTickLength +0x38)
    ├ +0x340  networkHandler ► NComm::TinCatNetwork  (vtbl: 4=send · 8=disconnect · 0x10=connect/host ·
    │                       0x14=drop a peer · 0x30=localId · 0x40=playerId · 0x50=onPlayerJoined)
    ├ +0x3c8  nMode  (0 Offline · 1 LanClient · 2 LanHost · 3 InternetClient · 4 InternetHost;
    │                 chosen at StartUpNetwork; 0, 2 and 4 act as host)
    ├ +0x3cc  cStartLoading  (set to 1 by event 0x30012; the flag WorldScreen::Update polls)
    └ +0xdc   gameInformation ► embedded NComm::EventGameInformation (0x24f)
                ├ +0x10 + i*0x4c   slots[i]   (6 slots, NComm::PlayerInfo, below)
                └ +0x22f GameSeed (referee value, `SetGameSeed` S 004139f0; seeds only the chest contents
                  of a network match — see docs/MATCH_START.md)
```

The slot settings of event 0x30002 (tribe, team, colour, playerIndex) travel in the event itself
(`EventPlayerInformation +0x24 / +0x28 / +0x2c / +0x30`); the manager has no staging fields for them.

- The **game information** (Manager+0xdc) holds the 6-slot array and the GameSeed (`+0x22f`).
  `NComm::EventGameInformation::GetSlot@0x413100` `(i) = this + 0x10 + i*0x4c` `[PROVEN]`.
- **Transport `[PROVEN]`:** NComm P2P traffic rides **TinCat** (`tincat3.dll` — the *same* library as the
  lobby/village), via a **`NComm::TinCatNetwork`** object (`.\TinCatNetwork.cpp`, implements `ITinCatCallback`),
  created by `NComm_Manager::StartUpNetwork@0x40a9a0` and stored at `Manager+0x340`. The session is spun up when
  the `GameServerConnection` (`LM+0x544`) logs into the game server:
  `GameServerConnection::OnLoggedIn@0x48edf0` → `StartUpNetwork(mode 3)` → `NComm_Manager::ConnectAndJoin@0x40ad60`
  (sends the `0x30001` join). That is *why* `GameServerConnection`'s own `HandleMessage` (`vtbl[0x24]`) is the
  no-op stub — NComm events are consumed by the **NComm Manager** (`NComm_Manager::HandleEvent`), not the
  `LobbyComm::BaseConnection` dispatch path. (Host-authoritative: the host is the game server.) **The stub speaks
  TinCat, so it can sit in this path.**

---

## `NComm::PlayerInfo` — one player slot (0x4c = 76 bytes) `[PROVEN]`

The slot is the RTTI class `NComm::PlayerInfo` (vtbl S 007d4ee0, ctor S 00415230); the accessors below are
its methods. `ResetToOpen@0x4153d0` writes every field.

| Off | Type | Field | Accessor(s) | Note |
|----:|------|-------|-------------|------|
| `+0x04` | int8 | state | `GetState@0x414d30` | `0`=empty; `5`=active/ready-eligible (see `NComm_Manager::RefreshSlots`) |
| `+0x05` | u32 | playerId | `GetPlayerId@0x414d40`, `SetPlayerId@0x414de0` | NComm connection id; default `0xEFFFFFEE` (= "none") |
| `+0x09` | `NComm::NetGUID` (0x14) | ownerGuid `[known]` | `GetOwnerGuid@0x415200`, `SetOwnerGuid`; `NetGUID::Clear` S 00416350, `NetGUID::IsValid` (in `IsFilled` S 00414ed0) | embedded object: vftable pointer at `+0x09` (ctor S 00415230 stores `NComm::NetGUID::vftable` S 007d42b4), the 16 GUID bytes at `+0x0d`; the `"ownr"` identity. Serialized raw as 0x14 bytes **including the vftable pointer** (`Serialize` S 00415060, `Deserialize` S 00415130), so a receiver's pointer is overwritten with the sender's. `CopyFrom` S 00415460 copies only `+0x0d..+0x1c`. Whether a virtual call is made through the pointer after `Deserialize`: `[TODO]` |
| `+0x1d` | int8 | connectionType `[known]` | `SetConnectionType` S 00414e10 (one caller, S 0040e8de), `GetConnectionType` S 00414d50 | the player's self-declared connection type, 0..4 (labels of the 5-way switch in `nMenu::NetInfo::RefreshInfo` S 005fd96c `[TODO]`). Source: the joiner's `EventUserInformation` (0x30001) `+0x48` = `UserProfile_GetConnectionType` S 0041f220 (UserProfile `+0x94`), filled in `ConnectAndJoin` S 0040af35 (the host runs the same path for itself); the host copies it in the 0x30001 handler. `Init` S 00415500 first stores the literal 4 passed by `AssignSlotToJoiningUser` S 0040bb60; all setup/clear functions write 0. Readers: `NetInfo::RefreshInfo` and the 0x3000e handler (S 0040f9cb, back to the transport's `SetUserData`). Serialized |
| `+0x1e` | std::string | playerName | `GetPlayerName@0x415430` | |
| `+0x3a` | int8 | playerIndex | `Get/SetPlayerIndex@0x414d60/0x414e20` | default `0xFF` |
| `+0x3b` | int8 | **kind** | `GetKind@0x414d70` | `0`=empty · `1`=human · `2`=AI · `3`=closed |
| `+0x3c` | int8 | aiLevel | `GetAiLevel@0x414d80` | valid when kind==AI |
| `+0x3d` | int8 | **tribe** `[PROVEN]` | `Get/SetTribe@0x414da0/0x414e50` | `0`=Bavarian `1`=Scots `2`=Egyptian (`NComm_GetNationIdForTribe@0x4538b0`) → descriptor `+0x68`; default `0xFF` |
| `+0x3e` | int8 | **color** `[PROVEN]` | `Get/SetColor@0x414db0/0x414e60` | **unique** — 0x30002 swap-on-conflict loop → descriptor `+0x88`; default = slot index |
| `+0x3f` | int8 | **team** `[known]` | `Get/SetTeam@0x414dc0/0x414e70` | → descriptor `+0xa8` → `Player.team` (`+0x94`); `0xFF` (-1) = no team; a joined human starts with team = playerIndex (`Init` S 00415500), an AI slot with team = playerIndex (`SetupAi`), an open slot with team = slot index. Chain below |
| `+0x40` | int8 | readyState `[known]` | folded setter S 00552f10 (`*(this+0x40) = value`, shared with two unrelated LuaProps functions); `IsReady` S 00414f50, `IsLoaded` S 00414f90 | `0` not ready · `1` ready (pre-game room) · `2` loaded (map loaded, waiting for StartGame). Writers and readers below |
| `+0x41` | u16 | avatarTribeGenderLevel `[known]` | `SetAvatarTribeGenderLevel` S 00415000 (one caller S 0040bca7), `GetAvatarTribeGenderLevel` S 00414fc0 (one caller S 0045615c) | the joined user's lobby avatar look, `body<<8 \| gender<<4 \| level` (a host's slot read `0x0105` for body 1, gender 0, level 5 in the server's save `[live, 2026-10-12]`). `0xFFFF` = unset (AI, open, closed, cleared). Source: `EventUserInformation +0x50`, filled by the joiner from `NComm_GetLocalAvatarTribeGenderLevel` S 0041f260. Reader: `SetupGameDialog::RefreshPlayerRows` (avatar preview). Serialized |
| `+0x43` | u32 | avatarColors `[known]` | `SetAvatarColors` S 00415030 (one caller S 0040bcb3), `GetAvatarColors` S 00414ff0 (one caller S 00456168) | the joined user's avatar colours: eight 4-bit values, low nibble first (packed in `NComm_GetLocalAvatarColorsPacked` S 0041f2f0, unpacked at S 00456182..004561be), in the save's order hair, skin, shirt, trousers, addColor1..4 (a host's slot read `0x2E918519` for the colours `[9,1,5,8,1,9,14,2]` `[live, 2026-10-12]`). `-1` = unset. Source: `EventUserInformation +0x54`. Serialized |
| `+0x47` | u32 | avatarId `[known]` | `SetAvatarId` S 00415040 (one caller S 0040bcbf), `GetAvatarId` S 00415050 | lobby AvatarID of the human in the slot (= the perm id; a host's slot read 100000 `[live, 2026-10-12]`); `0` = none (the constant at S 007db510 is 0). Source: `EventUserInformation +0x58`, filled by the joiner from `NComm_GetLocalAvatarId` S 0041f3e0; the host stores it unchecked. Readers: `RegisterGame 0xDB6` AvatarID x6 (S 004322b0), `FinishGame 0xDC0` Winner (S 00535ac9), `ClaimChest 0xDAC` (S 00782ae1), chat observers (S 0040e46f, S 0040e520). Serialized |
| `+0x4b` | int8 | leftNoticeShown `[inferred]` | `SetLeftNoticeShown` S 00414e80; folded getter S 0046b5f0 (`return *(byte*)(this+0x4b)`) | local latch, **not serialized**: the "<name> left the game" notice is shown only while it is 0 and it is set to 1 right after (`HandlePlayerLeft` S 00410720, event 0x3000f at S 0040fb5b, `Reconnector_DropRemotePlayers` S 00410c0b / S 00410e40). ctor, `Clear`, `Init` write 0; `SetupAi`, `SetupClosed`, `ResetToOpen` write 1; `CopyFrom` copies it. On a non-host it is 0 for all six slots after every applied game information (`Deserialize` S 00415130 leaves the constructor's 0, `AssignGameData` S 00414290 copies it), so a later leave event for the same slot shows the notice again `[known]` |

The match-start reader `LobbyMenu::SetupGameDialog::SetupSession@0x4562d0` walks these 6 slots
into the `GameLoadDescriptor`. `PlayerInfo::ResetToOpen` is the per-slot clear.

> Labels confirmed 2026-06-13: **tribe (`+0x3d`)** `[PROVEN]` — `NComm_GetNationIdForTribe` maps `0/1/2` to the
> literal nation names *Bavarian / Scots / Egyptian* (the three playable tribes). **color (`+0x3e`)** `[PROVEN]`
> — the 0x30002 unique-swap loop.

**team (`+0x3f`)** `[known]`. `SetupGameDialog::SetupSession` S 004562d0 reads `GetTeam(slot)` (S 00456584) and
stores it in the load descriptor's per-player table `desc+0xa8`, keyed by playerIndex (colour `+0x3e` → `+0x88`,
nation of tribe `+0x3d` → `+0x68`, controller → `+0x48`, aiLevel → `+0xc8`). `Game_CreatePlayersFromDescriptor`
S 005abb60 passes the `+0xa8` value as the team argument of `PlayerTable::CreatePlayer` S 005be100 →
`Player::Init` S 005bea90, which stores `Player.team` (`+0x94`). `Player::IsEnemyOf` S 005be280 is true when the
indices differ and (the teams differ or team == -1); it decides the allies at match start
(`PlayerTable_RevealAllies` S 005bdf70) and winners / losers in `VictoryConditions::DeclareWinner` S 00535990.
Inside NComm the same byte filters the "chat to allied" event 0x30007 (`ArePlayersAllied` S 00413780), limits
`SendTeamChat` S 00409f60 to slots with an equal value, and is what `CountParties` S 00414b50 counts (each -1
counts as its own side).
- **-1 = no team:** such a player is everyone's enemy. It arises only through `Clear` or a 0x30002 that carries
  `0xff`. In a two-player room every seat was in a team by default and none was without one
  `[live, 2026-10-14]`. `AssignRandomPlayerIndicesAndTeams` S 00413930 (from `BroadcastStartLoading`, S 0040ff1d) replaces
  every -1 team below maxPlayers with `rand() % maxPlayers` and a missing playerIndex with a random free one. It
  works on the temporary 0x30012 event (a copy of the session); the host applies that event to its own session
  like every joiner (`BroadcastEvent` S 0040fd80 → `HandleEvent` case 0x30012 → `AssignGameData`), so its
  session holds the same values `[known]`. `rand()` is seeded with `time()` on the host.
- The team travels only in the peer-to-peer GameInformation payloads (0x30003 / 0x30012 / 0x30005); no lobby or
  referee message carries it.

**readyState (`+0x40`)** `[known]`. Direct writes: ctor / `Clear` / `Init` / `ResetToOpen` 0; `SetupAi`,
`SetupClosed` and `ResetToState` S 00414d10 (player dropped or removed) 2. Through the folded setter S 00552f10:
event 0x30002 → 0 after a tribe, team or colour change (not after a playerIndex change); 0x30011 PlayerReady → 1
when the value is non-zero and `EventGameInformation::ArePlayerIndicesUnique` S 00413540 holds, else 0; 0x30004
GameLoaded → 2 when the value is non-zero, else 0; `NComm_Manager::SetGameSettings` S 0040bfd0 and `SetWager`
(S 0040c1ee) → 0 on the human slots. Readers: `IsReady` (strict: == 1; otherwise a human needs 1 or 2, AI and
closed slots always pass, open slots never) for `AreAllSlotsReady`, `IsLocalPlayerReady` and the dialog's ready
column; `IsLoaded` (== 2 for humans; non-human slots pass when not open) only for `AreAllSlotsLoaded`
S 00413500, which gates the host's `BroadcastStartGame` in `nGame::System::Update` (S 00780d52).

---

## NComm event dispatcher — `NComm_Manager::HandleEvent@0x40e560` `[PROVEN]`

Called for each queued event from the NComm Manager main loop (`NComm_Manager::Process_MainLoop@0x410f70`).
It reads the event type via `event->vtbl[4]()` (the `NE_EventType` at event `+4`) and switches. Two id
spaces exist: **`0x2xxxx`** (game events, `GE_*`; lockstep game commands) and **`0x3000x`** (network events,
`NE_*`; the ones dispatched here). The names are those of the `NE_EventType` enum and of the event-name
table the game fills at S 00421bd0 `[known]`.

| Event id | Name | Behaviour `[PROVEN]` |
|---|---|---|
| `0x20023` | GE_Logic_SpeedUp | `gameSpeedMultiplier` (`Mgr+0x3c`) = `ev+0x10`; `logicTicksPerNetTick` (`Mgr+0x34`) = `netTickLength` × value. Returns false, so the event is also forwarded to the game listener (`Mgr+0x50`) |
| `0x30001` | **NE_UserInformation** (join request, host) | validate `NComm_GetBuildVersion` / `NComm_GetBuildChecksum` / the password MD5 → `NComm_Manager::KickPlayer("!VERSION MISMATCH" / "!CHECKSUM MISMATCH" / "!PASSWORD_MISMATCH")` on fail; else `AssignSlotToJoiningUser` S 0040bb60, `RefreshSlots`, `BroadcastGameInfo`, "!Player joined game". The event (`EventUserInformation`) carries the joiner's connection type `ev+0x48`, avatar look `ev+0x50`, avatar colours `ev+0x54` and AvatarID `ev+0x58`, copied to slot `+0x1d` / `+0x41` / `+0x43` / `+0x47` `[known]` (S 0040e8de, S 0040bca7..0040bcbf) |
| `0x30002` | **NE_PlayerInformation** (slot settings change) | the slot is found by the NetGUID at `ev+0x10`; apply the event's values to it: tribe `ev+0x24→slot+0x3d`, team `ev+0x28→slot+0x3f`, colour `ev+0x2c→slot+0x3e` (**unique-swap loop**; -1 = none), playerIndex `ev+0x30→slot+0x3a`; a tribe, team or colour change → readyState 0 (S 00552f10); on the host `RefreshSlots` + `BroadcastGameInfo` |
| `0x30003` | **NE_GameInformation** (host session broadcast) | `AssignGameData` (copies the host's payload, GameSeed `+0x22f` included); reconcile the two slot arrays (detect join/leave by ownerGuid/name diff → UI notify); map lookup by GUID (`GameFile_FindMapByGuidAnyType`). Map missing `[known]` (S 0040eea1..0040f30d): session `+0x228` clear → local `0x30010` "!MAP NOT EXISTING" (self-kick); `+0x228` set and `+0x229` == 3 → `RequestFileFromHost` S 004084d0 for `<My Documents>\SAdK\maps\<mapName>.s2m` and `.bmp`; `+0x228` set and `+0x229` != 3 → self-kick. No caller in this build sets `+0x228` (see `docs/types.md` §2.2) |
| `0x30004` | **NE_GameLoaded** `[known]` | slot[`ev->playerId`] readyState = 2 when `ev+0x10` is non-zero, else 0 (S 00552f10); if host → `RefreshSlots` + `BroadcastGameInfo`. Sent by `SendGameLoadedEvent` S 00408e50 (from the game's `OnEnter` S 005eef8f and `ReconnectAndRejoin` S 0040952c) |
| `0x30005` | **NE_StartGame** | `SendEventUserChecksum(0)`; `AssignGameData(session, ev)` `[known]` (S 0040e560 case 0x30005; the host broadcasts it only when `AreAllSlotsLoaded`, S 00780d52); `connectedHumanCount` (`Mgr+0x28`) = `CountConnectedHumans`; the game listener's vtbl `+8` starts the game |
| `0x30006` / `0x30007` | chat to all / chat to allied (`EventText`) `[known]` | `OnChatToAll` S 0040e400 / `OnChatToAllied` S 0040e4b0 (sender slot `ev+0xc`, text `ev+0x10`); 0x30007 is ignored unless sender and local player are allied |
| `0x30008` | user list text (`EventText`) `[known]` | `userListText` (`Mgr+0x344`) = the event's string |
| `0x30009` | **NE_UserChecksum** `[known]` | with a non-empty NetGUID: `ChecksumLog::Add` S 00416030 (`Mgr+0xc4`, tick `ev+0x10`, guid, netId, checksum `ev+0x14`) |
| `0x3000a` | **NE_UserLeave** | in a running game: queue an `EventUserLeft` (0x3000b) into the tick package; in the room: reset the slot, `RefreshSlots` + `BroadcastGameInfo`, send 0x3000b, "!Player left game" |
| `0x3000b` | user left (`EventUserLeft`) `[known]` | non-host: `HandlePlayerLeft` S 00410720 (guid, netId, playerIndex); host: `Event1Integer` 0x2002b (GE_PlayerLeftGame) with the player index, dispatched locally in mode 0 and queued into the tick package otherwise |
| `0x3000c` | NE_InGame_PlayerRemoveLogicData `[known]` name | consumed with no action in this switch |
| `0x3000d` | NE_InGame_ChangeNetTickLength `[known]` name | `netTickLength` (`Mgr+0x38`) = `ev+0x10`; `logicTicksPerNetTick` (`Mgr+0x34`) = `gameSpeedMultiplier` × value |
| `0x3000e` | **NE_UserReJoinGame** | the game id at `ev+0x24` must equal `Mgr+0x2c` and a slot with the NetGUID must exist, else kick `"!COULD NOT RECONNECT"`; then slot playerId = netId (`PlayerInfo::SetPlayerId` S 00414de0), slot state = 1 (S 00414dd0) |
| `0x3000f` | NE_PreGame_HostReconnectRestartAndSendGameInformation `[known]` name | marks the human slots that are no longer filled as left ("!Player left game", slot `+0x4b` = 1), replaces the session by the event's game information, resets the reconnect fields (`Mgr+0x00..+0x18`) |
| `0x30010` | kick (`EventKickUser`) | "!You were kicked!" + the reason text (`ev+0x10`); in a running game `SendEventUserLeave`, otherwise disconnect and `Shutdown` |
| `0x30011` | **NE_PlayerReady** | readyState = 1 when `ev+0x10` is non-zero **and** `EventGameInformation::ArePlayerIndicesUnique` S 00413540 holds, else 0 `[known]` (this is a playerIndex uniqueness test, not a password check); if host → `RefreshSlots` + `BroadcastGameInfo`. Sent by `SendPlayerReadyEvent` S 00408d80 (0/1) |
| `0x30012` | **NE_StartLoading** | `AssignGameData`; `connectedHumanCount` = `CountConnectedHumans`; set `cStartLoading` (`Mgr+0x3cc`) = 1 (the flag the `LobbyMenu::WorldScreen` referee-login pump reads — see `docs/MATCH_START.md`) |

### Supporting NComm functions

`NComm_Manager::BroadcastGameInfo@0x4090e0` (host pushes room state), `NComm_Manager::RefreshSlots@0x40b5a0`
(per-slot ready/AI fill, kicks "!GAME FULL"), `NComm_Manager::KickPlayer@0x40b470`,
`NComm_Manager::AssignSlotToJoiningUser@0x40bb60`,
`NComm::EventGameInformation::ArePlayerIndicesUnique@0x413540` (see 0x30011),
`NComm::EventGameInformation::FindSlotByGuid@0x413300` (match by 16-byte ownerGuid, caps at 6),
`NComm_Manager::IsLeftPlayerGuid@0x409cc0`,
`NComm::EventGameInformation::GetMapFileType@0x413010` (the map type, see 0x30003),
`NComm_Manager::IsHost@0x408410`, `NComm_Manager::IsInGame@0x408440`, `NComm_Manager::IsClient@0x4083b0`,
the folded setter S 00552f10 (`byte +0x40`; on a slot it writes readyState),
`NComm::EventGameInformation::CountConnectedHumans@0x4133c0`,
`NComm::EventGameInformation::AssignGameData@0x414290`, `NComm_GetBuildVersion` / `NComm_GetBuildChecksum`
`@0x41f230/0x41f240`.

---

## How the room actually fills (the host↔client flow) `[PROVEN behaviour]`

1. **Join.** A client requests to join → host gets `0x30001`: it checks build version + checksum + password +
   static-data MD5 (kicks on any mismatch), assigns the player a slot, then **`BroadcastGameInfo`** pushes the
   whole room state to everyone.
2. **Configure.** A player changes tribe/color/team/position → `0x30002` applies it to their slot (colour is
   kept unique via the swap loop) → host re-broadcasts.
3. **Ready.** `0x30011` toggles a player's ready state → host re-broadcasts; `NComm_Manager::RefreshSlots`
   reflects it and fills empty slots / kicks overflow ("!GAME FULL").
4. **Clients apply** every host broadcast (`0x30003`, `AssignGameData`).
5. **Start.** Host issues `0x30012` (StartLoading) → sets `Mgr+0x3cc=1` → `LobbyMenu::WorldScreen` arms the
   referee login and the match-start sequence runs (`docs/MATCH_START.md`).

---

## Open `[TODO]`

- The five connection-type labels. (The nibble order of slot `+0x41` and the body part of each `+0x43` nibble are
  answered in the slot table `[live, 2026-10-12]`.)
- **Host vs P2P topology:** is `NComm::TinCatNetwork` a star (clients→host) or routed via a server? Read the
  connect/listen path (`StartUpNetwork` mode switch; `TinCatNetwork` vtbl `0x10`/`0x40`).
- The consumer of `0x3000c` (NE_InGame_PlayerRemoveLogicData): this switch only swallows it.
- The other `0x2xxxx` game events are not listed here (`0x20023` handled, `0x2002b` sent).
