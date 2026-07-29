// Recovers LobbyComm::IAvatarDataBlock (RTTI-proven interface) and its 6 concrete
// Avatar*BlockEx subclasses -- AvatarCreationBlockEx, AvatarAppearanceBlockEx, AvatarStyleBlockEx,
// AvatarStatsBlockEx, AvatarActiveItemsBlockEx, AvatarInventoryBlockEx -- following the
// docs/SOURCEMAP.md "[TODO -- RTTI class hygiene]" note left by the 2026-07-28 avatar/shop/trade
// survey. This is a SEPARATE, parallel serialization family from the already-documented LobbyComm
// wire readers (AvatarProxy_ReadXBlock): it uses NComm::MemoryStream + an 8-slot vtable
// (Destructor, ReadFromBuffer, WriteToBuffer, Deserialize, Serialize, GetVariant, GetSize, Clear),
// most likely the avatar-cosmetics-sync payload carried inside an NComm PlayerInformation-style
// event during an actual match, as opposed to the village/lobby wire.
//
// Evidence for the 8-slot shape and per-class field counts/widths: decompiled every class's own
// Deserialize body (the one PER-CLASS override every subclass must supply) and read the Read()
// call boundaries directly -- field COUNT and WIDTH are therefore [PROVEN] (backed by the actual
// stream reads), but individual field NAMES are NOT -- they are left as generic fieldN /
// undefined4, explicitly marked [HYPOTHESIS] in the struct field comments, per RE_PRACTICES
// "never fabricate structure". AvatarProxy itself was investigated and found to inherit
// ActorProxy : IActor (a distinct, widely-shared actor interface referenced by 4+ other class
// hierarchies) rather than composing/inheriting this Block family -- deliberately NOT bound here;
// it needs its own dedicated pass so as not to half-reverse a shared interface.
//
// Run from Ghidra's Script Manager against your checked-out sadk_noav.exe, then File > Check In --
// no headless merge restriction applies there. Idempotent -- safe to re-run (DataTypeConflictHandler
// .REPLACE_HANDLER on every struct/signature; functions are looked up and reused, not recreated).
//@category SADK
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.data.ParameterDefinition;
import ghidra.program.model.data.ParameterDefinitionImpl;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.data.Structure;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.GhidraClass;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.app.script.GhidraScript;

public class ApplyAvatarDataBlockVtables extends GhidraScript {

    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();
        FunctionManager fm = currentProgram.getFunctionManager();
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        CategoryPath cat = new CategoryPath("/LobbyComm");
        if (dtm.getCategory(cat) == null) dtm.createCategory(cat);
        Namespace lobbyComm = st.getNamespace("LobbyComm", currentProgram.getGlobalNamespace());

        // ---------- 1. classes ----------
        String[] classNames = {"IAvatarDataBlock", "AvatarCreationBlockEx", "AvatarAppearanceBlockEx",
            "AvatarStyleBlockEx", "AvatarStatsBlockEx", "AvatarActiveItemsBlockEx", "AvatarInventoryBlockEx"};
        java.util.Map<String, GhidraClass> classMap = new java.util.HashMap<>();
        for (String cn : classNames) {
            GhidraClass found = null;
            for (Symbol s : st.getSymbols(cn)) {
                if (s.getObject() instanceof GhidraClass && s.getParentNamespace() == lobbyComm) {
                    found = (GhidraClass) s.getObject();
                    break;
                }
            }
            if (found == null) found = st.createClass(lobbyComm, cn, SourceType.USER_DEFINED);
            classMap.put(cn, found);
        }
        println("Classes ready: " + classMap.keySet());

        // ---------- 2. object structs ----------
        DataType u4 = dtm.getDataType("/undefined4");
        DataType u1 = dtm.getDataType("/undefined1");
        PointerDataType genericPtr = new PointerDataType();

        StructureDataType base = new StructureDataType(cat, "IAvatarDataBlock", 0);
        base.add(genericPtr, 4, "pVftable", "vtable pointer");
        base.add(u4, 4, "nVariant", "discriminator/variant field read first by Deserialize; gates which extended fields follow. [HYPOTHESIS] exact semantic meaning per subclass not confirmed.");
        DataType baseResolved = dtm.addDataType(base, DataTypeConflictHandler.REPLACE_HANDLER);

        String[] simpleNames = {"AvatarCreationBlockEx", "AvatarAppearanceBlockEx", "AvatarStyleBlockEx"};
        int[] fieldCounts = {10, 2, 8};
        for (int i = 0; i < simpleNames.length; i++) {
            StructureDataType sdt = new StructureDataType(cat, simpleNames[i], 0);
            sdt.add(baseResolved, 8, "base", "embedded IAvatarDataBlock (vftable + nVariant)");
            for (int f = 0; f < fieldCounts[i]; f++) {
                sdt.add(u4, 4, "field" + (f + 1), "[HYPOTHESIS] 4-byte field read/written by Deserialize/Serialize; width proven, semantic name not yet confirmed.");
            }
            dtm.addDataType(sdt, DataTypeConflictHandler.REPLACE_HANDLER);
        }

        StructureDataType stats = new StructureDataType(cat, "AvatarStatsBlockEx", 0);
        stats.add(baseResolved, 8, "base", "embedded IAvatarDataBlock (vftable + nVariant)");
        stats.add(u4, 4, "field1", "[HYPOTHESIS] always read");
        stats.add(u4, 4, "field2", "[HYPOTHESIS] always read");
        stats.add(u4, 4, "field3", "[HYPOTHESIS] always read");
        stats.add(u4, 4, "field4_tier1", "[HYPOTHESIS] read only if GetVariant()!=0");
        stats.add(u4, 4, "field5_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        stats.add(u4, 4, "field6_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        stats.add(u4, 4, "field7_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        stats.add(u4, 4, "field8_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        stats.add(u1, 1, "byte1_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        stats.add(u1, 1, "byte2_tier2", "[HYPOTHESIS] read only if GetVariant()>1");
        dtm.addDataType(stats, DataTypeConflictHandler.REPLACE_HANDLER);

        ArrayDataType slot12 = new ArrayDataType(u1, 12, 1);
        StructureDataType activeItems = new StructureDataType(cat, "AvatarActiveItemsBlockEx", 0);
        activeItems.add(baseResolved, 8, "base", "embedded IAvatarDataBlock (vftable + nVariant)");
        activeItems.add(slot12, 12, "slot1", "[HYPOTHESIS] 12-byte item slot; internal layout not resolved (one layer deep per RE_PRACTICES)");
        activeItems.add(slot12, 12, "slot2", "[HYPOTHESIS] 12-byte item slot");
        activeItems.add(slot12, 12, "slot3", "[HYPOTHESIS] 12-byte item slot");
        activeItems.add(slot12, 12, "slot4", "[HYPOTHESIS] 12-byte item slot");
        dtm.addDataType(activeItems, DataTypeConflictHandler.REPLACE_HANDLER);

        ArrayDataType slots20 = new ArrayDataType(slot12, 20, 12);
        StructureDataType inv = new StructureDataType(cat, "AvatarInventoryBlockEx", 0);
        inv.add(baseResolved, 8, "base", "embedded IAvatarDataBlock (vftable + nVariant)");
        inv.add(u4, 4, "nCount", "slot count; clamped to max 20 in Deserialize");
        inv.add(slots20, 240, "slots", "[HYPOTHESIS] up to 20x 12-byte item slots (fixed-capacity array); only nCount of them are meaningful");
        dtm.addDataType(inv, DataTypeConflictHandler.REPLACE_HANDLER);
        println("Object structs ready.");

        // ---------- 3. vftable struct ----------
        DataType voidT = dtm.getDataType("/void");
        PointerDataType voidPtr = new PointerDataType(voidT);

        FunctionDefinitionDataType dtor = new FunctionDefinitionDataType("IAvatarDataBlock::Destructor");
        dtor.setReturnType(voidPtr);
        dtor.setArguments(new ParameterDefinition[]{ new ParameterDefinitionImpl("freeMemory", u1, "nonzero = also free(this)") });

        FunctionDefinitionDataType readFromBuffer = new FunctionDefinitionDataType("IAvatarDataBlock::ReadFromBuffer");
        readFromBuffer.setReturnType(u1);
        readFromBuffer.setArguments(new ParameterDefinition[]{
            new ParameterDefinitionImpl("buffer", voidPtr, null),
            new ParameterDefinitionImpl("length", u4, null)
        });

        FunctionDefinitionDataType writeToBuffer = new FunctionDefinitionDataType("IAvatarDataBlock::WriteToBuffer");
        writeToBuffer.setReturnType(u1);
        writeToBuffer.setArguments(new ParameterDefinition[]{
            new ParameterDefinitionImpl("buffer", voidPtr, null),
            new ParameterDefinitionImpl("length", genericPtr, "in/out; *length must be >= GetSize()")
        });

        FunctionDefinitionDataType deserialize = new FunctionDefinitionDataType("IAvatarDataBlock::Deserialize");
        deserialize.setReturnType(u1);
        deserialize.setArguments(new ParameterDefinition[]{ new ParameterDefinitionImpl("stream", voidPtr, "NComm::MemoryStream*") });

        FunctionDefinitionDataType serialize = new FunctionDefinitionDataType("IAvatarDataBlock::Serialize");
        serialize.setReturnType(u1);
        serialize.setArguments(new ParameterDefinition[]{ new ParameterDefinitionImpl("stream", voidPtr, "NComm::MemoryStream*") });

        FunctionDefinitionDataType getVariant = new FunctionDefinitionDataType("IAvatarDataBlock::GetVariant");
        getVariant.setReturnType(u4);
        getVariant.setArguments(new ParameterDefinition[]{});

        FunctionDefinitionDataType getSize = new FunctionDefinitionDataType("IAvatarDataBlock::GetSize");
        getSize.setReturnType(u4);
        getSize.setArguments(new ParameterDefinition[]{});

        FunctionDefinitionDataType clear = new FunctionDefinitionDataType("IAvatarDataBlock::Clear");
        clear.setReturnType(voidT);
        clear.setArguments(new ParameterDefinition[]{});

        DataType dtorR = dtm.addDataType(dtor, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType rfbR = dtm.addDataType(readFromBuffer, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType wtbR = dtm.addDataType(writeToBuffer, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType desR = dtm.addDataType(deserialize, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType serR = dtm.addDataType(serialize, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType gvR = dtm.addDataType(getVariant, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType gsR = dtm.addDataType(getSize, DataTypeConflictHandler.REPLACE_HANDLER);
        DataType clR = dtm.addDataType(clear, DataTypeConflictHandler.REPLACE_HANDLER);

        StructureDataType vft = new StructureDataType(cat, "IAvatarDataBlock_vftable", 0);
        vft.add(new PointerDataType(dtorR), 4, "pDestructor", null);
        vft.add(new PointerDataType(rfbR), 4, "pReadFromBuffer", null);
        vft.add(new PointerDataType(wtbR), 4, "pWriteToBuffer", null);
        vft.add(new PointerDataType(desR), 4, "pDeserialize", "PER-CLASS OVERRIDE");
        vft.add(new PointerDataType(serR), 4, "pSerialize", "PER-CLASS OVERRIDE");
        vft.add(new PointerDataType(gvR), 4, "pGetVariant", "inherited unchanged in all subclasses; shares code (ICF) with the unrelated NComm::Event::GetType -- do not confuse the two");
        vft.add(new PointerDataType(gsR), 4, "pGetSize", "PER-CLASS OVERRIDE; base default returns 4");
        vft.add(new PointerDataType(clR), 4, "pClear", "PURE VIRTUAL in the base interface -- every subclass must override");
        dtm.addDataType(vft, DataTypeConflictHandler.REPLACE_HANDLER);
        println("IAvatarDataBlock_vftable ready.");

        // fix pVftable field type + name on the base struct (must happen after the vftable struct exists)
        Structure baseStruct = (Structure) dtm.getDataType("/LobbyComm/IAvatarDataBlock");
        DataType vftType = dtm.getDataType("/LobbyComm/IAvatarDataBlock_vftable");
        baseStruct.replace(0, new PointerDataType(vftType), 4, "pVftable", "vtable pointer");

        // ---------- 4. rename / namespace / calling-convention ----------
        String[][] shared = {
            {"0x004863f0", "Destructor"}, {"0x00486120", "ReadFromBuffer"}, {"0x004861c0", "WriteToBuffer"},
            {"0x00486410", "Deserialize"}, {"0x00486440", "Serialize"}, {"0x004f2810", "GetSize"}
        };
        GhidraClass iadb = classMap.get("IAvatarDataBlock");
        for (String[] pair : shared) {
            Function f = fm.getFunctionAt(toAddr(pair[0]));
            if (f == null) { println("MISSING " + pair[0]); continue; }
            f.getSymbol().setNamespace(iadb);
            f.setName(pair[1], SourceType.USER_DEFINED);
            if (!"__thiscall".equals(f.getCallingConventionName())) f.setCallingConvention("__thiscall");
        }

        String[] perClassNames = {"AvatarCreationBlockEx", "AvatarAppearanceBlockEx", "AvatarStyleBlockEx",
            "AvatarStatsBlockEx", "AvatarActiveItemsBlockEx", "AvatarInventoryBlockEx"};
        String[][] perClassAddrs = {
            {"0x00486550", "0x00486620", "0x00486270", "0x00486290"},
            {"0x00486760", "0x004867c0", "0x004862c0", "0x004862e0"},
            {"0x004868c0", "0x00486970", "0x004862f0", "0x00486310"},
            {"0x00486d70", "0x00486e50", "0x00486360", "0x004863a0"},
            {"0x00486a20", "0x00486a90", "0x00486330", "0x00486b00"},
            {"0x00486b60", "0x00486be0", "0x00486350", "0x00486c50"}
        };
        String[] methodNames = {"Deserialize", "Serialize", "GetSize", "Clear"};
        for (int i = 0; i < perClassNames.length; i++) {
            GhidraClass cls = classMap.get(perClassNames[i]);
            for (int m = 0; m < methodNames.length; m++) {
                Function f = fm.getFunctionAt(toAddr(perClassAddrs[i][m]));
                if (f == null) { println("MISSING " + perClassAddrs[i][m]); continue; }
                f.getSymbol().setNamespace(cls);
                f.setName(methodNames[m], SourceType.USER_DEFINED);
                if (!"__thiscall".equals(f.getCallingConventionName())) f.setCallingConvention("__thiscall");
            }
        }
        println("Function rename/namespace/calling-convention pass done.");

        // ---------- 5. apply vftable struct type at each class's vftable address ----------
        String[] vfAddrs = {"0x007de3dc", "0x007de400", "0x007de424", "0x007de448", "0x007de46c", "0x007de490", "0x007de4b4"};
        DataType vftableType = dtm.getDataType("/LobbyComm/IAvatarDataBlock_vftable");
        for (String a : vfAddrs) {
            Address addr = toAddr(a);
            currentProgram.getListing().clearCodeUnits(addr, addr.add(vftableType.getLength() - 1), false);
            currentProgram.getListing().createData(addr, vftableType);
            println("Applied IAvatarDataBlock_vftable @ " + addr);
        }

        println("ApplyAvatarDataBlockVtables: done. Verify a decompile (e.g. AvatarStyleBlockEx::Deserialize) "
            + "resolves this->field1.. and this->base.pVftable->pGetVariant() by name, then File > Check In.");
    }
}
