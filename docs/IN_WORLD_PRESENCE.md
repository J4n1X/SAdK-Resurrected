# In-world presence — the world-connection entity/player protocol

**Status: SPEC DERIVED 2026-07-27 (static, `sadk_noav.exe`). NOT YET IMPLEMENTED — nothing here has
been sent to a live client.** This is the map for making the 3D lobby world non-empty: other
players visible, NPCs spawned, avatars moving.

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

## `PlayerCreate` (1004) — the exact payload

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

### Position dequantisation (`FUN_0048f670`)
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

## Suggested order of work

1. Read the world-bound globals (`0x87b700`–`0x87b714`, `0x7debc8`, `0x7debc0`, `0x7debb8`) from a
   live process — one TTD/debugger read, no gameplay needed.
2. Build the named/bit-packed LobbyMessage writer (the reusable piece).
3. Send **one** `PlayerCreate(1004)` after `EnterWorld(1000)` with a mid-world position and a
   plausible `npcdesc`, and see whether an avatar appears. One frame, immediately falsifiable.
4. If it appears: drive it from the player registry so each client sees the others, then
   `EntityUpdate(1002)` for movement and `EntityRemove(1003)` on leave.
5. `EntityCreate(1001)` for NPCs, using the same writer.

⚠️ Every failure mode in the referee subsystem was silent, and this one has the same shape (an
observer fan-out that simply does not fire). Before a live drive, prefer
`ttd_calls 0x0046f8c0` (did `HandlePlayerCreate` run?) and `ttd_calls 0x00464300` over guessing
from the absence of an avatar on screen.

## Related

- `sadk_lobby/village.py` — where `EnterWorld(1000)` is built; the new messages belong beside it.
- The `EnterWorld` `ChatChannelID`/`ChatChannelZone`/`ChatChannelsCount` fields are **not** the
  source of the in-world chat tabs (refuted 2026-07-27 — the tabs are hardcoded in
  `FUN_004389d0`). Do not conflate the two.
