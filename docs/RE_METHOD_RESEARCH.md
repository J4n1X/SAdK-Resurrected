# Method research — how to stop losing sessions to live-test roulette

**Date:** 2026-07-27 · **Status:** research findings + recommended plan. No stub or wire changes.
**Trigger:** repeated live tests that cost a full human-driven host+join+Start cycle and return one
bit of information, often "no".

Status tags in this document are honest per `HARNESS.md §4`:
**[PROVEN-ARTIFACT]** = verified in this repo's own artifacts, right now, and shown below ·
**[EXTERNAL]** = documented capability of a third-party tool, not yet tried here ·
**[HYPOTHESIS]** = plausible, explicitly unverified.

---

## Part 0 — Why we are stuck (diagnosis before prescription)

The wall is not that the protocol is hard. It is that **our experiment loop has a terrible
information-per-unit-of-effort ratio.** Three distinct failure modes, all visible in the last
several sessions:

1. **One run answers one question.** Each live test costs a human several minutes of
   launching, logging in, hosting, joining, readying and pressing Start — and is designed to
   confirm or deny *a single hypothesis*. A protocol state space does not get explored one bit
   at a time.
2. **The evidence is not re-queryable.** When the run ends, the state is gone. A new question —
   even an obvious follow-up like "OK, but did `RegisterGame` ever get called?" — costs another
   full run. We are paying full price for every question.
3. **We repeatedly re-derive things we already have.** Proven twice in the last two sessions:
   the entire match-start chain was sitting unread in `minisrv:stub_gsassign.out` from an earlier
   session, and — see Part 1 — the developers' own function names have been sitting in
   `decomp/sadk/SADK.exe_strings_uniq.txt` in this repo the whole time.

There is a fourth, subtler one worth naming because it burned a multi-session investigation:
**building a model on an unverified base.** The `this = ServerList+8` trap made correct live reads
look like they refuted a correct model, and spawned a hunt for a sixth writer of `+0x9c` that does
not exist.

**The reframe:** stop asking "what experiment confirms hypothesis H?" and start asking **"what
capture makes every future question cheap?"** Ordered by cost, cheapest first.

---

## Part 1 — Tier 0: harvest what the developers already left in the binary (free, no live run)

This is the headline finding of this research cycle, and I verified it against our own artifacts
rather than taking it on faith.

### 1.1 The binary contains a developer-authored, fully-qualified symbol table [PROVEN-ARTIFACT]

`decomp/sadk/SADK.exe_strings_uniq.txt` contains **217 strings** of the exact form
`Namespace::Class::Method`, plus **36 source-file path strings** (`.\LobbyManager.cpp`,
`.\LobbyRefereeServerConnection.cpp`, `.\LobbySetupGameDialog.cpp`, `.\Private\CLobby.cpp`, …).

They are not decoration. Every instrumented function opens with an **RAII log-scope prologue**.
From `decomp/sadk/SADK.exe.c` (`LobbyComm::ServerList::GameServerAssigned`):

```c
_DAT_0088592c = 399;                                            // <- __LINE__, into a global
FUN_004035d0(".\\LobbyVillageServerList.cpp", 0x1c);            // <- __FILE__      (len 28)
FUN_004035d0("LobbyComm::ServerList::GameServerAssigned", 0x29);// <- __FUNCTION__  (len 41)
FUN_00462e50(local_48);                                         // <- scope ctor, level 4
```

**Why this reading is proven, not guessed:** the second argument of `FUN_004035d0` is the exact
byte length of the string in every case — `0x1c` = 28 = `len(".\LobbyVillageServerList.cpp")`,
`0x29` = 41 = `len("LobbyComm::ServerList::GameServerAssigned")`, `0x22` = 34 and `0x30` = 48 and
`0x43` = 67 for the referee triples. So `FUN_004035d0` is a `std::string` assign(ptr,len), and
`FUN_00462e50` is a scope object constructed from (file, line, function) that calls
`FUN_00467f40(this, 4)` — a severity/level argument.

### 1.2 Three separate payoffs, all free

**(a) Mass symbol recovery — but the payoff is smaller than the raw count suggests.**
A Ghidra script (`run_script_inline` — HARNESS-legal) can walk every function, match the prologue
shape, and rename it from its own embedded string. That is up to ~217 exact, developer-authored
names.

> **⚠️ CORRECTED 2026-07-27, after checking against the live program.** A meaningful share of these
> are **already named** from prior sessions — e.g. `RefereeServerConnection::RegisterGame` was
> already `RefereeServerConnection_RegisterGame`. So "217 free names" overstates the delta against
> our ~150 hand-ported ones; the true new-name yield is unmeasured and likely much smaller. **The
> value was not the bulk rename.** It was that the string list named a handful of *unexplored*
> functions sitting directly on the open leads — which is exactly what paid off (see below).
> If the sweep is run, do it for the `(file, line)` map in (b), not for the name count.

It also settles open naming debts: `CLobby_RequestExitVillage` is currently an **inferred** name
flagged `[TODO]` — the string table is the place to confirm or kill it.

**(b) A source-tree map for free.** Each instrumented function carries its `.cpp` *and* its line
number. Sorting recovered functions by `(file, line)` reconstructs the original module layout —
which functions were neighbours in the developers' source. We currently rebuild that structure by
hand, one xref at a time.

**(c) The intended API surface — which speaks directly to both open leads.** Extracted now:

```
LobbyComm::RefereeServerConnection::  Login · LoginSuccessReceived · LoginFailedReceived ·
    RegisterGame · RegisterGameAcknowledgeReceived · RegisterGameResultReceived ·
    ClaimChest(+Acknowledge/Result) · FinishGame(+Acknowledge/Result) · GiveUpGame(+Acknowledge) · Logout
LobbyComm::ServerList::  GameServerAdded · GameServerAssigned · AssignGameServerResultReceived ·
    CreateResultReceived · DeleteResultReceived · UpdateResultReceived · KickResultReceived ·
    GameServerDataReceived · StartObservationResultReceived · StopObservationResultReceived ·
    RequestTANConnectionResultReceived · TANConnectionGranted
NComm::Manager::  StartUpNetwork · Reconnector_RestartAsServer_DoAction · AddClientGameEventsToServerGameEvents
NComm::TinCatReconnector::  cb_BecameServer · cb_ReconnectTo
```

Three things jump out of that list, unprompted:

- **`RegisterGame` is the referee verb we have never seen fire.** Open lead #1 is "no
  `AssignServer(189)`, nothing dials `:5481`". The intended lifecycle is evidently
  `Login → RegisterGame → Acknowledge → Result`. We have been reasoning about the referee from
  the assign side; the register side is a named, unexplored half.
- **`RequestTANConnectionResultReceived` / `TANConnectionGranted` exist on `ServerList`.**
  `MEMORY.md` records that TAN is a SAdK addition absent from base DNG. A "TAN connection" being
  *granted* on the ServerList is a plausible match-transport we have not modelled at all.
  (Caveat: `TANConnectionGranted` decompiles to a logging-only stub in this build — see 1.4.)
- **`Reconnector_RestartAsServer_DoAction` + `cb_BecameServer`.** The known teardown wall is
  "`FUN_004389d0` Shuts down the net-driver and `StartUpNetwork` is never called again". Here is a
  named function whose entire job appears to be *restarting as server*. That is a direct candidate
  for the thing that is supposed to rebuild the transport after the lobby tears it down.

None of that required a live run. It required grepping a file we already had.

### 1.3 The game writes its own log file [PROVEN-ARTIFACT, enablement UNVERIFIED]

The string table also contains `%s\Logfile_%d.txt`, `%s\Logfile_0.txt` and `\comm.log`. `comm.log`
is already known-good — `mp-host-join-ready-start-works-wall-match-load` was proven with it.

**If** the lobby log scopes reach a file sink at their severity, the client will narrate its own
match-start in developer terms, with file and line, with **no debugger, no breakpoints, and no
fragile live attach**. That is the single highest-value unknown in this document.

- Prefer enabling it the legitimate way: config file, command line, env var. That is using the
  real mechanism, exactly as `HARNESS.md §2` wants.
- If the only route is flipping a level/sink global, that is a **state-mutating action** and needs
  a user-approved Engagement Record. It is instrumentation, not a bypass — but the gate still
  applies, and per §4 anything obtained under a patch is a **diagnostic**, never reported as a
  working result.

### 1.4 Caveats on Tier 0, stated plainly

- The strings dump and `.c` dump are from **`SADK.exe`**, while the active RE target is
  **`sadk_noav.exe`** (`decomp/RE_PRACTICES.md`). Same source, different build — names transfer,
  **addresses do not**. Re-anchor by string/xref, per `porting-decomp-to-sadk-noav-method`.
- The 96 scope-constructor call sites in the `.c` dump reflect only the functions that were
  exported to that dump, not the whole binary. The real count is whatever the Ghidra sweep finds.
- `TANConnectionGranted` is already annotated in our dump as a logging-only stub with no state
  change in the clean build. So "TAN is the answer" is **[HYPOTHESIS]**, and a weak one on current
  evidence — the *interesting* half is `RequestTANConnectionResultReceived`, which we have not read.

---

## Part 2 — Tier 1: make one live run answer unlimited questions (Time Travel Debugging)

> **STATUS 2026-07-27 — ✅ BUILT AND VALIDATED END TO END.** The §3 gate was cleared by the
> maintainer. TTD is installed and wired into the **debugger MCP** as `ttd_*` tools (not a
> standalone script, per §1). Proven on a recorded 32-bit process: recording works, `cdb -z` does
> open `.run` traces, `ttd_calls` returns per-call time/return/thread, and `ttd_memory` returns the
> full write history of a **non-module-mapped** address *with the writing instruction pointer* —
> the capability §4 watchpoints refuse. Queries take ~0.4 s once indexed.
> **One `ttd_memory` query would have replaced the entire multi-session `+0x9c` writer hunt.**
> Two traps found and neutralised on the way (both `[PROVEN]`, both in the runbook): `TTD.exe`
> cannot be executed from inside `WindowsApps`, and an **unindexed trace returns 0 results instead
> of erroring** — a silent false negative. Runbook: `docs/LIVE_DEBUG_RUNBOOK.md` §9.

This is the direct antidote to failure modes 1 and 2.

**What it is [EXTERNAL].** Microsoft's TTD records every instruction a process executes into a
`.run` trace, then replays it forwards *and backwards*, arbitrarily many times, offline. x86 32-bit
is supported. It is distributed with WinDbg, and `TTD.exe` can also be installed standalone as a
command-line recorder for automation.

**Why it changes this project's economics.** The trace is a *queryable database of the run*:

```
dx @$cursession.TTD.Calls("sadk_noav!LobbyComm::RefereeServerConnection::RegisterGame")
dx @$cursession.TTD.Memory(0x0E6A45C4+0x9c, 0x0E6A45C4+0xa0, "w")
```

- The first answers "did `RegisterGame` *ever* fire, and when?" over the **whole session**, in
  seconds — the exact shape of open lead #1.
- The second answers "who wrote `+0x9c`, in order, with call stacks" — the precise question that
  cost a multi-session investigation and that the old plan wanted a hardware watchpoint for, which
  the debugger MCP **rejects on heap addresses**. TTD has no such limitation because it is not
  using a watchpoint at all.

One recorded host+join+Start would let us re-ask every question in this document, plus the ones we
have not thought of yet, without touching the game again.

**Costs and risks, honestly [EXTERNAL]:**
- ~10–20× slowdown while recording; traces reach multiple GB in minutes.
- **The real risk for us is multiplayer timing**: a 10–20× slowed host may time out the joiner and
  manufacture a fake "stuck" state — precisely the failure mode already recorded in
  `dbgeng-breakpoint-vs-loader-conflict`. Mitigation: record the **host only**, and use
  *attach*-mode to start recording immediately before pressing Start rather than tracing the whole
  session.
- Requires elevation (already true here). TTD transparently survives `IsDebuggerPresent`-class
  checks, and we are on the SecuROM-free magazine build anyway.

**Harness fit — this needs the `HARNESS.md §3` gate, and here is the stated reason.** The Ghidra
MCP debugger provides breakpoints and non-freezing function traces, but it is strictly *live*:
every question must be decided before the run, and an unanticipated follow-up costs a whole new
session. It cannot answer retrospective questions, cannot run backwards, and explicitly cannot
watch heap memory. TTD provides exactly those. §1 already prescribes the correct shape:
**"if a debugging capability is missing, add a debugger MCP; do not write a script."** So the
proposal is to extend the existing debugger MCP with record/replay backed by `TTD.exe` and headless
`cdb.exe -z <trace>.run -c "<dx query>"` — not a standalone RE script.

---

## Part 3 — Tier 2: let the binary tell us where working and broken diverge (coverage diffing)

**The technique [EXTERNAL].** Record executed basic blocks with DynamoRIO's `drcov`, then load and
**diff** two coverage sets in Ghidra via **Dragon Dance** (native drcov support, built-in trace
diffing) or **Cartographer** (NCC Group). The divergence point between a working run and a failing
run shows up as a concrete set of basic blocks.

**Why it suits us specifically.** We are unusually rich in *working comparators* — most RE projects
have none:
- lobby-world entry **works** (milestone 1, screenshot-confirmed);
- single-player match load **works**;
- MP match start **fails**.

Diffing SP match-load against MP match-start should localise "what does the working path execute
that the broken path never reaches" without any hypothesis at all. That is a fundamentally
different epistemics from our current loop: it does not require us to guess right first.

**Caveats.** Also a new tool → §3 gate, same as above. Coverage tells you *where* execution
diverged, not *why*; it is a pointer, not an explanation. And basic-block callbacks can fire
slightly early/late, so treat single-block deltas as leads rather than proof.

---

## Part 4 — Tier 3: systematic instead of sequential (protocol state fuzzing)

**The technique [EXTERNAL].** Active automata learning (Angluin's L*, via LearnLib) infers a
protocol implementation's state machine by driving it with generated message sequences and
observing responses. It is established practice for TLS, DTLS, OpenVPN and Bluetooth stacks.

**Applicability here: real but limited.** We are in the ideal structural position — we own the
server, so we control the entire input alphabet the client sees. But the binding constraint in this
project is **not** message generation; it is that a human must click the client through host → join
→ ready → Start for every episode. Automata learning assumes cheap, resettable episodes. Ours cost
minutes of human attention. Building the learner before automating the reset would be effort spent
in the wrong place.

**What to take from it anyway — this part is free.** The *principle* transfers even without the
framework: **make the harness enumerate, not the human.** Concretely, design each live run as a
multi-hypothesis experiment with pre-registered predictions, rather than a single yes/no probe.

---

## Part 5 — Discipline changes that cost nothing and adopt immediately

Tools are half of it. These are the process changes the recent sessions actually argue for:

1. **Artifact-first rule.** Before spending a live run, grep the artifacts we already hold. Twice
   now the answer was already on disk — the match-start chain in old stub logs, the symbol table in
   the strings dump. Make this a checklist item, not a virtue.
2. **Pre-register the prediction.** Before the run, write down what each outcome would mean and
   what would *falsify* the model. A run whose every outcome is explainable teaches nothing.
3. **One run, many questions.** Never spend a human cycle on a single bit. Arm the full trace set.
4. **Verify the base before quoting an offset.** Check for secondary vtables. When a live value
   contradicts the model, suspect the base before the model.
5. **Named ≠ verified.** Keep the distinction visible in the artifact itself, as
   `CLobby_RequestExitVillage`'s plate comment now does.

---

## Part 6 — Learning resources (the "how to get good at this" half of the question)

Closest analogues and genuinely useful sources, roughly in order of relevance to *this* project:

- **"Cyber Necromancy: Reverse Engineering Dead Protocols"** — Tartaro & Halchyshak (31C3 /
  ToorCon 16 / BruCON 2015). Reviving Metal Gear Online's servers **after** shutdown, with no live
  server to observe. That is our exact problem statement, by people who finished. Highest-value
  single item on this list.
- ***Attacking Network Protocols*** — James Forshaw (No Starch). The standard text on protocol
  capture, analysis and structure inference.
- ***Practical Malware Analysis*** — Sikorski & Honig. Not about games; it is the best structured
  grounding in Windows dynamic analysis, WinDbg, and anti-analysis, which is the skill we keep
  needing.
- **"Deep Dive into Game Network Protocols"** (Shalzuth) and the **Game Server Protocol Archive** —
  practitioner writeups on exactly this genre.
- **Microsoft TTD documentation**, especially the object-model/queries pages, and **Elastic Security
  Labs' TTD ecosystem deep dive** for how the recorder actually works.
- **"Protocol state fuzzing of TLS implementations"** (USENIX Security '15) and the LearnLib
  ecosystem, for the systematic-exploration mindset in Part 4.
- **Troopers "Reverse Engineering a (M)MORPG"** training syllabus — a good outline of the full
  skill chain (dissectors, async proxies, binary RE) if you want a curriculum rather than a book.

---

## Part 7 — Recommended plan

Ordered by value-per-effort. **Steps 1–2 need no new tools, no live run, and no ER.**

| # | Action | Cost | Gate |
|---|---|---|---|
| 1 | Ghidra script: sweep the log-scope prologue, auto-rename every instrumented function from its own string; record `(file, line)` per function | one Ghidra session | none — `run_script_inline` is HARNESS-legal |
| 2 | Read the newly-named `RefereeServerConnection::RegisterGame` + `ServerList::RequestTANConnectionResultReceived` + `NComm::Manager::Reconnector_RestartAsServer_DoAction` statically; find their callers and guards | static only | none |
| 3 | Determine whether the logger's file sink can be enabled via config/CLI/env | static + config read | none, unless it needs a patch → **ER** |
| 4 | Propose the TTD extension to the debugger MCP; record one host+join+Start; answer leads 1 and 2 offline | tool build + 1 run | **§3 stated-reason gate** (drafted in Part 2) |
| 5 | Coverage-diff SP match-load vs MP match-start | tool build + 2 runs | **§3 gate** |

**The single most important consequence of this research:** steps 1–3 plausibly answer both open
leads outright, cost zero live runs, and were available the entire time. Do them before building
any new tooling.

---

## Sources

- [TTD overview](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-overview) ·
  [TTD.exe CLI](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-ttd-exe-command-line-util) ·
  [TTD object model / queries](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-object-model) ·
  [TTD queries](https://learn.microsoft.com/en-us/archive/blogs/windbg/time-travel-debugging-queries) ·
  [Recording a trace](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/time-travel-debugging-record)
- [Elastic Security Labs — Deep dive into the TTD ecosystem](https://www.elastic.co/security-labs/deep-dive-into-the-ttd-ecosystem) ·
  [ttd-bindings](https://github.com/commial/ttd-bindings) ·
  [Binary Ninja TTD support](https://docs.binary.ninja/guide/debugger/dbgeng-ttd.html)
- [DynamoRIO drcov](https://github.com/DynamoRIO/dynamorio/tree/master/clients/drcov) ·
  [Code coverage with DynamoRIO](https://vuln.dev/code-coverage-with-dynamorio/) ·
  [Dragon Dance](https://github.com/0ffffffffh/dragondance) ·
  [Cartographer](https://github.com/nccgroup/Cartographer)
- [Cyber Necromancy — 31C3 (media.ccc.de)](https://media.ccc.de/v/31c3_-_5956_-_en_-_saal_2_-_201412281400_-_cyber_necromancy_-_joseph_tartaro_-_matthew_halchyshak) ·
  [BruCON 2015 abstract](http://2015.brucon.org/index.php/Cyber_Necromancy:_Resurrecting_the_Dead_(Game_Servers))
- [Protocol state fuzzing of TLS implementations](https://dl.acm.org/doi/10.5555/2831143.2831156) ·
  [State machine inference for security protocols](http://www.cs.ru.nl/~joeri/StateMachineInference.html) ·
  [Survey of network protocol fuzzing](https://arxiv.org/html/2402.17394v1)
- [Reverse Engineering: Deep Dive into Game Network Protocols](https://shalzuth.com/Blog/DeepDiveIntoGameNetworkProtocols) ·
  [Game protocol archive](https://github.com/lan-dot-party/game-protocols) ·
  [Reverse Engineering Network Protocols](https://jhalon.github.io/reverse-engineering-protocols/) ·
  [Troopers — Reverse Engineering a (M)MORPG](https://troopers.de/troopers18/trainings/drqcyk/)
