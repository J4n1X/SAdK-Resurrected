# Match start — pre-game room → loading the map → playing

How the **client** transitions out of the pre-game game-screen into actually loading the
map and starting the match. This is the long-stuck `[TODO]` ("Entering matches"). All
addresses are **`sadk_noav.exe`** (the active binary), verified live via the Ghidra MCP
this session. Evidence tags: `[PROVEN]` = address + decompiled evidence here;
`[TODO]` = inferred or runtime-indirected, needs a live trace.

> **Why it's broken in the stub.** Match start is **referee-gated**. The referee /
> match-arbiter subsystem was removed from `sadk_lobby/`, so the client's referee login
> never completes and the host's `RegisterGame` never gets a `GameSeed` back — and a
> deterministic lockstep RTS cannot start a match without the shared seed. The 3D lobby
> works; pressing through to a match does not.

---

## The big picture (sequence)

```
        ┌── HOST only ──────────────────────────────────────────────┐
        │ Start clicked → Lobby_HostRegisterGameWithReferee@0x432240 │
        │   gathers room state, sends RegisterGame(0xDB6) ──────────────► REFEREE
        │                                              RegisterGameResult(0xDB8) ◄──
        │                                              { Result==0 → GameSeed }    │
        └────────────────────────────────────────────────────────────┘
                                                                            (seed → +0x50 fan-out)

  ALL clients (host + joiners):
   NE_StartLoading (NComm 0x30012)
        → LobbyGameScreen_OnStartLoading@0x4316c0
            ├ observer?         → just proceed (vtbl[0x30])
            ├ MP game?          → ARM referee login  (+0x3624=1,+0x3625=1,+0x362c=0,+0x3628=0x10)
            └ single/direct?    → LOAD NOW: Game_SetRunMode(game,2) + Game_PropagateModeToChildren(game)

   per-frame: LobbyGameScreen_Update@0x435980  (the referee-login pump)
        if armed:
            retry>4            → give up waiting, LOAD ANYWAY (same Game_SetRunMode(2)+Propagate)
            else after 0x10 fr → RefereeServerConnection_Login(LM+0x490, commSystem); clear do-login
        OnLoginSuccess(0xDCA)  → fan-out refConn+0x80 → screen callback un-arms & proceeds   [TODO callback]
        OnLoginFailed(0xDCB)   → fan-out refConn+0x8c → screen callback re-arms / ++retry      [TODO callback]

   LOAD KICK:
     Game_SetRunMode(game,2)            game+0xc = 2  (run mode → loading/in-game)
     Game_PropagateModeToChildren(game) → Game_NotifyChildrenLifecycle: walk game+0x3b0 child
                                          list, call each child vtbl[0x10] → every subsystem starts
```

---

## Actors & key addresses `[PROVEN]`

| Thing | Where | Notes |
|---|---|---|
| `RefereeServerConnection` sub-object | `LobbyManager+0x490` | getter `LobbyManager_GetRefereeServerConnection@0x4624f0` |
| Host start trigger | `Lobby_HostRegisterGameWithReferee@0x432240` | sole caller of `RegisterGame` |
| Start-loading event handler | `LobbyGameScreen_OnStartLoading@0x4316c0` | NE_StartLoading (NComm 0x30012) |
| Per-frame pump / login retry | `LobbyGameScreen_Update@0x435980` | drives the arm flags below |
| Observer subscribe / unsubscribe | `LobbyGameScreen_Subscribe/UnsubscribeConnectionObservers@0x4351a0 / 0x433d80` | OnEnter / OnExit |
| Load kick | `Game_SetRunMode@0x429900` + `Game_PropagateModeToChildren@0x42a640` → `Game_NotifyChildrenLifecycle@0x429de0` | `game+0xc=2`, then fan-out to children |

### `LobbyGameScreen` arm-state fields (`this+…`) `[PROVEN]`

| Offset | Meaning |
|---|---|
| `+0x3624` | armed (referee login pending) |
| `+0x3625` | do-login this cycle (one Login per arming) |
| `+0x3628` | delay countdown (starts `0x10` frames) |
| `+0x362c` | retry count; `>4` ⇒ stop waiting and load anyway |

---

## Phase 1 — referee server assignment (before login) `[PROVEN, prior RE]`

The referee is a separate server, assigned on demand (see `REFEREE_FUNCTIONS_TO_NAME.md` §C/D):

1. `LobbyServerList_RequestRefereeServer@0x468f60` → `GameServerManager::AssignServer` **NETMSG 189**
   with `server_type=4, subtype=5`.
2. `GameServerManager::OnGameServerAssigned` gates `type==4 && subtype==5` → fires the
   referee-assigned callback `LobbyManager_SetRefereeServerAddress@0x4625d0` → stores `serverId`
   to `LM+0x580`, arms a 60000 ms timer at `LM+0x588`.
3. `LobbyManager_InitRefereeServerConnection@0x462910` (gated on `LM+0x580 != 0`) resolves the
   serverId → ip:port and initialises the `RefereeServerConnection` at `LM+0x490`.

## Phase 2 — host registers the game → GameSeed `[PROVEN]`

`Lobby_HostRegisterGameWithReferee@0x432240` harvests the SetupGame room state and sends
**`RegisterGame(0xDB6)`**. Fields (cat 3 LobbyMessage):

`GameID(u32)`, `MapGUID(16-byte buffer)`, `MapName(str)`, `MapSettings(str)`,
`RankedGame(bool)`, `Wager(u32)`, `AIPlayer(u8 flags)`, `AvatarID(u32) ×6` (one per slot).

The referee answers **`RegisterGameResult(0xDB8)`**: `GameID`, `Result`; on `Result==0` it
carries **`GameSeed(u32)`** and fires the 2-arg fan-out on `refConn+0x50`; on failure it
carries `FailReason(str)` and fires `refConn+0x5c`. (Intermediate `RegisterGameAck(0xDB7)`:
`GameID`, `Result`.) **The `GameSeed` is the lockstep determinism seed — without it the
match cannot start.**

## Phase 3 — start-loading + the referee-login gate `[PROVEN]`

`NE_StartLoading` (NComm `0x30012`) → `LobbyGameScreen_OnStartLoading`. For a **multiplayer**
game (gate: `NMenuSystem+0x3cc != 0`) it does *not* load immediately — it **arms** the login
(`+0x3624/+0x3625/+0x362c/+0x3628`). Observers skip the gate; single-player / direct loads
immediately.

`LobbyGameScreen_Update` is the per-frame pump: after a `0x10`-frame delay it calls
**`RefereeServerConnection_Login@0x4793f0`** (opens the referee transport channel via
`transport+0x34->vtbl[0x10]`), one attempt per arming. After **5 attempts** (`+0x362c>4`) it
**stops waiting and runs the load kick anyway**.

Referee replies: **`LoginSuccess(0xDCA)`** (`PermID`) fires `refConn+0x80`;
**`LoginFailed(0xDCB)`** (`PermID`) fires `refConn+0x8c`. The screen has callbacks on both
lists (subscribed in `LobbyGameScreen_SubscribeConnectionObservers`) — success un-arms and
proceeds, failure drives the retry. **The exact callback bodies are observer-template-
indirected → `[TODO]`** (see below).

## Phase 4 — the load / start-playing kick `[PROVEN]`

Both the success path and the give-up-after-5 path converge on the same two calls:

- `Game_SetRunMode(game, 2)` — sets `game+0xc = 2` (run mode → loading/in-game).
- `Game_PropagateModeToChildren(game)` → `Game_NotifyChildrenLifecycle`: walks the game's
  child-object list at `game+0x3b0` and calls each child's lifecycle `vtbl[0x10]` (with
  `vtbl[0x44]` "active?" / `vtbl[0x1c]` / `vtbl[0x18]` guards). This is the fan-out that
  actually brings up the map/simulation subsystems.

---

## Referee protocol reference (`RefereeServerConnection`, LobbyMessage **category 3**)

Router: `RefereeServerConnection_OnReceive@0x47b090` (switch on msg id) `[PROVEN]`.
Send/recv follow `send 0xD_6/0xD_0/… → ack +1 → result +2`.

| Dir | ID | Message | Payload | Handler |
|---|---|---|---|---|
| C→R | (chan-open) | `Login` | opens transport channel | `…_Login@0x4793f0` |
| C→R | — | `Logout` | | `…_Logout@0x479540` |
| C→R | `0xDB6` | `RegisterGame` | GameID, MapGUID[16], MapName, MapSettings, RankedGame, Wager, AIPlayer, 6×AvatarID | `…_RegisterGame@0x479840` |
| C→R | `0xDAC` | `ClaimChest` | | `…_ClaimChest@0x479670` |
| C→R | `0xDC0` | `FinishGame` | | `…_FinishGame@0x479c40` |
| C→R | `0xDD4` | `GiveUpGame` | | `…_GiveUpGame@0x479ab0` |
| R→C | `0xDCA` | `LoginSuccess` | PermID | `…_OnLoginSuccess@0x47ac20` → `+0x80` |
| R→C | `0xDCB` | `LoginFailed` | PermID | `…_OnLoginFailed@0x47ad50` → `+0x8c` |
| R→C | `0xDB7` | `RegisterGameAck` | GameID, Result | `…_OnRegisterGameAck@0x47a3d0` |
| R→C | `0xDB8` | `RegisterGameResult` | GameID, Result, **GameSeed** \| FailReason | `…_OnRegisterGameResult@0x47a580` → `+0x50`/`+0x5c` |
| R→C | `0xDC1` | `FinishGameAck` | | `…_OnFinishGameAck@0x47a810` |
| R→C | `0xDC2` | `FinishGameResult` | | `…_OnFinishGameResult@0x47a9c0` |
| R→C | `0xDAD` | `ClaimChestAck` | GameID, Result | `…_OnClaimChestAck@0x479fb0` |
| R→C | `0xDAE` | `ClaimChestResult` | AvatarID, ChestID, str | `…_OnClaimChestResult@0x47a160` |
| R→C | `0xDD5` | `GiveUpGameAck` | | `…_OnGiveUpGameAck@0x47ae80` |

### Game-screen observer-list map (referee conn = `LobbyManager+0x490`) `[PROVEN]`

Subscribed in `LobbyGameScreen_SubscribeConnectionObservers@0x4351a0`:

All callbacks are subscribed in `LobbyGameScreen_SubscribeConnectionObservers@0x4351a0` as an 8-byte
`{screen, handlerFn}` struct handed to `ObserverList::Subscribe@0x458860` at `conn+listOffset`. The handler
fn-ptrs are **plain immediates in the registration disassembly** — so the whole callback set is statically
recoverable (no live trace needed; the decompiler only choked on the *fire* path, not the *subscribe* side).
The screen watches **two** connections: the referee conn (`LM+0x490`) and the village/world conn
(`LM+0x540`, via `LobbyManager_GetVillageServerConnection@0x4624d0`).

| Conn list | Fires on | Screen handler (recovered `[PROVEN 2026-06-13]`) | Body |
|---|---|---|---|
| `refConn+0x04` | referee connect/lifecycle | `LobbyGameScreen_ArmRefereeLogin@0x431780` | arms login: `+0x3624=1, +0x3625=0` |
| `refConn+0x10` | referee lifecycle | `LobbyGameScreen_RetryRefereeLogin@0x4317a0` | `+0x362c++, +0x3625=1, +0x3628=retries*8+0x10` |
| `refConn+0x50` | `OnRegisterGameResult` success — (gameId, **GameSeed**) | `LobbyGameScreen_OnRefereeRegisterGameResult@0x431800` | **stores GameSeed → session `DAT_00885754+0xdc`** (`FUN_004082e0`→`FUN_004139f0`, gated `sess+0x1c==2`); `…FillMpDescriptor`; un-arms `+0x3624/+0x3625=0`; Game `vtbl[0x2c](1)` |
| `refConn+0x5c` | `OnRegisterGameResult` failure | `LobbyGameScreen_OnRegisterGameFailed@0x432fd0` | `!REGISTER_GAME_FAILED` dialog |
| `refConn+0x80` | `OnLoginSuccess` | `Lobby_HostRegisterGameWithReferee@0x432240` | **host sends `RegisterGame(0xDB6)`** (login OK → register) |
| `refConn+0x8c` | `OnLoginFailed` | `LobbyGameScreen_OnRefereeLoginFailed@0x4317d0` | retry+backoff (identical to `+0x10`) |
| `villageConn+0x1c` | `NE_StartLoading` (`0x30012`) | `LobbyGameScreen_OnStartLoading@0x4316c0` | arm referee login (MP) or load now |
| `villageConn+0x28` | game-connect result | `LobbyGameScreen_OnGameConnectionResult@0x432ed0` | **load kick** (`Game_SetRunMode(2)`+propagate); `!CONNECTION_LOST` dialog on error |
| `villageConn+0x8c` | join rejected: no table | `LobbyGameScreen_OnJoinFailedNoTable@0x433280` | `!MINIGAME_NOTABLELEFT` dialog |
| `villageConn+0x98` | join rejected: no slot | `LobbyGameScreen_OnJoinFailedNoSlot@0x433380` | `!MINIGAME_NOPLAYERSLOTLEFT` dialog |

**Room model corroboration:** the village-conn join-failure handlers say `!MINIGAME_NOTABLELEFT` /
`!MINIGAME_NOPLAYERSLOTLEFT` — i.e. a game is a **"table"** with **"player slots"**, and join failures
arrive as **village/world-connection** events (the `GameServerConnection` at `+0x544` stays a no-op on the
dispatch path). So the room/slot layer lives on the **village connection's** message+observer system.

---

## LobbyManager connection topology `[PROVEN 2026-06-13]`

The LobbyManager (`LobbyComm::System`, ctor `LobbyManager::ctor@0x463fd0`, singleton ptr
`g_pLobbyManager@0x885890`) owns **three peer `LobbyBaseConnection` subclasses**, all created in its ctor:

| Field | Off | Class | Bytes | ctor |
|---|---|---|---|---|
| `pVillageConnection` | `LM+0x540` | `LobbyComm::VillageServerConnection` (vtbl `0x7dc8d4`*) | 0x280 | `VillageServerConnection::ctor_full` |
| `pGameSlotConnection` | `LM+0x544` | `LobbyComm::GameServerConnection` (vtbl `0x7deaf0`, `LobbyGameServerConnection.cpp`) | 0x38 | `GameServerConnection::ctor@0x48ed50` |
| `refereeServerConnection` | `LM+0x490` | `RefereeServerConnection` (embedded) | 0xB0 | — |

\* village vtbl base is build-specific; `0x7dc8d4` is the SADK.exe map. In noav the gameserver vtbl is `0x7deaf0`
(slot `+0x14`=`OnLoggedIn@0x48edf0` confirms the base — no off-by-0xc).

**Inbound routing — `LobbyManager::DispatchInboundToConnection@0x462760`:** for an inbound `(connId, channel,
data, byteLen)` it finds which of the three connections owns `connId` (`FUN_0048dd30(conn, connId)` predicate),
wraps `data` in an `NCore::BitStream`, and calls `conn->vtbl[0x24](channel, &bitStream)` — the same dispatch
slot the village conn uses for `HandleMessage`.

**Key negative result:** `GameServerConnection`'s `vtbl[0x24]` is the engine's **shared no-op default**
(`Stub_NoOpReturnVoid@0x472360`, referenced as the default slot by dozens of vtables). So **the pre-game room
protocol does NOT ride `GameServerConnection::HandleMessage`** the way the 3D-world protocol rides
`VillageServerConnection::HandleMessage`. The slot/tribe/team/color/ready updates ride **another
layer** — and the recovered handler map (below) shows which one: the **village/world connection's**
observer+message system. Its join-failure events (`!MINIGAME_NOTABLELEFT` / `_NOPLAYERSLOTLEFT`) and the
`NE_StartLoading`/load-kick events all come off `LM+0x540`, not the game-slot conn. The granular slot **data**
lives in the **NComm game-session object** (see "Pre-game room — player-slot model" below); the wire path that
*updates* those slots is still `[TODO]` — the two village cases checked so far (`0xC1C`→`FUN_0046e660`,
`0xC80`→`FUN_0046c940`) turned out to be in-world **entity-pool** ops (read `"ownr"`, touch `this+0x170`),
**not** slot updates, so the slot-update messages are elsewhere (likely the NComm/NetEngine protocol).

## Pre-game room — player-slot model `[PROVEN 2026-06-13]`

The SetupGame dialog's slots are a fixed **6-slot array inside the NComm game-session object**. Slot API:
`NComm_GetSlotDataPtr(gameObj, i) = gameObj + 0x10 + i*0x4c` (`@0x413100`), `NComm_IsSlotEmpty@0x409cc0`,
`NComm_FindPlayerSlotByNamePtr@0x413300` (matches the 16-byte owner GUID, caps at 6). The match-start reader
is `LobbyMenu_SetupGameDialog_SetupSession_FillMpDescriptor@0x4562d0` — it walks the 6 slots, reads each via
the accessors below, and writes a `GameLoadDescriptor` (the per-player setters `FUN_005293b0`=type,
`FUN_005293e0`=color/faction, … verified against `MapSelect_ConfigurePlayerSlot_FillDescriptor@0x5df2c0`).

**`NCommGameSlot` (0x4c = 76 bytes):**

| Off | Type | Field | Accessor | Note |
|----:|------|-------|----------|------|
| `+0x00` | — | (header, 13B) | — | `[TODO]` unknown |
| `+0x0d` | byte[16] | ownerGuid | `NComm_Slot_GetOwnerGuid@0x415200` | `NComm::NetGUID`; the `"ownr"` identity |
| `+0x1e` | char[~0x1c] | playerName | `NComm_Slot_GetPlayerName@0x415430` | inline C-string |
| `+0x3a` | int8 | playerIndex | `NComm_Slot_GetPlayerIndex@0x414d60` | |
| `+0x3b` | int8 | **kind** | `NComm_Slot_GetKind@0x414d70` | `0`=empty, `1`=human, `2`=AI, `3`=closed |
| `+0x3c` | int8 | aiLevel | `NComm_Slot_GetAiLevel@0x414d80` | valid when kind==AI |
| `+0x3d` | int8 | tribe/color? | `FUN_00414da0` (→`FUN_004538b0` map → descriptor color/faction) | `[TODO]` exact semantic |
| `+0x3e` | int8 | ? | `FUN_00414db0` | `[TODO]` |
| `+0x3f` | int8 | ? | `FUN_00414dc0` | `[TODO]` |
| `+0x40` | — | (12B) | — | `[TODO]` — team / ready likely here |

`[TODO]` to finish the room model: (a) disambiguate `+0x3d/+0x3e/+0x3f` and the `+0x40..0x4b` tail against
the descriptor setters → label tribe/color/team/**ready**; (b) formalize `NCommGameSlot` as a Ghidra struct;
(c) **the wire-update path** — how slots get populated/changed over the network (join, pick tribe, ready). The
slot object passed to `FillMpDescriptor` is the SetupGame game object; the GameSeed lives in a *different*
object (`DAT_00885754+0xdc`, the nMenu session singleton) — relationship `[TODO]`.

## Open `[TODO]` — to finish the model / unblock the stub

1. ~~**Observer callback bodies (the linchpin).**~~ **DONE 2026-06-13 — statically.** The
   subscribe side stores each callback fn-ptr as a plain immediate, so a live trace was NOT needed:
   all ten handlers are recovered + named (see the table above). `LoginSuccess→`
   `Lobby_HostRegisterGameWithReferee` (host registers the game); `LoginFailed→` retry+backoff.
2. ~~**GameSeed consumer.**~~ **DONE 2026-06-13 (storage endpoint).** `refConn+0x50` →
   `LobbyGameScreen_OnRefereeRegisterGameResult@0x431800` stores the seed into the game-session
   singleton **`DAT_00885754+0xdc`** (via `FUN_004082e0`→`FUN_004139f0`, gated on `sess+0x1c==2`),
   fills the MP descriptor, and kicks the Game (`vtbl[0x2c](1)`). `[TODO]` one hop deeper: confirm
   `DAT_00885754+0xdc`/`FUN_004139f0` is where the deterministic-sim RNG actually reads the seed.
3. ~~**Identify `FUN_004624d0`**~~ — **DONE 2026-06-13.** It is `LobbyManager_GetVillageServerConnection@0x4624d0`
   (returns `VillageServerConnection*` at `LM+0x540`). The game screen's second observer target is the
   **village/world connection**, not a new actor — proven via the noav struct field + the
   `CreateVillageServerConnection@0x463850` setter. (New lead surfaced here: `LobbyManager.pGameSlotConnection`
   at `LM+0x544` — a *distinct* connection slot beside `pVillageConnection@0x540`, not previously mapped;
   candidate carrier of the unreversed pre-game slot/tribe/team/ready protocol.)
4. **Stub implication.** To start a match the stub referee must, at minimum: accept the
   referee `Login` (→ `LoginSuccess 0xDCA`), accept the host's `RegisterGame 0xDB6`
   (→ `RegisterGameAck 0xDB7` then `RegisterGameResult 0xDB8` **with a `GameSeed`**). All
   clients in the match must receive the **same** seed. Re-introducing the referee server is
   the path to unblocking "entering matches".
5. **Re-verify live** that the "give-up-after-5-retries → load anyway" path is what actually
   happened in past failed tests (it loads but likely can't start the sim without a seed).

---

## Live debug plan (run on Windows — the game can't run on the Linux box)

Static RE is exhausted at the observer-callback boundary; the rest needs a live trace. Drive
the **real client** against the stub via the Ghidra MCP debugger (HARNESS §1 — attach/breakpoint
through the MCP, not a standalone script). Addresses are `sadk_noav.exe` base `0x400000`.

**In-game path (single play session):** launch the client pointed at the stub → log in
`test/test/test` → enter the lobby/village → **Host** a game (SetupGame dialog) → add a joiner
or an AI to a slot → click **Start**. (For the joiner side, join the hosted game and ready up.)

**Tier A — observable against the *current* stub (no referee needed):**
| Breakpoint | Read | Confirms |
|---|---|---|
| `LobbyGameScreen_OnStartLoading@0x4316c0` | `this+0x3624/0x3625/0x362c/0x3628`; `NMenuSystem+0x3cc` | the arm vs load-now fork |
| `RefereeServerConnection_Login@0x4793f0` | the referee transport target (ip:port) at `this+0x34` | Phase 1/3 — client *does* try the referee |
| `LobbyGameScreen_Update@0x435980` (the `0x362c>4` branch) | retry count | the give-up-after-5 → load-anyway path |
| `Game_SetRunMode@0x429900` | `game+0xc` becomes `2` | the load kick fires |
| `Lobby_HostRegisterGameWithReferee@0x432240` | the harvested args before `RegisterGame` | host's RegisterGame payload (host only) |

**Tier B — needs a minimal stub-referee responder first** (accept `Login`→`LoginSuccess 0xDCA`,
and `RegisterGame 0xDB6`→`Ack 0xDB7`+`Result 0xDB8` with a `GameSeed`). Only then do these fire:
| Breakpoint | Read | Resolves |
|---|---|---|
| inside `FUN_00479ef0` at the callback dispatch `(*(code*)puVar3[3])(…)` | `puVar3[3]` (the callback fn ptr) | **the game-screen LoginSuccess/Failed callback** (`[TODO]` #1) |
| inside `FUN_00464300` (register-result fan-out) | the callback fn ptr + the `GameSeed` arg | **the seed-result callback** |
| `RefereeServerConnection_OnRegisterGameResult@0x47a580` | the `GameSeed` value read off the wire | seed delivery |
| then single-step the resolved callbacks | where `GameSeed` is stored / the sim RNG seeded | **GameSeed→sim consumer** (`[TODO]` #2) |

Chicken-and-egg: Tier B's success callbacks can't fire until the stub at least *answers* the
referee `Login`/`RegisterGame`. So the practical order is: (1) Tier A first (pure observation,
nothing to build); (2) stand up a minimal stub referee responder; (3) Tier B to read the live
callback targets and seed wiring; (4) flesh out the stub referee from what Tier B reveals.
