# The 3D lobby village on the client

Specification of the walkable 3D village of `sadk_noav.exe`: namespace `Lobby` and its helpers in `ai::lobby` and
`ai::lobbygfx`. Tags: [known] = read at the address given (S 00xxxxxx) or in the named data file and key;
[inferred] = one step of reasoning from what is visible; [TODO] = open. Nothing here was observed in the running
game unless a line cites a dated live observation of another document.

Related documents, not repeated here:

- [`../village-and-character-protocol.md`](../village-and-character-protocol.md): every village message, its
  fields, the server flows (EnterWorld, presence, NPC records, shop, leaving). This document says which message
  drives which change of the 3D world and links there for the layouts.
- [`../message-catalog.md`](../message-catalog.md): the message ids and bit layouts.
- [`frontend-screens.md`](frontend-screens.md), [`../LOBBY_SCREEN_VTABLES.md`](../LOBBY_SCREEN_VTABLES.md): the
  lobby UI (`LobbyMenu::*`), which sits on top of this world.
- [`app-shell.md`](app-shell.md) §4: who creates `CLobby` and calls it per frame. [`audio.md`](audio.md) §3.4:
  the emitter and listener side of the sound system. [`formats-inventory.md`](formats-inventory.md) §3: the
  container formats (`.KEX`, encrypted XML, `.npc` / `.avo`, `ItemsClient.txt`, `itemicons.txt`,
  `QuickEmotes.txt`). [`../BINARY_PATCHES.md`](../BINARY_PATCHES.md): the billboards mod.

## 1. Purpose and scope

`Lobby::CLobby` (0x290 bytes, one instance, `CApplicationEx + 0x88`) is a second, self-contained 3D world next
to the RTS scene: a small village in which every logged-in player walks an avatar, meets other avatars and NPCs,
selects objects and sits down at minigame tables. It owns its own scene graph (13 `CGfxScene` zones), renderer,
camera, PhysX world, avatar system and input mapping, and it hosts the lobby UI (`LobbyMenu::System`). It also
renders the character selection and customisation stage and the avatar portraits. [known] S 004f8c90

In scope: `CLobby` and its context, `CLobbyScene` and the scene files, zones and zone transitions, collision,
`CLobbyObj` and its controllers, `CGfxObjAvatar` (model choice, colours, items, pets, animation, emotes, name
tags, chat bubbles), NPC objects, `CLobbyCamera`, picking and selection, billboards and web textures, sound and
music of the village, `CLobbyClient` as the bridge to the village connection, and the files under `data/lobby`.

Out of scope: the wire formats (protocol documents above), the lobby dialogs and screens, the three minigame
boards (`CGfxObjMiniGame*_Board`, `CMiniGameController*`, `CLobbyClient_MiniGame*`; only their hooks into the
scene and the camera are listed), the lobby's shader and material system beyond the file inventory.

Coordinates: right-handed use is not established; **y is up**, units are metres-like world units (an avatar's
text anchor is 2.4 above its feet). Angles in files are degrees, in code radians. Times are 64-bit milliseconds
of the application clock (`Timer_GetElapsedMsSinceStart`).

## 2. Data model

### 2.1 `Lobby::CLobby` (0x290)

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x04 | `bDirty` u8 | forces one more object step in the next tick (§4.1); set by every mode or view change | [known] S 004fb230 |
| +0x05 | `bAmbientSoundsActive` u8 | the zone's ambient emitters are started | [known] S 004f9960 |
| +0x08 | `soundListener` | `CLobbySoundListener`: position (+4), forward (+0x10) for FMOD | [known] S 004f56c0 |
| +0x28 / +0x30 / +0x38 | `lastFrameMs`, `nowMs`, `nextStepMs` u64 | frame clock and the fixed-step clock | [known] S 004fb230 |
| +0x40 | `stepMs` u64 | fixed step, **83 ms** (about 12.05 steps per second) | [known] S 004fb100 |
| +0x48 | `viewMode` i32 | requested camera mode (§2.6); 0 = leave the camera alone | [known] S 004f58a0 |
| +0x4c | `pLobbyScene` | `CLobbyScene` (§2.3) | [known] S 004f8c90 |
| +0x50 | `renderMask` u16 | OR of the category bits whose `rm*` flag is set (§2.4) | [known] S 004fb230 |
| +0x54 | `currentZone` i32 | zone the camera is in; selects the `CGfxScene` drawn and picked | [known] S 004f9960 |
| +0x58 / +0x60 | `pSelectedObj`, `pHoverObj` | selection and hover (§3.8) | [known] S 004f5210 |
| +0x5c | `snapshotStatus` i32 | 1 = the selection portrait was rendered this frame, 2 = the selected object has no player proxy; left unchanged while nothing is selected (§3.9) | [known] S 004f9960 |
| +0x64 / +0x68 | texture ids | `lightmap_white.tga`, `skyWaterReflection.dds` | [known] S 004f8c90 |
| +0x6c..+0x7c | five i32 | cached graphics options: shadow, mirror, shader detail, texture quality, object details; all −1 until first set | [known] S 004fb100, S 004f5290 |
| +0x80 | i32 | camera preset index for mode 5 (§3.7) | [known] S 004f54b0 |
| +0x84 | `pCustomizePreviewObj` | the `customizeavatar` object while customising | [known] S 004f7550 |
| +0x88 | `pSnapshotAvatarObj[7]` | the seven `snapshotavatar` objects (§3.9) | [known] S 004f7300 |
| +0xa4 / +0xa8 / +0xac | `objCount`, `objCapacity`, `objData` | all live `CLobbyObj`; growth ×1.5; removal swaps the last entry in | [known] S 004f6ca0, S 004f5ce0 |
| +0xb0 / +0xb4 / +0xb8 / +0xbc | `CGfxView*` | main, aux (portraits), reflection (256), shadow | [known] S 004f8c90 |
| +0xc0.. | `ctx` (`LobbyContext`) | shared pointers handed to every object: client +0xc0, render settings +0xc4 / +0xc8, mesh mgr +0xcc, texture mgr +0xd0, shader mgr +0xd4, renderer +0xd8, shadow map +0xdc, `pZoneScenes[13]` +0xe0, device +0x114, random generator +0x11c (seed 0x5432ace0), pet mgr +0x120, body parts +0x124, NPC body parts +0x128, avatar item list +0x12c, physics +0x130, object config +0x134, camera +0x138, snapshot maker +0x13c, node tag table +0x140, item database +0x22c, UI renderer +0x230, anim selector +0x234, pick ray +0x238, local avatar object +0x254, text bubble renderer +0x258 | [known] S 004f8c90 |
| +0x25c..+0x263 | `rmDefault`, `rmTerrain`, `rmCharacter`, `rmBuildingMajor`, `rmBuildingMinor`, `rmVegetationMajor`, `rmVegetationMinor`, `rmMiniGame` | render-mask switches, all true at start; `rmBuildingMinor` and `rmVegetationMinor` are rewritten every frame from the object-details option (§3.11) | [known] S 004fb100, S 005006e0 |
| +0x264 / +0x265 | `bSelectionEnabled`, `bClickPending` | selection gate; latched left click | [known] S 004f5420 |
| +0x268 | `maxSelectionDistance` f32 | **25.0** | [known] S 004fb100 |
| +0x26c / +0x270 / +0x274 | `prevMode`, `curMode`, `requestedMode` | lobby mode (§2.2); −1 = none | [known] S 004f5950 |
| +0x278, +0x27c.. | `nextWatchId`, vector of `LobbyDistanceWatch` | walk-away watches (§3.10) | [known] S 004fb5f0 |

### 2.2 Lobby mode (`curMode`)

| Value | Meaning | Tag |
|---|---|---|
| 0 / 1 | the lobby world is not the foreground: the game or the main menu runs; ambient sound, lobby UI update and zone music are off | [inferred] S 004f5950, S 004fb460 |
| 2 | lobby world shown without a village connection: a local avatar built from an empty default `AvatarProxy` is created at once, no position reports are sent | [known] S 004f5950, S 004f6fd0, S 005034e0 |
| 3 | lobby world with the lobby UI, online: login, character screens, then the village | [known] S 004f5950 |

A request is latched with `RequestModeTransition` (only when none is pending) and applied once per frame by
`ProcessModeTransition` (§4.3). [known] S 004f4eb0

### 2.3 `CLobbyScene` (0x1340) and its records

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x04 | world file name (string) | `world1.xml` in the shipped game | [known] S 00502750, string S 007d41a8 |
| +0x20 | `bLoaded` | settings table valid | [known] S 00501980 |
| +0x28 | `sceneSettings[32]` (0x98 each) | per zone: `fogStart`, `fogEnd` (+0, +4), `fogColor` rgba (+8), `ambient` rgba (+0x18), `diffuse` rgba (+0x28), `lightDir` normalised (+0x38), `shadowLightIntensity` (+0x44), `lightMapTexture` id (+0x48), bounds, transform and world bounds of the light-map object (+0x4c, +0x64, +0x80) | [known] S 005013b0 |
| +0x1328 | spawned object list | every object created from the scene files and the table spots | [known] S 00501b90 |
| +0x1334 | emitter list (0x34 each) | `name` (lower case), `soundId` u32, `pos` f32[3], `scene` i32, `playing` u8 | [known] S 00501b90 |

### 2.4 Object classes: `LobbyObjConfig` and `CLobbyObj` (0x94)

An object class is one `<lobbyobj>` of `lobbyobj.xml` (§6.2): a lower-cased name, a `gfxclass`, a
`controllerclass` and the two parameter nodes. [known] S 004ffe70

`CLobbyObj`:

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x04 | `gfxObj` | graphics object, by `gfxclass` (table below) | [known] S 00502a90 |
| +0x08 | `owner` | the `LobbyContext` | [known] |
| +0x0c / +0x10 / +0x14 | controller stack index, current controller, stack of 4 | minigames push a seat controller on top and pop it again | [known] S 00502910, S 00502960 |
| +0x24 / +0x28 | primary scene handle and **zone** index | the zone the object belongs to | [known] S 005027f0 |
| +0x2c / +0x30 | secondary scene handle and zone | second zone the object is also drawn in; 0xf = none | [known] S 005027f0 |
| +0x34 | `actorProxy` | `AvatarProxy` / `NPCProxy`, null for scenery | [known] S 00502e60 |
| +0x38 / +0x44 | `position` f32[3], `rotation` quaternion f32[4] | written by the controller every step | [known] S 005029e0 |
| +0x54 | `objectDef` | the class record | [known] |
| +0x58 | `bLocal` | the player's own avatar | [known] |
| +0x78 | `name` | scene object name, or the actor's name | [known] |

`gfxclass` → graphics object [known] S 00502a90:

| `gfxclass` | Class (size) | Used for |
|---|---|---|
| `std` | `CGfxObjStd` (0x100) | all scenery, buildings, table spots, the letterbox |
| `avatar` | `CGfxObjAvatar` (0x5060) | players, NPCs, the customise and portrait dummies |
| `skydome` | `CGfxObjSkydome` (0xc8) | sky sphere and cloud planes |
| `minigamedice_board`, `minigamepoker_board`, `minigamepawnchess_board` | board classes (0x3720, 0x5990, 0x4380) | minigame tables in play |

An unknown `gfxclass` leaves `gfxObj` null. [known]

`controllerclass` → controller [known] S 00502e60:

| `controllerclass` | Controller | Rule |
|---|---|---|
| `customize` | `CustomizeAvatarController` (0x58) | stand that turns with the mouse (§3.6) |
| `character` | `CLocalController` (0xa8) if `bLocal`, else `CNetController` (0x198) | own avatar / every other actor |
| `none` | none created here | the minigame code pushes its own controller onto the stack |
| anything else (`std`) | `CStaticController` (0x48) | fixed pose plus static collision |

`CGfxObjStd` parameters (attributes of `gfxparm`) [known] S 005191c0:

| Attribute | Field | Meaning |
|---|---|---|
| `file` | | `.KEX` scene file of the model |
| `mesh` | +0xc0 | mesh name inside the file (optional) |
| `collision_mesh` | +0xc4 | mesh used for static collision; `none` = no collision; **absent = the visual mesh (`mesh`) is the collision mesh** (in `lobbyobj.xml` 49 of the 100 `std` classes carry the attribute, 29 of them `none`) |
| `collision_mesh_move` | +0xc8 | second collision mesh that only blocks walking (§3.3) |
| `scene_trigger`, `transition_area`, `scene` | +0xcc, +0xd0, +0xd4 | door volumes and the zone they lead to (§3.2) |
| `node_hierarchy`, `node_hierarchy_scale` | +0xd8 | animated node set whose node names carry `pfx:` and `slot:` tags (§3.2); scale default 1.0 |
| `lod_class` | render mask | `building_major` 8, `building_minor` 0x10, `vegetation_major` 0x20, `vegetation_minor` 0x40, `terrain` 2, `character` 4; absent or other = 1 [known] S 0051d410 |
| `fadeout_start`, `fadeout_end` | +0xdc, +0xe0 | distance fade (§3.11); default no fade |
| `rank` | +0xe4 | fixed draw order key; default −1 |
| `instancing` | | `true` loads the mesh for instanced drawing |
| `selectionValue` | +0xe8 | non-zero makes the object pickable (flag 0x10000) and is the value the UI reads (§3.8) |
| `selectionDecalOffsetY`, `selectionDecalSize` | +0xec, +0xf0 | selection ring placement |
| `visible` | flag 0x20 | `false` hides the mesh (the object can still be picked) |

`IGfxObj` flags (+0x98) [known]: 4 hovered, 8 selected, 0x20 hidden, 0x10000 pickable.
S 005040c0, S 005040e0, S 005191c0

### 2.5 Controllers

`ILobbyObjController` (0x24): `zone` (+4), `ghostZone` (+8, the secondary zone, 0xf = none), idle animation id
(+0xc), walk animation id (+0x10), current animation id and speed (+0x18, +0x1c; −1 after activation), pending
"reset interpolation" flag (+0x14), owner context (+0x20). [known] S 005111a0, S 00511200, S 00511250

`CLocalController` adds [known] S 0051a1a0:

| Offset | Field | Meaning |
|---|---|---|
| +0x24 | `charPhysics` | `CPhysicObjCharacter` (§3.3) |
| +0x30 | `collisionMask` u32 | `0x10001 << zone`, recomputed every step |
| +0x38 | step counter u8 | wraps; a report goes out when `counter & 3 == 0` |
| +0x39 / +0x3a / +0x3b | `moving`, `running`, `jump` latch | |
| +0x3c | view heading (radians) | the heading the camera aligns to |
| +0x40 | move heading (radians) | the body orientation and the reported rotation |
| +0x48 | `OrbitCameraRig` (0x60) | pitch, yaw, roll, orientation quaternion, zoom speed, distance limits, pitch and yaw limits, target and current distance, a 500 ms distance tween, close-up flag |

`CNetController` adds [known] S 00519c10: `samples[8]` at +0x28 (0x28 each: `timeMs` u64, `pos` f32[3], `rot`
f32[4], `running` u8, `jump` u8), `headIndex` (+0x168), last output position (+0x16c), `lobbyObj` (+0x188),
`bHasSample` (+0x18c), `bInitialized` (+0x18d), `interpMode` (+0x190, the actor type: 1 = player avatar).

`CStaticController`: pose (+0x24), `physStatic` (+0x40), `physMove` (+0x44). [known] S 005198c0

### 2.6 `CLobbyCamera` (0x450)

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x04 | `mode` | key slot in use: **1** walking, **2** seated at a table, **3** watching a table, **4** character selection / customise, **5** fly-by presets (initial) | [known] S 004fef10, S 0051a840, S 005269e0, S 004ff420 |
| +0x08 / +0x0c / +0x10 | `fov`, `nearClip`, `farClip` | 72° (64° in mode 4), **0.1**, **500** | [known] S 004fef10, S 004ff420 |
| +0x18 | `lastTime` | evaluation time, set every tick | [known] S 004fee20 |
| +0x20 | 6 orbit interpolators | per slot: orientation quaternion and distance | [known] S 004ff220 |
| +0x200 | 6 target interpolators | per slot: look-at point | [known] S 004ff280 |
| +0x3e0 | `interpState[6]` | per slot: the **zone** given with the last target key; reset to 0xf | [known] S 004ff280, S 004fee40 |
| +0x3f8 / +0x404 | water clip plane normal (0,1,0), `waterHeight` **−0.1** | reflection pass | [known] S 004fef10 |
| +0x448 | `presetIndex` 0..2 | mode 5 preset | [known] |
| +0x44c | `fovScale` | 1.0; set by the table camera | [known] S 004fef00 |

Eye position = target + orientation · (0, 0, −1) · distance, both evaluated for slot `mode` at `lastTime`.
[known] S 004ff940

### 2.7 `CGfxObjAvatar`: state that matters

Model set (avatar or NPC body parts), body-part set index (`modelIndex`: gender for players), variant index,
eight colour indices and the palette built from them, three item slots (name, mesh id, bone matrix), pet
instance id and name, pet trail, animation graph, animation model, emote player, animation state and speed,
bubble text, `textOpaqueUntil`, two bitmap fonts. [known] S 005084b0, S 00508090

### 2.8 `CLobbyClient` (0x38)

`pLobby` (+4), `pLobbyManager` (+8), `pVillageConn` (+0xc), `bReleaseConnection` (+0x10), `bReenterPending`
(+0x11), a dword handed to the village connection when the village is entered (+0x14), `fReenterTimeout`
seconds (+0x18), `nReenterRetries` (+0x1c), `bUseDefaultSpawn` (+0x20), `bHasSavedPosition` (+0x21), `savedPos`
(+0x24), `savedHeading` (+0x30), `savedZone` (+0x34), `savedGhostZone` (+0x35). [known] S 005033b0, S 00503f50
[TODO] not established: what +0x14 holds (the mapped struct types it as a pointer; a character id is the other
reading); the function that writes the field would settle it.

## 3. Rules and algorithms

### 3.1 Start-up and world loading

`CLobby::StartUp(device, soundManager)` runs once from `CApplicationEx::Initialize` and creates, in this order
[known] S 004f8c90: animation selector, UI renderer (1024 × 1536), two render-setting blocks (main; portrait
with shadows and mirror off), shadow map, 13 `CGfxScene`, the four views, texture, shader and mesh managers,
renderer, camera, physics wrapper, object config, random generator, `bodyparts.xml`, `npc_bodyparts.xml`, pet
manager (`pets.xml`), avatar item list, snapshot maker, node tag table, PhysX initialisation, `lobbyobj.xml`,
`CLobbyClient`, item database pointer, text bubble renderer, `LobbyMenu::System`, `CLobbyScene`, the two fixed
textures, the seven portrait dummies.

`CLobby::LoadZoneTable("world1.xml")` then loads the world [known] S 004f57f0, S 00502380:

1. Reset the light-map bounds of all 32 settings entries.
2. For every child of `<world_scenes>`: read `file` and `scene_id_offset` and load that scene file (below).
3. Load every settings file named under `<world_settings>` (below).
4. Create the table spots: for zone 2 and zone 3, for tag number 0..14, read position and rotation of the node
   tagged `slot:<NN>_c` of that zone from the node tag table and create an object named `table<N>` of class
   `table<N>` in that zone (30 objects; no test whether the tag exists). [known: loop bounds in the disassembly
   at S 005024f9..S 00502706; 15 classes `table0`..`table14` with `selectionValue` 100..114 exist in
   `lobbyobj.xml`]
5. For each of the 13 zones: give its `CGfxScene` the bounds stored in its settings entry and build the 16 × 16
   culling grid.

Scene file (`scene_file` or `scene_objects` root; neither the root name nor the child element name is tested:
every child of the root is one object), per `<obj>` [known] S 00501b90, S 006e7980, S 006e7870:

- `name`, `type`, `scene` (int, default 0), `pos` (3 floats), `orientation` (3 floats, degrees; a fourth value in
  the file is ignored).
- `type` beginning with `sound:` (case-insensitive): the rest is a hexadecimal sound id; an emitter record
  {lower-cased name, id, `pos` as written, `scene` without offset} is appended. No object is created.
- Otherwise the lower-cased `type` is the object class and an object is created in zone `scene +
  scene_id_offset` at position **(−pos[2], pos[1], pos[0])** with rotation
  `Quaternion::FromEuler(orientation[2], orientation[1], orientation[0])` in radians. [known] S 00501b90
  With half angles a = `orientation[0]`/2, b = `orientation[1]`/2, c = `orientation[2]`/2 the quaternion is
  x = sin a · cos b · cos c + cos a · sin b · sin c,
  y = cos a · sin b · cos c + sin a · cos b · sin c, z = cos a · cos b · sin c − sin a · sin b · cos c,
  w = cos a · cos b · cos c − sin a · sin b · sin c, i.e. q = R_y(`orientation[1]`) · R_z(`orientation[2]`) ·
  R_x(`orientation[0]`) as a Hamilton product: the x turn is applied first, then z, then y, each about the
  engine axis of that name. [known for the formula, disassembly of S 006e8700; the product form is derived
  from it] All three angles are in use: 1758 of the 2026 objects of `scene1.xml` have a non-zero first or third
  angle (e.g. `-4.55927 -84.173 2.97835`). Emitter positions are **not** remapped: they are world coordinates
  as written. Cross-check from the data: the fireplace emitters of zones 2 and 3 lie about 31 units from their
  tavern's origin under this mapping, 88 and more without it.
- A class name that is not in `lobbyobj.xml` is not handled: `CLobby::CreateObj` passes the null result of
  `LobbyObjConfig::FindEntry` to the `CLobbyObj` constructor, which reads the class strings through it (access
  violation). Every `type` of the shipped scene files has its class. [known] S 004f6ca0, S 00502e60,
  S 00502a90; data `scene*.xml` against `lobbyobj.xml`

Settings file, per `<setting>` [known] S 005013b0: `scene` selects the entry (no range check); `fog_start`,
`fog_end`, `shadow_light_intensity` floats; `fog_color`, `ambient`, `diffuse` three floats (alpha forced to 1);
`light_dir` three floats, normalised; `light_map` texture name; `light_map_object` names an object of that zone
whose local bounds, transform and world bounds are copied (they define the light-map projection and the zone's
bounds).

### 3.2 Zones, doors and node tags

A zone is one `CGfxScene`. Zones share one coordinate system: an interior stands at the same place as its
exterior and is simply a different zone. [known: `scene_taverne02.xml` and `scene1.xml` give the same position
for `taverne02` and `taverne02_inside`] Shipped zones: **0** outdoors, **1** town hall interior, **2**
`taverne03` interior, **3** `taverne02` interior, **12** character selection stage
(`scene_customizeavatar.xml`, whose objects say `scene="0"`, loaded with `scene_id_offset="12"`;
`scene_skydome.xml` is loaded twice, with offsets 0 and 12); 0xf means "none". `world1.xml` names one settings
file, `scene1_settings.xml`, with entries for the zones 0, 1, 2, 3 and 12; `scene2.xml`, `scene2_settings.xml`
and `scene_gasthaus2.xml` are not referenced by it. [known] `world1.xml`, `scene*.xml`

Only the zone the camera is in is drawn, picked and heard (§4.2). An object is registered in its primary zone
and, while it stands in a doorway, also in a secondary zone. [known] S 005027f0

Door test, once per step for an object whose controller exposes a zone holder (vtable slot 3). Only the local
controller does (slot 3 returns the controller itself, vtable S 007e70e8); slot 3 of `CNetController` (vtable
S 007e70c0) and of `CStaticController` (vtable S 007e7098) returns null, so other actors and scenery never run
it. [known] S 005027f0, S 00504d60, S 00518a80:

1. Ask the active objects of the primary zone's scene in list order, the first hit wins:
   `CGfxObjStd::TestSceneTrigger(time, position)`. An object without a `scene_trigger` mesh never hits. After
   an AABB reject, the point is tested against the `scene_trigger` mesh, then against the `transition_area`
   mesh, in the object's transform.
2. Hit on the **scene trigger**: the old primary zone becomes the secondary zone and the object's `scene`
   attribute becomes the primary zone (the object has gone through the door).
3. Hit on the **transition area** only: the secondary zone becomes the object's `scene` (standing in the door:
   drawn on both sides).
4. No hit: secondary zone = 0xf.
5. The graphics object is moved between the `CGfxScene`s to match.

For remote actors the zone and the ghost zone are not computed but taken from the actor proxy with every
position sample (§3.5). The local controller's `zone` and `ghostZone` are what the position report sends as
`zone` and `ghstzne`. [known] S 00519b20, S 0051ace0

Node tags [known] S 00518e50, S 004fbcc0: every node name of a `node_hierarchy` that contains `pfx:` gets a
particle effect attached to that node (effect name = the node name from its fifth character on); otherwise a
name that contains `slot:` registers the node (tag = the name from its sixth character on) in the object's slot
map and in the global node tag table `[zone][number][slot]` (13 × 16 × 9 entries, zone = the object's primary
zone), where `number` is the two leading decimal digits of the tag and `slot` is the character at index 3: a
digit, or `c` for slot 8. Slot 8 is the
table anchor; the digit slots are the seat anchors of that table. [known for the indexing; that digits are seats:
inferred from `CMiniGameController::UpdateCamera` S 005269e0]

### 3.3 Collision and the PhysX world

`LobbyPhysics_Init` S 00500410 [known]: PhysX SDK 2.7 (`NxCreatePhysicsSDK(0x2070000)`), one controller manager,
one scene with gravity **−9.8** (that the component is y is [inferred] from its place in the descriptor),
timing `setTiming(stepSeconds × 0.25, 4 sub-steps)` with step = 0.083 s, three setters of the default material
called with **0.5** (restitution and both frictions [inferred: the slots were not identified]). A missing
PhysX runtime shows a message box and ends the process (exit code 1 or 2). `LobbyPhysics::Step` S 005003a0 simulates one step of 0.083 s after all objects
have been updated (§4.1).

Static geometry [known] S 005198c0, S 00522c80, S 00522410: a `CStaticController` of a class whose
`controllerclass` is `std` creates up to two static triangle-mesh actors from the graphics object's meshes:

- the collision mesh (`collision_mesh`, or the visual mesh when the attribute is absent, §2.4) → actor created
  with group argument **zone**;
- `collision_mesh_move` → actor created with group argument **zone + 16**.

That the argument becomes the shapes' PhysX collision group is [inferred] from the masks below: the decompile of
`CreateTriangleMeshActor` shows one 16-bit store into the group field of the `NxTriangleMeshShapeDesc`, but
attributes it to the mesh-id argument (§10 #14). The triangles are cooked with the PhysX cooking library into
a cache file `<local application data>\<folder>\<mesh name>_<model file>.phx` and cooked again when the
comparison of the write times of the model file and the cache is not negative. [known for the concatenation
and the test, S 00522410; the folder string at S 007d421c was not read; which side of the time comparison is
newer is inferred] A `file` attribute on `controllerparm`
would instead instantiate an NxuStream collection; no shipped class has one. [known] S 00522c80, `lobbyobj.xml`

The own avatar [known] S 005234c0, S 00523670, S 00523610: a PhysX capsule character controller, radius
**0.5**, height **1.0**, skin width **0.02**, step offset **1.0**, up axis y, created at the spawn position
raised by 1.0 (radius + height / 2); its actor's shapes are put in group 0x1f. The slope limit is
cos(1.0471975 rad) = cos 60° = **0.5** (double constant S 007e7760, loaded at S 0052358d). `Move(displacement,
groups)` calls the controller with minimum
distance **0.01** and sharpness **1.0**; the resulting collision flags are ignored. The pose returned to the
world is the controller position with y lowered by 1.0 (feet), plus the orientation last set.

The local controller moves with active groups `0x10001 << zone`: bit `zone` and bit `zone + 16`, so it
collides with both meshes of its own zone only. The camera's collision rays use only the low 16 bits, i.e.
`collision_mesh` but not the move-only mesh. [known] S 0051a1a0, S 0051a450

Other avatars, NPCs and pets have no collision. [inferred: only `CLocalController` creates a character
controller]

### 3.4 Local controller: input to movement

Input comes from `LobbyMenu::LobbyAction` (key state by virtual-key code; all keys are ignored while a text
widget has focus, except the forward key code 5) [known] S 004294a0..S 004296c0:

| Input | Keys | Tag |
|---|---|---|
| forward | W, Up, virtual key 5 | [known] S 004295c0 |
| backward | S, Down | [known] S 00429620 |
| turn left / right | A / D | [known] S 00429540, S 00429580 |
| sidestep left / right | Q or Left / E or Right | [known] S 004294a0, S 004294f0 |
| run | Shift | [known] S 00429670 |
| jump | Space | [known] S 004296c0 |
| mouse look | hold the right or the middle button (middle only while a table view sets button mode 1); the cursor is hidden and re-centred, x and y offsets accumulate | [known] S 00428fd0, S 00429360 |
| zoom | mouse wheel | [known] S 0051a840 |

Mouse-look yaw = accumulated x / (client width / 2) × 500; pitch likewise with the height; y can be inverted.
[known] S 00429030, S 00429080, scale set at S 00428e10 Mouse capture begins on the press of the right or the
middle button (button mode 1: the middle button only) and ends on its release; both clear the accumulators and
the release puts the cursor back where it was. The accumulators are also cleared at the end of every object
step, so a step sees the mouse travel since the previous step. [known] S 00429430, S 004290d0, S 004291c0,
S 004f58a0, S 00429220

One movement step (`CLocalController::UpdateMovementAndCamera` S 0051a840, once per fixed step) [known unless
tagged]:

1. Camera target key for slot 1 at the avatar position + (0, 2, 0), tagged with the controller's zone.
2. `turn` = −`TurnSpeed` if A, +`TurnSpeed` if D (both: 0). `TurnSpeed` is the tweakable `Lobby/TurnSpeed`,
   **30.0** in the image (range 0.1..100). S 0087cba4
3. `yawDelta` = mouse yaw; plus `turn` unless the middle button is down ("button down" in this list is
   `BaseAction::IsMiddleButtonDown` / `IsRightButtonDown`, slots +0x44 / +0x3c of the vtable S 007d6824).
4. Space sets the jump latch.
5. If the middle button is not down and forward or backward is held, the camera is pulled behind the avatar:
   `d` = (rig yaw − view heading) as an unsigned 16-bit angle (65536 = full turn).
   `d` < 0x8000: `yawDelta −= TurnSpeed × min(d, 0x800) / 2048` (for `d` > 0x800 the full `TurnSpeed`).
   `d` ≥ 0x8000: `yawDelta += TurnSpeed` if `d` < 0xf800, else `TurnSpeed × (0x10000 − d) / 2048`.
6. Rig update (S 00522f20), in this order: unless in close-up, `targetDistance += zoomSpeed × w`, with `w` the
   negated wheel delta of the cursor (`Cursor_GetNegWheelDelta`); current distance = the tween value while a
   tween runs, else the target distance (0.1 in close-up); target and current distance clamped to the limits;
   pitch += mouse pitch / 300; yaw += `yawDelta` / 150; roll = 0; pitch and yaw clamped;
   orientation = rotation(y, yaw) · rotation(x, pitch). Close-up is on when
   the tweakable `Lobby/FirstPerson` is set and the avatar has a ghost zone (secondary zone ≠ 0xf); toggling it
   tweens the current distance over **500 ms** to 0.1 (on) or back to the target distance (off).
   Rig constants of the walking camera: start distance **5.0**, zoom speed **0.75**, distance **0.1..10.0**,
   start pitch and yaw 0, pitch **−π/4..+π/4**, yaw unlimited (±3.4028235e38). S 0051a1a0, S 00522e60 The π/4
   is the global S 0088f1fc, which is 0 in the image and set to π/2 × 0.5 by the static initialiser S 007cb260.
7. View heading: the rig yaw while the right button is down; otherwise view heading += `turn` / 150 (0.2 rad
   per step, about 2.4 rad/s, at the default speed).
8. Camera collision (below) and the orbit key for slot 1: rig orientation, corrected distance.
9. Move heading = view heading. Exactly one of the sidestep keys held: move heading −/+ **π/4** with forward,
   −/+ **3π/4** with backward, −/+ **π/2** alone (left is minus), and the move direction is forward.
10. Move vector in the avatar's frame: (0, 0, +1) for forward (also together with backward) or exactly one
    sidestep key, (0, 0, −1) for backward without those, else zero. Speed factor **0.5**, with Shift **1.0**.
11. Non-zero: normalise, scale, rotate by rotation(y, move heading); `moving` = true, `running` = Shift held.
    Zero: `moving` = `running` = false.
12. Orientation of the character = rotation(y, move heading). Displacement y −= **0.5** (constant pull to the
    ground in every step, moving or not; there is no jump arc; the store is at S 0051acb1).
    `Move(displacement, collisionMask)`.

Resulting speeds: 0.5 units per 83 ms step = about **6.0 units/s** walking, **12.0 units/s** running.
[inferred from the step length] The jump is an animation only (§3.6).

Camera collision (`ComputeCameraCollisionDistance` S 0051a450) [known]: with the own character's collision
switched off, 8 rays are cast from points on a circle of radius 0.5 around the camera target, perpendicular to
the view direction, along the view direction. Each hit gives `hitDistance − CameraCollisionDistance` (tweakable
`Lobby/CameraCollisionDistance`, **0.1**, range 0..2), at least 0.01; the smallest value, capped by the rig's
current distance, is the orbit distance. The rays test the groups in the low 16 bits of the collision mask and
have no length limit. [inferred for the cap and for the exact ray origins: the decompile shows neither the
initial minimum nor the x87 return cleanly]

Position report (`ProcessInputAndSendLocation` S 0051ace0, every step after the movement) [known]: the step
counter is incremented; `CLobbyClient::SendAvatarLocation(now, pose, move heading in degrees, zone, ghostZone,
send, running, jump)` is called every step, with `send` = true on every 4th step (about every 332 ms, 3 per
second) and only when the context has a client. The jump latch is cleared only after a step that sent. The
client method does nothing in lobby mode 2 or without a logged-in village connection; otherwise
`VillageServerConnection::SendAvatarLocation` S 0046ca40 mirrors pose, heading, zone and ghost zone into the
own `AvatarProxy` every step and sends message **2000** when `send` is set. S 005034e0 Layout and quantisation:
[`../village-and-character-protocol.md`](../village-and-character-protocol.md) §4.2.

### 3.5 Net controller: other avatars and NPCs

Sample intake (`CNetController::PushActorSample(time, proxy)` S 00519b20, called by `CLobbyClient::UpdateAvatar`
for every avatar-data notification with `time` = `ActorProxy::GetLastTick`; that this is the 16-bit wire tick
expanded to the client clock is taken from the protocol document §4.2, not re-read here) [known]:

- A position equal to (0, 0, 0) is ignored.
- Otherwise `headIndex = (headIndex + 1) mod 8` and that slot gets: position, rotation quaternion, the proxy's
  running and jump flags (`proxy + 0xd8`, `+0xd9`), and `timeMs = time + 2000`. The controller's zone and ghost
  zone are set from the proxy. `bHasSample` = true.

Per step (`CNetController::Update` S 00519d50) [known]:

1. `interpMode` ≠ 1 (not a player avatar): the pose is sample slot 0, which the constructor seeded with the
   spawn pose; such actors never move. [known; that NPCs get no samples: inferred]
2. Otherwise search 7 consecutive ring pairs (a, b), oldest first, for `a.time < now ≤ b.time`.
3. Pair found: if `b.time − a.time` > **2.0 s**, or `a.pos` is (0, 0, 0), or the distance |b − a| ≥ **10.0**:
   snap to sample b (pose and flags of b). Otherwise position = linear interpolation, rotation = slerp at
   `(now − a.time) / (b.time − a.time)`; `running` and `jump` are the OR of both samples.
4. No pair: the pose is the newest sample; if `now − newest.time` > **3.0 s** (unsigned 64-bit difference, so a
   newest sample that still lies in the future also counts) the object is hidden for this step.
5. `moving` = output position differs from the previous output position. The first output after activation
   does not count as moving.
6. Animation by the common rule (§3.6), then visibility and pose go to the graphics object.

Activation of a player's net controller clears the ring, `bHasSample` and `bInitialized`; the `CLobbyObj`
constructor activates the controller right after creating it, which discards the seeded spawn pose. An avatar
that has received no sample since outputs (0, 0, 0) and is hidden by the 3 s rule (its newest time is 0).
Actors of another type keep the seeded slot 0. [known] S 00519ab0, S 00502e60 The 2000 ms offset
is a fixed playback delay: the server must stamp positions so that, after the offset, they bracket the client's
clock (the rule and its live verification: protocol document §4.2).

### 3.6 Avatars

**Model.** `UpdateAppearance(preview)` S 00508090 [known]:

- Player (actor type 1): body-part set = gender (0 male, 1 female); variant = `tribe + (level − 1) × 3` with
  level clamped to 1..5 (0 counts as 1) and tribe 0..2 (anything else counts as 2). Catalogue:
  `bodyparts.xml`.
- Other actors: body-part set 0, variant = the actor's model index (vtable +0x1c); catalogue
  `npc_bodyparts.xml` when the avatar object was created for an NPC. The choice of catalogue and why only the
  male set is reachable: protocol document §5.1.
- If set or variant changed: the animation objects are rebuilt (same animation state re-entered), the three
  item slots and the pet are cleared.
- The eight colour indices (hair, skin, shirt, trousers, four additional; `AvatarProxy + 0x49..+0x50`) are
  compared with the cached ones; the 256-row palette is rebuilt: the variant's colour map (`slotMap`) fills the
  palette, then for channel i = 0..7 the ramp `slot<i>` of that colour map gets the colour set `index mod set
  count` copied into its row. The palette is uploaded to a shared palette atlas. S 004fcc90, S 004fcc10
- Players only: the equipment containers of the proxy are synchronised (below); in preview mode only head and
  left hand, and the right-hand slot and the pet are cleared.

The protocol document names the two style inputs `bodypart` and `tribe`; they are the values called tribe and
level here. `bodyparts.xml` orders its 15 heads per set as level 1 (bavarian, scot, egypt), level 2, ... and
labels them so. [known] `bodyparts.xml`

**Items.** `SyncEquipmentSlot` S 00507f60, `AttachItem` S 00507ca0 [known]:

| Container type | Visual slot | Bone | Content |
|---|---|---|---|
| 2 | 0 | `Bip01 Head` | head item |
| 4 | 1 | `Bip01 L Hand` | left-hand item |
| 3 | 2 | `Bip01 R Hand` | right-hand item |
| 5 | 3 | (none) | pet |

An empty container (item id 0 or count < 1) clears the slot; the same item is kept; otherwise the item's mesh
name (token 6 of `ItemsClient.txt` [inferred: the token number was not re-read]) is attached. For slots 0..2
the key `<mesh name>_<Tribe>_<Gender>` with `Bavarian` / `Scot` / `Egypt` (tribe 0 / 1 / 2) and `Male` /
`Female` (gender 0 / 1; string tables S 0087c800, S 0087c7f8) is looked up in `avatar_items.xml` and its
`.KEX` mesh is loaded with scale 1.2 and bound to the bone (bone names: table S 0087c7e8). For slot 3 the mesh
name is a pet type name of `pets.xml`. The right-hand item (slot 2) is not drawn while a non-exclusive overlay
(an emote) plays; the jump overlay is exclusive and does not hide it. [known] S 0050e6a0, S 00507060,
S 00506530

**Pets.** A pet is a separate animated model that follows its owner's trail [known] S 005061d0, S 00505e70,
S 005060a0, S 004fe080:

- Every pose sample of the avatar pushes its position into a breadcrumb ring of 16 points spaced **0.5**
  apart; `speed` = distance moved per sample / 0.5 (only when the avatar moved more than 0.01).
- The pet's cursor on the trail is a 4.16 fixed-point index. Lag = head − cursor (in points). The pet starts
  moving when lag > 6 and stops when lag < 5; while moving, the cursor advances by `speed` points per sample.
- Position = Hermite spline at the cursor; heading = towards the spline point 1.9 points ahead.
- Animation: state 0 (`Stand`) while its position is unchanged, state 1 (`Walk`) otherwise, at the avatar's
  animation speed (1.0 when standing).
- The pet is drawn only while the dword at `ActorProxy + 0x80` is 0 (or there is no proxy). [known] S 00507060,
  getter S 004683d0 The mapped struct names that field `seatedMiniGame`: no pet while the owner sits at a
  table. [inferred from the field name; its writer was not read]
- The speed is not reset when the avatar stops; the pet halts through the lag rule alone. [known] S 00505e70

**Animation.** Each body-part set has an animation graph `[data]/config/<set name>_animation_graph.xml`
(states, zero-time transitions, overlays, random idles; §6.2). Graph and animation model are built with the
factor **1.2** in the argument that carries the `scale` of `pets.xml` for pets, i.e. avatars are scaled by 1.2.
[inferred] S 00506e10, S 004fe5c0
`ILobbyObjController::UpdateAvatarAnimation(moving, running, jump)` S 00511250 chooses per step [known]:

| Situation | State | Speed |
|---|---|---|
| standing, player | `anim_idle` of the `<avatar itemid>` entry of `anim_selector.xml` for the right-hand item id | 1.0 |
| standing, other actor | `anim_idle` of the `<npc npcindex>` entry for the actor's model index | 1.0 |
| moving, player | `anim_walk` of the item entry | **1.5** walking, **3.0** running |
| moving, other actor | `Walk` | 1.5 / 3.0 |
| jump flag set | additionally the exclusive overlay `Jump` | |
| customise stand, portraits | `CustomizeStand` | 1.0 |
| seated at a table | set by the minigame controllers (`SitChair` exists in the graph) | [inferred] |

State and speed are sent to the animation model only when they change. The idle and walk state ids start as
`Stand` and `Walk`; an actor without a proxy keeps them. The player's item id is read from the equipment
container at `AvatarProxy + 0x8c + 0x10`; that this is the right-hand container is [inferred] from the order
in which `UpdateAppearance` synchronises the four containers. Selector indices: NPC entries 0..63, item
entries from 64 on. S 00500aa0 A state with `<randoms>` plays one of its random sources after a random delay
in [`minDelay`, `maxDelay`] seconds, drawn from a shuffled weighted bag; the delay is counted down only when
the state animation completes a loop, so a random source starts at a loop boundary. S 0051ea30, S 0050ec80
Overlays (emotes, jump) play on top of the state and end by themselves when their remaining time reaches 0;
the state is then entered again. S 0050ec80

**Emotes and chat text.** `CGfxObjAvatar::ShowChatText(text)` S 005079b0 [known]:

1. The candidate word starts after the first `/` of the text, or **at the start of the text when it has no
   `/`** (`find` returns −1, plus 1 = index 0), and ends before the next space or at the end. If it is not
   empty it is lower-cased and tried as an emote name; if the emote starts, no bubble is shown. A message whose
   first word is an emote name therefore plays the emote and shows no text: `laugh`, `dance with me`,
   `well /bow`.
2. Otherwise the text becomes the bubble text and `textOpaqueUntil = t + (length + 10) × 75 ms`, with `t` the
   avatar's last update time (nothing happens before its first update).

An emote (`emotes.xml`, loaded once; the element name, lower-cased, is the emote name) has an optional `sound`,
an optional `anim` (overlay name of the graph) and a `text` key; its duration comes from the sound and the
animation length [inferred: that it is the longer of the two was not re-read]. Starting it plays the sound at
the avatar's position at volume 255 and the overlay (not exclusive). S 00506610, S 0051c710 Shipped emotes:
`laugh`, `dance`, `applaud`, `cry`, `bow`, `monkey`, each with `anim` and `text` and without `sound`. [known]
`emotes.xml`

**Name tag and bubble.** Per frame, in pass 0 [known] S 00507060, S 00507580, S 00506860, S 00505c10:

- `fade = (fontFadeEnd − distance) / (fontFadeEnd − fontFadeStart)`, with `fontFadeStart` **18.0** and
  `fontFadeEnd` **25.0** (tweakables); zero or negative: nothing is drawn; above 1: 1.
- While `now < textOpaqueUntil` and a bubble text exists: the bubble. Else the name. The text item is sorted on
  top of everything (key 0xffffff) while `now < textOpaqueUntil` or the fade is 1, otherwise by distance.
- Anchor: avatar position + **2.4** in y, **2.7** with a head item.
- Name: the actor's name, not drawn for the own avatar, centred, alpha = fade, colour by relation and state:

| | plain | hovered | selected |
|---|---|---|---|
| player | 0xFFB4B4FF | 0xFFD4D4FF | 0xFFFFFFFF |
| relation 1 (friend [inferred]) | 0xFF00FF50 | 0xFF40FF90 | 0xFFFFFFFF |
| relation 2 (ignored [inferred]) | 0xFFFF9600 | 0xFFFFC630 | 0xFFFFFFFF |
| NPC (actor type 2) | 0xFF7BDDAE | 0xFFFFFFFF | 0xFFFFFFFF |

  (ARGB dwords, table S 0087c80c.)
- Bubble: rich text laid out to at most 200 × 400 pixels at the projected anchor, offset by (**37**, **−27**)
  pixels (`bubbleOffsetX`, `bubbleOffsetY`), depth bias **−3.0** (`TextBubbleBias`); the frame is drawn by
  `TextBubbleRenderer` with the text box's width − 8 and height − 12.
- Together with that text item, a hovered or selected avatar other than the own one gets the selection ring
  (half size 1.0, 0.1 above the ground).

The avatar is faded in near the camera: `fade = (distance − 1.0) / 2.5` clamped to 0..1; at distance ≤ 1.0
nothing of the avatar is queued: no body, name, bubble, pet or items (except in views flagged 0x1000, where
the fade is 1). An avatar with flag 0x20 is skipped the same way. [known] S 00507060 The renderer sorts the
queued avatars by distance and walks the list once, raising the LOD from 0 to 1 and from 1 to 2 when the rank
reaches a count limit or the distance passes a border; the limits are 10 for LOD 0 and 20 / 50 / 100 for LOD 1
by the "object details" option 0 / 1 / 2. [known] S 00509140, S 00509110, S 005006e0 [TODO] not established:
the two distance borders (`avatarLodBorder0`, `avatarLodBorder1`; read the `CGfxRenderer` constructor).

**Customise stand** (`CustomizeAvatarController` S 0051af50) [known]: while mouse look is active the mouse-look
yaw, truncated to a 16-bit integer, is added to the yaw (16-bit angle) each step; otherwise the yaw returns to
0 by 0x152d per step on the shorter side. Rotation = base rotation · rotation(y, yaw / 32767.5 × 3.141596)
(the constant is written that way in the image).

### 3.7 Camera

Controllers feed keys into the slot of their mode; the camera evaluates the slot of its current mode at the
frame time (§2.6). `CLobby` applies `viewMode` to the camera at every object step when it is non-zero. [known]
S 004f58a0

| Mode | Fed by | Rule | Tag |
|---|---|---|---|
| 1 | `CLocalController` | §3.4 | [known] |
| 2 | `CMiniGameController`, own seat | seated rig, keys with slot 2 | [known] S 005269e0 |
| 3 | `CMiniGameController`, watching | target = table anchor (slot 8 node) + 1.5 in y; orbit distance fixed **1.0**; orientation = anchor rotation · rig orientation; the rig's distance value is not a distance here but the camera's `fovScale` (start 1.0, wheel speed 0.25, range 0.4..1.0). Rig: pitch start 1.5009832, pitch 0.2617994..1.5009832 rad, yaw start π/2, yaw ±62.831856 rad | [known] S 00526800, S 005269e0 |
| 4 | camera itself | target (0, `camLookAtY` **7.0**, 0), zone 12; orientation rotation(y, π) · rotation(x, `cameraAngleX` **16°**); distance `cameraDistance` **4.0**; fov 64°; the projection is shifted by the tweakables `Customize Camera X/Y Offset` | [known] S 004ff420, S 004ff350, S 0087c714 |
| 5 | camera itself | preset by `presetIndex`, zone 0, distance 0.1, yaw swaying by `sin(t / 28 s) / 6` rad around the base yaw | [known] S 004ff420 |

Mode 5 presets [known] S 004ff420:

| Preset | Target (x, y, z) | Pitch (rad) | Base yaw (rad) |
|---|---|---|---|
| 0 | (−24.69, 2.3523, −55.851) | 0.004340168 | −6.0763054 |
| 1 | (−7.2585, 4.6376, −45.7567) | −0.03906264 | −6.701304 |
| 2 | (−41.2425, 4.738, 8.8378) | −0.14322917 | −5.4882812 |

Switching from mode 4 or 5 to walking: in the first tick in which a local avatar object exists, no customise
preview exists and the camera mode is 4 or 5, the clocks are resynchronised, selection is enabled and `viewMode`
becomes 1. [known] S 004fb230 `SetViewMode` callers: 1 on leaving a seat or ending observation, 2 on taking a
seat, 3 on observing, 5 when the world is left or the connection closes; 4 is set by `EnterCustomizeMode`.
[known] S 004f5200, S 004f71d0

### 3.8 Picking, selection and the action it triggers

`UpdatePickingAndSelection` S 004f6190, once per rendered frame after the main pass [known]:

1. Build the pick ray from the cursor position.
2. Selection disabled: clear the hover object and stop.
3. If nothing is selected, or the selected object is farther than `maxSelectionDistance + 2.5` (27.5) from the
   first three floats of the pick ray, or neither of its zones is the current zone: select the own avatar
   (which may be null). [known for the test and the operand `ctx.pickRay`; that those floats are the ray origin
   is [inferred] from `BuildPickRay`'s output layout]
4. Zones 0..10 only: a physics ray along the pick ray is cast first (use of its result [TODO]: the decompile
   drops the arguments). The own avatar is excluded from picking unless a distance exceeds 3.5; that the
   distance is between the camera eye and the avatar position + (0, 2, 0) is [inferred] from the calls around
   it. `CGfxScene::PickClosestObject` returns the nearest object of the current zone
   with flag 0x10000 whose ray test hits closer than `maxSelectionDistance` (25.0; tweakable
   `Lobby/MaxSelectionDistance`, range 0..100). [known] S 00504e00 In the zones 11 and 12 nothing is picked.
5. Hit: if a click is pending it becomes the selected object; it becomes the hover object.
6. No hit: hover is cleared; a pending click ends a UI drag in state 3 if there is one (the function then
   returns without clearing the click latch), otherwise selects the own avatar.
7. The click latch is cleared. It is set by a left click on the world while selection is enabled. S 004f5420

Selection and hover only set flags 8 and 4 on the graphics object (ring, name colour). What happens next is
decided by the world screen, which reads [known] S 004f5370, S 004f5e40:

- the selected actor's proxy (player or NPC), or
- for a scene object: its zone and its `selectionValue`: **1** = letterbox, **100 + n** = table spot `n`.

The mapping of those to action codes, the automatic dispatch for an NPC with one action and the dialogs are in
the protocol document §5.2 and §6.4. The dialogs opened there register a distance watch (§3.10).
`SetSelectionEnabled(false)` is how dialogs freeze the selection. S 004fad00

### 3.9 Portraits and the character stage

- Seven `snapshotavatar` objects exist from start-up. After the main pass, if the selected object has a player
  proxy, portrait slot 0 is rendered: only that slot's dummy is visible, it takes the proxy's look
  (`UpdateAppearance` in preview mode: no right-hand item, no pet) and the `CustomizeStand` state at speed 1.0,
  names and bubbles are switched off, the portrait render settings are applied and the aux view renders with
  the render mask | 0x1000 into the snapshot target on a (0.5, 0.5, 0.5, alpha 0) background; `snapshotStatus`
  = 1, else 2. [known] S 004f9960, S 004f7fd0 The targets are square, 256 pixels (slot 0) and 512 pixels
  (grid). [known] S 004fc250
- Slots 1..6 are drawn into the second target as a grid of cells of 512 / 3 = 170 pixels, cell (column, row) =
  (i mod 3, i / 3) for i = 0..5: three columns, two rows; a null avatar entry clears its cell. [known]
  S 004f82a0
- Portrait camera: fov 0.87266463 rad (50°), near 0.1, far 100; target = actor position + (xt, 1 + yt, zt),
  eye = target + actor rotation · 4 · (x, y, z) from the tweakables `Lobby/Snapshot x`, `y`, `z`, `xt`, `yt`,
  `zt`. Image defaults: x = y = xt = zt = 0, z = **0.6**, yt = **0.6**, i.e. target 1.6 above the feet and the
  eye 2.4 in front along the actor's z axis. [known] S 004fc250, S 004fbeb0, S 0087c66c, S 0087c670
- Character stage (zone 12, objects `map`, `bg0`..`bg2`, `bgcreation`): `ApplyCustomizeAvatarLook(avatar,
  showTribeBackground)` shows `bg<tribe>` alone when the flag is set, else `bgcreation` alone. [known]
  S 004f84b0; object names `scene_customizeavatar.xml`

### 3.10 Distance watches

`AddDistanceWatch(radius, callback, userData)` stores the own avatar's current position and returns an id (−1
without an avatar). Every tick in which an own avatar exists each watch is tested against its position; when
the distance is not below the radius (≥) the callback is called with (id, distance, radius, userData) and the
watch is removed.
`CancelDistanceWatch(id)` removes one. [known] S 004fb5f0, S 004fad20, S 004f6850

### 3.11 Rendering rules that affect what is seen

- Per frame the zone's settings give fog range, background (= fog) colour, ambient, one directional light and
  the light-map projection. [known] S 004f9960
- Passes: shadow map (only if the shadow option ≠ 0), water reflection into a 256-pixel view with the clip plane
  at y = −0.1 and reversed culling (only if the mirror option = 1), main pass. [known] S 004f9960
- `CGfxObjStd`: beyond `fadeout_end` nothing is drawn; between `fadeout_start` and `fadeout_end` the opacity
  falls linearly from 1 to 0. A pickable object also queues its selection decal. [known] S 00518b70
- An object is drawn only if its render-mask bit is in `CLobby.renderMask`. [known] S 00504b20
- Graphics options (`SetLobbyGraphicsOptions` stores them, `LobbyRenderSettings::Apply` applies them at the
  start of every frame): shadow quality 1 / 2 / 3 → shadow map quality 0.5 / 0.75 / 1.0, any other value 0
  (and no shadow pass at 0); shader detail = 1 sets the second lighting flag of the shader manager; mirror = 1
  enables the reflection view; texture quality 0 → texture reduction level 1, else 0; object details 0 / 1 / 2
  → `rmBuildingMinor` off / off / on, `rmVegetationMinor` off / on / on, and the avatar LOD limits of §3.6.
  [known] S 004f5290, S 005006e0, S 004f9960 That reduction level 1 means one mip level smaller is [inferred]
  from the function summary of S 005043e0.
- The portrait pass uses a second settings block: shader-detail flag off, shadow level 0, mirror off; texture
  quality and object details follow the options. [known] S 004f8c90, S 004f5290

### 3.12 Billboards and web textures

`CGfxTextureMgr::GetTexture` creates every texture on first use from its file name, except three names:
`ad0.tga`, `ad1.tga`, `ad2.tga` become 1024 × 512 textures filled by `url2tex` from
`http://www.funatics.de/sadk/forwarding1.html`, `…2.html`, `…3.html`. [known] S 00504650 `url2tex` hosts an
Internet Explorer control per texture; on DocumentComplete the page body is drawn into the texture's level-0
surface, on NavigateError the texture is cleared to red. [known] S 005c8a30, S 005c7ba0 The two boards stand in
zone 0 (`scene_ad.xml`, classes `ad0`, `ad1`). The Hall of Fame dialog uses the same mechanism with the URLs of
`LobbySettings.ini`. Details and the replacement mod: [`../BINARY_PATCHES.md`](../BINARY_PATCHES.md)
("Billboards").

### 3.13 Sound and music

- Listener: position = own avatar's position (origin without one), forward = camera orientation · (0, 0, 1), up
  (0, 1, 0), velocity 0. Installed as the sound manager's listener while the lobby mode is 2 or 3. [known]
  S 004f9960, S 004f56c0, S 004f5950
- Ambient emitters: active only in camera modes 1, 2, 3 and lobby mode 3, for zones 0..3: when the modes are
  entered or the camera zone changes, all started emitters are removed and those of the new zone are added.
  [known] S 004f9960, S 004f5480 Emitter mechanics: [`audio.md`](audio.md) §3.4.
- Music: on a camera zone change in lobby mode 3: zone 0 → menu music group 5, zones 1..3 → 6, other → 0.
  [known] S 004f5430
- Emote sounds: §3.6. NPC and minigame sounds (`sound/npc`, `sound/minigame*`) are started by the UI and the
  minigame code, not by the world. [inferred]

## 4. Update order

### 4.1 Per frame: `CLobby::Update(now, cameraActive)` S 004fb460 → `Tick` S 004fb230 [known]

`Update` runs in every lobby mode (the application calls it from both frame ticks, [`app-shell.md`](app-shell.md)
§4); only steps 1 and 8 depend on the mode.

1. Store `cameraActive` in the context (`ctx + 0x84`, read by `ResyncTime`); set the global animation time
   scale S 00884a6c to 1.0. In lobby mode 2 or 3, if a sound manager exists: `SoundManager::Update` (listener
   and FMOD).
2. `nowMs = now`. `CLobbyClient::Update` S 00503fc0: `LobbyManager::StatePump_Tick` (all network delivery,
   including the village connection's event queues, runs here); a connection flagged for release is
   unsubscribed and dropped; the re-enter timer is counted down (§5.2).
3. Camera hand-over to walking mode if due (§3.7).
4. If `now − nextStepMs` > 1000 ms (signed 64-bit): `nextStepMs = now`, dirty.
5. While `nextStepMs < now`: `nextStepMs += stepMs` (83); **object step** at `nextStepMs` (below).
6. If dirty: one more object step at `nextStepMs`; clear dirty.
7. Camera `lastTime = now`; distance watches.
8. Lobby mode 2 or 3: `LobbyMenu::System::Update(stepped)`, `stepped` = an object step ran in step 5 or 6.
9. Compose `renderMask`; register the eight `Lobby GfxSettings/rm*` tweakables on the first call
   (S 004f5f20); if the device state (`device + 0x10c`) is 1 (lost) try to restore it, else
   `RenderFrame(now − lastFrameMs, now)`.
10. `lastFrameMs = now`.

Object step (`CLobby::RenderObjects` S 004f58a0, a misnomer: it is the fixed-step update) [known]:

1. `viewMode` ≠ 0: camera mode = `viewMode`, preset index = `CLobby + 0x80`.
2. Lobby mode 3 with an own avatar: `JoinZoneChatChannel(avatar's zone)` (no-op unless the zone changed).
3. A call pair on the physics wrapper: PhysX scene virtual +0x1d4 with (1, 1, 0), then controller manager
   virtual +0x14. [known] S 005002b0 [TODO] not established: which PhysX methods these are (no symbols; the
   SDK headers of the shipped PhysX version would settle it).
4. For every object in array order: controller `Update(time, gfxObj, &position)` → door test (§3.2) →
   controller post-step, virtual +8 (local controller: input, movement, position report). [known] S 005029e0
5. `LobbyPhysics::Step`: scene virtual +0x1cc with `stepMs` / 1000 seconds (0.083), then scene virtual +0xe0.
   [known] S 005003a0
6. Two dwords of the `LobbyAction` singleton (+0xd20, +0xd24) are set to 0. [known] S 00429220 [inferred] they
   are per-step input accumulators (the mouse-look deltas of §3.4).

Poses are handed to the graphics objects as timed samples at the step time; rendering evaluates them at the
frame time between the last two samples, so movement is smooth at any frame rate. [inferred] S 00504060,
S 00510c80 After a resynchronisation or a controller activation the interpolators are reset instead.

### 4.2 `RenderFrame` S 004f9960 [known]

Camera preset keys → camera zone (`interpState[mode]`) → listener → zone music (lobby mode 3, zone changed) →
ambient emitters (camera mode 1..3, §3.13) → `currentZone` → settings of the zone (light-map matrix, fog,
background colour, ambient, directional light) → shadow pass (only when the shadow option is not 0) →
reflection pass (only when the mirror option is on) → main pass of the zone's `CGfxScene` → picking and
selection → debug overlays → UI (`LobbyMenu::System::Render` in modes 2 and 3, else the main menu's render;
both only while the tweakable `Lobby/Show Menu`, S 0087c628, image default 1, is set) → present → selection
portrait (only when the device is not lost and an object is selected, §3.9).

### 4.3 Mode transition: `ProcessModeTransition` S 004f5950, once per frame after the tick [known]

Nothing happens while `requestedMode` is −1.

- 0 / 1 → 2 / 3: `ResyncTime` (below), `bAmbientSoundsActive` = 0, install the listener, hide the game UI and
  menu, activate the lobby UI and `LobbyAction`.
  - Request 2: create the local avatar at once at the default spawn (−31.24, 2.71, −8.28), heading 0, zone 0,
    ghost zone 0xf (§5.2), request lobby screen 3 and run `LobbyMenu::System::Update(true)`.
    [known] constants S 007dd028, S 007dd02c, S 007dd06c, S 007db52c
  - Request 3, by the `LobbyManager` state (enum `LobbyManagerState`):
    - Authorized (3) or VillageLeft (11), coming from mode 1: `FindBestVillageServer(client protocol version,
      cached village server id)`. Found: select the character whose id is the local permanent id, select
      that server, `RequestEnterVillage(false)`; no screen is requested. Not found (−1): select the
      character, request screen 2.
    - Authorized or VillageLeft, coming from mode 0: request screen 2.
    - Disconnected (1): request screen 1, `LobbyMenu::System::Update(true)`, open the login dialog.
    - any other state: `LobbyManager::Logout`, then as for Disconnected.
- 2 / 3 → 0 / 1: `ResyncTime`, remove the listener, destroy the local avatar object, `viewMode` = 5, dirty,
  preset 0, lobby screen 0 with `LobbyMenu::System::Update(true)`, hand input back to the game action,
  deactivate the lobby UI, show the menu again; request 1 activates the game screen, request 0 the main
  screen.
- After either branch: `prevMode ← curMode`, `curMode ← requestedMode`, `requestedMode ← −1`.
- **Any other pair** (0 ↔ 1, 2 ↔ 3, or a request outside 0..3) returns without doing anything and **without
  clearing the request**; as `RequestModeTransition` only latches while none is pending, the lobby then accepts
  no further mode request. [known] branch targets at S 004f596b..S 004f599b [TODO] not established: whether
  any caller issues such a request (list the callers of vtable slot +0x2c and their arguments).

`ResyncTime(now)` S 004f5d90 (vtable +0x18) [known]: dirty, `nextStepMs = nowMs = now`, virtual +0x30 of every
object's graphics object is called (the interpolation reset of §4.1 [inferred]), and the camera interpolators
are reset if `cameraActive` was true in the last `Update`. Initial state from the constructor: `curMode` 0,
`prevMode` and `requestedMode` −1, `viewMode` 0. [known] S 004fb100

### 4.4 On load

Start-up and world loading: §3.1. Textures, meshes and physics caches are created on first use.

## 5. Inputs and outputs

### 5.1 Interfaces

| Other subsystem | Direction | Interface | Tag |
|---|---|---|---|
| application shell | in | `CLobby` vtable: `StartUp`, `LoadZoneTable`, `Update`, `ProcessModeTransition`, `RequestModeTransition`, input sinks `OnKeyDown/Up`, `OnMouseMove/Wheel/ButtonDown/Up` | [known] S 004f4f10..S 004f5010 |
| lobby UI | both | `GetSelectedObjectInfo`, `GetSelectedActorProxy`, `SelectLocalAvatar`, `SetSelectionEnabled`, `AddDistanceWatch`, `EnterCustomizeMode` / `LeaveCustomizeMode`, `ShowCharacterPreview*`, `RenderAvatarSnapshotGrid`, `GetSelectionSnapshotTexture`, `WorldToZoneNormalizedCoords` (minimap), `ApplyToActorLobbyObject` (NPC speech), `RequestEnterVillage`, `RequestExitVillage`, `RequestReenterVillage` | [known] by address in §11 |
| village connection | both | `CLobbyClient` (§5.2) | [known] |
| chat connection | in / out | chat lines → bubbles; zone → chat channel | [known] S 00503200, S 004f58a0 |
| sound | out | listener, emitters, music group, emote sounds | [known] §3.13 |
| item database | in | item id → mesh name | [known] S 00507f60 |

### 5.2 `CLobbyClient`: which message drives which change

`EnterVillage(useDefaultSpawn)` creates the `VillageServerConnection` (server id −1), subscribes to its
observer lists and calls the connection's `OpenUserComm` with one dword: normally the selected character's id
(`CharacterManager + 0x98`), after which `bUseDefaultSpawn` is stored and `bHasSavedPosition` cleared; while a
re-entry is pending the dword kept at `CLobbyClient + 0x14` instead, with `bUseDefaultSpawn` = 0 and the saved
position kept. [known] S 00503f50, S 00503d00, S 00472200 `UnsubscribeVillageConnection` S 00503ab0 removes the
same subscriptions. Message layouts and server flows: [`../village-and-character-protocol.md`](../village-and-character-protocol.md) §3..§7 and
[`../message-catalog.md`](../message-catalog.md).

| Message (village) | Observer list → handler | Change in the world | Tag |
|---|---|---|---|
| 1000 EnterWorld | +0x104 → `OnEnterWorld` S 00503940 | create the own avatar object (below); lobby screen 3 unless re-entering; subscribe to chat lines | [known] |
| 1001 AvatarData | queue → +0xbc → `UpdateAvatar` S 00503620 | proxy without an object: create a `settler` object at the proxy's position, rotation and zone (`& 0xf`) and bind it to the proxy; no sample is pushed for this first message (the controller starts from the spawn pose). Proxy with an object: push a sample (the proxy's last tick, §3.5) to its net controller. Both cases end with `UpdateAppearance`. A failed creation logs `Could not create CLobbyObj.` and returns | [known] S 004f6de0 |
| 1002 AvatarLoggedIn | queue → +0xa4 → no-op S 00472360 | none | [known] S 00503d00, S 0046fde0 |
| 1003 AvatarRemove | queue → +0xb0 → `OnAvatarRemoved` S 00503170 | if the proxy has an object: destroy it (selection and hover cleared first, S 004f5ce0) and clear the proxy's object pointer. The same list is fired directly for every avatar when the connection clears its avatar map (S 0046fab0) | [known] |
| 1004 NPCData | +0x38 (direct, not queued) → `OnNPCAdded` S 005031a0 | only if the proxy has no object yet. NPC kind (`NPCProxy + 0xc4`) 1: `settler` object; kind 2: `letterbox` object; other kinds: none. Name, position, rotation and zone (`& 0xf`) from the record; a later 1004 for the same NPC changes nothing in the world | [known] S 004f6ea0, S 0046f8c0 |
| (NPC list cleared, S 0046fc10) | +0x44 → `OnNPCRemoved` S 005031d0 | destroy the object and clear the proxy's object pointer | [known] |
| 1005 WorldTick | +0x11c (direct) → `OnWorldTick` S 00503590 | `Timer_SyncElapsedToServerTick16(tick, 250)` S 0057b910: compare the low 16 bits of the application's elapsed milliseconds with the 16-bit server tick; if the shorter distance modulo 65536 is 250 ms or more, shift the clock's start so that the low 16 bits equal the tick (elapsed time stays ≥ 0). If shifted: `ResyncTime(elapsed ms)` (§4.3) | [known] |
| 0xC1C active items, 0xC1E full item sync | queues → +0xc8, +0xe0 → `OnAvatarItemsChanged` S 005036d0 | `UpdateAppearance` of that avatar (items, pet), if it has an object | [known] S 0046e660, S 0046e780 |
| 0xC1D inventory | queue → +0xd4, not subscribed here | none in the world | [known] S 00503d00, S 0046e6f0 |
| 0xD9 table update | handled only in `LobbyManager` state VillageEntered, for a table whose key has a non-zero chat channel id and whose proxy exists (S 0046f380). First update of a new proxy: +0x68 → `OnMiniGameTableShown` S 005032b0. Every update the proxy parses successfully: +0x80 → S 00503780 | +0x68: create the 0x1c-byte minigame client for the table by game type (1 dice, 2 poker, 3 pawn chess; any other type: none, the proxy's table object stays null) and store it in the proxy (`+0x20`); the client spawns the board at the table anchor. +0x80: call virtual +4 of that table client (no null check) | [known] |
| (table events) | +0x5c → S 00503730, +0x50 → S 00503710 | forward one argument to virtual +0xc / +8 of the proxy's table client. [TODO] not established: which code fires these two lists and with what argument (search for notifications on `VillageServerConnection + 0x50` and `+ 0x5c` made through the proxy's owner pointer) | [known] for the subscriptions |
| 0xD8 table remove | +0x74 → S 00503750 | delete the proxy's table client (if any) and null the pointer; also fired for every table when the connection clears its table map (S 0046fd10) | [known] S 0046f510 |
| login failed (fired among others when the user-comm login fails, code −1, S 00470660, and when `OpenUserComm` fails, code 0x91, S 00470d50) | +0x10 → `OnVillageLoginFailed` S 00503800 | while re-entering and `nReenterRetries` < 3: timeout 2.5 s, retries + 1, release the connection (`Update` re-enters). Else: lobby screen 2, message box titled `!ERROR_DIALOG` with text `!LOGIN_FAILED_TEXT`, release the connection, clear `bReenterPending`, +0x14 and the retry count | [known] |
| logged out / disconnected | +0x1c, +0x28 → `OnVillageConnectionClosed` S 00503280 | `DestroyLocalAvatarObject` (vtable +0xf0, S 004f5ee0: removes the own avatar object and clears the selection), `viewMode` 5, camera preset 0, flag the connection for release | [known] |
| (list +0x110) | +0x110 → S 005037a0 | unsubscribe from chat lines, `DestroyLocalAvatarObject`, `viewMode` 5, camera preset 0. No function in the decompile cache fires this list (only the connection's constructor and destructor and the subscribe / unsubscribe pair touch it) [known: cache-wide search], so the chat-line subscription made at EnterWorld is not removed by any path seen | [known] |
| chat line (UC connection) | → `OnChatMessage` S 00503200 | if a village connection exists and is logged in, the channel is the current zone channel or the main channel, and the sender's avatar is known and has an object: `ShowChatText(channel kind, text)` (§3.6) | [known] |

Sent: **2000 AvatarLocation** (§3.4) through `SendAvatarLocation` S 005034e0, which sends nothing in lobby
mode 2 or while the village connection is missing or not logged in; **2002** leave request through
`LeaveVillage` S 00503470, which first stores position, heading, zone and ghost zone of the village
connection's local avatar proxy (`CLobby::GetLocalAvatar` S 004f50f0, vtable +0x90; `bHasSavedPosition` = 1;
without such a proxy the flag is cleared). [known]

Own avatar at EnterWorld [known] S 00503940, in this order:

1. Defaults: **(−31.24, 2.71, −8.28)**, heading 0, zone 0, ghost zone 0xf.
2. If a character is selected: position, heading, zone and ghost zone of its proxy (the saved character
   data).
3. If `bUseDefaultSpawn`: position and zone back to the defaults (heading and ghost zone stay); the flag is
   cleared.
4. If `bHasSavedPosition` (set by `LeaveVillage`): saved position, heading, zone and ghost zone; the flag is
   cleared.
5. `CreateLocalAvatarObjAt(pos, heading, zone, ghostZone)` (vtable +0xec); unless a re-entry is pending,
   request lobby screen 3; subscribe `OnChatMessage` to the user-comm chat list; clear `bReenterPending`, the
   timeout and +0x14.

`CreateLocalAvatarObjAt` S 004f6fd0 [known]: the proxy is the village connection's local avatar; if there is
none and `curMode` is 3 nothing is created; if `requestedMode` is 2 a static default-constructed `AvatarProxy`
is used instead. The object is of class `settler` with `bLocal`, named after the proxy, in zone `zone & 0xff`,
orientation rotation(y, heading); it is appended to the object array, bound to the proxy and stored as the
local avatar object. The ghost zone argument is not read; the controller's ghost zone is set by the door test
of the first step. [inferred: no use of the fourth argument in the decompile]

`RequestExitVillage` S 004f5090: in lobby mode 2 it requests mode 0; otherwise, if a client exists, it calls
`LeaveVillage`. [known]

Re-entry (`RequestReenterVillage` S 00503560): mark pending, store `LobbyManager`'s local permanent id
(`LobbyManager + 0x54c`, S 00462510) in +0x14, timeout 2.5 s, retries 0, `LeaveVillage`. In `Update`
S 00503fc0, while a re-entry is pending and the connection object is gone, the timeout is reduced by the
frame time (`Timer_GetFrameDeltaSeconds`) in every frame in which the `CharacterManager`'s action queue is
not busy (virtual +0x10, S 0048ee90); at ≤ 0 it calls `EnterVillage(false)`. The pending flag is cleared by
EnterWorld or by the final login failure. [known]

## 6. Data-driven parameters

### 6.1 Folders under `data/lobby`

`[data]` resolves to `data\game\` and `data\lobby\` ([`app-shell.md`](app-shell.md) §7). XML and `.KEX` files
are encrypted containers ([`formats-inventory.md`](formats-inventory.md) §2).

| Folder | Content | Defines |
|---|---|---|
| `scene` | `world1.xml`, `world2.xml`, `scene1.xml` (2,026 objects, all zone 0), `scene_taverne02.xml`, `scene_taverne03.xml`, `scene_townhall.xml`, `scene_ad.xml`, `scene_customizeavatar.xml`, `scene_skydome.xml`, `scene_ambient_sounds.xml`, `scene1_settings.xml`, `scene2_settings.xml`, `scene2.xml`, `scene_gasthaus2.xml` | the world: which scene files, object placement, zone lighting, sound emitters. Only `world1.xml` is loaded; `world2.xml` (a test world: `scene2.xml` with one `testheightmap` object, a missing `scene_gasthaus.xml`) has no reference in the code [known: no string] |
| `config` | `lobbyobj.xml`, `materials.xml`, `bodyparts.xml`, `npc_bodyparts.xml`, `color_slots.xml`, `avatar_items.xml`, `pets.xml`, `emotes.xml`, `anim_selector.xml`, `*_animation_graph.xml` (male, female, MacDoyleJr, MacGabhan, nine pets), plain text `ItemsClient.txt`, `itemicons.txt`, `QuickEmotes.txt`, `LobbySettings.ini` (and a stray `LobbySettings - Copy.ini`); 27 files | object classes, materials, avatar catalogue, colours, items, pets, emotes, animation; server address and Hall of Fame URLs |
| `objects` | 168 files including the subfolders `minigame` and `TestData`: 89 `.KEX` models, 67 `.dds`, 10 `.tga`, 2 `.bmp` (`*_lm.dds` light maps, `ad0.tga`..) | models of buildings, plants, fences, tables, boards, the sign boards |
| `avatars` | 325 files (297 `.KEX`, 28 `.dds`): `model.KEX`, `model_woman.KEX` and two NPC skeletons (`model_MacDoyleJr.KEX`, `MacGabhan_model.KEX`); body meshes per tribe, gender, level and LOD; item meshes per tribe and gender; animations (`male_idle01..10`, `settler_male_walk`, `emote_*`); `*_colorindices_luminance.dds` | avatar and NPC geometry and animation |
| `pets` | 13 `lobbypet_*.KEX` | pet meshes |
| `heightmap` | `Terrain.KEX`, `testheightmap.KEX`, terrain textures (`terrain_color01.dds`, `terrain_mask01.dds`, `terrain_light01.dds`, `terrain_details.dds`, `Ground_parallax.dds`), `heightmap1.tga`, `density.tga`, `grassblade.TGA` | the terrain is an ordinary mesh object (`Terrain`, class `Terrain`, zone 0) whose mesh `collision` is its walk collision. No code string names `heightmap1.tga`, `density.tga` or `grassblade.TGA` [known: string search]; whether a `.KEX` or shader references them is [TODO] |
| `physic` | `myhouse.xml`, `lobby_castle01.xml`, `lobby_castle02.xml` (PhysX NxuStream 2 XML) | not referenced by `lobbyobj.xml`, the scene files or any code string [known]; the shipped collision comes from the model meshes (§3.3) |
| `sky` | `sky01.KEX` (meshes `Sphere01`, `plane_low`, `plane_high`), `panorama1..5.dds`, `cloudlayer*.dds`, `SkyWaterReflection.dds` | sky dome and two cloud planes (classes `sky01_dome` without a rank, `sky01_plane_high` rank 16777216, `sky01_plane_low` rank 16777217; `WaterPlane` has rank 16777218), loaded into zones 0 and 12 by the two `scene_skydome.xml` entries of `world1.xml` |
| `buildings` | 11 textures (`taverne02_inside_diffuse.dds`, `townhall_top_lm.dds`, `Taverne02Top.dds`, ..) | interior textures and the light maps named in the settings |
| `gfx` | `lightmap_white.tga`, `Village_Minimap.dds`, `fx_20/*.fx` (17 effects: `lobby_shader`, `skin`, `lobby_water`, `lobby_sky_shader`, `lobby_textbubble`, `lobby_pet`, `grass`, ..; 19 files in the folder tree) | shaders named by `materials.xml`; minimap image of the UI |
| `sound` | `ambient/*.ogg` (4: indoors, outdoors, brook, fireplace), 41 `.wav` in `npc` (5), `minigame` (16), `minigameDice` (13), `miniGamePoker` (7) | lobby sounds; the ids are defined in the game's sound table |
| `ui` | `layout/lobby*.xml` (32 dialogs and screens) | lobby UI ([`frontend-screens.md`](frontend-screens.md)) |
| `web` | `Rangliste1.html`, `Rangliste2.html`, `UIColor.PNG` | static sample pages for the web texture; no code reference established [TODO] |

### 6.2 Files and keys

**`scene/world1.xml`**: `world/world_settings/setting file`; `world/world_scenes/scene file scene_id_offset`.
Nine scene entries; `scene_customizeavatar.xml` and a second `scene_skydome.xml` use offset 12.

**`scene/scene*.xml`**: `obj name type scene pos orientation` (§3.1). Examples: `<obj name="townhall"
type="townhall" scene="0" pos="50.7544 4.4792 21.7764" orientation="0.0 18.1015 0.0"/>`; `<obj
name="ambient_brook" type="sound:63c3100c" scene="0" pos="-18.5 3 -32.5" .../>`. `scene1.xml` by class: 573
`Grass2`, 549 `Grass1`, 165 `Reet1`, 123 `bush_1_big`, plants, 24 trees, 8 fences, 4 walls, 3 houses, 3 taverns,
town hall, bridge, cart, letterbox, water plane, ground, terrain.

**`scene/scene1_settings.xml`**: `setting scene light_map light_map_object fog_start fog_end fog_color light_dir
shadow_light_intensity ambient diffuse`. Zone 0: light map `terrain_light01.dds` on object `Terrain`, fog
40..160, fog colour `1.0 0.99 0.81`, light direction `0.5 -1.0 0.25`, shadow intensity 0.40, ambient `0.45 0.37
0.50`. Zones 1, 2, 3: fog 10..50, light map on object `obj2`. Zone 12: light map `Box01_TopLightning.dds` on
object `map`.

**`scene/scene_ambient_sounds.xml`**: seven emitters: zone 0 `63c3100a` (outdoor) at the origin and `63c3100c`
(brook); zones 1..3 `63c31009` (indoor); zones 2 and 3 `63c3100b` (fireplace).

**`config/lobbyobj.xml`**: 110 `lobbyobj name gfxclass controllerclass` with `gfxparm` (§2.4) and an empty
`controllerparm`. 99 are `std` / `std`. Special: `Settler` (`avatar` / `character`), `CustomizeAvatar` (`avatar`
/ `customize`), `snapshotavatar` (`avatar` / `std`), three `skydome`, `spielfeld` (dice board), `pokertable4`,
`pokertable8`, `PawnChessTable`, `dice`. Examples: `taverne02`: `mesh="taverne02"
collision_mesh="collisionmesh_out" scene_trigger="transition_trigger_in" transition_area="transition"
scene="3"`; `taverne02_inside`: `mesh="inside" collision_mesh="collisionmesh_in"
collision_mesh_move="collisionmesh_moveOnly" scene_trigger="transition_trigger_out" scene="0"
node_hierarchy="inside"`; `Terrain`: `collision_mesh_move="collision" lod_class="terrain"`; `Letterbox`:
`selectionValue="1" selectionDecalOffsetY="0.5" selectionDecalSize="2.0"`; `table0`..`table14`:
`file="TableSelection2x2m.kex" selectionValue="100".."114" selectionDecalOffsetY="-0.7" visible="false"`;
`Grass1`: `fadeout_start="65" fadeout_end="75" instancing="true" lod_class="vegetation_minor"`.

**`config/bodyparts.xml`, `npc_bodyparts.xml`**: `bodypartset name model` / `heads` / `head meshLod0 meshLod1
meshLod2 texture slotMap`. A `head` without all of the first four attributes is skipped; `slotMap` defaults to
`default`. [known] S 004fd760 Players: sets `male` (`model.KEX`) and `female` (`model_woman.KEX`), 15 heads
each. NPCs: `male` 17 heads (`Severin`, `zeus`, `Kostas`, `npc01`..), `female` 6, `MacDoyleJr` 1, `MacGabhan` 1.
The set name selects the animation graph file.

**`config/color_slots.xml`**: `SlotEnumeration/Slot name` (15); `ColorRamps/ColorRamp slot` (44) with one of
the attribute forms `solid` (3 floats), `lit` + `dark` (3 floats each) or `texture` with optional `rows`, and
otherwise child elements carrying `value` (3 floats); the lobby file uses `solid` once, `texture` 43 times
(10 with `rows`) and neither of the other forms. `ColorMaps/ColorMap name slot0..slot7` (32; the map `default`
has no `slotN` attributes) with 16 `Material index slot` children each. Example: `<ColorMap name="bavarian_default" slot0="14" slot1="1"
slot2="12" slot3="2" slot4="3" slot5="7" slot6="8" slot7="11">`. [known] S 0050d920 The same format as the
game's `character/color_slots.xml` ([`animation-models.md`](animation-models.md) §6.3).

**`config/avatar_items.xml`**: root `avatar_Items`, 132 `Item name mesh`, name = `<Mesh>_<Tribe>_<Gender>`, e.g. `Crown_Bavarian_Male` →
`Crown_bavarian_Male.KEX`.

**`config/pets.xml`**: 13 `pet name model mesh scale anim_graph texture`, e.g. `dog`: `dog_model.KEX`,
`lobbypet_dog.KEX`, scale `0.012`, `pet_dog_animation_graph`, `dog.dds`. Pet graphs have two states, `Stand`
and `Walk`.

**`config/emotes.xml`**: one element per emote (the element name, lower-cased, is the emote name) with `anim`,
`sound`, `text`, e.g. `<Dance anim="Dance" text="!EmoteDance"/>`. Six emotes: `Laugh`, `Dance`, `Applaud`,
`Cry`, `Bow`, `Monkey`; none of them has a `sound` attribute in the shipped file. [known] S 0051c710

**`config/anim_selector.xml`**: under the root, `avatar/avatar itemid anim_idle anim_walk` (item ids 0..36) and
`npc/npc npcindex anim_idle anim_walk` (0..10; only `anim_idle` is read). Indices are not range-checked; the tables
hold 64 entries each. [known] S 00500b50 Examples: item 1 (sword) `Stand_LongItem` / `WalkItemInRightHand`;
NPC 5 `Stand_Guard`; NPC 10 `SitChair`.

**`config/*_animation_graph.xml`**: `anim name source emotes` with optional `randoms minDelay maxDelay` /
`random source probability`; `trans from to blend`; `overlay name source`. `male`: states `CustomizeStand`
(must be first: its index is shared with `female`), `Stand` (10 random idles, delay 5..8 s), `Stand_Guard`,
`Stand_Guard2`, `Stand_LongItem`, `Stand_ItemInRightHand`, `Stand_ItemInRightHandFlat`, `Walk`, `SitChair`,
`WalkItemInRightHand`, `WalkItemInRightHandFlat`; all transitions go through `Stand` with blend 0.0; overlays
`Laugh`, `Dance`, `Applaus`, `Crying`, `Bow`, `Monkey`, `Jump`.

**`config/materials.xml`**: 48 `material name` / `lod shadow pplighting [default instanced]` / `pass name shader
technique transparent_shader transparent_technique alpha_sorting`; the pass name contains `std`, `shadow` or
`mirror`. [known] S 0050c300

### 6.3 Tweakables (debug variables with their image defaults)

| Group / name | Default | Use |
|---|---|---|
| `Lobby/TurnSpeed` | 30.0 | §3.4 |
| `Lobby/ControllerMode` | 2 (0..2) | registered by the local controller; never read: the registration at S 0051ad37 is the only reference to the variable [known: xrefs to S 0087cbd4] |
| `Lobby/FirstPerson` | false | close-up camera |
| `Lobby/CameraCollisionDistance` | 0.1 | §3.4 |
| `Lobby/MaxSelectionDistance` | 25.0 | §3.8 |
| `Lobby/WaterHeight` | −0.1 | reflection plane |
| `Lobby/fontFadeStart`, `fontFadeEnd` | 18.0, 25.0 | §3.6 |
| `Lobby/bubbleOffsetX`, `bubbleOffsetY`, `TextBubbleBias` | 37, −27, −3.0 | §3.6 |
| `CharSelection/cameraAngleX`, `cameraDistance`, `camLookAtY` | 16.0, 4.0, 7.0 | §3.7 |

[known] image values at S 0087cba4 (`TurnSpeed`), S 0087cbd0 (`CameraCollisionDistance`), S 0087cbd4
(`ControllerMode`), S 0087c8a8 (`bubbleOffsetY`), S 0087c8ac (`bubbleOffsetX`), S 0087c8b0 (`TextBubbleBias`),
S 0087c91c (`fontFadeEnd`), S 0087c920 (`fontFadeStart`), S 0087c714 (`camLookAtY`), S 0087c718
(`cameraDistance`), S 0087c71c (`cameraAngleX`); `MaxSelectionDistance` and `WaterHeight` are object fields
set by the constructors S 004fb100 and S 004fef10; `FirstPerson` is the zero-initialised byte S 008896d0.
Further debug switches of the groups `Lobby`, `Lobby GfxSettings` and `Evil Hacks` (`Show Menu`, `Show DBG`,
`rm*`, `AvatarLodBorder0/1`, `Write Avatar`, `CustomizeNPCHack`, ..) are registered where they are used. They
can only be changed through the developer tweak server
([`../BINARY_PATCHES.md`](../BINARY_PATCHES.md)).

## 7. Save and load

- Nothing of the 3D world is written by this subsystem during play. The avatar's look, items, gold and last
  position are part of the character data kept by the server and delivered at character selection (protocol
  document §1.4); the client only re-reports its position (message 2000).
- In memory only: the position saved by `LeaveVillage` for a re-entry (§5.2).
- `CGfxObjAvatar::SaveAvatarFile(name, bUserAvatar)` S 00506a40 writes the current look (with the `Stand`
  animation source) as `<users folder>\<name>.avo` when `bUserAvatar` is set, else as `<name>.npc` (format
  strings `%s\%s.avo`, `%s.npc`). Format and the in-game reader: [`formats-inventory.md`](formats-inventory.md)
  §3.5. Its three callers [known]:
  - `RenderAvatarSnapshot` S 004f7fd0 when its save flag is set (`.avo`). `RenderFrame` passes false; the
    portrait grid `RenderAvatarSnapshotGrid` S 004f82a0 passes its own second argument on, with the name
    `slot_<n>`, n taken per portrait from the integer list in its third argument. [TODO] not established:
    which UI caller of the grid (vtable +0xcc) passes a non-zero flag and what the integers are (find the
    virtual call sites in `LobbyMenu`).
  - `CGfxObjAvatar::CollectRenderItems` S 00507060 while the debug switch `Lobby/Write Avatar` is set: name
    `Default`, `.avo`; the switch is cleared afterwards.
  - `ApplyCustomizeAvatarLook` S 004f84b0 while the debug switch `Evil Hacks/SAVE` is set: name
    `CustomizedNPC`, `.npc`; the switch is cleared.
- PhysX cooking caches `*.phx` in the local application data folder (§3.3): derived data, rebuilt on demand.
- The five lobby graphics options are stored with the profile ([`app-shell.md`](app-shell.md) §6).

## 8. Determinism notes

Presentation and front end only. No function read for this document touches `NLogic` simulation state.
[inferred] The world is updated and drawn in lobby modes 2 and 3, in which the frame goes through
`FrameTick_Menu` and no logic tick runs, and in modes 0 / 1 from the other frame tick whenever the menu system
shows the 3D world behind its screen (`nMenu::System + 0xb5`, set by the 2 / 3 → 0 transition)
([`app-shell.md`](app-shell.md) §4). It uses its own random generator (seed 0x5432ace0, for random idles), the
wall clock and PhysX, none of which feed the match. Its only authoritative outputs are the position report
(2000) and the UI actions; the server relays positions without checking them. Two clients therefore do not see
bit-identical villages, and need not.

## 9. Notes for a Godot reimplementation

- **Scene.** One Godot scene per zone, or one scene with a visibility layer per zone: only the camera's zone is
  visible, an object in a doorway is in two zones. Keep the shared coordinate system and the axis mapping of
  §3.1 ((−z, y, x) from the file), because spawn points, camera presets, NPC positions and the wire
  quantisation (x and z in [−150, 150], y in [−10, 30]) are in world coordinates.
- **Converter.** From the player's install: `world1.xml` and its scene and settings files → placements and
  environment; `lobbyobj.xml` → class table; each `.KEX` → mesh resources including the named sub-meshes used as
  `collision_mesh`, `collision_mesh_move`, `scene_trigger`, `transition_area` and the `node_hierarchy` nodes
  with their `pfx:` / `slot:` names; `bodyparts.xml`, `color_slots.xml`, `avatar_items.xml`, `pets.xml`,
  `anim_selector.xml`, the animation graphs, `emotes.xml`, `ItemsClient.txt`.
- **Collision.** Static trimesh bodies on two layers per zone (all / walk-only) and a capsule
  `CharacterBody3D` (radius 0.5, height 1.0, step 1.0) moved in a fixed 83 ms step with the constant downward
  0.5. Doors are `Area3D`-like point-in-mesh tests of the avatar's feet position. Camera: a spring arm with 8
  rays reproduces the collision rule.
- **Must be exact.** The 83 ms step and the every-4th-step report; walk and run step lengths; the sample ring
  rules of §3.5 (2000 ms delay, 2 s gap, 10-unit snap, 3 s hide, zero rejection), because the server's stamping
  rule depends on them; model index = tribe + (level − 1) × 3; item slot and bone mapping; selection values 1
  and 100 + n; table tags; default spawn; chat bubble duration.
- **Free to redo.** Shaders, shadows, reflection, LOD counts, fades, the palette atlas (a palette texture per
  avatar works the same), particle effects, sky, the portrait renderer.
- **Engine features.** `AnimationTree` state machine per body-part set with one-shot overlays for emotes and
  jump; `Label3D` or a 2D overlay for name tags and bubbles; `AudioStreamPlayer3D` for emitters with the
  listener at the avatar.
- **Server.** Must provide what the protocol document lists; for the world specifically: 1005 before the first
  position, positions stamped about 1 s in the past, zone and ghost zone relayed verbatim, NPC records with a
  kind (1 character, 2 letterbox), a model index and a zone.
- **Web textures.** The three boards and the Hall of Fame need a replacement source; the original URLs are
  dead.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 4 | Use of the physics ray in picking, and the two points of the 3.5 test that excludes the own avatar (§3.8) | static: disassembly of S 004f6190 |
| 5 | Cap of the camera collision distance and the exact ray origins | static: disassembly of S 0051a450 |
| 6 | Answered: the first extra mouse button is the forward key 5, with or without text focus, but only while the cursor is over the 3D world: the desktop forwards a mouse-down to the world screen only when it is itself the target, and the world screen maps button 3 to key 5 (table S 00879fd4). No input capture is taken for this button, so a press over the world and a release over a widget leaves key 5 set and the avatar keeps walking | static: S 00401f30, S 0042e990, S 0042eab0, S 00431d60, S 00431db0, S 004f4fd0, S 004f5010, S 00490f50, S 004295c0 |
| 7 | Whether `ActorProxy + 0x80`, which hides the pet while non-zero, is set for seated players only or also for observers | static: the writers of the field |
| 9 | Handedness of the world, and with it the sense of the three `orientation` turns (the composition is in §3.1) | live: compare one rotated object with its place in the game |
| 10 | Whether `heightmap1.tga`, `density.tga`, `grassblade.TGA`, `physic/*.xml`, `web/*` are referenced from inside `.KEX` files. The 17 lobby `.fx` files name none of them (`grass.fx` has a density-map switch on its second texture stage but no file name) [known: text search of the decrypted `fx_20`] | data: search the decrypted `.KEX` containers |
| 12 | The seated animation and camera constants of each minigame | static: the `CMiniGameController*` constructors |
| 13 | Observed walking speed, report rate and remote smoothing | live: two clients, measure against §3.4 and §3.5 |
| 14 | Whether the group argument of `CPhysicObj::ctor` (zone, zone + 16) is the value of the 16-bit store into the group field of the `NxTriangleMeshShapeDesc` | static: disassembly of that store in S 00522410 (which stack argument it reads) |
| 15 | Which UI caller of `RenderAvatarSnapshotGrid` (vtable +0xcc) passes the save flag that writes `slot_<n>.avo` (§7) | static: virtual call sites of `CLobby` vtable +0xcc in `LobbyMenu` |
| 16 | Which code fires the village connection's lists +0x50 and +0x5c (forwarded to the table client, §5.2), and whether any path fires +0x110 | static: instruction search for the notifier S 00464300 with those list offsets; live: hook S 005037a0 |
| 17 | Whether any caller requests a lobby mode pair that `ProcessModeTransition` does not handle (§4.3) | static: callers of vtable +0x2c and their arguments |
| 18 | The two PhysX calls before the object loop and the second call of `LobbyPhysics::Step` (§4.1) | the PhysX SDK headers of the shipped version (vtable offsets 0x1d4, 0x1cc, 0xe0 of `NxScene`, 0x14 of the controller manager) |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004f8c90 | `CLobby::StartUp` | creates all sub-systems |
| 004f57f0 | `CLobby::LoadZoneTable` | loads the world file, builds the zone grids |
| 004fb460 / 004fb230 | `CLobby::Update` / `Tick` | per-frame driver, fixed-step loop |
| 004f58a0 | `CLobby::RenderObjects` | the fixed object step |
| 004f9960 | `CLobby::RenderFrame` | zone, sound, passes, picking, UI, portrait |
| 004f5950 / 004f4eb0 | `ProcessModeTransition` / `RequestModeTransition` (index name `App_RequestStateTransition`) | lobby mode machine |
| 004f5d90 / 004f5ee0 / 004f50f0 / 004f5200 | `ResyncTime` / `DestroyLocalAvatarObject` / `GetLocalAvatar` / `SetViewMode` | clock resync, own avatar removal, own proxy, camera mode request |
| 004f6ca0 / 004f7d10 | `CreateObj` / `CreateObjWithoutActor` | object factory |
| 004f6de0 / 004f6ea0 / 004f6fd0 | `CreateAvatarObj` / `CreateNpcObj` / `CreateLocalAvatarObjAt` | actors |
| 004f5ce0 | `CLobby::RemoveObject` | destroy an object |
| 004f6190 | `UpdatePickingAndSelection` | hover and selection |
| 004f5210 / 004f5250 / 004f5e00 | `SetSelectedObject` / `SetHoverObject` / `SelectLocalAvatar` | selection flags |
| 004f5370 / 004f5e40 | `GetSelectedObjectInfo` / `GetSelectedActorProxy` | what the UI reads |
| 004fb5f0 / 004fad20 / 004f6850 | `AddDistanceWatch` / `UpdateDistanceWatches` / `CheckAndFire` | walk-away watches |
| 004f5480 / 004f5430 | `UpdateZoneAmbientSounds` / `Lobby_PlayZoneMusic` | zone sound |
| 004f5290 | `SetLobbyGraphicsOptions` | the five options |
| 004f71d0 / 004f5780 / 004f84b0 | `EnterCustomizeMode` / `LeaveCustomizeMode` / `ApplyCustomizeAvatarLook` | character stage |
| 004f7fd0 / 004f82a0 / 004f51b0 | `RenderAvatarSnapshot` / `RenderAvatarSnapshotGrid` / `GetSelectionSnapshotTexture` | portraits |
| 004f7d40 / 004fa6b0 / 004fa6f0 / 004fa730 | `ShowCharacterPreview` / `...ById` / `...ByIndex` / `ShowLocalAvatarPreview` | character preview for the UI |
| 004f65a0 / 004f53d0 / 004fad00 | `WorldToZoneNormalizedCoords` / `ApplyToActorLobbyObject` / `SetSelectionEnabled` | minimap coordinates, NPC speech, selection gate |
| 004f5070 / 004f5090 / 004f50c0 | `RequestEnterVillage` / `RequestExitVillage` / `RequestReenterVillage` | UI entry points to `CLobbyClient` |
| 00502380 / 00501b90 / 005013b0 | `CLobbyScene::LoadWorld` / `LoadSceneObjects` / `LoadSceneSettings` | world files |
| 00500fe0 / 00501040 | `StartAmbientSoundGroup` / `StopAmbientSounds` | emitters |
| 004ffe70 / 004ffa80 | `LobbyObjConfig::LoadFromFile` / `FindEntry` | object classes |
| 00502e60 / 00502a90 / 005029e0 / 005027f0 | `CLobbyObj::ctor` / `CreateGfxObj` / `Update` / `UpdateScene` | object, controller choice, door test |
| 005191c0 / 00518a80 / 00518e50 / 00518b70 | `CGfxObjStd::ctor` / `TestSceneTrigger` / `ParseNodeHierarchyTags` / `CollectRenderItems` | scenery |
| 004fbcc0 / 004fbd10 / 004fbd90 | `NodeTagTable::Set` / `GetNodePosRot` / `GetNodePosRotSlotC` | table and seat anchors |
| 0051a1a0 / 0051a840 / 0051ace0 / 0051a450 | `CLocalController::ctor` / `UpdateMovementAndCamera` / `ProcessInputAndSendLocation` / `ComputeCameraCollisionDistance` | own avatar |
| 00519c10 / 00519b20 / 00519d50 / 00519ab0 | `CNetController::ctor` / `PushActorSample` / `Update` / `Activate` | other avatars |
| 005198c0 / 005197f0 | `CStaticController::ctor` / `Update` | scenery and its collision |
| 0051aed0 / 0051af50 | `CustomizeAvatarController::ctor` / `Update` | turning stand |
| 00511250 | `ILobbyObjController::UpdateAvatarAnimation` | idle / walk / run / jump choice |
| 00522e60 / 00522f20 | `OrbitCameraRig::ctor` / `Update` | orbit rig |
| 004fef10 / 004ff420 / 004ff220 / 004ff280 / 004ff940 | `CLobbyCamera::ctor` / `UpdatePresetModeKeys` / `AddOrbitKey` / `AddTargetKey` / `GetEyePosition` | camera |
| 00500410 / 005003a0 | `LobbyPhysics_Init` / `LobbyPhysics::Step` | PhysX world |
| 00522c80 / 00522410 / 00522290 | `CPhysicObj::ctor` / `CreateTriangleMeshActor` / `LoadFromNxuFile` | static collision |
| 005234c0 / 00523670 / 00523610 | `CPhysicObjCharacter::ctor` / `Move` / `GetTransform` | character capsule |
| 005084b0 / 00508090 / 00506e10 | `CGfxObjAvatar::ctor` / `UpdateAppearance` / `CreateAnimation` | avatar model |
| 00507f60 / 00507ca0 | `SyncEquipmentSlot` / `AttachItem` | items and pets |
| 005079b0 / 00506610 / 00506530 | `ShowChatText` / `PlayEmote` / `PlayJumpOverlay` | bubbles, emotes, jump |
| 00507060 / 00507580 / 00506860 / 00505c10 / 00505b10 | `CollectRenderItems` / `DrawRenderItem` / `DrawNameTag` / `DrawChatBubble` / `GetTextAnchor` | avatar drawing |
| 004fd760 / 004fd2a0 / 004fcc90 / 004fcc10 | `AvatarBodyParts::LoadFromXml` / `AcquireVariant` / `BuildVariantPalette` / `CopyVariantColorRamp` | catalogue and colours |
| 0050d920 | `AvatarColorSlots::LoadXml` | `color_slots.xml` |
| 004fec10 / 004fe5c0 / 004fe080 | `LobbyPetMgr::ctor` / `CreateInstance` / `UpdateInstance` | pets |
| 00505e70 / 005060a0 | `LobbyPetTrail::PushPosition` / `EvaluatePose` | pet following |
| 0051c710 / 0051c5a0 | `LobbyEmotePlayer::LoadDefinitions` / `Begin` | emotes |
| 00500b50 / 00500aa0 | `LobbyAnimSelector::LoadXml` / `GetAnimEntry` | `anim_selector.xml` |
| 0050ea00 / 0050ec80 / 0050e6c0 | `AnimModel::SetState` / `Update` / `PlayOverlay` | animation model |
| 00510b70 / 00510c80 | `TransformInterpolator::AddSample` / `Evaluate` | two-key pose interpolation |
| 00504650 / 005049c0 | `CGfxTextureMgr::GetTexture` / `LoadTextureEx` | textures, the three web textures |
| 005c8050 / 005c7ba0 / 005c8a30 | `CURL2Tex::RequestURL` / `CURL2TexEntry::RenderToTexture` / `CSDKIEEvents::Invoke` | web page to texture |
| 0050c300 | `CGfxShaderMgr::LoadMaterials` | `materials.xml` |
| 00504e00 / 00504d60 / 00504eb0 / 00504b20 | `CGfxScene::PickClosestObject` / `FindSceneTransition` / `SetBoundsAndBuildGrid` / `RenderVisibleObjects` | zone scene |
| 005033b0 / 00503f50 / 00503d00 / 00503ab0 / 00503fc0 | `CLobbyClient::ctor` / `EnterVillage` / `SubscribeVillageConnection` / `UnsubscribeVillageConnection` / `Update` | bridge |
| 00503280 / 005037a0 / 00503750 / 00503780 | `OnVillageConnectionClosed` / observer of list +0x110 / table client removal / table client update | connection end, tables |
| 0057b910 | `Timer_SyncElapsedToServerTick16` | clock slew to the 16-bit server tick |
| 00503940 / 00503620 / 00503170 / 005031a0 / 005031d0 | `OnEnterWorld` / `UpdateAvatar` / `OnAvatarRemoved` / `OnNPCAdded` / `OnNPCRemoved` | world changes from messages |
| 00503590 / 005036d0 / 00503200 / 005032b0 | `OnWorldTick` / `OnAvatarItemsChanged` / `OnChatMessage` / `OnMiniGameTableShown` | clock, items, chat, tables |
| 005034e0 / 00503470 / 00503560 / 00503800 | `SendAvatarLocation` / `LeaveVillage` / `RequestReenterVillage` / `OnVillageLoginFailed` | outgoing and re-entry |
| 0046fde0 | `VillageServerConnection::DrainEventQueues` | queue → observer list order |
| 004294a0..004296c0, 00428fd0, 00429030 | `LobbyAction::Is*Down`, `IsMouseLookActive`, `GetMouseLookYaw` | input mapping |
| 005269e0 / 00526800 | `CMiniGameController::UpdateCamera` / `ctor` | table cameras |
