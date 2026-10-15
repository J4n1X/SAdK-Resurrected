# Remake: mods — packages, load stages, code, multiplayer

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). It turns the mod model fixed in
[`../remake-architecture.md`](../remake-architecture.md) §3, §8, §9 into a concrete design: what a mod package
holds, how the engine finds, orders and loads mods, how code mods are loaded and patched, how mod sets work in
multiplayer and in saves.

Tags: **[binding]** = decided by the maintainer (the architecture and rendering documents); **[draft]** = proposed
here, to be confirmed; facts about the original keep the tags of the document they come from.

## 1. What is already fixed [binding]

- The base game is a mod (`base`); the engine knows no content.
- Load stages over all mods in dependency order: settings, data (definitions, updates, final fixes), frozen
  registry, runtime. One registry; any mod may change any entry during the data stages.
- A manifest per mod: name, version, dependencies (required, optional, incompatible), whether it changes the
  simulation. Multiplayer requires the same simulation mods in the same versions; missing mods are transferred.
- Three levels of change: values of registry entries, components added to types, Harmony patches.
- Mods are precompiled assemblies loaded through `AssemblyLoadContext`; JIT runtime, no NativeAOT. Mods define no
  Godot node classes; UI comes as `IInspectable` descriptions and XML layouts. Source mods (Roslyn) are optional and
  later.
- The renderer is moddable through the asset lookup (assets, shaders) and Harmony, not through registry entries of
  its own.
- `base` builds its registry entries by running the original's property scripts against its own `properties.*`
  bindings.

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
| `maps/` | per map | a map is compared and transferred as a map, not as part of the mod set |

The manifest's simulation flag must agree with the contents: the engine refuses a mod that declares itself
client-only but carries a simulation assembly, a `data/` script or a `scripts/` library. The registry checksum
(§6.5) catches anything the flag misses.

`base` is a built-in mod with the same layout. Its assemblies are compiled with the game [binding]; its
`assets/` holds the remake's own files (shaders, the remake's layouts and UI parts); the content converted from
the player's installation is mounted below it as a layer of its own (assets.md §5.1). A second built-in mod,
`refined`, carries the refined mode's simulation fixes (§9.4).

## 3. Manifest (`mod.xml`) [draft]

```xml
<Mod id="brewery-yeast" version="1.2.0">
  <Title>Yeast for the brewery</Title>
  <Description>The brewery also produces yeast.</Description>
  <Authors><Author>someone</Author></Authors>
  <Engine min="1.0" max="1.*"/>
  <Simulation>true</Simulation>
  <Dependencies>
    <Requires id="base" version="^1.0"/>
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
- **Simulation**: the [binding] flag "changes the simulation".
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
| built-in | inside the game's installation folder (`base`, `refined`) | always present, never transferred |
| the player's mods | `<user data>/mods/<id>/` or `<user data>/mods/<id>.zip` | enabled per profile |
| received from peers | `<user data>/mods-received/<id>-<version>-<hash>/` | kept apart from the player's own; used only for matches that need them; pruned by age |
| development | folders given with `--mod-dir=<folder>` | for working on a mod without copying it |

`<user data>` is Godot's `user://` folder of the remake. A **profile** is a named set of enabled mods with their
startup settings (`<user data>/profiles/<name>.xml`); the game starts with the last profile used. A match runs with
the host's simulation set (§9.2).

## 5. Load order [draft]

1. Collect the enabled mods and `base`; check `Requires` (present, version in range) and `Incompatible`; any failure
   stops with a message that names both mods.
2. Sort topologically: every `Requires` and every present `Optional` dependency comes before the dependent mod.
   Ties are broken by the ordinal order of the ids, so every machine computes the same order from the same set. A
   cycle stops with a message listing it.
3. `base` is always first; `refined`, when active, comes right after `base`.

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
| 2 | mount the virtual file system: converted installation, then `base`, then the mods in order ([assets.md](assets.md) §5) | engine |
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

### 6.3 Data stage [draft]

Three sub-stages; each runs over all mods in load order before the next starts [binding]. In each sub-stage a
mod's C# part runs first (`IDataStage.Definitions` / `Updates` / `FinalFixes`), then its Lua file (`data.lua` /
`data-updates.lua` / `data-final-fixes.lua`).

`base`'s definitions sub-stage runs the original's property scripts from the converted installation
([lua.md](lua.md) §3): `data.lua` with the 21 files it loads, through the `properties.*` bindings, which create
and fill registry entries. Afterwards `base` applies what the original keeps outside the property scripts
(settings XML values that the simulation reads, §8.3) and its own C# definitions (the behaviour components the
property values configure).

Data-stage Lua sees two APIs:

- `properties.*`: the original's 243 functions with the original's semantics, so a property script written for
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
- `base`'s keys are the global variable names the original's property scripts assign the ids to (`brauhaus`,
  `woodCutter`); how they are found is in [lua.md](lua.md) §3.3. Each entry also keeps its original id (signed
  32 bit) as data [binding].
- A mod's new entries take the prefix `<mod id>.` by convention. Defining a key that exists is an error; changing
  an existing entry goes through `get`. Collisions are loud instead of silently overriding.

### 6.5 Freeze and the registry checksum [draft]

After the final fixes:

1. every reference by key (a building's job, a cost's good) is resolved to the entry; an unknown key stops loading
   with the mod and entry that named it;
2. entries get dense runtime indices per kind. The order is definition order, which for `base` is the original's
   record creation order; tables the original iterates in **signed id order** keep a second order list, since that
   order changes simulation results ([binding] §8, `../sim/properties-data.md` §2.1);
3. validation by each definition class (`Validate()`), e.g. a production needs a workplace;
4. the **registry checksum**: a hash over the canonical serialisation of every simulation-relevant definition field
   (presentation fields such as the gfx name excluded). Peers compare it at join; a mismatch with an identical mod
   set means a mod's data stage is not deterministic, and the message names the first differing entry.

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

- **One `AssemblyLoadContext` per mod**, not collectible. It resolves the engine, `base`, Harmony, GodotSharp and
  the .NET libraries to the instances already loaded (shared type identity) and everything else from the mod's
  own `bin/` folder, so two mods may carry different versions of the same private library.
- A mod references the engine through reference assemblies of the engine SDK (a NuGet package for mod authors),
  never its own copy of `GodotSharp` or `Sadk.Engine`.
- Simulation assemblies must not reference Godot: the headless runner (tests, replays, checksum comparison against
  the original, [binding] §2) loads only them. The engine checks the references at load time.
- **No ReadyToRun and no trimming** for the engine, `base` and mods. Trimming removes code mods may need;
  ReadyToRun precompiles call sites with inlined callees, which Harmony cannot reach. Everything is JIT-compiled.
- Assemblies stay loaded until the process ends; a different mod set means a new process (§9.3).

### 7.2 Entry point [draft]

```csharp
public sealed class BreweryYeast : IMod
{
    public void OnLoad(ModContext ctx)
    {
        ctx.Harmony.PatchAll(typeof(BreweryYeast).Assembly);      // Harmony id = mod id
        ctx.Systems.Add<YeastSpoilageSystem>(after: "base.production");
        ctx.Commands.Add<DumpYeastCommand>();
        ctx.Lua.Simulation.AddLibrary("yeast", new YeastLuaLibrary());
    }
}
```

`OnLoad` runs in load order before the settings stage, so patches are in place before any engine code that they
change runs, and before the JIT has compiled callers that might inline the patched methods. `ModContext` gives
the mod its id, its logger, its settings, its folder in the virtual file system and the registration APIs of
§6.7. A client assembly has its own entry point (`IClientMod.OnLoad(ClientModContext)`), called after the
simulation entry points, with the presentation registrations (render kinds, UI parts, input actions, audio).

### 7.3 Harmony [draft]

- The engine ships one Harmony version (`Lib.Harmony`) and loads it into the shared context; mods do not bundle
  their own.
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
build checksum, `../data-loading.md` §3, which makes it worth checking), `base` extracts it into registry data during
the data stage, where the registry checksum covers it. A texture pack or a replaced model therefore can never
desynchronise a match, and the simulation runs headless without any asset.

## 9. Mod sets in multiplayer

### 9.1 Identity [draft]

A mod in a match is `(id, version, content hash)`. The content hash covers the simulation-relevant files: the
manifest, the simulation assemblies, `data/`, `scripts/`, and the values of the mod's `startup` settings. Client
assemblies and assets are not covered: client-only differences are allowed.

The **match set** is the list of simulation mods in load order with their identities; its hash is exchanged when
a peer joins, together with the registry checksum (§6.5) and the engine version.

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

### 9.3 Changing the mod set restarts the process [draft]

The remake does not unload mods. Harmony patches, the JIT's inlining decisions, static state in mod assemblies and
the frozen registry make reliable unloading in one .NET process a research problem; a restart is simple and
always correct. To keep it cheap:

- the conversion of the installation is cached and only checked at start (milliseconds, [binding] §11);
- the game relaunches itself with `--profile=<match set>` and `--join=<session>` / `--load=<save>` so the player
  lands back where the switch started (lobby room, match, save);
- data-only switches (no assemblies involved) could later rebuild the registry in-process, as an optimisation.

This differs from today's sadkmod design, where unloading per match was required because restarting the original
game in the middle of the lobby flow is not possible. **To confirm with the maintainer.**

### 9.4 Compatibility mode, refined mode [draft]

- **Compatibility mode** is the match set `{base}` with presentation-only differences allowed, so the simulation is
  the original's tick by tick. Talking to original clients additionally needs the original's build checksum of the
  installation's `scripts\**\*.lua` and `settings\**\*.xml` (`../data-loading.md` §3), which the remake computes
  from the same installation.
- **Refined mode** is `{base, refined}`: `refined` is a built-in simulation mod holding the fixes of the original's
  simulation bugs (the navalcombatfix rules and their successors). Presentation refinements are not part of it:
  they are switches ([binding] rendering §2.3).
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
- Saves of the original (compatibility mode, `../sim/save-format.md`) store original ids; `base` maps them to keys
  through the original ids it keeps.

## 11. Tooling for mod authors [draft]

- **SDK**: reference assemblies of the engine and `base` as a NuGet package; a `dotnet new` template that builds a
  mod folder with `mod.xml`; documentation generated from the XML doc comments.
- **Lua API reference** generated from the binding attributes ([lua.md](lua.md) §10), one page per table.
- **`--validate-mods`**: headless run of steps 1-8 for a mod set, printing the load order, the patch report, every
  data-stage error and the registry checksum; also usable in a mod's CI.
- **Development mode**: assets and presentation documents reload when their files change; the data stage reruns on
  request (registry rebuilt, current match ended).
- **Logs**: one log file; every line from mod code carries the mod id; Lua errors with file and line (the original
  discards them, [lua.md](lua.md) §2.7).

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

1. Restart instead of unloading when the mod set changes (§9.3).
2. Lua (with the original `properties.*` API and a `registry` view) as the data-file format for registry entries,
   no XML/JSON definitions in the first version (§6.3); answers [binding] §13 item 1.
3. XML for manifests and every patchable presentation document; JSON only for machine-written files (§3).
4. `refined` as a built-in simulation mod (§9.4).
5. Consent per content hash for received code mods; data-only mods automatic (§7.4).
6. Command ids of mod commands from a name hash (§6.7) versus a registry assigned at match start.
7. Confirm that the original's simulation reads no value from the settings XML (§8.3).
