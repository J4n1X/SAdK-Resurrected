# decomp/ — Ghidra decompiles + navigation indexes

Ghidra "Export as C/C++" dumps of the two binaries, plus indexes generated from them.
**Nothing is manually labelled** — names are auto-generated (`FUN_<addr>`, `DAT_<addr>`,
`LAB_<addr>`). The way in is (a) the inlined **string literals** and (b) the original
C++ **`__FILE__` / log strings** the compiler left in (e.g. `LobbyVillageServerList.cpp`,
`LobbyComm::System::CreateVillageServerConnection`). Those reveal real class/file names
even with zero labelling.

## Files

| File | What |
|------|------|
| `sadk/SADK.exe.c` / `.h` | Decompiled game client (~1.2M lines, ~38.8k functions). |
| `tincat/tincat3.dll.c` / `.h` | Decompiled network library (~57k lines, ~1.7k functions). |
| `extract_index.py` | Regenerates the indexes below from any Ghidra C export. |
| `*_functions.tsv` | `addr · c_line · n_lines · n_strings · signature` — the function list. |
| `*_strings.tsv` | `func_addr · func_line · string` — every inlined literal, mapped to its function. |
| `*_strings_uniq.txt` | Sorted unique string literals — the program's vocabulary. |

`addr` is the function's virtual address (from its `FUN_`/`LAB_` name; blank for
RTTI/library functions). `c_line` is the 1-based line of the signature in the `.c`, so
you can jump straight there (Read offset / editor goto).

## Regenerate

```
python decomp/extract_index.py decomp/sadk/SADK.exe.c decomp/tincat/tincat3.dll.c
```

The parser relies on Ghidra's fixed layout: column-0 signature → blank → column-0 `{`
→ indented body → column-0 `}` (nested braces are always indented, so the col-0 `}` is
the function end). Re-run it after any fresh export.

## How to navigate by "vibe"

1. **Start from strings.** Grep `*_strings_uniq.txt` for a concept (`village`, `chat`,
   `connect`, a UI key like `!ENTER_VILLAGE_BUTTON`, a `.cpp` filename, an error message).
2. **Map string → function.** Grep `*_strings.tsv` for the hit to get `func_addr` +
   `func_line`.
3. **Read the function** at `func_line` in the `.c`. Follow `FUN_<addr>` calls; look each
   up in `*_functions.tsv` (or just grep the `.c` for `FUN_<addr>(`).
4. **Callers/callees:** `grep "FUN_<addr>(" *.c` finds every call site.

## Key leads found (lobby-world entry)

The greyed **"Suche Server…"** button is internally the **VILLAGE** (3D lobby world).
Search `VILLAGE`, not "Suche Server".

**Conclusion (traced s3):** the button is greyed (`!LOBBY_LOADING_SERVERS`) until the
client holds a **ready village server list**; it then reads `!ENTER_VILLAGE_BUTTON`, and
connecting needs a listed entry whose RoomId/LobbyId matches the selected
`g_SelectedVillageRoomId` (`DAT_0087d580`) or you get `!COULDNOT_CONNECT_TO_VILLAGE`.
⇒ feed a byte-perfect ServerType=4 `GameServerData(170)` with the expected LobbyId. Full
write-up + actions in **`SESSION_STATUS.md`** (DECOMP FINDING s3); all addresses, labels,
struct offsets, and the `LobbyManagerState` enum in **`RENAME_LIST.md`**.

Anchor functions: `FUN_00439e80` UpdateEnterButton · `FUN_0043ab10` OnVillageConnectFailed ·
`FUN_00462bc0` LobbyManager::GetStateName · `FUN_00463750` CreateVillageServerConnection ·
`FUN_00468d80` FindByRoomId. The text-gate predicate is the **unrecovered jump table at
`0x4682d0`** — recover it in Ghidra to confirm "list count > 0".
