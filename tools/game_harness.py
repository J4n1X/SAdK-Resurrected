r"""
game_harness.py -- autonomous game-run/test harness for the SADK lobby-revival project.

WHAT THIS IS (Phase 0 + Phase 1 MVP of GAME_HARNESS_DESIGN.md):
  One command -- `python tools/game_harness.py run` -- that launches the sadk_lobby
  stub, launches SADK.exe under the PROVEN transparent debug loop, watches the
  client's LobbyManager state ladder via read-only ReadProcessMemory, classifies
  the outcome (PASS / FAIL_DISCONNECT / CRASH / FROZEN / FAIL_NOCLIENT / TIMEOUT),
  writes verdict.json, collects logs, and tears everything down. It turns the
  previously-manual "launch + watch + judge" loop into a single automated cycle an
  AI agent can drive.

DESIGN SOURCE: GAME_HARNESS_DESIGN.md (Phase 0 + Phase 1). This file is the ONLY
new file; it imports nothing from the other tools/ scripts but faithfully LIFTS:
  * tools/debugger_loader.py  -- the transparent debug loop (CreateProcess + sleep +
    DebugActiveProcess + WaitForDebugEvent/ContinueDebugEvent(DBG_EXCEPTION_NOT_HANDLED),
    eating only the attach BP). Reproduced BYTE-IDENTICALLY here on a daemon thread.
    WIN32 INVARIANT preserved: the SAME thread calls CreateProcess + DebugActiveProcess
    + WaitForDebugEvent + ContinueDebugEvent end-to-end. The orchestrator never touches
    those APIs; it only reads a thread-safe status dict.
  * tools/read_village_state.py -- the OpenProcess(VM_READ) + ReadProcessMemory machinery
    and the LobbyManager singleton resolution (@ 0x0088CEF0). Extended here with the
    state enum read at LobbyManager+0x57c (1=Disconnected .. 9=VillageEntered .. 12=
    ConnectionLost), which the design pins as the PRIMARY oracle.

CONSTRAINTS HONORED:
  * Pure-Win32 via ctypes; no third-party deps (matches the existing tools' style).
  * The MCP debugger is NOT used here (that is Phase 3).
  * Existing tools/ files are NOT modified -- only this file is added.
  * Read-only RPM cannot crash the game and is safe ALONGSIDE the debugger (separate
    handle). DebugSetProcessKillOnExit(False) so the harness owns teardown via
    TerminateProcess.

ELEVATION: the user is disabling compat mode, so non-elevated is the target. The
harness still checks for and CLEARLY reports ACCESS_DENIED on attach / RPM (a
debugger cannot attach to a higher-integrity process; a VM_READ handle on an admin
process needs admin too) -> it tells you to relaunch elevated instead of silently
misreporting.

USAGE:
  python tools/game_harness.py run [--enter-delay N] [--timeout N] [--out DIR]
                                   [--game PATH] [--no-arm] [--attach-delay S]
  python tools/game_harness.py --help

NOTE: a full cycle requires the LIVE game; it cannot be exercised without SADK.exe
running on this machine. Lines that genuinely need a live run to validate are marked
with `# LIVE-VALIDATE:`.
"""
import argparse
import ctypes
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# Paths / fixtures
# ──────────────────────────────────────────────────────────────────────────────
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(TOOLS_DIR)

# Game location (same as debugger_loader.py). Overridable via --game / $SADK_EXE.
# EDIT PER MACHINE: set $SADK_EXE, pass --game, or replace the default placeholder below.
GAME_EXE_DEFAULT = r"<PATH TO YOUR SADK.exe>"  # e.g. r"...\Die Siedler - Aufbruch der Kulturen\bin\SADK.exe"
GAME = os.environ.get("SADK_EXE", GAME_EXE_DEFAULT)
GAME_CWD = os.path.dirname(GAME)

# Stub: launched as `python -m sadk_lobby` (per the design + the package's __main__).
STUB_MODULE = "sadk_lobby"
STUB_PORTS = (7070, 7071, 5479)  # lobby / UC / world (sadk_lobby.config)
STUB_LOG_NAME = "tincat_server.log"  # sadk_lobby.config.LOG_FILE basename (in REPO_DIR)

# Game logs land here when launched with -log_info -log_path (AGENTS.md §3/§10).
GAME_LOG_DIR = r"C:\tmp"
GAME_LOG_NAMES = ("commLayer.log", "LobbyComm.log", "comm.log")

# Default attach delay -- IDENTICAL to debugger_loader.py (let SecuROM's startup
# anti-debug finish before DebugActiveProcess).
ATTACH_DELAY_DEFAULT = 8.0

# ──────────────────────────────────────────────────────────────────────────────
# LobbyManager state ladder (the oracle). SOURCEMAP.md / GAME_HARNESS_DESIGN.md §4.
# Singleton ptr @ ABSOLUTE 0x0088CEF0 (SADK.exe base 0x400000, no ASLR rebase 1:1).
# state enum byte @ LobbyManager+0x57c.
# ──────────────────────────────────────────────────────────────────────────────
LOBBY_MGR = 0x0088CEF0          # singleton pointer (matches read_village_state.py)
STATE_OFFSET = 0x57C            # +0x57c = LobbyManagerState byte

STATE_NAMES = {
    1: "Disconnected",
    2: "Connecting",
    3: "Authorized",
    4: "Authorizing",
    5: "LoggingIn",
    6: "LoadingGlobalData",
    7: "GlobalDataLoaded",      # == reached char-select
    8: "EnteringVillage",
    9: "VillageEntered",        # == PASS (entered the 3D world)
    10: "RoomLogin",
    11: "VillageLeft",
    12: "ConnectionLost",       # == FAIL (latched; SetState latches at 12)
}
STATE_MIN, STATE_MAX = 1, 12    # offset-drift guard: trust the byte only if in 1..12

STATE_REACHED_CHARSELECT = 7
STATE_ENTERED_WORLD = 9
STATE_CONNECTION_LOST = 12

# ──────────────────────────────────────────────────────────────────────────────
# Win32 plumbing (ctypes) -- shared by all controllers.
# ──────────────────────────────────────────────────────────────────────────────
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# --- debug-loop constants (verbatim from debugger_loader.py) ---
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT = 1
EXIT_PROCESS_DEBUG_EVENT = 5
EXCEPTION_BREAKPOINT = 0x80000003

# --- process / handle constants ---
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259

# SendMessageTimeout (freeze probe)
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002


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


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


# Bind the few prototypes that need non-default arg/restypes (rest default to int).
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.CreateProcessW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION)]
k32.OpenProcess.restype = wintypes.HANDLE
k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]


def _now():
    return time.monotonic()


def _iso():
    return datetime.now().isoformat(timespec="milliseconds")


# ──────────────────────────────────────────────────────────────────────────────
# Process helpers (find / kill stale SADK.exe; free ports)
# ──────────────────────────────────────────────────────────────────────────────
def find_pids(name="SADK.exe"):
    """Enumerate PIDs of processes whose image == `name` (from read_village_state.py)."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32()
    e.dwSize = ctypes.sizeof(e)
    pids = []
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.decode("ascii", "ignore").lower() == name.lower():
                pids.append(e.th32ProcessID)
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return pids


PROCESS_TERMINATE = 0x0001


def kill_pid(pid, exit_code=0):
    h = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    ok = bool(k32.TerminateProcess(h, exit_code))
    k32.CloseHandle(h)
    return ok


def kill_stale_game(name="SADK.exe"):
    """Kill any pre-existing SADK.exe so the single-instance lock can't make our
    CreateProcess "succeed" into a dead instance (design §5.2 PREP)."""
    killed = []
    for pid in find_pids(name):
        if kill_pid(pid):
            killed.append(pid)
    if killed:
        # Give the OS a beat to release the single-instance mutex + sockets.
        time.sleep(1.0)
    return killed


def port_in_use(port, host="127.0.0.1"):
    """True if something is already LISTENING on `port` (a connect succeeds)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.25)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_ports_free(ports, timeout=8.0):
    """Best-effort wait for `ports` to be free. We don't own the PIDs binding them
    (the stub uses SO_REUSEADDR), so we kill stale SADK first and then just confirm.
    Returns the list of ports still in use after the wait."""
    deadline = _now() + timeout
    while _now() < deadline:
        busy = [p for p in ports if port_in_use(p)]
        if not busy:
            return []
        time.sleep(0.4)
    return [p for p in ports if port_in_use(p)]


# ──────────────────────────────────────────────────────────────────────────────
# 1. StubController -- start/stop `python -m sadk_lobby`, tee its output + log,
#    expose recent milestones (handshake, 207, 170, 211-214, EnterWorld 1000).
# ──────────────────────────────────────────────────────────────────────────────
# Milestone regexes matched against the stub's stdout AND tincat_server.log. The
# exact strings are taken verbatim from sadk_lobby (server.py / dispatch.py /
# village.py) -- see each comment for the source line.
STUB_MILESTONES = [
    ("listening", re.compile(r"listening on port\s+7070")),          # server.py _banner/_make_listener
    ("connection", re.compile(r"CONNECTION #")),                      # connection.py banner
    ("handshake", re.compile(r"HandShakeConnected")),                 # dispatch handshake (type 5)
    ("session_key_207", re.compile(r"SessionKey \(207\)")),           # dispatch _h_auth
    ("serverlist_170", re.compile(r"ServerList\(type=")),             # dispatch _h_request_servers
    ("village_injected", re.compile(r"Injected fake village world")), # dispatch FAKE_VILLAGE
    ("token_212", re.compile(r"AckValidateTokenSession \(212\)")),    # dispatch _h_start_token
    ("token_214", re.compile(r"ValidateToken \(214\)")),              # dispatch _h_send_token
    ("village_conn", re.compile(r"\[VILLAGE\] connection opened")),    # connection.py is_village
    ("enter_scheduled", re.compile(r"scheduling EnterWorld\(1000\)")),  # village.schedule_enter_world
    ("enter_sent", re.compile(r"sent EnterWorld\(1000\)")),           # village._send (the push)
    ("enter_disarmed", re.compile(r"EnterWorld\(1000\) not pushed")), # dispatch (ARM_ENTER_WORLD False)
]


class StubController:
    """Runs `python -m sadk_lobby` as a child process; tees its stdout to an
    in-memory ring + a per-run file, and ALSO tails tincat_server.log. Exposes
    milestone detection for the wire-side view of how far the conversation got."""

    def __init__(self, out_dir, log_path=None, arm_enter_world=True, enter_delay=2.0,
                 python_exe=None):
        self.out_dir = out_dir
        # The stub truncates its log on start (server.py opens it "w"); we point it
        # at a per-run file so runs don't cross-contaminate (design §5.2).
        self.log_path = log_path or os.path.join(out_dir, STUB_LOG_NAME)
        self.arm_enter_world = arm_enter_world
        self.enter_delay = enter_delay
        self.python_exe = python_exe or sys.executable
        self.proc = None
        self._reader = None
        self._lines = []            # tee of stub stdout (ring-buffered)
        self._lines_lock = threading.Lock()
        self._stdout_path = os.path.join(out_dir, "stub_stdout.log")
        self._stdout_fh = None
        self._milestones = {}       # name -> first ISO timestamp seen

    # -- lifecycle ------------------------------------------------------------
    def start(self, wait_listen=10.0):
        os.makedirs(self.out_dir, exist_ok=True)
        env = dict(os.environ)
        # config.py reads these knobs at import time, but only ADVERTISE_IP from env.
        # ARM_ENTER_WORLD / ENTER_WORLD_DELAY are module constants -> we override them
        # via a tiny `-c` bootstrap that patches config BEFORE server.main() runs, so
        # the harness controls the auto-push without editing the repo (design constraint).
        boot = (
            "import runpy, sadk_lobby.config as c;"
            f"c.ARM_ENTER_WORLD={bool(self.arm_enter_world)!r};"
            f"c.ENTER_WORLD_DELAY=float({self.enter_delay!r});"
            "import sadk_lobby.server as s;"
            f"s.main(['--log', {self.log_path!r}])"
        )
        self._stdout_fh = open(self._stdout_path, "w", encoding="utf-8", errors="replace")
        # PYTHONUNBUFFERED so we see the stub's prints promptly through the pipe.
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [self.python_exe, "-c", boot],
            cwd=REPO_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=1,
            universal_newlines=True,
        )
        self._reader = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader.start()
        ok = self.wait_for("listening", wait_listen)
        return ok

    def _pump_stdout(self):
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                with self._lines_lock:
                    self._lines.append(line)
                    if len(self._lines) > 4000:
                        self._lines = self._lines[-3000:]
                if self._stdout_fh:
                    try:
                        self._stdout_fh.write(line + "\n")
                        self._stdout_fh.flush()
                    except OSError:
                        pass
                self._scan_line(line)
        except Exception:
            pass

    def _scan_line(self, line):
        for name, rx in STUB_MILESTONES:
            if name not in self._milestones and rx.search(line):
                self._milestones[name] = _iso()

    # -- introspection --------------------------------------------------------
    def poll_logfile(self):
        """Also scan the on-disk tincat_server.log for milestones (belt + braces:
        the stub writes there even if a stdout line is dropped)."""
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
        except OSError:
            return
        for name, rx in STUB_MILESTONES:
            if name not in self._milestones and rx.search(data):
                self._milestones[name] = _iso()

    def milestones(self):
        self.poll_logfile()
        return dict(self._milestones)

    def saw(self, name):
        return name in self.milestones()

    def wait_for(self, name, timeout):
        deadline = _now() + timeout
        while _now() < deadline:
            if self.saw(name):
                return True
            if self.proc and self.proc.poll() is not None:
                return self.saw(name)
            time.sleep(0.2)
        return self.saw(name)

    def log_tail(self, n=120):
        """Last n lines of the stub log (for the verdict artifact)."""
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            return lines[-n:]
        except OSError:
            with self._lines_lock:
                return list(self._lines[-n:])

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
        if self._stdout_fh:
            try:
                self._stdout_fh.flush()
                self._stdout_fh.close()
            except OSError:
                pass
            self._stdout_fh = None


# ──────────────────────────────────────────────────────────────────────────────
# 2. GameController -- the transparent debug loop on a daemon thread.
#    LIFTED BYTE-IDENTICALLY from tools/debugger_loader.py. The Win32 invariant is
#    preserved: the worker thread alone calls CreateProcess + DebugActiveProcess +
#    WaitForDebugEvent + ContinueDebugEvent. The orchestrator only reads `status`.
# ──────────────────────────────────────────────────────────────────────────────
class GameController:
    def __init__(self, game=GAME, game_cwd=None, attach_delay=ATTACH_DELAY_DEFAULT,
                 log_path=None):
        self.game = game
        self.game_cwd = game_cwd or os.path.dirname(game)
        self.attach_delay = attach_delay
        self.log_path = log_path        # game -log_path dir (per-run C:\tmp\run_<id>)
        # Thread-safe status the orchestrator polls (design §2.1).
        self.status = {
            "pid": None,
            "attached": False,
            "exited": False,
            "exit_code": None,
            "fault_count": 0,
            "last_fault_code": None,
            "error": None,             # human-readable startup/attach failure
            "access_denied": False,    # ACCESS_DENIED on attach -> relaunch elevated
            "launched_at": None,
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._hProcess = None          # kept so the orchestrator can TerminateProcess

    # -- public API the orchestrator uses ------------------------------------
    def start(self):
        """Spawn the debug-pump thread. Returns once the PID is known (or it failed)."""
        self._thread = threading.Thread(target=self._run, name="sadk-debug-pump",
                                         daemon=True)
        self._thread.start()
        # Wait until the pump has CreateProcess'd (pid set) or errored.
        deadline = _now() + 30.0
        while _now() < deadline:
            with self._lock:
                if self.status["pid"] or self.status["error"]:
                    break
            time.sleep(0.05)
        return self.get()

    def get(self):
        with self._lock:
            return dict(self.status)

    @property
    def pid(self):
        return self.get()["pid"]

    def _set(self, **kw):
        with self._lock:
            self.status.update(kw)

    def _build_cmdline(self):
        """ANSI/Unicode command line. We pass the game args (-log_info -log_path DIR)
        via lpCommandLine so SADK writes commLayer.log/LobbyComm.log per run."""
        # CreateProcessW wants a MUTABLE buffer for lpCommandLine; argv[0] must be quoted.
        parts = [f'"{self.game}"']
        if self.log_path:
            # LIVE-VALIDATE: exact -log flag spelling is from AGENTS.md (-log_info
            # -log_path C:\tmp); confirm the game honors a per-run subdir and still
            # emits commLayer.log / LobbyComm.log there.
            parts += ["-log_info", "-log_path", self.log_path]
        return " ".join(parts)

    # -- the debug pump (SINGLE THREAD owns attach->loop, per Win32 rule) ------
    def _run(self):
        si = STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        cmdline = self._build_cmdline()
        cmd_buf = ctypes.create_unicode_buffer(cmdline)  # mutable for CreateProcessW
        # CreateProcessW(app=GAME, cmdline=buf, ... cwd=GAME_CWD) -- same call shape as
        # debugger_loader.py, but we pass a real command line so -log args take effect.
        if not k32.CreateProcessW(self.game, cmd_buf, None, None, False, 0, None,
                                  self.game_cwd, ctypes.byref(si), ctypes.byref(pi)):
            err = ctypes.get_last_error()
            self._set(error=f"CreateProcess failed: {err} "
                            f"(bad --game path, or run me ELEVATED if the EXE is admin-only)")
            return
        pid = pi.dwProcessId
        self._hProcess = pi.hProcess          # KEEP for TerminateProcess on teardown
        k32.CloseHandle(pi.hThread)
        self._set(pid=pid, launched_at=_iso())

        # Let SecuROM's startup anti-debug finish (IDENTICAL to debugger_loader.py).
        # We sleep in small slices so a stop request during the delay aborts promptly.
        slept = 0.0
        while slept < self.attach_delay and not self._stop.is_set():
            time.sleep(0.2)
            slept += 0.2
        if self._stop.is_set():
            return

        if not k32.DebugActiveProcess(pid):
            err = ctypes.get_last_error()
            denied = (err == ERROR_ACCESS_DENIED)
            self._set(error=f"DebugActiveProcess failed: {err}"
                            + (" -- relaunch the harness ELEVATED (cannot attach to a "
                               "higher-integrity process)" if denied else ""),
                      access_denied=denied)
            return
        k32.DebugSetProcessKillOnExit(False)   # game survives if we detach; harness owns kill
        self._set(attached=True)

        de = DEBUG_EVENT()
        consumed_attach_bp = False
        passed = 0
        while not self._stop.is_set():
            # 100ms wait so the stop flag is honored even when no events arrive.
            if not k32.WaitForDebugEvent(ctypes.byref(de), 100):
                # 121 = ERROR_SEM_TIMEOUT (no event in the window) -> loop & re-check stop.
                continue
            code = de.dwDebugEventCode
            status = DBG_CONTINUE
            if code == EXCEPTION_DEBUG_EVENT:
                exc_code = struct.unpack_from("<I", bytes(de.u), 0)[0]
                if exc_code == EXCEPTION_BREAKPOINT and not consumed_attach_bp:
                    consumed_attach_bp = True          # system attach breakpoint -> eat it
                else:
                    status = DBG_EXCEPTION_NOT_HANDLED  # everything else -> app VEH (SecuROM)
                    passed += 1
                    self._set(fault_count=passed, last_fault_code=exc_code)
            if code == EXIT_PROCESS_DEBUG_EVENT:
                # Exit code lives at offset 0 of the union for EXIT_PROCESS.
                ec = struct.unpack_from("<I", bytes(de.u), 0)[0]
                k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, DBG_CONTINUE)
                self._set(exited=True, exit_code=ec)
                return
            k32.ContinueDebugEvent(de.dwProcessId, de.dwThreadId, status)
        # stop requested: stop debugging but DO NOT kill (KillOnExit already False).
        with self._lock:
            cur_pid = self.status["pid"]
        if cur_pid:
            k32.DebugActiveProcessStop(cur_pid)

    # -- teardown -------------------------------------------------------------
    def terminate(self):
        """Stop the debug pump and explicitly TerminateProcess the game (design §5.3:
        because KillOnExit is False, stopping the loop alone won't kill a healthy game)."""
        self._stop.set()
        pid = self.pid
        # Terminate via the handle we kept (works even after DebugActiveProcessStop).
        if self._hProcess:
            k32.TerminateProcess(self._hProcess, 0)
        elif pid:
            kill_pid(pid)
        if self._thread:
            self._thread.join(timeout=6)
        if self._hProcess:
            k32.CloseHandle(self._hProcess)
            self._hProcess = None

    def is_alive(self):
        """True if the game process is still running (independent of the debug loop)."""
        st = self.get()
        if st["exited"]:
            return False
        pid = st["pid"]
        if not pid:
            return False
        # Cross-check via the OS in case the pump missed the exit event.
        return pid in find_pids(os.path.basename(self.game))


# ──────────────────────────────────────────────────────────────────────────────
# 3. StateProbe -- read-only RPM of the LobbyManager state enum. Reuses
#    read_village_state.py's OpenProcess(VM_READ)+RPM + the singleton resolution.
# ──────────────────────────────────────────────────────────────────────────────
class StateProbe:
    def __init__(self, pid):
        self.pid = pid
        self.h = None
        self.error = None
        self.access_denied = False
        self.history = []   # list of (iso, monotonic, state_int|None, name)

    def open(self):
        # Read-only handle; safe alongside the debugger (separate handle).
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.h:
            err = ctypes.get_last_error()
            self.access_denied = (err == ERROR_ACCESS_DENIED)
            self.error = (f"OpenProcess(VM_READ) failed: {err}"
                          + (" -- relaunch the harness ELEVATED (RPM on an admin process "
                             "needs admin)" if self.access_denied else ""))
            return False
        return True

    def _rpm(self, addr, size):
        buf = (ctypes.c_ubyte * size)()
        n = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
        return bytes(buf) if (ok and n.value == size) else None

    def _u32(self, addr):
        b = self._rpm(addr, 4)
        return None if b is None else int.from_bytes(b, "little")

    def _u8(self, addr):
        b = self._rpm(addr, 1)
        return None if b is None else b[0]

    def read_state(self):
        """Return {state, name, raw, ok, reason}. Offset-drift guard: only trust the
        byte if the singleton resolves AND state in 1..12 (design §4.3)."""
        if self.h is None and not self.open():
            return {"state": None, "name": None, "raw": None, "ok": False, "reason": self.error}
        lm = self._u32(LOBBY_MGR)
        if not lm:
            return {"state": None, "name": None, "raw": None, "ok": False,
                    "reason": "LobbyManager singleton null/unreadable (game not far enough, "
                              "or wrong build)"}
        raw = self._u8(lm + STATE_OFFSET)
        if raw is None:
            return {"state": None, "name": None, "raw": None, "ok": False,
                    "reason": "state byte unreadable"}
        if not (STATE_MIN <= raw <= STATE_MAX):
            # Out of range -> either a torn mid-update read or offset drift. Don't trust.
            return {"state": None, "name": None, "raw": raw, "ok": False,
                    "reason": f"state byte {raw} out of 1..12 (offset drift or mid-update)"}
        return {"state": raw, "name": STATE_NAMES.get(raw, f"#{raw}"),
                "raw": raw, "ok": True, "reason": None}

    def sample(self):
        """Take one reading, append to history, return the snapshot dict."""
        snap = self.read_state()
        self.history.append({
            "iso": _iso(), "t": round(_now(), 3),
            "state": snap["state"], "name": snap["name"], "ok": snap["ok"],
        })
        return snap

    def trace(self):
        """Compressed trace: only transitions (consecutive duplicates collapsed)."""
        out = []
        last = object()
        for h in self.history:
            key = (h["state"], h["ok"])
            if key != last:
                out.append(h)
                last = key
        return out

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


# ──────────────────────────────────────────────────────────────────────────────
# Freeze probe -- SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG) on the game window.
# ──────────────────────────────────────────────────────────────────────────────
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_top_window(pid):
    """First top-level visible window owned by `pid` (pid->hwnd). The SADK window
    class/title is discovered live rather than hardcoded (design §3.3)."""
    result = {"hwnd": None}

    def _cb(hwnd, lparam):
        wpid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            result["hwnd"] = hwnd
            return False  # stop
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return result["hwnd"]


def ui_responsive(pid, timeout_ms=2000):
    """True if the game's UI thread answers a WM_NULL within timeout_ms. Used to tell
    a legit PhysX world-load (still pumping) from a wedged UI (design §4.1/§5.3).
    Returns None if no window was found yet."""
    hwnd = find_top_window(pid)
    if not hwnd:
        return None  # LIVE-VALIDATE: confirm SADK exposes a top-level window pre-world.
    res = wintypes.DWORD(0)
    # SendMessageTimeoutW returns nonzero on success, 0 on timeout/hung.
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    ret = user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0, SMTO_ABORTIFHUNG,
                                     timeout_ms, ctypes.byref(res))
    return bool(ret)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Outcome classifier + the full cycle.
# ──────────────────────────────────────────────────────────────────────────────
VERDICT_PASS = "PASS"
VERDICT_FAIL_DISCONNECT = "FAIL_DISCONNECT"
VERDICT_CRASH = "CRASH"
VERDICT_FROZEN = "FROZEN"
VERDICT_FAIL_NOCLIENT = "FAIL_NOCLIENT"
VERDICT_TIMEOUT = "TIMEOUT"
VERDICT_ERROR = "ERROR"            # harness/setup failure (not a game result)


def collect_game_logs(dest_dir, src_dir):
    """Copy game logs (commLayer.log etc.) from C:\\tmp (or the per-run subdir) into
    the run folder. Returns the list of copied basenames."""
    copied = []
    if not os.path.isdir(src_dir):
        return copied
    for name in os.listdir(src_dir):
        low = name.lower()
        if low.endswith(".log") or low.startswith("logfile_") or low.endswith(".txt"):
            try:
                src = os.path.join(src_dir, name)
                if not os.path.isfile(src):
                    continue
                with open(src, "rb") as fi, open(os.path.join(dest_dir, name), "wb") as fo:
                    fo.write(fi.read())
                copied.append(name)
            except OSError:
                pass
    return copied


def run_cycle(args):
    """One full PREP->STUB->GAME->observe->classify->collect->teardown cycle."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out, run_id)
    os.makedirs(out_dir, exist_ok=True)
    # Per-run game-log dir under C:\tmp so runs don't cross-contaminate (design §5.2).
    game_log_dir = os.path.join(GAME_LOG_DIR, f"run_{run_id}")
    try:
        os.makedirs(game_log_dir, exist_ok=True)
    except OSError:
        game_log_dir = GAME_LOG_DIR  # fall back to C:\tmp root

    t0 = _now()
    timings = {}
    verdict = {
        "run_id": run_id,
        "started": _iso(),
        "verdict": None,
        "reason": None,
        "final_state": None,
        "final_state_name": None,
        "state_trace": [],
        "stub_milestones": {},
        "stub_log_tail": [],
        "game": {"pid": None, "exit_code": None, "fault_count": 0, "last_fault_code": None},
        "timings": timings,
        "artifacts": [],
        "config": {
            "game": args.game, "enter_delay": args.enter_delay,
            "arm_enter_world": not args.no_arm, "timeout": args.timeout,
            "attach_delay": args.attach_delay,
        },
    }

    def finish(v, reason, stub=None, game=None, probe=None):
        verdict["verdict"] = v
        verdict["reason"] = reason
        verdict["finished"] = _iso()
        timings["total_s"] = round(_now() - t0, 2)
        if stub is not None:
            verdict["stub_milestones"] = stub.milestones()
            verdict["stub_log_tail"] = stub.log_tail(150)
        if probe is not None:
            verdict["state_trace"] = probe.trace()
            last_ok = [h for h in probe.history if h["ok"]]
            if last_ok:
                verdict["final_state"] = last_ok[-1]["state"]
                verdict["final_state_name"] = last_ok[-1]["name"]
        if game is not None:
            gs = game.get()
            verdict["game"].update({
                "pid": gs["pid"], "exit_code": gs["exit_code"],
                "fault_count": gs["fault_count"], "last_fault_code":
                    (hex(gs["last_fault_code"]) if gs["last_fault_code"] is not None else None),
            })
        # collect logs
        copied = collect_game_logs(out_dir, game_log_dir)
        if game_log_dir != GAME_LOG_DIR:
            copied += collect_game_logs(out_dir, GAME_LOG_DIR)  # also grab root commLayer.log
        verdict["artifacts"] = sorted(set(copied)) + ["stub_stdout.log", STUB_LOG_NAME]
        # write verdict.json
        vpath = os.path.join(out_dir, "verdict.json")
        with open(vpath, "w", encoding="utf-8") as f:
            json.dump(verdict, f, indent=2)
        verdict["_verdict_path"] = vpath
        return verdict

    # ── 0. PREP ────────────────────────────────────────────────────────────
    print(f"[harness] run {run_id}: PREP (kill stale SADK.exe; free ports {STUB_PORTS})")
    killed = kill_stale_game(os.path.basename(args.game))
    if killed:
        print(f"[harness]   killed stale SADK.exe pid(s): {killed}")
    busy = wait_ports_free(STUB_PORTS, timeout=8.0)
    timings["prep_s"] = round(_now() - t0, 2)
    # Ports may be 'busy' simply because a previous stub is lingering; we start our own
    # stub next (SO_REUSEADDR), so a busy 7071/5479 isn't fatal. Only fail if 7070 is
    # held by something we can't displace AND our stub then fails to bind.

    # ── 1. STUB ──────────────────────────────────────────────────────────────
    stub = StubController(out_dir,
                          arm_enter_world=not args.no_arm,
                          enter_delay=args.enter_delay,
                          python_exe=args.python)
    print(f"[harness] STUB: launching `{STUB_MODULE}` (arm={not args.no_arm}, "
          f"enter_delay={args.enter_delay}s)")
    t_stub = _now()
    if not stub.start(wait_listen=12.0):
        # Could not confirm "listening on 7070" -> almost always a port-bind/permission
        # problem (server.py prints 'Run as Administrator' and exits on PermissionError).
        tail = stub.log_tail(40)
        stub.stop()
        return finish(VERDICT_ERROR,
                      "stub did not report 'listening on port 7070' (port bind / permission "
                      f"problem? busy_ports={busy}). Stub tail: {tail[-6:]}",
                      stub=stub)
    timings["stub_listen_s"] = round(_now() - t_stub, 2)
    print("[harness]   stub is listening.")

    # ── 2. GAME (debug loop on a thread) ─────────────────────────────────────
    game = GameController(game=args.game, attach_delay=args.attach_delay,
                          log_path=game_log_dir)
    print(f"[harness] GAME: launching SADK.exe under debug loop "
          f"(attach_delay={args.attach_delay}s)")
    gs = game.start()
    if gs.get("error"):
        stub.stop()
        return finish(VERDICT_ERROR, gs["error"], stub=stub, game=game)
    print(f"[harness]   SADK.exe pid={gs['pid']}; attaching after {args.attach_delay}s...")
    verdict["game"]["pid"] = gs["pid"]

    # ── 3-6. OBSERVE: poll the state ladder with a hard cap ──────────────────
    probe = StateProbe(gs["pid"])
    deadline = _now() + args.timeout
    enter_seen_at = None        # when stub pushed/scheduled 1000
    poll = 0.25
    try:
        while _now() < deadline:
            g = game.get()

            # CRASH: the debug pump saw EXIT_PROCESS before we reached state 9.
            if g["exited"]:
                last = probe.read_state() if probe.open() else {"state": None}
                if last.get("state") == STATE_ENTERED_WORLD:
                    return finish(VERDICT_PASS,
                                  "state 9 (VillageEntered) reached; process then exited",
                                  stub=stub, game=game, probe=probe)
                # Surface access-denied as ERROR, not CRASH.
                if probe.access_denied:
                    return finish(VERDICT_ERROR, probe.error, stub=stub, game=game, probe=probe)
                return finish(VERDICT_CRASH,
                              f"SADK.exe exited (code={g['exit_code']}) before reaching "
                              f"state 9; {g['fault_count']} SecuROM faults passed, last="
                              f"{hex(g['last_fault_code']) if g['last_fault_code'] else None}",
                              stub=stub, game=game, probe=probe)

            # Attach failure (e.g. ACCESS_DENIED) surfaced mid-poll.
            if g.get("error"):
                if g.get("access_denied"):
                    return finish(VERDICT_ERROR, g["error"], stub=stub, game=game, probe=probe)
                return finish(VERDICT_ERROR, g["error"], stub=stub, game=game, probe=probe)

            snap = probe.sample()
            if probe.access_denied:
                return finish(VERDICT_ERROR, probe.error, stub=stub, game=game, probe=probe)

            # Track the stub's auto-push moment to time the enter-world budget.
            ms = stub.milestones()
            if enter_seen_at is None and ("enter_sent" in ms or "enter_scheduled" in ms):
                enter_seen_at = _now()

            if snap["ok"]:
                st = snap["state"]
                # PASS
                if st == STATE_ENTERED_WORLD:
                    timings["enter_world_s"] = round(_now() - t0, 2)
                    return finish(VERDICT_PASS,
                                  "state 9 (VillageEntered) reached -- client entered the 3D world",
                                  stub=stub, game=game, probe=probe)
                # FAIL_DISCONNECT (latched at 12)
                if st == STATE_CONNECTION_LOST:
                    return finish(VERDICT_FAIL_DISCONNECT,
                                  "state 12 (ConnectionLost) -- token/handshake rejected or "
                                  "connection dropped",
                                  stub=stub, game=game, probe=probe)

            time.sleep(poll)
            poll = 0.25

        # ── DEADLINE hit: classify TIMEOUT vs FROZEN vs FAIL_NOCLIENT ────────
        ms = stub.milestones()
        # FAIL_NOCLIENT: the stub never even saw a client handshake -> config/binding.
        if "handshake" not in ms and "connection" not in ms:
            return finish(VERDICT_FAIL_NOCLIENT,
                          "deadline reached and the stub never saw a client handshake "
                          "(client config not pointing at the stub, or it never connected)",
                          stub=stub, game=game, probe=probe)
        # Distinguish FROZEN (UI wedged) from a slow load / stuck-but-pumping TIMEOUT.
        resp = ui_responsive(game.pid, timeout_ms=2000)  # None=no window, True/False
        last = probe.read_state()
        reason_state = (f"last trusted state={last.get('state')} "
                        f"({STATE_NAMES.get(last.get('state'), '?')})")
        if resp is False:
            return finish(VERDICT_FROZEN,
                          f"deadline reached, process alive but UI thread did not answer "
                          f"WM_NULL (SMTO_ABORTIFHUNG) -> wedged. {reason_state}",
                          stub=stub, game=game, probe=probe)
        return finish(VERDICT_TIMEOUT,
                      f"deadline ({args.timeout}s) reached; process alive, "
                      f"state<9 ({reason_state}); ui_responsive={resp}",
                      stub=stub, game=game, probe=probe)
    finally:
        # ── TEARDOWN: kill game, stop stub, confirm ports freed ──────────────
        print("[harness] TEARDOWN: terminating game + stub")
        try:
            probe.close()
        except Exception:
            pass
        try:
            game.terminate()
        except Exception:
            pass
        try:
            stub.stop()
        except Exception:
            pass
        # belt + braces: sweep any straggler + confirm ports
        kill_stale_game(os.path.basename(args.game))
        still = wait_ports_free(STUB_PORTS, timeout=5.0)
        if still:
            print(f"[harness]   WARNING: ports still in use after teardown: {still}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def _print_verdict(v):
    line = "=" * 64
    print("\n" + line)
    print(f" VERDICT: {v['verdict']}   (run {v['run_id']})")
    print(f" reason : {v['reason']}")
    if v.get("final_state") is not None:
        print(f" state  : {v['final_state']} ({v['final_state_name']})")
    g = v["game"]
    print(f" game   : pid={g['pid']} exit={g['exit_code']} "
          f"faults={g['fault_count']} last_fault={g['last_fault_code']}")
    ms = v.get("stub_milestones", {})
    print(f" stub   : {', '.join(sorted(ms)) if ms else '(no milestones)'}")
    print(f" written: {v.get('_verdict_path')}")
    print(line)


def cmd_run(args):
    # Elevation hint up-front (non-fatal): we target non-elevated, but if attach/RPM
    # is denied later, the classifier reports ERROR with a clear 'relaunch elevated'.
    v = run_cycle(args)
    # Machine-readable JSON to stdout (the agent reads this directly), then a summary.
    print("\n----- verdict.json -----")
    print(json.dumps({k: val for k, val in v.items() if not k.startswith("_")}, indent=2))
    _print_verdict(v)
    # Exit code: 0 only for PASS, so a CI/agent caller can gate on it.
    return 0 if v["verdict"] == VERDICT_PASS else 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="game_harness.py",
        description="Autonomous SADK launch->observe->classify test harness "
                    "(Phase 0 + Phase 1 MVP of GAME_HARNESS_DESIGN.md).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n"
               "  python tools/game_harness.py run --enter-delay 2.0 --timeout 180\n"
               "\nNote: a full cycle requires the live SADK.exe on this machine; it "
               "cannot be exercised without the game running.",
    )
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="run one full launch->observe->classify cycle")
    r.add_argument("--enter-delay", type=float, default=2.0,
                   help="seconds after the 214 token handshake before the stub pushes "
                        "EnterWorld(1000) (default: 2.0)")
    r.add_argument("--timeout", type=float, default=180.0,
                   help="hard cap for the whole observe phase in seconds (default: 180)")
    r.add_argument("--attach-delay", type=float, default=ATTACH_DELAY_DEFAULT,
                   help=f"seconds to let SecuROM start before DebugActiveProcess "
                        f"(default: {ATTACH_DELAY_DEFAULT}; matches debugger_loader.py)")
    r.add_argument("--out", default=os.path.join(REPO_DIR, "runs"),
                   help="output directory for per-run artifacts (default: <repo>/runs)")
    r.add_argument("--game", default=GAME, help=f"path to SADK.exe (default: {GAME})")
    r.add_argument("--no-arm", action="store_true",
                   help="do NOT arm the stub's auto-push of EnterWorld(1000) "
                        "(ARM_ENTER_WORLD=False); observe only")
    r.add_argument("--python", default=sys.executable,
                   help="python interpreter used to launch the stub "
                        "(default: this interpreter)")
    r.set_defaults(func=cmd_run)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
