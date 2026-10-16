# Save games: the store interface and the file format

Binary: `sadk_noav.exe` (image base 0x400000). Tags: **[known]** = read in the code or data at the given place
(`S 00xxxxxx` = address in the binary); **[inferred]** = one step of reasoning from what was read; **[TODO]** = not
established. Nothing here has been observed in the running game.

Related documents, not repeated here:

- `docs/asset-formats.md` §1: the encrypted container (key, scramble, LZSS) every save and map file is wrapped in.
- `docs/map-format.md`: the byte layout of the map part (sections `Game File Map` ... `Logic SpawnSystem`), the
  section header, the small records (cell, unique, UUID), the map types and folders.
- `docs/multiplayer-save.md`: saving and loading inside a network match, the menu gates.
- `docs/sim/logic-core.md`, `players-victory.md`, `village-buildings.md`, `settlers-jobs.md`,
  `streets-transport.md`, `military.md`, `navy.md`, `ai-player.md`, `map-resources.md`: §7 of each lists the fields
  of that subsystem's records.

---

## 1. Purpose and scope

The save system writes the complete deterministic simulation state of a running match into one file and reads it
back into a freshly built (or already populated) world.

It is responsible for:

- the serialisation interface every simulation object implements (`NCore::IStoreable`) and the four stream classes
  that consume it (encrypted file, plain file, checksum, text dump);
- the file container and the two parts of a save (map part, logic part), the order of the subsystems in them, the
  per-section version numbers and the rules for reading older versions;
- the save folder, file naming, autosave, emergency save, the load and save panel, "Continue";
- starting a game from a save and the post-load pass that rebuilds everything that is not stored.

It is not responsible for:

- the layout of each subsystem's own records beyond their first layer (see the per-subsystem documents);
- the user profile (`settings.cfg`, map states), which uses the same stream classes but is a different file;
- the network session: a save contains none of it (`docs/multiplayer-save.md`).

A save has **no thumbnail, no time stamp, no play time, no description and no separate header block**. What the load
menu shows is the file name only (§3.7). The only metadata readable without loading the world is the `MapInfo`
section, which is the first section after the 12-byte file tag (§2.5) [known] S 0060da50, S 005aa030.

---

## 2. Data model

### 2.1 `NCore::IStoreable`

Every storable object starts with (or embeds) a vtable of this shape [known] vftable S 007d4fbc (the base destructor S 00663dd0 restores it at the end of every derived destructor):

| Slot | Offset | Name | Meaning |
|---|---|---|---|
| 0 | +0x00 | scalar deleting destructor | |
| 1 | +0x04 | `Store(stream)` | write the object to the stream |
| 2 | +0x08 | `Load(stream)` | read it back; the object already exists (constructed empty or with a "for load" ctor) |

The subsystem classes and most simulation objects add a fourth slot [known] S 005273d0, S 00559cd0, S 006654f0:

| Slot | Offset | Name | Meaning |
|---|---|---|---|
| 3 | +0x0c | `PostLoad()` | called once after the whole file was read: resolve references by unique id, re-register with maps, indexes and callbacks |

Conventions that hold across the code [known]:

- `Store` and `Load` take the stream as their only argument and call the stream's virtual slots (§2.2). They never
  seek, never write a length, never look ahead. **The file is the plain concatenation of every `Store` call in
  call order.** One wrong field shifts everything after it.
- An object's `Store` normally begins with a section tag (§2.4) naming its class, and its `Load` begins by reading
  that tag and keeping the stored version number to decide which fields exist.
- Objects with identity embed an `NLogic::Unique` (64-bit id) and store it first. Pointers to other objects are
  never stored; a `Reference*` member stores the target's `Unique` (S 00538db0) and its `Relink` resolves the
  pointer in `PostLoad` through the owning system's id lookup (S 00538620 flag, S 00539710 harbor, S 00539790 ship
  route, S 0053a480 ship, S 0053dc00 fight, S 0053dc80 deposit, S 0053dd00 package, S 0053ddb0 projectile,
  S 0053e2f0 fight group, S 0053e7c0 order, S 0053a570 settler; one class `NLogic::Reference<Kind>` each). All
  eleven classes (and `ReferenceSoldier`, which inherits the settler's `Relink`) share slot 1 `Store` S 00538db0
  and slot 2 `Load` S 0059d3c0, which reads the `Unique` and sets the cached pointer (+0x18) to 0 [known: the
  vftables S 007e7bbc .. S 007e7ec4]. `Relink` (slot 3) runs the lookup only when the id's high dword (+0x14) is
  in 0..0x7fffffff and stores its result at +0x18; every lookup returns 0 when nothing matches, so a stale or
  invalid id leaves a null pointer [known]. The containers [known]:

  | Reference | Lookup | Container searched |
  |---|---|---|
  | Flag | `NNet::System::FindFlagByIdAnyPlayer` S 00665070 | the per-player `std::map` by unique (`flagById[p]`), players 0..7 in turn, first hit |
  | Harbor | `HarborList::FindByUnique` S 005b5cb0 | `navy->harbors` vector, linear |
  | Ship route | `ShipRouteList::FindByUnique` S 005b75a0 | `navy->shipRoutes` vector, linear |
  | Ship | `NNavy::System::FindShipByUnique` S 005b3810 | the navy's ship vector, linear, comparing the `Unique` returned by ship slot 0 |
  | Fight | `FightList::FindById` S 00573720 | `military->pFightList` vector, linear |
  | Deposit | `NResources::System::GetResource` S 0053ebc0 | the resource system's `std::map` by unique |
  | Package | S 00573720 (the same folded code) | the first vector of `transport->packageSystem`, linear |
  | Projectile | `ProjectileList::FindById` S 00573de0 | `military->pProjectileList` vector, linear |
  | Fight group | `FightGroupList::FindById` S 005742f0 | `military->pFightGroupList` vector, linear |
  | Order | `OrderSystem::FindOrderByUnique` S 00562210 | `village->orderSystem` order vector, linear |
  | Settler | `NSettlers::System::FindSettlerByUnique` S 006546b0 | six settler vectors in the order +0x04, +0x14, +0x24, +0x44, +0x34, +0x54 |
- Many classes have a second writer, named `StoreUntagged`, `StoreForChecksum` or `StoreBody` in the map. It writes
  nearly the same fields without the section tag and without version logic and is called only for the lockstep
  checksum (§3.9). It never reaches a file.
- Settlers are stored through vtable slot +0x0c, not +0x04 [known] S 00654270. Slots 1 and 2 of a settler are
  those of its `Unique` base [inferred].

### 2.2 The stream interface (`NCore::Stream`)

Base object [known] S 00581800: `+0x00` vtable, `+0x04` `std::string name`. The vtable has 26 slots; the names are
those of the mapped `Stream_vftable` struct [known] vftables S 007e9d3c (base), S 00834f04 (`FileStreamCrypt`),
S 007e9c5c (`FileStream`), S 007e9ccc (`CRCStream`), S 00834f74 (`DumpStream`).

| Slot | Off | Name | File encoding (`FileStream`, `FileStreamCrypt`) |
|---|---|---|---|
| 0 | +0x00 | destructor | |
| 1 | +0x04 | `Open(path, mode)` | mode 0 = read, 1 = write |
| 2 | +0x08 | `Close()` | |
| 3 | +0x0c | `IsOpen()` | |
| 4 | +0x10 | `GetSize()` | |
| 5 | +0x14 | `BeginReadSection(category)` | reads 12 bytes, discards all (S 007804f0) |
| 6 | +0x18 | `ReadBinary(buf, n)` | n raw bytes |
| 7 | +0x1c | `ReadString(out)` | u32 length, then that many bytes, no terminator (S 007808d0) |
| 8 | +0x20 | `ReadFloat(out)` | 4 bytes, IEEE-754 single |
| 9 | +0x24 | `ReadUShort(out)` | 2 bytes |
| 10 | +0x28 | `ReadInt64(out)` | 8 bytes |
| 11 | +0x2c | `ReadBool(out)` | **4 bytes**, value != 0 (S 00780490) |
| 12 | +0x30 | `ReadInt(out)` | 4 bytes |
| 13 | +0x34 | `ReadULong(out)` | 4 bytes |
| 14 | +0x38 | `ReadSizeT(out)` | 4 bytes |
| 15 | +0x3c | `ReadSection(category)` → version | reads 12 bytes, returns the first dword (S 0057cf80) |
| 16 | +0x40 | `BeginWriteSection(category)` | writes 12 bytes (S 0057cfc0, §2.4) |
| 17 | +0x44 | `WriteBinary(buf, n)` | n raw bytes |
| 18 | +0x48 | `WriteString(str)` | u32 length, bytes (S 00780580) |
| 19 | +0x4c | `WriteFloat(v)` | 4 bytes (S 0057cff0) |
| 20 | +0x50 | `WriteUShort(v)` | 2 bytes (S 00780540) |
| 21 | +0x54 | `WriteInt64(v)` | 8 bytes (S 0057d010) |
| 22 | +0x58 | `WriteBool(v)` | **4 bytes**, 0 or 1 (S 00780520) |
| 23 | +0x5c | `WriteInt(v)` | 4 bytes (S 0057cff0) |
| 24 | +0x60 | `WriteULong(v)` | 4 bytes |
| 25 | +0x64 | `WriteSizeT(v)` | 4 bytes |

All values are little-endian, unaligned, unpadded [known] (every typed slot forwards a stack copy of the value to
`WriteBinary` / `ReadBinary`). `FileStream` and `FileStreamCrypt` share every typed slot; they differ only in the
destructor, `Open`, `Close`, `IsOpen`, `GetSize`, `ReadBinary`, `WriteBinary` (slots 0-4, 6, 17) [known] (vtable
contents S 00834f04, S 007e9c5c). So a plain `FileStream` file
(`settings.cfg`, the `.info` cache) has byte for byte the encoding of a decrypted save.

Slots 5 and 15 read the same 12 bytes. Loaders that never had a second version call slot 5; loaders with version
logic call slot 15 [known] e.g. S 00538a20 vs S 005be500.

`ReadString` copies into a 0x800-byte stack buffer with no length check [known] S 007808d0: a stored length of
0x800 or more overflows the stack. A reimplementation must bound it. After the read the buffer is terminated at
the stored length and the result is assigned up to the **first zero byte** (`strlen`), so a stored string with an
embedded zero byte comes back truncated although the stream has advanced by the full stored length [known]
S 007808d0.

### 2.3 The four stream classes

| Class | Size / members | Used for | Tag |
|---|---|---|---|
| `NCore::FileStreamCrypt` | base + `+0x20` inner `MemoryStream *`, `+0x24` file buffer, `+0x28` file size, `+0x2c` mode | saves and maps: `.aav`, `.sav`, `.s2m`, `.a2m` | [known] S 007807f0, S 007805d0 |
| `NCore::FileStream` | base + `+0x20` Win32 file handle | `settings.cfg`, map states, the `<map>.info` cache, the editor's copy buffer | [known] S 0057d140; callers S 005792c0, S 00579430, S 005aa030, S 006015f0 |
| `NCore::CRCStream` | base + `+0x20` CRC-32 accumulator, `+0x28` active byte | the lockstep checksum (§3.9), the game-settings CRC | [known] S 0057d270, S 00784080, S 00414720 |
| `NCore::DumpStream` | base + `+0x20` `FILE *` | the text dump written on a desync (§3.10) | [known] S 00780bb0, S 005ab220 |

**`FileStreamCrypt`** works on memory, not on the file [known]:

- `Open(path, 0)`: reads the whole file and decrypts it (`NBase::gReadFileData` + `NBase::gDecryptData` through
  S 006e7770), wraps the plaintext in a read-only `MemoryStream`. `Open` returns true if the inner stream exists.
  There is no "file not found" result: `gReadFileData` leaves a null buffer for a missing, unreadable or empty
  file (S 006e6d40), neither S 006e7770 nor `Open` tests it, and `gDecryptData` reads the header through that
  pointer at once (S 006e6660), i.e. the process faults on a read at address 4. The callers test for the file
  with `Fs_FileExists` S 0057d060 first (§3.4, §3.11); `GameFile_LoadImpl` does not guard its last fallback.
- `Open(path, 1)`: creates an empty growing `MemoryStream` (initial capacity 0x400, growth step 0x80).
- `Close()` in write mode: resolves the path, `CreateFileA(GENERIC_WRITE, share read|write, CREATE_ALWAYS)`, takes
  the stream's buffer and size, computes the CRC-32 of the plaintext, derives the file key from the file name,
  packs and encrypts (`FileCrypt_PackAndEncrypt` S 006ee8e0), writes the 20-byte container header and the payload,
  frees everything. Returns true only if the file was created. Nothing is written to disk before `Close`.
- `Close()` in read mode: frees the buffer and the inner stream.

**`CRCStream`** [known] vtable S 007e9ccc: every read slot and **`BeginWriteSection` are no-ops** (`ReadSection`,
slot 15, returns −1, S 007809c0); `WriteBool` feeds
**one** byte (S 0057d300), `WriteInt` / `WriteULong` / `WriteSizeT` / `WriteFloat` four bytes (S 0057d360),
`WriteUShort` two, `WriteInt64` eight, `WriteBinary` the buffer, and `WriteString` **the first four bytes of the
string's buffer whatever its length** (S 0057d3d0). `Begin(name)` resets the accumulator, `GetCrc()` returns it.
`Begin` (S 0057d400) and `End` (S 0057d430) sit in the `Open` and `Close` slots (1 and 2) [known] (vtable
contents).

**`DumpStream`** [known] vtable S 00834f74: `Open(path, mode)` is `fopen(path, "w")` and refuses mode 0. Each write
slot prints one text line: section tag as `Chunk: '<name>' Ver: <version>, Crc32: 0x<crc of the name>`
(S 00780b70), bool as `bool: true` / `bool: false` (S 00780aa0), binary data only as `Binary Data: <n> Byte`
(S 00780a20), int as `int: %d` (S 00780a40), float as `float: %f` (S 00780b10), int64 as `int64: %I64d`
(S 00780ad0), ushort as `unsigned short: %hd` (S 00780af0), and a string as `"%s" (%d)` with the text and its
length and **without a line break** (S 00780b30), so the next line continues on the same text line; ulong as
`unsigned long: %u` (S 00780a60, slot 24) and size_t as `size_t: %d` (S 00780a80, slot 25).
The read side does nothing [known] (vtable contents S 00834f74): `GetSize` (slot 4, S 006c8d50) and `ReadSection`
(slot 15, S 007809c0) return −1; `BeginReadSection`, `ReadBinary` and the eight typed read slots 7..14 are empty
functions (S 0064b9c0, S 00472360) that leave their output argument untouched.

### 2.4 Section tag

Each tag is a static `LogCategory` object: `+0x04` name string, `+0x1c` current version, `+0x20` CRC-32 of the name,
`+0x24` name length [known] S 0057cfc0, S 00780b70. `BeginWriteSection` writes 12 bytes:

| Off | Type | Field |
|---|---|---|
| 0 | i32 | version (the compiled-in current version of that class's layout) |
| 4 | u32 | zlib CRC-32 of the section name |
| 8 | u32 | length of the section name in bytes |

The reader uses only the version and **never compares the CRC or the length with the expected section**
[known] S 0057cf80, S 007804f0. There is no end-of-section mark and no section length. Details and examples:
`docs/map-format.md` §2.2. The current version of every section is listed in Appendix A.

### 2.5 The container and the two parts

On disk [known], `docs/asset-formats.md` §1:

| Off | Type | Field |
|---|---|---|
| 0x00 | u32 | container version `0x06091812` |
| 0x04 | char[4] | `"sadk"` |
| 0x08 | u32 | CRC-32 of the plaintext |
| 0x0c | u32 | CRC-32 of the 16-byte file key |
| 0x10 | u32 | plaintext size |
| 0x14 | ... | scrambled, LZSS-packed payload |

- The key of a `.aav` or `.s2m` file is the shared base key; every other extension, **`.sav` included**, mixes the
  lower-case file name into the key, so such a file only decrypts under its own name [known] S 006eeac0
  (`docs/asset-formats.md`). A `.aav` save can be renamed freely.
- The plaintext size written is the memory stream's **capacity**, so a game-written payload is padded with zero
  bytes to the next 0x80 step; the reader never reaches the padding [known], `docs/map-format.md` §3.2.
- The reader checks, in this order, the magic `"sadk"`, the key CRC, the unpacked size and the data CRC; on
  each mismatch it logs a line and then writes to address 0, a deliberate crash. It does **not** compare the
  container version at 0x00 [known] S 006e6660 (`NBase::gDecryptData`; it never calls the version getter
  S 006ee670 the writer uses).

Plaintext of a save [known] S 005aa260:

```
+--------------------------------------------------------------+
| map part    GameFile_SaveMap    S 005a9fa0                    |
|   tag "Game File Map" v1                                      |
|   MapInfo, LogicSystem, MapSystem (7 grids), resources,       |
|   DoodadsSystem, Logic Ambients, Navy System, Logic SpawnSystem|
+--------------------------------------------------------------+
| logic part  GameFile_SaveLogic  S 005a9ec0                    |
|   tag "Game File Logic" v6                                    |
|   Logic Random, PlayerSystem, VillageSystem, SettlersSystem,  |
|   Transport System, MilitarySystem, Net System, AI System,    |
|   LogicStatistics, GameScript, Logic Quests, Sacrifice System,|
|   Logic ChestSystem                                           |
+--------------------------------------------------------------+
| zero padding to the buffer capacity                           |
+--------------------------------------------------------------+
```

A map file (`.s2m`) is the map part alone. The map part of a save has the same sections in the same versions as a
map; the difference is the content (territory, exploration, grid state bits, ships, animals and deposits carry the
running match) [known] S 005aa260: the same `GameFile_SaveMap` writes both.

### 2.6 File types, folders, names

`ai::game::MapPath` = `{ +0 i32 mapType, +4 std::string fullPath }`; `fullPath` = directory + file name + extension
[known] S 0052c880, S 0052c320, S 0052c1b0, S 0052c100.

| Type | Extension | Directory | Content read by the loader |
|---|---|---|---|
| 0 | `.s2m` | `[data]\maps\freeGameMaps\` | map part |
| 1 | `.s2m` | `[data]\maps\campaignMaps\` | map part |
| 2 | `.s2m` | `[data]\maps\tutorialMaps\` | map part |
| 3 | `.s2m` | `<My Documents>\SAdK\maps\` | map part |
| 10 | `.sav` | `<My Documents>\SAdK\saves\` | map part + logic part |
| 100 (0x64) | `.s2m` | `[data]\maps\freeGameMaps\` | map part |
| 101 (0x65) | `.a2m` | `[data]\maps\campaignMaps\` | map part + logic part |
| 102 (0x66) | `.s2m` | `[data]\maps\tutorialMaps\` | map part |
| 103 (0x67) | `.s2m` | `<My Documents>\SAdK\maps\` | map part |
| 110 (0x6e) | `.aav` | `<My Documents>\SAdK\saves\` | map part + logic part |

- **Every save the game writes is type 110: `<My Documents>\SAdK\saves\<name>.aav`** [known]: all four runtime
  callers of `GameFile_Save` pass 0x6e (S 0060d000, S 0060d5b0, S 0078af30, S 005da7d0). The fifth caller, the
  debug / editor screen, passes type 1 (a map export into `campaignMaps`, §3.1 step 8) [known] S 00609130.
  Type 10 (`.sav`) is only
  ever read, as a fallback [known] S 005aaed0, S 005dfef0, S 005aaa30. Which build wrote `.sav` files into the
  save folder, and whether they were containers, is [TODO]: this build holds no writer of type 10, so only
  `.sav` files written by an old installation (or its executable) can settle it (§10 #5). The one `.sav` in the
  install (below) carries a `Game File Logic` tag of the current version 6 next to an old `MapInfo` v9, so it
  comes from an earlier build of this game, not from another product [inferred].
- Type 101 (`.a2m`) is a campaign file that carries a logic part, i.e. a prepared scenario state
  [inferred] from S 005aaed0 and S 005ac770 (type 0x65 is treated as a started game: `onStarted` runs). The
  install holds no `.a2m` file [known] (file search of the `data` tree). It holds exactly one `.sav`:
  `data\game\maps\campaignMaps\C02.sav`, in a folder no map type pairs with the `.sav` extension, so
  `MapPath` cannot name it [inferred] S 0052c1b0, S 0052c320. That file is **not a container**: it starts
  directly with the plaintext of §2.5 (`Game File Map` v1 at offset 0, `MapInfo` **v9** at 0x0c, `LogicSystem`
  **v7** at 0x1a1, `MapSystem` at 0x1dd, `Game File Logic` v6 at 0x1c0a6d, then `Logic Random`, `PlayerSystem`,
  `VillageSystem`) and is 2 158 976 bytes long, a multiple of 0x80 [known] (the file's bytes). It is a complete
  map part + logic part written by an older build without the encryption wrapper; `FileStreamCrypt` cannot open
  it, a plain `FileStream` could. No code names it: the image holds the bytes `.sav` once (S 007e7a4c), referenced
  only by `MapPath_GetFileExtension` for type 10, whose folder is the save folder, and holds no `C02` literal
  [known] (byte search, xrefs); so the file is unused by this build [inferred]. Its section versions are older
  than this build's (Appendix A) almost throughout [known] (the file's tags): `MapInfo` v9 (15), `LogicSystem` v7
  (8) followed by the obsolete `TriggerSystem` section that the v < 8 gate of §3.5 skips, `resources` v5 (6),
  `PlayerObject` v0 (1), `SettlersSystem` v0 (1), `VillageBuilding` v1 (2), `AI Player` v2 (7), `Sacrifice System`
  v3 (4), among others; `Game File Logic` v6 is already current. So the build that wrote it is older than the
  current one in nearly every subsystem.
- The save folder is created on demand by `Fs_CreateUserDataDirectories` S 0057bfb0 before every save [known].
- File name: the name given, with each of `* / : < > ? \` replaced by `_` [known] S 005aa260. `"` and `|` are not
  replaced.

| Name | Source | Tag |
|---|---|---|
| `<YYYY>-<MM>-<DD> <hh>-<mm>-<ss> <localised map name>` | default text of the save panel's edit box; local time, two-digit fields zero-padded, the year unpadded; the map name is `MapInfo.mapName` passed through the localisation table | [known] S 0060dd90 |
| `Autosave` | autosave; one file, overwritten each time. The name is the bare prefix string (global S 0087e920): the function reads the local time but its only stream insertion is that string | [known] S 0078af30 (callees: one string inserter, no number inserter), string initialiser S 007c6310 |
| `_EmergencySave_` | written when Windows reports low battery (window message 0x218 `WM_POWERBROADCAST` with wParam 9 `PBT_APMBATTERYLOW`), only if the game screen exists and is active; then the application's running flag is cleared, so the game quits. No offline check: it also runs in a network match | [known] S 005da7d0, S 00401f30 |

### 2.7 Globals that are part of the saved state

| Global | Meaning | Stored by |
|---|---|---|
| `DAT_00889ad0` (i64) | next unique id | `LogicId_StoreGlobal` S 00538760, inside `LogicSystem` |
| `DAT_00889b00` (bool), `g_TrivialObj_00889b08` (8 bytes) | logic random generator: initialised flag, then the 8 raw bytes of the generator object: `+0` state u32 (the word `Rng_ParkMillerNext` S 006ec350 advances), `+4` seed u32 (S 006ec2a0 stores the seed there; `LogicRandom_SetUp` S 00538980 restarts with state = seed & 0x7fffffff, or 1 if the seed is 0, S 006ec280) [known] | `LogicRandom_Save` S 005389c0 |
| `DAT_0088b314` (bool), `g_GameScript_MapScriptPath`, `g_GameScript_ScriptData` (map string → int) | map script: loaded flag, script path, the `sd_setValue` store | `GameScript_Store` S 005b0f30 |
| `DAT_0088a4d0` (u32), map at `DAT_0088a4e0` (size `DAT_0088a4e4`) | attack path-length cache: tick stamp, entries. The second, transient cache of the same class is not written (`docs/sim/military.md`) | `NMilitary::Attack::Store` S 00575740 |
| `g_MapWidth`, `g_MapHeight` and the vertex sizes | set from `MapSystem` on load | `docs/map-format.md` §4.4 |

---

## 3. Rules and algorithms

### 3.1 Saving: `GameFile_Save(mapType, name)` S 005aa260 [known]

1. Copy the name; replace `* / : < > ? \` by `_`.
2. Show the busy cursor (cursor 1, visible), remembering the previous visibility.
3. `Fs_CreateUserDataDirectories()`.
4. Build the `MapPath` from type and name.
5. If the type is **not** 10 and not 110 (map export from the built-in editor): set `MapInfo.mapName` to the name
   and `MapInfo` width and height to the map's.
6. `FileStreamCrypt::Open(path, 1)`. On failure: destroy and return (the cursor is left as set in step 2).
7. Type 10 or 110:
   1. `MapInfo+0x1f0 = 1` (the save-generation number checked by "Continue", §3.8);
   2. `GameFile_SaveMap(stream)`;
   3. `GameFile_SaveLogic(stream)`;
   4. if the session is offline (`NComm_Manager_IsRole0`): store the name as the user profile's last save
      (`UserProfile+0x08`, the first string of `settings.cfg`; the profile file itself is written later, by the
      options panel or at shutdown [inferred] S 005792c0 callers).
8. Other types: only if the type is one of 0, 1, 2, 100, 102 (S 0052c270): `GameFile_ResetWorldForMapExport()`
   (removes buildings, remains, orders, streets, flags, settlers, ships, animals on blocked cells, per-player map
   grids; resets tick timing, tick counter = −1; S 005aa150), then `GameFile_SaveMap(stream)`. For every other
   type (3, 101, 103) nothing is written into the stream, so the file holds **no section at all**, only the
   0x400 zero bytes of the untouched initial buffer [known] (no branch writes anything; `Close` still creates the
   file and takes the buffer capacity as size, S 007805d0, S 00412120).
9. `Close()` (this is where the file is written), restore the cursor.

`GameFile_Save` returns nothing; a failed write is not reported to the caller or the player [known].

Saving does not pause, does not flush pending commands and changes no simulation state other than `MapInfo+0x1f0`
[known] for the top-level function; [inferred] for the `Store` functions (they are also used for the per-tick
checksum variants and are written as pure readers).

### 3.2 Order of the map part: `GameFile_SaveMap` S 005a9fa0 [known]

| # | Call | Section(s) |
|---|---|---|
| 0 | `BeginWriteSection` | `Game File Map` v1 |
| 1 | `NLogic::System::Save` S 005275c0 | `MapInfo` v15 (the `MapInfo` object's own `Store` S 00529db0), then `LogicSystem` v8 |
| 2 | `map->Store` (`NMap::System::Store` S 00671930) | `MapSystem` and its seven grids |
| 3 | `resources->Store` S 0053e960 | `resources` (deposits, animals, animal areas) |
| 4 | `doodads->Store` S 00543bf0 | `DoodadsSystem` |
| 5 | `ambients->Store` S 00536600 | `Logic Ambients` |
| 6 | `NNavy::System::Store` S 005b35d0 | `Navy System`: bool initialised, count, per ship {i32 owner player index, `Navy Ship` record}, route list, harbor list |
| 7 | `LogicSpawnSystem::Save` S 0052cb70 | `Logic SpawnSystem` |

`LogicSystem` v8 body [known] S 005275c0: i64 next unique id; bool `running`; f32 `frameDelta`; f32 `nextTickTime`;
f32 `accumulatedTime`; u32 `tickCounter`. Field tables of all map-part sections: `docs/map-format.md` §4.

`MapInfo` v15 first layer, in write order [known] S 00529db0 (offsets in the `NLogic::MapInfo` object; meanings
in `docs/map-format.md` §4.2): position vector `+0x04` (start positions); string `+0x24` (map name); i32 `+0x40`,
i32 `+0x44` (map size); 8 × i32 `+0x48[i]`; 8 × { i32 `+0x68[i]`, i32 `+0x88[i]`, i32 `+0xa8[i]`,
i32 `+0xc8[i]` }; i32 `+0x1c8`; i32 `+0x1cc`; i32 `+0x1d0` (map type); the UUID record of the object at `+0x1d4`
= tag `Core UUID` v0, bool valid (`+0x1d8`), 16 raw bytes (`+0x1dc`) (S 0057ce20), but if the valid byte is 0
the writer stores a temporary, freshly generated UUID (valid = 1, `UuidCreate`, S 0057ce00) in its place and
leaves the object unchanged, so two saves of such a world carry different UUIDs; bool `+0x1ec`; 8 strings
(player names, `+0xe8`, 0x1c bytes apart); i32 `+0x1f0`; position vector `+0x14`; u32 count and per entry
{ i32 tribe key, good-amount list } (map at `+0x1f8`, ascending key); u32 count and per entry { i32 key, i32
vector } (map at `+0x204`, ascending key).

### 3.3 Order of the logic part: `GameFile_SaveLogic` S 005a9ec0 [known]

| # | Call | Top section | First layer of content |
|---|---|---|---|
| 0 | `BeginWriteSection` | `Game File Logic` v6 | |
| 1 | `LogicRandom_Save` S 005389c0 | `Logic Random` v0 | bool initialised; 8 raw bytes (state u32, seed u32) |
| 2 | `PlayerTable::Store` S 005bde00 | `PlayerSystem` v0 | bool neutral-initialised; 8 × { i32 slot index or −1; if not −1 a `PlayerObject` } |
| 3 | `village->Store` S 00557cc0 | `VillageSystem` v0 | bool `flagBC`; buildings; remains; `Order System` |
| 4 | `settlers->Store` S 00654420 | `SettlersSystem` v1 | bool `flag64`; six settler lists |
| 5 | `transport->Store` S 0064cdd0 | `Transport System` v0 | bool; `Package System`; `Transport PackageNeedSystem`; `Transport BuildingNeedSystem` |
| 6 | `military->Store` S 0056ffe0 | `MilitarySystem` v0 | bool; `Military Distances`; `Military Allocation`; `Military Attack`; projectiles; fights; fight groups |
| 7 | `net->Store` S 006640d0 | `Net System` v3 | bool; flags; streets; 16 flag-network maps; `Net StreetNetContinentIds` |
| 8 | `ai->Store` S 00581ad0 | `AI System` v2 | bool; 8 × { `AI Player`; military map if the player is active }; u32 tick; resource map; low-res resource map; bool enabled |
| 9 | `statistics->Store` S 00537280 | `LogicStatistics` v2 | i32 count; productivity entries; 8 × `LogicPlayerStatistics` |
| 10 | `GameScript_Store` S 005b0f30 | `GameScript` v0 | bool; string script path; u32 count; count × { string key, i32 value } |
| 11 | `quests->Store` S 00535ef0 | `Logic Quests` v3 | bool; i32 40; 40 × `Logic Quest` |
| 12 | `NSacrifice::System::Store` S 0065f500 | `Sacrifice System` v4 | bool; 8 × `Sacrifices Player Data` |
| 13 | `LogicChestSystem::Save` S 0052d200 | `Logic ChestSystem` v1 | bool initialised; u32 count; chests; bool enabled |

The first layer of each, in write order (types as in §2.2: "bool" is 4 bytes in the file):

**2. Players** [known] S 005be3c0. `PlayerObject` v1: bool active; string name; i32 index; i32 colour; i32 kind
(1 AI, 2 local human, 3 remote human; `docs/multiplayer-save.md`); i32 tribe property id; `Good Priorities`; `Good Arrangement`;
`Player Military`; `Messages`; goods `Stock` (only this one item is conditional: written if active); i32 update
phase; `Player ShipNames`; i32 team;
8 × { bool spotted, bool reached, cell reachedPos }; mobile `Stock` (always written); i32 state.
The loader reads both stocks only if the active bool is set (S 005be500); the writer's unconditional mobile stock
never disagrees with that because `PlayerTable::Store` writes a `PlayerObject` only for active players
(S 005bde00) [known]. Before reading a stock the loader empties it if its initialised byte (`Stock +0x04`) is set,
and for an active player sets that byte to 1 before the stock's own `Load` [known] S 005be500. In `Player Military`
the eight ignore-distance flags are bools, so 4 bytes each in the file (32 bytes), although the object holds them
as one byte each [known] S 005c09d0.
Field lists of the sub-records: `docs/sim/players-victory.md` §7.

**3. Village** [known] S 00557a20, S 00557b60, S 00561f90. Buildings: i32 count; per building in vector order
{ i32 building property id, i32 owner player index, `VillageBuilding` record (`Building::StoreSavegame`
S 0055c470) }. Remains: i32 count; per entry, in ascending unique-id order of the remains map, two i32 ids (the
first dword of the two objects the remains object points to at `+4` and `+8`; both are handed to the "for load"
constructor, S 00559b90) and a `VillageRemains` record. The first id is a **remains property id**, the second a
**building property id**: the constructor resolves them with `PropertiesDb::GetRemainsProperty` and
`GetBuildingProperty` into `+4` and `+8` [known] S 00563fc0. A remains entry carries no owner player.
Orders: `Order System`.
Building record (`VillageBuilding` v2, components in the order of `StoreSavegame` S 0055c470; the hit points under
the tag `Village Hitpoints`): `docs/sim/village-buildings.md` §7.

**4. Settlers** [known] S 00654270. Six lists in kind order 0..5 (worker, constructor, carrier, soldier,
specialist, NPC); each: u32 count; per settler { i32 owner player index, i32 settler property id, the settler's
record through vtable slot +0x0c }. Records: `docs/sim/settlers-jobs.md` §7.

**5. Transport** [known]. A package container (`NTransport::PackageContainer`, e.g. inside the flag package stacks of
`docs/sim/streets-transport.md` §7) stores its count as an **i32**, not as the stream's u32 count (`PackageContainer::Store` S 0064dd40). `Package System` (S 0064f640): bool initialised; u32 count; per package { i32 owner
player index, `Transport Package` (unique, good id, location, target, two ints; S 00651530) }.
`Transport PackageNeedSystem` (S 00650080): bool; u32 count; targets. `Transport BuildingNeedSystem` (S 00651840):
bool; u32 count; `Transport NeedGood` records.

**6. Military** [known]. `Military Distances` (S 00574dc0): i32 update countdown. `Military Allocation`
(S 00574920): i32 update countdown. `Military Attack` v1 (S 00575740): u32 tick stamp; u32 count; count ×
{ u32 packed cell-pair key, i32 path length }, in ascending key order. `Military Projectiles` (S 00573e50): bool;
u32 count; projectiles. `Military Fights` (S 00573790): bool; u32 count; fights. `Military FightGroups`
(S 00574360): bool; u32 count; groups. Records: `docs/sim/military.md` §7 (the soldier record in the member
order of `Soldier::Store` S 00658960). After the load, `NMilitary::Attack::PostLoad` S 00575800 empties the
transient path-length cache and stamps it with the tick counter of the loaded game [known].

**7. Street net** [known] S 006640d0. bool initialised; u32 total flag count; for player 0..7, each flag in vector
order { i32 owner player index, `Flag` record }; u32 total street count; for player 0..7, each street { i32 owner
player index, `NetStreet` record }; then 16 maps (8 players × 2), each: u32 count; per entry { unique key, u32 inner
count, inner count × { unique, i32 cost } } in ascending id order; then `Net StreetNetContinentIds` (S 0066d8e0):
bool; u32 count; per entry { unique, u32 n, n × i32 continent id, cell }. Records: `docs/sim/streets-transport.md`.
The 16 maps are the array at `NNet::System +0x1d0` (0x0c bytes each), written and read in index order
player × 2 + k, k = 0, 1 (outer loop 8 players, inner loop 2) [known] S 00668050. k is the net kind: map
`player × 2 + 0` caches the costs over goods streets (kind 0), `player × 2 + 1` over all streets (kind 1, walking);
both readers index the array as `flagNetworks + netKind + owner × 2` (`GetFlagPathCost` S 00667f30,
`GetFlagNetworkValue` S 00664e70) [known]. How the costs are computed: `docs/sim/streets-transport.md`
§2.7. The loader inserts with
`map[key][inner key] = cost`, so duplicate keys in a file collapse to the last value [known] S 00668050.
In the continent-id record the n ids are the members of a `set<int>` (ascending), and the cell is looked up in a
second map by the same unique [known] S 0066d8e0; the loader rebuilds three containers from it: unique → id
set, id → set of uniques, unique → cell [known] S 006707f0.

**8. AI** [known] S 00581ad0, S 00583180. In `AI System` the military map of slot i is written when the **logic**
player i (player table entry) is active, not the AI player. `AI Player` v7: bool active; i32 AI profile id
(−1 none); only if active, in this order: start position (cell); construction system; needs arrangement; needs
construction; resource-map adds; low-res resource-map adds; four id-keyed maps (buildings, needs A, needs B,
productions); territory map; cell system; expansion system; military system; resource system; destruction
system; need creation; locksmith; food arrangement; goods arrangement; production control; conquered
continents; nine bools (expansion, coin production, needs, sacrifices, catapults, one unnamed profile flag, ship
construction, foresting, attack allowed); the harbor map; forbidden harbor positions (cell vector); an int
vector; bool enabled.
The second layer (the records of each AI part) is in `docs/sim/ai-player.md` §7: the field list of every AI
section type of Appendix A after its tag, in stream order, with the encodings of the shared value types, the
version gates of each `Load` and the values of fields an old version does not carry [known there].

**9. Statistics** [known] S 00537280: i32 count; per productivity entry { unique, item }; 8 player records.

**10. Script** [known] S 005b0f30: only the `sd_setValue` / `sd_getValue` key-value store and the script path. The
map iterates in ascending key order (string compare) [inferred: `std::map<std::string, int>`].

**11. Quests** [known] S 00536000. `Logic Quest` v5: i32 state; string id; bool; bool; cell marker position; string
text; bool changed; u32 `field54`; u32 text-changed tick.

**12. Sacrifices** [known] S 00662b40, S 00661dd0. `Sacrifices Player Data` v4, per player: u32 count and per
running sacrifice { i32 owner player index, i32 sacrifice definition id, `Sacrifice Sacrifice` record };
regenerations; research; dependencies; free tickets. `Sacrifice DataDependencies` v2: bool; **i32** count (not the
stream's u32 count); count × { i32 definition id, bool } (`docs/sim/quests-sacrifices-stats.md` §7). The running
sacrifices are read by `SacrificePlayerData::LoadSacrifices` S 00662390 (called from `Load` S 00662ba0): per entry
the owner index and definition id, a sacrifice constructed with its "loaded" flag, its `Load`, `push_back`; after
the list it recomputes the modifier table of all players (`SacrificePlayerTable::RecomputeModifiers` S 00662fb0),
so the modifiers are not stored but derived [known].

**13. Chests** [known] S 00539360. `Logic Chest` v0: unique; cell; i32 owner player; i32 content kind; if kind is
1: i32 good id, i32 good count; otherwise one u32 value; i32 open progress in ticks.

Polymorphic lists follow one pattern [known]: count, then per element the data needed to construct it (owner
player index and/or property id) **before** the element's own record, because the loader must allocate the right
class with the right owner before it can call `Load`.

### 3.4 Loading: `nGame_File_load` → `GameFile_LoadImpl(mapType, name, suspend)` S 005ab180, S 005aaed0 [known]

1. `nGame_File_load` logs `File::load (type %d) %s`, shows the busy cursor, calls `GameFile_LoadImpl`, restores the
   cursor.
2. If `suspend`: `CallbackManager::Notify_Slot00(0)` and `MapUpdateBatch_Begin` (map-change notifications are
   collected, not delivered).
3. Build the path for (type, name). If the file does not exist: try type 10 (`saves\<name>.sav`); if that does not
   exist either: type 3 (`<My Documents>\SAdK\maps\<name>.s2m`). The type variable follows the fallback. The
   type-3 path is used whether or not that file exists (its existence test is made and the result dropped).
4. `FileStreamCrypt::Open(path, 0)`. If none of the three files exists the process faults inside `Open`
   (null read in `gDecryptData`, §2.3); `Open` returns false only if the inner stream could not be allocated.
   If it opens:
   - types 0, 1, 2, 3, 100, 102, 103: `GameFile_LoadMap`;
   - types 10, 101, 110: `GameFile_LoadMap`, then `GameFile_LoadLogic`;
   - any other type: result false;
   - `Close()`.
5. **Always**, also when `Open` returned false or the type was not one of the above: `GameFile_FinishLoad(suspend)`.
6. The result is dropped by `nGame_File_load` [known]: no caller learns that a load failed.

`GameFile_LoadMap(mapType, stream)` S 005aa7b0 [known]:

1. `v = ReadSection("Game File Map")`.
2. `NLogic::System::Load`: `MapInfo::Load` (version gates 1..15, `docs/map-format.md` §4.2), then `LogicSystem`
   (§3.5).
3. `map->Load`, `resources->Load`, `doodads->Load`, `ambients->Load`, `NNavy::System::Load`.
4. If `v > 0`: `LogicSpawnSystem::Load`.
5. Map script: take `MapInfo.mapType` (`+0x1d0`, the type the match was started from). If it is 10 or 110, or if
   the `mapType` argument is 1, use the argument instead. Build the `MapPath` of (that type, `MapInfo.mapName`),
   replace the extension by `.lua`, and call `GameScript_LoadMapScript(path)` S 005b1fe0.
   **So a save runs the map script of the map it was started from, found by the map name stored in the save**
   [known].

`GameFile_LoadLogic(stream)` S 005a9db0 [known]: `v = ReadSection("Game File Logic")`, then

| Step | Condition | Call |
|---|---|---|
| 1 | `v > 0` | `LogicRandom_Load` S 00538a20 |
| 2 | always | `PlayerTable::Load` S 005be1b0 |
| 3 | always | `village->Load` S 00559c80 |
| 4 | always | `settlers->Load` S 00656430 |
| 5 | always | `transport->Load` S 0064ce30 |
| 6 | always | `military->Load` S 00570050 |
| 7 | `v < 4` | `NNavy::System::Load` (old saves had the navy here; since v4 it is in the map part only) |
| 8 | always | `net->Load` S 00668050 |
| 9 | always | `ai->Load` S 005821f0 |
| 10 | always | `statistics->Load` S 005384f0 |
| 11 | `v > 1` | `GameScript_Load` S 005b2780 |
| 12 | `v > 2` | `quests->Load` S 00535f40 |
| 13 | `v > 4` | `NSacrifice::System::Load` S 0065f650 |
| 14 | `v > 5` | `LogicChestSystem::Load` S 0052d600 |

Each system's `Load` empties itself before reading [known]: `PlayerTable::Load` removes all players and resets the
neutral player; `LoadBuildings` calls `ClearBuildings`; `NSettlers::System::Load` clears the six vectors;
`NMilitary::System::Load` clears projectiles, fight groups and fights; `NNet::System::Load` calls `Clear`;
`NAI::System::Load` calls `Reset`; `NSacrifice::System::Load` resets and re-inits the player table;
`LogicChestSystem::Load` resets if initialised. `GameScript_Load` and `Quests::Load` do not clear first
[known] S 005b2780, S 00535f40:

- Quests: the loader calls `Load` on the first N slots only. A current file always holds N = 40, i.e. every
  slot (S 00535ef0); only a file of `Logic Quests` version < 3 (5 or 10 quests) leaves the other slots as they
  were.
- Script store: each stored pair is written with `map[key] = value` (S 005b2780, disassembly: the value read by
  `ReadInt` is stored through the pointer `operator[]` returns); keys that are in memory but not in the file
  survive. On the normal path the store is empty at that point, because `GameScript_InitMapScript` S 005b2720
  (called by `BuildWorld` before the load, §3.8) erases the whole map, clears the script path, sets the loaded
  flag and creates a new Lua thread [known]. Only the debug screen's load into a running world (§3.8) reads on
  top of an existing store [inferred].

`GameFile_FinishLoad(resume)` S 005aa1b0 [known]:

1. If the UI is not suppressed (`nMenu::System+uiSuppressed == 0`): call slot +0x1c of the object returned by
   `Global_0088ca60_Get` (the singleton at S 0088ca60). The object is the 3D scene (`S2CG::Scene`, vtable
   S 007f8f2c) [inferred] (the getter's users are the render and HUD code); the slot function S 0067eb10 copies
   the logic system's just-loaded `nextTickTime` (`NLogic::System +0x78`) into the scene object's `+0x48`
   [known]. It changes no simulation state.
2. `NLogic::System::PostLoad()` (§3.6).
3. `CEnviromentMgr::LoadMapEnvData(MapInfo.mapName)`: the `<map>.bin` lighting sidecar.
4. If `resume`: `Notify_Slot00(1)`, `MapUpdateBatch_End`.

### 3.5 Version rules

There is **no check that rejects a file**: no loader compares a section version against a maximum, and section
names are not verified (§2.4). A newer or foreign section is read with the current layout and silently
desynchronises the stream [known] by the absence of such checks in the loaders read. The only checks that exist:

| Check | Where | Effect |
|---|---|---|
| Container magic `sadk`, key CRC, size, data CRC (not the container version) | `NBase::gDecryptData` S 006e6660 | log line, then a deliberate crash (write to address 0) |
| File missing or empty | `FileStreamCrypt::Open(path, 0)` | not a check: null read, the process faults (§2.3) |
| `MapInfo+0x1f0 >= 2` (accepted: 0 and 1) | "Continue" only, S 005dfef0 | message `!INVALID_SAVEGAME` (title `!INVALID_FILE`); the load panel does not check it |
| File exists as `.aav`, else `.sav` | "Continue", S 005dfef0 | message `!FILENOTFOUND` (title `!FILENOTFOUND_TITLE`) |

`MapInfo+0x1f0` is stored from `MapInfo` v9 on (older: 0), defaults to 1 (`MapInfo::Reset` S 0052b8d0), and
`GameFile_Save` writes 1 [known] S 0052bd40, S 005aa260. Its intended meaning is a save-generation number: a
build that wrote 2 would be
refused by this build [inferred].

Backward compatibility is per section: `Load` reads the stored version and skips or defaults what older versions
did not have. Gates of the top-level sections [known]:

| Section (current) | Rule |
|---|---|
| `Game File Map` (1) | v0: no `Logic SpawnSystem` section |
| `Game File Logic` (6) | table in §3.4 |
| `LogicSystem` (8) | v1..5: one extra i32 after `running`, discarded; v ≥ 4: the three floats, and if `nextTickTime <= accumulatedTime` then `accumulatedTime = nextTickTime − 0.01`; v < 8: an obsolete section `TriggerSystem` { bool, i32 } is read and discarded; v ≥ 7: `tickCounter` (S 00527d60) |
| `PlayerObject` (1) | v0: no `state`; it becomes 2 (S 005be500) |
| `SettlersSystem` (1) | v0: no NPC list (S 00656430) |
| `MapInfo` (15) | v ≥ 2: the two map-size ints; v ≥ 3: per player the ints `+0x68`, `+0x88`, `+0xa8`, and v ≥ 6 also `+0xc8`; v ≥ 1: `+0x1c8`; v ≥ 4: `+0x1cc`; v ≥ 5: `+0x1d0`; v ≥ 7: the UUID record, else the valid byte is cleared and a new UUID generated; v ≥ 8: bool `+0x1ec` and the 8 names; v ≥ 9: `+0x1f0`, else 0; v ≥ 10: the second position vector and the two maps (both emptied first). After reading: v ≤ 13 `ResetInitialGoodsFromTribes`, v ≤ 12 `ResetSacrificesFromTribes`, v ≤ 14 `NormalizeInitialGoodsForTribes` S 0052a670; **none of the three runs for a v15 file**. Last, the map name is handed to the scene (S 0067e8d0) (S 0052bd40, disassembly) |
| `Net System` (3) | v < 2: one extra i32 per street, read after the owner index and discarded; v ≥ 1: the 16 flag-network maps, else `ClearFlagNetworkCache` S 006679a0; v ≥ 3: `Net StreetNetContinentIds` is loaded (S 006707f0), else the continent-id object is only marked dirty (S 0056e140). The path finder object (0x40 bytes, S 0066bf60) is created anew between the streets and the maps in every version (S 00668050, disassembly: compares against 2 at S 0066820b, 1 at S 00668320, 3 at S 00668447) |
| `AI System` (2) | v0: no military maps in the file; v1: a military map for every player; v ≥ 2: only for active players (S 005821f0) |
| `Logic Quests` (3) | v0: `bInitialized` forced true; quest count 5 (v < 2), 10 (v2), read from the file (v ≥ 3; no bound check against the 40 slots) (S 00535f40) |
| `Logic Quest` (5) | v ≥ 1 second bool; v ≥ 2 marker cell; v ≥ 3 text; v ≥ 4 changed flag and `field54`; v ≥ 5 text-changed tick, else the current tick (S 00536090) |
| `Sacrifice System` (4) | v < 4: a flat list { count; per entry i32 player, i32 definition id, sacrifice record }, then modifiers are recomputed; v ≥ 4: per-player data (S 0065f650) |
| `Sacrifices Player Data` (4) | v ≥ 2 regenerations; v ≥ 3 research and dependencies; v ≥ 4 free tickets (S 00662ba0) |
| `Logic ChestSystem` (1) | v ≥ 1: trailing `enabled` bool (S 0052d600) |

Gates of the inner records are in the per-subsystem documents.

A writer has one version per section: the current one (Appendix A). The `MapInfo` section is the one exception: its
`Store` writes version 7 instead of 15 when `MapInfo+0x1f4` is set and then omits the bool at `+0x1ec`, the eight
names and `+0x1f0` [known] S 00529db0. The constructor clears `+0x1f4` (S 0052bc10) and no instruction in the
program writes a byte at offset 0x1f4 of a `MapInfo` afterwards (the only other byte access at that offset
besides `Store`'s three tests is a copy inside the load descriptor's assignment S 007849f0, a different
object) [known] (instruction search); so the version-7 writer is never taken in this build [inferred], and a
`.info` cache is always written as v15.

### 3.6 Post-load: `NLogic::System::PostLoad` S 005273d0 [known]

In this order:

1. For each of the 8 per-player street planners: if slot 2 of the object at planner `+0x0c` answers true, call
   that object's slot 1 with the planner's search object (`+0x04`) and set planner `+0x08` to 6 (S 00663740);
   then stop the planner (S 006638c0: `+0x0c` = 0, search object cleared and freed, active byte `+0x00` = 0).
   Then start all 8 again on the loaded map. What the object at `+0x0c` is (a pending search request) is
   [inferred].
2. `village->PostLoad` (S 00559cd0): every building's `PostLoad` followed by `IndexBuilding` (category indexes),
   in building vector order; every remains object's `PostLoad`; `OrderSystem::PostLoad`.
3. `net->PostLoad` (S 006654f0): every flag, then every street; then every street whose start or end flag
   reference is invalid is removed.
4. `NNavy::System::PostLoad` (S 005b3a90).
5. `settlers->PostLoad`.
6. `transport->PostLoad`.
7. `resources->PostLoad` (S 0053ec60).
8. `ai->PostLoad` (S 005819a0): `PostLoad` of every active AI player; the AI street planner is restarted; the two
   path analysers are reset to the map size.
9. `mapInfo->PostLoad`.
10. `doodads->PostLoad`.
11. `military->PostLoad`.
12. `map->PostLoad` (an empty function, `docs/map-format.md` §5.5).
13. `ambients->PostLoad` (S 005366f0).
14. `NSacrifice::System::PostLoad` (S 0065f540).
15. `ai::logic::LogicChestSystem::PostLoad` (S 0052d2c0): raises "chest added" for every chest, in vector order.
16. `ai::logic::LogicSpawnSystem::PostLoad` (S 0052cd70).
17. If S 0057b800 returns true: `Timer_Reset()`. S 0057b800 returns the global byte `DAT_0088a614`, the frame
    timer's "initialised" flag: `Timer_Init` S 0057b790 sets it at application start-up (both of its branches)
    and S 0057b7f0 clears it at application shutdown; nothing else writes it [known] (xrefs). So the reset
    always happens in a running game. `Timer_Reset` S 0057b990 zeroes the current time, the previous frame's
    time and the frame delta (all in ms) and takes a new start time; the next frame therefore has a frame delta
    of 0 [known] S 0057b810.

Between the steps the loader emits ten progress ticks `!Finalizing world` of weight 10 each [known].
The player table, statistics, quests and the script store have no post-load step [known] (absent from the list).

The order matters where one system's `PostLoad` looks up objects of another: buildings resolve flag, settler and
deposit references while those objects are loaded but not yet post-loaded themselves [inferred]. All lookups are by
unique id into containers filled during `Load`, so they do not depend on the other object's `PostLoad` [inferred].

### 3.7 The load and save panel `nMenu::LoadSavePanel` [known] S 0060ce40, S 0060e0e0, S 0060da50, S 0060d000

- Layout `menuLoadSave.xml`; mode 0 = load, 1 = save (constructor argument). The caption comes from the root
  attribute `textLoad` or `textSave`.
- File list: all files matching `<My Documents>\SAdK\saves\*.aav`, shown by name without folder and extension, one
  text item each. **Type-10 `.sav` files are not listed.** The first ten items get the hotkeys `0`..`9`.
  The order is the order in which `FindFirstFileA` / `FindNextFileA` return the files: the scan appends each hit
  to a string vector and neither it nor the panel sorts [known] S 006e4f00, S 006e4310, S 0060da50. That is
  name order on NTFS and creation-slot order on FAT [inferred] (file-system behaviour, not game code).
  No date, map name, player or picture is shown.
- Save mode: the edit box is pre-filled with the default name (§2.6). Confirm: if an item's name equals the text
  ignoring case, a message box asks `!Overwrite file?` (title `!Save`), and on yes the save runs; otherwise the
  panel fades out (0.2 s) and `GameFile_Save(110, text)` runs at once. The text is not checked for being empty:
  an empty edit box saves a file named `.aav` [inferred] (no length test in S 0060d000).
- Load mode: confirm copies the marked item's name into the panel; the panel's next `Update` fades out and hands the
  name to `nMenu::System::pendingMapPath`; the menu system's next `Update` calls `StartPendingMap` (§3.8).
- Delete (button `btDelete`, after a message box): `DeleteFileA("<save dir><name>.aav")`, then the list is rebuilt.
- In a network match the Save and Load entries are removed from the in-game menu (`docs/multiplayer-save.md`).

### 3.8 Starting a game from a save

Four entry points, all offline [known]:

| Entry | What it does | Tag |
|---|---|---|
| Load panel | `StartPendingMap` S 005d9fd0: close all screens; if a game runs, `nGame::System::Shutdown`; put the name into the game screen's load descriptor; NComm `Shutdown(false)`, `StartUpNetwork(0)`, `ConnectAndJoin` (a fresh offline session); read the file's `MapInfo` (`GameFile_LoadMapInfo(name, 110, info, true)`); `SetGameSettings(name, map GUID, player count = number of start positions, ..., type byte 110, ...)`; one session slot per map player from `MapInfo` (controller 2 → slot 0 human; 1 → next slot AI; anything else → next slot closed; if no player has a controller, player 0 is made the human); enter the game screen | [known] |
| "Continue" (main menu) | `ContinueLastSavegame` S 005dfef0: name = user profile's last save; type 110 if `<name>.aav` exists, else 10 if `<name>.sav` exists, else `!FILENOTFOUND`; read `MapInfo`; refuse if `MapInfo+0x1f0 >= 2`; put the name into the load descriptor; restart the offline session as above; `ActivateGameScreen`. No slots are set up here. | [known] |
| Command line `-start <file>` | `App_CmdLine_StartGameFile` S 00401420: name into the load descriptor, restart the offline session, `ActivateGameScreen` | [known] |
| Debug screen | `nGame_File_load(1, name, true)` into the running world; its Save button calls `GameFile_Save(1, name)` | [known] S 00609130; the screen has no opener in retail (`docs/subsystems.md`, not re-read) |

On all three menu and command-line paths the load descriptor is filled by `GameLoadDescriptor::SetMapName`
S 005a9c10, which sets the name **and** the map type 110 (`+0x00 = 0x6e`), the load-path selector `+0x23c = 0`
(load from a file) and `+0x240 = −1` [known]. So the world loader always asks for `saves\<name>.aav` first and
falls back to `saves\<name>.sav`, then to the user map `maps\<name>.s2m` (§3.4 step 3). A `.sav` found by
"Continue" is therefore loaded through that fallback, not by passing type 10 [inferred].

`Game_LoadWorldFromDescriptor` has a second path that reads no file: if the descriptor's selector `+0x23c` is 1
it only clears and re-initialises the logic system with `(+0x240, +0x240)` as map size and returns [known]
S 005ac770. Selector 1 is the descriptor's default state: `GameLoadDescriptor::Reset` S 005a9bb0 sets type 0,
an empty name, selector 1 and size 80 (and resets the embedded `MapInfo` at `+0x2c`); it runs in the
descriptor's constructor and in `nMenu::Game::OnLeave` S 005eb030. Only the two name setters
(`GameLoadDescriptor::SetMapName` S 005a9c10, `GameLoadDescriptor::SetMapNameAndType` S 005a9c50) put it back
to 0 [known] (instruction search for writes to `+0x23c`). Entering the game screen without setting a name
therefore builds an empty 80 × 80 world [inferred].

A user map is not started with type 3 or 103: the free-game panel always passes type 0
(`nMenu::FreeGamePanel::SetMap` S 005e8410 → `GameLoadDescriptor::SetMapNameAndType(desc, 0, name)`) and the
file is found through the loader's fallback to type 3 (§3.4 step 3). The "new game" test of step 4.3 below is
made on the descriptor's type, which stays 0, so players are created [known] S 005e8410, S 005ac770.

Then, for every entry [known] S 005eed00, S 00784d40, S 005ac770:

1. `nMenu::Game::OnEnter` → `nGame::System::BuildWorld(descriptor)`:
   1. reset the load progress channel (600 steps); register the game as NComm's command and checksum handler;
   2. `BuildScene` (constructs the game system and the 3D scene from scratch);
   3. progress `!Loading rest...`; `GameScript_InitMapScript()`; if offline, register the Lua libraries;
   4. `Game_LoadWorldFromDescriptor`:
      1. `MapUpdateBatch_Begin`, `Notify_Slot00(0)`;
      2. `nGame_File_load(type, name, false)` (§3.4): map part, logic part, post-load;
      3. only for "new game" types (0, 1, 2, 100, 102): resize AI tables, create players from the descriptor,
         and, if the session's game seed or else its game id is not 0 (a network match [inferred]), distribute
         chests. **Skipped for a save**: the players come from the file;
      4. `MapModifier_InitAfterMapLoad` S 00673000: recompute every player's construction map, announce territory
         and the local player's map;
      5. `Notify_Slot00(1)`, `MapUpdateBatch_End`;
      6. only for new-game types or type 101: store the extra start parameter, `MapInfo.mapType = type`, call the
         script's `onStarted`. **Skipped for a save**;
      7. **always**: call the script's `onLoaded` (`GameScript_CallOnLoaded` S 005b2180);
      8. mark the map as started in the user's map states;
   5. initialise cursor and camera, reset the autosave timer, start the music (only if the UI is not suppressed,
      `nMenu::System+uiSuppressed == 0`), set the running flag; if the UI is suppressed and the NComm state is
      3, `NComm_Manager::BroadcastStartGame`.

A save therefore resumes with: the map script file run again from the top by `GameScript_LoadMapScript`, then
`onLoaded()` instead of `onStarted()`. The script must rebuild its own Lua-side state from the `sd_` store and the
quest table [inferred].

`GameScript_Load` reads the stored script path into a temporary and does not use it; the script is located from
`MapInfo` (§3.4 step 5) [known] S 005b2780. The loop stores each read value under its key (§3.4) [known]
(disassembly S 005b2833 .. S 005b2854).

### 3.9 The lockstep checksum uses the same interface

`nGame::System::ComputeChecksum` S 00784080 [known] builds a `CRCStream`, `Begin("")`, and feeds, in this order:

1. `LogicRandom_Checksum`;
2. `PlayerTable::StoreChecksum` S 005bde70 (without player kind and name, `docs/multiplayer-save.md`);
3. the village system's body writers (buildings via `Building::StoreForChecksum` S 0055c690, remains, orders);
4. `NSettlers::System::StoreUntagged` S 00654490;
5. `transport->Store` (the ordinary save writer; its tags vanish in a `CRCStream`);
6. `NMilitary::System::StoreUntagged` S 00570120;
7. `NNavy::System::StoreUntagged` S 005b36a0;
8. `NNet::System::StoreForChecksum` S 00664550;
9. `NAI::System::StoreBody` S 00581b90; after it an empty function (S 0064b9c0) is called on the object at
   `NLogic::System +0x30` (the map system) with the stream: it feeds nothing;
10. `LogicId_StoreGlobal` (the next unique id);

then `GetCrc()`. Not covered by the checksum although saved: `MapInfo`, the tick counter and timing, all map grids,
resources (deposits, animals), doodads, ambients, spawns, statistics, script data, quests, sacrifices, chests
[known] (absent from the list).

The checksum writers are not always the save writers minus the tag. Differences read here [known]:

- `NNavy::Ship::StoreUntagged` S 005bb1a0 writes unique, movement, state, state countdown, expedition, ship
  number, cargo, condition, military; the save writer `Ship::Store` S 005bb060 writes the ship's
  `NavyConstruction` record after the unique in addition. Construction progress of a ship is saved but not
  hashed.
- `NNet::System::StoreForChecksum` S 00664550 includes the flag-network cost maps and calls the same
  `NetContinentIds::Store` S 0066d8e0 as the save.
- `LogicRandom_Checksum` S 00538a00 feeds the 8 generator bytes (state and seed) without the initialised bool.

Per-writer field lists: §7 / §8 of the subsystem documents (`players-victory.md`, `village-buildings.md`,
`settlers-jobs.md`, `streets-transport.md`, `military.md`, `navy.md`, `ai-player.md`) and `logic-core.md`.

### 3.10 The desync dump

`GameFile_WriteDesyncDump(baseName)` S 005ab220 [known]: writes `<dumps dir>\<baseName>.s2dump.txt` with a
`DumpStream`: the string `---- MAPS ----`, then exactly the calls of `GameFile_SaveMap`; the string
`---- LOGIK ----`, then the calls of `GameFile_SaveLogic` **without** `GameScript_Store`, the quests and the
sacrifice system, but with the chest system (S 005aa690, S 005aa540). The dumps directory is built by
`Fs_GetDumpsDirPath` S 0057bdf0 as `<My Documents>\SAdK\dumps` [known]: the game folder literal at S 007d421c
is the bytes `SAdK`, the last component is the literal `dumps` (S 0057bbd0). `Fs_CreateUserDataDirectories`
runs first.

### 3.11 The map-info cache

`GameFile_LoadMapInfo(name, type, info, allowFallback)` S 005aaa30 [known] reads only the `MapInfo` of a file:

1. Path of (type, name). If missing and `allowFallback`: type 3, then type 10. If none exists: return false.
2. Cache file `<LocalAppData>\SAdK\<name>.info` (`.usermapinfo` when found as type 3).
3. `GameFile_LoadMapInfoCached` S 005aa030: if the cache is newer than the file, `MapInfo::Load` from the plain
   cache file. Otherwise open the encrypted file, read the 12-byte file tag, `MapInfo::Load`, close; then write the
   cache with `MapInfo::Store` into a plain `FileStream`.
4. If a fallback type was used, `info.mapType (+0x1d0)` = that type.

Consequences: `MapInfo` must be the first section after the file tag; every save in the save folder leaves a
`<name>.info` file behind once its info was read (load panel start, "Continue"); the cache is keyed by name only,
so a map and a save of the same name share one cache file [inferred].

---

## 4. Update order

The save system has no per-tick work. What runs when:

| When | What | Tag |
|---|---|---|
| Per frame, in a running offline game | `nGame::Autosave::Update` S 0078b040: if the interval is not 0 and the session is offline: on the first call remember the current time; later, when `now − last > interval` (wall-clock seconds from `Timer_GetTotalSeconds`, not logic ticks), post the message `!Autosave...` (type 8) to the local player, set `last = now`, write `Autosave.aav`. Caller: `nGame::System::Update` S 00780d20 (the game system's per-frame update) calls slot 1 of the `nGame::Autosave` object embedded at `nGame::System +0x5f8` (vtable S 008353d0), **only if the UI is not suppressed and the byte `nGame::System +0x635` is 0**, before the cursor and camera updates | [known]; that `+0x635` is the "cinematic running" flag is [known]: `BeginCinematic` S 00782b60 sets it, `EndCinematic` S 00782bb0 clears it. Live: `Update` ran once per frame (one object); with a 10-minute interval and the game paused at tick 99,479 for more than five minutes, `Autosave.aav` was written inside the pause, exactly 10 minutes after the previous one, and not again within the pause [live, 2026-10-12] |
| Per frame, menu | `LoadSavePanel::Update` hands a chosen file to the menu system; `nMenu::System::Update` S 005da500 starts it | [known] |
| On demand | `GameFile_Save` runs synchronously inside the frame that confirmed it, between two logic ticks [inferred: every caller is UI or frame code] | |
| On load | everything in §3.4–3.8, synchronously | [known] |

The autosave timer is reset when a world is built (`BuildWorld`) [known] S 00784d40. `last == 0.0` means "not
started": the first `Update` after a reset only stores the current time [known] S 0078b040.

`Timer_GetTotalSeconds` S 0057b8a0 is the frame timer's current sample in ms (unsigned) divided by 1000. The
sample is taken once per frame by `Timer_UpdateFrame` S 0057b810 from the performance counter (or the fallback
time source chosen in `Timer_Init`), called by both frame functions (`CApplicationEx::FrameTick_Menu`
S 00401780, `FrameTick_InGame` S 004018e0) with no test of the pause state [known]. It is real time: pausing
does not stop it,
because pause is implemented as game speed 0 (§7), not as a stopped clock [known] S 005ea9b0. So the interval
keeps running while paused and the autosave fires in a paused game [known] (no pause test
in S 00780d20 or S 0078b040). The post-load `Timer_Reset` (§3.6 step 17) does not restart the interval:
`Timer_GetTotalSeconds` returns the raw sample again from the next frame on [inferred] S 0057b990, S 0057b810.

---

## 5. Inputs and outputs

**Inputs**

| Input | Handler |
|---|---|
| In-game menu entries Save (action 0) and Load (action 1), offline only | `nMenu::Game::OnMenuComboSelected` S 005eb310 → `LoadSavePanel` |
| Main menu: Load, Continue | `nMenu::Main::HandleButtonClicks` S 005e27c0 → `LoadSavePanel` ctor / `ContinueLastSavegame` |
| Confirm in the exit requester (type "exit to desktop" or "exit to title / lobby") with its autosave check box marked, while the game screen is active | `nMenu::Requester::ExecuteConfirmed` S 006008b0 → `nGame_Autosave_WriteSave` [known]. In a lobby match the "exit to title" type sends the referee give-up instead and does not save. `nGame_Autosave_WriteSave` itself saves only in an offline session (S 0078af30) |
| Windows low-battery broadcast | `nMenu::System::EmergencySave` S 005da7d0 |
| Command line `-start <file>` | S 00401420 |
| Options panel combo `cAutosave` | `OptionsPanel::ApplyOptionValue` S 005e5bd0 |

No network event saves or loads. `NComm::EventSaveGame` exists only as a deserialiser (`docs/multiplayer-save.md`).

**Outputs**

- Files: `<name>.aav`; `<name>.info` caches; the user profile's last-save name.
- During load: load-progress ticks (`!Loading rest...` 50, `!Finalizing world` 10 × 10) on
  `g_LoadProgressChannel` S 0088cf18.
- During post-load: the "added" callbacks of the callback manager for buildings, chests and others (each object's
  `PostLoad`), collected while the map-update batch is open and delivered at its end [inferred].
- After load: the script callback `onLoaded`, only if a map script was found: `GameScript_CallOnLoaded` (like every
  other script hook) does nothing while the script path `g_GameScript_MapScriptPath` is empty, and
  `GameScript_LoadMapScript` empties it when the `.lua` file does not exist [known] S 005b2180, S 005b1fe0.
- The HUD message `!Autosave...`.

**What it asks of other subsystems**: a `Store`, a `Load` that first clears, and a `PostLoad` per system; a
constructor "for load" per object class that takes owner and property but allocates no new unique id
(`ctor_ForLoad`, e.g. S 0055c8b0 building, S 0066b1a0 flag, S 005bb290 ship); an id lookup per system for `Relink`.

---

## 6. Data-driven parameters

The save format itself is not data-driven: no Lua, XML or INI key changes what is written. The surrounding
behaviour reads:

| Source | Key | Use | Example |
|---|---|---|---|
| `data\game\ui\layout\menuLoadSave.xml` | root attributes `textLoad`, `textSave` | panel caption and confirm button text | `!Load`, `!Save` |
| same | children `btLoad`, `btDelete`, `listbox`, `edit`, `messagebox`, `headline`, `closeButton` | the panel's controls: `btLoad`, `btDelete`, `listbox`, `edit`, `headline` are bound by name and widget kind in S 0060d7b0, `messagebox` is loaded by name in S 0060e0e0, `closeButton` is matched by name in the dialog base's click handler S 0060e3f0 [known]. The caption text goes to `btLoad` and `headline` (S 0060e0e0) | `btDelete` hotkey `d`, `btLoad` hotkey 13 |
| `data\game\ui\layout\menuoptions.xml` | `cAutosave` with `size`, `string0`..`string5` | autosave choices; the interval is `atol(localised item text) × 60` seconds | `!Off`, `!5 Minutes`, `!10 Minutes`, `!20 Minutes`, `!30 Minutes`, `!60 Minutes` |
| `<My Documents>\SAdK\users\settings.cfg` (plain `FileStream`, section `UserSettings` v2) | first string: last save name (`UserProfile +0x08`); second field (f32): the game speed (`+0x24`, §7); third field (i32): autosave interval in seconds (`+0x04`), 0 = off | "Continue"; game speed; autosave | [known] S 00579640 (writer), S 00579960 (reader). The reader reads the second field and then sets `+0x24` to 1.0: the stored speed is never used (§7) |
| property scripts `data\game\scripts\properties\*.lua` | the hex ids given to `bp_create`, `tp_create`, settler, good, sacrifice and AI definitions | a save refers to every definition by this id; the same data must be loaded for a save to resolve | `docs/map-format.md` §2.4 |
| map folder | `<mapName>.lua`, `<mapName>.bin` | re-read on load by the name stored in `MapInfo` | |

Because the autosave interval is parsed with `atol` from the **localised** combo text, a translation whose item
text does not start with the number yields 0 (off) [inferred] S 005e5bd0. The text parsed is the combo item's
displayed string (`nUi::Text +0x3c` of the item button, i.e. item `+0x290`), which `ComboBoxNew::AddItem`
S 004cbd60 fills through `nUi::Text::SetText` S 004b3fe0 with the localisation of the `string<i>` key; the raw key
(`!5 Minutes`) would parse as 0 [known].

---

## 7. Save and load

This section is the subsystem itself; see §3. Summary of what a save does **not** contain, i.e. what a
reimplementation must rebuild or accept as lost:

| Not stored | What happens on load | Tag |
|---|---|---|
| The Lua state of the map script | the script file is executed again, then `onLoaded()` (both only if the `.lua` file exists, §5); only the `sd_` integers and the quest table persist | [known] S 005aa7b0, S 005b0f30, S 005b1fe0, S 005b2180 |
| Pointers of any kind | resolved from unique ids in `PostLoad` | [known] |
| Victory-condition state (who was eliminated, who won) | re-derived by the next ticks; a match that was already decided declares its winner again after a load (with the referee message of a lobby match, `docs/sim/players-victory.md` §3.7) | [inferred], `docs/sim/players-victory.md` §7 |
| A ship's phase timer (`NNavy::Ship +0x44..+0x4c`: timer id, total, left; the sinking timer of `docs/sim/navy.md`) | not among the fields `Ship::Store` writes (unique, construction, movement, state, state countdown, expedition, ship number, cargo, condition, military); what a ship saved while sinking does after a load: `docs/sim/navy.md` | [known] S 005bb060 for the field list and the mapped `Ship` struct for the offsets; that the three fields are the sinking timer is taken from `docs/sim/navy.md`, not re-derived |
| The transient half of the attack path-length cache | only the stamp `DAT_0088a4d0` and the map at `DAT_0088a4e0` are written; `NMilitary::Attack::PostLoad` empties the transient map and stamps it with the tick counter of the loaded game | [known] S 00575740, S 00575800; `docs/sim/military.md` |
| Sacrifice modifiers | recomputed from the loaded running sacrifices at the end of `LoadSacrifices` | [known] S 00662390 |
| The neutral player | rebuilt by `PlayerTable::Load` | [known] S 005be1b0 |
| Per-player building counts, lock maps | refilled later / by the script | `docs/sim/players-victory.md` §7 |
| Construction maps, object layers, A* grids, AI low-resolution cell grid | rebuilt: `MapModifier_InitAfterMapLoad`, `NAI::System::Load` resizes its grid from the map size | [known] S 005ac770, S 005821f0; `docs/map-format.md` §5.5 |
| Building category indexes, the order index, flag and street id maps | rebuilt in `Load` / `PostLoad` | [known] S 00559cd0, S 00668050 |
| Street planners, AI path analysers, the street-net path finder | restarted / recreated | [known] S 005273d0, S 005819a0, S 00668050 |
| Player messages of type 8 (letters; also the type of the `!Autosave...` notice, §4) | written like every other message, but `NPlayer::Messages::Load` reads each one and does not put it back into the list | [known] S 005c1900, S 005c2520; `docs/sim/players-victory.md` §7 |
| The frame timer | reset at the end of post-load (§3.6 step 17) | [known] S 005273d0 |
| Game speed and pause | the speed is the float `UserProfile +0x24`: read by the speed-cycle command sender S 00782950 and Lua `getSpeed` S 005ad6f0, written by the lockstep command 0x20023 (S 00782a20: the command's integer as float, no range check; the sender produces `floor(speed) mod 3 + 1`, i.e. 1..3). Pause is speed 0: `nMenu::Game::SetPaused` S 005ea9b0 keeps the old speed in the game screen object, writes 0, and on unpause restores it (at least 1.0). It is a profile value, not part of the save: `StoreSettings` S 00579640 writes it to `settings.cfg` as it stands (0 if the profile is written while paused), but `LoadSettings` S 00579960 sets `+0x24` to 1.0 right after reading the stored float, so the stored value never takes effect. `nMenu::Game::SetupHud` S 005ed700 writes 1.0 inside its one top-level branch "UI not suppressed"; its only caller `nMenu::Game::OnEnter` S 005eed00 calls it unconditionally, before `BuildWorld` | [known] for each function; so every game entered with the HUD, a loaded one included, starts at speed 1.0 and unpaused in terms of speed [inferred]; a save written while paused (`TogglePause` S 005da400 had set `+0x24` to 0, tick 54,259) loaded with the factor at 1.0 and the ticks running on from 54,259 [live, 2026-10-14]. The "UI suppressed" byte (`nMenu::System +0xa4`) is written only by the constructor S 005db1e0 (0), so the 1.0 write of `SetupHud` runs for every game, network matches included [known: decompile of every function; scan of all stores at +0xa1..+0xa4 and of every `LEA` of +0xa4]. All writers of the speed: `LoadSettings` (1.0), `SetupHud` (1.0), `HandleSetGameSpeed` S 00782a20 (command 0x20023), pause (`TogglePause` S 005da400, `SetPaused`), the options panel (S 005e62f0 writes 0 while it is open, its destructor S 005e61b0 restores the kept value), `nMenu::Game::OnKeyDown` S 005ec340 (20.0, the float at S 007df110) and the cinematic (`Cinematic::Update` S 005fb3e0, `OnHide` S 005faee0) |
| Camera position, selection, open windows, minimap state | not part of any `Store` reached from `GameFile_Save`; the camera is re-activated by `BuildWorld` | [inferred] from the call lists of S 005a9fa0 and S 005a9ec0 |
| Network session: slots, GUIDs, GameID, GameSeed, net tick, queued commands, checksum log | belongs to the session | `docs/multiplayer-save.md` |
| Commands issued but not yet executed | lost [inferred] | |
| Thumbnail, date, play time | never written | [known] |

Stored although derivable (must be written by a writer, the loader does not recompute them): the grid-state bits,
the continent partition, the flag-network cost maps and the street-net continent ids (`docs/map-format.md` §5.5;
S 00668050 reads them verbatim in current versions).

---

## 8. Determinism notes

- **A save is a full lockstep state.** The logic random generator's state and seed, the tick counter and the next
  unique id are stored, so a loaded game continues the exact sequence [known] S 005389c0, S 005275c0.
- **Order of records = order of containers.** Vectors are written front to back (buildings, settlers per kind,
  flags and streets per player, packages, fights, projectiles, chests, sacrifices); maps in ascending key order
  (unique id as signed high dword then unsigned low dword [known] S 0066d8e0; good id; string key). Loading pushes
  back in file order, so vector order survives a save/load cycle [known] S 00559a10, S 0052d460. Since the
  simulation iterates these vectors, **a reimplementation must preserve them**, including the order produced by
  removals in the original (swap-with-last or erase: per container, see the per-subsystem documents).
- **Per-player grouping changes interleaving only inside the file**: flags and streets are stored grouped by
  player 0..7, and loaded back into per-player vectors [known] S 006640d0.
- **Floats** are stored as raw 4-byte singles (tick timing, construction progress, interpolators). No text
  conversion, so no rounding on a save/load cycle [known].
- **One deliberate non-identity**: on load, `accumulatedTime` is pulled to `nextTickTime − 0.01` if it was not
  below it [known] S 00527d60. This affects only when the first tick after the load fires in real time, not the
  tick sequence [inferred].
- **Post-load side effects are the risk.** `PostLoad` re-raises "added" callbacks and `NNet::System::PostLoad`
  removes streets with dangling flags; `MapModifier_InitAfterMapLoad` recomputes construction maps. If any of these
  produces state that differs from what the running game had (a cache the checksum covers, a counter advanced by a
  re-add), a loaded game diverges from one that kept running. Known case: `NLogic::Stock::Load` re-adds goods unit
  by unit, advancing the change stamp once per unit [known] S 00539fa0 (`docs/sim/logic-core.md` §7); the stamp
  itself is in neither the save nor the checksum data (`Stock::Store` S 00539850 and `StoreContents` S 00539910
  write flag, count and entries only), so this case does not show [known]. No other such difference reaches the
  checksum: a developed six-player offline game saved at the end of tick 54,004, and the same save loaded, gave
  equal `ComputeChecksum` values on all 45 compared ticks (54,010 to 54,054); the first tick after the load was
  54,005. Save and load are checksum-neutral over this window [live, 2026-10-14].
- **The checksum is weaker than the save**: bools count one byte, strings only four bytes, section tags nothing,
  and several saved systems are not covered (§3.9). Two games can be "in sync" with different quests, statistics
  or chests.
- Saving reads the wall clock only for the default file name and the autosave timer; nothing time-dependent goes
  into the file [known], with one exception: `MapInfo::Store` writes the map UUID at `+0x1d4` only if the flag
  byte `+0x1d8` is set; otherwise it **generates a fresh UUID** and writes that (the stored object is not
  changed) [known] S 00529db0. Two saves of such a state differ in these 16 bytes. The flag is the UUID
  object's own "valid" byte (`NCore::UUID +4`): cleared by the UUID constructor and by `MapInfo::Reset`
  S 0052b8d0, set by `UUID::Generate` S 0057ce00 (called only from `MapInfo::Store`, on a temporary, and from
  `MapInfo::Load` for files older than v7), and otherwise read from the file as the bool of the `Core UUID`
  record (S 0057ce60) [known]. So it is clear exactly for a `MapInfo` that was reset and never loaded (the
  file-less empty world of §3.8) or loaded from a file that stored the bool as false [inferred].
- `MapInfo::Load` does not rewrite the per-tribe initial goods of a current file: the three repair functions run
  only for stored versions below 15 (§3.5) [known] S 0052bd40. A v15 `MapInfo` is taken as stored.
- The loader of the flag-network cost maps and of the continent ids takes the file's values without
  recomputing them (§3.3 item 7, §7); cached costs are whatever the saving game had computed at its last
  refresh (`docs/sim/streets-transport.md`).

---

## 9. Notes for a reimplementation

**If compatibility with original saves is wanted** (read and write `.aav`):

- Bit-exact: the container (`docs/asset-formats.md`), little-endian packing, 4-byte bools, u32-length strings
  without terminator, the 12-byte tags with the versions of Appendix A, the order of §3.2 and §3.3, the id-before-
  record pattern of polymorphic lists, and "none" references as `ff ff ff ff ff ff ff ff`
  (`docs/map-format.md` §2.3).
- The reader must implement the current versions only to read saves written by the last patch; the old-version
  gates of §3.5 matter only for saves from earlier patch levels.
- Tag CRC and name length are ignored by the game but should be written correctly.
- Trailing zero padding is optional.
- Property ids must match the original data.
- The AI sections are the largest undocumented block (some 70 section types, Appendix A). A reader that does not
  model the AI cannot skip them, because sections have no length: **reading an original save requires parsing
  every AI record correctly even to reach the statistics, quests and chests behind it.** A writer that wants the
  original game to load its saves must emit valid AI records for every player (an inactive AI player is the
  `AI Player` tag and two fields: bool active = false, i32 profile id or −1; S 00583180 [known]).

**If compatibility is not wanted** (a Godot remake with its own format), keep the design and drop the accidents:

- Keep: one `store` / `load` / `post_load` triple per object; identity by 64-bit id with a post-load relink pass;
  per-section versions; a load that first clears; the fixed subsystem order (map before logic, players before
  everything that refers to players, post-load after all data is in).
- Add: section lengths (so unknown sections can be skipped), a real header with version, map name, date and a
  thumbnail, verification of section names, a bounded string read, an error path that reaches the player, and an
  atomic write (temp file + rename; the original truncates the target with `CREATE_ALWAYS` and writes in place).
- Drop: the container's scramble and LZSS (use the engine's compression), the 0x80 padding, the `.info` cache, the
  `.sav` and user-map fallbacks of the loader.
- Decide deliberately: script state. The original keeps only integers and quests and re-runs the script. A remake
  that keeps the original campaign scripts must keep this contract (`onLoaded`, `sd_getValue`).
- The checksum should hash exactly what the save writes (one writer, two sinks), with full strings and tags, so
  that "saved state equal" and "in sync" mean the same thing.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 1 | Answered (§3.3 item 8, Appendix A): the layouts of all 73 AI section names of Appendix A are in `docs/sim/ai-player.md` §7 (field lists in stream order, value encodings, `Load` version gates, values of skipped fields). `Ai Cell` v2 is `NAI::Cell` (S 00594d80 / S 00596130), `Ai Cell` v1 is `NAI::Trigger` (S 005a7890 / S 005a78e0), each the only user of its tag object | — |
| 2 | Answered (§8): a save/load cycle is checksum-neutral; a developed six-player game and the same game loaded from its save at tick 54,004 gave equal checksums on all 45 compared ticks [live, 2026-10-14] | — |
| 3 | Pause and sacrifices: nothing of the pause is saved (it is game speed 0, §7) and running sacrifices are stored with their start ticks, so both saves are ordinary ones. Answered for the pause (§7): a save made during a pause loads unpaused at speed 1.0 and runs on from the saved tick [live, 2026-10-14]; the sacrifice save was not tried. Cinematic: a save can be written by `EmergencySave` S 005da7d0 (battery low) and, if a click gets through during the 1.0 s HUD fade, by an open save panel; it loads with the computer players and the chests switched off (`camera-input-cutscenes.md` §7) | open: the click during the fade (running game) |
| 4 | Answered (autosave rows of the "when a save is written" table): the autosave fires while the game is paused and not during a cinematic. `Autosave::Update` S 0078b040 compares wall-clock seconds and has no pause test; `nGame::System::Update` S 00780d20 calls it every frame unless the UI is suppressed or `nGame::System +0x635` is set, and that byte is set by `BeginCinematic` S 00782b60 (called from `nMenu::Cinematic::OnShow`) and cleared by `EndCinematic` S 00782bb0. The interval keeps running during the cinematic, so an overdue autosave fires in the first frame after it | static: S 0078b040, S 00780d20, S 00782b60; live 2026-10-12 (`Update` runs once per frame) |
| 5 | [TODO] Which build wrote `.sav` (type 10) files into the save folder, and whether those were containers. This build cannot answer it: no caller of `GameFile_Save` passes type 10 (§2.6), it only reads `.sav` as a fallback (S 005aaed0, S 005dfef0, S 005aaa30). Partial evidence: the one `.sav` the install carries, `campaignMaps\C02.sav`, is plaintext (no container) written by an older build whose section versions are listed in §2.6 [known: the file's bytes]; whether the save-folder `.sav` files of that build had the same form stays open | a `.sav` written by an old installation (or that installation's executable); the code of this build holds no writer to read |
| 6 | Answered (§2.1): each `Relink` looks the stored `Unique` up in its owner's container (table in §2.1) when the id's high dword is 0..0x7fffffff; the shared `Load` S 0059d3c0 has set the pointer to 0 and every lookup returns 0 on a miss, so a failed lookup leaves a null pointer | — |
| 7 | `MapInfo` field meanings are in `docs/map-format.md` §4.2: `+0x48` who controls the slot (0 none, 1 computer, 2 local human, 3 remote human), `+0x68` tribe, `+0xc8` AI level and `+0x1c8` win condition are [known] from their setters and readers (S 004562d0, S 005abb60, S 005293e0, S 00529470, S 00535870); `+0x88` colour and `+0xa8` team are [inferred] from one reader each; `+0x1ec` is a network-game flag that no function tests. Answered: `+0x1cc` is the water preset index; its only reader is `S2CG::CMapRenderer::InitForMap` S 006883e0 (`WorldRenderer::SetWaterPreset`), and it is otherwise only cleared (constructor, `Reset`, `Load` below v4), loaded, stored and copied (S 00529a00, S 007849f0). `+0x1f0` is read only by "Continue" (`ContinueLastSavegame` S 005dfef0, refuses values ≥ 2, §3.5) and set to 1 by `MapInfo::Reset` S 0052b8d0 and `GameFile_Save` S 005aa260. Neither field reaches the simulation [known: decompile of every function] | — |
| 8 | Answered (§3.3, `Net System`): map `player × 2 + k` holds the costs of net kind k (0 goods streets, 1 all streets); both readers index `flagNetworks + netKind + owner × 2` (S 00667f30, S 00664e70) | — |
| 9 | Answered (§7, game speed row): the case does not occur. `nMenu::System +0xa4` ("UI suppressed") is only ever written 0 (constructor S 005db1e0), so `SetupHud` S 005ed700 writes 1.0 on entering every game, a network match included; the other writers of `UserProfile +0x24` are listed in §7 | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 005aa260 | `GameFile_Save` | write a save (types 10/110) or export a map |
| 005a9fa0 / 005a9ec0 | `GameFile_SaveMap` / `GameFile_SaveLogic` | the two parts, in order |
| 005ab180 / 005aaed0 | `nGame_File_load` / `GameFile_LoadImpl` | load by type and name, with fallbacks |
| 005aa7b0 / 005a9db0 | `GameFile_LoadMap` / `GameFile_LoadLogic` | readers of the two parts, version gates |
| 005aa1b0 | `GameFile_FinishLoad` | post-load, environment data, resume notifications |
| 005aaa30 / 005aa030 | `GameFile_LoadMapInfo` / `GameFile_LoadMapInfoCached` | `MapInfo` only, `.info` cache |
| 005aa150 | `GameFile_ResetWorldForMapExport` | strips the world before a map export |
| 005ab220, 005aa690, 005aa540 | `GameFile_WriteDesyncDump`, `GameFile_DumpMap`, `GameFile_DumpLogic` | text dump |
| 00784080 | `nGame::System::ComputeChecksum` | the checksum writer list |
| 00663dd0 | `NCore::IStoreable::dtor` | base destructor: restores the base vtable S 007d4fbc |
| 00581800 | `NCore::Stream::ctor` | base stream |
| 007803c0, 007807f0, 007805d0 | `NCore::FileStreamCrypt` ctor, `Open`, `Close` | encrypted in-memory stream |
| 00780470 / 00780480 | `FileStreamCrypt::ReadRaw` / `WriteRaw` | |
| 007808d0 / 00780580 | `ReadString` / `WriteString` | u32 length + bytes |
| 0057cf80 / 007804f0 / 0057cfc0 | read section (version) / read section (discard) / write section | the 12-byte tag |
| 00780490 / 00780520 | read / write bool | 4 bytes |
| 0057cea0, 0057d140, 0057cf00, 0057cf30 | `NCore::FileStream` ctor, `Open`, `Read`, `Write` | plain file stream |
| 0057d270, 0057d400, 0057d390, 0057d3d0 | `NCore::CRCStream` ctor, `Begin`, `GetCrc`, `WriteString` | checksum sink |
| 00780960, 00780bb0, 00780b70 | `NCore::DumpStream` ctor, `Open`, `WriteChunkHeader` | text sink |
| 006e7770 | `File_ReadAndDecrypt` | read + decrypt a container (`gReadFileData`, then `gDecryptData`) |
| 006eeac0 / 006ee8e0 | `FileCrypt_DeriveFileKey` / `FileCrypt_PackAndEncrypt` | key, packing |
| 0052c880, 0052c320, 0052c1b0, 0052c100 | `MapPath::CtorWithFileName`, `ai::game::MapPath::BuildDirectory`, `MapPath_GetFileExtension`, `MapPath_GetDataSubdir` | type → folder and extension |
| 0052c270 | (unnamed) is-new-game-type | types 0, 1, 2, 100, 102 |
| 0057bfb0 | `Fs_CreateUserDataDirectories` | creates the user folders |
| 005275c0 / 00527d60 / 005273d0 | `NLogic::System::Save` / `Load` / `PostLoad` | `MapInfo` + `LogicSystem`; post-load order |
| 00529db0 / 0052bd40 | `NLogic::MapInfo::Store` / `Load` | the metadata section |
| 00538760 / 00538740 | `LogicId_StoreGlobal` / `LogicId_LoadGlobal` | next unique id |
| 005386e0 / 00538710 | `NLogic::Unique::Store` / `Load` | 64-bit id record |
| 005389c0 / 00538a20 | `LogicRandom_Save` / `LogicRandom_Load` | random generator |
| 005bde00 / 005be1b0 | `PlayerTable::Store` / `Load` | players |
| 005be3c0 / 005be500 | `Player::Store` / `Load` | one player; `Load` empties an initialised stock and marks an active player's stocks initialised |
| 00557cc0 / 00559c80 / 00559cd0 | `NVillage::System::Store` / `Load` / `PostLoad` | village |
| 00557a20 / 00559a10 | `StoreBuildings` / `LoadBuildings` | building list |
| 0055c470 / 0055d290 | `NVillage::Building::StoreSavegame` / `Load` | one building |
| 00654420 / 00656430 / 00654270 | `NSettlers::System::Store` / `Load` / `StoreSettlerVector` | settlers |
| 0064cdd0 / 0064ce30 | `NTransport::System::Store` / `Load` | transport |
| 0064f640, 00650080, 00651840 | `PackageSystem::Store`, `PackageNeedSystem::Store`, `NeedSystem::Store` | transport parts |
| 0056ffe0 / 00570050 | `NMilitary::System::Store` / `Load` | military |
| 00575740 | `NMilitary::Attack::Store` | path-length cache |
| 00575800 | `NMilitary::Attack::PostLoad` | transient path-length cache emptied, stamped with the load tick |
| 00658960 | `NSettlers::Soldier::Store` | soldier record (member order) |
| 0064dd40 | `NTransport::PackageContainer::Store` | package container: tag, byte, i32 count, references |
| 00662390 / 00662fb0 | `SacrificePlayerData::LoadSacrifices` / `SacrificePlayerTable::RecomputeModifiers` | running sacrifices read; modifiers recomputed |
| 00773f80 | `NMovement::Fine::Store` | fine mover record, written without a section tag |
| 006640d0 / 00668050 / 006654f0 | `NNet::System::Store` / `Load` / `PostLoad` | street net |
| 0066d8e0 / 006707f0 | `NetContinentIds::Store` / `Load` | street-net continent ids |
| 00581ad0 / 005821f0 / 005819a0 | `NAI::System::Store` / `Load` / `PostLoad` | AI |
| 00583180 / 00584320 | `NAI::Player::Store` / `Load` | one AI player |
| 00537280 / 005384f0 | `NLogic::Statistics::Store` / `Load` | statistics |
| 005b0f30 / 005b2780 | `GameScript_Store` / `GameScript_Load` | script key-value store |
| 005b1fe0, 005b2180, 005b2220 | `GameScript_LoadMapScript`, `GameScript_CallOnLoaded`, `GameScript_CallOnStarted` | script on load |
| 00535ef0 / 00535f40, 00536000 / 00536090 | `NLogic::Quests::Store` / `Load`, `NLogic::Quest::Store` / `Load` | quests |
| 0065f500 / 0065f650 / 0065f540 | `NSacrifice::System::Store` / `NSacrifice::System::Load` / `NSacrifice::System::PostLoad` | sacrifices |
| 00662b40 / 00662ba0 | `SacrificePlayerData::Store` / `Load` | per-player sacrifice data |
| 0052d200 / 0052d600 / 0052d2c0 | `LogicChestSystem::Save` / `LogicChestSystem::Load` / `ai::logic::LogicChestSystem::PostLoad` | chests |
| 00539360 / 005393e0 | `LogicChest::Store` / `Load` | one chest |
| 005b35d0 / 005b4650 / 005b3a90 | `NNavy::System::Store` / `Load` / `PostLoad` | navy (map part) |
| 0060ce40, 0060e0e0, 0060da50, 0060d000, 0060d5b0, 0060dd30 | `nMenu::LoadSavePanel` ctor, `LoadFromXml`, `RefreshFileList`, `Confirm`, `OnMessageBoxResult`, `Update` | the panel |
| 0060dd90 / 0060d2f0 | `SaveGame_BuildDefaultSaveName` / `SaveGame_GetSaveFileSearchPath` | default name; `saves\*.aav` |
| 005d9fd0 | `nMenu::System::StartPendingMap` | offline start from a chosen save |
| 005a9c10 | `GameLoadDescriptor::SetMapName` | load descriptor: name, type 110, load from file |
| 005dfef0 | `nMenu::Main::ContinueLastSavegame` | "Continue" |
| 00401420 | `App_CmdLine_StartGameFile` | `-start <file>` |
| 005da7d0 | `nMenu::System::EmergencySave` | low-battery save |
| 0078b040 / 0078af30 | `nGame::Autosave::Update` / `nGame_Autosave_WriteSave` | autosave |
| 005e5bd0 | `nMenu::OptionsPanel::ApplyOptionValue` | autosave interval from the options |
| 00579640 / 00579960 | `UserProfile::StoreSettings` / `LoadSettings` | `settings.cfg`: last save, speed (stored, forced to 1.0 on read), interval |
| 00784d40 / 005ac770 | `nGame::System::BuildWorld` / `Game_LoadWorldFromDescriptor` | world build around the load |
| 00673000 | `MapModifier_InitAfterMapLoad` | construction maps, territory after a load |
| 005a9bb0 / 005a9c50 | `GameLoadDescriptor::Reset` / `GameLoadDescriptor::SetMapNameAndType` | descriptor defaults (file-less world); name and type for a new game |
| 005e8410 | `nMenu::FreeGamePanel::SetMap` | starts every free-game map, user maps included, as type 0 |
| 005b2720 | `GameScript_InitMapScript` | empties the script store before a world is loaded |
| 00780d20 | `nGame::System::Update` | per-frame; calls the autosave update |
| 0078af10 | `nGame::Autosave::ctor` | vtable S 008353d0 |
| 0057b790, 0057b7f0, 0057b800, 0057b810, 0057b8a0, 0057b990 | `Timer_Init`, timer shutdown, timer-initialised test, `Timer_UpdateFrame`, `Timer_GetTotalSeconds`, `Timer_Reset` | the frame timer behind the autosave interval and the post-load reset |
| 00401f30 | `CApplicationEx::HandleWindowMessage` | low-battery message → emergency save |
| 0067eb10 | scene slot +0x1c | copies the loaded `nextTickTime` into the scene |
| 006e4f00 / 006e4310 | `FileScanHolder::FindFilesByPattern` / `FindFilesInDirectory` | the save list scan (`FindFirstFileA` order) |
| 00563fc0 | `NVillage::Remains::ctor_ForLoad` | remains property id, building property id |
| 0057cde0, 0057ce00, 0057ce20, 0057ce60 | `NCore::UUID` ctor, `Generate`, `Serialize`, `Deserialize` | the `Core UUID` record |
| 0052b8d0, 0052a670, 0052b550, 0052bb40 | `MapInfo::Reset`, `NormalizeInitialGoodsForTribes`, `ResetInitialGoodsFromTribes`, `ResetSacrificesFromTribes` | defaults; repairs for `MapInfo` versions below 15 |
| 006ec350, 006ec280, 006ec2a0, 00538980, 00538a00 | `Rng_ParkMillerNext`, `RandomGenerator::RestartFromSeed`, `SetSeed`, `LogicRandom_SetUp`, `LogicRandom_Checksum` | layout of the 8 saved generator bytes |
| 005bb060 / 005bb1a0 | `NNavy::Ship::Store` / `StoreUntagged` | ship record; its checksum variant without the construction record |
| 00664550 | `NNet::System::StoreForChecksum` | street net in the checksum |
| 00782950, 00782a20, 005ea9b0, 005ed700, 005ad6f0 | speed-cycle command sender, its handler, `nMenu::Game::SetPaused`, `SetupHud`, Lua `getSpeed` | the game speed in the user profile |
| 00780a60 / 00780a80 | `NCore::DumpStream::WriteULong` / `WriteSizeT` | dump lines |
| 0078af00 | (unnamed) autosave reset | `lastSaveTime = 0`; called by `BuildWorld` |
| 005eed00 | `nMenu::Game::OnEnter` | calls `SetupHud`, then `BuildWorld` |
| 005eb310 / 006008b0 | `nMenu::Game::OnMenuComboSelected` / `nMenu::Requester::ExecuteConfirmed` | in-game menu Save / Load (offline only); exit requester with autosave |
| 0060d7b0 / 0060e3f0 | `nMenu::LoadSavePanel::BindControls` / `nMenu::Dialog::OnButtonClick` | panel controls by name; `closeButton` |
| 004cbd60 / 004b3fe0 | `nUi::ComboBoxNew::AddItem` / `nUi::Text::SetText` | localised combo item text (autosave interval) |
| 005c1900 / 005c2520 | `NPlayer::Messages::Store` / `Load` | message list; type 8 dropped on load |
| 00539fa0 | `NLogic::Stock::Load` | re-adds goods unit by unit |

---

## Appendix A: section names and current versions

Every section tag a save can contain, as `name` version. The name is exact (case, spaces and the original
spelling mistakes); the CRC in the tag is the zlib CRC-32 of the name, the third dword its length.
[known]: read from the static initialisers of the `g_LogCategory_*` objects (S 007c01e0 .. S 007cd880, extracted
list `mapping/work/mapdoc/scratch/st_cats.json`); the versions agree with the highest gate in each loader read for
this document.

**File** (2):
`Game File Logic` 6, `Game File Map` 1.

**Logic core and shared records** (18):
`Blocking` 1, `Core UUID` 0, `ElevationCursor` 0, `GameSystem` 0, `Logic Need` 0, `Logic Random` 0,
`Logic ReferncesFightGroup` 0, `Logic ReferncesProjectile` 0, `Logic ReferncesShip` 0, `logic UniqueId` 0,
`LogicAnimation` 0, `LogicSystem` 8, `MapInfo` 15, `Path` 0, `PatternCursor` 0, `Stock` 1, `ticker` 0, `uniqueId` 0.

**Players** (12):
`Good Arrangement` 4, `Good Priorities` 1, `Good Priority` 0, `Message` 2, `Messages` 0, `Player ArrangementBase` 0,
`Player ArrangementObject` 0, `Player GoodArrangementGroup` 0, `Player Military` 2, `Player ShipNames` 0,
`PlayerObject` 1, `PlayerSystem` 0.

**Statistics, quests, script, chests, spawns, ambients** (10):
`GameScript` 0, `Logic Ambients` 0, `Logic Chest` 0, `Logic ChestSystem` 1, `Logic Quest` 5, `Logic Quests` 3,
`Logic Spawn` 0, `Logic SpawnSystem` 0, `LogicPlayerStatistics` 4, `LogicStatistics` 2.

**Village** (28):
`Order Container` 0, `Order System` 1, `Returning Good System` 0, `Settlers Container` 0, `Soldier Exchange` 0,
`Soldiers Container` 0, `Village Catapult` 1, `Village Hitpoints` 0, `Village Military` 9, `Village Order` 2,
`Village Ordering` 0, `Village SettlerSpawn` 2, `Village Territory Updater` 0, `VillageBuilding` 2,
`VillageBulldozing` 0, `VillageCasern` 1, `VillageConstruction` 2, `VillageDepot` 3, `VillageGoodFlags` 0,
`VillageProduction` 1, `VillageRemains` 0, `VillageSacrifice` 0, `VillageSoldiers` 0, `VillageSystem` 0,
`VillageTraining` 0, `VillageUpgrade` 0, `VillageUpgrading` 0, `VillageWorkers` 0.

**Settlers** (13):
`Settlers Fight` 3, `Settlers Movement` 2, `Settlers Settler` 1, `SettlersAnimation` 1, `SettlersBow` 0,
`SettlersCarrier` 1, `SettlersConstructor` 0, `SettlersLivePoints` 1, `SettlersNPC` 0, `SettlersSoldier` 1,
`SettlersSpecialist` 0, `SettlersSystem` 1, `SettlersWorker` 3.

**Movement** (9):
`Movement Base` 0, `Movement Fine` 0, `Movement Fine Path` 0, `Movement Free Path` 0, `Movement Interpolator` 0,
`Movement Path Base` 1, `Movement Rough` 0, `Movement Street Path` 0, `MovementMovement` 1.

**Movies (settler action sequences)** (40):
`Movie BeNervous` 0, `Movie BringGoodHome` 1, `Movie BringGoodOut` 1, `Movie BringGoodToWorkingPlace` 0,
`Movie CatapultAttack` 0, `Movie Construct` 0, `Movie ConstructBuilding` 0, `Movie ConstructShip` 0, `Movie Drop` 0,
`Movie EnterBuilding` 0, `Movie GoAfforest` 0, `Movie GoFishing` 0, `Movie GoHunting` 0, `Movie GoMining` 0,
`Movie GoToConstructionPlace` 0, `Movie GoToPackageTarget` 0, `Movie GoToWorkingPlace` 0, `Movie IdleOutside` 0,
`Movie LeaveBuilding` 0, `Movie LeaveBuildingFromIdle` 0, `Movie LeaveMap` 0, `Movie LookForEmptyPlace` 0,
`Movie LookForFishing` 0, `Movie MoveToAnimal` 0, `Movie MoveToAttackBuilding` 0, `Movie MoveToDeposit` 0,
`Movie MoveToShip` 0, `Movie Pickup` 0, `Movie PickupProduct` 0, `Movie PutDownPackage` 0, `Movie ReturnFromIdle` 0,
`Movie ReturnHome` 1, `Movie ReturnToMilitaryBuilding` 0, `Movie ReturnToWorkingPlace` 0,
`Movie SearchScholarDiggingPosition` 0, `Movie ShipConstruct` 0, `Movie Stray` 0, `Movie WaitForPackage` 0,
`Movie WaitForShip` 0, `MovieGoDigging` 0.

**Transport** (11):
`Package Container` 0, `Package System` 0, `Transport BuildingNeedSystem` 0, `Transport Movement` 0,
`Transport Need Goods` 0, `Transport NeedGood` 0, `Transport Package` 0, `Transport PackageNeedSystem` 0,
`Transport PackageNeedTarget` 0, `Transport System` 0, `Transport Target` 0.

**Military** (15):
`Military Allocation` 0, `Military Attack` 1, `Military Distances` 0, `Military Fight` 8, `Military FightGroup` 1,
`Military FightGroups` 0, `Military Fights` 0, `Military FightSoldierList` 2, `Military GatheringPositions` 0,
`Military GatheringPositionState` 0, `Military Projectile` 1, `Military Projectile Owner` 0,
`Military Projectile Target` 0, `Military Projectiles` 0, `MilitarySystem` 0.

**Street net** (10):
`Flag` 3, `Net FlagLink` 0, `Net Package Stack` 0, `Net Package Stock` 0, `Net Parking` 0, `Net Specialist` 0,
`Net Street Map Updater` 0, `Net StreetNetContinentIds` 0, `Net System` 3, `NetStreet` 0.

**Navy** (15):
`Navy Cargo` 1, `Navy Condition` 0, `Navy Docking Position` 0, `Navy Expedition` 0, `navy harbor` 2, `Navy Harbors`
0, `Navy Military` 0, `Navy Movement` 1, `Navy Path` 0, `Navy Ship` 2, `navy ShipRoute` 1, `Navy ShipRoutes` 0,
`Navy System` 3, `NavyConstruction` 2, `Ship Route Position` 0.

**Sacrifices** (7):
`Sacrifice DataDependencies` 2, `Sacrifice DataRegenerations` 1, `Sacrifice DataResearch` 3, `Sacrifice Sacrifice`
2, `Sacrifice System` 4, `Sacrifices Free Tickets` 0, `Sacrifices Player Data` 4.

**AI** (74):
`Ai AttackExecution` 3, `Ai AttackSystem` 1, `Ai AttackTarget` 0, `Ai AttackTargetSelection` 1, `Ai Building` 1,
`AI BuildingConstruction` 0, `AI Casern` 0, `AI CatapultConstruction` 0, `Ai Cell` 2, `Ai Cell` 1, `AI CellClearing`
0, `Ai CellDepotCreation` 0, `Ai CellExpansion` 0, `AI CellFull` 0, `AI CellFullElement` 0,
`AI CellPositionItertator` 0, `Ai CellSystem` 0, `AI CellValidator` 0, `AI CoinProduction` 0,
`Ai ConqueredContinents` 0, `AI ConstructionHunter` 0, `Ai ConstructionOrder` 0, `AI ConstructionSacrificeSite` 1,
`Ai ConstructionSystem` 4, `Ai DestructionSystem` 2, `Ai ExpansionSystem` 1, `Ai ExpansionTarget` 0, `AI Expedition`
0, `Ai Fight` 1, `Ai FightData` 1, `Ai FightSettings` 0, `AI FoodArrangement` 0, `AI ForesterConstruction` 0,
`AI GoodsArrangement` 0, `Ai Harbor` 0, `AI LockSmith` 0, `Ai LowResResourceMap` 0, `Ai LowResResourceMapAdds` 0,
`Ai LowResResourceMapAddsElement` 1, `Ai Military Map` 0, `AI Military Map Element` 2, `Ai MilitaryBuildingCreation`
0, `AI MilitaryLimiter` 0, `AI MilitarySettings` 0, `Ai MilitarySystem` 2, `AI MilitaryUpgrade` 1,
`AI MinMaxCellIterator` 0, `Ai Need` 0, `AI NeedCreation` 0, `AI NeedsArrangement` 0, `AI NeedsConstruction` 0,
`AI Player` 7, `Ai Production` 0, `AI ProductionControl` 0, `Ai ReferncesBuilding` 0, `Ai ReferncesHarbor` 0,
`Ai ReferncesNeed` 0, `Ai ReferncesProduction` 0, `Ai ResourceMap` 1, `Ai ResourceMapAdds` 0,
`Ai ResourceMapAddsElement` 0, `AI ResourceMapElement` 0, `AI ResourceMapElements` 0, `Ai ResourceSystem` 0,
`AI SearchConstructionPlace` 0, `AI ShipConstruction` 0, `AI SoldierCreation` 0, `AI StreetConstruction` 2,
`AI StreetOptimizer` 1, `AI StreetRouteOptimizer` 1, `AI System` 2, `Ai TerritoryMap` 0, `AI TerritoryMap Element`
2, `AI WeaponProduction` 0.

**Map and resources (map part)** (16):
`deposit` 1, `DoodadsObject` 1, `DoodadsSystem` 0, `ElevationMap` 1, `GridStatesMap` 0, `Map Continent` 4,
`Map Continents` 1, `Map Exploration` 1, `Map Resources` 0, `Map Territory` 0, `MapSystem` 0, `PatternMap` 0,
`resources` 6, `Resources Animal` 3, `Resources AnimalAreas` 0, `Resources Path` 0.

**Same interface, other files (not in a save)** (4):
`SceneSettings` 1, `UserMapState` 1, `UserMapStates` 0, `UserSettings` 2.

Two names are used by two different tag objects: `Ai Cell` (versions 2 and 1) and `Movie Construct` (both 0).
`Ai Cell` v2 (tag object S 0088ab14, initialiser S 007c4390) belongs to `NAI::Cell` (`Store` S 00594d80, `Load`
S 00596130); `Ai Cell` v1 (S 0088b198, initialiser S 007c5d50) belongs to `NAI::Trigger` (`Store` S 005a7890,
`Load` S 005a78e0) [known: the only references to each tag object]. A reader tells them apart by position and by
the version, not by the name. The two `Movie Construct` objects are in the settler code.

A tag object does not mean the record writes it: `Movement Fine` has a tag object, but `NMovement::Fine::Store`
S 00773f80 writes its fields with no section tag (`docs/sim/settlers-jobs.md` §7) [known]; the nested `Movement Fine
Path` record inside it does carry its tag.
