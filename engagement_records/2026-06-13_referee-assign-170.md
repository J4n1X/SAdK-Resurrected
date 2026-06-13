# Engagement Record — Referee assign reply (170 type4/sub5)

- **Date:** 2026-06-13
- **Type:** Stub wire-change (flag-gated), exercised under live read-only debugger trace
- **Approved by:** user (in-session, explicit: "Set the flag, do any changes you need")
- **Flag:** `config.REPLY_REFEREE_ASSIGN = True` (set `False` to revert)
- **Status:** ARMED — awaiting live confirmation

## Goal
Make the stub deliver the referee server address the way the genuine lobby server did, so the
client latches `LobbyManager+0x580` and dials the referee on `:5481`. This is the last gate on
MP match-start (the ~13 s referee-login abort that kills hosted games).

## The change
`sadk_lobby/dispatch.py :: _h_assign_server` — for the referee assign only
(`server_type == 4 && server_subtype == 4`), additionally send a `GameServerData(170)` for
`REFEREE_SERVER` (id 77, **type 4 / subtype 5**, `→ ADVERTISED_IP:5481`) echoing the request's
`ticket_id`. The existing `UsercommServerData(192)` still goes out (keeps UC/chat up).

## Why this is the genuine mechanism, NOT a forced/injected result (wait-state ruled out)
- The client **itself** sends `AssignServer(189, type=4, subtype=4)` from
  `RequestRefereeServer@0x468f60` — **captured live** this session via a debugger trace of
  `tincat3!GameServerManager_AssignServer` (`this=…, server_type=0x4, server_subtype=0x4`,
  caller `SADK+0x68fa4`). The client is genuinely waiting for the assign result.
- It registers `SetRefereeServerAddress@0x4625d0` as the result callback (`StatePump_Tick`).
- The reply only reaches that callback when the descriptor is `type=4/subtype=5`
  (`GameServerManager_OnGameServerAssigned@0x10021520` gate, RE-confirmed in `tincat3.dll`).
- So we are answering a real client request with the protocol-correct reply — HARNESS §2
  ("provide it via the real mechanism"), not a force-call / inject / live-patch.

## Falsifiable prediction (the test)
On next login, with traces armed on `AssignServer`, `OnGameServerAssigned`, and
`SetRefereeServerAddress`:
1. `AssignServer(4,4)` fires (already confirmed).
2. **`OnGameServerAssigned(serverDesc)` fires with `serverDesc.type==4, subtype==5`.**
3. **`SetRefereeServerAddress(serverId)` fires** → `LM+0x580 = id 77`.
4. (downstream) `InitRefereeServerConnection@0x462910` dials `:5481`.

If `OnGameServerAssigned` stays silent, the s41.8 "client drops the assign on its lobby
connection" conclusion stands and we revert.

## Rollback
`config.REPLY_REFEREE_ASSIGN = False` → identical to prior plain-`192` behavior. No other
files changed. Forced results, if any, are diagnostics only — never reported as success.
