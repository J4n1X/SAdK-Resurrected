# Engagement Record — referee assign needs BOTH 170s: sub5 to register, sub4 to notify

- **Date:** 2026-07-27
- **Type:** Stub wire-change (send a second 170 in the 189 reply; **no flag**, HARNESS §5)
- **Approved by:** user (in-session, explicit: "Well, alright, you can do that.")
- **Status:** ⏳ applied, awaiting live test
- **Builds on:** `2026-07-27_referee-assign-subtype-routing.md` (which **worked**, and exposed this)

## What the subtype fix achieved (confirmed, not assumed)

Same connection `#1`, host, across two runs:

| | first `189` | second `189` |
|---|---|---|
| pre-fix (`sub5`), `stub_reflogin.out` | 11:00:29 | never |
| post-fix (`sub4`), `stub_subtype.out` | 12:08:56 | **12:09:56 — +60.1 s** |

A retry at exactly 60 s can only originate from `LobbyManager_SetRefereeServerAddress@0x004625d0`,
the sole writer of `LM+0x588 = 60000`; `StatePump_Tick` counts it down and re-arms the request when
it goes negative. **So `GameServerAssigned` fired and `LM+0x580` latched** — the thing that had
never once happened before. The routing model is proven correct.

## The new failure, named by the client's own logger

`Documents\SAdK\dumps\LobbyComm.log` (developer logging enabled by the maintainer, 2026-07-27):

```
12:14:19 - E An error occured in LobbyManager.cpp at Line 907
12:14:19 - E COMM_LAYER_ERROR_CANNOT_CONNECT - TinCat failed to start connection
12:14:19 - E An error occured in LobbyBaseConnection.cpp at Line 119
12:14:19 - E COMM_LAYER_ERROR_CANNOT_CONNECT - TinCat failed to start connection
```

`LobbyManager.cpp:907` resolves to **`LobbyManager::OnLoginFailed`** — found by locating the
line-number store `MOV dword ptr [0x0088592c], 0x38b` at `0x00464aeb`. (907 = 0x38B.)

So the client now *attempts* the referee connect and TinCat cannot even start it. That is one step
further than before the subtype fix, where it never attempted at all. And the stub log confirms
**zero** connections to `:5481` this run (`grep -c "listener :5481" = 0`).

## Why: we removed the thing that registered the address

`LobbyManager_InitRefereeServerConnection@0x00462910` does not use an address from the assign —
it resolves the **server id** through the ConnectionManager:

```c
iVar2 = pComm->vtbl[0x38](LM+0x580);     // resolve id → status
if (iVar2 != 0 && iVar2 != 0xcd) { log @cpp:0x27c; return; }
uVar4 = pComm->vtbl[0x18](LM+0x580);     // resolve id → address
bInitOk = refConn->vtbl[4](uVar4);       // connect  ← fails: "TinCat failed to start connection"
```

The `type4/sub5` descriptor we used to send was consumed by tincat3's **private** handler
(`GameServerManager_OnGameServerAssigned` → `*(this+8+0x5c)`→`vtbl[0x20]`), which is what
**registered** id 77 → `192.168.1.130:5481` *and* dialled it. Routing to `sub4` gained the lobby
notification but lost the registration. We have had exactly one of the two halves at any time:

| descriptor | registers id→addr (tincat3) | notifies lobby (`+0x580`) | result |
|---|---|---|---|
| `type4/sub5` | ✅ (and dials) | ❌ | dial happens, lobby never latches, `Login` is a no-op |
| `type4/sub4` | ❌ | ✅ | latch happens, connect fails: *TinCat failed to start connection* |

## The change

In `_h_assign_server`, on the referee assign (type 4 / subtype 4), send **two** `GameServerData(170)`
frames for the same referee server, in this order:

1. `type4/sub5` — routes to tincat3's private handler → registers id 77 → `ADVERTISED_IP:5481`
2. `type4/sub4` — routes to the default branch → `LobbyServerList_GameServerAssigned` → `+0x580`

Implementation: a second descriptor dict differing only in `server_subtype`. No other code path
touches `REFEREE_SERVER`, so browsers are unaffected.

## Falsifiable predictions

1. **Success:** `:5481` is dialled again (as in the sub5 era) **and** `LM+0x580` latches (60 s retry
   disappears, because the connect succeeds and the timer is satisfied). `refConn+0x34` becomes
   non-NULL, `RefereeServerConnection::Login` stops being a no-op and opens the channel,
   `referee.handle_frame` answers `LoginSuccess(0xDCA)`, then `RegisterGame(0xDB6)` arrives.
   No `COMM_LAYER_ERROR_CANNOT_CONNECT` in `LobbyComm.log`.
2. **Dial returns but still no RegisterGame:** the registration+latch both worked but something
   downstream of `Login` is wrong — go at the channel-open (`refConn+0x34` vtbl `+0x10`) and the
   referee message framing (`referee.py` `_u32` endianness, and the `names` bit in `type_word()`,
   since `OnLoginSuccess` reads its field via `LobbyMessage_SelectField(msg,"PermID",0)` — **by
   name**, while we send `names=0`).
3. **Still "TinCat failed to start connection":** the sub5 frame is not what registers the address
   after all. Next probe: enable dev logging again and read `LobbyComm.log` for the
   `LobbyManager.cpp:0x27c` (=636) resolve-failure line, which distinguishes "id did not resolve"
   from "address resolved but connect failed".
4. **Double connection to :5481:** harmless if login completes on one of them; if it confuses the
   client, drop the sub5 frame and instead register the referee by including it in the type-4
   server-list responses (it carries no ServerDataBlock, so it stays non-joinable in the browser).

## Note on scope

The P2P layer is **not** implicated. `comm.log` for the same session shows the full host+join+ready
sequence working: `cb_LoggedIn`/`UIS_Add` for the joiner, `NE_PlayerReady` from both sides, then
`NE_StartLoading` at 12:15:29 — after which only `cb_Ping_Received` every 10 s. Match-start is
signalled correctly inside the session; what is missing is the referee handshake that gates the
world load.
