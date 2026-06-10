"""
Static configuration & protocol constants for the SaDK lobby stub server.

Everything here was reverse-engineered from SADK.exe + tincat3.dll (see
SESSION_STATUS.md). Values that affect the wire format must NOT be changed
without re-validating against the real client.
"""
import os

# ── Package paths ─────────────────────────────────────────────────────────────
PKG_DIR   = os.path.dirname(os.path.abspath(__file__))
REPO_DIR  = os.path.dirname(PKG_DIR)
DATA_DIR  = os.path.join(PKG_DIR, "data")
MSGDEFS_PATH = os.path.join(DATA_DIR, "msgdefs.ini")   # the game's own schema, bundled

LOG_FILE = os.path.join(REPO_DIR, "tincat_server.log")
BIN_DIR  = os.path.join(REPO_DIR, "sadk_captures")

# ── Listener ports ────────────────────────────────────────────────────────────
LOBBY_PORT = 7070   # main lobby connection
UC_PORT    = 7071   # UC/chat second connection (MUST differ from lobby port)
WORLD_PORT = 5479   # village/world third connection
GAME_PORT  = 5480   # dedicated game-server connection (the joiner's LobbyComm::GameServerConnection
#   endpoint when GAME_CONN_VIA_STUB routes joins to the stub). Kept SEPARATE from WORLD_PORT so a game
#   connection is NEVER mistaken for a lobby-world village conn — it logs in (153 ACK) but is NOT pushed
#   EnterWorld(1000) (which a GameServerConnection has no template for → would NULL-deref/crash). Capture-only.
REFEREE_PORT = 5481  # referee/match-arbiter server (LobbyComm::RefereeServerConnection). The match-START
#   gate: on NE_StartLoading the client logs into a referee (LM+0x580) and ABORTS the match after 5 failed
#   retries if it can't (s39.5, mp-match-start-needs-referee-server.md). Distinct from WORLD/GAME ports.

# IP the stub ADVERTISES to the client as the address to connect back to (chat/village/game servers).
# Same machine -> 127.0.0.1. For the WinXP-VM test (game in the VM, stub on the host), set env
# SADK_ADVERTISE_IP to the HOST's IP as seen FROM the VM, so the client dials the host, not the VM's
# own loopback. Listeners still bind 0.0.0.0 either way.
ADVERTISED_IP = os.environ.get("SADK_ADVERTISE_IP", "192.168.1.134")

# ── Hardcoded test account ────────────────────────────────────────────────────
TEST_USERNAME  = "test"
TEST_PASSWORD  = "test"     # raw, SHA-512 hashed on use
TEST_PERM_ID   = 1
TEST_CHAR_ID   = 1
TEST_CHAR_NAME = "Testler"

# GameServerData (TYPE 170) wire layout. "old" == ServerInfoOld == the canonical
# msgdefs.ini schema (u16 counts + spectators + subtype + room_id). The real
# tincat3.dll rejects the emulator's "adk" byte-count variant (s6). Keep "old".
GAMESERVERDATA_FORMAT = "old"

# Avatar data blob from the AdK emulator (LobbyProcessor._nicknameData).
NICKNAME_DATA = bytes.fromhex(
    "000000003900000000000000000000000000000000000000"
    "a2000000785edbc9c8800cd880b8842195a1184c1631e000"
    "ff819891094508668e438300886265604788beb8ce644b0c"
    "8d0d1c05004a9b0ff3"
)

# ── Multi-client hosting / multiple players (s39.5) ───────────────────────────
# Lets MORE THAN ONE client log in as DISTINCT players (a host + a joiner) so game
# hosting and joining can actually be tested, and makes a game hosted by client A
# visible to client B (a process-global game registry instead of the old
# per-connection server list). See sadk_lobby/players.py + sadk_lobby/registry.py.
#
# ⛔ OFF BY DEFAULT. With the flag OFF the stub is byte-identical to before:
# every connection serves the single hardcoded test account (PLAYERS[0]) and game
# servers stay per-connection. Turning it ON changes the stub's WIRE behaviour in
# the MULTI-client case (it serves a second player's identity, and relays one
# client's hosted game to another client) — per HARNESS.md that is a wire-behaviour
# change requiring a USER-APPROVED Engagement Record before it is run against live
# clients (engagement_records/2026-06-08_multi-client-hosting.md). SINGLE-client
# output is unaffected either way (the default player == the old TEST_* identity).
MULTI_CLIENT_HOSTING = True

# Player accounts the stub can serve. PLAYERS[0] MUST stay the default/test player
# (perm_id == TEST_PERM_ID): it is byte-identical to the old hardcoded identity and
# is the fallback for unknown / single-user logins. Add a player by appending a
# dict with a UNIQUE perm_id and the account `username` you put in THAT client's
# data/lobby/config/LobbySettings.ini. Appearance is shared (NICKNAME_DATA) for now.
#
# Two-client test recipe: client A's LobbySettings account = "test"  (→ Testler,
# perm 1); client B's = "test2" (→ Siedler, perm 2). With MULTI_CLIENT_HOSTING on,
# any other username auto-registers as a fresh player on first login.
PLAYERS = [
    {"username": TEST_USERNAME, "perm_id": TEST_PERM_ID,
     "char_id": TEST_CHAR_ID, "char_name": TEST_CHAR_NAME},   # PLAYERS[0] = default
    {"username": "test2", "perm_id": 2, "char_id": 2, "char_name": "Siedler"},
]

# When a joiner clicks Join, the stub answers RequestConnectionData(221) with
# ConnectionData(222) carrying the GAME server's address. By default that is the
# HOST's own advertised address (from its 168) — the original P2P design, where the
# joiner dials the host directly (and the stub never sees that connection).
#
# Flip this ON (with MULTI_CLIENT_HOSTING) to instead return the STUB's own DEDICATED
# game address (ADVERTISED_IP:GAME_PORT, :5480 — NOT the lobby-world :5479), so the
# joiner dials the STUB. That lets the stub LOG/CAPTURE the game-connection handshake
# (the pre-match room/slot protocol we have NOT reversed yet — msgdefs has no slot
# message; it rides this connection) and, later, act as the game server / relay. The
# :5480 listener does the login (153 ACK) but does NOT push EnterWorld(1000) — that
# lobby-world message would crash a GameServerConnection. Read-only capture lever for
# the next layer; same Engagement Record as MULTI_CLIENT_HOSTING. OFF = faithful P2P.
GAME_CONN_VIA_STUB = False

# ── TinCat transport constants ────────────────────────────────────────────────
MAGIC       = 0xDABAFBEF
FROM_CLIENT = 0xEFFFFFEE
FROM_SERVER = 0xEFFFFFCC
PREFIX_SIZE = 0x1C          # 28-byte TinCat header

PAYLOAD_MAGIC = 0x26B6      # lobby app-payload magic (Magic + Type1 + Type2)

# TinCat frame types (header Type field)
MSG_HANDSHAKE_CONNECT   = 3
MSG_HANDSHAKE_CONNECTED = 5
MSG_APPLICATION         = 2
MSG_PING                = 11

# Handshake payload geometry
HANDSHAKE_USERNAME_SIZE = 0x20   # 32
HANDSHAKE_PASSWORD_SIZE = 0x08   # 8
HANDSHAKE_SIZE          = 0x34   # 52
REPLY_PASSWORD          = bytes([0x2D, 0, 0, 0, 0, 0, 0, 0])

# ── Chat (second-connection) protocol ─────────────────────────────────────────
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
VILLAGE_MSG_ENTER_WORLD = 1000    # 0x3E8 — HandleEnterWorld @0x46f470 (SERVER → client, the reply)
VILLAGE_SENDGAMEDATA    = 74      # 0x4A NETMSG SendGameData — the game-data ENVELOPE that carries every
#   village/world message (1000+). s35 live+RE: the client's inbound bridge (tincat3
#   TinCat_DispatchInboundToSADK @0x100307a0) ONLY routes NETMSG 73(bundle)/74 to
#   VillageServerConnection::HandleMessage, extracting the inner `msg_type` as the dispatch key. So
#   EnterWorld(1000) MUST ride a SendGameData(74) envelope: {type:u16, msg_type:u32=1000, data:MEMBLOCK=
#   <EnterWorld body>}. A bare 1000 frame is silently DROPPED by the bridge (74!=0x49/0x4a → return).
WORLD_LOGIN_REQUEST_MSGTYPE = 0x27D2  # 10194 — the inner msg_type the client SENDS as SendGameData(74)
#   {data="code"=0xAFFEDEAD} once its village transport is AUTHORIZED (Village_SendEnterWorld_2002
#   @0x46b990, forced via tools/force_send2002.py). THE cue to reply EnterWorld(1000). (0x46b990 builds
#   type 0x7D2; the send path category-encodes it to wire msg_type 0x27D2 = (0x20<<8)|0x7D2.)

# ── In-world stage (after EnterWorld 1000) — s35 ──────────────────────────────
VILLAGE_MSG_WORLD_LOGIN_ACK = 1006        # 0x3EE — HandleWorldLoginAck @0x46e8b0. THE loading-screen gate:
#   the server confirms the world session by sending a "code" MEMBLOCK whose first dword == 0xDEADBEEF →
#   client sets loginAckReceived(+0x224)=1 and finalizes the UC conn (FUN_0047e920). Without it the client
#   sits on the loading screen forever. Any other code is ignored.
WORLD_LOGIN_ACK_CODE = 0xDEADBEEF         # the world-login magic the client compares in msg 1006.
VILLAGE_MSG_PONG = 0xED7                   # 3799 — HandlePongCode @0x46be00; our reply to the client's
#   in-world PingCode (keepalive round-trip; the PongCode value isn't validated, only RTT timing).
VILLAGE_PINGCODE_MSGTYPE = 0x2ED6          # 11990 — the client's in-world keepalive PingCode arrives as
#   SendGameData(74){msg_type=(0x20<<8)|0xED6}; SendWorldReadyAck @0x46bd00 emits it every ~30s.
VILLAGE_MSG_WORLD_TICK = 1005               # 0x3ED — HandleWorldTick @0x46f420 (sim heartbeat). Body = a
#   64-byte "tick" MEMBLOCK (reader vtable+0x20, len 0x40). OPTIONAL/post-gate — held OFF for the first
#   isolated 1006 drive so a render-gate failure isn't conflated with a missing world clock.

# WORLD ENTRY — how the client leaves character-selection (s30 — multi-agent static RE, CORRECTED).
#
# Leaving char-select into the 3D world is driven ENTIRELY by the server PUSHING village msg 1000
# (EnterWorld). The user's click ("BETRETE WELT") sends ZERO network — it only arms a client-side
# action; the client then waits for the server to push 1000. HandleEnterWorld @0x46f470 calls
# LobbyManager::SetState(VillageEntered=9) as its FIRST instruction, BEFORE parsing the body, so a
# single well-framed 1000 enters the world even with ChatChannelsCount=0 / dummy values.
#
# BODY SCHEMA (s35 — CORRECTED via 30-agent RE on the decrypted dump; supersedes the all-u32 guess):
#     STRING Worldname | MEMBLOCK0x20 ServerPerm | MEMBLOCK0x20 ChatChannelsCount(first dword=N) |
#       N×(MEMBLOCK0x20 ChatChannelZone, MEMBLOCK0x20 ChatChannelID)
#   - HandleEnterWorld @0x46f470 reads Worldname via reader vtbl+0x30 (ReadString) and EVERY other field
#     via vtbl+0x18 (ReadMemBlock(dst,0x20)) — length-prefixed MEMBLOCKs (int32 len + bytes), NOT raw u32.
#     village.enter_world_body() is correct; this comment used to be wrong (the u32 reading desyncs the parse).
#   - Serialization rule (tincat3 PropertyDataConverter @0x100110E0/0x100112B0): POSITIONAL; VAR types
#     {MEMBLOCK,STRING,WSTRING} get an int32-LE length prefix; FIXED scalars {u8..u64,float,bool} are raw
#     little-endian. The whole post-EnterWorld in-world protocol is mapped in IN_WORLD_PROTOCOL.md.
#
# ★★ CORRECTION (s30): THERE IS NO SEPARATE "VILLAGE MAGIC". The whole client uses ONE TinCat comm
# layer, magic 0x26B6 — `LobbyComm_System_Initialize` (SADK 0x4640f0) is the ONLY CreateCommLayer call
# in the binary; lobby, UserComm and Village/World connections all multiplex that single layer + its
# single PropertySet factory (*(*(LobbyManager+0x50)+0x20)). msg 1000 rides 0x26B6, same as login.
# The months-long "hunt the overlay magic" was a red herring (the overlay's `push 0x62…` is metamorphic
# decoy arithmetic, and no capture ever held a village magic).
#
# ★★ THE REAL BLOCKER = TEMPLATE-REGISTRATION TIMING. The factory starts EMPTY; tincat3 registers the
# 221 msgdefs types, and the village types 1000-1006 are registered LATER, by SecuROM-overlay code
# during the village/world connection setup that runs AFTER char-select. Before that,
# cPropertyFactory::CreatePropertySet(0x3E8) (tincat3 0x10013830, vtable +0x0C) returns NULL and
# DeserializeProperty NULL-derefs → the historical "push 1000 = crash" was pushing too EARLY (no
# template yet), NOT a magic/format error. (s26/s27 pushed immediately after 214; the template wasn't
# registered yet.)
#
# STRATEGY: push 1000 with magic 0x26B6, on a DELAY after the token handshake (214), betting the overlay
# has registered the village templates by then. If the client still crashes, the templates need a later
# trigger (the actual BETRETE WELT engagement) — find the exact moment with a live breakpoint on
# tincat3!RegisterPropertySet (0x10013710), watching msgType 0x3E8-0x3EE. See WORLD_ENTRY_PLAN.md.
VILLAGE_PAYLOAD_MAGIC = 0x26B6      # msg 1000 rides the single lobby comm-layer magic (NOT a separate layer)
ARM_ENTER_WORLD       = True       # ⛔ default OFF — flipping True changes the stub's WIRE behavior (pushes
#   msg 1000 UNPROMPTED) → needs a USER-APPROVED Engagement Record (engagement_records/2026-06-07_push-
#   enterworld.md) + the user present to observe. s39 LIVE-CONFIRMED the wait-state (probes/ +
#   tincat_server.log): after the VILLAGE conn's 153 ACK the client parks at LobbyManager EnteringVillage(8)
#   waiting for the SERVER to push EnterWorld (msg 1000); the client's own 0x27D2 cue never comes (send-2002
#   @0x46b990 is dormant) → deadlock. When ARMED, dispatch._h_send_token pushes village.send_enter_world(conn)
#   on the village conn ENTER_WORLD_DELAY s after the 153 → HandleEnterWorld → SetState(VillageEntered=9).
#   This is the harness-ENDORSED action for this wait-state (provide the awaited msg via the real mechanism —
#   NOT force ActivateScreenById). After arming, re-run tools/probe_lobby_world_entry.py to confirm state 9 +
#   whether the world RENDERS (the s36 no-CD build stalled post-9 on an empty observer — re-verify on clean).
#   (Supersedes the old s34b "pushing 1000 cold crashes / wait for the client's 2002" model: send-2002 is
#   dormant, so waiting for the 2002 deadlocks — exactly what the live probes show.)
ENTER_WORLD_WORLDNAME = "world1"    # must match the ServerType=4 entry name/map (a real local world)
ENTER_WORLD_DELAY     = 2.0         # seconds after the village 153 ACK before pushing 1000 (settle + let templates register)

# s28 relic: periodic re-send of the ServerType=4 village GameServerData(170) on the LOBBY conn to
# "re-trigger HandleRoomServerDescriptor → LoadLevel". s34 RE (OpenUserComm @0x470b50) proved village
# entry does NOT use 170/221/222 — it dials a pre-stored handle, and entry is driven by EnterWorld(1000)
# → SetState(9) → finalize. So the resend is stale, and it fires DURING world-entry (a possible crash
# culprit). Off by default now; flip True only to re-test that old theory.
RESEND_VILLAGE_DESCRIPTOR = False

# ── MP server browser (s38) — make the lobby's server browser FUNCTIONAL ──────────────────────────────
# The goal: a working server browser (find + join), not walking the 3D world. RE map in
# memory/mp-server-browser-join-path.md + memory/server-list-entry-validity-serverdatablock.md.
#
# MATCH KEY. The client decides a VILLAGE entry is joinable (Enter button enables) iff some list entry
# has entry.roomId(+0x30) == DAT_0087aed8. That global is the client's LobbyClient/ProtocolVersion
# (LobbyClient_LoadProtocolVersion @0x465380 → GetPrivateProfileIntA @0x004651c0, default -1 if the ini
# key is absent). The stub advertises roomId as the FIRST field of the 170 ServerDataBlock (BIG-ENDIAN
# u32); it MUST equal the client's ProtocolVersion or the Enter button stays grey forever. s28 RPM
# live-confirmed the live value was 1000 (and our roomId=1000 matched → entry joinable). If a given
# install reports a different ProtocolVersion — read DAT_0087aed8 live (RPM 0x8aed8+imagebase) or check
# the client's LobbyClient ini — set this to match. ⚠ If the client side is -1/unset, NOTHING the stub
# sends will ever match (the #1 silent-fail cause of a populated-but-greyed browser).
LOBBY_PROTOCOL_VERSION = 1000

# GAME browser (WorldScreen → BrowseGameDialog, the bottom-left BROWSE button). It lists GAME servers =
# NETMSG 170 with server_subtype=1 (AddOrUpdateDescriptor @0x46a440 routes desc+0x29: 1=game list
# this+0x7c, 2=village list this+0x68; the subtype-1 fill FUN_0048da70 needs NO ServerDataBlock). A client
# that hosts a browsable game sends its AddGameServer(168) with server_subtype=1 ITSELF (live-confirmed:
# 'Siedlerwill spielen' arrived subtype=1), so real hosted games route to the game browser on their own —
# the stub relays them as-is from the registry with their real player counts. No synthetic game entry is
# injected (the old FAKE_GAME placeholder, which showed a phantom "0/2", was removed).

# ── Referee / match-arbiter server (s39.5) ────────────────────────────────────────────────────────────
# The match-START wall (memory/mp-match-start-needs-referee-server.md, binary-PROVEN build 34688): on every
# NE_StartLoading the client arms a referee login (LM+0x3625=1) and the per-frame loop calls
# RefereeServerConnection::Login (FUN_004793f0) up to 5x ([Reconnector] timesClientRetries) then ABORTS the
# match. The referee is the ranked-match arbiter (a trusted 3rd connection that watches the P2P game so a
# rage-quitting host can't dodge a loss). Our stub ran lobby/UC/world but NO referee → every match aborted.
#
# RE'd flow (referee-server-re workflow, docs/REFEREE_RE_findings.json):
#   1. ASSIGN: client sends AssignServer(189, server_type=4) on the lobby conn with a ticket (category 0x108);
#      stub must reply GameServerData(170) server_type=4 + server_subtype=5 + SAME ticket_id + server_id/ip/port.
#      tincat3 FUN_10021520 gates the referee-assigned path EXACTLY on desc.server_type==4 && desc.server_subtype==5.
#      ⚠ The UC server is ALSO assigned via AssignServer(189, type=4, subtype=4)→UsercommServerData(192); the
#      referee is the SECOND type-4 assign on a lobby conn (UC is assigned once at login, referee later at
#      state>5). We branch on that order (and log the wire subtype to confirm the cleaner discriminator live).
#   2. RESOLVE: the referee server_id must resolve to ip:port → also advertise it on the type-4 server-list.
#   3. CONNECT + LOGIN: client dials REFEREE_PORT, runs the SAME base login as UC/village (CheckVersion 188 →
#      token 211/213 → AddResult 153), then opens the referee data channel.
#   4. LOGIN VERDICT: the stub PUSHES one inbound bare LobbyMessage (category 3) id=0xDCA LoginSuccess carrying
#      a PermID. The verdict is the MESSAGE ID (0xDCA=ok clears the gate; 0xDCB=fail). Neither validates PermID.
#      LoginSuccess alone clears the 5x-retry abort; RegisterGame ack/result is second-tier (only if the host emits it).
REF_CATEGORY        = 3
REF_LOGIN_OK        = 0xDCA   # LoginSuccessReceived  (FUN_0047ac20) — clears the match-start gate
REF_LOGIN_FAIL      = 0xDCB   # LoginFailedReceived   (FUN_0047ad50) — NEVER send this
REF_REGISTER_GAME   = 0xDB6   # RegisterGame (client→referee): GameID, MapGUID(16B), MapName, MapSettings, ...
REF_REGISTER_ACK    = 0xDB7   # RegisterGameAck (referee→client): GameID, Result(0=ok)
REF_REGISTER_RESULT = 0xDB8   # RegisterGameResult: GameID, Result(0=ok)+GameSeed(u32)
REF_FINISH_GAME     = 0xDC0
REF_GIVEUP_GAME     = 0xDD4
REF_CLAIM_CHEST     = 0xDAC
REF_SERVER_ID       = 60      # the referee's server_id (distinct from the FAKE_VILLAGE id=50)
REF_GAME_SEED       = 0x5EED  # fixed GameSeed echoed in RegisterGameResult (value never validated by the client)

# ⛔ ADVERTISE_REFEREE_SERVER (default OFF): when ON, the stub stands up the REFEREE_PORT listener, advertises
# the referee on the type-4 server-list, and replies to the 2nd type-4 AssignServer(189) with 170(subtype=5)
# instead of 192. This is a stub WIRE-BEHAVIOR change → per HARNESS.md requires a USER-APPROVED Engagement
# Record (engagement_records/2026-06-09_referee-server.md, pre-approved by J4n1X) BEFORE running live. With it
# OFF the stub is byte-identical to today (every AssignServer → 192, no referee port). This step alone is the
# READ-ONLY-in-effect Part A: it lets the client CONNECT to our referee + reveal its login framing in the log;
# it does NOT push anything that drives match state.
ADVERTISE_REFEREE_SERVER = True
# ⛔ ARM_REFEREE (default OFF): when ON, after the referee conn's 153 login the stub PUSHES LoginSuccess(0xDCA)
# — the genuine message the client's match-start gate waits for (NOT a forced bypass). Separate flag so Part A
# (capture the framing) precedes Part B (push) — flip only after a live capture confirms the LoginSuccess bytes.
ARM_REFEREE = True
# The LoginSuccess names-flag is the ONE byte-level unknown (bit15 of the 0xDCA type word). False = names-off
# (type word 0x3DCA + a bare u32 PermID — the primary guess, matching the client's own send-side); True =
# names-on (0xBDCA + name-keyed 'PermID' + 0xFFF end-marker). Flip if names-off doesn't clear the gate.
REF_LOGIN_SUCCESS_NAMES = False

# ⛔ REFEREE_ALSO_PUSH_UC (default ON): the CORRECTED referee fix answers the single type-4 AssignServer(189)
# with GameServerData(170, subtype=5) instead of UsercommServerData(192) — that single 189 is the REFEREE
# one-shot (re-RE'd s39.6: SADK has exactly ONE type-4 189 caller, latched; the 2 live runs show exactly ONE
# 189 per client). But chat currently reaches the UC server (:7071) ONLY because the client acted on that 192.
# So when we send the 170, we ALSO push a 192 (unsolicited, ticket_id=0 — tincat3's 0xc0 handler FUN_10030420
# does not validate the ticket category, so it dials :7071 regardless) to PRESERVE chat. Set False ONLY if a
# live capture proves chat survives on the lobby transport without it (the client's UserComm channel opens on
# nChatServerHandle = the lobby handle, independent of the 192 — so chat MAY work either way; the push is the
# conservative default). Only meaningful when ADVERTISE_REFEREE_SERVER is on.
REFEREE_ALSO_PUSH_UC = True

# REF_USE_GAMEDATA_ENVELOPE (default ON): wrap the referee LobbyMessages (LoginSuccess 0xDCA, RegisterGame
# acks) in a SendGameData(74) envelope, exactly like the sibling cat-2 village LobbyMessages (world-login
# 0x27d2, PingCode 0x2ed6, …, all built by the same LobbyMessage builder FUN_0048fb00). s39.6 LIVE CRASH
# (crashdump.dmp, tools/minidump_exc.py): a BARE referee frame (Magic|0x3dca|0x3dca|body) made tincat3
# PropertyDataConverter::Deserialize call CreatePropertySet(0x3dca) → NULL (no registered template) → NULL
# deref → client crash (the EnterWorld(1000) crash class). The 74 NETMSG HAS a template, so tincat3
# deserializes the OUTER 74 and the referee conn's handler reads the INNER LobbyMessage MANUALLY (no
# CreatePropertySet) → no crash. Wire: Magic|74|74|msg_type=type_word(u32)|data=MEMBLOCK(field body).
# Set False to send the (crashing) bare form only for diagnostics.
REF_USE_GAMEDATA_ENVELOPE = True
