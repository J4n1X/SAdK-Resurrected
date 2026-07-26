# Match-start static reconciliation — 2026-06-17

Status: **static RE on `sadk_noav.exe`** (magazine build, base 0x400000, all addrs 1:1), via the
Ghidra MCP. Every line below is `[PROVEN static]` (decompiled/byte-verified this session) unless
fenced as `[RUNTIME — not statically resolvable]`. This doc **corrects** errors in
`MATCH_START_HOST_WALL.md` and `MP_P2P_TRANSITION.md` (see "Corrections" below) and is the
authoritative match-start map going forward.

Maintainer ground truth (in-game, this session): *when all players ready up, the "Connecting to
Game Server" window opens on the host; there is **never any button to press** after that, and it is
unknown what should happen next.*

---

## The two screens — a naming error that caused real confusion [PROVEN static]

There are **two distinct sibling screens**, both deriving from `LobbyMenu::ScreenBase`
(shared ctor `LobbyMenu_ScreenBase_ctor@0x45f420` / `..._variant@0x45f520`, which set
`*this = LobbyMenu::ScreenBase::vftable`). The prior docs called **both** "LobbyGameScreen::Update"
while pointing at two different functions:

| Screen | vtable base | Update (slot 8, vtbl+0x20) | Owns |
|---|---|---|---|
| `LobbyMenu::SetupGameDialog` | `0x007d931c` | `0x00457a00` | the **"Connecting to Game Server" modal**, the Map/MaxPlayer/WinCondition/etc. settings, and the Minimize/Ready/Leave buttons |
| `LobbyMenu::WorldScreen` | `0x007d6eac` | `0x00435980` | the **referee-login pump**, the **game-server-request arm**, the world-screen activation |

(`WorldScreen` vtable owner proven via xref from `LobbyMenu_WorldScreen_ctor@0x00434b46`;
`SetupGameDialog` vtable owner via `LobbyMenu_SetupGameDialog_ctor@0x00454a22`, created by
`FUN_0042bc40`.)

**Consequence:** the modal lives in `SetupGameDialog`, but the code that would send `AssignServer`
(the only escape) lives in `WorldScreen`. They are different objects.

---

## What opens the "Connecting to Game Server" window [PROVEN static]

`LobbyMenu_SetupGameDialog_Update@0x457a00`, top of frame:

```
if ( IsConnectingPhaseActive(0x460850)        // slot 13, vtbl+0x34
     && NComm_IsHost()
     && villageList+0x9c ∈ {-1, -2} )         // -1=DAT_007db520, -2=DAT_007db524 (both byte-confirmed)
{ show "!Connecting to Game Server" / "!PLEASE WAIT"; early-return; }
```

- `villageList = LobbyManager_GetVillageServerList (LM+0x54)`, a `LobbyVillageServerList`.
- `IsConnectingPhaseActive` = `panel(this+0x1e8)->vtbl[0x2c]() && this+0x1d9`. **`this+0x1d9` is a
  `ScreenBase` ctor default (=1)** — toggled by `ScreenBase_SetConnectingVisible@0x460800`,
  cleared by `0x460830`. It is **not** the trigger. The decisive variable is **`villageList+0x9c`**.

So: window opens when the host's `+0x9c` is a sentinel (`-1`/`-2`). This matches the maintainer's
"opens when all ready."

---

## The only escape, and why it's button-free but stalled [PROVEN static]

Escape = `+0x9c → 0`, written by `LobbyServerList_GameServerAssigned@0x469ad0` when the lobby replies
to the host's `AssignServer`. The host emits `AssignServer` via `FUN_0046aaa0` (sets `+0x9c=-2`). The
trigger chain for `FUN_0046aaa0`:

1. **Arm** — `LobbyMenu_WorldScreen_ArmGameServerRequest@0x433f60` (per-frame, called only from
   `WorldScreen::Update@0x435980`): **iff `NComm_Manager_GetState == 0`** and a village-server is
   selected → `FUN_00432180(slots, 8, 0)` writes action-code **8** into `this+0x356c[0]` **and** sets
   the deferred flag `this+0x3638`/`[0xd8e] = 1`.
2. **Dispatch** — `LobbyVillageScreen::OnLeaveVillage@0x437760` has a **programmatic** branch:
   `if (this[0xd8e]!=0 && this[0xd5c]==0 && this[0xd5d]==0 && this[0xd5b]!=0) →
   WorldScreen_DispatchSlotAction(0x434230, slot0)`.
3. **Fire** — `DispatchSlotAction` reads `this+0x356c[slot]`, `switch(code-2)`; **case 6 (code==8) →
   `FUN_0046aaa0` (AssignServer)**.

⇒ The AssignServer path needs **no button** (the deferred-flag branch drives it). Its **sole**
precondition is **`EManagerState == 0`**. (`OnLeaveVillage` also has click-gated entries via
`this[0xd58/0xd59/0xd5a]`, but those are not the auto-start path.)

### Why it stalls

- `EManagerState → 0` happens **only** through `NComm_Manager_Shutdown@0x40b410`, reached without a
  button via: `LobbyVillageServerList_ShutdownNCommIfNotMatchHost@0x468410`'s callers, the
  **referee-abort** path in `WorldScreen::Update` (after 5 failed logins), or `FreeGamePanel`.
- `ShutdownNCommIfNotMatchHost` (gate: `EManagerState!=0 && NComm_Manager_GetMode!=4` → Shutdown +
  `+0x9c=-1`) is itself reached **only** via the **LeaveButton** click (see below) or the
  slot-36 wrapper `LobbyVillageServerList_ShutdownNComm_Wrapper@0x452d90` (vtbl+0x90, pure virtual
  dispatch, no static caller).
- Prior live capture (`MATCH_START_HOST_WALL.md`): `NComm_Manager_Shutdown@0x40b410` had **0 hits**
  and `FUN_0046aaa0` had **0 hits**. If that holds, **the NComm is never torn to state 0 → EManagerState
  stays 2 → the arm never fires → AssignServer never sent → `+0x9c` never advances → stuck.** This is
  the cold model consistent with every observation, including "no button, just stuck."

The Ready button confirms the room state: `SetupGameDialog_HandleButtonClicks@0x457f00` →
`this[0x2df]="ReadyButton"` → `NComm_SendPlayerReadyEvent@0x408d80` = NComm `Event1Integer 0x30011`,
which **requires `EManagerState == 2`**. So in the room the host's NComm sits at **2**.

---

## The button identities [PROVEN static]

`SetupGameDialog_BuildWidgets@0x456c70` looks the dialog's widgets up by name. The three click-latch
buttons read in `HandleButtonClicks@0x457f00`:

| Field | Widget name | Click action |
|---|---|---|
| `this[0x2dd]` (+0xb74) | `"MinimizeButton"` | set `this[0x2ea]=1` |
| `this[0x2de]` (+0xb78) | `"LeaveButton"` | `ShutdownNCommIfNotMatchHost@0x468410` (NComm teardown → `+0x9c=-1`) |
| `this[0x2df]` (+0xb7c) | `"ReadyButton"` | `NComm_SendPlayerReadyEvent@0x408d80` (`0x30011`) |

**LeaveButton is a player ABORT**, not the start path — so the teardown route through `0x457f00` is
irrelevant to the auto-start (matches "no button pressed").

---

## Corrections to prior docs [PROVEN static]

| Prior claim | Corrected |
|---|---|
| "LobbyGameScreen::Update" (`0x457a00` in `MATCH_START_HOST_WALL`, `0x435980` in `MP_P2P_TRANSITION`) | Two screens: `0x457a00`=`SetupGameDialog::Update`, `0x435980`=`WorldScreen::Update`. |
| `MP_P2P_TRANSITION`: "No external trigger needed — the host tears its own NComm down" | **False.** `ShutdownNCommIfNotMatchHost@0x468410` is reached only via LeaveButton click or the slot-36 virtual wrapper — neither automatic. |
| `MATCH_START_HOST_WALL`: `FUN_004ac170(...,4,1)` = "world build / OnEnter" | It's a **screen-stack enable-bit setter** (finds entry==4 in `this+0x3338..` array, sets its active byte). Not a build call. |
| (implicit) `this+0x1d9` gates the modal | `this+0x1d9` is a `ScreenBase` ctor default; the modal gate is `villageList+0x9c`. |

---

## What's left — `[RUNTIME — not statically resolvable]`

Static analysis is exhausted on these; they need a live capture (purely-virtual dispatch / runtime
sequencing — HARNESS §6 escalation, not guessing):

1. **What dispatches slot-36 `LobbyVillageServerList_ShutdownNComm_Wrapper@0x452d90` (vtbl+0x90)** — the
   only button-free route to `NComm_Manager_Shutdown` → `EManagerState 0` → arm → AssignServer? No
   static caller; pure `call [reg+0x90]`.
2. **Does `WorldScreen::Update@0x435980` (which holds the arm) run per-frame while the
   `SetupGameDialog` "Connecting" modal is active?** If the modal sibling suspends it, the arm can
   never fire regardless of `EManagerState`.
3. **What writes `villageList+0x9c = -1` at all-ready** to open the window, given the capture says
   `NComm_Manager_Shutdown` never ran? (The five known `+0x9c` writers are ctor→-1,
   `GameServerAssigned`→0, `AssignGameServerResultReceived`→0, `FUN_0046aaa0`→-2,
   `ShutdownNCommIfNotMatchHost`→-1. A MOV-store search did not find a writer of the room value `101`
   — a 6th path, likely struct-copy.)

### The decisive live test (when the debugger is attached this evening)

Trace `NComm_Manager_Shutdown@0x40b410` + `WorldScreen_ArmGameServerRequest@0x433f60`, and read
`NComm_Manager_GetState@0x408430` (EManagerState) across the both-ready → window-open window. The one
binary question: **does EManagerState ever leave 2?** If no → the missing trigger is whatever should
tear the lobby NComm down to 0. If yes but the arm still doesn't fire → check whether
`WorldScreen::Update` is being pumped while the modal is up.
