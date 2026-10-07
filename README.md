# SAdK-Resurrected — *Die Siedler - Auferstehung der Kulturen*

A community effort to **resurrect** the long-dead online lobby of the 2008 real-time strategy game
**Die Siedler: Aufbruch der Kulturen** (English: *The Settlers: Rise of Cultures*), abbreviated **SAdK**.
The project name riffs on the game's: *Aufbruch* (rise) → *Auferstehung* (resurrection).

The official servers went offline around 2014. This project reverse-engineers the unmodified game
client (`SADK.exe` + `tincat3.dll`) and reimplements the server side it talks to: a Python lobby server
that the real client connects to, plus a small optional client add-on for hosting from behind a router.

> **Status.** Two or more unmodified clients can log in, walk around the 3D lobby village together,
> chat, play the tavern minigames, dress up at the tailor, mail each other, and host, join and finish
> real matches with rewards. It runs as a service and is played on, but it is a research project:
> expect rough edges, and read *What doesn't work yet*.
>
> Most of the reverse engineering and code was produced with heavy LLM assistance. Facts in the docs are
> tagged with their evidence (`[known]`, `[inferred]`, `[PROVEN]` = binary address + live evidence).

---

## Features

**Account and lobby**
- Login with the game's own crypto (ECDH secp521r1 + Twofish-CTR). A new user name is registered on its
  first login with the password used; after that the password must match. `!setpwd` changes it.
- Accounts and characters persist across restarts: character list, creation and deletion, the avatar's
  look, clothing, items, gold, level and last position (the character's save blob is the game's own).
- Message of the day, global and local (per-zone) chat channels, whispers, friends list with presence,
  in-game mail with "YOU'VE GOT MAIL!" notices, and an introduction mail for every new character.

**The 3D lobby village**
- Other players' avatars appear, move and animate; their outfits and levels show correctly.
- NPCs, the tailor (clothing colours, live-tested) and the shops (buying and selling; not yet verified
  in live play).
- Tavern minigames in both taverns: **Dice**, **Poker** and **Pawn Chess**, all live-tested with two
  players.
- Funnies (play money for the minigames): 500 per day on the first visit.
- The advertising screens show a plain board instead of the dead web pages ("Disable billboards" in
  SAdK-ServerConfig; live-tested 2026-10-07).

**Matches**
- Hosting a game, the game browser, joining, the pre-game room, and the full referee chain that lets a
  match load and run (since 2026-07-27).
- End-of-match handling: finish, give-up and chest claims are answered; players earn XP and gold by
  playtime (2-minute minimum), with a bonus for the winner and for chests (which also give an item).
- **Host bridge:** a host behind a router without a forwarded port can still be joined. A small proxy
  `wsock32.dll` next to the game detects this at start-up and routes joiners through the server instead
  (`docs/bridge-protocol.md`). Live-tested 2026-10-07.

**Chat commands**

| Command | Effect |
|---|---|
| `!help` | lists the commands |
| `!setpwd <new>` | changes your password (from the next login on) |
| `!fasttrack` | maximum level plus 100,000 gold and 100,000 funnies |
| `!level <1-5>` | sets your level (which also changes your avatar's look) |
| `!pos <name>` / `!poslist` | saves / lists positions (used to place NPCs) |

## What doesn't work yet

- No rankings or match statistics; there is no ranking server.
- The game's hall of fame / web pages are not served.
- Some village content is unverified in live play (see the status table in `CLAUDE.md`).
- Joining a bridged game requires the bridge `wsock32.dll` on the joiner's side too.
- Nothing is hardened or load-tested.

---

## Playing on a server

You need a legal install of the game and the **SAdK-ServerConfig** tool (`bridge/serverconfig/`):

1. Run `SAdK-ServerConfig.exe`. It finds the game folder (or pick it), shows whether your game data is
   modified, and lets you enter the server's address. *Advanced configuration* exposes the ports.
2. Click **Save**. It writes the game's lobby and network settings and installs the bridge shim
   (`bin\wsock32.dll`).
3. Start the game and log in with any new name and password; the first login registers it.

The bridge shim and map sharing need the **DRM-free build of `SADK.exe`** (MD5
`d4832bc5103c14f5445471af29b8d778`), because the shim calls game functions at fixed addresses. On any other
build the tool still configures the server but doesn't install the shim.

The tool warns when your game data differs from the original: the game kicks joiners whose data
checksum differs from the host's, so only players with the same modifications can play together.

**Windows 10/11:** the original retail exe is SecuROM-protected and needs the runtime fixes in
`docs/BINARY_PATCHES.md`; the publisher's later DRM-free build runs as is. Install the NVIDIA PhysX
Legacy driver (9.13.0604) if the game reports `NxCreatePhysicsSDK failed`.

## Running a server

```bash
pip install -r requirements.txt     # cryptography, twofish
python -m sadk_lobby                # or as a systemd service, see below
```

The server reads the game's own message schema, `msgdefs.ini`, from `sadk_lobby/data/msgdefs.ini` and refuses to
start without it. It is copyrighted game data, so neither this repository nor the release includes it: copy
`bin\msgdefs.ini` from your game installation into `sadk_lobby/data/` (in the release: `server/sadk_lobby/data/`).

| Port (TCP) | Role |
|---|---|
| 7070 | lobby (login, characters, game browser, mail, friends) |
| 7071 | chat |
| 5477 | lobby village (3D world) |
| 5481 | referee (match start and end) |
| 7072 | host bridge: control and data |
| 7073 | host bridge: joiners |

Set `SADK_ADVERTISE_IP` to the server's **public** IP (its LAN IP for a LAN-only server): the lobby
hands that address to clients for their chat, village, referee and bridge connections. It defaults to
`127.0.0.1`, which only works for a client on the same machine. Players are stored in `sadk_players.json` and mail in
`sadk_mail.json` beside it. `tools/start_server_upnp.sh` opens the ports via UPnP and starts the
server. The maintainer runs it as a systemd user service (`systemctl --user restart sadk-lobby`,
logs via `journalctl --user -u sadk-lobby`).

Hosting a match needs the host's game port (TCP 5479 by default) reachable, or the bridge.

## Tests

```bash
for t in tests/test_*.py; do python3 "$t"; done     # or: pytest tests/
```

The tests cover the wire codec (a byte-for-byte golden test), login, characters and saves, chat,
mail, friends, the village economy, all three minigames, the referee and rewards, and the bridge,
against fake sockets. Live behaviour is only ever proven against a real client.

---

## For reverse engineers

- **`sourcemap/`** — everything named and typed in Ghidra, for both binaries: ~30,000 named functions
  with signatures, 1,500+ classes and namespaces, 4,300 data types, labels and comments. Import it
  into your own Ghidra on your own copy of the DRM-free `SADK.exe` and `tincat3.dll` with
  `ApplySourcemap.java` (see `sourcemap/README.md`).
- **`sadkmod/`** — a C++ library for modding the game from inside its process: typed declarations of the
  game's functions, classes and globals generated from the sourcemap (17,000+ callable functions, 2,300
  types with checked layouts), byte patches that check what they replace, MinHook-based hooks, mirrors of
  the MSVC 2005 `std::string` / `vector` / `list`, and a verify mode that checks a mod's patches against
  `SADK.exe` without running it. The bridge shim is built on it. See `sadkmod/README.md`.
- **`docs/message-catalog.md`** — the protocol reference: every message the client sends or handles,
  what it expects back, and why, with binary addresses.
- `docs/types.md` (structs and classes), `docs/subsystems.md`, `docs/village-and-character-protocol.md`,
  `docs/bridge-protocol.md`, `docs/map-format.md`.
- **`HARNESS.md`** — the rules the work follows: reverse engineering through the Ghidra MCP, live
  debugging through the Frida MCP (`tools/frida_mcp/`), no faked results, honest status.

### How the match-start chain works

Getting from "both players ready" to "match running" is an eight-step chain, and every link fails
silently if it's wrong: the frame is accepted, the socket stays open, and nothing is logged.

| # | Who | What | Gotcha |
|---|-----|------|--------|
| 1 | client | `AssignServer(189, type4/sub4)` at login | A one-shot: if it isn't latched, the client never asks again for the process lifetime. |
| 2 | server | reply `GameServerData(170)` type4/sub4 | Never `4/5`: tincat3 routes that to a private handler that doesn't notify the lobby. When it works, `189` repeats every 60 s. |
| 3 | client | creates a connection keyed by the referee's `server_id` | It has no address yet. |
| 4 | client | at match start, asks `221 RequestConnectionData(server_id=77)` | — |
| 5 | server | reply `222 ConnectionData` with the referee's ip:port | The only way a TinCat connection learns where to dial. |
| 6 | both | the normal TinCat login on the referee port | Same as every other connection. |
| 7 | server | push `LoginSuccess(0xDCA){PermID}` unprompted | `PermID` must be big-endian or the client silently drops it. |
| 8 | client → server | `RegisterGame(0xDB6)` → `Ack(0xDB7)` + `Result(0xDB8, GameSeed)` | The match loads. |

LobbyMessage field scalars are big-endian; the surrounding TinCat message fields are little-endian.

### Wire encoding (`msgdefs.ini` type tokens)

| Token | Wire |
|---|---|
| `UNBYTE` / `SIBYTE` | 1 byte |
| `UNSHORT` / `SISHORT` | 2 bytes LE |
| `UNLONG` / `SILONG` | 4 bytes LE |
| `LBOOL` | 1 byte (0/1) |
| `STRING N` | int32 length (incl. NUL) + ISO-8859-15 bytes |
| `MEMBLOCK` | int32 length + raw bytes |

The message schema comes from the game's own `msgdefs.ini` (supplied from your install into `sadk_lobby/data/`),
so one generic codec encodes and decodes every message.

## Repo map

```
sadk_lobby/          the server (Python package)
sadkmod/             C++ modding library: generated game declarations, patches, hooks (sadkmod/README.md)
bridge/wsock32_shim/ the host bridge's client side and the game patches (proxy wsock32.dll, C++ on sadkmod)
bridge/serverconfig/ SAdK-ServerConfig, the Windows setup tool (C, Win32)
sourcemap/           Ghidra map of SADK.exe and tincat3.dll + its import script
docs/                protocol and RE reference
tests/               offline tests
tools/               wire proxy and capture decoders, the Frida MCP, CVar client
mapping/             the whole-binary mapping run's infrastructure
CLAUDE.md, HARNESS.md   instructions and rules for the agents doing the work
```

## Legal / copyright

This is independent, non-commercial interoperability and reverse-engineering research for a game whose
official online service has been dead since ~2014. *Die Siedler: Aufbruch der Kulturen* and all its
assets are © their respective owners (Funatics / Blue Byte / Ubisoft).

- **No game code, assets, executables or memory dumps are distributed here.** You need a legal copy.
  The sourcemap contains only names, types and comments keyed by address, no game bytes.
- The server needs the game's own message schema `msgdefs.ini`, which every player has in the game's `bin`
  folder. It is not distributed here: you copy it from your own installation.
- Third-party community tools (e.g. `AdKEd.exe` for the game's encrypted asset files) are not shipped.

## Credits

By **[J4n1X](https://github.com/J4n1X)**, as a heavily AI-assisted research project. Protocol facts are
grounded in the game's own `msgdefs.ini` and in analysis of the client through the Ghidra and Frida MCPs.

## License

Released under the **MIT License** — see [`LICENSE`](LICENSE). © 2026 **J4n1X**. This covers the
original code in this repository only, not any game-derived data or third-party tools.
