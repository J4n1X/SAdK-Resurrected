# RE practices — the runbook

Reverse engineering is the project's deliverable (`CLAUDE.md`: understanding first, working second). This file is
the detailed how behind the binding short form in `HARNESS.md` §6.

All of it runs through the MCPs (HARNESS §1): the Ghidra MCP for static work, the Frida MCP (`frida-sadk`,
`tools/frida_mcp/`) for the running game. Scripts that run inside Ghidra through the MCP (`run_ghidra_script`,
`run_script_inline`) are fine; standalone RE, memory or patch scripts are not.

Addresses below: `S` = `sadk_noav.exe`, `T` = `tincat3.dll`.

---

## 1. The map

### Where it lives

The map is the Ghidra Server repository `sadk`; the MCP backend works on a checkout of it (setup:
`docs/HEADLESS_SETUP.md`).

| Program | What | Image base |
|---|---|---|
| `/sadk_noav.exe` | the DRM-free `SADK.exe` on disk (MD5 `d4832bc5103c14f5445471af29b8d778`), RTTI intact | `0x400000` |
| `/tincat3.dll` | the TinCat network layer (MD5 `8addb5da4b82956cdb67984181bb04e0`) | `0x10000000` |
| `/NXCHARACTER.DLL` | the PhysX character controller, mapped by hand; not in the sourcemap | `0x10000000` |

- **Never map `/SADK.exe`.** It is a SecuROM dump-base build with other code and vtable addresses
  (`LobbyComm::System::SetState` is `0x462540` in `sadk_noav.exe` and `0x462700` there; the village vtable is
  `0x7db8d4` here and `0x7dc8d4` there). Keep it closed in the backend, so a wrong `program=` fails instead of
  answering from the wrong build.
- Pass `program="sadk_noav.exe"` or `program="tincat3.dll"` on every MCP call.
- An address in an older note that does not fit comes from the dump-base build: re-derive it against
  `sadk_noav.exe`.
- Static addresses are the runtime addresses (no rebase), in Ghidra and in Frida alike.

### What is authoritative

Ghidra is the map. Everything else is derived from it or describes it:

| Where | What |
|---|---|
| `sadkmod/sourcemap/` | the published export: names, signatures, types and comments by address (`sadkmod/sourcemap/README.md`); sadkmod's C++ declarations are generated from it |
| `docs/types.md` | the recovered classes and structs; how types are organised in Ghidra (§5) and the naming conventions (§6) |
| `docs/message-catalog.md` | every network message the client speaks |
| `docs/SOURCEMAP.md` | the lobby, village and match-network names with their roles |
| `mapping/` | the mapping pipeline (`README.md`, `AGENT_GUIDE.md`). Its local, gitignored `state.db` records every change made through the change queue: `python3 mapping/bin/changes.py fn <addr>` shows a function's history with the decompile before and after |
| `decomp/RENAME_LIST.md` | a dated log of hand renames, 2026-06 to 2026-10, kept as history. It is not the map, and nothing new is added to it; read it as evidence to check, like every older note |

A hand edit made outside the change queue is recorded by its `checkin_program` comment and by the document that
carries the finding.

### Confidence

In Ghidra every claim carries a tier: a plate has an `[ai]` block with `conf=` and its evidence, a struct field
carries `[ai:<conf>]` in its comment.

- `known`: directly visible in code or data (a string, a constant, RTTI, a vtable slot, an import, an allocation
  size).
- `inferred`: strong evidence from callers, strings and types, not directly visible.
- `guess`: plausible, unverified.

Documents use the tags of HARNESS §4 (`[PROVEN]` needs a binary address and live evidence). A tier is never
raised without new evidence; when in doubt, go lower.

---

## 2. Why this exists

SAdK is a 2008 MSVC 8 C++ Win32 binary. What repeatedly produced false conclusions is virtual dispatch: a
`call dword ptr [reg+0xNN]` whose target depends on the object's vtable, which may be fixed only at run time. The
practices below turn as much of that as possible into named, typed calls the decompiler resolves, and make the
genuinely runtime cases a measured result instead of a guess.

---

## 3. Order of operations (per function or subsystem)

1. **RTTI first.** RTTI analysis has run on `sadk_noav.exe`, `tincat3.dll` and `NxCharacter.dll`, with names
   demangled. For any new program, confirm it before reversing a vtable; if it has not run, run Ghidra's RTTI and
   demangler analyzers on it through the MCP first (`list_analyzers`, `run_analysis`), and say so in the check-in
   comment. Never reverse vtables on un-demangled output. RTTI gives the class names, the hierarchy (base classes
   with their displacements) and the vftables in `.rdata`.
2. **Recover the class and its vtable.** From the RTTI type descriptor (`.?AVX@Ns@@` → `Ns::X`), its vftable and
   its constructor (the function that stores the vftable pointer at `this+0`). The constructor fixes the concrete
   type. `operator new(n)` right before it gives the struct size (`known`), once you have checked that the call
   after it is the class's own constructor and not a base-class or temporary one.
3. **Model it as a struct.** The class struct lives at `/<Namespace>/<Class>`, where Ghidra's `this` typing looks
   for it. Its `+0` points to `/<Namespace>/<Class>_vftable`: one field per slot, named after the method, typed as a
   pointer to a function definition that is `__thiscall` with the explicit `this` as its first parameter, and with
   the method named in the field comment (sadkmod types the slot from that comment). The decompiler then shows
   `this->pVftable->Method(...)` instead of an opaque indirect call.
4. **Type everything you touch.** Variables, parameters, returns. Take the calling convention from the
   disassembly, not from a declaration: `RET n` must pop exactly the stack bytes the prototype declares (`__cdecl`
   returns with `RET 0`), and a function that never reads ECX is not `__thiscall`.
5. **Measure ownership and layout questions** program-wide (§5) instead of reasoning them out one function at a
   time.
6. **One layer deep, then stop.** Infer a type from its declaration and its uses; if it is still unclear, look at
   one callee or caller deeper. Still unclear after that hop: type it as far as the evidence goes and record the
   open point. Do not recurse through the call graph to type one variable; program-wide questions go to the
   measurements (§5).
7. **Never fabricate structure.** Unknown bytes stay undefined. A field needs an access in code you have read:
   offset, width, how it is used, what is stored. Never pad a struct to look complete; without an allocation size
   the highest evidenced offset is only a lower bound. Bytes a constructor writes in a regular pattern are usually
   an inlined member constructor: embed the member type instead of naming its dwords (`/std/string`, 0x1c bytes in
   MSVC 8; `/ai/std/MsvcList`; `/ai/stl/MsvcVector`; `/ai/stl/MsvcTree`; check them with `get_struct_layout`
   first). An array of a class built in a loop is `Class[n]`.
8. **Ambiguous indirect call** whose target is statically computable: resolve it with P-code emulation
   (`emulate_function`, `get_function_pcode`).
9. **Target chosen only at run time:** §10.
10. **Write it back and keep the map current:** §6 and §7.

**Open points.** A `[TODO]` says in one sentence what is known and which observation would decide the rest. Facts
are not open points: "no caller in this binary" or "the server decides this" are stated plainly, without `[TODO]`.

---

## 4. Evidence is the only safeguard

- **Hand-made work is not protected** (maintainer rule, 2026-10-12). The pipeline writer runs with
  `PROTECT_PRIOR = false`, and a hand edit through the MCP follows the same rule: a change that overwrites earlier
  names, fields or types is applied when the evidence supports it, and its evidence says why.
- **Prior names are evidence, not truth.** Confirm, refine or replace them from the code.
- **No guess-level renames.** A name needs `inferred` or `known` evidence. A best guess goes into the plate as
  "possible name: X (guess, because …)", and the default name stays. A shape name inside the right class
  (`SetByte_1ec`) is honest and `known`.
- **Keep a replaced name findable.** The writer keeps an overwritten function name as a secondary label and in the
  plate, and a replaced field name in the field comment ("Was …"). Do the same for a direct MCP edit.
- **Naming.** Methods are `Namespace::Class::Method`, with RTTI class names exactly as RTTI spells them. Free
  functions are `Subsystem_VerbObject`. Library code carries its library's real names (`lua_pushstring`,
  `memcpy`). Only constructors, destructors and operators get C++-style names (`ctor`, `dtor`,
  `scalar_deleting_dtor`). Full table: `docs/types.md` §6.

---

## 5. Measure, then read

Who owns a method and what a struct holds are measurable. Four read-only scripts in `mapping/scripts/` decompile
every function and write what the p-code shows to `mapping/cache/<prog>/verify/`:

| Script | Writes | Decides |
|---|---|---|
| `RefUsers.java` | `users.jsonl` | which RTTI vftable slots and which callers use a function |
| `ReceiverTypes.java` | `receivers.jsonl` | the receiver's type at every direct call site of a method |
| `DumpHierarchy.java` | `hierarchy.tsv` | RTTI bases and their offsets per vftable, the vftable slots, the first member of each struct |
| `StructEvidence.java` | `member_ctors.jsonl`, `field_access.jsonl` | which member constructor runs on `this+offset`; which undefined struct bytes are read or written, with what width and type |

They run with `run_ghidra_script`; the MCP finds scripts in `~/ghidra_scripts/`, so copy them there and keep the
copies identical to `mapping/scripts/`. `mapping/bin/owners.py` turns the first three into a verdict per function
(one class, a base class, unrelated classes, untyped). `mapping/bin/struct_fill.py` turns the fourth, with the type
dump of `DumpTypes.java`, into change files for the writer. Reading is for what the measurement cannot decide.

- **Sample a measurement before applying it.** A measurement can be wrong in a systematic way: through a method
  that runs on a secondary base pointer, every offset it shows is shifted by that base's offset.
- **Owner verdicts.** All users are one class or derive from it: the class's method. Unrelated classes: a body the
  linker folded (`ICF_SHARED`, §11). Siblings under one base: the base's method only if the base declares the slot
  and the body touches only the base's fields, otherwise folded. A `__cdecl` or `__stdcall` helper is never moved
  into a class on call-site evidence alone.
- **After a writer pass, run `Verify.java`.** It checks stack clean-up against the prototype, allocation sizes
  against struct sizes, vftable slots whose function still sits in Global, placeholder types in prototypes, plates
  without a confidence, and duplicate field names. Its allocation check takes the first constructor after
  `operator new`, which is sometimes a base-class or temporary one: read such a finding before acting on it.

---

## 6. Writing to the map

- **Batches go through the change queue.** A measurement's output, a pass over many functions or a reading agent's
  results become change files (format: `mapping/AGENT_GUIDE.md` §7), applied by the single writer
  `mapping/scripts/ApplyChanges.java` (its `test` mode applies, records and rolls back). The queue records every op
  in `mapping/state.db`. A few targeted edits may use the MCP's write tools directly.
- **One writer per struct.** Adding or removing a field in a packed struct shifts every later offset, so parallel
  agents editing one struct corrupt each other. Fan out read-only analysis; apply struct edits serially, with
  `recreate_struct` for a whole-struct rebuild.
- **Read-only agents call no write tool.** That includes `disassemble_bytes`, which creates instructions even with
  `dry_run`; read code with `disassemble_function` or `read_memory`.
- **One backend serves one call at a time.** For many functions, read the decompile cache
  (`python3 mapping/bin/mapctl.py fn <prog> <addr>`) or refresh it in one call (`run_ghidra_script` with
  `Extract.java`, args `list <addrFile> <outFile>`).
- **Saving.** Ghidra wraps every script in a transaction, so scripts do not save. Persist with `save_program`, or
  with `checkin_program` and a comment that says what changed and on what evidence, which creates a server
  version. `checkin_program` unloads the program, even with `keep_checked_out=true`: call
  `load_program_from_project` right after, or the next call with `program=…` fails. `server_status` may report
  "not connected" while check-in works.
- **Stale checkout.** If check-in fails because the checkout is behind the server: without local changes,
  fast-forward it with `DomainFile.merge(true, monitor)` from an inline script run under another open program;
  with local changes, `mapping/scripts/RebaseNoav.java` (`plan`, `swap`, `apply <baseVersion>`) rebases them three
  ways, and the server's version wins a conflict. Never edit the project files by hand.

---

## 7. Keeping the map current

The map is current when Ghidra holds the finding and what is derived from it follows:

1. Edit in Ghidra: named, typed, with evidence.
2. `checkin_program`, then `load_program_from_project`.
3. When mods or documents need it, re-export the sourcemap: `run_ghidra_script` with `ExportSourcemap.java` per
   program and the sourcemap folder (`<repo>/sadkmod/sourcemap`) as argument, then `ExportTypesJson.java` with the
   program's folder (`<repo>/sadkmod/sourcemap/<program>`). Details and the headless variant:
   `sadkmod/sourcemap/README.md`.
4. `make` in `sadkmod/` regenerates the declarations. Then build the mods (`make -C mods`,
   `make -C lobby/mods SADKMOD=../../sadkmod`): a re-export can rename a declaration a mod uses, and such a mod is
   fixed in the same change.
5. Commit the sourcemap in the `sadkmod` submodule, push it there, and update the submodule pointer here.
6. When a finding changes what a document states (`docs/types.md`, `docs/message-catalog.md`, `docs/SOURCEMAP.md`,
   `docs/sim/`), update the document in the same session.

---

## 8. Map before mod code

Every game field, type or function a mod touches is mapped first: named, typed and with evidence in Ghidra, checked
in, exported, sadkmod regenerated (§7). Only then is the mod written, against the generated declarations
(`sadkmod/docs/writing-mods.md`).

- No raw offsets (`reinterpret_cast<char *>(p) + 0xNN`), no local `sadk::Fn` / `sadk::Var` stand-ins for something
  the map should declare, no `void *` where the type is known.
- Verify the calling convention from the disassembly (§3, step 4), not from the generated declaration: a
  declaration is only as good as the map.
- A method entered through a secondary vftable is declared with `sadk::Face<Class, offset> *` as its `this`; pass
  it on unchanged, and `object()` gives the `Class *`.

---

## 9. Before changing server behaviour, read the client

The rule is HARNESS §5: read the client's whole code path for a feature before the server implements or changes it.
How:

- List the client functions involved: the message handlers, the observers they fire, the dialogs' update and
  phase code, the 3D controllers and per-type proxies that consume the state. Read them to the end, including the
  crash limits (unchecked indexes and counts, NULL objects).
- Start from `docs/message-catalog.md` for the wire and the server behaviour the client requires; `msgdefs.ini` is
  authoritative for the schema.
- A large audit fans out to parallel read-only agents; spot-check their key claims yourself.
- Ask the maintainer only for what the binary cannot contain (game rules, the original servers' behaviour).
- Implement after the audit, then test live. A live failure is not a reading method: each reactive fix only finds
  the next gap the code already showed.

---

## 10. Calls resolved only at run time

When the concrete target is chosen at run time (a factory returns a base pointer, a subclass is selected by
configuration or state), static analysis cannot resolve it, and guessing is how false conclusions start.

When a live check is allowed, and who runs it, is HARNESS §7. The RE side:

1. **Read to the end first.** Most targets are fixed by a constructor or factory reachable in the binary: the RTTI
   vftables that hold the slot (`RefUsers.java`), the receiver types at the call sites (`ReceiverTypes.java`), the
   constructors that store each candidate vftable, P-code emulation.
2. **Measure live with the Frida MCP** (`docs/LIVE_DEBUG_RUNBOOK.md`). Hook the indirect call site, or the factory
   or constructor (`frida_hook` records ECX, the stack arguments and the return value; `frida_events` reads them),
   read `[this+0]` (`frida_read_u32`) and map the vftable address to its RTTI class.
   - Interceptor hooks only, no hardware watchpoints from JS (HARNESS §7). For the readers of a field, use static
     xrefs and `analyze_struct_field_usage`, then hook the candidate functions.
   - Every call into the game (`frida_call`, `frida_eval`) is stated with its reason; writing game memory or
     changing game state needs the maintainer's go-ahead (HARNESS §2).
3. **Run unattended where possible:** the game window in the foreground (a lost Direct3D device stops the game),
   a throwaway match, game functions called on the main thread from inside a hook that runs there.
4. **Hand the maintainer only what needs his eyes, his ears or a second player:** one batched list in
   `docs/live-session-queue.md`, each entry with the shortest in-game path that makes every hook fire in one
   session.
5. **Label the result.** Map the live targets to the recovered vftables, name them, and tag the finding
   `[PROVEN]` with the date and source of the live evidence.

The Ghidra-debugger route (debugger MCP, Time Travel Debugging) is retired.

### Dispatch points that have produced false conclusions

- `TinCatProperties::cPropertyFactory::CreatePropertySet` (T `0x10013830`, factory vtable T `0x1004de84`, slot
  `+0x0c`) returns NULL for a message type whose template is not registered yet (`RegisterPropertySet`, slot
  `+0x04`): a message pushed before its template exists becomes a NULL dereference in the decoder.
- The `LobbyComm::System` state pump (`SetState` S `0x462540`, state at `+0x57c`, enum `LobbyManagerState`;
  called LobbyManager in older notes) and the connection classes, each bound as `/LobbyComm/<Class>_vftable`:
  village S `0x7db8d4`, UserComm S `0x7dcecc`, referee S `0x7dc1b0`, game server S `0x7deaf0`
  (`docs/types.md` §1).
- Observer callbacks entered through a secondary vftable (for example `LobbyComm::ServerList`'s
  `IGameServerObserver` table S `0x7daf8c`, at `+0x08`): an offset read inside such a method is relative to that
  base, not to the object, unless its `this` is typed as a face (§11).

---

## 11. Classes, faces and folded bodies

**The canonical layout.** One `GhidraClass` per C++ class, named for the RTTI class (`LobbyComm::X`); its struct at
the matching path (`/LobbyComm/X`), so the data type lines up with the class; every member function parented to
that one class namespace. The decompiler then shows `void __thiscall LobbyComm::X::Method(X *this, ...)`, and
sibling calls resolve by name. Ghidra types `this` from the namespace, so a namespace whose name differs from the
struct path does not type `this`. A class without RTTI gets a class namespace that mirrors its struct path:
`/ai/<sub>/<Name>` → `ai::<sub>::<Name>`, a root struct `/X` → class `X` (`docs/types.md` §5.2).

**Function tags.**

| Tag | Meaning |
|---|---|
| `AI` | touched by the mapping writer |
| `LIBRARY:<name>` | recognised library code (MSVC runtime, STL, Lua, ...) |
| `NETMSG`, `NETMSG_HANDLER`, `STATE_MACHINE` | parses or builds a network message; handles an inbound one; a state machine |
| `FACE_THIS` | entered through a secondary vftable only; `this` is an offset pointer into the class |
| `CUSTOM_THIS` | `this` has custom storage: a face (together with `FACE_THIS`) or a `this` that is not a struct pointer |
| `ICF_SHARED` | one body the linker folded for unrelated classes; it has no owning class |
| `VALUE_THIS` | a method of a class that holds one primitive; the object is typed as that primitive |

**Faces.** A method that is a slot of a secondary vtable receives `ECX = object + N` (for example the
`IGameServerObserver` callbacks of `LobbyComm::ServerList`, `N = 8`). Type its `this` as an offset pointer into the
class, `Class * __((offset(N))) this`, and tag it `FACE_THIS`; the decompiler then shows the class's own field
names at their real offsets (`ADJ(this)->field`). Do not build a mirror struct of the class shifted by `N`, and do
not type such a `this` as the plain class: every field measured through it would land `N` bytes too low.

**Custom storage is a last resort.** Type `this` through the class namespace. Custom variable storage freezes the
parameter locations and is used only for faces and for a `this` that is not a struct pointer, tagged
`CUSTOM_THIS`.

**Folded bodies.** When a body's users are unrelated classes, the linker folded identical code: tag it
`ICF_SHARED`, keep a shape name in Global (`Generic_GetDword_80`), and write in the plate, as fact, what the body
does and what it means for each user. It needs no `[TODO] owning class`: the question is answered.

### Class hygiene — one C++ class, one class node

`set_function_this_type` types `this`, but if the struct's name does not match the RTTI class it creates a bare
Global `GhidraClass` twin instead of using `Ns::Class`. Together with `__thiscall` methods that were typed but never
moved into the class, that gives two class nodes for one C++ class and members loose in Global, so calls render
double-scoped or unscoped and hide which methods belong to the class. Fix it whenever you finish typing a class.

**Rules (read before running the script):**

1. **RTTI gives the canonical name.** Confirm it through the type-descriptor string: search memory for `.?AVX@Ns@@`
   (for example `.?AVUserCommConnection@LobbyComm@@` → `LobbyComm::UserCommConnection`). Use that exact namespace.
2. **No RTTI descriptor:** the class namespace mirrors the struct path (`ai::<sub>::<Name>` for
   `/ai/<sub>/<Name>`). Never invent a C++ namespace from a guess; a base class shared by several `Ns::*` classes
   belongs in `Ns` only on structural evidence, marked `inferred`.
3. **The same simple name is not a duplicate.** `NMap::AStar` and `NNavy::AStar`, the 16 `*::System` classes,
   `Logger` (`.?AVLogger@@`, the engine logger) and `LobbyComm::Logger` are distinct C++ classes with different
   vftables. Only a bare-Global twin of a namespaced class, or loose Global `__thiscall` members, is the artifact to
   fix. Compare vftable addresses before merging anything that shares a name.
4. **`this` types survive the move**: they live on the function's parameters, not on its namespace. The pass is
   reversible (the previous version is on the server). Verify anyway by decompiling one method afterwards.
5. **Second-order mangle:** loose members often already carry `X::` or `X_` in their simple name; after the move
   that becomes `Ns::X::X::Method`. Strip the redundant prefix (the script does this).

**The template** (run through `run_script_inline`). Set `CLASS`, `PARENT` and `TARGET_CAT` at the top. If the
`PARENT::CLASS` class already exists (RTTI created it) it is reused; otherwise it is created, so rule 2 must hold
first. Members are collected by the full path of their `this` struct, never by its simple name (rule 3). `PARENT`
must be a namespace directly under Global; for a class under `ai::<sub>`, use the writer's `set_class` op and
namespace moves instead (`mapping/AGENT_GUIDE.md` §11).

```java
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;

String CLASS="UserCommConnection", PARENT="LobbyComm", TARGET_CAT="/LobbyComm";
boolean MOVE_ROOT_STRUCT=false;   // true only if a root /CLASS struct is this class's own layout (its +0 is this
                                  // class's vftable) and TARGET_CAT/CLASS does not exist yet
String STRUCT_PATH=TARGET_CAT+"/"+CLASS;
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

if (MOVE_ROOT_STRUCT && dtm.getDataType(STRUCT_PATH)==null) {               // align struct category
  DataType s0=dtm.getDataType("/"+CLASS);
  if (s0!=null) s0.setCategoryPath(new CategoryPath(TARGET_CAT));
}

java.util.LinkedHashSet<Function> mem=new java.util.LinkedHashSet<>();        // collect members
for (Function f: fm.getFunctions(true)) {
  if (!"__thiscall".equals(f.getCallingConventionName()) || f.getParameterCount()==0) continue;
  DataType p0=f.getParameter(0).getDataType();
  if (p0 instanceof Pointer) { DataType b=((Pointer)p0).getDataType();
    if (b!=null && b.getPathName().equals(STRUCT_PATH)) mem.add(f); }
}
if (dup!=null){ SymbolIterator it=st.getSymbols(dup); while(it.hasNext()){
  Symbol s=it.next(); if(s.getSymbolType()==SymbolType.FUNCTION){Function f=fm.getFunctionAt(s.getAddress()); if(f!=null) mem.add(f);} } }

for (Function f: mem) if (f.getParentNamespace()!=cls) f.getSymbol().setNamespace(cls);  // setNamespace(Namespace): ONE argument

String[] pref={CLASS+"::", CLASS+"_"};                // strip redundant prefixes
SymbolIterator it=st.getSymbols(cls);
while (it.hasNext()){ Symbol s=it.next(); if(s.getSymbolType()!=SymbolType.FUNCTION) continue;
  Function f=fm.getFunctionAt(s.getAddress()); String n=f.getName(),nn=n;
  for(String p:pref) if(n.startsWith(p)){nn=n.substring(p.length());break;}
  if(!nn.equals(n)&&nn.length()>0) f.setName(nn, SourceType.USER_DEFINED); }

if (dup!=null && !st.getSymbols(dup).hasNext()) dup.getSymbol().delete();     // drop the empty twin
```

Then verify: decompile a member, confirm `Ns::Class::Method(Class *this, …)` and that the struct fields and virtual
calls still resolve. Check in with a comment that says whether the namespace is RTTI-proven or inferred. API notes:
`Symbol.setNamespace` takes the namespace only (no `SourceType` overload); `FlatProgramAPI.find(String)` is the
single-argument string search (not `find(null, str)`).
