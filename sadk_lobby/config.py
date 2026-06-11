"""
Static configuration & protocol constants for the SaDK lobby stub server.

Reverse-engineered from SADK.exe + tincat3.dll. Values tagged [PROVEN] are backed by
a binary address and live read-only evidence; values tagged [TODO] are unverified.
Anything that affects the wire format must be re-validated against the real client
before it is changed.

There are NO feature flags here. Everything the stub knows how to do, it does by
default. (Historically half of this file was `⛔ off-by-default` toggles; that bloat
is gone — see HARNESS.md.)
"""
import os

# ── Package paths ─────────────────────────────────────────────────────────────
PKG_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_DIR  = os.path.dirname(PKG_DIR)
DATA_DIR  = os.path.join(PKG_DIR, "data")
MSGDEFS_PATH = os.path.join(DATA_DIR, "msgdefs.ini")   # the game's own NETMSG schema, bundled

LOG_FILE = os.path.join(REPO_DIR, "tincat_server.log")
BIN_DIR  = os.path.join(REPO_DIR, "sadk_captures")

# ── Listener ports [PROVEN] ───────────────────────────────────────────────────
LOBBY_PORT = 7070   # main lobby connection
UC_PORT    = 7071   # UC/chat second connection (MUST differ from lobby port)
WORLD_PORT = 5479   # village/world third connection

# IP the stub ADVERTISES to the client as the address to dial back (chat/village servers).
# Same machine -> 127.0.0.1. For a VM test (game in the VM, stub on the host) set
# SADK_ADVERTISE_IP to the host's IP as seen FROM the VM. Listeners always bind 0.0.0.0.
ADVERTISED_IP = os.environ.get("SADK_ADVERTISE_IP", "192.168.1.130")

# ── Player accounts ───────────────────────────────────────────────────────────
# Multiple clients can log in as DISTINCT players (host + joiner). PLAYERS[0] is the
# default/test identity and the fallback for unknown logins. Any other username
# auto-registers as a fresh player on first login (players.py). Appearance is shared
# (NICKNAME_DATA) for now — [TODO] per-player appearance.
TEST_USERNAME  = "test"
TEST_PASSWORD  = "test"     # raw, SHA-512 hashed on use
TEST_PERM_ID   = 1
TEST_CHAR_ID   = 1
TEST_CHAR_NAME = "Testler"

PLAYERS = [
    {"username": TEST_USERNAME, "perm_id": TEST_PERM_ID,
     "char_id": TEST_CHAR_ID, "char_name": TEST_CHAR_NAME},   # PLAYERS[0] = default
    {"username": "test2", "perm_id": 2, "char_id": 2, "char_name": "Siedler"},
]

# Avatar data blob from the AdK emulator (LobbyProcessor._nicknameData).
NICKNAME_DATA = bytes.fromhex(
    "000000003900000000000000000000000000000000000000"
    "a2000000785edbc9c8800cd880b8842195a1184c1631e000"
    "ff819891094508668e438300886265604788beb8ce644b0c"
    "8d0d1c05004a9b0ff3"
)

# GameServerData(170) wire layout = ServerInfoOld (the canonical msgdefs.ini schema:
# u16 counts + spectators + subtype + room_id). [PROVEN] tincat3 rejects the emulator's
# "adk" byte-count variant. There is no other layout; this is fixed, not a toggle.

# ── MP server browser match key [PROVEN, s28 RPM] ─────────────────────────────
# The client enables a village entry's Enter button iff some list entry's roomId(+0x30)
# == DAT_0087aed8 (the client's LobbyClient/ProtocolVersion, LobbyClient_LoadProtocolVersion
# @0x465380, default -1 if the ini key is absent). The stub advertises roomId as the FIRST
# field of the 170 ServerDataBlock (BIG-ENDIAN u32); it MUST equal the client's
# ProtocolVersion. Live value was 1000. If an install reports a different ProtocolVersion,
# set this to match (read DAT_0087aed8 live, or the client's LobbyClient ini).
LOBBY_PROTOCOL_VERSION = 1000

# ── TinCat transport constants [PROVEN] ───────────────────────────────────────
MAGIC       = 0xDABAFBEF
FROM_CLIENT = 0xEFFFFFEE
FROM_SERVER = 0xEFFFFFCC
PREFIX_SIZE = 0x1C          # 28-byte TinCat header

PAYLOAD_MAGIC = 0x26B6      # the SINGLE app-payload magic for the whole client (lobby + UC + village)

# TinCat frame types (header Type field)
MSG_HANDSHAKE_CONNECT   = 3
MSG_HANDSHAKE_CONNECTED = 5
MSG_APPLICATION         = 2
MSG_PING                = 11

# Handshake payload geometry [PROVEN]
HANDSHAKE_USERNAME_SIZE = 0x20   # 32
HANDSHAKE_PASSWORD_SIZE = 0x08   # 8
HANDSHAKE_SIZE          = 0x34   # 52
REPLY_PASSWORD          = bytes([0x2D, 0, 0, 0, 0, 0, 0, 0])

# ── Chat (second-connection) protocol [PROVEN] ────────────────────────────────
# Chat payload prefix: Magic(0x0062) + Type(u16=0) + Id(u16=chatType).
CHAT_PAYLOAD_MAGIC = 0x0062

CHAT_CHANNEL_INFO   = 0
CHAT_MESSAGE        = 2
CHAT_REPLY          = 3
CHAT_CREATE_CHANNEL = 7
CHAT_CHANNEL_JOINED = 9
CHAT_STATUS_REPLY   = 11

# (cell_id, name, subject, creator, creator_id, protected)
DEFAULT_CHANNELS = [
    (1, "System", "System Channel", "Admin", 0, True),
    (2, "Lobby",  "Lobby Channel",  "Admin", 0, True),
]

# ── Village / world-entry protocol ────────────────────────────────────────────
# World entry [PROVEN, s39 screenshot-confirmed on the clean build]: leaving char-select
# into the 3D world is driven ENTIRELY by the SERVER pushing inbound EnterWorld (msg 1000).
# The user's "Betrete Welt" click sends ZERO network; the client parks at LobbyManager
# EnteringVillage(8) waiting for 1000. HandleEnterWorld calls SetState(VillageEntered=9) as
# its FIRST instruction, so a single well-framed 1000 enters the world. The stub pushes it
# on the village conn a short delay after the 153 login ACK (dispatch._h_send_token).
# Its own client-side world-login request (SendGameData(74){0x27D2}) path is dormant/dead,
# so the stub does NOT wait for it — it provides 1000 via the genuine mechanism.
VILLAGE_MSG_ENTER_WORLD = 1000    # 0x3E8 — HandleEnterWorld (server → client)
VILLAGE_SENDGAMEDATA    = 74      # 0x4A NETMSG SendGameData — the envelope that carries every
#   village/world message (1000+). [PROVEN, s35] The client's inbound bridge only routes NETMSG
#   73/74 to VillageServerConnection::HandleMessage and extracts the inner msg_type as the dispatch
#   key, so EnterWorld(1000) MUST ride a SendGameData(74) envelope. A bare 1000 frame is dropped.
WORLD_LOGIN_REQUEST_MSGTYPE = 0x27D2  # 10194 — the (dormant) client world-login request msg_type
VILLAGE_PAYLOAD_MAGIC = PAYLOAD_MAGIC  # msg 1000 rides the single 0x26B6 comm layer, same as login

ENTER_WORLD_WORLDNAME = "world1"   # must match the ServerType=4 village entry name/map
ENTER_WORLD_DELAY     = 2.0        # seconds after the village 153 ACK before pushing 1000 (settle)

# ── In-world stage (after EnterWorld 1000) ────────────────────────────────────
# [TODO — UNVERIFIED] Everything below was largely derived on the faulty no-CD build. The clean
# build renders the world at SetState(9) WITHOUT msg 1006, so 1006 is NOT confirmed as a render
# gate. These are best-effort replies to client-driven messages (not unsolicited pushes); treat
# their in-world effect as unproven until re-confirmed live on the clean build.
VILLAGE_MSG_WORLD_LOGIN_ACK = 1006        # 0x3EE — HandleWorldLoginAck; sends a "code" the client compares
WORLD_LOGIN_ACK_CODE = 0xDEADBEEF         # the value the client compares in msg 1006
VILLAGE_MSG_PONG = 0xED7                   # 3799 — HandlePongCode; our reply to the client's in-world PingCode
VILLAGE_PINGCODE_MSGTYPE = 0x2ED6          # 11990 — the client's in-world keepalive PingCode (SendGameData 74)
VILLAGE_MSG_WORLD_TICK = 1005               # 0x3ED — HandleWorldTick (sim heartbeat); 64-byte tick MEMBLOCK
