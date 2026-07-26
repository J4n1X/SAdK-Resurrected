# Match-start world-login (`0x27D2` → `EnterWorld(1000)`) — model

> ## ⛔ CORRECTED 2026-07-25/26 — READ BEFORE USING THIS DOC
>
> **The core prescription of this document is WRONG.** Msg **2002** (`0x27D2`, `code=0xAFFEDEAD`) is a
> **LEAVE-VILLAGE request**, not a world-login request: `VillageServerConnection_SendLeaveVillageRequest_2002
> @0x46bde0` calls `SetState(LeavingVillage=10)` and waits. Answering it with `EnterWorld(1000)` tells the
> client to *enter* the lobby world when it asked to *leave* — that is the origin of the "clone" (both
> clients reloading the lobby world at match-start). **Do not answer `0x27D2` with `1000`.**
>
> Live-proven 2026-07-25: the stub receives the frame and no-ops it; the client parks in
> `LeavingVillage(10)` and retries forever (no timeout, no disconnect).
>
> Also **do not** "fix" it by closing the village connection: that reaches `VillageLeft(11)` but fires the
> **Disconnected** observer (`villageConn+0x28` → `LobbyGameScreen_OnGameConnectionResult@0x432ed0`),
> producing an `!ERROR_DIALOG` / `!CONNECTION_LOST_TEXT` and never arming the referee. `[PROVEN]`
>
> What legitimately clears `LeavingVillage(10)` is **still unknown** — see `decomp/RENAME_LIST.md`
> (2026-07-25/26 entries) for the full evidence chain and the open question.

> **s42 (2026-06-10), ranked MP live test + read-only RE on `sadk_noav.exe` (image base 0x400000).**
> Status discipline: every claim tagged **[PROVEN]** (binary addr + read-only/live evidence) or
> **[HYPOTHESIS]**. This doc is the model behind `engagement_records/2026-06-10_match-world-login.md`.

## TL;DR

At **match-start** (host clicks Start → game delisted), **both** clients re-send the world-login
`SendGameData(74){msg_type=0x27D2, code=0xAFFEDEAD}` on their existing village conn and wait for the
server's `EnterWorld(1000)`. **This refutes the long-standing "the client's `0x27D2` cue is dormant /
never comes" model** — it was true at *lobby* entry, **false at match-start**. The stub *detects* the
request but its `EnterWorld(1000)` is **one-shot per conn** and already fired on the lobby-entry timer,
so it **no-ops** — the client's genuine request goes unanswered → ~80s timeout → disconnect. The fix is
to **answer each `0x27D2` with a fresh `EnterWorld(1000)`** (request-driven, the genuine mechanism).
Caveat: that advances the **LobbyManager** state machine; it does **not** statically trigger the 3D
**match-world build** (a separate `nMenu_System+0x7c` gate), which remains the next open gap.

---

## 1. What the live ranked test showed [PROVEN — live, `tincat_server.log` 2026-06-10]

Two-machine ranked match (conn `#4` = host-side village, conn `#8` = joiner `test2`). Timeline:

| Time | Event |
|---|---|
| `11:59:56.514` | stub pushes `EnterWorld(1000)` on **#4** (lobby-entry timer, +2s after 153) → `_enter_world_sent=True` for #4 |
| `12:05:40.993` | stub pushes `EnterWorld(1000)` on **#8** (lobby-entry timer) → `_enter_world_sent=True` for #8 |
| `12:06:27.727` | conn #5 → `RemoveServer(server_id=100)` — game delisted, **match starting** |
| `12:06:27.735` | **#4** → `SendGameData(74){0x27D2, code=affedead}`; stub logs `→ EnterWorld(1000)` — **no send line follows** |
| `12:06:27.751` | **#8** → same `0x27D2`; stub logs `→ EnterWorld(1000)` — **no send line follows** |
| `12:07:47.042` | all conns force-closed (WinError 10054) — clients gave up ~**80s** after the unanswered request |

Decisive contrast: the lobby-entry pushes have a real `→ [VILLAGE] EnterWorld(1000) … sent on conn #N`
line; the two match-start detections have **none**. The match-start `EnterWorld(1000)` was **swallowed by
the one-shot latch**. Death at **80s, not the ~13s referee abort** — with `ARM_REFEREE` on this run, the
match cleared the referee and stalled here.

The frame (identical from both clients):
```
b6 26 4a 00 4a 00 d2 27 00 00 04 00 00 00 af fe de ad
magic 0x26b6 | t1=74 | t2=74 | msg_type=0x27d2 | memblock len=4 | code = AF FE DE AD
```

## 2. Binary mechanism — the client SENDS `0x27D2` at match-start [PROVEN — binary + live]

`VillageServerConnection_SendLeaveVillageRequest_2002 @0x46bde0`:
- Guards `connState (conn+0x34 →vtbl[0xc]) == 8` (authorized/in-village); else returns false.
- `LobbyMessage(cat=2, id=0x7d2)` → wire type word **`0x27D2`** = `(2<<12)|0x7d2`.
- Field `"code"` = `WriteInt(-0x50012153)` = **`0xAFFEDEAD`** (matches the captured bytes exactly).
- `LobbyManager::SetState(LeavingVillage=10)`, then sends via `conn->vtbl[0xc]`.

**Why memory called this "dormant":** its only xref is **DATA from a vtable slot `0x007db914`** — it is
invoked through a **virtual call** Ghidra can't resolve statically, so static xref analysis reported "no
analyzed caller." The live capture proves the vtable slot **is** invoked at match-start. **[PROVEN]** The
`[[world-entry-server-push-1000-not-missing-sink]]` / `village.py` "send-2002 is dormant, the cue never
comes" claim is therefore **CORRECTED**: dormant at lobby entry, **live at match-start**.

## 3. The server's reply path [PROVEN — binary]

`VillageServerConnection::HandleMessage @0x470890`-equiv (xref) → `HandleEnterWorld @0x46f670`:
- `LobbyManager::SetState(VillageEntered=9)`.
- Reads `Worldname` (display only; `<UNNAMED>` fallback), `ServerPerm` (stored, not validated),
  `ChatChannelsCount` + channels (rebuilds the chat-channel map at `this+0x168`).
- `UserCommConnection::JoinChannel`, sets `connState(this+0x244)=3`, `SendPing`, observer fan-out
  `FUN_004760c0`.
- **It does NOT touch `nMenu_System` or any world-build trigger.** `Worldname` is cosmetic here. **[PROVEN]**

So a pushed `1000` drives the **LobbyManager** state machine (8/10 → 9, connState 3, chat) — nothing more.

## 4. World-build gate verification — does `1000` build the 3D match world? [PROVEN static — NO, not directly]

The 3D world build runs through `nMenu_Game::OnEnter` (vtbl[0x84]), reached by **two** entry points,
**neither set by `HandleEnterWorld`**:

1. **Per-frame `+0x7c` gate** — `nMenuSystem_Update_FramePump @0x5da500`: tail `if (this->+0x7c != 0)
   AppState_EnterWorld_FillDescriptorAndCallOnEnter(@0x5d9fd0)`. That consumer fills the GameLoadDescriptor
   — **map name from `nMenu_System+0x68`** (NOT from msg 1000), builds the player/team slot list — then
   calls `nMenu_Game::OnEnter`. `+0x7c` is **not cleared** in the pump (external setter). **[PROVEN]**
2. **App state transition** — `App_ProcessStateTransition (req==1)` → `AppState_ActivateWorldScreen_CallOnEnter
   @0x5d9f10`: activate Game screen + `OnEnter` (descriptor assumed already filled). This is the s40
   **host** path (`[[mp-world-build-trigger-chain-proven]]`: FreeGamePanel Start → … → this). **[PROVEN]**

`HandleEnterWorld` (msg 1000) sets **neither** `+0x7c` nor the App transition req. The only conceivable
bridge is the generic EnterWorld observer fan-out `FUN_004760c0` (walks a runtime-registered observer list,
calls `observer[3](arg)`); its observers are **not statically enumerable**, so whether any sets `+0x7c`
**can only be settled live** (BP on `+0x7c` write / `OnEnter` during match-start). **[HYPOTHESIS — open]**

**Conclusion:** pushing the match-start `1000` is **necessary** (fills the client's actual wait-state,
stops the 80s disconnect, advances LobbyManager → 9) but **not statically proven sufficient** to build the
3D match world. The joiner's build trigger (`+0x7c` setter / `App` transition) is the **next open gap**,
unchanged from `[[world-build-model-clean-binary]]`.

## 5. Referee relationship [PROVEN static / live]

- The referee login is armed for **every non-observer MP match-start** — `LobbyGameScreen_OnVillageConnectionLoggedOut
  @0x4316c0` arms `+0x3624/+0x3625` gated only on a player/observer predicate + `Manager+0x3cc`
  (StartLoading flag); **no `RankedGame` branch**. The pump `LobbyGameScreen_Update @0x435980` has none
  either. **[PROVEN static]** So ranked is **not** the gate for whether the referee is contacted.
- `"RankedGame"` is a host-selectable UI toggle (`GameSettingsPanel` widget `+0xb70`, `FUN_00456c70`), a
  displayed property (`FUN_004593c0`), and a **bool field** in `RefereeServerConnection::RegisterGame`
  (msg `0xDB6`, `@0x479840`) alongside `Wager`/`AIPlayer`. Ranked is **recorded/reported** (leaderboards),
  not a contact gate. **[PROVEN static]**
- This ranked run died at **80s on the unanswered world-login**, not the ~13s referee abort (`ARM_REFEREE`
  on; LoginSuccess pushed #2@`11:59:53`, #6@`12:05:34`). **[PROVEN live]** ⇒ the world-login is the active
  wall once the referee path is armed.

## 6. Proposed fix (gated — see the ER)

Answer **each** client `0x27D2` with a fresh `EnterWorld(1000)` (request-driven), instead of relying on
the one-shot lobby-entry timer push. Minimal change in `dispatch._h_send_game_data`'s `0x27D2` branch:
send the 1000 **bypassing** the per-conn `_enter_world_sent` latch (the client explicitly asked), behind a
new default-OFF flag. The 1000 **wire format is unchanged** (same `enter_world_body`, same SendGameData(74)
envelope, already independently reviewed in s35) — only the **trigger** changes (event-driven vs timer).

**Open questions to settle before/at the live test (read-only):**
1. Does answering the match-start `0x27D2` make the client advance past `LeavingVillage(10)` and stop the
   80s disconnect? (probe `LM+0x57c`.)
2. Does the 3D match world then build, or stall? If it stalls → the `+0x7c`/App-transition build trigger is
   the isolated next gap (BP-confirm live).
3. Does the match `1000` need different content than the lobby one? Static says no (Worldname cosmetic;
   build map from `nMenu_System+0x68`) — confirm at the independent review.
