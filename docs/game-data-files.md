# Reading and changing the game's data files

How to read the data of an installed game and how to get a changed file into it. The formats are specified
elsewhere: the encrypted container and `.KEX` scenes in [asset-formats.md](asset-formats.md); every file type,
its reader and the document that specifies it in [sim/formats-inventory.md](sim/formats-inventory.md) (the
appendix has one row per extension); maps in [map-format.md](map-format.md); the mod system in
[`sadkmod/docs/writing-mods.md`](../sadkmod/docs/writing-mods.md).

Tags: **[known]** = read in the client (`S 00xxxxxx` = address in `sadk_noav.exe`) or in the named data file;
**[inferred]** = one step of reasoning from that; **[TODO]** = open. `<game>` is the install folder.

## 1. Which files are encrypted

- A file is an encrypted container when it starts with `12 18 09 06 "sadk"`; the extension says nothing. The
  install has 1,742: textures (`.dds`, `.tga`), Lua scripts (`.lua`, `menu.cfg`), XML (layouts, settings,
  scenes), shaders (`.fx`, `.inc`), maps (`.s2m`) and the language tables (`language\<lang>\*.txt`) [known].
- `.KEX` models and animations are **not** encrypted, nor are sound, `.pfx`, `.npc`, `.fnt`, `.bin`, `.ini` and
  the remaining types [known].
- The file key is derived from the **lower-case file name without folders** (except for `.s2m` and `.aav`). A
  container therefore decrypts only under its own name, and an encrypted file has to be built for the name it
  will have [known] (asset-formats.md §1).
- The reader decides, not the file: `NBase::gDecryptData` S 006e6660 has no plain-file branch. A plain file
  where the game expects a container is logged (`FCC mismatch`) and the game faults on purpose [known]
  (formats-inventory.md §2.3). The mod system lifts this for files that mods bring (§4.1).

## 2. Where things are

`<game>\data` has two roots, `game` and `lobby`; the game indexes every file below them by its lower-case name
(formats-inventory.md §2.2, §3.1). The `lobby` folders are described in
[sim/lobby-world-client.md](sim/lobby-world-client.md) §6.1. The `game` folders:

| Folder | Holds | Specified in |
|---|---|---|
| `animals`, `buildings`, `character`, `items`, `ships` | models and animations (`.KEX`) and their textures | asset-formats.md §2, sim/animation-models.md |
| `map`, `enviroment` | terrain and landscape objects with their textures; two maps in an older layout (`Presentation.s2m`, `X_MediterranDemo.s2m`) | map-format.md §9 |
| `maps\Freegamemaps`, `maps\campaignMaps` | the maps: `.s2m`, `.bin` sidecar, `.bmp` preview, map script `.lua` | map-format.md, lua-surface.md |
| `scripts` | `properties\*.lua` (buildings, goods, patterns: the rule data), `effects\*.pfx` (particle effects), `mapTools\*.lua` (libraries for map scripts: quests, cutscenes, AI limits), `menu.cfg`, `editor\*.lua`; `info\*.lua` (info pages the client never runs) | sim/properties-data.md, sim/lua-runtime.md (§6.1 for `info`), lua-surface.md, formats-inventory.md §3.3 |
| `settings` | settings XML (`animals.xml`, `buildings.xml`, `engine.xml`, …), `engine.ini`, `network.ini` | formats-inventory.md §3.10, data-loading.md |
| `ui\layout` | the 22 layouts of the front end and the match HUD (the lobby's 32 are in `lobby\ui\layout`) | formats-inventory.md §3.8, sim/ui-toolkit.md |
| `gfx` | shaders (`.fx`), interface and effect textures | formats-inventory.md §3.4 |
| `language` | text tables per language (`de\*.txt`), bitmap fonts (`.fnt` with `.tga` pages), speech (`.ogg`) | formats-inventory.md §3.6, §3.9 |
| `npc` | in-game avatar files (`.npc`) | formats-inventory.md §3.5 |
| `sound` | sound effects and music | sim/audio.md |
| `Editor` | `.lep` editor presets, not read by the client | formats-inventory.md §3.7 |

The texture paths of eight `.KEX` files and two unused PhysX files (`lobby\physic\myhouse.xml`,
`lobby_castle02.xml`) still carry the developers' path `D:\s2c\siedlerii008\development\app\client\data\...`
[known: data].

## 3. Reading

```
python3 tools/sadk_crypt.py decrypt <game>/data <out>    every container, checked against its own CRCs; same layout
python3 tools/sadk_crypt.py file <file> [<out>]          one container (to stdout without <out>)
python3 tools/kex.py info <file.KEX>                     one scene as JSON
python3 tools/kex.py split <dir> <out>                   per KEX: scene.json + raw indices, streams, tracks
python3 tools/kex.py check <dir>                         parse every KEX, report any that does not end exactly
```

- Decrypt once and work on the copy. The decrypted tree holds only the former containers; plain files (`.KEX`,
  sound, `.pfx`, …) are read from the install.
- Text on screen is named by `!KEY` tokens in layouts and scripts (e.g. `!ENTER_VILLAGE_BUTTON`); the language
  tables map keys to text (formats-inventory.md §3.9). To find where a visible text is used, look the text up in
  the tables, then search the data for its key.
- Conversion into open formats for the remake: [remake/assets.md](remake/assets.md).

## 4. Changing

Work on copies and keep the originals.

### 4.1 With the mod system

Mods run only on the DRM-free `SADK.exe` ([../mods/README.md](../mods/README.md)). Put the changed file, **plain**, at
the same path below `<game>\mods\<name>\data` as it has below `<game>\data`. The shim redirects the game's file
opens to it and lets a file without the container header through `gDecryptData`, so nothing has to be
re-encrypted; nothing in the game folder changes, and deleting the mod's folder undoes it. Conflicts, new files
and load order: `writing-mods.md`, "Data files".

- A property script with a new name in `scripts\properties\` runs after the game's own; for a few changed values
  that is better than replacing the game's file (example: `mods/foresterfix`).
- Changed `scripts\**\*.lua` or `settings\**\*.xml` change the build checksum: the game can then play matches only
  with players who have the same files ([data-loading.md](data-loading.md) §3; server mods in `writing-mods.md`).
- The game caches converted meshes as `%LOCALAPPDATA%\SAdK\*.mshraw`; the mesh of a mod is cached apart from the
  game's. The `nomeshcache` mod loads every model from its `.KEX` while models are being changed. The repository
  has no `.KEX` writer: `kex.py` reads and splits.
- The redirect and the pass-through are covered by the mod host's Wine tests (`writing-mods.md`); a replaced
  script loaded by the running game is not recorded yet [TODO] ([lua-surface.md](lua-surface.md) §2.1).

### 4.2 Without the mod system

Without the shim (for example the retail, SecuROM-protected executable) a changed file has to replace the original
in `<game>\data`, as a container built for its file name:

```
python3 tools/sadk_crypt.py encrypt <plain file> <output file>    key from the output file's name
```

The tool stores the data uncompressed (every LZSS item a literal, 12.5 % larger than the plain file) and checks
the result by decrypting it again. The game's decoder reads such a stream like any other [inferred from
`Lzss_Decode` S 007630a0]; a file built this way has not been loaded by the game yet [TODO]. The build checksum of
§4.1 applies the same way.

## 5. What a data change can and cannot do

- Rules and content are data the code reads: property scripts, settings XML, map scripts. Changing them changes
  the game ([sim/properties-data.md](sim/properties-data.md), [data-loading.md](data-loading.md)).
- Layout files hold layout only. A screen class loads a fixed file and looks its own controls up by name; an
  element with a `controltype` attribute is created and owned by its parent and drawn with it
  (formats-inventory.md §3.8) [known]. Which screen or dialog opens, when, and what a click does is code
  ([sim/lobby-screens.md](sim/lobby-screens.md) §2, [sim/frontend-screens.md](sim/frontend-screens.md),
  [sim/ingame-ui.md](sim/ingame-ui.md) §3.9). None of the 54 layout files has an attribute that names another
  screen or an action [known: data].
- A control added to a layout is therefore drawn but does nothing unless its class binds that name [inferred].
  Example: Host and Join are items of the `MainMenu` drop-down of `lobbyWorldScreen.xml`, bound and handled by
  `WorldScreen` (sim/lobby-screens.md §2.8, §3.11), which exists only after the village is entered (state 9,
  [sim/lobby-client-state.md](sim/lobby-client-state.md)). A copy in `lobbyAvatarScreen.xml` is drawn on the
  character screen and stays inert: `AvatarScreen` binds only its own controls (sim/lobby-screens.md §2.7).
- New behaviour needs code: a `mod.dll` (`writing-mods.md`).

## 6. AdKEd

`AdKEd.exe` (banner `AdKEd v1.11 BETA (c) 2008 Trass3r`, published in the Xentax thread below) is the community's
converter for the containers. It is not shipped here and not needed: `tools/sadk_crypt.py` decrypts and encrypts.
For those who still use it: it toggles a file in place (a container becomes plain, a plain file becomes a
container) and derives the key from the file's name, so run it on a copy that keeps the original name [inferred
from §1]. It is packed with MEW and crashes before `main()` under Wine, in 64- and 32-bit prefixes.

## 7. Community

| Resource | URL |
|---|---|
| ModDB (mods and tools) | https://www.moddb.com/games/the-settlers-rise-of-cultures |
| Siedler-Maps.de | https://www.siedler-maps.de |
| GOG forum, file decoder thread | https://www.gog.com/forum/the_settlers_series/file_decoder_settlers_2_10th_anniversary_and_rise_of_cultures |
| Xentax forum, AdKEd thread | https://forum.xentax.com/viewtopic.php?f=21&t=3165 |
