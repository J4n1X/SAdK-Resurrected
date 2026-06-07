<!--
ENGAGEMENT RECORD TEMPLATE  --  copy this file, do NOT edit it in place.

  cp templates/ENGAGEMENT_RECORD.md engagement_records/YYYY-MM-DD_<tool>.md

Then fill EVERY section below with binary-grounded evidence. This record is the
mandatory precondition for ANY state-mutating action against the live SADK game,
its binary, or the wire protocol (see ../HARNESS.md). The user reviews this record
and only THEN approves the gate:

  python tools/harness_gate.py approve <tool> engagement_records/YYYY-MM-DD_<tool>.md

Rules while filling this out:
  * Every factual claim is tagged [PROVEN] (binary address + read-only live evidence)
    or [HYPOTHESIS]. No bare assertions.
  * "It worked when I tried it" is NOT evidence and NOT allowed here -- this record
    is written BEFORE the action, from read-only analysis only.
  * If you cannot complete a section with real evidence, the action is NOT READY.
    Do not approve. Go back to read-only diagnosis.
-->

# Engagement Record

| Field | Value |
|---|---|
| Date | YYYY-MM-DD |
| Author (agent/session) | |
| Tool to be run | `tools/force_xxx.py` (exact filename) |
| Tool category | injection / remote-thread / thread-hijack / live-binary-patch / wire-stub change |
| One-line goal of THIS action | |

---

## 0. Classification check (why this needs the gate)

- [ ] This action mutates the live game process, the binary, and/or the wire protocol.
- [ ] It is NOT achievable by a read-only RPM probe or a Ghidra read.

If either box is unchecked, you do not need this record — use the read-only path.

---

## 1. The verified model (MODEL BEFORE MUTATION)

State the mechanistic model of the subsystem this action touches. Every claim tagged
`[PROVEN <addr> + <evidence>]` or `[HYPOTHESIS]`. Cite Ghidra addresses (image base
0x400000 for SADK.exe; 0x10000000 for tincat3.dll) and the read-only
live evidence (which probe, what it printed).

- Function(s) this action calls / patches:
  - `0x________` — name — what it does — **[PROVEN/HYPOTHESIS]** (evidence: …)
- Relevant state variables / offsets and their meaning:
  - `obj+0x___` — meaning — **[PROVEN/HYPOTHESIS]** (evidence: …)
- The model in prose (2–6 sentences), distinguishing proven from hypothesized:

> …

**Independent review:** has the model (or the wire-format change) been independently
re-derived from the binary by a separate agent, per
`memory/independent-review-protocol-changes.md`?
- [ ] Yes — verdict: __________ (LOGICALLY SOUND / FLAWED + corrections). Link/summary: …
- [ ] N/A and why: …  *(wire-format changes: review is MANDATORY, not optional.)*

---

## 2. Read-only precondition checks (live system is in the EXACT expected state)

List the read-only probe(s) you ran and the ACTUAL values observed, NOW, on the live
process — not what you expect. The action is only valid if these match the model's
required preconditions.

| What | Read-only source (probe + addr) | REQUIRED value | OBSERVED value | OK? |
|---|---|---|---|---|
| LobbyManager state (+0x57c) | probe_appfsm.py / read_village_state.py | | | |
| (relevant ptr/flag/vtable) | | | | |
| (transport / conn state) | | | | |

Paste the decisive probe output lines:

```
<paste probe_appfsm.py / read_village_state.py / force_*_probe.py output here>
```

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before)

> The canonical overstep: an agent force-called `nMenuSystem_ActivateScreenById` to
> build the 3D world while the game was simply parked in **LobbyManager state 8
> (EnteringVillage)**, legitimately waiting for an inbound **msg 1000** to advance to
> state 9. Forcing fought the game's own state machine and could never have worked.

Answer explicitly, with evidence:

- Is the relevant subsystem currently in a **wait-for-message / wait-for-event** state
  (e.g. a pump with NO case for the current state, a connection awaiting a reply)?
  - Evidence (the pump/handler address + which states it handles, and the live state): …
- If something is being awaited, **what is it, and can we provide it through the game's
  GENUINE mechanism** (e.g. have the stub send the real message; let the real UI action
  fire) instead of forcing?
  - The genuine provider: …  **[PROVEN/HYPOTHESIS]**
- **Ruling-out statement:** “The game is NOT waiting for a message/event we should
  instead supply, because ______.” (Fill the blank with evidence, or STOP.)

- [ ] I confirm the game is not in a legitimate wait-state that the real mechanism
      should satisfy. If you cannot check this box with evidence, **do not proceed.**

---

## 4. Why this is the GENUINE mechanism, not a shortcut to fake a result

- Why is forcing/patching here the right move rather than driving the game's own code
  path (real UI action, real network message, real FSM transition)?
  - …
- If this is the genuine path: cite where the game ITSELF does the same call/transition
  (address + context), so we are reproducing real behaviour, not inventing it.
  - …  **[PROVEN/HYPOTHESIS]**
- If this is explicitly a **diagnostic probe** (not a fix): say so. A forced result here
  will be reported as a DIAGNOSTIC OBSERVATION, never as “world entry works”.
  - [ ] This is a labelled diagnostic, not a claimed solution.

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- Precise expected observable (the ONE thing that confirms the hypothesis):
  - …
- Exactly how it will be checked **read-only** after the action (which probe, which
  address, what value = success vs failure):
  - success: probe `____` shows `____`
  - failure / no-op: probe `____` shows `____`
- What result would FALSIFY the model (so we don't rationalize a non-result):
  - …

---

## 6. Rollback / blast radius / safety

- Threading/contention risk (remote thread vs main-thread hijack; renderer/UI safety):
  - …
- Blast radius if the model is wrong (crash? corrupt state? silent no-op?):
  - …
- Rollback plan (e.g. `force_tick_patch.py … undo`; or “none possible — a wrong call
  may crash; acceptable because the game is relaunchable and no user data is at risk”):
  - …
- Is the target a relaunchable / disposable session — **the magazine `SADK.exe` under
  `tools/debugger_loader.py`** (preferred)?
  - …

---

## 7. Decision

- [ ] Sections 1–6 are completed with real, binary-grounded, read-only evidence.
- [ ] The game is NOT in a legitimate wait-state we should satisfy via its real mechanism.
- [ ] The expected observable and its read-only verification are defined.
- [ ] I will report a forced result as a diagnostic, never as a working feature.

**Requested of the user:** approve running `tools/force_xxx.py` against pid ____ /
the magazine `SADK.exe` under `tools/debugger_loader.py`, once.

> User approval is recorded out-of-band by running
> `python tools/harness_gate.py approve <tool> <this-record-path>`.
> That command — run by the user, or by the agent ONLY on the user's explicit
> in-session “approved: run <tool>” — opens the single-shot gate.
