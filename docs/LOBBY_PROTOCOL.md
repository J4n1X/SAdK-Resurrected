# SaDK Lobby System — Reverse Engineering Report
**Game**: Die Siedler: Aufbruch der Kulturen (The Settlers: Rise of Cultures)  
**Developer**: Funatics / Blue Byte / Ubisoft (2008)  
**Status**: Lobby protocol substantially reversed (message-type catalogue complete). The village/world
(`:5479`) sub-protocol is only **PARTIALLY** reversed — see §3.2 caveats and `sadk_lobby/village.py`.  
**Last updated**: 2026-05-31

---

## 1. Server Endpoints

All connection data sourced from plaintext config files in the game install.

> **⚠️ HISTORICAL — these endpoints are DEAD.** The official Funatics lobby/ranking
> infrastructure was shut down ~2014. The IPs/hostnames below (`84.17.180.120`,
> `www.diesiedler2lobby.de:8777`, `sadk.funatics.de`) no longer resolve/respond and are
> recorded here only for reference. The revival stub stands in for them locally.

### 1.1 Lobby Server (`data/lobby/config/LobbySettings.ini`)
```
Host = 84.17.180.120   ← HISTORICAL, dead since ~2014
Port = 7070            ← TCP, main lobby connection
```

### 1.2 Secondary Lobby URL (`data/game/settings/network.ini`)
```
url      = www.diesiedler2lobby.de:8777   ← HISTORICAL, dead since ~2014
patchlevel = 9212       ← required client version, server rejects older clients
```

### 1.3 Ranking / Hall of Fame (HTTP, `LobbySettings.ini`) — HISTORICAL, dead since ~2014
```
GET http://sadk.funatics.de:7012/rankingMaster/ranking.php
  ?ranking=weekly|monthly|yearly
  &limit=20
  &offset=0
  &permID=<player_perm_id>   ← appended automatically (AppendPermID=1)
```

### 1.4 In-game Peer-to-Peer (`data/game/settings/network.ini`)
```
gamePort      = 5479   ← TCP/UDP, direct player-to-player game connection
broadcastPort = 6582   ← LAN broadcast discovery
broadcastTimeout = 10000 ms
```

---

## 2. Networking Middleware: `tincat3.dll`

The library `bin/tincat3.dll` is the proprietary Funatics networking layer ("TinCat 3").  
It implements the entire lobby client protocol. The game links against it dynamically.  
Reconstructing the lobby server requires implementing the same binary protocol.

Other DLLs present: `expat.dll` (XML parser), `fmod.dll` (audio), `NxCharacter.dll` (PhysX).

---

## 3. Binary Protocol

### 3.1 Wire Format

All communication is over **TCP** to port 7070.  
All messages are **binary**, little-endian.  
Every message begins with a `type` field — a **UNSHORT** (unsigned 16-bit integer) identifying the message.

#### Data Types
| Token | C type | Size | Notes |
|-------|--------|------|-------|
| `UNBYTE` | uint8 | 1 B | |
| `SIBYTE` | int8 | 1 B | signed |
| `UNSHORT` | uint16 | 2 B | |
| `SISHORT` | int16 | 2 B | signed |
| `UNLONG` | uint32 | 4 B | |
| `SILONG` | int32 | 4 B | signed |
| `LBOOL` | uint32 | 4 B | 0 = false, non-zero = true |
| `STRING N` | char[N] | N B | null-terminated, fixed-length buffer |
| `MEMBLOCK 0` | blob | variable | length-prefixed binary block |

`ticket_id` (UNLONG) is a client-generated nonce for matching async responses to requests.  
`perm_id` (UNLONG) is the server-assigned persistent player identity (survives re-logins).

### 3.2 Message Type Reference

Sourced verbatim from `bin/msgdefs.ini` / `msgdefs.ini` (identical files). The **catalogue of
lobby message types below is complete** (it is the game's own NETMSG schema). Note, however, that the
**in-world village/world sub-protocol (the `:5479` connection, message types 1000+) is only PARTIALLY
reversed** — the EnterWorld(1000) handshake is understood and drives the client into the rendered world,
but the full in-world message set (1001–1006, ticks, observer fan-out, entity overlays) is not yet a
finished, reimplementable spec. See `sadk_lobby/village.py` for the current (partly hypothesis-tagged) model.

#### Authentication & Session

| Type | Name | Key Fields |
|------|------|-----------|
| 4 | **RequestLogin** | nick(256), password(32), cd_key(128), keypool(UNSHORT), patchlevel, ticket_id |
| 71 | **RequestCreateAccount** | nick(256), password(32), cd_key(128), keypool, patchlevel, ticket_id |
| 201 | **StartAuthenticateSession** | key(MEMBLOCK) — client sends its ECDH (secp521r1) public key |
| 202 | **AckAuthenticateSession** | cipher(MEMBLOCK) — server's ECDH public key → shared secret |
| 203 | **SelfRegistration** | cipher(MEMBLOCK) |
| 204 | **AuthenticateUser** | cipher(MEMBLOCK) — client proves identity (Twofish-CTR credential blob) |
| 205 | **AuthenticateSupport** | cipher(MEMBLOCK) |
| 206 | **AuthenticateServer** | cipher(MEMBLOCK) — game server authenticates |
| 207 | **SessionKey** | perm_id, cipher(MEMBLOCK) — server assigns permanent ID + session key |
| 211 | **StartValidateTokenSession** | ticket_id |
| 212 | **AckValidateTokenSession** | nonce(MEMBLOCK) |
| 213 | **SendToken** | perm_id, cipher(MEMBLOCK) |
| 214 | **ValidateToken** | perm_id, cipher(MEMBLOCK), nonce(MEMBLOCK) |
| 183 | **CheckLevel** | level(UNBYTE) — probably access level check |
| 188 | **CheckVersion** | version(SISHORT), subversion(SISHORT) |
| 178 | **ChangePatchlevel** | patchlevel |

**Login flow (the real, reversed scheme — ECDH, NOT RSA; see `sadk_lobby/crypto.py`):**
```
Client → Server:  TYPE 201  StartAuthenticateSession (client ECDH secp521r1 public key)
Server → Client:  TYPE 202  AckAuthenticateSession   (server ECDH public key)
   → both sides derive a shared secret; the session key = SHA-512(shared) XOR-folded.
Client → Server:  TYPE 204  AuthenticateUser         (credentials in a Twofish-CTR blob)
Server → Client:  TYPE 207  SessionKey               (perm_id + session token)
   → login COMPLETES on a TYPE 153 AddResult ACK (errorcode=0), not on 207 alone.
```
The key exchange is **ECDH over secp521r1**; the session key is derived via **SHA-512 + XOR**;
credentials/tokens are sealed with **Twofish-CTR** (IV-prefixed, no MAC). There is **no RSA** anywhere
in this flow — earlier notes calling it "RSA-based" were wrong.

Or simpler/older flow:
```
Client → Server:  TYPE 4    RequestLogin (nick, password hash, cd_key)
Server → Client:  TYPE 42   Result       (success/failure)
Server → Client:  TYPE 207  SessionKey   (perm_id assigned)
```

---

#### Generic Responses

| Type | Name | Key Fields |
|------|------|-----------|
| 1 | **Simple** | data(UNLONG) — generic acknowledgement |
| 42 | **Result** | errorcode(UNBYTE), errormsg(32), ticket_id |
| 153 | **AddResult** | errorcode(UNBYTE), errormsg(32), id(UNLONG), ticket_id |

---

#### Channel / Chat System

| Type | Name | Key Fields |
|------|------|-----------|
| 2 | **ChatMessage** | mode, txt(256), ticket_id, from_id |
| 3 | **PrivateChatMessage** | mode, txt(256), cell_id, from_id, to_id, from_name(256) |
| 5 | **UserJoinedChannel** | perm_id, cell_id, nick(256) |
| 6 | **UserLeftChannel** | perm_id, cell_id |
| 7 | **ChannelInfo** | cell_id, usr_count |
| 16 | **InviteToChannel** | cell_id, perm_id, from_id |
| 17 | **RequestJoinChannel** | cell_id, ticket_id, option(UNSHORT), password(32), from_id |
| 18 | **RequestKickFromChannel** | cell_id, perm_id, ticket_id |
| 30 | **WhisperChatMessage** | mode, txt(256), cell_id, from_id, perm_id |
| 76 | **BeenKicked** | cell_id, perm_id |
| 105 | **RequestMOTD** | ticket_id |
| 106 | **MOTD** | txt(256), ticket_id |
| 107 | **RegObserverGlobalChat** | ticket_id — subscribe to global chat |
| 108 | **DeregObserverGlobalChat** | ticket_id |
| 165 | **Chat** | txt(256), from_id — simple broadcast chat |
| 259 | **RequestLeaveChannel** | cell_id, ticket_id, from_id |
| 262 | **GetChannelByName** | ticket_id, name(64) |

**UC (User Communication) subsystem** — real-time voice/text channels:

| Type | Name | Key Fields |
|------|------|-----------|
| 240 | **UCRoute** | from_id, cell_id, message_text(MEMBLOCK), status |
| 241 | **UCPrivate** | from_id, perm_id, message_text(MEMBLOCK), status |
| 242 | **UCCreateChannel** | from_id, name(128), password_required, password(32), status |
| 243 | **UCUpdateChannel** | from_id, id, name(128), password_required, password(32), status |
| 244 | **UCRemoveChannel** | from_id, id |
| 245 | **UCJoinChannel** | from_id, id, password(32) |
| 246 | **UCLeaveChannel** | from_id, id |
| 247 | **UCChannelJoined** | perm_id, id |
| 248 | **UCChannelLeft** | perm_id, id |
| 249 | **UCKickUser** | from_id, perm_id, id |
| 250 | **UCUserKicked** | perm_id, id |
| 251 | **UCUserInfo** | perm_id, nick(256), user_access |

---

#### User & Account Management

| Type | Name | Key Fields |
|------|------|-----------|
| 19 | **RequestUser** | perm_id |
| 21 | **FullUserData** | username(32), perm_id, userpwd(32), group_id, user_access, active, banned |
| 23 | **CreateUser** | username(32), userpwd(32), group_id, user_access, active, banned |
| 25 | **UpdateUser** | username(32), perm_id, userpwd(32), group_id, user_access, active, banned |
| 27 | **RequestRemoveUser** | perm_id |
| 29 | **UserMgrResult** | result_id, usr_grp_id |
| 53 | **RequestUsers** | user_id, cd_key(128), keypool, name(128), selection, ticket_id |
| 59 | **UserData** | user_id, name(128), password(32), mail(128), banned, active, status, data(MEMBLOCK), created(32), last_login(32), total_logins, ticket_id |
| 84 | **AddUser** | name(128), cipher(MEMBLOCK), mail(128), banned, active, data(MEMBLOCK) |
| 88 | **ChangeUser** | user_id, name(128), cipher(MEMBLOCK), mail(128), banned, active, data(MEMBLOCK), property_mask |
| 92 | **RemoveUser** | user_id |
| 96 | **AddUserKey** | user_id, cd_key(128), keypool |
| 97 | **RemoveUserKey** | user_id, cd_key(128), keypool |
| 98 | **AddUserBuddy** | user_id, buddy_id |
| 99 | **RemoveUserBuddy** | user_id, buddy_id |
| 109 | **UserLoggedIn** | user_id, name(128) |
| 110 | **UserLoggedOut** | user_id |
| 111 | **RegObserverUserList** | ticket_id |
| 112 | **DeregObserverUserList** | ticket_id |
| 115 | **RegObserverUserLogin** | send_all(LBOOL), ticket_id |
| 116 | **DeregObserverUserLogin** | ticket_id |
| 123 | **UserAdded** | user_id, ticket_id |
| 125 | **UserRemoved** | user_id, ticket_id |
| 135 | **RestoreUser** | user_id, restore_chars(LBOOL), filename(256) |
| 154 | **AddUserIgnore** | user_id, ignore_id |
| 155 | **RemoveUserIgnore** | user_id, ignore_id |
| 156 | **RequestUserBuddyRefs** | user_id |
| 157 | **RequestUserIgnoreList** | user_id |
| 158 | **RequestUserKeyList** | user_id |
| 159 | **UserKeyConn** | user_id, cd_key(128), keypool |
| 160 | **UserIgnoreConn** | user_id, ignore_id, name(128), perm_id_type, status, server_id, server_name(128) |
| 184 | **SetUserVisible** | visible(LBOOL) |
| 186 | **ChangeGroupUser** | old_group_id, new_group_id, user_id |
| 187 | **ChangeUserKey** | user_id, old_cd_key(128), old_keypool, new_cd_key(128), new_keypool |

---

#### CD Key Management

| Type | Name | Key Fields |
|------|------|-----------|
| 119 | **RequestSingleCdKey** | cd_key(128), keypool |
| 120 | **CdKeyData** | cd_key(128), keypool, banned(LBOOL), user_id |
| 140 | **AddKey** | cd_key(128), keypool |
| 141 | **RemoveKey** | cd_key(128), keypool |
| 142 | **BanKey** | cd_key(128), keypool |
| 143 | **UnbanKey** | cd_key(128), keypool |

---

#### Group / Permission System

| Type | Name | Key Fields |
|------|------|-----------|
| 20 | **RequestGroup** | group_id |
| 22 | **FullGroupData** | groupname(32), group_id, grouptype, group_access |
| 24 | **CreateGroup** | groupname(32), group_access |
| 26 | **UpdateGroup** | groupname(32), group_id, group_access |
| 28 | **RequestRemoveGroup** | group_id |
| 55 | **RequestUserCharList** | user_id |
| 56 | **RequestUserBuddyList** | user_id |
| 57 | **RequestUserGroupList** | user_id |
| 58 | **RequestPermIDAccess** | perm_id, access_index |
| 62 | **UserGroupConn** | user_id, group_id, name(128), level |
| 63 | **PermIDAccess** | perm_id, access_index, access |
| 64 | **RequestGroups** | group_id, name(128), selection |
| 66 | **RequestGroupUserList** | group_id |
| 67 | **RequestGroupAccess** | group_id, access_index |
| 68 | **GroupUserConn** | group_id, user_id, name(128), server_id, server_name(128) |
| 69 | **GroupData** | group_id, name(128), level |
| 70 | **GroupAccess** | group_id, access_index, access |
| 85 | **AddGroup** | name(128), level |
| 89 | **ChangeGroup** | group_id, property_mask, name(128), level |
| 93 | **RemoveGroup** | group_id |
| 100 | **AddGroupUser** | group_id, user_id |
| 101 | **RemoveGroupUser** | group_id, user_id |
| 104 | **SetGroupAccess** | group_id, access_index, access |
| 144 | **RequestPermID** | perm_id, name(128) |
| 145 | **PermIDData** | perm_id, name(128), perm_id_type |

---

#### Character System (Lobby Avatars)

| Type | Name | Key Fields |
|------|------|-----------|
| 60 | **UserCharConn** | char_id, name(128), owner_id, owner_name(128), guild_id, guild_name(128), guild_role, status, server_id, server_name(128), data(MEMBLOCK) |
| 72 | **RequestCharacters** | char_id, name(128), selection |
| 75 | **CharacterData** | char_id, name(128), owner_id, owner_name(128), guild_id, guild_name(128), guild_role, status, server_id, server_name(128), data(MEMBLOCK) |
| 77 | **CreateCharacterFromPreview** | name(128), owner_id, data(MEMBLOCK) |
| 79 | **AddCharacterFromPreview** | name(128), owner_id, data(MEMBLOCK) |
| 86 | **AddCharacter** | name(128), user_id, data(MEMBLOCK) |
| 90 | **ChangeCharacter** | char_id, name(128), data(MEMBLOCK), property_mask |
| 94 | **RemoveCharacter** | char_id |
| 113 | **RegObserverCharList** | ticket_id |
| 114 | **DeregObserverCharList** | ticket_id |
| 126 | **CharAdded** | char_id, ticket_id |
| 128 | **CharRemoved** | char_id, ticket_id |
| 137 | **RestoreChar** | char_id, filename(256) |

The `data(MEMBLOCK)` blob in character messages contains avatar customization data (body parts, colors, equipped items, pets) serialized in a game-specific format — content defined in the encrypted `avatar_items.xml`, `bodyparts.xml`, `color_slots.xml`.

---

#### Guild System

| Type | Name | Key Fields |
|------|------|-----------|
| 78 | **RequestGuilds** | owner_id, guild_id, name(128), selection |
| 80 | **RequestGuildCharList** | guild_id |
| 82 | **GuildData** | guild_id, name(128), owner_id, owner_name(128), data(MEMBLOCK) |
| 83 | **GuildCharConn** | guild_id, perm_id, name(128), perm_id_type, status, server_id, server_name(128), guild_role |
| 87 | **AddGuild** | name(128), owner_id, data(MEMBLOCK) |
| 91 | **ChangeGuild** | guild_id, name(128), owner_id, data(MEMBLOCK), property_mask |
| 95 | **RemoveGuild** | guild_id |
| 102 | **AddGuildChar** | perm_id, guild_id |
| 103 | **RemoveGuildChar** | perm_id, guild_id |
| 152 | **ChangeGuildChar** | perm_id, guild_id, guild_role |

---

#### Game Server Browser

| Type | Name | Key Fields |
|------|------|-----------|
| 146 | **EnterServer** | perm_id |
| 166 | **RequestServers** | server_id, room_id, server_type, server_subtype, selection |
| 167 | **RequestMachineGameServers** | machine_id, selection |
| 168 | **AddGameServer** | name(128), description(128), ip(128), port, server_type, server_subtype, cipher(MEMBLOCK), version(32), max_players, max_spectators, ai_players, room_id, level, game_mode, hardcore, map(128), running, locked_config, automatic_join, data(MEMBLOCK) |
| 169 | **RemoveServer** | server_id, running |
| 170 | **GameServerData** | server_id, name(128), owner_id, description(128), ip(128), port, password_required, server_type, server_subtype, version(32), max_players, cur_players, max_spectators, cur_spectators, ai_players, room_id, level, game_mode, hardcore, map(128), running, locked_config, data(MEMBLOCK) |
| 171 | **RegObserverServerList** | send_all, server_type, room_id, level, game_mode, hardcore, selection |
| 172 | **DeregObserverServerList** | |
| 177 | **ChangeGameServer** | name(128), description(128), cipher(MEMBLOCK), max_players, max_spectators, ai_players, room_id, level, game_mode, hardcore, map(128), running, locked_config, data(MEMBLOCK), property_mask |
| 189 | **AssignServer** | server_type, server_subtype |
| 190 | **LeaveServer** | perm_id |

**Host a game flow:**
```
Host → Lobby:   TYPE 168  AddGameServer   (name, ip, port 5479, map, player limits)
Lobby → Clients: TYPE 170 GameServerData  (broadcast to observers)
```

**Join a game flow:**
```
Client → Lobby:  TYPE 221  RequestConnectionData (perm_id, server_id)
Lobby → Client:  TYPE 222  ConnectionData        (ip, port, nonce, errorcode)
Client → Host:   Direct TCP to ip:5479
Host → Lobby:    TYPE 223  TANConnectionRequest  (ip, nonce, char info)
Client → Host:   TYPE 224  TANLogin              (perm_id, nonce) — nonce-verified handshake
```

---

#### Connection Data & NAT Traversal

| Type | Name | Key Fields |
|------|------|-----------|
| 221 | **RequestConnectionData** | perm_id, server_id |
| 222 | **ConnectionData** | perm_id, server_id, ip(128), port, nonce(MEMBLOCK), errorcode, errormsg(32) |
| 223 | **TANConnectionRequest** | ip(128), nonce(MEMBLOCK), char_id, name(128), owner_id, owner_name(128), guild_id, guild_name(128), guild_role, data(MEMBLOCK) |
| 224 | **TANLogin** | perm_id, nonce(MEMBLOCK) |

---

#### Machine Management (Dedicated Server Admin)

| Type | Name | Key Fields |
|------|------|-----------|
| 121 | **RequestMachines** | machine_id, ip(128), selection |
| 122 | **MachineData** | machine_id, description(128), ip(128), active |
| 124 | **KickPermIDMachine** | perm_id, machine_id |
| 138 | **KickPermIDServer** | perm_id, ip(128), port |
| 139 | **KickPermID** | perm_id |
| 191 | **AddUsercomm** | ip(128), port, max_players |
| 192 | **UsercommServerData** | server_id, ip(128), port, server_type, version(32), data(MEMBLOCK) |
| 193 | **UsercommRequestUserdata** | perm_id |
| 194 | **UsercommUserData** | perm_id, username(32), user_access |

---

#### Mailbox / Private Messages

| Type | Name | Key Fields |
|------|------|-----------|
| 31 | **EmailMessage** | delivery_target_name(32), body(1024) |
| 43 | **EmailNotification** | cell_id, notification_type, target_msg_id |
| 147 | **RequestPrivateMessageList** | delivery_target, selection |
| 148 | **ChangePrivateMessage** | message_id, status |
| 149 | **PrivateMessage** | delivery_target, message_id, creator, creation_time, title(128), status, message_text(MEMBLOCK), data(MEMBLOCK) |
| 150 | **AddPrivateMessage** | delivery_target, creator, creation_time, title(128), message_text(MEMBLOCK), data(MEMBLOCK) |
| 151 | **RemovePrivateMessage** | message_id |

---

#### Admin Broadcast Messages (MOTD, Announcements)

| Type | Name | Key Fields |
|------|------|-----------|
| 8 | **AdminRequestMsgList** | cell_id |
| 9 | **AdminRequestMessage** | cell_id, msg_id, ticket_id |
| 10 | **AdminRequestAllMessages** | cell_id, ticket_id |
| 11 | **AdminUpdateMessage** | cell_id, msg_id, msg_type, msg_data(MEMBLOCK), title(128), usrcom_mode, creation_time, creator, expiration_mode, expiration_date, delivery_mode, delivery_target, delivery_interval, delivery_date |
| 12 | **AdminMessageList** | cell_id, idlist(MEMBLOCK) |
| 13 | **AdminMessageEntry** | full message record |
| 14 | **AdminAddMessageEntry** | full message record with ticket_id |
| 15 | **AdminRemoveMessageEntry** | cell_id, msg_id, ticket_id |
| 32 | **AdminAddEmailMessageEntry** | full email record |
| 33 | **AdminRequestEmailList** | cell_id |
| 179 | **ChangeMOTD** | txt(256) |
| 185 | **DownloadLogs** | ticket_id |

---

#### Server Statistics / Uptime

| Type | Name | Key Fields |
|------|------|-----------|
| 48 | **StatisticsRequestItemList** | ticket_id |
| 49 | **StatisticsGetLiveValue** | value_name(64), ticket_id |
| 50 | **StatisticsItemInfo** | value_name(64), ticket_id |
| 51 | **StatisticsLiveValueData** | value(32), ticket_id |
| 52 | **StatisticsResultCode** | resultcode, ticket_id |
| 117 | **RegObserverUptime** | ticket_id |
| 118 | **DeregObserverUptime** | ticket_id |
| 173 | **GetStatisticsConnection** | ticket_id |
| 174 | **StatisticsConnection** | ip(MEMBLOCK), port, name(MEMBLOCK), username(MEMBLOCK), password(MEMBLOCK) |
| 180 | **RequestServerInfo** | ticket_id |
| 181 | **ServerInfoData** | starttime(32), starttimestamp, time, patchlevel, txt(256) |
| 182 | **UptimeData** | uptime, registered_users, logins, registered_gameservers, started_gameservers |

---

#### Player Properties (Stats/Inventory Stored Server-Side)

| Type | Name | Key Fields |
|------|------|-----------|
| 161 | **PropertyGet** | kategory(SILONG), index(SILONG) |
| 162 | **PropertyData** | kategory(SILONG), index(SILONG), value(SILONG) |
| 163 | **PropertySetAbsolute** | kategory(SILONG), index(SILONG), value(SILONG) |
| 164 | **PropertySetRelative** | kategory(SILONG), index(SILONG), value(SILONG) — delta |

Properties are keyed by (category, index) → signed integer value. Used for game-specific persistent data (resources, XP, unlock flags, etc.).

---

#### Item Broker (In-Lobby Marketplace)

| Type | Name | Key Fields |
|------|------|-----------|
| 34 | **BrokerAddItem** | owner, item_type, item_name(128), item_prize, item_values(1024), item_data(MEMBLOCK) |
| 35 | **BrokerChangePrize** | item_id, item_prize |
| 36 | **BrokerRemoveItem** | item_id |
| 37 | **BrokerGetItem** | netzone, item_id |
| 38 | **BrokerItem** | item_id, owner, owner_name(32), item_type, item_name(128), item_prize, item_values(1024), item_data(MEMBLOCK) |
| 39 | **BrokerGetItemList** | netzone, item_type, owner_name(32), name_pattern(128), min_prize, max_prize, offset, limit, sort_field(SIBYTE), sort_order(LBOOL), criterias(1024) |
| 40 | **BrokerGetLimit** | ticket_id |
| 41 | **BrokerLimit** | limit |
| 44 | **BrokerBuyRequest** | item_id, buyer |
| 45 | **BrokerNotification** | item_id, buyer |
| 46 | **BrokerSoldNotification** | item_id, buyer, item_type, item_name(128), item_prize, item_values(1024), item_data(MEMBLOCK) |
| 47 | **BrokerItemListFinished** | items_found |

---

#### Ranking System

| Type | Name | Key Fields |
|------|------|-----------|
| 252 | **GameResultSubmit** | perm_id_a, perm_id_b, result(UNSHORT), map_id, custom_1, custom_2 |
| 253 | **GameResultSubmitResult** | perm_id_a, perm_id_b, result_id |
| 254 | **RequestSingleUserRank** | ranktable(UNSHORT), perm_id |
| 255 | **ReceiveSingleUserRank** | ranktable, perm_id, nick(256), rank, points, played, won, lost, tie, disconnected |
| 256 | **RequestRankRange** | ranktable, rangestart, rangeend |
| 257 | **ReceiveRankRange** | ranktable, rangestart, rangeend, count, rankdata(MEMBLOCK) |
| 258 | **AddRankingServer** | ip(128), port |

**Match result submission:**
```
Game ends → TYPE 252: GameResultSubmit (perm_id_a, perm_id_b, result: 0=tie/1=A wins/2=B wins, map_id)
Lobby    → TYPE 253: GameResultSubmitResult (echoes ids + result_id for confirmation)
```

`ranktable` distinguishes weekly/monthly/yearly leaderboards.  
`rankdata` in TYPE 257 contains packed array of rank entries (format TBD from binary analysis).

---

#### Player Status Monitoring

| Type | Name | Key Fields |
|------|------|-----------|
| 61 | **UserBuddyConn** | user_id, buddy_id, name(128), perm_id_type, status, server_id, server_name(128) |
| 175 | **RegObserverBuddylist** | user_id, send_all |
| 176 | **DeregObserverBuddylist** | user_id |
| 260 | **CheckPlayerOnServerAndGetInfos** | connection_pid, user_pid |
| 261 | **CheckPlayerOnServerAndGetInfosReply** | perm_id, username(32), user_access, result_id |

---

## 4. Lobby Structure & Content

Discovered from the file listing under `data/lobby/` (all content files are KEX-encrypted but the file names reveal the full feature set).

### 4.1 Lobby Scenes / Areas
- `scene1.xml` / `scene2.xml` — main lobby rooms
- `scene_taverne02.xml`, `scene_taverne03.xml` — tavern areas
- `scene_townhall.xml` — town hall area  
- `scene_gasthaus2.xml` — inn/guesthouse
- `lobby_castle01.xml`, `lobby_castle02.xml` — castle areas
- `scene_customizeavatar.xml` — avatar customization screen
- `scene_ad.xml` — advertisement/announcement area
- `scene_ambient_sounds.xml` — ambient audio config
- `world1.xml`, `world2.xml` — world map views

### 4.2 Avatar System
Files: `bodyparts.xml`, `color_slots.xml`, `avatar_items.xml`, `npc_bodyparts.xml`, `materials.xml`  
Animations per gender: `male_animation_graph.xml`, `female_animation_graph.xml`  
NPC characters: `MacDoyleJr_animation_graph.xml`, `MacGabhan_animation_graph.xml`  
Animation selector: `anim_selector.xml`

### 4.3 Pet System
Available pets (each with own animation graph):
- Bear, Cat, Dog, Falcon, Goat, Goop (fantasy creature), Marmot, Rabbit, Sheep

File: `pets.xml` + `pet_<animal>_animation_graph.xml` for each

### 4.4 Lobby UI Dialogs
All XML-defined, encrypted, under `data/lobby/ui/layout/`:
- `lobbyLoginDialog.xml` — username/password
- `lobbyCreateAccountDialog.xml` — registration
- `lobbyAvatarScreen.xml`, `lobbyCustomizeAvatarDialog.xml` — avatar editor
- `lobbyBrowseGameDialog.xml` — game server browser
- `lobbyHallOfFameDialog.xml` — rankings
- `lobbyMailboxDialog.xml`, `lobbyMailDialog.xml` — in-lobby mail
- `lobbyMotDDialog.xml` — Message of the Day
- `lobbyFriendIgnoreListDialog.xml` — social lists
- `lobbyAccountScreen.xml` — account management
- `lobbyEnterPasswordDialog.xml`, `lobbyGetPasswordDialog.xml`
- `lobbyConfirmTaylorDialog.xml` — tailor/customization confirmation
- `lobbyMessageBoxDialog.xml` — generic alerts
- `lobbyMiniGameManualDialog.xml`, `lobbyMiniGameMatchMakingDialog.xml`

### 4.5 Mini-Games (in lobby)
- `lobbyMinigameDialog_Dice.xml`
- `lobbyMinigameDialog_Poker.xml`
- `lobbyMinigameDialog_PawnChess.xml`
- `lobbyMinigameDialog_Observer.xml`

---

## 5. Patchlevel / Version Validation

`network.ini`: `patchlevel = 9212`

The server enforces this via TYPE 183 (CheckLevel) and TYPE 188 (CheckVersion).  
A reimplemented server should either accept any patchlevel, or patch the binary to skip validation.

---

## 6. Reconnection Logic (`network.ini`)
```
timeHostWaitForClients  = 30.0 s   (host waits this long for players to reconnect)
timeClientWaits         = 3.0 s    (client retry interval)
timesClientRetries      = 5        (max reconnect attempts)
timeClientWaitsFailed   = 4.0 s    (wait after failed attempt)
```

LAN ping rates:
- In menu: every 10.0 s
- In game:  every 2.5 s

---

## 7. Reimplementation Roadmap

To bring the lobby back online, a server must be implemented that:

1. **Listens TCP on any port** (originally 7070). Clients need `LobbySettings.ini` patched to point at the new server.

2. **Implements the binary protocol** from Section 3. All messages are little-endian with UNSHORT type prefix.

3. **Authentication**: The real flow (TYPEs 201–207) is **ECDH (secp521r1) + SHA-512/XOR session key + Twofish-CTR credentials**, completing on a TYPE 153 AddResult ACK — fully reversed and implemented in `sadk_lobby/crypto.py` (it is NOT RSA). A server may instead downgrade to plaintext login (TYPE 4) if it sends back TYPE 42 (Result OK) + TYPE 207 (SessionKey with perm_id).

4. **Minimum viable feature set for multiplayer:**
   - Login / account creation (TYPE 4 or 201–207)
   - Game server browser (TYPEs 168, 170, 171)
   - ConnectionData relay (TYPEs 221–222)
   - TAN handshake (TYPEs 223–224)
   - MOTD + basic chat (TYPEs 105, 106, 165)
   - Result response (TYPE 42)

5. **Patchlevel check**: Either serve patchlevel 9212, or patch `SADK.exe` / `tincat3.dll` to skip the check.

6. **CD key check**: Original server validated CD keys. A reimplemented server should accept any key (or no key), requiring either a binary patch or a permissive server-side check.

7. **`LobbySettings.ini` patching**: Change `Host` from the dead `84.17.180.120` (see §1) to the new server IP.

> **Scope note:** items 1–7 above bring the **lobby** back online (login, browser, chat, server list).
> Full in-world play additionally requires the village/world `:5479` sub-protocol, which is only
> **partially** reversed (§3.2) — the EnterWorld handshake works, but the complete in-world spec does not
> yet exist. This document is therefore *not* a finished "drop-in" reimplementation guide for the whole game.

---

## 8. Outstanding Unknowns

- **Exact TCP framing**: Is each message length-prefixed, or does the protocol use fixed packet boundaries? The `MEMBLOCK 0` type implies length prefixing exists, but overall message framing needs `tincat3.dll` disassembly to confirm.
- **Authentication cipher**: RESOLVED — ECDH (secp521r1) key exchange + SHA-512/XOR session key + Twofish-CTR credentials (reversed and implemented in `sadk_lobby/crypto.py`). Not RSA.
- **CD key format**: The `keypool` field suggests multiple key pools (different regions/editions). Format unknown.
- **`rankdata` MEMBLOCK format**: The packed rank array structure in TYPE 257.
- **Character `data` MEMBLOCK**: The avatar blob structure (requires decrypting `avatar_items.xml`).
- **`lobbyobj.xml` content**: Encrypted, defines lobby objects/entities — needed for full scene reconstruction.

---

## 9. File Inventory Summary

| File | Type | Content |
|------|------|---------|
| `data/lobby/config/LobbySettings.ini` | plaintext | Server IP, port, ranking URLs |
| `data/game/settings/network.ini` | plaintext | Game port, broadcast, reconnect timing |
| `bin/msgdefs.ini` = `msgdefs.ini` | plaintext | **Complete binary protocol definition** |
| `bin/tincat3.dll` | PE DLL | Networking middleware — needs disassembly |
| `bin/SADK.exe` | PE EXE | Game binary |
| `data/lobby/config/*.xml` | KEX-encrypted | Avatar, pet, object definitions |
| `data/lobby/ui/layout/*.xml` | KEX-encrypted | UI dialog layouts |
| `data/lobby/scene/*.xml` | KEX-encrypted | 3D scene definitions |
| `data/lobby/physic/*.xml` | KEX-encrypted | Physics collision for lobby |

---

*Generated by reverse engineering. All information extracted from the game's own plaintext config files and file structure.*
