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

from . import config, players
from .log import hex_dump, log
from .tincat import BinaryReader, str_field, bytes_field


# ── Channel roster ────────────────────────────────────────────────────────────
# Who is in which chat cell, so joins/messages/leaves can be fanned out to the other members.
# Before 2026-07-27 there was no roster at all: a joiner was told only about *themselves* and a
# chat line was echoed only back to its author, so the lobby was completely asocial even with two
# clients in the same channel.
_roster_lock = threading.Lock()
_roster: dict = {}          # cell_id -> list[Conn]  (UC/chat connections)


def _roster_join(cell_id, conn):
    """Add conn to the cell; return the OTHER live members."""
    with _roster_lock:
        members = _roster.setdefault(cell_id, [])
        if conn not in members:
            members.append(conn)
        return [c for c in members if c is not conn and getattr(c, "alive", False)]


def _roster_members(cell_id):
    with _roster_lock:
        return [c for c in _roster.get(cell_id, []) if getattr(c, "alive", False)]


def on_conn_closed(conn):
    """A UC socket went away: drop it from every cell and tell the remaining members."""
    left = []
    with _roster_lock:
        for cell_id, members in _roster.items():
            if conn in members:
                members.remove(conn)
                left.append(cell_id)
    if not left:
        return
    p = players.of(conn)
    for cell_id in left:
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


def status_reply(cell_id, ticket, result_id=0):
    body = struct.pack("<I", cell_id) + struct.pack("<I", ticket) + struct.pack("<H", result_id)
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


def inner_user_left(perm_id, cell_id):
    """lobby type 6 = UserLeftChannel {perm_id, cell_id} (docs/LOBBY_PROTOCOL.md §3.5).
    ⚠️ INFERRED — only inner type 5 is live-confirmed. If members never disappear from the list,
    this id is wrong; it is cosmetic, so drop it rather than let it block join/broadcast."""
    return struct.pack("<H", 6) + struct.pack("<I", perm_id) + struct.pack("<I", cell_id)


# ── Handlers (operate on a Conn) ──────────────────────────────────────────────
def send_initial_reply(conn):
    """Push the default channel list the instant the chat handshake completes."""
    for cell_id, name, subject, creator, creator_id, protected in config.DEFAULT_CHANNELS:
        blob = channel_data_blob(
            name=name, subject=subject, creator=creator, password=None,
            protected=protected, persistent=True, autodelete=False,
            hidden=False, creator_pid=creator_id)
        conn.send_chat(channel_info(cell_id, blob, ticket=0))
    log(f"  → [CHAT] pushed {len(config.DEFAULT_CHANNELS)} ChannelInfo on connect")


def handle_frame(conn, payload):
    if len(payload) < 6:
        log("  [CHAT] runt chat frame"); return
    _magic, _type, chat_id = struct.unpack_from("<HHH", payload, 0)
    body = payload[6:]
    log(f"  [CHAT] ← chat frame id={chat_id}")
    if chat_id == config.CHAT_CREATE_CHANNEL:
        r = BinaryReader(body); _data = r.blob()
        ticket = r.u32() if r.remaining() >= 4 else 0
        conn.send_chat(status_reply(3, ticket, 0))
        log("  → [CHAT] StatusReply(create channel) OK")
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
    try:
        r = BinaryReader(body)
        _module_id = r.u16(); message_id = r.u16(); _except = r.u32()
        data = r.blob(); cell_id = r.u32()
    except Exception as e:  # noqa: BLE001
        log(f"  [CHAT] failed to parse ChatMessage: {e}"); return
    p = players.of(conn)
    targets = _roster_members(cell_id)
    if conn not in targets:            # not rostered (never joined / stale) — still show the author
        targets.append(conn)
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
    # ⚠️ EXPERIMENT 2026-07-27 — resolve cell_id 0 to a real advertised channel.
    # The client sends RequestJoinChannel with cell_id=0 (twice, tickets 1 and 2) even though we
    # advertised cells 1 and 2 via ChannelInfo, i.e. it is asking the SERVER to assign. We used to
    # echo 0 straight back in ChannelJoined + StatusReply, confirming membership of a channel that
    # does not exist — and the client answered each one with chat-magic id 11 =
    # StatusReply{cell_id=0, ticket_id=N, status=2}, then never transmitted a single chat frame.
    # (Layout PROVEN by matching the middle field against the join ticket_ids, 1 and 2.)
    # status != 0 is read as a failure report; assigning the Nth advertised channel to the Nth join
    # is the natural reading, since the request carries no name/password to discriminate on.
    # FALSIFIABLE: if this is right the client should answer status=0 and chat should start
    # flowing. If status stays 2, cell assignment is not the problem — revert and read the client's
    # StatusReply handler instead.
    if not cell_id:
        seen = getattr(conn, "_chan_joins", 0)
        conn._chan_joins = seen + 1
        channels = config.DEFAULT_CHANNELS
        cell_id = channels[seen][0] if seen < len(channels) else channels[-1][0]
        log(f"  [CHAT] join asked for cell 0 → assigning advertised cell {cell_id} "
            f"({channels[min(seen, len(channels) - 1)][1]!r})")
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
