# Live debug runbook — the standing instrument

> **Why this exists.** For several sessions the test loop was: *guess → ship a stub wire-change → drive the
> GUI by hand → describe a symptom → infer backwards.* Three shipped changes in a row were falsified, and
> each cost a full play-through plus a revert. This runbook replaces that with **observation**: the client
> is a state machine we can read directly, so most questions should be answered **without changing the
> stub at all**.
>
> Everything here runs through the sanctioned Ghidra/debugger MCP — no standalone scripts (`HARNESS §1`).

---

## 0. Prerequisites

- Debugger backend up (elevated, on the machine running the game):
  `cd C:\Users\user\Downloads\ghidra-mcp && python -m debugger`   → binds `127.0.0.1:8099`
- Game running (any state; the probe works even when disconnected).
- Ghidra MCP connected with `sadk_noav.exe` open.

## 1. Attach (every session)

1. Find the pid — `Get-Process -Name SADK`.
2. `debugger_attach(target=<pid>)`.
3. **Sync the module map** — required every attach, or all module-relative calls fail with
   *"not in any mapped module"*:
   ```
   POST http://127.0.0.1:8099/debugger/sync_modules
   {"ghidra_bases": {"SADK": "0x400000", "tincat3": "0x10000000"}}
   ```
   (Runtime module names are `SADK` / `tincat3`; the Ghidra program is `sadk_noav.exe`. Bases are 1:1.)
4. Resume with `POST /debugger/go` when done arming.

**Gotchas learned the hard way**
- The MCP's `debugger_resume` / `debugger_interrupt` target Ghidra Trace-RMI, **not** this backend. Use
  `POST /debugger/go` and `POST /debugger/interrupt`.
- `debugger_attach` fails with *"Cannot attach in state stopped"* if a previous (dead) target is still
  held — `POST /debugger/detach` first.
- Setting a breakpoint while the target is running can time out; interrupt first. The request often lands
  anyway — check `breakpoint_count` before retrying.

## 2. The state probe (read-only, no freeze, ~5 reads)

Walk the chain. **The LobbyManager address is stable for the process lifetime; everything below it is not
— re-walk each time.**

```
g_pLobbyManager  = *(0x00885890)
  +0x54   LobbyComm_ServerList      (embedded)
  +0x140  world-stream/loader        (embedded)
  +0x2f8  LobbyWorldStreamHandler    (embedded)
  +0x3bc  LobbyPostOffice            (embedded)
  +0x3d8  UserCommConnection         (EMBEDDED — its address IS LM+0x3d8; vtable 0x007DCECC)
  +0x490  RefereeServerConnection    (embedded)
  +0x540  pVillageConnection         (POINTER; vtable 0x007DB8D4)
  +0x544  pGameSlotConnection        (POINTER)
  +0x550  selected village server id (50 = our stub's village)
  +0x57C  ***LobbyManager.state***
  +0x580  nRefereeServerId

<any LobbyComm connection>
  +0x34   transport  (CommLayer::ConnectionReal, vtable 0x10051694) — NULL when disconnected
  +0x1c   observer list: LoggedOut      → fired by BaseConnection::LoggedOut@0x0048e2a0
  +0x28   observer list: Disconnected   → fired by BaseConnection::Disconnected@0x0048e3c0

<transport (ConnectionReal)>
  +0x08   ***transport state***  (GetState@0x10036bd0 is literally `return *(this+8)`)
  +0x1c   server id
  +0x24   net-driver / socket wrapper
  +0x38   state observer (its vtbl[0x0C] is a no-op stub for our connection)
```

### `LobbyManager.state` (+0x57C) values
| val | name | set by |
|---|---|---|
| 1 | Disconnected | Initialize / OnLoginFailed / OnLoggedOut(main) |
| 2 | Connecting | Login, `FUN_004633f0` |
| 3 | Authorized | OnLoggedIn |
| 4 / 5 / 6 / 7 | version-check → global-data ladder | StatePump_Tick, OnVersionChecked |
| 8 | EnteringVillage | `0x0047063e` |
| 9 | **VillageEntered** | HandleEnterWorld (msg 1000) |
| 10 | **LeavingVillage** | SendLeaveVillageRequest_2002 (msg 2002) — **has no self-recovery** |
| 11 | **VillageLeft** | HandleLoggedOut **or** HandleDisconnected — the ONLY two exits from 10 |
| 12 | LobbyConnectionLost | OnConnectionLost (main conn) |

### transport state (+0x08) values
`0` none · `2` connecting · `5`/`6`/`7` handshake ladder · **`8` authorized** · **`9` logging out**

### ⭐ The single most important rule this instrument encodes
`FUN_10030ad0` (ConnectionReal event handler) **case 4 = disconnect** branches on transport state:

| transport state at disconnect | result |
|---|---|
| **8** | `ConnectionLost` with a **hardcoded reason 10** → `!CONNECTION_LOST_TEXT` dialog |
| **9** | **`OnLoggedOut`** → `HandleLoggedOut` → `VillageLeft(11)` → `+0x1c` observer → **arms the referee** |

State 9 is set **only** by `ConnectionReal::Logout@0x10030510`, which is called only from
`HandleWorldLoginAck` (msg 1006), `UserCommConnection::Logout@0x0047ed70`, and
`RefereeServerConnection_Logout@0x00479540`.

### Worked example (2026-07-26, validated live)
```
*(0x885890)      = 0x0E5C9040   LobbyManager
  +0x57C         = 0x0C  (12)   → LobbyConnectionLost  ← client was disconnected
  +0x540         = 0x0E5C95F0   village conn (vtable 0x007DB8D4 ✓)
      +0x34      = 0x00000000   transport NULL          ← consistent with state 12
  +0x3d8         = 0x0E5C9418   UserComm conn (vtable 0x007DCECC)
```
That took ~4 reads and replaced "it seems odd" with an exact diagnosis.

## 3. Standing trace set (non-freezing)

`debugger_trace_function` logs each call **with arguments and auto-resumes in ~0.5 ms** — invisible at
25 fps. This is the right tool: ordinary breakpoints freeze the client, which times out a joiner and
manufactures fake "stuck" states (that contamination wrecked an earlier session).

Read hits with `debugger_trace_log()`; stop with `debugger_trace_stop`.

| # | address | module | conv | args | what it tells you |
|---|---|---|---|---|---|
| 0 | `0x00462540` `LobbyManager::SetState` | SADK | `__thiscall` | `newState` | **every** lobby state transition, with the value. The backbone. |
| 1 | `0x004647e0` `OnConnectionLost` | SADK | `__thiscall` | `connId,p2,reason` | the **reason code** (10 = dialog) |
| 2 | `0x0046bde0` `SendLeaveVillageRequest_2002` | SADK | `__thiscall` | — | the client asked to leave |
| 3 | `0x0046ec50` `HandleWorldLoginAck` | SADK | `__thiscall` | `msgStream` | msg 1006 arrived → the Logout branch |
| 4 | `0x10030510` `ConnectionReal::Logout` | tincat3 | `__fastcall` | — | **state → 9** (the good path) |
| 5 | `0x00470e20` `HandleLoggedOut` | SADK | `__thiscall` | `arg` | the exit we want |
| 6 | `0x00470f90` `HandleDisconnected` | SADK | `__thiscall` | `arg` | the exit that shows a dialog |
| 7 | `0x10030ad0` `ConnectionReal` event handler | tincat3 | `__thiscall` | `eventType,p2` | `eventType==4` = disconnect |

A single play-through with these armed yields an ordered event timeline instead of a symptom report.

## 4. Watchpoints — limitation

`debugger_watch_memory` only accepts **module-mapped** addresses; heap addresses are rejected
(*"not in any mapped module"*), so `LobbyManager+0x57C` and `transport+0x08` **cannot** be watched
directly. Trace their *writers* instead — trace #0 (`SetState`) and #4 (`Logout`) cover every transition
that matters. Reserve real watchpoints for globals in `.data`.

## 5. Correlating with the stub

The stub logs unbuffered (`python -u`) to `~/projects/sadk-resurrected/stub*.out` on `linux-server`
with millisecond timestamps; trace hits are timestamped too. Line the two up to see *"client sent 2002 at
T, we answered at T+2 ms, client did X at T+40 ms."*

## 6. Method note — trust order

When static and live disagree, **live wins**. This session alone, static shape-matching produced three
false positives (a `GetState`/`OnLoggedOut` slot collision at `+0xc`, message-factory calls at the same
offset, and a five-arg `vtbl[0x10]`), the stack unwinder produced garbage frames twice, and an
operand-filter search silently returned zero matches for an instruction that demonstrably exists. The
logout mechanism was finally found by **stepping**, not sweeping.

Corollary: prefer reading `[ESP]` at a function's *entry* over any stack trace — and remember tail-jumps
(`CLobbyClient::LeaveVillage` tail-jumps into the 2002 sender, so `[ESP]` there holds *its caller's*
return address, not its own).

---

## 7. Wire endianness — the rule, and the audit (2026-07-26)

A little-endian/big-endian mix-up silently disabled msg 1006 for months with **no visible symptom**
(the client's `if (code == 0xDEADBEEF)` simply never matched, so the whole handler body was skipped).
After fixing it, every integer the stub puts on the wire was audited. The rule:

| layer | endianness | proof |
|---|---|---|
| **NETMSG** (`msgdefs.py` / `codec.py`) | **little** (`fmt = "<" + …`) | login, server browser and room config all carry `UNLONG` fields and work end to end |
| **TinCat framing** — envelope `msg_type`, MEMBLOCK length prefix, type words | **little** | the client's own msg-2002 frame, captured byte-exact: `… d2 27 00 00 │ 04 00 00 00 │ …` |
| **TinCat property VALUES** (scalars inside a LobbyMessage/PropertySet) | **BIG** | same frame: `code=0xAFFEDEAD` → wire `af fe de ad`; independently, `MEMORY.md` records the ServerDataBlock `roomId` as a big-endian u32 |
| **MEMBLOCK payload bytes** | raw, unswapped | `enter_world_body`'s 32-byte channel-count block (first dword = N) works as a raw dword; EnterWorld renders |

**Audit results — one real bug, since fixed:**
- `village.world_login_ack_body` (msg 1006 `code`) — was little-endian. **THE bug.** Fixed → big-endian,
  regression-guarded by `test_1006_code_is_big_endian`.
- `dispatch.py` ServerDataBlock `roomId` — already `>I`. Correct.
- `village.gamedata_frame` envelope `msg_type`, `enter_world_body`, `pong_body` (echoes the client's
  token raw), `world_tick_body` — correct.
- `chat.py`, `connection.py` (`status_with_id` → AddResult 153), `crypto.py` — NETMSG layer, correct.

**`[TODO]` Latent, NOT currently harmful — `referee.py`.** Its `_u32()` packs *property values*
little-endian, which is wrong by the rule above. It does not bite today:
`RefereeServerConnection_OnRegisterGameResult@0x0047a580` reads `GameID` but **never compares it**; its
only branch is `if (Result == 0)`, and `Result = 0` is byte-order symmetric; `GameSeed` is byte-swapped
but our fixed constant swaps identically for every client, so lockstep still agrees; `PermID` in
LoginSuccess is ignored (the client gates on the message id). Deliberately **left unchanged** — the
referee path has never been exercised end to end, so changing an untested encoding on an inference could
introduce a fresh bug we have no way to detect. Fix it *when* that path is first driven for real, and
verify with a trace at that time.

**Method note:** a wrong scalar encoding fails *silently* — the handler runs, the compare fails, and the
body is skipped, so it looks exactly like "the hypothesis was wrong". If a message provably reaches its
handler but nothing happens, check the encoding before abandoning the theory.
