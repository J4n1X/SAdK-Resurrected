r"""
debugger_trace.py -- INSTRUMENTED variant of debugger_loader.py.

Runs SADK.exe under the SAME transparent debug loop that makes SecuROM's
exception-based API dispatch work on Win10/11 (DebugActiveProcess +
WaitForDebugEvent + ContinueDebugEvent, passing every first-chance access
violation back to the app's VEH), and ADDITIONALLY installs two software
(INT3) breakpoints to capture the two stubborn unknowns that live in the
SecuROM overlay and won't decompile statically:

  (a) tincat3!TinCat_CreateCommLayer  (0x10018C20, tincat3 @ 0x10000000)
        -> logs the per-layer app MAGIC (arg2) and the server-address string
           (arg4). The lobby layer uses magic 0x26B6; the VILLAGE layer's
           magic is what we still need to plug into the stub.

  (b) ws2_32!connect
        -> logs the exact sockaddr the client dials (ip:port). After login the
           client sits at "Betrete Welt..." -- this reveals the real village /
           world server address it tries to reach (or proves it reaches none).

WHY A SIBLING, NOT A REWRITE:
  The plain debugger_loader.py is proven to carry this SecuROM target into the
  3D world. This file reuses that exact loop byte-for-byte and only ADDS our own
  INT3 handling on TWO known addresses. SecuROM's first-chance AVs are still
  passed through untouched (DBG_EXCEPTION_NOT_HANDLED) so the protector's
  dispatch is never disturbed. If a hook cannot be installed it is skipped with
  a warning; with TRACE_HOOKS = {} the behaviour is byte-identical to the loader.

SOFTWARE-BREAKPOINT TECHNIQUE (classic, per-address):
  install : Read original byte -> Write 0xCC -> FlushInstructionCache.
  hit     : EXCEPTION_BREAKPOINT whose ExceptionAddress == a hooked address ->
            read 32-bit context (Wow64GetThreadContext for the WOW64 target),
            read stack args at [ESP+4..], LOG, then re-arm:
              restore original byte, set EIP back to the bp address,
              set the trap flag (TF) so the CPU single-steps off the instr.
  re-arm  : on the following EXCEPTION_SINGLE_STEP, rewrite 0xCC and clear TF.
  This keeps the byte present for every future call while never executing the
  hooked instruction with the 0xCC in place.

RUN ELEVATED (the game needs admin; to debug an admin process the debugger must
be admin too). Keep this window open for the whole session.

Usage:  python debugger_trace.py                 (launch + debug + trace)
        python debugger_trace.py 12.0            (override attach delay seconds)
        python debugger_trace.py 8.0 --no-hooks  (behaves exactly like debugger_loader.py)

Output: a clear, timestamped trace to BOTH stdout and tools/trace.out, e.g.
        [CreateCommLayer] magic=0x000026b6 addr="127.0.0.1:7070"
        [connect]         -> 127.0.0.1:5479
"""
import ctypes, sys, time, struct, os, datetime
from ctypes import wintypes

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
# EDIT PER MACHINE: point these at your SADK.exe and its containing bin\ directory.
GAME     = r"<PATH TO YOUR SADK.exe>"            # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin\SADK.exe"
GAME_CWD = r"<PATH TO YOUR SADK.exe bin DIR>"    # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin"

# Parse args: an optional float (attach delay) and an optional --no-hooks flag.
ATTACH_DELAY = 8.0          # seconds; let SecuROM's startup anti-debug finish
HOOKS_ENABLED = True
for _arg in sys.argv[1:]:
    if _arg == "--no-hooks":
        HOOKS_ENABLED = False
    else:
        try:
            ATTACH_DELAY = float(_arg)
        except ValueError:
            pass

TRACE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.out")

# tincat3 loaded at 0x10000000 this session (un-rebased). We also resolve the
# real base from LOAD_DLL_DEBUG_EVENT and rebase the hook if it differs.
TINCAT3_ASSUMED_BASE = 0x10000000
CREATECOMMLAYER_RVA  = 0x10018C20 - 0x10000000   # = 0x18C20

# Hooks are filled in at runtime once we know module bases (see build_hooks()).
# Each entry: name -> {"addr": int, "orig": int|None, "installed": bool, "log": callable}

# --------------------------------------------------------------------------
# Win32 plumbing (mirrors debugger_loader.py + adds memory/context calls)
# --------------------------------------------------------------------------
DBG_CONTINUE              = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT     = 1
CREATE_PROCESS_DEBUG_EVENT= 3
LOAD_DLL_DEBUG_EVENT      = 6
EXIT_PROCESS_DEBUG_EVENT  = 5
EXCEPTION_BREAKPOINT      = 0x80000003
EXCEPTION_SINGLE_STEP     = 0x80000004

PROCESS_ALL_ACCESS        = 0x001F0FFF
TRAP_FLAG                 = 0x100        # EFlags TF

# WOW64_CONTEXT flags (i386 values; identical numeric meaning to CONTEXT_*).
WOW64_CONTEXT_i386            = 0x00010000
WOW64_CONTEXT_CONTROL         = WOW64_CONTEXT_i386 | 0x00000001
WOW64_CONTEXT_INTEGER         = WOW64_CONTEXT_i386 | 0x00000002
WOW64_CONTEXT_FULL            = WOW64_CONTEXT_i386 | 0x00000007
WOW64_CONTEXT_ALL             = WOW64_CONTEXT_i386 | 0x0000003F

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:
    sys.stdout.reconfigure(line_buffering=True)   # flush per line even when redirected to a file
except Exception:
    pass


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


# WOW64_FLOATING_SAVE_AREA + WOW64_CONTEXT (i386 layout) -- needed to read/write
# EIP/ESP/EFlags of the 32-bit target from this 64-bit Python debugger.
class WOW64_FLOATING_SAVE_AREA(ctypes.Structure):
    _fields_ = [("ControlWord", wintypes.DWORD), ("StatusWord", wintypes.DWORD),
                ("TagWord", wintypes.DWORD), ("ErrorOffset", wintypes.DWORD),
                ("ErrorSelector", wintypes.DWORD), ("DataOffset", wintypes.DWORD),
                ("DataSelector", wintypes.DWORD), ("RegisterArea", ctypes.c_ubyte * 80),
                ("Cr0NpxState", wintypes.DWORD)]


class WOW64_CONTEXT(ctypes.Structure):
    _fields_ = [("ContextFlags", wintypes.DWORD),
                ("Dr0", wintypes.DWORD), ("Dr1", wintypes.DWORD),
                ("Dr2", wintypes.DWORD), ("Dr3", wintypes.DWORD),
                ("Dr6", wintypes.DWORD), ("Dr7", wintypes.DWORD),
                ("FloatSave", WOW64_FLOATING_SAVE_AREA),
                ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
                ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
                ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD),
                ("Ebx", wintypes.DWORD), ("Edx", wintypes.DWORD),
                ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
                ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD),
                ("SegCs", wintypes.DWORD), ("EFlags", wintypes.DWORD),
                ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
                ("ExtendedRegisters", ctypes.c_ubyte * 512)]


# argtypes for the calls we add (defensive; ctypes defaults to int otherwise)
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype  = wintypes.HANDLE
k32.OpenThread.argtypes  = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenThread.restype   = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.FlushInstructionCache.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t]
k32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
THREAD_GET_CONTEXT  = 0x0008
THREAD_SET_CONTEXT  = 0x0010
THREAD_QUERY_INFO   = 0x0040
THREAD_HOOK_ACCESS  = THREAD_GET_CONTEXT | THREAD_SET_CONTEXT | THREAD_QUERY_INFO

# Wow64* may be absent on a 32-bit OS; resolve defensively.
HAVE_WOW64 = hasattr(k32, "Wow64GetThreadContext")
if HAVE_WOW64:
    k32.Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
    k32.Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]

# psapi!GetMappedFileNameW -- identify a loaded module by its mapped file path
# (works for the 32-bit ws2_32.dll inside the WOW64 target; we can then parse
# THAT module's 32-bit export table to find connect()'s real address).
try:
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _GetMappedFileNameW = _psapi.GetMappedFileNameW
except OSError:
    # On modern Windows the export also lives in kernel32/kernelbase.
    _GetMappedFileNameW = getattr(k32, "GetMappedFileNameW", None)
if _GetMappedFileNameW is not None:
    _GetMappedFileNameW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    wintypes.LPWSTR, wintypes.DWORD]
    _GetMappedFileNameW.restype  = wintypes.DWORD


# --------------------------------------------------------------------------
# logging (stdout + file, timestamped)
# --------------------------------------------------------------------------
_trace_fh = None

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    if _trace_fh is not None:
        try:
            _trace_fh.write(line + "\n"); _trace_fh.flush()
        except Exception:
            pass


# --------------------------------------------------------------------------
# target memory helpers
# --------------------------------------------------------------------------
def rpm(hproc, addr, size):
    """ReadProcessMemory -> bytes, or None on failure."""
    buf = (ctypes.c_ubyte * size)()
    got = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
    if not ok or got.value != size:
        return None
    return bytes(buf)


def wpm(hproc, addr, data):
    """WriteProcessMemory; returns True on success."""
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    wrote = ctypes.c_size_t(0)
    ok = k32.WriteProcessMemory(hproc, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(wrote))
    return bool(ok) and wrote.value == len(data)


def read_u32(hproc, addr):
    b = rpm(hproc, addr, 4)
    return None if b is None else struct.unpack_from("<I", b, 0)[0]


def read_cstr(hproc, addr, maxlen=256):
    """Read a NUL-terminated ASCII/UTF-8 string from the target (best effort)."""
    if not addr:
        return None
    out = bytearray()
    chunk_addr = addr
    while len(out) < maxlen:
        chunk = rpm(hproc, chunk_addr, 32)
        if chunk is None:
            break
        nul = chunk.find(b"\x00")
        if nul >= 0:
            out += chunk[:nul]
            break
        out += chunk
        chunk_addr += 32
    try:
        return out.decode("utf-8", "replace")
    except Exception:
        return repr(bytes(out))


def mapped_file_name(hproc, base):
    """psapi!GetMappedFileNameW(base) -> lowercased device path, or '' on failure."""
    if _GetMappedFileNameW is None or not base:
        return ""
    buf = ctypes.create_unicode_buffer(260)
    n = _GetMappedFileNameW(hproc, ctypes.c_void_p(base), buf, 260)
    return buf.value.lower() if n else ""


def export_rva_from_target(hproc, base, want_name):
    """Parse a 32-bit module's PE export directory IN THE TARGET and return the
    RVA of `want_name` (bytes), or None. Pure ReadProcessMemory; no assumptions
    about our own process's copy of the DLL."""
    try:
        dos = rpm(hproc, base, 0x40)
        if dos is None or dos[:2] != b"MZ":
            return None
        e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
        # PE header: Signature(4) + FileHeader(20). OptionalHeader starts at +24.
        # Export Directory is data-directory[0]; its RVA sits at OptionalHeader+96
        # for PE32 (IMAGE_OPTIONAL_HEADER32). Read enough to cover it.
        opt = rpm(hproc, base + e_lfanew, 0x78 + 8)
        if opt is None or opt[:4] != b"PE\x00\x00":
            return None
        magic = struct.unpack_from("<H", opt, 24)[0]
        if magic != 0x10B:          # 0x10B = PE32 (32-bit); we only expect this
            return None
        exp_rva = struct.unpack_from("<I", opt, 24 + 96)[0]
        if not exp_rva:
            return None
        # IMAGE_EXPORT_DIRECTORY (40 bytes): NumberOfNames@24, AddressOfFunctions@28,
        # AddressOfNames@32, AddressOfNameOrdinals@36.
        exp = rpm(hproc, base + exp_rva, 40)
        if exp is None:
            return None
        n_names      = struct.unpack_from("<I", exp, 24)[0]
        addr_funcs   = struct.unpack_from("<I", exp, 28)[0]
        addr_names   = struct.unpack_from("<I", exp, 32)[0]
        addr_ords    = struct.unpack_from("<I", exp, 36)[0]
        want = want_name if isinstance(want_name, bytes) else want_name.encode()
        for i in range(n_names):
            name_rva = read_u32(hproc, base + addr_names + 4 * i)
            if name_rva is None:
                continue
            nm = read_cstr(hproc, base + name_rva, 64)
            if nm is None:
                continue
            if nm.encode() == want:
                ordb = rpm(hproc, base + addr_ords + 2 * i, 2)
                if ordb is None:
                    return None
                ordinal = struct.unpack_from("<H", ordb, 0)[0]
                func_rva = read_u32(hproc, base + addr_funcs + 4 * ordinal)
                return func_rva
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# breakpoint install / re-arm
# --------------------------------------------------------------------------
def install_bp(hproc, hook):
    """Read original byte and write 0xCC. Returns True if installed."""
    orig = rpm(hproc, hook["addr"], 1)
    if orig is None:
        log(f"[warn] cannot read byte at {hook['name']} @ {hook['addr']:#010x} -- hook DISABLED")
        return False
    if orig[0] == 0xCC:
        # Already an INT3 there (shouldn't happen on a fresh attach) -- don't
        # clobber, just record and treat as installed so we still log hits.
        log(f"[warn] {hook['name']} @ {hook['addr']:#010x} already 0xCC -- assuming installed")
        hook["orig"] = 0xCC
        hook["installed"] = True
        return True
    hook["orig"] = orig[0]
    if not wpm(hproc, hook["addr"], b"\xCC"):
        log(f"[warn] cannot write 0xCC at {hook['name']} @ {hook['addr']:#010x} -- hook DISABLED")
        return False
    k32.FlushInstructionCache(hproc, ctypes.c_void_p(hook["addr"]), 1)
    hook["installed"] = True
    log(f"[hook] armed {hook['name']} @ {hook['addr']:#010x} (orig byte {hook['orig']:#04x})")
    return True


def restore_byte(hproc, hook):
    if hook.get("orig") is None or hook["orig"] == 0xCC:
        return
    wpm(hproc, hook["addr"], bytes([hook["orig"]]))
    k32.FlushInstructionCache(hproc, ctypes.c_void_p(hook["addr"]), 1)


def rearm_byte(hproc, hook):
    if hook.get("orig") is None or hook["orig"] == 0xCC:
        return
    wpm(hproc, hook["addr"], b"\xCC")
    k32.FlushInstructionCache(hproc, ctypes.c_void_p(hook["addr"]), 1)


def get_ctx(hthread):
    """Read the 32-bit context of the WOW64 target. Returns WOW64_CONTEXT or None."""
    ctx = WOW64_CONTEXT()
    ctx.ContextFlags = WOW64_CONTEXT_CONTROL | WOW64_CONTEXT_INTEGER
    if HAVE_WOW64 and k32.Wow64GetThreadContext(hthread, ctypes.byref(ctx)):
        return ctx
    return None


def set_ctx(hthread, ctx):
    ctx.ContextFlags = WOW64_CONTEXT_CONTROL | WOW64_CONTEXT_INTEGER
    return bool(HAVE_WOW64 and k32.Wow64SetThreadContext(hthread, ctypes.byref(ctx)))


# --------------------------------------------------------------------------
# per-hit loggers (args are read off the 32-bit stack at [esp+4], [esp+8], ...)
# stdcall/cdecl both put args there on entry; ret-addr is at [esp].
# --------------------------------------------------------------------------
def stack_arg(hproc, esp, index):
    """index 1 = first arg at [esp+4], etc."""
    return read_u32(hproc, esp + 4 * index)


def _hx(v, width=0):
    """Format an optional int as hex (or '?')."""
    if v is None:
        return "?"
    return f"{v:#0{width}x}" if width else f"{v:#x}"


def log_createcommlayer(hproc, esp):
    # TinCat_CreateCommLayer(arg1, magic=arg2, arg3, addr_ptr=arg4, ...)
    a1       = stack_arg(hproc, esp, 1)
    magic    = stack_arg(hproc, esp, 2)
    a3       = stack_arg(hproc, esp, 3)
    addr_ptr = stack_arg(hproc, esp, 4)
    addr_str = read_cstr(hproc, addr_ptr) if addr_ptr else None
    log(f'[CreateCommLayer] magic={_hx(magic, 10)} addr="{addr_str}" '
        f'(arg1={_hx(a1)} arg3={_hx(a3)} addr_ptr={_hx(addr_ptr, 10)})')


def log_connect(hproc, esp):
    # connect(SOCKET s=arg1, const sockaddr* name=arg2, int namelen=arg3)
    sa_ptr = stack_arg(hproc, esp, 2)
    if not sa_ptr:
        log("[connect]         -> (could not read sockaddr ptr)")
        return
    sa = rpm(hproc, sa_ptr, 16)
    if sa is None:
        log(f"[connect]         -> (could not read sockaddr @ {sa_ptr:#010x})")
        return
    fam = struct.unpack_from("<H", sa, 0)[0]
    port = struct.unpack_from(">H", sa, 2)[0]          # sin_port is BIG-ENDIAN
    ip = ".".join(str(b) for b in sa[4:8])             # sin_addr (network order = printable order)
    fam_s = "AF_INET" if fam == 2 else f"af={fam}"
    log(f"[connect]         -> {ip}:{port}  ({fam_s})")


# --------------------------------------------------------------------------
# hook table builder
# --------------------------------------------------------------------------
def resolve_connect_addr(hproc, ws2_base):
    """Resolve ws2_32!connect IN THE TARGET.

    NOTE: the debugger here is 64-bit Python but the target SADK.exe is 32-bit
    (WOW64), so they do NOT share a ws2_32 base -- we must read the target's
    own 32-bit ws2_32.dll export table. ws2_base is that DLL's base as seen in
    LOAD_DLL_DEBUG_EVENT."""
    if not ws2_base:
        log("[warn] ws2_32 base unknown (no LOAD_DLL event seen yet) -- connect hook deferred")
        return None
    rva = export_rva_from_target(hproc, ws2_base, b"connect")
    if rva is None:
        log(f"[warn] could not find 'connect' export in target ws2_32 @ {ws2_base:#010x} "
            f"-- connect hook DISABLED")
        return None
    return ws2_base + rva


# --------------------------------------------------------------------------
# main debug loop -- IDENTICAL pass-through behaviour to debugger_loader.py,
# with our own INT3 handling layered on top (only for our two addresses).
# --------------------------------------------------------------------------
def main():
    global _trace_fh
    try:
        _trace_fh = open(TRACE_FILE, "a", encoding="utf-8")
        _trace_fh.write("\n" + "=" * 70 + "\n")
    except Exception as e:
        print(f"[warn] cannot open trace file {TRACE_FILE}: {e} (stdout only)")

    log(f"=== debugger_trace.py start (hooks={'ON' if HOOKS_ENABLED else 'OFF'}, "
        f"delay={ATTACH_DELAY:g}s) ===")
    log(f"trace file: {TRACE_FILE}")

    si = STARTUPINFO(); si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
        wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
    if not k32.CreateProcessW(GAME, None, None, None, False, 0, None, GAME_CWD,
                              ctypes.byref(si), ctypes.byref(pi)):
        log(f"[!] CreateProcess failed: {ctypes.get_last_error()} (run me ELEVATED)"); return 1
    pid = pi.dwProcessId
    k32.CloseHandle(pi.hThread); k32.CloseHandle(pi.hProcess)
    log(f"[+] launched SADK pid={pid}; letting SecuROM start ({ATTACH_DELAY:g}s)...")
    time.sleep(ATTACH_DELAY)

    if not k32.DebugActiveProcess(pid):
        log(f"[!] DebugActiveProcess failed: {ctypes.get_last_error()}"); return 2
    k32.DebugSetProcessKillOnExit(False)        # game survives if we detach
    log(f"[+] attached pid={pid}. Passing faults to SecuROM's VEH. KEEP THIS OPEN. (Ctrl+C to stop)")

    # Process handle for memory r/w (the debug events also give us one, but a
    # dedicated handle is simplest and the loop already owns the process).
    hproc = k32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not hproc and HOOKS_ENABLED:
        log(f"[warn] OpenProcess failed: {ctypes.get_last_error()} -- hooks DISABLED, "
            f"falling back to pure pass-through loader")

    # state
    hooks_by_addr = {}               # addr -> hook dict (only installed ones)
    installed_names = set()          # which hooks we've already armed
    tincat3_base = None              # set when tincat3.dll loads
    ws2_base = None                  # set when ws2_32.dll loads (the target's 32-bit copy)
    consumed_attach_bp = False
    passed = 0
    pending_rearm = {}               # tid -> hook dict awaiting its single-step

    def _arm(h):
        if install_bp(hproc, h):
            hooks_by_addr[h["addr"]] = h
        installed_names.add(h["name"])   # mark attempted either way -> don't retry

    def try_build_and_install():
        """Arm each breakpoint as soon as the module it lives in is mapped.
        Independent per hook so a missing ws2_32 never blocks the
        TinCat_CreateCommLayer hook (and vice-versa). Safe to call repeatedly."""
        if not (HOOKS_ENABLED and hproc):
            return
        if tincat3_base is not None and "TinCat_CreateCommLayer" not in installed_names:
            cc_addr = tincat3_base + CREATECOMMLAYER_RVA
            _arm({"name": "TinCat_CreateCommLayer", "addr": cc_addr,
                  "orig": None, "installed": False, "log": log_createcommlayer})
        if ws2_base is not None and "ws2_32!connect" not in installed_names:
            conn = resolve_connect_addr(hproc, ws2_base)
            if conn is not None:
                _arm({"name": "ws2_32!connect", "addr": conn,
                      "orig": None, "installed": False, "log": log_connect})
            else:
                installed_names.add("ws2_32!connect")   # resolved-as-failed; stop retrying

    def note_module(base):
        """Identify a freshly-loaded module by mapped file name and record the
        bases we care about. Cheap; only does name lookup for unknown bases."""
        nonlocal tincat3_base, ws2_base
        if base == 0:
            return
        name = mapped_file_name(hproc, base) if hproc else ""
        if tincat3_base is None and (name.endswith("\\tincat3.dll") or base == TINCAT3_ASSUMED_BASE):
            tincat3_base = base
            log(f"[hook] tincat3.dll mapped @ {base:#010x}")
        if ws2_base is None and name.endswith("\\ws2_32.dll"):
            ws2_base = base
            log(f"[hook] ws2_32.dll mapped @ {base:#010x}")

    de = DEBUG_EVENT()
    while True:
        if not k32.WaitForDebugEvent(ctypes.byref(de), 0xFFFFFFFF):
            log(f"[!] WaitForDebugEvent failed: {ctypes.get_last_error()}"); break
        code = de.dwDebugEventCode
        status = DBG_CONTINUE

        if code == LOAD_DLL_DEBUG_EVENT:
            # LOAD_DLL_DEBUG_INFO: { HANDLE hFile; LPVOID lpBaseOfDll; ... }.
            # On an x64 debugger the struct begins with a 64-bit handle, so
            # lpBaseOfDll is at offset 8 (also 64-bit). The WOW64 target's
            # modules live in the low 4 GB, so masking to 32 bits is safe.
            base = struct.unpack_from("<Q", bytes(de.u), 8)[0] & 0xFFFFFFFF
            note_module(base)
            try_build_and_install()

        elif code == EXCEPTION_DEBUG_EVENT:
            exc_code = struct.unpack_from("<I", bytes(de.u), 0)[0]
            # EXCEPTION_RECORD: ExceptionCode@0, Flags@4, Record*@8, Address@12 (32-bit ptr)
            exc_addr = struct.unpack_from("<I", bytes(de.u), 12)[0]
            tid = de.dwThreadId

            if exc_code == EXCEPTION_BREAKPOINT and exc_addr in hooks_by_addr:
                # --- OUR breakpoint fired -------------------------------------
                hook = hooks_by_addr[exc_addr]
                hthread = k32.OpenThread(THREAD_HOOK_ACCESS, False, tid)
                if hthread:
                    ctx = get_ctx(hthread)
                    if ctx is not None:
                        # log args from the stack (esp valid on function entry)
                        try:
                            hook["log"](hproc, ctx.Esp)
                        except Exception as e:
                            log(f"[warn] logger for {hook['name']} raised: {e}")
                        # re-arm: restore byte, rewind EIP to bp, set trap flag so
                        # the CPU steps off the original instruction, then we
                        # rewrite 0xCC on the following EXCEPTION_SINGLE_STEP.
                        restore_byte(hproc, hook)
                        ctx.Eip = exc_addr
                        ctx.EFlags |= TRAP_FLAG
                        if set_ctx(hthread, ctx):
                            pending_rearm[tid] = hook
                        else:
                            # couldn't set TF: best effort, re-arm immediately.
                            rearm_byte(hproc, hook)
                            log(f"[warn] SetThreadContext failed for {hook['name']}; "
                                f"re-armed without single-step (may miss reentry)")
                    else:
                        log(f"[warn] Wow64GetThreadContext failed at {hook['name']}; "
                            f"leaving INT3 in place (one hit only)")
                    k32.CloseHandle(hthread)
                else:
                    log(f"[warn] OpenThread({tid}) failed at {hook['name']}: "
                        f"{ctypes.get_last_error()}")
                # Our INT3 is consumed by us -> DBG_CONTINUE (do NOT pass to app).
                status = DBG_CONTINUE

            elif exc_code == EXCEPTION_SINGLE_STEP and tid in pending_rearm:
                # --- our single-step after stepping off a restored bp --------
                hook = pending_rearm.pop(tid)
                rearm_byte(hproc, hook)
                # TF is auto-cleared by the CPU after the single step; nothing else.
                status = DBG_CONTINUE

            elif exc_code == EXCEPTION_BREAKPOINT and not consumed_attach_bp:
                consumed_attach_bp = True            # the system's attach breakpoint -> eat it
                status = DBG_CONTINUE
                # By now ALL synthetic LOAD_DLL events for already-mapped modules
                # have been delivered. Last-resort fallback: if module-name
                # resolution failed but the known tincat3 base is readable, arm
                # the CreateCommLayer hook there anyway (conservative: only if we
                # can read an MZ-less code byte; install_bp itself guards reads).
                if (HOOKS_ENABLED and hproc and tincat3_base is None
                        and "TinCat_CreateCommLayer" not in installed_names):
                    log(f"[hook] tincat3 not identified by name; falling back to "
                        f"assumed base {TINCAT3_ASSUMED_BASE:#010x}")
                    tincat3_base = TINCAT3_ASSUMED_BASE
                    try_build_and_install()

            else:
                # EVERYTHING ELSE -> the app's VEH (SecuROM). UNCHANGED behaviour.
                status = DBG_EXCEPTION_NOT_HANDLED
                passed += 1
                if passed <= 15 or passed % 250 == 0:
                    log(f"    passed fault #{passed}: code={exc_code:#010x} tid={tid}")

        elif code == CREATE_PROCESS_DEBUG_EVENT:
            # First chance to build hooks (tincat3 may load before/after; the
            # LOAD_DLL handler also tries). Harmless if it loads later.
            try_build_and_install()

        if code == EXIT_PROCESS_DEBUG_EVENT:
            k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, DBG_CONTINUE)
            log(f"[+] game exited. ({passed} faults passed)"); break
        k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, status)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n[+] stopped. (game keeps running, but will crash on its next SecuROM dispatch)")
