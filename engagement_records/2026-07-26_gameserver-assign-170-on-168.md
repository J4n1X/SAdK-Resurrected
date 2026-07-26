# Engagement Record — clear the host's "Connecting to Game Server" gate with a ticketed 170 on AddGameServer(168)

- **Date:** 2026-07-26
- **Type:** Stub wire-change (default behaviour, no flag — `HARNESS.md §5`)
- **Approved by:** user (in-session, explicit)
- **Files:** `sadk_lobby/dispatch.py` (`_h_add_game_server`), `tests/test_multi_client.py` (helper fix)

## The wait-state being answered (HARNESS §2)

The host is **legitimately waiting** and we have been saying nothing useful.

`[PROVEN — live trace + RE, 2026-07-26]`
1. Host creates the game → `FUN_0046aaa0` (this = `ServerList` = `LM+0x54`) runs and **succeeds**:
   `NComm_Manager_Shutdown` → `StartUpNetwork(mode 4 = match host)` → `ConnectAndJoin` →
   `gameServerManager->vtbl[0x20](name, …, 5, 1, …)` → parks `serverList+0x9c = DAT_007db524` (PENDING).
2. That `vtbl[0x20]` emits **`AddGameServer(168)` type5/sub1** — live-confirmed: the 168 lands on the wire
   at the exact instant the `FUN_0046aaa0` trace fires. (The referee uses a *different* slot,
   `vtbl[0x2c]` = `AssignServer(189)`. This is why the pre-existing `REPLY_GAME_SERVER_ASSIGN` branch in
   `_h_assign_server` never fires for a game — it waits on a 189 the host never sends.)
3. `serverList+0x9c` PENDING is what holds the `!Connecting to Game Server` modal
   ("Verbindung zu Spieleserver wird hergestellt") up. Live-read: `+0x9c = 0xFFFFFFFF`.
4. Only `LobbyServerList_GameServerAssigned@0x00469ad0` clears it (`+0x9c = 0; +0xa0 = 0`) after firing
   the pending callback at `+0xa0`.
5. It is **vtbl slot `+0x28`** of the ServerList observer (vtable `0x007daf8c`), and a scripted sweep of
   tincat3 finds exactly one invoker: **`GameServerManager_OnGameServerAssigned@0x10021520`**, driven by
   an inbound **`GameServerData(170)` descriptor**:
```c
if (serverDesc+0x28 == 4 && serverDesc+0x29 == 5) { ...REFEREE arm...; return; }
if (this+4) (**(this+4))->vtbl[0x28](serverDesc);   // ← default → LobbyServerList_GameServerAssigned
```

## The change
`_h_add_game_server` now answers the host's 168 with a **ticketed `GameServerData(170)`** echoing the
host's own freshly-registered game (type 5 / sub 1), immediately after the existing `AddResult(153)`.
Guarded so a `type4/sub5` descriptor is never sent down this path (that is the referee arm).

**Why ticketed, and why this is not what we already send:** the stub already pushes a 170 for the hosted
game via `_push_to_obs` (log: `[OBS] pushed 170 GameServerData id=101 to 2 observer(s)`) and the gate did
**not** clear — an unsolicited observer push evidently routes to the server-list update path, not to
`OnGameServerAssigned`. The referee 170 that *does* work (live-proven, latches `LM+0x580`) is a **ticketed
reply to its request**. This mirrors that exactly.

Not forced, not injected: an ordinary server reply carrying the id we just assigned, which the client's
own unmodified code acts on.

## Falsifiable predictions (2 clients, traces armed)
Host creates game → joiner joins → both ready → Start.

1. Stub logs `[GAME] GameServerData(170) id=… type5/sub1 (ticket=…)` right after `AddGameServer`.
2. **SUCCESS:** the trace on `LobbyServerList_GameServerAssigned@0x00469ad0` **fires**, `serverList+0x9c`
   goes to 0, and the *"Verbindung zu Spieleserver wird hergestellt"* dialog closes on the host.
3. **PARTIAL:** the gate clears but the match still does not load → the wall has moved downstream (next
   suspects: the referee `RegisterGame` round-trip and `NE_StartLoading` over the P2P).
4. **FAILURE — trace silent:** the 170 did not reach `OnGameServerAssigned`. Then the routing is not
   ticket-based and we look at how the descriptor is delivered, not at its content.
5. **FAILURE — trace fires, dialog stays:** `+0xa0` held no valid pending callback, so the clear happened
   but the UI gate is keyed on something else.

### Honest limit
`[PROVEN]` that `OnGameServerAssigned`'s default arm clears the gate, and that the host's request is a 168.
`[INFERRED, strong]` that a ticketed 170 reply to the 168 is routed there — by exact analogy with the
referee flow, which is live-proven. Outcome 4 falsifies that cleanly.

## Rollback
Revert `dispatch.py`. Prior behaviour was `AddResult(153)` + the observer push only, so reverting restores
byte-identical wire behaviour. Forced or unexplained results are diagnostics only, never reported as success.
