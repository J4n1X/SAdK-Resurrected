#!/usr/bin/env python3
"""
SaDK Lobby Proxy / Traffic Logger  v2
Intercepts and decodes login traffic from Die Siedler: Aufbruch der Kulturen.

SETUP:
  1. Edit the game file:
       data/lobby/config/LobbySettings.ini
     Change:
       Host = "84.17.180.120"
     To:
       Host = "127.0.0.1"

  2. Run this script (may need to run as Administrator for port 7070):
       python lobby_proxy.py

     OR with forwarding to the real server (if it's still online):
       python lobby_proxy.py --forward

  3. Start the game and attempt to log in.
     All traffic is printed here and saved to sadk_lobby_capture.log.

  4. When done, revert LobbySettings.ini to the original IP.

v2 changes:
  - Proper TCP stream buffering (no more truncated packets)
  - TinCat_Scramble implemented — tries to decrypt header with candidate keys
  - Extracts embedded strings from any position in packet
  - Saves raw binary captures per connection for offline analysis
"""

import socket
import threading
import struct
import sys
import os
import argparse
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT  = 7070

REAL_HOST = "84.17.180.120"
REAL_PORT = 7070

# This script lives in tools/; write logs/captures to the repo root, as before.
_ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(_ROOT, "sadk_lobby_capture.log")
BIN_DIR  = os.path.join(_ROOT, "sadk_captures")

# ── TinCat_Scramble (RE'd from tincat3.dll at 0x10007d70) ───────────────────

def tincat_scramble(data: bytearray, key: bytes, decrypt: bool = False) -> bytearray:
    """
    Python implementation of TinCat_Scramble.

    Encrypt (param_4=0):
        prev = 0x3F
        for i in range(len):
            raw    = data[i]
            mixed  = (raw + i + prev) & 0xFF
            data[i] = key[i % keylen] ^ mixed
            prev   = raw           ← carry is the PLAINTEXT byte

    Decrypt (param_4 != 0):
        prev = 0x3F
        for i in range(len):
            mixed  = key[i % keylen] ^ data[i]
            plain  = (mixed - i - prev) & 0xFF
            data[i] = plain
            prev   = plain
    """
    if not key:
        return data  # keylen=0 would div/zero in C; skip
    out  = bytearray(data)
    prev = 0x3F  # '?'
    klen = len(key)
    if not decrypt:
        for i in range(len(out)):
            raw     = out[i]
            mixed   = (raw + i + prev) & 0xFF
            out[i]  = key[i % klen] ^ mixed
            prev    = raw
    else:
        for i in range(len(out)):
            mixed   = key[i % klen] ^ out[i]
            plain   = (mixed - i - prev) & 0xFF
            out[i]  = plain
            prev    = plain
    return out


def try_decrypt_with_keys(data: bytes, candidate_keys: list) -> list:
    """
    Try to decrypt a data block with each candidate key.
    Returns list of (key, decrypted_bytes, readable_strings) for promising results.
    """
    results = []
    for key in candidate_keys:
        if not key:
            continue
        dec = tincat_scramble(bytearray(data), key.encode() if isinstance(key, str) else key, decrypt=True)
        strs = extract_strings(bytes(dec), min_len=3)
        # Only return if we found some readable strings
        if strs:
            results.append((key, bytes(dec), strs))
    return results


# ── Message type table (from msgdefs.ini) ────────────────────────────────────

MSG_NAMES = {
    1:   "Simple",                    2:   "ChatMessage",
    3:   "PrivateChatMessage",        4:   "RequestLogin",
    5:   "UserJoinedChannel",         6:   "UserLeftChannel",
    7:   "ChannelInfo",               8:   "AdminRequestMsgList",
    9:   "AdminRequestMessage",       10:  "AdminRequestAllMessages",
    11:  "AdminUpdateMessage",        12:  "AdminMessageList",
    13:  "AdminMessageEntry",         14:  "AdminAddMessageEntry",
    15:  "AdminRemoveMessageEntry",   16:  "InviteToChannel",
    17:  "RequestJoinChannel",        18:  "RequestKickFromChannel",
    19:  "RequestUser",               20:  "RequestGroup",
    21:  "FullUserData",              22:  "FullGroupData",
    23:  "CreateUser",                24:  "CreateGroup",
    25:  "UpdateUser",                26:  "UpdateGroup",
    27:  "RequestRemoveUser",         28:  "RequestRemoveGroup",
    29:  "UserMgrResult",             30:  "WhisperChatMessage",
    31:  "EmailMessage",              32:  "AdminAddEmailMessageEntry",
    33:  "AdminRequestEmailList",     34:  "BrokerAddItem",
    35:  "BrokerChangePrize",         36:  "BrokerRemoveItem",
    37:  "BrokerGetItem",             38:  "BrokerItem",
    39:  "BrokerGetItemList",         40:  "BrokerGetLimit",
    41:  "BrokerLimit",               42:  "Result",
    43:  "EmailNotification",         44:  "BrokerBuyRequest",
    45:  "BrokerNotification",        46:  "BrokerSoldNotification",
    47:  "BrokerItemListFinished",    48:  "StatisticsRequestItemList",
    49:  "StatisticsGetLiveValue",    50:  "StatisticsItemInfo",
    51:  "StatisticsLiveValueData",   52:  "StatisticsResultCode",
    53:  "RequestUsers",              55:  "RequestUserCharList",
    56:  "RequestUserBuddyList",      57:  "RequestUserGroupList",
    58:  "RequestPermIDAccess",       59:  "UserData",
    60:  "UserCharConn",              61:  "UserBuddyConn",
    62:  "UserGroupConn",             63:  "PermIDAccess",
    64:  "RequestGroups",             66:  "RequestGroupUserList",
    67:  "RequestGroupAccess",        68:  "GroupUserConn",
    69:  "GroupData",                 70:  "GroupAccess",
    71:  "RequestCreateAccount",      72:  "RequestCharacters",
    73:  "SendGameDataBundle",        74:  "SendGameData",
    75:  "CharacterData",             76:  "BeenKicked",
    77:  "CreateCharacterFromPreview",78:  "RequestGuilds",
    79:  "AddCharacterFromPreview",   80:  "RequestGuildCharList",
    82:  "GuildData",                 83:  "GuildCharConn",
    84:  "AddUser",                   85:  "AddGroup",
    86:  "AddCharacter",              87:  "AddGuild",
    88:  "ChangeUser",                89:  "ChangeGroup",
    90:  "ChangeCharacter",           91:  "ChangeGuild",
    92:  "RemoveUser",                93:  "RemoveGroup",
    94:  "RemoveCharacter",           95:  "RemoveGuild",
    96:  "AddUserKey",                97:  "RemoveUserKey",
    98:  "AddUserBuddy",              99:  "RemoveUserBuddy",
    100: "AddGroupUser",              101: "RemoveGroupUser",
    102: "AddGuildChar",              103: "RemoveGuildChar",
    104: "SetGroupAccess",            105: "RequestMOTD",
    106: "MOTD",                      107: "RegObserverGlobalChat",
    108: "DeregObserverGlobalChat",   109: "UserLoggedIn",
    110: "UserLoggedOut",             111: "RegObserverUserList",
    112: "DeregObserverUserList",     113: "RegObserverCharList",
    114: "DeregObserverCharList",     115: "RegObserverUserLogin",
    116: "DeregObserverUserLogin",    117: "RegObserverUptime",
    118: "DeregObserverUptime",       119: "RequestSingleCdKey",
    120: "CdKeyData",                 121: "RequestMachines",
    122: "MachineData",               123: "UserAdded",
    124: "KickPermIDMachine",         125: "UserRemoved",
    126: "CharAdded",                 128: "CharRemoved",
    135: "RestoreUser",               137: "RestoreChar",
    138: "KickPermIDServer",          139: "KickPermID",
    140: "AddKey",                    141: "RemoveKey",
    142: "BanKey",                    143: "UnbanKey",
    144: "RequestPermID",             145: "PermIDData",
    146: "EnterServer",               147: "RequestPrivateMessageList",
    148: "ChangePrivateMessage",      149: "PrivateMessage",
    150: "AddPrivateMessage",         151: "RemovePrivateMessage",
    152: "ChangeGuildChar",           153: "AddResult",
    154: "AddUserIgnore",             155: "RemoveUserIgnore",
    156: "RequestUserBuddyRefs",      157: "RequestUserIgnoreList",
    158: "RequestUserKeyList",        159: "UserKeyConn",
    160: "UserIgnoreConn",            161: "PropertyGet",
    162: "PropertyData",              163: "PropertySetAbsolute",
    164: "PropertySetRelative",       165: "Chat",
    166: "RequestServers",            167: "RequestMachineGameServers",
    168: "AddGameServer",             169: "RemoveServer",
    170: "GameServerData",            171: "RegObserverServerList",
    172: "DeregObserverServerList",   173: "GetStatisticsConnection",
    174: "StatisticsConnection",      175: "RegObserverBuddylist",
    176: "DeregObserverBuddylist",    177: "ChangeGameServer",
    178: "ChangePatchlevel",          179: "ChangeMOTD",
    180: "RequestServerInfo",         181: "ServerInfoData",
    182: "UptimeData",                183: "CheckLevel",
    184: "SetUserVisible",            185: "DownloadLogs",
    186: "ChangeGroupUser",           187: "ChangeUserKey",
    188: "CheckVersion",              189: "AssignServer",
    190: "LeaveServer",               191: "AddUsercomm",
    192: "UsercommServerData",        193: "UsercommRequestUserdata",
    194: "UsercommUserData",          201: "StartAuthenticateSession",
    202: "AckAuthenticateSession",    203: "SelfRegistration",
    204: "AuthenticateUser",          205: "AuthenticateSupport",
    206: "AuthenticateServer",        207: "SessionKey",
    211: "StartValidateTokenSession", 212: "AckValidateTokenSession",
    213: "SendToken",                 214: "ValidateToken",
    221: "RequestConnectionData",     222: "ConnectionData",
    223: "TANConnectionRequest",      224: "TANLogin",
    240: "UCRoute",                   241: "UCPrivate",
    242: "UCCreateChannel",           243: "UCUpdateChannel",
    244: "UCRemoveChannel",           245: "UCJoinChannel",
    246: "UCLeaveChannel",            247: "UCChannelJoined",
    248: "UCChannelLeft",             249: "UCKickUser",
    250: "UCUserKicked",              251: "UCUserInfo",
    252: "GameResultSubmit",          253: "GameResultSubmitResult",
    254: "RequestSingleUserRank",     255: "ReceiveSingleUserRank",
    256: "RequestRankRange",          257: "ReceiveRankRange",
    258: "AddRankingServer",          259: "RequestLeaveChannel",
    260: "CheckPlayerOnServerAndGetInfos",
    261: "CheckPlayerOnServerAndGetInfosReply",
    262: "GetChannelByName",
}

TINCAT_MAGIC = b'\xef\xfb\xba\xda'

# ── Packet analysis ──────────────────────────────────────────────────────────

def hex_dump(data: bytes, indent="    ") -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part   = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04x}  {hex_part:<47}  |{ascii_part}|")
    return "\n".join(lines) if lines else f"{indent}(empty)"


def extract_strings(data: bytes, min_len: int = 4, max_count: int = 20) -> list:
    results, current = [], []
    for b in data:
        if 32 <= b < 127:
            current.append(chr(b))
        else:
            if len(current) >= min_len:
                results.append("".join(current))
                if len(results) >= max_count:
                    break
            current = []
    if len(current) >= min_len:
        results.append("".join(current))
    return results


def find_string_offsets(data: bytes) -> list:
    """Find offsets of all printable-ASCII runs of length ≥ 4."""
    hits = []
    start = None
    for i, b in enumerate(data):
        if 32 <= b < 127:
            if start is None:
                start = i
        else:
            if start is not None and (i - start) >= 4:
                hits.append((start, data[start:i].decode("ascii")))
            start = None
    if start is not None and (len(data) - start) >= 4:
        hits.append((start, data[start:].decode("ascii")))
    return hits


def tincat_header_info(data: bytes) -> dict:
    """Parse the TinCat frame header heuristically."""
    info = {}
    if len(data) < 4:
        return info

    # Check magic at offset 0 and 26
    if data[:4] == TINCAT_MAGIC:
        info["magic_at_0"] = True
    if len(data) > 29 and data[26:30] == TINCAT_MAGIC:
        info["magic_at_26"] = True

    # Payload length field hypothesis: big-endian uint32 at offset 16
    if len(data) >= 20:
        be_len = struct.unpack_from(">I", data, 16)[0]
        if 4 <= be_len <= len(data):
            info["payload_len_at_16_BE"] = be_len

    # Sequence number hypothesis: uint16 at offset 24
    if len(data) >= 26:
        seq = struct.unpack_from("<H", data, 24)[0]
        info["seq_at_24_LE"] = seq

    return info


def decode_inner_message(payload: bytes, label="payload") -> list:
    """Try to interpret the payload as a msgdef message at various starting offsets."""
    notes = []
    for off in range(min(8, len(payload) - 2)):
        if len(payload) < off + 2:
            break
        t = struct.unpack_from("<H", payload, off)[0]
        name = MSG_NAMES.get(t)
        if name:
            notes.append(f"  Possible msgdef TYPE {t} ({name}) at {label} offset +{off}")

            # Decode specific types
            rest = payload[off+2:]
            try:
                if t == 4 and len(rest) >= 5:    # RequestLogin
                    nick_raw = rest[:256] if len(rest) >= 256 else rest
                    nick = nick_raw.rstrip(b'\x00').decode("utf-8", errors="replace")
                    notes.append(f"    nick={nick!r}")
                    if len(rest) >= 256 + 32:
                        pwd = rest[256:288].rstrip(b'\x00').decode("utf-8", errors="replace")
                        notes.append(f"    password={'*'*len(pwd)}")
                    if len(rest) >= 256 + 32 + 128:
                        cdkey = rest[288:416].rstrip(b'\x00').decode("utf-8", errors="replace")
                        notes.append(f"    cd_key={cdkey!r}")
                elif t == 71 and len(rest) >= 5:  # RequestCreateAccount
                    nick = rest[:256].rstrip(b'\x00').decode("utf-8", errors="replace") if len(rest) >= 256 else rest.rstrip(b'\x00').decode("utf-8","replace")
                    notes.append(f"    nick={nick!r}")
                elif t == 42 and len(rest) >= 5:  # Result
                    ec = rest[0]
                    msg = rest[1:33].rstrip(b'\x00').decode("utf-8", errors="replace") if len(rest) > 1 else ""
                    notes.append(f"    errorcode={ec}  msg={msg!r}")
                elif t == 207 and len(rest) >= 4:  # SessionKey
                    perm_id = struct.unpack_from("<I", rest, 0)[0]
                    notes.append(f"    perm_id={perm_id}")
                elif t == 106 and len(rest) >= 4:  # MOTD
                    txt = rest[:256].rstrip(b'\x00').decode("utf-8", errors="replace")
                    notes.append(f"    MOTD={txt!r}")
            except Exception:
                pass
    return notes


def analyze_packet(data: bytes, direction: str) -> list:
    """Full packet analysis: header, strings, inner message decoding, scramble attempts."""
    lines = []
    arrow = "CLIENT ──► SERVER" if direction == "c2s" else "SERVER ──► CLIENT"
    lines.append(f"  {arrow}   ({len(data)} bytes)")

    # 1. Check for TinCat magic header
    hdr = tincat_header_info(data)
    if hdr:
        lines.append(f"  TinCat header: {hdr}")

    # 2. String offsets in raw packet
    str_hits = find_string_offsets(data)
    if str_hits:
        lines.append(f"  Strings in raw packet:")
        for off, s in str_hits:
            lines.append(f"    offset {off:3d} (0x{off:02x}): {s!r}")

    # 3. Try to find inner msgdef message (scanning first 36 bytes for a known type)
    inner_notes = decode_inner_message(data, "raw")
    lines.extend(inner_notes)

    # 4. If TinCat magic present, guess payload offset and try decoding there
    if hdr.get("magic_at_0") and hdr.get("payload_len_at_16_BE"):
        payload_len = hdr["payload_len_at_16_BE"]
        payload_off = len(data) - payload_len
        if payload_off > 0:
            lines.append(f"  Trying payload at offset {payload_off} (len={payload_len}):")
            inner_notes2 = decode_inner_message(data[payload_off:], f"payload@{payload_off}")
            if inner_notes2:
                lines.extend(inner_notes2)

    # 5. Try TinCat_Scramble decryption on the full packet with candidate keys
    candidate_keys = [
        "user", "password", "asdf",
        "TinCat", "tincat", "Funatics", "SADK", "sadk",
        "Siedler", "siedler",
    ]
    for key in candidate_keys:
        dec = try_decrypt_with_keys(data[:32], [key])  # Only try first 32 bytes
        for k, dec_bytes, strs in dec:
            # Only report if decryption reveals a known msg type or interesting strings
            typed = [s for s in strs if len(s) >= 4 and all(32 <= ord(c) < 127 for c in s)]
            msgtype_found = False
            for off in range(min(4, len(dec_bytes)-2)):
                t = struct.unpack_from("<H", dec_bytes, off)[0]
                if t in MSG_NAMES:
                    lines.append(f"  SCRAMBLE-DECRYPT with key={k!r}: type {t} ({MSG_NAMES[t]}) at dec_off+{off}")
                    msgtype_found = True
            if typed and not msgtype_found:
                lines.append(f"  SCRAMBLE-DECRYPT with key={k!r}: strings={typed}")

    return lines


# ── Stream buffer (proper TCP reassembly) ────────────────────────────────────

class StreamBuffer:
    """
    Accumulates raw TCP bytes, yields complete 'chunks' to log.
    We log every recv() as one unit (since we don't know message framing yet),
    but also save the full binary stream for offline analysis.
    """
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)

    def flush(self) -> bytes:
        out = bytes(self.buf)
        self.buf = bytearray()
        return out


# ── Logging ──────────────────────────────────────────────────────────────────

_log_lock = threading.Lock()
_conn_counter = 0
_conn_lock = threading.Lock()


def next_conn_id():
    global _conn_counter
    with _conn_lock:
        _conn_counter += 1
        return _conn_counter


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] {msg}"
    print(line)
    with _log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_packet(direction: str, conn_id: int, peer: str, data: bytes, bin_file):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    # Save raw bytes to binary capture file
    if bin_file:
        marker = f"[{ts}] {direction} {len(data)} bytes\n".encode()
        with _log_lock:
            bin_file.write(marker)
            bin_file.write(data)
            bin_file.write(b"\n")
            bin_file.flush()

    sep = "─" * 62
    lines = [f"\n{sep}", f"  conn={conn_id}  {peer}"]
    lines += analyze_packet(data, direction)
    lines.append(f"  HEX ({min(len(data), 256)} of {len(data)} bytes):")
    lines.append(hex_dump(data[:256]))
    if len(data) > 256:
        lines.append(f"    ... ({len(data)-256} more bytes not shown)")

    for line in lines:
        log(line)


# ── Proxy core ───────────────────────────────────────────────────────────────

def recv_all(sock: socket.socket, buf: StreamBuffer, stop_evt: threading.Event):
    """Receive data, accumulate in buffer, return chunks on idle or close."""
    try:
        while not stop_evt.is_set():
            sock.settimeout(0.5)
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                # Yield anything accumulated after idle
                if buf.buf:
                    yield buf.flush()
                continue
            if not chunk:
                break
            buf.feed(chunk)
            # Small sleep to let TCP deliver rest of the same message
            import time
            time.sleep(0.005)
            # If nothing more arrives in 5ms, yield what we have
            sock.settimeout(0.005)
            try:
                more = sock.recv(65536)
                while more:
                    buf.feed(more)
                    more = sock.recv(65536)
            except socket.timeout:
                pass
            if buf.buf:
                yield buf.flush()
    except Exception:
        pass
    if buf.buf:
        yield buf.flush()


def pipe(src, dst, direction, conn_id, peer, stop_evt, bin_file):
    buf = StreamBuffer()
    try:
        for data in recv_all(src, buf, stop_evt):
            log_packet(direction, conn_id, peer, data, bin_file)
            if dst:
                try:
                    dst.sendall(data)
                except Exception:
                    break
    except Exception as e:
        log(f"  [pipe error ({direction}): {e}]")
    finally:
        stop_evt.set()


def handle_client(client_sock, client_addr, forward):
    conn_id = next_conn_id()
    peer = f"{client_addr[0]}:{client_addr[1]}"
    log(f"\n{'#'*62}")
    log(f"  CONNECTION #{conn_id}  {peer}")
    log(f"{'#'*62}")

    # Open binary capture file for this connection
    os.makedirs(BIN_DIR, exist_ok=True)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bin_path = os.path.join(BIN_DIR, f"conn_{conn_id}_{ts_str}.bin")
    bin_file = open(bin_path, "wb")
    log(f"  Binary capture: {bin_path}")

    real_sock = None
    if forward:
        try:
            real_sock = socket.create_connection((REAL_HOST, REAL_PORT), timeout=5)
            log(f"  Forwarding to real server {REAL_HOST}:{REAL_PORT}")
        except Exception as e:
            log(f"  Could not reach real server: {e}  (capture-only mode)")

    stop_evt = threading.Event()

    t1 = threading.Thread(target=pipe, args=(client_sock, real_sock, "c2s", conn_id, peer, stop_evt, bin_file), daemon=True)
    t2 = None
    if real_sock:
        t2 = threading.Thread(target=pipe, args=(real_sock, client_sock, "s2c", conn_id, peer, stop_evt, bin_file), daemon=True)

    t1.start()
    if t2:
        t2.start()
    t1.join()
    if t2:
        t2.join()

    bin_file.close()
    client_sock.close()
    if real_sock:
        real_sock.close()
    log(f"\n  DISCONNECTED #{conn_id}  {peer}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SaDK Lobby Proxy v2")
    parser.add_argument("--forward", action="store_true",
                        help=f"Forward to real server {REAL_HOST}:{REAL_PORT}")
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    args = parser.parse_args()

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"SaDK Lobby Capture Log v2\nStarted: {datetime.now()}\n\n")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((LISTEN_HOST, args.port))
    except PermissionError:
        print(f"ERROR: Cannot bind to port {args.port}. Run as Administrator.")
        sys.exit(1)

    srv.listen(5)
    print()
    print("╔══════════════════════════════════════════╗")
    print("║   SaDK Lobby Proxy v2 / Scramble-aware   ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  Port    : {args.port}")
    print(f"  Forward : {'YES → ' + REAL_HOST + ':' + str(REAL_PORT) if args.forward else 'NO (capture only)'}")
    print(f"  Log     : {LOG_FILE}")
    print(f"  Binaries: {BIN_DIR}/")
    print()
    print("  LobbySettings.ini must have: Host = \"127.0.0.1\"")
    print("  Waiting for connection... (Ctrl+C to stop)")
    print()

    try:
        while True:
            client_sock, client_addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, client_addr, args.forward), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nStopped. Log:", LOG_FILE)
    finally:
        srv.close()


if __name__ == "__main__":
    main()
