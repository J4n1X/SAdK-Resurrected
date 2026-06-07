# Debugger plan — crack the UC/chat connection (next session)

Static RE took the chat connection as far as it goes (see `SESSION_STATUS.md` s9). The last
unknowns are RUNTIME: the value of the chat-server handle `param_2` at login, and how the comm
layer (`tincat3.dll`) turns it into an address. A debugger answers both in minutes.

The `bethington/ghidra-mcp` fork exposes `debugger_*` tools (launch/attach, breakpoints,
read registers/memory/args, step). So: get SADK.exe running under Ghidra's debugger, then
Claude drives the breakpoints over MCP.

## Setup (user)
0. **Start the ghidra-mcp debugger SERVER first** — the `debugger_*` MCP tools proxy to a
   standalone Python server at `http://127.0.0.1:8099` (`GHIDRA_DEBUGGER_URL`), which bridges to
   Ghidra's TraceRMI/dbgeng. If it's not running, every debugger tool errors
   ("Debugger server not running at :8099. Start it with: python -m debugger"). Start it from
   the ghidra-mcp repo (needs a working Python). Do NOT also manually attach via the Ghidra
   dbgeng UI — let the MCP drive the attach (`debugger_attach`), or they'll conflict (one
   debugger per process).
   - **pybag gotcha:** Ghidra's `dbgeng` launcher needs `pybag>=2.2.12` in the SAME python it
     invokes. If it errors "INCORRECT OR INCOMPLETE SETUP", answer YES to auto-resolution (it
     pip-installs into the right interpreter), close the terminal, relaunch. (Done 2026-06-01.)
1. Start the stub: `python tincat_server.py` (with the s7 fixes — 170="old", 171 parse).
2. Launch SADK.exe normally and reach the login screen (don't log in yet). Then tell Claude —
   Claude calls `debugger_attach(target="SADK.exe")`, sets the BPs below, you log in.

## Breakpoints (Claude drives via MCP)
Set BEFORE logging in, then log in test/test/test and reach character select.

0. **`0x464740` `LobbyManager::OnLoginFailed` — DO THIS FIRST.** It fires when a sub-connection's
   login/connect fails ("TinCat failed to start connection"). Read `param_1` (the failed conn id)
   and compare to the LobbyManager connection slots `+0x540` (village), `+0x544`, `+0x490`,
   `+0x3d8` (and `+0x50` main). This identifies **which** connection is actually failing
   post-login — NOT necessarily the chat/UC one. After `Authorized(3)` the client also does
   `LoadingGlobalData(6)`, which may use its own connection; the post-login failure could be
   that, the UC/chat, or another. Confirm the identity before assuming it's chat.

1. **`0x463910` `LobbyManager::OnLoggedIn`** — when the MAIN lobby conn logs in, read the
   2nd stack arg `param_2` (the chat-server handle stored to `+0x548`). **This is THE value.**
   Is it 0/null (⇒ login never supplied a handle), a small int (a server-id to resolve), or a
   pointer (a descriptor)? Also dump `[ECX+0x548]` after.
2. **`0x47fb40` `UserCommConnection::OpenCommunication`** and **`0x470b50`** — confirm whether
   they're even hit.
   - **Never hit** ⇒ the UC open is gated (logic), not an address bug — pivot to "what triggers
     the open" (a message/state we're not producing).
   - **Hit** ⇒ read `param_1` (the handle) and **step into the comm call `vtable[0x10]`**
     (lands in tincat3.dll `CommLayer::ConnectionManagerINet`). Watch the handle→address
     resolution and where the host comes out empty.
3. **`0x4626c0` `LobbyManager::GetChatServerHandle`** — confirm the returned `+0x548` value.

## Decision tree from the results
- `param_2` null at login ⇒ our login reply (LoginReplyCipher 207 / the comm login) must
  supply a chat-server handle the client expects. Reverse what fires `OnLoggedIn` in
  tincat3.dll to see what populates it.
- `param_2` valid but comm `vtable[0x10]` resolves empty ⇒ the comm's server registry lacks
  the address for that handle ⇒ check whether our `GetChatServer(192)` (ServerId=1) must
  register the address under the SAME id the handle uses.
- OpenCommunication never hit ⇒ find the trigger gate.

## No-debugger fallback (pure static)
Open **tincat3.dll** in Ghidra and reverse `CommLayer::ConnectionManagerINet` `vtable[0x10]`
(the handle-based connect) + where the `LoggedIn` callback is fired with its data arg. The
local decomp is `decomp/tincat/tincat3.dll.c` (grep `ConnectionManagerINet`,
`ConnectionReal`), but the vtable slot→function mapping needs the live DLL (vtables are data).
