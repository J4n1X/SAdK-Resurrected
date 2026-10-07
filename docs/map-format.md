# SAdK `.s2m` map file format

Reference for map-editor developers. Game: *Die Siedler: Aufbruch der Kulturen* (SAdK). Binary
analysed: `sadk_noav.exe` (Ghidra, function names and addresses as below). Samples: the 22
decrypted map payloads in `mapping/work/mapdoc/samples/`. The reference file throughout is
**`MP_6P_ship_ahoi.s2m`** (110×110 cells, 12 harbors, 6 ship routes).

**Confidence tags** (every claim carries one):

| Tag | Meaning |
|---|---|
| `[known]` | Read in code **and** matched in the sample bytes, or read in code with no ambiguity. |
| `[inferred]` | Follows from code or data, but not proven. |
| `[guess]` | Plausible, no direct evidence. |

All offsets are offsets into the **decrypted payload**. "ship_ahoi 0x…" means a byte offset in
`mapping/work/mapdoc/samples/MP_6P_ship_ahoi.s2m`. Unknown bytes are written as "unknown (n bytes)".

---

## Start here: why editor-made harbors fail

In a map file a harbor is **not a building**. It is a record in the `Navy System` section, and the game
rebuilds nothing about it when the map loads. Everything has to be written by the editor:

1. **Ship routes are stored, never computed.** Each route links exits of two different harbors over
   water. A harbor without a route connects to nothing.
2. **Exit, dock and route references must agree.** Each exit names its route by id, and each route's path
   starts and ends exactly on those exit cells.
3. **The navy grid bits must be exact:** `0x2000` harbor cells, `0x4000` exit cells, `0x800` dock cells,
   `0x8000` route path cells, all in `GridStatesMap`.
4. **Ship ground is needed near a coast** (pattern `0xdecade01`), or no shipyard can be placed.
5. **Exits and docks are plain offsets** from the harbor cell, taken from the harbor's facing in
   `harbors.lua`, with no hex-row correction. Continents must put the exit, its docks and the whole path
   into one water body.

The complete checklist is in §6.6, and the failure modes ranked by likelihood are in §6.7.

---

## Contents

1. Overview
2. Serialization primitives
3. File layout (section table)
4. Sections in detail
5. Coordinates and grids
6. Harbors in depth
7. Cross-section consistency rules
8. Validation and open questions

Appendix A: section-header table (name, version, CRC32, length).

---

## 1. Overview

### 1.1 File family

| Extension | Content | Tag |
|---|---|---|
| `.s2m` | Map: only the "Game File Map" part (this document). | `[known]` (`GameFile_SaveMap` 005a9fa0) |
| `.sav` | Savegame: the same map part, followed by a "Game File Logic" part (v6, buildings, settlers, flags, AI, quests…). | `[known]` (`GameFile_SaveLogic` 005a9ec0) |
| `.a2m` / `.aav` | Parallel "+100" type family (types 101/110). Meaning not established. | `[inferred]` (`MapPath_GetFileExtension` 0052c1b0) |
| `<map>.bin` | Unencrypted environment and lighting sidecar (§4.17). Optional. | `[known]` |
| `<map>.bmp` | Preview picture for the map list (`UiResourceManager_LoadMapPreviewTexture` 00493700). Not analysed. | `[inferred]` |
| `<map>.lua` | Optional map script (campaign). Freegame maps ship without one. | `[known]` (`GameFile_LoadMap` 005aa7b0 → `GameScript_LoadMapScript` 005b1fe0) |

A map file contains **no** buildings, settlers, flags, streets, players, AI data, quests or
triggers. Those exist only in the savegame logic part. A tag scan of all 22 samples finds none of
their section headers. `[known]` (`GameFile_Save` 005aa260 calls `FUN_005aa150`, which clears
the street net, settlers, ships and village state before `GameFile_SaveMap`.) The HQ and starting
goods of each player are created at game start from MapInfo (§4.2). `[inferred]`
(`FUN_005abb60` call list: `PlayerTable_CreatePlayer` 005be100, `NVillage::System::PlaceBuilding`
0055a090.)

### 1.2 Encryption container (decryption is out of scope)

The samples were decrypted with AdKEd. For completeness, the on-disk container
(`NCore::FileStreamCrypt`, vftable 00834f04, `Close` 007805d0):

| Off | Type | Field | Tag |
|---|---|---|---|
| 0x00 | u32 | container version `0x06091812` | `[known]` |
| 0x04 | char[4] | `"sadk"` | `[known]` |
| 0x08 | u32 | CRC32 of the plaintext | `[known]` (written); whether the loader checks it: open |
| 0x0c | u32 | key hash | `[known]` |
| 0x10 | u32 | plaintext size (= decrypted sample size in all 20 installed maps) | `[known]` |
| 0x14 | … | packed and encrypted payload | `[known]` |

- `.s2m` and `.aav` use the **shared base key**: `FileCrypt_DeriveFileKey` 006eeac0 skips the
  per-file-name derivation for them, so renaming a map does not break it. `[known]`
- Writer: `FileCrypt_PackAndEncrypt` 006ee8e0. Reader: `NBase::gReadFileData` +
  `NBase::gDecryptData` 006e6660. `[known]` (not re-documented here)

### 1.3 How the game finds and loads a map

Map type → directory and extension (`MapPath_GetFileExtension` 0052c1b0, `MapPath_BuildDirectory`
0052c320, `MapPath_GetDataSubdir` 0052c100) `[known]`:

| Type | Ext | Directory |
|---|---|---|
| 0 | .s2m | `[data]\maps\freeGameMaps\` |
| 1 | .s2m | `[data]\maps\campaignMaps\` |
| 2 | .s2m | `[data]\maps\tutorialMaps\` |
| 3 | .s2m | `<MyDocuments>\SAdK\maps\` (user maps) |
| 10 | .sav | `<MyDocuments>\SAdK\saves\` |
| 100/101/102/103/110 | .s2m/.a2m/.s2m/.s2m/.aav | "+100" family, meaning unknown |

| Step | Function | What happens | Tag |
|---|---|---|---|
| Map list / lobby | `GameFile_LoadMapInfo` 005aaa30 → `GameFile_LoadMapInfoCached` 005aa030 | Opens the .s2m, reads the 12-byte "Game File Map" header, then **`MapInfo::Load` directly**. The result is cached as a plain `<map>.info` / `.usermapinfo` file. **MapInfo must immediately follow the file header.** | `[known]` |
| Lobby map identity | `GameFile_FindMapByGuidAnyType` 005ac2f0, `GameFile_FindMapNameByGuid` 005ab3d0 | Maps are matched by the MapInfo UUID. | `[inferred]` |
| Full load | `GameFile_LoadImpl` 005aaed0 → `GameFile_LoadMap` 005aa7b0 | Types 0,1,2,3,100,102,103 read only the map part; 10,101,110 also the logic part. | `[known]` |
| Sidecars | `GameFile_LoadMap` 005aa7b0, `GameFile_FinishLoad` 005aa1b0 | The `.lua` and `.bin` paths are built from **MapInfo name (+0x24)**, not from the file name. | `[known]` |
| Post-load | `GameFile_FinishLoad` 005aa1b0 | No grid, continent or navy geometry is recomputed (§5.5). | `[known]` |

**Keep MapInfo name == file base name.** Two samples (MP_3P_Spiral stores "Spiral", MP_5P_pentagon
stores "Pentagon") do not; the game would look for `Spiral.bin` / `Spiral.lua`. `[known]` (sample
bytes; `GameFile_LoadMap` copies MapInfo+0x24 into the `MapPath`)

---

## 2. Serialization primitives

### 2.1 Encoding rules `[known]`

All values are **little-endian**, with **no alignment and no padding**. There are **no length
fields per section and no seeking**: the reader consumes the stream strictly in order, so one wrong
field silently desynchronises everything after it.

Stream slots of `NCore::FileStreamCrypt` (vftable 00834f04, read from memory):

| Primitive | Write impl | Read impl | Bytes on disk | Tag |
|---|---|---|---|---|
| Section header (`BeginSection(cat)`) | 0057cfc0 | 0057cf80 (returns version), 007804f0 (discards) | 12, see §2.2 | `[known]` |
| Raw bytes | `WriteRaw` 00780480 | `ReadRaw` 00780470 | n | `[known]` |
| String | 00780580 | 007808d0 | `u32 len` + len bytes, **no terminator** | `[known]` |
| float | 0057cff0 | 007804d0 | 4, IEEE-754 binary32 | `[known]` |
| u16 | 00780540 | 0057cf60 | 2 (not used by any map section) | `[known]` |
| i64 | 0057d010 | 007804b0 | 8 | `[known]` |
| **bool** | 00780520 | 00780490 | **4 bytes** (u32 0 or 1; read as `u32 != 0`) | `[known]` (ship_ahoi 0x5cf = `01 00 00 00`) |
| i32 / u32 / count | 0057cff0 | 007804d0 | 4 | `[known]` |

String limits `[known]` (007808d0 disassembly): read into a 0x800-byte stack buffer, NUL placed at
`buf[len]`. **A length of 0x800 or more overflows the stack: keep strings ≤ 2047 bytes.** An
embedded NUL truncates. Bytes are copied without code-page conversion; Windows-1252 is presumably
intended `[inferred]`.

Containers: there is no generic container primitive. Each list is `u32 count` followed by the
elements. Polymorphic lists (deposits, animals, doodads, spawns, harbors) write an **i32/u32
property id** before each element; the loader uses it to find the property and factory. `[known]`

### 2.2 Section header ("tag") `[known]`

Every `stream->BeginSection(&g_LogCategory_X)` writes 12 bytes taken from the subsystem's static
`LogCategory` object (`LogCategory::ctor` 005816e0):

| Off | Type | Field |
|---|---|---|
| +0 | i32 | version (LogCategory+0x1c, the compile-time "current" version) |
| +4 | u32 | zlib-compatible CRC32 of the category name |
| +8 | u32 | byte length of the name |

- Example: `00000000 a2fe4954 0d000000` = "PatternCursor" v0 (crc32 0x5449fea2, 13 chars). The first
  12 bytes of every sample are `01000000 8908a979 0d000000` = "Game File Map" v1. `[known]`
- **The loader only uses the version.** `ReadSection` 0057cf80 returns the first dword and discards
  CRC and length; 007804f0 discards all three. A writer must still emit all 12 bytes, and should
  emit the correct CRC and length for compatibility with the game's own tools. `[known]`
- **The version selects the layout.** Loaders branch on it (examples: `MapInfo::Load` 0052bd40
  handles 1..15, `NLogic::System::Load` 00527d60 handles 1..8). **Write exactly the versions in
  Appendix A**, with the matching current layout. `[known]`
- The `*StoreUntagged` functions (e.g. `NNavy::System::StoreUntagged` 005b36a0) write the same data
  without headers for the desync CRC only; they never reach a file. `[inferred]`

### 2.3 Small records used everywhere `[known]`

| Record | Bytes | Layout | Writer / reader |
|---|---|---|---|
| **Cell** (`PatternCursor`) | 20 | hdr(v0,"PatternCursor") + i32 x + i32 y | `PatternCursor_Serialize` 00675190 / `_Deserialize` 006751d0 |
| **Fine position** (`ElevationCursor`) | 20 | hdr(v0,"ElevationCursor") + i32 fx + i32 fy (vertex grid coordinates, §5.2) | — |
| **Unique** (object id or reference) | 20 | hdr(v0,"logic UniqueId") + i64 (low dword first) | `NLogic::Unique::Store` 005386e0 |
| **UUID** | 32 | hdr(v0,"Core UUID") + bool32 valid + 16 raw bytes | `NCore::UUID::Serialize` 0057ce20 |
| **GoodAmount** | 8 | i32 goodId + i32 amount | `GoodAmount_Store` 00552c40 |
| **vector\<Cell\>** | 4 + 20n | u32 n + n × Cell | `Stl_VectorPair8_Store` 00529630 / `_Load` 0052a850 |
| **Rect** | 16 | i32 x0, y0, x1, y1 (inclusive) | `Rect_Serialize` 006765a0 |

**Unique validity** `[known]`: a reference is valid iff its **high dword** is in [0, 0x7fffffff]
(`ReferenceHarbor::Relink` 00539710, `NavyHarbor_FindExitForRoute` 005b4e80,
`GameQuery_IsFreeHarborExitAt` 0052dbb0). **"None" must be written as `ff ff ff ff ff ff ff ff`.**
Writing `ffffffff 00000000` produces a *valid* reference to id 0xffffffff.

### 2.4 Property ids `[known]`

The 32-bit ids before polymorphic objects and in MapInfo are the hex literals of the property
scripts in `data/game/scripts/properties/*.lua` (encrypted `.lua` on disk; decrypted copies in
`mapping/work/mapdoc/scratch/prall/`): `pa_create` (patterns, `LuaProps_pa_create` 0054ef60), `dp_create` (deposits,
0054e150), `an_create` (animals, 0054c5c0), `dd_create` (doodads, 0054fe10), `sp_create` (spawns,
0054a4d0), `hp_create` (harbors), `sn_create` (sounds), `tp_create`/`gp_create`/`sf_create`
(tribes, goods, sacrifices). Parsed with `Str_ParseHexUInt32` 005455b0. They are opaque designer
ids, not CRC32s of names. Some ids are created outside their "home" file (goods in `Jobs.lua`,
sacrifices in `sacrifices_goodExchange.lua`). With all of `properties/*.lua` loaded, every id in
every sample resolves.

**Unknown property ids crash the loader** for harbors (`Properties_GetHarbourProperty` 00547720,
`[known]`), spawns (`LogicSpawn_CreateFromProperty` 0052c990 returns NULL, `[inferred]`) and
deposits/animals (no null check after `Generic_MapIntLookup_*`, `[inferred]`).

---

## 3. File layout

### 3.1 Ordered section table

Write order: `GameFile_SaveMap` 005a9fa0 → `NLogic::System::Save` 005275c0 → `NMap::System::Store`
00671930. Read order is identical: `GameFile_LoadMap` 005aa7b0 → `NLogic::System::Load` 00527d60 →
`NMap::System::Load` 00672030. `[known]`

"Stored" = the game uses the bytes as written. "Derived" = the content is a pure function of other
sections; the game does **not** recompute it at load, so the editor must compute it (§5.5).

| # | Section (version) | ship_ahoi range | Size | Writer / reader | Stored / derived | Tag |
|---|---|---|---|---|---|---|
| 0 | `Game File Map` (v1) | 0x000000–0x00000c | 12 | `GameFile_SaveMap` 005a9fa0 / `GameFile_LoadMap` 005aa7b0 | header only; v ≥ 1 enables §15 | `[known]` |
| 1 | `MapInfo` (v15) | 0x00000c–0x00059b | 1423 | `NLogic::MapInfo::Store` 00529db0 / `Load` 0052bd40 | stored | `[known]` |
| 2 | `LogicSystem` (v8) | 0x00059b–0x0005c3 | 40 | `NLogic::System::Save` 005275c0 / `Load` 00527d60 | stored (uid counter must be consistent) | `[known]` |
| 3 | `MapSystem` (v0) header + fields | 0x0005c3–0x0005db | 24 | `NMap::System::Store` 00671930 / `Load` 00672030 | stored | `[known]` |
| 4 | `ElevationMap` (v1) | 0x0005db–0x0be4bb | 777952 | `NMap::Elevations::Store` 00675db0 | stored (source data) | `[known]` |
| 5 | `PatternMap` (v0) | 0x0be4bb–0x0ca1df | 48420 | `NMap::Patterns::Store` 006762b0 | stored (source data) | `[known]` |
| 6 | `GridStatesMap` (v0) | 0x0ca1df–0x0d5f03 | 48420 | `NMap::GridStates::Store` 0067ab70 / `Load` 0067b040 | **derived** from 4, 5 and entities/navy, but used verbatim | `[known]` |
| 7 | `Map Resources` (v0) | 0x0d5f03–0x0ed93b | 96824 | `NMap::Resources::Store` 0067a450 | stored | `[known]` |
| 8 | `Map Territory` (v0) | 0x0ed93b–0x0f9663 | 48424 | `NMap::Territory::Store` 006796e0 | stored (all −1 in maps) | `[known]` |
| 9 | `Map Exploration` (v1) | 0x0f9663–0x157efb | 387224 | `NMap::Exploration::Store` 006777c0 / `Load` 00677b30 | stored (all 0 in ship_ahoi) | `[known]` |
| 10 | `Map Continents` (v1) | 0x157efb–0x164a8f | 52116 | `NMap::Continents::Store` 00678090 / `Load` 006791b0 | **derived** from 4, 5, 6, used verbatim | `[known]` |
| 11 | `resources` (v6) | 0x164a8f–0x18af0b | 156796 | `NResources::System::Store` 0053e960 / `Load` 00540fd0 | stored | `[known]` |
| 12 | `DoodadsSystem` (v0) | 0x18af0b–0x21bc27 | 593180 | `NDoodads::System::Store` 00543bf0 / `Load` 00544ef0 | stored | `[known]` |
| 13 | `Logic Ambients` (v0) | 0x21bc27–0x21bcfb | 212 | `NLogic::Ambients::Store` 00536600 / `Load` 00536fd0 | stored | `[known]` |
| 14 | `Navy System` (v3) | 0x21bcfb–0x21df1f | 8740 | `NNavy::System::Store` 005b35d0 / `Load` 005b4650 | stored (**harbors live here**) | `[known]` |
| 15 | `Logic SpawnSystem` (v0) | 0x21df1f–0x21e1d3 | 692 | `LogicSpawnSystem_Save` 0052cb70 / `_Load` 0052cf90 | stored; only read if §0 version > 0 | `[known]` |
| — | slack | 0x21e1d3–0x21e200 | 45 | — | zero bytes, unused buffer capacity | `[known]` |

Sections 4–10 are sub-sections of MapSystem; their order is fixed by `Store`/`Load`: Elevations
(+0x10), Patterns (+0x14), GridStates (+0x18), Resources (+0x30), Territory (+0x1c), Exploration
(+0x28), Continents (+0x2c). `[known]`

Section 14 is written even when the map has no harbors (60-byte empty form, §6.2). `[known]`

### 3.2 Trailing slack `[known]`

`FileStreamCrypt::Close` takes the payload size from the MemoryStream **capacity** (`+0x10`, via
00412270), which starts at 0x400 and grows in 0x80 steps (`Open` 007807f0, `Write` 004122f0). So
game-written payloads are multiples of 0x80, and the bytes after the data are zero. The reader never
reaches them. **A writer does not need to pad.** MP_3P_Spiral and MP_5P_pentagon (older writer) are
not 0x80-aligned and end in 4 zero bytes; the reason is unknown.

### 3.3 Section sizes for a W×H map (current versions) `[known]`

| Section | Size in bytes |
|---|---|
| MapSystem header+fields | 24 |
| ElevationMap | 28 + 4·(4W+1)·(4H+1) |
| PatternMap | 20 + 4·W·H |
| GridStatesMap | 20 + 4·W·H |
| Map Resources | 24 + 8·W·H |
| Map Territory | 24 + 4·W·H |
| Map Exploration | 24 + 32·W·H |
| Map Continents | 24 + 4·W·H + 4 + Σ(44 + 4·neighbours) + 4 |

---

## 4. Sections in detail

`hdr(v,"name")` = 12-byte section header (§2.2). Offsets in the "Off" column are relative to the
section start unless they are absolute ship_ahoi offsets (written `0x…` with 6 digits).

### 4.1 Game File Map (v1) `[known]`

| Off | Type | Field | Meaning |
|---|---|---|---|
| 0 | hdr(1,"Game File Map") | — | Version 0 skips the Logic SpawnSystem on load (`GameFile_LoadMap` 005aa7b0). Write 1. |

### 4.2 MapInfo (v15) — ship_ahoi 0x00000c

Field order from `MapInfo::Store` 00529db0; version gates from `MapInfo::Load` 0052bd40. "Struct"
is the offset in the in-memory `NLogic/MapInfo` (0x210 bytes).

| ship_ahoi | Struct | Type | Name | ship_ahoi value | Meaning | Tag |
|---|---|---|---|---|---|---|
| 0x00c | — | hdr(15,"MapInfo") | header | | v15; `Store` writes v7 only on a `+0x1f4 != 0` branch never seen in maps (`.info` cache) `[inferred]` | `[known]` |
| 0x018 | +0x04 | vector\<Cell\> | startPositions | 6: (42,76) (27,55) (41,34) (68,34) (81,55) (68,76) | Player start cells; the HQ is placed here at game start (`FUN_005abb60`) | `[known]` encoding, `[inferred]` meaning |
| 0x094 | +0x24 | string | mapName | "MP_6P_ship_ahoi" | Scene name and sidecar base name (`.bin`, `.lua`). Keep = file base name. | `[known]` |
| 0x0a7 | +0x40 | i32 | width | 110 | = MapSystem W (`GameFile_Save` 005aa260 via `GameDesc_SetPair_40` 00529400) | `[known]` |
| 0x0ab | +0x44 | i32 | height | 110 | = MapSystem H | `[known]` |
| 0x0af | +0x48 | 8 × i32 | slotKind[8] | 2,1,1,1,1,1,0,0 | 0 closed, 1 computer, 2 human (`StartFreeGame` 005e7350, `FreeGamePanel::HasDuplicateColor` 005e69d0, `CountDistinctTeams` 005e75e0). Every sample: exactly one 2, in slot 0. Non-zero count = start-position count in 21/22 samples (sp03_the_sun: 4 occupied, 2 starts). | `[inferred]` |
| 0x0cf | +0x68,+0x88,+0xa8,+0xc8 | 8 × {4 × i32}, **interleaved per slot** | per slot i: tribe, colour, team, aiLevel | (0xb0d378a3,0,−1,0), (0xb0d378a3,3,−1,2)… slots 6–7: (−1,6/7,−1,0) | tribe = tribe property id (−1 none); colour index; team (−1 none); AI difficulty 0..2 (`PlayerRow_Refresh` 005e7830) | `[known]` encoding, `[inferred]` meanings |
| 0x14f | +0x1c8 | i32 | victoryMode | 0 | 1 conquest, 2/3 threshold, 5 quest (`VictoryCond_Update` 00535d70) | `[inferred]` |
| 0x153 | +0x1cc | i32 | unknown (water render preset?) | 0 | Read by `S2CG::CMapRenderer::InitForMap` 006883e0 → SetWaterPreset. 1 on 10 samples, no clear pattern. | `[guess]` meaning |
| 0x157 | +0x1d0 | i32 | mapType | 0 | Overwritten on load with the type the file was found under (`GameFile_LoadMapInfo` 005aaa30). All samples 0. | `[inferred]` |
| 0x15b | +0x1d4 | UUID (32) | mapGuid | valid=1, 66f14596a250dc4084c70bd8a0ba480f | Map identity for the lobby. Store generates a new one if invalid. **Give each distinct map its own UUID.** | `[known]` encoding, `[inferred]` use |
| 0x17b | +0x1ec | bool32 | unknown | 0 | Set by `SetupGameDialog::SetupSession` | `[guess]` |
| 0x17f | +0xe8 (stride 0x1c) | 8 × string | playerName[8] | "COMPUTER" ×8 | Player names | `[known]` encoding |
| 0x1df | +0x1f0 | i32 | unknown | 1 | `Reset` 0052b8d0 sets 1 | `[guess]` |
| 0x1e3 | +0x14 | vector\<Cell\> | chestPositions | 12 cells | Chest candidate cells (`Game_DistributeChestsForNetworkMatch` 00775dd0) | `[known]` encoding, `[inferred]` meaning |
| 0x2d7 | +0x1f8 | u32 n + n × {i32 tribeId, u32 m, m × GoodAmount} | initialGoods | 3 tribes | Starting stock per tribe | `[known]` encoding |
| 0x50b | +0x204 | u32 n + n × {i32 tribeId, u32 m, m × i32 sacrificeId} | sacrifices | 3 tribes | Sacrifice ids per tribe | `[known]` encoding |
| 0x59b | | | end | | | `[known]` |

Load-time upgrades run only for old versions (v ≤ 13 `ResetInitialGoodsFromTribes`, v ≤ 12
`ResetSacrificesFromTribes`, v ≤ 14 `NormalizeInitialGoodsForTribes` 0052a670). **A v15 writer must
supply the goods and sacrifice maps itself.** `[known]`

`MapInfo::Reset` 0052b8d0 defaults: kind 0, tribe −1, colour i, team −1, AI 0, name "<invalid>",
+0x1d0 = 110, +0x1f0 = 1. `[known]`

### 4.3 LogicSystem (v8) — ship_ahoi 0x00059b, 40 bytes `[known]`

| ship_ahoi | Type | Field | Value | Notes |
|---|---|---|---|---|
| 0x59b | hdr(8,"LogicSystem") | | | |
| 0x5a7 | i64 | **uidCounter** (next Unique id) | 204102 | `LogicId_StoreGlobal` 00538760. Must exceed every Unique in the file (§7). |
| 0x5af | bool32 | running | 1 | |
| 0x5b3 | 3 × f32 | frameDelta, nextTickTime, accumulatedTime | 0, 0, 0 | |
| 0x5bf | u32 | tickCounter | 0xffffffff | |

### 4.4 MapSystem (v0) — ship_ahoi 0x0005c3, 24 bytes `[known]`

| ship_ahoi | Type | Field | Value |
|---|---|---|---|
| 0x5c3 | hdr(0,"MapSystem") | | |
| 0x5cf | bool32 | initialised | 1 |
| 0x5d3 | i32 | W (cells) | 110 |
| 0x5d7 | i32 | H (cells) | 110 |

`Load` sets `g_MapWidth/Height` = W, H and `g_MapVertexWidth/Height` = 4W+1, 4H+1. **Grid sizes in
the sub-sections are not cross-checked against W and H.** `[known]`

### 4.5 ElevationMap (v1) — ship_ahoi 0x0005db

| Off | Type | Field | ship_ahoi | Tag |
|---|---|---|---|---|
| 0 | hdr(1,"ElevationMap") | | | `[known]` |
| 12 | bool32 | init | 1 | `[known]` |
| 16 | i32 | **minHeight = water level** | −100 | `[known]` (ctor default −100; water test §5.3) |
| 20 | i32 | vw | 441 (= 4·110+1) | `[known]` |
| 24 | i32 | vh | 441 | `[known]` |
| 28 | vw·vh × i32 | height per vertex, row-major `vy·vw + vx` | min −10772, max 14927, −5000 common sea floor | `[known]` |

v0 (legacy) reads a count and assumes the global vertex size. `[inferred]`

### 4.6 PatternMap (v0) — ship_ahoi 0x0be4bb `[known]`

| Off | Type | Field |
|---|---|---|
| 0 | hdr(0,"PatternMap") | |
| 12 | bool32 | init = 1 |
| 16 | u32 | count = W·H (12100) |
| 20 | count × i32 | pattern property id per cell, index `y·W + x` |

Pattern flags that drive grid bits (`PatternProperty` offsets, Lua setters) `[known]`:

| Offset | Flag | Setter | patterns.lua helpers that set it |
|---|---|---|---|
| +0x3c | blocked | `pa_setBlocked` 0054edb0 | Snow, Swamp, Lava, map border `0x76d31873` |
| +0x3d | forMining | 0054ee70 | Rock |
| +0x3e | forBuilding | 0054eeb0 | Meadow, Earth, Stoneground |
| +0x3f | forShip | 0054ee30 | **Ship** only |

Sand and Seaground set no flag. **The only forShip pattern is `0xdecade01` (`pattern_pavement`,
name "SHIP")** — the shipyard ground (§6.6). `[known]`

### 4.7 GridStatesMap (v0) — ship_ahoi 0x0ca1df `[known]`

| Off | Type | Field |
|---|---|---|
| 0 | hdr(0,"GridStatesMap") | |
| 12 | bool32 | init = 1 |
| 16 | u32 | count = W·H |
| 20 | count × u32 | flag word per cell (ship_ahoi data starts at **0x0ca1f3**; cell word at `0x0ca1f3 + 4·(y·110 + x)`) |

The bit table is in §5.4. Loaded verbatim; nothing on the load path recomputes any bit (§5.5).

### 4.8 Map Resources (v0) — ship_ahoi 0x0d5f03 `[known]`

| Off | Type | Field |
|---|---|---|
| 0 | hdr(0,"Map Resources") | |
| 12 | bool32 | init |
| 16 | i32, i32 | W, H |
| 24 | W·H × {i32 amount, i32 resourceType} | per-cell ground resource; empty = {0, −1} |

- ship_ahoi: 9081 empty cells, amount 7 on 3013 cells, 1000 on 6. `[known]`
- Type 0x4012e5a3 is the only one allowed on water, and only next to a shore cell
  (`MapModifier_CanHoldResourceAtCell` 00674210). Fish `[guess]`.
- The bit-deriving functions reset a cell to {0, −1} whenever bit 0x4, 0x10, 0x200 or 0x20000
  changes. `[known]`

### 4.9 Map Territory (v0) — ship_ahoi 0x0ed93b `[known]`

`hdr(0,"Map Territory")`, bool32 init, i32 W, i32 H, W·H × i32 owner. **All −1 in every sample.**

### 4.10 Map Exploration (v1) — ship_ahoi 0x0f9663 `[known]`

`hdr(1,"Map Exploration")`, bool32 init, i32 W, i32 H, then 8 players × W·H × i32 (a byte flag
widened to i32), index `player·W·H + y·W + x`. All 0 in ship_ahoi. The in-memory class behind
`NMap::System+0x28` is unresolved; the section name is what appears at this position. (v0 reads
bools: `[inferred]`.)

### 4.11 Map Continents (v1) — ship_ahoi 0x157efb `[known]`

```
hdr(1,"Map Continents")
bool32 init
i32 W, i32 H
W·H × i32 continentId              (−1 = no continent)
u32 n
n × Continent:
    hdr(4,"Map Continent")
    u32    cellCount
    bool32 isWater                 (1 = water body, 0 = land mass)
    i32    id
    Rect   bbox                    (inclusive x0,y0,x1,y1)
    [v2/v3 only: vector<Cell>, legacy, discarded]
    u32 k ; k × i32 neighbourId
u32 landCellCount                  (= Σ cellCount over land continents)
```

- ship_ahoi: 79 continents; id 0 is the sea (5456 cells, water, bbox 0,0–109,109); 761 cells have
  id −1; landCellCount = 5883. `[known]`
- **Continents v ≥ 1 are used verbatim. Only v0 is discarded and recomputed** (`Continents::Load`
  006791b0). Continent v0 has no rect; v2/v3 carry the legacy vector; v > 2 has neighbours. `[known]`
- The partition algorithm is in §5.6.

### 4.12 resources (v6) — ship_ahoi 0x164a8f `[known]`

```
hdr(6,"resources")
bool32 +0x44                      = 1
u32 depositCount ; depositCount × { i32 depositPropertyId ; Deposit }
u32 animalCount  ; animalCount  × { i32 animalPropertyId  ; Animal  }
[v3..v4 only: unknown (32 bytes)]
i32 +0x5c                         = 0 in all samples, meaning unknown
i32 +0x60                         = 0 in all samples, meaning unknown
i32 +0x08                         = 100 in all samples, meaning unknown   (v > 5 only)
```

ship_ahoi: 1130 deposits (12 types), 140 animals. MP_3P_Spiral and MP_5P_pentagon are v4 (the
32-byte block, no +0x08, Animal v2). The destination field of the v > 5 int is `[inferred]`
(decompile artefact).

**Deposit record** — 108 bytes including the property id (`NResources::Deposit::Store` 00542e10 /
`Load` 00542e80). Checked on all 18,655 deposits. `[known]`

| Off | Size | Type | Field | Map value / rule |
|---|---|---|---|---|
| +0 | 4 | i32 | depositPropertyId | from `dp_create` |
| +4 | 12 | hdr(1,"deposit") | | |
| +16 | 20 | Unique | depositId | distinct (§7) |
| +36 | 20 | Cell | cell | at most one deposit per cell |
| +56 | 20 | Unique | reservingBuilding | **always none** |
| +76 | 20 | ElevationCursor | finePos | within ±1 vertex of the cell sample vertex (§5.2): offset in {(0,0),(±1,0),(0,±1),(−1,±1)} (visual jitter `[inferred]`) |
| +96 | 4 | f32 | growth | **1.0** |
| +100 | 4 | i32 | depletedTicks | **0** (absent in v0) |
| +104 | 4 | i32 | ttlWithoutOwner | **−1** (absent in v0) |

A deposit with depletedTicks ≠ 0, growth < 1.0 or ttl ≥ 0 goes into the ticking list on load;
write 1.0 / 0 / −1 for a static deposit. `[known]` `Deposit::PostLoad` 00542f00 registers object
layer 3 but **does not set grid bits 0x80/0x1** (§7). `[known]`

**Animal record** — 248 bytes for v3 (244 for v2) including the property id
(`NResources::Animal::Store` 00541cc0 / `Load` 00541d50; movement chain
`NResources::Movement::Store` 00543710, `NResources::Path::Store` 00543b80,
`NMovement::PathBase::Store` 00772cc0, `NMovement::Base::Store` 007729e0,
`NMovement::Interpolator::Save` 00774a40). All 2,018 sample animals parse. `[known]`

| Off | Size | Type | Field | Map value ("idle template") |
|---|---|---|---|---|
| +0 | 4 | i32 | animalPropertyId | from `an_create` |
| +4 | 12 | hdr(3,"Resources Animal") | | |
| +16 | 20 | Unique | animalId | |
| +36 | 4 | f32 | timeStamp | 0.0 |
| +40 | 20 | Cell | home | |
| +60 | 12 | hdr(1,"Navy Movement") | (name really is "Navy Movement") | |
| +72 | 12 | hdr(0,"Resources Path") | | |
| +84 | 12 | hdr(1,"Movement Path Base") | | |
| +96 | 4 | bool32 | pathActive | **0**. If 1, followed by u32 n, n × Cell, bool32 valid, u32 index, bool32 newPath (never in maps). |
| +100 | 20 | Cell | registeredCell | = home |
| +120 | 12 | hdr(0,"Movement Base") | | |
| +132 | 20 | Cell | currentCell | = home |
| +152 | 20 | Cell | targetCell | = home |
| +172 | 20 | Cell | nextCell | (−1, −1) |
| +192 | 12 | hdr(0,"Movement Interpolator") | | |
| +204 | 12 | 3 × f32 | interpolator | (−1.0, 0.0, 0.0) |
| +216 | 4 | i32 | state | 0 |
| +220 | 4 | i32 | counter | 0..170, meaning unknown (idle phase `[guess]`) |
| +224 | 20 | Unique | hunterReservation | none |
| +244 | 4 | u32 | +0xb0 | 0 (v3 only) |

`AnimalAreas` is not stored; `System::Load` calls `AnimalAreas::Init` and `Animal::PostLoad`
00541bf0 re-adds each animal. `[known]`

### 4.13 DoodadsSystem (v0) — ship_ahoi 0x18af0b `[known]`

```
hdr(0,"DoodadsSystem")
bool32 +0x40                     = 1
u32 n0 ; n0 × Doodad             list 0: permanent, non-blocking
u32 n1 ; n1 × Doodad             list 1: temporary (has a lifetime)
u32 n2 ; n2 × Doodad             list 2: permanent, blocking
```

| Off | Size | Type | Field |
|---|---|---|---|
| +0 | 4 | i32 | doodadPropertyId (`dd_create`) |
| +4 | 12 | hdr(1,"DoodadsObject") | |
| +16 | 20 | Unique | doodadId |
| +36 | 20 | ElevationCursor | finePos |
| +56 | 4 | i32 | lifetime — **only if property+0x3c ≥ 0** |

Record size 56 bytes, or 60 with lifetime (`NDoodads::Object::Store` 00545210 / `Load` 00545260).
ship_ahoi: list 0 = 10384, list 1 = 0, list 2 = 208. `[known]`

List membership (`NDoodads::System::AddDoodadAtFinePos` 00544e00, property defaults from
`DoodadProperty_ctor` 00555970) `[known]`:

| Condition | List | Grid side effect |
|---|---|---|
| property+0x3c (lifetime, `dd_setLifeTime` 00550100) ≥ 1 | 1 | — |
| else property+0x48 (`dd_setBlocking` 0054fdc0) == 0 | 0 | — |
| else | 2 | **bit 0x400 on its cell** |

- Only 26 doodad types call `dd_setLifeTime` (3000 or 30000: resource signs), so in practice list-1
  records are 60 bytes and list-0/2 records 56 bytes. List 1 is empty in all 22 samples. All
  95,543 sample doodads sit in the list their property dictates. `[known]`
- The cell is not stored (v1); it is recomputed from finePos by
  `ElevationCursor_ToNearestPatternCursor` 00675500 (fallback `cy = fy/4`, `cx = (fx − 2·(cy&1))/4`;
  reproduces 208/208 blocking-doodad cells in ship_ahoi). `[known]`
- `Load` does **not** re-mark 0x400 for list-2 doodads; the bit must be in GridStatesMap. `[known]`

### 4.14 Logic Ambients (v0) — ship_ahoi 0x21bc27 `[known]`

```
hdr(0,"Logic Ambients") ; bool32 init = 1 ; u32 count ;
count × { i32 type ; Cell cell }          24 bytes each, no per-element header
```

`NLogic::Ambient::Store` 00536460. ship_ahoi: 8 entries, e.g. type 0x623437d3 at (41,72) (bytes at
0x21bc3b). All 167 ambient types in the samples are `ambient_*` sound ids from `sounds.lua`
(`sn_create`). Meaning "ambient sound emitter" is `[inferred]`; the consumer was not traced past
`Ambients::NotifyObserverAll` 005366f0.

### 4.15 Navy System (v3) — ship_ahoi 0x21bcfb

Full layout, field tables and rules are in §6.2–§6.5. `[known]`

### 4.16 Logic SpawnSystem (v0) — ship_ahoi 0x21df1f `[known]`

```
hdr(0,"Logic SpawnSystem") ; bool32 init = 1 ; u32 count ;
count × { i32 spawnPropertyId ; hdr(0,"Logic Spawn") ; Unique spawnId ; Cell cell }   56 bytes each
```

| ship_ahoi | Bytes | Meaning |
|---|---|---|
| 0x21df1f | `00000000 28f094b8 11000000` | hdr(0,"Logic SpawnSystem") |
| 0x21df2b | `01000000 0c000000` | init = 1, count = 12 |
| 0x21df33 | `77c8a5fc` | spawnPropertyId 0xfca5c877 (miscSpawn) |
| 0x21df37 | `00000000 7476804a 0b000000` | hdr(0,"Logic Spawn") |
| 0x21df43 | `00000000 dd2dfdc5 0e000000 68030300 00000000` | Unique 197480 |
| 0x21df57 | hdr + `4d000000 0a000000` | Cell (77,10) |

- Property `+0x6c == 0` → `SpawnResource` (regrows deposits, `SpawnResource::Spawn` 005390e0);
  `== 1` → `SpawnAnimal` (00538f40); other kinds → NULL and a crash on load `[inferred]`.
- These are **respawn points, not player start positions** (start positions are MapInfo +0x04).
- `Spawn::PlaceAt` 00538e10 sets bit 0x400; `Load` does not. The bit must be stored. `[known]`
- Spawns are found by position (`LogicSpawnSystem_FindSpawnAt` 0052ca70); their Unique ids are not
  evidently cross-checked. `[inferred]`

### 4.17 The `.bin` sidecar (unencrypted, optional) `[known]` layout, `[inferred]` names

Reader: `GameFile_FinishLoad` 005aa1b0 → `S2CG::CEnviromentMgr::LoadMapEnvData` 00685580 →
`MapEnvData_LoadBin` 006aea80 (`S2CG::EnvData::Load` 006ae220, `S2CG::EnvSphere::Load` 006ae290).
Path from MapInfo+0x24 (`Env_BuildMapEnvDataPath` 006852b0). If missing, the
`local_enviroment.xml` defaults stay (`MapEnvData_ctor` 006aee30). **No effect on gameplay or
harbors.** Size = 64 + 64·sphereCount.

| Off | Type | Field | ship_ahoi | oases |
|---|---|---|---|---|
| 0x00 | u32 | skydome index | 3 | 2 |
| 0x04 | u32 | light heading (deg) | 55 | 38 |
| 0x08 | u32 | light elevation (deg) | 50 | 55 |
| 0x0c | 9 × f32 | colours interleaved per component: bg.r, ambient.r, light.r, bg.g, ambient.g, light.g, bg.b, ambient.b, light.b | 0.8, 0.6, 0.938, 0.9, 0.5, 0.898, 1.0, 0.6, 0.781 | … |
| 0x30 | f32 | shadowIntensity | 0.899 | 1.0 |
| 0x34 | 2 × f32 | fog near, far | 175, 285 | 200, 335 |
| 0x3c | u32 | sphereCount | 1 | 0 |
| 0x40 | 64 B each | EnvSphere: the 12 floats of 0x0c..0x3b, then f32 centre[2], f32 innerRadius, f32 outerRadius | (…, −9.0, 2.598, 63.0, 200.0) | — |

Names come from `EnvData::LoadFromXml` 006ae0b0 attribute strings; the sphere-centre unit is
unknown.

---

## 5. Coordinates and grids

### 5.1 Cell grid and hex neighbours `[known]`

- W×H cells, linear index **`y·W + x`** (row-major) in every per-cell array
  (`Patterns::GetCellPtr` 00676270 and others).
- Hex grid, **odd rows shifted half a cell right** ("odd-r"). Neighbours via
  `MapPos_StepDirection` 00675000, parity tables at 00880f28 (dx) and 00880f68 (dy), read from
  memory:

| dir | even row (dx,dy) | odd row (dx,dy) | name |
|---|---|---|---|
| 0 | (+1, 0) | (+1, 0) | E |
| 1 | (0, −1) | (+1, −1) | NE |
| 2 | (−1, −1) | (0, −1) | NW |
| 3 | (−1, 0) | (−1, 0) | W |
| 4 | (−1, +1) | (0, +1) | SW |
| 5 | (0, +1) | (+1, +1) | SE |
| 6 | (0, +2) | (0, +2) | two rows down |
| 7 | (0, −2) | (0, −2) | two rows up |

Verified: the shore-bit and continent recomputations use exactly dirs 0..5 and match every sample;
all 615 ship-route path steps are single steps under this table.

- Hex rings/spirals: one step in dir 4, then dirs 0..5 with r steps each
  (`CliffMarker_CountCliffEdgeCellsInRadius2` 0067bbd0, `FloodFillContinent` 00678d70).
- **Exception: harbor exit/dock offsets are plain `(x+dx, y+dy)` without parity correction** (§6.3).

### 5.2 Elevation vertex grid `[known]`

- (4W+1) × (4H+1) vertices, index `vy·(4W+1) + vx`.
- **Cell (x,y) samples its height at vertex (4x + 2·(y&1), 4y).** (`FUN_0067b390`,
  `Elevations::GetSlopeClassBetween` 00676200; verified by the water-bit recomputation.)
- `ElevationCursor` fine positions (deposits, doodads) use the same vertex coordinates.

### 5.3 Slope class `[known]`

`Elevation_HeightDiffToSlopeClass` 00675d30 on the height difference of two cell sample vertices:
\> 2400 → 4, > 1200 → 3, > 600 → 2, > 200 → 1, −200..200 → 0, symmetric down to −4. Used for walk
cost and the cliff bit.

### 5.4 GridStates bits

"Recomputed ✓" = the rule, recomputed from the other stored data, reproduces the stored bit in
**all 22 samples** (script named).

| Bit | Mask | Meaning | Rule / setter | In maps | Tag |
|---|---|---|---|---|---|
| 0 | 0x1 | blocked | Pattern blocked (+0x3c), `FUN_0067b2c0`; plus cells of deposits whose property+0x54 ≠ 0 (`Deposit::ctor` 00542f80 → `MapModifier_SetGridBit0` 00673cf0). Recomputed ✓ for the pattern part (`patverify.py`). | yes | `[known]` pattern part, `[inferred]` object part |
| 1 | 0x2 | street | `MapModifier_SetStreetGridBit` 00674090 | always 0 | `[known]` |
| 2 | 0x4 | **water** | sample-vertex height **< minHeight** (`FUN_0067b390`). Recomputed ✓ (`verify.py`). | yes | `[known]` |
| 3 | 0x8 | **shore** | non-water cell with ≥ 1 water neighbour among dirs 0..5, in bounds (`FUN_0067b150`). Recomputed ✓. | yes | `[known]` |
| 4 | 0x10 | mining ground | pattern forMining (`FUN_0067b740`). Recomputed ✓. | yes | `[known]` |
| 5 | 0x20 | territory border | `MapCellUpdater_RefreshTerritoryBorderBits` 0067b910 | always 0 | `[inferred]` |
| 6 | 0x40 | cliff cut | algorithm §5.7 (`CliffMarker_RebuildAll` 0067be80). Recomputed ✓ (`cliff.py`). | yes | `[known]` |
| 7 | 0x80 | deposit | set of 0x80 cells **==** set of deposit cells (`MapModifier_SetGridBit7` 00673d40) | yes | `[known]` |
| 8 | 0x100 | building footprint | `MapModifier_SetGridBit8` 00673da0 | always 0 | `[inferred]` |
| 9 | 0x200 | **buildable** | forBuilding && !forMining && !blocked (`FUN_0067b820`). Recomputed ✓. | yes | `[known]` |
| 10 | 0x400 | logic object | set **==** spawn cells ∪ list-2 doodad cells (`MapModifier_SetGridBit10` 00673e00); excludes the cell from every continent | yes | `[known]` |
| 11 | 0x800 | **dock** | set **==** all stored docking-position cells (`MapModifier_SetDockingBit` 00673e60) | yes | `[known]` |
| 12 | 0x1000 | unknown | never set in any sample | no | — |
| 13 | 0x2000 | **harbor** | set **==** all stored harbor cells (`MapModifier_SetHarborBit` 00673ec0) | yes | `[known]` |
| 14 | 0x4000 | **harbor exit** | set **==** all stored exit cells (`MapModifier_SetHarborExitBit` 00673f20) | yes | `[known]` |
| 15 | 0x8000 | **ship route** | set **==** union of all route path cells (`MapModifier_SetShipRouteBit` 00673f80) | yes | `[known]` |
| 16 | 0x10000 | moving-ship tile | `MapModifier_SetShipTileBit` 00673fe0 | always 0 | `[inferred]` |
| 17 | 0x20000 | **ship ground** | forShip && !forBuilding && !blocked (`FUN_0067b650`), i.e. pattern 0xdecade01. Recomputed ✓. | harbor maps only | `[known]` |

ship_ahoi bit counts: b0 555, b2 5532, b3 1010, b4 2385, b6 443, b7 1130, b9 3626, b10 220, b11 52,
b13 12, b14 26, b15 142, b17 34. `[known]`

Key consumers `[known]` (each for that function's reading):

| Function | Test |
|---|---|
| `Map_IsCellWalkable` 0052df20 | none of 0x1, 0x4, 0x40, 0x100, 0x400 |
| `GameQuery_IsFreeWaterCell` 0052e360 | 0x4 set and 0x400 clear |
| `Map_HasShoreAndFreeWaterNeighbour` 0052e610 | a neighbour with 0x8 and a neighbour with 0x4 without 0x10000 |
| `GameQuery_IsBuildingFootprintFree` 0052f460 | 0x200 on every footprint cell, or **0x20000 when construction flags == 0x10** (ship buildings) |
| `GameQuery_IsOwnedCellFree` 0052f3d0 | none of 0x1, 0x80, 0x100 |
| `NNavy::AStar::GetStepCost` 005bba90 | see §6.4 |

### 5.5 Nothing is recomputed at load `[known]`

- `NMap::System::Load` 00672030 reads the seven grids verbatim. The map PostLoad slot (vtable
  007f890c slot 3) is an empty `ret` (`Stub_EmptyVoid_5657b0`).
- `GameFile_FinishLoad` 005aa1b0 → `MapUpdateBatch_End` 005321c0 only flushes dirty rects marked
  during load; nothing is marked (`MapUpdateBatch_Begin` 00532180 resets them). `[inferred]`
- The bit derivers (`MapModifier_RefreshWaterAndCliffsAll` 00672f30,
  `MapModifier_RefreshPatternBitsAll` 00673050, `NMap::Continents::Rebuild` 00679430) are reached
  only from the built-in editor/debug tools (`FUN_00602000`, `nMenu::Debug::Update` 00609130,
  `nMenu::Debug::HandleToolClick` 00604dd0), Lua doodad edits, or per-cell edits.
- Entity and navy loaders (deposits, list-2 doodads, spawns, harbors, exits, docks, routes) do not
  set their grid bits.
- Rebuilt at load, so **not stored**: construction map (`ConstructionMap_Init` 00675cc0), object
  layers (`NMap_ObjectLayers_Init` 00672d10), A\* grids, AI low-res grids. `[known]` for the Init
  calls, `[inferred]` that they are filled later.

**Consequence: an external editor must write GridStatesMap and Map Continents fully consistent with
everything else.** Shipped maps do carry a few stale values (§6.7), and the game accepts them as
stored.

### 5.6 Continent partition algorithm `[known]`

`RecomputeAll` 00679120 + `FloodFillContinent` 00678d70 + `RecountLandCells` 00678010. Reproduced
byte-exact, neighbour lists included, on 20/22 samples (`contfull.py`; the other two have 6 and 10
stale cells, §8).

1. Scan cells row-major (y outer, x inner). An unassigned cell seeds continent `id = next++` if:
   no 0x400; kind = (bit 0x4 set ? water : land); for land also: pattern not blocked and no 0x40.
2. DFS with an explicit stack (pop from the back). For each popped cell, visit neighbours in the
   order dir 4, then the cells reached by stepping 0, 1, 2, 3, 4 from there (SW, SE, E, NE, NW, W).
   - Unassigned neighbour passing the same test with the same kind → joins.
   - Assigned neighbour with another id → appended to the neighbour list if absent.
3. Consequences: dense ids; water and land are separate continents; neighbour lists contain only
   lower ids; cells with 0x400, and land cells with 0x40 or a blocked pattern, keep −1.
4. cellCount, bbox, isWater per continent, and the trailing landCellCount follow from the grid.

### 5.7 Cliff-bit algorithm `[known]`

`CliffMarker_ResolveRect` 0067bdf0 over the whole map, **x outer, y inner**. Reproduced exactly
(`cliff.py`).

1. Clear bit 0x40 everywhere.
2. For each cell C with neither 0x40 nor 0x4, for dirs 0..5: act on in-bounds neighbours N with
   neither 0x40 nor 0x4 whose slope class C→N is ±4.
3. Trial-mark N; count "unresolved cliff-edge" cells in the 19-cell radius-2 spiral around C → A.
4. Unmark N, mark C, count again → B.
5. If B < A keep C marked and stop with this cell; otherwise unmark C, keep N marked and continue.

"Unresolved edge" (`0067bab0`): the cell has neither 0x40 nor 0x4 and has a neighbour, also without
0x40 and 0x4, at slope class ±4.

---

## 6. Harbors in depth

### 6.1 What a harbor is `[known]`

| Fact | Evidence |
|---|---|
| A harbor in a map is **not a building**. It is a *harbor place*: a record in `Navy System` → `Navy Harbors`. No sample contains a `VillageBuilding`, and `buildings.lua` defines no harbor building. | tag scan; `hb_buildings.lua` |
| The harbor becomes active when a player places a **flag exactly on the harbor cell**: `Logic_PlaceFlag` 00538cd0 → `NavyHarborList_FindAtPos` 005b5d20 (exact x,y match) → `NavyHarbor_AttachBuilding` 005b49f0. | code |
| The visible harbor model `z_harbor_00` is spawned from the Navy record at PostLoad (`S2CG::Scene::OnHarborCreated` 00682ec0 via `NotifyNavy_Slot88`). A correct record is what makes the harbor visible. | code |
| **Ship routes are stored in the map, never computed by the game.** The only creator is the built-in editor tool (`DebugShipRouteTool_*` 0078d7c0..0078d960 → `NavyShipRouteList_Create` 005b7990). | code |
| **Nothing about harbors is recomputed at load**: no exits, no grid bits, no validation (`NNavy::System::Load` 005b4650 uses default ctors; `NavyHarbor_CreateExits` is not called). | code |
| Ships are built only at the shipyard, which needs **ship ground** (pattern 0xdecade01 → bit 0x20000) (§6.6). | code + data |

Harbors in the samples `[known]`: 9 of 22 maps, 62 harbors, 135 exits, 270 docks, 34 routes, 649
route cells.

| Map | Navy System @ | Harbors | Routes | Ship-ground cells |
|---|---|---|---|---|
| MP_6P_ship_ahoi | 0x21bcfb | 12 | 6 | 34 |
| MP_2P_oases | 0x172f57 | 12 | 8 | 15 |
| MP_6P_middle_of_nowhere | 0x24448b | 12 | 6 | 13 |
| MP_4P_quicksand | 0x1e8adf | 8 | 4 | 14 |
| MP_2P_fata_morgana | 0x14d1da | 4 | 2 | 3 |
| MP_2P_thick_grove | 0x1c2b81 | 4 | 2 | 6 |
| sp05_icebound | 0x150ab1 | 4 | 2 | 4 |
| MP_2P_ladybird_isle | 0x21bd9b | 3 | 2 | 5 |
| sp01_ring_of_brodgar | 0x1b09dc | 3 | 2 | 4 |
| 13 other maps | — | 0 | 0 | **0** |

### 6.2 Navy System byte layout `[known]`

`Unique` = 20 bytes, `Cell` = 20 bytes (§2.3). NONE = Unique with i64 `ffffffff ffffffff`.

```
NavySystem                              NNavy::System::Store 005b35d0 / Load 005b4650
  hdr(3,"Navy System")
  bool32 initialized                    = 1
  u32    shipCount                      = 0   (ship record layout undocumented; maps never have ships)
  ShipRouteList
  HarborList                            (routes come BEFORE harbors)

ShipRouteList                           NavyShipRouteList_Store 005b7610 / Load 005b7a10
  hdr(0,"Navy ShipRoutes")
  bool32 loaded                         = 1
  u32    count ; count × Route

Route                                   NavyShipRoute_Store 005b6de0 / Load 005b7530
  hdr(1,"navy ShipRoute")               MUST be v1: v0 does not read street+path -> stream desync
  Unique routeId
  Unique harborA                        harbor owning the exit == path[0]
  Unique harborB                        harbor owning the exit == path[last]
  hdr(0,"Logic ReferncesShip") ; u32 0  (sic; ReferencesShip_Store 007757f0; runtime refs, empty)
  Unique street                         NONE
  u32    pathLen ; pathLen × Cell

HarborList                              NavyHarborList_Store 005b6430 / Load 005b6830
  hdr(0,"Navy Harbors")
  bool32 loaded                         = 1
  u32    count ; count × { u32 harbourPropertyId ; Harbor }

Harbor                                  NavyHarbor_Store 005b5170 / Load 005b59d0
  hdr(2,"navy harbor")                  MUST be v2 (v<2: extra ReferencesShip list; v0: no flag ref)
  Unique harborId
  i32    player                         = -1
  Cell   harborCell
  u32    exitCount ; exitCount × Exit   in direction order
  Unique flag                           NONE

Exit ("Ship Route Position")            NavyHarborExit_Store 005bc290 / Load 005bc700
  hdr(0,"Ship Route Position")
  u32    dockCount                      = 2
  dockCount × Dock
  Unique route                          the route whose path starts/ends here, else NONE
  Cell   exitCell

Dock                                    NavyDockingPosition_Serialize 005bc830 / Deserialize 005bc860
  hdr(0,"Navy Docking Position")
  Unique ship                           NONE
  Cell   dockCell
```

Sizes: Dock = 52; Exit = 16 + 52·docks + 40 (= 160 with 2 docks); Harbor = 4 + 12 + 20 + 4 + 20 + 4
+ Σexit + 20; Route = 12 + 60 + 16 + 20 + 4 + 20·pathLen. Empty Navy System = **60 bytes**
(e.g. glacial_cave 0x1bb25e–0x1bb29a). All sizes match the samples. `[known]`

**Annotated: ship_ahoi harbor #0 (0x21caef–0x21cd23, 564 bytes)** `[known]`

```
21caef  85 19 aa aa                               harbourPropertyId 0xaaaa1985 ("south west")
21caf3  02000000 0fa9e53e 0b000000                hdr(2,"navy harbor")
21caff  00000000 dd2dfdc5 0e000000 8b5d0200 00000000   harborId Unique 155019
21cb13  ffffffff                                  player -1
21cb17  00000000 a2fe4954 0d000000 24000000 47000000   harborCell (36,71)
21cb2b  03000000                                  exitCount 3
21cb2f  00000000 7f63cde0 13000000                hdr(0,"Ship Route Position")   exit dir 0
21cb3b  02000000                                  dockCount 2
21cb3f  hdr(0,"Navy Docking Position") Unique NONE Cell(33,68)        dock 0 = cell+(-3,-3)
21cb73  hdr(0,"Navy Docking Position") Unique NONE Cell(33,67)        dock 1 = cell+(-3,-4)
21cba7  00000000 dd2dfdc5 0e000000 eaab0200 00000000   route Unique 175082
21cbbb  Cell(34,68)                               exitCell = cell+(-2,-3) = route 175082 path[0]
21cbcf  exit dir 1: docks (34,67),(32,66); route NONE; exit (33,66)
21cc6f  exit dir 2: docks (31,68),(32,67); route NONE; exit (32,68)
21cd0f  ffffffff ffffffff (Unique NONE)           flag
21cd23  c3 04 c0 8b                               next harbor: prop 0x8bc004c3 ("east")
```

**Annotated: start of ship_ahoi Navy System** `[known]`

```
21bcfb  03000000 2d50a451 0b000000   hdr(3,"Navy System")
21bd07  01000000 00000000            initialized 1, shipCount 0
21bd0f  00000000 318a08d6 0f000000   hdr(0,"Navy ShipRoutes")
21bd1b  01000000 06000000            loaded 1, count 6
21bd23  01000000 2dd1271c 0e000000   hdr(1,"navy ShipRoute")   route #0
21bd2f  Unique 175082                routeId
21bd43  Unique 155019                harborA
21bd57  Unique 175051                harborB
21bd6b  hdr(0,"Logic ReferncesShip") 00000000
21bd7b  Unique NONE                  street
21bd8f  17000000                     pathLen 23, then 23 × Cell (34,68) … (48,55)
21cadb  00000000 57d5035c 0c000000   hdr(0,"Navy Harbors")
21cae7  01000000 0c000000            loaded 1, count 12
```

### 6.3 Harbor properties and exit geometry `[known]`

Source: `scripts/properties/harbors.lua` (decrypted: `mapping/work/mapdoc/scratch/hb_harbors.lua`). `hp_create(hex)`;
`hp_setWaterStreetPosition(id, dir, dx, dy)` sets the exit offset (+0x20 + dir·8);
`hp_setShipPosition(id, dir, k, dx, dy)` sets dock offset k (+0x40) (setters 0054b120 / 0054b1a0).
The **property id is the harbor's facing**; there is no orientation field. Any other id crashes
(`Properties_GetHarbourProperty` 00547720).

| id (u32 in file) | name | dir → exit offset ; dock offsets |
|---|---|---|
| 0xaaaa1985 | south west | 0→(−2,−3);(−3,−3),(−3,−4) · 1→(−3,−5);(−2,−4),(−4,−5) · 2→(−4,−3);(−5,−3),(−4,−4) |
| 0xf7b86903 | north west | 0→(−2,3);(−3,3),(−3,4) · 1→(−3,5);(−2,4),(−4,5) |
| 0xcc08fcb3 | south east | 0→(2,−3);(3,−3),(3,−4) · 1→(3,−5);(2,−4),(4,−5) |
| 0xd2b08953 | north east | 0→(2,3);(3,3),(3,4) · 1→(3,5);(2,4),(4,5) |
| 0x6c9c81d3 | north | 0→(0,3);(−1,3),(1,3) · 1→(0,5);(−1,5),(1,5) |
| 0xf252e1d3 | south | 0→(0,−3);(−1,−3),(1,−3) · 1→(0,−5);(−1,−5),(1,−5) |
| 0x8bc004c3 | east | 0→(3,0);(3,−1),(3,1) · 1→(5,0);(5,−1),(5,1) |
| 0x8f84b743 | west | 0→(−3,0);(−3,−1),(−3,1) · 1→(−5,0);(−5,−1),(−5,1) |

- **Offsets are applied as plain `(x+dx, y+dy)`, with no hex row-parity correction**
  (`NavyHarbor_CreateExits` 005b5850: `harbor.pos + ftol(offset)`). 135/135 stored exits and 270/270
  docks equal `harborCell + offset` exactly. `[known]`
- A direction with offset (0,0) is skipped; up to 4 directions; the data uses 2 or 3. `[known]`

### 6.4 Placement and validity rules

**Harbor cell** (`GameQuery_CanPlaceHarborAt` 0052eda0, the built-in editor's check; and
`GameQuery_CanPlaceFlagAt` 0052f8a0, the in-game flag check):

| # | Rule | Source | Shipped data | Tag |
|---|---|---|---|---|
| H1 | Inside the map | 0052eda0 | 62/62 | `[known]` |
| H2 | Harbor cell has **none of** 0x1, 0x4, 0x20, 0x40, 0x80, 0x100, 0x400 (and no 0x2000 from another harbor) | 0052eda0 | 62/62 | `[known]` |
| H3 | **Buildable ground 0x200 is NOT required** | 0052eda0 never tests it | 12/62 harbor cells lack it (seaground, sand, rock 0x2010, ship ground 0x22008) | `[known]` |
| H4 | No other harbor cell within hex distance 1 (flag ring check `NMap::GridStates::AnyRingCellHasMask` 0052e780). The editor check intends this too, but its loop indexes the centre cell (bug). | 0052f8a0, 0052eda0 | 62/62; min harbor distance 3 | `[known]` |
| H5 | Harbor cell has a **land continent id ≥ 0** (its island) | `Navy_AreContinentsConnectedForPlayer` 0052eba0 | 62/62 | `[known]` |
| H6 | At least one direction passes the exit test E1 | 0052eda0 → `GameQuery_IsHarborOrientationValid` 0052e8f0 | — | `[known]` |
| H7 | For the flag in play: cell owned by the player and free (`GameQuery_IsOwnedCellFree` 0052f3d0: no 0x1/0x80/0x100), no flag within radius 1, no 0x2000 on the 6 ring cells | 0052f8a0 | — | `[known]` |

**Exit and docks** (`GameQuery_IsHarborOrientationValid` 0052e8f0 at placement;
`NavyHarborExit_IsValid` 005bbf40 when keeping):

| # | Rule | Shipped data | Tag |
|---|---|---|---|
| E1 | Exit offset non-zero; exit and both docks in the map | 135/135 | `[known]` |
| E2 | Exit and both docks are **free water** (0x4 set, 0x400 clear; `GameQuery_IsFreeWaterCell` 0052e360) | 132/135 (3 stale, §6.7) | `[known]` |
| E3 | Both docks have the **same continent id as the exit** | 132/135 | `[known]` |
| E4 | Exit cell has no 0x4000 / 0x8000 from another harbor or route (the editor re-test reads the exit twice instead of the docks: bug) | — | `[known]` |
| E5 | Exits stored in direction order; **the stored exit list is authoritative** and never re-derived. Any valid subset may be stored. ring_of_brodgar's two "sw" harbors store dirs 0–1 though dir 2 is valid. | — | `[known]` that only the stored list is used |

**Routes** (creation: `DebugShipRouteTool_Begin` 0078d7c0, `AddPoint` 0078d960, finish via
`Navy_CheckHarborExitPair` 0052d920; linking: `NavyHarbor_AttachRouteToExit` 005b54a0,
`NavyShipRoute_AttachHarbor` 005b6a50):

| # | Rule | Shipped data | Tag |
|---|---|---|---|
| R1 | path[0] is a stored exit of harborA whose route field = this route; path[last] likewise for harborB | 34/34 | `[known]` |
| R2 | harborA ≠ harborB; hex distance(path[0], path[last]) > 2 | 34/34 | `[known]` |
| R3 | Consecutive cells are hex neighbours (§5.1); no cell repeats | 615/615 steps | `[known]` |
| R4 | Every path cell is free water in **one** water continent (the exits' one) | 648/649 (1 stale) | `[known]` |
| R5 | **No two routes share a cell** (`ShipRouteAStar::GetStepCost` 005bb9d0 returns −1 on 0x8000) | 649 cells, all distinct | `[known]` |
| R6 | A path may cross docks and **non-endpoint** exits | 10 dock crossings, 2 foreign-exit crossings | `[known]` |
| R7 | **At most one route per exit**; a harbor may serve several routes through different exits | 56 harbors with 1 routed exit, 6 with 2 (oases ×4, ladybird_isle, ring_of_brodgar) | `[known]` |
| R8 | Route endpoints may join harbors on the same land continent (thick_grove) | 2 routes | `[known]` |
| R9 | pathLen ≥ 2 (`NNavy::Movement::AdvanceRouteLeg` 005b99d0 reads path[1]); shortest shipped = 8 | — | `[inferred]` |
| R10 | Every harbor has ≥ 1 routed exit | 62/62 | observed; requirement `[inferred]` (an unrouted harbor loads but connects to nothing) |

### 6.5 Derived structures and runtime behaviour `[known]`

| Stage | Function | Effect |
|---|---|---|
| Load | `NNavy::System::Load` 005b4650, `NavyHarbor_Load` 005b59d0, `NavyHarborExit` Load 005bc700 | Default ctors (`NavyHarbor_ctor` 005b57c0, `NavyHarborExit_ctor` 005bc580, `DockingPosition::ctor` 005bca00, `NavyShipRoute_ctor` 005b7120). No grid writes, no `CreateExits`, no validation. |
| Grid bits | Only creation ctors/dtors call `SetHarborBit`, `SetHarborExitBit`, `SetDockingBit`, `SetShipRouteBit` (via `NavyShipRoute_MarkPathCells` 005b6b30) | Bits 0x2000/0x4000/0x800/0x8000 come **only** from the stored GridStatesMap. |
| PostLoad | `NNavy::System::PostLoad` 005b3a90 | Rebuilds ship A\*; per route (`FUN_005b6af0`) relinks harborA/B/street by Unique (`ReferenceHarbor::Relink` 00539710 → `NavyHarborList_FindByUnique` 005b5cb0; unknown → NULL); per harbor (`FUN_005b5240`) relinks exit→route (`NavyHarborExit_ResolveReferences` 005bc340) and fires the harbor callback (model `z_harbor_00`). |
| Flag on harbor | `Logic_PlaceFlag` 00538cd0 → `NavyHarbor_AttachBuilding` 005b49f0 | Sets player; calls `NavyShipRoute_UpdateSeaStreet` 005b71d0 for each exit with a valid route ref. |
| Sea street | `NavyShipRoute_UpdateSeaStreet` 005b71d0 | Type-3 street harborA cell → A's exit for the route → B's exit → harborB cell, once both harbors belong to the same player and a route entry exists (created on ship assignment, `NavyShipRoute_AddMovementRef` 005b73a0). Exit found by `NavyHarbor_FindExitForRoute` 005b4e80 (route Unique match; **no match returns a static empty exit, not NULL**). Street A\* needs 0x2000 on harbor and 0x4000 on exit (`GameQuery_IsHarborExitTransition` 0052e3c0, `AStarStreet::PrepareSearch` 00776260). |
| Reachability | `Navy_AreContinentsConnectedForPlayer` 0052eba0 | Walks the player's harbors whose **harbor-cell continent** is A or B; for each exit with a valid route that has a street, takes the opposite harbor's harbor-cell continent. |
| Ship A\* | `NNavy::AStar::CanTraverse` 005bbbe0, `GetStepCost` 005bba90 | Same continent id and free water; cost −1 if not free water, 12 on 0x800 or on 0x4000&0x8000, 2 near land/0x400/0x800/map edge, else 1. Ship-route A\* (005bb9d0) also forbids 0x8000. |
| Shipyard | `GameQuery_IsBuildingFootprintFree` 0052f460; `NSettlers::Constructor::UpdateShipConstruction` 0065e770 → `NNavy::System::FindShipPlacement` 005b4370 → `ShipPlacementSearch_IsGoal` 005bbd10 | Shipyard (`SizeShip` = 16 = 0x10 in config.lua) needs 0x20000 on every footprint cell. When a ship is finished, a cell with **shore 0x8** on the building's continent within radius property+0x78 next to coast water is required, else "!No Place for Ship found!" and the shipyard is removed. (+0x78 = `bp_setWorkingRadius` is `[inferred]`.) |

Not stored, runtime only: sea streets, ships, harbor owner, flag link, ship refs. In maps: route
`street` NONE, harbor `flag` NONE, `player` −1, ships 0, all `ship` refs NONE, empty
`Logic ReferncesShip`. `[known]` for the values; effect of non-empty values `[inferred]` (dangling
refs resolve to NULL).

### 6.6 Editor checklist for a working harbor

All items `[known]` unless tagged; verified against the 62 shipped harbors.

**A. Navy System section** (once per map, also with 0 harbors)
1. Position: after `Logic Ambients`, before `Logic SpawnSystem`.
2. `hdr(3,"Navy System")`, initialized 1, shipCount 0.
3. `Navy ShipRoutes` list (v0, loaded 1) **before** `Navy Harbors` list (v0, loaded 1).

**B. Each harbor**
1. `u32 propertyId` ∈ the 8 ids of §6.3 (picks the facing).
2. `hdr(2,"navy harbor")` — exactly v2.
3. harborId: new Unique, **hi dword 0**, distinct from every other Unique, below the LogicSystem
   counter.
4. player = −1.
5. harborCell satisfying H2, H4, H5 (no 0x4/0x1/0x20/0x40/0x80/0x100/0x400; no harbor within 1; land
   continent ≥ 0). 0x200 not needed.
6. Exits, in direction order, for each kept direction:
   `hdr(0,"Ship Route Position")`, dockCount 2, 2 × {`hdr(0,"Navy Docking Position")`, Unique NONE,
   Cell `cell + dockOffset[dir][k]`}, Unique route (or NONE), Cell `cell + exitOffset[dir]`.
   Plain addition, no parity correction.
7. Keep a direction only if E1–E4 hold.
8. flag = Unique NONE.

**C. Each route** (without one, a harbor connects to nothing)
1. `hdr(1,"navy ShipRoute")` — exactly v1.
2. routeId: new Unique, hi dword 0.
3. harborA = owner of the exit at path[0]; harborB = owner of the exit at path[last].
4. `hdr(0,"Logic ReferncesShip")` + u32 0; street = NONE.
5. Path satisfying R1–R5, R7 (and R9).
6. Write the route's Unique into the `route` field of exactly those two exits.

**D. GridStatesMap** (OR-ed onto terrain bits; sets must be **exact**, rule F: 36/36 set
comparisons exact in the samples)

| Bit | Set on exactly |
|---|---|
| 0x2000 | the harbor cells |
| 0x4000 | the stored exit cells |
| 0x800 | the stored dock cells |
| 0x8000 | the union of route path cells |

**E. Map Continents** — consistent with the terrain (§5.6): exit, docks and whole path in one water
id; harbor cell on its island's land id.

**F. Ship ground** — at least one shipyard spot per sea the players should use: pattern
`0xdecade01` cells (so 0x20000 is derived and stored), with a shore cell (0x8) of the same land
continent within the shipyard radius next to the player's coast. 9/9 harbor maps have it, 0/13
non-harbor maps do; 91/98 ship-ground cells are themselves shore; in ship_ahoi every harbor has
ship ground 1–3 cells away. Requirement `[known]` (code); "one or two cells beside each harbor"
convention `[inferred]`.

**G. LogicSystem** — uid counter > every Unique written.

### 6.7 Failure modes, ranked (most likely first)

| Rank | Failure | Mechanism | Tag |
|---|---|---|---|
| 1 | **No (or broken) `navy ShipRoute` records** | The game never creates routes. Without one, `UpdateSeaStreet` has nothing to build and `AreContinentsConnected` never connects. All 62 shipped harbors have ≥ 1 route. | `[known]` |
| 2 | **Exit route-ref ↔ route Unique ↔ path-endpoint mismatch** (exit field left NONE, harborA/B swapped vs path[0]/path[last], endpoint not exactly a stored exit) | `FindExitForRoute` returns the static empty exit → sea street toward a bogus cell; `AreContinentsConnected` ignores exits with invalid refs. | `[known]` mechanism, `[inferred]` visible symptom |
| 3 | **Navy grid bits missing or not exact** (0x2000/0x4000/0x800/0x8000) | Not set by any load step. Without 0x2000/0x4000 the mode-3 street A\* cannot step harbor↔exit; flags can be placed next to harbors. Without 0x8000/0x800 ships do not path as designed. | `[known]` |
| 4 | **No ship ground (pattern 0xdecade01 → 0x20000) near a coast** | Shipyard cannot be placed, or is removed with "!No Place for Ship found!" — harbors *appear* but never carry anything. | `[known]` code + data |
| 5 | **Stream/version/encoding errors in the navy section** (route ≠ v1, harbor ≠ v2, missing `Logic ReferncesShip` sub-header, missing u32 property id before each harbor, routes after harbors, section omitted on a harbor-less map, NONE written as `ffffffff 00000000`) | Stream desync → SpawnSystem garbage, or dangling/false-valid references. | `[known]` |
| 6 | **Exit/dock geometry with hex row-parity correction**, or docks on another continent than the exit | Shipped exits/docks are exactly `cell + offset`, docks share the exit's water id. | `[known]` |
| 7 | **Continents inconsistent with terrain** | Ship A\* needs one water id along path and docks; reachability uses the harbor cell's land id. | `[known]` mechanism |
| 8 | **Harbor cell rejected for the flag** (harbor within distance 1; 0x1/0x80/0x100 on the cell; cell outside reachable territory; clicked cell ≠ record cell) | `CanPlaceFlagAt` / exact-match `FindAtPos`. Buildable ground is not needed. | `[known]` |
| 9 | **Unknown harbor property id** | Crash on load in 00547720. | `[known]` |

Stale data in shipped maps (accepted by the game as stored, not observed live) `[known]` (bytes):
ship_ahoi harbor (64,55) exit (61,55) is land (0x4018, continent 28); route 197913 crosses land
cell (54,45) (0x8008, continent 35); fata_morgana exits (19,62) and (18,64) each have a dock on land
(continent 2).

---

## 7. Cross-section consistency rules

Nothing below is checked or repaired by the loader; every rule is the editor's job.

| # | Rule | Sections involved | Tag |
|---|---|---|---|
| X1 | MapInfo W,H (+0x40/+0x44) = MapSystem W,H; every grid has W·H cells, elevations (4W+1)·(4H+1) | 2, 3, 4–10 | `[known]` (not cross-checked by the game) |
| X2 | MapInfo name (+0x24) = file base name (sidecar lookup) | 1 | `[known]` |
| X3 | Start positions: at least one per occupied slot (slotKind ≠ 0) | 1 | `[inferred]` |
| X4 | Every Unique (deposits, animals, doodads, spawns, harbors, routes) is distinct; ids share one global counter | 11–15 | `[known]` (0 duplicates in all samples) |
| X5 | **LogicSystem uid counter > max Unique.** New runtime objects (HQ, settlers, flags, ships) take ids from it; a duplicate within a class silently replaces the earlier object in its `std::map` (`StdMap_UniquePtr_Subscript`). Holds in 20/22 samples (not in Spiral/Pentagon). | 2 vs 11–15 | `[known]` data, `[inferred]` consequence |
| X6 | Unique ids written with **hi dword 0** for real objects, and `ffffffff ffffffff` for NONE | all | `[known]` |
| X7 | All references to buildings, settlers, ships, flags, streets are NONE (deposit +56, animal +224, dock ship, exit… flag, route street) | 11, 14 | `[known]` |
| X8 | Navy refs resolve inside the file: route.harborA/B → harbor Uniques; exit.route → route Unique; endpoints per R1 | 14 | `[known]` |
| X9 | GridStates terrain bits 0x1 (pattern part), 0x4, 0x8, 0x10, 0x40, 0x200, 0x20000 = recomputation from ElevationMap + PatternMap (§5.4, §5.7) | 4, 5 → 6 | `[known]` |
| X10 | 0x80 set **==** deposit cells; 0x1 also on cells of deposits whose property+0x54 ≠ 0 | 11 → 6 | `[known]` / `[inferred]` |
| X11 | 0x400 set **==** spawn cells ∪ list-2 (blocking) doodad cells | 12, 15 → 6 | `[known]` |
| X12 | 0x2000/0x4000/0x800/0x8000 sets == harbor/exit/dock/path cell sets | 14 → 6 | `[known]` |
| X13 | Map Continents = partition of §5.6 computed **after** the final GridStates bits (it reads 0x4, 0x40, 0x400) | 5, 6 → 10 | `[known]` |
| X14 | Doodad list = property class (lifetime → 1; blocking → 2; else 0); lifetime int present iff property+0x3c ≥ 0 | 12 | `[known]` |
| X15 | Map Resources cells hold {0,−1} where bit derivation changed; water resource type 0x4012e5a3 only next to shore | 7 | `[known]` |
| X16 | Every property id (pattern, deposit, animal, doodad, ambient sound, spawn, harbor, tribe, good, sacrifice) exists in `scripts/properties/*.lua` | 1, 5, 11–15 | `[known]` (all samples resolve) |
| X17 | MapInfo v15: initialGoods and sacrifices maps supplied for every tribe used | 1 | `[known]` |
| X18 | Each map gets its own valid UUID | 1 | `[inferred]` |

---

## 8. Validation and open questions

### 8.1 Reference parser

`mapping/work/mapdoc/scratch/s2m_parse.py [-v|-q] file.s2m …`

- Walks each payload **continuously from byte 0 to EOF** with the grammar of §3–§6; never searches
  for headers.
- Checks every section header (CRC32 of the exact name, length, supported version) and takes
  version branches exactly as the loaders do: `NResources::System::Load` 00540fd0 v4–v6,
  `Deposit::Load` 00542e80 v0–v1, `Animal::Load` 00541d50 v0–v3, `NResources::Movement::Load`
  00543750 v0–v1, `PathBase::Load` 00772e40 v0 / active, `Continent::Load` 00677450 v0–v4,
  `Object::Load` 00545260 v0–v1, `NavyHarbor_Load` 005b59d0 v0–v2, `NavyShipRoute_Load` 005b7530
  v0–v1, Game File Map v0.
- Fails loudly on: wrong header, unsupported version, string ≥ 0x800, impossible count, unknown or
  unsizable property id (checked against the decrypted Lua tables in `mapping/work/mapdoc/scratch/prall/`,
  `mapping/work/mapdoc/scratch/pr_*.lua`, `mapping/work/mapdoc/scratch/tr_patterns.lua`, `mapping/work/mapdoc/scratch/hb_harbors.lua`), non-empty ship or
  ship-reference lists, **non-zero bytes after the last section**.
- Warns on semantic inconsistencies: unknown ids, grid size ≠ W×H, doodads in the wrong list,
  navy cells without their grid bit, dangling navy refs, uid counter ≤ max id.

Companion checks: `verify.py`, `patverify.py`, `cliff.py`, `contfull.py` (terrain recomputation),
`ent_gridcheck.py`, `ent_dupids.py` (entity bits and ids), `hv_check.py` (all harbor/route rules of
§6.4).

### 8.2 Result

`python3 mapping/work/mapdoc/scratch/s2m_parse.py -q mapping/work/mapdoc/samples/*.s2m` → **22/22 parsed to EOF** (re-run for this
document). `[known]`

| Item | Result |
|---|---|
| Sample set | 22 decrypted maps: the 20 installed `Freegamemaps/*.s2m` plus MP_3P_Spiral and MP_5P_pentagon (from the upload; not in the local install). There is no 23rd sample. |
| Slack | Zero-only, 4–124 bytes in every file. |
| Warnings | 2: MP_3P_Spiral (counter 2845 ≤ max id 1941480473) and MP_5P_pentagon (counter 57079 ≤ max id 1992236637), caused by random 31-bit spawn ids. No navy warnings anywhere. |
| ship_ahoi / oases ranges | Identical to §3.1 and to the independent per-lane parsers. |
| Terrain recomputation | Bits 0x4, 0x8, 0x10, 0x40, 0x200, 0x20000 and the pattern part of 0x1: exact on 22/22. Continents: byte-exact on 20/22 (Spiral, Pentagon: 6 and 10 stale cells, Continent v3). |
| Entities | 18,655 deposits, 2,018 animals, 95,543 doodads, 167 ambients parse; 0x80 and 0x400 set identities exact on 22/22. |
| Navy | 62 harbors / 135 exits / 270 docks / 34 routes; rule table §6.4 as stated; navy bit sets exact on 9/9 harbor maps. |
| Version deviations | `resources` v4, `Resources Animal` v2, `Map Continent` v3 in MP_3P_Spiral and MP_5P_pentagon only (older writer). |

### 8.3 Open questions

| # | Question | Status |
|---|---|---|
| Q1 | Does the loader verify the container's plaintext CRC32 / size (`FileCrypt_PackAndEncrypt` 006ee8e0, key hash)? | not examined |
| Q2 | `NNavy::Ship` record layout (`Ship::Load` 005bb0f0) | unknown; maps always have 0 ships |
| Q3 | Element layout of a non-empty `Logic ReferncesShip` list (probably a 20-byte Unique `[guess]`) | always empty in maps |
| Q4 | Meanings of MapInfo +0x1cc (water preset?), +0x1ec, +0x1f0; confirmation of +0x48/+0x68/+0x88/+0xa8/+0xc8/+0x1c8 meanings | `[inferred]`/`[guess]` |
| Q5 | `resources` tail ints +0x5c, +0x60, +0x08 (=100) and the v4 32-byte block | unknown (12 / 32 bytes) |
| Q6 | Animal `counter` (+220) | unknown (4 bytes) |
| Q7 | Class behind `NMap::System+0x28` ("Map Exploration") | unresolved |
| Q8 | The 4 zero slack bytes and non-0x80 alignment of Spiral/Pentagon | unexplained |
| Q9 | Legacy layouts not sized by the parser: Map Continents v0, MapInfo < 15, ElevationMap v0 | not needed for writing |
| Q10 | In-game effect of stale exits/docks/path cells (§6.7) and of a route whose endpoints do not resolve | not observed live |
| Q11 | Effect of non-NONE street/flag/ship refs in a map (NULL resolve vs crash) | not tested |
| Q12 | `MilitaryGatheringPositions_Compute` 00576fb0 dereferences `NavyHarborList_FindNearestInWaterBody` without a NULL check; a map with an unreachable island lacking a harbor is a crash candidate | `[inferred]` |
| Q13 | Shipyard search radius = property+0x78 = `bp_setWorkingRadius` | `[inferred]` |
| Q14 | Reader of `cfg_setMaxWaterStreetWaterDepth(4000)` (GameConfig +0x40); might constrain sea routes by depth | not found |
| Q15 | GridStates bit 0x1000 | never set; unknown |
| Q16 | Whether campaign `.s2m` files contain only the map part | no decrypted campaign sample |
| Q17 | AI-only harbor data (`NAI::Player::AddHarbor`, `ai_forbidHarborPosition`) | out of scope |

---

## Appendix A: section headers used in a map

`{i32 version, u32 crc32(name), u32 len(name)}`. Versions are the ones current maps are written
with; the initialiser address is the static `g_LogCategory_*` initialiser (from `st_cats.json`).
All values `[known]` (CRC computed with zlib CRC32 and matched in the sample bytes).

| Name | Version | CRC32 | Len | Initialiser |
|---|---|---|---|---|
| `Game File Map` | 1 | 0x79a90889 | 13 | 007c61d0 |
| `MapInfo` | **15** (written by `Store` 00529db0; category default 7) | 0xc835b682 | 7 | — |
| `LogicSystem` | 8 | 0xa5e2d1a2 | 11 | 007c01e0 |
| `MapSystem` | 0 | 0x46de35ee | 9 | 007ca310 |
| `ElevationMap` | 1 | 0x820b2871 | 12 | 007ca500 |
| `PatternMap` | 0 | 0x75c888b4 | 10 | 007ca5a0 |
| `GridStatesMap` | 0 | 0x5620eaf4 | 13 | 007ca970 |
| `Map Resources` | 0 | 0x7cc3bbb0 | 13 | 007ca8d0 |
| `Map Territory` | 0 | 0x7ad16978 | 13 | 007ca830 |
| `Map Exploration` | 1 | 0x1325f73d | 15 | 007ca6e0 |
| `Map Continents` | 1 | 0xb84dad23 | 14 | 007ca780 |
| `Map Continent` | 4 | 0xff625c62 | 13 | 007ca640 |
| `resources` | 6 | 0xef66ebae | 9 | 007c0db0 |
| `deposit` | 1 | 0x95db9d39 | 7 | 007c0f90 |
| `Resources Animal` | 3 | 0x6a528ae4 | 16 | 007c0e50 |
| `Navy Movement` | 1 | 0x0d5b6777 | 13 | 007c6820 |
| `Resources Path` | 0 | 0x1b70e493 | 14 | 007c10d0 |
| `Movement Path Base` | 1 | 0x9cba071b | 18 | 007cb550 |
| `Movement Base` | 0 | 0x705402ae | 13 | 007cb4b0 |
| `Movement Interpolator` | 0 | 0x08708cf6 | 21 | 007cb870 |
| `DoodadsSystem` | 0 | 0x8ebccc3c | 13 | 007c1170 |
| `DoodadsObject` | 1 | 0xef5c765b | 13 | 007c1210 |
| `Logic Ambients` | 0 | 0x4ea029ce | 14 | 007c05d0 |
| `Navy System` | 3 | 0x51a4502d | 11 | 007c6430 |
| `Navy ShipRoutes` | 0 | 0xd6088a31 | 15 | 007c66d0 |
| `navy ShipRoute` | 1 | 0x1c27d12d | 14 | 007c6630 |
| `Logic ReferncesShip` (sic) | 0 | 0x25f83c79 | 19 | 007cbc30 |
| `Navy Harbors` | 0 | 0x5c03d557 | 12 | 007c6590 |
| `navy harbor` | 2 | 0x3ee5a90f | 11 | 007c64e0 |
| `Ship Route Position` | 0 | 0xe0cd637f | 19 | 007c6aa0 |
| `Navy Docking Position` | 0 | 0xff078720 | 21 | 007c6b40 |
| `Logic SpawnSystem` | 0 | 0xb894f028 | 17 | 007c0320 |
| `Logic Spawn` | 0 | 0x4a807674 | 11 | 007c08a0 |
| `logic UniqueId` | 0 | 0xc5fd2ddd | 14 | 007c0720 |
| `PatternCursor` | 0 | 0x5449fea2 | 13 | 007ca450 |
| `ElevationCursor` | 0 | 0x6f47851d | 15 | 007ca3b0 |
| `Core UUID` | 0 | 0x2c7c8b9a | 9 | 007c3120 |
