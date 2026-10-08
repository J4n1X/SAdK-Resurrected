# SAdK-ServerConfig

A small Win32 tool (Windows 7 and later, no runtime needed) that points a "Die Siedler - Aufbruch der
Kulturen" install at a revival lobby server and installs the shim (the mod host) with the mods every player
needs.

- **Game folder:** detected automatically (the tool's own folder, the Windows uninstall entries in both
  registry views, then `<drive>:\Program Files (x86)\` and `<drive>:\Program Files\` + `Ubisoft\Die Siedler -
  Aufbruch der Kulturen` on every drive), or chosen with `...`. The install folder or its `bin` both work.
- **Modified check:** recomputes the game's own build checksum (`GameData_ComputeBuildChecksum` S 005ab800):
  XOR over `data\game` and `data\lobby` → `scripts\**\*.lua` and `settings\**\*.xml` (encrypted files: the
  header CRC; plain files: size XOR first dword). Joiners whose value differs from the host's are kicked with
  `!CHECKSUM MISMATCH`, so a different value means only players with the same modifications can play
  together. Reference `0x555bfa51` = the unmodified data (computed from the repo's reference install).
- **Save** writes, with the Windows INI functions the game itself reads them with:
  `data\lobby\config\LobbySettings.ini [LobbyServer] Host / Port`, `data\game\settings\network.ini [Basics]
  gamePort`, and the mods' settings (below), and installs the embedded shim as `bin\wsock32.dll` when it is
  missing or different.
- **Shim and mods only on the DRM-free build:** they call game functions at fixed addresses, so they are installed
  only when `bin\SADK.exe` has MD5 `d4832bc5103c14f5445471af29b8d778` (the DRM-free build). On any other
  build Save writes the settings but not the shim, and says why.
- **Mods** (embedded, installed on the DRM-free build): `mods\gamebridge` (hosting through the server; "Bridge
  port" and "Always host through the bridge" are `[Bridge] Port` / `ForceBridge` in its `gamebridge.ini`),
  `mods\assetshare` (map sharing; `assetshare.ini` as shipped) and `mods\billboards` ("Disable billboards" is
  `[Billboards] Enabled` in its `billboards.ini`; ticked when nothing was chosen yet: the pages behind the lobby's
  advertising screens are gone for everyone). A `mod.dll` is replaced when it differs from the embedded one; an
  `.ini` is created from the shipped default only when missing, and then only the keys above are written. The
  older settings `ForceBridge` in `LobbySettings.ini` and `bin\sadk_bridge.ini` are no longer read. An install that still has `mods\gamehostbridge` (the mod's earlier name) gets it replaced: its `.ini` moves to
  `mods\gamebridge` when there is none there yet, and the old folder is removed, since both would tag the same
  connections.
- Ports are only editable with "Advanced configuration" ticked. The tool asks for admin rights: the game
  lives under Program Files, and without them Windows would silently redirect the writes elsewhere.

Build (Linux, mingw-w64): `make` (builds the shim and the mods first if needed) -> `SAdK-ServerConfig.exe`.
