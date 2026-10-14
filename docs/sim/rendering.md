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
| +0x1c | float | detail setting | 0..1 (settings virtual +0x3c); `toInt(v*4 + 0.5)` is the scene detail level | [known] S 0067f500; conversion [inferred] S 0067f6b0 |
| +0x20 | float | shadow setting | 0..1 (settings virtual +0x24); `toInt(v*6 + 0.5)` is the shadow level (§3.13) | [known] S 0067f500; conversion [inferred] S 0067f6b0 |
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

**`ai::render::TerrainPatternRecord`** (0x18 bytes; one per pattern the map uses; `CTerrainPatternManager +0x84`):
`patternIdx` (+0, index into `g_TerrainPatterns`), `mapPatternId` (+4, the id stored in the map's pattern grid),
`baseRecordIdx` (+8; for an alias: the record of the aliased pattern, else -1), `texture0` (+0xc), `texture1`
(+0x10), ground cover layer index (+0x14) [known] S 006bb3a0, S 006bbb60; the field offsets are those of the
mapped struct [inferred]. A pattern name of the map that has no `<Pattern>` definition gets no record
[known] S 006bb3a0.

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
| `S2CG::Building` | 0x218 | logic building (+0x18), gfx desc (+0x34), world position (+0x9c), hidden (+0xc0), fog visible (+0xc4), construction progress previous / current / fade end time / rate (+0xc8..+0xd4), under construction (+0xd8), the same four for the upgrade (+0xdc..+0xe8), upgrading (+0xec), upgrade gfx desc (+0xf0), demolish progress (+0xfc, negative = none), shadow caster (+0x100), ground decal (+0x104), scaffold (+0x1fc), fire point count (+0x200), fire points (+0x208, 0x5c each) | [known] S 006aa1b0, S 006aabe0, S 006abbb0, S 006ab840; [inferred] S 006ac810 |
| `S2CG::BuildingDesc` | 0xc0 | name, mesh path, frame path; LOD mesh parts (+0x54), animated visual (+0x5c), bounds (+0x68 min.y, +0x74 max.y), door and work animations (+0x80..+0x88), production sub-desc (+0x8c), stage count (+0xa4), stage subset table (+0xa8), frame render object (+0xac) | [known] S 006aabe0 for bounds, [inferred] S 006d3880, S 006a15a0 |
| `S2CG::CCharacter` | 0xbc [inferred, mapped struct] | animation (+0x80), movement (+0x84), per-type logic face (+0x88), queued animation (+0xa4), effects (+0xb0) | [known] S 006909f0 |
| `S2CG::CharacterAnimation` | 0x6c [inferred, mapped struct] | model cache (+8), current track (+0xc), instance handle (+0x30), selection keys (+0x38, +0x3c, +0x40, +0x44), requested slot (+0x54), loop mode (+0x58), owner face (+0x60), one-shot playing (+0x64), idle sequencer (+0x68) | [known] S 006c64c0, S 006c6590 |
| `ai::render::CharacterMovement` | 0x160 | previous and target position (+0x2c, +0x38), inverse duration (+0x48), render position (+0x58), route spline | [inferred] S 006c57b0 |
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
| +0x18, +0x1c | flag created / removed | map object `z_flag_00`, or `z_harbor_flag_00` when the flag has a harbor reference, tinted with the owner's colour; register with the item manager (goods stacks at the flag) | S 00682ca0, S 00682de0 |
| +0x20 | settler created | `CCharacterMgr::CreateCharacter` | S 0067f0f0 |
| +0x24 | settler removed | destroy the character, if one exists | S 0067f120 |
| +0x30 | fight strike | one-shot particle effect `HitDamage` at the attacker, facing the target | S 00683530 |
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
| +0xa0, +0xa4 | sacrifice started / removed | start / stop the effect on the sacrifice building | S 00681850, S 00681890 |
| +0xa8, +0xb0 | sacrifice research / wait for goods | effect movies `sacrificeResearchGfx` / `sacrificeWaitForGoodsGfx` | S 006818d0, S 00681900 |
| +0xac, +0xb4 | building effect stopped | stop the building's active effect | S 00681930 |
| +0xb8 | ship effect instance | attach an effect to the ship graphic | S 0067f3b0 |
| +0xbc | sacrifice applied to settler | attach the sacrifice's buff effect (`SacrificeProperty` `buffGfxName`) to the character | S 006819a0 |
| +0xc0 | sacrifice applied to cell | one-shot particle effect of that name at the cell, only if the cell is explored by the local player | S 00681fd0 |
| +0xc4 | building revealed by sacrifice | attach the buff effect to the building | S 00681960 |
| +0xc8, +0xcc | chest created / removed | map object of the doodad property whose id is game config +0x44 (`chestDoodadId`), or +0x48 (`openChestDoodadId`) when the chest predicate `ai::logic::LogicChest::IsOpenable` S 00539210 holds; occupancy bit | S 006819e0, S 00681aa0 |
| +0xd0 | chest opened | swap the closed model for the opened one | S 00680c80 |
| +0xd4, +0xd8 | spawn point added / removed | marker map object; occupancy bit | S 00681b30, S 00681bb0 |
| +0xdc | spawn triggered | one-shot particle effect named by the spawn property | S 006820f0 |

`NMap::CallbackReceiver` (face +8; five slots, [known] from the vtable S 007f8f08 and the handlers' code; event
names [inferred]):

| Slot | Event | Reaction | Handler |
|---|---|---|---|
| 0 | height rectangle changed | update mesh positions, normals, height texels, block bounds, objects' ground height, streets; recompute the water's map edge extents | S 0067ef80, S 006882e0 |
| 1 | pattern rectangle changed | rebuild the patches of the affected terrain blocks; recompute the water's map edge extents | S 0067efa0, S 00688360 |
| 2 | map re-initialised | re-initialise the terrain grid (S 00688050) and the map renderer | S 0067efe0 |
| 3 | territory changed | clear and rebuild the border point lists of all eight players (§3.8) | S 0067f010, S 006883c0 |
| 4 | exploration rectangle changed for a player | if that player is the viewing player: update the "FogOfWar" texture, the overlay texture and block reveal (only while the overlay is active), and mask building tiles; then refresh ship visibility | S 0067f020, S 00688d40 |

Both rectangle handlers contain a test whether the rectangle touches the map edge, but the edge extents are
recomputed on either outcome [known] S 006882e0, S 00688360.

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
ordered: non-alias patterns by rank ascending, then alias patterns in the order of the map's pattern list
[known] S 006bb3a0.

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
`d2 = ((x-b.x)^2 + (z-b.z)^2) * s^2` [known] S 006bd940. [TODO] not established: who sets `+0x64`; a static read
of the writers of that byte would settle it (candidate: the fixed-function path, whose
`TERRAIN_TRANSITION_2TEX` state block in `shared.inc` takes alpha from the vertex colour).

**Level of detail and stitching** [known] S 006b55e0 (disassembly), S 0068a4a0, S 006bd940; the `eye` line is
read from a decompile with lost stack variables [inferred]. Per visible block:

```
eye         = cameraPos + 0.7 * (cameraTarget - cameraPos)
lodDistance = lodDistanceSetting * (detailFactor * 5 + 0.25) + 1.15 * sqrt((4*stepX)^2 + (4*stepZ)^2)
lod         = min(2, trunc(distanceXZ(eye, blockCentre) / lodDistance + 0.5))       // 0 if lodDistance <= 0
```

`lodDistanceSetting` is `CLandscape +0x38`, set from a global that holds `<Landscape lodDistance="50.0">`
[inferred from the global's name; known, file for the value]; `detailFactor` is the detail setting clamped to
0..1 S 00688220. The same sum is the radius argument of the block culling. The draw batch has per-LOD index
and vertex tables; when a visible neighbour has a lower `lod` value than the block, the neighbour gets the
stitch bit of the shared edge, and a patch of a block with `lod` < 2 that touches a stitched edge has its odd
edge vertices replaced by the average of their two neighbours (height and normal) so that no crack opens.
[TODO] not established: the vertex counts per LOD (tables at `TerrainDrawBatch +0x74`, `+0x80`); read the
table builder.

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

**Where water is drawn** [known] S 006889d0, S 006a7de0: one flat quad per visible terrain block whose minimum
height is at or below the water level, covering the block's whole AABB in x and z at the water height. The quad
is skipped when the block's AABB minimum y is not below the water renderer's own water level
(`WorldRenderer +0x4a0` times `heightScale`) [known] S 006a7de0; quads are batched up to 8000 vertices. The coast
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

`texMatrix0/1`: rotation by `tex0Rot` / `tex1Rot` and a translation `time * phaseSpeed` [inferred] S 006a65a0
(which global holds which XML value is not traced; [TODO] read S 006a93c0). Blend `SrcAlpha / InvSrcAlpha`.
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
`depth <= 0.1`, with `depth = 100 - y` as written in the shader. With that term the factor
`1 - saturate(depth * 0.15)` is 0 for every vertex below `y = 93.3`, so the pass as shipped adds nothing to the
picture [inferred from the file]; a remake can leave it out.

**Map border skirt** [inferred] S 006a7fa0, S 006a7400: for every edge block and the four corners one segment
that extends the block 200 world units beyond the map edge and down to the minimum edge height; drawn first as
flat black ground (`RenderMapBorderGround`, texture factor 0), then as water with the map-border water passes.

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

1. **Terrain blocks.** A block is *revealed* once any of its cells is explored (`TerrainCell::RevealFromExploreMap`
   S 006b5f80, rectangle converted with a margin of one block S 006b6ea0) [known]; a block is never un-revealed
   by exploration changes. An unrevealed visible block is drawn whole in the `Unexplored` pass: flat colour 0
   (black), depth written [known, file and S 006b9d60]. Map objects attached to a block (except those whose
   type virtual returns 2) and the goods piles inside its rectangle are hidden unless the block is both in view
   and revealed [known] S 006b4f80.
2. **Overlay texture** "WorldElevationMap" [known] S 006c0ca0, S 006bef70, S 006bed80: `(2*W + 1) x H` texels,
   format 0x15 (A8R8G8B8), filled with 0xff at creation; cell `(x, y)` owns the texels `2x` and `2x + 1` of row
   `y`, shifted right by one texel on odd rows (matching the half-cell shift); the one texel left over per row
   takes the alpha of its neighbour. Alpha = 0xff for an explored cell, 0 for an unexplored one; blue =
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

   [known, `shared.inc`]. The noise texture is `[data]/map/textures/fow_noise.tga`, bound to sampler 6
   [known] S 006c0ec0, S 006bf390. With bilinear filtering the alpha ramp gives a soft, noise-modulated edge
   about one cell wide. In the low quality mode of the terrain mesh whole texels are written instead
   (0x00ffffff explored, 0xff000000 unexplored) and no height is stored [known] S 006bef70, S 006bed80; below
   shader level 2 the texture matrix is built in camera space for the fixed-function stages [known] S 006bf390.
3. **Objects.** Characters outside the visible block rectangle are hidden S 00692a30 [inferred]; a ship is drawn
   only while its current cell is explored by the local player; the flag is recomputed while the ship moves and
   on every exploration change [known] S 006a4e60, S 0067f020; animals and the resource effects receive the
   exploration grid and the player [inferred] S 006805e0, S 0068b220. Buildings have a fog-visible flag
   (`Building +0xc4`): the model is shown only when the flag is set and the building is not hidden
   [known] S 006aa150; the flag is written by `BuildingRenderer::ApplyVisibilityMaskToTiles` S 0069fe80 on
   exploration changes [inferred].

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
every cell whose territory owner is that player and whose grid flag 0x20 (territory border) is set; the world
position of the cell is appended to list A when the grid flag 0x4 (water) is clear, to list B when set
[known] S 006d8f50 (the flag names are those of `docs/sim/map-resources.md`). The points are appended in a
greedy nearest-neighbour order starting from the last cell of the scan; the order has no visible effect
[inferred]. The lists of all eight players are cleared and rebuilt whenever the map fires slot 3 of
`NMap::CallbackReceiver` (§3.2) [known] S 0067f010, S 006883c0; there is no other caller of S 006b29c0.

Drawing [inferred] S 006b2ae0, [known] S 006b3290 for the file names: list A with the mesh
`[data]\map\objects\limes.GR2`, list B with `[data]\map\objects\buoy.GR2` (a `.GR2` name is loaded as the `.KEX`
file of the same base name), one instance per point (a float4 position per instance, no rotation), tinted with
the player's colour, a player's set skipped when its bounding box is outside the frustum; A posts sit at the
cell's terrain height, B posts at the water height plus `0.05 * sin(..)` [known] S 006b2ae0. Shader
`border_shader.fx` [known, file]:

```
rgb = (ambient + lightColor * saturate(dot(N, -L)) * shadow) * lerp(playerColor * 1.8, tex.rgb, tex.a)
```

then `CalcFOWWithAlpha`; alpha test `> 127` and alpha blend. `CalcPlayerColor` (this formula) is shared by all
player-tinted objects [known, `shared.inc`]. [TODO] not established: the argument of the bobbing sine (lost in
the decompile); read the disassembly of S 006b2ae0.

### 3.9 Buildings

**Type lookup** [inferred] S 006a2bf0: key `"<tribe resource name>_<building property name>"` against
`buildings.xml` `<Building name=..>`. Instance class by description: sacrifice building, catapult, farm
(a `<Production>` child), else plain `Building`.

**Assets per type** [inferred] S 006d4060, S 006d3880: `mesh` (KEX) with LOD files `<name>LOD0`, `LOD1`, ... as
long as they exist, node `House`; `frame` = the construction frame mesh with its own texture; animations
`DoorOpen`, `DoorClose`, `Working` with timed `<Sound>` / `<Particle>` events; bone `MILFLAG` = military flag
anchor; nodes `FIRE_03`, `FIRE_06`, ... = fire points.

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

  S 0088d998 is the building renderer's multi-stream capability flag [inferred from its mapped name]; a remake
  has to pick one of the two forms. [TODO] not established: who sets S 0088d998 and on which devices.

  The frame mesh is drawn with the subsets of that stage (`BuildingDesc +0xa8[stage]`)
  S 006a0180 [inferred]. `stageCount` = `BuildingDesc +0xa4` of the building's description, or of the upgrade
  target's description while upgrading [known] S 006aa1b0.
- *Rising finished mesh* `Building::GetConstructionClipPlane` S 006aabe0 [known]: the finished mesh is drawn
  clipped by a horizontal plane at

  ```
  p      = prev + (cur - prev) * (1 - (tTarget - now) * rate)        // or cur when no fade is pending
  planeY = worldPos.y + (modelHeight - 0.1) * p / 0.9
  ```

  with `modelHeight = desc.maxY - desc.minY` (the upgrade target's description and the upgrade's own four
  progress fields while upgrading), `now` = `timeInfo[1]`, and "no fade pending" = a negative `tTarget`.
  Construction uses the negated global mesh normal as plane normal (keeps the part below the plane, the global
  being the up vector [inferred]); an upgrade uses the normal itself for the old model, and the building is
  drawn a second time with the mirrored plane and the new type S 006a0380 [inferred]. `rate` = 1 / the
  property's speed value S 006ac810 [inferred].
  [TODO] not established: which logic value feeds `cur` (`Building +constrProgress`); read S 006abcf0.
- *Material pile* `BuildingScaffold` [inferred] S 006d82f0: item stacks for the goods in the construction stock,
  rebuilt when the stock's revision changes, laid out with the item stack layouts (§6.5).
- *Ground decal*: every building and ruin has a `GROUND` decal from the building mesh
  (`HouseDecalRenderer`, `house_decal.fx`) [inferred] S 006b4400.

**Finished building shading** (`house_shader.fx`) [known, file lines]: diffuse x light map (`Texture1`,
`texcoord1`) x colour variation map (`Texture2`, u offset `COLORMAP_OFFSET`); `<Buildings colorMap=..
numVariations="8">` [known, file]. [TODO] not established: how the variation index is chosen per instance
(the "variant object" created in S 006ac810).

**Level of detail** [inferred] S 0069ff70: from the distance to the near frustum plane with the type's `lodBias`
and `lodScale`.

**Demolition** [known] S 006ab840, S 006aaab0, S 006a1f20: started on removal when `LeavesRemains` holds
(§3.2). Start: one-shot particle effect `DemolitionDust`, or `SmallDemolitionDust` when bit 0x4 of the building
property's flags at +0x3c is clear; a 3D sound; the ground decal and the material pile are removed;
`demolishProgress = 0`. Per frame: `demolishProgress = min(1, demolishProgress + dt * 0.35)` and
`worldPos.y = terrainHeight(cell) - modelHeight * progress^2`; the fire points follow. On the logic tick after
the progress reached 1.0 the instance is deleted. The remains are a `S2CG::Ruin` with its own decal
S 006d4e00 [inferred].

**Fire** `Building::UpdateFireEffects` S 006abbb0 [known, disassembly]: the first `burning` fire points run the
effect `BuildingFire`, the others are stopped, with

```
burning = toInt((1 - Hitpoints::GetRatio()) * firePointCount + 0.5)        // toInt truncates
```

Fire points are the nodes `FIRE_%02d`; without such nodes: 5 random points over 80 % of the bounds, from a
private generator with the static seed 0x5432ace0 S 006ac510 [inferred].

**Buff effects** [inferred] S 006abcf0: `ShipSpeedUp`, `BuildingArmor`, `WorkerPause` while the corresponding
state holds.

**Military flags** [known] S 006d2820, S 006d2d80: on buildings whose construction remainders are both <= 0
and whose military component reports a flag, at the bone `BuildingDesc +0xbc` (`MILFLAG`), or without that bone
at a point derived from the bounds (x = centre + 0.33 * size, z = centre - 0.55 * size; [inferred], the
decompile of this part is garbled). 23 meshes in `[data]\buildings\`: 0 `MilitaryFlagInactive.KEX`,
1..11 `MilitaryFlagSword00..10.KEX`, 12..22
`MilitaryFlagBow00..10.KEX`.

- Mesh: 0 unless the building is occupied and its territory component is active; else `1 + n` (`+ 11` for the bow
  set), with `n` = `NVillage::Military::GetFlagSoldierCount` S 0055fd40: the number of soldiers present in the
  building, or for a building whose property has the three flags at +0x54, +0xf1 and +0xf5 set (the
  headquarters-type depot [inferred]) the number of soldiers in its depot stock, capped at 10.
- Texture: one of three (`MilitaryFlag1..3.dds` [inferred]); index 0 unless the building is a military building,
  else `max(0, zone)` with `zone` = `NVillage::Military::GetProximityZoneA` S 0055fbb0 (a 0 / 1 / 2 class of the
  value at `Military +0x5c`, -1 while the territory component is inactive; `docs/sim/military.md`).
- Tinted with the owner's colour (`house_soldierflag.fx`).

[TODO] not established: the value that selects the bow set (its read is lost in the decompile of S 006d2820;
read the disassembly at the call of S 0055fd40).

**Farm props** S 006d5660: the first `visible` props of the `<Production>` child are shown, recomputed when
the productivity changes; productivity = `Statistics::GetProductivity` of the building, 0 unless production is
enabled and the building is occupied [known]; `visible = toInt(productivity * numModels + 0.5)` [inferred: the
x87 part is not in the decompile, the formula is the one of the mapped comment]. Props sit at `location<i>`
offsets or `boneLink<i>` bones [inferred].

**Catapult** [inferred] S 006d6000..S 006d65c0: bones `ROTATE`, `ARM_ROTATE` and `BULLET_POS` [known, strings
in S 006d65c0]; yaw interpolated toward the logic direction, arm angular speed 3.0.

### 3.10 Settlers: models, colours, movement, animation

**Model definition** (`settler_config.xml`) [known, file]: `<Character name mesh mesh1 mesh2 mesh3 color slotMap>`
= LOD meshes 0..3 (the shipped entries read here carry `mesh`, `mesh1`, `mesh2`), the index texture and the
colour slot map; one shared skeleton model (`<Models><Model>`).
Lookup key `"<tribe resource name><sep><character name>"`, fallback entry 0 S 00695490 [inferred].

**LOD** [inferred] S 00690460: squared camera distance against three ranges; `<Characters lod0Range="30.0"
lod1Range="40.0" lod2Range="60.0">` in `settler_config.xml` [known, file]. Global scale `scale="1.2"`.

**Colour** (`skin_color_mesh.fx`) [known, file]: the mesh texture is an index map, not a colour map:

```
idx   = indexMap(uv)                      // point filtered
D     = saturate(dot(N, -L)) * lightColor.a * shadow + ambient.a          // scalar light
tap.x = saturate(idx.g * D) * colorIndexScale.x + atlasOffset.x           // luminance x light -> ramp column
tap.y = idx.r * colorIndexScale.y + atlasOffset.y                         // red -> ramp row (material slot)
color = palette(tap + halfTexel)
rgb   = lerp(playerColor * idx.g * D * 2, color.rgb, idx.a)               // alpha 0 = player-coloured cloth
rgb  += pow(saturate(dot(reflect, V)), 16) * idx.b                        // blue = specular mask
```

The palette is a 1024 x 1024 atlas built at run time; each character owns a block and
`COLOR_INDEX_SCALE = (15 / atlasWidth, 256 / atlasHeight)` [inferred] S 006910e0, S 00695130: a block is 16
texels wide (shade) and 256 rows high. The rows come from `color_slots.xml`: `<Slot>` names (15),
`<ColorRamp slot solid|texture rows>` ramps, `<ColorMap name>` with `<Material index slot>` rows [known, file
structure]. When the creator passes no palette, a random one from the colour map table is taken S 00695490
[inferred]. [TODO] not established: which random generator that is and how a block is filled from the ramps
(S 006c9bc0, S 006c9d20).

**Movement between ticks** [inferred] S 006c57b0.., [known] S 006805e0 for the factor: on each logic tick the
movement component stores a previous and a target position (tile to tile, or a sample of the street's route
spline at the settler's path progress); per frame

```
f   = 1 - (nextTickTime - now) * (1 / tickLength)           // 0 at the tick, 1 at the next
pos = lerp(prev, target, f)
```

then the height is snapped to the terrain, a sideways offset (street avoidance of oncoming settlers,
`evadeRadiusScale`, `evadeStart`) is applied and decayed, and the yaw turns toward the hex direction of the move
by a fixed step per tick. Death (entity state 5): the figure sinks at `0.35 * dt` S 006c7640.

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

**Carried goods and tools** [inferred] S 006c7850, S 006c74f0: an item is attached to a bone (`Bip01 R Hand`,
`Bip01 Head` or the type's attach bone); a carried good overrides the default tool item; `<Characters goodOffset
goodRotation boatOffset>`. Animation events (`<Sound>`, `<Particle>`, `<Item>` children of an `<Animation>`)
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

**Placement** `MapObjLayer::AddInstance` S 0068dd40 [inferred]: at the cell's world position, with a random yaw in `rot`
(two values: min, max), random scales in `scaleX`, `scaleY`, `scaleZ`, an optional `offset`, snapped to the
ground or, with `alignOnWater`, to the water level. The random draws come from the static generator S 0088d4ec
(§8) [known] S 0068dd40.

**Instance classes by `type`** [known, file] for the values, [inferred] for the classes: `tree` → `TreeInstance`,
`stone` → `StoneInstance`, `wheatField` → `WheatInstance`, `gate` → `Stargate`, `routeBuoy` → `RouteBuoy`,
`harbor` → `Harborplace`, `flag`, none → plain `InstanceMesh`.

**Draw** [inferred] S 006b8ec0, S 0068d360: batches of `numInstances` per draw call with one matrix array upload;
a batch breaks when the instance colour (`FLAG_COLOR`, the owner colour of flags) changes; `blendMode` 1 = alpha
test and blend, 2 = blend only, else alpha test only; distance fade on the non-instanced path
`alpha = 1 - (d^2 - start^2) / (end^2 - start^2)`. `shadowCast`, `shadowReceive`, `forceShadowPass`, `priority`,
`transparent` per definition.

**Trees** `TreeInstance::UpdateAnimation` S 006dcb10 [inferred]: state 1 growing: with `g` = the resource's growth 0..1
(`resource +0x18`), scale `(min(1, 3g), g, min(1, 3g))`; state 2 standing (growth ≥ 1): optional sway, a rotation
about a horizontal axis by `amplitude * sin(phase)` while being felled at; state 3 falling: rotation about the
same axis by a fading angle; state 4 fallen. Value changes are faded at rate 10 per second (one logic tick).
Wind is in the vertex shader (`tree_shader*.fx`): `pos.x += s * sin(waveSpeed * m41 + t)`,
`pos.z += s * cos(waveSpeed * m43 + t)`, `s = saturate(dot(pos, pos) * waveStrength) * m22` [known, file].

**Wheat** `WheatInstance::UpdateAnimation` S 006dc590 [inferred]: Y scale = growth, faded the same way; state 2 = grown.

**Deposits (level fade)** `MapObjLayer::AnimateMeshesAndLevelFades` S 0068d160 [inferred]: a counter 0..20 on the logic
object (`+0x50`) lowers the instance by `level * extentY` (the pile shrinks into the ground), faded at rate 10.

**Route buoy** S 006dba70 [inferred]: `y = waterHeight + 0.15 * sin(time * w + x + z * k)`. **Flags** wave in the vertex
shader: `CalcFlagVertexPos` [known, `shared.inc`]:
`s = 0.33 * saturate(dot(p.xz, p.xz) - 0.02)`, `c = 0.5 + 0.5 * cos(4 * (m41 + m43 + p.x + p.y + t))`,
`p.z += s * c`, `p.x += s * (1 - c)`.

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
`ships.xml`: `idle`, `move`, `sink`); yaw steers toward the hex heading; sine bobbing; a status overlay mesh
(`<Freight>`, `<Expedition>`, `<Soldiers>` meshes) by cargo kind; construction `frame` mesh per tribe.

**Animals** [inferred] S 006ce2c0: logic states 5, 7, 8, 9 play the death animation once, after which the model
sinks at `0.4 * dt`; standing animals play one of two idles chosen with a private generator (static seed
0x5432ace0); moving animals interpolate between cell and next cell. Definitions in `animals.xml` (`model`,
`mesh`, `scale`, `<Animation
name filename>`).

**Projectiles** [inferred] S 006a3a40, S 006a3400: launched at `timeInfo[1]` from the
current world position to the logic target, flight time from the logic event's tick span, ballistic arc; model,
tumble `rotation`, `flightPFX`, `impactPFX`, `impactSound` from `projectiles.xml`.

**Particles** [inferred] S 00685bb0, S 004dfdc0: an effect name
maps to `[data]\scripts\effects\<name>.pfx`; emitters are culled, sorted back to front in depth buckets and drawn
with `particle_shader.fx` from one atlas; one-shot emitters delete themselves when empty. *Effect movies*
(`effectMovies.xml`: `<EffectMovie name>` with `<FX start particles link duration sound>`) are timed sequences of
effects on named links of a building or character. [TODO] not established: the `.pfx` file layout
(`ParticleEmitter` deserialiser, emitter virtual `+0xc`); a static read of that function settles it.

**Resource hints** [known] S 0068b220, S 0068ac10, S 0068ad40: when the check time is reached and no candidate
is pending, one random cell is drawn in every visible block that has pattern layers and whose maximum height is
above the water level. A drawn cell that is explored by the viewing player and holds a ground resource (amount
not 0) of `IronOre`, `Gold`, `Coal`, `Stone` or `Gemstones` becomes a candidate with the effect
`Resource_<good name>`. With at least one candidate the next check follows after a random whole number of
seconds in `ResourceFX minTime..maxTime`, with none after one in `minTime / 2..minTime`. The spawn step then
plays the one-shot particle effect of one random candidate and clears the candidate list.

**Ambient swarms** [known, file] `flocks.xml`: `maxFlocks`, spawn interval, `<Bird>`, `<Fish>`, `<Bug>` with
boids parameters (`Evade`, `Pack`, `MatchSpeed`); zones `flight`, `water`, `ground` derived from the grid states
at load. Pure decoration.

### 3.13 Light, fog, shadows, sky, post effects

**Light model** [known, `shared.inc`]: one directional light. Per-vertex objects:
`c = (ambient + saturate(dot(N, -L)) * lightColor)`, halved on the fixed-function paths. Shadows only darken the
direct term.

**Environment values** [inferred] S 006ae3a0: an `EnvData` gives clear colour, ambient, light colour, fog start
and end (linear distance fog) and shadow intensity; the light direction comes from `lightheading` and
`lightelevation` (degrees) applied to a base vector; the shadow intensity is scaled by
`clamp((|elevation| - 20°) / 20°, 0, 1)`.

**Local environment** `MapEnvData::Update` S 006ae700 [inferred]: per-map spheres; weight 1 inside
`innerRadius`, linear to 0 at `outerRadius` (2D distance from the camera's ground focus point); weights are
divided by the number of influencing spheres; if they sum to less than 1 the map default fills the rest.
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

The caster mask uses the map layer bits of §3.1 (`CMapRenderer::RenderWithExternalEffect` S 006884a0).
Render target `128 << level`, level 0..4, R32F (or a hardware depth format), S 00769600; light matrices fitted
to the camera frustum clipped by the scene bounds, orthographic or perspective-warped S 00769880, S 00769f10.
Lookup [known, `shared.inc`]: `test = z / w + shadowScale.y`; lit if `test < depth`, else `shadowIntensity`;
2 x 2 taps bilinearly weighted (`SOFT_SHADOW`). `<Shadows scale="1.0" bias="-0.00325"/>` [known, file] feed the
device values behind `g_ShadowScale` [inferred] S 0067edd0.

**Sky** [inferred] S 006af490, S 00683e50: a parabolic dome `y = -(x^2 + z^2) / outer` of radius 5000 (outer
5010), 64 x 64 quads, UV tiled 7 times, vertex alpha falling toward the rim; one or two skydome textures with a
rotating texture matrix (`rotation`); sun and moon quads (`size`); `enviroment_shader.fx`. The skydome index
comes from the map's `.bin`.

**Environment particle layer** (`ai::render::EnvParticleLayer`, 0x258 bytes) [inferred] S 006adc90: a grid of
falling streak billboards (spacing 0.1) around the camera with a per-point pseudo-random phase;
`rain_shader.fx`. **Not present in this build**: the class has no constructor in the binary, no function allocates
0x258 bytes, and the only pointer to a layer, `CEnviromentMgr.envParticleLayer` (+0x120), is written by the
manager's constructor (S 00685112) and destructor (S 00684880) only, both times with 0. `Update`, the draw step
of §3.1 and the debug draw act only on a non-null pointer, so no weather is ever drawn [known for the writes;
inferred for the absence of an allocation]. The layer is a render object: presentation only.

**Post processing** [inferred] S 00697290.., [known, file] for the values: scene colour plus a view-depth target;
downsample, separable blur, combine: bloom above `minLuminance 0.98` scaled by `bloomScale 0.25`; depth of field
around a focal distance that eases toward the picked ground point at `focusSpeed 3.0`, range `focalScale 25.0`.

### 3.14 Selection markers and the build-placement overlay

**Selection markers** `CMapRenderer::UpdateSelectionMarkers` S 00689500 [inferred]: up to 4 projected decals. By
selection kind: a map cell with a radius, a building, a unit, a ship (radius fixed to 11). Enemy targets use
style 2; linked buildings and destinations get the extra markers; a marker whose target is gone clears the
selection. The decal is projected onto the terrain triangles under it (`CLandscape::ProjectDecal` S 0068aad0);
textures from `decals.xml` (3 `<Texture>` entries; the first is `[data]\gfx\decals.dds`) [known, file].
[TODO] not established: the UV rectangle per style inside those textures (`SelectionMarker::UpdateDecal` S 006b0d00).

**Build-placement overlay** `ConstructionMapRenderer::AddCellsInRect` S 006b36d0: for every cell of every visible
block (except the cell of the object being placed) the construction flags of the cell for the local player
(`docs/sim/map-resources.md` §3.5) choose an icon; cells whose flags are 0 get none, and nothing is drawn when
the player's byte +0x50 is clear [known]:

```
base  = 0 if flags & 0x04, else 1 if 0x02, else 2 if 0x01, else 3 if 0x08, else 4 if 0x10
index = base + 0     if 0x20 set and 0x40 clear
      = base + 5     if 0x40 set and 0x20 clear
      = base + 8     if both set
      = base + 11    if neither set
index = 16           if none of the five base flags is set (no modifier)
```

`index` selects one float of the 17-entry table `g_ConstructionMapIconTable` (the icon's texture coordinate)
[known] S 006b36d0. Icons are camera-facing quads of size `iconSize 3.0` at `iconOffset "0 0 -1.0"`
(`<Landscape>` attributes [known, file]), at the cell's world position, batched 50 at a time, tinted by the
overlay colour, drawn only while its alpha > 0 [inferred]; `infomap_shader.fx`. [TODO] not established: the
contents of the icon table (filled at run time) and the icon atlas layout; read the writer of the table.

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
  `CCharacterMgr::PickCharacterByRay` S 00692fc0, `ShipMgr::PickShip` S 00697db0 [inferred, mapped names];
- the overview texture `RenderOverviewTexture` S 00680d90 (a top-down view of the whole map through a camera
  fitted to the grid, water and terrain pass only) [inferred] and the preview textures `RenderPreviewTexture`
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
| `Water` | `shader="water_shader.fx"`, `color`, `phaseSpeed0="0.015 0.015"`, `phaseSpeed1="-0.017 -0.03"`, `tex0Scale=".1 .1"`, `tex1Scale=".1 .1"`, `tex0Rot="206"`, `tex1Rot="145"`, `OpacityFFP`, `TextureScaleFFP`, `TextureAnimSpeedFFP`, `TextureMoveSpeedFFP`. The parser S 006a93c0 names every one of these keys except `color` [known], so `color` is not read by it |
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
| `scripts/effects/*.pfx` | 64 particle effect definitions; plain (not in the encrypted container), binary; every file starts with a u32 length 4 and the text `0002`, then a u32 length and a name (`Default` in the three files looked at). The rest of the layout is open (§10) |
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
- handlers such as `OnSacrificeStarted` are also fired for objects that already exist ("re-attached after load")
  [inferred] S 00681850.

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
| fallback fire points of a building without `FIRE_xx` nodes (§3.9) | static S 0088da38, built on first use | 0x5432ace0 | S 006ac510 |
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
| `.pfx` | particle definitions (format open, §10) |
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
`CalcFOW`. Hide objects on unexplored cells (block granularity in the original).

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
| 1 | `.pfx` particle file layout after the two header strings (§6.5) and the emitter model (curves, atlas cells, blend modes) | static: `ParticleEmitter` deserialiser and `ParticleEmitterParams`, `ParticleCurve*` |
| 2 | KEX material and subset conventions used by buildings (stage subsets of the frame mesh, light map and colour map UV sets) | static: S 006d4060; data: one building KEX through `tools/kex.py` |
| 3 | The value behind `constrProgress` / `upgradeProgress` and its fade timing | static: S 006abcf0 |
| 4 | The value that selects the bow set of the military flag meshes (§3.9) | static: disassembly of S 006d2820 at the call of S 0055fd40 |
| 5 | Building colour variation index per instance | static: the variant object in S 006ac810 |
| 6 | Palette block construction from `color_slots.xml` (ramp rows, `solid`, slot order) | static: S 006c9bc0, S 006c9d20 |
| 7 | Override table C of the animation set (which property family) and the meaning of loop mode values | static: S 006cc350, `CModelCache::Acquire` |
| 8 | Who enables the radial vertex alpha of terrain patches (`TerrainDrawBatch +0x64`) | static: writers of the byte |
| 9 | Per-LOD vertex counts of the terrain draw batch (§3.3) | static: the builder of the tables at `TerrainDrawBatch +0x74`, `+0x80` |
| 10 | Consumer of the `FogOfWar` texture in `CEnviromentMgr +0x11c` | static: bind calls of that texture |
| 11 | Combination of day-time keys and per-map `EnvData`. The hour does not run during a match: `CEnviromentMgr +0xfc` is written by the constructor S 00685070 (the `localtime` of the environment XML, default 10), by `Update` S 00683d50 (set to that value again every frame while the scene is not animated, untouched otherwise) and by the setter in vftable slot 8 S 00683fd0, which has no caller in the decompiled image; the time scale `+0xf8` has no reader [known]; the hour stayed 12.0 over 4,367 ticks [live, 2026-10-12] (§6.6). Open: the combination of the keys with `EnvData` | static: readers of the day-time keys and of `EnvData` |
| 12 | Argument of the buoy bobbing sine of the territory border (§3.8) | static: disassembly of S 006b2ae0 |
| 13 | Selection marker styles (UV rectangles, colours) and build icon atlas layout | static: `SelectionMarker::UpdateDecal`, `ConstructionMapRenderer::AddCellsInRect` |
| 14 | Mapping of the `<Water>` attributes to the texture matrix globals; whether anything reads `<Water color>` (§6.1) | static: S 006a93c0 with S 006a65a0; xrefs of the string `color` near the water globals |
| 15 | The caustics depth term `-(y - 100)` and the look of shallow water | running game: screenshot of a shore at shader level 2 |
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
| 006c0ec0, 006c0ca0 | `ai::render::TerrainMesh::Create` / `CreateOverlayTexture` | mesh and overlay texture |
| 006bef70, 006bed80 | `TerrainMesh::ApplyVisibilityMask` / `UpdateHeightTexels` | overlay alpha and blue channels |
| 006a8a20 | `S2CG::WorldRenderer::CreateGraphicResources` | water techniques and textures |
| 006a7c70, 006a7de0 | `WorldRenderer::BeginWaterPass` / `AddWaterTileQuad` | water surface |
| 006a65a0 | `S2CG::WorldRenderer::UpdateWaterAnimation` | normal map matrices |
| 006a7fa0, 006a7400 | `WorldRenderer::BuildMapBorderSegments` / `RenderMapBorder` | map border skirt |
| 006a93c0 | `Gfx_Water_LoadFromXml` | `<Water>` |
| 006b29c0, 006d8f50 | `BorderMgr::BuildPlayerBorders` / `PlayerBorderPoints::BuildFromMap` | territory border points |
| 006b2ae0 | `ai::render::BorderMgr::RenderSet` | border posts and buoys |
| 006a2bf0 | `S2CG::BuildingRenderer::AddBuilding` | building instance creation |
| 006a0ad0 | `S2CG::BuildingRenderer::Render` | building passes |
| 006a0180, 006a0380 | `RenderConstructionSites` / `RenderInstances` | frame mesh stages, clipped finished mesh |
| 006aa1b0 | `S2CG::Building::GetConstructionStageIndex` | stage formula |
| 006aabe0 | `S2CG::Building::GetConstructionClipPlane` | clip plane formula |
| 006abcf0 | `S2CG::Building::Update` | per-frame building visuals |
| 006abbb0, 006ac510 | `Building::UpdateFireEffects` / `InitFirePoints` | fire |
| 006d3880, 006d4060 | `BuildingDesc::LoadFromXml` / `LoadResources` | `buildings.xml`, meshes |
| 006d2820 | `S2CG::CMilitaryFlagRenderer::DrawFlags` | military flags |
| 00695130, 00694c00 | `CCharacterMgr::LoadFromXml` / `LoadCharacterDefs` | character data |
| 00695490 | `S2CG::CCharacterMgr::CreateCharacter` | settler visual creation |
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
