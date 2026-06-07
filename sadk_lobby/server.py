"""
Server entry point: binds the three TinCat listeners and accepts connections.

  * lobby  (default 7070) — main lobby protocol
  * UC/chat (7071)        — second connection (must differ from the lobby port)
  * world  (5479)         — village/world third connection
"""
import argparse
import os
import socket
import sys
import threading
from datetime import datetime

from . import config
from .connection import Conn, next_conn_id
from .log import log, set_log_path


def _make_listener(port, label):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(10)
        s.settimeout(1.0)
        print(f"  {label} listening on port {port}")
        return s
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: could not bind {label} port {port}: {e}")
        return None


def _accept_loop(server_sock, label):
    while True:
        try:
            client_sock, addr = server_sock.accept()
        except socket.timeout:
            continue
        except Exception:
            break
        cid = next_conn_id()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bf = open(os.path.join(config.BIN_DIR, f"{label}_{cid}_{ts}.bin"), "wb")
        c = Conn(client_sock, addr, cid, bf,
                 is_chat=(label == "uc"), is_village=(label == "world"))
        threading.Thread(target=c.run, daemon=True).start()


def _banner(port):
    print()
    print("+----------------------------------------------+")
    print("|       SaDK TinCat Stub Server  (sadk_lobby)  |")
    print("+----------------------------------------------+")
    print(f"|  Lobby port : {port:<31}|")
    print(f"|  Username   : {'test':<31}|")
    print(f"|  Password   : {'test':<31}|")
    print(f"|  Serial     : {'test':<31}|")
    print("+----------------------------------------------+")
    print('|  LobbySettings.ini -> Host = "127.0.0.1"     |')
    print("+----------------------------------------------+")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(description="SaDK TinCat stub lobby server")
    parser.add_argument("--port", type=int, default=config.LOBBY_PORT)
    parser.add_argument("--log", default=config.LOG_FILE, help="log file path")
    args = parser.parse_args(argv)

    set_log_path(args.log)
    with open(args.log, "w", encoding="utf-8") as f:
        f.write(f"SaDK TinCat stub server (sadk_lobby)\nStarted: {datetime.now()}\n\n")
    os.makedirs(config.BIN_DIR, exist_ok=True)

    lobby = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lobby.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        lobby.bind(("0.0.0.0", args.port))
    except PermissionError:
        print(f"ERROR: cannot bind port {args.port}. Run as Administrator.")
        sys.exit(1)
    lobby.listen(10)
    lobby.settimeout(1.0)

    _banner(args.port)
    uc = _make_listener(config.UC_PORT, "UC/chat server")
    world = _make_listener(config.WORLD_PORT, "Lobby world stub")
    print()

    try:
        if uc:
            threading.Thread(target=_accept_loop, args=(uc, "uc"), daemon=True).start()
        if world:
            threading.Thread(target=_accept_loop, args=(world, "world"), daemon=True).start()
        _accept_loop(lobby, "lobby")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        lobby.close()
        if uc:
            uc.close()
        if world:
            world.close()


if __name__ == "__main__":
    main()
