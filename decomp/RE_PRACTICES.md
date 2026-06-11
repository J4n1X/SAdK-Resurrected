# RE practices — the runbook

Reverse-engineering is the project's deliverable (see `CLAUDE.md`: understanding first,
working second). This is the standard every agent follows when working the binary. The
binding short form is `HARNESS.md §6`; this file is the detailed how.

All of it runs **through the Ghidra MCP** (HARNESS §1). Scripting *inside* Ghidra via the
MCP is fine; standalone RE/memory/patch scripts are not.

---

## Why this exists

SAdK is a 2008 **MSVC C++** Win32 binary. The thing that repeatedly produces *false
conclusions* is **virtual dispatch**: a `call dword ptr [reg+0xNN]` whose concrete target
depends on the object's vtable, which may only be fixed at runtime. The practices below
turn as much of that as possible into named, typed, decompiler-resolved calls — and make
the genuinely-runtime cases a deliberate, evidence-backed user escalation rather than a
guess. We use the DRM-free **magazine ("Gold")** build: unpacked, RTTI intact, launches
natively, so both static recovery and live breakpoints are straightforward.

## Order of operations (per function / subsystem you touch)

1. **RTTI first.** Confirm the program's RTTI has been analyzed and names demangled. If
   not, **STOP and ask the user** to run Ghidra's RTTI analysis / class-reconstruction
   (or for permission to trigger it via the MCP). Do not reverse vtables on un-demangled
   output — RTTI gives you class names, hierarchy, and the vftables in `.rdata` for free.
2. **Recover the class + vtable.** From RTTI (and, if useful, an OOAnalyzer/Pharos import)
   identify the class, its vftable, and its constructor (the function that writes the
   vftable pointer to `this+0`). The constructor is what fixes the concrete type.
3. **Model it as a struct.** Create a struct for the class; make `this+0` a pointer to a
   typed `<Class>_vftable` struct whose members are the virtual functions with correct
   `__thiscall` prototypes. Now the decompiler resolves `(*this->vftable->slot_N)(...)`
   to a *named* function instead of an opaque indirect call.
4. **Type everything you touch.** Variables, parameters, returns; set the calling
   convention (`__thiscall` for methods, `__stdcall`/`__cdecl` as the call sites show).
   Aim for a decompilation a human can read without guessing.
5. **One layer deep, then stop.** If a type isn't clear from declaration + usage, look at
   **one** callee/caller deeper. Still unclear after that single hop → mark `[TODO]` and
   move on. Never recurse further; that rabbit hole is itself a failure mode.
6. **Never fabricate structure.** Unknown bytes stay `undefined`/padding. Don't invent
   fields or types to look complete. Evidence-backed type → `[PROVEN]`; inferred type →
   allowed but **marked** (a comment / a `_guess` suffix), never laundered to `[PROVEN]`.
7. **Ambiguous indirect call?** If the target is statically computable, resolve it with
   **P-code emulation**.
8. **Purely runtime-virtual? Escalate.** See below.
9. **Update the map.** Land every rename/retype/struct in `RENAME_LIST.md` +
   `docs/SOURCEMAP.md` **this session**.

## Escalating a runtime-virtual call to the user

When the concrete target is genuinely chosen at runtime (a factory returns a base
pointer; a subclass is selected by config/state), static analysis cannot resolve it and
you must read it live. The agent cannot drive the game UI — the user can. So:

1. Identify **all** the call sites / objects you need to resolve in this pass (don't do
   them one at a time).
2. Via the MCP debugger, set the breakpoints (at the indirect call site, read the target
   or `[this+0]` → the live vtable pointer; or at the constructor/factory to see which
   vtable it stamps).
3. Hand the user **one** concise script: *"launch the game, log in, navigate to X, do Y,
   then Z"* — the minimal in-game path that makes every breakpoint fire in a single play
   session.
4. Read the live targets, map them to the recovered vftables, label them, update the map.
5. Tag the result `[PROVEN]` (you have the live evidence) — and only then.

## Known runtime-polymorphic / vtable hotspots (seed targets)

Addresses are from the dump-base build; confirm against the loaded program (address-base
caveat in `MEMORY.md`). These are the indirections that have historically caused stalls:

- **`cPropertyFactory::CreatePropertySet(msgType)`** — tincat3, vtable **+0x0C**. Returns
  NULL until the message's template is registered (`RegisterPropertySet`); this is the
  EnterWorld(1000)/referee "push too early = NULL-deref" class of bug. Resolve which
  factory/templates are live *when* via a breakpoint.
- **Property reader vtable slots** — `+0x30` ReadString, `+0x18` ReadMemBlock(dst,0x20),
  `+0x20` wide slot. These drive every body-parse; mis-typing a slot desyncs the parse.
- **`LobbyComm` comm-layer creation** (single comm layer, magic 0x26B6) and the
  `LobbyManager` state pump / `SetState` — the connection objects are polymorphic.
- **Connection vtables** (from `RENAME_LIST.md`): UserComm `0x7dded8`, GameServer
  `0x7dfafc`, Village `0x7dc8e0`. Bind these as typed vftable structs.

## Map maintenance

The symbol map (`RENAME_LIST.md`, `docs/SOURCEMAP.md`) is authoritative project memory
and must be kept current at all times — a stale map re-introduces solved false
conclusions. Related TODOs (see `MEMORY.md`): the big retro-typing sweep, an MCP-run
Ghidra script to re-export the C dumps on demand, and a map-vs-project audit.
