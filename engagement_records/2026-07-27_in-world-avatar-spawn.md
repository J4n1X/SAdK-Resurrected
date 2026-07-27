# Engagement Record — spawn other players' avatars in the lobby world (EntityCreate 1001)

- **Date:** 2026-07-27
- **Type:** Stub wire-change (new outbound message on the village/world connection; **no flag**)
- **Approved by:** user, in-session: *"go ahead in order with all of those. I wanna see some results!"*
  (referring to the ordered plan in `docs/IN_WORLD_PRESENCE.md`)
- **Status:** ⏳ implemented + deployed, **awaiting live test**

## Why

The lobby world renders but is empty — no other players, no NPCs. Root cause: of the eight world
messages `VillageServerConnection::HandleMessage@0x00470a90` accepts, the stub only ever sent three
(`EnterWorld 1000`, `WorldLoginAck 1006`, `PongCode 0xED7`). The four that populate the world
(`1001` EntityCreate · `1002` EntityUpdate · `1003` EntityRemove · `1004` PlayerCreate) have never
been sent.

## What the binary says (static, `sadk_noav.exe`)

**1001 is the visible one.** `HandleEntityCreate@0x0046e1d0` allocates an **AvatarProxy** (0xE0
bytes) into the avatar container at `VillageServerConnection+0x170`, registers it with the
LobbyManager and fires the observer notify. `1004 HandlePlayerCreate@0x0046f8c0` fills a *separate*
player map at `+0x174` — a player record, not the body.

`FUN_00482c20` (the avatar payload) reads a 4-bit **`dtblcks`** mask and then only the selected
blocks: bit0 AvatarLocation · bit1 AvatarStyle · bit2 ActiveItems · bit3 Stats. **We send
`dtblcks=1`** — the minimal viable avatar.

AvatarLocation for a REMOTE avatar (`FUN_004824b0`, the `this+0xc != GetCommSystem()` branch):

```
id 32 │ dtblcks 4 (=1) │ tick 16 │ posx 11 │ posy 11 │ posz 11 │ rot 7 │ zone 4 │ ghstzne 4 │ rnng 1 │ jmp 1
```
= **102 bits / 13 bytes.**

⚠️ This is a **bit-packed** stream, unlike everything else the stub sends. `FUN_0048f0d0` consumes
each byte MSB-first and assembles values MSB-first — plain big-endian bit packing, the same
convention that made the referee's `PermID` work. Field *names* are only looked up when the
LobbyMessage names flag (bit 15 of the type word) is set; we send **names=0**, so `FUN_0048f5f0`
skips the name and reads N bits positionally. Hence a width-only writer is sufficient.

Position quantisation (`FUN_0048f670`, constants read from the image and confirmed as **doubles**):
```
x = posx/2048 * (150 - -150) + -150      scale 1/2048 @0x7debc8   (11 bits)
y = posy/2048 * ( 30 -  -10) +  -10      bounds     @0x87b700..14
z = posz/2048 * (150 - -150) + -150
rot° = rot7 * 360.0 (@0x7debc0) * 1/128 (@0x7debb8)               (7 bits)
```
⇒ world origin at ground level = `posx=1024, posy=512, posz=1024`.

## The change

- `village.BitWriter` — MSB-first bit packer (+ `write_string`: 8-bit length then 8-bit chars,
  per `FUN_0048ffc0`, for the PlayerCreate fields we do not send yet).
- `village.entity_create_body()` / `send_entity_create()`.
- `dispatch._spawn_world_avatars()` — on world entry, mutual exchange: the newcomer receives an
  `EntityCreate` for everyone already in-world, and each of them receives one for the newcomer.
  Fires `AVATAR_SPAWN_DELAY` (2 s) after `EnterWorld`, so the client has an avatar container.
- `dispatch._spawn_spot(perm_id)` — deterministic ring position around the origin. Real positions
  are unreversed; keying on perm_id keeps a player's spot stable and identical for all observers.
- `tests/test_world_presence.py` — pins the bit layout, field offsets, quantisation and string form.

## Falsifiable predictions

1. **Success:** with two clients in the lobby world, each sees the other's avatar standing on a
   small ring around the town-square origin.
2. **Malformed body:** the client logs it — this subsystem, unlike the referee, reports parse
   failures. Look in `Documents/SAdK/dumps/LobbyComm.log` for
   `Can't peek AvatarID` (the leading 32-bit id is wrong / not first) or
   `Could not read AvatarLocation from message.` (the location block is wrong) or
   `Could not read tick from message.`
3. **Accepted but invisible:** no error logged and no avatar ⇒ the message parsed but the render /
   observer path needs more (most likely the AvatarStyle block, `dtblcks` bit1, so the client has a
   model to draw). Next step would be adding that block, not re-checking the location one.
4. **Wrong place:** avatar appears but underground / floating ⇒ `posy` mapping is off; y=0 should be
   `512` given bounds −10..30.

## Verification

Two clients into the lobby world, look around. Then read `LobbyComm.log` for the strings above —
that is the cheap discriminator between (2) and (3), and it needs no TTD.
