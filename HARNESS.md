# HARNESS — binding rules of engagement

> **Status: BINDING.** Every agent working in this repository follows this document. Read it in full before any
> reverse engineering, live debugging, protocol work, server or mod change.

The harness enforces four things: **use the right tool (the MCPs), don't fake results, report status honestly,
and spend the maintainer's time only where nothing else can.** All of them serve the goal in `CLAUDE.md`:
understanding is the deliverable.

---

## 1. MCP-first

- **Static analysis goes through the Ghidra MCP**: decompilation, disassembly, xrefs, symbol search, renaming,
  structs / classes / enums, types and prototypes, comments, check-ins. Setup: `docs/HEADLESS_SETUP.md`.
- **Live debugging goes through the Frida MCP** (`frida-sadk`, `tools/frida_mcp/`): reading objects, hooking
  handlers, calling client functions, catching crashes in the running game. Runbook: `docs/LIVE_DEBUG_RUNBOOK.md`.
- **Scripts run inside Ghidra through the MCP are allowed** and encouraged for batch work (the mapping pipeline's
  `mapping/scripts/*.java`, measurement scripts, applying a rename plan). That is using the MCP.
- **Standalone scripts that do RE or debugging are forbidden**: parsing offline decompile dumps, driving Ghidra
  over raw HTTP, `ReadProcessMemory` probes, module dumps, tracers, injectors, `WriteProcessMemory`, binary
  byte-patchers. The urge to "just write a quick script to read X from the binary or the process" is the signal
  to use an MCP. If an MCP lacks a capability, extend the MCP; don't write a script around it.

## 2. No faked results

Never force, inject, patch or otherwise bypass the game's own logic to make something *look* like it works. A
forced outcome is never a solution and is never reported as success.

If the game seems stuck, the first question is: **is it legitimately waiting for something we should provide
through its real mechanism?** (The canonical case: the client parks in `LobbyManagerState` EnteringVillage(8)
until the server pushes `EnterWorld(1000)`; the fix is to send 1000, not to force a screen transition.)

Writing game memory, or calling client functions that change game state, in a live session needs the
maintainer's explicit go-ahead unless the call is already approved. Say what you call and why.

## 3. New tools — state the reason first

Before writing **any** new tool or script, state in detail:

1. **the exact capability** needed;
2. **why neither the Ghidra MCP nor the Frida MCP can provide it** ("the MCP can't sniff TCP between the client
   and the server" is a reason; "it's easier in Python" is not);
3. **why the task needs it.**

If you cannot make that case, use the MCPs. The tools that cleared this gate are listed in `CLAUDE.md` ("Tools
and setup"); each names its reason in its header or README. The categories so far: network capture and offline
decoding, offline decoders of the game's data formats that re-implement the client's own loaders, code
generation from the committed sourcemap, file-format conversion, a game-window screenshot, a client for the
game's own CVar server, and the installer of the Ghidra MCP itself.

## 4. Honest status

| Tag | Meaning |
|---|---|
| `[PROVEN]` | a binary address **and** live evidence (name the source and date of the evidence) |
| `[known]` | read directly in the binary (address, constant, string, vtable slot) or in a named data file and key |
| `[inferred]` | one step of reasoning from what is visible |
| `[HYPOTHESIS]` / `[TODO]` | not established; say what would settle it |

Label every claim in docs, code comments and messages to the maintainer. Don't launder a guess into a fact by
repetition or by one lucky observation. "I believe X but haven't proven it" is a correct and welcome sentence.

## 5. The server — working behaviour is the default

- **Never gate a working feature behind a config flag.** If it works, it is the default.
- **No hack, bypass or new flag without the maintainer's explicit permission.** Fix problems at the real layer;
  don't paper over them with a special case.
- **Consult the client before implementing.** Read the client's whole code path for the feature in Ghidra first
  (every handler, the observers it fires, the UI and 3D code that consumes the state, its crash limits:
  unchecked indexes, counts, NULL objects); implement after that. Never patch reactively from a live failure.
- The wire is **byte-exact territory.** `msgdefs.ini` is authoritative; a wire change needs `msgdefs.ini` plus
  binary evidence and re-validation against the real client. Preserve edge cases (`None` vs `""`).

## 6. RE practices — mandatory

Full standard: `decomp/RE_PRACTICES.md`. The binding core:

- **Never map Ghidra's `/SADK.exe`**: it is a SecuROM dump-base build with other addresses. The game exe is
  `/sadk_noav.exe`; the DLLs are `/tincat3.dll` and `/NXCHARACTER.DLL`.
- **Type everything you touch** (variables, parameters, returns) with the right MSVC calling convention, and
  model each class as a struct whose `this+0` points to a typed vftable struct, so virtual calls resolve to names.
- **Measure, then read.** Ownership and layout questions are settled by measurement (the mapping scripts in
  `mapping/scripts/`), sampled against the code before they are applied.
- **One layer deep, then `[TODO]`.** Infer a type from its declaration and use; look at most one caller or callee
  further; if it is still unknown, mark it and move on.
- **Never fabricate structure.** Unknown bytes stay undefined; an inferred type is marked as inferred.
- **Evidence decides names.** Hand-made names are not protected: a change that overwrites earlier work is applied
  when the evidence supports it, and no rename is made on a guess.
- **One writer per struct.** Fan out read-only analysis; apply struct edits serially.
- **Runtime-virtual targets** that static analysis cannot resolve are measured live with Frida hooks (§7).
- **Keep the map current and published.** Changes are checked in to the Ghidra Server repository in the same
  session; a mod or doc that needs new names gets a re-exported `sadkmod/sourcemap/` and regenerated sadkmod
  before it is written ("map before mod code").

## 7. Live testing — only when the code cannot answer

**A live test may only be asked for when the behaviour cannot possibly be read from code** (maintainer,
2026-10-14). Read the code path to its end first. What qualifies: what the screen or the speaker shows, the timing
of real networks and hardware, libraries that cannot be read (packed `fmod.dll`, drivers), the original servers.
"Confirming the reading" is not a reason.

Sort every list of checks into (1) answerable by reading — do it; (2) measurable unattended in a running game
(hooks, reads, orders through the game's own send functions on the main thread) — run it yourself, with the game
window in the foreground, a throwaway match and every call into the game stated; (3) needs the maintainer's eyes,
ears or a second player — hand over only these, as one short list. No hardware watchpoints from JS: they stalled
and then killed the game (2026-10-14); use static xrefs and Interceptor hooks.

## 8. Evidence lives in the reference docs

No session diaries, hand-off notes or engagement records are kept. A result goes into the reference doc it
belongs to, as the current model, with its tag, its addresses and (for live evidence) the date and source. When
the model changes, the doc is corrected in place, without a story of the reversal; the history is in git.
Captures, logs and the raw measurement records of a live run (`docs/live-checks/`) stay as artifacts, cited by
the reference docs that use them.

---

### TL;DR

**Ghidra MCP for static work, Frida MCP for live work; scripting inside Ghidra is fine, external RE / memory /
patch scripts are not. Don't fake results; provide what the game waits for through its real mechanism. New tools
need a stated reason. Tag every claim honestly. In the server, working = default, no flags, no unsanctioned hacks,
and read the client before implementing. Type everything, measure before reading, stay one layer deep, never
fabricate, keep the map checked in and published. Ask for a live test only when the code cannot answer.**
