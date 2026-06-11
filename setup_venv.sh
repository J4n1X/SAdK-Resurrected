#!/usr/bin/env bash
# Set up (and, if sourced, activate) the Python venv for the SaDK lobby stub.
#
#   source ./setup_venv.sh     # sets up venv AND activates it in your shell
#   ./setup_venv.sh            # sets up venv only (can't activate a parent shell)
#
# Note: twofish on Python >=3.12 imports the stdlib `imp` module, which was
# removed in 3.12. zombie-imp restores it, so we install it alongside the reqs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
PYTHON="${PYTHON:-python3}"

echo ">> Creating venv at $VENV_DIR (using $($PYTHON --version 2>&1))"
rm -rf "$VENV_DIR"
"$PYTHON" -m venv "$VENV_DIR"

# Use the venv's pip directly so this works whether sourced or executed.
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install zombie-imp
# Deps for the Ghidra MCP bridge (decomp/bridge_mcp_ghidra.py, wired in .mcp.json).
"$VENV_DIR/bin/pip" install "mcp>=1.2.0,<2" "requests>=2,<3"

echo ">> Done. Installed:"
"$VENV_DIR/bin/pip" list --format=columns | grep -iE "cryptography|twofish|zombie-imp" || true

# If this script was sourced, activate the venv in the caller's shell.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    echo ">> venv activated: $VIRTUAL_ENV"
else
    echo ">> To activate: source $VENV_DIR/bin/activate"
    echo "   (or re-run as: source ./setup_venv.sh)"
fi
