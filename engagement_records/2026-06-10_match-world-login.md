# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-10 |
| Author (agent/session) | Claude (s42, ranked-MP match-start diagnosis; live `tincat_server.log` 2026-06-10 + read-only RE on `sadk_noav.exe`) |
| Tool to be run | New default-OFF flag `config.ANSWER_WORLD_LOGIN_REQUEST = True`, then run the stub. `dispatch._h_send_game_data` answers **each** client `SendGameData(74){0x27D2}` with a fresh **`EnterWorld(1000)`**, bypassing the per-conn `_enter_world_sent` one-shot latch. |
| Tool category | **wire-stub change** (the stub sends an inbound msg 1000 in response to the client's match-start request; today the latch swallows it) |
| One-line goal of THIS action | Answer the client's match-start world-login it is provably waiting for, so it advances past `LeavingVillage(10)` instead of timing out (~80s) and disconnecting. |

---

## 0. Classification check (why this needs the gate)

- [x] This action mutates the **wire protocol** (the stub starts replying `1000` to the match-start `0x27D2`).
- [x] NOT achievable read-only (the *test* requires the client to receive the `1000` and advance; we then verify read-only with a probe + the log + on-screen behavior).

---

## 1. The verified model (MODEL BEFORE MUTATION)

Image base 0x400000, `sadk_noav.exe`. Full model + evidence: `docs/MATCH_WORLD_LOGIN.md`.

- `LobbyManager_SendWorldLoginReq_2002 @0x46bde0` — at match-start the client builds `LobbyMessage(cat=2,
  id=0x7d2)` → wire `0x27D2`, field `"code"=0xAFFEDEAD`, `SetState(LeavingVillage=10)`, sends via
  `conn->vtbl[0xc]`. **[PROVEN — binary]** (constant `-0x50012153`=`0xAFFEDEAD` matches the captured bytes).
  It is invoked through **vtable slot `0x007db914`** (a virtual call), which is why static xref analysis
  called it "dormant"; the live capture proves it fires at match-start. **[PROVEN — live]**
- `VillageServerConnection::HandleEnterWorld @0x46f670` (← `HandleMessage`, msg_type 1000) →
  `SetState(VillageEntered=9)`, reads Worldname(display)/ServerPerm/channels, `JoinChannel`,
  `connState(+0x244)=3`, observer fan-out. **[PROVEN — static]** It does **not** set the world-build gate.
- Build gate is **separate**: per-frame `nMenuSystem_Update_FramePump @0x5da500` fires the build only when
  `nMenu_System+0x7c != 0` → `AppState_EnterWorld_FillDescriptorAndCallOnEnter @0x5d9fd0` (map from
  `+0x68`, not msg 1000). `HandleEnterWorld` does not set `+0x7c`. **[PROVEN — static]**
- Stub bug: `dispatch._h_send_game_data` (dispatch.py:635) detects `0x27D2` → `village.send_enter_world`,
  which one-shot-latches on `_enter_world_sent` (village.py:118), already set by the lobby-entry timer push
  (dispatch.py:590) → **no-op at match-start.** **[PROVEN — live]** (log: detection lines with no send line).

The model in prose:

> At match-start the client re-sends the world-login `0x27D2` on its village conn and parks at
> `LeavingVillage(10)` awaiting the server's `EnterWorld(1000)`. The stub already has the correct
> reply (the same 1000 it sends at lobby entry) but its one-shot latch suppresses the second send, so the
> request goes unanswered and the client disconnects after ~80s. Answering it advances the **LobbyManager**
> state machine (→ 9, connState 3). Whether the 3D **match** world then builds is a **separate** subsystem
> (`nMenu_System+0x7c` / App-transition) this message does not set — that remains the next open gap.

**Independent review:** the msg-1000 **wire FORMAT** (74 envelope + `enter_world_body`) is **UNCHANGED**
from the s35 work independently re-derived from the tincat3 PropertyDataConverter (it is the exact frame the
stub already sends at lobby entry). This action changes only the **TRIGGER** (answer the client's explicit
`0x27D2` vs the lobby-entry timer) and **relaxes the one-shot latch**. No new wire format.
- [x] N/A-new-format (trigger/latch change only); format reviewed s35. **Recommended belt-and-suspenders:**
  spawn a fresh agent to re-derive (a) that the match-start `1000` needs no different content than the lobby
  one, and (b) the `0x27D2`→`HandleMessage`→`HandleEnterWorld` routing — *before* the flip. *(Wire-format
  review is mandatory per the harness; this is a trigger change, but the independent re-derivation is cheap
  and the user calls it "rather crucial" — offered.)*

---

## 2. Read-only precondition checks (live system in the EXACT expected state)

Already observed this session in `tincat_server.log` (2026-06-10); a confirming probe at the live wait-state
is owed at test time.

| What | Read-only source | REQUIRED | OBSERVED | OK? |
|---|---|---|---|---|
| Client sends match-start `0x27D2` | `tincat_server.log` (12:06:27) | `0x27D2 code=affedead`, both conns | exactly that, #4 + #8 | ✅ |
| Stub did NOT answer it | `tincat_server.log` | no `→ EnterWorld(1000) … sent` after detection | none (latch no-op) | ✅ |
| Death is the world-login stall, not the 13s referee abort | `tincat_server.log` | death ≫ 13s | force-close at **+80s** | ✅ |
| LobbyManager state at the stall | `tools/probe_referee_match_start.py` (`LM+0x57c`) — **owed at test time** | `10` (LeavingVillage) | _to read live_ | ⏳ |

```
12:06:27.735  [#4] SendGameData(74){0x27D2 code=affedead}  →  *** → EnterWorld(1000) ***   (no send line)
12:06:27.751  [#8] SendGameData(74){0x27D2 code=affedead}  →  *** → EnterWorld(1000) ***   (no send line)
12:07:47.042  [#4..#8] WinError 10054  (clients disconnected ~80s after the unanswered request)
```

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before) — **YES, and this satisfies it via the real mechanism**

> The canonical overstep: force-calling `ActivateScreenById` while parked waiting for msg 1000. This action
> is the **opposite** — and here the client doesn't just wait passively, it **explicitly requests** the 1000.

- Wait-for-message state? **YES, definitively.** The client SENT `0x27D2` and parked at `LeavingVillage(10)`
  awaiting the server's `EnterWorld(1000)`; with no answer it timed out at ~80s (log). **[PROVEN — live]**
- Genuine provider? **This action IS it.** The server's job is to answer the world-login with `1000`;
  `HandleEnterWorld @0x46f670` is the client's designed handler. We are not injecting / force-calling / patching
  — we send the legitimate server reply to a request the client made.
- **Ruling-out statement:** "The game IS waiting (it sent `0x27D2`, parked at LeavingVillage 10, for msg 1000),
  and this action supplies that exact message through the real wire mechanism — the textbook harness-correct
  response, **strictly more genuine than the prior timer-push** (this answers an actual request)."
- [x] Confirmed: we are **satisfying** the legitimate wait-state via the real mechanism.

---

## 4. Why this is the GENUINE mechanism, not a shortcut

- Answering `0x27D2` with `EnterWorld(1000)` is **exactly what the original world server did** for a world-login
  request; `HandleEnterWorld` is the client's own handler. **[PROVEN]** It **corrects** the prior ER's premise
  ("the `0x27D2` cue is dormant → push on a timer") — at match-start the cue **does** fire, so request-driven is
  the more faithful behavior.
- [x] Honesty clause: reaching `VillageEntered(9)` / stopping the disconnect is the milestone of THIS step.
  Whether the **3D match world renders** is a SEPARATE gate (`nMenu_System+0x7c`, §1) this message does not set.
  A post-9 stall will be reported as **"world-login answered; build trigger is the next gap"**, never as "the
  match loads."

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- Expected: after the flip, the match-start `0x27D2` is followed by a real `→ [VILLAGE] EnterWorld(1000) … sent`
  line; the client advances out of `LeavingVillage(10)`; the conns do **not** force-close at ~80s.
- Read-only verification: `tincat_server.log` (send line present) + `tools/probe_referee_match_start.py`
  (`LM+0x57c`) on both clients + watch the screen.
  - **success (this step):** `1000` sent; `LM+0x57c` leaves 10 (→ 9 or onward); no 80s disconnect; match proceeds.
  - **partial:** state advances but the **3D match world does not build** (loading stalls) ⇒ isolates the
    `+0x7c` / App-transition build trigger as the next gap — NEW INFO, diagnosed read-only (BP on `+0x7c` /
    `OnEnter`), **not** force-fixed here.
  - **failure / no-op:** still disconnects ⇒ the `1000` wasn't accepted (framing/timing/conn identity) ⇒ disarm,
    re-RE.
- FALSIFY: a **crash** on the match-start `1000` push ⇒ the match-start `1000` is NOT framed/templated like the
  lobby one (precondition unmet) ⇒ disarm + investigate (reported as the observed crash, never as success).

---

## 6. Rollback / blast radius / safety

- Threading/contention: **none** — the stub sends one application message; no injection, no remote thread, no
  `WriteProcessMemory`, no binary patch.
- Blast radius: an extra inbound `1000` on the **village** conn, only when the client itself sends `0x27D2`
  (`conn.is_village` + msg_type gate). Lobby/UC/referee conns untouched. Worst realistic case: a client-side
  crash on the match-start `1000` → disarm. The lobby-entry timer push is unchanged.
- Rollback: `config.ANSWER_WORLD_LOGIN_REQUEST = False` (one line) ⇒ wire behavior byte-identical to today
  (golden + server-browser tests unaffected — different flag, default OFF). Instant, complete.
- Disposable/relaunchable: change is in the stub; the game is relaunchable; no user data at risk; no
  `force_*.py` / `harness_gate.py` token involved (not an injector).

---

## 7. Decision

- [x] Sections 1–6 completed with real, binary-grounded **+ live** evidence (the §2 live observations are MET;
  one probe of `LM+0x57c` at the stall is owed at test time).
- [x] **Independent review (s42): re-derived from the binary by a separate agent — verdict ALL SOUND, zero claims
  flawed.** Confirmed the `0x46bde0` sender (cat2/id0x7d2→`0x27D2`, `code=0xAFFEDEAD`, state==8 guard, lone
  vtable xref `0x7db914`), `HandleEnterWorld @0x46f670` using Worldname display-only and never writing
  `nMenu_System+0x7c`, the manual-deserialize path that avoids the `0x3DCA` `CreatePropertySet` crash class, and
  the correct scoping. Risks folded into the impl: re-entry idempotency + ping-pong (→ `WORLD_LOGIN_MAX_ANSWERS`
  cap + cadence log) and scope-honesty.
- [x] The game IS in a legitimate wait-state and this action **satisfies it via the real mechanism** (answers the
  awaited `1000`) — the harness-endorsed response, more genuine than the prior timer-push.
- [x] The expected observable and its read-only verification (send line + `LM+0x57c` + screen) are defined.
- [x] I will report the result as observed; a post-9 loading stall is the build-trigger gap, NOT "the match loads."

**Requested of the user:** with `config.ANSWER_WORLD_LOGIN_REQUEST = True` (now set), run the game + stub through
a match-start with you present and confirm read-only (the `→ [VILLAGE] EnterWorld(1000) … sent` line now follows
each match-start `0x27D2`; `LM+0x57c` leaves `LeavingVillage(10)`; conns do not force-close at ~80s).

> No `harness_gate.py` token is required (stub wire change, not a `force_*.py` injector).

> **✅ APPROVED 2026-06-10 — in-session user go-ahead ("went over both, we can get started, I approve") after
> the independent re-derivation came back SOUND. IMPLEMENTED s42:** `config.ANSWER_WORLD_LOGIN_REQUEST = True`
> (+ `WORLD_LOGIN_MAX_ANSWERS = 8`); `dispatch._h_send_game_data` answers each match-start `0x27D2` with a fresh
> `1000` (force=True, counted + capped); `village.send_enter_world(conn, force=…)` bypasses the one-shot latch.
> Tests: `tests/test_world_login.py` (5/5) + golden + smoke + referee all green; flag-OFF byte-identical.
> **To revert:** set `config.ANSWER_WORLD_LOGIN_REQUEST = False` (one line; safe repo baseline is False).
