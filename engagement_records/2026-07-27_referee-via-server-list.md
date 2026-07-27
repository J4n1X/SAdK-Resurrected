# Engagement Record — advertise the referee on the SERVER LIST; assign stays a single sub4 frame

- **Date:** 2026-07-27
- **Type:** Stub wire-change (revert the sub5 twin; add the referee to the type-4 list; **no flag**)
- **Approved by:** user (in-session: *"we should ensure that the referee is fetched and assigned from
  the server list"*) — the maintainer's steer, which the static RE below independently supports
- **Status:** ⏳ applied, awaiting live test
- **Supersedes:** `2026-07-27_referee-dual-170-register-and-notify.md` → **REGRESSION, reverted**

## Why the dual-170 was wrong (measured)

`189` frames per client:

| run | retries |
|---|---|
| sub4 only (`stub_subtype.out`) | #1 12:08:56→**12:09:56**, #12 12:14:18→**12:15:18**, #18 12:15:14→**12:16:14** |
| sub5 + sub4 (`stub_dual170.out`) | #1 12:25:23 once, #3 12:25:26 once — **no retry** |

The +60 s retry only exists once `SetRefereeServerAddress@0x004625d0` has armed `LM+0x588 = 60000`
(`StatePump_Tick` counts it down and re-arms `+0x584` when it goes negative). So **sub4 alone runs
the lobby latch; adding the sub5 twin suppresses it.** Both frames carried the same `ticket_id`;
the first reply evidently consumes the pending assign and the second is discarded.

Confirmed in the TTD trace `matchstart_referee.run` (recorded across a full Start):
`LM+0x580` = 0, `LM+0x584` = 0, `LM+0x588` = 0 with **zero writes** for the whole window, and
`refConn+0x34` = NULL — so `RefereeServerConnection::Login` (now reached: **1 call**, vs 0 before)
still early-outs and is a no-op.

## The static RE that settles the mechanism

`LobbyManager_InitRefereeServerConnection@0x00462910` calls
`pConnectionManager->vtbl[0x38](LM+0x580)` then `->vtbl[0x18](LM+0x580)`. Resolved live from the
trace: `pConnectionManager` = `0x01507F78`, vtable `0x1005186C` (tincat3), slot `+0x38` =
`FUN_100196b0`, slot `+0x18` = `0x10019560`. **Both funnel into vtable slot `+0x5c` = `FUN_10019570`:**

```c
FUN_10019570(this, serverId) {
    if (serverId == 0) return 0;
    for (entry in list at *(this+0x10))
        if (entry && *(int*)(entry + 0x1c) == serverId) return entry;   // key = +0x1c
    return 0;
}
```

It walks the list of **live connection objects**, matched on `entry+0x1c == serverId`. `FUN_100196b0`
creates one when absent (`operator_new(0x58)` … `puVar4[7] = param_1`, and `7*4 = 0x1c` — the same
key) and returns `0xcd` when one already exists, which is exactly the value the caller whitelists.

**There is no id→address registry.** The lobby never resolves an address; it looks for a connection
the client already has. So the client must have learned about server 77 through the normal channel —
the **server list** — before the assign names its id. Without that, the created connection has
nowhere to dial and the attempt surfaces as `COMM_LAYER_ERROR_CANNOT_CONNECT — TinCat failed to
start connection` (`LobbyManager::OnLoginFailed`, `LobbyManager.cpp:907`, located via the
line-number store `MOV dword ptr [0x0088592c], 0x38b` at `0x00464aeb`).

## The change

1. **Revert** the `type4/sub5` twin — `_h_assign_server` sends exactly one referee `170` (type4/sub4).
   `REFEREE_SERVER_REGISTER` removed; a comment records why it must not come back.
2. **Advertise the referee on the type-4 server list** in `_send_server_list`, placed *after* the
   `sent == 0` fake-village check so it can never suppress the village injection.

`test_server_browser` now asserts exactly **one** referee `170` from the assign, with the reason
inline (it previously asserted two, then before that asserted sub5 — it has encoded each wrong model
in turn, so the assertion now carries its justification).

## Falsifiable predictions

1. **Success:** the client learns server 77 from the list; the assign latches `LM+0x580`;
   `InitRefereeServerConnection` finds/creates a connection that can dial; `refConn+0x34` becomes
   non-NULL; `Login` opens the channel; `LoginSuccess(0xDCA)` is answered; `RegisterGame(0xDB6)`
   arrives. No `COMM_LAYER_ERROR_CANNOT_CONNECT` in `LobbyComm.log`, and no +60 s `189` retry.
2. **Latch but still no dial:** `189` retries at +60 s return and the connect error persists ⇒ being
   in the list is not sufficient to create the connection object; next probe is what *populates*
   `*(pConnectionManager+0x10)` — i.e. which inbound message constructs a connection entry.
3. **Browser pollution:** a stray/greyed referee row appears in the village browser. It carries no
   `ServerDataBlock`, so `FillFromDescriptor@0x481640` should leave validity 0 — if it shows anyway,
   restrict the listing to the `RegObserverServerList` that precedes the assign, or give it a
   subtype the browser filters out.
4. **Village entry breaks:** should not happen (the referee is appended after the village check) but
   it is the thing to check first if the lobby world stops loading.

## Verification plan

Record from **before login** this time — the assign and the referee connect both happen seconds
after login, outside the window of the two traces we have. Then offline:
`ttd_calls 0x00469ad0` (lobby observer fired), `ttd_calls 0x004625d0` (SetRefereeServerAddress ran),
`ttd_memory` on `LM+0x580`, and `refConn+0x34` (= `LM+0x4C4`) for non-NULL.
