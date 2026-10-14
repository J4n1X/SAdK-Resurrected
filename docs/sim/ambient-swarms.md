# Ambient swarms: birds, fish and bugs

Specification of the ambient swarm system of the match scene: the manager `S2CG::SwarmMgr`, the spawn zones built
from the map, the swarms (`S2CG::Swarm`), the flock simulation (`ai::render::SwarmFlock`, `SwarmActor`, the three
steering behaviours) and the parameters of `flocks.xml`. Binary: `sadk_noav.exe`; "S 00xxxxxx" is a static address
in it.

Tags: **[known]** = read directly in the decompiled code or the disassembly at the address given, in the bytes at
the address given, or in the named data file. **[inferred]** = one step of reasoning from what is visible.
**[TODO]** = open, with what would settle it. Nothing here was observed in the running game.

Related documents (not repeated here): `docs/sim/rendering.md` (scene structure, render passes §3.1, the scene time
block §2.2, world load §4.1, per-tick and per-frame order §4.2 and §4.3, units §2.1), `docs/sim/particles.md` §2.9
(the `RandomGenerator`), `docs/sim/map-format.md` §5.4 (grid state bits), `docs/sim/map-resources.md` §2.1 (cell and
vertex coordinates), `docs/sim/map-editor-devtools.md` §3.13 (the `SceneInfo` debug variables).

---

## 1. Purpose and scope

The swarm system is meant to put flocks of birds over the map and schools of fish into its lakes and seas: it
builds spawn zones from the map at world load, spawns a flock out of the player's view every 10 to 30 seconds, moves
each member with three boids rules (evade, pack, match speed) and an optional wandering point of interest, and
deletes flocks that stay out of view too long.

**In this build the system is dormant.** Every method of the manager starts with a test of the byte `SwarmMgr +0x1c`,
the constructor writes 0 there, and no code writes anything else (§3.1) [known]. So no zone is built, no swarm is
spawned, updated or drawn, the debug overlay shows nothing and the shadow fit gets no swarm bounds. The only work done
is the construction of the manager and the reading of `flocks.xml`. The rest of this document describes the code as
it would run with the byte set, because a reimplementation that wants ambient flocks needs exactly that; each part is
still read from the binary.

Even with the byte set nothing would be visible: the per-swarm draw call of the main pass and of the shadow pass is an
empty function, and no model, texture, animation or shader is referenced by any swarm function or by `flocks.xml`
(§3.13) [known]. The only drawing code is the debug overlay (white spheres and lines).

The system is pure presentation: it reads the map's grid states and terrain heights and writes only its own objects
[known: every function of §11; none writes a logic object or uses the simulation's random generator].

Out of scope: the land animals (`AnimalMgr`, `animals.xml`), the particle effects, the lobby world.

---

## 2. Data model

### 2.1 Object graph

```
S2CG::SwarmMgr (0x48, singleton g_pSwarmMgr S 0088d864)
  pFlocksXml      the parsed flocks.xml, kept for the manager's lifetime
  rng             RandomGenerator, shared by everything below
  zones[]         SwarmSpawnZone (0x2c): AABB + type (+ cell rectangle for water zones)
  swarms[]        SwarmSlot (8): { Swarm*, idleTime }
S2CG::Swarm (0x58)                      one flock; POI state
  flock -> ai::render::SwarmFlock (0x74) zone box, actors, target point, behaviours
    actors[]    -> ai::render::SwarmActor (0x120) position, velocity, neighbour list, behaviour scores
    behaviours[] -> SwarmBehaviourEvade (0x1c), SwarmBehaviourPack (0x1c), SwarmBehaviourMatchSpeed (0x18)
```

[known] S 0069ab00, S 0069a260, S 006cd6b0, S 00770d20, S 00770b40, S 00770470.

RTTI: `.?AVSwarmMgr@S2CG@@` (S 00881874) and `.?AVSwarm@S2CG@@` (S 00882308) exist [known]. The `ai::render` swarm
classes carry no RTTI: the word before the behaviour base vtable S 008340ac is the float 0.125, not a locator
[known: bytes S 008340a8 = `00 00 00 3e`]; their names are the ones of the Ghidra map [inferred].

### 2.2 `S2CG::SwarmMgr` (0x48, vtable S 007f9f70)

The vtable is the shadow caster face: [0] `RenderWithExternalEffect` S 00699af0, [1] `GetVisibleSwarmBounds`
S 00699bf0, [2] `AddVisibleSwarmBoxes` S 00699b90 [known: bytes S 007f9f70; slots 0 and 1 are called by
`S2CG::ShadowManager::RenderCasters` S 0069e2a0 and `UpdateMatrices` S 0069e340].

| Offset | Field | Default (ctor S 0069ab00) | From `flocks.xml` | Meaning |
|---|---|---|---|---|
| +0x00 | vtable | S 007f9f70 | | |
| +0x04 | `pFlocksXml` | the document | | `[data]\settings\flocks.xml` (S 0069a9c0) |
| +0x08 | `rng` | `ctor_WithSeed(this)`: `SetSeed(address of the manager)` | | §3.14 |
| +0x10 / +0x14 / +0x18 | `zoneCount` / `zoneCapacity` / `pZones` | 0 / 0 / null | | spawn zones, 0x2c each |
| +0x1c | `enabled` (byte) | **0, never set** | | gate of every method (§3.1) |
| +0x20 / +0x24 / +0x28 | `swarmCount` / `swarmCapacity` / `pSwarms` | 0 / 0 / null | | slots, 8 bytes each |
| +0x2c | `visibleSwarmCount` | 0 | | counted each frame |
| +0x30 | `maxSwarms` | 5 | `maxSwarms` (absent: 5 stays) | limit of **visible** swarms for spawning |
| +0x34 | `minSpawnDelay` | 5.0 | `minSpawn` = 10.0 | seconds |
| +0x38 | `maxSpawnDelay` | 30.0 | `maxSpawn` = 30.0 | seconds |
| +0x3c | `swarmTimeout` | 15.0 | `swarmTimeout` = 10.0 | seconds out of view before deletion |
| +0x40 | `spawnCountdown` | 0.0 | | seconds |
| +0x44 | unused | 5.0 | | written by the constructor only, never read |

[known] S 0069ab00 (disassembly: `XOR EBX,EBX` … `MOV byte ptr [ESI+0x1c],BL`; constants S 007e1cd8 = 5.0,
S 007db61c = 30.0, S 007db618 = 15.0), S 0069a9c0, field use in §11.

### 2.3 `SwarmSpawnZone` (0x2c) and `SwarmSlot` (8)

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `boxMin` vec3 | world |
| +0x0c | `boxMax` vec3 | world |
| +0x18 | `type` | 0 unspecified, 1 flight, 2 water, 3 ground |
| +0x1c..+0x28 | `cellX0, cellY0, cellX1, cellY1` | cell rectangle of a water zone; -1 after construction, not written for the flight zone |

The type names are the table S 0088185c = `unspecified`, `flight`, `water`, `ground` (strings S 007f9f48..S 007f9f64)
[known]. Constructor `SwarmSpawnZone_ctor` S 00699dc0: box = the zero box S 0088f258 (initialised to zeros by
S 007cb350), type 0, cells -1 [known]. Arrays grow by 1.5x with a minimum of 8 (`SwarmSpawnZoneArray::Reserve`
S 0069a1a0) [known].

`SwarmSlot`: +0x00 `Swarm*`, +0x04 `idleTime` (seconds the swarm has been out of view; 0 when created) [known]
S 0069a260, S 0069a920.

### 2.4 `S2CG::Swarm` (0x58, vtable S 007fbbd8)

Vtable [known] bytes S 007fbbd8: [0] scalar deleting dtor S 006cd8f0, [1] `Update(dt)` S 006cd950 (per logic
tick), [2] `InterpolateFrame(tickFraction)` S 006cd630 (per frame).

| Offset | Field | Default (ctor S 006cd6b0) | Meaning |
|---|---|---|---|
| +0x04 | `flock` | new `SwarmFlock` | |
| +0x08 | `visible` (byte) | 0 | flock box in the view frustum this frame |
| +0x0c | `bounds` AABB | zero box | actors' AABB inflated by `boundsMargin` (shadow bounds) |
| +0x24 | `boundsMargin` | 1.0 | |
| +0x28 | `rng` | the manager's generator | |
| +0x2c | `hasPOI` (byte) | 0, then `hasPOI` | |
| +0x30 / +0x34 | `nextMin` / `nextMax` | 0, then file | wait between points of interest, seconds |
| +0x38 / +0x3c | `minPOI` / `maxPOI` | 0, then file | duration of a point of interest, seconds |
| +0x40 | `poiSpeed` | 0, then file | length of the target offset (§3.10) |
| +0x44 | `poiPos` vec3 | 0 | |
| +0x50 | `poiTimeLeft` | 0 | |
| +0x54 | `timeToNextPOI` | 0, then `nextMin + unit() * (nextMax - nextMin)` when `hasPOI` | |

The five POI floats are read only when `hasPOI` is true [known] S 006cd6b0.

### 2.5 `ai::render::SwarmFlock` (0x74, no vtable)

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `lastDt` | dt of the last step |
| +0x04 / +0x10 | `boundsMin` / `boundsMax` | the zone box: positions are clamped to it (`startMin`/`startMax` are read here first and then overwritten, §3.5) |
| +0x1c | `numActors` | |
| +0x20 | `actors` | array of `SwarmActor` (count prefix at -4) |
| +0x24 / +0x30 | `actorsMin` / `actorsMax` | AABB of the actors' simulated positions, rebuilt every frame; empty box after construction (S 0088f270: `+FLT_MAX` / `-FLT_MAX`) |
| +0x3c | `target` vec3 | point the Pack rule pulls toward (§3.10) |
| +0x48 | `avgVelocity` vec3 | mean actor velocity (debug only) |
| +0x54 | `targetOffset` vec3 | POI offset added to the target |
| +0x60 / +0x64 / +0x68 | `numBehaviours` / `behaviours` / `influences` | 3; Evade, Pack, MatchSpeed; influence per behaviour |
| +0x6c / +0x70 | `debugBehaviour` / `debugParam` | -1; written by the constructor only |

[known] S 00770d20, S 007702c0, S 00770770, S 007707c0, S 007705c0.

### 2.6 `ai::render::SwarmActor` (0x120)

| Offset | Field | Default (ctor S 00771780) | Meaning |
|---|---|---|---|
| +0x00 | `renderPos` vec3 | 0 | interpolated, per frame |
| +0x0c | `orientation` quaternion | (0, 0, 0, 1) | **never changed** |
| +0x1c | `worldMatrix` | identity | from `orientation` and `renderPos`, per frame |
| +0x5c | `velocity` vec3 | 0 | |
| +0x68 | `prevPos` vec3 | | position before the last tick |
| +0x74 | `pos` vec3 | | position after the last tick |
| +0x80 | `steerGain` | 1.0 | constant |
| +0x84 | (unnamed) | 1.0 | constant, no reader found |
| +0x88 | `neighborRadius` | 2.0 | constant |
| +0x8c | `neighbors` | | `SwarmActorNeighbors` (0x70), §2.7 |
| +0xfc / +0x100 / +0x104 | `numBehaviours` / `behaviourEntries` / `behaviourOrder` | | entries `{score, influence, behaviour}` (12 bytes); order = indices, initially 0, 1, 2 |
| +0x108 | `currentBehaviour` | -1 | index into `behaviourOrder` while the behaviours run |
| +0x10c | `steerSum` vec3 | | this tick |
| +0x118 | `steerBudget` | | 2.0 at the start of every tick |
| +0x11c | `steerCount` | | this tick |

The fields +0x0c..+0x18, +0x80, +0x84, +0x88 are written only by the constructor [known: scan of all stores in
S 00770200..S 007728b0]. `InitBehaviours` S 00771400 copies behaviour pointer and influence per entry; the entry
constructor S 00771240 zeroes the score [inferred: 19-byte body].

### 2.7 `ai::render::SwarmActorNeighbors` (0x70, at actor +0x8c)

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `owner` | the actor |
| +0x04 | `entries[6]` | `{distance, weight, actor}`, 12 bytes each; nearest at index 5; empty = `{FLT_MAX, 0, null}` |
| +0x4c | `distSum` | sum of the entry distances |
| +0x50 | `count` | entries used |
| +0x54 | `minWeightComplement` | `min(1 - weight)`; no reader found |
| +0x58 | `avgPos` vec3 | mean neighbour position |
| +0x64 | `avgVelocity` vec3 | mean neighbour velocity |

[known] S 00771720, S 00771360, S 007712a0, S 007715c0. Actor-relative offsets used by the behaviours:
`entries[5].distance` +0xcc, `entries[5].actor` +0xd4, `avgPos` +0xe4, `avgVelocity` +0xf0 [known].

### 2.8 Behaviours

Base `ai::render::SwarmBehaviour` (0x14): +0x00 vtable, +0x04 flock, +0x08 parameter count, +0x0c parameter table
(0x10 per parameter: value pointer, two floats 0.0 and 1.0, name), +0x10 name (the XML element name). Shared slots
[known] bytes S 008340ac..S 00834124: [0] scalar deleting dtor S 00772400, [1] validate, [2] `Apply(actor)`,
[3] debug draw.

| Class (size, vtable) | Element | Parameters (offset, constructor default) | [1] | [2] `Apply` | [3] |
|---|---|---|---|---|---|
| `SwarmBehaviourEvade` (0x1c, S 008340d4) | `Evade` | `minRange` +0x14 = 0.0, `maxRange` +0x18 = 1.0 | S 00772260 | S 007725f0 | S 00772440 |
| `SwarmBehaviourPack` (0x1c, S 008340f8) | `Pack` | `returnStr` +0x14 = 0.001, `distance` +0x18 = 0.75 | S 00772340 | S 00772780 | S 007724e0 |
| `SwarmBehaviourMatchSpeed` (0x18, S 00834118) | `MatchSpeed` | `weight` +0x14 = 1.0 | none (S 005657b0, empty) | S 00772540 | none (S 00488270, `RET 0xc`) |

[known] constructors S 007721d0, S 007722b0, S 00772390; arguments from `CreateBehaviours` S 00770b40 (floats
S 007dffb0 = 0.75, S 007e3c20 = 0.001). Slot [1] keeps Evade's range ordered (if `maxRange <= minRange`: swap and
set `maxRange = old minRange + 0.01`) and clamps Pack's two values to >= 0 [known]; no caller of slot [1] was found
in the swarm functions [TODO, §10]. Slot [3] draws range spheres; it is reached only with actor debug flag 2, which
nothing passes (§3.13) [known].

---

## 3. Rules and algorithms

### 3.1 The gate

`SwarmMgr +0x1c` is tested first by `Update`, `SyncAndRemoveTimedOutSwarms`, `BuildSpawnZones`, `Render`,
`RenderWithExternalEffect`, `GetVisibleSwarmBounds`, `AddVisibleSwarmBoxes` and `DebugDraw`; each returns at once
(false for the two bounds functions) when it is 0 [known]. The only store to it is in the constructor (0) [known:
scan of every instruction with a `+0x1c` memory destination in the manager's methods S 00699800..S 0069ac20 and in
all eight callers of `GetInstance` S 006998b0: `Scene::RenderPasses`, `Shutdown`, `Update`, `Init`,
`RenderDebugOverlays`, `SyncLogicTick`, `OnWorldLoadStateChanged`, `OnLogicInitStateChanged`]. The manager is heap
allocated and `g_pSwarmMgr` is read only by `GetInstance` and `DestroyInstance` [known: xrefs of S 0088d864], so no
other code can reach the byte [inferred]. The shadow manager holds the manager only as a caster pointer and calls
its slots 0 and 1 [known] S 0069e2a0, S 0069e340.

### 3.2 Creation and settings

`Scene::Init` S 006824c0 calls `SwarmMgr::CreateInstance` S 0069abb0 after the ship manager and before the projectile
table; with `Scene +0x78 > 1` it registers the manager with the shadow manager as caster layer 6 (pass mask 0x40,
`ShadowManager::AddEntry` S 0069e580) [known]. The constructor seeds the generator (§3.14) and calls `LoadSettings` S 0069a9c0: open
`[data]\settings\flocks.xml`, parse, keep the document, read the root attributes `maxSwarms` (int), `minSpawn`,
`maxSpawn`, `swarmTimeout` (floats); a missing attribute keeps the default [known]. `Scene::Shutdown` destroys the
manager (`DestroyInstance` S 0069a230) [known].

### 3.3 Spawn zones at world load

`Scene::OnWorldLoadStateChanged(true)` S 0067eed0 (end of a map or save load) and
`Scene::OnLogicInitStateChanged(true)` S 0067ef40 (end of `NLogic::System::InitSubsystems`) call
`BuildSpawnZones(gameAccess, gridStates)` S 0069a3f0 with `g_pGameSystem->map->pGridStates` [known]. `W` and `H` are
the map size in cells (game access slots +0x10 / +0x14 = map +0x08 / +0x0c, S 00538800, S 005387f0) [known].

```
DeleteAllSwarms(); zoneCount = 0
covered[W*H] = 0
for y in 0 .. H-2:  for x in 0 .. W-2:
    if not water(x, y) or covered[y*W + x]: continue          // water = grid state bit 0x4
    x1 = x; y1 = y; growX = growY = true
    loop:
        if growX and not all water(x1+1, yy) for yy in y..y1:  growX = false
        if growY and not all water(xx, y1+1) for xx in x..x1:  growY = false
        if growX and growY and not water(x1+1, y1+1): break   // diagonal fails: stop at once
        if not growX and not growY: break
        if growX: if x1 < W-1: x1 += 1;  if x1 == W-1: growX = false
        if growY: if y1 < H-1: y1 += 1;  if y1 == H-1: growY = false
    if x1 - x > 2 and y1 - y > 2:                             // at least 4 x 4 cells
        zone = { type 2 (water), cells (x, y, x1, y1),
                 min = CellToWorldPos(x, y)   with y := deepWaterLevel * heightScale  (= -3.0),
                 max = CellToWorldPos(x1, y1) with y := seaLevel * heightScale       (= -0.1) }
        covered[yy*W + xx] |= 4 for the rectangle
hmax = max over all cells of GetCellHeight(cell)              // start value -FLT_MAX
zone = { type 1 (flight), min = CellToWorldPos(0, 0) with y := hmax,
                          max = CellToWorldPos(W-1, H-1) with y := hmax + 2.0 }
```

[known] disassembly S 0069a3f0..S 0069a916 (constants S 007e51c0 = `-FLT_MAX`, S 007e0bc0 = 2.0). Details:

- Only the start cell is checked against `covered`; the growth tests only the water bit, so a rectangle may overlap
  earlier ones [known].
- The grid is indexed with `g_MapWidth` S 00880fb0, the `covered` array with `W` [known]; both are the cell width
  [inferred].
- `CellToWorldPos` S 00687790 returns the cell's centre vertex `(4x + 2(y&1), 4y)` in world units, with the terrain
  height there; `GetCellHeight` S 00687220 the same height [known]. `seaLevel` and `deepWaterLevel` are the image
  constants -100 and -3000 height units (`rendering.md` §2.1), so water zones span world y -3.0 .. -0.1 [known]
  S 00687050, S 00687070.
- The box corners are stored as given (`AABB::Set` S 006ea2c0 does not order them) [known]; x and z grow with the
  cell indices, so min < max on those axes [inferred].
- The water bit is "sample-vertex height below the map's `minHeight`" (`map-format.md` §5.4), while the water zone
  depth uses the render constants; on a map whose `minHeight` differs from -100 the two disagree [inferred].
- **No ground zone (type 3) and no unspecified zone (type 0) is ever built** [known]. The flight zone is always the
  last one.

### 3.4 Spawn scheduling

Per frame `SwarmMgr::Update` S 0069a920 calls `TrySpawnSwarm(frustum, frameDelta)` S 0069a320 when
`visibleSwarmCount < maxSwarms` (counted just before, §3.11) [known]:

```
if spawnCountdown <= 0:
    spawnCountdown = minSpawnDelay + unit() * (maxSpawnDelay - minSpawnDelay);  return
c = spawnCountdown - frameDelta
if c > 0 or zoneCount == 0:  spawnCountdown = c;  return
n = zoneCount
i = NextInRange(0, n + n/4);  if i >= n-1: i = n-1          // integer n/4
box = zones[i].box
if ChooseOffscreenFlockBox(frustum, box) and SpawnSwarm(i, box) != null:  spawnCountdown = 0
// otherwise spawnCountdown is left unchanged: the attempt repeats on the next frame
```

[known]. With the file values the first spawn is due 10..30 s of frame time after the zones exist (the first call
only rolls the delay). The chance of the flight zone is `(n/4 + 2) / (n + n/4 + 1)`, of each water zone
`1 / (n + n/4 + 1)` [inferred: arithmetic of `NextInRange`, inclusive]. Because the countdown pauses while
`maxSwarms` swarms are visible and the attempt repeats every frame while the camera sees every candidate box, the
spawn rate depends on the camera [inferred].

`ChooseOffscreenFlockBox(frustum, box)` S 00699ed0, with `c` and `e` the centre and size of the zone box and six `unit()`
draws `r0..r5` in this order:

```
min_k = c_k + e_k * (0.5 - r_k)                      k = x, y, z   (draws r0, r1, r2)
max_k = min_k + 0.1 * e_k + 0.15 * e_k * r_(k+3)     (draws r3, r4, r5)
return Frustum::TestAABB(frustum, box) == 1          // 1 = completely outside
```

[known] disassembly S 0069a048..S 0069a055 (`SUB EAX,1; NEG; SBB; ADD 1`), constants S 007d4a90 = 0.5,
S 007db630 = 0.1, S 007f9f80 = 0.15; `TestAABB` S 004e0540 returns 1 when the box is behind a frustum plane, else 2.
So **swarms are only spawned out of view**. The box is 10 % to 25 % of the zone size on each axis and its minimum
corner anywhere in the zone, so it may reach past the zone's maximum [known]. `frustum` is the scene's view frustum
`Scene +0x5e0` [known] S 006805e0.

### 3.5 Swarm construction

`SpawnSwarm(i, box)` S 0069a260: the flocks.xml node is the first child of the root whose attribute `zone` equals the
zone type's name (case-sensitive) (`FindZoneXmlNode` S 00699ca0); none: no swarm. In the shipped file `flight`
selects `<Bird>` and `water` selects `<Fish>`; `<Bug>` (`ground`) is never selected (§3.3) [known]. Then
`new Swarm(doc, node, &rng, &zones[i], box)` is appended with `idleTime = 0` [known].

`Swarm::ctor` S 006cd6b0, in order [known]:

1. `SwarmFlock::ctor` S 00770d20: creates the behaviours Evade, Pack, MatchSpeed with the defaults of §2.8; every
   influence 0.0 (`CreateBehaviours` S 00770b40).
2. `SwarmFlock::LoadFromXml` S 007702c0:
   `numActors` (int) if present; else `minCount`, `maxCount` (default 0) and
   `numActors = minCount < maxCount ? NextInRange(minCount, maxCount) : max(minCount, maxCount)`;
   `startMin`, `startMax` (3 floats) into the flock box; for each child element whose name equals a behaviour name:
   `influence` (float, **1.0 when absent**) and every parameter of that behaviour by its attribute name. A behaviour
   without a child element keeps influence 0.
3. `SwarmFlock::Init(zone, box, rng)` S 00770770: flock box = the zone box (this replaces `startMin`/`startMax`;
   the zone pointer is never null on this path), `CreateActors` S 00770470 (actor array, `InitBehaviours` per actor),
   `ScatterActors(box)` S 00770640:
   `pos = prevPos = renderPos = centre(box) + 0.45 * size(box) * (2 r - 1)` per axis (x, y, z draws per actor in actor
   order), `velocity = 0`, neighbour list reset.
4. `hasPOI` (exactly `true` / `false`, `XmlDoc::GetAttrBool` S 006e7b60); if true `minPOI`, `maxPOI`, `nextMin`,
   `nextMax`, `poiSpeed` (floats, read in this order) and `timeToNextPOI = nextMin + unit() * (nextMax - nextMin)`.

Floats are read with `atof`; a missing attribute leaves the field unchanged (`GetAttrFloat` S 006e7bd0) [known].

### 3.6 The flock step (per logic tick)

`SwarmMgr::SyncAndRemoveTimedOutSwarms(dt)` S 006998c0 runs once per logic tick from `Scene::SyncLogicTick`
S 00680550 with `dt = Scene +0x50`, the tick length (0.1 s) [known for the call; that it runs once per tick is
inferred in `rendering.md` §4.2]. For each
slot from the last to the first: `idleTime > swarmTimeout` → delete the swarm, swap the last slot in, `count--`;
else `Swarm::Update(dt)` S 006cd950 [known]. `Swarm::Update` runs `SwarmFlock::Update(dt)` S 007707c0 and then the POI
logic (§3.10). `SwarmFlock::Update`:

```
lastDt = dt
for a in actors (index order):  a.Simulate(dt, flock box)            // §3.8, §3.9
c = centre(actorsMin, actorsMax)            // AABB built by the last frame (§3.11)
target = 0; avgVelocity = 0; wsum = 0
for i in 0 .. n-2:                          // the last actor is left out of the target
    d = pos_i - c;  w = |d|^2
    target += w * d;  wsum += w;  avgVelocity += vel_i
    for j in i+1 .. n-1:
        s = |pos_j - pos_i|^2;  dist = s > 0 ? FastSqrt(s) : s
        if dist < neighborRadius_i:          // 2.0
            neighbors_i.Insert(actor_j, dist);  neighbors_j.Insert(actor_i, dist)
avgVelocity = (avgVelocity + vel_(n-1)) / n
target = (wsum > 0 ? target / wsum : 0) + c + targetOffset
```

[known] disassembly S 007707c0..S 00770b3a. `FastSqrt` S 006e8a20 is a table approximation (about 0.05 % high)
[known: its plate in the Ghidra map]. With one actor the pair loop does not run and `target = c + targetOffset`
[known]. The target weights an actor by its squared distance from the box centre: stragglers dominate [inferred].

### 3.7 Neighbour lists

`Insert(actor, d)` S 007712a0 [known, disassembly]:

```
i = 5;  while entries[i].distance <= d:  i -= 1;  if i < 0: return      // farther than all six: dropped
for k in 0 .. i-1:
    if entries[k+1].actor == null: break                                  // stops at the first empty entry
    entries[k].distance = entries[k+1].distance;  entries[k].actor = entries[k+1].actor
entries[i] = { d, actor }
```

The list is sorted with the nearest at index 5 and empty entries (`FLT_MAX`) at the low indices. Because the shift
stops at the first empty entry above index 0, a list with 4 or fewer entries does not push entries down: an insert
into an occupied slot replaces that entry, so neighbours are lost until the list holds 5 entries [known: the stop
condition; the consequence is arithmetic].

`ComputeAndReset` S 007715c0 runs at the end of each actor's `Simulate` (§3.9) [known]:

```
count = 0; distSum = 0
for e in entries[5], entries[4], ... while e.actor != null:
    count += 1;  distSum += e.distance
    avgPos += e.actor.pos;  avgVelocity += e.actor.velocity   // the first entry assigns instead of adding
minWeightComplement = 1
for e in entries[5], ... while e.actor != null:
    e.weight = e.distance / distSum;  minWeightComplement = min(minWeightComplement, 1 - e.weight)
    e.actor = null;  e.distance = FLT_MAX
if count > 0:  avgPos /= count;  avgVelocity /= count
// count == 0: avgPos and avgVelocity keep their previous values
```

[known]. Timing within a tick: the behaviours of `Simulate` read the entries filled by the pair loop of the
previous tick and the means computed at the end of the previous tick's `Simulate` (which came from the pair loop two
ticks back); the neighbours' positions read by Evade and by `ComputeAndReset` are whatever those actors hold at that
moment (actors before this one in index order have already moved) [inferred: call order of §3.6].

### 3.8 The behaviours

`Simulate` runs the behaviours in the actor's current priority order; each calls `AddSteering(vector, strength)`
S 00771510 zero, one or two times [known]:

```
AddSteering(v, s):
    entry = behaviourEntries[behaviourOrder[currentBehaviour]]
    entry.score += entry.influence * s                  // scores are never reset or decayed
    if steerBudget > 0:
        steerBudget -= |v|^2;  steerSum += v;  steerCount += 1
```

So the strength only raises the behaviour's score (its priority); the vector enters the steering mean unscaled, and
the first vector of a tick always enters (budget 2.0) [known].

**Evade** S 007725f0 (`minRange` m, `maxRange` M):

```
sum = 0; wsum = 0
for e in entries[5], entries[4], ... (at most 6) while e.actor != null:
    if e.distance < M:
        w = 1 - (e.distance - m) / (M - m)              // not clamped: > 1 below m
        sum += 10 * w * (pos - e.actor.pos);  wsum += w
if wsum > 0 and |sum|^2 > 0:  AddSteering(sum, wsum)
```

**Pack** S 00772780 (`distance` D, `returnStr` R):

```
if entries[5].actor != null:
    v = neighbors.avgPos - pos
    if |v|^2 > D^2:  AddSteering(v, R * |v|^2 / D^2)
u = flock.target - pos
AddSteering(u, 0.1 * R * |u|^2 / D^2)                   // always
```

**MatchSpeed** S 00772540:

```
c = clamp(dot(velocity, neighbors.avgVelocity), -1, 1)
AddSteering(neighbors.avgVelocity, 0.5 * c + 0.5)       // always; weight is not read
```

[known] disassembly of the three; constants S 007e2508 = 10.0, S 007db630 = 0.1, S 007e2210 = -1.0, S 007d4a90 = 0.5.
Since neighbours are only listed within `neighborRadius` 2.0, an Evade `maxRange` above 2.0 acts as 2.0 for the
distance test (the formula still uses the file value) [inferred]. MatchSpeed's `weight` is read from the file but
used by nothing [known: no reader of +0x14 in S 00772540].

### 3.9 Steering, integration and the zone clamp

`SwarmActor::Simulate(dt, box)` S 00771900 [known, disassembly]:

```
steerSum = 0; steerCount = 0; steerBudget = 2.0
for k in 0 .. nb-1:  currentBehaviour = k;  behaviour[behaviourOrder[k]].Apply(this)
for k in 0 .. nb-2:                                       // one bubble pass, descending score
    if score[order[k]] < score[order[k+1]]:  swap order[k], order[k+1]
if steerCount > 0:
    velocity += steerGain * (steerSum / steerCount - velocity) * dt      // steerGain 1.0
p = pos + velocity * dt
for axis in x, y, z:  if box.min < box.max:  p = clamp(p, box.min, box.max)
prevPos = pos;  pos = p
neighbors.ComputeAndReset()
```

Constant S 007d435c = 2.0 [known]. There is no speed limit, no gravity, no terrain or obstacle test, and the velocity
is kept when the position is clamped [known: nothing else in the function]. The initial order is Evade, Pack,
MatchSpeed [known] S 00771400.

### 3.10 Target point and point of interest

`Swarm::Update(dt)` S 006cd950 after the flock step, only with `hasPOI` [known, disassembly]:

```
if timeToNextPOI > 0:
    timeToNextPOI -= dt
    if timeToNextPOI <= 0:
        c = centre(zone box); e = size(zone box); d = flock.target - c
        per axis: if d > e or d < -e:  e *= 0.01
        poiPos = c + (unit() - 0.5) * e                  // x, y, z draws
        poiTimeLeft = minPOI + unit() * (maxPOI - minPOI)
elif poiTimeLeft > 0:
    flock.targetOffset = poiSpeed * normalize(flock.target - poiPos)
    poiTimeLeft -= dt
else:
    timeToNextPOI = nextMin + unit() * (nextMax - nextMin)
```

Constant S 007d4a70 = 0.01 [known]. `normalize` S 004d8bb0 has no zero-length guard [known]. The offset is
recomputed every tick of an active POI and **never reset** when it ends; it is added to the next target (§3.6)
[known: the only stores to flock +0x54..+0x5c are the constructor and S 006cdb7c..S 006cdb88]. A positive `poiSpeed`
shifts the target away from the POI by that many world units, a negative one toward it: the shipped fish (-1.0) are
drawn toward their POI, the birds (0.1) slightly away [inferred: sign of `target - poiPos`].

### 3.11 Per-frame update

`SwarmMgr::Update(tickFraction, frameDelta, frustum)` S 0069a920, from `Scene::Update` S 006805e0 with
`tickFraction = 1 - (nextTickTime - now) * (1 / tickLength)`, `frameDelta = Scene +0x58` (the simulation's frame
delta) and `frustum = Scene +0x5e0` [known: disassembly S 0068084f..S 00680878]:

```
visibleSwarmCount = 0
for each slot:
    swarm.InterpolateFrame(tickFraction)              // S 006cd630
    swarm.visible = TestAABB(frustum, flock.actorsMin..Max) != 1      // S 006cdbe0
    if visible:  idleTime = 0;  visibleSwarmCount += 1
    else:        idleTime += frameDelta
if visibleSwarmCount < maxSwarms:  TrySpawnSwarm(frustum, frameDelta)
```

`InterpolateFrame` → `SwarmFlock::UpdateRender(t)` S 007705c0: per actor `renderPos = prevPos + (pos - prevPos) * t`
(`Segment3::Lerp` S 00771c50) and `worldMatrix = FromQuaternion(orientation)` with translation `renderPos`
(S 00771d00); `actorsMin..Max` = AABB of the actors' `pos` (simulated, not interpolated). Then
`Swarm.bounds = actorsMin..Max` grown by `boundsMargin` (1.0) on every side [known].

`frameDelta` scales with the game speed and is 0 while the simulation stands still (`animation-models.md`, "The time
record") [inferred], so the spawn countdown and the out-of-view timer run in game time.

### 3.12 Despawn

A swarm is deleted at the first logic tick after its `idleTime` exceeds `swarmTimeout` (10 s with the file) [known]
S 006998c0. Swarms that come into view reset the timer. `DeleteAllSwarms` S 00699c50 empties the list when the zones
are rebuilt and in the destructor [known]. The total number of swarms is not limited, only the visible count gates new
spawns [known].

### 3.13 Drawing, shadow and debug overlay

- **Main pass.** `Scene::RenderPasses` S 0067eb20, pass bit 0x40 (the `SceneDetail` pass "animals, then ambient
  swarms", `rendering.md` §3.1): `AnimalMgr` S 0069ad40, then `SwarmMgr::Render` S 00699ac0, which calls S 0064b9c0
  with `ECX = swarm` and argument 0 for every visible swarm [known]. S 0064b9c0 is a single `RET 4` shared by many
  empty functions (identical-code folding) [known]. Nothing is drawn.
- **Shadow pass.** Slot 0 `RenderWithExternalEffect(effect, lightFrustum)` S 00699af0: `effect +0x44(2)`, then
  `swarmCount` times a loop over all swarms calling the same empty function for each swarm whose flock box is in the
  light frustum (S 006cd930), then `effect +0x48()` [known]. Slot 1 `GetVisibleSwarmBounds(aabb)` S 00699bf0 merges
  the `bounds` of every visible swarm into the scene box that `ShadowManager::UpdateMatrices` S 0069e340 fits the
  light matrices to; so with the gate set, invisible flocks would still widen the shadow map's area [inferred: the
  box feeds `BuildFocusPoints` S 0076a1f0]. Slot 2 `AddVisibleSwarmBoxes` S 00699b90 adds the same boxes to a
  triangle list; its caller is [TODO].
- **No assets.** No swarm function and no `flocks.xml` attribute names a model, texture, animation or shader; the
  actors' orientation never leaves identity [known]. The only data file read is `flocks.xml` [known].
- **Debug overlay.** `Scene::RenderDebugOverlays` S 00683850 calls `SwarmMgr::DebugDraw` S 00699950 when
  `Scene +0x520` is set, the variable `AmbientAnimals` of the group `SceneInfo` (constructed in `Scene::ctor`
  S 0067fb40 at S 0067fe65, default off; group name from `map-editor-devtools.md` §3.13) [known]. Per visible swarm (S 006cd850, S 00770e10,
  S 00771d40 with flags 1): per actor a line from its world position along `velocity` in (1, 1, 0, 0.5) and a white
  sphere of radius 0.125 with the actor's world matrix; the actors' AABB in (0.5, 0.5, 0.5); a sphere of radius 0.25
  at `target` in (0.75, 0.75, 0.75); a yellow line `target` → `target + avgVelocity`; the text `NumActors: %d` at
  (16, 100); with an active POI a magenta line `target` → `poiPos`. Then every zone box: flight (1, 1, 0.5), water
  (0.5, 0.5, 1), ground (1, 0.75, 0.3). The behaviour parameter text needs `debugBehaviour >= 0`, which nothing sets
  [known].

### 3.14 Random generator and draw order

One `ai::math::RandomGenerator` (Park–Miller, `particles.md` §2.9) at `SwarmMgr +0x8` serves the manager, every swarm
(pointer at `Swarm +0x28`) and every flock [known] S 0069a260, S 006cd6b0. It is seeded with `SetSeed(this)`, the
manager's heap address [known] S 0069ab2b, so the sequence differs from run to run [inferred]. Draws, in order:

| When | Draws |
|---|---|
| countdown at or below 0 (per frame) | 1: delay |
| countdown expired, zones exist | 1: zone (`NextInRange`); 6: spawn box (3 corner, 3 size) |
| swarm created | 1 actor count (only without `numActors` and with `minCount < maxCount`); 3 per actor (x, y, z); 1 POI wait (with `hasPOI`) |
| per tick, per swarm with `hasPOI` | 4 when a POI starts (x, y, z, duration); 1 when a wait starts |

[known] S 0069a320, S 00699ed0, S 007702c0, S 00770640, S 006cd6b0, S 006cd950. `unit()` returns
`(state mod 1000001) / 1000000`, at most 1.000001 [known, `particles.md` §2.9].

---

## 4. Update order

| Moment | Call | Work |
|---|---|---|
| scene init | `SwarmMgr::CreateInstance` S 0069abb0 | construct, read `flocks.xml`; shadow caster registration (layer 6) |
| world load end, logic init end | `BuildSpawnZones` S 0069a3f0 | delete swarms, rebuild zones (gated) |
| each logic tick (`Scene::SyncLogicTick` step 5, after ships) | `SyncAndRemoveTimedOutSwarms(tickLength)` S 006998c0 | time-outs, then per swarm: actors simulate, neighbour pairs, target, POI |
| each frame (`Scene::Update` step 6, after ship visibility, before projectiles) | `SwarmMgr::Update` S 0069a920 | interpolation, AABB, visibility, idle timers, spawn attempt |
| each frame with a shadow map (shader level > 1, shadow level ≥ 2) | slot 1 for every caster; slot 0 only when the caster mask holds 0x40 (mask 0x3ff, `rendering.md` §3.13) | bounds into the shadow fit; empty draw |
| each frame, every view whose pass mask holds bit 0x40 | `SwarmMgr::Render` S 00699ac0 | empty draw |
| each frame with `SceneInfo/AmbientAnimals` | `SwarmMgr::DebugDraw` S 00699950 | wireframes |
| scene shutdown | `DestroyInstance` S 0069a230 | |

[known] for the calls (S 00680550, S 006805e0, S 0067eb20, S 006810b0, S 00683850); every row after the first stops at
the gate in this build (§3.1).

---

## 5. Inputs and outputs

**Consumes**: `flocks.xml`; at world load the map size, the grid state bit 0x4 of every cell and the terrain heights
(`g_TerrainGrid`), the render water constants; per tick the tick length; per frame the tick fraction, the frame
delta and the view frustum [known].

**Produces**: nothing visible in this build. With the gate set: actor positions and world matrices (no drawer),
swarm bounds for the shadow fit, debug wireframes [known].

---

## 6. Data-driven parameters

`[data]\settings\flocks.xml` (decrypted copy: `game/settings/flocks.xml`) [known, file; readers known at the
addresses given]:

| Element | Attribute | File value | Read by | Effect |
|---|---|---|---|---|
| `Flocks` | `maxFlocks` | 10 | **nothing** | the code asks for `maxSwarms`, so the limit stays 5 |
| `Flocks` | `maxSwarms` | (absent) | `LoadSettings` S 0069a9c0 | visible-swarm limit for spawning, default 5 |
| `Flocks` | `minSpawn`, `maxSpawn` | 10.0, 30.0 | S 0069a9c0 | spawn delay range, seconds (defaults 5.0, 30.0) |
| `Flocks` | `swarmTimeout` | 10.0 | S 0069a9c0 | out-of-view time before deletion (default 15.0) |
| `Bird`, `Fish`, `Bug` | (element name) | | nothing | the node is chosen by `zone` only |
| all three | `zone` | `flight`, `water`, `ground` | `FindZoneXmlNode` S 00699ca0 | first node whose value matches the zone type; `ground` zones do not exist |
| `Bird`, `Fish` | `minCount`, `maxCount` | 8–16, 8–20 | `LoadFromXml` S 007702c0 | actor count, inclusive random |
| `Bug` | `numActors` | 12 | S 007702c0 | fixed actor count, takes precedence |
| all three | `startMin`, `startMax` | `-1 -1 -1`, `1 1 1` | S 007702c0 | read, then overwritten by the zone box: no effect |
| `Bird`, `Fish` | `hasPOI` | `true` | `Swarm::ctor` S 006cd6b0 | POI cycle; exact `true`/`false` only |
| `Bird`, `Fish` | `nextMin`, `nextMax` | 5–20, 2–5 | S 006cd6b0 | wait between POIs, seconds |
| `Bird`, `Fish` | `minPOI`, `maxPOI` | 2–8, 1–3 | S 006cd6b0 | POI duration, seconds |
| `Bird`, `Fish` | `poiSpeed` | 0.1, -1.0 | S 006cd6b0 | target offset length (§3.10) |
| `Evade` | `minRange`, `maxRange` | Bird 0.0/1.0, Fish 1.0/3.5, Bug 1.0/3.0 | S 007702c0 | Evade weights (defaults 0.0/1.0) |
| `Pack` | `distance`, `returnStr` | Bird 1.0/0.05, Fish 3.0/0.3, Bug 1.5/0.2 | S 007702c0 | Pack threshold and scores (defaults 0.75/0.001) |
| `MatchSpeed` | `weight` | Bird 1.0, Fish 0.8, Bug 0.4 | S 007702c0 | stored, **unused** |
| `Evade`, `Pack`, `MatchSpeed` | `influence` | (absent) | S 007702c0 | score factor, 1.0 when the element exists and the attribute does not; 0 without the element |

Constants in code: neighbour radius 2.0, steer gain 1.0, steer budget 2.0 per tick, Evade factor 10, Pack target
factor 0.1, MatchSpeed `0.5 c + 0.5`, scatter 0.45 of the spawn box, spawn box 0.1 + 0.15 r of the zone, POI shrink
0.01, swarm bounds margin 1.0, flight band height 2.0 above the highest cell, water band -3.0 .. -0.1, minimum water
rectangle 4 x 4 cells, zone pick range `n + n/4` [known, §3].

---

## 7. Save and load

Nothing of the swarm system is saved [inferred: no swarm state in the save sections, `save-format.md`]. A save load
ends with `OnWorldLoadStateChanged(true)`, which would rebuild the zones and delete all swarms [known] S 0067eed0.

---

## 8. Determinism notes

- Presentation only: no simulation object is read beyond the grid states and terrain heights at world load, none is
  written, and the simulation's generator is not used [known: §11 functions].
- The generator is seeded from a heap address and advanced by frame-rate-dependent calls (spawn attempts every frame,
  visibility from the camera), so two machines or two runs differ [inferred]. A reimplementation need not reproduce
  any sequence.
- The one cross-system effect (with the gate set) is the shadow fit box (§3.13) [inferred].

---

## 9. Notes for a Godot reimplementation

- **Compatibility mode.** The original shows no swarms; draw none, and do not let swarm bounds touch the shadow fit.
- **Refined mode (reviving the design).** Everything below follows §3; the quirks marked *fix* are bugs of the
  original that a refined mode can correct.
  - Zones: build water rectangles from grid bit 0x4 with the growth of §3.3 and one flight band over the whole map
    at `hmax .. hmax + 2` world units. *Fix:* add ground zones (the file has `<Bug zone="ground">`, the debug colour
    exists, the builder does not), use the map's own water level instead of -0.1/-3.0, and clip fish boxes to the
    terrain (the box spans -3.0 .. -0.1 even over shallow water).
  - Spawning: frame-time countdown `U(minSpawn, maxSpawn)`; zone pick `NextInRange(0, n + n/4)` clamped to the flight
    zone; spawn box as §3.4, accepted only if outside the camera frustum (`Camera3D` frustum planes); retry every
    frame. Visible-swarm limit 5 (*fix:* read `maxFlocks` too).
  - Simulation in C#: a 10 Hz fixed step (the logic tick) with `prevPos`/`pos` and per-frame linear interpolation by
    the tick fraction. Per actor: behaviours in priority order with `AddSteering` (score += influence × strength;
    vector into the mean while the budget 2.0 lasts), one bubble pass on the scores, `v += (mean − v) · dt`,
    `p = clamp(p + v dt, zone box)`. Neighbour lists of up to 6 within 2.0 world units, built after the step and
    used on the next one (*fix:* a correct sorted insert; include the last actor in the target).
  - Despawn after `swarmTimeout` seconds out of view (frame time), checked on the tick.
  - Drawing: the original has no assets; pick a bird and a fish model, orient each actor along its velocity (the
    original never rotates), and use a `MultiMesh` per swarm (8–20 instances) with a simple flap or swim animation in
    the vertex shader. Fish move 0.1 to 3.0 units below the water plane and are seen through it.
- **Data.** `flocks.xml` is encrypted in the install; read it with the project's decryptor or ship an equivalent
  table. Accept both `maxFlocks` and `maxSwarms`.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Caller of `SwarmMgr` caster slot 2 (`AddVisibleSwarmBoxes` S 00699b90) | static: indirect calls through `+0x8` on the shadow caster entries (`ShadowManager +0x3f4`) or on `IShadowCaster` pointers program-wide |
| 2 | Caller of behaviour slot 1 (the validate functions S 00772260, S 00772340) | static: indirect calls through `+0x4` on `SwarmBehaviour` pointers; none in the functions of §11 |
| 3 | Reader of `SwarmActor +0x84` (1.0) and of `SwarmActorNeighbors +0x54` | static: loads at those offsets on actor pointers outside S 00770200..S 007728b0 (none inside) |
| 4 | What the empty per-swarm draw drew in the source (models, sizes) | not in this binary; the sister title's executable (Settlers II 10th Anniversary) could carry a non-empty version — static comparison of its `SwarmMgr::Render` |
| 5 | Whether `SyncLogicTick` runs exactly once per logic tick | `rendering.md` §4.2 (its caller is a scene interface slot) |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 0069abb0 | `S2CG::SwarmMgr::CreateInstance` | `new SwarmMgr` (0x48) into S 0088d864 |
| 006998b0 | `SwarmMgr::GetInstance` | singleton getter |
| 0069a230 | `SwarmMgr::DestroyInstance` | delete singleton |
| 0069ab00 | `SwarmMgr::ctor` | defaults, generator seed, gate 0 |
| 0069a9c0 | `SwarmMgr::LoadSettings` | `flocks.xml` root attributes |
| 00699e10 | `SwarmMgr::dtor` | free swarms, document, arrays |
| 0069a3f0 | `SwarmMgr::BuildSpawnZones` | water rectangles, flight band |
| 00699dc0 | `SwarmSpawnZone_ctor` | zero box, type 0, cells -1 |
| 00699ca0 | `SwarmMgr::FindZoneXmlNode` | zone type → XML node |
| 0069a920 | `SwarmMgr::Update` | per frame: interpolation, visibility, idle, spawn |
| 0069a320 | `SwarmMgr::TrySpawnSwarm` | countdown, zone pick |
| 00699ed0 | `SwarmMgr::ChooseOffscreenFlockBox` | random sub-box, true when out of view |
| 0069a260 | `SwarmMgr::SpawnSwarm` | construct and register a swarm |
| 006998c0 | `SwarmMgr::SyncAndRemoveTimedOutSwarms` | per tick: time-outs, swarm updates |
| 00699c50 | `SwarmMgr::DeleteAllSwarms` | |
| 00699ac0 | `SwarmMgr::Render` | main pass, empty per-swarm call |
| 00699af0 | `SwarmMgr::RenderWithExternalEffect` | shadow caster slot 0, empty per-swarm call |
| 00699bf0, 00699b90 | `SwarmMgr::GetVisibleSwarmBounds` / `AddVisibleSwarmBoxes` | shadow caster slots 1, 2 |
| 00699950 | `SwarmMgr::DebugDraw` | swarms, zone boxes |
| 00699d40, 0069a060, 0069a160, 0069a0e0, 0069a1a0 | `SwarmSlotArray::Allocate` / `Reserve` / `PushBack`, `SwarmSpawnZoneArray::Allocate` / `Reserve` | arrays |
| 006cd6b0 | `S2CG::Swarm::ctor` | flock, POI parameters |
| 006cd8f0 | `Swarm::scalar_deleting_dtor` | |
| 006cd950 | `Swarm::Update` | per tick: flock step, POI |
| 006cd630 | `Swarm::InterpolateFrame` | per frame: interpolation, bounds |
| 006cdbe0, 006cd930 | `Swarm::UpdateVisible` / `IsFlockInFrustum` | frustum test of the actors' AABB |
| 006cd850 | `Swarm::DebugDraw` | flock debug, POI line |
| 00770d20 | `ai::render::SwarmFlock::ctor` | defaults, behaviours |
| 00770b40 | `SwarmFlock::CreateBehaviours` | Evade, Pack, MatchSpeed |
| 007702c0 | `SwarmFlock::LoadFromXml` | count, start box, behaviour parameters |
| 00770770 | `SwarmFlock::Init` | zone box, actors, scatter |
| 00770470, 00770640 | `SwarmFlock::CreateActors` / `ScatterActors` | |
| 007707c0 | `SwarmFlock::Update` | per tick: simulate, neighbours, target |
| 007705c0 | `SwarmFlock::UpdateRender` | per frame: render transforms, AABB |
| 00770540 | `SwarmFlock::Release` | destructor body |
| 00770e10 | `SwarmFlock::DebugDraw` | |
| 00771780, 00771260 | `SwarmActor::ctor` / `dtor` | |
| 00771400 | `SwarmActor::InitBehaviours` | entries, order |
| 00771890 | `SwarmActor::SetPositionAndVelocity` | teleport, neighbour reset |
| 00771900 | `SwarmActor::Simulate` | behaviours, sort, integrate, clamp |
| 00771510 | `SwarmActor::AddSteering` | score, budget, steering sum |
| 00771d00 | `SwarmActor::UpdateRenderTransform` | lerp, world matrix |
| 00771c50 | `ai::math::Segment3::Lerp` | |
| 00771d40 | `SwarmActor::DebugDraw` | |
| 00771720, 00771360 | `SwarmActorNeighbors::ctor` / `ResetFltMaxBlock` | |
| 007712a0, 007715c0 | `SwarmActorNeighbors::Insert` / `ComputeAndReset` | neighbour list |
| 007721d0, 007722b0, 00772390 | `SwarmBehaviourEvade::ctor` / `SwarmBehaviourPack::ctor` / `SwarmBehaviourMatchSpeed::ctor` | |
| 007725f0, 00772780, 00772540 | `Evade::Apply` / `Pack::Apply` / `MatchSpeed::Apply` | the three rules |
| 00772260, 00772340 | `SwarmBehaviourEvade_Validate` / `SwarmBehaviourPack_Validate` | parameter order and clamps |
| 00772440, 007724e0 | `Evade::DebugDraw` / `Pack::DebugDraw` | range spheres |
| 00772400 | `SwarmBehaviour::scalar_deleting_dtor` | |
| 0067eed0, 0067ef40 | `Scene::OnWorldLoadStateChanged` / `OnLogicInitStateChanged` | zone rebuild triggers |
| 00680550, 006805e0, 0067eb20, 00683850 | `Scene::SyncLogicTick` / `Update` / `RenderPasses` / `RenderDebugOverlays` | callers |
| 0069e2a0, 0069e340 | `S2CG::ShadowManager::RenderCasters` / `UpdateMatrices` | caster slots 0, 1 |
| 004e0540 | `ai::render::Frustum::TestAABB` | 1 outside, 2 inside or crossing |
| 0064b9c0 | (shared empty function, `RET 4`) | the per-swarm draw |

Names given in this pass (earlier map names in brackets): `SwarmMgr::GetInstance` (`Singleton_0088d864_Get`),
`SwarmMgr::DestroyInstance` (`Singleton_0088d864_Destroy`), `SwarmMgr::ChooseOffscreenFlockBox` (`PickVisibleSpawnBox`),
`Swarm::InterpolateFrame` (`Swarm::Tick`); fields `Swarm::boundsMargin` (`field24`), `SwarmMgr +0x44` (`unk44`).
