# SADK.exe — Win10/11 SecuROM boot fix (release note)

The genuine SecuROM-protected `SADK.exe` crashes at startup / world-entry on Win7/10/11
(`0xC0000005` at `0x7C81320C`). Two runtime patches explain and fix it; they are applied
operationally by **`tools/debugger_loader.py`** when it attaches to the freshly-decrypted process —
no static binary edit is involved (the regions only exist in the running, decrypted image).

- **P1 — World-entry DRM dispatch (OpenFileMappingA).** A SecuROM encrypted-import dispatch computes a
  hardcoded *WinXP* kernel32 address (`0x7C81320C`, unmapped on Win7+) and `call`s it to invoke
  `OpenFileMappingA` on the SecuROM license shared-memory. The loader allocates the dead XP page and
  writes a `JMP rel32` to the process's real `OpenFileMappingA`.
- **P2 — Stack-balance NOP (second domino after P1).** With P1 in place the fault moves +14 bytes to a
  `add [ecx],edx` write, caused by a no-op SecuROM wrapper stub that never pops its pushed argument
  (stack imbalance lands a handle in ECX). The loader NOPs the offending `push eax` (`50` → `90`).

Together P1 + P2 are *why* the Win10/11 SecuROM crash happened and *how* it is now handled.

> **Note on the go-forward base.** The clean **2014 magazine `SADK.exe`** (SecuROM-free) is the current
> RE/run base; runtime patching the genuine exe via `debugger_loader.py` remains the operational path for
> the protected build. Earlier work toward a standalone statically-patchable rebuild (the retired
> `SADK_glass.exe` unpack pipeline and live memory dumps) is gone and no longer relevant.

## Server-side (NOT a binary patch)
- `LobbySettings.ini` → `Host = "127.0.0.1"` (point the client at the revival server). Config, not code.
- Credentials: any user/pass works at login (serial only checked at registration).
