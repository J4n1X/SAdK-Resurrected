# Connect → Leave Character-Selection → 3D World: The Concrete Flow

**Status (s30):** The full path is reverse-engineered end-to-end (two multi-agent static-RE passes over
SADK.exe + tincat3.dll; the flow functions are now named/typed/commented in Ghidra and read like
source). The world-entry mechanism is **fully understood** and the stub is updated to drive it. The
single remaining variable is a **timing** one, not a protocol unknown. `SESSION_STATUS.md` has the
session narrative.

---

## TL;DR — what makes the client leave character-select

The server must **PUSH village message `1000` (EnterWorld)**. The "BETRETE WELT" click sends **zero**
on the wire — it only arms a client-side action; the client then *waits* for the server to push `1000`.
`HandleEnterWorld` (`SADK 0x46f470`) calls `LobbyManager::SetState(VillageEntered=9)` as its **first
instruction, before parsing the body** — so a single well-framed `1000` enters the world even with
`ChatChannelsCount=0` and dummy values.

### ★ The two big corrections from the s30 RE pass
1. **There is no "village magic."** The entire client uses **one** TinCat comm layer, magic **`0x26B6`**.
   `LobbyComm_System_Initialize` (`0x4640f0`) is the **only** `CreateCommLayer` call in the binary; the
   lobby, UserComm and Village/World "connections" are sub-objects multiplexing that one layer and its
   **one** PropertySet factory (`*(*(LobbyManager+0x50)+0x20)`). msg 1000 rides `0x26B6`, same as login.
   *(The overlay's `push 0x62; sub 0x61` is metamorphic decoy arithmetic, not a magic; and no capture
   ever contained a village magic. Both dead ends, definitively.)*
2. **The real blocker is template-registration TIMING.** The factory starts **empty**; tincat3 loads
   the 221 `msgdefs.ini` types, and the village types **1000–1006 are registered later, by SecuROM-overlay
   code during the village/world connection setup that runs *after* char-select.** Until then,
   `cPropertyFactory::CreatePropertySet(0x3E8)` (tincat3 `0x10013830`, vtable slot +0x0C) returns **NULL**
   and `DeserializeProperty` faults on it. **The historical "push 1000 = crash" (s26/s27) was pushing too
   EARLY — the template didn't exist yet.** Not a magic or format error.

---

## The end-to-end flow (message-by-message)

| # | Dir | Conn | Message | Notes |
|---|-----|------|---------|-------|
| 1 | C→S | lobby :7070 | TinCat handshake (type 3) → server type 5 | the one comm layer, magic `0x26B6` |
| 2 | C↔S | :7070 | login: 188, 201/202, 204→207, 161/162, 55/60, 189→192, 171→170×N, 105/106, 157 | **WORKS** |
| 3 | — | :7070 | `170` ServerType=4 village entry: roomId=1000, validity=1, `data=00 00 03 E8 00` | makes the entry JOINABLE → "Suche Server" button **lit** |
| 4 | C→S | UC :7071 | 2nd connection opens (to the `AssignServer/192` endpoint) | handle stored at `LobbyManager+0x548` at login |
| 5 | C↔S | :7071 | 188 → **211** → `212`+128B nonce → **213** SendToken(perm_id, cipher) → `214` ValidateToken | UC-login token round-trip; tincat3-internal |
| 6 | — | client | after 214 → renders the **3D lobby world**, then **parks** | waiting for `1000` |
| 7 | user | client | "BETRETE WELT" → `EnterVillageAction 0x503da0` → reuses UC transport → **village setup → overlay registers the 1000–1006 templates** | **emits nothing on the wire** |
| 8 | **S→C** | **UC :7071** | **★ `1000` EnterWorld (magic `0x26B6`) ★** | → `HandleEnterWorld 0x46f470` → **`SetState(9)`** → 3D world |
| 9 | C→S | :7071 | `0xED6` (3798) `SendWorldReadyAck` ("PingCode") | in-world keepalive kickoff; stub should tolerate it |

**Topology:** only two sockets ever (7070 + 7071); the client never dials :5479. msg 1000 goes on the
**UC connection (7071)** with magic `0x26B6`.

## msg 1000 body schema (CONFIRMED — tincat3 `PropertyDataConverter` + `SADK 0x46f470`)

```
STRING Worldname | u32 ServerPerm | u32 ChatChannelsCount | N×( u32 ChatChannelZone, u32 ChatChannelID )
```
Property type tags (from `Property::SetMemBlock 0x10011500`): 1/2/3 = variable (`u32 len-prefix + bytes`);
4..0xe = fixed width (8/9 = u32). Only `Worldname` is length-prefixed; `ServerPerm`/`Count`/`Zone`/`ID`
are **fixed u32**. `sadk_lobby/village.py:enter_world()` emits exactly this (byte-verified). `HandleEnterWorld`
read order: Worldname → ServerPerm(32B buf) → ChatChannelsCount → N×{Zone, ID} → JoinChannel → connState=3
→ `SendWorldReadyAck`. `HandleWorldLoginAck` (msg 1006) accepts the session only if `code == 0xDEADBEEF`.

---

## THE REMAINING VARIABLE — push timing (the only thing left)

We must push `1000` **after** the overlay registers the type-1000 template, but that registration is
**client-side** (no wire signal — the enter action emits nothing). Two ways forward:

1. **Delayed-push bet (implemented, default ON):** push `1000` (magic `0x26B6`) `ENTER_WORLD_DELAY`
   seconds after the `214` handshake, betting the post-214 village setup has registered the templates by
   then. `config.ARM_ENTER_WORLD=True`, `ENTER_WORLD_DELAY=2.0`. The s26/s27 failures pushed *immediately*
   (0 s) — the delay is the new variable. **If the client enters the world → done. If it crashes → the
   template needed the explicit BETRETE WELT engagement, go to (2).**
2. **Pin the exact registration moment (live BP):** breakpoint **tincat3!`RegisterPropertySet` (0x10013710)**
   — args `__thiscall`: `ECX` = factory `this` (= `*(*(LobbyManager+0x50)+0x20)`), `[ESP+4]` = u16 msgType,
   `[ESP+8]` = `IPropertySet*`. Watch for msgType in **0x3E8..0x3EE** to see exactly *when* (and after
   which client action) the village templates register. Then push `1000` at/after that moment. (Presence
   probe alt: call/inspect `CreatePropertySet(0x3E8)` on that factory — non-NULL = template live.)

The exact NULL-returning function (the crash) is `cPropertyFactory::CreatePropertySet` @ **tincat3 0x10013830**.

---

## What's implemented (s30)

- `config.py`: `VILLAGE_PAYLOAD_MAGIC = 0x26B6` (corrected — one layer), `ARM_ENTER_WORLD = True`,
  `ENTER_WORLD_DELAY = 2.0`, `ENTER_WORLD_WORLDNAME = "world1"`, + the corrected model write-up.
- `tincat.py`: `app_payload(ptype, body, magic=None)` — per-layer magic (defaults to `0x26B6`).
- `village.py`: `enter_world()` emits the confirmed `0x26B6` schema; `schedule_enter_world` pushes it.
- `dispatch.py`: `_h_send_token` pushes `1000` `ENTER_WORLD_DELAY`s after `214` when armed.
- `connection.py`: flags any unexpected non-`0x26B6` app magic (insurance — single-layer should hold).
- Verified offline: `1000` frames with `0x26B6`; `enter_world` byte-exact; codec-golden + smoke tests pass.

## Ghidra (now reads like source)

Two RE passes named/typed/commented ~40 functions + built structs: `VillageServerConnection` (0x258),
`LobbyVillageEnterAction`, `LobbyManager` (extended), `LobbyVillageScreen`, `UserCommConnection`,
`TinCatProperty`/`TinCatPropertySet`/`TinCatPropDataConverter`. Both programs saved. Note: Ghidra's API
can't retype the `__thiscall this` auto-param, so `this->field` still renders as `*(this+0xN)` in the
decompiler — every offset is annotated; a one-click "Retype Variable → <Struct>*" on `this` in the UI
renders all accesses as named fields.

## Next (decisive, needs the live client — for the maintainer)

1. **Run it armed** (current default): login → BETRETE WELT. The stub pushes `1000` (0x26B6) 2 s after the
   token handshake. **Enters the world?** → done. **Crashes?** → the template wasn't registered yet.
2. If it crashed: live-BP `tincat3!0x10013710` (above) to see exactly when the 1000–1006 templates
   register and after which action, then move the push to that trigger (or lengthen the delay). On Win11,
   run under `tools/debugger_loader.py` as before.
