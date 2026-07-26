# HANDOFF — pick-up note for the next agent (2026-07-26, night)

Branch `master`, clean tree. Today was a **correction + elimination** session: no stub wire changes,
three commits (`610408f`, `d0e869f`, `572fa8b`), all docs/RE. Several long-standing "facts" turned out
to be wrong — including ones stated confidently in the previous version of this file. Read the
corrections before trusting anything older than this.

## Read first
1. `CLAUDE.md`  2. `HARNESS.md` (binding rules)  3. `MEMORY.md` (index)
4. **`decomp/RENAME_LIST.md`, the four `2026-07-26` sections** — the whole derivation, in order.
5. `docs/LIVE_DEBUG_RUNBOOK.md` **§8** — ServerList field map, the `this+8` trap, trace sets.
6. `docs/LOBBY_SCREEN_VTABLES.md` — corrected `LobbyComm::ServerList` field table.

## Milestone: Host + Join matches. Status: **the lobby half is now cleared end to end.**

---

## ⭐ The one thing to internalise: `LobbyComm::ServerList` has TWO vtables

`LobbyComm_ServerList_ctor@0x0046a160`:
```
0046a1a6  MOV [ESI],       0x7dafcc   ; primary                        -> this = ServerList+0
0046a1ac  MOV [ESI + 0x8], 0x7daf8c   ; CommLayer::IGameServerObserver -> this = ServerList+8
```
**Every** callback in the `0x7daf8c` table runs on `this = ServerList + 8`, so all offsets quoted inside
them are +8 shifted. **LIVE-CONFIRMED 2026-07-26**: observer `this = 0x0E6A45CC` while the base was
`0x0E6A45C4`. Misreading this produced two wrong "facts" and a multi-session hunt for an "unidentified
sixth writer" of `+0x9c` that does not exist.

| field | type | meaning |
|---|---|---|
| `+0x9c` | u32 | hosting latch: `0xFFFFFFFF` INVALID · `0xFFFFFFFE` PENDING · else the real assigned id |
| `+0xa0` | **bool** | a byte flag — **not** a callback pointer |
| `+0xa4`/`+0xa8` | ptr/fptr | pending **referee** callback, armed only by `RequestRefereeServer@0x00468f80` |

Writers of `+0x9c` — **five, all named**: ctor→INVALID · `CreateGameServer@0x0046aaa0`→PENDING ·
`CreateResultReceived@0x0046a6a0`→real id / INVALID+Shutdown · `DeleteResultReceived@0x00469990`→INVALID ·
`DestroyGameServerAndShutdown@0x00468410`→INVALID.

## What actually happens at match-start — traced live, end to end

```
[21] CreateResultReceived(id=100, errorCode=0)     hosting latches. WORKS.
[17] DestroyGameServer(ServerList)                 client self-delists -> 169. Its own doing.
[19] CLobby_RequestExitVillage@0x004f5090          the exit hatch. FIRES.
[22] SetState(0x0A LeavingVillage)                 via the 2002 sender
[22] SetState(0x0B VillageLeft)                    via HandleLoggedOut, 110 ms. CLEAN.
[18] DeleteResultReceived(errorCode=0)             +0x9c -> INVALID  <-- 360 ms AFTER the leave
```
Stub side, same moment: **both** clients sent 2002, dropped **both** world (:5479) and UC (:7071)
connections, then re-subscribed to the server-list observers — i.e. back to *browsing*.

**The "Verbindung zu Spieleserver" modal is a stuck SCREEN, not a stuck protocol.** `+0x9c` only goes
INVALID *after* the leave already completed; from that frame the still-visible `SetupGameDialog`
(`Update@0x00457a00`, host-only via `NComm_IsHost()`) shows the modal and early-returns every frame.

## Killed this session — do not re-run these

- ⛔ **The entire "Step 1" plan in the previous HANDOFF** — hardware write-watchpoint on `+0x9c` to catch
  a "6th writer". There is no 6th writer; the five above are the complete set, found by a scripted store
  sweep. (And `debugger_watch_memory` rejects heap addresses, as the older doc originally said.)
- ⛔ **"`villageList+0x9c` = assign state, `+0xa0` = a callback fn-ptr"** — the previous HANDOFF's
  "Corrected:" line. It was the correction that was wrong; the ORIGINAL names were right.
- ⛔ **"`+0x9c = 0xFFFFFFFF` means PENDING"** — that is INVALID. PENDING is `0xFFFFFFFE`.
- ⛔ **"`GameServerAssigned` clears the game-server gate"** — it is the *referee* completion and never
  touches `+0x9c`.
- ⛔ **"Pushing `GameServerAssigned` would crash on a garbage callback"** — refuted; the ctor zeroes it.
- ⛔ **"The exit hatch silently no-ops"** — my own hypothesis, refuted live: `CLobby+0x270 = 3` and
  `+0xc0 = 0x25DEFA70` (non-NULL), so it took the dispatch branch and worked.
- ⛔ **A third delivery-shape experiment on the 168** — `CreateGameServer`'s only callers are
  village-screen UI actions, not the game-room Start button. Killed before it cost a live run.
- ⛔ **`running=true` broadcast** — reverted in `a2377d2` as unsupported (`170.running` appears nowhere
  in the match-load path); ER marked ABANDONED. `MEMORY.md` used to claim it was implemented, deployed
  and awaiting a live test. It was not. That entry is now corrected.

## Where the wall actually is, and the two leads

The wall sits where `MEMORY.md`'s `mp-host-join-ready-start-works-wall-match-load` already put it:
**nothing initiates the match world load after VillageLeft(11).** Two concrete leads from tonight:

1. **No `AssignServer(189)` ever fired and nothing dialled `:5481`** — despite `MEMORY.md` recording
   "VillageLeft(11) → arms the referee", and despite `referee-delivery-proven-live` having that path
   working. Either that model is wrong or the arm is conditional on something absent. **Start here** —
   it is a named path we already know how to answer.
2. **What is supposed to move the host off `SetupGameDialog`?** The client went back to browsing
   (re-subscribed type 4/5) while the screen stayed put.

## Environment left as-is
- Stub live on `linux-server`, ports 7070/7071/5479/5481, logging to `stub_n.out`, current master.
  Deployed content == master. (Four modules differ from local on md5 by **CRLF vs LF only** — strip CR
  before comparing across a Windows→Linux deploy; a raw hash compare is not a valid equality test.)
- Debugger **detached**; game pid 54956 left running. Tonight's six-trace set is recorded in
  `decomp/RENAME_LIST.md` if you want to re-arm it.
- Ghidra: program `sadk_noav.exe`, addrs 1:1 (SADK@0x400000, tincat3@0x10000000). All names/labels/plate
  comments from today are applied and saved.

## Method notes worth keeping
- **Check for secondary vtables before trusting any quoted offset.** "When static and live disagree,
  live wins" still holds — but this session the reverse also bit: a wrong *base* made live reads look
  like they refuted a correct model.
- **Check the artifacts you already have before spending a live run.** The whole match-start chain was
  sitting unread in `minisrv:stub_gsassign.out` / `stub_final.out` from earlier sessions.
- A named function is not a verified one. `CLobby_RequestExitVillage` is an *inferred* name (from the
  `+0x80` neighbour and the shared `+0xc0` action object) — flagged `[TODO]` in its plate comment.
