# ghidra_find_field_writes.py — find every instruction that WRITES to [reg + OFFSET].
#
# WHY: struct fields like LobbyManager+0x580 (refereeId) live on a heap singleton reached via a
# global pointer (g_pLobbyManager), so Ghidra can't xref them as a fixed address. A write is
# `MOV dword ptr [reg + 0x580], val` — i.e. a memory-WRITE operand whose displacement == OFFSET.
# This scans all instructions for exactly that, so you get the complete writer list.
#
# USE:
#   1. Ghidra → Window → Script Manager → (folder icon) add this file's dir → run this script
#      on the program that has the CODE (sadk_noav.exe).
#   2. Set OFFSET below and re-run:
#        0x580  -> LobbyManager.refereeId        (Q3: is SetRefereeServerAddress @0x4625d0 the ONLY writer?)
#        0x3624 -> LobbyGameScreen.doRefereeLogin (Q1: who ARMS the referee login — and is it CONDITIONAL?)
#        0x57c  -> LobbyManager.state             (sanity check: should show SetState @0x462540)
#   3. Double-click any hit to jump to it; decompile its function to see the CONTEXT (e.g. is the
#      0x3624 arm gated on a "ranked" flag, or unconditional?).
#
# CAVEAT: catches direct `[reg+disp]` writes (the normal case). It will MISS a write done via a
# pointer first LEA'd into a register (LEA reg,[base+0x580] ; MOV [reg],val) — rare, but if the
# list looks empty/short, also run with SHOW_READS=True to eyeball every 0x580 reference.
#
# @category SAdK
from ghidra.program.model.scalar import Scalar

OFFSET    = 0x580      # <-- change me
SHOW_READS = False     # True = also list READs of [reg+OFFSET] (debug / fallback)

listing = currentProgram.getListing()
it = listing.getInstructions(True)
writes = 0
reads  = 0
print("==== scanning for [reg+0x%X] (program: %s) ====" % (OFFSET, currentProgram.getName()))
while it.hasNext():
    insn = it.next()
    for opIdx in range(insn.getNumOperands()):
        rt = insn.getOperandRefType(opIdx)
        if rt is None:
            continue
        is_w = rt.isWrite()
        is_r = rt.isRead()
        if not (is_w or (SHOW_READS and is_r)):
            continue
        for obj in insn.getOpObjects(opIdx):
            if isinstance(obj, Scalar) and obj.getUnsignedValue() == OFFSET:
                f = getFunctionContaining(insn.getAddress())
                tag = "WRITE" if is_w else "read "
                print("  %s  [%s]  %-42s  %s" % (
                    insn.getAddress(), tag,
                    f.getName() if f else "(no func)", insn.toString()))
                if is_w: writes += 1
                else:    reads += 1
print("==== %d WRITE(s)%s to [reg+0x%X] ====" % (
    writes, (" + %d read(s)" % reads) if SHOW_READS else "", OFFSET))
