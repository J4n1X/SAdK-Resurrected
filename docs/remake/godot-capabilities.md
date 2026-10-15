# Godot: what the remake can work with

Reference of 2026-10-15 for the remake design set ([README.md](README.md)): which engine version the remake builds
on, which of its facilities the design relies on, which renderer offers what, and the engine's pitfalls the testbed
viewer ran into. The design documents cite this file instead of repeating engine facts.

Tags: **[api]** = the type or member is in the C# API reference of the engine (checked against Redot 26.2, the
engine until 2026-10-15: `RedotSharp.xml`, 49,813 documented members; editor types in `RedotSharpEditor.xml`; the
move to Godot 4.7.2 was checked by building and running everything, §1);
**[viewer]** = used by the testbed viewer (`sadk-remake`, commit `ea6b13e`) and seen working there;
**[godot]** = Godot behaviour as Godot's documentation states it, not checked here;
**[source]** = read in Godot's sources at the tag `4.7.2-stable` (2026-10-15 audit; file and line in the text);
**[check]** = to verify before a design depends on it. An [api] tag says the member exists, not that it behaves as
its name suggests.

## 1. Version

| Fact | Value | Evidence |
|---|---|---|
| Engine | **Godot 4.7.2 stable**, .NET build (`Engine.GetVersionInfo()["string"]` = `4.7.2-stable (official)`) | the maintainer's decision 2026-10-15 |
| C# SDK | `Godot.NET.Sdk/4.7.2`; the packages `GodotSharp` and `Godot.SourceGenerators` 4.7.2 from nuget.org (the editor download carries the same in `GodotSharp/Tools/nupkgs`); projects target `net8.0` with `RollForward=Major` and `EnableDynamicLoading` | the project files |
| C# API assembly | `GodotSharp.dll`; namespace `Godot` | API reference |

Godot's documentation for 4.7 is the reference for engine behaviour.

**The move from Redot 26.2 (Godot 4.5.2 base) to Godot 4.7.2** (2026-10-15) changed project files, package names
and scripts; the code needed one change: `Animation.Length` is a `double` in 4.7. Checked on 4.7.2 after the move:
every test, the map view and the viewer giving the same pictures, the asset check, unloading the mod set in the
process (mod node types included), the Linux and Windows exports, the custom `ResourceFormatLoader` with shader
includes through it, `CAMERA_VISIBLE_LAYERS`, global shader parameters added at run time, and threaded loading:
Godot 4.7 has the fix of PR #118824, and concurrent `LoadThreadedRequest` through the `vfs://` loader ran 0 crashes
in 120 runs, against 4 in 40 on Redot 26.2 for requests sharing a sub-resource (Godot issues #111202, #118185).

## 2. Renderers

Godot has three renderers. The maintainer runs **Forward+** on Windows; unattended test shots on the Linux box use
**Compatibility** (OpenGL 3.3) under a virtual display, because a software Vulkan device takes minutes per shot
[viewer; maintainer, 2026-10-14].

| Facility | Forward+ | Mobile | Compatibility | Evidence |
|---|---|---|---|---|
| Spatial shaders in Godot's shading language, `#include`, global and per-instance uniforms | yes | yes | yes | [godot]; globals [viewer] in both |
| MultiMesh with per-instance colour and custom data | yes | yes | yes | [api]; [viewer] |
| Directional shadows with cascades | yes | yes | yes | [viewer] (soft-shadow filter quality on Forward+) |
| SSAO, SSR, SSIL, SDFGI, VoxelGI, volumetric fog | yes | no | no | [godot]; SSAO [viewer] Forward+ only |
| Depth fog (`Environment`, fog mode depth) | yes | yes | yes | [source]: `smoothstep(begin, end, length(vertex))`, not linear and on radial distance (scene_forward_clustered.glsl:1141) |
| `FOG` output of a spatial shader (the shader's own fog; Godot skips the environment's and blends this one) | yes | yes | yes | [source] scene_forward_clustered.glsl:1486, gles3 scene.glsl:2381 |
| Depth of field (`CameraAttributesPractical`) | yes | partly | no | [viewer]: Forward+ only in its Quality tab |
| MSAA | yes | yes | yes | [viewer] |
| FXAA, SMAA, TAA, FSR 1, FSR 2.2 | yes | some | FXAA only [check] | [viewer] Quality tab; FSR 2.2 and TAA Forward+ [godot] |
| `RenderingDevice`: compute shaders and GLSL (`RDShaderFile`, `RDShaderSource`, SPIR-V from source) | yes | yes | **no** | [api]; [godot] |
| `CompositorEffect` (custom post passes in GLSL) | yes | yes | **no** | [api]; [godot] |
| `Decal` nodes (projected textures) | yes | yes | no | [api]; renderer comparison table [godot] |
| `GPUParticles3D` | yes | yes | yes [check] | [api]; [godot] |
| Occlusion culling (`OccluderInstance3D`, `Viewport.UseOcclusionCulling`) | yes | yes | yes | [source]: a CPU ray cast in the shared cull code (renderer_scene_cull.cpp:2927), not a renderer feature |

**Consequence for the design:** everything the original's look needs (light model, terrain, water, objects,
settlers, particles, reflection, shadows) must work in Godot's shading language on all three renderers. GLSL through
`RenderingDevice` and compositor effects are allowed for **optional** features (refined-look post effects, compute
skinning or particles as an alternative path) that have a shading-language fallback or switch off on the
Compatibility renderer. `remake-architecture.md` §11 ("GLSL allowed") is read in that sense.

Godot's screen-space reflection (`Environment.SsrEnabled`) serves opaque materials only (the flags are set for the
opaque pass, render_forward_clustered.cpp:755), traces the previous frame's picture, replaces part of the indirect
specular light and fades out between roughness 0.6 and 0.7; where it misses, the sky or probe radiance remains
[source]. It cannot apply the original's lookup offsets and never reaches the blended water, so the remake traces its
own ([renderer.md](renderer.md) §8.3).

The Compatibility renderer shows its output linearly, without the sRGB step: colours in its shots are darker and more
saturated than on Forward+; it also uses a different depth range in NDC (`CURRENT_RENDERER ==
RENDERER_COMPATIBILITY` branch in the viewer's water shader) [viewer].

## 3. Loading files at run time

The remake loads converted and modded assets at run time from the virtual file system ([assets.md](assets.md)), not
through the editor's import pipeline. Godot offers:

| Kind | Facility | Evidence |
|---|---|---|
| Images | `Image.LoadPngFromBuffer`, `LoadJpgFromBuffer`, `LoadWebpFromBuffer`, `LoadTgaFromBuffer`, `LoadBmpFromBuffer`, `LoadSvgFromBuffer`, `LoadDdsFromBuffer`, `LoadKtxFromBuffer` | [api]; DDS and TGA [viewer] |
| Image processing | `Image.Compress`, `Decompress`, `GenerateMipmaps`; `PortableCompressedTexture2D`; `Texture2DArray`, `ImageTexture3D`, `Cubemap` | [api]; decompress and mipmaps [viewer] |
| Models | `GltfDocument` + `GltfState`: `AppendFromBuffer` / `AppendFromFile`, then `GenerateScene`; extensions through `GltfDocumentExtension` (`RegisterGltfDocumentExtension`) | [api]; runtime glTF in exported projects [godot] |
| Meshes in code | `ArrayMesh.AddSurfaceFromArrays` (custom vertex channels with an explicit format flag), `SurfaceTool`, `ImporterMesh`; `RenderingServer.Mesh*` | [api]; `ArrayMesh` with custom channels [viewer] |
| Audio | `AudioStreamOggVorbis.LoadFromBuffer` / `LoadFromFile`, `AudioStreamWav.LoadFromBuffer`, `AudioStreamMP3` | [api] |
| Fonts | `FontFile.LoadDynamicFont` (TrueType/OpenType), `FontFile.LoadBitmapFont` (BMFont) | [api]; `LoadBitmapFont` opens real paths only and applies kerning [source] font.cpp:1494, 2050 |
| Video | `VideoStreamTheora` (Ogg Theora only; other codecs need a native plugin) | [api]; [godot] |
| Archives | `ZipReader`, `ZipPacker` | [api] |
| Resource packs | `ProjectSettings.LoadResourcePack` (mounts a `.pck` into `res://`) | [api] |
| Godot resources | `ResourceLoader.Load`, `LoadThreadedRequest`; `ResourceSaver`; custom `ResourceFormatLoader`. Through the remake's loader they reach every asset kind under `vfs://` and merged documents under `doc://` ([assets.md](assets.md) §5.3b); concurrent threaded requests that share a sub-resource are safe from Godot 4.7 on (PR #118824) | [api]; [measured] |
| Files | `FileAccess`, `DirAccess`; .NET `System.IO` works as well | [api]; `System.IO` [viewer] |

Rules that follow:

- A runtime-loaded image gets no import step: mipmaps, compression and the alpha check are the loader's job. The
  viewer generates mipmaps only for uncompressed images, so a compressed DDS without a mip chain keeps none
  [viewer]. The conversion writes complete mip chains ([assets.md](assets.md) §6.2).
- Godot's DDS loader reads only the first face of a cube map; the viewer parses cube maps itself [viewer]. Read
  from a buffer, `Image.LoadDdsFromBuffer` returns only the first image (texture_loader_dds.cpp:751) [source].
- The original's fonts are bitmap fonts (BMFont after conversion). The remake builds their `FontFile` itself: Godot's
  loader cannot read from `vfs://` and would apply the kerning pairs the original ignores ([assets.md](assets.md)
  §6.1) [source]. Multichannel signed distance fields, mipmaps and oversampling apply to vector fonts only (the glyphs
  are drawn from the outlines, text_server_adv.cpp:1408; a fixed-size font skips oversampling, :4265). The project
  setting `gui/theme/default_font_multichannel_signed_distance_field` changes only Godot's embedded default font, and
  only while no custom default font is set (default_theme.cpp:1393) [source]; the remake copies these settings
  (MSDF, mipmaps, antialiasing, hinting, subpixel positioning) onto the vector fonts it loads itself.
- `Theme.MergeWith` merges items, type variations and the defaults; `Clear()` keeps the default font, font size and
  base scale [api; measured 2026-10-15]. The remake builds its UI theme by merging every layer's `ui/theme.tres`
  ([mods.md](mods.md) §6.6).
- Exported games cannot compress to BC formats: etcpak's compressor is registered in editor builds only
  (etcpak/register_types.cpp:41) [source]. The conversion, which has no Godot dependency, writes compressed textures
  with complete mip chains itself.
- Vulkan uploads DXT1 as RGB and loses the one-bit alpha the foliage is cut out with: such textures go to the GPU
  decompressed [viewer].
- glTF loaded at run time produces scene nodes; the remake converts them to its own render data (meshes, skeleton
  tables, animation tables) instead of keeping node trees per object ([renderer.md](renderer.md) §6).

## 4. Shaders

| Facility | Notes | Evidence |
|---|---|---|
| `Shader.Code` settable at run time | shaders can be compiled from text the game assembled | [api]; [viewer] (`ShaderFiles.cs` builds variants from strings) |
| `ShaderInclude` with `ShaderInclude.Code`; `#include` in shader code | The preprocessor resolves an include through `ResourceLoader.Exists` and `Load`: a relative path, a bare name included, against the including file's folder, any other path as written. Include-once is by the include's resource path, cycles are an error, nesting stops at depth 25. A shader recompiles when one of its includes changes. `Shader.Code` drops preprocessor errors (missing include, cycle) and compiles the unexpanded code, which reports "Unknown character '#'". Compile errors inside an include are listed per file with path and line. `set_include_path` is not exposed in C#, so a shader made from code resolves relative includes only once it has a path | `shader_preprocessor.cpp` `process_include`; `shader.cpp` `Shader::set_code`; [measured] editor and exported build |
| Custom `ResourceFormatLoader` in C# | Registered at the front, it answers `Exists` and `Load` for its own paths. A path with an alphanumeric `scheme://` passes `localize_path` unchanged; a relative path becomes `res://`. Godot caches results by exact path, which is case-sensitive; clearing a resource's path takes it out of the cache. `Exists` answers true for a cached path whatever the loaders say. The engine calls the C# overrides only when the assembly is built with Redot's source generators | `resource_loader.cpp` (`exists`, `_load`, `_validate_local_path`); `project_settings.cpp` `localize_path`; [measured] |
| Global shader parameters | `RenderingServer.GlobalShaderParameterSet` and friends, declared in `project.godot` or added at run time (`GlobalShaderParameterAdd`); switching one takes effect at once, no recompile | [api]; [viewer] (15 globals) |
| Camera built-ins in spatial shaders | `CAMERA_VISIBLE_LAYERS` (the drawing camera's cull mask), `CAMERA_POSITION_WORLD`, `NODE_POSITION_WORLD`, `INSTANCE_ID`, `INSTANCE_CUSTOM`, `MODEL_NORMAL_MATRIX`, `VIEW_INDEX` | names present in the engine binary; `CAMERA_POSITION_WORLD` [viewer]; `CAMERA_VISIBLE_LAYERS` lets a shader tell the mirror pass from the main view ([renderer.md](renderer.md) §8.3) [check on all three renderers] |
| Per-instance uniforms | `instance uniform` in the shader, set with `RenderingServer.InstanceGeometrySetShaderParameter` / `GeometryInstance3D.SetInstanceShaderParameter`; Godot limits them to 16 per shader | [api]; limit [godot]; not used by the viewer |
| Per-instance data of a MultiMesh | `INSTANCE_CUSTOM` (vec4) and `COLOR` per instance; `MultimeshSetBuffer` uploads a whole instance buffer at once | [api]; transforms [viewer] |
| `ShaderGlobalsOverride` | per-scene override of global parameters | [api] |
| GLSL | only through `RenderingDevice` (§2) | [api] |

Shading-language limits the viewer hit [viewer, `remake-rendering.md` §4.1]: varyings cannot be written inside
helper functions; values computed in `fragment()` reach `light()` only through varyings; `textureQueryLod` is not
portable (point sampling with the nearest mip computes the level from derivatives); Godot turns a back face's normal
toward the viewer; `blend_add` is SrcAlpha/One.

The game's file system is in Godot's `ResourceLoader` under `vfs://` (`VfsResourceLoader`, Sadk.Presentation). A
shader loaded from `vfs://` resolves its includes through it, so a mod's file at the same logical path replaces an
include for every shader that uses it ([renderer.md](renderer.md) §7.2). The loader reports missing and cyclic
includes with file and line itself. Godot's text and binary resources in a directory layer load through Godot's own
loaders, and their `vfs://` references come back through the file system; inside a zip layer (a zipped mod, a map
package) they cannot be loaded, since Godot's resource loaders read only real files. A layer's paths leave Godot's
resource cache when the layer is unmounted. A path must be written in the file's own spelling: Godot's cache
compares case, the file system does not, and two spellings make two resources.

## 5. Low-level rendering (`RenderingServer`)

The renderer works on `RenderingServer` resources (RIDs) for anything numerous and uses nodes only for singletons
(camera, environment, sun) ([renderer.md](renderer.md) §3).

| Facility | Members | Evidence |
|---|---|---|
| Instances in a scenario | `InstanceCreate`, `InstanceSetBase`, `InstanceSetTransform`, `InstanceSetLayerMask`, `InstanceSetCustomAabb`, `InstanceSetVisibilityParent`, `InstanceGeometrySetVisibilityRange`, `InstanceGeometrySetLodBias`, `InstanceGeometrySetTransparency`, `InstanceGeometrySetShaderParameter` | [api] |
| MultiMesh | `MultimeshCreate`, `MultimeshSetMesh`, `MultimeshSetBuffer`, `MultimeshSetVisibleInstances`, `MultimeshSetCustomAabb`, `MultimeshInstanceSetTransform` / `SetColor` / `SetCustomData`, `MultimeshSetBufferInterpolated`, `MultimeshSetPhysicsInterpolated`, `MultimeshGetBufferRdRid` (GPU buffer for compute, not on Compatibility) | [api]; `MultiMeshInstance3D` [viewer] |
| Meshes | `MeshCreate`, `MeshSurfaceUpdateIndexRegion`, surface arrays and formats; `MeshSetCustomAabb` | [api] |
| Skeletons | `SkeletonCreate`, `Skeleton3D`, `Skin`; `AnimationMixer`, `AnimationPlayer`, `AnimationTree`, `SkeletonModifier3D` | [api]; `Skeleton3D` + `AnimationPlayer` per settler [viewer] |
| Views | `SubViewport` (update modes, own environment, cull mask); per-viewport anisotropy and mipmap bias | [viewer] (mirror view) |
| Measurement | `ViewportSetMeasureRenderTime`, `ViewportGetMeasuredRenderTimeGpu` / `Cpu`, `ViewportGetRenderInfo` (draw calls, primitives per pass), `GetRenderingInfo`; `Performance` monitors | [api]; [viewer] (`--stats`) |

Costs the viewer measured or ran into [viewer, `remake-rendering.md` §4.2]:

- **Godot's skinning is per instance**: one `Skeleton3D` per settler cost 211 MB of video memory for 240 settlers on
  the Compatibility renderer (Forward+ not measured). The remake skins in its own shader from a bone texture
  ([renderer.md](renderer.md) §9).
- A directional shadow map is rendered **per camera** that sees the shadowed light: the mirror camera gets a
  shadowless copy of the sun on its own layer (directional lights honour the camera's cull mask).
- A sky shader that reads `TIME` or `POSITION` re-renders the radiance cube map every frame per viewport: the sky is
  driven by global parameters.
- Transparent materials cast no shadows: blended foliage needs an alpha-tested shadow-only copy.
- Reading the screen or depth texture makes Godot copy them every frame: only the variant that needs it declares
  them.
- SSAO darkens only Godot's ambient light; it reaches the remake's own light only through `ssao_light_affect` with
  `ssao_ao_channel_affect = 1`.
- A Godot camera cannot hold a mirror matrix: the mirror camera uses the mirrored eye, forward and up vectors, and its
  picture comes out flipped left to right.
- Godot keeps the vertical field of view by default; the original's 50° is horizontal. `Camera3D.KeepAspect`
  [api] set to keep the width makes Godot's field of view horizontal ([renderer.md](renderer.md) §8.1).
- Winding: Godot's front faces are clockwise, the original's counter-clockwise; triangles are reversed at
  conversion.

## 6. Time, interpolation, threads

| Facility | Notes | Evidence |
|---|---|---|
| `_Process` / `_PhysicsProcess`, `Engine.PhysicsTicksPerSecond` | the remake does **not** run the simulation in Godot's physics step: lockstep stalls, speed changes and pause must not produce empty physics frames that Godot would interpolate across ([sim-boundary.md](sim-boundary.md) §4) | [api] |
| Physics interpolation (`Node.ResetPhysicsInterpolation`, `MultimeshSetPhysicsInterpolated`, `MultimeshSetBufferInterpolated`) | not used for the simulation clock, for the reason above; the renderer interpolates with its own tick fraction | [api] |
| `WorkerThreadPool`, .NET `Task`/`Thread` | the simulation library uses .NET threads only (no Godot types) | [api] |
| Threading rule | scene-tree and most Godot calls from the main thread only; the simulation thread never touches Godot | [godot]; [binding] the simulation has no Godot dependency |

What follows `Engine.TimeScale` and `SceneTree.Paused` [source]:

| Facility | `Engine.TimeScale` | `SceneTree.Paused` |
|---|---|---|
| `_Process` delta | scaled (main.cpp:5062) | stops pausable nodes (node.cpp:911) |
| `_PhysicsProcess` | delta scaled (main.cpp:5001); the number of ticks per second follows real time (main.cpp:4937), so a time scale never adds ticks | stops pausable nodes |
| shader `TIME` | scaled: the renderer adds the scaled step (main.cpp:5089, renderer_compositor_rd.cpp:123); wraps at `rendering/limits/time/time_rollover_secs` (3600) | keeps running |
| `AnimationPlayer` / `AnimationMixer` | scaled; no option to ignore the scale (animation_mixer.cpp:2407) | stops |
| `Timer`, `SceneTreeTimer`, `Tween` | scaled unless told to ignore it (timer.cpp:54, scene_tree.cpp:796, 829; `CreateTimer` scales by default) | stop, unless they process always |
| `GPUParticles3D` | scaled (particles_storage.cpp:1484) | speed set to 0 (gpu_particles_3d.cpp:599) |
| audio | not scaled; `AudioServer.PlaybackSpeedScale` is separate (audio_server.cpp:1229) | players pause (audio_stream_player_internal.cpp:118) |

No unscaled process step is exposed to scripts (core_bind.cpp:2110); real time comes from `Time.GetTicksUsec`. For
the remake this means: game speed is `Engine.TimeScale` and pause is `SceneTree.Paused`, so Godot-animated
presentation (animation players, particles, tweens, shader time) follows both by itself; the simulation keeps its own
fixed-tick accumulator fed by the scaled delta, so frame timing decides only when a tick runs, never what it computes
([sim-boundary.md](sim-boundary.md) §4); the camera, the UI and the boot code run on real time and process always.
Godot's own `--time-scale`, `--fixed-fps` and `--write-movie` then work for unattended runs and replay videos.
Godot keeps no run-time changes of the `InputMap`, so the remake stores key bindings in `settings.xml` (`<Input>`, one
`<Action name>` with `<Key code shift ctrl alt meta physical>` and `<Mouse button>` children in Godot's enum names);
a binding that does not parse is reported at start and left out [implemented 2026-10-15].

**Visibility notifiers** (`VisibleOnScreenNotifier3D`, or node-free ones through `RenderingServer`) [source]: each is
an instance in the normal cull loop of every camera of the world, sub-viewports (the mirror) included, filtered by the
camera's cull mask (renderer_scene_cull.cpp:2924); signals fire only on a change; they are sent after all viewports
are drawn, so work they gate starts one frame late (rendering_server_default.cpp:109); shadow passes do not count
(renderer_scene_cull.cpp:2427); a `MultiMesh` is culled as one box, never per instance (:2004). Useful for objects
animated on the CPU (an `AnimationPlayer` per building: disable it while unseen, seek to the clock's time on
entering), and for batched objects (map objects, settlers, animals, ships), whose `MultiMesh` Godot culls only as a
whole: the notifier is what lets an object outside the view leave its batch, so it is not drawn at all
([renderer.md](renderer.md) §4.7, §13). The GPU-skinned crowds need no animation work while unseen either, since
their pose is computed from the clock in the shader.

## 7. Audio, UI, input, network

| Area | Facilities | Evidence |
|---|---|---|
| Audio | `AudioStreamPlayer`, `AudioStreamPlayer3D`, `AudioStreamPolyphonic` (many one-shots on one player), `AudioStreamInteractive` and `AudioStreamPlaylist` (music), buses and effects | [api] |
| UI | `Control` nodes built at run time; `RichTextLabel`, `NinePatchRect`, `TextureRect`, `Theme`, `TextServer`; `TranslationServer` | [api]; run-time `Control` trees [viewer]; a theme does not pass a `CanvasLayer`, so each layer needs its own theme owner (theme_owner.cpp:404) [source] |
| Input | `InputMap` and actions, `InputEvent*` | [godot] |
| Network | `ENetConnection`, `StreamPeerTcp`, `PacketPeerUdp`, `Upnp`; .NET sockets equally available | [api] |

The original's protocols (TinCat frames, NCOMM game protocol) are byte-exact formats; the remake implements them on
.NET sockets in a Godot-free library, like the simulation, so the headless runner and the lobby tests use them too.

How the presentation uses these facilities [draft; suggestions forwarded by the maintainer 2026-10-15]:

- **Text**: the engine's text service is Godot-free (Lua, the headless runner and the server resolve text keys
  through it); the presentation loads the same tables into `Translation` resources of the `TranslationServer`, so
  controls translate their text themselves and a language switch updates every visible label
  ([assets.md](assets.md) §8).
- **Input**: controls are `InputMap` actions declared by the mod that owns them, so every control can be rebound
  ([renderer.md](renderer.md) §8.1).
- **Audio**: Godot's buses (one per volume setting, effects on the buses) and `AudioStreamPlayer3D` for positional
  sounds; many short one-shots of one kind share an `AudioStreamPolyphonic` player.
- **UI styling**: `Theme` resources, referenced by the XML layouts and replaceable or patchable by mods like any other
  asset; the layouts themselves stay XML ([mods.md](mods.md) §6.6).
- **Animation of few objects**: `AnimationPlayer` on a `Skeleton3D` for buildings and other single instances; the
  thousands of characters keep the GPU skinning of [renderer.md](renderer.md) §9.
- **Window and screen**: Godot cannot list a screen's display modes and never changes them; full screen and borderless
  always have the screen's resolution (`DisplayServer.ScreenGetSize`), and the 3D picture's resolution is the render
  scale's business. The Options screen therefore offers window sizes only in windowed mode: the screen's own size
  first, then common sizes that fit the whole screen; a window that does not fit beside the taskbar opens maximized
  [implemented 2026-10-15].

## 8. Editor

`EditorPlugin`, `EditorImportPlugin` and `EditorInspectorPlugin` exist for C# [api]. They
serve the remake's own tooling, for example a preview of XML layouts inside the editor ([binding] architecture §6);
nothing in the shipped game depends on the editor.

## 9. Project and build facts

- C# only; no GDScript [binding].
- Godot registers C# node classes from the project's own assembly when it is built; a mod's node classes become
  scripts without a path when their first object is made, and leave Godot's type map with their last object, so mods
  may bring node classes and still unload ([mods.md](mods.md) §7.1) [measured on Redot 26.2 and Godot 4.7.2].
- Exports ship the .NET runtime; mods and Harmony need the JIT, so no NativeAOT [binding] architecture §9; no
  trimming and no ReadyToRun either ([mods.md](mods.md) §7.1).
- The repository is shared by Linux and Windows through Samba: build output goes to per-OS folders
  (`Directory.Build.props`: `obj/$(OS)`, `bin/$(OS)`, `.godot/mono/temp/obj/$(OS)`); `.uid` files belong in the
  repository [viewer].
- Unattended checks: `godot --path <project> --rendering-driver opengl3 --rendering-method gl_compatibility -- <args>`
  under `xvfb-run` [viewer].
- Not available: DLSS (Godot has none) [viewer README].

## 10. Not used, and why

| Facility | Reason |
|---|---|
| GDScript | [binding]: no float32 scalar, too slow for pathfinding; one language for all mods |
| GDExtension for game code | native code is out of reach of Harmony and closes the code to mods ([binding] architecture, 2026-10-14 decision against a native core) |
| `.tscn` scenes for moddable UI | [binding] architecture §6, confirmed by the maintainer 2026-10-15: scenes do not merge across mods, their `res://` references bypass the virtual file system, and they can carry GDScript; used only for the remake's own development screens |
| The editor import pipeline for game content | content arrives at run time from the player's installation and from mods; nothing is imported at build time |
| Godot's physics step as the simulation clock | §6 |
| `Skeleton3D` per character for crowds | §5 (video memory per instance) |
| Environment screen-space reflection for water and ice | opaque materials only, Forward+ only, traces the previous frame, no lookup offsets (§2); the remake traces its own ([renderer.md](renderer.md) §8.3) |
| An oblique near plane for the mirror camera | `Camera3D` has perspective, orthogonal and frustum projections only; the mirror pass cuts at the water by `discard` ([renderer.md](renderer.md) §8.3) [source] |
| A visibility notifier to gate the mirror view | its answer arrives after the frame is drawn (§6), so water entering the view would miss its reflection for a frame; the remake's own box test costs microseconds |
| Per-instance culling, LOD or sorting of a `MultiMesh` | Godot culls, picks the LOD and sorts a `MultiMesh` as one box (renderer_scene_cull.cpp:2004); the remake batches per region and sorts blended instances itself ([renderer.md](renderer.md) §4.2, §12) [source] |
| Visibility ranges for the terrain and settler LOD bands | measured to the instance box's centre (renderer_scene_cull.cpp:1480), per `MultiMesh` too coarse; a fading range forces the alpha pass (render_forward_clustered.cpp:978); nothing stitches cracks [source] |
| `FontFile.LoadBitmapFont` | opens real paths only, not `vfs://`, and applies kerning the original ignores (§3) [source] |
| `Image.LoadDdsFromBuffer` for cube maps | returns the first face only (§3) [source] |
| Godot's BC compression | missing from exported games (§3); the conversion compresses [source] |
| Resource packs (`LoadResourcePack`) as the mod file system | cannot be unmounted, which in-process mod unloading needs; the remake's own layers ([assets.md](assets.md) §5) |
| Physics raycasts for picking (`HeightMapShape3D`) | the fine grid shifts odd rows by half a step and the smooth surface exists only in the shader; one ray per frame is cheap without physics bodies, which thousands of movers would need updated every frame ([renderer.md](renderer.md) §18) |
| Physics interpolation (`MultimeshSetBufferInterpolated`) | tied to physics ticks, which a time scale never adds (§6); the renderer interpolates with the simulation's tick fraction |
| `GltfDocument` for models at run time | the converter and the headless runner need engine-neutral data, and the GPU skinning needs raw skeleton and animation tables |
| `TranslationServer` fallback locale | read once from a project setting at start (translation_server.cpp:603), `set_fallback_locale` not exposed to C#; the base language differs per installation, so the remake merges it into every language ([assets.md](assets.md) §8) [source] |

Node classes from mod assemblies: `Godot.Bridge.ScriptManagerBridge.LookupScriptsInAssembly(Assembly)` is public in
GodotSharp 4.7.2 (and was in RedotSharp 26.2) [api]; the remake does not call it, its mods' node types work through
the path-less scripts of §9.

## 11. Checked for later systems [2026-10-15 audit]

Facilities the remake does not use yet but that fit systems still to be built; facts from Godot 4.7.2's sources.

| Facility | Fact | Where it fits |
|---|---|---|
| `render_mode depth_prepass_alpha` | a blended material casts shadows only with it, on all three renderers (scene_shader_forward_clustered.cpp:254, gles3 rasterizer_scene_gles3.cpp:258); the engine's alpha cut in the shadow pass is 0.1 (render_forward_clustered.cpp:2818) [source] | could replace the shadow-only copies of blended foliage ([renderer.md](renderer.md) §12); compare the look first, the depth prepass may change how overlapping leaves blend |
| Automatic mesh LOD (`ImporterMesh.GenerateLods`, `Viewport.MeshLodThreshold`) | LODs can be generated at run time (importer_mesh.cpp:570; meshoptimizer is in export builds); the LOD is picked per instance, a whole `MultiMesh` counting as one, by distance to its box; threshold 0 turns it off (render_forward_clustered.cpp:1083) [source] | fewer triangles for map objects and buildings in the refined look, also in the shadow cascades; threshold 0 keeps the faithful look |
| `GPUParticles3D` with a process shader | process shaders get `TIME`, `INDEX`, `NUMBER`, `RANDOM_SEED`, `USERDATA1-6`, `ACTIVE`, `LIFETIME` (shader_types.cpp:368); a system is processed only while culled visible (renderer_scene_cull.cpp:2992); view-depth sorting on the GPU on Forward+ and Mobile, on the CPU from two-frame-old data on Compatibility (gles3 particles_storage.cpp:824); Godot adds up frame deltas and freezes unseen systems, while the original computes particles from elapsed time, so a process shader with the closed-form life cycle is needed [source] | particles ([renderer.md](renderer.md) §16); follows game speed and pause by itself (§6) |
| Sky radiance | Forward+ updates the radiance whenever the sky is drawn, even if nothing reads it (render_forward_clustered.cpp:2068); a sky shader reading `TIME` or `POSITION` re-renders every frame (sky.cpp:1003) [source] | the original dome sky as a mesh instead of a sky shader would save that work per viewport, the mirror's included (a GPU-load item) |
| Occlusion culling (`ArrayOccluder3D.SetArrays`) | occluders can be built at run time (occluder_instance_3d.cpp:150); moving them rebuilds the tree; the raycast module is built for x86_64, arm64 and wasm32 except arm64 Windows with MSVC (modules/raycast/config.py) [source] | conservative occluders per region from the terrain's lowest heights on hilly maps; the gain for a camera looking down is unverified |
| `ResourceLoader.LoadThreadedRequest` + `LoadThreadedGetStatus` | progress per request through `vfs://` (§3) [api] | the match's loading screen |
| `Window.ContentScaleMode` (`canvas_items`), `ContentScaleSize` | scales the whole UI with the window [api] | UI scale, once the original's layout size is known; vector fonts with MSDF stay sharp at any scale |
| `TranslationServer.PseudolocalizationEnabled` | lengthens and marks every translated text [api] | a test for texts that do not fit in other languages |
| `OS.AddLogger` | a C# logger receives the engine's messages and errors [api] | showing engine errors (shader errors, for example) in the game instead of only in the log |
| `Input.SetCustomMouseCursor` + a `Timer` that ignores the time scale | [api] | the original's cursors (`ui/layout/cursors.xml`, one animated at 5 fps) |
| Audio | `AudioStreamWAV.LoadFromBuffer` accepts PCM (format 1) and IEEE float (format 3) only (audio_stream_wav.cpp:736), so the conversion turns the original's IMA ADPCM into PCM; `AudioServer.PlaybackSpeedScale` is separate from the time scale (audio_server.cpp:1229) [source] | buses, `AudioStreamPlayer3D`, `AudioStreamPolyphonic`, `AudioStreamRandomizer` (§7) when audio is built; whether the original picks random sound variants is open |
| `ReflectionProbe` | captures a cube map at a point; materials using Godot's specular get it; that a custom shader cannot sample it directly is [check] | the maintainer's idea for reflective surfaces away from the water and for what screen-space reflection cannot see; would need the reflecting materials to output Godot's specular |
