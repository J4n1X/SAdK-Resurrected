# SAdK-ServerConfig

A small Win32 tool (Windows 7 and later, no runtime needed) that points a "Die Siedler - Aufbruch der
Kulturen" install at a revival lobby server and installs the bridge shim.

- **Game folder:** detected automatically (the tool's own folder, the Windows uninstall entries in both
  registry views, then `<drive>:\Program Files (x86)\` and `<drive>:\Program Files\` + `Ubisoft\Die Siedler -
  Aufbruch der Kulturen` on every drive), or chosen with `...`. The install folder or its `bin` both work.
- **Modified check:** recomputes the game's own build checksum (`GameData_ComputeBuildChecksum` S 005ab800):
  XOR over `data\game` and `data\lobby` → `scripts\**\*.lua` and `settings\**\*.xml` (encrypted files: the
  header CRC; plain files: size XOR first dword). Joiners whose value differs from the host's are kicked with
  `!CHECKSUM MISMATCH`, so a different value means only players with the same modifications can play
  together. Reference `0x555bfa51` = the unmodified data (computed from the repo's reference install).
- **Save** writes, with the Windows INI functions the game itself reads them with:
  `data\lobby\config\LobbySettings.ini [LobbyServer] Host / Port / ForceBridge`,
  `data\game\settings\network.ini [Basics] gamePort`, `bin\sadk_bridge.ini [Bridge] port`,
  and installs the embedded shim as `bin\wsock32.dll` when it is missing or different.
- Ports are only editable with "Advanced configuration" ticked. The tool asks for admin rights: the game
  lives under Program Files, and without them Windows would silently redirect the writes elsewhere.

Build (Linux, mingw-w64): `make` (builds the shim first if needed) -> `SAdK-ServerConfig.exe`.
