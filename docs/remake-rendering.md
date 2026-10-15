# Remake renderer: specification and lessons from the viewer

Binding decisions for the renderer of the remake (maintainer, 2026-10-14) and what the testbed viewer established
while reproducing the original's picture. Companion of [`remake-architecture.md`](remake-architecture.md). The
behaviour to reproduce is specified in [`sim/rendering.md`](sim/rendering.md), [`sim/particles.md`](sim/particles.md),
[`sim/animation-models.md`](sim/animation-models.md) §3.15 (settler colours) and
[`sim/ambient-swarms.md`](sim/ambient-swarms.md); this document does not repeat them.

## 1. The viewer is a testbed

`sadk-remake/src/Sadk.Viewer` (model viewer and map viewer) reads the original's files at run time (`.KEX`, `.s2m`,
the settings XML, the encrypted containers) and draws them as the original does. It exists to get the rough shape
right and to find things out; it is **not the game's architecture**:

- it reads the player's installation directly instead of converting it once (`remake-architecture.md` §11) and keeps
  the data in viewer classes instead of a registry (§3);
- it builds a map's picture once at load instead of following the simulation (map objects have no identity, §5);
- its object shader is one file with about fifteen variant defines, the opposite of §2.1 below.

The game is set up separately. The viewer stays for experiments (buildings and settlers on maps: its *Place* tab);
its code is a reference for formulas and pitfalls, not a base to extend.

## 2. Binding decisions

### 2.1 Shader structure

- **No shaders full of `#ifdef` variants.** Shared behaviour (the light model, shadow, fog, gamma handling, the
  reflection lookup, the water haze) lives in include files; each object kind gets a small shader of its own (tree,
  willow, flag, water plant, water lily, duck, ice floe, route buoy, stone, rock, doodad, building, building frame,
  settler, animal, ...) that includes what it needs and adds only its own vertex animation or colour step.
- Shaders are files, not strings in code; Godot's shading language, GLSL allowed (`remake-architecture.md` §11).
- Switches that change at run time (per-pixel lighting, for example) are global shader parameters read by the
  shaders, not variants, so they take effect at once without recompiling materials.

### 2.2 Vertex animation on the GPU

The route buoy bobs in its vertex shader, `y = seaLevel + 0.15 * sin(0.45 * pi * t + x + 143.5 * z)` with the buoy's
world position (`rendering.md` §3.11), as the viewer does, and not per object on the CPU as the original's
`RouteBuoy::UpdateAnimation`. The same holds for every animation the original does in its shaders (trees, willow,
flags, water plants, water lilies, ducks, ice floes).

### 2.3 The original's look by default, refinements as switches

When following the original looks worse than an alternative, the alternative stays as a switch. The settings the
viewer has, with the original's behaviour and the viewer's default:

| Setting | The original | Viewer default | Options |
|---|---|---|---|
| Water reflection | planar mirror view (off on hardware without a reflection target) | planar | off, screen-space (costs more than planar) |
| Reflect objects | everything at the highest detail level | on | off: terrain only |
| Shadows in reflection | the one shadow map is reused | off | on (Godot draws a second shadow map for the mirror camera) |
| Reflection resolution | fixed 2:1 target, 256 x 128 .. 2048 x 1024 | half the window, plus a guard band of a quarter above and below | 0.25 .. 1 |
| Reflection updates, range | every frame, the main view's visible blocks only | every frame, 3000 | every 2nd .. 4th frame; 100 .. 3000 |
| Ice | mirrors the water's reflection picture | only while the water reflection is planar | tied to it, no own switch |
| Sky | a 633-unit dome above the camera, bare horizon | own cloud layer to the horizon | the original's dome |
| Fog | linear table fog on view depth | on | off |
| Depth of field | full blur 25 units from the focus | off, much gentler | on |
| Object lighting | direct light per vertex | per pixel (it looks clearly better) | per vertex |
| SSAO | none | on, intensity 4, radius 4, 0.6 on lit surfaces | off, tunable |
| Texture filtering | trilinear, no anisotropy | anisotropic 16x | trilinear .. 8x, mipmap bias |
| Shadows | one map of at most 2048 x 2048, 2 x 2 taps | 8192 atlas, 4 cascades, soft very low | 2048 .. 16384, hard .. ultra, none .. 4 splits, range, darkness, softness, bias |
| Frame pacing | vertical sync, no limiter | vsync on, no limiter | off, adaptive, mailbox; limits 30 .. 240 |
| Anti-aliasing, upscaling | multisampling from `engine.ini` | off, native | MSAA, FXAA, SMAA, TAA, FSR 1 / 2.2, render scale 0.5 .. 2 |

The shadow defaults are far heavier than the original's single map; settling them is open.

### 2.4 Not reproduced

- The original's terrain tessellation and level of detail (the remake draws the terrain at full resolution and
  culls it in regions, §4.2).
- The fixed-function and low-shader paths: the pre-animated water frames, the radial terrain alpha (it exists only
  below shader level 2, `rendering.md` §3.3) and the `ffp` techniques.
- The caustics pass: as shipped it adds nothing (`rendering.md` §3.5).
- Ambient swarms: dormant in the original (`ambient-swarms.md`); a refined mode that wants flocks needs its own
  models.

### 2.5 Objects and UI

Map objects are instances with an identity shared by simulation and renderer, and UI parts are reusable components
(`remake-architecture.md` §5, §6). The renderer draws them in batches but addresses each object by its identity and
follows the simulation's events.

## 3. Rules of the original that are easy to miss

What the viewer had to get right beyond the formulas of the `sim/` documents:

- **Light in gamma space.** The original computes `light = ambient + lightColour * saturate(N . L) * shadow` and
  `light * texture` in gamma space. Godot works in linear space: compute the light in gamma, hand it over as
  `pow(light, 2.2)` and sample textures as sRGB, so the product comes out as the original's. Godot's own ambient and
  reflected light stay off; the ambient is part of the light function.
- **Where the light is computed** (the original's shaders):

  | Surface | N . L | Shadow |
  |---|---|---|
  | map objects, animals, building frames | per vertex, clamped as COLOR0 | per pixel |
  | stones (`stone_shader.fx`) | per pixel | per pixel |
  | buildings (`house_shader.fx`) | per vertex; the light map blends per pixel by `saturate(1.5 - D)` | per pixel |
  | settlers (`skin_color_mesh.fx`) | per pixel, luminances of ambient and light only | per pixel |
  | terrain, water | per pixel, normal-mapped | per pixel |

- **Normal length.** The original bakes a model's scale `s` into the mesh at load and transforms the normals with
  the inverse transpose, so they are `1 / s` long; the vertex shaders do not normalise after the instance matrix.
  Consequences: a tree placed with scale 0.6 gets 60 % of the direct light, and the animals scaled 0.013 get normals
  77 long, which saturates N . L (fully lit on the lit side). A renderer that keeps scales in transforms must restore
  that length (the viewer's `normal_scale`).
- **Per-shader quirks.** Only `tree_shader.fx` multiplies the direct light by the vertex colour (`tree_shader2`,
  `_winter`, `_willow` have it commented out). `weed_shader.fx` (the wheat fields) lights with `lightColour -
  ambient` and no N . L and tints by `saturate(lerp((0.5, 8, 0.2), 1, scaleY))`. Back faces of double-sided meshes
  are lit with the mesh's own normal.
- **Placement draws.** Yaw and scale of map objects come from one random generator in a fixed creation order
  (`rendering.md` §3.11); the viewer reproduces the first map after a start exactly.
- **Map border.** Beyond the map the water's height overlay clamps to its edge column and stripes the water; the
  reflection view draws neither the border skirt nor the water. The viewer gives the border water no mirror and the
  opacity of deep water in every mode, so the border reads as black ground under a faint sheen.
- **The reflection view** is drawn only while a terrain block at or below the water level or with ice is in view.
  The ice adds its bump offset before the projective divide, so it grows as one over depth and, near the camera,
  reads past the picture's edge (the original's sampler clamps and smears). The viewer caps the offset below depth 20,
  as the water's wave offset, and renders the guard band of §2.3.
- **Resource hints** resolve their good names to the first good of each name in signed id order, so on the shipped
  maps only gemstones sparkle (`particles.md` §3.14).
- **Settler colours** come from a palette drawn per settler with the original's generator; the viewer's palette
  builder reproduces the documented test vector (`animation-models.md` §3.15).
- **Buildings on the map** stand at the centre vertex of their cell, turned about Y by the type's heading (-30 degrees
  for every shipped type); Direct3D's `RotationY(h)` in the original's left-handed world is a turn by `-h` about
  Godot's Y. The house's colour-map variation follows the instance number in creation order (`rendering.md` §3.9).
- **Ground decals** are the `GROUND` mesh in world space, clipped against every terrain triangle under it and laid on
  it 0.01 above. The vertex grid with its odd rows shifted by half a step is a triangular lattice, so its
  triangulation is unique and the triangles under any rectangle can be listed exactly (the viewer's
  `MapGeometry.TerrainTriangles`); the decal takes the terrain triangle's normal [inferred].
- **Settler levels of detail** hang on one skeleton: the definition's `mesh`, `mesh1`, `mesh2` (and `mesh3`) are
  skinned to the same bones and switched by the camera distance at 30, 40 and 60 units, a definition with fewer meshes
  keeping its last (`animation-models.md` §3.14). The meshes' own material textures are never used, and some are not
  in the install (`Scot.bmp`, `bavarian.b3d (Copy).bmp`).

## 4. Engine findings (made on Redot 26.2, the engine until 2026-10-15)

### 4.1 Pitfalls

- **The compatibility renderer** (the one usable without a fast GPU) shows its output linearly, without the sRGB
  step: a flat 0.5 comes out as 55 of 255. Screenshots from it are darker and more saturated; judge colours on
  Forward+.
- **A sky shader that reads `TIME` or `POSITION`** makes Godot render and filter the sky's radiance cubemap again
  every frame, per viewport, even when nothing uses it. Drive the sky from global parameters.
- **A directional shadow map is rendered per camera.** A mirror camera that sees the shadowed sun doubles the shadow
  work; give it a copy of the sun without shadows on a light layer only it sees (directional lights honour the
  camera's cull mask).
- **Transparent materials cast no shadows.** Blended foliage needs a shadow-only, alpha-tested copy.
- **SSAO darkens only Godot's ambient light**, which is black here; it reaches the original's light only through
  `ssao_light_affect` with `ssao_ao_channel_affect = 1`.
- **Reading the screen or depth texture** makes Godot copy them every frame; only the shader variant that needs them
  may declare them, and the screen copy should have no mipmaps.
- **Vulkan uploads DXT1 as RGB** and loses the one-bit alpha the foliage is cut out with; such textures go to the GPU
  decompressed.
- **Winding.** Godot's front faces are clockwise, the original's counter-clockwise on screen: every triangle is
  reversed at import.
- **Shading language:** varyings cannot be written inside helper functions; values computed in `fragment()` reach
  `light()` through varyings; `textureQueryLod` is not portable, so point sampling with the nearest mip level computes
  the level from derivatives.
- **Anisotropic filtering** is set per viewport; a mirror sub-viewport needs it too.
- **Build output** per operating system (`obj/Unix`, `obj/Windows_NT`) when Windows and Linux share the project;
  `.uid` files belong in the repository.

### 4.2 Performance

- Measure with the Visual Profiler (Debugger panel) or `--gpu-profile`; the viewer's *Show performance* gives per
  view GPU time, draw calls and triangles. The GPU clock is no measure: in a close-up the viewer's two views together
  took about 7 % of a frame.
- **Batch by region, never across the whole map.** One mesh per pattern or element over the whole map cannot be
  culled, and the shadow cascades and the reflection draw all of it again; regions of 4 x 4 terrain blocks (16 x 16
  cells) cut a close view from 1.31 million to 236 thousand triangles.
- The light function runs per pixel for the shadow lookup in any case; per-vertex lighting saves the N . L only.
- The mirror view is the biggest single cost after the main view: shadowless sun copy, reduced resolution, update
  rate and range, and no render at all while no water or ice is visible.
- **Skinned settlers are expensive in video memory with Godot's skinning.** Measured in the viewer (compatibility
  renderer, 2026-10-14): 240 settlers as one `MeshInstance3D` per mesh on a `Skeleton3D` each add 211 MB, 176 MB of
  it with the LOD0 meshes alone (8 454 vertices for the carrier, 1 743 and 770 for its two lower levels); Godot skins
  into vertex buffers of each mesh instance [inferred from the numbers]. Forward+ was not measured. The original
  skins in the vertex shader with up to 50 bone matrices per draw (`MAX_BONES`, `animation-models.md`), so its
  settlers cost no memory per instance beyond the bones; the remake's settler shader should skin itself (bone
  matrices from a texture or an instance buffer) instead of Godot's per-instance skinning.

## 5. The viewer's code, for reference

| File | What it holds |
|---|---|
| `Sadk.Formats/Kex/` | `.KEX` reader with the original's load-time bake |
| `Sadk.Formats/Map/` | `.s2m` reader (shipped layout only; the prototype maps' old layout is not read) |
| `Sadk.Formats/Container/` | the encrypted container, the Park-Miller generator, CRC-32 |
| `Sadk.Formats/Settings/` | graphics, map objects, animals, buildings, environment, settler colours and palettes |
| `Sadk.Formats/Effects/`, `Images/` | `.pfx` reader; TGA |
| `Sadk.Viewer/Map/TerrainBuilder.cs` | terrain blocks, pattern layers and transitions, regions, mirror blocks |
| `Sadk.Viewer/Map/MapScene.cs` | water and border, object placement and batching, animals |
| `Sadk.Viewer/Map/MapViewer.cs` | environment, light, sky, reflection camera, settings, performance readout |
| `Sadk.Viewer/Map/ResourceHints.cs`, `Particles/` | the particle system and the effects of a fresh map |
| `Sadk.Viewer/Subjects.cs` | what both viewers share for settlers and buildings: colour tables, palettes, materials |
| `Sadk.Viewer/ModelViewerSubjects.cs` | the model viewer's palette controls and construction display |
| `Sadk.Viewer/Map/Placement.cs`, `MapViewerPlace.cs` | buildings and settlers on a map: placement, ground decals on the terrain, settler LODs |
| `Sadk.Viewer/shaders/` | terrain, water, sky, object, building, settler and particle shaders |
| `tools/KexCheck`, `tools/MapCheck` | whole-install checks (every `.KEX`, `.pfx`, map; the palette test vector) |

## 6. Open

- Buildings and settlers on maps: placement, ground decals and settler LODs work in the viewer; open are military
  flags, the door and work animations, the settlers' animation choice and carried goods, the skinning approach for
  many settlers (§4.2), and what happens to the objects under a new building (the simulation's part).
- What only the simulation brings: goods piles, ships and their wake, projectiles, moving animals, streets and sea
  routes, territory borders, selection markers and build placement, fog of war, building fires and buffs,
  demolition and ruins, effect movies and animation events.
- Reverse engineering that still affects the picture: selection marker styles and the build icon atlas
  (`rendering.md` §10 Q13), the border bobbing (Q12), the ship manager's player-colour values, the loader of a
  building's own particle elements (`particles.md` §10 Q3), the texture particle passes 1 and 2 see (Q1).
- The shadow defaults (§2.3).
