# GAME_HARNESS_DESIGN.md — Autonomous SAdK test harness

> **Status:** DESIGN ONLY (no code written yet). This document specifies the infrastructure
> that lets **Claude (an AI agent)** autonomously launch *Die Siedler: Aufbruch der Kulturen*
> (`SADK.exe`), drive it (login → char-select → Start Game), observe its state, and run full
> test cycles against the `sadk_lobby` stub — replacing the human-in-the-loop.
>
> Companion reading: `AGENTS.md` §7 (the Win11 SecuROM fix), `tools/debugger_loader.py`,
> `tools/read_village_state.py`, `WORLD_ENTRY_PLAN.md`, `SOURCEMAP.md` (the
> `LobbyManagerState` enum @ `LobbyManager+0x57c`).

---

## 0. TL;DR — the recommended design in five bullets

1. **One launcher = the debugger.** Reuse `tools/debugger_loader.py`'s proven transparent
   debug loop as the *only* way the game starts. It already satisfies the SecuROM/WOW64
   exception-forwarding requirement (it IS a debugger). Wrap it in a controller that exposes
   pid + lifecycle. **Do not** try to launch the game "normally" and attach automation on
   top — the debug loop is mandatory for world-enter on Win11, so make it the foundation.
2. **Observation is primarily memory, not pixels.** The client exposes a single-byte state
   enum at `LobbyManager+0x57c` (`Disconnected=1 … VillageEntered=9 … ConnectionLost=12`).
   An extended `read_village_state.py` (read-only `ReadProcessMemory`) is the **ground-truth,
   deterministic** signal for "where is the client right now / did it enter / did it crash".
   Screenshots are a *secondary*, human-facing artifact — never the primary gate.
3. **Input is foreground `SendInput` with scancodes**, against the game forced into **windowed
   mode at a fixed resolution**. `PostMessage` is unreliable for a D3D9/DirectInput title.
   The two clicks we actually need (login submit, Start Game) both have **Enter-key
   accelerators**, so 90% of the input problem collapses to "focus the window, send VK_RETURN".
4. **The stub already automates the server side.** Login is `test/test/test`; world-entry is
   driven by the server *pushing* msg `1000` (config `ARM_ENTER_WORLD`/`ENTER_WORLD_DELAY`),
   not by the client click. So the harness's job on the client side is minimal: get to
   char-select, then just *exist* while the stub pushes — the test is mostly about
   **observing** the result and **correlating** stub log ↔ client state.
5. **Build it in phases.** v0 (MVP) wires launch → wait-for-state(char-select) via RPM →
   collect logs → classify outcome → kill. It needs **zero pixel input** because the stub's
   delayed `1000` push drives world-entry autonomously. Input injection (clicking Start Game
   to register the village templates) is Phase 2, only if the delayed-push bet fails.

---

## 1. Constraints recovered from the repo (the ground we must stand on)

| Fact | Source | Consequence for the harness |
|---|---|---|
| World-enter on Win10/11 needs a **debugger attached** passing first-chance AVs back to SecuROM's VEH. | `AGENTS.md` §7, `tools/debugger_loader.py` | The launcher must *be* (or run under) a debug loop for the whole session. |
| The transparent loop is `CreateProcess` → sleep(~8s) → `DebugActiveProcess` → `WaitForDebugEvent`/`ContinueDebugEvent(DBG_EXCEPTION_NOT_HANDLED)`, eating only the attach BP. | `tools/debugger_loader.py` | Proven, byte-for-byte reusable. `debugger_trace.py` already extends it with INT3 hooks — same skeleton can host more. |
| Client state lives at `LobbyManager+0x57c` (1 byte enum); singleton ptr @ `0x0088CEF0`. `GetState`@`0x4626f0`, `SetState`@`0x462700` (latches at 12=ConnectionLost). | `SOURCEMAP.md`, `RENAME_LIST.md`, `read_village_state.py` | **Primary state probe.** Read-only RPM, cannot crash the game, works alongside the debugger. |
| `LobbyManagerState`: `1 Disconnected · 3 Authorized · 6 LoadingGlobalData · 7 GlobalDataLoaded · 8 EnteringVillage · 9 VillageEntered · 10 (room/login) · 11 VillageLeft · 12 ConnectionLost`. | `SOURCEMAP.md` §enum | The state ladder *is* the test oracle. ≥7 = reached char-select; ==9 = **PASS** (entered world); ==12 = ConnectionLost (fail). |
| World-entry is driven by the **server pushing msg `1000`** (`HandleEnterWorld`@`0x46f470` calls `SetState(9)` first). The "BETRETE WELT" click emits **zero** on the wire. | `WORLD_ENTRY_PLAN.md`, `config.py`, `dispatch.py` `_h_send_token` | The client click is *not* strictly required to flip state to 9 — the stub can drive it. Click is only needed to make the overlay **register the 1000-template** (the timing blocker). |
| Stub: `python -m sadk_lobby` binds 7070/7071/5479; logs to `tincat_server.log`; per-conn `.bin` under `sadk_captures/`. `ARM_ENTER_WORLD`, `ENTER_WORLD_DELAY` gate the auto-push. | `server.py`, `config.py` | The server half is *already* a non-interactive automaton. Harness just starts it + reads its log. |
| Game logs (when `-log_info -log_path C:\tmp`): `commLayer.log`, `LobbyComm.log`. Client config must point at the stub in **two** files (`LobbySettings.ini`, `network.ini`). | `AGENTS.md` §3/§10, observed `C:\tmp` | Harness collects these per run; config is a one-time fixture, not per-run. |
| Login dialog widgets & the Start button are **name-bound in C++** from XML (`lobbyLoginDialog.xml`; `StartGameButton`, hotkey **13 = Enter** = "Betrete Welt", in `lobbyAvatarScreen.xml`). | `UI_FINDINGS.md` §2/§3 | Both key actions have **Enter accelerators** → keyboard, not pixel-hunted mouse clicks. |
| Dead ends: two `SADK.exe` instances won't run; `-localhostmode` exposes no socket. Game has run **elevated** historically; user is now **disabling compat mode** → non-elevated launch going forward. | `AGENTS.md` §12, task brief | One game instance per cycle. Plan for non-elevated, but keep an elevation fallback. |
| Env: Windows 11 x64, Python 3.11.9 (`C:\…\Python311`), game at `E:\…\bin\SADK.exe`. A dbgeng **MCP debugger** @ `127.0.0.1:8099` and a Ghidra MCP @ `:8089` exist; `computer-use` + `claude-in-chrome` MCPs may be intermittently connected. | verified this session | Use the in-repo Python debug loop as the spine (always available); treat MCPs as optional accelerators, not dependencies. |

### The single most important design consequence

Because (a) world-entry is **server-push driven** and (b) the client's progress is **readable
from memory**, the *core* automated loop needs **no GUI input at all** for the common case.
That makes a robust MVP dramatically easier than "drive a DirectX GUI blind." GUI input is a
Phase-2 capability reserved for the one thing the server can't do for the client: trigger the
**BETRETE WELT** action so the SecuROM overlay registers the type-1000 PropertySet template.

---

## 2. Architecture

```
                         ┌──────────────────────────────────────────────────────────┐
                         │  Claude (agent)                                           │
                         │  drives via: Bash(python game_harness.py …)  +  reads     │
                         │  the JSON verdict + artifacts it writes.                  │
                         └───────────────┬──────────────────────────────────────────┘
                                         │ subprocess / stdout-JSON
                                         ▼
        ┌────────────────────────────  tools/game_harness.py  (the orchestrator) ───────────────────────┐
        │                                                                                                 │
        │  1. StubController         2. GameController            3. StateProbe         4. (opt) InputDriver
        │     start `python -m          (the debug loop:             read-only RPM        SendInput to the
        │     sadk_lobby` as a          CreateProcess + Debug        of LobbyManager       focused game window
        │     child; tee its            ActiveProcess loop, from     +0x57c etc.          (Enter / clicks)
        │     stdout+log; parse         debugger_loader.py),         (extends
        │     for milestones.           run as a worker thread       read_village_state)
        │                               INSIDE this process.                                              │
        │                                                                                                 │
        │  5. Outcome classifier  ──► verdict {pass|fail|timeout|crash|frozen} + reason + artifacts        │
        │  6. Artifact collector  ──► copies tincat_server.log, C:\tmp\*.log, a screenshot, state trace    │
        │  7. Lifecycle: kill game + stub, ensure ports freed, repeat N times deterministically.           │
        └─────────────────────────────────────────────────────────────────────────────────────────────────┘
                 │                          │                              │
                 ▼                          ▼                              ▼
        sadk_lobby (stub)          SADK.exe (debugged child)        ReadProcessMemory (VM_READ)
        7070/7071/5479             SecuROM faults → VEH (works)      LobbyManager state ladder
```

### 2.1 Why the debug loop lives *inside* the harness process (not a separate console)

`debugger_loader.py` today is a standalone script you keep open in a window. For automation,
the controller runs the **same loop on a daemon thread** (or a child process whose stdout the
controller tees). Reasons:

- **A Win32 debuggee dies/detaches with its debugger** unless `DebugSetProcessKillOnExit(False)`
  is set (the loader already calls this). Keeping the loop in-process means the harness owns the
  game's lifetime cleanly: when the harness decides "kill and retry", it stops the loop and
  terminates the pid.
- The loop must call `WaitForDebugEvent`/`ContinueDebugEvent` **continuously** or the game
  freezes at the next fault. A thread that does nothing but pump the loop (exactly as today) is
  the simplest way to guarantee that while the *main* thread runs the test logic (probing state,
  reading logs, timing out).
- **Critical threading rule (Win32):** the thread that calls `DebugActiveProcess` must be the
  same thread that calls `WaitForDebugEvent`/`ContinueDebugEvent`. So the debug pump owns
  attach→loop end-to-end on one thread; the orchestrator communicates with it via thread-safe
  state (a shared `dict`/`Event`: `pid`, `attached`, `exited`, `fault_count`, `last_fault_code`).

### 2.2 Reconciling "needs a debugger" with "wants automation" (the central question)

There are three candidate launch strategies. **Recommended: A.**

| Option | How | Verdict |
|---|---|---|
| **A. In-repo debug loop as the spine** (RECOMMENDED) | `GameController` = `debugger_loader.py`'s loop on a thread; orchestrator drives everything else. | **Self-contained, no external service, proven.** The loop already carries the game into the 3D world on Win11. Zero new RE risk. Always available (pure ctypes + Win32). |
| **B. Game under the dbgeng MCP** (`debugger_attach`/`debugger_launch` @ :8099) | Let the MCP own the debuggee; harness reads state via MCP `debugger_read_memory`/`registers`. | Useful **add-on** for deep dives (breakpoints on `RegisterPropertySet`, `SetState`), but: only **one debugger per process**, the MCP must be elevated+running, and it's a heavier moving part. **Don't make the test loop depend on it.** Use it *instead of* the in-repo loop only when you specifically need live breakpoints (Phase 3). |
| **C. No debugger, patch the DRM slot** (`drm_addr_patch.py`) | Externally rewrite the dead SecuROM VM slot so the faulting call returns scratch. | **Rejected.** `AGENTS.md`/the tool's own header say returning NULL/scratch is *insufficient* — the VM consumes the real return; this is a proof tool, superseded by the debugger. |

**Rule:** exactly **one** debugger attaches to `SADK.exe` at a time. The default harness uses
the in-repo loop (Option A). If a run needs the dbgeng MCP for breakpoints, the harness launches
the game *under the MCP* and skips its own loop for that run (mutually exclusive). The read-only
`StateProbe` (RPM) is **always** safe to run concurrently with either — a `VM_READ` handle does
not conflict with a debugger.

### 2.3 Elevation

The user is disabling compat mode, so the target is **non-elevated** operation:
- `CreateProcess` + `DebugActiveProcess` + `ReadProcessMemory` all work non-elevated **when the
  debugger and the game run at the same integrity level** (both medium). That's the new normal.
- Binding lobby port **7070** sometimes needed admin historically. If `_make_listener` fails to
  bind, the harness surfaces the clear "Run as Administrator" error and aborts the run (rather
  than producing a false "client never connected" fail).
- Keep an `--elevated` assumption switch: if a future machine still marks the EXE
  run-as-admin, the whole harness must be launched elevated (a debugger can't attach to a
  higher-integrity process). Detect this early: if `DebugActiveProcess` fails with
  `ERROR_ACCESS_DENIED`, emit "relaunch the harness elevated" and stop.

---

## 3. Input injection — method, rationale, risks

### 3.1 What input we actually need (small!)

| Action | Screen | Cheapest deterministic input |
|---|---|---|
| Submit login `test/test` | `lobbyLoginDialog` | Type into focused fields then **Enter**; or if creds persist from a prior run, just **Enter**. |
| "Start Game / BETRETE WELT" | `lobbyAvatarScreen` → `StartGameButton`, **hotkey 13 (Enter)** | **Press Enter** (the accelerator). No pixel hunt. |
| Dismiss an error/MOTD modal | `lobbyMessageBoxDialog` etc. | **Enter** or **Esc**. |

Because every required action maps to **Enter/Esc**, the harness avoids the hardest part of GUI
automation (locating moving D3D-rendered buttons). Typing the username/password is the only
character input, and even that is skippable if the client remembers the last login.

### 3.2 Method comparison (researched for D3D9/DirectInput)

| Method | Works for SADK (D3D9, likely DirectInput)? | Notes |
|---|---|---|
| **`SendInput` (foreground, scancodes)** ✅ RECOMMENDED | **Yes**, when the window is foreground+focused. | The only method that reliably feeds DirectInput games, which read device state, not the window message queue. Use **scancodes** (`KEYEVENTF_SCANCODE`), not just VKs. This is what PyDirectInput/pydirectinput_rgx do. |
| `PostMessage(WM_KEYDOWN/WM_LBUTTONDOWN)` to bg window | **Unreliable.** | DirectInput bypasses the message queue, so posted messages are often ignored by the game's input path. Fine for *non*-DirectInput menus, but we can't assume that. **Do not rely on it.** |
| `SendMessage` | same problem as PostMessage + can block on a hung UI thread | avoid. |
| UI Automation (UIA) | **No.** | The game is a single D3D surface; widgets aren't UIA elements. Nothing to enumerate. |
| **computer-use MCP (desktop screenshot + click)** ✅ FALLBACK | **Yes** (it injects at the desktop/composited layer like a user). | Great when connected; intermittent availability and pixel-coordinate fragility make it a *fallback/секondary*, not the spine. |

**Decision:** primary = **`SendInput` with scancodes to the foreground game window**, via a tiny
ctypes `InputDriver`. Fallback = **computer-use MCP** for the rare case SendInput is swallowed or
a genuinely mouse-only widget appears. (PyDirectInput could be vendored, but a ~40-line ctypes
`SendInput` wrapper keeps the harness dependency-free, matching the existing tools' style.)

### 3.3 Making `SendInput` deterministic for a DirectX window

1. **Force windowed mode at a fixed size/position.** Fullscreen-exclusive D3D9 complicates
   focus, capture, and coordinate math. Find the SAdK display setting (an options INI / registry
   key under the user profile) and pin **windowed, e.g. 1024×768 at (0,0)**. *Action item: locate
   this config — likely `data\lobby\config\*` or `%USERPROFILE%\Documents\SAdK\`; if none exists,
   `-localhostmode`-style flags or a borderless-window shim may be needed. Treat "force windowed"
   as a fixture step, validated once.*
2. **Bring to foreground reliably.** Foreground-stealing is restricted on modern Windows; the
   robust sequence is: `ShowWindow(SW_RESTORE)` → `AttachThreadInput(ourTID, gameTID, TRUE)` →
   `BringWindowToTop` + `SetForegroundWindow` → `SetFocus` → `AttachThreadInput(…, FALSE)`. Verify
   with `GetForegroundWindow()==hwnd` before sending input; retry a few times.
3. **Locate the window** by pid → top-level `hwnd` (`EnumWindows`, match `GetWindowThreadProcessId`
   to the game pid; the SADK window class/title can be confirmed once with Spy++ or
   `GetWindowText`). Don't hardcode a title guessed from training data; **discover it live** the
   first time and record it in the harness as a constant.
4. **Send scancode key events** with small inter-event sleeps (~30–50 ms down/up; DirectInput
   polling needs the key state to persist across at least one frame). For text fields, send each
   character as scancodes; for accelerators, a single `VK_RETURN`/`VK_ESCAPE`.
5. **Gate every input on an observed state precondition** (see §4): e.g. only press the
   Start-Game Enter once `StateProbe` shows the client has reached char-select (state ≥7) — never
   fire blind on a timer.

### 3.4 Risks (input)

- **Focus loss** if another window pops (incl. the debugger console). Mitigate: run the game
  window pinned/topmost during a run; re-assert foreground before each input; the harness has no
  visible console of its own (it's a child process Claude spawns).
- **DirectInput swallows VK-only input.** Mitigate: always include scancodes.
- **The Start-Game Enter accelerator may require the avatar to be selected first.** `UI_FINDINGS`
  hints the button ungreys on `IsListReady && HasServerSelected` (server-side, already handled by
  the stub's `170`). Validate that a bare Enter on the avatar screen triggers
  `LobbyVillageEnterAction`; if it needs a prior avatar click, that's the one place a coordinate
  click (or the SelectNickname/TYPE 72 flow) is needed — fall back to computer-use MCP for that
  single click, or script it via the known widget layout.

---

## 4. Observation — how Claude knows the game's state

### 4.1 Signal hierarchy (most → least authoritative)

1. **RPM of `LobbyManager+0x57c` (PRIMARY).** Extend `read_village_state.py` into an importable
   `StateProbe` that, given the pid, returns a structured snapshot:
   - `state` (the enum byte) + its **name** (`Disconnected/Authorized/…/VillageEntered/…/ConnectionLost`).
   - the existing village-list view (entries, `roomId`, `pending`, `validity`, JOINABLE?).
   - the connect-gate fields it already reads (`conn+0x34`, selected-server id, `commLayer`).
   This is deterministic, sub-millisecond, **cannot crash** the game (read-only `VM_READ`), and
   works *while the debugger holds the game*. It directly answers: **at login? (state ≤3) ·
   char-select reached? (state 7) · entering? (8) · ENTERED WORLD? (9) · ConnectionLost? (12)**.
2. **Stub log / milestones (PRIMARY for the wire side).** `StubController` tees
   `tincat_server.log` and matches milestone lines: handshake, `SessionKey (207)`, `170×N`,
   second-conn (UC), `211→214`, `→ … EnterWorld (msg 1000)`. Gives the *server's* view of how far
   the conversation got, and timestamps to correlate with state transitions.
3. **Liveness / crash / freeze (from the debug loop).** The in-process debug loop already knows:
   - `EXIT_PROCESS_DEBUG_EVENT` → the game **exited/crashed** (clean signal, no polling).
   - fault rate: a *burst* of unhandled AVs around world-load that never resolves, with state
     stuck <9, indicates the SecuROM dispatch path is unhappy (the historical crash signature).
   - **Frozen vs busy:** PhysX world-load spins; distinguish a legitimate load from a hang by
     watching **state advancement** (does it reach 9 within the budget?) and optionally GUI
     responsiveness (`SendMessageTimeout(WM_NULL, …, SMTO_ABORTIFHUNG)` → if it times out, the UI
     thread is wedged).
4. **Game logs (`C:\tmp\commLayer.log`, `LobbyComm.log`).** Collected per run; grepped for
   client-side deserialize/connect errors (e.g. the `LobbyVillageServerList.cpp` lines). Best for
   *post-mortem diagnosis*, not real-time gating (they lag and aren't structured).
5. **Screenshot (SECONDARY / human-facing).** A single capture at the decision point + on failure,
   saved as an artifact for the human and for Claude to eyeball. **Not** a gate. Capture options:
   - **computer-use MCP screenshot** — easiest, captures the composited desktop (sidesteps the D3D
     black-frame problem entirely). Preferred when connected.
   - **`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT=2)`** — works for a *windowed* D3D9 target where
     plain `BitBlt` returns black. Pure GDI, no MCP dependency.
   - **Windows.Graphics.Capture (WGC)** — most robust for D3D but heaviest to stand up; defer.
   - OCR is **not** needed because memory tells us the state; a screenshot is just corroboration.

### 4.2 The state oracle (single source of truth for pass/fail)

```
poll StateProbe.state every 250 ms, with a per-phase deadline:
  reach_login        : state in {1,3}            within  20 s  (client connected, at login)
  reach_charselect   : state == 7                within  45 s  (login OK, global data loaded)
  enter_world        : state == 9                within  30 s  of the stub's "EnterWorld(1000)" line
classification:
  state == 9                                   -> PASS (entered the 3D world)
  EXIT_PROCESS_DEBUG_EVENT before state 9      -> CRASH (+ last state, last fault code, log tails)
  state == 12 (ConnectionLost)                 -> FAIL_DISCONNECT (token/handshake rejected)
  deadline exceeded, process alive, state<9    -> TIMEOUT/FROZEN (+ SMTO_ABORTIFHUNG result)
  stub never saw a handshake                   -> FAIL_NOCLIENT (config/binding problem)
```

This ladder makes runs **objective and machine-checkable** — no screenshot interpretation in the
hot path.

### 4.3 Offsets the probe relies on (record-and-pin)

- `LobbyManager` singleton ptr: `0x0088CEF0` → `+0x57c` = state byte. (`SOURCEMAP.md`,
  `read_village_state.py`.) Image base `0x400000`, **no ASLR rebase** → absolute addrs are stable.
- Village list `+0x54`; entry fields `+0x28/2c/30/34/35` (already in the reader).
- These are **version-specific**; the harness asserts the singleton ptr is readable and the state
  byte is in `1..12` before trusting it (guards against an offset drift / mid-update read).

---

## 5. The end-to-end automated test loop

### 5.1 One cycle (the default, **no GUI input** path — relies on the stub's auto-push)

```
run_cycle(run_id):
  0. PREP    ensure 7070/7071/5479 free (kill stragglers); assert client config points at stub.
  1. STUB    start `python -m sadk_lobby` as a child (ARM_ENTER_WORLD=True, ENTER_WORLD_DELAY=T);
             tee stdout+tincat_server.log; wait for "listening on 7070".
  2. GAME    start the debug-loop GameController:
                CreateProcess(SADK.exe, cwd=bin)  [+ "-log_info -log_path C:\tmp" for game logs]
                sleep(ATTACH_DELAY≈8s)            [let SecuROM startup anti-debug finish]
                DebugActiveProcess(pid); DebugSetProcessKillOnExit(False); pump loop on a thread.
  3. LOGIN   wait StateProbe.state in {1,3} (client connected).  [if creds not remembered:
                focus window; SendInput "test"⇥"test"⏎]          ← Phase-2 input; MVP assumes remembered
  4. CHAR    wait StateProbe.state == 7  (char-select reached).  ← login crypto already works
  5. ENTER   the stub auto-pushes msg 1000 ENTER_WORLD_DELAY s after the 214 handshake.
             wait StateProbe.state == 9  OR  deadline.
             [Phase 2: if the delayed push needs the client BETRETE WELT engagement first to
              register templates, focus window + SendInput ⏎ at char-select, THEN expect the push.]
  6. OBSERVE classify via the §4.2 oracle.  Snapshot a screenshot at the decision point.
  7. COLLECT copy tincat_server.log, C:\tmp\commLayer.log + LobbyComm.log, the state trace
             (timestamped state samples), fault count/last code, screenshot  → runs/<run_id>/.
  8. VERDICT write runs/<run_id>/verdict.json {result, reason, last_state, durations, artifacts[]}.
             also print the JSON to stdout (Claude reads it directly).
  9. TEARDOWN stop the debug loop; TerminateProcess(game); stop the stub; confirm ports freed.
```

### 5.2 Determinism & isolation

- **Fixed inputs:** same account, same `ENTER_WORLD_DELAY`, windowed at a fixed size, game logs to
  a **fresh per-run `C:\tmp\run_<id>\`** (so logs aren't cross-contaminated). Truncate/rotate
  `tincat_server.log` per run (the stub already truncates on start).
- **Clean process state:** kill any stale `SADK.exe` *before* starting (the single-instance lock
  otherwise makes `CreateProcess` "succeed" into a dead instance). Verify the new pid is the one we
  launched. Free ports between runs (the stub uses `SO_REUSEADDR`, but confirm no lingering owner).
- **One variable at a time:** the harness takes the knob under test as an arg (e.g.
  `--enter-delay`, `--worldname`, `--arm/--no-arm`) so a sweep changes exactly one thing per run.
- **Bounded everything:** every wait has a deadline; the whole cycle has a hard cap (e.g. 180 s)
  after which it's force-classified TIMEOUT and torn down — no run can wedge the agent.

### 5.3 Recovering from a frozen game (the PhysX world-load spin)

- **Detect:** state stuck <9 past the enter deadline AND `SendMessageTimeout(WM_NULL,…,
  SMTO_ABORTIFHUNG, 2000)` times out → UI thread wedged. (A *legit* load reaches state 9 well
  inside the budget; a wedge doesn't and stops pumping messages.)
- **Recover:** `TerminateProcess(pid)`; the debug loop sees `EXIT_PROCESS_DEBUG_EVENT` and unwinds;
  harness frees ports and proceeds to the next run. Because `DebugSetProcessKillOnExit(False)` is
  set, stopping the loop alone won't kill a *healthy* game — so the harness **explicitly**
  terminates on the freeze path.
- **Never** leave a half-dead game holding the single-instance lock into the next cycle (PREP
  step 0 also sweeps, as a belt-and-suspenders).

### 5.4 How Claude drives it

Claude runs `python tools/game_harness.py run --runs 1 --enter-delay 2.0` via Bash, then reads the
emitted `verdict.json` (also echoed to stdout). For a sweep: `--runs 5 --sweep enter-delay=0,1,2,4,6`.
For a deep dive on a failing case, Claude switches to the **dbgeng MCP** path
(`--debugger mcp`) and sets a breakpoint on `tincat3!RegisterPropertySet (0x10013710)` to watch the
1000-template registration (per `WORLD_ENTRY_PLAN.md`) — the harness just launches+holds the game;
Claude does the breakpoint science through MCP tools.

---

## 6. Build plan (phased, concrete)

### Phase 0 — fixtures & probes (no game launch logic yet) — *0.5 day*
- **`tools/game_harness.py` skeleton**: arg parsing, `runs/<id>/` layout, JSON verdict writer,
  port-sweep + stale-`SADK.exe` killer (`PREP`).
- **Extend `read_village_state.py` → importable `StateProbe`**: add a `read_state(pid)->{state,
  name}` using `+0x57c` and the `LobbyManagerState` map; keep the CLI behavior. Validate live by
  hand against a running game at login vs char-select (expect 3 → 7).
- **`StubController`**: spawn `python -m sadk_lobby`, tee log, detect "listening on 7070" and the
  milestone lines (regexes). Unit-test the parser against the existing `tincat_server.log`.
- *Risk:* low. These are read-only / process-spawn utilities; the state offset is already proven.

### Phase 1 — **MVP: one autonomous launch→observe cycle, zero GUI input** — *1 day*
- **`GameController`**: lift `debugger_loader.py`'s loop into a thread-driven class exposing
  `start()`, `pid`, `wait_exit()`, shared `{attached,exited,fault_count,last_code}`. Add
  `-log_info -log_path C:\tmp\run_<id>` to the launch.
- **Wire the loop (§5.1) steps 0–2,4–9**, skipping step 3 login-typing by relying on **remembered
  credentials** (manually log in once so the client stores `test`; confirm it auto-fills). The stub
  already auto-pushes `1000`, so this MVP can reach **state 9** with **no input injection at all**.
- **Outcome oracle (§4.2)** + artifact collection + `verdict.json`.
- **Deliverable:** `python tools/game_harness.py run` →
  starts stub, launches game under the debugger, watches the state ladder to 9 (or classifies
  crash/timeout), dumps logs+screenshot+verdict, kills everything. **This is the minimal first
  version that gives Claude a full automated login→Start-Game→observe cycle.**
- *Risk:* medium. Threading the debug loop correctly (same-thread attach/wait rule) is the main
  pitfall; mitigate by keeping the loop *identical* to the proven script and only adding the shared
  status dict + a stop flag checked each iteration.

### Phase 2 — input injection (close the loop without relying on remembered creds / explicit click) — *1 day*
- **`InputDriver`** (ctypes `SendInput`, scancodes): `focus(hwnd)` (the AttachThreadInput dance),
  `type_text(s)`, `press(vk)`. Discover the game window (pid→hwnd) and record its class/title;
  force windowed mode (locate the display setting — *spike first*).
- **Wire step 3** (type `test`/`test`+Enter at login) and the **BETRETE WELT Enter** at char-select
  (only if Phase-1 shows the stub's delayed push needs the client engagement to register templates).
- **computer-use MCP fallback** for any single mouse-only widget (e.g. avatar pre-select) that the
  Enter accelerator doesn't cover.
- *Risk:* medium-high. Foreground/focus on modern Windows and DirectInput swallowing are the known
  hazards (§3.4). The Enter-accelerator design keeps the surface tiny; "force windowed" is the
  riskiest unknown — spike it before committing.

### Phase 3 — deep-dive integration (the template-timing science) — *0.5 day, as needed*
- **`--debugger mcp` mode**: launch/hold the game under the dbgeng MCP instead of the in-repo loop;
  expose helpers so Claude can set the `RegisterPropertySet`/`SetState` breakpoints from
  `WORLD_ENTRY_PLAN.md` and correlate the exact moment the 1000-template registers with the stub's
  push timing. The harness orchestrates launch+state probing; Claude does the breakpoint reasoning.
- *Risk:* low-medium (depends on the MCP being up+elevated; it's optional, not on the test path).

### Phase 4 — sweeps & regression (quality of life) — *0.5 day*
- `--sweep enter-delay=…`, `--runs N`, an aggregate `summary.json` (pass rate, per-delay outcomes),
  and a tiny human-readable table. Lets Claude *empirically* find the right `ENTER_WORLD_DELAY` by
  bisection instead of guessing — directly attacking the one remaining protocol unknown.

### What's hard / risky (consolidated)
1. **Threading the debug loop** (same-thread attach/wait; never stall the pump). → keep it
   byte-identical to the proven loader; only add a status dict + stop flag.
2. **Forcing windowed mode + reliable foreground** for `SendInput`. → spike the display setting
   early; pin topmost; verify `GetForegroundWindow`. This is the single biggest Phase-2 unknown.
3. **DirectInput swallowing VK input.** → scancodes always.
4. **Freeze vs slow-load disambiguation.** → state-advancement budget + `SMTO_ABORTIFHUNG`.
5. **Offset drift** if the binary/patch level changes. → probe asserts state∈1..12 & ptr readable
   before trusting; fail loud, don't silently misreport.
6. **MCP availability** (computer-use / dbgeng). → never on the critical path; pure-Win32 spine.

### Explicit non-goals
- No binary patching / SecuROM RE (the debugger sidesteps it).
- No OCR / pixel state-machine (memory is the oracle).
- No two-instance / multiplayer automation (single-instance lock; out of scope).
- No headless/offscreen rendering (the game must render for D3D/world-load to proceed).

---

## 7. Concrete minimal first version (what to build first)

A single file, **`tools/game_harness.py`**, plus a small **`StateProbe`** factored out of
`read_village_state.py`. The MVP command:

```
python tools/game_harness.py run --enter-delay 2.0 --out runs/
```

does exactly this, **with no GUI input** (leaning on remembered creds + the stub's auto-push):

1. Kill stale `SADK.exe`; ensure 7070/7071/5479 free.
2. Spawn the stub (`ARM_ENTER_WORLD=True`, `ENTER_WORLD_DELAY=2.0`); wait for "listening on 7070".
3. Launch `SADK.exe` under the in-repo debug loop (Option A) with `-log_info -log_path C:\tmp\run_…`.
4. Poll `StateProbe.state` (RPM @ `LobbyManager+0x57c`) every 250 ms against the §4.2 ladder.
5. Classify **PASS** (state 9) / **CRASH** (early exit) / **TIMEOUT-FROZEN** / **FAIL_DISCONNECT**
   (state 12) / **FAIL_NOCLIENT** (stub saw no handshake).
6. Collect `tincat_server.log` + `C:\tmp\run_…\*.log` + a `PrintWindow(PW_RENDERFULLCONTENT)` (or
   computer-use) screenshot + the timestamped state trace into `runs/<id>/`.
7. Write+print `verdict.json`. Terminate the game; stop the stub; free ports.

This gives Claude a **fully autonomous login → char-select → (stub-driven) Start-Game → observe →
report** cycle on the very first build, with the deterministic memory oracle deciding pass/fail —
and a clean seam to add `SendInput` (Phase 2) and the dbgeng-MCP breakpoint science (Phase 3) when
the delayed-push experiment demands them.

---

## 8. Open spikes to resolve during build (small, bounded)

- **Window identity:** confirm `SADK.exe`'s top-level window class/title live (pid→hwnd), record it.
- **Windowed-mode setting:** find where SAdK stores display mode (game INI / registry under the
  user profile); confirm a fixed windowed size sticks. *(Biggest Phase-2 unknown.)*
- **Remembered credentials:** verify the client refills `test`/`test` so the MVP needs no typing.
- **Start-Game precondition:** confirm a bare **Enter** on the avatar screen fires
  `LobbyVillageEnterAction` (vs. needing a prior avatar click → then script that one click).
- **`PrintWindow(PW_RENDERFULLCONTENT)` on this title:** confirm it yields a non-black frame in
  windowed mode (else fall back to computer-use MCP screenshots).

---

### Sources (DirectX automation research)
- [SendInput vs PostMessage / focus + AttachThreadInput for input injection](https://microsoft.public.win32.programmer.kernel.narkive.com/sG2n75ih/how-to-make-sendinput-or-postmessage-work)
- [Capturing an obscured DirectX window (hook D3D; GDI returns black)](https://www.gamedev.net/forums/topic/563845-capturing-an-obscured-directx-window/)
- [PrintWindow PW_RENDERFULLCONTENT / Windows.Graphics.Capture options (MS Q&A)](https://learn.microsoft.com/en-us/answers/questions/801244/capturing-a-window)
- [DirectInput games need SendInput w/ scancodes, not PostMessage (PyDirectInput)](https://pypi.org/project/PyDirectInput/)
- [pydirectinput_rgx — scancode SendInput for DirectX titles](https://github.com/ReggX/pydirectinput_rgx)
