# In-world presence — the world-connection entity/player protocol

**Status 2026-07-29.** Spec derived statically from `sadk_noav.exe`. `EntityCreate(1001)` spawn +
`EntityRemove(1003)` despawn are **IMPLEMENTED and deployed** (`village.entity_create_body` /
`entity_remove_body`, `dispatch._spawn_world_avatars`, tests in `tests/test_world_presence.py`) but
**NOT YET CONFIRMED ON THE WIRE** — nothing here has been seen working live. The block-level survey
(AvatarStyle / ActiveItems / Stats / Inventory, and the `0xC1x`/`0xC8x` re-sync family) was added
2026-07-28 and is **not** implemented.

This is the map for making the 3D lobby world non-empty: other players visible, NPCs spawned,
avatars moving, and — see the chat section — possibly what is blocking in-world chat text too.

## Two separate presence systems, not one

> Supersedes the first draft's "one implementation covers both".

`EntityCreate(1001)`/`EntityUpdate(1002)` and `PlayerCreate(1004)` parse completely different,
separately-implemented structures. `EntityCreate` reads an **`AvatarProxy`** (source file
`LobbyAvatarProxy.cpp`, confirmed via embedded log strings) — a player profile: name, tribe/gender,
hair/skin/shirt/trouser colours, level/experience/gold, equipped items, inventory. `PlayerCreate`
reads an NPC-shaped structure (`FUN_0047b5c0`). The two readers share no code and write into two
different containers on `VillageServerConnection` (`+0x170` for `AvatarProxy`, `+0x174` for
`PlayerCreate` entries).

⭐ **`1001 EntityCreate` is the one that puts a VISIBLE body in the world.**
⛔ **`1004 PlayerCreate` is a player RECORD, not a body** — an early revision of this document led
with 1004 and was wrong.
⛔ **`1002 EntityUpdate` is NOT movement.** Movement is still **unfound** — do not reach for 1002
expecting it.

**Reading of the evidence [HYPOTHESIS, well-grounded]:** `1001/1002/1003` + the `AvatarProxy` payload
are how **other human players** appear (RPG-profile fields — gold, level, equipped items — describe a
player account, not scenery). `1004 PlayerCreate`, despite its name, is shaped for **NPCs** (village
folk with idle chat lines `actChat`, an explicit `npctyp`/`npcidx`/`bdyprt`). `msgdefs.ini` does not
cover any of these ids (they ride inside `SendGameData(74)` envelopes, outside the NETMSG schema), so
there is no authoritative name to defer to — the message-id *label* and the *payload shape* disagree,
and the payload shape is the stronger signal.

> **This subsystem REPORTS its parse failures** (unlike the referee, where everything failed
> silently). `Documents/SAdK/dumps/LobbyComm.log` is the cheap oracle:
> `Can't peek AvatarID` · `Can't read AvatarID` · `Can't find Avatar` ·
> `Could not read AvatarLocation from message.` · `Could not read tick from message.` ·
> `Avatar already logged in.` · `Error allocating memory for AvatarProxy`

## The world connection's full inbound API

`LobbyComm::VillageServerConnection::HandleMessage@0x00470a90` is the dispatcher for the village /
world connection (port 5479). Full switch, surveyed end-to-end 2026-07-28:

| msg | id | handler | role | stub status |
|---|---|---|---|---|
| EnterWorld | 1000 `0x3E8` | `HandleEnterWorld@0x0046f670` | world-entry trigger | ✅ implemented |
| **EntityCreate** | **1001 `0x3E9`** | `HandleEntityCreate@0x0046e1d0` | create-or-update an `AvatarProxy` (another player) | ⚠️ implemented, unconfirmed |
| **EntityUpdate** | **1002 `0x3EA`** | `HandleEntityUpdate@0x0046e390` | reserve a bare `AvatarProxy` id — NOT a content update | ❌ |
| **EntityRemove** | **1003 `0x3EB`** | `HandleEntityRemove@0x0046e570` | remove an `AvatarProxy` by id | ⚠️ implemented, unconfirmed |
| **PlayerCreate** | **1004 `0x3EC`** | `HandlePlayerCreate@0x0046f8c0` | spawn an NPC-shaped avatar [HYPOTHESIS: NPCs, not players] | ❌ |
| WorldTick | 1005 `0x3ED` | `HandleWorldTick@0x0046f620` | sim heartbeat | ❌ |
| WorldLoginAck | 1006 `0x3EE` | `HandleWorldLoginAck@0x0046ec50` | logout trigger | ✅ implemented |
| PongCode | 3799 `0xED7` | `HandlePongCode@0x0046c250` | ping/pong keepalive | ✅ implemented |
| AvatarActiveItems update | `0xC1C` | `HandleAvatarActiveItemsUpdate@0x0046e660` | re-sync 4 equip slots, by `ownr` id | ❌ |
| AvatarInventory update | `0xC1D` | `HandleAvatarInventoryUpdate@0x0046e6f0` | re-sync inventory, by `ownr` id | ❌ |
| Avatar items full sync | `0xC1E` | `HandleAvatarItemsFullSync@0x0046e780` | both of the above combined | ❌ |
| Avatar level/exp update | `0xC80` | `HandleAvatarLevelExpUpdate@0x0046c940` | partial stats, by `ownr` id | ❌ |
| Avatar full stats update | `0xC81` | `HandleAvatarStatsUpdate@0x0046c9c0` | full stats, by `ownr` id | ❌ |
| Shop inventory data | `0xE11` | `HandleShopInventoryData@0x004706b0` | NPC vendor stock | ❌ (secondary) |
| Shop result | `0xE1B` / `0xE25` | `FUN_00470990` / `FUN_00470a10` | shop-action acks; buy vs. sell unconfirmed | ❌ (secondary) |
| Trade request | `0xF46` | `HandleTradeRequest@0x0046d920` | incoming player-to-player trade offer | ❌ (secondary) |
| Trade offer detail | `0xF5A` | `HandleTradeOffer@0x0046cd10` | gold/items on both sides of a trade | ❌ (secondary) |
| party/relationship family [HYPOTHESIS] | `0xD8`–`0xDC`, `0x12F` | unrenamed | member join/leave-shaped lifecycle on a `this+0x178` container | ❌ (secondary, low confidence) |

The shop/trade/party rows are **not needed to make other players visible** — documented for
completeness. Per-case evidence and confidence ratings: `docs/SOURCEMAP.md` §5a.

## ⭐ `EntityCreate` (1001) — the avatar spawn (IMPLEMENTED)

`HandleEntityCreate@0x0046e1d0` peeks **`id`** (32 bits) — if that is not the leading big-endian
dword you get `Can't peek AvatarID`. It looks the id up in the avatar container `+0x170`
(`FUN_00471a80`); if unknown it allocates an `AvatarProxy` (0xE0 bytes, `FUN_004818d0`) and inserts
it. It then **always** calls `AvatarProxy_ReadDataBlocks@0x00482c20` to parse the content, registers
the id with the LobbyManager singleton (`LobbyManager_RegisterAvatar@0x004780c0`) and fires
`NotifyQueue_FireAndClear` on `VillageServerConnection+0x1ac` — that is what tells the world/UI to
render it. On error it calls `pVftable->pTickInWorld` (vtbl `+0x28`) instead.

### `AvatarProxy_ReadDataBlocks` — a 4-bit dirty-block mask, then only the selected blocks

| bit | value | block | reader | error string |
|---|---|---|---|---|
| 0 | 1 | AvatarLocation | `FUN_004824b0` | "Could not read AvatarLocation from message." |
| 1 | 2 | AvatarStyle | `FUN_004825f0` | "Could not read AvatarStyle from message." |
| 2 | 4 | ActiveItems | `FUN_0048abe0` | "Could not read ActiveItems from message." |
| 3 | 8 | Avatar Stats | `FUN_00481da0` | "Could not read Avatar Stats from message." |

Any subset may be set — a full spawn presumably sets all four; the dedicated `0xC1x`/`0xC8x`
messages reuse these same block readers to update just one. **We currently send `dtblcks = 1`**
(location only) — the minimal viable avatar.

**AvatarLocation** (`FUN_004824b0`), remote-avatar branch — taken when the avatar's comm-system at
`+0xC` differs from `LobbyManager::GetCommSystem()`, i.e. for everyone who is not the local player.
(The server does not feed a player their own position back.)

```
id 32 │ dtblcks 4 (=1) │ tick 16 │ posx 11 │ posy 11 │ posz 11 │ rot 7 │ zone 4 │ ghstzne 4 │ rnng 1 │ jmp 1
```

= **102 bits / 13 bytes.** `rnng` (running) and `jmp` (jumping) are 1-bit bools via vtbl `+0x28`;
`ghstzne` is 4 bits (`FUN_0048f930`). This is the layout pinned by `tests/test_world_presence.py`.

**AvatarStyle** (`FUN_004825f0`) — *not yet implemented; this is the next block to add:*

| field | width | notes |
|---|---|---|
| `name` | STRING | player display name |
| `trbgndr` | 8 bits | tribe + gender packed into one byte |
| `hrclr` | 8 bits | hair colour (⚠️ full byte, unlike `PlayerCreate`'s 4-bit nibble) |
| `sknclr` | 8 bits | skin colour |
| `shrtclr` | 8 bits | shirt colour |
| `trsrclr` | 8 bits | trouser colour |
| `addColor1..4` | 8 bits each | four extra colour slots (accessory/team?) |

**ActiveItems** (`FUN_0048abe0`): exactly 4 fixed equip slots, each via
`AvatarProxy_ReadItemSlot@0x0048ab40` = `{sltt: 8b slot, cnt: 8b count, itmid: width uncertain —
decompiler noise around the raw vtable call, likely 32b by pattern elsewhere}`.

**AvatarStats** (`FUN_00481da0`): `{lvl: 32b, exp: 32b, gold: 32b, glod: 32b}`. `glod` is verbatim
from the binary's own field-name string — likely a shipped typo for a second currency, not a
transcription error here.

**Inventory** (`FUN_0048ac20`, reached via `0xC1D`/`0xC1E`, *not* one of the 1001 dtblcks blocks):
`{sltcnt: 8b count, then sltcnt × ItemSlot}` — variable length, unlike the fixed 4-slot ActiveItems.

## `EntityRemove` (1003) — despawn (IMPLEMENTED)

`HandleEntityRemove@0x0046e570` reads **only `id`** (32 bits) and releases the handle. The entire
body is one big-endian dword. Errors: `Can't read AvatarID`, `Can't find Avatar`.

## `EntityUpdate` (1002) — reserves an id, reads no payload

Peeks `id`; if already present it logs *"Avatar already logged in."* and bails; otherwise it
allocates a **bare, empty** `AvatarProxy` with **no further fields read**. So 1002 just reserves an
id, while **1001 both creates (if needed) and always populates**. A minimal implementation likely
needs 1001 only.

## `PlayerCreate` (1004) — the NPC-shaped payload

`HandlePlayerCreate` reads `id` (32 bits), looks it up in the **player** container `+0x174`,
allocates a `Player` (0x120 bytes, `FUN_0047b4d0`) if unknown, inserts it, then `FUN_0047b5c0`
parses the rest and `FUN_00464300`/`NotifyQueue_FireAndClear` fires the fan-out.

`FUN_0047b5c0`, in wire order:

| field | width | notes |
|---|---|---|
| `npcdesc` | STRING | avatar descriptor; read via reader vtbl `+0x34` |
| `posx` / `posy` / `posz` | 11 bits each | dequantised into world bounds (below) |
| `rot` | 7 bits | orientation |
| `zone` | 4 bits | |
| `hrclr` / `sknclr` / `shrtclr` / `trsrclr` | 4 bits each | ⚠️ nibble-width here vs. full-byte in `AvatarStyle` — further evidence these are different formats for different kinds of entity |
| `npcidx` | 4 bits | NPC index |
| `bdyprt` | 4 bits | body part |
| `npctyp` | 2 bits | NPC type |
| `actcnt` | 8 bits | number of actions that follow |
| … × `actcnt` | | `act` (8 bits) + `actChat` (STRING) — idle/vendor chat lines |

## Position dequantisation (`FUN_0048f670`) — SOLVED, statically

Shared by `PlayerCreate` and the `AvatarProxy` Location block.

```
x = posx/2048 * (150 - -150) + -150        y = posy/2048 * (30 - -10) + -10
z = posz/2048 * (150 - -150) + -150        rot° = rot7 * 360.0 / 128
```

⇒ **world origin at ground level = `posx=1024, posy=512, posz=1024`**; the world is 300 × 40 × 300
centred on the origin.

| constant | address | value |
|---|---|---|
| bounds min x / y / z | `0x87b700` / `04` / `08` | −150.0 / −10.0 / −150.0 |
| bounds max x / y / z | `0x87b70c` / `10` / `14` | +150.0 / +30.0 / +150.0 |
| position scale | `0x7debc8` | **1/2048** (11 bits) |
| rotation range | `0x7debc0` | 360.0 |
| rotation step | `0x7debb8` | **1/128** (7 bits) |

⚠️ The three `0x7deb*` constants are **doubles** (`FLD double ptr`), not floats. Reading them as
4-byte floats yields `0.0`, which silently collapses every position into the min corner — that
mistake was made once already. The bounds at `0x87b7**` *are* 4-byte floats. These values are
resolved; they do **not** need a live read.

## ⚠️ Bit-packed stream — and one OPEN CONTRADICTION about field names

Every message on this page is **bit-packed, MSB-first** (`FUN_0048f0d0` consumes each byte MSB-first
and assembles values MSB-first ⇒ a 32-bit field is exactly 4 big-endian bytes, the same convention as
the referee `PermID`). Field widths are not byte-aligned (11/7/4/2/1 bits all appear), so the writer
must be a real bit-stream, and strings (`FUN_0048ffc0` = 8-bit length + 8-bit chars) are embedded
mid-stream, not byte-aligned. That much is agreed.

The **names flag** is `*(LobbyMessage+0x20)`, set by `LobbyMessage_InitFromWire@0x0048fa50` from
**bit 15 of the type word**: `typeWord = names<<15 | category<<12 | id`. Two sessions drew opposite
conclusions from it and **this is not yet settled**:

- **`names = 0` (what the deployed stub sends).** `FUN_0048f5f0(msg, nbits, name)` is
  `SelectField(name)` **then** `ReadBits(nbits)`, and the name lookup is *conditional on the flag*.
  With the flag clear the name is skipped and N bits are read positionally, so widths alone suffice.
  Derivation recorded at `sadk_lobby/village.py:127`.
- **`names = 1` (asserted by the 2026-07-28 survey).** Same mechanism described, opposite
  conclusion drawn.

⚠️ The `names = 1` claim traces back to an early draft of *this file* that predates the reading of
`FUN_0048f5f0`, and was carried forward rather than re-derived — so it is the older and less-examined
side, not independent corroboration. **[TODO]** re-derive from the binary. Cheap arbiter: the
deployed code already sends `names = 0`, so the first live test settles it at no extra cost — a
`Can't peek AvatarID` in the log points straight at this.

## Does this also explain the dead chat input?

In-world chat channels/roster/join work, but **typing produces zero wire traffic and no local echo** —
the client's submit handler for the `ChatInput` widget never runs (a submit would call
`AppendLine@0x004ae200` before any network I/O). Established live; not a server gap. A static attempt
to explain it did not reach a definitive answer but produced a concrete, testable [HYPOTHESIS]:

- The chat UI is a real RTTI-named class (`nUi::ChatSystem`; `ChatInput`/`ChatOutput`/`ChatButton`/
  `ChatScrollbar`/`ChatMinimize`/`ChatMaximize` widget-binding keys at `~0x7dfd6e-0x7dfdf8`), but its
  methods are not yet namespaced in the project — only its layout method (`FUN_004ad150`) was
  reached, not OnSubmit/OnChar.
- `LobbyMenu_WorldScreen_OnShow` instantiates ~a dozen sub-controllers when the world is shown.
  Exactly **one** is constructed with the `VillageServerConnection*` passed in directly
  (`FUN_0042b7b0`, a ~0xC58-byte object via `FUN_00445ac0`) — one specific controller is wired
  straight to the entity/avatar pipeline documented above, unlike the others.
- **Hypothesis:** in-world chat may gate input on the local player having a real `AvatarProxy`
  registered in the world ("you must exist to speak" is common in this class of engine). If so, chat
  and player-visibility share a root cause, and `EntityCreate(1001)` would plausibly unblock chat
  submission as a side effect.

Not proven — but **falsifiable and cheap**: retest chat typing the moment an avatar is confirmed
present, before investing more static-RE time in the `ChatSystem` vtable.

## Progress

- [x] World bounds + quantisation constants — resolved statically, no live read needed.
- [x] `village.BitWriter` — MSB-first bit packer + `write_string` (8-bit len, 8-bit chars).
- [x] `EntityCreate(1001)` spawn with `dtblcks=1`, and `EntityRemove(1003)` despawn.
- [x] Driven from the live player registry: `dispatch._spawn_world_avatars` exchanges avatars on
      world entry; `on_conn_closed` despawns. Placement is a deterministic ring keyed by perm_id
      (`_spawn_spot`) so every observer agrees on where a player stands.
- [x] `tests/test_world_presence.py` pins the bit layout and field offsets.
- [x] Full block-level survey of the `AvatarProxy` payload + the `0xC1x`/`0xC8x` re-sync family.
- [ ] **Live confirmation** — nothing here has been seen working.
- [ ] `names` flag contradiction resolved (see above).
- [ ] AvatarStyle block (`dtblcks |= 2`) — layout is known, writer is not written.
- [ ] Movement (`1002` is not it; the real update path is unfound).
- [ ] NPCs via `PlayerCreate(1004)` — a separate, lower-priority track. Do not conflate with player
      visibility.

## ⭐ How to read the first live test — this subsystem LOGS its failures

Two clients into the lobby world, look around, then read `Documents/SAdK/dumps/LobbyComm.log`:

| observation | meaning | next move |
|---|---|---|
| avatars on a ring around the town square | 🎉 | retest chat typing, then movement, then NPCs |
| `Can't peek AvatarID` | leading 32-bit id wrong/not first — **suspect the `names` flag first** | resolve names=0 vs 1 |
| `Could not read AvatarLocation from message.` | location block malformed | re-check widths |
| `Could not read tick from message.` | `tick` is not the first 16 bits of the block | |
| **no error, no avatar** | it PARSED, nothing rendered | add AvatarStyle (`dtblcks \|= 2`) — **do not** re-check the location block |

That last row is the point: unlike the referee, silence here is *informative*, because this subsystem
logs when it is wrong. NPCs are deliberately NOT implemented yet — they will likely need AvatarStyle
too, and stacking a second unproven block on an unproven spawn makes a failure impossible to
attribute.

⚠️ Every failure mode in the referee subsystem was silent, and the *render* half of this one has the
same shape (an observer fan-out that simply does not fire). If the log is silent, prefer
`ttd_calls 0x0046e1d0` (did `HandleEntityCreate` run?) and `ttd_calls` on `NotifyQueue_FireAndClear`
over guessing from the absence of an avatar on screen.

## Related

- `sadk_lobby/village.py` — `BitWriter`, `entity_create_body`, `entity_remove_body`, and where
  `EnterWorld(1000)` is built.
- `sadk_lobby/dispatch.py` — `_spawn_world_avatars`, `_spawn_spot`, despawn in `on_conn_closed`.
- The `EnterWorld` `ChatChannelID`/`ChatChannelZone`/`ChatChannelsCount` fields are **not** the
  source of the in-world chat tabs (refuted 2026-07-27 — the tabs are hardcoded in
  `FUN_004389d0`/`LobbyMenu_WorldScreen_OnShow`). Do not conflate the two.
- `docs/SOURCEMAP.md` §5a — full address table + confidence ratings for every case surveyed here,
  including the secondary shop/trade/party subsystems.
- `API.md` — flow-level protocol reference; village section + known-gaps table.
- `engagement_records/2026-07-27_in-world-avatar-spawn.md` — the ER for the deployed spawn.
