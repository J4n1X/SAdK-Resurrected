# CLAUDE.md — instructions for every agent in this repository

> Loaded into every session. It applies to every agent, not only Claude (`AGENTS.md` points here).
> Read it in full, then **`HARNESS.md`** (the binding rules) before any reverse engineering, live debugging or
> server change, and **`MEMORY.md`** (what is established, what is open) before picking up work.

---

## The goal

This repository reverse-engineers **Die Siedler: Aufbruch der Kulturen** ("The Settlers: Rise of Cultures",
Funatics / Blue Byte / Ubisoft, 2008; **SAdK**, on the *Settlers II: 10th Anniversary* engine) and documents it.
**A faithful, evidence-backed model of the client is the deliverable.** Everything that runs (the lobby server,
the mods) demonstrates that understanding; it is not the point.

- **Understanding first.** Build the model brick by brick. A change that makes something "work" without an
  understood, evidence-backed reason is a regression: it buries the knowledge the project exists to capture.
- **End goal: a remake** in Godot (maintainer, 2026-10-12), C# throughout (2026-10-14). It ships no original data,
  keeps every system moddable (Harmony-patchable assemblies, data, Lua), and has two modes: a *compatibility mode*
  in lockstep with the original client (crossplay) and a *refined mode* that fixes the original's bugs. When you
  document a quirk, say whether it changes simulation state (compatibility mode must reproduce it) or is
  presentation only. The remake's code lives in its own repository (`sadk-remake`); its design lives here.

**Milestones**
1. ✅ Load into the 3D lobby village.
2. ✅ Host and join matches (2026-07-27).
3. ✅ The lobby revival is played on (2026-10-12): accounts, village, minigames, mail, matches with rewards and
   wagers, the host bridge, map and mod sharing. Its open points are in `MEMORY.md`.
4. ◀ **current** — Groundwork for the remake: close the remaining `[TODO]` / `[inferred]` gaps, specify every
   subsystem (`docs/sim/`), design the remake (`docs/remake-architecture.md`, `docs/remake-rendering.md`,
   `docs/remake/`).

---

## The rules in short (`HARNESS.md` has the binding text)

1. **MCP-first.** Static RE through the **Ghidra MCP**, live debugging through the **Frida MCP**. Scripts run
   *inside* Ghidra through the MCP are fine. Standalone scripts that do RE, read or write process memory, trace,
   inject or patch are forbidden. A new tool needs a stated reason first (`HARNESS.md` §3).
2. **No faked results.** Never force, patch or inject to make something look like it works. If the game waits,
   ask what it waits for and provide it through the real mechanism.
3. **Honest status.** `[PROVEN]` = binary address + live evidence; `[known]` = read in the binary; `[inferred]`;
   `[TODO]`. Never upgrade a tag by repetition.
4. **Consult the client before implementing.** Read the client's whole code path in Ghidra (handlers, the
   observers they fire, the UI and 3D code that consumes the state, its crash limits) before writing server or
   mod behaviour. Never patch reactively from a live failure.
5. **Map before mod code.** A mod uses only mapped game fields, types and functions: map in Ghidra → check in →
   re-export `sadkmod/sourcemap/` → regenerate sadkmod → write the mod. No raw offsets.
6. **Live tests only when the code cannot answer** (maintainer, 2026-10-14). Read the code path to its end
   first; run what can be measured unattended yourself; hand the maintainer only what needs their eyes, ears or a
   second player, as one short list (`HARNESS.md` §7).
7. **No flag-gating, no hidden hacks** in the server: working behaviour is the default; a hack, bypass or new
   flag needs the maintainer's explicit permission.
8. **Docs state the current model as clean fact.** No session diaries, no dated engagement records, no
   "superseded" stories: when something was wrong, correct the reference doc. Evidence (addresses, dated live
   observations) goes into the reference doc itself; history lives in git.

---

## How to work here

- **Act, don't ask.** Clear blockers with the tools at hand (scripts inside Ghidra, Frida, SSH to the game PC)
  and report afterwards. Ask only real decisions — writes to game memory or new server behaviour that are not yet
  approved, deleting the maintainer's data, anything outward-facing — and bundle them into one question.
- **Parallel agents are welcome** for big work: commit a small shared foundation first, give each agent its own
  files (or its own `git worktree add` + branch), and merge. In Ghidra keep **one writer per struct**: fan out
  read-only analysis, apply struct edits serially.
- **Git.** Branch `master` (not `main`). When work is done and checked, fast-forward it into `master`, push, and
  delete the branch and its worktree; leftover branches get in the way. `backup/*` branches are never merged.
  The submodules `lobby/` and `sadkmod/` are separate public repositories: change them inside the submodule,
  commit and push there, then update the pointer here.
- **Public repository, anonymized history.** Never commit the maintainer's real name or e-mail, the server's
  public IP or host names, or `/home/<user>` / `C:\Users\<user>` paths (write "the maintainer", `127.0.0.1`,
  `~`). The noreply identity `J4n1X <J4n1X@users.noreply.github.com>` is repo-*local*: set it in every new clone
  and submodule checkout before the first commit, and scan outgoing commits for personal strings before pushing.
- **Scratch space.** Never put bulk data in `/tmp` (it starved the live server once). A decrypted copy of the game
  data is at `~/sadk_game_decrypted`: read it there, never decrypt the data again. Use an on-disk scratch folder
  outside the repository and delete what you create.
- **Never touch the players' saves.** The live service reads `sadk_players.json` / `sadk_mail.json` in this
  repository's root (gitignored): never move, overwrite or delete them.

---

## Current status (keep honest; update when it changes)

| Piece | State |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list | ✅ working |
| Village entry, 3D lobby village (server pushes `EnterWorld(1000)`) | ✅ working |
| Multi-client (host and joiner as distinct players, process-global game registry) | ✅ default |
| In-world NPCs (shops, tailor, hall of fame, games, matchmakers, mail) | ✅ on; models: only the male set of `npc_bodyparts.xml` is reachable (`docs/village-and-character-protocol.md` §5.1) |
| Village economy (gold, items, shops, tailor) | ✅ tailor (2026-10-07), shops open and list their items (2026-10-12); sell prices and unknown item ids open (`docs/live-session-queue.md`) |
| Accounts and persistent characters (password on first login, `!setpwd`, the character `data` blob kept as the game's save) | ✅ live 2026-10-07 (`lobby/sadk_lobby/store.py`, `savegame.py`) |
| Tavern minigames: Dice, Poker, Pawn Chess in both taverns | ✅ live 2026-10-07, two clients |
| Mail, buddy lists and presence, whispers, channel leave | ✅ live play (2026-10-12) |
| Hosting, pre-game room (slot / tribe / team / ready) | ✅ working |
| Entering matches (the full referee chain) | ✅ since 2026-07-27 (`docs/MATCH_START.md`) |
| In-match referee messages: GiveUp `0xDD4`, FinishGame `0xDC0`, ClaimChest `0xDAC` | ✅ live 2026-10-10; rewards credited |
| Match wagers (`lobby/sadk_lobby/wagers.py`) | ✅ two-player matches live 2026-10-12; refusal codes and matches of more than two players `[TODO]` |
| Shim and mod system (`mods\<name>\{data,mod.dll}`), mods billboards / borderless / nomeshcache / npcmodels | ✅ in the game 2026-10-08 (`mods/README.md`) |
| Server mods per match (assetshare: manifest, LZMS archives, mod switching, kick without assetshare) | ✅ in the game 2026-10-12 |
| Ghidra map | function-complete in both binaries since 2026-10-13; figures and what stays open in `MEMORY.md` |
| Remake specifications (`docs/sim/`, 36 documents) and design (`docs/remake*`) | written; the design set of 2026-10-15 is a draft until the maintainer confirms it |

**Every failure in the referee path is silent** (frame accepted, socket open, nothing logged), so "no error" is
not evidence. Read `docs/MATCH_START.md` and `lobby/sadk_lobby/referee.py` / `dispatch.py` before touching it. Two
facts to burn in:
- The referee assign reply is **type 4 / sub 4**, never 4/5: 4/5 goes to a tincat3-private handler that never
  notifies the lobby, so `LobbyComm::System+0x580` never latches. The exact-60 s `189` retry cadence is the tell
  that the latch worked.
- **LobbyMessage bodies (village, referee) are an MSB-first bit stream**: 32-bit values read big-endian when
  byte-aligned, strings carry a u8 length, bools are 1 bit; TinCat NETMSG property-bag fields are little-endian.
  A little-endian `PermID` is silently discarded by `OnLoginSuccess@0x0047ac20`.

---

## Where things are

| Path | What |
|---|---|
| `docs/` | The reference (index: `docs/README.md`). Protocol: `message-catalog.md` (every message, what the client expects, why), `MATCH_START.md`, `village-and-character-protocol.md`, `NCOMM_GAME_PROTOCOL.md`. Game: `types.md`, `subsystems.md`, `map-format.md`, `asset-formats.md`. Remake: `sim/`, `remake-architecture.md`, `remake-rendering.md`, `remake/`. Live work: `LIVE_DEBUG_RUNBOOK.md`, `live-session-queue.md` |
| `decomp/` | `RE_PRACTICES.md` (the RE standard behind `HARNESS.md` §6), `RENAME_LIST.md` |
| `mapping/` | The whole-binary mapping pipeline (`README.md`, `AGENT_GUIDE.md`, `scripts/` run inside Ghidra, `bin/`); its bulk (`cache/`, `work/`, `queue/`, `state.db`) is gitignored |
| `mods/` | This repository's further mods (`mods/README.md`) |
| `tools/` | The tools that cleared `HARNESS.md` §3 (below), the Frida MCP |
| `lobby/` | Submodule `S2-modders/sadklobby`: the server `sadk_lobby/`, `tests/`, the players' mods (`gamebridge`, `assetshare`, `billboards`), the setup tool `setup/`, `docs/bridge-protocol.md` |
| `sadkmod/` | Submodule `S2-modders/sadkmod`: the C++ modding library generated from the Ghidra map (`sourcemap/`), the shim `shim/` (proxy `wsock32.dll` that loads mods), `mods.mk`, `docs/writing-mods.md` |
| `packaging/make_release.sh` | Assembles a release from both submodules and the mods listed in it |

After cloning: `git submodule update --init` (not recursive). Build the lobby's mods against this repository's
sadkmod: `make -C lobby/mods SADKMOD=../../sadkmod` (`lobby/sadkmod` stays empty here).

`lobby/sadk_lobby/` file roles: `__main__.py` entry · `config.py` constants and ports (no feature flags) ·
`tincat.py` frames · `msgdefs.py` parses the game's `msgdefs.ini` · `codec.py` generic message bodies ·
`crypto.py` login crypto · `chat.py` chat/UC connection · `village.py` village connection · `players.py`
identities · `registry.py` hosted games · `connection.py` per-socket state · `dispatch.py` lobby handlers ·
`referee.py`, `wagers.py`, `rewards.py` matches · `server.py` listeners and main loop.

---

## Tools and setup

- **Ghidra MCP** (`ghidra`): bethington/ghidra-mcp in headless mode on the Linux server, working on a checkout of
  the Ghidra Server repository `sadk`; installed, updated and registered (local scope) by
  `tools/ghidramcp/update-ghidramcp.sh`. Runbook and troubleshooting: `docs/HEADLESS_SETUP.md`. Working rules:
  - Map **`/sadk_noav.exe`** (= the DRM-free `SADK.exe` on disk, MD5 `d4832bc5103c14f5445471af29b8d778`),
    `/tincat3.dll` and `/NXCHARACTER.DLL`. Ghidra's `/SADK.exe` is a SecuROM dump-base build with other
    addresses: never map it, keep it closed, pass `program=` on every call. Static addresses equal runtime ones
    (`SADK.exe` base `0x400000`, `tincat3.dll` `0x10000000`).
  - `checkin_program` writes a new repository version and **unloads** the program: `load_program_from_project`
    right after. `server_status` may say "not connected" while check-in works.
  - `run_ghidra_script` runs scripts by name from `~/ghidra_scripts/`. The mapping pipeline's writer
    (`mapping/scripts/ApplyChanges.java`) does not protect hand-made names: evidence decides.
- **Frida MCP** (`frida-sadk`, `tools/frida_mcp/`): call client functions, hook handlers, read objects, catch
  crashes in the running game. Registered at user scope (a project `.mcp.json` entry is skipped in background
  sessions); needs frida-server 17.22.2 (windows-x86) running as Administrator on the game PC. Runbook:
  `docs/LIVE_DEBUG_RUNBOOK.md`. No hardware watchpoints from JS: they stalled and then killed the game.
- **The game PC** is reachable over SSH (Windows PowerShell 5: use `;`, not `&&`). Install builds and read the
  shim log `bin\wsock32_shim.txt` yourself; overwrite a DLL only while `SADK.exe` is not running. The maintainer
  only starts the game and reports what they see.

Tools that cleared the `HARNESS.md` §3 gate (nothing else without a stated reason):
- `tools/lobby_proxy.py` (passive MITM logger of the wire); `tools/analyze_capture.py`,
  `tools/decode_lobby_capture.py`, `tools/decode_game_join.py` (offline capture decoders).
- `tools/frida_mcp/` (the live-debugging MCP itself).
- `tools/sadk_crypt.py`, `tools/kex.py`: offline decryption (and re-encryption) of the game's data files and
  `.KEX` scene parsing (`docs/asset-formats.md`); they re-implement the client's own loaders, checked against every
  file. How to read and change game data today, mods included: `docs/game-data-files.md`. `AdKEd.exe` is not
  needed.
- `sadkmod/gen/gen_game_headers.py` (C++ declarations from `sadkmod/sourcemap/`; fed by
  `sadkmod/sourcemap/ExportTypesJson.java` inside Ghidra).
- `tools/s2m_upgrade.py`: rewrites a map in the old prototype layout into the shipped one (`docs/map-format.md` §9).
- `tools/screenshot.ps1`: a PNG of the game window (`PrintWindow`), run through the scheduled task
  `sadk-screenshot` in the logged-on desktop session.
- `tools/cvar_client.py`: client for the game's developer-tweak (CVar) server (`docs/BINARY_PATCHES.md`).
- `tools/ghidramcp/update-ghidramcp.sh`: installs and registers the Ghidra MCP itself.

Captures and logs are RE artifacts: don't delete or casually rewrite them.

---

## Protocol and wire rules

- **`msgdefs.ini` is authoritative** for NETMSG layouts; it overrides RE guesses. It is copyrighted game data:
  copy it from the game's `bin\` into `lobby/sadk_lobby/data/` (gitignored), never commit it.
- Wire behaviour is **byte-exact**. Change it only with `msgdefs.ini` plus binary evidence, and re-validate
  against the real client. Preserve edge cases such as `None` vs `""` string encoding.
- `[PROVEN]` constants: TinCat header **28 bytes**; NETMSG module id **0x26B6** (lobby, and the logins on every
  other connection); chat runs as CellManager module **0x0062** templates, not as a second payload magic; auth =
  **ECDH secp521r1** + **Twofish-CTR**: the lobby login completes on **207 SessionKey**, the token logins of the
  UC, village and referee connections on **153 AddResult** after 213 (the UC path has no 214 handler);
  `GameServerData(170)` = the ServerInfoOld layout; a connection learns its server's address only from
  `ConnectionData(222)`; leave-village `0x27D2` is answered with `1006` (`0xDEADBEEF`), never with `1000`. Details
  and evidence: `docs/message-catalog.md`.

---

## Running and testing

```bash
git submodule update --init
source ./setup_venv.sh              # .venv with lobby/requirements.txt (+ zombie-imp: twofish needs `imp` on CPython >= 3.12)
cd lobby && python -m sadk_lobby
```

- Ports: `7070` lobby · `7071` UC/chat · `5477` village · `5481` referee · `7072`/`7073` host bridge. `5479` is a
  *hosting client's* game port, not a server port. Binds `0.0.0.0`; the advertised IP comes from
  `SADK_ADVERTISE_IP` (the live service gets it from a local systemd drop-in, never from the repository).
- The live service is the systemd user unit `sadk-lobby` (`systemctl --user restart sadk-lobby`, logs via
  `journalctl --user -u sadk-lobby`), running from `lobby/` under PyPy (`.venv-pypy` in this root) with
  `SADK_STORE_PATH` pointing at this root.
- Clients point at the server through `data/lobby/config/LobbySettings.ini` and `data/game/settings/network.ini`
  (SAdK-ServerConfig, `lobby/setup/`, writes both). AdK patchlevel **9212**. Test credentials: any new name
  registers on its first login.

```bash
pytest lobby/tests/                 # wire codec (byte-for-byte golden), login, village, minigames, referee, bridge
make -C sadkmod test                # library self-test and mod host (Wine)
make -C mods verify                 # every mod's patches checked against SADK.exe (Wine)
```

---

## Platform notes and dead ends

- The retail exe is SecuROM-protected; on Windows 10/11 it needs the runtime fixes in `docs/BINARY_PATCHES.md`.
  The project targets the publisher's DRM-free build (MD5 above), which runs as is; the shim and the mods need it.
- The game runs as administrator on the game PC; Frida's server must run elevated too.
- Dead ends (stay dead unless new evidence): `-localhostmode`; two client instances on one machine; treating the
  `170` wire layout as the source of room/validity (those values come from the `data` blob path).
- File tools can't read raw `.bin` captures: decode them to text first.

---

## Maintainer context

The maintainer is a game-domain expert; weight their in-game instincts, especially *"is the game waiting for
something earlier in the real flow?"* (`HARNESS.md` §2). Their time at the game PC is the scarce resource. They want
heavy initiative, work merged rather than parked on branches, and questions only for real decisions.
