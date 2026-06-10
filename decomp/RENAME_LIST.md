# SADK.exe — proposed labels (apply in Ghidra)

> **⚠️ Predates the magazine-build re-map.** Every `FUN_<addr>` / `DAT_<addr>` below is an
> **old-build VA** (the no-CD/dump base); the clean 2014 magazine build shifted these addresses.
> The logic/struct-offsets still transfer, but for current addresses use **`docs/SOURCEMAP.md`** as
> the firmer reference. Treat this list as historical RE notes, not live addresses.

From tracing the greyed **"Suche Server…" / Enter-Village** button. Addresses are
virtual (the `FUN_<addr>` name). Confidence: **H** = string/file-name confirmed,
**M** = inferred from clear logic, **L** = plausible, verify before trusting.

## Functions

| Address | Proposed name | Conf | Evidence |
|---------|---------------|------|----------|
| `FUN_00439e80` | `LobbyVillageScreen::UpdateEnterButton` | H | Sets enter button to `!ENTER_VILLAGE_BUTTON` (live) or `!LOBBY_LOADING_SERVERS` (greyed); computes enabled state. |
| `FUN_0043a580` | `LobbyVillageScreen::RefreshView` (SetMode/tab) | M | Mutates mode field `+0x1e8` 18×, refreshes the 5 tab/button widgets + enter-button text. NOT the network enter action. |
| `FUN_0043ab10` | `LobbyVillageScreen::OnVillageConnectFailed` | H | Shows `!COULDNOT_CONNECT_TO_VILLAGE` / `!ERROR`; runs when server-list lookup for the selected room fails. |
| `FUN_00462bc0` | `LobbyManager::GetStateName` | H | switch over `this+0x57c` → `"LobbyManagerState: ..."` strings (the lobby state enum). |
| `FUN_00463750` | `LobbyManager::CreateVillageServerConnection` | H | Literal `LobbyComm::System::CreateVillageServerConnection`, from `LobbyManager.cpp`. Opens the village connection at `this+0x540`. |
| `FUN_00468d80` | `LobbyVillageServerList::FindByRoomId` | M | Searches the entry vector (`this+0x70..0x78`), matches `entry+0x30 == key`, returns index or -1. |
| `FUN_0046b250` | `LobbyManager::GetSelectedVillageServer` | L | Returns `*(this+0x80)` (the village server handle/id used as the default connect target). |
| `FUN_00472040` | `*::IsField98Set` (enable-cond #2) | L | Returns `*(this+0x98) != 0`; generic getter — confirm what `+0x1ec` object is. |
| `FUN_00437680` | `LobbyVillageScreen::OnLeaveVillage` | M | References `!LEAVE_VILLAGE` / `!LEAVE_VILLAGE_QUESTION`. |
| `thunk @ 0x4682d0` (`thunk_FUN_01375b50`) | `LobbyVillageServerList::IsListReady` (predicate) | L | The predicate that flips the button text (false → "Loading Servers"). **Unrecovered jump table** — see notes. |

## Globals

| Address | Proposed name | Conf | Evidence |
|---------|---------------|------|----------|
| `DAT_0087d580` | `g_SelectedVillageRoomId` | M | Compared against `serverEntry+0x30` in every list filter (38017, 44083/116, 44250/258); assigned at 41512, 42321. The selected room/LobbyId the village list is filtered by. |
| `DAT_012f161c` | `g_pVillageListReadyFn` (jumptable slot) | L | Indirect target called by `thunk_FUN_01375b50`. Only read, never written in the dump → set via the unrecovered jump table at `0x4682d0`. |

## Struct field offsets (set these as struct members in Ghidra)

**LobbyVillageScreen** (the `this` of `FUN_00439e80` / `FUN_0043ab10`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x1e8` | view mode / selected tab (int; enable needs `== 1`) | M |
| `+0x1ec` | ptr → sub-object, enable needs `*(it+0x98) != 0` | M |
| `+0x1f0` | ptr → `LobbyVillageServerList` | M |
| `+0x204..0x214` | UI widget ptrs (enter button + tab buttons) | M |
| `+0x218` | byte: idle/ready-to-connect (1 = idle; failure handler resets to 1) | L |
| `+0x21c` | byte: busy/guard (proceed only when `== 0`) | M |
| `+0x254` | (inside `+0x204`) the Enter-Village button widget | M |

**LobbyManager** (`this` of `FUN_00463750` / `GetStateName`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x50` | lobby comm / socket object | M |
| `+0x540` | village server connection object | H |
| `+0x57c` | state enum (see `LobbyManagerState` below) | H |
| `+0xd4` | selected village server handle/id (`*(+0x54 +0x80)`) | L |

**ServerListEntry** (elements of `LobbyVillageServerList`):
| Off | Meaning | Conf |
|-----|---------|------|
| `+0x30` | RoomId / LobbyId (filtered against `g_SelectedVillageRoomId`) | M |
| `+0x34` | flag (checked `== 0` in some filters) | L |

## LobbyManagerState enum (value at `LobbyManager+0x57c`)

```
1 Disconnected   2 Authorizing   3 Authorized   4 CheckingVersion
5 VersionChecked 6 LoadingGlobalData 7 GlobalDataLoaded
8 EnteringVillage 9 VillageEntered 10 LeavingVillage 11 VillageLeft
12 ConnectionLost
```

## Live-confirmed in Ghidra (s4) — already applied + saved

| Address | Name / type | Note |
|---------|-------------|------|
| `004626f0` | `LobbyManager::GetState` | `return this->state` (+0x57c). |
| `00462700` | `LobbyManager::SetState` | `if(state==12) return; state=arg` — latches on ConnectionLost. |
| `00503da0` | (EnterVillage action) | sole caller of `CreateVillageServerConnection`; passes -1 → uses selected server. |
| `00468140` | `LobbyVillageServerList::HasServerSelected` | `selected(+0x80) != -1`. |
| `007dc51c` (data) | `g_dwInvalidVillageServerId` | the -1 "no selection" sentinel. |
| enum | `LobbyManagerState` | created, 12 values. |
| struct | `LobbyManager` (0x580) | fields pComm+0x50, selectedVillageServer+0xd4, pVillageConnection+0x540, state+0x57c. |
| struct | `LobbyVillageScreen` (0x21d) | viewMode+0x1e8, pField98Owner+0x1ec, pServerList+0x1f0, pButtonContainer+0x204, pWidget1-4, idleFlag+0x218, busyGuard+0x21c. |

Login-sequence state writers (set literals 1→7): `FUN_00462fe0` `004632f0` `00463910`
`00464b90` `00464c00` (+ readers `00464910` `00470f10`). `EnteringVillage(8)` is set via
`SetState(8)` (no inline constant) — caller still TBD.

## Connection classes (s9) — applied + saved in Ghidra

The lobby uses 5 `LobbyBaseConnection` subclasses (Connect@0x48d730 shared). Names below are
applied in the project.

| Address | Name | Conf |
|---------|------|------|
| `0x48d730` | `LobbyBaseConnection::Connect` (→ comm `vtable[0x1c]`(port,ip,x)) | H |
| `0x48d8b0` / `0x48d9d0` / `0x48dc20` | `LobbyBaseConnection::On{LoggedIn,LoginFailed,Disconnected}` | H |
| `0x47ed90` | `UserCommConnection::Initialize` (chat/UC conn = LobbyUserCommConnection.cpp) | H |
| `0x47fb40` | `UserCommConnection::OpenCommunication` (opens UC via comm `vtable[0x10]`(handle)) | H |
| `0x47fca0` | `UserCommConnection::JoinChannel` | H |
| `0x47ef50/0x47f040/0x47f130/0x47f220/0x47f310/0x47f400` | `UserCommConnection::On{LoggedIn,LoginFailed,LoggedOut,Disconnected,ReceivedData,ChatChannelListReceived}` | H |
| `0x48e650` | `GameServerConnection::OnLoggedIn` (LobbyGameServerConnection.cpp) | H |
| `0x462fe0` | `LobbyManager::Login` | H |
| `0x463910` | `LobbyManager::OnLoggedIn` (sets chatServerHandle +0x548 = login param_2) | H |
| `0x464740` | `LobbyManager::OnLoginFailed` | H |
| `0x4626c0` | `LobbyManager::GetChatServerHandle` (returns +0x548) | H |

vtables: UserComm `0x7dded8`, GameServer `0x7dfafc`, Village `0x7dc8e0`. `LobbyManager+0x548`
= chat-server handle (set at login).

## Notes / next in Ghidra

- **Recover the jump table at `0x4682d0`** (the `thunk_FUN_01375b50` body — Ghidra warned
  "Could not recover jumptable. Too many branches"). Once recovered, `g_pVillageListReadyFn`
  resolves and confirms the "list ready" predicate. This is the cleanest way to verify the
  text gate.
- The actual button **click → enter** wiring (button widget → `CreateVillageServerConnection`)
  wasn't traced; start from the widget at `LobbyVillageScreen+0x254` / the input handler.
