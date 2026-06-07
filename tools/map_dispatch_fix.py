r"""
map_dispatch_fix.py -- neutralize SecuROM's dead world-entry import dispatch.

At the LoggedIn checkpoint SecuROM calls, via a baked WinXP kernel32 address
0x7C81320C (UNMAPPED on Win7/10/11):
    OpenFileMappingA(FILE_MAP_WRITE=2, FALSE, "0A25A3F6E7D13B25951F80DE03F34C3")
(decoded byte-for-byte from the crash dump: push 0 / push 2 / call edx, with the
name passed as the call-over-data return address). The call faults; SecuROM's
startup VEH has already torn down -> unhandled -> the crash you hit at world-entry.

FIX: in the LIVE game process, commit a page over the dead 64K region and drop a
JMP at 0x7C81320C to the process's REAL OpenFileMappingA. The dispatch then runs
the genuine import (returns the handle to SecuROM's already-open named mapping),
the MapViewOfFile follow-up succeeds, and world-entry proceeds. No slot hunting.

apply(pid) is called by debugger_loader.py right after it attaches (so it runs
elevated). Standalone:  python map_dispatch_fix.py [pid]   (run ELEVATED).
"""
import ctypes, sys, struct, os
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pe_exports import parse_exports

DEAD   = 0x7C81320C
REGION = 0x7C810000              # 64K-aligned block containing DEAD
RSIZE  = 0x10000
PROCESS_ALL = 0x1F0FFF
MEM_COMMIT_RESERVE = 0x3000
PAGE_EXECUTE_READWRITE = 0x40
LIST_MODULES_32BIT = 0x02

k32   = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi",    use_last_error=True)
ntdll = ctypes.WinDLL("ntdll",    use_last_error=True)

H, D, LPV, BOOL, SIZE = wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.BOOL, ctypes.c_size_t
PSZ = ctypes.POINTER(SIZE)
k32.OpenProcess.argtypes = [D, BOOL, D];                       k32.OpenProcess.restype = H
k32.CloseHandle.argtypes = [H]
k32.VirtualAllocEx.argtypes = [H, LPV, SIZE, D, D];            k32.VirtualAllocEx.restype = LPV
k32.WriteProcessMemory.argtypes = [H, LPV, LPV, SIZE, PSZ];    k32.WriteProcessMemory.restype = BOOL
k32.ReadProcessMemory.argtypes  = [H, LPV, LPV, SIZE, PSZ];    k32.ReadProcessMemory.restype  = BOOL
k32.CreateToolhelp32Snapshot.argtypes = [D, D];               k32.CreateToolhelp32Snapshot.restype = H
k32.Process32First.argtypes = [H, LPV];                       k32.Process32First.restype = BOOL
k32.Process32Next.argtypes  = [H, LPV];                       k32.Process32Next.restype  = BOOL
ntdll.NtQueryInformationProcess.argtypes = [H, D, LPV, D, ctypes.POINTER(D)]

class PE32(ctypes.Structure):
    _fields_ = [("dwSize", D), ("cntUsage", D), ("th32ProcessID", D),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", D), ("cntThreads", D), ("th32ParentProcessID", D),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", D), ("szExeFile", ctypes.c_char * 260)]

def find_pid():
    snap = k32.CreateToolhelp32Snapshot(2, 0)        # TH32CS_SNAPPROCESS
    pe = PE32(); pe.dwSize = ctypes.sizeof(PE32); pid = None
    if k32.Process32First(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.lower() == b"sadk.exe":
                pid = pe.th32ProcessID; break
            if not k32.Process32Next(snap, ctypes.byref(pe)): break
    k32.CloseHandle(snap)
    return pid

def _rpm(h, addr, size):
    buf = ctypes.create_string_buffer(size); rd = SIZE(0)
    if not k32.ReadProcessMemory(h, ctypes.c_void_p(addr & 0xFFFFFFFF), buf, size, ctypes.byref(rd)):
        return None
    return buf.raw[:rd.value]

def kernel32_base(h):
    """Walk the WOW64 target's 32-bit PEB loader module list (robust cross-bitness)."""
    peb32 = ctypes.c_ulonglong(0)
    ntdll.NtQueryInformationProcess(h, 26, ctypes.byref(peb32), 8, None)   # ProcessWow64Information
    p = peb32.value & 0xFFFFFFFF
    if not p:
        print("[!] no WOW64 PEB (is the target 32-bit?)"); return None
    d = _rpm(h, p + 0x0C, 4)
    if not d: return None
    ldr = struct.unpack("<I", d)[0]
    head = ldr + 0x0C                                # PEB_LDR_DATA.InLoadOrderModuleList
    d = _rpm(h, head, 4)
    if not d: return None
    flink = struct.unpack("<I", d)[0]
    names = []
    for _ in range(512):
        if flink == 0 or flink == head: break
        db = _rpm(h, flink + 0x18, 4)                # LDR_DATA_TABLE_ENTRY32.DllBase
        nl = _rpm(h, flink + 0x2C, 2)                # BaseDllName.Length
        nb = _rpm(h, flink + 0x30, 4)                # BaseDllName.Buffer
        nx = _rpm(h, flink, 4)                       # InLoadOrderLinks.Flink
        if not (db and nl and nb and nx): break
        namelen = struct.unpack("<H", nl)[0]; namebuf = struct.unpack("<I", nb)[0]
        if namelen and namebuf:
            raw = _rpm(h, namebuf, namelen)
            if raw:
                nm = raw.decode("utf-16-le", "ignore")
                names.append(nm)
                if nm.lower() == "kernel32.dll":
                    return struct.unpack("<I", db)[0]
        flink = struct.unpack("<I", nx)[0]
    print(f"[!] kernel32 not in module list ({len(names)}): {names[:12]}")
    return None

PUSH_EAX_VA = 0x01841A9D   # `push eax` (OpenFileMappingA handle) feeding the no-op wrapper
WRAPPER_VA  = 0x02460510   # stub `mov eax,0x5cc; ret` -> returns junk AND doesn't pop its arg

def _stack_balance_fix(h):
    """After the (now-working) OpenFileMappingA call, the VM pushes the handle @0x01841a9d
    and `call`s a no-op stub @0x02460510 (`mov eax,0x5cc; ret`) that does NOT clean that arg.
    So `pop ecx` @0x01841ab9 lands the handle in ecx and `add [ecx],edx` @0x01841aba
    write-faults (0xc0000005). NOP the push so the stack stays balanced and ecx keeps the
    real pointer; the continuation then restores the saved regs correctly."""
    w = _rpm(h, WRAPPER_VA, 6)
    stubby = bool(w) and len(w) == 6 and w[0] == 0xB8 and w[5] == 0xC3
    print(f"[i] wrapper @{WRAPPER_VA:#010x} = {w.hex() if w else '??'} ({'no-op stub (expected)' if stubby else 'UNEXPECTED -- stack fix may be wrong'})")
    cur = _rpm(h, PUSH_EAX_VA, 1)
    if cur == b"\x50":
        wr = SIZE(0)
        k32.WriteProcessMemory(h, ctypes.c_void_p(PUSH_EAX_VA), b"\x90", 1, ctypes.byref(wr))
        chk = _rpm(h, PUSH_EAX_VA, 1)
        print(f"[i] NOP `push eax` @{PUSH_EAX_VA:#010x}: now={chk.hex() if chk else '??'} (stack-balance fix)")
        return chk == b"\x90"
    print(f"[!] @{PUSH_EAX_VA:#010x} expected 50 (push eax), got {cur.hex() if cur else None} -- skip stack fix")
    return False

def apply(pid):
    """Commit the dead page + write JMP 0x7C81320C -> OpenFileMappingA. Returns bool."""
    rva = parse_exports(r"C:\Windows\SysWOW64\kernel32.dll")["exports"]["OpenFileMappingA"]
    h = k32.OpenProcess(PROCESS_ALL, False, pid)
    if not h:
        print(f"[!] OpenProcess({pid}) failed err={ctypes.get_last_error()} -- run ELEVATED"); return False
    try:
        base = kernel32_base(h)
        if not base:
            print("[!] could not locate game kernel32"); return False
        ofa = (base + rva) & 0xFFFFFFFF
        print(f"[i] pid={pid}  kernel32={base:#010x}  OpenFileMappingA(+{rva:#x})={ofa:#010x}")

        got = k32.VirtualAllocEx(h, ctypes.c_void_p(REGION), RSIZE, MEM_COMMIT_RESERVE, PAGE_EXECUTE_READWRITE)
        print(f"[i] VirtualAllocEx({REGION:#x},{RSIZE:#x},RWX) -> {(got or 0):#x}  err={ctypes.get_last_error()}")

        rel  = (ofa - (DEAD + 5)) & 0xFFFFFFFF
        stub = b"\xE9" + struct.pack("<I", rel)                # JMP rel32 -> OpenFileMappingA
        wr = SIZE(0)
        cbuf = ctypes.create_string_buffer(stub, len(stub))
        ok = k32.WriteProcessMemory(h, ctypes.c_void_p(DEAD), cbuf, len(stub), ctypes.byref(wr))
        print(f"[i] WriteProcessMemory({DEAD:#x}) ok={ok} wrote={wr.value} err={ctypes.get_last_error()}")

        rbuf = ctypes.create_string_buffer(5); rd = SIZE(0)
        k32.ReadProcessMemory(h, ctypes.c_void_p(DEAD), rbuf, 5, ctypes.byref(rd))
        got_bytes = rbuf.raw[:5]
        print(f"[i] readback @{DEAD:#x}: " + " ".join(f"{b:02x}" for b in got_bytes))
        if ok and got_bytes == stub:
            print(f"[+] 0x{DEAD:x} -> JMP OpenFileMappingA")
            _stack_balance_fix(h)
            print(f"[+] patches applied. Trigger world-entry (ENTER).")
            return True
        print("[!] patch did not verify"); return False
    finally:
        k32.CloseHandle(h)

def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else find_pid()
    if not pid:
        print("[!] SADK.exe not running"); return 1
    return 0 if apply(pid) else 4

if __name__ == "__main__":
    sys.exit(main())
