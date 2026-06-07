# Elevated launcher for debugger_loader.py (launch mode): starts SADK.exe under the debug loop,
# waits out SecuROM startup, attaches, and applies the world-entry DRM dispatch fix
# (0x7C81320C -> OpenFileMappingA) + the stack-balance NOP.
# The loader self-tees its output (incl. FAULT addresses) to tools\loader_live.log with per-line
# flush, so the non-elevated session can read the crash address live (PowerShell Tee-Object buffered
# it last run). Keep this elevated window open for the whole session.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
Write-Output "[run_loader_elevated] launching SADK.exe under debugger_loader.py (launch mode)..."
python '.\debugger_loader.py'
Write-Output "[run_loader_elevated] loader exited."
