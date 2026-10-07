"""
Chat behaviour (offline): whispers go to the target only as NETMSG 3 (plus the sender's echo),
RequestLeaveChannel(259) completes on the CellManager layer, channel creation is refused with 0x11,
StatusReply carries a u32 result. See sadk_lobby/chat.py and docs/message-catalog.md (UC/chat).

Run:  python tests/test_chat.py
"""
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sadk_lobby import chat, codec, config, dispatch, players  # noqa: E402
from sadk_lobby.tincat import bytes_field  # noqa: E402


class UC:
    def __init__(self, name):
        self.player = players.resolve_by_username(name)
        self.alive = True
        self.chat = []          # (chat_id, body)
        self.app = []

    def send_chat(self, payload):
        _magic, _t, chat_id = struct.unpack_from("<HHH", payload, 0)
        self.chat.append((chat_id, payload[6:]))

    def send_app(self, t, body):
        self.app.append(t)

    def ok(self, ticket):
        self.app.append(42)

    def relays(self):
        """(message_id, inner NETMSG fields, from_id) of every template-3 relay received."""
        out = []
        for cid, body in self.chat:
            if cid != config.CHAT_REPLY:
                continue
            mid = struct.unpack_from("<H", body, 0)[0]
            blen = struct.unpack_from("<I", body, 2)[0]
            data = body[6:6 + blen]
            cell, frm = struct.unpack_from("<II", body, 6 + blen)
            out.append((mid, codec.decode_body(mid, data[2:]), frm))
        return out


def _cell_message(message_id, data, cell_id):
    body = struct.pack("<HHi", 0x62, message_id, -1) + bytes_field(data) + struct.pack("<I", cell_id)
    body += b"\x01\x01"
    return struct.pack("<HHH", config.CHAT_PAYLOAD_MAGIC, 0, config.CHAT_MESSAGE) + body


def _join(conn, cell):
    chat.handle_join_channel(conn, {"cell_id": cell}, 1)
    conn.chat.clear()


def test_whisper_reaches_target_only():
    a, b, c = UC("chat_anna"), UC("chat_bert"), UC("chat_carl")
    for x in (a, b, c):
        _join(x, 1)
    for x in (a, b, c):
        x.chat.clear()
    w = struct.pack("<H", 30) + codec.encode_body(30, {"mode": 3, "txt": "psst", "cell_id": 1,
                                                       "from_id": a.player.perm_id,
                                                       "perm_id": b.player.perm_id})
    chat.handle_frame(a, _cell_message(30, w, 1))
    got = b.relays()
    assert len(got) == 1 and got[0][0] == 3, got
    f = got[0][1]
    assert (f["txt"], f["from_id"], f["to_id"], f["from_name"]) == \
        ("psst", a.player.perm_id, b.player.perm_id, "chat_anna"), f
    assert [r[0] for r in a.relays()] == [3]             # sender echo
    assert c.relays() == []                               # nobody else
    for x in (a, b, c):
        chat.on_conn_closed(x)
    print("whisper → NETMSG 3 to the target + echo only OK")


def test_leave_completes_on_cellmanager():
    a, b = UC("chat_dora"), UC("chat_emil")
    _join(a, 1)
    _join(b, 1)
    a.chat.clear()
    b.chat.clear()
    dispatch.dispatch_lobby(a, 259, {"cell_id": 1, "ticket_id": 77, "from_id": a.player.perm_id})
    assert [cid for cid, _ in a.chat] == [config.CHAT_CHANNEL_LEFT, config.CHAT_STATUS_REPLY]
    assert struct.unpack("<III", a.chat[1][1]) == (1, 77, 0)       # u32 result
    assert 42 not in a.app                                         # no NETMSG Result
    assert [(m, f["perm_id"]) for m, f, _ in b.relays()] == [(6, a.player.perm_id)]
    chat.on_conn_closed(b)
    print("leave → Left + StatusReply(u32 0), others get NETMSG 6 OK")


def test_create_channel_refused():
    a = UC("chat_finn")
    body = bytes_field(b"\x00" * 8) + struct.pack("<I", 55)
    chat.handle_frame(a, struct.pack("<HHH", config.CHAT_PAYLOAD_MAGIC, 0,
                                     config.CHAT_CREATE_CHANNEL) + body)
    assert a.chat == [(config.CHAT_STATUS_REPLY, struct.pack("<III", 0, 55, 0x11))]
    print("create channel → StatusReply 0x11 OK")


if __name__ == "__main__":
    test_whisper_reaches_target_only()
    test_leave_completes_on_cellmanager()
    test_create_channel_refused()
    print("\nAll chat tests PASSED")
