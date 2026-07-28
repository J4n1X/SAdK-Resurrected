# In-world presence — the world-connection entity/player protocol

**Status: SPEC DERIVED (static, `sadk_noav.exe`), extended 2026-07-28. NOT YET IMPLEMENTED —
nothing here has been sent to a live client.** This is the map for making the 3D lobby world
non-empty: other players visible, NPCs spawned, avatars moving, and (see the chat section below)
possibly what's blocking in-world chat text too.

## Two separate presence systems, not one (supersedes the 2026-07-27 draft's "one implementation
covers both")

`EntityCreate(1001)`/`EntityUpdate(1002)` and `PlayerCreate(1004)` parse completely different,
separately-implemented structures. `EntityCreate` reads **`AvatarProxy`** (source file
`LobbyAvatarProxy.cpp`, confirmed via embedded log strings) — a player-profile: name, tribe/gender,
hair/skin/shirt/trouser colours, level/experience/gold, equipped items, inventory. `PlayerCreate`
reads an NPC-shaped structure (`FUN_0047b5c0`). The two readers share no code and write into two
different containers on `VillageServerConnection` (`+0x174` for `PlayerCreate` entries, `+0x170` for
`AvatarProxy` entries).

**Reading of the evidence [HYPOTHESIS, well-grounded]:** `1001/1002/1003 EntityCreate/Update/Remove`
+ the `AvatarProxy` payload are how **other human players** appear in the world (RPG-profile shaped
fields: gold, level, equipped items — that's a player account, not scenery). `1004 PlayerCreate`,
despite its name, is shaped for **NPCs** (village folk with idle chat lines `actChat`, an explicit
`npctyp`/`npcidx`/`bdyprt`). msgdefs.ini does not cover any of these IDs (they ride inside
`SendGameData(74)` envelopes, outside the NETMSG schema), so there is no authoritative name to defer
to — the message-id *label* ("PlayerCreate") and the *payload shape* disagree, and the payload shape
is the stronger signal. **This means: to make other players visible, implement the `AvatarProxy`
path (1001/1002), not `PlayerCreate`.** `PlayerCreate` is still worth implementing for NPCs, but it
is not the blocker for "I want to see the other player."

## The world connection's full inbound API

`LobbyComm::VillageServerConnection::HandleMessage@0x00470a90` (`sadk_noav.exe`) is the dispatcher
for the village/world connection (port 5479). Full switch, surveyed end-to-end 2026-07-28:

| msg | id | handler (`sadk_noav.exe`) | role | stub status |
|---|---|---|---|---|
| EnterWorld | 1000 `0x3E8` | `HandleEnterWorld@0x0046f670` | world-entry trigger | ✅ implemented |
| **EntityCreate** | **1001 `0x3E9`** | `HandleEntityCreate@0x0046e1d0` | create-or-update an `AvatarProxy` (another player) | ❌ |
| **EntityUpdate** | **1002 `0x3EA`** | `HandleEntityUpdate@0x0046e390` | reserve a bare `AvatarProxy` id (see below — NOT a content update) | ❌ |
| **EntityRemove** | **1003 `0x3EB`** | `HandleEntityRemove@0x0046e570` | remove an `AvatarProxy` by id | ❌ |
| **PlayerCreate** | **1004 `0x3EC`** | `HandlePlayerCreate@0x0046f8c0` | spawn an NPC-shaped avatar [HYPOTHESIS: NPCs, not players] | ❌ |
| WorldTick | 1005 `0x3ED` | `HandleWorldTick@0x0046f620` | sim heartbeat | ❌ |
| WorldLoginAck | 1006 `0x3EE` | `HandleWorldLoginAck@0x0046ec50` | logout trigger | ✅ implemented |
| PongCode | 3799 `0xED7` | `HandlePongCode@0x0046c250` | ping/pong keepalive | ✅ implemented |
| AvatarActiveItems update | `0xC1C` | `HandleAvatarActiveItemsUpdate@0x0046e660` | re-sync an existing avatar's 4 equip slots, by `ownr` id | ❌ |
| AvatarInventory update | `0xC1D` | `HandleAvatarInventoryUpdate@0x0046e6f0` | re-sync inventory, by `ownr` id | ❌ |
| Avatar items full sync | `0xC1E` | `HandleAvatarItemsFullSync@0x0046e780` | both of the above combined | ❌ |
| Avatar level/exp update | `0xC80` | `HandleAvatarLevelExpUpdate@0x0046c940` | partial stats, by `ownr` id | ❌ |
| Avatar full stats update | `0xC81` | `HandleAvatarStatsUpdate@0x0046c9c0` | full stats, by `ownr` id | ❌ |
| Shop inventory data | `0xE11` | `HandleShopInventoryData@0x004706b0` | NPC vendor's stock | ❌ (secondary — not needed for presence) |
| Shop result | `0xE1B` / `0xE25` | `FUN_00470990` / `FUN_00470a10` | shop-action acks, unrenamed (buy vs. sell unconfirmed) | ❌ (secondary) |
| Trade request | `0xF46` | `HandleTradeRequest@0x0046d920` | incoming player-to-player trade offer | ❌ (secondary) |
| Trade offer detail | `0xF5A` | `HandleTradeOffer@0x0046cd10` | gold/items on both sides of a trade | ❌ (secondary) |
| party/relationship family [HYPOTHESIS] | `0xD8`/`0xD9`/`0xDA`/`0xDB`/`0xDC`/`0x12F` | unrenamed, see `docs/SOURCEMAP.md` §5a | member join/leave-shaped lifecycle on a `this+0x178` container | ❌ (secondary, low confidence) |

The last four rows are **not needed to make other players visible** — they're documented here for
completeness (the user asked for the whole village communication structure to be evaluated) but
should not block the core presence work. Full per-case evidence and confidence ratings:
`docs/SOURCEMAP.md` §5a.

## The `AvatarProxy` payload — the "other players visible" protocol

`HandleEntityCreate` reads `id` (32 bits, peeked), looks it up in the avatar container at
`VillageServerConnection+0x170` via `FUN_00471a80`; if unknown, allocates an `AvatarProxy` (0xE0
bytes, `FUN_004818d0`) and inserts it; then always calls `AvatarProxy_ReadDataBlocks@0x00482c20` to
parse the content, registers the id with the LobbyManager singleton
(`LobbyManager_RegisterAvatar@0x004780c0`), and fires `NotifyQueue_FireAndClear` on
`VillageServerConnection+0x1ac` (tells the world/UI to render it). On error it calls
`this->pVftable->pTickInWorld` (vtbl slot `+0x28`) instead — **not** the same fan-out `PlayerCreate`
uses (`FUN_00464300`/`NotifyQueue_FireAndClear` is shared code, but the two features hook different
per-connection notify slots).

`HandleEntityUpdate` (1002) is **not** a content update despite the name: it peeks `id`, and if that
id is **already present** it logs `"Avatar already logged in."` and bails — it only allocates a
**bare, empty** `AvatarProxy` when the id is unknown, with no further fields read. Reading this
plainly: **1002 just reserves an id**; **1001 is what both creates (if needed) and always
populates/updates** the avatar's content, gated by which blocks are marked dirty. A minimal
implementation likely only needs 1001 — 1002 may not be required at all for a working spawn.

`HandleEntityRemove` (1003) reads `id`, finds it in the same container, and releases the handle. Simple.

### `AvatarProxy_ReadDataBlocks` (1001's body) — dirty-block bitmask + 4 sub-blocks

```
4 bits   dtblcks     dirty-block mask: bit0=Location bit1=Style bit2=ActiveItems bit3=Stats
if bit0: AvatarLocation block
if bit1: AvatarStyle block
if bit2: ActiveItems block
if bit3: AvatarStats block
         (stream finalize — see LobbyMessage_FinishRead below)
```

Any subset of the 4 bits may be set — a full spawn presumably sets all 4; a later re-sync (or the
dedicated 0xC1x/0xC8x messages, which reuse these same block readers) can update just one.

**AvatarLocation block** (`AvatarProxy_ReadLocationBlock@0x004824b0`):

| field | width | notes |
|---|---|---|
| `tick` | 16 bits | server tick this position is valid at |
| position | quantised, same dequantiser as `PlayerCreate` (`FUN_0048f670`) | **only read when this avatar is not the connection's own CommSystem** — i.e. the server does not feed a player's position back to themselves |
| `rnng` | 1 bit | running flag |
| `jmp` | 1 bit | jump flag |

**AvatarStyle block** (`AvatarProxy_ReadStyleBlock@0x004825f0`):

| field | width | notes |
|---|---|---|
| `name` | STRING | player display name |
| `trbgndr` | 8 bits | tribe + gender packed into one byte |
| `hrclr` | 8 bits | hair colour (⚠️ full byte here, unlike `PlayerCreate`'s 4-bit nibble) |
| `sknclr` | 8 bits | skin colour |
| `shrtclr` | 8 bits | shirt colour |
| `trsrclr` | 8 bits | trouser colour |
| `addColor1..4` | 8 bits each | four extra colour slots (accessory/team?) |

**ActiveItems block** (`AvatarProxy_ReadActiveItemsBlock@0x0048abe0`): exactly 4 fixed equip slots,
each via `AvatarProxy_ReadItemSlot@0x0048ab40` = `{sltt: 8b slot, cnt: 8b count, itmid: width
uncertain — decompiler noise around the raw vtable call, likely 32b by pattern elsewhere}`.

**AvatarStats block** (`AvatarProxy_ReadStatsBlock@0x00481da0`): `{lvl: 32b, exp: 32b, gold: 32b,
glod: 32b}`. `glod` is verbatim from the binary's own field-name string — likely a shipped typo for
a second currency, not a transcription error here.

**Inventory** (`AvatarProxy_ReadInventoryBlock@0x0048ac20`, reached via the 0xC1D/0xC1E messages,
*not* part of the 1001 dtblcks blocks): `{sltcnt: 8b count, then sltcnt × ItemSlot}` — variable
length, unlike the fixed 4-slot ActiveItems.

**[TODO — RTTI class hygiene]** The project has empty, RTTI-sourced namespaces for the real engine
class names (`AvatarProxy`, `AvatarCreationBlockEx`, `AvatarAppearanceBlockEx`, `AvatarStyleBlockEx`,
`AvatarStatsBlockEx`, `AvatarInventoryBlockEx`, `AvatarActiveItemsBlockEx`) that were not
cross-checked against the flat `AvatarProxy_ReadXBlock` names above — see `docs/SOURCEMAP.md` §5a.

## `PlayerCreate` (1004) — the NPC-shaped payload

`HandlePlayerCreate` reads **`id`** (32 bits), looks it up in the **player** container at
`VillageServerConnection+0x174` (separate from the avatar container above), allocates a `Player`
(0x120 bytes, `FUN_0047b4d0`) if unknown, inserts it, then `FUN_0047b5c0` parses the rest and
`FUN_00464300`/`NotifyQueue_FireAndClear` fires the fan-out that tells the world/UI about it.

`FUN_0047b5c0`, in wire order:

| field | width | notes |
|---|---|---|
| `npcdesc` | STRING | avatar descriptor; read via reader vtbl `+0x34` |
| `posx` / `posy` / `posz` | 11 bits each | dequantised into world bounds (see below) |
| `rot` | 7 bits | orientation |
| `zone` | 4 bits | |
| `hrclr` / `sknclr` / `shrtclr` / `trsrclr` | 4 bits each | ⚠️ nibble-width here, vs. full-byte in `AvatarStyle` above — further evidence these are different formats for different kinds of entity |
| `npcidx` | 4 bits | NPC index |
| `bdyprt` | 4 bits | body part |
| `npctyp` | 2 bits | NPC type |
| `actcnt` | 8 bits | number of actions that follow |
| … × `actcnt` | | `act` (8 bits) + `actChat` (STRING) — idle/vendor chat lines |

### Position dequantisation (`FUN_0048f670`, shared by `PlayerCreate` and `AvatarProxy` Location)
```
x = posx * (BOUND_MAX_X - BOUND_MIN_X) * SCALE + BOUND_MIN_X     ; DAT_0087b70c / DAT_0087b700
y = posy * (BOUND_MAX_Y - BOUND_MIN_Y) * SCALE + BOUND_MIN_Y     ; DAT_0087b710 / DAT_0087b704
z = posz * (BOUND_MAX_Z - BOUND_MIN_Z) * SCALE + BOUND_MIN_Z     ; DAT_0087b714 / DAT_0087b708
rot = rot * DAT_007debc0 * DAT_007debb8
```
`SCALE` = `DAT_007debc8` (a 1/2047-style normaliser). The bound globals are runtime values — read
them from a live process/TTD trace before computing a real spawn point. A mid-range value
(e.g. 1024) lands near the middle of the world and is fine for a first test.

## ⚠️ This is a BIT-PACKED, NAMED-field stream — unlike everything we send today

This applies to **every** message documented on this page (1001-1004 and the 0xC1x/0xC8x family),
not just `PlayerCreate`. `FUN_0048f5f0(msg, nbits, name)` = `SelectField(name)` **then**
`ReadBits(nbits)`; the individual `AvatarProxy` block readers call `LobbyMessage_SelectField`
directly followed by a width-specific vtable read, which is the same named-lookup mechanism. The
name lookup only happens when the LobbyMessage's **names flag is set** — that flag is
`*(LobbyMessage+0x20)`, set by `LobbyMessage_InitFromWire@0x0048fa50` from **bit 15 of the type
word**:

```
typeWord = names<<15 | category<<12 | id
```

⇒ **every message on this page must be sent with `names = 1`**, i.e. type word `0x8000 | (cat<<12) |
id`. Every message the stub sends today uses `names = 0` (positional). So implementing any of this
needs a **new encoder**: a named + bit-packed LobbyMessage writer. The existing positional
PropertySet/`referee_payload` path will not do.

Note also that field widths are not byte-aligned (11/7/4/2/1 bits all appear), so the writer must be
a real bit-stream, and strings are embedded mid-stream.

## Does this also explain the dead chat input?

`API.md`'s known-gaps table notes that in-world chat channels/roster/join work, but **typing
produces zero wire traffic and no local echo** — i.e. the client's own submit handler for the
`ChatInput` widget never appears to run. That observation is from a live session
(`LobbyComm.log`); this session tried to explain it statically and did **not** reach a definitive
answer, but did find a concrete, testable [HYPOTHESIS]:

- The client's chat UI is a real, RTTI-named class (`nUi::ChatSystem`, string evidence: `ChatInput`/
  `ChatOutput`/`ChatButton`/`ChatScrollbar`/`ChatMinimize`/`ChatMaximize` widget-binding keys at
  `~0x7dfd6e-0x7dfdf8`), but its methods are not yet namespaced in the project (empty namespace,
  vtable not linked) — this session could not reach its OnSubmit/OnChar handler in the time
  available, only its pure layout method (`FUN_004ad150`).
- `LobbyMenu_WorldScreen_OnShow` (the screen that owns the chat tabs) instantiates roughly a dozen
  sub-controllers when the world is shown. Exactly **one** of them is constructed with the
  `VillageServerConnection*` passed in directly (`FUN_0042b7b0`, a ~0xC58-byte object via
  `FUN_00445ac0`) — i.e. one specific controller is wired straight to the entity/avatar message
  pipeline documented above, unlike the others.
- **Hypothesis:** the in-world chat system may gate input on the local player having a real
  `AvatarProxy`/entity registered in the world (the pattern "you must exist to speak" is common in
  this class of engine). If so, chat and player-visibility share a root cause, and implementing
  `EntityCreate(1001)` for the local player (which we need for presence anyway, per
  `HARNESS.md §2`'s "is the game waiting for something earlier?" instinct) would very plausibly also
  unblock chat submission as a side effect.

This is not proven — it is the natural next experiment. **Falsifiable and cheap:** implement 1001 for
one avatar (see order of work below), then retest chat typing before investing more static-RE time in
the `ChatSystem` vtable.

## Suggested order of work

1. Read the world-bound globals (`0x87b700`–`0x87b714`, `0x7debc8`, `0x7debc0`, `0x7debb8`) from a
   live process — one TTD/debugger read, no gameplay needed.
2. Build the named/bit-packed LobbyMessage writer (the reusable piece, shared by every message on
   this page).
3. Send **one** `EntityCreate(1001)` after `EnterWorld(1000)` for the *other* client's own id, with
   `dtblcks` = Location+Style only, a mid-world position and a plausible name — see whether an avatar
   appears. One frame, immediately falsifiable, and directly tests the "other players visible" ask.
4. While that client is present, **retest chat text entry** on both clients — this is the cheap check
   for the chat-gating hypothesis above, before spending more RE time on `nUi::ChatSystem`.
5. If the avatar appears: drive `EntityCreate`/`EntityRemove` from the existing player registry so
   each client sees the others on join/leave, then extend to `EntityUpdate`-family messages
   (0xC1x/0xC8x) for live position/stat sync if needed.
6. `PlayerCreate(1004)` for NPCs is a separate, lower-priority track — do not conflate it with player
   visibility (see the correction at the top of this doc).

⚠️ Every failure mode in the referee subsystem was silent, and this one has the same shape (an
observer fan-out that simply does not fire). Before a live drive, prefer
`ttd_calls 0x0046e1d0` (did `HandleEntityCreate` run?) and `ttd_calls` on
`NotifyQueue_FireAndClear`/`AvatarProxy+0x1ac` over guessing from the absence of an avatar on screen.

## Related

- `sadk_lobby/village.py` — where `EnterWorld(1000)` is built; the new messages belong beside it.
- The `EnterWorld` `ChatChannelID`/`ChatChannelZone`/`ChatChannelsCount` fields are **not** the
  source of the in-world chat tabs (refuted 2026-07-27 — the tabs are hardcoded in
  `FUN_004389d0`/`LobbyMenu_WorldScreen_OnShow`). Do not conflate the two.
- `docs/SOURCEMAP.md` §5a — full address table + confidence ratings for every case surveyed here,
  including the secondary shop/trade/party subsystems.
- `API.md` (repo root) — flow-level protocol reference; village section + known-gaps table updated
  alongside this doc.
