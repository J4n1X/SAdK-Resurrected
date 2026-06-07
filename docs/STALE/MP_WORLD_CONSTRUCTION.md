> # ⚠️ CORRECTION — this doc's headline thesis is REFUTED
> The central claim — that MP world-entry crashes because the **GameSystem singleton
> `*(0x890fcc)` is NULL** and `OnEnter` dereferences it unconditionally, so the fix is to
> "construct GameSystem" — was **corrected**: that NULL was a **no-CD-build artifact**. On the
> clean build GameSystem is built on the shared path regardless of mode, and world entry is **not**
> blocked on a client-side build step — it is the server pushing msg 1000. Addresses (`0x5ef110`,
> `0x890fcc`, `0x4e37d0`, …) are **old-build** VAs. Kept for the factory/ctor/descriptor RE only.

# MP World Construction — what the multiplayer fix must replicate

**Status: s37, READ-ONLY construction workflow (4 tracks) + independent raw-byte review — verdict "confirmed".**
All addresses are `SADK.exe` @ image base `0x400000`. This is the client-side *build* model; the wire
protocol lives in [`IN_WORLD_PROTOCOL.md`](IN_WORLD_PROTOCOL.md). Engagement rules in [`../HARNESS.md`](../HARNESS.md).

> **Headline.** There is exactly ONE 3D-world builder both SP and MP converge on: `nMenu_Game_OnEnter@0x5ef110`.
> At the stuck MP world-entry the Game screen is already built and its descriptor is already allocated — the
> **only missing object is the `GameSystem` singleton `*(0x890fcc)`**, which OnEnter dereferences *unconditionally*.
> The MP world is a server-**named local map**, not streamed terrain, so the fix needs **no terrain injection** —
> just construct `GameSystem`, ensure the map name is staged, and dispatch OnEnter.

---

## The one confirmed gap — `GameSystem` singleton `*(0x890fcc)`

| | built SP world | stuck MP entry |
|---|---|---|
| `*(0x890fcc)` GameSystem | **populated** | **NULL** ← the gap |
| Game screen `*(System+0x3c)` vtbl | `0x7efcbc` ✓ | `0x7efcbc` ✓ (built) |
| descriptor `*(Game+0xffe4)` | populated | **populated** (`0x315844B0`) |
| Game is active screen (`System+0xc`) | yes | no |

`OnEnter@0x5ef110` dereferences `*(0x890fcc)` **unconditionally** at `0x5ef2e7`
(`MOV ECX,[0x890fcc]; CALL 0x526bc0` → double-deref `*(*(GS+0x30)+0x34)`) *before* any branch — so forcing
OnEnter while GameSystem is NULL crashes here regardless of the descriptor. **GameSystem must be constructed first.**

### Probe-offset correction (important)
OnEnter's `this` is `Game+0x20` (the screen-base subobject). Therefore its `[this+0xffc4]` / `[this+0xffc8]`
are the **absolute** `Game+0xffe4` (descriptor) / `Game+0xffe8` (build-this). There is **no separate
`Game+0xffc4`/`+0xffc8` field** — `search_instructions` finds zero writers to those offsets. The earlier
`probe_build_state.py` read `GameBase+0xffc4/+0xffc8` (off by 0x20 = junk) and wrongly reported the
descriptor as NULL at MP. The **real** descriptor (`Game+0xffe4`) is populated in MP. *The descriptor was
never the gap.* (Probe corrected: `GAME_DESC_OFF=0xffe4`, `GAME_BUILD_OFF=0xffe8`, plus a `desc+0x04` map-name read.)

---

## SP construction sequence (what MP must replicate)

### Lifetime A — `GameSystem` singleton `*(0x890fcc)` (SecuROM-veiled)
- Written at exactly **3** sites image-wide: `0x4e384f` (success), `0x4e3866` (null-fail), `0x526b72` (dtor).
- **Factory `@0x4e37d0`** has **zero static xrefs** → invoked via SecuROM dynamic dispatch (overlay). Prologue:
  installs SEH, `PUSH 0xF4` (244-byte object), `operator new @0x6f2b53`, then the **obfuscated ctor body
  `@0x4e382c`** (scramble tables `0x12edaac`/`0x8f2d88`; dynamic-return trampoline lands success `@0x4e384f`).
- The veiled ctor allocates the subsystem slots that `GameSystem_LoadWorldData@0x5aac90` later `Load()`s
  (`vtbl+8`): `[0xb]`+0x2c map-header, `[0x12]`+0x48 terrain (`FUN_005b4b10`), `[0x1a]`+0x68 entities
  (`FUN_0052ca90`), `[4]`/`[8]`/`[0xc]`, accessor `+0x30`, per-player flags `+0xac`. Object vtable @ obj+0.
- **Unknown (live-only):** the factory's *caller/timing*, and whether the ctor consumes the prologue-pushed
  `ECX` as an argument or assumes other singletons exist. Resolve with a BP on `0x4e384f` during an SP new-game.

### Lifetime B — the `nMenu::Game` screen object (built at screen-tree time, cleartext)
`nMenu_Game_ctor@0x5ee9e0` allocates **unconditionally**:
- `Game+0xffe4` ← GameLoadDescriptor, 0x248 B (ctor `0x5aa170`; reset `0x5aa090` → map-name `std::string`@+0x04)
- `Game+0xffe8` ← build-this `nGame::System`, 0x648 B (ctor `0x7834c0`)
- `Game+0xffec` ← UI/LoadingPanel-host, 0x4310 B (ctor `0x5f87a0`)

### Staging the descriptor (per world-entry)
`GameLoadDescriptor_SetMapNameAndType@0x5aa130` writes `desc+0x04`=map-name, `desc+0`=type, `desc+0x23c/240`=players.
**Shared writer** — SP `MapSelect_…_FillDescriptor@0x5df4b0` and **MP `FillMpDescriptor@0x4563c0`** both call it,
targeting `*(*(System+0x3c)+0xffe4)` (System = `*(0x892e9c)`).

### Activation + dispatch (the convergence primitive)
`FUN_005da0a0` → `MOV [System+0xc], Game` (Game becomes the **active screen**) → `[Game+0x20].vtbl[0x84]`
= `OnEnter@0x5ef110` (raw read `0x7efd40` = `0x5ef110`). `ActivateScreenById@0x5d98c0` only makes a screen
*visible* (`vtbl+0x08`); it does **not** call OnEnter.

### Build (inside OnEnter → `0x785070`)
`SP_BuildScene_LoadTerrainXml@0x784610` (global `[data]\settings\map_objects.xml` + `terrain_static_data.xml`
templates) → `GameConfig_CopyToLoadParams@0x785000` (descriptor → `nGame::System+0x3b0`) →
`SP_LoadMapFile_Orchestrator@0x5acc50` → `nGame_File_load@0x5ab660` → **seam `FUN_00780b27`** (`loadFromNet==0`
→ LOCAL file from `desc+0x04`; `==1` → net/savegame stream) → `GameSystem_LoadWorldData@0x5aac90` streams map
data into the pre-built `*(0x890fcc)` subsystem slots.

---

## Data seam — the MP world is a server-NAMED LOCAL map (not streamed)

- `FillMpDescriptor@0x4563c0` stages the same `Game+0xffe4` descriptor and does a **local map lookup**
  (`"Map not found: %s"`) plus a cross-client name check (`"Mapnamen unterschiedlich: %s != %s"`).
- **msg-1000 `Worldname` is chat/display only** (`HandleEnterWorld@0x46f470` → VillageServerConnection+0x228,
  `<UNNAMED>` fallback; SetState 9; JoinChannel; `connState+0x244=3`; SendWorldReadyAck PingCode `0xED6`). It is
  **not** a map-file name and never writes a descriptor or dispatches OnEnter.
- Server world content arrives as **dynamic entity/player overlays** (msgs 1001–1006: `HandleEntityCreate@0x46ddf0`
  → 0xE0 record into conn+0x170; `HandlePlayerCreate@0x46f6c0` → 0x120 record into conn+0x174), layered onto the
  already-built local map — **not** into `*(0x890fcc)` terrain.

⇒ **The fix needs no terrain injection and does not touch the net-vs-local seam.** The injection point is the
OnEnter *trigger* + GameSystem construction.
**MEDIUM caveat:** the deeper MP loader body is SecuROM-virtualized (below), so we cannot statically *prove* the
triggered MP path loads terrain via the SP local chain rather than a parallel overlay path.

---

## BgCreation reconciled — it is the MP loader, not dead code

`App_ProcessStateTransition@0x4f57e0` (App-mode secondary vtable `0x7e69c8`, `this=App+0x88`) has two
mutually-exclusive arms keyed on **current** state (`+0x270`):
- **ARM1** (current ∈ {0,1}, requested ∈ {2,3}) = world-ENTER → on requested==3 + LobbyMgr 3/0xB →
  **App `vtbl[0x80]=0x4fa540`** (raw `0x7e6a48`=`0x4fa540`) → `FUN_004f7bd0` →
  **`MP_LoadVillageWorld_BgCreation@0x4f7bd7`** = the MP village loader.
- **ARM2** (current ∈ {2,3}, requested==1) → `FUN_005d9a30` + `FUN_005da0a0` → OnEnter.

So BgCreation **is** dispatched (the MP arm) — the s36 "BgCreation is dead/off-base misread" note was wrong on
that. But its deeper body `FUN_004f6900 = (*_DAT_012e9058)()` is a **SecuROM overlay jump** → opaque. **Whether
BgCreation already constructs `*(0x890fcc)` or loads terrain cannot be ruled out** — the key remaining unknown.
(`0x7e69c8` is a legit App-mode secondary vtable, not a phantom; CLobby's own vtable is `0x7e699c`, whose
`vtbl[0x80]=0x4f4ef0=RequestEnterVillage` is a different slot.)

---

## The refined fix (mutation footprint — for a future Engagement Record; NOT run)

Ordered; **A before D is mandatory** (OnEnter derefs `*(0x890fcc)` unconditionally):

- **A. Construct `GameSystem *(0x890fcc)`** — drive the genuine SP trigger, or one-shot the cleartext factory
  `0x4e37d0` (risk: the veiled ctor may need an `ECX` arg / assume other singletons — live-only).
- **B.** Game screen + descriptor(`+0xffe4`) + build-this(`+0xffe8`) + UI-host(`+0xffec`) already exist in MP —
  likely no work; re-confirm build-this/UI-host live.
- **C.** Ensure `desc+0x04` (`Game+0xffe4`) holds a valid local map name (FillMpDescriptor may have done it; a
  joiner may need it re-staged from the host-advertised name).
- **D. Dispatch OnEnter** via `FUN_005da0a0` (`System+0xc:=Game`; `[Game+0x20].vtbl[0x84]`). Cascades:
  build-this+0xc/+0xd=1, scene-render (`Game+0x7fd0`) activated, LoadingPanel hidden.

---

## Decisive next checks (read-only, do first)

1. **Corrected-probe RPM snapshot** on a stuck MP entry (`tools/probe_build_state.py`): `*(0x890fcc)`; the Game
   screen + vtable; `*(Game+0xffe4)` descriptor + **`desc+0x04` map-name** + `*(Game+0xffe8)` build-this.
   - GameSystem NULL + Game built + `desc+0x04` = a real map name ⇒ **minimal fix** = construct GameSystem + OnEnter.
   - Empty `desc+0x04` ⇒ staging must be added (joiner path).
2. **Live BP on `0x4e384f`** during a *successful SP new-game* → capture the factory's caller/timing and whether
   `ECX` carries an argument (the only way to de-risk a blind call to `0x4e37d0`).
3. **Live BP on `0x4e384f` / `0x5ab660`** during the MP village-enter → settle whether `BgCreation` already
   constructs GameSystem / loads terrain.

## Open questions
- The factory `0x4e37d0` caller + ctor arg/singleton assumptions (SecuROM-veiled).
- Whether `MP_LoadVillageWorld_BgCreation` already builds GameSystem (overlay-opaque).
- Which lobby NETMSG carries the host map name to a *joining* client (server-named-local-map model for non-hosts
  is asserted; carrier message unidentified).
- The exact subsystem classes newed into each GameSystem slot + the singleton's vtable (ctor is veiled).
