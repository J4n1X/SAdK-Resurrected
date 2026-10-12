# NComm game/room protocol — the pre-game room + in-game P2P layer

How SAdK synchronises the **pre-game room** (player slots: occupant / tribe / color / team / ready)
and drives the match. This is a **separate layer** from the lobby NETMSGs (`msgdefs.ini`) and from the
village/world `LobbyMessage` protocol — it is the engine's **NComm** ("network communication") event system.
All addresses are `sadk_noav.exe`, base `0x400000`, verified live via the Ghidra MCP (2026-06-13).

> Evidence tags: `[PROVEN]` = address + decompiled evidence here; `[INFERRED]` = behaviour-supported guess,
> not yet confirmed; `[TODO]` = open.

---

## Architecture

```
  NComm Manager  (singleton DAT_00885754)
    ├ +0x1c   m_ManagerState  (0 None · 1 NetworkStarted · 2 Connected/InGame)
    ├ +0x24   pending tribe      ─┐ inbound slot-config staging (applied in event 0x30002):
    ├ +0x28   pending team        │   +0x24→slot tribe · +0x28→team · +0x2c→color · +0x30→index
    ├ +0x2c   pending color       │
    ├ +0x30   pending playerIndex ─┘
    ├ +0x340  pTransport ► NComm::TinCatNetwork  (vtbl: 4=send · 8=disconnect · 0x10=connect/host ·
    │                       0x14=kick · 0x30=localId · 0x40=playerId · 0x50=onPlayerJoined)
    ├ +0x3c8  session mode (0=local · 1-4 = host/client variants; chosen at StartUpNetwork)
    ├ +0x3cc  bStartLoadingFired  (set 1 by event 0x30012 — the flag LobbyGameScreen_Update polls)
    └ +0xdc   ► embedded GAME OBJECT
                ├ +0x10 + i*0x4c   slot[i]   (6 slots — NCommGameSlot below)
                └ +0x22f GameSeed (referee value, `SetGameSeed` S 004139f0; seeds only the chest contents
                  of a network match — see docs/MATCH_START.md)
```

- The **game object** (Manager+0xdc) holds the 6-slot array and the GameSeed (`+0x22f`). `NComm_GetSlotDataPtr(gameObj, i)
  = gameObj + 0x10 + i*0x4c` `@0x413100` `[PROVEN]`. In `Manager_HandleNCommEvent` the game object is reached
  as `pManager + 0xdc` (written `in_ECX + 0x37` in DWORD units).
- **Transport `[PROVEN]`:** NComm P2P traffic rides **TinCat** (`tincat3.dll` — the *same* library as the
  lobby/village), via a **`NComm::TinCatNetwork`** object (`.\TinCatNetwork.cpp`, implements `ITinCatCallback`),
  created by `NComm_Manager_StartUpNetwork@0x40a9a0` and stored at `Manager+0x340`. The session is spun up when
  the `GameServerConnection` (`LM+0x544`) logs into the game server:
  `GameServerConnection::OnLoggedIn@0x48edf0` → `StartUpNetwork(mode 3)` → `NComm_Manager_ConnectAndJoin@0x40ad60`
  (sends the `0x30001` join). That is *why* `GameServerConnection`'s own `HandleMessage` (`vtbl[0x24]`) is the
  no-op stub — NComm events are consumed by the **NComm Manager** (`Manager_HandleNCommEvent`), not the
  `LobbyBaseConnection` dispatch path. (Host-authoritative: the host is the game server.) **The stub speaks
  TinCat, so it can sit in this path.**

---

## `NCommGameSlot` — one player slot (0x4c = 76 bytes) `[PROVEN]`

Recovered from `NComm_Slot_Reset@0x4153d0` (writes every field) + the typed accessors.

| Off | Type | Field | Accessor(s) | Note |
|----:|------|-------|-------------|------|
| `+0x04` | int8 | state | `NComm_Slot_GetState@0x414d30` | `0`=empty; `5`=active/ready-eligible (see `NComm_UpdateReadyUI`) |
| `+0x05` | u32 | playerId | `NComm_Slot_GetPlayerId@0x414d40` | NComm connection id; default `0xEFFFFFEE` (= "none") |
| `+0x09` | `NComm::NetGUID` (0x14) | ownerGuid `[known]` | `NComm_Slot_GetOwnerGuid@0x415200`, `SetOwnerGuid`; `NetGUID::Clear` S 00416350, `NetGUID::IsValid` (in `IsFilled` S 00414ed0) | embedded object: vftable pointer at `+0x09` (ctor S 00415230 stores `NComm::NetGUID::vftable` S 007d42b4), the 16 GUID bytes at `+0x0d`; the `"ownr"` identity. Serialized raw as 0x14 bytes **including the vftable pointer** (`Serialize` S 00415060, `Deserialize` S 00415130), so a receiver's pointer is overwritten with the sender's. `CopyFrom` S 00415460 copies only `+0x0d..+0x1c`. Whether a virtual call is made through the pointer after `Deserialize`: `[TODO]` |
| `+0x1d` | int8 | connectionType `[known]` | `SetConnectionType` S 00414e10 (one caller, S 0040e8de), `GetConnectionType` S 00414d50 | the player's self-declared connection type, 0..4 (labels of the 5-way switch in `nMenu::NetInfo::RefreshInfo` S 005fd96c `[TODO]`). Source: the joiner's `EventUserInformation` (0x30001) `+0x48` = `UserProfile_GetConnectionType` S 0041f220 (UserProfile `+0x94`), filled in `ConnectAndJoin` S 0040af35 (the host runs the same path for itself); the host copies it in the 0x30001 handler. `Init` S 00415500 first stores the literal 4 passed by `AssignSlotToJoiningUser` S 0040bb60; all setup/clear functions write 0. Readers: `NetInfo::RefreshInfo` and the 0x3000e handler (S 0040f9cb, back to the transport's `SetUserData`). Serialized |
| `+0x1e` | char[~0x1c] | playerName | `NComm_Slot_GetPlayerName@0x415430` | inline C-string |
| `+0x3a` | int8 | playerIndex | `NComm_Slot_Get/SetPlayerIndex@0x414d60/0x414e20` | default `0xFF` |
| `+0x3b` | int8 | **kind** | `NComm_Slot_GetKind@0x414d70` | `0`=empty · `1`=human · `2`=AI · `3`=closed |
| `+0x3c` | int8 | aiLevel | `NComm_Slot_GetAiLevel@0x414d80` | valid when kind==AI |
| `+0x3d` | int8 | **tribe** `[PROVEN]` | `NComm_Slot_Get/SetTribe@0x414da0/0x414e50` | `0`=Bavarian `1`=Scots `2`=Egyptian (`NComm_GetNationIdForTribe@0x4538b0`) → descriptor `+0x68`; default `0xFF` |
| `+0x3e` | int8 | **color** `[PROVEN]` | `NComm_Slot_Get/SetColor@0x414db0/0x414e60` | **unique** — 0x30002 swap-on-conflict loop → descriptor `+0x88`; default = slot index |
| `+0x3f` | int8 | **team** `[known]` | `NComm_Slot_Get/SetTeam@0x414dc0/0x414e70` | → descriptor `+0xa8` → `Player.team` (`+0x94`); `0xFF` (-1) = no team; a joined human starts with team = playerIndex (`Init` S 00415500), an AI slot with team = playerIndex (`SetupAi`), an open slot with team = slot index. Chain below |
| `+0x40` | int8 | readyState `[known]` | folded setter S 00552f10 (`*(this+0x40) = value`, shared with two unrelated LuaProps functions); `IsReady` S 00414f50, `IsReadyState2` S 00414f90 | `0` not ready · `1` ready (pre-game room) · `2` loaded (map loaded, waiting for StartGame). Writers and readers below |
| `+0x41` | u16 | avatarTribeGenderLevel `[known]` | `SetVersionNibbles` S 00415000 (misnamed; one caller S 0040bca7), `GetAvatarTribeGenderLevel` S 00414fc0 (one caller S 0045615c) | the joined user's lobby avatar look, three nibbles `a<<8 \| b<<4 \| c`; which nibble is tribe / gender / level (bits 8..11 / 4..7 / 0..3) is `[inferred]` from the getter's callees. `0xFFFF` = unset (AI, open, closed, cleared). Source: `EventUserInformation +0x50`, filled by the joiner from `NComm_GetLocalAvatarTribeGenderLevel` S 0041f260. Reader: `SetupGameDialog::RefreshPlayerRows` (avatar preview). Serialized |
| `+0x43` | u32 | avatarColors `[known]` | `SetField43` S 00415030 (one caller S 0040bcb3), `GetAvatarColors` S 00414ff0 (one caller S 00456168) | the joined user's avatar colours: eight 4-bit values, low nibble first (packed in `NComm_GetLocalAvatarColorsPacked` S 0041f2f0, unpacked at S 00456182..004561be); which nibble is which body part `[TODO]`. `-1` = unset. Source: `EventUserInformation +0x54`. Serialized |
| `+0x47` | u32 | avatarId `[known]` | `SetField47` S 00415040 (one caller S 0040bcbf), `GetField47` S 00415050 | lobby AvatarID of the human in the slot; `0` = none (the constant at S 007db510 is 0). Source: `EventUserInformation +0x58`, filled by the joiner from `NComm_GetLocalAvatarId` S 0041f3e0; the host stores it unchecked. Readers: `RegisterGame 0xDB6` AvatarID x6 (S 004322b0), `FinishGame 0xDC0` Winner (S 00535ac9), `ClaimChest 0xDAC` (S 00782ae1), chat observers (S 0040e46f, S 0040e520). Serialized |
| `+0x4b` | int8 | leftNoticeShown `[inferred]` | `SetField4B` S 00414e80; folded getter S 0046b5f0 (`return *(byte*)(this+0x4b)`) | local latch, **not serialized**: the "<name> left the game" notice is shown only while it is 0 and it is set to 1 right after (`HandlePlayerLeft` S 00410720, event 0x3000f at S 0040fb5b, `Reconnector_DropRemotePlayers` S 00410c0b / S 00410e40). ctor, `Clear`, `Init` write 0; `SetupAi`, `SetupClosed`, `ResetToOpen` write 1; `CopyFrom` copies it. On a non-host it is 0 for all six slots after every applied game information (`Deserialize` S 00415130 leaves the constructor's 0, `AssignGameData` S 00414290 copies it), so a later leave event for the same slot shows the notice again `[known]` |

The match-start reader `LobbyMenu_SetupGameDialog_SetupSession_FillMpDescriptor@0x4562d0` walks these 6 slots
into the `GameLoadDescriptor`. `NComm_Slot_Reset` is the per-slot clear (empty/closed).

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
  `0xff`. `AssignRandomPlayerIndicesAndTeams` S 00413930 (from `BroadcastStartLoading`, S 0040ff1d) replaces
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
column; `IsReadyState2` (== 2 for humans; non-human slots pass when not open) only for `AreAllSlotsLoaded`
S 00413500, which gates the host's `BroadcastStartGame` in `nGame::System::Update` (S 00780d52).

---

## NComm event dispatcher — `Manager_HandleNCommEvent@0x40e560` `[PROVEN]`

Called every frame from the NComm Manager main loop (`NComm_Manager_Process_MainLoop@0x410f70`). It reads the
event type via `event->vtbl[4]()` and switches. Two id spaces exist: **`0x2002x`** (NComm transport/session
events) and **`0x3000x`** (game/room events — the ones dispatched here). Behaviour below is from the decompiled
switch; the **names are `[INFERRED]` from behaviour** unless noted.

| Event id | Name `[INFERRED]` | Behaviour `[PROVEN]` |
|---|---|---|
| `0x20023` | NE_LoggedIn | sets tick timing fields |
| `0x30001` | **PlayerJoinRequest** (host) | validate `NComm_GetBuildVersion`/`GetBuildChecksum`/password/`ValidateStaticDataMD5` → `NComm_KickPlayer("!VERSION/CHECKSUM/PASSWORD MISMATCH")` on fail; else find/assign slot, `NComm_UpdateReadyUI`, `NComm_BroadcastGameInfo`, "!Player joined game". The event (`EventUserInformation`) carries the joiner's connection type `ev+0x48`, avatar look `ev+0x50`, avatar colours `ev+0x54` and AvatarID `ev+0x58`, copied to slot `+0x1d` / `+0x41` / `+0x43` / `+0x47` `[known]` (S 0040e8de, S 0040bca7..0040bcbf) |
| `0x30002` | **SlotConfigChange** | apply staged config to the player's slot: tribe `Mgr+0x24→slot+0x3d`, color `Mgr+0x2c→slot+0x3e` (**unique-swap loop**), team `Mgr+0x28→slot+0x3f`, playerIndex `Mgr+0x30→slot+0x3a` (in the event: tribe `ev+0x24`, team `ev+0x28`, colour `ev+0x2c`, playerIndex `ev+0x30`); a tribe, team or colour change → readyState 0 (S 00552f10) |
| `0x30003` | AllConnectedSync (GameInformation) | `AssignGameData` (copies the host's payload, GameSeed `+0x22f` included); reconcile the two slot arrays (detect join/leave by ownerGuid/name diff → UI notify); map lookup by GUID (`GameFile_FindMapByGuidAnyType`). Map missing `[known]` (S 0040eea1..0040f30d): session `+0x228` clear → local `0x30010` "!MAP NOT EXISTING" (self-kick); `+0x228` set and `+0x229` == 3 → `RequestFileFromHost` S 004084d0 for `<My Documents>\SAdK\maps\<mapName>.s2m` and `.bmp`; `+0x228` set and `+0x229` != 3 → self-kick. No caller in this build sets `+0x228` (see `docs/types.md` §2.2) |
| `0x30004` | **GameLoaded** `[known]` | slot[`ev->playerId`] readyState = 2 when `ev+0x10` is non-zero, else 0 (S 00552f10); if host → `UpdateReadyUI` + `BroadcastGameInfo`. Sent by `SendGameLoadedEvent` S 00408e50 (from the game's `OnEnter` S 005eef8f and `ReconnectAndRejoin` S 0040952c) |
| `0x30005` | TickSync (StartGame payload) | `AssignGameData(session, ev)` `[known]` (S 0040e560 case 0x30005; the host broadcasts it only when `AreAllSlotsLoaded`, S 00780d52); `NComm_ProcessEventTimestamp` + `NComm_GetCurrentTick` |
| `0x30006`/`0x30007` | HostMigration `[INFERRED]` | `FUN_0040e400`/`FUN_0040e4b0` |
| `0x30008` | (name copy) | copies a string into `Mgr+0x3d1`-region |
| `0x30009` | (relay) | `NComm_IsSlotEmpty` + `FUN_00416030` |
| `0x3000a` | **PlayerLeave** | vacate slot, `UpdateReadyUI` + `BroadcastGameInfo`, "!Player left game" |
| `0x3000b` | **GameInfoBroadcast** | non-host applies slot data (`FUN_00410720`); when host & all-ready → send `NComm::Event1Integer 0x2002b` |
| `0x3000d` | TickTiming | tick fields |
| `0x3000e` | **Reconnect** | match slot by name, restore owner (`FUN_00414de0`) + connected (`FUN_00414dd0`); `"!COULD NOT RECONNECT"` kick on fail |
| `0x3000f` | SessionTeardown | mark disconnected players left across the 6 slots; reset tick state |
| `0x30010` | **Kicked** | "!You were kicked!" UI; then leave/cleanup |
| `0x30011` | **PlayerReady** | readyState = 1 when `ev+0x10` is non-zero **and** `EventGameInformation::ArePlayerIndicesUnique` S 00413540 holds, else 0 `[known]` (this is a playerIndex uniqueness test, not a password check); if host → `UpdateReadyUI` + `BroadcastGameInfo`. Sent by `SendPlayerReadyEvent` S 00408d80 (0/1) |
| `0x30012` | **StartLoading** | `AssignGameData`; `ProcessEventTimestamp`; set `Mgr+0x3cc = 1` (the flag `LobbyGameScreen_Update` polls to arm the referee login — see `docs/MATCH_START.md`) |

### Supporting NComm functions (already named in the project)

`NComm_BroadcastGameInfo@0x4090e0` (host pushes room state), `NComm_UpdateReadyUI@0x40b5a0` (per-slot ready/AI
fill, kicks "!GAME FULL"), `NComm_KickPlayer@0x40b470`, `NComm_CheckPlayerPassword@0x413540` (= `ArePlayerIndicesUnique`, see 0x30011),
`NComm_FindPlayerSlotByNamePtr@0x413300` (match by 16-byte ownerGuid, caps at 6), `NComm_IsSlotEmpty@0x409cc0`,
`NComm_GetConnectedPlayerCount@0x413010` (= `EventGameInformation::GetByte229`, the map type, see 0x30003), `NComm_IsHost@0x408410`, `NComm_IsInGame@0x408440`,
`NComm_IsAllConnected@0x4083b0`, `NComm_SetPlayerConnectionState@0x552f10` (a folded generic `byte +0x40` setter; on a slot it writes readyState), `NComm_GetCurrentTick@0x4133c0`,
`NComm_ProcessEventTimestamp@0x414290`, `NComm_ValidateStaticDataMD5@0x40bb60`, `NComm_GetBuildVersion/Checksum@0x41f230/0x41f240`.

---

## How the room actually fills (the host↔client flow) `[PROVEN behaviour]`

1. **Join.** A client requests to join → host gets `0x30001`: it checks build version + checksum + password +
   static-data MD5 (kicks on any mismatch), assigns the player a slot, then **`BroadcastGameInfo`** pushes the
   whole room state to everyone.
2. **Configure.** A player changes tribe/color/team/position → `0x30002` applies it to their slot (colour is
   kept unique via the swap loop) → host re-broadcasts.
3. **Ready.** `0x30011` toggles a player's ready/connection state → host re-broadcasts; `NComm_UpdateReadyUI`
   reflects it and fills empty slots / kicks overflow ("!GAME FULL").
4. **Clients apply** every host broadcast via `0x3000b` (`FUN_00410720`); when host sees all-ready it emits the
   session event `0x2002b`.
5. **Start.** Host issues `0x30012` (StartLoading) → sets `Mgr+0x3cc=1` → `LobbyGameScreen` arms the referee
   login and the match-start sequence runs (`docs/MATCH_START.md`).

---

## Open `[TODO]`

- ~~Confirm tribe/team + transport~~ **DONE 2026-06-13** — tribe = Bavarian/Scots/Egyptian; transport =
  `NComm::TinCatNetwork` over TinCat at `Manager+0x340`. Team (`+0x3f`) and the slot tail fields
  `+0x40/+0x41/+0x43/+0x47/+0x4b` are in the slot table. Remaining there: the nibble order of `+0x41` and the
  body part of each `+0x43` nibble, the five connection-type labels.
- **Host vs P2P topology:** is `NComm::TinCatNetwork` a star (clients→host) or routed via a server? Read the
  connect/listen path (`StartUpNetwork` mode switch; `TinCatNetwork` vtbl `0x10`/`0x40`).
- **Formalize** `NCommGameSlot` and the NComm Manager / game-object as Ghidra structs.
- **`0x2002x` event enum** is only partly observed here (`0x20023` handled, `0x2002b` sent). Map the rest.
- **Stub implication:** to demonstrate hosting, the stub must let the real host↔client NComm flow happen
  (join → broadcast → ready → start) and the referee must answer `RegisterGame` with `RegisterGameResult
  0xDB8`: the handler of that message starts the load (its GameSeed only seeds the chest contents). See
  `docs/MATCH_START.md`.
