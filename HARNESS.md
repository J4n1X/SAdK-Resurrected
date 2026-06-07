# HARNESS — Binding Rules of Engagement for the SADK Revival Project

> **Status: BINDING. Not aspirational.** Every AI agent working in this repo — current
> and future — MUST follow this document. It exists to structurally prevent a specific,
> repeated failure: **jumping the gun** — taking state-mutating actions against the live
> game "just to see a result" before the model is verified, and sometimes while the game
> is legitimately *waiting* for something we should instead provide through its real
> mechanism.
>
> This is wired into `CLAUDE.md` (auto-loaded every session) and into the auto-memory
> index (`MEMORY.md`, top priority), and it is **technically enforced**: the
> state-mutating tools refuse to run without an approved Engagement Record (see §6).
>
> If you are an agent and you have not read this in full this session, read it now.

---

## 0. The canonical incident this prevents (read it; internalize it)

An agent built `tools/force_activate_world.py` to inject a remote thread and force-call
`nMenuSystem_ActivateScreenById`, to make the 3D world screen build — and repeatedly
urged the user to "fire it." A subsequent **read-only** probe then proved the game was
simply parked in **LobbyManager state 8 (EnteringVillage)**, legitimately waiting for an
inbound **network msg 1000** to advance to state 9 (`HandleEnterWorld@0x46f470 →
SetState(9)`). The state-8 pump (`FUN_00464c00`) has **no case for state 8** — it is a
pure wait-for-message state. So the forcing was fighting the game's own state machine and
**could never have worked.** (See `memory/world-entry-clean-fix-app-fsm.md` §s36c and
`memory/loading-screen-gate-no-field-poll.md`.)

The lesson is not "that one call was wrong." The lesson is: **we mutated before the model
was verified, and we did not first ask whether the game was waiting for the genuine
mechanism.** This harness makes both of those impossible to skip.

---

## 1. READ-ONLY BY DEFAULT

All diagnosis uses only **non-mutating** means:

- **Ghidra** (the MCP) — decompilation, xrefs, disassembly. Reading only.
- **Elevated `ReadProcessMemory`** probes (`probe_appfsm.py`, `force_onenter_probe.py`,
  `force_observer_probe.py`, `read_village_state.py`, …). `VM_READ` only — cannot crash
  the game, runs safely alongside the debugger.

The game process, the binary, and the wire protocol are **NEVER mutated merely to
observe.** If a question can be answered by reading, it MUST be answered by reading.

When you need a new live fact, your first move is a **read-only probe**, never an
injector. Reach for `tools/probe_appfsm.py` / `read_village_state.py` (or write a new
read-only RPM probe) — not `tools/force_*.py`.

---

## 2. MODEL BEFORE MUTATION

No state-changing action may be **proposed as runnable** until a written,
**binary-grounded mechanistic model** of the relevant subsystem exists, in which:

- every claim is labelled **`[PROVEN]`** (cite a binary address *and* the read-only live
  evidence) or **`[HYPOTHESIS]`** — no bare assertions;
- the model is **independently reviewed**: a *separate* agent re-derives it from the
  binary (Ghidra) rather than echoing the analysis that motivated the action. For ANY
  change to wire format / message layout this review is **mandatory** (see
  `memory/independent-review-protocol-changes.md` — the user calls it "rather crucial").
  Extend it to non-trivial force-call/patch models too: if a wrong byte/offset/address
  would crash the game or silently no-op, get the independent re-derivation first.

"PROVEN" has a hard meaning here: **binary evidence + live read-only evidence.** A thing
that merely "looked like it worked once" is not proven — it is an observation to be
explained.

---

## 3. THE HARD MUTATION GATE

**Definition — "state-mutating action" (any of these):**

- process **injection** / **remote-thread** / **force-call** of a game function
  (`VirtualAllocEx` + `WriteProcessMemory` + `CreateRemoteThread`);
- **thread-hijack** (`Suspend` + `Wow64SetThreadContext` to redirect EIP into a stub);
- **any** `WriteProcessMemory` into the live game;
- **binary patches** (to the live process or to a rebuilt exe) — e.g. NOP-ing a branch,
  rewriting a dispatch slot;
- **any change to the network stub's wire behavior** (new/changed message, changed
  field encoding, changed timing that the client consumes).

**Before ANY such action is even *proposed as runnable*, a mandatory _Engagement Record_
(`templates/ENGAGEMENT_RECORD.md`) MUST be completed and EXPLICITLY APPROVED BY THE
USER.** The record forces you to answer, **with evidence**:

1. **The verified model** — addresses + read-only evidence; `[PROVEN]`/`[HYPOTHESIS]`
   tags; independent review status.
2. **Read-only precondition checks** — the ACTUAL live values (from a probe, now)
   confirming the system is in the **EXACT** state the model requires.
3. **⛔ "Is the game legitimately WAITING for something we should instead provide through
   its real mechanism?"** — with the evidence ruling that out. *This is the exact trap
   from §0 and is a required, evidence-backed section.* If something is being awaited,
   the answer is to **supply it through the genuine mechanism** (have the stub send the
   real message; let the real UI/FSM transition fire), not to force.
4. **Why this is the GENUINE mechanism, not a shortcut to fake a visible result** —
   ideally citing where the game itself performs the same call/transition.
5. **The precise expected observable + how it will be verified READ-ONLY afterward** —
   including what result would *falsify* the model.
6. **Rollback / blast-radius / safety** — contention, crash risk, revert plan, and
   whether it targets a relaunchable / disposable session (the **magazine `SADK.exe`** under
   `tools/debugger_loader.py`; the `SADK_glass.exe` build is RETIRED).

Approval is granted out-of-band by the user (see §6). The Engagement Record is written
**from read-only analysis, before the action** — never backfilled to justify something
already run.

---

## 4. FORCED RESULTS ARE NOT SOLUTIONS

Forcing/injecting/patching to **bypass the game's own logic is FORBIDDEN as a "fix."**

It is permitted **only** as an explicitly-labelled, gated, approved **DIAGNOSTIC probe**,
and **only after ruling out a legitimate wait-state** (§3.3). A diagnostic tells us
*what happens if X*; it does not constitute the feature working.

A visibly "working" forced result **MUST NEVER be reported as success.** If
`force_onenter.py` makes the loading screen disappear, that is the datapoint *"calling
OnEnter dismisses the panel"* — **not** *"world entry works."* World entry works only
when the **genuine in-game path** produces it. State forced results as exactly what they
are: a probe outcome that informs the model.

---

## 5. HONEST STATUS / NO OVER-CLAIMING

- **"PROVEN"** requires binary + live evidence. Everything else is **`[HYPOTHESIS]`** and
  must be labelled so — in records, in memory notes, and in messages to the user.
- Do not launder a hypothesis into a conclusion by repetition or by a single forced
  observation. Report uncertainty honestly. "I believe X but have not proven it" is a
  correct and welcome sentence; a confident wrong claim is the failure mode we are
  killing.

---

## 6. TECHNICAL ENFORCEMENT (the gate actually BITES)

The rule is not honor-system. The state-mutating tools **refuse to run** without an
approved Engagement Record.

- **`tools/harness_gate.py`** is a shared preflight. Each gated injector imports it and
  calls `require_approval("<tool>")` as the **first statement in `main()`**, before it
  opens the process / allocates / writes / spawns a thread. With no valid approval it
  prints a BLOCKED banner and exits `90` — *before any mutation.*
- **Approval token:** `tools/.engagement_approved` (a small JSON). It authorizes **exactly
  one named tool**, references a real, filled Engagement Record, is **time-bounded**
  (default 30 min) and **single-shot** (consumed on first run, so a stale approval can't
  silently authorize a second, different run). It is gitignored — a local, per-action
  capability, not project state.

**Retrofitted (gated) injectors:**

| Tool | Mutation |
|---|---|
| `tools/force_activate_world.py` | remote-thread force-call (the canonical overstep) |
| `tools/force_send2002.py` | remote-thread force-call |
| `tools/force_onenter.py` | main-thread hijack force-call |
| `tools/force_tick_patch.py` | live code-byte patch (the `undo`/rollback path is left ungated) |

**Ungated (read-only) probes** — unchanged, always safe to run: `tools/probe_appfsm.py`,
`tools/force_onenter_probe.py`, `tools/force_observer_probe.py`,
`tools/read_village_state.py`, and any other `ReadProcessMemory`-only tool.

**Carve-out — boot/diagnostic infrastructure (NOT results-chasing world-forcers):**
`tools/map_dispatch_fix.py` and `tools/drm_addr_patch.py` write to the process, but they
exist to make the SecuROM target **boot at all** on Win10/11 (the dead-XP-import fix);
`map_dispatch_fix.py` is auto-applied by `debugger_loader.py` on attach.
`tools/debugger_trace.py` writes INT3 breakpoints as a tracer. Gating these at import
would break the ability to launch/trace the game. They are therefore **left ungated by
default but are still STATE-MUTATING** — using them to *force world-entry behaviour*
(as opposed to booting/tracing) still requires an Engagement Record per §3. *(Open item
for the user: if you want these gated too, say so — see §9.)*

### The only sanctioned way to open the gate

1. **Fill the record.** `cp templates/ENGAGEMENT_RECORD.md
   engagement_records/YYYY-MM-DD_<tool>.md` and complete every section with binary
   addresses + read-only live evidence — including the §3.3 wait-state ruling-out.
2. **Get the user's explicit approval** to run the *named* tool.
3. **Open the gate** (run by the **user**, or by the agent **only** on the user's
   explicit in-session "approved: run `<tool>`"):
   ```
   python tools/harness_gate.py approve <tool> engagement_records/YYYY-MM-DD_<tool>.md
   ```
4. **Run the tool.** It validates + consumes the token, runs once, then the gate closes.

Inspect or close the gate any time:
```
python tools/harness_gate.py status     # what is approved right now (if anything)
python tools/harness_gate.py revoke      # close the gate now
```

> The agent must **never** self-approve to satisfy its own urge to try something. The
> `approve` step encodes the *user's* decision. An agent runs it only to record an
> approval the user has explicitly given this session.

A second, defensive tripwire is a `Stop`-hook reminder in `.claude/settings.json` (§8)
that re-surfaces this gate at the end of turns where mutation language appears.

---

## 7. TRIPWIRES — operationalizing "don't jump the gun"

If you (the agent) catch **yourself or the user** using any of these phrases/urges about a
state-mutating action, **STOP and run the gate** (§3): do not act; instead either run a
**read-only probe** to settle the question, or fill an **Engagement Record** and ask the
user to approve. Red-flag language:

- "fire it" / "let's just fire it"
- "let's just see" / "let's see what happens" / "just to see a result"
- "hit it" / "send it" / "run it real quick"
- "force-call it" / "just force it" / "inject it"
- "quick experiment" / "blind experiment" / "quick test on the live game"
- "try the injector" / "patch it and see" / "nop it and see"
- "just this once" / "it can't hurt to try"
- any urge to run a `tools/force_*.py` (other than a read-only `*_probe.py`) or any
  `WriteProcessMemory`/patch **before** the Engagement Record exists and is approved.

The correct reflex when you feel the pull to "just try it": **that pull is the signal to
go read-only.** Ask "what read-only probe would tell me whether this will work?" and run
*that* instead. Nine times out of ten the probe either answers the question outright or
reveals a wait-state (§0) that makes the forcing pointless.

**Self-check before proposing to run anything that mutates:**
1. Is there a written model with `[PROVEN]`/`[HYPOTHESIS]` tags? (§2)
2. Did a read-only probe confirm the live state matches the model's preconditions? (§3.2)
3. Have I explicitly ruled out a legitimate wait-state with evidence? (§3.3)
4. Is there a filled Engagement Record the **user has approved**? (§3, §6)

If any answer is "no," you do not propose running it. You go back to read-only.

---

## 8. The `.claude/settings.json` Stop-hook (secondary tripwire)

A `Stop` hook prints a short reminder of this gate at the end of each turn (a backstop,
not the primary control — the primary control is the `harness_gate.py` preflight in §6).
It is intentionally lightweight and non-blocking. See `.claude/settings.json`.

---

## 9. Open items the user may decide (explicitly left open)

- **Gate the boot/diagnostic writers too?** `map_dispatch_fix.py`, `drm_addr_patch.py`,
  `debugger_trace.py` are left ungated so the game can boot/trace (§6 carve-out). If you
  want them gated as well (accepting that you'd then approve the gate as part of every
  launch), tell an agent to add `require_approval(...)` to them.
- **Block instead of remind?** The `Stop` hook only *reminds*. Claude Code hooks cannot
  see *which* tool a future Bash call will run, so a hook cannot reliably *block* a
  specific injector — that is precisely why the hard control lives **inside** the tools
  (§6). If you want a coarser block (e.g. a `PreToolUse` hook that flags any Bash command
  containing `force_` and not `_probe`/`undo`), an agent can add it; weigh the false
  positives.
- **TTL / single-shot defaults.** Default approval is 30 min, single-shot. Adjust with
  `--ttl-min N` / `--multi` per approval, or change the defaults in `harness_gate.py`.

---

### TL;DR (pin this)

**Read-only by default. Model (proven vs hypothesis) before mutation, independently
reviewed. No state-mutating action without a completed, user-approved Engagement Record
that explicitly rules out a legitimate wait-state. A forced result is a diagnostic, never
a reported success. The injectors enforce this — they refuse to run without the approved
token.**
