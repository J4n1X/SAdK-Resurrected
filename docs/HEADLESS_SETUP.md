# Ghidra MCP: the headless setup on the Linux server

All reverse engineering goes through the Ghidra MCP (`HARNESS.md` §1). On the Linux server it is
[bethington/ghidra-mcp](https://github.com/bethington/ghidra-mcp) **v6.0.0** in headless mode, working on a
checkout of the Ghidra Server repository `sadk`. This document covers what runs where, how a Claude Code
session gets the tools, the rules for working on the shared repository, how to install and update the setup,
how to rebuild it from scratch, and how to fix the usual failures. `tools/ghidramcp/update-ghidramcp.sh`
installs and updates everything above the Ghidra Server; its README (`tools/ghidramcp/README.md`) has the
step-by-step details and `tools/ghidramcp/audit-report.md` the reasons behind its choices.

Live debugging of the running game is the Frida MCP (`frida-sadk`, `tools/frida_mcp/`), not part of this
setup.

---

## 1. What runs where

```
Claude Code session
   │ stdio (MCP server "ghidra", local scope)
   ▼
ghidra_mcp_launch.py ── upstream bridge bridge_mcp_ghidra 6.0.0 (pinned venv)
   │ spawns or attaches; HTTP 127.0.0.1:8089
   ▼
GhidraMCP 6.0.0 headless backend (JVM) ── opens ~/ghidra-mcp-projects/sadk-shared.gpr
   │ account mcp, password from ~/.ghidra-cred
   ▼
Ghidra Server (systemd ghidra-server, ports 13100-13102) ── repository sadk
```

| Piece | Where | Lifetime |
|---|---|---|
| Ghidra 12.1 | `/home/ghidra/ghidra_12.1_PUBLIC`, owner and group `ghidra`, group-accessible (the working account is in group `ghidra`) | installed |
| JDK 21 | `/usr/lib/jvm/java-21-openjdk-amd64` | installed |
| Ghidra Server | systemd unit `ghidra-server.service`, runs as `ghidra`; repositories in `/home/ghidra/ghidra_12.1_PUBLIC/repositories/` (repository `sadk`) | always on, starts at boot |
| Server-bound working copy | `~/ghidra-mcp-projects/sadk-shared.gpr` + `sadk-shared.rep/`, bound to `sadk` at `127.0.0.1:13100` | permanent |
| Credentials | `~/.ghidra-cred` (mode 600, first line = password of the server account `mcp`) | permanent |
| Backend | `~/.local/share/ghidramcp-sadk/v6.0.0/GhidraMCP-6.0.0.jar`, started by `~/.local/share/ghidramcp-sadk/bin/run-headless-sadk.sh`; HTTP on `127.0.0.1:8089` | as long as the session bridge that started it |
| Bridge | upstream package `bridge_mcp_ghidra` in `~/.local/share/ghidramcp-sadk/v6.0.0/venv`, wrapped by `~/.local/share/ghidramcp-sadk/bin/ghidra_mcp_launch.py` (backend lifecycle, timeouts) | one per Claude Code session |
| Launcher settings | `~/.local/share/ghidramcp-sadk/config.json` (generated) | |
| Registration | `ghidra` at **local scope** in `~/.claude.json` for the repository path: `~/.local/share/ghidramcp-sadk/v6.0.0/venv/bin/python ~/.local/share/ghidramcp-sadk/bin/ghidra_mcp_launch.py --config ~/.local/share/ghidramcp-sadk/config.json` | |
| Client timeouts | `MCP_TIMEOUT=120000`, `MCP_TOOL_TIMEOUT=1900000` in `.claude/settings.local.json` (gitignored) | |
| Ghidra scripts | `~/ghidra_scripts/` (what `run_ghidra_script` runs by name) | |
| Logs | backend: `~/.local/share/ghidramcp-sadk/logs/backend-<timestamp>.log`; Ghidra's own log of the backend: `~/.config/ghidramcp/ghidramcp_12.1_PUBLIC/application.log`; launcher and bridge: `~/.cache/claude-cli-nodejs/<project>/mcp-logs-ghidra/` (launcher lines start with `[sadk-launcher]`) | |

`~/ghidra-mcp` is the git clone of bethington/ghidra-mcp. The update script builds from a separate worktree
of it at the target tag (`~/.local/share/ghidramcp-sadk/v6.0.0/src`) and leaves the clone's own checkout alone.

The project `.mcp.json` carries no `ghidra` entry: the server is registered at local scope only, by the update
script.

## 2. How a session gets the tools

Starting Claude Code in the repository (or in a worktree under `.claude/worktrees/`) starts the `ghidra` MCP
server. The launcher then:

1. Checks `127.0.0.1:8089`. If something answers, it **attaches** and will never stop that backend.
2. Otherwise it runs `run-headless-sadk.sh` in its own process group, with output to a new
   `logs/backend-*.log`, and waits up to 90 s for `GET /get_project_info` to answer 200. The backend script
   refuses to start a second backend if the port is taken, removes a stale `sadk-shared.lock`, reads the
   `mcp` password from `~/.ghidra-cred`, sets `GHIDRA_MCP_ALLOW_SCRIPTS=1` and opens the server-bound project.
3. Merges the per-endpoint timeouts from `config.json` into the bridge and turns off the bridge's retry on
   timeout.
4. Starts the upstream bridge with `--no-lazy`: every tool group is registered at once as `mcp__ghidra__*`
   (the backend serves 245 endpoints). No `connect_instance` call is needed.

When the session ends, the launcher sends SIGTERM to the backend's process group (SIGKILL after 20 s), if it
started that backend. `/mcp` shows whether `ghidra` is connected.

Timeouts on the bridge side (`config.json`): 60 s by default; `decompile_function` and `force_decompile` 90 s;
`analyze_function_complete` 180 s; `open_project` and `save_program` 180 s; `batch_decompile`,
`load_program_from_project` and `checkin_program` 300 s; upstream's values for the rest (`run_ghidra_script`
and `run_script_inline` 1800 s). A bridge timeout comes back at once as an error ("did not answer … within
N s (bridge timeout, not retried)"); the backend may still be working on the call, so check the backend log
before sending a write again. `config.json` is regenerated by every update run: change a value in the
script's `gen_config` and run the script again.

Do RE through MCP tool calls only. `curl http://127.0.0.1:8089/get_project_info` is a health check, nothing
more.

## 3. Working rules

- **Programs.** Map `/sadk_noav.exe` (the DRM-free `SADK.exe` on disk, MD5 `d4832bc5103c14f5445471af29b8d778`)
  and `/tincat3.dll`. Ghidra's `/SADK.exe` is a SecuROM dump-base build with other addresses: keep it closed,
  so that a call with a wrong or missing program selector fails instead of answering from the wrong build.
  Pass `program=` on every call when more than one program is open (`list_open_programs` shows them).
- **Opening.** `load_program_from_project(path="/sadk_noav.exe")`. The backend carries one local patch: a
  versioned file that is not yet checked out is checked out **non-exclusively** before it is opened, so edits
  are writable and a GUI client can still hold its own checkout.
- **Saving and checking in.** `save_program` saves to the local checkout. `checkin_program(path, comment,
  keep_checked_out=true)` saves, writes a new repository version and **unloads the program**: call
  `load_program_from_project` right after it. (`keep_checked_out` defaults to false, which drops the checkout;
  the next load then checks out again.)
- **`server_status`** may report "not connected" while checkout and check-in work. Do not act on that flag.
- **Scripts inside Ghidra.** `run_ghidra_script(script_name=…, program=…, args=…)` runs a script by name from
  `~/ghidra_scripts/` (copy repository scripts such as `mapping/scripts/*.java` there first);
  `run_script_inline(code=…)` takes a complete Java `GhidraScript` class. Ghidra wraps a script in a
  transaction; persist with `save_program` or `checkin_program`.
- **One backend.** Only one backend can open the shared project. All sessions on this machine share it and its
  calls run one at a time; it lives as long as the session bridge that started it (§7).

## 4. Install and update

`tools/ghidramcp/update-ghidramcp.sh` performs pre-flight checks (Ghidra 12.1.x, Java 21, Python ≥ 3.10 with
`venv`, Maven ≥ 3.6.3, `git`, `ss`, `curl`, the `claude` CLI, the clone's origin and local changes, the
project `.gpr`, a free port 8089), takes a backup under `~/.local/share/ghidramcp-sadk/backups/<timestamp>/`,
builds the backend jar from a worktree of `~/ghidra-mcp` at the target tag with the checkout-on-load patch,
creates the pinned bridge venv, generates `bin/run-headless-sadk.sh`, `bin/ghidra_mcp_launch.py` and
`config.json`, registers `ghidra` at local scope, writes the two client timeouts into
`.claude/settings.local.json`, and runs a smoke test that drives the registered command the way Claude Code
does. A run on an installed, unchanged setup only repeats the smoke test. It never touches the Ghidra install,
the Ghidra Server, the working copy or `~/.ghidra-cred`.

1. Exit every Claude Code session that has `ghidra` connected. `ss -tlnp 'sport = :8089'` must print nothing.
2. Preview: `tools/ghidramcp/update-ghidramcp.sh --dry-run`
3. Run, smoke-testing on the mapped program:
   ```bash
   GHIDRAMCP_SMOKE_PROGRAM=/sadk_noav.exe tools/ghidramcp/update-ghidramcp.sh
   ```
   (The default smoke program is `/SADK.exe`; the smoke test's backend is stopped afterwards, but it leaves a
   non-exclusive checkout of whichever program it opened.)
4. Start a new session; `/mcp` shows `ghidra` connected.

Other modes: `--smoke-only`, `--skip-smoke`, `--rollback` (restores the newest backup; the backups on this
machine predate 6.0.0 and lead back to the retired 5.13.1 setup), `--help`. `GHIDRAMCP_TAG` selects another
tag, but only tags in the script's compatibility matrix are accepted (v6.0.0, v5.13.1). Prerequisite paths
can be overridden: `GHIDRAMCP_GHIDRA_HOME`, `GHIDRAMCP_JAVA_HOME`, `GHIDRAMCP_MVN`, `GHIDRAMCP_CLONE`,
`GHIDRAMCP_PROJECT`, `GHIDRAMCP_CRED`, `GHIDRA_MCP_PORT`.

The checkout-on-load patch is the only change to upstream (6.0.0 ships `checkin_program` itself). It lives in
the script (`gen_patch`) and is re-applied on every build.

## 5. Building the base from scratch (one-time)

Everything below the update script: the host, the Ghidra Server and the server-bound working copy.

### 5.1 Host

- **JDK 21** (Ghidra 12.1 requires it): `sudo apt-get install -y openjdk-21-jdk`.
- **Ghidra 12.1** unpacked to `/home/ghidra/ghidra_12.1_PUBLIC`, owned by a dedicated `ghidra` account, group
  `ghidra` with group read/write (the directories are setgid `ghidra`); add the working account to group
  `ghidra`. If the install was copied without exec bits (for example over SFTP from Windows), restore them:
  `chmod +x` on `ghidraRun`, the launchers in `support/` (`analyzeHeadless`, `*.sh`),
  `server/{ghidraSvr,svrAdmin,svrInstall,svrUninstall}` and every file under an `os/linux_x86_64/` directory
  (decompiler, sleigh, demangler).
- **Maven** ≥ 3.6.3, for the backend build: the Apache Maven 3.9.9 binary tarball unpacked to
  `~/apache-maven-3.9.9` (the update script looks there first, then on `PATH`).
- **Python** ≥ 3.10 with `venv`, plus `git`, `curl`, `ss`, and the `claude` CLI.
- The clone: `git clone https://github.com/bethington/ghidra-mcp ~/ghidra-mcp`.

### 5.2 Ghidra Server

Server parameters in `/home/ghidra/ghidra_12.1_PUBLIC/server/server.conf`:

```
wrapper.app.parameter.1=-a0                       # password authentication
wrapper.app.parameter.2=-u                        # clients may log in under an account name, not their OS user
wrapper.app.parameter.3=-ip
wrapper.app.parameter.4=<server-lan-ip | 127.0.0.1>   # see §6
wrapper.app.parameter.5=${ghidra.repositories.dir}
```

The systemd unit `/etc/systemd/system/ghidra-server.service`:

```ini
[Unit]
Description=Ghidra Server (SaDK reverse-engineering project)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ghidra
Group=ghidra
UMask=0007
Environment=JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
WorkingDirectory=/home/ghidra/ghidra_12.1_PUBLIC/server
# 'console' runs the wrapper and JVM in the foreground; 'start' would install a service itself and needs root.
ExecStart=/home/ghidra/ghidra_12.1_PUBLIC/server/ghidraSvr console
KillMode=mixed
TimeoutStartSec=180
TimeoutStopSec=90
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`sudo systemctl daemon-reload && sudo systemctl enable --now ghidra-server`.

Accounts (`server/svrAdmin`, run as `ghidra` or a member of its group):
- `sadk` for GUI clients, `mcp` for the headless backend: `svrAdmin -add <name>`.
- Write access for the backend: `svrAdmin -grant mcp +w sadk`.
- A new account starts with the password `changeme` and must change it at the first login, which the backend
  cannot do. Log in once as `mcp` from a GUI client (§8), set the password, and write it as the first line of
  `~/.ghidra-cred` (`chmod 600`).

The repository `sadk` is created and filled from a GUI client: a shared project on the server, the programs
imported and analyzed, then *Add to Version Control*. New programs are added the same way.

### 5.3 The server-bound working copy

The headless backend cannot open a `ghidra://` repository as a project and cannot bind a project to a server
itself (`open_project` is local only). It works on a local project that has been converted to a shared one,
the headless equivalent of the GUI's *Convert to Shared Project*: `ProjectData.convertProjectToShared(repo,
monitor)`, called by the Ghidra script `ConvertToShared.java`. That script connects to `127.0.0.1:13100` as
`mcp` with the password from `~/.ghidra-cred` and binds the project to the repository `sadk`. It is kept at
`~/ghidra-mcp/setup-scripts/ConvertToShared.java` (outside this repository; every update backup holds a copy
under `backups/<timestamp>/clone/setup-scripts/`).

```bash
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
mkdir -p ~/ghidra-mcp-projects
/home/ghidra/ghidra_12.1_PUBLIC/support/analyzeHeadless ~/ghidra-mcp-projects sadk-shared \
  -preScript ConvertToShared.java -scriptPath ~/ghidra-mcp/setup-scripts -noanalysis
```

Result: `~/ghidra-mcp-projects/sadk-shared.gpr`; `sadk-shared.rep/project.prp` records the server
`127.0.0.1`, port 13100 and the repository `sadk`. The backend opens the `.gpr` file (not the directory).

Then run the update script (§4).

## 6. The Ghidra Server address (`-ip`)

The server listens on all interfaces, but it hands every client the address given by `-ip`
(`wrapper.app.parameter.4`) for the follow-up connections, and the client must be able to reach that
address. One value cannot serve both kinds of remote client:

- `127.0.0.1` for clients that come in through an SSH tunnel. The tunnel must carry **all three ports**:
  `ssh -L 13100:127.0.0.1:13100 -L 13101:127.0.0.1:13101 -L 13102:127.0.0.1:13102 <user>@<server>`; the client
  then connects to `localhost:13100`. A tunnel of 13100 alone connects and then fails.
- The server's LAN address for clients on the LAN.

The headless backend runs on the server itself and works with either value. To see the current value:
`grep '^wrapper.app.parameter.4' /home/ghidra/ghidra_12.1_PUBLIC/server/server.conf`. To change it, edit that
line (the file is writable by group `ghidra`) and `sudo systemctl restart ghidra-server`, preferably while no
session has `ghidra` connected.

## 7. Troubleshooting

**`ghidra` not connected, or no `mcp__ghidra__*` tools.** Read the `[sadk-launcher]` lines in
`~/.cache/claude-cli-nodejs/<project>/mcp-logs-ghidra/` and the newest `logs/backend-*.log`. "backend exited
during startup" and "backend not ready after 90s" point to the backend log. Check that the Ghidra Server runs:
`systemctl status ghidra-server`, `ss -tlnp | grep ':1310[0-2]'`; its own log is
`/home/ghidra/ghidra_12.1_PUBLIC/repositories/server.log`.

**Tools stop answering after another session ended.** The backend belonged to that session and was stopped
with it. Reconnect `ghidra` under `/mcp` (or restart the session); the launcher starts a new backend.

**Stale `sadk-shared.lock`.** A backend that was killed leaves `~/ghidra-mcp-projects/sadk-shared.lock` (and
`.lock~`) behind. `run-headless-sadk.sh` removes both whenever nothing listens on :8089, so a normal start
clears them. `LockException: Unable to lock project` while :8089 is free means another Ghidra process has the
project open: `pgrep -af 'GhidraMCPHeadlessServer|sadk-shared'`. When two sessions start at the same moment,
both may launch a backend; the second fails with `LockException` or `BindException: Address already in use` in
its log, and its bridge uses the first one. That is harmless.

**Port 8089 taken.** `ss -tlnp 'sport = :8089'` shows the process. The launcher attaches to whatever listens
there ("something listens on :8089 but /get_project_info does not answer 200" if it is not a backend). An
orphaned backend (its session was killed hard, so the teardown never ran) still works, but nothing will stop
it: end it with `kill <pid>` once no session uses it. To move the backend to another port for good, rerun the
update script with `GHIDRA_MCP_PORT=<port>`; it regenerates the launcher and `config.json`.

**Checkout behind HEAD.** After another client (a GUI, another working copy) checks in a newer version,
`checkin_program` fails with "file requires merge which is not supported in headless mode". Close the program
first (`close_program`), then run the fix under another open program, for example `tincat3.dll`:

- *No local changes:* fast-forward the checkout with `run_script_inline(program="tincat3.dll", code=…)`:
  ```java
  import ghidra.app.script.GhidraScript;
  import ghidra.framework.model.DomainFile;

  public class UpdateCheckout extends GhidraScript {
      @Override
      public void run() throws Exception {
          DomainFile df = currentProgram.getDomainFile().getParent().getProjectData().getFile("/sadk_noav.exe");
          println("v" + df.getVersion() + "/" + df.getLatestVersion() + " modified=" + df.modifiedSinceCheckout()
              + " open=" + df.isOpen());
          if (df.isOpen() || df.modifiedSinceCheckout()) {
              println("not updated: close the program, or rebase the local changes");
              return;
          }
          df.merge(true, monitor);
          println("now v" + df.getVersion() + "/" + df.getLatestVersion());
      }
  }
  ```
- *With local changes:* `mapping/scripts/RebaseNoav.java` (copy it to `~/ghidra_scripts/`; it handles
  `/sadk_noav.exe` and writes its reports to `mapping/rebase/`). Run it with `run_ghidra_script` under
  `tincat3.dll`, in order: `plan` (three-way comparison of the checked-out base version, the local copy and
  HEAD; writes `plan.json`), `swap` (undoes the checkout keeping a `.keep` copy, then checks out HEAD), and
  `apply <baseVersion>` (replays the local edits onto HEAD; where HEAD changed the same item since the base,
  HEAD wins and the item is reported in `apply-report.json`).

Then `load_program_from_project` and `checkin_program`.

**Answers come from the wrong build.** `/SADK.exe` is open and a call went to it: `close_program` it and pass
`program="sadk_noav.exe"` explicitly.

**A GUI client connects but nothing works.** The server's `-ip` does not fit the way the client connects, or
the SSH tunnel lacks 13101/13102 (§6).

## 8. Windows GUI client

A Ghidra GUI on Windows is a second client of the same repository. It is used to fill the repository, to set
the password of a new account and to look at the program by hand.

- **Connect.** Ghidra 12.1.x. *File → New Project → Shared Project*, server `<server-lan-ip>` (LAN, `-ip` set
  to the LAN address) or `localhost` (SSH tunnel of all three ports, `-ip` set to `127.0.0.1`), port 13100,
  account `sadk`, repository `sadk`. Check out `/sadk_noav.exe`.
- **Stay in step with the headless backend.** After the backend checks in, *Update* the GUI checkout. After the
  GUI checks in, the backend's checkout is behind HEAD (§7).
- **MCP from the GUI (optional).** The normal route is the Linux backend; the update script and the launcher
  are Linux-only. To serve MCP from a GUI instead: install the GhidraMCP 6.0.0 extension ZIP built for the
  GUI's Ghidra version (*File → Install Extensions*, restart; the 6.0.0 release targets 12.1.2, and upstream's
  `python -m tools.setup build` builds it from a clone), enable it in the CodeBrowser under *File → Configure →
  Configure All Plugins → GhidraMCP*, and start it with *Tools → GhidraMCP → Start MCP Server* (HTTP on
  `127.0.0.1:8089`). The bridge is upstream's `bridge-mcp-ghidra` from a 6.0.0 clone, registered at local
  scope: `claude mcp add -s local ghidra -- uv run --directory <clone> bridge-mcp-ghidra`. It acts on the
  program open in the CodeBrowser.
