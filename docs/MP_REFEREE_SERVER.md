# MP Referee Server — the match-start gate

**Status (s39.6):** implemented + model CORRECTED; awaiting the live `:5481`-connect confirm.
Binary model: `docs/REFEREE_RE_corrected.json` (the authoritative 2nd workflow) + `docs/REFEREE_RE_findings.json`
(1st workflow; its "2nd-189" trigger was REFUTED) · `memory/mp-match-start-needs-referee-server.md` ·
ER `engagement_records/2026-06-09_referee-server.md`.

> ⚠️ **CORRECTION (s39.6, after Part B did nothing):** there is **no 2nd `189`**. SADK sends the type-4
> `AssignServer(189)` **exactly once** (one latched state-pump caller). That **single login `189` IS the
> referee assign** — the stub was mis-answering it with `192` (UC). FIX: answer the single type-4 `189` with
> `170` (type=4, subtype=5, **same `ticket_id`** → tincat3 cat-`0x108` → sets `LM+0x580`) **and** push an
> unsolicited `192` (`REFEREE_ALSO_PUSH_UC`, default True) so chat still reaches `:7071`. The `8777`
> `[Lobby] url` is the NComm net-driver "site", unrelated to the referee. The flow below reflects this.

## Why a referee at all

MP matches are **peer-to-peer**. A ranked result therefore can't be trusted to either peer — a losing
host could just quit. SAdK's answer (a bolt-on over the base DNG engine, which had no referee) is a
**Referee Server**: a trusted third connection the client opens at match start that watches the game, so
the outcome survives a rage-quit. The client makes the referee login **mandatory** — on every
`NE_StartLoading` it tries `RefereeServerConnection::Login` up to 5× (`[Reconnector] timesClientRetries`)
and **aborts the match** if it can't. Our stub ran lobby/UC/world but no referee → every match aborted
~13 s after StartLoading (seen in both clients' `comm.log`).

## The flow we implement (build 34688, all [PROVEN] except the one noted)

```
LobbyManager state>5 ──> client sends AssignServer(189, server_type=4) on the lobby conn (ticket cat 0x108)
   stub ──> GameServerData(170)  server_type=4, server_subtype=5, ticket_id echoed, server_id=REF, ip, REFEREE_PORT
            (tincat3 FUN_10021520 gates the referee path on type==4 && subtype==5; writes server_id → LM+0x580)
   stub also advertises that same referee (170, type4/sub5) on the type-4 server-list  ──> pComm caches id→ip:port
client ──> resolves REF id → ip:port, dials REFEREE_PORT, runs the SAME base login as UC/village
            (CheckVersion 188 → token 211/213 → AddResult 153), then opens the referee data channel
   stub ──> PUSH LoginSuccess (bare LobbyMessage, cat=3, id=0xDCA, one field PermID)     [clears the gate]
            └─ the verdict is the MESSAGE ID (0xDCA ok / 0xDCB fail); PermID is never validated
[optional, only if the host emits it] client ──> RegisterGame(0xDB6)
   stub ──> RegisterGameAck(0xDB7, Result=0) + RegisterGameResult(0xDB8, Result=0, GameSeed)
```

**The one un-nailed byte:** the LobbyMessage type word is `names<<15 | cat<<12 | id`. Whether LoginSuccess
is sent **names-off** (`0x3DCA` + a bare u32 PermID — the primary bet, matching the client's own send-side)
or **names-on** (`0xBDCA` + name-keyed `PermID` + `0xFFF` end-marker) is statically undetermined. The
first live capture settles it.

## What's in the stub

| File | Change |
|---|---|
| `config.py` | `REFEREE_PORT=5481`, `REF_SERVER_ID=60`, `REF_*` msg-id constants, flags `ADVERTISE_REFEREE_SERVER`/`ARM_REFEREE`/`REF_LOGIN_SUCCESS_NAMES` (all default-OFF) |
| `referee.py` (new) | the `cat=3` LobbyMessage codec + `build_login_success` / `build_register_game_ack` / `build_register_game_result`, `push_login_success`, `handle_frame` (capture + RegisterGame ack) |
| `connection.py` | `is_referee` flag; `cat=3` data frames → `referee.handle_frame`, base-login frames fall through to the normal dispatch |
| `server.py` | a `REFEREE_PORT` listener (when `ADVERTISE_REFEREE_SERVER`) |
| `dispatch.py` | `AssignServer(189)`: the **2nd** type-4 assign on a conn → `170` (subtype 5) referee, the 1st stays UC `192`; referee advertised on the type-4 list; on the referee conn's 153, push `LoginSuccess` (when `ARM_REFEREE`) |

Tests: `tests/test_referee.py` (codec golden + dispatch smoke + flag-OFF byte-identical parity).

## How to test (staged — Part A then B)

> Both flags are wire changes covered by the ER (pre-approved). Run the stub on the machine the clients
> point at; have a host + a joiner (`test` / `test2`).

**Part A — capture the framing (read-only in effect).** Set `config.ADVERTISE_REFEREE_SERVER = True`
(leave `ARM_REFEREE = False`). Start a 2-client match. In `tincat_server.log` confirm:
- the client **connects to :5481** and completes the base login (188/211/213 → 153) — proves assignment +
  resolution worked (no `"Could not initialize RefereeServerConnection."` client-side);
- log any referee frame the client sends — it reveals the names-flag convention and whether a pre-login
  precedes the channel-open.

**Part B — push LoginSuccess.** Also set `config.ARM_REFEREE = True`. Start a match again. Success =
the match proceeds **past** `NE_StartLoading` (the clients' `comm.log` no longer shows the ~13 s-then-
`ShutDown` abort). If it still aborts, flip `config.REF_LOGIN_SUCCESS_NAMES = True` (names-on) and retry;
if both fail, capture the bytes and we refine the codec — do not claim success on an un-cleared gate.

**Precise read-only check (optional):** RPM-probe App-obj `+0x362c` (login attempts; success = never
reaches 5) and `+0x3624` (pending; success = 1→0), and `LobbyManager+0x580` (referee addr; non-zero =
assigned). Offsets are build-34688.

## Not yet done (deferred, separate ERs)

End-of-match (`FinishGame 0xDC0` / `GiveUpGame 0xDD4` / `ClaimChest 0xDAC` acks) and the lobby ranking
NETMSGs (`GameResultSubmit 252/253`, ranks `254-257`) are **not on the start path** — logged, acks
deferred. Whether a single revival host even emits `RegisterGame` (vs `LoginSuccess` alone sufficing) is
the open question the first live test answers.
