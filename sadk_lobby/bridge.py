"""
Host bridge: makes a hosted game joinable when its host cannot accept incoming connections
(docs/bridge-protocol.md). The client side is the wsock32 shim (bridge/wsock32_shim/).

Why it is needed [known, static — docs/message-catalog.md "Reachability"]: the host's match transport
is a TinCat server that can only accept connections, and joiners dial the ip:port of the game's 170
descriptor directly. So a host behind NAT without a forwarded game port cannot be joined. The shim keeps
an OUTGOING control connection to this module instead, and the stub relays joiners through it.

Connections, all starting with one ASCII line "SADKB1 <verb> ...\\n" (TinCat frames start with the
magic EF FB BA DA, so the two cannot be confused):
  :BRIDGE_PORT  "SADKB1 HELLO <token>"          the shim's control connection (one per game client)
                "SADKB1 DATA <token> <channel>" a data channel the shim opened for one joiner
  :RELAY_PORT   "SADKB1 JOIN <game id>"         a joiner, redirected here by its own shim
  lobby (7070)  "SADKB1 LOBBY <token>"          tags the lobby connection with the shim's token, so a
                                                168 on it is paired exactly with its bridge
"""
import socket
import threading

from . import config, registry
from .log import log

PREFIX = b"SADKB1 "
MAX_LINE = 256
PROBE_TIMEOUT = 5.0           # the stub's connect-back for CHECK
CHANNEL_TIMEOUT = 10.0        # a joiner waits this long for the shim's DATA connection

_lock = threading.Lock()
_sessions = {}                # token -> Session (live control connections)
_pending = {}                 # channel id -> (joiner socket, leftover bytes, threading.Event, [data sock])
_bridged_games = {}           # game id -> token
_next_channel = 1


class Session:
    def __init__(self, token, sock, addr):
        self.token, self.sock, self.addr = token, sock, addr
        self.needs_bridge = False
        self.host_port = None
        self.send_lock = threading.Lock()

    def send(self, line):
        with self.send_lock:
            self.sock.sendall(line.encode("ascii") + b"\n")


def reset_for_tests():
    global _next_channel
    with _lock:
        _sessions.clear()
        _pending.clear()
        _bridged_games.clear()
        _next_channel = 1


def virtual_port(game_id):
    return config.BRIDGE_VPORT_BASE + int(game_id)


# ── Reading the preamble line ─────────────────────────────────────────────────
def read_line(sock, timeout=10.0):
    """Read one "SADKB1 ...\\n" line; returns (words, leftover bytes) or (None, bytes read) when the
    stream does not start with the prefix."""
    sock.settimeout(timeout)
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(MAX_LINE)
        if not chunk:
            return None, buf
        buf += chunk
        if not PREFIX.startswith(buf[:len(PREFIX)]) or len(buf) > MAX_LINE:
            return None, buf
    line, _, rest = buf.partition(b"\n")
    if not line.startswith(PREFIX):
        return None, buf
    return line[len(PREFIX):].decode("ascii", "replace").split(), rest


def split_preamble(buf):
    """For the lobby listener: (token or None, remaining bytes, complete?) — `complete` is False while
    a started preamble line is still missing its newline."""
    if not buf.startswith(PREFIX[:min(len(buf), len(PREFIX))]):
        return None, buf, True
    if b"\n" not in buf:
        return None, buf, len(buf) > MAX_LINE
    line, _, rest = buf.partition(b"\n")
    words = line[len(PREFIX):].decode("ascii", "replace").split()
    if len(words) == 2 and words[0] == "LOBBY":
        return words[1], rest, True
    return None, rest, True


# ── Lobby side: pairing a hosted game with its bridge ─────────────────────────
def needs_bridge(token):
    with _lock:
        s = _sessions.get(token)
    return bool(s and s.needs_bridge)


def game_registered(game_id, token):
    """A 168 arrived on a lobby connection tagged with `token`. If that client's reachability test
    failed, the game is advertised at the bridge's virtual address; returns (ip, port) or None."""
    if not token or not needs_bridge(token):
        return None
    with _lock:
        _bridged_games[int(game_id)] = token
    addr = (config.ADVERTISED_IP, virtual_port(game_id))
    log(f"  [BRIDGE] game {game_id} is bridged (token {token[:8]}…) → advertised at {addr[0]}:{addr[1]}")
    return addr


def game_removed(game_id):
    with _lock:
        _bridged_games.pop(int(game_id), None)


# ── Pipes ─────────────────────────────────────────────────────────────────────
def _pipe(a, b, label):
    def one_way(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    t = threading.Thread(target=one_way, args=(b, a), daemon=True)
    t.start()
    one_way(a, b)
    t.join()
    a.close()
    b.close()
    log(f"  [BRIDGE] {label} closed")


# ── :BRIDGE_PORT ──────────────────────────────────────────────────────────────
def _probe(session, port, nonce):
    """CHECK: connect back to the client's address on its game port and hand it the nonce there."""
    ok = False
    try:
        with socket.create_connection((session.addr[0], port), timeout=PROBE_TIMEOUT) as s:
            s.sendall(PREFIX + f"PROBE {nonce}\n".encode("ascii"))
            ok = True
    except OSError as e:
        log(f"  [BRIDGE] probe {session.addr[0]}:{port} failed: {e}")
    try:
        session.send(f"CHECKED {'ok' if ok else 'fail'} {nonce}")
    except OSError:
        pass
    log(f"  [BRIDGE] reachability {session.addr[0]}:{port} → {'reachable' if ok else 'NOT reachable'}")


def _control(sock, addr, token):
    session = Session(token, sock, addr)
    with _lock:
        old = _sessions.get(token)
        _sessions[token] = session
    if old is not None:
        try:
            old.sock.close()
        except OSError:
            pass
    log(f"  [BRIDGE] control connection {addr[0]}:{addr[1]} token {token[:8]}…")
    try:
        session.send(f"WELCOME relay={config.BRIDGE_RELAY_PORT} vbase={config.BRIDGE_VPORT_BASE} "
                     f"vip={config.ADVERTISED_IP}")
        sock.settimeout(None)
        buf = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                words = line.decode("ascii", "replace").split()
                if not words:
                    continue
                if words[0] == "CHECK" and len(words) == 3 and words[1].isdigit():
                    threading.Thread(target=_probe, args=(session, int(words[1]), words[2]),
                                     daemon=True).start()
                elif words[0] == "BRIDGED":
                    session.needs_bridge = True
                    log(f"  [BRIDGE] token {token[:8]}… needs the bridge to host")
                elif words[0] == "HOSTING" and len(words) == 2 and words[1].isdigit():
                    session.host_port = int(words[1])
                    log(f"  [BRIDGE] token {token[:8]}… is hosting on its port {session.host_port}")
                elif words[0] == "STOPPED":
                    session.host_port = None
                    log(f"  [BRIDGE] token {token[:8]}… stopped hosting")
    except OSError:
        pass
    finally:
        with _lock:
            if _sessions.get(token) is session:
                del _sessions[token]
        sock.close()
        log(f"  [BRIDGE] control connection token {token[:8]}… closed")


def _data(sock, token, channel):
    with _lock:
        entry = _pending.get(channel)
    if entry is None or entry[3] != token:
        log(f"  [BRIDGE] data connection for unknown channel {channel} — closed")
        sock.close()
        return
    entry[4].append(sock)
    entry[2].set()          # the joiner's thread takes over this socket


def _handle_bridge_port(sock, addr):
    try:
        words, _rest = read_line(sock)
    except OSError:
        words = None
    if not words:
        sock.close()
        return
    if words[0] == "HELLO" and len(words) == 2:
        _control(sock, addr, words[1])
    elif words[0] == "DATA" and len(words) == 3 and words[2].isdigit():
        _data(sock, words[1], int(words[2]))
    else:
        sock.close()


# ── :RELAY_PORT ───────────────────────────────────────────────────────────────
def _handle_relay_port(sock, addr):
    global _next_channel
    try:
        words, rest = read_line(sock)
    except OSError:
        words, rest = None, b""
    if not words or words[0] != "JOIN" or len(words) != 2 or not words[1].isdigit():
        sock.close()
        return
    game_id = int(words[1])
    with _lock:
        token = _bridged_games.get(game_id)
        session = _sessions.get(token) if token else None
        channel = _next_channel
        _next_channel += 1
        event = threading.Event()
        _pending[channel] = (sock, rest, event, token, [])
    if session is None or registry.games.get(game_id) is None:
        log(f"  [BRIDGE] joiner {addr[0]} for game {game_id}: no bridge for that game — closed")
        with _lock:
            _pending.pop(channel, None)
        sock.close()
        return
    try:
        session.send(f"OPEN {channel}")
    except OSError:
        pass
    ok = event.wait(CHANNEL_TIMEOUT)
    with _lock:
        entry = _pending.pop(channel, None)
    if not ok or not entry or not entry[4]:
        log(f"  [BRIDGE] joiner {addr[0]} for game {game_id}: host's shim never opened channel {channel}")
        sock.close()
        return
    data_sock = entry[4][0]
    try:
        data_sock.settimeout(None)
        sock.settimeout(None)
        if rest:
            data_sock.sendall(rest)
    except OSError:
        sock.close()
        data_sock.close()
        return
    log(f"  [BRIDGE] joiner {addr[0]}:{addr[1]} ↔ game {game_id} host (channel {channel})")
    _pipe(sock, data_sock, f"channel {channel} (game {game_id})")


# ── Listeners ─────────────────────────────────────────────────────────────────
def _serve(port, handler, label):
    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", port))
        srv.listen(32)
    except OSError as e:
        print(f"  WARNING: could not bind {label} port {port}: {e}")
        return
    print(f"  {label} listening on port {port}")
    while True:
        try:
            sock, addr = srv.accept()
        except OSError:
            break
        threading.Thread(target=handler, args=(sock, addr), daemon=True).start()


def start():
    threading.Thread(target=_serve, args=(config.BRIDGE_PORT, _handle_bridge_port, "Bridge control"),
                     daemon=True).start()
    threading.Thread(target=_serve, args=(config.BRIDGE_RELAY_PORT, _handle_relay_port, "Bridge relay"),
                     daemon=True).start()
