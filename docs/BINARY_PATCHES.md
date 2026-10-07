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
- **Tried live 2026-10-07: connection refused on port 1234; not pursued further.** Unresolved whether the
  patched exe was the one running, the port was taken, or the server failed to bind. Treat as unproven.

## Map sharing (bridge shim, in memory)

The client already contains a map transfer: a joiner that lacks the host's map asks the host for
`SAdK\maps\<map>.s2m` and `.bmp` over the match connection (S2TFTP, message `0x3eb`) and stores them in its
own `Documents\SAdK\maps` (`NComm::Manager::HandleEvent` S 0040e560, game-information case). It only runs when
the host advertises the map with type 3 (found under `Documents\SAdK\maps`) and "download allowed" (`+0x228`),
which `SetupGameDialog::OnMapSelected` S 00454ad0 always sends as 0, and the map picker never lists that folder.
Live 2026-10-07 (Frida, through the bridge): with both values forced, a joiner received a map it did not
have and the match started. Live 2026-10-07 with the shim: picker, download, progress messages, ready guard
and refresh all work.

A match never starts while a slot is **open**, on any map (vanilla behaviour, confirmed live): the host starts
only when `EventGameInformation::AreAllSlotsReady` S 00413400 holds, which needs every slot below the map's
player count ready, and `PlayerInfo::IsReady` S 00414f50 counts AI and closed slots as ready but never an open
one. `NComm_Manager::RefreshSlots` S 0040b5a0 resets the extra slots of a map with more start positions to
open (to AI offline), so on such a map the host must close them or add AI players.

The shim (`bridge/wsock32_shim`) applies these patches in memory at start-up (after the exe check), each only
where the original bytes match exactly:

| Address | Original | Change |
|---|---|---|
| 00454c37 (17 bytes) | push of the found-under type and of `0` to `SetGameSettings` | push type `3` and "download allowed" `1` for every map |
| 0045a381 | `call SelectMapDialog_AppendMapFiles(0, …)` | also lists location 3 (`Documents\SAdK\maps`, warm-tinted rows) |
| 00426b14 | `fopen_s` of the file a peer asked for (S2Tftp_Session_ReadNextBlock) | only `<Documents>\SAdK\maps\<name>.s2m/.bmp`; a map not found there is served from `data\game\maps\Freegamemaps` |
| 00427b29, 00427b7e | `rename` of a finished download (S2TftpSession::CloseFile) | only into `Documents\SAdK\maps` as `.s2m/.bmp`, else the temp file is deleted |
| 00457f51 | `SendPlayerReadyEvent` from the Ready button | refused (sends not-ready) while a download runs or the map is missing — starting without the map crashes the client |
| 00426ca5, 00426d14, 00427a08 | temp-file open, block `fwrite`, abort `remove` | progress messages in the pre-game room; after the last file a not-ready event makes the host re-broadcast, so the joiner finds the map |

**Security note (vanilla game):** without the shim, any peer in a host's match can read any file below the
host's `My Documents` (and above it with `..\`) through this transfer: `S2TftpManager::OnReceive` S 00428110
answers every read request with `My Documents\<requested name>`, unchecked. The shim's filter closes this
for hosts that run it.

## Billboards (bridge shim, in memory)

The three advertising screens in the lobby world (`lobby/scene/scene_ad.xml`, models `ad0.KEX` / `ad1.KEX`) are
web pages. Each model has two materials: the board (`sign ad0` → `sign_ad0.dds`) and the screen
(`Material #478` → `ad0.tga` / `ad1.tga` / `ad2.tga`). `Lobby::CGfxTextureMgr::GetTexture` S 00504650 compares
the texture name against those three literals (S 007e6240 / 007e6208 / 007e61d0, read nowhere else) and, on a
match, creates the texture with `S2CE::CTexture::CreateFromURL` S 004e7880: an embedded Internet Explorer
renders `http://www.funatics.de/sadk/forwardingN.html` into it. Those pages return HTTP 404:
`CSDKIEEvents::Invoke` S 005c8a30 answers NavigateError by clearing the texture to red (`ClearTextureToRed`
S 005c7790) and then renders IE's own "navigation canceled" page over it. The `ad*.tga` files the game ships are
never used.

The screen is part of the board mesh, so a transparent screen texture leaves a hole. With
`DisableBillboards = true` (`[LobbyServer]` in `data\lobby\config\LobbySettings.ini`, set by SAdK-ServerConfig),
the shim instead shows a plain plank area of the board's own texture:

| Address | Original | Change |
|---|---|---|
| 007e6240, 007e6208, 007e61d0 | `"ad0.tga"`, `"ad1.tga"`, `"ad2.tga"` | first letter `#`: no name matches, the screens load from file like any texture |
| 00504806 (7 bytes) | `MOV EDX,[ESI+0x28]; MOV ECX,EAX; CALL EDX`: virtual `CTexture::CreateFromFile` S 004e80d0 | `MOV ECX,EAX; CALL billboard_load` |

`billboard_load` calls the original `CreateFromFile` (`bool __thiscall (CTexture*, const std::string *path,
bool, bool, bool)`, `RET 0x10`) with `BillboardTexture` (default `sign_ad0.dds`) in place of `ad0/1/2.tga`,
then copies the rectangle `BillboardRect` (default `305,680,730,1005`, x0,y0,x1,y1) of the loaded texture into a
new 512×512 texture with the game's own `d3dx9_38.dll` (`D3DXCreateTexture`, `D3DXLoadSurfaceFromSurface`) and
puts it in place of the full sheet (CTexture `+0x18` `IDirect3DTexture9*`, `+0x58` / `+0x5c` width / height).
All other names pass through unchanged. No game art is shipped or written to disk. Live 2026-10-07: the
screens show the plank area.
