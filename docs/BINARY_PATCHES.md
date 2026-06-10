# SADK.exe — Win10/11 SecuROM boot fix (release note)

The genuine SecuROM-protected `SADK.exe` crashes at startup / world-entry on Win7/10/11
(`0xC0000005` at `0x7C81320C`). Two **runtime** patches explain and fix it. They are applied to the
freshly-decrypted process while it runs under a debugger — no static binary edit is involved (the
regions only exist in the running, decrypted image). Apply them via the **Ghidra MCP debugger**
(`debugger_*` tools), not a standalone loader script (HARNESS §1).

- **P1 — World-entry DRM dispatch (OpenFileMappingA).** A SecuROM encrypted-import dispatch computes a
  hardcoded *WinXP* kernel32 address (`0x7C81320C`, unmapped on Win7+) and `call`s it to invoke
  `OpenFileMappingA` on the SecuROM license shared-memory. Fix: commit the dead XP page and write a
  `JMP rel32` to the process's real `OpenFileMappingA`.
- **P2 — Stack-balance NOP (second domino after P1).** With P1 in place the fault moves +14 bytes to a
  `add [ecx],edx` write, caused by a no-op SecuROM wrapper stub that never pops its pushed argument
  (stack imbalance lands a handle in ECX). Fix: NOP the offending `push eax` (`50` → `90`).

Together P1 + P2 are *why* the Win10/11 SecuROM crash happened and *how* it is handled.

> **Go-forward base.** The clean **2014 magazine `SADK.exe`** (SecuROM-free) is the current RE/run base;
> runtime-patching the genuine exe under the debugger remains the path for the protected build. The
> retired `SADK_glass.exe` unpack pipeline and live memory dumps are gone and no longer relevant.

## Server-side (NOT a binary patch)
- `LobbySettings.ini` → `Host = "127.0.0.1"` (point the client at the revival server). Config, not code.
- Credentials: any user/pass works at login (serial only checked at registration).
