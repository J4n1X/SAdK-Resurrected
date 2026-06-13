#!/usr/bin/env python3
"""Configure the `ghidra` MCP bridge for whatever OS you're on.

`.mcp.json` must name a concrete interpreter, and that path differs by platform
(POSIX `.venv/bin/python` vs Windows `.venv\\Scripts\\python.exe`), so a single
committed value cannot serve both the Linux minisrv and a Windows GUI host. This
script writes the correct `.mcp.json` for the current platform and creates a
repo-local `.venv` with the bridge deps if one is missing.

Run once per clone (and again after changing your Python):

    python setup_mcp.py            # Windows, Linux, or macOS

Then restart the Claude Code session so the new config is read.

Idempotent — safe to re-run; it only changes what is wrong. This wires up the
MCP plumbing only: it does no RE, reads no process memory, and touches no game
binary, so it is fine under HARNESS.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parent
VENV = REPO / ".venv"
MCP_JSON = REPO / ".mcp.json"
BRIDGE_ARG = "decomp/bridge_mcp_ghidra.py"
# Same pins as setup_venv.sh so the bridge venv matches the stub venv.
DEPS = ["mcp>=1.2.0,<2", "requests>=2,<3"]
IS_WIN = os.name == "nt"


def venv_python() -> Path:
    """Absolute path to the venv interpreter on this OS."""
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def rel_python() -> str:
    """Interpreter path as stored in .mcp.json (relative to the repo root)."""
    return ".venv\\Scripts\\python.exe" if IS_WIN else ".venv/bin/python"


def _imports_ok(py: Path) -> bool:
    return (
        subprocess.run(
            [str(py), "-c", "import mcp, requests"], capture_output=True
        ).returncode
        == 0
    )


def ensure_venv() -> None:
    py = venv_python()
    if not py.exists():
        print(f">> creating venv at {VENV}")
        venv.EnvBuilder(with_pip=True).create(VENV)
        py = venv_python()
    if _imports_ok(py):
        print(">> venv already has the bridge deps (mcp, requests)")
        return
    print(f">> installing bridge deps into venv: {', '.join(DEPS)}")
    subprocess.check_call([str(py), "-m", "pip", "install", "--quiet", *DEPS])
    if not _imports_ok(py):
        sys.exit("!! mcp/requests still not importable in the venv — check pip output")


def desired_config() -> dict:
    server: dict = {"command": rel_python(), "args": [BRIDGE_ARG]}
    if not IS_WIN:
        # The Linux headless backend is auto-spawned by the bridge. On Windows
        # you run the Ghidra GUI plugin yourself (it already serves :8089), so
        # AUTOSTART is omitted — the bridge just connects to the running plugin.
        server["env"] = {"GHIDRA_MCP_AUTOSTART": "1"}
    return {"mcpServers": {"ghidra": server}}


def write_mcp_json() -> dict:
    cfg = desired_config()
    new = json.dumps(cfg, indent=2) + "\n"
    old = MCP_JSON.read_text(encoding="utf-8") if MCP_JSON.exists() else None
    if old == new:
        print(f">> {MCP_JSON.name} already correct for this OS")
    else:
        MCP_JSON.write_text(new, encoding="utf-8")
        print(f">> wrote {MCP_JSON.name} for {'windows' if IS_WIN else 'posix'}")
    return cfg


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True
    )


def keep_local_uncommitted(cfg: dict) -> None:
    """If this OS's config differs from the committed one, hide the local file
    from git (skip-worktree) so you never commit your platform's path over the
    other's. If it matches the committed value, make sure it stays tracked."""
    head = _git("show", "HEAD:.mcp.json")
    if head.returncode != 0:
        return  # not a git repo, or .mcp.json isn't committed — nothing to guard
    try:
        diverges = json.loads(head.stdout) != cfg
    except json.JSONDecodeError:
        diverges = True
    flag = "--skip-worktree" if diverges else "--no-skip-worktree"
    if _git("update-index", flag, ".mcp.json").returncode == 0 and diverges:
        print(
            ">> marked .mcp.json skip-worktree so your OS path is not committed.\n"
            "   undo with: git update-index --no-skip-worktree .mcp.json"
        )


def main() -> None:
    ensure_venv()
    cfg = write_mcp_json()
    keep_local_uncommitted(cfg)
    print("\n>> Done. Restart the Claude Code session so the `ghidra` MCP loads,")
    print("   then open sadk_noav.exe in the Ghidra CodeBrowser to give it a program.")


if __name__ == "__main__":
    main()
