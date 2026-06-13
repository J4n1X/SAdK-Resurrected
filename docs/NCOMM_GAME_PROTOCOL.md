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
                └ (GameSeed stored here too, via FUN_004139f0 — see docs/MATCH_START.md)
```

- The **game object** (Manager+0xdc) holds the 6-slot array and the GameSeed. `NComm_GetSlotDataPtr(gameObj, i)
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
| `+0x09` | — | (4B) | — | `[TODO]` reset via `FUN_00416350` |
| `+0x0d` | byte[16] | ownerGuid | `NComm_Slot_GetOwnerGuid@0x415200` | `NComm::NetGUID`; the `"ownr"` identity |
| `+0x1d` | int8 | (join flag) | set by `FUN_00414e10` | `[TODO]` set on join |
| `+0x1e` | char[~0x1c] | playerName | `NComm_Slot_GetPlayerName@0x415430` | inline C-string |
| `+0x3a` | int8 | playerIndex | `NComm_Slot_Get/SetPlayerIndex@0x414d60/0x414e20` | default `0xFF` |
| `+0x3b` | int8 | **kind** | `NComm_Slot_GetKind@0x414d70` | `0`=empty · `1`=human · `2`=AI · `3`=closed |
| `+0x3c` | int8 | aiLevel | `NComm_Slot_GetAiLevel@0x414d80` | valid when kind==AI |
| `+0x3d` | int8 | **tribe** `[PROVEN]` | `NComm_Slot_Get/SetTribe@0x414da0/0x414e50` | `0`=Bavarian `1`=Scots `2`=Egyptian (`NComm_GetNationIdForTribe@0x4538b0`) → descriptor `+0x68`; default `0xFF` |
| `+0x3e` | int8 | **color** `[PROVEN]` | `NComm_Slot_Get/SetColor@0x414db0/0x414e60` | **unique** — 0x30002 swap-on-conflict loop → descriptor `+0x88`; default = slot index |
| `+0x3f` | int8 | **team** `[INFERRED]` | `NComm_Slot_Get/SetTeam@0x414dc0/0x414e70` | → descriptor `+0xa8`; default = slot index |
| `+0x40` | int8 | ? | — | `[TODO]` |
| `+0x41` | u16 | ? | — | `[TODO]` default `0xFFFF` |
| `+0x43` | u32 | ? | — | `[TODO]` default `-1` |
| `+0x47` | u32 | ? | — | `[TODO]` default `DAT_007db510` |
| `+0x4b` | int8 | ? | — | `[TODO]` default `1` |

The match-start reader `LobbyMenu_SetupGameDialog_SetupSession_FillMpDescriptor@0x4562d0` walks these 6 slots
into the `GameLoadDescriptor`. `NComm_Slot_Reset` is the per-slot clear (empty/closed).

> Labels confirmed 2026-06-13: **tribe (`+0x3d`)** `[PROVEN]` — `NComm_GetNationIdForTribe` maps `0/1/2` to the
> literal nation names *Bavarian / Scots / Egyptian* (the three playable tribes). **color (`+0x3e`)** `[PROVEN]`
> — the 0x30002 unique-swap loop. **team (`+0x3f`)** `[INFERRED]` — by elimination + its own distinct descriptor
> array (`desc+0xa8`); the only one not yet hard-proven.

---

## NComm event dispatcher — `Manager_HandleNCommEvent@0x40e560` `[PROVEN]`

Called every frame from the NComm Manager main loop (`NComm_Manager_Process_MainLoop@0x410f70`). It reads the
event type via `event->vtbl[4]()` and switches. Two id spaces exist: **`0x2002x`** (NComm transport/session
events) and **`0x3000x`** (game/room events — the ones dispatched here). Behaviour below is from the decompiled
switch; the **names are `[INFERRED]` from behaviour** unless noted.

| Event id | Name `[INFERRED]` | Behaviour `[PROVEN]` |
|---|---|---|
| `0x20023` | NE_LoggedIn | sets tick timing fields |
| `0x30001` | **PlayerJoinRequest** (host) | validate `NComm_GetBuildVersion`/`GetBuildChecksum`/password/`ValidateStaticDataMD5` → `NComm_KickPlayer("!VERSION/CHECKSUM/PASSWORD MISMATCH")` on fail; else find/assign slot, `NComm_UpdateReadyUI`, `NComm_BroadcastGameInfo`, "!Player joined game" |
| `0x30002` | **SlotConfigChange** | apply staged config to the player's slot: tribe `Mgr+0x24→slot+0x3d`, color `Mgr+0x2c→slot+0x3e` (**unique-swap loop**), team `Mgr+0x28→slot+0x3f`, playerIndex `Mgr+0x30→slot+0x3a`; each change → `NComm_SetPlayerConnectionState(0)` |
| `0x30003` | AllConnectedSync | reconcile the two slot arrays (detect join/leave by ownerGuid/name diff → UI notify); `SP_CheckMapExists`; build `.s2m`/`.bmp` map paths; `0x30010`+"!MAP NOT EXISTING" if missing |
| `0x30004` | ConnStateChange | set `NComm_SetPlayerConnectionState`; if host → `UpdateReadyUI` + `BroadcastGameInfo` |
| `0x30005` | TickSync | `NComm_ProcessEventTimestamp` + `NComm_GetCurrentTick` |
| `0x30006`/`0x30007` | HostMigration `[INFERRED]` | `FUN_0040e400`/`FUN_0040e4b0` |
| `0x30008` | (name copy) | copies a string into `Mgr+0x3d1`-region |
| `0x30009` | (relay) | `NComm_IsSlotEmpty` + `FUN_00416030` |
| `0x3000a` | **PlayerLeave** | vacate slot, `UpdateReadyUI` + `BroadcastGameInfo`, "!Player left game" |
| `0x3000b` | **GameInfoBroadcast** | non-host applies slot data (`FUN_00410720`); when host & all-ready → send `NComm::Event1Integer 0x2002b` |
| `0x3000d` | TickTiming | tick fields |
| `0x3000e` | **Reconnect** | match slot by name, restore owner (`FUN_00414de0`) + connected (`FUN_00414dd0`); `"!COULD NOT RECONNECT"` kick on fail |
| `0x3000f` | SessionTeardown | mark disconnected players left across the 6 slots; reset tick state |
| `0x30010` | **Kicked** | "!You were kicked!" UI; then leave/cleanup |
| `0x30011` | **PlayerReady** | `NComm_CheckPlayerPassword` → `SetPlayerConnectionState(1/0)`; if host → `UpdateReadyUI` + `BroadcastGameInfo` |
| `0x30012` | **StartLoading** | `ProcessEventTimestamp`; set `Mgr+0x3cc = 1` (the flag `LobbyGameScreen_Update` polls to arm the referee login — see `docs/MATCH_START.md`) |

### Supporting NComm functions (already named in the project)

`NComm_BroadcastGameInfo@0x4090e0` (host pushes room state), `NComm_UpdateReadyUI@0x40b5a0` (per-slot ready/AI
fill, kicks "!GAME FULL"), `NComm_KickPlayer@0x40b470`, `NComm_CheckPlayerPassword@0x413540`,
`NComm_FindPlayerSlotByNamePtr@0x413300` (match by 16-byte ownerGuid, caps at 6), `NComm_IsSlotEmpty@0x409cc0`,
`NComm_GetConnectedPlayerCount@0x413010`, `NComm_IsHost@0x408410`, `NComm_IsInGame@0x408440`,
`NComm_IsAllConnected@0x4083b0`, `NComm_SetPlayerConnectionState@0x552f10`, `NComm_GetCurrentTick@0x4133c0`,
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
  `NComm::TinCatNetwork` over TinCat at `Manager+0x340`. Remaining: hard-prove **team** (`+0x3f`) and identify
  the slot tail fields `+0x40/+0x41/+0x43/+0x47/+0x4b`.
- **Host vs P2P topology:** is `NComm::TinCatNetwork` a star (clients→host) or routed via a server? Read the
  connect/listen path (`StartUpNetwork` mode switch; `TinCatNetwork` vtbl `0x10`/`0x40`).
- **Formalize** `NCommGameSlot` and the NComm Manager / game-object as Ghidra structs.
- **`0x2002x` event enum** is only partly observed here (`0x20023` handled, `0x2002b` sent). Map the rest.
- **Stub implication:** to demonstrate hosting, the stub must let the real host↔client NComm flow happen
  (join → broadcast → ready → start) and the referee must supply the GameSeed. See `docs/MATCH_START.md`.
