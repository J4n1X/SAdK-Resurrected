<#
  probe_referee_match_start.ps1 -- Win7-native twin of probe_referee_match_start.py.
  NO PYTHON NEEDED: pure PowerShell + .NET P/Invoke (ships with Win7 / PS 2.0+).

  RUN ELEVATED. READ-ONLY: OpenProcess(VM_READ|QUERY) + ReadProcessMemory only -- never writes,
  never debugs, never resumes. Cannot crash the game. (An *_probe: ungated by the harness.)

  Reads the referee / match-start ladder off the magazine build (sadk_noav) globals so you can
  watch the referee lifecycle on the Win7-VM client too. See the .py for the full RE writeup.

  Usage (in an ELEVATED PowerShell, inside the VM, while the game runs):
    powershell -ExecutionPolicy Bypass -File tools\probe_referee_match_start.ps1
    powershell -ExecutionPolicy Bypass -File tools\probe_referee_match_start.ps1 -Watch
    powershell -ExecutionPolicy Bypass -File tools\probe_referee_match_start.ps1 -GamePid 20680 -Watch

  WHAT TO LOOK FOR: start it BEFORE entering the village; watch LM+0x580 go 0 -> 60 (assign+connect
  at state 6) and whether it then DROPS back to 0 (the referee dying mid-village). Note the clock
  against the stub's tincat_server.log LoginSuccess push (~2s after the :5481 login): if 0x580 dies
  right after, the village-entry LoginSuccess push is the killer.
#>
param(
    [int]$GamePid = 0,
    [switch]$Watch
)

$sig = @'
using System;
using System.Runtime.InteropServices;
public static class Rpm {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool ReadProcessMemory(IntPtr hProcess, IntPtr lpBaseAddress, byte[] lpBuffer, int nSize, out int lpNumberOfBytesRead);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool CloseHandle(IntPtr hObject);
}
'@
Add-Type -TypeDefinition $sig

$PROCESS_VM_READ = 0x10
$PROCESS_QUERY_INFORMATION = 0x400

# --- magazine-build (sadk_noav) globals, confirmed via Ghidra getters (s41) -----------------
$G_PMANAGER      = 0x00885754   # FUN_00408290 -> NComm::Manager*  (+0x3cc bNE_StartLoadingFired)
$G_PLOBBYMANAGER = 0x00885890   # LobbyManager_GetInstance @0x462420 -> g_pLobbyManager
$REF_SERVER_ID   = 60           # config.REF_SERVER_ID; LM+0x580 should equal this when assigned

# struct offsets (build-stable)
$MGR_START_LOADING = 0x3cc      # Manager+0x3cc  bNE_StartLoadingFired
$LM_STATE          = 0x57c      # LobbyManager+0x57c  state (1..12)
$LM_REFEREE_ID     = 0x580      # LobbyManager+0x580  referee serverId
$LM_REFEREE_CONN   = 0x490      # LobbyManager+0x490  embedded RefereeServerConnection
$LM_CONNECT_TIMER  = 0x588      # LobbyManager+0x588  connect timer (ms)
$REFCONN_TRANSPORT = 0x34       # RefereeServerConnection+0x34  transport (0 == not connected)

$StateNames = @{
    1='Disconnected';2='Authorizing';3='Authorized';4='CheckingVersion';5='VersionChecked';
    6='LoadingGlobalData';7='GlobalDataLoaded';8='EnteringVillage';9='VillageEntered (IN 3D WORLD)';
    10='LeavingVillage';11='VillageLeft';12='ConnectionLost'
}

if ($GamePid -le 0) {
    $p = Get-Process -Name SADK -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $p) { Write-Host "SADK.exe not found (is the game running?)"; exit 1 }
    $GamePid = $p.Id
    Write-Host ("[+] SADK.exe pid={0}" -f $GamePid)
}

$h = [Rpm]::OpenProcess(($PROCESS_VM_READ -bor $PROCESS_QUERY_INFORMATION), $false, [uint32]$GamePid)
if ($h -eq [IntPtr]::Zero) {
    Write-Host ("[!] OpenProcess failed: err={0} -- run this ELEVATED" -f [Runtime.InteropServices.Marshal]::GetLastWin32Error())
    exit 2
}

function Read-Bytes([int64]$addr, [int]$size) {
    $buf = New-Object byte[] $size
    $read = 0
    $ok = [Rpm]::ReadProcessMemory($h, [IntPtr]$addr, $buf, $size, [ref]$read)
    if ($ok -and $read -eq $size) { return ,$buf } else { return $null }
}
function Get-U32([int64]$addr) {
    $b = Read-Bytes $addr 4
    if ($b -eq $null) { return $null } else { return [System.BitConverter]::ToUInt32($b, 0) }
}
function Get-I32([int64]$addr) {
    $b = Read-Bytes $addr 4
    if ($b -eq $null) { return $null } else { return [System.BitConverter]::ToInt32($b, 0) }
}
function Get-U8([int64]$addr) {
    $b = Read-Bytes $addr 1
    if ($b -eq $null) { return $null } else { return $b[0] }
}
function Valid-Ptr($p) { return ($p -ne $null -and $p -ge 0x10000 -and $p -le 0x7FFFFFFF) }
function Hex($v) { if ($v -eq $null) { '<unreadable>' } else { '0x{0:X8}' -f $v } }

function Snapshot() {
    Write-Host ("`n  [{0}] ----------------------------------------" -f (Get-Date).ToString('HH:mm:ss'))

    $mgr = Get-U32 $G_PMANAGER
    Write-Host ("  NComm Manager  @0x{0:X8} -> {1}" -f $G_PMANAGER, (Hex $mgr))
    $startLoading = $null
    if (Valid-Ptr $mgr) {
        $startLoading = Get-U8 ([int64]$mgr + $MGR_START_LOADING)
        if ($startLoading) { $note = "   <<< Start fired (referee login GATE open)" } else { $note = "   <<< 0: Start not seen here yet" }
        Write-Host ("    +0x3cc bNE_StartLoadingFired = {0}{1}" -f $startLoading, $note)
    } else {
        Write-Host "    >>> Manager null/invalid -- no NComm session yet, or live exe != magazine build."
    }

    $lm = Get-U32 $G_PLOBBYMANAGER
    Write-Host ("  LobbyManager   @0x{0:X8} -> {1}" -f $G_PLOBBYMANAGER, (Hex $lm))
    $state = $null; $refId = $null; $transport = $null
    if (Valid-Ptr $lm) {
        $state = Get-U32 ([int64]$lm + $LM_STATE)
        $refId = Get-I32 ([int64]$lm + $LM_REFEREE_ID)
        $timer = Get-I32 ([int64]$lm + $LM_CONNECT_TIMER)
        $transport = Get-U32 ([int64]$lm + $LM_REFEREE_CONN + $REFCONN_TRANSPORT)
        $sname = $StateNames[[int]$state]; if (-not $sname) { $sname = 'Unknown' }
        Write-Host ("    +0x57c state                = {0} ({1})" -f $state, $sname)
        if ($refId -eq $REF_SERVER_ID) { $rnote = "   <<< ASSIGNED == REF_SERVER_ID($REF_SERVER_ID)" } else { $rnote = "   <<< NOT assigned (0x580 unset)" }
        Write-Host ("    +0x580 refereeServerId      = {0}{1}" -f $refId, $rnote)
        if ($transport) { $tnote = "   <<< referee :5481 transport OPEN" } else { $tnote = "   <<< 0: referee NOT connected" }
        Write-Host ("    +0x490+0x34 refConn.transport = {0}{1}" -f (Hex $transport), $tnote)
        Write-Host ("    +0x588 connectTimer (ms)    = {0}" -f $timer)
    } else {
        Write-Host "    >>> LobbyManager null/invalid -- not logged in, or live exe != magazine build."
    }

    Write-Host "  --- verdict ---"
    $sname = $StateNames[[int]$state]; if (-not $sname) { $sname = '?' }
    if (-not (Valid-Ptr $mgr) -and -not (Valid-Ptr $lm)) {
        Write-Host "    Both globals invalid: re-anchor for the live exe (tell me the SADK.exe build)."
    } elseif ($state -ne $null -and $state -ge 10) {
        Write-Host ("    POST-VILLAGE snapshot (state {0}={1}) -- AMBIGUOUS: referee torn down by definition here." -f $state, $sname)
        Write-Host "    -Watch from state 9 THROUGH the Start click; a single read here proves nothing."
    } elseif ($refId -ne $null -and $refId -ne $REF_SERVER_ID -and $state -ge 6 -and $state -le 9) {
        Write-Host ("    >>> referee NOT assigned in the village (state {0}={1}, LM+0x580={2}, want {3})." -f $state, $sname, $refId, $REF_SERVER_ID)
        Write-Host "        If it was 60 a second ago and is 0 now, you just caught the referee dying."
    } elseif ($transport -ne $null -and $transport -eq 0 -and $state -ge 6 -and $state -le 9) {
        Write-Host ("    >>> assigned but :5481 transport==0 in the village (state {0}={1})." -f $state, $sname)
    } elseif ($transport) {
        Write-Host ("    Referee transport UP at state {0}={1}, StartLoading={2}. Keep watching across Start:" -f $state, $sname, $startLoading)
        Write-Host "      if transport/0x580 drop to 0 right as the stub logs LoginSuccess, that push is the killer."
    } else {
        Write-Host ("    state {0}={1}: refId={2}, transport={3}, StartLoading={4}." -f $state, $sname, $refId, (Hex $transport), $startLoading)
    }
}

if ($Watch) {
    Write-Host "[watch] FAST poll (50ms) + LATCH. Start BEFORE entering the village. Prints on CHANGE only;"
    Write-Host "        Ctrl+C prints the ever-seen summary (catches a sub-second state-6 referee window)."
    $latchRef = $false; $latchTr = $false; $latchSl = $false; $statesSeen = @(); $prev = $null
    try {
        while ($true) {
            $lm = Get-U32 $G_PLOBBYMANAGER
            $mgr = Get-U32 $G_PMANAGER
            $st = $null; $rid = $null; $tr = $null; $sl = $null
            if (Valid-Ptr $lm) {
                $st = Get-U32 ([int64]$lm + $LM_STATE)
                $rid = Get-I32 ([int64]$lm + $LM_REFEREE_ID)
                $tr = Get-U32 ([int64]$lm + $LM_REFEREE_CONN + $REFCONN_TRANSPORT)
            }
            if (Valid-Ptr $mgr) { $sl = Get-U8 ([int64]$mgr + $MGR_START_LOADING) }
            if ($rid -eq $REF_SERVER_ID) { $latchRef = $true }
            if ($tr) { $latchTr = $true }
            if ($sl) { $latchSl = $true }
            if ($st -ne $null -and ($statesSeen.Count -eq 0 -or $statesSeen[$statesSeen.Count-1] -ne $st)) { $statesSeen += $st }
            $cur = "$st|$rid|$tr|$sl"                            # RAW values — print on ANY change
            if ($cur -ne $prev) {
                $sn = $StateNames[[int]$st]; if (-not $sn) { $sn = '?' }
                Write-Host ("  [{0}] state={1} ({2})  LM+0x580={3}  transport={4}  StartLoading={5}" -f (Get-Date).ToString('HH:mm:ss.fff'), $st, $sn, $rid, (Hex $tr), $sl)
                $prev = $cur
            }
            # NO sleep: loop nonstop (as fast as PowerShell allows) to catch a sub-second state-6 window.
            # Pegs a core for the duration -- fine for a short capture; insert Start-Sleep -Milliseconds 1
            # here if you'd rather cap the rate on a constrained VM.
        }
    } finally {
        Write-Host "`n[watch] stopped. ---- LATCH (ever seen this session) ----"
        Write-Host ("    referee EVER assigned (LM+0x580=={0})? {1}" -f $REF_SERVER_ID, $(if ($latchRef) {'YES'} else {'no'}))
        Write-Host ("    referee transport EVER up?            {0}" -f $(if ($latchTr) {'YES'} else {'no'}))
        Write-Host ("    NE_StartLoading EVER fired?           {0}" -f $(if ($latchSl) {'YES'} else {'no'}))
        Write-Host ("    states seen:                          {0}" -f ($statesSeen -join ' -> '))
        if ($latchRef -or $latchTr) {
            Write-Host "    >>> Referee DID come up but reads 0 normally => it connects then DIES (lifecycle/timing)."
        } else {
            Write-Host "    >>> Referee NEVER assigned/connected this session => the assign itself is failing."
        }
        [Rpm]::CloseHandle($h) | Out-Null
    }
} else {
    Snapshot
    Write-Host "`n  A single snapshot past state 9 is ambiguous. Best: -Watch from inside the lobby world"
    Write-Host "  (state 9) THROUGH the host's Start click, on BOTH clients."
    [Rpm]::CloseHandle($h) | Out-Null
}
