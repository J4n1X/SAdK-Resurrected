# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-09 |
| Author (agent/session) | Claude (s39.5, referee-server implementation) |
| Tool to be run | **Part A:** set `config.ADVERTISE_REFEREE_SERVER = True` and run the stub + two clients to the match-start (capture the referee framing, read-only in effect). **Part B:** ALSO set `config.ARM_REFEREE = True` to PUSH `LoginSuccess(0xDCA)`. |
| Tool category | **wire-stub change** (new referee listener :5481; replies `170` instead of `192` to the 2nd type-4 `AssignServer`; advertises a type-4/subtype-5 server; pushes a NEW bare `LobbyMessage` family the stub has never sent — `0xDCA`, `0xDB7/0xDB8`) |
| One-line goal of THIS action | Provide the **Referee Server** the client's match-start gate requires, so a 2-client match clears `RefereeServerConnection::Login` instead of aborting after 5 retries. |

---

## 0. Classification check (why this needs the gate)

- [x] Mutates the stub's **wire behaviour**: stands up a new TCP listener (:5481), changes the reply to the 2nd type-4 `AssignServer(189)` (`192`→`170`), advertises a referee on the type-4 list, and (Part B) PUSHES a new `cat=3` referee `LobbyMessage` (`LoginSuccess 0xDCA`, `RegisterGameAck/Result`).
- [x] NOT achievable read-only: the *test* needs two live clients starting a match; we then verify read-only from `tincat_server.log`, the clients' `comm.log`, and an RPM probe of the gate counter.

> Staging (deliberate, per the workflow's validation gate): **Part A** (advertise + listener, `ARM_REFEREE` off) is *read-only in effect* — it only lets the client connect to our referee and reveal its login framing in the log; it pushes nothing that drives match state. **Part B** (`ARM_REFEREE` on) pushes the `LoginSuccess` the gate awaits. Do A first; it de-risks the one un-nailed byte (the names flag) before B.

---

## 1. The verified model (MODEL BEFORE MUTATION)

Full RE: `docs/REFEREE_RE_findings.json` (6-agent workflow) + `memory/mp-match-start-needs-referee-server.md`. Addresses are **build 34688** (`decomp/sadk/SADK.exe.c`), which **is the running build** (both clients report `AppVer 34688` in `comm.log`).

- **The gate.** On `NE_StartLoading` the client arms a referee login: App-obj `+0x3625 = 1` (do-login), `+0x362c = 0` (attempts), `+0x3628 = 0x10` (countdown). The per-frame loop (`@46171-46200`) calls `RefereeServerConnection::Login` (`FUN_004793f0`) up to **5** times (`[Reconnector] timesClientRetries=5`) then **aborts** the match (`FUN_00429900(2)` + `FUN_0042a640`). — **[PROVEN 0x4316c0 / 0x46171; live: both `comm.log`s show `NE_StartLoading` → ~13 s of pings → `ShutDown`, the abort].**
- **Address assignment.** At LobbyManager state>5 the client sends `AssignServer(189, server_type=4)` (ticket category `0x108`); the lobby must reply `GameServerData(170)` with `server_type=4 && server_subtype=5 && ticket_id` echoed + `server_id/ip/port`. `tincat3 FUN_10021520` gates the referee-assigned observer EXACTLY on `desc.server_type==4 && desc.server_subtype==5`, then `FUN_004625d0` writes `server_id` to `LobbyManager+0x580`. — **[PROVEN tincat3 0x10021830/0x10021520/0x10021520; SADK 0x468f60(@83327)/0x4625d0/0x462910].**
- **Resolution.** `FUN_00462910` inits the referee conn only if `*(LM+0x580)!=0`, resolving `server_id`→ip:port via `pComm` (`FUN_100196b0`, keyed on server_id) — so the referee must ALSO be advertised on the type-4 server-list with the same `server_id`. — **[PROVEN 0x462910; HYPOTHESIS that the type-4 list pre-cache is required vs the assign-170 alone — covered by advertising both].**
- **Login verdict.** Once the referee channel opens, the SERVER pushes one inbound bare `LobbyMessage` `cat=3, id=0xDCA` (LoginSuccess) carrying a `PermID`. The router `FUN_0047b090` switches on the id: `0xDCA`→`FUN_0047ac20` (LoginSuccess; reads PermID, **never validates it**, fires the login-complete fan-out that clears the gate); `0xDCB`→fail. **The verdict is the MESSAGE ID, not any errorcode.** — **[PROVEN 0x47b090/0x47ac20/0x47ad50].**
- **Wire framing.** Referee msgs ride the single `0x26B6` TinCat layer (28-byte header), bodies are bare `LobbyMessage`s (PropertyDataConverter), NOT msgdefs and NOT the `74` envelope. Type word = `names<<15 | cat<<12 | id`; `0xDCA`→`0x3DCA` names-off. — **[PROVEN 0x48fa50/0x48fb00; one GAP below].**
- **⚠ The one un-nailed byte.** The names flag (bit15) is statically undetermined. Primary bet = **names-off** (the client's own send-side `FUN_0048fb00` builds referee msgs names-off) → `0x3DCA` + a bare u32 PermID. Fallback = names-on (`0xBDCA` + name-keyed `PermID` + `0xFFF` end-marker). — **[HYPOTHESIS — resolved by Part-A capture / the Part-B probe].**

**Independent review:** the model was produced by a **6-agent RE workflow with an adversarial synthesis pass** (`docs/REFEREE_RE_findings.json`: `verify.contradictions` resolved the `74`-envelope-vs-bare and port questions; `verify.riskiestAssumptions` flags the names byte). That is the independent re-derivation per `memory/independent-review-protocol-changes.md` for the proven chain; the **one** unproven element (names flag) is explicitly NOT relied upon — Part A captures it and Part B falls back, both verified read-only before any success claim.

---

## 2. Read-only precondition checks (live system is in the EXACT expected state)

| What | Read-only source | REQUIRED | OBSERVED | OK? |
|---|---|---|---|---|
| Match reaches `NE_StartLoading` then aborts | both clients' `comm.log` | StartLoading → no completion → ShutDown | **exactly that** (`sadk_captures/comm_gamestart_2026-06-09.log`, `comm_joiner_2026-06-09.log`) | ✅ |
| Both clients same build | `comm.log` UserInformation | equal `AppVer` + `StatData` | `AppVer 34688`, `StatData 1432091217` both | ✅ |
| No referee assigned today | stub default | stub advertises lobby/UC/world only | `ADVERTISE_REFEREE_SERVER=False` default; no :5481 | ✅ |

```
comm.log (both sides): ... NE_PlayerReady (both) → CloseSession + NE_StartLoading → cb_Ping_Received ×N → ShutDown
  (no NE_*/loaded after StartLoading = the referee-login abort, model §1)
```

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before)

- The subsystem IS in a **wait-for-message** state: after `NE_StartLoading` the client's per-frame loop is calling `RefereeServerConnection::Login` and waiting for the server's `LoginSuccess(0xDCA)` push; with no referee it retries 5× and aborts. — **[PROVEN 0x46171 loop + 0x47ac20 handler].**
- The awaited thing = the referee **LoginSuccess** message; the GENUINE provider is **the referee server sending it** (exactly as a real referee did in 2008). We supply it through the real mechanism (advertise+assign the referee, accept the connection, push `0xDCA`) — we do NOT force a screen/FSM call.
- **Ruling-out statement:** “The game is NOT waiting for something we should fake — it is waiting for the genuine Referee Server, which never existed in our stub; we are *implementing that server*, the real mechanism.” This is the same harness-endorsed pattern as the `EnterWorld(1000)` push, not an `ActivateScreenById`-style force.
- [x] Confirmed: not a wait-state to be satisfied by a forced call — it is satisfied by providing the real server the client dials.

---

## 4. Why this is the GENUINE mechanism, not a shortcut to fake a result

- The referee is a real, mandatory server component of SAdK multiplayer (the ranked-match arbiter). The client itself dials it, runs the real login, and the real referee answered `LoginSuccess`. We reproduce that server. We are not bypassing the client's logic — we are completing the network it expects.
- Where the game itself relies on it: `FUN_004793f0` (Login) + `FUN_0047ac20` (LoginSuccess handler) + the abort path `@46193` — the client's OWN code path is "login to referee or abort"; we make the login succeed via the genuine reply. — **[PROVEN].**
- [ ] (N/A — this is a feature implementation, not a labelled diagnostic.) Honesty caveat: a *cleared gate* is only reported as success once verified read-only per §5; until then it is a hypothesis under test.

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- **Primary observable (cleanest):** with Part B armed, the match proceeds **past** `NE_StartLoading` instead of aborting — the clients' `comm.log` shows the load continuing (no ~13 s-then-`ShutDown`), and the binary no longer logs `"Could not initialize RefereeServerConnection."` in the client log.
- **Precise read-only probe (secondary):** RPM-read the gate counter across the StartLoading window — **success: App-obj `+0x362c` (attempts) never reaches 5 and `+0x3624` (pending) transitions 1→0**; failure: `+0x362c` climbs to 5 then the match aborts. Also read `LobbyManager+0x580` (referee addr) — non-zero = the assignment landed. (Extend `tools/read_village_state.py`-style RPM; offsets build-34688.)
- **Part A observable:** the stub log (`tincat_server.log`) shows the client CONNECTING to :5481 and completing the base login (188/211/213→153), plus any referee frame it sends — this reveals the names-flag convention and whether a pre-login precedes the channel-open.
- **Falsifier:** if `+0x362c` still climbs to 5 with names-off, the framing is wrong → flip `REF_LOGIN_SUCCESS_NAMES=True` (names-on) and re-probe; if BOTH fail, the model's framing is wrong — STOP and capture, do not claim success.

---

## 6. Rollback / blast radius / safety

- Threading: the LoginSuccess push runs on a daemon thread `ENTER_WORLD_DELAY`s after the 153 (mirrors the proven `send_enter_world` pattern); no game-process threads touched (the stub is a separate process).
- Blast radius if the framing is wrong: the client drops/ignores the malformed referee frame → the gate simply doesn't clear → the match aborts as it does today (no NEW failure mode). Worst case = unchanged behaviour. The stub never crashes the game (it only sends frames the client decodes or discards).
- Rollback: set both flags back to `False` → the stub is byte-identical to today (golden + smoke + multi-client + referee tests confirm flag-OFF parity). No persistent state.
- Disposable session: yes — the magazine/retail clients are relaunchable; no user data at risk.

---

## 7. Decision

- [x] Sections 1–6 completed with binary-grounded, read-only evidence.
- [x] The game is NOT in a wait-state we should fake — it awaits the genuine Referee Server, which we implement.
- [x] The expected observable and its read-only verification are defined (gate counter + comm.log).
- [x] A "cleared gate" is reported as success ONLY after read-only verification; until then it is a hypothesis under test.

**Requested of the user:** approve flipping `config.ADVERTISE_REFEREE_SERVER` (Part A) then `config.ARM_REFEREE` (Part B) and running a 2-client match.

> **Pre-approved by J4n1X in-session (s39.5): "Implement it, I give all consent ahead-of-time."** This record documents the model + verification for that standing approval; the flags ship **default-OFF** and are flipped by the user when present to test.
