# decomp/ — how the Ghidra map is made

Reverse engineering runs through the **Ghidra MCP** (static) and the **Frida MCP** (live), never through
standalone scripts (`HARNESS.md` §1). The map itself is the Ghidra Server repository `sadk` (programs
`/sadk_noav.exe`, `/tincat3.dll`, `/NXCHARACTER.DLL`; never `/SADK.exe`), published as `sadkmod/sourcemap/`.

| File | What |
|------|------|
| `RE_PRACTICES.md` | **Mandatory.** The RE standard behind `HARNESS.md` §6: where the map lives and what is authoritative, typing and calling conventions, vftable structs, measure-then-read, writing to the map (one writer per struct, check-in), keeping the sourcemap current, map before mod code, runtime-resolved calls, class hygiene. |
| `RENAME_LIST.md` | A dated log of hand renames and their evidence, 2026-06 to 2026-10. History only: nothing new is added to it, and its older addresses may be dump-base ones. Read it as evidence to check. |

Elsewhere:
- Setup of the Ghidra MCP, the Ghidra Server and troubleshooting: `docs/HEADLESS_SETUP.md`.
- The mapping pipeline (inventory, batches, the change queue and its single writer, measurement scripts):
  `mapping/README.md`, `mapping/AGENT_GUIDE.md`.
- Names and roles of the lobby, village and match-network code: `docs/SOURCEMAP.md`; classes and structs:
  `docs/types.md`.
- Live debugging: `docs/LIVE_DEBUG_RUNBOOK.md`.

Offline "Export as C/C++" dumps of the binaries are gitignored (large, game-derived). Treat a local copy only as a
grep convenience; the current view is the program through the MCP.
