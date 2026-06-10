#!/usr/bin/env python3
"""Run an inline Ghidra Java script via the GhidraMCP (xebyte fork) HTTP endpoint.

The code is the BODY of GhidraScript.run(): `currentProgram` / `monitor` are in scope, use
fully-qualified class names (no imports), `println(...)` for output, and wrap DB writes in
currentProgram.startTransaction(...) / endTransaction(tx, commit).

Usage:
    python tools/ghidra_inline.py path/to/script.java        # from file
    echo '...java...' | python tools/ghidra_inline.py -      # from stdin

This talks ONLY to the local Ghidra plugin (RE tooling), never the live game — outside the
HARNESS mutation gate. Default endpoint matches docs/GHIDRA_MCP_SETUP.md (plugin on :8089).
"""
import sys
import time

import requests

BASE = "http://127.0.0.1:8089/"

# The xebyte plugin writes each inline script into the $USER_HOME/ghidra_scripts OSGi bundle and triggers an
# async refresh; a load that fires before the refresh settles throws ClassNotFoundException/GhidraScriptLoadException.
# This is transient — retry settles it. (Distinct from a real javac error, whose text shows "cannot find symbol"
# / "unclosed string literal" etc.; those are NOT retried since retrying won't help.)
_TRANSIENT = ("ClassNotFoundException", "GhidraScriptLoadException", "could not be found")
_REAL_COMPILE = ("cannot find symbol", "unclosed string literal", "';' expected", "not a statement",
                 "reached end of file", "incompatible types", "error: ")


def run(code: str, timeout: int = 180, retries: int = 5) -> str:
    last = ""
    for attempt in range(retries):
        last = requests.post(BASE + "run_script_inline", json={"code": code}, timeout=timeout).text
        transient = any(t in last for t in _TRANSIENT)
        real = any(t in last for t in _REAL_COMPILE)
        if not transient or real:
            return last
        time.sleep(1.5)  # bounded wait for the OSGi bundle refresh to settle, then retry
    return last


if __name__ == "__main__":
    src = sys.stdin.read() if (len(sys.argv) > 1 and sys.argv[1] == "-") else open(sys.argv[1], encoding="utf-8").read()
    out = run(src)
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
