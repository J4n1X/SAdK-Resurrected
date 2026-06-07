r"""
input_server.py -- elevated input relay.

UIPI blocks a medium-integrity process (the agent's shell) from injecting input
(SetCursorPos / mouse_event / keybd_event) into the ELEVATED SADK game. Run this ONCE,
ELEVATED (RunAs); it sits in the elevated session and executes mouse/keyboard/window
commands the agent writes to a relay file -- so the agent can finally drive the game.
(The agent takes its own screenshots; reading the screen needs no elevation.)

Relay files (tools/):
  relay_cmd.txt  -- agent writes one line:  <seq>|<COMMAND ...>
  relay_out.txt  -- server writes:          <seq>|<result>
The agent bumps <seq> per command and polls relay_out.txt for the matching <seq>.

Commands:
  FG                bring SADK to foreground (restore if minimized + SetForegroundWindow)
  MOVE <x> <y>      SetCursorPos to screen (x,y)
  CLICK <x> <y>     move + left down/up at (x,y)
  KEY <hex>         press a virtual key (0D=Enter 09=Tab 1B=Esc 20=Space)
  TYPE <text>       type ASCII text into the focused control
  PING              liveness
"""
import ctypes, time, os
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
CMD = os.path.join(HERE, "relay_cmd.txt")
OUT = os.path.join(HERE, "relay_out.txt")

u32 = ctypes.WinDLL("user32", use_last_error=True)
u32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int];      u32.SetCursorPos.restype = wintypes.BOOL
u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
u32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
u32.VkKeyScanW.argtypes = [wintypes.WCHAR];                    u32.VkKeyScanW.restype = ctypes.c_short
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.SetForegroundWindow.argtypes = [wintypes.HWND];           u32.SetForegroundWindow.restype = wintypes.BOOL
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.IsWindowVisible.argtypes = [wintypes.HWND]
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]

def find_game():
    found = []
    def cb(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        if "Aufbruch der Kulturen" in buf.value and u32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    u32.EnumWindows(EnumProc(cb), 0)
    return found[0] if found else None

def do(cmd):
    p = cmd.split()
    op = p[0].upper() if p else ""
    if op == "PING":
        return "pong"
    if op == "FG":
        h = find_game()
        if not h: return "no-game-window"
        u32.ShowWindow(h, 9); time.sleep(0.15)             # SW_RESTORE
        ok = u32.SetForegroundWindow(h); time.sleep(0.1)
        return f"fg hwnd={h} setfg={ok} fgnow={u32.GetForegroundWindow()}"
    if op == "MOVE":
        x, y = int(p[1]), int(p[2]); ok = u32.SetCursorPos(x, y)
        return f"move {x},{y} ok={ok}"
    if op == "CLICK":
        x, y = int(p[1]), int(p[2]); ok = u32.SetCursorPos(x, y); time.sleep(0.07)
        u32.mouse_event(0x0002, 0, 0, 0, None); time.sleep(0.05); u32.mouse_event(0x0004, 0, 0, 0, None)
        return f"click {x},{y} setpos={ok}"
    if op == "KEY":
        vk = int(p[1], 16)
        u32.keybd_event(vk, 0, 0, None); time.sleep(0.05); u32.keybd_event(vk, 0, 2, None)
        return f"key {vk:#04x}"
    if op == "TYPE":
        text = cmd[len(p[0]):].lstrip()
        for ch in text:
            s = u32.VkKeyScanW(ch); vk = s & 0xFF; sh = (s >> 8) & 1
            if vk == 0xFF: continue
            if sh: u32.keybd_event(0x10, 0, 0, None)
            u32.keybd_event(vk, 0, 0, None); time.sleep(0.02); u32.keybd_event(vk, 0, 2, None)
            if sh: u32.keybd_event(0x10, 0, 2, None)
            time.sleep(0.03)
        return f"typed {len(text)}ch"
    return f"unknown:{op}"

def main():
    print(f"[input_server] ELEVATED relay running. Polling {CMD}  (Ctrl+C to stop)")
    try: open(OUT, "w").close()
    except Exception: pass
    last = ""
    while True:
        try:
            if os.path.exists(CMD):
                data = open(CMD, "r", encoding="utf-8", errors="ignore").read().strip()
                if data and data != last:
                    last = data
                    seq, _, cmd = data.partition("|")
                    try: res = do(cmd.strip())
                    except Exception as e: res = f"ERR {e!r}"
                    open(OUT, "w", encoding="utf-8").write(f"{seq}|{res}")
                    print(f"  [{seq}] {cmd.strip()}  ->  {res}")
        except Exception as e:
            print("loop-err", e)
        time.sleep(0.15)

if __name__ == "__main__":
    main()
