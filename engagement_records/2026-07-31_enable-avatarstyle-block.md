# Engagement Record — enable the AvatarStyle block on EntityCreate(1001)

**Date:** 2026-07-31 · **Status:** APPROVED, deployed · **Type:** stub wire change

## Why

The avatar does not appear, and as of tonight we know **why it is not a wire problem**: the
negative-control probe crashed the client, which proves msg 1001 *is* routed to
`HandleEntityCreate@0x0046e1d0` and *is* executed (an undelivered frame cannot crash anything).
The well-formed 13-byte frame is therefore delivered and parsed — it produces no error on either of
the handler's two logging failure paths. See
`engagement_records/2026-07-31_entitycreate-negative-control.md`.

So the remaining hypothesis is **H1: it parses, and nothing renders** — most plausibly because a
location-only avatar has no appearance for the client to draw. `dtblcks` bit1 (**AvatarStyle**)
carries exactly that: name, tribe/gender and eight colour slots.

## What changed

`dispatch._avatar_style(player)` supplies a style block and `_spawn_world_avatars` passes it to
`village.send_entity_create`, which sets `dtblcks = 3` (location | style). Body grows 13 → 30 bytes.

Values are conservative: the real `char_name`, `tribe_gender = 0`, all eight colours `0`.
`trbgndr` packs tribe and gender into one byte and the packing is **[TODO]** — 0 is the safest first
guess.

## Layout VERIFIED against the binary first — not taken from the doc

Given the probe crash came from an *inferred* detail, the layout was re-derived before sending:

- `AvatarProxy_ReadStyleBlock@0x004825f0` — `LobbyMessage_SelectField("name")` + reader vtbl+0x34,
  then **nine** 8-bit reads via vtbl+0x8 landing in consecutive bytes `AvatarProxy+0x48..+0x50`:
  `trbgndr`, `hrclr`, `sknclr`, `shrtclr`, `trsrclr`, `addColor1`, `addColor2`, `addColor3`,
  `addColor4`. Matches the merged 2026-07-28 survey exactly.
- `FUN_0048ffc0` (the string reader) — `FUN_0048f0d0(this, 8)` for the length, then that many 8-bit
  chars. Exactly what `village.BitWriter.write_string` emits. ⚠️ It does **not** bounds-check, so the
  declared length must be honest — ours is, by construction.
- `LobbyMessage_SelectField@0x0048f490` is a no-op under `names=0`, so every `SelectField` call in
  this block collapses to a positional read.

## Reading the result

⭐ **Every field in this block has its own distinct error string** in `LobbyAvatarProxy.cpp`, so
unlike the location block a mistake **names itself** in `Documents\SAdK\dumps\LobbyComm.log`:

| log line | meaning |
|---|---|
| avatar visible | 🎉 H1 confirmed — the missing piece was appearance |
| `Could not read name from stream.` | the string encoding is wrong (8-bit len + 8-bit chars) |
| `Could not read tribe and gender from stream.` | `trbgndr` width/position wrong |
| `Could not read hair/skin/shirt/trouser color from stream.` | that colour's width/order wrong |
| `Could not read additional color from stream.` | one of `addColor1..4` |
| still silent, still no avatar | style was NOT the missing piece — look at the `+0x1ac` notify subscriber next |

⚠️ Parsing is now well-covered, but a **render-time** crash remains possible if colour 0 or
tribe/gender 0 indexes something invalid. That is an accepted risk of the test; the previous crash
was a *parse* over-read, which this design avoids.

## Harness compliance

- Not faking a result: this supplies real data the client asks for, via the real message.
- No flag-gating: style is now the default for player spawns, not hidden behind a switch.
- Reversible: `_avatar_style` returns the block; passing `style=None` restores the 13-byte form,
  which is still pinned bit-identical by `test_default_spawn_is_unchanged_by_the_style_option`.

## Result

*(to be filled in after the run)*
