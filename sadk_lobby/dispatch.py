"""
Lobby application-message dispatch.

Every inbound message is decoded generically by the codec (canonical msgdefs
field names), then routed here. Types we care about have explicit handlers;
everything else falls through to a default Result-OK ack so no message type is
left unhandled.

Handler signature:  fn(conn, fields: dict, ticket: int)

Multiple clients can be logged in as distinct players at once; hosted games live
in a process-global registry (players.py / registry.py) so one client's game is
visible to another.
"""
import os
import struct
import threading
import time

from . import chat, codec, config, crypto, msgdefs, players, registry, village
from .log import log

HANDLERS = {}

# Observer subscriptions for server-list push notifications.
# Maps server_type → list of live Conn objects that subscribed via 171 RegObserverServerList.
# The stub pushes 170 GameServerData to all matching observers when a game is added/changed,
# so the browser updates without the joiner having to re-request the list.
# Cleaned up by unregister_observer() when a connection closes (connection.py finally block).
_obs_lock = threading.Lock()
_obs: dict = {}   # int server_type → list[Conn]


def _reg_obs(conn, server_type):
    with _obs_lock:
        _obs.setdefault(server_type, [])
        if conn not in _obs[server_type]:
            _obs[server_type].append(conn)


def unregister_observer(conn):
    """Remove conn from all observer lists (call from connection.py on close)."""
    with _obs_lock:
        for lst in _obs.values():
            try:
                lst.remove(conn)
            except ValueError:
                pass


def _push_to_obs(server_type, srv):
    """Push a 170 GameServerData to all registered observers for server_type (and type-0 subscribers)."""
    with _obs_lock:
        targets = list(set(_obs.get(server_type, []) + _obs.get(0, [])))
    if not targets:
        return
    body = codec.encode_body(170, server_to_170_values(srv, 0))
    pushed = 0
    for c in targets:
        if getattr(c, "alive", False):
            try:
                c.send_app(170, body)
                pushed += 1
            except Exception:  # noqa: BLE001
                pass
    if pushed:
        log(f"  [OBS] pushed 170 GameServerData id={srv.get('id')} to {pushed} observer(s)")


def handler(*types):
    def deco(fn):
        for t in types:
            HANDLERS[t] = fn
        return fn
    return deco


def dispatch_lobby(conn, type_num, fields):
    ticket = fields.get("ticket_id", 0) or 0
    fn = HANDLERS.get(type_num)
    if fn is not None:
        fn(conn, fields, ticket)
    elif type_num >= 1000:
        # Village/world property-bag message (1001-1006, 0xED6 …) that arrives AFTER a successful
        # EnterWorld. We don't model the in-world protocol yet — just LOG it; do NOT send a lobby
        # Result(42) ack (wrong layer; acking could destabilize the world session). This capture is
        # what we need to build the next (in-world) stage.
        log(f"  [VILLAGE-MSG] type {type_num} (0x{type_num:x}) received post-entry — logged, NOT acked")
    else:
        log(f"  (default-ack: {msgdefs.name_of(type_num)} [{type_num}])")
        conn.ok(ticket)


# ── Identity + game-store helpers ─────────────────────────────────────────────

def _player(conn):
    """The player identity this connection serves (default = test account)."""
    return players.of(conn)


def _register_game(conn, info):
    """Store a hosted game (168) in the process-global registry; returns the server_id."""
    return registry.games.add(conn.id, info)


def _remove_game(conn, sid):
    """Remove a hosted game (169) owned by this connection."""
    return registry.games.remove(conn.id, sid)


def _change_owned_game(conn, changes):
    """Apply field changes (177) to the game this connection hosts; returns the record."""
    return registry.games.update_owned(conn.id, changes)


def _get_game(conn, sid):
    """Look up a game by id (221), cross-client."""
    return registry.games.get(sid)


def _owned_game(conn):
    """The game this connection hosts (for its own AssignServer 189), or None."""
    return registry.games.get_owned(conn.id)


def _games_for_list(conn, server_type):
    """Games to advertise for a server-list request (server_type 0 == any)."""
    return registry.games.list_by_type(server_type)


# ── Auth flow ─────────────────────────────────────────────────────────────────
@handler(201)  # StartAuthenticateSession
def _h_auth_start(conn, fields, ticket):
    key = fields.get("key")
    if not key:
        log("  !! No key in StartAuthenticateSession"); return
    try:
        reply_cipher, conn.shared = crypto.handle_login_key(key)
        log(f"  ECDH OK. shared={conn.shared.hex()[:16]}...")
        conn.send_app(202, codec.encode_body(202, {"cipher": reply_cipher, "ticket_id": ticket}))
        log("  → AckAuthenticateSession (202) sent")
    except Exception as e:  # noqa: BLE001
        log(f"  !! ECDH failed: {e}")


@handler(203, 204, 206)  # SelfRegistration / AuthenticateUser / AuthenticateServer
def _h_auth_cipher(conn, fields, ticket):
    cipher = fields.get("cipher")
    if not cipher:
        log("  !! No cipher in auth message"); return
    if not conn.shared:
        log("  !! No shared secret — StartAuthenticateSession must come first"); return
    creds = {}
    try:
        blob = crypto.decrypt_cipher(cipher, conn.shared)
        creds = crypto.decode_login_blob(blob, has_cdkey=True)
        log(f"  auth: username={creds.get('username')!r}"
            + (f"  cd_key={creds['cd_key']!r}" if "cd_key" in creds else ""))
    except ImportError as e:
        log(f"  !! {e} — accepting anyway")
    except Exception as e:  # noqa: BLE001
        log(f"  !! Decryption failed: {e}")
    conn.logged_in = True
    # Bind this lobby connection to the account it logged in as, so the SessionKey(207) perm_id
    # and the char/user replies serve that player. The perm_id propagates to this client's UC +
    # village conns via the token (213).
    conn.player = players.resolve_by_username(creds.get("username"))
    log(f"  [PLAYER] lobby #{conn.id} → {conn.player.username!r} (perm_id={conn.player.perm_id})")
    session = None
    if crypto.TWOFISH_AVAILABLE and conn.shared:
        # KEEP the 32B session key (the token 213/214 crypto almost certainly uses it as the key,
        # and the stub must know it to build a valid 214; s31).
        conn.session_key = os.urandom(32)
        session = crypto.encrypt_session_key(conn.session_key, conn.shared)
    _send_session_key(conn, ticket, session)


def _send_session_key(conn, ticket, session_cipher=None):
    perm_id = _player(conn).perm_id
    conn.send_app(207, codec.encode_body(207, {
        "perm_id": perm_id, "cipher": session_cipher, "ticket_id": ticket}))
    log(f"  → SessionKey (207) perm_id={perm_id}")


@handler(4)  # RequestLogin (legacy plaintext path)
def _h_request_login(conn, fields, ticket):
    log(f"  RequestLogin nick={fields.get('nick')!r}")
    conn.player = players.resolve_by_username(fields.get("nick"))
    conn.ok(ticket)
    _send_session_key(conn, ticket, None)
    conn.logged_in = True


@handler(71)  # RequestCreateAccount
def _h_create_account(conn, fields, ticket):
    log(f"  RequestCreateAccount nick={fields.get('nick')!r}")
    conn.ok(ticket)
    conn.logged_in = True


@handler(188)  # CheckVersion
def _h_check_version(conn, fields, ticket):
    log(f"  Version {fields.get('version')}.{fields.get('subversion')}")
    conn.ok(ticket)


# ── Properties ────────────────────────────────────────────────────────────────
@handler(161)  # PropertyGet -> PropertyData
def _h_property_get(conn, fields, ticket):
    kat = fields.get("kategory", 0)
    idx = fields.get("index", 0)
    conn.send_app(162, codec.encode_body(162, {
        "kategory": kat, "index": idx, "value": 0, "ticket_id": ticket}))
    conn.ok(ticket)


# ── Account / character info ──────────────────────────────────────────────────
@handler(53)  # RequestUsers -> UserData
def _h_user_info(conn, fields, ticket):
    p = _player(conn)
    conn.send_app(59, codec.encode_body(59, {
        "user_id": p.perm_id, "name": p.username,
        "password": None, "mail": "test@test.test",
        "banned": False, "active": True, "status": 2,
        "data": p.data,
        "created": "2024-01-01 00:00:00+0:00",
        "last_login": "2024-01-01 00:00:00+0:00",
        "total_logins": 1, "ticket_id": ticket}))
    conn.ok(ticket)


def _char_values(conn, ticket):
    p = _player(conn)
    return {
        "char_id": p.char_id, "name": p.char_name,
        "owner_id": p.perm_id, "owner_name": p.username,
        "guild_id": 0, "guild_name": None, "guild_role": 0, "status": 1,
        "server_id": 0, "server_name": None, "data": p.data,
        "ticket_id": ticket}


@handler(55)  # RequestUserCharList -> UserCharConn
def _h_player_info(conn, fields, ticket):
    conn.send_app(60, codec.encode_body(60, _char_values(conn, ticket)))
    conn.ok(ticket)


@handler(72)  # RequestCharacters -> CharacterData
def _h_select_nickname(conn, fields, ticket):
    conn.send_app(75, codec.encode_body(75, _char_values(conn, ticket)))
    conn.ok(ticket)


@handler(77)  # CreateCharacterFromPreview
def _h_register_nickname(conn, fields, ticket):
    log(f"  CreateCharacter name={fields.get('name')!r}")
    conn.status_with_id(0, _player(conn).perm_id, ticket)


@handler(86, 88, 94)  # AddCharacter / ChangeUser(confirm) / RemoveCharacter
def _h_char_ack(conn, fields, ticket):
    conn.ok(ticket)


# ── CD keys ───────────────────────────────────────────────────────────────────
@handler(158)  # RequestUserKeyList -> UserKeyConn
def _h_cdkeys(conn, fields, ticket):
    conn.send_app(159, codec.encode_body(159, {
        "user_id": _player(conn).perm_id, "cd_key": "0000000000000000",
        "keypool": 1, "ticket_id": ticket}))
    conn.ok(ticket)


# ── Social / observers (ack-only) ─────────────────────────────────────────────
@handler(56, 98, 99, 107, 108, 115, 116, 175, 176, 172, 146, 190)
def _h_ack(conn, fields, ticket):
    conn.ok(ticket)


@handler(157)  # RequestUserIgnoreList — the LAST message of the lobby-connection login
def _h_ignore_list(conn, fields, ticket):
    conn.ok(ticket)


# ── MOTD ──────────────────────────────────────────────────────────────────────
@handler(105)  # RequestMOTD -> MOTD
def _h_motd(conn, fields, ticket):
    conn.send_app(106, codec.encode_body(106, {
        "txt": "Willkommen! SaDK Revival Server - WIP", "ticket_id": ticket}))


# ── Assign server (AssignServer 189) ──────────────────────────────────────────
@handler(189)  # AssignServer -> UsercommServerData(192)
def _h_assign_server(conn, fields, ticket):
    """Point the client at the stub's UC/chat server (:7071).

    The 192 is consumed by tincat3's generic CommLayer 0xc0 handler (FUN_10030420): it dials
    the advertised ip:port and stands up the UserComm-SERVER connection that our :7071 listener
    serves chat over. The handler does NOT validate the ticket category, so an unsolicited
    ticket_id is accepted the same as a reply ticket.
    """
    server_type = fields.get("server_type", 0)
    server_subtype = fields.get("server_subtype", 0)

    # ── Referee assign (type=4, subtype=4) ── [flag-gated · ER 2026-06-13_referee-assign-170] ──────────
    # RequestRefereeServer@0x468f60 sends AssignServer(4,4); a debugger trace of AssignServer (2026-06-13,
    # live) confirmed the discriminator is server_subtype=4 (village-entry uses the 221→222 path, not 189).
    # Reply a GameServerData(170) for the REFEREE_SERVER (type4/sub5) so its cat-0x108 ticket routes into
    # tincat3 GameServerManager_OnGameServerAssigned@0x10021520 → SetRefereeServerAddress@0x4625d0 →
    # LM+0x580. The 192 below still goes out (different message type → tincat3's UsercommServerData dial
    # handler, independent of the 170) so UC/chat stays up.
    if config.REPLY_REFEREE_ASSIGN and server_type == 4 and server_subtype == 4:
        conn.send_app(170, codec.encode_body(170, server_to_170_values(REFEREE_SERVER, ticket)))
        log(f"  → [REFEREE] GameServerData(170) id={config.REF_SERVER_ID} type4/sub5 "
            f"-> {config.ADVERTISED_IP}:{config.REFEREE_PORT} (ticket={ticket})")

    # ── Game-server assign (type=5, subtype=1) — the host's match-server registration ───────────────
    # [PROVEN static, docs/MP_P2P_TRANSITION.md] FUN_0046aaa0 does StartUpNetwork(4) (TinCat host) then
    # sends AssignServer(189 type5/sub1) and parks villageList+0x9c=-2 ("Connecting to Game Server").
    # tincat3 GameServerManager_OnGameServerAssigned@0x10021520 special-cases ONLY type4/sub5 (referee);
    # any other descriptor → the default sink LobbyVillageServerList.vtbl[0x28] =
    # LobbyServerList_GameServerAssigned@0x469ad0, which fires the pending-assign callback with
    # serverDesc->server_id and CLEARS villageList+0x9c → the dialog completes. So reply a
    # GameServerData(170) echoing the host's OWN hosted game (type/sub stays 5/x, never 4/5). A game
    # assign must NOT also get the UC 192 (that is the chat server) → return after the 170.
    if config.REPLY_GAME_SERVER_ASSIGN and server_type == 5 and server_subtype == 1:
        game = _owned_game(conn)
        if game is not None:
            conn.send_app(170, codec.encode_body(170, server_to_170_values(game, ticket)))
            log(f"  → [GAME] GameServerData(170) id={game['id']} "
                f"type{game.get('server_type', 5)}/sub{game.get('server_subtype', 0)} "
                f"-> {game['ip']}:{game['port']} (ticket={ticket}) — clears villageList+0x9c")
            return
        log("  ! AssignServer(type5/sub1) but this conn hosts no game — no 170 to echo; sending 192")

    conn.send_app(192, codec.encode_body(192, {
        "server_id": 1, "ip": config.ADVERTISED_IP, "port": config.UC_PORT,
        "server_type": server_type,
        "version": None, "data": None, "ticket_id": ticket}))
    log(f"  → UsercommServerData(192) -> {config.ADVERTISED_IP}:{config.UC_PORT} "
        f"(type={server_type}, subtype={server_subtype}, ticket={ticket})")


# ── Game/village server list ──────────────────────────────────────────────────
def server_to_170_values(srv, ticket):
    return {
        "server_id": srv["id"], "name": srv["name"], "owner_id": srv["owner_id"],
        "description": srv.get("description", ""), "ip": srv["ip"], "port": srv["port"],
        "password_required": False,
        "server_type": srv.get("server_type", 5),
        "server_subtype": srv.get("server_subtype", 0),
        "version": srv.get("version", ""),
        "max_players": srv.get("max_players", 2), "cur_players": srv.get("cur_players", 1),
        "max_spectators": 0, "cur_spectators": 0, "ai_players": srv.get("ai_players", 0),
        "room_id": srv.get("lobby_id", 9212),
        "level": srv.get("level", 0), "game_mode": srv.get("game_mode", 0),
        "hardcore": bool(srv.get("hardcore")), "map": srv.get("map", ""),
        "running": bool(srv.get("running")), "locked_config": False,
        "data": srv.get("data"), "ticket_id": ticket}


def server_data_block(room_id):
    """Build the village 'ServerDataBlock' that makes a list entry JOINABLE. [PROVEN, s15 live]

    FillFromDescriptor @0x481640 sets entry.roomId(+0x30) from the FIRST field of this block (the
    170 `data` MEMBLOCK), read BIG-ENDIAN, then a 1-byte pending flag. Without the block the client
    logs "Invalid Server Data Block" and forces entry.validity(+0x35)=0 → the Enter button greys
    out. Layout: 4-byte BIG-ENDIAN roomId + 1 pending byte (=0). roomId MUST equal the client's
    match key DAT_0087aed8 (= ProtocolVersion); see config.LOBBY_PROTOCOL_VERSION.
    server_data_block(1000) == b"\\x00\\x00\\x03\\xe8\\x00".
    """
    return struct.pack(">I", int(room_id)) + b"\x00"


# The ServerType=4 village world that gets us INTO the list (s12/s13). [PROVEN]
# id MUST NOT be 1 — AssignServer/UsercommServerData(192) advertises the UC server as server_id=1,
# so a village with id=1 makes CommLayer_ResolveServer reuse the already-connected UC conn instead
# of dialing :5479. A unique id forces a real dial.
FAKE_VILLAGE = {
    "id": 50, "owner_id": config.TEST_PERM_ID,
    "name": "world1", "description": "SaDK Revival Lobby World",
    "ip": config.ADVERTISED_IP, "port": config.WORLD_PORT,
    "max_players": 20, "cur_players": 1, "ai_players": 0,
    "lobby_id": 1000, "version": "", "server_type": 4, "server_subtype": 2,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "world1", "running": True,
    # The village entry's roomId/validity come from this 170 `data` MEMBLOCK, NOT the room_id field
    # (s15 live-confirmed). 5 bytes = roomId as BIG-ENDIAN u32 + 1 pending byte; roomId must equal
    # the client's ProtocolVersion (DAT_0087aed8) or Enter stays grey — see config.
    "data": server_data_block(config.LOBBY_PROTOCOL_VERSION),
}

# The referee/match-arbiter server (server_type=4, server_subtype=5). Advertised so its server_id resolves
# to ip:port via the ConnectionManager when LobbyManager_InitRefereeServerConnection dials it. A unique id
# (REF_SERVER_ID, not 1/50) forces a real dial to REFEREE_PORT rather than reusing the UC/village conn.
# No data block (not a joinable village); not on the browsable game list (subtype 5 ≠ village 2 / game 1).
REFEREE_SERVER = {
    "id": config.REF_SERVER_ID, "owner_id": config.TEST_PERM_ID,
    "name": "referee", "description": "SaDK Referee",
    "ip": config.ADVERTISED_IP, "port": config.REFEREE_PORT,
    "max_players": 0, "cur_players": 0, "ai_players": 0,
    "lobby_id": config.LOBBY_PROTOCOL_VERSION, "version": "",
    "server_type": 4, "server_subtype": 5,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "", "running": False, "data": None,
}


def _send_server_list(conn, server_type, ticket):
    sent = 0
    for srv in _games_for_list(conn, server_type):
        conn.send_app(170, codec.encode_body(170, server_to_170_values(srv, ticket)))
        sent += 1
    if sent == 0 and server_type == 4:
        conn.send_app(170, codec.encode_body(170, server_to_170_values(FAKE_VILLAGE, ticket)))
        sent += 1
        log("  → Injected fake village world (ServerType=4) w/ room-assign data blob")
    # NO synthetic GAME entry. The game browser (server_type 5) shows ONLY real hosted games,
    # registered via AddGameServer(168) and relayed cross-client from the registry in the loop above.
    # The client sets server_subtype=1 itself when it hosts a browsable game, so a hosted game routes
    # to BrowseGameDialog on its own with its real player count. An empty list when nobody hosts is
    # the correct, honest state.
    conn.ok(ticket)
    log(f"  → ServerList(type={server_type}): sent {sent} server(s) + OK")


@handler(171)  # RegObserverServerList
def _h_reg_observer_servers(conn, fields, ticket):
    server_type = fields.get("server_type", 0)
    room = fields.get("room_id")
    log(f"  RegObserverServerList type={server_type} room_id={room} send_all={fields.get('send_all')}")
    _reg_obs(conn, server_type)   # register for future push notifications
    _send_server_list(conn, server_type, ticket)


@handler(166)  # RequestServers (one-shot)
def _h_request_servers(conn, fields, ticket):
    log(f"  RequestServers type={fields.get('server_type')} room_id={fields.get('room_id')}")
    _send_server_list(conn, fields.get("server_type", 0), ticket)


@handler(168)  # AddGameServer
def _h_add_game_server(conn, fields, ticket):
    info = {
        "owner_id": _player(conn).perm_id,
        "name": fields.get("name", "TestGame"),
        "description": fields.get("description", ""),
        "ip": fields.get("ip") or conn.addr[0],
        "port": fields.get("port", config.WORLD_PORT),
        "max_players": fields.get("max_players", 2), "cur_players": 1,
        "ai_players": fields.get("ai_players", 0),
        "lobby_id": fields.get("room_id", 9212),
        "version": fields.get("version", ""),
        "server_type": fields.get("server_type", 5),
        "server_subtype": fields.get("server_subtype", 0),
        "level": fields.get("level", 0), "game_mode": fields.get("game_mode", 0),
        "hardcore": fields.get("hardcore", False),
        "map": fields.get("map", ""), "running": fields.get("running", False),
        "data": fields.get("data"),
    }
    sid = _register_game(conn, info)
    log(f"  AddGameServer: id={sid} name={info['name']!r} map={info['map']!r} "
        f"owner={info['owner_id']} subtype={info['server_subtype']}")
    conn.status_with_id(0, sid, ticket)
    # Push 170 to all subscribed observers so their browser updates without a re-request.
    _push_to_obs(info["server_type"], {**info, "id": sid})


@handler(169)  # RemoveServer
def _h_remove_server(conn, fields, ticket):
    _remove_game(conn, fields.get("server_id", 0))
    conn.ok(ticket)


@handler(177)  # ChangeGameServer
def _h_change_server(conn, fields, ticket):
    # Only overwrite fields the message actually carried a value for (a 177 may touch a subset;
    # the stub ignores property_mask).
    changes = {k: fields.get(k) for k in
               ("name", "description", "max_players", "map", "running", "data")
               if fields.get(k) is not None}
    rec = _change_owned_game(conn, changes)
    if rec is not None:
        log(f"  ChangeGameServer: id={rec.get('id')} running={rec.get('running')} map={rec.get('map')!r}")
        # Keep observers' browser current as the host changes map/settings.
        _push_to_obs(rec.get("server_type", 5), rec)
    conn.ok(ticket)


@handler(221)  # RequestConnectionData -> ConnectionData
def _h_connection_data(conn, fields, ticket):
    sid = fields.get("server_id", 0)
    srv = _get_game(conn, sid)
    # P2P handoff: a join to a real hosted game returns that host's advertised address (the joiner
    # dials the host directly). The lobby-WORLD entry request (server_id=50, the injected
    # FAKE_VILLAGE, never registered → srv is None) falls back to WORLD_PORT (:5479).
    ip = srv["ip"] if srv else config.ADVERTISED_IP
    port = srv["port"] if srv else config.WORLD_PORT
    conn.send_app(222, codec.encode_body(222, {
        "perm_id": _player(conn).perm_id, "server_id": sid,
        "ip": ip, "port": port,
        "nonce": os.urandom(128), "errorcode": 0, "errormsg": None,
        "ticket_id": ticket}))
    log(f"  → ConnectionData(222) server={sid} → {ip}:{port}"
        + ("" if srv else "  (unknown id — fell back to advertised world)"))


# ── Token / chat-login validation ─────────────────────────────────────────────
@handler(211)  # StartValidateTokenSession -> AckValidateTokenSession
def _h_token_start(conn, fields, ticket):
    conn.token_nonce = os.urandom(128)          # remember our challenge so we can mirror it in 214
    conn.send_app(212, codec.encode_body(212, {"nonce": conn.token_nonce, "ticket_id": ticket}))
    log("  → AckValidateTokenSession (212) sent")


@handler(213)  # SendToken -> AddResult(153)  [the 0x99 ACK the client awaits; NOT a 214]
def _h_send_token(conn, fields, ticket):
    # [PROVEN, s31] The UC-login client state machine (tincat3 ClientRecvHandler) has NO case for 214
    # (jump-table bound 0xAA, so a 214 is dropped as "Invalid message-type"). After 213 SendToken the
    # client waits for the 0x99 ACK = NETMSG 153 (AddResult) with errorcode==0 → connState→8 AUTHORIZED
    # → fires the LoggedIn callback. So we ACK with 153, not a 214. (The 214/Twofish-CTR path is only
    # consumed on the separate secured ROOM-server connection.)
    perm_id = fields.get("perm_id", config.TEST_PERM_ID)
    # The UC + village connections carry the perm_id the lobby issued in 207; bind this connection
    # to that player (its chat user-info / world identity).
    if fields.get("perm_id"):
        conn.player = players.resolve_by_perm(fields["perm_id"])
        perm_id = conn.player.perm_id
        log(f"  [PLAYER] token #{conn.id} → {conn.player.username!r} (perm_id={perm_id})")
    conn.status_with_id(0, perm_id, ticket)   # NETMSG 153 AddResult, errorcode=0 → the 0x99 ACK
    log("  → SendToken → AckResult(153) errorcode=0 [the 0x99 ACK → state 8 AUTHORIZED → LoggedIn]")
    # Post-login: push the chat ChannelInfo (deferred from the handshake so it lands in a
    # fully-constructed channel container instead of corrupting a half-built one; s31).
    if getattr(conn, "is_chat", False):
        chat.send_initial_reply(conn)
    # WORLD ENTRY [PROVEN, s39 live]: on the VILLAGE conn (:5479) after this 153 ACK the client parks
    # at LobbyManager EnteringVillage(8) and waits for the server to push EnterWorld (msg 1000). Its
    # own world-login request is dormant, so the genuine fix is for the server to PROVIDE msg 1000:
    # village.send_enter_world wraps it in the SendGameData(74) envelope → HandleEnterWorld →
    # SetState(VillageEntered=9) → the 3D world renders. Only on the village conn (lobby/UC lack the
    # 1000-series templates and would NULL-deref).
    if getattr(conn, "is_village", False):
        def _push_enter_world(c=conn):
            time.sleep(config.ENTER_WORLD_DELAY)
            village.send_enter_world(c)             # idempotent (_enter_world_sent latch)
        threading.Thread(target=_push_enter_world, daemon=True).start()
        log(f"  [ENTER] (VILLAGE) pushing EnterWorld(1000) in {config.ENTER_WORLD_DELAY}s "
            "→ HandleEnterWorld → SetState(VillageEntered=9).")
    else:
        log("  [ENTER] (lobby/UC) 153 ACK — no world push on this conn.")


# ── Village / world game-data envelope (SendGameData 74) ───────────────────────
@handler(74)  # SendGameData — the NETMSG envelope that carries every village/world message (1000+)
def _h_send_game_data(conn, fields, ticket):
    """Village/world envelope handler. The genuine world-entry mechanism is the SERVER pushing
    EnterWorld (msg 1000) once the transport is AUTHORIZED (see _h_send_token / village.send_enter_world).
    The client's own SendGameData(74){0x27D2} world-login request is dormant at lobby-entry but LIVE at
    MATCH-START — the client re-sends it, and we MUST answer each one with a fresh 1000 (see the 0x27D2
    branch; one-shot latch bypassed via force=True). This handler also answers in-world PingCodes."""
    msg_type = fields.get("msg_type", 0)
    data = fields.get("data", b"") or b""
    if not getattr(conn, "is_village", False):
        log(f"  (SendGameData[74] msg_type=0x{msg_type:x} on non-village conn #{conn.id} — logged)")
        return
    if msg_type == config.VILLAGE_LEAVE_REQUEST_MSGTYPE:      # 0x27D2 — msg 2002 LEAVE-VILLAGE request
        # [PROVEN 2026-07-25/26] This is a LEAVE request, not a world-login: the client's
        # VillageServerConnection_SendLeaveVillageRequest_2002@0x0046bde0 sets
        # LobbyManager::SetState(LeavingVillage=10) and then WAITS. State 10 has exactly two exits —
        # HandleLoggedOut (vtbl+0x1c, unreachable for the village transport class ConnectionReal) and
        # HandleDisconnected (vtbl+0x20, via OnConnectionLost) — and StatePump_Tick never touches state
        # 10, so the client cannot recover on its own. Answering with EnterWorld(1000) told it to ENTER
        # when it asked to LEAVE (that is the "clone"); answering with nothing hung it forever. The
        # genuine completion is for the server to END the connection it was asked to leave.
        # ER: engagement_records/2026-07-26_village-leave-close-connection.md
        # ⛔ LIVE-FALSIFIED 2026-07-26 — closing the connection is NOT how a logout completes.
        # We shipped exactly that (close the village conn on 2002) and tested it:
        #   * single client leaving a village → the leave DOES complete (state 10 → 11, screen returns
        #     to character select) BUT the client shows "!CONNECTION_LOST_TEXT"
        #     ("Fehler: Verbindung zum Server verloren") — so the close surfaces with a NON-ZERO reason;
        #   * at MATCH START both clients send 2002, so BOTH village conns got closed and BOTH players
        #     were KICKED — strictly worse than the hang it replaced.
        # Reverted to a no-op. The RE model (state 10 has only two exits, and the referee arm hangs off
        # the +0x1c LoggedOut observer which a close does NOT fire — a close fires +0x28 Disconnected)
        # still stands; what is refuted is that a socket close is the server's answer to msg 2002.
        # [TODO] Find the real answer. Leads: SADK's own vtbl[0x1c] call sites in StatePump_Tick
        # (0x465092/0x4650d0/0x4650e1) and next to CLobbyClient::LeaveVillage (0x5036ec).
        conn._leave_requests = getattr(conn, "_leave_requests", 0) + 1
        log(f"  [VILLAGE] LEAVE-VILLAGE REQUEST #{conn._leave_requests} — msg 2002 "
            f"(0x{msg_type:x}, code=0x{data[:4].hex()}) — no-op. Client parks in LeavingVillage(10). "
            f"Closing the conn was LIVE-FALSIFIED (kicks both players at match start); the genuine "
            f"answer is still unknown — see engagement_records/2026-07-26_village-leave-close-connection.md")
    elif msg_type == config.VILLAGE_PINGCODE_MSGTYPE:         # 0x2ED6 — in-world keepalive PingCode
        village.send_pong(conn, token=data)                 # echo the ping token, close the RTT round-trip…
        first_ack = not getattr(conn, "_world_login_ack_sent", False)
        village.send_world_login_ack(conn)                  # …and (once) the best-effort 1006 WorldLoginAck
        if first_ack:
            log("  [VILLAGE] 1006 WorldLoginAck sent on first PingCode "
                "([TODO] its in-world effect is unverified on the clean build)")
    else:
        log(f"  (SendGameData[74] msg_type=0x{msg_type:x} on conn #{conn.id} — logged, no in-world handler)")


# ── Chat over lobby magic ─────────────────────────────────────────────────────
@handler(17)  # RequestJoinChannel
def _h_join_channel(conn, fields, ticket):
    chat.handle_join_channel(conn, fields, ticket)


@handler(2)  # ChatMessage
def _h_chat_message(conn, fields, ticket):
    txt = fields.get("txt", "") or ""
    log(f"  CHAT: {txt!r}")
    conn.send_app(165, codec.encode_body(165, {"txt": f"[Server] {txt}", "from_id": 0}))


# ── Quiet routing: keep routine 'default-implementation' chatter out of the main log ──────────────
# These handlers do nothing protocol-significant for the work under study — bare acks + boilerplate
# account/social login replies. connection.py routes their full per-message decode to
# tincat_lobby_unhandled.log (file only) so the main view stays focused on auth, server-list,
# AssignServer, village/world and chat. Genuinely UNKNOWN types (no handler) STAY in the main log.
QUIET_HANDLERS = frozenset({
    _h_ack, _h_char_ack, _h_ignore_list, _h_user_info, _h_player_info,
    _h_select_nickname, _h_cdkeys, _h_property_get, _h_motd,
})


def is_quiet(type_num):
    """True if this lobby message is routine/boilerplate → route its log to tincat_lobby_unhandled.log
    instead of the main view. False for unknown types (no handler), so new protocol stays visible."""
    return HANDLERS.get(type_num) in QUIET_HANDLERS
