#!/usr/bin/env python3
"""Enumerate every USER_DEFINED function in the active Ghidra program via run_script_inline.
Prints:  0xADDRESS : FunctionName
One line per function, sorted by address.
"""
import sys
sys.path.insert(0, __import__('pathlib').Path(__file__).parent.__str__())
from ghidra_inline import run

CODE = r"""
java.util.TreeMap<Long,String> m = new java.util.TreeMap<Long,String>();
ghidra.program.model.listing.FunctionIterator fi = currentProgram.getListing().getFunctions(true);
while (fi.hasNext()) {
    ghidra.program.model.listing.Function f = fi.next();
    if (f.getSymbol().getSource() == ghidra.program.model.symbol.SourceType.USER_DEFINED) {
        m.put(f.getEntryPoint().getOffset(), f.getEntryPoint().toString() + " : " + f.getName());
    }
}
for (String line : m.values()) { println(line); }
"""

if __name__ == "__main__":
    out = run(CODE, timeout=120)
    # Strip preamble/epilogue from run_script_inline response
    body = out.split("--- SCRIPT OUTPUT ---")[-1].split("=== SCRIPT COMPLETED")[0] if "SCRIPT OUTPUT" in out else out
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and " : " in ln and ("00" in ln[:4]):
            print(ln)
