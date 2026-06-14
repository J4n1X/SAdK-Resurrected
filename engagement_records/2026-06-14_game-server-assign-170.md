# Engagement Record — Game-server assign reply (170 type5/sub1)

- **Date:** 2026-06-14
- **Type:** Stub wire-change (flag-gated), grounded in static RE of `sadk_noav.exe` + `tincat3.dll`
- **Approved by:** user (in-session, explicit: "Implement it, one more live test, then we are done")
- **Flag:** `config.REPLY_GAME_SERVER_ASSIGN = True` (set `False` to revert)
- **Status:** ⚠️ INCONCLUSIVE — the trigger never fired in the live test (see Live result). The branch
  is harmless (correct-in-principle, never executed) and stays flag-gated; the premise is now in doubt.

## Live test result (2026-06-14, host+joiner on minisrv stub)
**My branch never ran.** Stub log over a full host→ready cycle:
- The ONLY `AssignServer(189)` messages were **type4/sub4 (referee)** → `[REFEREE]` 170 (once per login).
  **No `type5/sub1` ever arrived** → `FUN_0046aaa0` did NOT fire.
- The host registers its game via **`AddGameServer(168)` id=100 + repeated `ChangeGameServer(177)`**
  (desc `34688|2|1|0|0|Testler|Siedler` — both players present), and it stays **`running=False`** the
  whole time. No client ever sends `RequestConnectionData(221)` for id=100 (only server=50 = the lobby
  world). Both clients enter the **lobby world** (EnterWorld 1000) → the "clone" screenshot.

**Conclusion:** this build hosts through the **168/177 lobby-game-registration path**, NOT the
`AssignServer(189 type5/sub1)` / `FUN_0046aaa0` path this fix targets. The fix is correct *if* that
message ever comes, but it doesn't in this flow — so it neither confirms nor breaks anything. The real
match-start gap is elsewhere: the 168/177 game never flips `running=True`, the joiner never requests
ConnectionData for id=100, and the EnterWorld(1000) re-push parks both in the lobby world. NOT a success.

## Goal
Clear the host's "Connecting to Game Server" wall at MP match-start. The host brings up its own
TinCat match server and then waits for the lobby to confirm the assignment; the stub never sent that
confirmation, so the host parks forever (`villageList+0x9c = -2`).

## The change
`sadk_lobby/dispatch.py :: _h_assign_server` — for the game-server assign
(`server_type == 5 && server_subtype == 1`), reply a `GameServerData(170)` echoing the host's OWN
hosted game (from the registry, owned by this conn), echoing the request's `ticket_id`, and RETURN —
do NOT also send the UC `UsercommServerData(192)` (that is the chat server, which is the original
bug: a game assign was being answered with a UC server). New helpers: `registry.GameRegistry.get_owned`,
`dispatch._owned_game`.

## Why this is the genuine mechanism, NOT a forced/injected result (wait-state ruled out)
- The host **itself** sends `AssignServer(189, type=5, subtype=1)` from its match-server bring-up
  `FUN_0046aaa0@0x46aaa0` (decompile-confirmed: `Shutdown → StartUpNetwork(4) → ConnectAndJoin →
  villageList+0x6c->vtbl[0x20](…, 5, 1, …)` → sets `villageList+0x9c = -2`). The host is genuinely
  waiting on the assign result — the "Connecting to Game Server" dialog spins on that field.
- The result only reaches the host's pending-assign callback (`villageList+0xa0`) and clears
  `+0x9c` when the lobby delivers a `GameServerData(170)`: tincat3
  `GameServerManager_OnGameServerAssigned@0x10021520` routes `type4/sub5`→referee and **everything
  else → the default sink** `LobbyVillageServerList.vtbl[0x28] = LobbyServerList_GameServerAssigned
  @0x469ad0` (vtable base `0x7daf8c`, offset `0x28` RE-confirmed this session), which fires
  `+0xa0(serverDesc->server_id)` and sets `+0x9c = 0`.
- So we answer a real client request with the protocol-correct reply (HARNESS §2 — "provide it via
  the real mechanism"), exactly parallel to the LIVE-PROVEN referee delivery
  (`2026-06-13_referee-assign-170.md`). No force-call / inject / live-patch.

## Falsifiable prediction (the live test)
On a hosted match (both ready), stub on `:7070`:
1. The host sends `AssignServer(189, 5, 1)` → stub logs `→ [GAME] GameServerData(170) id=… type5/…`.
2. The host's "Connecting to Game Server" dialog CLEARS (`villageList+0x9c → 0`) instead of hanging.
3. (downstream) match-start proceeds past the host wall (NComm / referee / world-build follow).

If the dialog keeps spinning, the 170 is not routing to `GameServerAssigned` (wrong type/sub or ticket
category) and we revert / re-RE the tincat3 routing under a live read-only trace.

## Rollback
`config.REPLY_GAME_SERVER_ASSIGN = False` → byte-identical to the prior plain-`192` behavior. Files
changed: `config.py` (flag + comment), `dispatch.py` (the branch + `_owned_game`), `registry.py`
(`get_owned`). Forced results, if any, are diagnostics only — never reported as success.
