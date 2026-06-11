# decomp/ — Ghidra link + RE references

Reverse-engineering is done through the **Ghidra MCP** (see `GHIDRA_MCP_SETUP.md`).
All decompilation, xrefs, renaming, struct/enum work, and live debugging go through
the MCP — not standalone scripts (HARNESS §1).

## Files

| File | What |
|------|------|
| `GHIDRA_MCP_SETUP.md` | Runbook to connect Claude to Ghidra over the MCP (bethington/ghidra-mcp, ~245 tools incl. `debugger_*`). |
| `RE_PRACTICES.md` | **Mandatory** RE standard: typing, vtable structs, RTTI-first, one-layer rule, runtime-virtual escalation, map upkeep. |
| `DEBUGGER_PLAN.md` | How to drive the Ghidra MCP debugger (launch/attach, breakpoints, read regs/mem). |
| `RENAME_LIST.md` | Applied labels, structs (`LobbyManager`, `VillageServerConnection`, …), and the `LobbyManagerState` enum. |
| `bridge_mcp_ghidra.py` | The MCP bridge `.mcp.json` points at. Infrastructure, not an RE script. |

Offline "Export as C/C++" dumps of `SADK.exe` / `tincat3.dll` are **gitignored** (large,
game-derived). If you keep local copies, treat them only as a grep convenience; the
authoritative, current view is the loaded program via the MCP.

## How to navigate

1. **Start from strings.** The compiler left `__FILE__` / log strings in (e.g.
   `LobbyVillageServerList.cpp`, `LobbyComm::System::CreateVillageServerConnection`),
   which reveal real class/file names even on auto-named functions. Search them via the
   MCP.
2. **String → function → callers/callees.** Follow xrefs through the MCP.

### Key leads (lobby-world entry) `[PROVEN]`

The greyed "Suche Server…" button is internally the **VILLAGE** (3D lobby world) — search
`VILLAGE`. It enables once the client holds a ready village server list, then connecting
needs a listed entry whose roomId matches the selected `g_SelectedVillageRoomId`
(`DAT_0087d580`). Anchor functions: `FUN_00439e80` UpdateEnterButton ·
`FUN_0043ab10` OnVillageConnectFailed · `FUN_00462bc0` LobbyManager::GetStateName ·
`FUN_00463750` CreateVillageServerConnection · `FUN_00468d80` FindByRoomId. Struct
offsets + the `LobbyManagerState` enum are in `RENAME_LIST.md`.
