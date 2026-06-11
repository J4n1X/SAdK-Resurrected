// Smoke test: confirm the headless decompiler works against the current program.
//@category SADK
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;

public class HeadlessSmoke extends GhidraScript {
    @Override
    public void run() throws Exception {
        int fcount = currentProgram.getFunctionManager().getFunctionCount();
        println("SMOKE: program=" + currentProgram.getName() + " functions=" + fcount);

        Function f = getFirstFunction();
        if (f == null) { println("SMOKE: no functions"); return; }

        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        DecompileResults res = ifc.decompileFunction(f, 60, monitor);
        if (res.decompileCompleted()) {
            String c = res.getDecompiledFunction().getC();
            println("SMOKE: decompiled " + f.getName() + " -> " + c.length() + " chars OK");
        } else {
            println("SMOKE: decompile FAILED: " + res.getErrorMessage());
        }
        ifc.dispose();
    }
}
