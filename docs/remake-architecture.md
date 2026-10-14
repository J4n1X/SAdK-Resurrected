# Remake architecture

Binding decisions for the remake of *Die Siedler: Aufbruch der Kulturen* (maintainer, 2026-10-14). The behaviour to
reproduce is specified in [`sim/`](sim/README.md); this document fixes how the code that implements it is laid out.
The renderer's own decisions and what the testbed viewer found: [`remake-rendering.md`](remake-rendering.md).

## 1. Goals that shape the layout

- **Two modes.** A *compatibility mode* runs in lockstep with the original client: same simulation results tick by
  tick, same quirks where they change simulation state. A *refined mode* fixes the original's bugs and jank.
- **Everything moddable,** down to core systems such as pathfinding.
- **No original data shipped.** The remake reads the player's own installation.

## 2. Platform

- **Redot** (the Godot fork) with .NET; "Godot" in this document means Redot. Rendering, input, audio, UI and
  tools use it.
- The **simulation is a plain C# library** without Godot nodes. It runs headless: for tests, for replays and for
  the tick-by-tick comparison against the original's checksum (`sim/logic-core.md` §3.6).
- **C# everywhere:** simulation, presentation, UI, tools and mods. No GDScript. One language means one build, one
  mod format (assemblies) and Harmony reach over every layer.

## 3. Mod model

Modelled on Factorio: **the base game is a mod.** The engine knows no content.

- **Load stages** over all mods in dependency order: settings, then data (each mod's definitions, then all
  "updates", then all "final fixes"), then the frozen registry becomes the game's content, then runtime.
- **One registry.** Every type (building, good, settler job, tribe, …) is an entry. A mod may change any entry of
  any other mod during the data stages. Entries can come from C# definitions or from data files; both land in the
  same registry.
- **Manifest** per mod: name, version, dependencies (required, optional, incompatible), whether it changes the
  simulation. Multiplayer requires the same simulation mods in the same versions on every machine; missing mods
  are transferred (as assetshare does today).
- **Three levels of change**, from light to deep:
  1. change values of registry entries in a later data stage;
  2. add components (new behaviour, with its own UI and actions) to existing types;
  3. Harmony patches on any method of the engine or another mod, for what the first two cannot express.
- **The renderer is moddable, but not one of the easy parts.** It offers no data-stage entries or components of its
  own to change; assets and shaders are replaced or added through the asset lookup (§11), and anything deeper goes
  through level 3.
- **Lua** runs map scripts with the original's `logic.*` API (`sim/lua-runtime.md`). Scripts see only ordered
  iteration (no hash-order `pairs` in simulation code).

## 4. What the engine defines and what `base` defines

**Rule: the engine fixes what is a mechanism; `base` defines what the original keeps as data. Make something
generic only where it is cheap now and expensive to add later; otherwise wait until a mod needs it.**

| Thing | Engine | `base` / data |
|---|---|---|
| Building sizes | site computation over footprint shapes | the three shapes small, medium, large |
| Tribes, goods, buildings, settler jobs | registry types | all entries |
| Job behaviour, production, transport, combat | component framework, fixed tick order | the behaviour components |
| Map grid | hex grid with its six directions | — |
| Simulation tick | fixed 10 ticks per second at speed 1, single precision | — |
| Lua scripting | runtime and API mechanism | the `logic.*` functions |

Not abstracted: the grid, the tick, the number model. Compatibility mode rests on them, and a degree of freedom
there is a way to break lockstep.

## 5. Types, instances and components

- **Type and instance are separate.** A `BuildingType` (size, costs, components with their parameters) exists once
  per type; a placed `Building` points to its type and carries only its own state.
- **A component exists twice:** a definition on the type (`ComponentDef`, the parameters) and a state per instance
  (`ComponentState`, created by the definition). The state has `Tick`, `Save` and `Load`.
- **Interfaces describe capabilities of components** (`IStorage`, `IWorkplace`, `IInspectable`, …), so systems and
  UI ask what a thing can do without knowing its type.
- Inheritance is the exception: a mod may subclass a core type when composition cannot express what it needs.
- **Map objects are instances too.** Trees, stones, doodads and the other landscape objects each have an identity in
  the simulation and a render object of their own, so behaviour can be attached to them as to buildings
  (maintainer, 2026-10-14). The renderer batches them for drawing but addresses each one by that identity.
- **Values are never `const`.** C# copies constants into the code that uses them at compile time, which takes them
  out of reach of mods and Harmony. Values are properties or fields.

Example (the original's Bavarian brewery, `brauhaus`):

```csharp
registry.DefineBuilding("brauhaus", t =>
{
    t.Size = BuildingSize.Medium;
    t.NameKey = "!BUILDING_BREWERY!";
    t.Cost(frame: new() { ["plank"] = 2 }, cost: new() { ["stoneBav"] = 2 });
    t.Add(new WorkplaceDef { Job = "good_brewerBav" });
    t.Add(new StockDef     { Limit = 6 });
    t.Add(new ProductionDef
    {
        Input  = { ["water"] = 1, ["corn"] = 1 },
        Output = { ["weissbeer"] = 2 },
        WorkTicks = 333, RestTicks = 55,
    });
});

// another mod, later data stage
registry.Building("brauhaus").Get<ProductionDef>().Output["yeast"] = 1;
```

## 6. UI and player actions

- **The UI never changes simulation state.** Every player action is a `GameCommand`: queued, sent in lockstep,
  executed on every machine at the same tick. Commands that exist in the original carry its wire id (for example
  `ToggleProduction` = `0x2000A`, a toggle like the original's), so compatibility mode can talk to original
  clients.
- **Panels are generic.** A component that implements `IInspectable` describes what it shows (progress, goods rows,
  buttons) and which command a button sends; Godot draws the description. A mod's new component brings its panel
  rows and actions with it.
- **Layouts are XML**, as in the original (`ui\layout\*.xml`, `sim/ui-toolkit.md`). The engine builds Godot `Control`
  nodes from them at run time, so mods need no node classes.
  - **Bindings** tie widgets to values and commands that C# exposes per component (a small view model):
    `<ProgressBar value="{Production.Progress}"/>`, `<Button text="!PAUSE_PRODUCTION!" command="ToggleProduction"/>`.
  - **Slots** in a layout (`<ComponentSections/>` in the building panel) take the section templates of the
    components, so a new component's section appears in every panel that shows it.
  - **Patch operations** in the data stage change other mods' layouts: XPath selects a node, then add, replace or
    remove (the RimWorld model).
- **UI parts are components** (maintainer, 2026-10-14): the pieces panels are made of (a goods row, a progress bar
  with its label, a production section, a list of items) are reusable parts with their own layout, and screens are
  assembled from them, so mods reuse and extend them. Editing them comfortably in the Redot editor (a preview of the
  layout files there) is a goal for the tooling.
- Godot's scene files (`.tscn`) serve the remake's own development, not moddable UI: they are not made for several
  mods changing one scene, and their scripts are node classes.
- Option for compatibility mode: `base` reads the original's layout XML from the player's installation, as it does
  the property scripts.

## 7. Determinism rules for simulation code

- Floating point: C# `float` (IEEE single, round to nearest), matching the original's x87 control word; no
  `System.Math` / `MathF` trigonometry or powers (own implementations; `Sqrt` is exact and allowed).
- Integers: 32-bit `uint` where the original uses 32-bit arithmetic (random generator).
- No iteration over `Dictionary<,>` or hash sets; ordered containers where the original iterates a `std::map`.
- One simulation random generator, drawn only by simulation code, in the original's order.
- A fixed system order per tick, registered by position; mods insert their systems relative to named systems, and
  the engine refuses ambiguous orders.

## 8. The `base` mod and the original's data

- `base` builds its registry entries from the player's installation (the property scripts in
  `data\game\scripts\properties`, the settings XML), so no original values are shipped.
- **Names are the keys** inside the remake; `base` keeps each entry's original id as data. The original's maps and
  saves store those ids, and its tables are iterated in order of the **signed** id, which changes simulation
  results (`sim/properties-data.md` §2.1). Compatibility mode keeps both.
- **How the entries are made: by running the original's property scripts.** The 22 Lua scripts are a program that
  the original runs at every start through its bindings (`bp_create`, `gp_…`, `cfg_set…`; `lua-surface.md`
  §3.3, `sim/properties-data.md`). The remake runs the same scripts with its own Lua runtime and its own
  implementation of those bindings, which fill the registry. No code is generated and nothing is compiled; ids
  and record order come out as in the original. The other mods' data stages run afterwards.
- What `base` contains as C# is behaviour only (components, systems, commands); it is compiled with the game.

## 9. Code loading

- The game's own code, `base` included, is compiled ahead of time with the .NET tools into assemblies; an export
  ships them with the .NET runtime.
- **Mods are precompiled assemblies (DLLs)**, built against the engine assembly and loaded at start-up through
  `AssemblyLoadContext`. This needs the JIT runtime, not NativeAOT; Harmony needs it as well.
- **Optional, later: source mods.** `.cs` files compiled once with Roslyn (`Microsoft.CodeAnalysis.CSharp`) and
  cached as a DLL keyed by a hash of the sources, so modders can work without a .NET setup. Costs about 10-20 MB
  for the compiler.
- **Mods do not define Godot node classes.** Godot registers classes derived from its node types when the project
  is built, not reliably from an assembly loaded at run time. Mods bring UI as `IInspectable` descriptions that the
  engine draws (§6). If a mod ever needs its own node class, the engine provides a registration path for it.

## 10. Lua

- A pure C# Lua implementation (a NuGet package), not a native library.
- The original's scripts are Lua 5.0.2 (`sim/lua-runtime.md`). A **converter** rewrites them once, at the first
  start, for the package's Lua version; `sim/lua-runtime.md` lists the 5.0 features the shipped scripts rely on,
  which is the converter's worklist. Map scripts are converted the same way when a map is first loaded.
- Simulation scripts get ordered iteration only (§7).
- **Lua numbers must round like the original's.** The original runs its scripts with the x87 control word at
  24-bit precision (live 2026-10-14: `0xA001F`), so every Lua arithmetic result is rounded to single precision:
  `60 * 0.34` is 20.39999961853 there, 20.4 in double precision. Where a script turns such a value into an integer or
  compares it, the two land on different sides and lockstep breaks. The converter does not change this; the Lua
  package must let its number operations be rounded to `float` after each operation, at least for scripts that
  change simulation state.

## 11. Assets and the original installation

- **Converted once, at the first start**, from the player's installation into formats the engine loads directly
  (meshes, skeletons and animations from `.KEX`, textures, maps, sounds, the converted Lua). The conversion is
  slow; it runs again only when its sources change.
- **Maps bring their own assets.** A map made for the remake may bundle textures and other assets of its own, for
  example its own skydome, terrain or object textures, instead of only naming the base game's. The map format and
  the asset lookup must allow that from the start: a map's own files are searched before the base game's, and they
  travel with the map when it is shared (as map sharing does today).
- **Models are not bound to `.KEX`.** `.KEX` is the format the base game's models arrive in; models made for the
  remake (by mods or maps) may come in other formats, and the asset lookup chooses the loader by format, not by
  assuming `.KEX`.
- **Shaders may be loaded from files, GLSL included.** Mods and maps may bring their own shaders, and loading GLSL
  shader files is allowed, besides Godot's shading language.
- **Checked at every start:** the conversion records the installation's path and a list of its source files with
  size and modification time. Every start compares that list (milliseconds, no hashing). A changed file is hashed
  and converted again; a missing installation stops the game. The converted files are valid only next to the
  player's own copy of the original.

## 12. Development

- Repository `~/projects/sadk-remake`, local only for now (no remote).
- The maintainer tests on a Windows PC with Redot. The Linux box shares the home folders by Samba (`[homes]`, LAN
  only), so the PC opens the repository's project through that share directly.
- **First milestone: a model viewer.** It converts `.KEX` scenes (meshes, skeletons, animations;
  `asset-formats.md`, `sim/animation-models.md`) and shows them, so the conversion is checked by eye before
  anything else builds on it.

## 13. Open

- The file format of data-stage definitions (C# only, or also Lua or JSON as in Factorio).
- Which C# Lua package (MoonSharp or another), against the converter's needs, the ordered-iteration rule and
  single-precision number arithmetic (§10).
- The manifest format and the transfer of mods between peers.
- The engine's own asset formats after conversion.
