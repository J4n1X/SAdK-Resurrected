# HANDOFF — pick-up note for the next agent (2026-07-27)

Branch `master`, clean tree. Today built a **new capability** (Time Travel Debugging in the debugger
MCP), used it to map the referee chain, ran **one** stub experiment, and cleanly **falsified** it.
No match yet. Commits: `7883213` (TTD + method research), `2f8411a` (experiment), `4f8da76` (revert).

## Read first
1. `CLAUDE.md` · 2. `HARNESS.md` · 3. `MEMORY.md`
4. **`docs/LIVE_DEBUG_RUNBOOK.md` §9** — TTD: how to record and query. Read before any live work.
5. `engagement_records/2026-07-27_referee-loginsuccess-push-after-153.md` — the falsified experiment
   and the corrected model that came out of it.
6. `docs/RE_METHOD_RESEARCH.md` — why we changed method.

---

## ⭐ The big change: you no longer need a live run to ask a question

**TTD is wired into the debugger MCP and validated end to end.** Record one run, then query the
trace offline, forwards and backwards, as many times as you like, at ~0.4 s per question.

```
ttd_status · ttd_record(mode="attach") · ttd_stop · ttd_list_traces
ttd_calls(trace, "0x432240")      -- did X EVER get called, anywhere in the run?
ttd_memory(trace, "0xE769E68")    -- full write history of ANY address, heap included, with the writing IP
ttd_query(trace, "...")           -- arbitrary dx/cdb, incl. running backwards
```

- Recording needs the debugger server **elevated**; querying does not.
- **A retained 3.9 GB trace of a full match-start already exists:** `~/ttd_traces/matchstart_host.run`
  (host side, 2026-07-27, pre-fix). It is indexed. **Query it before asking for another run.**
- ⛔ **Two traps, both handled in code but know them:** an *unindexed* trace returns **0 results
  instead of erroring** (silent false negative — every query now auto-`!index`es); and `TTD.exe`
  cannot execute from inside `WindowsApps` (auto-copied to `%LOCALAPPDATA%`).
- The running `SADK.exe` is **byte-identical** to Ghidra's `sadk_noav.exe` (sha256 `591731…`), so
  Ghidra addresses map 1:1. Re-verify with a hash if the install ever changes.

---

## ⭐ Corrected referee model (this supersedes everything older)

```
StartLoading (netmgr+0x3cc)
  -> arms referee login       (screen+0x3624 pending, +0x3625 arm, +0x3628 delay, +0x362c try-count)
  -> LobbyGameScreen_Update@0x00435980 calls RefereeServerConnection::Login@0x004793f0
  -> SERVER answers LoginSuccess(0xDCA)
  -> RefereeServerConnection +0x80 observer
  -> Lobby_HostRegisterGameWithReferee@0x00432240   (no direct callers — installed at 0x00435269)
  -> RegisterGame(0xDB6) -> we answer Ack(0xDB7) + Result(0xDB8, GameSeed)
```

After **5** failed tries (`screen+0x362c`) the pump **aborts the match** via `NComm_Manager_Shutdown`.

**The referee login belongs to MATCH START, not to login.** The server's job is to *answer* it —
`referee.handle_frame` already does. Today's experiment pushed `LoginSuccess` unprompted after the
referee conn's base-login 153; it was **inert** (LobbyGameScreen has not entered yet, so nothing is
subscribed to `+0x80`) and has been reverted.

### What the 2026-07-27 trace proved (all live, all re-queryable)

| fact | how |
|---|---|
| `RegisterGame` never called | `TTD.Calls(0x432240) = 0` |
| `RequestRefereeServer` never called in-window (it is a **login-time one-shot**, latched `+0x584`) | `TTD.Calls(0x468f80) = 0` |
| referee never ready: `InitRefereeServerConnection` on **19/19** pump ticks | `TTD.Calls(0x462910) = 0x13` = `StatePump_Tick` |
| `LobbyManager+0x580` (`nRefereeServerId`) = **0**, with **zero writes** in-window | `ttd_memory` |
| referee assign callback `ServerList+0xa4/+0xa8` still armed at 5% **and** 90% (`+0xa8 = 0x004625D0`) | `ttd_memory` |
| state `9 VillageEntered` → `11 VillageLeft`; `CLobby_RequestExitVillage` ×1; `DeleteResultReceived` ×1 | `TTD.Calls` |
| the stub **does** answer `AssignServer(189,4/4)` and the client **does** dial `:5481` and base-auth | `minisrv:stub_n.out` |

⚠️ `LobbyManager+0x580` reading 0 with zero in-window writes is **not yet reconciled** with the fact
that the client dialled `:5481` at 10:40 (which requires `+0x580 != INVALID` at that moment). Either
it was reset before the window, or the readiness predicate differs. **Resolve this before theorising.**

---

## ▶ Start here next session — no new game run required

**Query the existing trace** (`matchstart_host.run`) for the upstream question:
*does the host ever reach `StartLoading`, or does it leave the village first?*

1. `ttd_calls(trace, "0x00435980")` — did `LobbyGameScreen_Update` run at all, and how often?
2. `ttd_memory` on `netmgr+0x3cc` (**StartLoading**) — is it ever set? `FUN_00408290()` returns the
   net-manager; get its live pointer from the trace, then watch `+0x3cc`.
3. `ttd_memory` on `screen+0x3624` / `+0x3625` / `+0x362c` — is the referee-login pump ever armed,
   and does the 5-try counter reach the abort?

That triage decides everything: if StartLoading never fires, the referee is a red herring and the
real wall is whatever makes the host exit the village instead. Our trace already shows it reaching
`VillageLeft(11)` — so that is the live suspicion.

## Also open
- `referee.py::_u32` packs **little-endian**; unproven for BitStream LobbyMessage fields. Matters for
  `GameSeed`, less for `LoginSuccess` (client checks the message id, not the PermID value).
- `OnLoginSuccess` reads its field via `LobbyMessage_SelectField(msg, "PermID", 0)` — **by name**.
  Our `type_word()` sends `names=0`. Worth confirming whether the wire must carry names.
- The developer log-scope strings (`docs/RE_METHOD_RESEARCH.md` Part 1) are a real but *smaller*
  win than first claimed — many are already named. Value is the `(file, line)` map, not the count.

## Environment
- Stub live on `linux-server`, ports 7070/7071/5479/5481, **reverted code**, logging `stub_n.out`.
  Previous run's logs: `stub_reflogin.out` (the falsified experiment), earlier `stub_n.out` (pre-fix).
- Ghidra `sadk_noav.exe` open; today's names/comments saved (`Reconnector_RestartAsServer_DoAction`
  @0x0040b700, plate comments on 0x00432240 and 0x0040b700).
- Debugger server was running **elevated** for TTD recording. Game closed by the user ~11:02.
