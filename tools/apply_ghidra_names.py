#!/usr/bin/env python3
"""Deterministically apply a Ghidra naming plan (JSON) to the active program via run_script_inline.

Plan JSON shape (the schema the naming workflow returns):
    {"functions": [
        {"address":"0x004793f0", "new_name":"RefereeServerConnection_Login",
         "calling_convention":"__thiscall", "return_type":"void",
         "params":[{"name":"this","type":"void *"},{"name":"netTransport","type":"void *"}],
         "locals":[{"old":"local_30","new":"msgSize","type":"int"}],  // "type" is optional; omit to rename-only
         "plate_comment":"Opens the referee transport channel."},
        ...]}

Per function (each in its own transaction, so one failure never poisons the batch):
  1. rename            -> Function.setName
  2. signature+params  -> Function.updateFunction(conv, ret, params, DYNAMIC_STORAGE_FORMAL_PARAMS, ...)
                          (proven recipe: clean thiscall, this->ECX, no duplicate auto-this)
  3. plate comment     -> Function.setComment
  4. decompiler locals -> HighFunctionDBUtil.updateDBVariable (only names that still exist)

Talks ONLY to the local Ghidra plugin (:8089) — RE tooling, never the live game.

Usage:  python tools/apply_ghidra_names.py docs/referee_naming_plan.json [--dry-run]
"""
import json
import sys

from ghidra_inline import run  # local helper (same dir)


def jstr(s: str) -> str:
    """Escape a Python str into a Java double-quoted string literal."""
    if s is None:
        s = ""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def build_java(fn: dict, prog: str = "currentProgram") -> str:
    addr = fn["address"]
    new_name = fn["new_name"]
    conv = fn.get("calling_convention") or "unknown"
    ret = fn.get("return_type") or "undefined4"
    params = fn.get("params") or []
    locals_ = fn.get("locals") or []
    comment = fn.get("plate_comment") or ""

    j = []
    j.append("{")
    j.append("ghidra.program.model.data.DataTypeManager dtm = currentProgram.getDataTypeManager();")
    j.append("ghidra.util.data.DataTypeParser dtp = new ghidra.util.data.DataTypeParser(dtm, dtm, null, "
             "ghidra.util.data.DataTypeParser.AllowedDataTypes.ALL);")
    j.append(f"ghidra.program.model.address.Address ad = currentProgram.getAddressFactory().getAddress({jstr(addr)});")
    j.append("ghidra.program.model.listing.Function f = currentProgram.getListing().getFunctionAt(ad);")
    j.append("StringBuilder st = new StringBuilder();")
    j.append(f"if (f == null) {{ println({jstr(addr)} + \" FAIL no-function\"); }}")
    j.append("else {")
    # 1-3: rename + signature + comment in one transaction
    j.append("  int tx = currentProgram.startTransaction(\"name\");")
    j.append("  boolean ok = false;")
    j.append("  try {")
    j.append(f"    f.setName({jstr(new_name)}, ghidra.program.model.symbol.SourceType.USER_DEFINED);")
    j.append("    java.util.List<ghidra.program.model.listing.Variable> ps = "
             "new java.util.ArrayList<ghidra.program.model.listing.Variable>();")
    for p in params:
        pname, ptype = p["name"], p["type"]
        j.append(f"    ps.add(new ghidra.program.model.listing.ParameterImpl({jstr(pname)}, "
                 f"dtp.parse({jstr(ptype)}), currentProgram));")
    j.append(f"    ghidra.program.model.data.DataType rt = dtp.parse({jstr(ret)});")
    j.append("    f.updateFunction(" + jstr(conv) + ", "
             "new ghidra.program.model.listing.ReturnParameterImpl(rt, currentProgram), ps, "
             "ghidra.program.model.listing.Function.FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS, "
             "true, ghidra.program.model.symbol.SourceType.USER_DEFINED);")
    if comment:
        j.append(f"    f.setComment({jstr(comment)});")
    j.append("    ok = true; st.append(\"sig-ok\");")
    j.append("  } catch (Exception e) { st.append(\"SIG-EXC \" + e); }")
    j.append("  finally { currentProgram.endTransaction(tx, ok); }")
    # 4: locals via decompiler (separate transaction)
    if locals_:
        j.append("  try {")
        j.append("    ghidra.app.decompiler.DecompInterface di = new ghidra.app.decompiler.DecompInterface();")
        j.append("    di.openProgram(currentProgram);")
        j.append("    ghidra.app.decompiler.DecompileResults dr = di.decompileFunction(f, 60, monitor);")
        j.append("    ghidra.program.model.pcode.HighFunction hf = (dr == null) ? null : dr.getHighFunction();")
        j.append("    if (hf != null) {")
        # name map
        j.append("      java.util.HashMap<String,String> m_names = new java.util.HashMap<String,String>();")
        # type map (populated per-entry only when a type is provided; parse failures are swallowed)
        j.append("      java.util.HashMap<String,ghidra.program.model.data.DataType> m_types = "
                 "new java.util.HashMap<String,ghidra.program.model.data.DataType>();")
        for lv in locals_:
            old = lv["old"]
            new = lv["new"]
            ltype = lv.get("type") or ""
            j.append(f"      m_names.put({jstr(old)}, {jstr(new)});")
            if ltype:
                j.append(f"      try {{ m_types.put({jstr(old)}, dtp.parse({jstr(ltype)})); }}"
                         f" catch (Exception __te) {{}}")
        j.append("      int tx2 = currentProgram.startTransaction(\"locals\");")
        j.append("      boolean ok2 = false; int n = 0;")
        j.append("      try {")
        j.append("        java.util.Iterator<ghidra.program.model.pcode.HighSymbol> it = "
                 "hf.getLocalSymbolMap().getSymbols();")
        j.append("        while (it.hasNext()) {")
        j.append("          ghidra.program.model.pcode.HighSymbol s = it.next();")
        j.append("          if (m_names.containsKey(s.getName())) {")
        j.append("            try {")
        j.append("              ghidra.program.model.data.DataType ltype = m_types.get(s.getName());")
        j.append("              ghidra.program.model.pcode.HighFunctionDBUtil.updateDBVariable(s, "
                 "m_names.get(s.getName()), ltype, ghidra.program.model.symbol.SourceType.USER_DEFINED); n++; }")
        j.append("            catch (Exception e3) { st.append(\" skip:\" + s.getName()); }")
        j.append("          }")
        j.append("        }")
        j.append("        ok2 = true; st.append(\" locals=\" + n + \"/\" + m.size());")
        j.append("      } catch (Exception e) { st.append(\" LOC-EXC \" + e); }")
        j.append("      finally { currentProgram.endTransaction(tx2, ok2); }")
        j.append("    } else { st.append(\" no-highfn\"); }")
        j.append("    di.dispose();")
        j.append("  } catch (Exception e) { st.append(\" DEC-EXC \" + e); }")
    j.append(f"  println({jstr(addr)} + \"  \" + f.getName() + \" :: \" "
             "+ f.getSignature().getPrototypeString() + \"  | \" + st);")
    j.append("}")
    j.append("}")
    # `prog` is the Program handle the block operates on (default = the active program). For cross-program
    # work pass prog="tc"; the only literal "currentProgram" tokens are API calls (never user data here).
    return "\n".join(j).replace("currentProgram", prog)


def _emit(out):
    """Print the per-function result lines from a run_script_inline response."""
    body = out.split("--- SCRIPT OUTPUT ---")[-1].split("=== SCRIPT COMPLETED")[0] if "SCRIPT OUTPUT" in out else out
    for ln in body.splitlines():
        s = ln.strip()
        if s and ("::" in s or "EXC" in s or "FAIL" in s or "NO FUNCTION" in s
                  or s.startswith(("SAVED", "no-change", "no-domainfile"))):
            print(s)


def _xprog_wrap(blocks_src: str, prog_path: str) -> str:
    """Wrap per-function blocks (built with prog='tc') so they run against a NON-active program opened by
    path, then SAVE it (cross-program edits aren't durable otherwise) and release. df.save takes only a
    TaskMonitor. Uses state.getProject() (the inline-script field; bare getProject() is NOT in scope)."""
    return (
        f'ghidra.framework.model.DomainFile df = state.getProject().getProjectData().getFile({jstr(prog_path)});\n'
        'if (df == null) { println("FAIL no-domainfile " + ' + jstr(prog_path) + '); }\n'
        'else {\n'
        '  ghidra.program.model.listing.Program tc = (ghidra.program.model.listing.Program) '
        'df.getDomainObject(this, true, false, monitor);\n'
        '  try {\n'
        f'{blocks_src}\n'
        '    if (tc.isChanged()) { df.save(monitor); println("SAVED " + tc.getName()); }\n'
        '    else { println("no-change"); }\n'
        '  } finally { tc.release(this); }\n'
        '}\n'
    )


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    # Apply all functions in ONE script invocation per chunk: a single EDT execution commits every
    # transaction before responding, eliminating the cross-POST race that silently dropped most commits.
    chunk = 999
    prog_path = None  # e.g. "/tincat3.dll" to edit a NON-active program (cross-program, saved at the end)
    for a in sys.argv:
        if a.startswith("--chunk="):
            chunk = int(a.split("=", 1)[1])
        if a.startswith("--program="):
            prog_path = a.split("=", 1)[1]
    plan = json.load(open(args[0], encoding="utf-8"))
    fns = plan["functions"] if isinstance(plan, dict) else plan
    where = f" in {prog_path} (cross-program)" if prog_path else ""
    print(f"Applying {len(fns)} function(s){where} in chunk(s) of {chunk}{' (DRY RUN)' if dry else ''}\n")
    prog_var = "tc" if prog_path else "currentProgram"
    for i in range(0, len(fns), chunk):
        group = fns[i:i + chunk]
        blocks = "\n".join(build_java(fn, prog_var) for fn in group)  # each fn is its own brace-scoped block
        script = _xprog_wrap(blocks, prog_path) if prog_path else blocks
        if dry:
            print(script)
            continue
        _emit(run(script, timeout=240))


if __name__ == "__main__":
    main()
