r"""
dump_module.py -- SecuROM unpack step 1: dump the LIVE DECRYPTED SADK.exe image from memory.

Walks committed regions in [0x400000, 0x2460000] (the SADK module), ReadProcessMemory each, and writes
a VA-offset flat image to SADK_dump.bin (file offset == VA - 0x400000). This captures the fully-decrypted
code (incl. the SecuROM .securom overlay that is encrypted/zero on disk) for loading into Ghidra.

Also a FEASIBILITY probe: reads the world-entry proceed-logic pointer *[0x12EBF30] and disassembles its
target -> tells us if the overlay is plain x86 (RE-able directly) or SecuROM VM-bytecode (needs more work).

RUN ELEVATED, READ-ONLY (OpenProcess VM_READ + RPM). Cannot crash the game.
Usage:  python dump_module.py [pid]
"""
import ctypes
import os
import sys
from ctypes import wintypes

import capstone

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

BASE = 0x400000
END = 0x2461000   # .securom ends at VA 0x24605E8 -> dump PAST it (the s34 glass.exe crashed because the
#   old END=0x2460000 truncated the last 0x5E8 bytes of .securom; the SecuROM VM CALLs code at 0x2460535).
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SADK_dump.bin")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("__pad", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD), ("__pad2", wintypes.DWORD)]


class PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def find_pid(name="SADK.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PE32(); e.dwSize = ctypes.sizeof(e); pid = None
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.decode("ascii", "ignore").lower() == name.lower():
                pid = e.th32ProcessID; break
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return pid


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else find_pid()
    if not pid:
        print("SADK.exe not found"); return 1
    print(f"[+] SADK.exe pid={pid}")
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"[!] OpenProcess failed err={ctypes.get_last_error()} -- run ELEVATED"); return 2

    def rpm(a, n):
        buf = (ctypes.c_ubyte * n)(); got = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(a), buf, n, ctypes.byref(got))
        return bytes(buf[:got.value]) if ok else b""

    img = bytearray(END - BASE)
    addr = BASE
    committed = 0
    regions = 0
    while addr < END:
        mbi = MBI()
        if k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)) == 0:
            break
        rbase = mbi.BaseAddress or addr
        rsize = mbi.RegionSize or 0x1000
        if (mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD))):
            regions += 1
            off = 0
            while off < rsize:
                a = rbase + off
                if a >= END:
                    break
                chunk = rpm(a, min(0x100000, rsize - off, END - a))
                if not chunk:
                    break
                img[a - BASE:a - BASE + len(chunk)] = chunk
                committed += len(chunk)
                off += len(chunk) if chunk else 0x1000
        addr = rbase + rsize

    with open(OUT, "wb") as fp:
        fp.write(img)
    mz = bytes(img[:2])
    print(f"[+] dumped {committed} committed bytes across {regions} regions -> {OUT}")
    print(f"[i] header bytes: {mz.hex()} ({'MZ ok' if mz == b'MZ' else 'NO MZ?!'})  total file={len(img)}")

    # feasibility probe: the action-proceed overlay target
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ptr = rpm(0x12EBF30, 4)
    if len(ptr) == 4:
        tgt = int.from_bytes(ptr, "little")
        print(f"\n[i] action_proceed: *[0x12EBF30] = 0x{tgt:08X}  (this is where 0x503900 jmps)")
        code = rpm(tgt, 0xA0)
        if code and not all(b == 0 for b in code):
            print(f"[i] disasm @0x{tgt:08X} (overlay proceed-logic):")
            for ins in md.disasm(code, tgt):
                print(f"     0x{ins.address:08X}  {ins.bytes.hex():<16} {ins.mnemonic:<6} {ins.op_str}")
        else:
            print("[!] target unreadable/zero")
    return 0


if __name__ == "__main__":
    sys.exit(main())
