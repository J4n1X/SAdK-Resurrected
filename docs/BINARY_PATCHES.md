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

## Optional developer patch: enable the built-in tweak (CVar) server

Not needed to play. It unlocks the developers' own tweak variables — among them the NPC designer
"Evil Hacks/CustomizeNPCHack" with `NPCIndex`, `color1..8` and `SAVE` (ApplyCustomizeAvatarLook
S 004f84b0).

- SADK.exe contains a CVar TCP server (`ai::debug::CVarRemoteServer`, ctor S 0067e690), compiled into the
  release build but never started: `CVarServerHolder_Init` (S 0067c6d0) creates it only when the byte at
  0x0088ca50 is non-zero. That byte lies in the zero-filled tail of `.data` (not stored in the file) and no
  code writes it. [known]
- **Patch (on a copy):** file offset **0x27C701**, `74 44` → `90 90` (the `JZ 0x0067c747` at
  VA 0x0067c701 becomes two NOPs, so the server is always created). Original md5
  d4832bc5103c14f5445471af29b8d778.
- The server then listens on TCP **1234** (u16 at 0x008810bc; file offset 0x4810bc, `d2 04`) and polls
  every 200 ms. Talk to it with `tools/cvar_client.py` (protocol in its docstring). [inferred until tried]
- Whether the copy-protection layer objects to a modified `.text` is untested.
