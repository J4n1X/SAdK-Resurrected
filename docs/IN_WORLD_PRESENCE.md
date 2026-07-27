# In-world presence — the world-connection entity/player protocol

**Status 2026-07-27: spec derived statically from `sadk_noav.exe`; spawn + despawn IMPLEMENTED and
deployed (`village.entity_create_body` / `entity_remove_body`, `dispatch._spawn_world_avatars`),
but NOT YET CONFIRMED ON THE WIRE.** This is the map for making the 3D lobby world non-empty:
other players visible, NPCs spawned, avatars moving.

> ## ⭐ Read this first — which message actually spawns a body
> **`1001 EntityCreate` is the one.** It allocates an **AvatarProxy** into the *avatar* container at
> `VillageServerConnection+0x170`, registers it with the LobbyManager and ticks the world.
> `1004 PlayerCreate` fills a **separate *player* map at `+0x174`** — a player record, not a visible
> body. Easy to conflate; an earlier revision of this document led with 1004 and was wrong.
>
> **`1002 EntityUpdate` is NOT movement.** It peeks `id`, bails with *"Avatar already logged in."*
> if the avatar exists, and otherwise allocates a **bare** AvatarProxy with **no payload read**.
> Movement is still unfound — do not reach for 1002 expecting it.
>
> **This subsystem REPORTS its parse failures** (unlike the referee, where everything failed
> silently). `Documents/SAdK/dumps/LobbyComm.log` is the cheap oracle:
> `Can't peek AvatarID` · `Can't read AvatarID` · `Can't find Avatar` ·
> `Could not read AvatarLocation from message.` · `Could not read tick from message.` ·
> `Avatar already logged in.` · `Error allocating memory for AvatarProxy`

## The world connection's full inbound API

`LobbyComm::VillageServerConnection::HandleMessage@0x00470a90` is the dispatcher for the village /
world connection (port 5479). Its complete world-message switch:

| msg | id | handler | stub status |
|---|---|---|---|
| EnterWorld | 1000 `0x3E8` | `HandleEnterWorld@0x0046f670` | ✅ implemented |
| **EntityCreate** | **1001 `0x3E9`** | `HandleEntityCreate@0x0046e1d0` | ❌ |
| **EntityUpdate** | **1002 `0x3EA`** | `HandleEntityUpdate@0x0046e390` | ❌ |
| **EntityRemove** | **1003 `0x3EB`** | `HandleEntityRemove@0x0046e570` | ❌ |
| **PlayerCreate** | **1004 `0x3EC`** | `HandlePlayerCreate@0x0046f8c0` | ❌ |
| WorldTick | 1005 `0x3ED` | `HandleWorldTick@0x0046f620` | ❌ |
| WorldLoginAck | 1006 `0x3EE` | `HandleWorldLoginAck@0x0046ec50` | ✅ implemented |
| PongCode | 3799 `0xED7` | `HandlePongCode@0x0046c250` | ✅ implemented |

Also dispatched (in-world entity ops / chat / room, not yet studied): `0xD8`–`0xDC`, `0x12F`,
`0xC1C`–`0xC1E`, `0xC80`/`0xC81`, `0xE11`/`0xE1B`/`0xE25`, `0xF46`, `0xF5A`.

## ⭐ `EntityCreate` (1001) — the avatar spawn (IMPLEMENTED)

`HandleEntityCreate@0x0046e1d0` peeks **`id`** (32 bits) — if that is not the leading big-endian
dword you get `Can't peek AvatarID`. It then allocates an AvatarProxy (0xE0 bytes) into the avatar
container `+0x170` if the id is unknown, calls `FUN_00482c20` to read the payload, registers the
avatar with the LobbyManager (`FUN_004780c0`) and fires the observer notify + `pTickInWorld`.

`FUN_00482c20` reads a **4-bit `dtblcks` mask** and then only the blocks it selects:

| bit | block | reader | error string |
|---|---|---|---|
| 1 | AvatarLocation | `FUN_004824b0` | "Could not read AvatarLocation from message." |
| 2 | AvatarStyle | `FUN_004825f0` | "Could not read AvatarStyle from message." |
| 4 | ActiveItems | `FUN_0048abe0` | "Could not read ActiveItems from message." |
| 8 | Avatar Stats | `FUN_00481da0` | "Could not read Avatar Stats from message." |

We send **`dtblcks = 1`** (location only) — the minimal viable avatar.

**AvatarLocation, remote-avatar branch** (`FUN_004824b0`, taken when the avatar's comm-system at
`+0xC` differs from `LobbyManager::GetCommSystem()` — i.e. for everyone who is not the local
player):

```
id 32 │ dtblcks 4 (=1) │ tick 16 │ posx 11 │ posy 11 │ posz 11 │ rot 7 │ zone 4 │ ghstzne 4 │ rnng 1 │ jmp 1
```
= **102 bits / 13 bytes.** `rnng` (running) and `jmp` (jumping) are 1-bit bools via vtbl `+0x28`;
`ghstzne` is 4 bits (`FUN_0048f930`).

## `EntityRemove` (1003) — despawn (IMPLEMENTED)

`HandleEntityRemove@0x0046e570` reads **only `id`** (32 bits) and releases the handle. The entire
body is one big-endian dword. Errors: `Can't read AvatarID`, `Can't find Avatar`.

## `PlayerCreate` (1004) — a player RECORD, not a body

`HandlePlayerCreate` reads **`id`** (32 bits), looks it up in the player container at
`VillageServerConnection+0x174`, allocates a `Player` (0x120 bytes, `FUN_0047b4d0`) if unknown,
inserts it, then `FUN_0047b5c0` parses the rest and `FUN_00464300` fires the observer fan-out that
tells the world/UI about it.

`FUN_0047b5c0`, in wire order:

| field | width | notes |
|---|---|---|
| `npcdesc` | STRING | avatar descriptor; read via reader vtbl `+0x34` |
| `posx` | **11 bits** | dequantised into world bounds (see below) |
| `posy` | **11 bits** | |
| `posz` | **11 bits** | |
| `rot` | **7 bits** | orientation |
| `zone` | **4 bits** | |
| `hrclr` | 4 bits | hair colour |
| `sknclr` | 4 bits | skin colour |
| `shrtclr` | 4 bits | shirt colour |
| `trsrclr` | 4 bits | trousers colour |
| `npcidx` | 4 bits | NPC index |
| `bdyprt` | 4 bits | body part |
| `npctyp` | 2 bits | NPC type |
| `actcnt` | 8 bits | number of actions that follow |
| … × `actcnt` | | `act` (8 bits) + `actChat` (STRING) |

So **an in-world player is an NPC-shaped avatar** — the same structure serves players and NPCs,
which is why `PlayerCreate` is full of `npc*` fields. That strongly suggests NPCs are spawned with
`EntityCreate`/`PlayerCreate` too, i.e. one implementation gets us both.

### Position dequantisation (`FUN_0048f670`) — SOLVED
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
4-byte floats yields `0.0`, which would collapse every position to the min corner — I made exactly
that mistake first. The bounds at `0x87b7**` *are* 4-byte floats.

## ⚠️ This is a BIT-PACKED, NAMED-field stream — unlike everything we send today

`FUN_0048f5f0(msg, nbits, name)` = `SelectField(name)` **then** `ReadBits(nbits)`. The name lookup
only happens when the LobbyMessage's **names flag is set** — that flag is
`*(LobbyMessage+0x20)`, set by `LobbyMessage_InitFromWire@0x0048fa50` from **bit 15 of the type
word**:

```
typeWord = names<<15 | category<<12 | id
```

⇒ **msg 1004 must be sent with `names = 1`**, i.e. type word `0x8000 | (cat<<12) | 0x3EC`.
Every other message the stub sends today uses `names = 0` (positional). So implementing this needs
a **new encoder**: a named + bit-packed LobbyMessage writer. The existing positional
PropertySet/`referee_payload` path will not do.

Note also that field widths are not byte-aligned (11/7/4/2 bits), so the writer must be a real
bit-stream, and strings are embedded mid-stream.

## Progress

- [x] World bounds + quantisation constants (statically, no gameplay needed).
- [x] `village.BitWriter` — MSB-first bit packer + `write_string` (8-bit len, 8-bit chars).
- [x] `EntityCreate(1001)` spawn with `dtblcks=1`, and `EntityRemove(1003)` despawn.
- [x] Driven from the live player registry: `dispatch._spawn_world_avatars` exchanges avatars on
      world entry; `on_conn_closed` despawns. Placement is a deterministic ring keyed by perm_id
      (`_spawn_spot`) so every observer agrees on where a player stands.
- [x] `tests/test_world_presence.py` pins the bit layout and field offsets.
- [ ] **Live confirmation** — nothing here has been seen working.
- [ ] Movement (`1002` is not it; the real update path is unfound).
- [ ] NPCs — same `EntityCreate` writer, but they will likely need the **AvatarStyle** block
      (`dtblcks` bit 1) so the client has a model to draw. Deliberately NOT added yet: stacking a
      second unproven block on an unproven spawn makes a failure impossible to attribute.

## How to read the first live test

Two clients into the lobby world, look around, then check
`Documents/SAdK/dumps/LobbyComm.log`:

| observation | meaning | next step |
|---|---|---|
| avatars visible | 🎉 | movement, then NPCs |
| `Can't peek AvatarID` | the leading 32-bit id is wrong or not first | fix the header |
| `Could not read AvatarLocation from message.` | the location block is malformed | re-check widths |
| `Could not read tick from message.` | `tick` is not the first 16 bits of the block | |
| **no error, no avatar** | the message PARSED but nothing rendered | add the AvatarStyle block (`dtblcks |= 2`) — the client probably has no model |

That last row is the important one: silence here does **not** mean the frame was wrong, because
this subsystem logs when it is. That is a genuine advantage over the referee work, where silence
was ambiguous and cost several live runs.

## Related

- `sadk_lobby/village.py` — where `EnterWorld(1000)` is built; the new messages belong beside it.
- The `EnterWorld` `ChatChannelID`/`ChatChannelZone`/`ChatChannelsCount` fields are **not** the
  source of the in-world chat tabs (refuted 2026-07-27 — the tabs are hardcoded in
  `FUN_004389d0`). Do not conflate the two.
