r"""
minidump_exc.py -- READ-ONLY analyzer for a SADK.exe WER crash dump.

Pulls the exception record, the faulting thread's x86 register context, and reconstructs a
probable call chain by scanning the stack for return addresses that point into SADK.exe's
.text. Pure file analysis -- touches no live process. Needs the `minidump` pip package.

Usage:  python minidump_exc.py [path-to-dump]
        (default: newest SADK.exe*.dmp in %LOCALAPPDATA%\CrashDumps)
"""
import glob
import os
import struct
import sys

from minidump.minidumpfile import MinidumpFile

TEXT_LO, TEXT_HI = 0x00401000, 0x007D4000     # SADK.exe analyzed .text
IMG_LO,  IMG_HI  = 0x00400000, 0x00800000     # whole image (rough)

# x86 CONTEXT field offsets
X86 = dict(Edi=0x9C, Esi=0xA0, Ebx=0xA4, Edx=0xA8, Ecx=0xAC, Eax=0xB0,
           Ebp=0xB4, Eip=0xB8, EFlags=0xC0, Esp=0xC4)


def newest_dump():
    d = os.path.join(os.environ.get("LOCALAPPDATA", ""), "CrashDumps")
    cands = sorted(glob.glob(os.path.join(d, "SADK.exe*.dmp")), key=os.path.getmtime, reverse=True)
    return cands[0] if cands else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else newest_dump()
    if not path or not os.path.exists(path):
        print("no dump found"); return 1
    print(f"[+] dump: {path}  ({os.path.getsize(path):,} bytes)\n")
    mf = MinidumpFile.parse(path)

    # ---- exception record ----
    exc = getattr(mf, "exception", None)
    recs = getattr(exc, "exception_records", None) or getattr(exc, "exceptions", None) or []
    if not recs:
        print("[!] no exception stream"); return 2
    def iv(x):
        if x is None:
            return None
        x = getattr(x, "value", x)
        try:
            return int(x)
        except (TypeError, ValueError):
            return x

    er = recs[0]
    rec = getattr(er, "ExceptionRecord", er)
    code = iv(getattr(rec, "ExceptionCode_raw", None))
    if code is None:
        code = iv(getattr(rec, "ExceptionCode", None))
    addr = iv(getattr(rec, "ExceptionAddress", None))
    nparm = iv(getattr(rec, "NumberParameters", 0)) or 0
    info = [iv(x) for x in (getattr(rec, "ExceptionInformation", []) or [])]
    tid = iv(getattr(er, "ThreadId", None))
    KNOWN = {0xC0000005: "ACCESS_VIOLATION", 0xC000000D: "INVALID_PARAMETER",
             0xC0000409: "STACK_BUFFER_OVERRUN", 0x80000003: "BREAKPOINT",
             0xC0000025: "NONCONTINUABLE_EXCEPTION", 0xC0000094: "INTEGER_DIVIDE_BY_ZERO"}
    print("== exception ==")
    print(f"  code    = {code:#010x}  [{KNOWN.get(code, '?')}]" if code is not None else "  code = ?")
    print(f"  address = {addr:#010x}   (SADK.exe+{addr-0x400000:#x})" if addr else "  address = ?")
    print(f"  thread  = {tid}")
    if nparm:
        print(f"  params  = {[hex(x) for x in list(info)[:nparm]]}")

    # ---- faulting thread x86 context (parse the CONTEXT blob at its file RVA) ----
    tc = getattr(er, "ThreadContext", None)
    ctx = {}
    if tc is not None and getattr(tc, "DataSize", 0):
        with open(path, "rb") as f:
            f.seek(tc.Rva)
            blob = f.read(tc.DataSize)
        print(f"\n== faulting thread CONTEXT (size={tc.DataSize}) ==")
        if tc.DataSize >= 0xCC:   # x86 CONTEXT
            for name, off in X86.items():
                ctx[name] = struct.unpack_from("<I", blob, off)[0]
            for name in ("Eip", "Esp", "Ebp", "Eax", "Ecx", "Edx", "Ebx", "Esi", "Edi", "EFlags"):
                v = ctx[name]
                tag = ""
                if name == "Eip" and TEXT_LO <= v < IMG_HI:
                    tag = f"  (SADK.exe+{v-0x400000:#x})"
                print(f"  {name:6} = {v:#010x}{tag}")
        else:
            print(f"  [!] unexpected context size; raw head = {blob[:32].hex()}")

    # ---- modules (confirm SADK base) ----
    mods = getattr(getattr(mf, "modules", None), "modules", []) or []
    for m in mods:
        nm = (getattr(m, "name", "") or "").lower()
        if "sadk" in nm or "tincat" in nm:
            base = getattr(m, "baseaddress", None)
            size = getattr(m, "size", None)
            print(f"\n  module {os.path.basename(getattr(m,'name','?'))}: base={base:#x} size={size:#x}"
                  if base is not None else f"\n  module {nm}")

    # ---- stack scan for return addresses into SADK .text ----
    esp = ctx.get("Esp")
    if esp:
        reader = mf.get_reader()

        def rd(addr, size):
            try:
                return reader.read(addr, size)
            except Exception:
                return None

        print(f"\n== stack scan from ESP={esp:#x} (return addrs into SADK .text) ==")
        n = 0
        for i in range(0, 0x800, 4):
            b = rd(esp + i, 4)
            if b is None or len(b) != 4:
                continue
            v = struct.unpack_from("<I", b, 0)[0]
            if TEXT_LO <= v < TEXT_HI:
                print(f"  esp+{i:#05x}: {v:#010x}   SADK.exe+{v-0x400000:#x}")
                n += 1
                if n >= 40:
                    break
        if n == 0:
            print("  (no SADK .text return addresses found in first 0x800 bytes)")
    print("\n[done] read-only file analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
