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
> If you want a working multiplayer revival, this is **not that** — it is a research log and
> a proof-of-concept that gets a single real client to *render the 3D lobby world* and *see
> game browsers*, nothing more.

---

## What this is

`sadk-lobby` re-implements just enough of the original **TinCat 3.0 / NETMSG** protocol to
walk one unmodified game client through:

**login → lobby chat → server/game browser → into a (mostly empty) 3D lobby world.**

The wire format is **data-driven from the game's own `msgdefs.ini`** (the NETMSG schema that
`tincat3.dll` itself loads — 221 message types), so a single generic codec encodes/decodes
messages instead of hand-rolled structs. Alongside the stub, the repo contains the RE
artifacts: a Ghidra source map, protocol notes, read-only memory probes, a Win10/11 launch
workaround for the game's SecuROM DRM, and an "engagement record" discipline (see `HARNESS.md`)
for how live-game experiments were gated.

## What it is **not**

- Not a playable multiplayer server — there is no working game room, no hosting, no NPC/entity
  population, and no real two-player path.
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
  Screenshot-confirmed once, on the clean game build. This is **gated behind a config flag**
  and an approved engagement record, and needs the elevated launch workaround on Win10/11.

**⚠️ Partial / experimental / unverified:**
- **214 ValidateToken** is a best-effort echo; the `207` session key is generated then discarded,
  so a cryptographically-real `214` is not built (only the separate secured-room path needs it).
- **Game browser (`subtype=1`)** is implemented but **default-OFF** with live preconditions still owed.
- **Disc-free single-player launch** via the publisher's SecuROM-free 2014 magazine build is
  *documented* (and is how the RE harness runs) but the exe is **not shipped** and its hash is
  unverified here. The community no-CD crack is **faulty** (crashes on Win11) — don't use it.
- **Win10/11 launch of the genuine exe** via `tools/debugger_loader.py` (a transparent debug loop
  that lets SecuROM's exception handler run) — works but must be edited per-machine and run elevated.
- **Everything after world entry** (WorldLoginAck `1006`, ping/pong, world tick) exists in code but
  is only reached if a real client drives it, and was largely derived on the faulty no-CD build —
  treat as **unproven**.

**❌ Doesn't work / not implemented:**
- **Hosting / pre-game room** — the SetupGame dialog opens but all player slots are empty; the
  per-slot room protocol (occupant/tribe/team/color/ready) is **unidentified**. "We are not
  transmitting that data yet."
- **In-world content** — the rendered world is **empty**: no NPCs, no entities, dead in-world
  browser, in-world chat loops, avatar shows `<UNNAMED>` / default appearance.
- **Real play-together** — single hardcoded test account; multi-user is a TODO; two clients need
  two machines/VMs. **Not playable.**

---

## 🧩 What you must generate / provide from your own game installation

**No copyrighted game assets are shipped.** The `.gitignore` deliberately excludes all binaries,
dumps, and decrypted assets. To use or extend this you need your **own legal copy** of the game
and must produce the following yourself:

- [ ] **A legal install of *Die Siedler: Aufbruch der Kulturen* (2008).** Everything below is derived from it.
- [ ] **A runnable game exe.** Either the genuine retail exe (CD inserted, or via
      `tools/debugger_loader.py` elevated on Win10/11), or the publisher's SecuROM-free **2014
      magazine build** for disc-free single-player (community "SAdK 2014 Patch"; verify its hash
      yourself). Plus **NVIDIA PhysX Legacy 9.13.0604** and "Disable fullscreen optimizations".
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

The server opens three listeners:

| Port | Role                       |
|------|----------------------------|
| 7070 | main lobby connection      |
| 7071 | UC / chat (2nd connection) |
| 5479 | village / world (3rd conn) |

Then point your game install at the stub (see the checklist above) and log in with
`test` / `test` / `test`. Binding `7070` may require running elevated. Reaching the 3D world
additionally requires opting into the gated `ARM_ENTER_WORLD` behavior and launching the game
via the elevated loader on Win10/11. **It is fragile and environment-dependent.**

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
python tests/test_codec_golden.py     # 170 reproduced byte-for-byte
python tests/test_server_smoke.py     # end-to-end vs a fake socket
python tests/test_server_browser.py   # default wire unchanged + flag gating
# or: pytest tests/
```

These exercise the wire codec/flow only — **not** the live game. There is no automated coverage
for crypto/auth, chat, or the world-entry push.

## Repo map (post-cleanup)

```
sadk_lobby/         the stub server package (the actual deliverable)
tools/              read-only RE probes + the Win10/11 debugger_loader + asset/decode helpers
docs/               protocol + RE reference (SOURCEMAP, LOBBY_PROTOCOL, …); some addresses are stale
decomp/             Ghidra workflow: MCP bridge, index extractor, rename list (dumps are gitignored)
tests/              offline codec / smoke / browser tests
templates/          the Engagement Record template (pre-mutation discipline)
engagement_records/ append-only ledger of approved live-game experiments
HARNESS.md          binding rules-of-engagement for touching the live game (read-only by default)
AGENTS.md           technical onboarding: protocol facts, ports, crypto, Win11 fix, tooling
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
and live read-only memory probes; the Win10/11 SecuROM launch insight and the lobby/world handshake
were derived through that work.

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE). © 2026 **J4n1X**. This covers the
original code in this repository only, **not** any game-derived data or third-party tools.
