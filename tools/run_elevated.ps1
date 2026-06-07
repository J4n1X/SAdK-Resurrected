# Generic elevated python wrapper. Usage (via Start-Process -Verb RunAs):
#   powershell -File run_elevated.ps1 <script.py> [pidArg]
# Captures output to tools\<scriptbasename>.log (ascii).
param([string]$Script, [string]$TargetPid)
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot ([IO.Path]::GetFileNameWithoutExtension($Script) + '.log')
$out = & python $Script $TargetPid 2>&1 | Out-String
Set-Content -Path $log -Value $out -Encoding ascii
