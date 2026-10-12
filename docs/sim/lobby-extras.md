# Lobby extras: physics and collision, web textures, lobby data files

Tags: **[known]** = read directly at an address (S 00xxxxxx = `sadk_noav.exe`) or in a named data file and
key; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open. Nothing here was observed
in the running game unless a dated live observation of another document is cited.

PhysX method names (`simulate`, `setGroup`, `raycastClosestShape`, ..) are **[inferred]** throughout: the SDK
lives in `PhysXLoader.dll` / `NxCharacter.dll`, the client only calls vtable slots. The slot offsets and the
arguments are **[known]**; the names follow the PhysX 2.7 header order and fit every call seen.

Related specifications, not repeated here: the lobby world, its objects, zones, doors, camera and the input
step ([`lobby-world-client.md`](lobby-world-client.md)); the lobby dialogs
([`lobby-screens.md`](lobby-screens.md)); the file inventory ([`formats-inventory.md`](formats-inventory.md));
the `.KEX` scene format ([`../asset-formats.md`](../asset-formats.md)); the replacement of the advertising
screens ([`../BINARY_PATCHES.md`](../BINARY_PATCHES.md), "Billboards").

## 1. Purpose and scope

Three small subsystems that only the 3D lobby village uses:

- **Physics** (`ai::lobby::LobbyPhysics`, `Lobby::CPhysicObj`, `Lobby::CPhysicObjCharacter`, the linked
  NxuStream utility `ai::physics::*` / `NXU::*`): one PhysX 2.7 scene that holds static triangle meshes of the
  village and one capsule character controller for the player's own avatar. It answers three questions: where
  may the own avatar move, how far may the camera be from the avatar, and how far along the cursor ray may an
  object be picked.
- **Web textures** (`url2tex::CURL2Tex`, `url2tex::CSDKIEWindow`): an embedded Internet Explorer control per
  texture renders a web page into a Direct3D texture. Used by the three advertising screens of the village and
  by the Hall of Fame dialog.
- **Lobby data files** this document adds to the inventory: `data\lobby\physic\*.xml`, the three loose images
  of `data\lobby\heightmap`, `data\lobby\web\*`, and the `.phx` cache the client writes.

None of this exists in a match (§8).

## 2. Data model

### 2.1 `ai::lobby::LobbyPhysics` (0x18) [known] S 00500290, S 00500410

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `allocator` | `MinimumUserAllocator` (4 bytes, vtable only) handed to the SDK |
| +0x04 | `sdk` | `NxPhysicsSDK*` from `NxCreatePhysicsSDK(0x2070000, allocator, 0, desc, 0)` |
| +0x08 | `scene` | `NxScene*`, the only scene |
| +0x0c | `controllerManager` | `NxControllerManager*` from `NxCreateControllerManager(allocator)` |
| +0x10 | `stepTimeMs` (u64) | copy of `CLobby.stepMs` = **83** [known] S 004fb100 (`0x53`) |

One instance, created by `CLobby::StartUp` S 004f8c90 and reachable as `LobbyContext + 0x70` (`pPhysics`) by
every lobby object.

### 2.2 `Lobby::CPhysicObj` (0x10) and `Lobby::CPhysicObjCharacter` (0x2c)

| Offset | Field | Meaning | Tag |
|---|---|---|---|
| +0x00 | vtable | `IPhysicObj` interface, 10 slots (below) | [known] S 007e75d8, S 007e7718 |
| +0x04 | `NXU_userNotify` face | second vtable; its `NXU_notifyActor` stores the actor an NxuStream file created | [known] S 00520ae0 |
| +0x08 | `actor` | `NxActor*`; for the character the controller's kinematic actor | [known] S 005235e3 |
| +0x0c | `world` | the `LobbyContext` | [known] S 00522c80 |
| +0x10 | `controller` | `NxController*` (character only) | [known] S 005235d2 |
| +0x14 | `orientation[4]` | quaternion x, y, z, w last set; starts as identity | [known] S 005234c0, S 005236c0 |
| +0x24 | `radius` (f32) | **0.5** | [known] S 00523555 |
| +0x28 | `height` (f32) | **1.0** | [known] S 0052355e |

`IPhysicObj` vtable [known: slot addresses read at S 007e75d8 (static) and S 007e7718 (character)]:

| Slot | Static object | Character | Role |
|---|---|---|---|
| 0 | `GetPose` S 00520a80 | `GetTransform` S 00523610 | writes position (3 floats) + quaternion (4 floats) |
| 1 | `DebugDraw` S 00522270 | same | wireframe of every shape of `actor` |
| 2 | S 005210c0 | same | `actor` slot 0x118 with (vec3, 0, 1): [inferred] add a force; no caller found |
| 3 | no-op (S 00472360) | `Move(displacement, activeGroups)` S 00523670 | controller move |
| 4 | no-op (S 0064b9c0) | `SetOrientation(quat)` S 005236c0 | stores the quaternion only |
| 5 | S 00520b30 | same | `SetRaycastEnabled(bool)`: shape slot 0x14 with (0x40, `!enable`) on every shape |
| 6 | `SetPose(pos + quat)` S 00521100 | `SetPosition(pos)` S 00523430 | actor slot 0x14 / controller slot 8 |
| 7, 8 | return 0 / return 0 (S 0072db80) | return 0 / returns `this` (S 00519aa0) | no caller found [inferred] |
| 9 | deleting destructor S 00520eb0 | deleting destructor S 00523410 | static: `scene` slot 0x1c with the actor ([inferred] `releaseActor`); character: releases the controller (§3.3), then the same base step |

Owners:

| Owner | Field | Object | Tag |
|---|---|---|---|
| `CStaticController` +0x40 | `physStatic` | static mesh, group argument = zone | [known] S 005198c0 |
| `CStaticController` +0x44 | `physMove` | static mesh, group argument = zone + 16 | [known] S 005198c0 |
| `CLocalController` +0x24 | `charPhysics` | the one `CPhysicObjCharacter` | [known] S 0051a1a0 |
| `CLocalController` +0x30 | `collisionMask` | `0x10001 << zone`; set in the constructor and again at the start of every step | [known] S 0051a1a0, S 0051ace0 |

No other class creates a physics object: remote avatars, NPCs, pets and the minigame controllers have no
collision. [inferred: `CPhysicObj::ctor` S 00522c80 has one caller (`CStaticController::ctor`), its
argument-less form S 005209d0 has one caller (`CPhysicObjCharacter::ctor`), and `CPhysicObjCharacter::ctor`
S 005234c0 has one caller (`CLocalController::ctor`)]

### 2.3 Collision groups [known] S 005198c0, S 00522a2c, S 0051a1a0, S 0051ace0, S 0051a450, S 004f6373

A PhysX shape has one group number 0..31; a query passes a bit mask of groups. `zone` is the object's primary
zone 0..15 (`CLobbyObj + 0x28`).

| Group | Shapes | Hit by |
|---|---|---|
| `zone` (0..15) | of an object in that zone: the mesh named by `collision_mesh`, or the object's render mesh when the attribute is absent (§3.2) | own avatar, camera rays, pick ray |
| `zone + 16` (16..31) | mesh named by `collision_mesh_move` | own avatar only |
| 31 | the character controller's own shapes (set after creation) | nothing in zones 0..14 (bit 31 = zone 15 + 16) |

Masks: avatar movement `0x10001 << zone` (both groups of the avatar's zone, recomputed from the avatar
object's zone at the start of every step); camera rays the low 16 bits of that mask (`1 << zone`); pick ray
`1 << currentZone` (`CLobby + 0x54`).

The group is written into `NxShapeDesc.group` from the second constructor argument (`MOV CX,[ESP+0x280]` →
`MOV [desc+0x3c],CX`). [known] S 00522a2c, S 00522a43

### 2.4 `url2tex` objects

`url2tex::CURL2Tex` (0x18), singleton `g_pURL2Tex` S 0088b824 [known] S 005c76b0, S 005c81d0:

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | vtable S 007eb874 | 0 `RequestURL(d3dTexture, url)`, 1 `GetContentSize(d3dTexture, &x, &y)`, 2 `UpdateTexture(d3dTexture, scrollLeft, scrollTop)`, 3 `SetEntryDisabled(d3dTexture)`, 4 destructor |
| +0x04 | `entries` | `std::map<IDirect3DTexture9*, CURL2TexEntry*>` |
| +0x10 | `hParentWnd` | the game window |
| +0x14 | `hInstance` | module instance |

`url2tex::CURL2TexEntry` (0x3c), one per texture [known] S 005c8050:

| Offset | Field | Meaning |
|---|---|---|
| +0x00 | `window` | `CSDKIEWindow*` |
| +0x04 | `texture` | `IDirect3DTexture9*` (not add-ref'd) |
| +0x08 / +0x0c | `width` / `height` | from the texture's level-0 description |
| +0x10 / +0x14 | `maxScrollX` / `maxScrollY` | scroll range of the page, **−1** until the first render |
| +0x18 | `url` | `std::string`, last requested URL |
| +0x34 | `owner` | the `CURL2Tex` |
| +0x38 | `disabled` (bool) | set when the texture object is destroyed; a new request clears it |

`url2tex::CSDKIEWindow` (0x38), the host of one browser control [known] S 005c8300, S 005c85c0: +0x04
`CSDKIEEvents` (event sink), +0x08 `CSDKIEClientSite`, +0x0c `CSDKIEInPlaceSite`, +0x10 `IWebBrowser2`, +0x14
connection point, +0x18 connection point container, +0x1c `IOleInPlaceObject`, +0x20 `IOleObject`, +0x24
parent window, +0x28 host window, +0x2c `IOleInPlaceActiveObject`, +0x30 reference count (starts 1), +0x34
back pointer to the entry.

`S2CE::CTexture` members used by web textures [known] S 004e7880, S 004e7c20: +0x18 `d3dTexture`, +0x58 /
+0x5c width / height, +0x60 format code, +0x65 `bRegisteredURL`. Vtable S 007e4570: slot 5
`GetURLContentSize(&x, &y)` S 004e7410, slot 6 `UpdateFromURL(scrollLeft, scrollTop)` S 004e7440, slot 7
`RegisterURL(url)` S 004e77d0 (navigate an existing web texture), slot 8 `CreateFromURL(width, height, url, 0)`
S 004e7880, slot 9 `CreateFromFileWithURL(path, url, 0)` S 004e7820 (no caller found [inferred]).

## 3. Rules and algorithms

### 3.1 The physics world [known] S 00500410

1. `NxCreatePhysicsSDK(0x2070000, allocator, 0, sdkDesc, 0)` (SDK version 2.7.0). Failure: message box
   "NxCreatePhysicsSDK failed / Please install PhysX drivers", `_exit(1)`.
2. `NxCreateControllerManager(allocator)`. Failure: message box "NxCreateControllerManager failed / Please
   install PhysX drivers", `_exit(2)`.
3. One scene, from SDK slot 0x10 ([inferred] `createScene`). Description: gravity **(0, −9.8, 0)**
   (`0xc11ccccd` in the second float); `maxTimestep` 1/60 (`0x3c888889`); `maxIter` 8; time step method 0
   (fixed); flags 0x44; no user notify, contact report or trigger report (all null). Which description field
   each of these constants lands in is [inferred] from the PhysX 2.7 `NxSceneDesc` layout, as is that
   everything but the gravity equals the SDK defaults.
4. Scene slot 0xe4 `setTiming(stepTimeMs in seconds × 0.25 = 0.083 × 0.25 = 0.02075 s, 4 sub-steps, method 0)`.
5. Default material, from scene slot 0xdc with index 0: material slots 0x24, 0x1c and 0x14 are each called
   with **0.5** (`0x3f000000`); [inferred] restitution, static friction and dynamic friction.

The scene contains only static actors and the kinematic actor of the one character controller (§3.2, §3.3).
No dynamic body is ever created, so gravity, the material and the simulation step change nothing that the
player can see. [inferred: both actor descriptions have a null body; no other creator exists]

Shutdown `LobbyPhysics_Shutdown` S 005002e0 [known]: if a scene exists, scene slot 0x1d4 (1, 1, 0), controller
manager slot 0x14 and `sdk->releaseScene(scene)` (SDK slot 0x14); then, each if non-null,
`NxReleaseControllerManager`, SDK slot 4 (release) and the allocator's deleting destructor (slot 0x1c).

### 3.2 Static collision meshes

A lobby object gets a `CStaticController` when its `controllerclass` is none of `customize`, `character` and
`none` [known] S 00502e60. Only when the class's `controllerclass` is exactly `std` does the constructor ask
the graphics object for two mesh ids (graphics object slot 11 with index 0, then 1); each id other than −1
becomes one `CPhysicObj` with group argument `zone`, respectively `zone + 16`. [known] S 005198c0

Slot 11 returns −1 for every graphics class except `CGfxObjStd` (`gfxclass="std"`): the avatar, sky dome and
pawn chess board vtables hold the shared stub S 007809c0 there [known: vtable entries S 007e6358, S 007e6990,
S 007e6e60]. `CGfxObjStd::GetCollisionMeshId(index)` S 005191b0 returns the two ids its constructor
S 005191c0 sets [known, disassembly S 005195bf..S 0051963f]:

| Id | `gfxparm` attribute | Rule |
|---|---|---|
| 0 (+0xc4) | `collision_mesh` | absent → **the id of the render mesh** (the `mesh` attribute's mesh, +0xc0); the literal `none` (case-sensitive) → −1; any other value → the mesh of that name in the class's `file` |
| 1 (+0xc8) | `collision_mesh_move` | absent → −1; any value → the mesh of that name (no `none` test) |

Named collision meshes are loaded with `CGfxMeshMgr::LoadMesh(name, format, file, null, type 3, 1.0)`
S 0050b5b0, which returns the index of an already loaded mesh of that name and file or appends a new entry; it
has no "not found" result of its own. [known] What `S2CE::CMesh::Load` leaves in the entry when the file has
no mesh of that name, or when the file is missing, is [TODO] not established: read `S2CE::CMesh::Load`. In
the shipped data 19 of the 23 named collision meshes exist in their `.KEX`; the other four belong to the
classes `gasthaus2_outside`, `gasthaus2_inside`, `building_outside` and `building_inside`, whose
`file="testhaus.kex"` is not in the install [known: `lobbyobj.xml`, the `.KEX` mesh lists, file listing].

`CPhysicObj::ctor(meshId, group, transform, xmlIndex, xmlNode, world)` S 00522c80 [known]:

1. If the class's `controllerparm` element has a `file` attribute: `LoadFromNxuFile` (§3.6). No shipped class
   has one (all 110 `controllerparm` elements are empty [known] `lobbyobj.xml`).
2. Else if `meshId ≠ −1`: `CreateTriangleMeshActor`.

`CreateTriangleMeshActor` S 00522410 [known unless tagged]:

1. Mesh geometry from `CGfxMeshMgr::GetMeshGeometry(meshId)` S 00509cb0: vertex pointer, vertex stride, vertex
   count, 16-bit index pointer, index count, the mesh entry's name and its file string (all read from the
   entry's CPU-side mesh data, whatever the entry's type).
2. Cache path = `<Local AppData>\SAdK\<mesh entry name>_<mesh entry file>.phx` (`SHGetFolderPath` CSIDL 0x1c
   S 0057ba10; literals `\` S 007d4964, `SAdK` S 007d421c, `_` S 007e7628, `.phx` S 007e7620). The entry name
   is the mesh name passed to `LoadMesh` (empty when a render mesh was loaded without a `mesh` attribute) and
   the entry file is the `file` attribute as written, so the terrain's two files are
   `Terrain_Terrain.kex.phx` and `collision_Terrain.kex.phx`. [inferred from S 0050b5b0, S 005191c0 and
   `lobbyobj.xml`]
3. `File_CompareWriteTime(<mesh entry file>, <cache path>) ≥ 0` S 006e7270 (model file not older than the
   cache; the function returns 0 when either file cannot be opened or a time cannot be read, so a missing
   cache cooks too) → cook: cooking interface `NxGetCookingLib(0x2070000)` (fetched once, kept), slot 0xc
   `NxInitCooking(0, 0)`, slot 0x14 `NxCookTriangleMesh(desc, memory stream)`, write the stream to the cache
   file, slot 0x10 `NxCloseCooking`. The mesh description: `numVertices` = vertex count, `numTriangles` = index
   count / 3, `pointStrideBytes` = vertex stride, `triangleStrideBytes` = **6**, `flags` = **3**
   ([inferred] flip normals + 16-bit indices), no material indices, `heightFieldVerticalAxis` = 0xff (not a
   height field), `convexEdgeThreshold` = **0.001**.
4. Read the whole cache file, `sdk->createTriangleMesh(stream)` (SDK slot 0x20).
5. Shape description (`NxTriangleMeshShapeDesc`): identity local pose, `shapeFlags` = **8**, `group` = the
   group argument, material index 0, density 1.0, mass −1, skin width −1 (SDK defaults except the group).
6. Actor description: no body (static), density **10.0**, global pose = translation `transform[0..2]`,
   rotation from the quaternion `transform[3..6]`; `scene->createActor` (scene slot 0x18). The result is stored
   in `CPhysicObj.actor`.

The mesh is used with the object's world position and rotation; it is not scaled. The cache is derived data.

Which meshes collide in the shipped data [known] `config\lobbyobj.xml` (decrypted): 110 classes, 104 with
controller `std`, of which 99 have `gfxclass="std"` (the other five, `sky01_dome`, `sky01_plane_low`,
`sky01_plane_high`, `snapshotavatar` and `PawnChessTable`, get no actor):

| Attribute value | Classes | Effect |
|---|---|---|
| `collision_mesh="collision"` | `Tree01_export`..`Tree04_export`, `Cart`, `Letterbox` | solid for avatar, camera, picking |
| `collision_mesh="collisionmesh_out"` | `taverne02`, `taverne03`, `townhall`; `gasthaus2_outside`, `building_outside` (file not shipped) | building exterior |
| `collision_mesh="collisionmesh_in"` | `taverne02_inside`, `taverne03_inside`, `townhall_inside`; `gasthaus2_inside`, `building_inside` (file not shipped) | interior (its own zone) |
| `collision_mesh_move="collisionmesh_moveOnly"` | `taverne02_inside`, `taverne03_inside` | second actor: blocks walking only |
| `collision_mesh_move="collision"`, no `collision_mesh` | `Terrain` | two actors: the render mesh `Terrain` in group `zone` (avatar, camera rays, pick ray) and the mesh `collision` in group `zone + 16` (avatar only) |
| `collision_mesh="none"` | 29 classes: `Grass1`..`Grass3`, `Reet1`, `tree01`, the flowers, nettles, ferns, mushrooms, `bush_1_big`, `bush_1_small` | no actor |
| `collision_mesh="empty"` | `taverne02_1`, `taverne02_2`, `taverne03_1`, `taverne03_2` | actor from the mesh `empty` of the class's `.KEX`: 24 vertices, 36 indices, a box of about 1.2 × 1.2 × 1.0 at file coordinates x 17.1..18.3, y −9.1..−7.9, z 0..0.99 (z up) [known: the four `.KEX` files]; a placeholder that stands in for "no collision" |
| `collision_mesh` absent | 49 further classes of `gfxclass="std"`: `wall01`..`wall04`, `house01`..`house03`, `taverne01`, `ground`, `Bridge_export`, `WaterPlane`, `Fence01`..`Fence06`, `fence07` (lower case in the file), `Fence08`, `ad0`, `ad1`, `banner01`, `triangleflags`, `minigametable4`, `table0`..`table14`, `bg_creation`, `bg_scot`, `bg_egypt`, `bg_bavaria`, `CharSelect`, `fadetest`, `softalpha`, `softalpha_plm`, `testheightmap`, `testtree` | the render mesh is the collision mesh, in group `zone` |

Which of these classes a scene file actually places is in [`lobby-world-client.md`](lobby-world-client.md).

Consequences [inferred from the table and §2.3]: camera rays and the pick ray hit the terrain's render mesh
and every scenery object that has no `collision_mesh` attribute, as well as buildings, trees, the cart and the
letterbox; only the terrain's `collision` mesh and the two `collisionmesh_moveOnly` meshes are invisible to
them. The avatar stands on whichever of the two terrain meshes is higher at its position. An interior and its
exterior stand at the same coordinates and are separated only by the zone number in the group.

### 3.3 The character controller [known] S 005234c0 (disassembly), constants read at the addresses given

Created by `CLocalController::ctor` S 0051a1a0, that is once per lobby object of controller class `character`
that is flagged as the player's own avatar (`CLobbyObj::ctor` S 00502e60); the constructor passes the object's
spawn transform and the `LobbyContext`:

| Parameter | Value | Evidence |
|---|---|---|
| Shape | capsule, type code 1 | `[desc+0xc] = 1` |
| Radius | **0.5** | S 007d877c → `desc.radius` |
| Height (cylinder part) | **1.0** (capsule 2.0 tall over all) | `FLD1` → `desc.height` |
| Position | spawn position with y **+ 1.0** (0.5 + 0.5): the capsule centre | double 0.5 at S 007d4a90, added twice |
| Up axis | y (code 1) | `desc.upDirection = 1` |
| Slope limit | **cos(π/3) = 0.5**: slopes up to 60° are walkable [inferred meaning] | double `0x3ff0c15240000000` = 1.0471976 at S 007e7760 → `__CIcos` |
| Skin width | **0.02** | float `0x3ca3d70a` at S 007e1d98 |
| Step offset | **1.0** (obstacles up to one unit are stepped onto) | `FLD1` → `desc.stepOffset` |
| Hit report | global `NxUserControllerHitReport` S 0087cebc | vtable S 007e763c: slots 0 and 1 (the two callbacks) are `__purecall` S 006f371b, slot 2 the deleting destructor |
| Other description fields | +0x08, +0x3c, +0x40 = 0 | [inferred] SDK defaults of `NxControllerDesc`; names not established |
| Shape group | 31, set on every shape of the controller's actor | S 005235de, S 00520af0 |

Operations:

- `Move(displacement, activeGroups)` S 00523670: `controller->move(displacement, activeGroups, minDist 0.01,
  &collisionFlags, sharpness 1.0, groupsMask null)`. The returned collision flags are discarded: the client
  never knows whether the avatar stands on the ground. [known]
- `GetTransform(out)` S 00523610: controller position (slot 0x10, doubles) with
  `y − height × 0.5 − radius` = y − 1.0 (the feet), then the stored quaternion. [known]
- `SetOrientation(quat)` S 005236c0: stores the quaternion; the capsule does not rotate. [known]
- `SetPosition(pos)` S 00523430: `controller->setPosition(pos)` without the +1.0 offset; no caller found in the
  decompile cache. [inferred] The avatar's position after creation changes only through `Move`.
- Destructor S 00523390: `controllerManager->releaseController(controller)` (slot 0xc).

### 3.4 Avatar movement, falling and jumping

The input step that produces the displacement is specified in
[`lobby-world-client.md`](lobby-world-client.md) §3.4. The physics part, per fixed step of 83 ms [known]
S 0051a840 (tail, disassembly S 0051aca0..S 0051acce):

1. Horizontal part: the local vector (0, 0, ±1) rotated by the move heading, times **0.5** (walking, float at
   S 007d877c) or **1.0** (run modifier held). The z component is −1 with the backward key, +1 with the
   forward key (forward wins over backward) and also +1 while exactly one of the two turn keys is held, so
   turning alone walks forward; zero without any of these.
2. `SetOrientation(rotation(y, moveHeading))` (axis (0, 1, 0) at S 00882864, angle `CLocalController + 0x40`).
3. `displacement.y −= 0.5` (double 0.5 at S 007d4a90), always, with or without input.
4. `Move(displacement, collisionMask)`.

Resulting rules:

- **Speed**: 0.5 units per step = about **6.0 units/s** walking, 1.0 per step = about **12.0 units/s**
  running. [inferred from the 83 ms step]
- **Falling**: there is no velocity and no acceleration. An unsupported avatar sinks a constant 0.5 units per
  step, about **6.0 units/s**. On the ground the downward part is absorbed by the collision. The scene gravity
  of −9.8 does not act on the controller. [known for the constant; inferred for the gravity]
- **Slopes and steps**: left to the controller: step offset 1.0, slope limit 60° (§3.3).
- **Jumping**: Space sets a latch (`CLocalController + 0x3b`) that is sent with the position report
  (S 0051ace0) and cleared after a report that went out; no upward displacement exists. [known] S 0051a93c
  That the latch plays an animation is specified in [`lobby-world-client.md`](lobby-world-client.md) §3.6.
- **World bounds**: none in code. The two terrain meshes span x and z −125..+125 (§6.2); what stops the
  avatar at their edge, or below them, is [TODO] (§10 #5).
- **Zone change**: `collisionMask` is recomputed as `0x10001 << zone` from the avatar object's primary zone
  (`CLobbyObj + 0x28`) at the start of every step, before the movement (`ProcessInputAndSendLocation`
  S 0051ace0), so the avatar collides with the groups of its new zone from the step after a door changed
  that field. [known for the write; the door test itself is in the lobby world document]

### 3.5 Ray queries

Both use scene slot 0x14c, [inferred] `raycastClosestShape(ray, shapesType, hit, groups, maxDist, hintFlags,
groupsMask, cache)`, with `shapesType` = 3 (static and dynamic), `hintFlags` = 0xffffffff, no groups mask, no
cache. The hit distance is read at hit + 0x24. [known: S 0051a7a3, S 004f63eb]

**Camera collision** (`CLocalController::ComputeCameraCollisionDistance(target, desiredDistance, viewDir)`
S 0051a450) [known]: the own character's shapes are excluded for the duration (`SetRaycastEnabled(false)`
before, `(true)` after); 8 rays, ray i (0..7) at the angle i × 45° (`π / 180 × i × 360 × 0.125`, constants
at S 007fccfc, S 007db6a0, S 007debc0, S 007e69e8), from points on a circle of radius 0.5 (double at
S 007d4a90) around the camera target, along the view direction, groups = `collisionMask & 0xffff`,
unlimited length (`FLT_MAX`, float at S 007e56e0). Each hit yields
`max(hitDistance − CameraCollisionDistance, 0.01)` (0.01: float at S 007dee88); the result is the smallest of
these values and `desiredDistance`, and it becomes the orbit distance of the camera key. The circle's two
axes are built by cross products of the normalised view direction with (0, 1, 0) [inferred: both
perpendicular to the view direction]. The remaining steps are in
[`lobby-world-client.md`](lobby-world-client.md) §3.4.

**Pick occlusion** (`CLobby::UpdatePickingAndSelection` S 004f6190) [known, disassembly S 004f6373..S 004f6409]:
only when the current zone is below 11. One ray from the pick ray's origin (`CLobby + 0x238`, three floats)
along its direction (`CLobby + 0x244`), groups = `1 << currentZone`, unlimited length (`FLT_MAX`). Start with
`limit = maxSelectionDistance` (`CLobby + 0x268`, the tweakable of §3.8 of the lobby world document, 25.0).
On a hit: `limit = min(limit, hitDistance + 2.0)` (double 2.0 at S 007e0bc0). `limit` is then the maximum
distance passed to `CGfxScene::PickClosestObject`. So an object standing more than 2.0 units behind anything
in the group `currentZone` cannot be picked: the terrain's render mesh, a building's collision mesh, a tree,
the cart, the letterbox, or any scenery object without a `collision_mesh` attribute (§3.2).

The same function's two other constants [known]: the selected object is dropped when its distance from the
pick ray's origin exceeds `maxSelectionDistance + 2.5` (double at S 007e56e8); the own avatar is excluded from
picking unless the distance between the camera eye (camera slot 8) and the point (0, 2.0, 0) above the
position its graphics object reports (slot 0x14) exceeds 3.5 (double at S 007e56d8; S 004f640d..S 004f649b).

### 3.6 NxuStream files (`ai::physics`, `NXU`)

The client links the PhysX utility library NxuStream: an XML reader (`ai::physics::NxuXmlReader`, on TinyXML),
a binary reader, a COLLADA physics importer (`ai::physics::ColladaImport`, about 130 named `Collada*`
functions) and the instantiator. One game function reaches it:

`CPhysicObj::LoadFromNxuFile(position, fileName)` S 00522290 [known]: resolve `fileName` through the file index
(`FileScanHolder::ResolvePath`), `NXU::loadCollection(path, 1, null, 0)` (file type 1 = XML: the loader
treats 0 as binary, 2 as COLLADA and anything else as XML), `NXU::instantiateCollection(collection, sdk,
scene, rootPose, notify)` with an identity rotation and the three floats of `position` as translation (the
object's rotation is not passed; disassembly S 0052239a..S 005223aa), `NXU_releaseCollection`. The result of
`loadCollection` is not tested. The object's notify face keeps the last actor the instantiator reports
(`NXU_notifyActor` S 00520ae0); `NXU_preNotifyScene` S 005209a0 returns null and `NXU_preNotifySceneInstance`
S 005209c0 returns true (library defaults).

This path needs a `file` attribute on a `controllerparm`, which no shipped class has (§3.2), so it never runs
with the shipped data. File type 2 (COLLADA) and 0 (binary) are never requested: `loadCollection` has this one
caller, so `ColladaImport` is dead code in this client. [known: caller lists of S 00731630, S 007578a0]

`loadCollection` S 00731630 opens the file with the C runtime (`fopen(name, "rb")` in `NXU_FILE::Init`
S 00731a40) and the XML reader S 0074d250 parses it with `TiXmlDocument::LoadFile` S 0075f2e0, which opens it
the same way, not through the game's decrypting file layer [known]. The three shipped `physic\*.xml` files
are encrypted containers (§3.7), so they could not be parsed as they ship. [inferred]

Debug drawing (`LobbyPhysics_DebugDrawShape` S 00522170) knows shape types 2 box, 3 capsule, 5 convex, 6
triangle mesh, 7 height field [known: jump table]; the game itself creates only type 6 and the controller's
capsule.

### 3.7 File format: `data\lobby\physic\*.xml`

Encrypted container ([`formats-inventory.md`](formats-inventory.md) §2.3); the plain text is PhysX NxuStream 2
XML as exported by the PhysX plug-in of the modelling tool. Three files: `myhouse.xml` (9,396 bytes plain),
`lobby_castle01.xml` (2,989), `lobby_castle02.xml` (2,272). No class, scene file, layout, shader, `.KEX` or
code string names them [known: search of the decrypted data and of the image's strings]. Layout as found in
the files [known: file contents]:

```
<?xml version="1.0" encoding="utf-8"?>
<NXUSTREAM2>
  <NxuPhysicsCollection id="<export path>" sdkVersion="244" nxuVersion="100">
    <NxPhysicsSDKDesc id="SDK"/>
    <NxConvexMeshDesc id="ConvexMesh_0">            (castle files)
      <points>x y z  x y z ...</points>             floats, 3 per vertex
      <triangles>a b c  a b c ...</triangles>       vertex indices, 3 per triangle
      <cookedDataSize>0</cookedDataSize> <cookedData/>
    </NxConvexMeshDesc>
    <NxTriangleMeshDesc id="TriangleMesh_0">        (myhouse.xml)
      <materialIndices/> <pmapData/> <cookedDataSize>0</cookedDataSize> <cookedData/>
      <NxSimpleTriangleMesh> <points>...</points> <triangles>...</triangles> </NxSimpleTriangleMesh>
    </NxTriangleMeshDesc>
    <NxSceneDesc id="Scene_0">
      <NxGroupsMask id="groupMask0"/> <NxGroupsMask id="groupMask1"/>
      <gravity>0 0 -9.809999466</gravity> <maxTimestep>0.016666668</maxTimestep>
      <NxSceneLimits id="limits"/>
      <NxMaterialDesc id="Material_0"> <dirOfAnisotropy>0 0 0</dirOfAnisotropy> </NxMaterialDesc>
      <NxMaterialDesc id="Material_1" materialIndex="1">   (castle files)
        <dynamicFriction>0.300000012</dynamicFriction> <staticFriction>...</staticFriction>
        <restitution>...</restitution>              (all three 0.300000012)
      </NxMaterialDesc>
      <NxActorDesc id="Actor_0" name="<node name>">
        <globalPose>12 floats</globalPose>          (lobby_castle01.xml only; [inferred] 3 x 3 rotation,
                                                    then translation)
        <density>1</density>
        <NxConvexShapeDesc meshData="ConvexMesh_0"> | <NxTriangleMeshShapeDesc meshData="TriangleMesh_0">
          <NxMeshShapeFlag id="meshFlags">          (castle files)
            <NX_MESH_SMOOTH_SPHERE_COLLISIONS>false</NX_MESH_SMOOTH_SPHERE_COLLISIONS>
            <NX_MESH_DOUBLE_SIDED>false</NX_MESH_DOUBLE_SIDED>
          </NxMeshShapeFlag>
          <NxShapeDesc>
            <localPose>12 floats</localPose>        (myhouse.xml, lobby_castle01.xml)
            <materialIndex>1</materialIndex>        (castle files)
            <shapeDensity>1</shapeDensity>
            <shapeMass>-1</shapeMass>               (castle files)
            <skinWidth>0.100000001</skinWidth> <NxGroupsMask id="groupsMask"/>
          </NxShapeDesc>
        </...ShapeDesc>
      </NxActorDesc>
    </NxSceneDesc>
  </NxuPhysicsCollection>
</NXUSTREAM2>
```

Content: `myhouse.xml` one actor `phys`, a triangle mesh of 193 vertices and 368 triangles (two nested boxes,
8 and 10 units wide, z up); `lobby_castle01.xml` one actor `Hull01`, a convex mesh of 18 vertices and 32
triangles, collection id `C:\Temp\teapot.xml`; `lobby_castle02.xml` one actor `Cone01`, 8 vertices and 12
triangles. The meshes are stored as raw points and triangles (`cookedDataSize` 0), z is up, gravity is along
−z: tool test exports, not village geometry. [known: file contents; the judgement is inferred]

### 3.8 The loose images in `data\lobby\heightmap`

The village terrain is an ordinary model (§6.2). Three images in the folder are named by nothing [known:
search of the decrypted data, the `.KEX` material lists, the shaders and the image's strings]:

| File | Format | Content |
|---|---|---|
| `heightmap1.tga` | encrypted; TGA type 3 (uncompressed greyscale), 128 × 128, 8 bit, top-left origin, TGA 2.0 footer | grey values 46..154; [inferred] the height image the terrain was modelled from |
| `density.tga` | encrypted; TGA type 2, 128 × 128, 24 bit | [inferred] a plant density mask of the same grid |
| `grassblade.TGA` | encrypted; TGA type 2, 32 × 256, 32 bit with alpha | one grass blade sprite |

The client has no height-map reader for the lobby: no function reads a grey image into terrain or into a PhysX
height field. [known: no reference to these names; `NxHeightField` appears only in the NxuStream library and
the debug drawer]

### 3.9 Web textures: life cycle

**Start-up** [known] S 00405590, S 005c76b0, S 005c7760, S 005c8540: `CApplicationEx::InitEngineLayer` calls
`CURL2Tex::CreateInstance(hInstance, hWnd)` before the graphics device exists. It runs once:
`OleInitialize(null)` and registration of the window class `URL2TEX_IE_WINDOW` (window procedure S 005c83a0,
null background brush).

**Creating a web texture** `CTexture::CreateFromURL(width, height, url, 0)` S 004e7880 [known]:
`D3DXCreateTexture(device, width, height, 1 level, usage 0, format 0x16 = X8R8G8B8, pool 1 = managed)`; width
and height are re-read from the level description; `g_pURL2Tex->RequestURL(d3dTexture, url)`;
`bRegisteredURL = 1`. Returns false only when the texture cannot be created. The texture is not cleared: until
the page arrives it shows whatever the driver allocated. [inferred]

**`RequestURL(texture, url)`** S 005c8050 [known]:

1. No entry for this texture: new entry (sizes from the texture, scroll range −1), new `CSDKIEWindow`,
   `CreateHostWindow`, insert into the map.
2. Entry exists: `disabled = false`.
3. Store the URL, `IWebBrowser2::Navigate(url)` (slot 0x2c, all optional arguments null, result ignored).

**Host window** `CreateHostWindow` S 005c8760, `EmbedWebBrowser` S 005c85c0 [known]: a window of class
`URL2TEX_IE_WINDOW`, style 0xcc0000 (caption, system menu, sizing frame; not visible), extended style 1, client
size 128 × 128, parent = the game window, with the property `URL2TexWindowProp` pointing at the object. Into
it: `CoCreateInstance(CLSID_WebBrowser, null, CLSCTX 7, IID_IUnknown)`, `SetClientSite`,
`SetObjectRects({0, 0, entry.width, entry.height}, clientRect)` ([inferred] the page is laid out at the
texture's size), `DoVerb(−5 = OLEIVERB_INPLACEACTIVATE)`, and an advise of the `DWebBrowserEvents2` sink
(class and interface ids read at S 00831ad8..S 00831b58). No result code is checked.

**Events** `CSDKIEEvents::Invoke` S 005c8a30 [known]:

| DISPID | Event | Reaction |
|---|---|---|
| 0xfa | BeforeNavigate2 | allowed (`*Cancel = false`) |
| 0x103 | DocumentComplete | only when the event's browser is the control itself (frames are ignored): `RenderToTexture(0, 0)` |
| 0x10f | NavigateError | `*Cancel = true`; unless the entry is `disabled`, texture level 0 is locked and filled with opaque red `0xffff0000` (S 005c7790) |
| 0x66, 0x6c, 0xfc | status text, progress, NavigateComplete2 | ignored, success |
| other | | `E_NOTIMPL` |

**`RenderToTexture(scrollLeft, scrollTop)`** S 005c7ba0 [known: the slot offsets, the order and the three
interface ids read at S 00831aa8 (`IHTMLBodyElement`), S 00831ab8 (`IHTMLElementRender`), S 00831ac8
(`IHTMLElement2`); inferred: the member names, which follow the MSHTML IDL order]. Nothing when `disabled`.
Else, each step only if the one before succeeded:

1. Browser slot 0x48 (`get_Document`), document slot 0x24 (`get_body`); the body is queried for
   `IHTMLElementRender` and `IHTMLBodyElement`, and that for `IHTMLElement2`.
2. Body slot 0x40 (`get_style`), style slot 0x1c4 with `"none"` (`put_borderStyle`); `IHTMLBodyElement` slot
   0x8c with `"no"` (`put_scroll`).
3. Read four values of `IHTMLElement2`: slot 0x104 (`clientLeft`), 0xfc (`clientWidth`), 0x100 (`clientTop`),
   0xf8 (`clientHeight`).
4. Slot 0x148 with 20000000 (`put_scrollTop`), slot 0x150 with 20000000 (`put_scrollLeft`).
5. `maxScrollX` = slot 0x144 (`scrollWidth`) + `clientLeft` − `clientWidth`;
   `maxScrollY` = slot 0x140 (`scrollHeight`) + `clientTop` − `clientHeight`.
6. Slot 0x148 with `scrollTop`, slot 0x150 with `scrollLeft`.
7. Texture slot 0x48 (`GetSurfaceLevel(0)`), surface slot 0x30 (`GetDesc`), slot 0x3c (`GetDC`),
   `IHTMLElementRender` slot 0xc (`DrawToDC(hdc)`), surface slot 0x40 (`ReleaseDC`).

A failure in step 7 is written to the debug output (`GetSurfaceLevel failed`, `GetDesc failed`,
`GetDC failed`, `Draw failed`) and leaves the texture as it was; a failure in steps 1 to 2 ends the function
silently. The results of steps 3 to 6 are not tested.

**Refresh**: there is no timer. A texture is redrawn when (a) a navigation of its control completes, which
includes any reload or redirect the page performs itself, (b) `UpdateFromURL(scrollLeft, scrollTop)` is called
(only the Hall of Fame does, when its slider moves), (c) a navigation error paints it red. [known: the callers
of S 005c7ba0 and S 005c7790]

**Destroying**: `CTexture::dtor` S 004e7c20 calls `SetEntryDisabled(d3dTexture)` when `bRegisteredURL` is set;
the entry and its browser stay alive (and may keep loading) until the `CURL2Tex` itself is destroyed
(`CURL2Tex::dtor` S 005c7fb0 deletes every entry and its window), they only stop drawing. [known]
`CSDKIEWindow::dtor` S 005c83e0 calls `IWebBrowser2::Quit` (slot 0x80) and releases the interfaces; the event
advise is never undone. A `WM_CLOSE` to a host window removes the property, destroys the window and deletes
its `CSDKIEWindow` (S 005c83a0, S 005c8360); the entry keeps its pointer. [known]

### 3.10 Web textures: the two users

**Advertising screens** [known] S 00504650: `Lobby::CGfxTextureMgr::GetTexture` creates a texture on first use
from its entry name. Three names are compared case-sensitively and are not loaded from disk:

| Texture name | Size | URL |
|---|---|---|
| `ad0.tga` | 1024 × 512 | `http://www.funatics.de/sadk/forwarding1.html` (S 007e6210) |
| `ad1.tga` | 1024 × 512 | `http://www.funatics.de/sadk/forwarding2.html` (S 007e61d8) |
| `ad2.tga` | 1024 × 512 | `http://www.funatics.de/sadk/forwarding3.html` (S 007e61a0) |

The page is requested once, when `GetTexture` is first called for the entry ([inferred] when the board model
is first drawn in zone 0), and never again by the client. The models `ad0.KEX`, `ad1.KEX` and their placement:
`scene\scene_ad.xml`
([`lobby-world-client.md`](lobby-world-client.md) §3.12). The shipped `objects\ad0.tga`, `ad1.tga`, `ad2.tga`
(each 789,354 bytes encrypted) are never read. The URLs answer 404 today; the result on screen and the
replacement mod are recorded in [`../BINARY_PATCHES.md`](../BINARY_PATCHES.md) (live 2026-10-07 and
2026-10-08 there).

**Hall of Fame** (`LobbyMenu::HallOfFameDialog`) [known] S 004427a0, S 00442230, S 004428f0, S 00442640:

1. Constructor: a new texture, `CreateFromURL(1024, 512, HallOfFame_BuildUrl(0), 0)`.
2. `HallOfFame_BuildUrl(i)`: `[LobbyClient] HallOfFameURL<i>` of `LobbySettings.ini` (default empty); if
   `HallOfFameURL<i>_AppendPermID` ≠ 0 and a local avatar exists, append `&permid=<decimal perm id>`; if
   `HallOfFameURL<i>_AppendCharname` ≠ 0 and a local avatar exists, append `&char=<character name>` (not
   URL-encoded).
3. A click on `Button_0`, `Button_1` or `Button_2`: `RegisterURL(HallOfFame_BuildUrl(i))` on the same texture.
4. Every frame while the dialog is visible: bind the texture to the `WebPage` widget with source rectangle
   (0, 0, **768**, **512**) in texels; `GetURLContentSize(&x, &y)`; when it succeeds (both ≠ −1): slider range
   = `y`; if the slider position changed: `UpdateFromURL(0, position)`.
5. `OnShow` S 00442340 registers a walk-away watch of radius 2.0 with the lobby; its callback S 004421c0
   closes the dialog ([`lobby-screens.md`](lobby-screens.md) §3.2, "Walk-away watch").

The page therefore has to be designed for a layout width of 1024 of which the left 768 × 512 are shown, and is
scrolled vertically by redrawing.

### 3.11 The files in `data\lobby\web`

Plain files, opened by nothing in the client [known: no string `Rangliste`, `UIColor`, `web\` or local `.html`
name in the image; [`formats-inventory.md`](formats-inventory.md) §3.14].

| File | Content |
|---|---|
| `Rangliste1.html`, `Rangliste2.html` | identical, 371 bytes, HTML 4.01 Transitional, ISO-8859-1, title `Test`: a body with `background-image: url(uicolor.png)` and one empty `div` of 768 × 512 pixels |
| `UIColor.PNG` | PNG, 768 × 512, 8-bit RGB: the dialog background the test page shows |

768 × 512 is the visible rectangle of the Hall of Fame view (§3.10): these are layout test pages for the
ranking ("Rangliste") display. [inferred]

## 4. Update order

On process start [known]: `CURL2Tex::CreateInstance` (S 00405590, engine layer); later
`CLobby::StartUp` S 004f8c90 creates `LobbyPhysics` and calls `LobbyPhysics_Init`. `StartUp` is called by
`CApplicationEx::Initialize` S 004075d0 only when a `CLobby` exists, and that is created only without
`-nolobby` (`CApplicationEx.noLobby`) ([`lobby-world-client.md`](lobby-world-client.md) §3.1).

On world load [known] S 00502e60, S 005198c0, S 0051a1a0: every object of controller class `std` builds its
static actors (cooking or reading the `.phx` cache) in the constructor of its `CStaticController`, after its
graphics object exists; the own avatar's `CLocalController` and character controller are created in the
constructor of the avatar object.

Per fixed step of 83 ms (`CLobby::RenderObjects` S 004f58a0, the object step; its only caller is
`CLobby::Tick` S 004fb230) [known]. `Tick` runs it while `nextStepMs < nowMs`, adding 83 to `nextStepMs` before
each call; when `nowMs − nextStepMs` exceeds 1000 it first sets `nextStepMs = nowMs` and the dirty flag; after
the loop a set dirty flag (`CLobby + 0x04`, 1 from the constructor) causes one more call and is cleared. Every
call, also the extra one, performs all three steps below with the same step length:

1. S 005002b0: scene slot 0x1d4 with (1, 1, 0) ([inferred] `fetchResults(rigid body finished, block)`), then
   controller manager slot 0x14 ([inferred] `updateControllers`).
2. Every object, in the order of the object array (`CLobbyObj::Update` S 005029e0): controller slot 1 `Update`
   (the local controller S 0051a350 reads `GetTransform` here and hands the pose to the graphics object), the
   door test `CLobbyObj::UpdateScene` S 005027f0, then controller slot 2. For the local controller slot 2 is
   `ProcessInputAndSendLocation` S 0051ace0 (vtable S 007e70e8): it recomputes `collisionMask`, calls
   `UpdateMovementAndCamera` S 0051a840 (in this order: `GetTransform` for the camera target key, the camera
   rays, the input evaluation, `SetOrientation`, `Move`) and then reads `GetTransform` again for the position
   report.
3. `LobbyPhysics::Step` S 005003a0 with `&CLobby.stepMs`: scene slot 0x1cc with 83 / 1000 = 0.083 ([inferred]
   `simulate(0.083)`), scene slot 0xe0 ([inferred] `flushStream`).

So the pose the graphics object shows in a step is the result of the `Move` of the step before. [inferred from
the order above]

Per rendered frame: the pick ray (§3.5) in `UpdatePickingAndSelection`, called from `CLobby::RenderFrame`
S 004f9960 [known]; the Hall of Fame's update (§3.10), a virtual of the dialog whose caller was not read
[inferred: per frame, [`lobby-screens.md`](lobby-screens.md)].

Asynchronously, from the window message loop: browser events (§3.9).

On shutdown: `LobbyPhysics_Shutdown` from `CLobby::dtor` S 004fa890.

## 5. Inputs and outputs

| Direction | Interface | Detail |
|---|---|---|
| in | `lobbyobj.xml` attributes `collision_mesh`, `collision_mesh_move`, `controllerparm file` | which meshes collide (§3.2) |
| in | mesh geometry from `CGfxMeshMgr` | vertices and 16-bit indices of the named mesh of the class's `.KEX` |
| in | input step of `CLocalController` | displacement and heading per step |
| out | avatar pose (feet position + quaternion) | to the graphics object and to the position report |
| out | camera distance limit, pick distance limit | to `CLobbyCamera` and `CGfxScene::PickClosestObject` |
| in | URLs: three literals, three keys of `LobbySettings.ini` | §3.10 |
| out | HTTP GET by the Internet Explorer control | outside the game protocol; no TinCat message |
| out | texture contents | sampled by the board material / the `WebPage` widget |

Network messages: none are sent or handled here. The pose produced by the controller is what message **2000**
(avatar location) carries; layout in
[`../village-and-character-protocol.md`](../village-and-character-protocol.md) §4.2, sending rule in
[`lobby-world-client.md`](lobby-world-client.md) §3.4. The server receives positions that only the sending
client has collision-checked; other clients display them without any collision.

## 6. Data-driven parameters

### 6.1 Constants and where they come from

| Parameter | Value | Source |
|---|---|---|
| Fixed step | 83 ms | code, `CLobby` constructor S 004fb100 |
| Walk / run displacement per step | 0.5 / 1.0 | code S 0051ab13, S 0051abf3 |
| Downward displacement per step | 0.5 | code S 0051acb3 |
| Capsule radius, height, skin, step offset, slope limit | 0.5, 1.0, 0.02, 1.0, cos 60° | code S 005234c0 |
| Scene gravity, default material | (0, −9.8, 0); 0.5 / 0.5 / 0.5 | code S 00500410 |
| `Lobby/CameraCollisionDistance` | 0.1 (range 0..2) | tweakable S 0087cbd0, registered in S 0051a450 |
| `Lobby/Show PhysicDBG`, `Lobby/Show GfxObjStd PhysicDBG` | off | debug tweakables S 005084b0, S 005191c0: wireframe of the actors |
| Web texture size | 1024 × 512 | code S 00504650, S 004427a0 |
| Hall of Fame visible rectangle | 768 × 512 | code S 00442230 |

None of the movement or controller parameters is read from a data file.

### 6.2 Files

| File | Role | Example values |
|---|---|---|
| `data\lobby\config\lobbyobj.xml` | `gfxparm collision_mesh`, `collision_mesh_move` per class (§3.2) | `Terrain`: `file="Terrain.kex" mesh="Terrain" collision_mesh_move="collision" lod_class="terrain"` |
| `data\lobby\heightmap\Terrain.KEX` | the ground: meshes `Terrain` (2,633 vertices, 15,111 indices) and `collision` (3,035 vertices, 16,299 indices) | both span −125..+125 on the two ground axes and −11.46..+49.44 in height (file axes: z up) |
| `data\lobby\heightmap\*.dds` | textures of the `Terrain` material: `terrain_color01.dds` (2048², diffuse), `terrain_details.dds` (1024²), `terrain_mask01.dds` (1024², DXT3), `Ground_parallax.dds` (1024²); `terrain_light01.dds` (2048², DXT1) is the zone 0 light map of `scene1_settings.xml` | |
| `data\lobby\heightmap\testheightmap.KEX` | one mesh `Terrain` (5,065 vertices, 18,339 indices); class `testheightmap` (`std` / `std`, `file` and `lod_class` only, so its render mesh would collide, §3.2); placed only by `scene2.xml`, which `world1.xml` does not list | |
| `data\lobby\heightmap\heightmap1.tga`, `density.tga`, `grassblade.TGA` | unreferenced (§3.8) | |
| `data\lobby\physic\*.xml` | unreferenced NxuStream exports (§3.7) | |
| `data\lobby\config\LobbySettings.ini` | `[LobbyClient] HallOfFameURL0..2`, `HallOfFameURL<n>_AppendPermID` | `http://sadk.funatics.de:7012/rankingMaster/ranking.php?ranking=weekly&limit=20&offset=0` (1: `monthly`, 2: `yearly`), each with `_AppendPermID=1`; no `_AppendCharname` key |
| `data\lobby\web\*` | unreferenced test pages (§3.11) | |
| `data\lobby\objects\ad0.tga`..`ad2.tga` | never read (§3.10) | |

The `collision` mesh of `Terrain.KEX` against its render mesh `Terrain` [known: vertex and index streams of the
file]: 5,433 triangles against 5,037; 468 triangles within 3° of vertical against 72. These walls stand inside
the area (ground axes about −105..+106 and −108..+101), are up to 23.3 units high, and are what only the avatar
collides with (§2.3). Neither mesh has a skirt or wall at the ±125 border: the 107 border vertices of both lie
at heights 12.44..41.0, above the lowest ground (−11.46). The walls alone do not fence the village [known: data, 0.5-unit grid of the
ground plane, faces at least 1.0 high]: the faces steeper than 60° leave the origin connected to the mesh border
(one way: to about (18, 10), then in +y to (18, 124), file axes); the faces steeper than 48° enclose it (free
region about 9,500 square units, x −56..61.5, y −74..92.5). The ring is closed by slopes between about 48° and
60°, so whether the avatar is confined depends on the slope rule of the character library (§10 #10).

Classes without a `collision_mesh` attribute that the scene files of `world1.xml` place, and whose render mesh
therefore is a collision mesh in group `zone` (§3.2) [known: `scene\world1.xml`, its eight scene files,
`lobbyobj.xml`]: `Terrain`, `WaterPlane`, `ground`, `Bridge_export`, `wall01`..`wall04`, `house01`..`house03`,
`taverne01`, `banner01` (4 objects), `triangleflags`, `ad0`, `ad1`, `fence07` in `scene1.xml` / `scene_ad.xml`,
and `bg_creation`, `bg_scot`, `bg_egypt`, `bg_bavaria`, `CharSelect` in `scene_customizeavatar.xml` (zone
offset 12). `scene1.xml` also writes the types `fence01`..`fence06`, `fence08` and `cart` in lower case, while
the classes are named `Fence01`.. and `Cart`; the scene loader lower-cases the type
([`lobby-world-client.md`](lobby-world-client.md) §3.1), so whether these eight objects resolve to a class
depends on how the class table compares names (§10 #8). The 30 table spots `table0`..`table14` that the world
load creates in zones 2 and 3 have no `collision_mesh` attribute either. Not placed by `world1.xml`:
`minigametable4`, `fadetest`, `softalpha`, `softalpha_plm`, `testheightmap` and `testtree`.

### 6.3 `data\lobby` against the inventory

Every folder of `data\lobby` holds only file types that [`formats-inventory.md`](formats-inventory.md) lists
(`.KEX` / `.kex`, `.dds`, `.tga`, `.BMP`, `.xml`, `.txt`, `.ini`, `.fx`, `.ogg`, `.wav`, `.html`, `.PNG`)
[known: listing of the install, 680 files in 13 top-level folders, 22 folders with their sub-folders]. What
that inventory does not describe, and this document adds:

| Item | Where specified |
|---|---|
| layout and content of `physic\*.xml`; that the meshes are raw, not cooked | §3.7 |
| the three loose images of `heightmap` | §3.8 |
| content of the `web` files | §3.11 |
| the `.phx` cache written to `<Local AppData>\SAdK\` | §3.2, §7 |
| sub-folders `objects\minigame` (26 files: tables, pieces, dice, chips, card and chip textures) and `objects\TestData` (12 files: the dice board `MaOb_Spielfeld.KEX`, `MaOb_Chiptray.KEX`, textures) | ordinary `.KEX` models and textures, found by name like every other file (`formats-inventory.md` §3.1) |
| `config\LobbySettings - Copy.ini` | a second copy of the settings with another `Host`; not read (`formats-inventory.md` §3.14) |

## 7. Save and load

Nothing of this state is saved. Derived files:

- `<Local AppData>\SAdK\<mesh name>_<mesh file>.phx`: one cooked PhysX triangle mesh per collision mesh, the
  cooking library's own stream format, rebuilt whenever the model file is not older than the cache (§3.2).
  A reimplementation ignores them.
- The browser control uses the Internet Explorer cache and cookies of the Windows user. [inferred]

## 8. Determinism notes

Presentation and front end only.

- `NxCreatePhysicsSDK` and `NxCreateControllerManager` are called only from `LobbyPhysics_Init`, and the scene
  is stepped only from the lobby's object step (scene slot 0x1cc has no other caller on a `LobbyPhysics`).
  That step runs from `CLobby::Tick` whenever `CLobby::Update` S 004fb460 is called, whatever the lobby mode:
  in modes 2 and 3, and in modes 0 / 1 while the main menu shows the 3D world behind its screen
  ([`lobby-world-client.md`](lobby-world-client.md) §8); in none of these is a match simulated. A match has
  no physics of any kind: units, ships,
  projectiles and the camera of the game use the map grid and the terrain mesh
  ([`logic-core.md`](logic-core.md), [`camera-input-cutscenes.md`](camera-input-cutscenes.md)). [known for
  the creators: import references, [`../subsystems.md`](../subsystems.md) §2.10; inferred for the rest]
- Inside the lobby, physics decides only the local avatar's position, the camera distance and the pick limit.
  Scene gravity, material values and the simulate call are cosmetic even there (§3.1).
- The avatar position is not synchronised deterministically: each client moves its own avatar and reports it.
- Web textures touch no game state. `url2tex` is created at start-up even with `-nolobby`, but nothing
  requests a URL outside the lobby. [inferred: the two users of §3.10 are lobby classes]

## 9. Notes for a Godot reimplementation

- **No PhysX.** One `CharacterBody3D` for the own avatar with a capsule of radius 0.5 and total height 2.0
  (centre 1.0 above the feet), safe margin 0.02, `floor_max_angle` 60°, and a step-up of 1.0 (Godot has no
  built-in step offset: sweep up, forward, down). Per 83 ms step call `move_and_collide` (or
  `move_and_slide` with a velocity of displacement / 0.083) with the horizontal displacement and a constant
  −0.5 in y; no gravity acceleration, no jump arc.
- **Static colliders** from the converter, for every class of controller `std` and graphics class `std`: the
  mesh named by `collision_mesh`, or the render mesh when that attribute is absent, or nothing when it is
  `none`; plus the mesh named by `collision_mesh_move` (§3.2). Each as a `ConcavePolygonShape3D` at the
  object's position and rotation, unscaled.
  Triangle winding: the original cooks with the flip-normals flag; use back-face collision or verify the
  winding on one building (§10 #6).
- **Layers**: layer `zone + 1` for the first collider, layer `zone + 17` for `collision_mesh_move`. Avatar
  mask = both layers of its zone; camera spring arm (8 parallel rays on a 0.5 circle, margin 0.1, minimum
  0.01) and pick ray = the first only. The terrain's render mesh is in the first layer, so the camera and the
  pick ray collide with the ground (§3.2).
- **Picking**: clip the pick distance to `min(25, wallHit + 2)`.
- **Other avatars** need no collision.
- **Web textures**: Godot has no HTML renderer. The remake's server should provide the ranking as data
  (weekly, monthly, yearly; 20 rows from an offset, as the original query shows) and the client should draw it
  with its own UI in a 768 × 512 panel with vertical scrolling. The three boards take an image (1024 × 512,
  2:1) from the server or the plank texture the billboards mod uses. A request per board on first sight and
  one per ranking tab click is the original's load pattern.
- **Converter**: skip `physic\*.xml`, `web\*`, `heightmap1.tga`, `density.tga`, `grassblade.TGA`, `ad*.tga`
  and all `.phx` files.

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | When `NxCharacter.dll` 2.7 calls the hit report: both callbacks of the client's report object are `__purecall`, so a call would abort the process | static: `NxCharacter.dll` (calls through the report pointer); live: walk into a wall with a breakpoint on S 006f371b |
| 2 | PhysX method names behind the slots used (scene 0x14c, 0x1cc, 0x1d4, 0xe0, 0xe4; shape 0x08, 0x14, 0x5c; actor 0x118; controller manager 0x14) | static: export tables and vtables of `PhysXCore.dll` / `NxCharacter.dll` 2.7.0, or the 2.7.0 SDK headers |
| 3 | What a mesh entry holds when its file or its mesh name does not exist (the four classes on the missing `testhaus.kex`), and so what `CreateTriangleMeshActor` cooks for it | static: `S2CE::CMesh::Load` and its callee for a missing file |
| 4 | Whether an entry loaded as a render mesh (`LoadMesh` type 0 or 2) keeps the CPU vertex and index arrays that `GetMeshGeometry` hands to the cooking (§3.2: render meshes as collision meshes) | static: `S2CE::CMesh::Load`, `LobbyGfx_MeshEntry_CreateBuffers`; live: `Lobby/Show GfxObjStd PhysicDBG` on a fence |
| 5 | Whether the avatar can leave the terrain. Data (§6.2): the `collision` mesh encloses the origin only when slopes above about 48° stop the avatar; with slopes up to 60° walkable there is a way to the ±125 border, where nothing stops the constant sinking | live: walk in +y (file axes) at x ≈ 18 from the spawn area; the same walk answers #10 |
| 6 | Meaning of mesh flags value 3 and the resulting solid side of the triangles | static: `NxMeshFlags` of the 2.7.0 headers; live: debug wireframe via `Lobby/Show GfxObjStd PhysicDBG` |
| 7 | The MSHTML member behind each slot of `RenderToTexture` (§3.9 names them by IDL order; the interface ids are read) | static: the `mshtml.h` vtable order of `IHTMLElement2`, `IHTMLBodyElement`, `IHTMLStyle` |
| 8 | Whether the lower-cased scene types `fence01`..`fence06`, `fence08` and `cart` find the classes `Fence01`.., `Cart` (§6.2): if they do, seven more render meshes and the cart's `collision` mesh collide | static: `LobbyObjConfig::FindEntry` S 004ffa80 and `LoadFromFile` S 004ffe70 (case handling of the class name) |
| 9 | Texture content between creation and the first DocumentComplete | live: watch a board while the page loads |
| 10 | Whether the slope limit acts as "walkable up to 60°" in NxCharacter 2.7 with these values | live: walk up the steepest terrain; static: `NxCharacter.dll` |

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 00500290 | `ai::lobby::LobbyPhysics::ctor` | stores the step length |
| S 00500410 | `LobbyPhysics_Init` | SDK, controller manager, scene, timing, default material |
| S 005002b0 | (fetch results + update controllers) | scene slot 0x1d4, controller manager slot 0x14; in the object step before the objects |
| S 005003a0 | `ai::lobby::LobbyPhysics::Step` | simulate one step, flush |
| S 005002e0 | `LobbyPhysics_Shutdown` | releases everything |
| S 005198c0 | `Lobby::CStaticController::ctor` | creates the two static collision objects of an object |
| S 005191b0 | `Lobby::CGfxObjStd::GetCollisionMeshId` | mesh id of `collision_mesh` (0) / `collision_mesh_move` (1) |
| S 00522c80 | `Lobby::CPhysicObj::ctor` | NxuStream file or triangle mesh |
| S 00522410 | `Lobby::CPhysicObj::CreateTriangleMeshActor` | `.phx` cache, cooking, shape, static actor |
| S 00522290 | `Lobby::CPhysicObj::LoadFromNxuFile` | NxuStream XML collection into the scene |
| S 00520a80 / S 00521100 | `CPhysicObj::GetPose` / `SetPose` | actor pose |
| S 00520b30 | `CPhysicObj` slot 5 | raycast flag of all shapes |
| S 00520af0 | `LobbyPhysics_ForEachActorShapeCall08` | sets the group of all shapes of an actor |
| S 005234c0 | `Lobby::CPhysicObjCharacter::ctor` | capsule controller and its parameters |
| S 00523670 | `CPhysicObjCharacter::Move` | controller move |
| S 00523610 | `CPhysicObjCharacter::GetTransform` | feet position + orientation |
| S 00523430 / S 005236c0 | `CPhysicObjCharacter::SetPosition` / `SetOrientation` | teleport / store orientation |
| S 0051a1a0 | `Lobby::CLocalController::ctor` | collision mask, creates the character |
| S 0051a350 | `CLocalController::Update` | controller slot 1: pose from `GetTransform` to the graphics object, animation flags |
| S 0051ace0 | `CLocalController::ProcessInputAndSendLocation` | controller slot 2: collision mask, movement, position report |
| S 0051a840 | `CLocalController::UpdateMovementAndCamera` | camera keys and rays, displacement, constant sink, `Move` |
| S 0051a450 | `CLocalController::ComputeCameraCollisionDistance` | 8 camera rays |
| S 004f6190 | `Lobby::CLobby::UpdatePickingAndSelection` | pick occlusion ray |
| S 004f58a0 | `Lobby::CLobby::RenderObjects` | the fixed object step |
| S 004fb230 / S 004fb460 | `Lobby::CLobby::Tick` / `Update` | fixed-step loop that calls the object step / its per-frame caller |
| S 005029e0 / S 005027f0 | `Lobby::CLobbyObj::Update` / `UpdateScene` | controller slot 1, door test, controller slot 2 |
| S 00522170 / S 00522220 | `LobbyPhysics_DebugDrawShape` / `DebugDrawActor` | debug wireframes |
| S 00731630 | `NXU::loadCollection` | NxuStream loader (XML, binary, COLLADA) |
| S 00730800 | `NXU::instantiateCollection` | creates the collection's objects in a scene |
| S 0074d250 | `ai::physics::NxuXmlReader::xmlReaderInit` | TinyXML parse of an NxuStream XML file |
| S 007578a0 | `NXU::colladaImport` | COLLADA physics importer, unreachable |
| S 005c76b0 / S 005c7760 | `url2tex::CURL2Tex::CreateInstance` / `Init` | singleton, OLE, window class |
| S 005c8050 | `CURL2Tex::RequestURL` | entry + browser per texture, navigate |
| S 005c79a0 / S 005c7f10 / S 005c7a30 | `CURL2Tex::GetContentSize` / `UpdateTexture` / `SetEntryDisabled` | scroll range, redraw, stop drawing |
| S 005c7ba0 | `url2tex::CURL2TexEntry::RenderToTexture` | page body drawn into texture level 0 |
| S 005c7790 | `CURL2TexEntry::ClearTextureToRed` | error fill |
| S 005c8760 / S 005c85c0 / S 005c8800 | `url2tex::CSDKIEWindow::CreateHostWindow` / `EmbedWebBrowser` / `Navigate` | hidden host window, browser control |
| S 005c8a30 | `url2tex::CSDKIEEvents::Invoke` | browser events |
| S 004e7880 / S 004e77d0 / S 004e7440 / S 004e7410 | `S2CE::CTexture::CreateFromURL` / `RegisterURL` / `UpdateFromURL` / `GetURLContentSize` | texture side of a web texture |
| S 00504650 | `Lobby::CGfxTextureMgr::GetTexture` | the three advertising textures |
| S 004427a0 / S 00442230 / S 004428f0 / S 00442640 | `LobbyMenu::HallOfFameDialog` ctor / `Update` / `HandleButtonClicks`, `HallOfFame_BuildUrl` | ranking view |
| S 00465960 | `ai::lobby::LobbyProfile::GetHallOfFameUrl` | the three ini keys |
