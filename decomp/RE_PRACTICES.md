# RE practices — the runbook

Reverse-engineering is the project's deliverable (see `CLAUDE.md`: understanding first,
working second). This is the standard every agent follows when working the binary. The
binding short form is `HARNESS.md §6`; this file is the detailed how.

All of it runs **through the Ghidra MCP** (HARNESS §1). Scripting *inside* Ghidra via the
MCP is fine; standalone RE/memory/patch scripts are not.

> ## ⚠️ Which binary — work on `sadk_noav.exe`
> The **active RE target is `sadk_noav.exe`** (the DRM-free unpacked "Gold" build, RTTI intact).
> `SADK.exe` is a **different build** — different code addresses *and* different struct layouts
> (e.g. `LobbyManager::SetState` is `0x462540` in `sadk_noav.exe` vs `0x462700` in `SADK.exe`;
> `VillageServerConnection` is 584 vs 600 bytes). Do not mix them up: apply renames/types/structs to
> **`sadk_noav.exe`**, and always pass the `program="sadk_noav.exe"` parameter on MCP calls (both
> programs are open in the backend). `SADK.exe` is kept only as a cross-reference; addresses in the
> older docs/`SOURCEMAP.md` are from that dump-base build and must be re-derived against `sadk_noav.exe`.

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

## Class hygiene — make a class look like one uniform C++ class

`set_function_this_type` is great for typing `this`, but it has a trap: if your struct's
name doesn't match the RTTI-recovered class, it **creates a duplicate bare-Global
`GhidraClass`** instead of using the proper `Ns::Class`. Combined with `__thiscall`
methods that were typed but never scoped, you end up with the classic mess: **two
class nodes** for one C++ class, plus members loose in `Global`, so calls render
double-scoped or unscoped. This is cosmetic-looking but it actively hides which methods
belong to the class. Fix it whenever you finish typing a class.

**The canonical layout (what "uniform C++" means here):** one `GhidraClass` named for
the RTTI class (`LobbyComm::X`), the struct living in the **matching category**
(`/LobbyComm/X`) so the data-type name lines up with the class, and **every** member
function parented to that one class namespace. Then the decompiler shows
`void __thiscall LobbyComm::X::Method(X *this, ...)` and sibling calls resolve by name.

### Rules (read before running the script)

1. **RTTI is the source of the canonical name.** Confirm it via the type-descriptor
   string: search memory for `.?AVX@Ns@@` (e.g. `.?AVUserCommConnection@LobbyComm@@` →
   the class is `LobbyComm::UserCommConnection`). Use that exact namespace.
2. **No RTTI descriptor?** You do **not** have a proven namespace. Either (a) derive one
   from hard structural evidence — e.g. a base class whose methods are called by several
   known `Ns::*` subclasses belongs in `Ns` (that's how `LobbyComm::LobbyBaseConnection`
   was placed) — and **mark it inferred, not `[PROVEN]`** in the checkin/`MEMORY.md`; or
   (b) **defer it** and flag the open question. Never invent a namespace from a guess.
3. **Same simple name ≠ duplicate.** `NMap::AStar` vs `NNavy::AStar`, the 16 `*::System`,
   `Logger` (`.?AVLogger@@`, real engine logger) vs `LobbyComm::Logger` (different
   vftables) — these are **distinct C++ classes**. Only a *bare-`Global` twin of a
   namespaced class*, or *loose `Global` `__thiscall` members*, is the artifact to fix.
   Check vftable addresses before merging anything that shares a name.
4. **`this`-types survive the move** — they live on the function's params, not its
   namespace; moving the struct's category doesn't change its identity. So this pass is
   safe and reversible (you're checked into the repo). Verify anyway by decompiling one
   method afterward.
5. **Second-order mangle:** loose members often already carry an embedded `X::` in their
   *simple* name. After moving them into `Ns::X` that becomes `Ns::X::X::Method` — strip
   the redundant `X::`/`X_` prefix (the script does this).

### The template (run via `run_script_inline` — scripting inside Ghidra is HARNESS-OK)

Set `CLASS`/`PARENT`/`TARGET_CAT` at the top. If the `PARENT::CLASS` GhidraClass already
exists (RTTI made it) it's reused; otherwise it's created (rule 2 must hold first).

```java
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;

String CLASS="UserCommConnection", PARENT="LobbyComm", TARGET_CAT="/LobbyComm";
SymbolTable st=currentProgram.getSymbolTable();
DataTypeManager dtm=currentProgram.getDataTypeManager();
FunctionManager fm=currentProgram.getFunctionManager();

Namespace parent=st.getNamespace(PARENT, currentProgram.getGlobalNamespace());
GhidraClass cls=null; Namespace dup=null;            // dup = bare-Global twin, if any
for (Symbol s: st.getSymbols(CLASS)) if (s.getObject() instanceof GhidraClass) {
  if (s.getParentNamespace().getName().equals(PARENT)) cls=(GhidraClass)s.getObject();
  else if (s.getParentNamespace().isGlobal())          dup=(Namespace)s.getObject();
}
if (cls==null) cls=st.createClass(parent, CLASS, SourceType.USER_DEFINED);   // rule 2!

DataType s0=dtm.getDataType("/"+CLASS);               // align struct category
if (s0!=null) s0.setCategoryPath(new CategoryPath(TARGET_CAT));

java.util.LinkedHashSet<Function> mem=new java.util.LinkedHashSet<>();        // collect members
for (Function f: fm.getFunctions(true)) {
  if (!"__thiscall".equals(f.getCallingConventionName()) || f.getParameterCount()==0) continue;
  DataType p0=f.getParameter(0).getDataType();
  if (p0 instanceof Pointer) { DataType b=((Pointer)p0).getDataType();
    if (b!=null && b.getName().equals(CLASS)) mem.add(f); }
}
if (dup!=null){ SymbolIterator it=st.getSymbols(dup); while(it.hasNext()){
  Symbol s=it.next(); if(s.getSymbolType()==SymbolType.FUNCTION){Function f=fm.getFunctionAt(s.getAddress()); if(f!=null) mem.add(f);} } }

for (Function f: mem) if (f.getParentNamespace()!=cls) f.getSymbol().setNamespace(cls);  // setNamespace(Namespace) — ONE arg

String[] pref={CLASS+"::", CLASS+"_"};                // strip redundant prefixes
SymbolIterator it=st.getSymbols(cls);
while (it.hasNext()){ Symbol s=it.next(); if(s.getSymbolType()!=SymbolType.FUNCTION) continue;
  Function f=fm.getFunctionAt(s.getAddress()); String n=f.getName(),nn=n;
  for(String p:pref) if(n.startsWith(p)){nn=n.substring(p.length());break;}
  if(!nn.equals(n)&&nn.length()>0) f.setName(nn, SourceType.USER_DEFINED); }

if (dup!=null && !st.getSymbols(dup).hasNext()) dup.getSymbol().delete();     // drop empty twin
```

Then **verify** (decompile a member — confirm `Ns::Class::Method(Class *this, …)` and
that the struct fields / virtual calls still resolve) and **`checkin_program`** with a
comment that states whether the namespace was RTTI-proven or inferred. Gotchas that bit
us: `Symbol.setNamespace` takes the namespace **only** (no `SourceType` overload);
`FlatProgramAPI.find(String)` is the single-arg string search (not `find(null, str)`).

## Map maintenance

The symbol map (`RENAME_LIST.md`, `docs/SOURCEMAP.md`) is authoritative project memory
and must be kept current at all times — a stale map re-introduces solved false
conclusions. Related TODOs (see `MEMORY.md`): the big retro-typing sweep, an MCP-run
Ghidra script to re-export the C dumps on demand, and a map-vs-project audit.
