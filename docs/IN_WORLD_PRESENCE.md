# In-world presence — the world-connection avatar and NPC protocol

Static reference for the village (world) connection of `sadk_noav.exe`: how other players, NPCs and
their state reach the 3D lobby world. Function addresses and field reads are `[known]` (visible in the
handlers); wire layouts and what the stub sends are in [message-catalog.md](message-catalog.md) and
`lobby/sadk_lobby/village.py`.

## Two separate record types

Message 1001 (AvatarData) and message 1004 (NPCData) parse different structures. 1001 fills a
**`LobbyComm::AvatarProxy`** (source file `LobbyAvatarProxy.cpp`, 0xe0 bytes): a player profile with name,
tribe/gender, hair/skin/shirt/trouser colours, level/experience/gold, equipped items and inventory. 1004
fills a **`LobbyComm::NPCProxy`** (0x120 bytes) through `NPCProxy::ReadFromMessage` `0x0047b5c0`: village
folk with idle chat lines (`actChat`) and an explicit `npctyp` / `npcidx` / `bdyprt`. The two readers
share no code and write into two different maps: `VillageServerConnection+0x170` (`pAvatarMap`) for
avatars, `+0x174` (`pNpcMap`) for NPCs. Both classes derive from `LobbyComm::ActorProxy` (types.md §1.10).

msgdefs.ini does not cover these ids: they are `LobbyMessage` bit streams of the village connection,
outside the NETMSG schema. Other human players appear through 1001 / 1002 / 1003; NPCs through 1004.

## The world connection's full inbound API

`LobbyComm::VillageServerConnection::HandleMessage@0x00470a90` (`sadk_noav.exe`) is the dispatcher
for the village/world connection (port 5477). The full switch (handlers are methods of
`LobbyComm::VillageServerConnection`):

| msg | id | handler (`sadk_noav.exe`) | role | sent by the stub |
|---|---|---|---|---|
| EnterWorld | 1000 `0x3E8` | `HandleEnterWorld@0x0046f670` | world-entry trigger | yes (`village.py`) |
| **AvatarData** | **1001 `0x3E9`** | `HandleAvatarData@0x0046e1d0` | create-or-update an `AvatarProxy` (a player) | yes (`village.py`) |
| **AvatarLoggedIn** | **1002 `0x3EA`** | `HandleAvatarLoggedIn@0x0046e390` | create an empty `AvatarProxy` for a new id (not a content update) | no |
| **AvatarRemove** | **1003 `0x3EB`** | `HandleAvatarRemove@0x0046e570` | queue an `AvatarProxy` for removal by id | yes (`village.py`) |
| **NPCData** | **1004 `0x3EC`** | `HandleNPCData@0x0046f8c0` | create-or-update an `NPCProxy` | yes (`village.py`) |
| WorldTick | 1005 `0x3ED` | `HandleWorldTick@0x0046f620` | world-clock sync (64-bit `tick`) | yes (`village.py`) |
| WorldLoginAck | 1006 `0x3EE` | `HandleWorldLoginAck@0x0046ec50` | logout trigger | yes (`village.py`) |
| PongCode | 3799 `0xED7` | `HandlePongCode@0x0046c250` | ping/pong keepalive | yes |
| AvatarActiveItems update | `0xC1C` (3100) | `HandleAvatarActiveItemsUpdate@0x0046e660` | re-sync an existing avatar's 4 equip slots, by `ownr` id | yes (`village.py`) |
| AvatarInventory update | `0xC1D` (3101) | `HandleAvatarInventoryUpdate@0x0046e6f0` | re-sync inventory, by `ownr` id | see message-catalog.md |
| Avatar items full sync | `0xC1E` (3102) | `HandleAvatarItemsFullSync@0x0046e780` | both of the above combined | see message-catalog.md |
| Avatar level/exp update | `0xC80` (3200) | `HandleAvatarLevelExpUpdate@0x0046c940` | partial stats, by `ownr` id | see message-catalog.md |
| Avatar full stats update | `0xC81` (3201) | `HandleAvatarStatsUpdate@0x0046c9c0` | full stats, by `ownr` id | yes (`village.py`, `minigames.py`) |
| Shop inventory data | `0xE11` (3601) | `HandleShopInventoryData@0x004706b0` | NPC vendor's stock | yes (`village.py`) |
| Shop buy / sell result | `0xE1B` / `0xE25` | `HandleShopBuyResult@0x00470990` / `HandleShopSellResult@0x00470a10` | `ShopID` + 1-bit `Result` | see message-catalog.md |
| Trade request | `0xF46` (3910) | `HandleTradeRequest@0x0046d920` | incoming player-to-player trade offer | see message-catalog.md |
| Trade offer detail | `0xF5A` (3930) | `HandleTradeOffer@0x0046cd10` | gold/items on both sides of a trade | see message-catalog.md |
| Minigame tables | `0xD8` / `0xD9` / `0xDA` / `0xDB` / `0xDC` / `0x12F` | `HandleMiniGameTableRemove@0x0046f510`, `HandleMiniGameTableUpdate@0x0046f380`, `HandleMiniGameTableCreate@0x0046eb70`, `HandleMiniGameNoTableLeft@0x0046f4d0`, `HandleMiniGameNoPlayerSlotLeft@0x0046f4f0`, `HandleMiniGameHand@0x0046d380` | table lifecycle on the map at `this+0x178` (`miniGameTables`) | yes (`minigames.py`) |

Per-case roles: `docs/SOURCEMAP.md` §5a.

## The `AvatarProxy` payload (1001 / 1002 / 1003)

`HandleAvatarData` (1001) reads `id` (32 bits, peeked), looks it up in the avatar map at
`VillageServerConnection+0x170` (`Stl_Map_TryGetValue_N18` `0x00471a80`); if unknown, allocates an
`AvatarProxy` (0xE0 bytes, `AvatarProxy::ctor` `0x004818d0`) and inserts it; then always calls
`AvatarProxy::ReadDataBlocks@0x00482c20` to parse the content, caches the id ↔ name pair in the
CharacterManager (`CharacterManager::CacheUserName@0x004780c0`), pushes the proxy on the avatar-data
deque (`avatarDataQueue`, `+0x1ac`) and runs `TickInWorld` (vtbl slot `+0x28`) at once, so that
`DrainEventQueues` `0x0046fde0` hands the proxy to the avatar-data observers (`+0xbc`,
`CLobbyClient::UpdateAvatar`) immediately when in-world.

`HandleAvatarLoggedIn` (1002) is not a content update: it peeks `id`, and if that id is already
present it logs `"Avatar already logged in."` and returns. Otherwise it allocates an empty
`AvatarProxy` with no further fields read and queues it (`avatarLoggedInQueue`, `+0x184`) for the
logged-in observers (`+0xa4`); the only subscriber of that list is an empty function. 1001 is what
both creates (if needed) and always fills the avatar's content, gated by the block mask.

`HandleAvatarRemove` (1003) reads `id`, finds the proxy in the same map and queues it on
`avatarRemovedQueue` (`+0x198`) for the avatar-removed observers (`+0xb0`). The proxy itself stays in
the avatar map; the observer removes its 3D object, and the proxies are deleted on world exit.

### `AvatarProxy::ReadDataBlocks` (1001's body) — block bitmask + 4 sub-blocks

```
4 bits   dtblcks     dirty-block mask: bit0=Location bit1=Style bit2=ActiveItems bit3=Stats
if bit0: AvatarLocation block
if bit1: AvatarStyle block
if bit2: ActiveItems block
if bit3: AvatarStats block
         (end of read: LobbyMessage::FinishRead 0x0048f530)
```

Any subset of the 4 bits may be set; the dedicated 0xC1x/0xC8x messages reuse the same block
readers and update just one block.

**AvatarLocation block** (`AvatarProxy::ReadLocationBlock@0x004824b0`):

| field | width | notes |
|---|---|---|
| `tick` | 16 bits | server tick this position is valid at |
| position | quantised, same dequantiser as NPCData (`LobbyMessage::ReadLocationBlock` `0x0048f670`) | for the local player's own avatar (actor id == own perm id) the location fields are read and discarded, so the server echo does not overwrite the client-side position |
| `rnng` | 1 bit | running flag |
| `jmp` | 1 bit | jump flag |

**AvatarStyle block** (`AvatarProxy::ReadStyleBlock@0x004825f0`):

| field | width | notes |
|---|---|---|
| `name` | STRING | player display name |
| `trbgndr` | 8 bits | tribe + gender packed into one byte |
| `hrclr` | 8 bits | hair colour (a full byte here, unlike the 4-bit nibble of NPCData) |
| `sknclr` | 8 bits | skin colour |
| `shrtclr` | 8 bits | shirt colour |
| `trsrclr` | 8 bits | trouser colour |
| `addColor1..4` | 8 bits each | four extra colour slots (accessory/team?) |

**ActiveItems block** (`ai::village::AvatarItemContainer::ReadActiveItemsBlock@0x0048abe0`): exactly 4
fixed equip slots, each via `AvatarProxy_ReadItemSlot@0x0048ab40` = `{sltt: 8b slot type, cnt: 8b count,
itmid: 32b item id}`, read into a `TradeItemSlot`.

**AvatarStats block** (`AvatarProxy::ReadStatsBlock@0x00481da0`): `{lvl: 32b, exp: 32b, gold: 32b,
glod: 32b}`. `glod` is verbatim from the binary's own field-name string — likely a shipped typo for
a second currency, not a transcription error here.

**Inventory** (`ai::village::AvatarItemContainer::ReadInventoryBlock@0x0048ac20`, reached via the 0xC1D/0xC1E messages,
*not* part of the 1001 dtblcks blocks): `{sltcnt: 8b count, then sltcnt × ItemSlot}` — variable
length, unlike the fixed 4-slot ActiveItems.

The `LobbyComm::IAvatarDataBlock` family (`AvatarCreationBlockEx`, `AvatarAppearanceBlockEx`,
`AvatarStyleBlockEx`, `AvatarStatsBlockEx`, `AvatarInventoryBlockEx`, `AvatarActiveItemsBlockEx`) is a
separate serialisation path over an `NComm::MemoryStream`, not these `LobbyMessage` readers; see
`docs/SOURCEMAP.md` §5a.

## NPCData (1004) — the `NPCProxy` payload

`HandleNPCData` reads **`id`** (32 bits), looks it up in the **NPC** map at
`VillageServerConnection+0x174` (separate from the avatar map above), allocates an `NPCProxy`
(0x120 bytes, `NPCProxy::ctor` `0x0047b4d0`) if unknown, inserts it, then `NPCProxy::ReadFromMessage`
`0x0047b5c0` parses the rest and `ObserverList_NotifyAll` `0x00464300` fires the NPC-added observers
(`+0x38`, subscriber `CLobbyClient::OnNPCAdded`) at once, not through a queue.

`NPCProxy::ReadFromMessage`, in wire order:

| field | width | notes |
|---|---|---|
| `npcdesc` | STRING | avatar descriptor; read via reader vtbl `+0x34` |
| `posx` / `posy` / `posz` | 11 bits each | dequantised into world bounds (see below) |
| `rot` | 7 bits | orientation |
| `zone` | 4 bits | |
| `hrclr` / `sknclr` / `shrtclr` / `trsrclr` | 4 bits each | nibble width here, a full byte in `AvatarStyle` above |
| `npcidx` | 4 bits | NPC index |
| `bdyprt` | 4 bits | body part |
| `npctyp` | 2 bits | NPC type |
| `actcnt` | 8 bits | number of actions that follow |
| … × `actcnt` | | `act` (8 bits) + `actChat` (STRING) — idle/vendor chat lines |

### Position dequantisation (`LobbyMessage::ReadLocationBlock` `0x0048f670`, shared by NPCData and the `AvatarProxy` Location block)
```
x = posx * (BOUND_MAX_X - BOUND_MIN_X) * SCALE + BOUND_MIN_X     ; DAT_0087b70c / DAT_0087b700
y = posy * (BOUND_MAX_Y - BOUND_MIN_Y) * SCALE + BOUND_MIN_Y     ; DAT_0087b710 / DAT_0087b704
z = posz * (BOUND_MAX_Z - BOUND_MIN_Z) * SCALE + BOUND_MIN_Z     ; DAT_0087b714 / DAT_0087b708
rot = rot * DAT_007debc0 * DAT_007debb8
```
`SCALE` = `DAT_007debc8` (a 1/2047-style normaliser). The bound globals are runtime values.

## A bit-packed stream with named fields

This applies to **every** message documented on this page (1001-1004 and the 0xC1x/0xC8x family).
`LobbyMessage::ReadNamedBits` `0x0048f5f0` `(msg, nbits, name)` selects the field by name and then reads
`nbits` bits; the individual `AvatarProxy` block readers select the field and then call a
width-specific vtable read, which is the same named-lookup mechanism. The name lookup only happens when
the LobbyMessage's **names flag is set**: `namesMode` (`LobbyMessage+0x20`), set by
`LobbyMessage::InitFromWire@0x0048fa50` from **bit 15 of the type word**:

```
typeWord = names<<15 | category<<12 | id
```

With `names = 1` the type word is `0x8000 | (cat<<12) | id`. Field widths are not byte-aligned
(11/7/4/2/1 bits all appear), so the stream is a real bit stream with strings embedded mid-stream; the
stub's writer is in `lobby/sadk_lobby/village.py`.

## Chat UI and the world screen

- The chat UI is the RTTI class `nUi::ChatSystem` (widget-binding keys `ChatInput` / `ChatOutput` /
  `ChatButton` / `ChatScrollbar` / `ChatMinimize` / `ChatMaximize` at `~0x7dfd6e-0x7dfdf8`). Its methods
  are in the namespace `nUi::ChatSystem`; `LoadFromXml` is `0x004ad150`.
- `LobbyMenu::WorldScreen::OnShow` `0x004389d0` creates the cached dialogs when the world is shown. One of
  them is constructed with the `VillageServerConnection*`: the `LobbyMenu::MiniGameMatchMakingDialog`
  (`MiniGameMatchMakingDialog::ctor` `0x00445ac0`, opened by `LobbyMenu::System::OpenMiniGameMatchMakingDialog`
  `0x0042b7b0`).
- The in-world chat tabs are hard-coded in `WorldScreen::OnShow`; the `EnterWorld` fields
  `ChatChannelID` / `ChatChannelZone` / `ChatChannelsCount` fill the zone-to-channel map
  (`zoneChatChannels`, `VillageServerConnection+0x164`), not the tabs.

## Related

- `lobby/sadk_lobby/village.py`, `lobby/sadk_lobby/minigames.py`: the stub's senders of the messages above.
- `docs/SOURCEMAP.md` §5a: address table of every switch case.
- `docs/message-catalog.md`: wire layouts and status per message.
