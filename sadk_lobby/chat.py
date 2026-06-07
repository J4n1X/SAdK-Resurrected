"""
Chat / UC (second-connection) sub-protocol.

The chat connection uses a different app-payload prefix than the lobby:
    Magic(0x0062) + Type(u16=0) + Id(u16=chatType)
Source of truth: S2Library/Protocol/ChatPayloads.cs (ChatPayloadPrefix).

Builders return ready-to-send bytes (wrap in a TinCat application frame via
conn.send_chat). Frame handlers take the owning Conn and use conn.send_chat().
"""
import struct

from . import config
from .log import log
from .tincat import BinaryReader, str_field, bytes_field


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
        log(f"  [CHAT] (no handler for chat id {chat_id})")


def _handle_message(conn, body):
    try:
        r = BinaryReader(body)
        _module_id = r.u16(); message_id = r.u16(); _except = r.u32()
        data = r.blob(); cell_id = r.u32()
    except Exception as e:  # noqa: BLE001
        log(f"  [CHAT] failed to parse ChatMessage: {e}"); return
    conn.send_chat(reply(message_id, data or b"", cell_id, config.FROM_SERVER, ispropset=True))
    log(f"  → [CHAT] echoed ChatMessage in cell {cell_id}")


def handle_join_channel(conn, fields, ticket):
    """JoinChatChannel(17) arrives lobby-magic; replies are chat-magic."""
    cell_id = fields.get("cell_id", fields.get("CellId", 1))
    option = fields.get("option", fields.get("Option", 0))
    conn.send_chat(channel_joined(cell_id, ticket, option))
    conn.send_chat(status_reply(cell_id, ticket, 0))
    inner = inner_user_info(config.TEST_PERM_ID, cell_id, config.TEST_CHAR_NAME)
    conn.send_chat(reply(5, inner, cell_id, config.FROM_SERVER, ispropset=True))
    log(f"  → [CHAT] JoinChatChannel cell={cell_id}: Joined + StatusReply + ChatUserInfo")
