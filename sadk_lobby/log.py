"""Logging + hex-dump helpers (thread-safe, mirrors the legacy monolith)."""
import threading
from datetime import datetime

from . import config

_log_lock = threading.Lock()
_log_path = config.LOG_FILE


def set_log_path(path):
    """Override the log file path (used by the server entry point)."""
    global _log_path
    _log_path = path


def log(msg):
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


def hex_dump(data, indent="    ", w=16):
    lines = []
    for i in range(0, len(data), w):
        c = data[i:i + w]
        hexs = " ".join(f"{b:02x}" for b in c)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in c)
        lines.append(f"{indent}{i:04x}  {hexs:<{w * 3}}  |{text}|")
    return "\n".join(lines)
