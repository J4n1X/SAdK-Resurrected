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

## Map sharing (mod `mods/assetshare`, in memory)

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

The assetshare mod applies these patches in memory at start-up, each only where the original bytes match exactly
(`assetshare.ini [AssetShare] AcceptServerMaps = false` makes a joiner refuse downloads: its temp-file open returns
no file, and `S2Tftp_Session_WriteBlock` S 00426c70 answers the host with the game's own Error 2,
`!TFTP_ERROR_WRITEERROR`):

| Address | Original | Change |
|---|---|---|
| hook `NComm_Manager::SetGameSettings` 0040bfd0 | the map's location type and "download allowed" `0` from `OnMapSelected` | while hosting a network game: type `3` and "download allowed" `1` for every map |
| 0045a381 | `call SelectMapDialog_AppendMapFiles(0, …)` | also lists location 3 (`Documents\SAdK\maps`, warm-tinted rows) |
| 00426b14 | `fopen_s` of the file a peer asked for (S2Tftp_Session_ReadNextBlock) | only `<Documents>\SAdK\maps\<name>.s2m/.bmp` (a map not found there is served from `data\game\maps\Freegamemaps`) and assetshare's own archives below `<Documents>\SAdK\assetshare\` (built on request: the manifest, a server mod, a map file; a `.s2m` with its `<map>.bin`, `<map>.lua` and `<map>_*.lua`) |
| 00427b29, 00427b7e | `rename` of a finished download (S2TftpSession::CloseFile) | only into `Documents\SAdK\maps` as `.s2m/.bmp` or into assetshare's download folder, else the temp file is deleted |
| 00457f51 | `SendPlayerReadyEvent` from the Ready button | refused (sends not-ready) while a download runs or the map is missing — starting without the map crashes the client |
| 00426ca5, 00426d14, 00427a08 | temp-file open, block `fwrite`, abort `remove` | progress messages in the pre-game room; after the last file a not-ready event makes the host re-broadcast, so the joiner finds the map |

**Security note (vanilla game):** without the shim, any peer in a host's match can read any file below the
host's `My Documents` (and above it with `..\`) through this transfer: `S2TftpManager::OnReceive` S 00428110
answers every read request with `My Documents\<requested name>`, unchecked. The shim's filter closes this
for hosts that run assetshare.

## Billboards (mod `mods/billboards`, in memory)

The three advertising screens in the lobby world (`lobby/scene/scene_ad.xml`, models `ad0.KEX` / `ad1.KEX`) are
web pages. Each model has two materials: the board (`sign ad0` → `sign_ad0.dds`) and the screen
(`Material #478` → `ad0.tga` / `ad1.tga` / `ad2.tga`). `Lobby::CGfxTextureMgr::GetTexture` S 00504650 compares
the texture name against those three literals (S 007e6240 / 007e6208 / 007e61d0, read nowhere else) and, on a
match, creates the texture with `S2CE::CTexture::CreateFromURL` S 004e7880: an embedded Internet Explorer
renders `http://www.funatics.de/sadk/forwardingN.html` into it. Those pages return HTTP 404:
`CSDKIEEvents::Invoke` S 005c8a30 answers NavigateError by clearing the texture to red (`ClearTextureToRed`
S 005c7790) and then renders IE's own "navigation canceled" page over it. The `ad*.tga` files the game ships are
never used.

The screen is part of the board mesh, so a transparent screen texture leaves a hole. The billboards mod
(`mods/billboards`, installed into `<game>\mods\billboards` by SAdK-ServerConfig, on unless `[Billboards] Enabled = false` in its `billboards.ini`) instead
shows a plain plank area of the board's own texture. It changes no bytes; it hooks `GetTexture`:

- An entry (`GfxTextureEntry`, 0x24 bytes: `+0` texture, `+4` `std::string` name, `+0x20..0x23` four flags) whose
  texture is not made yet and whose name is `ad0.tga`, `ad1.tga` or `ad2.tga` (compared as the game does,
  case-sensitively) is made by the mod the way `GetTexture` makes every other texture:
  `S2CE::CResourceMgr::CreateTexture(device, 0)` S 004db310, then `CreateFromFile` (texture vtable `+0x28`,
  `bool __thiscall (CTexture*, const std::string *path, bool, bool, bool)`) with the entry's first three flags, and
  `LobbyGfx_Texture_DecrementRedChannel` S 005042e0 when the fourth is set. The path is `Texture`
  (`billboards.ini` next to the mod's `mod.dll`, default `sign_ad0.dds`) instead of the screen's name.
- The rectangle `Rect` (default `305,680,730,1005`, x0,y0,x1,y1) of the loaded texture is copied into a new
  512×512 texture with the game's own `d3dx9_38.dll` (`D3DXCreateTexture`, `D3DXLoadSurfaceFromSurface`) and put
  in place of the full sheet (CTexture `+0x18` `IDirect3DTexture9*`, `+0x58` / `+0x5c` width / height).
- Every other entry goes to the game's `GetTexture` unchanged.

No game art is shipped or written to disk. The earlier version of the mod (literal and call-site patches, same
result) showed the plank area in the game (live 2026-10-07); the hook version is verified against the binary
(`make verify` in `mods/`) and ran in the game (maintainer's test, 2026-10-08: both screens made and cropped, per the log).

## NPC model sets (mod `mods/npcmodels`, in memory)

`Lobby::CGfxObjAvatar::UpdateAppearance` S 00508090 takes an NPC's model from `npc_bodyparts.xml` with
`AvatarBodyParts::AcquireVariant(set, 0, npcidx)` S 004fd2a0 but always passes set 0, so the file's female,
MacDoyleJr and MacGabhan sets are never shown (`docs/village-and-character-protocol.md` §5.1). The NPC
record's `bdyprt` nibble reaches the NPCProxy (`+0x48`, `NPCProxy::ReadFromMessage` S 0047b5c0) and is unused
for NPCs. The npcmodels mod makes it the set number:

| Address | Original | Change |
|---|---|---|
| 005081db (13 bytes) | `MOV EDX,[EAX]; MOV ECX,EAX; MOV EAX,[EDX+0x1C]; XOR EBX,EBX; CALL EAX; MOV EBP,EAX` | `MOVZX EBX,BYTE [EAX+0x48]; MOV EDX,[EAX]; MOV ECX,EAX; CALL [EDX+0x1C]; MOV EBP,EAX` |

`EAX` is the NPCProxy (`ActorProxy::AsType2` S 0046b6d0 returns the proxy itself), `EBX` the set, `EBP` the
NPC index. A record with `bdyprt` 0 behaves as before. There is no bounds check (there was none for the index
either): the server must send only a set that exists and an index below its size (shipped file: male 17, of
which 16 are reachable through the 4-bit `npcidx`; female 6; MacDoyleJr 1; MacGabhan 1). The expected bytes
are verified against the DRM-free `SADK.exe` (`make verify` in `mods/`); the mod works in the game (maintainer's
test, 2026-10-08).


## Mesh cache off (mod `mods/nomeshcache`, hook)

`S2CE::CMesh::Load` S 0076e0d0 (19 callers, every model) reads `%LOCALAPPDATA%\SAdK\<mesh>[_<variant>].mshraw`
(`GetPackedCachePath` S 0076c9f0) when `IsPackedCacheUpToDate` S 0076cbe0 finds it newer than the `.KEX`
(`File_CompareWriteTime` S 006e7270), and writes a new one after converting (`SavePackedBinary` S 0076bdc0), unless
its last argument `noCache` is set. The callers checked (`LoadMesh` 0050b68b, `AcquireMesh` 006945ba,
`LoadItemTypeMesh` 0069dc80) pass 0. The mod hooks `CMesh::Load` and passes `noCache = true`. `engine.ini`
`[Engine] useMeshCache` (read into `CGraphicDevice+0xc9` by `CGraphicDevice::Init` S 004da2a0) is not what those
callers use; its reader is [TODO]. In the game (maintainer's test, 2026-10-08) the mod works, but the lobby town flickers while it is on;
the cause is not investigated.

## Map without a preview picture (mod `mods/nopreview`, hooks)

`LobbyMenu::SetupGameDialog::UpdateMapPreviewImage` S 00454fc0 (hosting) and
`nMenu::FreeGamePanel::UpdateMapPreviewImage` S 005e7220 (offline free game) are the same code. When the chosen map
differs from `previewMapName`, the previous preview texture is destroyed (`UiResourceManager::ReleaseTexture`
S 00493ae0 → `CResourceMgr::DestroyTexture` S 004daf10: destructor and `free`) and the name is cleared. Only when the
new map's `<map>.bmp` exists (`Fs_FileExists`) is a texture loaded (`PreloadMapPreviewTexture` S 00494610), stored in
the `MapPreview` widget's `shape.texture` (`nUi::ShapedObject` `+0x198`, `nUi::Shape` `+0x14`) and the name set again.
For a map without a `.bmp` the widget keeps the pointer to the destroyed texture and stays visible, so the next frame
draws it: `UiSprite_RenderToOwnerRect` S 004aa310 only tests the pointer, and `S2CE::CTexture::LinkToStage` S 004e7520
reads the texture's device at 004e7562. `[known]` (static). A player's crash dump (2026-10-10, hosting a custom map)
shows this call stack with a null device and a null D3D texture; that the map had no `.bmp` is `[inferred]`. All 20
shipped free-game maps have a `.bmp`, so only custom maps are affected.

The mod hooks both functions: when a call cleared a non-empty `previewMapName` and stored none, it sets the widget's
`shape.texture` to null, and the preview area stays empty. Verified against the DRM-free `SADK.exe` (`make verify`
in `mods/`); in the game `[TODO]`.

## Borderless fullscreen (mod `mods/borderless`, hooks)

`S2CE::CGraphicDevice` keeps its display settings as a 9-dword block at `+0xa8`: width, height, and in the third
dword's low byte the windowed flag (`+0xb0`); `+0xc8` marks a window the game does not own. The block is the game's
own graphics configuration: `S2CG::Settings::Load` S 006960a0 reads it from the player's profile and applies it
(`ApplyDisplayMode`), the options change it (`SetDisplaySize` S 00695ab0), and `Settings::Store` S 00696270 writes the
device's block back into the profile. The options also read it (`FillVideoModeCombo`, `LoadOptionValue`). So a mod
must not change the flag: it would be saved and shown as "windowed".

`CGraphicDevice::Init` S 004da2a0 takes the block; `InitPresentParameter` S 004d3f70 (at creation and every reset,
e.g. a resolution change) builds the D3D present parameters: windowed → `Windowed = 1`, fullscreen → the display
mode nearest the requested size with its refresh rate. `ApplyWindowStyle` S 004d4190 shapes the window (windowed: a
caption window sized to the backbuffer; fullscreen: a topmost popup at 0,0).

The mod leaves the block alone and hooks:
- `InitPresentParameter`: after the game has filled in its fullscreen parameters, `Windowed = 1` and
  `FullScreen_RefreshRateInHz = 0` (required for a windowed device). The backbuffer keeps the game's resolution;
  Direct3D stretches it to the window.
- `ApplyWindowStyle`: in fullscreen, a `WS_POPUP` covering the monitor from `borderless.ini` `[Borderless] Monitor`
  (`primary`, or n for `\\.\DISPLAYn`), not topmost.
- The fullscreen-only cursor paths, which take screen pixels of a mode at 0,0: `UiCursor_QueryRelativePosition`
  S 00492410, `nUi::Cursor::SetPixelPosition` S 00492620, `WarpToPosition` S 004926d0. Around these calls the
  windowed flag reads 1, so they use the window's client area. (`nUi::Cursor::SetPositionFromPixels` S 00492300
  always divides by the client size.)
- The lobby's mouse look (right button): `LobbyMenu::LobbyAction` warps the cursor to the centre of the client area
  (`clientWidth/Height` from `GetClientRect`) and measures the offset from it each frame, but its `OnMouseMove`
  S 00429360 receives picture pixels (`LobbyDesktop::OnMouseMove` S 0042e8c0: relative cursor position ×
  `nUi_RelativeToPixelsX/Y`). Stretched, the offset never reaches zero and the camera keeps turning (seen live
  2026-10-08); in borderless mode the mod passes the cursor's real client position (`GetCursorPos` +
  `ScreenToClient`).

Live 2026-10-08: the first version set the windowed flag, so resolution changes in the options did not apply and
the flag ended up in the settings; the lobby's mouse look then turned continuously. The version described here
fixes both and works in the game (maintainer's test, 2026-10-08).

## Windows cursor (mod `mods/oscursor`, hooks)

`engine.ini` `[Engine] hardwareCursor` (`data\game\settings\engine.ini`, the game's `[data]\settings\engine.ini`
through `FileScanHolder::ResolvePath` S 006e3fd0) is read once, when `S2CE::CGraphicDevice::Init` S 004da2a0 first
creates the device, into `CGraphicDevice+0xbd` (default 1; not read for an external window, `+0xc8`).
- **1:** `SetHWCursor` S 004d6b50 loads `gfx\Mousecursors_MainCursor.tga` (or `engine.xml`'s `hwCursor`) into a
  texture and sets `bHwCursorLoaded` (`+0x4b0`). The cursors of `game\ui\layout\cursors.xml` (arrow, animated
  clock, build cursor; all 32×32, 32-bit TGA) are textures too: `HwCursorSlot::LoadFromFile` S 004d4b70, managed
  pool, the file's format. `nUi::Cursor::SelectCursor` S 00492960 switches them through `SetCustomCursor`
  S 004d6ca0 (only with `+0x4b0` set). `Show`/`Hide` go through `ShowHWCursor` S 004d69d0, which calls
  `SetCursorProperties`, `SetCursor(NULL)` and `IDirect3DDevice9::ShowCursor`. On `WM_SETCURSOR`,
  `HandleWindowMessage` S 004da8d0 calls `ShowHWCursor(true)` again while the cursor is visible.
- **0:** the Windows arrow (`LoadCursor(IDC_ARROW)` into `+0x1b0`), set on `WM_SETCURSOR`. Cursor changes do nothing
  (`SetCustomCursor` needs `+0x4b0`), and `ShowHWCursor` returns early without a cursor texture.

Direct3D 9 only shows such a cursor as a Windows cursor when its size is the system cursor size: 32×32 up to 125%
display scaling, 48×48 from 150%
([SetCursorProperties](https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-idirect3ddevice9-setcursorproperties),
[About Cursors](https://learn.microsoft.com/en-us/windows/win32/menurc/about-cursors)). Otherwise Direct3D draws the
cursor itself. PCGamingWiki reports an invisible pointer above 125% scaling for The Settlers II 10th Anniversary, the
same engine. [TODO, live] Which of the paths an affected PC takes.

The mod makes a Windows cursor (`CreateIconIndirect`, 32-bit colour with alpha) from each cursor texture's level 0
and the slot's hotspot, and sets it with `SetCursor` where the game shows its Direct3D cursor:
- `ShowHWCursor` (`bHwCursorVisible` `+0x4b1` kept);
- `SetCustomCursor`, after the game's slot bookkeeping (cursor changes and the clock's animation);
- `WM_SETCURSOR` in the client area (`HTCLIENT`; a window frame keeps Windows' cursors).

Direct3D's `ShowCursor` is never called, so its cursor stays hidden. With `hardwareCursor = 0` (no `+0x4b0`), or for
a texture that is not A8R8G8B8 or X8R8G8B8, the game's own code runs.
