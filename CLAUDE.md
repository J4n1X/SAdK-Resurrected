# CLAUDE.md — authoritative instructions for every agent in this repo

> Loaded into **every** session. Read it in full before starting any work, then read
> **`HARNESS.md`** (the binding rules of engagement) before any RE, debugging, or
> stub change.

---

## The goal — understanding first, working second (read this before anything)

The purpose of this project is to **comprehensively reverse-engineer the code the
client uses to connect to the server, and to write detailed, correct documentation of
that protocol.** That faithful model of the systems at play **is the deliverable.** A
working stub lobby is how we *demonstrate* the understanding — it is not the point.

Therefore:
- **Build understanding brick by brick. Do not sprint to a milestone.** A change that
  makes something "work" without an understood, evidence-backed reason is a regression,
  not progress — it buries the very knowledge we exist to capture.
- **Prefer a correct, documented model over a quick result.** Knowledge is power; a
  green checkmark bought with a guess or a hack is worthless to us.
- This is *why* `HARNESS.md` forbids faking results and demands honest
  `[PROVEN]`/`[TODO]` status, and why RE is done to a standard (`HARNESS.md §6`): those
  rules all serve understanding.

**Milestones** — each a *demonstration* of understanding, subordinate to the goal above:
1. ✅ Load into the 3D lobby world at all (even with nothing working inside it).
2. ✅ **Host and Join matches** — achieved 2026-07-27, two games back-to-back.
3. ◀ **current** — Finalize the lobby system.

---

## The three rules that matter most (see `HARNESS.md` for the full text)

1. **MCP-first.** Do all reverse-engineering and debugging through the **Ghidra
   MCP**. Running scripts *inside* Ghidra via the MCP is fine. Writing standalone
   Python/PowerShell to do RE, read process memory, trace, inject, or patch is
   **forbidden** — that's circumventing the harness. If a debugging capability is
   missing, add a debugger MCP; do not write a script.
2. **No faking results, and new tools need a stated reason.** Never force/patch/inject
   to fake a "working" result; if the game waits for something, provide it via the
   real mechanism. Before writing **any** new tool, state in detail what capability
   it needs and why neither the Ghidra MCP nor a debugger MCP can provide it. The only
   thing that has cleared that bar so far is **network capture/decode**.
3. **Honest status + no flag-gating.** `[PROVEN]` = binary address + live evidence;
   everything else is labelled `[TODO]`. In the stub, working behaviour is the
   **default** — never gate a working feature behind a flag, and never add a hack or
   bypass without explicit user permission.

---

## Project orientation

This repo revives the dead online lobby of **Die Siedler: Aufbruch der Kulturen**
("The Settlers: Rise of Cultures", Funatics / Blue Byte / Ubisoft, 2008) — **SAdK**,
the German standalone on the *Settlers II: 10th Anniversary* (DNG) engine. The
official servers died ~2014.

The method: reverse-engineer the original client (`SADK.exe` + `tincat3.dll`) and run
a Python **stub lobby server** (`sadk_lobby/`) that the real, unmodified client
connects to. The goal is to **speak the protocol correctly**, not to force
client-side bypasses.

Two tracks:
- **Online lobby revival** — the active frontier, centred on `sadk_lobby/`.
- **Game asset decoding / modding** — encrypted `.KEX` / `sadk` files via `AdKEd.exe`
  (see `docs/REVERSE_ENGINEERING_GUIDE.md`).

---

## Mandatory reading order

1. **`HARNESS.md`** — binding rules (MCP-first, no faking, honest status, no flags).
2. **`MEMORY.md`** — compact persistent context: proven facts + current TODOs.
3. **`docs/LOBBY_PROTOCOL.md`** — the NETMSG protocol reference (msgdefs-grounded).
4. **`docs/SOURCEMAP.md`** — named functions / structs / offsets (Ghidra map).
5. **`README.md`** — quick-start, what works / what doesn't.

---

## Current status (keep honest; update when it changes)

| Piece | State |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list | ✅ working |
| Room-assign → village entry joinable in the browser | ✅ working |
| Village-enter → 3D lobby world renders (server pushes EnterWorld 1000) | ✅ reached (clean build, screenshot-confirmed once) |
| Multi-client (host + joiner as distinct players, global game registry) | ✅ default |
| In-world content: NPCs | ⚠️ implemented, parked by `config.VILLAGE_NPCS_ENABLED = False` |
| Village economy (gold, items, shop, tailor) | ⚠️ implemented 2026-10-07; tailor ✅ live 2026-10-07 (owner and others see the new look); shop/inventory `[TODO]` |
| Accounts + persistent characters: password set on first login, `!setpwd`; new names start without avatars; the character `data` blob is kept as the game's save (look, gold, items, position) | ✅ live 2026-10-07 (`store.py`, `savegame.py`) |
| Minigame tables: Dice, Poker and Pawn Chess in both taverns (create, join, full rounds) | ✅ live 2026-10-07, two clients (`sadk_lobby/minigames.py`, `poker.py`, `pawnchess.py`) |
| Mail, buddy lists + presence, whispers, channel leave | ⚠️ implemented 2026-10-07, not live-tested — `[TODO]` |
| Hosting / pre-game room (slot/tribe/team/ready protocol) | ✅ working |
| **Entering matches (full referee chain)** | ✅ **working — 2026-07-27, two games back-to-back** |
| In-match referee msgs (GiveUp `0xDD4`, FinishGame `0xDC0`, ClaimChest `0xDAC`) | ⚠️ answered per the catalog since 2026-10-07, not live-tested — `[TODO]` |

The referee/match-arbiter subsystem is **live and proven end-to-end**: `RegisterGame(0xDB6)`
arrives from both clients and is answered with `Ack(0xDB7)` + `Result(0xDB8, GameSeed)`. The
full chain — and the four *silent* bugs that hid it — are documented in `sadk_lobby/referee.py`,
`dispatch.py` (`_h_assign_server` / `_h_connection_data`) and
`engagement_records/2026-07-27_referee-*.md`. **Read those before touching anything referee-related:
every failure mode in this subsystem is silent** (frame accepted, socket stays open, nothing
logged anywhere), so "no error" tells you nothing.

Two facts worth burning in:
- The referee assign reply must be **type4/sub4**, never 4/5 — 4/5 is special-cased to a
  tincat3-private handler that never notifies the lobby, so `LM+0x580` never latches. The
  exact-60 s `189` retry cadence is the tell that the latch worked.
- **LobbyMessage field scalars are BIG-endian** (`village.py` already knew: `struct.pack(">I")`).
  A little-endian `PermID` is silently discarded by the guard in `OnLoginSuccess@0x0047ac20`.

---

## Repository architecture quick map

Run the stub:
```bash
pip install -r requirements.txt
python -m sadk_lobby
```

`sadk_lobby/` file roles:
- `__main__.py` — entry point · `config.py` — constants/ports/players (no flags)
- `tincat.py` — frame parsing/building · `msgdefs.py` — parses the game's `msgdefs.ini`
- `codec.py` — generic message-body encode/decode · `crypto.py` — login crypto
- `chat.py` — chat/UC second connection · `village.py` — village/world third connection
- `players.py` — multi-user identities · `registry.py` — process-global hosted-game store
- `connection.py` — per-socket state machine · `dispatch.py` — lobby handler table
- `server.py` — listeners (lobby 7070, UC/chat 7071, world 5479) + main loop
- `data/msgdefs.ini` — authoritative NETMSG schema, copied locally from the game (copyrighted: gitignored, never commit)

---

## Protocol & wire-format rules

- **`msgdefs.ini` is authoritative. Consult it first.** It overrides RE guesses and
  emulator field layouts where they disagree.
- Wire behaviour is **byte-exact**. Don't change it casually; re-validate against the
  real client. Preserve `None` vs `""` string-encoding distinctions.
- Key constants `[PROVEN]`: TinCat header = **28 bytes**; lobby payload magic
  **0x26B6**; chat payload magic **0x0062**; auth = **ECDH secp521r1** + **Twofish-CTR**,
  completing on **153 AddResult** (the client has no 214 handler on the UC path);
  `GameServerData(170)` = the ServerInfoOld layout.

---

## Running & environment notes

- Ports: `7070` lobby · `7071` UC/chat · `5479` world. Binds `0.0.0.0`. Advertised IP
  via `SADK_ADVERTISE_IP`.
- Point **both** client configs at the stub: `data/lobby/config/LobbySettings.ini`
  and `data/game/settings/network.ini`. AdK patchlevel **9212**.
- Test credentials: `test` / `test` / `test`.
- **Git uses `master`, not `main`.** The game runs as admin; any live debugging (via
  the MCP) must be elevated too. Ghidra static addresses for `SADK.exe` (base
  `0x400000`) and `tincat3.dll` (`0x10000000`) line up with runtime.

---

## Reverse-engineering setup

- Connect the **Ghidra MCP** per `decomp/GHIDRA_MCP_SETUP.md`. Applied labels/structs
  live in `decomp/RENAME_LIST.md`.
- All RE and debugging goes through the MCP (HARNESS §1). Scripting *inside* Ghidra
  via the MCP is allowed; standalone RE/memory/patch scripts are not.
- **Follow the mandatory RE practices** in `HARNESS.md §6` / `decomp/RE_PRACTICES.md`:
  type everything, build typed vtable structs, one-layer-then-`[TODO]`, never fabricate
  structure, escalate purely-runtime-virtual calls to the user, keep the symbol map
  current.

## Windows 10/11 launch note

The Win10/11 village-enter crash is a **SecuROM-vs-modern-OS** protector issue, not
proof the protocol is wrong. The two runtime patches that get the genuine exe to boot
on Win10/11 are documented in `docs/BINARY_PATCHES.md`. Win7 runs natively. (The boot
itself is done by launching/attaching the game under a debugger — via the MCP — not a
standalone loader script.)

## Asset decryption / modding

The game's XML/Lua data files are encrypted. Prefer **`AdKEd.exe`** (the known-good
two-way converter); work on copies. See `docs/REVERSE_ENGINEERING_GUIDE.md` and
`docs/UI_FINDINGS.md`. Python decrypt tooling exists only for analysis/automation.

---

## Tooling (deliberately minimal — see `tools/`)

Only capabilities the Ghidra MCP and a debugger genuinely cannot provide survive here:
- `tools/lobby_proxy.py` — passive MITM proxy/logger of the live wire
- `tools/analyze_capture.py`, `tools/decode_lobby_capture.py`, `tools/decode_game_join.py`
  — offline decoders for captured traffic
- `tools/frida_mcp/` — **the live-debugging MCP** (Frida): call client functions, hook handlers, read
  objects and catch crashes in the running SADK.exe. Needs frida-server 17.22.2 (windows-x86) running as
  Administrator on the game PC; registered at USER scope as `frida-sadk` (`claude mcp add -s user`; a
  project `.mcp.json` entry is skipped in background sessions, which never show the approval prompt)
- `tools/sadk_crypt.py` / `tools/kex.py` — offline decryption of the game's encrypted data files and parsing /
  splitting of `.KEX` scenes (`docs/asset-formats.md`). Stated reason: `AdKEd.exe` (MEW-packed) crashes under
  Wine and no MCP converts files in bulk; both re-implement the client's own loaders, checked against every file
- `tools/cvar_client.py` — client for the game's own developer-tweak (CVar) server, which only exists after
  the optional patch in `docs/BINARY_PATCHES.md`; neither Ghidra nor a debugger speaks its text protocol

Adding anything else requires the stated-reason gate in `HARNESS.md §3`. Treat
captures/logs as valuable RE artifacts — don't delete or casually rewrite them.

---

## Conventions & known dead ends

- `master`, not `main`. File tools can't read raw `.bin` captures — decode to text first.
- Dead ends (keep dead unless new evidence): `-localhostmode`; two local client
  instances on one machine; treating the `170` wire layout as the source of
  room/validity (those values come from the `data` blob path).

---

## Testing

```bash
python tests/test_codec_golden.py     # 170 reproduced byte-for-byte vs the frozen legacy monolith
python tests/test_server_smoke.py     # end-to-end vs a fake socket
python tests/test_server_browser.py   # server-browser wire
python tests/test_multi_client.py     # multi-player + global game registry
# or: pytest tests/
```

---

## Maintainer context

The maintainer is a game-domain expert; weight their in-game instincts, especially:
**is the game actually waiting for something earlier in the real flow?** That instinct
was previously correct and is codified in `HARNESS.md §2`.
