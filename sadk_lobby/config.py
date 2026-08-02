"""
Static configuration & protocol constants for the SaDK lobby stub server.

Reverse-engineered from SADK.exe + tincat3.dll. Values tagged [PROVEN] are backed by
a binary address and live read-only evidence; values tagged [TODO] are unverified.
Anything that affects the wire format must be re-validated against the real client
before it is changed.

There are NO feature flags here, with ONE user-authorised exception
(`VILLAGE_NPCS_ENABLED`, see below). Everything else the stub knows how to do, it
does by default. (Historically half of this file was `⛔ off-by-default` toggles;
that bloat is gone — see HARNESS.md §5.)
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

# ── Ambient village NPCs ──────────────────────────────────────────────────────
# ⚠️ THE ONE FEATURE FLAG IN THIS FILE, and it exists by EXPLICIT USER INSTRUCTION
# (J4n1X, 2026-08-02: "let's move NPC spawning behind a flag and disable it in the
# config for now, I wanna pursue something else"). HARNESS.md §5 forbids an agent
# adding a flag on its own initiative — it does NOT forbid the maintainer asking for
# one. Recorded here so a later session reads this as authorised, not as drift.
#
# The NPC subsystem itself is NOT broken and NOT abandoned: msg 1004 spawns them,
# they render with per-npcidx models, they speak their actChat lines, and the wire
# format is documented in docs/SOURCEMAP.md §"The NPC system". It is parked because
# two questions need answers that the binary cannot give (npcidx→appearance lives in
# the encrypted game data; the OpenShop click path needs a live trace).
#
# Set back to True to bring the whole cast back — nothing else needs changing.
VILLAGE_NPCS_ENABLED = False

# ── Persistent characters ─────────────────────────────────────────────────────
# ⚠️ Second user-authorised feature flag (J4n1X, 2026-08-02: "on avatar selection the message
# is 'login attempt failed'. We have to roll back this avatar feature behind a flag once more").
# Same standing as VILLAGE_NPCS_ENABLED — HARNESS §5 permits a maintainer-requested flag.
#
# ⛔ THIS ONE MARKS A LIVE REGRESSION, not a parked experiment. Turning persistent characters ON
# broke character selection: the client reports "login attempt failed" after picking an avatar.
# OFF restores exactly the behaviour that worked all session: one implicit character per account,
# char_id == perm_id == an in-memory sequential id, appearance = the shared NICKNAME_DATA blob.
#
# Prime suspects for the regression, in order (none yet verified — see docs/SOURCEMAP.md):
#   1. char_id != perm_id. The client's own avatar id IS its PermID and the CharacterManager is
#      keyed by char_id; if the post-selection login presents the ACCOUNT id while the character
#      lives under a 100_000-range id (or vice versa), the own-avatar lookup misses and the
#      village login fails — the "WTF?! There is no avatar with that id in the CharacterManager"
#      path. This is the flaw the dual lookup in players.resolve_by_perm was meant to survive,
#      and it is the first thing to check in the client's LobbyComm.log.
#   2. The stored blob. A character created through the client's own flow may be incomplete if
#      creation never fully succeeded, leaving a character that lists but cannot be logged in as.
#   3. An empty character list on a fresh account taking a path the old code never exercised.
#
# The store, its schema and its tests are all intact and unused while this is False — the
# understanding is kept; only the wire behaviour reverts.
PERSISTENT_CHARACTERS_ENABLED = False

# ── Player accounts ───────────────────────────────────────────────────────────
# ⭐ There is NO account table. Any number of clients may log in at once, and the USERNAME each
# one types in the game's login box becomes that player's identity AND character name — the name
# over their settler, in the chat roster and on their hosted games (players.py). perm_ids are
# issued sequentially from 1 in first-seen order and stay stable per name for the life of the
# process (the client's own avatar id IS its PermID, so a changing id would orphan its avatar).
#
# Passwords, serials and CD-keys are NOT validated anywhere — they are decoded for logging only
# (crypto.decode_login_blob) and never compared against anything. Testers just need to pick
# DIFFERENT usernames from each other; anything at all works for the other fields.
#
# ⭐ Identity and appearance are now PERSISTENT (store.py, 2026-08-02): the perm_id and the
# character blob live in sadk_players.json, keyed by login name, and survive restarts. The
# perm_id MUST be stable — char_id == perm_id and the client's own avatar id is its PermID.
TEST_USERNAME  = "test"     # only the suggested name in the startup banner
TEST_PASSWORD  = "test"     # only the suggested password in the startup banner
TEST_PERM_ID   = 1          # defensive fallback owner id for stub-injected server entries

# ⛔ LEGACY / NO LONGER SENT. The AdK emulator's hardcoded character blob
# (LobbyProcessor._nicknameData). Every player used to wear this — its zlib payload contains the
# name "tester" in UTF-16LE, so everyone was literally the same character. Superseded by real
# per-player characters (store.py); a player without one now gets an EMPTY character list, which
# is what makes the client open its creation flow. Kept only as a decoding reference for the
# blob format: {u32 ?, u32 0x39, u32×4 zeros, u32 uncompressed_len, zlib stream}.
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

# [PROVEN 2026-08-02] The tincat3 CellManager only accepts a channel JOIN for a cell it already
# has in its registry (this+8): the ChannelJoined handler (tincat3 FUN_1000e4a0) looks the cell up
# FIRST and answers StatusReply(status=2) on a miss — without queuing the joined-event. The
# registry is populated ONLY by inbound ChannelInfo/PublishCell frames (dispatcher case 0 →
# FUN_1000ee30 → cell-record insert). Advertising a cell in EnterWorld(1000) feeds a DIFFERENT,
# SADK-side map (VillageServerConnection+0x164) and does NOT register it here — so every joinable
# cell must ALSO be published on the chat connection. Cells 16..31 are the per-zone LOCAL channels
# (WORLD_CHAT_CHANNELS below); before 2026-08-02 they were never published, the client rejected
# its own local-zone join (seen live: "StatusReply from client: cell=16 → REJECTED (status=2)"),
# and every LOCAL chat line was silently discarded by the client's null-check in
# UserCommConnection::ChatReceived@0x00480e30 (which logs its scope BEFORE that check).
ZONE_CHANNELS = [
    (16 + z, f"Zone {z}", f"Local chat, zone {z}", "Admin", 0, True)
    for z in range(16)
]

# ── In-world chat channels, advertised in EnterWorld(1000) ────────────────────
# [PROVEN 2026-08-01] The client keeps a std::map<byte zoneKey, u32 cellId> at
# VillageServerConnection+0x164, built ONLY from the (ChatChannelZone, ChatChannelID) pairs in
# EnterWorld. Chat tab → key (FUN_0046d5d0@0x0046d5d0):
#     tab 1 GLOBAL   → key 0xFF   (also auto-joined at world entry by HandleEnterWorld)
#     tab 2 LOCAL    → key = the player's CURRENT ZONE byte (conn+0x225), re-joined on every zone
#                      change by SetLocalChatZone@0x0046e860
#     tab 3 MINIGAME → key 0xFE   (tab is disabled in the UI, listed for completeness)
# ⛔ cell id 0 = INVALID (DAT_007db53c): the submit handler drops the message SILENTLY — no wire
# traffic, no local echo. Every id here MUST be non-zero.
# Zones seen live 2026-08-01: 0 = village square, 1 and 3 = side rooms (hall of fame / minigame).
# The zone field is 4 bits, so 0..15 is the complete space — we advertise all of it so LOCAL chat
# works in every room without needing to know which id is which.
GLOBAL_CHAT_CELL   = 1                     # matches DEFAULT_CHANNELS[0] ("System")
MINIGAME_CHAT_CELL = 2                     # matches DEFAULT_CHANNELS[1] ("Lobby")
LOCAL_CHAT_CELL_BASE = 16                  # zone N → cell 16+N (16..31), all non-zero
WORLD_CHAT_CHANNELS = ([(0xFF, GLOBAL_CHAT_CELL), (0xFE, MINIGAME_CHAT_CELL)]
                       + [(z, LOCAL_CHAT_CELL_BASE + z) for z in range(16)])

# ── Village / world-entry protocol ────────────────────────────────────────────
# World entry [PROVEN, s39 screenshot-confirmed on the clean build]: leaving char-select
# into the 3D world is driven ENTIRELY by the SERVER pushing inbound EnterWorld (msg 1000).
# The user's "Betrete Welt" click sends ZERO network; the client parks at LobbyManager
# EnteringVillage(8) waiting for 1000. HandleEnterWorld calls SetState(VillageEntered=9) as
# its FIRST instruction, so a single well-framed 1000 enters the world. The stub pushes it
# on the village conn a short delay after the 153 login ACK (dispatch._h_send_token).
# The client's own SendGameData(74){0x27D2} is NOT a world-login request — it is the LEAVE-VILLAGE
# request (msg 2002); see VILLAGE_LEAVE_REQUEST_MSGTYPE below. The stub does not wait for it at
# entry — it provides 1000 via the genuine mechanism (the server push).
VILLAGE_MSG_ENTER_WORLD = 1000    # 0x3E8 — HandleEnterWorld (server → client)
VILLAGE_SENDGAMEDATA    = 74      # 0x4A NETMSG SendGameData — the envelope that carries every
#   village/world message (1000+). [PROVEN, s35] The client's inbound bridge only routes NETMSG
#   73/74 to VillageServerConnection::HandleMessage and extracts the inner msg_type as the dispatch
#   key, so EnterWorld(1000) MUST ride a SendGameData(74) envelope. A bare 1000 frame is dropped.
VILLAGE_LEAVE_REQUEST_MSGTYPE = 0x27D2  # 10194 = (cat 2 << 12) | 0x7d2 → NETMSG **2002, LEAVE VILLAGE**
#   [PROVEN 2026-07-25/26] Sent by VillageServerConnection_SendLeaveVillageRequest_2002@0x0046bde0
#   (village vtable +0x40) with field "code" = 0xAFFEDEAD, immediately after
#   LobbyManager::SetState(LeavingVillage=10). Reached from the !LEAVE_VILLAGE_QUESTION confirm popup
#   via CLobbyClient::LeaveVillage@0x00503470 (which tail-jumps into it). It was long mis-named
#   "world-login request" — that error is what produced the match-start "clone".
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
VILLAGE_AVATAR_LOCATION_MSGTYPE = 0x27D0   # 10192 = (cat 2 << 12) | 0x7d0 → NETMSG **2000, AVATAR LOCATION**
#   [PROVEN 2026-08-01] The client's OWN position report — where the player actually IS. Sent ~3/s by
#   VillageServerConnection_SendAvatarLocation_2000@0x0046ca40, driven by the local player controller
#   (LobbyPlayerController_Update@0x0051ace0 → CLobbyClient_ReportOwnAvatarLocation@0x005034e0). Body is
#   the same bit-packed AvatarLocation block we send in 1001, minus the id/dtblcks header:
#   tick 16 · posx/posy/posz 11 · rot 7 · zone 4 · ghstzne 4 · rnng 1 · jmp 1 (village.parse_avatar_location).
#   Long dismissed as unhandled keepalive spam (connection._is_quiet_frame names it) — it is the OTHER
#   HALF of the presence protocol: the server relays it to the other clients as a 1001 refresh.

# RETIRED 2026-07-26 — `ANSWER_WORLD_LOGIN_REQUEST` / `WORLD_LOGIN_MAX_ANSWERS` are gone.
# They gated answering the client's 0x27D2 with a fresh EnterWorld(1000). BOTH settings were wrong
# answers to a misunderstood message: 0x27D2 is the LEAVE-VILLAGE request, so a 1000 told the client to
# ENTER when it asked to LEAVE (the "clone"), while the off/no-op setting hung it in LeavingVillage(10)
# forever. The stub now completes the leave the genuine way — by closing the village connection
# (dispatch._h_send_game_data → conn.close_graceful). No flag: working behaviour is the default
# (HARNESS §5). ER: engagement_records/2026-07-26_village-leave-close-connection.md
VILLAGE_MSG_WORLD_TICK = 1005               # 0x3ED — HandleWorldTick@0x46f620: WORLD-CLOCK SYNC (64-BIT tick, slews client clock; see village.send_world_tick)

# ── In-world presence (docs/IN_WORLD_PRESENCE.md) ────────────────────────────
# Bit-packed avatar/entity messages. 1001 is the one that makes a body VISIBLE: it allocates an
# AvatarProxy into VillageServerConnection+0x170. 1004 populates a separate *player* map at +0x174
# and is NOT the visible avatar. All are still UNPROVEN on the wire — spec is static-only.
VILLAGE_MSG_ENTITY_CREATE = 1001            # 0x3E9 — HandleEntityCreate@0x0046e1d0 (avatar spawn)
VILLAGE_MSG_ENTITY_UPDATE = 1002            # 0x3EA — HandleEntityUpdate@0x0046e390 (movement)
VILLAGE_MSG_ENTITY_REMOVE = 1003            # 0x3EB — HandleEntityRemove@0x0046e570 (despawn)
VILLAGE_MSG_PLAYER_CREATE = 1004            # 0x3EC — HandlePlayerCreate@0x0046f8c0 (player record)
# Where other players are spawned relative to the world origin, until real positions exist.
# posx/posz 1024 == world centre; posy 512 == ground (y=0) given bounds (-10..30).
AVATAR_SPAWN_SPREAD = 6.0                   # ring radius around the origin for placeholder avatars
# Wait after EnterWorld(1000) before spawning avatars, so the client has finished entering the
# world (SetState(VillageEntered=9)) and has an avatar container to insert into.
AVATAR_SPAWN_DELAY = 2.0

# ── Referee / match-arbiter server ────────────────────────────────────────────
# The match-START gate. RE'd fresh this session (docs/MATCH_START.md, sadk_noav.exe):
#   * StatePump_Tick@0x464ee0: at state>=6 calls LobbyServerList_RequestRefereeServer@0x468f60 ONCE,
#     which sends AssignServer(189, server_type=4, server_subtype=4) and registers
#     LobbyManager_SetRefereeServerAddress@0x4625d0 as the assigned-callback.
#   * The stub's assign RESPONSE must deliver a server_id to that callback → latched at LM+0x580 →
#     LobbyManager_InitRefereeServerConnection@0x462910 (pumped per-frame) resolves it via the
#     ConnectionManager (LM+0x50) and DIALS it. So the referee server_id must ALSO resolve to ip:port,
#     i.e. be advertised on the type-4 server list (same mechanism as the village server).
#   * On NE_StartLoading the client opens the referee data channel; RefereeServerConnection_OnReceive
#     @0x47b090 routes cat-3 LobbyMessages by id. The stub answers LoginSuccess(0xDCA) (clears the
#     5-retry abort — the verdict is the message ID, not the PermID value) and, for RegisterGame(0xDB6),
#     RegisterGameAck(0xDB7) + RegisterGameResult(0xDB8){GameSeed}. Without the GameSeed the lockstep
#     sim cannot start; all clients in a match must receive the SAME seed (a fixed value is fine).
# [VERIFY LIVE] The exact assign discrimination (UC vs referee 189) and the referee-channel framing were
# never nailed by the prior (removed) attempt without live captures — re-confirm against the real client.
REFEREE_PORT = 5481           # the RefereeServerConnection dials here (distinct from WORLD_PORT 5479)
REF_SERVER_ID = 77            # the referee's server_id (unique; must resolve on the type-4 server list)
# NOTE: the referee's ip:port is NOT pushed — the client ASKS for it with 221 RequestConnectionData
# and dispatch._h_connection_data answers 222 ConnectionData with REFEREE_PORT. Resolving
# REF_SERVER_ID there is what makes the referee dial-able at all.
# Delay between the referee conn's base-login 153 ACK and our LoginSuccess(0xDCA) push. The client
# never asks for that result (RefereeServerConnection::Login sends no message), so the 153 is the
# only cue. Small delay because a bare frame sent too early was previously linked to a client-side
# crash, and the 153 must first drive the client's own LoggedIn transition.
REFEREE_LOGIN_OK_DELAY = 0.5
# [LIVE TEST 2026-06-13 · ER engagement_records/2026-06-13_referee-assign-170.md] Reply a GameServerData(170)
# type4/sub5 to the referee AssignServer(189, type=4, subtype=4) so its cat-0x108 ticket routes into
# tincat3 GameServerManager_OnGameServerAssigned → SetRefereeServerAddress → LM+0x580. Set False to revert.
REPLY_REFEREE_ASSIGN = True
# [LIVE TEST 2026-06-14 · ER engagement_records/2026-06-14_game-server-assign-170.md] The host's match-
# server bring-up FUN_0046aaa0 sends AssignServer(189, type=5, subtype=1) after StartUpNetwork(4) and parks
# villageList+0x9c=-2 ("Connecting to Game Server"). Reply a GameServerData(170) for the host's OWN hosted
# game (type/sub ≠ 4/5) so tincat3 GameServerManager_OnGameServerAssigned@0x10021520 routes it non-referee
# → the default sink LobbyServerList_GameServerAssigned@0x469ad0 → fires the pending callback + clears
# villageList+0x9c. Set False to revert to the plain-192 behavior.
REPLY_GAME_SERVER_ASSIGN = True
REF_GAME_SEED = 0x5EED1234    # fixed lockstep determinism seed (client never validates the value)

# ⛔ REF_LOGIN_SUCCESS_DELAY was added and REVERTED on 2026-07-27 — the "server must push LoginSuccess
# after the referee 153" model was refuted the same day by LobbyGameScreen_Update@0x00435980: the
# CLIENT sends RefereeServerConnection::Login at MATCH START (gated on netmgr+0x3cc StartLoading and
# the arm flag screen+0x3625), and the server's job is to ANSWER it. See the ER for the full trace.

REF_CATEGORY        = 3       # all referee LobbyMessages are category 3 (type word = names<<15|cat<<12|id)
REF_LOGIN_OK        = 0xDCA   # LoginSuccess  (RefereeServerConnection_OnLoginSuccess) — clears the gate
REF_LOGIN_FAIL      = 0xDCB   # LoginFailed   (…_OnLoginFailed) — NEVER send this
REF_REGISTER_GAME   = 0xDB6   # RegisterGame (client→referee): GameID, MapGUID[16], MapName, MapSettings, …
REF_REGISTER_ACK    = 0xDB7   # RegisterGameAck (referee→client): GameID, Result(0=ok)
REF_REGISTER_RESULT = 0xDB8   # RegisterGameResult: GameID, Result(0=ok) + GameSeed(u32)
REF_FINISH_GAME     = 0xDC0   # end-of-match (logged, not on the start path)
REF_GIVEUP_GAME     = 0xDD4
REF_CLAIM_CHEST     = 0xDAC
