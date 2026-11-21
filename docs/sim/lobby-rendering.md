# The lobby world's render path

Specification of how `sadk_noav.exe` draws the 3D lobby village (namespaces `Lobby`, `ai::lobbygfx` and the engine
layer `S2CE` below them): material choice, render queue, passes, the constants and textures each effect receives,
what the effects compute, plants, sky, water, shadows, the fly-by camera and when the world is drawn at all. Scope:
what the main menu's backdrop shows, i.e. zone 0 from camera mode 5 in lobby mode 0 (no avatars, NPCs or ambient
sounds; [`lobby-world-client.md`](lobby-world-client.md) §2.2, §3.7, §3.13). Avatars, pets, minigame boards, text
bubbles and the portrait pass are out of scope.

Tags: [known] = read at the address given (S 00xxxxxx) or in the named data file; [inferred] = one step of reasoning
from what is visible; [TODO] = open. Nothing here was observed in the running game.

Related documents, not repeated here: [`lobby-world-client.md`](lobby-world-client.md) (the world model: `CLobby`,
zones, objects, scene and settings files, camera modes), [`world-objects-rendering.md`](world-objects-rendering.md)
§3.11 (the engine's effect loading and shared constants), [`rendering.md`](rendering.md) (the device: table fog,
shadow map sizes, the shadow lookup in `shared.inc`), [`frontend-screens.md`](frontend-screens.md) §3.2 (the main
menu), [`app-shell.md`](app-shell.md) §2.7, §3.3 (the lobby graphics options and their first-run values).

## 1. Purpose and scope

The lobby has its own small renderer on top of the RTS engine's device and effect system: a material table read from
`lobby/config/materials.xml`, a texture and a mesh manager, a render queue sorted by a 32-bit key, and four views
(main, portrait, shadow, reflection). Every frame `CLobby::RenderFrame` S 004f9960 sets the zone's light, fog and
light-map projection, runs up to three passes (shadow map, water reflection, main) and draws the menu on top.
[known] S 004f9960

In scope: everything that decides the colour of a pixel of the menu backdrop. Out of scope: picking, selection
decals, debug overlays, avatars and the other zones' interiors (their materials use the same rules).

## 2. Data model

### 2.1 Material table (`CGfxShaderMgr`, `CLobby` +0xd4)

`materials.xml` is parsed once by the shader manager's constructor. [known] S 0050cb40, S 0050c300

- One `MaterialEntry` (0x1fc bytes) per `<material>`: its name, **lower-cased**, and 8 variants × 3 passes of
  `MaterialPass` (0x14 bytes): `shaderIndex`, `technique`, `transparentShaderIndex`, `transparentTechnique`,
  `alphaSorting`. Unset slots hold −1 (shader −1 = the pass does not exist). [known] S 0050c300, S 0050ba10
- Variant index of a `<lod>` = 4 · `instanced` + (`pplighting` ? 0 : 2) + (`shadow` ? 0 : 1). A `<lod default="true">`
  is stored as variant 0 and copied into variants 1, 2 and 3; its instanced variants 4..7 stay empty. [known]
  S 0050c300
- A `<pass>`'s `name` is searched for the substrings `std`, `shadow`, `mirror`, giving pass slots 0, 1, 2; one
  `<pass>` element can fill several slots (`name="std,mirror"`). [known] S 0050c300
- `shader` and `transparent_shader` are effect file names, registered in the shader table (`FindOrAddShader`
  S 0050c230); the effect is created on first use through `S2CE::CResourceMgr::AcquireShaderProgram` and four
  parameter handles are looked up by name: `OPACITY`, `COIN_COLOR`, `CHIP_TEXOFFSET`, `BOARD_COLOR_ARRAY`. The
  transparent pair is stored only when both `transparent_shader` and `transparent_technique` are present. [known]
  S 0050c300, S 0050b8c0

The 49 materials of the install, by variant (S = shadow on, P = per-pixel lighting on), are in `materials.xml`; the
ones zone 0 uses are in §3.3.

### 2.2 Mesh entries and submesh ranges (`CGfxMeshMgr`, `CLobby` +0xcc)

`LoadMesh(name, decl, file, bounds, type, scale)` caches meshes by file, mesh name and vertex declaration. `type`:
0 = instanced, 1 = plain without textures, 2 = plain with textures, 3 = footprint collider only. [known] S 0050b5b0

Per KEX material (submesh) a `SubmeshRange` {`effectIndex`, `textureCount`, `textures[4]`, `primStart`,
`primCount`} is built by `BuildSubmeshRanges` S 0050ad70 [known]:

1. The material name is lower-cased and looked up in the material table by exact match
   (`FindMaterialByName` S 0050bbd0); when it is not found, the material `default_opacity` is used.
2. The KEX material's texture list is walked **in file order**; texture *i* is loaded by the basename of its path
   (`CGfxTextureMgr::LoadTexture` S 00504aa0) and later bound to **sampler stage *i***. The usage string next to
   each path (3ds Max map slot names such as `DiffuseColor`, `SpecularColor`, `SpecularLevel`, `Glossiness`,
   `Opacity`, `Bump`, `Self-Illumination`) is read and **ignored**. [known] S 0050ad70
3. The array has 4 entries; the loop writes as many as the KEX lists (no bound check). No zone-0 material lists
   more than 4. [known for the loop; data: converted `.glb`, extension `SADK_kex`]
4. The material lookup runs inside the texture loop, so a KEX material **without textures keeps effect −1** and is
   never drawn (`leer`, `leer2` of the taverns, the `default` material of the town hall's collision mesh). [known]
   S 0050ad70, S 0051d580

In the remake's conversion each glTF material keeps the KEX texture list in file order under `SADK_kex.textures`;
the list index is the sampler stage, the `usage` field is the 3ds Max slot name and has no meaning to the game.

### 2.3 Render items and the queue (`CGfxRenderer`, `CLobby` +0xd8)

A render item (0x28 bytes): renderable, `sortKey`, kind, `pass`, `opacity` (the fade), distance, mesh, submesh.
`DrawQueue` S 00509880 sorts the items with `qsort` by ascending signed `sortKey` (`a.sortKey − b.sortKey`,
S 005090f0; ties in no defined order) and calls each item's draw callback. [known]

Sort key of a submesh item [known] S 0051d310, S 0051d6e0, S 0050ba90:

- the object's `rank` when it is ≥ 0 (`gfxparm rank`, default −1);
- else, when the material pass needs sorting (`alpha_sorting="true"`, or opacity < 1): `0x70000000 − int(distance ×
  100.0)` (double S 007d8ff0 = 100.0), so far items first;
- else `(effectIndex << 16) | (meshId << 8) | submeshIndex` (OR'ed, so mesh ids above 255 bleed into the material
  bits): opaque items grouped by material.

So the drawing order of zone 0 is: opaque items (all keys below 0x01000000), then the high cloud plane (rank
16777216 = 0x01000000), the low cloud plane (0x01000001), the water (0x01000002), then every sorted item back to
front. The sky dome has no rank and is an opaque item. [known for the keys; inferred for the resulting order from
the data: material count 49, mesh ids below 0x10000]

### 2.4 Views

`CGfxView(owner, renderTargetSize)`; the owner value is the **pass index** handed to the objects (0 = `std`,
1 = `shadow`, 2 = `mirror`, the slots of §2.1). Created by `CLobby::StartUp`: two views with owner 0 and no target
(main and portrait), one with owner 1 and no target (shadow; it draws into the shadow manager's target), one with
owner 2 and a 256 × 256 A8R8G8B8 target with a D24S8 depth buffer (reflection). [known: constructor arguments at
S 004f8f3f, S 004f8f9a, S 004f8ff6, S 004f9056, S 00508e70; the pass meaning is inferred from the material slots
and `CollectRenderItems`' pass argument]

`CGfxView::Render(now, renderMask, viewProj, eyePos, …, scene)`: frustum from `viewProj`, the zone's
`CGfxScene::RenderVisibleObjects` collects items (render-mask test, 16 × 16 culling grid), then `DrawQueue`.
[known] S 00508f20, S 00504b20 All three passes hand the **main camera's eye position** to the objects, so the
distance fade is the same in every pass. [known: the same stack block is passed at the three call sites
S 004f9fcc, S 004fa152, S 004fa399]

## 3. Rules and algorithms

### 3.1 Material, variant and technique choice

Per drawn submesh, `GetSubmeshRenderParams(mesh, submesh, pass, opacity)` S 00509db0 →
`GetMaterialTechniquePair(material, pass, instanced, opacity)` S 0050ba10 [known]:

1. **Instanced** = the mesh was loaded instanced **and** opacity = 1.0 **and** the tweakable
   `Lobby GfxSettings/enableInstancing` (image default 1, S 0087c965) is set. A fading instanced plant therefore
   draws through the non-instanced variants.
2. **Variant** = 4 · instanced + (per-pixel lighting ? 0 : 2) + (shadows ? 0 : 1), with the two flags of the shader
   manager: shadows = lobby shadow quality ≠ 0, per-pixel lighting = lobby shader detail = 1 ("High").
   `LobbyRenderSettings::Apply` S 005006e0 sets them at the start of every frame from the options stored by
   `CLobby::SetLobbyGraphicsOptions` S 004f5290.
3. **Pass slot** = the view's pass index (§2.4).
4. Opacity < 1.0 → the transparent pair of that slot, else the normal pair. A missing pair (shader −1) means the
   submesh is **not drawn** in that pass: no shadow pass → no shadow cast; no mirror pass → not reflected; no
   transparent pair → a fading object vanishes instead of fading. [known] S 0051d580
5. A mesh entry of type 1 (no textures) has no technique at all. [known] S 00509db0

The lobby graphics options and the main-menu defaults: shadow quality 0..3 (`UserProfile +0x98`), mirror 0..1
(`+0x9c`), texture quality 0..1 (`+0xa0`), object details 0..2 (`+0xa4`), shader detail 0..1 (`+0xa8`); first-run
values by measured fill rate in [`app-shell.md`](app-shell.md) §3.3 (below 1500 Mpixel/s: shadows off, shader detail
low or high, mirror on from 500). [known, cited there]

### 3.2 Per frame: what `RenderFrame` sets up (zone = `CLobbyCamera.interpState[mode]`, 0 for mode 5)

In order [known] S 004f9960 unless tagged:

1. Active camera = the lobby camera; `LobbyRenderSettings::Apply(main block, true)`; camera mode-4/5 keys (§3.8).
2. **Light-map projection matrix** of the zone, from the `light_map_object` copied at load
   ([`lobby-world-client.md`](lobby-world-client.md) §3.1): with the object's local bounds `min`, `size` and its
   transform (position `t`, rotation `q`):
   `M_lm = T(−t) · R(conj q) · S`, row-vector convention (`p' = p · M`), where `S` maps local x to
   `(x − min.x) / size.x` in column x and local z to `(z − min.z) / size.z` in column z. A world point thus gets its
   light-map coordinate from its position inside the light-map object's box, ignoring height. Zone 0: object
   `Terrain` at the origin without rotation, `light_map="terrain_light01.dds"`. [known for the construction; the
   assignment of the decompile's aliased temporaries to `T`, `R`, `S` is inferred]
3. Textures: the zone's light map and `skyWaterReflection.dds` (`CLobby +0x68`; the name at S 007e5878, next to
   `lightmap_white.tga` at S 007e5890).
4. Device state: fog range = `fog_start`, `fog_end`; background (clear and fog colour) = `fog_color`; ambient =
   `ambient`; directional light = (`light_dir` normalised, `diffuse`); `UpdateTransformations`.
5. Shadow pass (§3.7) when the shadow option ≠ 0.
6. Reflection pass (§3.6) when the mirror option = 1.
7. Main pass: bind the shadow map on stage 5 (shadow option ≠ 0), the zone light map on **stage 6 with `M_lm` as its
   texture matrix**, and on **stage 4** either the reflection view's target with the main camera's
   `viewProj · bias` (mirror on, `BindProjectedTexture` S 00508fa0, bias = scale (0.5, −0.5), offset (0.5, 0.5)) or
   `skyWaterReflection.dds` with the fixed matrix
   `u = 0.005 · x + 0.5`, `v = 0.005 · z + 0.5`, `w = 1` (mirror off; floats at S 00888b38..S 00888b74, 0x3ba3d70a
   = 0.005); render the main view; picking; the menu (`nMenu::System` render in lobby modes 0 and 1); present;
   unbind. [known; that the bound object on stage 6 is the zone light map and on stage 4 the reflection texture is
   inferred from the decompile's aliased locals]

The device turns each bound texture matrix into the shared `TEXTURE_TRANSFORM[stage]`
([`world-objects-rendering.md`](world-objects-rendering.md) §3.11), which is how the effects read `M_lm` (stage 6),
the shadow matrix (stage 5) and the reflection matrix (stage 4). [known: `shared.inc` aliases `ShadowMatrix`,
`PlanarLightMapTexMatrix` and the water's `TextureTransform[4]`]

**Shared constants the lobby effects read** [known: `shared.inc`, S 004e9810; sources as tagged]:

| Constant | Value in the lobby | Tag |
|---|---|---|
| `VIEW`, `PROJECTION`, `VIEWPROJECTION` | the pass's camera (main, reflected, or the light in the shadow pass) | [known] S 004d9300; light [inferred] S 00769170 |
| `WORLD` | the object's matrix, per draw (effect slot +0x14) | [inferred] S 00509af0 |
| `g_LobbyInstanceMatrix[50]` (register c40) | the batch's world matrices (effect slot +0x24 with the count) | [inferred] S 00509520 |
| `OPACITY` | the item's fade (§3.4), per draw | [known] S 0050b9b0 |
| `CAMERA_POSITION` | eye | [known] S 004d9300 |
| `MAIN_LIGHT`, `LIGHT_COLOR`, `AMBIENT` | `light_dir` (normalised, the direction the light travels), `diffuse`, `ambient` of the zone | [known] S 004f9960 |
| `SHADOW_INTENSITY` | `1 − clamp(shadow_light_intensity, 0, 1)`: zone 0 → 0.6 | [known] S 004f5120; that +0x15c feeds this constant [inferred], as in [`rendering.md`](rendering.md) §3.13 |
| `SHADOW_SCALE.y` | the shadow depth bias; the lobby does not set it, so it is whatever the game's `<Shadows bias>` set (−0.00325) | [inferred] |
| `TIMER` | `.x`, `.y` = the two times `RenderFrame` receives divided by 1000: the frame delta and the application clock (`CLobby::Tick` S 004fb230 passes `(delta, now)`) | [known for the division and the arguments; that `.y` is `now` in seconds is inferred from the RTS convention and from the effects' use of `.y` as a running time] |
| `FOG_SETTINGS`, `MATERIAL` | set, but read by no lobby effect | [known: text of the effects] |

**Fog** is the device's per-pixel linear table fog between `fog_start` and `fog_end` in the fog colour; no lobby
effect computes fog ([`rendering.md`](rendering.md) §3.13). The sky objects switch it off around their draw
(§3.5). The shadow pass switches it off and clears to white. [known] S 004d3ae0, S 004d75b0, S 00518580, S 004f9960

### 3.3 Zone 0: objects, materials and techniques

Zone-0 classes and the KEX material names they carry (count of objects; `lobbyobj.xml`, `scene*.xml`, converted
`.glb`) [known: data]:

| Objects | `lod_class` | Material(s) |
|---|---|---|
| `grass1` 549, `grass2` 573, `grass3` 28, `reet1` 165 (instanced, with fade) | vegetation_minor | `Plants_plm` → `plants_plm` |
| flowers 222, mushrooms 54, `nettle_*` 61 (instanced) | vegetation_minor / major | `default_plm` |
| `fence01`..`08` | building_major | `default_plm` |
| `bush_1_big` 123, `fern_big` 22 (instanced) | vegetation_major | `default_plm_cs` |
| `bush_1_small` 68, `fern_medium` 49, `fern_small` 58 (instanced) | vegetation_minor | `default_plm_cs` |
| `letterbox` | building_major | `default_plm_cs` |
| `cart` | building_major | `default_plm_cs_rs` |
| `tree01..04_export` 24 | vegetation_major | `normalmap_anim` (bark), `hardalpha_anim` (leaves) |
| `house01..03`, `wall01..04`, `taverne01`, `ground` | building_major / terrain | `default_lm`, `parallax_lm` |
| `townhall`, `taverne02`, `taverne03` (outside mesh) | building_major | `default_lm`, `default_lm_rs`, `parallax_lm` |
| `banner01` 4 | building_minor | `banner_cs` (cloth), `default_rs` (pole) |
| `triangleflags` | building_minor | `triangleflags` → not in the table → `default_opacity` |
| `bridge_export` | building_major | `normalmap_sm` |
| `terrain` | terrain | `Terrain` → `terrain` |
| `waterplane` (rank 16777218) | terrain | `water` |
| `sky01_dome`, `sky01_plane_low` (rank 16777217), `sky01_plane_high` (rank 16777216), class `skydome` | default (1) | `skydome`, `skyplane` |
| `ad0`, `ad1` | building_major | `sign ad0`, `Material #478` → `default_opacity` |

Texture stages per material (KEX order, §2.2) and the technique per variant (SP / Sp / sP / sp; `—` = no such
pass) [known: data, `materials.xml`]:

| Material | Stages 0, 1, 2, 3 | std / mirror | shadow pass |
|---|---|---|---|
| `plants_plm` | diffuse+alpha, (same file, unused) | `Plants_plm` (instanced: `Plants_plm_instanced`), transparent `Plants_plm_Opacity`, alpha_sorting | — |
| `default_plm` | diffuse+alpha, (unused) | `Default_plm` (instanced: `Default_plm_instanced`) | — |
| `default_plm_cs` | diffuse+alpha, (unused) | as `default_plm` | S*: `Shadow_TextureMask` (instanced `…_instanced`) |
| `default_plm_cs_rs` | diffuse+alpha, (unused) | SP, Sp: `Default_plm_rs`; sP, sp: `Default_plm` | S*: `Shadow` (no mask) |
| `default_lm` | diffuse, light map (uv1) | `Lightmap` (lobby_shader) | — |
| `default_lm_rs` | diffuse, light map (uv1) | S*: `Lightmap_rs`; s*: `Lightmap` | — |
| `parallax_lm` | diffuse, normal+height, light map (uv1) | SP, sP: `ParallaxMapping_Lightmap`; Sp, sp: `Lightmap2` | — |
| `terrain` | colour (uv0), detail RGBA (uv1), splat weights (uv0), normal+height (uv1) | SP `Parallax_rs`, Sp `Default_rs`, sP `Parallax`, sp `Default` (terrain shader) | — |
| `normalmap_anim` | bark colour, bark normal | SP `NormalMapping_rs_anim`, Sp `Default_rs`, sP `NormalMapping_anim`, sp `Default`; transparent `SoftAlpha` | — |
| `hardalpha_anim` | leaves diffuse+alpha, (unused) | `Hardalpha_anim` in all, transparent `HardAlpha_Opacity_anim` | — |
| `banner_cs` | cloth diffuse+alpha | S*: `Default_rs`, s*: `Default` (banner shader); transparent `HardAlpha_Opacity` | S*: banner `Shadow_TextureMask` |
| `default_rs` | diffuse | S*: `Default_rs`, s*: `Default` | — |
| `normalmap_sm` | colour, normal, baked shadow mask (uv1) | SP `NormalMapping_Shadowmap_rs`, Sp `NormalMapping_ShadowMap_only_rs`, sP `NormalMapping_Shadowmap`, sp `NormalMapping_ShadowMap_only` | — |
| `default_opacity` | diffuse(+alpha) | `Default`, transparent `Default_Opacity` | — |
| `water` | normal map; stage 4 reflection | std only: `Water` (alpha_sorting, but ranked) | — |
| `skydome` | panorama | std, mirror: `SkyDome` | — |
| `skyplane` | clouds, fade mask | std, mirror: `SkyPlane` (alpha_sorting, but ranked) | — |

Consequences for the backdrop [inferred from the tables]:

- **Shadow casters** in zone 0 are only bushes, ferns, the letterbox, the cart and the banner cloth. Buildings,
  trees, terrain and grass cast nothing (their materials have no shadow pass). **Receivers** with shadows on: the
  terrain, the `default_lm_rs` parts of the town hall and taverns, the cart, banners and poles, the bridge, and the
  tree bark only with per-pixel lighting; houses, walls, `default_lm`/`parallax_lm` parts, plants and leaves do not
  receive.
- With per-pixel lighting off the tree bark loses its wind animation (`Default_rs` / `Default`) while the leaves
  keep it (`Hardalpha_anim`): bark and leaves drift apart. Presentation only.
- The water is not reflected (std pass only); everything else with a `mirror` slot is.

### 3.4 What the effects compute (zone-0 techniques)

All effects include `shared.inc` (the copy in `game/gfx/fx_20/`), compile as vs_2_0 / ps_2_0, use row vectors, and
read `L = −MAIN_LIGHT.xyz` as the direction to the light. Samplers: stages 0..3 trilinear and wrapped; stage 4 and 5
point and clamped (stage 4 linear in `lobby_water.fx`); stage 6 wrapped, linear where the effect defines
`FILTER_MODE_6` (all zone-0 effects but the sky). State macros: `ATEST127` = alpha test `> 127/255`; `ABLEND` =
`SrcAlpha, InvSrcAlpha`; every technique uses `ZFunc LessEqual`; no zone-0 technique sets `CullMode` except
`SoftAlpha` (two passes CCW then CW), so the device's cull mode applies (CW, CCW in the reflection pass, §3.6).
[known: `shared.inc` lines 205..307, 654..727; effects as cited]

**`lobby_shader.fx`** (`Default*`, `Lightmap*`, `Hardalpha_anim`, opacity and shadow techniques):

- Vertex: `worldPos = pos · W` (W = `WORLD`, or `g_LobbyInstanceMatrix[BLENDINDICES.x]` instanced); per-vertex
  `diffuse = saturate(N · L) · LIGHT_COLOR` with `N = normal · (float3x3)W`, unnormalised. Planar light map:
  `uvLM = (float4(worldPos, 1) · TEXTURE_TRANSFORM[6]).xz`. Shadow coordinate: `worldPos · TEXTURE_TRANSFORM[5]`.
  [known] `lobby_shader.fx` 78..157
- Pixel (`Default*`): `rgb = tex0.rgb · (diffuse + AMBIENT) [· tex6(uvLM).rgb (plm)] [· shadow (rs)]`,
  `a = tex0.a [· OPACITY]`. [known] 280..326
- `Lightmap` / `Lightmap2` (and `_rs`): `rgb = tex0(uv0).rgb · tex1 (or tex2)(uv1).rgb [· shadow]`, `a = tex0.a`; no
  ambient, no light direction: the baked map holds all lighting. [known] 160..186, 249..278
- `Default`, `Default_plm`, `Lightmap*`, `Hardalpha_anim`: opaque, z-write, alpha test > 127.
  `Default_Opacity`: a depth-only pass (colour writes off, no alpha test), then a blended pass with `ZFunc Equal`.
  `HardAlpha_Opacity(_anim)`: blended, no z-write, no alpha test. [known] 338..471, 590..720
- **Wind** (`_anim`): in object space before W, `s = saturate(dot(float4(pos, 1), float4(pos, 1)) · 0.001) · W._22`
  (so `(|pos|² + 1) · 0.001`: the homogeneous 1 is in the dot product), `φ = frac(0.05 · π · TIMER.y) · 2π`,
  `pos.x += s · sin(W._41 + φ)`, `pos.z += s · cos(W._43 + φ)`; normals unchanged; π = 3.1415297 as written in
  `shared.inc`. Period 1 / (0.05 π) ≈ 6.37 s. W is `WORLD` even in an instanced technique (no zone-0 technique is both).
  [known] 95..104
- `Shadow` / `Shadow_TextureMask(_instanced)`: output `z / w` of the light-space position as grey;
  the mask variants discard where `tex0.a < 0.5`. [known] 189..247, 557..579

**`lobby_parallax_shader.fx`** (trees' bark, `parallax_lm`, the bridge):

- View-space tangent frame (T, B = N × T, N), T the vertex's `TANGENT`: no lobby model has a tangent stream, and
  the object declaration (S 007e6e80: position, normal, colour, blend indices, two uv sets, tangent) has a tangent
  element, so `CMesh::ComputeTangents` S 0076c320 gives every mesh per-vertex tangents at load (per triangle the
  direction of increasing u, `(dv2 · e1 − dv1 · e2) / (du1 · dv2 − du2 · dv1)`, summed per vertex, made orthogonal to
  the normal and normalised) [known]. In the mirror pass the view matrix holds the reflection, so B = N × T computed in
  that view space is the reflection of the true binormal turned around: the normal map's y acts reversed in the
  reflection [inferred from the code]. `uv` offset parallax: `h = tex1.a · 0.06 − 0.03`,
  `uv −= h · (T·v, B·v)` (v = normalised view-space position). Normal `n = normalize(n.x T − n.y B + n.z N)` from
  `tex1.rgb − 0.5`. `diff = saturate(L · n)`; the specular term is multiplied by the constant `specular` = 0. [known]
  56..190
- Lighting mode 0 (`NormalMapping*`): `rgb = c · (AMBIENT + LIGHT_COLOR · diff)`, c = `tex0(uv)`.
  Mode 1 (`ParallaxMapping_Lightmap`): the same times `tex2(uv1).rgb` (uv1 not offset).
  Mode 2 (`NormalMapping_Shadowmap`): `rgb = c · AMBIENT + c · LIGHT_COLOR · diff · tex2(uv1).rgb`.
  `[· shadow]` for `_rs`; `a = tex0.a`; opaque with alpha test > 127. [known] 166..190, 252..400
- `NormalMapping_ShadowMap_only(_rs)`: per-vertex `diffuse = saturate(N · L) · LIGHT_COLOR`, pixel
  `rgb = AMBIENT · c + c · LIGHT_COLOR · diffuse · tex2(uv1).rgb` (the light colour enters twice), `a = 1`. [known]
  193..274
- Wind as in `lobby_shader.fx` for `_anim`. [known] 72..81

**`lobby_plants.fx`** (`Plants_plm*`): §3.4.1.

**`lobby_terrain_shader.fx`** (`Default`, `Default_rs`, `Parallax`, `Parallax_rs`) [known] 47..235:

- Weights `w = tex2(uv0)` normalised by their sum (division by zero where all four are 0); detail `d = tex1(uv1)`;
  `detail = d.g·w.g + d.b·w.b + d.a·w.a + X·w.r` with `X = d.r` (plain) or, in `Parallax*`, the red detail channel
  re-read at a parallax-offset uv (`h = −(tex3.a · 0.04 − 0.02)`, sign opposite to the object shader) and lit
  `X = AMBIENT · r + r · LIGHT_COLOR · saturate(L · n)` with the normal from `tex3`.
- `rgb = saturate(tex0(uv0).rgb [· shadow] · detail · 2)`; a detail value of 0.5 is neutral. Outside the parallax
  channel the terrain gets **no** light-direction or ambient term: its colour map carries the lighting. Opaque,
  z-write, no alpha test.

**`lobby_sky_shader.fx`**: §3.5. **`lobby_water.fx`**: §3.6.

**`lobby_banner_shader.fx`** (`Default`, `Default_rs`, `HardAlpha_Opacity`, `Shadow_TextureMask`): `lobby_shader`'s
pixel shader with a waving vertex shader, in object space before W [known] 79..151:
`f = (pos.y > −1) ? pos.y · 0.1 : 0.1`, `pos.z += f · cos(3 pos.y − 3 pos.x + 1.6 TIMER.y)`,
`pos.x += 0.5 f · cos(2.5 pos.y − 3.4 pos.x + 1.5 TIMER.y)`; normals unchanged. The shadow technique does not wave,
so the cloth's shadow stays still.

**`default_opacity`** (ad boards, triangle flags): `lobby_shader` `Default`: `rgb = tex0.rgb · (N·L · LIGHT_COLOR +
AMBIENT)`, alpha test > 127 on the texture's alpha, no light map.

#### 3.4.1 Plants and grass

- **Instancing** (`instancing="true"` → mesh type 0): the mesh is loaded with `n = clamp(2500 / triangles, 1, 50)`
  copies of its vertices, each vertex carrying its copy number in the 4-byte `BLENDINDICES` slot, and the index list
  repeated with offsets. [known] S 0050b320 At draw time consecutive queue items of the same mesh and submesh with
  opacity 1 are batched: their world matrices are collected (`QueueInstance` S 005097f0) and drawn as one indexed
  call of `count` copies once the mesh, the submesh or the count (> 49, or ≥ n) changes (`FlushInstancedBatch`
  S 00509520). The effect reads the matrix from `g_LobbyInstanceMatrix[BLENDINDICES.x]` (c40). [known for the
  batching; the constant-register path is inferred] Instancing changes nothing visible; a port may use any
  instancing. Grass is alpha-sorted (§2.3), so the queue interleaves meshes by distance and batches stay short.
- **Distance fade** (`CGfxObjStd::CollectRenderItems` S 00518b70) [known]: d = distance from the main eye to the
  object's position; d > `fadeout_end` → not queued; `fadeout_start` < d ≤ `fadeout_end` → opacity
  `1 − (d − start) / (end − start)`, which selects the transparent technique (`Plants_plm_Opacity`, non-instanced);
  else opacity 1. Zone 0: `grass1` 65..75, `grass2` 35..50, `grass3` 20..30, `reet1` 70..80; no other zone-0 class
  has a fade.
- **Render mask** (`lod_class`): object details 0 hides `building_minor` and `vegetation_minor`, 1 hides
  `building_minor`, 2 shows all ([`lobby-world-client.md`](lobby-world-client.md) §3.11). So with object details
  "Low" the backdrop has **no grass, reeds, flowers, mushrooms, small ferns and bushes, banners or triangle flags**.
- **`Plants_plm*` shading** [known] `lobby_plants.fx` 36..176: vertex wind `s = saturate(pos.y · 0.05) · W._22`
  (height-weighted, 0 at the ground), same `φ` and sin/cos offsets as §3.4 (here with the instance matrix's
  `_22`, `_41`, `_43`); view fade `t = saturate(dot(−normalize(worldPos − eye), N) · 1.5)` with the unnormalised
  world normal; planar light map as §3.4. Pixel: `rgb = tex0.rgb · tex6(uvLM).rgb`, `a = tex0.a · t [· OPACITY]`;
  no light direction, no ambient, no shadow. States: blended, **no z-write**, no alpha test. The grass meshes are
  crossed vertical quads whose normals are horizontal (converted `Grass1/2`, `Reet1`: every normal has y = 0), so
  `t` hides each quad seen edge-on or from behind. [known: data]
- `default_plm*` plants (flowers, bushes, ferns, nettles): `Default_plm(_instanced)`, opaque cutouts lit per vertex
  times the planar light map (§3.4), no wind.

### 3.5 Sky dome and cloud planes

- `gfxclass skydome` (`CGfxObjSkydome`, 0xc8): mesh `file`/`mesh`, `rank` (default −1); placed like any object
  (`scene_skydome.xml`: all three at the origin, loaded for zone 0 and again for zone 12). It does **not** follow the
  camera. Its draw callback switches fog off around the draw, so dome and both planes are unfogged. [known]
  S 005186a0, S 005185f0, S 00518580
- Converted mesh extents (`sky01.glb`): dome about ±324 in x and z, y −113..335; `plane_low` at height 73.9
  (±305), `plane_high` at 137.4 (±362). [known: converted data] The converted models are in Godot's axes (the engine's
  z negated): the terrain's colour-map uv (`Terrain.glb`: uv0 = (−z/250 + 0.5, x/250 + 0.5)) agrees with the planar
  light-map projection of §3.2 built from them, the light map being the colour map transposed [inferred].
- `SkyDome`: `rgb, a = tex0(uv0)`, no light. The dome is unranked and unsorted, so it is drawn among the opaque items,
  and nothing lies behind it but the cleared background: its blend comes out as `lerp(fog_color, tex0.rgb, tex0.a)`
  [inferred]. `SkyPlane`: `uv = uv0 · 3 + (frac(TIMER.y / 100), frac(TIMER.y / 200))`,
  `rgb = tex0(uv)`, `a = tex0(uv).a · tex1(uv0).r` (the fade mask `cloudlayer_transition.dds`). Both blended
  **with** z-write. [known] `lobby_sky_shader.fx` 25..103 The high plane uses `cloudlayer2.dds`, the low one
  `cloudlayer.dds`. [known: data]
- Order: the dome among the opaque items, then high plane, low plane, water, sorted items (§2.3). Both planes are
  drawn in the mirror pass too.

### 3.6 Water and its reflection

**Reflection pass** (mirror option = 1) [known] S 004f9960, S 004feeb0, S 004ff880:

1. Shadow map on stage 5 (if shadows are on); `SetWaterClipPlane(true)`: user clip plane 0 = the camera's plane
   (+0x3f8: (0, 1, 0, `waterHeight`), `waterHeight` = −0.1, tweakable `Lobby/WaterHeight`).
2. The camera's virtual slot 0 multiplies the view matrix by the reflection `diag(1, −1, 1)` with translation
   `y = −2 · waterHeight · n.y` = 0.2, i.e. `y' = 0.2 − y`: a mirror about **y = +0.1**. As a D3D plane
   `(0, 1, 0, −0.1)` keeps `y ≥ 0.1`. [known for the matrix; that the fourth float is the plane's `d` and the clip
   keeps the side above is inferred from the layout and D3D's plane convention]
3. `UpdateTransformations` (now the reflected view-projection), reflection target active, cull mode 3 (CCW, the
   mirrored winding), render the zone with pass index 2, cull mode 2, target off, clip plane off, unbind.
   The pass uses the device's fog (the main pass's settings) [inferred: fog is not switched].

**Water surface** (`lobby_water.fx`, `Water`) [known] 47..134:

- Two layers of the normal map: `uv0 = worldPos.xz · 0.1 + TIMER.y · 0.1 · (−0.19, 0.17)`,
  `uv1 = worldPos.xz · 0.1 + TIMER.y · 0.1 · (0.23, 0.19)`; `N = 0.5 · (N0.xzy + N1.xzy)` from `2 · tex − 1`, not
  normalised.
- Reflection: `r = worldPos · TEXTURE_TRANSFORM[4]`; `r.xy += N.xz` (before the projective divide); colour =
  `tex2Dproj(stage 4, r)`. With the mirror on this is the main camera's screen position (the reflected image lines
  up there); with it off the static `skyWaterReflection.dds` at `0.005 · xz + 0.5` with `w = 1`, so the same
  distortion is a whole texture unit: the static reflection is strongly smeared. [known for the formula and both
  matrices; the visual consequence inferred]
- `rgb = lerp(refl, (0.25, 0.65, 0.9999), 0.15) · (saturate(L · N) · LIGHT_COLOR + AMBIENT)`
  `+ (L · N > 0 ? pow(saturate(R · −v), 16) : 0) · (0.5, 0.6, 0.7)`, `R = normalize(2 · saturate(L · N) · N − L)` (not
  a true reflection: N is not normalised and the dot product is clamped), `L = −normalize(MAIN_LIGHT)`.
- `alpha = 0.65 − 0.5 · saturate(dot((0, −1, 0), v))`, v = normalised eye→point (0.65 at grazing angles, 0.15
  looking straight down); blended **with** z-write; the pixel shader writes depth
  `(clip.z + (N.y − 0.75) · 0.01) / clip.w`. Drawn after all opaque items and the clouds (rank 0x01000002).
- Converted plane (`WaterPlane.glb`, Godot's axes as §3.5): y = 0, x −98.7..68.9, z −67.5..61.1. [known: converted data]

### 3.7 Shadow map pass (shadow option 1..3)

[known] S 004f9960, S 0076a3d0, S 00769230, S 005006e0; sizes from [`rendering.md`](rendering.md) §3.13:

- Size: option 1 / 2 / 3 → quality 0.5 / 0.75 / 1.0 → `128 << trunc(q · 4)` = **512 / 1024 / 2048** pixels
  (`ShadowManager::SetQuality` S 00769600, applied when the option changed).
- Light setup: direction = zone `light_dir`; `SHADOW_INTENSITY` from `shadow_light_intensity` (§3.2); the shadow
  manager receives the main camera's eye, view direction, frustum and view-projection, and
  `UpdateMatrices(6, light-map object's world bounds)` builds focus points from the camera frustum inside the zone
  box and an orthographic or perspective light projection (by the manager's flag +0x3a8), then
  `shadowTexMatrix = lightViewProj · texBias`. [known for the calls; the internals of the fit are the RTS
  `ShadowManager`'s, not re-read here: [TODO]]
- Render: fog off, clear white, the shadow view with pass index 1 and the light view-projection; only materials
  with a shadow slot draw (§3.3), writing `z / w`. Then fog on and the old background colour.
- Lookup (`_rs` techniques, `calculateShadow` in `shared.inc`): `s = worldPos · TEXTURE_TRANSFORM[5]`,
  `test = s.z / s.w + SHADOW_SCALE.y`; four point taps at `s.xy / s.w + {0, 1}² · texel`, each 1 if
  `test < depth` else `SHADOW_INTENSITY`, bilinearly weighted by the sub-texel position. The factor multiplies the
  whole lit colour (ambient included). [known: `shared.inc` 349..386]

### 3.8 Camera mode 5 (the menu's fly-by)

[known] S 004ff420, S 004ff220, S 004ff280, S 00510b70, S 00510c80, S 004ff940, S 004d9300 unless tagged:

- Every frame, `UpdatePresetModeKeys(now)` adds one target key and one orbit key for slot 5 at time `now`: target =
  the preset's point, orbit = rotation `q = R_y(ψ) · R_x(θ)` (pitch applied first) with distance **0.1**, where
  `ψ = baseYaw + sin(now_s / 28) / 6`, `now_s` = application clock in seconds. Presets: §3.7 of
  [`lobby-world-client.md`](lobby-world-client.md) (0 and 1 for the main menu's panels 0 and 1; preset 2 is set when
  the lobby is entered online, S 004018e0).
- Each slot is a two-key `TransformInterpolator`: a new key replaces the older one; `Evaluate(t)` blends linearly
  (position) and by slerp (rotation) between the keys, extrapolating outside them. The camera is evaluated at
  `lastTime = now` (`SetLastTime` from `CLobby::Tick` before the frame), the newest key's time, so it returns the
  newest key exactly: **a preset change is a cut**, with no tween. [known for both functions; the cut follows]
- Eye = target + q · (0, 0, −1) · 0.1 (S 004ff940); look-at point = target. So the preset point is in effect the eye
  (10 cm in front of it), the view direction is `q · (0, 0, 1) = (sin ψ cos θ, −sin θ, cos ψ cos θ)` (positive pitch
  looks down) [inferred from `FromAxisAngle` about the y and x unit axes; axis vectors S 008828xx not re-read], and
  the yaw sways by ±1/6 rad (±9.5°) with a period of 2π · 28 s ≈ 176 s.
- Projection: `fov = 72 · (π / 180)` (the scale S 0088a69c = π / 180, written by S 007c3210) times `fovScale` 1.0,
  used as the **vertical** field of view of `PerspectiveFovLH` with aspect = viewport width / height, near 0.1
  (plus the device's near offset), far 500; view = `LookAtLH` (left-handed, y up, up vector chosen automatically by
  `LookAtLH_AutoUp`). [known] S 004d9300, S 004fede0
- Zone: target key value 0 → `interpState[5]` = 0 → zone 0 settings and scene. [known] S 004ff280

### 3.9 When the world is drawn

[known] S 004018e0, S 0060cb80, S 005d98f0, S 005d9900, S 004f5950, S 005e27c0, S 005e8820

- The main loop (`CApplicationEx::FrameTick_InGame`) draws the frame through **`CLobby::Update`** (tick, then
  `RenderFrame`, which draws the menu on top) when `nMenu::System.worldActive` (+0xb5) is set and a `CLobby`
  exists; otherwise through `App_RenderWorldFrame` (the RTS scene, or the menu alone). There is no test of what the
  UI covers: while the flag is set the 3D world is rendered every frame under any panel, opaque or not.
- The flag is written by:
  - every layout loaded through `nMenu::Object::LoadFromXml` S 0060cb80 (the screen and dialog base:
    `nMenu::Object`, `Main` S 005e0bff, `Overlapped` dialogs S 0062e11f, `Splash` S 0060b7df, `Info`, `Exit`):
    attribute `BG_3D`, **default false**. Install: `menumain.xml` and `menucampaign.xml` true, `menusplash.xml`
    and `menusplash_dev.xml` false; every other layout lacks it, so loading it clears the flag.
  - the main menu: "exit to desktop" opens the requester (an `Overlapped`, so its load clears the flag) and sets the
    flag again; "free game" creates or shows the free-game panel and sets it; the panel's `BindWidgets` sets it
    too; "continue", a mission tile (`StartCampaignMap`) and `StartFreeGame` clear it.
  - `CLobby::ProcessModeTransition` leaving the online lobby: back to the main screen → set; to the game screen →
    clear. `Main`'s destructor clears it.
  The options and load panels are not `nMenu::Object` layouts and leave the flag alone [inferred: their load paths
  are not among the callers of S 0060cb80].
- Lobby mode 0 or 1 and camera mode 5 are the backdrop state: no avatar exists, so no ambient emitters, no picking
  target, nothing but the static zone.

### 3.10 The advertising boards

- `ad0` (file position (3.5, 2.3, 21) → world (−21, 2.3, 3.5), yaw −15°) and `ad1` (class `ad1`, file (11, 2.7, 21.5)
  → world (−21.5, 2.7, 11), yaw 150°) stand in zone 0 (`scene_ad.xml`). Each mesh has two materials: `sign ad0`
  (`sign_ad0.dds`, the frame) and `Material #478` (`ad0.tga`, the screen); both fall back to `default_opacity`.
  `ad1.kex` is the same model with `ad1.tga` on its screen. [known: data]
- `ad0.tga`, `ad1.tga`, `ad2.tga` are not files: `CGfxTextureMgr::GetTexture` creates a 1024 × 512 web texture of
  `http://www.funatics.de/sadk/forwarding1.html` (2, 3). [known] S 00504650 The browser sink's `NavigateError`
  (DISPID 0x10f) cancels and fills level 0 with **0xFFFF0000, opaque red**; `DocumentComplete` draws the page body
  into it. [known] S 005c8a30, S 005c7790, S 005c7ba0 Before either event, and when the server answers with some
  other page, the content is not established [TODO].
- Visibility [inferred from the preset geometry, occlusion not checked]: from preset 0 (eye (−24.7, 2.35, −55.9),
  heading 11.9° from +z) `ad0` lies 8.3° left of the view axis at about 59 units; from preset 1 (eye (−7.3, 4.6,
  −45.8), heading −24.0°) 8.4° right of it at about 51 units. Both inside the 72° vertical frustum on any aspect, in
  fog (start 40, end 160), unless a building or tree is in between.

## 4. Update order

Per frame in the world-active branch: `CLobby::Update` → `Tick` (camera `lastTime = now`, render mask from the
`rm*` switches) → `RenderFrame(delta, now)`: §3.2 steps 1..7. Inside each `CGfxView::Render`: cull and collect →
sort → draw (each draw: textures to stages 0..3, effect/technique/pass with state caching, `OPACITY`, `WORLD`,
commit, `DrawIndexedPrimitive`; per pass of the technique). [known] S 004fb230, S 004f9960, S 00508f20, S 00509880,
S 005099c0, S 00509af0

## 5. Inputs and outputs

- Inputs: the five lobby graphics options, the zone settings, the scene objects, the material table, the camera
  preset index (`CLobby +0x80`), the viewport size, the application clock.
- Outputs: the back buffer under the menu; the reflection target (256²) and the shadow map as intermediate
  targets.

## 6. Data-driven parameters

| Source | Keys | Used for |
|---|---|---|
| `lobby/config/materials.xml` | `material name`, `lod shadow pplighting default instanced`, `pass name shader technique transparent_shader transparent_technique alpha_sorting` | §2.1, §3.1 |
| `lobby/config/lobbyobj.xml` `gfxparm` | `file`, `mesh`, `lod_class`, `fadeout_start`, `fadeout_end`, `rank`, `instancing`, `visible` | §3.3, §3.4.1 |
| `lobby/scene/scene1_settings.xml` | `fog_start`, `fog_end`, `fog_color`, `ambient`, `diffuse`, `light_dir`, `shadow_light_intensity`, `light_map`, `light_map_object` | §3.2, §3.7 |
| KEX material | name (lower-cased → material), texture list in order (→ stages 0..3) | §2.2 |
| `lobby/gfx/fx_20/*.fx`, `game/gfx/fx_20/shared.inc` | techniques and constants | §3.4 |
| exe defaults | 72°, near 0.1, far 500, presets, `waterHeight` −0.1, reflection size 256, instancing limits 2500 / 50, sort scale 100.0, fallback reflection matrix 0.005 / 0.5 | as cited |

## 7. Save and load

Nothing is saved; the options are profile values ([`app-shell.md`](app-shell.md) §2.7).

## 8. Determinism notes

Presentation only; nothing here touches simulation state. The fly-by and every shader animation run on the
application clock, so they do not depend on frame rate. `qsort` leaves the order of equal keys open (opaque items
of the same material, mesh and submesh; sorted items at the same distance).

## 9. Notes for a Godot port

Must be exact for the faithful look:

- Material choice by lower-cased KEX material name with the `default_opacity` fallback; textures by KEX list index,
  never by usage; the variant from (shadows on, shader detail high, instanced) and the pass slots, including "no
  pass → not drawn" (casters, reflections, a fade without a transparent pair).
- The light model per technique (§3.4): baked light maps carry the lighting of `default_lm`/`parallax_lm` parts
  with no ambient; plants are lit only by the planar light map; the terrain only by its colour map and the detail
  ×2 blend; per-vertex N·L elsewhere; no specular anywhere but the water.
- The planar light map projection from the zone's `light_map_object` box (§3.2), sampled at world xz.
- Draw order: opaque, high clouds, low clouds, water, sorted transparents far to near; grass without depth writes;
  sky and water with depth writes while blended.
- Fog: linear per-pixel depth fog in the zone colour, cleared to the same colour, sky unfogged.
- Wind, banner wave, cloud scroll and water scroll formulas with `TIMER.y` = seconds of the application clock;
  π = 3.1415297 where the effects use it.
- The camera: vertical 72°, left-handed look-at with the presets of [`lobby-world-client.md`](lobby-world-client.md)
  §3.7, the slow yaw sway, cuts between presets.
- The distance fade bands and the object-details render mask (grass gone at "Low").

Free:

- How instancing is done (the 2500 / 50 replication is an implementation detail).
- Sampler filtering on stage 6 and the shadow map's manual PCF may be replaced by Godot's filters if the result
  matches; the exact shadow-map fit is engine-internal and only its coverage (the zone box) matters.
- The reflection may use a Godot reflection probe or planar reflection as long as the mirror is at y = +0.1, the
  water itself is not reflected, and the fallback (mirror off) shows the static `skyWaterReflection.dds` smeared as
  in §3.6 (or a refined setting fixes that smear: it is a presentation quirk).
- The ad boards' content: the original shows red when the page fails to load; a port shows a texture of its choice
  as a setting, faithful = red.
- The integer sort key's mesh-id overflow and `qsort`'s tie order.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Which of the two `RenderFrame` times lands in `TIMER.x` and `.y` (the decompile aliases them; §3.2) | static: disassembly of the three `BeginRendering` call sites S 004f9f95, S 004fa11f, S 004fa270 back to the loads of the two argument pointers |
| 2 | The pixel format of the web texture and what GDI's `DrawToDC` leaves in its alpha: `default_opacity` alpha-tests at 127, so a page with alpha 0 would draw no board at all (the red fill has alpha 255) | static: `CTexture` vtable +0x20 (the URL texture creator) and its `CreateTexture` format |
| 3 | The content of the web texture before `DocumentComplete` / `NavigateError` (cleared or undefined) | static: the same creator |
| 4 | The shadow manager's fit (`BuildFocusPoints`, orthographic or perspective by +0x3a8, `texBias`) for the lobby | static: S 0076a3d0's callees and the lobby's `ShadowManager` construction in `CLobby::StartUp` |
| 5 | Whether the effect system saves and restores render states around a technique (D3DX `Begin` flags), which decides whether `SoftAlpha`'s cull mode leaks into later draws | static: `CShaderProgram` slot +0x40 (`Begin`) |
| 6 | Whether the ad boards are occluded from presets 0 and 1 by buildings or trees (§3.10) | a render of the remake's port from both presets, or a screenshot of the original's menu |
| 7 | The `lightmap_white.tga` texture (`CLobby +0x64`): which draw binds it (a zone without a light map leaves stage 6 unbound in `RenderFrame`) | static: readers of `CLobby +0x64` |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004f9960 | `CLobby::RenderFrame` | per-frame setup and passes |
| 004fb230 | `CLobby::Tick` | camera time, render mask, `RenderFrame(delta, now)` |
| 004f5290 / 005006e0 | `CLobby::SetLobbyGraphicsOptions` / `LobbyRenderSettings::Apply` | options → variant flags, shadow size, render mask |
| 0050c300 / 0050cb40 | `CGfxShaderMgr::LoadMaterials` / `ctor` | material table |
| 0050ba10 / 0050ba90 / 0050bbd0 / 0050b8c0 / 0050c230 | `GetMaterialTechniquePair` / `NeedsAlphaSort` / `FindMaterialByName` / `GetShaderEffect` / `FindOrAddShader` | material lookup |
| 0050b9b0 | `CGfxShaderMgr::ApplyBoardColorsAndOpacity` | `OPACITY` per draw |
| 0050b5b0 / 0050ad70 / 0050b320 / 00509db0 | `CGfxMeshMgr::LoadMesh` / `BuildSubmeshRanges` / `CreateInstancedBuffers` / `GetSubmeshRenderParams` | meshes, textures, instancing |
| 00504650 / 00504aa0 | `CGfxTextureMgr::GetTexture` / `LoadTexture` | textures, the web boards |
| 00518b70 / 0051d510 / 0051d310 / 0051d6e0 / 0051d580 | `CGfxObjStd::CollectRenderItems` / `CGfxObj::SubmitMeshRenderItems` / `SubmitRenderItem` / `ComputeSortKey` / `DrawRenderItem` | fade, queue, keys |
| 005185f0 / 00518580 / 005186a0 | `CGfxObjSkydome::CollectRenderItems` / `Render` / `ctor` | sky, unfogged |
| 00509880 / 005090f0 / 005099c0 / 00509af0 / 005097f0 / 00509520 | `CGfxRenderer::DrawQueue` / comparator / `SetEffectPass` / `DrawSingleMesh` / `QueueInstance` / `FlushInstancedBatch` | drawing |
| 00508e70 / 00508f20 / 00508e30 / 00508fa0 | `CGfxView::ctor` / `Render` / `SetActive` / `BindProjectedTexture` | views, reflection target |
| 004ff420 / 004ff220 / 004ff280 / 004ff940 / 004fede0 / 004feeb0 / 004ff880 | `CLobbyCamera::UpdatePresetModeKeys` / `AddOrbitKey` / `AddTargetKey` / `GetEyePosition` / `GetScaledFov` / `SetWaterClipPlane` / `ApplyWaterReflection` | camera |
| 00510b70 / 00510c80 | `TransformInterpolator::AddSample` / `Evaluate` | two-key interpolation |
| 004d9300 / 004d9ce0 | `CGraphicDevice::UpdateCameraMatrices` / `UpdateTransformations` | look-at, vertical fov, aspect |
| 004d3ae0 / 004d3a80 / 004d75b0 / 004f5120 | `SetFogRange` / `EnableFog` / `SetBackgroundColor` / `SetInverseClampedFloat_15c` | fog, shadow intensity |
| 0076a3d0 / 00769230 | `ShadowManager::UpdateMatrices` / `BindTexture` | shadow map |
| 004e9810 | `CShaderProgram::ApplySharedParameters` | shared constants |
| 004018e0 / 0060cb80 / 005d98f0 / 005d9900 | `FrameTick_InGame` / `nMenu::Object::LoadFromXml` / `SetWorldActive` / `ClearWorldActive` | world-active rule |
| 005c8a30 / 005c7790 / 005c7ba0 | `CSDKIEEvents::Invoke` / `ClearTextureToRed` / `RenderToTexture` | web textures |
