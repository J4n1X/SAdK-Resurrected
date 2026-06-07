r"""
probe_lobby_world_entry.py -- read SADK's live LOBBY-WORLD-ENTRY state via ReadProcessMemory.

RUN ELEVATED (the game runs elevated; OpenProcess(VM_READ) on it needs admin too).
READ-ONLY: OpenProcess(VM_READ) + ReadProcessMemory only. Never writes, never debugs,
never resumes. Cannot crash the game. Safe to run WHILE the game + stub are live.

WHAT IT ANSWERS (s39 read-only diagnosis -- see memory/lobby-world-entry-client-side-fsm.md):
  Entering the 3D lobby world is a CLIENT-SIDE FSM transition, NOT a server-message wait:
    CLobby requests a state -> App_ProcessStateTransition@0x4f5950 executes it ->
    AppState_ActivateWorldScreen_CallOnEnter@0x5d9f10 -> nMenu_Game_OnEnter (the 3D builder).
  Login only sets the gate (LobbyManager.state = Authorized). So the question is: after we log in
  over the stub, does the client ever REQUEST the lobby-world transition? This probe reads, in one
  shot, exactly where the client is:
    - CLobby   (the "App FSM" = Lobby::CLobby singleton)  nCurrentState/nRequestedState
    - LobbyManager.state            (did login reach Authorized=3? or stuck earlier? VillageEntered=9?)
    - nMenu_System active screen's GameLoadDescriptor    (which map is staged: lobby world1 vs blank)

HOW TO USE:
  1. Launch the game + the lobby stub; connect and LOG IN (reach the lobby).
  2. From an ELEVATED shell:  python tools\probe_lobby_world_entry.py
     (auto-finds SADK.exe; or pass an explicit pid:  python tools\probe_lobby_world_entry.py 12345)
  3. Read the DIAGNOSIS block. Re-run at each step (just-logged-in vs after clicking into the lobby)
     to watch the state move (or fail to).

ADDRESSES are for the CLEAN magazine build (Ghidra program sadk_noav.exe, base 0x400000, no rebase ->
absolute runtime addrs). If you run a different build, the .data globals shift; re-derive them.
ALL offsets below are PROVEN by static decompile this session (sadk_noav.exe).
"""
import ctypes
import sys
from ctypes import wintypes

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

# ---- globals (absolute; clean build) ----------------------------------------------------------
G_APP            = 0x008856A8   # CApp object (static). +0xa8 localhostmode, +0xaa nolobby, +0x88 CLobby ptr
CLOBBY_PTR       = 0x008882C4   # DAT_008882c4 -> Lobby::CLobby singleton (the "App FSM")
LOBBY_MGR_PTR    = 0x00885890   # g_pLobbyManager -> LobbyManager
NMENU_SYS_PTR    = 0x0088B83C   # g_pNMenuSystem  -> nMenu_System

# ---- struct offsets (PROVEN static) -----------------------------------------------------------
CLOBBY_PREVSTATE = 0x26C        # CLobby+0x26c
CLOBBY_CURSTATE  = 0x270        # CLobby+0x270  nCurrentState (init 0 = main menu)
CLOBBY_REQSTATE  = 0x274        # CLobby+0x274  nRequestedState (init -1 = none pending)

LM_STATE         = 0x57C        # LobbyManager+0x57c  state (LobbyManagerState)

NMENU_ACTIVESCR  = 0x3C         # nMenu_System+0x3c  pActiveScreen
SCR_DESC_PTR     = 0xFFE4       # activeScreen+0xffe4 -> GameLoadDescriptor*
DESC_MAPTYPE     = 0x00         # GameLoadDescriptor.nMapType (SetMapName forces 0x6e)
DESC_MAPNAME     = 0x04         # GameLoadDescriptor.mapName std::string (SSO buf @+0x4, len @+0x14, cap @+0x18)

LOBBY_MGR_STATE_NAMES = {
    0: "Init", 1: "Disconnected", 2: "Authorizing", 3: "Authorized",
    4: "CheckingVersion", 5: "VersionChecked", 6: "LoadingGlobalData", 7: "GlobalDataLoaded",
    8: "EnteringVillage", 9: "VillageEntered", 10: "LeavingVillage", 11: "VillageLeft",
    12: "ConnectionLost",
}
# CLobby state numbers (TENTATIVE -- exact semantics to be confirmed by this very probe):
#   0 = MainMenu (ctor init). Transitions handled by App_ProcessStateTransition: 0/1 -> 2/3 (enter),
#   2/3 -> 0/1 (leave); req 1 -> activate WORLD screen (3D), req 3 -> join match, req 2 -> lobby
#   screen-host setup, req 0 -> main menu. So a non-zero current state == past the bare 2D menu.
CLOBBY_STATE_HINT = {
    0: "MainMenu (2D menu / not in a world)",
    1: "(tentative) WorldScreen active (3D world built via OnEnter)",
    2: "(tentative) Lobby screen-host active",
    3: "(tentative) Match/Game active",
    -1: "none",
    0xFFFFFFFF: "none (-1)",
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


def main():
    if len(sys.argv) > 1:
        pid = int(sys.argv[1])
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

    def s32(addr):
        v = u32(addr)
        return None if v is None else (v - 0x100000000 if v >= 0x80000000 else v)

    def read_stdstring(strbase):
        """MSVC std::string @ strbase: buf[16] @ +0 (SSO) | ptr @ +0, _Mysize @ +0x10, _Myres @ +0x14."""
        if strbase is None:
            return None
        size = u32(strbase + 0x10)
        cap = u32(strbase + 0x14)
        if size is None or cap is None:
            return None
        if size > 0x1000:
            return f"<bad size {size}>"
        if cap < 16:
            raw = rpm(strbase, max(1, size))
        else:
            ptr = u32(strbase)
            raw = rpm(ptr, size) if ptr else None
        if raw is None:
            return "<unreadable>"
        return raw.split(b"\x00", 1)[0].decode("ascii", "replace")

    print("\n=== SADK lobby-world-entry probe (READ-ONLY) ===")

    # --- App flags (localhostmode/nolobby) ---
    lhm = rpm(G_APP + 0xA8, 1)
    nolobby = rpm(G_APP + 0xAA, 1)
    print(f"\n  g_app @0x{G_APP:08X}: localhostmode(+0xa8)={lhm[0] if lhm else '?'}  "
          f"nolobby(+0xaa)={nolobby[0] if nolobby else '?'}")

    # --- CLobby FSM ---
    clobby = u32(CLOBBY_PTR)
    print(f"\n  CLobby (App FSM) @0x{CLOBBY_PTR:08X} -> "
          + (f"0x{clobby:08X}" if clobby else "NULL (FSM not created -> -nolobby, or pre-init)"))
    cur = req = None
    if clobby:
        prev = s32(clobby + CLOBBY_PREVSTATE)
        cur = u32(clobby + CLOBBY_CURSTATE)
        req = s32(clobby + CLOBBY_REQSTATE)
        print(f"    nCurrentState (+0x270) = {cur}   -> {CLOBBY_STATE_HINT.get(cur, '?')}")
        print(f"    nRequestedState(+0x274) = {req}   -> "
              + ("none pending" if req in (-1, None) else f"REQUESTED {req} = {CLOBBY_STATE_HINT.get(req, '?')}"))
        print(f"    prevState (+0x26c) = {prev}")

    # --- LobbyManager.state ---
    lm = u32(LOBBY_MGR_PTR)
    lm_state = None
    print(f"\n  LobbyManager @0x{LOBBY_MGR_PTR:08X} -> " + (f"0x{lm:08X}" if lm else "NULL"))
    if lm:
        lm_state = u32(lm + LM_STATE)
        print(f"    state (+0x57c) = {lm_state}  -> {LOBBY_MGR_STATE_NAMES.get(lm_state, '?')}")

    # --- nMenu_System active screen + staged GameLoadDescriptor ---
    nms = u32(NMENU_SYS_PTR)
    map_name = None
    print(f"\n  nMenu_System @0x{NMENU_SYS_PTR:08X} -> " + (f"0x{nms:08X}" if nms else "NULL"))
    if nms:
        scr = u32(nms + NMENU_ACTIVESCR)
        print(f"    pActiveScreen (+0x3c) = " + (f"0x{scr:08X}" if scr else "NULL"))
        if scr:
            desc = u32(scr + SCR_DESC_PTR)
            print(f"    activeScreen+0xffe4 (GameLoadDescriptor*) = " + (f"0x{desc:08X}" if desc else "NULL"))
            if desc:
                mtype = u32(desc + DESC_MAPTYPE)
                map_name = read_stdstring(desc + DESC_MAPNAME)
                print(f"      nMapType (+0x0) = {mtype} (0x{mtype:x})   [SetMapName forces 0x6e]")
                print(f"      mapName (+0x4)  = {map_name!r}")

    # --- DIAGNOSIS ---
    print("\n  --- DIAGNOSIS ---")
    if lm_state is None:
        print("  ! LobbyManager unreadable -- offsets may be off for this build, or not yet in a lobby session.")
    elif lm_state < 3:
        print(f"  > Login has NOT completed: LobbyManager.state={LOBBY_MGR_STATE_NAMES.get(lm_state)} (<Authorized).")
        print("    The lobby-world transition is correctly NOT firing yet -- finish/repair the stub login first.")
    elif lm_state == 3:
        print("  > Logged in (Authorized). The login gate is SATISFIED.")
        if cur == 0 and (req in (-1, None)):
            print("  >> KEY FINDING: CLobby is still in MainMenu (state 0) and NOTHING has requested a")
            print("     transition (nRequestedState=-1). => the genuine post-login trigger never fires over")
            print("     the stub. The fix lives on the CLIENT side (drive/allow the CLobby transition),")
            print("     NOT in a wire message. (Mutation => Engagement Record.)")
        elif req not in (-1, None):
            print(f"  >> A transition to state {req} IS requested but not yet executed -- the per-frame")
            print("     App_ProcessStateTransition is either gated or not running. Re-run to see if it clears.")
        elif cur != 0:
            print(f"  >> CLobby has advanced to state {cur} ({CLOBBY_STATE_HINT.get(cur, '?')}). If the screen is")
            print(f"     still not the 3D lobby, check the staged map (mapName={map_name!r}) and OnEnter.")
    elif lm_state in (8, 9):
        print(f"  > LobbyManager is in the VILLAGE path (state={LOBBY_MGR_STATE_NAMES.get(lm_state)}). That's the")
        print("    msg-1000 saga, NOT the client-side lobby-world entry. (See loading-screen-gate note.)")
    else:
        print(f"  > LobbyManager.state={LOBBY_MGR_STATE_NAMES.get(lm_state)} -- note where the lobby-world entry stands.")

    print("\n  (Re-run at each UI step to watch CLobby nCurrentState / nRequestedState move.)")
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
