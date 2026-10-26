# Rendering and scene: what the player sees

Specification of the presentation layer of the match: the 3D scene that mirrors the simulation. Namespaces `S2CG`
(game graphics), `S2CE` (engine: device, textures, meshes, effects), `ai::render`, `ai::gfx`, `ai::rendering`.
Binary: `sadk_noav.exe`; "S 00xxxxxx" is a static address in it.

Tags: **[known]** = read directly in the decompiled code at the address given, in the bytes at the address given,
or in the named data file and key. **[inferred]** = one step of reasoning from what is visible; this tag is also used
for statements that rest on the mapped name and comment of a function whose code was not re-read line by line for
this document. **[TODO]** = open, with what would settle it. Nothing here was observed in the running game.

Related documents (not repeated here): `docs/sim/map-resources.md` (grids, hexagon geometry, exploration,
territory, grid flag bits), `docs/sim/logic-core.md` §2.6 and §3.7 (`NLogic::CallbackManager`),
`docs/sim/village-buildings.md` (construction, upgrade, hit points), `docs/sim/settlers-jobs.md` (settler states),
`docs/sim/streets-transport.md`, `docs/sim/navy.md`, `docs/sim/military.md`, `docs/sim/save-format.md`,
`docs/asset-formats.md` (encrypted container, KEX scenes), `docs/map-format.md` (`.s2m`, the `.bin` sidecar),
`docs/data-loading.md`, `docs/subsystems.md` §2.8.

---

## 1. Purpose and scope

The scene is a read-only mirror of the simulation. It owns no game rule. Its work:

- keep one visual object per simulation object (building, settler, flag, street, deposit, doodad, ship, animal,
  projectile, chest, spawn point, harbor, sea route), created and removed by callbacks of the logic;
- turn the height map and the pattern map into terrain geometry with blended textures, water, coast and a map
  border;
- show exploration (black unexplored ground, hidden objects), territory borders, selection markers and the
  build-placement overlay;
- interpolate everything between logic ticks and select animations from simulation state;
- light the scene (one directional light, ambient, distance fog, shadow map, optional bloom and depth of field).

Out of scope: the HUD ([ingame-ui.md](ingame-ui.md), [hud-panels.md](hud-panels.md)), the widget toolkit `nUi`
([ui-toolkit.md](ui-toolkit.md)), the front-end menus `nMenu` ([frontend-screens.md](frontend-screens.md)), the
lobby screens ([lobby-screens.md](lobby-screens.md), [match-setup-room.md](match-setup-room.md)), the 3D lobby
renderer (`Lobby::CGfx*`),
the camera controller (`nGame::Camera`), sound, and the editor tools that live in the same classes (terrain
generator, Terragen import, auto-texturing: S 00688540, S 006885f0, S 00688670).

---

## 2. Data model

### 2.1 Units and coordinate spaces

| Space | Definition | Evidence |
|---|---|---|
| cell | `(x, y)`, 0..W-1, 0..H-1; one hexagon of the simulation | `docs/sim/map-resources.md` §2.1 |
| vertex ("fine") | `(vx, vy)`, 0..4W, 0..4H; height samples; a cell's vertex is `(4x + 2*(y&1), 4y)` | same |
| world | left-handed, Y up (Direct3D 9): `x = vx*stepX + originX (+stepX/2 on odd vy)`, `y = height*heightScale`, `z = vy*stepZ + originZ` | same, [known] S 00687500 |
| terrain cell (render block) | 4 x 4 cells; culling, LOD and reveal unit | [known] dwords S 00881e7c = 4, S 00881e80 = 4 |

`graphics.xml` `<Map scaling="1.5 0.001 1.2990375"/>` gives `stepX`, `heightScale`, `stepZ` [known, file]. One
cell is 6.0 world units wide, rows are 5.19615 apart, 1000 height units are 1 world unit [inferred].

The map is centred on the world origin: `ai::map::TerrainGrid::Init` S 00688050 sets
`originX = -(gridWidth - 1) * stepX / 2` and `originZ = -(gridHeight - 1) * stepZ / 2` [known], where the two
sizes come from the first two virtuals of the grid's size source; they are the vertex grid sizes `4W+1`, `4H+1`
[inferred: the same pair sizes the per-vertex normal array]. So world x runs from `-2W*stepX` to `+2W*stepX`.

`g_TerrainGrid` is the global at S 00881440 (`ai::map::TerrainGrid`: size source +0, elevations +4, `seaLevel`
+8, `deepWaterLevel` +0xc, origin +0x10/+0x18, packed normals +0x1c, scanned minimum and maximum vertex height
+0x20/+0x24, row stride +0x28, occupancy bitset +0x2c) [known] S 00688050, S 006872c0. All render code that tests
"below water" compares integer heights against `seaLevel` (S 00881448), and the water height in world units is
that value times `heightScale` (`TerrainGrid::GetSeaLevelHeight` S 00687050) [known] S 006b4f60, S 006b6840.
`seaLevel` and `deepWaterLevel` are the two ends of the overlay height range (§3.7) [known] S 006bed80.

**Packed vertex normals** (`g_TerrainGrid +0x1c`, three bytes per vertex) `ComputeNormalsInRect` S 00687810,
`PackNormalToBytes` S 00687090 [known]: per vertex, the x slope from the left and right neighbours of its row and
the z slope from the rows above and below **at the same column index** (the half-step shift of odd rows is not
compensated); at the map border, where one neighbour is missing, the divisor stays `2·step`, so a border
vertex's slope comes out smaller than an inner one's on the same ramp. Packing truncates to bytes: flat ground
packs to (127, 255, 127) [known]; that the byte is `trunc((n + 1) · 127.5)` is [inferred] from those values. Readers unpack `b · 0.0078431367874145508 − 1` (the float 2/255) and do not renormalise:
the terrain mesh copies the bytes unchanged (S 006c0410), and the ground decal clipper builds its planes from them
(§3.9).

Both are constants of the program image: S 00881448 holds **-100** and S 0088144c holds **-3000** in the
initialised data, every reference to them is a read, and `TerrainGrid::Init` writes only +0x20/+0x24 [known]. So
the renderer's water plane is at world `y = -0.1` on every map, and the water depth value of the overlay
saturates 2900 height units below it. The renderer does not read the map's `minHeight`
(`docs/map-format.md` §4.5; -100 by default), which is the water level of the simulation: the picture and the
simulation agree only on a map that keeps the default [inferred].

### 2.2 `S2CG::Scene` (singleton S 0088ca60, primary vtable S 007f8f2c)

Five interface faces: `IScene` (+0), `S2CE::I3DSoundListener` (+4), `NMap::CallbackReceiver` (+8, vtable
S 007f8f08), `NLogic::CallbackReceiver` (+0xc, vtable S 007f8e24), `S2CE::IDeviceChangeListener` (+0x10)
[known] S 0067fb40.

| Offset | Type | Name | Meaning | Evidence |
|---|---|---|---|---|
| +0x14 | u32 | `passMask` | scene passes drawn in the main view (§3.1); 0x1ff, one bit per `SceneDetail` debug CVar | [known] S 0067fb40, S 0067f6b0 |
| +0x18 | u32 | `passMaskDefault` | pass mask of the reflection view, rebuilt every frame from the detail level (§3.1) | [known] S 0067f6b0, S 00680ab0 |
| +0x1c | float | detail setting | 0..1 (settings virtual +0x3c); `trunc(v*4 + 0.5)` is the scene detail level | [known] S 0067f500; conversion [known] S 0067f6b0 (at 0067f76e: `FMUL 4.0`, `FADD 0.5`, `__ftol2_sse`) |
| +0x20 | float | shadow setting | 0..1 (settings virtual +0x24); `trunc(v*6 + 0.5)` is the shadow level (§3.13) | [known] S 0067f500; conversion [known] S 0067f6b0 (at 0067f7ca: `FMUL 6.0`, `FADD 0.5`, ftol, passed to S 0067f420) |
| +0x24 | u32 | `renderFlagsA` | map layer flags of the main view (§3.1); 0x3ff at construction | [known] S 0067eb20, S 0067fb40 |
| +0x28 | u32 | `renderFlagsB` | map layer flags of the reflection view, rebuilt every frame (§3.1) | [known] S 0067eb20, S 0067f6b0 |
| +0x2c | float | shadow map quality | settings virtual +0x1c; 0 disables the shadow map; passed to `S2CE::ShadowManager::SetQuality` | [known] S 0067f500, S 0067f420, S 006810b0 |
| +0x30, +0x34, +0x38 | int, u32, u32 | shadow technique, flags, caster mask | §3.13 | [known] S 0067f420 |
| +0x48 | float | `gameTime` | time of the next logic tick (`NLogic::System +0x78`), stored on every logic tick | [known] S 00680550, S 006805e0 |
| +0x4c | float | `realTime` | accumulated simulation time now (`+0x7c`), or a wall-clock sum | [known] S 0067f6b0 |
| +0x50 | float | tick length | copy of game config +4 (the tick interval) | [known] S 0067fb40 |
| +0x54 | float | inverse tick length | `1 / (+0x50)`; the factor of the interpolation `1 - (gameTime - realTime) * (+0x54)` | [known] S 0067fb40, S 006805e0 |
| +0x58 | float | frame delta | seconds | [known] S 0067f6b0 |
| +0x60 | ptr | `postProcessor` | exists only while the POSTFX setting is on | [known] S 006836b0 |
| +0x64 | ptr | `SceneBorder` (0x4b4 bytes) | the GUI frame around the view (`<GUI><Border>`) | [known] S 0067fb40, S 0067edd0; role [inferred] S 006967d0 |
| +0x68 | ptr | selection context | the in-game screen; its dword +0xfff4 is the local player record | [inferred] S 0067f020, S 00680a00 |
| +0x6c | byte | reflection view flag | 1 while the reflection view is drawn | [known] S 0067eb20, S 00680ab0 |
| +0x70 | int | `currentPass` | cull mode id: 2 normal, 3 mirrored | [known] S 0067eb20, S 00680ab0 |
| +0x74 | bool | shadows suppressed | set each frame when device value +0x15c >= 1.0 (the comparison is read from the decompile; +0x15c is the shadow intensity [inferred]); also clears layer flag 0x10000 | [inferred] S 006805e0 |
| +0x75 | bool | post processor bypass | when set, the post processor is not used although it exists | [known] S 006836b0, S 00680a00; writer [TODO] |
| +0x78 | int | device quality | effective shader level of the device; > 1 allows shadow map and post FX | [known] S 0067eb20 |
| +0x5e0 | Frustum (0xf0) | view frustum | copy of the device frustum (frozen by a debug CVar) | [known] S 006805e0 |
| +0x6d0 | Matrix44 | view-projection | copy of device +0x278 at the start of `Render` | [known] S 006836b0 |
| +0x720 | bool | fog enabled | distance fog on for the map and sky | [known] S 0067eb20 |

The block at +0x48 is passed around by pointer as "frame info" / "time info": `timeInfo[0]` = next tick time,
`timeInfo[1]` = now, `[2]` = tick length, `[3]` = its inverse, `[4]` = frame delta [known] S 006805e0,
S 006aabe0, S 006aaab0.

### 2.3 Scene singletons

| Global | Class | Draws |
|---|---|---|
| S 0088cf64 | `S2CG::CMapRenderer` | terrain, water, streets, borders, buildings, map objects, markers |
| S 0088cf28 | `S2CG::CEnviromentMgr` | sky, light, fog, local environment spheres (and the pointer of the environment particle layer, always null, §3.13) |
| S 0088d6b0 | `S2CG::CCharacterMgr` | settlers and transport donkeys |
| S 0088d86c | `S2CG::ItemMgr` | goods (carried, stacked at flags and building sites) |
| S 0088d868 | `S2CG::AnimalMgr` | animals |
| S 0088d864 | `S2CG::SwarmMgr` | ambient flocks (birds, fish, bugs) |
| `S2CG::ShipMgr::GetInstance` | `S2CG::ShipMgr` | ships |
| S 0088d9ac | `S2CG::ProjectileTable` | projectile types (`projectiles.xml`) and the live projectile visuals |
| S 008872f4 | `ai::render::MeshRenderer` | single meshes (ship status overlays and similar) |
| S 008872fc | `ai::render::DecalRenderer` | projected ground decals (selection markers and similar) |
| S 00887300 | `ai::render::ParticleManager` | all particle emitters |
| S 0088d988 | `S2CG::ShadowManager` | the shadow map |
| S 0088cf48 | animation event registry (`ai::gfx::EffectScriptMgr`) | sound, particle and item events of animations |

[known] for the getters named in S 0067eb20; class roles [inferred] from the functions called on them.

### 2.4 `S2CG::CMapRenderer` (sub-renderers)

| Offset | Object | Role |
|---|---|---|
| +0x18 | `CLandscape` | terrain: pattern manager (+0x14), terrain mesh (+0x18), draw batch (+0x1c), cell manager (+0x20), ground cover (+0x24) |
| +0x1c | `ai::rendering::StreetSet` | streets and sea routes (owns the `ai::gfx::StreetRenderer` at +0x24) |
| +0x20 | `S2CG::WorldRenderer` | water, reflection target, map border skirt (the class is the water renderer) |
| +0x24 | `ai::render::MapObjLayer` | instanced map objects (trees, stones, flags, doodads, ...) |
| +0x28 | `S2CG::BuildingRenderer` | buildings, construction sites, ruins, military flags |
| +0x2c | `ai::render::BorderMgr` | territory border posts |
| +0x30 | `ai::render::HouseDecalRenderer` | ground decals under buildings and ruins |
| +0x44 | `ai::render::ConstructionMapRenderer` | build-placement icons |
| +0x80 | `SelectionMarker*[4]` | selection decals (0x38 bytes each) |
| +0x9c | u32 `renderFlags` | layer flags of the pass in progress |
| +0xf4 | ptr | local player record with visibility (set by the visibility callback) |

[known] S 006890f0 (construction of every sub-renderer), S 006898f0, S 006889d0. `CMapRenderer` also owns an
`ai::terrain::TerrainGenerator` at +0x58 (editor) and the float `streetDepthBias` at +0xf0 (CVar
"Street/DepthBias", range -1..1, 0.1 at construction) [known] S 006890f0.

### 2.5 Terrain structures

**`ai::render::TerrainPatternDef`** (0xc0 bytes; global array `g_TerrainPatterns`, data pointer S 0088dc80)
[known] S 006bade0:

| Offset | Type | XML attribute | Meaning |
|---|---|---|---|
| +0x00 | int | - | id = registration order (counter `g_TerrainPatternNextId`); the **blend rank** |
| +0x04 | std::string | `name` | pattern name; the link to the pattern names of the map |
| +0x20 | bool | - | `isAlias`: the pattern has an `alias` attribute |
| +0x24 | std::string | `texture` or `alias` | diffuse texture path, or the name of the aliased pattern |
| +0x40 | float[2] | `texScale` | diffuse UV scale (default 1 1) |
| +0x48 | std::string | `normal` | normal map path |
| +0x64 | float[2] | `nrmScale` | normal map UV scale (default 1 1) |
| +0x6c | int | `transition` | index into the transition mask list (§6.1) |
| +0x70 | int | `type` | shading mode 0..6 (§3.4) |
| +0x74 | float | `specularIntensity` | |
| +0x78 | float | `specularPower` | |
| +0x7c | float | `parallaxHeight` | read, 0.0 in all shipped patterns |
| +0x80, +0x8c, +0x98 | float[3] each | `ambient`, `diffuse`, `specular` | default 1 1 1 |
| +0xa4 | std::string | `groundCover` | ground cover layer name |

**`ai::render::TerrainPatternRecord`** (0x18 bytes; one per entry of the pattern source that has a definition, §3.3;
`CTerrainPatternManager +0x84`):
`patternIdx` (+0, index into `g_TerrainPatterns`), `mapPatternId` (+4, the id stored in the map's pattern grid),
`baseRecordIdx` (+8; for an alias: the record of the aliased pattern, else -1), `texture0` (+0xc), `texture1`
(+0x10), ground cover layer index (+0x14) [known] S 006bb3a0 (writes at S 006bb521..006bb552), S 006bbb60. One
record per pattern property whose `gfxName` has a `<Pattern>` definition (for an alias: whose target has a record);
any other pattern id gets no record and is not drawn [known] S 006bb3a0.

**`ai::render::TerrainCell`** (0xb4 bytes; `CTerrainCellMgr +0x14`, grid of `ceil(W/4) x ceil(H/4)`):

| Offset | Name | Meaning | Evidence |
|---|---|---|---|
| +0x04..+0x10 | `x0, y0, x1, y1` | cell rectangle (inclusive corners shared with the neighbours) | [known] S 006b6840 |
| +0x14, +0x18 | min, max height | integer heights over the block's vertices `(4*x0 + 2*(y0&1) .. 4*x1 + 2*(y1&1), 4*y0 .. 4*y1)` | [known] S 006b62b0 |
| +0x1c..+0x28 | neighbours | four block pointers, null at the map edge; order left, right, up, down [inferred] | [known] S 006b4ec0 |
| +0x2c..+0x40 | AABB | world bounds; min.y, max.y = the two heights times `heightScale`; max.y raised to the water height when the block's maximum height is below the water level | [known] S 006b62b0 |
| +0x54 | visible | in the frustum this frame | [known] S 006b55e0 |
| +0x64 | `TerrainPatch[]` | count, capacity, data (0x24 bytes each) | [known] S 006b65d0 |
| +0x70 | layers | `{recordIdx, firstPatch, patchCount}` (12 bytes) per pattern, ascending rank | [known] S 006b6840 |
| +0x58, +0x5c, +0x60 | eye distance squared, `lod`, `stitchMask` | §3.3 | [known] S 006b55e0 |
| +0x7c, +0x94.. | objects | merged AABB and list of attached map objects | [known] S 006b6400 |
| +0xa0 | revealed | fog of war: 0 = never explored by the local player (§3.7) | [known] S 006b5f80, S 006b4f80 |
| +0xa1 | dirty | set on reveal; makes the next visibility update re-apply object hiding | [known] S 006b5f80, S 006b4f80 |
| +0xa4.. | underwater patch list | built only when the block's minimum height is at or below the water level: indices of the solid patches whose cell has one of its 4 x 4 fine vertices `(4x + 2*(y&1) + i, 4y + j)`, `i, j = 0..3`, at or below it | [known] S 006b6840 |

**`ai::render::TerrainPatch`** (0x24 bytes) [known] S 006b65d0, S 006bd940: flags bit 0 = second triangle of the
quad, bit 1 = "one corner" blend (odd match count), bit 2 = blend patch (0 = solid), bit 3 = vertex cache valid;
+4 low nibble = edge mask of the block edges the triangle touches (1 left, 2 right, 4 top, 8 bottom); +5 = pattern
`type`; +8 bit 0 = built with the radial alpha (§3.3); +0xc, +0x10 = cell x, y; +0x14..+0x1c = world position of
the blend vertex; +0x20 = cached vertices (allocated for the vertex count of LOD 0).

**Terrain mesh vertex** (0x14 bytes, one per height vertex): float3 position, 3 bytes normal, 3 bytes tangent,
each byte `b` meaning `b * 2/255 - 1` [known] S 006bd940 (unpack); the normal bytes are copied from the terrain
grid's packed normals and the tangent is `(n x a) x n` normalised with the fixed axis `a` = the global unit X
vector [known] S 006c0410.

**Terrain draw vertex** (0x40 bytes) = input layout of `terrain_shader.fx` [known] S 006bd940 and file:

| Floats | Semantic | Content |
|---|---|---|
| 0..2 | POSITION | world position |
| 3..5 | NORMAL | unpacked normal |
| 6 | COLOR0 (ARGB) | 0xffffffff, or the under-water tint for `type` 1 (§3.5), alpha optionally replaced by a radial fade |
| 7, 8 | TEXCOORD0 | world x, z (scaled by `texScale` / `nrmScale` in the shader through texture matrices) |
| 9, 10 | TEXCOORD1 | transition mask UV (§3.3) |
| 11, 12 | TEXCOORD2 | map UV: `(x - minX) / extentX`, `(z - minZ) / extentZ` over the mesh bounds (first and last mesh vertex) [known] S 006bd560 |
| 13..15 | TANGENT | unpacked tangent |

### 2.6 Other structures (summary)

| Structure | Size | Content | Evidence |
|---|---|---|---|
| `S2CG::Building` | 0x218 | kind 6 (+0x04), logic building (+0x18), heading in radians (+0x28, [known] S 006ac8b2, read by S 006aab4c), type index (+0x30), gfx desc (+0x34), world position (+0x9c), hidden (+0xc0), fog visible (+0xc4), construction progress previous / current / fade end time / rate (+0xc8..+0xd4), under construction (+0xd8), the same four for the upgrade (+0xdc..+0xe8), upgrading (+0xec), upgrade gfx desc (+0xf0), demolish progress (+0xfc, negative = none), entrance street `pEntranceStreet` (+0x100, the door path, [world-objects-rendering.md](world-objects-rendering.md) §3.6), ground decal (+0x104), scaffold (+0x1fc), fire point count (+0x200), fire points (+0x208, 0x5c each) | [known] S 006aa1b0, S 006aabe0, S 006abbb0, S 006ab840; [inferred] S 006ac810 |
| `S2CG::BuildingDesc` | 0xc0 | name, mesh path, frame path; LOD mesh parts (+0x54), animated visual (+0x5c), bounds (+0x68 min.y, +0x74 max.y), door and work animations (+0x80..+0x88), production sub-desc (+0x8c), stage count (+0xa4), stage subset table (+0xa8), frame render object (+0xac) | [known] S 006aabe0 for bounds, [inferred] S 006d3880, S 006a15a0 |
| `S2CG::CCharacter` | 0xbc [inferred, mapped struct] | animation (+0x80), movement (+0x84), per-type logic face (+0x88), queued animation (+0xa4), effects (+0xb0) | [known] S 006909f0 |
| `S2CG::CharacterAnimation` | 0x6c [inferred, mapped struct] | model cache (+8), current track (+0xc), instance handle (+0x30), selection keys (+0x38, +0x3c, +0x40, +0x44), requested slot (+0x54), loop mode (+0x58), owner face (+0x60), one-shot playing (+0x64), idle sequencer (+0x68) | [known] S 006c64c0, S 006c6590 |
| `ai::render::CharacterMovement` | 0x160 | fog visibility byte (+0x04, §3.7; [known]), previous and target position (+0x2c, +0x38), inverse duration (+0x48), logic position (+0x4c), render position (+0x58), world matrix (+0x64, copied by `CCharacter::Update`), rotation matrix (+0xa4), yaw / target yaw (+0xe4 / +0xe8), forward vector (+0xec), yaw previous / current / time (+0xf8 / +0xfc / +0x100), snap-yaw flag (+0x108), lateral offset (+0x10c, with its previous / current / time record up to +0x11c), height target (+0x120, the death sink and the carrier's boat) with its interpolated previous / current pair (+0x124 / +0x128, [animation-models.md](animation-models.md) §3.19), figure height (+0x24, read by `IsBelowWaterLevel` S 006c4820), the spline-step flag (+0x135, read only by the carrier's boat S 006c934d), route spline | [known] S 006c48c0 (disassembly), S 006c4f40, S 006909f0, S 00690bd0; [inferred] S 006c57b0 for the rest |
| `S2CG::InstanceMesh` | 0x7c | object type (+4), id (+0xc), cell (+0x10), bounds, world matrix (+0x1c), colour (+0x5c), visibility byte (+0x6c; [TODO] not established: whether 1 means hidden or shown, read the constructor and the block's hide call S 006b4f80), handle (+0x70) | [inferred] mapped struct and ctor comment |
| `ai::render::MapObjDef` | 0xbc | one `<LandscapeElement>` (§6.4) | [inferred] S 0068f200 |
| `S2CG::EnvData` | 0x34 | background rgb, ambient rgb, light rgb, shadow intensity (+0x28), fog start and end (+0x2c, +0x30) | [inferred] S 006ae2e0 |
| `S2CG::EnvSphere` | 0x44 | `EnvData` + centre x, z (+0x34), inner radius (+0x3c), outer radius (+0x40) | [inferred] S 006ae350 |
| `ai::render::DaytimeKey` | 0x4c | one `<Daytime>` (§6.6) | [inferred] S 00684130 |
| `ai::rendering::WaterPreset` | 0xa8 | one `<WaterProperty>` (§6.2) | [inferred] S 006a8f00 |
| `MapBorderSegment` | 0x2c | AABB, texcoords, visible (+0x28), edge flags (+0x29) | [inferred] S 006a7fa0 |

---

## 3. Rules and algorithms

### 3.1 Frame structure and render order

`Scene::Render` S 006836b0 [known]:

1. copy the device view-projection matrix;
2. **shadow map view** if device quality > 1, the shadow setting is on and shadows are not suppressed
   (`RenderShadowMapPass` S 006810b0);
3. **reflection view** if the reflection setting is on (`RenderReflectionPass` S 00680ab0); it draws only the sky
   when both per-frame counters of the pattern manager are zero, and the scene when either is positive
   [known] S 00688f40: `CTerrainPatternManager +0x154` (visible blocks with a pattern of type 2 or 6 [inferred])
   and `+0x158` (visible blocks at or below the water level [inferred]; the same counter gates the water in
   `RenderObjectsAndWater`);
4. a pending screenshot;
5. create or destroy the post processor (0x6c bytes) to follow the POSTFX setting;
6. with a post processor and `Scene +0x75` clear: `BeginScene`, `RenderPasses(passMask)`, `EndScene`.

`Render` itself draws the main view only in step 6; without a post processor the main view is drawn by the next
stage.

`Scene::RenderPostFxAndOverlay` S 00680a00 [known]: without a post processor (or with `+0x75` set) it updates
the selection markers and runs `RenderPasses(passMask & ~0x100)`; with one it combines the frame
(`PostProcessor::UpdateFocusAndCombine`). Then the build-placement overlay (for the local player of the
selection context when its byte +0x50 is set, else for the player table's local player when the table has an
active player of type 2, else skipped), then `RenderPasses(0x100)` (particles). The selection markers are
therefore not updated on frames that go through the post processor [inferred].

The overlay is drawn by `Scene::RenderPostFxAndOverlay` after `Scene::RenderPasses` S 0067eb20 (sky,
`CMapRenderer::Render` terrain/streets/buildings, characters, items, animals and swarms, ships, single meshes,
projected decals, then `RenderObjectsAndWater` S 006889d0: map objects, water) and before the particle pass
(`RenderPasses(0x100)`). Its states come from `infomap_shader.fx` technique `Default` pass `RenderInfoIcons` (ZEnable
true, ZFunc LessEqual, ZWriteEnable false, alpha blend SrcAlpha/InvSrcAlpha, no alpha test, Cullmode CW); no
`SetRenderState` call sits in S 00688c40 or in `ConstructionMapRenderer` (`Begin` S 006b33e0, `AddCellsInRect`
S 006b36d0, `FlushQuads`, `End`) [PROVEN]. Nearer plants, rocks and animals (which write depth) cover the icons; water
and decals (no depth write) do not.

`Scene::RenderPasses(mask)` S 0067eb20 [known], in this order:

| Order | Mask bit | Content |
|---|---|---|
| 0 | - | bind the shadow map to sampler 5 (quality > 1 and shadows on); set cull mode `currentPass` |
| 1 | 0x001 | sky dome (fog per `+0x720`) |
| 2 | 0x020 | map, first part: `CMapRenderer::Render` (table below) |
| 3 | 0x008 | characters |
| 4 | 0x010 | items (goods) |
| 5 | 0x040 | animals, then ambient swarms |
| 6 | 0x002 | ships |
| 7 | 0x004 | single meshes (`MeshRenderer`) |
| 8 | 0x080 | projected decals, with cull mode 1, then cull mode back to `currentPass` |
| 9 | 0x020 | map, second part: `CMapRenderer::RenderObjectsAndWater` |
| 10 | 0x100 | particles, with fog switched off around them |
| 11 | 0x001 | draw the environment's particle layer (`CEnviromentMgr.envParticleLayer` +0x120, `DrawEnvParticleLayer` S 00683c20) if one exists; none is ever created in this build (§3.13), so the step draws nothing |
| 12 | - | unbind the shadow map |

"Shadows on" in this function = the shadow setting is on and `Scene +0x74` is clear; it also adds layer flag
0x10000 to the map flags of the call, and removes it otherwise. The map flags are `renderFlagsA` in the main view
and `renderFlagsB` in the reflection view [known] S 0067eb20.

Masks and flags of the two views [known] S 0067f6b0, S 0067f500, S 0067fb40:

- main view: `passMask` = 0x1ff and `renderFlagsA` = 0x3ff, each bit cleared only by its debug CVar
  (`SceneDetail/*`, `MapDetail/*`); `renderFlagsA` bit 0x20000 follows the reflection setting, 0x10000 the
  shadow setting, and bit 0x80 follows the settings boolean `Coverage` (`S2CG::Settings.bCoverageEnabled` +0x24,
  getter in slot 3 of the in-game settings interface S 00695c70; also the CVar `MapDetail/Coverage`). No map
  render function tests bit 0x80, and no function calls the setter in slot 2 (S 00695c60): the value is saved
  and loaded with the settings file and has no effect [inferred, plate of S 00695c60: the flag tests of
  S 006898f0 and S 006889d0];
- reflection view, from the detail level `d` = `toInt(detail * 4 + 0.5)`: `passMaskDefault` = 0x001 (sky);
  `d > 0` adds pass 0x020 and layer 0x1 (terrain); `d > 1` adds layer 0x8 (buildings); `d > 2` adds pass 0x008
  (characters); `d > 3` sets pass mask 0x1ff and layers 0x3ff. Layer 0x10000 is added when the shadow and the
  reflection setting are both on.

`CMapRenderer::Render(flags)` S 006898f0 [known], layer flags and order:

| Order | Flag | Layer |
|---|---|---|
| 0 | - | bind the exploration/height overlay texture to sampler 3 and the noise texture to sampler 6 (§3.7) |
| 1 | 0x00001 | terrain (`CLandscape::Render`; the ground cover argument is the constant 0, §3.6) |
| 2 | 0x00002 | streets, crossings, routes (`StreetSet::Render`, depth bias `streetDepthBias`, 0.1 unless the CVar "Street/DepthBias" changes it) |
| 3 | 0x00020 | territory border posts |
| 4 | 0x00008 | buildings; with 0x00100 the house ground decals first (same depth bias); 0x00200 adds the military flags |
| 5 | 0x00004 | map objects that are not clip-flagged (`MapObjLayer::RenderEntries`) |
| - | 0x10000 | modifier: use the shadow-receiving techniques |

`CMapRenderer::RenderObjectsAndWater(flags)` S 006889d0 [known]:

1. unless this is the reflection view: clip-flagged map objects, side 1 of the water plane; then, if flag 0x10:
   - the map border skirt (§3.5);
   - if the counter `CTerrainPatternManager +0x158` is positive and at least one block is visible: with shader
     level > 1 and flag 0x40 the caustics pass over the visible terrain (fog off); then the water surface: one
     quad per visible block whose minimum height is at or below the water level (flag 0x20000 = with reflection
     texture, 0x10000 = shadowed);
2. clip-flagged map objects, side 0 of the water plane;
3. unbind the overlay textures.

So the reflection view draws neither the border skirt nor the water. The building flags 0x100 and 0x200 are
tested only inside the 0x8 branch [known] S 006898f0.

Reflection view [known] S 00680ab0: `currentPass` = 3 and `+0x6c` = 1 for its duration, then 2 and 0;
`RenderPasses(passMaskDefault)`, or the sky dome alone. Mirror camera: the view matrix is pre-multiplied by a
reflection about the water plane (`diag(1, -1, 1)` with a y translation) S 006d7cc0, and user clip plane 0 is
`(0, +1, 0, -waterHeight)` when the camera is at or above the water height, `(0, -1, 0, +waterHeight)` when it
is below [known] S 006d7c30 (disassembly). Render target [known] S 006a64c0: the quality setting converted to
an integer level clamped to 0..4; level 0 = no target; width `128 << level` halved until it does not exceed the
device's maximum texture size, height = half the width; if creation fails, or 32 MB or less of texture memory
remain afterwards, the level is lowered by one and the step repeated.

### 3.2 Mirroring the simulation: the callback receivers

The scene registers one `NLogic::CallbackReceiver` (face +0xc) and one `NMap::CallbackReceiver` (face +8). The
broadcaster and its slot list are in `docs/sim/logic-core.md` §3.7. The vtable offset is the slot of the receiver
interface; slot and handler address are [known] from the 56 pointers of the vtable S 007f8e24, and the reaction
is [known] from the handler's code. The event name is [inferred] from the reaction and from the broadcaster
named in the handler's mapped comment. Slots +0x28, +0x2c, +0x34 and +0x38 point to an empty function.

| Slot | Event | Scene reaction | Handler |
|---|---|---|---|
| +0x00 | world load begin / end | map renderer, character manager and item manager off / on; on end rebuild swarm zones | S 0067eed0 |
| +0x04 | logic init begin / end | same without the item refresh | S 0067ef30 |
| +0x08 | building created | `BuildingRenderer::AddBuilding`; add to the pickable list | S 00681520 |
| +0x0c | building removed | detach from characters and the pickable list; then start the demolition (§3.9) if the building leaves remains (`Building::LeavesRemains` S 006aa2b0: the property has a remains id, both construction remainders are <= 0 and the logic building is not flagged destroyed), else delete the instance at once | S 00681560 |
| +0x10, +0x14 | upgrade started / cancelled | load the upgrade mesh / `EndUpgrade` | S 00681f10, S 00681f40 |
| +0x18, +0x1c | flag created / removed | map object `z_flag_00`, or `z_harbor_flag_00` when the flag has a harbor reference (the id of the reference object at flag +0x168, read at +0x17c, is valid), tinted with the owner's colour; register with the item manager (goods stacks at the flag) | S 00682ca0, S 00682de0 |
| +0x20 | settler created | `CCharacterMgr::CreateCharacter` | S 0067f0f0 |
| +0x24 | settler removed | destroy the character, if one exists | S 0067f120 |
| +0x30 | fight strike | one-shot particle effect `HitDamage` at the attacker's position, turned toward the target vertex | S 00683530 |
| +0x3c, +0x40 | street added / removed | `StreetSet::AddStreetFromRoute` / remove and detach characters | S 0067f150, S 0067f160 |
| +0x44 | street upgraded | `StreetSet::PromoteStreetToKind1` (texture set 1, §3.12) | S 0067f1a0 |
| +0x48, +0x4c | deposit added / removed | map object of the deposit's gfx name; occupancy bit | S 006815e0, S 00681650 |
| +0x50 | deposit level changed | `MapObjLayer::AddLevelFade` (§3.11) | S 0067f1b0 |
| +0x54, +0x58 | animal created / removed | `AnimalMgr::CreateAnimal` / `RemoveAnimal` | S 0067f230, S 0067f250 |
| +0x5c | settler path changed | `CCharacter::SetPath(1)` | S 00681690 |
| +0x60, +0x64 | good created / removed | `ItemMgr::CreateItemForLogicItem` / `DestroyItem` | S 0067f1d0, S 0067f1e0 |
| +0x68, +0x6c | good added to / taken from a pile | `ItemMgr::OnLogicItemAddedToPile` / `OnLogicItemRemovedFromPile` | S 0067f280, S 0067f2a0 |
| +0x70, +0x74 | remains created / removed | `BuildingRenderer::AddRuin` / `RemoveInstance` | S 0067f210, S 0067f220 |
| +0x78, +0x7c | doodad created / removed | map object; occupancy bit | S 006816c0, S 00681730 |
| +0x80 | ship created | `S2CG::Ship`; then refresh ship visibility for the local player | S 0067f2c0 |
| +0x84 | ship removed | `ShipMgr::RemoveShip` | S 0067f310 |
| +0x88, +0x8c | harbor place created / removed | map object `z_harbor_00` at the harbor cell | S 00682ec0, S 00682fa0 |
| +0x90, +0x94 | sea route created / removed | map object `RouteBuoy` at the first (and, with both end references valid, last) path cell; route decal when the path has more than one cell | S 00683040, S 00683260 |
| +0x98 | projectile source set | kinds 0, 2, 3: a render projectile from the source settler's template, launched at `gameTime`; kind 1 (catapult [inferred]): the logic projectile is bound to the render projectile the source building already owns | S 00681780 |
| +0x9c | projectile removed | remove the render projectile (kind 1: play its impact at `gameTime` first) | S 0067f340 |
| +0xa0, +0xa4 | sacrifice started / removed | `SacrificeBuilding::StartEffect` S 006ace00 (the definition's movie, back-dated by the ticks already run, `particles.md` §3.13) / stop the building's movie | S 00681850, S 00681890 |
| +0xa8, +0xb0 | sacrifice research / wait for goods | effect movies `sacrificeResearchGfx` (back-dated by the research's absolute start tick, S 006acf70) / `sacrificeWaitForGoodsGfx` (S 006ad050) | S 006818d0, S 00681900 |
| +0xac, +0xb4 | research ended / order ended | stop the sacrifice building's movie (one shared handler) | S 00681930 |
| +0xb8 | sacrifice applied to ship | `Ship::AddEffectInstance` with the definition's `buffGfxName` (`SacrificeProperty +0x3c`) | S 0067f3b0 |
| +0xbc | sacrifice applied to settler | `CCharacter::AddEffect` with the `buffGfxName` | S 006819a0 |
| +0xc0 | sacrifice applied to cell | one-shot particle effect `buffGfxName` at the cell, only if the cell is explored by the viewing player | S 00681fd0 |
| +0xc4 | building revealed by sacrifice | `Building::AddAttachment` with the `buffGfxName` | S 00681960 |
| +0xc8, +0xcc | chest created / removed | map object of the doodad property whose id is game config +0x44 (`chestDoodadId`), or +0x48 (`openChestDoodadId`) when the chest predicate `ai::logic::LogicChest::IsOpenable` S 00539210 holds; occupancy bit | S 006819e0, S 00681aa0 |
| +0xd0 | chest opened | swap the closed model for the opened one | S 00680c80 |
| +0xd4, +0xd8 | spawn point added / removed | marker map object; occupancy bit | S 00681b30, S 00681bb0 |
| +0xdc | spawn triggered | one-shot particle effect named by the spawn property | S 006820f0 |

`NMap::CallbackReceiver` (face +8; five slots, [known] from the vtable S 007f8f08 and the handlers' code; event
names [inferred]):

| Slot | Event | Reaction | Handler |
|---|---|---|---|
| 0 | height rectangle changed | update mesh positions, normals, height texels, block bounds, objects' ground height, streets; recompute the water's map edge extents; the territory border points are not rebuilt (§3.8) | S 0067ef80, S 006882e0 |
| 1 | pattern rectangle changed | rebuild the patches of the affected terrain blocks; recompute the water's map edge extents | S 0067efa0, S 00688360 |
| 2 | map re-initialised | re-initialise the terrain grid (S 00688050) and the map renderer | S 0067efe0 |
| 3 | territory changed | clear and rebuild the border point lists of all eight players (§3.8) | S 0067f010, S 006883c0 |
| 4 | exploration rectangle changed for a player | if that player is the viewing player: update the "FogOfWar" texture, the overlay texture and block reveal (only while the overlay is active), and mask building tiles; then refresh ship visibility | S 0067f020, S 00688d40 |

Both rectangle handlers contain a test whether the rectangle touches the map edge, but the edge extents are
recomputed on either outcome [known] S 006882e0, S 00688360.

A flag's model is chosen only when the flag is created. When a harbour is linked to an existing flag,
`NNet::Flag::LinkNavyObject` S 00669e60 announces the flag again (flag removed, then flag added), so the scene
replaces `z_flag_00` by `z_harbor_flag_00` [known] S 00669e60, S 00682ca0.

A flag's vertex is the fine-grid vertex of its cell, `vx = 4*cx + 2*(cy & 1)`, `vy = 4*cy` (`Scene::OnFlagCreated` S 00682ca0), so
`vy` is always even and the half step of `VertexToWorldPos` S 00687500 for odd `vy` never applies to a flag.
`g_MapVertexWidth` (0x00880fa8) is `4*mapWidth + 1` (`NMap::System::Init` S 00672430, `Load` S 00672030). World z grows with
`vy`; the 1.3 street-width shift is on z only and its sign is "toward smaller z when the hash <= 0.5" (below). [known, decompiled]

World position of a cell-anchored object in the handlers (flag, harbor place, route buoy, chest, spawn point):
`vx = cx*4 (+2 if cy odd)`, `vy = cy*4` in vertex coordinates, then the vertex-to-world rule of §2.1
[known] S 00680c80, S 00682ec0. Deposits and doodads pass their stored position unchanged; it is therefore a
vertex position [inferred] S 006815e0, S 006816c0.

The occupancy bitset `g_TerrainGrid +0x2c` (S 0088146c) has one bit per height vertex, index
`rowStride * vy + vx` with the row stride at `+0x28` (S 00881468) [known] S 00688050, S 006819e0. The handlers
set the bit of the vertex that holds a deposit, doodad, chest or spawn point model and clear it on removal; it
belongs to the render side [inferred].

### 3.3 Terrain geometry and pattern blending

**Mesh.** One vertex per height sample: `(4W+1) x (4H+1)` vertices [inferred: the sizes come from two virtuals
of the height source], 0x14 bytes each, positions from the height grid, normals from the terrain grid's packed
normals [known] S 006c0ec0, S 006c0410. A map quad `(x, y)` has the corners
`c0 = (x, y)`, `c1 = (x+1, y)`, `c2 = (x, y+1)`, `c3 = (x+1, y+1)` (cells) and is split into two triangles by row
parity [known] tables S 007fad68 (odd rows), S 007fad80 (even rows), read in S 006b65d0:

| Row `y` | Triangle 0 | Triangle 1 |
|---|---|---|
| even | c0, c1, c2 | c2, c1, c3 |
| odd | c0, c1, c3 | c3, c2, c0 |

Each triangle is a 4-fold subdivided patch of the fine vertex grid (the mesh vertex of cell `(x, y)` is at
`(4x + 2*(y&1), 4y)`) [known] S 006bd940 for the index base.

**The pattern grid stores one pattern id per cell, that is per triangle corner.** Blending happens inside
triangles whose corners differ.

**Rank.** A pattern's rank is its `TerrainPatternDef.id`: its position in `terrain_static_data.xml` (first
`<Pattern>` = lowest; a second `<Pattern>` with a name already registered is ignored) [known] S 006bade0,
S 006ba190, S 006b65d0. Later patterns draw over earlier ones. A pattern id of the map without a record has
rank -1 [known] S 006ba190.

**Patch construction per terrain block** `TerrainCell::BuildPatches` S 006b6840 [known]:

1. collect the distinct pattern ids of all cells `x0..x1`, `y0..y1` that lie inside the map; sort them by rank
   ascending (S 006b5280 with the comparator S 006b4eb0);
2. for each pattern `P` in that order, for each quad `x0..x1-1`, `y0..y1-1` inside the map, for each of its two
   triangles (`AddHexPatches` S 006b65d0), with `n` = number of corners whose pattern is `P`; a triangle with a
   corner outside the map is skipped:
   - **solid patch** if `n == 3`, or if `n` is 1 or 2 and no corner has a rank lower than `P`'s (`P` is the lowest
     pattern of the triangle);
   - **blend patch** if `P` is not the lowest-ranked pattern *of the block* and `n` is 1 or 2. The blend vertex is
     the one corner that has `P` (`n == 1`) or the one corner that does not (`n == 2`); flag bit 1 = (`n == 1`);
3. the patches of `P`, if any were added, form one layer `{record, first, count}`.

Consequences [inferred]: a pattern that is the lowest of its triangle but not of its block gets a solid and a blend
patch in the same triangle; three different patterns in one triangle give one solid (lowest) and two blend patches.

**Draw order** `CLandscape::Render` S 00689f10 [known]: (a) all solid patches, record by record ("base layers",
opaque, depth write, `ZFunc LessEqual`); (b) unexplored blocks in flat black; (c) all blend patches, record by
record ("transition layers", alpha blend `SrcAlpha / InvSrcAlpha`, no depth write, `ZFunc Equal`); render states
[known, file]. Only revealed blocks contribute to (a) and (c) [known] S 006bbde0, S 006bbeb0. Records are
ordered: non-alias patterns by rank ascending (a swap sort on `def+0`), then alias patterns in the order of the
pattern source, each linked to the first record whose pattern name equals its `alias` [known] S 006bb3a0. The
pattern source is **every pattern property, not the patterns the map uses** [known]: `Scene::Init` S 00682685
passes `&PropertiesDb.staticAccess` (`PropertiesDb +0x60`) to `CMapRenderer::CreateInstance` S 00689450, the
`CMapRenderer` constructor S 006890f0 hands it to `CLandscape::ctor` S 0068ad40 (stored as `patternInitArg`,
`CLandscape +0xc`), and `CLandscape::Init` S 00689c90 passes it on. Its vftable S 007e8030 gives slot 0
S 00556910 the size of the pattern map `PropertiesDb +0x28`, slot 1 S 00556a00 the n-th property's `gfxName`
(property `+0x20`, `pa_setGfxName`), slot 2 S 00556a10 its id; the n-th is an in-order walk of that `std::map<int>`
(`GetNthValueMap28` S 00556950), whose key compare is signed (`JGE`, S 00549040), so the source runs in **ascending
signed id** order. A property is matched to the first `<Pattern>` whose name equals its `gfxName` (exact byte
compare, S 00408080): pass 1 adds a record per matched non-alias pattern (`def+0x20 == 0`), the swap sort follows,
and pass 2 walks the source again and adds a record per matched alias whose target names a record present at that
moment. A property without a matching `<Pattern>`, and an alias whose target has no record, get no record; a map
cell whose id has no record is not drawn. The record writes are `[rec+0] = patternIdx`, `[rec+4] = id` (S 006bb521,
S 006bb524). The second argument (the ground cover renderer, `CLandscape +0x24`) is the `this` of
`GroundCover_FindLayerIndexByName` S 006be460 for a pattern with a ground cover; only afterwards is its stack slot
reused as the mask-texture loop counter. The per-record visible-cell lists (`+0x144`) are allocated for the number
of pattern properties, not of records. Quirk [known] S 006bb5b6: when pass 1 made no record, the sort's step count
`count − 1` wraps and the sort runs 2^32 − 1 empty steps (never with the shipped data, which has 114 properties).

**Transition mask coordinates** [known] S 006bd940; with `b` = blend vertex, `s = 1 / (4 * stepX)` (one over the
cell width) [known] S 006bd560:

```
u = ((x - b.x) * s + 1) * 0.25 + (n == 1 ? 0.5 : 0.0)
v = ((z - b.z) * s + 1) * 0.5
```

So a transition texture holds two square masks side by side, each centred on the blend vertex and spanning two
cell widths: the left half is used when two corners carry the pattern (the blend vertex is the hole), the right
half when one corner carries it (the blend vertex is the blob). The shader adds half a texel
(`0.5 * TextureParameter[1].zw`).

**Transition pixel** (`terrain_shader.fx`, `TerrainPixelShader`, `bUseTransitionTexture`) [known, file]:

```
alpha = mask.a
rgb   = light * (diffuse.rgb + (mask.r * 2 - 1))        // the mask's red channel brightens or darkens the seam
```

The mask texture is `Transitions[def.transition]`; for an alias pattern the diffuse and normal textures are those
of the aliased pattern's record, the UV scales, `type`, material and `transition` are the alias's own
[known] S 006bbb60.

**Optional radial alpha.** When `TerrainDrawBatch +0x64` is set, the vertex colour alpha of every patch (solid
ones too) becomes `d2` (flag bit 1 clear) or `1 - d2` (flag bit 1 set) with
`d2 = ((x-b.x)^2 + (z-b.z)^2) * s^2` [known] S 006bd940. `+0x64` (`lowShaderLevel`) is set by
`TerrainDrawBatch::BeginFrame` S 006bd460 at the start of every terrain draw to `effective shader level < 2`
[known], so the radial alpha exists only below shader level 2, for the fixed-function path whose
`TERRAIN_TRANSITION_2TEX` state block in `shared.inc` takes alpha from the vertex colour; the shader path never
uses it.

**Level of detail and stitching.** The unit is the terrain block (`TerrainCell`): 4 × 4 cells (S 00881e7c,
S 00881e80, constant), clamped at the map's last row and column (`CTerrainCellMgr::CreateTerrainCells`
S 006b73b0) [known].

*Selection* (`CLandscape::UpdateVisibleCells` S 0068a4a0, `GridQuadTree::Cull` S 006db440,
`TerrainCell::UpdateLOD` S 006b55e0) [known, disassembly], once per frame from the main camera (the only caller
chain is `Scene::Update` S 006805e0 → `CMapRenderer::Update` S 006888f0, besides the preview texture
S 00681300), so the shadow and reflection passes draw the levels chosen for the main view [inferred]:

```
eye         = A + 0.7 * (B - A)        // A, B: device+0x1b4 methods +8 and +0xc (position, target [inferred])
lodDistance = landscape+0x38 * landscape+0x3c + 1.15 * sqrt((4*stepX)^2 + (4*stepZ)^2)
d           = sqrt((c.x - eye.x)^2 + (c.z - eye.z)^2)     // c: centre of the block's bounding box; y ignored
lod         = min(2, trunc(d / lodDistance + 0.5))         // FPU control word 0xC00 (chop) around FISTP
```

- `landscape+0x38` is copied by the `CLandscape` constructor (S 0068ada8) from `g_Landscape_LodDistance`
  (S 0088d478, 0 until `<Landscape lodDistance>` is read; `Landscape_LoadSettingsXml` S 00689bf0;
  `game/settings/graphics.xml`: 50.0, one global value) [known].
- `landscape+0x3c` = `groundDetail * 5 + 0.25`, with `groundDetail` clamped to 0..1 (`CMapRenderer::SetDetailFactor`
  S 00688220; constructor value 1.0). `groundDetail` is `Settings+0x20`, read through `SceneSettings` method +4
  (S 00695c50; vtable S 007f9bfc) by `Scene::ApplySceneSettings` S 0067f500; the presets 0..4 set it to 0, 0.25,
  0.5, 0.75, 1 (`Settings::ApplyQualityPreset` S 00695860). It is not `Settings.detail` (method +0x5c), which
  drives the map objects' priority gate [known].
- `stepX`, `stepZ` are the map scaling (`g_MapTileStepX` S 0088cf4c and +8; `graphics.xml <Map scaling="1.5 0.001
  1.2990375">`), so the second term is 9.128 units. The same `lodDistance` is the radius argument of the block
  culling [known].
- The level is computed anew every frame, without hysteresis, for culled blocks as well
  (`GridQuadTree::HideSubtree` S 006da740), and switches hard: a change of level clears the "vertices built" flag
  (bit 3) of every patch of the block, and the next draw rebuilds them [known].
- Bands: level 0 while `d < 0.5 · lodDistance`, level 1 while `d < 1.5 · lodDistance`, else level 2. Per preset
  (`lodDistance` / the two borders, world units): 0: 21.6 / 10.8, 32.4; 1: 84.1 / 42.1, 126.2; 2: 146.6 / 73.3,
  219.9; 3: 209.1 / 104.6, 313.7; 4: 271.6 / 135.8, 407.4 [known, computed]. At the top preset and the original's
  zoom (eye at most 84 units from the focus, so the selection point at most about 25 units from it) the view near
  the focus is level 0; levels 1 and 2 lie toward the horizon, mostly in the fog.

*Geometry per level* (`TerrainDrawBatch::BuildStitchIndexTables` S 006bbfe0, `TerrainDrawBatch::AddPatch`
S 006bd940) [known]. A patch is one cell triangle. Its vertices are a subset of the fine mesh's own vertices
(position, normal and tangent as stored; no filtering), given as offsets `row * meshWidth + column` from the cell's
base vertex `(4x + 2*(y & 1), 4y)`; a fine row's vertices sit half a step to the right of the row below. Four
variants, `kind = (cellY & 1) + 2 * (patch.flags & 1)`: kinds 0 and 1 are the upward triangles (base row below,
apex above: `c0 c1 c2` in even rows, `c0 c1 c3` in odd rows), kinds 2 and 3 the downward ones (`c2 c1 c3`,
`c3 c2 c0`); kinds 0/1 and 2/3 share their tables. Counts per level (S 007fb0c0, S 007fb0cc, S 007fb0d8):

| Level | Subdivision of the cell triangle | Vertices | Triangles | Indices |
|---|---|---|---|---|
| 0 | 4-fold | 15 | 16 | 48 |
| 1 | 2-fold (every second fine vertex) | 6 | 4 | 12 |
| 2 | none (the three cell corners) | 3 | 1 | 3 |

Vertices (column, row) and triangles:

- level 0, upward: rows of 5, 4, 3, 2, 1 from the base: (0..4, 0), (0..3, 1), (1..3, 2), (1..2, 3), (2, 4);
  triangles `0 1 5, 6 5 1, 1 2 6, 7 6 2, 2 3 7, 8 7 3, 3 4 8, 5 6 9, 10 9 6, 6 7 10, 11 10 7, 7 8 11, 9 10 12,
  13 12 10, 10 11 13, 12 13 14`;
- level 0, downward: rows of 1, 2, 3, 4, 5 from the apex: (4, 0), (3..4, 1), (3..5, 2), (2..5, 3), (2..6, 4) for
  kind 2, columns 4 less for kind 3; triangles `2 1 0, 4 3 1, 1 2 4, 5 4 2, 7 6 3, 3 4 7, 8 7 4, 4 5 8, 9 8 5,
  11 10 6, 6 7 11, 12 11 7, 7 8 12, 13 12 8, 8 9 13, 14 13 9`;
- level 1, upward: (0,0) (2,0) (4,0) (1,2) (3,2) (2,4); triangles `0 1 3, 4 3 1, 1 2 4, 3 4 5` (S 007fb17c);
- level 1, downward: (4,0) (3,2) (5,2) (2,4) (4,4) (6,4) for kind 2 (columns 4 less for kind 3); triangles
  `2 1 0, 4 3 1, 1 2 4, 5 4 2` (S 007fb164);
- level 2, upward: (0,0) (4,0) (2,4), triangle `0 1 2` (S 007fb15c); downward: (4,0) (2,4) (6,4) for kind 2
  (columns 4 less for kind 3), triangle `0 2 1` (S 007fb154).

Solid and blend patches are built once per block, whatever the level (above); the level only picks the template when
a patch's 0x40-byte vertices are rebuilt (position, normal, colour, world xz, mask uv, map uv, tangent). The mask
coordinates are a linear function of x and z around the blend vertex, so the transition masks look the same at every
level; what changes with the level is the shape, the interpolation of the stored normals across larger triangles,
the under-water tint (computed per drawn vertex for under-water patterns), and, below shader level 2 only, the radial
alpha (also per drawn vertex) [known; the visibility of the change is inferred].

*Stitching* [known]. A block's four neighbours are x−1, x+1, y−1, y+1 (slots 0..3, own bits 1, 2, 4, 8, the
neighbour's opposite bits 2, 1, 8, 4). In `UpdateLOD` of block B, for every visible neighbour N (`+0x54`): if N's
level is finer (lower) than B's, N gets the stitch bit of the shared edge and B loses its own; otherwise, only if N
holds a stitch bit toward B, that bit is cleared and B's bit toward N is set when N is coarser (cleared when the levels
are equal). N's own update sets the remaining case. So of two visible neighbours with different levels, the finer one
stitches; equal levels never stitch. A change invalidates the neighbour's patch
vertices. Neighbours are read as they stand when B is updated, so a bit may lag by a frame [inferred].

In `AddPatch`, for a block of level 0 or 1 (a level-2 block never stitches) and every edge `i` that both the stitch
mask and the patch's own edge mask (`patch+4`, the block edges the cell triangle lies on) contain, the odd vertices
of that edge get the average of their two neighbours on the edge: the height and the normal; x, z, the tangent and
the other attributes stay. Two vertices at level 0 (the second and fourth of the five), one at level 1 (the middle of
three) (S 007fb1b4). The y−1 edge is the base row of upward patches (vertices 1, 3 at level 0; 1 at level 1), the
y+1 edge the base row of downward patches (row starting at vertex 10 at level 0, 3 at level 1; S 007fb1b0); the x
edges are slanted triangle edges, taken from triples (previous, target, next) per kind and level from S 007fb1b8:

| Kind | Level 0 | Level 1 |
|---|---|---|
| 0 (upward, even row; left edge) | (0,5,9) (9,12,14) | (0,3,5) |
| 1 (upward, odd row; right edge) | (4,8,11) (11,13,14) | (2,4,5) |
| 2 (downward, even row; right edge) | (0,2,5) (5,9,14) | (0,2,5) |
| 3 (downward, odd row; left edge) | (0,1,3) (3,6,10) | (0,1,3) |

Consequence [inferred]: the averaging matches a neighbour exactly one level coarser. A level-0 block next to a
level-2 block keeps its edge's middle vertex at its true height while the coarse edge is straight, so a crack can
open; with blocks 24 units wide this needs a band narrower than a block, which happens only at the lowest
`groundDetail` (`lodDistance` 21.6).

**Culling** [inferred] S 0068a4a0, S 006db440: quadtree over the blocks, frustum test with six planes, plus a
horizon occlusion buffer fed with the ground edges of accepted blocks, used only while the view direction's y
component is above -0.2 [known] S 006db440. A Godot renderer needs none of this for correctness.

### 3.4 Terrain shading (`terrain_shader.fx`) [known, file]

Samplers: 0 = diffuse (`texScale`), 1 = transition mask, 2 = normal map (`nrmScale`), 3 = overlay ("WorldTex",
§3.7), 4 = cube map or reflection texture, 5 = shadow map, 6 = fog noise.

Common part:

```
N     = 2 * normalMap.rgb - 1                      // tangent space
L     = normalize(TBN * -mainLightDir)             // B = cross(tangent, normal)
light = lightColor.rgb * saturate(dot(N, L)) * shadow + ambient.rgb
rgb   = light * diffuse.rgb                        // or the transition formula of §3.3
if type != 1: rgb *= vertexColor.rgb
```

| `type` | Pass | Extra |
|---|---|---|
| 0 | BaseLayer | none |
| 1 | BaseLayerCaustics (under-water ground) | `rgb = lerp(vertexColor.rgb, rgb, vertexColor.a)`; UV wobble below `y = -0.15`: strength 0.008 (scaled `-y * 1.42` between -0.15 and -0.7), `sin((t + (z + y) / 0.4) * 2.25)` on u and `sin((t + (x + y) / 0.4) * 2.25)` on v |
| 2 | BaseLayerSwamp | `rgb = lerp(rgb, cubeMap(cameraPos - pos + 5*sin((1.5t + x + z) * 1.5)), diffuse.a)`; v wobble `sin((t + (x + y) * 0.1) * 1.5) * 0.004` |
| 3 | BaseLayerSpecular | `rgb += normalMap.a * k * pow(saturate(dot(R, V)), specularPower)` with `k = specularIntensity * specular` (computed per vertex into the colour alpha), `R = normalize(2 * lightRgb * N - L)` (`lightRgb` = the direct light colour term before ambient, as written in the shader), `V` = tangent-space view vector |
| 4 | BaseLayerLava0 | `rgb = lerp(rgb, lerp((1, .3, 0), (1, .7, .4), tex2(uvWobbled).a), diffuse.a)`; wobble 0.04 at speed 2.25, counter-wobble 0.02 at 1.3 |
| 5 | BaseLayerLava1 | the colour formula of 4; no wobble; the lava lookup scrolls: `v += frac(t * 0.1)` |
| 6 | BaseLayerIce | planar reflection: the water reflection texture (or the cube map when there is none), projective lookup offset by `normalMap.a * 8 * 0.015 * camera.y`, toned (`*0.8` r and g, `*1.5 - 0.25`, 60 % desaturated), blended by `diffuse.a` |

Technique set: 7 base passes, 7 transition passes, 1 `Unexplored` pass, in the techniques `Default` (shadowed),
`NoShadow`, `LowDefault`, `LowNoShadow`, `ffp_min` and `ffp` [known, file]. The manager picks
`techniqueHandles[base + clamp(type, 0, 6)]` with base 0 (solid) or 7 (blend) [known] S 006bbb60,
S 006bbde0, S 006bbeb0, and handle 14 for unexplored blocks S 006b9d60. The handle order is the name table
S 00881eb0 [known, bytes]: `BaseLayer`, `BaseLayerCaustics`, `BaseLayerSwamp`, `BaseLayerSpecular`,
`BaseLayerLava0`, `BaseLayerLava1`, `BaseLayerIce`, then the seven `Transition*` names in the same order, then
`Unexplored`; this fixes the `type` to pass mapping of the table above (the order of the passes in the file is
different). In the `Default` technique the three transition passes Lava0, Lava1 and Ice are compiled without
the shadow lookup [known, file]. For `type` 6 the reflection texture of the water renderer is bound to sampler 4
when it exists, else the environment cube map [known] S 006bbb60.

Every pass ends with `CalcFOW` (§3.7). Shadow lookup: §3.13.

### 3.5 Water, coast and map border

**Where water is drawn** [known] S 006889d0, S 006a7de0, S 006a6a40: one flat quad per visible terrain block whose
minimum height lies **strictly below** the water level, at the water height. Two tests apply: the block's minimum
height at or below `seaLevel` (`IsMinHeightAtOrBelowSeaLevel` S 006b4f60), and the FCOMPP test of
`AddWaterTileQuad` S 006a7de0, which draws only when `heightScale × WorldRenderer +0x4a0` (−100, set in the
constructor at S 006a925d) is greater than the block box's lowest y; a block whose lowest vertex sits exactly at
the water level gets no water. The quad spans the block's box in x and z and ends two vertex steps before the box's
far end (`EmitWaterQuad` S 006a6a40, shader level ≥ 2 path). The box comes from `TerrainCell::Init` S 006b61f0:
its x and z extents follow the block's cells (`CTerrainCellMgr::CreateTerrainCells` S 006b73b0, with the row
overhang), but the overhang term `stepZ × overhangY` is added to the box's maximum **y**, not its z (disassembly
S 006b6282..S 006b628d), and `UpdateHeightRange` S 006b62b0 then overwrites y, so a block's z ends at its last
row [known]. The lowest height is taken over the vertices S 006b62b0 reads (§2.5). Quads are batched up to 8000
vertices. The reflection request uses only the at-or-below test (S 006b4f60), a superset of the blocks that get
water [known]. The coast
line is therefore not geometry: it is the intersection of that plane with the terrain, softened in the pixel
shader by the height channel of the overlay texture.

**Water pixel** (`water_shader.fx`, `Water_PS_2_0`) [known, file]:

```
uv0 = (pos.xz * (0.19, 0.17) * 0.3) * texMatrix0 ;  uv1 = (pos.zx * (0.23, 0.19) * 0.3) * texMatrix1
N   = normalize((2*normalMap0(uv0 * 1.7) - 1).xzy * (2*normalMap1(uv1 * 1.6) - 1).xzy * 2)
D   = lerp(1, 0.4, saturate(dot(L, N))) * lightColor.rgb + ambient.rgb
C   = lerp(waveColor, waterColor, N.y)
rgb = saturate(D) * lerp(C, mirror(reflUV + reflectionNoise * N.xz), reflectionFactor * D.r)   // with mirror
rgb = D * C                                                                                    // without
a   = (mirror.r + 0.15) * saturate(opacity.y - |V.y| * opacity.x)
a  += saturate(pow(dot(normalize(L + V), N), 8)) * 0.4 * 0.6
a  *= saturate(1.2 - overlay.b)            // overlay.b = 1 - normalised terrain height: fades out toward the shore
rgba *= saturate(shadow + 0.8)             // shadowed techniques
rgb *= overlay.a ;  a += 1 - overlay.a     // unexplored water is opaque black
```

**Quirk (presentation only): the reflection warps up close.** `reflectionNoise * N.xz` is added to the projective
coordinates before `tex2Dproj` divides by `w`, so the shift on screen grows as one over the depth: about twelve times
larger at 5 units than at the usual 60 [known, file; arithmetic]. The remake may cap it.

`texMatrix0/1` are rewritten every frame by `WorldRenderer::UpdateWaterAnimation` S 006a65a0 [known]: rows
`(cos a, sin a)`, `(-sin a, cos a)` and the translation row `(t * k0, t * k1)`, with `t` the accumulated frame time;
there is no scale term, so `tex0Scale` / `tex1Scale` do not enter these matrices. That `a` is `tex0Rot` / `tex1Rot`
and `k` is `phaseSpeed0` / `phaseSpeed1` is [inferred]: the angles reach the `sin` and `cos` calls on the FPU stack,
and which global the parser S 006a93c0 fills from which key is [TODO]. Blend `SrcAlpha / InvSrcAlpha`.
The preset (`WaterProperty`) is chosen per map by the index at `MapInfo +0x1cc` when the map renderer is
initialised for a map [known] S 006883e0 (the save version that carries the field: `docs/sim/save-format.md`);
out-of-range indices fall back to 0 [known] S 006a66e0.

**Under-water ground tint** (patterns of `type` 1) `TerrainDrawBatch::ComputeUnderwaterTint` S 006bd770
[known, disassembly], per vertex with world height `y`:

```
d = (y + 0.05) / 7.0
if d >= 0:  colour = 0xffffffff                      // no tint
if d <= -1: colour = 0x00000000                      // black, alpha 0 (y <= -7.05)
t = clamp(-sin(d * pi/2), 0, 1)
if y > -10:  t *= 0.97                               // always true in this branch
if y < -0.1: t = clamp(t, 0.07, 1)
rgb   = lerp(shallowColor, deepColor, t)
alpha = 1 - t
```

`shallowColor` and `deepColor` are the globals S 00881ae0 and S 00881af0, copied from the active water preset
(+0x88 and +0x98 of the 0xa8-byte preset) [known] S 006a66e0; that these are the XML attributes of the same
names is [inferred]. The shader then computes `lerp(vertexColor.rgb, lit, vertexColor.a)` (§3.4). The same
constants appear as `g_waterHazeMin 0.05`, `g_waterHazeMax 7.0`, `g_waterHazeAbsoluteMax 10.0`,
`g_waterHazeMaxOpacity 0.97`, `g_waterHazeMinOpacity 0.07` in `terrain_shader.fx` [known, file].

**Caustics** (`RenderUnderwaterSurface`, additive `One / One`, shader level > 1) [known, file]: drawn over the
visible terrain; texture `caustics.tga` is a strip of 16 frames; `frame = floor(frac(t * 0.2) * 16)`, cross-faded
with the previous frame by `frac`; UV = world xz `* 0.05 * 0.8`, u additionally `/ 16`; intensity 0.7, modulated
by `1 - sin(.4x + sin t) * sin(.4y + sin t) * sin(.4z + sin t)` and by `1 - saturate(depth * 0.15)`, zero where
`depth <= 0.1`, with `depth = 100 - y` as written in the shader. The pass draws the terrain draw batch, whose
vertex positions are world positions (`TerrainMesh::UpdateVertexPositions` S 006bec70 through
`TerrainGrid::VertexToWorldPos`: height times `g_MapHeightScale`, 0.001, so `y` lies between about -3 and 30)
[known]. So the factor `1 - saturate(depth * 0.15)` is 0 for every terrain vertex (it is above 0 only for
`y > 93.3`) and the additive pass adds nothing to the picture [inferred: arithmetic]; a remake can leave it out.

**Map border skirt** `WorldRenderer::BuildMapBorderSegments` S 006a7fa0, `ComputeMapEdgeExtents` S 006a77d0,
`RenderMapBorder` S 006a7400, `EmitWaterQuad` S 006a6a40 [known, decompile and disassembly]:

- *Edge height*: one value for the whole map, the lowest height of the edge cells (S 006a77d0). A second copy,
  S 006a79c0, is called from S 006882e0 and S 00688360 when a height change rectangle touches an edge cell; the
  segments themselves are built once, in `InitForMap` S 006a88f0.
- *Segments*: one per edge block plus the four corners, each extending its block `BorderReach` = 200.0 world units
  (double S 007e2a78) beyond the map edge. The extents are coded per case: the corner with edge flags 0xc has an
  inverted z range, corner 6 an extra step, left blocks `+3·step`, right blocks `−4·step` (doubles 3.0 S 007e5358,
  4.0 S 007e5b38, 1.0 S 007d8a08). A segment (`MapBorderSegment`, §2.6) carries its edge flags at +0x29.
- *Drawing*: two passes with the water effect's pass `RenderMapBorderGround` (`WorldRenderer +0x54`, looked up in
  S 006a8a20), no depth write, no culling. Pass 1 is sloped: the corners on the map side sit at the edge height, the
  outward corners at the water level − 1, chosen by the edge flags. Pass 2 is flat at the water level. The skirt is
  drawn after the map's own passes and before the water (`CMapRenderer::RenderObjectsAndWater` S 006889d0), so the
  water over the outermost blocks lies on black and looks darker there.
- *Colour*: black, set by the technique, not by code [known, file `gfx/fx_20/water_shader.fx`, the same pass in
  all five techniques `Default`, `NoShadow`, `LowDefault`, `LowNoShadow`, `ffp`]: fixed function (no vertex or pixel
  shader), `TextureFactor = 0`, `ColorOp[0] = SelectArg1` with `ColorArg1[0] = TFactor`, stage 1 disabled, no
  alpha blend, `ZWriteEnable = False`, `ZFunc = LessEqual`. `RenderMapBorder` S 006a7400 binds the two water
  normal maps to stages 0 and 1 (`WorldRenderer +0x58`, `+0x5c`), but the stage setup never samples them. The pass
  sets no fog state, so the device's per-pixel linear fog (§3.13) applies as the scene left it: `RenderObjectsAndWater`
  is called with the scene's fog flag and switches fog only around the underwater surface, so with fog on the skirt
  turns from black to the background colour over the fog range [known] S 006889d0, S 004d3a80.
- *No water beyond the map.* Water is drawn only as the per-block quads above. The two border-water techniques
  `RenderMapBorder` / `RenderMapBorderNoMirror` (`WorldRenderer +0x4c` / `+0x50`) are looked up in S 006a8a20 and
  used by none of the water renderer's methods; beyond the edge the player sees black.

**Fixed-function fallback** (shader model < 2): 64 pre-animated frames `water00..63.dds`, parameters
`TextureScaleFFP`, `TextureAnimSpeedFFP`, `OpacityFFP`, `TextureMoveSpeedFFP` [inferred] S 006a8a20. A remake does
not need it.

### 3.6 Ground cover (grass shells)

`GroundCoverRenderer` (`groundcover.fx`) draws, for patterns with a `groundCover` attribute, `sliceCount` shells of
the terrain patches: slice `i` has `t = (i + 1) / sliceCount`, vertical offset `height * t`, horizontal bend
`t^2 * bend * sin(phase)`, alpha-test reference `1 - t`; the layer's `opacity` texture (blade mask) is tiled by
`density` [inferred] S 006be2d0, [known, file] for the parameter block `GRASS_PARAMETER = (height, t, height*t,
t^2*bend)`.

`CMapRenderer::Render` calls `CLandscape::Render` with the ground cover argument fixed to 0 [known] S 006898f0.
It is the only caller of `CLandscape::Render` S 00689f10, which in turn is the only caller of
`CTerrainPatternManager::RenderGroundCover` S 006b9dd0 [known, cross-references of the function cache], so this
build draws **no** ground cover.

### 3.7 Exploration display (fog of war)

The simulation keeps one byte per cell and player: explored or not (`docs/sim/map-resources.md` §3.7). There is no
second "currently visible" state, so the display has two states only: unexplored and explored [inferred].
The viewer is the local player.

Three mechanisms:

1. **Terrain blocks.** A block covers the cells `4b .. 4b + 4` on each axis, its edge cells shared with the
   neighbouring block, so an explored edge cell reveals both [known] S 006b5f80, S 006b6ea0. A block is
   *revealed* once any of its cells is explored (`TerrainCell::RevealFromExploreMap` S 006b5f80, rectangle
   converted with a margin of one block by `CTerrainCellMgr::RevealCellsInRect` S 006b6ea0) [known]; a block is
   never un-revealed by exploration changes. An unrevealed visible block is drawn whole in the `Unexplored` pass:
   flat colour 0 (black), depth written [known, file and S 006b9d60]. **Block objects** are attached to the block
   of their cell divided by 4 (`CTerrainCellMgr::AddObject` S 006b7070): map objects, goods piles, flags and
   buildings. They are hidden unless the block is both in view and revealed (`TerrainCell::SetVisible`
   S 006b4f80, which calls slot 0 of the object's vtable), except map objects whose type virtual returns 2
   [known] S 006b4f80, S 006b7070. For a building (`S2CG::Building` vftable S 007fa79c, §3.9 "When a building
   updates") slot 0 is `SetHidden` S 006aa320, which writes `hidden` (+0xc0), and slot 1 S 006ab260 returns that
   integer [known]. Of the three subclasses, `SacrificeBuilding` (S 007fa85c) and `FarmBuilding` (S 007fc06c)
   override slot 0 and call `Building::SetHidden` from it (S 006accd0 also shows or hides the sacrifice effect
   list; S 006d55b0 shows the first `visibleModelCount` production props or hides all of them), and
   `CatapultBuilding` (S 007fc0d4) keeps it; none overrides slot 1 [known: RTTI and slots of the four vftables]. `TerrainCell::SetVisible` is its only writer,
   driven every frame by the main view's quadtree cull (`GridQuadTree::Cull` S 006db440 → S 006db220 →
   S 006daff0 / `HideSubtree` S 006da740), so a building is hidden unless its anchor's block is both revealed and
   in the view frustum [known]. Hiding does not stop the building's per-frame model update (§3.9), but it gates
   its door and collapse sounds and the start of its clips' events (§3.9).
2. **Overlay texture** "WorldElevationMap" [known] S 006c0ca0, S 006bef70, S 006bed80: `(2*W + 1) x H` texels,
   format 0x15 (A8R8G8B8), one mip level (`Create(2W + 1, H, A8R8G8B8, 1)`), filled with 0xff at creation; cell
   `(x, y)` owns the texels `2x` and `2x + 1` of row `y`, shifted right by one texel on odd rows (matching the
   half-cell shift); the one texel left over per row takes the alpha of its neighbour. On a partial update (an
   exploration rectangle) `ApplyVisibilityMask` S 006bef70 writes each row's left-over texel from the
   rectangle's edge cell [known], so it can light half a cell beyond the explored area [inferred]. Alpha = 0xff
   for an explored cell, 0 for an unexplored one; blue =
   `1 - clamp((h - hmin) / (hmax - hmin), 0, 1)` with `h` = the height at the cell's vertex and `hmin`, `hmax` =
   `g_TerrainGrid +8`, `+0xc` (§2.1). It is bound to sampler 3 with the texture matrix
   `u = x / (4*W*stepX) + 0.5 / (2*W + 1) + 0.5`, `v = z / (4*H*stepZ) + 0.5 / H + 0.5` (the `+ 0.5` undoes the
   centring of the world, §2.1) [known] S 006bf390, and sampled by every scene shader:

   ```
   CalcFOW(c, uv):   a = overlay(uv).a
                     c.rgb *= a
                     c.rgb = lerp(noise(uv * 16).rgb * c.rgb, c.rgb, a)       // noise = fow_noise.tga, sampler 6
   CalcFOWWithAlpha: as above with c *= a (the alpha fades too)
   ```

   that is `c.rgb × a · lerp(noise, 1, a)` [known, `shared.inc`]. `CalcFOWWithAlpha` with an alpha test draws
   the border posts (§3.8). The noise texture is `[data]/map/textures/fow_noise.tga` (128 × 128, 24 bits, grey
   noise [known, file]), loaded by `TerrainMesh::Create` S 006c0ec0 and bound to sampler 6 [known] S 006c0ec0,
   S 006bf390. Sampler 6 is point-sampled with Wrap addressing, so the noise is read unfiltered at 16 × the
   overlay coordinate; sampler 3 (the overlay) is filtered linearly with Wrap addressing, and only
   `water_shader.fx` overrides its addressing to Clamp [known: the `SAMPLER_n` defaults of `shared.inc`, the
   defines at the top of `water_shader.fx`]. The linear filter gives the alpha ramp a soft, noise-modulated edge
   about one cell wide. In the low quality mode of the terrain mesh whole texels are written instead
   (0x00ffffff explored, 0xff000000 unexplored) and no height is stored [known] S 006bef70, S 006bed80; below
   shader level 2 the texture matrix is built in camera space for the fixed-function stages [known] S 006bf390.
3. **Objects.**
   - **Characters are hidden in the fog.** While the overlay is active, `CharacterMovement::Update` S 006c57b0
     sets its visibility byte (movement +4) to `NMap::Exploration::IsExplored(logic cell, player)` for the
     player of the update (§4.3 step 5; with no grid or player the byte keeps its value); with the overlay off it
     sets the byte to 1. `CCharacter::IsInFrustum` S 00690f80 requires the byte, so a settler on a cell the
     viewing player has not explored is not drawn, and a hidden settler's speed particle effect stops [known].
     Besides, the character manager culls by the visible block rectangle S 00692a30 [inferred]. Carried goods
     are hidden with their carrier (`CCharacter::SetVisible` S 006919b0) [known].
   - Animals are hidden on unexplored cells (`Animal::UpdateVisibility` S 006cdfb0, the test at S 006cdfe3)
     [known].
   - A ship is drawn only while its current cell is explored by the local player; the flag is recomputed while
     the ship moves and on every exploration change [known] S 006a4e60, S 0067f020.
   - The resource effects receive the exploration grid and the player [inferred] S 006805e0, S 0068b220.
   - Buildings are block objects (item 1) and also have a fog-visible flag (`Building +0xc4`): the model is shown
     only when the flag is set and the building is not hidden [known] S 006aa150. `BuildingRenderer::AddBuilding`
     S 006a2bf0 calls `SetFogVisible(true)` when the building is not hidden; afterwards the flag follows the
     explored state of the building's anchor cell on every exploration change whose rectangle covers the anchor
     (`BuildingRenderer::ApplyVisibilityMaskToTiles` S 0069fe80 → `SetFogVisible` S 006aa150) [known].
   - Picking: `nGame::Cursor::PickVisibleEntityAtMouse` S 00787cc0 drops a building whose anchor cell is
     unexplored, but it tests the exploration of the building's owner (`+8`), not the local player's [inferred]
     ([camera-input-cutscenes.md](camera-input-cutscenes.md), click selection).

The debug CVar "SceneInfo/FogOfWar" (on by default) switches the overlay off for the whole map (all alpha 0xff,
all blocks revealed) and on again (everything hidden, then the viewing player's exploration applied)
`CLandscape::SetFogOfWarOverlay` S 0068a120, called from `Scene::Update` when the CVar changes
[known] S 006805e0, S 0067fb40.

A second texture "FogOfWar" (`W x H`, A8R8G8B8, 0xff000000 = hidden, cleared to 0 per explored cell) lives in
`CEnviromentMgr +0x11c` S 006aefd0, S 006aeef0 [inferred]; it is resized to the map when the map renderer is
initialised and updated on every exploration change of the viewing player [known] S 006883e0, S 00688d40.
[TODO] not established: its consumer (candidate: the sky; the environment particle layer of §3.13 does not
exist in this build); an xref read of the texture's bind calls settles it.

### 3.8 Territory borders

`BorderMgr::BuildPlayerBorders` S 006b29c0 builds, for each player index 0..7, a `PlayerBorderPoints` list:
every cell whose territory owner is that player and whose grid flag 0x20 (territory border) is set; the cell is
appended to list A (land) when the grid flag 0x4 (water) is clear, to list B (water) when set [known] S 006d8f50
(the flag names are those of `docs/sim/map-resources.md`). A land point is the world position of the cell's sample
vertex at its stored height (`TerrainGrid::CellToWorldPos` S 00687790) [known] S 006d8f50, S 00687790. The points
are appended in a greedy nearest-neighbour order starting from the last cell of the scan (squared cell distance,
strict `<`, so the first index wins a tie; the chosen cell is swap-removed with the last remaining one). The posts
have no rotation and their heights depend on the position, not the index; the order shows only where two posts
overlap with blended alpha (`border_shader.fx`: z write, alpha blend, alpha test 127, the fog-of-war alpha), where
the one drawn later lies on top [known] S 006d8f50, S 006b2ae0. The lists of all eight players are cleared and rebuilt whenever the map fires slot 3 of
`NMap::CallbackReceiver` (§3.2) [known] S 0067f010, S 006883c0; there is no other caller of S 006b29c0. A height
change (slot 0) therefore leaves the stored land points as they are: after levelling under a border the land posts
keep their old height, floating above or sunk into the new ground, until the next territory change rebuilds the
lists [inferred from the caller list]. Presentation only.

Drawing (`ai::render::BorderMgr::RenderSet` S 006b2ae0) [inferred, except where tagged]; the file names are
constants of `BorderMgr::ctor` S 006b3290 [known]. List A is drawn with the mesh `[data]\map\objects\limes.GR2`, list B with
`[data]\map\objects\buoy.GR2` (a `.GR2` name is loaded as the `.KEX` file of the same base name), one instance per
point (a float4 position per instance, no rotation); a player's set is skipped when its bounding box is outside the
frustum. The tint is the player's colour, white when the set has no player (`Render_GetPlayerColorOrWhite`
S 006d8d00) [known]. A land post stands at its stored point. A water post's height is computed at the sea level
(`TerrainGrid::GetSeaLevelHeight` S 00687050) every frame, with a bob [known: disassembly of S 006b2ae0]:

```
y = seaLevelHeight + 0.05 * sin(t * 2π * 0.3 + x + z)
```

`x`, `z` are the point's world position in the original's axes; 2π is the constant at S 00882840, 0.3 the one at
S 007e6af0, 0.05 the double at S 007e6d80; `t` is the time the render call receives [inferred: as for the route
buoy, §3.11]. `BorderMgr::RenderWithEffect` S 006b2d80 draws the same sets with an effect passed in by the caller:
it is the shadow-map pass (`ShadowManager::RenderCasters` S 0069e2a0 → `CMapRenderer::RenderWithExternalEffect`
S 006884a0, which calls it only while the render flags hold bit 0x20; `Scene::RenderShadowMapPass` S 006810b0
copies the scene's shadow mask into those flags). `Scene::ApplyShadowQuality` S 0067f420 sets the mask to 0 below
level 2, 8 at level 2, 0xC at levels 3 and 4 and 0x3FF from level 5, so the posts cast shadows only from shadow
level 5 [known]. Shader `border_shader.fx` [known, file]:

```
rgb = (ambient + lightColor * saturate(dot(N, -L)) * shadow) * lerp(playerColor * 1.8, tex.rgb, tex.a)
```

then `CalcFOWWithAlpha`; alpha test `> 127` and alpha blend. `CalcPlayerColor` (this formula) is shared by all
player-tinted objects [known, `shared.inc`].

### 3.9 Buildings

**Type lookup** [known] `BuildingRenderer::AddBuilding` S 006a2bf0: key = the `TribeProperty` name of the
building's placement tribe (`NVillage::Building +0x34`, through `ResourceDb_GetNameCStr` S 00687340) + `"_"` +
`BuildingProperty.gfxName` (+0x20, `bp_setGfxName` S 0054d160), matched against `buildings.xml`
`<Building name=..>` exactly (equal length and bytes, case-sensitive); on a miss no instance is made. Instance
class by the building property, tested in this order: working mode (+0x80) 9 → `SacrificeBuilding`, catapult
(+0xb0) → `CatapultBuilding`, `gfxBreeding` (+0xf3, test at 006a2ea6) → `FarmBuilding` S 006d59e0 (which shows the
description's `<Production>` models), else plain `Building` [known] S 006a2bf0.

**Assets per type** `BuildingDesc::LoadResources` S 006d4060, `BuildingDesc::LoadFromXml` S 006d3880 [known
unless tagged]:

- *Animated model.* The `mesh` file is also loaded as the type's animated model (`CAnimatedObject`, scale 1.0,
  `BuildingDesc +0x5c`). Its skeleton holds the moving parts (`door`, `wheel`, ... bones), `MILFLAG`
  (`BuildingDesc +0xbc`), the `FIRE_%02d` nodes (of which every third, from `FIRE_03`, is a fire point, §3.9) and
  the `boneLink<i>` bones of `<Production>`. `DoorOpen`, `DoorClose` and `Working` (`+0x80`, `+0x84`, `+0x88`, -1
  when absent) are animation-only KEX files played on that skeleton; the child elements of an animation element
  (`<Sound start name duration>`, `<Particle start duration name slot offset>`) become timed events of that
  animation (`EffectScriptMgr::LoadAnimEvents`).
- *LOD meshes* (`BuildingDesc +0x54`, parts of 0x18 bytes): part 0 = the `mesh` file, part 1 = the path up to
  its first `.` + `LOD0` + the rest, part 2 = `...LOD1...`, as long as the file exists (`.gr2` is read as
  `.KEX`). Each part is one mesh of its file: the mesh named `House`, else the first mesh. Data: 36 of the 106
  distinct `mesh` files have a `LOD0` file, none has `LOD1`; 97 have a `House` mesh, the other 9 (the 3 ruins
  and 6 houses) are read from their first mesh [known, data]. The bounds `+0x64..+0x78` (and so `modelHeight`
  below) are those of the last part loaded: every part writes the same field.
- *Vertex layout* of the LOD and frame meshes (S 007fa138, entries {type, usage, index}) [known, bytes]:
  POSITION float3, NORMAL float3, BLENDINDICES D3DCOLOR, TEXCOORD0, TEXCOORD1, TEXCOORD2 float2, i.e. the KEX
  streams 0, 1, 13, 4, 5, 6 (`asset-formats.md` §2); the bone weights (12) and the vertex colour (3) are dropped,
  absent streams stay zero [inferred: the vertex buffer is cleared before the fill, S 0076d3d0]. In all 443,169
  house vertices the first bone index has the largest weight, and only 12 are not bound to one bone alone
  [known, data].
- *Materials* (`BuildingMaterial::Create` S 006d50e0), one per subset of a LOD mesh: texture usage
  `DiffuseColor` → stage 0, `Self-Illumination` → stage 1 (the light map, the `*_L.dds` files); any other usage
  (`Opacity`, in 45 of the 111 house materials) is logged and ignored. Path = the directory of `mesh` + the file
  name after the last `\`. Materials with the same two paths are shared by all types. Data: 101 houses have one
  material, five Egyptian houses two (two diffuse textures, one light map); every house except the three ruins
  has a light map [known, data].
- *Frame* (`frame`, `+0x9c`): loaded with `mergeAllMeshes` (`CMesh::LoadMergedFromKFile` S 0076d3d0,
  `animation-models.md` §3.2): one subset per KEX mesh, in the order of the decimal mesh names `"0"`, `"1"`, ...
  The subset count is the type's `stageCount` (`+0xa4`); `+0xa8` holds the running sum of the subsets' triangle
  counts (`stageCount + 1` entries, entry 0 = 0). Texture (`+0xa0`) = the file of subset 0's first texture
  entry, in the directory of `mesh`. Data: the 100 `frame` attributes name 80 files; in every one the meshes are
  named `0 .. N-1` with one material each, N between 4 and 145, all with the texture
  `PB_R_ConstructionSite01.dds` [known, data].
- *Ground decal*: the mesh `GROUND` of the `mesh` file (103 of the 106 files; its material always names
  `house_decal.dds`) [known, data]; drawing below.
- *Defaults* (`BuildingDesc::ctor` S 006a0990): `enterDistance` 0.3, `leaveDistance` 0, `heading` -30, `lodBias`
  and `lodScale` from the root. In the install only `Bavarian_Castle` sets `enterDistance` (0.2) and only
  `Bavarian_Bakery` sets `lodBias` / `lodScale` (to the root values) [known, data].

**Placement** S 006ac810, S 006aaab0 [known]: world matrix = rotation about Y by `heading` (`BuildingDesc +0x98`,
integer degrees, passed by `AddBuilding` S 006a2bf0 to every building constructor; the constructor stores
`heading × π / 180` in radians at `Building +0x28`, float π S 007fccfc over double 180.0 S 007db6a0, and
`UpdateTransform` calls `SetRotationY` with it every frame) with translation `worldPos` = the centre vertex of the building's cell at its height
(`TerrainGrid::CellToWorldPos` S 00687790). No type sets `heading`, so every building is turned by -30°.

**Passes** `BuildingRenderer::Render` S 006a0ad0 [known for the order], all with `house_shader.fx` and the
technique chosen by shadow level and quality (§6.3): pass `RenderFrame` draws the construction frames
(S 006a0180), then the ruins (S 006a06d0); pass `RenderHouse` the buildings (S 006a0380); pass `RenderAddOns`
the skinned add-ons (`SkinnedMeshRenderer`; the `<Production>` animals, §"Farm props"); then the military flags
(`house_soldierflag.fx`). The shadow map pass `BuildingRenderer::RenderWithExternalEffect` S 006a0cc0 draws the
same frames, ruins, buildings (with the same clip planes), add-ons and flags with the caller's depth effect.

**Building shading** (`house_shader.fx`, pass `RenderHouse`: z test and write, no blending, alpha test `> 127`)
[known, file]:

```
// vertex; b = BLENDINDICES.x, the first bone of the vertex (rigid, no weights)
world = (position * INSTANCEMATRICES[b]) * WORLD                  // WORLD = identity in this pass
N     = normal * (float3x3)INSTANCEMATRICES[b]                    // not normalised
vcol  = saturate(dot(N, -L)) * lightColor
uv0   = texcoord0 + 0.5 * texel(0)
uv1   = texcoord1 + 0.5 * texel(1)
uv2   = texcoord2 + 0.5 * texel(2) + (colorMapOffset, 0)
// pixel
D     = ambient.rgb + vcol.rgb * shadow       // CalcLight; shadow 1 or shadowIntensity, 4-tap PCF (1 tap: Low*)
C     = tex0(uv0)                             // diffuse
Lm    = tex1(uv1)                             // light map
Cm    = tex2(uv2)                             // colour map
rgb   = D * C.rgb * Cm.rgb
rgb   = lerp(rgb, rgb * Lm.rgb, saturate(1.5 - D))       // per channel: the light map shows where D < 1.5
a     = C.a                                              // alpha test
CalcFOW(rgb)                                             // exploration, §3.7
```

`texel(n)` = `TEXTURE_ATTRIBUTES[n].zw` = `(1 / width, 1 / height)` of the texture on stage n
(`world-objects-rendering.md` §3.11); samplers 0..2 are linear and wrapped. Buildings have no player colour; the
file's `textureAtlasOffset` and `colorIndexScale` are used by no pass [known, file].

Inputs per draw `BuildingRenderer::DrawInstance` S 0069fb10, S 006a0380 [known]: `WORLD` = identity; without a
skeleton binding one instance matrix = the building's world matrix (`SetInstanceMatrices(world, 1)` S 004e8b30),
with one the bone matrices of the type's animated model in the order of the LOD mesh's bone names
(`MeshBoneBinding`, `Building +0x3c`, S 004e8ba0), which then carry the placement as well [inferred: `WORLD` is
the identity]. On shader level 0 the vertices are skinned on the CPU instead (`CpuSkinVertices` S 0069f860,
S 0088d999 = shader level != 0). Per subset: stage 0 = the material's diffuse texture, stage 1 = its light map
(a material without one leaves the texture of the previous draw on stage 1; only the ruins lack one, and they
are drawn in the frame pass); stage 2 = the colour map, bound once for the pass.

**Colour variation** [known] S 0069fb10 (disassembly), S 006a0e60, S 006821b0:

```
colorMapOffset = (instanceId mod numVariations) * (1 / numVariations)      // unsigned modulo
```

`numVariations` = the root attribute (8; 1 without it, S 008819d0); the colour map = the root `colorMap`, default
`[data]\buildings\colors.tga`. `instanceId` = the building's 1-based slot in the renderer's instance pool
(`Building +0x10`): a removed building's slot goes to a free list, and a new building takes the slot freed last,
else a new slot at the end (S 006a2bf0, S 006a17a0). The index thus follows the creation order of the session
and is no logic value. An upgrade's completion removes and re-adds the building (§3.2) and so keeps the slot and
the variation [known: `HandlePool_Free` S 0076b180 pushes the freed slot on top of the free stack, and
`AddBuilding` S 006a2bf0 pops the top, else appends `count + 1`]. (The object created in S 006ac810 and
named "variant" is the LOD mesh's bone binding, rebuilt by S 006aa9d0 when the LOD changes; the LOD index at
`Building +0x38`.)

`colors.tga` is 64 x 256 RGB, 8 column blocks of 8 texels (the variations) by 32 row bands of 8 texels
[known, file]. The third texture coordinate set of a house (KEX stream 6, `TEXCOORD2`) picks a texel in block 0;
it is constant over most meshes and mostly points at white rows (rows 0, 32..47 and 240..255 are white, rows
88..239 black and unused). Sampled as the shader samples (bilinear, wrapped, half-texel offset), 102 of the 106
house meshes get pure white in all 8 variations (among them the 11 meshes without that set, which sample (0, 0));
only `PB_B_Spytower01` (greys 224..254),
`PB_E_WoodcutterHut01` (slight warm tints), `PB_S_Smelter01` and `PB_S_Goldmine01` (one step per channel) vary
[known, data, computed]. The shipped colour variation is therefore nearly invisible. The file is stored
bottom-up and read with its origin flag honoured, as the D3DX loader does [inferred].

**Frame and ruin shading** (pass `RenderFrame`: z test and write, no blending, no alpha test) [known, file]:
`world = position * WORLD` (the building's world matrix, set per site),
`rgb = (ambient + saturate(dot(N, -L)) * lightColor * shadow) * tex0(uv0).rgb`, `a = tex0.a` (no effect), then
`CalcFOW`. No light map and no colour map. A ruin is drawn with LOD part 0 of its descriptor (`AddRuin` sets the
LOD index 0 for every part count, disassembly S 006a1d21..S 006a1d4a), and its material's diffuse texture S 006a06d0 [known].

**Construction and upgrade display.** Inputs are the two floats `remainingA` (+0x70) and `remainingB` (+0x74) of
the logic `NVillage::Construction` (1.0 at the start, 0 when done; `docs/sim/village-buildings.md`), taken from
the building's construction, or from its upgrade record while upgrading.

- *Stage index* `Building::GetConstructionStageIndex` S 006aa1b0 [known, disassembly]:

  ```
  built = 1 - remainingB                                  if the byte S 0088d998 is non-zero
        = ((1 - remainingA) + (1 - remainingB)) * 0.5     otherwise
  stage = min(stageCount, toInt(0.5 + (stageCount + 1) * built))        // toInt truncates
  stage = 0 while demolishing (demolishProgress >= 0) or when neither constructing nor upgrading
  ```

  `stageCount` = `BuildingDesc +0xa4` of the building's type, or of the upgrade target's type while upgrading
  [known] S 006aa1b0. S 0088d998 = `D3DCAPS9.MaxUserClipPlanes >= 2` (`CGraphicDevice +0x18`, written by
  `DetermineDeviceCaps` S 004d3df0; the byte is refreshed every frame in S 0069ff70) [known]. Shader model 2
  hardware offers 6 user clip planes, so on any device a remake targets the first form holds: the frame follows
  the frame phase alone. The second form belongs to the fallback without clip planes, in which the rising
  building (next items) is never drawn and the frame grows over both phases [inferred].
- *Frame stages* `BuildingRenderer::RenderConstructionSites` S 006a0180 [known, disassembly]: every building of
  the construction list (constructing or upgrading and not demolishing, rebuilt each frame in S 0069ff70) that is
  not hidden and passes the frustum test gets one draw of the frame of its type, or of the upgrade target's type
  while upgrading: one indexed triangle list from the frame's first index with
  `primitiveCount = BuildingDesc +0xa8[stage]`, i.e. the subsets (KEX meshes) `"0" .. "stage - 1"` together;
  stage 0 draws nothing. World matrix = the building's; texture = the frame texture on stage 0.
- *Rising building* `BuildingRenderer::RenderInstances` S 006a0380, `Building::GetConstructionClipPlane`
  S 006aabe0 [known, disassembly]: in pass `RenderHouse` a building under construction is drawn only when
  S 0088d998 is set and `Building_HasClipProgress` S 006aae30 holds (`constrProgress > 0` or
  `upgradeProgress > 0`). Such a draw, and both draws of an upgrade in its main phase, get a user clip plane and
  the cull mode `D3DCULL_NONE`, so the open cut shows the inner faces; the other draws get the cull mode the pass
  hands in.

  ```
  p      = prev + (cur - prev) * (1 - (tNext - now) * rate)       // tNext >= 0; else p = cur. Not clamped.
  planeY = worldPos.y + (modelHeight - 0.1) * p / 0.9            // 0.1 and 0.9 are float constants
  construction:    normal (0, -1, 0) through (worldPos.x, planeY, worldPos.z)      keeps y <= planeY
  upgrade, draw 1: the old type, normal (0, 1, 0)                                  keeps y >= planeY
  upgrade, draw 2: the target type (BuildingDesc +0xb0 of the old type), mirrored plane, keeps y <= planeY,
                   bone binding Building +0xf4 of the target's animated model
  ```

  `modelHeight = maxY - minY` of the type's bounds (of the target type while upgrading); `now = timeInfo[1]`;
  the up vector is the constant S 00882864 = (0, 1, 0) [known, bytes]; Direct3D keeps the points with
  `dot(plane, p) >= 0`. Since `minY` is close to 0 (-0.23 .. 0 in the files measured) the cut reaches the roof
  at about `p = 0.9` [inferred, data].
- *The progress values* `Building::Update` S 006abcf0 (per logic tick: vftable slot +0x2c, §4.2),
  `Building::ctor` S 006ac810 [known]:

  | Field | Value |
  |---|---|
  | `constrProgress` +0xcc | `1 - construction.remainingA`, the main phase (the `cost` list); written every tick while the building is under construction; 1.0 for a building created finished |
  | `constrProgressPrev` +0xc8 | `constrProgress` before that tick's write |
  | `constrProgressTime` +0xd0 | `timeInfo[0]`, the time of the next tick, at that write; -1 until the first write |
  | `constrProgressRate` +0xd4 | `1 / GameConfig.gameSpeed` = 1 / 0.1 s (`properties-data.md`) |
  | `upgradeProgress` +0xe0, `Prev` +0xdc, `Time` +0xe4, `Rate` +0xe8 | the same from `1 - upgrade.construction.remainingA`, written every tick in which the building is not under construction and upgrading |

  `p` therefore runs linearly from the previous tick's value to the new one within one tick and arrives when the
  next tick is due; the plane stands still between the builder's strokes.
- *What the player sees* [inferred from the rules above; clip planes present]:
  1. Placed (`remainingA = remainingB = 1`): stage 0, `constrProgress = 0`: no frame and no building; only the
     ground decal (created with the instance) and, once goods arrive, the material pile.
  2. Frame phase (`remainingB` falls): the frame meshes appear one by one in name order,
     `stage = min(N, toInt(0.5 + (N + 1) * (1 - remainingB)))`; the whole frame stands from
     `1 - remainingB >= (N - 0.5) / (N + 1)` on.
  3. Main phase (`remainingA` falls): the whole frame, and inside it the building rising from the ground, cut at
     `planeY`.
  4. Done (both 0): the building leaves the construction list, so the frame vanishes and the building is drawn
     whole without a plane; the material pile is removed on the next tick (S 006abcf0).

  Upgrade: `BeginUpgrade` S 006ab5b0 (on "upgrade started", §3.2) replaces the ground decal by the target type's,
  creates the target's animated model and bone binding and sets `upgrading`. The old building stays whole while
  the target's frame grows (stages from the upgrade construction's `remainingB` and the target's
  `stageCount`); in the main phase the old building is cut away from below while the target rises in its place,
  both at the same `planeY`. On completion `Building::SetType` raises "building removed" with the building
  flagged destroyed, so `LeavesRemains` is false and the instance is deleted without demolition, then "building
  added" creates a finished instance of the new type [known] S 0055c110, S 006aa2b0, S 00681560. A cancel calls
  `EndUpgrade` S 006ab710 (old decal back, target model dropped).
- *Material pile* `BuildingScaffold` [inferred] S 006d82f0: item stacks for the goods in the construction stock,
  rebuilt when the stock's revision changes, laid out with the item stack layouts (§6.5).

**Ground decal** `HouseDecalRenderer::AddDecal` S 006b4400, `GroundDecalMesh::Build` S 006da2a0 [known]: made
with the instance (so also under construction; replaced on upgrade start and end) from the `GROUND` mesh of the
type's `mesh` file. Callers of `AddDecal`: buildings, ruins (`Ruin::ctor` S 006d4e00, the dead building's
`GROUND`, §"Demolition") and harbour places (`Harborplace::ctor` S 006db7a0, `Harbour_decal.KEX`, §3.11). Meshes
are loaded once per file (`GetOrLoadMesh` S 006b4240) and removed with `RemoveDecal` S 006b3e00. The build
(`HouseDecal::ctor` S 006da650 → `Build` with step 1) [known, decompile and disassembly]:

1. *Triangles, once.* The model's box (`ComputeAABB` S 0076b6f0) has its 8 corners transformed by the world matrix
   (`TransformInPlace` S 006ea510); the terrain triangles under that one world box are collected
   (`CollectTrianglesInBounds` S 0068a760 → `CollectTrianglesInAabb` S 006c08a0 → `AppendTriangleIfOverlapsXZ`
   S 006c0600, an inclusive overlap test in x and z). On the grid's last row the collection reads past the vertex
   array. `AddTriangle` S 006ecd90 inserts at the head of its list, so both lists are walked last-first; it writes
   through a null pointer when its 512-triangle pool is full.
2. *Clip.* Each terrain triangle clips the **whole** transformed mesh (`TriangleList::ClipByPlanes` S 006ed6e0,
   `projectCulled` 0). Its three edge planes (`TriangleListNode::BuildEdgePlanes` S 006ed590,
   `Plane::FromPoints` S 006eb9c0, `DotCoord` S 006eb4d0, `Math_Vec3_Normalize` S 004d8bb0, which multiplies by
   `1 / length`) each pass through the edge's two vertices and the point `(((nA + vA) + vB) + nB) · 0.5`, with
   `nA`, `nB` the packed normals of the two edge vertices (§2.1), unpacked and not renormalised. Neither face normals nor
   vertical planes are used, so the planes lean with the averaged normals, and around a terrain vertex the planes
   of neighbouring triangles do not meet in one line.
3. *Height.* The mesh is clipped at the height it was authored at; afterwards each vertex goes through
   `TerrainGrid::SampleHeightAndNormal` S 00687e60 at its clipped 3D position and gets `+0.01` (the double
   S 007d4a70, equal to the float 0.01). `FindNearestVertex` S 00687570 searches in 3D, so the vertex's own height
   takes part, and `FindTriangleAt` S 00687a70 tests only the wedge of the vertex's fan (tables S 00881478,
   S 008814b0), not the far edge; `VertexToWorldPos` S 00687500.
4. All of it runs at the x87's 24-bit precision (S 0057b9b0).
5. *Normals.* The decal vertices carry the `GROUND` mesh's own normals (`g_DefaultMeshNormal` S 00882864 when it has
   none), turned by the upper 3 × 3 of the world matrix without renormalising (`TriangleList::AddMeshTransformed`
   S 0076e530) and interpolated by the clip like the positions; the terrain normal is never fetched
   (`SampleHeightAndNormal` is called with a null normal at 006da414). In `ClipByPlanes` the first interpolation
   factor is clamped to 0..1, while the second is set to 0 below 0 and also to 0, not 1, when it is > 1 (exactly 1
   is kept; disassembly at 006ed882 and 006eddbf), and a vertex counts as behind a plane when its distance is
   < −0.0001 (the float at S 007fcd00, negated; `FCOMPP` / `TEST AH,0x41` / `JP` at 006ed771), so a distance of
   exactly −0.0001 is in front [known] S 006ed6e0.

Consequence [known: the algorithm; measured on a port of it]: a decal on a slope, and any decal mesh above or below
the local ground, does not tile: pieces spanning a crease dip below the terrain and pieces overlap, so the original
shows notches, small holes and thin cracks in building and harbour plots on sloped ground. On the harbour plot of
`MP_6P_ship_ahoi` the port hides 6.8 % of the plot under the terrain; with vertical edge planes nothing is hidden.

After a height change `Building::RefreshGroundPlacement` S 006ab420 lays the decal again with the matrix of the
last frame: `UpdateTransform` S 006aaab0 rebuilds the matrix only on the next frame. Ruins (`RefreshGroundPlacement`
S 006d4f90, slot 5 as well) set the new matrix first [known].

Shader `house_decal.fx` [known, file]: positions already in world space,
`rgb = (ambient + saturate(dot(N, -L)) * lightColor * shadow) * tex.rgb`, `a = tex.a`, z test without z write,
blending `srcAlpha, 1 - srcAlpha`, then `CalcFOW`. Texture `[data]\buildings\house_decal.dds` (string S 007fac60
in the decal renderer's constructor) [inferred].

**Door and work animations** S 006aa640, S 006aa3b0, S 006aa6f0, S 006abcf0 [known]: two playback slots on the
building's instance of the type's animated model (created from `BuildingDesc +0x5c` in S 006ac810): slot 0 for
the door clips, slot 1 for `Working`; neither clip starts while the building is under construction.

**Building vftables** [known: RTTI type descriptors behind each vftable's complete-object locator, slots read
from memory]. `S2CG::Building` S 007fa79c (offset 0; a second vftable S 007fa78c at `+0xc`, two empty slots
S 00472360): 0 `SetHidden` S 006aa320, 1 `IsHidden` S 006ab260 (`+0xc0`), 2 `GetWorldBounds` S 006ab270, 3 `GetCell`
S 006ab2b0, 4 `GetFineCellPosition` S 006ab310, 5 `RefreshGroundPlacement` S 006ab420, 6 S 006aa180, 7
`SetTransform` S 006ab2d0, 8 S 0046b610 (returns `this + 0x54`), 9 `Render` S 006aae60, 10 the deleting destructor
S 006ab360, 11 `Update` S 006abcf0, 12 `UpdateTransform` S 006aaab0, 13 `DebugDraw` S 006aa4a0, 14
`PlayOneShotAnimation` S 006aa6f0, 15 returns false S 0041ecc0, 16 returns 0 S 0072db80, 17 an empty stub
S 005657b0 that `UpdateTransform` calls every frame (`vftable + 0x44`); 18 slots (the string "GROUND" follows). The
subclasses keep slots 1–4 and 6–9 and override: `SacrificeBuilding` S 007fa85c slots 0 (S 006accd0), 10, 11
(S 006acd90), 12 (S 006acc80) and 15 (returns true, S 005e4e90); `FarmBuilding` S 007fc06c slots 0 (S 006d55b0), 5
(S 006d59c0), 10, 11 (S 006d5760), 12 (S 006d5530) and 13; `CatapultBuilding` S 007fc0d4 slots 10, 11 (S 006d6000),
12 (S 006d61a0), 13, 14 (S 006d6510), 16 (S 006d5db0, returns its sub-object at `+0x21c`) and 17
(`ApplyBoneRotations` S 006d5e50, [animation-models.md](animation-models.md) "catapult").
`Building::ctor` S 006ac810 writes the kind 6 at `+4` that the cursor pick tests ([ingame-ui.md](ingame-ui.md)).

**When a building updates** [known]. Primary vftable S 007fa79c: slot 11 `Building::Update` S 006abcf0 runs
**per logic tick** (`Scene::SyncLogicTick` S 00680550 → `CMapRenderer::SyncLogicTick` S 006882c0), slot 12
`UpdateTransform` S 006aaab0 per frame, slot 14 `PlayOneShotAnimation`. `BuildingRenderer::Update` S 0069ff70 calls
`UpdateTransform` for every active building every frame, in view or not, so its model and clip events advance
whether drawn or not. The events' enabled flag is the model's `+0x50`, written by `SetHidden` S 006aa320: set while
the building is not hidden and fog-visible (+0xc4) (§3.7). Building attachments (the sacrifice movies) advance in
`EffectList::Update` inside `Building::Update`, so per logic tick as well.

- *Door*: `Building::TriggerWorkCycle` S 006aa640 (despite the name, the door trigger) sets
  `doorCloseTime = now + 0.6` and marks the cycle pending, even under construction; only the `DoorOpen` clip on
  slot 0 and the 3D sound 0xE29EF893 wait for a finished building, and the sound plays only when the building is
  not hidden. The per-tick update plays `DoorClose` on slot 0 (sound 0x9C700243, same gate) once
  `timeInfo[0] >= doorCloseTime`; every new trigger pushes that time back.
- *Who opens it* (`CharacterSettler::Update` S 006c7640, [animation-models.md](animation-models.md) §3.10): each
  settler's render logic keeps a target building, refreshed when its refresh flag (`CharacterSettler +0x18`, set by
  `CCharacter::SetPath` S 006905e0) is set and the figure walks no street spline (`CharacterMovement +0`, set by
  `SetPath` S 006c5160 for street paths). The target is chosen per class: worker S 006c8c10, soldier S 006c7a80,
  carrier S 006c8df0, specialist S 006c8300 (shared with the constructor and the NPC; classes from
  `CCharacter::Init` S 00690760), each looked up in the building grid, which is keyed by **entrance cell**
  (`AddBuilding` S 006a2bf0 → `GetInstanceIdAtTile` S 0069f790). `UpdateBuildingEntrancePass` S 006c7510 triggers
  the door when the figure's path progress passes the target's `enterDistance` or `leaveDistance`, chosen by the
  pass direction (`GetDoorPassDirection` S 006c73a0, which compares the step's target cell, movement +0x28, and the
  last cell reached, +0x30, or the fine position fields +0xe0 / +0xe8 on fine walks; positive → `enterDistance`,
  read as going in [inferred]). A worker at its workplace also triggers it while its current clip still has time
  left and has a slot override (`CharacterWorker::UpdateWorkplaceWork` S 006c88c0, call at S 006c89d4).
- *The door rule* [known, x87 disassembly of S 006c70c0, S 006c73a0, S 006c7510, S 006c7640]: `FindTargetBuilding`,
  `GetDoorPassDirection` and `UpdateBuildingEntrancePass` treat the figure as moving when the logic interpolator's
  progress (movement +4) is `>= 0` (`FLDZ; FCOMP [p+4]; FNSTSW; TEST AH,0x41; JP/JNP` at S 006c70d0..006c70dc,
  S 006c73d0..006c73e1, S 006c7526..006c752e; the decompiler's `!NAN(f) && 0.0 < f != (f == 0.0)` hides this). Not moving
  is -1.0. A walk that has just started has progress exactly 0.0 and counts as moving. Only the final threshold test is
  strict: `TriggerWorkCycle` is called when `enterDistance` (+0x90) or `leaveDistance` (+0x94) `< progress` (FCOMPP /
  TEST AH,5, S 006c756c..006c7573); with `leaveDistance` 0 a leaving settler opens the door from its second sample on.
- *Target refresh* [known]: the refresh in `CharacterSettler::Update` S 006c7640 runs in the tick in which `SetPath` set
  the flag (+0x18): the callback fires inside `StartRoughMove` S 00657480 (also `MoveToFinePos` S 006574d0, a completed
  step in `SettlerMovement::Update` S 00658140), and the render hook (`SyncLogicTick` step 22 -> `UpdateLogicAll`
  S 006929e0 -> `CCharacter::UpdateLogic` S 006909f0 -> `CharacterSettler::Update`) is the last step of the tick, so the
  first refresh sees the step's progress as the logic left it (0.0 right after a start). The flag is cleared
  unconditionally right after the `UpdateTargetBuilding` call (S 006c768d; the else branch at S 006c766d is dead code),
  only while no route spline is active (`CharacterMovement +0 == 0`); on a spline it stays set and the lookup is retried
  every tick. The target is not recomputed per tick: a target survives a state change that starts no new walk (a
  carrier's 0x13 -> 0x14 keeps the building until the next `SetPath`). `CharacterSettler::Update` runs once per logic
  tick; the progress is the logic interpolator's, not a frame-interpolated one.
- *Worked example, the carrier's delivery* [known]: 0x12 street walk -> 0x13 `EnterBuilding` (target by the step's
  destination cell, `FindTargetBuilding(false)`; the door opens past `enterDistance`) -> 0x14 inside (`DeliverPackage`,
  no door call, target kept) -> 0x15 leave (target by own cell, `FindTargetBuilding(true)`; the door is held open from
  `leaveDistance`). The carrier never calls a door function itself; the door and the building's Working clip use separate
  animation slots (0 and 1) and neither reads the other's latch.
- *Work*: `Building::PlayOneShotAnimation` S 006aa6f0 (vftable +0x38), called by `UpdateWorkplaceWork` while the
  worker is at its workplace and no one-shot runs (a building whose property byte +0xb0 is set, the catapult,
  restarts it at each new work start): `Working` on slot 1, started `workElapsed` into the clip [inferred: the
  offset argument of the play call], at the worker's
  speed factor (`Worker::GetWorkAnimSpeedFactor` when `ShouldSpeedUpWorkAnim`, else 1), stopped after the work
  duration, which the per-tick update counts down by the tick length (`timeInfo[2]`, Scene +0x50, subtracted in
  float). The one-shot's running flag and times are set even when there is no clip or the building is under
  construction, so a new start waits for the countdown in either case [known] S 006aa6f0.
- The `<Sound>` and `<Particle>` events of the clips fire as the clips play.

**Level of detail** `BuildingRenderer::Update` S 0069ff70 (disassembly), S 0069fb10, S 006aa9d0 [known]:

```
d   = dot(nearPlane, centre of the building's world AABB)        // normalised plane: world units
lod = toInt(0.05 * (1 - objectDetails) * (lodBias + lodScale * d) + 0.5)        // toInt truncates
lod = clamp(lod, 0, lodPartCount - 1)
```

`nearPlane` = plane 4 of the scene frustum (`Frustum::ExtractFromViewProj` S 004d6de0, normalised by
S 004d9ce0). `objectDetails` = the scene setting read through S 00695ee0: 0, 0.25, 0.5, 0.75, 1.0 for the
quality presets 0..4 (S 00695860), 1.0 in the constructor. At the top preset the factor is 0 and every building
uses part 0; otherwise part 1 (the `LOD0` file) starts at `d >= (10 / (1 - objectDetails) + 70) / 1.2` with the
root values (66.7 world units at preset 0). A LOD change also rebuilds the bone binding. Frames and ruins have
no distance LOD.

**Demolition** [known] S 006ab840, S 006aaab0, S 006a1f20: started on removal when `LeavesRemains` holds (§3.2).
Start: one-shot particle effect `DemolitionDust`, or `SmallDemolitionDust` when bit 0x4 of the building property's
`size` mask (+0x3c, `bp_setSize`) is clear: small (7), medium (6) and large (4) types have the bit, so only mines
(8) and ship sites (16) get the small dust; a 3D sound; the ground decal and the material pile are removed;
`demolishProgress = 0`. Per frame: `demolishProgress = min(1, demolishProgress + dt * 0.35)` and
`worldPos.y = terrainHeight(cell) - modelHeight * progress^2`; the fire points follow. On the logic tick after the
progress reached 1.0 the instance is deleted. The remains are a `S2CG::Ruin` (vftable S 007fbfa4; scene slot +0x70
`Scene::OnRemainsAdded` S 0067f210, raised by `CreateRemains` S 005598a0 → `BuildingRenderer::AddRuin` S 006a19b0 →
`Ruin::ctor` S 006d4e00) [known]. `AddRuin` reads the remains object's remains type (+4), building type (+8), tribe
(+0x40) and cell (+0x20/+0x24); the ruin is the descriptor `"<tribe>_<remains gfx name>"`, turned by that
descriptor's `heading`, and its ground decal is the `GROUND` mesh of the dead building's descriptor
`"<tribe>_<building gfx name>"` (its mesh path, desc +0x1c), laid with the ruin's matrix. When that second lookup
fails, index −1 reads the memory before the type table. A ruin's bounds are the decal's when it has one
(S 006d4c70). It lasts as long as its logic remains [inferred]; the shipped `remains.lua` sets a burning time of
50 ticks (`rm_setBurningTime 50`, 600 commented out) [known, data], so a ruin shows for about 5 s, mostly under the
demolition dust.

**Fire** `Building::UpdateFireEffects` S 006abbb0 [known, disassembly]: the first `burning` fire points run the
effect `BuildingFire`, the others are stopped, with

```
burning = toInt((1 - Hitpoints::GetRatio()) * firePointCount + 0.5)        // toInt truncates
```

**Fire points** (`Building::InitFirePoints` S 006ac510) [known, disassembly]: the nodes `FIRE_03`, `FIRE_06`,
`FIRE_09`, ... of the animated model, the number stepping by 3 from 3 (`XOR EDI,EDI` at S 006ac54f, `ADD EDI,3`
at S 006ac551, the loop back from S 006ac6c1), up to the first name the model lacks; each node's matrix times the
building's world matrix gives the point. `FIRE_00` is never a fire point. The shipped files number their nodes
`FIRE_00` upward without gaps, and only the military models (guard house, watchtower, fortress or stronghold,
castle of each tribe, with their `LOD0` files) have any [known, files], so every other building takes the
fallback: 5 points, two draws each from a process-wide generator with the static seed 0x5432ace0 (S 0088da38,
built on first use): `x = cx + (2r − 1) · 0.4 · sx`, `z = cz + (2r − 1) · 0.4 · sz` with centre `c` and size `s`
of the world bounds, `y` = the centre's height. `InitFirePoints` is called only from the building constructor
(S 006acc23), so the generator advances in building creation order across the whole process.

**Effects in `Building::Update`** (S 006abcf0) [known]: nothing runs while `demolishProgress > 0`, so the
fires keep burning unchanged while the building sinks. The buffs run only when the building has no scaffold and
`showEffects` is set; each starts its effect at the building's position with identity rotation (the identity
quaternion S 008828d4, so buffs, fires and dust stand upright in world space and do not turn with the building's
heading) (`StartByName(name, active 1, emitting 1, time, position, identity)`) while its condition holds and stops it
(`Stop(true)`) otherwise:

| Slot | Effect | Condition |
|---|---|---|
| `fxShipSpeedUpA` | `ShipSpeedUp` | size 8 (mine) and working mode (`+0x80`) 6, and the miners do not need food (`SacrificeModifierQuery::MinersNeedFood` false) |
| `fxBuildingArmor` | `BuildingArmor` | an active military building (`IsActiveMilitaryBuilding`) and `ScaleCatapultDamage(100) < 100`; for other buildings the slot is left as it is |
| `fxShipSpeedUpB` | `ShipSpeedUp` | a territory building whose sacrifice-modified territory range differs from `bp_setTerritoryRange` |
| `fxSacrificeBuff` | `ShipSpeedUp` | working mode 2 and the sacrifice-modified goods differ from the type's goods |
| `fxScaleBuff` | `ShipSpeedUp` | a type with goods whose sacrifice-modified production time differs from `bp_setProductionTime` |
| `fxWorkerPause` | `WorkerPause` | a type with goods whose `restTime` is below the sacrifice-scaled time |

Then the work-cycle and one-shot clips, and `UpdateFireEffects` (above).

**Military flags** `CMilitaryFlagRenderer::DrawFlags` S 006d2820 (disassembly), S 006d2d80, S 006d2ec0 [known]:
every building is registered on creation (S 006a2bf0); a flag is drawn for one whose renderer building is not
hidden (its vtable +4 test), whose own
construction remainders are both <= 0 and for which `Military::HasMilitaryFlag` S 0055fd00 holds (property
+0x94 > 0 and +0x98 != 0, or the three headquarters flags +0x54, +0xf1, +0xf5). World matrix = the node matrix
of the bone `MILFLAG` (`BuildingDesc +0xbc`) of the building's animated model, or without that bone a rotation
about Y by 90° with the translation `(centre.x + 0.33 * size.x, 0, centre.z - 0.55 * size.z)` of the type's
bounds; then times the building's world matrix. 23 meshes in `[data]\buildings\`: 0 `MilitaryFlagInactive.KEX`,
1..11 `MilitaryFlagSword00..10.KEX`, 12..22 `MilitaryFlagBow00..10.KEX`, packed into one vertex and index buffer
(each draw starts after the summed counts of the meshes before it).

- Mesh, chosen anew every frame (there is no raise animation): 0, the bare pole, unless
  `Building::IsOccupied` S 0055c400 holds and the building's `TerritoryUpdater` (+0xc4) has its byte +8
  (`bActive`) set; else
  `1 + n + (soldierKind != 0 ? 11 : 0)` with `soldierKind` = `Military +0x68` (0 sword, 1 bow; `military.md`
  §2.4) [known, disassembly S 006d2a13..S 006d2a2b] and `n` = `NVillage::Military::GetFlagSoldierCount`
  S 0055fd40: the number of soldiers present in the building, or for a building whose property has the three
  flags at +0x54, +0xf1 and +0xf5 set (the headquarters-type depot [inferred]) the number of soldiers in its
  depot stock, capped at 10.
- Texture: `[data]\buildings\MilitaryFlag<i>.dds`, i = 1..3 (built as text in S 006d2ec0); index 0 unless the
  building is a military building (`Military::IsMilitaryBuilding` S 0055fb80), else the zone when it is > 0 and 0
  otherwise, through `S2CG::Building::GetMilitaryProximityZone` S 006aa2f0, with `zone` =
  `NVillage::Military::GetProximityZoneA` S 0055fbb0 (a 0 / 1 / 2 class of the value at `Military +0x5c`, -1 while the territory component is inactive;
  `docs/sim/military.md`). The meshes' own material name (`MilitaryFlag1.dds`) is not used.
- Colour: `FLAG_COLOR` = the owner's player colour entry (`Player::GetColorEntry`).
- Shader `house_soldierflag.fx` (z test and write, no blending, no alpha test) [known, file]:

  ```
  // vertex, model space (CalcBigFlagVertexPos)
  s  = 0.14 * saturate(x*x + z*z - 0.02)
  w  = WORLD._41 + WORLD._43 + 0.5*x + 0.5*y + TIMER.y
  c  = 0.5 + 0.5 * cos(4 * w)
  z -= s * c;   y += s * (1 - c);   then * WORLD
  // pixel
  base     = tex(uv0);  base.rgb = lerp(flagColor * 1.8, base.rgb, base.a)      // alpha 0 = owner colour
  over     = tex(uv1);  rgb = lerp(base.rgb, over.rgb, over.a) * D;  a = 1;  CalcFOW
  ```

  `D` = `ambient + saturate(dot(N, -L)) * lightColor * shadow` as in the building shader. Both coordinate sets
  read the same texture; the 22 soldier meshes share their first set and differ in the second (the emblem and
  the count) and slightly in their positions [known, data].
- The shadow map pass draws the flags with the pass `ShadowPassBigFlag` (S 006d2b60). The renderer also loads
  `house_flag.fx` with `FLAG_COLOR` and `FLAG_TEXTURE_OFFSET`; none of its three draw functions (S 006d2ab0,
  S 006d2b60, S 006d2820) uses that effect.

**Farm props** S 006d5660: the first `visible` props of the `<Production>` child are shown, recomputed when
the productivity changes; productivity = `Statistics::GetProductivity` of the building, 0 unless production is
enabled and the building is occupied [known]; `visible = toInt(productivity * numModels + 0.5)` [inferred: the
x87 part is not in the decompile, the formula is the one of the mapped comment]. Props sit at `location<i>`
offsets or `boneLink<i>` bones [inferred]. They are skinned meshes of the `SkinnedMeshRenderer` that the farm
instance receives (S 006a2bf0), drawn in pass `RenderAddOns` [inferred]: `house_shader.fx` `SkinShader`, four
weighted bones (two in the `Low*` techniques), `rgb = D * tex0.rgb`, `a = tex0.a`, no alpha test, `CalcFOW`
[known, file]; texture `<Production texture>`, mesh and skeleton at `<Production scale>` (S 006d4060).

**Catapult** [inferred] S 006d6000..S 006d65c0: bones `ROTATE`, `ARM_ROTATE` and `BULLET_POS` [known, strings
in S 006d65c0]; yaw interpolated toward the logic direction, arm angular speed 3.0.

### 3.10 Settlers: models, colours, movement, animation

**Model definition** (`settler_config.xml`) [known, file]: `<Character name mesh mesh1 mesh2 mesh3 color slotMap>`
= LOD meshes 0..3 (the shipped entries read here carry `mesh`, `mesh1`, `mesh2`), the index texture and the
colour slot map; one shared skeleton model (`<Models><Model>`).
Lookup key `"<tribe resource name><sep><character name>"` (`CCharacterMgr::FindCharacterDefIndex` S 00692c60, −1
when no definition has the name); `CreateCharacter` S 00695490 turns −1 into definition 0 [known]. Definition 0 is
`Bavarian_Carrier` (the first `<Character>` of `settler_config.xml`), so a Scots or Egyptian NPC profession, whose
definitions exist only as `Bavarian_Garibald` and `Bavarian_TreeMerchant`, draws as a Bavarian carrier [known: data].

**LOD** [inferred] S 00690460: squared camera distance against three ranges; `<Characters lod0Range="30.0"
lod1Range="40.0" lod2Range="60.0">` in `settler_config.xml` [known, file]. Global scale `scale="1.2"`.

**Colour** (`skin_color_mesh.fx`) [known, file]: the mesh texture is an index map, not a colour map:

```
idx   = indexMap(uv)                      // point filtered
D     = saturate(dot(N, -L)) * lightColor.a * shadow + ambient.a          // scalar light
tap.x = saturate(idx.g * D) * colorIndexScale.x + atlasOffset.x           // luminance x light -> ramp column
tap.y = idx.r * colorIndexScale.y + atlasOffset.y                         // red -> ramp row (material slot)
color = palette(tap + halfTexel)                                          // bilinear
rgb   = lerp(playerColor * idx.g * D * 2, color.rgb, idx.a)               // alpha 0 = player-coloured cloth
rgb   = saturate(rgb + pow(saturate(dot(normalize(2*D*N + L), V)), 16) * idx.b)   // blue = specular mask
```

The palette is a 1024 x 1024 atlas built at run time; each character owns a 16 x 16 block (column = shade, row =
slot) and `COLOR_INDEX_SCALE = (15 / 1024, 256 / 1024)` [known] S 006910e0, so a red byte k selects row k. The
index maps store the 1-based `Material index` of `color_slots.xml` in R, and `Texture_DecrementIndexChannel`
S 00692170 subtracts 1 at load [known]. Every settler gets a random palette (the only caller of S 00695490 passes
none) [known]: one Park-Miller draw per slot from a static generator seeded `0x5432ace0`, the ramp copied
reversed into its row. Construction, atlas and the full pixel formula: [`animation-models.md`](animation-models.md)
§3.15.

**Movement between ticks** [inferred] S 006c57b0.., [known] S 006805e0 for the factor: on each logic tick the
movement component stores a previous and a target position (tile to tile, or a sample of the street's route
spline at the settler's path progress); per frame

```
f   = 1 - (nextTickTime - now) * (1 / tickLength)           // 0 at the tick, 1 at the next
pos = lerp(prev, target, f)
```

then the height is snapped to the terrain, a sideways offset (street avoidance of oncoming settlers,
`evadeRadiusScale`, `evadeStart`) is applied and decayed, and the yaw turns toward its target by at most
0.43982297 rad per logic tick, interpolated over the tick [known] S 006c4f40, S 006c48c0. A walk on a street
follows the street's route spline, a free walk of more than two cells a spline of its own; the rules, the
layout of `CharacterMovement` and the street evasion are in [animation-models.md](animation-models.md) §3.19.
Death (entity state 5): once the current clip has no time left the figure sinks by `0.35 × tick length` per logic
tick (the double S 007fa780 = 0.3499999940395355) S 006c7640 [known]. The test runs before the tick's new clip is
applied, so a figure that dies out of a looping clip (negative remaining time) starts sinking at once. The offset
goes to the movement's height target (+0x120), is interpolated over the tick as previous / current (+0x124 /
+0x128, `UpdateLogic` S 006c4f40) and is added after the terrain snap (S 006c57b0) [known].

**Animation slots** [known] pointer table S 008816b8 (10 entries; names at S 007f997c..):

| Slot | Name | Slot | Name |
|---|---|---|---|
| 0 | `Stand` | 5 | `WorkLoop1` |
| 1 | `Walk` | 6 | `WorkLoop2` |
| 2 | `SwimIdle` | 7 | `Pickup` |
| 3 | `SwimFwd` | 8 | `PutDown` |
| 4 | `WorkLoop0` | 9 | `Hit` |

(strings of slots 0 and 1 at S 007e5f38 and S 007e5f30.)

**Slot choice per logic tick** `CCharacter::UpdateLogic` S 006909f0 [known]:

1. skipped when the character has no face or the settler's state (`settler +0x54`) is 6;
2. the per-type face (`Worker`, `Carrier`, `Soldier`, `Constructor`, `Specialist`; virtual +8) may return a slot;
   a carrier in a boat returns 4 or 5 S 006c9250 [inferred];
3. otherwise the state code of the face (`+0x1c`): 2 → 8 (`PutDown`), 3 → 7 (`Pickup`), 4 → 4, 5 → 5, 6 → 6,
   7 → 9 (`Hit`), anything else none [known] S 006c6590; a result of 4, 5 or 6 is discarded when the face's byte
   `+0x2c` is set;
4. otherwise from movement: below the water level `2 + moving`, else `0 + moving`.

The slot is queued (`+0xa4`) and applied by the per-frame update.

**Animation choice for a slot** `AnimationSet::GetAnimIdForSlot` S 006ca8d0 [known]: four keys are set each tick
(`SetSelectionKeys`: `keyA` = face `+0x24`, `keyB` = face virtual +0x14, `keyC` = face virtual +0x18,
`outerKey` = `settler -> +0x28 -> +0x44`, the tribe [inferred]) [known] S 006909f0. Lookup order, first hit that
is not -1 wins:

1. override table C `[outerKey][keyC][slot]` (if `keyC != -1`);
2. override table B `[outerKey][keyB][slot]` (if `keyB != -1`);
3. override table A `[keyA][slot]` (if `keyA != -1`);
4. the default animation of the slot.

The tables are built by probing animation names `"<slotName><propertyName>"` [inferred] S 006cc350: A = goods
(for example `StandWood`, `WalkWood`, `StandPlank` in `settler_animations.xml` [known, file]), B = per tribe and
good of type 1, C = per tribe and a second property family (job names are the candidate; [TODO] read the property
map used in S 006cc350). `<Animation tribes="mask">`: 0 = all tribes; the first name match is final even when the
mask does not fit S 006ca790 [inferred].

**Playback** [known] S 006c64c0, S 006c63a0: default loop mode = `slot > 3`; an unchanged request (same slot
and loop mode) does not restart; the playback speed is taken from the face (virtual `+0x34`) when the face
allows it (virtual `+0x30`) and the evaluated skeleton is not shared with another character; global
`<Animations globalSpeed="1.8"/>` [known, file]. Characters that play the same animation share one evaluated
skeleton (`CModelCache`, pool collected every 10 s) S 006ad380 [inferred]: all walkers are in phase unless an
exclusive instance is requested.

**Idle variations** [known] S 006c64c0, S 006c6590, [known, file `settler_animations.xml`]
`<RandomAnimations><Random minDelay="5.0" maxDelay="8">`: when slot 0 is requested again unchanged and the
animation set has random animations for `keyA`, a random-animation player is created; on a logic tick it picks
a one-shot variation (`probability` attribute per animation), which is played once, and when its remaining
time reaches 0 the slot's base animation is looked up again and resumed. Any other slot request destroys the
player.

**Carried goods and tools** [known] S 006c7850, S 006c7460, S 006c74f0: every settler class except the carrier
gets the settler type's tool or weapon item (its `gfxGoodId`) attached at the definition's `link` bone
(`SLOT_HandR`); a carried good overrides it (the tool is hidden while a package is held and shown again after),
and while nothing is carried the tool's good is animation key A, which selects the `…Axe`, `…Scythe`, `…Sword`
clips ([animation-models.md](animation-models.md) §3.9, §3.13); `<Characters goodOffset goodRotation
boatOffset>`. Animation events (`<Sound>`, `<Particle>`, `<Item>` children of an `<Animation>`)
fire at their `start` time S 006867d0.

**Other per-type visuals** [inferred]: soldier buff effects `SoldierDamage` (hand), `SoldierDefense` (body),
`BlindSoldier`, `ArcherSpeed` S 006c7f80; speed boost effect `SettlerSpeed`; carrier boat effect `BoatFX`, boat
bobbing `sin * 0.15 + 0.3`; door animation of the target building when the path progress passes the building's
`enterDistance` / leave distance S 006c7510; footstep sound every `0.5 / rate` s near the
camera.

**Donkey** [known, file] `<Donkey scale=".01" mesh model link="SLOT_Goods">` in `settler_config.xml` (the
shipped mesh is the transport ox, `oxTransport.KEX`) with its own animation list under the slot names above;
`donkey.fx`.

### 3.11 Map objects and instancing

Everything that is not a building, character, ship or animal is a *landscape element* instance: trees, stones
(deposits), wheat fields, flags, harbor markers, gates, route buoys, doodads, chests, spawn markers. One
`InstanceMeshRenderer` per element definition batches all its instances.

**Which element** `MapObjLayer::SpawnLandscapeObject` S 00690240 [known]: the logic object's gfx name (deposit,
doodad or spawn property `gfxName`, or a fixed name such as `z_harbor_00`) is compared exactly, case-sensitive, with
the `name` of every element (a `SingleLandscapeObjects` definition first); a name that matches no element creates no
instance and reports nothing.

**Placement** `MapObjLayer::AddInstance` S 0068dd40 [known]: the vertex's world position; for kinds 1 (`flag`) and 9
(`harbor`) a shift of 1.3 street widths (`<Street width>`) on z, toward -z when
`((0x3434b6 - (u*u*0x4bd9 + 0x2e48d)*u) & 0x4b746f) / 3354521.0 <= 0.5` with `u = i*0x3a ^ i*0x74000`,
`i = vy * vertexWidth + vx` (u32 arithmetic), else toward +z (the compare at S 0068ddd3-0068dde2 is `FLD r; FCOMP 0.5f;
FNSTSW AX; TEST AH,0x41; JNZ`, taken for `r <= 0.5` to 0068ddf9: `z = z - width*1.3` (`FSUBP`); otherwise 0068dde4:
`z = z + width*1.3`; the 1.3 is the double 1.2999999523 at S 007f97c8; `r` reaches about 1.47, the mask 0x4b746f exceeds
the divisor 3354521, so the "minus" share is not one half); plus the element's `offset`; a yaw
`rotMin + r * (rotMax - rotMin)` from one draw and the scales `min + r * (max - min)` for x, y, z from three more,
always, whatever the ranges; world = scale * rotationY(yaw) * translation (row vectors: scale in the model's axes);
then the height sampled at that position (`TerrainGrid::SampleHeightAndNormal`), raised to the water level when at or
below it if `alignOnWater`. `rot` is read as integer degrees and converted to radians at parse time (S 0068f200); the
`type` strings give the kinds flag 1, tree 2, stone 3, wheatField 4, gate 5, routeBuoy 8, harbor 9 [known]. The draws
`r` are `Math_Random_NextUnitFloat` S 006ec410, `(next % 1000001) / 1000000` rounded to float, of the Park-Miller
generator S 0088d4ec seeded 0x5432ace0 at program start and never reseeded (§8). An element with `meshType="none"`
(`z_harbor_00`) is placed without a mesh, so it takes its draws and draws no model; the harbour place still shows
its ground plot (below). When a height change re-grounds an object (vftable slot 5, below), the base
`InstanceMesh::UpdateGroundHeight` S 006db520 sets an `alignOnWater` object to the water level always, not only
when it lies below it [known].

**Harbour place plot** [known]. `Scene::OnHarborCreated` S 00682ec0 places `z_harbor_00` (`type="harbor"`, kind 9)
at every harbour cell, owned or not, through `SpawnLandscapeObject` S 00690240 → `AddInstance` S 0068dd40 →
`InstanceMeshRenderer::AddInstance` S 006b90a0, whose case 9 creates an `S2CG::Harborplace`. `Harborplace::ctor`
S 006db7a0 calls `HouseDecalRenderer::AddDecal` S 006b4400 with `"[data]/buildings/Harbour_decal.KEX"` (string
S 007fc234), group `GROUND`, at the instance's world matrix, unconditionally. The file's `GROUND` mesh is a 6 × 6
grid textured from `house_decal.dds`, quadrant u 0..0.5, v 0..0.5: the compass-rose stone circle [known, file].
`Harborplace::UpdateGroundHeight` S 006db8d0 (slot 5) removes the decal and adds it again at the re-grounded matrix;
the destructor S 006db700 removes it. Slot 5 is called by `CTerrainCellMgr::UpdateCellHeightsInRegion` S 006b7220
for every object attached to a terrain block that a height change touches: the changed rectangle's corners go
through `MapPos::SetFromFinePos` S 00675160 and are divided by 4 (blocks of 4 × 4 cells, §2.1), inclusive, and an
object belongs to the block of `InstanceMesh::GetClampedMapCell` S 006db650 / 4 (`CTerrainCellMgr::AddObject`
S 006b7070). The plot is drawn with every ground decal (§3.9), in the buildings pass after the streets, so it covers
a street's end at the harbour flag. The harbour flag itself adds only its model `z_harbor_flag_00` and its goods
pile (`Scene::OnFlagCreated` S 00682ca0): it has no ground of its own. `harbor_flag.KEX` (182 vertices, height 0 to
3.358) stands on a pole foot, eight vertices of a ±0.25 square, no plate; it stands upright (yaw ±3°, no tilt:
`AddInstance` S 0068dd40 samples the height with a null normal) at the terrain height of its shifted position. A
"path circle" at a harbour is the street crossing fan (`StreetDecal::BuildJunctionFan` S 006de590), present only when
a land street ends at the flag; the stone ring is the plot above [known]. The plot, like every ground decal, has no
depth bias and no vertical clipping: the cut is the three edge planes of each terrain triangle (`ClipByPlanes`
S 006ed6e0) with a lift of 0.01 above the fine triangles, whatever level the
terrain draws [known]. Within half the level-of-detail distance of the selection point (§3.3: 42 to 136 units by
preset; at the original's zoom the view near the focus) the terrain draws the fine grid, so the plot lies on the
drawn surface there; farther out a coarser level can cover parts of it [inferred from §3.3].

**Creation order**, which fixes which draws an object gets [known] S 005273d0, S 005b3a90, S 0053ec60, S 00543f50,
S 00683040, S 00682ec0: the map's objects reach the renderer through the logic callbacks of `NLogic::System::PostLoad`:
the navy first (sea routes in stored order, each with its start buoy and, when both harbor ends are set, its end
buoy; then the harbors in stored order), then the resources (deposits in stored order, those with growth ≥ 0, S 00542f00),
then the doodads (the static, temporary and blocking maps, each in ascending id), then the spawn points. A gfx name
without an element creates nothing and draws nothing. Because the generator carries on across maps, a second map in
one session gets other yaws than the first [inferred].

**Instance classes by `type`** [known, file] for the values, [inferred] for the classes: `tree` → `TreeInstance`,
`stone` → `StoneInstance`, `wheatField` → `WheatInstance`, `gate` → `Stargate`, `routeBuoy` → `RouteBuoy`,
`harbor` → `Harborplace`, `flag`, none → plain `InstanceMesh`.

**Draw** [inferred] S 006b8ec0, S 0068d360: batches of `numInstances` per draw call with one matrix array upload;
a batch breaks when the instance colour (`FLAG_COLOR`, the owner colour of flags) changes; distance fade on the
non-instanced path `alpha = 1 - (d^2 - start^2) / (end^2 - start^2)`. `shadowCast`, `shadowReceive`,
`forceShadowPass` and `priority` per definition.

**Blend modes** `MapObjLayer::RenderEntries` S 0068d360, `CGraphicDevice::SetAlphaBlend` S 004d4710 [known]; the
alpha reference is 0.5 for all of them; blending always turns depth writes off:

| `blendMode` | Alpha test | Blending | Other |
|---|---|---|---|
| 0 (default) | on | off | |
| 1 | on | `SrcAlpha / InvSrcAlpha` | |
| 2 | off | **additive** `SrcAlpha / One` | fog off for the draw and the per-instance path forced (`InstanceMeshRenderer::Render` S 006b8ec0) |

`map_objects.xml` says the same in its header comment. The shipped mode-2 elements are glows and fog sheets
(`fogHighland_00/01`, `lavafog1..4`, all with `doodads_shader.fx`): drawn opaquely they show as flat grey discs.

**Culling** [known] S 004d3c20, S 0067eb20, S 006b8ec0: `CGraphicDevice::SetCullMode(id)` writes `id` to
`D3DRS_CULLMODE` unchanged; the main view uses 2 (`D3DCULL_CW`, clockwise triangles dropped, so front faces are
counter-clockwise on screen), the mirrored reflection view 3 (`D3DCULL_CCW`). `RenderEntries` sets it before
`InstanceMeshRenderer::Render` begins the effect pass, so a pass that names its own `Cullmode` wins: of the shaders
`map_objects.xml` uses, only `weed_shader.fx` draws both sides (`Cullmode = None` in all its passes); `duck`,
`waterlily` and `waterplants` set `CW`, the default; everything else is one-sided [known, files].

**Per-shader looks** [known, files `game/gfx/fx_20`]: a shader whose passes name their own render states overrides
the element's blend mode, because `InstanceMeshRenderer::Render` begins the pass after `RenderEntries` set the states:
`tree_shader2`, `tree_shader_winter`, `tree_shader_willow` and `weed_shader` blend with the alpha test at 127 and keep
writing depth (`STATES_ZENABLE_ZWRITE_ABLEND_ATEST127`); `tree_shader` and `signs_shader` alpha-test without blending;
`stone_shader` neither tests nor blends and adds `pow(saturate(dot(refl, V)), 16) * tex.a * tex` with
`refl = normalize(2 * D * N + mainLight)` (`D` the lit colour, used as a vector as written), so its texture alpha is a
specular mask; `rock_shader2` multiplies the whole light by the vertex colour. `rock_shader`, `rock_shader2`,
`waterplants`, `waterlily` and `duck_shader` add the **water haze**: per vertex
`a = saturate((y + hazeMax + 0.05) / hazeMax)` from the world height, `hazeColour = lerp(bottom, top, a - 0.3)`, per pixel
`lerp(hazeColour, lit, a)`; `top` = (0.5, 0.5, 0.8) and `hazeMax` 5.5 in `rock_shader`, (0.3, 0.3, 0.8) and 7.0 in
`rock_shader2`, (0, 0.8, 0.3) and 7.0 in the water shaders; `bottom` (0, 0, 0.05) in all.

**`transparent`** [known] S 0068d360, S 0068d610: `RenderEntries` draws only the elements with `transparent` false;
the ones with `transparent` true are drawn by `MapObjLayer::RenderClippedEntries`, with user clip plane 1 at the
water height, so only their part above the water is drawn, in the step that draws objects and water
(`CMapRenderer::RenderObjectsAndWater` S 006889d0).

**Trees** `TreeInstance::UpdateAnimation` S 006dcb10 [inferred]: state 1 growing: with `g` = the resource's growth 0..1
(`resource +0x18`), scale `(min(1, 3g), g, min(1, 3g))`; state 2 standing (growth ≥ 1): a sway branch, a rotation
about a horizontal axis by `amplitude * sin(phase)` while being felled at, which never runs: the sway byte
(`TreeInstance +0xe8`) is only ever written 0 (S 006dca2f, S 006dcf70) [known]; state 3 falling: rotation about
the fall axis by a fading angle; state 4 fallen. Value changes are faded at rate 10 per second (one logic tick).
The fall [known] S 006c87d0, S 006dd050, S 006dcd40: the woodcutter's render logic (`CharacterWorker::UpdateFellingObject`,
§3.10 of [animation-models.md](animation-models.md)) takes the job's tree unless it is already falling or fallen
(state 3 or 4), turns the figure toward it, and once `workElapsed > 3.0` s calls `TreeInstance::StartFalling` with
the negated worker-to-tree direction: state 3, angular speed `(π/2) / (g_AnimTimeScale × 20)`, the fall axis from
that direction (`SetFallAxis` S 006dcfd0), and sound `0x01c27b83` (`sound_treefall`) plays at the tree. The
emitter branch of `StartFalling` is dead: the tree's emitter `TreeInstance +0x124` is only ever written null (the
constructor at S 006dca49, the destructor at S 006dc908; every `+0x124` store and LEA in the binary checked)
[known]. The direction is `GetDirectionToObject` S 006c8740: from the figure's render position (movement `+0x58`)
to the tree, horizontal only. The tree turns about that line itself, so it falls sideways across the line from the
worker through the tree rather than straight away from the worker; on a scaled tree the axis is not normalised,
which skews the fall slightly [known] S 006dcfd0. `RotationAxis` S 006e8fa0 builds the standard Rodrigues matrix
but the engine applies it to row vectors, which is the opposite rotation sense to D3DX's [known].
`UpdateFalling` S 006dcd40 runs once per logic tick: its only caller is `TreeInstance::Tick` S 006dcf00 (slot 11,
`+0x2c`, of the tree vftable S 007fc440), the per-tick update that `MapObjLayer::Update` gives map objects from
`CMapRenderer::SyncLogicTick` S 006882c0 (§4.2) [known]. Each call adds `speed × tick length` (`speed / timeRecord[3]`) to the angle (with the previous
value kept for the fade) and multiplies the speed by 1.2000000476837158 (the double S 007fc478); once the angle is
`≥ (float)(π/180 · 90)` the state becomes 4, and the tree lies until its deposit is removed; the deposit level fade
below then sinks it lying down, since `AnimateMeshesAndLevelFades` lowers only the translation y of the current
matrix [known].
Wind is in the vertex shader (`tree_shader*.fx`): `pos.x += s * sin(waveSpeed * m41 + t)`,
`pos.z += s * cos(waveSpeed * m43 + t)`, `s = saturate(dot(pos, pos) * waveStrength) * m22` [known, file]. `waveSpeed` = 0.35 pi,
`waveStrength` = 0.003 (`tree_shader_willow.fx`: 0.3 times that, and `pos.z += 0.12 * sin(pos.z * 8 + 2.6 t)` where
`texcoord.y < -0.5` and `pos.y < 8`); `pos` is the model-space vertex with w = 1, before the instance matrix. The direct
light of trees is multiplied by the vertex colour. Other vertex animations [known, files]: water plants
(`pos.y += 0.12 sin(t) x`, `pos.x += 0.12 sin(t) y`), water lilies (world `y < 0.125`: `y += 0.11 sin((m41 + m43 + 2x) * 2
+ 2t)`), ducks (bobbing `0.07 sin(2z + 4t)` and circling with radius 4.5), ice floes (rocking by `0.6 * vertexColour.r`).

**Wheat** `WheatInstance::UpdateAnimation` S 006dc590 [inferred]: Y scale = growth, faded the same way; state 2 = grown.
One `WheatInstance` exists per field deposit (ctor S 006dc490, `UpdateGrowth` S 006dc660; `Scene::OnDepositAdded`
S 006815e0 → `SpawnLandscapeObject` S 00690240 → `AddInstance` kind 4 S 006b90a0); once growth ≥ 1 and the
resource's level counter (+0x50) is 0, state 2 uses the base matrix [known].

**Extended meshes: the wheat field cluster** [known]. `meshType` is parsed by S 0068f200: `"extended"` → 1, `"none"`
→ 2, anything else 0 (exact compares); `Wheatfield` is the shipped element with `meshType="extended"`.
`InstanceMeshRenderer::LoadMesh` S 006b9690 builds a mesh of type 1 as `ExtendedMeshData::ctor(3.0, (1, 1, 1))`
S 006dd7e0: one instance is a cluster of 300 sub-instances. `ExtendedMeshData::Load` S 006dddc0 loads the KEX with
`CMesh::Load(merge = true, rebase = false)` S 0076e0d0, so the variants are the file's subsets (`LO_Wheat.KEX`: six
tufts `RS_Wheat07..02`, 36 vertices and 54 indices each); each sub-instance gets the variant
`Rng_ParkMillerNext % n` from the generator S 0088e118, which only this code uses and which is seeded `0x5432ace0`
at program start (S 007cb190; [engine-core.md](engine-core.md)). `BuildInstancedVertices` S 006dd8e0, per
sub-instance `i`: `SetSeed(this + i)` (`LEA ECX,[EDI+ESI]` at 006dd960, `this` the `ExtendedMeshData`; a heap
address, so the scatter differs between runs and its exact value is runtime-only; `SetSeed` S 006ec2a0 leaves a seed
with 8..24 set bits unchanged, which a heap address plus `i` < 300 normally has, while seeds with fewer bits are
balanced with bits from S 007fd528 and small bases collapse onto each other), `r = NextUnit × 3.0`,
`a = NextUnit × 2π` (S 00882840), the variant's vertices scaled, then moved by `(cos a × r, 0, sin a × r)`; byte 0 of
`BLENDINDICES` is the batch slot, bytes 1..3 are not read by `weed_shader.fx`. `BuildInstancedIndices` S 006ddce0:
the variant's local indices plus `i × verticesPerVariant`. A field is therefore drawn as a disc of wheat tufts about
6 units across around its deposit, one cluster per deposit. The material is the first subset's texture
(S 006b9690); the cull bounds are those of the unscattered mesh: `ExtendedMeshData::Load` S 006dddc0 computes the
box before any scatter and never updates it, and `LoadMesh` S 006b9690 takes the bounding radius from that box's
diagonal [known].

**Deposits (level fade)** `MapObjLayer::AnimateMeshesAndLevelFades` S 0068d160 [inferred]: a counter 0..20 on the logic
object (`+0x50`) lowers the instance by `level * extentY` (the pile shrinks into the ground), faded at rate 10.

**Route buoy** `RouteBuoy::UpdateAnimation` S 006dba70 [known, disassembly]: `y = seaLevelHeight + 0.15 * sin(t * 0.45
* pi + x + z * 143.5)` with `x`, `z` the buoy's world position and `t` the frame context's time (float S 007fccfc = pi,
doubles S 007fc2d8 = 0.45, S 007fc2d0 = 143.5, S 007f9f80 = 0.15); the large factor on `z` puts neighbouring buoys out
of step. Its fire emitter follows. **Flags** wave in the vertex
shader (`flag_shader.fx`; `harborflag_shader.fx` computes the same strength and never applies it, so the harbor flag
hangs still [known, file]): `CalcFlagVertexPos` [known, `shared.inc`]:
`s = 0.33 * saturate(dot(p.xz, p.xz) - 0.02)`, `c = 0.5 + 0.5 * cos(4 * (m41 + m43 + p.x + p.y + t))`,
`p.z += s * c`, `p.x += s * (1 - c)`. Their colour is the owner's colour by the `CalcPlayerColor` rule
`lerp(playerColor * 1.8, tex.rgb, tex.a)` (§3.8), and the flag passes have no alpha test, so flags are drawn
opaque [known, file].

**What is drawn at all** (2026-10-15):
- **Priority gate** (`MapObjLayer::RenderEntries` S 0068d360): an element is drawn when its
  `<LandscapeElement priority>` (default 0, S 0068f200) is at most `CMapRenderer+0xa0`, or when `device+0xc8`
  (`bExternalWindow`, the editor) is set. `+0xa0 = ftol(Settings.detail)` (`Scene::ApplySceneSettings` S 0067f500);
  the presets give `detail` 0, ⅓, ⅔, 1, 1 (`ApplyQualityPreset` S 00695860), so the level is 0, 0, 0, 1, 1. Of 230
  elements, 50 have priority 0, 32 have 1, 35 have 2, 24 have 3, 15 have 4 and 74 none (0). **[known]** Consequence:
  elements of priority 2 to 4 (grass, stones, plants, cacti, shells, water plants) are never drawn in the game
  **[inferred; to verify live by reading `CMapRenderer+0xa0`, instance S 0088cf64, in a running match]**; who could
  set `detail` above 1 is open.
- **Size cull** (`InstanceMeshRenderer::RenderShaderInstanced` S 006b8250, `RenderPerInstance` S 006b8600): an
  instance is drawn if `0.0009·d² > 0.01` (nearer than 3.33 units it is culled) and `boundingRadius / (0.0009·d²) ≥
  lodDistance`, d from the eye, `lodDistance = 1 − objectDetails` (`CMapRenderer+0xa4`, S 0067f662): at preset 0 a
  radius-r object vanishes beyond about 33.3·√r units, at the top preset nothing beyond the near limit. Skipped when
  `noDistanceCull` (`+0x90`, setter not found) or `bExternalWindow` is set. The per-instance path also fades the
  instance out with `alpha = 1 − (d² − fogStart²)/(fogEnd² − fogStart²)` (device fog range `+0x320` / `+0x324`).
  **[known]**
- Map objects have no LOD meshes. **[known, data]**

### 3.12 Streets, goods, ships, animals, projectiles, particles

**Streets** [inferred] S 0069f570, S 006df940: a street is a
decal mesh that follows the route spline of the logic street: `numSegments` slices per spline segment, half
width `width`, the terrain triangles under each slice clipped by four planes, texture v along the length scaled
by `texStretch`; a flag gets a 7-vertex hexagon fan (centre + 6 hex corners) with the crossing texture. Street
kind 0 uses `texture0` / `normal0` / `crossingTexture0`, kind 1 the `..1` set; a street under construction is
drawn with `alphaStreetColor`, the red variant with `redStreetColor` (`RenderStreetUnderConstruction`).
Water streets (route type 2) are a `WaterStreet` with a chain of buoys every `buoyDistance`; sea routes are
route decals with `routeTexture`, `routeWidth`, `routeNumSegments`, scrolled by `routeTexSpeed` over
`routeTexCount` frames. The build-mode preview is a `CStreet` made from a bare point path.

**Goods** [inferred] S 0069e0f0, S 006d82f0: an item per visible good, type by the good's
property name against `items.xml` `<Item name mesh>`; stacks at flags and building sites use
`<StackLayouts><Layout offset0..N good0..N>`; types with many visible items are promoted to instanced batches of
up to 40.

**Ships** [inferred] S 006a54c0, S 006a5cc0: position = lerp between the logic ship's two
cells by its progress; animation state 0 idle, 1 moving, 2 when the logic state is 6 or 7 (sinking set of
`ships.xml`: `idle`, `move`, `sink`); yaw steers toward the hex heading by at most 0.43982297 rad per logic tick,
clamped at the target, interpolated over the tick (`Ship::StepYawTowardTarget` S 006a4eb0 [known]: about 0.7 s
for a half turn); sine bobbing; a status overlay mesh
(`<Freight>`, `<Expedition>`, `<Soldiers>` meshes) by cargo kind; construction `frame` mesh per tribe, drawn
triangle by triangle with the frame's progress before the hulls, and a hull that rises through a user clip plane
with its fade ([animation-models.md](animation-models.md) §3.17) [known].

**Animals** [known] S 006ce2c0 ([animation-models.md](animation-models.md) §3.18): logic states 5, 7, 8, 9 play
the death animation once, after which the model sinks at `0.4 * dt`; an animal stands while its move progress is
< 0 and, only on the edge from walking, plays one of two idles chosen with a function-static generator (seed
0x5432ace0 on first use, shared by all animals for the life of the process); moving animals interpolate between cell and next cell and turn by at most 0.43982297 rad per logic
tick (`Animal::StepHeading` S 006cde40 [known]); a new animal starts with `Stand1` looping and heading 0, without
a random draw (`Animal::ctor` S 006ce090 [known]). Definitions in `animals.xml` (`model`,
`mesh`, `scale`, `<Animation
name filename>`).

**Projectiles** [known] S 006a3d90, S 006a3a40, S 006a32b0, S 006a3400, S 006a3610, S 006a3af0: launched at
`timeInfo[1]` from the current world position toward the target box. Until the launch the projectile copies its
owner's matrix (owner vtable slot 0) every frame (ctor S 006a3720, `Update` S 006a3400), so the start point is the
translation of that matrix at launch. Owners: a soldier (kinds 0, 2, 3; the character's per-type logic face +0x88,
slot 0x24, through `Scene::OnProjectileSourceSet` S 00681780), launched at once; the catapult (kind 1;
`CatapultBuilding` +0x21c, created on animation kind 4 in `PlayOneShotAnimation` S 006d6510), launched when the arm
reaches its limit (`CatapultBuilding::Update` S 006d6000). [TODO] which matrix the soldier face returns (bone or
body). The `projectiles.xml` records are the `<Projectile>` children of the root in file order (`LoadProjectilesXml`
S 006a4440; `name` only sets a type index that `AddProjectile` does not use), and the record is chosen by the
logic type (0 → record 1, 1 → 0, 2 → 3, 3 → 2); flight time = flight ticks × 0.1 s; ballistic arc with gravity
2.44269 for the catapult stone (type 1, S 00881a10) and 1.4715 otherwise, horizontal speed `distance / T`,
vertical `g/2 · T + dy/T`; the flight emitter follows the arc, the impact plays `impactPFX` once and its
`impactSound` (+0xac, when not −1) with `SoundSystem::Play3D` at the target point, and releases the flight emitter; model and tumble `rotation` from the same record. Details: `particles.md` §3.13.

**Particles** [known] S 00685bb0, S 004dfdc0: an effect name
maps to `[data]\scripts\effects\<name>.pfx`; emitters are culled, sorted back to front in depth buckets and drawn
with `particle_shader.fx` from one atlas; one-shot emitters delete themselves when empty. *Effect movies*
(`effectMovies.xml`: `<EffectMovie name>` with `<FX start particles link duration sound>`) are timed sequences of
effects on named links of a building or character. The file layout, the simulation, the drawing and the places
that start effects: [`particles.md`](particles.md).

**Resource hints** [known] S 0068b220, S 0068ac10, S 0068ad40: when the check time is reached and no candidate
is pending, one random cell is drawn in every visible block that is revealed (`TerrainCell +0xa0`, set by
`RevealFromExploreMap` S 006b5f80) and whose maximum height is above the water level. A drawn cell that is
explored by the viewing player and holds a ground resource (amount not 0) of the good that the name `IronOre`,
`Gold`, `Coal`, `Stone` or `Gemstones` resolves to becomes a candidate with the effect `Resource_<good name>`;
on the shipped maps that is gemstones only (`particles.md` §3.14). With at least one candidate the next check
follows after a random whole number of seconds in `ResourceFX minTime..maxTime`, with none after one in
`minTime / 2..minTime`. The spawn step then plays the one-shot particle effect of one random candidate and clears
the candidate list.

**Ambient swarms** [known] S 0069ab00: dormant in this build. Every `SwarmMgr` method tests a byte that only the
constructor writes (0), and the per-swarm draw of the main and the shadow pass is an empty function, so no flock
is ever built or drawn; `flocks.xml` is read and unused. The code as it would run: [`ambient-swarms.md`](ambient-swarms.md).

### 3.13 Light, fog, shadows, sky, post effects

**Light model** [known, `shared.inc`]: one directional light. Per-vertex objects:
`c = (ambient + saturate(dot(N, -L)) * lightColor)`, halved on the fixed-function paths. Shadows only darken the
direct term.

**Environment values** [inferred] S 006ae3a0: an `EnvData` gives clear colour, ambient, light colour, fog start
and end (linear distance fog) and shadow intensity; the light direction comes from `lightheading` and
`lightelevation` (degrees): `Matrix44::RotationYawPitchRoll(heading · 0.017453292, |elevation · 0.017453292|, 0)`
(the factor a float) applied to the unit Z vector (S 00882870) as a row vector, which gives row 2 of the matrix,
`(cos e * sin h, -sin e, cos e * cos h)` (the D3DX layout of S 006e90c0, [engine-core.md](engine-core.md) §3.8); it is
passed unchanged as the direction of the `D3DLIGHT_DIRECTIONAL` (`SetDirectionalLight` S 004d5340), so it is the
direction the light travels, pointing down for a positive elevation [known] S 006ae3a0, S 006e90c0, S 004d5340;
the shadow intensity is
scaled by `clamp((|elevation| - 20°) / 20°, 0, 1)`. The device stores the result through `SetInverseClampedFloat_15c` S 004f5120, which clamps its argument to
0..1 and keeps **one minus** it (`CGraphicDevice +0x15c`) [known, disassembly]; that this value is the shaders'
`g_ShadowIntensity` (`SHADOW_INTENSITY`), the factor of the direct light in shadow (`doShadow` in `shared.inc`:
1 lit, `g_ShadowIntensity` shadowed), is [inferred] from the name and from `Scene` turning shadows off when
`+0x15c >= 1.0` (§2.2). With the usual `shadowIntensity` 0.9 and an elevation of 40° or more, shadowed ground keeps
a tenth of the direct light: the environment value is how dark shadows are, not how bright.

**Light of objects** (`shared.inc` `CalcLight`, `mesh_shader.fx`, `doodads_shader.fx`, `tree_shader.fx`) [known,
file]: per vertex `colour = saturate(dot(N, -mainLight)) * lightColor` (trees also times the vertex colour), per pixel
`(ambient + colour * shadow) * texture`; the shader-1.1 paths compute `(ambient + colour) / 2`. The terrain uses the
same sum per pixel with its normal map (§3.4). All of it is in gamma space.

**Fog** [known] S 004d8f99, S 004d3ae0, S 004d3a80: `CGraphicDevice::SetDefaultStates` sets `D3DRS_FOGENABLE` 1,
`FOGTABLEMODE` = `D3DFOG_LINEAR`, `FOGVERTEXMODE` = `D3DFOG_NONE` and the fog colour = the background colour; so it
is per-pixel linear fog on view depth between the environment's fog start and end (`SetFogRange`), the shaders
write no fog themselves. `RenderSkydome` and the reflection view enable it too (the Scene's fog flag +0x720), so a
reflected object is fogged over the mirrored path's length, which includes twice the camera height, and the water
in front of it is fogged again [inferred from the states; presentation only].

**Local environment** `MapEnvData::Update` S 006ae700 [known]: per-map spheres (stride 0x44: the `EnvData`
+4..+0x30, centre x, z +0x34 / +0x38 in world units, inner +0x3c, outer +0x40). With `dsq` = the squared 2D distance
from the point below (summed in x87, stored as a float): `dsq < inner²` → weight 1; `dsq > outer²` → 0 and the
sphere does not count; else `w = 1 − (√dsq − inner) ÷ (outer − inner)`, and the sphere counts even when `w` is 0
(`dsq = outer²`); with `outer = inner` that boundary case divides 0 by 0. Every weight is multiplied by
`(float)(1 ÷ count)`; sphere 0 is assigned, the others are added (`AddWeighted` S 006ae170); when the sum is below
1 the map default is added with weight `1 − sum`; with no counting sphere the default is used alone. The point is
`Camera_GetGroundFocusPoint` S 0068ce50 (from `Scene::Update` S 006805e0): `(60 × hit + d × camera) ÷ (60 + d)` in
x and z, where `hit` is the screen-centre ray (`Camera_BuildScreenCenterRay` S 0068cdc0) cut with the plane
y = 0 and lifted to the nearest vertex's height (`Terrain_RayHitGroundApprox` S 0068a610), or the point 1000 along
the ray when `t < 0` or `t > 1000` (S 007d3e58), and `d` the horizontal camera-to-hit distance (60.0 at S 007dc9c8).
`ApplyToDevice` S 006ae3a0 applies the result.
Source: the map's `.bin` sidecar (`docs/map-format.md` §4.17): u32 skydome index, light heading, light elevation,
the default `EnvData` (12 floats: background, ambient and light colour interleaved per component, shadow
intensity, fog start, fog end), u32 sphere count, the spheres S 006aea80.

**Day time** [inferred] S 00684130, S 00683d50: `daytimes.xml` keys by hour; `<Enviroment timescale localtime
animated>`. In the shipped file all keys carry the same light and differ only in fog at hour 12
[known, file]. [TODO] not established: how the day-time keys and the per-map `EnvData` are combined, and whether
the hour advances in a match; read S 00683d50 and the device call S 004d3a50.

**Shadow map** [known] S 0067f420 for the levels, [inferred] for the rest:

| Level `round(setting * 6)` | Effect |
|---|---|
| 0 | no shadows |
| 1 | global S 0088d6bc = 1 only (the simple ground decal under characters is the candidate) |
| 2 | shadow map on (needs shader level > 1); caster mask 0x8 (buildings); technique 1 |
| 3 | caster mask 0xc (buildings and map objects) |
| 4 | S 0088d6bc = 0; flags 0x18; technique 2 |
| 5 | caster mask 0x3ff (all layers); flags 0x1a; technique 4 |
| 6 | technique 5; flags 0x5a |

The caster mask uses the map layer bits of §3.1 (`CMapRenderer::RenderWithExternalEffect` S 006884a0): terrain
0x1, buoys 0x2, map objects 0x4, buildings 0x8 (parts, an upgrade's target parts, frames, ruins and military flags,
as `BuildingRenderer::RenderWithExternalEffect` S 006a0cc0 draws them), territory borders 0x20 [known]. So the
mask is 0 below level 2, 0x8 at 2, 0xc at 3 and 4, 0x3ff from 5, and the terrain casts shadows only from level 5;
S 0067f420 also clears the mask while the shadow map quality (+0x2c) is 0 [known]. The level is
`trunc(setting × 6.0 + 0.5)` (`Scene::UpdateDetailFlagsAndTime` S 0067f6b0, ftol), the options panel's
`cShadowDetail` ([app-shell.md](app-shell.md) §2.7).
Render target `128 << level`, level 0..4, R32F (or a hardware depth format), S 00769600: `ShadowManager::SetQuality`
multiplies the quality (`cShadowQuality`, Scene +0x2c, passed by `Scene::RenderShadowMapPass` S 006810b0) by 4.0,
truncates and clamps to 0..4 (disassembly), with a step down when free texture memory is 32 MB or less [known];
light matrices fitted
to the camera frustum clipped by the scene bounds, orthographic or perspective-warped S 00769880, S 00769f10.
Lookup [known, `shared.inc`]: `test = z / w + shadowScale.y`; lit if `test < depth`, else `shadowIntensity`;
2 x 2 taps bilinearly weighted (`SOFT_SHADOW`). `<Shadows scale="1.0" bias="-0.00325"/>` [known, file] feed the
device values behind `g_ShadowScale` [inferred] S 0067edd0.

**Sky** S 006af960, S 006af490, S 00683e50, S 006af260: one mesh "SkyPlane" built once by
`SkyRenderer::BuildGeometry(inner 5000, outer 5010, n 64, texScale 7, 7, sunSize, moonSize)` [known; the values below
from the disassembly of S 006af490, whose stack effects admit only this reading]:

```
span  = 2 * sqrt(outer^2 - inner^2)                    = 632.8 world units
x     = col * span / n - span / 2,   z = row * span / n - span / 2        (col, row = 0..n)
y     = -(x^2 + z^2) / outer                           (0 at the centre, -40 at the corners)
alpha = 1 - ((c - col)^2 + (c - row)^2) / (n + 1)^2,   c = (n + 1) / 2   (0.5 at the corners)
uv    = (7 * col / n, 7 * (1 - row / n))
```

followed by a sun and a moon quad (half sizes from `<Sun size>`, `<Moon size>`). The highest point is the centre, so
the mesh is a shallow **dome** (a cap opening downward). It **follows the camera** [known]: `SkyRenderer::Update`
S 006af210 copies, once per frame, the eye position of the device's active camera (`CGraphicDevice +0x1b4`, set by
`SetActiveCamera`; slot 2 of the camera interface, `GetEyePosition`) into the renderer's `+0x40..+0x48`, or the
vector at S 0088f1b0 when there is no camera; `BeginSkydomePass` S 006af260 takes the identity matrix and sets its
translation to that eye position plus `(0, 15.0, 0)` (double S 007e2aa8). So the apex sits 15 units above the eye,
the dome passes eye level about 274 units out (`sqrt(15 * 5010)`) and its rim is 25 units below the eye: looking up
shows its inside, toward the horizon its lower part. Both views draw it first: `Scene::RenderPasses` S 0067eb20 runs
it when pass bit 0x001 is set (the main view's mask is 0x1ff), `RenderReflectionPass` S 00680ab0 in the mirrored
view; it writes no depth, so everything drawn after it covers it [known]. Because the eye is taken once per frame,
the mirrored view sees the dome of the main camera, from below the water [inferred: the copy is made by the per-frame update, not per view; other writers of `+0x40` were not searched].
**Quirk (presentation only): the reflected sky ends at a hard edge.** The mirrored camera sits as far below the
water as the main camera is above it, so for water farther from the camera the mirrored view rays rise past the
dome's 633-unit square and the reflection shows the clear colour behind a straight cut [inferred from the geometry;
the remake's viewer, which draws this geometry, shows the cut, maintainer 2026-10-14]. No simulation state depends
on it; the remake may continue the dome's surface past the square in both modes.
`DrawSkydome` S 006af150 draws only the grid: the sun and moon quads are built and never drawn
[known]. `RenderSkydome` S 00683e50 binds the skydome texture of the map's `.bin` index (`<Enviroment><Skydome>`
in `graphics.xml`: Clouds, Stars, Egypt, Bavaria, Scot) with a rotation texture matrix, and a second one only when a
secondary index is set [known]. Shader (`enviroment_shader.fx`, technique `Default`) [known, file]: the vertex
shader `Main_VertexShader` sets texcoord 0 = `rotation(uv) + g_Timer.y × (0.015, 0.005)`; the pixel colour = the
texture alone (the vertex colour, and with it the alpha above, and the day-time blend of two textures are used
only by the `combineTextures` variant, which the `Default` technique does not compile), alpha-blended over the
background colour, depth test on, no depth write.

**Shader time** [known] S 004d78a0, S 0067f6b0: `g_Timer` (`TIMER`, handle S 008874dc in the table S 0088746c)
is `CGraphicDevice +0x300`, written by `BeginRendering` S 004d78a0 with `.x` = Scene +0x58 (the frame delta)
and `.y` = Scene +0x4c. `Scene::UpdateDetailFlagsAndTime` S 0067f6b0 copies `NLogic::System.accumulatedTime`
(+0x7c) into Scene +0x4c (and the system's frame delta +0x74 into +0x58): game seconds, scaled by the game speed
and standing still in a pause. (With its real-time argument set the function accumulates a high-resolution timer
instead.) So the clouds drift with game time; the main view and `RenderReflectionPass` S 00680ab0 share the value.

**Environment particle layer** (`ai::render::EnvParticleLayer`, 0x258 bytes) [inferred] S 006adc90: a grid of
falling streak billboards (spacing 0.1) around the camera with a per-point pseudo-random phase;
`rain_shader.fx`. **Not present in this build**: the class has no constructor in the binary, no function allocates
0x258 bytes, and the only pointer to a layer, `CEnviromentMgr.envParticleLayer` (+0x120), is written by the
manager's constructor (S 00685112) and destructor (S 00684880) only, both times with 0. `Update`, the draw step
of §3.1 and the debug draw act only on a non-null pointer, so no weather is ever drawn [known for the writes;
inferred for the absence of an allocation]. The layer is a render object: presentation only.

**Post processing** (`S2CG::PostProcessor`, 0x6c bytes; exists while the POSTFX setting is on, `Scene::Render`
S 006836b0) [known] S 00696d20, S 00697010, S 00696ac0, S 00696f10, file `postprocess.fx`, `shared.inc`:

1. `BeginScene` binds two targets: the scene colour, and a second target that every scene shader fills through
   `COLOR_OUT` with its view depth (`PixelOut.luminance = viewZ`; the name is a leftover). The focal distance
   `g_PostFx_FocalPoint` moves toward the view depth of the active camera's focus point (camera interface slot 6,
   fallback a fixed point); the range is set to `1 / (focal + focalScale)` through `SetValueAndInverseRate` S 00696ca0.
2. `RenderBlurPasses`: `CopyToTempBuffer` copies the scene colour into a temporary target and writes
   `alpha = saturate(L - bloomParameter.y)` with `L` the sum of the maximum of nine taps of the second target;
   then `BlurHorizontal` and `BlurVertical`, each a 9-tap box blur.
3. `RenderCombine`: `lerp(blurred, scene, dof)` with `dof = 1 - saturate(|depth - focal| * range)`; technique 4
   when the device can blur and a focus was found, else 3; both compile the same function, and neither blends.

So **no bloom reaches the screen**: the bloom alpha of step 2 is never read (the combine ignores alpha and writes
with blending off), and its threshold is taken from the depth target [inferred from the three functions and the
pass states]. What the player sees is depth of field: sharp around the focal distance, the blurred copy elsewhere.
`minLuminance 0.98`, `bloomScale 0.25`, `focalScale 25.0`, `focusSpeed 3.0` [known, file]. The temporary targets'
size is [TODO] (the arguments of `CreateRenderTarget` in S 00697290 are not resolved by the decompile).

The post-processor is off by default: `Settings::bPostFxEnabled` (+0x0c) is 0 from the constructor S 00695b40, is set
only by `ParseCommandLine` S 00403c7f for `-postFX` (via S 00695bb0), and `Settings::Load` S 006960a0 sets it to 0
after reading it [PROVEN]; the order of the two at start-up is not read [TODO]. When it is on, `PostProcessor::BeginScene`
S 00696d20 renders the scene into `sceneColorRT` with a depth surface of its own, `EndScene` S 00697250 restores the
backbuffer and its depth surface, and `UpdateFocusAndCombine` S 00696f10 / `RenderCombine` S 00696ac0 draw one
full-screen quad with ZEnable false: the backbuffer's depth then holds no scene depth (only the frame's `Clear` to
1.0), so the overlay's depth test passes everywhere and the icons appear on top of everything [PROVEN for the targets
and depth flow; the visual result is inferred].

### 3.14 Selection markers and the build-placement overlay

**Selection markers** `CMapRenderer::UpdateSelectionMarkers` S 00689500 [inferred]: up to 4 projected decals. By
selection kind: a map cell with a radius, a building, a unit, a ship (radius fixed to 11). Enemy targets use
style 2; linked buildings and destinations get the extra markers; a marker whose target is gone clears the
selection. A selected ship gets a size-11 marker that follows it (`SetTargetShip` S 006b0cd0) plus the two end
cells of its route while it is on one; a selected route gets its two end cells plus the local player's ship on it
[known] S 00689500, S 006b0cd0, S 006b0d00 ([ingame-ui.md](ingame-ui.md) §3.5 for the picks and the selection
kinds). A marker vertex below the water level is lifted to the water level (`DecalProjector::BuildVertices`
S 004efe20, the `minHeight` argument, [world-objects-rendering.md](world-objects-rendering.md) §3.9) [known]. The
ship box's 128 × 128 picture of the ship is rendered once per ship (`RenderShipPreview` S 0068cb60) [known]. The decal is projected onto the terrain triangles under it (`CLandscape::ProjectDecal` S 0068aad0);
textures from `decals.xml` (3 `<Texture>` entries: `decals.dds`, `buildingselect.dds`, `catapultTarget.dds`, all
in `[data]\gfx\`) [known, file]. The marker [known unless tagged]:

- takes the whole texture, UV (0, 0)–(1, 1), in white; the style is the index into the `<Texture>` list
  (`SelectionMarker` `CreateDecal` S 006b0b50 → `DecalRenderer::CreateDecal` S 004df1d0) [inferred: that the
  style indexes the list]: 1 `buildingselect.dds` (style 1 is set in S 00689500), 2 `catapultTarget.dds` (an
  enemy building);
- is a square whose full side is the size (`DecalProjector::BuildVertices` S 004efe20, `SetSize` S 004efd10,
  `GetClipPlanes` S 004f0390): 4 world units for a flag, a street cell and a clicked cell
  (`PushSelectionToScene` S 00615bb0; also the cell ring of build placement, `BeginBuildPlacement` S 006176d0 /
  `SelectCell` S 00617770, [ingame-ui.md](ingame-ui.md) §3.5), and for a building the larger of the x and z
  sizes of its box (S 006b0bc0);
- turns by `time × 0.025132744` radians, i.e. 2π / 250 per second (`SelectionMarker::UpdateDecal`
  S 006b0d00). The time is the scene's `+0x4c` (`Scene::Update` S 006805e0 hands `&Scene +0x48` to
  `CMapRenderer::Update` S 006888f0, which keeps it at `+0x50` for `UpdateSelectionMarkers` S 00689500), which
  `Scene::UpdateDetailFlagsAndTime` S 0067f6b0 sets to `nGame::System`'s accumulated time while its flag is 0
  (with the flag set, to a running high-resolution timer sum instead): simulation seconds,
  scaled by the game speed ([logic-core.md](logic-core.md) §3.1). So the spin follows the game speed, stands
  while the simulation stands, and its phase is the absolute game time, not the time since the marker appeared
  [known];
- lies 0.3 above the ground (the normal offset of the projection,
  [world-objects-rendering.md](world-objects-rendering.md) §3.9).

**The decal pass** [known]: `gfx/fx_20/decal_shader.fx`, technique `Default`, pass `RenderDecal`: `ZWriteEnable` False,
`AlphaBlendEnable` on with `SrcBlend` SrcAlpha and `DestBlend` One (additive: the marker glows), `Lighting` False. The
vertex colour is white; the only motion is the spin above (`time × 0.025132744`); an own and an enemy marker differ only
by their texture (`buildingselect.dds` or `catapultTarget.dds`). In the scene's passes the decals are drawn as pass 8,
after the terrain, the streets, the characters and the ships, and before map part 2 (the map objects and the water).

**Build-placement overlay** `ConstructionMapRenderer::AddCellsInRect` S 006b36d0: for every cell of every visible
block, except the cell the cursor hovers, the construction flags of the cell for the local player
(`docs/sim/map-resources.md` §3.5) choose an icon. Cells whose flags are 0 get none, and nothing is drawn when
the player's byte +0x50 (active) is clear [known]. The player is the game screen's (`+0xfff4`, the local player,
`RenderPostFxAndOverlay` S 00680a00). The same +0x50 byte is read, together with kind 2, by
`PlayerTable::HasActiveType2` S 005bdd70 and `FindLocalPlayer` S 005bdda0 (which falls back to the table base),
and it changes only in `Player::Reset` S 005bea50 [known]. The overlay keeps no picture between frames: every
frame it reads the flags (`ConstructionMap::GetCellFlags` S 00675740) and places each icon at
`TerrainGrid::CellToWorldPos` S 00687790, so an emptied cell or a height change shows at once [known]. The cell left out is the cursor's: `Begin` is handed
`nGame::System + 0x10`, the game cursor, and `AddCellsInRect` skips the cell at its +0x14 / +0x18 [known]. The
hovered cell is not empty, though: `nGame::Cursor::UpdateCellMarker` S 007885e0 (from `Cursor::Update`
S 0078a2b0, from `nGame::System::Render` S 007835d0) draws that cell's icon every frame, info-map mode on or off,
by the same index rule but from the glowing rows of `ui_ingame3.dds`: `x = entry + 0.015625` (S 008352e0),
row = `int(x)`, u = `frac(x)`, v = 0.625 (S 008352d8) + row × 0.0859375 (S 00835328), i.e. the 88 × 88 cell at
pixel `(16 + 88 × col, 640 + 88 × row)`, 168 px above the overlay's row at 808. Its quad is 3.5 world units
(constants 0.5 S 007d877c, 3.5 S 007e6954), camera-facing about (0, 1, 0), and drawn as a UI sprite; nothing
is drawn when the cell's flags are 0 or a building is under the mouse [known]
([camera-input-cutscenes.md](camera-input-cutscenes.md) §3.10). The overlay's icon index is:

```
base  = 0 if flags & 0x04, else 1 if 0x02, else 2 if 0x01, else 3 if 0x08, else 4 if 0x10
index = base + 0     if 0x20 set and 0x40 clear
      = base + 5     if 0x40 set and 0x20 clear
      = base + 8     if both set
      = base + 11    if neither set
index = 16           if none of the five base flags is set (no modifier)
```

`index` selects one float of the 17-entry table `g_ConstructionMapIconTable` S 0088da78 (the icon's texture
coordinate) [known] S 006b36d0.

**Icon atlas** [known]: `CreateResources` S 006b3870 binds `[data]\map\textures\ui_ingame3.dds`. The quad's own UVs
start at u0 = 16/1024, v0 = 808/1024 and span 88/1024 on both axes (S 007cacc0, S 007cacf0, S 007cad10; 1024.0 =
S 00881e70). S 007cad30 fills the table with `step = 88/1024`: entry k is `k × step` for k = 0..10 and
`(k − 11) × step + 1` for k = 11..16. `infomap_shader.fx` splits an entry `w` again: `u += frac(w)`,
`v += (w − frac(w)) × 88/1024`. So the integer part is the row and the fraction the column offset: entries 0..10
are row 0, entries 11..16 row 1. The shipped atlas holds there, in index order [known: data]: row 0 large, medium,
small, mine, harbour with a flag ring (0..4, flag bit 0x20 only), then large, medium, small with crossed swords
(5..7, military bit 0x40 only), then the same three with swords and flag (8..10, both bits); row 1 the five plain
icons (11..15, neither bit) and a lone flag (16). The modifier ranges overlap: mine + military gives index 8 and
harbour + military index 9, both "swords and flag" icons of building sizes [known: arithmetic of the formula]. The
flags the construction map stores never produce these two, because 0x40 is set only together with 0x1
(`docs/sim/map-resources.md` §3.5) [inferred].

**Quads** [known] S 006b3870, `infomap_shader.fx`: four corners at ±size/2 along the view x axis and 0..size
along the view y axis, so the icon stands on the cell's world position and faces the camera; `iconOffset` is
added in view space (−1 on z = one unit toward the camera). Size and offset come from the `<Landscape>`
attributes `iconSize 3.0` and `iconOffset "0 0 -1.0"` [known, file]; without them the defaults are 1.5
(S 008814ec) and 0 (S 0088cf68). The quads are batched 50 at a time (`FlushQuads` S 006b3530) and tinted by the
renderer's overlay colour. At shader level 0 `FlushQuads` draws one quad at a time with a billboard matrix
through the technique `ffp`, whose stages select only the texture (colour and alpha), so that path shows the icons
untinted and without the overlay's fading alpha [known, `infomap_shader.fx`].

**Order and depth** [known] S 00688c40, S 006b36d0, S 006db220, S 006dad30, `infomap_shader.fx`: the visible block
list is collected nearest child first ([world-objects-rendering.md](world-objects-rendering.md) §3.14), and the
overlay walks it from its last entry to its first, so blocks are drawn roughly far to near: the list is front to
back only by quadtree level (`CullNode` S 006db220 visits the children of a node it recurses into in the order of
the table S 007fc1b8 picked by the nearest child, S 006dad30 — nearest 0: 0,1,2,3; 1: 1,0,3,2; 2: 2,0,3,1; 3: 3,1,2,0
— and a subtree wholly in view goes through `CollectVisible` S 006daff0 with the nearest-child bits it last stored),
not sorted by distance; inside a block cells go row by row in y, each row in x. Technique `Default`: depth test on (`ZFunc LessEqual`), no depth write, alpha blend. The
overlay is drawn after the whole map, water included, and before the particles (`RenderPostFxAndOverlay`
S 00680a00, §3.1), and after the post processor's combine, so depth of field never blurs it (with the post processor
on, the depth test no longer separates the icons from the scene: see the post processor below). The icons are
world-sized quads: they grow on screen as the camera comes closer, and nearer plants, rocks and figures cover
them through the depth test. `water_shader.fx` writes no depth, so water never hides an icon [known, files].

**When it is drawn** [known]: only while the tint alpha is > 0 (S 00688c40). The alpha is 0 from the
`CMapRenderer` constructor S 006890f0 and is changed only by `nMenu::Game::StartOverlayColorFade` S 005eabd0.
Its callers are `btInfoMap1` (`OnButtonClick` S 005eb850) and the cinematic screen (`nMenu::Cinematic::Update`
S 005fb3e0, and `OnHide` S 005faee0, which restores the fade state the cinematic saved). The fade runs linearly
over 0.2 s from the last drawn colour to `(1, 1, 1, fadeIn ? 1 : 0)`; `nMenu::Game::Update` S 005efea0 does not
advance it while paused. So the icons belong to info-map mode; placing a building does not show them.

`RenderBuildPlacementOverlay` S 00688c40 draws the construction-place icons of the info map. Its gate, the
`CMapRenderer` tint alpha (+0x40), is raised only by `nMenu::Game::StartOverlayColorFade` S 005eabd0 (callers:
`OnButtonClick` S 005eb850 for `btInfoMap1`, `nMenu::Cinematic::Update` S 005fb3e0, `nMenu::Cinematic::OnHide`
S 005faee0) through scene slot 15 (`SceneCb_SetRendererRect` S 0067f3e0); `BeginBuildPlacement` S 006176d0 and
`SelectCell` S 00617770 never touch it [PROVEN].

---

## 4. Update order

### 4.1 On load / match start

`Scene::Init` S 006824c0 [known], in this order:

1. open `[data]\settings\graphics.xml`; when it cannot be opened the whole function is skipped;
2. `ApplySceneSettings`, then the scene's own keys of the file (`LoadSettingsFromXml`);
3. once per process (latch S 0088ca6a): map scaling (`<Map>`), the map render settings (`<Landscape>`,
   `<Water>`, `<Street>`: S 00688170) and `<Enviroment>` (S 00684be0);
4. terrain grid; shadow manager (only with `Scene +0x78` > 1); screen pick helper; environment manager, which
   loads the map's environment data; effect script manager;
5. `CMapRenderer` S 006890f0, which creates in this order: house decals, landscape, build-placement overlay,
   streets, water, buildings, map objects, territory borders, the editor's terrain generator, 4 selection
   markers; then its detail factor from the scene settings;
6. item manager and `[data]\settings\items.xml` (skipped when the file is missing);
7. character manager: `[data]\character\settler_config.xml`, then `settler_animations.xml`;
8. `[data]\settings\buildings.xml`; animal manager and `animals.xml`; ship manager and `ships.xml`; swarm
   manager (its constructor reads `flocks.xml`, S 0069ab00, S 0069a9c0); projectile table;
9. with `Scene +0x78` > 1 the shadow casters are registered: map renderer, characters, items, ships, animals,
   swarms;
10. picking access (`CGraphicAccess::Init`); the scene becomes the sound manager's listener;
11. `gameTime = nextTickTime`, `realTime = 0`.

`terrain_static_data.xml` and `map_objects.xml` are read by S 00783790 [known], called from
`nGame::System::BuildScene` S 007842e0.

`CMapRenderer::InitForMap` S 006883e0 [known] does nothing until the map interface reports a width and a height
other than 0. Then: terrain mesh rebuild and draw batch, destruction and creation of the terrain blocks, water
(half-texel offsets of normal map 0, reflection quality 0, map border segments S 006a88f0; the water preset
index from the map info `+0x1cc`), size of the "FogOfWar" texture (§3.7). It has two entries [known]:

- `CMapRenderer::SetActive(true)` S 00688cd0, when the renderer is not yet initialised for the map.
  `SetActive(flag)` is called by `Scene::OnWorldLoadStateChanged(flag)` S 0067eed0 and
  `Scene::OnLogicInitStateChanged(flag)` S 0067ef30; `false` switches the terrain blocks off, releases the water
  target and clears the initialised flag and the viewing player;
- `CMapRenderer::ReinitForMap` S 00688d20, from the map callback S 0067efe0, which first re-initialises the
  terrain grid.

A world load brackets the file load with `OnWorldLoadStateChanged(false)` and `(true)` S 005ac770; the creation
callbacks of the loaded objects (§3.2) fall between the two [inferred]. On `true` the scene also forwards the
flag to the character manager and the item manager (carrier attachments) and rebuilds the swarm spawn zones
from the map's grid states [known] S 0067eed0.

### 4.2 Per logic tick

`Scene::SyncLogicTick` S 00680550 [known for the order; inferred that the caller runs it once after each
simulation tick: it is a scene interface slot without a direct caller]:

1. `gameTime = nextTickTime`;
2. `CMapRenderer::SyncLogicTick` S 006882c0: building instances (`UpdateInstances` S 006a1f20: an instance with
   demolish progress `+0xfc` < 0 (not demolishing) gets its per-tick virtual update `+0x2c`, one with progress
   >= 1.0 is removed, one with 0 <= progress < 1.0 gets neither [known, disassembly]), then map objects
   (`MapObjLayer::Update`);
3. characters (`UpdateLogicAll` S 006929e0 → `CCharacter::UpdateLogic` per live character: type logic,
   animation slot, movement, attached effects; then the street-collision pass is marked dirty);
4. item attachments of carriers; animals; ships;
5. swarms: time-out and removal (`SwarmMgr +0x3c`, §6.5);
6. the particle manager's clock (`+0x94`) = `gameTime`;
7. `ApplySceneSettings` S 0067f500.

### 4.3 Per frame

`Scene::Update` S 006805e0 [known for the order]:

1. first frame only: evict managed resources, latch `gameTime`;
2. `UpdateDetailFlagsAndTime` S 0067f6b0: pass masks and layer flags from the detail setting and the debug
   CVars, shadow level, time. Normal mode: `realTime` = the simulation's accumulated time (`+0x7c`), frame
   delta = `+0x74`. Real-time mode (the function's flag): frame delta from a private high-resolution timer,
   `realTime += delta`, and `gameTime` and the particle clock are set to the same sum;
3. device transforms; copy the device frustum into the scene (skipped while the freeze-culling debug flag is
   set); pass the freeze-shadow debug flag to the shadow manager;
4. `CMapRenderer::Update` S 006888f0: camera position; once, on the first frame on which
   `NLogic::Edit::GetBatchEditing()` (`docs/sim/logic-core.md` §3.1) is false, the terrain grid is recomputed and
   the terrain mesh rebuilt; water animation; terrain culling and LOD (`UpdateVisibleCells`); resource hint
   candidates (only with a viewing player) and one hint spawn; buildings; map object animation and level
   fades. Then the visible block rectangle is passed to the character manager;
5. with a selection context whose player has its byte `+0x50` set: `CCharacterMgr::Update` (interpolation,
   culling, LOD) with the exploration grid and that player, then the ships' graphic entries with the same
   pair, then, with a post processor, the post processor's fallback focus point = the world position of the
   vertex held at `+0x2c`, `+0x30` of the context's companion object, when that vertex is inside the map.
   Without such a context: `CCharacterMgr::Update` with neither grid nor player, and the ship and focus steps
   are skipped. The player argument is null while `GetBatchEditing()` is true;
6. items; animals (exploration grid always, player as in 5); ship visibility; swarms (with the interpolation
   factor `1 - (gameTime - realTime) * invTick`); projectiles; particle culling and sorting;
7. environment at the camera's ground focus point; the shadow-suppress flag `+0x74` with layer flag 0x10000
   (§2.2); exploration overlay switch when the CVar changed (§3.7).

Then `Scene::Render` and `Scene::RenderPostFxAndOverlay` (§3.1), then the HUD (outside this document).

Particles and the post processor [known] S 006836b0, S 00680a00, S 0067eb20: with a post processor
`Scene::Render` runs `RenderPasses(passMask)` between `BeginScene` and `EndScene`, and `passMask` holds bit
0x100 unless the debug CVar of that pass hides it; `RenderPostFxAndOverlay` then runs `RenderPasses(0x100)`
again after the combine. Pass 0x100 calls `ParticleManager::RenderAll`, which has no once-per-frame guard, so
on that path the particles are drawn twice per frame: once into the processed image and once on top of it.
Without a post processor the first call masks the bit out (`passMask & ~0x100`) and they are drawn once.

---

## 5. Inputs and outputs

**Consumes**

| From | What |
|---|---|
| `NMap` | height grid, pattern grid, grid states (water, border), territory owner, exploration bytes, ground resources; change rectangles through `NMap::CallbackReceiver` |
| `NLogic::CallbackManager` | creation, removal and state events (§3.2) |
| logic objects (read by pointer every tick or frame) | building construction and upgrade progress, hit point ratio, productivity, military level; settler state, path progress, carried good, type; ship cells and progress; resource growth; projectile timing |
| `NLogic::System` | `nextTickTime` (+0x78), accumulated time (+0x7c), frame delta (+0x74), tick length |
| players | player colour, local player and its "active" flag |
| properties | tribe resource names, good names, building and settler type names (the keys into the XML files) |
| settings | scene settings (detail, shadows, reflections, post FX, quality) |

**Produces**

- the frame; picking for the cursor and commands: `CGraphicAccess::PickAtScreenPos` S 006a9830 (terrain cell
  and hexagon under a back-buffer pixel, through `ScreenPickHelper::PickCell` S 0068c8d0 and `PickHex`
  S 0068cc10) [known]; `CLandscape::PickRayCell` S 0068a0d0 / `PickRayHex` S 0068a080,
  `CCharacterMgr::PickCharacterByRay` S 00692fc0, `ShipMgr::PickShip` S 00697db0 ([known]: nearest bounding-sphere entry with a mesh hit, [ingame-ui.md](ingame-ui.md) §3.4) [inferred, mapped names for the others];
- the overview texture `RenderOverviewTexture` S 00680d90 (an orthographic top-down view of the box between the corner
  cells, near 0.1, far 200, eye 50 above the box; `CMapRenderer::RenderWaterPass` S 00688f70: the terrain patterns with
  every cell revealed, the map objects of detail level 0, the water without mirror; device fog off) [known]
  ([hud-panels.md](hud-panels.md) §3.7) and the preview textures `RenderPreviewTexture`
  S 00681300, whose callers are the object and ship previews of the pick helper S 0068cae0, S 0068cb60
  [known for the callers];
- the 3D sound listener transform S 00681c10 and positional sound emitters of characters and buildings
  [inferred];
- sound and particle events of animations [inferred].

**Writes into simulation objects**: none found. `CCharacter::SetPath` S 006905e0 sets byte `+0x18` of the
character's own per-type logic object (`CCharacter +0x88`: `CharacterWorker`, `CharacterConstructor`,
`CharacterCarrier`, `CharacterSoldier` or `CharacterSpecialist`, created by `CCharacter::Init` S 00690760), a
scene object that only points to the settler (`+0x34`) [known]. The door trigger starts the *render* building's
animation only [inferred]. See §8.

---

## 6. Data-driven parameters

All paths are under the game's `data` directory; `[data]` in a value is that directory. Files are in the
encrypted container of `docs/asset-formats.md`. Values quoted are examples from the install [known, file].

### 6.1 `game/settings/graphics.xml`

| Element | Keys (example) |
|---|---|
| `Settings/Shadows` | `scale="1.0"`, `bias="-0.00325"` |
| `Settings/PostEffects` | `minLuminance="0.98"`, `bloomScale="0.25"`, `focalScale="25.0"`, `focusSpeed="3.0"` |
| `Settings/Animations` | `globalSpeed="1.8"` |
| `Map` | `scaling="1.5 0.001 1.2990375"` |
| `Camera` | `nearPlane="0.1"`, `farPlane="500.0"`, `minElevation="-85"`, `maxElevation="85"`, `moveSpeed="20.0"`, `zoomSpeed="150.0"`, `turnSpeed="0.5"`, `tiltSpeed="0.25"`, `minZoomLevel="1.0"`, `maxZoomLevel="1000.0"`, `doTerrainCollision="false"`, `targetRelativeHeight="0.3"`, `cameraRelativeHeight="0.6"` |
| `Landscape` | `lodDistance="50.0"`, `iconSize="3.0"`, `iconOffset="0 0 -1.0"`; `Terrain maxIndices="20000"`; `ResourceFX minTime="8" maxTime="25"` |
| `Landscape/Transitions/Transition` | 8 mask textures in index order: `transition00`, `01`, `02`, `C`, `B`, `A`, `03`, `04` (`[data]\map\transitions\*.dds`) |
| `Water` | `shader="water_shader.fx"`, `color`, `phaseSpeed0="0.015 0.015"`, `phaseSpeed1="-0.017 -0.03"`, `tex0Scale=".1 .1"`, `tex1Scale=".1 .1"`, `tex0Rot="206"`, `tex1Rot="145"`, `OpacityFFP`, `TextureScaleFFP`, `TextureAnimSpeedFFP`, `TextureMoveSpeedFFP`. The parser S 006a93c0 names every one of these keys except `color` [known], so `color` is not read by it. `tex0Rot`, `tex1Rot` are degrees (`* pi / 180`, double S 007db6a0): `WorldRenderer::UpdateWaterAnimation` S 006a65a0 writes, every frame, the normal-map texture matrices 0 and 1 (`+0x160`, `+0x1a0`) with the upper 2 x 2 `(cos, sin; -sin, cos)` and the translation row `animTime * phaseSpeed0` / `phaseSpeed1` (`animTime` = the sum of the frame deltas), which `Water_VS_2_0` applies to `position.xz * (0.19, 0.17) * 0.3` and `position.zx * (0.23, 0.19) * 0.3` as row vectors [known]. `tex0Scale`, `tex1Scale` scale the world x, z into the water vertices' own TEXCOORD0 and TEXCOORD1 (`EmitWaterQuad` S 006a6a5a); only the fixed-function technique reads those, `Water_VS_2_0` derives its coordinates from the position [known, file]. `OpacityFFP` becomes the alpha of the water vertex colour (`+0x4a8`) [known] |
| `Water/WaterProperty` | 4 presets `Default`, `Highland`, `Swamp`, `Braindead`: `waterColor`, `waveColor`, `opacity` (2), `reflectionFactor`, `reflectionNoise` (2), `normalMap0`, `normalMap1`, `shallowColor`, `deepColor` |
| `Street` | `shader="street_shader.fx"`, `numSegments="8"`, `width="1.0"`, `texStretch="0.25"`, `crossingRadius="2.25"`, `buoyDistance="1.7"`, texture and normal pairs 0 and 1, crossing pairs, `buoyTexture`, `routeTexture`, `routeNumSegments="3"`, `routeWidth="2.5"`, `routeTexStretch="0.1"`, `routeTexSpeed="10.0"`, `routeTexCount="16"`, `redStreetColor="1.0 0.0 0.0 0.9"`, `alphaStreetColor="1.0 1.0 1.0 0.6"` |
| `Enviroment` | `timescale="0.033"`, `localtime="12"`, `animated="true"`; `Cubemap`, `Sun size="30.0"`, `Moon size="9"`, `Skydome name texture rotation` (5: Clouds, Stars, Egypt, Bavaria, Scot) |
| `GUI/Border` | frame texture and 8 piece rectangles |

### 6.2 `game/settings/terrain_static_data.xml`

`<GroundCover><Cover name="GrassBlades" opacity="[data]\map\textures\grass_opacity.dds" density="0.3"
height="0.3" bend="0.1" sliceCount="20"/>`; `<Patterns>` with 114 `<Pattern>` entries; attributes `name`,
`texScale`, `nrmScale`, `type` (on all 114), `blocking` (113), `texture`, `normal` (88 each), `transition` (77),
`specularIntensity`, `specularPower`, `parallaxHeight` (34 each), `alias` (26), `groundCover` (12, always
`GrassBlades`). The order is the blend rank; it starts `z_border_00`, `z_water_00`, `s_ice_00..03`,
`z_swamp_00..02`, `h_swamp_00..02`, ... and ends `z_snow_00..02`, `s_rock_03`, `s_rock_00..02`. Name prefixes
group the landscape sets: `z_` (44), `h_` (23), `m_` (19), `s_` (16), `l_` (12). Type usage: 0 = 67 patterns
(the default grounds, including `z_swamp_02` and `h_swamp_02`); 1 = `z_water_00` and the 11 `*_seaground_*`;
2 = `z_swamp_00`, `z_swamp_01`, `h_swamp_00`, `h_swamp_01`; 3 = 23 patterns (rocks, the three snows, some
grounds); 4 = `l_ground_01`, `l_ground_03`, `l_ground_05`; 5 = `l_rock_03`; 6 = `s_ice_00..03`. 26 patterns are
aliases (for example `z_sand_04` → `z_sand_02`, `z_seaground_04` → `z_rock_00`); exactly these 26 have no
`texture` and no `normal` of their own.

Keys named by the render parser `TerrainPatterns_RegisterFromXml` S 006bade0 [known]: `texture`, `normal`,
`texScale`, `nrmScale`, `transition`, `type`, `alias`, `groundCover`, `specularIntensity`, `specularPower`,
`parallaxHeight`, and `diffuse`, `ambient`, `specular`, which no pattern of the install carries. It does not
name `blocking`: the simulation reads that and its own flags from the pattern properties
(`docs/sim/map-resources.md` §2.5).

### 6.3 Shaders `game/gfx/fx_20/*.fx`

43 plain HLSL effect files (Direct3D 9; `vs_2_0` / `ps_2_0`, and `vs_1_1` in 28 technique passes) with
`shared.inc`. They are the authoritative source
for every pixel formula quoted in §3 and should be ported, not guessed: `terrain_shader`, `water_shader`,
`house_shader`, `house_decal`, `house_flag`, `house_soldierflag`, `skin_color_mesh`, `donkey`, `animals`,
`ships`, `item_shader`, `mesh_shader`, `doodads_shader`, `tree_shader` (+ `2`, `_winter`, `_willow`),
`stone_shader`, `rock_shader` (+ `2`), `ice_shader`, `weed_shader`, `waterplants_shader`, `waterlily_shader`,
`duck_shader`, `signs_shader`, `flag_shader`, `harborflag_shader`, `gate_shader`, `border_shader`,
`street_shader`, `decal_shader`, `infomap_shader`, `groundcover`, `particle_shader`, `rain_shader`,
`enviroment_shader`, `shadow`, `postprocess`, `line_shader`, `ui_shader`, `ui_graphshader`.

Shared constants by semantic [known, `shared.inc`]: `VIEW`, `PROJECTION`, `VIEWPROJECTION`, `ALIGNVIEW`,
`INSTANCEMATRICES` (50), `INSTANCEVECTOR0..3` (100 each), `TIMER`, `TEXTURE_ATTRIBUTES` (8),
`TEXTURE_TRANSFORM` (8), `CAMERA_POSITION`, `FOG_SETTINGS`, `MAIN_LIGHT`, `LIGHT_COLOR`, `WORLD`, `AMBIENT`,
`SHADOW_INTENSITY`, `SHADOW_SCALE`, `CAMERA_FOCUS`, `MATERIAL`. Sampler defaults: 0..3 linear and wrapped,
4 and 5 point and clamped, 6 point and wrapped, 7 point and clamped.

### 6.4 `game/settings/map_objects.xml`

221 `<LandscapeElement>` under `<LandscapeElements>`; `<SingleLandscapeObjects>` is empty in the install.
Attributes: `name`, `mesh`, `shader`, `rot` (min max), `type` (`tree` 28, `stone` 12, `flag` 2, `harbor`,
`wheatField`, `gate`, `routeBuoy` 1 each; absent on 175), `scaleX`, `scaleY`, `scaleZ` (min max),
`numInstances`, `shadowCast`, `shadowReceive`, `forceShadowPass`, `priority`, `blendMode`, `transparent`,
`offset`, `alignOnWater`, `meshType`.
Example: `z_flag_00`: `mesh="[data]\map\objects\flag.KEX"`, `shader="flag_shader.fx"`, `rot="90 90"`,
`type="flag"`, `forceShadowPass="ShadowPassFlag"` (no other attribute).

Parser `MapObjDefs_ParseLandscapeElement` S 0068f200 [known]: an element without `mesh` or without `shader`
is not stored. Defaults for absent attributes: `rot` 0 0, the three scales 1 1, `offset` 0 0, `numInstances` 50,
`shadowCast` and `shadowReceive` true, `blendMode` 0, `alignOnWater` and `transparent` false. It also reads
`vbSize` (default 15000) and `ibSize` (default 30000), which no element of the install sets, and `meshType`
with the values `extended` and `none`.

Names used by code [known]: `z_flag_00` and `z_harbor_flag_00` (a flag; the second when the flag has a harbor
reference) S 00682ca0, `z_harbor_00` S 00682ec0, `RouteBuoy` (first cell of a sea route, and the last cell
when both end references of the route are valid) S 00683040.

### 6.5 Buildings, items, characters, animals, ships, effects

| File | Structure (example values) |
|---|---|
| `settings/buildings.xml` | `<Buildings lodBias="-70.0" lodScale="1.2" colorMap="[data]\buildings\colors.tga" numVariations="8">`; 112 `<Building name mesh frame enterDistance lodBias lodScale>` (`frame` on 100; `enterDistance`, `lodBias`, `lodScale` on one each) with `<DoorOpen file>` and `<DoorClose file>` (84 each), `<Working file>` (53; children `<Sound start name duration>`, `<Particle start duration name slot offset>`), `<Production mesh model texture scale numAnims anim0.. numModels boneLink0..>` (3), `<Sacrifice name>` with `<PFX name link>` children (1). `BuildingDesc::LoadFromXml` S 006d3880 also names `leaveDistance`, `heading`, `location0` and `location%d`, which the install does not use [known] |
| `buildings/` (models, textures) | per type: `<mesh>.KEX` (meshes `House` and `GROUND`, skeleton with `root`, door / wheel bones, `MILFLAG`, `FIRE_%02d`; texture coordinate sets: diffuse atlas, light map unwrap, colour map texel; 95 of 106 have all three, 8 the first two, 3 one), optional `<mesh base>LOD0.KEX`, `<frame>.KEX` (meshes `0 .. N-1`, one per stage), the clips of `DoorOpen` / `DoorClose` / `Working` mostly in a folder named after the mesh; textures `<name>.dds` (diffuse, DXT1, 1-bit alpha for the alpha test) and `<name>_L.dds` (grey light map, DXT1). Shared: `PB_R_ConstructionSite01.dds` (all frames), `house_decal.dds` (1024², DXT3, all ground decals), `colors.tga` (64 x 256 RGB, 8 variation blocks x 32 bands), `MilitaryFlag1..3.dds` (512², DXT3), `MilitaryFlagInactive.KEX`, `MilitaryFlagSword00..10.KEX`, `MilitaryFlagBow00..10.KEX` (§3.9) [known, data] |
| `settings/items.xml` | root `<Items>`: `<ItemDefinitions><Item name mesh references>` (55; `references` on one), `<AnimatedItems>`, `<DonkeyItems>`, `<StackLayouts count="2" distance="0.5"><Layout offset0..5 good0..>` (2 layouts) |
| `character/settler_config.xml` | `<Characters scale="1.2" evadeRadiusScale evadeStart boatOffset goodOffset goodRotation lod0Range="30.0" lod1Range="40.0" lod2Range="60.0">`, 98 `<Character name mesh mesh1 mesh2 mesh3 color slotMap>`, `<Models><Model file>` (one model, `settler_model.KEX`), `<Donkey scale mesh model link="SLOT_Goods">` with 47 `<Animation name filename>` |
| `character/settler_animations.xml` | `<Animations>` with 168 `<Animation name filename tribes>` (`tribes` on 8) and `<Sound start name>` (78) / `<Particle start name>` (1) children; `<RandomAnimations>` with one `<Random minDelay="5.0" maxDelay="8">` holding 11 `<Animation src probability>` |
| `character/color_slots.xml` | `<SlotEnumeration><Slot name>` (15), `<ColorRamps><ColorRamp slot solid|texture rows>` (41), `<ColorMaps><ColorMap name><Material index slot>` (63 maps) |
| `settings/animals.xml` | one element per species (12: `Deer`, `Bear`, `Rabbit`, `Boar`, `Camel`, `Elk`, `Goat`, `HighlandCattle`, `MountainHare`, `Ox`, `Polarbear`, `Sheep`): `model`, `mesh`, `scale`, `<Animations><Animation name filename>` (48 in all) |
| `settings/ships.xml` | `<Freight mesh>`, `<Expedition mesh>`, `<Soldiers mesh>`, 3 `<Ship tribe scale frame mesh model idle move sink>` |
| `settings/projectiles.xml` | 4 `<Projectile name mesh rotation flightPFX impactPFX impactSound>` |
| `settings/effectMovies.xml` | 7 `<EffectMovie name>` with `<FX start particles link duration sound>` (13 in all) |
| `settings/flocks.xml` | `<Flocks maxFlocks="10" minSpawn="10.0" maxSpawn="30.0" swarmTimeout="10.0">`; `<Bird>` and `<Fish>` (`minCount maxCount startMin startMax zone hasPOI nextMin nextMax minPOI maxPOI poiSpeed`), `<Bug>` (`numActors startMin startMax zone`), each with `<Evade minRange maxRange>`, `<MatchSpeed weight>`, `<Pack distance returnStr>`; `zone` = `flight`, `water`, `ground`. `SwarmMgr::LoadSettings` S 0069a9c0 reads the root attributes `maxSwarms`, `minSpawn`, `maxSpawn`, `swarmTimeout` [known]: the install's `maxFlocks` is not the key it asks for, so the swarm limit stays at the constructor default 5 (S 0069ab00; the other constructor defaults 5.0, 30.0 and 15.0 are replaced by the file) |
| `settings/decals.xml` | 3 `<Texture name>` |
| `scripts/effects/*.pfx` | 64 particle effect definitions; plain (not in the encrypted container), binary; layout in `particles.md` §3.1 |
| `settings/engine.xml` | one `<Engine>` element: `pureDevice`, `hardwareCursor`, `specialDepthMap`, `lowresDepthMap`, `multiSample`, `vsync`, `hwCursor` (cursor texture), `hotspot` |

Meshes, skeleton models and animations are `.KEX` scenes; textures are `.dds` / `.tga`. Code that names a
`.GR2` or `.gr2` file loads the `.KEX` of the same name [known] S 004de400, S 006d4060.

### 6.6 `game/settings/daytimes.xml` and `local_enviroment.xml`

`daytimes.xml`: 9 `<Daytime hour background skydome lightelevation lightheading lightambient lightcolor
shadowIntensity fog>` for the hours 0, 4, 6, 8, 12, 16, 18, 20, 22. In the install all nine carry the same
values (`background="0.8 0.9 1.0"`, `skydome="0"`, `lightelevation="50"`, `lightheading="55"`,
`lightambient="0.6 0.5 0.6"`, `lightcolor="0.9375 0.898 0.781"`, `shadowIntensity=".9"`, `fog="100.0 200.0"`)
except the fog of hour 12, `"10240.0 10240.0"`.

`CEnviromentMgr::LoadDaytimes` S 00684130 [known] fills one 0x4c-byte record per element:

| Offset | Type | From |
|---|---|---|
| +0x00 | i32 | `hour` |
| +0x04 | float[4] | `background` (3 values), 4th = 1.0 |
| +0x14 | i32 | `skydome` |
| +0x18 | i32 | `lightelevation` |
| +0x1c | i32 | the attribute `lighteeading` (sic) |
| +0x20 | float[4] | `lightambient` (3 values), 4th = 1.0 |
| +0x30 | float[4] | `lightcolor` (3 values), 4th = 1.0 |
| +0x40 | float | `shadowIntensity` |
| +0x44 | float[2] | `fog` (start, end) |

The code asks for `lighteeading`, the file spells `lightheading`: the attribute is not found, the integer
reader S 006e7b20 leaves its output untouched on a miss, and the output variable still holds the elevation just
read. So the heading of every day-time key equals its elevation (50 in the install) and the file's
`lightheading` is never used [known] S 00684130: both reads use the same output variable, and the key's
heading is stored from it directly after the failed read. Read in a running match: all nine keys have heading =
elevation = 50, and the hour stayed 12.0 over 4,367 ticks; `CEnviromentMgr::Update` S 00683d50 runs once per
frame and `GetDaytime` S 00684a20 is not called [live, 2026-10-12]; the time of day does not change in play
(maintainer).

When `[data]\settings\daytimes.bin` exists it is loaded instead of the XML (u32 count, then the raw 0x4c-byte
records, S 00684510); otherwise the XML is parsed and the same layout is written to that path (S 00684690)
[known]. The install ships no `daytimes.bin`. A remake reads the XML and needs no cache.

`local_enviroment.xml` [known] S 006aec60, S 006ae0b0: one `<Enviroment skydomeindex lightelevation lightheading
background lightambient lightcolor shadowIntensity fog>` (here `lightheading` is spelled as the code asks) and
`<EnvSphere center innerRadius outerRadius background lightambient lightcolor shadowIntensity fog>` children.
The install's four sphere elements are named `XEnvSphere`, which the reader does not look for, so the default
data has no spheres.

---

## 7. Save and load

Nothing of the scene is written to a save game [inferred]: no `Store` of an `S2CG` class is reached from the save
path (`docs/sim/save-format.md` §7 lists camera, selection and windows as not saved). On load:

- the scene is constructed from scratch (`BuildScene`) and re-populated by the creation callbacks of the loaded
  logic objects (§3.2, §4.1);
- the post-load step `GameFile_FinishLoad` S 005aa1b0 [known] runs, in this order: scene slot +0x1c, which
  copies the loaded `nextTickTime` into `gameTime` S 0067eb10 (skipped while the menu system suppresses the
  UI); the logic's `PostLoad`; the environment manager's load of the map's environment data (§3.13); and, when
  its argument asks to resume, `OnWorldLoadStateChanged(true)`, which runs the map initialisation of §4.1;
- the sacrifice post-load (`NSacrifice::System::PostLoad` S 0065f540) raises "sacrifice started" (+0xa0) for every
  running sacrifice and "research started" (+0xa8) for every running research [known]; `StartEffect` S 006ace00
  back-dates the movie by the ticks already run, so it resumes at the point it had reached (the research movie by
  its absolute start tick, §3.2) [known].

Rebuilt and therefore not reproduced exactly after a load [inferred]: random yaw and scale of map objects,
palette choice of settlers created without a palette, idle variations, swarm state, particle state,
interpolation history, tree sway, day time.

The scene *settings* (`S2CG::Settings::Load` S 006960a0 / `Store` S 00696270: quality preset, overall quality,
display mode flag, display width and height, the quality sliders and switches `+0x20..+0x48`) are written by
`UserProfile::StoreSettings` S 00579640 into the user settings, not into a match [known for the callers].

---

## 8. Determinism notes

The scene is presentation only:

- it is driven by callbacks and by reads of logic objects; the handlers of §3.2 create and remove render objects
  and call no logic mutator [inferred from the handler comments; the handler bodies were not all re-read];
- its time base is the simulation's tick time plus an interpolation factor; nothing in §3 feeds a value back into
  a tick;
- the shared animation pool is advanced by frame time [inferred].

**Random numbers.** The simulation's generator is the global at S 00889b08 (`LogicRandom_Next` S 005389b0,
`docs/sim/logic-core.md`). None of the scene's random draws read for this document uses it [known]; each uses
a generator of its own:

| Draw | Generator | Seed | Evidence |
|---|---|---|---|
| map object yaw and per-axis scale (§3.11) | static S 0088d4ec | 0x5432ace0 (initialiser S 007cab10) | S 0068dd40, S 0068f120 |
| resource hint cell, pick and next check time (§3.12) | static S 0088d47c | 0x400 (initialiser S 007caaf0) | S 0068b220, S 0068ac10 |
| palette of a settler created without one (§3.10) | static S 0088d7c8, built on first use | 0x5432ace0 | S 00695490 |
| fallback fire points of a building without a `FIRE_03` node (§3.9) | static S 0088da38, built on first use | 0x5432ace0 | S 006ac510 |
| animal idle choice (0 or 1) | static S 0088decc, built on first use | 0x5432ace0 | S 006ce2c0 |
| swarm spawn zone, spawn box, flock sizes and actor scatter | member of `SwarmMgr` (`+0x8`); the swarms draw through a generator pointer [inferred: the same object] | the manager's own address (`PUSH ESI` with `ESI = this` before the generator constructor, S 0069ab2b): differs from run to run | S 0069a320, S 00699ed0, S 006cd6b0, S 006cd950, S 007702c0, S 00770640 |

Because the fixed-seed generators are advanced in creation order, two machines in the same match can show
different palettes, yaws and fire points; nothing of that reaches a tick [inferred].

**Writes.** `CCharacter::SetPath` S 006905e0 writes byte `+0x18` of the character's per-type logic object,
which is a scene object (§5), not the settler [known]. No other write from the scene into a simulation object
was found in the functions read; the handlers of §3.2 were not all re-read (first bullet).

**Exploration** gates hunters, foresters and geologists in the simulation (`map-resources.md` §3.7); the
*display* of exploration does not.

A remake can therefore run the simulation headless and attach any renderer.

---

## 9. Notes for a Godot reimplementation

**Converter output (once, into the cache)**

| Source | Output |
|---|---|
| `.KEX` meshes, models, animations | glTF 2.0 (`.glb`): meshes with LODs as separate meshes, the shared settler skeleton with one animation per KEX file, named nodes kept (`House`, `FIRE_xx`, `MILFLAG`, `SLOT_Goods`, `Dummy*`, bone links) |
| `.dds`, `.tga` | PNG or KTX2; keep alpha; index maps of characters must stay unfiltered and uncompressed |
| the XML files of §6 | JSON resources with the same keys; keep the order of `<Pattern>` (rank) and `<Transition>` (index) |
| `.fx` | hand-ported Godot shaders, one per effect family; the formulas of §3 are the reference |
| `.pfx` | particle definitions (`particles.md` §3.1, §9) |
| map `.bin` sidecar | environment resource (skydome index, light angles, default and sphere `EnvData`) |

**Terrain.** Build one `ArrayMesh` per 4 x 4 cell block from the height grid with the triangle split of §3.3
(row parity matters for exact silhouettes) and 4 subdivisions per cell edge. Reproduce the blending exactly: per
block the sorted pattern list, solid and blend patches as in §3.3, mask UVs from the blend vertex, two mask halves.
A practical equivalent that gives the same picture in one draw: per triangle vertex attributes (lowest pattern
layer, up to two blended layers with their mask UVs and mask indices) and texture arrays for diffuse, normal and
masks; the pixel rule `mix(lower, light * (tex + mask.r*2 - 1), mask.a)` applied in rank order equals the
multi-pass result. Pattern `type` selects a shader branch (§3.4). Height edits and pattern edits arrive as
rectangles: rebuild the touched blocks plus a one-block margin.

**Water.** One plane at the water height (or per-block quads), the two scrolling normal maps, planar reflection
(Godot: a mirrored `SubViewport` camera with a clip plane, or screen-space reflection as a cheaper stand-in),
shore fade from a height texture (the overlay's blue channel), under-water tint as vertex colour or computed in
the terrain shader from depth, caustics as an additive pass.

**Exploration.** One `(2W+1) x H` (or simply `W x H` with the half-cell shift in the shader) RG8 texture: explored
flag and normalised inverse height; sample it in every world shader through a global shader uniform and apply
`CalcFOW`. Hide objects on unexplored cells: per terrain block for map objects, goods piles, flags and
buildings (the buildings also by their anchor cell), per cell for characters, animals and ships (§3.7).

**Instancing.** `MultiMeshInstance3D` per landscape element; per-instance colour for flags; growth and felling
as per-instance transforms (§3.11); wind and flag waving in the vertex shader.

**Buildings.** Stage subsets of the frame mesh by the stage formula; the rising mesh with a clip plane
(`discard` above `planeY` in the shader); upgrades with two models and opposite planes; decal under the house
(`Decal` node or a baked ground mesh).

**Settlers.** One skeleton, shared animation library; a custom shader for the index-map palette (§3.10) with a
palette texture array or atlas; animation slot and override lookup exactly as §3.10; interpolation factor from
the tick clock. Sharing one evaluated pose per animation is an optimisation, not a look requirement, but it is
why all walkers of the original step in phase.

**Light.** `DirectionalLight3D` from heading and elevation, ambient colour, linear depth fog from `fog` start and
end, shadow strength from `shadowIntensity` and the elevation rule; blend `EnvData` by the sphere weights.

**Built in the original but without effect.** None of these changes simulation state; a remake that reproduces
the original's picture leaves them out, a remake that refines it may add them: the environment particle layer
(never created, §3.13), ground cover (the render call passes a constant 0, §3.6), the settings switch `Coverage`
(saved and loaded, read by no render function, §3.1), and the sun and moon quads of the sky (built, never drawn;
`docs/sim/world-objects-rendering.md` §3.10).

**Must be exact** for the look: pattern rank order, the triangle split, mask selection and UVs, the transition
pixel rule, the stage and clip-plane formulas, animation slot rules, the palette lookup, the border post rule.
**Free**: culling, LOD thresholds, batching limits, buffer sizes, the fixed-function paths, the shadow fitting.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered: the `.pfx` layout and the emitter model are in [`particles.md`](particles.md) | - |
| 2 | Answered (§3.9 "Assets per type", "Frame stages"): one frame subset per KEX mesh in the order of the names `0 .. N-1`, stage `k` draws the first `k`; LOD meshes `House` (else the first mesh); UV sets 1 / 2 / 3 = diffuse / light map (`Self-Illumination`) / colour map texel | - |
| 3 | Answered (§3.9 "The progress values"): `1 - remainingA` of the construction (or of the upgrade's construction), sampled every logic tick and interpolated over one tick (`rate = 1 / gameSpeed`) | - |
| 4 | Answered (§3.9 "Military flags"): `Military +0x68 soldierKind` (non-zero = bow set) | - |
| 5 | Answered (§3.9 "Colour variation"): `instanceId mod numVariations`, the 1-based slot in the renderer's instance pool; the S 006ac810 "variant" is the LOD bone binding | - |
| 6 | Answered: [`animation-models.md`](animation-models.md) §3.15 (index map R = 1-based Material index, decremented at load S 00692170; palette row = index - 1, ramp copied reversed; one Park-Miller draw per slot, seed 0x5432ace0; 1024² atlas of 16 x 16 blocks; full pixel formula) | - |
| 7 | Answered: [`animation-models.md`](animation-models.md) §2.13, §3.9: table C = buildings (PropertiesDb +0x00), keyed by the worker's workplace building id; loop mode = KAnimationControl maxLoops: -1 default -> (type > 3) ? 1 : 0, 0 endless on a shared pool instance, 1 once and hold on an own instance | - |
| 8 | Answered (§3.3): `TerrainDrawBatch::BeginFrame` S 006bd460 sets `+0x64` to `shader level < 2` every frame | - |
| 9 | Per-LOD vertex counts of the terrain draw batch (§3.3) | static: the builder of the tables at `TerrainDrawBatch +0x74`, `+0x80` |
| 10 | Consumer of the `FogOfWar` texture in `CEnviromentMgr +0x11c` | static: bind calls of that texture |
| 11 | Combination of day-time keys and per-map `EnvData`. The hour does not run during a match: `CEnviromentMgr +0xfc` is written by the constructor S 00685070 (the `localtime` of the environment XML, default 10), by `Update` S 00683d50 (set to that value again every frame while the scene is not animated, untouched otherwise) and by the setter in vftable slot 8 S 00683fd0, which has no caller in the decompiled image; the time scale `+0xf8` has no reader [known]; the hour stayed 12.0 over 4,367 ticks [live, 2026-10-12] (§6.6). Open: the combination of the keys with `EnvData` | static: readers of the day-time keys and of `EnvData` |
| 12 | Answered (§3.8): a water post's height is `seaLevelHeight + 0.05 * sin(t * 2π * 0.3 + x + z)` (disassembly of S 006b2ae0; constants S 00882840, S 007e6af0, S 007e6d80) | - |
| 13 | Answered (§3.14): a marker takes a whole `decals.xml` texture in white (style 1 `buildingselect.dds`, 2 `catapultTarget.dds`; that the style indexes the list is [inferred]), 4 units for a cell, the larger box side for a building, 0.3 above the ground. The rotation time is the simulation's accumulated time in seconds (§3.14). The build icon atlas layout is answered too (§3.14: `ui_ingame3.dds`, 88-pixel icons from (16, 808), table filled by S 007cad30, split by `infomap_shader.fx`; the cursor cell's glowing icons from (16, 640)) | - |
| 14 | Answered (§6.1): rotations and phase speeds build the normal-map texture matrices, `tex0Scale`/`tex1Scale` reach only the fixed-function texture coordinates, `color` is read by nothing | - |
| 15 | Answered (§3.5): the terrain vertices are world positions, so the caustics pass adds nothing | - |
| 16 | Meaning of shadow level 1 (global S 0088d6bc) and of the shadow flags 0x18 / 0x1a / 0x5a | static: readers of S 0088d6bc and of `Scene +0x34` |
| 17 | Answered (§6.6): a day-time key loaded from `daytimes.xml` has heading = elevation | static: S 00684130, S 006e7b20 |
| 18 | Whether the handlers of §3.2 that were not re-read call any logic mutator (§8) | static: read each handler body |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 006824c0 | `S2CG::Scene::Init` | load order of all render data |
| 006890f0, 006883e0 | `CMapRenderer::ctor` / `InitForMap` | sub-renderer creation order; per-map initialisation |
| 00688cd0, 00688d20 | `CMapRenderer::SetActive` / `ReinitForMap` | the two entries of the per-map initialisation |
| 0067eed0, 0067ef30 | `Scene::OnWorldLoadStateChanged` / `OnLogicInitStateChanged` | renderers off and on around a load |
| 00681850, 00681890, 006818d0, 00681930, 00681900 | `Scene` callback slots +0xa0, +0xa4, +0xa8, +0xac/+0xb4, +0xb0 | sacrifice building movies |
| 0067f3b0, 006819a0, 00681fd0, 00681960 | `Scene` callback slots +0xb8, +0xbc, +0xc0, +0xc4 | `buffGfxName` on ship, character, explored cell, building |
| 006ace00 / 006acf70 / 006ad050 | `S2CG::SacrificeBuilding::StartEffect` / `StartResearchEffect` / `StartWaitForGoodsEffect` | back-dated movies |
| 006a3d90 / 006a32b0 / 006a3400 / 006a3610 / 006a3af0 | `ProjectileTable::AddProjectile` / `Projectile::ComputeLaunchVelocity` / `Update` / `ComputeImpactPoint` / `OnImpact` | projectile record, arc, target point, impact |
| 00783790 | `Scene_LoadTerrainStaticDataAndMapObjects` | `terrain_static_data.xml`, `map_objects.xml` |
| 006905e0 | `S2CG::CCharacter::SetPath` | path change; writes only scene objects |
| 0069a9c0, 0069ab00 | `SwarmMgr::LoadSettings` / `ctor` | `flocks.xml` root keys, defaults, generator seed |
| 006aec60 | `ai::render::MapEnvData::LoadDefaultsXml` | `local_enviroment.xml` |
| 00684510, 00684690 | `CEnviromentMgr::LoadDaytimesBin` / `SaveDaytimesBin` | day-time key cache |
| 00680550 | `S2CG::Scene::SyncLogicTick` | per-tick synchronisation |
| 006805e0 | `S2CG::Scene::Update` | per-frame update order |
| 0067f6b0 | `S2CG::Scene::UpdateDetailFlagsAndTime` | pass masks, layer flags, time base |
| 006836b0 | `S2CG::Scene::Render` | shadow view, reflection view, main view |
| 0067eb20 | `S2CG::Scene::RenderPasses` | scene pass order |
| 00680a00 | `S2CG::Scene::RenderPostFxAndOverlay` | combine, overlay, particles |
| 0067f420 | `S2CG::Scene::ApplyShadowQuality` | shadow levels |
| 00681520, 00681560 | `Scene::OnBuildingCreated` / `OnBuildingRemoved` | examples of the logic callbacks (all in §3.2) |
| 006898f0 | `S2CG::CMapRenderer::Render` | map layer order |
| 006889d0 | `S2CG::CMapRenderer::RenderObjectsAndWater` | clipped objects, border, caustics, water |
| 006888f0 | `S2CG::CMapRenderer::Update` | per-frame map update |
| 00689500 | `S2CG::CMapRenderer::UpdateSelectionMarkers` | selection markers |
| 006b36d0 / 006b3870 | `ai::render::ConstructionMapRenderer::AddCellsInRect` / `CreateResources` | build icon per cell; quads, shader, atlas |
| 007cad30 / 007cacc0, 007cacf0, 007cad10 | build icon table filler / atlas origin and icon size initialisers | `g_ConstructionMapIconTable` S 0088da78 |
| 00688c40 | (construction overlay draw test) | draws only while the tint alpha > 0 |
| 005eabd0 | `nMenu::Game::StartOverlayColorFade` | the only writer of the overlay tint (info map, cinematic) |
| 00689f10 | `S2CG::CLandscape::Render` | base, unexplored, transition, ground cover |
| 0068a4a0 | `S2CG::CLandscape::UpdateVisibleCells` | terrain culling |
| 0068a120 | `S2CG::CLandscape::SetFogOfWarOverlay` | exploration overlay switch |
| 006b73b0 | `S2CG::CTerrainCellMgr::CreateTerrainCells` | block grid |
| 006b6840 | `ai::render::TerrainCell::BuildPatches` | pattern layers of a block |
| 006b65d0 | `ai::render::TerrainCell::AddHexPatches` | solid and blend patch rule |
| 006bd940 | `ai::render::TerrainDrawBatch::AddPatch` | terrain vertex, mask UVs, stitching |
| 006bd770 | `ai::render::TerrainDrawBatch::ComputeUnderwaterTint` | under-water vertex colour |
| 006b55e0 | `ai::render::TerrainCell::UpdateLOD` | block LOD |
| 006bade0 | `TerrainPatterns_RegisterFromXml` | pattern definitions and rank |
| 006bb3a0 | `S2CG::CTerrainPatternManager::Init` | pattern records of a map |
| 006bbb60 | `S2CG::CTerrainPatternManager::ApplyPatternMaterial` | textures, scales, mask, pass per record |
| 006bbde0, 006bbeb0 | `RenderBaseLayers` / `RenderTransitionLayers` | the two terrain passes |
| 006b9d60 | `S2CG::CTerrainPatternManager::RenderUnexploredCells` | black unexplored blocks |
| 006c0ec0, 006c0ca0 | `ai::render::TerrainMesh::Create` / `CreateOverlayTexture` | mesh, overlay texture, `fow_noise.tga` |
| 006bef70, 006bed80 | `TerrainMesh::ApplyVisibilityMask` / `UpdateHeightTexels` | overlay alpha and blue channels |
| 006b5f80, 006b6ea0 | `TerrainCell::RevealFromExploreMap` / `CTerrainCellMgr::RevealCellsInRect` | block reveal |
| 006b7070, 006b4f80 | `CTerrainCellMgr::AddObject` / `TerrainCell::SetVisible` | block objects and their hiding |
| 006aa320, 006aa150, 0069fe80 | `S2CG::Building::SetHidden` / `SetFogVisible` / `BuildingRenderer::ApplyVisibilityMaskToTiles` | building hiding and fog flag |
| 006c57b0, 00690f80, 006919b0 | `ai::render::CharacterMovement::Update` / `CCharacter::IsInFrustum` / `CCharacter::SetVisible` | character fog test, carried goods hidden with the carrier |
| 006cdfb0, 006a4e60 | `Animal::UpdateVisibility` / `S2CG::Ship::UpdateEnabledFlag` | animal and ship fog tests |
| 00787cc0 | `nGame::Cursor::PickVisibleEntityAtMouse` | ray pick of buildings, owner's exploration |
| 006a8a20 | `S2CG::WorldRenderer::CreateGraphicResources` | water techniques and textures |
| 006a7c70, 006a7de0 | `WorldRenderer::BeginWaterPass` / `AddWaterTileQuad` | water surface |
| 006a65a0 | `S2CG::WorldRenderer::UpdateWaterAnimation` | normal map matrices |
| 006a7fa0, 006a7400 | `WorldRenderer::BuildMapBorderSegments` / `RenderMapBorder` | map border skirt |
| 006a77d0, 006a79c0, 006a6a40 | `WorldRenderer::ComputeMapEdgeExtents` (two copies) / `EmitWaterQuad` | skirt edge height; water and skirt quads |
| 00687810, 00687090 | `TerrainGrid::ComputeNormalsInRect` / `PackNormalToBytes` | packed vertex normals |
| 006a93c0 | `Gfx_Water_LoadFromXml` | `<Water>` |
| 006b29c0, 006d8f50 | `BorderMgr::BuildPlayerBorders` / `PlayerBorderPoints::BuildFromMap` | territory border points |
| 006b2ae0 | `ai::render::BorderMgr::RenderSet` | border posts and buoys, the water posts' bob |
| 006b3290, 006b2d80 | `BorderMgr::ctor` / `RenderWithEffect` | border mesh names; the sets drawn with a passed effect (the shadow pass, shadow level 5 and above) |
| 006d8d00 | `Render_GetPlayerColorOrWhite` | border tint, white without a player |
| 00687790, 00687050 | `TerrainGrid::CellToWorldPos` / `GetSeaLevelHeight` | land border point; water post height |
| 00682ca0, 00669e60 | `S2CG::Scene::OnFlagCreated` / `NNet::Flag::LinkNavyObject` | flag model choice; flag announced again when a harbour is linked |
| 006821b0, 006a0e60 | `Scene_LoadBuildingsXml` / `BuildingRenderer::InitGraphicsResources` | root attributes, colour map, `COLORMAP_OFFSET`, variation step |
| 006a2bf0, 006a17a0 | `S2CG::BuildingRenderer::AddBuilding` / `RemoveBuildingInstance` | building instance creation, instance slot (colour variation) |
| 006a0ad0, 006a0cc0 | `S2CG::BuildingRenderer::Render` / `RenderWithExternalEffect` | building passes; shadow map pass |
| 0069ff70 | `S2CG::BuildingRenderer::Update` | construction list, distance LOD, clip plane capability |
| 006a0180, 006a0380 | `RenderConstructionSites` / `RenderInstances` | frame mesh stages, clipped finished mesh |
| 0069fb10 | `S2CG::BuildingRenderer::DrawInstance` | LOD part, colour variation offset, materials |
| 006a06d0 | `S2CG::BuildingRenderer::RenderRuins` | ruins in the frame pass |
| 006aa1b0 | `S2CG::Building::GetConstructionStageIndex` | stage formula |
| 006aabe0, 006aae30 | `S2CG::Building::GetConstructionClipPlane` / `Building_HasClipProgress` | clip plane formula; when the rising building is drawn |
| 006abcf0 | `S2CG::Building::Update` | per-tick building visuals: progress values, material pile, door close, buffs, fire |
| 006ac810 | `S2CG::Building::ctor` | placement, progress fields, animated model, LOD bone binding, ground decal |
| 006aa640, 006aa3b0, 006aa6f0 | `Building::TriggerWorkCycle` / `PlayStateAnimation` / `PlayOneShotAnimation` | door and work clips |
| 006aa9d0 | `S2CG::Building::SetModelVariant` | LOD level and its bone binding |
| 006ab5b0, 006ab710, 006a1250 | `Building::BeginUpgrade` / `EndUpgrade` / `BuildingRenderer::BeginBuildingUpgrade` | upgrade display |
| 006abbb0, 006ac510 | `Building::UpdateFireEffects` / `InitFirePoints` | fire; fire points `FIRE_03`, `FIRE_06`, ... or the five fallback points |
| 006ab840 | `Building::StartDemolition` | dust by bit 0x4 of the size mask, sink start |
| 006d3880, 006d4060, 006a0990 | `BuildingDesc::LoadFromXml` / `LoadResources` / `ctor` | `buildings.xml`, meshes, defaults |
| 006d50e0 | `S2CG::BuildingMaterial::Create` | texture usages of a subset |
| 006b4400, 006da2a0 | `HouseDecalRenderer::AddDecal` / `GroundDecalMesh::Build` | ground decal laid on the terrain |
| 0068a760, 006c08a0, 006c0600 | `CollectTrianglesInBounds` / `CollectTrianglesInAabb` / `AppendTriangleIfOverlapsXZ` | terrain triangles under a decal's world box |
| 006ed590, 006ed6e0, 006ecd90 | `TriangleListNode::BuildEdgePlanes` / `TriangleList::ClipByPlanes` / `AddTriangle` | decal clip |
| 00687e60, 00687a70, 00687570 | `TerrainGrid::SampleHeightAndNormal` / `FindTriangleAt` / `FindNearestVertex` | decal vertex heights |
| 006ab420, 006d4f90 | `Building::RefreshGroundPlacement` / `Ruin::RefreshGroundPlacement` | decal laid again after a height change |
| 006a19b0, 006d4e00 | `BuildingRenderer::AddRuin` / `Ruin::ctor` | ruin model and decal |
| 006db7a0, 006db8d0, 006db700 | `Harborplace::ctor` / `UpdateGroundHeight` / `dtor` | harbour place plot |
| 006b7220, 006db520 | `CTerrainCellMgr::UpdateCellHeightsInRegion` / `InstanceMesh::UpdateGroundHeight` | re-grounding block objects after a height change |
| 006d2820, 006d2ec0, 006d2ab0 | `S2CG::CMilitaryFlagRenderer::DrawFlags` / `InitGraphicsResources` / `Render` | military flags |
| 004d3df0 | `S2CE::CGraphicDevice::DetermineDeviceCaps` | `MaxUserClipPlanes` (S 0088d998) |
| 00695130, 00694c00 | `CCharacterMgr::LoadFromXml` / `LoadCharacterDefs` | character data |
| 00695490 | `S2CG::CCharacterMgr::CreateCharacter` | settler visual creation |
| 00692c60 | `CCharacterMgr::FindCharacterDefIndex` | character definition by name, −1 when missing |
| 006909f0 | `S2CG::CCharacter::UpdateLogic` | animation slot choice |
| 006c64c0, 006c63a0, 006c6590 | `CharacterAnimation::SetAnimationType` / `PlayAnimation` / `UpdateLogic` | playback, idle variations |
| 006ca8d0, 006cc350 | `ai::anim::AnimationSet::GetAnimIdForSlot` / `ctor` | override lookup, table construction |
| 006910e0 | `S2CG::CCharacter::SetShaderConstants` | palette constants |
| 00692a30, 00692e20 | `CCharacterMgr::Update` / `Render` | culling, LOD, draw |
| 0068f200 | `MapObjDefs_ParseLandscapeElement` | `map_objects.xml` |
| 0068d360, 0068d610 | `MapObjLayer::RenderEntries` / `RenderClippedEntries` | map object passes |
| 006b8ec0, 006b90a0 | `InstanceMeshRenderer::Render` / `AddInstance` | instancing |
| 006be2d0 | `S2CG::GroundCoverRenderer::SetSlice` | grass shell parameters |
| 0068b220, 0068ac10 | `CLandscape::CollectResourceParticleCandidates` / `SpawnRandomResourceParticle` | resource hints |
| 00684be0, 00684130 | `Env_ParseEnvironmentXml` / `CEnviromentMgr::LoadDaytimes` | environment data |
| 006ae700, 006ae3a0, 006aea80 | `MapEnvData::Update` / `ApplyToDevice` / `LoadBin` | local environment |
| 006af490 | `ai::render::SkyRenderer::BuildGeometry` | sky dome |
| 006810b0, 0069e2a0, 00769600 | `Scene::RenderShadowMapPass` / `ShadowManager::RenderCasters` / `S2CE::ShadowManager::SetQuality` | shadow map |
| 00680ab0, 006d7cc0 | `Scene::RenderReflectionPass` / `MirrorCamera::ReflectViewMatrix` | reflection |
| 00696d20, 00697010, 00696ac0 | `PostProcessor::BeginScene` / `RenderBlurPasses` / `RenderCombine` | post effects |
| 006c3f10 | `ai::gfx::StreetRenderer::LoadConfigXml` | `<Street>` |
| 006a9830 | `S2CG::CGraphicAccess::PickAtScreenPos` | picking entry |
| 006960a0, 00696270 | `S2CG::Settings::Load` / `Store` | scene settings stream |
