"""
Lobby application-message dispatch.

Every inbound message is decoded generically by the codec (canonical msgdefs
field names), then routed here. Types we care about have explicit handlers;
everything else falls through to a default Result-OK ack so no message type is
left unhandled.

Handler signature:  fn(conn, fields: dict, ticket: int)
"""
import os
import struct
import threading
import time

from . import chat, codec, config, crypto, msgdefs, players, referee, registry, village
from .log import log

HANDLERS = {}

# Observer subscriptions for server-list push notifications (s39.5).
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
        # Village/world property-bag message (e.g. 0xED6 SendWorldReadyAck, 1001-1006) that arrives
        # AFTER a successful EnterWorld. We don't model the in-world protocol yet — just LOG it; do NOT
        # send a lobby Result(42) ack (wrong layer/semantics; acking could destabilize the world session).
        # This is the capture we need to build the next (in-world) stage. (s30)
        log(f"  [VILLAGE-MSG] type {type_num} (0x{type_num:x}) received post-entry — logged, NOT acked")
    else:
        log(f"  (default-ack: {msgdefs.name_of(type_num)} [{type_num}])")
        conn.ok(ticket)


# ── Identity + game-store helpers (multi-client, s39.5) ───────────────────────
# These keep single-user / per-connection behaviour byte-identical when
# config.MULTI_CLIENT_HOSTING is OFF, and switch to per-player identity + the
# process-global game registry when it is ON.

def _player(conn):
    """The player identity this connection serves (default = test account)."""
    return players.of(conn)


def _register_game(conn, info):
    """Store a hosted game (168); returns the assigned server_id."""
    if config.MULTI_CLIENT_HOSTING:
        return registry.games.add(conn.id, info)
    sid = conn.alloc_server_id()
    rec = dict(info); rec["id"] = sid
    conn.servers[sid] = rec
    return sid


def _remove_game(conn, sid):
    """Remove a hosted game (169) owned by this connection."""
    if config.MULTI_CLIENT_HOSTING:
        return registry.games.remove(conn.id, sid)
    return conn.servers.pop(sid, None) is not None


def _change_owned_game(conn, changes):
    """Apply field changes (177) to the game this connection hosts; returns the record."""
    if config.MULTI_CLIENT_HOSTING:
        return registry.games.update_owned(conn.id, changes)
    sid = next(iter(conn.servers), None)
    if sid is None:
        return None
    conn.servers[sid].update(changes)
    return conn.servers[sid]


def _get_game(conn, sid):
    """Look up a game by id (221) — cross-client when multi-hosting is on."""
    if config.MULTI_CLIENT_HOSTING:
        return registry.games.get(sid)
    return conn.servers.get(sid)


def _games_for_list(conn, server_type):
    """Games to advertise for a server-list request (server_type 0 == any)."""
    if config.MULTI_CLIENT_HOSTING:
        return registry.games.list_by_type(server_type)
    return [s for s in conn.servers.values()
            if server_type == 0 or s.get("server_type") == server_type]


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
    # Multi-client: bind this lobby connection to the account it logged in as, so the
    # SessionKey(207) perm_id and the char/user replies below serve that player. The
    # perm_id then propagates to this client's UC + village conns via the token (213).
    if config.MULTI_CLIENT_HOSTING:
        conn.player = players.resolve_by_username(creds.get("username"))
        log(f"  [PLAYER] lobby #{conn.id} → {conn.player.username!r} (perm_id={conn.player.perm_id})")
    session = None
    if crypto.TWOFISH_AVAILABLE and conn.shared:
        # KEEP the 32B session key (was discarded via os.urandom inline) — the token 213/214 crypto
        # almost certainly uses it as the key, and the stub must know it to build a valid 214 (s31).
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
    if config.MULTI_CLIENT_HOSTING:
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
def _send_uc_server_192(conn, server_type, ticket):
    """UsercommServerData(192): point the client at the stub's UC/chat server (:7071).

    The 192 is consumed by tincat3's generic CommLayer 0xc0 handler (FUN_10030420 @0x10030420):
    it dials the advertised ip:port and stands up the UserComm-SERVER connection — which is the
    connection our :7071 (is_chat) listener serves chat over. The handler does NOT validate the
    ticket against an outstanding request (no category check), so a ticket_id of 0 (unsolicited
    advertisement) is accepted just the same as a reply ticket.
    """
    conn.send_app(192, codec.encode_body(192, {
        "server_id": 1, "ip": config.ADVERTISED_IP, "port": config.UC_PORT,
        "server_type": server_type,
        "version": None, "data": None, "ticket_id": ticket}))
    log(f"  → UsercommServerData(192) -> {config.ADVERTISED_IP}:{config.UC_PORT} "
        f"(type={server_type}, ticket={ticket})")


@handler(189)  # AssignServer
def _h_assign_server(conn, fields, ticket):
    server_type = fields.get("server_type", 0)
    server_subtype = fields.get("server_subtype")

    # ── CORRECTED REFEREE MODEL (re-RE'd s39.6, binary build 34688 + 2 live captures) ──────────────
    # The PRIOR model ("UC = 1st type-4 189, referee = a 2nd type-4 189") is REFUTED:
    #   * SADK has EXACTLY ONE type-4 AssignServer caller — the LobbyManager state-pump one-shot at
    #     0x468f60→0x468f60 vtbl[0x2c](4,4), which registers the REFEREE-address callback FUN_004625d0
    #     (writes LM+0x580) and is LATCHED (LM+0x5ac), so it fires at most ONCE per session. The two
    #     live runs show EXACTLY ONE 189 per client (type=4, sub=4) — there is NO 2nd 189, ever.
    #   * So the single login 189 IS the referee assign. tincat3 routes its reply by the ticket's
    #     category 0x108: case 0xaa(170)+cat 0x108 → FUN_10021520, which fires the referee callback
    #     IFF the reply carries server_type==4 && server_subtype==5. A 192 reply instead goes to the
    #     generic UC-server handler (no cat check) → the client dialed :7071 (chat worked "by accident")
    #     but LM+0x580 stayed 0 → RefereeServerConnection::Login no-op'd → match aborted after 5 retries.
    # FIX: answer the (only) type-4 189 with GameServerData(170, type=4, subtype=5, SAME ticket_id,
    # id=REF_SERVER_ID) so the cat-0x108 path sets LM+0x580 = REF id, which resolves to :5481 from the
    # type-4 list we already advertise (FAKE_REFEREE). The id MUST be the FAKE_REFEREE id and the entry
    # MUST have been advertised on the type-4 list first (it is — see _send_server_list) so pComm can
    # resolve it. ⛔ Gated by ADVERTISE_REFEREE_SERVER; OFF → every assign falls through to 192 (today's
    # byte-identical behavior).
    if config.ADVERTISE_REFEREE_SERVER and server_type == 4:
        conn.send_app(170, codec.encode_body(170, server_to_170_values(dict(FAKE_REFEREE), ticket)))
        log(f"  → [REFEREE] AssignServer(type=4, sub={server_subtype}, ticket={ticket}) → "
            f"GameServerData(170, type=4, subtype=5, id={config.REF_SERVER_ID}) -> "
            f"{config.ADVERTISED_IP}:{config.REFEREE_PORT}  [sets LM+0x580 via tincat3 FUN_10021520]")
        # Switching the 189's reply from 192→170 means the client no longer learns the UC-server
        # address FROM THIS MESSAGE, which is how chat currently reaches :7071. To keep chat working,
        # also (unsolicited) push the 192 so the client still dials the UC server. ticket_id=0 because
        # this is an advertisement, not a reply to an outstanding request (the 170 already consumed the
        # cat-0x108 ticket). If a live capture shows chat survives on the lobby transport WITHOUT this,
        # set REFEREE_ALSO_PUSH_UC=False — the 192 push is the conservative chat-preservation default.
        if config.REFEREE_ALSO_PUSH_UC:
            _send_uc_server_192(conn, server_type, 0)
        return

    # Non-referee assign (or referee disabled): reply UsercommServerData(192) as before.
    _send_uc_server_192(conn, server_type, ticket)


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
    """Build the village 'ServerDataBlock' that makes a list entry JOINABLE.

    FillFromDescriptor @0x481640 sets entry.roomId(+0x30) from the FIRST field of this block (the 170
    `data` MEMBLOCK), read BIG-ENDIAN, then a 1-byte pending flag. Without the block the client logs
    "Invalid Server Data Block" and FORCES entry.validity(+0x35)=0 → the Enter button greys out.
    s15 live-confirmed layout: 4-byte BIG-ENDIAN roomId + 1 pending byte (=0). The roomId MUST equal
    the client's match key DAT_0087aed8 (= LobbyClient/ProtocolVersion); see config.LOBBY_PROTOCOL_VERSION.
    server_data_block(1000) == b"\\x00\\x00\\x03\\xe8\\x00" (byte-identical to the long-standing literal).
    """
    return struct.pack(">I", int(room_id)) + b"\x00"


# The ServerType=4 village world that currently gets us INTO the list (s12/s13).
# s28: id MUST NOT be 1 — AssignServer/UsercommServerData(192) advertises the UC server as
# server_id=1, so a village with id=1 makes the client's CommLayer_ResolveServer find the
# already-connected UC connection (vtbl[+0x5c](1)!=0 → 0xcd) and reuse it instead of dialing
# 5479. CreateVillageServerConnection then skips (conn+0x34 already set). Unique id → real dial.
FAKE_VILLAGE = {
    "id": 50, "owner_id": config.TEST_PERM_ID,
    "name": "world1", "description": "SaDK Revival Lobby World",
    "ip": config.ADVERTISED_IP, "port": config.WORLD_PORT,
    "max_players": 20, "cur_players": 1, "ai_players": 0,
    "lobby_id": 1000, "version": "", "server_type": 4, "server_subtype": 2,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "world1", "running": True,
    # s15 LIVE-CONFIRMED: the village entry's roomId/validity come from the 170's `data` MEMBLOCK,
    # NOT the room_id field. Client update @0x130a080 -> commit branch @0x130a1b4 parses `data` to
    # set entry.roomId(+0x30) + entry.pending(+0x34); validity(+0x35)=(listAction!=0)=1. Live trace:
    # ECX=0xE8030000 from data E8 03 00 00 => roomId is read BIG-ENDIAN. Format (gate [0x12f283c]=5):
    # 5 bytes = roomId as BIG-ENDIAN u32 + 1 pending byte. roomId=1000=0x3E8 BE, pending=0.
    # Derived from config.LOBBY_PROTOCOL_VERSION (default 1000 → b"\x00\x00\x03\xe8\x00", unchanged).
    # The roomId must equal the client's ProtocolVersion (DAT_0087aed8) or Enter stays grey — see config.
    "data": server_data_block(config.LOBBY_PROTOCOL_VERSION),
}
# The referee/match-arbiter server (s39.5). server_type=4 + server_subtype=5 is the EXACT pair tincat3
# FUN_10021520 gates the referee-assigned path on. Advertised on the type-4 server-list so the client caches
# REF_SERVER_ID → ip:port (pComm FUN_100196b0 resolves the id when AssignServer hands it back). No
# ServerDataBlock needed (that gate is village-Enter-button only; the referee is resolved by id, not joined).
FAKE_REFEREE = {
    "id": config.REF_SERVER_ID, "owner_id": config.TEST_PERM_ID,
    "name": "referee", "description": "SaDK Revival Referee",
    "ip": config.ADVERTISED_IP, "port": config.REFEREE_PORT,
    "max_players": 0, "cur_players": 0, "ai_players": 0,
    "lobby_id": 0, "version": "", "server_type": 4, "server_subtype": 5,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "", "running": True, "data": None,
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
    # NO fake GAME entry. The game browser (server_type 5) shows ONLY real hosted games — registered
    # via AddGameServer(168) and relayed cross-client from the registry in the loop above. The client
    # sets server_subtype=1 itself when it hosts a browsable game (live-confirmed: 'Siedlerwill spielen'
    # arrived with subtype=1), so a hosted game routes to BrowseGameDialog on its own with its REAL
    # player count. An empty game list when nobody is hosting is the correct, honest state.
    # Advertise the referee on the type-4 (and type-0/any) list so the client CACHES REF_SERVER_ID→ip:port
    # BEFORE the AssignServer round-trip hands it that id (pComm FUN_100196b0 resolves the id from this cache;
    # without it FUN_00462910 logs "Could not initialize RefereeServerConnection."). Gated by the ER flag.
    if config.ADVERTISE_REFEREE_SERVER and server_type in (0, 4):
        conn.send_app(170, codec.encode_body(170, server_to_170_values(dict(FAKE_REFEREE), ticket)))
        sent += 1
        log(f"  → [REFEREE] advertised referee (type=4, subtype=5, id={config.REF_SERVER_ID}) → resolves "
            f"{config.ADVERTISED_IP}:{config.REFEREE_PORT}")
    conn.ok(ticket)
    log(f"  → ServerList(type={server_type}): sent {sent} server(s) + OK")


@handler(171)  # RegObserverServerList
def _h_reg_observer_servers(conn, fields, ticket):
    server_type = fields.get("server_type", 0)
    room = fields.get("room_id")
    log(f"  RegObserverServerList type={server_type} room_id={room} send_all={fields.get('send_all')}")
    _reg_obs(conn, server_type)   # register for future push notifications (s39.5)
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
        f"owner={info['owner_id']} subtype={info['server_subtype']} "
        f"{'[registry]' if config.MULTI_CLIENT_HOSTING else '[per-conn]'}")
    conn.status_with_id(0, sid, ticket)
    # Push 170 to all subscribed observers so their browser updates without a re-request (s39.5).
    if config.MULTI_CLIENT_HOSTING:
        _push_to_obs(info["server_type"], {**info, "id": sid})


@handler(169)  # RemoveServer
def _h_remove_server(conn, fields, ticket):
    _remove_game(conn, fields.get("server_id", 0))
    conn.ok(ticket)


@handler(177)  # ChangeGameServer
def _h_change_server(conn, fields, ticket):
    # Only overwrite fields the message actually carried a value for (a 177 may touch
    # a subset; the stub ignores property_mask). Mirrors the prior per-conn semantics.
    changes = {k: fields.get(k) for k in
               ("name", "description", "max_players", "map", "running", "data")
               if fields.get(k) is not None}
    rec = _change_owned_game(conn, changes)
    if rec is not None:
        log(f"  ChangeGameServer: id={rec.get('id')} running={rec.get('running')} map={rec.get('map')!r}")
        # Keep observers' browser current as host changes map/settings (s39.5).
        if config.MULTI_CLIENT_HOSTING:
            _push_to_obs(rec.get("server_type", 5), rec)
    conn.ok(ticket)


@handler(221)  # RequestConnectionData -> ConnectionData
def _h_connection_data(conn, fields, ticket):
    sid = fields.get("server_id", 0)
    srv = _get_game(conn, sid)
    # GAME_CONN_VIA_STUB redirects to the stub's capture port ONLY for a join to a REAL
    # hosted game (one actually in the registry → srv is not None). The lobby-WORLD entry
    # request (server_id=50, the injected FAKE_VILLAGE, which is never registered → srv is
    # None) MUST keep going to WORLD_PORT (:5479) — else the client dials the game port for
    # the lobby world and never enters it. (s39.5 live bug: this redirected every 221.)
    if config.MULTI_CLIENT_HOSTING and config.GAME_CONN_VIA_STUB and srv is not None:
        ip, port = config.ADVERTISED_IP, config.GAME_PORT
    else:
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


@handler(213)  # SendToken -> AckResult(153)  [the 0x99 ACK the client awaits; NOT a 214 — see below]
def _h_send_token(conn, fields, ticket):
    # ★★★ s31 LIVE-RE VERDICT (slot-lifecycle agent) — THE FIX. The game's UC-login client state machine
    # (tincat3 ClientRecvHandler @0x10023460) has NO case for 214 (0xd6): its jump-table bound is 0xAA,
    # so a 214 (index 0xAC) is DROPPED as "Invalid message-type". After sending 213 SendToken the client
    # waits for the **0x99 ACK = NETMSG 153 (AddResult)** with errorcode==0 → connection state→8
    # (AUTHORIZED) → fires the LoggedIn callback (the thing that's been missing). So we ACK with 153,
    # NOT a 214. This corrects the s22 213→214 regression. (The 214/Twofish-CTR path — crypto.build_token_*
    # — is consumed ONLY on the separate secured ROOM-server connection, kept for that case.)
    perm_id = fields.get("perm_id", config.TEST_PERM_ID)
    # Multi-client: the UC + village connections carry the perm_id the lobby issued in
    # 207, so bind this connection to that player (its chat user-info / world identity).
    if config.MULTI_CLIENT_HOSTING and fields.get("perm_id"):
        conn.player = players.resolve_by_perm(fields["perm_id"])
        perm_id = conn.player.perm_id
        log(f"  [PLAYER] token #{conn.id} → {conn.player.username!r} (perm_id={perm_id})")
    conn.status_with_id(0, perm_id, ticket)   # NETMSG 153 AddResult, errorcode=0 → the 0x99 ACK
    log("  → SendToken → AckResult(153) errorcode=0 [the 0x99 ACK → state 8 AUTHORIZED → LoggedIn]")
    # s31 (trace agent): NOW (post-login) push the chat ChannelInfo — deferred from the handshake so
    # it lands in a fully-constructed channel container instead of corrupting a half-built one. The 153
    # above fires the client's LoggedIn observer fan-out (NotifyObservers @0x48d7e0); a UC observer
    # null-derefs if the container was poisoned by a pre-login push. (Candidate-B fix; if the crash
    # persists it's a never-constructed m_ChatChannelManager — confirm via live BP @ SADK 0x48d845.)
    if getattr(conn, "is_chat", False):
        chat.send_initial_reply(conn)
    # WORLD ENTRY — s39 LIVE-CONFIRMED (probes/ + tincat_server.log). On the VILLAGE conn (:5479), after this
    # 153 ACK the client parks at LobbyManager EnteringVillage(8) and WAITS for the server to push EnterWorld
    # (msg 1000). Its own world-login request (SendGameData(74){0x27D2}, Village_SendEnterWorld_2002 @0x46b990)
    # never fires — that path is dormant — so waiting for it deadlocks (the long-standing hang). The genuine,
    # harness-endorsed fix for this wait-state is to PROVIDE msg 1000 via the real mechanism: the server pushes
    # it. village.send_enter_world wraps it in the SendGameData(74) envelope → HandleMessage → HandleEnterWorld
    # @0x46f670 → SetState(VillageEntered=9). (NOT on the lobby/UC conn — those lack the 1000-series templates
    # and would NULL-deref; only the village conn.) GATED OFF by config.ARM_ENTER_WORLD (wire change → needs an
    # approved Engagement Record + user present to observe; see engagement_records/2026-06-07_push-enterworld.md).
    if getattr(conn, "is_village", False):
        if config.ARM_ENTER_WORLD:
            def _push_enter_world(c=conn):
                time.sleep(config.ENTER_WORLD_DELAY)
                village.send_enter_world(c)             # idempotent (_enter_world_sent latch)
            threading.Thread(target=_push_enter_world, daemon=True).start()
            log(f"  [ENTER] (VILLAGE) ARMED — pushing EnterWorld(1000) in {config.ENTER_WORLD_DELAY}s "
                "→ HandleEnterWorld → SetState(VillageEntered=9). Re-run probe_lobby_world_entry.py to confirm "
                "state 9 + whether the world renders.")
        else:
            log("  [ENTER] (VILLAGE) 153 ACK — client now parks at EnteringVillage(8) awaiting msg 1000; "
                "push DISARMED (config.ARM_ENTER_WORLD=False, needs Engagement Record).")
    elif getattr(conn, "is_referee", False):
        # The referee conn has completed its base login (153 AUTHORIZED); the client now opens the referee
        # data channel (RefereeServerConnection::Login) and WAITS for the server to push LoginSuccess(0xDCA).
        # PUSH it (after a short settle so the channel-open lands first) — the genuine message the match-start
        # gate awaits. GATED by config.ARM_REFEREE (wire change → Engagement Record; flip only after a live
        # capture confirms the LoginSuccess framing — see referee.py / config.REF_LOGIN_SUCCESS_NAMES).
        if config.ARM_REFEREE:
            def _push_ref(c=conn):
                time.sleep(config.ENTER_WORLD_DELAY)
                referee.push_login_success(c)           # idempotent (_ref_login_pushed latch)
            threading.Thread(target=_push_ref, daemon=True).start()
            log(f"  [REFEREE] ARMED — pushing LoginSuccess(0xDCA) in {config.ENTER_WORLD_DELAY}s after the 153 "
                "→ clears the 5x-retry match-start abort. Probe LM+0x362c (attempts) to confirm it never hits 5.")
        else:
            log("  [REFEREE] 153 login done — LoginSuccess push DISARMED (config.ARM_REFEREE=False, needs "
                "Engagement Record). Capturing the referee channel framing (Part A) only.")
    else:
        log("  [ENTER] (lobby/UC) 153 ACK — no world push on this conn.")


# ── Village / world game-data envelope (SendGameData 74) ───────────────────────
@handler(74)  # SendGameData — the NETMSG envelope that carries every village/world message (1000+)
def _h_send_game_data(conn, fields, ticket):
    """Village/world envelope handler. The genuine world-entry mechanism is the SERVER pushing EnterWorld
    (msg 1000) once the transport is AUTHORIZED (see _h_send_token / village.send_enter_world); the client's
    own SendGameData(74){0x27D2} world-login request is dormant/dead, so we don't depend on it. msg 1000 must
    ride a SendGameData(74) envelope — the only framing the inbound bridge routes to HandleMessage →
    HandleEnterWorld → SetState(VillageEntered=9). This handler also answers in-world PingCodes."""
    msg_type = fields.get("msg_type", 0)
    data = fields.get("data", b"") or b""
    if not getattr(conn, "is_village", False):
        log(f"  (SendGameData[74] msg_type=0x{msg_type:x} on non-village conn #{conn.id} — logged)")
        return
    if msg_type == config.WORLD_LOGIN_REQUEST_MSGTYPE:        # 0x27D2 — the world-login request
        log(f"  [VILLAGE] *** WORLD-LOGIN REQUEST — SendGameData(74){{msg_type=0x{msg_type:x}, "
            f"code=0x{data[:4][::-1].hex()}}} → EnterWorld(1000) ***")
        village.send_enter_world(conn)
    elif msg_type == config.VILLAGE_PINGCODE_MSGTYPE:         # 0x2ED6 — in-world keepalive PingCode
        village.send_pong(conn, token=data)                 # echo the ping token, close the RTT round-trip…
        first_ack = not getattr(conn, "_world_login_ack_sent", False)
        village.send_world_login_ack(conn)                  # …and (once) THE loading-screen gate (1006, 0xDEADBEEF)
        if first_ack:
            log("  [VILLAGE] *** 1006 WorldLoginAck sent on first PingCode — watch for loading-screen dismiss "
                "(or an observer-AV crash, which still means the gate FIRED) ***")
        # OPTIONAL world clock (msg 1005) — held OFF for the first isolated 1006-gate drive so a render-gate
        # failure isn't conflated with a missing sim clock. Enable once 1006 is confirmed to dismiss loading:
        # village.send_world_tick(conn)
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
# tincat_lobby_unhandled.log (FILE ONLY — not console, not the main log) so the main view stays focused
# on auth, server-list, AssignServer, village/world, referee and chat. Genuinely UNKNOWN types (no
# handler) STAY in the main log so new protocol is still discoverable. Add a handler here to silence its
# message types; remove one to bring them back.
QUIET_HANDLERS = frozenset({
    _h_ack, _h_char_ack, _h_ignore_list, _h_user_info, _h_player_info,
    _h_select_nickname, _h_cdkeys, _h_property_get, _h_motd,
})


def is_quiet(type_num):
    """True if this lobby message is routine/boilerplate → route its log to tincat_lobby_unhandled.log
    instead of the main view. False for unknown types (no handler), so new protocol stays visible."""
    return HANDLERS.get(type_num) in QUIET_HANDLERS
