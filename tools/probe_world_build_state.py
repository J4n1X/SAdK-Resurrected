r"""
probe_world_build_state.py -- read SADK's live world-build gate via ReadProcessMemory.

RUN ELEVATED. READ-ONLY: OpenProcess(VM_READ) + ReadProcessMemory only -- never writes,
never debugs, never resumes. Cannot crash the game. Safe while debugger_loader.py holds it.

WHY: s40 traced the in-match world build to a per-frame GATE in the magazine build (sadk_noav):
  nMenuSystem_Update_FramePump @0x5DA500 fires the 3D build ONLY when
    g_pNMenuSystem(*0x0088B83C)->nPendingEnterWorldRequest[+0x7C] != 0
  -> AppState_EnterWorld @0x5D9FD0 -> nMenu_Game::OnEnter @0x5EED00 -> GameSystem build.
The setter of +0x7C is static-RE-elusive ("TBD"). This probe reads it LIVE so we can settle:

  * +0x7C == 0 during the MP stall  => the build NEVER ARMS in MP (the gate is the MP gap;
                                       SP sets it, MP doesn't -> needs the genuine trigger).
  * +0x7C != 0 during the MP stall  => the build ARMED but stalls DEEPER (GameSystem/terrain).

Compare MP (stuck match) vs SP (start a skirmish): the difference in +0x7C / +0xA4 / +0x68
is the answer. ADDRESSES are for the magazine build (sadk_noav). If the live game is a
different SADK.exe build, the singleton read will look like garbage -- say so and I'll re-anchor.

Fields (nMenu_System):  +0x3c pActiveScreen   +0x68 pGameLoadDescriptorStaging
                        +0x7c nPendingEnterWorldRequest (THE GATE)   +0xa4 cModeFlag (SP/MP)

Usage:  python tools\probe_world_build_state.py            (auto-find SADK.exe)
        python tools\probe_world_build_state.py 20680      (explicit pid)
        python tools\probe_world_build_state.py --watch    (re-read every 1s; Ctrl+C to stop)
"""
import ctypes
import sys
import time
from ctypes import wintypes

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

G_PNMENUSYSTEM = 0x0088B83C   # *this = nMenu_System singleton (CONFIRMED in sadk_noav, s40)
G_PGAMESYSTEM = 0x0088996C    # GameSystem singleton (from memory world-build-model-clean-binary; verify)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def find_pids(name="SADK.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32(); e.dwSize = ctypes.sizeof(e)
    pids = []
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.decode("ascii", "ignore").lower() == name.lower():
                pids.append(e.th32ProcessID)
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return pids


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    watch = "--watch" in sys.argv
    if args:
        pid = int(args[0])
    else:
        pids = find_pids()
        if not pids:
            print("SADK.exe not found (is the game running?)"); return 1
        pid = pids[0]
        print(f"[+] SADK.exe pid={pid}")

    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"[!] OpenProcess failed: err={ctypes.get_last_error()} -- run this ELEVATED"); return 2

    def rpm(addr, size):
        buf = (ctypes.c_ubyte * size)()
        n = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
        return bytes(buf) if (ok and n.value == size) else None

    def u32(addr):
        b = rpm(addr, 4); return None if b is None else int.from_bytes(b, "little")

    def u8(addr):
        b = rpm(addr, 1); return None if b is None else b[0]

    def snapshot():
        sysptr = u32(G_PNMENUSYSTEM)
        print(f"\n  g_pNMenuSystem @0x{G_PNMENUSYSTEM:08X} -> "
              + (f"0x{sysptr:08X}" if sysptr else "null/unreadable"))
        if not sysptr or sysptr < 0x10000 or sysptr > 0x7FFFFFFF:
            print("  >>> singleton looks invalid -- live game may not be the magazine build; tell me the exe.")
            return
        pending = u32(sysptr + 0x7c)
        mode = u8(sysptr + 0xa4)
        desc = u32(sysptr + 0x68)
        active = u32(sysptr + 0x3c)
        slot = u32(sysptr + 0xc)
        print(f"    +0x7c nPendingEnterWorldRequest = "
              + (f"{pending} (0x{pending:X})" if pending is not None else "<?>")
              + ("   <<< GATE OPEN: build SHOULD fire" if pending else "   <<< GATE CLOSED: build will NOT fire"))
        print(f"    +0xa4 cModeFlag (SP/MP)        = " + (f"{mode}" if mode is not None else "<?>")
              + "   [FramePump full-UI path runs when ==0]")
        print(f"    +0x68 pGameLoadDescriptorStg  = "
              + (f"0x{desc:08X}" if desc is not None else "<?>")
              + ("   (staged)" if desc else "   (NULL -- no descriptor staged)"))
        print(f"    +0x3c pActiveScreen           = " + (f"0x{active:08X}" if active is not None else "<?>")
              + f"   +0xc activeSlot = " + (f"0x{slot:08X}" if slot is not None else "<?>"))
        gs = u32(G_PGAMESYSTEM)
        print(f"  g_pGameSystem  @0x{G_PGAMESYSTEM:08X} -> "
              + (f"0x{gs:08X}   (GameSystem CONSTRUCTED)" if gs else "NULL (GameSystem NOT built yet)"
                 if gs is not None else "<unreadable>")
              + "   [verify this global if it always reads odd]")

    if watch:
        print("[watch] reading every 1s -- start/leave the MP match (or a SP game) to see +0x7c flip. Ctrl+C to stop.")
        try:
            while True:
                snapshot(); time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[watch] stopped.")
    else:
        snapshot()
        print("\n  Compare this against a working SINGLE-PLAYER game start: if +0x7c is non-zero in SP")
        print("  but 0 in the stuck MP match, the gate is the MP gap (the build never arms).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
