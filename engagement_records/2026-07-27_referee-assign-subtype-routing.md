# Engagement Record — route the referee assign into the LOBBY observer (subtype 5 → 4)

- **Date:** 2026-07-27
- **Type:** Stub wire-change (one descriptor field; **no flag**, HARNESS §5)
- **Approved by:** user (in-session, explicit: "get that ER going and then you can do the changes")
- **Status:** ⏳ awaiting live test
- **Supersedes:** `2026-06-13_referee-assign-170.md` — whose central claim is **refuted** below.

## The defect, in one line

Our referee `AssignServer(189,4/4)` reply advertises the descriptor as **type4/subtype5**, which is
the one value tincat3 special-cases to a **private internal handler that returns without ever
notifying the lobby**. The lobby-side latch we need is on the *default* branch.

## Binary proof (decompiled 2026-07-27, `tincat3.dll`, current target)

`GameServerManager_OnGameServerAssigned@0x10021520`:

```c
if (desc+0x28 == 4 && desc+0x29 == 5) {                 // type4/sub5 = REFEREE special-case
    assignHandler = *(this+8+0x5c);                     //   tincat3-INTERNAL handler
    assignHandler->vtbl[0x20](&descFields, serverId, 0);
    return;                                             //   ← returns; lobby NEVER notified
}
if (this+4 != 0)
    (**(this+4)->vtbl[0x28])(serverDesc);               // ← DEFAULT branch = the LOBBY observer
```

Slot **+0x28** of the `IGameServerObserver` vtable `0x7daf8c` is
`LobbyServerList_GameServerAssigned@0x00469ad0` (stated in that function's own plate comment, and
confirmed by decompiling it). That function is the *only* thing that fires the pending assign
callback and latches the referee server id:

```c
nAssignedId = DAT_007db538;                     // 0 = failure default
if (assignedServerId != NULL) nAssignedId = *assignedServerId;
(**(code **)(this + 0xa0))(nAssignedId, ...);   // this = ServerList+8  →  ServerList+0xa8
*(this + 0x9c) = 0;                             // clears ServerList+0xa4
*(this + 0xa0) = 0;                             // clears ServerList+0xa8
```

→ `LobbyManager_SetRefereeServerAddress@0x004625d0` → `LM+0x580 = serverId`, `LM+0x588 = 60000`.

**The repo already recorded the correct routing** — in `dispatch.py`'s *type5/sub1* block, forty
lines below the bug: *"special-cases ONLY type4/sub5 (referee); any other descriptor → the default
sink … `LobbyServerList_GameServerAssigned@0x469ad0`, which fires the pending-assign callback"*.
The referee block above it assumes the inverse. One of the two comments had to be wrong; the
decompile says it is the referee one.

## Live measurements that the model explains exactly (TTD `matchstart_host.run`, 2026-07-27)

| observation | consistent with |
|---|---|
| client dials `:5481` and completes base login | the tincat3-internal handler does the connect itself |
| `ServerList+0xa4/+0xa8` **still armed** at 5% *and* 90% | lobby `GameServerAssigned` never ran (it clears both) |
| `LM+0x580` = 0 with **zero writes** in-window | `SetRefereeServerAddress` never ran |
| `InitRefereeServerConnection` called **19/19** ticks, body never runs | its gate is `+0x580 != INVALID` |
| `refConn+0x34` (transport) = **NULL** | never initialised |
| `RefereeServerConnection::Login` produces **no wire traffic** | early-outs on `+0x34 == 0` — it is a no-op |
| host idles on the menu map indefinitely, no error | pump disarms `+0x3625`; `+0x362c` never increments, so the 5-try abort never triggers either |

**Refutation of the prior ER.** `2026-06-13_referee-assign-170.md` claimed type4/sub5 "latches
LM+0x580", marked PROVEN LIVE. The observable it was almost certainly based on — the `:5481` dial —
comes from the *internal* branch and says nothing about the latch. The latch demonstrably does not
happen. Reclassified as **REFUTED**.

## The change

`sadk_lobby/dispatch.py`, `REFEREE_SERVER`: `server_subtype` **5 → 4** (echo the requested 4/4).
Nothing else. `REFEREE_SERVER` is referenced only by the 189 reply, so no list/browser behaviour
changes — and subtype 4 is still neither village (2) nor game (1), so it stays off the browsers.

## Falsifiable predictions

1. **Success:** `LM+0x580` latches to `REF_SERVER_ID` (77), `ServerList+0xa4/+0xa8` clear,
   `InitRefereeServerConnection` builds the transport, `refConn+0x34` becomes non-NULL, and
   `RefereeServerConnection::Login` finally opens the channel — at which point the client should
   emit referee-channel traffic and `referee.handle_frame` answers `LoginSuccess(0xDCA)` reactively
   (already implemented), leading to `RegisterGame(0xDB6)`.
2. **Routes to the lobby but assign reports failure:** `GameServerAssigned` fires with
   `assignedServerId == NULL` → callback gets `0` → `+0x580 = 0` (still INVALID) but `+0xa4/+0xa8`
   **do** clear. Distinguishable from (3) by the cleared callback pair. Means the descriptor is
   reaching the observer but is malformed — look at the 170 field layout vs `msgdefs.ini`.
3. **No change at all:** `+0xa4/+0xa8` still armed ⇒ the descriptor is not reaching
   `OnGameServerAssigned` at all (routing/ticket-category problem, not the subtype). Next lead
   would be the **cat-0x108** ticket routing referenced in `dispatch.py`.
4. **Referee connection stops being dialled:** if the `:5481` dial was *only* ever produced by the
   internal type4/sub5 branch, switching to 4/4 may stop it. Then the dial must instead come from
   `InitRefereeServerConnection` once `+0x580` latches — which is the intended mechanism, so this
   is expected and fine, but watch for the dial disappearing *without* a latch, which would be
   outcome (3) in disguise.

## How to test

Record with TTD **from before login** (`ttd_record(mode="attach")` at the login screen), since the
referee assign happens seconds after login, not at match start. Then offline:
`ttd_calls(trace,"0x00469ad0")` (did the lobby observer fire), `ttd_calls(trace,"0x004625d0")`
(did SetRefereeServerAddress run), and `ttd_memory` on `LM+0x580`.
