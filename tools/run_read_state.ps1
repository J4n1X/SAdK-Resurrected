# Elevated wrapper for read_village_state.py (READ-ONLY RPM of the live game). Captures output to
# tools\village_state.log (ascii) so the non-elevated session can read it. Pass the SADK pid as arg.
param($TargetPid)
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$out = & python '.\read_village_state.py' $TargetPid 2>&1 | Out-String
Set-Content -Path (Join-Path $PSScriptRoot 'village_state.log') -Value $out -Encoding ascii
