# HANDOFF — pick-up note for the next agent (end of 2026-07-27)

Branch `master`, clean tree. **This was the day the project's central wall came down: two
unmodified clients now host, join and PLAY A MATCH end to end.** Milestone 2 is done; the current
milestone is 3 (finalise the lobby). Afterwards we made the lobby channel list social, established
that in-world chat *text* is blocked client-side, and derived + implemented (but did not yet
confirm) in-world avatar presence.

## Read first
1. `CLAUDE.md` · 2. `HARNESS.md` · 3. `MEMORY.md`
4. **`README.md` → "How the match-start chain works"** — the eight steps, with the gotcha per link.
5. **`docs/IN_WORLD_PRESENCE.md`** — the live frontier (avatars/NPCs), spec + what is implemented.
6. `docs/LIVE_DEBUG_RUNBOOK.md` §9 — TTD: record once, query offline. Read before any live work.
7. `engagement_records/2026-07-27_*.md` — six records, including four **refuted** models with
   banners saying why. Read the refutations; they are what stops the fourth repeat.

---

## 🏆 DONE: matches start and run

Proven twice back-to-back on the wire (`stub_refbe.out`, GameID 100 and 101, both clients):
`RegisterGame(0xDB6)` inbound → `Ack(0xDB7)` + `Result(0xDB8, GameSeed)` → in-match referee traffic.

The chain, all eight links now proven — full table in `README.md`:

```
login → AssignServer(189) ONE-SHOT → stub replies 170 type4/sub4 (NEVER 4/5) → LM+0x580 latches
→ match start → RefereeServerConnection::Login OPENS the socket (sends NOTHING)
→ client asks 221 RequestConnectionData(server_id=77) → stub answers 222 → :5481
→ base TinCat login on the referee socket (…→153)
→ stub PUSHES LoginSuccess(0xDCA){PermID} → +0x80 fan-out → RegisterGame(0xDB6)
```

⚠️ The `189` is a **one-shot** (`StatePump_Tick+0x584`); its only re-arm needs `+0x588 < 0`, and
`+0x588` is armed *only* by a successful latch. Miss the first one and the client never asks again
for the whole process lifetime — which also means **a TTD recording must start before the client's
first login**, or it records only zeros. Two traces were wasted learning that.

### The two facts most likely to be re-broken
- **The referee assign descriptor is `type4/sub4`, never `4/5`.** `4/5` is special-cased in tincat3
  to a private handler that never notifies the lobby. The tell that the latch worked: `189` starts
  repeating on an exact **60 s** cadence.
- **LobbyMessage field scalars are BIG-endian** (`struct.pack(">I")`), while the surrounding TinCat
  body scalars are little-endian. A little-endian `PermID` is silently discarded.

### Why it took so long — four stacked bugs, every one silent
wrong descriptor · `221` unresolved (we sent the referee to `:5479`, the world port, and the client
obediently dialled it) · a duplicated type word inside the MEMBLOCK · endianness. **In this
subsystem "no error" means nothing** — frame accepted, socket open, nothing logged.

TTD is what ended it: `ttd_calls 0x0047ac20` = 1 call, fan-out = 0 calls, then reading the guard
operands named the bug exactly. ⚠️ `dd` prints the dword VALUE — `01000000` means `0x01000000`, not
1. **Trust the flags** (`efl 0x246 → 0x216`, ZF cleared), not the hex.

---

## 💬 Lobby chat — half works, and the other half is not ours to fix

**Working, confirmed from the client's OWN `LobbyComm.log`:** `JoinChannelReceived`,
`UserJoinedReceived` **for the other player**, `UserLeftReceived`. The channel roster, join/leave
fan-out and global-chat relay (`107`/`108`/`2`/`165`) are all in.

The join fix that mattered: the client sends `RequestJoinChannel` with **`cell_id=0`** — it is
asking the *server* to assign. Echoing 0 back made it reject the join via chat-magic
**id 11 = StatusReply{cell_id, ticket_id, status}** (bidirectional!) with `status=2`.

⛔ **Chat TEXT is blocked CLIENT-SIDE. Do not chase it from the server.** Typing produces zero wire
traffic, zero log entries, **and no local echo** — the submit handler would call
`AppendLine@0x004ae200` before any network I/O, so it never runs. `UserCommConnection` has no
outbound chat method at all. The in-world tabs are hardcoded in `FUN_004389d0`
(GLOBAL/LOCAL/MINIGAME/SETTLERS; 3+4 disabled; **LOCAL is the default active tab**), and LOCAL
plausibly depends on in-world presence — i.e. chat text may be *downstream* of the frontier below.

---

## 🌍 CURRENT FRONTIER: in-world presence (implemented, UNCONFIRMED)

Spec: `docs/IN_WORLD_PRESENCE.md`. Code: `village.BitWriter` / `entity_create_body` /
`entity_remove_body`, `dispatch._spawn_world_avatars` + despawn in `on_conn_closed`.
Tests: `tests/test_world_presence.py`. Deployed on `stub_avatars.out`. **Never seen working.**

**Merged in 2026-07-28 research** (a parallel session, `origin/master`): the full `AvatarProxy` block
survey — **AvatarStyle / ActiveItems / Stats / Inventory layouts are now known**, so the "add
AvatarStyle" next step below is ready to write rather than needing more RE. Also the `0xC1x`/`0xC8x`
re-sync family, shop/trade/party, and a testable hypothesis that in-world **chat text may be gated on
the local player having an AvatarProxy** — i.e. retest typing the moment an avatar appears.

⭐ **`names` flag — SETTLED 2026-07-29 (static): it must be 0, which is what we send.** The
2026-07-28 survey's `names=1` is wrong and has been corrected everywhere. Field names are
caller-side C string constants that never ride the wire; `FUN_0048f5f0` always tail-calls the
positional bit reader `FUN_0048f0d0` either way. The catch: with the flag SET, the finalize
`FUN_0048f530` reads a **trailing 32-bit hash word** off the stream — which we do not send, so
`names=1` would over-read every body by 4 bytes with no error of its own. Full chain in
`docs/IN_WORLD_PRESENCE.md`; the constraint is now comment-pinned at `village.py:127`.

- ⭐ **1001 EntityCreate** puts a VISIBLE body in the world (AvatarProxy → `+0x170`).
  ⛔ **1004 PlayerCreate is a player RECORD** (`+0x174`), not a body — an earlier draft got this
  wrong. ⛔ **1002 EntityUpdate is NOT movement** (bare proxy, no payload). Movement is **unfound**.
- Wire: **bit-packed, MSB-first**, names=0 so widths only. `dtblcks` 4-bit mask selects blocks; we
  send `1` (location). `id 32 │ dtblcks 4 │ tick 16 │ posx 11 │ posy 11 │ posz 11 │ rot 7 │
  zone 4 │ ghstzne 4 │ rnng 1 │ jmp 1` = 13 bytes. EntityRemove = `id 32`, nothing else.
- Origin at ground = `posx 1024, posy 512, posz 1024`. ⚠️ the scale constants at `0x7deb*` are
  **doubles**; read as floats they are 0.0 and every avatar collapses into the map corner.

### ⭐ How to read the first live test — this subsystem LOGS its failures
Two clients into the lobby world, then read `Documents/SAdK/dumps/LobbyComm.log`:

| observation | meaning | next move |
|---|---|---|
| avatars on a ring around the town square | 🎉 | movement, then NPCs |
| `Can't peek AvatarID` | leading 32-bit id wrong/not first | fix the header |
| `Could not read AvatarLocation from message.` | location block malformed | re-check widths |
| **no error, no avatar** | it PARSED, nothing rendered | add AvatarStyle (`dtblcks \|= 2`) — **do not** re-check the location block |

That last row is the point: unlike the referee, silence here is *informative*. NPCs are deliberately
NOT implemented yet — they will likely need AvatarStyle too, and stacking a second unproven block on
an unproven spawn makes a failure impossible to attribute.

---

## Other open ends (none blocking)
- **End-of-match**: `0xDD4` (GiveUpGame) and `0xDC0` (FinishGame) arrive in-match, are logged, and
  are **not** acked (`0xDD5`/`0xDC1`). Matches play but do not *conclude* server-side.
- **Spurious `192`**: the referee assign falls through and also sends `UsercommServerData`, so a
  fresh UC connection is dialled every 60 s. It is also currently the ONLY thing standing up chat,
  so untangle carefully.
- `GameSeed` is the constant `0x5eed1234` (fine — all clients get the same one).
- Unknown chat-magic ids now hex-dump themselves; `id=11` is solved (StatusReply).

## ⛔ Deploy hazards — five ways the server silently runs code you did not write (2026-07-31)

All five bit in one session, and together they cost a live test window with a second player.

1. ⭐ **Unpushed local commits get REVERTED by anyone else's deploy.** The in-world avatar work sat
   local-only for four days; a parallel session deployed from its own `origin/master` checkout and
   overwrote `village.py`/`dispatch.py`/`config.py` with the pre-avatar versions. The tell was that
   `chat.py`/`referee.py` still hash-matched (they were pushed) while the other three did not.
   **Push before anyone else deploys, and grep the server for a symbol you expect** —
   `grep -c entity_create_body` beats any hash comparison for answering "is my feature there at all".
2. ⭐ **`config.py` on the server carries LOCAL-ONLY settings — never blind-copy it.** It holds the
   real deployment's `ADVERTISED_IP` (a *public* IP for internet tests) and a different `WORLD_PORT`
   (5477, not 5479). Copying local `config.py` over it silently reverts the operator's setup.
   **Diff before overwriting, and copy only the modules you actually changed.**
3. ⭐ **A hash match proves nothing about the RUNNING process.** Python imports at startup, so a file
   written *after* launch is not loaded. Compare `ps -o lstart -p PID` against `stat -c %y file` —
   this session had a process 46 s older than the code it was supposed to be running.
4. **`SADK_ADVERTISE_IP` in the launch command OVERRIDES the config default** (`os.environ.get`).
   Passing the LAN IP out of habit makes the server hand a remote player an unreachable address.
   Launch with **no** env override unless you mean it.
5. **Launch with `python3 -u`.** Without it stdout is block-buffered into the log file, so a healthy
   server looks identical to a dead one (0-byte log) for a long time.

Restart, verify in this order:
```bash
ssh linux-server "pkill -f '[s]adk_lobby'"                       # separate invocation!
timeout 12 ssh linux-server "cd ~/projects/sadk-resurrected && \
  setsid nohup python3 -u -m sadk_lobby > stub.out 2>&1 </dev/null & disown; sleep 3"
ssh linux-server "ss -ltn | grep -E ':(7070|7071|5477|5481)'; \
  ps -o pid,lstart,cmd -C python3 | grep sadk; head -20 ~/projects/sadk-resurrected/stub.out"
```
⚠️ Backgrounding over ssh without `timeout`/`disown` **hangs the ssh channel** until the server dies.

## Environment
Stub deployed to `linux-server:~/projects/sadk-resurrected` **by file copy, not git** — the
remote checkout is an old commit with a dirty tree, so **verify by content hash, not `git log`**:
`tr -d '\r' < f | md5sum` on both sides (local checkout is CRLF, remote is LF — a raw md5 differs
even when the content is identical; that nearly caused a false alarm). Restart with
`ssh linux-server "pkill -f '[s]adk_lobby'"` then `ssh -f … setsid nohup …`; note
`pkill -f sadk_lobby` **self-matches the ssh command line** and kills your own session.

## Housekeeping
All work is committed. **Several commits are unpushed** — the remote
(`github.com/J4n1X/sadk-resurrected`, public) was last pushed at `9ad2842`. Push when you want the
match-start milestone and the in-world work visible.
