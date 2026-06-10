# Driving the Ghidra MCP debugger

Live (dynamic) reverse-engineering is done through the **Ghidra MCP**, not standalone
scripts. The `bethington/ghidra-mcp` fork exposes `debugger_*` tools (launch/attach,
breakpoints, read registers/memory/args, step). Claude drives the breakpoints over the
MCP; you keep Ghidra + the game running.

## Setup (user)

0. **Start the ghidra-mcp debugger server first.** The `debugger_*` MCP tools proxy to a
   standalone server (default `http://127.0.0.1:8099`, `GHIDRA_DEBUGGER_URL`) that bridges
   to Ghidra's TraceRMI/dbgeng. If it isn't running, every debugger tool errors
   ("Debugger server not running at :8099"). Start it from the ghidra-mcp repo. Do **not**
   also manually attach via the Ghidra dbgeng UI — let the MCP drive the attach
   (`debugger_attach`), or they conflict (one debugger per process).
   - **pybag gotcha:** Ghidra's dbgeng launcher needs `pybag>=2.2.12` in the same Python it
     invokes. On "INCORRECT OR INCOMPLETE SETUP", accept auto-resolution, relaunch.
1. Start the stub: `python -m sadk_lobby`.
2. Launch SADK.exe (elevated; on Win10/11 it boots past SecuROM via the two patches in
   `docs/BINARY_PATCHES.md`) and reach the login screen. Then tell Claude — it calls
   `debugger_attach(target="SADK.exe")`, sets breakpoints, and you drive the game.

## Working notes `[PROVEN]`

- Ghidra static addresses line up 1:1 with runtime (`SADK.exe` base `0x400000`,
  `tincat3.dll` `0x10000000`).
- LobbyManager state ladder: `1` Disconnected · `3` Authorized · `6` LoadingGlobalData ·
  `8` EnteringVillage (waits for server-pushed EnterWorld 1000) · `9` VillageEntered ·
  `11` Left. `LobbyManager::GetStateName` @ `FUN_00462bc0`; the enum is in `RENAME_LIST.md`.
- vtable slot → function mappings need the **live** DLL (vtables are data, not in a static
  export) — a prime reason to use the MCP debugger rather than reading offline dumps.

## What you may NOT do

Per HARNESS §1, do not script `ReadProcessMemory`, byte-patches, or force-calls to work
around a missing capability. If the MCP debugger lacks something you need, add/extend a
debugger MCP — don't write a Python probe/injector.
