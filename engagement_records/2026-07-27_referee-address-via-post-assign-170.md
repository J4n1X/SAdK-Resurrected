# Engagement Record — address the referee connection with a 170 pushed AFTER the assign

- **Date:** 2026-07-27
- **Type:** Stub wire-change (referee assign descriptor 5→4 + a follow-up observer 170; **no flag**)
- **Status:** ⏳ proposed — awaiting user approval
- **Supersedes:** `2026-07-27_referee-via-server-list.md` (right mechanism, **wrong ordering**)

## The mechanism, proven

`ConnectionManagerINet` keys connections by **server id** at `conn+0x1c`, and stores the dial
target at `conn+0x14` (host strdup) / `conn+0x18` (port). `FUN_100309d0` (ConnectionReal::Connect)
dials from `+0x14`/`+0x18` only; `RefereeServerConnection::Login` passes `param_2 = NULL`, so it
supplies no address of its own — the connection must already carry one.

**Measured, `referee_gateA.run` + `host_start_full.run`** — the *working* village connection:

| field | value |
|---|---|
| `villageConn+0x34` | `0x1bd51b00` |
| `conn+0x14` | → `"192.168.1.130"` |
| `conn+0x18` | `0x1567` = **5479** |
| `conn+0x1c` | `0x32` = **50** = `FAKE_VILLAGE["id"]` |

`FUN_100196b0` (CM `vtbl[0x38]`, verified at instruction level: `RET 0x4`, `[EDI+0x1c] = EBX`,
no address write) creates that connection **address-less**, keyed by the server id. The only place
the client can have learned `192.168.1.130:5479` is our village **`170 GameServerData`**.

⇒ **A `170` for server id N applies ip:port to the live connection keyed by N.** That is the same
shape as `CommLayer_OnUsercommServerData` (reached from `CommLayer_ServerRecvHandler_StateMachine`),
which applies an address via `FUN_100191e0` and then dials.

## Why the previous attempt failed — ordering, not mechanism

`stub_reflist.out`:

```
12:44:12.412  → [REFEREE] listed id=77 type4/sub4     <- list entry
12:44:49.462  → [REFEREE] GameServerData(170) id=77   <- assign reply, +37 s
```

The list `170` is emitted answering `RegObserverServerList(171)` at **login**. The connection keyed
by 77 does not exist until `InitRefereeServerConnection` runs, which is gated on `LM+0x580`, which
only latches when the **assign** reply reaches the lobby observer. So the address arrived 37 s
before there was anything to apply it to; the connection created afterwards stayed address-less and
the dial died as `COMM_LAYER_ERROR_CANNOT_CONNECT`.

## The change

1. `REFEREE_SERVER["server_subtype"]` **5 → 4.** Only a non-4/5 descriptor takes the default branch
   to `LobbyServerList_GameServerAssigned@0x00469ad0` → `SetRefereeServerAddress` → `LM+0x580 = 77`
   (+ arms `LM+0x588 = 60000`). Corroborated by the 60 s retry cadence present in every 4/4 run and
   absent from every 4/5 run.
2. In `_h_assign_server`, **after** the referee assign reply, push a second `170 GameServerData`
   for id 77 (ip, port 5481) on the **observer/list** path — not on the assign ticket, which is
   consumed once. A short delay so it lands after `StatePump_Tick` has run
   `InitRefereeServerConnection`. This is the same observer push the stub already performs for
   hosted games (`[OBS] pushed 170 GameServerData id=…`).

Both frames are legitimate: one answers the assign, one is an ordinary server-list update. Nothing
deliberately malformed is sent.

## Falsifiable predictions

1. **Success:** `LM+0x580` = 77; the connection keyed by 77 gains `+0x14`/`+0x18`; it dials `:5481`;
   `refConn+0x34` non-NULL; no `CANNOT_CONNECT`; no 60 s retry. Then the stub pushes
   `LoginSuccess(0xDCA){PermID=1}` → `+0x80` observer → `RegisterGame(0xDB6)`.
2. **Latch but still address-less:** `+0x580` = 77 and the 60 s retry returns ⇒ the `170` is not
   reaching the address-apply path for a type-4 descriptor. Next probe = the two call sites of
   `CommLayer_OnUsercommServerData` inside `CommLayer_ServerRecvHandler_StateMachine`.
3. **Too early again:** identical to today's failure ⇒ increase the delay, or trigger the push off
   the *next* `171` rather than a timer.

## Verification plan

⚠️ **Record with `ttd_record(mode="launch")`, or restart the game first.** The referee request is a
one-shot (`StatePump+0x584`) that fires on the FIRST login after process start; both of today's
attach-mode traces recorded only zeros because it had already fired. Then offline:
`ttd_calls 0x00469ad0` · `ttd_calls 0x004625d0` · `ttd_memory` on `LM+0x580` ·
`refConn+0x34` (`LM+0x4c4`) · and the bound connection's `+0x14`/`+0x18`/`+0x1c`.
