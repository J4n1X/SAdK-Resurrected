// GUI replay for a headless-session fix: the 2026-07-28 village/avatar survey's this-typing step
// (see ApplyVillageServerConnectionThisTypes.java) had actually been applied via raw
// set_function_this_type calls in an even earlier headless session, before that script existed --
// and that raw path hit the exact duplicate-bare-Global-class trap decomp/RE_PRACTICES.md warns
// about: it created a synthetic Global::VillageServerConnection class (distinct from the real
// RTTI-proven LobbyComm::VillageServerConnection) and put the 8 avatar/shop/trade handlers there.
// Tell: HandleMessage's dispatcher called them as "::VillageServerConnection::HandleX(...)" --
// the leading "::" is the decompiler disambiguating from the *different*, more-nested class
// already in lexical scope -- instead of the unqualified sibling-call form every other handler in
// that same switch uses.
//
// This script (a) moves those 8 functions into the real class and deletes the empty duplicate,
// matching the RE_PRACTICES "Class hygiene" procedure, and (b) fixes an unrelated, independently
// discovered issue in the same vtable: slot +0x40 was still named/typed as the pre-2026-07-25-
// correction "LobbyManager_SendWorldLoginReq_2002" (stale -- see decomp/RENAME_LIST.md's
// 2026-07-25 correction entry) even though the docs already recorded the real name
// (SendLeaveVillageRequest_2002); this replays that rename, drops its redundant/phantom second
// parameter, restores the correct __thiscall convention, and re-points the vtable struct field at
// a freshly-built signature. Finally it retypes the 8 handlers' message parameter from a bare
// "int *" to "NetMsgStream *", matching every sibling handler in the same dispatcher.
//
// Run from Ghidra's Script Manager against your checked-out sadk_noav.exe, then File > Check In --
// no headless merge restriction applies there. Idempotent -- safe to re-run.
//@category SADK
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.BooleanDataType;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.data.ParameterDefinition;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.Structure;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.GhidraClass;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolTable;

public class FixVillageServerConnectionDuplicateClass extends GhidraScript {

    private static final String[] AVATAR_SHOP_TRADE_HANDLERS = {
        "0x0046c940", // HandleAvatarLevelExpUpdate
        "0x0046c9c0", // HandleAvatarStatsUpdate
        "0x0046e660", // HandleAvatarActiveItemsUpdate
        "0x0046e6f0", // HandleAvatarInventoryUpdate
        "0x0046e780", // HandleAvatarItemsFullSync
        "0x004706b0", // HandleShopInventoryData
        "0x0046d920", // HandleTradeRequest
        "0x0046cd10", // HandleTradeOffer
    };

    private static final String[] HANDLER_NAMES = {
        "HandleAvatarLevelExpUpdate", "HandleAvatarStatsUpdate", "HandleAvatarActiveItemsUpdate",
        "HandleAvatarInventoryUpdate", "HandleAvatarItemsFullSync", "HandleShopInventoryData",
        "HandleTradeRequest", "HandleTradeOffer",
    };

    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();
        FunctionManager fm = currentProgram.getFunctionManager();

        // --- Step 1: fix the duplicate-class trap ---
        GhidraClass real = null, dup = null;
        for (Symbol s : st.getSymbols("VillageServerConnection")) {
            if (s.getObject() instanceof GhidraClass) {
                Namespace parent = s.getParentNamespace();
                if (parent != null && "LobbyComm".equals(parent.getName())) real = (GhidraClass) s.getObject();
                else if (parent != null && parent.isGlobal()) dup = (GhidraClass) s.getObject();
            }
        }
        if (real == null) {
            println("ABORT: LobbyComm::VillageServerConnection not found -- expected it to already exist.");
            return;
        }
        println("real class = " + real.getSymbol().getName(true));
        if (dup == null) {
            println("No Global::VillageServerConnection duplicate found -- this-typing already correct, skipping step 1.");
        } else {
            println("dup class = " + dup.getSymbol().getName(true) + " -- moving its members into the real class");
            java.util.List<Function> members = new java.util.ArrayList<>();
            SymbolIterator it = st.getSymbols(dup);
            while (it.hasNext()) {
                Symbol m = it.next();
                if (m.getSymbolType() == ghidra.program.model.symbol.SymbolType.FUNCTION) {
                    Function f = fm.getFunctionAt(m.getAddress());
                    if (f != null) members.add(f);
                }
            }
            for (Function f : members) {
                println("  moving " + f.getName() + " @ " + f.getEntryPoint());
                f.getSymbol().setNamespace(real);
                if (!"__thiscall".equals(f.getCallingConventionName())) f.setCallingConvention("__thiscall");
            }
            if (!st.getSymbols(dup).hasNext()) {
                dup.getSymbol().delete();
                println("Deleted empty duplicate class 'VillageServerConnection' (Global).");
            } else {
                println("dup still has members after move -- NOT deleting, investigate manually.");
            }
        }

        // --- Step 2: fix the stale SendWorldLoginReq_2002 vtable slot ---
        Address slotAddr = toAddr("0x0046bde0");
        Function sendLeave = fm.getFunctionAt(slotAddr);
        if (sendLeave == null) {
            println("SKIP step 2: no function at 0x0046bde0");
        } else if ("SendLeaveVillageRequest_2002".equals(sendLeave.getName())
                && sendLeave.getParentNamespace() == real) {
            println("SKIP step 2: already SendLeaveVillageRequest_2002 in the real class");
        } else {
            println("Fixing 0x0046bde0: " + sendLeave.getName() + " -> LobbyComm::VillageServerConnection::SendLeaveVillageRequest_2002");
            sendLeave.getSymbol().setNamespace(real);
            sendLeave.setName("SendLeaveVillageRequest_2002", SourceType.USER_DEFINED);
            sendLeave.setCallingConvention("__thiscall");
            // Drop the redundant/phantom second "conn" parameter left over from the pre-this-typed
            // __fastcall signature -- it is unused in the body (VillageServerConnection *this covers it).
            sendLeave.replaceParameters(Function.FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS,
                true, SourceType.USER_DEFINED);

            currentProgram.getListing().setComment(slotAddr, CodeUnit.PLATE_COMMENT,
                "Village vtable slot +0x40. LEAVE-village request (corrected 2026-07-25; was misnamed "
                + "SendWorldLoginReq_2002 and marked \"DORMANT\" -- both wrong). Guards on transport "
                + "state==8 (authorized); builds LobbyMessage(cat=2, msgId=0x7d2=2002){code=0xAFFEDEAD}, "
                + "calls LobbyManager::SetState(LeavingVillage=10), then sends via "
                + "this->pVftable->Connect (vtbl+0xc, the transport send path -- NOT a connect call "
                + "despite the field's inherited name). Caller: CLobbyClient::LeaveVillage (tail-jumps "
                + "here) both from the \"!LEAVE_VILLAGE_QUESTION\" confirm popup and from the "
                + "match-start SetupGameDialog update. After this sends, the client sits in "
                + "LeavingVillage(10) until the transport is driven to Logout -> OnLoggedOut -> "
                + "HandleLoggedOut -> SetState(VillageLeft=11). See docs/SOURCEMAP.md section 2b and "
                + "decomp/RENAME_LIST.md (2026-07-25 correction) for the full derivation.");

            // Re-point the VillageServerConnection_vftable's slot +0x40 field at a fresh signature
            // matching the corrected name (the old one is now orphaned and can be deleted).
            DataTypeManager dtm = currentProgram.getDataTypeManager();
            FunctionDefinitionDataType sig = new FunctionDefinitionDataType("VillageServerConnection::SendLeaveVillageRequest_2002");
            sig.setReturnType(BooleanDataType.dataType);
            sig.setArguments(new ParameterDefinition[]{});
            DataType sigResolved = dtm.addDataType(sig, DataTypeConflictHandler.REPLACE_HANDLER);

            DataType vft = dtm.getDataType("/LobbyComm/VillageServerConnection_vftable");
            if (vft instanceof Structure) {
                Structure s = (Structure) vft;
                s.replace(16 /* offset 0x40 / 4 = field index 16 */, new PointerDataType(sigResolved), 4,
                    "pSendLeaveVillageRequest_2002", null);
                println("Updated VillageServerConnection_vftable slot +0x40 field type.");
            } else {
                println("WARNING: could not find /LobbyComm/VillageServerConnection_vftable to retype slot +0x40 -- do it manually via modify_struct_field_type.");
            }

            DataType stale = dtm.getDataType("/LobbyManager_SendWorldLoginReq_2002");
            if (stale != null) {
                try {
                    dtm.remove(stale, monitor);
                    println("Removed orphaned stale data type LobbyManager_SendWorldLoginReq_2002.");
                } catch (Exception e) {
                    println("Could not remove stale type (non-fatal, leave it for manual cleanup): " + e);
                }
            }
        }

        // --- Step 3: retype the 8 avatar/shop/trade handlers' message param to NetMsgStream* ---
        DataType netMsgStreamPtr = currentProgram.getDataTypeManager().getDataType("/NetMsgStream");
        for (int i = 0; i < AVATAR_SHOP_TRADE_HANDLERS.length; i++) {
            Address a = toAddr(AVATAR_SHOP_TRADE_HANDLERS[i]);
            Function f = fm.getFunctionAt(a);
            if (f == null) { println("SKIP " + AVATAR_SHOP_TRADE_HANDLERS[i] + ": no function"); continue; }
            if (f.getParameterCount() == 1 && "NetMsgStream *".equals(f.getParameter(0).getDataType().getName() + " *")) {
                // already NetMsgStream*, nothing to do (defensive; getName() comparison above is
                // deliberately loose since Ghidra doesn't expose a cheap "is this exact pointer type" check here)
            }
            f.updateFunction("__thiscall", null,
                java.util.Arrays.asList(new ghidra.program.model.listing.ParameterImpl(
                    "msg", new PointerDataType(netMsgStreamPtr), currentProgram)),
                Function.FunctionUpdateType.DYNAMIC_STORAGE_FORMAL_PARAMS,
                true, SourceType.USER_DEFINED);
            println("OK retyped " + HANDLER_NAMES[i] + "(msg: NetMsgStream *)");
        }

        println("FixVillageServerConnectionDuplicateClass: done. Verify a decompile (e.g. "
            + "HandleAvatarStatsUpdate) shows 'LobbyComm::VillageServerConnection::HandleAvatarStatsUpdate"
            + "(VillageServerConnection *this, NetMsgStream *msg)', then File > Check In.");
    }
}
