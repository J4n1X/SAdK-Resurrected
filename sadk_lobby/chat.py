"""
Chat / UC (second-connection) sub-protocol.

The chat connection uses a different app-payload prefix than the lobby:
    Magic(0x0062) + Type(u16=0) + Id(u16=chatType)
Source of truth: S2Library/Protocol/ChatPayloads.cs (ChatPayloadPrefix).

Builders return ready-to-send bytes (wrap in a TinCat application frame via
conn.send_chat). Frame handlers take the owning Conn and use conn.send_chat().
"""
import struct
import threading

from . import codec, config, players
from .log import hex_dump, log
from .tincat import BinaryReader, str_field, bytes_field


# ── Channel roster ────────────────────────────────────────────────────────────
# Who is in which chat cell, so joins/messages/leaves can be fanned out to the other members.
# Before 2026-07-27 there was no roster at all: a joiner was told only about *themselves* and a
# chat line was echoed only back to its author, so the lobby was completely asocial even with two
# clients in the same channel.
_roster_lock = threading.Lock()
_roster: dict = {}          # cell_id -> list[Conn]  (UC/chat connections)


# ⛔ A cell roster holds one entry per PLAYER, not per socket. [PROVEN 2026-08-01 live, the
# Win7 "double send" bug] A relog opens a fresh UC connection while the previous one is still in
# the list and still flagged alive — the join log showed "3 existing members" with two players
# present. Delivering the relay once per socket makes the client print every line twice, and the
# machine that had relogged most doubled first (Win7 VM), which is why it looked OS-specific.
def _live_one_per_player(members, exclude=None):
    """Live connections from `members`, at most ONE per player, newest winning."""
    by_player = {}
    for c in members:
        if c is exclude or not getattr(c, "alive", False):
            continue
        by_player[players.of(c).perm_id] = c        # a later conn replaces an earlier one
    return list(by_player.values())


def _roster_join(cell_id, conn):
    """Add conn to the cell; return the OTHER live members (one per player)."""
    with _roster_lock:
        members = _roster.setdefault(cell_id, [])
        me = players.of(conn).perm_id
        for stale in [c for c in members if c is not conn and players.of(c).perm_id == me]:
            members.remove(stale)                   # this player's previous socket
        if conn not in members:
            members.append(conn)
        return _live_one_per_player(members, exclude=conn)


def _roster_members(cell_id):
    with _roster_lock:
        return _live_one_per_player(_roster.get(cell_id, []))


def on_conn_closed(conn):
    """A UC socket went away: drop it from every cell and tell the remaining members.

    Only announce the leave if the player has no OTHER live connection in that cell — when a
    stale socket from a previous login finally closes, the player is still standing there, and
    telling everyone they left would drop them from the roster while they are present."""
    left, still_here = [], set()
    with _roster_lock:
        for cell_id, members in _roster.items():
            if conn in members:
                members.remove(conn)
                left.append(cell_id)
                if any(getattr(c, "alive", False) and players.of(c).perm_id == players.of(conn).perm_id
                       for c in members):
                    still_here.add(cell_id)
    if not left:
        return
    p = players.of(conn)
    for cell_id in left:
        if cell_id in still_here:
            log(f"  [CHAT] {p.char_name!r} dropped a stale socket in cell {cell_id} "
                f"— still present on another connection, no leave announced")
            continue
        inner = inner_user_left(p.perm_id, cell_id)
        others = _roster_members(cell_id)
        for c in others:
            try:
                c.send_chat(reply(6, inner, cell_id, config.FROM_SERVER, ispropset=True))
            except Exception:  # noqa: BLE001
                pass
        log(f"  → [CHAT] {p.char_name!r} left cell {cell_id} — told {len(others)} member(s)")


# ── Payload builders ──────────────────────────────────────────────────────────
def chat_payload(chat_id, body):
    return struct.pack("<HHH", config.CHAT_PAYLOAD_MAGIC, 0, chat_id) + body


def channel_data_blob(name, subject, creator, password, protected,
                      persistent, autodelete, hidden, creator_pid, publish="SC"):
    b = str_field(publish)
    b += str_field(name)
    b += str_field(subject)
    b += str_field(creator)
    b += str_field(password)
    b += struct.pack("<B", 1 if protected else 0)
    b += struct.pack("<B", 1 if persistent else 0)
    b += struct.pack("<B", 1 if autodelete else 0)
    b += struct.pack("<B", 1 if hidden else 0)
    b += struct.pack("<I", creator_pid)
    return b


def channel_info(cell_id, channel_blob, ticket=0):
    body = bytes_field(channel_blob)
    body += struct.pack("<I", cell_id)
    body += struct.pack("<I", ticket)
    return chat_payload(config.CHAT_CHANNEL_INFO, body)


def channel_joined(cell_id, ticket, option=0):
    body = struct.pack("<I", cell_id) + struct.pack("<I", ticket) + struct.pack("<H", option)
    return chat_payload(config.CHAT_CHANNEL_JOINED, body)


def channel_left(cell_id, ticket, option=0):
    """Template 10 Left — same shape as Joined (9) {cell_id, ticket_id, option u16}. On a known cell
    the client queues event 11 (left). [known, T 1000e4a0]"""
    body = struct.pack("<I", cell_id) + struct.pack("<I", ticket) + struct.pack("<H", option)
    return chat_payload(config.CHAT_CHANNEL_LEFT, body)


def status_reply(cell_id, ticket, result_id=0):
    """Template 11 StatusReply {cell_id, ticket_id, result_id} — all three are read as u32 (UNLONG
    accessor, T 1000ef30 case 11). result_id was packed as u16 before 2026-10-07; joins still
    completed live with 0 from the 2-byte-short body, but non-zero codes need the full u32. The client
    sends its own StatusReply in this same 12-byte shape. [known]"""
    body = struct.pack("<III", cell_id, ticket, result_id)
    return chat_payload(config.CHAT_STATUS_REPLY, body)


def reply(message_id, inner_data, cell_id, from_id, ispropset=True):
    body = struct.pack("<H", message_id)
    body += bytes_field(inner_data)
    body += struct.pack("<I", cell_id)
    body += struct.pack("<I", from_id)
    body += struct.pack("<B", 1 if ispropset else 0)
    return chat_payload(config.CHAT_REPLY, body)


def inner_user_info(perm_id, cell_id, nick):
    b = struct.pack("<H", 5)            # lobby type 5 = ChatUserInfo, no full header
    b += struct.pack("<I", perm_id)
    b += struct.pack("<I", cell_id)
    b += str_field(nick)
    return b


def netmsg(type_num, values):
    """A full NETMSG PropertySet (type u16 + body) for a template-3 relay's `data`."""
    return struct.pack("<H", type_num) + codec.encode_body(type_num, values)


def inner_user_left(perm_id, cell_id):
    """lobby type 6 = UserLeftChannel {perm_id, cell_id} (docs/LOBBY_PROTOCOL.md §3.5).
    ⚠️ INFERRED — only inner type 5 is live-confirmed. If members never disappear from the list,
    this id is wrong; it is cosmetic, so drop it rather than let it block join/broadcast."""
    return struct.pack("<H", 6) + struct.pack("<I", perm_id) + struct.pack("<I", cell_id)


# ── Dynamic cells (minigame table channels) ───────────────────────────────────
# Cells created at runtime must be published on every UC connection — the client rejects a join of
# an unpublished cell (StatusReply 2) and silently drops its chat. Late joiners get them in
# send_initial_reply.
_extra_cells = {}            # cell_id -> name


def _cell_blob(name, subject=""):
    return channel_data_blob(name=name, subject=subject, creator="Server", password=None,
                             protected=False, persistent=False, autodelete=True, hidden=True,
                             creator_pid=config.FROM_SERVER)


def publish_cell(cell_id, name, uc_conns):
    _extra_cells[cell_id] = name
    frame = channel_info(cell_id, _cell_blob(name), ticket=0)
    sent = 0
    for c in uc_conns:
        try:
            c.send_chat(frame)
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    log(f"  → [CHAT] published cell {cell_id} {name!r} on {sent} UC connection(s)")


# ── Handlers (operate on a Conn) ──────────────────────────────────────────────
def send_initial_reply(conn):
    """Push the channel list the instant the chat handshake completes.

    The zone cells (16..31) MUST be published here even though nobody browses them: the client's
    tincat3 CellManager rejects a join of any cell missing from its ChannelInfo-fed registry with
    StatusReply(status=2) and then silently discards every chat line relayed on that cell — the
    LOCAL-chat black hole root-caused 2026-08-02 (see config.ZONE_CHANNELS)."""
    channels = config.DEFAULT_CHANNELS + config.ZONE_CHANNELS
    for cell_id, name, subject, creator, creator_id, protected in channels:
        blob = channel_data_blob(
            name=name, subject=subject, creator=creator, password=None,
            protected=protected, persistent=True, autodelete=False,
            hidden=False, creator_pid=creator_id)
        conn.send_chat(channel_info(cell_id, blob, ticket=0))
    for cell_id, name in list(_extra_cells.items()):
        conn.send_chat(channel_info(cell_id, _cell_blob(name), ticket=0))
    log(f"  → [CHAT] pushed {len(channels) + len(_extra_cells)} ChannelInfo on connect "
        f"({len(config.DEFAULT_CHANNELS)} lobby + {len(config.ZONE_CHANNELS)} zone)")


def handle_frame(conn, payload):
    if len(payload) < 6:
        log("  [CHAT] runt chat frame"); return
    _magic, _type, chat_id = struct.unpack_from("<HHH", payload, 0)
    body = payload[6:]
    log(f"  [CHAT] ← chat frame id={chat_id}")
    if chat_id == config.CHAT_CREATE_CHANNEL:
        # Template 7 requestCreateCell {data, ticket_id}. Success is reported ONLY by publishing the
        # new cell (template 0); on this kind-3 ticket a StatusReply handles only 0x11 (the client's
        # failure 0x8C) and drops every other code. Until a channel-creation feature exists, refuse
        # (L26) so the client shows the failure instead of waiting forever. [inferred, T 10017640]
        r = BinaryReader(body); _data = r.blob()
        ticket = r.u32() if r.remaining() >= 4 else 0
        conn.send_chat(status_reply(0, ticket, 0x11))
        log("  → [CHAT] create channel refused: StatusReply(result 0x11)")
    elif chat_id == config.CHAT_MESSAGE:
        _handle_message(conn, body)
    else:
        # Unknown chat-magic id. Dump the body so the next live run identifies it instead of us
        # guessing — chat ids are a small enum separate from the NETMSG numbering, and the only
        # cited source (S2Library ChatPayloads.cs) is not in this tree.
        # Seen live 2026-07-27: id=11, 12-byte body, 24x per session, always in pairs right after
        # a channel join. Our CHAT_STATUS_REPLY is also 11 but that is server→client, so this is
        # either a different meaning in the client→server direction or a gap in our enum.
        # chat id 11 = StatusReply, and it is BIDIRECTIONAL — the client answers our
        # ChannelJoined/StatusReply with one of its own. [PROVEN 2026-07-27: the middle u32 matches
        # the ticket_id of the join it answers, 1 and 2.]
        #     {cell_id u32, ticket_id u32, status u32}   status 0 = ok, non-zero = the client
        #     rejected what we sent (we saw 2 while echoing a bogus cell_id=0).
        if chat_id == config.CHAT_STATUS_REPLY and len(body) >= 12:
            cell_id, tkt, status = struct.unpack_from("<III", body, 0)
            verdict = "OK" if status == 0 else f"REJECTED (status={status})"
            log(f"  [CHAT] ← StatusReply from client: cell={cell_id} ticket={tkt} → {verdict}")
            return
        log(f"  [CHAT] (no handler for chat id {chat_id}) — {len(body)}B body:")
        log(hex_dump(body))


def _handle_message(conn, body):
    # ⚠️ This layout is [HYPOTHESIS]. Chat text never reached the server before 2026-08-01 (the
    # client dropped every message internally — see config.WORLD_CHAT_CHANNELS), so it has never
    # been validated against a real frame. The actual encoder is tincat3's ChatChannelManager
    # (UserCommConnection::SendChat@0x0047ede0 → manager vtbl+0x1c), not SADK.exe, so it could not
    # be settled statically here. Both branches below dump the raw bytes on the FIRST message of a
    # session, so one live test settles the format either way.
    try:
        r = BinaryReader(body)
        _module_id = r.u16(); message_id = r.u16(); _except = r.u32()
        data = r.blob(); cell_id = r.u32()
    except Exception as e:  # noqa: BLE001
        log(f"  [CHAT] ⚠ COULD NOT PARSE ChatMessage ({e}) — {len(body)}B raw body follows; the "
            f"assumed layout {{module u16, msg u16, except u32, data blob, cell u32}} is wrong:")
        log(hex_dump(body))
        return
    if not getattr(conn, "_chat_msg_seen", False):
        conn._chat_msg_seen = True
        log(f"  [CHAT] ⭐ FIRST chat message parsed: msg_id={message_id} cell={cell_id} "
            f"data={data[:64]!r} — raw {len(body)}B:")
        log(hex_dump(body))
    p = players.of(conn)
    if message_id == 30:
        _handle_whisper(conn, p, data or b"")
        return
    targets = _roster_members(cell_id)              # already one per player
    if not any(players.of(c).perm_id == p.perm_id for c in targets):
        targets.append(conn)           # author not rostered — still echo their own line back
    # ⚠️ from_id was FROM_SERVER here until 2026-07-27. Using the SPEAKER's perm_id is the natural
    # reading of the field and is what lets the client attribute the line, but it is INFERRED —
    # if lines show up unattributed or as the wrong player, put FROM_SERVER back and carry the
    # speaker inside `data` instead. ER: 2026-07-27_channel-roster-and-chat-broadcast.md
    frame = reply(message_id, data or b"", cell_id, p.perm_id, ispropset=True)
    sent = 0
    for c in targets:
        try:
            c.send_chat(frame)
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    log(f"  → [CHAT] <{p.char_name}> relayed in cell {cell_id} to {sent} member(s)")


def handle_join_channel(conn, fields, ticket):
    """JoinChatChannel(17) arrives lobby-magic; replies are chat-magic."""
    cell_id = fields.get("cell_id", fields.get("CellId", 1))
    option = fields.get("option", fields.get("Option", 0))
    # ⛔ REFUTED 2026-08-01 — "cell_id=0 means the client is asking the SERVER to assign" was WRONG.
    # The client joins the id it looked up in the chat-channel map it built from EnterWorld(1000)
    # (HandleEnterWorld: map[0xFF] → JoinChannel). Our EnterWorld body was encoded as a TinCat
    # PropertySet while the client parses msg 1000 as a bit-packed LobbyMessage, so it read
    # ChatChannelsCount as 0, left the map empty, and `map[0xFF]` default-inserted **0** — the id it
    # then tried to join. Fixing the encoding (config.WORLD_CHAT_CHANNELS) makes real ids arrive.
    # A 0 here now means the EnterWorld channel list did NOT land, so say so loudly instead of
    # quietly papering over it — but still confirm a usable cell so the session stays alive.
    if not cell_id:
        cell_id = config.GLOBAL_CHAT_CELL
        log(f"  [CHAT] ⚠ join asked for cell 0 — the client's chat-channel map is EMPTY, i.e. our "
            f"EnterWorld(1000) channel list did not parse. Confirming cell {cell_id} to keep the "
            f"session usable, but chat sends will be dropped client-side until that is fixed.")
    conn.send_chat(channel_joined(cell_id, ticket, option))
    conn.send_chat(status_reply(cell_id, ticket, 0))
    p = players.of(conn)
    others = _roster_join(cell_id, conn)
    mine = inner_user_info(p.perm_id, cell_id, p.char_name)
    # 1. the joiner learns about themselves — the one frame proven to work (they appear in their
    #    own member list), so everything below is the SAME frame to a different socket.
    conn.send_chat(reply(5, mine, cell_id, config.FROM_SERVER, ispropset=True))
    # 2. the joiner learns about everyone already here …
    for other in others:
        op = players.of(other)
        conn.send_chat(reply(5, inner_user_info(op.perm_id, cell_id, op.char_name),
                             cell_id, config.FROM_SERVER, ispropset=True))
    # 3. … and everyone already here learns about the joiner.
    for other in others:
        try:
            other.send_chat(reply(5, mine, cell_id, config.FROM_SERVER, ispropset=True))
        except Exception:  # noqa: BLE001
            pass
    log(f"  → [CHAT] JoinChatChannel cell={cell_id}: {p.char_name!r} joined; "
        f"exchanged ChatUserInfo with {len(others)} existing member(s)")


def _uc_conn_of(perm_id):
    """The live UC/chat connection of a player (newest), found through the cell rosters."""
    with _roster_lock:
        members = [c for lst in _roster.values() for c in lst]
    found = [c for c in members if getattr(c, "alive", False) and players.of(c).perm_id == perm_id]
    return found[-1] if found else None


def _handle_whisper(conn, p, data):
    """WhisperChatMessage (30) arrives as template 2 on cell 1 {mode 3|4, txt, cell_id 1, from_id,
    perm_id = target} (T 10017100). The client has NO receive case for 30: a whisper is delivered as
    NETMSG 3 PrivateChatMessage {mode, txt, cell_id, from_id, to_id, from_name} inside template 3, to
    the target only, and echoed to the sender so the outgoing line shows (from_id == local perm).
    [inferred, S 004810a0] An offline target is dropped silently (L22): the client has no error path."""
    try:
        w = codec.decode_body(30, data[2:])
    except Exception as e:  # noqa: BLE001
        log(f"  [CHAT] ⚠ could not parse whisper ({e}):")
        log(hex_dump(data))
        return
    target = w.get("perm_id", 0)
    msg = netmsg(3, {"mode": w.get("mode", 3), "txt": w.get("txt") or "", "cell_id": 1,
                     "from_id": p.perm_id, "to_id": target, "from_name": p.char_name})
    frame = reply(3, msg, 1, p.perm_id, ispropset=True)
    dest = _uc_conn_of(target)
    if dest is None:
        log(f"  [CHAT] whisper {p.char_name!r} → {target}: target offline, dropped (L22)")
        return
    dest.send_chat(frame)
    if dest is not conn:
        conn.send_chat(frame)                       # the sender's own outgoing line
    log(f"  → [CHAT] whisper {p.char_name!r} → {players.of(dest).char_name!r} delivered")


def handle_leave_channel(conn, fields, ticket):
    """RequestLeaveChannel (259) {cell_id, ticket_id = a CellManager ticket, from_id} arrives on the
    NETMSG layer of the UC connection, but its ticket is a CellManager one: a NETMSG Result(42) is
    ignored there and the leave never completes. Complete it like a join, with template 10 Left +
    template 11 StatusReply(0), and tell the other members with NETMSG 6. [known, T 10016f10 /
    T 10017640]"""
    cell_id = fields.get("cell_id", 0) or 0
    p = players.of(conn)
    with _roster_lock:
        members = _roster.get(cell_id, [])
        if conn in members:
            members.remove(conn)
    conn.send_chat(channel_left(cell_id, ticket))
    conn.send_chat(status_reply(cell_id, ticket, 0))
    others = _roster_members(cell_id)
    for c in others:
        if players.of(c).perm_id == p.perm_id:
            continue                                # the same player on another socket
        try:
            c.send_chat(reply(6, inner_user_left(p.perm_id, cell_id), cell_id, config.FROM_SERVER,
                              ispropset=True))
        except Exception:  # noqa: BLE001
            pass
    log(f"  → [CHAT] {p.char_name!r} left cell {cell_id} (Left + StatusReply 0); told {len(others)} member(s)")
