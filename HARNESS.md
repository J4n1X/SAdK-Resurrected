# HARNESS — Binding Rules of Engagement

> **Status: BINDING.** Every agent working in this repo MUST follow this document.
> It is short on purpose. Read it in full before doing any RE, debugging, protocol
> work, or stub changes.

The harness exists to enforce three things: **use the right tool (the MCP), don't
fake results, and report status honestly.**

---

## 1. MCP-FIRST — the Ghidra MCP is the way you do RE and debugging

Any task that the **Ghidra MCP** can do, you **MUST** do through the Ghidra MCP:
decompilation, disassembly, xrefs, listing/searching symbols, reading/renaming
functions and data, creating structs/classes/enums, applying types/prototypes,
chasing state-setters, and **live debugging** (the MCP exposes debugging; if a
specific debugging capability turns out to be missing, see §3 — you add a debugger
MCP, you do not write a script).

- **Running a script *inside* Ghidra via the MCP's script-runner is ALLOWED** and
  encouraged for batch RE work (e.g. applying a rename plan, scanning for field
  writes). That is "use the MCP," not "circumvent it."
- **Writing a standalone Python/PowerShell/shell script to do RE or debugging is
  FORBIDDEN.** Parsing offline decompile dumps, driving Ghidra over raw HTTP,
  `ReadProcessMemory` probes, module dumps, minidump parsing, breakpoint tracers,
  remote-thread/force-call injectors, `WriteProcessMemory`, binary byte-patchers —
  **all of that is circumvention and is not allowed.** Those tools were deleted; do
  not recreate them. If you feel the urge to "just write a quick script to read X
  from the binary/process," that urge is the signal to **use the MCP instead.**

The setup runbook for the MCP link is `decomp/GHIDRA_MCP_SETUP.md`.

## 2. NO FAKING RESULTS

You may not force, inject, patch, or otherwise bypass the game's own logic to make
something *look* like it works. A forced/patched outcome is never a solution and is
never reported as success.

If the game appears stuck, the first question is always: **is it legitimately
WAITING for something we should provide through its real mechanism?** (The canonical
case: the client parks in LobbyManager EnteringVillage(8) waiting for the server to
push `EnterWorld(1000)`. The fix is to send 1000 over the wire — the genuine
mechanism — not to force a screen transition.) Provide the awaited input through the
real path; never simulate the result.

## 3. NEW TOOLS — state the reason, in detail, FIRST

Before you write **any** new tool or script, you must state, up front and in detail:

1. **the exact capability** you need;
2. **why neither the Ghidra MCP nor a debugger MCP can provide it** (be specific —
   "the MCP can't sniff TCP between the client and the stub" is valid; "it's easier
   in Python" is not);
3. **why it's necessary** for the task at hand.

If you cannot make that case, you do not write the tool — you use the MCP. The only
category that has so far cleared this bar is **network capture/decode** (passive
MITM of the wire, offline decoding of captures) — things genuinely outside the reach
of a static-analysis MCP and a debugger. New tools that duplicate MCP/debugger
functionality will be rejected.

## 4. HONEST STATUS — PROVEN vs TODO

- **`[PROVEN]`** means: a binary address **and** live evidence back the claim. Only
  then may you call something proven.
- Everything else is **`[TODO]`** (or `[HYPOTHESIS]`) and must be **labelled** as
  such — in docs, in code comments, and in messages to the user.
- Do not launder a guess into a fact by repetition or by a single lucky observation.
  "I believe X but haven't proven it" is a correct and welcome sentence.

## 5. THE STUB — working behaviour is the default; no flags, no hidden hacks

- **Never gate a working feature behind a config flag.** If it works, it is the
  default. (The codebase was previously bloated with `⛔ off-by-default` toggles and
  an "engagement record" gate; that is gone and must not come back.)
- **Do not introduce a hack, bypass, or new flag without explicit user permission.**
  Don't paper over a problem with a special case — fix it at the real layer.
- The stub's wire behaviour is **byte-exact territory.** `msgdefs.ini` is
  authoritative; any wire-format change must be grounded in it + binary evidence and
  re-validated against the real client. Preserve edge cases (e.g. `None` vs `""`).

## 6. RE PRACTICES — mandatory

Reverse-engineering *is* the deliverable (`CLAUDE.md`), so it is done to a standard,
through the Ghidra MCP. Full runbook: `decomp/RE_PRACTICES.md`. The binding rules:

- **Type everything you touch** — variables, parameters, returns — and set the correct
  MSVC calling convention (`__thiscall` / `__stdcall` / `__cdecl`). Model each class as
  a struct whose `this+0` points to a **typed vftable struct** of function pointers, so
  the decompiler resolves virtual calls to *named* functions.
- **RTTI first.** Before reversing any vtables, verify the program's RTTI has been
  analyzed/demangled. If it has not, **STOP and ask the user** to run it (or for
  permission to trigger it via the MCP) — do not reverse vtables on un-demangled output.
- **One layer deep, then stop.** Infer a type from its declaration + usage; if still
  unknown, look at most **one** callee/caller deeper. If it is *still* unknown after
  that single hop, mark it `[TODO]` and move on. **Never recurse further.**
- **Never fabricate structure.** Unknown bytes stay `undefined`/padding — you do not
  invent fields or types to look complete. A type backed by RTTI, a known API/import, or
  clear usage is `[PROVEN]`; an inferred one is allowed but must be **marked**, never
  laundered into `[PROVEN]`.
- **Resolve ambiguous indirect calls with P-code emulation** where the target is
  statically computable.
- **Purely runtime-virtual → escalate to the user.** When a call target is genuinely
  chosen at runtime (a factory returning a base pointer, a config-selected subclass),
  static analysis *cannot* resolve it — and guessing is how false conclusions happen.
  Set up the breakpoint(s) via the MCP debugger and hand the user **one batched**
  "navigate the game to X, do Y, then Z" script so they fire every needed breakpoint in
  a single play session; read the live targets, then label them.
- **Keep the map current — always.** Every rename / retype / new struct lands in
  `decomp/RENAME_LIST.md` and `docs/SOURCEMAP.md` **in the same session**. A stale map
  is how false conclusions creep back in.

---

### TL;DR

**Do RE and debugging through the Ghidra MCP — scripting *inside* Ghidra is fine,
writing external RE/memory/patch scripts is not. Don't fake results; provide what
the game waits for through its real mechanism. New tools need a stated, detailed
reason and must be outside MCP/debugger reach. Proven = binary + live evidence;
everything else is labelled TODO. In the stub, working = default — no flags, no
unsanctioned hacks. Type everything, build typed vtable structs, stay one layer deep,
never fabricate, escalate runtime-virtual calls to the user, keep the map current.
Understanding is the deliverable — build it brick by brick, don't sprint.**
