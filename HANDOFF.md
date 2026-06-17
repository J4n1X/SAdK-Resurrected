# HANDOFF — pick-up note for the next agent (2026-06-17, evening)

Branch `claude/match-start-re-and-referee-stub` is merged to `master`. Treat this as a fresh start.

## Read first
1. CLAUDE.md  2. HARNESS.md (binding rules)  3. MEMORY.md (index)
4. **`docs/MATCH_START_HOST_WALL.md`** — the wall + the §"2026-06-17" narrowing.
5. `docs/MATCH_START_STATIC_RECONCILIATION.md`, `docs/NCOMM_LAYER.md`, `docs/LOBBY_SCREEN_VTABLES.md`
   — the named/typed map of the screens + NComm (this session named ~210 funcs, 6 structs, 2 enums).

## Milestone: Host + Join matches. Stuck at: host parks on the "Connecting to Game Server" modal.

## ⭐ THE PLAN — chase this, in order ⭐

**The one decisive question: what writes `villageList+0x9c = -1` at match-start?**
That write is what raises/keeps the "Connecting to Game Server" modal, and static RE **cannot** find it
(reasons below). It must be caught live.

### Step 1 — write-watchpoint on `+0x9c` (the whole ballgame)
- Absolute address: `villageList = LobbyManager+0x54`; `+0x9c` ⇒ **`LM + 0xF0`**. Resolve `LM` live:
  `LM = *(0x00885890)` (`g_pLobbyManager`). (Capture #1 had `LM=0x0E5E98E8` → watch `0x0E5E99D8`, but LM
  varies per run — recompute.)
- **Arm a hardware WRITE watchpoint on that dword**, then drive: log in → host a game → both ready.
  The instruction that writes `-1` (and earlier the room value `101`) is the unidentified writer — it is
  **not** any of the 5 known `MOV`-store writers, so it's a struct-copy/`memcpy` an instruction search
  can't see. Catching it names the 6th writer and explains the modal.
- **Tooling note:** the wall doc previously said "heap data watchpoints aren't exposed by the debugger
  MCP." That may be **stale** — the MCP lists `debugger_watch_memory` / `debugger_watch_log` /
  `debugger_watch_stop`. **First action: confirm `debugger_watch_memory` can arm a write watch on an
  absolute heap address.** If yes, this is solved in one session. If genuinely unavailable, fall back to
  trace-and-narrow (arm non-breaking traces on the candidate copy sites around the room→start window).

### Step 2 — once the writer is known
Decide whether `-1` at match-start is correct ("host genuinely needs a game-server assignment, must ASK")
or a bug (something clobbers a previously-valid `+0x9c`). Then either make the host ASK (drive the
teardown→arm→AssignServer chain — but see "no auto trigger" below) or feed the value the real flow expects.

### Step 3 — two independent live probes (cheap, do alongside)
- **Trace `NComm_Manager_BroadcastStartLoading@0x40fe50` at all-ready.** Fires → host got *past* the modal,
  stall is downstream (AllConnected / map). Never fires → the `+0x9c` modal is the hard blocker (the
  broadcasting screen's `Update` is short-circuited). Both WorldScreen::Update and SetupGameDialog::Update
  call it, so it also shows which screen is pumping.
- **Confirm the selected map exists on BOTH peers (.134 and .143).** `NE_GameInformation(0x30003)` runs
  `SP_CheckMapExists` and kicks `"!MAP NOT EXISTING"` (EventKickUser 0x30010) otherwise — a second,
  independent gate that bites *after* the modal clears.

## Why the modal won't clear — the proven chain (static)
Modal clears only when `villageList+0x9c → 0`, written **solely** by `LobbyServerList_GameServerAssigned
@0x469ad0` (the reply to the host's `AssignServer`). Host sends `AssignServer` (`FUN_0046aaa0`) only via
`WorldScreen_DispatchSlotAction@0x434230` case6 (slot action==8), set by `WorldScreen_ArmGameServerRequest
@0x433f60` — **gated on `EManagerState==0`**. NComm reaches 0 only via `NComm_Manager_Shutdown@0x40b410`.

## New proven facts THIS session (sharpen the gap)
- **No automatic NComm teardown exists.** `ShutdownNCommIfNotMatchHost@0x468410` (→ Shutdown → `+0x9c=-1`)
  has two callers: the **LeaveButton** handler, and slot-36 `ShutdownNComm_Wrapper@0x452d90` (`vtbl+0x90`).
  A program-wide search found **one** `call [reg+0x90]` and it is **not** in the lobby (`0x7450fe`,
  `FUN_00741360`). So slot-36 is effectively never dispatched → the teardown is reachable only by the Leave
  button. ⇒ the `+0x9c`/AssignServer "Connecting to Game Server" mechanism has **no auto-start trigger** —
  strong hint it is **not** the intended match-start path (or the host is in an unexpected state).
- **The village list is constructed once** (`LobbyComm_ServerList_ctor@0x46a160`, sole caller
  `LobbyManager::ctor@0x46408f`). Not rebuilt at match-start ⇒ the `-1` is a *write*, not a re-ctor.
- **`Manager_HandleNCommEvent@0x40e560` has no all-ready→teardown case** (only the kick path shuts NComm
  down) ⇒ the teardown trigger is external (screen/UI), confirming the reconciliation doc.
- Corrected: `villageList+0x9c` = assign state (NOT "pending create id"); `+0xa0` = a callback fn-ptr
  (NOT a bool). `LobbyComm_ServerList` struct relabelled accordingly.

## Key named addresses (sadk_noav.exe, base 0x400000) — all applied + saved in Ghidra
- Modal: `LobbyMenu_SetupGameDialog_Update@0x457a00` (gate `NComm_IsHost && +0x9c∈{-1,-2}`),
  `..._IsConnectingPhaseActive@0x460850`.
- Assign chain: `..._GameServerAssigned@0x469ad0` (+0x9c→0) · `FUN_0046aaa0` (AssignServer, +0x9c→-2) ·
  `WorldScreen_DispatchSlotAction@0x434230` (case6) · `WorldScreen_ArmGameServerRequest@0x433f60`
  (needs EManagerState==0) · `ShutdownNCommIfNotMatchHost@0x468410` · `ShutdownNComm_Wrapper@0x452d90`.
- NComm: `NComm_GetManager@0x408290` (`*0x885890`-style singleton `DAT_00885754`) ·
  `NComm_Manager_GetState@0x408430` (mgr+0x1c, EManagerState) · `_Shutdown@0x40b410` ·
  `_StartUpNetwork@0x40a9a0` · `_ConnectAndJoin@0x40ad60` · `_BroadcastStartLoading@0x40fe50` ·
  `Manager_HandleNCommEvent@0x40e560`. Enums `EManagerState`, `NE_EventType`. Struct `NComm_Manager`
  (+0x1c state, +0x3c8 mode, +0x3cc StartLoading, +0xdc 6-slot player table).

## Environment
- RE: Ghidra MCP, program **sadk_noav.exe**, project SaDK, addrs 1:1 (SADK@0x400000, tincat3@0x10000000).
- Live debug: dbgeng `python -m debugger` from C:\Users\user\Downloads\ghidra-mcp, ELEVATED (:8099).
  Break-in POST /debugger/interrupt; reads need target stopped; sync modules after attach; DETACH before
  killing the game. `debugger_watch_memory`/`_trace_function` are the tools for Step 1/Step 3.
- Stub: minisrv `user@linux-server` (.130, **this repo lives here**; `SADK_ADVERTISE_IP=.130`,
  `python3 -m sadk_lobby`). Host = local .134, joiner = .143. master already current here (no pull needed).
- Harness (binding): MCP-first (no standalone RE scripts), no faking, ER-gated stub wire-changes.

## Maintainer ground truth
All players ready → "Connecting to Game Server" modal opens; **no button to press after**; unknown what
should follow. ⇒ supports: the host is waiting on an earlier trigger it never gets, and the `+0x9c` write
that raises the modal is the thread to pull.
