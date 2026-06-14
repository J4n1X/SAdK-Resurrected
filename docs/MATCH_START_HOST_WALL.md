# Match-start host wall — the host never obtains a game-server assignment

Status: **2026-06-14, live-debugged on the real binary** (dbgeng MCP on host PID 37676, magazine
build `sadk_noav.exe`, image base 0x400000, all addrs 1:1). The 2026-06-14 binary question
("does `FUN_0046aaa0` fire on Start?") is **ANSWERED: it never fires.** Every claim below is
tagged `[PROVEN]` (binary addr + live/static evidence) or `[HYPOTHESIS]`.

## TL;DR

The host parks on the modal **"Bitte warten… Verbindung zu Spieleserver wird hergestellt"**
(connecting to game server). Root cause, fully characterized:

- `villageList+0x9c = -1` is the **constructor default** meaning *"no game server assigned"* — it
  is NOT set by the start sequence. The host has been at -1 since the lobby list was built.
- At match-start the LobbyGameScreen's "connecting phase" gate flips on; its per-frame Update then
  shows the dialog and **early-returns every frame** while `+0x9c ∈ {-1,-2}`.
- The only escape is `+0x9c → 0` (assigned), written by `GameServerAssigned`. The host reaches
  that by **sending `AssignServer` via `FUN_0046aaa0`** and getting the reply — but `FUN_0046aaa0`
  and all 3 of its callers **never fire** in the both-ready auto-start. The host never asks.
- A naive stub *push* of `GameServerAssigned` would **crash**: the handler first calls a callback
  at `villageList+0xa0`, which is uninitialized garbage until a real request installs it.

**This is a client-side trigger gap, not a message the stub fails to answer.** The host never
*initiates* the game-server-assignment request in this flow.

## Capture #2 refinement (2026-06-14, fresh start, host PID 44992) [PROVEN]

A second live run (room → both-ready) refines/corrects the model:

- **`+0x9c` is NOT a persistent constructor default.** In the room it reads **101 (0x65)** — a valid
  (non-sentinel) value, so the dialog gate is false and the screen works. It flips to **-1 only at
  match-start**, *after* the start broadcast. (Live: room `+0x9c=0x65`; post-start `+0x9c=0xFFFFFFFF`;
  `+0xa0` stays `0x70732E00` throughout → no request callback ever installed.) So the ctor's -1 is
  overwritten by 101 during lobby/village setup, then reset to -1 at start.
- **The auto-start trigger works:** `FUN_0040fe50` (broadcast `NE_StartLoading` 0x30012) fires exactly
  once at both-ready, called from inside `LobbyGameScreen::Update`'s normal path (caller 0x457CA1) —
  i.e. while `+0x9c` was still 101 (before the dialog gate trips).
- **`FUN_0046aaa0` is the "leave the lobby village" teardown, not a generic start.**
  `LobbyVillageScreen::OnLeaveVillage @0x437760` runs per-frame (~13×/s; 2050 hits) and polls a popup
  result via `FUN_004b2630(this[0xd7b])`; it calls `FUN_0046aaa0` only on **case 0 = the player
  confirming a "!LEAVE_VILLAGE" popup** (the popup is opened in case 5). In the both-ready auto-start
  that confirm never happens → `FUN_0046aaa0` never fires (0 hits in both captures).
- **The deadlock is softer than first stated:** the 3D village screen (`OnLeaveVillage`) is NOT blocked
  — it runs every frame and *could* pump the request. Only the LobbyGameScreen Update is blocked
  (showing the dialog). The host simply never **leaves the lobby village** to transition to a match
  game server.

**Crux (next):** (1) what writes `+0x9c = -1` at match-start — not `FUN_0046aaa0` (writes -2), not
`GameServerAssigned` (writes 0), not the ctor (overwritten by 101); an unidentified writer runs after
`NE_StartLoading`. (2) What is supposed to drive the village-leave/transition at start so `FUN_0046aaa0`
(→ `AssignServer`) fires. Both need a focused capture (trace candidate writers across the room→start
window) — heap-address data watchpoints aren't exposed by the debugger MCP, so it's trace-and-narrow.

### `+0x9c` lifecycle — complete writer set [PROVEN static]

All register-relative `[reg+0x9c]` stores in the lobby code → exactly five writers of the field:
- `FUN_0046a160` (ctor) → -1
- `LobbyServerList_GameServerAssigned @0x469ad0` → 0 (assign success; calls `+0xa0` cb first)
- `LobbyServerList_AssignGameServerResultReceived @0x469be0` → 0 **on error only** (calls `+0xa0` cb
  with failure sentinel `DAT_007db538`; success path leaves `+0x9c` alone)
- `FUN_0046aaa0` → -2 (request sent)
- **`FUN_00468410` → -1 when `NComm_state (FUN_004890b0) != 4`** OR the connect
  `(*(villageList+0x6c))->vtbl[0x28]` fails → `NComm_Manager_Shutdown` + `+0x9c=-1`.

`FUN_00468410` is the prime suspect for the at-start `101 → -1` reset: a match-start NComm reconfigure
takes NComm out of "state 4" → it tears down the game-server link and resets `+0x9c=-1`. (None of the
five writes **101**, so the room value 101 comes from a 6th path the MOV-store search didn't catch —
struct copy / other encoding — minor open detail.)

**Fix-relevant restatement:** at match-start the host's NComm leaves "state 4", the game-server link is
torn down, and `+0x9c` resets to "need assignment" (-1). The host must then **re-establish the
game-server connection** (the `FUN_0046aaa0` path: `StartUpNetwork(4)` → `ConnectAndJoin` →
`AssignServer`), but nothing triggers it in the both-ready auto-start → "connecting to game server"
forever. Next: RE the NComm "state 4" transition at match-start and what is supposed to re-trigger the
connect/request (and whether a lobby/stub message drives it).

## FreeGamePanel world-build path — the host's actual match-start [PROVEN static]

The host's match-world build is SELF-CONTAINED and **independent of the `+0x9c` game-server dance**:
- `FreeGamePanel_OnWidgetClick @0x5e8050`: clicking the widget at `this+0x2cc` sets **`+0x3a9 = 1`**
  (the start flag); `this+0x2c8`/closeButton sets `+0x3a8` (close).
- `FUN_005e3810` (FreeGamePanel per-frame): `if (panel+0x3a9 && panel+0x13c==0) →
  FreeGamePanel_TriggerMPWorldBuild`.
- `FreeGamePanel_TriggerMPWorldBuild @0x5e7350`: clears `+0x3a9`; **`NComm_Shutdown →
  StartUpNetwork(0) → ConnectAndJoin`** (re-inits NComm in mode **0** — NOT the mode-4 lobby path in
  `FUN_0046aaa0`); writes the 6 player slots (tribe/team/color via `FUN_0040bcd0`) into NComm; then
  **`AppState_ActivateWorldScreen_CallOnEnter`** → `nMenu_Game::OnEnter` → builds the 3D match world.

⇒ The world-build does **not** consult `+0x9c`/`GameServerAssigned`; it re-inits NComm itself. So the
"Connecting to Game Server" (`+0x9c=-1`) dialog is likely a **separate LobbyGameScreen state**, and the
real question is whether **`+0x3a9` (Start) ever gets set in the both-ready auto-start** (→ world build),
or whether the `+0x9c` modal is *blocking* the FreeGamePanel Start. **Capture #3** (trace `OnWidgetClick`
0x5e8050 + `TriggerMPWorldBuild` 0x5e7350 + read `+0x3a9`) settles which.

## Live evidence (host PID 37676, capture #1) [PROVEN]

- `g_pLobbyManager = *0x885890 = 0x0E5E98E8`; `villageList = LM+0x54` (`FUN_0046b610` returns
  `LM+0x54`). So `villageList+0x9c` = abs `LM+0xf0` = `0x0E5E99D8`.
- Read while parked on the dialog: `+0x94 = -1`, **`+0x9c = -1`**, `+0xa0 = 0x70732E00` (not a
  code/loaded-module address → invalid callback).
- 7 non-breaking traces armed BEFORE the start, across the full start→park: **0 hits on all of**
  `FUN_0046aaa0` (0x46aaa0), `GameServerManager_AssignServer` (tincat3 0x10021830),
  `LobbyGameScreen_OnStartLoading` (0x4316c0), button/slot dispatch `FUN_00434230` (0x434230),
  and the NComm trio `StartUpNetwork`/`ConnectAndJoin`/`Shutdown` (0x40a9a0/0x40ad60/0x40b410).
- Game stays alive (3D background animates) — confirmed a stuck wait, not a freeze/crash.
- **Deadlock PROVEN (non-breaking traces on the parked host):** `LobbyGameScreen::Update`
  (`FUN_00457a00`) hit **25/25** frames, while the normal-path-only `FUN_004573c0` hit **0** and the
  widget processor `FUN_004588e0` hit **0**. ⇒ Update early-returns *every frame* at `+0x9c=-1`; the
  entire normal path (widget processing, the `[0x2d5]`→`FUN_0046aaa0` request click, the world-build
  call) is unreachable. The host **cannot self-escape** this state. The only thing that can clear
  `+0x9c` is an inbound network msg (`GameServerAssigned`, processed off the screen-Update path) — but
  that handler crashes on the invalid `+0xa0` unless the request was first initiated properly.

## The state machine (static, `sadk_noav.exe`) [PROVEN]

- **`FUN_0046a160`** = LobbyVillageServerList ctor (sets `LobbyComm::ServerList` +
  `CommLayer::IGameServerObserver` vftables). Inits `+0x94 = -1` (create/delete state = idle) and
  **`+0x9c = -1`** (assignment state = none). So -1 is the *resting/default* assignment state.
- **`FUN_00457a00`** = `LobbyGameScreen::Update` (vtable-dispatched). Top of frame:
  `if (vtbl[0x34](this) /*connecting-phase active*/ && NComm_IsHost() &&
   (villageList+0x9c == -1 || == -2)) { show "!Connecting to Game Server"/"!PLEASE WAIT"; return; }`
  → **early-return** before any widget processing or the world-build path. The normal path (below
  the early-return) is where the host would broadcast `NE_StartLoading` (`FUN_0040fe50`) and, when
  `StartLoading && state==VillageEntered`, call `FUN_004683e0(villageList)` + `screen[0xe]->vtbl[0x84]()`
  (= OnEnter / world build). None of that runs while stuck at -1.
- **`FUN_0046aaa0`** (`__fastcall(villageList)`) = the game-server **request**. Gate: only proceeds
  if `+0x9c == -1`. Then `FUN_0046c100` gate → `NComm_Manager_Shutdown` → `StartUpNetwork(4)` →
  `ConnectAndJoin` → builds `"!LOBBY_GAME"` → `*(LM+0x6c)->vtbl[0x20](…, 5, 1, …)` =
  AssignServer type5/sub1. On send success sets `+0x9c = -2` (pending). Does **not** set `+0xa0`.
  Its only 3 callers (all vtable/event-driven, none fired): `FUN_00434230` (slot dispatch, case6),
  `FUN_004588e0` (LobbyGameScreen widget-click processor — widget `[0x2d5]` calls it), and
  `LobbyVillageScreen::OnLeaveVillage @0x437760`.
- **`LobbyServerList_GameServerAssigned @0x469ad0`** (the reply handler): computes `nAssignedId`
  (`*arg`, or failure sentinel `DAT_007db538` if NULL), **calls `(*(villageList+0xa0))(nAssignedId)`**,
  then unconditionally `villageList+0x9c = 0` and `villageList+0xa0 = 0`. So it WOULD clear -1 — but
  the `+0xa0` call is why a blind push crashes when `+0xa0` was never validly installed.
- `+0x94` (create state) is handled by `LobbyVillageServerList_CreateResultReceived @0x46a6a0`
  (CreateServer ACK, valid only if `+0x94 == -2` pending → stores new GameServerID) and
  `LobbyServerList_DeleteResultReceived @0x469990` (on success sets `+0x94 = -1`). The live `+0x94=-1`
  matches the match-start RemoveServer (game delisted). `+0x94` is NOT `+0x9c`.

## What's still open

- **What installs `villageList+0xa0` (the pending-assign callback) and what triggers the request in
  the real flow?** `FUN_0046aaa0` and its callers don't set `+0xa0`; it's installed by an earlier
  request-init / game-server-observer registration that did not happen here. `+0xa0` search is too
  generic to pin statically. `[HYPOTHESIS]` the "earlier action the host waits on" is a lobby step
  (observer registration) that installs `+0xa0` and arms the request — possibly gated on a lobby
  message the stub never sends.
- `vtbl[0x34]` (the "connecting-phase active" gate on LobbyGameScreen) — what flips it at start, and
  does that same handler arm the request? Not yet located.

## Next step

Dynamic capture #2 on a fresh start (debugger stays attached, module map synced): reset to the room,
arm traces on the request path + `FUN_004588e0` (widget processor) + candidate request-init entries,
baseline-read `+0x9c`/`+0xa0` in the room, then re-ready and watch the exact sequence. That directly
shows whether any known trigger fires and pinpoints the `+0xa0` installer.

NOTE (live-RE harness): the dbgeng backend needs its module map synced after attach
(`POST :8099/debugger/sync_modules {"ghidra_bases":{"SADK":"0x400000","tincat3":"0x10000000"}}`,
target **stopped** — keys are runtime module names, which `_normalize_name` matches). There is no MCP
tool for this yet; it's config of the sanctioned debugger, not RE-by-script. Break-in to the dbgeng
target is `POST :8099/debugger/interrupt` (the MCP `debugger_interrupt` tool targets Ghidra Trace-RMI,
a different subsystem). Reads/`get_modules` require the target stopped.

## Superseded

Corrects the 2026-06-14 framing that the wall hinged on whether `FUN_0046aaa0` fires "then bails in
NComm bring-up". It never fires at all; the host sits at the constructor-default unassigned state
and the LobbyGameScreen Update early-returns before any request could be pumped.
