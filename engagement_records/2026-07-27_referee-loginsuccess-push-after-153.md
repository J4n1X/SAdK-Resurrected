# Engagement Record — push referee LoginSuccess(0xDCA) after the referee conn's 153 ACK

- **Date:** 2026-07-27
- **Type:** Stub wire-change (trigger move; **no flag** — working behaviour is the default, HARNESS §5)
- **Approved by:** user (in-session, explicit: "You can change it if you like, yeah.")
- **Status:** ⏳ awaiting live test
- **Evidence class:** live TTD trace of the host + the stub's own wire log of the same session.
  This is **not** a hypothesis fishing trip — the deadlock is directly observed on both sides.

## The wait-state, and why it is NOT a legitimate one to leave alone

HARNESS §2 requires ruling out "the game is legitimately waiting for something earlier in the flow".
Here the client **is** waiting — and what it waits for is a message only the server can send. We are
the ones failing to send it. The change makes us answer, via the real mechanism; it forces nothing.

**Observed deadlock (2026-07-27, `matchstart_host.run` + `minisrv:stub_n.out`):**

```
10:40:16.171  [#9]  TYPE 189 = AssignServer (server_type 4, subtype 4)
10:40:16.171   →    [REFEREE] GameServerData(170) id=77 type4/sub5 -> 192.168.1.130:5481   ← we answer, correctly
10:40:16.263  CONNECTION #10  192.168.1.134:56939 -> listener :5481 [referee]              ← client dials
10:40:16.324–.510  #10: handshake → CheckVersion 188 → 211/213 token → AckResult(153) err=0 ← base login OK
        …then #10 is SILENT for 3m37s, through the Start attempt at 10:43:51, and never disconnects.
```

Our `referee.py::handle_frame` only calls `send_login_success()` when the client sends a
**referee-channel** frame. The client never sends one, because it is waiting for LoginSuccess.
Stub waits for client; client waits for stub. Deadlock. The code comment already flagged the
trigger as `[VERIFY LIVE]` — it is now verified, and it is wrong.

## Why this is the match-start blocker (chain, all evidence-backed)

| step | evidence |
|---|---|
| `Lobby_HostRegisterGameWithReferee@0x00432240` has **no direct callers**; it is an observer callback installed on **RefereeServerConnection +0x80 = LoginSuccess** | disassembly `0x00435269`–`0x0043527f` (2026-07-27) |
| therefore no LoginSuccess ⇒ no `RegisterGame(0xDB6)` ⇒ referee never registers the match | same |
| `RegisterGame` fired **0 times** across the whole recorded match-start | TTD `TTD.Calls(0x432240).Count() = 0` |
| referee never becomes ready: `InitRefereeServerConnection` ran on **19/19** pump ticks | TTD `TTD.Calls(0x462910).Count() = 0x13`, `StatePump_Tick = 0x13` |
| the referee assign callback pair `ServerList+0xa4/+0xa8` is still armed at 5% **and** 90% of the trace (`+0xa8 = 0x004625D0` = `LobbyManager_SetRefereeServerAddress`) | TTD memory read |
| `LobbyManager+0x580` (`nRefereeServerId`) reads **0** with **zero writes** in-window | TTD memory + `ttd_memory` write history |

## The change

`sadk_lobby/dispatch.py`, in the 213→153 handler, beside the existing village `EnterWorld(1000)`
push (same shape, same place, same rationale): after the **referee** conn's 153 AckResult, push
`LoginSuccess(0xDCA)`. `referee.send_login_success()` is already idempotent (`_ref_login_sent`) and
already builds the `SendGameData(74)` envelope, so `handle_frame` keeps working unchanged if the
client *does* later open the channel first.

A small settle delay (`REF_LOGIN_SUCCESS_DELAY`, mirroring `ENTER_WORLD_DELAY`) is used for the same
reason the village push has one: land it in a fully-constructed connection object rather than a
half-built one.

**Not a flag.** Per HARNESS §5 working behaviour is the default; there is no env toggle and no
gating. Reverting means reverting the commit.

## Falsifiable predictions

1. **Success:** the referee conn stops being silent; the log shows the client sending
   `RegisterGame(0xDB6)` and the stub answering `RegisterGameAck(0xDB7)` +
   `RegisterGameResult(0xDB8, GameSeed)`. `TTD.Calls(0x432240)` becomes ≥ 1 on a new trace.
2. **Framing wrong:** the client crashes or drops `:5481` shortly after our push. See
   `referee-loginsuccess-crash-template` — a **bare-frame** LoginSuccess crashed the client
   historically; we send it inside the `SendGameData(74)` envelope, which is the current model but
   is **not** live-confirmed on this build.
3. **No effect:** LoginSuccess is accepted but `RegisterGame` still never fires ⇒ the `+0x80`
   observer is not the only gate, and `RefereeServerConnection` needs something further upstream
   (next place to look: `FUN_00408480(LM+0x490)` and the referee vtbl `+0x2c` readiness predicate).

## Known open risk — endianness `[TODO]`

`referee.py::_u32` packs **little-endian**. Referee bodies are LobbyMessages read via BitStream
(positional u32s), *not* TinCat PropertySets — and the big-endian rule in
`docs/LIVE_DEBUG_RUNBOOK.md` §7 applies to **property values**. So LE is *probably* right here, but
it is **unproven**. If prediction 2 or 3 occurs, flipping this is the first thing to try. Note the
client reportedly does not validate the PermID value, only the message id — so a wrong-endian
PermID should still clear the gate, which limits the blast radius for LoginSuccess specifically
(it would matter more for `GameSeed` in `RegisterGameResult`).
