# Connect Claude to Ghidra — runbook (bethington/ghidra-mcp)

Live link so Claude can read/rename/comment **and create structs/classes/enums + apply
types** in your Ghidra project. Using <https://github.com/bethington/ghidra-mcp> — a
rewritten GhidraMCP with ~245 tools that **targets Ghidra 12.1** natively (build against
your install → no version-patch hacks). Plugin port **8089**; bridge transport **stdio**.

## Prerequisites
- **JDK 21** — Ghidra 12.1 already needs it, so you have it. Point Maven at it if needed
  (`JAVA_HOME` = your JDK 21 path).
- **Maven 3.9+** — install it (e.g. `winget install Apache.Maven`, or scoop/choco).
- **Python** — already have it (you run the stub server).
- Know your Ghidra install path, e.g. `C:\ghidra_12.1_PUBLIC`.

## 1. Clone + build + deploy the plugin
Clone the plugin somewhere on your machine (`<your-tools-dir>\ghidra-mcp`):
```
git clone https://github.com/bethington/ghidra-mcp <your-tools-dir>\ghidra-mcp
cd <your-tools-dir>\ghidra-mcp
python -m tools.setup ensure-prereqs --ghidra-path "C:\ghidra_12.1_PUBLIC"
python -m tools.setup build
python -m tools.setup deploy --ghidra-path "C:\ghidra_12.1_PUBLIC"
```
`deploy` installs the extension into Ghidra for you. **Follow the repo README if any
command name differs** — it's actively developed.

## 2. Enable the plugin in Ghidra
1. **Restart Ghidra.**
2. Open **SADK.exe** (double-click the program → CodeBrowser opens).
3. `File → Configure` → click **Configure All Plugins** (the plug/list icon, top-right) →
   filter **MCP** → tick the GhidraMCP plugin → OK.
4. The HTTP server should now listen on `127.0.0.1:8089` (check `Edit → Tool Options` if
   there's an MCP server entry).

## 3. Bridge Python deps
From the cloned repo (it may ship a requirements file):
```
pip install -r requirements.txt      # or: pip install mcp requests
```

## 4. Register with Claude Code
`.mcp.json` at the project root now points at the in-repo bridge
`decomp/bridge_mcp_ghidra.py` over stdio, so no per-machine path edit is needed there.
(If you instead want to run the bridge from your own `<your-tools-dir>\ghidra-mcp`
clone, update the `args` path in `.mcp.json` to that copy.)

## 5. Activate + verify
- **Restart the Claude Code session** in this folder → **approve** the `ghidra` MCP server
  when prompted.
- Run **`/mcp`** → `ghidra` should be **connected** (Ghidra open, plugin enabled, SADK.exe
  loaded).
- Tell Claude "you're connected." It will `list_methods`/`list_namespaces` to confirm, then
  apply `RENAME_LIST.md`: create the `LobbyManager` / `LobbyVillageScreen` / `ServerListEntry`
  structs + the `LobbyManagerState` enum, set `__thiscall` prototypes, rename, and chase the
  state-setter via xrefs — live.

## Troubleshooting
- **Bridge can't reach Ghidra:** confirm the plugin is enabled and on **8089**. If the bridge
  needs an explicit URL, add `"--ghidra-server", "http://127.0.0.1:8089/"` to the `args` in
  `.mcp.json` (check the repo README for the exact flag name).
- **Maven uses the wrong Java:** set `JAVA_HOME` to your JDK 21 and reopen the shell.
- **`python` not found:** use `py` or the full path in `.mcp.json`'s `command`.
- Keep Ghidra open with SADK.exe focused while we work — the link acts on the active program.
