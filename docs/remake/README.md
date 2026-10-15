# Remake design set (draft)

Draft of 2026-10-15 for the remake of *Die Siedler: Aufbruch der Kulturen* in Redot/C#. It builds on the two binding
documents, [`../remake-architecture.md`](../remake-architecture.md) and [`../remake-rendering.md`](../remake-rendering.md),
and on the behaviour specifications in [`../sim/`](../sim/README.md), and turns them into a design for the parts the
game is built from first: the renderer, the asset pipeline, the mod system and the Lua surface. It was written after
a study of the testbed viewer (`sadk-remake/src/Sadk.Viewer`, commit `ea6b13e`); nothing of the game is built yet.

Everything here is a proposal (**[draft]**) until the maintainer confirms it; decisions of the binding documents are
marked **[binding]**. Facts about the original carry the tags of the documents they come from.

## The documents

| Document | What it fixes |
|---|---|
| [redot-capabilities.md](redot-capabilities.md) | Redot 26.2 (Godot 4.5.2): which engine facilities the design relies on, checked against the installed API; what each renderer offers; the pitfalls the viewer found |
| [sim-boundary.md](sim-boundary.md) | the boundary between the deterministic simulation and the presentation: clock, tick records (events and motion samples), read-only views, commands as the only way back, random streams, guards |
| [renderer.md](renderer.md) | the world renderer: render objects with identity in batches, render kinds, visual descriptors, the shader library and its loading, views and passes, GPU skinning, every kind of object, picking, switches, moddability, what is taken over from the viewer |
| [assets.md](assets.md) | the first-start conversion and the check at every start, the virtual file system with its layers, formats after conversion, map packages, what is loaded when |
| [mods.md](mods.md) | mod packages and manifests, load order and stages, code mods (assemblies, Harmony, trust), data-stage formats, mod sets in multiplayer and saves |
| [lua.md](lua.md) | the Lua surface: runtime and number model, the converter, script states, when map scripts run, every function table with its class and remake service, callbacks, saves, the remake's own `sadk` surface |
| [performance.md](performance.md) | budgets and how they are measured; every technique the original uses to save work, sorted into keep exactly (the simulation's), adopt, leave to Redot, drop; the original's waste; the viewer's measurements |

Reading order: this file, then `sim-boundary.md` (the interface everything else uses), then the topic you need.

## The architecture in brief

**Assemblies** ([sim-boundary.md](sim-boundary.md) §3):

```
Sadk.Formats  ──►  Sadk.Convert                                   (no Godot)
Sadk.Engine   ──►  Sadk.Session                                   (no Godot)
     ▲                 ▲
     │      mods: core.game (no Godot) ─── its client assembly (Godot); core.mainmenu, … (Godot)
     │                 ▲                          ▲
Sadk.Presentation (Godot: renderer, audio, UI) ───┘
     ▲
Sadk.Game (the executable)          Sadk.Headless (conversion, validation, replays)
```

**A run of the game:**

1. Start: settings; the installation is found and checked; the first start converts it into open formats
   ([assets.md](assets.md) §4).
2. Mods are resolved and ordered, the virtual file system mounted (converted installation, then the mods),
   assemblies loaded and their Harmony patches applied ([mods.md](mods.md) §5, §6).
3. Settings stage; data stage (`core.game` runs the original's property scripts through its `properties.*` bindings; mods
   change entries in C# and Lua); the registry is frozen and checksummed; presentation documents (the original's
   settings XML as visual descriptors, layouts) are merged and patched.
4. Main menu.
5. A match: the map package mounted on top; the simulation builds the world, runs the map script's top-level chunk,
   `onStarted`, `onLoaded` ([lua.md](lua.md) §4); the presentation preloads the match's assets and builds its mirror
   from the published events ([renderer.md](renderer.md)).
6. Every frame: input → commands; 0..n ticks; each tick record's events and motion samples applied; interpolation;
   render ([sim-boundary.md](sim-boundary.md) §4.2).

## Answers to the open points of the binding architecture (§13)

| Open point | Proposal | Where |
|---|---|---|
| file format of data-stage definitions | C# and Lua (the original's `properties.*` API plus a `registry` view); no XML or JSON definitions in the first version. Presentation data is XML, merged and patched | [mods.md](mods.md) §6.3, §6.6 |
| which C# Lua package | MoonSharp, used as source in a fork of our own (insertion-ordered tables, run-time constant evaluation, a clear place for the single-precision hook; formatter and escapes fixed) | [lua.md](lua.md) §2.1 |
| manifest format, transfer of mods | `mod.xml`; identity = id, version, content hash of the simulation parts; the host's simulation set wins; received code needs the player's consent; a different set means a restart into it | [mods.md](mods.md) §3, §9 |
| the engine's asset formats after conversion | glTF 2.0 with a `SADK_kex` extension; DDS kept (BC1 with one-bit alpha transcoded to BC3); PNG; OGG and WAV; BMFont with Unicode glyph ids; UTF-8 text tables; the original XML; `.pfx.json`; map packages `.sadkmap` | [assets.md](assets.md) §6, §7 |

## Decisions for the maintainer

The proposals that change direction or cost real work, bundled:

1. **No unloading of mods.** A different simulation mod set restarts the game into it, landing back in the lobby
   room, match or save; today's sadkmod design unloads per match ([mods.md](mods.md) §9.3).
2. **The Lua package** — decided 2026-10-15: MoonSharp in a fork of our own ([lua.md](lua.md) §2.1).
3. **Scripted maps in compatibility-mode matches with original clients**: run them without `logic` as a fresh
   original process does, or refuse them ([lua.md](lua.md) §4.5).
4. **End of a cinematic in a remake multiplayer match**: when every peer has finished it, or for everyone when the
   first does ([sim-boundary.md](sim-boundary.md) §11).
5. **`refined` as a simulation mod shipped with the game**: refined mode = `{core.game, refined}`, compatibility mode
   = `{core.game}`
   ([mods.md](mods.md) §9.4).
6. **Data-stage formats**: C# and Lua only in the first version ([mods.md](mods.md) §6.3).
7. **DXT1 textures with one-bit alpha** — decided 2026-10-15: transcoded to BC3 (twice the size of BC1) instead of
   decoded to RGBA8 (eight times) ([assets.md](assets.md) §6.2).

Also decided on 2026-10-15:

- **UI stays XML.** Godot scenes (`.tscn`) were weighed as the form of moddable UI parts and rejected: they do not
  merge across mods, their `res://` references bypass the virtual file system, and compatibility mode needs the
  original's XML layouts anyway. Architecture §6 stands as written.
- **Game elements are inspectable nodes** ([renderer.md](renderer.md) §4.6): every building, settler, animal and
  ship is a node that shows its state in the remote inspector, while drawing stays batched.
- **The first implementation step** is the loader: the first-start conversion, the virtual file system and a loader
  per kind, ending in an asset check that loads every asset; the data stage (Lua runtime, registry) is the next
  step.

## What the viewer study found

- **Taken over**: `Sadk.Formats` (container, KEX with the load-time bake, maps, `.pfx`, settings XML), the particle
  simulation, the settler palette generator, the light model, the terrain mesh math, the exact terrain triangle
  lattice and the ground-decal clipping, the KEX-to-Godot formulas, the mirror view, the shaders' formulas
  ([renderer.md](renderer.md) §22).
- **Replaced**: the object shader with its 21 variant defines and the terrain's run-time type branch (§7); anonymous
  batches without identity (§4); node trees with Godot skinning per settler, animal and building (§9, §13); materials
  copied per instance; direct reads of the installation and the by-name texture table ([assets.md](assets.md) §5);
  names of the original's content in code (§22).
- **Bugs to keep out of the game**: the construction cut compares world and model heights; `HeightAt` interpolates
  bilinearly instead of using the drawn triangle; the water level is a shader default; the mirror pass is detected
  by "camera below water"; compressed DDS files without mips stay without.

## Corrections to the existing documents found on the way

Settled from the shipped scripts and the binary while writing [lua.md](lua.md):

- `sendMessage` in the campaign's sacrifice calls is a parameter, passed `true` from quest callbacks (the message is
  sent), not an undefined global (`../sim/lua-runtime.md` §3.7, §6.2).
- Under single precision `showBookDelay` never falls from 2 000 000 000 (`../sim/lua-runtime.md` §3.9).
- The AI attack limiter is inert (every `ai.setup` is commented out), so `logic.getRandom` never runs; script draws
  come only from `map_createDeposit` (`../sim/lua-runtime.md` §3.9, §8).
- The hex in `scripts\info\i_<hex>.lua` is the object's `*_create` id (`i_12e67603` = `guardHouse`)
  (`../lua-surface.md` §6, `../sim/lua-runtime.md` §6.1).
- `triggers.removeTrigger` in `Presentation.lua` is a call to an unregistered table (dead code), and
  `onTriggerIsActive` is called from nowhere (`../lua-surface.md` §3.1).
- `patterns.lua` has seven literals with bytes above 0x7F, not one (`../sim/lua-runtime.md` §6.2).
- `menu.updateCinematic` runs `nMenu::Cinematic::Update` synchronously; `BOOKDIALOG = 24` does not index the book;
  the second `ui` registration returns −1 results for an unknown widget; `pl_getProducedGoodCount` aborts for a good
  outside the tribe's lists; a negative spiral radius hangs (read in the binary, 2026-10-15).

The corrections to `lua-runtime.md` and `lua-surface.md` are applied in those files.

## Suggested first steps

1. `Sadk.Formats` taken over from the viewer; `Sadk.Convert` with the file record, the start check and the
   whole-install self-checks (the viewer's `KexCheck`, `MapCheck`); the virtual file system.
2. `Sadk.Lua` (the fork) with the number model and the formatter; the converter; the data stage running `data.lua`
   into a registry; the registry checksum; the vocabulary replay.
3. The simulation's world build from a converted map, publishing `MapChanged` and `EntityAdded` events headless.
4. The renderer's first steps on top of it ([renderer.md](renderer.md) §23).
