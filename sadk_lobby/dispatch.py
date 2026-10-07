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
import math
import os
import struct
import json
import threading
import time

from . import (buddies, chat, codec, config, crypto, economy, mail, minigames, msgdefs, npcs,
               players, referee, registry, store, village)
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


# ── Live-connection registry ──────────────────────────────────────────────────
# A client owns several sockets (lobby / UC-chat / village / referee). The village LEAVE is a
# two-phase teardown that needs the UC and village conns paired, so we keep a live list and match
# on the player's perm_id (players.of() resolves lobby by username, UC/village by token perm_id).
_live_lock = threading.Lock()
_live: list = []


def register_conn(conn):
    with _live_lock:
        if conn not in _live:
            _live.append(conn)


def _find_live(pred):
    with _live_lock:
        return [c for c in _live if getattr(c, "alive", False) and pred(c)]


def on_conn_closed(conn):
    """Called from connection.py once a socket is fully down.

    Drives **phase 2** of the village leave. `HandleWorldLoginAck@0x0046ec50` branches on whether the
    UserComm connection is open:
        UC OPEN   → UserCommConnection::Logout   (phase 1 — logs UC out; the player name goes "default")
        UC CLOSED → ConnectionReal::Logout on the VILLAGE transport → state 9 → on disconnect
                    FUN_10030ad0 case 4 takes the state-9 branch → OnLoggedOut → HandleLoggedOut →
                    SetState(VillageLeft=11) → the +0x1c observer → arms the referee.
    The client sends msg 2002 exactly ONCE (live-verified 2026-07-26 by trace), so it will never
    prompt us for the second 1006 — we must send it ourselves, and the right trigger is the UC socket
    actually going away. That is what this hook is for.
    """
    with _live_lock:
        try:
            _live.remove(conn)
        except ValueError:
            pass
    _gchat_drop(conn)                             # global-chat subscribers must not leak
    if getattr(conn, "role", "") == "lobby":
        gone = _player(conn).perm_id
        if _lobby_conn_of(gone) is None:          # no newer lobby socket for this player
            buddies.push_presence(gone, False, _lobby_conn_of)
    # A village conn going away means that player's avatar must be despawned for everyone still
    # in-world, or they are left staring at a ghost that never moves.
    if getattr(conn, "is_village", False) and getattr(conn, "_enter_world_sent", False):
        gone = _player(conn)
        minigames.leave_all(_minigame_io(), gone.perm_id)     # credits go back to gold
        for other in _in_world_conns(exclude_player=gone.perm_id, exclude_conn=conn):
            village.send_entity_remove(other, gone.perm_id,
                                       label=f"[{gone.char_name!r} left the world]")
    if not getattr(conn, "is_chat", False):
        return                                    # only a UC/chat close can complete a leave
    chat.on_conn_closed(conn)                     # drop from channel rosters + notify members
    me = players.of(conn)
    waiting = _find_live(lambda c: getattr(c, "is_village", False)
                         and getattr(c, "_leave_phase", 0) == 1
                         and players.of(c).perm_id == me.perm_id)
    for v in waiting:
        v._leave_phase = 2
        log(f"  [VILLAGE] leave phase 2 — UC conn #{conn.id} is gone, so HandleWorldLoginAck will now "
            f"take the VILLAGE branch: re-sending WorldLoginAck(1006) on conn #{v.id} "
            f"→ ConnectionReal::Logout → transport state 9 → OnLoggedOut → SetState(VillageLeft=11)")
        village.send_world_login_ack(v, force=True)


# The village spawn square, [PROVEN] 2026-08-01 by TTD trace `avatar_spawn_diag.run`: the client's
# OWN avatar visual is constructed at (-31.24, 2.71, +8.28) (x/y equal the binary's default-spawn
# constants DAT_007dd028/2c exactly; z is the observed value — the static default DAT_007dd06c is
# -8.28, sign-flipped somewhere on the own path, but the REMOTE path is proven pass-through: we sent
# (0,0,6) on the wire and the visual ctor received (0,0,6) verbatim). Ring-spawning around world
# origin put remote avatars ~31 units away from the square and ~2.7 below its ground level — fully
# spawned, modelled and styled, just standing where nobody looks. NOT in config.py on purpose: the
# deploy server's config.py is local-only and must never be overwritten (see HANDOFF.md).
VILLAGE_SPAWN_POINT = (-31.24, 2.71, 8.28)

#: The ambient NPC cast, placed around the square above: record NPCs via PlayerCreate(1004)
#: and walkers via EntityCreate(1001) (see npcs.py). Spawned to every entrant in
#: _spawn_world_avatars; the walkers are kept alive and moving by the 1 Hz location ticker.
#:
#: ⚠️ Gated on `config.VILLAGE_NPCS_ENABLED`, currently OFF by explicit user instruction
#: (2026-08-02 — see the flag's comment in config.py; HARNESS §5 permits a maintainer-requested
#: flag). An empty list makes every downstream site — record_npcs/walker_npcs/advance_all and
#: both refresh loops — a natural no-op, so no other code needs a condition.
_npcs = npcs.make_village_npcs(VILLAGE_SPAWN_POINT) if config.VILLAGE_NPCS_ENABLED else []


def _spawn_spot(perm_id):
    """A deterministic ring spot around the village spawn square — the PLACEHOLDER position, used
    only until the client's first real location report arrives (see `_live_pose`).

    Keying it on perm_id keeps it stable and identical for every observer. Centered on
    VILLAGE_SPAWN_POINT — the spot the client's own avatar provably spawns at — so a just-spawned
    remote player appears beside the observer rather than at the distant world origin.

    ⚠️ Placeholder positions are necessarily INCONSISTENT between machines: each client places its
    own avatar itself (client-side default spawn) while we place the remote one on this ring, so
    the two machines disagree about the pair's relative geometry. Real reported positions
    (`_live_pose`) fix that — they are one shared truth, relayed to everyone."""
    # Golden-angle placement so ANY number of players spreads out instead of colliding every
    # 8th id (the old `perm_id % 8` ring): each successive id lands ~137.5° round, and the
    # radius grows a little each full turn.
    ang = perm_id * 2.39996322972865332
    r = config.AVATAR_SPAWN_SPREAD * (1.0 + (perm_id // 8) * 0.3)
    cx, cy, cz = VILLAGE_SPAWN_POINT
    return (cx + math.cos(ang) * r, cy, cz + math.sin(ang) * r)


#: perm_id → the player's last reported pose, from their own msg 2000 (village.parse_avatar_location).
#: This is the world's single source of truth for where each avatar is; the refresh/relay path feeds
#: it straight back out as 1001 waypoints, so every client sees everyone where they actually stand.
_poses = {}
_poses_lock = threading.Lock()


def _in_world_conns(exclude_player=None, exclude_conn=None):
    """Live village connections that have entered the world — **ONE per player**.

    Same stale-socket hazard as the chat roster (see `chat._live_one_per_player`, and the Win7
    "double send" bug it caused): a relog opens a fresh village connection while the previous one
    is still live, so iterating sockets would send every spawn, waypoint and clock sync twice to
    that client — and count the same player twice as an occupant of the world. Newest wins."""
    by_player = {}
    for c in _find_live(lambda c: getattr(c, "is_village", False)
                        and getattr(c, "_enter_world_sent", False)):
        if c is exclude_conn:
            continue
        pid = _player(c).perm_id
        if exclude_player is not None and pid == exclude_player:
            continue
        by_player[pid] = c
    return list(by_player.values())


def _live_pose(perm_id):
    """The kwargs describing where a player is, ready to splat into `village.send_entity_create`:
    their last REPORTED pose, or the placeholder ring spot if they have not reported yet (the ~1 s
    window between world entry and their first msg 2000).

    ⭐ `zone`/`ghost_zone` are relayed VERBATIM. They are the sub-zone the player is standing in —
    the minigame rooms and the hall of fame are separate zones — and hardcoding 0 told everyone
    else that a player who had walked into a side room was still out on the square. The client is
    the authority on its own zone; the server's job is to pass it on. (`FUN_0045fd30`, the minimap
    renderer, gates on own `zone == 0 && ghstzne == 0x0F`, which also shows **15**, not 0, is the
    neutral outdoor ghost-zone value — so 0/0 was never a harmless placeholder.)"""
    with _poses_lock:
        loc = _poses.get(perm_id)
    if loc is None:
        return {"pos": _spawn_spot(perm_id), "rot_deg": 0.0}
    return {"pos": loc["pos"], "rot_deg": loc["rot_deg"],
            "running": loc["running"], "jumping": loc["jumping"],
            "zone": loc["zone"], "ghost_zone": loc["ghost_zone"]}


def _avatar_style(player):
    """AvatarStyle block (dtblcks bit1) for a player — the appearance the client draws.

    Layout VERIFIED against `AvatarProxy_ReadStyleBlock@0x004825f0` (2026-07-31): a `name` STRING via
    reader vtbl+0x34, then NINE 8-bit values landing in consecutive bytes AvatarProxy+0x48..+0x50 —
    `trbgndr`, `hrclr`, `sknclr`, `shrtclr`, `trsrclr`, `addColor1..4`. Each has its own error string
    in LobbyAvatarProxy.cpp, so a wrong field names ITSELF in the client's LobbyComm.log
    ("Could not read skin color from stream." etc.) rather than failing silently.

    Values are conservative defaults: colour 0 on every slot, tribe/gender 0. `trbgndr` packs tribe
    and gender into one byte and the packing is **[TODO]** — 0 is the safest first guess. The name is
    the real character name, so a rendered avatar should also be labelled correctly.
    """
    return {"name": player.char_name, "tribe_gender": 0,
            "colours": tuple(economy.wallet(player.perm_id).colours)}   # tailor changes (3950)


# Avatar movement-ring refresh — WHY THIS EXISTS (proven 2026-08-01, TTD avatar_vanish_diag.run):
# the client positions every remote avatar from a ring buffer of timestamped WAYPOINTS that only
# location UPDATES feed (`FUN_00519b20`, reached via `CLobbyClient_UpdateAvatar`'s update path on a
# repeat 1001). The spawn frame paints exactly one frame; from the next frame the interpolator
# (`FUN_00519d50`) snaps an empty-ringed avatar to (0,0,0). So the server must STREAM location
# refreshes — this is the real protocol, not a workaround. 1 Hz is ample: each waypoint says
# "be here at tick+2000 ms" and the avatar holds position past the last waypoint.
AVATAR_REFRESH_SECS = 1.0
_avatar_ticker_lock = threading.Lock()
_avatar_ticker_started = False


def _now_ms():
    """THE wire timebase: an advancing millisecond clock. Every tick we send — the WorldTick(1005)
    clock sync AND the EntityCreate location tick16s — must come from THIS one clock, because the
    client slews its world clock to the 1005 ticks and then reconstructs every location tick16
    against that slewed clock (`FUN_004f4d10`, nearest-anchor mod 65536)."""
    return int(time.monotonic() * 1000)


def _now_tick16():
    """Low 16 bits of `_now_ms()` — the wire `tick` field of avatar location blocks.

    ⚠️ CORRECTED MODEL 2026-08-01: the client does NOT tolerate an arbitrary absolute phase. The
    nearest-anchor reconstruction is anchored on the client WORLD CLOCK, which the real server
    kept slewed to ITS tick stream via WorldTick(1005). Without 1005 the phase error is arbitrary
    (up to ±32.7 s, per machine/boot) — that was the round-2/3 avatar die-off. With 1005 flowing
    from the same clock, reconstruction is phase-true."""
    return _now_ms() & 0xFFFF


def _avatar_location_ticker():
    cycles = 0
    while True:
        time.sleep(AVATAR_REFRESH_SECS)
        cycles += 1
        # Geometry experiment 2026-08-01 (round 3): send now-1000 so the client-side waypoint stamp
        # (reconstruct(tick)+2000) lands ≈now+1000 — each 1 Hz push then brackets "now" between the
        # push from 1-2 s ago and the fresh one, and the newest stamp is never behind the clock.
        # With plain "now" the stamps sit +2000 ahead and live behaviour showed the avatar hidden
        # (stale/no-bracket path latching render-node bit 0x20).
        tick = (_now_tick16() - 1000) & 0xFFFF
        in_world = _in_world_conns()
        sent = 0
        for conn in in_world:
            # World-clock sync FIRST, every cycle (see village.send_world_tick): keeps each
            # client's world clock slewed to the same clock the location tick16s below are cut
            # from. After the first slew the client's 250 ms tolerance makes this a no-op.
            try:
                village.send_world_tick(conn, _now_ms(), quiet=True)
            except Exception as exc:  # noqa: BLE001 — a dying socket must not kill the ticker
                log(f"  [WORLD] WorldTick(1005) to conn #{conn.id} failed: {exc}")
        # NPC walkers take one step per cycle; the step size (speed × 1 s) stays far
        # under the interpolator's 10-unit snap threshold, so the client walks the
        # model smoothly between waypoints.
        npcs.advance_all(_npcs, AVATAR_REFRESH_SECS)
        for conn in in_world:
            me = _player(conn)
            for other in in_world:
                op = _player(other)
                if other is conn or op.perm_id == me.perm_id:
                    continue
                try:
                    village.send_entity_create(conn, op.perm_id, tick=tick, quiet=True,
                                               **_live_pose(op.perm_id))
                    sent += 1
                except Exception as exc:  # noqa: BLE001 — a dying socket must not kill the ticker
                    log(f"  [WORLD] avatar refresh to conn #{conn.id} failed: {exc}")
            for npc in npcs.walker_npcs(_npcs):
                try:
                    village.send_entity_create(conn, npc.perm_id, tick=tick, quiet=True,
                                               **npc.pose())
                    sent += 1
                except Exception as exc:  # noqa: BLE001 — a dying socket must not kill the ticker
                    log(f"  [WORLD] NPC refresh to conn #{conn.id} failed: {exc}")
        if sent and cycles % 30 == 0:
            log(f"  [WORLD] avatar location refresh running: {sent} update(s)/cycle every "
                f"{AVATAR_REFRESH_SECS:.0f}s, tick={tick} (logged 1-in-30 cycles)")


def _ensure_avatar_ticker():
    global _avatar_ticker_started
    with _avatar_ticker_lock:
        if _avatar_ticker_started:
            return
        _avatar_ticker_started = True
        threading.Thread(target=_avatar_location_ticker, daemon=True).start()
        log(f"  [WORLD] avatar location ticker started — {AVATAR_REFRESH_SECS:.0f}s waypoint "
            f"refresh per remote avatar (ER 2026-08-01_avatar-location-refresh)")


def _spawn_world_avatars(conn):
    """Mutual avatar spawn on world entry: show this client everyone already in-world, and show
    this client TO everyone already in-world.

    PROVEN ON THE WIRE 2026-08-01: the spawn itself works end-to-end (TTD-verified chain, see
    docs/IN_WORLD_PRESENCE.md). The avatar only STAYS visible while the location ticker above
    streams waypoint refreshes — the spawn paints one frame, the ring does the rest."""
    _ensure_avatar_ticker()
    me = _player(conn)
    # Ambient NPCs first — they exist for every entrant, players or not.
    # World-clock sync MUST precede the first waypoint: stamps are cut against the
    # client's slewed clock at parse time and a later slew does not re-anchor them
    # (ER 2026-08-01_worldtick-clock-sync). The others-branch resend below is a no-op
    # client-side once the clock is slewed (250 ms tolerance).
    village.send_world_tick(conn, _now_ms())
    # The owner's purse and items (3201 + 3102), so the client's own checks — e.g. the tailor's
    # gold >= 50 — see the server's values. Discarded silently if the client has no avatar with
    # this id in its map, so it is harmless either way.
    economy.send_owner_state(conn, me.perm_id)
    # Record NPCs (PlayerCreate 1004): one message each — the consumer builds the
    # object from its template immediately, no waypoint stream involved.
    for npc in npcs.record_npcs(_npcs):
        village.send_player_create(conn, npc.perm_id, npc.name, quiet=True,
                                   **npc.record_kwargs())
        # ⛔ Do NOT push the NPC's shop here. ShopInventoryData(0xE11) is not a stock cache —
        # its ARRIVAL OPENS THE DIALOG: the villageConn+0x128 observer `FUN_004323d0` hands the
        # data to the ShopDialog (screen+0x35d4) and then calls its vtbl+0x2c *show* method
        # [PROVEN 2026-08-02]. Pushing it at world entry made the shop pop open unbidden the
        # moment the NPC spawned (live-observed) and did nothing on a later click — a result
        # that LOOKS like a working shop but is really the server forcing a dialog. The real
        # server can only have sent 0xE11 as the REPLY to a shop-open request.
        # ⏳ The blocker: clicking a shop NPC puts NOTHING on the wire (live-verified twice via
        # the stub journal), so the client's request path is not being reached. Finding out why
        # needs a live trace of the OpenShop button handler — static analysis of
        # `VillageScreen_UpdateActionButtons@0x00433f60` bottoms out in unreliable
        # decompilation. `village.send_shop_inventory` is ready for that reply when we get
        # there; `npc.shop` carries the stock.
    # Walkers (EntityCreate 1001 avatars): the proven remote-player pattern — one
    # styled spawn plus two ring-priming pushes so the movement ring brackets "now".
    npc_tick_base = _now_tick16()
    for npc in npcs.walker_npcs(_npcs):
        pose = npc.pose()
        village.send_entity_create(conn, npc.perm_id, tick=(npc_tick_base - 1000) & 0xFFFF,
                                   quiet=True, style=npc.style(), **pose)
        for prime in ((npc_tick_base - 3000) & 0xFFFF, (npc_tick_base - 1000) & 0xFFFF):
            village.send_entity_create(conn, npc.perm_id, tick=prime, quiet=True, **pose)
    if _npcs:
        log(f"  [WORLD] spawned {len(npcs.record_npcs(_npcs))} record NPC(s) + "
            f"{len(npcs.walker_npcs(_npcs))} walker(s) for {me.char_name!r}")
    else:
        log("  [WORLD] NPCs are OFF (config.VILLAGE_NPCS_ENABLED=False) — none spawned")
    others = _in_world_conns(exclude_player=me.perm_id, exclude_conn=conn)
    if not others:
        log(f"  [WORLD] {me.char_name!r} entered — no other players in-world yet")
        return
    # Sync each client's world clock to OUR timebase BEFORE any waypoint lands: waypoint stamps
    # are absolute u64s cut against the clock at parse time and are NOT re-anchored by a later
    # slew, so the slew must happen first. First 1005 ⇒ phase error ≥250 ms ⇒ immediate slew.
    village.send_world_tick(conn, _now_ms())
    for other in others:
        village.send_world_tick(other, _now_ms(), quiet=True)
    tick_base = _now_tick16()
    tick = (tick_base - 1000) & 0xFFFF
    my_pose = _live_pose(me.perm_id)
    for other in others:
        op = _player(other)
        # Spawn each side at the other's LAST REPORTED pose (msg 2000) — position, facing AND zone.
        # A player who has been walking around is already somewhere, possibly inside a side room;
        # only a player who has not reported yet falls back to the placeholder ring spot.
        op_pose = _live_pose(op.perm_id)
        village.send_entity_create(conn, op.perm_id, tick=tick,
                                   label=f"[{op.char_name!r} shown to {me.char_name!r}]",
                                   style=_avatar_style(op), **op_pose)
        village.send_entity_create(other, me.perm_id, tick=tick,
                                   label=f"[{me.char_name!r} shown to {op.char_name!r}]",
                                   style=_avatar_style(me), **my_pose)
        # Prime the movement ring so the avatar is bracketed from the very first tick: waypoint
        # stamp = reconstruct(wire tick)+2000 ms, so wire now-3000 lands a stamp at ≈now-1000 and
        # wire now-1000 lands one at ≈now+1000 — a bracket STRADDLING "now" immediately, held until
        # the 1 Hz ticker takes over. Without waypoints the interpolator hides the avatar
        # (render-node bit 0x20) one frame after the create paints it (TTD: avatar_vanish_diag.run).
        for prime in ((tick_base - 3000) & 0xFFFF, (tick_base - 1000) & 0xFFFF):
            village.send_entity_create(conn, op.perm_id, tick=prime, quiet=True, **op_pose)
            village.send_entity_create(other, me.perm_id, tick=prime, quiet=True, **my_pose)
    log(f"  [WORLD] {me.char_name!r} entered — exchanged avatars with {len(others)} player(s)")


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


def push_servers_removed(server_ids, server_type=5):
    """Push 169 RemoveServer {server_id, running 0, ticket 0} to the observers, so other browsers drop
    the row. A ticket-0 169 reaches listener +0x14 = ServerList::RemoveServer S 0046a5e0, which erases
    the entry; a 170 can never remove a game (games ignore `running`). [inferred, T 10023cc0 case 0xa9]
    Called when a host removes its game and when the host's connection closes."""
    with _obs_lock:
        targets = list(set(_obs.get(server_type, []) + _obs.get(0, [])))
    for sid in server_ids:
        body = codec.encode_body(169, {"server_id": sid, "running": False, "ticket_id": 0})
        pushed = 0
        for c in targets:
            if getattr(c, "alive", False):
                try:
                    c.send_app(169, body)
                    pushed += 1
                except Exception:  # noqa: BLE001
                    pass
        log(f"  [OBS] pushed 169 RemoveServer id={sid} to {pushed} observer(s)")


def _has_password(fields):
    """H9: the host sends `cipher` only when the game has a password (the literal "PASSWORD"
    encrypted by tincat3; the real password never leaves the client). Present → protected."""
    return bool(fields.get("cipher"))


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


def _char_values(conn, ticket, char=None):
    """CharacterData(75)/UserCharConn(60) field values for ONE character.

    ⭐ `char_id` and `owner_id` are DIFFERENT namespaces (msgdefs.ini gives both fields): the
    character has its own id, the account owns it. They used to be the same number here, which
    only worked while an account could hold exactly one character."""
    p = _player(conn)
    return {
        "char_id": int(char["char_id"]) if char else p.char_id,
        "name": (char.get("name") if char else p.char_name) or p.username,
        "owner_id": p.user_id, "owner_name": p.username,
        "guild_id": 0, "guild_name": None, "guild_role": 0, "status": 1,
        "server_id": 0, "server_name": None,
        "data": (char.get("data") if char else p.data) or b"",
        "ticket_id": ticket}


@handler(55)  # RequestUserCharList -> UserCharConn
def _h_player_info(conn, fields, ticket):
    # Same rule as RequestCharacters(72): a player who has not created a character has an empty
    # list, not a stand-in one. Announcing a character here that 72 then fails to produce would
    # leave the two lists disagreeing about who this account is.
    p = _player(conn)
    if not config.PERSISTENT_CHARACTERS_ENABLED or p.has_character:
        conn.send_app(60, codec.encode_body(60, _char_values(conn, ticket)))
    conn.ok(ticket)


@handler(72)  # RequestCharacters -> CharacterData
def _h_request_characters(conn, fields, ticket):
    """Answer with the player's PERSISTED character, or with nothing at all.

    ⭐ Sending ZERO CharacterData frames is a first-class, supported client path, not a failure:
    `CharacterManager::CharacterObserverListener::CharacterDataReceived@0x00474910` branches on
    the aggregated count and, at count==0, logs "No characters found." at INFO severity, sets the
    parent's loaded flag (+0x88) and refreshes the UI — which is what opens character creation.
    That is why a brand-new player gets an empty list here instead of the old hardcoded stand-in
    character (`config.NICKNAME_DATA`, whose zlib payload is literally named "tester")."""
    p = _player(conn)
    if not config.PERSISTENT_CHARACTERS_ENABLED:
        # LEGACY (rollback path): one implicit character, char_id == perm_id, shared appearance.
        conn.send_app(75, codec.encode_body(75, _char_values(conn, ticket)))
        conn.ok(ticket)
        return
    chars = store.list_characters(p.username)
    for char in chars:
        conn.send_app(75, codec.encode_body(75, _char_values(conn, ticket, char)))
    if chars:
        log(f"  → CharacterData ×{len(chars)} for {p.username!r}: "
            + ", ".join(f"{c['name']!r}(id {c['char_id']}, {len(c['data'])}B)" for c in chars))
    else:
        log(f"  → RequestCharacters: {p.username!r} has NO characters yet — replying with an "
            f"empty list so the client opens character creation")
    conn.ok(ticket)


def _store_character(conn, fields, ticket, what):
    """Shared body of the three character-creating messages (77/79/86).

    The `data` blob is stored EXACTLY as the client sent it. We do not parse or regenerate it:
    the client authors the character (name in UTF-16LE plus appearance/stat fields, split into
    six sub-blocks by `CommLayer::Character::GetData`), and replaying its own bytes is both the
    correct store behaviour and the only way to avoid corrupting a format we have not fully
    reversed."""
    p = _player(conn)
    name = fields.get("name") or p.username
    data = fields.get("data") or b""
    if not config.PERSISTENT_CHARACTERS_ENABLED:
        # LEGACY (rollback path): acknowledge the creation with the account's own id and store
        # nothing — the client then plays the single implicit character, as it did all session.
        log(f"  {what} name={name!r} — persistence is OFF, acknowledging without storing")
        conn.status_with_id(0, p.perm_id, ticket)
        return
    if not data:
        # Storing an empty blob would leave a character that LOOKS created but has no body —
        # better to refuse loudly than to persist a broken record.
        log(f"  ⚠ {what} for {p.username!r} carried NO data blob — refusing to store an empty "
            f"character; the client will be told the creation failed.")
        conn.status_with_id(1, 0, ticket)
        return
    char = store.create_character(p.username, name, data)
    existing = store.list_characters(p.username)
    log(f"  ✅ {what}: {name!r} stored for {p.username!r} → char_id {char['char_id']} "
        f"({len(data)}B); the account now has {len(existing)} character(s), surviving restarts.")
    # ⭐ Answer with the NEW character's id, not the account's — this is the id the client will
    # refer to that character by from now on (and, on selection, present as its token perm_id).
    conn.status_with_id(0, int(char["char_id"]), ticket)


@handler(77)  # CreateCharacterFromPreview
def _h_create_character(conn, fields, ticket):
    _store_character(conn, fields, ticket, "CreateCharacterFromPreview")


@handler(79)  # AddCharacterFromPreview
def _h_add_character_preview(conn, fields, ticket):
    _store_character(conn, fields, ticket, "AddCharacterFromPreview")


@handler(86)  # AddCharacter
def _h_add_character(conn, fields, ticket):
    _store_character(conn, fields, ticket, "AddCharacter")


@handler(90)  # ChangeCharacter
def _h_change_character(conn, fields, ticket):
    """Persist an edit to the character the client NAMES by char_id.

    `property_mask` says which fields the client considers changed; we update only what it
    actually sent and leave the rest alone. [TODO] the mask's bit meanings."""
    p = _player(conn)
    if not config.PERSISTENT_CHARACTERS_ENABLED:
        conn.ok(ticket)                       # LEGACY: bare ack, nothing persisted
        return
    char_id = fields.get("char_id") or p.char_id
    mask = fields.get("property_mask", 0)
    if not char_id:
        log(f"  ⚠ ChangeCharacter from {p.username!r} named no char_id — ignoring")
        conn.ok(ticket)
        return
    updated = store.update_character(char_id, name=fields.get("name"), data=fields.get("data"))
    if updated is None:
        log(f"  ⚠ ChangeCharacter: no character with char_id {char_id} — nothing updated")
    else:
        players.refresh_from_store(p.username)
        log(f"  ✅ ChangeCharacter: char_id {char_id} is now {updated['name']!r} "
            f"({len(updated['data'])}B, mask=0x{mask:x})")
    conn.ok(ticket)


@handler(94)  # RemoveCharacter
def _h_remove_character(conn, fields, ticket):
    """Delete the character the client NAMES by char_id — not 'whatever this account has'.

    With several characters on an account, deleting by account would remove the wrong one; the
    message carries the id precisely so the client can say which."""
    p = _player(conn)
    if not config.PERSISTENT_CHARACTERS_ENABLED:
        conn.ok(ticket)                       # LEGACY: bare ack, nothing to delete
        return
    char_id = fields.get("char_id") or p.char_id
    if not char_id:
        log(f"  ⚠ RemoveCharacter from {p.username!r} named no char_id — refusing to guess "
            f"which character to delete")
        conn.ok(ticket)
        return
    gone = store.delete_character(char_id)
    if gone is None:
        log(f"  ⚠ RemoveCharacter: no character with char_id {char_id} — nothing deleted")
    else:
        players.refresh_from_store(p.username)
        left = store.list_characters(p.username)
        log(f"  ✅ RemoveCharacter: {gone['name']!r} (char_id {char_id}) deleted; "
            f"{p.username!r} has {len(left)} character(s) left"
            + (" — the next RequestCharacters re-opens creation" if not left else ""))
    conn.ok(ticket)


@handler(88)  # ChangeUser (confirm)
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
# 172 DeregObserverServerList is acked but the observer is NOT removed: the message carries only a
# ticket, so it cannot say WHICH list is closing, and every client registers two (171 for the village
# list and for the game list). Dropping both on one 172 would silently stop village-list pushes. The
# observer goes away when the socket closes; until then it only receives a few extra pushes. [inferred]
@handler(115, 116, 172, 146, 190)
def _h_ack(conn, fields, ticket):
    conn.ok(ticket)


# ── Buddies (buddies.py; catalog 56/61/98/99) ─────────────────────────────────
def _lobby_conn_of(perm_id):
    """A player's live LOBBY connection (newest), for 61 presence pushes."""
    found = _find_live(lambda c: getattr(c, "role", "") == "lobby" and _player(c).perm_id == perm_id)
    return found[-1] if found else None


@handler(56)  # RequestUserBuddyList -> N x 61 on the ticket, then Result
def _h_buddy_list(conn, fields, ticket):
    buddies.send_list(conn, _player(conn).perm_id, ticket)


@handler(98)  # AddUserBuddy
def _h_add_buddy(conn, fields, ticket):
    me, other = _player(conn).perm_id, fields.get("buddy_id", 0) or 0
    err = buddies.add(me, other)
    conn.result(err, ticket)
    log(f"  [BUDDY] {me} adds {other}: {'OK' if not err else 'refused (errorcode 1)'}")
    if not err:
        buddies.push_one(conn, me, other)          # T29: start with the buddy's real status


@handler(99)  # RemoveUserBuddy
def _h_remove_buddy(conn, fields, ticket):
    conn.result(buddies.remove(_player(conn).perm_id, fields.get("buddy_id", 0) or 0), ticket)


@handler(175, 176)  # Reg/DeregObserverBuddylist
def _h_buddy_observer(conn, fields, ticket):
    """Completed ONLY by AddResult(153): there is no Result case for 0xaf/0xb0 in the routing table, so
    a Result(42) leaks the ticket (T 1002677c). No buddy pushes yet (T30). [known]"""
    conn.status_with_id(0, fields.get("user_id", 0) or 0, ticket)


# ── Mail (mail.py; docs/message-catalog.md 147-151) ───────────────────────────
@handler(150)  # AddPrivateMessage
def _h_add_private_message(conn, fields, ticket):
    """Completed ONLY by AddResult(153) (T 10028fc0 -> PostOffice::SendMailResultReceived). A Result(42)
    leaves MailManager busy +0x34 set and stalls the whole PostOffice queue. [known, board #4788]"""
    target = fields.get("delivery_target", 0) or 0
    known = any(p.perm_id == target for p in players.all_players())
    if not known:
        log(f"  [MAIL] AddPrivateMessage to unknown recipient {target} → AddResult errorcode 1")
        conn.status_with_id(1, 0, ticket)
        return
    mid = mail.add(target, _player(conn).perm_id, fields.get("title"), fields.get("message_text"))
    log(f"  [MAIL] {_player(conn).perm_id} → {target}: {fields.get('title')!r} stored as #{mid}")
    conn.status_with_id(0, mid, ticket)


@handler(147)  # RequestPrivateMessageList
def _h_private_message_list(conn, fields, ticket):
    mail.send_inbox(conn, fields.get("delivery_target") or _player(conn).perm_id, ticket)


@handler(148)  # ChangePrivateMessage (mark read)
def _h_change_private_message(conn, fields, ticket):
    mail.mark(fields.get("message_id", 0), fields.get("status", 1))
    conn.ok(ticket)


@handler(151)  # RemovePrivateMessage
def _h_remove_private_message(conn, fields, ticket):
    mail.remove(fields.get("message_id", 0))
    conn.ok(ticket)


@handler(157)  # RequestUserIgnoreList — the LAST message of the lobby-connection login
def _h_ignore_list(conn, fields, ticket):
    conn.ok(ticket)
    # The lobby login is complete: tell this player's watchers it is online (T25).
    buddies.push_presence(_player(conn).perm_id, True, _lobby_conn_of)


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

    Because that handler dials unconditionally, the 192 is sent only when the player has no live
    UC connection — see the comment above the send. Sending one per assign leaked a client socket
    a minute and eventually OOM-killed the client.
    """
    server_type = fields.get("server_type", 0)
    server_subtype = fields.get("server_subtype", 0)

    # ── Referee assign (type=4, subtype=4) ── [flag-gated · ER 2026-06-13_referee-assign-170] ──────────
    # RequestRefereeServer@0x468f60 sends AssignServer(4,4); a debugger trace of AssignServer (2026-06-13,
    # live) confirmed the discriminator is server_subtype=4 (village-entry uses the 221→222 path, not 189).
    # Reply a GameServerData(170) for the REFEREE_SERVER so it routes into tincat3
    # GameServerManager_OnGameServerAssigned@0x10021520 → its DEFAULT branch →
    # LobbyServerList_GameServerAssigned@0x00469ad0 → SetRefereeServerAddress@0x4625d0 → LM+0x580.
    # ⚠️ The descriptor MUST NOT be type4/sub5 — that value is special-cased to a tincat3-private
    # handler that returns without notifying the lobby. See the REFEREE_SERVER comment below and
    # ER 2026-07-27_referee-assign-subtype-routing. The 192 below is a different message type
    # (tincat3's UsercommServerData dial handler, independent of the 170), so UC/chat still comes up
    # on the FIRST assign — but it is now suppressed once a UC conn is live; see there for why.
    if config.REPLY_REFEREE_ASSIGN and server_type == 4 and server_subtype == 4:
        # ONE frame, type4/sub4 → the DEFAULT branch of tincat3
        # GameServerManager_OnGameServerAssigned@0x10021520 → LobbyServerList_GameServerAssigned
        # @0x00469ad0 → SetRefereeServerAddress@0x004625d0 → LM+0x580 latched (+0x588 = 60000).
        #
        # ⛔ Do NOT also send a type4/sub5 twin here. Tried 2026-07-27 and it REGRESSED: the assign
        # ticket (kind 0x108) is consumed ONCE, so the second frame never reaches the assign path at
        # all — measured by the 60 s retry, which only exists once SetRefereeServerAddress armed
        # LM+0x588. sub4 alone → retry at +60 s; sub5+sub4 → no retry, i.e. no latch.
        conn.send_app(170, codec.encode_body(170, server_to_170_values(REFEREE_SERVER, ticket)))
        log(f"  → [REFEREE] GameServerData(170) id={config.REF_SERVER_ID} "
            f"type{REFEREE_SERVER['server_type']}/sub{REFEREE_SERVER['server_subtype']} "
            f"-> {config.ADVERTISED_IP}:{config.REFEREE_PORT} (ticket={ticket}) "
            "— default branch → LobbyServerList_GameServerAssigned → LM+0x580")
        # This frame ONLY latches the id and gets the connection created. The ip:port arrives
        # separately, when the client asks for it with 221 RequestConnectionData → see
        # _h_connection_data. (A follow-up 170 was tried here on 2026-07-27 and did nothing —
        # 170 is not the message that addresses a connection.)

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

    # ── UC/chat dial (UsercommServerData 192) ────────────────────────────────────────────────────
    # ⚠️ ONE 192 PER UC CONNECTION — never one per assign. tincat3's generic CommLayer 0xc0 handler
    # (FUN_10030420) DIALS the advertised ip:port every single time it sees a 192; it does not check
    # whether a UserComm connection is already up. The referee reply above arms LM+0x588, which makes
    # the client re-send AssignServer(189 type4/sub4) every 60 s for the rest of the session — that
    # exact-60 s cadence is the tell that the latch worked, so it is CORRECT and must keep happening.
    # Answering each retry with a 192 therefore stood up a brand-new UC socket every minute that the
    # client never closed. Measured live 2026-08-08: 57 assigns, 48 UC logins for one player, 41 of
    # those sockets still open, each carrying 18 ChannelInfo worth of channel objects. The client is
    # a 32-bit process, so that leak ends exactly one way — `operator new`@0x006f2524 gets NULL from
    # malloc and throws the static std::bad_alloc at DAT_0088f5b0 (crash 16:41:04, and 5 more that
    # day). The retry is not the bug; re-dialing on the retry is.
    me = _player(conn)
    live_uc = _find_live(lambda c: getattr(c, "is_chat", False)
                         and _player(c).perm_id == me.perm_id)
    if live_uc:
        log(f"  → UsercommServerData(192) SUPPRESSED — {me.username!r} (perm_id={me.perm_id}) already "
            f"has a live UC conn (#{live_uc[0].id}); a 192 here would dial a SECOND one and leak it")
        return

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
        # "Protected" icon: true only when ==1 (S 0048da70). Set from the host's 168/177 cipher (H9).
        "password_required": bool(srv.get("password_required")),
        "server_type": srv.get("server_type", 5),
        "server_subtype": srv.get("server_subtype", 0),
        "version": srv.get("version", ""),
        "max_players": srv.get("max_players", 2), "cur_players": srv.get("cur_players", 1),
        # ⚠️ The game browser shows occupied = max_spectators + ai_players and never reads
        # cur_players for games (S 0048da70, disasm 0048db1b). The host sends its HUMAN count in
        # max_spectators (168/177, CountHumanSlots), so it must be echoed here, or every hosted game
        # lists as "0 + AI" occupied. [known]
        "max_spectators": srv.get("max_spectators", 1), "cur_spectators": 0,
        "ai_players": srv.get("ai_players", 0),
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

# The referee / match-arbiter server (tincat3 calls it the RANKING server — its API is
# RegisterGame / FinishGame / GiveUpGame / ClaimChest). Replied to AssignServer(189, type4/sub4).
# A unique id (REF_SERVER_ID, not 1/50) forces a real dial to REFEREE_PORT rather than reusing the
# UC/village conn. No data block (not a joinable village); stays off the browsers.
#
# subtype 4 is deliberate: only a NON-4/5 descriptor reaches the lobby observer and latches
# LM+0x580. 4/5 goes to a tincat3-private handler that never notifies the lobby. But 4/4 alone is
# NOT enough either — it latches an ADDRESS-LESS connection. The address arrives in the follow-up
# 170 from _push_referee_address(). Read the full chain below the dict before touching either.
REFEREE_SERVER = {
    "id": config.REF_SERVER_ID, "owner_id": config.TEST_PERM_ID,
    "name": "referee", "description": "SaDK Referee",
    "ip": config.ADVERTISED_IP, "port": config.REFEREE_PORT,
    "max_players": 0, "cur_players": 0, "ai_players": 0,
    "lobby_id": config.LOBBY_PROTOCOL_VERSION, "version": "",
    "server_type": 4, "server_subtype": 4,
    "level": 0, "game_mode": 0, "hardcore": False,
    "map": "", "running": False, "data": None,
}


# ⛔ There is deliberately NO "push a 170 to address the referee" helper here. That was tried on
# 2026-07-27 and did nothing: 170 GameServerData is a DESCRIPTOR/list message, not the one that
# fills conn+0x14/+0x18. The address is delivered by 222 ConnectionData in reply to the client's
# 221 RequestConnectionData — see _h_connection_data.

# ══ REFEREE ASSIGN — the complete proven model, 2026-07-27 (tincat3 + sadk_noav + TTD) ══
#
# TICKETING. GameServerManager_AssignServer@0x10021830 allocates a ticket of kind 0x108 and puts its
# id in the 189. Only 0x108 replies reach GameServerManager_OnGameServerAssigned@0x10021520, and a
# ticket is consumed ONCE — so exactly one reply per 189 can take the assign path. (Measured: an
# unmatched reply carries 0xAB = 171 and is demoted to a list update.) That is why the "send both
# 4/5 and 4/4" attempt regressed: the second frame never reached the assign handler at all.
#
# THE FORK. OnGameServerAssigned tests desc+0x28/+0x29. That single `CMP byte ptr [ESI+0x29],5` at
# 0x1002152e is the ONLY test of subtype 5 in the entire DLL (exhaustive instruction search):
#     4/5   -> CommLayer::RankingManager::vtbl[0x20] = FUN_10029a20   (lobby NEVER notified)
#     other -> default branch -> LobbyServerList_GameServerAssigned@0x00469ad0
#              -> SetRefereeServerAddress@0x004625d0 -> LM+0x580 = id, LM+0x588 = 60000
#
# WHY 4/5 ALONE FAILS. FUN_10029a20 does NOT create a connection — vtbl[0x54] (=0x100185a0) is a
# plain getter returning ConnectionManagerINet+0x1c, a PRE-ALLOCATED singleton built in the CM ctor
# (kinds 0/1/2 live at +0x14/+0x18/+0x1c). It applies the address, sets +0x1c = serverId and dials.
# So the :5481 dial we observe is real — but the lobby is never told, LM+0x580 stays INVALID, and
# LobbyManager_InitRefereeServerConnection@0x00462910 never runs, so refConn+0x34 stays NULL and
# RefereeServerConnection::Login@0x004793f0 is a silent no-op. (Measured: refConn+0x34 = 0.)
#
# WHY 4/4 ALONE FAILS. It latches LM+0x580, so InitRefereeServerConnection runs and binds
# refConn+0x34 = connMgr->lookup_by_serverId(77). That lookup (FUN_10019570) walks ONLY the +0x10
# collection. The CM ctor creates +0x10 EMPTY and never adds the three fixed connections, so the
# addressed kind-2 singleton is invisible to it. The lookup therefore falls to FUN_100196b0's
# freshly created connection, which has an EMPTY address (FUN_10037120(this+0x48, "")). Login then
# calls Connect(netTransportId, NULL) — param_2 NULL means it supplies no address either — so the
# dial dies as COMM_LAYER_ERROR_CANNOT_CONNECT (LobbyManager.cpp:907 + LobbyBaseConnection.cpp:119,
# both seen live on 4/4 runs).
#
# ✅ RESOLVED — the address comes from a SECOND 170, sent AFTER the connection exists.
# The static sweep of FUN_100191e0's callers suggested "list-registered AND serverId-keyed AND
# addressed" was unsatisfiable. That was WRONG, and measuring the working village connection proved
# it: conn+0x14 -> "192.168.1.130", conn+0x18 = 5479, conn+0x1c = 50 (FAKE_VILLAGE's id). A
# list-registered connection demonstrably carries both. A 170 for server id N fills +0x14/+0x18 on
# the live connection keyed by N — the same job CommLayer_OnUsercommServerData does for the UC conn.
# So the sequence is: 4/4 assign reply latches + creates the connection, then a follow-up 170
# addresses it. See _push_referee_address() above.
# ⛔ Ordering is load-bearing: advertising the referee in _send_server_list (answering 171 at login)
# sends that 170 ~37 s BEFORE the connection exists and is silently useless — that is precisely how
# the 2026-07-27 server-list attempt failed, and why it must NOT go back there.
#
# ONE-SHOT DEADLOCK (LobbyManager::StatePump_Tick@0x00464ee0) — the reason retries are so rare:
#     if (5 < state) {
#         if (+0x584 == 0) { +0x584 = 1; RequestRefereeServer(); +0x588 = 0; }  // fires ONCE
#         if (+0x588 < 0) +0x584 = 0;                                           // only re-arm
#     }
# +0x588 is armed (=60000) only by SetRefereeServerAddress. So if the first assign does not latch,
# +0x588 stays 0, never goes negative, and the client NEVER requests a referee again for the whole
# process lifetime. This is why 4/4 runs show a 60 s retry cadence and 4/5 runs show a single frame.
# ⚠️ TEST RULE: the one-shot fires on the FIRST login after process start, so any TTD recording must
# begin BEFORE that login (mode="launch" / restart the game) or it records only zeros.
#
# NEXT [TODO] once the dial succeeds: RefereeServerConnection::Login@0x004793f0 sends NO message —
# it only opens the channel — so nothing on the wire ever requests a login result. The server must
# PUSH LoginSuccess(0xDCA), and OnLoginSuccess@0x0047ac20 silently drops it unless the message's
# "PermID" field equals LobbyManager+0x54c (measured = 1, the logged-in user id; INVALID = 0).
# That fan-out (+0x80) is what runs Lobby_HostRegisterGameWithReferee@0x00432240 → RegisterGame.


def _send_server_list(conn, server_type, ticket):
    sent = 0
    for srv in _games_for_list(conn, server_type):
        conn.send_app(170, codec.encode_body(170, server_to_170_values(srv, ticket)))
        sent += 1
    if sent == 0 and server_type == 4:
        conn.send_app(170, codec.encode_body(170, server_to_170_values(FAKE_VILLAGE, ticket)))
        sent += 1
        log("  → Injected fake village world (ServerType=4) w/ room-assign data blob")
    # ⛔ The referee is deliberately NOT advertised here. Listing it was tried on 2026-07-27 on the
    # theory that the client learns id→address from the list; the tincat3 decompile refuted that —
    # the address travels in the ASSIGN reply (serverDesc+0x10 → FUN_100191e0), and the lookup
    # FUN_10019570 only walks live connections keyed by +0x1c. A list entry creates no connection.
    # See the REFEREE_SERVER comment above and ER 2026-07-27_referee-via-server-list (REFUTED).
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
        "max_spectators": fields.get("max_spectators") or 1,    # the host's human count (see 170)
        "ai_players": fields.get("ai_players", 0),
        "password_required": _has_password(fields),
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
    sid = fields.get("server_id", 0)
    removed = _remove_game(conn, sid)
    conn.ok(ticket)     # Result(42) 0 → DeleteResultReceived S 00469990 resets the host's +0x9c
    if removed:
        push_servers_removed([sid])


@handler(177)  # ChangeGameServer
def _h_change_server(conn, fields, ticket):
    """The host re-sends ALL fields on every room change (property_mask is never written, T 10021040),
    so every field is applied, including the ones the game browser shows: max_spectators (human
    count), ai_players, hardcore (ranked) and the password flag (cipher present). [known]"""
    changes = {k: fields.get(k) for k in
               ("name", "description", "max_players", "max_spectators", "ai_players",
                "game_mode", "hardcore", "map", "running", "data")
               if fields.get(k) is not None}
    changes["password_required"] = _has_password(fields)
    rec = _change_owned_game(conn, changes)
    if rec is not None:
        log(f"  ChangeGameServer: id={rec.get('id')} humans={rec.get('max_spectators')} "
            f"ai={rec.get('ai_players')} protected={rec.get('password_required')} map={rec.get('map')!r}")
        # Keep observers' browser current as the host changes map/settings.
        _push_to_obs(rec.get("server_type", 5), rec)
    conn.ok(ticket)


@handler(221)  # RequestConnectionData -> ConnectionData
def _h_connection_data(conn, fields, ticket):
    """⭐ THIS is where a tincat3 connection learns its ip:port. [PROVEN 2026-07-27]

    CommLayer_ServerRecvHandler_StateMachine@0x10023cc0 pulls the `server_id` / `ip` / `port`
    fields (name strings @0x1004f154 / @0x1004f0f0 / @0x1004cd3c) out of the inbound message,
    looks the connection up by server id (`vtbl[0x5c]` = FUN_10019570, matching conn+0x1c), and
    on a hit calls FUN_10030420 → FUN_100191e0, which fills conn+0x14 (host strdup) and
    conn+0x18 (port) and then dials. ConnectionReal::Connect@0x100309d0 dials from those two
    fields ONLY — with them empty it takes a passive branch and never opens a socket.

    ⇒ Any server the client must reach has to be resolvable HERE. The 170 GameServerData does NOT
    carry the address into the connection; that was tried on 2026-07-27 and did nothing. Measured:
    the client asked `221 server_id=77` and the old fallback answered :5479 (the world), so it
    dialled the world listener instead of the referee and the referee connect failed with
    COMM_LAYER_ERROR_CANNOT_CONNECT.
    """
    sid = fields.get("server_id", 0)
    srv = _get_game(conn, sid)
    if sid == config.REF_SERVER_ID:
        # The referee/ranking server. Its connection was created keyed by this id when the
        # AssignServer(189) reply latched LM+0x580; this is the frame that gives it a target.
        ip, port, note = config.ADVERTISED_IP, config.REFEREE_PORT, "  [REFEREE]"
    elif srv:
        # P2P handoff: a join to a real hosted game returns that host's advertised address
        # (the joiner dials the host directly).
        ip, port, note = srv["ip"], srv["port"], ""
    else:
        # The lobby-WORLD entry request (server_id=50, the injected FAKE_VILLAGE, never
        # registered) falls back to WORLD_PORT (:5479).
        ip, port, note = config.ADVERTISED_IP, config.WORLD_PORT, "  (unknown id — fell back to advertised world)"
    conn.send_app(222, codec.encode_body(222, {
        "perm_id": _player(conn).perm_id, "server_id": sid,
        "ip": ip, "port": port,
        "nonce": os.urandom(128), "errorcode": 0, "errormsg": None,
        "ticket_id": ticket}))
    log(f"  → ConnectionData(222) server={sid} → {ip}:{port}{note}")


# ── Token / chat-login validation ─────────────────────────────────────────────
@handler(211)  # StartValidateTokenSession -> AckValidateTokenSession
def _h_token_start(conn, fields, ticket):
    conn.token_nonce = os.urandom(128)          # remember our challenge so we can mirror it in 214
    conn.send_app(212, codec.encode_body(212, {"nonce": conn.token_nonce, "ticket_id": ticket}))
    log("  → AckValidateTokenSession (212) sent")


@handler(213, 224)  # SendToken / TANLogin -> AddResult(153)  [the 0x99 ACK the client awaits; NOT a 214]
# 224 TANLogin {perm_id, nonce, ticket} replaces 213 on a server-id connection opened with data
# (HandlerGS T 10023460, conn+0x3c == 0) and completes the same way: 153 with the 207 perm_id. [known]
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
        if not players.issued(fields["perm_id"]):
            # A stale token (issued before a server restart, or to someone else): refuse it so the
            # client goes back through a real login instead of impersonating the id's current owner.
            # A non-zero errorcode is the client's own failure path (UC: OnError + Disconnect).
            conn.status_with_id(1, 0, ticket)
            log(f"  [PLAYER] token #{conn.id} names perm_id {fields['perm_id']}, which did not log in "
                f"on this server run — REFUSED (errorcode 1); the client must log in again")
            return
        conn.player = players.resolve_by_perm(fields["perm_id"])
        perm_id = conn.player.perm_id
        log(f"  [PLAYER] token #{conn.id} → {conn.player.username!r} (perm_id={perm_id})")
    conn.status_with_id(0, perm_id, ticket)   # NETMSG 153 AddResult, errorcode=0 → the 0x99 ACK
    log("  → SendToken → AckResult(153) errorcode=0 [the 0x99 ACK → state 8 AUTHORIZED → LoggedIn]")
    # Post-login: push the chat ChannelInfo (deferred from the handshake so it lands in a
    # fully-constructed channel container instead of corrupting a half-built one; s31).
    if getattr(conn, "is_chat", False):
        chat.send_initial_reply(conn)
    # Post-login on the REFEREE conn: push LoginSuccess(0xDCA). [PROVEN 2026-07-27]
    # RefereeServerConnection::Login@0x004793f0 sends NO message — its body is a log-scope prologue
    # plus conn->vtbl[0x10](transport, 0), i.e. "open the channel" — so nothing on the wire ever
    # asks for a login result and the server must PUSH it. This 153 is the only cue there is: the
    # client sends no referee-channel frame to react to (which is why the old handle_frame trigger
    # could never fire). Measured 2026-07-27: both clients dialled :5481, completed the base login,
    # and the socket then went silent.
    # ⚠️ referee.send_login_success uses THIS connection's perm_id, and that is load-bearing —
    # OnLoginSuccess@0x0047ac20 compares the message's PermID against LobbyManager+0x54c and returns
    # SILENTLY on mismatch (no log, no error). With test=1 and test2=2, a constant would work for
    # one player and silently fail for the other.
    # ER: engagement_records/2026-07-27_referee-loginsuccess-on-153.md
    if getattr(conn, "is_referee", False):
        t = threading.Timer(config.REFEREE_LOGIN_OK_DELAY, referee.send_login_success, (conn,))
        t.daemon = True
        t.start()
        log(f"  [REFEREE] 153 ACK — pushing LoginSuccess(0xDCA, perm_id={perm_id}) in "
            f"{config.REFEREE_LOGIN_OK_DELAY}s → +0x80 observer → RegisterGame(0xDB6)")
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
            # Now that this client is in the world, exchange avatars with everyone else who is.
            time.sleep(config.AVATAR_SPAWN_DELAY)
            _spawn_world_avatars(c)
            # Then the minigame tables that already exist. After the avatars, because a seat block
            # naming an avatar the client has no 3D object for is dropped whole (ReadSeats S 00471f00).
            time.sleep(config.AVATAR_SPAWN_DELAY)
            minigames.sync_tables(_minigame_io(), c)
        threading.Thread(target=_push_enter_world, daemon=True).start()
        log(f"  [ENTER] (VILLAGE) pushing EnterWorld(1000) in {config.ENTER_WORLD_DELAY}s "
            "→ HandleEnterWorld → SetState(VillageEntered=9).")
    # ⛔ REFEREE LoginSuccess push REVERTED 2026-07-27 — the model behind it was REFUTED the same day.
    # We briefly pushed LoginSuccess(0xDCA) here, on the theory that the client was deadlocked waiting
    # for it after its base login. It is not. LobbyGameScreen_Update@0x00435980 shows the CLIENT sends
    # RefereeServerConnection::Login@0x004793f0 itself, gated on netmgr+0x3cc (StartLoading) and the
    # arm flag screen+0x3625 — i.e. at MATCH START, not at login. The server's job is to ANSWER that
    # Login, which referee.handle_frame already does. Pushing it here was also inert: the
    # LobbyGameScreen has not entered yet at base-login time, so nothing is subscribed to the +0x80
    # observer and the fan-out reaches nobody — exactly what the live test showed (sent 11:00:30.459,
    # zero client response, no RegisterGame). See ER 2026-07-27_referee-loginsuccess-push-after-153.
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
        conn._leave_phase = 1
        log(f"  [VILLAGE] *** LEAVE-VILLAGE REQUEST #{conn._leave_requests} — msg 2002 "
            f"(0x{msg_type:x}, code=0x{data[:4].hex()}) → phase 1: WorldLoginAck(1006, "
            f"code=0x{config.WORLD_LOGIN_ACK_CODE:08x}) → HandleWorldLoginAck → UserCommConnection::Logout "
            f"(UC is open, so it takes that branch). Phase 2 fires from on_conn_closed() when the UC "
            f"socket goes away. ***")
        village.send_world_login_ack(conn, force=True)
    elif msg_type == config.VILLAGE_PINGCODE_MSGTYPE:         # 0x2ED6 — in-world keepalive PingCode
        village.send_pong(conn, token=data)                 # echo the ping token, close the RTT round-trip
        # ⛔ DO NOT send WorldLoginAck(1006) here. [PROVEN LIVE 2026-07-26] msg 1006 is the LOGOUT
        # trigger, not an in-world ack: HandleWorldLoginAck@0x0046ec50 → ConnectionReal::Logout on the
        # UserComm AND village transports → state 9 → OnLoggedOut → HandleLoggedOut →
        # SetState(VillageLeft=11). Sending it on the first in-world PingCode logged the player straight
        # back out to character select ~0.1s after entering the world.
        # This call existed for months and looked harmless ONLY because the code scalar was serialised
        # little-endian, so the client's `if (code == 0xDEADBEEF)` never matched and the whole handler
        # body was skipped. Fixing the byte order (village.world_login_ack_body) exposed it immediately.
        # 1006 is now sent ONLY as the answer to a leave request (msg 2002), above.
    elif msg_type == config.VILLAGE_AVATAR_LOCATION_MSGTYPE:   # 0x27D0 — msg 2000 AVATAR LOCATION
        _h_avatar_location(conn, data)
    elif msg_type in _ECONOMY_HANDLERS:                         # 3001/3002/3600/3610/3620
        try:
            _ECONOMY_HANDLERS[msg_type](conn, _player(conn).perm_id, data)
        except Exception as exc:  # noqa: BLE001 — a malformed request must not kill the conn
            log(f"  [ECON] msg 0x{msg_type:x} from conn #{conn.id} failed: {exc} ({data[:16].hex()})")
    elif msg_type in _MINIGAME_HANDLERS or msg_type in config.VILLAGE_GAME_ACTION_MSGTYPES:
        try:
            if msg_type in _MINIGAME_HANDLERS:
                _MINIGAME_HANDLERS[msg_type](_minigame_io(), conn, _player(conn).perm_id, data)
            else:
                minigames.handle_game_action(_minigame_io(), conn, _player(conn).perm_id, msg_type, data)
        except Exception as exc:  # noqa: BLE001
            log(f"  [MINIGAME] msg 0x{msg_type:x} from conn #{conn.id} failed: {exc} ({data[:24].hex()})")
    elif msg_type == config.VILLAGE_COLOR_CHANGE_MSGTYPE:      # 0x2F6E — msg 3950 tailor
        _h_color_change(conn, data)
    elif msg_type == config.VILLAGE_CHAT_COMMAND_MSGTYPE:      # 0x2FA0 — msg 4000, nothing required
        log(f"  [WORLD] ChatCommand (msg 4000) from {_player(conn).char_name!r}: {data[:64].hex()}")
    else:
        log(f"  (SendGameData[74] msg_type=0x{msg_type:x} on conn #{conn.id} — logged, no in-world handler)")


def _shops():
    """npc_id -> (shop_id, name, stock) for the shop NPCs in the world (catalog V25/V28)."""
    return {n.perm_id: (n.shop[0], n.shop[1], n.shop[3]) for n in _npcs if getattr(n, "shop", None)}


def _gear_changed(handler):
    """Wrap an item handler: when the worn gear changed, send the other in-world players this avatar's
    ActiveItemsUpdate (3100) so their client re-runs UpdateAppearance for it."""
    def push(perm_id, conn, clear=()):
        body = economy.active_items_body(perm_id, economy.wallet(perm_id), clear)
        for other in _in_world_conns(exclude_player=perm_id, exclude_conn=conn):
            village._send_village(other, 3100, body, None, "ActiveItemsUpdate(3100)", quiet=True)

    def run(conn, perm_id, data):
        changed, cleared = handler(conn, perm_id, data)
        if changed:
            push(perm_id, conn, cleared)                 # two-step clear, see economy._active_slots
            if cleared:
                economy.settle(lambda: push(perm_id, conn))
            log(f"  → [ECON] ActiveItemsUpdate(3100) ownr={perm_id} to the other players")
    return run


_ECONOMY_HANDLERS = {
    config.VILLAGE_MOVE_ITEM_MSGTYPE: _gear_changed(economy.handle_move_item),
    config.VILLAGE_DELETE_ITEM_MSGTYPE: _gear_changed(economy.handle_delete_item),
    config.VILLAGE_OPEN_SHOP_MSGTYPE: lambda conn, pid, data: economy.handle_open_shop(conn, pid, data, _shops()),
    config.VILLAGE_SHOP_BUY_MSGTYPE: economy.handle_buy,
    config.VILLAGE_SHOP_SELL_MSGTYPE: economy.handle_sell,
}


def _minigame_io():
    return minigames.Io(
        send=lambda c, msg, body: village._send_village(c, msg, body, None,
                                                        f"minigame msg 0x{msg:x}", quiet=True),
        everyone=lambda: _in_world_conns(),
        publish_cell=lambda cell, name: chat.publish_cell(
            cell, name, _find_live(lambda c: getattr(c, "is_chat", False))),
        zone_of=_zone_of,
        # The owner's gold/glod after a stake moves: the matchmaking dialog checks the balance it
        # reads from the own avatar (+0xd0 / +0xd4, S 004447f0), which only 3201 updates.
        stats=lambda perm_id: [economy.send_stats(c, perm_id) for c in _in_world_conns()
                               if _player(c).perm_id == perm_id])


def _zone_of(perm_id):
    """The player's current location zone from its latest msg-2000 report (None if none yet)."""
    with _poses_lock:
        loc = _poses.get(perm_id)
    return loc["zone"] if loc else None


_MINIGAME_HANDLERS = {
    config.VILLAGE_CREATE_TABLE_MSGTYPE: minigames.handle_create,
    config.VILLAGE_JOIN_TABLE_MSGTYPE: minigames.handle_join,
    config.VILLAGE_LEAVE_TABLE_MSGTYPE: minigames.handle_leave,
    config.VILLAGE_TABLE_AMOUNT_MSGTYPE: minigames.handle_amount,
    config.VILLAGE_DICE_BETS_MSGTYPE: minigames.handle_place_bets,
    config.VILLAGE_DICE_ROLL_MSGTYPE: minigames.handle_roll,
}


# ── Position capture for NPC placement (maintainer tool, 2026-10-07) ──────────
# Stand where an NPC should be, face the right way, stop, then type "!pos <name>" in chat: the server
# stores the speaker's latest reported pose (msg 2000: position, facing, zone) in npc_positions.json.
# "!poslist" whispers back what is stored. Command lines are not relayed to other players.
NPC_POSITIONS_FILE = os.path.join(config.REPO_DIR, "npc_positions.json")


def _chat_command(conn, player, text):
    # The client sends chat as UTF-8 while the codec decodes STRING fields as ISO-8859-15, so
    # "Händler" arrives as "HÃ€ndler"; undo that for the command text.
    try:
        text = text.encode("iso-8859-15").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    cmd, _, arg = text.partition(" ")
    cmd, arg = cmd.lower(), arg.strip()
    try:
        saved = json.load(open(NPC_POSITIONS_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if cmd == "!pos":
        if not arg:
            return "Usage: !pos <name>  (stand still at the spot, facing the right way)"
        with _poses_lock:
            loc = _poses.get(player.perm_id)
        if loc is None:
            return "No position reported yet - walk a step first."
        x, y, z = loc["pos"]
        saved[arg] = {"pos": [round(x, 2), round(y, 2), round(z, 2)], "rot_deg": round(loc["rot_deg"], 1),
                      "zone": loc["zone"], "ghost_zone": loc["ghost_zone"], "by": player.char_name,
                      "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(NPC_POSITIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(saved, f, indent=1, ensure_ascii=False)
        log(f"  [POS] {player.char_name!r} saved {arg!r}: ({x:.2f}, {y:.2f}, {z:.2f}) rot={loc['rot_deg']:.0f} "
            f"zone={loc['zone']}/{loc['ghost_zone']}")
        return f"Saved '{arg}': ({x:.1f}, {y:.1f}, {z:.1f}) facing {loc['rot_deg']:.0f} deg, zone {loc['zone']}"
    if cmd == "!level":
        # The avatar's head is picked by level: model = (level - 1) * 3 + tribe column, level clamped
        # to 1..5 (CGfxObjAvatar::UpdateAppearance S 00508090; heads bavarian/scot/egypt _1.._5 in
        # bodyparts.xml). StatsUpdate (3201) sets the level but fires no observer, so an item update
        # follows to make the clients redraw (3102 to the owner, 3100 to the others).
        try:
            level = int(arg)
        except ValueError:
            return "Usage: !level <1-5>"
        w = economy.wallet(player.perm_id)
        w.level = max(0, min(level, 255))
        stats = economy.stats_body(player.perm_id, w)
        active = economy.active_items_body(player.perm_id, w)
        for c in _find_live(lambda c: getattr(c, "is_village", False)
                            and getattr(c, "_enter_world_sent", False)):
            village._send_village(c, economy.MSG_STATS, stats, None, "StatsUpdate(3201)", quiet=True)
            if _player(c).perm_id == player.perm_id:
                economy.send_items(c, player.perm_id)
            else:
                village._send_village(c, 3100, active, None, "ActiveItemsUpdate(3100)", quiet=True)
        log(f"  [STATS] {player.char_name!r} level -> {w.level}")
        return f"Level set to {w.level} (looks change for levels 1-5)"
    if cmd == "!poslist":
        if not saved:
            return "No positions saved yet."
        return " | ".join(f"{k}: ({v['pos'][0]:.0f},{v['pos'][2]:.0f}) {v['rot_deg']:.0f}deg"
                          for k, v in saved.items())
    return None                                   # not a server command: relay as normal chat


chat.COMMAND_HOOK = _chat_command


def _h_color_change(conn, data):
    """Tailor (msg 3950). The client recoloured its own avatar locally; nobody else sees it until a
    1001 with the style block arrives (no reply handler exists). On an accepted change, re-broadcast
    the style to every other in-world player with the current pose. [inferred, catalog V15]"""
    me = _player(conn)
    try:
        accepted = economy.handle_color_change(conn, me.perm_id, data)
    except Exception as exc:  # noqa: BLE001
        log(f"  [ECON] AvatarColorChange from conn #{conn.id} unparseable: {exc} ({data.hex()})")
        return
    if not accepted:
        return
    tick = (_now_tick16() - 1000) & 0xFFFF
    for other in _in_world_conns(exclude_player=me.perm_id, exclude_conn=conn):
        try:
            village.send_entity_create(other, me.perm_id, tick=tick, quiet=True,
                                       style=_avatar_style(me), **_live_pose(me.perm_id))
        except Exception as exc:  # noqa: BLE001
            log(f"  [ECON] style re-broadcast to conn #{other.id} failed: {exc}")


def _h_avatar_location(conn, data):
    """The client telling us where its player actually IS (msg 2000) — the inbound half of the
    presence protocol. Store the pose, then RELAY it to every other in-world client as a 1001
    location refresh, which is how a waypoint reaches their movement ring.

    Relay timing: we re-stamp with OUR clock (`_now_ms() - 1000`) rather than forwarding the
    sender's `tick`. The client turns a wire tick into a waypoint stamped `reconstruct(tick) +
    2000 ms`, and the interpolator needs waypoints straddling "now" — forwarding the sender's own
    (current) tick would put every stamp ~2 s in the FUTURE, which underflows the staleness check
    and hides the avatar (proven the hard way in round 2, ER 2026-08-01_avatar-location-refresh).
    Position/rotation/animation flags are relayed verbatim; only the timebase is ours.

    Arrival rate is ~15/s per client at 60 fps (S 0051ace0), so this is the real movement stream; the 1 Hz ticker stays as
    a keepalive for anyone who has stopped reporting."""
    try:
        loc = village.parse_avatar_location(data)
    except Exception as exc:  # noqa: BLE001 — a malformed report must not kill the conn
        log(f"  [WORLD] avatar location (msg 2000) from conn #{conn.id} unparseable: {exc} "
            f"({len(data)}B: {data[:16].hex()})")
        return
    me = _player(conn)
    with _poses_lock:
        prev = _poses.get(me.perm_id)
        _poses[me.perm_id] = loc
    x, y, z = loc["pos"]
    if prev is None:
        log(f"  [WORLD] {me.char_name!r} is reporting its position (msg 2000, ~15/s) — first fix "
            f"({x:.1f}, {y:.1f}, {z:.1f}) rot={loc['rot_deg']:.0f}° "
            f"zone={loc['zone']} ghstzne={loc['ghost_zone']}; relaying live to the others")
    elif (prev["zone"], prev["ghost_zone"]) != (loc["zone"], loc["ghost_zone"]):
        # Sub-zone transition (minigame room / hall of fame). Logged loudly because it is exactly
        # the case that used to break: we relayed zone 0 regardless, so a player who walked into a
        # side room stayed advertised as standing outside.
        log(f"  [WORLD] {me.char_name!r} ZONE CHANGE "
            f"{prev['zone']}/{prev['ghost_zone']} → {loc['zone']}/{loc['ghost_zone']} "
            f"at ({x:.1f}, {y:.1f}, {z:.1f}) — relaying the new zone")
    tick = (_now_tick16() - 1000) & 0xFFFF
    for other in _in_world_conns(exclude_player=me.perm_id, exclude_conn=conn):
        try:
            village.send_entity_create(other, me.perm_id, tick=tick, quiet=True,
                                       **_live_pose(me.perm_id))
        except Exception as exc:  # noqa: BLE001 — a dying socket must not kill the relay
            log(f"  [WORLD] avatar location relay to conn #{other.id} failed: {exc}")


# ── Chat over lobby magic ─────────────────────────────────────────────────────
@handler(259)  # RequestLeaveChannel — completed on the CellManager layer, not with a Result(42)
def _h_leave_channel(conn, fields, ticket):
    chat.handle_leave_channel(conn, fields, ticket)


@handler(17)  # RequestJoinChannel
def _h_join_channel(conn, fields, ticket):
    chat.handle_join_channel(conn, fields, ticket)


# ── Global chat ───────────────────────────────────────────────────────────────
# The client subscribes to the global-chat feed with 107 RegObserverGlobalChat and drops it with
# 108. Until 2026-07-27 both were bare-acked and `2 ChatMessage` was answered by echoing a
# "[Server] …" line back to the sender alone — so global chat looked alive to whoever was typing
# and reached nobody. Layouts are straight from msgdefs.ini (authoritative):
#     107 / 108  RegObserver / DeregObserverGlobalChat : ticket_id
#     2   ChatMessage (client → server) : mode, txt(256), ticket_id, from_id
#     165 Chat        (server → client) : txt(256), from_id
# NOTE the client only sends 107 once the player actually opens the global-chat tab, so an empty
# subscriber list is normal, not a bug — hence the echo-to-speaker fallback below.
_gchat_lock = threading.Lock()
_gchat: list = []


@handler(107)  # RegObserverGlobalChat
def _h_reg_global_chat(conn, fields, ticket):
    with _gchat_lock:
        if conn not in _gchat:
            _gchat.append(conn)
        n = len(_gchat)
    log(f"  RegObserverGlobalChat — conn #{conn.id} subscribed ({n} listener(s))")
    conn.ok(ticket)


@handler(108)  # DeregObserverGlobalChat
def _h_dereg_global_chat(conn, fields, ticket):
    _gchat_drop(conn)
    log(f"  DeregObserverGlobalChat — conn #{conn.id} unsubscribed")
    conn.ok(ticket)


def _gchat_drop(conn):
    with _gchat_lock:
        try:
            _gchat.remove(conn)
        except ValueError:
            pass


@handler(2)  # ChatMessage → relay to every global-chat subscriber as 165 Chat
def _h_chat_message(conn, fields, ticket):
    txt = (fields.get("txt") or "").strip()
    if not txt:
        return
    speaker = _player(conn)
    with _gchat_lock:
        targets = [c for c in _gchat if getattr(c, "alive", False)]
    if not targets:
        targets = [conn]        # nobody has opened the global tab — at least show the speaker
    body = codec.encode_body(165, {"txt": txt, "from_id": speaker.perm_id})
    sent = 0
    for c in targets:
        try:
            c.send_app(165, body)
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    log(f"  CHAT <{speaker.char_name}> {txt!r} → relayed to {sent} listener(s)")


# ── Quiet routing: keep routine 'default-implementation' chatter out of the main log ──────────────
# These handlers do nothing protocol-significant for the work under study — bare acks + boilerplate
# account/social login replies. connection.py routes their full per-message decode to
# tincat_lobby_unhandled.log (file only) so the main view stays focused on auth, server-list,
# AssignServer, village/world and chat. Genuinely UNKNOWN types (no handler) STAY in the main log.
# ⭐ The CHARACTER handlers (72/77/79/86/90/94) were quiet while they were boilerplate that
# echoed one hardcoded stand-in character. They are now the persistence path — creation,
# storage and replay of a real player's character — so they belong in the main log.
QUIET_HANDLERS = frozenset({
    _h_ack, _h_char_ack, _h_ignore_list, _h_user_info, _h_player_info,
    _h_cdkeys, _h_property_get, _h_motd,
})


def is_quiet(type_num):
    """True if this lobby message is routine/boilerplate → route its log to tincat_lobby_unhandled.log
    instead of the main view. False for unknown types (no handler), so new protocol stays visible."""
    return HANDLERS.get(type_num) in QUIET_HANDLERS
