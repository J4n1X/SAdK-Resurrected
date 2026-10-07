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
[PROVEN] means the working stub (`sadk_lobby/`) shows it live against the real client. A
[PROVEN] claim carries a binary address and the date of the live evidence. [TODO] marks an open
question.

**Addresses.** `S 00xxxxxx` is in `sadk_noav.exe`; `T 10xxxxxx` is in `tincat3.dll`. Struct
offsets such as `LM+0x57c` are relative to the named object.

---

## 1. Objects and state the flows depend on

### 1.1 Who holds what

| Object | Where | Holds | Tag |
|---|---|---|---|
| `LobbyManager` (LM) | singleton | state `+0x57c`; local avatar id `+0x54c`; local `AvatarProxy*` `+0x554`; village conn `+0x540`; UC conn `+0x3d8` | [known] |
| `LobbyComm::CharacterManager` | embedded at `LM+0x140` (ctor S 00478f80) | character map `+0x8c` (id → AvatarProxy, 0xE0 each); list-valid flag `+0x88`; selected id `+0x98`; working/preview avatar `+0xa0`; action queue `+0x74`; buddy/ignore maps `+0x184`/`+0x194`; name↔id caches `+0x1a0`/`+0x1ac` | [known] |
| tincat3 `CommLayer::CharacterManager` | `CharacterManager+0x5c` | sends 72/86/77/90/94; per-request busy flags `+0xc/+0x10/+0x14/+0x18` | [known] |
| tincat3 `CommLayer::UserManager` | `CharacterManager+0x60` | sends 55/88/56/157/…; collects 60 rows at `+0xd0` | [known] |
| `LobbyComm::VillageServerConnection` | `LM+0x540` | transport `+0x34`; server perm `+0x160`; chat map `+0x164` (zone byte → cell id); avatar map `+0x170`; NPC map `+0x174`; minigame tables `+0x178`; event queues `+0x184/+0x198/+0x1ac`; current chat zone `+0x225`; world name `+0x228`; link quality `+0x244`; pending ping `+0x248`; trade latch `+0x274` | [known] |
| `LobbyMenu::AvatarScreen` | screen | view mode `+0x1e8` (0 create, 1 select, 2 entering); wait dialog `+0x200` | [inferred] |

### 1.2 LobbyManager states (`LM+0x57c`)

| Value | Name | Entered by | Left by |
|---|---|---|---|
| 1 | Disconnected | init, login failed, logged out | lobby login |
| 2 | Connecting | lobby login | 207 SessionKey |
| 3 | Authorized | OnLoggedIn | state pump |
| 4–5 | version check | state pump | 42 for 188 |
| 6 | LoadingGlobalData | state pump | all four global lists valid (§2.1) |
| 7 | GlobalDataLoaded | state pump | character selected, Enter clicked |
| 8 | EnteringVillage | `OnUserCommLoggedIn` S 004704e0 | **server-pushed** EnterWorld 1000 |
| 9 | VillageEntered | `HandleEnterWorld` S 0046f670 | msg 2002 sent |
| 10 | LeavingVillage | `SendLeaveVillageRequest` S 0046bde0 | only LoggedOut (→11) or Disconnected (→11) |
| 11 | VillageLeft | `HandleLoggedOut` / `HandleDisconnected` | — |
| 12 | LobbyConnectionLost | main connection lost | — |

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
| 2–5 | Stats, active items and inventory blocks (`AvatarStatsBlockEx`, `AvatarActiveItemsBlockEx`, `AvatarInventoryBlockEx`) | [inferred] exact part index per block [TODO] |

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
| channel keys `0x00..0x0D` | optional, one per zone | local tab. On a zone change `SetLocalChatZone` S 0046e860 leaves the old cell and joins `map[zone]` | [inferred] |
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
  (`ReadLocationBlock` S 004824b0 skips the own-avatar branch). Do not send a player their own id.
  Whether the skipped bits are still consumed is [TODO], so a Location block for the own id could
  desynchronize the rest of the body. [inferred]
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

`itmid` values are game-data item ids from the encrypted item tables. They cannot be derived from
the binary. [TODO]

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
| `act` | LobbyAction id (below) | sets one of the 3 village-screen action buttons | [PROVEN 2026-08-02, S 004325b0] |
| `actChat` | UTF-8 string | button label or spoken line: [TODO] | — |

LobbyAction table (S 004325b0):

| `act` | Action |
|---|---|
| 0, 19, other | None (button hidden) |
| 1 | HairColor (tailor) |
| 2–6 | MinigameMatchmaking |
| 7 | Mailbox |
| 8, 18 | HostGame |
| 9 | ListGames |
| 10 | Hall of Fame |
| 11 | OpenShop |

- No message for **removing** an NPC record has been identified. [TODO]
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
  | 10 | egypt_male_5 | Egyptian original character; idle animation sits, model turned 270° |
  | 11 | egypt_soldier2_mesh | Egyptian generic (easy computer opponent) |
  | 12 | egypt_soldier3_mesh | Egyptian generic (hard computer opponent) |
  | 13 | scot_soldier1_mesh | Scottish generic (easy) |
  | 14 | scot_soldier2_mesh | Scottish generic (medium) |
  | 15 | scot_soldier3_mesh | Scottish generic (hard) |

  The colour palette per model is still [TODO].

**Stub:** NPC spawning is implemented but currently switched off (`config.VILLAGE_NPCS_ENABLED =
False`, at the maintainer's request) until the appearance and `actChat` questions are settled.

### 5.2 NPC interaction

Clicking an NPC fills the three action buttons from its `act` list. Each button runs a local
LobbyAction (matchmaking dialog, host/list games, hall of fame, mailbox, tailor). Only **OpenShop**
is known to put a village message on the wire (§6.1). [inferred]

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
- [TODO] In live tests, clicking an NPC with `act = 11` put nothing on the wire. Open question:
  whether `act 11` becomes slot code 11 (set by `RefreshActionSlots` S 00433f60, not by
  `SetActionButton` S 004325b0, which only labels the button).

**Stub:** has `village.send_shop_inventory`, but no handler for 0x2E10/0x2E1A/0x2E24 (they are
logged and dropped).

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
| Own avatar | never send a player their own id | 4.1 |
| NPC record | `actcnt ≤ 3`; `npctyp` 1 or 2; ids disjoint from players | 5.1 |
| Shop | 0xE11 only as the reply to 0x2E10 | 6.1 |
| Minigame | `mngt` low nibble 1–3; seats ≤ 8, used = 1 | 6.4 |
| Leave | 1006 on 2002, second 1006 when the UC socket closes; never close the socket | 7 |

---

## 9. Open questions

1. Which id reaches the server in the village 213 token when `char_id ≠ perm_id`, and what the
   village login expects there (§2.3).
2. Whether `act = 11` reaches `OpenShop` (`RefreshActionSlots` S 00433f60). Live clicks sent
   nothing (§6.1).
3. The index of the stats, active-items and inventory blocks inside the 6-part character blob
   (§1.4).
4. Tribe value range: the select icons use 0–2, the model path clamps to 1–5 (§2.2, §4.3).
5. Whether the own-avatar Location block's bits are consumed or skipped (§4.1).
6. Meaning of `actChat` (button label or spoken line); NPC removal (§5). (The `npcidx` → model table is settled, §5.)
7. The minigame request/reply pairing and the exact table-state layouts per game, beyond the board
   facts (§6.4).
8. Any timeout in EnteringVillage (8) or LeavingVillage (10).
