# Engagement Record — answer the village LEAVE request (msg 2002) by closing the village connection

- **Date:** 2026-07-26
- **Type:** Stub wire-change (default behaviour, no flag — per `HARNESS.md §5`)
- **Approved by:** user (in-session, explicit)
- **Files:** `sadk_lobby/connection.py` (new `close_graceful`), `sadk_lobby/dispatch.py` (the `0x27D2`
  branch), `sadk_lobby/config.py` (retire the disproven `ANSWER_WORLD_LOGIN_REQUEST` lever + fix comments)
- **Status:** implemented; **live verification owed** (the reason-code question below)

## The wait-state being answered (HARNESS §2)

This is the canonical "is the game legitimately waiting for something we should provide?" case, and the
answer is yes — the client asks to leave and we have been saying nothing.

`[PROVEN]` chain, from the binary and from live breakpoints on the real client (2026-07-25/26):

1. User picks *leave village* → `LobbyVillageScreen::OnLeaveVillage` case 5 raises the
   `!LEAVE_VILLAGE_QUESTION` / `!LEAVE_VILLAGE` confirm popup.
2. On confirm, callback `FUN_00431ce0` (`param_2 == 2`) calls screen-host `vtbl[0x84]` =
   `CLobbyClient::LeaveVillage@0x00503470`, which **tail-jumps** into
   `VillageServerConnection_SendLeaveVillageRequest_2002@0x0046bde0` (village vtable `+0x40`).
3. That builds `LobbyMessage(cat=2, id=0x7d2 = 2002){code=0xAFFEDEAD}`, calls
   `SetState(LeavingVillage = 10)`, and sends. Guard `transport state == 8` passes (live: `GetState`
   is `return *(this+8)`, value `8`).
4. **The stub receives the frame and no-ops it.** Live-proven: byte-exact
   `b6 26 4a 00 4a 00 d2 27 00 00 04 00 00 00 af fe de ad` in the log, three times in one session.
5. The client parks in `LeavingVillage(10)` **forever** — it retries, never times out, never drops the
   connection. In game: "nothing happens" (user-observed, twice).

## Why closing the connection is the genuine mechanism

Exhaustive scripted sweep of every write to `LobbyManager.state (+0x57C)`: **state 11 (`VillageLeft`) has
exactly two writers** — `HandleLoggedOut@0x00470e20` (village vtbl `+0x1c`) and
`HandleDisconnected@0x00470f90` (village vtbl `+0x20`). `StatePump_Tick` writes 4/6/7 only, so there is
**no timeout or self-recovery** out of state 10.

Of those two exits:

- **`LoggedOut` is unreachable** for the village transport. Exhaustive in-Ghidra sweep of tincat3 (all
  101k instructions, every register encoding) found exactly one caller of the comm-sink's `OnLoggedOut`
  (`sink+0x0C`): `CommLayerConn_PumpPendingLoginNotifications`. That pump is reached only from the
  `ConnectionBC` / `ConnectionLANLobby` ticks — never from `CommLayer::ConnectionReal`, which is what the
  village transport is (vtable `0x10051694`, read from the live client twice).
- **`Disconnected` is the village connection's path.** `LobbyManager::OnConnectionLost@0x004647e0` routes
  the village conn to `vtbl[0x20]` → `HandleDisconnected` → `SetState(VillageLeft = 11)` +
  `Game_SetRunMode(host, 2)` (return to the lobby/village screen).

So the village connection was never meant to use `LoggedOut` — which dissolves the paradox that blocked
three sessions. The server ending a connection it was asked to leave **is** the completion.

This is not a forced result: we are not patching, injecting, or faking any client state. We perform a
normal server-side TCP close (`shutdown(SHUT_WR)` → FIN) in response to an explicit client request, and
the client's own unmodified code does the rest.

## The change

`connection.py` gains `close_graceful()`: half-closes with `shutdown(SHUT_WR)` so the peer sees a clean
FIN (not an RST), then lets the normal run-loop teardown finish. `dispatch.py`'s `0x27D2` branch now logs
the leave and calls it, instead of no-oping.

**Retired in the same change:** `ANSWER_WORLD_LOGIN_REQUEST` / `WORLD_LOGIN_MAX_ANSWERS`. Answering 2002
with `EnterWorld(1000)` told the client to *enter* the world when it asked to *leave* — that is the origin
of the "clone". Both settings of that lever were wrong answers to a misunderstood message, so the lever is
deleted rather than left looking plausible (`HARNESS §5`: no flags; working behaviour is the default).

## Falsifiable prediction (the live test)

Single client. Log in → enter village → leave village → confirm.

1. Stub logs `[VILLAGE] msg 2002 leave-village → closing the village connection (FIN)`.
2. **SUCCESS:** the client leaves cleanly — back to the village/server list, `LobbyManager.state`
   goes `10 → 11`, **no error dialog**.
3. **PARTIAL:** state reaches 11 and the screen changes, but an `!ERROR_DIALOG` /
   `!CONNECTION_LOST_TEXT` popup appears → the close surfaced with a **non-zero reason code**.
4. **FAILURE:** the client stays in state 10, or drops to the login screen / lobby-disconnected.

### The one genuinely open variable
`LobbyGameScreen_OnGameConnectionResult@0x00432ed0` shows the error dialog **only** `if (reason != 0)`;
`Game_SetRunMode(host, 2)` is unconditional. The reason code is produced by tincat3's socket layer at
runtime and **cannot be determined statically** — it is threaded `OnConnectionLost(connId, ?, reason)` →
`vtbl[0x20]` → `BaseConnection::Disconnected@0x0048e3c0` → the `+0x28` observer. Read it directly with a
breakpoint at `0x004647e0` (reason arrives as an argument). If it is non-zero, outcome 3 tells us the
close must be shaped differently (e.g. a different shutdown/linger), not that the model is wrong.

## Rollback
Revert the three files (`git revert`). The prior behaviour was an explicit no-op on `0x27D2`, so reverting
restores byte-identical wire behaviour. Any forced or unexplained result is a diagnostic only and is never
reported as success.
