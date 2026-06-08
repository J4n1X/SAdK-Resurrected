# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-08 |
| Author (agent/session) | Claude (s39.5, game-hosting scaffolding) |
| Tool to be run | Set `config.MULTI_CLIENT_HOSTING = True` in `sadk_lobby/config.py` (optionally also `ADVERTISE_GAME_SERVERS = True`), then run the stub with **two** clients (a host + a joiner on distinct LobbySettings accounts). |
| Tool category | **wire-stub change** (serves a 2nd player's identity; relays one client's hosted game to another client; hands the joiner the host's address in 222) |
| One-line goal of THIS action | Let two DISTINCT players connect, one host a game via `AddGameServer(168)`, the other SEE it in BrowseGameDialog and JOIN it (`221`→`222` with the host's address) — i.e. make the *matchmaking + join-handoff* layer work cross-client. |

---

## 0. Classification check (why this needs the gate)

- [x] This action mutates the stub's **wire behaviour**: a 2nd connection is served a different `perm_id`/char (not always perm 1 / Testler), and a 170 GameServerData for client A's hosted game is sent to client B (a message B does not receive today), and `222 ConnectionData` returns the host's address.
- [x] NOT achievable read-only: the *test* requires two live clients exchanging real frames. (We then verify read-only from `tincat_server.log` + `sadk_captures/`.)

> Scope honesty up front: this enables **matchmaking + the join address handoff**. It does **NOT** populate the pre-match game ROOM (map / settings / the 6 player slots). That room/slot state is a **separate, later, separately-gated** layer — see §1 "scope" and §5.

---

## 1. The verified model (MODEL BEFORE MUTATION)

All wire layouts below are **[PROVEN]** from the game's own schema `sadk_lobby/data/msgdefs.ini` (the authoritative NETMSG definitions tincat3 loads). This change touches **field VALUES and routing only** — no field encoding / message layout is altered (the codec is untouched; the golden test stays byte-for-byte).

- **`AddGameServer(168)`** carries `ip`/`port`/`server_type`/`server_subtype`/`max_players`/`map`/`room_id`/… — **[PROVEN msgdefs NETMSG_TYPE_168]**. The host registers its game; the lobby assigns a `server_id` and acks `AddResult(153)`.
- **`GameServerData(170)`** carries `server_id`/`owner_id`/`ip`/`port`/`server_subtype`/`max_players`/`cur_players`/… — **[PROVEN msgdefs NETMSG_TYPE_170]**. This is the list entry other clients receive; `server_subtype=1` routes it to the game list (BrowseGameDialog) — **[PROVEN, live s39d]** (subtype-1 validated on screen).
- **`RequestConnectionData(221)`** `{perm_id, server_id}` → **`ConnectionData(222)`** `{perm_id, server_id, ip, port, nonce, errorcode}` — **[PROVEN msgdefs NETMSG_TYPE_221/222]**. The joiner asks for the selected game's address; the lobby returns it.
- **Identity**: `SessionKey(207)` carries `perm_id`; the client then presents that `perm_id` on its UC + village conns via `SendToken(213).perm_id` — **[PROVEN msgdefs 207/213; live]** the single-client flow already works with `perm_id=1`. So resolving the lobby conn by the auth-blob `username` and the UC/village conns by the token `perm_id` maps all three sockets of one client to one player.

**The change, mechanically:**
1. `players.py` resolves `conn.player` per login (lobby→username, UC/village→token perm_id; auto-registers unknown usernames). `PLAYERS[0]` == the old hardcoded test identity, so a single client on account `test` is **byte-identical** to today.
2. `registry.py` is a process-global, thread-safe game store. `168/169/177` write it (tagged with the owning conn id); `166/171` and `221` read it, so client A's game is visible to and joinable by client B. On disconnect the owner's games are dropped.
3. Both behaviours are gated by `config.MULTI_CLIENT_HOSTING`; with it OFF the old per-connection / single-identity path runs unchanged.

**⛔ Scope / what this does NOT do (honest):** the pre-match ROOM state — map, settings, and the 6 player slots (occupant/tribe/team/color/ready) — is **not** any lobby NETMSG. I verified the full `msgdefs.ini`: `166–177` are server-list, `240–251` are UC chat channels, `252–262` are ranking — **none carry player slots**. So the room/slot state rides the **direct host↔joiner game connection** (the original 2008-LAN P2P design), like the 1000-series world protocol over `SendGameData(74)`. **[HYPOTHESIS — P2P game connection]**, under independent read-only RE this session (host-listener / 222-consumer / room-source). Flipping this flag therefore gets the joiner to the point of **receiving the host's address and dialing the game connection**; the room then opens empty (the known next gap, s39d). That next layer is a **separate** change with its **own** ER.

**Independent review:** This is a wire-**behaviour** (values + routing) change, NOT a wire-**format/layout** change — every touched message keeps its msgdefs encoding (proven by the golden byte-for-byte test). The mandatory independent re-derivation in `memory/independent-review-protocol-changes.md` is scoped to *format/layout* changes and is therefore not triggered here; the authoritative source for all touched messages is `msgdefs.ini` itself. Offered if you want belt-and-suspenders on the routing logic.

- [x] N/A — no new/changed wire **format**; field encodings unchanged (golden test byte-for-byte). Values/routing only, grounded in `msgdefs.ini`.

---

## 2. Read-only precondition checks

| What | Read-only source | REQUIRED | OBSERVED | OK? |
|---|---|---|---|---|
| Single-client default wire unchanged | `tests/test_codec_golden.py` | byte-for-byte 170 | **PASS** (this session) | ✅ |
| Flag OFF keeps per-conn isolation + default identity | `tests/test_server_browser.py`, `tests/test_multi_client.py` | unchanged | **PASS** | ✅ |
| Multi-client logic correct (offline) | `tests/test_multi_client.py` | A's game visible+joinable by B; cleanup | **PASS** | ✅ |
| 168/170/221/222 handlers already in use live | `tincat_server.log` (s15/s28/s38/s39d) | exist + exercised | yes | ✅ |
| BrowseGameDialog lists subtype-1 games | s39d screenshots | subtype 1 shows | yes | ✅ |

```
test_codec_golden.py      → test_170_matches_legacy_byte_for_byte  PASS
test_multi_client.py      → hosted game visible + joinable cross-client; owner cleanup  PASS
test_server_browser.py    → default subtype 0 (OFF) / subtype 1 (ON), village data block unchanged  PASS
```

**Owed live preconditions (these ARE the test):** (a) two clients with distinct LobbySettings accounts (`test`, `test2`); (b) the host's SetupGameDialog **Create** actually emits a `168` (s39d confirmed the dialog opens; the 168 emission is to be confirmed in the capture — if Create sends no 168, host registration must be re-RE'd).

---

## 3. ⛔ Is the game legitimately WAITING? (THE trap that was hit before)

- Is anything in a wait-for-message state that we are about to **force past**? **No — this action does not force anything.** There is no injection / remote-thread / patch / `WriteProcessMemory`. The stub answers the client's own requests (`166/171/221`) and relays a host's own `168`, all through the genuine lobby wire protocol.
- The honest wait-state that REMAINS (and that this action deliberately does **not** fake): after the joiner dials the game connection, it waits for the host/server to push the **room state** — which the stub does not send yet. We are **not** papering over that with a forced result; we scope this action to matchmaking + handoff and leave the room push as a separate, evidence-gated step. The decisive read-only **capture of that very wait** is the verification in §5.
- **Ruling-out statement:** "We are not forcing past a wait-state; we are supplying the genuine matchmaking responses the client requests. The remaining room-state wait is explicitly out of scope here and will be satisfied through its own real mechanism once RE'd — not forced."
- [x] Confirmed: no force; the only changes are genuine lobby responses + cross-client routing.

---

## 4. Why this is the GENUINE mechanism, not a shortcut

- `168/170/221/222` **are** the game's documented lobby matchmaking protocol (`msgdefs.ini` is the client's own schema). A real lobby served each account its own `perm_id` and relayed hosted games between clients — that is exactly what this does. **[PROVEN — msgdefs + the existing, live-validated single-client flow]**.
- No UI/FSM function is force-called; no binary is patched. The clients drive their own code paths; the stub just answers.
- [x] This is the genuine matchmaking layer, not a diagnostic. (The game-connection/room layer it leads into IS still partly hypothesis and will be treated as such — see §5.)

---

## 5. Expected observable + how it is verified READ-ONLY afterward

With `MULTI_CLIENT_HOSTING = True` (+ `ADVERTISE_GAME_SERVERS = True`), host on client A (account `test`), join on client B (account `test2`):

- **Expected:** A creates a game (SetupGameDialog → Create) → `tincat_server.log` shows A's `AddGameServer(168)` → registry. B opens SPIEL SUCHEN → B's `166/171` → a `170` carrying A's game (name/map/owner) → B's BrowseGameDialog lists **A's** game. B selects it + Beitreten → B's `221` → stub `222` with A's address → **B's client opens a new connection to that game address** (the capture).
- **Read-only verification:** `tincat_server.log` + `sadk_captures/*.bin`:
  - success (matchmaking): log shows A's 168, B's 170-with-A's-game, B's 221→222; B's BrowseGameDialog shows A's game on screen.
  - **the decisive capture:** the new connection B opens after 222 — what it dials and the first frames it sends/receives — reveals the game-connection/room-slot protocol (the next layer). If B dials the host directly (P2P) it won't hit the stub; route it through the stub for capture (see the recipe — set the host's advertised address to the stub, or have the stub return its own address in 222).
- **FALSIFY:** B's BrowseGameDialog does **not** show A's game ⇒ the relay/visibility model is wrong (re-RE the 170 routing). A's Create emits **no** 168 ⇒ host registration assumption wrong (re-RE SetupGameDialog Create). A served identity is wrong (B logs in as Testler/perm 1) ⇒ resolution bug.

A populated room or a started match will **NOT** be claimed from this action — this action's success is strictly: two identities, cross-client visibility, and the join address handoff (+ the capture). Anything beyond is the next, separate layer.

---

## 6. Rollback / blast radius / safety

- Threading/contention: **none** — pure Python stub responses; no injection, no remote thread, no `WriteProcessMemory`, no binary patch. The clients are ordinary network peers.
- Blast radius: with the flag **OFF**, zero (golden test = byte-identical). With it **ON** and a single client on account `test`, still byte-identical (resolves to perm 1 / Testler). New behaviour only manifests with a 2nd distinct account / 2 clients. Worst realistic case: a client is served the wrong identity or sees a stale game → relaunch the client; revoke the flag.
- Rollback: `config.MULTI_CLIENT_HOSTING = False` (one line) ⇒ wire behaviour identical to today; `registry`/`players` paths dormant. Instant, complete.
- Disposable/relaunchable: yes — the magazine `SADK.exe` under `tools/debugger_loader.py`; no user data at risk; no `force_*.py` / `harness_gate.py` token involved (this is a stub wire change, not an injector).

---

## 7. Decision

- [x] Sections 1–6 completed with msgdefs-grounded + offline-test evidence; the live preconditions in §2 are the test itself and are stated honestly as owed.
- [x] No force / injection / patch — only genuine lobby matchmaking responses + cross-client routing. The remaining room-state wait is explicitly out of scope, not faked.
- [x] The expected observable + read-only verification (log + capture) are defined, including what falsifies the model.
- [x] I will report only what is observed: identities + visibility + the join handoff (+ the capture). A populated room / started match will not be claimed here.

**Requested of the user:** approve setting `config.MULTI_CLIENT_HOSTING = True` (and `ADVERTISE_GAME_SERVERS = True`), then — with you present — run two clients (host `test`, join `test2`) through host → browse → join, and let the stub log + capture the result (the join handshake is the next-layer evidence).

> No `harness_gate.py` token is required (stub wire change, not a `force_*.py` injector). "Approval" = you, present, reviewing this record and flipping the flag(s). Default stays OFF until then.
