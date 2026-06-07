r"""
patch_je_file.py -- STATIC file patch: revert the no-CD crack's sole game-code corruption.

The ~2013 no-CD crack's ONLY game-code (.text) change vs genuine retail -- proven by a full-image
byte-diff of the unpacked "SADK - NO CD.exe" vs the raw retail memory dump tools/SADK_dump.bin -- is a
single inserted branch: at file offset 0x103e22 (image 0x503e22, inside EnterVillageAction_Tick @0x503e10)
the crack has `74 18` (je 0x503e3c) where genuine retail has `90 90` (nop;nop). That gate wedges the
EnterVillageAction state machine ([+0xc] left uncleared) and is the lead suspect for the 0xC000000D
_vsnprintf_s crash. See engagement_records/2026-06-07_patch_je_file.md + memory/securom-win11-crash-modes.md.

This tool makes a COPY of the no-CD exe and reverts those 2 bytes to retail's `90 90`. It does NOT touch
the original. Non-destructive + trivially reversible (delete the copy / `undo`).

NOTE: this is a CRASH-FIX candidate only. It restores genuine retail code; it does NOT claim to enable MP
world-entry (P3/BINARY_PATCHES.md showed the live flip is a no-op for world-entry -- a separate wait-state).

(R) STATE-MUTATING (a binary patch). `apply` is GATED by harness_gate (require_approval) -- see ../HARNESS.md.
`verify` (read-only) and `undo` (rollback) stay ungated.

Usage:
  python patch_je_file.py verify     # read-only: show current bytes in src + dst (UNGATED)
  python patch_je_file.py apply      # GATED: copy src->dst, revert 74 18 -> 90 90 in the COPY
  python patch_je_file.py undo       # UNGATED rollback: delete the patched copy
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness_gate import require_approval  # noqa: E402

# EDIT PER MACHINE: point this at the bin\ directory holding your no-CD SADK exe.
BIN = r"<PATH TO YOUR SADK.exe bin DIR>"              # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin"
SRC = os.path.join(BIN, "SADK - NO CD.exe")          # the unpacked no-CD crack (33.9MB; plaintext here)
DST = os.path.join(BIN, "SADK - NO CD - jefix.exe")  # the patched COPY we create
OFF = 0x103E22          # file offset == image 0x503e22 (unpacked dump-PE: file offset == RVA)
ORIG = b"\x74\x18"      # je 0x503e3c -- the crack's inserted gate
PATCH = b"\x90\x90"     # nop ; nop   -- genuine retail bytes (tools/SADK_dump.bin @0x103e22)


def _read2(path):
    with open(path, "rb") as f:
        f.seek(OFF)
        return f.read(2)


def _tag(b):
    return "je/CRACK" if b == ORIG else ("nop;nop/RETAIL" if b == PATCH else "?? unexpected")


def cmd_verify():
    print(f"[verify] read-only -- nothing modified.  offset 0x{OFF:x} (image 0x503e22)")
    for label, p in (("src  (no-CD)", SRC), ("dst  (jefix)", DST)):
        if os.path.exists(p):
            b = _read2(p)
            print(f"  {label}: {b.hex()}  ({_tag(b)})")
        else:
            print(f"  {label}: (absent)")
    return 0


def cmd_apply():
    require_approval("patch_je_file")  # HARD GATE -- aborts unless an approved Engagement Record exists
    if not os.path.exists(SRC):
        print(f"[!] source not found: {SRC}")
        return 1
    cur = _read2(SRC)
    if cur != ORIG:
        print(f"[!] src @0x{OFF:x} = {cur.hex()} ({_tag(cur)}), expected 7418 (je). Wrong file/offset -- ABORT.")
        return 3
    shutil.copy2(SRC, DST)
    with open(DST, "r+b") as f:
        f.seek(OFF)
        f.write(PATCH)
    chk = _read2(DST)
    if chk != PATCH:
        print(f"[!] verify FAILED: dst @0x{OFF:x} = {chk.hex()} -- ABORT")
        return 4
    print(f"[+] patched copy written: {DST}")
    print(f"    @0x{OFF:x}: 7418 (je/crack) -> {chk.hex()} (nop;nop/retail)")
    print(f"    original UNTOUCHED: {SRC}")
    print("    => run the patched copy and check (read-only) whether the 0xC000000D crash is gone.")
    return 0


def cmd_undo():
    if os.path.exists(DST):
        os.remove(DST)
        print(f"[+] rollback: deleted patched copy {DST}")
    else:
        print("[i] no patched copy present -- nothing to undo.")
    return 0


def main(argv):
    cmd = argv[0] if argv else "verify"
    return {"verify": cmd_verify, "apply": cmd_apply, "undo": cmd_undo}.get(cmd, cmd_verify)()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
