# Particle effects: the `.pfx` format, simulation and rendering

Specification of the particle system of the match and of the 3D lobby: the effect file format, the particle
simulation, the vertex builders, the shader passes and the places that start effects. Namespaces `ai::render`
(emitter, particles, curves, manager), `ai::rendering` (the quad renderers), `ai::gfx` (`EffectScriptMgr`, the
effect name table), `S2CG` (the scene objects that own effects), `Lobby` (the lobby's own emitter holder).
Binary: `sadk_noav.exe`; "S 00xxxxxx" is a static address in it.

Tags: **[known]** = read directly in the decompiled code or the disassembly at the address given, in the bytes at
the address given, or in the named data file. **[inferred]** = one step of reasoning from what is visible.
**[TODO]** = open, with what would settle it. Nothing here was observed in the running game.

Related documents (not repeated here): `docs/sim/rendering.md` (frame structure §3.1, fog and light §3.13, the
scene time block §2.2, the per-frame order §4.3, the double draw of particles with the post processor),
`docs/sim/animation-models.md` §3.12 (animation events `<Particle start duration name slot>`),
`docs/sim/formats-inventory.md` §2.5 and §3.3 (first description of the format; this document supersedes it),
`docs/sim/navy.md` §2.3 (sea routes), `docs/sim/map-resources.md` (ground resources, exploration),
`docs/sim/lobby-world-client.md` (the lobby scene).

---

## 1. Purpose and scope

A particle effect is pure presentation: it never feeds a value back into the simulation [inferred: no writer into a
logic object was found in any function of this document]. Its work:

- read one emitter definition per `.pfx` file (`[data]\scripts\effects\<name>.pfx`, 64 files in the install);
- keep a fixed pool of particles per emitter; spawn them staggered, move and fade them with four curves over their
  normalised life, recycle them while the emitter emits, retire them when it stops;
- draw them as camera-facing quads or as flat horizontal quads, optionally as a flip-book, from one texture atlas,
  with one of six passes of `particle_shader.fx`, sorted back to front;
- start, move, hide and stop emitters on behalf of buildings, settlers, ships, projectiles, map objects, effect
  movies, animation events, map scripts, the resource hints of the landscape and the lobby.

Out of scope: the weather / environment particle layer of `CEnviromentMgr` (never created in this build,
`rendering.md` §3.1), the PhysX particle data of the lobby physics, the effect movie timing of `effectMovies.xml`
beyond the point where it starts an effect.

---

## 2. Data model

### 2.1 Object graph

```
ParticleManager (singleton, render singleton S 00887300 getter S 004dfc60)
  emitters[]            every live ParticleEmitter
  depthBuckets[20]      this frame's visible emitters, by squared camera distance
ParticleEmitter (200 bytes)            one per started effect, loaded from one .pfx
  params    -> ParticleEmitterParams   (0xcc)  spawn ranges + own random generator + emitter transform
  renderer  -> ParticleQuad / ParticleQuadAnim (0x24 / 0x28)  vertex builder + atlas rectangle
  particles -> Particle[particleCount] (0x78 each)
  curveSet  -> ParticleCurveSet (0x14)  4 curves: velocity, size, colour, opacity
S2CG::Particles (0x28)                 handle embedded in the owning scene object
```

[known] S 004e0950, S 004f0940, S 004f0de0, S 004f0f10, S 004f0c10, S 004f2b10.

### 2.2 `ai::render::ParticleEmitter` (200 bytes, vtable S 007e51fc)

| Offset | Field | Meaning | Evidence |
|---|---|---|---|
| +0x00 | vtable | [0] scalar deleting dtor S 004f0bf0, [1] `Update` S 004f0790, [2] `FillVertices` S 004f0530, [3] `Load` S 004f1150, [4] `Save` S 004f1310 | [known] bytes S 007e51fc |
| +0x04 | `nextInBucket` | link in the manager's depth bucket | [known] S 004e0660 |
| +0x08 | `camDistSq` | squared distance AABB centre to camera, this frame | [known] S 004e0660 |
| +0x0c | `name` | the resolved file path | [known] S 004f1150 |
| +0x28 | `startTime` | seconds; particle spawn times are relative to it | [known] S 004f04b0, S 004f0790 |
| +0x2c | `particleCount` | pool size, from the file | [known] S 004f1150 |
| +0x30 | `particles` | array of `Particle` | [known] S 004f0c10 |
| +0x34 | `visibleCount` | particles visible after the last `Update` | [known] S 004f0790 |
| +0x38 | `sortedHead` | visible particles, far to near | [known] S 004f0790 |
| +0x3c / +0x58 | params type name / `params` | | [known] S 004f1150 |
| +0x5c / +0x78 | renderer type name / `renderer` | | [known] S 004f1150 |
| +0x7c | particle type name | | [known] S 004f1150 |
| +0x98 | `passIndex` | pass of `particle_shader.fx`; the last i32 of a version `0002` file, else 0 | [known] S 004f1150, S 004dfdc0 |
| +0x9c | `curveSet` | | [known] S 004f0940 |
| +0xa0 | `active` (byte) | 0 = the manager neither updates nor draws the emitter (owners use it as "shown") | [known] S 004e0660, S 006964a0 |
| +0xa1 | `emitting` (byte) | 1 = particles are born and recycled; 0 = no particle is born, expired ones are retired (§3.5). Mapped as `looping` | [known] S 004f16c0 |
| +0xa4 | `bounds` | AABB min[3], max[3]; empty (`+FLT_MAX` / `-FLT_MAX`) after construction | [known] S 004f0940, S 007cb3b0, S 00882888 |
| +0xbc | `inFrustum` (byte) | result of this frame's frustum test | [known] S 004e0660 |
| +0xc0 | `autoDelete` (i32) | -1 after construction (never deleted by the manager); 0 = delete once it has shown a particle and shows none; 1 = has shown a particle while in state 0. Mapped as `everVisible` | [known] S 004f0940, S 004f0790, S 004e0660 |
| +0xc4 | `attachment` | the owning `S2CG::Particles`, or 0 once the owner let it go | [known] S 006964c0, S 00696400 |

### 2.3 `ai::render::ParticleEmitterParams` (0xcc, vtable S 007e53a0)

Vtable [known] bytes S 007e53a0: [0] property count S 004f2be0 (13), [1] and [2] `GetProperty` S 004f2c80,
[3] scalar deleting dtor S 004f3150, [4] `RandomTtl` S 004f3170, [5] `RandomSpawnDelay` S 004f31c0,
[6] `RandomSpawnPosition` S 004f36f0, [7] `RandomInitialVelocity` S 004f3740, [8] `RandomColor` S 004f3770,
[9] `RandomSize` S 004f3210, [10] `Load` S 004f3250, [11] `Save` S 004f3350.

| Offset | Field | Type | Default (ctor S 004f2d50) | In file |
|---|---|---|---|---|
| +0x04 | `maxLoops` | i32 | 0 | yes |
| +0x08 / +0x14 | `pos` / `posVar` | vec3 | 0 / 0 | yes |
| +0x20 / +0x2c | `vel` / `velVar` | vec3 | (0, 1, 0) / 0 | yes |
| +0x38 / +0x3c | `size` / `sizeVar` | f32 | 1 / 0 | yes |
| +0x40 / +0x44 | `ttl` / `ttlVar` | f32 seconds | 3 / 0 | yes |
| +0x48 / +0x4c | `spawn` / `spawnVar` | f32 seconds | 0.25 / 0 | yes |
| +0x50 / +0x60 | `color` / `colorVar` | vec4 RGBA | (1, 1, 1, 1) / 0 | yes |
| +0x70 | `randomSeed` | u32 | low 16 bits of the vtable pointer = **0x53a0** | no |
| +0x74 | `random` | `RandomGenerator` (state, seed) | constructed with 0x5432ace0, then `SetSeed(0x53a0)` | no |
| +0x7c | `emitterPos` | vec3 world | 0 | no |
| +0x88 | `emitterRotation` | quaternion (x, y, z, w) | (0, 0, 0, 1) (S 008828d4) | no |
| +0x98..+0xc8 | 13 property descriptors | `{vtable, type, name, ptr}` | names as in the column "Field" | no |

[known] S 004f2d50 (disassembly: `MOV EAX,[ESI]; AND EAX,0xffff` with `[ESI]` = 0x7e53a0), S 004f3250.

### 2.4 Renderers (`ai::rendering::ParticleQuad`, 0x24; `ParticleQuadAnim`, 0x28)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | property count | 2, or 3 for the animated ones |
| +0x08 | property descriptors | `m_texMin`, `m_texMax` (vec2), `m_numFrames` (int) |
| +0x0c | `texMin` (u, v) | atlas rectangle corner, from the file |
| +0x14 | `texMax` (u, v) | the opposite corner, from the file (may be smaller than `texMin`: mirrored) |
| +0x1c | `halfTexel` (u, v) | `0.5 / width`, `0.5 / height` of the particle atlas, read at construction |
| +0x24 | `numFrames` (ParticleQuadAnim only) | 1 after construction, then from the file |

[known] S 004f38e0, S 004f3800, S 004f3890, S 004f39a0, S 004f3a60.

Vtable slots used by the manager [known] bytes S 007e5420..S 007e5530, S 004dfdc0: `+0x10` register properties,
`+0x14` vertices per particle, `+0x18` primitives per particle, `+0x1c` D3D primitive type, `+0x20` build the
vertices of one particle, `+0x24` `Load`, `+0x28` `Save`.

| Type name (file) | Constructor | Vtable | Vertices / prims / prim type | Builder | `Load` |
|---|---|---|---|---|---|
| `Default` | `ParticleQuad::ctor` S 004f38e0 | S 007e5424 | 1 / 1 / 1 (point list) | `BuildVertices` S 004f3b20 | S 004f39a0 |
| `Decal` | `ctor_Decal` S 004f3a00 | S 007e5480 | 6 / 2 / 4 (triangle list) | `BuildBillboardVertices` S 004f3b80 | S 004f39a0 |
| `TexAnim` | `ParticleQuadAnim::ctor_TexAnim` S 004f3a40 | S 007e54ac | 6 / 2 / 4 | `ParticleQuadAnim::BuildBillboardVertices` S 004f3fc0 | S 004f3a60 |
| `GroundDecal` | `ctor_GroundDecal` S 004f3ae0 | S 007e54d8 | 6 / 2 / 4 | `BuildDirectionalVertices` S 004f43d0 | S 004f39a0 |
| `GroundDecalAnimated` | `ctor_GroundDecalAnimated` S 004f3b00 | S 007e5504 | 6 / 2 / 4 | `ParticleQuadAnim::BuildDirectionalVertices` S 004f4860 | S 004f3a60 |

[known]: the counts are the shared constant getters S 00416490 (1), S 004f23f0 (6), S 004f1ea0 (2),
S 004f2810 (4); that the third value is the D3D primitive type follows from the call order in `RenderAll`, where it
is called with the start vertex and the primitive count already pushed and its result becomes the first argument
of the vertex buffer's draw call [inferred, disassembly S 004e0123..S 004e0156]. A type name that is none of the
five leaves the renderer null and the following `Init` call crashes [known] S 004f0f10. `CreateRenderer(NULL)`
builds a `Decal` renderer named `Default`, a path the file loader never takes [known] S 004f0f10.

### 2.5 Curves (`ai::render::ParticleCurveSet` 0x14 and the curve classes)

`ParticleCurveSet` [known] S 004f2b10, vtable S 007e5218: `+0x04..+0x10` four curve pointers, one per channel,
each a constant curve of 1.0 after construction. Slot [1] `Evaluate(channel, t, values, count)` S 004f1bf0
applies the channel's curve to `count` floats in place; slot [4] `SetCurveType` S 004f2940; slot [10] `Load`
S 004f2430; slot [11] `Save` S 004f24c0.

| Channel (file order) | Applied to | Components |
|---|---|---|
| 0 | velocity | 3 |
| 1 | size | 1 |
| 2 | colour RGB | 3 |
| 3 | opacity (alpha) | 1 |

[known] S 004f1960 (four calls with channels 0..3 and counts 3, 1, 3, 1).

| Id | Class (size, vtable) | Properties in file order (type, default) | `Prepare` (slot 3) | `Evaluate` (slot 4) |
|---|---|---|---|---|
| 0 | Constant (0x10, S 007e52b0) | `constantValue` f32 1 | none | S 004f1db0 |
| 1 | Linear (0x1c, S 007e52dc) | `startValue` f32 1, `endValue` f32 1 | S 004f1e60 | S 004f1e70 |
| 2 | Cosine (0x1c, S 007e52f0) | `startValue` f32 1, `endValue` f32 1 | S 004f1e60 | S 004f1f40 |
| 3 | Cubic (0x34, S 007e531c) | `startValue`, `startSlope`, `endValue`, `endSlope`, all f32 1 | S 004f20a0 | S 004f20e0 |
| 4 | Hermite (0x40, S 007e5340) | `startValue`, `startSlope`, `endValue`, `endSlope` f32 1; `tension`, `bias` f32 0 | S 004f22c0 | S 004f2330 |
| 5 | NoiseLinear (0x28, S 007e5360) | `offset` **i32** 0, `phase` f32 1, `scale` f32 1, `bias` f32 0 | none | S 004f2700 → S 004f2620 |
| 6 | NoiseCosine (0x28, S 007e5380) | `offset` **i32** 0, `phase` f32 1, `scale` f32 1, `bias` f32 0 | none | S 004f2af0 → S 004f2830 |
| other | Constant | as id 0 (the stored type becomes 0) | | |

[known] constructors S 004f1d60, S 004f1dd0, S 004f1eb0, S 004f1fb0, S 004f2170, S 004f2530, S 004f2720 and the
switch in S 004f2940. Property descriptor value types: 0 Int (4 bytes), 1 Float (4), 2 Vec2 (8), 3 Vec3 (12),
4 Vec4 (16); `PropertyDesc::LoadValue` S 004f1ce0 reads that many bytes straight into the field the descriptor
points at.

### 2.6 `ai::render::Particle` (0x78, vtable S 007e5210)

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `index` | position in the pool |
| +0x08 | `camDistSq` | -1 when not visible, else squared distance to the camera |
| +0x0c | `nextSorted` | link of the emitter's far-to-near list |
| +0x10 | `curPos` | vec3 world, this frame |
| +0x1c | `curSize` | this frame |
| +0x20 | `curColor` | RGBA this frame |
| +0x30 | `lifeT` | normalised life of the current cycle, 0 ≤ t < 1 |
| +0x34 | `curVelocity` | start velocity × velocity curve, this frame |
| +0x40 | `spawned` (byte) | 1 = in a life cycle; 0 = retired |
| +0x44 | `spawnTime` | start of the current cycle, seconds after the emitter's `startTime` |
| +0x48 | `ttl` | life length of every cycle of this particle |
| +0x4c | `startPos` | vec3 world, drawn at birth |
| +0x58 | `velocity` | start velocity, vec3 world |
| +0x64 | `startColor` | RGBA |
| +0x74 | `startSize` | |

Vtable [known] bytes S 007e5210: [0] vector deleting dtor S 004f05f0, [1] `ApplyCurves` S 004f1960.

### 2.7 `ai::render::ParticleManager` (0x100)

| Offset | Field |
|---|---|
| +0x00 | particles drawn in the last `RenderAll` |
| +0x04, +0x08 | effect `particle_shader.fx`, technique table (`Default`, `ffp`) |
| +0x28 | dynamic vertex buffer "ParticleManager" (ring of 20000 vertices) |
| +0x30 | atlas texture `[data]\gfx\particles_texture.tga` |
| +0x74 | `TANGENT_LIGHT_VECTOR` value |
| +0x80..+0x90 | effect handles `TANGENT_LIGHT_VECTOR`, `VOLUME_MIN`, `VOLUME_MAX`, `VOLUME_CENTER`, `VOLUME_EX` |
| +0x94 | `time`: set to the scene's `gameTime` on every logic tick (`rendering.md` §4.2) |
| +0x98 | `disableAlphaBlend` (byte): when set, alpha blending is switched off after each pass begins ([TODO] writer) |
| +0x9c / +0xa0 / +0xa4 | emitter array count / capacity / data |
| +0xa8 / +0xac | squared distance range of the previous frame (min, max) |
| +0xb0 | `depthBuckets[20]` |

[known] S 004e0ad0, S 004dfdc0, S 004e0660, S 00680550.

### 2.8 `S2CG::Particles` (0x28): the owner's handle

`+0x04` effect index, `+0x08` effect name (std::string), `+0x24` emitter. Methods [known]:
`StartByIndex` S 006964c0, `StartByName` S 00696620, `Stop(immediate)` S 00696400, `SetVisible` S 006964a0
(writes emitter `active`), `SetEmitterLooping` S 00696480 (writes `emitting`), `SetEmitterPositionAndColor`
S 00696450 (position and rotation; the second argument is a quaternion, not a colour).

### 2.9 `ai::math::RandomGenerator` (8 bytes)

`+0x00` state, `+0x04` seed. A Park–Miller "minimal standard" generator [known] S 006ec410, S 006ec3a0, S 006ec2a0:

```
next():      state = (state * 16807) mod (2^31 - 1)        // carry form: lo/hi 16-bit halves, two folds
unit():      next(); return float(state mod 1000001) / 1000000.0     // 0 .. 1.000001
range(a,b):  next(); return a + (state mod (b - a + 1))     // unsigned modulo, a..b inclusive
SetSeed(s):  s &= 0x7fffffff
             n = number of set bits among bits 0..30 of s
             if n < 8:  for i in 0 .. 7-n:   s |=  1 << T[i]     // T = table S 007fd528
             if n > 24: for i in 0 .. 31-n:  s &= ~(1 << T[i])
             seed = s; state = (s == 0) ? 1 : s
T = 12, 23, 10, 25, 8, 27, 6, 29, 4, 30, 1, 22, 9, 13, 21, 0, 17, 26, 5, 15, 18, 28, 11, 2, 14, 3, 24, 7, 19, 16, 20, 31
```

The bit loop does not recount: a table bit that is already set counts as one of the `8 - n` additions [known].
So `SetSeed(0x53a0)` (6 bits) gives state 0x008053a0 (bit 12 already set, bit 23 added) [inferred: arithmetic].

---

## 3. Rules and algorithms

### 3.1 File format

One file = one emitter. Little-endian, no padding, no alignment. `str` = `u32 length` + `length` bytes, no
terminator; the reader copies into a 260-byte stack buffer without a bound check and keeps the bytes up to the
first zero (`NBase::File::ReadString` S 006e6960); `NBase::File::Read` S 006e6530 reads raw bytes. [known]

```
str   version              "0002" in all 64 files; only this value enables the trailing passIndex
str   paramsType           "Default" (the only type; anything else leaves params null -> crash)
--- ParticleEmitterParams::Load S 004f3250 (108 bytes)
i32   maxLoops             0 = endless; else the number of ttl periods a particle may start in (§3.5)
f32x3 pos                  spawn centre, emitter space
f32x3 posVar               spawn half range per axis
f32x3 vel                  start velocity, emitter space, units per second
f32x3 velVar               half range per axis
f32   size, sizeVar        quad edge length in world units, half range
f32   ttl, ttlVar          life of one cycle in seconds, half range
f32   spawn, spawnVar      spawn interval and extra delay in seconds, half range
f32x4 color, colorVar      RGBA 0..1, half range
--- renderer
str   rendererType         Default | Decal | TexAnim | GroundDecal | GroundDecalAnimated (case sensitive)
f32x2 texMin               atlas UV of the first frame's top-left corner (D3D convention, v down)
f32x2 texMax               atlas UV of the opposite corner
i32   numFrames            only for TexAnim and GroundDecalAnimated
--- particles
i32   particleCount        pool size
str   particleType         "Default" (the only type)
--- ParticleCurveSet::Load S 004f2430, channels velocity, size, color, opacity
4 x { i32 curveType; properties of that type in the order of §2.5 }
--- only when version == "0002"
i32   passIndex            pass of particle_shader.fx (§3.11); otherwise 0
```

After the params block: if `ttl - ttlVar <= 0`, then `ttlVar = max(ttl - 0.1, 0)` [known] S 004f3250 (no shipped
file triggers it).

**Grammar** (what the validation reader implements; every file of the install parses to exactly its last byte):

```
pfx        := str:version str:"Default" params renderer i32:count str:"Default" curve curve curve curve trailer
params     := i32 f32{3} f32{3} f32{3} f32{3} f32 f32 f32 f32 f32 f32 f32{4} f32{4}
renderer   := str:R f32{2} f32{2} [ i32 if R in {TexAnim, GroundDecalAnimated} ]
              ; R not in {Default, Decal, TexAnim, GroundDecal, GroundDecalAnimated} is invalid
curve      := i32:k body(k)
body(0)    := f32                      ; also for every k outside 0..6
body(1)    := f32 f32
body(2)    := f32 f32
body(3)    := f32 f32 f32 f32
body(4)    := f32 f32 f32 f32 f32 f32
body(5)    := i32 f32 f32 f32
body(6)    := i32 f32 f32 f32
trailer    := i32   if version == "0002"
            | ""    otherwise
str        := u32:n byte{n}            ; n < 260
```

The install's 64 files are 207 to 257 bytes long [known, files]. Statistics [known, files]: renderer `Decal` 49,
`TexAnim` 12, `GroundDecal` 2, `GroundDecalAnimated` 1, `Default` 0; pass 3 in 34 files, 2 in 16, 0 in 8, 1 in 6;
`maxLoops` 0 in 44, 1 in 18, 2 in 1, 5 in 1; curve types per channel: velocity {0: 17, 1: 35, 3: 12},
size {0: 12, 1: 7, 3: 40, 4: 5}, colour {0: 49, 1: 15}, opacity {0: 3, 1: 23, 3: 28, 4: 10}. Types 2, 5 and 6 are
not used. The per-file values are in §6.1.

### 3.2 Load sequence

[known] S 00685bb0 / S 00685e10, S 004e0950, S 004f1150, S 004f0c10, S 004f1820.

1. The caller names an effect. `EffectScriptMgr::FindEffectIndex` S 00685f00 lower-cases the name and looks it up
   in the table built at start-up by `ScanEffectNames` S 00686af0 (every `*.pfx` under `[data]\scripts\effects`,
   base name lower-cased; the table index is the effect id); not found = -1. `LoadEffectByIndex` S 00685e10 builds
   `[data]\scripts\effects\<table name>.pfx` and does not check the index (so -1 reads before the table
   [inferred]); `LoadEffectByName` S 00685bb0 checks the name and builds the path from the caller's spelling.
2. `ParticleManager::LoadEmitterFile` S 004e0950 opens the file (failure: returns null), constructs an emitter,
   calls `Restart(manager.time)` (no particles yet: only `startTime` is stored), calls `Load`, appends the emitter
   to the manager. **Every start loads the file again**; emitters are never shared or cached.
3. `Load`: name = path; version; params type → `CreateParams` (new params: generator seeded, §2.3) → params
   `Load`; renderer type → `CreateRenderer` → renderer `Init` (property registration) → renderer `Load`;
   `particleCount`; particle type → `CreateParticles`: allocate the pool, then for `n = 0..count-1`:
   `index = n`, `Spawn(params, (n + 1) * spawn)`; curves: for each channel read the type, `SetCurveType`
   (keeps the existing curve when the type is equal, else replaces it), read its properties; `Prepare` of the four
   curves (S 004f1bc0); `passIndex`; finally `Reset(params)` of every particle.
4. The caller then places the emitter and calls `Restart(startTime)` (§3.4). Everything drawn from the generator
   in step 3 is overwritten by that `Restart`, but it advances the generator: 13 draws per particle in
   `CreateParticles` and 11 in the final `Reset` [known: the draw counts of §3.3].

### 3.3 Random draws

Each draw is `base + var * (2r - 1)` with `r = unit()` of the params' own generator, one `r` per component in
component order [known] S 004f3170, S 004f31c0, S 004f3210, S 004f3410, S 004f34b0.

| Draw (params slot) | Value | Clamp | Draws |
|---|---|---|---|
| ttl ([4]) | `ttl ± ttlVar` | `>= 0.1` | 1 |
| spawn delay ([5]) | `spawn ± spawnVar` | `>= 0` | 1 |
| start position ([6]) | `R(q) · (pos ± posVar) + emitterPos` | none | 3 |
| start velocity ([7]) | `R(q) · (vel ± velVar)` | none | 3 |
| start colour ([8]) | `color ± colorVar` (RGBA) | none (clamped only when packed, §3.10) | 4 |
| size ([9]) | `size ± sizeVar` | none | 1 |

`R(q)` rotates by the emitter quaternion (`q · v · q⁻¹`, S 004f3620). The emitter transform is set by
`SetPosition` S 004f0730 (also adds the point to the AABB), `SetRotation` S 004f0760, or `SetTransform`
S 004f06c0 (both, then `Reset(params)` of every particle; used by the lobby only).

`Particle::Spawn(params, base)` S 004f1660 draws, in this order: ttl, `spawnTime = delay + base`, start position,
start velocity, start colour, start size; `spawned = 1` (13 draws). `Particle::Reset(params)` S 004f1820 draws start
position, start velocity, start colour, ttl (11 draws) and sets `startSize = 0`, `spawnTime = 0`, `spawned = 0`,
`curColor = (1, 1, 1, 1)`; `Reset(null)` sets zero position and velocity, white start colour, `ttl = 0` and the
same zeros without drawing.

### 3.4 Restart and seeding

`ParticleEmitter::Restart(startTime)` S 004f04b0 [known]: `startTime` is stored, the sorted list cleared; for
`n = 0..count-1`: `Reset(null)`, `Spawn(params, (n + 1) * spawn)`. So particle `n` begins its first cycle at

```
spawnTime_n = (n + 1) * spawn + max(0, spawn + spawnVar * (2r - 1))      // seconds after startTime
```

(one extra spawn interval on top of the stagger, because the delay draw is centred on `spawn` itself).
A file with `spawn = 0` and `spawnVar = 0` (`ExplorePos`, `HitDamage`) starts all particles at once.

Seeding [known]: the params generator starts with `SetSeed(0x53a0)` for every emitter. `Particles::StartByIndex`
and the Lua `createParticel` call `params.Reseed(randomSeed + trunc(x + y + z))` S 004f2c90 with the emitter's
world position, **after** `Restart` (disassembly S 006964c0, S 005aca40); so the random numbers of the first cycle
of a started effect depend only on the file, and those of the later re-draws (§3.5) also on the start position. The gate fire, the ship effects and
the lobby emitters are not reseeded.

### 3.5 Particle life cycle (`Particle::Update` S 004f16c0)

Called per particle from `ParticleEmitter::Update(time, cameraPos)` S 004f0790 with `elapsed = time - startTime`
and the emitter's `emitting` byte. Returns whether the particle is visible. [known: disassembly]

```
age = elapsed - spawnTime
if age < 0:                                         // not born yet
    if not emitting and age > -ttl: spawnTime += ttl   // pushed back: never born while not emitting
    startPos = drawPosition(); velocity = drawVelocity()   // re-drawn every frame until birth
    return invisible
loops = trunc(age / ttl)
if maxLoops > 0 and trunc(spawnTime / ttl) + loops >= maxLoops:
    return invisible                                 // nothing changes
if loops >= 1:
    if not emitting:
        spawned = 0; startPos = drawPosition(); return invisible     // retired
    startPos = drawPosition(); velocity = drawVelocity(); startColor = drawColor()
    if spawned == 0:                                 // re-arm a retired particle
        spawned = 1; spawnTime += (loops + 1) * ttl; startPos = drawPosition()
        return invisible
    spawnTime += loops * ttl                         // next cycle; ttl and size are kept
t = age / ttl - loops                                // with the age from the first line
lifeT = t; ApplyCurves(t); return visible
```

Consequences [inferred from the branches]:

- `emitting` is the emitter's on/off switch: while it is 0 no particle is born and expired particles are retired;
  particles in flight finish their cycle. Turning it on again re-arms retired particles one ttl later.
- A particle keeps its `ttl` and `startSize` for its whole existence; position, velocity and colour are re-drawn at
  every new cycle (and the start position and velocity on every frame before birth, so the birth position follows
  a moving emitter, but a born particle does not).
- With `maxLoops > 0` a cycle that starts at `s` (seconds after `startTime`) is shown only if
  `trunc(s / ttl) < maxLoops`. The check uses the stagger offset too, so with `maxLoops = 1` only particles whose
  first spawn time is below their own ttl are ever shown: `Resource_*` (ttl 0.8 ± 0.2, spawn 0.15 ± 0.08,
  30 particles) shows about the first four, `HitDamage` (spawn 0) shows all 30 once. A dead particle stays dead;
  the emitter's visible count then drops to 0 (deletion, §3.8).
- Nothing is integrated over time: the state at a frame follows from `elapsed` and the stored cycle values, so an
  emitter that was not updated for a while (off screen, §3.8) catches up in one step (`loops` may be > 1).

`ParticleEmitter::Update` S 004f0790 [known]: skipped when params, renderer or particles are missing; sets the AABB
to the emitter position, clears the visible count and the list; per particle: `camDistSq = -1`, update; if
visible: `camDistSq = |curPos - cameraPos|²`, insert into the list ordered by descending `camDistSq` (farthest
first), grow the AABB by `curPos ± curSize / 2` (cube), count it, and set `autoDelete` from 0 to 1.

### 3.6 Curve formulas

Every curve multiplies its input `v` in place: `v' = v * f(t)` [known] S 004f1bf0 and the evaluators of §2.5.
With `p0..p3` = `startValue`, `startSlope`, `endValue`, `endSlope` in file order:

| Id | `f(t)` |
|---|---|
| 0 | `constantValue` |
| 1 | `startValue + (endValue - startValue) * t` (`Prepare` stores the difference) |
| 2 | `startValue + (endValue - startValue) * (1 - cosLut(π t)) / 2` |
| 3 | `p0 + c1 t + c2 t² + c3 t³` with `c3 = p3 - p2 - p1 + p0`, `c2 = p1 - p0 - c3`, `c1 = p2 - p1` |
| 4 | `p0 (2t³ - 3t² + 1) + m0 (t³ - 2t² + t) + m1 (t³ - t²) + p2 (3t² - 2t³)` with `k = (1 - tension) / 2`, `m0 = k (1 + bias)(p0 - p1) + k (1 - bias)(p3 - p0)`, `m1 = k (1 + bias)(p3 - p0) + k (1 - bias)(p2 - p3)` |
| 5, 6 | `noise * scale + bias`, see below |

The cubic is the four-point cubic interpolation between `startValue` (`f(0) = p0`) and `endValue` (`f(1) = p2`),
with `startSlope` acting as the point before the start and `endSlope` as the point after the end; despite their
names both are values, not slopes [inferred: algebra of S 004f20a0, S 004f20e0]. The hermite curve also ends at
`p2`, but its tangents treat `endSlope` as the end point and `endValue` as the point after it [known: disassembly
S 004f22c0]; a reimplementation must copy the formula, not a textbook hermite. `Prepare` runs once after load
[known] S 004f1bc0.

`cosLut(x)` S 006e8a50 [known]: `sinTable[(round(x * 40.743664) + 64) & 255]`, table S 007fcd10 =
`sin(2π i / 256)` (40.743664 = 256 / 2π, float S 008829b4).

Noise (S 004f2620, S 004f2830) [known: disassembly], 32-bit wrapping integer arithmetic:

```
x = phase * t;  i = trunc(x);  f = x - i
L(j): n = j * 0x3a;  n ^= n << 13
      return 1 - ((n * (n * n * 0x3d73 + 0xc0ae5) + 0x208dd0d) & 0x7ffffff) * 2^-30   // 0.875 .. 1
noise = (1 - w) * L(i + offset) + w * L(i + offset + 1)
w = f                          (type 5)
w = (1 - cos(π f)) / 2         (type 6, library cosine)
```

The mask is 27 bits wide, so the lattice values lie in (0.875, 1], not in [-1, 1] as in the textbook hash
[known: constant 0x7ffffff at S 004f267e, 2^-30 = double S 007e5378].

### 3.7 Applying the curves (`Particle::ApplyCurves` S 004f1960)

[known: disassembly]

```
curVelocity = velocity * fVel(t)                    (per component)
curSize     = startSize * fSize(t)
curColor.rgb = startColor.rgb * fColor(t)
curColor.a   = startColor.a * fOpacity(t)
curPos      = startPos + curVelocity * (t * ttl)    // = curved velocity of this instant times the age
```

The position is not an integral of the velocity: a velocity curve rising from 0.1 to 3 (fires, smoke) makes the
displacement grow faster than linearly, `age * vel * f(t)`.

### 3.8 Ownership, visibility and deletion

[known] S 004e0660, S 00696400, S 006964c0, S 006964a0, S 00696480, S 004dfd40.

- An emitter is updated and drawn only when `active` is set and its AABB (from its last update, grown by every
  `SetPosition` since) passes the frustum test. `active = 0` freezes it: no update, no draw.
- `ParticleManager::CullAndSortEmitters` S 004e0660 runs once per frame (`Scene::Update`, `rendering.md` §4.3),
  over the emitter array from the end: an emitter with `autoDelete == 1` is **deleted** when its visible count is
  0 or `active` is 0. All others with `active` set are frustum-tested.
- `autoDelete` is -1 after construction, so an owned emitter is deleted only by its owner (owner destructors call
  `ParticleManager::RemoveEmitter` S 004dfd40 through S 006857c0). It becomes 0 in `Particles::Stop` and in Lua
  `createParticel`; the next update that sees a visible particle turns it into 1, and the first later frame with no
  visible particle deletes the emitter. An emitter set to 0 that never shows a particle again is never deleted
  [inferred from the branches].
- `Particles::Stop(immediate)` S 00696400: `autoDelete = 0`; immediate: `emitting = 0`, detach (`attachment = 0`,
  handle reset): the effect fades out naturally and deletes itself. Not immediate: detach only when
  `maxLoops != 0` (the effect runs out on its own); an endless effect stays attached and keeps emitting.
- `Particles::StartByIndex(index, active, emitting, startTime, pos, rot)` S 006964c0: with an emitter already
  attached it only updates `emitting`; else load, set `active` and `emitting`, `SetPosition`, `SetRotation`,
  `Restart(startTime)`, attach, reseed (§3.4). `StartByName` S 00696620 resolves the name and calls it, so on a
  running handle it changes nothing but `emitting`: an owner may call it every frame (the building and soldier
  buffs do) and the effect is not restarted.
- A `Stop(false)` on an endless effect (`maxLoops == 0`) has no visible effect: the emitter stays attached and
  keeps emitting; only its `autoDelete` drops to 0, and an emitter that always shows particles is never deleted.
- `S2CG::Particles::dtor` S 00696570 always stops as `Stop(true)` does (`autoDelete = 0`, `emitting = 0`,
  detach), whatever the effect's `maxLoops`: an owner that dies lets its effects fade out.

### 3.9 Sorting and draw order

[known] S 004e0660, S 004dfdc0.

- Per emitter: `d = |AABB centre - camera|²`. Bucket `b = clamp(trunc((d - prevMin) * 20 / (prevMax - prevMin)),
  0, 19)` with the minimum and maximum `d` of the previous frame's visible emitters (0 and 25000 when they were
  equal). Inside a bucket the emitters are kept in **ascending** `d`.
- `RenderAll` draws bucket 19 down to 0 (far buckets first) and each bucket from its head, i.e. near to far
  inside the bucket. The particles of an emitter are drawn far to near (§3.5).
- Emitters with the same pass share one `BeginPass`; a pass change ends the previous pass.

### 3.10 Vertex building

Vertex (32 bytes) [known] S 004f3b80, `particle_shader.fx`: `float3 position` (world), `D3DCOLOR color`,
`float2 uv` (TEXCOORD0), `float2 corner` (TEXCOORD1, ±1). Six vertices per quad, two triangles:

```
v0 = P - sA + sB   uv (u0, v0)  corner (-1,  1)
v1 = P - sA - sB   uv (u0, v1)  corner (-1, -1)
v2 = P + sA + sB   uv (u1, v0)  corner ( 1,  1)
v3 = P + sA - sB   uv (u1, v1)  corner ( 1, -1)
v4 = v2, v5 = v1                triangles (v0, v1, v2), (v3, v4, v5)
s  = curSize / 2,  P = curPos
```

Both triangles are counter-clockwise on screen for a camera-facing quad, the front face under the cull mode 2
(`D3DCULL_CW`) that `RenderAll` sets [inferred: winding; cull mode [known] S 004dfdc0, `rendering.md` §3.13].

| Renderer | Axis A | Axis B | UV |
|---|---|---|---|
| `Decal` | camera right | camera up | `u0 = texMin.u + h.u`, `u1 = texMax.u + h.u`, `v0 = texMin.v + h.v`, `v1 = texMax.v + h.v`; `h` = half texel (`0.5 / 512`) |
| `TexAnim` | camera right | camera up | frame `k = trunc((numFrames - 1) * t + 0.5)`; `w = texMax.u - texMin.u`; `u0 = texMin.u + k w`, `u1 = texMax.u + k w`, `v0 = texMin.v`, `v1 = texMax.v` |
| `GroundDecal` | `up × d` = `(d.z, 0, -d.x)` | `d` | as `Decal` without the half texel |
| `GroundDecalAnimated` | `up × d` | `d` | as `TexAnim` |
| `Default` | one point vertex at `P`, colour white × fade, uv 0 | | |

`d` = the horizontal direction of `curVelocity` (`(v.x, 0, v.z)` normalised with the table square root S 006e8a20,
about 0.05 % high), `(0, 0, 1)` when both are 0; `up = (0, 1, 0)` (S 00882864). So the ground quads lie flat at the
particle's height (no terrain projection) and are stretched along their horizontal motion; their texture's `v`
axis points against `d` [known] S 004f43d0, S 004f4860.

Camera axes [known] S 004dfdc0, S 006ebef0, S 004dfce0: the upper 3 × 3 of the device view matrix, transposed, its
third row negated; rows 0 and 1 are the camera's right and up vectors in world space [inferred: D3D look-at
layout], passed to every builder.

The flip-book frame is a function of the cycle's life `t`, not of a frame rate: the frames are spread over one
cycle, frame 0 for `t < 0.5 / (numFrames - 1)`, the last frame from `t >= (numFrames - 1.5) / (numFrames - 1)`.
Frames lie side by side to the right of the first one in the atlas.

Colour [known] S 004f3b80, S 004a8380: `rgba = (curColor.rgb, curColor.a * fade)`, each component clamped to 0..1,
times 255, rounded to nearest, packed as D3DCOLOR (A R G B).

**Distance fade** (`FillVertices` S 004f0530) [known]: with the device fog range `start = device +0x320`,
`end = device +0x324` (`SetFogRange` S 004d3ae0, the environment's fog values, `rendering.md` §3.13):

```
fade = 1 - (camDistSq - start²) / (end² - start²)      if end² > start², else 1
```

unclamped before packing, so particles nearer than `start` get alpha factors above 1 (clamped by the pack) and
particles beyond `end` vanish. The scene's fog is switched off around the particle pass (`rendering.md` §3.1);
this fade replaces it.

### 3.11 Shader passes (`particle_shader.fx`, technique `Default`)

[known, file `game/gfx/fx_20/particle_shader.fx`] All passes: Z test on, no Z write, vertex position transformed
by `g_ViewProjectionMatrix` (the effect's world matrix is the identity, S 004dfdc0). Sampler 0 = the atlas (wrap,
linear). `L` = `g_LightColor.rgb`, `Amb` = `g_Ambient.rgb`, `c` = vertex colour, `T0` = atlas sample.

| Pass | Name | Blend | Colour |
|---|---|---|---|
| 0 | `FlatDecal` | `SrcAlpha`, `InvSrcAlpha` | `rgb = (Amb + L) * c.rgb * T0.rgb`, `a = c.a * T0.a` |
| 1 | `Spherical` | `SrcAlpha`, `InvSrcAlpha` | `c * T0`, `rgb *= L * saturate(dot(2 N.xyz - 1, TLV) * N.a) + Amb`; `N` = sampler 1 at `uv1 = (0.5 + 0.5 corner.x, 0.5 - 0.5 corner.y)` |
| 2 | `VolumeSphere` | `SrcAlpha`, `InvSrcAlpha` | as pass 1, with `fDot += w * (dot(normalize(n), -g_MainLight) - fDot)`, `n = position - (0, VOLUME_MIN.y / VOLUME_EX.y, 0)`, `w = 1 - abs(position.y - VOLUME_MIN.y) / (2 VOLUME_EX.y)` (per vertex) |
| 3 | `FlatDecalAdditive` | `One`, `One` | `rgb = c.rgb * T0.rgb * c.a`; the texture alpha has no effect |
| 4 | `FlatNormal` | `SrcAlpha`, `InvSrcAlpha` | `N = 2 T0.rgb - 1`, `rgb = (L * saturate(dot(N, -g_MainLight)) + Amb) * c.rgb`, `a = c.a` |
| 5 | `FlatDecalAlphaTest` | none, alpha test `>= 128` | as pass 0 |

In pass 0 the tint `(Amb + L) * c.rgb` is computed in the vertex shader and leaves it through a `COLOR0` output,
which Direct3D 9 clamps to 0..1 for `vs_2_0` [inferred: D3D9 rule]; with the shipped light (ambient 0.6/0.5/0.6
plus light 0.94/0.90/0.78, `rendering.md` §6.6) a white particle stays white, a grey one is brightened.
Passes 4 and 5 are not used by any shipped file. `VOLUME_*` are set per emitter: `VOLUME_MIN`, `VOLUME_MAX` = its
AABB, `VOLUME_CENTER` = the AABB centre, `VOLUME_EX` = the AABB size, at least 0.001 per axis [known] S 004dfdc0.
`TANGENT_LIGHT_VECTOR` (`TLV`) = the negated directional light direction expressed in camera axes
(right, up, towards the viewer) [known] S 004dfdc0, S 004dfce0; that is the frame of a screen-space sphere normal
map. The expression `float3(0, VolumeMin.y, 0) / VolumeEx` is the shader's own precedence (a division, then a
subtraction), copied as written.

Sampler 1 of passes 1 and 2 is **never bound by the particle code** (the manager binds stage 0 only, and no code
references `sphere_normal.tga`), so these passes light the sprite with whatever texture an earlier draw left on
stage 1 [inferred: S 004dfdc0, S 004e0ad0 bind calls; string search]. `game/gfx/sphere_normal.tga` (512 × 512, a
hemisphere normal map: centre (0, 0, 1), top of the image +y, right +x, alpha 1 inside the disc) matches the
pass's texture coordinates exactly [known, file] and is the evident intent [inferred]. [TODO] what stage 1 holds in
the running game (read the texture bound on stage 1 during `RenderAll`).

With the post processor the passes also write the view depth to the second render target (`COLOR_OUT` with
`POSTFX`, `shared.inc`), and the whole particle pass is drawn twice per frame (`rendering.md` §4.3), each time
with an `Update` of every drawn emitter at the same time [known] S 004dfdc0, `rendering.md` §4.3.

The `ffp` technique (no shaders) draws `texture × vertex colour` in every pass; its additive pass blends
`SrcAlpha`, `One` with the vertex alpha [known, file]; it has no normal-mapped lighting and no ambient tint.

### 3.12 Texture atlas

One atlas for all effects: `[data]\gfx\particles_texture.tga` (`game/gfx/particles_texture.tga`), loaded once by
`ParticleManager::InitResources` S 004e0ad0 [known]. The file in the install is encrypted (`sadk` container,
`docs/asset-formats.md`); decrypted it is a 512 × 512 32-bit TGA with bottom-left origin [known, file]. The UVs in
the files use the D3D convention with `v = 0` at the top of the picture as displayed (D3DX honours the TGA origin)
[inferred]; with that reading every rectangle of the 64 files lands on drawn content [known, files]. Regions used
(pixels of 512): sparkle/star (259,3)-(343,87) and (270,13)-(337,80), RGB only, alpha 0 throughout (drawn with
pass 3); smoke puff (128,0)-(256,128); dust (64,32)-(92,64) and (64,32)-(96,64); saw dust (0,0)-(64,32); leaf
(64,0)-(92,32); water ring (3,0)-(61,63) and (34,67)-(61,93); fire flip-books 6 × (32 × 31) from (0,129) and
8 × (64 × 63) from (0,416); ship wake flip-book 16 × (32 × 32) on the bottom row, mirrored in v [known, files].

### 3.13 Who starts effects

[known for the call sites and the effect names; the trigger conditions of the rows not named in §3.14 are
summarised from the functions named and were not all re-read line by line, so they count as [inferred]; the
`Stop(false)` of the demolition and fight rows passes a register that holds 0 in those functions [inferred]]

| Owner | Effect | Start | Position, rotation | Stop |
|---|---|---|---|---|
| building fire points `Building::UpdateFireEffects` S 006abbb0 | `BuildingFire` | each frame: the first `round(points × (1 - hp ratio))` fire points burn (`StartByName(..., active 1, emitting 1, time, fire point, identity)`); the points are `FIRE_03`, `FIRE_06`, ... or five fallback points (below) | fire point position, identity | `Stop(true)` on the others |
| building buffs `Building::Update` S 006abcf0 | `ShipSpeedUp` (four slots), `BuildingArmor`, `WorkerPause` | while the condition of its slot holds (`rendering.md` §3.9: mines without food need, armour, territory range, modified goods, production time, rest time); only without scaffold and with `showEffects` | building position, identity | `Stop(true)` |
| demolition `Building::StartDemolition` S 006ab840 | `DemolitionDust`, or `SmallDemolitionDust` when bit 0x4 of the size mask (`+0x3c`) is clear: mines (8) and ship sites (16) | once | building | `Stop(false)` |
| animation events `ParticleEvent::Start` S 006b05e0 | `<Particle start duration name slot>` of `buildings.xml`, `settler_animations.xml` | at the event time; the effect's start time is `desc.start / animScale + startTime` | the bone's world position plus `offset` turned by the bone's rotation, followed every tick (`ParticleEvent::Update` S 006b0710) | at `start + duration` `emitting = 0` and the event ends; `duration = 0`: `Stop(false)` at once |
| effect movies `EffectMovieElement::Start` S 006c6bc0 | `effectMovies.xml` `particles=` | at the keyframe (below) | link transform | past the keyframe's end, or movie end |
| soldiers `CharacterSoldier::Update` S 006c7f80 | `SoldierDamage`, `SoldierDefense`, `ArcherSpeed`, `BlindSoldier` | while the buff applies | right-hand bone (`SoldierDamage`), head (`BlindSoldier`), the figure's render position and rotation (`SoldierDefense`, `ArcherSpeed`), `animation-models.md` §3.10 | `Stop` while hidden, inside the building or riding a ship (`ArcherSpeed`: when its condition fails) |
| settlers `CharacterMovement::Update` S 006c57b0 | `SettlerSpeed` | `emitting` while the settler moves and its speed flag is set: visible and the sacrifice-scaled speed of its kind above `gameConfig.settlerSpeed` (`CharacterMovement::UpdateLogic` S 006c4f40, per tick) | settler | |
| carriers `CharacterCarrier::Update` S 006c9250 | `BoatFX` | `emitting` while moving on a boat | | |
| ships `Ship::UpdateFxEmitter` S 006a4a20, `Ship_SpawnParticleEffect` S 006a5bf0 | `ShipFX` under way; `ShipSpeedUp` or `ShipSpeedDown` while the ship's speed byte `+0xfc` or `+0xfd` is set (caller `Ship::UpdateVisuals` S 006a5cc0, `animation-models.md` §3.17) | created with `emitting = 0`, `active = 1`, `Restart(time)`, no reseed; `emitting` while the owner says active | ship x, z at the water height; rotation about up by `angle - π/2` | |
| projectiles `Projectile::SpawnNamedEffect` S 006a3980, `OnImpact` S 006a3af0 | `projectiles.xml` `flightPFX`, `impactPFX` | launch, impact | projectile | `ReleaseEffect` |
| fights `Scene::OnFightStrike` (string reference S 006835e8) | `HitDamage` | per strike | the attacker's position, turned toward the target vertex | `Stop(false)` |
| scene callbacks `Scene::OnSacrificeAppliedToCell` S 00681fd0, `OnSpawnTriggered` (S 0068216a) | sacrifice on a cell (the definition's `buffGfxName`), spawn trigger | callback; the sacrifice one-shot only on a cell the viewing player has explored | cell | `Stop(false)` |
| Lua `gfx.createParticel(name, x, y [, dx, dy, dz])` S 005aca40 | any (`Spawning`, `AnimalSpawned`, `BuildingFireShort`, `WhiteSmokeShort`, ...) | script call | cell centre + offset, identity; `active = emitting = 1`, `autoDelete = 0` | self (one-shots with `maxLoops > 0`) |
| lobby minigames (S 00512c28, S 0051836b) | `MGChess_Capture`, `MGDice_*` | game events | | |

**Sacrifice callbacks of the scene** (`NLogic::CallbackReceiver` face, vtable S 007f8e24, `rendering.md` §3.2)
[known]:

| Slot | Handler | Effect |
|---|---|---|
| +0xa0 | S 00681850 | `SacrificeBuilding::StartEffect` (below) |
| +0xa4 | S 00681890 | stop the sacrifice building's movie |
| +0xa8 | S 006818d0 | research movie `sacrificeResearchGfx` (`StartResearchEffect` S 006acf70) |
| +0xac, +0xb4 | S 00681930 (shared) | stop the sacrifice building's movie |
| +0xb0 | S 00681900 | wait-for-goods movie `sacrificeWaitForGoodsGfx` (`StartWaitForGoodsEffect` S 006ad050) |
| +0xb8 | S 0067f3b0 | `Ship::AddEffectInstance` |
| +0xbc | S 006819a0 | `CCharacter::AddEffect` |
| +0xc0 | S 00681fd0 | particle one-shot at the cell, only when the viewing player has explored it |
| +0xc4 | S 00681960 | `Building::AddAttachment` |

Slots +0xb8 to +0xc4 all use the sacrifice definition's `buffGfxName` (`SacrificeProperty +0x3c`). The
sacrifice building (`S2CG::SacrificeBuilding`) plays one movie at a time from its single movie list (+0x218).
`StartEffect` S 006ace00 clears that list, starts the definition's movie back-dated to
`now − (end − start) · timeInfo[2]` (the ticks the sacrifice has run, in seconds) and updates the list once in the
same call, so a sacrifice seen after a load or a late start shows the movie at the point it has reached. The
research movie is back-dated by the research's **absolute** start tick (S 006acf70), so every keyframe that starts
in the movie's first `startTick` seconds is already past: the ignite sound keyframe never plays and the fire burns
at once (presentation only; `quests-sacrifices-stats.md` §3.2.13).

**Effect movies** [known]: an `effectMovies.xml` movie is a list of keyframes of 0x5c bytes, one per `<FX>`.
`EffectMovieElement::ctor` S 006c69a0 resolves the keyframe's `link` by bone name once; a missing bone falls back to
the owner's matrix. Per update, `Update` S 006c6c80 starts an element when `start <= elapsed`, or stops it at once if
it is already past its end; `IsPastEnd` S 006c67c0 is `duration > 0 && start + duration <= elapsed`, so a keyframe
with `duration = 0` never ends on its own. `Start` S 006c6bc0 passes the current time (`*now`) as the emitter's
start time, not the movie's start, so a back-dated movie skips keyframes but does not fast-forward the particles of
the ones it starts.

**Projectiles** [known]: `ProjectileTable::AddProjectile` S 006a3d90 picks the `projectiles.xml` record by the
logic projectile type: type 0 → record 1, 1 → 0, 2 → 3, 3 → 2. The flight time is `T = flight ticks × 0.1` s
(`ComputeLaunchVelocity` S 006a32b0); gravity is 2.44269 (the float 0x401c5509 at S 00881a10) for type 1 (the
catapult stone) and 1.4715 otherwise; the launch velocity is `distance / T` horizontally and `g/2 · T + dy/T`
vertically. `Projectile::Update` S 006a3400 moves the projectile, and its `flightPFX` emitter with it, along that
arc. The target point (`ComputeImpactPoint` S 006a3610) starts at the bottom centre of the target's box and is moved
back along the normalised launch-to-target direction, per axis by that direction's component times 0.3 of the
box's width (x), 0.5 of its height (y) and 0.3 of its depth (z), so the projectile lands on the near face. `OnImpact` S 006a3af0 plays
`impactPFX` once at the impact and calls `ReleaseEffect` on the flight emitter.

**Building fire points** (`Building::InitFirePoints` S 006ac510, called only from the building constructor
S 006acc23) [known]: the model nodes `FIRE_03`, `FIRE_06`, ... (the counter starts at 0 and adds 3 before each
lookup: `XOR EDI,EDI` at S 006ac54f, `ADD EDI,3` at S 006ac551, loop back from S 006ac6c1) up to the first one
the model lacks; `FIRE_00` is never a fire point. Only the military models have such nodes [known, files]; every
other building gets five fallback points from the process-wide generator S 0088da38 (seed 0x5432ace0), two
draws each: `x = cx + (2r − 1) · 0.4 · sx`, `z = cz + (2r − 1) · 0.4 · sz` over the world bounds, `y` = the
centre's height. The generator advances in building creation order across the process. While a building sinks
after its demolition `Building::Update` returns at once, so its fires keep burning unchanged (`rendering.md`
§3.9).

The direct children `<PFX name link>` and `<Particle name position [timer]>` of `<Building>` in `buildings.xml`
(`BlackSmoke`, `Fire`, `WhiteSmoke` at `Dummy0..2`; `GoldMineSpark`, `StarSpark`, `SteamPuff`, `Fire`,
`StoneMineWork` at positions) have no loader identified [TODO]: no string `position` or `timer` exists in the
binary [known: string search], `animation-models.md` §10 Q12 asks the same for `<PFX>`.

### 3.14 Effects on a freshly loaded map

Three kinds of effects run without any simulation step that targets them; they need only the map, the scene and
the viewer.

**Resource hints** (`CLandscape::CollectResourceParticleCandidates` S 0068b220, `SpawnRandomResourceParticle`
S 0068ac10, table built by `CLandscape::ctor` S 0068ad40) [known]:

- Effects: good `IronOre` → `Resource_IronOre`, `Gold` → `Resource_Gold`, `Coal` → `Resource_Coal`,
  `Stone` → `Resource_Stone`, `Gemstones` → `Resource_Gemstones`. The good id comes from
  `PropertiesDb::FindGoodIdByName` S 00545f50 → `Properties_GoodMap_FindIdByName` S 00545db0: a linear walk of the
  good map in key order (ascending **signed** id, `properties-data.md` §2.2) that returns the first good whose name
  equals the string exactly [known]. Every name belongs to three goods (one per tribe variant and a generic one), so
  the table holds `ironOreScots` 0xaab683f3, `goldBav` 0xde8affb3, `coalScots` 0x9d676ab3, `stoneScots` 0x409ed753
  and `gemstones` 0xcb98c903 [known, `Goods.lua`]. The ground resources of all 31 readable shipped maps use the
  generic goods (`ironOre` 0xec5020be, `gold` 0x4f41c633, `coal` 0x7068dcd3, `stone` 0x55e952d3, `gemstones`;
  besides `fish` and `salt`) [known, files: every `.s2m` parsed], so on the shipped maps only **gemstone** cells
  can become candidates [inferred: the two lists].
- Generator: the static `RandomGenerator` S 0088d47c, seeded once at program start with `SetSeed(0x400)`
  (initialiser S 007caaf0; state 0x0a801540 after the bit balancing [inferred: arithmetic]), used by nothing else
  [known: its references are the initialiser, the exit destructor and the two functions above].
- Timing: every frame `CMapRenderer::Update` S 006888f0 calls the collection when there is a viewing player, then
  the spawn step. Collection runs when `now >= nextCheck` and no candidate is pending (`now` = the scene's
  `realTime`, frame info +4; `nextCheck` starts at 0, so the first check is on the first frame).
- Collection: `particleTime = now`; for every visible terrain block (4 × 4 cells, `rendering.md` §2.5), in the
  order of the visible list that the terrain culling built this frame (`CLandscape::UpdateVisibleCells`
  S 0068a4a0 → `GridQuadTree::Cull` S 006db440: a quadtree walk with the frustum and a horizon occlusion test;
  `CullNode` S 006db220 is depth first: a node wholly inside and not occluded is collected whole, otherwise its four
  children are visited in the order of the table S 007fc1b8 chosen by the nearest child; occluded blocks are not in
  the list [known]),
  whose revealed byte (+0xa0, mapped as `hasLayers`; set by `TerrainCell::RevealFromExploreMap` S 006b5f80) is set
  and whose maximum vertex height is above the renderer's water level (`IsMaxHeightAtOrBelowSeaLevel` S 006b4f70,
  the raw height against `g_TerrainGrid.seaLevel` S 00881448 = -100, is false): `x = range(x0, x1)`, `y = range(y0, y1)` (inclusive block corners);
  the cell must be on the map and explored by the viewing player; its resource record `{amount, goodId}`
  (`map.resources +0x10`, 8 bytes per cell) must have `amount != 0` and `goodId != -1` and the good must be in the
  table: then `{x, y, effect}` is a candidate. At most one candidate per block. Next check:
  `now + range(minTime, maxTime)` seconds with at least one candidate, `now + range(minTime / 2, minTime)` without.
  `minTime`, `maxTime` = `graphics.xml` `<Landscape><ResourceFX minTime="8" maxTime="25"/>` (integer seconds;
  code defaults 10 and 30, S 00881554).
- Spawn (same frame): with candidates, `pick = range(0, count - 1)`; world position of that cell
  (`TerrainGrid::CellToWorldPos` S 00687790: its centre vertex `(4x + 2 (y & 1), 4y)` with that vertex's height); a temporary `S2CG::Particles` starts the effect with `active = 1`,
  `emitting = 1`, `startTime = particleTime`, identity rotation, then `Stop(false)` detaches it (the effects have
  `maxLoops = 1`); candidates cleared. The emitter deletes itself when its particles are done (§3.8).
- Look of one hint (`Resource_*.pfx`, all five identical but for the name): 30 pooled sparkles, pass 3 (additive),
  spawned `pos (0, 5, 0) ± (3, 5, 3)` around the cell centre, size `5 ± 2` scaled by a cubic from 0 to 1, opacity a
  cubic from 1 to 0, ttl `0.8 ± 0.2`, spawn every `0.15 ± 0.08` s; by the `maxLoops` rule (§3.5) only the
  sparkles whose first spawn time is below their ttl show, about four.

**Gate fire** (`S2CG::Stargate::UpdateAnimation` S 006dc410, `CreateFireEffect` S 006dc310) [known]: on the first
frame a gate map object (`map_objects.xml` type `gate`, `rendering.md` §3.11) is drawn while not hidden, it loads
`Fire` (`LoadEffectByName`), sets `active = 1`, `Restart(realTime)` (frame info +4), `emitting = 1`, then
`SetPosition(centre of the gate's world AABB)`; identity rotation, no reseed. It burns until the gate is destroyed
(destructor S 006dc800 removes the emitter). Because `Restart` precedes `SetPosition`, the first-cycle start
positions are drawn around the world origin; every particle re-draws its start position on each update until its
birth (§3.5), and the first birth is at least `spawn + (spawn - spawnVar)` ≈ 0.22 s later, so no particle is
born at the origin as long as the gate is in view during that time [inferred].

**Sea route buoys** (`S2CG::RouteBuoy`, `ctor` S 006dbb90, `Tick` S 006dbd10, `StartFireEffect` S 006dbc30,
`UpdateAnimation` S 006dba70) [known]: a route buoy stands on the first cell of a sea route and, when both end
references are valid, on the last (`rendering.md` §3.2). On every logic tick (`MapObjLayer::Update` →
`InstanceMeshRenderer::UpdateInstances` → slot 11, all active instances, visible or not) the buoy looks up its
route (`ShipRouteList::FindByUnique`) and scans the route's ship references (+0x58, the ships assigned to the
route, `navy.md` §2.3): if one of them refers to a live object (id high word `>= 0`) the fire is started, else
`Stop(true)`. Start: `StartByName("Buoy_Fire", active 1, emitting 1, startTime = gameTime, buoy translation,
identity)` (only when no emitter is attached), then `active = not hidden`. Every frame the buoy is drawn,
`UpdateAnimation` bobs it (`y = seaLevel + 0.15 sin(0.45π t + x + 143.5 z)`, `rendering.md` §3.11) and moves the
emitter to the buoy-space point `(0, 3.75, 0)` through the bobbing world matrix, identity rotation. So on a fresh
map the buoys burn only where a route already has an assigned ship; a burning buoy that is hidden keeps its
emitter but freezes it (`active = 0`). The seed after the start is `0x53a0 + trunc(x + y + z)` of the buoy
position at the start.

**Lobby** (`Lobby::ParticleSystem::CreateEmitter` S 0051cfe0, `Render` S 0051ce20): the lobby building models
carry KEX scene nodes named `pfx:<effect>` (`pfx:candle` several times in the tavern and town hall models,
`pfx:fire`) [known, files `lobby/objects/*.KEX`]; that these names feed the lobby particle system's effect name is
[inferred]. An emitter is loaded from `[data]\scripts\effects\<name>.pfx`, start time = the frame stamp in ms /
1000, `SetTransform(node position, node rotation)`, fixed AABB (-75, -20, -75)..(75, 20, 75),
`active = emitting = 1`, `Restart` [known]. Each frame the transform is pushed again and the emitter is updated and
drawn at once with `RenderEmitter` S 004e0280 (fog off), outside the depth buckets [known]. [TODO] which data root `[data]` names in the lobby (the lobby data has no
`scripts\effects` folder): settled by the path resolver of the lobby context.

---

## 4. Update order

**Per logic tick** [known] S 00680550: the particle manager's `time` = `gameTime`; map object ticks (route buoys
start or stop their fire); building and character ticks start, move and stop their effects
(`rendering.md` §4.2).

**Per frame** [known] S 006805e0, S 006888f0, S 004e0660, S 0067eb20, S 004dfdc0:

1. `CMapRenderer::Update`: resource hint collection and spawn; buildings (fire points, buffs); map object
   animation (buoys move their emitter, gates create theirs).
2. Characters, ships, projectiles, animation events move their emitters.
3. `ParticleManager::CullAndSortEmitters(frustum)`: deletions, frustum test, depth buckets.
4. Render pass 0x100 (`RenderPasses`): fog off; `ParticleManager::RenderAll(realTime)`: per bucketed emitter
   `Update(realTime, cameraPos)` then `FillVertices` and draw; fog back on. With a post processor step 4 runs
   twice (`rendering.md` §4.3).

The simulation of a particle therefore happens inside the draw call, only for emitters that are active and in the
view frustum.

---

## 5. Inputs and outputs

Inputs: effect name or index, start time (scene seconds: `gameTime` from ticks, `realTime` from frames, or a
lobby frame stamp), world position and rotation, the `active` and `emitting` switches; per frame the scene's
`realTime`, the camera position and axes, the frustum, the fog range, the directional light and ambient.
Outputs: draw calls only. No write into the simulation, no sound (sounds of effect movies are separate,
`audio.md`).

---

## 6. Data-driven parameters

### 6.1 The 64 shipped effects

Parsed by a validation reader of the grammar of §3.1: **all 64 files parse to exactly their last byte**, all have
version `0002`, params type `Default` and particle type `Default` [known, files]. Atlas rectangles in pixels of
the 512 × 512 atlas (`texMin`-`texMax`, rounded); curves = the type ids of the velocity, size, colour and opacity
channels. "Started by": §3.13; "no reference found" = no string in the binary and no reference in the decrypted
data files.

| File | Renderer | Frames | Atlas rect (px) | Count | Curves v/s/c/o | Pass | maxLoops | ttl | spawn | size | Started by |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `AnimalSpawned` | Decal | - | (259,3)-(343,87) | 30 | 1/0/0/3 | 3 | 1 | 4 | 0.05 | 1.5 | `spawnpoints.lua` |
| `ArcherSpeed` | Decal | - | (259,3)-(343,87) | 30 | 1/0/0/3 | 3 | 0 | 2 | 0.2 | 1.5 | soldier buff (code) |
| `BlackSmoke` | Decal | - | (128,0)-(256,128) | 72 | 1/3/1/3 | 2 | 0 | 5 | 0.02 | 4 | `buildings.xml` |
| `BlindSoldier` | Decal | - | (64,32)-(92,64) | 19 | 1/4/0/4 | 2 | 0 | 2 | 0.1 | 1 | soldier buff (code) |
| `BoatFX` | GroundDecal | - | (3,63)-(61,0) | 15 | 0/1/0/1 | 0 | 0 | 3 | 0.5 | 1 | carrier on a boat (code) |
| `BoulderFly` | Decal | - | (64,32)-(96,64) | 50 | 1/0/0/1 | 0 | 0 | 2.5 | 0.2 | 0.4 | `projectiles.xml` flight |
| `BoulderHit` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 1 | 1 | 3 | 0.001 | 4 | `projectiles.xml` impact |
| `BuildingArmor` | GroundDecal | - | (34,67)-(61,93) | 10 | 0/0/0/1 | 0 | 0 | 0.5 | 0.05 | 15 | building buff (code) |
| `BuildingFire` | TexAnim | 6 | (0,129)-(32,160) | 59 | 3/3/1/1 | 3 | 0 | 1.8 | 0.015 | 1.8 | building fire points (code) |
| `BuildingFireShort` | TexAnim | 6 | (0,129)-(32,160) | 59 | 3/3/1/1 | 3 | 2 | 1.8 | 0.015 | 1.8 | `C08.lua` |
| `Buoy_Fire` | TexAnim | 6 | (0,129)-(32,159) | 59 | 3/3/1/1 | 3 | 0 | 1.5 | 0.015 | 0.8 | sea route buoys (code) |
| `candle` | TexAnim | 8 | (0,416)-(64,479) | 50 | 3/3/1/1 | 3 | 0 | 1.5 | 0.515 | 0.1 | lobby KEX node `pfx:candle` |
| `CoalMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `DarkClouds` | Decal | - | (64,32)-(92,64) | 54 | 1/4/0/4 | 2 | 0 | 5 | 0.1 | 8 | `effectMovies.xml` |
| `DemolitionDust` | Decal | - | (128,0)-(256,128) | 50 | 1/3/0/3 | 1 | 1 | 5 | 0.001 | 7 | demolition (code) |
| `DestroyShip` | Decal | - | (64,32)-(92,64) | 54 | 1/4/0/4 | 2 | 0 | 5 | 0.1 | 8 | `effectMovies.xml`, `C05.lua` |
| `Explore` | Decal | - | (259,3)-(343,87) | 43 | 1/0/0/3 | 3 | 1 | 7 | 0.05 | 1.5 | `effectMovies.xml`, Lua |
| `ExplorePos` | Decal | - | (259,3)-(343,87) | 43 | 1/0/0/3 | 3 | 1 | 7 | 0 | 1.5 | no reference found |
| `FallingLeaves` | Decal | - | (64,0)-(92,32) | 20 | 1/0/0/0 | 0 | 1 | 1.5 | 0.005 | 0.3 | no reference found |
| `Fire` | TexAnim | 8 | (0,416)-(64,479) | 56 | 3/3/1/1 | 3 | 0 | 2.5 | 0.115 | 0.8 | `buildings.xml`, `effectMovies.xml`, gates (code) |
| `FireSparkles` | TexAnim | 8 | (0,416)-(64,479) | 44 | 3/3/1/1 | 3 | 0 | 2.5 | 0.115 | 0.8 | no reference found |
| `GemstoneMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `GoldMineSpark` | Decal | - | (259,3)-(343,87) | 11 | 0/3/0/3 | 3 | 0 | 0.7 | 0.15 | 0.8 | `buildings.xml` building-level `<Particle position>` (loader [TODO]) |
| `GoldMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `Healed` | Decal | - | (259,3)-(343,87) | 43 | 1/0/0/3 | 3 | 1 | 5 | 0.05 | 1 | `effectMovies.xml` |
| `HitDamage` | Decal | - | (270,13)-(337,80) | 30 | 0/1/0/1 | 3 | 1 | 0.45 | 0 | 0.5 | fight strike (code) |
| `HotIron` | TexAnim | 1 | (0,128)-(32,160) | 20 | 1/3/1/0 | 3 | 0 | 1 | 0.08 | 2 | `buildings.xml` |
| `IronMineSpark` | Decal | - | (259,3)-(343,87) | 11 | 0/3/0/3 | 3 | 0 | 0.7 | 0.15 | 0.8 | no reference found |
| `IronMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `MGChess_Capture` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.2 | 0.02 | 0.25 | lobby minigame (code) |
| `MGDice_Smoke` | Decal | - | (128,0)-(256,128) | 20 | 1/3/1/3 | 2 | 1 | 1.5 | 0.02 | 0.2 | lobby minigame (code) |
| `MGDice_Won` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 0.5 | lobby minigame (code) |
| `Resource_Coal` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 5 | resource hints (code) |
| `Resource_Gemstones` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 5 | resource hints (code) |
| `Resource_Gold` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 5 | resource hints (code) |
| `Resource_IronOre` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 5 | resource hints (code) |
| `Resource_Stone` | Decal | - | (259,3)-(343,87) | 30 | 0/3/0/3 | 3 | 1 | 0.8 | 0.15 | 5 | resource hints (code) |
| `SacrificeBlackSmoke` | Decal | - | (128,0)-(256,128) | 39 | 1/3/1/4 | 2 | 0 | 5 | 0.02 | 6 | `effectMovies.xml` |
| `SacrificeFire` | TexAnim | 8 | (0,416)-(64,479) | 26 | 3/3/1/4 | 3 | 0 | 2.5 | 0.115 | 0.8 | `effectMovies.xml` |
| `SacrificeFireSparkles` | TexAnim | 8 | (0,416)-(64,479) | 94 | 3/3/1/4 | 3 | 0 | 2.5 | 0.115 | 0.8 | `effectMovies.xml` |
| `SacrificeFireSparklesFalling` | TexAnim | 8 | (0,416)-(64,479) | 48 | 3/3/1/4 | 3 | 0 | 2.5 | 0.115 | 0.4 | no reference found |
| `SacrificeOrder` | Decal | - | (259,3)-(343,87) | 70 | 1/0/0/3 | 3 | 0 | 4 | 0.05 | 1.5 | `effectMovies.xml` |
| `SacrificeResearchFire` | TexAnim | 8 | (0,416)-(64,479) | 26 | 3/3/1/4 | 3 | 0 | 2.5 | 0.115 | 0.8 | `effectMovies.xml` |
| `SaltMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `SawDust` | Decal | - | (0,0)-(64,32) | 70 | 1/1/0/0 | 0 | 0 | 0.5 | 0.004 | 0.05 | `buildings.xml` |
| `SawSmoke` | Decal | - | (128,0)-(256,128) | 20 | 1/1/0/1 | 0 | 0 | 3 | 0.02 | 3 | `buildings.xml` |
| `SettlerSpeed` | Decal | - | (64,32)-(96,64) | 30 | 1/1/0/1 | 0 | 0 | 1 | 0.2 | 0.4 | moving settler buff (code) |
| `ShipFX` | GroundDecalAnimated | 16 | (0,512)-(32,480) | 54 | 0/1/0/3 | 0 | 0 | 2.3 | 0.2 | 0.2 | ship wake (code) |
| `ShipSpeedDown` | Decal | - | (64,32)-(92,64) | 54 | 0/4/0/4 | 2 | 0 | 1.9 | 0.1 | 2 | `iconconfig.xml`, `sacrifices.lua` |
| `ShipSpeedUp` | Decal | - | (259,3)-(343,87) | 70 | 1/0/0/3 | 3 | 0 | 4 | 0.05 | 1.5 | building buffs (code) |
| `SmallDemolitionDust` | Decal | - | (128,0)-(256,128) | 50 | 1/3/0/3 | 1 | 1 | 5 | 0.001 | 5 | demolition (code) |
| `SmelterFire` | TexAnim | 6 | (0,129)-(32,160) | 59 | 3/3/1/1 | 3 | 0 | 1.5 | 0.01 | 1.1 | `buildings.xml` |
| `Smoke` | Decal | - | (128,0)-(256,128) | 50 | 1/3/0/3 | 1 | 0 | 5 | 0.02 | 4 | no reference found |
| `SoldierDamage` | Decal | - | (270,13)-(337,80) | 20 | 0/1/0/1 | 3 | 0 | 0.15 | 0.2 | 0.8 | soldier buff (code) |
| `SoldierDefense` | Decal | - | (259,3)-(343,87) | 43 | 1/0/0/3 | 3 | 0 | 3 | 0.2 | 1 | soldier buff (code) |
| `Spark` | Decal | - | (259,3)-(343,87) | 46 | 0/3/0/3 | 3 | 0 | 5.7 | 0.15 | 0.01 | no reference found |
| `Spawning` | Decal | - | (259,3)-(343,87) | 43 | 1/0/0/3 | 3 | 1 | 5 | 0.05 | 1.5 | `spawnDepots.lua` |
| `StarSpark` | Decal | - | (259,3)-(343,87) | 11 | 0/3/0/3 | 3 | 0 | 0.7 | 0.15 | 0.8 | `buildings.xml` building-level `<Particle position>` (loader [TODO]) |
| `SteamPuff` | Decal | - | (128,0)-(256,128) | 13 | 3/3/0/1 | 1 | 0 | 1.2 | 0.01 | 0.5 | `buildings.xml` |
| `StoneDust` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 1 | 0 | 3 | 0.001 | 4 | `settler_animations.xml` |
| `StoneMineWork` | Decal | - | (64,32)-(92,64) | 50 | 1/3/0/1 | 2 | 0 | 5 | 0.01 | 4 | `buildings.xml` |
| `WhiteSmoke` | Decal | - | (128,0)-(256,128) | 50 | 1/3/0/3 | 2 | 0 | 5 | 0.02 | 4 | `buildings.xml` |
| `WhiteSmokeShort` | Decal | - | (128,0)-(256,128) | 50 | 1/3/0/3 | 2 | 5 | 5 | 0.02 | 4 | `C08.lua` |
| `WorkerPause` | Decal | - | (64,32)-(92,64) | 54 | 1/4/0/4 | 2 | 0 | 5 | 0.1 | 4 | building buff (code) |

Worked examples [known, files]:

- `Buoy_Fire`: pos 0 ± (0.3, 0, 0.3), vel (0, 0.8 ± 0.2, 0), size 0.8 ± 0.2, ttl 1.5 ± 1.4, spawn 0.015 ± 0.008,
  colour (1, 1, 1, 0.8 ± 0.2); velocity cubic (0.1, -2, 3, 10), size cubic (0.5, -8, 0, 1), colour linear 0 → 20
  (black to white within the first 5 % of the life, then clamped), opacity linear 1 → 0.33; 6-frame flip-book of
  32 × 31 px; pass 3 (additive).
- `Fire`: colour alpha `0 ± 0.5`: about half of the particles draw with alpha 0 (clamped) and are invisible in the
  additive pass.
- `ShipFX`: ground wake, size linear 9 → 13 × (0.2 ± 0.2), opacity cubic (1, -1, 0, -4), 16 frames, pass 0.

### 6.2 Other parameters

| Source | Value | Use |
|---|---|---|
| `graphics.xml` `<Landscape><ResourceFX minTime maxTime>` | 8, 25 (integer seconds) | resource hint interval (§3.14) |
| environment fog (`daytimes.xml`, `local_enviroment.xml`, map `EnvData`) | start, end | distance fade (§3.10) |
| `projectiles.xml` `flightPFX`, `impactPFX`; `effectMovies.xml` `particles`; `buildings.xml`, `settler_animations.xml` `<Particle>` | effect names | §3.13 |
| constants in code | half texel `0.5 / 512`; bucket count 20; vertex ring 20000; fire offset of buoys (0, 3.75, 0); lobby AABB ±(75, 20, 75) | §3 |

---

## 7. Save and load

Nothing of the particle system is saved [inferred: no particle state in the save sections, `save-format.md`]. After
a load the owners re-create their effects from simulation state on the next tick or frame (fire points from hit
points, buffs, buoys from route ships, gates on first draw), with fresh start times. Effects that were started by
one-shot events (impacts, demolitions, animation events in progress) are not restored.

---

## 8. Determinism notes

- The particle system draws from its own generators only (each emitter's params generator; the static resource
  hint generator S 0088d47c); none of it touches the simulation's generator (`logic-core.md`) [known: the
  generators of §2.9 and §3.14].
- The first-cycle values of an effect are a pure function of the file (seed 0x53a0 and the draws of the load).
  Everything after depends on the frame cadence: unborn particles re-draw position and velocity on every
  `Update`, retired particles re-draw their position on every `Update`, `Update` runs only for active emitters in
  the frustum and twice per frame with the post processor. Two machines in the same match show different
  particles; a reimplementation cannot and need not reproduce the exact sequence [inferred].
- The resource hint generator is seeded once per process, so the hint cells and times depend on everything the
  process showed before (earlier matches, camera path, frame rate).

---

## 9. Notes for a Godot reimplementation

- **Loading.** Read the `.pfx` files of the player's install directly with the grammar of §3.1 (they are not
  encrypted). Look names up case-insensitively (the table is lower-case, the install mixes cases, Godot on Linux is
  case-sensitive). Reject a file whose renderer, params or particle type is unknown instead of crashing.
- **Atlas.** Decrypt and convert `particles_texture.tga` once (PNG with alpha, image top at UV v = 0). Keep the
  RGB of fully transparent pixels: the additive sparkles live only in RGB.
- **Simulation.** A CPU pool per emitter in C# (presentation layer): the structures of §2.6, `Spawn`, `Restart`,
  the life cycle of §3.5, the curves of §3.6 and §3.7, all evaluated from `elapsed = now - startTime` (no
  integration). Use the scene's interpolated time (`realTime`) as `now` and the tick time as start time for
  effects started by ticks. Run the update only for active emitters in the view (or for all; the result is the same
  apart from the random re-draws). Because the forms are closed, they also run per particle in a GPU particle
  shader, which is what the remake does (`../remake/renderer.md` §16.1).
- **Random numbers.** Implement the generator of §2.9 with the seeds of §2.3 and §3.4 to get the same
  distributions and the same first cycle; do not try to match later draws (§8).
- **Drawing.** One `ArrayMesh` (or `ImmediateMesh`) per emitter per frame, built from the six-vertex quads of
  §3.10 with the camera's right and up vectors; or a `MultiMesh` with a vertex shader that expands the corner
  attribute. Sort particles far to near inside the emitter and emitters far to near (a plain sort is fine; the
  original's bucket order inside a bucket is near to far). Depth test on, depth write off, cull back faces
  (both triangles face the camera), no fog.
- **Passes as materials.** 0: `blend_mix`, `ALBEDO = (ambient + light) * c.rgb * tex.rgb`, `ALPHA = c.a * tex.a`,
  unshaded; 3: `blend_add`, `ALBEDO = c.rgb * tex.rgb * c.a`, ignore `tex.a`; 1 and 2: `blend_mix` with the sphere
  normal lighting of §3.11 (decide on `sphere_normal.tga` for sampler 1, §10); 5: alpha scissor at 0.5. Pass the
  light and ambient of the environment as uniforms.
- **Distance fade.** Multiply alpha by the fade of §3.10 with the environment's fog start and end; clamp the vertex
  colour to 0..1 before use (the original clamps when packing, which also clamps `colour × 20` curves).
- **Owners.** Recreate the start sites of §3.13 and §3.14 from presentation state: fire points from building hit
  points, buoys from route ships, gate fires on first sight, resource hints from the explored resource grid with the
  interval of `graphics.xml`. Mods can add effects by dropping `.pfx` files into the effect folder (the name table is
  built from the folder).

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Which texture sampler 1 holds when passes 1 and 2 draw (§3.11) | running game: read the texture bound on stage 1 during `RenderAll` S 004dfdc0 (Frida hook on `SetTexture`) |
| 2 | Writer of `ParticleManager +0x98` (`disableAlphaBlend`) | static: writers of the byte; likely a debug CVar |
| 3 | Loader (if any) of the direct `<PFX name link>` and `<Particle name position timer>` children of `<Building>` (§3.13) | static: readers of the `buildings.xml` building node besides `LoadAnimEvents` S 006867d0; running game: a gold mine's sparkle |
| 4 | The data root `[data]` of the lobby's emitter paths (§3.14) | static: the path resolver used in the lobby context |
| 5 | Whether the tree emitter `TreeInstance +0x124` (cleared in `Tick` S 006dcf00) is ever created, and with which effect (`FallingLeaves` has no reference) | static: writers of `TreeInstance +0x124` |
| 6 | The texture-transform values `ParticleManager +0x54/+0x58` written by `InitResources` (affect the `ffp` technique only) | static: disassembly of S 004e0ad0 near the texture size call |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 00686af0 | `ai::gfx::EffectScriptMgr::ScanEffectNames` | effect name table from `*.pfx` |
| 00685f00 | `EffectScriptMgr::FindEffectIndex` | name → index, -1 |
| 00685bb0, 00685e10 | `EffectScriptMgr::LoadEffectByName` / `LoadEffectByIndex` | path, load |
| 004e0950 | `ai::render::ParticleManager::LoadEmitterFile` | open, construct, `Restart`, `Load`, register |
| 004e0ad0 | `ParticleManager::InitResources` | vertex buffer, effect, handles, atlas |
| 004e0660 | `ParticleManager::CullAndSortEmitters` | deletion, frustum, depth buckets |
| 004dfdc0 | `ParticleManager::RenderAll` | per emitter: volume constants, pass, `Update`, `FillVertices`, draw |
| 004e0280 | `ParticleManager::RenderEmitter` | immediate draw of one emitter (lobby) |
| 004dfd40 | `ParticleManager::RemoveEmitter` | delete one emitter |
| 004f0940, 004f1430 | `ParticleEmitter::ctor` / `ctor_FromFile` | defaults |
| 004f1150 | `ParticleEmitter::Load` | file layout |
| 004f1310 | `ParticleEmitter::Save` | mirror of `Load` |
| 004f0de0, 004f0f10, 004f0c10 | `CreateParams` / `CreateRenderer` / `CreateParticles` | type factories, stagger |
| 004f04b0 | `ParticleEmitter::Restart` | start time, respawn |
| 004f0790 | `ParticleEmitter::Update` | particles, AABB, sorted list |
| 004f0530 | `ParticleEmitter::FillVertices` | distance fade, builder calls |
| 004f0730, 004f0760, 004f06c0 | `SetPosition` / `SetRotation` / `SetTransform` | emitter transform |
| 004f2d50 | `ParticleEmitterParams::ctor` | defaults, seed 0x53a0 |
| 004f3250, 004f3350 | `ParticleEmitterParams::Load` / `Save` | params block |
| 004f3170, 004f31c0, 004f36f0, 004f3740, 004f3770, 004f3210 | `RandomTtl` / `RandomSpawnDelay` / `RandomSpawnPosition` / `RandomInitialVelocity` / `RandomColor` / `RandomSize` | draws |
| 004f3410, 004f34b0 | `RandomizeVec3` / `RandomizeVec4` | per-component draws |
| 004f2c90 | `ParticleEmitterParams::Reseed` | `SetSeed(randomSeed + offset)` |
| 004f1660, 004f1820 | `Particle::Spawn` / `Reset` | particle initialisation |
| 004f16c0 | `Particle::Update` | life cycle |
| 004f1960 | `Particle::ApplyCurves` | curves → position, size, colour |
| 004f2b10, 004f2430, 004f2940, 004f1bf0 | `ParticleCurveSet::ctor` / `Load` / `SetCurveType` / `Evaluate` | curves |
| 004f1ce0 | `PropertyDesc::LoadValue` | property read widths |
| 004f1d60..004f2720 | curve constructors | properties, defaults |
| 004f1db0, 004f1e70, 004f1f40, 004f20e0, 004f2330, 004f2620, 004f2830 | curve `Evaluate` | formulas |
| 004f1e60, 004f20a0, 004f22c0 | curve `Prepare` | coefficients |
| 004f38e0, 004f3a00, 004f3a40, 004f3ae0, 004f3b00 | renderer constructors | half texel, frame count |
| 004f39a0, 004f3a60 | `ParticleQuad::Load` / `ParticleQuadAnim::Load` | renderer block |
| 004f3b20, 004f3b80, 004f3fc0, 004f43d0, 004f4860 | vertex builders | §3.10 |
| 006ec2a0, 006ec410, 006ec3a0 | `RandomGenerator::SetSeed` / `unit` / `NextInRange` | generator |
| 006e8a50 | `Math_FastCosLut` | cosine table |
| 006964c0, 00696620, 00696400 | `S2CG::Particles::StartByIndex` / `StartByName` / `Stop` | owner handle |
| 00696570 | `S2CG::Particles::dtor` | always stops as `Stop(true)` |
| 00681850, 00681890, 006818d0, 00681930, 00681900, 0067f3b0, 006819a0, 00681fd0, 00681960 | scene callback slots +0xa0 .. +0xc4 | sacrifice movies, buff effects (§3.13) |
| 006ace00 / 006acf70 / 006ad050 | `S2CG::SacrificeBuilding::StartEffect` / `StartResearchEffect` / `StartWaitForGoodsEffect` | back-dated movies |
| 006c69a0 / 006c6bc0 / 006c6c80 / 006c67c0 | `EffectMovieElement::ctor` / `Start` / `Update` / `IsPastEnd` | effect movie keyframes |
| 006a3d90 / 006a32b0 / 006a3400 / 006a3610 / 006a3af0 | `ProjectileTable::AddProjectile` / `Projectile::ComputeLaunchVelocity` / `Update` / `ComputeImpactPoint` / `OnImpact` | projectile flight |
| 00683530 (reference S 006835e8) | `S2CG::Scene::OnFightStrike` | `HitDamage` |
| 006964a0, 00696480, 00696450 | `Particles::SetVisible` / `SetEmitterLooping` / `SetEmitterPositionAndColor` | switches, transform |
| 0068b220, 0068ac10 | `CLandscape::CollectResourceParticleCandidates` / `SpawnRandomResourceParticle` | resource hints |
| 00689bf0 | `Landscape_LoadSettingsXml` | `ResourceFX minTime maxTime` |
| 006dbb90, 006dbd10, 006dbc30, 006dba70 | `S2CG::RouteBuoy::ctor` / `Tick` / `StartFireEffect` / `UpdateAnimation` | buoy fire |
| 006dc410, 006dc310 | `S2CG::Stargate::UpdateAnimation` / `CreateFireEffect` | gate fire |
| 006abbb0 | `S2CG::Building::UpdateFireEffects` | fire points |
| 006ac510 / 006acc23 | `S2CG::Building::InitFirePoints` / its call in the building constructor | `FIRE_03`, `FIRE_06`, ... or five fallback points |
| 006abcf0 / 006ab840 | `S2CG::Building::Update` / `StartDemolition` | buff effects; demolition dust |
| 006b05e0, 006b0710 | `S2CG::ParticleEvent::Start` / `Update` | animation events |
| 005aca40 | `LuaGame_createParticel` | Lua effects |
| 0051cfe0, 0051ce20 | `Lobby::ParticleSystem::CreateEmitter` / `Render` | lobby emitters |
| 006a4a20, 006a5bf0 | `S2CG::Ship::UpdateFxEmitter` / `Ship_SpawnParticleEffect` | ship effects |
