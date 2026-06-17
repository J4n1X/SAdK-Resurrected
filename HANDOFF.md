# HANDOFF — pick-up note (2026-06-17)

Branch `claude/match-start-re-and-referee-stub`, fast-forwarded to and committed on `master`.

## Read first
1. CLAUDE.md  2. HARNESS.md (binding rules)  3. MEMORY.md (index)
4. **`docs/MATCH_START_STATIC_RECONCILIATION.md`** ← this session's findings + the decisive live test.

## Milestone: Host + Join matches. Stuck at: host parks on "Connecting to Game Server."

## What this session did (static RE on `sadk_noav.exe` via Ghidra MCP — no live debug, no stub change)
- Fully mapped the host's game-server-request chain and **corrected two real doc errors**:
  - "LobbyGameScreen::Update" was conflating **two sibling screens**: `0x457a00`=`SetupGameDialog::Update`
    (owns the "Connecting to Game Server" modal), `0x435980`=`WorldScreen::Update` (owns the arm). Both
    `: LobbyMenu::ScreenBase`.
  - `MP_P2P_TRANSITION`'s "no external trigger needed — host tears its own NComm down" is **refuted**:
    the teardown `0x468410` is reached only via the **LeaveButton** click or the slot-36 virtual wrapper.
- The AssignServer auto-trigger is **button-free** (deferred-flag path through `OnLeaveVillage`); its sole
  precondition is **`EManagerState==0`**, which the NComm never reaches at match-start. That single fact
  ties together "no button, just stuck" + the prior capture's `Shutdown`/`AssignServer` 0-hits.
- Renamed + plate-commented ~17 functions in Ghidra (saved). See `decomp/RENAME_LIST.md`.

## THE next action (live, this evening — debugger attached)
Decisive binary question: **does `EManagerState` ever leave 2 at all-ready?**
- Trace `NComm_Manager_Shutdown@0x40b410` + `WorldScreen_ArmGameServerRequest@0x433f60` (both non-breaking),
  read `NComm_Manager_GetState@0x408430` (returns NComm `mgr+0x1c`) across both-ready → window-open.
- `EManagerState stays 2` → the missing trigger is whatever should tear the lobby NComm to 0 (find what
  dispatches slot-36 `0x452d90`, vtbl+0x90 — purely virtual, unresolved statically).
- `reaches 0 but arm still silent` → check whether `WorldScreen::Update@0x435980` is even pumped while the
  `SetupGameDialog` modal is up (modal may suspend the sibling).

## Key named addresses (sadk_noav.exe, base 0x400000)
- `0x457a00` SetupGameDialog_Update (modal gate `+0x9c ∈ {-1,-2}`) · `0x457f00` HandleButtonClicks
  (Leave=`this[0x2de]`/Ready=`[0x2df]`/Minimize=`[0x2dd]`) · `0x456c70` BuildWidgets
- `0x435980` WorldScreen_Update · `0x433f60` ArmGameServerRequest (needs EManagerState==0) ·
  `0x434230` DispatchSlotAction (case6→AssignServer `0x46aaa0`)
- `0x468410` ShutdownNCommIfNotMatchHost (→ Shutdown + `+0x9c=-1`) · `0x452d90` ShutdownNComm_Wrapper (slot 36)
- `0x408430` NComm_Manager_GetState · `0x408290` NComm_GetManager · `0x4890b0` NComm_Manager_GetMode ·
  `0x46b610` LobbyManager_GetVillageServerList (LM+0x54) · `0x408d80` NComm_SendPlayerReadyEvent (0x30011)

## Environment (unchanged from prior handoff)
- RE: Ghidra MCP, program **sadk_noav.exe**, project SaDK. Addrs 1:1 (SADK@0x400000, tincat3@0x10000000).
- Live debug: dbgeng `python -m debugger` from C:\Users\user\Downloads\ghidra-mcp, ELEVATED (:8099).
  Break-in: POST /debugger/interrupt. Reads need target stopped. `debugger_trace_function` non-breaking
  (param `ghidra_address`). Sync modules after attach. DETACH before killing the game.
- Stub: minisrv `user@linux-server:~/projects/sadk-resurrected` (.130), `SADK_ADVERTISE_IP=.130`.
  Host = local .134, joiner = .143. `git pull` master for latest.
- Harness (binding): MCP-first (no standalone RE scripts), no faking results, ER-gated stub wire-changes.

## Maintainer ground truth (this session)
All players ready → "Connecting to Game Server" window opens; **no button to press after**, unknown what
should follow. Directly supports the EManagerState-never-leaves-2 hypothesis (the host is waiting on an
earlier trigger to tear the lobby NComm down).
