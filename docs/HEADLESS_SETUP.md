# Headless Ghidra + Ghidra Server + MCP on Linux — reproducible runbook

This documents the **headless** RE backend that runs on the Linux box (`linux-server`),
so a future clone can reproduce it. It complements the Windows-GUI runbook in
[`decomp/GHIDRA_MCP_SETUP.md`](../decomp/GHIDRA_MCP_SETUP.md).

The stack, bottom to top:

```
Ghidra Server (systemd, :13100)  ──canonical `sadk` repo──┐
                                                          │  (mcp user, password auth)
GhidraMCP headless server (:8089, on-demand) ────────────┘
        ▲ HTTP
decomp/bridge_mcp_ghidra.py  (MCP stdio bridge, .mcp.json)
        ▲ stdio
Claude Code
```

Everything below assumes the Ghidra install at `~/ghidra_12.1_PUBLIC` and the repo at
`~/projects/sadk-resurrected`.

---

## 0. One-time host prerequisites

- **JDK 21** (Ghidra 12.1 requires it): `sudo apt-get install -y openjdk-21-jdk` →
  `/usr/lib/jvm/java-21-openjdk-amd64`. Export `JAVA_HOME` to it for every Ghidra/Maven command.
- **Exec bits**: if the Ghidra install was copied via SFTP from Windows, the exec bits are
  stripped. Restore them: `chmod +x` on `support/*.sh`, `ghidraRun`, `server/{ghidraSvr,svrAdmin,svrInstall}`,
  and every file under any `os/linux_x86_64/` dir (decompiler `decompile`/`sleigh`, demangler).
- **Maven** (for building the MCP jar), no root needed: download the Apache Maven 3.9.x binary
  tarball, extract to `~/apache-maven-3.9.9`, use `~/apache-maven-3.9.9/bin/mvn`.

## 1. Ghidra Server (canonical repo)

The canonical project lives in a **Ghidra Server** repository named `sadk`, served on this box.
See [the server memory] for the full story; key points:

- `server/server.conf` parameters: `-a0` (password auth), `-u` (prompt for user ID, so clients
  log in as an account rather than their OS username), `-ip 127.0.0.1` (so a remote Windows GUI
  reaches it over an SSH tunnel; use the LAN IP for direct LAN access).
- Runs as a **systemd service** (`/etc/systemd/system/ghidra-server.service`, `User=user`,
  `ExecStart=…/server/ghidraSvr console`, `Type=simple`). Persistent across reboots.
- Accounts (`server/svrAdmin`): `sadk` (the Windows GUI), `mcp` (the headless MCP — write access
  to the `sadk` repo via `svrAdmin -grant mcp +w sadk`). New accounts get default password
  `changeme` and **must change it on first login** (GhidraMCP can't do that change, so a human
  sets it once via a GUI login, then drops it in `~/.ghidra-cred`).

## 2. Build the GhidraMCP headless server (one-time)

GhidraMCP (bethington fork) ships only the GUI extension prebuilt; the headless server
(`com.xebyte.headless.GhidraMCPHeadlessServer`) must be built from source.

```bash
git clone https://github.com/bethington/ghidra-mcp ~/ghidra-mcp
cd ~/ghidra-mcp
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export GHIDRA_INSTALL_DIR=~/ghidra_12.1_PUBLIC
export PATH=~/apache-maven-3.9.9/bin:$PATH

python3 -m tools.setup install-ghidra-deps --ghidra-path "$GHIDRA_INSTALL_DIR"   # Ghidra jars → ~/.m2
mvn -Pheadless clean package -DskipTests                                         # → target/GhidraMCP-<ver>.jar
```

The `headless` Maven **profile is required** — the default profile builds only the GUI plugin jar.
Output: `~/ghidra-mcp/target/GhidraMCP-5.13.1.jar` (a fat jar minus Ghidra's own jars, which are
supplied on the classpath at runtime).

## 3. The bridge (already wired in the repo)

`.mcp.json` launches the bridge with the repo venv:

```json
{ "mcpServers": { "ghidra": { "command": ".venv/bin/python", "args": ["decomp/bridge_mcp_ghidra.py"] } } }
```

- `decomp/bridge_mcp_ghidra.py` is kept **version-matched** to the built backend (sync it from
  `~/ghidra-mcp/bridge_mcp_ghidra.py` after a backend upgrade — the CLI/route set changes between versions).
- Bridge deps (`mcp`, `requests`) are in `.venv` (see `setup_venv.sh`). The backend URL defaults
  to `http://127.0.0.1:8089`.

## 4. The backend lifecycle is tied to the MCP server (auto start/stop)

The headless backend is **spawned and torn down by the bridge**, so it lives exactly as long as the
Claude Code `ghidra` MCP server: it comes up when a session connects and dies when the session ends —
no manual start/stop, and not a systemd service.

How it's wired (patch in `decomp/bridge_mcp_ghidra.py`):
- `.mcp.json` sets `env: { "GHIDRA_MCP_AUTOSTART": "1" }`.
- On startup the bridge's `_start_backend()` runs `~/ghidra-mcp/run-headless-sadk.sh` (override with
  `GHIDRA_MCP_BACKEND_CMD`), waits up to `GHIDRA_MCP_BACKEND_WAIT` (45s) for `:8089`, then
  `_auto_connect()` registers all ~192 `ghidra` tools.
- On bridge exit/`SIGTERM` (`atexit` + signal handler) `_stop_backend()` kills the backend's process
  group. If a backend is already on `:8089` it attaches instead of spawning (and doesn't own teardown).
- The launcher clears a **stale project lock** (`sadk-shared.lock`) on start — a killed backend leaves
  one and it would block the next boot. Safe: only this headless backend ever opens `sadk-shared`.

So the normal flow is just: **connect the `ghidra` MCP server (once per session) → use the tools.**
The backend is already there. `connect_instance` is the manual fallback if you ever start a backend
yourself. `curl localhost:8089/...` is only a health check, never how RE is done.

The launcher (`~/ghidra-mcp/run-headless-sadk.sh`) runs the server in **shared-repo mode**
(`GHIDRA_SERVER_USER=mcp`, password from `~/.ghidra-cred`).

## 5. Loading a repo program into the live tools — the server-bound project (one-time)

The 191 live tools (decompile/rename/xrefs/…) operate on an **open program** in an **open project**.
GhidraMCP headless can `/server/connect` and do repo file ops, but it **cannot open a `ghidra://`
repo as a project** and **cannot create a server-bound project** itself (`open_project` is
local-only — upstream headless-parity gap #119). The bridge is a **server-bound project working copy**
created **once** — the headless equivalent of the GUI "Convert to Shared", via
`ProjectData.convertProjectToShared(repo, monitor)` (present in 12.1).

The one-time command (creates an empty project, binds it to the `sadk` repo as `mcp`):

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
mkdir -p ~/ghidra-mcp-projects
~/ghidra_12.1_PUBLIC/support/analyzeHeadless ~/ghidra-mcp-projects sadk-shared \
  -preScript ConvertToShared.java -scriptPath ~/ghidra-mcp/setup-scripts -noanalysis
```

`setup-scripts/ConvertToShared.java` (in the `~/ghidra-mcp` clone) reads the `mcp` password from
`~/.ghidra-cred`, connects, and binds the new project. Result: `~/ghidra-mcp-projects/sadk-shared.gpr`
with `project.prp` recording `SERVER=127.0.0.1 / REPOSITORY_NAME=sadk / PORT=13100`.

The launcher (`run-headless-sadk.sh`) then opens it via `--project ~/ghidra-mcp-projects/sadk-shared.gpr`
(point at the **`.gpr` file**, not the dir). **Verified working:** `get_project_info` →
`project_server_bound: true, server_repo: sadk, program_count: 22`; `load_program_from_project
{"path":"/SADK.exe"}` → `success` with the analyzed program (renames/comments intact); decompile works.

## 6. Persisting edits back to the repo — local patch (write side of #119)

Stock GhidraMCP opens repo programs **read-only** (`load_program_from_project` → `getDomainObject`
with no checkout), so `save_program` fails ("Location does not exist for a save operation") and there
is no checkin tool — edits are lost on unload. We patched the **local clone** (`~/ghidra-mcp`) and
rebuilt the jar (`mvn -Pheadless clean package -DskipTests`):

- **`HeadlessProgramProvider.java`** — `loadProgramFromProjectDetailed` now `domainFile.checkout(false, monitor)`
  (non-exclusive) on a versioned, not-yet-checked-out file *before* `getDomainObject`, so the program is
  writable. Added a `checkinProgram(name, comment, keepCheckedOut)` method: `save()` then
  `DomainFile.checkin(CheckinHandler, monitor)`.
- **`HeadlessManagementService.java`** — new `@McpTool /checkin_program` endpoint (auto-registered by the
  `AnnotationScanner`) wrapping it.

**Write workflow:** `load_program_from_project` → edit via MCP tools (e.g. `add_struct_field`) →
`checkin_program(comment="…")` → a new repo version is created (canonical; the Windows GUI sees it on
update). **Proven:** the `LobbyManager`/`LobbyVillageScreen` `pVtable@0` edits were checked in as
**SADK.exe version 2**. A fresh clone must re-apply this patch and rebuild (or it should be upstreamed).
`keep_checked_out=true` (default) leaves a non-exclusive checkout so the next session opens read-write.

> Batch alternative: `analyzeHeadless ghidra://127.0.0.1:13100/sadk <prog> -connect mcp …` works
> directly against the shared repo with no local project (good for scripted passes), but it is not the live MCP.

## 6. Quick clean-state check

```bash
ss -tlnp | grep ':13100'   # Ghidra Server (systemd) — should be UP
ss -tlnp | grep ':8089'    # MCP backend — UP only while in use (on-demand)
```

## 7. MCP on Windows (the live-debug host)

The Linux box does **static** RE. **Live debugging the game must run on Windows** (the game is a
Win32 process; the Ghidra Debugger has to attach locally). The bridge is portable, but the
Linux-specific **config** is not — change these on the Windows checkout:

1. **`.mcp.json` `command`.** The committed value is the Linux venv (`.venv/bin/python`). On Windows
   it must be `.venv\Scripts\python.exe` (or just `python` on PATH). This is the hard blocker —
   without it the MCP server itself won't launch.
2. **Backend auto-start.** The bridge spawn is now platform-aware: on Windows `GHIDRA_MCP_AUTOSTART=1`
   resolves to `~/ghidra-mcp/run-headless-sadk.bat` and is run via `cmd /c` (no bash). You must
   **author that `.bat`** — the Windows analogue of `run-headless-sadk.sh`: set `JAVA_HOME` to the
   Windows JDK21, point at the Windows Ghidra install + the patched `GhidraMCP-5.13.1.jar`, and set
   `GHIDRA_SERVER_HOST` to the **Linux box's LAN IP (192.168.1.130), not 127.0.0.1**, user `mcp`,
   password from the cred file. Then `connect_instance` registers the tools as on Linux.
   - If you don't want auto-start, **unset `GHIDRA_MCP_AUTOSTART`** and start the backend by hand;
     the bridge then just connects to the running `:8089` (fully portable, unchanged upstream path).
3. **Patched jar.** The checkout/checkin write-back patch (§5) must be built/copied on Windows **only
   if you need write-back**. For read-only live tracing you can skip it.
4. **The Debugger.** GhidraMCP's `debugger_*` tools need Ghidra's **Debugger module + a working
   Windows connector** (attach to the local game process) — that is the part that fundamentally must
   live on Windows. Loading `sadk_noav.exe` from the shared repo (same as Linux) gives the live
   session all our annotations; the debugger then maps breakpoints onto it. See
   `docs/MATCH_START.md` → *Live debug plan* for the exact breakpoints/targets.

> TL;DR on "will the modded bridge run on Windows?" — **yes, the Python is portable now** (the only
> Windows-hostile bit, a hardcoded `bash` spawn, is fixed and gated). What is *not* portable is the
> committed `.mcp.json` venv path and the absence of a Windows `.bat` launcher — both are config you
> set up once on the Windows host per the steps above.
