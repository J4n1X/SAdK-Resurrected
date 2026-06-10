"""
Per-connection TinCat framing + the receive loop.

A Conn owns one client socket (lobby, UC/chat, or village). It handles the
28-byte header state machine, the handshake, and routing of application frames:
  * village connections  -> village.handle_frame (raw logging while we RE it)
  * chat-magic frames     -> chat.handle_frame
  * lobby frames          -> codec.decode_body + dispatch.dispatch_lobby
"""
import socket
import struct
import threading
from datetime import datetime

from . import chat, codec, config, dispatch, msgdefs, players, referee, registry, village
from .log import log, routed_to_unhandled
from .tincat import (BinaryReader, app_payload, build_frame,
                     build_handshake_payload, crc32, parse_header)

_conn_counter = 0
_counter_lock = threading.Lock()


def next_conn_id():
    global _conn_counter
    with _counter_lock:
        _conn_counter += 1
        return _conn_counter


class Conn:
    def __init__(self, sock, addr, conn_id, bin_file, is_chat=False, is_village=False,
                 is_game=False, is_referee=False):
        self._sock = sock
        self.addr = addr
        self.id = conn_id
        self._bin_file = bin_file
        self.is_chat = is_chat
        self.is_village = is_village
        # Dedicated game-server connection (GAME_CONN_VIA_STUB capture endpoint, :5480).
        # Framed/logged like a village conn, but is_village stays False so it does the
        # login WITHOUT the EnterWorld(1000) push (which would crash a GameServerConnection).
        self.is_game = is_game
        # Referee / match-arbiter connection (:5481). Does the SAME base login as UC/village
        # (188/211/213 → 153), then its cat=3 LobbyMessage data frames route to referee.handle_frame.
        # The match-start gate is cleared by the stub pushing LoginSuccess(0xDCA) (gated by ARM_REFEREE).
        self.is_referee = is_referee
        self._buf = b""
        self._state = "PREFIX"
        self._hdr = None
        self.shared = None          # ECDH shared secret
        self.session_key = None     # 32B session key issued in 207 (likely the token 213/214 key; s31)
        self.logged_in = False
        self.alive = True
        self._lock = threading.Lock()
        self.servers = {}           # ServerId -> info dict (per-conn store; single-user path)
        self._next_server_id = 100
        # Identity this connection serves. Defaults to the test account (byte-identical
        # to the old hardcoded TEST_*); login resolves a distinct player only when
        # config.MULTI_CLIENT_HOSTING is on (see players.py / dispatch._h_auth_cipher).
        self.player = players.default_player()

    def alloc_server_id(self):
        sid = self._next_server_id
        self._next_server_id += 1
        return sid

    # ── Low-level send ────────────────────────────────────────────────────────
    def send_raw(self, data):
        self._save("SEND", data)
        with self._lock:
            try:
                self._sock.sendall(data)
            except Exception as e:  # noqa: BLE001
                log(f"  [#{self.id}] send error: {e}")
                self.alive = False

    def _save(self, direction, data):
        if self._bin_file:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            from .log import _log_lock
            with _log_lock:
                self._bin_file.write(f"[{ts}] {direction} {len(data)} bytes\n".encode())
                self._bin_file.write(data + b"\n")
                self._bin_file.flush()

    def send_app(self, ptype, body):
        self.send_raw(build_frame(config.FROM_SERVER, self.id, config.MSG_APPLICATION,
                                  app_payload(ptype, body)))

    def send_chat(self, chat_bytes):
        self.send_raw(build_frame(config.FROM_SERVER, self.id, config.MSG_APPLICATION, chat_bytes))

    def ok(self, ticket):
        # Result(42): errorcode(UNBYTE)=0, errormsg(STRING32)=null, ticket_id
        body = struct.pack("<B", 0) + struct.pack("<i", 0) + struct.pack("<I", ticket)
        self.send_app(42, body)

    def status_with_id(self, errorcode, obj_id, ticket):
        # AddResult(153): errorcode, errormsg(null), id, ticket_id
        body = struct.pack("<B", errorcode) + struct.pack("<i", 0)
        body += struct.pack("<I", obj_id) + struct.pack("<I", ticket)
        self.send_app(153, body)

    # ── Receive loop ──────────────────────────────────────────────────────────
    def run(self):
        log(f"\n{'#' * 60}")
        log(f"  CONNECTION #{self.id}  {self.addr[0]}:{self.addr[1]}")
        log(f"{'#' * 60}")
        try:
            self._sock.settimeout(60.0)
            while self.alive:
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self._save("RECV", chunk)
                self._buf += chunk
                self._process()
        except Exception as e:  # noqa: BLE001
            log(f"  [#{self.id}] error: {e}")
        finally:
            self.alive = False
            self._sock.close()
            if self._bin_file:
                self._bin_file.close()
            if config.MULTI_CLIENT_HOSTING:
                dead = registry.games.remove_owner(self.id)
                if dead:
                    log(f"  [REGISTRY] dropped {len(dead)} game(s) owned by #{self.id}: {dead}")
            dispatch.unregister_observer(self)
            log(f"\n  DISCONNECTED #{self.id}")

    def _process(self):
        while True:
            if self._state == "PREFIX":
                if len(self._buf) < config.PREFIX_SIZE:
                    break
                self._hdr = parse_header(self._buf)
                self._buf = self._buf[config.PREFIX_SIZE:]
                self._state = "PAYLOAD"
            elif self._state == "PAYLOAD":
                psz = self._hdr["PayloadSize"]
                if len(self._buf) < psz:
                    break
                payload = self._buf[:psz]
                self._buf = self._buf[psz:]
                self._state = "PREFIX"
                self._on_message(payload)

    def _on_message(self, payload):
        h = self._hdr
        calc = crc32(payload)
        ok_str = "OK" if calc == h["Checksum"] else f"BAD(calc={calc:08X})"
        # The client floods the lobby with CONSTANT keepalive spam — TinCat pings + village/world
        # SendGameData(74) polls (~3/s while idling in the 3D lobby world). _is_quiet_frame classifies it,
        # and routed_to_unhandled() diverts the WHOLE message (frame header + village hex + decode +
        # dispatch) to tincat_lobby_unhandled.log (file only) in one shot, so the main view keeps only the
        # protocol under study (auth, server-list, AssignServer, referee, the real world-entry events, chat).
        with routed_to_unhandled(self._is_quiet_frame(h, payload)):
            log(f"\n{'-' * 60}")
            log(f"  [#{self.id}] <- CLIENT  TYPE={h['Type']}  {len(payload) + config.PREFIX_SIZE}B  CRC:{ok_str}")

            if h["Type"] == config.MSG_PING:
                log("  PING received (ignored)")
                return
            if h["Type"] == config.MSG_HANDSHAKE_CONNECT:
                self._handle_handshake(payload)
                return
            if h["Type"] != config.MSG_APPLICATION:
                log(f"  Unknown frame type {h['Type']}")
                return

            # Application frame.
            if self.is_referee:
                # The referee conn runs the SAME base login as UC/village (CheckVersion 188 → token 211/213 →
                # AddResult 153) — those are msgdef types and must decode+dispatch normally. Its DATA frames are
                # bare referee LobbyMessages whose type word carries category 3 in bits 14-12 (e.g. 0x3DCA /
                # RegisterGame 0x?B6); those are NOT msgdef types → route them to referee.handle_frame and stop.
                if len(payload) >= 4:
                    t1 = struct.unpack_from("<H", payload, 2)[0]
                    if ((t1 >> 12) & 7) == config.REF_CATEGORY:
                        referee.handle_frame(self, payload)
                        return
                # else a base-login frame (188/211/213/…) → fall through to the lobby decode+dispatch below.
            elif self.is_village or self.is_game:
                # The village/world conn is a UserCommConnection on the SAME 0x26B6 comm layer:
                # VillageServerConnection::HandleMessage (@0x470890) handles only village types (1000-1006,
                # 3xxx) and TAIL-CALLS the base UserComm dispatch for everything else — so its LOGIN
                # (CheckVersion 188 → token 211/213 → Result/153) is the SAME flow the lobby/UC handlers
                # already answer. Firewalling it into a log-only path stalled the login at CheckVersion, so
                # the 1000-series PropertySet templates never registered and the server-pushed EnterWorld
                # crashed in tincat3!DeserializeProperty. Fix: capture the frame (hex log) THEN fall through
                # to the normal decode+dispatch so the village login actually completes. (s34)
                village.handle_frame(self, payload)
                # (no return — fall through to the lobby decode+dispatch below)
            elif len(payload) >= 2 and struct.unpack_from("<H", payload, 0)[0] == config.CHAT_PAYLOAD_MAGIC:
                chat.handle_frame(self, payload)
                return

            # Lobby frame: Magic + Type1 (+ Type2 if it mirrors Type1) + body.
            r = BinaryReader(payload)
            _magic = r.u16()
            if _magic != config.PAYLOAD_MAGIC:
                # Not the lobby layer (0x26B6); chat (0x0062) was already handled+returned above. RE (s30)
                # found SADK uses a SINGLE comm layer (0x26B6), so an unexpected magic here would be news —
                # flag it loudly (and don't mis-parse it as a lobby frame) rather than silently dropping.
                log(f"  ⚠ APP-FRAME MAGIC 0x{_magic:04x} != lobby 0x{config.PAYLOAD_MAGIC:04x} "
                    f"— UNEXPECTED comm-layer magic (SADK should only use 0x26B6). Flagging for analysis.")
                log(f"    frame[:64]={payload[:64].hex()}")
                return
            t1 = r.u16()
            if r.remaining() >= 2 and r.peek_u16() == t1:
                r.u16()
            if msgdefs.get(t1) is None:
                # >=1000 village/world PropertySet message (no msgdefs schema; codec.decode_body would
                # KeyError). The raw frame is already hex-logged (village.handle_frame). Route to dispatch
                # with empty fields so the >=1000 branch logs it; never crash the conn on an unknown type.
                log(f"  TYPE {t1} (0x{t1:x}) — no msgdefs schema (village/world PropertySet); not decoded")
                dispatch.dispatch_lobby(self, t1, {})
                return
            fields = codec.decode_body(t1, payload, r.pos)
            name = msgdefs.name_of(t1)
            log(f"  TYPE {t1} = {name}")
            for k, v in fields.items():
                if isinstance(v, bytes):
                    log(f"    {k}: [{len(v)}B] {v[:32].hex()}{'...' if len(v) > 32 else ''}")
                else:
                    log(f"    {k}: {v!r}")
            dispatch.dispatch_lobby(self, t1, fields)

    def _is_quiet_frame(self, h, payload):
        """True if this is the client's CONSTANT in-lobby keepalive spam → divert its whole log block to
        tincat_lobby_unhandled.log. Quiet = TinCat pings + village/world SendGameData(74) polls whose inner
        msg_type has NO in-world handler (e.g. 0x27D0, ~3/s). The INTERESTING village events STAY in the main
        log: world-login (0x27D2), PingCode (0x2ED6), the server-pushed 1000/1006, and the base login (t1!=74).
        On a pure-lobby conn, routine account/social boilerplate (dispatch.is_quiet) is also diverted."""
        if h["Type"] == config.MSG_PING:
            return True
        if h["Type"] != config.MSG_APPLICATION or len(payload) < 4:
            return False
        t1 = struct.unpack_from("<H", payload, 2)[0]                       # app Type1
        if self.is_village or self.is_game:
            if t1 == config.VILLAGE_SENDGAMEDATA:                          # SendGameData(74) → peek inner msg_type
                off = 6 if (len(payload) >= 6 and struct.unpack_from("<H", payload, 4)[0] == t1) else 4
                if len(payload) >= off + 4:
                    msg_type = struct.unpack_from("<I", payload, off)[0]
                    return msg_type not in (config.WORLD_LOGIN_REQUEST_MSGTYPE,
                                            config.VILLAGE_PINGCODE_MSGTYPE)
            return False                                                   # base login / other village frames stay
        if self.is_referee:
            return False
        return dispatch.is_quiet(t1)

    # ── Handshake ─────────────────────────────────────────────────────────────
    def _handle_handshake(self, payload):
        if len(payload) != config.HANDSHAKE_SIZE:
            log(f"  !! Bad handshake size {len(payload)}")
        _hs_magic, _conn_id = struct.unpack_from("<II", payload)
        u0 = 8
        username_raw = payload[u0:u0 + config.HANDSHAKE_USERNAME_SIZE]
        p0 = u0 + config.HANDSHAKE_USERNAME_SIZE
        password_raw = payload[p0:p0 + config.HANDSHAKE_PASSWORD_SIZE]
        unknown1 = struct.unpack_from("<i", payload, p0 + config.HANDSHAKE_PASSWORD_SIZE)[0]
        log(f"  Machine user: {username_raw.rstrip(chr(0).encode())!r}")
        log(f"  Serial:       {password_raw.rstrip(chr(0).encode())!r}")

        reply_pl = build_handshake_payload(self.id, username_raw, unknown1)
        self.send_raw(build_frame(config.FROM_SERVER, config.FROM_CLIENT,
                                  config.MSG_HANDSHAKE_CONNECTED, reply_pl))
        log(f"  → HandShakeConnected (type 5), conn_id={self.id}")

        if self.is_chat:
            # s31 (trace agent): do NOT push ChannelInfo here (pre-login). The UC/usercomm
            # connection's chat-channel container (UserCommConnection+0x5c / m_ChatChannelManager)
            # isn't constructed until the token login completes. Pushing channels into it pre-login
            # leaves it half-built, and the post-login observer fan-out
            # (LobbyBaseConnection::NotifyObservers @0x48d7e0, fired by the 153 → LoggedIn) then
            # null-derefs reading it → process death ~215 ms after the 153. Deferred to the 213
            # handler, right AFTER the 153 ACK (see dispatch._h_send_token).
            log("  [CHAT] connection opened — ChannelInfo DEFERRED until after login (post-153)")
        if self.is_game:
            log("  [GAME] game-server connection opened (:5480 capture endpoint) — framing/logging like a "
                "village conn; login is answered (153 ACK) but NO EnterWorld push (would crash a "
                "GameServerConnection). Capturing the un-reversed game-room handshake.")
        if self.is_referee:
            log("  [REFEREE] referee connection opened (:5481) — answering the base login (188/211/213 → 153); "
                "cat=3 LobbyMessage frames route to referee.handle_frame. After login the stub "
                f"{'PUSHES' if config.ARM_REFEREE else 'will NOT push (ARM_REFEREE off)'} LoginSuccess(0xDCA) "
                "to clear the match-start gate.")
        if self.is_village:
            # s33: the PATCHED client now reaches this REAL village-server connection (:5479) without
            # crashing (3 conns alive, pinging). HandleEnterWorld (@0x46f470, SetState VillageEntered=9)
            # lives on THIS VillageServerConnection — so push EnterWorld(1000) HERE (not on the UC conn,
            # which has no village templates and would NULL-deref). Frames are still hex-dumped via the
            # recv loop (village.handle_frame), so we keep the capture too.
            if config.ARM_ENTER_WORLD:
                log("  [VILLAGE] connection opened — ARMED → EnterWorld(1000) fires after the village "
                    "login settles (debounced in village.handle_frame)")
            else:
                log("  [VILLAGE] connection opened — logging raw frames (no EnterWorld push yet)")
