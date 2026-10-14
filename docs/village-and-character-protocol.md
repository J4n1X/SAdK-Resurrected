# Village and character protocol (server-side flows)

This document covers the 3D lobby world ("village") and the account's characters (avatars). Each
flow is written for someone implementing the server: who sends what, what the client holds while
it waits, what happens on errors, and which values the server may use.

- Wire layouts (bit widths, field order, envelopes) are in [message-catalog.md](message-catalog.md).
  This document only repeats a field when a flow decision depends on it.
- Related: [LOBBY_PROTOCOL.md](LOBBY_PROTOCOL.md) (login, NETMSG basics),
  [LIVE_DEBUG_RUNBOOK.md](LIVE_DEBUG_RUNBOOK.md) (state values, transport states),
  [MATCH_WORLD_LOGIN.md](MATCH_WORLD_LOGIN.md) (leaving the village at match start),
  [SOURCEMAP.md](SOURCEMAP.md) (symbol map). [IN_WORLD_PRESENCE.md](IN_WORLD_PRESENCE.md) is an
  older draft. Where it disagrees with this document (the `names=1` claim, the meaning of 1002),
  this document is current.

**Confidence tags.** [known] means read directly from code or disassembly. [inferred] means
derived from code but not observed end to end. [guess] means plausible, with no direct evidence.
[PROVEN] means the working stub (`lobby/sadk_lobby/`) shows it live against the real client. A
[PROVEN] claim carries a binary address and the date of the live evidence. [TODO] marks an open
question.

**Addresses.** `S 00xxxxxx` is in `sadk_noav.exe`; `T 10xxxxxx` is in `tincat3.dll`. Struct
offsets such as `LM+0x57c` are relative to the named object.

---

## 1. Objects and state the flows depend on

### 1.1 Who holds what

| Object | Where | Holds | Tag |
|---|---|---|---|
| `LobbyComm::System` (LM; the singleton `g_pLobbyManager`, called LobbyManager in older notes) | singleton, 0x5a8 bytes | state `+0x57c` (enum `LobbyManagerState`); local avatar id `+0x54c`; local `AvatarProxy*` `+0x554`; village conn `+0x540`; UC conn `+0x3d8`; `characterManager` `+0x140`; `postOffice` `+0x2f8`; `properties` `+0x3bc` | [known] |
| `LobbyComm::CharacterManager` | embedded at `LM+0x140` (ctor S 00478f80) | character map `+0x8c` (id → AvatarProxy, 0xE0 each); list-valid flag `+0x88`; selected id `+0x98`; working/preview avatar `+0xa0`; action queue `+0x74`; buddy/ignore maps `+0x184`/`+0x194`; name↔id caches `+0x1a0`/`+0x1ac` | [known] |
| tincat3 `CommLayer::CharacterManager` | `CharacterManager+0x5c` | sends 72/86/77/90/94; per-request busy flags `+0xc/+0x10/+0x14/+0x18` | [known] |
| tincat3 `CommLayer::UserManager` | `CharacterManager+0x60` | sends 55/88/56/157/…; collects 60 rows at `+0xd0` | [known] |
| `LobbyComm::VillageServerConnection` | `LM+0x540` | transport `+0x34`; owner `pSystem` `+0x158`; `serverPermId` `+0x160`; `zoneChatChannels` `+0x164` (zone byte → cell id); avatar map `+0x170`; NPC map `+0x174`; `miniGameTables` `+0x178`; event queues `+0x184/+0x198/+0x1ac`; `worldLoginAckReceived` `+0x224`; `currentZone` `+0x225`; `zoneJoinPending` `+0x226`; `worldName` `+0x228`; `connectionQuality` `+0x244`; pending ping `+0x248`; trade latch `+0x274` | [known] |
| `LobbyMenu::AvatarScreen` | screen | view mode `+0x1e8` (0 create, 1 select, 2 entering); wait dialog `+0x200` | [inferred] |

### 1.2 `LobbyComm::System` states (`LM+0x57c`, enum `LobbyManagerState`)

| Value | Name | Entered by | Left by |
|---|---|---|---|
| 1 | Disconnected | init, login failed, logged out | lobby login |
| 2 | Authorizing | lobby login | 207 SessionKey |
| 3 | Authorized | OnLoggedIn | state pump |
| 4–5 | version check | state pump | 42 for 188 |
| 6 | LoadingGlobalData | state pump | all four global lists valid (§2.1) |
| 7 | GlobalDataLoaded | state pump | character selected, Enter clicked |
| 8 | EnteringVillage | `OnUserCommLoggedIn` S 004704e0 | **server-pushed** EnterWorld 1000 |
| 9 | VillageEntered | `HandleEnterWorld` S 0046f670 | msg 2002 sent |
| 10 | LeavingVillage | `SendLeaveVillageRequest` S 0046bde0 | only LoggedOut (→11) or Disconnected (→11) |
| 11 | VillageLeft | `HandleLoggedOut` / `HandleDisconnected` | — |
| 12 | ConnectionLost | main connection lost | — |

[known] for the values and setters; LIVE_DEBUG_RUNBOOK.md has the trace evidence.

### 1.3 Two encodings

- **Character messages** (55/60/72/75/77/79/86/90/94 and their 42/153 results) travel on the
  **lobby** connection as TinCat PropertySets. Their scalars are little-endian. Each STRING or
  MEMBLOCK has a u32 length prefix. [known]
- **Village messages** travel on the **village** connection. Each one is wrapped in NETMSG 74
  `SendGameData {type, msg_type u32, data MEMBLOCK}`; NETMSG 73 also exists, for bundles.
  `msg_type` is a LobbyMessage type word: bit 15 = names flag, bits 12–14 = category, bits 0–11 =
  id. The body is an MSB-first bit stream: scalars are big-endian at their stated bit width, and
  strings are an 8-bit length followed by UTF-8 bytes. The client sends category 2 (category 5
  for minigame actions). The client dispatches on the 12-bit id only. The server sends category 0
  with **names = 0**; with names = 1 the reader would also consume a trailing 32-bit word.
  Unknown ids are dropped silently by `HandleMessage` S 00470a90. [known; envelope PROVEN since
  s39, S 00470a90]

### 1.4 Character data blob (shared by 60, 75, 86, 77, 79)

`data` MEMBLOCK = `u32 LE size[6]` (0x18-byte header) followed by six parts, concatenated. All
values inside the parts are u32 LE. [known, T 100163c0, T 1002eac0]

| Part | Content | Tag |
|---|---|---|
| 0 | **Creation** block: `variant, tribe, gender, hair, skin, shirt, trouser` + (`variant != 0`) `addColor1..4`, size 0x2C (0x1C if variant 0). Or an **Appearance** block of exactly 0xC bytes: `variant, tribeGenderHi, …` | [known] S 00486550, S 00486760 |
| 1 | **Style** block: `variant, hair, skin, shirt, trouser` + (`variant != 0`) `addColor1..4` | [known] S 004868c0 |
| 2 | **ActiveItems**: `variant`, 4 × {`slotType`, `itemId`, `count`} (empty slots keep slot types 2, 3, 4, 5) | [known] S 00486a20 |
| 3 | **Inventory**: `variant`, `count`, min(count, 20) × {`slotType`, `itemId`, `count`} | [known] S 00486b60 |
| 4 | **Stats**: `variant`, `level`, `exp`, `gold`, [`glod` if variant ≠ 0], [`x`, `y`, `z` f32, `heading` f32 degrees, `zone` u8, `ghostZone` u8 if variant > 1] | [known] S 00486d70 |
| 5 | unused | [known] S 00481e60 |

This blob is the game's own **save**: the client builds the character (look, items, gold/glod, level,
last position) from it at login, and the avatar-select screen draws it. The server keeps it current
(`lobby/sadk_lobby/savegame.py`). [PROVEN 2026-10-07: look, items and position restored after a re-login]
The avatar-select screen shows the saved colours but only some equipped items: items that change the
main-hand animation are not drawn there, and neither are some that do not [observed live 2026-10-07;
which items the select screen draws, and why, is TODO].

The avatar-select list comes from **RequestUserCharList (55)**: one UserCharConn (60) row per
character, then Result(42); `CharListReceived` S 00474910 keeps rows only for a 55 ticket. Entering
the village then logs chat and village in with the **picked character's id** (EnterVillage S 00503f50
-> CharacterManager+0x98, set by SelectCharacter S 00472200). [PROVEN 2026-10-07]

Rules that matter for a server:
- A blob shorter than 0x18 bytes makes all six parts empty. The avatar is then likely dropped
  silently. [inferred, board #2390]
- The part sizes are **not** checked against the blob length. They must be consistent. [known]
- `ApplyCharacterDataBlocks` S 00481e60 treats the character as **freshly created** when part 0 is
  non-empty, its size is not 0xC, and parts 1–5 are all empty. A fresh character gets level 1,
  gold = glod = 50 and the default spawn. Otherwise the blocks are parsed in full; stats variant 0
  forces glod = 1000. Look values are masked `& 0xF` on this path. [inferred]
- Each block parser succeeds whenever its buffer holds at least 4 bytes. Missing trailing fields
  keep their constructor defaults. [known]

---

## 2. Character lifecycle (lobby connection)

All character work goes through `CharacterManager`'s **action queue**, pumped by
`ProcessActions` S 00476390. These rules apply to every flow in this section: [inferred, board
#13/#67/#105]

- Only **one** action is in flight. The next one is sent only after the result for the head action
  arrives.
- A result whose action type does not match the head action is logged and ignored. The queue
  **stays busy forever**.
- A send error pops the action. For CreateCharacter it also fires "create failed".

Server rule: **answer every character request exactly once, in order, and always with its
completion message.** A missing Result stalls every later character, friend and ignore operation.

| Action type | Producer | tincat3 call | NETMSG | Completion → callback |
|---|---|---|---|---|
| 0 CreateCharacter | S 004750f0 | `AddCharacter` T 10015e90 | 86 | 153 AddResult → `CreateResultReceived` S 00476a40 |
| 1 DeleteCharacter | S 004751e0 | `RemoveCharacter` T 10016120 | 94 | 42 Result → T 100161e0 → `DeleteResultReceived` S 00473a50 |
| 8 LookUpName | S 00475370 | `RequestCharacterById` T 10015df0 | 72 | 75 rows + 42 → `CharacterDataReceived` S 00473590 |
| 9 LookUpID | S 004752a0 | `RequestCharacterByName` T 10015d50 | 72 | same |
| (list) | `RequestCharacterList` S 00472f00 | `RequestUserCharList` T 1002ea10 | 55 | 60 rows + 42 → T 1002f0c0 → `CharListReceived` S 00474910 |
| 2–7, 10 | friend/ignore/e-mail | UserManager | 56/157/88/… | see [LOBBY_PROTOCOL.md](LOBBY_PROTOCOL.md) |

LookUpName and LookUpID are answered from the local caches when possible. Every avatar seen in the
village fills those caches (`CacheUserName` S 004780c0). [inferred]

### 2.1 List characters

```
client                                   server
  55 RequestUserCharList {user_id, ticket=T}  ->
                                         <-  60 UserCharConn {char_id, name, ..., data, ticket=T}   x N
                                         <-  42 Result {errorcode=0, ticket=T}
  CharListReceived: builds one AvatarProxy per row, map +0x8c, sets +0x88 valid, MarkDirty
```

- **When:** in `LoadingGlobalData` (6), and again after the lobby logs out (S 00464bf0). The
  request first **clears** the local list. [inferred]
- **Login dependency:** state 6 → 7 needs **all four** of these: MotD done, character list valid,
  buddy list valid, ignore list valid. Buddies are requested only after the first two are done,
  ignores only after three are done. Any missing piece hangs silently in state 6. [known, S
  00464ee0, board #995]
- `user_id` in 55 is the client's chat-server handle. The callback's user id is the one the client
  sent (echoed by tincat3), not one from the wire. [known]
- Rows are delivered to the UI **only** when the Result arrives. A Result with `errorcode != 0`
  delivers zero rows. [known, T 1002f0c0]
- **Zero rows** is a valid answer. The log says "No characters found.", and the avatar screen opens
  in create mode once the list is valid and empty (`AvatarScreen::OnShow` S 0043b3a0). [inferred;
  the stub's live path always sends one character]
- The select dialog shows **at most 8** characters. "Create new avatar" is enabled only while fewer
  than 8 exist. [inferred, S 0043fa40]
- Row display: label = name; level and credits come from the stats block; the icon is
  `<Tribe><Gender>Small` with tribe 0 Bavarian / 1 Scot / 2 Egypt and gender 0 male / 1 female.
  [inferred, S 0043fa40]

**Stub:** answers 55 with one 60 and a Result(42). With `PERSISTENT_CHARACTERS_ENABLED = False`
(the current default) every account has exactly one implicit character with `char_id == perm_id`.
[PROVEN, character select and village entry live since s39]

### 2.2 Create a character

```
client (AvatarScreen, mode 0)                         server
  validate name locally; build Creation block (part 0)
  queue CreateCharacter; show "!CREATING_CHARACTER_TEXT" wait box (id 0x3000)
  86 AddCharacter {name, user_id, data=6-part blob, ticket=T}   ->
                                                       <-  153 AddResult {errorcode, errormsg, id=new char_id, ticket=T}
  success: new AvatarProxy(id, queued name, queued blob) -> map, fire CharacterManager+0x08
           AvatarScreen: close wait box, SelectCharacter(id), switch to select mode
  failure: fire +0x14 -> error box with the localized text for errorcode
```

- **Message:** creation is sent as **86 AddCharacter**, not 77 or 79. tincat3 also implements 77
  `CreateCharacterFromPreview` and 79 `AddCharacterFromPreview`, but this client's creation path
  does not use them. [inferred, board #4144]
- **Client-side checks** (S 0043b4d0, S 00439d20). A failed check sends nothing on the wire:
  - name at most **16 bytes**, and every byte must be in the NameEdit widget's allowed character
    set (from the layout XML). Failure shows `!CREATE_CHARACTER_NAME_INVALID`. [inferred]
  - an **empty name passes** this check, so the server must reject it. [inferred]
  - the name is converted ANSI → UTF-8 before it is queued (`Str_AnsiToUtf8` S 00487530).
    [inferred]
- **Appearance fields** come from the working avatar (`CharacterManager+0xa0`), edited in
  `CustomizeAvatarDialog` S 0043e500. The edits are local only and go out with the create request:
  - tribe = high nibble of byte `+0x48`; gender = low nibble (used as a boolean);
  - hair/skin/shirt/trouser = `+0x49..+0x4c`; addColor1..4 = `+0x4d..+0x50`.
  - The creation block is always variant 1 (0x2C bytes). The other five parts are empty.
  - [inferred]
- **Server decisions:**

  | Case | Reply | Client effect |
  |---|---|---|
  | accepted | `153 {errorcode 0, id = new non-zero char_id}` | character added and selected |
  | `errorcode 0` with `id 0` | — | tincat3 rewrites it to error 0x84 (T 100160e0) → create failed |
  | name taken | `153 {errorcode 71 CHAR_EXISTS}` | localized `!COMM_LAYER_ERROR_CHAR_EXISTS` |
  | other refusal | non-zero code from the CommLayer error table (S 00486010; 3 INTERNAL, 72 CHAR_NOT_FOUND, …) | error box |

  Error codes: [known, board #61]. Their use per case: [inferred].
- The server does **not** echo character data. The client builds the new avatar from its own
  queued blob. The server should store the blob verbatim and return it in later 60/75 rows.
  [known, board #2391]
- Reasonable server-side validation: at most 8 characters per account; tribe nibble 0–2 (the select
  icons know 3 tribes; the 3D model path clamps tribe to 1–5, see §4.3 — reconcile [TODO]); gender
  0 or 1; colour values small integers (the editor steps them by ±1, randomizes `& 0xF`). [guess
  for the ranges]

**Stub:** stores the blob and answers `153 {0, char_id}` when persistent characters are on. In the
default legacy mode, creation is not exercised. [inferred]

### 2.3 Select a character and enter the village

Selection is purely local: `SelectCharacter` S 00472200 sets `CharacterManager+0x98` and loads the
3D preview. Nothing is sent on the wire. [inferred]

The **Enter Village** button is enabled only when a character is selected **and** a joinable village
server exists (`AvatarScreen::Update` S 00439f30). A server is joinable when its list entry has
`+0x30 == client protocol version` (`DAT_0087aed8`) and `+0x35` (online) set. [known; joinability
PROVEN s15, S 00481640]

The village server list entry comes from 170 GameServerData, with `server_type = 4`. Its `data`
MEMBLOCK must be a 5-byte LobbyMessage stream: `u32 BE room/protocol key` followed by `1 bool`
(must be 0). A missing or invalid block logs "Invalid Server Data Block" and greys out Enter. The
entry's `server_id` must not collide with the UC server's id (1). The client resolves connections
by server id, and a collision reuses the UC socket instead of dialling. [PROVEN s12–s15, S
00481640]

```
client                                              server
 [7] Enter clicked: FindBestVillageServer (lowest load = players*100/capacity),
     SelectVillageServer -> AvatarScreen mode 2 -> CLobby vtbl+0x80(resetPosition)
     CreateVillageServerConnection (S 00463750): connection keyed by server_id
     OpenUserComm (S 00470d50) on the already-open UC connection
     UC logged-in notify -> OnUserCommLoggedIn (S 004704e0):
        FindCharacter(avatarId) -> SetLocalAvatar -> village transport Login(avatarId, 0)
        SetState(8 EnteringVillage); LM+0x54c = avatarId
  221 RequestConnectionData {server_id}             ->
                                                    <-  222 ConnectionData {perm_id, server_id, ip, port, nonce, errorcode 0}
  dial ip:port (village listener)
  188 CheckVersion                                  ->
                                                    <-  42 Result {0}
  211 StartValidateTokenSession  (or 224 TANLogin if opened with ConnectWithData)  ->
                                                    <-  212 AckValidateTokenSession {nonce}
  213 SendToken {perm_id, cipher}                   ->
                                                    <-  153 AddResult {errorcode 0, id = perm_id}
 [8] client waits; it sends no world-login request
                                                    <-  74{1000 EnterWorld}   (server push)
 [9] HandleEnterWorld ... (section 3.2)
```

- The village connection's base login uses the **per-server-id handler** `HandlerGS` T 10023460,
  not the UC handler. On it, a non-zero `153.id` overwrites the client's perm id
  (`ConnectionManager+0x24`). Send the same perm id the lobby issued in 207. [known, board #4776]
- `153.errorcode != 0` → OnError and disconnect. [known]
- The id passed to the village transport login is the **selected character id**, and `LM+0x54c`
  holds it. Whether this id is what reaches the server in 213's `perm_id` is [TODO]. In the stub's
  legacy mode `char_id == perm_id`, so both readings agree. With persistent characters
  (`char_id != perm_id`) the client reports a failed login after picking an avatar. This is
  consistent with the id mismatch, but not proven. [inferred]
- The exact point where 221 is sent, relative to the UC open, is [inferred]. The stub answers any
  221 for an unregistered id with the world address.
- If the character id is not in the CharacterManager, `OnUserCommLoggedIn` logs "WTF?! There is no
  avatar with that id" and sends no login. If the transport login returns an error, the client
  **still** enters state 8 and waits. [known, S 004704e0]
- **No timeout** for state 8 has been found. A server that never sends 1000 leaves the client on the
  loading view. [inferred]

**Stub:** pushes 1000 two seconds after the village 153. [PROVEN s39 (screenshot), S 0046f670 sets
state 9 as its first action]

### 2.4 Delete a character

```
client (SelectAvatarDialog)                         server
  DeleteAvatar -> confirm box "!LOBBY_CONFIRM_DELETE_AVATAR_TEXT"
  confirm (button 2) -> S 0043f3e0 -> DeleteCharacter(selected id); selection cleared
  94 RemoveCharacter {char_id, ticket=T}            ->
                                                    <-  42 Result {errorcode, ticket=T}
  T 100161e0 -> DeleteResultReceived(charId, errorcode):
     errorcode 0: erase charId from map +0x8c; MarkDirty (list rebuilds)
     always: pop action, end busy
```

[inferred: S 0043f3e0, S 00473a50, T 100161e0]

- `char_id` names the character exactly. Delete that one, never "the account's character".
- `char_id` comes back from the ticket, not from the wire. A Result with a stale or unknown ticket
  reports `charId 0`, and nothing is erased. [known, T 100161e0]
- After the last character is deleted, the next list request returns zero rows, and the client
  opens creation. [inferred]

### 2.5 Rename or change a character

- tincat3 implements 90 `ChangeCharacter {char_id, name, data, property_mask}` (T 10016550, result
  via T 1002d6b0 → listener slot 3). This client's `CharacterManager` has **no** action that calls
  it: the action types 0–10 cover create, delete, friends, ignores, look-ups and e-mail. **There is
  no rename flow in this client.** [inferred]
- The in-world appearance change ("tailor", LobbyAction 1 HairColor) is a **village** message:
  `3950 AvatarColorChange {Changes 8-bit mask, then one 4-bit colour per set bit, ascending}` (S
  0046c760). In village mode the editor only allows colour slots 3–7 (S 0043e7f0). The server
  should apply the change to the stored character. It should then re-broadcast the avatar's Style
  block (1001 with dtblcks bit 1) to everyone in the world. [inferred for the re-broadcast; the
  stub logs and drops 3950]
- E-mail changes use 88 ChangeUser with property mask 8 (`UpdateEMail` S 00475a70). [inferred]

---

## 3. Village connection: set-up, EnterWorld, keepalive

### 3.1 Inbound routing

tincat3 routes **only** NETMSG 73 and 74 on the village connection to
`VillageServerConnection::HandleMessage` S 00470a90, keyed on the inner id. A bare 1000 frame is
dropped. Sending 1000-series bodies on the lobby or UC connection is unsafe: those connections lack
the templates. [PROVEN s35, S 00470a90 / stub `village.gamedata_frame`]

Server → client avatar events (1001/1002/1003) are **queued** (`+0x1ac/+0x184/+0x198`) and drained
to observers. AvatarData deliveries are held until state 9. NPC records (1004) notify immediately.
[known]

### 3.2 EnterWorld (1000)

Fields: `Worldname str; ServerPerm u32; ChatChannelsCount u32; N × {ChatChannelZone u32, ChatChannelID u32}`.

What `HandleEnterWorld` S 0046f670 does, in order: [known]
1. `SetState(9 VillageEntered)`.
2. Stores the world name (`<UNNAMED>` if empty) and `ServerPerm` at `+0x160`.
3. Fills the chat map `+0x164` with **key = low byte of ChatChannelZone**, value = cell id.
4. Joins `map[0xFF]` (the global channel) through the UC connection (NETMSG 17).
5. Requests mail headers, sends the first PingCode (§3.4), and fires the EnterWorld observers.

Server decisions:

| Field | Accepted values | Effect / hazard | Tag |
|---|---|---|---|
| `Worldname` | ≤ 255 UTF-8 bytes | display name; the stub uses the 170 entry's name | [known] |
| `ServerPerm` | any u32 that is **not** a player perm id | chat lines whose `from_id == ServerPerm` show as `[SYSTEM]` plus the modal `!LOBBY_IMPORTANT_SYSTEM_MESSAGE` (S 00436180) | [inferred]; the stub sends 0 |
| channel key `0xFF` | required | global tab; auto-joined | [PROVEN 2026-08-01, S 0046f670] |
| channel key `0xFE` | recommended | minigame tab | [inferred] |
| channel keys `0x00..0x0D` | optional, one per zone | local tab. On a zone change `JoinZoneChatChannel` S 0046e860 leaves the old cell and joins `map[zone]` | [inferred] |
| `ChatChannelID` | **non-zero**, and the cell must also exist on the UC/chat server | cell id 0 is the invalid sentinel: chat submit returns silently (S 00436860) | [PROVEN 2026-08-01] |

After 1000, the server should send, in this order (stub order, [PROVEN 2026-08-01]):
1. **1005 WorldTick**, so the clock is synced before any waypoint (§4.2);
2. **1004** NPC records (§5);
3. **1001** for every other player already in the world, plus this player's 1001 to each of them
   (§4.1).

The stub waits about 2 s after 1000 before sending these.

### 3.3 Re-entering

The client also sends 2002 at **match start** (§7). Do not answer 2002 with a new 1000: that makes
the client re-enter the lobby world instead of leaving. A connection that leaves and later returns
goes through §2.3 again. [PROVEN 2026-07-26/27; the earlier "answer 2002 with 1000" behaviour
caused the match-start stall]

### 3.4 Keepalive

```
client                                server
  74{0x2ED6 PingCode {code u32 random}}   ->
                                      <-  74{0xED7 PongCode {code}}   (echo)
```

- The first ping is sent from `HandleEnterWorld`. Answer within **30 s**, or link quality
  (`+0x244`, 0..3) drops to 0. After a pong, the next ping comes about **120 s** after the previous
  one. [inferred, board #47]
- `HandlePongCode` S 0046c250 matches the pending code (`+0x248`) and grades the round-trip time.
  Echo the code. [known; the stub echoes it, PROVEN in every live session since s35]
- The TinCat kernel also sends `STAYINGALIVE` frames; they need no reply. [inferred]
- **Never** answer a ping with 1006. 1006 is the logout trigger (§7). [PROVEN 2026-07-26, S
  0046ec50]

---

## 4. Presence: players in the world

### 4.1 Spawning, updating and removing other players

| Msg | Meaning | Client action | Tag |
|---|---|---|---|
| **1001 AvatarData** `{id, dtblcks 4 bits, blocks…}` | create-or-update | Unknown id: new AvatarProxy in `+0x170`, then parse the blocks. Known id: parse the blocks. The name is cached; queue `+0x1ac` → render | [PROVEN 2026-08-01, S 0046e1d0] |
| 1002 AvatarLoggedIn `{id}` | reserve an id | Unknown id: empty proxy; known id: error "Avatar already logged in." Not needed for a working spawn | [known, S 0046e390]; the stub does not send it |
| **1003 AvatarRemove** `{id}` | player left | Queue `+0x198` → observers `+0xb0` (despawn); the proxy stays in the map | [known, S 0046e570]; the stub sends it when a village socket closes |

`dtblcks` bits, in read order: 0 Location, 1 Style, 2 ActiveItems, 3 Stats. Any subset may be sent.
The blocks follow in bit order. [known, S 00482c20]

Server flow when player B enters a world where A already is:
1. To B: 1005, then for A: 1001 (Location + Style) at A's last reported pose.
2. To A: 1001 (Location + Style) for B at B's pose (or a spawn placeholder).
3. To both: two location-only 1001s that **prime** the waypoint ring (§4.2).
4. From then on: relay each 2000 report as a location-only 1001, and refresh every stationary
   avatar about once per second.

When B's village connection closes, send 1003 for B to everyone else in the world. [PROVEN
2026-08-01 (spawn and movement, TTD-verified), `dispatch._spawn_world_avatars`]

Rules:
- **Never send a malformed or truncated 1001.** A 2-byte body crashed the client about 1 s later.
  Keep probes well-formed and vary only the values. [PROVEN 2026-07-31, negative control]
- The client does **not** apply a Location block to its **own** avatar
  (`ReadLocationBlock` S 004824b0). The bits are consumed, so the body stays in sync: the 16-bit
  tick is stored for every avatar; then, for proxy id == `LM+0x54c`, posx 11, posy 11, posz 11,
  rot 7, zone 4 (S 0048f790), ghstzne 4 (S 0048f970) and rnng 1, jmp 1 (S 0048f950) are read and
  dropped, 50 bits. [known] That the storing branch (S 0048f670, S 0048f930) reads the same widths
  rests on the field names. [inferred] The Style, ActiveItems and Stats blocks have no own-id
  branch (`ReadDataBlocks` S 00482c20) and are applied to the own proxy, so a 1001 for the own id
  is a working way to set the own avatar's style, equipped items and stats. [known] `CLobbyClient::UpdateAvatar` S 00503620 then pushes a movement sample only to a net controller
  (controller slot `+0x10`); the own avatar's `CLocalController` returns 0 there (vftable
  S 007e70e8 slot 4 = S 0072db80), so nothing is pushed and the avatar neither moves nor
  vanishes; `CGfxObjAvatar::UpdateAppearance` runs and shows the new look. [known]
- The own avatar is in the avatar map without any 1001: `+0x170` points at the map at `LM+0x558`,
  and `LobbyComm::System::SetLocalAvatar` S 004626c0 inserts a copy of the chosen character there before
  the village login is sent (`OnUserCommLoggedIn` S 004704e0). The `ownr` lookups of 0xC1C–0xC1E
  and 0xC80 / 0xC81 therefore find it. Nothing empties the avatar map while the local proxy stays
  registered (`ClearAvatarsAndEventQueues` S 0046fab0 runs only after `ClearLocalAvatar`, in
  `HandleLoggedOut` and `HandleDisconnected`). [known]
- One village connection per player. When a client reconnects, address only the newest
  connection, or every message arrives twice. [PROVEN, stub `_in_world_conns`]

### 4.2 Movement and the world clock

```
client A                         server                          client B
  74{0x27D0 2000 AvatarLocation}  ->
     {tick16, posx/posy/posz 11, rot 7, zone 4, ghstzne 4, rnng 1, jmp 1}
                                  store pose; re-stamp tick
                                                             ->  74{1001 id=A dtblcks=1 Location}
```

- **Report rate:** every 4th frame of the local controller (S 0051ace0), so the rate depends on the
  frame rate. The stub sees about 3 per second. `tick` is sent as `tick | 1` (never 0). [known for
  the code; observed rate PROVEN 2026-08-01]
- **Quantisation:** 11 bits per axis over x ∈ [-150, 150], y ∈ [-10, 30], z ∈ [-150, 150]
  (`value = raw/2048·(max−min)+min`); rotation is 7 bits (`raw·360/128` degrees). Out-of-range
  values wrap modulo 2048 on the client side. [known, S 0048f670 / S 0048f7e0]
- **How remote avatars are drawn:** each later 1001 location pushes a **waypoint** into an 8-slot
  ring (S 00519b20), stamped `reconstruct(tick16) + 2000 ms`. The per-frame interpolator
  (S 00519d50) positions the avatar **only** from that ring:
  - an empty ring snaps the avatar to (0,0,0) and hides it one frame after spawn;
  - waypoints older than about 3 s hide the avatar;
  - waypoints in the future underflow and hide it;
  - waypoints at about (0,0,0) are rejected.
  [PROVEN 2026-08-01, TTD]
- **tick16 reconstruction:** expanded to the nearest wrap of the client clock (S 004f4d10), within
  ±32.7 s. [inferred]
- **Clock sync, 1005 WorldTick `{tick 64}`:** if the client world clock differs in phase from
  `tick & 0xFFFF` by **250 ms or more**, the clock is slewed to match (S 0057b910). After that,
  repeats are no-ops. The high dword **must be 0**: a shipped 64-bit read bug folds the halves
  together. Send 1005 before the first waypoint; a later slew does not re-anchor waypoints that were
  already stored. [PROVEN 2026-08-01]
- **Server timing rule:** stamp relayed locations from the **server's own clock**, about 1 s in the
  past (`now − 1000`), not with the sender's tick. With the sender's tick every waypoint lands
  about 2 s in the future. Prime a new avatar with stamps at `now−3000` and `now−1000`, so the ring
  brackets "now" immediately. [PROVEN 2026-08-01]
- **Zones:** relay `zone` and `ghstzne` verbatim. Zone 0 is the outdoor square; minigame rooms and
  the hall of fame are other zones. `ghstzne = 15` is the neutral "no ghost zone" value (the minimap
  shows the square when `zone == 0 && ghstzne == 15`). Hardcoding 0/0 shows a player who went into
  a side room as still outside. [inferred, minimap gate S 0045fd30]
- `rnng`/`jmp` drive the remote run and jump animation. Relay them. `jmp` is set by Space and
  cleared after a frame that was sent. [known]

### 4.3 What the client renders from which block

| Block / message | Renders | Ranges | Tag |
|---|---|---|---|
| Style (1001 bit 1) `name str, trbgndr 8, 8 × colour 8` | name label, model, tint | `trbgndr`: high nibble = body part (model math clamps to < 3), low nibble = gender (boolean). Model index = `bodypart + (tribe−1)·3`, with tribe clamped to 1–5 (from a separate getter). Colours land in proxy `+0x49..+0x50` | [PROVEN 2026-08-02 for name and model, S 00508090] |
| Stats (bit 3) `lvl, exp, gold, glod 32` | level, XP bar, credits / play money | `exp` should lie between `thr[lvl]` and `thr[lvl+1]` of the XP table at S 007d8d90, or the bar wraps | [inferred] |
| ActiveItems (bit 2) `4 × {sltt 8, cnt 8, itmid 32}` | equipped items (Pet, Head, RightHand, LeftHand) | always exactly 4 records | [known, S 0048abe0] |
| 0xC1C / 0xC1D / 0xC1E | re-sync active items / inventory / both, by `ownr` | inventory: `sltcnt` is read and **ignored**; send exactly the client's slot count (0 before init, otherwise max(20, n)) | [known, S 0048ac20] |
| 0xC80 `{ownr, lvl, exp}` / 0xC81 `{ownr, lvl, exp, gold, glod}` | stats update | unknown `ownr` is dropped silently; 0xC80 fires no UI notify | [known] |

`itmid` values are the item ids of `ItemsClient.txt`, a plain-text file (not an encrypted
container) in the install's `data/lobby/config/`; the shipped file defines 36 items, ids 1..36.
`LobbyComm::System::Initialize` S 004643d0 loads it once with `ItemDatabase::LoadFromFile` S 0048bfd0
into a map (item id → ItemInfo) at `LM+0x570`; if the file cannot be opened it logs `Loading of
ItemDatabase failed!` and returns before the comm layer is created, so the lobby never starts.
[known] That 3100–3102 `itmid` uses these ids is [inferred]; for 0xE11 `ItemID` it is [known]
(S 0045b790).

Parsing [known]: each line is trimmed; a line whose first character is `#` is skipped; the rest is
tokenised on `;` with `"` as quote and `\` as escape and must give exactly 9 tokens, otherwise it
is logged (`Invalid line %d (only %d tokens)`, an empty line included) and skipped. A duplicate id
is ignored (first wins) [inferred].

| Token | ItemInfo | Meaning | Tag |
|---|---|---|---|
| 0 | `+0x00` u32 | item id | [known] |
| 1 | `+0x04` string | name (text key, e.g. `!LOBBY_ITEM_CROWN`) | [known] |
| 2 | `+0x20` string | description (text key) | [known] |
| 3 | `+0x3c` u32 | always 4 in the shipped file; no reader found; meaning [TODO] | [known] offset |
| 4 | `+0x44` int | always 1 in the shipped file; ≥ 1 makes the item valid (below); meaning [TODO] | [known] offset |
| 5 | `+0x40` u32 | equipment slot mask (below) | [known] |
| 6 | `+0x48` string | mesh name | [known] |
| 7 | `+0x64` string | icon name, resolved through `itemicons.txt` (plain text, 6 tokens, loader S 00430ae0) | [known] |
| 8 | `+0x80` u32 | base value: the shop sell price of an item the open shop does not list is base value × SellMod (§6.1) | [known] |

- **Slot mask.** `CanItemGoToSlot` S 0044d390: container 0 (backpack) always fits; containers 2, 3,
  4, 5 need a valid item and mask bit 0, 1, 2, 3. [known] In the shipped file the head items have
  mask 1, the right-hand items 2, the Slord and the ring 4, the pets 8, so container 2 = head,
  3 = right hand, 4 = left hand, 5 = pet. [inferred, from the data rows and the equip order in
  S 0044e0f0] Which code interprets the wire field `sltt` is [TODO].
- **Valid item** (S 0048b100): (id ≠ 0 and name not empty) or token 4 ≥ 1. [known] Every shipped
  item is valid.
- **Unknown id.** The network handlers do not check ids. `ItemDatabase_GetItemInfo` S 0048b6c0
  never fails: an id outside the file returns the shared placeholder `g_InvalidItemInfo`
  S 00885978 (id 0, name `!INVALID_ITEM_NAME`, mesh `InvalidItemMesh`, icon `InvalidItemIcon`, all
  numbers 0), which is not valid, fits no equipment container and gets the `InvalidIcon` shape
  (S 0042f670). [known] One path does not return cleanly: with a shop open, hovering an inventory
  slot that holds such an id reaches `GetShopSellPriceByItemId` S 0046d6d0, which calls
  `_invalid_parameter_noinfo` and then reads one entry past the end of the stock vector
  (S 0046d73e..0046d7dd). [known] On an avatar an unknown `itmid` shows nothing:
  `CGfxObjAvatar::SyncEquipmentSlot` S 00507f60 attaches only a valid item and clears a slot that
  showed one before. [known] In the backpack an unknown id (99) draws an empty slot, hovering it with a shop
  open shows nothing and the process keeps running [live, 2026-10-14], so the hover does not reach the
  failure path above (`docs/message-catalog.md` V23).

---

## 5. NPCs

### 5.1 The NPC record (1004)

```
server                                         client
  74{1004 {id, npcdesc str, posx/posy/posz 11, rot 7, zone 4,
           hrclr 4, sknclr 4, shrtclr 4, trsrclr 4, npcidx 4, bdyprt 4,
           npctyp 2, actcnt 8, actcnt × {act 8, actChat str}}}  ->
                                               NPCProxy (0x120) into +0x174, notify +0x38 at once
                                               -> S 005031a0 -> S 004f6ea0 builds the 3D object
```

[known for the reader, S 0047b5c0; spawning and rendering PROVEN 2026-08-02]

| Field | Accepted values | Effect | Tag |
|---|---|---|---|
| `id` | u32 not used by any avatar or player (the stub uses ≥ 1 000 000) | key in the NPC map (separate from avatars) | [known] |
| `npcdesc` | UTF-8 string, ≤ 255 bytes | label | [PROVEN 2026-08-02] |
| location | as §4.2, but **no** tick, ghost zone or run/jump fields | static placement; no refresh stream needed | [inferred] |
| colours | 4-bit nibbles (0–15) | tint `+0x49..+0x4c` | [known] |
| `npcidx` | 0–15 | **model selector** for type-2 proxies | [PROVEN 2026-08-02, S 00508090] |
| `bdyprt` | 0–15 | stored at `+0x48`; not used for the NPC look | [known] |
| `npctyp` | 1 = settler template person, 2 = letterbox; anything else = no visual | | [known, S 004f6ea0] |
| `actcnt` | **0–3** | **≥ 4 corrupts the heap**: the `actChat` strings are written without a bound | [known, S 0047b5c0 disasm] |
| `act` | LobbyAction id (below) | copied unchanged into the world screen's three action slot codes when the NPC is selected (S 0047b200); a single action in slot 0 is dispatched at once on selection, see §5.2. The slot parameter is always 0 for an NPC | [known, S 00437760] |
| `actChat` | UTF-8 string (read with the UTF-8 → ANSI string reader into `NPCProxy+0xc8 + i·0x1c`) | the NPC's **spoken line** for that slot: speech bubble plus a chat line, see §5.2. Not a button label | [known, S 004337f0] |

LobbyAction table (button templates S 004325b0; what a code does is the switch on `code − 2` in
`DispatchSlotAction` S 00434230 [known]). "NPC text" = the slot's `actChat` is shown afterwards:

| `act` | Action |
|---|---|
| 0, 19, other | None (button hidden); no case in the switch |
| 1 | HairColor: labels the button only; `DispatchSlotAction` S 00434230 has no case for it, so the button does nothing (live 2026-10-07) |
| 2–6 | MinigameMatchmaking: sound 0x63c3110f, CLobby vtbl+0xd4, `MiniGameMatchMakingDialog::Open(true, code − 2, −1, mode 0, 0)`, NPC text. Local |
| 7 | Mailbox: if the mailbox dialog exists, is usable and not shown: sound 0x63c3110d, show it, `PostOffice::RequestMailHeaders` |
| 8 | HostGame: `ServerList::CreateGameServer` (the host-game request on the lobby connection); on success clears the setup-game flag (`+0xBA8`) |
| 9 | ListGames: toggles the browse-games dialog. Local |
| 10 | Hall of Fame: sound 0x63c3110e, `System::OpenHallOfFameDialog`, NPC text |
| 11 | OpenShop: sound 0x63c3110c, `SendOpenShop(selected actor id)` → village 0x2E10, NPC text |
| 12, 13 | create a minigame table: CLobby vtbl+0xd4, `Open(true, code − 12, table = slot parameter, mode 1, 0)`. Local |
| 14, 15 | join a minigame table: CLobby vtbl+0xd4, `Open(true, code − 14, −1, mode 2, slot parameter)`. Local |
| 16 | NPC text only |
| 17 | Tailor (clothes): if CLobby vtbl+0x74 is false and the own avatar exists: gold < 50 → `!TAYLOR_QUESTION_NOMONEY`, else asks `!TAYLOR_QUESTION` (callback `OnTailorQuestionResult`). Nothing is sent here |
| 18 | clears the setup-game flag if set. Local |

Codes 12–15 from an NPC would use table / parameter 0, because an NPC's slot parameters are always 0.

- **No message removes an NPC record.** [known] The village dispatcher `HandleMessage` S 00470a90
  handles exactly 24 ids (0xD8–0xDC, 0x12F, 1000–1006, 0xC1C–0xC1E, 0xC80, 0xC81, 0xE11, 0xE1B,
  0xE25, 0xED7, 0xF46, 0xF5A) and drops everything else silently; only 1004 touches the NPC map
  (`+0x174`, which points at the map at `LM+0x564`), and it only adds or re-reads in place
  (S 0046f8c0). 1003 concerns the avatar map only. The map is emptied by `ClearNPCs` S 0046fc10,
  called only from `HandleLoggedOut` and `HandleDisconnected`: it fires the "NPC removed" observers
  (`+0x44` → `CLobbyClient::OnNPCRemoved` S 005031d0, which destroys the 3D object) for every
  record. The connection's destructor (S 0046e922) also clears it, without firing the observers.
  So NPCs disappear only when the village connection logs out or drops.
- A 1004 for a known id re-reads the proxy in place (name, position, act ids, actChat) and fires
  observers `+0x38` again, but `OnNPCAdded` S 005031a0 returns at once when the proxy already has a
  3D object, so the existing object is not rebuilt. [known] A re-sent 1004 does not move the
  visible NPC but changes its label: a kind-1 NPC (class `Settler`, controller `character`) has a
  `CNetController` in interpolation mode 2 (NPCProxy vftable S 007dc7d8 slot 1 = S 004f1ea0), which
  outputs the creation transform for ever (`CNetController::Update` S 00519d50 interpolates in mode
  1 only; `PushActorSample` S 00519b20 is called from the 1001 path only), while
  `CGfxObjAvatar::DrawNameTag` S 00506860 reads the proxy's name when it draws. A kind-2 NPC has a
  `CStaticController` with a constant pose (S 005197f0). [known] Not read: whether the selection
  distance or the minimap use the proxy's position.
- "Walkers" (moving ambient figures) are ordinary 1001 avatars with ids in the NPC range. They have
  no interaction, and they need the 1 Hz waypoint refresh. [PROVEN 2026-08-02, stub `npcs.py`]
- `npcidx` → model: it indexes the **male** `<bodypartset>` of `data/lobby/config/npc_bodyparts.xml` in
  file order. Only the first 16 of its 17 heads are reachable, and the female set not at all, so a 1004
  NPC cannot be female. [PROVEN 2026-10-07, live lineup of npcidx 0–15]

  | npcidx | head (`meshLod0`) | in-game look |
  |---|---|---|
  | 0 | Severin | Wütherich (campaign character) |
  | 1 | zeus | Zeus (campaign) |
  | 2 | Kostas | Kostas (campaign) |
  | 3 | npc01 | hired Bavarian goon (campaign) |
  | 4 | npc02 | hired Egyptian goon (campaign) |
  | 5 | npc03 | Bavarian halberdier, blond moustache, red clothes |
  | 6 | npc03b | Bavarian halberdier, red moustache, green clothes |
  | 7 | bavarian_soldier1_mesh | Bavarian halberdier, unarmoured, unarmed; idle: squints, hand above the eyes |
  | 8 | bavarian_soldier2_mesh | Bavarian halberdier, unarmed, blond moustache, blue clothes |
  | 9 | bavarian_soldier3_mesh | Bavarian halberdier, unarmed, golden armour, grey clothes |
  | 10 | egypt_male_5 | Egyptian original character; idle animation sits as if mounted (floats on flat ground), model turned 270° |
  | 11 | egypt_soldier2_mesh | Egyptian generic (medium computer opponent) |
  | 12 | egypt_soldier3_mesh | Egyptian generic (hard computer opponent) |
  | 13 | scot_soldier1_mesh | Scottish generic (easy) |
  | 14 | scot_soldier2_mesh | Scottish generic (medium) |
  | 15 | scot_soldier3_mesh | Scottish generic (hard) |

  The field is `ReadNamedBits(msg, 4, "npcidx")` (S 0047b5c0), so 16+ cannot be encoded. Other looks
  (female, every tribe, items) are only possible as 1001 avatars, which have no action buttons
  (AvatarProxy slot 5 zeroes the codes, S 00482490). The colour palette per model is still [TODO].

#### How the client picks an NPC model (why only the male set)

[known: Ghidra, sadk_noav.exe, 2026-10-08]

- **Two model databases.** `CLobby::StartUp` S 004f8c90 loads two `AvatarBodyParts` catalogues:
  `[data]/config/bodyparts.xml` into `CLobby+0x124` (players) and `[data]/config/npc_bodyparts.xml` into
  `CLobby+0x128` (NPCs). A `CGfxObjAvatar` sees them at `gfxContext+0x64` / `+0x68`.
- **Which database.** `CGfxObjAvatar::SetActorProxy` S 00505550 (and the constructor S 005084b0) sets
  `bAltModelTable` (`+0x630`) when the proxy's `ActorID` kind is 2 (an `NPCProxy`), and
  `UpdateAppearance` S 00508090 then uses `npc_bodyparts.xml`.
- **Which entry.** `UpdateAppearance` calls `AvatarBodyParts::AcquireVariant(set, slot 0, index)`
  S 004fd2a0, where `set` is the `<bodypartset>` in file order:
  - players (`GetActorType` 1): `set` = gender, `index` = body part + (level − 1) × 3 (in `bodyparts.xml`);
  - everything else, i.e. every `NPCProxy`: **`set` is the constant 0**, `index` = the proxy's NPC index
    (`+0xc0`).

  `Lobby::CGfxObjAvatar::Render` S 00507580, the only other caller, reuses the stored pair. No code path passes another
  set, so the **female, MacDoyleJr and MacGabhan sets of `npc_bodyparts.xml` are never used by this
  build**: Sakhmet, Moppet, the three tribe women, MacDoyleJr and MacGabhan cannot appear as NPCs
  without a client patch.
- **Loader.** `AvatarBodyParts::LoadFromXml` S 004fd760 numbers the entries in file order and silently
  skips an entry missing any of `meshLod0`, `meshLod1`, `meshLod2`, `texture` (`slotMap` defaults to
  `default`). Every entry of the shipped file is complete, so the numbering is plain file order:

  | set | entries (index: `meshLod0`) |
  |---|---|
  | 0 `male` (`avatars/model.KEX`) | 0–15 as in the table above; **16: `egypt_soldier1_mesh`** |
  | 1 `female` (`avatars/model_woman.KEX`) | 0: Sakhmet, 1: Sakhmet (same entry twice), 2: Moppet, 3: `bavarian_woman_1`, 4: `scot_woman_1`, 5: `egypt_woman_1` |
  | 2 `MacDoyleJr` (`avatars/model_MacDoyleJr.KEX`) | 0: MacDoyleJr |
  | 3 `MacGabhan` (`avatars/MacGabhan_model.KEX`) | 0: MacGabhan |

- **Where entry 16 is used: computer opponents.** In the pre-game room,
  `SetupGameDialog::RefreshPlayerRows` S 00455fd0 shows each AI slot as a client-side `NPCProxy` whose
  NPC index comes from the table at **`0087a6f8`**, `[tribe × 3 + AI level]` (no bounds check):

  | tribe (slot value) | easy | medium | hard |
  |---|---|---|---|
  | 0 | 7 `bavarian_soldier1_mesh` | 8 `bavarian_soldier2_mesh` | 9 `bavarian_soldier3_mesh` |
  | 1 | 13 `scot_soldier1_mesh` | 14 `scot_soldier2_mesh` | 15 `scot_soldier3_mesh` |
  | 2 | 16 `egypt_soldier1_mesh` | 11 `egypt_soldier2_mesh` | 12 `egypt_soldier3_mesh` |

  The tribe names per row follow the mesh names [inferred]. So the soldier meshes are the computer
  players' portraits, and `egypt_soldier1_mesh` (easy Egyptian) can only be seen there.
- **Developer preview.** `CLobby::ApplyCustomizeAvatarLook` S 004f84b0 has a debug path behind the CVar
  `Evil Hacks/CustomizeNPCHack` (`008882c8`): it puts a static `NPCProxy` with NPC index
  `Evil Hacks/NPCIndex` (0–32, unchecked) and colours `color1`–`color8` on the character-creation
  preview, and `Evil Hacks/SAVE` writes it as an avatar file `CustomizedNPC`. CVars are only reachable
  with the optional CVar-server patch (`docs/BINARY_PATCHES.md`, `tools/cvar_client.py`). It still only
  shows set 0 (indices 17+ read past the set) [inferred from the code; not tried live].
- **No other source of the set.** An `ActorID` kind is read from the wire only for minigame seats
  (`ActorID::ReadFromMessage` S 00490e40, sole caller `MiniGameProxy::ReadSeats`), so no server message can
  give a player-type proxy the NPC table either.
- **Client patch** (the npcmodels mod, `mods/npcmodels`, `docs/BINARY_PATCHES.md` "NPC model sets"): the
  record's `bdyprt` nibble reaches the `NPCProxy` (`+0x48`) but is unused for NPCs; the patch makes it the
  set number. With `bdyprt` 0 nothing changes. The client checks neither number, so a server must send only
  sets and indices that exist. Verified offline against the binary; **not yet live-tested** [TODO]. The
  stub's `!npc <set> <index>` spawns such an NPC next to the speaker; a client without the mod shows
  male entry `index` instead.
- **Other NPC-ready characters.** `data/lobby/avatars` also holds meshes and colour maps (`color_slots.xml`
  slot maps) for Garibald, Hatschipsut, MacDoyle, the pirate (`pirat`) and Theofanos, which no body-part list
  references. All lobby character meshes use the same 46 bone names as the four base models, so they could be
  added to `npc_bodyparts.xml` by a mod [inferred from the bone names; untested].

**Stub:** NPC spawning is on (`config.VILLAGE_NPCS_ENABLED = True`): eight record NPCs at the
maintainer's measured spots (shops, tailor, hall of fame, games, both taverns' matchmakers, mail) and one
walker (`lobby/sadk_lobby/npcs.py`).

### 5.2 NPC interaction

Selecting an NPC copies its `act` list into the world screen's three action slot codes. An NPC
whose only action sits in slot 0 runs that action at the moment it is selected, and the selection
then returns to the own avatar. [known, S 00437760] Most actions are local (matchmaking dialog,
host/list games, hall of fame, mailbox, tailor); only **OpenShop** puts a village message on the
wire (§6.1), and codes 7 and 8 send through the PostOffice and the server list. [known, S 00434230]

The chain, read in Ghidra on 2026-10-08 [known statically]:
- `WorldScreen::RefreshActionSlots` S 00433f60 (every frame) takes the codes from a selected scene object
  first (letterbox: 7; minigame table spot: create 12/13 or join 14/15), else from the selected actor through
  its vtbl+0x14: `NPCProxy::GetActionSlots` S 0047b200 copies the record's `act` ids unchanged; a player
  (`AvatarProxy` S 00482490) gives none. With nothing or yourself selected: host 8 and list 9.
- `WorldScreen::SetActionButton` S 004325b0 applies the button template `LobbyAction_*` (all present in
  `game/ui/layout/templates.xml`, codes 2-6 → `LobbyAction_MinigameMatchmaking`) and enables the button.
  Its only call site (S 0043414f) is in the "nothing or own avatar selected" branch of
  `RefreshActionSlots` (codes 8 + 9, or 0x12 + 0x13). For a selected NPC, other avatar or scene object
  the codes are filled in, but all three buttons (`+0x3560` / `+0x3564` / `+0x3568`) get the template
  `LobbyAction_None` and button vtbl+0x24(0) (loop S 00434175..0043420e). [known] Slot `+0x24` of the
  button vftable (S 007dff14) is `nUi::Object::SetVisible` S 004a1090; with 0 it calls `Hide`, so the three
  buttons are hidden. A hidden button cannot latch a click: `Object::OnMouseButton0Up` S 0049ff60 sets the
  latch only when the widget's visible test (slot `+0x2c`) holds. [known] The minigame
  functions `LeaveMiniGameMode` (S 00431b31) and `HideMinigameObserverDialog` (S 00431f21) call
  vtbl+0x24(1) on all three buttons whatever is selected.
- `WorldScreen::HandleButtonClicks` S 00437760 is the only caller of `DispatchSlotAction`. It returns
  early when the base screen handler returns false or CLobby vtbl+0x8c (S 004f50d0, byte `+0x11` of the
  lobby client) is true. Then: the selection-changed latch (`+0x3638`, set only when the selected actor
  pointer changes, S 00434068) is tested and cleared; if it was set and slot 0 holds a code while
  slots 1 and 2 are 0, it calls `DispatchSlotAction(0)` and then CLobby vtbl+0xc0 (`SelectLocalAvatar`
  S 004f5e00). After that the click latches of the three buttons dispatch slot 0 / 1 / 2, with no test
  of what is selected. [known] Consequences: the automatic dispatch is the only path for an NPC's codes; an
  NPC with two or three actions gets no automatic dispatch and its buttons are hidden, so none of its
  actions can be run and `actcnt` is effectively 0 or 1 for a working NPC [known; live 2026-10-12 for a
  two-action NPC]. A shop action in slot 0 next to a second action therefore sends no 0x2E10. In the scene-object path
  `selectedObject` (`+0x3630`) is 0 (S 00434047), and code 11 reads it without a null check.
- `WorldScreen::DispatchSlotAction` S 00434230 runs the code. Codes 2-6 call
  `MiniGameMatchMakingDialog::Open(true, tavernId = code - 2, table 0xFF, mode 0 = search, 0)` S 00444cb0
  (phase 1, "create" / "search"). Its `Update` S 00445cf0 lists only tables whose `scntblLo - 2` equals the
  tavernId, so a tavern's matchmaker needs code = the tavern's scene id (stub: 3 for taverne02, 2 for
  taverne03). A game created there goes out as 2001 with `tvrn` = tavernId and `tblidx` 0xFF, which the stub
  handles (first free table). `Open` also registers a 2-unit walk-away watch (`CLobby::AddDistanceWatch`
  S 004fb5f0) that closes the dialog once the avatar moves farther than that from where it was opened.
- **`actChat`** is the NPC's spoken line for that slot: codes 2-6, 10 and 11 fall through to
  `ShowNpcSlotText(npc, actChat[slot])` S 004337f0, and code 16 shows only that text; codes 7, 8, 9,
  12-15, 17 and 18 never show it. The single accessor is S 0047b250 (`&actionChat[index]`, the shared
  empty string for index > 2). `ShowNpcSlotText` does nothing for an empty text; a text starting with
  `!` is first replaced by the localized string for that key. The text then goes (a) to the NPC's 3D
  object (`CLobby` vtbl+0xe4 S 004f53d0 → `CGfxObjAvatar::ShowChatText` S 005079b0): a text containing
  `/word` is tried as an emote (lower-cased; no bubble if the emote plays), otherwise it becomes the
  speech bubble for (length + 10) × 75 ms; and (b) into chat tab 0 as
  `[<NPC name>] <!LOBBY_CHAT_FROM> : <text>`, whether or not the bubble is shown. [known statically;
  not seen live]

**Open: the matchmaker NPC does nothing when clicked** (maintainer, live). [TODO] Established: a
one-action matchmaker NPC (code 2..6) is dispatched on selection exactly like a shop NPC (sound,
CLobby vtbl+0xd4, `MiniGameMatchMakingDialog::Open` in search mode), and nothing in that path depends
on a button or touches the network, so the stub's log cannot show where it stops. Not established:
what CLobby vtbl+0xd4 (S 004fad00) does and what `Open` S 00444cb0 requires; whether
`DispatchSlotAction` is reached at all in the live case (`docs/live-session-queue.md`).

---

## 6. Shops, inventory, trade and minigame tables

### 6.1 Shop (client-initiated)

```
client                                              server
  74{0x2E10 OpenShop {NPCID u32 = selected actor id}}   ->
                                                    <-  74{0xE11 ShopInventoryData {NPCID, ShopID, ShopName str,
                                                             SellMod 32 (LE float inside the BE stream), StockCount 16,
                                                             N × {ItemID, Buy, Sell 32}}}
                                                         arrival OPENS the shop dialog
  74{0x2E1A ShopBuy {ShopID, Slot 16, QTY 16, Backpack 16 (0xFFFF = any)}}  ->
                                                    <-  74{0xE1B ShopBuyResult {ShopID, Result 1 bit}}
  74{0x2E24 ShopSell {ShopID, Backpack 16, QTY 16}}     ->
                                                    <-  74{0xE25 ShopSellResult {ShopID, Result 1 bit}}
```

- `OpenShop` is sent by `DispatchSlotAction` S 00434230 (slot code 11) via S 0046ddf0. The reply's
  `NPCID` must equal the requested id. [known for the wire; inferred for the pairing]
- **Arrival of 0xE11 opens the dialog** (observer `+0x128` → S 004323d0 → ShopDialog show). Never
  push it unprompted: it is not a stock cache. [PROVEN 2026-08-02]
- `Result = 1` means success. [inferred] After a purchase or sale, push the new inventory (0xC1D or
  0xC1E) and stats (0xC81) so the UI shows the new state. [inferred; no client request asks for
  them]
- `act 11` becomes slot code 11 unchanged (S 0047b200) and is dispatched on selection when it is the
  NPC's only action, in slot 0 (§5.2). [known] A live click on 2026-08-02 put nothing on the wire;
  that observation is unexplained [TODO]: statically nothing else gates the send, and a record with
  more than one `act`, or with 11 not in slot 0, would send nothing. [inferred]
- The 0xE11 dispatch looks at the message id only, not the category (S 00470a90). `ShopDialog::SetShop`
  S 0045d580 refuses, silently, only when the dialog is already visible for another NPC or ShopID.
  [known]
- The dialog shows **at most 25 stock entries** (25 slot widgets, first index always 0, no paging,
  S 0045b790). A slot is enabled only when its Buy price ≤ the avatar's gold. An ItemID outside
  `ItemsClient.txt` shows as an empty slot but keeps its stock index. [known]
- **Sell price.** The client computes the price it shows in `!LOBBY_SELL_ITEM_QUESTION`
  (S 0046d800): the Sell value of the open shop's stock entry with the same ItemID if the shop lists
  the item, otherwise the item's base value (§4.3) × SellMod, truncated toward zero, 0 when below 1.
  A price of 0 shows `!LOBBY_TRADER_NOT_WANTS_ITEM` (valid item) or `!LOBBY_CANT_SELL_ITEM` and
  sends nothing. 0x2E24 goes out only after the question is answered Yes; buy and sell both carry
  QTY 1. Closing the dialog sends nothing. [known]

**Stub:** `dispatch._ECONOMY_HANDLERS` routes 0x2E10 / 0x2E1A / 0x2E24 to `economy.handle_open_shop` /
`handle_buy` / `handle_sell`; the wire layouts match. It credits a different sell amount than the
client shows (`mapping/work/protocol_gaps/stub_differences.md`).

### 6.2 Inventory (client-initiated, no dedicated reply)

| Client → server | Fields | Server reply | Tag |
|---|---|---|---|
| 3001 MoveItem `0x2BB9` | `srcslt, srcidx, dstslt, dstidx (0xFF = auto), mvcnt` 8 bits each | validate, then 0xC1D/0xC1E/0xC1C re-sync to the owner (and 0xC1C to others when the equipped items change) | [inferred] |
| 3002 DeleteItemRequest `0x2BBA` | `slt, idx` 8 bits each (from the "drop on world" confirm box) | same | [inferred] |

### 6.3 Trade

This client build can only **receive** trades. It contains no trade sender (outbound village ids
are only 2000, 2001, 2002, 3001, 3002, 3600, 3610, 3620, 3798, 3950, 4000 in category 2, plus
category 5). [known, board #4786]
- 0xF46 TradeRequest only latches `+0x274` when no trade is pending.
- 0xF5A TradeOffer is parsed and discarded.

**A server need not implement trade.**

### 6.4 Minigame tables (Dice, Poker, PawnChess)

Tables are keyed by a **MiniGameKey** `{mngt 8, scntbl 8, chtid, msgprt 16, rnid 8}`. The client
map `+0x178` is keyed by `msgprt | rnid << 16`. [known, S 00471160]

```
client                                                   server
  74{0x27D1 2001 CreateMiniGameTable {type, plyMny, stck, gmnm, lmtmn, lmtmx(=0x7fffffff),
         mxplyr, tvrn, tblidx, psswd, psswdcrc}}  ->
                                                    <-  74{0xDA TableCreate {key, table state}}   to everyone in the village
                                                     or 74{0xDB NoTableLeft} / 74{0xDC NoPlayerSlotLeft}
  74{0x50D1 JoinTable {msgprt, rnid, stck, psswdcrc}}  ->
                                                    <-  74{0xD9 TableUpdate {key, state with seats}}
  74{0x50DE Amount {msgprt, rnid, amnt}}               ->   (stake / buy-in)
  game actions (cat 5): Dice 0xDC/0xDD, Poker 0x12C-0x12E, PawnChess 0x190-0x193  ->
                                                    <-  0xD9 updates; Poker 0x12F hand {crd0, crd1, hndval}
  74{0x50CC LeaveTable {msgprt, rnid}}                 ->
                                                    <-  0xD9 (seat freed) / 0xD8 TableRemove {key}
```

The message ids, fields and senders are [known] (board #615, #713, #1032, S 0046cf20, S 00471720,
S 00471660, S 00471800). The request/reply pairing is [inferred]. 0xDB/0xDC as refusals:
[inferred] from their handlers, which only notify (S 0046f4d0 / S 0046f4f0).

Client-side state and gates the server must respect:

| Rule | Consequence if broken | Tag |
|---|---|---|
| `mngt` low nibble ∈ {1 Dice, 2 Poker, 3 PawnChess} in 0xDA | NULL dereference, **client crash** (S 0046eb70) | [known] |
| `mngt` high nibble bits 4–7 = which blocks follow (settings, currency flag, seats, game state) | wrong blocks → parse failure | [inferred] |
| seat block: `plyrcnt` ≤ 8; only `used = 1` entries; `sltidx` 0–7; avatar occupants must already be spawned (1001) | stack corruption or out-of-bounds write; the whole seat block is rejected | [known, S 00471f00] |
| 0xDA for an existing key | old proxy leaks; send 0xD9 instead | [known] |
| password tables carry the client's password CRC (`proxy+0x21c`) | join refused locally, nothing sent | [inferred] |
| join gate: free seat, enough credits (`avatar+0xd0`) or play money (`+0xd4`) ≥ `lmtmn`, matching tavern (`scntbl`) | Join button stays disabled | [inferred, S 00445cf0] |
| PawnChess: every request must be answered by a state update that changes the move counter (`+0x2a8`) | board stays locked silently | [inferred] |
| Dice: client ignores local bets while `phase == 1`; it computes payouts itself in phase 3 | — | [inferred] |
| spectating joins the UC chat cell given in the key's `chtid` | no spectator chat if 0 | [inferred] |

**Stub:** logs 2001 and the category-5 actions, and sends no table messages.

### 6.5 In-world chat command

`4000 ChatCommand {cmd str}` is sent for `/ac <text>`. All other chat goes through the UC
connection (NETMSG 2 on the cell taken from the §3.2 channel map; whispers as NETMSG 30). [inferred,
S 00436860]

---

## 7. Leaving the village

```
client                                               server
 [9] Leave confirmed (or match start)
     SendLeaveVillageRequest: SetState(10 LeavingVillage) BEFORE sending
  74{0x27D2 2002 {code = 0xAFFEDEAD}}   (sent exactly once)  ->
                                                     <-  74{1006 WorldLoginAck {code = 0xDEADBEEF}}   phase 1
     HandleWorldLoginAck: UC open -> UserCommConnection::Logout
     (UC socket closes)
                                                     <-  74{1006 {0xDEADBEEF}}   phase 2, sent when the UC socket is gone
     UC closed -> village transport Logout -> transport state 9
     disconnect in state 9 -> OnLoggedOut -> HandleLoggedOut -> SetState(11 VillageLeft)
     -> village +0x1c observer (at match start: arms the referee login)
```

[PROVEN 2026-07-26/27: the two-phase leave is the stub's live behaviour and completes the
match-start chain; S 0046ec50, S 0046bde0]

- 2002 is sent **only when the village transport is logged in** (state 8). The client never repeats
  it and has no timeout: state 10 has exactly two exits (LoggedOut, Disconnected).
- `HandleWorldLoginAck` acts **only** on `code == 0xDEADBEEF`. The code is a big-endian u32. A
  little-endian value (`ef be ad de`) is ignored silently. [PROVEN 2026-07-26]
- **Do not close the socket** to answer 2002. A disconnect while the transport is in state 8
  becomes ConnectionLost with reason 10 and the `!CONNECTION_LOST_TEXT` box; at match start both
  players are kicked. [PROVEN 2026-07-26 (falsified approach)]
- **Do not send 1006 unprompted.** With UC in state 8 it logs the player out of the world.
  [PROVEN 2026-07-26]
- A 1006 that arrives at world entry, before UC reaches state 8, is harmless. [PROVEN 2026-07-26,
  trace]
- When the village socket goes away, send 1003 for that player to everyone else in the world (§4.1).

---

## 8. Server decision summary

| Decision | Value / range | Section |
|---|---|---|
| Character list | N × 60 then 42 with the same ticket; N ≤ 8; N = 0 allowed | 2.1 |
| New character id | non-zero, unique; 153 `id` | 2.2 |
| Character name | 1–16 bytes UTF-8, unique; reject empty | 2.2 |
| Every character request | exactly one completion, in order | 2 |
| Village list entry | `server_type 4`, `data = BE u32 protocol + 0x00`, `server_id ≠ 1` | 2.3 |
| Village 153 | `errorcode 0`, `id` = the lobby perm id | 2.3 |
| EnterWorld | unprompted, after 153; `ServerPerm` ≠ any player id; channel cells non-zero, key 0xFF present | 3.2 |
| Pong | echo within 30 s | 3.4 |
| Clock | 1005 before waypoints; high dword 0 | 4.2 |
| Location relay | server-clock stamp `now − 1000`; zone/ghstzne verbatim; ~1 Hz refresh | 4.2 |
| Own avatar | a 1001 for the own id is not needed and is safe on the wire; its Location values are dropped | 4.1 |
| NPC record | `actcnt ≤ 3`, one action (slot 0) for it to run; `npctyp` 1 or 2; ids disjoint from players | 5.1 |
| Shop | 0xE11 only as the reply to 0x2E10; at most 25 stock entries; item ids 1..36 | 6.1 |
| Minigame | `mngt` low nibble 1–3; seats ≤ 8, used = 1 | 6.4 |
| Leave | 1006 on 2002, second 1006 when the UC socket closes; never close the socket | 7 |

---

## 9. Open questions

1. Which id reaches the server in the village 213 token when `char_id ≠ perm_id`, and what the
   village login expects there (§2.3).
2. Why a live click on an `act = 11` NPC sent nothing on 2026-08-02 (§6.1); whether an action button
   can fire for an NPC with more than one action (§5.2).
3. The index of the stats, active-items and inventory blocks inside the 6-part character blob
   (§1.4).
4. Tribe value range: the select icons use 0–2, the model path clamps to 1–5 (§2.2, §4.3).
5. What a 1001 for the own id does to the locally controlled avatar beyond style, items and stats
   (§4.1).
6. Whether a re-sent 1004 moves the visible NPC (§5.1); why the matchmaker NPC does nothing (§5.2).
   (The `npcidx` → model table is settled, §5.)
7. The minigame request/reply pairing and the exact table-state layouts per game, beyond the board
   facts (§6.4).
8. Any timeout in EnteringVillage (8) or LeavingVillage (10).
