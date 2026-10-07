#!/usr/bin/env python3
"""
Frida MCP — live access to the running SADK.exe (the "debugger MCP" HARNESS §1 asks for).

Why it exists (HARNESS §3): the Ghidra MCP is static. Questions like "why does the client not seat the
player" or "which branch does the client take on our 0xD9" need the live client: call its functions,
hook its handlers, read its objects, catch its crashes with full context. Frida provides that; this
server wraps it as MCP tools so all live work stays inside the harness.

Setup: run frida-server (same version as the `frida` package here, 17.22.2) on the game PC as
Administrator — `frida-server-17.22.2-windows-x86.exe -l 0.0.0.0:27042` — start the game, then call
frida_connect with that PC's address. Addresses are the static Ghidra addresses (no ASLR).

Run (stdio, registered in .mcp.json):  ~/.venvs/frida/bin/python tools/frida_mcp/server.py
"""
import json
import os

import frida
from mcp.server.mcpserver import MCPServer

AGENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.js")

mcp = MCPServer(name="frida-sadk", instructions=(
    "Live access to the running SADK.exe via Frida. Connect first with frida_connect. Addresses are "
    "the static Ghidra addresses (SADK.exe base 0x400000, tincat3.dll 0x10000000). Calling client "
    "functions or writing memory changes the live game: say what you call and why."))

_state = {"device": None, "session": None, "script": None, "target": None, "detached": None}


def _api():
    if _state["script"] is None:
        raise RuntimeError("not connected — call frida_connect first")
    return _state["script"].exports_sync


def _addr(a):
    return a if isinstance(a, str) else hex(a)


def _on_detached(reason, crash):
    _state["detached"] = {"reason": str(reason), "crash": (crash.report if crash else None)}
    _state["session"] = _state["script"] = None


@mcp.tool()
def frida_connect(host: str, port: int = 27042, target: str = "SADK.exe") -> str:
    """Attach to the game process `target` on the frida-server at host:port and load the agent."""
    mgr = frida.get_device_manager()
    dev = mgr.add_remote_device(f"{host}:{port}")
    session = dev.attach(target)
    session.on("detached", _on_detached)
    script = session.create_script(open(AGENT, encoding="utf-8").read())
    script.load()
    _state.update(device=dev, session=session, script=script, target=target, detached=None)
    mods = script.exports_sync.modules()
    main = [m for m in mods if m["name"].lower() in (target.lower(), "tincat3.dll")]
    return f"attached to {target} on {host}:{port}; modules: {json.dumps(main)}"


@mcp.tool()
def frida_status() -> str:
    """Connection state, and why the session ended if it did (e.g. the game crashed)."""
    if _state["script"] is not None:
        return f"attached to {_state['target']}"
    return f"not attached; last detach: {json.dumps(_state['detached'])}"


@mcp.tool()
def frida_call(address: str, args: list = None, abi: str = "cdecl", ret: str = "uint32") -> str:
    """Call a client function. abi: cdecl | stdcall | thiscall | fastcall (thiscall: first arg is
    `this`). Each arg is an int / hex string (32-bit value), {"str": "text"} (pointer to a new ANSI
    string) or {"bytes": "hex"} (pointer to a new buffer). ret: uint32 | int | pointer | void | float
    | double."""
    return json.dumps(_api().call(_addr(address), args or [], abi, ret))


@mcp.tool()
def frida_read(address: str, length: int = 64) -> str:
    """Read `length` bytes at `address`; returns hex."""
    data = _api().read(_addr(address), length)
    return data.hex(" ") if data else "unreadable"


@mcp.tool()
def frida_read_u32(address: str) -> str:
    """Read one little-endian u32 (handy for following pointers)."""
    return hex(_api().read_u32(_addr(address)))


@mcp.tool()
def frida_read_cstring(address: str, max_length: int = 256) -> str:
    """Read a NUL-terminated ANSI string."""
    return str(_api().read_cstring(_addr(address), max_length))


@mcp.tool()
def frida_hook(address: str, nargs: int = 0, name: str = "") -> str:
    """Record every call of the function at `address`: ECX (this), the first `nargs` stack args and
    the return value. Read them with frida_events."""
    return _api().hook(_addr(address), nargs, name)


@mcp.tool()
def frida_unhook(address: str) -> str:
    """Remove a hook set by frida_hook."""
    return _api().unhook(_addr(address))


@mcp.tool()
def frida_events(clear: bool = True, limit: int = 200) -> str:
    """Recorded hook calls and caught exceptions (with registers and a backtrace), oldest first."""
    ev = _api().events(clear)
    return json.dumps(ev[-limit:], indent=1)


@mcp.tool()
def frida_eval(code: str) -> str:
    """Run JavaScript inside the game (Frida API: ptr, Memory, NativeFunction, Interceptor, ...).
    Returns the value of the last expression."""
    return json.dumps(_api().evaluate(code), default=str)


@mcp.tool()
def frida_detach() -> str:
    """Detach from the game (the game keeps running)."""
    if _state["session"] is not None:
        _state["session"].detach()
    _state.update(session=None, script=None)
    return "detached"


if __name__ == "__main__":
    mcp.run("stdio")
