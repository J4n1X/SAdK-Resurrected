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
- Mods bring precompiled assemblies loaded through `AssemblyLoadContext`, or C# sources that the game compiles with
  Roslyn when the mod loads (source mods, §7.5); JIT runtime, no NativeAOT. Mods may define their own Godot node types
  (maintainer, 2026-10-15, §7.1); moddable UI comes as `IInspectable` descriptions and XML layouts.
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
  src/                        C# sources the game compiles (source mods, §7.5); any folder the manifest names
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
| simulation / client sources | as the assemblies | compiled into one assembly per declared folder (§7.5) |
| `data/*.lua` | yes | registry changes. `settings.lua` only declares settings |
| `assets/` | no | presentation only; the simulation never reads an asset (§8.3) |
| `patches/` | no | patch presentation documents only |
| `scripts/` | yes | run inside the simulation when a map script requires them |
| `assets/maps/` | per map | a map is compared and transferred as a map, not as part of the mod set; an overlay folder that changes a map's `world/` or `script/` changes that map (assets.md §5.6) |

Whether a mod changes the simulation is read from its contents [implemented 2026-10-15]: a simulation assembly or
simulation sources, a data-stage script (`data/data.lua`, `data/data-updates.lua`, `data/data-final-fixes.lua`) or a `scripts/` library
makes it a simulation mod; `mod.xml` has no flag for it. The registry checksum (§6.5) catches anything the contents
miss.

The built-in mods (§11a) have this layout too, without `bin/`: their data is in `<game folder>/base/<id>/` (in the
source tree `src/Base/<id>/`), their code is the game's own assemblies, which their `mod.xml` names by file name
under `<Assemblies>` (`<Simulation>Sadk.Simulation.dll</Simulation>`) and the loader finds in the engine's load
context [implemented]. `core.game`'s `assets/` holds the remake's own files (shaders, the remake's
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
- **Assemblies**: the entry assemblies per side; their private dependencies sit next to them in `bin/`. A source mod
  names folders of C# sources instead (`<SimulationSources name="BreweryYeast">src/</SimulationSources>`,
  `<ClientSources>`, §7.5); a mod may have both kinds.
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

- a mod received from a peer (§9.2) that contains code (assemblies or source parts) is loaded only after the player
  confirmed it (mod id, version, content hash, which peer sent it); the confirmation is remembered per content hash;
- source mods (§7.5) have the same full trust as built ones: the compiler gives no sandbox, and the compiled code runs
  like any mod's;
- data-only mods (no assemblies, no source parts) can be accepted automatically, as today's `AcceptServerMods=true`;
- Lua is sandboxed: no `io`, `os`, `debug`, `loadlib` ([lua.md](lua.md) §2.4).

### 7.5 Source mods [implemented 2026-10-27]

A mod may ship its C# as plain `.cs` files: no project, no build step, no SDK. The game compiles them with Roslyn when
the mod loads and loads the result like a built assembly (§7.1, §7.2): the mod's collectible context, its entry
points, unloading with Harmony unpatching and the leak check (§9.3) are the same.

- **Manifest.** Under `<Assemblies>`, `<SimulationSources name="Salzfeld">src/</SimulationSources>` and
  `<ClientSources name="Salzfeld.Client">src/Client/</ClientSources>`. Each element is one assembly named `name`
  (`A-Z a-z 0-9 . - _`; by default the mod's id, for a client part the id with `.client`) of the `.cs` files below its
  folder, a folder inside the mod, except those below a deeper folder another part names and those below a `bin/` or
  `obj/` folder (an editor's build output). The parts of a side load after its assemblies and may use them;
  simulation code loads before client code, so a client part may use the mod's simulation parts. Simulation sources
  make the mod a simulation mod (§2).
- **The compiler** (`Sadk.Engine.Mods.SourceCompiler`): Microsoft.CodeAnalysis.CSharp 4.12.0, the newest line that ships
  a net8.0 build, about 9.5 MB in the export's `data_` folder. A part compiles as the SDK's `Mod.props` builds a
  project: net8.0 and C# 12, nullable on, the SDK's implicit usings and preprocessor symbols, release optimisation,
  `CS1701`/`CS1702` off, deterministic.
- **References**: what a built mod's references resolve to when it loads (§7.1): the running runtime's assemblies;
  `Sadk.Engine`, `Sadk.Formats`, `Sadk.Lua`, `Sadk.Session`, the base game's `Sadk.Simulation` and HarmonyX; for a client
  part also `Sadk.Presentation`, `Sadk.Client`, `Sadk.MainMenu` and GodotSharp; the code of the mods it depends on
  (the dependency rule of §7.1; a simulation part sees only their simulation code); the mod's own code loaded before
  it; the libraries in the mod's `bin/`. A simulation part has no Godot: `using Godot` there is a compile error, which
  the load errors explain with a pointer to client parts; the check of §7.1 still runs on the compiled assembly.
- **Godot node types** in a client part: the game runs Godot's source generators and analyzers (the SDK's
  `sdk/analyzers/Godot.SourceGenerators.dll`, in an exported game's folder and, after a build, in the development game's)
  with the "tools project" properties of §7.1, so a node type gets its bridges and a missing `partial` is Godot's
  `GD0001` error, as in the editor. A game without them refuses a client part that defines a `GodotObject` type, naming
  the type, instead of loading a node whose `_Ready` would never be called.
- **Cache.** The build (dll and portable PDB) is kept in `<user data>/cache/mods/<id>/<name>-<key>.dll`; the key is a
  SHA-256 over the build rules' version, the engine version, the compiler's version, the part's side and name, every
  reference's identity (name and module version id; an image's name and content hash; the runtime as one identity of
  its version, runtime identifier and `System.Private.CoreLib`'s module version id), the analyzers' content hashes and
  every source file's path and content hash. A new engine build, a changed dependency or a changed file therefore
  compiles again; a hit reads two files and never starts the compiler, and a new build replaces the part's older one.
  Measured with the Salzfeld as a source mod (one file; headless `validate-mods`, debug build of the engine,
  2026-10-27): 1.3 s to compile in a fresh process (Roslyn's first use), 6 ms from the cache.
- **Diagnostics.** A compile error fails the mod's load, each error as `[mod] src/File.cs(line,col): error CSxxxx: …`
  among the load errors that the mods screen and `validate-mods` show; warnings go to the log. The symbols carry the
  sources, so stack traces name the mod's files and lines.
- **Multiplayer.** The content hash (§9.1) covers the simulation sources, not the build: the build is deterministic, so
  peers with the same sources on the same game version run the same code. [inferred] Peers on different systems
  compile against their own builds of the same runtime release, whose API is the same; the cache key keeps each
  machine's builds apart.
- **Trust**: full, as for a built mod (§7.4).
- [TODO] A changed file compiles its whole part again (one to a few seconds; no incremental compilation).

The Salzfeld (§14.1) runs its whole cycle as a source mod too: sadk-remake's `SalzfeldTests` copies its package without
`bin/`, with `SaltWork.cs` under `src/`, and checks the same cycle; `SourceModTests` load, patch and unload a source mod
in three rounds (the first compiles, the next two hit the cache) and check the errors.

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
manifest, `data/`, `defs/`, `scripts/`, the simulation assemblies and the libraries in `bin/` (not a declared client
assembly), the sources of the simulation parts (§7.5), and the values of the mod's `startup` settings. Client
assemblies and sources and assets are not covered: client-only differences are allowed. The files' part is
`ModSource.ContentHash` in sadk-remake [implemented 2026-10-27]; the match set (`ModSet.MatchSet`) still names id and
version only, and the hash and the setting values join it with the multiplayer work [TODO].

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
  `src/Sdk/Directory.Build.props`), and `dotnet run` starts the development game through the Godot editor. A mod
  without a project is a source mod (§7.5); the guide's "Source mods" section describes it.
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
mods** (maintainer's decision 2026-10-22): the host names their folders to the mod loader (`ModSource.BuiltIn`),
their data is in `<game folder>/base/<id>/` (`mod.xml`, `intents.xml`, `assets/`), and their `mod.xml` names their
assemblies. Only where their code comes from differs from a mod's: the loader takes the assemblies of those names from
the engine's load context (compiled with the game, never collected, no source parts) instead of a collectible context
of their own; from there they take a mod's path, entry points found in each assembly, the check that a simulation
assembly does not reference Godot, intents, systems and commands from their assemblies [implemented]. They are always loaded, first, are
not listed on the mods screen and never stored in a profile; everything else about them is a mod's: the id that owns
their intents, settings, systems, commands and rule layers, their place in the match set, their asset layers (directly
above the installation, below every other mod), and dependencies on them by id. Game rules stay overridable by name.

| Mod | Side | Holds |
|---|---|---|
| `core.game` | simulation + client | the game's content (it fills the engine's registry from the original's property scripts) and the logic that uses it, systems, `logic.*`, rendering and HUD, and the match networking: it behaves like a server already (lockstep, joining, the referee). `refined` requires it. Its assemblies are the engine's `Sadk.Simulation` (no Godot, namespace `Core.Game` with one sub-namespace per folder, `Core.Game.Village`, …) and `Sadk.Client` (Godot, `Core.Game.Rendering`), so another mod (a map editor) can require core.game and use its renderer. [implemented: the data stage (the original's property scripts, 892 records) and the renderer's entry point; the rest planned] |
| `core.mainmenu` | client | the main menu [implemented as a stub: a column of buttons in the original's Chapter Garamond on a plain colour; the original's menu runs over the lobby map rendered live (`menumain.xml`: `BG_3D`, `campaignName="Main"`), which comes when maps render]; other mods add entries with `core.mainmenu.addmenuitem`. Its assembly: `Sadk.MainMenu` (an assembly of its own: the loader reads a mod's entry points, intents and registrations from its assemblies, one mod id per assembly) |
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
1. **Components on types.** Named component types (`IComponentType`) / `ComponentState` with `Tick`, `Save`, `Load`,
   `WriteChecksum`, named by building types (later settlers, map objects); state saved and checksummed by the base game,
   not by each mod (done, §14.2).
2. **Placement rules.** A list of rules on the building definition (distance to water, terrain, neighbours, …) that the
   site check runs and that build mode shows, so valid sites appear without renderer code.
3. **Named work behaviours.** The 12 original modes become registered behaviours (faithful mode keeps the original's
   code and order); `Production.Behaviour` names one; a mod registers its own. The original's job steps (walk to a
   cell, search a water or resource cell, play an animation, carry, take from and put into a building) become a step
   library behaviours are built from.
4. **Panel sections.** `IInspectable` components bring their rows and buttons into the building panel (done, §14.2).
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
   - Further seams in core.game, candidates for rules: the sacrifice effects (`ApplyOwnEffect` S 006630b0); the
     initial group membership (`InitFromTribe`) and `ArrangementGroup.PickNext` S 005c30c0; the stock-and-age score
     (S 00651330, factor 10); `DefaultBuildingType` S 00533b20; the literal-id good rules in `GoodRulesDef`
     (TimedWhileWorked, FreeDepositNeedsNoTimer, StreetCarrier, GroundResourceOnWater, FoundOnBuildableGround).

Constraint: in compatibility mode the registered original behaviours run in exactly the original's order with the
original's random draws, so the checksum against the original holds; a mod that adds a behaviour makes the match
remake-only (§9.4).

### 14.1 The first slice [decided 2026-10-27; planned]

Items 2 and 3 with the Salzfeld as the first user (migration steps 1 and 2 of the data-driven concept: the frameworks
in the engine, core.game's behaviours wrapped coarse and faithful; splitting them finer comes later).

- **Named work behaviours** [implemented, sadk-remake r3-behaviours]. A work behaviour is core.game's contract
  (`Core.Game.Work.IWorkBehaviour`, `[ModApi]`; its members drive core.game's `Worker` at its `Building`, so it is not an
  engine type), implemented through the base class `WorkBehaviour` and registered by name with `[WorkBehaviour("name")]`.
  The mechanism is the engine's: a class with a `[Named]` attribute (the contract's own attribute derives from it) that
  implements one `[NamedContract("registry")]` interface is collected, as rules and systems are, into a `NamedRegistry`
  per contract owned by the simulation catalog (`SimulationCatalog.Named`), owner by owner in load order. A later mod's
  class under a name stands to the earlier one as a rule's implementation does: a public constructor taking the contract
  wraps it (the class gets that object), one without parameters replaces it [implemented, sadk-remake b792f00]; core.game's
  overridable base classes derive from the engine's `StackedPiece<TSelf, TContract>`, whose steps run the piece below
  unless overridden and whose base-game code calls its steps on the uppermost piece, so the steps several mods override
  all take part, as hooks that call the next (replacing or wrapping a base behaviour makes the match remake-only, §9.4). One object
  of each class serves every match of the mod set: a behaviour keeps no match state. `BuildingDef.Production.Behaviour`
  names one with the parameters it reads (a `SlotUse`, as a placement rule: `<Behaviour use="mymod.saltWork"
  workTicks="3500"/>`; left out of the registry checksum while empty); when a definition names none, the original's working mode
  gives its base name (`work.foresting`, `work.mining`, `work.farming`, `work.fishing`, `work.settlerBreeding`,
  `work.catapult`, `work.producing`, `work.hunting`, `work.idling`, `work.sacrifice`, `work.animalBreeding`,
  `work.scholar`; `WorkBehaviourNames`). A type whose behaviour no mod registers is a load error of the mod set naming
  the type. The contract extends the engine's `ISlotUseCheck` (`CheckParameters(SlotUse, Registry)`, the problems of a
  use's parameters and children, none by default in `WorkBehaviour`): `WorkBehaviourNames.Check` runs it for every type
  that names its behaviour when the mod set loads and when a world starts, so a malformed use is a load error naming the
  type's owner, the type and the use, never an exception inside a tick. The contract has the decision points the original's worker passes through (`Start`: step 3 of
  `ChooseNextWork` S 0065d660; `UpdateJob`: the job's states before the worker's own in `Worker::Update` S 0065d7f0;
  `UpdateWork`, `UpdateSecondWork`, `Release`: states 0x1d, 0x1e, 0x24; `BringOutFinished`; `WorkActionKind` and
  `FinishWorking`: `NMovie::Working` S 0077eda0 / S 0077ebf0; `ProductGood`: `PickupProduct::Start` S 00777f80;
  `Progress`: `GetWorkProgress` S 0065ce80; `WorkTarget`) and the properties other code asks of a mode
  (`ScalesWithProductionSpeed`: `GetProductionDuration` S 00565ed0; `IsMine(type)`; `LimitsAnimalsInBlock`: S 00565bd0;
  `LinksDeposit`: S 0055bfb0; `HuntsAnimal`: S 0055c050; `PutsDownExtraUnits`: the transport handover's gatherer test,
  S 0077a8e0; `IsSacrifice`; `StartsInWork`: S 0065c710; `WorksAtDeposit`; `IsScholar`). The presentation reads the ones
  it needs (the info box's sacrifice, mine and scholar tests in `BuildingKind`, the minimap's sacrifice mark, the worker
  figure's work object) through the engine view `IWorkBehaviourView.TraitsOf(type)`. core.game's 12 behaviours
  (`src/Sadk.Simulation/Work/`) are the former `switch` branches moved as they were, with their addresses;
  `BuildingWorkingMode` stays the original's data value, which the computer player's port, the definition's validation,
  the product-buff test and the product-amount rules still read. The match identity records the behaviours (form 2, a
  part `Named`) and the world checksum adds their fingerprint only when more than one mod registered, so the base game's
  saves and checksums are the original's. Proof: per-tick checksums, state hashes and saves of sessions with every
  working mode byte-identical before and after.
- **The step library** [implemented, sadk-remake r3-salzfeld]: core.game's `StepBehaviour : WorkBehaviour` (`[ModApi]`,
  `src/Sadk.Simulation/Work/StepBehaviour.cs`), whose subclass plans the worker's `Job` (`Plan(in WorkContext)`, a function
  of the building's definition only) from steps: `Find(query, out target)` (a target cell by an `ITargetQuery`; the
  library's first, `TargetQueries.NearestShore(radius)`, the fisher's shore search from the entrance flag cell, the cell
  `placement.nearWater` tests for), `WalkTo(target)` (out: the worker's `LeaveBuilding`, then `MoveToCell` with the plain
  and then the free-path search, in state 0x1d; `WalkTo(JobTarget.Door)`: the gatherers' `ReturnHome` in state 0x21),
  `Act(kind, ticks)` (the worker's action timer in state 0x1d; the presentation picks the clip of the action kind:
  handling-second-half shows `Pickup`, work shows `WorkLoop0`; the simulation never names a clip), `Carry(good)` (a
  transport package in the worker's hands, `CreateCarriedPackage` S 0064cce0; a walk with it plays the good's carrying
  clip, as a carrier's), `Deliver` (the carried unit into the input stock), `Consume` (the carried unit used up, into no
  stock), `Produce(product)` (units into the output stock as `OnProductionFinished` delivers: the production event, the
  product-amount rule when the good is a product slot, the goods statistic) and `Rest(ticks)` (state 0x23); the steps
  after `Otherwise()` run instead when a step cannot be done (a find without a result, a walk that cannot start). `Start`
  plans the job, puts its state on the worker (`Worker.StepJob`) and runs it to its first step that takes time;
  `UpdateJob` runs it while the worker has it; at its end the job is dropped and the worker rests or idles outside
  (`RestOrIdleOutside`), walking home first when outside. A job's cycle time is the sum of its steps (the `Act` ticks,
  and the walks once their targets are known, a cell of a walk counted as a tick) and `Progress` is the share of that sum
  done (0 in the otherwise steps), so a step-built behaviour needs no `ProductionTime`: the ticks are its parameters,
  given on the definition and read by the behaviour, not by the engine. A behaviour that is speed-scaled has the
  production-speed factor of S 00565ed0 applied to its `Act` ticks (float32, truncated). The productivity statistic gains 0.25
  per production event and loses 0.05 every 600 ticks (`RegisterProductionEvent` S 00538460, `Statistics::Update`
  S 00537ba0): it counts products, and every original building produces well within 3000 ticks, so it reads full while
  it works. A step-built `Produce` registers one event per 600 ticks of its branch's `Act` ticks (at least one),
  counting a long work as the short cycles it stands for; no original building runs a step list, so the faithful mode is
  unchanged. Steps count in integers and draw
  only the simulation's random generator. The job saves (the village's remake section, `VillageRemakeStateSystem`, a
  second record `Remake Work Jobs` v0 after `Remake Buildings`, written only while a worker has a job: per worker in
  building and slot order its id, the behaviour's name, the branch, the step, the step's phase, the timer, the done and
  current cost, the targets) and enters the checksum and state hash only while one exists, so the base game's saves and
  checksums are the original's; a load rebuilds the plan by the behaviour's name and puts the rest back. The worker's own
  record and the walks' movies are saved as for every worker. The base behaviours keep the original's data and formulas
  (`ProductionTime` as the producing timer; the gatherers' fixed progress per stage, S 0077d1f0).
- **Placement rules** [implemented, sadk-remake r3-defs]. `BuildingDef.Placement.Rules` lists rules by name with
  parameters (data: `SlotUse`, a name, its parameters as an ordered string map and its children, an ordered list of
  nested `SlotUse`s, `[OmitWhenEmpty]` so a use without children keeps its canonical form; the type behaviours take too;
  the section is `[OmitWhenEmpty]`, so the base records' canonical form and the registry checksum stay the original data's).
  A rule is the engine contract `IPlacementRule` (`Sadk.Engine.Simulation`, beside the world and map views it reads), a
  named contract (`[NamedContract("placement")]`) registered with `[PlacementRule("name")]` in a simulation assembly on
  the named implementations of the work behaviours (`SimulationCatalog.Named`; a later mod's registration of a name wraps
  or replaces the earlier one, the registry goes with the catalog when the set unloads, and a match records a mod's rules
  with the other named implementations, each name's stack bottom first). `GameQuery.CanPlaceBuildingTypeAt` runs a type's rules after the
  original's tests, so the place command and an upgrade see them; build mode asks them through the placement view
  (`IBuildingPlacementQueries.PlacementRulesAllow`) for the cursor's mark and the build menu opened at a cell, and the
  computer player's site test (`SearchConstructionPlace.FitsCellFlags` S 0052eab0, its candidate scan and its re-check
  before placing) asks them after the original's flags test, while
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
  an element mapped to a `SlotUse` takes `use` and its parameters as attributes and its children as child elements (each
  child named by its element, its attributes its parameters, recursively; `SlotUse.Source`, not walked by the registry,
  keeps the file and line for the load's errors). `parent` makes the entry a deep copy
  of an entry defined before it (any mod's), then applies the element. Every reference must name an entry by the end of
  the mod's XML of the sub-stage. Errors (an unknown kind, member, entry or key, a bad value, a parent not defined yet)
  are load errors naming mod, file, line, entry and member path. The Salzfeld adds itself to the Bavarians' buildings
  with an `<Update>`.
- **The step list** [implemented, sadk-remake r4-steps]: core.game's built-in behaviour `work.steps` (`StepListWork`,
  `src/Sadk.Simulation/Work/StepListWork.cs`), a `StepBehaviour` whose `Plan` reads the definition's
  `Production.Behaviour` children in order, one `Job` builder call each, so a linear job without decisions needs no code:
  `<Find shore="n|radius"/>` (a query of the step library named by the step's one parameter, its value the argument;
  `shore`: `TargetQueries.NearestShore`, `radius` the building's `WorkingRadius`; the queries are a list over the step
  library's own, and a job that needs another query is a coded `StepBehaviour`, whose `Find` takes any `ITargetQuery`),
  `<WalkTo target="found|door"/>` (the last `Find`'s target, or home), `<Act kind="…" ticks="n"/>` (kinds `handlingFirstHalf`
  2, `handling` 3, `work` 4, `alternativeWork` 5 of `ActionKinds`), `<Carry good="key"/>`, `<Deliver/>`,
  `<Consume/>`, `<Produce good="key" amount="n"/>` (without `good` the building's product, its amount unless `amount` says otherwise;
  with it 1 unit unless `amount` says otherwise), `<Rest ticks="n|rest"/>` (`rest` the building's `RestTime`) and
  `<Otherwise/>` (once, with steps before and after it). Its `CheckParameters` is the same reading, collecting every
  problem: an unknown step, kind, query or good, a missing, malformed or unknown parameter, a step with children, a
  `WalkTo target="found"` without a `Find` before it, a misplaced or second `Otherwise`, each an error
  `[owner] building 'key': work behaviour work.steps: file:line: step n <Step …/>: what is wrong`. The behaviour is
  speed-scaled (`ScalesWithProductionSpeed`, one answer per behaviour as `GetProductionDuration` S 00565ed0 asks it): the
  production-speed factor shortens every `Act`, not the walks and rests. A behaviour that decides (between targets, on
  counted state) stays C#, as RimWorld's job drivers do.
- **Reacting to the game** [implemented, sadk-remake 1cb6bec]: a mod's system subscribes to the world's events in its
  `Start` (`SimSystem.On<T>`, sim-boundary.md §5.2: delivered right after the command or system that emitted them, inside
  the tick) and acts through core.game's `[ModApi]` operations. The first one: `VillageSystem.ChangeType(building,
  type)`, `Building::SetType` S 0055c110 with the hit-point rescale as an upgrade finishes (a type without hit points,
  health 0 as the original's non-military types, takes the new type's health: the original's rescale would divide by
  0 and remove it). The SDK guide's section "Reacting to the game".
- **Per-building recipes and `Take`** [implemented, sadk-remake 1cb6bec]: `ProductionSection.Recipe` (`<Recipe><Item
  Good="water" Amount="1"/></Recipe>`) in place of the product's costs, resolved by `ProductionSection.Inputs()` for
  every reader (`RecipeOf`, the goods arrangement, production on/off, the computer players' needs, the info box's input
  slots, the building tip); empty for every original type and then left out of the registry checksum. The step
  `<Take good="key"/>` (`Job.Take`): a unit from the input stock, requested again at once (as `StartProductionCycle`
  S 005657c0 does with the recipe); none there: the step cannot be done.
- **The Salzfeld mod** [implemented, sadk-remake r3-salzfeld; its worker data only since r4-steps; a simulation
  assembly since 2026-10-28; two kinds since 1cb6bec: the build menu offers `salzfeld.saltworksLandlocked` (no
  placement rule, recipe water, `Take`), and its code (`Salzfeld.cs`, a handler of `BuildingAdded`) turns one placed
  where the coastal type's rules allow into `salzfeld.saltworks` in the tick it was placed] (`src/Mods/Salzfeld`, `Salzfeld.csproj` against core.game's simulation, shipped in the
  game's `mods/` like `refined`; the SDK guide's example of a content mod): `defs/salzfeld.xml`
  (the building, parent `oxenBreeding`, its own key `salzfeld.saltworks` and `Name` (its text key), `GfxName`
  `Saltworks`, working mode `Producing`, no produced settler, product `saltBav`, `IgnoreGoodCosts` (the salt's recipe is
  the salt mine's fish), `StockLimit` -1, `RestTime` 400, `WorkingRadius` 8, placement `placement.nearWater` 6, an
  `<Update>` adding it to the Bavarians' buildings, and its worker as the step list: `Find shore="radius"`,
  `WalkTo found`, `Act handlingFirstHalf 4`, `Carry water`, `Act handling 4` (the original's pick-up, `NMovie::Pickup`
  S 007781e0: the put-down clip, the good in hand, the pick-up clip), `WalkTo door` (with the bucket: `WalkWater`),
  `Consume`, `Act work 3500`, `Produce`, `Otherwise`, `Rest rest`),
  `patches/salzfeld.xml` (its descriptor `Bavarian_Saltworks` in `buildings.xml`: `Bavarian_Donkeybreeding`'s mesh,
  frame and doors without the oxen of its production and their sounds; its build-menu icon in `iconconfig.xml`, the Oxen
  Breeding's) and its texts (`assets/game/language/{en,de}/salzfeld.txt`: "Salt Works", "Salzfeld"). The game's mods
  without code are folders listed in `src/Mods/DataMods.targets` (none at present), which the game's and the tests'
  builds import: it mirrors each into the game's `mods/<id>/` (the export copies that folder as for every mod). The same job as code,
  `SaltWork : StepBehaviour` (`salzfeld.saltWork` with `handlingTicks` and `workTicks`), is the SDK guide's example of a
  coded behaviour and the tests' source-mod variant. Acceptance, in `SalzfeldTests` over the shipped package through the
  loader (MP_2P_ladybird_isle, player 0 Bavarian with god mode): placed only near water; one cycle (the shore cell, kinds 2
  and 3 for 4 ticks each there, the second from tick 92, the water in hand to the door, kind 4 for 3500 inside from tick
  190, the salt at tick 3690, the productivity full), the same from the coded
  behaviour compiled as a source mod; a save in the work phase loads and finishes the cycle tick by tick in step with the
  uninterrupted match; the computer player's site test refuses a site the rule refuses; the base game's registry
  checksum, record, saves and checksums unchanged with the mod off.

The Salzfeld's panel is the original's production info box, chosen from its data (a product with a stock); a
building's own panel is presentation, keyed by its key, never part of the definition.

Open after the slice: components with their own state (item 1, the evaporation slots), panel sections (item 4), the
other closed dispatch (settler classes, sacrifice effects, victory conditions, info boxes, actions, HUD widgets), and
splitting the base behaviours into steps.
A candidate mod for then: congestion-aware routing of packages (the maintainer's idea, 2026-10-27): a named slot
`transport.nextHop` whose base is the original's next-hop cache, wrapped by a mod whose own system keeps the smoothed
load per flag, the reservations and each package's detour budget (saved and checksummed), plus backpressure for
single-path networks.

### 14.2 The second slice [decided 2026-10-27; planned]

Items 1 and 4 (components, panel sections) and the carriers' decision points, on the pattern of the first slice: a
definition names a piece and its parameters (`SlotUse`), an implementation registers by that name on the engine's
named implementations, the base game's code moves into its base implementation unchanged.

- **Components with their own state** [implemented, sadk-remake s2-components]. A definition lists components by name
  with parameters: `Def.Components`, a list of `SlotUse` (`<Components><Component use="brewery.yeast" limit="6"/></Components>`),
  `[OmitWhenEmpty]`, so the base records' canonical form and the registry checksum stay the original data's. The typed
  sections code attaches to a definition (core.game's `GoodRulesDef` and `AiGoodRolesDef`, the rules the original ties
  to literal good ids) are data, not components: they are `Def.Attached` (`AttachedSection`, found by type with
  `TryGet<T>`), written under their old canonical name `Components` (`[CanonicalName]`), so the checksum keeps them as
  before. A component type is the engine contract `IComponentType` (`[NamedContract("component")]`, `[ModApi]`),
  registered with `[ComponentType("name")]`; it checks a use's parameters at load (`ISlotUseCheck`; `ComponentTypes.Check`
  also refuses an unknown name, a name listed twice and components on a definition that is no building) and creates one
  `ComponentState` (`[ModApi]`: `Tick`, `Save`, `Load`, `WriteChecksum`, `WriteState`) per instance from a
  `ComponentContext` (the world, the entity, the use); integers and the simulation's random generator only. Building
  types first (later settlers and map objects). The village of core.game makes the states when a building's construction
  completes (`IComponentType.OnConstructionSite` makes them at placement), brings them in line with the type when it
  changes (an upgrade: kept by name, the new type's made, the ones it lacks dropped) and after a load, removes them with
  the building and hands them to the new building on a change of owner (`TransferBuildingOwnership`). They live on the
  building (`Building.ComponentStates`; a work behaviour reaches them with `job.Building.Component<T>("name")`).
  `VillageRemakeStateSystem` (no new system: the match's systems list is recorded in saves) ticks them right after the
  village's update, building by building in vector order, a building's in its type's order, and saves them as a third
  record of its section, `Remake Components` v0 after `Remake Buildings` and the optional `Remake Work Jobs`, only while
  some building has one: the count of such buildings, per building in vector order its id and its count, per component
  its name and the state's own length-prefixed block, so a load that does not know a component skips it with a warning.
  The same content without the counts of buildings enters the checksum (`WriteChecksum`) and the state hash
  (`WriteState`) only while one exists. With no component anywhere every match's checksums, state hashes and saves are
  byte-identical to before (sp04_hayfield with a god player and 69 buildings, MP_2P_steinfjord with a god player,
  MP_6P_middle_of_nowhere with computer players: per-tick checksums, state hashes every 25 ticks, saves every 500).
- **Panel sections** [implemented, sadk-remake s2-components]. A component state that implements `IInspectable`
  (`[ModApi]`) has a title (a text key) and describes rows: `ComponentText` (a text key), `ComponentBar` (a label, a value
  and its maximum, drawn as `value/maximum` and a bar), `ComponentGood` (a good and a count) and `ComponentButton` (a text
  key and an action id). The simulation evaluates them and the presentation reads them through the view
  `IComponentView.SectionsOf(entity)` (the village offers it), plain records, so the client stays on views
  (ClientBoundaryTests); every building info box part has them as `InfoBoxPart.Sections`. The building info boxes get a
  `<ComponentSections template="componentSection"/>` slot (core.game's `patches/component-sections.xml` adds it to the
  production, mine, catapult, default, store, territory, barracks and construction boxes of `menuingame.xml` and puts the
  section template `componentSection` into `templates.xml`: its margins and line heights as attributes, the elements of
  a title, a text, a value, a bar, a good's picture and a button as children); the box grows by the selected building's
  sections below the original's members and is built again when their shape changes; a box without components looks as
  before. A button sends the core.game command `ComponentAction(Entity, Component, Action)` (`core.game.componentaction`),
  validated and executed by the component type (`IComponentType.Validate`, `Execute`) like any command.
- **The carriers' decision points.** Named contracts in core.game with today's code as the base implementation, moved
  as it is with its addresses and proven byte-identical: `transport.flagAdmission` (may a settler put his package down
  here: `Transport_CarrierTryPlacePackageOnFlag` S 0064dae0, asked by carriers, workers and builders alike),
  `transport.nextHop` (the package's next flag: the search `GetNextHopFlagCell` S 006666d0 that the package's
  one-entry next-hop cache, `ComputeNextHop` S 0064f3a0, and the free packages' return search ask; the cache stays the
  transport's), `transport.choosePackage` (which package a carrier takes: `WaitForPackage` S 0077ac50 with
  `FindBestPackageToCarry` S 0064d7e0, and the exchange choice `FindBestSwapPackageOnFlag` S 0064d2f0), and the street
  carrier's state machine `carrier.street` (`UpdateStreetTransport` S 0065b200) as a carrier behaviour a mod can replace
  or extend: one virtual handler per state, a mod's own states numbered from 0x100. Each base implementation is a class
  with virtual steps; a mod derives from it and registers under the same name. The drop's own stack test
  (`PutDownCarriedPackage` S 0064d590) is not part of the admission: a package admitted to a full flag stays in the
  carrier's hands, so a mod that hands packages over at a full flag does it in a state of its own with the transport's
  link operations. State such a mod keeps (a congestion load per flag, an overflow slot) lives in the mod's own
  system (saved and checksummed by it, §7.2). The base game's carriers do not change.
- **Acceptance.** A test mod gives the brewery (`brauhaus`) a yeast stock component whose section shows in its info box
  (the table of §12: "A brewery panel shows its yeast stock") and whose button empties it by command (done:
  `tests/TestMods/ComponentMod`, `ComponentModTests`: the stock grows while the brewery produces, a save in between loads
  and goes on in step, the mod unloads cleanly); a test mod
  replaces `transport.flagAdmission` and changes where packages wait; with no mod, every match test's checksums and
  saves are byte-identical to before. Then the maintainer's transport ideas (the overflow slot, congestion routing)
  can be built as a mod on these seams.

### 14.3 Info boxes and actions by name [decided 2026-10-27; planned]

The in-match selection's closed sets become open registries, before the panel sections of §14.2 build on them.

- **Info boxes.** What box a selection gets is a name (`MenuSelection.Kind`; the base game's `SelectionKind.*`,
  `core.game.flag`, `core.game.production`, …, one per original kind 0..0x14). An info box type (`IInfoBox`,
  `[ModApi]`; `InfoBox` a ready implementation) gives its layout element (the original's `menuingame.xml` element, e.g.
  `infoboxProduction`, none for the attack slider's kind), its members (`BoxMember`, the constructor's table), its four
  actions by name for a selection (`SetSelectionKind` S 00616f40), its step when chosen (the attack slider's binding),
  its per-frame keep test (the boxes' `Update` closing with `ResetAndRefresh(0)`), whether it chooses again every frame
  (the sacrifice boxes), and its shown instance (`InfoBoxPart`, `[ModApi]`, one per opening): `Update` reads its content
  from the views every frame into its own fields and buffers (no content record per frame), `Build` makes its members,
  `Refresh` writes them through the view, which writes a list or a picture only when it changed. The boxes register by
  name (`InfoBoxes.Register`, a `NamedRegistry`) from core.game's client entry (`OriginalInfoBoxes`, the original's
  boxes moved as they are with their addresses); a mod's registration is owned by its `ModContext` and goes with it. The
  choice stays the original's rule (`SelectionRules.Compute`, `MenuSelection_ComputeSelectionKind` S 006156a0, moved as it
  is) and returns a name; a mod's choice rule (`InfoBoxes.RegisterChoice`) is asked first, the last registered first,
  and gives a name or none to leave the choice to the next rule. Nothing changes on screen.
- **Actions.** An action of the four buttons (`SelectionAction`, `[ModApi]`) has a name (the base game's are the original's
  `g_ActionNames`, `Action_Building_Destroy`, …, which also key the layout's failure texts `<Name>_<code>`), the
  original's number where it has one, its tooltip, its icon cell (or an own picture), red or green, whether it asks for
  confirmation, its availability with the failure code for a selection (`RefreshAvailability` S 00623da0), the typed
  command it sends or its own step (`ExecuteAction` S 00623730), and the action a button shows instead (the swaps of
  6/7 and 15..20). They register by name (`SelectionActions.Register`; `GameActions.Original` the original's 30); a box
  lists its actions by name, and a mod adds an action to any box by name (`SelectionActions.AddToBox`), which takes the
  box's first hidden buttons. No command goes by its hex id through reflection.
- **HUD widgets** [implemented 2026-10-27]. Each widget of the HUD (`HudFrame`, the original's `SetupHud` S 005ed700 reading
  `menuingame.xml`) is a HUD widget (`IHudWidget`, `[ModApi]`) registered by its layout element's name with an order
  (`HudWidgets.Register(element, order, create)`, a `NamedRegistry` of core.game's client, owned by the registering
  mod's context): it builds and wires that element (where it goes, its intent, its hotkey, its per-frame refresh, what
  it takes from the match's records). The frame makes one widget per registered name its layout has, in order (the
  order is the drawing order; the base game's follow `SetupHud`'s attach order); the elements under a widget's element
  are built with it, and an element of the layout's root without a widget is left to its owner (the selection's info
  boxes, the pause bar). The base widgets are the frame's former code moved as it is; a mod adds a widget for an
  element its layout patch adds, or replaces one by name.

### 14.4 TODO after the refactor [the maintainer, 2026-10-27: to be done, not deferred]

The closed dispatch and seams still left after §14.1–§14.3, each on the same pattern (a name with parameters on the
definition, an implementation registered by name, the base game's code moved as it is and proven byte-identical):

- **Settler classes** [implemented, sadk-remake 6f69bbb]: a good names its class (`GoodDef.SettlerClass`, else the base
  class of its `SettlerType`); `ISettlerClass`/`[SettlerClass]`, core.game's six as `settler.*` (the creators of
  S 00656500, the leave rule of S 005ae160, the class destructors S 0065afb0, S 0065a4e0, S 0065e600); a save reads a
  settler back by its profession's class; `NamedSettler` is a mod's base (its own states from 0x100, `[Saved]` state,
  `WalkTo`/`Act`/`GoHome`). Test mod `HeraldMod`.
- **Sacrifice effects** [implemented, sadk-remake 5778b7d]: effects by name (`ISacrificeEffect`, `[SacrificeEffect]`,
  `NamedSacrificeEffect` with `Fire`, `Modify`, `Started`, `Ended`); core.game registers the original's effect types under
  names (`sacrifice.soldierDamage`, … `SacrificeEffectNames`, S 00660960, S 00660500, S 00663560, S 006630b0,
  S 006631e0), a definition names more in `NamedEffects`; a modifier table holds named values a mod's effect sets and its
  rules read; a tribe's `OfferedSacrifices` offer a mod's sacrifice at its temples.
- **Victory conditions** [implemented, sadk-remake 6f69bbb]: `IVictoryCondition` (`[VictoryCondition]`, a stacked piece:
  `Begin`, `IsEliminated`, `UpdateProgress`, `IsReached`, `Progress`, `ShowsProgress`, `UpdateLocalQuest`; S 00535d70 and its
  callees, the scenario's S 0052da20, S 0052da60, S 00535fd0); the original's modes are `victory.endless`,
  `victory.destroyAllEnemies`, `victory.conquer`, `victory.coin`, `victory.scenario`, and the rule `victory.condition` names
  a match's condition from its win condition number. Test mod `HillMod` (hold the hill). Open: naming a mod's condition in
  `MatchSetup` and the lobby (a mod's condition is chosen today by its startup setting through the rule).
- **Soldier kinds as data** [implemented, sadk-remake 6f69bbb]: `SoldierSection.Reach` (`OfKind`, the default, `Melee`,
  `Ranged`); `IsRanged` keys the soldier's own fighting (S 007798d0, S 00779980, S 005721a0, S 005735b0, S 00576b80,
  S 00570c90, S 00572060); the kind's index stays for the MilitaryConfig table, a building's garrison kind and its toggle,
  the fight's per-kind counts and groups, where two kinds remain fixed.
- **Replaceable systems and command handlers** [implemented, sadk-remake cfd8337, 6bcb4f4]: `[SimSystem(Replaces = "…")]`
  takes a system's slot in the tick (the replaced system keeps its state, operations, save section and checksum; one
  replacement per system, a later mod replaces the replacement); command handlers by command id (`ICommandHandler`,
  `[CommandHandler("<command id>")]`, a named implementation over the record's own `Validate`/`Execute`, stacked as every
  named piece; `CommandHandler<T>` for one command type; the command record stays data).
- **Combat and AI formulas as rules**: strike value, hit chance, reach, the attack decision and the strength estimate
  as named game rules (`MilitarySystem.Combat`, `AiPlayer` scoring), like `production.productAmount`. The sword group's
  superiority is one [implemented, sadk-remake 5778b7d]: `military.groupSuperiority` (S 005735b0), its query carrying
  the striker's owner and the sacrifices' view. The computer players' are [implemented, sadk-remake 6f69bbb]: `ai.attack`
  (S 005a0dd0; the mode's draw stays with the attack execution), `ai.strength` (S 0059e6c0, S 0059f0b0), `ai.goodPriority`
  (S 00554bc0), `ai.producer` (S 005936e0, S 00592c40); a mod's building is built through `ai.Want(good)` (S 0058d370) and
  those rules. Open: the AI's role finders and its scoring by working mode (a building-role section like `AiGoodRolesDef`
  when a mod needs one), the build order's stages. The strike is [implemented, sadk-remake 5e5ea68]: `military.strike`
  (`IStrikeRule`: `HitThreshold` S 007798d0, the query carrying the opponent's blocking chance as well as the striker's;
  `StrikeValue` S 005721a0; `Damage` S 00659260, a projectile's too); a mod's own shot asks it
  (`StrikeRules.HitThresholdOf`, `DamageOf`). Open: the reach (where a soldier may fight from).
- **The presentation's remaining concrete reads** [implemented, sadk-remake e952365]: the interface reads map objects,
  characters, ships, buildings and the build overlay through services (`IObjectPlaces`, `ICharacterPlaces`,
  `IBuildingPlaces`, `IBuildOverlay`; renderer.md §2.2), and the particle service hands out `IEffectHandle` and
  `IMovieHandle`. Open: shader time per renderer (the time globals are the process's, shared by a gallery's renderer).
- **Declarative panel bindings** [implemented, sadk-remake 809dc12]: a component's panel section as data,
  `<ComponentSection key="brewery.yeast" Title="!YEAST"><Rows><Bar label="…" value="{Yeast}" max="{limit}"/>…`, the rows
  (`Text`, `Bar`, `Good`, `Button`, each with `if`/`unless`) bound to the state's public properties and the use's
  parameters; it takes the place of the rows `IInspectable` describes, so a section is XML only and another mod changes it
  with an `Update`. The kind is presentation (out of the registry checksum). Open: bindings in the original's layouts
  themselves (the building boxes' own members), which need the presentation's reads as views first (the item above).
- **The maintainer's transport mod**: congestion-aware routing and the overflow slot over the §14.2 seams
  (`transport.nextHop`, `transport.flagAdmission`, `carrier.street`). The seams it needs exist [implemented, sadk-remake
  5778b7d]: `NextHopContext.Purpose` (a route or a probe), `IFlagAdmission.CanDrop`, the rule `transport.flagOverflow`
  (an overflow place beyond the six stacks, 0 in the original), the carrier's retry and swap at a refused flag as
  `StreetCarrier` virtuals (step 0x14 of S 0077a2f0); the test mod `AntiStallMod` uses them.
- **Multiplayer identity of mods**: the match set's content hash and startup values in `MatchIdentity` (with the
  lockstep work, milestone 4).
- **The accessibility pass** (the maintainer, 2026-10-28: "a wide, sweeping change to the codebase once more to make
  things far more accessible"). Its goal is the reason the base game is a built-in mod: the engine's surface so open
  that any mod can change any other thing. Its measure: **core.game uses only what any mod can use.** Wherever the base
  game reaches private code, a closed switch, a sealed panel or a hard-coded limit, that is a hole in the surface: every
  rule replaceable by name, every moment an event, every action an opened `[ModApi]` operation, every panel and menu
  extensible, every limit data or a setting, the original's code staying the base implementation (faithful mode
  byte-identical). The history: making the Salzfeld's second kind took about 80 lines in the engine and core.game,
  because a mod could neither react to the game (events went to the presentation only; now `World.On`) nor call what
  core.game's systems can do (their operations are private; `ChangeType` is the first opened). The pass is driven by
  the maintainer's examples of what a mod must be able to do (to come); each example becomes a test mod, and what it
  needs is opened as `[ModApi]` operations on core.game's systems (placing, removing, changing and capturing
  buildings, handing out and taking goods, spawning settlers and soldiers, starting attacks and expeditions, map
  edits) and as events where a moment has none yet, each a port of the original's code path with its address. The
  first sweep before the examples: list every system's operations a mod would call and whether the original has them as
  one function.
  The examples arrived the same day (eleven: an archery tower upgrade, a warehouse that refuses a good, several ships per
  sea route with a dock action, a radial menu with any number of buttons, a deposit-restoring sacrifice, a Scots street
  upgrade, garrison slots by soldier level, the anti-stall router and overflow slot, longer water streets, a
  first-person mode, a HUD toggle). Assessed against sadk-remake 1cb6bec: possible on the supported surface today only
  the water-street depth (`GameConfigDef.MaxWaterStreetWaterDepth`, data); on public but unmarked members the deposit
  sacrifice, most of the archery tower, the router and swaps, the first-person mode; blocked the rest. The work list,
  each item serving the ideas in brackets:
  - mechanisms: refined-setting switches for named implementations, systems and components, numeric startup settings
    into rules (2, 3, 6, 8, 9); a typed component view for the client (1, 7);
  - named seams and rules (the original's code moved unchanged into the base implementation, proven byte-identical):
    `transport.returnDepot` with an `Accepts` test (2, 8); `FlagAdmission.CanDrop` and an overflow place in `FlagStacks`
    (8); the carrier's wait-and-swap decision as a `StreetCarrier` virtual and `NextHopContext.Purpose` (8);
    `net.streetUpgrade`, `movement.stepSpeed` (6); a garrison policy `IGarrisonPolicy` named by `MilitarySection` (7);
    `navy.routeCapacity`, the ship state machine as a named `navy.ferry` piece, `sacrifice.sinksShip` (3); sacrifice
    effects by name (5); optionally `streets.waterStreetCell` (9);
  - operations opened as `[ModApi]`: a projectile shot from a building and `TakeDamage` (1); `SendOut(depot, good)`, the
    good flags, `TryStreetSwap`, `ComputeNextHop` (2, 8); taking a ship off its route, sailing it to a harbour (3);
    sacrifice offers and map resources with a write that emits `MapChanged` (5); the match's client surface
    (`MatchContext`, `MapGeometry`, the renderer's camera and services, `InputActions`) (10);
  - client seams: a military-flag provider (1); the military and warehouse info-box parts and a good button's indicator
    opened (2, 7); the radial action menu with any number of buttons, pixel-identical up to four (4, base game); one
    owner of the mouse cursor, `MatchView.HideHud`, `MatchView.TakeCamera` (10, 11); a radial-menu widget for mods (7).
    The military-flag provider (`BuildingFlags.Register`), the info-box parts (`InfoBoxes.Extend` with stacking
    extensions, the store and military boxes, `UiGoodButton.SetIndicator`) and the ring widget (`UiRadialMenu`) are
    implemented [sadk-remake 7305fa7]: the garrison slots by group with a ring of levels, the warehouse's refusal and
    the archery tower's bow flag are their test mods' client parts.
  The radial action menu (4) is implemented [sadk-remake b25d6fe]: up to four buttons the original's panel (`btAction1..4`,
  the strip by `LayoutVisibleButtons` S 005f0df0 and its jump table S 005f0ef0, `PositionAtCursor` S 005f0880), more
  buttons on the half circle the four span (190.3°, 63.4° apart; `ActionPanelRules.Arc`) over a generated background
  (`ActionPanelArcBackground`), keys 5–0 for actions 5–10; a mod adds an action to a selection kind with
  `SelectionActions.Add` (its availability and command like the base game's). FleetMod's client part docks and undocks
  a ship by it and lists every ship of a sea route in the route box (`ShipBoxContent.Ships`); a sacrifice definition
  names its own icon (`SacrificeDef.IconTexture`, `IconRegion`, `SacrificeIcons.Of`) for the mods' sacrifices.
  The seams of 10 and 11 are implemented [sadk-remake b25d6fe]: `MatchView.TakeCamera(owner)` (the match camera steps
  aside until the handle is disposed), `MatchView.HideHud(reason)`, one owner of the mouse pointer
  (`CursorMode.Request(reason, Hidden|Captured)`, the camera's look-around through it), the marked `MatchContext`
  (`World`, `Renderer`, `Geometry` with heights and water, `Local`) and `InputActions` for a mod's keys; the test mod
  `FirstPersonMod` (F7: walk, jump, sprint, swim and dive, the fog of war keeping you out) uses only them.
  The HUD toggle (11) is a base-game feature (F10, `core.game.hud.toggle`, the original's hidden "Hide UI" developer
  switch S 005ed700): through `HideHud` and the pointer owner it hides the panels and the mouse pointer, which the
  original's `ui.Hide UI` leaves shown (S 00491660 does not draw it).
  Steps 1 and 2 (the audit tool `Sadk.Headless audit` and the friendly foundation) are in sadk-remake 31ae102.
  **Round 1** [implemented, sadk-remake 5778b7d] covers transport and streets, military, navy, sacrifices and the map, each
  idea a test mod in `tests/TestMods` that builds without Harmony on the `[ModApi]` surface, faithful mode byte-identical
  (the six capture sessions' checksums, state hashes and save sections):
  - transport and streets: `transport.returnDepot` (`ReturnDepotChooser`, virtual `Accepts`; S 00557ef0), `SendOut`
    (`depot.SendOut(good)`), the good flags (`depot.PullsIn`), the overflow and carrier seams above, the rules
    `net.streetUpgrade` (S 00668e10), `movement.stepSpeed` (S 00773a40, S 00773ec0) and `net.waterStreet` (S 0052e550,
    the length asked by the street planner, S 00663bf0); refined's `WaterStreetsByLength` (any depth, a length setting).
    Test mods `WarehouseBanMod` (2), `ScotsRoadsMod` (6), `AntiStallMod` (8); 9 in refined;
  - military: the garrison policy `IGarrisonPolicy` named by `MilitarySection.Garrison` (capacity, wanted size, orders,
    surplus, fits and exchange, promotion, conquest, the computer players' threat), `military.groupSuperiority`,
    `MilitarySystem.ShootAt` (`b.ShootAt`), a non-soldier settler killed through the dying path (`Settler.Kill`). Test
    mods `ArcheryMod` (1), `GarrisonSlotsMod` (7), `HumanWaveMod` (13);
  - navy, sacrifices and map: the rule `navy.routeCapacity` (S 005b6d30), the ship state machine as the named piece
    `navy.ferry` (S 005bb500), `ship.TakeOffRoute`, `SailTo`, `MoveTo`, `ReturnToOwnHarbour`, the event `ShipCompleted`,
    the sacrifice effects by name (above; the sink sacrifice's `Sinks` replaces the planned `sacrifice.sinksShip`),
    `MapSystem.ChangeResource(s)` announcing `MapChanged(GroundResources)`. Test mods `FleetMod` (3), `AlchemyMod` (5).
  A save's or log's identity lists every rule; a rule one side does not record compares as equal while it runs its base
  implementation alone (`MatchIdentity.Compare`), so files from before a new rule load without a warning. Left in these
  areas: the remaining fixed decisions (the supplier search S 00557da0, the stack and swap tests, the catapults, the fight
  cell search, the coast and expedition queries), setters of packages, flags, fights and ships, and the systems' own
  cross-system calls turned into events.
  **Round 2** [implemented, sadk-remake 6f69bbb] covers the village, the settlers and the simulation core, the computer
  players, map scripts, statistics and victory, each area with its test mod, faithful mode byte-identical (the capture's
  checksums, state hashes and save sections; a reloaded save's whole bytes differ by the rules its remake part lists):
  - a mod's state: `[Saved]` members of its system or a `SavedComponentState` are saved by name in the save's extension
    part, loaded (an older or newer version of the state still loads) and in the checksum and state hash (`SavedFields`);
  - the village: the production cycle as the stacked named piece `village.production` (`ProductionCycle`: `CanStart`
    S 00565bd0, `Start` S 005657c0, `Duration` S 00565ed0, `Finish` S 00565f80 with `Products` S 00565990, `RequestInputs`
    S 00565a70, `RebalanceInputs` S 00565f00; the context's recipe lets a mod run the base rules over an alternative input)
    and the settler orders as `village.orders` (`SettlerOrderService`: `FindSupplier` S 00562280, `CanSupply` S 00562440,
    `Select` S 00569430 / S 00569290, `Spawn` S 005624f0, `Deliver` S 00561e20; the loop S 005626c0 stays the village's);
    the events `ProductsDelivered`, `SettlerOrderCreated`, `SettlerOrderServed`, `SettlerOrderRemoved`; the operations other
    systems called privately opened (construction, territory, damage and healing, stock in and out, orders, settler spawns,
    messages) with friendly forms on the building. Test mod `GuildMod`. Left: the step list's fixed vocabulary
    (`JobStepKind`), the store's settler acceptance, occupancy, the stock-keeping and decay ticks;
  - the settlers and core: settler classes and soldier kinds (above); the settlers' friendly forms (`SpawnSettler`,
    `SendHome`, `Remove`, `Npc.MoveTo`, `SpawnAnimal`, `Kill`), `OnSettlerSpawned`/`OnSettlerRemoved`,
    `PlayerTable.ChangeTeam` (S 00527b30) and `Rename` (the map scripts call them), the job operations of work behaviours.
    Left: a settler's profession changed in place (the original exchanges through an order), more than two soldier kinds;
  - the computer players, map scripts, statistics and victory: victory conditions and the AI's rules (above); a mod's
    map-script functions in core.game's tables (`ModContext.ExtendLuaTable`); statistics categories (`StatisticCategory`,
    sampled on the S 00537ba0 schedule).
  Round 3, the client (ideas 4, 10, 11 and the ideas' client parts), is implemented
  [sadk-remake 7305fa7, b25d6fe].
- **Step-list fallbacks** (the maintainer, 2026-10-28) [implemented, sadk-remake 941fef4: `Job.Branches`, `JobState.Branch`
  saved in the place of the old flag; the `Take` step and the landlocked Salt Works came before]: several `<Otherwise/>` branches tried in order (a failed step
  goes to the next branch, the last one's failure ends the job; the branch index in the saved job state), and a step
  `<Take good="key"/>` that takes a unit from the building's input stock and cannot be done when it holds none. The
  carriers bring the good because the input stock asks for it (the recipe and the stock limit), never the step. First
  use: a Salt Works built where no shore is in reach takes water as an input good and works from its stock.

