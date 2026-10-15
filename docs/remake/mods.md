# Remake: mods — packages, load stages, code, multiplayer

Draft of 2026-10-15. Part of the remake design set ([README.md](README.md)). It turns the mod model fixed in
[`../remake-architecture.md`](../remake-architecture.md) §3, §8, §9 into a concrete design: what a mod package
holds, how the engine finds, orders and loads mods, how code mods are loaded and patched, how mod sets work in
multiplayer and in saves.

Tags: **[binding]** = decided by the maintainer (the architecture and rendering documents); **[draft]** = proposed
here, to be confirmed; facts about the original keep the tags of the document they come from.

## 1. What is already fixed [binding]

- The base game is mods: `core.game`, `core.mainmenu`, `core.lobby` (§11a); the engine knows no content. Every mod,
  these included, can be switched off (maintainer, 2026-10-15); there is no built-in mod.
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

The manifest's simulation flag must agree with the contents: the engine refuses a mod that declares itself
client-only but carries a simulation assembly, a `data/` script or a `scripts/` library. The registry checksum
(§6.5) catches anything the flag misses.

The core mods (§11a) are ordinary mods with this layout that ship with the game in `<game folder>/mods/`
[implemented 2026-10-15]. `core.game`'s
`assets/` will hold the remake's own files (shaders, the remake's layouts and UI parts); the content converted from
the player's installation is mounted below all mods as a layer of its own (assets.md §5.1). `refined`, a mod that
ships with the game as well, carries the refined mode's simulation fixes (§9.4).

## 3. Manifest (`mod.xml`) [draft]

```xml
<Mod id="brewery-yeast" version="1.2.0">
  <Title>Yeast for the brewery</Title>
  <Description>The brewery also produces yeast.</Description>
  <Authors><Author>someone</Author></Authors>
  <Engine min="1.0" max="1.*"/>
  <Simulation>true</Simulation>
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
| the player's mods | `<game folder>/mods/<id>/` or `<game folder>/mods/<id>.zip`; the mods that ship with the game (`core.*`, `refined`, `tools.assetbrowser`) are among them | enabled per profile; a mod with `<EnabledByDefault>true</EnabledByDefault>` is on unless the profile switches it off |
| received from peers | `<game folder>/mods/received/<id>-<version>-<hash>/` | kept apart from the player's own; used only for matches that need them; pruned by age |
| development | folders given with `--mod-dir=<folder>[;<folder>]` | for working on a mod without copying it; wins over a player mod of the same id |

[implemented, maintainer 2026-10-15] Mods live in the **game folder**, next to its `settings.xml` (assets.md §3), not
in the user folder. A **profile** is a named set of enabled mods with their startup settings
(`<game folder>/profiles/<name>.xml`); the game starts with `default`. A match runs with the host's simulation set
(§9.2). A folder or zip whose manifest is unreadable, or a second mod with an id already found, is listed as a
problem on the mods screen; the other mods stay usable.

## 5. Load order [draft]

1. Collect the enabled mods (no mod is added by force); check `Requires` (present, version in range) and
   `Incompatible`; any failure stops with a message that names both mods.
2. Sort topologically: every `Requires` and every present `Optional` dependency comes before the dependent mod.
   Ties are broken by the ordinal order of the ids, so every machine computes the same order from the same set. A
   cycle stops with a message listing it.
3. `refined`, when active, comes before every mod that is not one of its own dependencies (so right after
   `core.game`). [implemented]

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
| 2 | mount the virtual file system: converted installation, then the mods in order ([assets.md](assets.md) §5) | engine |
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
   installation gives `22926df0…` (892 records).

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

- **One `AssemblyLoadContext` per mod**, collectible (the mod set can be unloaded, §9.3). It resolves the engine,
  Harmony, GodotSharp and the .NET libraries to the instances already loaded, in the context that loaded the
  engine (in an exported Redot game that is not .NET's default context), and everything else from the mod's own
  `bin/` folder, so two mods may carry different versions of the same private library. Assemblies are read into
  memory, so zip mods work the same and no file stays locked. [implemented]
- A mod references the engine through reference assemblies of the engine SDK (a NuGet package for mod authors),
  never its own copy of `GodotSharp` or `Sadk.Engine`.
- Simulation assemblies must not reference Godot: the headless runner (tests, replays, checksum comparison against
  the original, [binding] §2) loads only them. The engine checks the references at load time.
- **No ReadyToRun and no trimming** for the engine and the mods. Trimming removes code mods may need;
  ReadyToRun precompiles call sites with inlined callees, which Harmony cannot reach. Everything is JIT-compiled.
- A simulation assembly that references GodotSharp is refused with a message naming the mod [implemented].
- **Mods may define their own Godot node types** (maintainer, 2026-10-15) [implemented]. A mod project runs Redot's
  source generators as a "tools project" (`IsGodotToolsProject=true`): the method, property and signal bridges are
  generated, so `_Ready` and `_Process` overrides are called, but no `res://` script paths (a mod's files are not in
  the game's project, and the paths of two mods would collide) and no game entry point. A mod's node type becomes a
  script without a path when its first object is made; such a script is reference-counted and leaves Redot's type map
  with its last object, so the mod's code unloads once its views are freed, in editor runs and exports alike
  [tested 2026-10-15]. The shared build rules are `src/Mods/Mod.props` in sadk-remake.
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

- **Compatibility mode** is the match set `{core.game}` with presentation-only differences allowed, so the simulation is
  the original's tick by tick. Talking to original clients additionally needs the original's build checksum of the
  installation's `scripts\**\*.lua` and `settings\**\*.xml` (`../data-loading.md` §3), which the remake computes
  from the same installation.
- **Refined mode** is `{core.game, refined}`: `refined` is a simulation mod shipped with the game, holding the fixes of the original's
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
- Saves of the original (compatibility mode, `../sim/save-format.md`) store original ids; `core.game` maps them to keys
  through the original ids it keeps.

## 11. Tooling for mod authors [draft]

- **SDK** [implemented 2026-10-15]: the game's `sdk/` folder holds `Mod.props`, Redot's source generator and an
  example mod. A mod's project sets `ModId` and imports `sdk/Mod.props`; it then references the game's assemblies
  (from the exported `data_` folder, never copied), the generator (as a "tools project", §7.1; `ModUsesGodot=false`
  for simulation-only code) and the assemblies of every mod its `mod.xml` names as `Requires` or `Optional` (from the
  game's `mods/`, in a step the editor's design-time build runs too, so IntelliSense completes their types). A build
  copies the mod into `mods/<id>/`; `dotnet run` starts the game with the mod switched on for that run (the game's
  `--enable=<id>`; `GameArguments` and `GameEngineArguments` add the game's and Redot's options, for instance the
  installation and conversion folder when the game folder has no `settings.xml` yet). `sdk/README.md` is the guide
  for mod authors. In the source repository the SDK builds against the repository's projects (a repository-only
  `src/Sdk/Directory.Build.props`), and `dotnet run` starts the development game through the Redot editor.
  **The editor's view is checked** [implemented]: `tools/check-sdk.sh <game folder>` opens mod projects with Roslyn's
  `MSBuildWorkspace`, the loader of the editor's language server (a design-time build, then the compiler with the
  generators and analyzers), and compares references and diagnostics: the shipped example clean with `Core.Game`
  referenced, a misspelled `TribeDef` member exactly CS0117, a client mod with its own node type clean, the same
  without `partial` exactly Redot's GD0001, the repository's example clean. `tools/export-game.sh` runs it after
  every export; with only the SDK and the game files, a mod author's machine needs nothing else but .NET's
  reference packs. **Descriptions** [implemented]: the code's doc comments are XML (`<summary>`, `<para>`, `<c>`,
  `<code>`), every assembly writes its documentation file, and the files travel with the dlls (the mods' `bin/`, the
  export's `data_` folder, Godot's and Harmony's from their packages), so the editor shows the engine's, core.game's
  and Godot's descriptions; the check probes them. Checked with two mods built outside the repository: a tribe in C# with
  the engine's `TribeDef` (the example requires no mod since the content model moved into the engine), and a client mod
with its own node type, an overlay and a menu entry. The core mods in the
  repository use `src/Mods/Mod.props`, with project references to each other. [planned] Typed constants and emit
  helpers for the intents of the required mods (a source generator over their declarations), XML schemas for
  `mod.xml` and `intents.xml`, the mods' XML doc files next to their assemblies, a `dotnet new` template.
- **Lua API reference** generated from the binding attributes ([lua.md](lua.md) §10), one page per table.
- **`Sadk.Headless validate-mods [--game-folder=] [--mod-dir=] [--enable=a,b]`** [implemented]: loads a mod set like
  the game (without client code), prints the load order, the layers, the patch report, the startup settings, every
  patched document with the patches that miss, the data-stage errors and the registry checksum, then unloads it and
  checks the leak check; exit code 1 on any problem; also usable in a mod's CI.
- **Development mode**: assets and presentation documents reload when their files change; the data stage reruns on
  request (registry rebuilt, current match ended).
- **Logs**: one log file; every line from mod code carries the mod id; Lua errors with file and line (the original
  discards them, [lua.md](lua.md) §2.7).

## 11a. Core mods, modes and intents [agreed with the maintainer 2026-10-15; implemented in sadk-remake d49188c]

### 11a.1 The game is a host; the remake is mods

`Sadk.Game` and the engine are a host: the first-start conversion, the virtual file system, the registry, the mod
loader, the Lua host, the asset loaders and instantiation helpers, the intent bus with its mode host (below), and the
game's own `engine.shell` (when no mod enters a mode) and `engine.mods` (the mods screen). After the start the game
emits `engine.start`; from there the mods decide what shows. The remake itself is three **core mods**, ordinary mods in
`<game folder>/mods/` that ship with the game and are on by default (`<EnabledByDefault>true</EnabledByDefault>` in
`mod.xml`; the profile lists such a mod only when the player switched it off, as `<Disabled id="…"/>`):

| Mod | Side | Holds |
|---|---|---|
| `core.game` | simulation + client | the game's content (it fills the engine's registry from the original's property scripts) and the logic that uses it, systems, `logic.*`, rendering and HUD, and the match networking: it behaves like a server already (lockstep, joining, the referee). `refined` requires it. Its assemblies: `Core.Game.Simulation` (no Godot) and `Core.Game.Renderer` (Godot), so another mod (a map editor) can require core.game and use its renderer. [implemented: the data stage (the original's property scripts, 892 records) and the renderer's entry point; the rest planned] |
| `core.mainmenu` | client | the main menu [implemented as a stub: a column of buttons in the original's Chapter Garamond on a plain colour; the original's menu runs over the lobby map rendered live (`menumain.xml`: `BG_3D`, `campaignName="Main"`), which comes when maps render]; other mods add entries with `core.mainmenu.addmenuitem` |
| `core.lobby` | client + network | the lobby world only: the traffic while the player is in the lobby (village, chat, rooms); it starts matches through `core.game`'s intents [planned] |

`core.game` is the only simulation mod of the three, so it alone decides multiplayer compatibility (§9.1); a changed
main menu or lobby never splits players. `core.game` requires no other core mod, so it loads headless (tests, replays,
the checksum comparison, a dedicated host).

The development tools are a mod as well: `tools.assetbrowser` (on by default, requires `core.mainmenu`) adds "Asset
browser" (a mode) and "Check all assets" (an overlay) to the main menu [implemented].

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
  text language, [assets.md](assets.md) §8).
- **Dependencies.** A mod whose listener or route emits another mod's intent names that mod among its dependencies
  (`tools.assetbrowser` requires `core.mainmenu`), else a warning; the version range is the contract's version. Mods
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
2. Decided 2026-10-15: C# and Lua (the original `properties.*` API and a `registry` view) for registry entries,
   no XML/JSON definitions in the first version (§6.3); answers [binding] §13 item 1.
3. XML for manifests and every patchable presentation document; JSON only for machine-written files (§3).
4. `refined` as a built-in simulation mod (§9.4).
5. Consent per content hash for received code mods; data-only mods automatic (§7.4).
6. Command ids of mod commands from a name hash (§6.7) versus a registry assigned at match start.
7. Confirm that the original's simulation reads no value from the settings XML (§8.3).
