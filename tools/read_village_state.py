r"""
read_village_state.py -- read SADK's live village-list state via ReadProcessMemory.

RUN ELEVATED (the game runs as admin; opening it for VM_READ needs admin too).
READ-ONLY: OpenProcess(VM_READ) + ReadProcessMemory only -- never writes, never
debugs, never resumes. Cannot crash the game. Safe to run *while* debugger_loader.py
still holds the game (a separate read handle does not conflict with the debugger).

Resolves (SADK.exe base 0x400000, no rebase -> these are absolute runtime addrs):
  g_dwSelectedVillageRoomId @ 0x0087D580        (the room the client wants to enter)
  LobbyManager singleton ptr @ 0x0088CEF0  -> +0x54 = LobbyVillageServerList
      std::vector<GameServerInfo*>  begin @ +0x74 , end @ +0x78
  GameServerInfo: dwCurPlayers +0x28, dwMaxPlayers +0x2c, nRoomId +0x30,
                  pending +0x34, bValidityFlag +0x35

For world-entry (HandleRoomServerDescriptor -> LoadLevel) the entry must have:
  nRoomId == g_dwSelectedVillageRoomId , pending == 0 , bValidityFlag != 0 , load < 90%

Usage:  python tools\read_village_state.py            (auto-find SADK.exe)
        python tools\read_village_state.py 20680      (explicit pid)
"""
import ctypes
import sys
from ctypes import wintypes

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002

SEL_ROOM_ID = 0x0087D580
LOBBY_MGR = 0x0088CEF0

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

    def u8(addr):
        b = rpm(addr, 1); return None if b is None else b[0]

    sel = u32(SEL_ROOM_ID)
    print(f"\n  g_dwSelectedVillageRoomId @0x{SEL_ROOM_ID:08X} = "
          + (f"{sel} (0x{sel:X})" if sel is not None else "<read failed>"))

    lm = u32(LOBBY_MGR)
    if not lm:
        print(f"  LobbyManager @0x{LOBBY_MGR:08X} = null/unreadable"); return 0
    print(f"  LobbyManager @0x{LOBBY_MGR:08X} -> 0x{lm:08X}")

    vlist = lm + 0x54
    begin, end = u32(vlist + 0x74), u32(vlist + 0x78)
    if begin is None or end is None:
        print("  village list begin/end unreadable"); return 0
    count = (end - begin) // 4 if end >= begin else -1
    print(f"  villageList @0x{vlist:08X}: begin=0x{begin:08X} end=0x{end:08X} count={count}")
    if count < 0 or count > 1024:
        print("  (list bounds look wrong -- offsets may be off or list mid-update)"); return 0
    if count == 0:
        print("  >>> village list is EMPTY <<<"); return 0

    print(f"\n  {'#':>2}  {'entry':>10}  {'roomId':>8}  {'pending':>7}  {'validity':>8}  players   JOINABLE?")
    for i, p in enumerate(range(begin, end, 4)):
        entry = u32(p)
        if not entry:
            print(f"  {i:>2}  <null entry ptr>"); continue
        room = u32(entry + 0x30); pend = u8(entry + 0x34); val = u8(entry + 0x35)
        cur = u32(entry + 0x28); mx = u32(entry + 0x2c)
        load = (cur * 100 // mx) if mx else 0
        joinable = (room == sel) and (pend == 0) and (val not in (0, None)) and load < 90
        print(f"  {i:>2}  0x{entry:08X}  {room:>8}  {pend:>7}  {val:>8}  {cur}/{mx}   "
              + ("YES <<<" if joinable else "no"))
    # SPIEL STARTEN path: CreateVillageServerConnection resolves GetSelectedVillageServer()
    # = *(villageList+0x80). If that's the invalid sentinel, the resolve bails (error 0x23a)
    # and the client never enters. +0x98 is advertise-5479's "IsField98Set" lead.
    inv = u32(0x007DC51C)  # g_dwInvalidVillageServerId
    selsrv = u32(vlist + 0x80)
    f98 = u32(vlist + 0x98)
    print("\n  --- SPIEL STARTEN resolve inputs (villageList @0x%08X) ---" % vlist)
    print(f"  g_dwInvalidVillageServerId           = "
          + (f"0x{inv:08X}" if inv is not None else "<?>"))
    print(f"  selected SERVER id (villageList+0x80) = "
          + (f"0x{selsrv:08X}  -> {'INVALID — no server selected!' if selsrv == inv else 'valid'}"
             if selsrv is not None else "<read failed>"))
    print(f"  field98            (villageList+0x98) = "
          + (f"0x{f98:08X}  -> {'INVALID' if f98 == inv else 'set'}" if f98 is not None else "<read failed>"))
    # CreateVillageServerConnection internals: it skips creating if a conn already sits at
    # LobbyManager+0x540, else it calls commLayer(+0x50).vtbl[+0x38](serverId) to resolve.
    comm = u32(lm + 0x50)
    print(f"\n  commLayer (LobbyManager+0x50) = "
          + (f"0x{comm:08X}" if comm is not None else "<?>"))
    if comm:
        vt = u32(comm)
        if vt:
            m38 = u32(vt + 0x38)
            m18 = u32(vt + 0x18)
            print(f"    vtable = 0x{vt:08X}")
            print(f"    vtbl[+0x38] (resolve method)      = 0x{m38:08X}" if m38 else "    vtbl[+0x38] unreadable")
            print(f"    vtbl[+0x18] (get-connection)      = 0x{m18:08X}" if m18 else "    vtbl[+0x18] unreadable")
    vconn = u32(lm + 0x540)
    print(f"  villageConn slot (LobbyManager+0x540) = "
          + (f"0x{vconn:08X}  -> {'EXISTS — create may be SKIPPED' if vconn else 'null (will create)'}"
             if vconn is not None else "<?>"))

    # --- the two gates that decide the SPIEL STARTEN connect ---
    print("\n  --- connect gates ---")
    gate = u32(vconn + 0x34) if vconn else None
    print(f"  conn+0x34 (FUN_00526ba0 skip-gate) = "
          + (f"0x{gate:08X}  -> {'NONZERO: connect block is SKIPPED' if gate else 'zero: connect block RUNS'}"
             if gate is not None else "<?>"))
    if comm:
        prop = u32(comm + 4)
        name = u32(prop + 4) if prop else None
        print(f"  ResolveServer name-check: prop=0x{prop:08X}  GetName=*(prop+4)="
              + (f"0x{name:08X}" if name is not None else "<?>") if prop else "  prop unreadable")
        if name:
            s = rpm(name, 64)
            txt = s.split(b"\x00")[0].decode("ascii", "replace") if s else ""
            print(f"     -> NAME SET ('{txt}')  => ResolveServer returns 5 => error 0x23a => NO CONNECT  <<< BUG")
        elif name == 0:
            print("     -> name is NULL => ResolveServer will NOT return 5 (resolve proceeds)")
    # --- s34: world-entry STATE machine (where did BETRETE WELT stall?) ---
    # LobbyManager::SetState (@0x462700) writes the lobby/world state to LobbyManager+0x57c.
    # OnConnected(FUN_004702e0) sets 8=EnteringVillage; HandleEnterWorld sets 9=VillageEntered;
    # FUN_0046b990 (after SENDing msg 2002 code=0xAFFEDEAD) sets 10. The village conn logs in fine
    # but goes silent (no 2002) -> read this to see exactly where the client stalled.
    print("\n  --- s34 world-entry state (LobbyManager+0x57c) ---")
    st = u32(lm + 0x57c)
    names = {8: "EnteringVillage", 9: "VillageEntered", 10: "WorldLoginSent(2002)"}
    if st is not None:
        print(f"  LobbyManager+0x57c (SetState) = {st} (0x{st:X})  {names.get(st, '<pre-enter / other>')}")
        if st == 8:
            print("    >>> reached EnteringVillage(8): OnConnected ran + overlay gate PASSED.")
            print("        Client should now SEND msg 2002 (FUN_0046b990) but didn't -> the send-2002")
            print("        callback / its state==8 check is the blocker.")
        elif st < 8:
            print("    >>> did NOT reach EnteringVillage(8): OnConnected overlay gate")
            print("        (*_DAT_012f1e40) likely FAILED -> the connect path bailed before state 8.")
    else:
        print("  LobbyManager+0x57c = <read failed>")
    if vconn:
        cstate = u32(vconn + 0x244)
        tport = u32(vconn + 0x34)
        print(f"  villageConn+0x244 (connState)     = " + (f"{cstate}" if cstate is not None else "<?>"))
        print(f"  villageConn+0x34  (transport ptr) = " + (f"0x{tport:08X}" if tport else "<null/zero>"))
        if tport:
            # FUN_0046b990 (send-2002) gates on the tincat3 CONNECTION state == 8 (AUTHORIZED),
            # read via transport->vtbl[+0xC](). tincat3 conn state field is at *(conn)+8 (4->5->8).
            tvt = u32(tport)
            s8 = u32(tport + 8)
            print(f"    transport+0 (vtable)             = " + (f"0x{tvt:08X}" if tvt is not None else "<?>"))
            print(f"    transport+8 (tincat3 conn STATE) = "
                  + (f"{s8} (0x{s8:X})" if s8 is not None else "<?>")
                  + "   [client 4->5->8 ; 8=AUTHORIZED ; FUN_0046b990 sends 2002 IFF ==8]")
            blob = rpm(tport, 0x28)
            if blob:
                print("    transport[0:0x28] = " + blob.hex())
        cvt = u32(vconn)
        if cvt:
            m40 = u32(cvt + 0x40)
            m38v = u32(cvt + 0x38)
            print(f"  villageConn vtable = " + (f"0x{cvt:08X}" if cvt else "<?>")
                  + "  vtbl[+0x40]=" + (f"0x{m40:08X}" if m40 else "<?>") + " (expect 0046b990 send-2002)"
                  + "  vtbl[+0x38]=" + (f"0x{m38v:08X}" if m38v else "<?>"))

    print("\n  -> world-entry (LoadLevel) fires when an entry shows JOINABLE=YES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
