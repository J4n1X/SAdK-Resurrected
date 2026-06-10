# SaDK Lobby Protocol Reference

**Game**: Die Siedler: Aufbruch der Kulturen (2008, Funatics / Blue Byte / Ubisoft).

Source of truth for all message types/field layouts: `bin/msgdefs.ini` (= `msgdefs.ini`). [PROVEN]
Lobby catalogue is complete. The in-world `:5479` sub-protocol (types 1000+) is only **partially**
reversed — see §3.2.

---

## 1. Endpoints

> Official Funatics endpoints are dead (infra shut down ~2014); recorded for reference only.

| Source file | Key | Value | Note |
|---|---|---|---|
| `LobbySettings.ini` | Host / Port | `84.17.180.120` / `7070` | [PROVEN] TCP main lobby |
| `network.ini` | url | `www.diesiedler2lobby.de:8777` | secondary lobby URL |
| `network.ini` | patchlevel | `9212` | [PROVEN] required client version |
| `LobbySettings.ini` | ranking | `http://sadk.funatics.de:7012/rankingMaster/ranking.php` | HTTP, `?ranking=weekly\|monthly\|yearly&limit&offset&permID` |
| `network.ini` | gamePort | `5479` | [PROVEN] world / direct game connection (TCP/UDP) |
| `network.ini` | broadcastPort | `6582` | LAN discovery, broadcastTimeout 10000 ms |

---

## 2. Networking Middleware

`bin/tincat3.dll` is the proprietary Funatics networking layer ("TinCat 3"). Reimplementing the
server means matching this binary protocol.

---

## 3. Binary Protocol

### 3.1 Wire Format [PROVEN]

- TCP, binary, **little-endian**.
- TinCat frame header is **28 bytes**.
- Lobby payload prefix magic **0x26B6**; chat payload prefix magic **0x0062**.
- Every message begins with a `type` field — **UNSHORT** (uint16).

| Token | C type | Size | Notes |
|-------|--------|------|-------|
| `UNBYTE` / `SIBYTE` | uint8 / int8 | 1 B | |
| `UNSHORT` / `SISHORT` | uint16 / int16 | 2 B | |
| `UNLONG` / `SILONG` | uint32 / int32 | 4 B | |
| `LBOOL` | uint32 | 4 B | 0 = false |
| `STRING N` | char[N] | N B | null-terminated fixed buffer |
| `MEMBLOCK 0` | blob | variable | u32 length-prefix + bytes |

- `ticket_id` (UNLONG): client-generated nonce matching async responses to requests.
- `perm_id` (UNLONG): server-assigned persistent player identity (survives re-logins).

### 3.2 Village / world sub-protocol caveat

EnterWorld(1000) is understood and drives the client into the rendered world. [PROVEN]
**[TODO]** full in-world set (1001–1006, ticks, observer fan-out, entity overlays) — not yet a
reimplementable spec. See `sadk_lobby/village.py` and the in-world TODO in `MEMORY.md`.

### 3.3 Authentication & Session [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 4 | **RequestLogin** | nick(256), password(32), cd_key(128), keypool(UNSHORT), patchlevel, ticket_id |
| 71 | **RequestCreateAccount** | nick(256), password(32), cd_key(128), keypool, patchlevel, ticket_id |
| 201 | **StartAuthenticateSession** | key(MEMBLOCK) — client ECDH (secp521r1) public key |
| 202 | **AckAuthenticateSession** | cipher(MEMBLOCK) — server ECDH public key → shared secret |
| 203 | **SelfRegistration** | cipher(MEMBLOCK) |
| 204 | **AuthenticateUser** | cipher(MEMBLOCK) — client proves identity (Twofish-CTR credential blob) |
| 205 | **AuthenticateSupport** | cipher(MEMBLOCK) |
| 206 | **AuthenticateServer** | cipher(MEMBLOCK) — game server authenticates |
| 207 | **SessionKey** | perm_id, cipher(MEMBLOCK) — assigns permanent ID + session key |
| 211 | **StartValidateTokenSession** | ticket_id |
| 212 | **AckValidateTokenSession** | nonce(MEMBLOCK) |
| 213 | **SendToken** | perm_id, cipher(MEMBLOCK) |
| 214 | **ValidateToken** | perm_id, cipher(MEMBLOCK), nonce(MEMBLOCK) |
| 183 | **CheckLevel** | level(UNBYTE) |
| 188 | **CheckVersion** | version(SISHORT), subversion(SISHORT) |
| 178 | **ChangePatchlevel** | patchlevel |

**Login flow** [PROVEN] (implemented in `sadk_lobby/crypto.py`; **ECDH, not RSA**):
```
C→S  201 StartAuthenticateSession  (client ECDH secp521r1 public key)
S→C  202 AckAuthenticateSession    (server ECDH public key)
     → both derive shared secret; session key = SHA-512(shared), XOR-folded
C→S  204 AuthenticateUser          (credentials in Twofish-CTR blob, IV-prefixed, no MAC)
S→C  207 SessionKey                (perm_id + session token)
     → login COMPLETES on a 153 AddResult ACK (errorcode=0), NOT on 207, and NOT on 214.
```

Plaintext fallback: `4 RequestLogin` → `42 Result` (OK) → `207 SessionKey`. [PROVEN]

### 3.4 Generic Responses [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 1 | **Simple** | data(UNLONG) |
| 42 | **Result** | errorcode(UNBYTE), errormsg(32), ticket_id |
| 153 | **AddResult** | errorcode(UNBYTE), errormsg(32), id(UNLONG), ticket_id |

### 3.5 Channel / Chat [PROVEN]

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
| 107 | **RegObserverGlobalChat** | ticket_id |
| 108 | **DeregObserverGlobalChat** | ticket_id |
| 165 | **Chat** | txt(256), from_id |
| 259 | **RequestLeaveChannel** | cell_id, ticket_id, from_id |
| 262 | **GetChannelByName** | ticket_id, name(64) |

**UC (User Communication) subsystem** [PROVEN]:

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

### 3.6 User & Account Management [PROVEN]

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

### 3.7 CD Key Management [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 119 | **RequestSingleCdKey** | cd_key(128), keypool |
| 120 | **CdKeyData** | cd_key(128), keypool, banned(LBOOL), user_id |
| 140 | **AddKey** | cd_key(128), keypool |
| 141 | **RemoveKey** | cd_key(128), keypool |
| 142 | **BanKey** | cd_key(128), keypool |
| 143 | **UnbanKey** | cd_key(128), keypool |

### 3.8 Group / Permission System [PROVEN]

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

### 3.9 Character System (Lobby Avatars) [PROVEN]

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

`data(MEMBLOCK)` = avatar customization (body parts, colors, items, pets), game-specific format
defined in encrypted `avatar_items.xml`, `bodyparts.xml`, `color_slots.xml`. **[TODO]** blob layout.

### 3.10 Guild System [PROVEN]

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

### 3.11 Game Server Browser [PROVEN]

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
| 192 | **UsercommServerData** | server_id, ip(128), port, server_type, version(32), data(MEMBLOCK) |

Notes:
- `GameServerData(170)` must use the real-client-compatible format (per `msgdefs.ini`), **not**
  emulator assumptions. The decoder uses `CreatePropertySet(0xAA)` (see SOURCEMAP §3b). [PROVEN]
- **ServerDataBlock match-key**: a `170` descriptor is JOINABLE when its `room_id` equals the selected
  village `room_id` (`g_dwSelectedVillageRoomId`, live = 1000), plus the `running`/`locked` flag pair.
  The room/validity values come from the `data` blob path, **not** from the `170` scalar wire fields. [PROVEN]
- `189 AssignServer` → server replies `192 UsercommServerData`. [PROVEN]

**Host-a-game flow** [PROVEN]:
```
Host → Lobby:    168 AddGameServer   (name, ip, port 5479, map, player limits)
Lobby → Clients: 170 GameServerData  (broadcast to observers)
```

**Join-a-game flow** [PROVEN]:
```
Client → Lobby:  221 RequestConnectionData (perm_id, server_id)
Lobby → Client:  222 ConnectionData        (ip, port, nonce, errorcode)
Client → Host:   direct TCP to ip:5479
Host → Lobby:    223 TANConnectionRequest  (ip, nonce, char info)
Client → Host:   224 TANLogin              (perm_id, nonce) — nonce-verified handshake
```

### 3.12 Connection Data & NAT Traversal [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 221 | **RequestConnectionData** | perm_id, server_id |
| 222 | **ConnectionData** | perm_id, server_id, ip(128), port, nonce(MEMBLOCK), errorcode, errormsg(32) |
| 223 | **TANConnectionRequest** | ip(128), nonce(MEMBLOCK), char_id, name(128), owner_id, owner_name(128), guild_id, guild_name(128), guild_role, data(MEMBLOCK) |
| 224 | **TANLogin** | perm_id, nonce(MEMBLOCK) |

### 3.13 Machine Management [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 121 | **RequestMachines** | machine_id, ip(128), selection |
| 122 | **MachineData** | machine_id, description(128), ip(128), active |
| 124 | **KickPermIDMachine** | perm_id, machine_id |
| 138 | **KickPermIDServer** | perm_id, ip(128), port |
| 139 | **KickPermID** | perm_id |
| 191 | **AddUsercomm** | ip(128), port, max_players |
| 193 | **UsercommRequestUserdata** | perm_id |
| 194 | **UsercommUserData** | perm_id, username(32), user_access |

### 3.14 Mailbox / Private Messages [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 31 | **EmailMessage** | delivery_target_name(32), body(1024) |
| 43 | **EmailNotification** | cell_id, notification_type, target_msg_id |
| 147 | **RequestPrivateMessageList** | delivery_target, selection |
| 148 | **ChangePrivateMessage** | message_id, status |
| 149 | **PrivateMessage** | delivery_target, message_id, creator, creation_time, title(128), status, message_text(MEMBLOCK), data(MEMBLOCK) |
| 150 | **AddPrivateMessage** | delivery_target, creator, creation_time, title(128), message_text(MEMBLOCK), data(MEMBLOCK) |
| 151 | **RemovePrivateMessage** | message_id |

### 3.15 Admin Broadcast / MOTD [PROVEN]

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

### 3.16 Server Statistics / Uptime [PROVEN]

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

### 3.17 Player Properties [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 161 | **PropertyGet** | kategory(SILONG), index(SILONG) |
| 162 | **PropertyData** | kategory(SILONG), index(SILONG), value(SILONG) |
| 163 | **PropertySetAbsolute** | kategory(SILONG), index(SILONG), value(SILONG) |
| 164 | **PropertySetRelative** | kategory(SILONG), index(SILONG), value(SILONG) — delta |

Keyed by (category, index) → signed int. Used for persistent game data (resources, XP, unlock flags).

### 3.18 Item Broker [PROVEN]

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

### 3.19 Ranking System [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 252 | **GameResultSubmit** | perm_id_a, perm_id_b, result(UNSHORT), map_id, custom_1, custom_2 |
| 253 | **GameResultSubmitResult** | perm_id_a, perm_id_b, result_id |
| 254 | **RequestSingleUserRank** | ranktable(UNSHORT), perm_id |
| 255 | **ReceiveSingleUserRank** | ranktable, perm_id, nick(256), rank, points, played, won, lost, tie, disconnected |
| 256 | **RequestRankRange** | ranktable, rangestart, rangeend |
| 257 | **ReceiveRankRange** | ranktable, rangestart, rangeend, count, rankdata(MEMBLOCK) |
| 258 | **AddRankingServer** | ip(128), port |

- `252 GameResultSubmit` result field: 0=tie / 1=A wins / 2=B wins. Server echoes `253` with result_id.
- `ranktable` distinguishes weekly/monthly/yearly leaderboards.
- **[TODO]** `rankdata` (257) packed rank-entry array layout.

### 3.20 Player Status Monitoring [PROVEN]

| Type | Name | Key Fields |
|------|------|-----------|
| 61 | **UserBuddyConn** | user_id, buddy_id, name(128), perm_id_type, status, server_id, server_name(128) |
| 175 | **RegObserverBuddylist** | user_id, send_all |
| 176 | **DeregObserverBuddylist** | user_id |
| 260 | **CheckPlayerOnServerAndGetInfos** | connection_pid, user_pid |
| 261 | **CheckPlayerOnServerAndGetInfosReply** | perm_id, username(32), user_access, result_id |

### 3.21 World entry (`:5479`) — partial

- `1000 EnterWorld` is the world-entry handshake that drives the client into the rendered world. [PROVEN]
  Receiver and field reads: see SOURCEMAP §2b (`HandleEnterWorld`).
- **[TODO]** full in-world message set (1001–1006, ticks, observer fan-out). Tracked in
  `sadk_lobby/village.py` and the in-world TODO in `MEMORY.md`.

---

## 4. Lobby Content (from `data/lobby/` file listing; files KEX-encrypted)

- **Scenes**: `scene1/2.xml`, `scene_taverne02/03.xml`, `scene_townhall.xml`, `scene_gasthaus2.xml`,
  `lobby_castle01/02.xml`, `scene_customizeavatar.xml`, `scene_ad.xml`, `world1/2.xml`.
- **Avatar**: `bodyparts.xml`, `color_slots.xml`, `avatar_items.xml`, `npc_bodyparts.xml`,
  `materials.xml`, `*_animation_graph.xml`, `anim_selector.xml`.
- **Pets** (`pets.xml` + per-animal graph): Bear, Cat, Dog, Falcon, Goat, Goop, Marmot, Rabbit, Sheep.
- **UI dialogs** (`data/lobby/ui/layout/`): login, create-account, avatar/customize, browse-game,
  hall-of-fame, mailbox/mail, MOTD, friend/ignore, account, password dialogs, message box,
  mini-game manual/matchmaking.
- **Mini-games**: Dice, Poker, PawnChess, Observer.

---

## 5. Config / Version

- `network.ini`: `patchlevel = 9212`, enforced via `183 CheckLevel` / `188 CheckVersion`. Serve 9212. [PROVEN]
- Reconnection (`network.ini`): `timeHostWaitForClients=30s`, `timeClientWaits=3s`,
  `timesClientRetries=5`, `timeClientWaitsFailed=4s`. LAN ping: 10s menu, 2.5s in game.

---

## 6. Reimplementation Notes

Minimum viable lobby (login → browser → chat → server list):
1. TCP listener (orig 7070); point `LobbySettings.ini` Host at the stub.
2. Auth: real flow (201–207, ECDH + SHA-512/XOR + Twofish-CTR, completes on `153`), implemented in
   `sadk_lobby/crypto.py`. Plaintext fallback: `4` → `42` OK → `207`.
3. Server browser (168, 170, 171); ConnectionData relay (221–222); TAN handshake (223–224).
4. MOTD + chat (105, 106, 165); Result (42).
5. Serve patchlevel 9212; accept any CD key.

> **Scope**: the above restores the **lobby** only. Full in-world play needs the `:5479` sub-protocol,
> which is only partially reversed (§3.2, §3.21). This is **not** a drop-in full-game guide.

---

## 7. Outstanding [TODO]

- `rankdata` MEMBLOCK (257) packed-array layout.
- Character `data` MEMBLOCK (avatar blob) layout — needs `avatar_items.xml` decrypt.
- CD key / `keypool` format (multiple key pools, unknown structure).
- Full in-world `:5479` sub-protocol spec.

---

## 8. File Inventory

| File | Type | Content |
|------|------|---------|
| `LobbySettings.ini` | plaintext | server IP, port, ranking URLs |
| `network.ini` | plaintext | game port, broadcast, reconnect timing |
| `bin/msgdefs.ini` = `msgdefs.ini` | plaintext | **complete binary protocol definition** |
| `bin/tincat3.dll` | PE DLL | networking middleware |
| `bin/SADK.exe` | PE EXE | game binary |
| `data/lobby/**/*.xml` | KEX-encrypted | avatar/pet/object/UI/scene/physics definitions |
