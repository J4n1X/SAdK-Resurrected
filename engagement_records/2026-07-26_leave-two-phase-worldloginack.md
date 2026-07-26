# Engagement Record — two-phase village LEAVE: answer msg 2002 with WorldLoginAck (1006), twice

- **Date:** 2026-07-26
- **Type:** Stub wire-change (default behaviour, no flag — `HARNESS.md §5`)
- **Approved by:** user (in-session, explicit: "build it, and we'll see")
- **Files:** `sadk_lobby/village.py` (`send_world_login_ack(force=)`), `sadk_lobby/dispatch.py`
  (live-conn registry, `on_conn_closed`, the 2002 branch), `sadk_lobby/connection.py` (register/close hooks)
- **Supersedes:** `2026-07-26_village-leave-close-connection.md` (socket close — live-falsified)

## What the instrument showed (this is why the previous attempt failed)

With the standing trace set (`docs/LIVE_DEBUG_RUNBOOK.md`) armed, one leave produced:

```
SetState ← 0x00470643            → 8   EnteringVillage
SetState ← 0x0046F6B5            → 9   VillageEntered      (HandleEnterWorld)
HandleWorldLoginAck ← 0x00470BF6       the entry-time 1006 fires
SendLeaveVillageRequest_2002 ← 0x00431CFB
SetState ← 0x0046BE7B            → 10  LeavingVillage
… nothing, ever …
```

Two facts fall straight out, both new and both decisive:

1. **The client sends msg 2002 exactly ONCE.** No retry, no timeout, no fallback (stub log agrees: one
   `0x27D2` and silence). So any design that relies on the client asking again is dead on arrival.
2. **The entry-time 1006 is harmless.** It reaches `HandleWorldLoginAck`, but `ConnectionReal::Logout`
   never fires — `UserCommConnection::Logout` is guarded on `transport->GetState()==8` and UC is not in
   state 8 at entry. The earlier worry that it was silently corrupting sessions is **withdrawn**.

That explains the previous attempt exactly. We answered each 2002 with one 1006; there was only ever one
2002; so only one 1006 arrived; UC was open, so it took the **UserComm-logout** branch — the player name
went "default" — and the village branch never ran. **It was one message short, not wrong.**

## The mechanism `[PROVEN]`

`VillageServerConnection::HandleWorldLoginAck@0x0046ec50`, on `code == 0xDEADBEEF`:
```c
uc = LobbyManager::GetUserCommConnection();
if (uc->vtbl[0x2c]() == false)  { ...; this->transport->vtbl[0x18](); return; }  // VILLAGE transport Logout
else                            { FUN_00458860(&uc->field_0x1c); FUN_0047ed70(uc); }  // UserComm Logout
```
`ConnectionReal::Logout@0x10030510` sets transport state **9**. On the ensuing disconnect,
`FUN_10030ad0` case 4 branches on that state:

| transport state | result |
|---|---|
| 8 | `ConnectionLost` with hardcoded **reason 10** → `!CONNECTION_LOST_TEXT` |
| **9** | **`OnLoggedOut`** → `HandleLoggedOut` → `SetState(VillageLeft=11)` → `+0x1c` observer → **arms the referee** |

## The change

- **Phase 1** — on msg 2002: send `WorldLoginAck(1006){0xDEADBEEF}` and latch `conn._leave_phase = 1`.
  UC is open, so the client runs `UserCommConnection::Logout`.
- **Phase 2** — when the **UC socket actually closes**, `dispatch.on_conn_closed()` finds the village conn
  of the *same player* (matched on `players.of().perm_id`) that is waiting at phase 1, and sends a second
  1006. UC is now closed, so `HandleWorldLoginAck` takes the **village** branch.

Phase 2 is **event-driven off the real socket close**, not a timer — the client's own teardown decides
when, and we react. A small live-connection registry (`dispatch.register_conn` / `on_conn_closed`, wired
from `connection.run()`) exists purely to pair a player's UC and village sockets.

Nothing is forced, injected, or patched: both phases are ordinary server messages the client's own
unmodified code acts on.

## Falsifiable predictions (single client, traces armed)
Log in → enter village → leave → confirm.

1. Stub logs **phase 1** (1006 on 2002), then **phase 2** when the UC conn drops.
2. **SUCCESS:** trace shows `ConnectionReal::Logout` firing, then `HandleLoggedOut`, then
   `SetState → 11`; in game you leave the village with **no** `!CONNECTION_LOST_TEXT`.
3. **PARTIAL A:** phase 1 runs, name goes "default", but the UC socket never closes → phase 2 never
   fires → still stuck in state 10. Then `UserCommConnection::Logout` is not actually tearing the socket
   down, and we need to find what does.
4. **PARTIAL B:** phase 2 fires but the exit is `HandleDisconnected` + the dialog → the village transport
   was still in state 8, i.e. the second 1006 did not reach the village branch (UC-open predicate still
   true). Trace #4 (`ConnectionReal::Logout`) discriminates 3 from 4 immediately.
5. **FAILURE:** no change at all → 1006 is not the answer to 2002 and the `[INFERRED]` link is wrong.

### Honest limit
`[PROVEN]` that 1006 `{0xDEADBEEF}` drives the Logout chain and that state 9 selects the `OnLoggedOut`
exit. `[INFERRED, strong]` that 1006 is the intended *reply to 2002*, and `[INFERRED]` that the real
server sent two of them — the two-phase shape is derived from the client's branch, not observed on a real
server.

## Rollback
Revert the three files. Prior behaviour was a no-op on 2002, so reverting restores byte-identical wire
behaviour. Forced or unexplained results are diagnostics only and are never reported as success.
