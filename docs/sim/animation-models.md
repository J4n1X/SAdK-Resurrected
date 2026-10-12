# Models, skeletons and animation at runtime

Evidence tags: **[known]** = read directly at an address (S 00xxxxxx, `sadk_noav.exe`) or in a named data file and
key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open. Nothing here was observed in
the running game. Statistics ("all 1,639 files") were computed over the reference install with `tools/kex.py`.

Related documents: the KEX container itself is specified in [`../asset-formats.md`](../asset-formats.md) §2; this
file adds what the loader does to a file after reading it and what a converter needs. The simulation side of
settler actions (`NMovie`, `NSettlers::Animation`) is specified in [`settlers-jobs.md`](settlers-jobs.md) §2.5,
§2.10 and §3.5; the tick loop in [`logic-core.md`](logic-core.md); world coordinates of the map in
[`map-resources.md`](map-resources.md) §2.

---

## 1. Purpose and scope

This subsystem turns KEX scenes into drawn, animated objects:

- `KSceneInternal::*` — the scene library: file (`KFile`), mesh (`KMesh`), skeleton (`KSkeleton`), animation
  (`KAnimation`), a posed skeleton instance (`KModel`) and one playing animation on it (`KAnimationControl`).
- `S2CE::CMesh`, `S2CE::CAnimatedObject` — the engine wrappers: a render mesh with subsets (cached on disk as
  `.mshraw`) and an animated skeleton instance with numbered animation slots.
- `ai::render::AnimResMgr`, `ai::rendering::SharedResourceCache` — handles for loaded animation files and the
  shared, reference-counted KEX file cache.
- `ai::anim::AnimationSet`, `S2CG::CModelCache`, `S2CG::CharacterAnimation` — which animation a settler or animal
  plays, and the pool of shared posed skeletons.
- `S2CG::CCharacter*`, `S2CG::Building`, `S2CG::Ship`, `S2CG::Animal`, `S2CG::Item` — the render objects of
  settlers, buildings, ships, animals and goods, as far as they select animations, attach objects to bones and
  colour models.

All of it is presentation. The simulation never reads a model, a skeleton or an animation length (§8). The name
"movie" belongs to the simulation: `NMovie::*` are the scripted action state machines of settlers
(`settlers-jobs.md` §2.10); they time actions with the tick counter `NSettlers::Animation`, and this subsystem only
*displays* the kind of action that timer reports (§3.9).

Out of scope: the lobby's avatar system (`ai::anim::AnimGraph`, `ai::lobbygfx::AnimModel`,
`ai::anim::TransformInterpolator`; the only constructors of `AnimGraph` are `LobbyPetMgr::CreateInstance`
S 004fe5c0 and `CGfxObjAvatar::CreateAnimation` S 00506e10 **[known]**), terrain, particles, static map objects
drawn by `InstanceMeshRenderer`, and shader lighting.

---

## 2. Data model

### 2.1 Conventions of the scene library

- Matrices are row-major with **row vectors**: `v' = v * M`; a 4x4 has its translation in elements 12..14 and
  column 3 forced to `(0,0,0,1)` (`Mat4_MultiplyAffine` S 0072ea30, `Vec3_MulMat3InPlace` S 0072f890). **[known]**
- Quaternions are stored `(x, y, z, w)`; `Mat4_FromQuat` S 0072eea0 produces, for a unit quaternion, the matrix
  whose row 0 is `(1-2(y²+z²), 2(xy+zw), 2(xz-yw))`, i.e. the usual rotation matrix transposed for row vectors.
  **[known]**
- Composition of a child with its parent is `world_child = local_child * world_parent`
  (`KBoneKey_MultiplyMat4` S 0072f650). **[known]**

### 2.2 `KSceneCoordSystem` (0x34 bytes) — a coordinate system description

| Offset | Type | Field |
|---|---|---|
| `+0x00` | f32[3] | `axisX` |
| `+0x0c` | f32[3] | `axisY` |
| `+0x18` | f32[3] | `axisZ` |
| `+0x24` | f32[3] | `origin` |
| `+0x30` | f32 | `unitScale` |

A `KFile` carries the one it was exported in (`+0x3c`), read from the file header. The engine's target system is
the constant at S 0087c550: `axisX = (0,0,-1)`, `axisY = (0,1,0)`, `axisZ = (1,0,0)`, `origin = (0,0,0)`,
`unitScale = 1.0`; callers overwrite `unitScale` with their model scale (§3.1). **[known]**

Every file of the install stores `axisX = (1,0,0)`, `axisY = (0,0,1)`, `axisZ = (0,1,0)`, `origin = (0,0,0)`.
`unitScale` is 1.0 in 1,605 files, 39.37008 in 23 (e.g. `game/character/donkey/*`, `map/objects/street_buoy.KEX`)
and 100.0 in 11 (e.g. `game/animals/rabbit*.KEX`, `mountainHare*.KEX`). **[known]** (data)

### 2.3 `KFile` (0xa0 bytes, vftable S 0082be18)

`+0x04` name (`std::string`), `+0x20` second string (never filled by `Load`), `+0x3c` `KSceneCoordSystem coords`,
`+0x70` vector of `KMesh*`, `+0x80` vector of `KSkeleton*`, `+0x90` vector of `KAnimation*` (each vector: first
element pointer at `+4`, end at `+8`). **[known]** (S 0072b8b0, S 0072b820). Virtuals (vtable dump): `+0x00` name,
`+0x04` mesh count, `+0x08` `GetMesh(i)`, `+0x0c` skeleton count, `+0x10` `GetSkeleton(i)`, `+0x14` animation
count, `+0x18` `GetAnimation(i)`, `+0x1c` text dump to a file, `+0x20` destructor. **[known]** (S 0072b200,
S 0072a8e0, S 0072b220, S 0072a920, S 0072b240, S 0072a960, S 0072adc0)

`CAnimatedObject::Load` accepts a file only when its skeleton count is exactly 1 (S 0076b4a0). **[known]** In the
install 189 files hold one skeleton and 1,450 none. **[known]** (data)

### 2.4 `KMesh` (vftable S 0082becc)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04` / `+0x20` | `name`, `name2` | strings |
| `+0x44` | `numVertices` | |
| `+0x48` | `numStreams` | |
| `+0x4c` | `numIndices` | 3 per triangle |
| `+0x50` / `+0x54` | `numMaterials`, `materials` | array of `KMaterialDesc*` |
| `+0x58` / `+0x5c` | `numBoneNames`, `boneNames` | array of `std::string` (0x1c each) |
| `+0x60` | `indices` | `u32[numIndices]` |
| `+0x64` | `streams` | array of `{i32 type; u32 byteSize; void* data}` (0xc each) |

**[known]** (S 0072c880). Virtuals (vtable dump) **[known]**: `+0x00` name, `+0x10` `numVertices`, `+0x14`
`numIndices`, `+0x18` `numBoneNames`, `+0x1c` bone name `i`, `+0x20` `numStreams`, `+0x24` / `+0x28` / `+0x2c`
type / byte size / data of stream `i`, `+0x30` `indices`, `+0x34` `numMaterials`, `+0x38` material `i`, `+0x3c`
bounding box of the type-0 stream.

Stream types as the engine consumes them (`CMesh::FillVertices` S 0076c030) **[known]**:

| Type | Per vertex | Written to (D3D declaration usage) | Processing |
|---|---|---|---|
| 0 | 3 x f32 | POSITION (0) | copied |
| 1 | 3 x f32 | NORMAL (3) | normalised |
| 2 | 3 x f32 | TANGENT (6) | normalised |
| 3 | u32 | COLOR (10) | copied as one dword (D3DCOLOR) |
| 4, 5, 6, 7 | 2 x f32 | TEXCOORD (5), index `type - 4` | copied |
| 12 | 4 x f32 | BLENDWEIGHT (1) | divided by the sum of the four weights |
| 13 | 4 x u8 | BLENDINDICES (2) | copied |

A stream whose usage is missing from the target vertex declaration is dropped. Types 8..11 do not occur and have no
case. Bone indices (type 13) index the mesh's own `boneNames` list, not the skeleton (§3.6). **[known]**

`KMaterialDesc` (0x4c bytes, vftable S 0082c14c): `+0x04` name, `+0x20` second string, `+0x3c` `u32 startIndex`,
`+0x40` `u32 triangleCount`, `+0x44` texture count, `+0x48` array of string pairs `{usage, textureFile}` (0x38
each). **[known]** (S 007303a0). Virtuals (vtable dump): `+0x00` name, `+0x10` `startIndex`, `+0x14`
`triangleCount`, `+0x18` texture count, `+0x1c` usage string of texture `i`, `+0x20` file name of texture `i`.
**[known]** These are the fields `a` and `b` of `asset-formats.md`: the subset builder copies virtual `+0x10` into
the subset's first index and `+0x14` into its primitive count, and skips a material whose `+0x14` is 0
(`Mesh_AppendSubsetsFromKMesh` S 0076d010). **[known]** The data agree: in 5,279 of 5,332 meshes the `b` values
sum to `numIndices / 3`, and in multi-material meshes `a` is the running index offset, e.g. 0, 3, 45, 261, …; the
53 exceptions are helper meshes without materials such as `Bip01` and `Box01`. **[known]** (data)

### 2.5 `KBoneKey` — a local transform (0x44 bytes used, stored in 0x80-byte aligned slots)

| Offset | Type | Field |
|---|---|---|
| `+0x00` | u32 | `flags`: bit 0 position present, bit 1 rotation present, bit 2 3x3 matrix present |
| `+0x04` | f32[3] | position |
| `+0x10` | f32[4] | rotation quaternion (x, y, z, w) |
| `+0x20` | f32[9] | 3x3 "scale" matrix (scale and shear) |

**[known]** (S 0072f1d0, S 0072f160). `KBoneKey_ToMat4` S 0072f510: rotation and matrix present → `R * S`; only
one → that one; neither → identity; then translation = position when bit 0 is set. **[known]**

### 2.6 `KSkeleton` (vftable S 0082bf28)

`+0x04` name, `+0x20` name2, `+0x44` `boneCount`, `+0x48` bone array (0x28 each: `+0x00` name string, `+0x1c`
`i32 parentIndex` (-1 = root), `+0x20` pointer to the bone's 4x4 matrix, `+0x24` pointer to its `KBoneKey`),
`+0x4c` the `KBoneKey` block, `+0x50` the matrix block, `+0x54` `std::map<string,int>` name → index. **[known]**
(S 0072d290). Virtuals (vtable dump): `+0x00` name, `+0x10` bone count, `+0x14` name of a bone, `+0x18` bind
`KBoneKey` of a bone, `+0x1c` bone matrix, `+0x20` parent index, `+0x24` `FindBoneIndex(name)` (-1 if absent),
`+0x28` model-space matrix of a bone from the bind keys. **[known]** (S 0072d220, S 0072dba0, S 0072d230,
S 0072d250, S 0072d270, S 0072d030, S 0072cef0)

The per-bone 4x4 matrix of the file is the **inverse bind matrix**: the skin matrix is `fileMatrix * boneWorld`
(§3.6). **[known]** (S 0072bf20). In 181 of the 189 skeletons `fileMatrix * world(bindKeys)` is the identity for
every bone (to two decimals), i.e. the matrix is the inverse of the bind pose given by the bones' own keys. In six
it is one constant other than the identity for all bones of the file — notably the settler skeleton
`settler_model.KEX`, where it is `[[0,1,0],[-1,0,0],[0,0,1]]` (a quarter turn about the file's Z axis), so the
settler mesh in bind pose is drawn turned by that constant; the other five have a constant translation
(`game/character/donkey/donkey_model.KEX`, `game/animals/donkey_model.KEX`, `farmpig_model.KEX`) or a constant
rotation with translation (`mountainHare_model.KEX`, `rabbit_model.KEX`). In two lobby files
(`lobby/objects/minigame/pokertable*.KEX`) it varies per bone. **[known]** (data)
The engine never derives one from the other; it uses the file matrix as it is.

In all 189 skeletons there is exactly one root and every parent index is smaller than the bone's own index, which
`KModel::UpdateBoneMatrices` relies on. **[known]** (data; S 0072c340). The largest skeleton has 109 bones; a
skinned mesh references at most 46 bone names. **[known]** (data)

### 2.7 `KAnimation` (vftable S 0082bf8c)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04` / `+0x20` | `name`, `name2` | `name` is matched against the skeleton's name (§3.7) |
| `+0x3c` | `length` (f32) | seconds |
| `+0x40` | `trackCount` | |
| `+0x44` | `keyCount` | the same for every track |
| `+0x48` | `tracks` | array of `KAnimationTrack` (0x28 each) |
| `+0x4c` | `invLength` | `1 / length`, computed on load |

`KAnimationTrack`: `+0x00` bone name, `+0x1c` positions (`keyCount` x 16 bytes: vec3 padded), `+0x20` rotations
(`keyCount` x quaternion), `+0x24` scale matrices (`keyCount` x 9 floats); a null pointer means the channel is
absent. **[known]** (S 0072dcf0, S 0072d550). Virtuals (vtable dump): `+0x00` name, `+0x10` length, `+0x14` track
count, `+0x18` key count, `+0x1c` track bone name, `+0x20` `GetKey(track, key, out)` (the raw key, missing channels
as in §3.4). **[known]** (S 00695ec0, S 0072db90, S 0072d220, S 0072dba0, S 0072d550)

Data: lengths range from 0.033 s to 72.0 s; `keyCount / length` is 18.0 (104 animations), 25.0 or 24.99 (131),
27.49 (79) and a few other rates. Channel combinations over all 12,174 tracks: position+rotation+scale 6,463,
position+rotation 3,811, position 949, position+scale 816, rotation 98, scale 25, rotation+scale 12. **[known]**

### 2.8 `KModel` — a posed skeleton instance (vftable S 0082be44)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04` | `skeleton` | shared `KSkeleton*` |
| `+0x08` / `+0x0c` | deformable mesh list, count | `KDeformableMesh` bindings (§3.6) |
| `+0x10` | `boneStates` | per bone 8 bytes: `u16 stamp`, `u16 contributorCount`, `f32 weightSum` |
| `+0x14` | `poseRecords` | per bone one 0x80-byte `KBoneKey`: the blended local pose |
| `+0x18` | `boneMatrices` | per bone a 4x4 world matrix |
| `+0x1c` | `skinMatrices` | per bone a 4x4 `inverseBind * world` |
| `+0x20` | `animControls` | singly linked list of `KAnimationControl` |
| `+0x24` / `+0x28` | `deltaTime`, `lastTime` | `lastTime` starts at the constructor argument (0 from the engine) |
| `+0x2c` / `+0x38` | `boundsMin`, `boundsMax` | min/max of the bones' world translations |
| `+0x44` | `frameStamp` (u16) | incremented once per `Update` |

**[known]** (S 0072c430, S 0072bf20 disassembly, S 0072c1d0, S 0072ba20).

Virtuals (vtable dump) **[known]**: `+0x00` skeleton, `+0x04` `PlayAnimation(anim, timeOffset, duration)`, `+0x08`
`PlayAnimation(anim, 0, 0)`, `+0x0c` `StopAnimation(control)`, `+0x10` set a control's bone masks, `+0x14` /
`+0x18` attach / detach a mesh, `+0x1c` mesh count, `+0x20` mesh `i`, `+0x24` `UpdateTime(now)`, `+0x28`
`Update()`, `+0x2c` `UpdateBoneMatrices(root)`, `+0x30` / `+0x34` pose record of a bone, `+0x38` / `+0x3c` the
`boneMatrices` array, `+0x40` the `skinMatrices` array, `+0x44` `ResetPose()` (frame stamp 0, all controls
removed, every pose record = the bone's bind key, bone states zeroed), `+0x48` `GetBounds`.

`UpdateTime(now)` S 0072baa0: `deltaTime = max(now - lastTime, 0)`, `lastTime = now`. The model is driven with an
absolute time, not with a time step. **[known]**

### 2.9 `KAnimationControl` — one playing animation (0x54 bytes, vftable S 0082c114)

| Offset | Field | Initial | Meaning |
|---|---|---|---|
| `+0x04` | `next` | 0 | list link |
| `+0x08` / `+0x0c` | `boneMask`, `inverseBoneMask` | 0 | optional per-bone weight objects (`vtbl+8(bone)` → f32) |
| `+0x10` | `active` (u8) | 0 | result of `IsActive` in the last `KModel::Update` |
| `+0x14` / `+0x18` | `skeleton`, `animation` | | |
| `+0x1c` | `timeOffset` (f32) | argument | added to `time` when sampling |
| `+0x20` | `duration` (f32) | argument, or `animation.length` when the argument is `<= 0` | loop length for loop counting |
| `+0x24` | `time` (f32) | 0 | seconds played |
| `+0x28` | `weight` (f32) | 1.0 | |
| `+0x2c` | `speed` (f32) | 1.0 | |
| `+0x30` | `maxLoops` (i32) | 0 | 0 = loop for ever |
| `+0x34` | `trackToBone` | | `i32[trackCount]`: skeleton bone index of each track, -1 if the bone is missing |
| `+0x38` | `bonePoses` | identity | per skeleton bone one 0x80-byte `KBoneKey`: this control's sample |
| `+0x3c` | `autoRemove` (u8) | 0 | delete the control when it becomes inactive |
| `+0x40` | `heldFrame` (i32) | -1 | key index the control is frozen on |
| `+0x44` / `+0x48` | `fadeFrom`, `fadeTo` | 0 | |
| `+0x4c` / `+0x50` | `fadeStart`, `fadeDuration` | 0 | |

**[known]** (S 00730070, S 007301e0 disassembly). Vtable slots: 1 `SetWeight`, 3 `SetSpeed`, 4 `GetSpeed`,
2 `GetWeight`, 5 set `maxLoops`, 6 get `maxLoops`, 7 `SetTime`, 8 get time, 9 `GetTotalDuration`,
10 `GetCurrentLoop` = `trunc((time + timeOffset) / duration)`, 11 set `autoRemove = 1`, 12 `FadeWeight`.
**[known]** (vtable dump of S 0082c114; S 00695da0, S 00555800, S 007302c0)

### 2.10 `S2CE::CMesh` — a render mesh

Fields named by use: source path, optional mesh name ("variant suffix"), vertex declaration, `vertexStride`,
`vertexCount`, interleaved `vertices`, `indexCount`, `u16 indices`, `boneNameCount`, `boneNames`, and a subset array
(0x28 each: `+0x00` name, `+0x1c` texture list pointer, `+0x20` `startIndex`, `+0x24` `primitiveCount`); a texture
list is `{count, capacity, data}` of string pairs `{usage, fileName}`. **[known]** (S 0076bdc0, S 0076d990).
Exact offsets of the scalar fields are **[TODO]** (not needed for a reimplementation).

### 2.11 `S2CE::CAnimatedObject` (0x4c bytes) and `S2CG::AnimatedVisual` (0x64 bytes)

`CAnimatedObject`: `+0x04` slot array (0x14 each: `+0x00` animation id, `+0x04` `KAnimationControl*`, `+0x08`
callback object, `+0x0c` callback argument, `+0x10` f32 start time), free-handle stack, `+0x1c..` list of active
slot handles (1-based), `+0x28` the shared `KFile*`, `+0x2c` pointer to its `KSceneCoordSystem` key, `+0x30`
`KModel*`, `+0x34` world-space bounds. **[known]** (S 0076b230 disassembly, S 0076b4a0). Vtable: slot 1
`CreateInstance` (new object on the same `KFile`, own `KModel`), 2 `AddAnimation`, 3 `AddAnimationWithCallback`,
4 `RemoveAnimation(slot)`, 5 (`AnimatedVisual` only) `PlayAnimationWithEffects`. **[known]** (plate vtable list of
`AnimatedVisual`, S 006d8670).

`AnimatedVisual` adds `+0x4c` a callback face, `+0x50` an "effects enabled" byte (1 from the constructor; a pool
sets it to 0 on a new instance and `CharacterAnimation::PlayAnimation` copies its own flag `+0x34` into it; it is
the second argument of `EventBase::Tick`), `+0x54..+0x5c` an array `{count, capacity, data}` of effect
attachments (sounds, particles, items bound to an animation), `+0x60` the argument handed to effect factories (a
world matrix or the holder's value). **[known]** (S 006d8440, S 006d8670, S 006d8570, S 006ad4f0, S 006c63a0)

### 2.12 `ai::render::AnimResMgr` — animation handles

A singleton (S 008872f0 getter) with a 16-byte entry per **animation file**: `+0x00` number of `KAnimation`s in the
file, `+0x04` array of their pointers, `+0x08` the `KFile*`, `+0x0c` copy of the load key. An **animation id** is
the 1-based index of such an entry. One file may hold several `KAnimation`s, one per skeleton it applies to; the
right one is chosen when the animation is started (§3.7). **[known]** (S 004de400, S 0076b230). In the install 514
files hold one animation and 2 files hold three. **[known]** (data)

`LoadAnimation(path, scale)` S 004de400: the second argument is a float, written into `unitScale` of the load key
(§3.1); the function returns the id, or -1 when the file could not be acquired or holds no animation (no entry is
made then). Two loads of the same file make two entries on the one cached `KFile`. **[known]**

### 2.13 `ai::anim::AnimationSet` (0x48 bytes) — named animations and slot tables

| Offset | Field | Meaning |
|---|---|---|
| `+0x00` | `slotCount` | number of animation *types* (10 for settlers, §3.9) |
| `+0x04..+0x0c` | `anims` | vector of 0x24-byte records: `+0x00` animation id, `+0x04` name, `+0x20` `tribes` mask |
| `+0x10` | `defaultAnimBySlot` | `int[slotCount]`, -1 = none |
| `+0x14` | `overrideByKeyA` | `map<goodId, int[slotCount]>` |
| `+0x20` | `overrideByOuterKeyB` | `map<tribeKey, map<goodId of a type-1 good, int[slotCount]>>` |
| `+0x2c` | `overrideByOuterKeyC` | `map<tribeKey, map<id, int[slotCount]>>` |
| `+0x38` | `defaultRandomAnim` | `RandomAnimDesc*` |
| `+0x3c` | `randomAnimByItem` | `map<itemId, RandomAnimDesc*>` |

**[known]** (S 006cc350, S 006ca8d0). `+0x04` as the anims vector start **[inferred]** (the loader indexes
`set+4/+8/+0xc`).

### 2.14 `S2CG::CModelCache` (0x40 bytes) — pool of shared posed skeletons

`+0x00` `AnimationSet*`, `+0x04` model (skeleton) file name, `+0x20` model scale (a float stored in an int field),
`+0x24` entry array `{count, capacity, data}` (0x14 per entry: `+0x00` `AnimatedVisual* instance`, `+0x04`
`animId` (-1 = free), `+0x08` `trackHandle` (slot handle on the instance, -1 = none), `+0x0c` `f32 animTime`,
`+0x10` pointer to the user list `{count, capacity, holders}`), `+0x30` `gcTimer`, `+0x34` / `+0x38` / `+0x3c`
three counters (references, models, animated). **[known]** (S 006ad8c0, S 006ad4f0, S 006ad380, S 006ad2e0,
S 006c63a0 disassembly)

### 2.15 `S2CG::CharacterAnimation` (0x6c bytes, vftable S 007fb588)

| Offset | Field | Meaning |
|---|---|---|
| `+0x04` | `animSystem` | the `SkinnedMeshRenderer` |
| `+0x08` | `animSet` | actually the `CModelCache*` of the character's model |
| `+0x0c` | `currentTrack` | the pool instance (`AnimatedVisual*`) whose bones this character is drawn with |
| `+0x10` | `singleTrack` | the same pointer when this character is the instance's only user, else null |
| `+0x14` / `+0x18` | bounds-valid byte, world AABB | |
| `+0x30` | `instanceHandle` | handle in the skinned renderer |
| `+0x34` | `visible` (u8) | 0 from the ctor, written by `CharacterAnimation::SetVisible` S 006c6120; copied into the pool instance's "effects enabled" byte (§2.11); idle variations start only when it is set (§3.9) |
| `+0x38..+0x44` | selection keys | keyA, keyB, keyC, outer key (§3.9); all -1 from the ctor |
| `+0x48` | `worldMatrix` pointer | |
| `+0x4c` | `currentAnimId` | -1 = none |
| `+0x50` | `hasEvents` (u8) | the current animation id has an entry in the animation-event table (§3.12) |
| `+0x54` | `requestedType` | animation type, -1 = none |
| `+0x58` | `loopMode` | `maxLoops` of the current request |
| `+0x5c` | `force` (u8) | set when a selection key changed |
| `+0x60` | `ownerLogic` | the logic settler (`NSettlers::Settler*`) |
| `+0x64` | `oneShotPlaying` (u8) | an idle variation is playing |
| `+0x68` | `idleSequencer` | `RandomAnimPlayer*` |

**[known]** (S 006c61d0, S 006c63a0 disassembly, S 006c64c0, S 006c60a0)

### 2.16 Character definitions (`S2CG::CCharacterMgr`)

`CharacterModelDef` (100 bytes): `+0x00` `model` index into the model-name list, `+0x04` name, `+0x20` `slotMap`
(colour-map name, default `"default"`), `+0x3c` array of up to 4 `CMesh*` (LOD 0..3), `+0x40` their count, `+0x44`
the colour-index texture, `+0x48` `link` bone name (default `"SLOT_HandR"`). **[known]** (S 00694c00)

Globals read from `<Characters>` (S 00695130) **[known]**: `scale` S 008816e0, `evadeRadiusScale` S 008816e4,
`evadeStart` S 008816e8, `goodRotation` S 008816ec (degrees), `lod0Range` / `lod1Range` / `lod2Range` S 008816f0 /
f4 / f8, `boatOffset` S 00881704 (2 floats), `goodOffset` S 0088170c (2 floats).

---

## 3. Rules and algorithms

### 3.1 Loading a KEX file

1. **Name mapping.** A path containing `.gr2` or `.GR2` has its last three characters replaced by `KEX`
   (`CMesh::Load` S 0076e0d0, `CAnimatedObject::Load` S 0076b4a0, `AnimResMgr::LoadAnimation` S 004de400). The
   path then goes through `ai::file::FileScanHolder::ResolvePath` (the `[data]` prefix). **[known]**
2. **Cache.** `SharedResourceCache::Acquire(path, key)` S 004ef660 returns the loaded `KFile` for the pair (path,
   52-byte `KSceneCoordSystem` key), loading it on first use and counting references. The same file loaded with
   two different scales is two cache entries. A file that fails to load is cached as null. **[known]**
3. **Read.** `KScene_LoadFile(path, target, bakeFlag = 1)` S 0072a7b0 constructs the `KFile` and reads it with
   `fopen("rb")`/`fread` (layout: `asset-formats.md` §2). KEX files are not encrypted. A failed open is not
   checked. **[known]**
4. **Bake on read** (always, because `bakeFlag` is always 1):
   - *Skeleton* (`KSkeleton::Load` S 0072d290): after reading each bone, `KBoneKey_StripIdentityComponents`
     S 0072f720 clears a flag whose component is within `1e-5` of neutral (position all `|p| <= 1e-5`, rotation
     near `(0,0,0,1)`, matrix near identity). Then `FlattenBoneOrientations` S 0072ce50: for every bone with a
     parent, `position = position * inverse(ownMatrix3x3)`; then every bone's 3x3 matrix is set to identity and
     flag bit 2 cleared. **[known]**
   - *Animation* (`KAnimation::Load` S 0072dcf0): for a track with a scale channel, every position key is
     replaced by `position * inverse(scaleKey)` (if the track has positions) and the scale channel is freed. Then
     `invLength = 1 / length`. **[known]**
   So at run time no bone and no track carries a scale or shear matrix.
5. **Import transform** (`KFile::ApplyImportTransform` S 0072a9a0, when a target system is given; every engine
   caller gives one). With `F` = matrix whose columns are the file axes and `T` = matrix whose columns are the
   target axes: `B = (F * T) * (target.unitScale / file.unitScale)`, `N = inverse(B)`,
   `d = target.origin - file.origin`. Then **[known]**:
   - mesh streams (`KMesh::TransformVertices` S 0072c550): type 0 `p = p * B + d`; type 1 `n = N * n` (column
     vector, i.e. the inverse transpose); type 2 `t = t * B`; if `det(B) < 0`, the second and third index of
     every triangle are swapped;
   - skeleton (`TransformBones` S 0072cd80): per bone key `position = position * B + d`,
     `rotation = quat(N * mat(rotation) * B)` normalised (`Quat_TransformBasisInPlace` S 0072f9c0), 3x3 matrix
     `= N * S * B`; per inverse-bind matrix `rot3x3 = N * R * B`, `translation = t * B + d`
     (`Mat4_ApplyBasisChange` S 0072fa20);
   - animation (`TransformKeys` S 0072d810): the same per key; afterwards each track's rotation keys are made
     sign-continuous (a key whose dot product with the previous key is negative is negated).
6. **Result for the shipped data.** With the file axes of §2.2 and the engine target,
   `B = s * [[0,0,1],[-1,0,0],[0,1,0]]`, `s = modelScale / file.unitScale`, so a file point `(x, y, z)` becomes
   the engine point `s * (-y, z, x)`. `det(B) < 0`: the files are right-handed with Z up, the engine is
   left-handed with Y up, and the loader flips the winding once. **[inferred]** (arithmetic on **[known]**
   constants)

The model scale `target.unitScale` comes from the caller **[known]**:

| Object | Scale | Source |
|---|---|---|
| settler meshes, settler skeleton, settler animations | `<Characters scale>` (S 008816e0) | S 00694480, S 00692390 **[known]** |
| donkey / ox meshes | `<Donkey scale>`, default 1.0 | S 00693880 **[known]**; skeleton and animations with the same value **[inferred]** (the arguments of those two calls are not resolved in the decompile) |
| animal mesh | the type's `scale` attribute, default 1.0 | S 0069b7c0 **[known]**; skeleton and animations with the same value **[inferred]** (the decompile shows the same variable; the calls were not disassembled) |
| building meshes (the LOD meshes and the `frame` mesh), building skeleton | 1.0 | S 006d4060 (`fld1` at the skeleton load S 006d40f6) **[known]** |
| building state animations (`DoorOpen`, `DoorClose`, `Working`) | 1.0 (`0x3f800000`) | S 006d3880 **[known]** |
| building production animals: mesh, skeleton, animations | `<Production scale>`, default 1.0 (`production +0x68`) | S 006d3880 (the float is passed unconverted, S 006d3d1e), S 006d4060 **[known]** |
| ship mesh, ship skeleton, ship animations | `<Ship scale>`, default 1.0 (`ShipDesc +0x04`) | S 00698cb0 (float passed unconverted, S 00699186), S 00698290 → S 006a51e0 **[known]** |
| animated items: skeleton and animation | 1.0 | S 006c9660 **[known]** |

Where the decompiled C shows an `(int)` cast on a scale handed to `LoadAnimation`, `CModelCache::ctor` or
`Ship::ctor`, the machine code passes the float's bits unchanged (`fld` / `fstp [esp]`); no rounding happens.
**[known]** for the two sites named above, **[inferred]** for the others.

Because the scale is part of the cache key and is applied to positions, a skeleton, its meshes and its animations
must be loaded with the same scale to fit together. **[inferred]**

### 3.2 Building a `CMesh` from a `KFile`

`CMesh::Load(path, vertexDecl, scale, mergeAllMeshes, rebaseMergedIndices, meshName, noCache)` S 0076e0d0
**[known]**:

1. Unless `noCache`: if the `.mshraw` cache file is up to date (§3.3) load it and return.
2. Acquire the `KFile` (§3.1), build the vertex layout from the declaration.
3. `mergeAllMeshes == false` → `LoadSingleFromKFile` S 0076de30: the first mesh, or the mesh whose name equals
   `meshName`; returns false when no mesh matches. Vertices via `FillVertices` (§2.4). Indices are narrowed to
   `u16` and each triangle `(i0, i1, i2)` is written as `(i0, i2, i1)`. Bone names are copied. Tangents are
   computed (`ComputeTangents` S 0076c320) when the declaration has a tangent element and the mesh has no type-2
   stream. Subsets are appended from the mesh's materials: one subset per material with a non-zero triangle
   count, with name, start index, primitive count and the texture list, each texture path cut to its file name
   (everything after the last `\`). **[known]** / subset fields **[inferred]** (§2.4)
4. `mergeAllMeshes == true` → `LoadMergedFromKFile` S 0076d3d0 **[known]**:
   - Order: for `i = 0 .. meshCount-1` the mesh named with the decimal text of `i` is looked up and appended to
     the order list; when no mesh at all is named so, the order is the file order.
   - Subsets: first the material subsets of the file's mesh 0 are appended as in step 3 (name, textures). Then,
     for each mesh in order, the **last** subset of the list is overwritten with `startIndex` = running index
     count and `primitiveCount = numIndices / 3`, and (except after the last mesh) a new subset with no texture
     list is appended. With one material on mesh 0 this gives one subset per source mesh, of which only the
     first carries a name and textures.
   - Vertices are concatenated (`FillVertices` per mesh); indices are written with the same `(i0, i2, i1)`
     reorder plus a base vertex that advances by the mesh's vertex count only when `rebaseMergedIndices` is
     set.
   - Tangents are computed when the declaration has a tangent element and at least one mesh has no type-2
     stream. **[inferred]** (the counter of meshes with a type-2 stream is not visible in the decompile)
   What happens when only some meshes carry numeric names, or when mesh 0 has no material, is not guarded
   (the order list is then shorter than the mesh count, or the "last subset" does not exist). **[known]**
5. If the build succeeded: release the `KFile` and, unless `noCache`, write the cache file. (After a failed
   build the `KFile` reference is not released.) **[known]**

The engine uses `mergeAllMeshes = true` only for a building's `frame` mesh among the callers read (S 006d4060);
ships, animals, settlers, donkey, production animals and building LOD meshes load a single mesh. Building LOD
meshes ask for the mesh named `House` and fall back to the first mesh when there is none. **[known]**

The winding is therefore swapped twice for the shipped data (once in §3.1 step 5, once here): the index order in
the GPU buffer equals the order in the file, in a mirrored space. **[inferred]**

Settler meshes are loaded with `mergeAllMeshes = false`, `meshName = null`, i.e. only the first mesh of a settler
mesh file is used. **[known]** (S 00694480)

### 3.3 The mesh cache (`.mshraw`)

Path (`CMesh::GetPackedCachePath` S 0076c9f0): `%LOCALAPPDATA%` + `\` + `SAdK` (the string at S 007d421c) + `\` +
the source file's base name (the part after the last `\` or `/`) without its 4-character extension + (`_` +
meshName, when a mesh name was given) + `.mshraw`. The folder is created first. **[known]**
The directory part of the source path is dropped, so two source files with the same base name share one cache
file. **[inferred]**

Valid when the file exists and `File_CompareWriteTime(cache, source) > 0` (cache newer than the KEX)
(S 0076cbe0). **[known]** The model scale and the vertex declaration are *not* part of the name or of the check.
**[known]**

Layout, little-endian (`SavePackedBinary` S 0076bdc0, `LoadPackedBinary` S 0076d990) **[known]**:

```
u32  vertexCount
u32  vertexStride
u8   vertices[vertexCount * vertexStride]      interleaved, in the layout of the vertex declaration
u32  indexCount
u16  indices[indexCount]
u32  boneNameCount
str  boneNames[boneNameCount]                  str = u32 length + bytes
u32  subsetCount
subsetCount x {
  str  name
  u32  startIndex
  u32  primitiveCount
  u32  textureCount
  textureCount x { str usage; str fileName }
}
```

There is no magic number and no version. Any short read logs `Failed: Mesh: loaded binary '%s'`, frees the mesh
and falls back to the KEX. The vertex data is already in engine space (transformed and scaled). A remake has no use
for this cache except as a cross-check of a converter.

### 3.4 Sampling an animation

`KAnimation::ComputeKeyInterp(time, out, loop)` S 0072d650 **[known]**:

```
u    = time * invLength
f    = (u - trunc(u)) * keyCount
key0 = trunc(f)
if key0 == keyCount - 1 and not loop:  return false            (no interpolation; show key0)
key1 = key0 + 1  if key0 < keyCount - 1  else 0
t    = f - key0
return true
```

So key `i` sits at time `i * length / keyCount`; the keys are evenly spaced and the interval after the last key
blends back to key 0 when looping. A non-looping animation shows its last key unblended during the final
`length / keyCount` seconds.

`KAnimation::SampleTrack` S 0072d6e0: position = linear interpolation of the two keys; rotation =
`Quat_Slerp` S 0072e250 (the dot product of the two keys is made positive, and when it was negative one of the
two keys enters with the opposite sign; if `1 - dot <= 0.01` the weights are the linear `1 - t` and `t`;
otherwise `sin((1-t)θ)/sin θ` and `sin(tθ)/sin θ` with `θ = acos(dot)`; the result is not renormalised); scale
matrices = element-wise linear interpolation. Missing channels give position 0, rotation `(0,0,0,1)`, identity
matrix and leave the flag bit clear. **[known]** The arguments of the `acos` and the three `sin` calls are on
the FPU stack and not visible in the decompile: the two slerp weights as written are **[inferred]** (one `acos`,
three `sin`, two divisions by the first `sin`).

### 3.5 Playing: `KAnimationControl` and blending in `KModel`

`KModel::PlayAnimation(animation, timeOffset, duration)` S 0072bbd0 creates a control (§2.9) and puts it at the
head of the model's list. At construction each track is bound to a bone by name (`skeleton.FindBoneIndex`); tracks
whose bone the skeleton lacks are ignored, bones without a track keep whatever the other controls or the bind pose
give them. **[known]** (S 00730070)

`KModel::Update()` S 0072c1d0, once per model per frame **[known]**:

1. For every control: `active = IsActive()` = `(weight > 0 and heldFrame == -1) or fadeDuration > 0`
   (S 0072ff00).
   - Active: `Advance(deltaTime)` then `SamplePose()`.
   - Inactive with `autoRemove`: unlink and delete.
2. `frameStamp += 1`; for every bone: blend (below).

`Advance(dt)` S 007301e0 **[known]** (disassembly):

```
time += speed * dt
if fadeDuration > 0:
    if time >= fadeStart + fadeDuration:  weight = fadeTo; fadeDuration = 0
    elif time >= fadeStart:               weight = fadeFrom + (fadeTo - fadeFrom) * (time - fadeStart) / fadeDuration
if weight > 0 and maxLoops != 0:
    loop = trunc((timeOffset + time) / duration)
    if loop < 0:            heldFrame = 0
    elif loop >= maxLoops:  heldFrame = animation.keyCount - 1
```

`SamplePose()` S 0072ff30: nothing when `weight <= 0`. If `heldFrame == -1` and
`ComputeKeyInterp(time + timeOffset, …, loop = (maxLoops == 0))` succeeds, every bound track is sampled (§3.4)
into the control's `bonePoses`; otherwise every bound track gets the raw key `heldFrame` (or `key0` when the
interpolation call returned false). **[known]** Note that sampling uses the animation's own length, while loop
counting uses the control's `duration`; the game-side callers read here pass duration 0, so both are the animation
length. **[known]** (S 0076a7e0 passes 0, 0)

Consequence for a play-once animation (`maxLoops = 1`): in the update in which `Advance` sets `heldFrame`, the
control is still active, so `SamplePose` writes the raw last key once. From the next update on `IsActive` is false
(no fade running): the control is neither advanced nor sampled and no longer contributes to the blend, and the
bones keep the pose of that last key through the stale per-bone state described below. The control itself stays
in the list until it is stopped (or deleted when `autoRemove` is set). **[inferred]** (from the three functions
above)

`FadeWeight(from, to, duration)` S 0072fe40: clamps `from` and `to` to `[0, 1]`, `fadeStart = time`,
`fadeDuration = max(duration, 0)`. **[known]** Its wrapper `CAnimatedObject::FadeAnimWeight` S 0076af80 has one
caller, the lobby's `AnimModel::Update` S 0050ec80 **[known]**; that no game-side code reaches the virtual by
another path is **[inferred]** (indirect calls through the control's vtable `+0x30` were not searched).

Blending one bone (`BlendBoneFromAnimations` S 0072bca0 and the tail of `Update`) **[known]**:

```
for each control c in list order, if c.active and c.bonePoses[bone].flags != 0:
    w = c.weight                               (virtual getter)
    if c.boneMask:         w *= c.boneMask.weight(bone)
    if c.inverseBoneMask:  w *= 1 - c.inverseBoneMask.weight(bone)
    if first contributor this frame:
        pose = c.sample with position, quaternion and matrix each multiplied by w   (plain copy when w == 1)
        weightSum = w; count = 1
    else:
        pose.flags |= sample.flags
        pose.position += w * sample.position
        pose.rotation += (dot(pose.rotation, sample.rotation) < 0 ? -w : w) * sample.rotation
        pose.matrix   += w * sample.matrix
        weightSum += w; count += 1
if weightSum <= 0:   pose = skeleton bind key of the bone
elif not (count == 1 and weightSum == 1.0):
    position, matrix and quaternion are multiplied by 1 / weightSum
```

It is a normalised weighted sum (quaternions are blended linearly and not renormalised). The per-bone state is not
cleared between frames: when no control contributes any more, the bone keeps its last pose, `count` and
`weightSum`; the tail above still runs on those stale values, so the pose is left alone only when they are
`count == 1` and `weightSum == 1.0` (the case of a single control of weight 1) and is otherwise divided by the
stale `weightSum` again every frame. **[known]** In the game proper every control has weight 1 and a model has
one control at a time for settlers and animals (§3.8), so there is **no cross-fade**: a change of animation is a
cut. **[inferred]**

### 3.6 Bone matrices and skinning

`KModel::UpdateBoneMatrices(rootMatrix)` S 0072c340, bones in index order **[known]**:

```
world[b] = toMat4(pose[b]) * (parent(b) == -1 ? rootMatrix : world[parent(b)])     (KBoneKey_MultiplyMat4)
skin[b]  = skeleton.inverseBind[b] * world[b]                                     (Mat4_MultiplyAffine)
bounds   = min/max over world[b].translation
```

`CAnimatedObject::SetWorldTransform(m)` S 0076a890 calls it with `m` as the root matrix and refreshes the
object's bounds. Pool instances of settlers and animals use the identity as root (S 006ad380), so their matrices
are in model space and the object's world matrix is applied by the shader; buildings, ships and animated items
pass their real world matrix. **[known]**

A mesh is bound to a skeleton by name (`KDeformableMesh::ctor` S 0072fd00): for each of the mesh's bone names,
`boneIndex[i] = skeleton.FindBoneIndex(name)` and a pointer to `skin[boneIndex[i]]`. The byte indices of stream 13
select from this per-mesh list. **[known]** What happens for a mesh bone name the skeleton lacks (index -1) is not
guarded. **[known]**

Skinned vertex (`shared.inc` `CalcSkinnedVertex`, data file `game/gfx/fx_20/shared.inc`) **[known]**:

```
position = Σ(i = 0..3) weight[i] * (float4(pos, 1) * g_InstanceMatrix[index[i]])
normal   = Σ(i = 0..3) weight[i] * (normal * (float3x3) g_InstanceMatrix[index[i]])
```

with `g_InstanceMatrix[MAX_BONES]`, `MAX_BONES = 50`; the shader functions take the number of influences as a
uniform (`_numBones`, at most 4). Weights are normalised to sum 1 at load (§2.4). **[known]** (data)
`SkinnedMeshRenderer::RenderInstances` S 0076e8a0 has a CPU path with the same blend (fewer influences allowed)
for the lowest quality level and a GPU path that uploads the matrix array. **[inferred]** (plate; the function
body was not read line by line → the path selection and the influence limit are **[TODO]**)

### 3.7 Animation slots on a `CAnimatedObject`

`AddAnimation(animId, timeOffset, duration, startTime, maxLoops)` S 0076b230 **[known]** (disassembly; the map's
parameter names `playArg1/2`, `callback`, `callbackArg` are these):

1. `animId == -1` → return -1. Take the `AnimResMgr` entry `animId`; an entry without animations → return -1.
2. Among the entry's `KAnimation`s pick the first whose **name equals the name of this model's skeleton**; start
   it with `KModel::PlayAnimation(anim, timeOffset, duration)`. If none matches, log
   `No anim found for "%s" in model "%s"!` and start the entry's first animation instead. (Example: the settler
   skeleton is named `Bip01` and `settler_walk.KEX` holds one animation named `Bip01`.)
3. On the new control: `SetWeight(1.0)`, `SetTime(0)`, `SetSpeed(g_AnimTimeScale)`, `maxLoops = maxLoops`.
4. Allocate a slot (reuse a freed handle, else grow), append its handle to the active list, store the animation
   id, the control and `startTime`. Return the 1-based slot handle.

`AddAnimationWithCallback(animId, startTime, maxLoops)` S 0076a7e0 = `AddAnimation(animId, 0, 0, startTime,
maxLoops)`. **[known]**

`AnimatedVisual::PlayAnimationWithEffects(animId, startTime, maxLoops, timeOffset)` S 006d8670: the above; if it
succeeded, create the animation's event attachments (§3.12), register the visual's own callback on the slot, and
`SetAnimTime(slot, timeOffset)`. **[known]**

Slot functions **[known]**: `SetAnimSpeed(slot, s)` → control speed `g_AnimTimeScale * s` (S 0076aee0);
`SetAnimTime(slot, t)` → control time `g_AnimTimeScale * t` (S 0076ad90); `GetAnimRemainingTime(slot)` =
`(control.GetTotalDuration() - control.time) / g_AnimTimeScale`, where `GetTotalDuration` is
`duration * maxLoops` for `maxLoops > 0` and `-1.0` for an endless loop, so the result is negative for looping
animations (S 0076ad40, S 00730020); `FindTrackByAnim(animId)` → handle of the active slot playing that id
(S 0050e9c0).

`g_AnimTimeScale` S 00884a6c is 1.0 in the image and is read from `<Animations globalSpeed>` of the scene settings
XML (`Scene::LoadSettingsFromXml` S 0067edd0). **[known]**

`CAnimatedObject::Update(now)` S 0076ac90: call `KModel::UpdateTime(now)` (vtable `+0x24`, §2.8), and if any slot
is active run `KModel::Update` (§3.5) and call each active slot's callback with the slot's animation id and
callback argument. The argument is an **absolute** time: the model derives its own step as
`max(now - lastTime, 0)`, so a caller that passed a per-frame step would freeze the animation. **[known]**

### 3.8 The shared pose pool (`CModelCache`)

Settlers of one skeleton and animals of one type do not own a posed skeleton each. All objects that play the same
animation id are drawn with the bones of **one** pool instance, so they move in phase. **[known]**

`Acquire(animId, maxLoops, holder, exclusive)` S 006ad4f0 **[known]**:

1. Scan the entries in order; take the first one that has no users, or (when not `exclusive`) whose `animId`
   equals the request or is -1.
   - If its `animId` is -1: (take the holder's effect argument when it had no users,) set `animTime = 0`,
     `animId`, start the animation with `PlayAnimationWithEffects(animId, 0, maxLoops, 0)`, `Update(0)`, root =
     identity.
   - An entry that already plays `animId` is joined as it is: the new user enters at the animation's current
     time.
2. No entry fits: create one. The first instance of a pool is loaded with
   `CAnimatedObject::Load(modelName, scale)`; later ones are cloned from an existing instance. Start the
   animation as above.
3. Append the holder to the entry's user list; `references += 1`. Return the entry index.

Callers pass `exclusive = (maxLoops != 0)`: a play-once animation always gets an instance of its own (or a free
one), a looping animation shares. **[known]** (S 006c63a0, S 006cddd0)

`Release(instance, holder)` S 006ad2e0: remove the holder; when the entry has no users left, stop its animation
slot and mark it free (`animId = -1`, `animTime = 0`). **[known]**

`Update(dt)` S 006ad380, once per frame per pool (nothing happens while the pool has no entries): add `dt` to
`gcTimer`; when it exceeds 10.0 and the pool holds more than 5 entries, subtract 10.0 and destroy every entry
whose `animId` is -1 and that has no users; then for every entry with a running slot (`trackHandle != -1`) and at
least one user call `instance.Update(entry.animTime)` and set the identity root; then `entry.animTime += dt` for
every entry. **[known]** The value handed to `Update` is the entry's accumulated time, which is what
`CAnimatedObject::Update` expects (§3.7). `dt` is the float at `+0x10` of the frame's view context
(S 00692a30). **[known]**

### 3.9 Which animation a settler plays

**Animation types (slots).** The settler `AnimationSet` is built with 10 slot names (pointer table S 008816b8)
**[known]**:

| Type | Name | Type | Name |
|---|---|---|---|
| 0 | `Stand` | 5 | `WorkLoop1` |
| 1 | `Walk` | 6 | `WorkLoop2` |
| 2 | `SwimIdle` | 7 | `Pickup` |
| 3 | `SwimFwd` | 8 | `PutDown` |
| 4 | `WorkLoop0` | 9 | `Hit` |

**Per logic tick** (`CCharacter::UpdateLogic` S 006909f0, called for every character from
`Scene::SyncLogicTick`) **[known]** (disassembly):

1. Skip when the settler's state is 6 (`settler +0x54`).
2. `req = logic.Update(time)` (virtual `+0x08` of the per-type render logic). It returns -1 except for a carrier
   in a boat, which returns 4 (standing) or 5 (moving) (`CharacterCarrier::Update` S 006c9250). `loopMode = 0`
   when `req != -1`, else `loopMode = -1` ("default").
3. Selection keys (`SetSelectionKeys` S 006c60a0; a change sets `force`):
   - keyA = `logic +0x24`: the good id of the item the settler holds. `SetOverrideItem` S 006c7460 sets it to
     the good of the item handed to the settler (a carried good), or, without one, to the good of its own
     attached item — the settler type's default item (`typeDef +0x74`, only if that good has an item type,
     S 006c72b0) — unless that item is an animated one; -1 otherwise. The value is the dword at `+0x0c` of the
     item record; that it is a good id is **[inferred]** (it is looked up in a table keyed by good id). A
     carrier in a boat gets the boat item's good (S 006c9250);
   - keyB = virtual `+0x14`: `logic +0x38`, the settler's property id (`NSettlers::Settler::GetPropertyId`,
     cached by the constructor S 006c7240) for the base class, soldiers, specialists, constructors and workers;
     -1 for carriers (vtables S 007fb984, S 007fb9d0, S 007fba50, S 007fba8c, S 007fbac8, S 007fbb0c);
   - keyC = virtual `+0x18`: for workers the first dword of the workplace building's type record while the
     workplace reference is valid (S 006c8620); -1 for every other class; that this dword is the building's
     property id is **[inferred]**;
   - outer key = the owning player's tribe id (`settler +0x28 → +0x44`).
4. If `req == -1`: `req = CharacterAnimation::UpdateLogic()` S 006c6590, which maps the action timer kind
   (`settler +0x1c`, `NSettlers::Animation.kind`, `settlers-jobs.md` §2.5):

   | Timer kind | Meaning in the simulation | Animation type |
   |---|---|---|
   | 2 | first half of pick-up / put-down | 8 `PutDown` |
   | 3 | second half of pick-up / put-down | 7 `Pickup` |
   | 4 | work | 4 `WorkLoop0` |
   | 5 | alternative work | 5 `WorkLoop1` |
   | 6 | dying | 6 `WorkLoop2` |
   | 7 | (not started by any movie listed in `settlers-jobs.md`) | 9 `Hit` |
   | other | | -1 |

   If the render logic's byte `+0x2c` is set and the result is 4, 5 or 6, the result becomes -1 (the settler is
   not shown working). Otherwise, for 7 or 8 with the character's pile latch set, the latch value (pile height)
   is copied into the movement component (`+0xe8`) and the latch is cleared. **[known]** The byte `+0x2c` is
   written only for workers (`CharacterWorker::UpdateTargetBuilding` S 006c8c10): once the worker's workplace
   reference is valid it becomes the byte at `+0xb0` of the workplace's property record, and 0 again when the
   reference is gone. **[known]** That byte is the building property `catapult` (`properties-data.md`):
   the crew of a catapult never shows a work animation of its own. **[inferred]**
5. Advance the render movement (`CharacterMovement::UpdateLogic`).
6. If `req` is still -1: below the water level → `2 + moving`; else → `moving ? 1 : 0`.
7. Queue `(req, loopMode)`; it is applied in the next frame update.

**Per frame** (`CCharacter::Update` S 00690bd0): apply the queued request with
`CharacterAnimation::SetAnimationType(type, loopMode)` S 006c64c0 **[known]**:

- `loopMode == -1` → `loopMode = (type > 3) ? 1 : 0`: stand, walk and swim loop; work, pick-up, put-down and hit
  play once and hold their last key.
- Unchanged type and loop mode and not `force`: nothing, except that an unchanged type 0 on a visible character
  (`+0x34`) with no idle sequencer running starts idle variations when the set has random animations for keyA
  (§3.11).
- Otherwise: clear `force`; if an animation is playing, `PlayAnimation(-1, 0)` (the character moves to a pool
  instance without animation); if the type is not -1, `animId = set.GetAnimIdForSlot(type, keyA, keyB, keyC,
  outerKey)` and `PlayAnimation(animId, loopMode)`; remember the type; drop a running idle sequencer.

`CharacterAnimation::PlayAnimation(animId, loopMode)` S 006c63a0: release the pool instance in use, acquire one for
`animId` (§3.8), and when this character is the instance's only user and the settler's virtual `+0x30` returns
true, set the slot speed to the settler's virtual `+0x34` (`settlers-jobs.md` §2.3: only `Soldier` overrides the
pair; base returns false / 1.0). If the instance changed, rebind the renderer's bone source
(`SkinnedMeshRenderer::RebindInstanceBones`). **[known]**

**Resolving type → animation id** (`AnimationSet::GetAnimIdForSlot` S 006ca8d0), first hit that is not -1
**[known]**:

1. keyC ≠ -1: `overrideByOuterKeyC[outerKey][keyC][type]`
2. keyB ≠ -1: `overrideByOuterKeyB[outerKey][keyB][type]`
3. keyA ≠ -1: `overrideByKeyA[keyA][type]`
4. `defaultAnimBySlot[type]`

**How the tables are built** (`AnimationSet::ctor` S 006cc350) **[known]**: after loading `<Animations>` (§6.2),
`defaultAnimBySlot` is filled for every set; the three override tables only when the constructor's
`buildPropertyOverrides` argument is set — 1 for the settler set (S 00692390) and the donkey set (S 00693880,
which uses the same 10 slot names), 0 for the animal sets (S 0069b7c0, 4 slot names).
Last, the set's `<RandomAnimations>` child is loaded (§3.11).

- `defaultAnimBySlot[i]` = id of the animation named exactly like slot `i`;
- for every good of the properties database whose name `G` gives at least one existing animation
  `<slotName><G>`: if the good's type field (`+0x14`) is 1, then for every tribe a row
  `overrideByOuterKeyB[tribe][goodId][i] = FindAnimIdByName(slotName_i + G, tribe)`; otherwise a row
  `overrideByKeyA[goodId][i] = FindAnimIdByName(slotName_i + G, -1)`;
- for every record of the properties map at `StaticAccess +0x00` (id `+0`, name `+4`) whose name `N` gives at
  least one existing animation `<slotName><N>`: for every tribe a row `overrideByOuterKeyC[tribe][id][i]`.

Names are concatenated without a separator and compared exactly (case-sensitive memcmp): `WalkWood`,
`StandPlank`, `WorkLoop0Scythe`, `WorkLoop0Forester`, `WorkLoop0Smelter`. A row entry whose name does not exist is
-1 and falls through to the next level. Since keyB at run time is a settler's property id and keyC a building's,
type-1 goods are the settler kinds and the `+0x00` map holds the buildings. **[inferred]**

`FindAnimIdByName(name, tribe)` S 006ca790: the first animation with that name decides; with `tribe != -1` and a
non-zero `tribes` mask on the record, the id is returned only if `mask & (1 << (tribe & 31))` is set, else -1 (the
search does not continue to a later record of the same name). **[known]** Which number each tribe contributes to
this test is **[TODO]** (§10): the value is the key of the properties tribe map, the same key the run-time lookup
uses.

### 3.10 What the per-type render logic adds

All of this reads simulation state and writes only render state.

- **Base** (`CharacterSettler::Update` S 006c7640) **[known]**: refresh the target building when asked to
  (virtual `+0x34`, only while the figure has no route spline); while the figure is **not** moving, face the
  cell at `settler +0x70` when it is not -1; run the door trigger of the target building when there is one;
  when the settler state is 5 (dying): wait until the current animation's remaining time is `<= 0` (or the
  figure has no pool instance), then sink the figure on every update: `offset -= dt * 0.35`, written to the
  movement component (`+0x120`); `dt` = the third float of the time record.
- **Worker** (`CharacterWorker::Update` S 006c8ab0) **[known]**: while the action timer kind is 4 or 5,
  `workElapsed = (total - remaining) * dt` and `workDuration = total * dt` (timer fields at `settler +0x24` /
  `+0x20`, `dt` = the third float of the time record). Then by the workplace's working mode: mode 1 handles
  tree felling / facing the work object (branch structure **[inferred]**); otherwise `UpdateWorkplaceWork`
  S 006c88c0: if the worker is at its
  workplace and the building's work animation is not running (or must restart: building flag `+0xb0` and
  `workElapsed == 0`), start it with `Building::PlayOneShotAnimation(time, workDuration, kind, workElapsed,
  speed)` where `speed = Worker::GetWorkAnimSpeedFactor()` if `Worker::ShouldSpeedUpWorkAnim()` else 1.0; if the
  figure's own animation still has time left and the set has a keyB/keyC override for the current type
  (`HasSlotOverride`), call `Building::TriggerWorkCycle`. After that, for working modes 0 and 2 (the job's
  target object, cell at its `+0x20`), 3 (the cell at `job +0x94`) and 7 (the hunted animal's cell) the figure
  is turned towards that cell. Workers with an animated tool create the tool's `AnimatedItem` while working
  (hiding the static tool) and destroy it afterwards.
- **Constructor** (S 006c8480): while timer kind 4, face the construction site. **[known]**
- **Soldier** (S 006c7f80): face the fight target; show buff particle effects (`SoldierDamage` at the right-hand
  bone matrix, `SoldierDefense`, `BlindSoldier` at the head matrix, `ArcherSpeed`). **[known]**
- **Carrier** (S 006c9250) **[known]**: on a water street with a boat, start the `BoatFX` emitter, switch between
  boat mode and wading, bob with `sin(phase) * 0.15 + 0.3` times the boat draft
  (`phase += dt * 0.7 * const` S 00882840), and return animation type `4 + moving` (so `WorkLoop0Boat` /
  `WorkLoop1Boat` through keyA = the boat good **[inferred]**).

### 3.11 Idle variations (`RandomAnimDesc`, `RandomAnimPlayer`)

`<RandomAnimations>` of the set holds `<Random minDelay maxDelay>` groups with `<Animation src probability>`
children (`RandomAnimDesc::LoadXml` S 006de030): each child is loaded as an animation; its integer weight is
`trunc(probability / smallestProbabilityOfTheGroup + 0.5)` (disassembly: `FDIV`, `FADD 0.5`, `__ftol2`);
`totalWeight` is the sum. `probability` defaults to 1.0. **[known]** Every child element of `<RandomAnimations>` is one group
(`LoadRandomAnimationsXml` S 006cb130; the element name is not tested): with an `item` attribute — the name of a
good, resolved with `PropertiesDb::FindGoodIdByName` — the group is stored in `randomAnimByItem[goodId]`;
without one it becomes the set's default (a later default group replaces an earlier one). **[known]**

`RandomAnimPlayer::Update(dt)` S 006ddfa0: `timer -= dt`; when `<= 0`: next index in a shuffled order of
`totalWeight` entries (reshuffle on wrap), `timer = duration(animation) + minDelay + rand01 * (maxDelay -
minDelay)`, return true. `rand01` comes from the generator at S 0088e120, not the simulation's. **[known]**

`CharacterAnimation::UpdateLogic` S 006c6590, once per logic tick: with a sequencer and not in a one-shot, when the
player fires, play the chosen animation once (`PlayAnimation(id, 1)`, `oneShotPlaying = 1`); while in a one-shot,
when its remaining time is `<= 0`, return to the animation of the requested type with loop mode 0. **[known]**
This is the only place where an animation's length (`AnimResMgr::GetAnimationDuration` S 004de100) drives a timer,
and the timer is render state.

### 3.12 Animation events (sounds, particles, items)

Children of an `<Animation>` element (and of a building's `DoorOpen` / `DoorClose` / `Working` element, and of a
random-animation child) are registered per animation id by `EffectScriptMgr::LoadAnimEvents` S 006867d0; the
element names it knows are `Sound`, `Particle` and `Item`. **[known]** (string literals) Attributes seen in the
data: `<Sound start="0.3" name="scythe"/>`, `<Particle start="9.36" duration="7.3" name="SawDust"
slot="sawdust00"/>`; no `<Item>` event occurs in the install's XML files read here (§6). An animation id that
already has events is not loaded again.

Event descriptors **[known]** (each creator's `Desc::LoadFromXml`): all three read `slot` (a name; its use as a
bone name is **[inferred]**, §3.13), `start` and `duration` (floats; `EventBase::Desc::LoadBaseXml` S 00685b30),
then `name`: a sound of the properties database (`PropertiesDb::FindSoundIdByName`, S 006b0920), a particle effect
of the effect script manager (`FindEffectIndex`) plus an `offset` of three floats (S 006b09f0), or an item type
(`ItemTypes_FindByName`, S 006b0a50).

Event behaviour **[known]**: `EventBase::Tick(time, allowStart)` S 006b00f0 computes
`local = (time - startTime) * g_AnimTimeScale`; once `local >= start` (and `allowStart`) it calls the event's
`Start` a single time, and from then on its `Update(local)` every tick, whose result decides whether the event
stays active. A particle event starts its effect at the event's world transform plus the rotated `offset`
(S 006b05e0), follows that transform every tick, and ends when `duration > 0` and `local >= start + duration`;
with `duration == 0` the emitter is told to stop right after the start (S 006b0710). An item event creates a
visual item of the named type through `ItemMgr::CreateItemByType`, marks it externally positioned (item byte
`+0x58`) and copies the event's world transform into the item's matrix every tick; it never ends by itself
(S 006b0800, S 006b0840). `SoundEvent::Start` / `Update` (S 006b0550, S 006b01f0) were not read → **[TODO]**.

When an `AnimatedVisual` starts an animation it instantiates the animation's events (§3.7). Each frame its
callback (`Callback_OnAnimUpdate` S 006d8570) computes the event time — the slot's animation time plus the slot's
start time, or the global clock when the slot's start time is 0 — and ticks every attachment of that animation id
(`EventBase::Tick(time, enabled)`). **[known]** Events are tied to the pool instance, so one shared instance emits
them once for all settlers that share it. **[inferred]**

### 3.13 Attachment points

Attachment is by bone **name**, resolved once to a bone index with `CAnimatedObject::GetBoneIndex` S 0076a9f0
(`skeleton.FindBoneIndex`); the attached object's world matrix is `boneWorld * objectWorld`, with `boneWorld` the
bone's matrix in `KModel.boneMatrices` (model space for pool instances). **[known]** (S 006c7760, S 006c60f0)

| Attached thing | Bone | Evidence |
|---|---|---|
| a settler's tool / weapon (the type's default item good), or its animated variant | the definition's `link` attribute, default `SLOT_HandR` | S 00694c00, S 006c7850, S 006c7760 **[known]** |
| the good a settler carries | bone index from virtual `+0x20` of the render logic: the definition's link bone (`+0x0c`) for every class except the carrier, which returns its own index `+0x88`, resolved by its constructor from the bone name it is given (-1 without a name) | S 006d09b0, S 006c8d40, S 006c9150, vtables of §3.9 **[known]**; which name the carrier is given is **[TODO]** (`CCharacterMgr::CreateCharacter` S 00695490, call not resolved in the decompile) |
| goods on a donkey / ox | `link="SLOT_Goods"` | `settler_config.xml` `<Donkey>` **[known]** (data) |
| a carrier's boat | placed at the figure's matrix shifted by `boatOffset` (x, z) and lowered by `draft * 0.7`; its cargo at `goodOffset` rotated by `goodRotation` degrees about Y | S 006c8ee0 **[known]** |
| production animals of a building | bones named by `boneLink0..N`, or fixed `location0..N` vectors | S 006d3880 **[known]** |
| building fire points, sound / particle / item events | bone names | S 006ac510, S 006b0350, S 006b0400, S 006b0880 **[inferred]** (callers of `GetBoneIndex`; not read) |

The settler skeleton has exactly one helper bone, `SLOT_HandR` (46 bones). No animation track targets it in the
sampled files, so it follows its parent with its bind key. **[known]** (data: `settler_model.KEX`,
`settler_walk.KEX`)

A lying or falling item not attached to anybody gets an identity rotation at its position (S 006d0830). **[known]**

### 3.14 Level of detail

`CCharacter::UpdateLod` S 00690460: starting at 0, the LOD index is raised while the squared camera distance is
not less than the square of the next threshold of `lod0Range`, `lod1Range`, `lod2Range` (result 0..3), unless
forced to 0 by the caller or replaced by the manager's forced LOD (manager `+4 != -1`); the skinned renderer
switches to the definition's mesh of that index (`mesh`, `mesh1`, `mesh2`, `mesh3`). All LODs are driven by the
same bones. **[known]** `SkinnedMeshRenderer::SetInstanceLod` S 0076e850 clamps the index to
`0 .. meshCount - 1` of the instance's mesh group, so a definition with fewer meshes keeps its last one, and
stores the unclamped non-negative index as the instance's influence reduction. **[known]**

### 3.15 Colouring

**Settlers** (shader `game/gfx/fx_20/skin_color_mesh.fx`, constants set in `CCharacter::SetShaderConstants`
S 006910e0) **[known]**:

- The mesh's texture 0 is the definition's `color` texture (e.g. `bavarian_colorindices_luminance.dds`), sampled
  with point filtering. Its channels: **R** = palette row, **G** = luminance, **B** = specular strength, **A** =
  1 for palette colour, 0 for player colour.
- Texture 1 is a 1024x1024 atlas holding one 256-entry palette (16 slots x 16 shades) per distinct settler
  look. The lookup is `u = saturate(G * light) * (15 / atlasWidth)`, `v = R * (256 / atlasHeight)`, plus the
  palette's atlas offset and half a texel (`COLOR_INDEX_SCALE`, `TEXTURE_ATLAS_OFFSET`).
- `rgb = lerp(playerColor * G * light * 2, paletteColour, A)`, then `+ specular * B`; output alpha = A.
- `playerColor` (`PLAYER_COLOR`) is the owning player's colour entry (`Player_GetColorEntry` S 005be2c0 of
  `settler +0x28`).

The palette of a settler is built when its character is created (`CCharacterMgr::CreateCharacter` S 00695490):
the colour map named by the definition's `slotMap` gives, for each of 16 palette slots, a colour-ramp name; one
variant of each ramp is drawn at random (`ColorMapTable::BuildRandomPalette` S 006c9770) with a static generator
seeded `0x5432ace0`; equal palettes share one atlas entry (`AcquirePaletteTexture` S 00693140). **[known]** So
hair, skin and clothing shades vary per settler, and only the texels with A = 0 show the team colour.

Colour ramps (`ColorMapTable::LoadFromXml` S 006c9d20, file `[data]\character\color_slots.xml`) **[known]**: a
ramp is 16 colours; a `<ColorRamp slot=…>` gives one variant as `solid="r g b"`, as a gradient `lit=` / `dark=`,
as 16 `<… value="r g b">` children, or several variants as the rows of a 16-texel-wide `texture` (32-bit, `rows`
= number of rows used, default the texture height). `<ColorMap name>` children `<Material index slot>` map palette
slot `index` to a ramp.

**Ships** (`ships.fx`): `rgb = lerp(colour, colour * lerp(1, playerColor * 1.8, textureAlpha), playerColorWeight)`
with `PLAYER_COLOR` and `PLAYER_COLOR_WEIGHT` set by `ShipMgr`: the diffuse texture's alpha marks the team-colour
area. **[known]** (shader; S 006985e0 resolves both parameters) The values `ShipMgr` writes are **[TODO]**.

**Buildings** (`house_shader.fx`): no player colour. `rgb = light * diffuse * colorMap`, where `colorMap` is the
global building colour texture (`<Buildings colorMap>`, default `[data]\buildings\colors.tga`) sampled at the
third texture-coordinate set shifted in u by `COLORMAP_OFFSET = (instanceId % numVariations) / numVariations`
(`BuildingRenderer::DrawInstance` S 0069fb10 per its plate, S 006a0e60). It is a cosmetic per-building tint.
**[known]** / the modulo expression **[inferred]** (plate, not re-read). Team ownership of a building is shown by
its flag (`CMilitaryFlagRenderer`), not covered here.

### 3.16 Buildings

`BuildingDesc::LoadFromXml` S 006d3880 reads per `<Building>`: `mesh`, `frame` (construction-site mesh),
`enterDistance`, `leaveDistance`, `lodBias`, `lodScale`, `heading`, and three optional child elements in this
order (name table S 00882408): `DoorOpen`, `DoorClose`, `Working`, each with `file` (an animation, loaded with
scale 1.0) and optional event children (§3.12); the ids land in `desc +0x80 / +0x84 / +0x88`. An optional
`<Production>` child describes animals shown at the building: `mesh`, `model`, `texture`, `scale`, `numAnims` +
`anim0..`, `numModels` + (`location0..` | `boneLink0..`). **[known]**

Playing **[known]**:

- `Building::TriggerWorkCycle(time)` S 006aa640: `workCycleEndTime = time + 0.6`; if no cycle is pending, stop
  handle slot 0, play `DoorOpen` once (`PlayAnimationWithEffects(id, time, 1, 0)`), play the sound with property
  id `0xe29ef893` at the building when the building's virtual `+0x04` returns 0, and latch "pending".
  `Building::Update` S 006abcf0: when a cycle is pending and `workCycleEndTime <= time`, it calls
  `PlayStateAnimation(1, time, 0)` (`DoorClose`) and clears the latch.
- `Building::PlayStateAnimation(state, time, blend)` S 006aa3b0: states 0 and 1 use handle slot 0, state 2 slot
  1; stops the slot's animation, starts `desc.anim[state]` once with `blend` as its time offset; sounds
  `0xe29ef893` (state 0) and `0x9c700243` (state 1), under the same virtual `+0x04` test.
- `Building::PlayOneShotAnimation(time, duration, kind, offset, speed)` S 006aa6f0 (the worker's call of §3.10;
  `kind` is not used): if none is running, stop handle slot 1, start `Working` once with time offset `offset`,
  set its speed, mark running; always store `oneShotStartTime = time - offset` and
  `oneShotRemaining = duration`. `Update` S 006abcf0 subtracts the third float of the time record from
  `oneShotRemaining` on each call and, when it runs out, removes the slot's animation and clears the three
  fields.
- Nothing plays while the building is under construction or has no skeleton.

That the virtual `+0x04` test is a visibility test is **[inferred]** (plates of the two functions).

The catapult turns two bones procedurally (`CatapultBuilding::ApplyBoneRotations` S 006d5e50) **[known]**: both
bones are first reset to their bind key; the first gets a rotation about the axis constant S 00882864 by
`yawRender * π/180 + π - building.+0x28` radians, the second a rotation about the X axis by `-armRender`
radians; each through `CAnimatedObject::ApplyBoneOffset` S 0076a8e0 (multiply the bone's pose quaternion by
the rotation, add a zero translation, set flags 1 and 2). The bone names (`ROTATE`, `ARM_ROTATE` per the plate)
and the meaning of `building +0x28` are **[TODO]** (the function that resolves the two bone indices was not
read).

Buildings are skinned on the CPU by the building renderer: `BuildingRenderer::DrawInstance` S 0069fb10 calls
`CpuSkinVertices` for the mesh it draws. **[known]** (the call; the routine itself was not read)

### 3.17 Ships

`ships.xml` `<Ship>`: `tribe`, `scale`, `frame`, `mesh`, `model` (skeleton), `idle`, `move`, `sink` (animations);
plus three status meshes `<Freight>`, `<Expedition>`, `<Soldiers>`. **[known]** (data; `ShipMgr::LoadFromXml`
S 00698cb0 not read line by line). Mesh, skeleton and the three animations are loaded with the ship's `scale`
(§3.1).

`Ship::Update(time)` S 006a54c0, per logic tick **[known]**: while the logic ship's move progress
(`position record +0x20`) is `<= 0` the ship sits on its cell and the animation state is 2 when the logic
ship's state (`+0x28`) is 6 or 7, else 0; while it is `> 0` the position is interpolated between the two cells
and the state is 1. On a change the old slot is removed and `animSet[state]` is started through the object's
virtual `+0x0c` (`AddAnimationWithCallback`, §2.11) with the tick time as start time and `maxLoops = 1` on the
switch to state 2, 0 otherwise: idle and move loop, sink plays once and holds. That states 6 and 7 are the
sinking states is **[inferred]** (`navy.md`).

`Ship::UpdateVisuals(frame)` S 006a5cc0, per frame **[known]**: status mesh kind (-1 none; 1 when the logic flag at
`ship +0x30 → +8` is set; else 0 when the cargo is not empty; else 2 when the flag at `+0x40 → +8` is set) shown
through the plain mesh renderer; position and yaw interpolated between tick samples; roll and pitch from sines
(amplitudes 0.01 / 0.02 at rest, 0.04 / 0.08 under way), height = water level + `(sin + 1) * 0.06`;
`phase += dt * 0.25 * const` (`dt` = the fifth float of the frame record, the constant at S 00882840); then
`CAnimatedObject::Update(now)` with the second float of the frame record, and `SetWorldTransform`.

### 3.18 Animals

`animals.xml`: one element per animal type with `model`, `mesh`, `scale` and an `<Animations>` child with the four
names `Stand1`, `Stand2`, `Walk`, `Dying`. Each type gets its own `AnimationSet` and `CModelCache`
(`AnimalMgr::LoadAnimalTypesFromXml` S 0069b7c0). **[known]** (data; callers of the two constructors)

`Animal::UpdateLogic` S 006ce2c0, per logic tick **[known]**:

- Logic animal state (`+0x88`) 5, 7, 8 or 9 → play `Dying` once on an exclusive instance; latch dying.
- Alive and standing (move progress `+0x4c <= 0`): snap to the cell; if it was walking, play `Stand1` or `Stand2`
  looping, chosen with a static generator seeded `0x5432ace0`.
- Alive and moving: position = cell + (next cell − cell) * progress; start `Walk` looping if not walking; target
  heading from the hex direction table S 007f9494 (degrees).
- Dying and the death animation finished (`GetAnimRemainingTime <= 0`): sink, `offset -= dt * 0.4` per tick.

---

## 4. Update order

**On game load** (`S2CG::Scene::Init` S 006824c0) **[known]**, in this order, after `settings/graphics.xml` (scene
settings, §6.5) and the map renderer: `ItemMgr::LoadFromXml` (`settings/items.xml`);
`CCharacterMgr::LoadFromXml` (`character/settler_config.xml`: first `color_slots.xml`, then the tunables and
character definitions with their meshes and colour textures, the model list, the donkey; last it creates the
palette atlas); `CCharacterMgr::LoadAnimationSet` (`character/settler_animations.xml`: the settler animation set,
then one `CModelCache` per model of the list); `settings/buildings.xml`; `settings/animals.xml`;
`settings/ships.xml`. Each of the two character loads is skipped when its latch byte in the manager is already set.
All KEX files named by these XML files are loaded here; a `CMesh` goes through the `.mshraw` cache. Pool instances
(posed skeletons) are created lazily on first use. **[inferred]** (§3.8)

**Per logic tick** (`Scene::SyncLogicTick` S 00680550, step 22 of the tick in `logic-core.md` §4) **[known]**, in
this order: map renderer; `CCharacterMgr::UpdateLogicAll` (§3.9 per character: logic request, selection keys,
idle sequencer, movement, queue the animation type); `ItemMgr::UpdateAllCarrierAttachments` (who holds each
good, §3.13); `AnimalMgr::UpdateLogic` (§3.18); `ShipMgr::UpdateShips` (§3.17); swarms.

**Per rendered frame** (`Scene::Update` S 006805e0) **[known]** (call order in the decompile): refresh the time
record (`Scene::UpdateDetailFlagsAndTime` S 0067f6b0, below) and the device transforms; map renderer;
`CCharacterMgr::Update` S 00692a30 = (a) `CModelCache::Update(dt)` for every settler pool and the donkey pool,
which poses each shared skeleton once, (b) per character, only when the manager's visible cell rectangle
(`+0xb4..+0xc0`, copied from the map renderer just before) lies inside the map: a character outside that
rectangle is only hidden (unless the manager's force flag is set, which one update clears); every other one gets
`CCharacter::Update` — apply the queued animation type, advance the render movement, build the world matrix,
per-type logic (§3.10), attached item matrices, bounds — then (c) the frustum test, visibility and LOD;
`ShipMgr::UpdateGraphicEntries` (only in the branch taken when the scene has a selection context whose byte
`+0x50` is set); `ItemMgr::Update`; `AnimalMgr::Update` (its pools with the same `dt`, then every animal's
transform and visibility); `ShipMgr::UpdateVisibility` (→ `Ship::UpdateVisuals`); swarms; projectiles; particle
emitter culling; environment. So the per-type logic of a settler outside the visible cell rectangle does not
run: its death sink (§3.10) stands still until it is in view again. **[inferred]**

Within one `CAnimatedObject::Update` S 0076ac90: hand over the time (model virtual `+0x24`) and, only while at
least one slot is active, `KModel::Update` (virtual `+0x28`: advance and sample every control, blend every bone)
and then the slot callbacks (events). Bone and skin matrices are computed afterwards by `SetWorldTransform`
S 0076a890 (virtual `+0x2c`), which the pool calls with the identity matrix (S 006ad380). **[known]**

**The time record.** Every manager call above receives a pointer to five floats inside the scene object
(`Scene +0x48..+0x58`) **[known]** (S 0067fb40, S 00680550, S 0067f6b0):

| Offset | Value | Written |
|---|---|---|
| `+0x00` | simulation time of the next logic tick (`NLogic::System.nextTickTime`) | each logic tick; also on the first frame |
| `+0x04` | simulation time accumulated so far (`System.accumulatedTime`) | each frame |
| `+0x08` | the tick interval in seconds (`GameConfig +4`, 0.1; `logic-core.md` §3.1) | constructor |
| `+0x0c` | `1 / tick interval` | constructor |
| `+0x10` | frame delta (`System.frameDelta`) | each frame |

- `dt` of the pools (`+0x10`) is the simulation's frame delta: frame seconds times the game speed factors
  (`logic-core.md` §3.1), so pooled animations run faster and slower with the game speed and stand still while
  the simulation does. **[known]** (S 00692a30, S 0069aeb0, S 0067f6b0)
- The float at `+0x08` is a constant, not a delta. Code that multiplies by it converts ticks to seconds
  (the worker's `workElapsed`, §3.10) or advances by one tick interval **per call**: the idle-variation timer
  and the animal sink once per logic tick, the settler death sink once per call of the per-frame
  `CharacterSettler::Update` S 006c7640, the building one-shot countdown once per call of `Building::Update`
  S 006abcf0. **[known]** That the settler sink therefore depends on the frame rate is **[inferred]**; how often
  `Building::Update` runs is **[TODO]** (its callers are the virtual updates of the building subclasses).
- `Scene::Update` is entered with a flag; when it is non-zero the record is driven by a wall-clock timer instead
  (`+0x10` = timer step, `+0x04` and `+0x00` = its running sum). Which caller passes a non-zero flag is
  **[TODO]** (the function is reached only through the scene vtable S 007f8f2c slot 8).
- The swarm manager's frame argument is `1 - (record[0] - record[1]) * record[3]`: the fraction of the current
  tick that has elapsed. **[known]** (S 006805e0)

---

## 5. Inputs and outputs

**Consumes**

- KEX files (`asset-formats.md` §2), textures, shaders.
- XML: `character/settler_config.xml`, `character/settler_animations.xml`, `character/color_slots.xml`,
  `settings/buildings.xml`, `settings/ships.xml`, `settings/animals.xml`, `settings/items.xml`; from
  `settings/graphics.xml` the scene settings element `<Animations globalSpeed>` (§6.5).
- The properties database (`properties-data.md`): names and ids of goods, settler kinds, buildings and tribes,
  used only to build animation names (§3.9).
- Simulation state, read-only: per settler the state (`+0x54`), the action timer (`+0x1c` kind, `+0x20`
  remaining, `+0x24` total), target cell, carried package, workplace reference, owning player; the virtuals
  `+0x30` / `+0x34` (animation speed-up flag and factor); `Worker::IsAwayFromWorkplace`,
  `ShouldSpeedUpWorkAnim`, `GetWorkAnimSpeedFactor`; per animal state, cells and move progress; per ship state,
  cargo and movement; per player the colour entry and tribe id.
- The scene's time record (§4): next tick time, accumulated time, tick interval, frame delta.

**Produces**

- Draw data: per instance a bone-matrix array, a mesh (LOD), textures and shader constants.
- World matrices of bones for attachments, particle emitters and 3D sounds.
- Sound, particle and item events bound to animation times.
- Nothing that the simulation reads (§8).

**Interfaces to other documents**: `settlers-jobs.md` (the action timer and its kinds, the movies, the work
speed factor), `village-buildings.md` (building states that trigger door and work animations),
`navy.md` (ship states), `map-resources.md` (cell → world position, water level), `properties-data.md` (ids and
names), `players-victory.md` (player colour and tribe).

---

## 6. Data-driven parameters

### 6.1 `[data]\character\settler_config.xml` **[known]** (keys read at S 00695130, S 00694c00)

`<Characters scale="1.2" evadeRadiusScale="1.0" evadeStart="2.0" boatOffset="-0.25 0.2" goodOffset="-0.5 0.4"
goodRotation="10.0" lod0Range="30.0" lod1Range="40.0" lod2Range="60.0">` with 98 `<Character>` children (every
one has `name`, `color`, `slotMap`, `mesh`, `mesh1`, `mesh2`; 69 also `mesh3`):

| Attribute | Meaning | Example |
|---|---|---|
| `name` | `<tribe resource name>_<settler name>`; looked up as tribe name + `_` + character name, fallback: definition 0 | `Bavarian_Woodcutter` |
| `mesh`, `mesh1`, `mesh2`, `mesh3` | LOD meshes; the list stops at the first missing one | `…\meshes\bavarian_carrier_mesh_LoD1.KEX` |
| `color` | colour-index texture (required; a definition without `name` or `color` is skipped) | `…\bavarian_colorindices_luminance.dds` |
| `slotMap` | colour map name, default `default` | `bavarian_carrier` |
| `model` | index into `<Models>`, default 0 | (absent in the data) |
| `link` | attach bone, default `SLOT_HandR` | (absent in the data) |

`<Models><Model file="[data]\character\models\settler_model.KEX"/></Models>`: one skeleton for all settlers.
`<Donkey scale mesh mesh1.. model link="SLOT_Goods">` with its own `<Animations>` (the active block in the data is
the ox: `scale=".01"`, `oxTransport*.KEX`).

### 6.2 `[data]\character\settler_animations.xml` **[known]** (S 006caea0)

Root `<settler_animations>`; its `<Animations>` child holds 168 `<Animation name filename [tribes]>` elements
(children with another element name are skipped) and the `<RandomAnimations>` block.
Names are slot names (§3.9) optionally followed by a property name: `Stand`, `Walk`, `WalkWood`, `StandPlank`,
`WorkLoop0Scythe`, `WorkLoop0Boat`, `WorkLoop0Forester`, `WorkLoop0Smelter`, `WorkLoop2Sword`. Example files:
`settler_walk.KEX` (1.0 s, 18 keys), `male_idle00.KEX`, `soldier_falldown.KEX` (the default `WorkLoop2`, i.e. the
death animation, with `<Sound start="0.0" name="die"/>` and `<Sound start="0.3" name="fall down"/>`). Event
children in this file: 78 `<Sound>`, one `<Particle start="0.0" name="StoneDust"/>`, no `<Item>` (§3.12).
`tribes` is an integer bit mask, default 0 (the file's comment: 0 all, 1 Roman, 2 African, 4 Chinese; values used:
0, 3, 5). `<RandomAnimations>` holds one group, `<Random minDelay="5.0" maxDelay="8">`, with 11
`<Animation src probability>` children `male_idle00..10.KEX`: `probability` 0.1 for nine of them, 0.2 for
`male_idle01`, 0.01 for one; with the rule of §3.11 the weights are 10, 20 and 1 (total 111). **[inferred]**

### 6.3 `[data]\character\color_slots.xml` **[known]** (S 006c9d20)

`<SlotEnumeration>` (slot names such as `Hair`, `Skin`, `Jacket`, `Soldier_Armor_gold`), `<ColorRamps>` (e.g.
`<ColorRamp slot="Hair" texture="[data]\character\colormaps\hair_table.tga" rows="16"/>`,
`<ColorRamp slot="_empty_" solid="0.0 0.0 0.0"/>`), 63 `<ColorMap name>` elements with
`<Material index="3" slot="Hair"/>` children.

### 6.4 `settings/buildings.xml`, `ships.xml`, `animals.xml`, `items.xml` **[known]** (data)

- `<Buildings lodBias="-70.0" lodScale="1.2" colorMap="[data]\buildings\colors.tga" numVariations="8">`;
  `<Building name="Bavarian_Donkeybreeding" mesh=… frame=…>` with `<DoorOpen file=…\door_open.KEX/>`,
  `<DoorClose …/>`, `<Working file=…\dummy_working.KEX><Sound start="10" name="ox"/></Working>`,
  `<Production mesh=…\FarmOx.KEX model=…\FarmOx_model.KEX texture=…\Ox.dds scale="0.010" numAnims="1"
  anim0=…\FarmOx_idle.KEX numModels="5" boneLink0="ox1" …/>`. 112 `<Building>` elements, 3 with `<Production>`
  (all use `boneLink`, none `location`). Other child elements present in the data: `<PFX name link>`,
  `<Sacrifice name>`, and `<Particle start duration name slot>` events (§3.12).
- `<Ship tribe="Bavarian" scale="1.0" frame=… mesh=…\PV_B_Ship01.KEX model=…Model.KEX idle=…Idle.KEX
  move=…Rudder.KEX sink=…Sink.KEX/>`; three `<Ship>` elements (`Bavarian`, `Egyptian`, `Scots`) and the status
  meshes `<Freight mesh>`, `<Expedition mesh>`, `<Soldiers mesh>`.
- `<Deer model=…\deer_model.KEX mesh=…\deer.KEX scale="1.5">`, `<Bear … scale="0.013">` with
  `Stand1 / Stand2 / Walk / Dying`.
- `<ItemDefinitions><Item name="Wood" mesh="[data]\items\GO_Log01.KEX"/>…` (54 items), `<AnimatedItems>` (its
  only entry, the fishing rod with `references`, `mesh`, `model`, `animation`, is commented out), `<DonkeyItems>`
  (`<Item references="Wood" mesh=…\dummy_item.KEX/>`), `<StackLayouts>`.

### 6.5 `settings/graphics.xml` **[known]** (S 0067edd0, data)

`<Settings><Animations globalSpeed="1.8"/>`: `g_AnimTimeScale` (S 00884a6c, 1.0 without the element). Every
slot's control speed is `globalSpeed * slotSpeed` (§3.7), so all skeletal animations of this subsystem play at
1.8 times the speed stored in their files: `settler_walk.KEX` (length 1.0) takes 1 / 1.8 s of pool time per
cycle. Event `start` / `duration` values are compared against `(time - startTime) * globalSpeed`
(`EventBase::Tick` S 006b00f0), i.e. they are positions on the file's own time axis.

### 6.6 Constants in code **[known]**

| Value | Use | Evidence |
|---|---|---|
| target axes `(0,0,-1) (0,1,0) (1,0,0)`, origin 0, unit scale 1.0 | engine coordinate system | S 0087c550 (data bytes) |
| `1e-5` | "is neutral" threshold for bind keys | S 0072f720 |
| `0.01` | slerp → linear switch on `1 - dot` | S 0072e250 |
| more than 10.0 s on the pool timer and more than 5 entries | pool garbage collection | S 006ad380 |
| 0.35 / 0.4 times the tick interval, per call | sink step of dead settlers (per frame update) / animals (per logic tick), §4 | S 006c7640, S 006ce2c0 |
| 0.6 (on the time record's first float) | door-open phase of a work cycle | S 006aa640 |
| `MAX_BONES = 50` | bone matrices per draw (`g_InstanceMatrix[MAX_BONES]`) | `gfx/fx_20/shared.inc` |
| `Wrap` | default sampler address mode of every stage (`ADDRESS_MODE_U0..` / `V0..`) | `gfx/fx_20/shared.inc` |
| 0.5 | rounding of idle-variation weights (§3.11) | S 006de030 |
| 1024 x 1024 | settler palette atlas | S 00695130 |
| `0x5432ace0` | seed of the static cosmetic generators | S 00695490, S 006ce2c0 |

---

## 7. Save and load

Nothing of this subsystem is written to a save game. The settler's action timer is saved by the simulation
(`NSettlers::Animation::Store` S 0065f0c0: remaining, total, kind; `settlers-jobs.md` §7), and after a load the
render objects are created again from the logic objects (`Scene::OnSettlerCreated` S 0067f0f0 →
`CCharacterMgr::CreateCharacter`). **[known]** / that nothing here is saved (no `Store` / `Load` function was
found in the render classes of §1) and that every render object is rebuilt this way **[inferred]**

Consequences **[inferred]**: animation phase, the pool, idle-variation timers, sink offsets and the random settler
palettes are not preserved; a settler's hair and clothing shades are drawn anew after a load (the palette generator
is a process-wide static that is seeded once, so the shades depend on creation order since program start).

---

## 8. Determinism notes

The subsystem is presentation only:

- **No simulation timing depends on an animation length.** The length of a `KAnimation` is read only through
  `AnimResMgr::GetAnimationDuration` S 004de100 (callers: `RandomAnimPlayer::Update`,
  `LobbyEmotePlayer::LoadDefinitions`), `CAnimatedObject::GetAnimLength` S 0076ae10 (caller: the lobby's
  `AnimModel::Update`) and `GetAnimRemainingTime` S 0076ad40 (callers: the lobby's `AnimModel::Update`,
  `CharacterAnimation::UpdateLogic`, `S2CG::Animal::UpdateLogic` and
  `CharacterAnimation::GetCurrentAnimRemainingTime` S 006c6370, itself called by `CCharacter::IsInFrustum`, a
  debug draw, `CharacterSettler::Update` and `CharacterWorker::UpdateWorkplaceWork`). All callers are render
  classes. **[known]** (caller lists of the mapping cache) The two slot getters reach the length through a
  virtual of the control (`+0x24`); that no simulation class calls that virtual directly is **[inferred]**
  (indirect calls have no caller list).
- The direction of dependence is the opposite: the simulation's timers come from properties and configuration
  (`productionTime`, pick-up and drop times, `cfg_setSettlerDyingTime`, …; `settlers-jobs.md` §2.5, §3.5, §6)
  and the renderer shows an animation for as long as the timer kind lasts. An animation shorter than the timer
  holds its last key; a longer one is cut when the kind changes. Only for soldiers is the playback speed adapted
  (settler virtuals `+0x30/+0x34`), and the building's work animation is given `workDuration` and a speed factor
  by the worker's render logic (§3.10). **[known]**
- Where an animation's end *is* awaited, the waiting state is render state: the death sink of settlers and
  animals (§3.10, §3.18), the return from an idle variation (§3.11), `Building::TriggerWorkCycle` (§3.10).
  **[known]**
- Random numbers: idle variations use the generator at S 0088e120; palettes (S 0088d7c8) and animal idle choice
  (S 0088decc) use function-local static generators seeded `0x5432ace0` on first use. None is the simulation generator at S 00889b08
  (`logic-core.md` §2.2). **[known]**
- The render hooks (`CCharacter::UpdateLogic`, `Animal::UpdateLogic` per tick; the per-type logic per frame) call
  only getters on logic objects in the code read here. **[inferred]** The four named logic functions were read
  and write nothing **[known]**: `Worker::IsAwayFromWorkplace` S 0065cd70 (in a work cycle and moving, or not on
  the workplace's entrance cell), `ShouldSpeedUpWorkAnim` S 0065cdc0 (in a work cycle, at the workplace and
  `Production::GetProductionDuration() < productionTime`), `GetWorkAnimSpeedFactor` S 0065ce30
  (`productionTime / GetProductionDuration()`), and `Carrier::GetStreetCached` S 0065a6c0, which only returns
  the pointer already stored in the carrier's street reference when the reference id is valid, else null.

A remake may therefore implement this subsystem with engine facilities and float timing freely, as long as it
never feeds anything back into the simulation.

---

## 9. Notes for a Godot reimplementation

**Converter output.** glTF 2.0 (`.glb`) per model is the natural target; Godot imports it natively.

1. *Read* the KEX as in `asset-formats.md` §2.
2. *Bake* exactly as the loader does (§3.1 step 4) before anything else: strip near-neutral bind components
   (`1e-5`), flatten bone scale matrices into child positions, divide animation positions by the scale key and
   drop the scale channel. Skipping this changes poses.
3. *Coordinates.* The file is right-handed, Z up (`axisX (1,0,0)`, `axisY (0,0,1)`, `axisZ (0,1,0)` in every
   file). glTF is right-handed, Y up: map a file point `(x, y, z)` to `(x, z, -y)` — a proper rotation, so the
   triangle order of the file is kept as it is and quaternions transform by the same rotation
   (`q' = (qx, qz, -qy, qw)`). **[inferred]** Do *not* copy the engine's left-handed result `(-y, z, x)` plus
   winding swaps; that is the D3D form of the same thing. Front faces: the engine ends up drawing the file's
   index order in a mirrored (left-handed) space with D3D's default clockwise-front culling **[inferred]**
   (`skin_color_mesh.fx`, `house_shader.fx` and `ships.fx` set no `Cullmode` **[known]**; a render state set from
   code was not searched), which
   corresponds to counter-clockwise front faces in the right-handed file, the glTF convention. Verify on one
   model (§10).
4. *Units.* Divide positions by the file's `unitScale` (1, 39.37008 or 100) and multiply by the object's XML
   scale (§3.1 table) — or keep the XML scale as a node scale in the scene. After the division a settler is
   about 1.8 units tall (`bavarian_carrier_mesh.KEX`: z from -0.01 to 1.80) and is drawn at scale 1.2; one map
   cell is 6.0 world units wide (`map-resources.md` §2). **[known]** (data)
5. *Vertex streams* (§2.4): 0 → `POSITION`, 1 → `NORMAL` (normalise), 2 → `TANGENT`, 3 → `COLOR_0` (stored as a
   D3DCOLOR dword: bytes B, G, R, A **[inferred]**), 4..7 → `TEXCOORD_0..3`, 12 → `WEIGHTS_0` (renormalise to sum
   1), 13 → `JOINTS_0` after remapping each byte through the mesh's `boneNames` to the skeleton's bone index.
   Texture coordinates are copied unchanged by the engine. In the data the first set has `v` within `[-1, 0]`
   in about 3,800 meshes, within `[0, 1]` in 1,251 and outside both in about 275 (the split of the borderline
   cases depends on the tolerance) **[known]**, and the shaders' samplers default to `Wrap` (`shared.inc`,
   §6.6) **[known]**: keep the values and use repeat addressing (glTF and D3D share the top-left origin).
   **[inferred]** Stream sizes in the data: 12 bytes per vertex for types 0, 1, 2; 4 for type 3; 8 for types
   4..7; 16 for type 12; 4 for type 13; type 2 occurs in one mesh, types 12 and 13 in 524 of 5,332. **[known]**
6. *Primitives.* One glTF primitive per material with `triangleCount > 0`: indices
   `[startIndex, startIndex + 3 * triangleCount)`. For files the engine merges (`mergeAllMeshes`), each KEX mesh
   is one subset; settler files use only their first mesh (§3.2).
7. *Skin.* Joints in file order (parents precede children; one root). `inverseBindMatrices` = the file's per-bone
   4x4, converted from row-vector to glTF's column-vector layout (transpose) and to the target axes. Node
   local transforms = the baked bind keys. Do not recompute the inverse bind from the bind keys: in eight files,
   the settler skeleton among them, the two differ (§2.6), and the engine uses the file matrix.
8. *Animations.* One glTF animation per `KAnimation`; channel per track and component present. Key `i` at time
   `i * length / keyCount`. For a looping clip add a closing key at `t = length` equal to key 0 (the engine
   blends the last key back to the first); for a play-once clip the engine holds the last key from
   `(keyCount - 1) * length / keyCount` on, so end the clip there or repeat the last key at `length`
   (`KAnimation::ComputeKeyInterp` S 0072d650). Linear interpolation for positions, spherical for rotations.
   Pair animation-only files with a skeleton by bone name; the animation's `name` equals the skeleton's `name`
   (e.g. `Bip01`). Play every clip at `globalSpeed` (1.8, §6.5) times the per-slot speed, on a clock that
   advances with the simulation's frame delta (§4); idle-variation delays and work durations are in simulation
   seconds and are not scaled by `globalSpeed`. **[known]** Two files hold three animations each
   (`ships/PV_V_Ship01Idle.KEX`, `ships/PV_V_Ship01Rudder.KEX`: `root` with 19 tracks, `PV_V_Ship01` with none,
   `Shape01` with one); their skeleton file `PV_V_Ship01Model.KEX` is named `root`, so the rule of §3.7 picks
   the first. No `<Ship>` of the install's `ships.xml` references them. **[known]** (data)
9. *Materials.* Texture references are absolute paths of the developers' machine
   (`E:\_FUNATICS\…\GO_Warez02.dds`, also `Z:\…`; 7,018 of 8,529 references carry a drive letter); the engine
   keeps only the file name (§3.2). Extensions in the files: `.dds`,
   `.bmp`, `.tga`, `.psd` — resolve by base name against the install's textures (how the engine maps a `.psd` /
   `.bmp` name to an existing file is **[TODO]**). Usages: `DiffuseColor` → base colour, `Opacity` → alpha,
   `Self-Illumination` → emission, `SpecularColor` / `SpecularLevel` / `Glossiness` → specular workflow or
   dropped, `Bump` → normal, `Reflection` → dropped. For settlers the XML `color` texture replaces the material
   textures and needs the custom shader below.

**Runtime mapping.**

| Original | Godot |
|---|---|
| `KSkeleton` + `KModel` | `Skeleton3D` |
| `KAnimationControl`, slots | `AnimationPlayer` (an `AnimationTree` is not needed: no blending is used, §3.5) |
| animation type → clip (§3.9) | a lookup table built from `settler_animations.xml` with the four-level fallback |
| shared pose pool (§3.8) | optional optimisation: one skeleton per (model, clip) shared by many `MeshInstance3D`, or GPU instancing with baked animation textures; plain per-settler skeletons are behaviourally equal except that settlers would no longer move in phase |
| attachments | `BoneAttachment3D` on `SLOT_HandR` / `SLOT_Goods` / the `boneLink` names |
| animation events | call-method or audio tracks generated from the `<Sound start name>` children |
| settler colouring | a small shader: index texture (R row, G luminance, B specular, A mask) + palette texture + player colour uniform (§3.15) |
| ship colouring | shader mixing `albedo * player_color * 1.8` by the albedo alpha |
| building tint | per-instance uniform selecting a column of `colors.tga` |
| LOD (`mesh`..`mesh3`, ranges 30 / 40 / 60) | `GeometryInstance3D` visibility ranges or manual switching |

**Must be reproduced exactly**: nothing numerically — but the *rules* of §3.9 (which clip for which state and
keys, loop versus play-once-and-hold) and the timing contract of §8 (the simulation timer decides, the clip
follows) define what the player sees. **Free to change**: blending quality (adding cross-fades), pooling, LOD,
palettes' random source.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Do the settler meshes look right with the constant quarter turn of §2.6 applied (i.e. is the turn compensated by the mesh data or by the render movement's heading)? | One converted settler viewed with a walk animation next to a screenshot. |
| 2 | Front-face winding as the engine draws it: the `STATES_*` macros of `shared.inc` and the three object shaders set no cull mode, and samplers default to `Wrap` (§9); a `D3DRS_CULLMODE` write from code is not excluded. | Static: search the device wrapper for the cull render state; or one converted model viewed next to a screenshot. |
| 3 | The tribe number tested against the `tribes` mask (`1 << (key & 31)`). | Static read of the properties tribe map (`StaticAccess +0x9c`) loader: the first dword of a tribe record. |
| 4 | Which code sets the render logic's byte `+0x2a` (copied to the character each tick and, as the animation's track flag, to `currentTrack +0x50`; §3.9 treats it as "visible"). | Static read of the writers of that byte in `S2CG::Character*`. |
| 5 | Which caller enters `Scene::Update` with a non-zero flag (wall-clock time record, §4), and how often `Building::Update` runs. | Static: the callers of scene vtable slot 8 (S 007f8f2c) and of the building subclasses' virtual update. |
| 6 | Timer kind 7 → `Hit`: none of the 15 callers of `NSettlers::Animation::Start` S 0065f080 passes 7 (they pass 2, 3, 4, 5 or 6; `Soldier::Update` S 006594a0 passes 5) **[known]**, so `Hit` looks unreachable **[inferred]**. Is the kind field (`settler +0x1c`) written anywhere else than `Start`, `Tick` and the loader? | Static: write references to the field. |
| 7 | `SoundEvent::Start` / `Update`: when a sound event ends and whether `duration` cuts it (§3.12). | Static read of S 006b0550, S 006b01f0. |
| 8 | Where an event's `slot` name is resolved to a bone and what an event without `slot` is attached to. | Static read of the three event constructors (S 006b0350, S 006b0400, S 006b0880) and `EventBase::GetWorldTransform` S 006b0480. |
| 9 | The vertex declarations per object class (settlers S 00881670, buildings, items) and so the exact `.mshraw` vertex layouts. | Read the declaration tables (data bytes) and `VertexLayout::Init`. |
| 10 | Construction-site display: how the `frame` mesh and the construction progress (`Building::Update` S 006abcf0 stores `1 - remaining` with its time) are drawn. | Static read of `GetConstructionClipPlane` and the building renderer. |
| 11 | The values written to the ship shader's `PLAYER_COLOR_WEIGHT`. | Static: the user of the parameter handle resolved in `ShipMgr::ctor` S 006985e0. |
| 12 | Do the `<PFX name link>` and `<Sacrifice name>` children of `<Building>` (§6.4) belong to this subsystem's loader or to another one? | Static: string references to `PFX` and `Sacrifice`. |
| 13 | How a `.psd` / `.bmp` texture name in a material resolves to a shipped file. | Static read of the mesh managers' `AcquireTexture` / `GetOrLoadTexture`. |
| 14 | `<Production scale>` reaches `AnimResMgr::LoadAnimation` as a float **[inferred]**: the third parameter is a float pushed raw by other callers (disassembly of S 006de030), the same function passes the bit pattern of 1.0 for the door animations, and S 006d3880 calls no float-to-int helper. | Confirm with the disassembly of the call in S 006d3880. |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 0072a7b0 | `KScene_LoadFile` | allocate, read and convert a KEX file |
| S 0072b820 | `KSceneInternal::KFile::Load` | file header and the three lists |
| S 0072a9a0 | `KFile::ApplyImportTransform` | file → engine coordinate system and scale |
| S 0072c880 | `KMesh::Load` | mesh record |
| S 0072c550 | `KMesh::TransformVertices` | import transform of streams, winding swap |
| S 007303a0 | `KMaterialDesc::Load` | material: start index, triangle count, textures |
| S 0072d290 | `KSkeleton::Load` | bones, bind keys, inverse bind matrices |
| S 0072ce50 | `KSkeleton::FlattenBoneOrientations` | remove bone scale matrices |
| S 0072f720 | `KBoneKey_StripIdentityComponents` | clear neutral components (1e-5) |
| S 0072dcf0 | `KAnimation::Load` | tracks, scale baking, `invLength` |
| S 0072d810 | `KAnimation::TransformKeys` | import transform of keys, quaternion continuity |
| S 0072d650 | `KAnimation::ComputeKeyInterp` | time → key pair and fraction |
| S 0072d6e0 | `KAnimation::SampleTrack` | lerp / slerp of one track |
| S 0072e250 | `Quat_Slerp` | rotation interpolation |
| S 0072bbd0 | `KModel::PlayAnimation` | create a control |
| S 00730070 | `KAnimationControl::ctor` | bind tracks to bones |
| S 007301e0 | `KAnimationControl::Advance` | time, fade, loop limit |
| S 0072ff30 | `KAnimationControl::SamplePose` | sample or hold |
| S 0072c1d0 | `KModel::Update` | advance controls, blend bones |
| S 0072bca0 | `KModel::BlendBoneFromAnimations` | weighted sum per bone |
| S 0072c340 | `KModel::UpdateBoneMatrices` | world matrices down the hierarchy |
| S 0072bf20 | `KModel::ComputeBoneMatrix` | world and skin matrix of one bone |
| S 0072fd00 | `KDeformableMesh::ctor` | mesh bone names → skeleton indices |
| S 004ef660 | `SharedResourceCache::Acquire` | shared KEX cache keyed by path and coordinate system |
| S 0076e0d0 | `S2CE::CMesh::Load` | KEX or `.mshraw` → render mesh |
| S 0076c030 | `CMesh::FillVertices` | stream types → vertex declaration |
| S 0076de30 / S 0076d3d0 | `CMesh::LoadSingleFromKFile` / `LoadMergedFromKFile` | one mesh / all meshes |
| S 0076d010 | `Mesh_AppendSubsetsFromKMesh` | materials → subsets |
| S 0076c9f0 / S 0076cbe0 | `CMesh::GetPackedCachePath` / `IsPackedCacheUpToDate` | `.mshraw` name and validity |
| S 0076bdc0 / S 0076d990 | `CMesh::SavePackedBinary` / `LoadPackedBinary` | `.mshraw` layout |
| S 0076b4a0 | `S2CE::CAnimatedObject::Load` | skeleton file → `KModel` |
| S 0076b230 | `CAnimatedObject::AddAnimation` | pick the variant, start, allocate a slot |
| S 0076ac90 | `CAnimatedObject::Update` | per-frame pose update and callbacks |
| S 0076a890 | `CAnimatedObject::SetWorldTransform` | bone matrices with a root matrix |
| S 0076ad40 | `CAnimatedObject::GetAnimRemainingTime` | time left of a slot |
| S 004de400 | `ai::render::AnimResMgr::LoadAnimation` | animation file → id |
| S 006d8670 | `S2CG::AnimatedVisual::PlayAnimationWithEffects` | start an animation and its events |
| S 006cc350 | `ai::anim::AnimationSet::ctor` | load animations, build default and override tables |
| S 006caea0 | `AnimationSet::LoadAnimationsXml` | `<Animation name filename tribes>` |
| S 006ca8d0 | `AnimationSet::GetAnimIdForSlot` | type + keys → animation id |
| S 006ca790 | `AnimationSet::FindAnimIdByName` | name (+ tribe mask) → id |
| S 006ddfa0 | `ai::anim::RandomAnimPlayer::Update` | idle variation timer |
| S 006ad4f0 / S 006ad2e0 / S 006ad380 | `S2CG::CModelCache::Acquire` / `Release` / `Update` | shared pose pool |
| S 00695130 | `S2CG::CCharacterMgr::LoadFromXml` | character definitions and tunables |
| S 00692390 | `CCharacterMgr::LoadAnimationSet` | settler animation set and pools |
| S 00695490 | `CCharacterMgr::CreateCharacter` | definition lookup, palette, character |
| S 006909f0 | `S2CG::CCharacter::UpdateLogic` | per tick: choose the animation type |
| S 00690bd0 | `CCharacter::Update` | per frame: apply it, transform |
| S 006910e0 | `CCharacter::SetShaderConstants` | palette offset, colour scale, player colour |
| S 006c64c0 / S 006c63a0 / S 006c6590 | `S2CG::CharacterAnimation::SetAnimationType` / `PlayAnimation` / `UpdateLogic` | request, switch, timer kind mapping |
| S 006c7640 | `S2CG::CharacterSettler::Update` | facing, door trigger, death sink |
| S 006c88c0 | `S2CG::CharacterWorker::UpdateWorkplaceWork` | building work animation, work cycle |
| S 006c7760 / S 006c7850 | `CharacterSettler::UpdateAttachedItem` / `InitAttachedItem` | tool on the link bone |
| S 006c8ee0 | `S2CG::CharacterCarrier::UpdateAttachedItem` | boat and cargo placement |
| S 006d09b0 | `S2CG::Item::UpdateCarrierAttachment` | which settler or ship holds a good |
| S 006c9d20 / S 006c9770 | `ai::gfx::ColorMapTable::LoadFromXml` / `BuildRandomPalette` | colour ramps and settler palettes |
| S 006d3880 | `S2CG::BuildingDesc::LoadFromXml` | building meshes, animations, production animals |
| S 006aa640 / S 006aa3b0 / S 006aa6f0 | `S2CG::Building::TriggerWorkCycle` / `PlayStateAnimation` / `PlayOneShotAnimation` | building animations |
| S 006a54c0 / S 006a5cc0 | `S2CG::Ship::Update` / `UpdateVisuals` | ship animation state, bobbing |
| S 006ce2c0 | `S2CG::Animal::UpdateLogic` | animal animation choice and death sink |
| S 0076e8a0 | `ai::render::SkinnedMeshRenderer::RenderInstances` | CPU or GPU skinning of instances |
| S 00680550 / S 006805e0 | `S2CG::Scene::SyncLogicTick` / `Update` | per-tick and per-frame order |
| S 006824c0 | `S2CG::Scene::Init` | load order of the XML files |
| S 0067edd0 | `S2CG::Scene::LoadSettingsFromXml` | `<Animations globalSpeed>` |
| S 0067f6b0 | `S2CG::Scene::UpdateDetailFlagsAndTime` | per-frame refresh of the time record |
| S 006929e0 / S 00692a30 | `S2CG::CCharacterMgr::UpdateLogicAll` / `Update` | per-tick and per-frame loop over the characters, pools |
| S 00694c00 / S 00693880 | `CCharacterMgr::LoadCharacterDefs` / `LoadDonkeyModel` | `<Character>` and `<Donkey>` attributes |
| S 0069aeb0 | `S2CG::AnimalMgr::Update` | animal pools, transforms, visibility |
| S 006de030 | `ai::anim::RandomAnimDesc::LoadXml` | idle-variation group and weights |
| S 006867d0 | `ai::gfx::EffectScriptMgr::LoadAnimEvents` | `Sound` / `Particle` / `Item` event creators per animation id |
| S 00685b30 | `S2CG::EventBase::Desc::LoadBaseXml` | event attributes `slot`, `start`, `duration` |
| S 006b00f0 | `S2CG::EventBase::Tick` | start an event once, then update it |
| S 0065cd70 / S 0065cdc0 / S 0065ce30 | `NSettlers::Worker::IsAwayFromWorkplace` / `ShouldSpeedUpWorkAnim` / `GetWorkAnimSpeedFactor` | read-only getters used by the worker's render logic |
| S 0065a6c0 | `NSettlers::Carrier::GetStreetCached` | read-only getter of the carrier's street pointer |
| S 0065f080 / S 0065f040 | `NSettlers::Animation::Start` / `Tick` | the simulation's action timer (see `settlers-jobs.md`) |
