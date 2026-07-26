# Engagement Record — Match-start GO signal (170 running=true broadcast on 169)

> ## ⛔ ABANDONED 2026-07-26 — hypothesis unsupported, change reverted
>
> An independent clean-room derivation of the match-load path found **no role for `170.running`** — the
> field does not appear anywhere in the transition chain. The real match-start blocker was identified
> instead as the unanswered msg **2002** (leave-village) request.
>
> `config.ANNOUNCE_GAME_RUNNING` and the `_h_remove_server` broadcast were **reverted** on 2026-07-26;
> the stub is back to byte-identical prior behaviour and the flag no longer exists. This record is kept
> only as history of a falsifiable experiment that was never live-tested and is now moot.

- **Date:** 2026-07-04
- **Type:** Stub wire-change (flag-gated, env-toggled), grounded in the **authoritative AdK emulator**
  (`S2Lobby`, our exact `0x26B6` wire) + live stub-log verification of the real client's Start messages.
- **Approved by:** user (in-session, explicit: "Very well, set it all up.")
- **Flag:** `config.ANNOUNCE_GAME_RUNNING` (env `SADK_ANNOUNCE_RUNNING=1`; default OFF = byte-identical to prior)
- **Status:** ⏳ HYPOTHESIS TEST — awaiting live result. Honest caveat: unlike the referee/game-assign ERs,
  there is **no binary proof yet** that the client transitions on an inbound `170{running=true}`. The basis
  is the reference emulator + the verified fact that our stub has *never* sent `running=true`. Falsifiable.

## Goal
Get the host past the match-start self-teardown into an actually-loaded MP match. Proven this session
(live non-freezing trace): at Start the host fires networked `StartLoading`, then +16 ms its
`LobbyGameScreen` destructor `FUN_004389d0` unconditionally `Shutdown`s the P2P net-driver, and
`StartUpNetwork@0x40a9a0` gets **0 hits** — the host severs its own game socket and never rebuilds. This is
the client's *fallback* when the lobby never signals the match has started.

## The evidence this fills a real, missing half of the protocol
Four-agent research pass (docs/memory/stub/reference). The decisive input is the **AdK emulator**
(`AdK-emulator/S2Lobby/src/Core/LobbyProcessor.cs`, magic `0x26B6` = our client's exact wire):

- Match-start there is **entirely lobby-level**: host Start → server sets the game `running=true` and
  **broadcasts `GameServerData(170){running=true}` to every joined player** — the GO signal that flips the
  room into loading. (Plus a `ConnectionData(222)` address+nonce + `PlayerConnecting(223)` handoff for the
  actual game socket — deferred to a follow-up step; this ER is the `running=true` signal only.)
- **Live-verified against our real client** (stub log): the host sends `RemoveServer(169)` at the exact
  Start moment (21:48:13.921, right after the final room `ChangeGameServer(177)`). BUT: the reference's
  "`ticket_id==14` = StartGameServer" discriminator is **REFUTED for our build** — `ticket_id` is a
  per-connection sequence counter (the "14" in our log sat on a `CheckVersion(188)`), and our Start-`169`
  carries `running:False, ticket_id:39`. So we key off the `169`-at-Start itself, not the ticket.
- **The verified gap:** our stub has emitted `running=False` on *every* `170`/`177`, forever. The client
  has never once received a `running=true`. This is a whole missing half of the match-start protocol —
  the binary RE only ever saw the client's teardown *symptom*, never the absent server signal.

## The change
`sadk_lobby/dispatch.py :: _h_remove_server` (169) — when `config.ANNOUNCE_GAME_RUNNING`: set the host's
owned game `running=True`, send a `GameServerData(170)` on the host's own conn AND `_push_to_obs` to all
browser observers (the joiner subscribed as one), and **keep** the game resolvable (do not delist) so the
joiner's later `221→222` still returns the match address. `config.py`: the env-toggled flag.

## Why this is the genuine mechanism, NOT a forced result (wait-state ruled out)
- We are **providing a real, expected server broadcast** that the reference protocol emits at exactly this
  point — not a force-call / inject / live-patch of the client. The client's own Start message (`169`)
  triggers it; we answer with the protocol's documented go-signal (HARNESS §2 "provide it via the real
  mechanism").
- It is fully reversible and OFF by default (`SADK_ANNOUNCE_RUNNING` unset → byte-identical prior behavior).
- **Residual honesty:** the referee/game-assign ERs had tincat3 decompile proving the client latches the
  reply. Here the proof is one layer softer (reference reconstruction + "never-sent" gap), so this is run
  as a *falsifiable experiment*, and a read-only static check of the client's inbound-`170` handler
  (does it branch on `running` → a room→loading transition?) is owed alongside the live test.

## Falsifiable prediction (the live test)
Host+joiner on the minisrv stub with `SADK_ANNOUNCE_RUNNING=1`, host-side debugger traces active
(`StartUpNetwork@0x40a9a0`, `Shutdown@0x40b410`, `StartLoading@0x40fe50`):
1. Stub logs `[MATCH-START] RemoveServer(169) … GameServerData(170){running=True} broadcast`.
2. **SUCCESS:** the host does NOT self-destruct — either the room-screen destructor `Shutdown` does not
   fire, or `StartUpNetwork` fires (re-host), and/or the match loads instead of the lobby-world clone.
3. **FAILURE:** the host still `Shutdown`s at +16 ms with `StartUpNetwork`=0 (identical to prior) → the
   `running=true` broadcast is NOT the lever → revert, and pivot to the state-9 suppression hypothesis
   (host is world-build-eligible only because the stub's login-time `EnterWorld(1000)` parks it in state 9).

## Rollback
Unset `SADK_ANNOUNCE_RUNNING` (or `config.ANNOUNCE_GAME_RUNNING = False`) → byte-identical to prior `169`
delist+ack. Files changed: `config.py` (flag+comment), `dispatch.py` (`_h_remove_server`). Forced results,
if any, are diagnostics only — never reported as success.
