#!/usr/bin/env python3
"""
⚠️ FROZEN REFERENCE ONLY — do NOT run or maintain this file.
It is the original monolithic stub, kept solely as the byte-for-byte GOLDEN REFERENCE for
tests/test_codec_golden.py. All live behavior lives in the `sadk_lobby/` package.

SaDK TinCat Stub Server  v3
============================
Full post-login flow. Gets a player into the lobby world.

Test account (hardcoded):
  Username : test
  Password : test
  Serial   : test   (entered as the CD key / serial number in-game)

SETUP:
  1. data/lobby/config/LobbySettings.ini  →  Host = "127.0.0.1"
  2. pip install cryptography twofish
  3. python tincat_server.py
  4. Start the game and log in with username=test / password=test / serial=test
"""

import socket, struct, threading, os, sys, argparse, hashlib, time
from datetime import datetime

# ── Crypto deps ───────────────────────────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.asymmetric.ec import (
        SECP521R1, EllipticCurvePublicNumbers, generate_private_key, ECDH)
    from cryptography.hazmat.backends import default_backend
    ECDH_AVAILABLE = True
except ImportError:
    ECDH_AVAILABLE = False
    print("WARNING: pip install cryptography")

try:
    import twofish as _twofish_mod
    TWOFISH_AVAILABLE = True
except ImportError:
    TWOFISH_AVAILABLE = False
    print("WARNING: pip install twofish")

# ── Hardcoded test account ────────────────────────────────────────────────────
TEST_USERNAME   = "test"
TEST_PASSWORD   = "test"     # raw, will be SHA-512 hashed
TEST_PERM_ID    = 1
TEST_CHAR_ID    = 1
TEST_CHAR_NAME  = "Testler"  # name shown in lobby

# GameServerData (TYPE 170) has two competing wire layouts:
#   "adk"  → emulator's AdK-specific GameServerData (player counts are BYTES, no
#            spectators/subtype/roomid). This is what the AdK-targeted emulator
#            (Payloads.cs::GameServerData) actually serializes for this client.
#   "old"  → ServerInfoOld / Ghidra msgdef (uint16 counts + spectators + subtype
#            + room_id + locked_config). Matches the generic Sacred2 TinCat.
# Flip this if the server browser shows garbage / rejects the list.
# s6 (2026-06-01): the REAL tincat3.dll rejected "adk" — commLayer.log showed
# "ConnectionReal was unable to deserialize packet 170". TinCat deserializes 170 via
# PropertyDataConverter against a fixed schema (var-len fields = 4-byte len prefix;
# scalars = fixed size); the schema is ServerInfoOld (uint16 counts + spectators), so
# "adk" byte-counts desync the stream. The emulators are wrong for this client. Use "old".
GAMESERVERDATA_FORMAT = "old"

# Avatar data blob from AdK emulator (LobbyProcessor._nicknameData)
NICKNAME_DATA = bytes.fromhex(
    "000000003900000000000000000000000000000000000000"
    "a2000000785edbc9c8800cd880b8842195a1184c1631e000"
    "ff819891094508668e438300886265604788beb8ce644b0c"
    "8d0d1c05004a9b0ff3"
)

# ── Protocol constants ────────────────────────────────────────────────────────
MAGIC          = 0xDABAFBEF
FROM_CLIENT    = 0xEFFFFFEE
FROM_SERVER    = 0xEFFFFFCC
PREFIX_SIZE    = 0x1C        # 28 bytes

PAYLOAD_MAGIC  = 0x26B6

MSG_HANDSHAKE_CONNECT    = 3
MSG_HANDSHAKE_CONNECTED  = 5
MSG_APPLICATION          = 2
MSG_PING                 = 11

HANDSHAKE_USERNAME_SIZE  = 0x20   # 32 bytes
HANDSHAKE_PASSWORD_SIZE  = 0x08   # 8 bytes
HANDSHAKE_SIZE           = 0x34   # 52 bytes
REPLY_PASSWORD           = bytes([0x2D, 0, 0, 0, 0, 0, 0, 0])

PING_INTERVAL  = 0.0   # disabled — server does NOT send pings to client

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tincat_server.log")
BIN_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sadk_captures")

# ── CRC32 ─────────────────────────────────────────────────────────────────────
def _build_crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = 0xEDB88320 ^ (c >> 1) if c & 1 else c >> 1
        t.append(c)
    return t

_CRC_TABLE = _build_crc_table()

def crc32(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]) & 0xFFFFFFFF
    return crc

# ── ECDH (secp521r1) ──────────────────────────────────────────────────────────
def _der_len(n):
    if n < 0x80:   return bytes([n])
    if n < 0x100:  return bytes([0x81, n])
    return bytes([0x82, n >> 8, n & 0xFF])

def _int_to_der(v):
    if v == 0: return b'\x02\x01\x00'
    nb = (v.bit_length() + 7) // 8
    b  = v.to_bytes(nb, 'big')
    if b[0] & 0x80: b = b'\x00' + b
    return b'\x02' + _der_len(len(b)) + b

def _parse_ec_key(der):
    pos = 1
    if der[pos] & 0x80: pos += 1 + (der[pos] & 0x7F)
    else: pos += 1
    pos += 1 + 1 + der[pos+1]   # BITSTRING
    pos += 1 + 1 + der[pos+1]   # INTEGER 0x41
    assert der[pos] == 0x02; pos += 1
    xl = der[pos]; pos += 1; x = int.from_bytes(der[pos:pos+xl], 'big'); pos += xl
    assert der[pos] == 0x02; pos += 1
    yl = der[pos]; pos += 1; y = int.from_bytes(der[pos:pos+yl], 'big')
    return x, y

def _encode_keystream(x, y):
    inner = b'\x03\x02\x07\x00' + b'\x02\x01\x41' + _int_to_der(x) + _int_to_der(y)
    return b'\x30' + _der_len(len(inner)) + inner

def _encode_reply_cipher(ks, secret):
    oid     = bytes([0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x03])
    o_ks    = b'\x04' + _der_len(len(ks)) + ks
    o_sec   = b'\x04' + _der_len(len(secret)) + secret
    inner   = oid + o_ks + o_sec
    return b'\x30' + _der_len(len(inner)) + inner

def crypto_handle_login_key(key_bytes):
    if not ECDH_AVAILABLE: raise ImportError("pip install cryptography")
    x, y = _parse_ec_key(key_bytes)
    client_pub = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP521R1()).public_key(default_backend())
    server_priv = generate_private_key(SECP521R1(), default_backend())
    server_pub  = server_priv.public_key()
    agreement   = server_priv.exchange(ECDH(), client_pub)
    if len(agreement) == 65: agreement = b'\x00' + agreement
    h = hashlib.sha512(agreement).digest()
    shared = os.urandom(32)
    xored  = bytes(shared[i] ^ h[i] for i in range(32))
    pn = server_pub.public_numbers()
    ks = _encode_keystream(pn.x, pn.y)
    return _encode_reply_cipher(ks, xored), shared

def _twofish_ctr(key, iv, data):
    if not TWOFISH_AVAILABLE: raise ImportError("pip install twofish")
    tf = _twofish_mod.Twofish(key)
    counter = bytearray(iv); out = bytearray(); pos = 0
    while pos < len(data):
        ks = bytearray(tf.encrypt(bytes(counter)))
        chunk = min(16, len(data) - pos)
        for i in range(chunk): out.append(ks[i] ^ data[pos+i])
        pos += chunk
        j = 0
        while j < len(counter):
            counter[j] = (counter[j] + 1) & 0xFF
            if counter[j]: break
            j += 1
    return bytes(out)

def crypto_decrypt_cipher(cipher, shared):
    return _twofish_ctr(shared, cipher[:16], cipher[16:])

def crypto_encrypt_session_key(sk, shared):
    iv = os.urandom(16)
    return iv + _twofish_ctr(shared, iv, sk)

def decode_login_blob(blob, has_cdkey=False):
    r = {}; pos = 0
    try:
        nl = blob[pos]; pos += 1
        r['username'] = blob[pos:pos+nl].decode('ascii','replace'); pos += nl
        pl = blob[pos]; pos += 1
        pw = blob[pos:pos+pl]; pos += pl
        r['password_raw']    = pw.hex()
        r['password_sha512'] = hashlib.sha512(pw).hexdigest()
        if has_cdkey and pos + 3 <= len(blob):
            ksl = blob[pos]; pos += 1
            kp  = blob[pos]; pos += 1
            kl  = blob[pos]; pos += 1
            if ksl == 1 and kp == 1 and kl == 16 and pos + kl <= len(blob):
                r['cd_key'] = blob[pos:pos+kl].decode('ascii','replace')
    except Exception as e:
        r['_err'] = str(e)
    return r

# ── Payload serialization helpers ─────────────────────────────────────────────
def _str_field(s):
    if s is None: return struct.pack('<i', 0)
    b = (s + '\x00').encode('iso-8859-15')
    return struct.pack('<i', len(b)) + b

def _bytes_field(b):
    if b is None: return struct.pack('<i', 0)
    return struct.pack('<i', len(b)) + b

# ── Frame building ────────────────────────────────────────────────────────────
def build_frame(from_id, to_id, msg_type, payload, unknown1=0):
    hdr = struct.pack('<IIIIIII',
        MAGIC, from_id, to_id, msg_type, unknown1, len(payload), crc32(payload))
    return hdr + payload

def build_handshake_payload(conn_id, username_raw, unknown1):
    u = (username_raw + b'\x00' * HANDSHAKE_USERNAME_SIZE)[:HANDSHAKE_USERNAME_SIZE]
    return struct.pack('<II', 0xDABAFBEF, conn_id) + u + REPLY_PASSWORD + struct.pack('<i', unknown1)

def app_payload(ptype, body):
    return struct.pack('<HHH', PAYLOAD_MAGIC, ptype, ptype) + body

# ── Chat (second-connection) protocol ─────────────────────────────────────────
# The chat/UC connection uses a DIFFERENT wire prefix than the lobby connection.
#   Lobby payload prefix : Magic(0x26B6) + Type1(u16) + Type2(u16)
#   Chat  payload prefix : Magic(0x0062) + Type(u16=0) + Id(u16=chatType)
# Source of truth: S2Library/Protocol/ChatPayloads.cs (ChatPayloadPrefix).
CHAT_PAYLOAD_MAGIC = 0x0062

# ChatTypes enum (ChatPayloads.cs)
CHAT_CHANNEL_INFO   = 0
CHAT_MESSAGE        = 2
CHAT_REPLY          = 3
CHAT_CREATE_CHANNEL = 7
CHAT_CHANNEL_JOINED = 9
CHAT_STATUS_REPLY   = 11

# Default channels (Channels.cs seeds these two, both protected, creator "Admin").
DEFAULT_CHANNELS = [
    # (cell_id, name,     subject,          creator, creator_id, protected)
    (1, "System", "System Channel", "Admin", 0, True),
    (2, "Lobby",  "Lobby Channel",  "Admin", 0, True),
]

def chat_payload(chat_id, body):
    # ChatPayloadPrefix.Serialize: Magic(u16), Type(u16=0), Id(u16)
    return struct.pack('<HHH', CHAT_PAYLOAD_MAGIC, 0, chat_id) + body

def _channel_data_blob(name, subject, creator, password, protected,
                       persistent, autodelete, hidden, creator_pid, publish="SC"):
    # ChannelData.Serialize (ChatPayloads.cs)
    b  = _str_field(publish)
    b += _str_field(name)
    b += _str_field(subject)
    b += _str_field(creator)
    b += _str_field(password)
    b += struct.pack('<B', 1 if protected else 0)
    b += struct.pack('<B', 1 if persistent else 0)
    b += struct.pack('<B', 1 if autodelete else 0)
    b += struct.pack('<B', 1 if hidden else 0)
    b += struct.pack('<I', creator_pid)
    return b

def chat_channel_info(cell_id, channel_blob, ticket=0):
    # ChannelInfo (id=0): Data(blob) + CellId(u32) + TicketId(u32)
    body  = _bytes_field(channel_blob)
    body += struct.pack('<I', cell_id)
    body += struct.pack('<I', ticket)
    return chat_payload(CHAT_CHANNEL_INFO, body)

def chat_channel_joined(cell_id, ticket, option=0):
    # ChannelJoined (id=9): CellId + TicketId + Option(u16)
    body  = struct.pack('<I', cell_id) + struct.pack('<I', ticket) + struct.pack('<H', option)
    return chat_payload(CHAT_CHANNEL_JOINED, body)

def chat_status_reply(cell_id, ticket, result_id=0):
    # StatusReply (id=11): CellId + TicketId + ResultId(u16)
    body  = struct.pack('<I', cell_id) + struct.pack('<I', ticket) + struct.pack('<H', result_id)
    return chat_payload(CHAT_STATUS_REPLY, body)

def chat_reply(message_id, inner_data, cell_id, from_id, ispropset=True):
    # ChatReply (id=3): MessageId(u16) + Data(blob) + CellId(u32) + FromId(u32) + Ispropset(bool)
    body  = struct.pack('<H', message_id)
    body += _bytes_field(inner_data)
    body += struct.pack('<I', cell_id)
    body += struct.pack('<I', from_id)
    body += struct.pack('<B', 1 if ispropset else 0)
    return chat_payload(CHAT_REPLY, body)

def chat_inner_user_info(perm_id, cell_id, nick):
    # ChatUserInfo (lobby type 5) serialized WITHOUT full header (fullHeader=false):
    #   Type2(u16=5) + PermId(u32) + CellId(u32) + Nick(str)
    b  = struct.pack('<H', 5)
    b += struct.pack('<I', perm_id)
    b += struct.pack('<I', cell_id)
    b += _str_field(nick)
    return b

# ── Village (3rd connection) protocol ─────────────────────────────────────────
# The 3D lobby world ("Village") is entered over a THIRD TinCat connection, opened
# to the Ip/Port advertised in the selected ServerType=4 GameServerData(170) entry
# (here 127.0.0.1:5479).
#
# Reversed from SADK.exe (Ghidra, s5): VillageServerConnection::HandleMessage @0x470890
# dispatches on a message-type field; type 1000 (0x3E8) = HandleEnterWorld @0x46f470,
# which calls SetState(VillageEntered=9) ON RECEIPT and then reads a POSITIONAL body:
#     Worldname:string, ServerPerm:u32, ChatChannelsCount:u32, N×(Zone:u32, Id:u32)
# Serializer matches S2Library Serializers.cs (LE; string = int32 len incl. trailing \0).
#
# UNKNOWNS (to learn empirically from the logged client frames below):
#   - the framing magic for village app messages (GUESS: lobby 0x26B6)
#   - whether a village LOGIN exchange is required before 1000 is accepted
#     (the conn has HandleLoggedIn@0x46d820 / HandleLoginFailed@0x46d910).
VILLAGE_MSG_ENTER_WORLD = 1000

def village_enter_world(worldname="SaDK Revival", server_perm=0, channels=None):
    channels = channels or []          # list of (zone:int, channel_id:int)
    body  = _str_field(worldname)
    body += struct.pack('<I', server_perm & 0xFFFFFFFF)
    body += struct.pack('<I', len(channels))
    for zone, cid in channels:
        body += struct.pack('<I', zone & 0xFFFFFFFF) + struct.pack('<I', cid & 0xFFFFFFFF)
    return app_payload(VILLAGE_MSG_ENTER_WORLD, body)

# ── Message type names ────────────────────────────────────────────────────────
MSG_NAMES = {
    1:"Simple",2:"ChatMessage",3:"PrivateChatMessage",4:"RequestLogin",
    5:"ChatUserInfo",6:"ChatDisconnected",17:"JoinChatChannel",
    42:"ResultStatusMsg",53:"GetUserInfo",55:"GetPlayerInfo",
    56:"RequestUserBuddyList",59:"SendUserInfo",60:"SendPlayerInfo",
    71:"RequestCreateAccount",72:"SelectNickname",75:"SelectNicknameReply",
    77:"RegisterNickname",86:"AddCharacter",88:"ConfirmNickname",
    94:"RemoveCharacter",98:"AddUserBuddy",99:"RemoveUserBuddy",
    105:"RequestMOTD",106:"SendMOTD",107:"RegObserverGlobalChat",
    108:"DeregObserverGlobalChat",109:"UserLoggedIn",110:"UserLoggedOut",
    115:"RegObserverUserLogin",116:"DeregObserverUserLogin",
    146:"PlayerJoinedServer",153:"StatusWithId",157:"RequestUserIgnoreList",
    158:"GetCDKeys",159:"SendCDKey",161:"PropertyGet",162:"PropertyData",
    165:"Chat",168:"RegisterServer",169:"UnlistServer",170:"GameServerData",
    171:"GetServers",172:"StopServerUpdates",175:"JoinServer",
    176:"LeaveServer",177:"UpdateServerInfo",188:"VersionCheck",
    189:"GetChatServer",190:"PlayerLeftServer",192:"SendChatServerInfo",
    201:"Login",202:"LoginReply",203:"RegisterUser",204:"LoginUser",
    206:"LoginServer",207:"LoginReplyCipher",211:"LoginChat",
    212:"LoginChatReply",213:"VerifyChatLogin",221:"ConnectToServer",
    222:"ConnectToServerReply",223:"PlayerConnecting",
}

# ── Logging ───────────────────────────────────────────────────────────────────
_log_lock = threading.Lock()

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

def hex_dump(data, indent="    ", w=16):
    lines = []
    for i in range(0, len(data), w):
        c = data[i:i+w]
        lines.append(f"{indent}{i:04x}  {' '.join(f'{b:02x}' for b in c):<{w*3}}  |{''.join(chr(b) if 32<=b<127 else '.' for b in c)}|")
    return "\n".join(lines)

# ── Payload reader ────────────────────────────────────────────────────────────
class PR:
    def __init__(self, data): self._d = data; self._p = 0
    def u8(self):   v=self._d[self._p]; self._p+=1; return v
    def i8(self):   v=struct.unpack_from('b',self._d,self._p)[0]; self._p+=1; return v
    def u16(self):  v=struct.unpack_from('<H',self._d,self._p)[0]; self._p+=2; return v
    def i16(self):  v=struct.unpack_from('<h',self._d,self._p)[0]; self._p+=2; return v
    def u32(self):  v=struct.unpack_from('<I',self._d,self._p)[0]; self._p+=4; return v
    def i32(self):  v=struct.unpack_from('<i',self._d,self._p)[0]; self._p+=4; return v
    def bool_(self):return self.u8() != 0
    def string(self):
        l=self.i32()
        if l<=0: return None
        v=self._d[self._p:self._p+l]; self._p+=l
        return v.rstrip(b'\x00').decode('iso-8859-15','replace')
    def blob(self):
        l=self.i32()
        if l<=0: return None
        v=self._d[self._p:self._p+l]; self._p+=l; return v
    def rem(self): return len(self._d)-self._p

def parse_payload(payload):
    if len(payload) < 4: return -1, {}
    r = PR(payload)
    magic = r.u16(); t1 = r.u16()
    # consume Type2 if it matches Type1
    if r.rem() >= 2 and struct.unpack_from('<H', payload, r._p)[0] == t1:
        r.u16()
    f = {}
    try:
        if t1 == 4:    # RequestLogin
            f['Nick']=r.string(); f['Password']=r.blob()
            f['CdKey']=r.blob(); f['Keypool']=r.u16()
            f['Patchlevel']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 71: # RequestCreateAccount
            f['Nick']=r.string(); f['Password']=r.blob()
            f['CdKey']=r.blob(); f['Keypool']=r.u16()
            f['Patchlevel']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 201: f['Key']=r.blob(); f['TicketId']=r.u32()
        elif t1 in (203,204,206): f['Cipher']=r.blob(); f['TicketId']=r.u32()
        elif t1 == 211: f['TicketId']=r.u32()  # LoginChat
        elif t1 == 213:  # VerifyChatLogin = PermId + Cipher + TicketId
            f['PermId']=r.u32(); f['Cipher']=r.blob(); f['TicketId']=r.u32()
        elif t1 == 17:   # JoinChatChannel = CellId + TicketId + Option + Password + FromId
            f['CellId']=r.u32(); f['TicketId']=r.u32(); f['Option']=r.u16()
            f['Password']=r.string(); f['FromId']=r.u32()
        elif t1 == 72: f['CharId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 105: f['TicketId']=r.u32()
        elif t1 == 107: f['TicketId']=r.u32()
        elif t1 == 108: f['TicketId']=r.u32()
        elif t1 == 115: f['SendAll']=r.bool_(); f['TicketId']=r.u32()
        elif t1 == 116: f['TicketId']=r.u32()
        elif t1 == 157: f['UserId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 158: f['UserId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 53:  f['UserId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 55:  f['UserId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 56:  f['UserId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 161: f['Category']=r.i32(); f['Index']=r.i32(); f['TicketId']=r.u32()
        elif t1 == 171:  # GetServers = SendAll + ServerType + LobbyId + Level + GameMode
            # + Hardcore + Selection + TicketId  (17 field bytes).
            # s6 fix: the previous 5-field parse dropped Level/GameMode/Hardcore (3 bytes),
            # so TicketId mis-read as 0x04000000/0x05000000 (ServerType bled into it) and we
            # echoed a wrong ticket. Restored to match the 17-byte payload.
            f['SendAll']=r.bool_(); f['ServerType']=r.u8()
            f['LobbyId']=r.u32()
            f['Level']=r.u8(); f['GameMode']=r.u8(); f['Hardcore']=r.bool_()
            f['Selection']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 172: f['TicketId']=r.u32()
        elif t1 == 175: f['ServerId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 176: f['ServerId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 188: f['Version']=r.i16(); f['Subversion']=r.i16(); f['TicketId']=r.u32()
        elif t1 == 189: f['ServerType']=r.u8(); f['TicketId']=r.u32()
        elif t1 == 2:   f['Mode']=r.u32(); f['Txt']=r.string(); f['TicketId']=r.u32()
        elif t1 == 168:  # RegisterServer (AdK format)
            f['Name']=r.string(); f['Description']=r.string()
            f['Port']=r.u32(); f['ServerType']=r.u8()
            f['LobbyId']=r.u32(); f['Version']=r.string()
            f['MaxPlayers']=r.u8(); f['AiPlayers']=r.u8()
            f['Level']=r.u8(); f['GameMode']=r.u8()
            f['Hardcore']=r.bool_(); f['Map']=r.string()
            f['AutomaticJoin']=r.bool_(); f['Data']=r.blob()
            f['TicketId']=r.u32()
        elif t1 == 169: f['ServerId']=r.u32(); f['Running']=r.bool_(); f['TicketId']=r.u32()
        elif t1 == 177:
            f['Name']=r.string(); f['Description']=r.string()
            f['Cipher']=r.blob(); f['MaxPlayers']=r.u16()
            f['SlotsOccupied']=r.u16(); f['AiPlayers']=r.u16()
            f['LobbyId']=r.u32(); f['Level']=r.u8()
            f['GameMode']=r.u8(); f['Hardcore']=r.bool_()
            f['Map']=r.string(); f['Running']=r.bool_()
            f['Data']=r.blob(); f['PropertyMask']=r.u32()
            f['TicketId']=r.u32()
        elif t1 == 146: f['PermId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 190: f['PermId']=r.u32(); f['TicketId']=r.u32()
        elif t1 == 221:
            f['PermId']=r.u32(); f['ServerId']=r.u32(); f['TicketId']=r.u32()
    except Exception as e:
        f['_parse_err'] = str(e)
    return t1, f

# ── Connection handler ────────────────────────────────────────────────────────
_conn_counter = 0; _counter_lock = threading.Lock()

def next_conn_id():
    global _conn_counter
    with _counter_lock: _conn_counter += 1; return _conn_counter

class Conn:
    def __init__(self, sock, addr, conn_id, bin_file, is_chat=False, is_village=False):
        self._sock      = sock
        self._addr      = addr
        self._id        = conn_id
        self._bin_file  = bin_file
        self._is_chat   = is_chat   # True for the chat/UC (second) connection
        self._is_village = is_village  # True for the village/world (third) connection
        self._buf       = b""
        self._state     = "PREFIX"
        self._hdr       = None
        self._shared    = None   # ECDH shared secret
        self._logged_in = False
        self._lock      = threading.Lock()
        self._alive     = True
        # Game server registry (ServerId → info dict)
        self._servers   = {}
        self._next_server_id = 100

    # ── Low-level send ────────────────────────────────────────────────────────
    def _send_raw(self, data):
        self._save("SEND", data)
        with self._lock:
            try:
                self._sock.sendall(data)
            except Exception as e:
                log(f"  [#{self._id}] send error: {e}")
                self._alive = False

    def _save(self, direction, data):
        if self._bin_file:
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with _log_lock:
                self._bin_file.write(f"[{ts}] {direction} {len(data)} bytes\n".encode())
                self._bin_file.write(data + b"\n")
                self._bin_file.flush()

    def _send_app(self, ptype, body):
        pl = app_payload(ptype, body)
        self._send_raw(build_frame(FROM_SERVER, self._id, MSG_APPLICATION, pl))

    def _ok(self, ticket):
        body = struct.pack('<B', 0) + struct.pack('<i', 0) + struct.pack('<I', ticket)
        self._send_app(42, body)

    def _status_with_id(self, errorcode, obj_id, ticket):
        body  = struct.pack('<B', errorcode)
        body += struct.pack('<i', 0)   # errormsg null
        body += struct.pack('<I', obj_id)
        body += struct.pack('<I', ticket)
        self._send_app(153, body)

    # ── Chat (second connection) ────────────────────────────────────────────────
    def _send_chat(self, chat_bytes):
        # Wrap a chat-magic payload in the standard TinCat application frame.
        self._send_raw(build_frame(FROM_SERVER, self._id, MSG_APPLICATION, chat_bytes))

    def _send_initial_chat_reply(self):
        for cell_id, name, subject, creator, creator_id, protected in DEFAULT_CHANNELS:
            blob = _channel_data_blob(
                name=name, subject=subject, creator=creator, password=None,
                protected=protected, persistent=True, autodelete=False,
                hidden=False, creator_pid=creator_id)
            self._send_chat(chat_channel_info(cell_id, blob, ticket=0))
        log(f"  → [CHAT] pushed {len(DEFAULT_CHANNELS)} ChannelInfo on connect")

    def _handle_chat_frame(self, payload):
        # ChatPayloadPrefix: Magic(u16) Type(u16=0) Id(u16=chatType)
        if len(payload) < 6:
            log("  [CHAT] runt chat frame"); return
        _magic, _type, chat_id = struct.unpack_from('<HHH', payload, 0)
        body = payload[6:]
        log(f"  [CHAT] ← chat frame id={chat_id}")
        if chat_id == CHAT_CREATE_CHANNEL:      # CreateChannel: Data(blob) + TicketId
            r = PR(body); _data = r.blob(); ticket = r.u32() if r.rem() >= 4 else 0
            # Reply StatusReply OK (cell 3 mirrors the emulator's placeholder)
            self._send_chat(chat_status_reply(3, ticket, 0))
            log("  → [CHAT] StatusReply(create channel) OK")
        elif chat_id == CHAT_MESSAGE:           # ChatMessage relay
            self._handle_chat_message(body)
        else:
            log(f"  [CHAT] (no handler for chat id {chat_id})")

    def _handle_chat_message(self, body):
        # ChatMessage: ModuleId(u16) MessageId(u16) Except(u32) Data(blob) CellId(u32) Self(bool) Ispropset(bool)
        try:
            r = PR(body)
            module_id = r.u16(); message_id = r.u16(); _except = r.u32()
            data = r.blob(); cell_id = r.u32()
        except Exception as e:
            log(f"  [CHAT] failed to parse ChatMessage: {e}"); return
        # Echo the inner payload straight back as a ChatReply from the server.
        self._send_chat(chat_reply(message_id, data or b"", cell_id, FROM_SERVER, ispropset=True))
        log(f"  → [CHAT] echoed ChatMessage in cell {cell_id}")

    def _handle_join_chat_channel(self, f, ticket):
        # JoinChatChannel(17) arrives lobby-magic; the replies are chat-magic.
        cell_id = f.get('CellId', 1)
        option  = f.get('Option', 0)
        # 1) ChannelJoined  2) StatusReply OK  3) ChatUserInfo (self) wrapped in ChatReply
        self._send_chat(chat_channel_joined(cell_id, ticket, option))
        self._send_chat(chat_status_reply(cell_id, ticket, 0))
        inner = chat_inner_user_info(TEST_PERM_ID, cell_id, TEST_CHAR_NAME)
        self._send_chat(chat_reply(5, inner, cell_id, FROM_SERVER, ispropset=True))
        log(f"  → [CHAT] JoinChatChannel cell={cell_id}: Joined + StatusReply + ChatUserInfo")

    # ── Village (third connection) ──────────────────────────────────────────────
    def _send_village_enter_world(self):
        # Sent shortly after the village TinCat handshake. SPECULATIVE: if the client
        # requires a login exchange first, watch the [VILLAGE] log to see what it sends.
        time.sleep(0.5)
        if not self._alive:
            return
        self._send_raw(build_frame(FROM_SERVER, self._id, MSG_APPLICATION,
                                   village_enter_world()))
        log(f"  → [VILLAGE] sent EnterWorld (msg 1000) — SetState(VillageEntered=9) expected")

    def _handle_village_frame(self, payload):
        # Log raw village frames verbatim — this is how we learn the village login
        # protocol (magic + message ids) so we can answer it correctly next pass.
        if len(payload) >= 6:
            magic, t1, t2 = struct.unpack_from('<HHH', payload, 0)
            log(f"  [VILLAGE] ← app frame  magic=0x{magic:04x}  type1={t1}  type2={t2}  ({len(payload)}B)")
        else:
            log(f"  [VILLAGE] ← runt app frame ({len(payload)}B)")
        log(hex_dump(payload))

    # ── Ping keepalive ────────────────────────────────────────────────────────
    # NOTE: The client sends TYPE 11 pings TO the server (we log and ignore them).
    # The server must NOT send pings to the client — it causes an immediate disconnect.
    def _ping_loop(self):
        pass  # disabled

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        log(f"\n{'#'*60}")
        log(f"  CONNECTION #{self._id}  {self._addr[0]}:{self._addr[1]}")
        log(f"{'#'*60}")

        ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        ping_thread.start()

        try:
            self._sock.settimeout(60.0)
            while self._alive:
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self._save("RECV", chunk)
                self._buf += chunk
                self._process()
        except Exception as e:
            log(f"  [#{self._id}] error: {e}")
        finally:
            self._alive = False
            self._sock.close()
            if self._bin_file: self._bin_file.close()
            log(f"\n  DISCONNECTED #{self._id}")

    def _process(self):
        while True:
            if self._state == "PREFIX":
                if len(self._buf) < PREFIX_SIZE: break
                magic,from_,to_,typ,unk1,psz,csum = struct.unpack_from('<IIIIIII', self._buf)
                self._buf = self._buf[PREFIX_SIZE:]
                self._hdr = dict(Magic=magic,From=from_,To=to_,Type=typ,Unknown1=unk1,
                                 PayloadSize=psz,Checksum=csum)
                self._state = "PAYLOAD"
            elif self._state == "PAYLOAD":
                psz = self._hdr['PayloadSize']
                if len(self._buf) < psz: break
                payload = self._buf[:psz]; self._buf = self._buf[psz:]
                self._state = "PREFIX"
                self._on_message(payload)

    def _on_message(self, payload):
        h = self._hdr
        calc = crc32(payload)
        ok_str = "✓" if calc == h['Checksum'] else f"BAD(calc={calc:08X})"
        log(f"\n{'─'*60}")
        log(f"  [#{self._id}] ← CLIENT  TYPE={h['Type']}  {len(payload)+PREFIX_SIZE}B  CRC:{ok_str}")

        if h['Type'] == MSG_PING:
            log("  PING received — pong")
            return  # no response needed, we send our own pings

        elif h['Type'] == MSG_HANDSHAKE_CONNECT:
            self._handle_handshake(payload)

        elif h['Type'] == MSG_APPLICATION:
            # Village (third) connection: log every frame raw; don't try to parse as lobby.
            if self._is_village:
                self._handle_village_frame(payload)
                return
            # Distinguish chat-magic (0x0062) frames from lobby-magic (0x26B6).
            if len(payload) >= 2 and struct.unpack_from('<H', payload, 0)[0] == CHAT_PAYLOAD_MAGIC:
                self._handle_chat_frame(payload)
                return
            ptype, fields = parse_payload(payload)
            name = MSG_NAMES.get(ptype, f"Unknown({ptype})")
            log(f"  TYPE {ptype} = {name}")
            for k,v in fields.items():
                if isinstance(v, bytes): log(f"    {k}: [{len(v)}B] {v[:32].hex()}{'...' if len(v)>32 else ''}")
                else: log(f"    {k}: {v!r}")
            self._handle_app(ptype, fields)

        else:
            log(f"  Unknown frame type {h['Type']}")

    # ── Handshake ─────────────────────────────────────────────────────────────
    def _handle_handshake(self, payload):
        if len(payload) != HANDSHAKE_SIZE:
            log(f"  !! Bad handshake size {len(payload)}")
        hs_magic, conn_id = struct.unpack_from('<II', payload)
        username_raw = payload[8:8+HANDSHAKE_USERNAME_SIZE]
        password_raw = payload[8+HANDSHAKE_USERNAME_SIZE:8+HANDSHAKE_USERNAME_SIZE+HANDSHAKE_PASSWORD_SIZE]
        unknown1     = struct.unpack_from('<i', payload, 8+HANDSHAKE_USERNAME_SIZE+HANDSHAKE_PASSWORD_SIZE)[0]
        machine_user = username_raw.rstrip(b'\x00')
        machine_pass = password_raw.rstrip(b'\x00')
        log(f"  Machine user: {machine_user!r}")
        log(f"  Serial:       {machine_pass!r}")

        reply_pl = build_handshake_payload(self._id, username_raw, unknown1)
        self._send_raw(build_frame(FROM_SERVER, FROM_CLIENT, MSG_HANDSHAKE_CONNECTED, reply_pl))
        log(f"  → HandShakeConnected (type 5), conn_id={self._id}")

        # CHAT connection: the server must PROACTIVELY push the channel list the
        # instant the handshake completes (ChatProcessor.HandleInitialReply).
        # The client waits for this before the lobby/server-browser unlocks.
        if self._is_chat:
            self._send_initial_chat_reply()

        # VILLAGE connection: speculatively send EnterWorld(1000) shortly after the
        # handshake. SetState(VillageEntered=9) fires on receipt; if a login is required
        # first, the [VILLAGE] log will show what the client sends.
        if self._is_village:
            log("  [VILLAGE] handshake done — scheduling EnterWorld(1000)")
            threading.Thread(target=self._send_village_enter_world, daemon=True).start()

    # ── Application message dispatcher ────────────────────────────────────────
    def _handle_app(self, ptype, f):
        ticket = f.get('TicketId', 0)

        # ── Auth flow ─────────────────────────────────────────────────────────
        if ptype == 201:   # Login — ECDH
            self._handle_ecdh(f, ticket)

        elif ptype in (203, 204, 206):  # Register / Login / LoginServer
            self._handle_login_cipher(ptype, f, ticket)

        elif ptype == 4:   # RequestLogin (old plaintext path)
            log(f"  Nick={f.get('Nick')!r}  Patchlevel={f.get('Patchlevel')}")
            self._ok(ticket)
            self._send_login_reply_cipher(ticket)
            self._logged_in = True

        elif ptype == 71:  # RequestCreateAccount
            log(f"  Nick={f.get('Nick')!r}")
            self._ok(ticket)
            self._logged_in = True

        # ── Version / patches ─────────────────────────────────────────────────
        elif ptype == 188:
            log(f"  Version {f.get('Version')}.{f.get('Subversion')}")
            self._ok(ticket)

        # ── Properties ────────────────────────────────────────────────────────
        elif ptype == 161:
            cat, idx = f.get('Category',0), f.get('Index',0)
            body  = struct.pack('<i', cat) + struct.pack('<i', idx)
            body += struct.pack('<i', 0) + struct.pack('<I', ticket)
            self._send_app(162, body)
            self._ok(ticket)

        # ── Account / character info ──────────────────────────────────────────
        elif ptype == 53:  # GetUserInfo
            self._send_user_info(ticket)

        elif ptype == 55:  # GetPlayerInfo
            self._send_player_info(ticket)

        elif ptype == 72:  # SelectNickname
            self._send_select_nickname(ticket)

        elif ptype == 77:  # RegisterNickname
            name = f.get('Name', TEST_CHAR_NAME)
            log(f"  RegisterNickname: {name!r}")
            self._status_with_id(0, TEST_PERM_ID, ticket)

        elif ptype == 88:  # ConfirmNickname
            self._ok(ticket)

        elif ptype == 86:  # AddCharacter
            self._ok(ticket)

        elif ptype == 94:  # RemoveCharacter
            self._ok(ticket)

        # ── CD keys ───────────────────────────────────────────────────────────
        elif ptype == 158:  # GetCDKeys
            body  = struct.pack('<I', TEST_PERM_ID)   # UserId
            body += _str_field("0000000000000000")    # CdKey
            body += struct.pack('<H', 1)               # Keypool
            body += struct.pack('<I', ticket)
            self._send_app(159, body)
            self._ok(ticket)

        # ── Social ────────────────────────────────────────────────────────────
        elif ptype == 56:   # RequestUserBuddyList
            self._ok(ticket)
        elif ptype == 98:   # AddUserBuddy
            self._ok(ticket)
        elif ptype == 99:   # RemoveUserBuddy
            self._ok(ticket)
        elif ptype == 157:  # RequestUserIgnoreList
            self._ok(ticket)

        # ── Observer registrations ────────────────────────────────────────────
        elif ptype in (107, 108, 115, 116):
            self._ok(ticket)

        # ── MOTD ──────────────────────────────────────────────────────────────
        elif ptype == 105:
            motd = "Willkommen! SaDK Revival Server — WIP\x00"
            body  = _bytes_field(motd.encode('utf-8'))
            body += struct.pack('<I', ticket)
            self._send_app(106, body)

        # ── Chat server ───────────────────────────────────────────────────────
        elif ptype == 189:
            # UC/chat server on a DIFFERENT port — TinCat refuses to open a
            # second connection to the same host:port as the main lobby.
            body  = struct.pack('<I', 1)              # ServerId
            body += _str_field("127.0.0.1")           # Ip
            body += struct.pack('<I', 7071)           # Port — DIFFERENT from main lobby
            body += struct.pack('<B', f.get('ServerType', 0))
            body += _str_field(None)                  # Version
            body += _bytes_field(None)                # Data
            body += struct.pack('<I', ticket)
            self._send_app(192, body)
            log("  → SendChatServerInfo(192) pointing to 127.0.0.1:7071")

        # ── Game server list ──────────────────────────────────────────────────
        elif ptype == 171:  # GetServers
            self._send_server_list(ticket, server_type=f.get('ServerType', 0))

        elif ptype == 172:  # StopServerUpdates
            self._ok(ticket)

        elif ptype == 168:  # RegisterServer (Create Game)
            self._handle_register_server(f, ticket)

        elif ptype == 169:  # UnlistServer
            sid = f.get('ServerId', 0)
            self._servers.pop(sid, None)
            self._ok(ticket)

        elif ptype == 177:  # UpdateServerInfo
            self._handle_update_server(f, ticket)

        elif ptype == 146:  # PlayerJoinedServer
            self._ok(ticket)

        elif ptype == 190:  # PlayerLeftServer
            self._ok(ticket)

        elif ptype == 175:  # JoinServer
            self._ok(ticket)

        elif ptype == 176:  # LeaveServer
            self._ok(ticket)

        elif ptype == 221:  # ConnectToServer
            self._handle_connect_to_server(f, ticket)

        # ── Chat ──────────────────────────────────────────────────────────────
        # ── UC / Chat server login (second connection) ────────────────────────
        elif ptype == 211:  # LoginChat — client authenticates on chat connection
            # Reply with LoginChatReply (212): just send a nonce
            nonce = os.urandom(128)
            body  = _bytes_field(nonce)
            body += struct.pack('<I', ticket)
            self._send_app(212, body)
            log("  → LoginChatReply (212) sent")

        elif ptype == 213:  # VerifyChatLogin → StatusWithId(153) OK (NOT ResultStatusMsg)
            self._status_with_id(0, 0, ticket)
            log("  → VerifyChatLogin → StatusWithId OK")

        elif ptype == 17:   # JoinChatChannel
            self._handle_join_chat_channel(f, ticket)

        elif ptype == 2:
            txt = f.get('Txt', '') or ''
            log(f"  CHAT: {txt!r}")
            # Echo to self
            body  = _str_field(f"[Server] {txt}")
            body += struct.pack('<I', 0)
            self._send_app(165, body)

        else:
            log(f"  (no handler for TYPE {ptype})")

    # ── ECDH handler ──────────────────────────────────────────────────────────
    def _handle_ecdh(self, f, ticket):
        key_bytes = f.get('Key')
        if not key_bytes:
            log("  !! No key in Login payload"); return
        try:
            reply_cipher, self._shared = crypto_handle_login_key(key_bytes)
            log(f"  ECDH OK. shared={self._shared.hex()[:16]}...")
            body  = _bytes_field(reply_cipher)
            body += struct.pack('<I', ticket)
            self._send_app(202, body)
            log("  → LoginReply (202) sent")
        except Exception as e:
            log(f"  !! ECDH failed: {e}")

    # ── Credential cipher handler ─────────────────────────────────────────────
    def _handle_login_cipher(self, ptype, f, ticket):
        cipher = f.get('Cipher')
        action = {203:'RegisterUser', 204:'LoginUser', 206:'LoginServer'}[ptype]
        if not cipher:
            log(f"  !! No cipher in {action}"); return
        if not self._shared:
            log("  !! No shared secret — ECDH must come first"); return
        try:
            blob  = crypto_decrypt_cipher(cipher, self._shared)
            creds = decode_login_blob(blob, has_cdkey=(ptype==203))
            log(f"  {action}: username={creds.get('username')!r}")
            if 'cd_key' in creds:
                log(f"  cd_key={creds['cd_key']!r}")
        except ImportError as e:
            log(f"  !! {e} — skipping decryption, accepting anyway")
        except Exception as e:
            log(f"  !! Decryption failed: {e}")

        self._logged_in = True
        sk     = os.urandom(32)
        secret = crypto_encrypt_session_key(sk, self._shared) if TWOFISH_AVAILABLE else None
        self._send_login_reply_cipher(ticket, secret)

    def _send_login_reply_cipher(self, ticket, session_cipher=None):
        body  = struct.pack('<I', TEST_PERM_ID)
        body += _bytes_field(session_cipher)
        body += struct.pack('<I', ticket)
        self._send_app(207, body)
        log(f"  → LoginReplyCipher (207) perm_id={TEST_PERM_ID}")

    # ── Account / character responses ─────────────────────────────────────────
    def _send_user_info(self, ticket):
        body  = struct.pack('<I', TEST_PERM_ID)   # UserId
        body += _str_field(TEST_USERNAME)         # Name
        body += _bytes_field(None)                # Password (null)
        body += _str_field("test@test.test")      # Mail
        body += struct.pack('<B', 0)              # Banned
        body += struct.pack('<B', 1)              # Active
        body += struct.pack('<B', 2)              # Status
        body += _bytes_field(NICKNAME_DATA)       # Data
        body += _str_field("2024-01-01 00:00:00+0:00")  # Created
        body += _str_field("2024-01-01 00:00:00+0:00")  # LastLogin
        body += struct.pack('<I', 1)              # TotalLogins
        body += struct.pack('<I', ticket)
        self._send_app(59, body)
        self._ok(ticket)

    def _send_player_info(self, ticket):
        # Status=0 → no character exists, triggers character creation
        body  = struct.pack('<I', TEST_CHAR_ID)   # CharId
        body += _str_field(TEST_CHAR_NAME)        # Name
        body += struct.pack('<I', TEST_PERM_ID)   # OwnerId
        body += _str_field(TEST_USERNAME)         # OwnerName
        body += struct.pack('<I', 0)              # GuildId
        body += _str_field(None)                  # GuildName
        body += struct.pack('<B', 0)              # GuildRole
        body += struct.pack('<B', 1)              # Status=1 (character exists)
        body += struct.pack('<I', 0)              # ServerId
        body += _str_field(None)                  # ServerName
        body += _bytes_field(NICKNAME_DATA)       # Data (None = null)
        body += struct.pack('<I', ticket)
        self._send_app(60, body)
        self._ok(ticket)

    def _send_select_nickname(self, ticket):
        # SelectNicknameReply (TYPE 75) — same fields as SendPlayerInfo
        body  = struct.pack('<I', TEST_CHAR_ID)
        body += _str_field(TEST_CHAR_NAME)
        body += struct.pack('<I', TEST_PERM_ID)
        body += _str_field(TEST_USERNAME)
        body += struct.pack('<I', 0)
        body += _str_field(None)
        body += struct.pack('<B', 0)
        body += struct.pack('<B', 1)
        body += struct.pack('<I', 0)
        body += _str_field(None)
        body += _bytes_field(NICKNAME_DATA)
        body += struct.pack('<I', ticket)
        self._send_app(75, body)
        self._ok(ticket)

    # ── Game server list ──────────────────────────────────────────────────────
    def _make_server_payload(self, srv, ticket):
        if GAMESERVERDATA_FORMAT == "adk":
            return self._make_server_payload_adk(srv, ticket)
        return self._make_server_payload_old(srv, ticket)

    def _make_server_payload_adk(self, srv, ticket):
        # TYPE 170 GameServerData — emulator AdK format (Payloads.cs::GameServerData).
        # ServerId, Name, OwnerId, Description, Ip, Port,
        #   ServerType(B), LobbyId(I), Version(str),
        #   MaxPlayers(B), CurPlayers(B), AiPlayers(B),
        #   Level(B), GameMode(B), Hardcore(bool), Map(str), Running(bool),
        #   Data(bytes), TicketId(I)
        body  = struct.pack('<I', srv['id'])
        body += _str_field(srv['name'])
        body += struct.pack('<I', srv['owner_id'])
        body += _str_field(srv.get('description', ''))
        body += _str_field(srv['ip'])
        body += struct.pack('<I', srv['port'])
        body += struct.pack('<B', srv.get('server_type', 5))
        body += struct.pack('<I', srv.get('lobby_id', 9212))
        body += _str_field(srv.get('version', ''))
        body += struct.pack('<B', srv.get('max_players', 2) & 0xFF)
        body += struct.pack('<B', srv.get('cur_players', 1) & 0xFF)
        body += struct.pack('<B', srv.get('ai_players', 0) & 0xFF)
        body += struct.pack('<B', srv.get('level', 0) & 0xFF)
        body += struct.pack('<B', srv.get('game_mode', 0) & 0xFF)
        body += struct.pack('<B', 1 if srv.get('hardcore') else 0)
        body += _str_field(srv.get('map', ''))
        body += struct.pack('<B', 1 if srv.get('running') else 0)
        body += _bytes_field(srv.get('data'))
        body += struct.pack('<I', ticket)
        return body

    def _make_server_payload_old(self, srv, ticket):
        # TYPE 170 GameServerData — ORIGINAL TinCat wire format (ServerInfoOld from Payloads.cs).
        # The emulator's GameServerData class was a broken reimplementation; TinCat's own
        # deserializer (commLayer.log) rejects it. Using the Ghidra-verified original format.
        # Field order: ServerId, Name, OwnerId, Description, Ip, Port,
        #   PasswordRequired(bool), ServerType(B), ServerSubtype(B), Version(str),
        #   MaxPlayers(H), CurPlayers(H), MaxSpectators(H), CurSpectators(H), AiPlayers(H),
        #   RoomId(I), Level(B), GameMode(B), Hardcore(bool), Map(str),
        #   Running(bool), LockedConfig(bool), Data(bytes), TicketId(I)
        body  = struct.pack('<I', srv['id'])
        body += _str_field(srv['name'])
        body += struct.pack('<I', srv['owner_id'])
        body += _str_field(srv.get('description', ''))
        body += _str_field(srv['ip'])
        body += struct.pack('<I', srv['port'])
        body += struct.pack('<B', 0)                               # PasswordRequired
        body += struct.pack('<B', srv.get('server_type', 5))      # ServerType
        # ServerSubtype -> descriptor[0x29], the village-list discriminator checked at
        # FUN_0046a000 (0x46a036: CMP byte [EDI+0x29],2). 2 = village/lobby list, 1 = game
        # list. Confirmed live: our ST=4 entry was dropped because this was hardcoded 0.
        body += struct.pack('<B', srv.get('server_subtype', 0))    # ServerSubtype
        body += _str_field(srv.get('version', ''))                # Version
        body += struct.pack('<H', srv.get('max_players', 2))      # MaxPlayers (uint16)
        body += struct.pack('<H', srv.get('cur_players', 1))      # CurPlayers (uint16)
        body += struct.pack('<H', 0)                               # MaxSpectators
        body += struct.pack('<H', 0)                               # CurSpectators
        body += struct.pack('<H', srv.get('ai_players', 0))       # AiPlayers (uint16)
        body += struct.pack('<I', srv.get('lobby_id', 9212))      # RoomId
        body += struct.pack('<B', srv.get('level', 0))            # Level
        body += struct.pack('<B', srv.get('game_mode', 0))        # GameMode
        body += struct.pack('<B', 1 if srv.get('hardcore') else 0) # Hardcore
        body += _str_field(srv.get('map', ''))                    # Map
        body += struct.pack('<B', 1 if srv.get('running') else 0) # Running
        body += struct.pack('<B', 0)                               # LockedConfig
        body += _bytes_field(srv.get('data'))                     # Data
        body += struct.pack('<I', ticket)
        return body

    def _send_server_list(self, ticket, server_type=0):
        sent = 0
        for srv in self._servers.values():
            if server_type == 0 or srv.get('server_type') == server_type:
                self._send_app(170, self._make_server_payload(srv, ticket))
                sent += 1

        # Inject fake servers if none registered yet
        if server_type == 4 and sent == 0:
            fake = {
                'id': 1, 'owner_id': TEST_PERM_ID,
                'name': 'world1', 'description': 'SaDK Revival Lobby World',
                'ip': '127.0.0.1', 'port': 5479,
                'max_players': 20, 'cur_players': 1, 'ai_players': 0,
                # RoomId = current-room g_SelectedVillageRoomId (DAT_0087d580, live=0x3E8=1000).
                # s11: 1000 IS the village-entry path -- the client recognizes "the server for my
                # room is here" and LoadLevel's the village. It froze before because name='Lobby'
                # matched no real world, so it built an empty scene + loaded garbage geo. Now
                # name+map point at a REAL local world (data\lobby\scene\world1.xml). Brute-force
                # candidates if world1 fails: world2, scene1, scene2.
                'lobby_id': 1000, 'version': '', 'server_type': 4, 'server_subtype': 2,
                'level': 0, 'game_mode': 0, 'hardcore': False,
                'map': 'world1', 'running': True, 'data': None,
            }
            self._send_app(170, self._make_server_payload(fake, ticket))
            sent += 1
            log("  → Injected fake lobby world server (ServerType=4)")

        if server_type == 5 and sent == 0:
            fake = {
                'id': 2, 'owner_id': TEST_PERM_ID,
                'name': 'Revival Test Game',
                'description': '2 player test',
                'ip': '127.0.0.1', 'port': 5479,
                'max_players': 2, 'cur_players': 1, 'ai_players': 0,
                'lobby_id': 9212, 'version': '9212', 'server_type': 5,
                'level': 0, 'game_mode': 0, 'hardcore': False,
                'map': 'MP_2P_steinfjord', 'running': False, 'data': None,
            }
            self._send_app(170, self._make_server_payload(fake, ticket))
            sent += 1
            log("  → Injected fake game server (ServerType=5)")

        self._ok(ticket)
        log(f"  → GetServers(type={server_type}): sent {sent} server(s) + OK")

    def _handle_register_server(self, f, ticket):
        sid = self._next_server_id; self._next_server_id += 1
        srv = {
            'id':          sid,
            'owner_id':    TEST_PERM_ID,
            'name':        f.get('Name', 'TestGame'),
            'description': f.get('Description', ''),
            'ip':          self._addr[0],   # use actual client IP
            'port':        f.get('Port', 5479),
            'max_players': f.get('MaxPlayers', 2),
            'cur_players': 1,
            'ai_players':  f.get('AiPlayers', 0),
            'lobby_id':    f.get('LobbyId', 9212),
            'version':     f.get('Version', ''),
            'server_type': f.get('ServerType', 5),
            'level':       f.get('Level', 0),
            'game_mode':   f.get('GameMode', 0),
            'hardcore':    f.get('Hardcore', False),
            'map':         f.get('Map', ''),
            'running':     False,
            'data':        f.get('Data'),
        }
        self._servers[sid] = srv
        log(f"  RegisterServer: id={sid} name={srv['name']!r} map={srv['map']!r}")
        self._status_with_id(0, sid, ticket)

    def _handle_update_server(self, f, ticket):
        sid = next(iter(self._servers), None)
        if sid and sid in self._servers:
            s = self._servers[sid]
            s['name']        = f.get('Name', s['name'])
            s['description'] = f.get('Description', s['description'])
            slots = f.get('MaxPlayers', s['max_players'])
            occ   = f.get('SlotsOccupied', 0)
            s['max_players'] = slots - occ
            s['map']         = f.get('Map', s['map'])
            s['running']     = f.get('Running', s['running'])
            s['data']        = f.get('Data', s['data'])
            log(f"  UpdateServer: id={sid} running={s['running']} map={s['map']!r}")
        self._ok(ticket)

    def _handle_connect_to_server(self, f, ticket):
        sid    = f.get('ServerId', 0)
        srv    = self._servers.get(sid)
        nonce  = os.urandom(128)
        body   = struct.pack('<I', TEST_PERM_ID)   # PermId
        body  += struct.pack('<I', sid)             # ServerId
        body  += _str_field(srv['ip'] if srv else '127.0.0.1')
        body  += struct.pack('<I', srv['port'] if srv else 5479)
        body  += _bytes_field(nonce)
        body  += struct.pack('<B', 0)              # errorcode
        body  += _str_field(None)                  # errormsg
        body  += struct.pack('<I', ticket)
        self._send_app(222, body)
        log(f"  → ConnectToServerReply (222) server={sid}")

# ── Server main ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SaDK TinCat Stub Server v3")
    parser.add_argument("--port", type=int, default=7070)
    args = parser.parse_args()

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"SaDK TinCat Stub Server v3\nStarted: {datetime.now()}\n\n")

    os.makedirs(BIN_DIR, exist_ok=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("0.0.0.0", args.port))
    except PermissionError:
        print(f"ERROR: Cannot bind to port {args.port}. Run as Administrator.")
        sys.exit(1)
    srv.listen(10)
    srv.settimeout(1.0)   # allow Ctrl+C to interrupt accept()

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║     SaDK TinCat Stub Server  v3              ║")
    print("╠══════════════════════════════════════════════╣")
    print(f"║  Port     : {args.port:<33}║")
    print(f"║  Username : {' test':<33}║")
    print(f"║  Password : {' test':<33}║")
    print(f"║  Serial   : {' test':<33}║")
    print("╠══════════════════════════════════════════════╣")
    print("║  LobbySettings.ini → Host = \"127.0.0.1\"      ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # Second listener on port 7071 — UC/chat server (must be different from 7070
    # or TinCat refuses to open a second connection to the same host:port).
    def make_extra_listener(port, label):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(10)
            s.settimeout(1.0)
            print(f"  {label} stub listening on port {port}")
            return s
        except Exception as e:
            print(f"  WARNING: Could not bind port {port}: {e}")
            return None

    uc_srv    = make_extra_listener(7071, "UC/chat server")
    # Third listener on port 5479 — the lobby world port.
    # We just need something to answer here so the game unlocks the Enter button.
    # The lobby world will be broken/empty but the game browser should still work.
    world_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    world_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        world_srv.bind(("0.0.0.0", 5479))
        world_srv.listen(10)
        world_srv.settimeout(1.0)
        print(f"  Lobby world stub also listening on port 5479")
        print()
    except Exception as e:
        world_srv = None
        print(f"  WARNING: Could not bind port 5479: {e}")

    def accept_loop(server_sock, label):
        while True:
            try:
                client_sock, addr = server_sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            cid = next_conn_id()
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            bf  = open(os.path.join(BIN_DIR, f"{label}_{cid}_{ts}.bin"), "wb")
            c   = Conn(client_sock, addr, cid, bf,
                       is_chat=(label == "uc"), is_village=(label == "world"))
            threading.Thread(target=c.run, daemon=True).start()

    try:
        if uc_srv:
            threading.Thread(target=accept_loop, args=(uc_srv, "uc"),
                             daemon=True).start()
        if world_srv:
            threading.Thread(target=accept_loop, args=(world_srv, "world"),
                             daemon=True).start()
        accept_loop(srv, "lobby")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        srv.close()
        if uc_srv:    uc_srv.close()
        if world_srv: world_srv.close()

if __name__ == "__main__":
    main()
