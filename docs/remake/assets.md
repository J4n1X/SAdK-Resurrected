# Remake: assets — conversion, virtual file system, formats, maps

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). It turns
[`../remake-architecture.md`](../remake-architecture.md) §11 into a design: where files live, how the player's
installation is converted once and checked at every start, how every asset is found (the virtual file system with
its layers), which formats the converted assets have (the architecture's open point §13 item 4), what a map package
holds, and when what is loaded.

Tags: **[binding]**, **[draft]**, and the source tags of the cited documents; **[measured]** = counted on the
reference installation (German retail, patch level 9212) on 2026-10-15. Short names: AF = `../asset-formats.md`,
FI = `../sim/formats-inventory.md`, MF = `../map-format.md`, DL = `../data-loading.md`, AU = `../sim/audio.md`,
AM = `../sim/animation-models.md`.

## 1. What is fixed [binding]

- No original data is shipped; the remake reads the player's installation.
- Assets are converted **once, at the first start**, into formats the engine loads directly; again only when their
  sources change. Every start compares the recorded file list (size and modification time, no hashing); a changed
  file is hashed and converted again; a missing installation stops the game.
- Maps bring their own assets, searched before the base game's and transferred with the map.
- Models are not bound to `.KEX`: the asset lookup chooses the loader by format.
- Shaders may be loaded from files, GLSL included (read as in [redot-capabilities.md](redot-capabilities.md) §2).

## 2. The original's installation [measured]

| Kind | Files | Size | Encrypted | Notes |
|---|---|---|---|---|
| `.dds` | 1,050 | 421 MB | yes | DXT1 792 (2 cube maps), DXT3 58, DXT5 17, A8R8G8B8 127, others 56; 226 without mips (FI) |
| `.kex` | 1,639 | 227 MB | no | meshes, skeletons, animations; no ids or hashes inside (AF §2) |
| `.ogg` | 738 | 194 MB | no | 540 voices (`language\de\voices`), sounds, music |
| `.tga` | 125 | 62 MB | yes | cursors, particle atlas, colour ramps, font pages |
| `.s2m` | 33 | 22 MB | yes | 31 free and campaign maps, 2 prototype maps in the old layout |
| `.wav` | 126 | 13 MB | no | PCM16 103, IMA ADPCM 16, float 7 (AU §6) |
| `.bmp` | 35 | 10 MB | no | map previews, two lobby textures |
| `.lua` | 355 | 0.3 MB | yes | property scripts, map tools, map and cutscene scripts, info pages |
| `.xml` | 110 | 0.3 MB | yes | settings, layouts, lobby data |
| `.pfx`, `.fx`, `.fnt`, `.npc`, `.bin` | 64, 59, 15, 32, 31 | < 1 MB | no / yes (`.fx`) | effects, D3D9 shaders, bitmap fonts, avatars, map environment sidecars |

4,453 files and 955 MiB below `data\` [measured 2026-10-15]; the sizes above are those of the stored (packed)
files: decrypted, the `.dds` files hold 756 MiB. 55 file names occur more than once below `data\`: 32 between
`data\game` and `data\lobby`, 23 inside `data\game` (settler and soldier meshes, idle animations, door clips,
`color_slots.xml`); 29 of them are identical in every copy. No video file exists in the installation.

## 3. Storage layout [draft]

| Location | Written by | Holds |
|---|---|---|
| the installation | never | the player's copy of the original |
| `<conversion folder>/<install id>/` | the converter | the converted tree in open formats, plus `conversion.json` (the source list and what each output was made from); the conversion folder is chosen at the first start (below) |
| the game's folder: `settings.xml` | the game, at the first start | the installation's path and the conversion folder [implemented, maintainer 2026-10-15] |
| `<user data>/cache/` | the game, on demand | engine-native forms of converted and modded assets (Godot binary meshes, baked animation textures, compiled shader variants), keyed by `(content hash, converter version, engine version)`; may be deleted at any time |
| the game's folder | the installer | the engine and, in `mods/`, the mods that ship with it: `core.game`, `core.mainmenu`, `core.lobby`, `refined`, `tools.assetbrowser` (assemblies, shaders, the remake's own layouts) |
| `<user data>/mods/`, `mods-received/` | the player / transfers | mods ([mods.md](mods.md) §4) |
| `<user data>/maps/`, `maps-received/` | the editor / transfers | map packages (§7) |
| `<user data>/saves/`, `profiles/`, `settings.xml` | the game | saves, mod profiles, settings |

`<user data>` is Godot's `user://` of the remake, a custom user folder named `sadk-remake` (`%APPDATA%\sadk-remake`
on Windows, `~/.local/share/sadk-remake` on Linux); the headless runner computes the same folder. **The conversion
folder** is the player's choice at the first start (maintainer, 2026-10-15): the game suggests
`%LOCALAPPDATA%\sadk-remake\converted` on Windows (not the roaming folder, for 1.3 GB) and `<user data>/converted`
elsewhere, shows the free space, and keeps the choice with the installation's path in `settings.xml` next to the
executable (the project folder when run from the editor; the user folder when the game folder is not writable).
Deleting `settings.xml` makes the next start ask again; `--conversion=<folder>` sets it for unattended runs. The `<install id>`
is a hash of the installation's path and its identity, so two installations (another language, another patch)
convert side by side. A conversion folder holds [implemented]:

| Path | What |
|---|---|
| `data/` | the converted tree: the bottom layer of the virtual file system, logical paths as the installation spells them |
| `maps/` | the map packages (§7) |
| `conversion.json` | the record: identity, converter versions per job kind, every source file (path, size, time, SHA-256), every job (sources, read-only dependencies, outputs with SHA-256, error), the compatibility CRCs |
| `conversion.journal` | while a run is going: one line per finished job, so an interrupted run resumes; folded into the record at the end |
| `report.md` | what was converted, rewritten, skipped (with the reason) or failed |

## 4. The conversion

### 4.1 When and what is checked [draft]

1. **Find the installation**: the recorded path, else the known install locations, else ask the player. Identify it
   by the build number (34688) and patch level (9212) and its language folder. An unknown build is converted with a
   warning; compatibility mode is offered only for the known one. [implemented, maintainer's rule 2026-10-15] The
   patch level is `[Lobby] patchlevel` of `game/settings/network.ini` (a file with a UTF-8 byte order mark). The
   executable is recognised by its hash among the known ones, the retail (SecuROM) and the DRM-free `SADK.exe`, which
   also gives the build (34688, the constant `g_BuildVersion` S 008793c0). The data files are compared with a
   **reference edition**: the SHA-256 of every file of an unmodified installation (`de-retail-9212`, 4,451 files,
   made from the maintainer's original installation), shipped with the converter, never the files themselves.
   - After every conversion, and at every start from the record's hashes (milliseconds), the installation is compared
     with the edition of its language and patch level. Changed, missing and added files are **warnings**: a changed
     file that parses is converted and used, one that does not is a failed job as well. Files on the ignore list do
     not count.
   - The player may ignore the warnings ("Ignore and continue" or "Quit"); the choice is remembered for exactly that
     state, so any further change is asked about again.
   - The record keeps two **base game hashes**: one over every converted source (content) and one over the files the
     original's build checksum covers (`scripts/**/*.lua`, `settings/**/*.xml`: the rules). They are the identity of
     base game that network games compare (mods.md §9.1), so a modified installation cannot pass for an original one;
     a presentation-only change (textures, sounds, texts) leaves the rules hash alone.
   - [measured] The original installation converts with 0 differences. A patched copy (fog values raised in all 31
     map `.bin` sidecars, a changed `daytimes.xml`, three ini files) shows those 34 files; `daytimes.xml` changes the
     rules hash, as it changes the original's own build checksum.
2. **Check** at every start: compare the recorded list (relative path, size, modification time) with the disk. A
   difference: hash the file; if the hash changed, mark the outputs made from it for conversion. Moving the
   installation keeps the conversion valid when the hashes match at the new place.
3. **Missing installation**: the game does not start and says which folder it expected [binding].

### 4.2 The pipeline [draft]

- `Sadk.Convert`, a library without Godot, run inside the game at first start (with a progress screen fed by
  progress events) or headless (`Sadk.Headless --convert`).
- One job per source file and kind, run in parallel. Each job writes to a temporary file and renames it when done,
  and the record is updated per finished job, so an interrupted conversion resumes.
- **Jobs** [implemented]: factories hand the source files to jobs in a fixed order (map packages first, so they
  take their companions; then fonts with their pages; then one factory per format); files on the ignore list
  (§6.1, last row) are taken out before, and a file no factory takes is listed in the report. A job may read files it
  does not own (a map reads the text tables for its keys) and lists them as dependencies. Each job kind has a
  converter version; raising it converts that kind again at the next start. A failed job leaves no output behind and
  runs again only when its kind's version changes; the report names it with the reason.
- **Deterministic output**: the same source gives byte-identical output, so outputs can be compared between
  machines and used as cache keys. [checked] Two full conversions of the reference installation agree output for
  output (`Sadk.Headless compare`).
- **Self-checks** run as part of the conversion: every container's CRCs (the reader checks them), every `.KEX` and
  `.pfx` parses completely, every map parses to its last byte, and the settler palette test vector
  (`AM` §3.15) comes out right. These are the viewer's `tools/KexCheck` and `tools/MapCheck`.
- **Compatibility records**: for every `scripts\**\*.lua` and `settings\**\*.xml` the converter keeps the container
  header field +0x08 (the plaintext CRC-32), which is what the original's build checksum XORs
  (`GameData_ComputeBuildChecksum` S 005ab800, DL §3). Without them the remake cannot answer an original client's
  checksum in a compatibility-mode match. [measured] The reference installation contributes 171 files (157 Lua: the
  property scripts, info pages, map tools, editor brushes and `graphic_main.lua`; 14 settings XML; `data\lobby` has
  no such folders; map scripts and `menu.cfg` do not count) whose CRCs XOR to **0x555bfa51**. The conversion compares
  its value with that one and reports a difference.
- **Base reference resolution**: the original finds nearly every file by its bare lower-case name, whatever folders
  a reference names (§5.4). The converter applies that rule once to every reference written in the original's data
  (XML attributes, Lua path strings, `.npc` strings, KEX material texture names, the names the code builds) and
  reports each reference that resolves through a duplicate name or not at all. The converted tree then uses
  logical paths only.

### 4.3 Expected cost [estimate]

Container decoding, KEX parsing and writing, map packaging and Lua conversion take seconds each; with textures kept
in their compressed form the first start should take on the order of a minute. The one slow step would be encoding
block-compressed textures; §6.2 keeps that to the DXT1 textures with one-bit alpha and a fast encoder.

## 5. Virtual file system and asset lookup

### 5.1 Layers [draft]

All assets are read through one virtual file system of **logical paths**. Layers, from bottom to top:

1. the converted installation (the base game's content from the player's copy);
2. the mods' `assets/` folders, in load order ([mods.md](mods.md) §5): first `core.game`'s (the remake's shaders,
   layouts, UI parts, visual-descriptor extensions), then `refined`'s when active, then the others;
3. the current map package's `assets/` folder, while that map is loaded [binding: a map's files before the base
   game's].

A file in a higher layer **shadows** the file with the same logical path below it. That is how a texture pack
works, and how a map brings its own skydome. Presentation XML documents are not shadowed but **merged** across
layers and then patched ([mods.md](mods.md) §6.6).

### 5.2 Logical paths [draft]

- Forward slashes, compared case-insensitively (the original's lookup is case-insensitive, the Linux file system is
  not), no `[data]` prefix, rooted like the original's data tree: `game/buildings/pb_b_bowmaker01.kex`,
  `game/map/textures/z_meadow_00.dds`, `lobby/...`.
- A mod's new assets go under `mods/<mod id>/...` by convention, a map's under `maps/<map id>/...`, so new files never
  collide by accident; shadowing an existing path is always deliberate.
- **Kind-based extension resolution.** References carry the original's extension (`.kex`, `.dds`), but the lookup
  treats the extension as a hint: for a reference of a given kind it searches each layer, top first, for the stem
  with every extension that kind accepts. Within one layer the first extension in the kind's order wins; across
  layers the higher layer wins whatever its extension. So a mod replaces a `.kex` model by a `.glb` or a `.dds`
  texture by a `.png` at the same path.

| Kind | Extensions, in order |
|---|---|
| model | `.glb`, `.gltf`, `.kex` |
| texture | `.dds`, `.ktx2`, `.png`, `.webp`, `.jpg`, `.tga` |
| sound | `.ogg`, `.wav`, `.mp3` |
| shader | `.gdshader`; include `.gdshaderinc`; compute and post effects `.glsl` |
| effect | `.pfx.json`, `.pfx` |
| font | `.fnt` (with its page), `.ttf`, `.otf` |
| text table | `.txt` (UTF-8, the original's syntax) |
| presentation XML, layouts | `.xml` |
| Lua | `.lua` |

- **Loaders by format.** Each `(kind, extension)` has a registered loader; mods can register loaders for new formats
  ([mods.md](mods.md) §6.7). The `.kex` loader is the converter's reader with its bake (`Sadk.Formats`), so a mod
  made for the original that ships raw `.KEX` files works unconverted.

### 5.3 References in data [draft]

- Registry entries and presentation documents name assets by logical path with the kind given by the field
  (`ModelRef`, `TextureRef`, `SoundRef`, `ShaderRef`, `EffectRef`). Entries of the original name presentation by
  **gfx name**, resolved through the visual descriptors ([renderer.md](renderer.md) §5).
- References are checked after the presentation documents are parsed ([mods.md](mods.md) §6.1 step 7): a missing
  asset is logged once, naming the mod and entry that referenced it. In faithful mode the object is not drawn (as in
  the original: "no match, no object, no error"); in refined mode a placeholder is drawn.
- The simulation never resolves an asset ([mods.md](mods.md) §8.3).

### 5.4 The original's bare-name rule [draft]

The original resolves a request by its file name through an index built once at start-up; the folders in the
request only decide between files of the same name, by a substring test on the candidate's last folder name
(`FileScan::ResolvePath` S 006ef8a0, `PickCandidateByParentDir` S 006ef680; FI §3.1). The shipped data relies on it
(`[data]\scripts\campaignMaps\C02_11bigBUILD.lua` loads a file from `maps\campaignMaps`).

The exact rule [known, FI §3.1]: the request is lower-cased with `/` turned into `\`; its name is the part after the
last `\`; one file of that name is found whatever folders the request names; of several, the first in the
index's scan order whose last folder name plus `\` occurs anywhere in the request (a plain substring test, so
`maps\` also matches `campaignmaps\`); a request without `\` finds nothing when the name occurs more than once.
`[data]` is never substituted. [measured] Of the 2,792 XML values with an extension, 2,395 resolve by a unique name,
366 through a duplicate name by the folder test, 25 not at all (bare duplicate names in the lobby's
`bodyparts.xml` and `npc_bodyparts.xml`, §9) and 6 name files that do not exist.

The remake reproduces the rule in two places only:

- in the converter, for every reference of the shipped data (§4.2);
- in the compatibility path resolver of the Lua host, for `[data]\...` paths that scripts pass at run time
  (`Default.CallScript`, cutscene paths), over a file-name index of all layers ([lua.md](lua.md) §4.6).

Everything else is addressed by logical path. A map's file named `door_open.kex` therefore cannot shadow every
building's door clip.

### 5.5 Loading and lifetime [draft]

- **Lazy, cached**: an asset is loaded on first use and cached by logical path. A cache entry belongs to the layer
  that provided it; entries from a map's layer are released when the match ends.
- **Preload per match**: before a match starts, the presentation collects the visual descriptors of every type the
  map contains and every type its players can build, and loads their assets behind the loading screen, so no file is
  read during play (the original reads `.pfx` files at every effect start and models when objects are created).
- **Threads**: file reading, decoding and mesh building run on worker threads; GPU resources are created on the
  main thread.
- **Development mode**: files of the mods are watched; a changed asset is reloaded and its users notified.

### 5.6 Packed assets and overlay folders [implemented, maintainer 2026-10-15]

A zip in the file system, such as a map package (`maps/<name>.sadkmap`), is a **packed asset**: opened, it is a file
system of its own. A **folder with the same logical path** as the packed asset, in any layer, is laid over its
contents: a file there shadows the package's file of the same inner path, a new one adds to it. Overlay folders
stack in layer order on top of the package, so a later mod wins; the package file itself is never changed.

```
english/assets/maps/MP_2P_steinfjord.sadkmap/locale/en/map.txt   adds an English text table to the map
fixes/assets/maps/C01.sadkmap/locale/de/map.txt                  shadows the map's own German texts
```

What a map package's overlay changes counts like the package's own content: an overlay of `world/` or `script/` makes
a different map, so the map's identity in multiplayer is computed over the package as seen through its overlays
(§7); texts, previews and the map's own assets only change the presentation. The game's file system mounts the
`assets/` folder of the opened package, overlays included, as layer 5 (§5.1) while the map is loaded.

## 6. Formats after conversion

Answers [binding] architecture §13 item 4. The rule: open formats that modders can edit with common tools, keeping
everything the original's look depends on; engine-native forms only in the disposable cache.

### 6.1 Overview [draft]

| Source | Converted | Runtime loader | Notes |
|---|---|---|---|
| `.kex` mesh, skeleton | `.glb` (glTF 2.0) with an extension `SADK_kex` | glTF reader → the renderer's mesh, skeleton and animation tables | §6.3 |
| `.kex` animation | `.glb` with the animation and the skeleton nodes it targets | same | keys stay evenly spaced (`keyCount` over `length`); nothing resampled |
| `.dds` BC1 without alpha, BC2, BC3, A8R8G8B8 | `.dds`, unchanged; mip chains completed where they are missing | `Image.LoadDdsFromBuffer` | §6.2 |
| `.dds` A4R4G4B4, R8G8B8, R5G6B5, A1R5G5B5, A8 (55 files) | `.dds` A8R8G8B8, every value expanded exactly (`round(v · 255 / max)`; A8's colour 0, as D3D9 samples it) | same | so Godot's loader always gets a format it reads |
| `.dds` BC1 with one-bit alpha | `.dds` BC3 | same | §6.2 |
| `.dds` cube maps (2) | `.dds`, unchanged | own reader: the six faces as images, then a `Cubemap` | Godot's loader reads only the first face [viewer, checked] |
| settler and avatar colour-index maps (`*_colorindices_*`) | `.dds` A8R8G8B8 unchanged (including the original's mip chain); the lobby's R8G8B8 ones expanded to A8R8G8B8, levels as they are | point sampled | never filtered, compressed or re-mipped (AM §3.15) |
| `.tga` | `.png` (top-left origin; grey, RGB or RGBA as the source) | `Image.LoadPngFromBuffer` | colour ramps, the building colour map and UI atlases keep their exact texels; also `game/animals/pig.dds`, which holds a BMP, and the one encrypted `.png` |
| `.bmp` map previews | `.png` inside the map package | — | §7 |
| `.ogg`, PCM16 `.wav` | unchanged | `AudioStreamOggVorbis`, `AudioStreamWav` | |
| IMA ADPCM and float `.wav` (23) | PCM16 `.wav` | `AudioStreamWav` | converted always, so the question whether Redot reads them as they are (AU §10 Q11) does not arise |
| `.fnt` + `_00.tga` page | `.fnt` with glyph ids mapped from Windows-1252 to Unicode, the original's padding arithmetic applied (padding and spacing then 0), a `page` line naming the page, kerning kept; page as `.png` | own reader building a `FontFile` (Godot's `LoadBitmapFont` reads only real files) | the original's glyph ids are cp1252 bytes and its reader ignores kerning and the `page` line (FI §3.6) |
| language `.txt` tables | UTF-8 `.txt` with the original's syntax (`key<TAB>value`, later wins, `\n`) | own loader | keys verbatim, `!` included; a missing key shows the key, as in the original; `info.txt` and `dialogs.txt` are loaded by no code and not converted |
| `engine.ini`, `network.ini`, `LobbySettings.ini`, the lobby's `;`-separated tables (`lobby/config/*.txt`) | copied as they are | — | |
| `.pfx` | `.pfx.json` (lossless: the grammar of `../sim/particles.md` §3.1) | own loader (both forms) | |
| settings XML, UI layouts | decrypted `.xml`, unchanged | presentation documents | merged and patched ([mods.md](mods.md) §6.6) |
| `.lua`, `menu.cfg` | converted Lua ([lua.md](lua.md) §3) | Lua host | the original source is kept beside it as `<path>.orig` for error reports |
| `.s2m` + `.bin`, `.bmp`, `.lua`, cutscenes, briefing texts | map package (§7) | map loader | |
| `.npc` | `.json` + palette `.png` | lobby / avatars | only when the remake has the 3D lobby |
| `.fx`, `.inc` | not converted | — | the remake's shaders are its own files in `core.game`; the `.fx` names stay lookup keys ([renderer.md](renderer.md) §7.5) |
| `.psd`, `.lep`, `.ico`, `.html`, `.sav`, `.fx`, `.inc`, `.npc`, unused text tables and ini copies, the installer pictures, the two prototype maps (124 files) | not converted; the report lists each with its reason | — | FI §3.14; the prototype maps need `tools/s2m_upgrade.py` first (MF §9) |

### 6.2 Textures [draft]

- Compressed textures stay compressed: BC1, BC2 and BC3 are GPU formats on every renderer.
- **BC1 with one-bit alpha** loses its alpha on Godot's Vulkan path (Vulkan uploads it as RGB) [viewer]. The
  converter transcodes these to BC3 (maintainer's decision, 2026-10-15): the alpha block holds the one-bit alpha
  exactly, the colour block is re-encoded from the decoded colours. Twice the size of BC1, an eighth of RGBA8.
  [measured] 234 of the 792 DXT1 files use a transparent texel (a three-colour block with index 3) inside the
  surface; four-colour blocks are copied unchanged. A three-colour block cannot be kept exactly: BC3's colour line has
  no midpoint and no black off the line, so the encoder chooses among range-fit, the original end points and widened
  end points, opaque texels first. The largest opaque error is 42 (0.34 % of the opaque texels differ by more than
  16); 85.8 % of the transparent texels stay black, the others take the block colour nearest to black, which only
  shows as the colour bilinear filtering blends in at cut-out edges (the original blends black there). The report
  gives both errors per texture. The maintainer compared originals and transcodes side by side (2026-10-15): the
  difference is barely noticeable, BC3 stays. Keeping the BC1 bytes exactly would need an own upload through
  `RenderingDevice` as BC1 with alpha (Godot's `ImageTexture` path uses the RGB variant on Vulkan); not needed now.
- **Missing mip chains** of 3D textures are completed at conversion: the last level present is decoded, box-filtered
  down to 1 × 1, and each new level encoded in the texture's own format (BC1, BC2, BC3 or A8R8G8B8). [measured] 226
  textures have no chain and `game/map/objects/buoy.dds` stops after three levels; 114 are completed (the 95
  animated water frames among them). This is needed, not only nicer: Godot's DDS loader rejects a partial chain
  [checked]. UI textures keep their chain as it is (four DXT5 UI textures and `PokerCards.dds` ship with full ones):
  everything under `game/gfx/` except the decals (`decals.dds`, `buildingselect.dds`, `catapultTarget.dds`), plus
  `lobby/gfx/Village_Minimap.dds`, `PokerCards.dds` and the localised `ui_s2logo*.dds`.
- The six settler colour-index maps (about 100 MB uncompressed) are kept byte for byte: the original's mip chain
  holds only level-0 values and the shader samples them point-wise.
- [measured] The converted textures and pictures take 847 MiB (A8R8G8B8 644 MiB, mostly the colour-index maps);
  every output loads with Godot's `LoadDdsFromBuffer` / `LoadPngFromBuffer` with its full number of levels, and the
  decoded texels match the converter's own decoders (colour ±1 from rounding of interpolated BC colours).
- `animals\pig.dds` holds a BMP; seven textures have non-power-of-two sizes (FI); the converter handles both.

### 6.3 Models [draft]

- One `.glb` per `.KEX` file, in Godot's axes `(x, y, z) → (−y, z, −x)` with every triangle reversed, after the
  client's load-time bake (identity keys stripped, bone orientations flattened, the scale channel folded into the
  positions; AM §3.1).
- **The caller's model scale is not baked.** The original bakes the scale chosen by the loader (settlers 1.2,
  animals and ships from their XML, buildings 1.0) into the vertices and leaves normals `1/s` long, which its light
  depends on. The converter writes unscaled meshes; the scale is applied per definition at run time and the shaders
  restore the normal length (`normal_scale`, [renderer.md](renderer.md) §7.4).
- The `SADK_kex` glTF extension keeps what glTF has no place for: the source axes and `unitScale`, `exportName`,
  material usages (`DiffuseColor`, `Self-Illumination` = light map, `Opacity`) with the bare texture names and the
  logical paths they resolved to, the per-mesh bone name lists, the extra UV sets (buildings use three) and vertex
  colours.
- Mesh, node and bone names are kept: the original's code addresses them (`House`, `GROUND`, construction stages
  `0..N−1`, `MILFLAG`, `FIRE_%02d`, `SLOT_HandR`, `SLOT_Goods`, `ROTATE`, `ARM_ROTATE`, `BULLET_POS`,
  `boneLink<i>`).
- The renderer does not keep glTF scenes as node trees: it converts them into its own mesh, skeleton and animation
  tables and caches those as engine-native resources ([renderer.md](renderer.md) §6).
- [implemented 2026-10-15, sadk-remake `Sadk.Formats/Gltf`] The engine-neutral model (`SadkModel`) is what both
  sides share: the converter writes it as `.glb`, the runtime reads `.glb`, `.gltf` and raw `.KEX` into it.
  - **Units**: positions are divided by the file's `unitScale` (1, 39.37 or 100), which is the original loader's
    result for model scale 1.0; the extension keeps `unitScale` as a record only, and the runtime must not divide by
    it again (the light's `normal_scale` takes the definition's model scale alone).
  - **Axes**: the original's import transform, then z negated; for every shipped file `(x, y, z) → (−y, z, −x)`.
    Rotations, inverse bind matrices and keys are carried through it; a skinned mesh in its rest pose equals the
    unskinned mesh, and every animated pose equals the file's own under the transform [checked, tests].
  - **Winding**: the model is in Godot's order; the `.glb` holds glTF's counter-clockwise order, and writer and reader
    swap two indices per triangle, as Godot's own glTF importer does.
  - **Standard attributes where glTF has them**: extra UV sets (`TEXCOORD_0..3`) and vertex colours (`COLOR_0`,
    normalised bytes); the KEX tangent has no handedness and goes into `_TANGENT`. Meshes skinned to another file's
    skeleton (381: settlers, animals, ships) keep their joints and weights in `_JOINTS_0` / `_WEIGHTS_0` and their
    bone names in the extension; meshes skinned to their own file's skeleton get a glTF skin.
  - **Animations**: key `i` at `i · length / keyCount`, LINEAR, nothing resampled; `length` and `keyCount` are kept
    in the extension, since the original blends the last key back to key 0. A channel the KEX track lacks is written
    out as position 0 or rotation identity, which is how the original samples it (not the rest value).
  - **Kept only in the extension**: materials with no triangles (1,552, for their texture references) and the 15
    animations with no channel at all.
  - **Repairs that do not change what the original draws** are reported: zero or non-finite normals take their face
    normal (114), tiny negative weights become 0, a joint repeated within one vertex is merged.
  - [measured] 1,639 files, 5,332 meshes, 189 skeletons, 520 animations, 200 MB; 1.4 s; every output passes the
    Khronos glTF validator without error or warning. Texture references: 6,462 resolve exactly (139 through a
    duplicate name), 100 only with `.dds` for the written extension, 1,963 are missing in `game/character/meshes` and
    `lobby/avatars` (replaced at run time by the settler and avatar colour data), 4 elsewhere.
  - The writer adds no glTF images: the textures are `.dds`, which core glTF does not allow, so other tools show the
    models untextured; the reader ignores embedded images with a warning.

## 7. Map packages [draft]

A map is one file, `<name>.sadkmap` (a zip; a folder in development), so that it is shared, hashed and cached as a
unit. It lives in the file system at `maps/<name>.sadkmap`: the converted original maps in the converted tree, a
mod's maps in its `assets/maps/`, received and editor maps in their own layers; overlay folders of the same name
change or add files without touching it (§5.6).

```
<name>.sadkmap
  map.xml                  manifest: id (the MapInfo UUID for converted maps), name, version, content hash,
                           format, players, size, title and description keys, required mods (id, version, hash),
                           whether original clients can play it, the script profile (`scriptApi`: `original` or
                           `remake-1`, lua.md §2.3)
  world/<name>.s2m         the original layout, read by the original's reader (compatibility mode); maps made for
                           the remake later use the remake's own map format (§7.2)
  world/environment.xml    the contents of the original's `.bin` sidecar (skydome, light, fog, environment spheres)
  script/<name>.lua        the map script; script/<name>_<n><cutscene>.lua the camera paths
  locale/<lang>/map.txt    the map's own text keys (briefings, quest texts)
  preview.png
  assets/                  a layer of the virtual file system for this map (§5.1)
```

- Original maps are packaged at conversion: each `.s2m` (decrypted) with its `.bin` (as `world/environment.xml`,
  the field names of `local_enviroment.xml`, floats in round-trip form), `.bmp` (as `preview.png`), `.lua` and
  cutscene scripts (`<name>_<k><label>.lua` beside the map, converted, the original beside as `.orig`), under the
  map's internal name (MapInfo `+0x24`). The map's own text keys go into `locale/<lang>/map.txt`: for campaign map
  `C<nn>` the briefing pages `B<n>_*` (n without the leading zero, `C01` → `B1_`) and `C<nn>`, `C<nn>_*` (title,
  subtitle, description, quests) of `briefings.txt`; for a free map its title, the key of its name in `ui.txt`
  (free maps have no description keys). `map.xml` [implemented] carries `id` (the MapInfo UUID, Microsoft byte
  order), `name`, `version`, `contentHash` (SHA-256 over the package's other files), `format`, `type` (campaign or
  free), `players` (start positions), `width`, `height`, `originalClients`, `scriptApi`, `titleKey`,
  `descriptionKey` and `RequiredMods`. The whole map is parsed to its last byte as the package's self-check. In the
  reference installation all 31 current maps have their file name as internal name; the two prototype maps in the
  old layout are not packaged (`MF` §9; `tools/s2m_upgrade.py` converts them).
- **Maps carry no assemblies and no data-stage scripts** in the first version: a map that needs new registry types
  needs a mod and names it in `required mods`. Maps can add assets, presentation XML (new visual descriptors, a
  patched skydome list) and scripts. Because maps are data only, they can be transferred without the trust question
  of code mods ([mods.md](mods.md) §7.4).
- **Transfer**: the lobby announces the map's id and content hash; a peer without it receives the package as one
  stream with a sliding window (today's assetshare sends one archive per file in 4 KB stop-and-wait blocks). A
  compatibility-mode match with original clients can only use original maps (the `.s2m` and its companions), since
  the original resolves nothing else.

### 7.2 The remake's own map format (later) [draft]

The `.s2m` stays the format of original maps, read bit-exactly for compatibility mode. Maps made with the remake's
editor need room for layers that mods add, so the remake's own format is a list of named, versioned sections, each
owned by a system (engine grid layers, `core.game` sections, a mod's sections). A section of a mod that is not present is
kept unread and written back unchanged. Designing it belongs with the map editor.

## 8. What is loaded when [draft]

| When | What | Notes |
|---|---|---|
| start | settings; installation check; conversion if needed | §4 |
| start | mods resolved, file system mounted, assemblies loaded | [mods.md](mods.md) §6 |
| start | data stage: the property scripts, the settings XML values the simulation reads, `menu.cfg` values (player colours, language) | the original reads the scene XML per match (DL §2); it does not change between matches, so the remake reads it once |
| start | presentation documents merged and parsed; the sound table built from the registry's sound entries (files themselves load lazily: the original decodes every sample at start, AU §3) | |
| start | UI: layouts, fonts, text tables of the chosen language, cursors | |
| match load | map package mounted; map read; script converted (if not cached) and loaded; preload of the match's assets (§5.5) | |
| match | nothing read from disk except streamed music and voices | |
| match end | the map's layer and its cache entries released | |

**Language**: one shipped folder (`de`) in the reference installation; the remake's language is its own setting,
defaulting to the installed folder. Text tables, fonts, localised textures and the 540 voice files follow it.
[draft, agreed with the maintainer 2026-10-15] Texts are looked up per key in two scopes:

- **game scope**: `game/language/<lang>/*.txt` of every layer, merged per key in layer order (a mod's table wins over
  the base game's);
- **map scope**: the map's `locale/<lang>/map.txt`, as seen through its overlay folders (§5.6).

A map's script and briefings look in map scope first, then game scope; the game's own UI only in game scope. Each
lookup falls back per key: the chosen language, then the installation's language, then the key itself, as the
original shows a missing key. A translation mod therefore ships `game/language/en/` (which also makes the language
selectable) and needs map-scoped files only for a map's keys of its own; the campaign's keys (`B<n>_…`, `C<nn>…`)
are global, so a translated `briefings.txt` covers the campaign. Texts never change the simulation, so a translation
is a client-only mod; the one text-derived value the simulation uses, the number of briefing pages
(`txt.isValid`, [lua.md](lua.md) §6), comes from the map's base language. Voices
(`game/language/<lang>/voices/<key>.ogg`) fall back the same way; a text-only translation keeps the original voices.
The original fonts hold Windows-1252 glyphs only: a translation into another script brings its own font.

**The text service** [implemented, sadk-remake 2026-10-15]: the engine resolves keys without Godot
(`Sadk.Engine.Text.TextService`, the static front `Locale`; mods get it as `ModContext.Text`), so Lua, the headless
runner and the server use the same lookup; the presentation loads the same tables into Godot `Translation` resources
of the `TranslationServer`, so controls translate their text themselves and a language switch updates every visible
label.

- **Keys** are written as the original writes them: a leading `!`, no trailing one (`!EXIT`, `!SINGLE PLAYER`); a
  text that starts with `!` is a key (`nUi::Text` S 004b46d0); a missing key shows as itself and an empty key gives
  an empty text (`Localization::GetText` S 00496070). A mod's own keys are `!<mod id>.<name>` in its
  `assets/game/language/<lang>/*.txt`.
- **Order**: within a language, map scope before game scope; the chosen language before the base language across
  both scopes, then the key. Within a layer the original's five files come first in its order (briefings, ui,
  credits, lobby_ui, lobby_items; `Localization::LoadAllTextFiles` S 00496b80), then the layer's other `*.txt` by name.
  `game/language/<lang>/` is the original's `[data]\language\<code>\` (S 00496b80, `BuildLanguagePath` S 004955a0).
- **Godot**: the message ids are the keys as written; each language's translation has the base language merged under
  it, so Godot falls back per key as the engine does. While a map is entered its texts sit in the translation domain
  `sadk.map`. The tables are rebuilt on every change (mod set load or unload, language switch) and removed with the
  mod set.
- **Language**: `settings.xml <Language code>` in the game folder, overridden by `--language=<code>` for one run, and
  switched with the intent `engine.language { code }`. When the base language cannot be told, it is the
  installation's only language folder. `Locale.LanguageFile("fonts/X.fnt")` finds a file of the chosen language (with
  the same fallback).

## 9. Open points

1. Settler lookup keys: the character name per settler type is chosen in code and is not simply the good's name
   (`good_helper` is drawn as `Carrier`) (AF; `../sim/rendering.md` §3.9). The building key `<tribe name>_<gfx
   name>` has no case question in the shipped data: 104 of the 109 `tp_addBuilding` pairs match `buildings.xml`
   exactly, the other 5 (`<tribe>_MediumDummy`, two `OlympicFlame`) have no entry.
2. Readers of `items.xml`, `sf_setBuffGfxName` and the building-level `<PFX>` / `<Particle position>` elements
   (`../sim/tribes-content.md` §10 Q5, Q6; `../sim/particles.md` §10 Q3).
3. Reference editions of other languages and patch levels (§4.1): an English or French installation would add its
   fingerprint and settle §9 item 5 at the same time.
5. Other retail languages: folder names and whether their installations differ beyond `language\` (an English or
   French installation would settle it).
6. The water-preset index of `MapInfo +0x1cc` and the `.bin` field names (MF §4.2, §4.17).
7. The lobby's `bodyparts.xml` and `npc_bodyparts.xml` name 25 textures by bare duplicate names, which the original's
   lookup does not find; the lobby loader probably puts a folder in front (FI §3.1).
8. How the original treats KEX material texture names with `.psd`, `.bmp` or a missing `.tga` (AM open question 13);
   the converter tries the name, then the same name with `.dds`.
9. Four skeletons fit their inverse bind matrices only before the load-time bake (`deer_model`, `elk_model`,
   `AO_FishingRod01_Model`, `PV_R_Ship01Model`; off by up to 2.0, 0.65 and 0.33 after it; AM §2.6 counts 181 that fit,
   the baked data 177): either the original draws these rest poses distorted, or `FlattenBoneOrientations`
   S 0072ce50 does more than `position · inverse(own 3×3)`. A question for Ghidra.
10. Which of two bones with the same name a track drives: the converter gives the k-th track of a name to the k-th
   bone of that name (the two Castle door clips animate two `ee_door1` bones).

