# MP match-start failure — evidence report (2026-07-04, live capture)

> ## ⛔ SUPERSEDED 2026-07-25/26 — the diagnosis below is largely obsolete
>
> The wall is **not** a client-side teardown ceiling. It is a **server non-answer**: at match-start the
> client sends msg **2002** (`0x27D2`, leave-village), sets `LeavingVillage(10)`, and waits forever. Our
> stub receives that frame and explicitly **no-ops** it (live-proven 2026-07-25, byte-exact in the log).
> The "clone" is caused by the stub's *other* possible answer, `EnterWorld(1000)`, which tells the client
> to enter the lobby world when it asked to leave.
>
> Also refuted here: the `running=true` broadcast hypothesis (the `170.running` field appears nowhere in
> the transition path) — that experiment has been **reverted**, see the abandoned ER of 2026-07-04.
>
> Still valid: the packet/timeline evidence and the "matchmaking through Start works" conclusion.
> Current model + evidence chain: `decomp/RENAME_LIST.md`, 2026-07-25/26 entries.

**One line:** A full 2-player room builds and both players connect P2P; then at match-start the
match never loads — the joiner goes silent after readying, the host times out in ~3s, tears down
the game net-driver, and both clients fall back into the **lobby** world (the "clone"). The clone is
the wreckage, not the bug.

All claims below are from evidence gathered this session — no guesswork. Ghidra was **offline** this
session, so the one remaining *internal-binary* question is explicitly flagged as open.

## Instruments
- Stub log (`stub_restart.out`, minisrv .130) — the lobby/UC/world/referee wire.
- Host's own logs (`Documents\SAdK\dumps\`): `LobbyComm.log`, `netlog.txt` (TriNodE net-driver),
  `userlog.txt`, `comm.log` (empty — NComm game events not logged in this build).
- **P2P packet capture** (`dumpcap` on Wi-Fi, host .134) — `p2p_matchstart.pcapng`, decoded with
  `tools/decode_game_join.py`.

## Proven timeline (time-correlated to the second)
Run at 15:13 (stub clock). Capture-relative `t` in brackets.

| Time | Evidence | Event |
|---|---|---|
| 15:13:02–16 | stub log | both clients login (lobby/UC/world), enter the **lobby** world (`EnterWorld 1000`) |
| 15:13:24 | stub log | host `AddGameServer` id=101 `MP_2P_fata_morgana`, `running=False` |
| 15:13:25 `[t+80.1]` | pcap | joiner `.143` → host `.134:5479` TinCat handshake — **P2P game connect** |
| `[t+80.6]` | pcap | joiner sends game-logon `0x27d9 … "Siedler"` |
| `[t+80.8]` | pcap | **host replies with room roster `"* Testler\n  Siedler"`** — join accepted, room built |
| `[t+82.3]` | pcap | joiner sends slot/ready (`0x27d9 …"11 11"`) — **then goes silent** |
| 15:13:29 | stub log | host `ChangeGameServer` → `Testler|Siedler` (room reflected to lobby) |
| `[t+82.3→85.1]` | pcap | host keeps broadcasting room state; joiner never replies (~3s = `timeClientWaits`) |
| `[t+85.1]` 15:13:34 | pcap + netlog | host tears down net-driver (`"removing… descriptor is not a socket… STOP"`); **both clients fire `0x27d2` world-login** |
| 15:13:34 | stub log | stub answers each `0x27d2` with `EnterWorld(1000)` = **lobby world** → clients reload lobby = **clone** |
| 15:13:35 | LobbyComm.log | `DeleteResultReceived` — host deletes the game |

## What WORKS (proven)
Lobby login, chat, browse, **P2P join, host room-build (both players), slot/ready exchange.** The two
players genuinely reach a shared room. Everything up to the match "GO" is functional.

## Ruled OUT (with evidence)
- **Checksum/version kick** — host's logon reply is the roster, not a `!…MISMATCH` kick (cf.
  `Manager.cpp` kick path). Install parity is fine this run.
- **Referee** — both sides base-auth to `:5481` OK, but the referee **data channel is never opened**
  (no `SendGameData(74)` on the referee conn, no `LoginSuccess`). The match dies *before* the referee
  is needed. Referee is not the wall.
- **`:8777` NComm "site"** — `network.ini [Lobby] url=192.168.1.130:8777`, and the stub does not
  listen there — **but the capture shows zero connection attempts to `:8777`.** Dead site is a red
  herring for LAN play.
- **Port config** — `gamePort=5478` in the ini, but the host actually serves on **5479** and the join
  works on it. Not the issue.

## CORRECTED (2026-07-04, live non-freezing trace — dbgeng) — room-screen-destructor teardown; LOOPBACK REFUTED

⚠️ **The "loopback teardown" theory (previously marked PROVEN here) is REFUTED by a clean live trace.**
Everything below this section that speaks of "Path B / `TriggerMPWorldBuild` loopback" or of deploying
`ANSWER_WORLD_LOGIN_REQUEST` is **superseded and wrong** — kept only for history.

Non-freezing `debugger_trace_function` on the host during a real repro (no breakpoints, game never paused):
`FreeGamePanel_TriggerMPWorldBuild` = **0 hits**, `NComm_KickPlayer` = **0**, `FUN_0046aaa0` (assign) = **0**.
The host does **not** loopback, kick, or re-assign. What actually fires, in order:

```
[t]        FUN_0040FE50  — host sends StartLoading (0x30012), networked, both players ready   ✓ correct
[t+16ms]   NComm_Manager_Shutdown  ← caller 0x438CD9, inside FUN_004389d0
```

`FUN_004389d0` is the **LobbyGameScreen destructor** (exception-unwind cleanup of the room screen); its body
**unconditionally** calls `NComm_Manager_Shutdown`, tearing down the one net-driver — which *is* the joiner's
live P2P socket. That is the "Virtual circuit was reset by other side" the joiner's `netlog.txt` records.

**Trigger (decompiled `FUN_00457a00`, the room-screen update / "Connecting to Game Server" dialog):**
```c
if (NComm+0x3cc [StartLoadingFired]) {
    if (LobbyManager state == VillageEntered [9])   →   (**vtbl[0x84])()   // OnEnter world-build
}
```
So: both-ready → `FUN_0040fe50` broadcasts `StartLoading` → host receives its own broadcast and sets `+0x3cc`
→ the next frame the `+0x3cc && state==9` gate trips **`OnEnter`** (the world-build) → it swaps out the room
screen → the room destructor `Shutdown`s the net-driver → **P2P severed; both fall to the lobby.**

**The `0x27d2`→lobby-`1000` answer (`ANSWER_WORLD_LOGIN_REQUEST`) is NOT the trigger and cannot fix this.**
The gate needs `state==VillageEntered(9)`, and the host is in state 9 since **login** — the stub's automatic
`EnterWorld(1000)` (milestone-1 lobby entry, stub log conn #25 at 16:30:55), *not* the match-start `0x27d2`
(conn #21 at 16:51:40), which merely re-sets an already-9 state. Suppress that answer and state stays 9 →
`OnEnter` still fires → P2P still dies. Proven from the stub log + the decompile.

**This teardown is client-side** — after the P2P is up, with the stub out of the loop. The game-socket's
lifetime is bolted to the room screen it destroys at world-build, so **no stub message prevents it.** This is
very likely the ceiling of the stub approach for *loading* the match (matchmaking through Start all works).
The one honest open question is RE, not a flag: **does genuine MP re-create the game socket after this teardown
(host re-hosts), and if so what triggers it — or does the destructor simply not fire in the real room→match
transition?** Settling that needs the real server's behavior or deeper client-side RE, not a stub change.

### The correct (networked) path the host should take instead
`Manager_HandleNCommEvent@0x40e560` **case 0x3000b**: `if (NComm_IsHost() && FUN_004083e0()[all-ready]) →`
send **`NComm::Event1Integer 0x2002b`**; and it arms `+0x3ae bStartLoadingReady` when `+0x3ad bStartLoadingArmed`.
The networked start is: all-ready → `0x2002b` → **`StartLoading (0x30012)`** over the P2P → each client's
`case 0x30012` sets `+0x3cc` + arms the referee (`LM+0x3625`) → `OnStartLoading@0x4316c0` (which does **NOT**
`StartUpNetwork(0)` — P2P preserved) → `OnEnter`/`BuildWorldSequence`. The host took the **loopback** path (#2),
not this networked path (#1) — which is exactly why **no referee frame and no `0x30012` ever appeared on the wire.**

### Fix direction + honest scope
The correct fix is to make the host reach the world-build via the **networked `0x30012` path (P2P preserved)**,
not the `TriggerMPWorldBuild` loopback. This teardown is **client-side** (it happens after P2P is up, with the
stub out of the loop), so the stub cannot directly prevent it.

### The two match-start paths (RE'd end to end) — and the connection to the earlier `+0x9c` work
The `StartLoading (0x30012)` emitter is **`FUN_0040fe50`**: it sends `0x30012` iff the NComm is a **host
(mode 0/2/4) AND `EManagerState==2` (Connected)**. Its **sole caller is `FUN_00457a00` — the "Connecting to
Game Server" dialog** (the one that spins on `villageList+0x9c`, cleared only by inbound `GameServerAssigned`).
So there are two mutually-exclusive ways the host can "start":

- **Path A (networked, correct):** host → **`FUN_00457a00` "Connecting to Game Server"** → (`FUN_0046aaa0`
  ensures mode-4 host + `AssignServer(189)`; `villageList+0x9c=-2`) → **stub replies `GameServerAssigned`**
  (→ `+0x9c` clears) → connected (state 2) → `FUN_0040fe50` broadcasts `0x30012` over the mode-4 P2P → each
  client's `OnStartLoading` builds the world **keeping the P2P**. *This is exactly the `+0x9c`/`GameServerAssigned`
  gate + the `type5/sub1 → 170` reply researched in `[[mp-matchstart-loopback-teardown-rootcause]]`/the s39–s42
  game-assign work.* So the correct path is **stub-reachable** (it needs the `GameServerAssigned` reply).
- **Path B (loopback, what happened):** host clicks the **`FreeGamePanel` Start** → `TriggerMPWorldBuild` →
  `StartUpNetwork(0)` → local single-machine build, P2P destroyed = the clone.

**The host took Path B, not Path A** — which is why no `0x30012`, no referee frame, and no `AssignServer(189
type5/sub1)` ever appeared, and why the joiner was never told to start.

### The one remaining question + decisive next step
**Why does the host branch to Path B (FreeGamePanel loopback) instead of Path A (the "Connecting to Game
Server" networked start)?** The gate is `FreeGamePanel FUN_005e3810: if (panel+0x3a9[Start] && panel+0x13c==0)
→ loopback`. Settling this — and whether the host can be pushed onto Path A (where the stub's `GameServerAssigned`
reply then carries it through) — is best done **live**: start the dbgeng backend (`python -m debugger`), attach
during a repro, breakpoint `FUN_005e3810` / `FreeGamePanel_TriggerMPWorldBuild` / `FUN_00457a00`, and read
`panel+0x13c`, `villageList+0x9c`, and which branch fires. Static RE can continue on the `+0x13c` setter, but
the live read is decisive. **The diagnosis is complete; the fix path (Path A + `GameServerAssigned`) is
identified and at least partly stub-reachable — the open piece is the client-side routing into it.**

## Fix path (corrected 2026-07-04)
The teardown is **client-side and stub-unreachable** (see the CORRECTED section). `ANSWER_WORLD_LOGIN_REQUEST`
is a dead lever — proven irrelevant. The only remaining productive work is understanding-first RE, not stub
tweaks:
1. **Determine whether real MP re-hosts the game socket after the room-screen destructor `Shutdown`.** If it
   does, find the trigger (an NComm event? a lobby msg?) and whether the stub can supply it. If it does not,
   then the room screen must not be destroyed at match-start in genuine MP — i.e. our host reaches `OnEnter`
   from the wrong screen/state, and the question becomes what the real room→match transition looks like.
2. Trace the `OnEnter` (`vtbl[0x84]`) target object (`FUN_00429940(param_1[0xe])`) and `BuildWorldSequence`
   to see if any networked re-establishment is *attempted* and failing, vs never attempted.

**Status (honest):** Matchmaking — host/join/room/ready/**Start** — all work and are proven. *Loading* the
match may be past the stub approach's reach: at world-build the client severs its own P2P game-socket
(room-screen destructor), and no server-side message we can send prevents a client from destroying its own
socket. The deliverable-grade understanding of the failure is complete; a playable match may require either
the real server's behavior or client-side means the harness forbids.
