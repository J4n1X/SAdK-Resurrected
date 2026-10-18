# File formats and assets: inventory and conversion targets

Binary: `sadk_noav.exe` (image base `0x400000`). `S 00xxxxxx` = static address in that image.
Tags: **[known]** = read at the given address or in the named data file; **[inferred]** = one step of reasoning
from what is visible; **[TODO]** = not established. Nothing here was observed in the running game.
Counts are for the reference install (`~/sadk_game`, AdK patchlevel 9212, German).

## 1. Purpose and scope

Every kind of file the client reads from its install folder and from the user folders, with: what it holds, which
function reads it, whether it must be an encrypted container, its layout, how the file is found, and the format a
one-time converter of a Godot remake should produce.

Specified in this document (not specified elsewhere): the file lookup (§3.1), `.pfx` particle effects (§3.3),
`.fx` shaders (§3.4), `.npc` / `.avo` avatar files (§3.5), `.fnt` fonts (§3.6), `.lep` (§3.7), the UI layout XML
(§3.8), localisation text (§3.9), `cursors.xml` and the small settings files (§3.10), the user profile files
(§3.11) and the caches the game writes (§3.12).

Specified elsewhere and only linked here:

| Topic | Document |
|---|---|
| Encrypted container (header, key, scramble, LZSS) | `docs/asset-formats.md` §1 |
| `.KEX` scenes (meshes, skeletons, animations) | `docs/asset-formats.md` §2 |
| `.s2m` maps, the `.bin` sidecar | `docs/map-format.md` (§4.17 for `.bin`) |
| Save games (`.aav`, `.sav`), `.info` caches, section tags, stream classes | `docs/sim/save-format.md` |
| Multiplayer saves (`mp_saves`) | `docs/multiplayer-save.md` |
| Property scripts (`scripts\properties\*.lua`) and their records | `docs/sim/properties-data.md` |
| Lua libraries, map scripts, script loading | `docs/lua-surface.md` |
| When each data file is read (start-up or per match), the build checksum | `docs/data-loading.md` |
| `network.ini` keys | `docs/NCOMM_LAYER.md`, `docs/sim/logic-core.md` |
| Lobby item files (`ItemsClient.txt`, `itemicons.txt`) in use | `docs/village-and-character-protocol.md` |

Out of scope: the network protocols, and `bin\` (executables, DLLs, `msgdefs.ini`).

## 2. Data model

### 2.1 Roots and virtual paths

| Item | Value | Evidence |
|---|---|---|
| Game root | parent folder of the folder holding the executable (module path cut at its last two `\`); made the working directory at start | [known] `WinMain` S 00407cf0, `App_SetGameRootDir` S 0057bc90 |
| Data roots | `data\game\` and `data\lobby\` | [known] strings in `FileScanHolder::ResolvePath` S 006e3fd0 |
| Virtual prefix | `[data]\` (also written `[data]/`) in file names inside the binary and the data | [known] e.g. S 007f9198 |
| User folder | `<My Documents>\SAdK\` (CSIDL 5, literal `SAdK` S 007d421c) with `users`, `maps`, `saves`, `mp_saves`, `dumps`, `dumps\lobby`, `screenshots`, `lobby` | [known] literals S 007e9c0c `maps`, `Str_InitLiteral_*` S 0057bb70..0057bc60; `Fs_CreateUserDataDirectories` S 0057bfb0 creates the root and seven of them (8 `CreateDirectoryA` calls, results ignored), not `mp_saves`; [TODO] not established: who creates `mp_saves` (callers of `Str_InitLiteral_mp_saves` S 0057bc30) |
| Cache folder | `<Local AppData>\SAdK\` (CSIDL 0x1c), created on demand by `Fs_CreateLocalAppDataGameDir` S 0057bcc0 | [known] `Sys_GetLocalAppDataPath` S 0057ba10, `CMesh::GetPackedCachePath` S 0076c9f0 |

### 2.2 The file index (`ai::file::FileScan`)

One object, held by the global `FileScanHolder` (getter `ai::file::FileScanHolder::GetInstance`).

| Field | Meaning | Evidence |
|---|---|---|
| `+0x00` byte | set once the first scan stored the root | [known] S 006ef440 |
| `+0x04` string | the root argument of the first scan. The start-up scan passes an **empty string** (the scanned directory `data\` is a separate argument), so it stays empty | [known] S 006e3ca0, S 006ef440 |
| `+0x20` map | key: **lower-case file name with extension, no folder**; value: list of the directories that hold a file of that name | [known] S 006f10e0 (`__strlwr` of the found name, map find, new list or append) |

No hash is involved: the key is the name itself. Every file below `data\` is entered, whatever its extension
[known] S 006f1330 (only the directory attribute `0x10` is tested).

### 2.3 Encrypted container

`docs/asset-formats.md` §1. Two facts matter for an inventory:

- **The reader decides, not the file.** `NBase::gDecryptData` S 006e6660 has no "plain file" branch: a buffer whose
  dword at `+4` is not `"sadk"` is logged (`file %s: FCC mismatch`) and the function then writes to address 0
  [known]; the three later checks (key CRC, size, data CRC) log and fault the same way. Nor does it test the
  buffer: `File_ReadAndDecrypt` hands it whatever `gReadFileData` returned, which is null for a missing or
  empty file [known]. A file type read through `File_ReadAndDecrypt` S 006e7770 or `XmlDoc::LoadFromFile` S 006e8210
  therefore **must** be a container; a type read with `NBase::File` S 006e6a30 / `NBase::File::Read` S 006e6530
  must be plain.
- The file key depends on the lower-case file name (except `.s2m` and `.aav`), so a container only opens under
  its own name.

Encrypted in the install: 1,742 files: `.dds` 1,050, `.lua` 355, `.tga` 125, `.xml` 110, `.fx` 59, `.s2m` 33,
`.txt` 7 (the language tables), `.inc` 1, `.cfg` 1 (`menu.cfg`), `.png` 1 (`timedgoodbutton.png`) [known: header
bytes of every file]. Everything else is plain.

### 2.4 Identifiers that are hashes of names

| Where | Hash | Evidence |
|---|---|---|
| Container key: seed of the per-file key stream | CRC-32 (zlib) of the lower-case file name without folders | `docs/asset-formats.md` §1, S 006eeac0 |
| Container header `+0x08`, `+0x0c` | CRC-32 of the plaintext; CRC-32 of the 16-byte key | same |
| Section tags in maps, saves, `settings.cfg`, `data.cfg` | CRC-32 of the section name, plus its length; written, never checked | `docs/map-format.md` §2.2 |
| Lobby message field names | CRC-32 of the field name (network only) | [inferred] `LobbyMessage_HashFieldName` S 0048ef10 |

Not hashes: property ids (hex literals chosen by the designers, `docs/map-format.md` §2.4), UI control names,
effect names, file names in the index. No asset is addressed by a hash of its path.

### 2.5 Particle emitter objects (`.pfx`)

`ai::render::ParticleEmitter`, 200 bytes [known: `operator_new(200)` S 004e0950].

| Offset | Field | Meaning |
|---|---|---|
| `+0x0c` | name | the resolved path the emitter was loaded from (copy of the file object's path) |
| `+0x28` | startTime | f32 seconds |
| `+0x2c` / `+0x34` | particleCount / visibleCount | |
| `+0x3c`, `+0x58` | params type name, `ParticleEmitterParams *` | |
| `+0x5c`, `+0x78` | renderer type name, renderer object | |
| `+0x7c` | particle type name | |
| `+0x98` | pass index | i32, the last field of a version `0002` file |
| `+0x9c` | `ParticleCurveSet *` | 4 curves |
| `+0xa1` | looping | byte |
| `+0xa4` | bounds | 6 × f32 |

Offsets `+0x0c`, `+0x3c`..`+0x9c` [known] S 004f1150; `+0x28`, `+0x2c`, `+0x34`, `+0xa1`, `+0xa4` and the further
fields `+0x30` particle array, `+0x38` head of the depth-sorted list, `+0xc0` ever-visible flag [known]
S 004f0790, S 004f04b0; `+0xc4` attachment from the typed struct `ParticleEmitter` [inferred].

`ai::render::ParticleEmitterParams`, 0xcc bytes [known: `operator_new(0xcc)` S 004f0de0]:

| Offset | Field | Type | In file |
|---|---|---|---|
| `+0x04` | maxLoops | i32 | yes |
| `+0x08` / `+0x14` | pos / posVar | vec3 | yes |
| `+0x20` / `+0x2c` | vel / velVar | vec3 | yes |
| `+0x38` / `+0x3c` | size / sizeVar | f32 | yes |
| `+0x40` / `+0x44` | ttl / ttlVar | f32 seconds | yes |
| `+0x48` / `+0x4c` | spawn / spawnVar | f32 seconds | yes |
| `+0x50` / `+0x60` | color / colorVar | vec4 RGBA, 0..1 | yes |
| `+0x70` | randomSeed | the low 16 bits of the params vtable pointer S 007e53a0, 0x53a0 for every emitter (`particles.md` §2.3) | no |
| `+0x74` | random generator | `RandomGenerator` (own instance), seeded with randomSeed | no |
| `+0x7c` / `+0x88` | emitter position / rotation quaternion | | no |

Read widths and order [known] S 004f3250; offsets from the typed struct `ParticleEmitterParams`, which tile
exactly with those widths [inferred].

`ai::render::Particle`, 0x78 bytes [known: array stride S 004f0c10]: `+0x10` current position, `+0x1c` current
size, `+0x20` current colour, `+0x30` life `t`, `+0x34` current velocity, `+0x40` spawned byte, `+0x44` spawn
time, `+0x48` ttl, `+0x4c` start position, `+0x58` start velocity, `+0x64` start colour, `+0x74` start size
[known: reads and writes in `ApplyCurves` S 004f1960 and `ai::render::Particle::Update` S 004f16c0], `+0x04` index,
`+0x08` squared camera distance, `+0x0c` next in the sorted list [known] S 004f0c10, S 004f0790.

Enums:

| Enum | Values |
|---|---|
| Curve channel (index in the file) | 0 `velocity`, 1 `size`, 2 `color`, 3 `opacity` [known] table S 0087c588; use of each channel S 004f1960 |
| Curve type | 0 `constant`, 1 `linear`, 2 `cosine`, 3 `cubic`, 4 `hermite`, 5 `noiseLinear`, 6 `noiseCosine`; any other value builds a constant curve [known] S 004f2940, names S 007e525c.. |
| Renderer type name | `Default`, `Decal`, `GroundDecal` (object of 0x24 bytes), `TexAnim`, `GroundDecalAnimated` (0x28 bytes, with a frame count); compared with case [known] S 004f0f10 |
| Params type name, particle type name | only `Default` [known] S 004f0de0, S 004f0c10 |
| Property value type | 0 Int (4 bytes), 1 Float (4), 2 Vec2 (8), 3 Vec3 (12), 4 Vec4 (16); any other type reads nothing [known] S 004f1ce0, S 004f3800 |

### 2.6 Bitmap font objects (`.fnt`)

`ai::render::BitmapFont`, 0x2448 bytes [known: `operator_new(0x2448)` S 004941a0].

| Offset | Field | Evidence |
|---|---|---|
| `+0x0004` | 256 glyphs of 0x24 bytes, indexed by the character code | [inferred] glyph slot `this + 4 + id * 0x24`, `lineHeight` at `+0x2404` |
| `+0x2404` | lineHeight (i32) | [known] S 004e2770 |
| `+0x2408` | base (i32) | [known] S 004e2770 |
| `+0x2410` / `+0x2414` | 1 / scaleW, 1 / scaleH (f32) | [known] S 004e2770 |
| — | textureIndex: index into the shared font texture table | [known] S 004e36b0 |

Glyph fields (all i32, plus a `valid` byte): `x`, `y`, `width`, `height`, `xOffset`, `yOffset`, `xAdvance`
[known] S 004e28b0.

### 2.7 In-game avatar objects (`.npc`, `.avo`)

`InGameAvatarData` [known] S 0068b850: `+0x1c` type name string; `pAnimObject` (`S2CE::CAnimatedObject`, 0x4c
bytes); `partCount`; `pParts` (array of `S2CE::CMesh`, 100 bytes each); `ppPartTextures`; `pPartColorData`
(`partCount` × 0x400 bytes); `idleAnimHandle` (set only when the file names an animation; [inferred] −1
otherwise, from the constructor, not read). The record is 0x54 bytes (`operator_new(0x54)` S 0068bf30).

### 2.8 UI objects built from layout XML

| Class | Role | Evidence |
|---|---|---|
| `nUi::XMLHandler` | `LoadFromFile(fileName)` opens the file, parses it and calls the handler's virtual `BuildFromXml(doc, &rootContext)` with a null context; returns false when the file cannot be opened or parsed | [known] S 00491ac0 |
| `nUi::Configurable` | base of everything that loads from XML; holds the list of `{doc, node}` sources pushed while a template is applied (`+4`) | [known] S 004ab6f0, S 004ab9f0 |
| `nUi::Object` | a control; children, deployment, tip, focus | [inferred] S 004a76c0 |
| `nUi::Deployment` | position, offset, size, dock (`+0x6c`), alignX (`+0x64`), alignY (`+0x68`) | [known] S 004bcb80; offsets from the typed struct `Deployment` (0x70 bytes) [inferred] |
| `nUi::Position` | x, y as `{f32 value, byte isRelative}` pairs (`+4`/`+8`, `+0xc`/`+0x10`) | [known] S 004aae00; offsets from the typed struct [inferred] |
| `nUi::Shape`, `nUi::Text`, `nUi::Tip`, `nUi::Focus`, `nUi::Texture` | the visual parts of a control | S 004aa700, S 004b46d0, S 004b5d80, S 004c1be0, S 004c4230 |

Deployment enums [known: value strings S 004bcb80; inferred: the numbers, from the typed enums
`EDeploymentDock`, `EDeploymentAlignX`, `EDeploymentAlignY`]: `anchor` none 0, top 1, right 2, bottom 3, left 4,
center 5; `alignx` none 0, left 1, center 2, right 3; `aligny` none 0, top 1, center 2, bottom 3. Text `align`:
left 4, center 8, right 0x10 [known] S 004b46d0. Tip `align`: topleft 0, topright 1, bottomright 2,
bottomleft 3 [known] S 004b5d80.

Control kinds created by `nUi::Factory::CreateObject` S 004c28a0 [known: switch cases, allocation sizes]:

| Kind | Class | Kind | Class |
|---|---|---|---|
| 0x00 | Item | 0x13 | ComboBoxNew |
| 0x01 | Slider | 0x14 | DropDownMenu |
| 0x02 | Slider2 | 0x16 | ListBox2 |
| 0x03 | StackedSlider | 0x18 | TextBlock |
| 0x04 | SliderEx | 0x19 | Chart |
| 0x05 | Grabber | 0x1b | TextScroller |
| 0x06 | Edit | 0x1c | ChatSystem |
| 0x07 | EditEx | 0x1f | Scroller |
| 0x08 | Icon | 0x20 | ShapedObject |
| 0x09 | Label | 0x21 | plain `nUi::Object` |
| 0x0a, 0x0b | Button | 0x22 | ProgressBar |
| 0x0c | PictureButton | 0x24 | Graph |
| 0x0d | OverlayButton | 0x25 | TabControl |
| 0x0e | Picture | 0x26 | InventoryButton |
| 0x0f | AlphaFanPicture | 0x11 | Bar |
| 0x12 | ComboBox | | |

Kinds 0x10, 0x15, 0x17, 0x1a, 0x1d, 0x1e, 0x23 and above 0x26 create nothing (logged). Kinds 0x0a and 0x0b
(`Button`, `ButtonEx`) build the same object: both cases allocate 0x468 bytes, call `nUi::Button::ctor`
S 004b0e90 with the kind value **10** and then the same `nUi::Button::CreateUnnamed` S 004c2110 call, so a
`ButtonEx` element becomes a `Button` whose stored kind is 10 [known] S 004c28a0 (cases 10 and 0xb).

Type names of the kinds: the table of 39 strings at S 0087b810 (filled by the static initialiser S 007bf5f0),
whose index is the kind [known]: 0 `Item`, 1 `Slider`, 2 `Slider2`, 3 `StackedSlider`, 4 `SliderEx`,
5 `Grabber`, 6 `Edit`, 7 `EditEx`, 8 `Icon`, 9 `Label`, 0x0a `Button`, 0x0b `ButtonEx`, 0x0c `PictureButton`,
0x0d `OverlayButton`, 0x0e `Picture`, 0x0f `AlphaFanPicture`, 0x10 `Desktop`, 0x11 `Bar`, 0x12 `ComboBox`,
0x13 `ComboBoxNew`, 0x14 `DropDownMenu`, 0x15 `Listbox`, 0x16 `ListBox2`, 0x17 `Dialog`, 0x18 `TextBlock`,
0x19 `Chart`, 0x1a `Video`, 0x1b `TextScroller`, 0x1c `ChatSystem`, 0x1d `Table`, 0x1e `Serverlist`,
0x1f `Scroller`, 0x20 `ShapedObject`, 0x21 `Container`, 0x22 `ProgressBar`, 0x23 `Root`, 0x24 `Graph`,
0x25 `TabControl`, 0x26 `InventoryButton`. `Desktop`, `Listbox`, `Dialog`, `Video`, `Table`, `Serverlist` and
`Root` are therefore known names that the factory cannot create.

## 3. Rules and algorithms

### 3.1 How a file is found

**Index build** [known]: `CApplicationEx::Initialize` S 004075d0 calls
`FileScanHolder::ScanDirectory` S 006e3ca0 once with `data\`. `FileScan::ScanDirectory` S 006ef440 enumerates
`<dir>\*.*`; `ai::file::FileScan::ProcessEntry` S 006f1330 skips `.` and `..`, recurses into directories
(`HandleSubdirectory` S 006f0630, unless `ShouldSkipSubdirectory` S 006f0200 vetoes; that test compares path
components with those of the stored root, which is empty at start-up, so nothing is skipped [inferred]) and
enters every file (§2.2). The index is never rebuilt: a file that appears below `data\` later is not found by name.

**Opening a file** (`NBase::File::Open` S 006e6a30, `NBase::gReadFileData` S 006e6d40) [known]:

1. If the global base-directory string is not empty and the path contains neither `:` nor `\\`, the base
   directory is put in front.
2. The result goes through `FileScanHolder::ResolvePath` S 006e3fd0:
   - empty path: unchanged;
   - path ending in `\` or `/` (a directory): looked up, ignoring case, under `data\game\` and `data\lobby\`;
     if exactly one root has it, that directory is the result; if both or neither have it the output string
     is left as it was;
   - path containing `:` (absolute): copied unchanged;
   - anything else: `FileScan::ResolvePath` S 006ef8a0.
3. `FileScan::ResolvePath` [known]: forward slashes become backslashes, the path is lower-cased, the part after
   the last `\` is the file name. The name is looked up in the index.
   - one directory holds that name: the result is `Path_GetDataRelative(directory) + name`, i.e. the
     lower-cased path from the first occurrence of `data` on (S 006ef160). **The folders written in the request
     are ignored.**
   - several directories hold it and the request contains a `\`: `PickCandidateByParentDir` S 006ef680 returns
     the first candidate (in scan order) whose last folder component occurs as a substring anywhere in the
     lower-cased request; no candidate: empty result. Only the last component is tried; the compared text
     is the folder name with its trailing `\` (directories are stored ending in `\`, S 006ef440, S 006f0630;
     `Path_GetTailComponents` S 006ef2d0 with depth 1), lower-cased.
   - several directories hold it and the request is a bare file name: empty result.
   - name not in the index: empty result, so the open fails.
4. `CreateFileA`: mode 0 read (`GENERIC_READ`, share read|write, `OPEN_EXISTING`), 1 write (`GENERIC_WRITE`,
   `CREATE_ALWAYS`), 2 append (`GENERIC_WRITE`, then seek to the end). Write and append opens pass through
   steps 1 to 3 as well. `gReadFileData` logs `Can't open file: %s` when the open fails and returns no buffer
   for an empty file or a short read.

Consequences:
- `[data]` is not substituted anywhere in this path: a request `[data]\gfx\x.dds` is answered by the index entry
  `x.dds`, wherever below `data\` it lies [known from steps 2–3].
- A file name must be unique below `data\`, or its parent folder name must appear in every request. The install
  has 55 names that occur more than once, e.g. `color_slots.xml` (`game\character`, `lobby\config`),
  `door_open.kex`, `hammer_01.wav` [known: file listing].
- Files of the user folder are opened by absolute path and bypass the index.

**Listing files** [known: `[data]` test, two listing calls; details of S 006e4310 inferred from its summary]:
`FileScanHolder::FindFilesInDataPath` S 006e4c10 cuts a leading `[data]` off a directory, resolves the rest
under both roots and lists each root that has it with `FindFirstFileA` / `FindNextFileA`
(`FindFilesInDirectory` S 006e4310); a directory not starting with `[` is listed as given;
`Fs_FindFilesInDataPathRecursive` S 006e68d0 and `FindFilesByPattern`
S 006e4f00 are its front ends. Used for map lists, save lists, `*.pfx`, the shader folder and the build checksum.
Listings read the disk, not the index.

**Named resources of the UI** (`ai::ui::ResourcePath::ctor` S 004bdc60) [known]:

| Kind | Path built from a bare name |
|---|---|
| Gfx | `[data]\gfx\` + name (prefix left out when the name contains `:`), `.dds` appended when the name has no `.` |
| Font | `[data]\language\<lang>\fonts\` + name (`Localization::BuildLanguagePath` S 004955a0) |
| Sound | `[data]\sound\` + name + `.wav` |
| Free-game map preview | `[data]\maps\freeGameMaps\` + name + `.bmp`; if that file does not exist, `<user>\maps\<name>.bmp`; if that does not exist either, `<user>\mp_saves\<name>.mps.bmp` |

**Model files**: data names `.gr2`; the loaders rewrite the extension to `.KEX` (`docs/asset-formats.md` §2).

### 3.2 Readers by file type

| Type | Reader | Container |
|---|---|---|
| `.xml` | `ai::xml::XmlDoc::LoadFromFile` S 006e8210 (expat, `expat.dll`), usually through `nUi::XMLHandler::LoadFromFile` S 00491ac0 | required [known] |
| `.lua`, `menu.cfg` | `File_ReadAndDecrypt` S 006e7770, then the Lua 5.0 loader (`docs/lua-surface.md` §2.2) | required [inferred: caller list of S 006e7770] |
| `.dds`, `.tga`, `.png` textures | `S2CE::CTexture::CreateFromFile` S 004e80d0: path lower-cased; a path containing `.bmp` is read raw (`gReadFileData`), every other path through the container reader; the image is then created by D3DX from memory [inferred from the summary] | required, except `.bmp` [known: the `.bmp` test selects between the two readers]. A texture name that merely contains `.bmp` is read raw too |
| `.bmp` | same function, raw | plain |
| cursor images | `HwCursorSlot::LoadFromFile` S 004d4b70, `CGraphicDevice::SetHWCursor` S 004d6b50 (`D3DXCreateTextureFromFileInMemoryEx`) | required [inferred: both call S 006e7770] |
| `.fx`, `shared.inc` | `S2CE::CShaderProgram::CreateFromFile` S 004ec060 (§3.4) | required [known: S 004ebad0 and the include handler S 004ec4a0 call S 006e7770] |
| language `.txt` | `ai::ui::Localization::LoadTextFile` S 004966d0 | required [inferred: calls S 006e7770] |
| `.KEX` | `KFile::Load` S 0072b820 | plain |
| `.pfx` | `ParticleEmitter::Load` S 004f1150 | plain [known: `NBase::File::Read`] |
| `.npc`, `.avo` | `ai::render::InGameAvatarData::LoadFromFile` S 0068b850 | plain [known] |
| `.fnt` | `BitmapFont::LoadFromFnt` S 004e3860 | plain [known: `NBase::File::Open` + line buffer] |
| `.ogg`, `.wav` | `ai::audio::SoundManager::LoadSound` S 005c7250, `PlayOneShotFile` S 005c7510 (FMOD 3, `fmod.dll`) | plain |
| `.ini` | Win32 `GetPrivateProfile*` | plain |
| `.s2m`, `.aav`, `.sav` | `NCore::FileStreamCrypt::Open` S 007807f0 | required (`docs/sim/save-format.md` §3) |
| `settings.cfg`, `data.cfg`, `.info`, `.usermapinfo`, `copypaste.dat` | `NCore::FileStream::Open` S 0057d140 | plain |
| lobby `.txt` (`ItemsClient`, `itemicons`, `QuickEmotes`) | text line readers S 0048bfd0, S 00430ae0, S 00436bc0 | plain |

### 3.3 `.pfx` particle effect

One file = one emitter. Little-endian, no padding. `str` = `u32 length` + bytes, no terminator
(`NBase::File::ReadString` S 006e6960; the reader copies into a 260-byte stack buffer without a length check, so
a string must stay below 260 bytes; the string kept ends at the first zero byte).

Layout (`ParticleEmitter::Load` S 004f1150) [known]; all 64 files of the install parse to exactly their last byte
with it:

```
str  version                 "0002" in all 64 files
str  paramsType              "Default"
-- ParticleEmitterParams (S 004f3250), 108 bytes
i32  maxLoops                0 = endless; install: 0 (44 files), 1 (18), 2, 5
f32  pos[3], posVar[3]       spawn position and half range, emitter space
f32  vel[3], velVar[3]       start velocity and half range, units per second
f32  size, sizeVar
f32  ttl, ttlVar             lifetime, seconds
f32  spawn, spawnVar         spawn interval between particles, seconds
f32  color[4], colorVar[4]   RGBA 0..1
-- renderer
str  rendererType            Default | Decal | TexAnim | GroundDecal | GroundDecalAnimated
                             install: Decal (49 files), TexAnim (12), GroundDecal (2), GroundDecalAnimated (1)
f32  texMin[2], texMax[2]    UV rectangle in the particle atlas (S 004f39a0)
i32  numFrames               only for TexAnim and GroundDecalAnimated (S 004f3a60)
-- particles
i32  particleCount
str  particleType            "Default"
-- 4 curves, channel order velocity, size, color, opacity (S 004f2430)
4 x { i32 curveType; properties of that type }
-- only when version == "0002"
i32  passIndex               else 0
```

Curve properties, in file order (constructors S 004f1d60..004f2720) [known]:

| Type | Properties | Defaults |
|---|---|---|
| 0 constant | f32 `constantValue` | 1 |
| 1 linear, 2 cosine | f32 `startValue`, `endValue` | 1, 1 |
| 3 cubic | f32 `startValue`, `startSlope`, `endValue`, `endSlope` | 1, 1, 1, 1 |
| 4 hermite | f32 `startValue`, `startSlope`, `endValue`, `endSlope`, `tension`, `bias` | 1, 1, 1, 1, 0, 0 |
| 5 noiseLinear, 6 noiseCosine | i32 `offset`, f32 `phase`, `scale`, `bias` | 0, 1, 1, 0 |

Fix-up after the params are read [known] S 004f3250: if `ttl − ttlVar <= 0`, `ttlVar = max(ttl − 0.1, 0)`.

An unknown renderer, params or particle type name leaves that object null, and the loader uses each of them
right after creating it without a test (the params' and the renderer's load call, the spawn loop over the
particle array), so such a file crashes the game [known] S 004f0f10, S 004f0de0, S 004f0c10, S 004f1150.

Load sequence [known] S 004e0950, S 004f1150, S 004f0c10, S 004f1820: `ParticleManager::LoadEmitterFile` opens
the file (failure: returns null, nothing is created), constructs the emitter, calls `Restart` with the manager's
current time (no particles exist yet, so this only stores the start time) and then `Load`. Creating the particle
array spawns particle `n` with base spawn time `(n + 1) · spawn`. The last step of `Load` then resets every
particle with the params: start position, velocity, colour and ttl are drawn again, and spawn time, start size
and the spawned byte are set to 0. The staggered spawn times therefore exist only after a later `Restart`.

**Curve evaluation.** A curve multiplies a value `v` by a factor of the particle's life `t` in 0..1
(`ParticleCurveSet::Evaluate` S 004f1bf0 calls the curve once per component) [known]:

| Type | Factor |
|---|---|
| constant | `constantValue` (S 004f1db0) |
| linear | `startValue + (endValue − startValue) · t` (S 004f1e60, S 004f1e70) |
| cosine | `startValue + (endValue − startValue) · (1 − cos(π·t)) / 2`, cosine from a lookup table (S 004f1f40) |
| cubic | `p0 + c1·t + c2·t² + c3·t³` with `p0..p3` = the four properties in file order, `c3 = p3 − p2 − p1 + p0`, `c2 = p1 − p0 − c3`, `c1 = p2 − p1` (S 004f20a0, S 004f20e0) |
| hermite | `p0·(2t³ − 3t² + 1) + m0·(t³ − 2t² + t) + m1·(t³ − t²) + p2·(3t² − 2t³)` with `k = (1 − tension)/2`, `m0 = k·(1 + bias)·(p0 − p1) + k·(1 − bias)·(p3 − p0)`, `m1 = k·(1 + bias)·(p3 − p0) + k·(1 − bias)·(p2 − p3)` (S 004f22c0, S 004f2330) |
| noiseLinear / noiseCosine | `noise·scale + bias` with `x = phase · t`, `i = trunc(x)`, `f = x − i`, `noise = (1 − w)·L(i) + w·L(i + 1)`; `w = f` (linear) or `w = (1 − cos(π·f)) / 2` (cosine, library cosine); lattice value `L(i)`: `n = (i + offset)·0x3a; n ^= n << 13; 1 − ((n·(n·n·0x3d73 + 0xc0ae5) + 0x208dd0d) & 0x7ffffff) · 2⁻³⁰`, 32-bit wrapping integer arithmetic (S 004f2620, S 004f2830) |

Note the cubic and hermite curves use the property named `startSlope` as a value (`p1`) and `endSlope` as a
value (`p3`); the names are the file's, the arithmetic is the code's. The start/end differences and the cubic
and hermite coefficients are computed once after load (`Prepare`, S 004f1e60, S 004f20a0, S 004f22c0).
No file of the install uses types 2, 5 or 6.

Curve types in the install: velocity 0/1/3; size 0/1/3/4; color 0/1; opacity 0/1/3/4.

**Per-particle state** (`Particle::ApplyCurves` S 004f1960) [known]: velocity = start velocity × curve 0 (3
components); size = start size × curve 1; RGB = start colour × curve 2; alpha = start alpha × curve 3;
position = start position + velocity · t · ttl (the curved velocity of this instant times the whole age, not
an integral).

**Spawning** [known]: `ParticleEmitter::Restart` S 004f04b0 stores the start time, clears the sorted list,
resets every particle (zero position and velocity, white colour, ttl 0) and spawns particle `n` with base spawn
time `(n + 1) · spawn`; spawn times are relative to the emitter's start time (the update passes
`time − startTime`, S 004f0790). `Particle::Spawn` S 004f1660 draws, in this order: ttl, spawn delay (added to
the base time), start position, velocity, colour, size, and sets the spawned byte. Each draw is
`base + var · (2r − 1)` per component with `r` uniform in 0..1 from the params' own generator (one `r` per
component, in component order); ttl is clamped to `>= 0.1`, the spawn delay to `>= 0`, size, velocity and
colour are not clamped [known] S 004f3170, S 004f31c0, S 004f3210, S 004f3410, S 004f34b0. The spawn position
is rotated by the emitter's quaternion and moved by its position [known] S 004f36f0. [inferred] the mapping of
the six draws to those functions (called through the params' virtual slots `+0x10`..`+0x24`, vtable
S 007e53a0 not read).

**Update** (`ai::render::Particle::Update` S 004f16c0, once per particle and frame from `ParticleEmitter::Update` S 004f0790)
[known: disassembly]. `age = elapsed − spawnTime`; the function returns whether the particle is visible.

1. `age < 0` (not born): on a non-looping emitter with `age > −ttl`, `spawnTime += ttl`. In every case start
   position and velocity are drawn again (two draws from the generator per frame while unborn). Invisible.
2. `loops = trunc(age / ttl)`. With `maxLoops > 0`: if `trunc(spawnTime / ttl) + loops >= maxLoops`, invisible,
   nothing changes.
3. `loops >= 1` on a non-looping emitter: the spawned byte is cleared and the start position drawn again.
   Invisible.
4. `loops >= 1` on a looping emitter: start position, velocity and colour are drawn again (ttl and size are
   kept). If the spawned byte is 0: it is set, `spawnTime += (loops + 1) · ttl`, the start position is drawn
   once more, invisible this frame. Otherwise `spawnTime += loops · ttl` and step 5 follows.
5. `t = age / ttl − loops` (with the `age` of step 1), stored as the particle's life; the curves are applied
   (virtual slot `+4` of the particle, `ApplyCurves`). Visible.

"Looping" is the emitter byte `+0xa1` (0 after construction S 004f0940; not in the file). By steps 1, 3 and 4
it acts as an "emitting" switch: while it is 0, unborn particles keep being pushed back and expired ones are
retired, while particles in flight finish their life [inferred from the branches]. [TODO] not established: who
sets it (writers of `ParticleEmitter +0xa1`).

The emitter update skips everything when params, renderer or particle array is missing; it starts the bounds
at the emitter position, grows them by each visible particle's position ± half its size, counts the visible
particles and links them into a list ordered by descending squared distance to the camera [known] S 004f0790.

**Rendering** [known unless tagged]: one atlas for all effects, `[data]\gfx\particles_texture.tga`, effect
`particle_shader.fx` (`ai::render::ParticleManager::InitResources` S 004e0ad0). `passIndex` selects the pass of that effect
(`RenderEmitter` S 004e0280: effect call with `emitter+0x98`). Passes of technique `Default` in file order
[known: `particle_shader.fx`]: 0 `FlatDecal`, 1 `Spherical`, 2 `VolumeSphere`, 3 `FlatDecalAdditive` (source and
destination blend `One`), 4 `FlatNormal`, 5 `FlatDecalAlphaTest`; passes 0, 1, 2, 4 blend `SrcAlpha` /
`InvSrcAlpha`; no pass writes depth. The install uses 0 (8 files), 1 (6), 2 (16), 3 (34). Particles are drawn as
quads, back to front by squared camera distance [known for the order] S 004f0790; the vertex count per
particle comes from the renderer (virtual slot `+0x14`) [inferred: 6, two triangles, from the summary of
S 004f3b80].
[TODO] not established: which vertex builder each renderer type uses (camera-facing S 004f3b80, direction-aligned
S 004f43d0, flip-book S 004f3fc0, S 004f4860) and how the flip-book frame is chosen; settled by reading the five
renderer vtables at S 007e5420..007e5530.

**Naming** [inferred]: `EffectScriptMgr::ScanEffectNames` S 00686af0 lists `[data]\scripts\effects\*.pfx`; the
lower-cased base names form a table whose index is the effect id. `LoadEffectByName` S 00685bb0 lower-cases a
name, checks the table and loads `[data]\scripts\effects\<name>.pfx`. Effects are named by `buildings.xml`
(`Particle name=`, `PFX name=`), `settler_animations.xml`, `effectMovies.xml` (`particles=`), `projectiles.xml`
(`flightPFX`, `impactPFX`), spawn properties (`sp_setParticleName` S 0054a760) and map scripts.

### 3.4 `.fx` shaders

Direct3D 9 effect source (HLSL with techniques and passes), text, CR LF, each file starting with a
`#line 2 "<name>"` directive [known: file contents]. 42 game effects and `shared.inc` in
`data\game\gfx\fx_20\`, 17 lobby effects in `data\lobby\gfx\fx_20\`.

Loading (`S2CE::CShaderProgram::CreateFromFile` S 004ec060) [known: S 004ec060, S 004ebad0, S 004eb8f0,
S 004eac20, unless tagged]:

1. Source path = shader directory + file name; the directory string is `[data]\gfx\fx_20\` (S 007e4d38)
   [inferred: that string is the content of the directory global].
2. `GetCompiledEffect` S 004ebad0: the cache file is used when no recompile is forced, it exists and the
   source's write time is older than the cache's; otherwise the source is read through the container reader
   and compiled with `D3DXCreateEffectCompiler` (one optional define, an include handler that also reads
   through the container reader, S 004ec4a0) and the binary is written to the cache. Cache name:
   `<Local AppData>\SAdK\<source file name><shader profile name><define name>v21`.
3. The cache file is read back raw (`gReadFileData`) and passed to `CreateEffectInterface` S 004eac20:
   `D3DXCreateEffect` from the binary with a shared effect pool; a technique is then looked up, validated and
   made current [inferred: the two effect calls are `FindNextValidTechnique` and `ValidateTechnique` by their
   vtable offsets 0xf4, 0xe8].
4. A compile error is logged and opens an Abort / Retry / Ignore box: Retry compiles again, Abort ends the
   process (`exit(1)`), Ignore goes on with the cache path as it is.

Effects carry render state in their passes (blend, depth, cull, alpha test) as well as shader code. Techniques
seen in `particle_shader.fx`: `Default` and `ffp` (fixed function).

### 3.5 `.npc` and `.avo` avatar files

Same layout for both (`ai::render::InGameAvatarData::LoadFromFile` S 0068b850) [known]; all 32 `.npc` files parse to their last
byte:

```
str  typeName        "male" (27 files), "female" (3), "MacDoyleJr", "MacGabhan"
str  modelFile       skeleton, e.g. "[data]/avatars/model.KEX"      -> CAnimatedObject::Load
u32  partCount       1 in 31 files, 2 in one
partCount x {
  str  meshFile      e.g. "[data]/avatars/Kostas.KEX"               -> CMesh::Load
  str  textureFile   e.g. "[data]/avatars/Kostas_colorindices_luminance.dds"
  u8   palette[0x400]  256 entries of 4 bytes
}
str  idleAnimation   e.g. "[data]/avatars/male_idle01.KEX"; empty = none (no install file leaves it empty)
```

- Path: `<name>.npc` (found through the index, install folder `data\game\npc\`) or
  `<My Documents>\SAdK\users\<name>.avo` (`InGameAvatar::LoadAvatar` S 0068bf30) [known: format strings
  `%s.npc`, `%s\%s.avo`]. A file that cannot be opened yields −1 without a message [known]. The record
  (0x54 bytes) is appended to the avatar table and its index returned; each part's palette starts from a
  default fill (`ai::gfx::Palette256::ctor`) before the 0x400 bytes are read [known] S 0068b850.
- Writer: `Lobby::CGfxObjAvatar::SaveAvatarFile` S 00506a40 / `AvatarBodyParts::WriteAvoFile` S 004fd110 write
  the same layout with the idle animation `Stand` [inferred from the summaries].
- `typeName` matches the lobby's animation graphs (`<typeName>_animation_graph.xml` in `data\lobby\config`)
  [inferred from the names].
- Palette: the fourth byte of every entry is 0 or 255 in the install [known: data]. [TODO] not established: the
  byte order of an entry (R, G, B, x or B, G, R, x) and how the texture's channels index the palette (the texture
  is post-processed by `Texture_DecrementIndexChannel`); settled by reading that function and `ingame_avatar.fx`.
- File names inside may end in `.gr2`; the loaders rewrite them to `.KEX` (two install files name their idle
  animation so: `female_idle01.gr2`, `MacDoyleJr_idle_01.gr2`; all 33 mesh names end in `.KEX`).

### 3.6 `.fnt` bitmap fonts

AngelCode BMFont **text** format, one tag per line, CR LF, `key=value` tokens. 15 fonts in
`data\game\language\de\fonts\`, each with one page texture `<name>_00.tga` (encrypted container).

What the game reads (`BitmapFont::LoadFromFnt` S 004e3860) [known]:

| Line | Keys used | Effect |
|---|---|---|
| `info` | `padding=up,right,down,left`, `spacing=x,y` | kept for the `char` lines of the same file; default 0 |
| `common` | `lineHeight`, `base`, `scaleW`, `scaleH` (`pages` parsed, unused) | metrics; `1/scaleW`, `1/scaleH`; then the page texture is loaded |
| `char` | second token must start with `id`; `x`, `y`, `width`, `height`, `xoffset`, `yoffset`, `xadvance` (`page` parsed, unused) | glyph `id` is filled (`ParseCharLine` S 004e28b0) |
| `page`, `chars`, `kernings`, `kerning` | — | ignored: no kerning, the page file name is never read |

Glyph arithmetic with `pad[0..3]` = up, right, down, left and `spacing[0]` = x [known] S 004e28b0:

```
x        = file.x        - pad[3]
y        = file.y        - pad[0]
width    = file.width    + pad[2] + pad[0]
height   = file.height   + pad[3] + pad[1]
xOffset  = file.xoffset  - pad[3]
yOffset  = file.yoffset  - pad[0]
xAdvance = file.xadvance + spacing[0]
```

- The padded values are what the game draws [known]: `ParseCommonLine` S 004e2770 stores `1/scaleW` and
  `1/scaleH`, and `BuildGlyphQuads` S 004e2c60 draws the whole grown rectangle with texture coordinates
  `x / scaleW`, `y / scaleH`. So a converter that writes the arithmetic above into a standard BMFont file pads
  once, as the game does (Subline_Garamond `n`: file x 126, width 12, xoffset −2 → drawn x 124, width 16,
  xoffset −4).
- Sampling [known] `gfx/fx_20/ui_shader.fx`, drawn by `UIRenderer::DrawGlyphQuads` S 004e1350: the passes
  `RenderFont` and `RenderFontDepth` use `addressU/V = Wrap` and linear filtering; `RenderFontDepth` adds an
  alpha test (`Greater`, reference 7). A padded rectangle that reaches past the page's edge therefore reads the
  opposite edge: Subline_Garamond's `e` lies at x 0, its rectangle starts at x −2 and samples columns 254–255,
  which are transparent. 430 glyphs of 13 fonts reach past an edge; `mini` and `title` have none [known, data].
  A reader that clamps instead of wrapping repeats the edge texels and paints them beside the glyph; a
  conversion has to add a border holding what the wrap reads, or draw fonts with repeat addressing.
- Page formats [known, data]: `title_00.tga` is the only 24-bit page (no alpha); the other 14 pages,
  `Kopie von system_00.tga` among them, are 32-bit.
- Glyph shapes [known, data]: `Body_Arial` and `small_no_alias_white` share their glyphs (Arial at about an
  11 px em with a 1 px edge and a shadow; gold in `Body_Arial`, grey in `small_no_alias_white`). `Mini_Silk` is
  a 5 × 7 pixel font (face `fixed_v01`) with `xadvance=6` for every glyph but the space (4), so 7 px with the
  file's `spacing=1,1`.
- Page texture: `<base path>_00.tga`, lower-cased, through the shared font texture table
  (`BitmapFont::LoadPageTexture` S 004e36b0) [known]. `Body_Arial.fnt` names `test_00.tga` on its `page` line;
  the game loads `Body_Arial_00.tga` all the same.
- The glyph table has 256 slots indexed by `id` with no range check [inferred: no test before
  `glyphs + id`]. The install's ids are 32..255 (Windows-1252 code points).
- The load fails (returns false) when the file cannot be opened or holds no `char` line.
- Fonts are found by lower-cased name through `UiResourceManager::LoadFont` S 004941a0 (kind Font, §3.1) and
  cached; the load result is not checked [inferred].
- Font names in the install: `Body_Arial`, `Chapter_Garamond`, `Gamertags_Garamond`, `Head_Garamond`,
  `Subline_Garamond`, `Mini_Silk`, `mini`, `title`, `editor`, `system`, `dark_system`, `light_system`,
  `light_system_outlined`, `font_big_white`, `small_no_alias_white`.

### 3.7 `.lep` editor presets

Eight files in `data\game\Editor\LogicalEditor\Presets\` (95 to 206 bytes), plain. The client does not read
them: the image holds no string `.lep`, `LogicalEditor` or `Presets` [known: string search]. They belong to a
map-editor tool that is not part of the install [inferred].

Visible in the bytes [inferred from data only]: `u32 1` (version), `str name` (`u32` length + bytes, equal to the
file's base name), then a sequence of 32-bit values (small integers, occasional f32 and what look like property
ids, e.g. `0x7068dcd3`). [TODO] not established: the body's structure; it would need the editor's binary. A
remake does not need these files.

### 3.8 UI layout XML

54 files: `data\game\ui\layout\*.xml` (22) and `data\lobby\ui\layout\*.xml` (32), each an encrypted container
holding XML 1.0 (16 files declare the encoding `utf-8`, the others declare none; see §3.9 for text).

**Document model.** A file is a tree of elements. **An element's name is the name of the control or part it
configures**, chosen by the C++ class that loads the file, not a type name (the 54 files use 1,760 different
element names). Three kinds of element exist:

1. **Bound elements**: a screen class asks for a child by name (`Object::LoadChildFromXml` S 004a3ad0,
   `Configurable::LoadChildFromXml` S 004ab9f0, `LobbyMenu::ComponentBase::LoadFromXml` S 00462280) and loads
   one of its own member controls from it. The control's type is fixed in code.
2. **Created elements**: an element with a non-empty `controltype` attribute. After a control loaded its own
   attributes, `nUi::Factory::CreateChildrenFromXml` S 004c21d0 creates one control per such child element
   through the factory, marks it as owned by its parent and loads it by the element's name from the parent
   node (and once more from each template source the parent is being loaded from); elements without
   `controltype` and unknown type names are skipped [known] S 004c21d0. The created control is looked up by
   name, so sibling elements with `controltype` need different names [inferred].
3. **Part elements** with fixed names inside a control: `deployment`, `shape`, `background`, `text`, `tip`,
   `focus`, `description` and control-specific ones.

**Root element.** Its name is free; the handler receives the document and looks its children up by name
(`nUi::XMLHandler::LoadFromFile` S 00491ac0).

**`controltype` values**, compared without case [known: `__stricmp` S 004a0b00, S 0060c880]:

- menu factory (`nMenu::Factory::CreateObjectByName` S 0060c880): `mainmenubutton`, `timedgoodbutton`,
  `goodbutton`, `sacrificebutton`, `clocksymbol`, `roundingamebutton`, `avatar`;
- everything else goes to `nUi::Factory::CreateObjectByName` S 004c2730, which looks the name up in the table
  of 39 names and creates the kind of that index (§2.8); a name not in the table is logged and creates
  nothing. Names used by the install (985 elements; `timedgoodbutton` is not among them): `label` (311),
  `picture` (288), `picturebutton` (119), `inventorybutton` (41), `button` (36), `comboboxnew`, `editex`,
  `mainmenubutton`, `slider2`, `sacrificebutton`, `overlaybutton`, `listbox2`, `goodbutton`, `dropdownmenu`,
  `textblock`, `avatar`, `container` (kind 0x21, a plain `nUi::Object`), `tabcontrol`, `roundingamebutton`,
  `sliderex`, `clocksymbol`, `shapedobject`, `scroller`, `progressbar`, `stackedslider`.

**Templates** (`nUi::Configurable::LoadFromXmlWithTemplate` S 004ab6f0, `LoadChildFromXml` S 004ab9f0) [known]:
an element with `template="name"` is loaded twice: first from the template element, then from itself, so its
own attributes win. The template is searched first among the root's children of `templates.xml`
(`data\game\ui\layout`, loaded on first use by `nUi_Templates_Load` S 004ab3e0 under its bare name); if it is
not there, the element's ancestors are walked upwards and the first one with a child element of exactly that
name (case-sensitive) supplies it. A template that is found nowhere is ignored. Templates nest (the template
element may carry `template` itself). While a template is applied, the element being loaded is kept on the
control's source list, and children created from the template are also loaded from those sources (above).

**Attributes of every control** (`nUi::Object::LoadFromXml` S 004a76c0) [known: attribute strings, value
types and order; the meaning of `clipping`, `intersectionType`, `forwardEvents`, `pointfiltering` is inferred
from the names]. Read in this order:

| Attribute | Meaning |
|---|---|
| `enabled`, `visible` | booleans |
| `clipping` | boolean: clip children |
| `intersectionType` | integer: hit-test mode |
| `name` | control name; without it the element name is taken, but only while the control has no name yet and is not being loaded from a template source |
| `data` | integer payload (stored sign-extended to 64 bits) |
| (deployment) | the control's deployment part loads itself (below) |
| `pos` | two integers, pixels, converted to relative coordinates |
| `description`, `focus` | sub-loaders of the tip and focus parts |
| `zorder` | integer; the parent's children are re-sorted when it changes |
| `debugColor` | four integers, each divided by 255 |
| `hotkey` | one character (its character code), or exactly two digits read as a decimal key code (e.g. `13`) |
| `forwardEvents`, `pointfiltering` | booleans |
| (events) | `nUi::Event::LoadFromXml` on the same element; [TODO] not established: its attributes (one function) |
| `transform` | 16 floats: local matrix |
| (children) | last step: `CreateChildrenFromXml` for the `controltype` children |

**`deployment`** (`nUi::Deployment::LoadFromXml` S 004bcb80): `pos`, `offset`, `size` (each two length tokens),
`anchor`, `alignx`, `aligny` (enum strings of §2.8, case-insensitive; an unknown value changes nothing) [known].
A length attribute must hold exactly two tokens or it is ignored (`nUi::Position::LoadFromXml` S 004aae00). A
token containing `%` is the number before it divided by 100, relative to the parent; a token with the suffix
`px`, or a bare number, is pixels (`nUi_ParseLengthValue` S 004aac10) [known].

**`shape` / `background`** (`nUi::Shape::LoadFromXml` S 004aa700) [known: attribute strings]: `texture` (a Gfx
resource name, §3.1), `mapping` (four numbers: the rectangle in the texture, pixels), `flipped`, `width`,
`height`, `color`, `disabledcolor` (four floats each, read as they are: not through the colour reader below),
`border` (one float for all four sides) or, without it, `bordertop` / `borderright` / `borderbottom` /
`borderleft` (border widths; [inferred] nine-slice), `stretch`, `mask` (a second Gfx texture) with
`maskUV0` / `maskUV1` (two floats each, read only when `mask` is present). Button-like controls add state
variants: `mapping_cursorover`, `mapping_pressed`, `mapping_cursoroverandpressed`, `mapping_marked`,
`texture_selected`, `texture_not_selected`, `texture_pressed`, `texture_marked`, `font_cursorover`, `type`,
`checkbutton` [known: present in the data; their loaders (`nUi::Button::LoadFromXml` S 004afed0,
`nUi::PictureButton::LoadFromXml` S 004b3a90) were not read].
`nUi::Shape` stores the four `mapping` numbers unchanged, and only when the attribute has exactly four numeric
tokens (`nUi_Xml_ReadFloat4Attr` S 004c1280) [known]; they read as `x y width height` in the data (e.g.
`0 432 40 40` beside `44 432 40 40`) [inferred]. The separate `nUi::Texture` part (attribute `name` = Gfx
texture) reads `mapping` as four integers `x0 y0 x1 y1` and stores `x0, y0, x1 − x0, y1 − y0`, or, without
`mapping`, takes the single attributes `u`, `v`, `w`, `h` [known] S 004c4230.
[TODO] not established: that the shape's drawing code treats the third and fourth number as a size; settled by
the reader of `Shape +0x18` in the shape's draw function.

**`text`** (`nUi::Text::LoadFromXml` S 004b46d0) [known]: `uppercase`, `lowercase` (booleans), `pos`, `offset`
(two integers each, pixels, converted to relative coordinates), `align` (`left`, `center`, `right`, without
case), `contenthidden`, `content` (a literal, or a localisation key when its first character is `!`), `font`
(font name, §3.6), `color` (four floats), `wrapSize` (two integers).

**`tip`** (`nUi::Tip::LoadFromXml` S 004b5d80) [known]: `description` (localised when it starts with `!`),
`data` (integer), `align` (`topleft`, `topright`, `bottomright`, `bottomleft`, without case), `hidden` (true
hides an open tip). **`focus`** (`nUi::Focus::LoadFromXml` S 004c1be0): `canReceiveFocus`.

**Colour reader** (`nUi_Xml_ReadColorAttr` S 004c1530) [known]: `r g b a` or `r g b` (alpha 1), each component
above 1.0 divided by 255; or one token `#RRGGBB` (alpha 1) / `#RRGGBBAA`, each byte divided by 255. Any other
token count leaves the value as it was. It is used by `nUi::Graph`, `nMenu::MiniMap` and `nMenu::IconConfig`
only; the `color` attributes of shapes and texts are plain four-float lists.

**Data files in the layout folder that are not control trees**:

| File | Root / elements | Reader |
|---|---|---|
| `cursors.xml` | §3.10 | `nUi::Cursor` |
| `campaigns.xml` | `Map` elements: `name`, `desc`, `filename`, `type`, `prerequisite0..2` | `nMenu::Campaigns::OnXmlLoaded` S 005e52a0, `nMenu::Map::LoadFromXml` S 005e3370 |
| `goodinfosets.xml` | `Set name= tribe=` with `Good name=` children | `nMenu::GoodSetsReader::OnXmlLoaded` S 0062a820 |
| `iconconfig.xml` | icon rectangles and colours | `nMenu::IconConfig::LoadFromXml` S 00611320 |
| `mapSymbols.xml` | `symbol texture= mapping= type= name= center= lifetime=` | `nMenu::MapSymbolDatas::LoadFromXml` S 005f5400 |
| `templates.xml` | shared templates (2,849 lines) | `nUi_Templates_Load` S 004ab3e0 |

Their element and attribute names are [known] from the data; the readers' handling of each attribute is [TODO]
(one function each, listed).

### 3.9 Localisation text

Seven encrypted files in `data\game\language\<lang>\` (`<lang>` = `de` in the install; set by `menu.cfg`,
`menu.setLanguage("de")`). Windows-1252 text, CR LF, one entry per line: `key<TAB>value`.

`Localization::LoadTextFile` S 004966d0 [known unless tagged]:

1. The file is read through `File_ReadAndDecrypt`. The loader tests for a missing buffer afterwards, but
   `gDecryptData` has already read the header of that buffer without a test, so a missing or empty file
   faults instead of being skipped [inferred from S 006e7770, S 006e6660].
2. Line ends: text with CR but no LF: every CR becomes LF; with both: every CR is removed.
3. Empty lines and lines whose first character is `;` or `#` are skipped, as are lines whose first two
   characters are `//` (the line's two-character prefix is compared with the literal `//`).
4. key = text before the first TAB; value = text after the last TAB. A line with an empty key is skipped. A
   line without TAB gives key = value = the whole line.
5. `Localization::SetText` S 004963a0: every two-character sequence `\n` in the value becomes a line feed; the
   entry replaces an existing one of the same key.

Load order (`Localization::LoadAllTextFiles` S 00496b80) [known: string order]: `briefings.txt`, `ui.txt`,
`credits.txt`, `lobby_ui.txt`, `lobby_items.txt`; later files win. `info.txt` and `dialogs.txt` are in the install
but the image holds no string naming them [known: string search], so they are not loaded.

Lookup (`Localization::GetText` S 00496070) [known]: empty key gives an empty string; a missing key is inserted
with itself as value and returned, so an untranslated key shows as its own text.

Conventions in the data [known: file contents]: most UI keys start with `!` (1,300 of the lines of `ui.txt`,
604 of `lobby_ui.txt`) and are written the same way in the layout XML (`content="!ABORT_BUTTON"`); briefing
keys are `B<map>_<scene>_<line>` with a companion `..._title` (664 lines); values may carry markup such as
`<hcenter>` (`lobby_ui.txt`) and speaker tags `[McDoyle:1]` (`briefings.txt`); credits keys are `cr000`,
`cr001`, ... and their values are empty or start with `#` or `%` as style marks.
[TODO] not established: the markup's grammar (text block and briefing renderers,
`nUi::TextBlock::LoadFromXml` S 004b7e90 and the rich text layout class `ai::render::RichTextLayout`, e.g.
`SetFont` S 004e3be0).

Sizes: `ui.txt` 1,769 lines, `briefings.txt` 1,562, `lobby_ui.txt` 608, `credits.txt` 400, `info.txt` 200,
`dialogs.txt` 23, `lobby_items.txt` 1.

Localised assets use the same folder: fonts (`fonts\`), `ui_s2logo.dds`, voice files `voices\<key>.ogg` (540
files, named after briefing keys, e.g. `B5_5_5.ogg`) through `Localization::BuildLanguagePath` S 004955a0.

### 3.10 Cursors and small settings files

**`cursors.xml`** (`nUi::Cursor::LoadFromXml` S 00493190, `nUi::StyleData::LoadCursorFromXml` S 00492d80)
[known: attribute strings and the two loops; the rest inferred from the summaries]: children `cursor0`,
`cursor1`, ... are read in order until one is missing; the index is the cursor id. Attributes: `hotSpot="x y"`
(two integers); a static cursor has `name` (image path, written with the `[data]\gfx\` prefix); an animated
one has `animated="true"`, `fps` (integer; frame time = 1 / fps) and `name0`, `name1`, ... read until one is
missing. The install defines 4 cursors: 0 and 2 main (`Mousecursors_MainCursor.tga`, hot spot 5 1), 1 clock (8
frames, 5 fps, hot spot 15 16), 3 build (`Mousecursors_BuildHouse.tga`, hot spot 5 1).

**`engine.ini`** (`data\game\settings`, plain; `S2CE::CGraphicDevice::Init` S 004da2a0, `GetPrivateProfileIntA`)
[known: keys and defaults]: section `[Engine]`: `vsync` (default 1), `refreshRate` (0), `useMeshCache` (1),
`hardwareCursor` (1; `docs/BINARY_PATCHES.md`); in the reference install all four take these defaults, because
the file's byte order mark hides `[Engine]` (next paragraph) [live, 2026-10-14]. **`engine.xml`** (encrypted, read by the same function when
it can be opened): attributes of the root element (its name is not tested; `Engine` in the install):
`pureDevice`, `specialDepthMap`, `lowresDepthMap`, `mixedDevice` (booleans), `multiSample` (integer),
`hwCursor` (cursor image path) and, only with `hwCursor`, `hotspot` (two integers) [known]. The install's file
also carries `hardwareCursor` and `vsync` attributes, which this function does not read, and has no
`mixedDevice`.

The reference install's `engine.ini` and `network.ini` start with a UTF-8 byte order mark (`EF BB BF`)
[known: file bytes]. The Win32 profile reader does not find a section whose header follows the mark directly
(`GetPrivateProfileIntA` called in the game process on test files) [live, 2026-10-14]. `engine.ini` has the mark
directly before its only section `[Engine]`, so every `[Engine]` key takes the code default, and edits to the file
have no effect until it is saved without the mark; in `network.ini` the first `[Basics]` section (`gamePort`
5478) is hidden and the effective value is 5479 = 0x1567, from a second `[Basics]` section further down or the
default [live, 2026-10-14]. A remake's reader should strip the mark. [TODO] not established: whether the retail
files carry the mark, or only this copy.

**`network.ini`** (plain; `NComm_NetworkConfig_LoadFromIni` S 0041ede0): sections `[Basics]` `gamePort`;
`[Broadcast]` `broadcastPort`, `broadcastTimeout`; `[Ping]` `pingFrequencyMenu`, `pingFrequencyGame`;
`[Reconnector]` `timeHostWaitForClients`, `timeClientWaits`, `timesClientRetries`, `timeClientWaitsFailed`;
`[Lobby]` `url`, `patchlevel`. Read again at every network start-up.

**`LobbySettings.ini`** (`data\lobby\config`, plain; the path is set up by `LobbyProfile::Init` S 00465dd0, the
keys are read on demand by `ai::lobby::LobbyProfile::GetLobbyServerHost` S 00466230, `LobbyProfile_GetLobbyServerPort`
S 00465450 and `ai::lobby::LobbyProfile::GetHallOfFameUrl` S 00465960) [known: key strings]: `[LobbyServer]` `Host`,
`Port`; `[LobbyClient]` `HallOfFameURL<n>` (default empty), `HallOfFameURL<n>_AppendPermID`,
`HallOfFameURL<n>_AppendCharname` (the install writes `n` = 0..2 and no `_AppendCharname` key).

**`menu.cfg`** (`data\game\scripts`, encrypted): a Lua 5.0 script run once in a temporary thread by
`nMenu::System::Initialize` S 005dda30. The install's file calls `menu.setLanguage`, `menu.setVideoVoiceStream`
and `menu.setPlayerColor(index, r, g, b)` for 8 players.

**Lobby text tables** (`data\lobby\config`, plain) [inferred from the summaries; examples from the data]:

| File | Line format | Reader |
|---|---|---|
| `ItemsClient.txt` | `#` comment lines; else exactly 9 `;`-separated tokens: id; name key; description key; int; int; int; mesh name; icon name; int (e.g. `2;"!LOBBY_ITEM_CROWN";...;4;1;1;"Crown";"CrownIcon";250`) | `ItemDatabase::LoadFromFile` S 0048bfd0 |
| `itemicons.txt` | exactly 6 tokens: icon name; texture name; four integers (e.g. `CrownIcon;ui_items;4;4;40;40`); `InvalidIcon` and `EmptyIcon` are required names | `ItemIconDB::LoadFromFile` S 00430ae0 |
| `QuickEmotes.txt` | `#` comments; else 3 `;`-separated tokens: label; tooltip; chat text (e.g. `!EMOTE_DANCE;!EMOTE_DANCE_TOOLTIP;"/dance"`) | `WorldScreen::LoadQuickEmotes` S 00436bc0 |

**Scene and world settings XML** (`data\game\settings`, `data\game\character`), all encrypted, all read per
match unless noted (`docs/data-loading.md` §2). Root, main elements and attributes [known: file contents]:

| File | Structure | Reader |
|---|---|---|
| `graphics.xml` | `Graphics`: `Settings`, `Shadows bias scale`, `PostEffects bloomScale focalScale focusSpeed minLuminance`, `Animations globalSpeed`, `Map scaling`, 8 `Transition texture`, 5 `Skydome name rotation texture`, 4 `WaterProperty` (colours, normal maps, opacity, reflection) | `S2CG::Scene::Init` S 006824c0 |
| `buildings.xml` | `Buildings lodBias lodScale colorMap numVariations`; 112 `Building name mesh frame enterDistance lodBias lodScale` with children `DoorOpen file`, `DoorClose file`, `Working file`, `Sound name start duration`, `Particle name slot offset start duration`, `PFX name link`, `Production` | `Scene::Init` |
| `animals.xml` | one element per animal (`Deer`, `Bear`, ...) `mesh model scale` with `Animations` / `Animation name filename` | `AnimalMgr::LoadAnimalTypes` S 0069be70 |
| `ships.xml` | `Ship tribe mesh model frame idle move sink scale`; `Freight mesh`, `Expedition mesh`, `Soldiers mesh` | `Scene::Init` |
| `items.xml` | `ItemDefinitions` / 55 `Item name mesh references`; `AnimatedItems`; `DonkeyItems`; `StackLayouts count distance` / `Layout good0..` | `Scene::Init` |
| `map_objects.xml` | 221 `LandscapeElement name mesh meshType shader blendMode numInstances offset rot scaleX/Y/Z priority alignOnWater shadowCast shadowReceive forceShadowPass` | `nGame::System::BuildScene` S 007842e0 |
| `terrain_static_data.xml` | `Patterns` / 114 `Pattern name alias type texture normal transition texScale nrmScale parallaxHeight specularIntensity specularPower blocking groundCover`; `GroundCover` / `Cover name density height bend opacity sliceCount` | `BuildScene` |
| `daytimes.xml` | 9 `Daytime hour background fog lightambient lightcolor lightelevation lightheading shadowIntensity skydome` | `CEnviromentMgr::LoadDaytimes` S 00684130 |
| `local_enviroment.xml` | `Enviroment` (defaults) and `XEnvSphere center innerRadius outerRadius ...` | `ai::render::MapEnvData::LoadDefaultsXml` S 006aec60 |
| `decals.xml` | 3 `Texture name` | `DecalRenderer::CreateResources` S 004df850 |
| `effectMovies.xml` | 7 `EffectMovie name` with `FX start duration link particles sound` | `ai::gfx::EffectScriptMgr::LoadEffectMovies` S 00686160 |
| `projectiles.xml` | 4 `Projectile name mesh rotation flightPFX impactPFX impactSound` | `ProjectileTable::LoadProjectilesXml` S 006a4440 |
| `flocks.xml` | `Flocks maxFlocks minSpawn maxSpawn swarmTimeout`; `Bird`, `Fish`, `Bug` with `Evade`, `Pack`, `MatchSpeed` | `SwarmMgr::LoadSettings` S 0069a9c0 |
| `settler_config.xml` | `Characters scale lod0Range.. goodOffset ...`; 98 `Character name mesh mesh1..3 color slotMap`; `Models` / `Model file`; `Donkey`; 47 `Animation name filename` | `CCharacterMgr::LoadFromXml` S 00695130 |
| `settler_animations.xml` | 179 `Animation name filename src tribes probability` with `Sound name start`, `Particle name start`; `RandomAnimations` | `CCharacterMgr::LoadAnimationSet` S 00692390 |
| `color_slots.xml` (character) | `SlotEnumeration` / 15 `Slot name`; `ColorRamps` / 41 `ColorRamp slot texture rows solid`; `ColorMaps` / 63 `ColorMap name` with 1,008 `Material index slot` | `CCharacterMgr` |

`daytimes.xml`: `CEnviromentMgr::LoadDaytimes` S 00684130 reads, per child of the root (element name not
tested): `hour` (integer), `background` (3 floats), `skydome` (integer), `lightelevation` (integer),
`lighteeading` (integer), `lightambient` (3 floats), `lightcolor` (3 floats), `fog` (2 floats),
`shadowIntensity` (float) [known]. The file writes `lightheading`, so the heading attribute is never found.
The loader stores the same temporary for elevation and heading, and `XmlDoc::GetAttrInt` S 006e7b20 leaves
its output untouched for a missing attribute, so every key's heading equals its elevation [known].
The values form the `DaytimeKey` record of 0x4c bytes (19 dwords) [known]: `i32 hour`,
`f32 background[3]` + `1.0`, `i32 skydome`, `i32 lightElevation`, `i32 lightHeading`, `f32 ambient[3]` +
`1.0`, `f32 lightColor[3]` + `1.0`, `f32 shadowIntensity`, `f32 fog[2]`.

The per-attribute semantics of these files belong to the rendering specifications; here they are inventory.

**Lobby data** (`data\lobby`, encrypted XML) [known: file contents; readers by name]:

| File | Structure | Reader |
|---|---|---|
| `scene\world1.xml`, `world2.xml` | `world` / `world_settings` / `setting file`; `world_scenes` / `scene file scene_id_offset` | `CLobby::LoadZoneTable` S 004f57f0 |
| `scene\scene*.xml` | `scene_file` / `obj name type pos orientation scene` (2,026 objects in `scene1.xml`) | lobby scene loader |
| `scene\scene*_settings.xml` | `setting scene ambient diffuse light_dir fog_color fog_start fog_end light_map light_map_object shadow_light_intensity` | lobby scene loader |
| `physic\*.xml` | PhysX NxuStream 2 XML (`NXUSTREAM2`, cooked triangle meshes as text) | `ai::physics::NxuXmlReader` |
| `config\lobbyobj.xml` | 110 `lobbyobj name gfxclass controllerclass` with `gfxparm`, `controllerparm` | lobby object factory |
| `config\materials.xml` | 48 `material name` / `lod default instanced pplighting shadow` / `pass name shader technique transparent_shader transparent_technique alpha_sorting` | `CGfxShaderMgr::LoadMaterials` S 0050c300 |
| `config\*_animation_graph.xml` | `anim name source emotes`, `trans from to blend`, `overlay`, `randoms minDelay maxDelay` / `random source probability` | `ai::anim::AnimGraph::ParseXml` S 0050fe30 |
| `config\bodyparts.xml`, `npc_bodyparts.xml` | `bodypartset name model` / e.g. `heads` / `head meshLod0..2 texture slotMap` | `AvatarBodyParts::LoadFromXml` S 004fd760 |
| `config\color_slots.xml`, `avatar_items.xml`, `pets.xml`, `emotes.xml`, `anim_selector.xml` | avatar colours, items (`Item name mesh`), pets, emotes, animation selection (`avatar itemid anim_idle anim_walk`, `npcindex`) | in file order: `AvatarColorSlots::LoadXml` S 0050d920, `AvatarItemList::ParseXml` S 004fc870, `LobbyPetMgr_LoadPetsXml` S 004fe940, `LobbyEmotePlayer::LoadDefinitions` S 0051c710, `LobbyAnimSelector::LoadXml` S 00500b50 |

### 3.11 User profile files

`<My Documents>\SAdK\users\`, plain `NCore::FileStream`, encoding of a decrypted save
(`docs/sim/save-format.md` §2).

**`settings.cfg`**: two sections, `UserSettings` (written as version 2 by `UserProfile::StoreSettings`
S 00579640, read by `UserProfile::LoadSettings` S 00579960) followed by `SceneSettings` (`S2CG::Settings::Store`
S 00696270 / `Load` S 006960a0, reached through `SceneSettings_StoreGlobal` S 0067e7c0 / `SceneSettings_LoadGlobal`
S 0067e7a0) [known]. Each section starts with the 12-byte tag (version, CRC-32 of the name, name length). The
field-by-field layout of both sections, the version rules of the reader and what is applied after the read are
specified once, in [app-shell.md](app-shell.md) §3.9; the meaning of every field is in its §2.6 (profile) and §2.7
(scene settings).

**`data.cfg`**: the per-map progress list (`UserProfile_SaveMapStates` S 00579430). Each record
(`nUser::MapState::Store` S 00579e80) [known]: tag `UserMapState`, `str mapName`, `bool completed`, `i32 state`,
`i32 difficulty`; a record of version 0 has no difficulty and reads as 2 [known] S 00579ed0.
List header (`UserMapStates::Store` S 0057a0b0, `Load` S 0057b500) [known]: tag `UserMapStates`, then the
record count, then the records in the order of the map they are kept in, which is keyed by map name; the
loader empties the map first and inserts each record under its name. The count is 4 bytes (stream slots
`+0x64` write, `+0x38` read: the size slots of `docs/sim/save-format.md` §2.2) [known].

**`<name>.avo`**: §3.5. **`lobby\<profile>.ini`**: per-user lobby settings, Win32 profile format [inferred]
S 00465dd0.

Other user files: `saves\<name>.aav`, `mp_saves\...` and its `.mps.bmp` previews, `maps\<name>.s2m` with
`.bmp` (user maps, type 3), `dumps\<...>.s2dump.txt` (desync dumps, written only),
`screenshots\Pic_<YYYYMMDD>_<hhmmss>.bmp` (written only, `ScreenshotTool::SaveScreenShot` S 004ddc50),
`copypaste.dat` (the debug map editor's buffer, S 006015f0).

Outside the user-folder rule: `copypaste.dat` is requested by its bare name (S 00609130). A write open of
`NCore::FileStream` S 0057d140 uses the request as given when the index does not resolve it, so the file is
created in the working directory, the game root [known: fallback; inferred: location]; the read open has no
such fallback, so a file there is not found again through the index [inferred] (§10 question 10).
Logs: `Logfile_0.txt` (older runs rotated to `Logfile_1.txt`..`Logfile_9.txt`, `LogFile_ctor` S 006e5620) and
the lobby's `commLayer.log` (S 004643d0) are written to the log directory, which is `dumps\` of the user
folder unless the command line gives `-log_path <dir>` [known] S 004075d0, S 00403ac0.

### 3.12 Caches the game writes

| File | Where | Content | Evidence |
|---|---|---|---|
| `<mesh>[_<variant>].mshraw` | `<Local AppData>\SAdK\` | converted mesh: `u32 vertexCount`, `u32 stride`, vertex bytes, `u32 indexCount`, `u16` indices, `u32 boneNameCount`, bone name strings, `u32 subsetCount`, per subset `str name`, `u32 startIndex`, `u32 primitiveCount`, `u32 texCount`, `texCount` × (`str usage`, `str file`) | [known: read order and widths] `CMesh::LoadPackedBinary` S 0076d990; [inferred] the meaning of the two strings per texture; used when the cache exists and passes the write-time comparison with the `.KEX` (S 0076cbe0) and `useMeshCache` is on [inferred from the summaries] |
| compiled effects | `<Local AppData>\SAdK\` | D3DX effect binaries, §3.4 | [known] S 004eb8f0, S 004ebad0 |
| `<map>.info`, `<map>.usermapinfo` | `<Local AppData>\SAdK\` | `MapInfo` only | `docs/sim/save-format.md` §3.10 |
| `daytimes.bin` | `[data]\settings\` (inside the install) | `u32 count`, then `count` records of 0x4c bytes; read in preference to `daytimes.xml` when present, written after the XML was parsed | [known] S 00684130 (existence test, XML parse, then the write call); [inferred from its summary] the layout read by S 00684510; record: §3.10; not in the reference install |
| `<graph>.xag` | `<Local AppData>\SAdK\` | path is built, file is never used | [inferred] S 0050f7e0 |

All are derived data; a converter ignores them. A `daytimes.bin` left in an install overrides `daytimes.xml`.

### 3.13 Textures, audio, maps: what the data holds

- `.dds` (1,050): DXT1 792 (2 of them cube maps), DXT3 58, DXT5 17, uncompressed 32-bit with alpha 127, 16-bit
  with alpha 28, 24-bit 21, 16-bit 5, 8-bit 1; 823 with mip chains, 226 without; 7 with a side that is not a
  power of two. One file (`data\game\animals\pig.dds`) holds a BMP image [known: decrypted headers]. The image
  type is taken from the content by D3DX, not from the extension [inferred].
- `.tga` (125): uncompressed true colour 24-bit 61 and 32-bit 60, RLE 3, greyscale 8-bit 1 [known].
- `.png`: `gfx\timedgoodbutton.png` (encrypted, read as a texture); `lobby\web\UIColor.PNG` plain.
- `.bmp` (35): 31 map previews `data\game\maps\...\<map>.bmp`, 128 × 128, 32-bit, uncompressed; 2 lobby textures
  (`Tree01color.BMP`, `Tree01normal.BMP`, 1024 × 1024, 24-bit); 2 installer images [known].
- `.ogg` (738): Vorbis, 44.1 kHz; 36 stereo (26 in `sound\music`, 6 in `sound\ambients`, 4 in
  `lobby\sound\ambient`), 702 mono (540 of them voices). `.wav` (126): 103 PCM 16-bit mono 44.1 kHz, 12 IMA
  ADPCM stereo 32 kHz, 4 IMA ADPCM mono 44.1 kHz, 7 IEEE float stereo 44.1 kHz [known: every file, `file`].
- Sound files are named by the sound properties (`sn_create`, file name lists `SoundProperty::AddFileName`
  S 00555ba0) and loaded at start-up by `Sound_LoadSoundsFromProperties` S 0056b190: samples or streams, 2D or
  3D with a minimum and maximum distance, with a loop mode [inferred from the summary]. UI sounds are named in
  code (`uiClick0`, `uiClick1`, `uiCancel`, `uiMessage0`, `uiMessage1`, `uiDialog0`, `uiKey0`, `uiRemove`,
  S 005dda30) and resolved as `[data]\sound\<name>.wav`.
- Maps: 33 `.s2m`, each with an optional `.bin` sidecar (31), a `.bmp` preview (31) and Lua scripts
  (197 `.lua` in `maps\`: one per map plus cutscene scripts such as `C01_2coldHills.lua`).

### 3.14 Files in the install that the client does not read

No string in the image names them [known: string search], and no listing pattern matches them [inferred]:
`.lep` presets, `language\de\info.txt`, `language\de\dialogs.txt`, `language\crashmsg.ini`,
`settings\properties_filterlist.ini`, `data\s2008_devnews.txt`, the `.psd` font sources, `Kopie von
system_00.tga`, the `- Copy.ini` files, `gfx\*.ico`. `maps\campaignMaps\C02.sav` is a plain file with the
encoding of a decrypted save; no map type pairs that folder with `.sav` (`docs/sim/save-format.md` §3.4).
`lobby\web\Rangliste1.html`, `Rangliste2.html` and `UIColor.PNG`: the image holds no string `Rangliste`,
`web\` or a local `.html` name (its only `.html` strings are three `http://www.funatics.de/sadk/forwarding<n>.html`
URLs at S 007e61a0..007e6210) [known: string search]; [inferred] the client does not open these files by a
name of its own.

## 4. Update order

On start-up (`CApplicationEx::Initialize` S 004075d0, call order [known]; what each callee reads is [known]
where an address is given, otherwise per `docs/data-loading.md` §1):

1. Command line parsed; user folders created (`Fs_CreateUserDataDirectories` S 0057bfb0). The log directory
   is set to `<My Documents>\SAdK\dumps` unless `-log_path <dir>` names another (§3.11). The working
   directory is already the game root (§2.1).
2. File index built from `data\` (§3.1). Everything after this resolves names through it.
3. Property scripts (`scripts\properties\data.lua` and the scripts it calls).
4. Sound system (`Sound_Init` S 0056b310): if the sound manager initialises, every file named by a sound
   property is loaded (`Sound_LoadSoundsFromProperties` S 0056b190); if it does not, none is.
5. User profile (`UserProfile_LoadFromDisk` S 00578fe0): `settings.cfg`, then `data.cfg`; each is skipped
   when the file does not exist or cannot be opened.
6. Lobby profile (`LobbyProfile::Init` S 00465dd0): only the paths of `LobbySettings.ini` and of the per-user
   `lobby\<profile>.ini` are built; the values are read on demand. Unless `-nolobby`: `ItemsClient.txt`
   (`LobbyComm::System::Initialize` S 004643d0).
7. Engine layer (`CApplicationEx::InitEngineLayer` S 00405590): `engine.ini` and `engine.xml`
   (`CGraphicDevice::Init` S 004da2a0); after the device exists the mesh renderer, the particle manager
   (`particle_shader.fx`, the particle atlas, S 004e0ad0) and the decal renderer are created. A failed device
   initialisation ends start-up here.
8. Unless `-nolobby`: the lobby's zone table `world1.xml` (`CLobby` vtable `LoadZoneTable`).
9. Menus (`nMenu::System::Initialize` S 005dda30), in this order: `menu.cfg`, the five language tables
   (`briefings.txt`, `ui.txt`, `credits.txt`, `lobby_ui.txt`, `lobby_items.txt`, S 00496b80), eight UI sounds
   (`uiClick0`, `uiClick1`, `uiCancel`, `uiMessage0`, `uiMessage1`, `uiDialog0`, `uiKey0`, `uiRemove`), the
   fonts `light_system`, `dark_system`, `light_system_outlined`, then the screens (main, game, splash, exit,
   info, debug, book, victory, requester, message box, defeat, report, net info, cinematic). Other fonts,
   `cursors.xml` and each screen's layout XML are read on first use [inferred].
10. Map-info caches refreshed (`GameFile_RefreshAllMapInfoCaches`, `docs/sim/save-format.md` §3.11).
11. Shaders: while the splash screen updates (`nMenu::Splash::Update` S 0060c5a0 →
    `ShaderPreload_StepUntilDone` S 0067e880 → S 004dacc0), the `*.fx` files of `fx_20` are listed once
    (`ShaderProgram_BuildPreloadList` S 004ebe80) and one of them, taken from the end of the list, is compiled
    or loaded from the cache per call (`ShaderProgram_PreloadNext` S 004ec910) [known]; the step is skipped
    while two graphic-device conditions (flag `+0xa4`, `+0x10c != 1`) do not hold ([TODO] not established:
    their meaning). An effect not preloaded is loaded when first requested (`ShaderProgram_GetOrCreate`
    S 004ecba0) [inferred].

Per match (`nGame::System::BuildWorld` S 00784d40 → `BuildScene` S 007842e0) [known: call order]:

1. `terrain_static_data.xml` and `map_objects.xml` (`Scene_LoadTerrainStaticDataAndMapObjects`).
2. The scene's vtable slot 0 (`S2CG::Scene::Init` S 006824c0 per `docs/data-loading.md` §2): `graphics.xml`,
   `items.xml`, `settler_config.xml`, `settler_animations.xml`, `buildings.xml`, `animals.xml`, `ships.xml`
   [order of the string uses in S 006824c0, inferred]. The effect manager is created here: its constructor
   S 00686da0 lists `[data]\scripts\effects\*.pfx` (names only) and reads `effectMovies.xml` (S 00686160)
   [known].
3. The map script is initialised, then the map (`.s2m`, `.bin`) is loaded (`Game_LoadWorldFromDescriptor`).

Models and textures are loaded as objects are created. `ParticleManager::LoadEmitterFile` S 004e0950 opens
and parses the `.pfx` on every call and keeps no cache; its two callers `EffectScriptMgr::LoadEffectByName`
S 00685bb0 and `LoadEffectByIndex` S 00685e10 only build the path and call it [known]. Every emitter that is
started therefore reads its effect file again.

Per frame: no file format is parsed in the logic tick. The scene's render pass calls
`ParticleManager::RenderAll` S 004dfdc0 with the scene's real-time value (S 0067eb20); it runs each
emitter's `Update` S 004f0790 (virtual slot `+4`) only for the emitters in its depth buckets, i.e. those
whose bounds passed the frustum test of `CullAndSortEmitters` S 004e0660 in the scene update [known].
The lobby draws its emitters one by one through `RenderEmitter` S 004e0280. Both menu systems' updates call
`Localization::ReloadIfLanguageChanged` S 00496e60, which empties the text map and loads the five tables
again when its change flag (`+0x29`) is set [known]; [inferred] the flag is set by a watch on the language
folder.

## 5. Inputs and outputs

Consumes: the install's `data\` tree, the user folder, the cache folder.

Produces, for the other subsystems:

| Consumer | Gets |
|---|---|
| Simulation (`docs/sim/*.md`) | property records from Lua; the map; nothing else of this document |
| Rendering | meshes, skeletons, animations (`.KEX`), textures, effects (`.fx`), particle emitters (`.pfx`), scene XML |
| UI | layout trees, fonts, cursors, text tables, UI sounds |
| Audio | samples and streams |
| Network | `network.ini`, `LobbySettings.ini`; the build checksum over `scripts\**\*.lua` and `settings\**\*.xml` (§8) |

Writes: the user profile, saves, avatar files, screenshots, dumps, the caches of §3.12.

## 6. Data-driven parameters

Every file here is a parameter source. Cross-references that a converter must follow:

| From | Key | To |
|---|---|---|
| `buildings.xml` | `Building mesh=`, `frame=`; `DoorOpen file=`, `DoorClose file=`, `Working file=`; `Production mesh=`, `model=`, `texture=`, `anim0=` | `.KEX` (written as `.KEX` in the file), `.dds` |
| `buildings.xml`, `settler_animations.xml`, `effectMovies.xml`, `projectiles.xml` | `Particle name=`, `PFX name=`, `particles=`, `flightPFX=` | `scripts\effects\<name>.pfx` |
| `settler_config.xml` | `Character mesh=`, `mesh1=`..`mesh3=`, `color=`; `Model file=`; `Animation filename=` | `.KEX`; `color` → `.dds` |
| `settler_animations.xml` | `Animation filename=`, `src=` | `.KEX` |
| `animals.xml`, `items.xml`, `projectiles.xml` | `mesh=`, `model=`; `items.xml` also `animation=` | `.KEX` |
| `ships.xml` | `mesh=`, `model=`, `frame=`, `idle=`, `move=`, `sink=` | `.KEX` |
| `map_objects.xml` | `LandscapeElement mesh=`, `shader=` | `.KEX`; `gfx\fx_20\<name>.fx` |
| `.KEX` materials | `DiffuseColor` etc. texture file names | `.dds` / `.tga` by bare name |
| `terrain_static_data.xml` | `Pattern texture=`, `normal=`; `Cover opacity=` (`transition=` is a number, not a file) | `map\textures\*.dds` |
| layout XML | `texture=`, `font=`, `content="!KEY"` | `gfx\<name>.dds`, `fonts\<name>.fnt`, text tables |
| `.fnt` | base name | `<name>_00.tga` |
| `.npc` | the strings `modelFile`, `meshFile`, `textureFile`, `idleAnimation` of §3.5, written `[data]/avatars/<file>` | `data\lobby\avatars\*` (found by name, §3.1) |
| sound properties (Lua) | `properties.sn_addFileName(id, "[data]\\sound\\...")` | `sound\**\*.wav`, `*.ogg`. The 540 `.ogg` under `language\de\` are not named there; [inferred] they are the voice files addressed through `Localization::BuildLanguagePath` (`Menu_PlayVoiceOver` S 005db000) |
| map list, `campaigns.xml` | `Map filename=` (base name, e.g. `C01`) | `.s2m` + `.bin` + `.bmp` + `.lua` of that base name |

Model references in the install's XML and `.npc` files end in `.KEX`. `.gr2` / `.GR2` names occur only in the
idle-animation string of two `.npc` files (§3.5) and in five path literals of the image (e.g. S 007fab48
`[data]\map\objects\buoy.GR2`) [known: data search, string search]; the loaders map them to `.KEX` (§3.1).

Example values [known: file contents]: `BlackSmoke.pfx`: 72 particles, ttl 5 ± 3 s, size 4 ± 3, velocity
(0, 2.5, 0) ± (0.3, 0.25, 0.3), colour (0.7, 0.7, 0.7, 0.8) ± (0, 0, 0, 0.2), spawn interval 0.02 ± 0.01 s,
renderer `Decal`, UV (0.25, 0)..(0.5, 0.25), velocity curve linear (1, 0.7), size curve cubic
(0.1, 1.5, 1.5, 2.0), colour curve linear (0.3, 1.3), opacity curve cubic (0.5, −4, 0, 1), pass 2.
`Smoke.pfx` differs in: 50 particles, velocity (0, 3, 0) ± (0.3, 1, 0.3), colour (1, 1, 1, 0.3) ±
(0, 0, 0, 0.15), colour curve constant 1, pass 1.
`system.fnt`: `lineHeight=19 base=15 scaleW=256 scaleH=256`, padding 3,3,3,3.

## 7. Save and load

No format of this document is part of a save game. A save refers to assets only indirectly: property ids, the
map name, the user profile's last-save name (`docs/sim/save-format.md` §7). Particle emitters, fonts, UI trees,
textures, sounds and the file index are rebuilt from the install on every start or match. The user profile
(`settings.cfg`, `data.cfg`) is separate from saves and survives them.

## 8. Determinism notes

Presentation only, with these exceptions that reach the simulation and are specified elsewhere: the property
scripts, the map and its scripts, `network.ini` timing values.

- **Particles** draw from the generator embedded in each `ParticleEmitterParams` (`+0x74`), a separate
  instance of the generator class; the simulation's generator is not touched. The constructor S 004f2d50 seeds
  it with the params' `randomSeed` (`+0x70`); `ParticleEmitterParams::Reseed` S 004f2c90 seeds it with
  `randomSeed + offset` [known]. `Reseed` is called by the two starters that load an effect by index, Lua
  `createParticel` S 005aca40 and `S2CG::Particles::StartByIndex` S 006964c0, right after `Restart`, with an
  integer truncated from a float [known]; [TODO] not established: which float (the operand of the
  `__ftol2_sse` call in each; the start time passed to `Restart` is the candidate). Emitters started through
  `LoadEffectByName` (S 006a5bf0 ships, S 006dc310 stargate) are not reseeded [known: no `Reseed` caller
  there]. Emitters update in the render pass with the scene's real-time value (§4), and only while their
  bounds are in view. Nothing reads particle state back into the logic [inferred: no logic caller of the
  particle classes was seen].
- **File lookup** depends on directory enumeration order only when a name exists in several folders and the
  last folder name of more than one of them (compared with its trailing `\`) occurs in the request: the first
  such candidate in scan order wins (`PickCandidateByParentDir` S 006ef680, `Path_GetTailComponents`
  S 006ef2d0) [known]. When no candidate matches, or the request is a bare name, the result is a failed
  open whatever the order (§3.1).
- **Build checksum**: `GameData_ComputeBuildChecksum` S 005ab800 lists `[data]\scripts\**\*.lua` and
  `[data]\settings\**\*.xml` (both data roots) and XORs one dword per file: it reads the first 20 bytes; if
  20 were read and the first dword is the container version constant, the dword is the header field `+0x08`
  (the CRC-32 of the plaintext, §2.4); otherwise, if more than 3 bytes were read, it is
  `file size XOR first dword`; shorter files add nothing [known]. File order does not matter. The value
  therefore follows the stored plaintext CRC of each container among those files, not its encrypted bytes
  (the header field is taken as it stands, without decrypting); a converter must not rewrite those files in
  place. Changes whose dwords cancel under XOR are not detected.
- `settler_animations.xml` and `buildings.xml` carry timings (`start`, `duration`) of sounds and particles;
  whether any logic duration is taken from the animation files is a question for
  `docs/sim/settlers-jobs.md`, not answered here.

## 9. Notes for a Godot reimplementation

**Lookup.** Reproduce §3.1 in the importer: build a map from lower-case file name to directories over the
player's `data\` tree; resolve every reference by bare name, use the folders of the request only to choose among
duplicates, and map `.gr2` to `.kex`. Do not treat `[data]\x\y` as a real relative path: the data relies on the
name-only lookup. Report a name with several candidates and no matching parent folder.

**Decrypt first.** Run the container decoder (`tools/sadk_crypt.py` logic) on the types of §2.3, keyed by the
file's own lower-case name. Keep the decision per reader (§3.2), not per magic bytes.

**Targets.**

| Source | Target | Lost or needing care |
|---|---|---|
| `.KEX` mesh, skeleton, animation | glTF 2.0 (`.glb`), one per model with its animations merged in by bone name | source axes and unit scale per file; evenly spaced keys (resample or keep step); 3×3 scale matrices in keys (may hold shear); material slots are 3ds Max usages, not PBR; vertex stream types 2 and 12/13 semantics (`docs/asset-formats.md` §2) |
| `.dds` | keep as DDS (Godot imports DXT1/3/5) or PNG for uncompressed and UI atlases | cube maps (2); 16-bit and 8-bit formats; non-power-of-two sizes; `pig.dds` is a BMP |
| `.tga`, `.png`, `.bmp` | PNG | cursor images need their hot spot from `cursors.xml`; colour-index avatar textures must stay unfiltered and lossless |
| `.ogg` | unchanged | sample or stream, 2D or 3D and the loop mode are sound properties, not in the file (`SoundManager::LoadSound` S 005c7250 takes them as arguments) |
| `.wav` | unchanged | 3D distances and loop mode come from the sound properties |
| `.fx` | hand-written Godot shaders per effect; keep the source as reference | D3D9 effect passes and fixed-function technique do not translate; render states live in the passes |
| `.pfx` | JSON (lossless, the layout of §3.3) plus a small CPU particle system that implements §3.3 | Godot's built-in particles do not offer the cubic and hermite forms or the staggered pre-spawn; the look depends on the pass (0..3) and on the atlas rectangle |
| `.fnt` + `_00.tga` | Godot `FontFile` from BMFont text (Godot reads this format) after applying the padding and spacing arithmetic of §3.6, with the PNG page | no kerning in the original (drop the `kerning` lines to match metrics); only ids 0..255, Windows-1252 |
| language `.txt` | Godot translation CSV or `.po`, keys unchanged | convert Windows-1252 to UTF-8; `\n` escapes; duplicate keys: later file wins; a missing key shows the key; markup tags need a renderer |
| layout XML | JSON trees, or generated Godot scenes | positions are pixels in a fixed design resolution with `%` options and dock / align enums; templates must be expanded in the game's order (template first, element second); bound elements need the screen's code |
| settings XML | JSON, same keys | misspelt names are part of the format (`enviroment`); `daytimes.xml` writes `lightheading` but the reader asks for `lighteeading`, so the heading is never read from the file (§3.10) |
| `.lua` | keep as text; run with a Lua 5.0-compatible interpreter or transpile the property scripts to JSON records | `docs/lua-surface.md`; property record order matters (`docs/sim/properties-data.md`) |
| `.s2m`, `.bin` | Godot resource per map | `docs/map-format.md` |
| `.aav` | importer optional | `docs/sim/save-format.md` §9 |
| `.npc`, `.avo` | JSON + 256-entry palette PNG (256 × 1) | palette byte order open (§3.5) |
| `.ini`, lobby `.txt` | JSON or Godot `ConfigFile` | `engine.ini` is start-up configuration of the original renderer only |
| caches (§3.12), `.lep`, files of §3.14 | ignore | — |

**Must be reproduced exactly:** the file lookup rules; the glyph arithmetic (text layout of every dialog depends
on it); the localisation fall-back (key as text); the template order; the particle formulas if effects are to
look the same. Everything else maps onto engine features (textures, audio streams, skeletal animation, fonts,
translation tables, `Control` anchors).

**Converter output layout.** Mirror the source tree below a cache root keyed by a fingerprint the converter
computes over every source file (size and modification time, or a content hash), so a changed or modded
install is converted again. The game's build checksum does not serve: it covers only Lua scripts and
settings XML and is a plain XOR (§8). Keep the original relative path and name of each file in the converted
resource's metadata, since references are by name.

## 10. Open questions

| # | Question | Settled by |
|---|---|---|
| 1 | Which vertex builder each `.pfx` renderer type uses, and the flip-book frame rule | static read of the renderer vtables S 007e5420..007e5530 and S 004f3fc0, S 004f4860 |
| 2 | Particle seeds: the float truncated into the `Reseed` offset; the source of the 16-bit `randomSeed` the params constructor stores (§2.5) | disassembly before the `__ftol2_sse` calls in S 005aca40 and S 006964c0; disassembly of the tail of S 004f2d50 |
| 3 | `.npc` palette byte order and how the texture indexes it | static read of `Texture_DecrementIndexChannel` and `ingame_avatar.fx` |
| 4 | `nUi::Shape` border widths (`border`, `bordertop`..): nine-slice or not. `LoadFromXml` S 004aa700 only stores the four floats | static read of the shape's draw function (the reader of the four border fields) |
| 5 | Attributes of the button, list, slider, combo box and tab controls | static read of their `LoadFromXml` functions (S 004afed0, S 004b8c00, S 004d04b0, S 004cbf90, S 004bad00, ...) |
| 6 | Text markup grammar (`<hcenter>`, `[Name:n]`, `#`, `%`) | static read of the text block and rich text layout code |
| 7 | `settings.cfg`: the layout is established ([app-shell.md](app-shell.md) §3.9). Open are only the meanings of the stored but unread profile fields `+0x32`, `+0x38`, `+0x78` and of the scene-settings byte `+0x48` | [app-shell.md](app-shell.md) §10, questions 1 and 3 |
| 8 | KEX vertex stream types (still inferred from sizes) | static read of the renderer's vertex declaration code (`docs/asset-formats.md` §2) |
| 9 | Answered (§3.10): the leading UTF-8 byte order mark of the reference install's `engine.ini` hides its only section `[Engine]` from `GetPrivateProfileIntA`, so every key takes the code default and edits have no effect until the file is saved without the mark [live, 2026-10-14] | — |
| 10 | Whether the debug editor ever reads `copypaste.dat` back (§3.11): the write falls back to the bare name, the read does not | static read of `Fs_FileExists` S 0057d060 and `nMenu::Debug::LoadCopyPasteBuffer` S 00606050 with its caller S 0060a340 |
| 11 | Per-attribute semantics of the settings and lobby XML files of §3.10 | static read of the listed readers, per rendering specification |
| 12 | `.lep` body | the map editor's binary (not in the install) |
| 13 | The two graphic-device conditions that gate the shader preload (§4) | static read of the writers of `CGraphicDevice +0xa4` and `+0x10c` |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 004075d0 | `CApplicationEx::Initialize` | start-up order; index build |
| 00405590 | `CApplicationEx::InitEngineLayer` | graphic device, then mesh, particle and decal renderers |
| 00403ac0 | `CApplicationEx::ParseCommandLine` | `-log_path`, `-nolobby` and the other switches |
| 006e3ca0 | `FileScanHolder::ScanDirectory` | builds the index from `data\` |
| 006ef440 | `FileScan::ScanDirectory` | enumerates one directory |
| 006f1330 | `ai::file::FileScan::ProcessEntry` | per entry: recurse or record |
| 006f10e0 | `ai::file::FileScan::AddFile` | lower-case name → directory list |
| 006e3fd0 | `FileScanHolder::ResolvePath` | request path → real path |
| 006ef8a0 | `FileScan::ResolvePath` | name lookup, duplicate choice |
| 006ef680 | `FileScan::PickCandidateByParentDir` | choice among duplicates |
| 006ef2d0 | `Path_GetTailComponents` | last folder name with its `\` for that choice |
| 006e4c10 | `FileScanHolder::FindFilesInDataPath` | listing over both roots |
| 006e6a30 | `NBase::File::Open` | plain file open (read, write, append) |
| 006e6960 | `NBase::File::ReadString` | `u32` length + bytes |
| 006e6d40 | `NBase::gReadFileData` | whole file into memory |
| 006e7770 | `File_ReadAndDecrypt` | whole file, then container decode |
| 006e6660 | `NBase::gDecryptData` | container decode; logs and writes to address 0 on a non-container |
| 006e8210 | `ai::xml::XmlDoc::LoadFromFile` | encrypted XML → tree (expat) |
| 004bdc60 | `ai::ui::ResourcePath::ctor` | bare UI resource name → path |
| 004e0950 | `ParticleManager::LoadEmitterFile` | opens a `.pfx`, creates the emitter |
| 004f1150 | `ParticleEmitter::Load` | `.pfx` layout |
| 004f3250 | `ParticleEmitterParams::Load` | params block |
| 004f2430 | `ParticleCurveSet::Load` | 4 curves |
| 004f2940 | `ParticleCurveSet::SetCurveType` | curve type → class |
| 004f1ce0 | `PropertyDesc::LoadValue` | value widths by type |
| 004f39a0 / 004f3a60 | `ParticleQuad::Load` / `ParticleQuadAnim::Load` | renderer block |
| 004f0f10 | `ParticleEmitter::CreateRenderer` | renderer type names |
| 004f04b0 | `ParticleEmitter::Restart` | staggered spawn |
| 004f1660 / 004f16c0 | `Particle::Spawn` / `ai::render::Particle::Update` | particle life cycle |
| 004f1960 | `Particle::ApplyCurves` | curves → velocity, size, colour, position |
| 004f1db0..004f2830 | curve `Evaluate` / `Prepare` functions | curve formulas |
| 004e0ad0 | `ai::render::ParticleManager::InitResources` | atlas texture, particle effect |
| 004e0280 / 004dfdc0 | `ParticleManager::RenderEmitter` / `RenderAll` | pass selection, emitter update and draw: one emitter (lobby) / all emitters in view (scene) |
| 004e0660 | `ParticleManager::CullAndSortEmitters` | frustum test, depth buckets, removal of finished emitters |
| 004f0790 | `ParticleEmitter::Update` | per-emitter update: particles, bounds, depth-sorted list |
| 004f2c90 / 004f2d50 | `ParticleEmitterParams::Reseed` / constructor | generator seed |
| 00686af0 / 00686da0 | `EffectScriptMgr::ScanEffectNames` / constructor | effect names and ids; `effectMovies.xml` |
| 00685bb0 / 00685e10 | `EffectScriptMgr::LoadEffectByName` / `LoadEffectByIndex` | effect path, one file read per emitter |
| 004ec060 | `S2CE::CShaderProgram::CreateFromFile` | `.fx` load |
| 004ebad0 | `S2CE::CShaderProgram::GetCompiledEffect` | compile and cache |
| 004ebe80 / 004ec910 | `ShaderProgram_BuildPreloadList` / `ShaderProgram_PreloadNext` | `*.fx` list; one effect per splash update |
| 004e80d0 | `S2CE::CTexture::CreateFromFile` | texture load |
| 0068b850 | `ai::render::InGameAvatarData::LoadFromFile` | `.npc` / `.avo` layout |
| 0068bf30 | `S2CG::InGameAvatar::LoadAvatar` | `.npc` / `.avo` paths |
| 004e3860 | `BitmapFont::LoadFromFnt` | `.fnt` reader |
| 004e2770 / 004e28b0 | `BitmapFont::ParseCommonLine` / `BitmapFontGlyph::ParseCharLine` | metrics, glyph arithmetic |
| 004e36b0 | `BitmapFont::LoadPageTexture` | `<name>_00.tga` |
| 004941a0 | `UiResourceManager::LoadFont` | font cache by name |
| 00491ac0 | `nUi::XMLHandler::LoadFromFile` | layout file entry |
| 004a76c0 | `nUi::Object::LoadFromXml` | common control attributes |
| 004ab6f0 | `nUi::Configurable::LoadFromXmlWithTemplate` | templates |
| 004c21d0 | `nUi::Factory::CreateChildrenFromXml` | `controltype` children |
| 004c2730 / 004c28a0 | `nUi::Factory::CreateObjectByName` / `CreateObject` | type name → kind → class |
| 0060c880 | `nMenu::Factory::CreateObjectByName` | game-specific control types |
| 004bcb80 | `nUi::Deployment::LoadFromXml` | position, size, dock, alignment |
| 004aa700 / 004b46d0 / 004b5d80 | `nUi::Shape` / `Text` / `Tip` `::LoadFromXml` | visual parts |
| 004c1530 | `nUi_Xml_ReadColorAttr` | colour syntax |
| 00493190 / 00492d80 | `nUi::Cursor::LoadFromXml` / `StyleData::LoadCursorFromXml` | `cursors.xml` |
| 00496b80 / 004966d0 | `Localization::LoadAllTextFiles` / `LoadTextFile` | text tables |
| 004963a0 / 00496070 | `Localization::SetText` / `GetText` | `\n` escape; key fall-back |
| 004955a0 | `Localization::BuildLanguagePath` | `[data]\language\<lang>\` |
| 005c7250 | `ai::audio::SoundManager::LoadSound` | sample or stream (FMOD 3) |
| 0056b310 / 0056b190 | `Sound_Init` / `Sound_LoadSoundsFromProperties` | all property sounds at start-up |
| 004da2a0 | `S2CE::CGraphicDevice::Init` | `engine.ini`, `engine.xml` |
| 0041ede0 | `NComm_NetworkConfig_LoadFromIni` | `network.ini` |
| 005dda30 | `nMenu::System::Initialize` | `menu.cfg`, text, UI sounds, screens |
| 00578fe0 | `UserProfile_LoadFromDisk` | opens `settings.cfg` and `data.cfg` |
| 00579640 / 00579960 | `UserProfile::StoreSettings` / `LoadSettings` | `settings.cfg` |
| 00579e80 / 00579ed0 | `nUser::MapState::Store` / `Load` | `data.cfg` record |
| 0057a0b0 / 0057b500 | `UserMapStates::Store` / `Load` | `data.cfg` list |
| 0057d140 | `NCore::FileStream::Open` | plain stream open; write falls back to the raw path |
| 006e5620 | `LogFile_ctor` | `Logfile_<n>.txt` rotation in the log directory |
| 0057bfb0 | `Fs_CreateUserDataDirectories` | user folder tree |
| 0076d990 / 0076c9f0 | `CMesh::LoadPackedBinary` / `GetPackedCachePath` | `.mshraw` cache |
| 00684130 / 00684510 | `CEnviromentMgr::LoadDaytimes` / `LoadDaytimesBin` | `daytimes.xml` / `.bin` |
| 007842e0 / 006824c0 | `nGame::System::BuildScene` / `S2CG::Scene::Init` | per-match order of the settings XML |
| 005ab800 | `GameData_ComputeBuildChecksum` | XOR of one header dword per Lua and settings XML file |

## Appendix: inventory by extension

Count = files of that extension in the reference install (all folders). "Enc." = encrypted container.

| Extension | Count | Enc. | Holds | Documented in | Converter | Open points |
|---|---|---|---|---|---|---|
| `.kex` | 1,639 | no | meshes, skeletons, animations | `docs/asset-formats.md` §2 | hard | stream types inferred; axes; material mapping |
| `.dds` | 1,050 | yes | textures | DDS standard; §3.13 | trivial | cube maps, odd formats, one BMP |
| `.ogg` | 738 | no | music, voices, long effects | Ogg Vorbis; §3.13 | trivial | — |
| `.lua` | 355 | yes | property, map, cutscene, tool scripts | `docs/lua-surface.md`, `docs/sim/properties-data.md` | moderate | Lua 5.0 semantics |
| `.wav` | 126 | no | sound effects | RIFF PCM; §3.13 | trivial | — |
| `.tga` | 125 | yes | textures, cursors, font pages | TGA standard; §3.13 | trivial | — |
| `.xml` | 110 | yes | UI layouts (54), scene and lobby settings | §3.8, §3.10 | moderate (settings), hard (layouts) | questions 4, 5, 11 |
| `.pfx` | 64 | no | particle emitters | §3.3 | moderate | questions 1, 2 |
| `.fx` | 59 | yes | D3D9 effects | §3.4 | hard (rewrite) | per-effect port |
| `.bmp` | 35 | no | map previews, 2 lobby textures, 2 installer images | BMP standard; §3.13 | trivial | — |
| `.s2m` | 33 | yes | maps | `docs/map-format.md` | hard | see that document |
| `.npc` | 32 | no | in-game avatar definitions | §3.5 | trivial | question 3 |
| `.bin` | 31 | no | map sidecars | `docs/map-format.md` §4.17 | trivial | names inferred there |
| `.fnt` | 15 | no | bitmap font metrics | §3.6 | trivial | — |
| `.txt` | 12 | 7 yes | language tables (7), lobby tables (3), 2 unused | §3.9, §3.10 | trivial | question 6 |
| `.ini` | 10 | no | engine, network, lobby settings; `msgdefs.ini`; unused files | §3.10 | trivial | question 9 |
| `.lep` | 8 | no | editor presets, not read by the client | §3.7 | none needed | question 12 |
| `.psd` | 6 | no | font page sources, not read | §3.14 | none | — |
| `.ico` | 6 | no | icons, not read from `data\` | §3.14 | none | — |
| `.png` | 2 | 1 yes | one UI texture; one web image | §3.13 | trivial | — |
| `.html` | 2 | no | lobby ranking pages, not named by the client | §3.14 | none | — |
| `.cfg` | 1 | yes | `menu.cfg` (Lua) | §3.10 | trivial | — |
| `.inc` | 1 | yes | `shared.inc` shader include | §3.4 | with `.fx` | — |
| `.sav` | 1 | no | stray campaign save | `docs/sim/save-format.md` §3.4 | none | — |
| user: `.aav` | — | yes | save games | `docs/sim/save-format.md` | hard (optional) | see that document |
| user: `.avo` | — | no | the player's avatar | §3.5 | trivial | question 3 |
| user: `settings.cfg`, `data.cfg` | — | no | profile | §3.11 | moderate (optional) | question 7 |
| cache: `.mshraw`, `.info`, `.usermapinfo`, compiled effects, `daytimes.bin` | — | no | derived data | §3.12 | none | — |
| written only: `.s2dump.txt`, screenshots `.bmp`, logs | — | no | diagnostics | `docs/sim/save-format.md` §3.9 | none | — |
