# CLAUDE.md — authoritative instructions for every agent in this repo

> This file is loaded into **every** session and is the **authoritative agent brief**
> for this repository.
>
> **Every agent MUST read `CLAUDE.md` in full before starting any work.**
> Do not begin investigation, editing, debugging, protocol analysis, live-game interaction,
> or planning until you have read this file.
>
> After reading this file, read **`HARNESS.md`** before touching the live game.

---

## ⛔ MANDATORY: read `HARNESS.md` (rules of engagement) before touching the live game

**`HARNESS.md`** (repo root) is the **binding** harness that governs all work here. It
exists to prevent a repeated, costly failure: **jumping the gun** — taking state-mutating
actions against the live game "just to see a result" before the model is verified, and
sometimes while the game is legitimately *waiting* for something we should instead provide
through its real mechanism (the canonical case: force-calling `ActivateScreenById` while
the game was parked in **LobbyManager state 8** waiting for inbound **msg 1000**).

You MUST follow `HARNESS.md` in full. The essentials, inlined so you cannot miss them:

### The non-negotiables

1. **READ-ONLY BY DEFAULT.** Diagnose only with Ghidra (reads) and elevated
   `ReadProcessMemory` probes (`tools/probe_appfsm.py`, `tools/read_village_state.py`, the
   `*_probe.py` tools). Never mutate the game/binary/wire-protocol merely to observe. When
   you want a new live fact, reach for a **read-only probe**, not an injector.
2. **MODEL BEFORE MUTATION.** No state-changing action until a written, binary-grounded
   model exists with every claim tagged **`[PROVEN]`** (binary address + live read-only
   evidence) or **`[HYPOTHESIS]`**, and independently reviewed (mandatory for any wire
   format change — see `memory/independent-review-protocol-changes.md`).
3. **HARD MUTATION GATE.** Any *state-mutating* action — process injection / remote-thread
   / force-call, **any** `WriteProcessMemory`, live or rebuilt **binary patches**, or any
   change to the **network stub's wire behavior** — requires a completed
   **Engagement Record** (`templates/ENGAGEMENT_RECORD.md`) that the **USER explicitly
   approves** *before* the action is even proposed as runnable. The record must answer,
   with evidence: the verified model; read-only precondition checks; **"is the game
   legitimately WAITING for something we should instead provide through its real
   mechanism?"** (the exact past trap — rule it out with evidence); why this is the
   genuine mechanism not a shortcut; the expected observable + read-only post-check;
   rollback/blast-radius.
4. **FORCED RESULTS ARE NOT SOLUTIONS.** Forcing/injecting/patching to bypass the game's
   own logic is **forbidden as a "fix."** It is allowed only as a labelled, gated,
   approved **diagnostic**, and only after ruling out a wait-state. A visibly "working"
   forced result is **never** reported as success.
5. **HONEST STATUS.** "PROVEN" needs binary + live evidence; everything else is
   `[HYPOTHESIS]` and is labelled so. No over-claiming.

### TRIPWIRES — stop-and-run-the-gate phrases

If you catch **yourself or the user** saying any of these about a mutating action — **"fire
it", "let's just see", "let's see what happens", "hit it", "send it", "force-call it",
"just force it", "inject it", "quick experiment", "blind experiment", "patch it and see",
"nop it and see", "just this once", "it can't hurt to try"** — or you feel the urge to run
a `tools/force_*.py` (anything other than a read-only `*_probe.py`) before an approved
Engagement Record exists: **STOP.** Do not act. Instead run a **read-only probe** to settle
the question, or fill an Engagement Record and ask the user to approve. *The pull to "just
try it" is itself the signal to go read-only.*

### Technical enforcement (the gate bites)

The state-mutating injectors **refuse to run** without an approved Engagement Record. They
call `require_approval(...)` from **`tools/harness_gate.py`** at startup and abort (exit
90) unless `tools/.engagement_approved` authorizes that exact tool. Gated:
`force_activate_world.py`, `force_send2002.py`, `force_onenter.py`, `force_tick_patch.py`.
Read-only `*_probe.py` tools are ungated. To open the gate (only after the user approves):

```bash
python tools/harness_gate.py approve <tool> engagement_records/<your-record>.md
python tools/harness_gate.py status      # inspect what's approved
python tools/harness_gate.py revoke      # close the gate
```

Never self-approve to satisfy your own urge to try something — the `approve` step records
the **user's** decision, run only on their explicit in-session go-ahead.

---

## Project orientation

This repository revives the dead online lobby of **Die Siedler: Aufbruch der Kulturen**
("The Settlers: Rise of Cultures", Funatics / Blue Byte / Ubisoft, 2008), abbreviated
**SAdK**. It is the German standalone built on the *Settlers II: 10th Anniversary*
(DNG) engine. The official servers died around 2014.

The main working method is to reverse-engineer the original client (`SADK.exe` +
`tincat3.dll`) and stand up a Python **stub lobby server** that the real, unmodified
client connects to. The project goal is to speak the protocol correctly, not to treat
forced client-side bypasses as fixes.

There are two project tracks to keep straight:

- **Online lobby revival** — the active frontier centered on `sadk_lobby/`.
- **Game asset decoding and modding** — working with encrypted `.KEX` / `sadk` data files
  via the bundled tools.

Be careful with historical docs that refer to Track A/Track B by letter only; some older
documents use those labels differently. Read the content, not just the letter.

---

## Mandatory reading order after this file

After reading `CLAUDE.md`, consult the following as needed:

1. **`HARNESS.md`** — binding rules for any live-game work.
2. **`MEMORY.md`** — persistent cross-session context. Start there.
3. **`memory/msgdefs-ini-authoritative.md`** — first stop for any lobby message work.
4. **`docs/ROADMAP.md`** — active plan and remaining frontier.
5. **`docs/archive/SESSION_STATUS.md`** — archived session log.
6. **`README.md`** — quick-start and package overview.

---

## Current high-level status

Use this as a working orientation, but keep status claims honest and update them when they
change.

| Piece | State |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list | ✅ working |
| Room-assign → "Suche Server" button lit + clickable | ✅ working |
| Village-enter → 3D lobby world renders | ✅ reached |
| Runs on Windows 11 x64 | ✅ fixed via `tools/debugger_loader.py` |
| Runs on Windows 7 natively | ✅ working |
| Final world entry over the world server (`:5479`) | ⏳ blocked by post-`214 ValidateToken` / world-entry grant work |

The previously long-running blockers around server-list population, room-assign, and the
Win11 SecuROM crash are solved. The current frontier is completing the world-entry grant,
proper `214` handling, and the `:5479` world protocol.

---

## Repository architecture quick map

The active stub server lives in **`sadk_lobby/`** and is run with:

```powershell
pip install -r requirements.txt
python -m sadk_lobby
```

High-level file roles:

- `sadk_lobby/__main__.py` — package entry point
- `sadk_lobby/config.py` — constants, ports, test account, wire toggles
- `sadk_lobby/tincat.py` — frame parsing/building and wire primitives
- `sadk_lobby/msgdefs.py` — parses the game's `msgdefs.ini`
- `sadk_lobby/codec.py` — generic encoder/decoder for message bodies
- `sadk_lobby/crypto.py` — login crypto
- `sadk_lobby/chat.py` — chat / UC second connection handling
- `sadk_lobby/village.py` — village / world third connection handling
- `sadk_lobby/connection.py` — per-socket state machine
- `sadk_lobby/dispatch.py` — lobby handler table
- `sadk_lobby/server.py` — listener setup and main loop
- `sadk_lobby/data/msgdefs.ini` — authoritative NETMSG schema copy

---

## Protocol and wire-format rules

- **`msgdefs.ini` is authoritative. Consult it first.** The game's own NETMSG schema
  overrides reverse-engineering guesses and emulator field layouts.
- The stub’s wire behavior is **byte-exact** territory. Do not change wire-format behavior
  casually. Re-validate against the real client.
- Preserve important edge cases such as the distinction between `None` and `""` string
  encoding.
- For any lobby message task, consult **`memory/msgdefs-ini-authoritative.md`** first.

Important protocol reminders:

- TinCat frame header size is **28 bytes**.
- Lobby payload prefix uses **magic `0x26B6`**.
- Chat payload prefix uses **magic `0x0062`**.
- Auth flow uses **ECDH secp521r1** and **Twofish-CTR**.
- `GameServerData(170)` should follow the real-client-compatible format, not emulator
  assumptions contradicted by `msgdefs.ini`.

---

## Running and environment notes

- The three primary listener ports are:
  - `7070` — lobby
  - `7071` — UC/chat
  - `5479` — world
- The server binds to `0.0.0.0`.
- The advertised IP can be changed with `SADK_ADVERTISE_IP`.
- **Both** client config files must point at the stub:
  - `data/lobby/config/LobbySettings.ini`
  - `data/game/settings/network.ini`
- AdK patchlevel is **9212**.
- Test credentials are:
  - username: `test`
  - password: `test`
  - serial: `test`

---

## Reverse-engineering and live-debugging setup

- **Ghidra addresses match runtime addresses 1:1** for `SADK.exe` at image base
  `0x400000`; `tincat3.dll` is at `0x10000000`.
- Renames, structs, and enums applied to the project are tracked in
  `decomp/RENAME_LIST.md`.
- Offline decompile exports and indexes exist under `decomp/`.

Dynamic work notes:

- The live debugger setup must run **elevated** because the game runs as admin.
- Static and dynamic addresses are intended to line up.
- Breakpoint planning and debugger setup details live under `decomp/`.

Always prefer read-only observation first, per the harness.

---

## Windows 11 / SecuROM note

A key proven project fact: the Win10/11 village-enter crash is a **protector-versus-modern-OS**
issue, not evidence that the stub protocol is necessarily wrong.

Use **`tools/debugger_loader.py`** for Win10/11 sessions. It provides the working launch path
without treating binary patching as the fix.

Operational reminders:

- Run it **elevated**.
- Keep the loader window open for the whole session.
- Win7 works natively without this loader.

---

## Asset decryption / modding guidance

The game’s XML/Lua data files are encrypted. For routine round-trips:

- **Prefer `AdKEd.exe`**.
- It is the game’s known-good **two-way** converter.
- Work on **copies**, because conversion is in-place.
- Avoid reinventing the data-file crypto unless you specifically need the Python tooling for
  analysis or automation.

Relevant docs/tools:

- `docs/Readme.txt`
- `docs/REVERSE_ENGINEERING_GUIDE.md`
- `tools/sadk_ui_decrypt.py`
- `tools/sadk_ui_decrypt_all.py`

---

## Tooling pointers

Useful repository tools include:

- `tools/debugger_loader.py` — Win11/Win10 compatibility path
- `tools/lobby_proxy.py` — passive MITM proxy/logger
- `tools/analyze_capture.py` — offline capture analysis
- `tools/decode_lobby_capture.py` — decode raw TinCat captures
- `tools/suspended_launch.py` — suspended-process tracing harness
- `tools/pe_exports.py` and `tools/dump_rva.py` — PE inspection helpers
- `tools/sadk_ui_decrypt.py` and friends — Python UI-container decryption tooling

Treat captured data and logs as valuable RE artifacts; do not delete or casually rewrite them.

---

## Reference material and documentation map

Important references:

- `README.md` — quick-start and architecture
- `docs/ROADMAP.md` — prioritized plan
- `docs/IN_WORLD_PROTOCOL.md` — world-entry RE spec
- `docs/LOBBY_PROTOCOL.md` — broader protocol reference
- `docs/SOURCEMAP.md` — named functions/structs/globals
- `docs/UI_FINDINGS.md` — UI findings and decrypt workflow
- `docs/BINARY_PATCHES.md` — binary patch history/strategy
- `decomp/README.md` — navigating offline decompiles
- `decomp/GHIDRA_MCP_SETUP.md` — live Ghidra link
- `decomp/DEBUGGER_PLAN.md` — debugger breakpoint plan
- `decomp/RENAME_LIST.md` — applied labels and structs
- `sadk_lobby/data/msgdefs.ini` — authoritative NETMSG schema

External emulator repos can be useful as flow references, but **not** as authoritative field
definitions where they disagree with the game’s own schema.

---

## Conventions and gotchas

- **Git uses `master`, not `main`.**
- The game runs as admin; attached debugging must also run elevated.
- On Win10/11, launch through `tools/debugger_loader.py`.
- File tools cannot read raw `.bin` captures directly; decode them to text first.
- Some scripts contain hardcoded absolute paths and may need machine-local adjustment.
- Known dead ends should stay dead ends unless new evidence appears:
  - `-localhostmode`
  - trying to run two local client instances on one machine
  - treating the `170` wire layout as the source of room/validity when those values actually
    come from the `data` blob path

---

## Testing

```powershell
python tests\test_codec_golden.py
python tests\test_server_smoke.py
# or: pytest tests\
```

---

## Maintainer-context note

The maintainer is a game-domain expert. Pay attention to their in-game instincts,
especially questions like: **is the game actually waiting for something earlier in the real
flow?** That exact instinct was previously correct and is now codified in the harness’s
wait-state checks.