# AGENTS.md — sadk_decoder

> Onboarding + reference for AI agents and humans working in this directory.
> ⚠️ **Some status claims below are stale.** For the current honest state of what works vs. doesn't,
> see [`README.md`](README.md). Many addresses refer to an older game build (`docs/SOURCEMAP.md` is
> the firmest reference). This is technical RE reference, not a status report.
> When protocol facts, file roles, or the frontier change, update the relevant section here
> instead of starting a fresh scratch doc.

---

## 1. Overview & goal

This project revives the dead online lobby of **Die Siedler: Aufbruch der Kulturen**
("The Settlers: Rise of Cultures", Funatics / Blue Byte / Ubisoft, 2008) — abbreviated
**SAdK**. It is the German standalone built on the *Settlers II: 10th Anniversary*
(DNG) engine. The official servers died ~2014.

**Method:** reverse-engineer the client (`SADK.exe` + `tincat3.dll`, the "TinCat 3.0.53"
netcode) and stand up a Python **stub lobby server** that the real, unmodified client
connects to. No game files are patched; we just speak the protocol.

There are **two tracks** in this folder:

- **Track B — Online lobby revival (the active frontier).** Get the client to log in,
  reach the lobby, and enter the 3D lobby world against our stub. This is `sadk_lobby/`.
- **Track A — Game asset decoding & modding (the original purpose).** Decrypt the game's
  `.KEX` / `sadk` data files to editable XML/Lua via the bundled `AdKEd.exe`. See §5.

> Note on "Track A/B" naming: in this file and `README.md`, **Track A = asset decoding /
> Track B = lobby revival**. In `docs/ROADMAP.md` the labels are reversed (**Track A = finish
> the lobby server / Track B = the Win11 client fix**). Read by content, not by letter.

### Current high-level status (2026-06)

| Piece | State |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list | ✅ working |
| Room-assign → "Suche Server" (village) button lit + clickable | ✅ working |
| Village-enter → **3D lobby world renders** ("Betrete Welt…", avatar visible) | ✅ reached |
| Runs on **Windows 11 x64** (SecuROM-vs-modern-OS crash) | ✅ **FIXED** — `tools/debugger_loader.py` |
| Runs on **Windows 7** natively | ✅ (SecuROM resolves its VM imports correctly there) |
| Final world entry over the world server (`:5479`) | ⏳ blocked: post-`214 ValidateToken` stall (see §8) |

The months-long blockers (server-list population, room-assign, the Win11 crash) are all
**solved**. The remaining work is building out the world-entry grant + the `:5479` world
protocol (`docs/ROADMAP.md` Track A).

---

## 2. Architecture of the stub (`sadk_lobby/`)

A Python package implementing the reverse-engineered TinCat 3.0.53 / NETMSG protocol.
Run with `python -m sadk_lobby`. The defining idea: the wire format is **data-driven
from the game's own `msgdefs.ini`**, not hand-rolled.

```
sadk_lobby/
  __main__.py      python -m sadk_lobby entry point
  config.py        constants, ports, test account, paths, wire-format toggles
  log.py           thread-safe logging + hex dump
  tincat.py        CRC32, 28-byte frame build/parse, BinaryReader/Writer (wire primitives)
  msgdefs.py       parse msgdefs.ini -> ordered MessageDef registry (221 types)
  codec.py         encode_body / decode_body for ANY message type, generically
  crypto.py        ECDH (secp521r1) + Twofish-CTR login handshake
  chat.py          chat/UC second-connection payloads + handlers (magic 0x0062)
  village.py       village/world third-connection payloads + handlers (msg 1000)
  connection.py    Conn: per-socket framing state machine + receive loop
  dispatch.py      lobby message dispatch table (handlers; default = Result-OK ack)
  server.py        the three listeners + accept loops + main()
  data/msgdefs.ini bundled copy of the game's own NETMSG schema
```

### `msgdefs.ini` — the authoritative schema (consult FIRST)

`msgdefs.ini` ships in the game's `bin/` directory and is the schema `tincat3.dll`
**itself** loads to (de)serialize every NETMSG. It is the **single source of truth** for
the wire format: 221 message types with exact field layouts. It **overrides** any RE
guesses and the (frequently wrong) C#/Go emulator field definitions.

- A bundled copy lives at `sadk_lobby/data/msgdefs.ini` (also the game's `bin/msgdefs.ini`).
- `msgdefs.py` parses it into a `{type_num: MessageDef}` registry on import.
- Each section is `[NETMSG_TYPE_<n>]`; the friendly name is the `#`-comment line above it.
- The leading `type="UNSHORT"` field of each message is the **type discriminator**; on the
  wire it lives in the app-payload prefix (Magic + Type1 + Type2), **not** the body, so the
  codec skips any field literally named `type`.

**Field type tokens → wire encoding** (see `tincat.py` / `msgdefs.py`):

| Token               | Wire                                                              |
|---------------------|------------------------------------------------------------------|
| `UNBYTE` / `SIBYTE` | 1 byte (unsigned / signed)                                       |
| `UNSHORT`/`SISHORT` | 2 bytes LE                                                       |
| `UNLONG` / `SILONG` | 4 bytes LE                                                       |
| `LBOOL`             | 1 byte (0/1)                                                     |
| `STRING [N]`        | int32 length (INCLUDES the trailing NUL) + bytes, **iso-8859-15** |
| `MEMBLOCK`          | int32 length + raw bytes                                          |

String/blob edge cases (byte-exact, do not "fix"): `None` → length 0 (4 zero bytes);
empty string `""` → length 1 + a single NUL byte (distinct from `None`, which the client
renders as `<UNNAMED>`).

### Connection / dispatch model

- **`Conn`** (`connection.py`) owns one client socket and runs the 28-byte-header state
  machine (`PREFIX` → `PAYLOAD`). It handles the TinCat handshake, then routes each
  application frame by listener role:
  - **village** connections → `village.handle_frame` (raw logging while we RE the protocol).
  - frames whose first u16 == `0x0062` → `chat.handle_frame` (the chat sub-protocol).
  - everything else → `codec.decode_body` → `dispatch.dispatch_lobby`.
- **`dispatch.py`** has a `HANDLERS` table keyed by message type. Handlers have signature
  `fn(conn, fields: dict, ticket: int)`. **Anything without an explicit handler falls
  through to a Result-OK ack (`type 42`)**, so no message type is ever left unanswered.
  Decoded `fields` use the canonical `msgdefs.ini` names.

### Login crypto (`crypto.py`) — fully working

1. **`StartAuthenticateSession (201)`** carries the client's **secp521r1** public key in a
   custom DER. We do **ECDH**, SHA-512 the shared point, XOR a random 32-byte secret with
   it, and reply **`AckAuthenticateSession (202)`** with our pubkey + the XORed secret.
2. Credentials (`203`/`204`/`206`) arrive **Twofish-CTR** encrypted under that secret.
   Blob = `nameLen(1B) + name + pwdLen(1B) + pwd` (+ optional CD-key triplet).
3. We reply **`SessionKey (207)`** with a Twofish-encrypted session key + `perm_id`.

> ⚠️ Known gap: the `207` session key is currently `os.urandom(32)` and then **discarded**
> (`dispatch.py`). The later `214 ValidateToken` token crypto almost certainly keys off
> *that* session key — which is why `214` is only a best-effort echo today. See §8.

### Ports / the three connections

| Port | Listener label | Role |
|------|----------------|------|
| **7070** | `lobby` | main lobby connection (login, server list, properties, MOTD) |
| **7071** | `uc`    | UC / chat **second connection** (AdK-specific; magic `0x0062`) |
| **5479** | `world` | village / world **third connection** (the 3D lobby world; msg `1000`) |

The server binds all three on `0.0.0.0`. Lobby `7070` may need admin to bind (the server
errors with a clear "Run as Administrator" message if not).

---

## 3. How to run

```powershell
pip install -r requirements.txt          # cryptography, twofish
python -m sadk_lobby                       # starts all three listeners
```

Optional: `python -m sadk_lobby --port 7070 --log path\to\tincat_server.log`.

**Advertise IP.** The stub tells the client which address to dial back for the chat/village
servers. Default `127.0.0.1` (game + stub on one machine). For the VM test (game in a Win7
VM, stub on the host) set the **host's IP as seen from the VM**:

```powershell
$env:SADK_ADVERTISE_IP = "<host-ip-as-seen-from-the-VM>"; python -m sadk_lobby
```

Listeners still bind `0.0.0.0`; only the advertised address changes.

### Point the client at the stub — BOTH files

Two independent config files must point at the stub or the client falls back to the dead
real servers:

1. `data/lobby/config/LobbySettings.ini` → `[LobbyServer]` `Host` and `Port`
   (the LobbyComm lobby — `127.0.0.1` / `7070`).
2. `data/game/settings/network.ini` → `[Lobby] url` (the engine/NComm lobby-master endpoint;
   default `81.3.59.139:8777`). Also set `[Lobby] patchlevel = 9212` (the AdK version the
   client filters on).

**Test account:** username `test` / password `test` / serial `test`.

---

## 4. Protocol quick facts (TinCat 3.0.53)

- **Frame header:** 28 bytes (`PREFIX_SIZE = 0x1C`) —
  `Magic(4) From(4) To(4) Type(4) Unknown1(4) PayloadSize(4) Checksum(4)`, all LE.
- **Header magic:** `0xDABAFBEF` (bytes `EF FB BA DA`). From-client `0xEFFFFFEE`,
  from-server `0xEFFFFFCC`.
- **Frame types:** 3 = HandshakeConnect, 5 = HandShakeConnected, 2 = ApplicationMessage,
  11 = Ping.
- **Checksum:** CRC32, polynomial `0xEDB88320`, **seeded at 0** (not `0xFFFFFFFF`, not
  inverted at the end).
- **Handshake payload (52 bytes):** `Magic(4) ConnectionId(4) Username[32] Password[8]
  Unknown1(4)`. Machine username is hardcoded `"user"`; machine password = serial, NUL-padded
  to 8. Server reply password = `{0x2D, 0x00×7}`.
- **Lobby app-payload prefix:** `Magic(0x26B6) + Type1(u16) + Type2(u16)` (Type1 == Type2),
  then the body. DNG (S2-10th) uses `0x27D8`.
- **Chat app-payload prefix:** `Magic(0x0062) + Type(u16=0) + Id(u16=chatType)`.
- **Auth:** ECDH **secp521r1** (custom DER) → SHA-512 → XOR; credentials are **Twofish-CTR**.
- **`GameServerData(170)`** uses `GAMESERVERDATA_FORMAT="old"` (ServerInfoOld: u16 player
  counts + spectators + subtype + room_id). **Confirmed in-game:** the real `tincat3.dll`
  **rejects** the emulators' byte-count `"adk"` variant. `msgdefs.ini` is authoritative.
- **Room-assign (the s15 breakthrough):** a village entry's `roomId(+0x30)` and
  `pending(+0x34)` are NOT read from the 170 `room_id` field — they are parsed from the 170's
  **`data` (MEMBLOCK)**: **5 bytes = roomId as BIG-ENDIAN u32 + 1 pending byte**. Validity
  (`+0x35`) = `(descriptor.listAction != 0)`. The stub sends `data = b"\x00\x00\x03\xe8\x00"`
  (roomId 1000 BE, pending 0) so `IsListReady` goes true and the button un-greys.
- **Village list membership:** the entry must have `ServerSubtype = 2` (descriptor `+0x29`)
  to be added to the village list at all.
- **Server-browser version filter:** the client filters games by `Version`/`LobbyId`; AdK
  patchlevel is **9212**. Non-matching games land under "other versions". The community "dll
  hack" is a *client-side* patch disabling that filter — not a server fix.

---

## 5. Game's encrypted data files + AdKEd workflow

**The game's XML/Lua data files are encrypted.** Worlds, scenes, and UI/screen definitions
all live on disk in an encrypted container (the `.KEX` files, and the `sadk` FourCC container
format). You cannot read or edit them directly — decrypt them first.

### `AdKEd.exe` — the game's own two-way converter (use THIS)

`AdKEd.exe` (project root) is Rheini's **AdK Editor v1.11 Beta (2008)** conversion tool
(from the Xentax forum; see `docs/Readme.txt`). It is **TWO-WAY and in-place**:

- Run it over an **encrypted** file → it **decrypts** it (to plain XML/Lua).
- Run it again over the now-decrypted file → it **re-encrypts** it (the game needs the files
  encrypted to load them).

So the round-trip to read/edit a game data file is:

```bat
REM 1. copy a game file into the batch folder
copy "<GAME-INSTALL>\data\lobby\scene\world1.xml" BatchConversion\

REM 2. decrypt the whole folder (BatchConv.bat = FOR %%i IN (BatchConversion\*.*) DO AdKEd %%i)
BatchConv.bat
REM -> BatchConversion\world1.xml is now decrypted XML; read/edit it.

REM 3. run again to RE-ENCRYPT before copying back into the game
BatchConv.bat
```

**Always work on copies** — the conversion is in-place. The files in `BatchConversion/`
may be left in *either* state (it's a scratch folder). At time of writing
`BatchConversion\lobbyWorldScreen.xml` is decrypted (readable `<worldScreen2>` UI XML) and
`BatchConversion\world1.xml` is re-encrypted (binary). Re-run `BatchConv.bat` to flip a file.

Helpers:
- **`BatchConv.bat`** — convert every file in `BatchConversion\` (one line, calls `AdKEd`).
- **`decrypt_all.bat` / `decrypt_all.ps1`** — bulk-decrypt the whole game `data\` tree of
  `.KEX` files into `result\`, preserving structure. **Paths (source `<GAME-INSTALL>`, output, and
  `AdKEd.exe` path) are hardcoded — edit per machine.**
- **`result\`** — output of a completed bulk decrypt (~1,639 files of decoded `game/` and
  `lobby/` assets), if present.

### `tools/sadk_ui_decrypt*.py` — pure-Python reimplementation (no AdKEd needed)

`tools/sadk_ui_decrypt.py` re-implements the `sadk` UI-container crypto in Python (reversed
from `SADK.exe NBase::gDecryptData`): a 20-byte header (`12 18 09 06` sig + `sadk` FourCC +
data CRC32 + pw CRC32/LCG-seed + decompressed size), then XOR with a Park-Miller LCG
keystream, then Okumura LZSS decompression. Use it to decrypt UI containers programmatically;
`sadk_ui_decrypt_all.py` batches it. For ordinary game-data round-trips, **prefer `AdKEd.exe`**
— it is the game's own, known-correct, two-way tool. Don't reinvent the crypto.

---

## 6. Reverse-engineering setup

### Ghidra (static)

- **SADK.exe** is loaded in Ghidra at image base **`0x400000`** with **no ASLR rebase**, so
  Ghidra addresses == runtime addresses 1:1. `tincat3.dll` is at `0x10000000`.
- Live link via the **`bethington/ghidra-mcp`** fork (Ghidra 12.1 native, ~245 MCP tools).
  Plugin HTTP server on **`127.0.0.1:8089`**; bridge over stdio (registered in `.mcp.json`).
  Build/deploy + enable steps are in **`decomp/GHIDRA_MCP_SETUP.md`**.
- Renames/structs/enums already applied to the project live in **`decomp/RENAME_LIST.md`**
  (`LobbyManager`, `LobbyVillageScreen`, `ServerListEntry`, the `LobbyManagerState` enum, etc.).
- Offline alternative: `decomp/sadk/SADK.exe.c` (~1.2M lines / ~38.8k funcs) and
  `decomp/tincat/tincat3.dll.c` (~57k lines) are "Export as C/C++" decompiles. They are
  **unlabelled** (auto `FUN_`/`DAT_`), so navigate by string literals →
  `decomp/extract_index.py` builds `*_functions.tsv` / `*_strings.tsv` → Read the `.c` at the
  mapped line. See `decomp/README.md`.

### Live debugger (dynamic)

- A **dbgeng-based debugger server** runs at **`http://127.0.0.1:8099`** (`GHIDRA_DEBUGGER_URL`),
  exposing HTTP endpoints + the MCP `debugger_*` tools (attach, breakpoints, read
  registers/memory/args, step). It bridges to Ghidra's TraceRMI/dbgeng.
- **Must run ELEVATED** — the game runs as admin, so the debugger must too.
- **Module-sync** maps the SADK Ghidra base to the runtime `0x400000` (and `tincat3` to
  `0x10000000`), so static and dynamic addresses line up.
- Drive it via MCP `debugger_*` tools or raw HTTP (e.g.
  `/debugger/interrupt|registers|sync_modules|continue`). Reading memory needs the worker free
  — interrupt first. Only one debugger per process — let the MCP do the attach.
- The full breakpoint plan for the connection-tracing work is in `decomp/DEBUGGER_PLAN.md`.
- **pybag gotcha:** Ghidra's dbgeng launcher needs `pybag>=2.2.12` in the *same* Python it
  invokes; on "INCORRECT OR INCOMPLETE SETUP" answer YES to auto-resolution, then relaunch.

---

## 7. The Windows 11 fix (`tools/debugger_loader.py`)

SAdK is **SecuROM 7.x** protected; even the no-CD binary still carries the SecuROM VM. The
game *launches* fine on Win11, but **village-enter crashed** on Win10/11 (it worked on Win7).

**Root cause (proven live):** SecuROM redirects its "imported" API calls through a
deliberately-**unmapped** WinXP-era kernel32 address (e.g. `0x7C81320C`). The call faults; a
SecuROM **vectored exception handler (VEH)** catches the access-violation, resolves the real
API, and forwards. On Win7 this works. On Win10/11 the modernized **WOW64 fails to deliver
that 32-bit fault to the in-process VEH unless a debugger is attached** → the fault goes
unhandled → crash. It is a **protector-vs-modern-OS** problem, *not* a bug in our network
logic or our packets.

**The fix — `tools/debugger_loader.py`:** a transparent debug loop. It `CreateProcess`-launches
`SADK.exe`, waits for SecuROM's startup anti-debug to finish, `DebugActiveProcess`-attaches,
then in its `WaitForDebugEvent` loop **passes every first-chance exception back to the app**
(`DBG_EXCEPTION_NOT_HANDLED`) — consuming only the system's initial attach breakpoint. That
forces the fault down the path that *does* reach SecuROM's 32-bit VEH, so dispatch succeeds.
**No binary patch, no DLL injection, no SecuROM RE.** Proven: full village-enter into the 3D
world on Win11, identical to Win7.

```powershell
# RUN ELEVATED. Edit GAME / GAME_CWD paths at the top of the script first.
python tools\debugger_loader.py            # launch + debug
python tools\debugger_loader.py 12.0       # override the attach delay (seconds)
```

Keep the loader window open for the whole session — if it stops, the next SecuROM dispatch
crashes. (Win7 also works natively, with no loader.)

---

## 8. Protocol state / where things stand

Working end-to-end today (Win7 natively, or Win11 via the loader): **login → chat → server
list → room-assign → "Suche Server" button → village-enter → the 3D lobby world renders**
("Betrete Welt…", the "Testler" avatar visible).

**Current blocker — the post-`214 ValidateToken` stall.** After the token handshake
(`211 → 212 nonce → 213 SendToken → 214 ValidateToken`), the client holds the lobby (`7070`)
+ UC (`7071`) connections and waits for a **server push** to grant the world connection before
it dials `:5479`. Two things to do (`docs/ROADMAP.md` Track A):

- **A1 — world-entry grant.** Find the NETMSG type the server pushes to fire the client's
  `TANConnectionGranted` / `RequestTANConnectionResultReceived`, and send it from `dispatch.py`.
- **A3 — proper `214` token crypto.** Today `214` is a best-effort echo. The real key is almost
  certainly the **session key issued in `207`** — currently generated then **discarded**
  (`dispatch.py`). Store it (keyed by `perm_id`) and build a cryptographically valid `214`
  (likely Twofish-CTR, reusing `crypto.py`).
- **A2 — the `:5479` world protocol** is the big remaining chunk (world handshake, spawn, objects,
  position sync, in-world chat, player list). Types are in `msgdefs.ini`; the world uses its own
  subset (msg `1000` EnterWorld = `HandleEnterWorld`, plus `1001`–`1006`, etc.).

`docs/ROADMAP.md` Track B (the Win11 fix) is **done**. The archived session log is at
`docs/archive/SESSION_STATUS.md`; current frontier lives in auto-memory.

---

## 9. Tooling reference (`tools/`)

| Script | Purpose |
|---|---|
| `debugger_loader.py` | **The Win11 fix.** Transparent debug loop that passes faults to SecuROM's VEH so the game runs on Win10/11. Run elevated. (§7) |
| `lobby_proxy.py` | Passive man-in-the-middle proxy/logger — point the game at it to capture real client traffic (`--forward` to relay). |
| `analyze_capture.py` | Offline deep-analysis of a single binary capture (includes the `TinCat_Scramble` cipher from the Ghidra decompile). |
| `decode_lobby_capture.py` | Walks a raw `.bin` capture, labels every TinCat frame, decodes key lobby messages. `python tools/decode_lobby_capture.py <file.bin> [--dng]`. |
| `drm_addr_patch.py` | External WPM patcher for the dead SecuROM VM slot — *proof* tool (showed NULL/scratch returns are insufficient; the VM consumes the real return). Superseded by `debugger_loader.py`. |
| `suspended_launch.py` | `CreateProcess(SUSPENDED)` harness to arm a HW watchpoint before the protector unpacks (for tracing the VM-import resolver). |
| `pe_exports.py` | Dependency-free PE32 export-table parser (XP kernel32 RVA→name; never executes the DLL). |
| `dump_rva.py` | Print raw bytes at a given RVA in a PE (no execution). |
| `sadk_ui_decrypt.py` / `sadk_ui_decrypt_all.py` | Pure-Python `sadk` UI-container decrypt (LCG-XOR + LZSS). Prefer `AdKEd.exe` for normal round-trips. (§5) |
| `ui_header_analyze.py` / `ui_try_decompress.py` | Scratch analysis helpers for the UI container format. |

---

## 10. Reference material (NOT ours — copy the *flow*, not bytes)

- **`Settlers-AdK-lobby-emulator/`** — C# AdK lobby emulator (cloned git repo). Field defs in
  `S2Library/Protocol/Payloads.cs`, `ChatPayloads.cs`; `S2Lobby/src/Core/LobbyProcessor.cs`,
  `Chat/ChatProcessor.cs`. ⚠️ Its `170` byte-count layout is **wrong** for the real client —
  `msgdefs.ini` wins.
- **`Settlers-DNG-lobby-emulator/`** — Go emulator for the S2-10th predecessor (cloned git repo).
  Most complete public reference (create/join/launch-lobby work). `src/network/network.go`,
  `src/packages/packages.go`, `API.md`. Differs from AdK: payload magic `0x27D8`, and **no chat
  second-connection** (DNG does chat on the main socket).
- Both are upstream open-source projects with their own `.git` — don't commit into them.

### Captured data & logs (precious RE data — do not delete)

- **`sadk_captures/`** — raw `.bin` TinCat captures from real/stub sessions. Decode with
  `decode_lobby_capture.py` (file tools can't read raw binary).
- **`*/data/*.bin` (+ `.rehex-meta`)** in the emulator repos — real captured handshakes.
- **`tincat_server.log`** — stub run log. **`sadk_lobby_capture.log`** — proxy capture log.
- The game's own logs (when `-log_info -log_path` is set, e.g. `C:\tmp`): `commLayer.log`,
  `LobbyComm.log` — ground truth for client-side deserialize/connect errors.

---

## 11. Documentation map

| File | Role |
|------|------|
| `AGENTS.md` | **This file** — stable onboarding + protocol facts. |
| `README.md` | Quick-start + architecture for the `sadk_lobby` package. |
| `docs/ROADMAP.md` | Prioritized plan: Track A (finish the server) / Track B (Win11, done). |
| `docs/BINARY_PATCHES.md` | All client-side binary patches (P1/P2) + release strategy. |
| `docs/IN_WORLD_PROTOCOL.md` | World-entry RE spec: handlers, loading gate, protocol. |
| `docs/SOURCEMAP.md` | All named functions/structs/globals in the Ghidra project. |
| `docs/UI_FINDINGS.md` | UI screen system verdict + AdKEd decrypt workflow. |
| `docs/UNPACK_NOTES.md` | SecuROM 7.37 unpack notes + SADK_glass.exe build. |
| `docs/LOBBY_PROTOCOL.md` | Full reversed protocol reference (endpoints + message types). |
| `docs/archive/SESSION_STATUS.md` | Archived session log (s1–s36). Current frontier = auto-memory. |
| `docs/archive/WORLD_ENTRY_PLAN.md` | s30-era world-entry flow (superseded; kept for history). |
| `docs/archive/LOADING_DISMISS_FIX.md` | s35 observer-hook fix (approach superseded by app-FSM). |
| `docs/archive/GAME_HARNESS_DESIGN.md` | Design doc for game_harness.py (implemented; design archived). |
| `docs/REVERSE_ENGINEERING_GUIDE.md` | Track-A: KEX/asset decoding & modding guide. |
| `docs/Readme.txt` | Original `AdKEd.exe` usage (Rheini's tool). |
| `decomp/README.md` | How to navigate the offline decompiles via the string/function indexes. |
| `decomp/GHIDRA_MCP_SETUP.md` | Build/enable the live Ghidra MCP link. |
| `decomp/DEBUGGER_PLAN.md` | Live-debugger breakpoint plan. |
| `decomp/RENAME_LIST.md` | Addresses/labels/structs applied to the Ghidra project. |
| `sadk_lobby/data/msgdefs.ini` | The game's own NETMSG schema (authoritative). |

---

## 12. Conventions & gotchas

- **Git uses the `master` branch** (not `main`). Commits are co-authored. Commit/push only when
  asked; branch first if needed.
- **The game runs as admin** — and so the **live debugger must run elevated** to attach to it.
  The stub's lobby port (`7070`) may also need admin to bind.
- **On Win10/11, launch the game via `tools/debugger_loader.py` (elevated)** or it crashes on
  village-enter. Win7 runs it natively.
- **Don't reinvent the data-file crypto** — use `AdKEd.exe` (two-way, in-place). Always work on
  copies. (§5)
- **`msgdefs.ini` is the authoritative schema** — consult it FIRST for any message's layout; it
  overrides RE guesses and the emulators.
- **Wire-format values are byte-exact.** Don't change anything in `config.py`/`tincat.py`/
  `crypto.py` that touches the wire without re-validating against the real client. Note the
  `None` vs `""` string distinction.
- **Platform:** Windows 11, PowerShell. File tools can't read raw `.bin` — decode to text first.
- **Test credentials:** username `test` / password `test` / serial `test`.
- **Both client config files must point at the stub** (`LobbySettings.ini` *and* `network.ini`).
- **Hardcoded absolute paths** (E:/C: drives) live in `decrypt_all.*` and the `tools/*.py`
  loaders — adjust per machine.
- **Dead ends (don't retry):** `-localhostmode` exposes no socket to bridge; `SADK.exe` won't run
  two instances on one machine; real 2-player testing needs two physical machines (or a VM). Tuning
  the `170` *wire* format for room/validity is a dead end — those come from the `data` blob (§4).

---

## 13. Tests

```powershell
python tests\test_codec_golden.py     # codec reproduces the legacy 170 byte-for-byte
python tests\test_server_smoke.py     # end-to-end conversation against a fake socket
# or: pytest tests\
```
