// This-types the 8 avatar/shop/trade dispatch handlers named by ApplyVillageAvatarRenames.java
// (run that one first, or in either order before checking in -- this script only touches
// namespace/calling-convention, not names).
//
// Follows the documented "Class hygiene" procedure in decomp/RE_PRACTICES.md: locates the
// EXISTING RTTI-proven LobbyComm::VillageServerConnection GhidraClass and moves each function's
// symbol into it -- does NOT create a new class. Creating one instead of reusing the real one is
// the exact duplicate-bare-Global-class trap that procedure exists to avoid (it happened once
// already on this project, 2026-06-11, and had to be cleaned up). Ghidra's auto-storage "this"
// parameter then retypes itself to VillageServerConnection* automatically once the function is
// in the right namespace -- no manual parameter edit needed.
//
// Run from Ghidra's Script Manager against your checked-out sadk_noav.exe, verify one decompile
// shows "VillageServerConnection *this", then File > Check In. Idempotent -- safe to re-run.
//@category SADK
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.GhidraClass;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

public class ApplyVillageServerConnectionThisTypes extends GhidraScript {

    private static final String[] TARGETS = {
        "0x0046c940", // HandleAvatarLevelExpUpdate
        "0x0046c9c0", // HandleAvatarStatsUpdate
        "0x0046e660", // HandleAvatarActiveItemsUpdate
        "0x0046e6f0", // HandleAvatarInventoryUpdate
        "0x0046e780", // HandleAvatarItemsFullSync
        "0x004706b0", // HandleShopInventoryData
        "0x0046d920", // HandleTradeRequest
        "0x0046cd10", // HandleTradeOffer
    };

    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();
        FunctionManager fm = currentProgram.getFunctionManager();

        GhidraClass cls = null;
        for (Symbol s : st.getSymbols("VillageServerConnection")) {
            if (s.getObject() instanceof GhidraClass) {
                Namespace parent = s.getParentNamespace();
                if (parent != null && "LobbyComm".equals(parent.getName())) {
                    cls = (GhidraClass) s.getObject();
                    break;
                }
            }
        }
        if (cls == null) {
            println("ABORT: LobbyComm::VillageServerConnection class not found -- expected it to "
                + "already exist (it's the class HandleEntityCreate etc. already live in). Not "
                + "creating a new one, since that would be the duplicate bare-Global-class trap. "
                + "Check the namespace manually in the Symbol Tree before retrying.");
            return;
        }
        println("Using class: " + cls.getSymbol().getName(true));

        int moved = 0, skipped = 0, failed = 0;
        for (String addrStr : TARGETS) {
            try {
                Address addr = toAddr(addrStr);
                Function f = fm.getFunctionAt(addr);
                if (f == null) {
                    println("FAIL  " + addrStr + " : no function at this address");
                    failed++;
                    continue;
                }
                if (f.getParentNamespace().getID() == cls.getID()) {
                    println("SKIP  " + addrStr + " " + f.getName() + " already in the class");
                    skipped++;
                    continue;
                }
                f.getSymbol().setNamespace(cls);
                if (!"__thiscall".equals(f.getCallingConventionName())) {
                    f.setCallingConvention("__thiscall");
                }
                println("OK    " + addrStr + " -> " + cls.getSymbol().getName(true) + "::" + f.getName());
                moved++;
            } catch (Exception e) {
                println("FAIL  " + addrStr + " : " + e.getMessage());
                failed++;
            }
        }
        println("ApplyVillageServerConnectionThisTypes: moved=" + moved + " skipped=" + skipped
            + " failed=" + failed);
        println("Verify: decompile one (e.g. HandleAvatarStatsUpdate) and confirm the signature "
            + "reads '(VillageServerConnection *this, ...)'. Then File > Check In.");
    }
}
