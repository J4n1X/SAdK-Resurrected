# SAdK-Resurrected — *Die Siedler - Auferstehung der Kulturen*

A community effort to **resurrect** the long-dead online lobby of the 2008 real-time strategy game
**Die Siedler: Aufbruch der Kulturen** (English: *The Settlers: Rise of Cultures*), abbreviated **SAdK**.
The project name riffs on the game's: *Aufbruch* (rise) → *Auferstehung* (resurrection).

> ## ⚠️ READ THIS FIRST — what this is and is NOT
>
> This repository is a **heavily AI-assisted ("vibe-coded") reverse-engineering journal**
> plus an **experimental, partially-functional** Python lobby-server stub for the long-dead
> 2008 online service of *Die Siedler: Aufbruch der Kulturen* (English: *The Settlers: Rise of Cultures*, "SAdK").
>
> - It is **NOT stable, NOT finished, and NOT a usable private game server.**
> - It is **NOT supported.** No warranty, no guarantees, expect rough edges and dead ends.
> - Most of the RE and most of this code was produced **with LLM assistance**; claims may be
>   wrong, addresses drift between game builds, and large parts of the docs are an
>   archaeological record of theories that were later **refuted**.
> - It ships **no copyrighted game files.** You must own a legal copy of the game and
>   generate/provide everything yourself (see *What you must provide* below).
>
> If you want a polished multiplayer revival, this is **not that** — it is a research log and a
> proof-of-concept. That said, as of **2026-07-27** two unmodified clients can log in, host,
> join, and **actually start and play a match** against each other through this stub. It is
> fragile, environment-dependent, and the in-match end-of-game messages are still unanswered.

---

## What this is

`sadk-lobby` re-implements just enough of the original **TinCat 3.0 / NETMSG** protocol to
walk unmodified game clients through:

**login → lobby chat → server/game browser → 3D lobby world → host/join a game → referee
handshake → a running match.**

The wire format is **data-driven from the game's own `msgdefs.ini`** (the NETMSG schema that
`tincat3.dll` itself loads — 221 message types), so a single generic codec encodes/decodes
messages instead of hand-rolled structs. Alongside the stub, the repo contains the RE
artifacts: a Ghidra source map, protocol notes, the Win10/11 SecuROM boot fix, and the
binding rules of engagement (`HARNESS.md`) — all RE/debugging goes through the Ghidra MCP.

## What it is **not**

- Not a *polished* multiplayer server — matches do start and run, but the lobby world is empty
  (no NPCs/entities), end-of-match reporting is unimplemented, and nothing is hardened or
  load-tested. Expect to babysit it.
- Not a crack or a redistribution of the game — no executables, assets, or memory dumps are included.
- Not address-stable — the RE base changed between game builds; many docs cite **older addresses**.

---

## ✅ What works / ⚠️ Partial / ❌ What doesn't

**✅ Works (offline-testable):**
- **TinCat transport** — 28-byte header, CRC32, handshake, app-payload framing, STRING/MEMBLOCK
  field encodings. This is the one layer pinned by a byte-for-byte golden test.
- **`msgdefs.ini`-driven codec** — generic encode/decode of ~150 NETMSG types; unhandled types
  fall through to a Result-OK ack (no crash).
- **Server-list / game-browser population** — a byte-perfect `170 GameServerData` (village
  `subtype=2` with the `ServerDataBlock` carrying `roomId 1000`; game `subtype=1`) puts a
  joinable entry in the village browser **and** lists a demo game in the in-world game browser.

**✅ Works, but only against a live game client (not reproducible from this repo alone):**
- **Lobby login** — ECDH (secp521r1) + SHA-512 + XOR, Twofish-CTR credentials, token handshake
  completing on a **`153 AddResult` ACK** (not a `214` — the client has no `214` handler).
- **Basic lobby chat** — UC second connection (magic `0x0062`), MOTD, channel join, chat echo.
- **3D lobby-world entry** — after the village-connection login the client parks awaiting an
  inbound `EnterWorld` msg `1000`; the stub pushes it via the real mechanism →
  `SetState(VillageEntered)` → the town-square world **renders** (avatar, minimap, UI).
  Screenshot-confirmed once, on the clean game build. Needs the elevated launch workaround on
  Win10/11.
- **Multi-client** — two+ clients log in as distinct players (host + joiner); hosted games live
  in a process-global registry so one client's game is visible/joinable to another.
- 🏆 **Hosting, joining and STARTING a match (2026-07-27)** — the full referee/match-arbiter
  chain now completes and the match loads and runs. Verified with two consecutive games:
  `RegisterGame(0xDB6)` arrives from both clients and is answered with `RegisterGameAck(0xDB7)`
  + `RegisterGameResult(0xDB8, GameSeed)`, followed by live in-match referee traffic. See
  *How the match-start chain works* below.

**⚠️ Partial / experimental / unverified:**
- **214 ValidateToken** is a best-effort echo; the `207` session key is generated then discarded,
  so a cryptographically-real `214` is not built (only the separate secured-room path needs it).
- **Disc-free single-player launch** via the publisher's SecuROM-free 2014 magazine build is
  *documented* (and is how the RE harness runs) but the exe is **not shipped** and its hash is
  unverified here. The community no-CD crack is **faulty** (crashes on Win11) — don't use it.
- **Win10/11 launch of the genuine exe** — the two SecuROM runtime patches (`docs/BINARY_PATCHES.md`)
  are applied to the running process under the Ghidra MCP debugger; works but is finicky and elevated.
- **Everything after world entry** (WorldLoginAck `1006`, ping/pong, world tick) exists in code but
  is only reached if a real client drives it, and was largely derived on the faulty no-CD build —
  treat as **unproven** (`[TODO]`).

**❌ Doesn't work / not implemented:**
- **End-of-match reporting** — the in-match referee messages `0xDD4` (GiveUpGame) and `0xDC0`
  (FinishGame) arrive and are logged, but are **not acknowledged** (`0xDD5` / `0xDC1`). Matches
  play; they just don't *conclude* cleanly server-side, and no results/ranking are recorded.
- **`GameSeed` is a fixed constant** (`0x5eed1234`). Fine for lockstep determinism as long as
  every client in a match gets the same value — which they do — but it is not a real seed.
- **In-world content** — the lobby world is **empty**: no NPCs, no entities, dead in-world
  browser, in-world chat loops, avatar shows `<UNNAMED>` / default appearance.
- **Spurious UC churn** — the referee assign reply also emits a `192 UsercommServerData`, so a
  fresh UC/chat connection is dialled every 60 s. Harmless in practice, but it is currently also
  the only thing that stands up chat, so the two paths need untangling carefully.

---

## 🏆 How the match-start chain works

This was the project's wall for weeks, so it is worth writing down properly. Getting from
"both players ready" to "match running" is an **eight-step chain**, and *every* link fails
silently if you get it wrong — the frame is accepted, the socket stays open, and nothing is
logged anywhere. "No error" tells you nothing in this subsystem.

| # | Who | What | Gotcha |
|---|-----|------|--------|
| 1 | client | `AssignServer(189, type4/sub4)` at **login** | A **one-shot**. `StatePump_Tick` latches `+0x584`; the only re-arm is `+0x588 < 0`, and `+0x588` is armed *only* by a successful latch. Miss it once and the client never asks again for the whole process lifetime. |
| 2 | **stub** | reply `GameServerData(170)` **type4/sub4** | ⚠️ **Never `4/5`.** `4/5` is special-cased in `tincat3` to a private handler that returns *without* notifying the lobby, so `LM+0x580` never latches. The tell that it worked: `189` starts repeating on an exact **60 s** cadence. |
| 3 | client | creates a connection keyed by the referee's `server_id` | Created **address-less** — it has no idea where to dial yet. |
| 4 | client | at **match start** (not login), `RefereeServerConnection::Login` opens the channel | It **sends no message**. Having no address, the client emits `221 RequestConnectionData(server_id=77)`. |
| 5 | **stub** | reply `222 ConnectionData` → `ip:5481` | ⭐ This is the *only* way a TinCat connection learns its target. The receive state machine reads `server_id`/`ip`/`port`, finds the connection by id, fills its host/port fields and dials. Resolve the referee id here or it silently gets the fallback (we sent it to the world port `:5479` for a while, and the client obediently connected to the wrong listener). |
| 6 | both | normal base TinCat login on `:5481` (handshake → `188` → `211`/`212` → `213` → `153`) | Same login as every other connection. |
| 7 | **stub** | **push** `LoginSuccess(0xDCA){PermID}` | Nothing requests it (see 4) — the server must push it unprompted. The client validates `PermID` against its own perm id and **returns silently** on mismatch. |
| 8 | client → stub | `RegisterGame(0xDB6)` → answer `Ack(0xDB7)` + `Result(0xDB8, GameSeed)` | The match loads. |

### Two facts that will bite you

- The referee assign descriptor must be **type4/sub4**, never `4/5`.
- **LobbyMessage field scalars are BIG-endian** (`struct.pack(">I")`), while the surrounding
  TinCat body scalars are little-endian. A little-endian `PermID` is silently discarded.

## 🔬 How we actually found it (the method)

Four stacked, silent bugs hid this chain. What broke the deadlock was **not** more guessing:

1. **Read the game's own logs.** The client writes `LobbyComm.log`, `comm.log`, `netlog.txt`
   into `Documents/SAdK/dumps/` when launched with the right flag. Line numbers in those
   messages (`LobbyManager.cpp:907`) map straight onto binary addresses, because every
   instrumented function stores `__FILE__`/`__LINE__` into globals before logging.

2. **The binary ships the developers' own symbols.** ~217 `Ns::Class::Method` log-scope strings
   are sitting in the executable — `RefereeServerConnection::RegisterGame`,
   `LobbyComm::System::LoggedIn`, and so on. Grepping those named most of this subsystem for
   free, before any live testing. See `docs/RE_METHOD_RESEARCH.md`.

3. **Time Travel Debugging (TTD) is the tool that ends arguments.** Record once, then query the
   trace offline as many times as you like. The decisive sequence here was three questions:
   `ttd_calls 0x0047ac20` → *1 call* (so the message arrived and dispatched), `ttd_calls`
   on the observer fan-out → *0 calls* (so it was dropped at a guard), then travelling to the
   compare instruction and reading the operands. That named the endianness bug exactly.
   ⚠️ **Record before the moment you care about** — the referee request is a one-shot fired on
   the first login after process start, and two traces were wasted attaching afterwards.
   ⚠️ **`dd` prints the dword *value*** — `01000000` means `0x01000000`, not `1`. Two operands
   looked equal until the flags (`efl 0x246 → 0x216`, ZF cleared) proved otherwise. Trust the
   flags, not the hex.

4. **Prefer a free observable to an expensive one.** Most steps above were confirmed from the
   stub's own log (does a connection appear on `:5481`? does the `189` repeat every 60 s?)
   before spending a 10 GB trace on it.

5. **Write down refutations, not just conclusions.** `engagement_records/` contains the wrong
   models too, with banners saying why they were wrong. The `4/5`-vs-`4/4` descriptor was
   flipped three times across sessions because each attempt only recorded its conclusion. The
   code comments now carry the *evidence*, not the verdict.

---

## 🧩 What you must generate / provide from your own game installation

**No copyrighted game assets are shipped.** The `.gitignore` deliberately excludes all binaries,
dumps, and decrypted assets. To use or extend this you need your **own legal copy** of the game
and must produce the following yourself:

- [ ] **A legal install of *Die Siedler: Aufbruch der Kulturen* (2008).** Everything below is derived from it.
- [ ] **A runnable game exe.** Either the genuine retail exe (CD inserted, or run under the Ghidra
      MCP debugger elevated on Win10/11 with the SecuROM patches in `docs/BINARY_PATCHES.md`), or the
      publisher's SecuROM-free **2014 magazine build** for disc-free single-player (community "SAdK
      2014 Patch"; verify its hash yourself). Plus **NVIDIA PhysX Legacy 9.13.0604** and "Disable
      fullscreen optimizations".
- [ ] **`bin/msgdefs.ini` from your install.** A bundled copy lives at `sadk_lobby/data/msgdefs.ini`,
      but if your build differs, replace it with yours or the wire format may desync.
- [ ] **Point both client configs at the stub:** `data/lobby/config/LobbySettings.ini` →
      `[LobbyServer] Host=127.0.0.1 Port=7070`, and `data/game/settings/network.ini` →
      `[Lobby] url=<host:port>`. Log in with `test` / `test` / `test`.
- [ ] **(RE work) Your own Ghidra project** imported from your `SADK.exe` (image base `0x400000`)
      and `tincat3.dll` (`0x10000000`). Re-apply labels from `docs/SOURCEMAP.md`.
- [ ] **(Asset work) `AdKEd.exe`** (the community KEX/sadk converter, from the Xentax forum) to decrypt/
      re-encrypt the game's UI/scene XMLs via `decrypt_all.ps1` / `BatchConv.bat`.
- [ ] **Python 3** + `pip install -r requirements.txt`.

> ⚠️ Do **not** commit any game binaries, memory dumps, decrypted assets, or your Ghidra project —
> they are copyrighted and the `.gitignore` is set up to keep them out. Keep it that way.

---

## Quick start (finicky — read the caveats above)

```bash
pip install -r requirements.txt          # cryptography, twofish
python -m sadk_lobby                       # or: python tincat_server.py
```

The server opens four listeners:

| Port | Role                                        |
|------|---------------------------------------------|
| 7070 | main lobby connection                       |
| 7071 | UC / chat (2nd connection)                  |
| 5479 | village / world (3rd conn)                  |
| 5481 | referee / match-arbiter (dialled at match start) |

Then point your game install at the stub (see the checklist above) and log in with
`test` / `test` / `test`. Binding `7070` may require running elevated. The stub pushes
`EnterWorld(1000)` automatically once the village connection logs in (no flags). Reaching the 3D
world still requires launching the game elevated on Win10/11 (SecuROM). **It is fragile and
environment-dependent.**

### Playing an actual match

With two clients pointed at the same stub: log both in, let both reach the lobby world, host a
game on one, join from the other, both ready up, press **Start**. The referee chain above runs
by itself. Useful things to watch in the stub log, in order:

```
→ [REFEREE] GameServerData(170) id=77 type4/sub4 …     # step 2 — the latch
→ ConnectionData(222) server=77 → …:5481  [REFEREE]    # step 5 — the address
  CONNECTION #n … -> listener :5481 [referee]          # the dial (this was never seen before 2026-07-27)
→ [REFEREE] LoginSuccess(0xDCA, perm_id=N)             # step 7 — the push
  [REFEREE] ← channel frame msg=0xdb6 …                # step 8 — RegisterGame: you're in
```

If the `189` in step 2 repeats every **60 s**, the latch is working. If it *doesn't* repeat at
all, the assign reply never reached the lobby observer — check the descriptor is `4/4`.

### Wire encoding (from `msgdefs.ini` type tokens)

| Token              | Wire                                             |
|--------------------|--------------------------------------------------|
| `UNBYTE`/`SIBYTE`  | 1 byte (u/s)                                     |
| `UNSHORT`/`SISHORT`| 2 bytes LE                                       |
| `UNLONG`/`SILONG`  | 4 bytes LE                                       |
| `LBOOL`            | 1 byte (0/1)                                     |
| `STRING N`         | int32 length (incl. trailing NUL) + iso-8859-15  |
| `MEMBLOCK`         | int32 length + raw bytes                         |

The leading `type` discriminator lives in the app-payload prefix (`Magic 0x26B6 + Type1 + Type2`),
not the body, so the codec skips it.

## Tests

```bash
python tests/test_codec_golden.py     # 170 reproduced byte-for-byte vs the frozen legacy monolith
python tests/test_server_smoke.py     # end-to-end vs a fake socket
python tests/test_server_browser.py   # server-browser wire + the referee assign descriptor
python tests/test_multi_client.py     # multi-player identities + global game registry
# or: pytest tests/
```

These exercise the wire codec/flow only — **not** the live game. There is no automated coverage
for crypto/auth, chat, the world-entry push, or the referee chain; those are only ever proven by
driving a real client and reading the logs.

## Repo map

```
sadk_lobby/         the stub server package (the actual deliverable)
tools/              only what the Ghidra MCP + a debugger can't do: a passive wire proxy + capture decoders
docs/               protocol + RE reference (SOURCEMAP, LOBBY_PROTOCOL, …); addresses may be from an older build
decomp/             Ghidra MCP link: setup runbook, bridge, rename list (offline dumps are gitignored)
tests/              offline codec / smoke / browser / multi-client tests
CLAUDE.md           authoritative agent instructions
HARNESS.md          binding rules of engagement (MCP-first RE/debug; no faking; honest status; no flags)
MEMORY.md           compact persistent context: proven facts + open TODOs
legacy_tincat_server.py   frozen reference-only monolith (kept for the golden test)
```

## Legal / copyright

This is independent, non-commercial **interoperability and reverse-engineering research** for a
game whose official online service has been **dead since ~2014**. *Die Siedler: Aufbruch der
Kulturen* and all its assets are **© their respective owners** (Funatics / Blue Byte / Ubisoft).

- **No game code, assets, executables, or memory dumps are distributed here.** You must own a
  legal copy and supply your own files.
- The only game-derived file in the tree is `sadk_lobby/data/msgdefs.ini` (a plain-text NETMSG
  schema used for protocol interop). If you object to its inclusion, remove it and supply your own.
- The original community asset tool `AdKEd.exe` (banner: `AdKEd v1.11 (c) 2008 Trass3r`, Xentax forum) is **not** shipped.

## Credits

By **[J4n1X](https://github.com/J4n1X)** — community reverse-engineering of SAdK / TinCat, conducted
as a heavily AI-assisted research project. Protocol facts are grounded in the game's own `msgdefs.ini`
and live analysis through the Ghidra MCP; the Win10/11 SecuROM launch insight and the lobby/world
handshake were derived through that work.

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE). © 2026 **J4n1X**. This covers the
original code in this repository only, **not** any game-derived data or third-party tools.
