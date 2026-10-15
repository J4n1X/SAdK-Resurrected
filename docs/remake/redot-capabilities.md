# Redot: what the remake can work with

Reference of 2026-10-15 for the remake design set ([README.md](README.md)): which engine version the remake builds
on, which of its facilities the design relies on, which renderer offers what, and the engine's pitfalls the testbed
viewer ran into. The design documents cite this file instead of repeating engine facts.

Tags: **[api]** = the type or member is in the C# API reference of the installed Redot 26.2
(`GodotSharp/Api/Release/RedotSharp.xml`, 49,813 documented members; editor types in `RedotSharpEditor.xml`);
**[viewer]** = used by the testbed viewer (`sadk-remake`, commit `ea6b13e`) and seen working there;
**[godot]** = Godot 4.5 behaviour as Godot's documentation states it, not checked against Redot here;
**[check]** = to verify before a design depends on it. An [api] tag says the member exists, not that it behaves as
its name suggests.

## 1. Version

| Fact | Value | Evidence |
|---|---|---|
| Engine | Redot 26.2 stable, .NET build (`26.2.stable.mono.official.4f5b14aba`) | `--version` of the editor binary |
| Godot base | **Godot 4.5.2** (`Godot Engine v4.5.2.stable.mono.redot.official` in the binary) | string in `redot.linuxbsd.editor.x86_64.mono` |
| C# SDK | `Redot.NET.Sdk/26.2.0`; the viewer targets `net8.0` with `RollForward=Major` and `EnableDynamicLoading` | `Sadk.Viewer.csproj` [viewer] |
| C# API assembly | `RedotSharp.dll`; namespace `Godot` (types keep Godot's names) | API reference |

Godot's documentation for 4.5 is the reference for engine behaviour; where Redot differs, its changelog says so.

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
| Depth of field (`CameraAttributesPractical`) | yes | partly | no | [viewer]: Forward+ only in its Quality tab |
| MSAA | yes | yes | yes | [viewer] |
| FXAA, SMAA, TAA, FSR 1, FSR 2.2 | yes | some | FXAA only [check] | [viewer] Quality tab; FSR 2.2 and TAA Forward+ [godot] |
| `RenderingDevice`: compute shaders and GLSL (`RDShaderFile`, `RDShaderSource`, SPIR-V from source) | yes | yes | **no** | [api]; [godot] |
| `CompositorEffect` (custom post passes in GLSL) | yes | yes | **no** | [api]; [godot] |
| `Decal` nodes (projected textures) | yes | yes | no [check for 4.5] | [api]; [godot] |
| `GPUParticles3D` | yes | yes | yes [check] | [api]; [godot] |
| Occlusion culling (`OccluderInstance3D`, `Viewport.UseOcclusionCulling`) | yes | yes | no [check] | [api]; [godot] |

**Consequence for the design:** everything the original's look needs (light model, terrain, water, objects,
settlers, particles, reflection, shadows) must work in Godot's shading language on all three renderers. GLSL through
`RenderingDevice` and compositor effects are allowed for **optional** features (refined-look post effects, compute
skinning or particles as an alternative path) that have a shading-language fallback or switch off on the
Compatibility renderer. `remake-architecture.md` §11 ("GLSL allowed") is read in that sense.

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
| Fonts | `FontFile.LoadDynamicFont` (TrueType/OpenType), `FontFile.LoadBitmapFont` (BMFont) | [api] |
| Video | `VideoStreamTheora` (Ogg Theora only; other codecs need a native plugin) | [api]; [godot] |
| Archives | `ZipReader`, `ZipPacker` | [api] |
| Resource packs | `ProjectSettings.LoadResourcePack` (mounts a `.pck` into `res://`) | [api] |
| Godot resources | `ResourceLoader.Load`, `LoadThreadedRequest`; `ResourceSaver`; custom `ResourceFormatLoader` | [api] |
| Files | `FileAccess`, `DirAccess`; .NET `System.IO` works as well | [api]; `System.IO` [viewer] |

Rules that follow:

- A runtime-loaded image gets no import step: mipmaps, compression and the alpha check are the loader's job. The
  viewer generates mipmaps only for uncompressed images, so a compressed DDS without a mip chain keeps none
  [viewer]. The conversion writes complete mip chains ([assets.md](assets.md) §6.2).
- Godot's DDS loader reads only the first face of a cube map; the viewer parses cube maps itself [viewer].
- Vulkan uploads DXT1 as RGB and loses the one-bit alpha the foliage is cut out with: such textures go to the GPU
  decompressed [viewer].
- glTF loaded at run time produces scene nodes; the remake converts them to its own render data (meshes, skeleton
  tables, animation tables) instead of keeping node trees per object ([renderer.md](renderer.md) §6).

## 4. Shaders

| Facility | Notes | Evidence |
|---|---|---|
| `Shader.Code` settable at run time | shaders can be compiled from text the game assembled | [api]; [viewer] (`ShaderFiles.cs` builds variants from strings) |
| `ShaderInclude` with `ShaderInclude.Code`; `#include` in shader code | Godot resolves include paths as resource paths (`res://…`); the viewer includes `res://shaders/…` | [api]; [viewer]; that files outside `res://` cannot be included by path is [godot, check] |
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

Because Godot's include resolution is path based, the remake expands `#include` itself before it sets
`Shader.Code`: an include path is a logical asset path, looked up through the virtual file system, so a mod can
replace a shared include for every shader that uses it ([renderer.md](renderer.md) §7.2).

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

## 7. Audio, UI, input, network

| Area | Facilities | Evidence |
|---|---|---|
| Audio | `AudioStreamPlayer`, `AudioStreamPlayer3D`, `AudioStreamPolyphonic` (many one-shots on one player), `AudioStreamInteractive` and `AudioStreamPlaylist` (music), buses and effects | [api] |
| UI | `Control` nodes built at run time; `RichTextLabel`, `NinePatchRect`, `TextureRect`, `Theme`, `TextServer`; `TranslationServer` | [api]; run-time `Control` trees [viewer] |
| Input | `InputMap` and actions, `InputEvent*` | [godot] |
| Network | `ENetConnection`, `StreamPeerTcp`, `PacketPeerUdp`, `Upnp`; .NET sockets equally available | [api] |

The original's protocols (TinCat frames, NCOMM game protocol) are byte-exact formats; the remake implements them on
.NET sockets in a Godot-free library, like the simulation, so the headless runner and the lobby tests use them too.

## 8. Editor

`EditorPlugin`, `EditorImportPlugin` and `EditorInspectorPlugin` exist for C# [api, `RedotSharpEditor.xml`]. They
serve the remake's own tooling, for example a preview of XML layouts inside the editor ([binding] architecture §6);
nothing in the shipped game depends on the editor.

## 9. Project and build facts

- C# only; no GDScript [binding].
- Godot registers C# node classes from the project's own assembly when it is built; classes in assemblies loaded
  later (mods) are not registered reliably [binding] architecture §9. Mods therefore bring no node classes.
- Exports ship the .NET runtime; mods and Harmony need the JIT, so no NativeAOT [binding] architecture §9; no
  trimming and no ReadyToRun either ([mods.md](mods.md) §7.1).
- The repository is shared by Linux and Windows through Samba: build output goes to per-OS folders
  (`Directory.Build.props`: `obj/$(OS)`, `bin/$(OS)`, `.godot/mono/temp/obj/$(OS)`); `.uid` files belong in the
  repository [viewer].
- Unattended checks: `redot --path <project> --rendering-driver opengl3 --rendering-method gl_compatibility -- <args>`
  under `xvfb-run` [viewer].
- Not available: DLSS (Redot has none) [viewer README].

## 10. Not used, and why

| Facility | Reason |
|---|---|
| GDScript | [binding]: no float32 scalar, too slow for pathfinding; one language for all mods |
| GDExtension for game code | native code is out of reach of Harmony and closes the code to mods ([binding] architecture, 2026-10-14 decision against a native core) |
| `.tscn` scenes for moddable UI | [binding] architecture §6, confirmed by the maintainer 2026-10-15: scenes do not merge across mods, their `res://` references bypass the virtual file system, and they can carry GDScript; used only for the remake's own development screens |
| The editor import pipeline for game content | content arrives at run time from the player's installation and from mods; nothing is imported at build time |
| Godot's physics step as the simulation clock | §6 |
| `Skeleton3D` per character for crowds | §5 (video memory per instance) |

Node classes from mod assemblies: `Godot.Bridge.ScriptManagerBridge.LookupScriptsInAssembly(Assembly)` is public in
RedotSharp 26.2 [api, checked by reflection 2026-10-15], so a mod assembly loaded at run time can have its node
classes registered as scripts. Not yet tried in an exported game; architecture §9 keeps mods without node classes
until it is.

