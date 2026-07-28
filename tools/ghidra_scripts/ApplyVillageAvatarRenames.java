// Batch-applies the 2026-07-28 village/avatar protocol survey renames + plate comments to
// sadk_noav.exe. Run this from Ghidra's Script Manager against your OWN checked-out copy of
// sadk_noav.exe (any GUI session), then check the file in normally -- no headless merge
// restriction applies to a GUI checkin.
//
// This is the GUI-side replay of work done in a headless MCP session whose own checkin got
// stuck ("file requires merge, which is not supported in headless mode"). Source of truth for
// every name/comment below: decomp/RENAME_LIST.md's "2026-07-28 -- village/avatar protocol
// survey" section and docs/SOURCEMAP.md section 5a. Idempotent -- safe to re-run.
//@category SADK
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class ApplyVillageAvatarRenames extends GhidraScript {

    private int renamed = 0;
    private int skipped = 0;
    private int failed = 0;
    private int commented = 0;

    @Override
    public void run() throws Exception {
        rename("0x0046c940", "HandleAvatarLevelExpUpdate");
        rename("0x0046c9c0", "HandleAvatarStatsUpdate");
        rename("0x0046e660", "HandleAvatarActiveItemsUpdate");
        rename("0x0046e6f0", "HandleAvatarInventoryUpdate");
        rename("0x0046e780", "HandleAvatarItemsFullSync");
        rename("0x004706b0", "HandleShopInventoryData");
        rename("0x0046d920", "HandleTradeRequest");
        rename("0x0046cd10", "HandleTradeOffer");
        rename("0x00482c20", "AvatarProxy_ReadDataBlocks");
        rename("0x0048f530", "LobbyMessage_FinishRead");
        rename("0x004824b0", "AvatarProxy_ReadLocationBlock");
        rename("0x004825f0", "AvatarProxy_ReadStyleBlock");
        rename("0x0048abe0", "AvatarProxy_ReadActiveItemsBlock");
        rename("0x0048ab40", "AvatarProxy_ReadItemSlot");
        rename("0x00481da0", "AvatarProxy_ReadStatsBlock");
        rename("0x00481d50", "AvatarProxy_ReadLevelExpBlock");
        rename("0x0048ac20", "AvatarProxy_ReadInventoryBlock");
        rename("0x00481d30", "AvatarProxy_ReadActiveItemsShim");
        rename("0x00481d40", "AvatarProxy_ReadInventoryShim");
        rename("0x00464300", "NotifyQueue_FireAndClear");
        rename("0x004780c0", "LobbyManager_RegisterAvatar");

        // NOTE: the corresponding VillageServerConnection this-typing for the 8 Handle* functions
        // above is a separate follow-up script -- see ApplyVillageServerConnectionThisTypes.java
        // in this same directory (run either before or after this one, either order is fine).

        comment("0x0046f510",
            "Village msg 0xD8. Gated on LobbyManagerState==VillageEntered. Looks up a compound key (via FUN_004712e0) in the container at VillageServerConnection+0x178; on a match fires NotifyQueue_FireAndClear(this+0x74) then erases the entry via FUN_00462b90. [HYPOTHESIS] Shape (lookup+notify+erase) fits a \"member left\" event for whatever social construct lives at +0x178 (party/group -- unconfirmed which). Siblings: 0xD9 (join, assigns a NComm net id), 0xDA (create-or-get, no notify).");
        comment("0x0046f380",
            "Village msg 0xD9. Gated on VillageEntered. Calls NComm_TinCatNetwork_GetLocalNetId, looks up the same +0x178 container as 0xD8/0xDA; on match assigns a NComm net id to the entry (FUN_00471640/FUN_00471650) and fires NotifyQueue_FireAndClear TWICE (this+0x68 then this+0x80, the second gated on a further per-entry vtbl[0xc] field-read succeeding). [HYPOTHESIS] Shape fits a \"member joined / accepted, network-addressable\" event.");
        comment("0x0046eb70",
            "Village msg 0xDA. NOT state-gated (unlike 0xD8/0xD9). Looks up the +0x178 container by compound key; if absent, CREATES a new entry (FUN_00471300) and inserts it (FUN_00686550) -- get-or-create semantics, no NotifyQueue fan-out. [HYPOTHESIS] Fits a \"request/invite\" event that seeds the entry 0xD9 later upgrades and 0xD8 later removes.");
        comment("0x0046f4d0",
            "Village msg 0xDB. Zero-payload: flushes the stream (LobbyMessage_FinishRead) then fires the observer set at this+0x8c via FUN_004760c0. No fields read at all. [TODO] exact event unknown; bare-notify shape (compare 0xDC at this+0x98).");
        comment("0x0046f4f0",
            "Village msg 0xDC. Zero-payload: flushes the stream then fires the observer set at this+0x98 via FUN_004760c0. Same shape as 0xDB (this+0x8c). [TODO] exact event unknown.");
        comment("0x0046d380",
            "Village msg 0x12F. Reads \"msgprt\" (16-bit) + \"rnid\" (8-bit), looks up the +0x178 container by compound key; on match, drills through a nested sub-object (found_entry+0x10) to fetch a handler pointer via two chained vtable calls and, if non-null, forwards the raw message to it (FUN_00489410). [TODO/HYPOTHESIS] Looks like a generic \"route this message to the entry's own sub-handler\" envelope (e.g. per-party-member private message?) rather than a message with its own fixed payload.");
        comment("0x00470990",
            "Village msg 0xE1B. Reads ShopID(32b) + Result(1-bit, via vtbl+0x28) then calls FUN_0045f620(this+0x134, shopId, result). Sibling of 0xE25 (same shape, this+0x140). [TODO] Which shop action (buy/sell/enter/exit) this acks vs 0xE25 is unconfirmed -- not renamed to avoid asserting a guess.");
        comment("0x00470a10",
            "Village msg 0xE25. Reads ShopID(32b) + Result(1-bit, via vtbl+0x28) then calls FUN_0045f620(this+0x140, shopId, result). Sibling of 0xE1B (same shape, this+0x134). [TODO] Which shop action this acks vs 0xE1B is unconfirmed.");

        println("ApplyVillageAvatarRenames: renamed=" + renamed + " skipped(already correct)=" + skipped
            + " failed=" + failed + " plate-comments=" + commented);
        println("Now: File > Check In... to publish this as a new repository version.");
    }

    private void rename(String addrStr, String newName) {
        try {
            Address addr = toAddr(addrStr);
            Function f = currentProgram.getFunctionManager().getFunctionAt(addr);
            if (f == null) {
                println("FAIL  " + addrStr + " -> " + newName + " : no function at this address");
                failed++;
                return;
            }
            if (f.getName().equals(newName)) {
                println("SKIP  " + addrStr + " already " + newName);
                skipped++;
                return;
            }
            String oldName = f.getName();
            f.setName(newName, SourceType.USER_DEFINED);
            println("OK    " + addrStr + " " + oldName + " -> " + newName);
            renamed++;
        } catch (Exception e) {
            println("FAIL  " + addrStr + " -> " + newName + " : " + e.getMessage());
            failed++;
        }
    }

    private void comment(String addrStr, String text) {
        try {
            Address addr = toAddr(addrStr);
            currentProgram.getListing().setComment(addr, CodeUnit.PLATE_COMMENT, text);
            println("OK    plate comment @ " + addrStr);
            commented++;
        } catch (Exception e) {
            println("FAIL  plate comment @ " + addrStr + " : " + e.getMessage());
            failed++;
        }
    }
}
