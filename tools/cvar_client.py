#!/usr/bin/env python3
"""
cvar_client.py — talk to the game's own developer-tweak (CVar) server.

Why this tool exists (HARNESS §3): SADK.exe contains a CVar TCP server (ai::debug::CVarRemoteServer,
S 0067e690) that exposes every developer tweak — e.g. "Evil Hacks/CustomizeNPCHack", the NPC designer.
It is compiled into the release build but never started: CVarServerHolder_Init (S 0067c6d0) only creates
it when the byte at 0x0088ca50 is non-zero, and nothing sets it. Neither the Ghidra MCP (static) nor a
debugger MCP speaks this text protocol, so a tiny client is the only way to use it.

Enable it (one-byte-pair patch, on a COPY of SADK.exe):
    file offset 0x27C701:  74 44  ->  90 90     (JZ 0x0067c747 -> NOP NOP at VA 0x0067c701)
The server then listens on TCP port 1234 (u16 at 0x008810bc).

Protocol (text, every message ends with '&'; board #928 / #1352):
    server -> client:  APP$<appname>&   then   CREATE$<group>$<name>$<type>$<value>[$<min>$<max>]&
                       CHANGE$<group>$<name>$<value>&   DESTROY$<group>$<name>&
    client -> server:  CHANGE$<group>$<name>$<value>&   REFRESH$&   CUSTOM$<text>&
    type: b bool, i/l int32, d/u u32, f float, g double

Usage:
    python cvar_client.py [host] [port]          (default 127.0.0.1 1234)
Commands at the prompt:
    list [filter]            show the known tweaks (optionally only groups/names containing filter)
    set <group>/<name> <v>   change a tweak, e.g.  set Evil Hacks/CustomizeNPCHack 1
    refresh                  ask the game to resend every tweak
    raw <text>               send a raw message (the trailing & is added)
    quit
"""
import socket
import sys
import threading

tweaks = {}          # (group, name) -> [type, value, min, max]
lock = threading.Lock()


def handle(msg):
    parts = msg.split("$")
    kind = parts[0]
    with lock:
        if kind == "APP":
            print(f"\n[connected to {parts[1] if len(parts) > 1 else '?'}]")
        elif kind == "CREATE" and len(parts) >= 5:
            tweaks[(parts[1], parts[2])] = parts[3:]
        elif kind == "CHANGE" and len(parts) >= 4:
            entry = tweaks.setdefault((parts[1], parts[2]), ["?", parts[3]])
            entry[1] = parts[3]
            print(f"\n[changed] {parts[1]}/{parts[2]} = {parts[3]}")
        elif kind == "DESTROY" and len(parts) >= 3:
            tweaks.pop((parts[1], parts[2]), None)
        else:
            print(f"\n[server] {msg}")


def reader(sock):
    buf = b""
    while True:
        data = sock.recv(4096)
        if not data:
            print("\n[disconnected]")
            return
        buf += data
        while b"&" in buf:
            raw, buf = buf.split(b"&", 1)
            handle(raw.decode("latin-1"))


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 1234
    sock = socket.create_connection((host, port))
    threading.Thread(target=reader, args=(sock,), daemon=True).start()

    def send(text):
        sock.sendall((text + "&").encode("latin-1"))

    while True:
        try:
            line = input("cvar> ").strip()
        except EOFError:
            break
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        if cmd == "quit":
            break
        if cmd == "list":
            with lock:
                for (g, n), v in sorted(tweaks.items()):
                    if rest.lower() in f"{g}/{n}".lower():
                        rng = f"  [{v[2]}..{v[3]}]" if len(v) >= 4 else ""
                        print(f"  {g}/{n} ({v[0]}) = {v[1]}{rng}")
        elif cmd == "set":
            target, _, value = rest.rpartition(" ")
            group, _, name = target.partition("/")
            if not (group and name and value):
                print("usage: set <group>/<name> <value>")
                continue
            send(f"CHANGE${group}${name}${value}")
        elif cmd == "refresh":
            send("REFRESH$")
        elif cmd == "raw":
            send(rest)
        else:
            print("commands: list [filter] | set <group>/<name> <value> | refresh | raw <text> | quit")
    sock.close()


if __name__ == "__main__":
    main()
