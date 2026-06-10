"""Logging + hex-dump helpers (thread-safe, mirrors the legacy monolith)."""
import contextlib
import os
import threading
from datetime import datetime

from . import config

_log_lock = threading.Lock()
_log_path = config.LOG_FILE


def set_log_path(path):
    """Override the log file path (used by the server entry point)."""
    global _log_path
    _log_path = path


# Per-thread routing flag. While set (via routed_to_unhandled), EVERY log() call in the current thread
# goes to tincat_lobby_unhandled.log ONLY — console + main suppressed. Lets a whole spammy message
# (frame header + village hex + decode + dispatch) be diverted in one shot, without threading a sink
# through every call site.
_route_tls = threading.local()


@contextlib.contextmanager
def routed_to_unhandled(active=True):
    """Within this block (when active), log() writes to the unhandled side-log only."""
    if not active:
        yield
        return
    prev = getattr(_route_tls, "on", False)
    _route_tls.on = True
    try:
        yield
    finally:
        _route_tls.on = prev


def log(msg):
    if getattr(_route_tls, "on", False):
        log_unhandled(msg)
        return
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        # Console can't encode (e.g. cp1252) — degrade rather than crash the conn.
        print(line.encode("ascii", "replace").decode("ascii"))
    with _log_lock:
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def log_unhandled(msg):
    """Append to the SEPARATE 'tincat_lobby_unhandled.log' (sibling of the main log) ONLY — never the
    console, never the main log. Routine default-ack'd / boilerplate chatter goes here so it doesn't
    congest the main view, while still being captured. The path tracks set_log_path's directory."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    path = os.path.join(os.path.dirname(_log_path) or ".", "tincat_lobby_unhandled.log")
    with _log_lock:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def hex_dump(data, indent="    ", w=16):
    lines = []
    for i in range(0, len(data), w):
        c = data[i:i + w]
        hexs = " ".join(f"{b:02x}" for b in c)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in c)
        lines.append(f"{indent}{i:04x}  {hexs:<{w * 3}}  |{text}|")
    return "\n".join(lines)
