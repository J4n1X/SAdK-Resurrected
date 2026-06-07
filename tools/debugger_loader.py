r"""
debugger_loader.py -- run SADK.exe under a transparent debug loop so SecuROM's
exception-based API dispatch works on Windows 10/11.

THE BUG (proven live):
  SecuROM 7.x redirects "imported" calls through a deliberately-UNMAPPED WinXP
  kernel32 address (e.g. 0x7C81320C). The call faults; SecuROM's vectored
  exception handler (VEH) catches the access-violation, resolves the real API,
  and forwards. On Win7 this works. On Win10/11 the modernized WOW64 fails to
  deliver that 32-bit fault to the in-process VEH WITHOUT a debugger attached ->
  unhandled -> crash (the "Suche Server" / village-enter crash).

THE FIX:
  A debugger attached, PASSING first-chance exceptions back to the app, forces
  the fault through the path that DOES reach the 32-bit VEH -> SecuROM dispatches
  -> the game runs. This loader is that debugger; it does nothing but pass
  exceptions (consuming only the system's attach breakpoint). No binary patch,
  no DLL injection, no SecuROM RE -- it transparently fixes every dispatch.

PROVEN: under this exact setup the host game completed village-enter on Win11
(token handshake + stable pings + 3D world), identical to Win7.

RUN ELEVATED (the game needs admin; to debug an admin process the debugger must
be admin too). Keep this window open for the whole session -- if the loader
stops, the next SecuROM dispatch will crash.

Usage:  python debugger_loader.py            (launch + debug)
        python debugger_loader.py 12.0       (override attach delay seconds)
"""
import ctypes, sys, time, struct, os
from ctypes import wintypes

try:
    sys.stdout.reconfigure(line_buffering=True)   # flush per line even when redirected to a file
except Exception:
    pass

# Tee stdout to a file with per-write flush so a NON-elevated watcher can read the loader's FAULT
# lines LIVE — the elevated console's pipe (PowerShell Tee-Object) buffered them away last run. (s34)
class _TeeStdout:
    def __init__(self, path):
        self._f = open(path, "w", buffering=1, encoding="utf-8")
        self._con = sys.__stdout__
    def write(self, s):
        try:
            if self._con:
                self._con.write(s)
        except Exception:
            pass
        try:
            self._f.write(s); self._f.flush()
        except Exception:
            pass
    def flush(self):
        for h in (self._con, self._f):
            try:
                if h:
                    h.flush()
            except Exception:
                pass

try:
    sys.stdout = _TeeStdout(os.path.join(os.path.dirname(os.path.abspath(__file__)), "loader_live.log"))
except Exception:
    pass

# EDIT PER MACHINE: point these at your SADK.exe and its containing bin\ directory.
GAME     = r"<PATH TO YOUR SADK.exe>"            # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin\SADK.exe"
GAME_CWD = r"<PATH TO YOUR SADK.exe bin DIR>"    # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin"
ATTACH_DELAY = 8.0  # launch mode: let SecuROM's startup anti-debug finish before attaching

DBG_CONTINUE              = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT     = 1
EXIT_PROCESS_DEBUG_EVENT  = 5
EXCEPTION_BREAKPOINT      = 0x80000003

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

class STARTUPINFO(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
                ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
                ("hStdError", wintypes.HANDLE)]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

class DEBUG_EVENT(ctypes.Structure):           # header + generous union buffer
    _fields_ = [("dwDebugEventCode", wintypes.DWORD),
                ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD),
                ("u", ctypes.c_ubyte * 184)]

def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "attach" and len(argv) > 1:
        pid = int(argv[1])                          # attach to an already-running SADK
        print(f"[+] ATTACH mode -> existing pid={pid}")
    else:
        delay = float(argv[0]) if argv else ATTACH_DELAY
        si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
            wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
        if not k32.CreateProcessW(GAME, None, None, None, False, 0, None, GAME_CWD,
                                  ctypes.byref(si), ctypes.byref(pi)):
            print(f"[!] CreateProcess failed: {ctypes.get_last_error()} (run me ELEVATED)"); return 1
        pid = pi.dwProcessId
        k32.CloseHandle(pi.hThread); k32.CloseHandle(pi.hProcess)
        print(f"[+] launched SADK pid={pid}; letting SecuROM start ({delay:g}s)...")
        time.sleep(delay)

    if not k32.DebugActiveProcess(pid):
        print(f"[!] DebugActiveProcess failed: {ctypes.get_last_error()}"); return 2
    k32.DebugSetProcessKillOnExit(False)        # game survives if we detach
    print(f"[+] attached pid={pid}. Passing faults to SecuROM's VEH. KEEP THIS OPEN. (Ctrl+C to stop)")

    try:                                        # neutralize the dead world-entry import (LoggedIn 0x7C81320C)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import map_dispatch_fix
        print("[*] applying world-entry dispatch fix (0x7C81320C -> OpenFileMappingA)...")
        map_dispatch_fix.apply(pid)
    except Exception as e:
        print(f"[!] dispatch fix failed: {e!r}")

    de = DEBUG_EVENT()
    consumed_attach_bp = False
    passed = 0
    while True:
        if not k32.WaitForDebugEvent(ctypes.byref(de), 0xFFFFFFFF):
            print(f"[!] WaitForDebugEvent failed: {ctypes.get_last_error()}"); break
        code = de.dwDebugEventCode
        status = DBG_CONTINUE
        if code == EXCEPTION_DEBUG_EVENT:
            # 64-bit DEBUG_EVENT: the union is 8-byte aligned -> 4 bytes after our u field.
            ub = bytes(de.u)
            exc_code  = struct.unpack_from("<I", ub, 4)[0]    # EXCEPTION_RECORD.ExceptionCode
            exc_addr  = struct.unpack_from("<Q", ub, 20)[0] & 0xFFFFFFFF  # .ExceptionAddress (32-bit fault)
            first_ch  = struct.unpack_from("<I", ub, 0)[0]    # (pad / dwFirstChance varies)
            if exc_code == EXCEPTION_BREAKPOINT and not consumed_attach_bp:
                consumed_attach_bp = True            # the system's attach breakpoint -> eat it
            else:
                status = DBG_EXCEPTION_NOT_HANDLED    # everything else -> the app's VEH (SecuROM)
                passed += 1
                if exc_code != EXCEPTION_BREAKPOINT or passed <= 4:
                    print(f"    FAULT #{passed}: code={exc_code:#010x} addr={exc_addr:#010x} tid={de.dwThreadId}")
        if code == EXIT_PROCESS_DEBUG_EVENT:
            k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, DBG_CONTINUE)
            print(f"[+] game exited. ({passed} faults passed)"); break
        k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, status)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[+] stopped. (game keeps running, but will crash on its next SecuROM dispatch)")
