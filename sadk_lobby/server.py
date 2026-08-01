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

from . import config, crypto
from .connection import Conn, next_conn_id
from .log import log, set_log_path


def _check_crypto_deps():
    """Fail LOUDLY if the login-crypto deps are missing.

    The login handshake (ECDH 201/202 + Twofish session key 207 + token 213) cannot be done
    without `cryptography` and `twofish`. If they're absent the stub used to start anyway, send a
    blank/unencrypted 207, and CRASH the real client at login — with a misleading "twofish not
    installed" log buried mid-session. `twofish` is a build-from-source C extension with no Linux
    wheel, so a bare box silently fails to compile it. Surface that at startup instead. (s39.5)
    """
    missing = []
    if not crypto.ECDH_AVAILABLE:
        missing.append("cryptography  (pip install cryptography)")
    if not crypto.TWOFISH_AVAILABLE:
        missing.append("twofish       (pip install twofish  -- needs a C compiler: "
                       "apt install build-essential python3-dev)")
    if missing:
        bar = "!" * 70
        print(f"\n{bar}")
        print("  FATAL: login-crypto dependency missing -- the client WILL crash at login.")
        for m in missing:
            print(f"    - {m}")
        print(f"  Python: {sys.executable}")
        print("  Install the dep for THIS interpreter (venv mismatch is the usual cause),")
        print("  then verify:  python -c \"import twofish, cryptography; print('crypto OK')\"")
        print(f"{bar}\n")
        return False
    return True


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
                 is_chat=(label == "uc"), is_village=(label == "world"),
                 is_referee=(label == "referee"))
        threading.Thread(target=c.run, daemon=True).start()


def _banner(port):
    print()
    print("+----------------------------------------------+")
    print("|       SaDK TinCat Stub Server  (sadk_lobby)  |")
    print("+----------------------------------------------+")
    print(f"|  Lobby port : {port:<31}|")
    print(f"|  Username   : {'ANY — becomes your name':<31}|")
    print(f"|  Password   : {'ANY — not checked':<31}|")
    print(f"|  Serial     : {'ANY — not checked':<31}|")
    print("+----------------------------------------------+")
    print("|  Players just need DIFFERENT usernames.      |")
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

    # Refuse to start without the login-crypto deps — a missing twofish silently crashes the
    # real client at login (the exact Linux-third-machine trap). Better a clear abort than that.
    if not _check_crypto_deps():
        sys.exit(2)

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
    referee_srv = _make_listener(config.REFEREE_PORT, "Referee server")
    print()

    try:
        if uc:
            threading.Thread(target=_accept_loop, args=(uc, "uc"), daemon=True).start()
        if world:
            threading.Thread(target=_accept_loop, args=(world, "world"), daemon=True).start()
        if referee_srv:
            threading.Thread(target=_accept_loop, args=(referee_srv, "referee"), daemon=True).start()
        _accept_loop(lobby, "lobby")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        lobby.close()
        if uc:
            uc.close()
        if world:
            world.close()
        if referee_srv:
            referee_srv.close()


if __name__ == "__main__":
    main()
