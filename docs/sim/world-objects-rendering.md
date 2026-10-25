# World presentation objects: goods, streets, decals, sky and the render engine layer

Specification of the presentation objects that `docs/sim/rendering.md` only summarises: goods as shown at flags,
on building sites and in hands (`S2CG::ItemMgr`, `S2CG::Item`, `ai::render::ItemPile`, `ai::render::ItemRenderer`),
street, crossing, water-street and sea-route geometry (`S2CG::CStreet`, `S2CG::StreetDecal`,
`ai::gfx::StreetFlagNode`, `ai::gfx::StreetRenderer`), projected ground decals (`ai::render::DecalProjector`,
`ai::render::DecalRenderer`), the sky dome (`ai::render::SkyRenderer`), block culling
(`ai::render::GridQuadTree`), and the engine layer below them (`S2CE::CGraphicDevice`, `CShaderProgram`,
`CTexture`, `CTextureAtlas`, `CResourceMgr`, `CVertexStream`). Binary: `sadk_noav.exe`; "S 00xxxxxx" is a static
address in it.

Tags: **[known]** = read directly in the decompiled code or disassembly at the address given, in the bytes at the
address given, or in the named data file and key. **[inferred]** = one step of reasoning from what is visible;
also used where a statement rests on the mapped name and comment of a function whose body was not re-read line
by line, and where the decompiler output is damaged at that place. **[TODO]** = open, with what would settle it.
Nothing here was observed in the running game.

Related documents (not repeated here): `docs/sim/rendering.md` (scene, frame order, terrain, water, buildings,
settlers, map objects, light, shadows, post effects), `docs/sim/animation-models.md` (`CMesh::Load`, the `.mshraw`
cache, skeletons, the colour ramp atlas), `docs/sim/streets-transport.md` (logic streets, flags, packages, flag
capacity), `docs/sim/map-resources.md` (grids, cell to world), `docs/sim/formats-inventory.md`,
`docs/asset-formats.md` (encrypted container, KEX), `docs/map-format.md`.

---

## 1. Purpose and scope

Everything in this document is presentation. It consumes simulation state through the scene callbacks and
produces draw calls. In scope:

- which model a good is shown with, where goods lie at a flag and on a building site, how a good follows its
  carrier, the limits of a pile;
- how the mesh of a street, of a crossing, of a water street and of a sea route is built and textured;
- projected decals (selection markers, the blob under settlers);
- the sky dome geometry and its shader;
- the quad tree that culls terrain blocks;
- the engine layer as far as a converter or a look-alike renderer needs it: technique selection, the shared
  shader constants, every `.fx` file with its inputs and result, texture loading, the run-time texture atlas,
  resource caching and the vertex layouts.

Out of scope: terrain, water, buildings, settlers, ships, animals, projectiles and particles (their rules are in
`docs/sim/rendering.md` §3.3 to §3.13); the mesh and animation file formats (`docs/sim/animation-models.md`).

---

## 2. Data model

### 2.1 Goods

**`ItemTypeDesc`**, 0x7c bytes, one per `<Item>` of `items.xml`, in the global table S 0088d870 (count), S 0088d878
(array) [known] S 0069d650, mapped struct:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | i32 | `refCount` | number of items created of the type; the mesh is loaded while it is 0 [known] S 0069def0 |
| +0x04 | string | `name` | the `name` attribute; equals the name of a good property |
| +0x20 | string | `meshFile` | the `mesh` attribute |
| +0x3c | ptr | `mesh` | `S2CE::CMesh` |
| +0x40 | ptr | texture | diffuse texture of the mesh (§3.1) |
| +0x44 | float[6] | `boundingBox` | AABB of the mesh, min then max [known] S 0069dbe0 |
| +0x5c | string | `donkeyMeshFile` | from `<DonkeyItems>` (§3.1) |
| +0x78 | ptr | second mesh | loaded only when `donkeyMeshFile` is not empty |

**`AnimatedItemTypeDesc`**, 0xdc bytes, one per child of `<AnimatedItems>` (count S 0088d87c, array S 0088d884):
item type index from `references` (+0x7c, -1 when no `<Item>` has that name), the strings `mesh` (+0x80), `model`
(+0x9c) and `animation` (+0xc0) [known] S 0069d650. The install has none (§6).

**`S2CG::Item`**, 0x7c bytes, one per visible good [known] mapped struct, S 006d0480:

| Offset | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | u32 | `handle` | 1-based handle in `ItemMgr` |
| +0x08 | ptr | `logicItem` | the logic package, or 0 for items created by good id or by type |
| +0x0c | i32 | `stackKey` | good id (of the package, `logicItem +0x18`, or as given), -1 for items created by type; decides the stack |
| +0x10 | i32 | `typeIndex` | index into the `ItemTypeDesc` table |
| +0x14 | bool | `visible` | drawn only when set |
| +0x18 | float[16] | `worldMatrix` | row-major, translation in elements 12..14 |
| +0x58 | bool | `frozen` | set for items owned by another renderer (scaffold stacks, the boat); `Update` skips them |
| +0x5c | i32 | `attachCharacterId` | character the item is bound to, 0 = none |
| +0x60 | i32 | `boneIndex` | bone of that character, -1 = the character's root matrix |
| +0x64 | bool | `landed` | false while falling to the ground |
| +0x68 | float | `fallVelocity` | world units per second, negative = down |
| +0x6c | bool | `pileLatch` | the pile direction was handed to the carrier once |
| +0x70 | float | stack angle | direction of the stack the item is in, radians (mapped name `stackHeight`) |
| +0x74 | ptr | `pile` | `ItemPile` it lies on |
| +0x78 | ptr | `carrierShip` | ship visual carrying it |

**`ai::render::ItemPile`**, 0x9b4 bytes, one per logic flag [known] S 006ce8d0, S 0069c390:

| Offset | Type | Field |
|---|---|---|
| +0x00 | ptr | owner: the logic flag (its cell at +0x28, its id at +0x38 / +0x3c) |
| +0x04 | bool | `visible` |
| +0x08 | i32 | `itemCount` |
| +0x0c | `ItemPileStack[6]` | six stacks, 0x19c bytes each (0xc + 6 x 0x19c = 0x9b4) |

**`ItemPileStack`**, 0x19c bytes: `key` (+0, i32, good id, -1 = free), `items` (+4, `Item*[6]`, slot 0 first),
`slotMatrices` (+0x1c, 6 x float[16], world matrix of each slot) [known] S 006ce8d0, S 006ceb50.

**`ItemPileLayoutTable`** (singleton S 0088df18): `layoutCount` (+0), `distance` (+4), `layouts` (+8, array of
`ItemPileSlotOffsets`, 0x48 bytes = six float[3]), a map good → layout index (+0xc) [known] S 006d0eb0.

**`S2CG::ItemMgr`** (singleton S 0088d86c), 0x50 bytes: the `ItemRenderer` (+4), a handle pool with the item
slots (+8 count, +0x10 `Item*` array indexed by handle - 1, +0x14.. free handles), the list of active handles
(+0x20 count, +0x28 data), the pile array (+0x2c count, +0x30 capacity, +0x34 data), the texture cache (+0x44
count, +0x4c entries of 0x20 bytes: path string, texture pointer at +0x1c) [known] S 0069def0, S 0069c390,
S 0069dac0.

**`ai::render::ItemRenderer`**: per item type a plain list (`{count, capacity, data}`, 0xc bytes) and an
instanced entry (0x1c bytes: vertex buffer, index buffer, i32 batch size (+8, 0 = not instanced, else 40), list
(+0xc..+0x14), float switch timer (+0x18)); a dynamic vertex stream of 10000 vertices and index stream of 30000
indices for the plain path [known] S 006d01e0, S 006cf210, S 006d0090, S 006cfc20.

### 2.2 Streets

**`StreetRenderConfig`**, 0x30 bytes, global S 0088dca0, filled from `<Street>` of `graphics.xml` [known]
S 006c3f10, mapped struct:

| Offset | Type | Field | Install value |
|---|---|---|---|
| +0x00 | i32 | `numSegments` | 8 |
| +0x04 | float | `width` (half width) | 1.0 |
| +0x08 | float | `texStretch` | 0.25 |
| +0x0c | float | `crossingRadius` | 2.25 |
| +0x10 | float | `buoyDistance` | 1.7 |
| +0x14 | i32 | `routeNumSegments` | 3 |
| +0x18 | float | `routeWidth` (half width) | 2.5 |
| +0x1c | float | `routeTexStretch` | 0.1 |
| +0x20 | float | `routeTexSpeed` | 10.0 |
| +0x24 | i32 | `routeTexCount` | 16 |
| +0x28 | i32 | `maxBatchVertices` | 6000 (constant in code) |
| +0x2c | i32 | `maxBatchIndices` | 8000 (constant in code) |

Two colours next to it, 4 floats each: `redStreetColor` at S 00881fc8 and `alphaStreetColor` at S 00881fd8
[known] S 006c3f10 (attribute name strings S 007fb38c, S 007fb378). Install values [known] `graphics.xml`:
`redStreetColor="1.0 0.0 0.0 0.9"`, `alphaStreetColor="1.0 1.0 1.0 0.6"`. The same element names the files:
`texture0` / `normal0`, `texture1` / `normal1`, `crossingTexture0` / `crossingNormal0`, `crossingTexture1` /
`crossingNormal1`, `buoyTexture`, `routeTexture`, `shader` (install: `street_shader.fx`).

**`S2CG::CStreet`**, 0x60 bytes (`S2CG::WaterStreet` 0xac) [known] S 006cd480, S 0069f570:

| Offset | Field | Meaning |
|---|---|---|
| +0x04 | `renderObj` | the mesh object (`StreetDecal`, `StreetBuoy` or `RouteDecal`) |
| +0x08 | `routeSpline` | `ai::math::RouteSpline` (0x24 bytes) |
| +0x0c | `previewDrawMode` | 0 normal, 1 and 2 = the two under-construction tints (§3.6) |
| +0x10 | `route` | the logic street (`NNet::Street`): cell path vector at +0x18 (first +0x1c, last +0x20, 8 bytes per cell), type at +0xe4 |
| +0x14..+0x20 | from / to cell | first and last cell of the path |
| +0x24..+0x30 | cell bounds | min / max cell of the path |
| +0x4c | bool | always-visible flag (frustum test bypass) |
| +0x50, +0x58 | `startLink`, `endLink` | `StreetFlagNode` at each end; the direction index beside each is 12345 when unset |

Street type `NNet::Street +0xe4`: 0 = normal, 1 = upgraded (second carrier), 2 = water street [known] S 0069f570,
S 006d1290; rule of the upgrade in `docs/sim/streets-transport.md`.

**`ai::math::RouteSpline`**, 0x24 bytes: a copy of the cell path (vector of 8-byte cells), `pointCount` (+0x10),
`tangents` (+0x14, float[4] per point: unit tangent xyz, w = length of the segment that starts at the point,
§3.5), `totalLength` (+0x18), `hasFixedHeight` (+0x1c), `fixedHeight` (+0x20) [known] S 006d7a80.

**`ai::gfx::StreetFlagNode`**, 0xcc bytes: owner (+0), `active` (+4), cell (`tileX` +8, `tileY` +0xc), `position`
(+0x10, world), frame axes (+0x1c, +0x28) and `normal` (+0x34), `streets[6]` (+0x40, one per hexagon direction),
`attachedCount` (+0x58), `corners` (+0x5c, six float[3]), `radius[6]` (+0xa4), `decal` (+0xc4, the crossing
mesh), `isKind1Crossing` (+0xc8) [known] S 006d1370, S 006d1670, S 006d1d90; offsets of owner, `active`, the
cell and `decal` [inferred] from the mapped struct.

**Street mesh object** (`S2CG::StreetDecal` and its siblings): `vertexCount` (+4), `indexCount` (+8), `vertices`
(+0xc, 48 bytes each, §2.6), `indices` (+0x10, u16), `subMeshCount` (+0x20), `subMeshRanges` (+0x24, pairs
`{vertexCount, indexCount}`) [known] S 006de590, S 006c3250.

**`ai::gfx::StreetRenderer`**, 0x168 bytes: a random generator seeded 0x5432ace0, one dynamic vertex and index
stream, the effect, five pass handles, the handles of `ROUTE_TEX_MIXER` and `STREET_COLOR_MODIFIER`, texture and
normal map pairs for street kind 0 and 1 and for crossing kind 0 and 1, the buoy and the route texture, two
route texture matrices, and eight pointer lists: streets kind 0, streets kind 1, crossings kind 0, crossings
kind 1, buoys, routes, under-construction (alpha), under-construction (red) [known] S 006c4290. The dynamic
streams hold `maxBatchVertices` vertices of the 48-byte layout and `maxBatchIndices` indices; the five passes are
looked up by name (`RenderStreet`, `RenderBuoys`, `RenderRoutes`, `RenderStreetUnderConstruction`,
`RenderBuoysUnderConstruction`) [known] S 006c4290.

### 2.3 Decals

**`ai::render::DecalProjector`**, 0x6c bytes [known] S 004efaa0, mapped struct:

| Offset | Type | Field | Initial |
|---|---|---|---|
| +0x00 | ptr | next projector of the same texture | 0 |
| +0x04 | bool | enabled | 0 |
| +0x08 | float[3] | `centre` | 0 |
| +0x14 | float[3] | `normal` (projection direction) | up |
| +0x20 | float[3] | `uAxis` | unit X |
| +0x2c | float[3] | `vAxis` | unit Z |
| +0x38 | float | `width` | 0 |
| +0x3c | float | `height` | 0 |
| +0x40 | float[4] | `color` rgba | 1, 1, 1, 1 |
| +0x50 | float[2] | `uvOffset` | 0, 0 |
| +0x58 | float[2] | `uvScale` | 1, 1 |
| +0x60 | i32 | `vertexCount` | 0 |
| +0x64 | ptr | `vertices` (36 bytes each, §2.6) | 0 |
| +0x68 | i32 | texture index (order of `decals.xml`) | constructor argument |

**`ai::render::DecalRenderer`** (singleton S 008872fc): a dynamic vertex stream of 12000 vertices, the effect
`decal_shader.fx`, the texture array, and one linked list of projectors per texture (a new projector becomes
the head of its list) [known] S 004df850, S 004df400, S 004df1d0. The textures are the `name` attributes of the
children of `[data]\settings\decals.xml`, in file order, each loaded with a single mip level [known]
S 004df850; the install lists three: `[data]\gfx\decals.dds` (index 0), `buildingselect.dds` (1),
`catapultTarget.dds` (2) [known] `decals.xml`.

**`ai::render::SelectionMarker`**, 0x38 bytes: the owning `CMapRenderer` (+0), `decal` (+4), a cell (+8) with a
radius (+0x10, i32), a target ship id (+0x18), a target object id (+0x28) [known] S 006b0d00; offsets [inferred]
from the mapped struct.

### 2.4 Sky

**`ai::render::SkyRenderer`**: effect (+0), handle of `DAYTIME_INTERPOLATION` (+4), technique table (+8), pass
handles `Skydome` (+0x28) and `Sun` (+0x2c), vertex stream (+0x30), index stream (+0x34), `triangleCount` (+0x38),
`vertexCount` (+0x3c), the dome position (+0x40, float[3]; mapped name `sunDirection`, used as the translation
of the dome's world matrix, §3.10), `daytimeInterpolation` (+0x4c) [known] S 006af150, S 006af210, S 006af260,
S 006af300.

Skydome definitions (global array `g_Env_SkydomeDefs`, 0x3c bytes each: name, texture path at +0x1c, rotation
at +0x38) and one instance per definition, in the same order, in `CEnviromentMgr` (0x24 bytes each: name,
texture at +0x1c, rotation at +0x20) [known] S 00684fb0.

### 2.5 Culling

**`ai::render::GridQuadTree`**, 0xa4 bytes, owned by `S2CG::CTerrainCellMgr` [known] S 006daf20: `root`, `width`,
`height` (in terrain blocks), `cellCount` = width x height, an optional horizon occluder, the frustum planes of
the frame, eye position and view direction, `lodParam`, a remaining-output budget, the merged bounds of the
visible blocks, the visible block rectangle (min / max x and y) and the min / max view depth of the visible
blocks.

**`GridQuadNode`**, 0x34 bytes: `parent`, `children[4]` (0 = low x low y, 1 = high x low y, 2 = low x high y,
3 = high x high y), `bounds` (float[6]), 3 flag bits (bits 1..2 select the child visiting order through the
table S 007fc1b8) and a 29-bit `cellIndex` (the block index `width * y + x` for a leaf, the value `cellCount`
for an inner node) [known] S 006da9f0, S 006db220. Build rule [known] S 006da9f0: a rectangle of one block is a
leaf whose bounds are the block's AABB, merged with the AABB of the block's objects when it has any; a rectangle
one block wide or high is split in two at the middle (children 0 and 2, or 0 and 1); any other rectangle is
split in four at `(x0 + x1) / 2`, `(y0 + y1) / 2`; an inner node's bounds are the union of its children.

"Block" is the terrain block of `docs/sim/rendering.md` §2.5 (the code calls it `TerrainCell`).

### 2.6 Vertex layouts

An engine vertex layout is a list of 12-byte records `{type, usage, usageIndex}` ended by a record with
`usageIndex` -1 (the tables end with `{9, 15, -1}`); offsets are packed in list order. Type sizes [known] bytes
at S 007e3fac: type 0 = 4 bytes, 1 = 8, 2 = 12, 3 = 16, 4 to 7 = 4. The three values are copied unchanged into
a Direct3D 9 vertex element (stream 0, method 0) [known] S 004e4fd0, so they are those of Direct3D 9: type
0..3 = float1..float4, 4 = packed ARGB colour; usage 0 = position, 2 = blend indices, 3 = normal, 5 = texture
coordinate, 6 = tangent, 10 = colour [inferred from the Direct3D 9 enumerations].

| Table | Used by | Layout | Size |
|---|---|---|---|
| S 007fbc0c | item meshes, plain path | position float3, normal float3, uv float2 | 32 |
| S 007fbc3c | item meshes, instanced path | position float3, normal float3, uv float2, blend indices (4 bytes, byte 0 = instance index) | 36 |
| S 007fb300 | streets, crossings, buoys, routes | position float3, normal float3, colour ARGB, uv float2, tangent float3 | 48 |
| S 007e3b68 | projected decals | position float3, normal float3, colour ARGB, uv float2 | 36 |
| S 007fa9c4 | sky dome | position float3, colour ARGB, uv float2 | 24 |

[known] bytes at the table addresses; users [known] S 0069dbe0, S 006cfd30, S 006c4290, S 004df850, S 006af490.
The buoy model is loaded with the 48-byte street layout [known] S 006e2350.

---

## 3. Rules and algorithms

### 3.1 Goods: which model

1. A good is shown with the `<Item>` whose `name` equals the name of the good's property record
   (`PropertiesDb::GetGoodProperty(goodId)->name`, `ItemTypes_FindByName`) [known] S 0069def0, S 0069e0f0. The
   comparison is exact (length and bytes, case-sensitive); a name without an `<Item>` gives -1 [known]
   S 0069c5c0. Neither creator that goes by good checks for -1 before indexing the type table [known]
   S 0069def0, S 0069e0f0; the check exists as `ItemTypes_HasTypeForGood` S 0069c660, whose only caller is
   `CharacterSettler::GetDefaultItemGoodId` S 006c72b0. A remake must give every good an item or skip the visual.
   In the install, 27 of the 100 `gp_setName` calls of `scripts/properties/Goods.lua` give a name without an
   `<Item>` among the 54 of `items.xml`, and every one of those goods has the type `WareGroup` or `EitherGroup`
   (`Weapons`, `Food`, `ConstructionResources`, `Casern Good`, `Ship`, ...) [known, files]. With the shipped
   data no group good becomes a package's good or a site stock entry [inferred from the code and the files].
   Packages are created only by `PackageSystem::CreatePackage` S 0064fb10, through four callers [known]:
   `CreateCarriedPackage` S 0064cce0 (from `Pickup` S 00777e00, `PutDownPackage` S 0077a8e0 and
   `ConstructShip` S 0077d6c0), `CreatePackageAt` S 0064cd90 (site stock of an aborted construction),
   `SpawnCarrierWithPackage` S 0064d020 (the good of a need) and `SpillGoodsOntoFlag` S 0064d9d0 (stock
   contents). None tests the good type, but the goods reaching them are wares: needs are the recipe entries
   of product slot 0, with an `EitherGroup` entry expanded to its members (`RequestAllInputs` S 00565a70;
   the one `WareGroup` entry, `sheepAnimal` of `sheep`, belongs to `hunterScots`, which has
   `bp_setIgnoreGoodCosts`), and every construction cost (`bp_addCost`, `bp_addFrameCost`) is a ware, which
   is all a site stock receives. A worker carries a stored good out only if it is of type Ware
   (`Depot::HasAnyWare` S 0055b120, `TakeOneWare`; `PickupProduct::Start` S 00777f80); otherwise he takes
   product slot 0, and the buildings whose product slot 0 is a group good have modes that never carry a
   product (sacrifice, barracks, catapult, sheep breeder, ship site without worker, the unplaceable
   `construction*` types). The animal stack goods and the script goods of the shipped maps
   (`vi_addGoodsToDepot`) are wares or soldiers. A changed data set (a group good in a cost list, as product of
   a mode 1, 2, 3 or 7 building, or given by a script) would make such packages.
2. On the first item of a type: load the mesh file with the 32-byte layout, compute its AABB, and take the
   texture named by the mesh's material parameter `DiffuseColor` of subset 0, looked up in the directory of the
   mesh file (the part of `mesh` up to and including the last backslash) [known] S 0069dbe0. A mesh without
   that parameter leaves the type without a texture. Textures are shared by exact path inside `ItemMgr`
   [known] `GetOrLoadTexture` S 0069dac0. A second mesh is loaded the same way when `donkeyMeshFile` is set.
3. `<DonkeyItems>`: for each child, the type named by `references` gets a second mesh file (`mesh`). The loop
   that reads these children starts from the first child of the `<AnimatedItems>` element, not of
   `<DonkeyItems>` [known] S 0069d650 (disassembly: the node pushed at S 0069d995 is the `<AnimatedItems>`
   node kept from S 0069d7d5 / S 0069d978). A child whose `references` names no `<Item>` is skipped. The install
   has one entry (`<Item references="Wood" mesh="[data]\items\dummy_item.KEX"/>`) and an `<AnimatedItems>`
   element that holds only a comment [known] `items.xml`, so no type gets a donkey mesh [inferred].
4. Three creators, all returning the item handle [known]: `CreateItemForLogicItem` S 0069def0 (a package; scene
   callback), `CreateItemForGood(goodId)` S 0069e0f0 (the good in a settler's hand, the boat of a water street,
   the stacks of a building site), `CreateItemByType(typeIndex)` S 0069e000 (item events of animations). Each
   loads the type's mesh when `refCount` is 0, else increments `refCount`, takes a handle from the pool, appends
   it to the active list and registers the item with the `ItemRenderer`.
5. A package item is placed by its constructor [known] S 006d0480: with a valid flag reference (`logicItem
   +0x48` object, id at `+0x5c` not negative) it joins that flag's pile (§3.2) and, when the package already lies
   (`logicItem +0x70` set), takes its slot matrix at once with `landed` = true; otherwise, with a valid ship
   reference (`+0x98` object, id at `+0xac`), it is bound to that ship's visual. A package has a flag reference
   when its item is created only after loading a save; a package made during play has none yet, and its item
   joins the pile later through the scene callback at +0x68 (`OnLogicItemAddedToPile` S 0069c920, §3.2) [known].
6. The destructor `Item::dtor` S 006d06a0 [known]: when the item is attached, the character's override item is
   cleared only if it still is this item (`CCharacter::ResetIfTargetMatches` with the item's handle); the item
   is removed from its pile (`RemoveItem`, §3.2) and its ship binding dropped.

### 3.2 Goods at a flag: the pile

One `ItemPile` exists per logic flag, created when the flag is created (`Scene::OnFlagCreated` S 00682ca0 →
`CreatePileForFlag` S 0069c390) and found by the flag's 64-bit id [known] S 0069c090.

**Slots.** A pile has 6 stacks of 6 slots: at most 36 goods have a place [known] S 006ce8d0. A stack holds one
good kind; one good kind can fill several stacks. Stack `d` (0..5) lies in direction `d * 60` degrees around
the flag [known] S 006cece0.

**Adding an item** `ItemPile::AddItem(item, alreadyMerged)` S 006cece0 [known]:

1. take the first stack whose `key` equals the item's good id and whose slot 5 is empty; put the item into its
   first empty slot;
2. otherwise take the first free stack (`key` = -1): set its key, put the item in slot 0 and compute the six slot
   matrices of the stack from the item's type (below);
3. otherwise, if `alreadyMerged` is false, run `MergeStacks` and repeat from step 1 once;
4. in every case copy the pile's `visible` to the item and increment `itemCount`. An item that found no place is
   in no stack and keeps the matrix it had. The slot matrices of a stack are computed only in step 2, from the
   type of the item that opens the stack.

**Slot matrices** `ComputeStackTransforms` S 006ce9c0 [known]: with `size` = the AABB size of the item type
(`AABB::GetSize`; max - min [inferred]),
`angle` = `d * 60` degrees in radians (factor 0.017453292), `R` = rotation about Y by `angle`:

```
base      = cellToWorld(flag cell) + R * (0, 0, distance + size.z)      // distance = StackLayouts distance
base.y    = terrain height at base.xz
slot[i]   = rotation R, translation base + R * (offset[i] * size)        // componentwise product, i = 0..5
```

`offset[i]` are the six offsets of the layout bound to the good; a good without a binding uses layout 0
[known] S 006d0cb0.

**Layouts** [known] S 006d0eb0, S 006d0d80: layout 0 is built in: offsets `(0, i, 0)` for i = 0..5 (a vertical
stack). Layouts 1.. are the children of `<StackLayouts>` in order (the element name is not tested): every
attribute whose name starts with `offset` gives the next offset (3 floats, in attribute order), every attribute
whose name starts with `good` binds every good whose property name equals the value to this layout. The table
holds `count + 1` layouts (`count` attribute of `<StackLayouts>`); the loader does not compare the number of
children with `count`. `distance` is the `distance` attribute. Install: `count="2" distance="0.5"` [known]
`items.xml`. Every entry of the table is constructed by `ItemPileSlotOffsets_ctor` S 006d0c70 (vector-constructed
for all `count + 1` entries), which stores 0.0 in all 18 floats (`FLDZ`, then `FST` / `FSTP` to +0x00..+0x44); so
the offsets a child does not give, and layouts announced by `count` that no child fills, stay `(0, 0, 0)` [known]
S 006d0c70, S 006d0eb0.

Limits of the loaders [known] S 0069d650, S 006d0eb0, S 006d0d80: the offsets of a layout are written without
a bound check, so a seventh and later `offset*` attribute overwrites the next layout's offsets (a layout is
six float[3], 0x48 bytes); more children than `count` write past the end of the table. The install's
`<StackLayouts>` holds three XML comments beside its two `<Layout>` children; since the element name is not
tested, the shipped data stays inside the table only if the XML reader does not hand comments to the loop as
children [inferred].

**Removing an item** `ItemPile::RemoveItem` S 006ceb50 [known]: in the stack whose key is the item's good id and
that holds the item (stacks are searched in order; a stack with that key that does not hold the item is passed
over and the search goes on in the later stacks with the same key), every item above moves down one slot and
takes that slot's matrix; slot 5 is cleared; the
removed item is given the matrix of the highest slot that was occupied before the removal, or keeps its own
matrix when it was the top item; a stack with six empty slots becomes free (`key` = -1). `itemCount` decrements
whether or not the item was found. The return value is the stack direction in radians (`d * 1.0471976`), 0 when
the item was in no stack.

**Merging** `ai::render::ItemPile::MergeStacks` S 006cee50 [known]: for each used stack whose slot 5 is empty, while a later
stack with the same key exists, move that stack's slot-0 item into this one (remove, then add). The moved item
is not given the matrix of its new slot: `AddItem` step 1 sets no matrix, so the item keeps the transform
`RemoveItem` gave it in its old stack [known] S 006cee50, S 006cece0, S 006ceb50. Presentation only.

**Visibility** `SetPilesVisibleInRect(minCell, maxCell, visible)` S 0069c300 [known] switches all piles whose
flag cell is inside a cell rectangle (inclusive): the block rectangle grown by one cell on every side when
showing, shrunk by one cell on every side when hiding. `ItemPile::SetVisible` S 006ce880 stores the flag and
copies it to the items of every used stack, up to the first empty slot. The caller is the terrain block's
visibility switch `TerrainCell::SetVisible` S 006b4f80 [known]: when a block's visibility changes or the block
is marked dirty, its piles are shown if the block is visible and revealed (`TerrainCell +0xa0`, the
exploration flag) and hidden otherwise. A new pile starts hidden [known] S 006ce8d0. An item's `visible`
follows its pile at the moment it is added [known] S 006cece0.

**Drop animation** `Item::Update` S 006d0720 [known], run for every active item each frame after the instancing
update (`ItemMgr::Update` S 0069c520), for an item that is not frozen, not attached and not on a ship, while
`landed` is false: if the terrain height under it is below its y,
`fallVelocity -= dt * 0.981; y += fallVelocity * dt` (`dt` = the float at `+0x10` of the frame context: the
scene's frame delta in seconds, which `Scene::UpdateDetailFlagsAndTime` S 0067f6b0 copies from the game system,
so an item falls at 0.981 world units per second squared [inferred: that the frame context carries that
delta]);
otherwise `fallVelocity = 0`, `landed = true` and the item takes its slot matrix (`ApplySlotTransform`
S 006ce970). An item created for a package that already lies (`logicItem +0x70` set) is placed in its slot at
once [known] S 006d0480.

`ApplySlotTransform` itself does not set `landed` [known] S 006ce970. So a good put on the pile without a
carrier (a spilled good, which takes its slot at once, see the hand-over below) is in its slot but not landed:
an item at ground level lands on the next `Item::Update`, while an item in a higher slot is above the terrain,
falls from its slot at 0.981, and on reaching the ground jumps back up into its slot matrix [known for the two
functions; the visible drop and pop is read from them]. Presentation only.

**Carrier hand-over.** Scene callbacks `OnLogicItemAddedToPile` S 0069c920 and `OnLogicItemRemovedFromPile`
S 0069c960 find the item of the package and the pile of the package's flag (`logicItem +0x48`) and call
`Item::OnAddedToPile` S 006d0bd0 / `OnRemovedFromPile` S 006d0c20 [known]. Both store the stack direction
returned by the pile in `Item +0x70` and, when the item has a carrying character (`GetCarrierCharacter`
S 006d0950), write it to the character (`CCharacter +0x98`, with the flag `+0x94` = true); an item added
without a carrier takes its slot matrix at once; `UpdateCarrierAttachment` S 006d09b0 hands the direction over
the same way when a carrier claims a lying item (§3.3) [known]. `CCharacter::UpdateLogic` S 006909f0 copies
that direction into the movement's target yaw (`+0xe8`, snap flag `+0x108` cleared) only while the character plays
a clip of type 7 or 8, and clears the latch [known]: so the carrier turns toward the stack it picks from or puts on
at the turn rate of [animation-models.md](animation-models.md) §3.19 during those clips. Presentation only.

### 3.3 Goods in hands, on ships, on building sites

**In hands** [known] S 006d0720, S 006d0620, S 006d0830: an item with `attachCharacterId` set copies, every
frame in which the character has a skeleton instance, `boneMatrix[boneIndex] * characterMatrix`, or the
character's world matrix alone when `boneIndex` is -1. When the character's visible flag differs from the
item's, the item's `visible` becomes: character visible and the character's item switch
(`CCharacter::GetItemComponentByte4` S 006903e0, which returns `CharacterMovement +0x04`, the fog visibility byte)
set. Attaching registers the item as the character's override item, sets
`boneIndex` when one is given and clears `landed` and `fallVelocity`. Detaching first clears the old
character's override item when it still is this item and takes the attached matrix one last time, then resets
the matrix to identity rotation at the last position with `landed` = false, so the item falls from where it was
released.

**Choosing the holder** `Item::UpdateCarrierAttachment` S 006d09b0, run for all items once per logic tick
(`UpdateAllCarrierAttachments` S 0069c4e0, called from `Scene::SyncLogicTick` S 00680550) [known]; items
without a logic package are skipped. With `lying` = `logicItem +0x70`, "carrier valid" = the id at
`logicItem +0x3c` is not negative, "ship valid" = the id at `logicItem +0xac` is not negative:

- item bound to no character and no ship: if not `lying`, a valid carrier (`logicItem +0x28` object) selects
  its character and the bone given by that character's settler class (virtual slot +0x20), otherwise the ship
  visual of the ship reference (`logicItem +0x98` object) is taken; if `lying` with a valid carrier, a pile and
  `pileLatch` clear, the stack direction (`Item +0x70`) is written to that character once (`pileLatch` = true);
- item bound to a character: it stays while the package is not `lying`, the ship is not valid and the
  character's logic object still equals the package's carrier (`logicItem +0x30`); with a valid ship it moves to
  that ship's visual; in every other case it is detached;
- item bound to a ship: it stays while the package is not `lying`, has no valid carrier and the ship still
  equals the package's ship (`logicItem +0xa0`); otherwise the ship binding is dropped.

Each call takes one of these branches, so a change of carrier takes two logic ticks [known] S 006d09b0,
S 006d0830: in the first the item, still bound to the old character, is detached (identity rotation at its last
position, `landed` = false: it starts to fall, `Item::Update` S 006d0720); in the next, bound to nobody, it is
attached to the new carrier, and `AttachToCharacter` clears `landed` and `fallVelocity` again. For one tick the
good drops from the old carrier's hand. Presentation only.

An item on a ship is not drawn (`visible` = false) [known] S 006d0720.

**Building site** `ai::render::BuildingScaffold` [known] S 006d82f0, S 006d8240, S 006d7f50, S 006d8070.

Lifetime and place [known] `S2CG::Building::Update` S 006abcf0 (per frame, not while the building is being
demolished): the building counts as under construction while its own construction (`Building +0x44`) has
`remainingA` (+0x70) or `remainingB` (+0x74) above 0. Only then, and only when no scaffold exists, one is
created; its source is that construction's stock (construction +0x10), and it is visible unless the building
visual is hidden. An upgrade runs on another construction object (`Building +0x104`), so an upgrade never gets
a scaffold. The scaffold is destroyed when the building is neither under construction nor upgrading. Its
position is `0.5 × (anchor cell centre + entrance flag cell centre)` (`CellToWorldPos` of `Building +0x20` and
of the flag cell, the flag from the reference at `Building +0xa0`), after which x is replaced by the anchor's
x [known: disassembly S 006abdec–S 006abe1a]; `BuildingScaffold::SetPosition` S 006d7d70 sets identity
rotation and the terrain height there. So the goods lie inside the footprint, half way toward the door on the
anchor's x. While the scaffold exists, `RebuildIfSourceChanged` runs in that update every frame (and the
building's sacrifice effects are not updated).

Contents: when the revision counter of the site's stock (`source +0x18`) changes, all site items are destroyed and rebuilt: for
every good of the stock map with a count above 0, in map order, `count` frozen items whose `visible` is the
scaffold's. Layout `LayoutItems` S 006d8070 [known, disassembly]: `pos` starts at the translation of the
scaffold's matrix (`+4`); every item gets that matrix with the translation below. Per good: `step` = the type's
AABB size x 1.05; `pos.y` = terrain height at `pos`; the item position starts at `pos`. Items 1..7 of a column
each add `step.y` to y. After the 8th item `pos.x -= step.x` and only x of the item position is replaced: y is
not reset, so the next column starts at the height of the previous column's top item. After each good
`pos.x -= step.x` once more and the next good starts on the terrain again.

**Water street boat** [known] S 006d2050: each water street owns one frozen item of the good whose property
name is `Boat` (bytes at S 007fbd48), created hidden (`visible` = false); the shared paddle mesh is
`[data]\items\GO_Paddle01.GR2` (loaded as `.KEX`) and the shared cargo texture `[data]\items\GO_Warez02.dds`,
both loaded by the first water street and reference counted; `boatSize` is the smallest of the three AABB
extents of the boat item [known].

### 3.4 Goods: drawing

`ItemRenderer::Render` S 006cf8a0 [known]: technique from the standard table (§3.11), then three passes of
`item_shader.fx`, begun by index: pass 0 `RenderItem` (plain), pass 1 `RenderSkinnedItem` (animated items,
skipped when the "animated off" switch `+0x74` is set), pass 2 `RenderInstancedItems` (skipped when the
"instanced off" switch `+0xb4` is set); pass names and order [known] `item_shader.fx`.

- **Plain** S 006cf210 [known]: per item type with at least one visible item, the type mesh is copied into the
  dynamic streams (cursors reset when 10000 vertices or 30000 indices would be exceeded) and drawn once per
  visible item with the item's world matrix; the type's texture is bound to stage 0. There is no frustum test
  per item.
- **Instanced** S 006d0090, S 006cfd30, S 006cff10, S 006cf760 [known]: a type is promoted when its plain list
  holds 20 or more items and the shader level is not 0, after the condition held for 5 seconds; it is demoted
  when its instanced list holds 9 or fewer items (or the shader level is 0), again after 5 seconds. Promotion
  and demotion move the whole list; while a type is instanced, new items join the instanced list [known]
  S 006d01e0. The instanced mesh is 40 copies of the type mesh, each vertex extended by 4 bytes whose first byte
  is the copy index; indices of copy `k` are offset by `k * vertexCount`. Visible items are drawn in batches of
  up to 40: the batch's world matrices are set as an array and the first `batch * indexCount / 3` triangles are
  drawn [known] S 006cf480; the array is `INSTANCEMATRICES`, indexed by the copy index [known]
  `item_shader.fx`, [inferred] for the effect method that sets it.
- A boolean CVar per item type in the group `ItemTypes` (named after the type) exists for debugging [known]
  S 006d01e0.

Pixel result of `item_shader.fx` [known, file]: `(ambient + lightColour * N.L * shadow) * texture.rgb`, alpha =
texture alpha with alpha test above 127, then the exploration darkening `CalcFOW`; depth test and depth write
on, no alpha blend.

### 3.5 Street path

`RouteSpline` S 006d7a80 turns a cell path into a curve through the world positions of the cells [known]:

1. **Tangents** `ComputeTangent` S 006d6ff0: for point `i`, `d = P[i+1] - P[i-1]` (first point `P[1] - P[0]`,
   last point `P[n-1] - P[n-2]`); with a fixed height both y values are replaced by it. `tangent[i] = d / |d|`,
   `w[i] = |d|`.
2. **Lengths**: for `i` in order, `w[i] = ApproxSegmentLength(i)` S 006d71a0 and `totalLength += w[i]`.
   `ApproxSegmentLength(i)` is the sum of the 31 chords between the points `EvaluateSegment(i, k / 32)`,
   k = 0..31: the last 1/32 of the segment is not counted. Evaluation of segment `i` reads only `w[i]` (step
   3), and while segment `i` is measured `w[i]` still holds the neighbour distance of step 1, so the measured
   curve is not exactly the final one. For the last point the evaluation returns the point itself and
   `w` = 0.
3. **Evaluation** `EvaluateSegment(seg, t)` S 006d6db0: cubic Hermite between `P[seg]` and `P[seg+1]` with
   `m0 = tangent[seg] * 1.3 * w[seg]`, `m1 = tangent[seg+1] * 1.3 * w[seg]`:
   `p = (2t^3 - 3t^2 + 1) P0 + (-2t^3 + 3t^2) P1 + (t^3 - 2t^2 + t) m0 + (t^3 - t^2) m1` (basis matrix
   [known] S 006d6ab0). `t` = 0 and `t` = 1 return the cell positions exactly. With a fixed height, y is that
   height.
4. **Frame** `EvaluateFrame` S 006d75b0: position as above; tangent = the same combination with the derivative
   basis (`6t^2 - 6t`, `-6t^2 + 6t`, `3t^2 - 4t + 1`, `3t^2 - 2t`), normalised; normal = `n0 + t * (n1 - n0)`,
   the cell normals of the two cells (`TerrainGrid::GetCellNormal`), not normalised; with a fixed height the
   normal is straight up. At `t` = 0 (and for a segment index past the end) the result is the cell position, the
   cell normal and the stored tangent of point `seg`; at `t` = 1 those of point `seg + 1`.

A water street (type 2) is built with the fixed height `ai::map::TerrainGrid::GetSeaLevelHeight(&g_TerrainGrid)` [known]
S 006cd320: the renderer's sea level, the constant -100 of the image times the height scale
(`docs/sim/rendering.md` §2.1) [known] S 00687050. A street is created only for a path of at least 2 cells
[known] S 0069f570.

### 3.6 Street mesh

`StreetDecal::BuildFromSpline` S 006df940 [known]. Let `step = 1 / numSegments`, `W = width`,
`side(frame) = normal x tangent`.

1. `trimStart` = the start flag node exists and has more than one street attached; `trimEnd` likewise for the
   end node.
2. First cross-section: frame at segment 0, `t = step` if `trimStart` else 0. `left = pos - W * side`,
   `right = pos + W * side`.
3. For each spline segment, slices: normally `numSegments` slices ending at `t = step, 2 step, ..`. In segment 0
   with `trimStart`: `numSegments - 1` slices, the first ending at `t = 2 step`. In the last segment with
   `trimEnd` (and not the trimmed first segment): `numSegments - 1` slices, so the mesh ends at `t = 1 - step`.
   The untextured gap at a flag with several streets is covered by the crossing mesh.
4. Per slice, between the previous and the current cross-section:
   - four clip planes: through the two left points, the two right points, the two previous points and the two
     current points, each completed by a third point offset along the frame normals (the planes stand on the
     terrain);
   - collect the terrain triangles inside the AABB of the four corner points
     (`CLandscape::CollectTrianglesInBounds`, level 1) and clip them by the four planes;
   - weld the result into indexed vertices (`DecalMeshBuilder24`) and append them:
     position and normal from the terrain, colour white (ARGB from 1,1,1,1),
     `tangent = (sidePrev + sideCur) / 2`,
     `u = clamp(dot((p - prevPos) / W, tangent) * 0.5 + 0.5, 0, 1)`,
     `v = vAccum + f * texStretch * sliceLength`, where `sliceLength = |pos - prevPos|`,
     `dir = (pos - prevPos) / sliceLength` and, with `uRaw` = `u` before clamping,
     `a = (p - prevLeft) / dot(left - prevLeft, dir)`, `b = (p - prevRight) / dot(right - prevRight, dir)`,
     `f = dot(a + uRaw * (b - a), dir)` (the vertex's fraction along the slice, measured against the left and
     the right edge and blended across);
   - `vAccum += texStretch * sliceLength`.
5. Whenever the pending part plus the next slice would reach `maxBatchVertices` or `maxBatchIndices`, a
   sub-mesh range `{vertexCount, indexCount}` is closed, so one draw batch never exceeds 6000 vertices and 8000
   indices. Ranges are stored only when at least one was closed; the last range is the remainder.

So a street is a strip 2 x `width` = 2.0 world units wide that lies exactly on the terrain triangles; `u` runs
0..1 across (texture clamped in u), `v` advances 0.25 per world unit along (texture wrapped in v; address
modes [known] `street_shader.fx`). The vertex attribute called tangent holds the averaged side vector.

**Crossing** `StreetDecal::BuildJunctionFan` S 006de590 [known]: 7 vertices, 18 indices. Vertex 0 = the node
position, normal up, uv (0.5, 0.5). Vertices 1..6 = the node's corners `k` = 0..5:
`corner[k] = position + crossingRadius * (sin a, 0, cos a)`, `a` = 60, 120, 180, 240, 300, 360 degrees
[known] S 006d1670, initialiser S 007cafc0 with its constants; each corner is snapped to the terrain height
with the terrain normal, except in a direction that holds a water street, where the corner keeps the centre's
height [known] S 006d1310 (`StreetFlagNode::GetCornerPoint`). The water corner returns before the sample, so its
normal slot is not written: it keeps the previous land corner's normal, and a water corner before the first land
corner keeps whatever the stack holds [known] S 006de590, S 006d1310; a land corner's normal is the plane normal of
the terrain triangle under it (S 00687e60);
`uv = ((corner.x - centre.x) / radius * 0.5 + 0.5, (corner.z - centre.z) / radius * 0.5 + 0.5)`. All tangents are
unit X, all colours white. Triangles: (0,2,1) (0,3,2) (0,4,3) (0,5,4) (0,6,5) (0,1,6). The crossing is a flat
hexagon fan, not clipped to the terrain triangles. It is rebuilt when a street is attached or detached and when
the terrain under it changes [known] S 006d1d90, S 006d19d0. The six corner directions are
`(sin 60°, 0, cos 60°)` .. `(sin 360°, 0, cos 360°)` in steps of 60 degrees [known] initialiser S 007cafc0
(multipliers 60, 120, 180, 240, 300, 360 times pi / 180).

**Where a crossing exists** [known]: `StreetSet::CreateFlagNode` S 0069ecc0 has one caller, `AttachFlagNodes`
S 0069eeb0, run on "street added". So a flag circle exists only where a land, upgraded or water street ends. Sea
streets (type 3) never raise "street added" (S 00668c70, S 006695a0, S 00668d60), and `Scene::OnFlagCreated`
S 00682ca0 draws only the flag model: a lone flag and a harbour flag with only sea streets have no circle. Water
streets themselves are drawn as buoy chains (§3.7).

The stone circle under a harbour flag is **not** a crossing: it is the harbour place's own ground plot, the
`GROUND` decal of `Harbour_decal.KEX` that `Harborplace::ctor` S 006db7a0 lays at every harbour cell, owned or not,
flag or no flag ([rendering.md](rendering.md) §3.11 "Harbour place plot") [known]. It is drawn with the house
ground decals, after the streets, so it covers the end of a land street at the harbour flag.

**Flag respawns** [known, decompiled]: flag objects are respawned (four new RNG draws) by `Flag::LinkNavyObject` S 00669e60
(as `z_harbor_flag_00`) and `Flag::UnlinkNavyObject` S 00669eb0 (back to `z_flag_00`), also from `Flag::PostLoad`
S 0066a5f0 on load. The hash shift and the fixed yaw/scale of the flag elements do not depend on the draws.

**Door path** [known]: every building has a short street from its door to its middle: a two-point `CStreet`
(S 006ccc70) from the cell of the entrance flag (flag +0x28) to the building's anchor cell (+0x20), stored at
`S2CG::Building +0x100`. It is made in `S2CG::Building::ctor` S 006ac810 and `Building::Update` S 006abcf0 through
`CreateEntranceStreet` S 006aa7b0; building sites have one too. Its mesh is `StreetDecal::BuildStraight`
S 006e0e30, the kind-0 texture; it has no flag node, so no crossing and no trimming.
`BuildStraight` [known, decompiled]: `d = normalize(toPos - fromPos)` (3D); `sideF = nF x d`, `sideT = nT x d` (unnormalised
cell normals from `GetCellNormal` S 00687270); edge points `pos -+ W*side` (`W` = `<Street width>` = 1.0, a half width: the
strip is 2.0 wide, no door-path special case). Four planes (`Plane::FromPoints` S 006eb9c0, `ClipByPlanes` S 006ed6e0 keeps
`dist >= -0.0001`): left edge, right edge, from-end through `fromPos`, to-end through `toPos`; each completed by a point
offset with the cell normals. No extension or `crossingRadius` trim. Triangles from `CLandscape::CollectTrianglesInBounds`
S 0068a760 (stride 1). UV: `u = clamp(dot((p-fromPos)/W, (sideF+sideT)/2)*0.5 + 0.5, 0, 1)`,
`v = f * texStretch * |toPos-fromPos|`. `street_shader.fx` addresses u Clamp, v Wrap. `Building::CreateEntranceStreet` is
called only from `Building::Update` S 006abcf0 and `Building::ctor` S 006ac810. The path is drawn
while the building is not hidden (`Building::SetHidden` S 006aa320; `CStreet::IsVisibleOrFlag4C` S 006ccdf0)
without a frustum test, with the streets (map layer 2, before the buildings' ground decals of layer 4,
[rendering.md](rendering.md) §3.1), and removed only by `Building::dtor` S 006ab040, so it stays through the
demolition sink.

**Kinds** [known] S 006c3ab0, S 006c39f0, S 006d1290: a street of type 0 is drawn with `texture0` / `normal0`,
a street of type 1 with `texture1` / `normal1`; the switch 0 → 1 moves the street to the kind-1 list and
promotes both of its flag nodes. A crossing is kind 1 (`crossingTexture1` / `crossingNormal1`) when any street
attached to it is of type 1 at the time it is registered (`RegisterCrossing` S 006c3160) or once one of its
streets is promoted, else kind 0. The diffuse texture is bound to stage 0 and the normal map to stage 1. The
upgrade has no animation: `StreetRenderer::PromoteStreetToKind1` S 006c39f0 moves the street and its two
crossings to the kind-1 lists at once [known].

**Build preview** [known] S 006c3250, S 006c3ab0, S 006cd560: a `CStreet` made from a bare cell path (no logic
street) carries `previewDrawMode` 0, 1 or 2. While the byte S 00881f70 is set, streets of the kind-0 list with
mode 1 or 2 are not drawn with the others but collected and drawn afterwards with the pass
`RenderStreetUnderConstruction`, textures of kind 0, and `STREET_COLOR_MODIFIER` = `alphaStreetColor` (mode 1)
or `redStreetColor` (mode 2); the pixel colour is multiplied by it [known] `street_shader.fx`. S 00881f70 is 1
in the image and no code writes it (its only references are the two reads in `DrawStreetList` and
`DrawBuoyList` S 006c3570) [known], so the rule is always on.

The modes come from the street build mode [known] `StreetBuildMode::UpdatePreview` S 0078bbe0,
`CreatePreviewCasters` S 0078b890: when the cursor cell changes, both preview streets are removed and rebuilt
from the paths of the build mode's two result objects, `points1` (planned in this call with the cursor cell
appended to the waypoints) and `points0`. Both are `NNet::StreetConstructorPoints` (0x30 bytes), street
constructors that only record points; each belongs to one `ai::logic::StreetPlanner` of the build mode
(`planner0` +0x10 with `points0` +8, `planner1` +0x14 with `points1` +0xc) [known]. The shorter path (`points0`'s when both have the same number of
cells) becomes a preview street of mode 0. From the longer path the cells from its end back to the last cell of
the shorter path, that cell included, become a second preview street (the whole longer path when the shorter
one is empty): mode 1 (alpha) when the longer path is `points1`'s, mode 2 (red) when it is `points0`'s. Either
street needs at least 2 cells. Both previews take the street type of the longer path, so a longer path of
kind 2 makes both a `WaterStreet`.

**What the two paths hold** [known] S 0078b220, S 0078b510, S 0078be80, S 0078bbe0:

- `points0` is `planner0`'s accepted plan: every click extends it by `PlanSegment` (S 0078b220,
  [ingame-ui.md](ingame-ui.md) §3.5), and after every street command of the player
  (`StreetBuildMode::OnPlannerCommand` S 0078be80, with the player's shared planner active and its path valid)
  `RebuildPath` S 0078b510 rebuilds it through the waypoints, with the shared planner's street id at
  `points +0x28`.
- `points1` is `RebuildPath` through the waypoints plus the cursor cell.
- `RebuildPath(planner)` S 0078b510 re-plans from scratch: it cancels the planner's construction; takes as
  reference street the street of the player's shared planner while its construction is active (stored at
  `points +0x28 / +0x2c` and passed to `CanStreetStepTo` / `CanStreetPassCell`); runs full searches
  (`PlanSegment` with `fullSearch`) from `waypoints[0]` to `waypoints[1]`, `waypoints[2]`, … until one returns
  ≠ 1; and then `ExtendTo` for each remaining waypoint while the planner cannot complete. Neither path is copied
  from the simulation, so both follow the current passability.

So the tail is drawn red when `points1` is the shorter path, i.e. when the cursor lies on the plan: the red
part is what a click there would cut back (`CommitPathTo`); the alpha tail is the extension a click would add.

### 3.7 Water streets and sea routes

**Buoy chain** `StreetBuoy::BuildBuoyChain` S 006e1e30 [known]: for each spline segment the frame at `t = 0.5`;
two copies of the buoy model (global mesh `g_StreetBuoyModel`) at `mid - side * buoyDistance` and
`mid + side * buoyDistance`, `side = normal x tangent`. The copies are translated only, not rotated.
`(n - 1) * 2` buoys for a path of `n` cells; sub-mesh ranges as for streets. Texture `buoyTexture`; passes
`RenderBuoys` and, for previews, `RenderBuoysUnderConstruction`. The model is
`[data]\map\objects\street_buoy.GR2` (loaded as `.KEX`, scale 1, 48-byte street layout), loaded by the first
`StreetBuoy` and reference counted [known] `StreetBuoy::ctor` S 006e2350.

**Sea route** `RouteDecal::BuildFromSpline` S 006e2450 [known]: the same slicing with `routeNumSegments` slices
per segment and half width `routeWidth`, without the trimming at flags (the first cross-section is at `t` = 0
and every segment has all its slices). Each slice is one quad, not clipped to terrain: vertices previous left,
previous right, current left, current right, with the frame normal of their cross-section, colour white,
tangent = the averaged side vector; indices (0, 1, 2) (3, 2, 1) plus the running base; `u` and `v` by the
street formulas with `routeWidth` and `routeTexStretch`, `vAccum += routeTexStretch * sliceLength`; lengths are
taken with the table square root `Math_FastSqrt` S 006e8a20 (256-entry table S 007fd118), not the exact root. The quad
lies at the spline's fixed height [inferred]: the spline of a sea route is built by `S2CG::ShipRoute::ctor`
S 006d2430, which was not read.

**When a sea route is created for the renderer** [known]: the logic callback `OnSeaRouteCreated` S 00683040 (the
renderer's slot +0x90, [rendering.md](rendering.md) §3.2) fires only at world load, from `NavyShipRoute::PostLoad`
S 005b6af0, and from the debug route tool. There is no "connected" condition (no check that the route joins two
harbours' water). The ribbon (the route decal) is built only for a path of more than one cell; the end buoy is placed
only when both harbour references of the route are valid.

**Route texture animation** `StreetRenderer::DrawRoutes` S 006c29a0 [known]: with `x = routeTexSpeed * time`,
`frame = floor(x) mod routeTexCount`, `next = frame + 1` (0 after the last), `mix = x - floor(x)`: texture
matrix 0 scales u by `1 / routeTexCount` and offsets it by `frame / routeTexCount`; matrix 1 the same with
`next`; `ROUTE_TEX_MIXER = mix`. The route texture is therefore a horizontal strip of `routeTexCount` (16)
frames, cross-faded at `routeTexSpeed` (10) frames per second. `frame` is taken by truncation. The matrices
are bound with the route texture on stages 0 and 1, and the shader's result is
`lerp(tex(stage 0), tex(stage 1), ROUTE_TEX_MIXER)` [known] `street_shader.fx`. `time` is the first argument
of `StreetRenderer::Render` S 006c3ab0. A sea route is drawn in every frame in which it passes the frustum
test (§3.8). `route_texture.tga` is 2048 x 128: 16 frames of a dark teal wake whose alpha is at most 75 / 255
(mean 20) [known, file]; the water is drawn after the streets (`Scene::RenderPasses` S 0067eb20 →
`RenderObjectsAndWater`, [rendering.md](rendering.md) §3.1), so a sea route is barely visible by its data.
Water-street buoys sit at the segment midpoints at the spline's height, the sea level; a water street across a
single water cell between two shore cells puts them under the shore, where they cannot be seen [known]
S 006e1e30.

### 3.8 Street drawing order

`StreetRenderer::Render(time, shadows, lowQuality, frustum, depthBias)` S 006c3ab0 [known]:

1. shift the near plane of the projection by `depthBias` (`CGraphicDevice::SetNearPlaneOffset`; 0.1 unless the
   CVar "Street/DepthBias" changes it, `docs/sim/rendering.md` §2.4): streets are pulled toward the camera in
   depth instead of using a depth-bias render state. The offset is added to the camera's near plane of 1.0
   ([camera-input-cutscenes.md](camera-input-cutscenes.md) §3.1), so the street pass is projected with a near
   plane of 1.1. With the far plane (500) much larger than the near plane, a point at view depth `d` is then
   depth-tested like a point at about `d / 1.1` of the other passes: a pull of about 9 % of the view depth, about
   3.4 units at 40 units (3.36 with the far plane 500; `d / 1.1` alone, the infinite-far-plane value, gives 3.6),
   not a fixed 0.1 units [known] S 006c3ab0, S 006898f0, S 006890f0, S 004d9e10, S 004d9300, S 006e97e0,
   S 007867c0. This is what
   keeps the unclipped crossing fans (§3.6) visible where the terrain bulges through them;
2. technique `Select(lowQuality, shadows)`; pass `RenderStreet`: kind-1 streets, kind-0 streets, then crossings
   of kind 1 and crossings of kind 0 (`DrawCrossings` S 006c3030);
3. pass `RenderStreetUnderConstruction`: the alpha list, then the red list (each only when not empty; both
   lists are emptied after drawing);
4. pass `RenderRoutes`: sea routes;
5. near plane offset back to 0, technique selected again;
6. pass `RenderBuoys`: buoys; then `RenderBuoysUnderConstruction` with the alpha and the red colour for the
   water-street previews collected while drawing the buoy list.

Every list entry is skipped unless its world AABB is in the frustum or its always-visible flag is set
(`CStreet::IsVisibleOrFlag4C` S 006ccdf0) [known]. All street geometry is streamed each frame into one dynamic
buffer in batches of at most 6000 vertices and 8000 indices; a mesh that alone exceeds a limit is streamed
sub-mesh range by sub-mesh range [known] S 006c3250.

Render states [known, `street_shader.fx`]: streets, previews and routes: depth test on, depth write off, alpha
blend (source alpha, inverse source alpha); buoys: the same with depth write on.

### 3.9 Projected decals

**Orientation** `DecalProjector::SetOrientation(pos, normal, angle)` S 004efb60 [known]: with
`d = dot(normal, unitX)`: `d > 0.99`: `uAxis` = minus the up vector, rotated about X by `angle`; `d < -0.99`:
`uAxis` = the up vector, rotated about X; otherwise `uAxis` = unit X rotated about Y by `angle`. Then
`vAxis = uAxis x normal` and `uAxis = normal x vAxis` (with the normal straight up and `angle` = 0 this gives
`uAxis` = unit X, `vAxis` = unit Z, the constructor's defaults). Neither axis is normalised.

**Footprint** [known] S 004f0390: four clip planes `±uAxis` at `width / 2` and `±vAxis` at `height / 2` from
the centre.

**Mesh** `CLandscape::ProjectDecal(projector, clip, normalOffset, level, flatten, minHeight)` S 0068aad0 [known]:
collect the terrain triangles inside the projector bounds, clip them by the four planes when `clip` is set, then
`DecalProjector::BuildVertices` S 004efe20: three unshared vertices per triangle; per vertex

```
d  = p - centre
u  = uvOffset.x + uvScale.x * (dot(d, uAxis) / width  + 0.5)
v  = uvOffset.y + uvScale.y * (1 - (dot(d, vAxis) / height + 0.5))
p += normal * normalOffset           // the vertex's terrain normal
colour = ARGB(color)
```

A vertex whose y is below `minHeight` is first raised to `minHeight` with the normal straight up (comparison
`y < minHeight` [known] disassembly S 004eff10..S 004eff1a); `u` and `v` are taken after that and before the
normal offset. With `flatten`, all vertices get the highest y of the decal (after the offset) and the up
normal. A triangle list without triangles sets `vertexCount` = 0.

The settler blob passes `minHeight` = 3.4028235e38 (float at S 007e56e0, bytes `ff ff 7f 7f`) [known]
S 00690bd0, so every vertex of a blob is raised to that height: as read statically the blob never appears on
the ground [inferred]. [TODO] not established: whether a blob is visible in the running game at shadow level
1 to 3; a screenshot at those levels settles it.

**Drawing** `DecalRenderer::Render` S 004df400 [known]: per texture, every enabled projector with vertices is
copied into the 12000-vertex stream and drawn as a triangle list, the buffer being flushed when full. Shader
`decal_shader.fx`: fixed function, `texture * vertex colour` for colour and alpha, **additive** blend (source
alpha, one), depth test on, depth write off, no lighting, no fog-of-war term, texture clamped. The scene draws
the decal pass with cull mode 1 (`docs/sim/rendering.md` §3.1).

**Users.**

| User | Texture index | Size | Colour | Call |
|---|---|---|---|---|
| Selection marker | the style (0..2) | `width = height = r` | 1, 1, 1, 1 | `ProjectDecal(decal, clip = 1, 0.3, 1, 0, waterLevel)` |
| Blob under a settler | 0 | `0.7 x 0.7` at creation, then from the animation bounds' size [inferred] | 1, 1, 1, 0.75 | `ProjectDecal(decal, clip = 0, 0.05, 1, 0, 3.4e38)` |

- Selection marker [known] S 006b0b50, S 006b0d00, S 006890c0: uv rectangle (0,0)-(1,1), so a style is a whole
  texture of `decals.xml`; a marker whose style changes gets a new projector. Target, in this priority: a valid
  ship id: centre = the ship position, `r` = the marker's radius field (11 for a ship, `SetTargetShip`
  S 006b0cd0); else a cell inside the vertex grid:
  centre = the vertex position of the cell, `r` = the radius field; else a valid object id: centre and `r` from
  the building's bounds (`Bounds_GetCenterAndMaxXZExtent` S 006b0bc0: `r` = the larger of the x and z sizes of
  its box); `r` defaults to 1. `r` is the full side of the square (`BuildVertices` S 004efe20); a flag, a street
  cell and a clicked cell get 4 (`PushSelectionToScene` S 00615bb0). Styles: 1 `buildingselect.dds`, 2
  `catapultTarget.dds` (an enemy building) ([rendering.md](rendering.md) §3.14). Projection straight down: the
  normal is `g_DefaultMeshNormal` (0, 1, 0) (S 00882864) and the start axis `g_Vec3_UnitX` (S 00882858), so
  `SetOrientation` takes the rotation-about-Y branch (S 004efa20): uAxis = (cos θ, 0, −sin θ), vAxis = uAxis × normal
  = (sin θ, 0, cos θ); u = dot(p − c, uAxis) / r + 0.5, v = 0.5 − dot(p − c, vAxis) / r, so at θ = 0 the texture's
  v grows toward −z. The footprint is the turned square, cut by the four side planes (clip = 1) [known] S 004efb60,
  S 004efa20, S 004efe20;
  rotation `angle = timeInfo[1] * 0.025132744` radians (one turn per 250 s of game time: `timeInfo[1]` is the
  scene's accumulated simulation time, [rendering.md](rendering.md) §3.14), 0 without a time argument.
- Settler blob [known] S 00690bd0: exists only while the global S 0088d6bc is set (shadow level 1 to 3,
  `docs/sim/rendering.md` §3.13), the character is visible and its movement is active; centre = the character
  position, or the centre of the animation bounds in animation states 4..6 [inferred], projected along the terrain normal,
  rotated by the movement heading (`movement +0xe4`). The projector's `enabled` is set each frame to "character
  visible and movement active". The creation size is the float pair at S 0088165c (bytes `0.7, 0.7`), the uv
  scale the pair at S 00881664 (`1, 1`), the uv offset the pair at S 0088d514: zero in the image, and its only
  reference is the read in S 00690bd0 [known], so (0, 0).

House ground decals (`ai::render::HouseDecalRenderer`) are meshes, not projected decals: `house_decal.fx` lights
them per vertex, multiplies by the texture and the exploration term, alpha blended without depth write, depth test
`LessEqual`, no depth bias [known, file]. Their owners are buildings, ruins and harbour places; how a mesh is clipped
onto the terrain (`GroundDecalMesh::Build` S 006da2a0), and why it cracks on slopes, is in
[rendering.md](rendering.md) §3.9 "Ground decal". `HouseDecalRenderer::Render` S 006b3fe0 draws every decal, culled
only by the frustum (the fog of war comes from the shader), in the buildings pass after the streets [known].

### 3.10 Sky dome

Geometry `SkyRenderer::BuildGeometry(inner = 5000, outer = 5010, n = 64, texU = 7, texV = 7, sunSize, moonSize)`
S 006af490, called from the constructor S 006af960 [known; the x / z grid step from the disassembly, the
decompiled C being damaged there]. The vertex stream is created under the name `SkyPlane`:

- `(n + 1)^2` grid vertices + 8 = 4233 vertices; `2 n^2 + 4` = 8196 triangles.
- Grid: `x = col * (2h / n) - h`, `z = row * (2h / n) - h` with `h = sqrt(outer^2 - inner^2)` (about 316.4),
  so both run from `-h` to `+h` in `n` steps [known] disassembly S 006af531..S 006af6cd;
  `y = -(x^2 + z^2) / outer`; `u = texU * col / n`, `v = texV * (1 - row / n)`; colour white with
  `alpha = 1 - ((c - col)^2 + (c - row)^2) / (n + 1)^2`, `c = (n + 1) / 2` (1 in the middle, about 0.75 at the
  middle of an edge, 0.5 at a corner).
- Then two quads of 4 vertices in the xy plane at z = 0, corners `(±sunSize, ±sunSize)` and
  `(±moonSize, ±moonSize)`, uv (0,0) (1,0) (0,1) (1,1), colour 0xffffffff.
- Indices (u16): per grid quad with first vertex `i = row * (n + 1) + col`: `(i, i + n + 1, i + 1)` and
  `(i + 1, i + n + 1, i + n + 2)`; then per extra quad with first vertex `b`: `(b, b + 1, b + 2)` and
  `(b + 1, b + 3, b + 2)`.

Drawing `CEnviromentMgr::RenderSkydome(enableFog)` S 00683e50 [known]: technique `Select(false, false)`, effect
begun, `DAYTIME_INTERPOLATION` set, world matrix set, streams bound; stage 0 = the texture of the skydome
whose index is the first dword of the map environment data (`docs/sim/rendering.md` §3.13), with a texture
matrix whose elements 0, 1, 4, 5 are `cos a, sin a, -sin a, cos a`; stage 1 = the skydome of the manager's
secondary index with its own rotation matrix, or, when that index is -1, the first texture and matrix again;
fog switched as requested; pass `Skydome` draws the grid only (`triangleCount - 4` triangles,
`vertexCount - 8` vertices) S 006af150; textures unbound, fog off, effect ended.

- Rotation [known] disassembly S 00683e6f..S 00683e85: `a` = the skydome's `rotation` (instance `+0x20`)
  `* pi / 180`, so the attribute is in degrees.
- World matrix [known] disassembly S 006af28a..S 006af2bb: identity with the translation
  `(p.x, p.y + 15, p.z)`, `p` = `SkyRenderer +0x40` (the constant 15 is the double at S 007e2aa8). `p` is filled
  by `SkyRenderer::Update` (below). The dome is not rotated or scaled.
- Sun and moon are built and never drawn. `SkyRenderer::InitEffect` S 006af300 stores the handle of the pass
  `Sun` in `SkyRenderer.hSunPass` (+0x2c) and `BuildGeometry` adds the two quads (8 vertices, the last 4
  triangles), but no function of the program reads `hSunPass`: no `SkyRenderer` method (S 006af120..S 006af960)
  and none of the functions that hold the `SkyRenderer` pointer begins that pass or draws those triangles
  [known for the write; inferred for the absence of a reader, from a search of the whole decompiled program].
  This is presentation only.

Shader `enviroment_shader.fx` [known, file]: vertex: `uv0 = uv * TextureTransform[0] + time * (0.015, 0.005)`
(the cloud drift, `time` = `g_Timer.y`), `uv1 = uv * TextureTransform[1]`. Pixel, technique `Default`: both
passes compile the shader with `combineTextures = false`, so the result is **texture 0 only**: the vertex
colour (the rim alpha), the second texture and `DAYTIME_INTERPOLATION` do not reach the picture. States: depth
test less-equal, no depth write, alpha blend; pass `Sun`: depth function always, no culling.

`SkyRenderer::Update(a, b)` S 006af210 [known]: when the device has a provider object (`CGraphicDevice +0x1b4`)
its virtual slot +8 fills the dome position `+0x40` and `daytimeInterpolation` = `a`; otherwise the position is
the vector at S 0088f1b0 and `daytimeInterpolation` = `b`. [inferred] the provider is the camera and the vector
it returns the eye position, which keeps the dome centred on the viewer. [TODO] not established: the class
behind `CGraphicDevice +0x1b4` and its slot +8; read the writer of that field. The interpolation value does not
reach the picture in the `Default` technique.

### 3.11 Technique selection and shared shader constants

**Technique table** `ShaderTechniqueTable::Init` S 004ef7b0 [known]: eight technique handles looked up by name,
-1 when absent: 0 `ffp_min`, 1 `ffp`, 2 `shader_2_0_vs_only`, 3 `Default`, 4 `NoShadow`, 5 `LowDefault`,
6 `LowNoShadow`, 7 `PFXEditor`.

**Selection** `Select(lowQuality, shadows)` S 004ef880 [known], `L` = effective shader level:

```
if L < 2: shadows = false
index = 1                          if L < 1      (fixed function)
      = 2                          if L == 1     (vertex shaders only)
      = 3 + 2 * lowQuality         if shadows    (Default / LowDefault)
      = 4 + 2 * lowQuality         otherwise     (NoShadow / LowNoShadow)
while handle[index] == -1: index -= 1
```

`L = min(configured cap, hardware level)` (`CGraphicDevice +0x4d4` CVar "Shader/MaxShader", `+0xf8`)
[known] S 004d4ab0.

**Shared constants.** Every effect declares the parameters of `shared.inc` as `shared`; the engine resolves
them by semantic each time an effect is created (the handles are global and serve all effects) and pushes its
cached values before a technique is used, only those the technique uses unless the CVar
`ui/AlwaysSetSharedParameter` is set [known] S 004e9600, S 004e9810. Order of application and type:

| # | Semantic | Type | Content |
|---|---|---|---|
| 0 | `VIEW` | matrix | view |
| 1 | `PROJECTION` | matrix | projection |
| 2 | `VIEWPROJECTION` | matrix | view x projection |
| 3 | `TEXTURE_ATTRIBUTES` | float4[8] | per stage `(width, height, 1 / width, 1 / height)` of the bound texture [known] S 004e8a40 |
| 4 | `TEXTURE_TRANSFORM` | matrix[8] | per stage, the matrix passed when the texture was bound (identity when none) [known] S 004e7520 |
| 5 | `ALIGNVIEW` | matrix | camera-facing rotation (billboards) [inferred from the name] |
| 6 | `CAMERA_FOCUS` | float2 | depth-of-field focus `(distance, 1 / range)` [inferred from `shared.inc`] |
| 7 | `TIMER` | float4 | `CGraphicDevice +0x300`, written by `BeginRendering` S 004d78a0: `.x` = the scene's frame delta, `.y` = its accumulated game time in seconds (scaled by the game speed, standing in a pause), the time of every animated shader [known] ([rendering.md](rendering.md) §3.13) |
| 8 | `CAMERA_POSITION` | float4 | eye position |
| 9 | `FOG_SETTINGS` | float4 | fog start, end, `end - start`, `1 / (end - start)` (0 when the range is not positive) [inferred from the four device fields written together, S 004d3ae0] |
| 10 | `MAIN_LIGHT` | float4 | light direction (pointing from the light) |
| 11 | `LIGHT_COLOR` | float4 | light colour |
| 12 | `AMBIENT` | float4 | ambient colour |
| 13 | `SHADOW_INTENSITY` | float | brightness of a shadowed pixel's direct term |
| 14 | `SHADOW_SCALE` | float2 | `.y` = depth bias of the shadow test |

Set per draw, not through the table above [inferred from the mapped names of S 004e8ab0..S 004e8c80; their
handles are resolved with the others, known S 004e9600]: `WORLD`, `INSTANCEMATRICES`, `INSTANCEVECTOR0..3`,
`MATERIAL`. Array sizes [known] `shared.inc`: `MAX_BONES` = 50 matrices, `MAX_VECTORS` = 100 vectors each,
unless an effect defines them before the include.

[TODO] not established: the exact content of `TIMER.z`, `.w` and of `CAMERA_FOCUS`; read the writers of the
cached values at S 00887460..S 00887490.

**Loading an effect** [known] S 004ec060, S 004ebad0, S 004eb8f0, S 004ecba0: effects are cached by file name in
a registry; the source is `<fx directory>\<name>` read through the decrypting file reader and compiled with the
D3DX effect compiler (includes resolved by the program's own include handler, S 004ec4a0). The compiled blob is
cached as `<Local AppData>\SAdK\<file name><shader profile name><define>v21` and reused while it is newer than
the source; the effect is always created from that cache file. A compile error shows an Abort / Retry / Ignore
box: Abort ends the program, Retry compiles again, Ignore goes on with the cache file as it is. A program whose
load failed stays registered. `ShaderProgram_GetOrCreate` and `ShaderProgram_PreloadNext` S 004ec910 pass no
define [known]. [TODO] not established: where the `POSTFX` define of `shared.inc` is supplied; the only path
that carries a define is `CShaderProgram::Reload(forceRecompile, defineName)` S 004ec260; read its callers
S 004ec340, S 004ec480, S 004ec490.

### 3.12 Textures, the texture atlas, resources

**Texture files** `CTexture::CreateFromFile(path, singleLevel, defaultPool, fullQuality)` S 004e80d0 [known]: the
path is lower-cased; a path containing `.bmp` is read raw, every other file through the decrypting reader; the
bytes go to the D3DX loader (`CreateD3DTexture` S 004e79f0), so the formats are those D3DX reads (the install
uses `.dds` and `.tga`). Mip chain [known] S 004e79f0: one level when `singleLevel`, else the full chain. Unless
`singleLevel` or `fullQuality`, the texture quality value `q` (`CGraphicDevice +0x10`) drops the `q` largest
mip levels of a file that has mips, or loads a file with one level at `width >> q`, `height >> q`. `defaultPool`
selects the default pool, else the managed pool; managed textures also get the global texture LOD (S 00887424).
With the null-texture switch S 008872e2 every texture is one shared 2 x 2 dummy. Each `CTexture`
created through `CResourceMgr::CreateTexture` is a new object: there is no engine-wide cache by path; sharing
is done by the owners (for example `ItemMgr::GetOrLoadTexture`) [known] S 004db310, [inferred] for the owners.

**Texture atlas** `S2CE::CTextureAtlas` [known] S 004ee7e0, S 004ee1d0, S 004ee710, S 004ee420: a run-time
packer, not a file format.

- `CreateTexture(width, height)`: one A8R8G8B8 texture with a single mip level; root node = the whole area.
- `AddImage(image)`: inserts a rectangle of exactly the image's size and copies its pixels; returns a 1-based
  region id, 0 when it does not fit.
- Insert at a node (`{x, y, w, h, regionId, child0, child1}`): fail when the node is smaller in either
  dimension or already used; an exact fit takes the node; otherwise, unless the node was split before, split
  it: with `dw = w - width`,
  `dh = h - height`, if `dh < dw` child0 = `(x, y, width, h)` and child1 = `(x + width, y, dw, h)`, else
  child0 = `(x, y, w, height)` and child1 = `(x, y + height, w, dh)`; then insert into child0, and into child1
  when that fails.
- `GetRegionUV(id)`: `uvOffset = (x / W, y / H)`, `uvSize = (w / W, h / H)`. No padding and no half-texel inset
  are applied here.

Users: the settler colour ramp atlas (`CCharacterMgr::LoadFromXml` S 00695130, `docs/sim/animation-models.md`),
the in-game avatar and the lobby avatar colour slots [known] callers of S 004db500.

**`S2CE::CResourceMgr`** (singleton, getter S 004dab50) [inferred from the mapped names, known for the three read]: a
factory and registry of device resources: textures (0x70-byte objects), vertex streams (0x4c), index streams
(0x20), texture atlases (0x54), render targets, cube textures, shader programs. Every created object is
registered for device-lost and device-reset notification; `AcquireShaderProgram(name)` is the only creator
that returns a shared object. The parsed scene file (`KScene_LoadFile`) behind meshes, animated objects and
animations is shared through `ai::rendering::SharedResourceCache::Acquire` S 004ef660 by file name and a
52-byte load key (the coordinate system argument); entries are reference counted and a failed load is cached as
a null object [known]; callers `CMesh::Load` S 0076e0d0, `CAnimatedObject::Load` S 0076b4a0,
`AnimResMgr::LoadAnimation` S 004de400.

**Resource names.** A path starting with `[data]` is under the game's `data` directory; code and data that name
a `.GR2` / `.gr2` mesh load the `.KEX` of the same name (`docs/sim/animation-models.md`); a material names its
texture by file name only, resolved in the directory of the mesh file [known] S 0069dbe0.

**Vertex streams** `CVertexStream::Create(count, dynamic, layout)` S 004e5330 [inferred from the mapped
comment]: dynamic streams are write-only buffers refilled every frame (streets, decals, plain items,
particles); static ones live in the managed pool.

### 3.13 Device capabilities used

What the renderers of this document ask of `S2CE::CGraphicDevice` (Direct3D 9) [known] for the calls read,
[inferred] from the mapped names for the rest:

- three shader levels (fixed function, vertex shaders only, shader model 2.0) with a configurable cap;
- one directional light and one ambient colour, linear distance fog with start and end (fixed-function fog
  states and the `FOG_SETTINGS` constant) S 004d3ae0;
- cull mode, alpha blend, alpha test with reference value, colour-write masks, a stencil mode that prevents
  overdraw, one user clip plane (the reflection view), viewport;
- a near-plane offset added to the projection (`SetNearPlaneOffset` S 004d9e10): the only depth bias mechanism
  used for streets and house decals;
- 8 sampler stages with a per-stage texture matrix and size record; render targets and a depth texture for
  the shadow map; cube textures;
- up to 50 instance matrices and 4 x 100 instance vectors per draw (shader constants);
- 16-bit index buffers throughout (every mesh builder here writes u16 indices).

### 3.14 Block culling

`GridQuadTree` [known] S 006daf20, S 006da9f0, S 006db440, S 006db220, S 006dac90:

**Build** (once, when the terrain blocks are created): recursive over the block rectangle `(x0, y0)-(x1, y1)`:
a single block is a leaf whose bounds are the block's AABB merged with the AABB of its objects when it has
any; a strip one block wide splits in two; any other rectangle splits in four at `mid = (lo + hi) / 2`
(integer); an inner node's bounds are the union of its children. `RefitNode` / `RefitFromRoot` recompute bounds
after terrain or object changes [inferred].

**Cull** per view `Cull(blocks, eye, planes, planeCount, lodParam, out, maxCount)`:

1. reset the visible rectangle, depth range and merged bounds; output budget = `maxCount`, or all blocks when
   negative; the horizon occluder is used only when the view direction's y is above -0.2 (not looking steeply
   down) and an occluder exists;
2. per node from the root: stop when the budget is 0; reject when the AABB is entirely behind any frustum
   plane (positive-vertex test) and hide the whole subtree; reject likewise when the occluder reports the AABB
   hidden;
3. classify the AABB against all planes: a leaf, or a node entirely inside, is collected whole
   (`CollectVisible`); otherwise the four children are visited in the order given by the node's order bits.
   `SelectNearestChild` S 006dad30 sets them, for every inner node that passed the tests, to the index `n` of
   the existing child whose AABB centre has the smallest squared distance to the eye (the first one on a tie);
   the order is row `n` of the table at S 007fc1b8 [known, bytes]: `n` = 0: 0, 1, 2, 3; 1: 1, 0, 3, 2;
   2: 2, 0, 3, 1; 3: 3, 1, 2, 0 (nearest first, the diagonally opposite child last);
4. for every node that passed, the farthest AABB corner along the view direction updates the min / max view
   depth (clamped at 0).

The output is the list of visible block indices; the depth range and the visible rectangle feed the shadow and
water code [inferred]. Streets, crossings and routes are culled individually against the same frustum (§3.8);
goods are not culled (§3.4); map objects are culled with their block (`docs/sim/rendering.md` §3.11).

### 3.15 The effect files

`[data]\gfx\fx_20\`, 42 `.fx` files and `shared.inc` [known, files]. Unless noted, an effect has the six
techniques (`house_flag`, `house_soldierflag`, `house_decal`, `gate_shader`, `terrain_shader` and `water_shader` lack `shader_2_0_vs_only`) `ffp`, `shader_2_0_vs_only`, `Default`, `NoShadow`, `LowDefault`, `LowNoShadow`; "std" below means
the common pixel formula `CalcLight` → `CalcColor` → `CalcFOW` of `shared.inc`:

```
rgb = (ambient + c * shadow) * tex0.rgb        c = per-vertex lightColour * saturate(N . -L), or a per-pixel term
a   = tex0.a
rgb = lerp(noise(worldUV * 16) * rgb, rgb, explored)   after rgb *= explored;  explored = sampler 3 alpha
```

Sampler roles common to all [known, `shared.inc`]: 0 diffuse, 1 second map (normal, palette, second layer),
3 the exploration / world texture addressed by world xz through `TextureTransform[3]`, 5 the shadow map with
`TextureTransform[5]`, 6 the noise texture.

| File | Vertex input | Own parameters | Computes |
|---|---|---|---|
| `item_shader` | pos, normal, uv (+ instance index, or skin) | - | std; alpha test 127; passes `RenderItem`, `RenderSkinnedItem`, `RenderInstancedItems` |
| `street_shader` | pos, normal, colour, uv, tangent | `ROUTE_TEX_MIXER`, `STREET_COLOR_MODIFIER` | streets: light vector into tangent space, `N` from normal map (sampler 1), std with `c = lightColour * N.L`, optional colour modifier; routes: lerp of two frames; buoys: per-pixel `N.L`; 5 passes; techniques `ffp`, `Default`, `NoShadow`, `LowDefault`, `LowNoShadow` |
| `decal_shader` | pos, normal, colour, uv | - | fixed function `tex * colour`, additive; technique `Default` only |
| `house_decal` | pos, normal, uv | - | std, alpha blend, no depth write; no `shader_2_0_vs_only` |
| `enviroment_shader` | pos, colour, uv | `DAYTIME_INTERPOLATION` | sky (§3.10); techniques `ffp`, `Default`; passes `Skydome`, `Sun` |
| `mesh_shader` | pos, normal, uv | - | std with alpha forced to 1; extra technique `PFXEditor` |
| `line_shader` | pos, colour (FVF) | - | unlit coloured lines, point size 4; technique `Default` |
| `infomap_shader` | pos, uv + instance vector | `COLOR` | build-placement icons: camera-facing quads from `INSTANCEVECTOR0`, `tex * colour`; `ffp`, `Default` |
| `rain_shader` | pos, uv | - | weather streaks, `tex` with alpha blend; `Default`, `ffp` |
| `particle_shader` | pos, colour, uv, second uv | `TANGENT_LIGHT_VECTOR`, `VOLUME_MIN`, `VOLUME_MAX`, `VOLUME_CENTER`, `VOLUME_EX` | particles, optional normal-mapped lighting from sampler 1; `Default`, `ffp` |
| `terrain_shader` | pos, normal, colour, 3 uv, tangent | `WATER_HEIGHT` and material | terrain layers and transitions (`docs/sim/rendering.md` §3.4); also `ffp_min` |
| `water_shader` | pos, normal, 3 uv | `WATER_COLOR`, `WAVE_COLOR`, `OPACITY`, `REFLECTION_FACTOR`, `REFLECTION_NOISE`, `FFP_OPACITY` | water surface (`docs/sim/rendering.md` §3.5) |
| `groundcover` | pos, normal, tangent, colour, 3 uv | `GRASS_PARAMETER` | grass shells; `ffp`, `Default`, `LowDefault` |
| `house_shader` | pos, normal, 3 uv | `TEXTURE_ATLAS_OFFSET`, `COLOR_INDEX_SCALE`, `COLORMAP_OFFSET` | buildings with colour map variations |
| `house_flag` | pos, normal, uv | `FLAG_COLOR`, `FLAG_TEXTURE_OFFSET` | waving building flag (`CalcFlagVertexPos`), owner colour |
| `house_soldierflag` | pos, normal, 2 uv | `FLAG_COLOR` | military flag (`CalcBigFlagVertexPos`), owner colour |
| `skin_color_mesh` | skinned | `TEXTURE_ATLAS_OFFSET`, `COLOR_INDEX_SCALE`, `PLAYER_COLOR` | settlers: index map → colour ramp atlas, specular |
| `donkey` | skinned | `PLAYER_COLOR` | donkey, std with player colour |
| `animals` | skinned | - | std, alpha test |
| `ships` | skinned and rigid | `PLAYER_COLOR`, `PLAYER_COLOR_WEIGHT` | `tex.rgb * lerp(1, playerColour * 1.8, tex.a)` |
| `border_shader` | instanced | `PLAYER_COLOR` | territory posts, owner colour |
| `flag_shader`, `harborflag_shader` | instanced | `FLAG_COLOR` | street flags, waving, owner colour |
| `doodads_shader`, `signs_shader`, `rock_shader`, `rock_shader2`, `stone_shader`, `weed_shader` | instanced | - | std variants (stone adds a specular term, weed uses a constant light term, rock2 a vertex colour) |
| `tree_shader`, `tree_shader2`, `tree_shader_winter`, `tree_shader_willow` | instanced | wave constants | std with wind sway |
| `ice_shader`, `waterlily_shader`, `waterplants_shader`, `duck_shader` | instanced (+ vertex colour) | movement constants | floating objects with bobbing or circling motion |
| `gate_shader` | pos, normal, uv | distortion constants | the gate with an animated distorted portal texture; no `shader_2_0_vs_only` |
| `shadow` | all input kinds | - | depth of every object class into the shadow map; `Default`, `ffp`, `HWShadowMap` |
| `postprocess` | screen quad | `BLOOM_PARAMETER`, `BLUR_PARAMETER`, `FILL_COLOR` | downsample, blur, bloom, depth of field; `BlurAndBloom`, `ffp` |
| `ui_shader`, `ui_graphshader` | screen vertices | `SCREEN_SIZE`, `TRANSFORM`; `GRAPH_*` | HUD quads and text; statistic graph lines; `Default` |

The `ffp` techniques use the fixed-function macros of `shared.inc`: stage 0 `texture * diffuse * 2`, stage 3
the exploration texture with camera-space texture coordinates [known, file].

---

## 4. Update order

**At program start** [known]: `CApplicationEx::InitEngineLayer` S 00405590 creates the `DecalRenderer`
(`ai::render::DecalRenderer::CreateInstance` S 004dfbd0), whose constructor loads `decals.xml` and the decal textures
(S 004df850). The decal renderer is not rebuilt per match.

**On load / match start**, `Scene::Init` S 006824c0, in this order [known]:

1. `[data]\settings\graphics.xml` is opened; when it cannot be opened nothing below runs. Once per program run
   (latch byte S 0088ca6a): `MapRender_LoadSettingsXml` S 00688170 → `ai::gfx::StreetRenderer::LoadConfigXml` S 006c3f10
   for the `<Street>` element, and `Env_ParseEnvironmentXml` S 00684be0 for `<Enviroment>` (sun and moon size,
   skydome definitions).
2. `Env_CreateEnviromentMgr` S 00685230: the `CEnviromentMgr` constructor S 00685070 creates the `SkyRenderer`
   (geometry built once) and then the skydome instances.
3. `CMapRenderer::CreateInstance`: its constructor S 006890f0 creates the `StreetSet`, whose constructor
   S 0069f4b0 creates the `StreetRenderer` (streams, effect, textures).
4. `S2CG::ItemMgr::CreateInstance`, then `[data]\settings\items.xml` → `ItemMgr::LoadFromXml` S 0069d650 (types,
   animated types, donkey meshes, stack layouts); a file that cannot be opened leaves the item table empty.
5. Later in the load [inferred, not part of `Scene::Init`]: terrain blocks are created and with them the
   `GridQuadTree` (`CTerrainCellMgr::CreateTerrainCells` S 006b73b0, called from `CLandscape::RebuildCells`).
6. Logic objects announce themselves through the scene callbacks [known]: a flag creates its map object and its
   pile (`Scene::OnFlagCreated` S 00682ca0); a street of at least 2 cells creates a `CStreet` / `WaterStreet`,
   then for its first and its last cell finds the `StreetFlagNode` on that cell or creates it and registers it as
   a crossing (`StreetSet::AttachFlagNodes` S 0069eeb0; a new node is also linked to one other street that ends
   on the cell), attaches to both nodes (each attach rebuilds the node's crossing and the street's own mesh),
   and registers with the renderer (`AddStreetFromRoute` S 0069f570); a package creates an item
   (`CreateItemForLogicItem` S 0069def0). A flag node is therefore created by the first street that ends on a
   cell, not by the flag.

**Per logic tick**: the scene callbacks for package added to / removed from a flag (`OnLogicItemAddedToPile`
S 0069c920, `OnLogicItemRemovedFromPile` S 0069c960), street added, removed or upgraded, flag created or
removed; then, in `Scene::SyncLogicTick` S 00680550, after the map renderer and the characters and before
animals and ships, the carrier attachment refresh of all active items (`UpdateAllCarrierAttachments`
S 0069c4e0) [known].

**Per frame**, in `Scene::Update` S 006805e0 [known]: map renderer, characters (and with them the settler
blobs, `CCharacter::Update` S 00690bd0), then `ItemMgr::Update` S 0069c520 (`ItemRenderer::UpdateInstancing`
for the switch timers, then `Item::Update` of every active item in handle-list order: follow the carrier, fall,
land), animals, ships, swarms, projectiles, particles, and last `CEnviromentMgr::Update` S 00683d50 (sky). The
time step of the item update is the scene's frame delta in seconds (`Scene +0x58`, `docs/sim/rendering.md`
§2.2). Selection marker decals are re-projected by `CMapRenderer::UpdateSelectionMarkers` S 00689500, whose only
caller is `Scene::RenderPostFxAndOverlay` S 00680a00 [known]; that function calls it only on frames drawn
without the post processor (`docs/sim/rendering.md` §3.1). Street meshes are rebuilt only on events [known]: a
flag node attached or detached at either end (`CStreet::SetStartFlagNode` S 006cd3c0, `SetEndFlagNode`
S 006cd410, which end with the street's virtual rebuild, slot +0x14) and a terrain change whose cell rectangle
overlaps the street's cell bounds (`StreetSet::OnTerrainRegionChanged` S 0069e8d0 →
`CStreet::OnTerrainRegionChanged` S 006ccaf0); the same terrain callback is passed to every flag node
(`StreetFlagNode::OnTerrainRegionChanged` S 006d19d0). The map renderer forwards the terrain change only while
its `inactive` flag is clear [known] S 006882e0.

**Per view** (main, reflection, shadow): block culling, then the passes in the order of
`docs/sim/rendering.md` §3.1: sky, map (terrain, then streets §3.8, ...), characters, items (§3.4), ...,
projected decals (§3.9).

---

## 5. Inputs and outputs

Consumes:

- scene callbacks of `NLogic::CallbackManager` (`docs/sim/logic-core.md` §2.6): flag created / removed, street
  added / removed / upgraded, package created / destroyed, package added to / removed from a flag, sea route
  created / removed;
- logic objects read directly: package (`+0x18` good id, carrier and ship references, `+0x70` lying flag), flag
  (cell, id), street (cell path, type), the stock map of a building site;
- the terrain: cell to world position, height and normal sampling, triangle collection in an AABB;
- the camera frustum and eye, the device time, the settings (shader level, shadow level);
- the selection state (which marker style, target and radius).

Produces: draw calls only. Its writes outside its own objects all go to the visual character
`S2CG::CCharacter` [known]: the pile direction and its flag (`+0x98`, `+0x94`; S 006d0bd0, S 006d0c20,
S 006d09b0) and the character's override item handle (`CCharacter::SetOverrideItem`, S 006d0830). Nothing is
written into the simulation.

Network: none. This subsystem sends and handles no message.

---

## 6. Data-driven parameters

All paths under the game's `data` directory; files are in the encrypted container of `docs/asset-formats.md`.
The code names these files with the prefix `[data]\` (`[data]\settings\items.xml` and so on), which in the
install is the folder `data\game` [inferred from where the files lie]. Values are examples from the install
[known, file].

**`game/settings/items.xml`**, root `<Items>` [known] loader S 0069d650, S 006d0eb0:

| Element | Keys | Install |
|---|---|---|
| `ItemDefinitions/Item` | `name`, `mesh` (both required, else the element is skipped; children with another element name are ignored) | 54 items, e.g. `Wood` → `[data]\items\GO_Log01.KEX`, `Plank` → `GO_Plank01.KEX`, `GoatHam` and `SheepHam` → `GO_Flesh01.KEX`; also tools and weapons (`Axe`, `Sword`, `Bow`, ...), `Boat`, `Oxen`, `TestItem` |
| `AnimatedItems/*` (element name not tested) | `references`, `mesh`, `model`, `animation` | none (one commented-out `AnimatedItem` entry for `Fishing Rod`) |
| `DonkeyItems/*` (element name not tested) | `references`, `mesh` | one: `Wood` → `[data]\items\dummy_item.KEX` (not applied, §3.1) |
| `StackLayouts` | `count`, `distance` | `count="2"`, `distance="0.5"` |
| `StackLayouts/*` (element name not tested; `Layout` in the install) | attributes whose name starts with `offset` (3 floats each, taken in attribute order) and with `good` (a good name) | two layouts, below |

Layout 1 (a pyramid in the stack's local x / y): offsets `(-1,0,0) (0,0,0) (1,0,0) (-0.5,1,0) (0.5,1,0)
(0,2,0)`; goods `Wood`, `Stone`, `Corn`, `Iron`, `Goat`, `Fish`, `GoatHam`, `SheepHam`, `Bread`, `Coin`, `Sword`,
`Tool`, `Bow`, `Leather`, `Fleshham`, `Pretzel`, `Sheep`, `Claymore`, `Halberd`, `Kilt`, `Clay`, `CornBread`,
`Gemstones`, `Cheese`, `Milk`, `Salt`. Layout 2 (flat, 2 x 3 in x / z): offsets `(-0.5,0,-1) (0.5,0,-1)
(-0.5,0,0) (0.5,0,0) (-0.5,0,1) (0.5,0,1)`; goods `Water`, `Flour`, `Coal`, `IronOre`, `Gold`, `weissbeer`,
`Whisky`. Every other good (`Plank`, `Crossbow`, tools, ...) uses the built-in vertical stack: the bindings
`good4 = "Plank"` and `good20 = "Crossbow"` of layout 1 stand in an XML comment. Offsets are in units of the
item's own bounding box size.

**`game/settings/graphics.xml`**, element `Street`: the keys of §2.2 plus `shader="street_shader.fx"`,
`texture0` / `normal0` = `[data]\map\textures\simple_street.dds` / `simple_street_n.dds`, `texture1` / `normal1`
= `street.dds` / `street_n.dds`, `crossingTexture0` / `crossingNormal0` = `simple_crossing.dds` /
`simple_crossing_n.dds`, `crossingTexture1` / `crossingNormal1` = `crossing.dds` / `crossing_n.dds`,
`buoyTexture` = `[data]\map\objects\street_buoy.dds`, `routeTexture` = `[data]\map\textures\route_texture.tga`,
`redStreetColor="1.0 0.0 0.0 0.9"`, `alphaStreetColor="1.0 1.0 1.0 0.6"`. Element `Enviroment`:
`Sun texture="[data]\enviroment\sun.tga" size="30.0"`, `Moon texture="[data]\enviroment\moon.dds" size="9"`,
`Cubemap texture="[data]\enviroment\cube_0.dds"`, five `Skydome name texture rotation`: `Clouds`
(`skyBavaria.dds`, 90), `Stars` (`starfield.tga`, -45), `Egypt` (`skyEgypt.dds`, 90), `Bavaria`
(`skyBavaria.dds`, 90), `Scot` (`skyScot.dds`, 90).

**`game/settings/decals.xml`**: `<Decals>` with `<Texture name>` in index order: 0 `[data]\gfx\decals.dds`,
1 `[data]\gfx\buildingselect.dds`, 2 `[data]\gfx\catapultTarget.dds`. Any child element with a `name` attribute
is loaded [known] S 004df850.

**`game/gfx/fx_20/*.fx`, `shared.inc`**: §3.15.

Constants in code, not in data [known]: pile 6 x 6 slots and 60 degree spacing (S 006ce8d0, S 006cece0); fall
acceleration 0.981 (S 006d0720); instancing thresholds 20 / 9 and delay 5 s (S 006d0090), batch 40
(S 006cfd30); plain item stream 10000 / 30000 (S 006cfc20); street batch 6000 / 8000 (S 006c3f10); Hermite
tangent factor 1.3 (S 006d6db0); decal stream 12000 (S 004df850); marker spin 0.025132744 (S 006b0d00); sky
5000 / 5010 / 64 / 7 / 7 (S 006af960); occluder threshold -0.2 (S 006db440); scaffold column 8 and spacing 1.05
(S 006d8070).

---

## 7. Save and load

Nothing of this subsystem is persisted: no function read here stores or loads a field of its objects [known
for the functions of §11]. Piles, items, street meshes, flag nodes, decals and the quad tree are rebuilt from the
simulation after a load through the same callbacks as at match start [inferred]; `docs/sim/save-format.md`
describes what the simulation stores and which "added" callbacks its post-load step raises. Two caches are
written outside the save, both derived data a remake does not need: compiled effects and `.mshraw` meshes under
`<Local AppData>\SAdK\` (§3.11, `docs/sim/animation-models.md` §3.3).

One consequence: the slot a good occupies in a pile depends on the order in which the scene callbacks arrived,
which differs between a running match and a reloaded one. The arrangement of goods at a flag is therefore not
stable across a save and load [inferred].

---

## 8. Determinism notes

Presentation only. Evidence:

- no function read here writes a field of a logic object; the only writes outside the subsystem's own objects
  are `CCharacter +0x94 / +0x98` (S 006d0bd0, S 006d0c20, S 006d09b0) and the character's override item
  (S 006d0830), fields of the visual character [known];
- item motion (`Item::Update`), the instancing timers, the route texture animation, the marker spin and the
  sky use the frame time step and device time, which differ per machine;
- `StreetRenderer` owns a private random generator with a fixed seed (0x5432ace0), separate from the
  simulation's generator [known] S 006c4290. No mapped method of `StreetRenderer` and no function of the street
  classes calls a method of the generator (`SetSeed`, `NextInRange`, `Math_Random_NextUnitFloat`,
  `RestartFromSeed`), so it is unused [inferred from a search of the decompiled program for such calls];
- culling and instancing depend on the local camera and shader level.

A remake may therefore change any rule of this document without affecting synchronisation.

---

## 9. Notes for a Godot reimplementation

- **Goods**: one `MultiMesh` per item type replaces the plain / instanced switch entirely. Reproduce exactly:
  the name match good → item, the 6 x 6 pile with one good kind per stack, the join / free / merge order of
  §3.2, the 60 degree directions, the base offset `distance + size.z`, the layouts scaled by the item's AABB,
  the fall at 0.981 units/s² and the snap on landing. The converter supplies per item: mesh, diffuse texture,
  AABB. Decide deliberately about donkey meshes (dead data in the original, §3.1) and about a good that finds
  no slot: the original has no defined picture for it (§10 question 2), so a remake needs its own rule (for
  example: hide it).
- **Carried goods**: a `BoneAttachment3D` on the bone the settler class names; hide goods on ships.
- **Streets**: build an `ArrayMesh` per street on creation and on terrain change. The original clips the
  terrain triangles to each slice so the street has the terrain's exact surface; a remake can do the same or
  sample the height field at a finer step, but must keep the Hermite path (tangent factor 1.3, segment
  lengths), the half width 1.0, `u` across, `v = 0.25` per unit, the trimmed first and last slice at flags
  with more than one street, and the six-triangle hexagon fan of radius 2.25 with its uv mapping (centre at
  the node position, each corner at the terrain height under it, not clipped to the terrain). The near-plane
  shift is not a small offset: it pulls streets by about 9 % of the view depth (§3.8, about 3.4 units at 40
  units). A small fixed depth offset leaves most of a flat crossing fan under the terrain wherever the ground
  bulges between its corners (the fan's radius 2.25 spans more than one terrain vertex step of 1.5), so only the
  trimmed street ends show, as hard cuts. Where the renderer cannot reproduce the shift for streets alone
  (opaque objects drawn before transparent ones would then be covered by streets), keep the fan's
  interpolation and raise the parts that would lie under the drawn ground onto it: subdivide each fan
  triangle and lift only the buried points; this gives the original's visible result. Street material: albedo
  + normal map, alpha blended, no depth write, clamped in u and repeated in v.
- **Sea routes**: flat strip at the route spline's height (the water level [inferred], §3.7), half width 2.5;
  a 16-frame horizontal strip texture cross-faded at 10 frames per unit of the render time (two uv offsets and
  a mix uniform).
- **Decals**: Godot `Decal` nodes project onto geometry natively. Selection: additive, full texture, size `r`,
  spinning one turn per 250 time units. Settler blob: texture 0, alpha 0.75, created only at shadow levels 1
  to 3; as read statically its vertices are all raised to the height 3.4e38 and it never shows on the ground
  (§3.9), so leaving it out is the faithful choice until a screenshot shows otherwise.
- **Sky**: a `Sky` resource or a large dome mesh with the map's skydome texture tiled 7 x 7, drifting by
  `(0.015, 0.005)` uv per unit of `TIMER.y` (game seconds, §3.11). The original's `Default` technique
  shows the texture alone; day-time blending, rim fade, sun and moon are not visible in it (§3.10), so adding
  them is a design choice, not a port.
- **Culling**: Godot's own frustum culling of per-block meshes replaces the quad tree; nothing depends on its
  exact output except performance.
- **Shaders**: port the pixel formulas of `shared.inc` (one directional light, ambient, shadow darkening of the
  direct term only, exploration darkening with noise) into one shared shader include; the per-file table of
  §3.15 lists what each object class adds. The fixed-function and vertex-shader-only techniques need no port.
- **Converter**: decrypt, convert `.dds` / `.tga` textures, `.KEX` meshes (with the vertex layouts of §2.6 as
  the target attribute sets), copy the XML values of §6. The texture atlas is built at run time from loaded
  images and needs no conversion step.

---

## 10. Open questions

| # | Question | What settles it |
|---|---|---|
| 1 | Answered (§3.1 item 1): not with the shipped data. The four package creators (callers of S 0064fb10) test no type, but they only receive wares: needs expand `EitherGroup` recipe entries (S 00565a70), construction costs are wares, a worker carries a stored good out only if it is a Ware (S 0055b120), and no building whose product slot 0 is a group good carries its product. Changed data could make such packages | — |
| 2 | Answered as far as the code decides: a good that finds no slot is left in no stack, and `ApplySlotTransform` S 006ce970 copies 64 bytes from `pile - 0x1b4` into its matrix; the pile is its own heap block (S 0069c390), so the transform is arbitrary. The case needs `cfg_setFlagPackageLimit` of 7 or more: for a limit up to 6 the pile's `ceil(count / 6)` stacks per good never exceed the logic's `ceil(count / limit)` (shipped limit 2) | static: S 006cece0, S 006ce7a0, S 006ce970; `docs/sim/streets-transport.md` §2.4 |
| 3 | Answered (§3.6): `points0` is `planner0`'s accepted plan (extended per click by `PlanSegment` S 0078b220, rebuilt by `RebuildPath` S 0078b510 in `OnPlannerCommand` S 0078be80); `points1` is the plan through the waypoints plus the cursor cell. Red means `points1` is shorter: the cursor lies on the plan and the red tail is what a click there would cut back (`CommitPathTo`) | — |
| 4 | Whether the settler blob is visible in the running game (statically every vertex is raised to 3.4e38, §3.9) | a screenshot at shadow level 1 to 3 |
| 5 | Layout of `decals.dds` (the blob uses the whole texture: uv offset (0, 0), scale (1, 1)) | look at the texture |
| 6 | Answered (§3.10): sun and moon are not drawn. The pass handle `Sun` is stored at `SkyRenderer.hSunPass` (+0x2c) by S 006af300 and the two quads are built, but no function of the decompiled program reads the handle: none of the functions that hold the `SkyRenderer` pointer (`CEnviromentMgr` constructor, destructor, `Update` S 00683d50, `RenderSkydome` S 00683e50) nor a `SkyRenderer` method begins that pass [inferred]. Not observed in the running game | static: S 006af300, S 006af490, S 00683e50 |
| 7 | Contents of `TIMER.z`, `.w` and of `CAMERA_FOCUS`; where the `POSTFX` define is supplied (§3.11). Answered for `.x` and `.y`: the scene's frame delta and its accumulated game time, written by `BeginRendering` S 004d78a0 ([rendering.md](rendering.md) §3.13) | writers of S 00887460..S 00887490; callers of `CShaderProgram::Reload` S 004ec260 |
| 8 | The class behind `CGraphicDevice +0x1b4` that fills the dome position (§3.10) | writer of that field |
| 9 | Animated items (`AnimatedItem`, `ItemEvent`) are unused by the install's data; their play rules | static read of S 006c9660, S 006b0800 if a mod needs them |
| 10 | How a carrier on a water street shows its good (the carrier's own attachment, besides the boat item of §3.3) | static read of `CharacterCarrier::UpdateAttachedItem` S 006c8ee0 |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| S 00405590 / 004dfbd0 | `CApplicationEx::InitEngineLayer` / `ai::render::DecalRenderer::CreateInstance` | decal renderer created at program start |
| S 006824c0 | `S2CG::Scene::Init` | load order: `graphics.xml`, environment, map renderer, `items.xml` |
| S 00680550 / 006805e0 | `Scene::SyncLogicTick` / `Scene::Update` | per logic tick, per frame |
| S 00682ca0 | `Scene::OnFlagCreated` | flag map object and pile |
| S 00688170 / 00684be0 | `MapRender_LoadSettingsXml` / `Env_ParseEnvironmentXml` | `<Landscape>`, `<Street>`, `<Water>` / `<Enviroment>` of `graphics.xml` |
| S 0069d650 | `S2CG::ItemMgr::LoadFromXml` | `items.xml` |
| S 006d0eb0 | `ai::render::ItemPileLayoutTable::LoadXml` | stack layouts |
| S 006d0cb0 | `ItemPileLayoutTable::GetSlotOffsets` | layout of a good |
| S 0069dbe0 | `ItemMgr::LoadItemTypeMesh` | mesh, AABB, diffuse texture of a type |
| S 0069def0 / 0069e0f0 / 0069e000 | `ItemMgr::CreateItemForLogicItem` / `CreateItemForGood` / `CreateItemByType` | item creation |
| S 0069c390 / 0069c090 | `ItemMgr::CreatePileForFlag` / `FindPileForFlag` | piles |
| S 0069c920 / 0069c960 | `ItemMgr::OnLogicItemAddedToPile` / `OnLogicItemRemovedFromPile` | scene callbacks |
| S 0069c520 / 0069c4e0 | `ItemMgr::Update` / `UpdateAllCarrierAttachments` | per frame / per logic tick |
| S 0069c5c0 | `ItemTypes_FindByName` | item type index of a name, -1 when absent |
| S 006d0480 / 006d06a0 | `S2CG::Item::ctor` / `dtor` | item for a package (pile only with a flag reference, i.e. after a load); removal from the pile and the character |
| S 006d0720 | `Item::Update` | follow, fall, land |
| S 006d09b0 / 006d0830 / 006d0620 | `Item::UpdateCarrierAttachment` / `AttachToCharacter` / `UpdateAttachedTransform` | carried goods |
| S 006d0bd0 / 006d0c20 | `Item::OnAddedToPile` / `OnRemovedFromPile` | pile entry and exit, stack direction to the carrier |
| S 006ce8d0 | `ai::render::ItemPile::ctor` | 6 x 6 slots |
| S 006cece0 / 006ceb50 / 006cee50 | `ItemPile::AddItem` / `RemoveItem` / `ai::render::ItemPile::MergeStacks` | pile rules |
| S 006ce9c0 / 006ce970 / 006ce7a0 | `ItemPile::ComputeStackTransforms` / `ApplySlotTransform` / `FindItem` | slot matrices, stack and slot of an item |
| S 006cf8a0 / 006cf210 / 006cf480 | `ai::render::ItemRenderer::Render` / `RenderPlain` / `RenderInstanced` | item drawing |
| S 006d0090 / 006cfd30 | `ItemRenderer::UpdateInstancing` / `BuildInstancedMesh` | instancing switch |
| S 006cfc20 | `ai::render::ItemRenderer::CreateResources` | plain item streams, `item_shader.fx` |
| S 006d82f0 / 006d8240 / 006d8070 | `ai::render::BuildingScaffold::RebuildIfSourceChanged` / `ai::render::BuildingScaffold::BuildStacks` / `ai::render::BuildingScaffold::LayoutItems` | goods on a building site |
| S 006abcf0 / 006d7d70 | `S2CG::Building::Update` / `ai::render::BuildingScaffold::SetPosition` | scaffold life cycle and place (anchor x, half way to the flag) |
| S 0078bbe0 / 0078b890 | `ai::game::StreetBuildMode::UpdatePreview` / `CreatePreviewCasters` | street build preview |
| S 0078b220 / 0078b510 / 0078be80 | `StreetBuildMode::PlanSegment` / `RebuildPath` / `OnPlannerCommand` | `points0` (accepted plan) and `points1` (plan to the cursor) |
| S 006c8ee0 | `CharacterCarrier::UpdateAttachedItem` | carried good on a water street [TODO] |
| S 006c3f10 | `ai::gfx::StreetRenderer::LoadConfigXml` | `<Street>` of `graphics.xml` |
| S 006d7a80 / 006d6ff0 / 006d6db0 / 006d75b0 | `ai::math::RouteSpline::ctor` / `ComputeTangent` / `EvaluateSegment` / `EvaluateFrame` | street path |
| S 006d71a0 | `RouteSpline::ApproxSegmentLength` | segment length from 31 chords |
| S 006d6ab0 | `Math_CubicHermiteBasis` | basis weights |
| S 0069f570 / 0069eeb0 | `ai::rendering::StreetSet::AddStreetFromRoute` / `AttachFlagNodes` | street creation, flag node lookup or creation |
| S 0069e8d0 / 006ccaf0 | `StreetSet::OnTerrainRegionChanged` / `S2CG::CStreet::OnTerrainRegionChanged` | mesh rebuild after a terrain change |
| S 006cd480 / 006cd320 | `S2CG::CStreet::ctor` / `BuildSpline` | street visual |
| S 006cd3c0 / 006cd410 | `CStreet::SetStartFlagNode` / `SetEndFlagNode` | link to a flag node, then mesh rebuild |
| S 006df940 | `S2CG::StreetDecal::BuildFromSpline` | street mesh |
| S 006de590 | `StreetDecal::BuildJunctionFan` | crossing mesh |
| S 006d1370 / 006d1670 / 006d1310 / 006d1d90 | `ai::gfx::StreetFlagNode::Init` / `ai::gfx::StreetFlagNode::ComputeCornerPoints` / `StreetFlagNode::GetCornerPoint` / `AttachStreet` | flag node |
| S 006e1e30 | `S2CG::StreetBuoy::BuildBuoyChain` | water street buoys |
| S 006e2450 | `S2CG::RouteDecal::BuildFromSpline` | sea route strip |
| S 006d2050 | `S2CG::WaterStreet::InitBoatResources` | boat item |
| S 006c4290 / 006c3ab0 | `ai::gfx::StreetRenderer::ctor` / `Render` | resources, draw order |
| S 006c3250 / 006c29a0 / 006c3030 / 006c3570 | `StreetRenderer::DrawStreetList` / `DrawRoutes` / `DrawCrossings` / `DrawBuoyList` | batches |
| S 006c39f0 / 0069e930 | `StreetRenderer::PromoteStreetToKind1` / `StreetSet::PromoteStreetToKind1` | street upgrade |
| S 0069ecc0 | `StreetSet::CreateFlagNode` | crossing node, only from `AttachFlagNodes` |
| S 006aa7b0 / 006ccc70 / 006e0e30 | `S2CG::Building::CreateEntranceStreet` / two-point `CStreet` / `StreetDecal::BuildStraight` | the door path |
| S 006aa320 / 006ab040 | `S2CG::Building::SetHidden` / `dtor` | door path shown / removed |
| S 006d0950 | `Item::GetCarrierCharacter` | the carrier that gets the stack direction |
| S 004df850 / 004df400 / 004df1d0 | `ai::render::DecalRenderer::CreateResources` / `Render` / `CreateDecal` | projected decals |
| S 004efaa0 / 004efb60 / 004f0390 / 004efe20 | `ai::render::DecalProjector::ctor` / `SetOrientation` / `GetClipPlanes` / `BuildVertices` | projector |
| S 0068aad0 | `S2CG::CLandscape::ProjectDecal` | terrain triangles under a decal |
| S 006b0b50 / 006b0d00 | `ai::render::SelectionMarker::CreateDecal` / `UpdateDecal` | selection markers |
| S 00689500 | `S2CG::CMapRenderer::UpdateSelectionMarkers` | chooses marker targets and styles, calls `UpdateDecal` |
| S 00690bd0 | `S2CG::CCharacter::Update` | per-frame character update; creates and projects the settler blob decal |
| S 006af960 / 006af490 / 006af150 / 006af260 | `ai::render::SkyRenderer::ctor` / `BuildGeometry` / `DrawSkydome` / `ai::render::SkyRenderer::BeginSkydomePass` | sky dome |
| S 006af300 / 006af210 | `ai::render::SkyRenderer::InitEffect` / `SkyRenderer::Update` | effect and pass handles; dome position per frame |
| S 00685070 / 00683d50 / 00683e50 / 00684fb0 | `S2CG::CEnviromentMgr::ctor` / `Update` / `RenderSkydome` / `CreateSkydomes` | sky renderer and sky textures |
| S 006daf20 / 006da9f0 / 006db440 / 006db220 / 006dac90 / 006dad30 | `ai::render::GridQuadTree::ctor` / `BuildNode` / `Cull` / `CullNode` / `IsAabbInFrustum` / `SelectNearestChild` | block culling |
| S 004def10 | `ai::render::MeshRenderer::AddInstance` | single meshes drawn with `mesh_shader.fx`; its three callers are `S2CG::Projectile::ctor` S 006a3720, `S2CG::Ship::UpdateVisuals` S 006a5cc0 and `S2CG::WaterStreet::SetBoatVisible` S 006d1ea0 [known, xrefs] |
| S 004ef7b0 / 004ef880 | `ai::rendering::ShaderTechniqueTable::Init` / `Select` | technique choice |
| S 004d4ab0 | `S2CE::CGraphicDevice::GetEffectiveShaderLevel` | shader level |
| S 004d9e10 / 004d3ae0 | `CGraphicDevice::SetNearPlaneOffset` / `SetFogRange` | depth shift, fog |
| S 004ec060 / 004ebad0 / 004eb8f0 / 004ecba0 | `S2CE::CShaderProgram::CreateFromFile` / `GetCompiledEffect` / `ShaderProgram_BuildCompiledEffectCachePath` / `ShaderProgram_GetOrCreate` | effect loading and cache |
| S 004e9600 / 004e9810 | `CShaderProgram::ResolveSharedSemanticHandles` / `ApplySharedParameters` | shared constants |
| S 004e80d0 / 004e7520 / 004e8a40 | `S2CE::CTexture::CreateFromFile` / `LinkToStage` / `Render_SetStageTextureSize` | textures |
| S 004ee7e0 / 004ee710 / 004ee1d0 / 004ee420 | `S2CE::CTextureAtlas::CreateTexture` / `AddImage` / `InsertNode` / `GetRegionUV` | run-time atlas |
| S 004db310 / 004db3a0 / 004db430 / 004db4c0 / 004db500 | `S2CE::CResourceMgr::CreateTexture` / `CreateVertexBuffer` / `CreateIndexBuffer` / `AcquireShaderProgram` / `CreateTextureAtlas` | resource factory |
| S 004ef660 | `ai::rendering::SharedResourceCache::Acquire` | shared meshes and animations |
| S 004e4fd0 / 004e5330 | `S2CE::CVertexStream::CreateDeclaration` / `Create` | vertex layouts |
