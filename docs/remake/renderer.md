# Remake: renderer

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). The architecture of the remake's world
renderer in Godot: how it follows the simulation, how objects get identity and are still drawn in batches, how
content chooses what is drawn (visual descriptors), how shaders are organised and loaded, how every kind of thing on
the map is drawn, and what is moddable at which level. The testbed viewer (`sadk-remake/src/Sadk.Viewer`) proved
that the picture can be made; this document says how the game's renderer is built, and which of the viewer's parts
it takes over.

Binding inputs: [`../remake-architecture.md`](../remake-architecture.md) (mod model, identity of map objects,
components, C# only) and [`../remake-rendering.md`](../remake-rendering.md) (shader structure, GPU vertex
animation, faithful look with switches, not reproduced features, findings). Behaviour to reproduce:
[`../sim/rendering.md`](../sim/rendering.md), [`../sim/world-objects-rendering.md`](../sim/world-objects-rendering.md),
[`../sim/particles.md`](../sim/particles.md), [`../sim/animation-models.md`](../sim/animation-models.md). Engine facts:
[godot-capabilities.md](godot-capabilities.md). Simulation interface: [sim-boundary.md](sim-boundary.md).

Tags: **[binding]**, **[draft]**, source tags of the cited documents; RE = `../sim/rendering.md`, WO =
`../sim/world-objects-rendering.md`, PA = `../sim/particles.md`, AM = `../sim/animation-models.md`, RR =
`../remake-rendering.md`.

## 1. Principles

From the binding documents:

1. The renderer **follows the simulation**: it draws what the tick records and views say and changes nothing
   ([sim-boundary.md](sim-boundary.md)).
2. **Every object has an identity** shared with the simulation; the renderer batches for drawing but addresses each
   object by that identity and adds, removes and updates it without rebuilding batches (architecture §5, RR §2.5).
3. **Batch by region, never across the whole map** (RR §4.2): regions of 4 × 4 terrain blocks = 16 × 16 cells.
4. **Shaders**: shared behaviour in include files, one small shader per object kind, no `#ifdef` variant soup;
   run-time switches are global shader parameters (RR §2.1). Shaders are files; GLSL only where §7.6 allows.
5. **Vertex animation on the GPU** for everything the original animates in shaders, and for the route buoy that the
   original moves on the CPU (RR §2.2).
6. **The original's look by default, refinements as switches** (RR §2.3); not reproduced: terrain tessellation and
   LOD, fixed-function paths, caustics, ambient swarms (RR §2.4).
7. **Moddable through assets and Harmony**, not through registry entries of its own (architecture §3).

Added here [draft]:

8. **The engine holds what every world needs, `core.game` the match maps** [the maintainer's decision 2026-10-15].
   The world renderer base (`Sadk.Presentation.Rendering`: renderer, layers, environment rig, mirror and
   reflections, settings, globals, orbit camera) and the shared shader includes (the engine asset layer,
   [assets.md](assets.md) §5) are engine code and assets, so no mod is needed for them; `core.game`'s client assembly
   adds the map renderer and its layers, and its shaders and descriptors reproduce the original's look, replaceable
   like any other asset. A later lobby renderer builds on the same base.
9. **Every look must work on all three renderers** (Forward+, Mobile, Compatibility); features that need
   `RenderingDevice` are optional extras with a switch ([godot-capabilities.md](godot-capabilities.md) §2).
10. **Batching technique by count**: tens of thousands of map objects go into region MultiMeshes; hundreds of
    buildings are single instances; thousands of characters go into skinned MultiMeshes. One technique does not fit
    all three.
11. **Per-instance variation never through copied materials** (the viewer's settler palettes and building colour
    offsets): instance data, instance uniforms or atlases.
12. **No game data in code** [binding, maintainer 2026-10-15]. Every value the original's data holds (settings XML,
    maps, scripts, `menu.cfg`, paths, colours, scales) is read from the converted installation and the mods; what the
    files do not give is reported and left out, never substituted. Constants in code are the original executable's
    own defaults and algorithm constants, each with its address, or the remake's own design values, labelled as
    such.
13. **No special cases for one material, type or name** [binding, maintainer 2026-10-15]. What a material needs (the
    mirror picture, an environment cube map, a vertex animation) is a flag in a data table that mods can patch; shared
    services take generic requests; composition points are open registries. A mod must be able to add another
    reflective material, terrain type or object kind without touching the renderer's code.

## 2. Place in the process [draft]

The world renderer base is the engine's (`Sadk.Presentation.Rendering`); the map renderer and its layers are
`core.game`'s client assembly `Core.Game.Renderer` (namespace `Core.Game.Rendering`; [mods.md](mods.md) §11a). Per
frame it runs in steps 3 and 4 of the presentation frame
([sim-boundary.md](sim-boundary.md) §4.2): apply each tick record's events and motion samples, then interpolate,
animate and draw. It runs on the main thread; CPU-heavy preparation (terrain region meshes, ground decals, street
meshes, particle simulation) runs on worker threads, with the results handed to the main thread.

Inputs:

| Input | From | Used for |
|---|---|---|
| tick records (events, motion samples) | `ISimHost.Advance` | creating, removing, changing render objects; movement |
| views | `IWorldView` | per-tick state (construction progress, growth, hit points, military flags), map grids |
| clock | `SimClock` | interpolation factor, simulation-scaled time, real time |
| visual descriptors | presentation documents ([mods.md](mods.md) §6.6) | what to draw for an entry |
| assets | the virtual file system ([assets.md](assets.md) §5) | meshes, textures, shaders, effects |
| camera, selection, placement modes, settings | presentation | views, overlays, switches |

Outputs: the frame, pick results for the next frame's input, world anchor positions for HUD overlays (building
labels, fight markers), presentation events for audio (animation sound events, impacts).

### 2.1 The public surface [implemented]

Other mods use the renderer as the map view does:

```csharp
var rc = new RenderContext(ctx);                              // any mod's ModContext
var map = MapData.Load(rc, "maps/MP_2P_steinfjord.sadkmap");  // or the package's name
var renderer = new MapRenderer(rc, new RenderSettings());
AddChild(renderer);
renderer.Show(map);
AddChild(new OrbitCamera(renderer));                           // or a camera controller of one's own
```

Engine (`Sadk.Presentation.Rendering`):

| Type | What it is |
|---|---|
| `WorldRenderer` | the node that draws a world through its own camera (horizontal field of view 50°, near plane 1): its kind (`WorldKind`), layers (`Layers`, `AddLayer`, `RemoveLayer`, `Layer<T>()`), `Environment` (the rig), `Mirror` (requests), `SetView(focus, eyeDistance)`, `Report`, the presentation clock (`Time`, `Paused`); a world type overrides `GroundHeight`, `Bounds`, `Pick` and its report lines |
| `IWorldLayer`, `WorldLayers` | one part of a world's picture (`Show`, `Clear`, `Frame`, `ApplySettings`, `Report`) and the registry per world kind: `WorldLayers.Register(kind, name, order, factory)` returns a registration the mod disposes in its `OnUnload` |
| `EnvironmentRig`, `WorldLight` | the world environment, the sun and its shadowless copy for the mirror, the mirror view, the sky, the fog that follows the zoom with the far plane and shadow range after it; a world's environment layer feeds it each frame (`SetLight`); `WorldLight.Unlit` is the neutral look without an environment |
| `MirrorRequests` | a layer whose material reads the mirror picture sets the bounds where it does; the mirror view is drawn only in planar mode while one of them is in view (§8.3) |
| `ReflectionVariants` | the shader of a reflective material per reflection mode, from its table's `<Reflection>` children |
| `RenderContext` | the mod set as the renderer reads it: file system, asset cache, frozen registry, presentation documents, a per-context cache (`Shared<T>()`); original references (`[data]\map\textures\x.dds` = `game/map/textures/x.dds`, then the path as written, then the bare-name rule of [assets.md](assets.md) §5.4) to textures and cube maps |
| `OrbitCamera`, `CameraActions` | the free orbit camera on the input actions `engine.camera.*` (§8.1) |
| `RenderSettings`, `RenderSettingsPanel` | the switches of §19 with their defaults (`NotifyChanged` applies them), and a panel of them with the engine's text keys |
| `RenderGlobals` | the global shader parameters (§7.3), declared once by the engine at start |
| `RenderLayers` | the render layers: terrain, objects, water, border, particles, overlays, sun, mirror sun, mirror marker |

core.game (`Core.Game.Rendering`):

| Type | What it is |
|---|---|
| `rc.GameSettings()` | the original's settings XML (`GameSettings`, merged and patched), cached per context |
| `MapData` | one map: the package, the parsed `.s2m`, `world/environment.xml` (else `local_enviroment.xml`; null when neither gives a complete one), the water preset (null when there is none; a preset may be incomplete), `MapGeometry`, the terrain patterns by map pattern id (registry `PatternDef` gfx name → `<Pattern>`), the terrain blocks (`TerrainBlock`: bounds, lowest and highest height, pattern ids); mounts the package's `assets/` as a layer while open |
| `MapGeometry` | grid to world; `HeightAt` is the plane of the drawn terrain triangle (§10.1), used for placement, picking and the camera |
| `MapRenderer` | a `WorldRenderer` of kind `core.game.map`: `Show(map)`, `Clear`, `HeightAt`, `CellAt` |
| `IMapLayer`, `MapLayers` | a map layer (`Show(renderer, map)`) and `MapLayers.Register(name, order, factory)`, the same as `WorldLayers.Register("core.game.map", …)` (core.game: map environment 100, terrain 200, water 300, map objects 400) |

The mode `core.game.mapview {map, back, x, z, yaw, pitch, distance}` shows a map outside a match with a HUD of the
switches; the asset browser opens map packages in it, and `--emit=core.game.mapview?map=…` with `--shot-after` and
`--shot` takes unattended pictures.

## 3. Structure [draft]

The tree below is the renderer of a match. Its parts that every world shares are implemented as the engine's world
renderer base (§2.1: `WorldRenderer`, its layer registry, the `EnvironmentRig` with the mirror view, the settings and
globals, the shader loading through `vfs://`); `MapRenderer` and its layers (map environment, terrain, water, map
objects) are core.game's. The render kinds are the layers of a world kind.

```
WorldRenderer                      Node3D; owns the World3D (scenario) of a match
├─ PresentationClock               alpha, simulation-scaled time, real time; sets the time globals
├─ EventRouter                     tick record events → handlers (registered per event type; mods add)
├─ RenderObjectTable               EntityId (+ sub index) → RenderObject
├─ VisualResolver                  (entity kind, registry entry) → visual descriptor (§5)
├─ RenderKinds                     one instance per kind per match (§4.4)
│  ├─ TerrainKind, WaterKind, BorderSkirtKind, SkyKind
│  ├─ MapObjectKinds               plain, tree, stone, wheat field, gate, route buoy, harbour place, flag
│  ├─ BuildingKind                 + frame, decal, military flag, fires, scaffold, ruins
│  ├─ CharacterKind                settlers, soldiers, oxen; AnimalKind; ShipKind (shared skinning, §9)
│  ├─ ItemKind                     piles, goods in hands, building sites, boats
│  ├─ StreetKind, TerritoryKind, ProjectileKind
│  ├─ ParticleKind                 the effect manager (§16)
│  └─ DecalKind, BuildOverlayKind
├─ Services
│  ├─ EnvironmentService           light, fog, colours from the map and its spheres (§11)
│  ├─ FogOfWarService              exploration textures (§15.4)
│  ├─ MinimapService               the minimap's world picture (§8.5)
│  └─ PickService                  terrain and object picking (§18)
├─ Views                           MainView, MirrorView (planar reflection), shadow settings, preview views
├─ ShaderLibrary                   shader files through the file system, include expansion, cache (§7)
├─ AssetBridge                     converted assets → Godot resources, caches (§6)
└─ RenderSettings                  faithful defaults and switches (§19)
```

Everything numerous is drawn through `RenderingServer` resources (instances, MultiMeshes, meshes, materials) in the
match's scenario; nodes that draw are used for singletons only (camera, `WorldEnvironment`, the sun, the mirror
`SubViewport`). Game elements are still nodes, but nodes that do not draw (§4.6).

## 4. Render objects and batches

### 4.1 The render object table [draft]

- A **render object** exists per simulation entity that has a picture, keyed by `EntityId`; presentation-only parts
  (each end buoy of a sea route, a fire point, a pile slot, a carried item) are keyed `(EntityId, sub)`.
- It records: its render kind, its visual descriptor, its batch slots (one per drawn part and LOD), its per-instance
  state (prev and current samples, fades, clip state), its pick proxy, and flags (visible by fog, hidden by its
  owner).
- `EntityAdded` creates it, state events and per-tick samples change it, `EntityRemoved` hands it to its kind, which
  may keep it alive for an exit (a building's demolition sink, a settler's death sink, a tree's fall) and then
  frees it. The table is cleared at match end.

### 4.2 Batches with stable slots [draft]

A **batch** is one `RenderingServer` MultiMesh with its instance buffer, for one `(render kind, mesh or LOD part,
material, region)`.

- Slot allocation is dense: removing an instance moves the batch's last instance into the freed slot and updates
  that object's slot record (swap-remove). Add and remove are O(1); the buffer stays contiguous;
  `MultimeshSetVisibleInstances` draws only the used part.
- Changes mark a dirty range; once per frame each dirty batch uploads its buffer with `MultimeshSetBuffer`. Region
  batches are small, so whole-buffer uploads are cheap.
- Instance layout: the 3 × 4 transform, `COLOR` and `INSTANCE_CUSTOM` (§7.4).
- Each batch has a custom bounding box: its region's box, grown by the objects' extents and, for moving objects, by
  one step.
- Batch counts are reported in the performance readout (§20).

Buildings and other kinds with few, individually animated objects use **single instances** (`InstanceCreate`) with
instance uniforms instead (§13).

### 4.3 Regions [draft]

Regions are 4 × 4 terrain blocks (16 × 16 cells), the viewer's measured choice (RR §4.2). The size is a setting of
the renderer, not of the data. Static objects are bucketed by their cell once; moving objects (settlers, animals,
ships) change bucket when a motion sample crosses a region border, which happens at a step boundary, never mid-step.

### 4.4 Render kinds [draft]

```csharp
public interface IRenderKind
{
    string Name { get; }                                    // "mapobject.tree", "building", "character", ...
    void Begin(MatchRenderContext ctx);                     // match start: shared resources
    void OnAdded(RenderObject obj, EntityAdded e);
    void OnRemoved(RenderObject obj, EntityRemoved e);      // may keep obj for its exit
    void OnTick(TickRecord tick, IWorldView world);         // per-tick samples and state reads
    void OnFrame(in FrameContext frame);                    // interpolation, fades, LOD, uploads
    void End();                                             // match end: free everything
}
```

- Kinds are registered by name by the engine and by client assemblies of mods ([mods.md](mods.md) §6.7). A visual
  descriptor names its kind (§5.2); a later registration of the same name replaces it, with a log line.
- Kinds share the infrastructure: batches, slot allocation, the pick proxy grid, the presentation random streams,
  the clocks.
- Mods bring new kinds only for new drawing techniques; a new look for an existing kind is a new shader and a
  descriptor entry.

### 4.5 Fog of war and visibility in the shaders [draft]

The original hides an object unless its terrain block (4 × 4 cells) is in view **and** revealed, hides characters
outside the visible block rectangle, hides ships on unexplored cells and buildings without the fog-visible flag,
and darkens everything by the exploration overlay (`CalcFOW`) (RE §3.7). The renderer does this without CPU work per
object:

- `FogOfWarService` keeps three textures for the local player: the **exploration overlay** (the original's
  `(2W+1) × H` "WorldElevationMap": alpha = explored, blue = 1 − normalised height), a **cell mask** (`W × H`) and a
  **block reveal mask** (`W/4 × H/4`, a block is revealed once any of its cells is explored and never again hidden).
  They are updated from `MapChanged(Exploration, rect, player)` for the local player.
- The include `sadk/fow.gdshaderinc` gives `fow_block_revealed(world)`, `fow_cell_explored(world)` and the
  original's `CalcFOW` darkening with `fow_noise.tga`. A kind's vertex shader collapses an instance whose block is not
  revealed (all vertices to one point, so it rasterises nothing); its fragment shader applies `CalcFOW`.
- Frustum culling is Godot's, per batch box.

### 4.6 Proxy nodes [binding, maintainer 2026-10-15]

Most elements of the game are their own nodes one can inspect (maintainer: "most elements of the game should in the
end be their own nodes you can inspect"), without giving up the batches:

- Every building, settler, animal and ship is a plain `Node3D` proxy under the `WorldRenderer`, named after its
  entity, at its interpolated transform. Its exported properties show the entity's state (type, owner, task,
  goods, health) in the remote inspector, and selection and picking can hand it out. It draws nothing: its render
  object (§4.1) holds its batch slots.
- Map objects (tens of thousands of trees and stones) get one proxy node per region (§4.3); the node of a single
  object is made on demand, when it is selected or inspected, and freed again.
- Proxies are made and freed by the same events as render objects (`EntityAdded`, `EntityRemoved`) and keep no state
  of their own, so they cannot drift from the simulation.
- The proxy node classes are `core.game`'s renderer's own node types; mods may define node types of their own
  ([mods.md](mods.md) §7.1).

### 4.7 Visibility per object [the maintainer's direction 2026-10-15; draft]

Godot culls a `MultiMesh` only as a whole, by its box, so an object outside the view is still drawn while its region
is partly in view. Every placed object (map objects, settlers, animals, ships) therefore gets a visibility notifier,
Godot's own (`VisibleOnScreenNotifier3D` under the proxy node of a kind that has one, §4.6; for map objects, which have
no node each, the same notifier without a node through `RenderingServer`). What it switches:

- **Out of view**: the object's slots leave their batches (swap-remove, §4.2), so its vertices are not processed at
  all, and its CPU work stops: interpolation, attachments, animation events, sounds, emitters. **Back in view**: its
  slots return with its current state; the pose is computed from the clock (§9), so it shows the right point of its
  clip at once.
- **The notifier's box** is the object's bounds grown by what the notifier cannot see: a margin for its answer
  arriving one frame late ([godot-capabilities.md](godot-capabilities.md) §6); for a moving object the motion of one
  tick, so its box moves once per tick, not per frame; and the reach of its shadow towards the sun (height over the
  tangent of the sun's elevation), since notifiers ignore shadow passes and an object just outside the view may cast
  a shadow into it.
- **The mirror counts**: the notifiers lie on a layer the mirror camera sees as well, so what shows only in the
  reflection stays drawn.
- Region batches stay (they keep the draw calls few) and Godot still culls whole regions; the notifiers drop what lies
  outside the view within the visible ones. Buildings (§13) are single instances, which Godot culls one by one
  already; their notifier switches their animation players.
- **To measure** before it is the default for every kind: the notifiers' cost in Godot's cull pass against the saved
  vertex work and uploads (a panning camera moves objects in and out of batches), on the maintainer's GPU (§20). Map
  objects come first, as they are the only kind drawn today.

## 5. Visual descriptors

### 5.1 What they are [draft]

A **visual descriptor** says how an entry of the registry is drawn: model, textures, shader, render kind,
animations, scales, flags. The original keeps this information in its settings XML, separate from the property
scripts, and links the two by name only (RE §2.5, §3.9, §3.11; AM §6): the remake keeps those XML schemas as the
descriptor format and extends them.

| Document (logical path under `game/`) | Entries | Linked from the registry by |
|---|---|---|
| `settings/map_objects.xml` `<LandscapeElement>` | trees, stones, doodads, wheat fields, flags, harbour places, route buoys, gates, chests, spawn markers | deposit, doodad and spawn-point gfx name; fixed names (`z_flag_00`, `z_harbor_flag_00`, `z_harbor_00`, `RouteBuoy`); chest doodad ids. Exact, case-sensitive |
| `settings/buildings.xml` `<Building>` | buildings, ruins, frames, door and work clips, farm animals, effects | `<tribe name>_<gfx name>` [inferred] |
| `character/settler_config.xml`, `settler_animations.xml`, `color_slots.xml` | settlers, soldiers, oxen; animation sets; colour ramps | `<tribe name>_<character name>` (character name per settler type, [assets.md](assets.md) §9 item 1) |
| `settings/animals.xml` | animal species | animal gfx name |
| `settings/ships.xml` | ships per tribe, status meshes | tribe name |
| `settings/items.xml` | goods as objects | good name |
| `settings/projectiles.xml`, `effectMovies.xml`, `decals.xml` | projectiles, effect movies (sacrifices), selection decals | names in the registry and in code |
| `settings/terrain_static_data.xml` `<Pattern>` | terrain patterns; blend rank = order in the file | pattern gfx name |
| `settings/graphics.xml` | map scaling, water and its presets, streets, skydomes, shadows, post effects, landscape | fixed |
| `settings/local_enviroment.xml`, `daytimes.xml`; the map's environment | light, fog, colours | the map |

They are presentation documents: merged across layers, patched by XPath, then parsed ([mods.md](mods.md) §6.6). A mod
adds a `<LandscapeElement>` in its own `game/settings/map_objects.xml`, which is merged into the base document, or
patches an attribute of an existing one.

### 5.2 Extensions to the original schemas [draft]

Optional attributes the remake understands on every descriptor element; without them the original's behaviour holds:

| Attribute | Meaning | Default |
|---|---|---|
| `renderKind` | name of the render kind (§4.4) | from the element's `type` (`tree` → `mapobject.tree`, ...; none → `mapobject.plain`) or the document |
| `shader` | an original `.fx` name **or** a remake shader path | the original's attribute, resolved through the shader map (§7.5) |
| `mesh`, `model`, `frame`, `texture`, ... | any logical path of the right kind; the extension is a hint ([assets.md](assets.md) §5.2) | the original's paths |
| `shadowCast`, `shadowReceive`, `forceShadowPass` | as the original (the viewer ignores `forceShadowPass`; the game reads it) | the original's |
| `lodRanges`, `scale` | for kinds whose original values were code constants | the original's constants (settler scale 1.2 and LOD ranges 30/40/60 are in `settler_config.xml` and are read from there) |

### 5.3 Resolution [draft]

`VisualResolver` turns `(entity kind, registry entry)` into a descriptor with the original's rules (the table
above), implemented in core.game's client assembly per entity kind, replaceable by mods (Harmony, or registering a resolver
for their own entity kinds). A miss is logged once per name; the faithful mode then draws nothing, as the original
does, the refined mode a placeholder.

## 6. From assets to Godot resources [draft]

- **Meshes**: a converted `.glb` (or a mod's `.gltf`, or a raw `.kex`) is read into the renderer's own mesh data
  (surfaces with vertex arrays, material slots, bone index lists, sub-mesh names) and turned into one
  `RenderingServer` mesh per sub-mesh and variant. Not into node trees: glTF scene nodes are only an intermediate.
- **Vertex channels**: position, normal, UV (diffuse), UV2 (light map), `CUSTOM0` (bone indices, or the colour-map
  texel for buildings), `CUSTOM1` (bone weights), `COLOR` (vertex colour, used by trees). Custom channels are
  declared with their explicit format flag ([godot-capabilities.md](godot-capabilities.md) §3).
- **Skeletons and animations**: kept as C# tables for the GPU skinning of §9 and for CPU queries (attachment bones);
  no `Skeleton3D`.
- **Textures**: `Texture2D` per logical path; colour-index maps flagged for point sampling.
- **Caches**: per logical path and file-system generation; built resources go to the disposable cache
  ([assets.md](assets.md) §3); entries from a map's layer are freed with the match.

## 7. Shaders and materials

### 7.1 The library [draft]

The shared includes `sadk/*` and the sky shaders come with the engine (`engine/shaders/`, [assets.md](assets.md)
§5.3a); the kinds' shaders are `core.game`'s, under `core.game/assets/shaders/` (logical `shaders/...`):

| File | Holds |
|---|---|
| `sadk/globals.gdshaderinc` | every `sadk_*` global parameter, declared once (the viewer declares them in seven places) |
| `sadk/axes.gdshaderinc` | the original's axes against Godot's (`(x, y, −z)`), D3D `RotationY(h)` = Godot turn by `−h` |
| `sadk/gamma.gdshaderinc` | light computed in gamma, handed to Godot as `pow(x, 2.2)` |
| `sadk/light_original.gdshaderinc` | the object light model: vertex half (`N · L` clamped as COLOR0, `normal_scale`) and pixel half (`ambient + direct × shadow`), with the per-pixel switch `sadk_pixel_light` |
| `sadk/shadow.gdshaderinc` | `mix(sadk_shadow, 1, ATTENUATION)` and the no-receive form |
| `sadk/fow.gdshaderinc` | §4.5 |
| `sadk/fog.gdshaderinc` | the original's linear table fog on view depth, and the particle alpha fade on the same range |
| `sadk/mirror.gdshaderinc` | `is_mirror_pass()` from `CAMERA_VISIBLE_LAYERS` (§8.3), the projective lookup into the mirror picture, the capped 1 / depth offset |
| `sadk/reflection.gdshaderinc` | the view a reflecting pixel needs (`SadkView`, `sadk_view(...)`); `sadk_reflect(view, world, normal, offset)` comes from one of `reflection_planar` (the mirror picture), `reflection_ssr` (traced through the screen and depth textures, the sky where the ray leaves the screen) and `reflection_none` (nothing found), picked by the reflection mode through the material's `<Reflection>` variants |
| `sadk/haze.gdshaderinc` | the water haze of rocks, water plants, lilies and ducks |
| `sadk/instance.gdshaderinc` | decoding `INSTANCE_CUSTOM` and `COLOR` per the layout of §7.4 |
| `sadk/skin.gdshaderinc` | GPU skinning from the animation texture (§9) |
| `sadk/wind.gdshaderinc`, `sadk/flagwave.gdshaderinc` | the tree wind and the flag wave, shared by their kinds |

Object shaders, one per kind of the original's shaders (`game/gfx/fx_20/*.fx`, RE §3.11), each including what it
needs:

| Group | Shaders |
|---|---|
| map objects | `objects/doodad`, `objects/sign`, `objects/tree`, `objects/tree2`, `objects/tree_winter`, `objects/willow`, `objects/wheat` (weed), `objects/stone`, `objects/rock`, `objects/rock2`, `objects/waterplant`, `objects/waterlily`, `objects/duck`, `objects/icefloe`, `objects/flag`, `objects/harborflag`, `objects/routebuoy`, `objects/gate`, `objects/glow` (additive) |
| buildings | `buildings/house`, `buildings/house_cut` (construction and upgrade, both sides), `buildings/frame`, `buildings/decal`, `buildings/soldierflag`, `buildings/ruin` |
| characters | `characters/settler`, `characters/donkey`, `characters/animal`, `characters/ship`, `characters/ship_status` |
| goods | `items/item` |
| terrain | `terrain/<type>` and `terrain/<type>_blend` for the seven pattern types: plain, under water, swamp, specular, lava 0, lava 1, ice — replacing the viewer's run-time `type` branch |
| water | `water/water`, `water/water_border`, `water/water_ssr` (refined option) |
| sky | `sky/sky` (the remake's cloud layer), `sky/sky_original` (the 633-unit dome) |
| particles | `particles/flat`, `particles/spherical`, `particles/volume`, `particles/additive` (passes 0..3; 4 and 5 unused) |
| world overlays | `streets/street`, `streets/crossing`, `streets/route`, `streets/buoys`, `border/border`, `overlays/build_icons`, `overlays/decal` (selection) |
| shadows | `shadow/cutout_<kind>` for blended casters (only with the original's blended foliage, §12): alpha-tested, shadow only, with the kind's vertex animation |

**Render states** (blend mode, culling, depth writes) belong to the file: a kind that the original draws in several
blend modes gets one thin wrapper per mode (`objects/doodad.gdshader`, `objects/doodad_blend.gdshader`, both
including `objects/doodad.gdshaderinc`). The viewer's wrapper files are this shape. A wrapper sets
`render_mode` and includes; it contains no `#define`.

**No matrices as varyings** [implemented 2026-10-15]: Forward+ and Mobile give a shader 32 varying slots (a `vec4`
each, a `mat4` four); the Compatibility renderer does not count them. A shader over the limit compiles there and fails
on Forward+ with "Too many varyings used in shader (33 used, maximum supported is 32)", and every material using it
draws white. The view a reflecting pixel needs is therefore built in the fragment function from Godot's built-ins,
`SadkView view = sadk_view(VERTEX, VIEW_MATRIX, INV_VIEW_MATRIX, PROJECTION_MATRIX, INV_PROJECTION_MATRIX)`, and handed
on as a parameter (`sadk_reflect(view, ...)`, a terrain type's `terrain_surface(view, ...)`). A shader change is
checked on Forward+ before it is merged.

### 7.2 Loading [draft]

- Shaders load through the file system's `vfs://` loader [implemented]: `rc.Assets.Load<Shader>("shaders/x.gdshader",
  AssetKinds.Shader)` and `ResourceLoader.Load<Shader>("vfs://shaders/x.gdshader")` give the same resource, and
  Godot's own preprocessor resolves `#include "vfs://shaders/sadk/globals.gdshaderinc"` or an include relative to the
  including file through the file system, once per file, with errors listed per include file and line
  ([godot-capabilities.md](godot-capabilities.md) §4).
- A mod that replaces `sadk/light_original.gdshaderinc` changes the light of every object shader; one that
  replaces `objects/tree.gdshader` changes trees only. A shader recompiles when one of its includes changes.
- Shaders compile at match load (behind the loading screen) for every descriptor of the match, so no frame stalls.

### 7.3 Global parameters [draft]

Declared by the engine once at game start (`RenderGlobals`, `RenderingServer.GlobalShaderParameterAdd`; the rendering
server lists globals only in the editor, so the class tracks what it declared) and set by the services; the shaders
read them through `vfs://shaders/sadk/globals.gdshaderinc`, which declares each once. A mod may declare globals of
its own and removes them in its `OnUnload`. Switches are globals so they apply at once without recompiling (RR §2.1).
Implemented so far: the light, sky, time, mirror, map and animation groups, `sadk_fog_start` / `sadk_fog_end` (the
map's unscaled fog, used outside the map, §11.1) and `sadk_pixel_light`.

| Group | Globals |
|---|---|
| light | `sadk_light_color`, `sadk_ambient`, `sadk_shadow`, `sadk_light_dir` (in the original's axes), `sadk_light_lum`, `sadk_ambient_lum` |
| fog and sky | `sadk_fog_start`, `sadk_fog_end`, `sadk_background`, `sadk_sky_tex`, `sadk_sky_rot`, `sadk_sky_apex` |
| time | `sadk_time` (simulation-scaled presentation time; stops when the game is paused), `sadk_real_time`, `sadk_tick_alpha` |
| map | `sadk_map_rect`, `sadk_water_level` (from the geometry; the viewer's shaders default to −0.1), `sadk_height_scale` |
| fog of war | `sadk_fow_overlay`, `sadk_fow_cells`, `sadk_fow_blocks`, `sadk_fow_noise`, `sadk_fow_enabled` |
| mirror | `sadk_mirror_tex`, `sadk_mirror_vp`, `sadk_mirror_enabled`, `sadk_mirror_min_depth` |
| players | `sadk_player_colors` (an 8 × 1 texture of the player colour table from `menu.cfg`) |
| animation | `sadk_anim_speed` (`graphics.xml <Animations globalSpeed>`, 1.8) |
| switches | `sadk_pixel_light`, `sadk_original_sky`, `sadk_reflect_objects`, ... (§19) |

Shaders read `sadk_time` instead of Godot's `TIME`, so animation in shaders stops with the game and runs at its
speed. Whether the original's shader timer (`TIMER.y`) is real or simulation time is open (WO §10 Q7); faithful mode
follows whichever it is.

### 7.4 Per-instance data [draft]

| Kind | `COLOR` | `INSTANCE_CUSTOM` |
|---|---|---|
| map objects | rgb = owner colour (flags), a = level fade (depletion) | x = growth (trees, wheat), y = fall angle / sway phase, z = flags (shadow-only, mirror-excluded), w = free |
| characters | rgb = player colour, a = flags | x = clip index, y = clip start time, z = palette slot, w = LOD and state flags |
| goods | — | x = flags |
| particles | rgba = colour × opacity | xy = atlas cell, z = size, w = rotation or stretch |

Buildings and other single instances use instance uniforms (Godot allows 16 per shader): colour-map offset, clip
height in model space and side, construction stage, two animation layers (§13).

**Normal length**: the original's normals are `1/s` long for a model of scale `s` (RE §3, RR §3). Instead of a
material uniform per scale (the viewer's `normal_scale`), the light include derives `s` from the instance matrix's
column lengths and restores the length, so instances of one batch may differ in scale.

### 7.5 The shader map [draft]

`shaders/fx-map.xml` (a presentation document) maps each original `.fx` name to the remake shader per blend mode
and the default render kind, so the original's descriptors keep working unchanged and a mod's new descriptor can
name either.

```xml
<ShaderMap>
  <Fx name="tree_shader.fx"   kind="mapobject.tree" opaque="shaders/objects/tree.gdshader"
      blend="shaders/objects/tree_blend.gdshader" shadow="shaders/shadow/cutout_tree.gdshader"/>
  <Fx name="stone_shader.fx"  kind="mapobject.stone" opaque="shaders/objects/stone.gdshader"/>
  <Fx name="weed_shader.fx"   kind="mapobject.wheat" opaque="shaders/objects/wheat.gdshader"/>
  <!-- one entry per .fx of game/gfx/fx_20 -->
</ShaderMap>
```

### 7.6 GLSL [draft]

GLSL through `RenderingDevice` is allowed for optional features that switch off on the Compatibility renderer:
compositor post effects of the refined look (an original-style depth of field, colour grading), compute paths that
speed up something the shading-language path also does (skinning, particle expansion). The original's look never
depends on them.

## 8. Views and passes

### 8.1 Camera [draft]

- The original's projection: **horizontal** field of view of 50° at every aspect, near 1, far 500 (CI §3.1). Godot's
  `Camera3D.KeepAspect = Width` makes its field of view horizontal ([api]). The far plane and the zoom range are
  switches of the refined look.
- The camera controller (zoom steps, tilt, yaw offsets, smoothing, border clamp, cutscene splines) is presentation
  code outside the renderer (CI §3.2, §3.7); the renderer only takes the pose and is told the ground focus point and
  the eye distance (`MapRenderer.SetView`), which the environment blend and the fog are measured from.
- **Controls are input actions** (Godot's `InputMap`): whoever owns a control declares the action with its default
  keys and buttons, unless an action of that name exists already (a player's own binding wins); a mod erases the
  actions it declared when it unloads. Every control can therefore be rebound. The engine's orbit camera
  (`OrbitCamera`, used by the map view and available to a map editor) uses `engine.camera.forward`, `back`, `left`,
  `right`, `turn_left`, `turn_right`, `zoom_in`, `zoom_out`, `drag` and `orbit`, declared by the engine at start.
  Saving a player's bindings belongs to the settings, later.
- Cutscene splines are converted to tracks by running the cutscene scripts against a recording `cutscene` table
  ([lua.md](lua.md) §6.2) and are sampled with the original's Hermite rule.

### 8.2 Draw order [draft]

The original's pass order (RE §3.1) mapped to Godot: sky; opaque terrain; unexplored terrain black (by the fog
shader); terrain blend layers (transparent, render priority by pattern rank); streets, crossings and routes
(transparent, pulled toward the camera by the original's 0.1 near-plane bias, done in the vertex shader instead of
writing depth); buildings with house decals before them; map objects; characters; goods; animals; ships; single
meshes; selection decals; map objects clipped at the water and then the water itself (after blended objects, RR §4.1);
particles; the build overlay. Godot sorts transparent objects by distance; render priorities enforce the pass
boundaries where the original's order matters.

### 8.3 The mirror view [draft]

As in the viewer, with one change:

- a `SubViewport` with a camera mirrored about the water plane (mirrored eye, forward and up; the picture comes out
  flipped left to right), its own environment with its own copy of the sky material (the original dome mirrors the
  camera's forward direction there); fogged by its materials as the original fogs its reflection view (§11.1);
  anisotropy and mip bias set on it too;
- a copy of the sun without shadows on a layer only the mirror camera sees (no second shadow map), unless "shadows in
  reflection" is on;
- a guard band of a quarter above and below; the original's lookup offsets are fractions of the screen, so the
  planar lookup scales their vertical part by `1 / (1 + 2 × 0.25)` (`sadk_mirror_offset_scale`) to keep the
  original's ripple in the taller picture [implemented 2026-10-15]; resolution, range and update rate as switches; not drawn while no
  terrain block at or below the water level or with ice is in view;
- **requests instead of materials** [implemented]: the mirror view knows no water or ice. Each layer whose material
  reads the picture states the world bounds where it does (`MapRenderer.Mirror.Set(layer, boxes)`): the water layer
  the blocks at or below the water level while the planar reflection is on, the terrain layer the blocks holding a
  pattern whose terrain type is marked `mirror="true"` in its type table, a mod's glass its own boxes. The view is
  drawn while any requested box is in view, as the original draws its reflection scene only while water or ice is
  visible (Scene::Render S 006836b0).
- **new**: the mirror camera's cull mask contains a marker layer; `is_mirror_pass()` in `sadk/mirror.gdshaderinc`
  tests it through `CAMERA_VISIBLE_LAYERS` and discards geometry below the water. The viewer's test "camera below the
  water" breaks for a camera that dips under the surface.
- **Cheaper first** (maintainer, 2026-10-15): the mirror ends at the fog (§11.1); its content follows the original's
  detail levels (terrain; + buildings; + characters; everything, R §3.1), small objects (grass tufts, small stones)
  are left out below the top level; resolution and update rate stay settings.

**Screen-space mode** (`Reflections mode="ScreenSpace"`, the remake's own) [implemented 2026-10-15]:
`sadk/reflection_ssr.gdshaderinc` marches the reflected ray through the screen and depth textures and takes the sky
for the reflected direction where it leaves the screen. To ripple like the planar picture, the ray starts from the
mirror plane's point seen at the screen position moved by the original's offset; moving only the colour fetched at
the hit would leave the outlines straight, a clean mirror. What lies outside the screen (hills above its top edge) is
never found, so open water shows more sky than in the planar mode. Godot's own screen-space reflection cannot serve:
opaque materials only, Forward+ only, no lookup offsets ([godot-capabilities.md](godot-capabilities.md) §2).

Alternatives weighed on 2026-10-15:

- **Pixel-projected reflections** (a later option, Forward+ and Mobile only): every on-screen point above the water is
  projected to where its mirror image lands on screen and written there by a compute pass; the water reads that
  picture, and pixels without a projected point take the sky's colour for the reflected direction (the sky is a
  function of the direction). Exact positions for everything on screen, no second render; weaker at the top edge of
  the screen, where the reflected objects lie outside the picture. It needs a `CompositorEffect` with compute shaders
  (about 500 lines) and the foliage in the opaque pass (cutouts, §12), or the previous frame's picture.
- **Not used**: flipping the screen picture at the shoreline (correct only for a camera looking level across the
  water; from above the water would show mirrored land where the sky belongs); box-projected cubemaps with
  screen-space rays for near objects (the near-shore objects the map camera mostly sees in the water are where the
  box approximation is worst, and screen-space rays miss everything above the screen's top edge; not clearly cheaper
  either, since probes need recapturing when trees fall or buildings rise).

### 8.4 Shadows [draft]

One directional light with Godot's cascaded shadow map. Casters follow the descriptors (`shadowCast`,
`forceShadowPass`); blended casters get their shadow-only cutout copy; characters cast through their skinning
shader (the shadow pass runs the same vertex code). **Default: a light preset** close to the original's single map of
at most 2048 × 2048 (one or two cascades, 2048 to 4096, the lightest soft filter). The viewer's 8192 atlas with four
cascades costs far more and, as the maintainer found (2026-10-15), improves the picture very little; the heavier
presets stay as options, not defaults. The GPU time saved goes to the smooth terrain (§10.2).

### 8.5 Minimap and previews [draft]

- The minimap's world picture is a top-down render of terrain and water into a 512 × 512 target, as the original
  makes it (`RenderOverviewTexture`, RE §5), redone when heights or patterns change; territory, objects and symbols
  are drawn by the UI from views.
- Object previews in the UI (a building in its panel) render through one shared preview `SubViewport`.

### 8.6 Post effects [draft]

Faithful: depth of field only, off by default (RR §2.3); the original's bloom never reaches the screen. Refined
switches: SSAO, anti-aliasing, upscaling, a gentler depth of field (Forward+).

## 9. Characters: GPU skinning [draft]

Godot's skinning costs video memory per instance (240 settlers: 211 MB, RR §4.2). Settlers, soldiers, oxen,
animals, ships and animated building parts use one skinning path of their own instead:

- **Animation texture** per skeleton: every clip of that skeleton is sampled at its own key times (the converted
  keys are evenly spaced) into 3 × 4 bone matrices, one row per frame, three RGBA32F texels per bone. The settler
  skeleton has 46 bones; a few thousand frames over all clips take a few MB. A clip table gives the first row, the
  frame count, the length and the loop mode.
- **Skinning** in `sadk/skin.gdshaderinc`: bone indices and weights from `CUSTOM0` / `CUSTOM1`, the clip from the
  instance data, time from `sadk_time × sadk_anim_speed × clip speed`; two frames fetched and blended. Vertex
  texture fetch works on all three renderers.
- **The original's pose pools**: looping clips (slot types 0 to 3) play on a shared pool instance, so every walker is
  in phase (AM §3.9). In faithful mode a looping clip's time is the global time, which gives exactly that; a
  refined switch adds a per-instance phase. Play-once clips (types 4 to 9) start at the event's time and hold their
  last key. No cross-fade: a clip change is a cut, as in the original.
- **Batches**: per `(character mesh, LOD, region)`; per frame, instances in visible regions are interpolated on the
  CPU (`prev`, `current`, `Alpha`; route splines for street walkers, height snap, evade offset) and their LOD band
  chosen by distance (settler LOD ranges from `settler_config.xml`, fewer meshes keep the last). A few thousand
  instances per frame are cheap in C# with arrays of structs.
- **Palettes**: one 1024² palette atlas of 16 × 16 blocks, as the original's; a settler's block is drawn when it is
  added, with the palette generator (presentation stream, [sim-boundary.md](sim-boundary.md) §8), and freed when it
  is removed.
- **Attachments** (goods in hands, tools, boat cargo): the attachment bone's matrix is evaluated on the CPU from the
  same animation table for that one bone and written into the item's instance.
- **Animation events** (`<Sound>`, `<Particle>`, `<Item>` children with start times, AM §3.12) are fired on the CPU
  when a character's clip time crosses them; faithful mode fires a looping clip's events once for all sharers of its
  pool, as the original does.
- Animals, ships and oxen use the same path with their own shaders (`animals.fx`, `ships.fx` player-colour weight,
  `donkey.fx`).
- **Unseen characters cost nothing**: their visibility notifier takes them out of their batches (§4.7), so neither
  their vertices nor their interpolation are processed; the pose is computed from the clock in the vertex shader, so
  a character shows the right point of its clip the moment it comes back into view.

## 10. Terrain [draft]

### 10.1 The mesh

- The mesh math is the viewer's (`TerrainBuilder`), split into a pure builder (vertex and index arrays per region
  and pattern, no Godot) and a thin Godot backend: the original's triangle tables, four-fold subdivision, solid and
  blend patches per 4 × 4 block with transition-mask UVs, under-water tint, the pattern order of
  `terrain_static_data.xml` (RE §3.3).
- One mesh per region with one surface per pattern; materials per pattern with the pattern type's shader (§7.1).
  With the level of detail of §10.3 the terrain is drawn as instanced blocks with the pattern layering in the
  shader instead; these region meshes are then the fallback.
- `MapChanged(Heights | Patterns, rect)` rebuilds the regions touched plus one block of margin on a worker thread;
  the result replaces the region's mesh on the main thread. Ground decals, streets and object heights in the
  rectangle are re-laid.
- Unexplored blocks are drawn flat black by the fog include, with depth.
- **One height function**: the renderer, the picking and object placement use the plane of the drawn terrain
  triangle (the viewer's `MapGeometry.TerrainTriangles`). The viewer's `HeightAt` interpolates bilinearly per row
  and lets objects float or sink slightly; which sampler the original uses to place objects is still open (viewer
  notes). With the smooth surface of §10.2 this function is `TerrainSurface.HeightAt`.

### 10.2 Smooth terrain (the refined look's main upgrade)

The maintainer's judgement (2026-10-15): the heavy shadow and quality settings change the picture very little; the
place where the remake can really look better is smoother terrain.

**What the original draws.** Heights sit on the fine vertex grid, one vertex every 1.5 units (`graphics.xml <Map
scaling>`): a cell is 4 × 4 fine vertices, odd rows shifted by half a step, and every cell triangle is drawn as 16 flat
triangles of that grid (RE §3.3). The light is smooth (vertex normals), but hill outlines and the shading across them
show the 1.5-unit facets.

**The smooth surface** goes through the same height samples and exists only in the presentation:

- **One cubic patch per fine triangle, for the height only**, so the surface stays a function of x and z: the corner
  control heights are the three samples; the edge control heights come from the corner heights and the gradients at
  the corners (from the vertex normals the terrain already computes); the centre control height follows the
  PN-triangle rule. The result:
  - an edge's curve depends only on its two end vertices, so neighbouring triangles meet without cracks;
  - the surface passes exactly through every sample, so objects standing on sample vertices stay on the ground;
  - where the gradients equal one plane's slope the patch is that plane, so a flattened building plot stays flat
    inside.
- **No overshoot**: steep edges (cliffs, plot borders) limit their edge control heights to the range of the two end
  heights, in the manner of monotone cubic interpolation, so no ridge or dip appears that the samples do not have.
- **Normals** come from the patch's derivative, so the light runs smoothly across the former facet edges.
- **Density**: the setting **Terrain detail** splits each fine triangle into k² triangles, every edge into k equal
  parts (an even split exists only for k², so there is no "double" step):

  | Level | k | Terrain triangles | Surface |
  |---|---|---|---|
  | Faithful | 1 | 1× | the original's flat triangles |
  | Smooth (default of the refined look) | 2 | 4× | cubic patches |
  | Smoother | 3 | 9× | cubic patches |
  | Smoothest | 4 | 16× | cubic patches |

  Every level lights per pixel, as the original's terrain shader already does: normals interpolated across the
  triangles plus the pattern's normal map. In the curved levels the vertex normals come from the patch's derivative.
  Smoothing the light alone, without the extra vertices, changes almost nothing: the interpolated normals already hide
  the facets in the light; what shows them is the shape (ridgelines, hilltop outlines, the turn of a slope away from
  the sun, how objects sit on the ground). The density is uniform over the map, so regions never meet at different
  densities (no T-junctions). If Smoothest everywhere proves too heavy, k = 4 near the camera and a lower k farther
  out, with stitched region borders as the original stitches its LOD levels (RE §3.3), is the fallback.
- **Computed in the vertex shader** (`sadk/terrain_surface.gdshaderinc`) from two small textures: the fine heights
  (R32F, (4W + 1) × (4H + 1): 441 × 441 for a 110 × 110 map) and the gradients (RG16F). Each mesh vertex carries its
  fine triangle and barycentric position. The global switch `sadk_smooth_terrain` chooses the patch or the flat
  triangle, which is exactly the original's surface, so the switch is instant while the mesh is denser than k = 1; a
  change of density rebuilds the regions in the background.
- **Height edits** (`MapChanged(Heights, rect)`) update the two textures in the rectangle (plus one vertex of margin
  for the gradients); the mesh itself does not change.
- **Everything on the ground uses the same surface**:
  - `TerrainSurface.HeightAt(x, z, mode)` in C#, float32, the same formula as the shader: object placement, settler
    and animal height snapping, picking;
  - ground decals, streets, crossings and selection markers are draped in their vertex shaders through the same
    include, with meshes dense enough to follow the curve, instead of being clipped against flat triangles;
  - the water's shore fade reads the smooth height; the border skirt joins the smooth edge.
- **The simulation is untouched**: it keeps the fine height grid and its rules; the smooth surface never reaches it.
  It is a presentation switch like per-pixel lighting ([binding] RR §2.3, faithful look plus a refinement).
- **Cost**: Smooth draws four times the terrain triangles (the viewer's close view: about 236 thousand → 0.95 million),
  Smoother nine times (2.1 million), Smoothest sixteen times (3.8 million), and the shadow and mirror passes draw them
  too. This is where the GPU time saved on shadows
  (§8.4) goes. The numbers are to be measured in the viewer before the defaults are fixed.
- **Size of a triangle on screen**: at the usual zoom a fine triangle (1.5 units) is about 40 to 50 pixels wide on a
  1080p screen; at Smoothest (0.375 units) still about 10. Triangle count is not the problem near the camera; tiny
  triangles toward the horizon and in the far shadow cascades are, and that is what §10.3 removes.

### 10.3 Level of detail by distance

- **Unit: the terrain block** (4 × 4 cells, 24 units), the original's own culling, reveal and LOD unit (RE §2.5,
  §3.3). A cell (6 units; 12 100 of them on a 110 × 110 map) is finer than the distance bands need and multiplies the
  borders to stitch; a region (16 × 16 cells, 96 units) is too coarse for the bands near the camera. A 110 × 110 map
  has about 760 blocks, few enough to choose a level for each one every frame.
- **Levels nest by powers of two**: k = 4 → 2 → 1, so every vertex of a coarser level is also a vertex of the finer
  one. Terrain detail sets the level near the camera (Smoothest 4, Smooth 2; Faithful is k = 1 everywhere); farther
  blocks step down band by band. Smoother (k = 3) does not nest with 2 and 4: it steps 3 → 1.
- **Selection** on the CPU every frame, from the block's distance to the point the camera looks at (as the original:
  `eye = camera + 0.7 × (target − camera)`, RE §3.3), with hysteresis so a block does not flicker between levels;
  the band distances are settings.
- **No cracks**: a block next to a coarser neighbour moves its border vertices onto the neighbour's coarser edge in
  the vertex shader (the neighbours' levels come with the instance), the same idea as the original's stitching,
  which replaces odd edge vertices by the average of their neighbours (RE §3.3).
- **No popping**: in the outer part of each band the vertex shader blends every vertex between its position at the
  block's level and at the next coarser level (geomorphing, as in the CDLOD terrain technique), so the change of
  level is not seen.
- **Drawn as instances**: because the heights come from the textures (§10.2), every block of one level is the same
  grid. The terrain becomes one instanced mesh per level, with the block's origin, level, neighbour levels and morph
  factor per instance: a handful of draw calls for the whole terrain, and the LOD costs no extra draw calls.
- **This moves the ground textures into the shader too**: the pattern of every cell in a texture, the patterns'
  diffuse and normal maps and the transition masks in texture arrays, and the original's layering (the lowest pattern
  of a triangle solid, the others blended over it with their transition masks in rank order, the seam brightened or
  darkened by the mask's red channel; RE §3.3) evaluated per pixel instead of drawn as separate patch layers. Same
  formula, same result; the per-region meshes with one surface per pattern of §10.1 remain the fallback if the
  per-pixel form cannot match the original exactly.
- **Shadows and the mirror view** choose their own, coarser levels (the far cascades and the reflection need less).
- The original's own terrain LOD (levels 0 to 2 by distance) is still not reproduced (RR §2.4): Faithful draws the
  full fine grid everywhere.

## 11. Water, border, sky, environment [draft]

- **Water**: one quad per block at or below the water level, at `sadk_water_level`, batched per region (the viewer
  builds one mesh for the whole map); the original's water shader with its scrolling normal maps, the shore fade
  from the overlay, planar reflection (default), screen-space (option) or none; border water without mirror.
- **Border skirt**: the original's 200-unit black ground with water over it, not drawn in the mirror (RE §3.5,
  RR §3).
- **Sky**: the remake's cloud layer to the horizon by default, the original's 633-unit dome as a switch; both driven
  by globals only (a sky shader reading `TIME` or `POSITION` re-renders the radiance every frame).
- **Environment**: `EnvironmentService` reads the map's environment (the `.bin` contents in the map package) and
  blends its spheres per frame by the camera's ground focus point (RE §3.13: weight 1 inside the inner radius,
  linear to 0 at the outer, divided by the count of influencing spheres, the rest from the map's default); sets the
  light, fog and colour globals and the sun's direction and shadow factor.

### 11.1 Fog that follows the zoom

**The original's fog is fixed**: linear on view depth between the map's `EnvData` fog start and end (RE §3.13),
blended by the environment spheres; the shipped maps end it at about 200 to 300 units (`MP_6P_ship_ahoi`: 140 to
215). That works because its camera never moves far: five zoom steps, the eye `21 × zoom` units from the focus point,
at most 84 units (CI §3.2; the widescreen fix many players use raises the limit to 6 steps, 126 units, where the
focus point already sits close to the fog). A camera that zooms out farther would see nothing but fog.

**The remake's fog is dynamic** (maintainer, 2026-10-15): it follows the zoom, so every zoom level keeps the
original's relation between the view and its haze.

- **Within the original's range** (eye distance up to `e₀ = 84` units) the fog is exactly the map's: faithful and
  refined look the same there.
- **Beyond it** both distances scale with the eye distance `e`: `start' = start × e / e₀`, `end' = end × e / e₀`.
  The ease of the zoom (`zoomCurrent`, CI §3.2) drives `e`, so the fog moves smoothly with the camera.
- The environment spheres still blend the fog colour and distances first; the scale applies to the blended result.
- **Everything that ends with the fog follows it**: the far plane (the fog's end plus a small margin; nothing beyond
  is seen, below the horizon the sky is the fog colour), the shadow range, the mirror view's range, the distance bands
  of the terrain LOD (§10.3) and of the object LODs. Zooming out therefore costs more only as far as more is really
  seen, and a high view over the whole map never fogs out.
- The sky stays unfogged in the fog pass: the cloud layer fades into the fog colour at the horizon by itself.
- A setting keeps the faithful behaviour (the map's fixed distances at any zoom) for comparison.

**How it is drawn** [implemented 2026-10-15]: the original sets `D3DFOG_LINEAR` table fog on view depth with the
background colour (`CGraphicDevice::SetDefaultStates`, S 004d8f99); its shaders write no fog of their own. It fogs
the sky dome (`Scene::RenderPasses` S 0067eb20 passes `Scene+0x720`, set to 1 by the constructor at S 0067ff07, to
`RenderSkydome` S 00683e50) and the reflection view (`RenderReflectionPass` reads the same flag); particles,
additive objects (blend mode 2) and the caustics pass are drawn without fog. Godot's depth fog is
`smoothstep(begin, end, length(vertex))` on radial distance, not this ([godot-capabilities.md](godot-capabilities.md)
§2), so every world pass writes the original's fog itself through the spatial `FOG` output:
`sadk_fog(VERTEX, CAMERA_VISIBLE_LAYERS)` in `sadk/fog.gdshaderinc` gives linear fog on view depth in the background
colour from `sadk_fog_range` (the distances after the zoom scaling above), and Godot blends it. The original dome
sky fogs the point each ray meets by its view depth (`sadk_view_forward`; sky shaders have no camera basis); the
remake's cloud layer is unchanged. The mirror is fogged as in the original, a switch (`<Reflections fog>`, on by
default; `sadk_mirror_fog`). The border skirt takes the stronger of the fog in effect and the original's unscaled
edge fade. **The curve is a setting** (`<Fog curve>`, maintainer 2026-10-15: "S curve fog is a bit prettier"):
`Smooth`, the default, is Godot's own depth fog (`smoothstep` on the distance from the eye), `Linear` the original's;
the include computes both (global `sadk_fog_smooth`), so every pass, the dome sky and the mirror follow the choice.
Godot's depth fog stays on with the same distances as the fallback for materials that write no `FOG` (a mod's
`StandardMaterial3D`); with the smooth curve it is exactly the same fog. A test checks that every spatial shader of the engine and core.game writes
`FOG = sadk_fog…` or declares `fog_disabled`. Residual: Godot mixes the fog in linear light, the original in gamma
space; both agree at no fog and at full fog, in between Godot's is lighter (black half fogged towards 0.5: 0.37
instead of 0.25), and the final pixel colour is known only after Godot's light pass, so it cannot be pre-corrected.

## 12. Map objects [draft]

- Created on `EntityAdded` for deposits, doodads, flags, harbours, sea routes (one buoy per end), chests and spawn
  points; the descriptor comes from the gfx name; `meshType="none"` creates a render object without a batch slot.
- **Placement** as the original's `MapObjLayer::AddInstance` (RE §3.11): the stored fine position's vertex (deposits
  and doodads) or the cell's vertex; flags shifted by the vertex hash; the element's `offset`; **yaw and three scales
  from four draws, always**; height at the final position; `alignOnWater`. The draws come from the map-object
  presentation stream: in creation order in faithful mode (reproducing the original's first map after a start), from
  `hash(map, entity)` in refined mode.
- **Kinds by the element's `type`** instead of names in code: `mapobject.tree` (growth scale `(min(1, 3g), g,
  min(1, 3g))`, sway while being felled, fall, fallen; changes faded at 10 per second), `mapobject.stone` (a new
  stage is a removal plus an addition with new draws, RE §3.11), `mapobject.wheat` (growth on Y), `mapobject.gate`
  (a fire emitter at the box centre on its first visible frame), `mapobject.routebuoy` (bobbing in the vertex shader;
  `Buoy_Fire` while a ship of the route is under way, from route events), `mapobject.flag` (owner colour, wave),
  `mapobject.plain`.
- **Level fade**: `DepositDepleted` starts the 20-tick fade (the pile sinks by `level × extentY`); removal follows.
- **Foliage as opaque cutouts** (maintainer, 2026-10-15): the elements the original blends (blend mode 1 and the
  shaders whose passes blend: `tree_shader2`, `_winter`, `_willow`, `weed_shader`) are drawn alpha-tested at the
  original's threshold in the opaque pass, with alpha to coverage when MSAA is on. They need no sorting, write depth,
  cast their own shadows (no shadow-only copies) and appear in the opaque picture. The original's blending softens only
  the filtered edge pixels (the leaf textures have one-bit alpha); in the viewer the difference is barely visible.
  The switch "Blended foliage (original)" draws them blended, sorted back to front per batch, with the shadow-only
  cutout copies of §7.1.
- Growth and fades are written into the instance data per tick and interpolated in the shader with `sadk_tick_alpha`
  where the original fades within a tick.

## 13. Buildings [draft]

A few hundred per map, few enough for each building to be a node tree of its own: `MeshInstance3D` parts on a
`Skeleton3D`, driven by an `AnimationPlayer`, with instance uniforms (`SetInstanceShaderParameter`) for the per-building
values; it is then also the building's inspectable node (§4.6). The thousands of settlers, soldiers and animals keep
the GPU skinning of §9. [draft; suggestion forwarded by the maintainer 2026-10-15] The parts:

- **House**: `house_shader.fx` RenderHouse (RE §3.9): per-vertex light, light map blended by `saturate(1.5 − D)`,
  colour map of the variation (`instance number mod 8`, the render pool slot with LIFO reuse; an upgrade keeps it),
  alpha test 127, rigid skinning to the first bone.
- **Construction**: the frame mesh merged with its stages `0..N−1`; the stage index sits in a vertex channel and the
  shader drops stages at or above the instance's stage (`min(N, toInt(0.5 + (N + 1)(1 − remainingB)))`). The rising
  building uses `buildings/house_cut` with the cut height **in model space** (`(height − 0.1) × p / 0.9` above the
  building's base, `p` interpolated within the tick), both sides drawn. The viewer compares a world height with a
  model height, which works only for a model at y = 0.
- **Upgrade**: the old type keeps `y ≥ plane`, the target type `y ≤ plane`, the target's frame grows first; started and
  cancelled by events; completion is a removal plus an addition that keeps the colour slot.
- **LOD**: part 0 at the top detail setting, as the original (RE §3.9: at the top preset always part 0); the
  `<mesh>LOD0` part as a performance switch.
- **Door and work clips**: `Animation` resources converted from the building's clips, two layers per building (slot 0
  door, slot 1 work) on disjoint bones (the conversion records each bone's layer per building model), so the two
  play at once without blending (an `AnimationTree` with both, or one player per layer).
  Triggered by `ActionTimerStarted` of the worker and by settlers passing `enterDistance` (presentation logic over
  motion samples), as RE §3.9 describes. While a building is out of view, a `VisibleOnScreenNotifier3D` on its node
  switches its players off; on `screen_entered` each player seeks to `(clock − clip start) mod length`, so the clip
  shows where it would be by now (`VisibleOnScreenEnabler3D` would resume where it stopped instead). Notifiers ignore
  shadow passes, so the shadow of a building just outside the view may show a held pose
  ([godot-capabilities.md](godot-capabilities.md) §6).
- **Ground decal**: the `GROUND` mesh clipped against the terrain triangles under it and laid 0.01 above (the viewer's
  `Placement.GroundDecal`), on a worker thread; rebuilt when heights change under it.
- **Fires**: `toInt((1 − hpRatio) × firePoints + 0.5)` emitters `BuildingFire` at the `FIRE_%02d` nodes, else at five
  points drawn from the fallback-fire stream.
- **Military flags**: their own small kind (`MILFLAG` bone, mesh by soldier count and kind, texture by proximity
  zone, owner colour, wave in the vertex shader).
- **Demolition**: dust effect, then `y = terrain − height × progress²` with `progress += dt × 0.35`, then removal;
  **ruins** with their own decal until the remains are removed (`burnTicks`).
- **Building sites and farms**: goods on the site (§14) and farm animals at `boneLink<i>` bones by productivity.

## 14. Goods [draft]

`ItemKind`, MultiMeshes per good mesh and region:

- **Piles at flags**: one pile per flag, 6 stacks × 6 slots, layouts per good (WO §3.2); add, remove and merge rules
  driven by `PackagePile` events; slot order follows event order (as the original's follows callback order).
- **In hands**: attached to the carrier's bone (§9); the holder from `CarriedPackageChanged`; items on ships hidden.
- **Building sites**: rebuilt when the site's stock revision changes (WO §3.3).
- **Water-street boats**: the hidden `Boat` item per water street, shown for carriers on it.
- Every good has an item or is skipped: 27 group goods have none (WO §3.1).

## 15. Streets, borders, overlays [draft]

### 15.1 Streets and routes

The original's route spline (Hermite, tangent factor 1.3), the street strip clipped against the terrain triangles,
crossings as hexagon fans, water-street buoy chains, sea-route strips with the 16-frame cross-faded texture (WO §3.5
to §3.8); built per street on a worker thread from `EntityAdded` / `StreetUpgraded` / removal, rebuilt on height
changes under it. Street previews of the placement mode come from `IQueries` and draw with the preview tint.

### 15.2 Territory borders

Per player the border points (land: `limes`, water: `buoy`), instanced; rebuilt for the changed rectangle of
`MapChanged(Territory, rect)` (the original rebuilds all eight players' lists on every change).

### 15.3 Build overlay and selection

- The construction icons per cell of the local player (RE §3.14), camera-facing quads per visible block, rebuilt on
  `MapChanged(ConstructionFlags, rect, localPlayer)` (the original recomputes them every frame); shown in info-map
  mode with its fade.
- Selection markers: decals laid on the terrain triangles like the ground decals (Godot's `Decal` is not available on
  the Compatibility renderer), additive, spinning, from the UI's selection.

### 15.4 Fog of war

§4.5.

## 16. Particles [draft]

- The emitter simulation is the viewer's (`Particles/ParticleEmitter.cs`): the original's spawn and reset draws,
  closed-form update, curves, far-to-near sorting (PA §3). It runs on worker threads, per frame, for emitters in view.
- **Owners**: emitters are handles owned by render objects (building fires, buoy fires, gate fires, buffs, ship
  wakes) or fire-and-forget (strikes, impacts, `SpawnTriggered`, `gfx.createParticel`, resource hints); an owner's
  removal stops or deletes its emitters.
- **Drawing**: one MultiMesh per pass (flat, spherical, volume, additive) with one instance per particle, written in
  sorted order each frame; the quad is expanded in the vertex shader from the camera's axes (so the mirror camera
  gets facing quads too); the atlas cell and its size come from the atlas texture, not the 512 × 512 constant of the
  viewer. The viewer rebuilds an `ArrayMesh` per emitter per frame.
- Faithful details: the fixed seed 0x53a0 and the reseed rule; resource hints resolve their goods by name in signed
  id order (only gemstones sparkle on the shipped maps); the particle pass draws once (the original draws it twice
  when post-processing is on).

## 17. Interpolation and time [draft]

- Movement: `pos = lerp(prev, current, Alpha)` per frame on the CPU for visible movers (§9), the picture one tick
  behind, never extrapolated (RE §3.10).
- Construction plane, growth fades, level fades: interpolated within a tick from the previous and current values.
- Frame-rate dependent effects of the original (the settler death sink per frame call, camera smoothing per frame)
  become `dt`-based in both modes; they are presentation only.
- Stalls: faithful saw-tooth or refined hold ([sim-boundary.md](sim-boundary.md) §4.1).
- **One clock** [the maintainer's direction 2026-10-15]: game speed is `Engine.TimeScale` and pause is
  `SceneTree.Paused`, so animation players, particles, tweens and the presentation time (`sadk_time`) follow both by
  themselves; the camera, the UI and the boot code run on real time (`Time.GetTicksUsec`) and process always
  ([godot-capabilities.md](godot-capabilities.md) §6). Implemented 2026-10-15 as `PresentationClock`: `Game`
  advances by Godot's process step and stands still under the tree pause (the shaders' `sadk_time`), `Real` comes from
  `Time.GetTicksUsec` (`sadk_real_time`); one driver node advances it before every other node. `SetGameSpeed` is the
  only way to set the speed and refuses 0. The renderer runs while paused (environment, fog and mirror follow the
  camera), layers get the game step, and what Godot animates goes under `WorldRenderer.Animated`, a pausable node. The
  free camera moves in real time and only on input nothing else handled (a text field or an open overlay keeps it
  still).

## 18. Picking [draft]

- Terrain: a ray from the eye through the pixel, length 1000, against the drawn terrain triangles of the visible
  regions (exact, since the remake draws the terrain at full resolution) → cell and vertex (CI §3.10).
- Objects: pick proxies (boxes from the descriptor's mesh bounds and the instance transform) in a grid of regions;
  the ray tests boxes, then the mesh where the original does.
- The original's priority (CI §3.10): the local player's flag on the cell, a building hit by the ray (explored), a
  building on or next to the cell, a ship, a sea-route marker, the player's street; settlers are hover-only. The
  results are checked against the views (exploration, ownership, existence) before a command is built.

## 19. Settings and switches [draft]

The table of RR §2.3 stands. Added here:

| Setting | Faithful | Refined option |
|---|---|---|
| Map-object yaw and scale, settler palettes | creation-order streams (differ per peer and after a load) | stable per map and entity |
| Walk cycles | in phase (shared pool) | per-instance phase |
| Foliage | blended, sorted per batch, shadow-only copies | opaque cutout with alpha to coverage (the default, §12) |
| Stall picture | saw-tooth | hold |
| Missing visual | nothing drawn | placeholder |
| Building LOD | part 0 | LOD parts by distance |
| Far plane, zoom range | 500, original steps | extended |
| Fog | the map's fixed distances, linear on the view depth | scaled with the eye distance beyond the original's 84 units (§11.1); far plane, shadow range and LOD bands follow it; smooth curve (the default) |
| Terrain detail | Faithful: flat triangles of the fine grid | Smooth (4×), Smoother (9×), Smoothest (16×) triangles on cubic patches (§10.2) |
| Shadow preset | one map, 2048, 2 × 2 taps; the default is a light preset close to it (§8.4) | cascades, larger maps, softer filter |
| Shader animation clock | as the original's timer (open, §7.3) | simulation-scaled |

Settings apply at once where they are globals; those that change batches (LOD, region size) rebuild at the next
match load.

**In the game** [implemented 2026-10-15]: one shared `RenderSettings.Current` (a map view reaches it as
`rc.Settings`), stored as `<Graphics>` in `settings.xml` ([assets.md](assets.md) §3) and changed in the Options screen
(`engine.options`, tabs Graphics, Shadows, Quality) or the map view's quick switches, which are a form over the same
object. Every change applies at once, including the region size and blended foliage, which rebuild the shown world.

| Element | Attributes |
|---|---|
| `Reflections` | `mode` (Off, ScreenSpace, Planar), `strength`, `resolution`, `range`, `rate`, `objects`, `shadows`, `minDepth`, `fog` (the mirror fogged as the original's, §11.1) |
| `Fog`, `Sky`, `Light`, `Foliage`, `Batching` | `mode` (Dynamic, Fixed, Off), `curve` (Smooth, Linear); `style` (Clouds, Dome); `perPixel`; `blended`; `regionBlocks` |
| `Shadows` | `enabled`, `mapSize`, `splits`, `filter`, `range`, `darkness`, `softness`, `blur` |
| `AntiAliasing`, `Scaling`, `Textures` | `msaa`, `screenSpace`, `temporal`; `upscaler`, `scale`, `sharpness`; `anisotropy`, `mipmapBias` |
| `AmbientOcclusion`, `DepthOfField` | `enabled`, `intensity`, `radius`, `lightAffect`; `enabled`, `strength` (follows the eye distance, easing at the original's focus speed 3, S 00696d20) |

SSAO, depth of field, TAA, SMAA, FSR and shadow softness have no effect on the Compatibility renderer.

## 20. Performance [draft]

- Budget: the remake must not load the GPU more than the original for the same picture (maintainer, 2026-10-14);
  the viewer's measurements are the starting point (RR §4.2).
- The performance readout of the viewer (per-view GPU and CPU time, draw calls of the visible and shadow passes,
  triangles, video memory) moves into the game's debug overlay, plus the renderer's own counts: render objects per
  kind, batches, instances, uploads per frame, worker-thread time.
- Unattended regression checks: fixed camera positions on the shipped maps rendered on the Compatibility renderer
  under a virtual display, compared with stored pictures within a tolerance; colour judgements on Forward+ by the
  maintainer.

## 21. What is moddable at which level [draft]

| Goal | How |
|---|---|
| a new tree, doodad, building or settler look | assets (model, textures) + a descriptor entry or patch |
| new textures for existing objects | shadowing assets at the same logical paths |
| a new look for one object kind | replace its shader file, or add one and point the descriptor at it |
| a new light model for everything | replace `sadk/light_original.gdshaderinc` |
| a new vertex animation | a new object shader including the shared parts |
| a new drawing technique | a render kind in a client assembly (§4.4) |
| visuals for a mod's own events | an event handler in a client assembly (`EventRouter`) |
| anything else | Harmony on `Sadk.Presentation` |

## 22. What is taken over from the viewer [draft]

| Viewer part | In the game |
|---|---|
| `Sadk.Formats` (container, KEX with bake, map reader, `.pfx`, settings XML, TGA) | taken over; becomes the converter's and the `.kex` loader's front end ([assets.md](assets.md)); `S2mMap`'s dictionaries become ordered lists |
| `Particles/ParticleEmitter.cs` | taken over (seed as a property, generator as a service); `ParticleView` replaced (§16) |
| `SettlerColours`, `PaletteGenerator` | taken over as a presentation service fed by settler events; palettes into the atlas (§9) |
| `original_light.gdshaderinc`, `OriginalLight.ShadowFactor`, the light direction, the sphere blend | taken over into `sadk/light_original`, `sadk/globals` and `EnvironmentService` |
| `MapGeometry.TerrainTriangles`, the ground-decal clipping | taken over as pure geometry |
| `TerrainBuilder` math | taken over, split from its Godot mesh building (§10) |
| KEX-to-Godot formulas (axes, winding, weights, inverse binds, animation keys, normal length) | taken over as the converter's specification |
| `TextureLoader` (DXT1 alpha, cube maps, mips) | moved into the converter |
| the mirror view (sub-viewport, mirrored camera, shadowless sun copy, guard band, gating, rate) | taken over, with the explicit mirror flag (§8.3) |
| the shaders' formulas (water, terrain types, buildings, settlers, particles, sky layer, dome, per-kind vertex animations) | taken over into the per-kind files of §7.1 |
| the `--stats` readout and the Quality, Shadows and Display settings | taken over into the debug overlay and the settings |
| `object.gdshaderinc` with its 21 defines, `ShaderFiles.Object` | replaced by §7 |
| anonymous MultiMesh batches, node trees per settler, animal and building, materials copied per instance | replaced by §4, §9, §13 |
| `GameInstall`, the by-name texture table, direct reads of the installation, `PropertyScripts` | replaced by the converter, the file system and the Lua runtime |
| names of the original in code (`RouteBuoy`, `z_harbor_00`, `gate` → `Fire`, `.fx` names, settler scale and LOD constants, cube map path) | data: descriptor `type` and `renderKind`, the shader map, `settler_config.xml`, `graphics.xml` |

## 23. Order of work [draft]

1. Asset bridge, shader library with the includes, global parameters, the settings object.
2. Terrain, water, border, sky and environment from a converted map package, through a simulation that loads the
   map and publishes `MapChanged(Reinitialised)` (no ticks yet). Parity with the viewer's map picture.
3. Render object table and batches; map objects from `EntityAdded` events of the loaded map; fog of war textures.
4. Buildings (houses, construction, decals) driven by a test simulation that places and builds.
5. Characters with GPU skinning, palettes, LOD; animals.
6. Goods, streets, borders, overlays, selection, picking.
7. Particles and their owners.
8. Mirror, shadows and post effects with the faithful and refined presets; performance pass against the original.

## 24. Open

1. Whether the original's shader timer runs on real or simulation time (WO §10 Q7) — decides `sadk_time` in faithful
   mode.
2. The shadow defaults (RR §6): light by default (§8.4); the exact cascade count and map size after measuring.
3. Which height sampler the original uses to place objects (§10).
4. The building and settler descriptor keys ([assets.md](assets.md) §9 item 1).
5. The remaining picture-affecting reverse engineering: selection marker styles and the build icon atlas (RE §10
   Q13), the border bobbing (Q12), ship player-colour values, the loader of building-level particle elements (PA
   §10 Q3), the texture particle passes 1 and 2 sample (Q1), what drives the tree sway and fall states.
6. The object alpha-test threshold: 0.5 in the viewer against "AlphaTest ≥ 127" in `map_objects.xml`, an
   off-by-one at 127 to check against the `.fx` files.
7. The smooth terrain's density default and its cost with shadows and the mirror view (§10.2): to be measured in the
   viewer.
