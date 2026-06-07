# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-07 |
| Author (agent/session) | Claude (s39, lobby-world-entry diagnosis; live probes probes/*.txt + tincat_server.log) |
| Tool to be run | Set `config.ARM_ENTER_WORLD = True` in `sadk_lobby/config.py`, then run the stub. It pushes **EnterWorld (msg 1000)** on the village conn ~`ENTER_WORLD_DELAY`s after the village 153 ACK. |
| Tool category | **wire-stub change** (the stub pushes inbound msg 1000 UNPROMPTED, which it does not do today) |
| One-line goal of THIS action | Advance the client from `LobbyManager EnteringVillage(8)` → `VillageEntered(9)` (get into the lobby/world) by supplying the msg 1000 it is provably waiting for. |

---

## 0. Classification check (why this needs the gate)

- [x] This action mutates the **wire protocol** (the stub starts pushing inbound msg 1000).
- [x] NOT achievable read-only (the *test* requires the client to receive 1000 and advance; we then verify read-only with the probe).

---

## 1. The verified model (MODEL BEFORE MUTATION)

Image base 0x400000, `sadk_noav.exe`. Chain, with **live** evidence this session:

- Village conn (:5479) login: client sends 188/211/213; stub replies **153 AddResult** → village conn AUTHORIZED.
  **[PROVEN — live]** `tincat_server.log`: `[VILLAGE] ←188/211/213` then `→ SendToken → AckResult(153)`.
- `LobbyManager.state` → **EnteringVillage(8)**. **[PROVEN — live]** `probes/posttryjoin.txt`: `state(+0x57c)=8`.
- The client then **waits for inbound EnterWorld (msg 1000)**; its own world-login request
  (`SendGameData(74){0x27D2}`, `Village_SendEnterWorld_2002 @0x46b990`) never fires (that path is dormant).
  **[PROVEN — live]** log shows no `0x27D2` from the client and `(no EnterWorld push yet)` from the stub → deadlock.
- `VillageServerConnection::HandleMessage` (msg_type 1000) → **`HandleEnterWorld @0x46f670` → `SetState(VillageEntered=9)`**. **[PROVEN static]** (decompile; LobbyManagerState enum VillageEntered=9).
- The stub's `village.send_enter_world` wraps 1000 in the **SendGameData(74)** envelope (the only framing the
  client's inbound bridge routes) with the ground-truthed EnterWorld body. **[PROVEN static + prior live drive]**.

**Independent review:** The msg-1000 **wire FORMAT** (74 envelope + `enter_world_body` Worldname/ServerPerm/
ChatChannelsCount) is **unchanged** from the s35 work that was independently re-derived from the tincat3
PropertyDataConverter (that review caught + fixed the 1006 MEMBLOCK-vs-u32 bug). This action changes only the
**TIMING** (push after the village 153 instead of after the client's dormant 0x27D2) — no new wire format. So
the format mandate is satisfied by the prior review; the timing is justified by the live wait-state evidence (§2/§3).
- [x] N/A-new-format (timing-only change); the format was independently reviewed (s35). *(Happy to spawn a fresh
  re-derivation of `enter_world_body` if you want belt-and-suspenders.)*

---

## 2. Read-only precondition checks (live system in the EXACT expected state) — **MET, observed this session**

| What | Read-only source | REQUIRED | OBSERVED | OK? |
|---|---|---|---|---|
| Login completes over the stub | `probes/postlogin.txt` | ≥ Authorized(3) | **GlobalDataLoaded(7)** | ✅ |
| Client parks at EnteringVillage | `probes/posttryjoin.txt` (`LobbyManager+0x57c`) | **8** | **8 = EnteringVillage** | ✅ |
| Village conn authorized, no 1000 yet | `tincat_server.log` | 153 sent, no 1000 push | exactly that | ✅ |
| CLobby is NOT the driver (won't fight it) | all 3 probes | static | `nCur=3/nReq=-1` throughout | ✅ |
| Stub push code correct | `sadk_lobby/village.py::send_enter_world` | 74-envelope + body | present (s35) | ✅ |

```
probes/posttryjoin.txt:  LobbyManager state(+0x57c) = 8 -> EnteringVillage
                         CLobby nCurrentState=3 nRequestedState=-1   (static -> not the driver)
tincat_server.log:       [VILLAGE] ←188 ←211 ←213 ; → AckResult(153) ;  (no EnterWorld push yet)
```

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before) — **YES, and this action satisfies it via the real mechanism**

> The canonical overstep: force-calling `ActivateScreenById` while parked in **EnteringVillage(8)** waiting for
> an inbound **msg 1000**. This action is the OPPOSITE: it *supplies* the msg 1000.

- Is the subsystem in a wait-for-message state? **YES — definitively, with live evidence.** The client is parked
  at `EnteringVillage(8)` (`probes/posttryjoin.txt`) with the village conn authorized (log), waiting for the
  server to push EnterWorld (msg 1000).
- Can we provide it via the GENUINE mechanism? **YES — that IS this action.** The lobby SERVER's job is to push
  msg 1000; `HandleEnterWorld @0x46f670` is the client's designed handler. We are NOT force-calling a UI/FSM
  function, NOT injecting, NOT patching — we send the legitimate server message the client is waiting for.
- **Ruling-out statement:** "The game IS waiting (EnteringVillage 8, for msg 1000), and this action supplies that
  exact message through the real wire mechanism (the stub being the server) — it is the harness's textbook
  *correct* response to this wait-state, not a force past it."
- [x] Confirmed: we are **satisfying** the legitimate wait-state via the real mechanism.

---

## 4. Why this is the GENUINE mechanism, not a shortcut

- Pushing EnterWorld(1000) is **literally what the original village/world server did**; `HandleEnterWorld` is the
  client's own handler for it. We reproduce real server behaviour. **[PROVEN]**
- The only change vs. today is *when* we push (after the village 153, since the client's `0x27D2` cue is dormant).
- [x] Honesty clause: reaching `VillageEntered(9)` is the milestone; whether the 3D world then **renders** is a
  SEPARATE question (see §5 risk). A forced-looking "in world" will NOT be claimed — only the observed state +
  whether the screen rendered.

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- Expected: after arming, `tools/probe_lobby_world_entry.py` shows `LobbyManager.state = VillageEntered(9)`
  (up from 8), and ideally the loading screen dismisses to the 3D lobby world.
- Read-only verification: re-run `probe_lobby_world_entry.py` (and watch the screen).
  - success: `state = 9` **and** the world renders.
  - partial: `state = 9` but **stuck on the loading screen** ⇒ the **s36 wall** (the world-entered observer
    `villageConn+0x104` empty → `nMenu_Game_OnEnter` never runs; [[loading-screen-gate-no-field-poll]]). This is
    NEW INFO — it would mean state-9 works on the clean build but the render-subscribe step is the next problem,
    to be diagnosed read-only (NOT force-fixed here).
  - failure/no-op: `state` stays 8 (1000 not received/parsed) ⇒ envelope/body wrong → disarm, re-RE.
- FALSIFY: a crash on the 1000 push ⇒ template/timing precondition unmet ⇒ disarm + investigate. (Reported as the
  observed crash, never as success.)

---

## 6. Rollback / blast radius / safety

- Threading/contention: **none** — the stub (our Python server) sends one application message; no injection, no
  remote thread, no `WriteProcessMemory`, no binary patch. The game is an ordinary network peer.
- Blast radius: one inbound msg 1000 on the village conn. The village path is the only one touched (`conn.is_village`
  gate); lobby/UC conns unaffected. Worst realistic case: a client-side crash on the 1000 push → disarm.
- Rollback: `config.ARM_ENTER_WORLD = False` (one line) ⇒ wire behaviour identical to today (golden/server-browser
  tests unaffected — different flag). Instant, complete.
- Disposable/relaunchable: the change is in the stub; the game is relaunchable; no user data at risk; no
  `force_*.py` / `harness_gate.py` token involved (not an injector).

---

## 7. Decision

- [x] Sections 1–6 completed with real, binary-grounded **+ live read-only** evidence (the precondition checks in
  §2 are MET, observed this session — not hypothetical).
- [x] The game IS in a legitimate wait-state and this action **satisfies it via the real mechanism** (pushes the
  awaited msg 1000), the harness-endorsed response — not a force.
- [x] The expected observable and its read-only verification (`probe_lobby_world_entry.py` → state 9 + render) are defined.
- [x] I will report the result as observed; a post-9 loading stall is the observer wall, NOT "world entry works".

**Requested of the user:** approve setting `config.ARM_ENTER_WORLD = True`, then (with you present) run the game +
stub through login → try-join, and re-run `tools/probe_lobby_world_entry.py` to confirm `state = 9` and whether
the lobby world renders.

> No `harness_gate.py` token is required (stub wire change, not a `force_*.py` injector). "Approval" = you,
> present, reviewing this record and flipping `config.ARM_ENTER_WORLD`. Default stays OFF until then.

> **✅ APPROVED 2026-06-07 — in-session user go-ahead ("Approve — I'll test now"). `config.ARM_ENTER_WORLD`
> set to `True` for the live test. To revert: set it back to `False` (one line; repo default is OFF).**
