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
   [assets.md](assets.md) §5) are engine code and assets, so no mod is needed for them; `core.game`'s client assembly (`Sadk.Client`, part of the engine)
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
14. **CPU and GPU in balance; integrated graphics are a target** [binding, maintainer 2026-10-15: "We can't offload
    everything to the GPU ... then we're fucked if someone only has integrated graphics"]. What is static or changes
    rarely (the terrain's surface, heights after building, placement) is computed once on the CPU, on worker threads,
    and stored; the GPU gets only work that changes every frame (blending between levels, skinning, waves). No
    evaluation per vertex per frame of what a vertex buffer could hold. Every expensive option has a cheap setting,
    and the defaults must run on integrated graphics.

## 2. Place in the process [draft]

The world renderer base is the engine's (`Sadk.Presentation.Rendering`); the map renderer and its layers are
`core.game`'s client assembly `Sadk.Client` (namespace `Core.Game.Rendering`; [mods.md](mods.md) §11a). Per
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
| `WorldRenderer` | the node that draws a world through its own camera (horizontal field of view 50°, near plane 1): its kind (`WorldKind`), layers (`Layers`, `AddLayer`, `RemoveLayer`, `Layer<T>()` for the code that made it), the layers' services (`Services`, §2.2), `Environment` (the rig), `Mirror` (requests), `SetView(focus, eyeDistance)`, `Report`, the clock it runs on (`Clock`, §17); a world type overrides `GroundHeight`, `Bounds`, `Pick` and its report lines |
| `IWorldLayer`, `WorldLayers` | one part of a world's picture (`ProvideServices`, `Show`, `Clear`, `Frame`, `ApplySettings`, `Report`) and the registry per world kind: `WorldLayers.Register(kind, name, order, factory)` returns a registration the mod disposes in its `OnUnload` |
| `RenderServices`, `WorldServices` | the services the layers offer one another by interface, and the registry per world kind a mod wraps or replaces them through (§2.2) |
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
| `MapServices` | `MapServices.Register<T>((renderer, current) => …)`, the same as `WorldServices.Register<T>("core.game.map", …)`; core.game's services in §2.2 |

The mode `core.game.mapview {map, back, x, z, yaw, pitch, distance}` shows a map outside a match with a HUD of the
switches; the asset browser opens map packages in it, and `--emit=core.game.mapview?map=…` with `--shot-after` and
`--shot` takes unattended pictures. The mod `tools.mapviewer` builds on the same public pieces (`MapData.Load`,
`MapRenderer`, `OrbitCamera`, `MapRenderer.Pick` / `CellAt`) and adds the map list, the data overlays, their legend and
a cell inspector (`tools.mapviewer.open?map=…&overlay=…&ontop=true`).

### 2.2 Services between layers [implemented]

A layer never looks another up by its type. What one layer serves the others is an interface, offered to the renderer's
`RenderServices` and resolved by the layers that use it once, in their `Show`:

1. When the renderer shows a world it asks every layer, in order, for its offers (`IWorldLayer.ProvideServices`:
   `services.Provide<IFogOfWar>(this)`); a later offer of an interface covers an earlier one.
2. Then the world kind's registrations (`WorldServices.Register<T>(kind, (renderer, current) => …)`, for maps
   `MapServices.Register<T>`) are asked in the order they were made; each gets the service in place to wrap or replace,
   or returns null to leave it.
3. Then the layers are shown. A layer without the service it asks for draws without it (no fog of war in a gallery).
4. When the world goes, every offer is withdrawn, so the renderer keeps neither a layer of that world nor a mod's object.

A mod hands its registration to its context; disposing it takes exactly that registration away, so the next world shown
has the service it covered (the layer's, or another mod's). A renderer showing its world when a registration comes or
goes keeps what it resolved until it shows a world again, as it keeps its layers. Replacing the layer itself by its name
(`WorldLayers`) replaces its services with it.

core.game's map layers offer:

| Service | Served by | Used by |
|---|---|---|
| `IFogOfWar` (viewer, active, explored cell, shown cell, revealed block) | fog of war | buildings, characters, streets (door paths) |
| `IGroundOcclusion` (occluders by `OccluderKey`) | ground occlusion | map objects, buildings |
| `IParticles` (start, one-shot, follow, stop, movies; handles `IEffectHandle`, `IMovieHandle`) | particles | buildings (fires, dust, clip events), characters (clip events, wakes), the scene's effects |
| `IBuildingPlaces` (node, world box, pick box, ray test, bone transform, turned box, hit distance, containment) | buildings | the scene's effects; the selection ring, picks, previews and the catapult box |
| `ICharacterPlaces` (bones, link bone, attachment, drawn, explored, position, top, records) | characters | goods, the scene's effects; the ship and settler picks, the selection ring, the ship box's picture, the soldier overlays |
| `IObjectPlaces` (records, world box, near fade, hold all) | map objects | the selection picture, the buoy picks, the minimap's overview, a mod's camera |
| `IBuildOverlay` (flags, alpha, excluded cell, map changes) | build overlay | the build placement (the info map) |
| `IWorkplaceAnimations`, `IBuildingEntrances` | buildings | the settler feed and the entrance passes (wired by the match) |
| `IAttachedItems` | goods | the settler feed (wired by the match) |

The code that makes a renderer and drives its layers (the match, the galleries, the map view's statistics) holds the
concrete layers it feeds (`Layer<T>()`): the feeds, sources and clocks it sets on them are its composition, not a layer's
business. The interface (the selection, the hover tooltip, the build mode, the minimap) reads the drawn world through the
services only, so a mod's layer that serves one replaces core.game's for the interface too; the layers hold the effects
they start as the particle service's handles. Tests keep both rules (`RenderServicesTests`).

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

The original hides a block object (map object, goods pile, flag, building) unless its terrain block (cells
`4b .. 4b + 4`, edges shared) is in view **and** revealed, hides characters, animals and ships on cells the viewing
player has not explored, hides buildings without the fog-visible flag (which follows the anchor cell), and darkens
everything by the exploration overlay (`CalcFOW`) (RE §3.7). The renderer does this without CPU work per object:

- `FogOfWarService` keeps three textures for the local player: the **exploration overlay** (the original's
  `(2W+1) × H` "WorldElevationMap": alpha = explored, blue = 1 − normalised height), a **cell mask** (`W × H`) and a
  **block reveal mask** (`W/4 × H/4`, a block is revealed once any of its cells is explored and never again hidden).
  They are updated from `MapChanged(Exploration, rect, player)` for the local player.
- The include `sadk/fow.gdshaderinc` gives `fow_block_revealed(world)`, `fow_cell_explored(world)` and the
  original's `CalcFOW` darkening with `fow_noise.tga`. A kind's vertex shader collapses an instance whose block is not
  revealed (all vertices to one point, so it rasterises nothing); its fragment shader applies `CalcFOW`.
- Frustum culling is Godot's, per batch box.

**As built** [implemented, sadk-remake b00b759]:

- **Layer**: `FogOfWarLayer` (the map layer `core.game.fogofwar`, order 50) keeps the local player's exploration as
  R8 `ImageTexture`s, published as the global shader parameters `sadk_fow_*`; the shaders read them through
  `fow.gdshaderinc`. The setting is `<Graphics><FogOfWar enabled>` (§19).
- **Darkening in Godot's fog**: `sadk_fog_fow` folds the original's factor `f` (`a · lerp(noise, 1, a)`, RE §3.7)
  into Godot's `FOG` output. With `d` the fog amount and `bg` the fog colour Godot would apply and `k = f^2.2`
  (the factor taken into linear colour), the shader writes the fog alpha `t = 1 − k(1 − d)` and the colour
  `bg · d / t`, so the pixel becomes `k(1 − d) · c + d · bg`: darkened first, then fogged, the original's order.
  Water as the original's: `rgb *= a`, `alpha += 1 − a` (RE §3.5).
- **Measured**: showing the whole map costs 8.65 ms (Steinfjord); an exploration change 13 to 101 µs (radius 2 to
  20); at most one R8 upload per frame (26.5 KB); no CPU work per frame.
- **Differences from the original** (to review, [sim-boundary.md](sim-boundary.md) §11 item 4): no left-over-texel
  quirk (RE §3.7 item 2); no separate black `Unexplored` pass; the overlay clamped in every shader (the original
  wraps it except in `water_shader.fx`); a border post is kept or hidden whole (the original fades it per
  pixel with `CalcFOWWithAlpha` and the alpha test); flags follow the block rule; hiding a building's node hides
  its decal and flag; no refined variant. A character and its carried good test the settler's logic cell, as the
  original's `CharacterMovement::Update` S 006c57b0 does (`MotionSample.Cell`, the engine field published by the
  settler system from `SettlerMovement +0x128`, and the record's `Explored` flag) [implemented, sadk-remake
  9fb619f].
- **Open**: selection and hover still ignore unexplored cells (the original's ray pick S 00787cc0 and hover
  tooltip S 005efd60, RE §3.7); the resource particles (S 0068b220); the consumer of the second "FogOfWar" texture
  (`CEnviromentMgr +0x11c`, RE §10 Q10); the map objects exempt from block hiding (type virtual returning 2).

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
- **Built for map objects** [implemented 2026-10-15]: a node-free notifier per object
  (`RenderingServer.VisibilityNotifierCreate`) on the objects' layer, which the main and the mirror camera both see; a
  batch counts its members apart from its drawn slots and is freed only when it has none. Godot never reports a
  notifier that was never in view, so a new object stays drawn until two frames were drawn with its notifier and none
  reported it. Box growth: 3 units for the one-frame-late answer (about a frame's pan at distance 150 and 60 fps); the
  shadow's reach towards the sun, height over the tangent of the sun's elevation, capped at 40 units, rebuilt when the
  sun turns. A switch (`<Batching visibility>`, on by default) draws every object of a visible region instead, for
  comparison. The map view's `stats=true` logs frame times, draw calls, primitives and the visibility bookkeeping
  every 2 s; `orbit=<degrees per second>` turns the camera for measuring.
- **Measured** on the maintainer's GPU (RTX 4080 SUPER, Forward+, 1920 × 1200, his settings: 8192 shadow map with
  four cascades, MSAA 2×, SSAO), Steinfjord at distance 150, main view plus mirror per frame:

  | | Primitives | GPU | Render CPU |
  |---|---|---|---|
  | standing, notifiers off | 2.14 M | 2.42 ms | 0.91 ms |
  | standing, notifiers on | 1.59 M (−26 %) | 2.31 ms | 1.32 ms |
  | turning 30°/s, off | 2.15 M | 2.70 ms | 1.03 ms |
  | turning 30°/s, on | 1.75 M (−19 %) | 2.35 ms | 1.44 ms |

  Godot's cull pass pays about 0.2 ms per camera for 4838 notifiers; the remake's own bookkeeping 0.02 to 0.04 ms;
  no object was missed. With these heavy settings, terrain, shadows and SSAO dominate the GPU and the saved vertices
  show little; with the default shadows (4096, hard edges) the maintainer saw the GPU clock drop markedly with the
  notifiers on (2026-10-15), the measure he judges load by. Decision: one notifier per object, on by default, for every
  kind; grouping static objects per terrain block stays in reserve should the cull pass's CPU time ever become the
  limit.

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
| `groundDecal` (core.game's `visuals/map-objects.xml` `<Type>`) [implemented, sadk-remake c8f44a0] | a ground decal file for every element of that type: laid at the object's transform, mesh or not, laid again when a height change touches its terrain block (the original's 4 × 4-cell block rule, `UpdateCellHeightsInRegion` S 006b7220) or the terrain detail changes, removed with the object; drawn by the shared house-decal code (`HouseDecalSet`) | none; the `harbor` type names `buildings/Harbour_decal.KEX`, the original's code constant (`Harborplace::ctor` S 006db7a0) |
| `fells="true"` (same file, on tree types) [implemented, sadk-remake 1fd328c] | the object falls when worked (§13 "Trees fall") | the original picks the felling path by the workplace's good, wood (hash 0xCD6EC133, `UpdateFellingObject` S 006c87d0); in the shipped data both select the same objects |

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
§5.3a); the kinds' shaders are `core.game`'s, under `core.game`'s `assets/shaders/` (`base/core.game/` in the game folder, `src/Base/core.game/` in the source; logical `shaders/...`):

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
| world overlays | `streets/street`, `streets/crossing`, `streets/buoys`, `border/border`, `overlays/build_icons`, `overlays/decal` (selection) |
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
| characters (as built, §9.1) | r = owner index (−1 none), g / b = palette block column and row, a = clip speed | x = clip (−(clip + 1) for a clip played once), y / z = start on the presentation clock as 2y + z, w = free |
| goods | — | x = flags |
| particles | rgba = colour × opacity | xy = atlas cell, z = size, w = rotation or stretch |

Buildings and other single instances use instance uniforms (Godot allows 16 per shader): colour-map offset, clip
height in model space and side, construction stage, two animation layers (§13).

**Normal length**: the original's normals are `1/s` long for a model of scale `s` (RE §3, RR §3). Instead of a
material uniform per scale (the viewer's `normal_scale`), the light include derives `s` from the instance matrix's
column lengths and restores the length, so instances of one batch may differ in scale. Characters are the exception:
their normals are unit length (`CMesh::FillVertices` normalises them and their world matrix carries no scale).

**Half floats on Compatibility**: the Compatibility renderer packs a MultiMesh's `COLOR` and `INSTANCE_CUSTOM` into half
floats (`unpackHalf2x16` in its `scene.glsl`), so a value needing more precision (a start time) is split over two
channels. Player colours are a global table (`sadk_player_colors`, §7.3), indexed by the owner in `COLOR.r`.

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
- **The match camera** [implemented, sadk-remake 726a5b1]: the original's camera is the default in a match
  (core.game `Camera/CameraRules.cs`, `MatchCamera.cs`): standard and look-around modes, zoom steps 0..4 with the
  tilt per step, the ±1.5 turn on Insert / Delete, H to go home, the nearest vertex (S 00687570) and the focus
  clamp; it reads scroll speed, edge scrolling, invert scrolling and invert mouse. The free orbit camera is a setting
  (core.game's camera style, Options → the core.game group), and a run given a yaw, pitch or distance uses it. The
  minimap and the message list focus whichever camera is active. Free-fly, cinematic and cutscene modes 2–5 are
  `[TODO]`. Because the original camera never comes closer than its first zoom step, world-sized quads such as the
  build icons (§15.3) no longer grow huge up close by default.
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
shader); terrain blend layers (transparent, render priority by pattern rank; drawn 0.05 units toward the eye, as built
in sadk-remake 16d7051: Godot compiles their vertex code apart from the opaque pass's, and [inferred] the depths
differed in the last bits, so single triangles failed the depth test); streets, crossings and routes
(transparent; the original pulls them toward the camera by moving the near plane from 1.0 to 1.1, `SetNearPlaneOffset`
S 004d9e10 with depth bias 0.1 in `StreetRenderer::Render` S 006c3ab0, a pull of about 9 % of the view depth, some
3.4 units at 40 (3.36 with the far plane 500; WO §3.8); §15.1 says how the remake stands in for it); buildings with
house decals before them (the remake cuts the streets off where the plot of a building site or a harbour place, its
decal alpha baked into a map texture, reaches half; a finished building's plot is drawn over them as the original's;
as built in sadk-remake b57b0e3: the original blends the decal's soft rim over the streets, so a street
under it showed through); map objects;
characters; goods; animals; ships; single meshes; selection decals; map objects clipped at the water and then the
water itself (after blended objects, RR §4.1); the build overlay; particles. The build overlay comes after the whole
map, water included, and before the particles (`Scene::RenderPostFxAndOverlay` S 00680a00), and after the post-process
combine, so the depth of field never blurs it. Godot sorts transparent objects by distance; render priorities enforce
the pass boundaries where the original's order matters. As built (sadk-remake d515744, `src/Sadk.Client/DrawOrder.cs`): the
terrain blend layers clamp to priority 125 at most, the build overlay is at 126 and the particles at 127 (pass 0x100,
the original's last); the remake's optional depth of field still blurs the overlay.

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

**Which parts cast** [implemented, sadk-remake d8f9737, e94cc01]: `ShadowCasters.Mask` follows the original's
`Scene::ApplyShadowQuality` S 0067f420 per shadow level: nothing below 2, buildings (0x8) at 2, buildings and map
objects (0xC) at 3 and 4, everything (0x3FF) from 5; the parts gated by `RenderWithExternalEffect` S 006884a0 /
S 006a0cc0 are the terrain (0x1), the buoys (0x2), the map-object batches (0x4), the buildings (0x8: parts, an
upgrade's target parts, frames, ruins, military flags) and the borders (0x20). The terrain therefore casts only from
level 5; each layer reads its bit through `ShadowCasters.CastSetting`, and a change applies live. The options map onto
it as the original's panel does (§19): `cShadowDetail` → level `trunc(v × 6 + 0.5)` (S 0067f6b0), `cShadowQuality`
→ a map of `128 << trunc(q × 4)`, none at 0 (`ShadowManager::SetQuality` S 00769600; 512 and 1024 were added as
allowed sizes). The original's step down at 32 MB of free texture memory and its shadow flags and technique
(Scene +0x30 / +0x34, S 0088d6bc) are not carried. The default level stays 6; the original's default slider value
was not traced.

### 8.5 Minimap and previews [draft]

- The minimap's world picture is a top-down render of terrain, the map objects drawn at detail 0 and water into a
  512 × 512 target, as the original makes it (`RenderOverviewTexture`, RE §5; hud-panels §3.7), rendered once;
  territory, objects and symbols are drawn by the UI from views. It is `MinimapOverview`, a `SubViewport` sharing the
  match's world, rendered once with `UpdateMode.Once`: its camera's cull mask is `RenderLayers.Overview` (bit 10, set by the
  terrain chunks, the water meshes and the batches of map objects drawn at detail 0) plus the shadowless sun and the marker
  `RenderLayers.OverviewMarker` (bit 18), by which the shaders drop the fog, the fog of war and the mirror
  (`shaders/sadk/overview.gdshaderinc`). The map objects out of the main view are held in their batches for the frame of the
  render (`ObjectLayer.HoldAll`).
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
- **Levels of detail** [the original's rules: [../sim/animation-models.md](../sim/animation-models.md) §3.14]: faithful,
  the set's `mesh` .. `mesh3` switched at eye distance 30 / 40 / 60 without hysteresis or cross-fade, clamped to the
  set, the same level in the shadow and mirror passes. The original's levels are automatic vertex-removal decimations
  with fixed budgets (heads collapse at LoD3). Refined: Godot's levels generated from LOD0, which compare as good or
  better at the same triangle count (asset browser, "Compare levels of detail", 2026-10-15: at LoD3 the original
  stretches the texture across the merged eyes, Godot keeps nose and both eyes) and index LOD0's own vertices, so one
  skin and one animation table serve every level. Godot halves per level (4480 → 2240 → 1120 → 560 → 280), so the
  refined set takes the levels nearest to the original's counts at the same distances.
- Animals, ships and oxen use the same path with their own shaders (`animals.fx`, `ships.fx` player-colour weight,
  `donkey.fx`).
- **Unseen characters cost nothing**: their visibility notifier takes them out of their batches (§4.7), so neither
  their vertices nor their interpolation are processed; the pose is computed from the clock in the vertex shader, so
  a character shows the right point of its clip the moment it comes back into view.

### 9.1 As built [implemented, sadk-remake 5aa8e1b]

- **Feed** (`Core.Game.Rendering.Characters.CharacterLayer`, the map layer `core.game.characters`, order 600):
  `Add(id, CharacterSpec, tick, CharacterPose)` gives the first sample (previous = current, so nothing glides in);
  `Sample(id, tick, pose)` once per tick in which the character moved (previous ← current ← the new sample); `Remove`;
  `Play(id, ClipRequest(clip, startTick, once, speed))`; `PlayType(id, type, startTick, once?, item?, building?,
  speed)` resolves the clip by the original's lookup order (building, profession, carried good, default, with the
  tribe-mask test; `AnimationChoice`). `CharacterSpec(Family, Type, Owner, TribeId)`: families `settler`, `ox`, `animal`,
  `ship` in an open registry (`CharacterFamilies.Register`); `Type` is the settler definition name, the animal's element
  name, the ship's tribe. `CharacterPose(Position, Heading)`, the heading being the original's yaw. The clock
  (`CharacterClock(Tick, Alpha, TickInterval)`) shows `Tick − 1 + Alpha`, one tick behind.
- **Data**: `CharacterSettings` reads `settler_config.xml`, `settler_animations.xml` (events, idle groups), `animals.xml`,
  `ships.xml` and `globalSpeed`; executable defaults only with their address.
- **Baking** (CPU, once per skeleton per render context, `BakedSkeleton`): clip 0 is the rest pose, then every clip at
  its own key times, three columns of `inverseBind × world` per bone, in an RGBA32F texture at most 4096 texels wide,
  plus a clip table of first frame, key count and length. The loop mode is per request, not per clip: one file plays
  both once and looping (WorkLoop0 against StandFish; a carrier's boat clip loops). Sizes: the settler skeleton has 46
  bones and 87 clips (86 files and the rest pose), 11,566 frames, 4002 × 399 texels, 24.4 MB, driven by the long work
  clips (fishing 60 s = 1080 keys, work_well 38.75 s); animals 0.2–1.4 MB, the ox 2.7 MB. RGBA16F would halve it at about
  0.05 % relative error (not done). Meshes bind their bone lists to the skeleton by name; characters with the same
  meshes and textures share one look and its batches.
- **Layer**: batches per (look, level, region) with dense slots; per-frame interpolation of the characters in view
  only; the level by eye distance (30 / 40 / 60 from the data, compared with ≥, no hysteresis); a node-free visibility
  notifier per character whose box covers the last step, moved once per tick, grown by the margin and the shadow reach
  (bounds: the bone bounds over all baked frames, grown by the largest |p × inverseBind| of each vertex's main bone); a
  `CharacterNode` proxy per character with inspectable state; samples put on the ground once per tick and the height
  interpolated in between (the remake's choice).
- **Palettes**: settler palettes in the original's 1024² atlas, packed in its order; blocks freed and reused.
- **Shaders**: `sadk/skin.gdshaderinc` (engine); `characters/settler` after `skin_color_mesh.fx` (the index map read at
  the nearest mip with red decremented, the light inside the palette lookup, owner colour, specular, fog; the colour is
  computed in `light()`); `characters/animal` for `animals.fx` and `donkey.fx` (the original light model, alpha ≥
  128/255); `characters/ship` for `ships.fx`; all in `fx-map.xml`. Each vertex does up to 4 influences × 3 texel fetches,
  twice when blending keys; zero weights are skipped.
- **Pitfall**: an RGBA8-unorm `CUSTOM0` next to an RGBA-float `CUSTOM1` gave `CUSTOM1` wrong components on Compatibility
  (torn hands and arms); both are RGBA float.
- **Settings**: `CharacterLod` (Original, the default; Refined = Godot's levels of LOD0 at the triangle counts nearest
  the original's: egypt_1 4396 / 1196 / 596 / 296 against 4396 / 1098 / 548 / 274) and `CharacterOwnPhase` (off; the
  global `sadk_anim_own_phase`).
- **Measured** (Compatibility on a CPU renderer: draw calls and CPU times only): 1000 walkers in view, 79 batches, 676
  draws, 2.12 M primitives with notifiers (696 draws, 2.20 M without); interpolation, levels and slot writes 0.7–1.1 ms
  per frame for 1054 characters (the proxy nodes 0.15–0.2 ms), batch uploads 0.12–0.15 ms (about 22 buffers), a motion
  sample about 1 µs with its ground height.
- **Answered while building it**: AM §10 Q11, `PLAYER_COLOR_WEIGHT` is the index of the mesh subset drawn
  (`S2CG::Ship::OnMaterialChange` S 006a49b0 from the index `SkinnedMeshRenderer::RenderInstances` S 0076e8a0 passes;
  `PLAYER_COLOR` from `Ship::BeginRender` S 006a4ae0; the shipped ships have hull 0 and sail 1). AM §10 Q1 [inferred
  from the pictures]: with the stored quarter-turn inverse bind, a settler turned by `RotationY(h)` faces (sin h, 0, cos
  h) in the original's axes. Data: the Bavarian ship's idle file holds no animation (the original plays none either);
  three ramp tables written without the `[data]` prefix resolve below `[data]`.
- **Built since**:
  - *Facing* [implemented, sadk-remake d42fb7c]: the turn toward a target yaw by at most 0.43982297 rad per tick with
    the original's wrap and snap (`UpdateFacing` S 006c48c0, `WrapYaw` S 006c4a40) for settlers and the ox
    (`CharacterTurn`, in `CharacterEvasion`), animals (S 006cde40 / S 006cdee0, the step direction taken between
    cells, no turn while dying) and ships (S 006a4eb0 / S 006a4f50). A new figure takes a random hex direction
    (`RandomizeInitialFacing` S 006c53f0, its own generator seeded 0x7c0); a hammering builder faces its site's
    entrance or its ship (`CharacterConstructor::Update` S 006c8480); a worker idling outside faces its workplace's
    flag (the look-at cell, S 006c7640), after the ship it waits for (S 006c7140); a carrier turns to the stack it
    puts down on or picks from; a standing soldier faces its opponent (`FaceEntity` S 006c7b10, through
    `ISoldierView.Opponent`) [implemented, sadk-remake 9fb619f]. Measured on Steinfjord: a builder's yaw is on the
    entrance in 214 of 240 ticks of a construction. `se_NPCLookAt`
    (S 005ae660) waits for the NPC component; the facing along a street's spline came with the route splines.
  - *Trees fall* [implemented, sadk-remake 1fd328c]: `DepositGrowth.StartFalling` starts the fall once the work has
    run more than 3.0 s: 24 ticks at `globalSpeed` 1.8, speeding up ×1.2 per tick, ending at a quarter turn (the tree
    lies at about 81.6° with the previous tick's angle, [inferred]), then sinking lying down; the axis as the
    original's (RE §3.11). Which objects fall is data (`fells`, §5.2). It raises `DepositGrowth.FallStarted(deposit,
    position)`, which the world sounds use. The angle steps once per tick; interpolating it per frame through
    `INSTANCE_CUSTOM.y` (§7.4) is `[TODO]`.
  - *Hidden figures* [implemented, sadk-remake 9fb619f]: a figure is drawn only while its logic cell is explored or
    the fog of war is off, it is not aboard a ship, and it is not inside a building unless it plays a work type 4..6
    with time left (`CCharacter::IsInFrustum` S 00690f80; the inside flag of `UpdateInsideBuildingFlag` S 006c7590,
    the soldier's `IsPresentInBuilding(true)`, cleared for carriers and when the building goes, S 006c7040); an
    inside work clip stands at the terrain height under the centre of its posed box (this frame's box; the original's
    is the previous frame's); leaving a ship collapses the interpolation (S 006c4870). The proxy shows Explored /
    Inside / Aboard / LogicVisible and the report counts the hidden. The notifier box is the look's bounds, not the
    original's 10× radius for inside work.
  - *Death sinks*: settlers 0.35 per second once the clip has no time left, through the movement's height pair
    (S 006c7640, S 006c4f40, S 006c57b0; the render logic is skipped in state 6); animals 0.4 per tick-second after
    `Dying`, added after the terrain snap (S 006ce2c0, S 006ce610).
  - *Route splines*: each street's spline at `StreetAdded` (sea level for water streets), `SetPath` S 006c5160 with
    its street or own spline for free walks of more than two cells, `StepAlongSpline` S 006c4d90 forward and
    backward with the tangent's yaw, `RouteSpline::EvaluatePosAndTangent` S 006d7280 with its extrapolation; the
    straight step runs in the logic update after the latch, as the original. A segment past the end falls back to the
    straight step (the original would read out of range).
  - *First work tick and the door* (`SettlerFeed`): the door test uses the clip and key the figure played before
    (`HasSlotOverrideForCurrent` S 006c61a0), an endless loop opens no door, and the animated building is the render
    logic's target building (S 006c88c0).
- **Not built yet**: idle variations (§3.11 of AM; the data is read), tools in hands (the animated tool and `bWorking`, S 006c8ab0), boats and boat bobbing (render
  logic slot `+0x1c`, movement `+0x135`), swim types (`IsBelowWaterLevel` S 006c4820), the soldier buff emitters
  (S 006c7f80), the `SettlerSpeed` effect (S 006c4f40 / S 006c57b0), the two-bone Low technique (Q16). The fog
  of war came with §4.5 (as built). Open: the atlas's untouched texels (Q15; the remake starts them transparent
  black).
- **Gallery**: `core.game.charactergallery {map, tribe (Bavarian by default), clip, owner, walkers, field, view=grid|
  first|walker|animals|ship|lod|field, lod, level, notifiers, ownPhase, stats, …}`.

## 10. Terrain [draft]

### 10.1 The mesh

- The mesh math is taken over from the retired testbed map viewer (`TerrainBuilder`; in git history), split into a pure builder (vertex and index arrays per region
  and pattern, no Godot) and a thin Godot backend: the original's triangle tables, four-fold subdivision, solid and
  blend patches per 4 × 4 block with transition-mask UVs, under-water tint, the pattern order of
  `terrain_static_data.xml` (RE §3.3).
- One mesh per region with one surface per pattern; materials per pattern with the pattern type's shader (§7.1).
  **The per-pattern patches stay** with the level of detail of §10.3 (maintainer, 2026-10-15): every pattern type
  keeps its own shader from `types.xml`, mods' types included; the levels change the patches' geometry, not the
  layering.
- `MapChanged(Heights | Patterns, rect)` rebuilds the regions touched plus one block of margin on a worker thread;
  the result replaces the region's mesh on the main thread. Ground decals, streets and object heights in the
  rectangle are re-laid.
- Unexplored blocks are drawn flat black by the fog include, with depth.
- **One height function**: the renderer, the picking and object placement use the plane of the drawn terrain
  triangle (the retired viewer's `MapGeometry.TerrainTriangles`). The viewer's `HeightAt` interpolates bilinearly per row
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

- **One cubic patch per fine triangle, for the height only**, so the surface stays a function of x and z. **The edges
  follow their own lattice lines** (maintainer, 2026-10-15: "non-linear offset interpolation by using neighbors and
  next-in-line comparisons"): every fine-triangle edge A→B lies on one of the triangle lattice's three line
  directions; its curve is a cubic Hermite in the height whose slopes are Catmull-Rom differences along that line,
  `m_A = (h(B) − h(A − u)) / 2` and `m_B = (h(B + u) − h(A)) / 2` with the next-in-line samples `A − u` and `B + u`
  (one-sided at the map border). The interior is the cubic Bézier triangle bounded by those three curves, its centre
  control height by the PN-triangle rule. Slopes per line instead of one gradient per vertex (an average over all six
  neighbours) keep a ridge along one line sharp across it. The result:
  - an edge's curve depends only on the samples of its own line, so neighbouring triangles meet without cracks;
  - collinear samples give a straight edge, so ramps stay straight;
  - the surface passes exactly through every sample, so objects standing on sample vertices stay on the ground;
  - where the gradients equal one plane's slope the patch is that plane, so a flattened building plot stays flat
    inside.
- **No overshoot** (the next-in-line comparison): where the steps on the two sides of a vertex along a line differ in
  sign or one is zero, the slope there is 0; otherwise it is limited to three times the smaller step (Fritsch–Carlson),
  so no ridge or dip appears that the samples do not have and plot borders stay crisp.
- **What it is not**: the surface reconstructs the same height samples more cleanly (as bicubic upscaling does an
  image); it adds no information. Detail finer than the samples (rough rock, rippled sand) is for later, through
  displacement maps per pattern (maintainer, 2026-10-15), added on the CPU like the rest of the surface.
- **A baked normal texture** at a finer resolution than the fine grid (e.g. 4×), computed once on the CPU from the
  curved surface (and on height edits), carries its light into the terrain shaders, so even the settings without extra
  triangles show the curvature in the light at one texture read per pixel (principle 14).
- **Normals** come from the patch's derivative, so the light runs smoothly across the former facet edges.
- **Density**: the setting **Terrain detail** splits each fine triangle into k² triangles, every edge into k equal
  parts (an even split exists only for k², so there is no "double" step):

  | Setting (maintainer, 2026-10-15) | k | Terrain triangles near the camera | Surface |
  |---|---|---|---|
  | Faithful | 1 | 1×, the original's three levels by distance (§10.3) | the original's flat triangles |
  | Low (the default, maintainer 2026-10-16) | 1 | 1× | cubic patches (smoothed shape and light, no extra triangles) |
  | Moderate | 2 | 4× | cubic patches |
  | High | 3 | 9× | cubic patches |
  | Very High | 4 | 16× | cubic patches |

  A triangle splits evenly only into k × k parts, so there are no 2× or 8× steps.

  Every level lights per pixel, as the original's terrain shader already does: normals interpolated across the
  triangles plus the pattern's normal map. In the curved levels the vertex normals come from the patch's derivative.
  Smoothing the light alone, without the extra vertices, changes almost nothing: the interpolated normals already hide
  the facets in the light; what shows them is the shape (ridgelines, hilltop outlines, the turn of a slope away from
  the sun, how objects sit on the ground). The density is uniform over the map, so regions never meet at different
  densities (no T-junctions). If Smoothest everywhere proves too heavy, k = 4 near the camera and a lower k farther
  out, with stitched region borders as the original stitches its LOD levels (RE §3.3), is the fallback.
- **Computed on the CPU, stored in the vertex buffers** (principle 14): the mesh builder evaluates the patches on a
  worker thread when a map is shown, with `TerrainSurface.HeightAt`'s formula, and writes final positions and normals.
  The vertex shader only blends: each vertex also carries its position and normal at the next coarser level for the
  refined settings' geomorphing, and a stitchable edge vertex its averaged alternative for the faithful stitching,
  chosen by the neighbour's level. A change of density rebuilds the blocks in the background; the finest levels exist
  only for blocks within their band.
- **Height edits** (`MapChanged(Heights, rect)`) rebuild the blocks touched (plus one vertex of margin for the
  gradients) on the worker thread.
- **Everything on the ground uses the same surface**:
  - `TerrainSurface.HeightAt(x, z, mode)` in C#, float32, the same formula as the shader: object placement, settler
    and animal height snapping, picking;
  - ground decals are clipped against the original's triangles, cut along the finest level's lattice and laid on it, and
    the terrain keeps that level under them (§10.3 "Kept ground", §13.1); streets, crossings and selection markers are
    laid on the surface at their own vertices (streets keep a reduced form of the original's depth bias, §15) [the streets
    and markers do not keep the levels];
  - the water's shore fade reads the smooth height; the border skirt keeps the original's one map-wide edge height
    (§11), which does not depend on the surface.
- **The simulation is untouched**: it keeps the fine height grid and its rules; the smooth surface never reaches it.
  It is a presentation switch like per-pixel lighting ([binding] RR §2.3, faithful look plus a refinement).
- **Cost**: Smooth draws four times the terrain triangles (the viewer's close view: about 236 thousand → 0.95 million),
  Smoother nine times (2.1 million), Smoothest sixteen times (3.8 million), and the shadow and mirror passes draw them
  too. This is where the GPU time saved on shadows
  (§8.4) goes. The numbers are to be measured with `core.game.mapview` before the defaults are fixed.
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
  the band distances are settings. Not Godot's visibility ranges for the blocks: they measure from the camera in 3D
  to the box centre, not from the original's eye point horizontally, and the stitching needs each neighbour's level,
  which the shader cannot learn from Godot's choice. They do serve the far band of the refined look: a region drawn
  whole at the coarsest level as the `visibility_parent` of its blocks replaces sixteen draw calls by one where the
  blocks are already morphed to that shape, so the switch shows nothing.
- **No cracks**: a block next to a coarser neighbour moves its border vertices onto the neighbour's coarser edge in
  the vertex shader (the neighbours' levels come with the instance), the same idea as the original's stitching,
  which replaces odd edge vertices by the average of their neighbours (RE §3.3).
- **No popping**: in the outer part of each band the vertex shader blends every vertex between its position at the
  block's level and at the next coarser level (geomorphing, as in the CDLOD terrain technique), so the change of
  level is not seen.
- **Drawn per block**: the levels are chosen per block (the original's unit), so the patches are drawn per block,
  with the block's level, its neighbours' levels and the morph factor as instance uniforms; the heights come from the
  textures (§10.2). The far band of the refined look draws whole regions as visibility parents of their blocks.
- **The layering stays in patches** (maintainer, 2026-10-15): each block's solid and blend patches are built per
  level; per-pixel layering in one shader (texture arrays, a shader generated from `types.xml`) was weighed and set
  aside: about three times the work, the faithful layering to be proven again, and its gain (fewer draw calls) is not
  the limit today.
- **Shadows and the mirror view** choose their own, coarser levels (the far cascades and the reflection need less).
- **Faithful** reproduces the original's own terrain LOD exactly (maintainer, 2026-10-15): its three levels per block,
  its selection (RE §3.3), its stitching and its hard switch, popping included. The refined settings morph instead.
- **Kept ground.** Under every building's and harbour place's plot every refined terrain detail keeps its finest level at
  every distance and does not blend it [implemented, sadk-remake e8a00c0]. A house stands at its levelled height (the simulation's
  vertex height at its cell) and its plot is laid on the finest level; the coarser levels the terrain blends to away from
  the eye do not keep the levelled ground, so without this the ground moved under the house and the plot by up to 0.5 to
  0.75 units (the sawmill at (47, 58) of `MP_2P_steinfjord`, every detail, the selection point swept out to 600 units; up
  to 0.29 to 0.74 with the eye within 100 units). The owners of the plots claim their decal's x, z box in an open registry
  (`FinestGround` on the map data, `DecalMeshes.Claim`: the buildings' plots, ruins and upgrade targets, the harbour
  places' plots; any owner may claim ground under its own key); the terrain keeps the blocks the box, grown by one fine
  step, reaches into (`TerrainMesher.BlocksUnder`), counted per block. A kept block takes the band scale
  `Never / blend start` for every level, the mechanism `Terrain lod="Shape"` uses for rocks: its band and the blend of
  every vertex it holds (its edge vertices included, by the largest scale of the blocks sharing them) reach no distance, so
  it is drawn at level 0 unblended. Its neighbours keep their own bands; an edge toward a coarser neighbour is stitched to
  that neighbour's unblended edge, which changes only the kept block's triangles along that edge, hence the grown box. A
  claim or a release rebuilds the kept blocks and their eight neighbours with the next batch, like a height change. The
  faithful look keeps the original's levels and ignores the claims.
  Cost per plot (the sawmill: 2 blocks kept): with the eye far away 1.5 k more triangles at Low, 7.9 k at Moderate, 34.6 k
  at Very high (the kept blocks at level 0 and the rings the one-level neighbour rule draws around them); building a kept
  block at level 0 takes about 0.7 ms at Low, 2.7 ms at Moderate, 10 ms at Very high on a worker, once per claim or height
  change, no per-frame work. A kept block's level stays in the CPU cache as its wanted level: 46 KB at Low, 181 KB at
  Moderate, 713 KB at Very high per block.

### 10.4 As built [implemented, sadk-remake 1135c7c]

**The mesh.**
- Patches (solid/blend per pattern, rank order, transition-mask UVs) are built once per block (TerrainMesher); a level only
  sets how finely each cell triangle is split: its vertices are the lattice points (i, j), i + j ≤ N, of the cell
  triangle (corners at the cells' sample vertices), placed on TerrainSurface on the CPU. N = 4, 2, 1 are exactly the
  original's levels 0, 1, 2 (rendering.md §3.3); the refined levels add N = 8, 12, 16.
- Draw unit: per region (regionBlocks × regionBlocks blocks) one mesh of the blocks at the fine grid or coarser, and one
  "near" mesh of its blocks finer than the fine grid; each a solid (shadow-casting) and a blend MeshInstance3D, one
  surface per pattern. Draw calls stay at the faithful look's level (Steinfjord: 1089 vs 1082 near, 3033 vs 2847 far).
- Rebuilds: each frame the selection's changes go out as one batch (the regions and near meshes whose blocks changed
  level, stitch or neighbour level); its CPU work runs in parallel on workers, the Godot meshes are made after, and the
  whole batch is swapped in in one frame. The first picture is built synchronously in the layer's first frame
  (Steinfjord, 6 cores, Compatibility renderer: Faithful 279 ms, Moderate 572-733 ms, Very High 0.9-1.0 s). A jump of the
  view is stepped the same way: the camera controllers say when they put the camera at another place at once
  (`WorldRenderer.JumpView`: the match camera's `FocusOn` for a minimap click, a good button, a message and the start,
  its home key, the free camera's `JumpTo`), and the terrain layer reads `WorldRenderer.ViewJumped` in that frame
  (the renderer clears it after the layers' frame). The levels of the new place are built on the workers and waited
  for, and the batch is swapped in before the frame is drawn. Only the regions whose signature changes are built (the
  place left and the place reached), not the map. The geomorph is a function of the eye alone (§10.2), so on meshes made
  for the new eye it shows the steady state and nothing reshapes after the jump. Scrolling, orbiting and zooming never
  jump, however far a slow frame moves the eye: they keep the asynchronous path. The jumps and the longest one's
  main-thread time are in the map view's statistics (`--stats`: `jumps=N worst jump=M ms` in the terrain part of the
  `STATS` line); measured on the real GPU machine: 95-139 ms per jump (at Low, Compatibility renderer, 6 cores,
  MP_6P_ship_ahoi: 115-180 ms).
- Memory: only the dense levels (finer than the fine grid) are kept on the CPU (the wanted level and one either side,
  prefetched one hysteresis ahead); the original's levels are built again with each batch. Measured on Steinfjord
  (vertex buffers / normal texture / CPU at rest):
  Faithful 10.9 MB / – / 0; Low 22.0 / 8.6 / 0; Moderate 27.7 / 8.6 / 20 MB (36 MB while turning);
  High 29.8 / 8.6 / ≈25 MB; Very High 35.9 / 8.6 / 48 MB (83 MB while turning). Icebound similar (normals 6.5 MB).
  Measured again with the threaded rebuilds (sadk-remake 8f4adb3): Faithful 10.8 / – / 0, Low 22.0 / 8.6 / 0, Very
  High 35.0 / 8.6 / 49 MB.
  Triangles: Faithful 320k (the whole map at the fine grid would be 866k), Low 350k, Moderate 492k, High 551k,
  Very High 710k.

**The smooth surface** (the maintainer's formula, 2026-10-15).
- Every fine-triangle edge lies on one of the lattice's three lines. Along an edge A → B the height is a cubic Hermite
  curve with Catmull-Rom slopes from the samples next in line (P₋₁ = A − (B − A), P₂ = B + (B − A); one-sided at the
  map's border), limited monotonically (Fritsch–Carlson: slope 0 where the two secants differ in sign or one is zero,
  else at most 3 × the smaller secant). Inside: the cubic Bézier triangle with those edges (edge controls a third of the
  way along: corner + slope / 3), centre control by the PN rule, limited to the corners' range. Properties (tested):
  through every sample, crack-free shared edges, no overshoot (monotone across a step), level plots stay level, a
  straight ramp stays straight, ridges along one line stay sharp across it.
- Normals: per grid vertex the average of the surrounding patches' derivative normals; between vertices the PN-triangle
  quadratic normal field over those (continuous across edges, so the light has no facet seams). Faithful keeps the
  original's stored vertex normals interpolated.
- Baked normal texture (all refined settings, Low included): the smooth surface's normals at 4 texels per fine step
  over the map's extent, RG8 (x and z; y follows), with mipmaps, baked on the CPU on a worker when a map is shown
  (Steinfjord 115 × 115: 1843² texels, 8.6 MB with mipmaps; Icebound 6.5 MB). The terrain passes read it once per pixel
  in place of the interpolated vertex normal (tangent made from it as the vertices' is); globals sadk_terrain_normals,
  _normal_rect, _normal_on (core.game's). **Per level** [implemented, sadk-remake e94cc01]: the original lights each
  level with the stored normals of the height samples that level keeps, interpolated over its triangles (RE §3.3), so
  the texture lights only the levels that keep every height sample (global `sadk_terrain_fine_levels` gives their
  count; the vertex's level goes in `UV.x`); the last such level fades over to its vertex normals while it blends
  into the coarser one, and coarser levels use their vertex normals only. A rock needle that a coarser level drops
  no longer keeps its light there.
- Everything on the ground uses the same surface: MapGeometry.HeightAt follows the drawn surface (HeightMode set by the
  terrain layer), so object placement, picking and the camera use it; objects are placed again when the surface
  changes. The border skirt does not follow it: it keeps the original's one edge height from the stored samples (§11).
- No height or gradient texture is read per vertex: the vertex shader only blends (§10.3).

**Levels by distance.**
- Chains: Faithful 4/2/1; Low 4/2/1 (smooth); Moderate 8/4/2/1; High 12/4/2/1; Very High 16/8/4/2/1. The original's
  lodDistance L = <Landscape lodDistance> (graphics.xml, 50; read into GameSettings.LandscapeLodDistance, 0 if absent as
  the exe) · (groundDetail · 5 + 0.25) + 1.15 · √((4 stepX)² + (4 stepZ)²) = 271.6 at the top preset (groundDetail 1).
  `groundDetail` is the options panel's ground detail (`SetDetailFactor` S 00688220, §19) [implemented, sadk-remake
  726a5b1]; a change rebuilds the terrain. Band ends: N = 4 at 0.5 L (135.8), N = 2 at 1.5 L (407.4), N = 1 beyond; the refined finer
  levels at 0.5 L · 4 / N (N = 8: 67.9, 12: 45.3, 16: 34.0).
- Faithful selection = the original's: from eye = camera + 0.7 (target − camera), XZ distance to the block's box
  centre, lod = min(2, trunc(d / L + 0.5)), every frame for every block, no hysteresis, hard switch (the batch makes the
  switch visible one or two frames after the original would: geometry exact, timing by a frame). Stitching: of two
  neighbours with different levels the finer stitches, levels 0 and 1 only; a stitched edge's odd vertices take the
  average height and normal of their two edge neighbours, the tangent and the rest stay (the original's AddPatch).
  Shadows and the mirror draw the same levels (the same meshes).
- Refined selection: XZ distance from the same eye point to the block's nearest point; a block steps coarser only
  24 units (one block) past its band's end and finer as soon as it is inside the finer band; neighbours are kept within
  one level. Every vertex of a refined level carries its next coarser level's position (CUSTOM0.xyz, RGBA float) and
  normal (CUSTOM1.xyz), and the distances where it starts and completes blending toward them (CUSTOM0.w, CUSTOM1.w: the
  last 40 % of the band); the vertex shader mixes by the vertex's XZ distance from the eye point (global
  sadk_terrain_eye): one distance and two mixes per vertex. A finer block's edge toward a coarser neighbour takes the
  neighbour's own edge data (position, coarser position, blend distances), so the two move together and no crack
  opens at any blend state; the switch happens only where the vertices are fully blended, so nothing pops.
- Not used: Godot's visibility ranges for the far band (regions already batch it; no draw-call gain) and HLOD.
- Map view: levels=true colours the levels, wire=true shows Godot's wireframe, stats=true adds the terrain's numbers to
  the STATS line, switchTo / switchAt change the setting while running.

**Levels that keep the shape** [implemented, sadk-remake 8f4adb3, 4c535b5]. The original chooses a block's level by
distance only (`TerrainCell::UpdateLOD` S 006b55e0: `min(2, trunc(d / L + 0.5))` from the box centre, no shape or
error term), so a rock needle on a vertex that level 1 drops (every second fine vertex) vanishes once its block is
past 0.5 L (135.8 units at the top preset), and the stitching averages an odd edge vertex next to a coarser block.
In Faithful this is a hard switch; in Low the shape blends from 60 % of the band, so the rock's height changes as the
camera moves. This is the original's behaviour and stays the default (`lod="Distance"`). The setting
`<Terrain lod="Distance|Shape">` (Options → Graphics, en/de texts) keeps each level of a block until what the coarser
level would remove is under 0.01 rad of height seen from the eye point (about 20 px at 1080p); the band then ends at
the larger of its usual end and `error / 0.01`. Vertices on shared edges blend with the larger scale of the blocks that
hold them, so no crack opens; Faithful + Shape keeps neighbours within one level. Its band data is measured again on
the main thread after a height change, marking the blocks it affects. Cost (triangles, Distance → Shape): Steinfjord
Low 348k → 717k (vertex buffers 22.0 → 38.6 MB), Faithful 317k → 408k, Very High 686k → 1055k; Icebound Low 325k →
554k. Whether Shape becomes the refined details' default is open (§24).

**The setting** (§19): <Terrain detail="Faithful|Low|Moderate|High|VeryHigh">, default Low (the maintainer's decision of
2026-10-16: the finer levels change the picture little, since the samples are already smooth at the game's distances
and the fine bands cover only the area around the focus; all levels stay selectable); Options (Graphics) and the map
view's quick switches; changing it rebuilds the terrain and the objects' placement.

**GPU cost**: per vertex the refined vertex shader does one distance, two mixes and a normalize; per pixel one RG8 texture read
and two cross products for the baked normal. Faithful: no blend, no texture read.

### 10.5 Map changes as built [implemented, sadk-remake 67b91c4]

- **Relay**: `MapChangeRelay` copies the changed grid parts into the shown map at once; the layers hear of them once
  per frame (`SimDriver.Advanced`, rectangles merged).
- **Heights**: the rectangle passed on is the samples that really changed plus 4 vertices; the simulation's rectangle
  carries a 16-vertex margin (castle placement: 40 dirty blocks with it, 16 without). `TerrainSurface.UpdateHeights`
  recomputes the normals only around the changed samples, in parallel.
- **Rebuild**: a dirty block keeps its level (no pop); a version check per block discards meshes that went stale while
  they were built. The baked normal texture (§10.4) is patched on a worker and uploaded whole (8.6 MB on Steinfjord).
- **What follows a height change**: the water (shore fade, regions, mirror request, the skirt at the map's edges); map
  objects are placed on the ground again; a building's base and ground decal are laid again; streets follow through
  their raw event, after the relay; border posts are laid again (§15.2).
- **Measured** (Steinfjord): a guard-house site at Low costs 1.5 ms on the main thread; 4 blocks and 2 region meshes in
  41 ms on workers; normals 11 ms on a worker, upload 1.6 ms. The levelling of both start castles touches 16 blocks;
  rebuilding their 48 member blocks takes 21–36 ms (Faithful, Low) and 220–335 ms at Very High in the worst case; the
  normal patch (445 × 92 texels) 31 ms.
- **Pattern changes** [implemented, sadk-remake c16efa5]: the simulation announces a pattern change at once
  (`MapChanged(Patterns)` over the cell; the sowing passes `defer = 0`, `../sim/map-resources.md` §3.4) and the
  relay copies the patterns; `TerrainMesher.PatternsChanged(rect)` makes the patches of every block holding a
  changed cell again (records and patches are replaced whole, so workers building the old ones stay consistent), and
  a pattern new to the map keeps the record it had from the start, so its draw order does not change.
  `MapData.Blocks.PatternIds` is not refreshed yet.
- **Pattern records** [implemented, sadk-remake e94cc01]: `TerrainMesher.BuildRecords` builds the records from every
  pattern property of the registry through `TerrainPatternRecords.Build` (`CTerrainPatternManager::Init` S 006bb3a0),
  shared with the viewer: non-aliases first in the original's swap-sort order by rank (`def+0` =
  `g_TerrainPatternNextId`, S 006bade0), then the aliases by ascending signed id, each linked to the first record of
  its target; an alias whose target has no record gets none and is not drawn, and an id without a pattern property
  gets an empty record. Materials are made only for the patterns the map uses (`UsedPatterns`), and the blend layers'
  render priorities are numbered densely over the used records (with 114 records `Order − 64` would have passed the
  water's priority). The ground-cover layer index of a record (+0x14) is not carried ([TODO] S 006bb3a0).
- **Off the main thread** [implemented, sadk-remake 8f4adb3]: rebuilds run on Godot's `WorkerThreadPool` at low
  priority; only the first picture is built at high priority and waited for. A batch region holding a block whose
  ground changed after the batch was planned is dropped and planned again, so a stale batch is never shown. Readers of
  the smooth normals take no lock: every result that overlaps a height change is versioned and discarded (the mesher,
  the normal patch, the first bake, which the pending patch follows, and the building decals, which are laid again).
  The water is recomputed only where heights change (a test checks it equals a full recomputation). Worst frame per
  2-second window while orbiting at 40°/s on Steinfjord (headless, CPU only; p50 / p90 / p99 / max): Low
  12.4 / 17.6 / 45.5 / 87.4 ms before, 10.7 / 14.7 / 34.9 / 53.4 ms after; Very High 12.7 / 17.9 / 29.9 / 51.1 →
  10.2 / 11.6 / 15.4 / 18.7 ms; the terrain's main-thread share at Very High 4.10 / 7.01 / 15.9 / 27.4 →
  2.76 / 3.38 / 4.07 / 4.41 ms. A building placement costs the terrain 2–5 ms of main thread per height change and
  the water under 0.5 ms (3.7–15 ms before). The rest of the placement hitch (frames of 35–74 ms) was the building
  type's visuals being read and built the first time one was placed (about 40 ms a type); the match's load now prepares
  every type its tribes can build (`BuildingLayer.Prepare`, sadk-remake 6a80842), as the original loads every
  `<Building>` of `buildings.xml` under "Loading building configs" (`Scene_LoadBuildingsXml` S 006821b0 →
  `RegisterBuildingType` S 006a2860 → `BuildingDesc::LoadFromXml` S 006d3880). The simulation's tick of a placement costs
  2–4 ms ([sim-boundary.md](sim-boundary.md) §4.3).
- **Garbage**: while orbiting at Low the rebuilds allocate about 257 MB/s (3 MB/s with a still camera), about 46
  collections a second with the longest pause per window around 5.5 ms (p50) and up to 25 ms; the remaining terrain
  spikes coincide with them. Exact-size arrays passed as spans halve the allocation but made the worst frame about
  1.5 ms worse at p50 and were not kept. The lever is caching the original's levels (below). `MapViewStats`
  (`stats=true`) reports the longest collector pause per frame, collections per generation and MB allocated per
  second.
- **Gaps**: the simulation never emits `MapChanged` for `GroundResources`; terrain levels are not cached, so a dirty
  region rebuilds all its blocks (caching them at Low would cost about 30 MB of CPU memory; open, §24); the normal texture's mipmaps are regenerated whole; a standing character is placed
  on the new ground only with its next motion sample.

## 11. Water, border, sky, environment [draft]

- **Water**: one quad per block whose lowest vertex lies strictly below the water level (`AddWaterTileQuad`
  S 006a7de0 with `IsMinHeightAtOrBelowSeaLevel` S 006b4f60), at `sadk_water_level`, batched per region (the viewer
  builds one mesh for the whole map); the quad spans the block's box and ends two vertex steps before its end
  (`EmitWaterQuad` S 006a6a40), the box's z ending at the block's last row (`TerrainCell::Init` S 006b61f0 adds the
  row overhang to y, not z); the original's water shader with its scrolling normal maps, the shore fade from the
  overlay, planar reflection (default), screen-space (option) or none. No water beyond the map: the original's two
  border-water techniques are never used (RE §3.5). [implemented, sadk-remake e94cc01: `WaterMesher`; block counts
  Icebound 423 → 419, Ship Ahoi 544 → 529.] The mirror request still uses the at-or-below test, a harmless superset.
- **Border skirt** [implemented, sadk-remake e94cc01, `src/Sadk.Client/Water/BorderSkirt.cs`]: the original's skirt
  (RE §3.5: `BuildMapBorderSegments` S 006a7fa0, `ComputeMapEdgeExtents` S 006a77d0, `RenderMapBorder` S 006a7400):
  one edge height for the map (the lowest edge cell), one segment per edge block plus the four corners with the
  original's coded extents, 200 units out; two black passes without depth writes or culling, the first sloped from
  the edge height down to the water level − 1, the second flat at the water level; drawn after the map's passes and
  before the water (render priority 9 in the transparent pass, `depth_draw_never`); rebuilt after a height change
  only when the edge height changes; not drawn in the mirror. Beyond the map the player sees black, and the water
  over the outermost three vertex steps looks darker where the flat pass lies under it, as in the original
  (`water_border.gdshader` and the `border` attribute of `water.xml` are gone). Whether the old look (water past the
  edge) or a lighter seam should come back as switches is open (§24).
- **Sky**: the remake's cloud layer to the horizon by default, the original's 633-unit dome as a switch; both driven
  by globals only (a sky shader reading `TIME` or `POSITION` re-renders the radiance every frame). The cloud layer
  is the main camera's in every view: the mirror view casts its rays from the mirrored eye into the main camera's
  layer, as the original draws the main camera's dome in its mirror (RE §3.13).
- **Environment**: `EnvironmentService` reads the map's environment (the `.bin` contents in the map package) and
  blends its spheres per frame by the original's focus point, `(60 × hit + d × camera) ÷ (60 + d)` of the screen-centre
  ray's ground hit and the camera (`Camera_GetGroundFocusPoint` S 0068ce50, ported with `Terrain_RayHitGroundApprox`
  S 0068a610), not the look-at point (RE §3.13: squared distances compared, weight 1 inside the inner radius, linear
  to 0 at the outer, a sphere exactly at the outer radius counted with weight 0, every weight multiplied by
  `(float)(1 ÷ count)`, the rest from the map's default); with inner = outer the remake gives weight 1 where the
  original divides 0 by 0 (a stated presentation-only deviation). It sets the light, fog and colour globals and the
  sun's direction and shadow factor.
- **Refined water** [implemented, sadk-remake, 2026-10-25]: `RenderSettings.WaterLook` is `Original` (the default) or
  `Refined`. `water.xml` declares the looks: `<Look name="Refined" shader shore="3">` with `<Reflection>` variants (the
  shaders `water/refined.gdshaderinc`, `refined`, `refined_plain`, `refined_ssr`) and `<Value>` tunables
  (`depth_absorption`, `depth_opacity`, `fresnel_f0`, `foam_width`, `foam_strength`, `foam_color`): the colour and
  opacity follow the water's depth, the reflection's weight follows a Schlick fresnel term, and foam lies along the
  shore. The shore comes from `ShoreField`, baked on the CPU: an exact Euclidean distance transform of the land mask at
  4 texels per cell step, reaching 3 cell steps from the shore, stored as R8; a height edit updates only the window it
  touches. Foam around objects in the water (from the screen depth) is a later option.

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

- **What the original draws at all** ([../sim/rendering.md](../sim/rendering.md) §3.11): no LOD meshes, but a
  priority gate (an element is drawn only if its `priority` is at most the detail level, 0 or 1 by preset, so
  priority 2 to 4 elements such as grass and small plants are inferred never to be drawn in the game) and a size cull
  (small objects vanish at a distance by `objectDetails`). **Not taken over** (maintainer, 2026-10-15): the size cull
  makes objects pop in, which looks worse than the cost it saves, and the priority gate is left out with it; the remake
  draws every element at every distance. The LOD plan for characters and buildings (§9, §13) is agreed.
- Godot's generated levels do not serve map objects or buildings: its simplifier prunes small separate parts, so a
  tree loses its leaf cards (almost the whole crown) and a building gets holes in walls and frames (asset browser
  comparison, 2026-10-15). Buildings keep the original's `LOD0` parts (§13); the `…LOD0` files some trees have are
  the candidates for a refined distance level of map objects, which the original does not use.
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
  original's threshold in the opaque pass. Alpha to coverage is on every cutout: the map objects, the houses, the ships
  and their frames and the animals; it has an effect when MSAA is on (§19). They need no sorting, write depth,
  cast their own shadows (no shadow-only copies) and appear in the opaque picture. The original's blending softens only
  the filtered edge pixels (the leaf textures have one-bit alpha); in the viewer the difference is barely visible.
  The switch "Blended foliage (original)" draws them blended, sorted back to front per batch, with the shadow-only
  cutout copies of §7.1.
- Growth and fades are written into the instance data per tick and interpolated in the shader with `sadk_tick_alpha`
  where the original fades within a tick.
- **Flags as built** [implemented, sadk-remake 67b91c4]: the owner's colour by the rule `lerp(colour × 1.8, texture,
  alpha)`, drawn opaque (the original's flag passes have no alpha test); `z_harbor_flag_00` when the flag view's
  `IFlagView.Harbour` is set (added for this; the original tests the harbour reference id at flag +0x17c, RE §3.2).
  Gap: the original announces a flag again (removed, then added) when a harbour is linked to it (`LinkNavyObject`
  S 00669e60), which swaps the model; the remake emits nothing then, so such a flag keeps the plain model.

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
  `<mesh>LOD0` part as a performance switch. Switched by Godot's visibility ranges (maintainer's suggestion,
  2026-10-15): the full part and the `LOD0` part are two mesh instances of the building's node with adjoining ranges,
  without margin in the faithful look (the original switches hard) and with a margin as hysteresis in the refined one
  ([godot-capabilities.md](godot-capabilities.md) §11).
- **Door and work clips**: `Animation` resources converted from the building's clips, two layers per building (slot 0
  door, slot 1 work) on disjoint bones (the conversion records each bone's layer per building model), so the two
  play at once without blending (an `AnimationTree` with both, or one player per layer).
  Triggered by `ActionTimerStarted` of the worker and by settlers passing `enterDistance` (presentation logic over
  motion samples), as RE §3.9 describes. While a building is out of view, its visibility notifier (the layers' shared
  `NotifierSet`, a RenderingServer notifier per building) switches its players off; on `screen_entered` each player seeks to `(clock − clip start) mod length`, so the clip
  shows where it would be by now (`VisibleOnScreenEnabler3D` would resume where it stopped instead). Notifiers ignore
  shadow passes, so the shadow of a building just outside the view may show a held pose
  ([godot-capabilities.md](godot-capabilities.md) §6).
- **Ground decal**: the `GROUND` mesh clipped against the terrain triangles under it and laid 0.01 above (the viewer's
  `Placement.GroundDecal`), on a worker thread; rebuilt when heights change under it.
- **Fires**: `toInt((1 − hpRatio) × firePoints + 0.5)` emitters `BuildingFire` at the fire-point nodes `FIRE_03`,
  `FIRE_06`, ... (every third from 3; `FIRE_00` is never one, RE §3.9), else at five points drawn from the
  fallback-fire stream.
- **Military flags**: their own small kind (`MILFLAG` bone, mesh by soldier count and kind, texture by proximity
  zone, owner colour, wave in the vertex shader).
- **Demolition**: dust effect, then `y = terrain − height × progress²` with `progress += dt × 0.35`, then removal;
  **ruins** with the dead building's ground decal until the remains are removed (`burnTicks`).
- **Building sites and farms**: goods on the site (§14) and farm animals at `boneLink<i>` bones by productivity.

### 13.1 As built [implemented, sadk-remake 6885d9e]

- **Feed**: the simulation implements `IBuildingSource.Connect(IBuildingSink)` and hands over every building, then
  feeds `Add(BuildingSpawn)`, `AddRemains`, `Update(id, BuildingState)` (every tick while constructing or upgrading,
  else on change), `Remove(id, Vanish | Demolish)`, `Door(id)` and `Work(id, duration, offset, speed)`
  (`Core.Game.Rendering.Buildings`, `src/Sadk.Client/Buildings/BuildingFeed.cs`). `BuildingState` keeps the original's two
  construction phases (`Frame = 1 − remainingB`, `Build = 1 − remainingA`, `FromRemaining`), an upgrade, health (the
  fire level comes from it), the military flag and the selection; the layer runs the demolition sink itself after
  `Remove(Demolish)` (0.35 per second).
- **Nodes**: one `BuildingNode` per building under the renderer's pausable `Animated` node, inspectable (type, tribe,
  stages, cut height, colour slot, flag, fires, demolition, in view, clip); part 0 on a `Skeleton3D` bound with weight 1
  to each vertex's first bone; the `LOD0` part through visibility ranges (part 0 only by default, the original's hard
  switch, a variant with hysteresis, or the LOD part only; the setting `<Buildings lod="Part0|ByDistance|
  ByDistanceSmooth|LastPart">`, default Part0, in the Options' Graphics tab; the building gallery's switch overrides it
  until the setting changes). Materials are shared per texture pair, per-building values are instance uniforms; colour-variation slots
  reuse the slot freed last.
- **Shaders** (`shaders/buildings/`): house, house_cut (the cut by including `cut_none` or `cut_plane`, no define),
  frame (also ruins), decal, soldierflag; all write `FOG`. `sadk/light_original.gdshaderinc` is split into the model
  (`light_original_model.gdshaderinc`) and its `light()` so the house shader supplies its own light function.
- **Construction and upgrade**: frame stages from a per-vertex stage index; the cut in model space, interpolated within
  the tick; during an upgrade the old building keeps the part above the plane and the target the part below (one
  plane serves both: they share the model space); the target's frame and decal replace the old ones.
- **Ground decal** [implemented, sadk-remake 451e0e3, de9e001]: an exact port of `GroundDecalMesh::Build`
  S 006da2a0 (RE §3.9): the terrain triangles collected once under the transformed model box, edge planes through
  the packed vertex normals (`TerrainGrid.PackedNormal`: same-column row neighbours, the `2·step` border divisor,
  truncation), the mesh clipped at its authored height, each vertex then at `SampleHeightAndNormal`'s height at its
  3D point plus the float 0.01, float arithmetic in the original's order, the lists walked last-first; laid on worker
  threads (`DecalMeshes.LayOnWorker`, shared with every decal owner, `HouseDecalSet` for owners that are not
  buildings) and again when the terrain detail changes; the options panel's ground detail only scales the LOD band
  distances, which the decal does not read, so it re-lays nothing. After a height change a building's decal is laid with the
  matrix from before that change (`RefreshGroundPlacement` S 006ab420 uses the last frame's), a ruin's with the new one
  (S 006d4f90). The exact clip shows the original's notches and holes on slopes (on the Ship Ahoi harbour plot 6.8 %
  of the plot under the terrain); clipping with vertical planes (edge-plane normals (0, 1, 0), one line in
  `LayOnWorker`) removes them entirely, presentation only. Whether to offer it as a switch
  (`<Terrain decalClip="Original|Vertical">`, the original the default) is open (§24). Not reproduced: the
  512-triangle pool crash, the read past the grid's last row ([TODO]), `Matrix44_TransformCoord`'s rounding order.
  `TerrainSurface.ComputeNormals` (the Faithful terrain's lighting) does not use the formula of S 00687810 yet.
  With the refined terrain details a decal is laid on the finest level: a finest level finer than the fine grid cuts the
  clipped pieces along its lattice (`DecalLattice`) and lays them on it (`TerrainSurface.LevelHeight`), so each piece lies
  in one drawn triangle; the terrain keeps that level under the decal's box at every distance (§10.3 "Kept ground"), so the
  decal needs no depth bias and no vertex work: it lies on the drawn surface wherever the eye is [implemented]. The harbour
  places' plots are claimed the same way. The faithful look keeps the original's plot on the fine triangles.
- **Harbour plot** [implemented, sadk-remake c8f44a0]: every harbour place gets the `GROUND` decal of
  `Harbour_decal.KEX` through the `groundDecal` attribute of its type (§5.2), owned or not, flag or not (RE §3.11);
  `ObjectLayer` lays it, relays it by the 4 × 4 block rule and on detail changes, and removes it with the object.
  `ObjectLayer.MapChanged` still re-grounds objects by "origin inside the changed box" and raises `alignOnWater`
  objects only when they lie below the water, where the original sets them to the water level always (S 006db520).
- **Ruins** [implemented, sadk-remake d8f9737]: the engine event `RemainsAdded(BuildingType, Tribe)` (`Remains`
  keeps its tribe, also through a load) feeds `BuildingLayer.AddRemains` as `AddRuin` S 006a19b0 / `Ruin::ctor`
  S 006d4e00 do: the descriptor `<tribe>_<remains gfx>` turned by its heading, LOD part 0, the dead building's
  `GROUND` decal laid with the ruin's matrix (a missing descriptor gives no decal and a report, where the original
  reads before its table); removed with the remains (50 ticks in the shipped `remains.lua`); re-placed with its decal
  after height changes (slot 5, S 006d4f90).
- **Hidden gate** [implemented, sadk-remake d8f9737]: `BuildingLayer.Hidden` ports `SetHidden` S 006aa320 as fed by
  `TerrainCell::SetVisible` S 006b4f80: hidden unless the anchor's block is revealed and in the view frustum. It gates
  the door-open, door-close and collapse sounds and the start of the clips' events (model `+0x50`). Not ported: the
  cull's horizon occlusion, budget and other objects' boxes (S 006db220); drawing is left to Godot and the fog layer.
- **Doors and work on the logic clock** [implemented, sadk-remake b4dbe0c, d8f9737]: `DoorCycle` holds the 0.6 s door
  timing of `TriggerWorkCycle` S 006aa640 and the close of `Building::Update` S 006abcf0 per logic tick;
  `EntrancePasses` opens doors as `CharacterSettler::Update` does (the target building per class, the pass across the
  entrance, RE §3.9), reading only the published tick records; `BuildingLayer.LogicTick(tickLength)` runs once per
  record before the trees and the settlers (the original's order) and counts the one-shot down by the tick length
  (`PlayOneShotAnimation` S 006aa6f0 in full: the flag is set even without a clip or under construction). The gallery
  counts by frame time. Building attachments (the sacrifice movies) still advance per frame, the original's per tick
  ([TODO]).
- **Clips**: door and work in two `AnimationPlayer`s; a visibility notifier switches them off while unseen and seeks
  them to the clock's time on entering view (§4.7). Two types move the same bones from both clips (Bavarian_Fisher
  `DOOR`, Scots_Smeltery 12 bones): the original averages them while both play, Godot lets the later one win; only the
  short door clip is affected.
- **Data facts** (checked by tests): 112 `<Building>` entries, 3 with `<Production>`, 106 model files, 36 with a `LOD0`
  file, none with `LOD1`; root values lodBias −70, lodScale 1.2, numVariations 8; only Bavarian_Castle sets
  enterDistance; every type uses heading −30. Gaps in the shipped data: Egyptian and Scots list OlympicFlame but
  buildings.xml has only `Bavarian_OlympicFlame`; `MediumDummy` has no entry for any tribe. All building models have
  unit scale 1. The houses' third UV set varies per vertex, and the sampled meshes land on white texels of the colour
  map in all 8 variations (the original's colour variation is nearly invisible). Six skeletons repeat a bone name;
  Godot rejects duplicates, so the second gets a `#<index>` suffix and indices stay the file's.
- **Alpha test**: `ATEST127` is AlphaFunc Greater, AlphaRef 127 (`shared.inc:668`), so Godot's threshold is 128/255;
  this settles §24 item 6 (the map-object shaders used 127/255 and let alpha 127 through; now 128/255 as well).
- **Not drawn yet**: farm animals at `boneLink` bones. The fire and demolition particles came with the particle layer (§16.1).
- **Gallery**: `core.game.buildinggallery {map, tribe, progress, upgrade, health, lod, flags, ruins, door, work,
  demolish, …}` places a tribe's types on the flattest dry ground of a map.

## 14. Goods [draft]

`ItemKind`, MultiMeshes per good mesh and region:

- **Piles at flags**: one pile per flag, 6 stacks × 6 slots, layouts per good (WO §3.2); add, remove and merge rules
  driven by `PackagePile` events; slot order follows event order (as the original's follows callback order).
- **In hands**: attached to the carrier's bone (§9); the holder from `CarriedPackageChanged`; items on ships hidden.
- **Building sites**: rebuilt when the site's stock revision changes (WO §3.3).
- **Water-street boats**: the hidden `Boat` item per water street, shown for carriers on it.
- Every good has an item or is skipped: 27 group goods have none (WO §3.1).

**As built** [implemented, sadk-remake a85f14f]:

- **Rules as the original's** (WO §3.2, §3.3): the site pile lies between the anchor and the entrance flag with the
  anchor's x, in columns of 8, only while the building is under construction (never for an upgrade); a good put down
  without a carrier takes its slot without landing, so items in higher slots drop and pop back (the spill quirk); a
  new carrier takes the good a tick late (released in one tick, attached in the next); `RemoveItem` searches the later
  stacks of the same key; `MergeStacks` keeps the moved item's old stack transform, with the refined switch
  `ItemPile.PlaceMergedItems` (off).
- **In hands**: carried goods keep their own size; the character scale 1.2 is in the skeleton and is taken out of the
  attachment rotation. The holder rule runs once per frame (the original's per tick); a new held-good key changes the
  animation at once (the original's a tick later).
- **Differences**: no notifier per item; items cast shadows. `IPackageCargoView` is declared, not implemented.
  Decisions to review: [sim-boundary.md](sim-boundary.md) §11 item 4.
- **Open**: the carrier turning to the stack; default tool items; animated items; the water-street boats
  (`CharacterCarrier::UpdateAttachedItem` S 006c8ee0); hiding under the fog of war.

## 15. Streets, borders, overlays [draft]

### 15.1 Streets and routes

The original's route spline (Hermite, tangent factor 1.3), the street strip clipped against the terrain triangles,
crossings as hexagon fans, water-street buoy chains (WO §3.5 to §3.8; the sea-route strip is not ported, see below); built per street on a worker thread from `EntityAdded` / `StreetUpgraded` / removal, rebuilt on height
changes under it. Street previews of the placement mode come from `IQueries` and draw with the preview tint.

**Sea routes are not drawn as a ribbon.** The remake does not port the route pass (`RenderRoutes`,
`StreetRenderer::DrawRoutes` S 006c29a0, with `RouteDecal::BuildFromSpline` S 006e2450 and the route shader): the
maintainer's decision of 2026-10-25, since the original's ribbon is practically invisible. A route stays visible through
its two end buoys (map objects, `Scene::OnSeaRouteCreated` S 00683040 -> `MapObjLayer::AddInstance` S 0068dd40), which
also carry the route's picking (`PickShipRouteAtMouse` S 00787b00) and selection. The simulation (`ShipRouteAdded`,
`NavySystem` routes) is unchanged. The `graphics.xml <Street route*>` attributes stay in the original's data and are not
read by the remake. The original's behaviour stays documented in `docs/sim/world-objects-rendering.md` §3.7. This is a
deliberate omission, not a `[TODO]`; a mod that wants the ribbon draws its own.

**As built** [implemented, sadk-remake fb451d1]:

- **Mesh**: `StreetMesher` follows the Hermite route spline with tangent factor 1.3 and 31-chord segment lengths;
  the strip has 8 slices per segment and leaves out a slice at a flag with several streets; a crossing is a
  hexagon fan.
- **Layer**: `StreetLayer` (map layer order 450) keeps one `MeshInstance3D` per street and one per crossing, named by
  street id or crossing cell; texture sets 0 and 1; draw order through render priority. A street is rebuilt on its
  add, remove and upgrade and on `MapChanged(Heights)` under it, and all streets, crossings and door paths are
  rebuilt when the terrain detail switches between the flat and the smooth surface. `street.gdshader` applies a depth
  offset of 0.1 world units and the normal map; the parameters come from `graphics.xml` `<Street>`.
- **The near-plane pull** (§8.2) is not reproduced as a depth shift: Godot draws opaque objects before transparent
  ones, so a pull of several units would draw streets over settlers' feet, goods and buildings. A small offset alone
  buries the original's flat 7-vertex crossing fan (radius 2.25, `BuildJunctionFan` S 006de590) where the ground
  bulges through it, leaving hard cut edges at junctions and harbour flags. So each fan triangle is split 6 × 6
  (`CrossingPieces`, the remake's own density), positions, normals and uv interpolated from the original's seven
  vertices, and only the points below the drawn surface are raised onto it; with one piece the mesh is the
  original's fan. A harbour flag reached only by sea routes has no crossing, as in the original (`AttachFlagNodes`
  S 0069eeb0 runs on "street added", which a sea route never raises); the stone circle at a harbour flag is not a
  crossing but the harbour place's ground plot (§13.1).
- **Differences from the original**: the strip is a grid sampled from the heights, not the strip clipped against
  the terrain triangles; every flag node gets a crossing; the other streets at a node are rebuilt when its street
  count changes [inferred]; water streets are not drawn yet, sea routes by decision (above); the normal map's
  channel convention is [inferred].

### 15.2 Territory borders

Per player the border points (land: `limes`, water: `buoy`), instanced; rebuilt for the changed rectangle of
`MapChanged(Territory, rect)` (the original rebuilds all eight players' lists on every change).

**As built** [implemented, sadk-remake 67b91c4]:

- **Rule** as the original's (RE §3.8): every owned cell with grid bit 0x20, a land post where bit 0x4 is clear, a
  water post where it is set; land posts at the cell's sample vertex, water posts at the sea level with the bob
  `0.05 · sin(t · 2π · 0.3 + x + z)`. The remake builds per region and keeps the scan order, not the original's
  greedy nearest-neighbour order (RE §3.8); the order shows only where two posts overlap with blended alpha
  (`border_shader.fx`: z write, alpha blend, alpha test 127, fog-of-war alpha), presentation only. Models and the
  shader's colour rule `lerp(colour × 1.8, texture, texture alpha) × light` as the original's; the colour is the
  owner's, white without a player.
- **Layer**: map layer order 460; one `MultiMesh` per region and set (land, water); the colour goes in
  `INSTANCE_CUSTOM`, since the buoy's vertex colours are black. The models are named by `<Border land water/>` in
  `visuals/map-objects.xml`.
- **Differences from the original** (to review, [sim-boundary.md](sim-boundary.md) §11 item 4): the posts are laid
  again on a height change (the original keeps the old height until the next territory change, so its posts float or
  sink; presentation only). The posts cast shadows only from shadow level 5, as in the original (§10: the border bit
  0x20 of `Scene::ApplyShadowQuality` S 0067f420; `BorderMgr::RenderWithEffect` S 006b2d80 is the shadow-map pass,
  RE §3.8 [known]).

### 15.3 Build overlay and selection

- The construction icons per cell of the local player (RE §3.14), camera-facing quads per visible block, rebuilt on
  `MapChanged(ConstructionFlags, rect, localPlayer)` (the original recomputes them every frame); shown in info-map
  mode with its fade.
- Selection markers: decals laid on the terrain triangles like the ground decals (Godot's `Decal` is not available on
  the Compatibility renderer), additive, spinning, from the UI's selection.

**As built** [implemented, sadk-remake d2d47ee]:

- **Overlay**: `BuildOverlayLayer` (an `IMapLayer`, `src/Sadk.Client/BuildMode/`) keeps one rendering-server MultiMesh per
  4 × 4-cell terrain block (sadk-remake d515744), one instance per cell with an icon at the cell's point on the drawn
  terrain surface, and Godot sorts the blocks back to front by distance. The original's order is the reversed
  quadtree collection order (`RenderBuildPlacementOverlay` S 00688c40 walks the visible block list backwards and
  calls `AddCellsInRect` S 006b36d0 per block; the list is collected nearest child first only per quadtree level,
  by the table S 007fc1b8, and wholly visible subtrees use stale nearest-child bits, S 006db220, S 006dad30,
  S 006daff0; RE §3.14), so the two orders differ wherever that order and the true distance disagree: a
  presentation-only deviation, visible only where icons overlap (no depth write). The
  icons are world-sized, depth-tested quads in the original too: nearer plants and rocks cover them, water never does
  (`water_shader.fx` writes no depth), and they grow only as close as the camera comes: with the original's match
  camera, now the default (§8.1), no closer than in the original; the free camera, a setting, still comes much
  closer. A block is asked again only when a `MapChanged(ConstructionFlags)` event marks it; the original asks every
  visible cell every frame.
- **The block cache's rule** [implemented, sadk-remake da4ce8f]: since the original keeps no picture
  (`RenderBuildPlacementOverlay` S 00688c40 draws only cells whose flags are not 0, every frame), a cached block must
  look the same: `BuildOverlayBlocks` (no Godot) decides each block's buffer, its visible instance count (0 without
  icons) and its visibility, which is "alpha above 0 **and** the block has icons" through every fade (an emptied block
  had shown its old icons again after the info map was toggled); it notes `MapChanged` (construction flags,
  re-initialised) for the local player and re-places the icons after height changes (the original places them at
  `CellToWorldPos` S 00687790 every frame). The flag source answers 0 while the local player's active byte (+0x50) is
  clear, as `AddCellsInRect` S 006b36d0 does. A block is read one frame after the change reaches the presentation
  (the original reads in the same frame). Icon index, atlas cell and quad follow RE §3.14 (`ConstructionIcons`, shader
  `shaders/overlay/buildicons.gdshader`); the cell under the cursor gets no icon; nothing draws while the info-map
  fade's alpha is 0.
- **Menu**: built at run time from `menuingame.xml`, `templates.xml` and `iconconfig.xml`: the original's tabs, grid,
  icons and filter (ingame-ui §3.8.10).
- **Intents**: `core.game.build {type, x, y}` submits `0x20002` for the local player (the menu's buttons send through
  it); `core.game.infomap` toggles info-map mode (space); `core.game.buildmenu {x?, y?}` with a cell acts as a left
  click there, without one opens the menu type first. **B** opens the type-first menu, the original's unreachable
  "choose a type, then click cells" mode (ingame-ui §3.8.10), as the remake's own addition.
- **Cell marker**: a translucent hexagon; the original lays a decal (`SelectionMarker::UpdateDecal` S 006b0d00) of
  style 1, `buildingselect.dds` [inferred], 4 units wide and turning (RE §3.14). The info box has its fade-in only.
- **Open**: the construction lock (`Player::IsLocked`, `menu.lockBuilding`) is not exposed to the menu yet; the
  create-flag box and `0x20004`; the help text keys come from ingame-ui §3.8.10, which is [inferred].

**Selection and street placement as built** [implemented, sadk-remake 0df0a07]:

- **Pick and actions**: a click picks as `Cursor::SelectAtCursor` S 00788370 does (own flag on the cell, then a
  building on or next to it, then an own street); the selection kind decides the four action buttons, their tooltips
  and the confirmation box (ingame-ui §3.5 to §3.7). **Esc** cancels the street placement, the remake's own (the
  original's Esc reaches only a visible box's close button); the action panel closes only after the cursor has been
  over it and left.
- **The game selection apart from the menu's** (ingame-ui §3.5) [implemented, sadk-remake 942f608]: the game's
  selection is kept on its own (`MenuSelection.GameTarget`); the sacrifice bar's click sets it, then resets and
  refreshes, then sets the cell, in the order of `SacrificePanel::OnItemClicked` S 00624bd0; a ship resolves through
  it and the route actions read it. [TODO] its other readers: `btBack` / `btForward` (S 005eb850 → S 005354c0 /
  S 00535300, in every menu-selection mode, so also in modes 2 and 3; the remake draws both buttons disabled) and
  `RemoveBuilding` S 00559e00 (through S 005350e0, S 00535220).
- **Street preview** (WO §3.6): the accepted plan and the plan through the cursor cell, as the original's two paths;
  the red part is the tail a click would cut back. The preview is extended click by click and replaced by the
  simulation's path on its event (the original re-plans the whole chain [inferred]); the first segment's pre-tests
  are folded into the searches. There is no separate water-street mode: the water preview is a plain strip. The
  marker's look and the tints are the remake's own.
- **Commands**: after a street is completed an extra `0x20007` can go out and is refused (as in the original's
  network flow; harmless).
- **Attack** [implemented, sadk-remake 8f20eb9]: an enemy territory building gives kind 6, or 7 when its active
  fight is led by the local player; a foreign building that is no enemy gives none (`MenuSelection_ComputeSelectionKind`
  S 006156a0). Kind 6 binds the attack slider (`attackslider`, S 005ebd30 and its methods) and actions 11 / 12
  (`RefreshAvailability` S 00623da0, `ExecuteAction` S 00623730) send `StartAttack` 0x2000D and `Retreat` 0x2000E;
  kind 7 opens the fight box (`infoboxFight`) with its count pulse (`nMenu::Flash`).
- **Ships and routes** [implemented, sadk-remake dd389da]: the click in the original's full order with its ray hits
  (`SelectAtCursor` S 00788370); buildings (kind 6) and route buoys (kind 8) in one pick list in the original's
  order (`Pick_MapObjectAtScreenPos` S 0068c920), the ship pick with the swell's tilt and lift (`PickShip`
  S 00697db0); the ship box and the route box, the expedition actions 1–3, the markers (a ship's size-11 marker and
  the route ends) and the hover tip; ingame-ui §3.5. The pick list holds only kinds 6 and 8, so removals of other map
  objects do not reorder it as in the original (S 0068cff0).
- **Implemented** (sadk-remake, the demo fix round): a building's own ray test after its box (vtable slot 9,
  `S2CG::Building::Render` S 006aae60 → `PickMesh::IntersectRay` S 0076ff90): LOD part 0's pick mesh, a site with a frame
  stage above 0 the frame's pick mesh up to the stage's triangle count, a site at `constrProgress` <= 0 nothing, else part
  0 cut by `GetConstructionClipPlaneStatic` S 006aad50 (a world-space plane tested against model-space vertices, an
  original quirk kept); the search goes on when it fails (`Buildings/BuildingPick.cs`).
- **Open**: the hidden flag in the pick (S 00787cc0); the good buttons' click
  in every box (close the action panel and focus the camera on the unit: `GoodButton::OnClicked` S 0062fe50 →
  `nMenu_FocusCameraOnUnique` S 00648de0), so the ship boxes' lists are partial; the tab pages' fade (`fadetime`,
  `TabControl::LoadFromXml` S 004bad00) and the shared frame's move and zoom; selection kind 3's third button (always 14);
  the sacrifice states and destroy block reason 2; `menu.allowActions`; action 30 until `0x20010`. Decisions to
  review: [sim-boundary.md](sim-boundary.md) §11 item 4.

**Building panels as built** [implemented, sadk-remake 24823f6]:

- **Boxes**: the construction, production and store boxes and the settings panel follow the original's layouts and
  rules (ingame-ui §3.6, §3.8, [`../sim/hud-panels.md`](../sim/hud-panels.md)): the good lists and their defaults,
  the count formats and colours, the productivity text, the confirmation order of the settings. The settings panel
  has no reset buttons for `0x20022` and `0x20020`, as the layout has none (tab 1 holds only `contGoodPriority` and
  `btConfirm`); it opens with **L** or `btSettings`; parents and layout details the layouts do not give are [inferred].
- **Info boxes** [implemented, sadk-remake bad476e]: every good list shows its constructor's button count, empty
  buttons drawn empty (construction 12, store 22, running sacrifice 3, production 12 of which stockLimit × inputs
  are shown; ingame-ui §3.6), sorted as `CompareEntries` S 00648d10; the headline is rewritten every frame; the
  product fans follow the worker's work progress; the store's soldier tab, the catapult box and a ship site's
  progress are built; `ResetAndRefresh` S 00617db0 switches a box whose keep rule fails, and a box closed by another
  kind's fades out behind the next one (`InfoBox::Hide` S 00631bc0, without its mover and zoom).
- **Boundary** [implemented, sadk-remake c16efa5]: the panels read views only. `IBuildingView` carries `Requests`
  (the depot's `NeedGoods` +0x44 in filing order: the good and the package on its way), `Workers` (the worker
  slots) and `DepotSettlers`; the productivity comes through `IStatisticsView.TryGetProductivity`;
  `IPlayerView.MinesNeedFood` (`Player::IsStateNotDefault` S 005be330) serves the box and the selection rule.
- **Open**: the stock overview (the statistics' inventory tab), the worker flags, the boxes' move-in, move-out and
  zoom, a selected ship under construction (kind 5 of S 006397e0). Decisions to review:
  [sim-boundary.md](sim-boundary.md) §11 item 4.

### 15.4 Fog of war

§4.5: the design and the layer as built (sadk-remake b00b759).

### 15.5 HUD frame, minimap and messages

**As built** [implemented, sadk-remake f6f296c]:

- **Frame**: follows `menuingame.xml` and the parents the original's `SetupHud` gives the widgets (ingame-ui §3.4:
  the selection frame holds back, forward, settings and statistics; the minimap frame holds the info-map, speed and
  options buttons; the pause panel lies on the desktop; the rest on the HUD root). The message list stands at the
  top left, where the layout puts it (`pos="-26 -4"` without alignment).
- **Messages**: rows, row text and scroll buttons follow the original's (ingame-ui §3.8.5, hud-panels §3.5); a
  message's remaining time falls by the tick's simulated time. The list is saved and restored with the game
  ([sim-boundary.md](sim-boundary.md) §7).
- **Minimap**: the map picture is the overview render of §8.5 in the original's 512 × 512 picture (the overlays 256 × 256); the territory and building overlays and the click as the original's
  (S 005f3fc0, S 005f4390, S 005f1520; hud-panels §3.7); the symbol lifetimes from `mapSymbols.xml`; unexplored
  cells transparent. The camera's view frame ports `MiniMap::DrawCameraFrustum` S 005f2a50 (frustum corners 0, 1,
  7, 6 cut with y = 0, the far pair only when nearer than the far corner, nothing when all four miss, edges clipped
  against the round minimap; [camera-input-cutscenes.md](../sim/camera-input-cutscenes.md) §5).
- **Minimap zoom, pan and symbols** [implemented, sadk-remake 2026-10-25]: the intents are `core.game.minimap {u, v}` (a
  click), `core.game.minimap.wheel {u, v, notches}` and `core.game.minimap.pan {dx, dy}`; the source rectangle (the zoom
  state) lives in the minimap view. The wheel and the middle-button pan follow the original's rules (hud-panels §3.7
  "Input": factor `(15 - notches) / 15`, the 1/10 size limit, the clamps, the rectangle sliding at an edge). The press is a
  camera jump (§10.4) and each held-button move refocuses without a jump, as the original calls `FocusCameraOnCursor`
  S 005f1520 from the press S 005f18e0 and from every move S 005f2130 while button 0 is held (`FocusOnVertex` S 00786060
  sets the focus at once). The ship symbol marks every finished ship of the local player, the fight symbol sits at the
  target building's anchor cell (half alpha for other fights unless both sides are enemies); symbol sizes are the
  mapping's pixels, list symbols fade over the second half of their lifetime; the picture is 512 × 512 and the overlays
  256 × 256 as the original's, sampled linearly. The original's reset of the zoom and pan on every recapture
  (`CaptureMapTexture` S 005f3dd0) is not ported: a harmful UI bug outside the simulation, fixed outright.
- **Statistics panel**: the curves, coloured from `menu.cfg`. The original's UI player colours (S 0087f8c8) are
  iconconfig.xml's `<PlayerColors>` (`IconConfig::LoadFromXml` S 00611320) and differ from `menu.cfg`'s.
- `debug=true` shows the developer panel.
- **Differences from the original** (to review, [sim-boundary.md](sim-boundary.md) §11 item 4): the message
  lifetime counts simulated time (the original subtracts the frame time once per logic tick, so its lifetime
  depends on the frame rate); no statistics key (**S** moves the camera); no build or pause
  button (the original has neither); the back button sits where the menu combo box is; unexplored minimap cells
  transparent as documented, not seen in the original; the curve colours from `menu.cfg` where the original's
  panels use the `<PlayerColors>` table.
- **Open**: the statistics player
  rows and the inventory, buildings and tech tabs; the chat, the selection preview, back and forward cycling, info-map buttons 2 and 3; whether the original hides `btOptions`
  or `btQuests` in code (ingame-ui §10 Q15).

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

The CPU emitter writing MultiMeshes above was not built: the remake draws Godot GPU particles (§16.1). The
original's particle state is a closed function of the time since the emitter's start (PA §3.4 to §3.7), so the
GPU can compute every particle each frame from that time alone: no particle state is stored or integrated, there
is no per-particle CPU work, and an emitter out of view costs nothing and is right again when it comes into view.
The price is the original's draw sequence, which PA §8 already gives up (two original clients show different
particles). This is the Godot-first and CPU/GPU-balance rule: per-frame work on the GPU.

### 16.1 As built [implemented, sadk-remake fd8bd29]

- **Layer**: `ParticleLayer` (`core.game.particles`, order 480) starts effects, plays one-shots, stops them and
  frees them when done; one `GpuParticles3D` per emitter of an effect (`EffectEmitter`), set up once from its `.pfx`
  by `EmitterSetup` (pool, drawn share, pass, builder switches, the box every particle stays in, a one-shot's
  length); `EmitterBudget` keeps the caps per effect and in all.
- **Process shader**: `pfx_process.gdshader` computes each particle from the time since the start, without
  accumulation: the original's stagger, life time, draws per cycle, `maxLoops`, emit window and curved velocity
  (`Restart`, `Particle::Update` and `ApplyCurves`, PA §3.4 to §3.7).
- **Passes**: the six passes of `particle_shader.fx` as small shaders over `particle.gdshaderinc` (and
  `sphere.gdshaderinc` for the sphere lighting of passes 1 and 2): billboard or ground quads, flip-book, half texel,
  the distance fade.
- **Data**: `assets/visuals/particles.xml` (the effect folders, the atlas, the sphere normal map, the shaders, the
  caps); the effect table is built from the effect folder.
- **Setting**: `<Particles detail="Off|Low|Faithful">`, Faithful the default; Low halves the pools (§19).
- **Owners built**: building fires at `FIRE_03`, `FIRE_06`, ... or the five fallback points (RE §3.9), one
  `BuildingFire` per burning point from `HitpointsChanged`; the demolition dust (`DemolitionDust`, or
  `SmallDemolitionDust` by bit 0x4 of the size mask); the `<Particle>` events of the Working clips at their slot
  bones (chimney smoke, sparkles, saw dust).
- **Measured**: 158 emitters with 9,322 particles add 314 draw calls (main view and mirror) and about 37,000
  primitives, with no per-particle CPU work.
- **Differences from the original** (to review, [sim-boundary.md](sim-boundary.md) §11 item 4): hash draws in the
  shader instead of the original's sequence; the caps; `sadk_time` wraps every hour; pass 2's volume uses the
  box fixed at the start; work-clip emitters fade out when the clip stops [inferred]; a one-shot of an endless
  effect stops it at once; one fallback fire-point stream per building layer (the original's is process-wide).
- **Scene effects** [implemented, sadk-remake 5281ab9]: `SceneEffects` applies the scene's effect callbacks to each
  published tick record (PA §3.13):
  - *effect movies* (`EffectMovies`, `MoviePlay`): `effectMovies.xml` read as `LoadEffectMovies` S 00686160 does
    (exact-name lookup, S 006858b0); the keyframe timing of `EffectMovieElement::Update` S 006c6c80 and `IsPastEnd`
    S 006c67c0; a keyframe starts at its link bone's transform of that moment; stopping lets `maxLoops` effects run
    out and stops endless ones;
  - *the sacrifice building* plays one movie at a time: the definition's `gfxName` while a sacrifice runs,
    back-dated by the ticks run (`StartEffect` S 006ace00); `sacrificeResearchGfx` back-dated by the research's
    absolute start tick as S 006acf70 does; `sacrificeWaitForGoodsGfx` while an order collects; slots +0xa4, +0xac,
    +0xb4 stop it;
  - *`SacrificeEffectApplied`*: the `buffGfxName` as a movie on the sinking ship, the healed soldier and the revealed
    building, a one-shot at a revealed harbour's cell only when the viewer has explored it (S 00681fd0);
  - *strikes*: `HitDamage` at the striker (`StrikeLanded`, `Scene::OnFightStrike`);
  - *building buffs* (`BuildingBuffs`): the six buffs of `Building::Update` S 006abcf0, tested after each record
    against the owners' modifier tables (`ISacrificesView`) and the garrison's zone;
  - *projectiles* (`ProjectileEffects`, `ProjectileFlight`): the `projectiles.xml` record in the slot order of
    `AddProjectile` S 006a3d90, the arc of S 006a32b0 / S 006a3400 (0.1 s per flight tick, gravity 2.44269 for the
    catapult stone, 1.4715 otherwise) and the target point of S 006a3610; `flightPFX` follows the arc
    (`ParticleLayer.Follow`), `impactPFX` plays at the target and the trail is released (S 006a3af0): in the shipped
    data the stone's `BoulderFly` and `BoulderHit`;
  - *clip particles* (`ClipEventRunner`, shared by buildings and characters, the original's one `AnimatedVisual`
    path: `EventBase::Tick` S 006b00f0, `PlayAnimationWithEffects` S 006d8670): a clip's `<Particle>` events
    (S 006b05e0, S 006b0710) at the slot bone plus the turned offset, the emitter dated to the event's moment, moved
    with the bone while it lives, a zero duration stopping the emission at once, every live emitter stopped at the clip's
    end; events start only while the model is enabled (fog-visible, not hidden) [inferred for characters].
  The building gallery plays a movie (`movie=<name>`) on every building, or a one-shot (`effect=<name>`) in front
  of every building each second. Tests: the shipped movies, the keyframe timing, the back-dating, the buff rules.
- **Scene effects, decisions to review** ([sim-boundary.md](sim-boundary.md) §11 item 4): the effect and movie names
  (`sacrificeWaitForGoodsGfx`, `sacrificeResearchGfx`, `HitDamage`, `ShipSpeedUp`, `BuildingArmor`, `WorkerPause`)
  are constants citing the exe strings (could move to `visuals/particles.xml`); the research back-dating quirk is
  kept; the projectile launch point is the source building's box centre, the shooter's position or the fine
  position, a deviation: the original starts at the translation of the owner's matrix at launch and the projectile
  follows that matrix until it is launched (RE [rendering.md](../sim/rendering.md), `Projectile::ctor` /
  `Update` / `Launch` S 006a3720 / S 006a3400 / S 006a3a40 [known]), and the catapult's stone is launched only when
  the arm reaches its limit (`CatapultBuilding::Update` S 006d6000), not at `ProjectileAdded` ([TODO] S 006a3a40);
  the buffs ignore `showEffects` (its meaning is open).
- **Emitters turn with their links** [implemented, sadk-remake d8f9737]: a movie element takes the link bone's matrix
  times the owner's (`MoviePlay.Place`, `EffectMovieElement::Start` S 006c6bc0 / `GetWorldRotationAndPosition`
  S 006c6a60), and `FollowLinks` moves and turns the emitter as `EffectList::UpdateEmitterTransforms` S 006c6da0 does
  (rotation without scale; a scaled link gives the original a non-unit quaternion [inferred]; in the original that
  call comes only from `CCharacter::Update` S 00690bd0 and `Ship::UpdateVisuals` S 006a5cc0, so only characters' and
  ships' effects follow their link after the start, while a building's keep the transform they started with,
  slot bone's rotation included); character clip events
  (S 006b05e0 / S 006b0710) and building clip events take the bone's rotation too. `pfx_process.gdshader` turns the
  start point and the velocity by the emitter's rotation at the start of each cycle (USERDATA1/2), as
  `Particle::Update` draws through R(q), so a later turn does not swing particles in flight. Fires (S 006abbb0),
  buffs (S 006abcf0), dust and one-shots pass the identity quaternion S 008828d4 and stay upright in world space.
  The heal movie therefore follows the "Bip01 Spine" bone's rotation (not yet seen in a match).
- **Sounds** [implemented, sadk-remake b4dbe0c]: keyframe sounds of effect movies follow their element
  (`GetSoundPositionAndVelocity` S 006c6910, stopped with the keyframe, S 006c6790); `impactSound` plays with
  `impactPFX`, and only the catapult stone reaches the impact (`Scene::OnShipFxEnded` S 0067f340 removes other types
  at once).
- **Open**: `ShipFX` and `BoatFX` (S 006a4a20, S 006a5bf0), the projectile model, the meaning
  of `showEffects`; besides `SettlerSpeed`, the soldier buffs, resource hints, buoy and gate fires and Lua
  `createParticel` (the `StoneDust` event of `WorkLoop0Forester` now plays through the character clip particles).

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
- **A clock per renderer** [implemented]: `WorldRenderer.Clock` is the clock a renderer runs on, the process clock
  (`PresentationClock.Current`) by default. The renderer's frame step, its environment and camera, and its layers'
  clip, door, effect and movie times read it, never the process clock, so a gallery or a test drives a renderer's time
  with a clock of its own (it advances it itself; the driver node advances only the process clock). The shaders' time
  globals (`sadk_time`, `sadk_real_time`) are process-wide and stay the process clock's: what a shader times by itself
  (the characters' skinning, §9) follows the process clock in any renderer.

## 18. Picking [draft]

- Terrain: a ray from the eye through the pixel, length 1000, against the drawn terrain triangles of the visible
  regions (exact, since the remake draws the terrain at full resolution) → cell and vertex (CI §3.10).
- Objects: pick proxies (boxes from the descriptor's mesh bounds and the instance transform) in a grid of regions;
  the ray tests boxes, then the mesh where the original does.
- The original's priority (CI §3.10): the local player's flag on the cell, a building hit by the ray (explored), a
  building on or next to the cell, a ship, a sea-route marker, the player's street; settlers are hover-only. The
  results are checked against the views (exploration, ownership, existence) before a command is built.
- As built (sadk-remake dd389da, `Selection/WorldPicks.cs`): that order with buildings and buoys in one list, the ship
  pick by bounding sphere (at distance ≥ 0, the mean of the scaled vertices at the ship's ground point, not turned)
  then mesh (S 006a5020, S 0076ff90 / S 006ec8a0, which ignore the distance along the ray), the exact square root in
  place of `Math_FastSqrt` (it only decides which of two ships is nearer); §15.3.

## 19. Settings and switches [draft]

The table of RR §2.3 stands. Added here:

| Setting | Faithful | Refined option |
|---|---|---|
| Map-object yaw and scale, settler palettes | creation-order streams (differ per peer and after a load) | stable per map and entity |
| Walk cycles | in phase (shared pool) | per-instance phase |
| Foliage | blended, sorted per batch, shadow-only copies | opaque cutout with alpha to coverage (the default, §12) |
| Stall picture | saw-tooth | hold |
| Missing visual | nothing drawn | placeholder |
| Building LOD (`<Buildings lod>`) | part 0 (Part0, the default) | the original's distance switch, hard (ByDistance) or with hysteresis (ByDistanceSmooth) |
| Far plane, zoom range | 500, original steps | extended |
| Fog | the map's fixed distances, linear on the view depth | scaled with the eye distance beyond the original's 84 units (§11.1); far plane, shadow range and LOD bands follow it; smooth curve (the default) |
| Terrain detail | Faithful: flat triangles of the fine grid | Smooth (4×), Smoother (9×), Smoothest (16×) triangles on cubic patches (§10.2) |
| Ground shading (`Terrain occlusion`) | none (the original's light) | baked ambient occlusion of the terrain, or of the terrain and the objects standing on it (§25 item 1) |
| Shadow preset | one map, 2048, 2 × 2 taps; the default is a light preset close to it (§8.4) | cascades, larger maps, softer filter |
| Shader animation clock | as the original's timer (open, §7.3) | simulation-scaled |

Settings apply at once where they are globals; those that change batches (LOD, region size) rebuild at the next
match load.

**In the game** [implemented 2026-10-15]: one shared `RenderSettings.Current` (a map view reaches it as
`rc.Settings`), stored as `<Graphics>` in `settings.xml` ([assets.md](assets.md) §3) and changed in the options
panel or the map view's quick switches, which are a form over the same object. Every change applies at once,
including the region size and blended foliage, which rebuild the shown world.

**The options panel** [implemented, sadk-remake 726a5b1, tabs from the registry 2026-10-25]: core.game's
`core.game.options`, built from the original's `menuoptions.xml` frame and `menuIngameSettings.xml`'s tab control
(`engine.options` is routed to it), opened from the main menu, the match's `cbMenu`, `btOptions` and O. Its tabs and
groups come from the options registry ([mods.md](mods.md) §6.2): the engine's tabs GRAPHICS (display, the graphics
preset and, with the advanced graphics, the original's VIDEO group with the world settings), SHADOWS and QUALITY
(advanced only), SOUND (the original's AUDIO group), CONTROLS (`keys`: the key bindings, then core.game's INPUT group),
INTERFACE (language, font, the advanced graphics switch), then the mods' places (core.game's GAME tab with its GAME
group, refined's switches after it). The original's groups keep their controls, titles and look where a section has
their name; every change applies at once, with no apply or cancel. Which settings are the engine's and which a mod's:
[mods.md](mods.md) §6.2. The original's eight graphics values live in the engine's `RenderSettings` with the
original's mappings (`ApplyOptionValue` S 005e5bd0, `LoadOptionValue` S 005e55b0):

| Option | Effect in the remake | Original |
|---|---|---|
| ground detail | the terrain's LOD distance (§10.4) | `CMapRenderer::SetDetailFactor` S 00688220 |
| object details | the buildings' distance switch (§13) | `BuildingRenderer::Update` S 0069ff70 |
| `cMirrorStrength` | the mirror's detail level 0..4 (new render layers `Buildings` and `Characters` split from the object layer) | scene detail, settings +0x38 |
| mirror quality | the mirror's width capped at `128 << trunc(q × 4)` (it keeps the screen's shape) | `SetReflectionQuality` S 006a64c0 |
| `cShadowQuality` | shadow map `128 << trunc(q × 4)`, none at 0 (512 and 1024 added as sizes) | `ShadowManager::SetQuality` S 00769600, settings +0x28 |
| `cShadowDetail` | shadow level `trunc(v × 6 + 0.5)` (§8.4) | S 0067f6b0 → S 0067f420, settings +0x2c |
| `cDetail`, `cTextureQuality` | stored, no effect (every element is drawn, maintainer 2026-10-15; the texture loader lacks the flags) | the priority gate S 0068d360; the reduction S 004e79f0 |

| Element | Attributes |
|---|---|
| `Reflections` | `mode` (Off, ScreenSpace, Planar), `strength`, `resolution`, `range`, `rate`, `objects`, `shadows`, `minDepth`, `fog` (the mirror fogged as the original's, §11.1) |
| `Terrain` | `detail` (Faithful, Low — the default —, Moderate, High, VeryHigh; §10.4), `lod` (Distance — the default, the original's —, Shape; §10.4), `occlusion` (Off — the default, the original's light —, Terrain, Objects; §25 item 1), `occlusionStrength` (0..3, 1) |
| `Fog`, `Sky`, `Light`, `Foliage`, `Batching` | `mode` (Dynamic, Fixed, Off), `curve` (Smooth, Linear); `style` (Clouds, Dome); `perPixel`; `blended`; `regionBlocks` |
| `FogOfWar` | `enabled` (§4.5) |
| `Shadows` | `enabled`, `mapSize`, `splits`, `filter`, `range`, `darkness`, `softness`, `blur` |
| `AntiAliasing`, `Scaling`, `Textures` | `msaa`, `screenSpace`, `temporal`; `upscaler`, `scale`, `sharpness`; `anisotropy`, `mipmapBias` |
| `AmbientOcclusion`, `DepthOfField` | `enabled`, `intensity`, `radius`, `lightAffect`; `enabled`, `strength` (follows the eye distance, easing at the original's focus speed 3, S 00696d20) |
| `Particles` | `detail` (Off, Low, Faithful — the default; §16.1) |

SSAO, depth of field, TAA, SMAA, FSR and shadow softness have no effect on the Compatibility renderer.

**Anti-aliasing defaults** (maintainer, 2026-10-25): `RenderSettings.Msaa` is Off and FXAA is on; MSAA is too expensive
as a default (the integrated graphics target, principle 6). The cutouts' alpha to coverage (§12) only has an effect
once MSAA is switched on; FXAA is the cheap setting that also smooths their edges.

**Simple and advanced graphics** [implemented, sadk-remake 2026-10-25; the maintainer, 2026-10-19]: by default the
options show the graphics as five presets; the switch *Advanced graphics* in INTERFACE (`<Interface
advancedGraphics>`, off by default) shows every graphics control listed above (the VIDEO group on the graphics tab,
the SHADOWS and QUALITY tabs, and mod sections marked advanced). The simple view keeps the display group (resolution,
display mode, screen, V-Sync, frame limit) and the preset; everything else of the options is the same in both views.

The presets (`GraphicsPresets`) are the original's quality presets 0..4 (`Settings::ApplyQualityPreset` S 00695860,
`../sim/app-shell.md` §3.10) through the original's conversions, extended to the remake's settings that cost. A preset
never chooses another look than the original's (water, terrain at the original density) and never turns on MSAA,
SSAO, depth of field or TAA (principle 6). Presets change performance only, never the look. MSAA is in no preset and
never a default (too expensive); FXAA is the cheap default anti-aliasing [the maintainer, 2026-10-25]. The look choices that cost nothing (sky,
fog mode and curve, decals, blended foliage, the baked ambient occlusion `<Terrain occlusion occlusionStrength>`, the characters' LOD and phase, shadow range, darkness, softness and blur,
mirror resolution, range, rate, objects, fog and distortion limit, the render scale and upscaler, mipmap bias, terrain
levels and cache, batching) are the player's: no preset sets them. A value another value of the preset makes
meaningless is not set either (the shadow map without shadows, the mirror quality without a mirror, the object
details at `Part0`).

| Setting | 0 Lowest | 1 Low | 2 Medium | 3 High | 4 Highest (default) | Source |
|---|---|---|---|---|---|---|
| GroundDetail | 0 | 0.25 | 0.5 | 0.75 | 1 | original +0x20 |
| Shadows | off | off | on | on | on | original: shadow detail > 1/6 |
| ShadowQuality (level) | — | — | 2 | 4 | 6 | `trunc(d · 6 + 0.5)` of +0x2c |
| ShadowMapSize | — | — | 1024 | 2048 | 4096 | twice the original's `128 << trunc(q · 4)` (512, 1024, 2048): the remake's map is shared by its cascades [remake] |
| ShadowSplits | — | — | None | Two | Two | remake |
| ShadowFilter | — | — | Hard | Hard | Hard | remake |
| Reflections | Off | Planar | Planar | Planar | Planar | original: mirror quality > 0 |
| MirrorQuality | — | 0.25 | 0.5 | 0.75 | 1 | original +0x34 |
| ReflectionDetail | 0 | 1 | 2 | 3 | 4 | `trunc(s · 4 + 0.5)` of +0x38 |
| ReflectionShadows | off | off | off | off | off | remake |
| Detail (stored only) | 0 | 1/3 | 2/3 | 1 | 1 | original +0x40 |
| BuildingLod / ObjectDetails | ByDistance 0 | ByDistance 0.25 | ByDistance 0.5 | ByDistance 0.75 | Part0 | original +0x44 (1 = part 0 everywhere) |
| TextureQuality (stored only) | 0 | 1/3 | 2/3 | 1 | 1 | original +0x10 |
| TerrainDetail | Low | Low | Low | Low | Low | remake (the original's density) |
| WaterLook | Original | Original | Original | Original | Original | remake |
| Msaa | Off | Off | Off | Off | Off | maintainer 2026-10-25 |
| ScreenSpaceAA | Off | FXAA | FXAA | FXAA | FXAA | remake |
| Taa, Ssao, DepthOfField | off | off | off | off | off | remake |
| Anisotropy | 0 | 2 | 4 | 8 | 16 | remake |
| Particles | Low | Low | Faithful | Faithful | Faithful | remake |
| PixelLight | off (the original's per-vertex light) | on | on | on | on | remake |

The original's shader level +0x3c (2 for presets 0 and 1, 3 above) has no remake setting [TODO, app-shell.md §2.7:
what reads the scene's copy is not established].

**First start** [the maintainer, 2026-10-25]: as the original picks its preset on its first run from the fill rate it
measured (preset 0 below 500 Mpixel/s, 1 below 700, 2 below 1000, 3 below 1500, 4 above; S 00695fc0, S 005798a0,
`../sim/app-shell.md` §3.10), the remake's first start chooses one from the adapter kind Godot reports
(`RenderingServer.GetVideoAdapterType`, `GraphicsPresets.Detected`) [inferred mapping]: a discrete GPU → 4 Highest;
integrated graphics → 1 Low; another or unknown kind → 1 Low (the Compatibility renderer reports no kind, whatever the
adapter); a virtual GPU or the CPU → 0 Lowest. The first start is the settings file holding no `<Graphics>` element
(no file yet; every save writes the element of each bound section, `GameFolderSettings.Holds`). The preset is applied,
logged once (`graphics: first start, adapter <name> (<kind>): preset <n>`) and saved at once, so later starts keep the
player's choice. A new `RenderSettings` (the settings' defaults, and Defaults in the options) stays the highest preset.

**Custom.** Nothing is stored for the preset: the simple view shows the preset whose values the settings hold, or
*Custom* (an extra last entry, only while no preset matches) after a change in the advanced view; choosing a preset
sets its values. Choosing *Custom* changes nothing.

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
   map and publishes `MapChanged(Reinitialised)` (no ticks yet). Parity with the retired testbed viewer's map picture (git history).
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
   Q13), ship player-colour values, the loader of building-level particle elements (PA
   §10 Q3), the texture particle passes 1 and 2 sample (Q1). The tree states are settled: the sway never runs and the
   fall is the woodcutter's (RE §3.11).
6. Settled 2026-10-16: `ATEST127` is AlphaFunc Greater with AlphaRef 127, so alpha 127 is rejected; the house and
   map-object shaders keep alpha ≥ 128/255 (sadk-remake 328c30c).
7. The smooth terrain's density default: **Low** (maintainer, 2026-10-16). Measured in the game (compat, Icebound near
   view, 2026-10-16): Very High against Faithful changes 9 % of the pixels by more than 8 of 255 levels, the mean by
   3.9; only 14 of 625 blocks lie in the 16× band (to 34 units from the eye point), most of the view in the original's
   band, and where the surface does refine, the samples (one every 1.5 units) already describe hills far larger than a
   facet. The extra triangles pay off only with detail the heightmap does not have (§25).
8. Decisions for the maintainer from the terrain and decal work (2026-10-18):
   - whether `lod="Shape"` becomes the default of the refined details (it roughly doubles the triangles at Low, §10.4);
   - whether to cache the original's terrain levels to cut the rebuild garbage, for about 30 MB of CPU memory at Low
     (§10.5);
   - whether the vertical decal clip becomes a switch (`<Terrain decalClip="Original|Vertical">`, the original's
     clip the default; presentation only, §13.1);
   - whether water past the map's edge (the remake's old look) or a lighter seam over the skirt should return as
     switches (§11).

## 25. Graphics improvements to do [the maintainer's list, 2026-10-16]

The terrain looks like the original's because its information is the original's (§24 item 7). What would change the
picture, by effect per cost, all as refined-look switches beside the faithful look:

1. **Shading baked from the heightmap** [implemented, sadk-remake bakedao]: ambient occlusion of the ground, baked on the
   CPU when a map is shown and where its heights or objects change, read as one texture per pixel (principle 14); the
   setting `<Terrain occlusion="Off|Terrain|Objects" occlusionStrength>` (Off, the original's light, is the default).
   - **Texture**: RG8 with mipmaps over the map's extent, 2 texels per fine vertex step (0.75 units; Steinfjord 921 × 797,
     1.9 MB with mipmaps); R the sky a ground point sees with the map objects, G without them. Globals
     `sadk_ground_occlusion`, `_map`, `_strength` (core.game's), read through `shaders/terrain/occlusion.gdshaderinc`.
   - **Terrain** (HBAO): the drawn surface (`MapGeometry.HeightAt`, so it follows the terrain detail) sampled at every
     second texel (one point per vertex step), smoothed by a 9-tap binomial (the ripple between vertex rows would alias
     into stripes), then from each point 16 directions walked out to 24 units (a terrain block) in 12 quadratically spaced
     steps; per direction the rise of the highest elevation above the tangent plane's, weighted by `1 − (r/R)²`. Planes,
     sloped or not, stay open; valleys, creases and slope feet darken. The texels between the points are interpolated.
   - **Objects** (level Objects): every map object that casts a shadow (its element's `shadowCast`, never an additive one:
     the highland and lava fog hide no sky) and every building reports an occluder: the sphere over its world box (radius
     of the footprint's area circle, at most ¾ of the height; centre at half the height above its ground; nothing below
     0.75 units), its cosine-weighted share of the sky `c r² / d³` taken from the ground around it out to where it falls
     under 2 %, at an opacity of 0.35 (the remake's own, by eye: a sphere overstates a tapering tree, crowns let sky
     through), multiplied over all occluders. A building site occludes by its progress in quarters. Objects report at
     every level, so a switch needs nothing from them.
   - **Receivers**: the terrain (both passes), the streets and the ground decals multiply their albedo by R (in the
     original's gamma space: `R^(2.2·strength)` on the linear albedo; not the emission of lava and ice). Trees, rocks,
     stones, doodads and crops read G per vertex (one float varying) and fade it out over their lowest 3 units, so an
     object is darkened at its foot as the ground around it and never by itself. Buildings, characters, carried goods,
     flags, buoys and water plants receive nothing (their light maps and their own light stay the original's).
   - **Updates**: the layer `core.game.occlusion` gathers changes on the main thread and runs one job at a time on a worker
     that owns the bake's arrays; its image is uploaded whole. A height change samples its texels at once (where the surface
     is current) and recomputes the terrain within 24 units plus the smoothing; an object that comes, goes or moves
     composes only its reach. A window equals a whole bake (tested).
   - **Cost** (Steinfjord, 6 cores, Release build, processor time; wall time on a loaded machine in brackets): the whole
     bake 0.95 s (200–550 ms): heights 0.2 s, terrain walk 0.65 s, 3000 occluders 0.06 s; in the game (Debug build) the
     first bake with its mipmaps 0.46–0.9 s on workers and 1.5 ms upload. A building plot's height change: 0.4 ms of
     sampling on the main thread, 20 ms (7–10 ms) on a worker for 16.8k texels; an object 3 ms (2 ms). The objects of a
     match arrive after the first bake: one more compose of the whole map (60–140 ms on workers). GPU: one RG8 read per
     ground pixel, one vertex read per object vertex; Off skips both (a uniform branch).
2. **Texture on steep slopes**: the original projects every pattern from above, so cliffs and steep slopes show
   stretched streaks; triplanar (or slope-aligned) mapping only where the slope is steep.
3. **Displacement per pattern** (§10.2): the detail the fine terrain levels need to pay off. Not painted by hand
   (maintainer: "insanely annoying to make by hand"): derived from data, e.g. by integrating the original's pattern
   normal maps into heights in the conversion, or generated from the pattern textures by a tool (CHORD, tested
   2026-10-15 and set aside: no height output, weak terrain normals).
4. **Less visible tiling**: variation of the patterns over large areas (macro variation, randomised tiles).
5. **A PBR path** (roughness and normals per material, Godot's lighting) for new assets; CHORD gives usable
   roughness and building normals (2026-10-15), set aside for now.
6. **The interface**: scaling with the window (content scale), the original's hover look of the menu entries
   (Head_Garamond in capitals), backgrounds for the shell and mods screens.
7. **Refined water**: colour by depth, foam from a CPU-baked shore-distance field and a tunable Schlick fresnel, as the
   water look `Refined` [implemented, sadk-remake, 2026-10-25; §11]. Open: foam around objects in the water.

