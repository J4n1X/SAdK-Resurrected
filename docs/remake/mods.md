# Remake: mods — packages, load stages, code, multiplayer

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). It turns the mod model fixed in
[`../remake-architecture.md`](../remake-architecture.md) §3, §8, §9 into a concrete design: what a mod package
holds, how the engine finds, orders and loads mods, how code mods are loaded and patched, how mod sets work in
multiplayer and in saves.

Tags: **[binding]** = decided by the maintainer (the architecture and rendering documents); **[draft]** = proposed
here, to be confirmed; facts about the original keep the tags of the document they come from.

## 1. What is already fixed [binding]

- The base game is built into the engine as built-in mods: `core.game`, `core.mainmenu`, later `core.lobby` (§11a);
  they are always loaded, first, and cannot be switched off (maintainer, 2026-10-22). They keep a mod's identity and
  extension points: other mods name them as dependencies, override their game rules by name, listen to and replace
  their intents, patch their documents and assets, and change their registry entries.
- Load stages over all mods in dependency order: settings, data (definitions, updates, final fixes), frozen
  registry, runtime. One registry; any mod may change any entry during the data stages.
- A manifest per mod: name, version, dependencies (required, optional, incompatible), whether it changes the
  simulation. Multiplayer requires the same simulation mods in the same versions; missing mods are transferred.
- Three levels of change: values of registry entries, components added to types, Harmony patches.
- Mods are precompiled assemblies loaded through `AssemblyLoadContext`; JIT runtime, no NativeAOT. Mods may define
  their own Godot node types (maintainer, 2026-10-15, §7.1); moddable UI comes as `IInspectable` descriptions and XML
  layouts. Source mods (Roslyn) are optional and later.
- The renderer is moddable through the asset lookup (assets, shaders) and Harmony, not through registry entries of
  its own.
- `core.game` builds its registry entries by running the original's property scripts against its own
  `properties.*` bindings.

## 2. The mod package [draft]

A mod is a folder, or a `.zip` file with the same layout, named after the mod's id. Every part is optional except
the manifest.

```
<id>/
  mod.xml                     manifest (§3)
  bin/                        assemblies: simulation assemblies (no Godot reference) and client assemblies
  data/                       data-stage Lua: settings.lua, data.lua, data-updates.lua, data-final-fixes.lua (§6)
  assets/                     a layer of the virtual file system (assets.md §4): models, textures, sounds,
                              shaders, presentation XML (visuals, layouts, UI parts), localisation, fonts
  patches/                    XML patch files applied to the merged presentation documents (§6.6)
  scripts/                    Lua libraries that map scripts may `require` (lua.md §4.6)
  assets/maps/<name>.sadkmap  map packages the mod ships (campaigns, scenarios); a folder of that name changes another
                              map's package (assets.md §5.6)
```

What a part changes, and therefore whether the mod is a simulation mod:

| Part | Changes the simulation | Notes |
|---|---|---|
| simulation assemblies | yes | components, systems, commands, Lua libraries for map scripts, Harmony patches of simulation code |
| client assemblies | no | render kinds, UI parts, input, audio; may reference Godot. Must not change simulation state (§7.6) |
| `data/*.lua` | yes | registry changes. `settings.lua` only declares settings |
| `assets/` | no | presentation only; the simulation never reads an asset (§8.3) |
| `patches/` | no | patch presentation documents only |
| `scripts/` | yes | run inside the simulation when a map script requires them |
| `assets/maps/` | per map | a map is compared and transferred as a map, not as part of the mod set; an overlay folder that changes a map's `world/` or `script/` changes that map (assets.md §5.6) |

Whether a mod changes the simulation is read from its contents [implemented 2026-10-15]: a simulation assembly, a
data-stage script (`data/data.lua`, `data/data-updates.lua`, `data/data-final-fixes.lua`) or a `scripts/` library
makes it a simulation mod; `mod.xml` has no flag for it. The registry checksum (§6.5) catches anything the contents
miss.

The built-in mods (§11a) have this layout too, without `bin/`: their data is in `<game folder>/base/<id>/` (in the
source tree `src/Base/<id>/`), their code is the game's own assemblies, which the host hands to the mod loader as
entry types [implemented 2026-10-22]. `core.game`'s `assets/` holds the remake's own files (shaders, the remake's
layouts and UI parts); the content converted from the player's installation is mounted below all mods as a layer of
its own (assets.md §5.1). `refined`, a mod that ships with the game in `mods/`, carries the refined mode's simulation
fixes as game rules (§9.4, §14 item 7).

## 3. Manifest (`mod.xml`) [draft]

```xml
<Mod id="brewery-yeast" version="1.2.0">
  <Title>Yeast for the brewery</Title>
  <Description>The brewery also produces yeast.</Description>
  <Authors><Author>someone</Author></Authors>
  <Engine min="1.0" max="1.*"/>
  <Dependencies>
    <Requires id="core.game" version="^1.0"/>
    <Optional id="more-goods" version="^2.1"/>
    <Incompatible id="old-brewery"/>
  </Dependencies>
  <Assemblies>
    <Simulation>bin/BreweryYeast.dll</Simulation>
    <Client>bin/BreweryYeast.Client.dll</Client>
  </Assemblies>
  <Transfer>allowed</Transfer>
  <SaveCompatible from="1.0.0"/>
</Mod>
```

- **id**: lower-case letters, digits, `-`, `_`, `.`; unique; never changes between versions. It is the mod's
  Harmony id, its log prefix, the default prefix of its registry keys (§6.4) and its virtual folder for its own
  assets (assets.md §4.2).
- **version**: semantic version. Multiplayer and saves compare the exact version plus a content hash (§9.1).
- **Engine**: the range of engine API versions the mod was built against. The engine refuses mods outside the
  range with a message instead of failing inside the mod.
- **Dependencies**: `Requires` must be present in a matching version; `Optional` is ordered before this mod when
  present; `Incompatible` must be absent. Version ranges use the npm/Cargo syntax (`^1.0`, `>=1.2 <2`).
- **Assemblies**: the entry assemblies per side; their private dependencies sit next to them in `bin/`.
- **Transfer**: `allowed` (default), `forbidden` (the author does not want peers to redistribute it; a peer
  without it cannot join), or `manual` (peers are told where to get it).
- **SaveCompatible**: the oldest version whose saves this version loads (§10).

XML because every user-edited data file of the remake that other mods may patch is XML (§6.6); the manifest itself
is not patched, but one parser and one schema tool for all user-edited files is simpler for modders and for the
editor tooling. Machine-written files (conversion records, caches) are JSON.

## 4. Where mods come from [draft]

| Source | Location | Notes |
|---|---|---|
| the player's mods | `<game folder>/mods/<id>/` or `<game folder>/mods/<id>.zip`; the mods that ship with the game (`refined`, `tools.assetbrowser`, `tools.mapviewer`) are among them; the built-in `core.*` are in `<game folder>/base/` | enabled per profile; a mod with `<EnabledByDefault>true</EnabledByDefault>` is on unless the profile switches it off; the built-in mods are always on and never stored |
| received from peers | `<game folder>/mods/received/<id>-<version>-<hash>/` | kept apart from the player's own; used only for matches that need them; pruned by age |
| development | folders given with `--mod-dir=<folder>[;<folder>]` | for working on a mod without copying it; wins over a player mod of the same id |

[implemented, maintainer 2026-10-15] Mods live in the **game folder**, next to its `settings.xml` (assets.md §3), not
in the user folder. A **profile** is a named set of enabled mods with their startup settings
(`<game folder>/profiles/<name>.xml`); the game starts with `default`. A match runs with the host's simulation set
(§9.2). A folder or zip whose manifest is unreadable, or a second mod with an id already found, is listed as a
problem on the mods screen; the other mods stay usable.

## 5. Load order [draft]

1. Collect the enabled mods and every built-in mod (always in; an enabled list that names one, from an old
   profile, replay or save, is fine); check `Requires` (present, version in range) and
   `Incompatible`; any failure stops with a message that names both mods.
2. Sort topologically: every `Requires` and every present `Optional` dependency comes before the dependent mod.
   Ties are broken by the ordinal order of the ids, so every machine computes the same order from the same set. A
   cycle stops with a message listing it. The built-in mods come before every other mod (core.mainmenu, then
   core.game, by core.game's Optional dependency), so their asset layers lie directly above the installation.
   [implemented 2026-10-22]
3. No mod is ordered by its id; a mod that builds on another's rules (§14 item 7) names it as a dependency.
   [implemented]

This one order is used everywhere a mod's position matters: the data stages, the order in which Harmony patches are
applied, the virtual file system's layers (a later mod's file shadows an earlier one's), the merge and patch order
of presentation documents, and the registration order of systems, commands, Lua libraries and render kinds. It is
the counterpart of today's "hook order = load order" rule for sadkmod mods.

## 6. Start-up sequence

### 6.1 Overview [draft]

| Step | What happens | Who runs |
|---|---|---|
| 0 | settings, installation check, first-start conversion ([assets.md](assets.md) §4) | engine |
| 1 | discover and resolve mods (§4, §5) | engine |
| 2 | mount the virtual file system: the engine's assets, the converted installation, then the mods in order, the built-in ones first ([assets.md](assets.md) §5) | engine |
| 3 | load assemblies, call each mod's entry point: Harmony patches, registrations (§7) | each mod in order |
| 4 | settings stage (§6.2) | each mod in order |
| 5 | data stage: definitions, then updates, then final fixes (§6.3) | each mod in order, per sub-stage |
| 6 | freeze: resolve references, assign indices, validate, checksum (§6.5) | engine |
| 7 | presentation documents: merge, patch, parse; asset references checked (§6.6) | engine |
| 8 | runtime registration resolved: system order, command ids, Lua libraries, render kinds (§6.7) | engine |
| 9 | main menu | — |

Per match, the map's package is mounted on top of the file system and its script is loaded ([lua.md](lua.md) §4).
Nothing above step 9 runs again for a match unless the mod set changes (§9.3).

### 6.2 Settings stage [draft]

Each mod declares its settings in C# (`ISettingsStage`) or in `data/settings.lua`. Three scopes, after Factorio:

| Scope | Meaning | In multiplayer |
|---|---|---|
| `startup` | read during the data stage; changes the registry | part of the mod set's identity; the host's values win; changing one needs the data stage again |
| `match` | read by simulation code at run time | stored in the match and its saves; set by the host in the pre-game room |
| `user` | presentation and input only | local; never read by simulation code |

`user` settings may change while the game runs and announce the change; their values are kept in the profile as
`<Setting name value>` and handed to the mod at load [implemented 2026-10-15]. The options show them in the mod's
sections (below), labelled by the text key `!<mod id>.<name>`. Startup settings are shown in the same section after
the user settings, under the note `!engine.options.mods.startup`; a change is kept in the profile and applies when the
mods load again (Apply on the mods screen, or a restart). Match settings are not listed (the host sets them in the
pre-game room). Game rules may be switched by a bool startup setting (§14 item 7). [implemented, sadk-remake cc7eb02]

**Where a mod's settings show** [implemented, sadk-remake 2026-10-25; the maintainer, 2026-10-19]: a mod chooses where
its settings go, a tab of its own or a section of its own inside an existing tab, named by the tab's id. Only the
placement changes: who owns a setting, where it is stored and its scope stay as above.
- The tabs are an entirely open registry (`OptionsRegistry`, `EngineOptions.Build`): the engine's tabs (`graphics`,
  `shadows`, `quality`, `audio`, `keys`, `interface`) and every tab a mod adds are equal, and any mod may put a section
  into any of them. Tabs stand in the order they are added: the engine's, then the mods' in load order (all mods' tabs
  before any mod's sections, so a mod may name the tab of a mod loaded after it).
- Sections stand in insertion order (the engine's, then the mods' in load order); no other ordering. A section lists
  its settings in declaration order, the mod's user settings first, its startup settings under the startup note.
- There is no Mods tab. A mod that names no place, or names a tab no loaded mod adds, gets a tab of its own under its
  title [the remake's own default].
- The API, in the settings stage: `ModSettings.Tab(id, title)` adds a tab; `Section(id, title?, tab?, advanced?)`
  opens a section that the settings declared after it (to the end of the stage) stand in; `Unlisted()` keeps the
  settings after it out of the options (stored and read as any). A section id taken already becomes
  `<mod id>.<id>`; a tab added twice is reported and its sections go to the first. `advanced: true` shows a section
  only with the advanced graphics ([renderer.md](renderer.md) §19).
- The base game: core.game's camera and cursor settings form the section `input` (the original's INPUT group) in the
  engine's `keys` tab (titled Controls); its pause band and autosave the section `game` (GAME) on its own tab `game`;
  the six lobby options are unlisted. refined puts its section `refined` on the `game` tab.
- Both options screens are made from the registry: core.game's panel in the original's look (a section named like one
  of the original's groups takes that group's bar and title; tab buttons beyond the template's eight go on along its
  row, 90 apart [the remake's own]) and the engine's own screen without core.game (which has no key bindings).

Declarations are validated: `Choice(...)` and ranged `Int`/`Float`; `SetPending`/`NextValue` hold a startup
setting's next value; `TitleOf` gives the owning mod's title for its own tab and its untitled sections. [implemented
with the options panel]

**Engine settings and mod settings** [rule, implemented with the options panel]. A setting lives with the code that
reads it. What is not specific to the game is an engine setting, stored in its own element of `settings.xml`; what
only the base game's code reads is a setting of its built-in mod (`core.game.*`), stored in the profile like any mod's:

| Setting | Lives in | Why |
|---|---|---|
| resolution, display mode, screen, V-Sync, frame limit | engine `WindowSettings` | not game-specific |
| the original's eight graphics values and every renderer setting | engine `RenderSettings` | the renderer is engine code ([renderer.md](renderer.md) §19) |
| the four volumes, ambience, voice, mute in background | engine `AudioSettings` | audio buses (the match's audio is engine code) |
| language, interface font | engine (`settings.xml` language, `InterfaceSettings`) | generic UI |
| key bindings | engine `InputSettings` | generic input |
| connection type | engine `NetworkSettings` | the session code is the engine's |
| scroll speed, invert scrolling, edge scrolling, invert mouse, camera style | `core.game` | the match camera is core.game's |
| smart cursor, pause band | `core.game` | only core.game's action panel, message boxes and pause panel read them |
| autosave interval | `core.game` | core.game's match saving |
| the six lobby options | `core.game` | the original's 3D lobby belongs to this game; stored only |
| `refined.fieldBlessing`, `refined.groupedGoods` | `refined`, startup scope | that mod's rules |

**The options panel** is `core.game.options` (`engine.options` is routed to it): the original's `menuoptions.xml`
frame with `menuIngameSettings.xml`'s tab control, its tabs and groups from the registry above
([renderer.md](renderer.md) §19 lists them). A setting an original control already shows is not repeated; a page whose
groups do not fit scrolls. Every change applies at once, with no apply or cancel button; showing a value never writes
it back (the original's `LoadOptionValue` S 005e55b0 snaps slider values when the panel opens, a menu bug not
reproduced). Refined or faithful is not an option: it is the mod set (§9.4).

### 6.3 Data stage [draft]

Three sub-stages; each runs over all mods in load order before the next starts [binding]. In each sub-stage a
mod's C# part runs first (`IDataStage.Definitions` / `Updates` / `FinalFixes`), then its XML definitions
(`defs/*.xml`, §14.1: entries in the definitions sub-stage, `<Update>` elements in the updates sub-stage), then its Lua
file (`data.lua` / `data-updates.lua` / `data-final-fixes.lua`).

**The content model is the engine's** [implemented, the maintainer's decision 2026-10-15]: the record types
(`TribeDef`, `GoodDef`, `BuildingDef`, `PatternDef`, …, namespace `Sadk.Engine.Content`), the registry kinds and the
`properties.*` API (`Sadk.Engine.Content.Properties`) belong to the engine, not to a mod. Before any mod's data stage
the engine defines the kinds and the four configuration blocks (owner `engine`) and installs `properties` in every
data-stage Lua state, with the global naming of §6.4; a C# data stage gets the same database (`ctx.Properties`).
While a mod's step runs, the records it creates are owned by that mod. A mod that adds records therefore needs no
dependency on `core.game`; one that reads or changes base entries (a tribe that uses the base goods) requires it.

`core.game`'s definitions sub-stage runs the original's property scripts from the converted installation
([lua.md](lua.md) §3): `data.lua` with the 21 files it loads, through the engine's `properties.*` bindings, which
create and fill registry entries. Afterwards `core.game` applies what the original keeps outside the property scripts
(settings XML values that the simulation reads, §8.3) and its own C# definitions (the behaviour components the
property values configure).

Data-stage Lua sees two APIs:

- `properties.*`: the original's 243 functions with the original's semantics, plus the remake's 13
  `X_createNamed` ([lua.md](lua.md) §3.3), so a property script written for
  the original (a sadkmod `scripts\properties\*.lua` mod) runs unchanged as a mod's `data-updates.lua`. The id
  globals of the original scripts (`woodCutter`, `brauhaus`, ...) are defined in this state.
- `registry`: a reflection view over the registry's definition objects for changes the property API cannot
  express (components, new entry kinds, mod-defined fields):

```lua
local b = registry.get("building", "brauhaus")
b.Production.WorkTicks = 300
b.Production.Output["yeast"] = 1
registry.define("building", "brewery-yeast.yeastvat", { copyOf = "brauhaus", Size = "Small" })
```

Field names are the C# property names of the definition classes; values convert as int, float (single
precision), bool, string, list and map; a registry key is a string. A field that does not exist is an error
naming the mod, file and line.

### 6.4 Registry keys [draft]

- Keys are strings, unique per entry kind (`building`, `good`, `job`, `tribe`, `doodad`, `deposit`, `pattern`,
  `animal`, `sacrifice`, `sound`, `aiProfile`, ...).
- `core.game`'s keys are the global variable names the original's property scripts assign the ids to (`brauhaus`,
  `woodCutter`); how they are found is in [lua.md](lua.md) §3.3. Each entry also keeps its original id (signed
  32 bit) as data [binding].
- An entry a mod defines without an original id gets one at the freeze, so maps, saves, commands and every rule that
  keys on the id treat it like the original's entries [decided 2026-10-26]: the same scheme as a mod command's wire id
  (`CommandType.HashWireId`: FNV-1a over the key's UTF-8 bytes, top bit set), read as signed 32 bit. It is the same
  on every peer with the same mod set and does not depend on load order. A collision with another entry's id of the
  kind, or the value −1 (the original's "none"), is a load error naming both entries. Kinds the original keeps in id
  order take a mod's entries at their assigned id's place. Consumers read `RegistryEntry.Id` (always present after the
  freeze); `OriginalId` stays the original's id alone [implemented, sadk-remake round 1].
- A mod's new entries take the prefix `<mod id>.` by convention (`X_createNamed` adds it). Defining a key that
  exists is an error; changing an existing entry goes through `get`. Collisions are loud instead of silently
  overriding; a hex `X_create` over an id another mod derived from a name is a load error naming both records, not a
  takeover.
- Owners: the kinds and configuration blocks are `engine`'s, every record belongs to the mod that created it.

### 6.5 Freeze and the registry checksum [draft]

After the final fixes:

1. every reference by key (a building's job, a cost's good) is resolved to the entry; an unknown key stops loading
   with the mod and entry that named it;
2. entries get dense runtime indices per kind. The order is definition order, which for `core.game` is the original's
   record creation order; tables the original iterates in **signed id order** keep a second order list, since that
   order changes simulation results ([binding] §8, `../sim/properties-data.md` §2.1);
3. validation by each definition class (`Validate()`), e.g. a production needs a workplace;
4. the **registry checksum**: a hash over the canonical serialisation of every simulation-relevant definition field
   (presentation fields such as the gfx name excluded). Peers compare it at join; a mismatch with an identical mod
   set means a mod's data stage is not deterministic, and the message names the first differing entry. A record's
   canonical form names its type without namespace [implemented], so moving a definition type between namespaces or
   assemblies does not change the checksum; code is covered by the match set's content hashes (§9.1). The reference
   installation gives `874b7d6c…` (896 entries).

After the freeze the registry is read-only for the rest of the process.

### 6.6 Presentation documents [draft]

Presentation data is XML that other mods extend and patch: the visual descriptors ([renderer.md](renderer.md)
§5), UI layouts and UI parts ([binding] §6), the converted settings XML the original's presentation reads
(`buildings.xml`, `map_objects.xml`, `animals.xml`, `graphics.xml`, ...), localisation tables.

1. **Merge.** All files with the same logical path in all layers are merged in layer order: the root elements'
   children are concatenated; a child with the same key attribute (`id`, `name`, `key`, per document type) as an
   earlier one replaces it.
2. **Patch.** The `patches/*.xml` of every mod, in load order, file name order within a mod: XPath selects nodes,
   then `add`, `insert`, `replace`, `remove`, `setAttribute`, `removeAttribute` (the RimWorld model; [binding]
   §6 for layouts, extended here to every presentation document). A patch that matches nothing is a warning unless
   marked `optional="true"`.

**The UI theme** [implemented 2026-10-15] is a Godot `Theme`, not XML: every layer's `ui/theme.tres` is merged in
layer order (the engine's first, then the mods' in load order) into one theme (`Sadk.Presentation.Ui.UiTheme`), so a
mod ships only what it changes or adds, made in Godot's theme editor; a relative path in it names a file next to it.
It is merged again when the conversion is mounted and when a mod set loads or unloads. The engine's type variations
are constants in `ThemeVariations` (Heading, Note, ErrorText, Dialog, Hud, ModalShade, ...), so mods see them in
IntelliSense. A theme does not pass a `CanvasLayer`, so the game's layers (modes, overlays) and a view's own layers
(the map view's HUD) start with `UiTheme.Root(...)`.

**The interface font** [implemented 2026-10-15]: `<Interface font="Vector|Original">` in settings.xml (Options,
language tab). `Vector`, the default, is Instrument Serif (SIL Open Font License, shipped with its license in the
engine's `fonts/instrument-serif/`), the maintainer's choice of a free look-alike of the original's Garamond; `Original`
is the original's bitmap fonts from the language folder. The original's roles are type variations, `GaramondHead`,
`GaramondChapter`, `GaramondSubline` at 27, 17 and 15 px, with the stroke weights 0.95, 0.80 and 0.85 px and the
glyph spacing 2, 2 and 1 px (matched against the original's bitmap fonts in the same screens). They share one
`FontVariation` (widened 1.1×) and the shader `ui/text/garamond.gdshader`, which draws the original's look from the distance field:
a heavier stroke; from the outside in a brown outline, a rim (orange facing the light from the upper left, deep brown
facing away), a band (yellowish facing the light, warm gold facing away) and the body; the soft shadow. Its colours,
weight, widths and shadow are the theme's `garamond_*` items (`garamond_body`, `_highlight`, `_shade`, `_rim`, `_edge`,
`_outline`, `_weight`, `_bevel`, `_rim_width`, `_outline_width`, `_shadow_soft`), so a mod restyles them in its
`ui/theme.tres`. The values were matched to the original glyphs' colour statistics at the menu's sizes (edge
saturation and the share of dark to coloured edge pixels within a few percent). The plain roles have their own
vector styles too [implemented, sadk-remake 1fd6903]: `Body_Arial` (the default of every widget: labels, buttons,
counts) and `small_no_alias_white` (the top bar's goods counts, the diplomacy rows, statistics; the same glyph shapes in
grey) in Liberation Sans Regular at 11 px, 1 px between glyphs, with the original glyphs' face, outline and shadow
colours; `Mini_Silk` (the 5 × 7 pixel font of slider limits, timers, "!Empty") in Liberation Mono Bold at 10 px with
its 7 px advance. Liberation 2.1.5 ships under the SIL Open Font License 1.1 in `fonts/liberation/` with its licence.
Each vector font's ascent and descent are its bitmap font's `base` and `lineHeight` (`UiFonts.LineBox`), so vector and
bitmap texts sit on the same baselines. `light_system_outlined` is used only by a layout the original never loads, and
the fonts the original names only in code (`system`, `title`, `mini`, `editor`, `dark_system`, `light_system`,
`font_big_white`, `Gamertags_Garamond`) have no style until a built screen needs them. Godot spaces glyphs in whole
pixels, so `Body_Arial` runs 3 to 7 % wider than the original.
3. **Parse** into the runtime objects (visual descriptors, layouts, UI parts).

Registry entries are not XML and are never patched this way: they change in the data stage.

### 6.7 Runtime registration [draft]

Mod entry points (§7.2) register code-level extension points during step 3; step 8 resolves what needs every
registration first:

| Extension point | Resolution |
|---|---|
| systems | ordered by "before / after named system" constraints; ambiguous or cyclic orders are refused [binding §7] |
| game commands | the original's commands keep their wire ids [binding §6]; a mod's commands get ids from a hash of `<mod id>.<command name>`, checked for collisions |
| Lua libraries | registered per context (data stage, simulation, UI) — [lua.md](lua.md) §10 |
| render kinds, asset format loaders, UI parts with code | by name; a later mod replacing a name logs it |

## 7. Code mods

### 7.1 Assembly loading [draft]

- **One `AssemblyLoadContext` per mod**, collectible (the mod set can be unloaded, §9.3). It resolves the engine,
  Harmony, GodotSharp and the .NET libraries to the instances already loaded, in the context that loaded the
  engine (in an exported Godot game that is not .NET's default context), and everything else from the mod's own
  `bin/` folder, so two mods may carry different versions of the same private library. Assemblies are read into
  memory, so zip mods work the same and no file stays locked. [implemented]
- A mod references the engine through reference assemblies of the engine SDK (a NuGet package for mod authors),
  never its own copy of `GodotSharp` or `Sadk.Engine`.
- Simulation assemblies must not reference Godot: the headless runner (tests, replays, checksum comparison against
  the original, [binding] §2) loads only them. The engine checks the references at load time.
- **No ReadyToRun and no trimming** for the engine and the mods. Trimming removes code mods may need;
  ReadyToRun precompiles call sites with inlined callees, which Harmony cannot reach. Everything is JIT-compiled.
- A simulation assembly that references GodotSharp is refused with a message naming the mod [implemented].
- **Mods may define their own Godot node types** (maintainer, 2026-10-15) [implemented]. A mod project runs Godot's
  source generators as a "tools project" (`IsGodotToolsProject=true`): the method, property and signal bridges are
  generated, so `_Ready` and `_Process` overrides are called, but no `res://` script paths (a mod's files are not in
  the game's project, and the paths of two mods would collide) and no game entry point. A mod's node type becomes a
  script without a path when its first object is made; such a script is reference-counted and leaves Godot's type map
  with its last object, so the mod's code unloads once its views are freed, in editor runs and exports alike
  [tested 2026-10-15]. The shared build rules of the mods that ship with the game are `src/Mods/Mod.props` in sadk-remake; the base game's
  projects (`Sadk.Simulation`, `Sadk.Client`, `Sadk.MainMenu`) are engine projects.
- **A mod may use the types of the mods it depends on** [implemented]. Its reference to an assembly of a dependency
  (a mod's to a type another mod defines) resolves to the copy that mod loaded, so both share one type; only
  declared dependencies are searched (`Requires`, `Optional`, and theirs in turn), before the mod's own `bin/`. A mod
  never ships a dependency's assembly: its project references it with `Private="false"`, which also gives the editor
  the dependency's symbols. The resolver holds only the dependencies' ids: it lives in the mod's load context, and
  anything of the mod it held would keep that context from being collected.

### 7.2 Entry point [draft]

```csharp
public sealed class BreweryYeast : IMod
{
    public void OnLoad(ModContext ctx)
    {
        ctx.Harmony.PatchAll(typeof(BreweryYeast).Assembly);      // Harmony id = mod id
        ctx.Systems.Add<YeastSpoilageSystem>(after: "core.game.production");
        ctx.Commands.Add<DumpYeastCommand>();
        ctx.Lua.Simulation.AddLibrary("yeast", new YeastLuaLibrary());
    }
}
```

`OnLoad` runs in load order before the settings stage, so patches are in place before any engine code that they
change runs, and before the JIT has compiled callers that might inline the patched methods. `ModContext` gives
the mod its id, its logger, its settings, its folder in the virtual file system and the registration APIs of
§6.7. A client assembly has its own entry point (`IClientMod.OnLoad(ModContext)`), called after the
simulation entry points, with the presentation registrations (render kinds, UI parts, input actions, audio). Modes,
overlays and client code read the mod set's frozen registry (`ModContext.Registry`) and its merged and patched
presentation documents (`ModContext.Documents`, set once the data stage is done) [implemented]; with them any mod
draws maps through `core.game`'s renderer (`new RenderContext(ctx)`, [renderer.md](renderer.md) §2.1). A client entry
point takes back in `OnUnload` what it gave Godot (global shader parameters, input actions), so nothing of it is left
after an in-process unload (§9.3).

### 7.3 Harmony [draft]

- The engine ships one Harmony and loads it into the shared context; mods do not bundle their own. [implemented]
  It is **HarmonyX 2.16.1** (BepInEx's fork, Harmony 2's API): Lib.Harmony 2.4.3 keeps an unloaded mod's code alive
  after `UnpatchAll` (its shared state keeps the replacement methods, which call the mod's patches), HarmonyX and
  Lib.Harmony 3.0 (release candidate) release it [tested 2026-10-15]. A test loads, patches, unloads and collects a
  mod in three rounds, so an update cannot bring the leak back unnoticed.
- At start-up the engine writes a **patch report** to the log: every patched method with the mods that patch it
  and the patch kinds (prefix, postfix, transpiler, finalizer). Two transpilers on one method are listed as a
  warning. This replaces sadkmod's "conflicts stop the game" rule, which fits fixed-address byte patches but not
  Harmony's composable patches.
- Engine code follows rules that keep it patchable: no `const` values [binding §5]; extension points are
  virtual methods or interfaces; tiny hot methods that mods are expected to change are marked
  `[MethodImpl(MethodImplOptions.NoInlining)]`.

### 7.4 Trust [draft]

Code mods run with full trust, as in RimWorld and Factorio's native-free world has no equivalent: a mod can do
anything the game process can. Therefore:

- a mod received from a peer (§9.2) that contains assemblies is loaded only after the player confirmed it (mod id,
  version, content hash, which peer sent it); the confirmation is remembered per content hash;
- data-only mods (no `bin/`) can be accepted automatically, as today's `AcceptServerMods=true`;
- Lua is sandboxed: no `io`, `os`, `debug`, `loadlib` ([lua.md](lua.md) §2.4).

### 7.5 Source mods (later) [binding §9, sketch]

`.cs` files under `src/` compiled with Roslyn at start-up into a DLL cached under `<user data>/cache/` by a hash of
the sources and the engine version; then loaded like any other mod. Content hashes for multiplayer use the sources.

### 7.6 Client code and the simulation [draft]

Client code reads the simulation only through the read interfaces and the event stream of
[sim-boundary.md](sim-boundary.md) and changes it only by sending game commands. The engine cannot enforce this
against Harmony; it is a rule for mod authors, and the per-tick checksum shows a peer whose client code broke it.

## 8. What mods can change, by layer

### 8.1 Simulation

Registry entries (data stage), new components and systems (assemblies), Harmony patches on any simulation method,
Lua libraries for map scripts, new game commands. The tick order, the hex grid, the number model and the tick
rate are not abstracted [binding §4]; a mod that changes them breaks compatibility mode and takes responsibility
for it.

### 8.2 Presentation

- **Assets**: a file at the same logical path shadows the earlier one (texture packs, replaced models, sounds); new
  assets under the mod's own folder ([assets.md](assets.md) §5).
- **Visuals**: visual descriptors map a registry entry's gfx name to model, material, shader, render kind and
  animation set ([renderer.md](renderer.md) §5); added or patched as presentation documents (§6.6).
- **Shaders**: object shaders and the shared include files are assets, so a mod can replace one object kind's
  shader or the light model for all of them ([renderer.md](renderer.md) §7).
- **Render kinds**: new drawing techniques as C# classes registered from a client assembly
  ([renderer.md](renderer.md) §4.4). This is code registration, not a registry entry, in line with [binding] §3.
- **UI**: layouts and UI parts (XML plus patches), component panels through `IInspectable` [binding §6].
- **Audio, localisation, fonts**: assets and merged tables; texts per key in a game and a map scope
  ([assets.md](assets.md) §8), maps' texts and files through overlay folders (assets.md §5.6).

### 8.3 The simulation never reads an asset [draft]

The simulation takes everything from the registry, never from an asset file. The original's simulation reads no
presentation file either as far as the documents show: it never waits for an animation
(`../sim/animation-models.md` §8), and sizes, door offsets and timings come from the property scripts. Should a value
turn up that the original's simulation takes from a presentation file (the settings XML is covered by the original's
build checksum, `../data-loading.md` §3, which makes it worth checking), `core.game` extracts it into registry data during
the data stage, where the registry checksum covers it. A texture pack or a replaced model therefore can never
desynchronise a match, and the simulation runs headless without any asset.

## 9. Mod sets in multiplayer

### 9.1 Identity [draft]

A mod in a match is `(id, version, content hash)`. The content hash covers the simulation-relevant files: the
manifest, the simulation assemblies, `data/`, `scripts/`, and the values of the mod's `startup` settings. Client
assemblies and assets are not covered: client-only differences are allowed.

The **match set** is the list of simulation mods in load order with their identities; its hash is exchanged when
a peer joins, together with the registry checksum (§6.5) and the engine version.

A map's bundled mods ([assets.md](assets.md) §7.1) belong to the match set while the map is played; they travel
with the map.

### 9.2 Joining [draft]

The host's simulation set wins, as with today's server mods (`server-mods` design, 2026-10-08):

1. the joiner compares the host's match set with its own;
2. mods it lacks (or has in another version or hash) are requested from the host and stored under
   `mods-received/` (§4); transfer is compressed and resumable; mods with `Transfer` = `forbidden` cannot be fetched
   and the join fails with the mod's name; code mods need the player's confirmation (§7.4);
3. if the joiner's running set differs from the match set, it restarts into the match set (§9.3) and reconnects
   automatically;
4. after connecting, registry checksum and match-set hash are compared once more; any difference refuses the
   join.

Client-only mods of either side are untouched.

### 9.3 Changing the mod set unloads it in the process [implemented, maintainer 2026-10-15]

The maintainer chose in-process unloading over the draft's restart. A mod set (`ModSet`) is loaded and unloaded as a
whole; nothing of a mod may outlive its set:

- every registration goes through the mod's `ModContext` and carries the mod as owner: Lua libraries, asset loaders
  (a replaced loader comes back when the replacing mod goes), settings and data stages; systems, commands and render
  kinds follow the same rule when they exist;
- unloading runs in reverse load order: `OnUnload` of every entry point, registrations removed, Harmony patches
  removed by owner (`UnpatchSelf`), the mods' layers unmounted, the registry, presentation documents and asset
  cache dropped, then every mod's load context unloaded;
- **the leak check**: afterwards the engine collects and checks every context through a weak reference. A mod whose
  code is still referenced (a static event of the engine it never left, an object of it some screen still holds) is
  named; its code stays in memory until the game restarts, and the mods screen says so. Code that keeps mod objects
  must not outlive the set: a stack frame that holds a mod's object while unloading pins it, too;
- the registry is rebuilt from scratch for the new set (data stage again; about a second for `core.game`'s property scripts).

A different simulation set for a match (§9.2) is the same unload-and-load; the game does not restart.

### 9.4 Compatibility mode, refined mode [draft]

- **Compatibility mode** is the match set `{core.game}` (the built-in base game alone) with presentation-only differences allowed, so the simulation is
  the original's tick by tick. Talking to original clients additionally needs the original's build checksum of the
  installation's `scripts\**\*.lua` and `settings\**\*.xml` (`../data-loading.md` §3), which the remake computes
  from the same installation.
- **Refined mode** is `{core.game, refined}`. `refined` is a code mod shipped with the game, off by default and
  enabled on the mods screen. Its fixes are implementations of game rules (§14 item 7) that wrap core.game's, each
  switched by a startup setting of its own (on by default, in refined's section on core.game's GAME tab of
  the options, §6.2):
  `refined.fieldBlessing` (the Blessing of the bountiful fields doubles every farm's grain, not only `corn`) and
  `refined.groupedGoods` (a need whose building type is no entry of the good's group is admitted, so olympic flames
  receive grouped goods). With every switch off
  the rule set is core.game's and the match hashes as compatibility mode. Presentation refinements are not part of
  it: they stay switches ([binding] rendering §2.3). [implemented, sadk-remake cc7eb02]
- Further simulation mods turn a match into a modded match; it can still be refined or not.

## 10. Saves and mods [draft]

- A save records the match set (identities and order), the registry checksum, the `startup` and `match` settings and
  the engine version.
- Loading needs the same simulation set; otherwise the game offers to restart into it (§9.3). A newer version of a
  mod loads a save if the save's version is at least the new version's `SaveCompatible`.
- Saved state is keyed by registry keys and component type names, never by runtime indices, so an added entry does
  not shift anything. Each component state writes a version number with its `Save` and reads older versions in
  `Load`.
- A component state of a mod that is absent is not dropped silently: the load is refused, naming the mod.
- Saves of the original (compatibility mode, `../sim/save-format.md`) store original ids; `core.game` maps them to keys
  through the original ids it keeps.

## 11. Tooling for mod authors [draft]

- **SDK** [implemented 2026-10-15]: the game's `sdk/` folder holds `Mod.props`, Godot's source generator and an
  example mod. A mod's project sets `ModId` and imports `sdk/Mod.props`; it then references the game's assemblies
  (from the exported `data_` folder, never copied), the generator (as a "tools project", §7.1; `ModUsesGodot=false`
  for simulation-only code) and the engine's assemblies, the base game's among them (`Sadk.Simulation`; for client code `Sadk.Client` and
  `Sadk.MainMenu`), and the assemblies of every other mod its `mod.xml` names as `Requires` or `Optional` (from the
  game's `mods/`, in a step the editor's design-time build runs too, so IntelliSense completes their types). A build
  copies the mod into `mods/<id>/`; `dotnet run` starts the game with the mod switched on for that run (the game's
  `--enable=<id>`; `GameArguments` and `GameEngineArguments` add the game's and Godot's options, for instance the
  installation and conversion folder when the game folder has no `settings.xml` yet). `sdk/README.md` is the guide
  for mod authors. In the source repository the SDK builds against the repository's projects (a repository-only
  `src/Sdk/Directory.Build.props`), and `dotnet run` starts the development game through the Godot editor.
  **The editor's view is checked** [implemented]: `tools/check-sdk.sh <game folder>` opens mod projects with Roslyn's
  `MSBuildWorkspace`, the loader of the editor's language server (a design-time build, then the compiler with the
  generators and analyzers), and compares references and diagnostics: the shipped example clean with the engine
  referenced, a misspelled `TribeDef` member exactly CS0117, a client mod with its own node type clean, the same
  without `partial` exactly Godot's GD0001, the repository's example clean. `tools/export-game.sh` runs it after
  every export; with only the SDK and the game files, a mod author's machine needs nothing else but .NET's
  reference packs. **Descriptions** [implemented]: the code's doc comments are XML (`<summary>`, `<para>`, `<c>`,
  `<code>`), every assembly writes its documentation file, and the files travel with the dlls (the mods' `bin/`, the
  export's `data_` folder, Godot's and Harmony's from their packages), so the editor shows the engine's, core.game's
  and Godot's descriptions; the check probes them. Checked with two mods built outside the repository: a tribe in C# with
  the engine's `TribeDef` (the example requires no mod since the content model moved into the engine), and a client mod
with its own node type, an overlay and a menu entry. The mods in the
  repository use `src/Mods/Mod.props`; the base game is built with the game (`src/Sadk.Simulation`,
  `src/Sadk.Client`, `src/Sadk.MainMenu`, data in `src/Base`). [planned] Typed constants and emit
  helpers for the intents of the required mods (a source generator over their declarations), XML schemas for
  `mod.xml` and `intents.xml`, the mods' XML doc files next to their assemblies, a `dotnet new` template.
- **The supported surface** [decided 2026-10-26]: every type stays public, so a mod can reach anything (with HarmonyX
  where it must change it); the part mod authors can rely on across versions carries `[ModApi]` (`Sadk.Engine`),
  which the SDK guide lists and the editor shows in its descriptions. A change to a `[ModApi]` member is a breaking
  change named in the release notes; anything unmarked may change without notice. The base game's simulation has one
  namespace per folder (`Core.Game.Village`, `Core.Game.Settlers`, …), so the namespace says where a type lives.
- **Lua API reference** generated from the binding attributes ([lua.md](lua.md) §10), one page per table.
- **`Sadk.Headless validate-mods [--game-folder=] [--mod-dir=] [--enable=a,b]`** [implemented]: loads a mod set like
  the game (without client code), prints the load order, the layers, the patch report, the startup settings, every
  patched document with the patches that miss, the data-stage errors and the registry checksum, then unloads it and
  checks the leak check; exit code 1 on any problem; also usable in a mod's CI.
- **Development mode**: assets and presentation documents reload when their files change; the data stage reruns on
  request (registry rebuilt, current match ended).
- **Logs**: one log file; every line from mod code carries the mod id; Lua errors with file and line (the original
  discards them, [lua.md](lua.md) §2.7).

## 11a. The built-in base game, modes and intents [agreed with the maintainer 2026-10-15, the base game built into the engine 2026-10-22; implemented in sadk-remake d49188c and the core merge]

### 11a.1 The game is a host; the base game is built in

`Sadk.Game` and the engine are a host: the first-start conversion, the virtual file system, the registry, the mod
loader, the Lua host, the asset loaders and instantiation helpers, the intent bus with its mode host (below), and the
game's own `engine.shell` (when no mod enters a mode) and `engine.mods` (the mods screen). After the start the game
emits `engine.start`; from there the mods decide what shows. The base game is part of the engine as **built-in
mods** (maintainer's decision 2026-10-22): the host hands their entry types to the mod loader (`ModSource.BuiltIn`),
their data is in `<game folder>/base/<id>/` (`mod.xml`, `intents.xml`, `assets/`). They are always loaded, first, are
not listed on the mods screen and never stored in a profile; everything else about them is a mod's: the id that owns
their intents, settings, systems, commands and rule layers, their place in the match set, their asset layers (directly
above the installation, below every other mod), and dependencies on them by id. Game rules stay overridable by name.

| Mod | Side | Holds |
|---|---|---|
| `core.game` | simulation + client | the game's content (it fills the engine's registry from the original's property scripts) and the logic that uses it, systems, `logic.*`, rendering and HUD, and the match networking: it behaves like a server already (lockstep, joining, the referee). `refined` requires it. Its assemblies are the engine's `Sadk.Simulation` (no Godot, namespace `Core.Game` with one sub-namespace per folder, `Core.Game.Village`, …) and `Sadk.Client` (Godot, `Core.Game.Rendering`), so another mod (a map editor) can require core.game and use its renderer. [implemented: the data stage (the original's property scripts, 892 records) and the renderer's entry point; the rest planned] |
| `core.mainmenu` | client | the main menu [implemented as a stub: a column of buttons in the original's Chapter Garamond on a plain colour; the original's menu runs over the lobby map rendered live (`menumain.xml`: `BG_3D`, `campaignName="Main"`), which comes when maps render]; other mods add entries with `core.mainmenu.addmenuitem`. Its assembly: `Sadk.MainMenu` (an assembly of its own: the loader reads a built-in mod's intents and registrations from the assemblies of its entry types, one mod id per assembly) |
| `core.lobby` | client + network | the lobby world only: the traffic while the player is in the lobby (village, chat, rooms); it starts matches through `core.game`'s intents [planned] |

The engine holds the vocabulary every mod builds on [the maintainer's decision
2026-10-15]: the content model (record types, kinds, the `properties` API, §6.3), and the world renderer base with
the shared shaders, global shader parameters and camera actions ([renderer.md](renderer.md) §2.1, the engine asset
layer of [assets.md](assets.md) §5.3a). `core.game`'s client entry point only registers its map layers; a mod adds
layers to maps with `MapLayers.Register` and to other worlds with `WorldLayers.Register(kind, …)`, and disposes the
registration in its `OnUnload`.

`core.game` is the only built-in mod with simulation code, so of the base game it alone enters the match set (§9.1).
Its simulation needs no Godot, so the headless runner loads it (tests, replays, the checksum comparison, a dedicated
host) with its client code left out, as every mod's is there.

The development tools are mods in `mods/`, on by default. `tools.assetbrowser` (requires the built-in `core.mainmenu`)
adds "Asset browser" (a mode) and "Check all assets" (an overlay) to the main menu [implemented]. `tools.mapviewer`
(requires `core.game` and `core.mainmenu`) adds "Map viewer" (the mode `tools.mapviewer.open {map?, overlay?, ontop?,
back?, x?, z?, yaw?, pitch?, distance?}`): every map package drawn by core.game's renderer outside a match, with
switchable overlays of what the map stores (grid bits, resources, deposits, blocking doodads, animals and roam ranges,
spawn points, ship routes, harbours with exits and docks, start and chest positions, ambient sounds, continents,
patterns; optionally through the hills), their legend and an inspector of the cell under the mouse [implemented,
sadk-remake 7cb8012]. It builds against core.game's Godot assembly (`Sadk.Client`).

`core.game` adds "Free game" (`!FREE GAME`) to the main menu the same way: a listener in its `intents.xml` on
`engine.start` emits `core.mainmenu.addmenuitem`. Its `mod.xml` names `core.mainmenu` as an `Optional`
dependency, which orders the two built-in mods; the load order is `core.mainmenu` → `core.game` → every other mod
(`tools.assetbrowser`, `tools.mapviewer`, …) [implemented, sadk-remake 636da4c; the screens in [sim-boundary.md](sim-boundary.md) §6.16].

### 11a.2 Modes, overlays, handlers, events, listeners, routes [implemented]

An **intent** is a request as plain data: a key and named parameters of type `string`, `int`, `float` or `bool`
(`core.lobby.world { frommatch: true }`). Plain data, because an intent may cross a mod-set reload, arrive over the
network or be logged; nothing of a mod travels in it. Godot signals are not used for this: they bind to live objects,
which would keep an unloaded mod's code alive (§9.3). Every intent is declared once, as one of four kinds:

| Kind | Answers its own id by | Example |
|---|---|---|
| **mode** | replacing the current mode: exactly one at a time (the main menu, the lobby world, a match). Pause or option menus are UI inside a mode | `core.mainmenu.main` |
| **overlay** | opening over the current mode. It belongs to that mode and closes when the mode is left, unless declared `keep`; a `modal` one gets a shade that takes the input below. Emitting an open overlay's id again calls `Reopen` instead of opening a second one (a minimized setup window comes back); minimizing is the overlay's own business | `tools.assetbrowser.check` |
| **handler** | running code, without a view and without leaving the mode: a command with one doer | `core.mainmenu.addmenuitem` |
| **event** | nothing: it announces that something happened; **listeners** react to it | `engine.start`, `core.game.matchended` |

A **listener** reacts to an event, when its condition holds (`when="type=network"`, `name=value` or `name!=value`,
several joined by `;`), by emitting one intent: the event's parameters that the target declares, plus constants
(`<Set>`). A listener written in C# runs its method instead, which may return the intent to emit. Whether that intent
switches the mode or runs a handler follows from its declaration. Its `id` is optional: it only lets other mods and
reports name it. A **route** sends an intent of a mode, overlay or handler somewhere else (one winner per key; events
are not routed, they are listened to).

**Two equal forms.** A mod writes its intents as C# attributes, in its `intents.xml` (at the top of the mod, next to
`mod.xml`), or both; a Lua form (registration calls) is [planned]. The loader turns the attributes into elements of the
same document, so both merge, patch and validate the same way; the same id twice within one mod is a load error.

```csharp
// core.mainmenu
[assembly: On("engine.start", Id = "core.mainmenu.boot", Emit = "core.mainmenu.main")]

public sealed class MainMenuMod : IClientMod                // the entry point keeps the menu's entries
{
    [Handler("core.mainmenu.addmenuitem")]
    void AddMenuItem(MenuItem item) { … }
}
public sealed record MenuItem(string Id, string Text, string Emit, string? Params = null, int Order = 100);

[Mode("core.mainmenu.main")]
public sealed class MainMenuMode : Mode                     // a new object per entry; the constructor asks for
{                                                           // the entry point and the mod's context
    public MainMenuMode(MainMenuMod mod, ModContext ctx) { … }
    public override object? Enter(Intent intent) => new MainMenuView { … };   // a node type of the mod's own
}

// tools.assetbrowser
[Overlay("tools.assetbrowser.check", Modal = true)]
public sealed class CheckOverlay : Overlay<CheckParams> { … }
public sealed record CheckParams(bool Quit = false);       // the record's constructor is the parameter list
```

```xml
<!-- tools.assetbrowser: intents.xml (pure wiring, so written as data) -->
<Intents>
  <Listeners>
    <On id="tools.assetbrowser.menu.check" event="engine.start" emit="core.mainmenu.addmenuitem">
      <Set name="id" value="tools.assetbrowser.check"/>
      <Set name="text" value="Check all assets"/>
      <Set name="emit" value="tools.assetbrowser.check"/>
      <Set name="order" value="110"/>
    </On>
  </Listeners>
</Intents>
```

The whole document has six groups; a mode, overlay or handler written in XML names its C# code (`class=`,
`method="Namespace.Type::Method"`), and the declared parameters must match the code's record (the drift check):

```xml
<Intents>
  <Modes><Mode id="mod.screen" class="Mod.ScreenMode"><Param name="map" type="string" required="true"/></Mode></Modes>
  <Overlays><Overlay id="mod.panel" class="Mod.Panel" modal="true" keep="false"/></Overlays>
  <Handlers><Handler id="mod.count" method="Mod.Entry::Count"><Param name="by" type="int" default="1"/></Handler></Handlers>
  <Events><Event id="mod.done"><Param name="ok" type="bool"/></Event></Events>
  <Listeners><On id="mod.afterMatch" event="core.game.matchended" when="type=network" emit="mod.screen"><Set name="map" value="x"/></On></Listeners>
  <Routes><Route key="other.screen" to="mod.screen"/></Routes>
</Intents>
```

Attribute forms: `[Mode]`, `[Overlay]` on a class deriving from `Mode`/`Mode<TParams>` or `Overlay`/`Overlay<TParams>`
(`Replaces = "…"` adds a route to it); `[Handler]` on a method taking nothing, an `Intent` (any parameters) or a
record; `[Event]` on the record an event carries (`Intents.Emit(new MatchEnded(…))`); `[On]` on a method or on the
assembly (pure wiring, `Emit` and `Set = new[] { "name=value" }`); `[Route(key, to)]` on the assembly. A record's
constructor parameters are the declared parameters (names in lower case, compared without regard to case); one without
a default that is not nullable is required. Modes and overlays are made new for each entry; handler and listener
methods run on the mod's one object of their class (the entry point when it is that class). Constructors may ask for
the mod's `ModContext`, `IntentEmitter`, `VirtualFileSystem`, `AssetCache`, entry point or another class of the mod.

### 11a.3 Rules [implemented]

- **Merging.** Each mod's attributes and `intents.xml` make one document of that mod. The mods' documents are merged
  in load order: a later mod's listener of the same `id` or route of the same `key` replaces the earlier one, and
  `remove="true"` takes it away. Then patches apply as to any presentation document (`<Patch file="intents.xml">`,
  §6.6), so a data-only mod can change even an attribute's listener (`SetAttribute` on its `when`, say).
- **Namespaces.** A mod declares modes, overlays, handlers and events only under its own id (`core.game.*` belongs to
  `core.game`); a listener with an id outside its namespace must replace an existing one. `engine.*` is the game's:
  `engine.start` (event, emitted after the mods load and by the mods screen's "Back"), `engine.quit { code }`,
  `engine.close { overlay }`, `engine.mods`, `engine.shell { reason }`, `engine.language { code }` (switches the
  text language, [assets.md](assets.md) §8), `engine.options { tab? }` (the Options screen, a modal overlay the game
  hosts; core.mainmenu's "!SETTINGS" entry and the map view open it, [renderer.md](renderer.md) §19).
- **Dependencies.** A mod whose listener or route emits another mod's intent names that mod among its dependencies
  (`tools.assetbrowser` requires `core.mainmenu`, `tools.mapviewer` requires `core.game`, whose renderer it uses), else a warning; the version range is the contract's version. Mods
  share no types: another mod's intent is emitted as a key and plain data, never with its record.
- **At load** (step 8): problems in a mod's own declarations are errors (the set does not load): a declaration
  without code, a class or method not found, a parameter list that differs from the record, a namespace broken, an id
  twice. A listener or route that names an intent nobody declares is a warning and is left out. `validate-mods`
  prints the table; a headless run does not load client code, so the ids of mods with client code are not checked
  there.
- **The bus.** `Emit` only queues; the game processes the queue once a frame, so a mode switch never happens inside a
  button's own signal. An undeclared intent, a missing required parameter or a value of the wrong type drops the
  intent with an error naming the emitter; an undeclared parameter is a warning. Of the intents one event's listeners
  produce, all handler and overlay intents go on, but only **one mode switch**: a conditional listener's beats an
  unconditional one's, a later listener's an earlier one's; the overruled ones are logged. A mode switch closes the
  overlays that belong to the mode and leaves it (`Exit`) before the next enters. A mode or overlay whose code throws
  is logged; a mode that fails falls back to `engine.shell`, as does an `engine.start` that enters no mode. A handler
  or listener that throws is logged and the rest goes on. More than 256 intents in one frame wait for the next; a queue
  sixteen times that is dropped as a loop.
- **Unloading.** Before the mod set unloads (§9.3) the bus closes the mods' overlays, leaves a mod's mode (the game's
  own `engine.mods` stays) and drops everything of the mods; the game frees their views at once, so the leak check
  finds nothing.
- **The game's options** for unattended runs: `--emit=<key>[?name=value&…][;…]` once the start has settled,
  `--press=<button text>[;…]` presses buttons as the player would, `--trace-intents` logs every intent and where it
  went, `--shot=<png>` once the intents have settled.

## 12. Examples

| Goal | Level | How |
|---|---|---|
| The brewery also makes yeast | 1 | `data-updates.lua`: `registry.get("building","brauhaus").Production.Output["yeast"] = 1`, plus a `good` entry for yeast with its gfx name and a visual descriptor |
| Higher-resolution tree textures | assets | files at the same logical paths in `assets/`; client-only, no effect on multiplayer |
| A brewery panel shows its yeast stock | 2 | a component `YeastStockDef` implementing `IInspectable`; its section appears in every panel that shows the component |
| Settlers avoid swamps when pathfinding | 3 | Harmony prefix on the pathfinder's cost function in a simulation assembly; simulation mod |
| A new campaign | maps | map packages under `maps/`, with scripts using `logic.*` and the mod's `scripts/` library |
| An existing sadkmod property mod | 1 | its `scripts\properties\*.lua` as `data-updates.lua`, unchanged |

## 13. Open decisions

1. Decided 2026-10-15 (instead of the draft's restart): unloading in the process, with the leak check (§9.3).
2. Decided 2026-10-27: a mod defines registry entries in C# or in XML definitions (RimWorld style; an entry names
   a parent by key, `parent="woodCutter"`, and states only what differs); Lua stays the format of the original's
   property scripts, from which the base game's definitions are converted out of the player's installation (no game
   data is shipped). The converter may write the converted base definitions as XML for reference, generated in the
   player's data folder, never shipped. Unifying the original's per-tribe variants of a good (`stoneBav`/`stoneScots`,
   `pretzel`/`bread`, `halberd`/`claymore`) is deferred: their original ids are in maps, saves, commands and
   checksums, which faithful mode keeps (§6.3; answers [binding] §13 item 1).
3. XML for manifests and every patchable presentation document; JSON only for machine-written files (§3).
4. Decided 2026-10-18: `refined` is a simulation mod shipped with the game; its fixes are game rules switched by
   mod settings (§9.4, §14 item 7).
5. Consent per content hash for received code mods; data-only mods automatic (§7.4).
6. Command ids of mod commands from a name hash (§6.7) versus a registry assigned at match start.
7. Confirm that the original's simulation reads no value from the settings XML (§8.3).

## 14. TODO: a mod-friendly engine [the maintainer's priority 2026-10-18]

Modding is the remake's top priority (`../remake-architecture.md` §1). Today the engine is mostly a data store
(definitions, registry, property scripts) and a rendering base; the game's behaviour is closed code inside core.game.
State of `sadk-remake` a923aeb:
- `BuildingDef` is a flat port of the original's `BuildingProperty`; the component model of architecture §5
  (`ComponentDef` on the type, `ComponentState` per instance, capability interfaces) is not built.
- What a worker does is chosen by `Production.WorkingMode`, the original's 12 modes, dispatched by `switch`
  statements in core.game (`Settlers/WorkerJobs.cs`, `GathererJobs.cs`). A mod cannot add a mode.
- Placement (`Village/VillageSystem.Placement.cs`) has no rule a definition or a mod can add.
- The generic building panel (`IInspectable`, `<ComponentSections/>`, §6 of the architecture) is not built.
- What does exist: mods add `SimSystem`s by position (`[SimSystem(After, Before)]`) with their own checksum and save
  data, entries through the data stage, and Harmony on anything.

**Acceptance scenario: the Salzfeld** (the maintainer's proof of concept, 2026-10-27). A Bavarian building with the
Oxen Breeding's model (`Bavarian_Donkeybreeding`, `PB_B_Cowbreeder01`), placed only near a shore. Its worker, the
plain building helper (`good_buildingHelperBav`), walks to the water, waits there a moment (the pick-up clip stands in
for fetching water, which has no clip of its own), walks back, works for a while and then produces the Bavarians' salt
(`saltBav`, which the pretzel needs). It is very slow on purpose (balance): a cycle takes many times a salt mine's
333 + 55 ticks. It must be possible as **one small mod without Harmony**: an XML definition, one behaviour class, a
presentation patch, no client code. It goes into the SDK as the example mod and into the tests. The evaporation slots
and their panel rows of the first draft wait for components and panel sections (items 1 and 4).

Work, in this order:
1. **Components on types.** `ComponentDef` / `ComponentState` with `Tick`, `Save`, `Load`, `WriteChecksum`, attached to
   building types (later settlers, map objects); state saved and checksummed by the engine, not by each mod.
2. **Placement rules.** A list of rules on the building definition (distance to water, terrain, neighbours, …) that the
   site check runs and that build mode shows, so valid sites appear without renderer code.
3. **Named work behaviours.** The 12 original modes become registered behaviours (faithful mode keeps the original's
   code and order); `Production.Behaviour` names one; a mod registers its own. The original's job steps (walk to a
   cell, search a water or resource cell, play an animation, carry, take from and put into a building) become a step
   library behaviours are built from.
4. **Panel sections.** `IInspectable` components bring their rows and buttons into the building panel.
5. **Audit core.game for closed dispatch.** Every `switch` on a type, mode or kind enum is a candidate seam; each one
   becomes a registry or stays, with the reason written down.
6. **Move the mechanisms into the engine.** The frameworks of 1 to 4 live in `Sadk.Engine` (simulation side) and
   `Sadk.Presentation` (panels, build-mode display); core.game keeps the original's content and behaviours.

7. **Game rules** [implemented, sadk-remake cc7eb02]. The engine (`Sadk.Engine.Simulation`) declares decisions of
   the simulation as rules: `[GameRule("area.decision")]` on a small interface whose query is a readonly record
   struct of engine vocabulary. Implementations are `[Rule]` classes in simulation assemblies, found like systems. A
   parameterless constructor replaces the layer below; a constructor taking the rule interface wraps it. The mod load
   order stacks them, within a mod by class full name. `[Rule(Setting = "x")]` names a bool startup setting that
   switches an implementation off. Wrong shapes are load errors naming the mod (no rule interface or two, a bad
   constructor, a wrapper with nothing below it, one rule name used twice).
   - The set is resolved once per mod set, after the settings stage (`SimulationCatalog.Rules`, `World.Rules`,
     `IWorldView.Rules`); systems take each rule once, so a call costs one interface call.
   - Rules are pure functions of their query: no match state, no randomness, no state of their own. So the
     presentation may evaluate them, and the simulation thread needs no lock. Numeric parameters read from settings
     are a later extension.
   - core.game implements every base rule as the original, with addresses (`Core.Game.Rules`,
     `Simulation/Rules/OriginalRules.cs`).
   - Saves (remake part v3) and command logs (format 6) record each rule's layers with the rest of the match identity
     ([sim-boundary.md](sim-boundary.md) §9.1); a load or replay with other rules warns. The rule set's fingerprint enters the world checksum and state hash only when a rule has more than one
     layer, so compatibility mode's checksum is the original's.
   - Mods may declare rules of their own under their id.
   - First rules: `production.productAmount` (`GetEntryWithModifiers` S 00661c50 with its literal-`corn` compare at
     S 00661c6f, `ApplyAmountDoubling` S 00663450; read by `DeliverProducts` S 00565990, `PutDownPackage::Update`
     S 0077a8e0 and the buff in `Building::Update` S 006abcf0) and `transport.groupMembership` (`SelectByArrangement`
     S 00652b70 → `ReleaseId` S 005c3220, from `SelectOrderForNode` S 00652e00; groups from `InitFromTribe`
     S 005c1370, entries by `AddEntry` S 005c38a0).
   - Further seams in core.game, candidates for rules: the work behaviours' `switch (WorkingMode)` (item 3); the
     sacrifice effects (`ApplyOwnEffect` S 006630b0); which production modes are speed-scaled (S 00565ed0); the
     initial group membership (`InitFromTribe`) and `ArrangementGroup.PickNext` S 005c30c0; the stock-and-age score
     (S 00651330, factor 10); `DefaultBuildingType` S 00533b20; the literal-id good rules in `GoodRulesDef`
     (TimedWhileWorked, FreeDepositNeedsNoTimer, StreetCarrier, GroundResourceOnWater, FoundOnBuildableGround).

Constraint: in compatibility mode the registered original behaviours run in exactly the original's order with the
original's random draws, so the checksum against the original holds; a mod that adds a behaviour makes the match
remake-only (§9.4).

### 14.1 The first slice [decided 2026-10-27; planned]

Items 2 and 3 with the Salzfeld as the first user (migration steps 1 and 2 of the data-driven concept: the frameworks
in the engine, core.game's behaviours wrapped coarse and faithful; splitting them finer comes later).

- **Named work behaviours.** A work behaviour is an engine contract (`IWorkBehaviour`, `[ModApi]`) registered by name
  in a `NamedRegistry` owned by the simulation catalog, so a mod adds or replaces one (replacing a base behaviour
  makes the match remake-only, §9.4). `BuildingDef.Production.Behaviour` names one; when a definition names none, the
  original's working mode gives its base name (`work.foresting`, `work.mining`, `work.farming`, `work.fishing`,
  `work.settlerBreeding`, `work.catapult`, `work.producing`, `work.hunting`, `work.idling`, `work.sacrifice`,
  `work.animalBreeding`, `work.scholar`). The contract has the decision points the original's worker passes through
  (choose the next work, update the work state, release the product, the progress shown) and the properties other
  code asks of a mode today (the production-speed scaling of `GetProductionDuration` S 00565ed0, the mine test, the
  animal cap, the transport handover's gatherer test, and the presentation's choice of the info box, `BuildingKind`,
  which tests the sacrifice, mine and scholar modes, read through a view). core.game's 12 behaviours are today's `switch` branches moved
  as they are (`ChooseNextWork`, `UpdateWorkState`, `UpdateRelease`, `StartGathering`, `UpdateGathering`,
  `FinishWorking`, `Worker.WorkProgress`, `Production.Duration`/`IsMine`/`CanStart` and the other mode tests), with
  their addresses; `BuildingWorkingMode` stays the original's data value. Proof: every match test's checksums and
  saves are byte-identical before and after.
- **The step library** for new behaviours: a job is a list of steps over the worker: `Find` (a target by a query),
  `WalkTo`, `Act(kind, ticks)` (an action timer; the presentation picks the clip of the action kind, as for the
  original's settlers: handling-second-half shows `Pickup`, work shows `WorkLoop0`), `Carry(good)`, `Deliver`,
  `Produce`. A job saves as its behaviour's name, its step index and its targets, and is rebuilt on load. Steps use
  integers and the simulation's random generator only. The simulation never names a clip.
  A job's cycle time is the sum of its steps (the `Act` ticks, and the walks once `Find` has a target, by path length)
  and its progress is the share of that sum done, so a step-built behaviour needs no `ProductionTime`: the ticks are
  its parameters, given on the definition (`<Behaviour use="salzfeld.saltWork" fetchTicks="30" workTicks="3500"/>`;
  parameters are read by the behaviour, not by the engine). A behaviour that is speed-scaled has the production-speed
  factor of S 00565ed0 applied to its `Act` ticks. The base behaviours keep the original's data and formulas
  (`ProductionTime` as the producing timer; the gatherers' fixed progress per stage, S 0077d1f0).
- **Placement rules** [implemented, sadk-remake r3-defs]. `BuildingDef.Placement.Rules` lists rules by name with
  parameters (data: `SlotUse`, a name and its parameters as an ordered string map, the type behaviours take too; the
  section is `[OmitWhenEmpty]`, so the base records' canonical form and the registry checksum stay the original data's).
  A rule is the engine contract `IPlacementRule` (`Sadk.Engine.Simulation`, beside the world and map views it reads),
  registered with `[PlacementRule("name")]` in a simulation assembly into the catalog's `NamedRegistry`
  (`SimulationCatalog.PlacementRules`; a later mod's registration of a name replaces the earlier one, and the registry
  goes with the catalog when the set unloads). `GameQuery.CanPlaceBuildingTypeAt` runs a type's rules after the
  original's tests, so the place command and an upgrade see them; build mode asks them through the placement view
  (`IBuildingPlacementQueries.PlacementRulesAllow`) for the cursor's mark and the build menu opened at a cell, while
  the overlay stays the cell's construction flags (the original's icon is the cell's alone, S 006b36d0). A rule name
  no loaded mod registers, or parameters the rule refuses (`CheckParameters`), is a load error naming the building.
  First rule, core.game's `placement.nearWater(distance)`: a shore cell (`GridBits.Shore`) within the distance over
  walkable ground from the entrance cell (anchor + direction 1), the fisher's flood fill without its fish test
  (`GroundResources.SearchShore` / `NearestShoreCell`, shared with `FindFishingSpots`).
- **XML definitions** [implemented, sadk-remake r3-defs]. A mod's `defs/*.xml` (root `<Defs>`, files in ordinal name
  order) are read in each sub-stage after the mod's C# part and before its Lua file: in the definitions stage an
  element per entry kind (`<Building key="…" parent="…" type="…">`, element names matched to the kind names without
  case) defines an entry; in the updates stage `<Update kind="…" key="…">` changes an existing one in the same form.
  Attributes and children are the definition's members by name (without case), mapped with the registry's own walker,
  so a mod's subclass fields work too (`type` names a definition class of the engine or of the simulation code of the
  mods loaded so far). Scalars and references are attributes or text (a typed reference is a key, an untyped one
  `kind:key`, empty text is none); a section is a child changing only what it states; an immutable record
  (`GoodAmount`) is built from its constructor's parameters, the unstated ones kept from the value it replaces; a
  list's children (`<Item>` by convention) replace its items, `<Add>` children append by the list's own rule and
  `<Remove>` children remove the items matching what they state; a map is the same with a `key` attribute per child;
  an element mapped to a `SlotUse` takes `use` and its parameters as attributes. `parent` makes the entry a deep copy
  of an entry defined before it (any mod's), then applies the element. Every reference must name an entry by the end of
  the mod's XML of the sub-stage. Errors (an unknown kind, member, entry or key, a bad value, a parent not defined yet)
  are load errors naming mod, file, line, entry and member path. The Salzfeld adds itself to the Bavarians' buildings
  with an `<Update>`.
- **The Salzfeld mod** (`src/Mods/Salzfeld`, also the SDK's example): `defs/salzfeld.xml` (the building, parent
  `oxenBreeding`, its own key `salzfeld.saltworks`, no produced settler, product `saltBav`, behaviour
  `salzfeld.saltWork`, placement `placement.nearWater`, an `<Update>` adding it to the Bavarians' buildings), a
  `patches/` entry adding its descriptor `Bavarian_<gfx>` (a copy of `Bavarian_Donkeybreeding`) to `buildings.xml`, and `SaltWork`: find a shore
  cell near the building, walk there, `Act` the handling kind for a moment, walk back, `Act` work for a long time,
  produce one salt. Acceptance: placed only near water; one cycle seen in a headless match; a save in the middle of a
  cycle loads and finishes it; the base game's checksums unchanged with the mod off.

The Salzfeld's panel is the original's production info box, chosen from its data (a product with a stock); a
building's own panel is presentation, keyed by its key, never part of the definition.

A follow-up on the step library: the built-in behaviour `work.steps` runs a linear step list given in the definition
(`<Work use="work.steps">` with `<Find>`, `<WalkTo>`, `<Act>`, `<Produce>` and an `<Otherwise>`), so a job without
decisions needs no code; a behaviour that decides (between targets, on counted state) stays C#, as RimWorld's job
drivers do.

Open after the slice: components with their own state (item 1, the evaporation slots), panel sections (item 4), the
other closed dispatch (settler classes, sacrifice effects, victory conditions, info boxes, actions, HUD widgets), and
splitting the base behaviours into steps.

