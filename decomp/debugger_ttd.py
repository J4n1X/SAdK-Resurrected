"""Time Travel Debugging (TTD) — record once, query the trace offline forever.

Why this lives in the debugger MCP (HARNESS §1/§3): the live dbgeng engine can only
answer questions that were decided *before* the run. Every follow-up question costs
another full session. TTD records one execution into a `.run` trace that can then be
replayed offline — forwards and backwards — and queried arbitrarily many times.

Three capabilities the live engine provably cannot provide:
  * retrospective queries  ("did X ever get called, anywhere in the run?")
  * reverse execution      ("what wrote this, and what was the stack when it did?")
  * heap memory histories  (dbgeng hardware watchpoints refuse heap addresses)

Recording requires elevation. Replay and querying do NOT — which is the point: one
elevated human-driven run, then unlimited non-elevated analysis.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows test environments
    winreg = None  # type: ignore[assignment]

_PACKAGE_REPOSITORY = (
    r"Local Settings\Software\Microsoft\Windows\CurrentVersion"
    r"\AppModel\PackageRepository\Packages"
)

# First open of a trace builds an index; that can take minutes on a big trace.
DEFAULT_QUERY_TIMEOUT = 600

# ⛔ PROVEN 2026-07-27: on an UNINDEXED trace, TTD.Calls / TTD.Memory return
# ZERO results instead of erroring. That is a silent false negative — you would
# read it as "the function was never called". Every query therefore indexes
# first. `!index` is a fast no-op once the .idx exists, so this costs nothing
# after the first run.
_INDEX_COMMAND = "!index"


def default_trace_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    runtime_env = env if env is not None else os.environ
    explicit = runtime_env.get("TTD_TRACE_DIR")
    if explicit:
        return Path(explicit)
    return Path.home() / "ttd_traces"


# -- Toolchain discovery ---------------------------------------------------


def _arch_dir_store() -> str:
    return "amd64" if platform.architecture()[0] == "64bit" else "x86"


def _arch_dir_sdk() -> str:
    return "x64" if platform.architecture()[0] == "64bit" else "x86"


def _is_debugger_root(path: Optional[Path]) -> bool:
    """A usable root has both the headless engine and the TTD payload."""
    if not path:
        return False
    return (path / "cdb.exe").is_file() and (path / "ttd" / "TTD.exe").is_file()


def _iter_debugger_roots(env: Optional[Mapping[str, str]] = None) -> Iterable[Path]:
    runtime_env = env if env is not None else os.environ
    seen: set[Path] = set()

    def offer(candidate: Optional[Path]) -> Iterable[Path]:
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate

    explicit = runtime_env.get("TTD_DIR") or runtime_env.get("WINDBG_ROOT")
    if explicit:
        yield from offer(Path(explicit))

    # Store / winget WinDbg package (ships cdb.exe + ttd/ together).
    if winreg is not None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _PACKAGE_REPOSITORY)
            try:
                index = 0
                while True:
                    try:
                        package_name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    if "WinDbg" not in package_name or "_neutral_" in package_name:
                        continue
                    yield from offer(
                        Path(r"C:\Program Files\WindowsApps")
                        / package_name
                        / _arch_dir_store()
                    )
            finally:
                winreg.CloseKey(key)
        except OSError:
            pass

    # Windows SDK "Debugging Tools for Windows".
    for base in (
        Path(r"C:\Program Files (x86)\Windows Kits\10"),
        Path(r"C:\Program Files\Windows Kits\10"),
    ):
        yield from offer(base / "Debuggers" / _arch_dir_sdk())


def resolve_ttd_dir(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Directory containing cdb.exe with a sibling ttd/ payload, or None."""
    for candidate in _iter_debugger_roots(env):
        if _is_debugger_root(candidate):
            return candidate
    return None


def _cache_ttd_payload(
    source_ttd_dir: Path, localappdata: Optional[Path | str] = None
) -> Path:
    """Copy the TTD payload out of WindowsApps so it can actually be executed.

    PROVEN 2026-07-27: `ttd\\TTD.exe` inside the MSIX package fails CreateProcess
    with Win32 error 5 (ACCESS_DENIED) even from an elevated process. It is not an
    ACL problem — the ACLs are byte-identical to the sibling `cdb.exe`, which runs
    fine — it is an MSIX execution restriction on the nested path. Copying the
    whole `ttd` folder to a normal directory makes it run. `cdb.exe` needs no such
    treatment and is used in place.
    """
    root = Path(localappdata) if localappdata else Path(os.environ.get("LOCALAPPDATA", ""))
    if not str(root):
        return source_ttd_dir

    cache_dir = root / "ghidra_mcp_ttd_cache"
    payload = cache_dir / "ttd"
    stamp = cache_dir / "source.txt"
    recorded = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""

    if (payload / "TTD.exe").is_file() and recorded == str(source_ttd_dir):
        return payload

    logger.info("Caching TTD payload %s -> %s", source_ttd_dir, payload)
    try:
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_ttd_dir, payload)
        stamp.write_text(str(source_ttd_dir), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to cache TTD payload (%s); using source path", exc)
        return source_ttd_dir
    return payload


def resolve_ttd_exe(env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """Path to a TTD.exe that can actually be launched, or None."""
    runtime_env = env if env is not None else os.environ

    explicit = runtime_env.get("TTD_EXE")
    if explicit and Path(explicit).is_file():
        return Path(explicit)

    root = resolve_ttd_dir(runtime_env)
    if root is None:
        return None

    source = root / "ttd"
    # Only the MSIX path needs the copy-out workaround.
    if "windowsapps" in str(source).lower():
        return _cache_ttd_payload(source) / "TTD.exe"
    return source / "TTD.exe"


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def toolchain_status(env: Optional[Mapping[str, str]] = None) -> dict:
    root = resolve_ttd_dir(env)
    ttd_exe = resolve_ttd_exe(env)
    trace_dir = default_trace_dir(env)
    status = {
        "available": root is not None,
        "root": str(root) if root else None,
        "cdb": str(root / "cdb.exe") if root else None,
        "ttd_exe": str(ttd_exe) if ttd_exe else None,
        "elevated": is_elevated(),
        "trace_dir": str(trace_dir),
        "can_record": root is not None and is_elevated(),
        "can_query": root is not None,
    }
    if root is None:
        status["error"] = (
            "No WinDbg/TTD toolchain found. Install with "
            "`winget install Microsoft.WinDbg`, or set TTD_DIR to a directory "
            "containing cdb.exe and ttd/TTD.exe."
        )
    elif not status["elevated"]:
        status["note"] = (
            "Not elevated: recording is unavailable, querying existing traces "
            "still works. Restart the debugger server elevated to record."
        )
    return status


# -- Recording -------------------------------------------------------------


def list_traces(trace_dir: Optional[Path] = None) -> List[dict]:
    directory = Path(trace_dir) if trace_dir else default_trace_dir()
    if not directory.is_dir():
        return []
    traces = []
    for path in sorted(directory.glob("*.run"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        traces.append(
            {
                "path": str(path),
                "name": path.name,
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "indexed": path.with_suffix(".idx").is_file()
                or (path.parent / (path.name + ".idx")).is_file(),
            }
        )
    return traces


def record(
    target: str,
    mode: str = "attach",
    out: Optional[str] = None,
    args: Optional[Sequence[str]] = None,
    trace_dir: Optional[Path] = None,
    ring_buffer_mb: Optional[int] = None,
    include_children: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Start a TTD recording.

    mode="attach": `target` is a PID or process name already running.
    mode="launch": `target` is an executable path; `args` are its arguments.

    Returns immediately — TTD keeps recording in the background until the
    process exits or stop_recording() is called. Recording requires elevation.
    """
    root = resolve_ttd_dir(env)
    if root is None:
        return {"error": toolchain_status(env)["error"]}
    if not is_elevated():
        return {
            "error": "TTD recording requires elevation. Restart the debugger "
            "server from an elevated shell (the game already runs elevated, so "
            "this matches the existing live-debug requirement)."
        }

    directory = Path(trace_dir) if trace_dir else default_trace_dir(env)
    directory.mkdir(parents=True, exist_ok=True)

    if out:
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = directory / out_path
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe = "".join(c for c in str(target) if c.isalnum() or c in "._-") or "trace"
        out_path = directory / f"{safe}_{stamp}.run"

    ttd_exe = resolve_ttd_exe(env)
    if ttd_exe is None or not ttd_exe.is_file():
        return {"error": "TTD.exe could not be resolved to a runnable path."}
    cmd: List[str] = [str(ttd_exe), "-accepteula", "-out", str(out_path)]
    if ring_buffer_mb:
        cmd += ["-ring", "-maxFile", str(ring_buffer_mb)]
    if include_children:
        cmd.append("-children")

    if mode == "attach":
        cmd += ["-attach", str(target)]
    elif mode == "launch":
        cmd += ["-launch", str(target)]
        if args:
            cmd += list(args)
    else:
        return {"error": f"Unknown mode '{mode}' (expected 'attach' or 'launch')"}

    logger.info("TTD record: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except OSError as exc:
        return {"error": f"Failed to launch TTD.exe: {exc}", "command": " ".join(cmd)}

    # Give it a moment to fail fast on a bad target, but never block on a
    # successful recording (which runs until the process exits).
    try:
        output = proc.communicate(timeout=5)[0]
        return {
            "recording": False,
            "exited": True,
            "exit_code": proc.returncode,
            "trace": str(out_path),
            "output": (output or "").strip(),
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "recording": True,
            "trace": str(out_path),
            "recorder_pid": proc.pid,
            "command": " ".join(cmd),
            "note": "Recording in progress. Stop with ttd_stop, or let the "
            "target exit. The .run file is finalized on stop/exit.",
        }


def stop_recording(
    target: str = "all", env: Optional[Mapping[str, str]] = None
) -> dict:
    """Stop an in-progress recording ('all', a PID, or a process name)."""
    root = resolve_ttd_dir(env)
    if root is None:
        return {"error": toolchain_status(env)["error"]}
    if not is_elevated():
        return {"error": "Stopping a TTD recording requires elevation."}

    ttd_exe = resolve_ttd_exe(env)
    if ttd_exe is None or not ttd_exe.is_file():
        return {"error": "TTD.exe could not be resolved to a runnable path."}
    cmd = [str(ttd_exe), "-accepteula", "-stop", str(target)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"ttd -stop failed: {exc}", "command": " ".join(cmd)}
    return {
        "stopped": proc.returncode == 0,
        "exit_code": proc.returncode,
        "output": (proc.stdout or "").strip() + (proc.stderr or "").strip(),
        "command": " ".join(cmd),
    }


# -- Offline replay / query ------------------------------------------------


def _clean_output(raw: str) -> str:
    """Strip cdb's startup/teardown boilerplate, keeping the command output.

    cdb emits ~40 lines of extension-gallery banner before, and NatVis/JS
    unload spam after, the part anyone cares about. The useful region sits
    between the 'Reading initial command' echo and the 'quit:' line.
    """
    if not raw:
        return raw
    lines = raw.splitlines()

    start = 0
    for i, line in enumerate(lines):
        if "Reading initial command" in line:
            start = i + 1
            break

    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("quit:"):
            end = i
            break

    body = "\n".join(lines[start:end]).strip()
    return body if body else raw.strip()


def query(
    trace: str,
    commands: Sequence[str] | str,
    timeout: int = DEFAULT_QUERY_TIMEOUT,
    env: Optional[Mapping[str, str]] = None,
    ensure_index: bool = True,
) -> dict:
    """Replay a trace headlessly under cdb and run debugger commands against it.

    This is read-only analysis of a recorded file — no live process is touched,
    and no elevation is required.
    """
    root = resolve_ttd_dir(env)
    if root is None:
        return {"error": toolchain_status(env)["error"]}

    trace_path = Path(trace)
    if not trace_path.is_absolute():
        trace_path = default_trace_dir(env) / trace_path
    if not trace_path.is_file():
        return {"error": f"Trace not found: {trace_path}"}

    if isinstance(commands, str):
        command_list = [commands]
    else:
        command_list = list(commands)
    if not command_list:
        return {"error": "No commands supplied"}

    if ensure_index and _INDEX_COMMAND not in command_list:
        command_list.insert(0, _INDEX_COMMAND)

    # Always terminate the session, otherwise cdb waits for input forever.
    script = "; ".join(command_list + ["q"])

    cmd = [
        str(root / "cdb.exe"),
        "-z",
        str(trace_path),
        "-c",
        script,
    ]
    logger.info("TTD query: %s", cmd)
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": f"cdb timed out after {timeout}s. First open of a large "
            "trace builds an index and can be slow — retry with a longer "
            "timeout; subsequent queries are fast.",
            "command": " ".join(cmd),
        }
    except OSError as exc:
        return {"error": f"Failed to launch cdb: {exc}", "command": " ".join(cmd)}

    raw = (proc.stdout or "") + (proc.stderr or "")
    return {
        "trace": str(trace_path),
        "script": script,
        "exit_code": proc.returncode,
        "elapsed_s": round(time.time() - started, 1),
        "output": _clean_output(raw),
    }


def _dx_target(function: str) -> str:
    """Accept either a symbol ('mod!Func') or an address ('0x468f80')."""
    text = str(function).strip()
    try:
        return hex(int(text, 16 if text.lower().startswith("0x") else 10))
    except ValueError:
        return f'"{text}"'


def calls(
    trace: str,
    function: str,
    limit: int = 200,
    timeout: int = DEFAULT_QUERY_TIMEOUT,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Every call to `function` across the whole recorded run.

    We have no PDBs for the target, so an address is the normal input.
    """
    selector = (
        f"@$cursession.TTD.Calls({_dx_target(function)})"
        ".Select(c => new { Start = c.TimeStart, End = c.TimeEnd, "
        "Ret = c.ReturnValue, ThreadId = c.ThreadId })"
    )
    return query(
        trace,
        [f"dx -r2 {selector}.Take({limit})", f"dx {selector}.Count()"],
        timeout=timeout,
        env=env,
    )


def memory_accesses(
    trace: str,
    address: str,
    size: int = 4,
    access: str = "w",
    limit: int = 200,
    timeout: int = DEFAULT_QUERY_TIMEOUT,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Every read/write/execute of an address range across the whole run.

    This is the capability hardware watchpoints cannot give us on heap
    addresses — TTD reconstructs it from the recording instead.
    """
    text = str(address).strip()
    start = int(text, 16 if text.lower().startswith("0x") else 10)
    end = start + int(size)
    selector = (
        f"@$cursession.TTD.Memory({hex(start)}, {hex(end)}, \"{access}\")"
        ".Select(m => new { Time = m.TimeStart, Access = m.AccessType, "
        "IP = m.IP, Value = m.Value, Address = m.Address })"
    )
    return query(
        trace,
        [f"dx -r2 {selector}.Take({limit})", f"dx {selector}.Count()"],
        timeout=timeout,
        env=env,
    )
