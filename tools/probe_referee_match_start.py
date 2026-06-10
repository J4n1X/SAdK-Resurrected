r"""
probe_referee_match_start.py -- read SADK's live referee / match-start state via ReadProcessMemory.

RUN ELEVATED. READ-ONLY: OpenProcess(VM_READ) + ReadProcessMemory only -- never writes,
never debugs, never resumes. Cannot crash the game. Safe while the game / debugger_loader.py
holds it. (An *_probe.py tool: ungated by the harness; no Engagement Record needed.)

WHY (s41 static RE, clean magazine build sadk_noav -- xrefs working):
  The MP joiner's 3D world build is NOT triggered by FreeGamePanel+0x3a9 (that is HOST-Start-click
  only -- refuted). At match start the chain is:
    NE_StartLoading (NComm event 0x30012) --HandleNCommEvent@0x40e560--> sets Manager+0x3cc=1
      (bNE_StartLoadingFired; the ONLY thing that event does)
    LobbyGameScreen_Update (the WorldScreen per-frame update) reads Manager+0x3cc as the GATE to
      drive RefereeServerConnection_Login(LM+0x490) -- retries 5x then ABORTS the match.
    Referee LoginSuccess -> OnLoginSuccess@0x47ac20 fires observers -> (clears the gate) -> world build.
  So the referee is squarely on the critical path. This probe reads the referee ladder LIVE so we can
  tell EXACTLY where a stuck MP match dies, WITHOUT mutating anything. Run it during a real 2-client
  match right after the host clicks Start (use --watch).

DIAGNOSTIC LADDER (read off two confirmed globals; addresses are for the magazine build sadk_noav):
  1. Manager(*0x885754)+0x3cc   bNE_StartLoadingFired   did the host's Start reach this client?
  2. LobbyManager(*0x885890)+0x580   refereeServerId     did our AssignServer->170(sub5) set it?
        == 60 (config.REF_SERVER_ID)  -> referee ASSIGNED (the s39.6 cat-0x108 fix landed)
        == -1 / sentinel              -> NOT assigned (the 189->170 reply never set LM+0x580) <-- stub bug
  3. refConn(LM+0x490)+0x34   transport               did the client actually dial+open :5481?
        != 0 -> referee transport OPEN (connected);  == 0 -> never connected (dial/listener problem)
  4. LobbyManager+0x57c   state (1..12)               9 = "Village Entered" (in the 3D world)
  5. LobbyManager+0x588   connectTimer (ms, 60000 armed on assign; counts down)

KNOWN GOOD (s41 tincat log, run 00:12): the referee assign+connect WORKS at VILLAGE ENTRY (state 6) --
189->170(sub5) lands, LM+0x580=60, :5481 opens, base login(153)+LoginSuccess(0xDCA) all happen. So the
s39.6 assign fix is validated. The open question is whether the referee SURVIVES from the village into
the match: a snapshot taken at state>=10 (LeavingVillage) shows LM+0x580=0/transport=0 because the
village session is ENDING there -- EXPECTED, proves nothing. You must --watch ACROSS the Start click.

READING IT (mind the STATE -- the referee is only meaningful while state is 6..9):
  * Manager null/garbage -> live game is not the magazine build, or no NComm session yet. Re-anchor.
  * In the village (state 6-9): refId should be 60 and transport!=0. If not THERE, the assign/connect
        genuinely failed (189->170(sub5) cat-0x108 reply, or :5481 dial). That conclusion is ONLY valid here.
  * Across the Start click: if refId/transport were 60/!=0 in the village and DROP to 0 as
        bNE_StartLoadingFired flips to 1 -> the referee is torn down / not reused at match-start (the
        lifecycle/timing bug -- the stub pushes LoginSuccess at village-entry, not at the match-start
        RefereeServerConnection_Login, so the match-start gate never clears -> 5x retry -> abort).
  * state>=10 with refId/transport=0 -> POST-VILLAGE/POST-ABORT teardown. Ambiguous; ignore, re-watch.
  Compare HOST vs JOINER side by side -- the value that changes at match-start is the wall.

Usage:  python tools\probe_referee_match_start.py            (auto-find SADK.exe)
        python tools\probe_referee_match_start.py 20680      (explicit pid)
        python tools\probe_referee_match_start.py --watch    (re-read every 1s; Ctrl+C to stop)
        python tools\probe_referee_match_start.py 20680 --watch
"""
import ctypes
import sys
import time
from ctypes import wintypes

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

# --- magazine-build (sadk_noav) globals, confirmed via Ghidra getters (s41) -------------------------
G_PMANAGER       = 0x00885754   # FUN_00408290 -> DAT_00885754 = NComm::Manager* (game P2P session)
G_PLOBBYMANAGER  = 0x00885890   # LobbyManager_GetInstance @0x462420 -> g_pLobbyManager
REF_SERVER_ID    = 60           # what the stub advertises (config.REF_SERVER_ID); LM+0x580 should equal this

# --- struct offsets (clean binary; struct layout is build-stable even if globals shift) -------------
MGR_START_LOADING = 0x3cc       # Manager+0x3cc  bNE_StartLoadingFired (set by HandleNCommEvent 0x30012)
LM_STATE          = 0x57c       # LobbyManager+0x57c  LobbyManagerState (1..12)
LM_REFEREE_ID     = 0x580       # LobbyManager+0x580  referee serverId (SetRefereeServerAddress @0x4625d0)
LM_REFEREE_CONN   = 0x490       # LobbyManager+0x490  embedded RefereeServerConnection
LM_CONNECT_TIMER  = 0x588       # LobbyManager+0x588  referee connect timer (ms; 60000 on assign)
REFCONN_TRANSPORT = 0x34        # RefereeServerConnection+0x34  net transport (0 == not connected)

STATE_NAMES = {
    1: "Disconnected", 2: "Authorizing", 3: "Authorized", 4: "CheckingVersion",
    5: "VersionChecked", 6: "LoadingGlobalData", 7: "GlobalDataLoaded",
    8: "EnteringVillage", 9: "VillageEntered (IN 3D WORLD)", 10: "LeavingVillage",
    11: "VillageLeft", 12: "ConnectionLost",
}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def find_pids(name="SADK.exe"):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    e = PROCESSENTRY32(); e.dwSize = ctypes.sizeof(e)
    pids = []
    if k32.Process32First(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.decode("ascii", "ignore").lower() == name.lower():
                pids.append(e.th32ProcessID)
            if not k32.Process32Next(snap, ctypes.byref(e)):
                break
    k32.CloseHandle(snap)
    return pids


def _valid_ptr(p):
    return p is not None and 0x10000 <= p <= 0x7FFFFFFF


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    watch = "--watch" in sys.argv
    if args:
        pid = int(args[0])
    else:
        pids = find_pids()
        if not pids:
            print("SADK.exe not found (is the game running?)"); return 1
        pid = pids[0]
        print(f"[+] SADK.exe pid={pid}")

    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"[!] OpenProcess failed: err={ctypes.get_last_error()} -- run this ELEVATED"); return 2

    def rpm(addr, size):
        buf = (ctypes.c_ubyte * size)()
        n = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
        return bytes(buf) if (ok and n.value == size) else None

    def u32(addr):
        b = rpm(addr, 4); return None if b is None else int.from_bytes(b, "little")

    def i32(addr):
        b = rpm(addr, 4); return None if b is None else int.from_bytes(b, "little", signed=True)

    def u8(addr):
        b = rpm(addr, 1); return None if b is None else b[0]

    def fmt(v, hexw=8):
        return "<unreadable>" if v is None else f"0x{v:0{hexw}X}"

    def snapshot():
        # Timestamp each snapshot so a LM+0x580 0->60->0 transition can be correlated against the
        # tincat_server.log referee events (esp. the LoginSuccess push ~2s after the :5481 login).
        print(f"\n  [{time.strftime('%H:%M:%S')}] ----------------------------------------")
        # ---- NComm Manager: did NE_StartLoading fire on this client? ----
        mgr = u32(G_PMANAGER)
        print(f"  NComm Manager  @0x{G_PMANAGER:08X} -> " + fmt(mgr))
        start_loading = None
        if _valid_ptr(mgr):
            start_loading = u8(mgr + MGR_START_LOADING)
            print(f"    +0x3cc bNE_StartLoadingFired = "
                  + (f"{start_loading}" if start_loading is not None else "<?>")
                  + ("   <<< Start fired (referee login GATE is OPEN)" if start_loading
                     else "   <<< 0: Start not seen on this client yet"))
        else:
            print("    >>> Manager null/invalid -- no NComm session yet, or live exe != magazine build.")

        # ---- LobbyManager: referee assign / connect / state ----
        lm = u32(G_PLOBBYMANAGER)
        print(f"  LobbyManager   @0x{G_PLOBBYMANAGER:08X} -> " + fmt(lm))
        ref_id = transport = state = None
        if _valid_ptr(lm):
            state = u32(lm + LM_STATE)
            ref_id = i32(lm + LM_REFEREE_ID)
            timer = i32(lm + LM_CONNECT_TIMER)
            transport = u32(lm + LM_REFEREE_CONN + REFCONN_TRANSPORT)
            sname = STATE_NAMES.get(state, "Unknown")
            print(f"    +0x57c state                = "
                  + (f"{state} ({sname})" if state is not None else "<?>"))
            print(f"    +0x580 refereeServerId      = "
                  + (f"{ref_id}" if ref_id is not None else "<?>")
                  + (f"   <<< ASSIGNED == REF_SERVER_ID({REF_SERVER_ID}) (stub assign OK)"
                     if ref_id == REF_SERVER_ID else
                     "   <<< NOT assigned (LM+0x580 unset -> referee login will no-op -> abort)"))
            print(f"    +0x490+0x34 refConn.transport = " + fmt(transport)
                  + ("   <<< referee :5481 transport OPEN" if transport
                     else "   <<< 0: referee NOT connected (never dialed / dial failed)"))
            print(f"    +0x588 connectTimer (ms)    = " + (f"{timer}" if timer is not None else "<?>"))
        else:
            print("    >>> LobbyManager null/invalid -- not logged in, or live exe != magazine build.")

        # ---- verdict (state-aware: the referee is assigned at state>=6 and must SURVIVE to match-start) ----
        print("  --- verdict ---")
        sname = STATE_NAMES.get(state, "?") if state is not None else "?"
        if not _valid_ptr(mgr) and not _valid_ptr(lm):
            print("    Both globals invalid: re-anchor for the live exe (tell me the SADK.exe build).")
        elif state is not None and state >= 10:
            # LeavingVillage(10)/VillageLeft(11)/ConnectionLost(12): the village session is ENDING.
            # LM+0x580==0 / transport==0 HERE means the referee was TORN DOWN (post-village or post-abort),
            # which does NOT prove the assign failed -- it WORKED earlier (tincat log shows :5481 opened).
            # A single snapshot at this state is ambiguous; only --watch from state 9 disambiguates.
            print(f"    POST-VILLAGE snapshot (state {state}={sname}) -- AMBIGUOUS. The referee is torn down")
            print("    by definition here, so LM+0x580/transport==0 is EXPECTED and proves nothing about the")
            print("    match-start failure. >>> Re-run with --watch from state 9 (in the lobby world) THROUGH")
            print("    the host's Start click, on BOTH clients, to catch whether the referee SURVIVES match-start.")
        elif ref_id is not None and ref_id != REF_SERVER_ID and state is not None and 6 <= state <= 9:
            print(f"    >>> referee NOT assigned during the village window (state {state}={sname},")
            print(f"        LM+0x580={ref_id}, want {REF_SERVER_ID}). The 189->170(sub5) cat-0x108 reply isn't landing.")
        elif transport is not None and transport == 0 and state is not None and 6 <= state <= 9:
            print(f"    >>> assigned but :5481 transport==0 in the village (state {state}={sname}):")
            print("        client hasn't opened the referee channel (firewall / REFEREE_PORT / advertised IP).")
        elif start_loading is not None and start_loading == 0:
            print(f"    state {state}={sname}, Start not clicked yet. Referee should be id={ref_id}, transport={fmt(transport)}.")
            print(f"    If id=={REF_SERVER_ID} and transport!=0, the VILLAGE referee is healthy -- keep --watch running")
            print("    and click Start: the question is whether it SURVIVES into the match (LoginSuccess timing).")
        elif transport:
            print(f"    Referee transport is UP at state {state}={sname} with StartLoading={start_loading}.")
            print("      If the match still aborts from here, the wall is PAST the transport: the match-start")
            print("      LoginSuccess timing (stub pushed it at village-entry, not at the match-start re-login),")
            print("      the OnLoginSuccess commSystem gate, or the post-referee world build.")
        else:
            print(f"    state {state}={sname}: id={ref_id}, transport={fmt(transport)}, StartLoading={start_loading}.")
            print("      Compare HOST vs JOINER and --watch through Start; the value that changes at match-start is the wall.")

    if watch:
        # FAST poll + LATCH. State 6 (the referee assign+connect) is sub-second, so a 1s poll misses it.
        # Poll every 50ms, print ONLY when something changes (so transitions are readable, not a flood),
        # and LATCH ever-seen values so even a single sample inside a brief window is remembered. Ctrl+C
        # prints the latch summary -- the decisive read is "was LM+0x580 EVER 60 / transport EVER up".
        print("[watch] FAST poll (50ms) + LATCH. Start BEFORE entering the village. Prints on CHANGE only;")
        print("        Ctrl+C prints the ever-seen summary (catches a sub-second state-6 referee window).")
        latch = {"ref_assigned": False, "transport": False, "start": False, "states": []}
        prev = None
        try:
            while True:
                lm = u32(G_PLOBBYMANAGER); mgr = u32(G_PMANAGER)
                st = u32(lm + LM_STATE) if _valid_ptr(lm) else None
                rid = i32(lm + LM_REFEREE_ID) if _valid_ptr(lm) else None
                tr = u32(lm + LM_REFEREE_CONN + REFCONN_TRANSPORT) if _valid_ptr(lm) else None
                sl = u8(mgr + MGR_START_LOADING) if _valid_ptr(mgr) else None
                if rid == REF_SERVER_ID:
                    latch["ref_assigned"] = True
                if tr:
                    latch["transport"] = True
                if sl:
                    latch["start"] = True
                if st is not None and (not latch["states"] or latch["states"][-1] != st):
                    latch["states"].append(st)
                cur = (st, rid, tr, sl)                         # RAW values — print on ANY change
                if cur != prev:
                    now = time.time()
                    ts = time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"
                    sn = STATE_NAMES.get(st, "?")
                    print(f"  [{ts}] state={st} ({sn})  LM+0x580={rid}  transport={fmt(tr)}  StartLoading={sl}")
                    prev = cur
                # NO sleep: poll nonstop (as fast as the CPU allows) to catch a sub-millisecond state-6
                # window. Pegs one core for the duration — fine for a short capture; insert
                # time.sleep(0.001) here if you'd rather cap it near ~1000 reads/s.
        except KeyboardInterrupt:
            ys = lambda b: "YES" if b else "no"
            print("\n[watch] stopped. ---- LATCH (ever seen this session) ----")
            print(f"    referee EVER assigned (LM+0x580=={REF_SERVER_ID})? {ys(latch['ref_assigned'])}")
            print(f"    referee transport EVER up?                       {ys(latch['transport'])}")
            print(f"    NE_StartLoading EVER fired?                      {ys(latch['start'])}")
            print(f"    states seen:                                     {' -> '.join(map(str, latch['states']))}")
            if latch["ref_assigned"] or latch["transport"]:
                print("    >>> Referee DID come up at some point but reads 0 normally => it connects then DIES")
                print("        (lifecycle/timing) -- NOT an assign failure. Matches the model.")
            else:
                print("    >>> Referee was NEVER assigned/connected this session => the assign itself is failing.")
    else:
        snapshot()
        print("\n  A single snapshot is ambiguous if you're already past the village (state>=10).")
        print("  BEST: run with --watch starting from state 9 (standing in the lobby world), on BOTH")
        print("  clients, and click Start on the host. Watch whether LM+0x580/transport SURVIVE the")
        print("  StartLoading flip (timing bug) or were already gone (lifecycle bug).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
