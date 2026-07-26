# Engagement Record — answer the village LEAVE request (msg 2002) with WorldLoginAck (msg 1006)

- **Date:** 2026-07-26
- **Type:** Stub wire-change (default behaviour, no flag — `HARNESS.md §5`)
- **Approved by:** user (in-session, explicit)
- **Files:** `sadk_lobby/village.py` (`send_world_login_ack(force=)`), `sadk_lobby/dispatch.py` (the 2002 branch)
- **Supersedes:** `2026-07-26_village-leave-close-connection.md` (that mechanism was live-falsified)

## Why this is the genuine mechanism (HARNESS §2)

The client sends msg **2002** (leave-village), sets `LobbyManager::SetState(LeavingVillage = 10)`, and
waits — retrying, never timing out. State 10 has exactly two exits, and we now know precisely how the
correct one is reached.

**`[PROVEN]` — the disconnect branch, found by live stepping 2026-07-26.** Breakpoint on
`LobbyManager::OnConnectionLost@0x004647e0`, stub dropped to force a disconnect, caller read from `[ESP]`
at entry (not from the unwinder, which is unreliable in this binary): `ESP` = `[0x10030C30, connId, 1,
0x0A]`. `0x10030C30` is inside **`FUN_10030ad0`**, the `CommLayer::ConnectionReal` event handler
(vtbl `+0x34`), whose **case 4 (disconnect)** branches on the connection state at that moment:

```c
iVar4 = *(conn+8);                       // state at disconnect
if (iVar4 == 8) { r = ...(10); sink->vtbl[0x10](conn, r); return; }   // ConnectionLost, reason 10 (hardcoded)
if (iVar4 != 9) { ...vtbl[8](conn, 0x3f); return; }                   // login-failed path
r = ...;         sink->vtbl[0x0c](conn, r);                           // ← OnLoggedOut
```

So `OnLoggedOut` **is** reachable for `ConnectionReal` (this overturns the earlier "unreachable"
conclusion — the shape-based sweeps missed this site), and the hardcoded **reason 10** on the state-8
branch is exactly why the previous socket-close experiment produced `!CONNECTION_LOST_TEXT`: the
connection was still in state 8.

**`[PROVEN]` — what sets state 9:** only `ConnectionReal::Logout` (vtbl `+0x18` = `0x10030510`).

**`[PROVEN]` — who calls that Logout** (scripted sweep of SADK for `conn[+0x34]->vtbl[+0x18]`):
`VillageServerConnection::HandleWorldLoginAck@0x0046ecf6` (**msg 1006**),
`UserCommConnection::Logout@0x0047ed90`, `RefereeServerConnection_Logout@0x004795f7`, and one
`<no-func>` at `0x0046db94` (`[TODO]`).

**`[PROVEN]` — `HandleWorldLoginAck` (msg 1006):**
```c
if (code == 0xDEADBEEF) {
    this->nLoginAckReceived = 1;
    uc = LobbyManager::GetUserCommConnection();
    if (uc->vtbl[0x2c]() == false)   { ...; this->transport->vtbl[0x18](); return; }  // LOGOUT the VILLAGE transport
    else                             { FUN_00458860(&uc->field_0x1c); FUN_0047ed70(uc); } // LOGOUT UserComm
}
```
`FUN_0047ed70` = `UserCommConnection::Logout` (`if transport->GetState()==8 → transport->vtbl[0x18]()`).

⇒ **Two-phase teardown.** 1006 with UserComm open logs out UserComm; 1006 with UserComm closed logs out
the **village** transport → state 9 → disconnect → **`OnLoggedOut`** → `HandleLoggedOut` →
`SetState(VillageLeft = 11)` → the village conn's `+0x1c` observer →
`LobbyGameScreen_OnVillageConnectionLoggedOut` → **arms the referee login**.

This is a server *message* the client's own code acts on — not a forced result, not a patch, not a socket
trick. It is the only message in the binary that reaches the logout path.

## The change
`village.send_world_login_ack(conn, force=False)` gains `force` (mirrors `send_enter_world`) so it can be
re-sent past its one-shot latch. `dispatch._h_send_game_data`'s 2002 branch answers **every** 2002 with a
fresh 1006 `{code=0xDEADBEEF}`. The client's own retry of 2002 then naturally drives phase two: first 1006
→ UserComm logout, retry → second 1006 → village logout.

**Deliberately NOT changed in this step:** the entry-time 1006, still sent on the first in-world PingCode.
Per the RE that call takes the **UserComm-logout** branch (UC is open at entry), which looks wrong and may
have been mis-shaping sessions all along — but changing two things at once would spoil the experiment. It
is called out in the predictions below and is the next thing to examine.

## Falsifiable predictions (live test — single client)
Log in → enter village → leave village → confirm.

1. Stub logs the 2002 and a `WorldLoginAck(1006 …)` answer for each.
2. **SUCCESS:** the client leaves the village cleanly — back to the village/server list or character
   select, `LobbyManager.state` reaching **11**, and **no** `!CONNECTION_LOST_TEXT` dialog (because the
   exit went via `OnLoggedOut`, not `ConnectionLost`).
3. **PARTIAL:** it takes two (or more) 2002/1006 rounds before the client leaves — that is the two-phase
   teardown working as modelled; still a success, just multi-round.
4. **FAILURE (dialog anyway):** the client still shows `!CONNECTION_LOST_TEXT` → the village transport was
   still in state 8 at disconnect, i.e. the 1006 did not reach the village-logout branch (most likely the
   UC-open predicate never goes false — implicating the entry-time 1006).
5. **FAILURE (no change):** the client stays in state 10 → 1006 is not the answer to 2002 and the
   `[INFERRED]` link below is wrong.

### Honest limit
`[PROVEN]` that 1006 `{0xDEADBEEF}` triggers the Logout chain. `[INFERRED, strong]` that 1006 is the
*intended reply to 2002* — it is the only message reaching that path and the client demonstrably waits
after sending 2002, but we have not proven the original server sent it in response to 2002 specifically.

## Rollback
Revert the two files. Prior behaviour was an explicit no-op on 2002, so reverting restores byte-identical
wire behaviour. Any forced or unexplained result is a diagnostic only and is never reported as success.
