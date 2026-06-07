# CLAUDE.md — auto-loaded instructions for every agent in this repo

> This file is loaded into **every** session. Read the two pointers below before doing
> any work. The first is non-negotiable.

---

## ⛔ MANDATORY: read `HARNESS.md` (rules of engagement) before touching the live game

**`HARNESS.md`** (repo root) is the **binding** harness that governs all work here. It
exists to prevent a repeated, costly failure: **jumping the gun** — taking state-mutating
actions against the live game "just to see a result" before the model is verified, and
sometimes while the game is legitimately *waiting* for something we should instead provide
through its real mechanism (the canonical case: force-calling `ActivateScreenById` while
the game was parked in **LobbyManager state 8** waiting for inbound **msg 1000**).

You MUST follow `HARNESS.md` in full. The essentials, inlined so you cannot miss them:

### The non-negotiables

1. **READ-ONLY BY DEFAULT.** Diagnose only with Ghidra (reads) and elevated
   `ReadProcessMemory` probes (`tools/probe_appfsm.py`, `tools/read_village_state.py`, the
   `*_probe.py` tools). Never mutate the game/binary/wire-protocol merely to observe. When
   you want a new live fact, reach for a **read-only probe**, not an injector.
2. **MODEL BEFORE MUTATION.** No state-changing action until a written, binary-grounded
   model exists with every claim tagged **`[PROVEN]`** (binary address + live read-only
   evidence) or **`[HYPOTHESIS]`**, and independently reviewed (mandatory for any wire
   format change — see `memory/independent-review-protocol-changes.md`).
3. **HARD MUTATION GATE.** Any *state-mutating* action — process injection / remote-thread
   / force-call, **any** `WriteProcessMemory`, live or rebuilt **binary patches**, or any
   change to the **network stub's wire behavior** — requires a completed
   **Engagement Record** (`templates/ENGAGEMENT_RECORD.md`) that the **USER explicitly
   approves** *before* the action is even proposed as runnable. The record must answer,
   with evidence: the verified model; read-only precondition checks; **"is the game
   legitimately WAITING for something we should instead provide through its real
   mechanism?"** (the exact past trap — rule it out with evidence); why this is the
   genuine mechanism not a shortcut; the expected observable + read-only post-check;
   rollback/blast-radius.
4. **FORCED RESULTS ARE NOT SOLUTIONS.** Forcing/injecting/patching to bypass the game's
   own logic is **forbidden as a "fix."** It is allowed only as a labelled, gated,
   approved **diagnostic**, and only after ruling out a wait-state. A visibly "working"
   forced result is **never** reported as success.
5. **HONEST STATUS.** "PROVEN" needs binary + live evidence; everything else is
   `[HYPOTHESIS]` and is labelled so. No over-claiming.

### TRIPWIRES — stop-and-run-the-gate phrases

If you catch **yourself or the user** saying any of these about a mutating action — **"fire
it", "let's just see", "let's see what happens", "hit it", "send it", "force-call it",
"just force it", "inject it", "quick experiment", "blind experiment", "patch it and see",
"nop it and see", "just this once", "it can't hurt to try"** — or you feel the urge to run
a `tools/force_*.py` (anything other than a read-only `*_probe.py`) before an approved
Engagement Record exists: **STOP.** Do not act. Instead run a **read-only probe** to settle
the question, or fill an Engagement Record and ask the user to approve. *The pull to "just
try it" is itself the signal to go read-only.*

### Technical enforcement (the gate bites)

The state-mutating injectors **refuse to run** without an approved Engagement Record. They
call `require_approval(...)` from **`tools/harness_gate.py`** at startup and abort (exit
90) unless `tools/.engagement_approved` authorizes that exact tool. Gated:
`force_activate_world.py`, `force_send2002.py`, `force_onenter.py`, `force_tick_patch.py`.
Read-only `*_probe.py` tools are ungated. To open the gate (only after the user approves):

```
python tools/harness_gate.py approve <tool> engagement_records/<your-record>.md
python tools/harness_gate.py status      # inspect what's approved
python tools/harness_gate.py revoke       # close the gate
```

Never self-approve to satisfy your own urge to try something — the `approve` step records
the **user's** decision, run only on their explicit in-session go-ahead.

---

## Project onboarding: read `AGENTS.md`

**`AGENTS.md`** (repo root) is the stable overview: goal, architecture, the lobby
protocol, file roles, the Win11 SecuROM fix, and tooling. `docs/archive/SESSION_STATUS.md` is the
archived session log; `docs/ROADMAP.md` is the plan. Persistent cross-session memory is auto-loaded from
`MEMORY.md` (start there) — its **top entry points at the harness**.

## Project conventions

- **git uses `master`, not `main`.** (See `memory/prefers-master-branch.md`.)
- Consult **`memory/msgdefs-ini-authoritative.md`** first for any lobby message — the
  game's own NETMSG schema overrides RE guesses.
- The maintainer is a game-domain expert; trust their in-game instincts (one of which —
  "is the game waiting for something earlier?" — was exactly right and is now codified in
  the harness's wait-state check).
