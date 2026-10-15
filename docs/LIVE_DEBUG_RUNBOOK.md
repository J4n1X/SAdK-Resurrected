# Live debug runbook

Live work on the running game goes through the Frida MCP `frida-sadk` (`tools/frida_mcp/server.py` and its agent
`agent.js`). This runbook covers the setup, the tools, the standing probes of the lobby client and how unattended
runs and the check queue work. The binding rules are `HARNESS.md` §2 and §7.

Addresses: `S` = `SADK.exe` (Ghidra program `sadk_noav.exe`, base 0x400000), `T` = `tincat3.dll` (base
0x10000000). Both load at these bases, so the static Ghidra addresses are the runtime addresses. The tools take
them as hex strings (`"0x462540"`).

## 1. When to go live

- Only when the behaviour cannot be read from code: what the screen or the speaker shows, timing of real networks
  or hardware, libraries that cannot be read (the packed `fmod.dll`, drivers), the original servers. "Confirm the
  reading" is not a reason. Read the code path to its end in Ghidra first.
- Sort every list of checks into (1) answerable by reading: do it; (2) measurable unattended in a running game
  (hooks, reads, orders through the game's own send functions on the main thread): run it yourself (§10);
  (3) needs the maintainer's eyes, ears or a second player: hand over only these, as one short list.
- Calling client functions or writing memory changes the live game: state every call and why. Writes to game
  memory and new server behaviour need the maintainer's approval first.
- No hardware watchpoints from JS (§5).

## 2. Setup

| Piece | Where |
|---|---|
| frida-server 17.22.2 (windows-x86) | on the game PC, as Administrator (the game runs elevated): `frida-server-17.22.2-windows-x86.exe -l 0.0.0.0:27042` |
| MCP server | stdio, registered at user scope: `claude mcp add -s user frida-sadk -- ~/.venvs/frida/bin/python <repo>/tools/frida_mcp/server.py`. The venv holds `frida` 17.22.2 (the same version as frida-server) and `mcp`. A project `.mcp.json` entry is skipped in background sessions, which never show the approval prompt |
| Attach | the maintainer starts the game; then `frida_connect(host="<game-pc-ip>")`. The reply lists `SADK.exe` at 0x400000 and `tincat3.dll` at 0x10000000 |

The game PC is reachable over SSH without a password; the remote shell is Windows PowerShell 5 (join commands
with `;`, not `&&`).
- Install builds only while `SADK.exe` is not running (`Get-Process SADK`): the shim `bin\wsock32.dll`, mods in
  `mods\<name>`. Stage uploads in `~\sadk_upload` (scp target `sadk_upload/`); keep previous copies in
  `~\sadk_upload\prev\<mod>`, never inside `mods\<mod>` (assetshare compares the whole mod folder).
- The shim log is `bin\wsock32_shim.txt` in the install folder; its `build` line names the installed shim.
- Screenshots: `schtasks /Run /TN sadk-screenshot` runs `tools/screenshot.ps1` in the logged-on desktop session,
  which SSH cannot see. It captures the game window only and writes `~\sadk_upload\shot.png`; copy it with scp.
- The lobby server runs as the systemd user service `sadk-lobby` on the Linux server; its log: §9.

## 3. The tools

| Tool | Arguments (default) | Does |
|---|---|---|
| `frida_connect` | `host`, `port` (27042), `target` (`"SADK.exe"`) | attaches, loads the agent, lists the two modules |
| `frida_status` | – | attached or not; after a detach the reason and, after a crash, Frida's crash report |
| `frida_read` | `address`, `length` (64) | bytes as hex |
| `frida_read_u32` | `address` | one little-endian u32 (to follow pointers) |
| `frida_read_cstring` | `address`, `max_length` (256) | a NUL-terminated ANSI string |
| `frida_hook` | `address`, `nargs` (0), `name` | records every call (below) |
| `frida_unhook` | `address` | removes a `frida_hook` hook; spell the address as in the `frida_hook` call |
| `frida_events` | `clear` (true), `limit` (200) | recorded calls and exceptions, oldest first |
| `frida_eval` | `code` | runs JavaScript in the agent; returns the value of the last expression |
| `frida_call` | `address`, `args`, `abi` (`cdecl`), `ret` (`uint32`) | calls a client function |
| `frida_detach` | – | detaches; the game keeps running and every hook is gone |

**Hook events.** `frida_hook` (`Interceptor.attach`) stores one event per call when the function returns:
`{kind: "call", name, addr, ecx, args, tid, ret, t}`. `ecx` is `this` of a `__thiscall` function (meaningless
otherwise). `args` are the first `nargs` 32-bit stack slots in hex (the stack arguments); a `__fastcall`
function's second argument (EDX) is not recorded, and a float shows as its bit pattern. `ret` is EAX: an x87 float
return is not visible. `t` is the game PC's clock in ms, `tid` the thread. Nested calls appear inner first; a call
that never returns leaves no event. The agent keeps the last 5000 events. `frida_events` returns the last `limit`
of them, and `clear` deletes all of them, those beyond `limit` included: pass a larger `limit` or `clear=false`
when more are expected.

**Exceptions.** The agent's `Process.setExceptionHandler` records every native exception (`kind: "exception"`,
registers, 24 backtrace frames) and returns false, so the game's own handling continues: such an event is not
necessarily a crash. When the game dies, the unread events are gone; `frida_status` keeps the reason.

**`frida_call`** types every argument as `pointer`: an int or hex string, `{"str": "text"}` (a new ANSI string) or
`{"bytes": "hex"}` (a new buffer, freed after the call). `abi`: `cdecl`, `stdcall`, `thiscall` (the first argument
is `this`), `fastcall`. `ret`: `uint32` (decimal text), `int`, `pointer` (hex), `void`, `float`, `double`. A fault
inside the call goes to the game's own handling (`exceptions: 'propagate'`). The call runs on the agent's thread,
not the game's main thread: use it only for functions that change nothing (§4). Float, double and struct
arguments need `frida_eval` with an explicit signature.

**`frida_eval`** is an indirect `eval` in the agent's global scope, on the agent's thread, with Frida's API (`ptr`,
`NativeFunction`, `Interceptor`, `Process`, `Thread`). Return numbers, strings and plain objects (`.toString()` on
pointers). Keep state on `globalThis`; hooks made here are unknown to `frida_unhook`, so keep the listener there
and call its `.detach()`. The agent runs Frida 17: use `p.readU32()`, `p.readPointer()` and
`Process.getModuleByName(...).getExportByName(...)`; static forms such as `Module.findExportByName(null, ...)`
no longer exist.

## 4. Calls on the main thread

The game's objects are not thread-safe. A call that changes the game is made once, from a hook on a function the
main thread runs every tick or frame. Example (it changes the game speed, so it is announced before the run):

```js
globalThis.job = { done: false };
globalThis.jobHook = Interceptor.attach(ptr("0x78b040"), {        // nGame::Autosave::Update (main thread, match)
  onEnter() {
    if (job.done) return;
    job.done = true;
    const ncomm = ptr("0x885754").readPointer();                    // g_NCommManager
    job.before = ncomm.add(0x3c).readU32();                         // game speed
    new NativeFunction(ptr("0x782950"), "void", [], "stdcall")();    // nGame::System::SendCycleGameSpeedCommand
    job.after = ncomm.add(0x3c).readU32();
    job.tid = this.threadId;
  }
});
```

Then `frida_eval("job")` for the result and `frida_eval("jobHook.detach(); 'detached'")`. Other anchors:
`nGame::Camera::Update` S 00787530 (every frame in a match), `Lobby::CLobbyClient::Update` S 00503fc0 (every frame
in the lobby). An order goes through the game's own sender (the function its button calls), or is built the way
that sender builds it and passed to `NComm_Manager::QueueGameCommand` S 00408b10, which drops a command sent
without `force` while `IsGameHanging` S 00408860 is true (`docs/sim/logic-core.md`).

The game window must keep the foreground. When another window takes it, the Direct3D device is lost and the main
thread waits in `S2CE::CGraphicDevice::WaitForDeviceRestore` S 004da170: no tick, no frame, no main-thread hook.
To check that the game advances, read `g_pGameSystem` S 0088996c `+0x88` (`tickCounter`) twice.

## 5. Hot functions, limits, watchpoints

- A function called thousands of times per tick floods the buffer and slows the game through `frida_hook`. Hook it
  in `frida_eval`, filter and count in the handler, and read the aggregate later, e.g.
  `globalThis.rec = {n: 0}; globalThis.recHook = Interceptor.attach(ptr("<address>"), {onLeave(r) {rec.n++;}});`
- `this.returnAddress` in `onEnter` tells the callers of a shared body apart. A function reached by a tail jump
  returns to its caller's caller (`CLobbyClient::LeaveVillage` S 00503470 jumps into `SendLeaveVillageRequest`).
- One-instruction getters (`MOV EAX,[ECX+n]; RET`) are too short for Interceptor; hook their callers.
- When a measurement disagrees with the decompiled text, read the disassembly of that branch: the decompiler can
  drop operations.
- **No hardware watchpoints** (`Thread.setHardwareWatchpoint` with a JS exception handler). On 2026-10-14 one
  slowed the game to 2 ticks in 65 s, and tearing it down killed the process. Find the readers and writers of a
  field with static xrefs in Ghidra, live with hooks on the candidate functions. If a watchpoint seems
  unavoidable: ask the maintainer first, one cold field, one thread, and never change the exception handler while
  traps can be pending (the agent installs one when it loads).

## 6. Lobby client probe

The root object is `LobbyComm::System` (`g_pLobbyManager` S 00885890; 0x5a8 bytes, vtable S 007dacb0); `LM+0x..`
is an offset inside it. The village connection and every transport are created and destroyed per connection:
walk the chain on every read. Layouts: `docs/types.md` §1, `docs/SOURCEMAP.md`.

| Read | Meaning |
|---|---|
| `*(S 00885890)` | `LM`; 0 when no lobby client exists |
| `LM+0x57c` | `LobbyManagerState` (below) |
| `LM+0x580` | `nRefereeServerId`; 0 until a type 4 / subtype 4 assign reply latched it |
| `LM+0x54` | `ServerList` (embedded): `+0x9c` the hosting latch (§7.2), `+0xa0` `bSelectionLocked` (a byte) |
| `LM+0x3d8` / `LM+0x490` | chat (UserComm) / referee connection (embedded) |
| `LM+0x540` / `LM+0x544` | village / game-room connection (pointer, 0 = none); village vtable S 007db8d4 |
| `conn+0x04` / `+0x10` / `+0x1c` / `+0x28` | the connection's observer lists: logged in, login failed, logged out, disconnected |
| `conn+0x34` | the connection's tincat3 transport (`CommLayer::ConnectionReal`, vtable T 10051694); 0 = none |
| `transport+0x08` | transport state (below) |
| `*(LM+0x50)+0x14` | the lobby connection's transport (it has no `LobbyComm` object; `ConnectionManager`, `types.md` §3) |

One `frida_eval` reads it all:

```js
(() => {
  const lm = ptr("0x885890").readPointer();
  if (lm.isNull()) return "no LobbyComm::System";
  const u32 = (p, off) => p.add(off).readU32();
  const tr = conn => { const t = conn.add(0x34).readPointer(); return t.isNull() ? null : u32(t, 0x08); };
  const vsc = lm.add(0x540).readPointer(), sl = lm.add(0x54);
  return { lm: lm.toString(), state: u32(lm, 0x57c), refereeServerId: u32(lm, 0x580),
           chat: tr(lm.add(0x3d8)), referee: tr(lm.add(0x490)),
           village: vsc.isNull() ? null
             : { at: vsc.toString(), vtable: "0x" + u32(vsc, 0).toString(16), transport: tr(vsc) },
           hostLatch: "0x" + u32(sl, 0x9c).toString(16), selectionLocked: sl.add(0xa0).readU8() };
})()
```

**`LobbyManagerState`** `[known]`; every transition with its writer: `docs/sim/lobby-client-state.md` §3.1.

| Value | Name | Set by |
|---|---|---|
| 0 | Init | before `Initialize`; `Destroy` S 00462f70 at shutdown |
| 1 | Disconnected | `Initialize` S 004643d0; lobby login failed S 00464a20; lobby logged out S 00464bf0 |
| 2 | Authorizing | `Login` S 004630e0, `CreateUser` S 004633f0 |
| 3 | Authorized | `OnLoggedIn` S 00463a10 (lobby connection) |
| 4 to 7 | CheckingVersion, VersionChecked, LoadingGlobalData, GlobalDataLoaded | `StatePump_Tick` S 00464ee0; 4 -> 5 `OnVersionChecked_State4to5` S 00464e70 |
| 8 | EnteringVillage | `VillageServerConnection::OnUserCommLoggedIn` S 004704e0 (from 7 or 11) |
| 9 | VillageEntered | `HandleEnterWorld` S 0046f670 (message 1000) |
| 10 | LeavingVillage | `SendLeaveVillageRequest` S 0046bde0 (message 2002) |
| 11 | VillageLeft | `HandleLoggedOut` S 00470e20 or `HandleDisconnected` S 00470f90 |
| 12 | ConnectionLost | `OnConnectionLost` S 004647e0 (lobby connection) |

No state has a timeout. `SetState` S 00462540 (`nargs` 1) does nothing in state 12, and only the village
connection calls it (states 8 to 11); the `LobbyComm::System` handlers write the field directly. A hook on
`SetState` therefore misses 1 to 7 and 12: poll `LM+0x57c`, or hook the handlers (`ecx` = `LM`): `OnLoggedIn`
S 00463a10 (`nargs` 3: connection, id, unused), `OnLoginFailed` S 00464a20 (2: connection, error), `OnLoggedOut`
S 00464bf0 (2: connection, reason), `OnConnectionLost` S 004647e0 (3: connection, unused, error).

**Transport state** (`ConnectionReal +0x08`): 0 idle, 2 connecting, 8 logged in, 9 logging out. The client tests 8
(logged in) and treats 0, 8 and 9 as "not pending", any other value as "connecting or logging in"
(`IsConnectionPending` S 0048dd00). The other values are tincat3-internal (`types.md` §3).

## 7. Standard hook sets

These functions run rarely; `frida_hook` is enough.

### 7.1 Leaving the village

The transport's Logout (vtbl `+0x18`, `ConnectionReal::Disconnect` T 10030510) sets transport state 9. When the
connection then closes, `ConnectionReal::OnTinCatEvent` T 10030ad0 takes the logged-out branch only in state 9:
`HandleLoggedOut` -> VillageLeft(11) -> the village connection's `+0x1c` list, whose observer
`WorldScreen::OnVillageConnectionLoggedOut` S 004316c0 arms the referee login at match start. A close in state 8
ends in `HandleDisconnected` -> the `+0x28` list -> `WorldScreen::OnVillageConnectionDisconnected` S 00432ed0,
which shows the `!CONNECTION_LOST_TEXT` box for a non-zero reason. These are the only two exits from
LeavingVillage(10) `[PROVEN]`. The server answers 2002 with two 1006 `{0xDEADBEEF}`: the first logs the chat
connection out, the second the village transport (`docs/message-catalog.md`, 2002 and 1006).

| Address | Function | A hit shows |
|---|---|---|
| S 00503470 | `Lobby::CLobbyClient::LeaveVillage` | the leave starts (confirm box, or match start) |
| S 0046bde0 | `VillageServerConnection::SendLeaveVillageRequest` | state 10, 2002 sent (only in transport state 8) |
| S 0046ec50 | `VillageServerConnection::HandleWorldLoginAck` | a 1006 arrived; it acts only on 0xDEADBEEF |
| S 0047ed70 | `UserCommConnection::Logout` | the chat logout |
| T 10030510 | `CommLayer::ConnectionReal::Disconnect` | `ecx` = the transport going to state 9 |
| T 10030ad0 | `CommLayer::ConnectionReal::OnTinCatEvent` | every TinCat event of every connection; filter by `ecx` in a `frida_eval` hook if it floods |
| S 00470e20 | `VillageServerConnection::HandleLoggedOut` | -> 11, the clean exit |
| S 00470f90 | `VillageServerConnection::HandleDisconnected` | -> 11 through the connection-lost path |

### 7.2 Hosting latch

`ServerList +0x9c` (`gameServerId`, at `LM+0xf0`): 0xFFFFFFFF INVALID, 0xFFFFFFFE PENDING, any other value the
hosted game's id. While it is INVALID or PENDING, `SetupGameDialog::Update` S 00457a00 returns early and shows the
"Connecting to Game Server" modal. Writers: the ctor (INVALID); `CreateGameServer` (PENDING once 168 is sent);
`CreateResultReceived` (the id on error code 0, else INVALID plus NComm shutdown); `DeleteResultReceived`
(INVALID); `DestroyGameServerAndShutdown` (INVALID plus NComm shutdown). Field map:
`docs/LOBBY_SCREEN_VTABLES.md`. The callbacks of the `IGameServerObserver` face (vtable S 007daf8c,
`SOURCEMAP.md` §2d) run with ECX = `ServerList+8`: in their events `ecx - 8` is the `ServerList`, and the latch is
at `ecx + 0x94`.

| Address | Function | A hit shows |
|---|---|---|
| S 0046aaa0 | `ServerList::CreateGameServer` | the host tried to host |
| S 0046a6a0 | `ServerList::CreateResultReceived` | `nargs` 2: (newGameServerId, errorCode), the answer to 168; dropped when no create is pending |
| S 00469610 | `ServerList::GameServerAdded` | a 170 reached the list |
| S 00469990 | `ServerList::DeleteResultReceived` | the answer to 169 |
| S 00468410 | `ServerList::DestroyGameServerAndShutdown` | the host left the setup dialog and sent 169 |

### 7.3 Match start (referee chain)

The sequence and every field: `docs/MATCH_START.md`. Each failure in this chain is silent (frame accepted,
socket open, nothing logged): a missing hook event is the only sign.

| Address | Function | A hit shows |
|---|---|---|
| S 00469ad0 | `ServerList::GameServerAssigned` | the 189 assign reply reached the client |
| S 004625d0 | `LobbyComm::System::SetRefereeServerAddress` | the id latched into `LM+0x580` (type 4 / subtype 4 replies only) |
| S 004316c0 | `WorldScreen::OnVillageConnectionLoggedOut` | the referee login is armed (match start), or back to the avatar screen |
| S 004793f0 | `RefereeServerConnection::Login` | the referee login was sent |
| S 0047ac20 | `RefereeServerConnection::LoginSuccessReceived` | 0xDCA arrived; returns silently when the PermID is not the local one |
| S 00432240 | `WorldScreen::OnRefereeLoginSuccess_RegisterGame` | `RegisterGame` 0xDB6 was sent |
| S 00431800 | `WorldScreen::OnRefereeRegisterGameResult` | `nargs` 2: (gameId, GameSeed); the load starts |

The login pump's state is in the `LobbyMenu::WorldScreen` (`ecx` of `WorldScreen::Update` S 00435980):
`+0x3624` pending, `+0x3625` armed, `+0x3628` delay, `+0x362c` tries (more than 4 aborts). Once `LM+0x580` is
latched, the client re-sends 189 every 60 s (timer `LM+0x588`); that cadence in the server log shows the latch.

## 8. Wire byte order

| Layer | Byte order | Reference |
|---|---|---|
| NETMSG messages and the TinCat property bag (lobby, chat, the NETMSG 73 / 74 envelope) | little-endian scalars and u32 lengths | `message-catalog.md`, NETMSG 74 |
| LobbyMessage body (village and referee messages inside NETMSG 74) | MSB-first bit stream: a 32-bit value is big-endian when it starts on a byte boundary; bool 1 bit; string u8 length; `SellMod` of 0xE11 is read byte-reversed (little-endian) | `message-catalog.md`, "Field bitstream" |
| NComm P2P events (pre-game room and match) | raw little-endian memory dumps | `message-catalog.md`, "NComm P2P events" |
| Game memory as Frida reads it | little-endian | – |

A wrong byte order fails silently: the handler runs, its compare fails and it skips the body. `HandleWorldLoginAck`
ignores a 1006 whose code is not 0xDEADBEEF; `LoginSuccessReceived` returns silently on a little-endian PermID.
When a hook shows that a message reaches its handler and nothing follows, check the encoding first.

## 9. Correlating with the server log

- Hook events carry the game PC's clock (`t`, ms), the journal the Linux server's. Measure the offset once per
  session: `frida_eval("Date.now()")` against `date +%s%3N` on the Linux server (accurate to the round trip).
- `journalctl --user -u sadk-lobby -o short-precise --since "-10min"` gives the server side.
- For the bytes on the wire, `tools/lobby_proxy.py` logs the traffic passively; `tools/decode_lobby_capture.py`
  decodes a capture.

## 10. Unattended runs and the check queue

`docs/live-session-queue.md` holds the open checks. Each entry says what happens in the game, what to observe
(`Observe:`) and which statement of a specification it settles (`Settles:`). Entries marked **needs permission**
write game memory or change what the server sends.

1. **Read first.** Settle in Ghidra every entry the code decides (`docs/live-checks/2026-10-12_read-from-code.md`
   is a batch settled this way).
2. **Prepare.** The maintainer starts the game and a throwaway match or lobby session. The game window keeps the
   foreground for the whole run (§4). Every call and write is listed before the run.
3. **Run.** Hooks observe; orders go through the game's own senders on the main thread; the tick counter shows
   that the game advances. Remove every hook at the end (`frida_unhook`, `.detach()` or `frida_detach`).
4. **Record** per entry: the status (PROVEN, PARTLY, CONTRADICTS SPEC, NOT POSSIBLE UNATTENDED); what was done (the
   hooks with their addresses, every call and write with its thread); what was measured; the conclusion against
   the specification's section. `docs/live-checks/2026-10-12_unattended-run.md` is a run recorded in this form.
5. **File the result** in the specification named under `Settles:` (tag, addresses, date and source;
   `HARNESS.md` §8) and remove the entry from the queue. A statement becomes `[PROVEN]` only with the binary
   address and the live observation. A case seen once is reported as seen once, and "not called in N ticks"
   describes that run, not every path.
6. **Hand over** what is left (look, listen, a second player) to the maintainer as one short list.
