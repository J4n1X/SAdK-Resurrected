# Engine core primitives: streams, serialisation, containers, math and utilities

Evidence tags: **[known]** = read at the given address (S 00xxxxxx = `sadk_noav.exe`, T 10xxxxxx = `tincat3.dll`)
or in a named data file; **[inferred]** = one step of reasoning from what is visible; **[TODO]** = open.
Nothing in this document was observed in the running game unless a dated observation of another document is
cited.

Conventions used below: all multi-byte values are little-endian unless a rule says otherwise; `u8/u16/u32/u64`
are unsigned, `i32/i64` signed, `f32` IEEE-754 single. "Bit *j* of a buffer" means byte `j / 8`, mask
`0x80 >> (j % 8)` (most significant bit first).

---

## 1. Purpose and scope

This document specifies the low-level building blocks that the other specifications use without describing:

- the two bit packers: `NCore::BitStream` and the bit packer inside `LobbyComm::LobbyMessage` (the one that
  actually carries the lobby, village and referee messages);
- the byte streams: `NCore::Stream` and its four implementations, `NComm::MemoryStream`, `NBase::File`, the
  PhysX `MemoryWriteBuffer` / `MemoryReadBuffer`;
- the section tag, `NCore::IStoreable`, the two unique-id classes and `NCore::UUID`;
- type identity (RTTI, factories);
- strings, text encoding and the string helpers;
- hashing: CRC-32 and MD5, and where a name becomes a number;
- containers and their iteration order;
- the math library: vectors, matrices, quaternions, angle units, the Park-Miller generator and every generator
  instance;
- timers and clocks;
- logging and assertion facilities;
- the localisation lookup and the file system layer (summaries; the full text lives in
  [formats-inventory.md](formats-inventory.md)).

Not in scope, and where it is: the save and map file layouts ([save-format.md](save-format.md),
`../map-format.md`), the encrypted container (`../asset-formats.md` §1), the NETMSG property-bag encoding of
`tincat3.dll` (`../message-catalog.md`, "Property-bag body (msgdefs field types)"), the typed field accessors
and field lists of each LobbyMessage (`../message-catalog.md`, [lobby-client-state.md](lobby-client-state.md)),
the frame loop
([app-shell.md](app-shell.md)) and the logic tick ([logic-core.md](logic-core.md)).

---

## 2. Data model

### 2.1 `NCore::ByteBuffer` (0x10 bytes) [known] S 0048f150, S 0057d460, S 00462630

| Off | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | ptr | vftable | S 007da868; slot 0 = `AssignShared` S 00462630 |
| +0x04 | `u8 *` | `data` | buffer |
| +0x08 | u32 | `size` | size in bytes |
| +0x0c | bool | `ownsData` | the destructor frees `data` only when 1 |

- `ctor(size)` allocates `size` bytes and zero-fills them (`ownsData = 1`). When the allocation fails `data` is
  null but `size` and `ownsData` are still set [known].
- `AssignShared(src)` copies `data` and `size` and clears `ownsData` (a view); the previous buffer is not freed.
- `GetDataAt(offset)` S 0057d450 returns `data + offset` with no bounds check.

### 2.2 `NCore::BitStream` (0x20 bytes) [known] vftable S 007da874, S 00462760, S 0057d4c0

The first 0x10 bytes are a `ByteBuffer` (vftable slot 0 of `BitStream` is `ByteBuffer::AssignShared`)
[known: vftable contents].

| Off | Type | Field | Meaning |
|---|---|---|---|
| +0x00..+0x0c | | `ByteBuffer` part | `data`, `sizeBytes`, `ownsBuffer` |
| +0x10 | i32 | `bitPos` | one cursor in bits, shared by reads and writes |
| +0x14 | i32 | `readLimitBits` | reads fail beyond this bit |
| +0x18 | i32 | `writeLimitBits` | writes fail beyond this bit |
| +0x1c | bool | `writable` | writes fail when 0 |

Virtual table (64 slots read; offsets are those the code calls through) [known: vftable contents S 007da874]:

| Slot | Off | Function | Slot | Off | Function |
|---|---|---|---|---|---|
| 0 | +0x00 | `AssignShared` | 32 | +0x80 | `ReadUInt16` |
| 1 | +0x04 | destructor | 33 | +0x84 | `WriteInt16` |
| 2 | +0x08 | `GetBytePos` = `bitPos / 8` | 34 | +0x88 | `ReadInt16` |
| 3 | +0x0c | `SeekByte` | 35 | +0x8c | `WriteUInt32` |
| 4, 14 | +0x10, +0x38 | getter of `sizeBytes` (+0x08), one body S 00412270 | 36 | +0x90 | `ReadUInt32` |
| 5 | +0x14 | `SeekBit` | 37 | +0x94 | `WriteInt32` |
| 6 / 7 | +0x18 / +0x1c | `SetLimitsBytes` / `GetLimitsBytes` | 38 | +0x98 | `ReadInt32` |
| 8 / 9 | +0x20 / +0x24 | read / write limit in bytes | 39 | +0x9c | `WriteUInt64` |
| 10 / 11 | +0x28 / +0x2c | `SetLimitsBits` / `GetLimitsBits` | 40 | +0xa0 | `ReadUInt64` |
| 12 / 13 | +0x30 / +0x34 | getters of +0x14 / +0x18 | 41 | +0xa4 | `WriteInt64` |
| 15 | +0x3c | `GetBytePosCeil` = `(bitPos + 7) / 8` | 42 | +0xa8 | `ReadInt64` |
| 16 | +0x40 | `GetBitsRemaining` = `writeLimitBits - bitPos` | 43 / 44 | +0xac / +0xb0 | `Write` / `ReadUIntInRange` |
| 17 | +0x44 | the same in whole bytes | 45 / 46 | +0xb4 / +0xb8 | `Write` / `ReadIntInRange` |
| 18 / 19 | +0x48 / +0x4c | `AlignWritePos` / `AlignReadPos` | 47 / 48 | +0xbc / +0xc0 | `WriteBit` / `ReadBit` |
| 20 | +0x50 | getter of `writable` | 49 / 50 | +0xc4 / +0xc8 | `Write` / `ReadVarUInt` |
| 21 / 22 | +0x54 / +0x58 | `SetWritable` / `ClearWritable` | 51 / 52 | +0xcc / +0xd0 | `WriteStdString` / `WriteCString` |
| 23..26 | +0x5c..+0x68 | `PeekUInt8/16/32/64` | 53 / 54 | +0xd4 / +0xd8 | `ReadStdString` / `ReadCString` |
| 27 | +0x6c | `WriteUInt8` | 55 | +0xdc | `PeekVarUInt` |
| 28 | +0x70 | `ReadUInt8` | 56 / 57 | +0xe0 / +0xe4 | `WriteBytes` / `ReadBytes` |
| 29 | +0x74 | `WriteInt8` | 58 / 59 | +0xe8 / +0xec | `WriteFloat` / `ReadFloat` (= `ReadUInt32`) |
| 30 | +0x78 | `ReadInt8` | 60 / 61 | +0xf0 / +0xf4 | `Write` / `ReadFloat3` |
| 31 | +0x7c | `WriteUInt16` | 62 / 63 | +0xf8 / +0xfc | `Write` / `ReadFloat4` |

**Use in the client.** The vftable is referenced from exactly two functions: the destructor and
`LobbyComm::System::DispatchInboundToConnection` S 00462760 [known: cross references of S 007da874]. That function
builds a read-only `BitStream` on the stack over each inbound payload of the village, game-slot and referee
connections (`data`, `sizeBytes = len`, `ownsBuffer = 0`, `bitPos = 0`, `readLimitBits = len * 8`,
`writeLimitBits = 0`, `writable = 0`) and hands it to the connection's slot `+0x24`. The referee and village
receivers pass it on as a `ByteBuffer` to `LobbyMessage::InitFromWire` S 0048fa50, which takes only `data` and
`size` [known] S 0047b090, S 00470a90, S 0048fa50. The game-slot connection (`LobbyComm::GameServerConnection`,
`LobbyComm::System +0x544`, vftable S 007deaf0) has an empty function in that slot (S 00472360, a bare `RET 8`), so
its payloads are dropped unread [known: vftable contents]. A connection id that matches none of the three is
dropped without a log line [known] S 00462760. **No field of any message is decoded through a `BitStream`
method; the field codec is the `LobbyMessage` bit packer (§2.3, §3.2).** With the vftable referenced from
nowhere else, no caller of the typed methods of §3.1 exists in the client [inferred]; that codec is specified
because it is in the image.

### 2.3 `LobbyComm::LobbyMessage` bit-packer state [known] S 0048ef70, S 0048f0d0, S 0048fa50

| Off | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | `ByteBuffer` | `buffer` | body bytes (owned when built for sending, a view when received) |
| +0x14 | u8 | `curByte` | the byte being assembled (write) or last fetched (read) |
| +0x18 | u32 | `bitCursor` | bits written or read so far |
| +0x1c | u32 | `byteIndex` | next byte of `buffer` to store to or fetch from |
| +0x20 | bool | `namesMode` | type word bit 15; adds the schema checksum (§3.2) |
| +0x24 | u32 | `category` | type word bits 12..14 |
| +0x28 | u32 | `msgId` | type word bits 0..11 |
| +0x2c | bool | `finished` | set by `Finalize` |
| +0x30 | `Crc32Acc` | schema checksum | running CRC-32 and byte count (§2.8) |

The complete object and its typed accessors: [lobby-client-state.md](lobby-client-state.md) §2 and
`../message-catalog.md` ("LobbyMessage bodies").

### 2.4 Byte streams

**`NCore::Stream`** (base: `+0x00` vftable, `+0x04` `std::string name`; 26 virtual slots) and its four
implementations `FileStreamCrypt`, `FileStream`, `CRCStream`, `DumpStream`: slot table, encodings and class
layouts are in [save-format.md](save-format.md) §2.2 and §2.3. Facts a reader of this document needs:

- every typed slot forwards the value's bytes to `WriteBinary` / `ReadBinary`; values are little-endian,
  unaligned, unpadded; `bool` is **4 bytes** in a file and **1 byte** in the checksum stream; a string is a
  `u32` length followed by the bytes, without terminator [known] S 00780520, S 00780580, vftables S 007e9c5c
  (file, 26 slots) and S 007e9ccc (checksum) ([save-format.md](save-format.md) §2.2). In the checksum stream a
  string contributes **exactly the first 4 bytes of its buffer**, whatever its length [known] S 0057d3d0, and
  the section-tag slot is an empty function;
- `FileStream::Open(path, mode)` S 0057d140 [known]: mode 0 = `CreateFileA(GENERIC_READ, share read|write,
  OPEN_EXISTING)` on the path resolved through the file index (§3.12); mode 1 = `CreateFileA(GENERIC_WRITE,
  share read|write, CREATE_ALWAYS)` on the resolved path, or on the path as given when the resolver returns an
  empty string; any other mode opens nothing. The given path is stored as the stream name in every case. The
  result is `handle != INVALID_HANDLE_VALUE`. `Read` / `Write` S 0057cf00 / 0057cf30 are `ReadFile` /
  `WriteFile` with the transferred count discarded (a short read is not detected).

**`NComm::MemoryStream`** (fields up to `+0x19`) [known] vftable S 007d4dc0, S 00412120, S 00412160:

| Off | Type | Field | Meaning |
|---|---|---|---|
| +0x04 | `u8 *` | `pBuffer` | |
| +0x08 | i32 | `size` | bytes written |
| +0x0c | i32 | `pos` | cursor, shared by reads and writes |
| +0x10 | i32 | `capacity` | |
| +0x14 | i32 | `growBy` | growth step |
| +0x18 | bool | `bReadOnly` | |
| +0x19 | bool | `bExternalBuffer` | the buffer is not owned and never reallocated |

It is the buffer behind every NComm peer-to-peer event and tick package (`../NCOMM_GAME_PROTOCOL.md`,
[network-session.md](network-session.md)) and the plaintext buffer inside `FileStreamCrypt`
([save-format.md](save-format.md) §2.3: initial capacity 0x400, step 0x80).

**`NBase::File`** [known] S 006e6a30, S 006e6530, S 006e6570: a Win32 file handle plus a running `position`;
the reader and writer of plain (non-container) data files and of the log. Open modes and path resolution:
[formats-inventory.md](formats-inventory.md) §3.1. Its string encoding is in §3.3.

**PhysX buffers.** `MemoryWriteBuffer` (vftable S 007e687c: `+0x04 currentSize`, `+0x08 maxSize`, `+0x0c data`)
and `NXU::MemoryReadBuffer` (vftable S 0083111c: `+0x04` read cursor) are the PhysX SDK's sample `NxStream`
implementations [known] S 00510f60, S 00511080, S 00757ac0, S 00757b80. Callers: `Lobby::CPhysicObj::
CreateTriangleMeshActor` S 00522410 (cooking a triangle mesh into memory) and the `NXU::NxuInstantiator`
functions S 00740560.. (reading cooked meshes back). They carry no game format: native little-endian values
appended to, or read from, a flat byte buffer; the write buffer grows to `needed + 0x1000` bytes [known]
S 00511080. They are used only for 3D-lobby physics [inferred from the two caller groups].

### 2.5 Section tag (`ai::logging::LogCategory`, 0x28 bytes) [known] S 005816e0

| Off | Type | Field | Meaning |
|---|---|---|---|
| +0x00 | `std::string` | `name` | section name (28 bytes, §2.7) |
| +0x1c | i32 | `level` | **the section's current version**: the third constructor argument |
| +0x20 | u32 | `nameCrc` | CRC-32 of the name's bytes (§3.5) |
| +0x24 | u32 | `nameLen` | byte count fed to the CRC = length of the name |

The class name is the map's; the object is not used for logging. Each tag is a static object built by a dynamic
initialiser at program start (the constructor has 290 callers; 286 of them are initialisers named
`dynamic_initializer_for_g_LogCategory_*`, the rest build a tag inside a function) [known: caller list, name
index]. The 12-byte record written to a file and the reader's behaviour: §3.4; names and versions of every
section: [save-format.md](save-format.md) Appendix A.

### 2.6 Storable objects and ids

**`NCore::IStoreable`** [known] vftable S 007d4fbc: slot 0 destructor, slot 1 `Store(stream)`, slot 2
`Load(stream)`; most simulation classes add slot 3 `PostLoad()`. Conventions: [save-format.md](save-format.md)
§2.1.

**Two unique-id classes with two separate counters** [known]:

| Class | Layout | Counter | Section tag | Used by |
|---|---|---|---|---|
| `NLogic::Unique` | 16 bytes: vftable, pad, id low `+0x08`, id high `+0x0c` | S 00889ad0 (64-bit), part of the saved and checksummed state | `logic UniqueId` [0] | every simulation object ([logic-core.md](logic-core.md) §2.3) |
| `NCore::Unique` | same shape, vftable S 007eb734 | `g_Unique_NextId` S 00897ce8 (64-bit) | `uniqueId` [0] S 007cd7d0 | `NPlayer::Message` only (constructors S 005c0660, S 005c0740, S 005c0830; load S 005c0390) |

`NCore::Unique` rules [known]:

- default constructor S 00780c00: id = −1 (both dwords 0xFFFFFFFF = "no id");
- `AssignNewId` S 00780c60: id = counter; counter += 1 (64-bit);
- `ctor_FromId(lo, hi)` S 00780c20: stores the id; if the id is **greater** than the counter (signed compare on
  the high dword, unsigned on the low) the counter is set **to that id**, not to id + 1;
- `Equals` S 00780c80 compares both dwords;
- `Serialize` S 00780cb0: section tag `uniqueId`, then the id as one 64-bit value; `Deserialize` S 00780ce0:
  skips the tag, reads 8 bytes.

`g_Unique_NextId` is referenced by `AssignNewId` and `ctor_FromId` only [known: cross references of S 00897ce8
and S 00897cec]. It is therefore 0 at program start (zero-initialised data), **never reset between matches and
never stored or loaded**; it only grows. `ctor_FromId` has one caller, the branch of `NPlayer::Message::Load`
S 005c0390 for section versions below 2; a current save (version 2) reads its ids through `Deserialize` and
leaves the counter alone [known]. Consequences [inferred]: ids of new messages continue across matches of one
program run, and after a load new messages can repeat ids of loaded ones (§7).

**`NCore::UUID`** (0x18 bytes) [known] S 0057cde0: `+0x00` vftable, `+0x04` bool `bValid`, `+0x08` 16 GUID
bytes.

- constructor: `bValid = 0`, GUID all zero;
- `Generate` S 0057ce00: `UuidCreate` (RPCRT4) into the 16 bytes, `bValid = 1`;
- `Serialize` S 0057ce20: section tag `Core UUID` [0] (S 007c3120), bool `bValid` (4 bytes in a file), the 16
  bytes raw, in the memory order of a Win32 `GUID`;
- `Equals` S 005a9d00: byte compare of the 16 bytes only; `bValid` is ignored.

It identifies a map file (`NLogic::MapInfo +0x1d4`, [save-format.md](save-format.md)) and is what the
multiplayer map-presence check compares (`GameFile_FindMapNameByGuid` S 005ab3d0).

### 2.7 Strings and standard containers

The image is built with the Visual C++ 8 (2005) runtime with checked iterators (calls to
`_invalid_parameter_noinfo` around iterator use, iterators that carry a container pointer) [known] e.g.
S 00487b20.

| Type | Size | Layout | Evidence |
|---|---|---|---|
| `std::string` | 0x1c | `+0x00` one pointer of the checked-iterator base ([inferred]), `+0x04` 16-byte union (inline text or heap pointer), `+0x14` size, `+0x18` capacity; inline while capacity < 16 (initial capacity 0xf) | [known] S 005816e0, S 004123a0 |
| `std::vector<T>` | 0x10 | `+0x00` the same base pointer, `+0x04` first, `+0x08` last, `+0x0c` end of storage | [known] S 00487b20 |
| `std::map`, `std::set` | | red-black tree with a head node (`ai::stl::MsvcTree` in the map) | [known: name index] |
| `std::list`, `std::deque` | | the runtime's (`ai::std::MsvcList`, `ai::stl::MsvcDeque` in the map) | [known: name index] |

All game text is held in `std::string` as **8-bit characters in the process's ANSI code page**. No
`std::wstring` instantiation is named in the image [known: name index]. In the decompiled image the `...W`
Win32 calls are `CreateFileW` (only in the C runtime's `_wsopen_nolock` S 00713cc3) and the runtime's locale
helpers (`LCMapStringW`, `GetStringTypeW`, `GetLocaleInfoW`, `CompareStringW`, environment and console
functions) [known: scan of the decompiled image; inferred for the locale helpers' callers, which were not
listed]. Outside the runtime, wide characters appear in the two conversion helpers of §3.6 and in the COM
`_bstr_t` strings of the embedded web view (`_com_util::ConvertStringToBSTR` S 00715960 from `_bstr_t::ctor`
S 005c7890, `ConvertBSTRToString` S 00715af0 from `URL2Tex_OnBeforeNavigate2` S 005c8980) [known: every
function of the decompiled image that calls `MultiByteToWideChar` or `WideCharToMultiByte`].

The engine's own containers (`ai::core::*`, the names are the map's) [known] S 004d9b40, S 004dedc0,
S 0076b180, S 006814a0:

| Container | Layout | Behaviour |
|---|---|---|
| dynamic array (`PtrArray`, `Array8/16/20`, `DwordArray`, `U16Array`, `Vec3Array`, ...) | `+0x00` count, `+0x04` capacity, `+0x08` data | `SetCapacity(n, min8)`: `n` raised to 8 when `min8` and `n < 9`; new zeroed buffer; elements copied; the callers grow by `capacity + capacity / 2` when `count == capacity` |
| bit set on a dword array | same | `SetBit(bit, value)`: grows to `bit / 32 + 1` zeroed words; bit `bit % 32` of word `bit / 32` |
| unordered remove | same | `RemoveAtSwapLast(i)`: the last element moves into slot `i` |
| handle pool (`HandlePool4/12/16/32`) | array of entries `+0x00..+0x08`; free stack `+0x0c` count, `+0x10` capacity, `+0x14` data; active list `+0x18` count, `+0x1c` capacity, `+0x20` data | `Alloc`: pop the most recently freed handle, else append; **handles are 1-based** (`index + 1`). `Free`: swap-remove from the active list, push on the free stack; the entry is not cleared |

`Array16::SetCapacity` S 004d9b40 sets `count = min(old capacity, new capacity)`, not the old count [known];
correct only for its grow-when-full callers. `HandlePool16::Alloc` S 004dedc0 copies the 16-byte entry and
returns the handle but does not append to the active list; that list is kept by the pool's users [known for
`Alloc`; inferred for the users, not read]. Freeing (`HandlePool16::FreeActive` S 004dee50, `HandlePool16::HandlePool_Free` S 0076b180) searches the active list linearly.

### 2.8 Hash state objects

**`ai::core::Crc32Acc`** (8 bytes) [known] S 00762320, S 00762350: `+0x00` u32 `crc`, `+0x04` u32 `byteCount`.
Constructor and `Reset`: `crc = crc32(0, NULL, 0)` = 0, `byteCount = 0`. `Update(buf, len)`:
`crc = crc32(crc, buf, len)`, `byteCount += len`. `UpdateDword(v)` S 00762400: the 4 little-endian bytes of
`v`. `Write(stream)` S 00762380 writes `crc` then `byteCount` as two 32-bit values; `Read(stream)` S 007623b0
reads them in the same order.

**`ai::crypto::MD5Hasher`** (0x70 bytes) [known] S 0041f140, S 0041f1d0, S 0041f180: `+0x00` the MD5 context
(count[2], state[4] at `+0x08`, 64-byte buffer at `+0x18`), `+0x58` an `NComm::MD5Digest` (vftable + 16 digest
bytes at `+0x5c`), `+0x6c` bool `finalized`. `UpdateString(str)` feeds the string's bytes; `GetDigest(out)`
finalises once and copies the 16 bytes; both refuse (return false) after finalisation.

### 2.9 `ai::math::RandomGenerator` (8 bytes) [known] S 006ec4a0, S 006ec2a0

`+0x00` u32 `state` (1..0x7FFFFFFE once running), `+0x04` u32 `seed` (the balanced seed, §3.7). The simulation's
instance and its save record: [logic-core.md](logic-core.md) §2.2, §3.3.

### 2.10 Math value types [known] S 004a8290, S 006e8a80, S 006e83c0

| Type | Layout |
|---|---|
| `Vec2f`, `Vec3`, `Vec4` | 2, 3, 4 × f32: x, y, (z, (w)) |
| `Quaternion` | 4 × f32: **x, y, z, w** |
| `Matrix44` | 16 × f32, `m[0..15]`; row-vector convention (Direct3D): translation in `m[12..14]` |
| `Matrix33` | 9 × f32 |
| `Plane` | 4 × f32 |
| `AABB` | min and max corner |
| `Ray`, `Segment3`, `OrientedBox`, `Frustum`, `TriangleList` | geometry helpers of the renderer and the picking code |

### 2.11 Timer globals

Frame timer [known] S 0057b790, S 0057b810 ([app-shell.md](app-shell.md) §2.2):

| Address | Type | Name | Meaning |
|---|---|---|---|
| 0088a610 | fn ptr | `g_Timer_GetTimeMsFn` | time source, milliseconds |
| 0088a614 | bool | `g_Timer_Initialized` | |
| 0088a615 | bool | `g_Timer_FixedStep` | when set, the frame delta reads 0.025 s. **Never written**: its only reference is the read in `Timer_GetFrameDeltaSeconds` [known: cross references] |
| 0088a618 | i64 | ticks per millisecond | `QueryPerformanceFrequency / 1000` (integer) |
| 0088a620 | u32 | `g_Timer_CurrentMs` | sample of this frame |
| 0088a624 | u32 | `g_Timer_PrevMs` | sample of the previous frame |
| 0088a628 | u32 | `g_Timer_FrameDeltaMs` | |
| 0088a62c | u32 | `g_Timer_StartMs` | sample at `Timer_Reset` |

`HiResTimer` (0x18 bytes [inferred from the last field]) [known] S 006e9de0, S 006e9d60: `+0x00` f32
`secondsPerTick` (1 / performance frequency), `+0x08` i64 `lastCounter`, `+0x10` f32 `frameDelta` (seconds),
`+0x14` f32 `totalTime` (seconds). One global instance (`Timer_GetGlobal`), plus 0x10-byte stopwatches made by
`Timer_CreateStarted` S 006e9db0.

### 2.12 Type identity and object creation

- The image carries Microsoft C++ run-time type information: 824 class type descriptor strings (`.?AV...`)
  and 13 struct ones (`.?AU...`), among them `.?AVIStoreable@NCore@@`, `.?AVUUID@NCore@@`,
  `.?AVMemoryStream@NComm@@`, `.?AVLogger@@` and the NComm event classes [known: string search]. They are the
  source of the original class and namespace names used in these documents. Game code does not
  appear to use `dynamic_cast` or `typeid` on polymorphic objects [inferred]: no function named
  `__RTDynamicCast` or `__RTtypeid` is in the name index, and the message texts those runtime helpers carry
  (`Bad dynamic_cast!`, `Attempted a typeid of NULL pointer!`, `Access violation - no RTTI data!`) are not in
  the image [known: string search for `dynamic_cast`, `typeid`, `rtti`]. The only users of `std::bad_cast` are
  the runtime's `use_facet` instantiations [known: scan of the decompiled image]. RTTI therefore matters as
  evidence of class names, not for behaviour.
- There is **no engine-wide type-id registry and no generic object factory** among the mapped functions
  [inferred: name index]. Objects that must be created from stored data use a per-system switch on a stored
  integer or name:
  - saves: the loader of each system decides which class to construct from values it has stored itself
    [inferred: no shared creation function is called from the `Load` functions read]; the rule for each
    object family is in its owning document ([settlers-jobs.md](settlers-jobs.md),
    [village-buildings.md](village-buildings.md), [ai-player.md](ai-player.md));
  - NComm events: a 32-bit class signature and a 32-bit event type at the start of each event
    (`../NCOMM_GAME_PROTOCOL.md`, [game-commands.md](game-commands.md) §2);
  - UI controls: `nUi::Factory::CreateObjectByName` S 004c2730 / `CreateObject` S 004c28a0 and
    `nMenu::Factory::CreateObjectByName` S 0060c880 map the `controltype` text of the layout XML to a class
    ([formats-inventory.md](formats-inventory.md) §2.8, §3.8);
  - singletons (`*_CreateInstance`, e.g. `S2CE::CResourceMgr::CreateInstance` S 004db050) are plain static
    creators, one per manager class.

---

## 3. Rules and algorithms

### 3.1 `NCore::BitStream` codec

**Core primitive** [known] S 0057df40 / 0057da40 (8-bit), S 0057e0b0 / 0057db70 (16), S 0057e220 / 0057dcb0
(32), S 0057d8d0 / 0057ddf0 (64); disassembly of S 0057e220 and S 0057d8d0 read for the full-width case. One
template instantiated for the widths `W` = 8, 16, 32, 64:

```
write_bits(buf, pos, value, n, W):          # 0 <= n <= W
    if n == W:  src = the W/8 bytes of value in memory order (little-endian)
    else:       src = the W/8 bytes of value byte-reversed (big-endian)
    # number the bits of src MSB-first through its bytes: 0 .. W-1
    for k in 0 .. n-1:
        if bit (W - n + k) of src is set:  set bit (pos + k) of buf       # OR, never clears

read_bits(buf, pos, n, W) -> value:
    acc = W/8 zero bytes
    for k in 0 .. n-1:  bit (W - n + k) of acc = bit (pos + k) of buf
    if n == W:  value = acc taken in memory order (little-endian)
    else:       value = acc byte-reversed (acc is big-endian)
```

Consequences [inferred from the pseudocode above, which transcribes the shift-and-mask loops]:

- A field narrower than its type (`n < W`) is the low `n` bits of the value, **most significant bit first**. At
  a byte boundary and with `n` a multiple of 8 this is big-endian.
- A full-width field (`n == W`) is the value's **little-endian bytes**, each byte most significant bit first.
  At a byte boundary it is a plain little-endian memory copy. So `WriteUInt32(v, 32)` and `WriteUInt32(v, 31)`
  use different byte orders.
- Writes only OR bits in: the target bits must be zero beforehand. Nothing in the class clears a buffer.
- `n > W` is not guarded.

**Typed methods** [known unless tagged]. `R` = `bitPos + n <= readLimitBits`; `Wr` = `writable` and
`bitPos + n <= writeLimitBits`. A failed check returns false and changes nothing, except in the multi-part
methods (var-uint, strings, `Float3` / `Float4`), where the parts already done stay done. No method tests
`n` against the width of its type.

| Method | Rule |
|---|---|
| `WriteUInt8/16/32/64(v, n)` | needs `Wr`; `write_bits` with W = 8/16/32/64; `bitPos += n` |
| `ReadUInt8/16/32/64(&v, n)` | needs `R`; `read_bits`; `bitPos += n` |
| `PeekUInt8/16/32/64(&v, n)` | as `Read`, cursor unchanged |
| `WriteBit(b)` / `ReadBit(&b)` | one bit through the 8-bit primitive with n = 1 |
| `WriteInt8/16/32/64(v, n)` | needs `Wr` for all `n` bits. **Sign and magnitude**: `WriteBit(v < 0)`, then `abs(v)` in `n − 1` bits through the same-width primitive (so always MSB-first). S 0057e550 (`NEG` at S 0057e58a), S 0057e650, S 0057e780, S 0057e880 |
| `ReadInt8/16/32/64(&v, n)` | needs `R` for `n` bits; sign bit, then `n − 1` magnitude bits; `v = sign ? −mag : mag`. S 0057f3a0, S 0057f430, S 0057f4d0, S 0057f570 |
| `WriteFloat(f, n)` | the 32 raw bits of the float through the 32-bit primitive (`n` = 32 gives little-endian IEEE bytes). S 0057f140 |
| `ReadFloat(&f, n)` | the same function as `ReadUInt32` (one body in both slots) |
| `WriteFloat3(p)` / `ReadFloat3(p)` | three consecutive 32-bit full-width fields; on failure after the first or second component the earlier ones stay written or read. S 0057f190, S 0057f200 |
| `WriteFloat4(p)` / `ReadFloat4(p)` | four such fields. S 0057f280, S 0057f300 |
| `WriteUIntInRange(v, min, max)` | fails unless `writable`, `max > min` and `min <= v <= max`; `nbits = bitlen(max − min)`; writes `v − min` (zero-extended to 64 bits) in `nbits` through the 64-bit primitive. S 0057e910 |
| `ReadUIntInRange(&v, min, max)` | fails unless `max > min` and the bits fit; `v = raw + min` (low 32 bits); **not clamped to `max`**. S 0057e9b0 |
| `WriteIntInRange(v, min, max)` | the same with signed compares; `nbits = bitlen(max − min)` on the sign-extended 32-bit difference; writes the low `nbits` of `v − min`. S 0057ea50 |
| `ReadIntInRange(&v, min, max)` | fails unless `max > min` (signed) and the bits fit; `v = (low 32 bits of raw) + min`, wrapping; no sign handling of its own and **not clamped to `max`**. S 0057eaf0 |
| `WriteVarUInt(v)` | groups of 7 bits, low group first, each as an 8-bit field at the cursor (no alignment); bit 7 = "more follows". The loop test is a **signed** `v >= 0x80` and the shift is arithmetic: a value ≥ 0x80000000 is written as one byte (its low 8 bits). S 0057ec10 |
| `ReadVarUInt(&v)` | `v |= (byte & 0x7f) << shift`, `shift += 7` (taken modulo 32), until a byte without bit 7; no limit on the number of groups; a failed limit check leaves the cursor after the groups already consumed. S 0057eca0 |
| `PeekVarUInt(&v)` | `ReadVarUInt`, cursor restored on success only. S 0057f100 |
| `WriteBytes(p, len)` | needs `writable`; `AlignWritePos(8)` (result ignored); `memcpy` to `data + bitPos / 8`; `bitPos += len * 8`. **No check against `writeLimitBits`.** S 0057d780 |
| `ReadBytes(p, len)` | `AlignReadPos(8)` (result ignored); `memcpy`; `bitPos += len * 8`; always true; **no check against `readLimitBits`**. S 0057d7d0 |

`bitlen(x)` = number of halvings until `x` is 0 (`Math_BitLength64` S 0057d490): 0 → 0, 1 → 1, 255 → 8,
256 → 9.

**Alignment** [known] S 0057e380, S 0057d730. `Align*(a)` with `a` in bits:

```
if a is a power of two (and not 0):  target = (bitPos - 1 + a) & ~(a - 1)       # stays if already aligned
else:                                target = bitPos - bitPos % a + a            # always advances; a = 0 divides by 0
write: fail if writeLimitBits <= target; else write (target - bitPos) zero bits (64-bit primitive), move
read:  fail if readLimitBits  <= target; else move the cursor (padding bits are not inspected)
```

Both fail when the aligned position **equals** the limit, i.e. when nothing may follow.

**Strings** [known] S 0057ed10, S 0057ee80, S 0057efd0, S 0057f000:

```
WriteCString(str):                      # the std::string overload passes its buffer; the length argument is unused
    utf8 = AnsiToUtf8(str up to its first NUL)                 # §3.6
    fail unless writable
    WriteVarUInt(byte length of utf8)                          # fail if it fails
    AlignWritePos(8)                                           # fail if it fails (the length stays written)
    memcpy(data + bitPos/8, utf8, len); bitPos += len * 8      # not checked against the write limit

ReadCString(dst, &size):
    ReadVarUInt(len); fail unless len < size                   # the cursor stays behind the length on failure
    aligned = (bitPos + 7) & ~7; fail unless aligned < readLimitBits; bitPos = aligned
    copy len bytes (not checked against the read limit), append NUL, convert Utf8ToAnsi
    bitPos += len * 8; size = ANSI length; copy the ANSI bytes to dst (no terminator)

ReadStdString(out):                     # [inferred]: the decompile loses the registers that carry len and out
    PeekVarUInt(len); resize out to len + 1; ReadCString(buffer, &size); resize out to the ANSI length
    on any failure: out = "" and return false
```

A zero-length string therefore fails to read when it is the last item of the buffer (the alignment test needs
`aligned < readLimitBits`), and fails to write when its length byte ends exactly at the write limit
(`AlignWritePos` needs `aligned < writeLimitBits`) [inferred].

**Cursor and limits** [known] S 0057d4e0..0057d720:

- `SeekByte(b)`: `bitPos = b * 8`; `SeekBit(b)`: `bitPos = b`. The only range test runs for negative arguments
  and cannot fail, so neither rejects anything.
- `SetLimitsBytes(r, w)` / `SetLimitsBits(r, w)`: a negative read limit becomes 0, one above the buffer size is
  clamped to it; a negative write limit becomes 0, one above the size is clamped.
- `GetLimitsBytes` rounds both limits up to whole bytes.
- `SetWritable(on)`: `writable = on && ownsBuffer`. A stream over a borrowed buffer can never be made writable.

### 3.2 The `LobbyMessage` bit packer (the lobby wire format)

[known] S 0048ef70, S 0048f0d0, S 0048f4c0, S 0048f530:

```
WriteBits(value, n):                    # n <= 0 writes nothing
    for i = n-1 down to 0:
        curByte |= ((value >> i) & 1) << (7 - (bitCursor & 7))
        bitCursor += 1
        if (bitCursor & 7) == 0:  buffer[byteIndex++] = curByte;  curByte = 0

ReadBits(n) -> value:                   # n <= 0 returns 0
    value = 0
    for i = n-1 down to 0:
        if (bitCursor & 7) == 0:  curByte = buffer[byteIndex++]
        if curByte & (1 << (7 - (bitCursor & 7))):  value |= 1 << i
        bitCursor += 1

Finalize():                             # once per outgoing message
    if namesMode:  crc.UpdateDword(0xFFF); crc.UpdateDword(bitCursor); WriteBits(crc.crc, 32)
    if (bitCursor & 7) != 0:  buffer[byteIndex++] = curByte; bitCursor = (bitCursor + 7) & ~7; curByte = 0
    finished = true
```

- Every field is **most significant bit first, with no alignment between fields**; the last byte is padded with
  zero bits. A 32-bit field is big-endian only when it happens to start on a byte boundary.
- `ReadBits` has **no end-of-buffer test**: reading past the body returns whatever follows in memory.
- The shift counts are taken modulo 32 by the processor: `n` above 32 is not usable. 64-bit fields have their
  own pair [known] S 0048efe0, S 0048f050. `WriteBits64` shifts the full 64-bit value and is correct for `n`
  up to 64. `ReadBits64` is not its inverse: for the bit with index `i` (from `n − 1` down to 0) it ORs
  `1 << (i mod 32)` into the **low** dword and ORs the sign extension of that mask into the high dword. Wire
  bits 32..63 therefore land on low-dword bits 0..31, and the high dword becomes 0xFFFFFFFF as soon as wire
  bit 31 or bit 63 is set, else 0. A 64-bit field round-trips only for values below 0x80000000 (high dword on
  the wire 0, bit 31 clear).
- Strings [known] S 0048fe20, S 004900a0, S 0048f440: `AnsiToUtf8`, then an **8-bit** byte length and the
  bytes, each through `WriteBits(…, 8)` (virtual slot `+0x38`, `WriteBuffer`), no terminator; the reader
  collects `len` bytes and converts `Utf8ToAnsi`. Both always return true. A string of more than 255 UTF-8
  bytes writes a truncated length byte followed by all its bytes, which desynchronises the reader.
- Names mode (type word bit 15): the message keeps a `Crc32Acc`. A named field mixes the CRC-32 of its name
  into it (`SelectField` S 0048f490, `WriteNamedBits` S 0048f570); a bit field then mixes the tag 1 and its
  bit width (S 0048f570, S 0048f340, S 0048f380), a byte buffer the tag 1 when its caller asks for it
  (S 0048f440; the string writer does not), a string the tag 3
  (S 0048fe20, S 004900a0) [known]; the tags of the other accessors are in `../message-catalog.md`.
  `Finalize` mixes 0xFFF and the bit count and appends the 32-bit result; `FinishRead` S 0048f530 mixes the
  same two values, reads the 32 bits and **discards them without comparing** [known]. The checksum covers the
  schema, not the values. Messages built by the client clear names mode (S 0048fb00).
  Details: [lobby-client-state.md](lobby-client-state.md) §3, `../message-catalog.md`.
- Field name hash: `LobbyMessage_HashFieldName(name)` S 0048ef10 = CRC-32 (§3.5) of the name's bytes without
  the terminator.

The typed accessors built on these (bool = 1 bit, packed unsigned, raw little-endian 32, location block) are
listed field by field in `../message-catalog.md` ("Field bitstream").

### 3.3 Byte stream rules

**`NComm::MemoryStream`** [known] S 004122f0, S 00412360, S 00412240, S 004123a0, S 00412400:

- `ctor(capacity, growBy)`: zero-filled buffer (`calloc`), `size = pos = 0`.
- `ctor_Buffer(data, len, readOnly, copy)`: `size = capacity = len`, `pos = 0`; with `copy` a private copy is
  made (and `growBy = len` unless read-only); without it the buffer is borrowed (`bExternalBuffer = 1`,
  `growBy = 0`).
- `Write(src, len)`: if `capacity < pos + len`, the capacity grows by the smallest multiple of `growBy` that
  fits, through `realloc`, **unless the buffer is external**; then `memcpy` at `pos`, `size += len`,
  `pos += len`. When the growth is skipped (external buffer, or `realloc` failed) the copy still happens: a
  buffer overrun. `size` is incremented by `len` even when the write overwrites earlier bytes after a `Seek`.
  `bReadOnly` is not tested. The growth amount is searched **before** the external-buffer test, by adding
  `growBy` until the data fits: with `growBy == 0` (every stream made by `ctor_Buffer` except a writable
  private copy of at least one byte) a write beyond the capacity never returns [inferred from the loop].
- `Read(dst, len)`: if `pos + len <= size`: copy, advance, return `len`; else return 0 and change nothing.
- `Seek(pos)`: clamped to `0 .. size`.
- `WriteString(str)`: `u16` length (the string's size truncated to 16 bits), then that many bytes; no
  terminator. The byte count is passed on as a signed 16-bit value, so a string of 0x8000 or more characters
  yields a negative size.
- `ReadString(out)`: if fewer than 2 bytes remain the length is 0 and the cursor stays; otherwise a 16-bit
  length, **read as signed and sign-extended** (a stored length of 0x8000 or more becomes a count near 2^32),
  then that many bytes are appended to the emptied string **without a check against `size`**, and the cursor
  advances by the length.
- Values are raw little-endian memory images; there is no tag, alignment or type information
  (`../NCOMM_GAME_PROTOCOL.md`).

**`NBase::File` strings** [known] S 006e65d0, S 006e6960: `WriteString` = `u32` length, then the bytes (none
for an empty string); `ReadString` = `u32` length, then the bytes into a **260-byte stack buffer with no length
check** (a stored length above 259 overruns it), and the result ends at the first zero byte. Used by the
particle effect files (`.pfx`), the avatar files (`.avo`, `.npc`) and the animation graph
([formats-inventory.md](formats-inventory.md) §3.3, §3.5).

### 3.4 Section tag record

[known] S 0057cfc0, S 0057cf80, S 007804f0, S 00762380. `BeginWriteSection(tag)` writes 12 bytes:

| Off | Type | Value |
|---|---|---|
| 0 | i32 | `tag.level`: the current version of that class's layout |
| 4 | u32 | CRC-32 of the section name (§3.5) |
| 8 | u32 | length of the section name in bytes |

Example [inferred, computed]: the name `LogicSystem` has CRC-32 0xA5E2D1A2 and length 11.

`ReadSection(tag)` reads the three values and returns the first; `BeginReadSection(tag)` reads and discards all
three. **Neither compares the CRC or the length with the expected tag**, and there is no end mark and no
section size: a reader that loses its place cannot resynchronise. The checksum stream ignores tags; the dump
stream prints them. Everything else: [save-format.md](save-format.md) §2.4, §3.5.

### 3.5 Hashes

**CRC-32** [known] S 007627c0, S 00762520, table S 00831b68 (first entries 0x00000000, 0x77073096, 0xEE0E612C,
0x990951BA): the standard zlib `crc32` (reflected polynomial 0xEDB88320, initial value and final XOR
0xFFFFFFFF, slice-by-4 tables). `crc32(crc, NULL, len)` returns 0, which is how an accumulator is started. Any
library CRC-32 of the "zip/PNG" kind reproduces it; the CRC of the empty string is 0.

Uses (complete as far as the callers of `Crc32Acc` show) [known for each address]:

| Use | Input | Evidence |
|---|---|---|
| section tag | bytes of the section name | S 005816e0 |
| lockstep checksum, game-settings CRC | bytes fed by `CRCStream` | [logic-core.md](logic-core.md) §3.6; S 00414720 |
| container: plaintext CRC, key CRC (`FileCrypt_Crc32OfKey`: the 16 key bytes) | | S 006ee680, `../asset-formats.md` §1 |
| container: seed of the per-file key | lower-case file name without folders | S 006eeac0, `../asset-formats.md` §1 |
| lobby field names and the schema checksum | field name bytes; 32-bit tags | S 0048ef10, S 0048f4c0 |
| password typed into `EnterPasswordDialog`; password of a minigame table being created | bytes of the text | S 00441100, S 0046cf20 ([lobby-screens.md](lobby-screens.md), [minigames-client.md](minigames-client.md)) |

**MD5** [known] S 00428c40, S 00428c70, S 00428d40, S 004284f0: init, update, final and transform functions
(the names `MD5Init` ... are the map's) with the standard initial state 0x67452301, 0xEFCDAB89, 0x98BADCFE,
0x10325476 [known] S 00428c40. The context keeps the bit count before the state (§2.8), which is not the
field order of the RFC 1321 reference code; that the transform is standard MD5 is [inferred: its body was not
compared round by round]. Used for the match password: the password string's bytes
are hashed and the 16-byte digest travels in `EventGameInformation` and `EventUserInformation` [known]
S 00413c60, S 0040c220, S 0040ad60 ([network-session.md](network-session.md)).

**No name-to-id hash.** Names are not turned into numeric ids anywhere else [inferred: the table above lists
every use the callers of `Crc32Acc` show, and no other hash function is named in the index]: property ids are
literals of the data, UI controls, effects and files are found by their text
([formats-inventory.md](formats-inventory.md) §2.4). Maps keyed by `std::string` compare the text.

### 3.6 Text encoding

| Where | Encoding | Evidence |
|---|---|---|
| in memory, everywhere | 8-bit, the process's ANSI code page (`CP_ACP`) | §2.7 |
| data files (language tables, XML attributes, Lua strings) | 8-bit, Windows-1252 in the German install; some XML files declare `utf-8` | [formats-inventory.md](formats-inventory.md) §3.8, §3.9 |
| LobbyMessage strings, `BitStream` strings | **UTF-8** on the wire, converted at the accessor | [known] S 0048fe20, S 004900a0, S 0057ed10 |
| NComm event strings (player name, chat text between peers, map name) | the raw 8-bit bytes, no conversion | [known] S 004123a0; [network-session.md](network-session.md) |
| save and profile files | the raw 8-bit bytes | [save-format.md](save-format.md) §2.2 |
| file names | 8-bit, `CreateFileA` / `FindFirstFileA` | [known] S 0057d140; [formats-inventory.md](formats-inventory.md) §3.1 |

Conversion helpers [known] S 00487530, S 00487620:

- `Str_AnsiToUtf8(in)`: `MultiByteToWideChar(CP_ACP)` then `WideCharToMultiByte(CP_UTF8 = 65001)`.
- `Str_Utf8ToAnsi(in)`: `MultiByteToWideChar(CP_UTF8)` then `WideCharToMultiByte(CP_ACP)`, default flags: a
  character the ANSI code page lacks becomes a best-fit letter where Windows has one, else the default
  character `?` [known: no flag or default-character argument is passed]. In the running game the trader label
  "Hinnerk Őł字" sent as UTF-8 shows as "Hinnerk Ol?" (`Ő` → `O`, `ł` → `l`, `字` → `?`), and the `ä` of
  "Händler" (in Windows-1252) is unchanged [live, 2026-10-14].
- Both pass the string as a C string (length −1): text after an embedded zero byte is dropped.

Consequence: two peers with different ANSI code pages see each other's lobby names correctly (UTF-8 in
between) but each other's in-match NComm strings as raw bytes of the sender's code page [inferred].

Other helpers [known]: `Str_ToLower` S 00487350 (`tolower` per character, copy), `Str_Tokenize` S 00487b20
(delimiters, kept delimiters, quote characters, escape characters, optional empty tokens → vector of strings;
[inferred] from its prototype, the body was not read), `Str_ToLong` / `Str_ToULong` S 00487240 / 00487270
(`strtol` / `strtoul` with base 0: decimal, `0x` hexadecimal or leading-`0` octal), `Str_Snprintf` S 004414e0
(`_vsnprintf_s` with count = buffer size) and `Str_ParseHexUInt32` S 005455b0, called by the thirteen
`LuaProps_*_create` functions (S 0054a4d0 .. S 00550880; their use of the result:
[properties-data.md](properties-data.md)). It takes up to 32 characters, stops at the first one that is
neither in `*`..`?` (0x2A..0x3F, value = low nibble) nor in `a`..`f` / `A`..`F` (value = low nibble + 9), and
ORs digit `k` of `n` in at `4 · (n − 1 − k)` bits (shift count modulo 32). There is no `0x` prefix handling;
`*`..`/` and `:`..`?` count as the digits 10..15.

`ai::text::TextTokenizer` S 006ec250 (S 006ec120) splits one line at runs of space and TAB, and
`ai::text::TextLineBuffer` S 006ec200 (S 006ebfd0) reads a whole file and indexes its lines at LF; text after
the last LF is not a line. Both serve only the bitmap font
loader ([formats-inventory.md](formats-inventory.md) §3.6).

Lower-casing (`tolower`, `_strlwr` in the file index) follows the C runtime's current locale. The only game
function that calls `setlocale` is `nUi::Text::SetText` S 004b3fe0: for a text widget with the `uppercase` or
`lowercase` attribute it saves the current locale, switches to the system locale (`setlocale(LC_ALL, "")`),
transforms the text with `toupper` / `tolower` and restores the saved locale [known]
([ui-toolkit.md](ui-toolkit.md)). Everywhere else the default "C" locale applies, in which only A..Z and a..z
are folded: a file name or a lobby name key with an upper-case umlaut keeps it. The only other callers of
`setlocale` are the C++ runtime's `std::_Locinfo` constructor and destructor (S 006f1938, S 006f17d9): the
constructor saves the current locale name and the destructor sets it again, and the object lives only inside
a facet constructor (S 00403fe0, five callers), so it never leaves another locale active [known].

### 3.7 Random generator

**Step** [known] S 006ec350 (also inlined in S 006ec3a0, S 006ec410): Park-Miller "minimal standard",
`state = state * 16807 mod (2^31 − 1)`, computed without 64-bit arithmetic:

```
next(state):                                           # all arithmetic 32-bit unsigned, wrapping
    hi = (state >> 16) * 16807
    lo = (state & 0xFFFF) * 16807 + ((hi & 0x7FFF) << 16)
    if lo > 0x7FFFFFFF:  lo = (lo & 0x7FFFFFFF) + 1
    lo += hi >> 15
    if lo > 0x7FFFFFFF:  lo = (lo & 0x7FFFFFFF) + 1
    state = lo;  return lo
```

**Seeding** [known] S 006ec2a0, table S 007fd528 (32 dwords, read):

```
ORDER = 12,23,10,25,8,27,6,29,4,30,1,22,9,13,21,0,17,26,5,15,18,28,11,2,14,3,24,7,19,16,20,31

SetSeed(seed):
    s = seed & 0x7FFFFFFF
    c = number of set bits among bits 0..30 of s
    if c < 8:   for i in 0 .. 8-c-1:    s |=  (1 << ORDER[i])
    if c > 24:  for i in 0 .. 32-c-1:   s &= ~(1 << ORDER[i])
    this.seed  = s
    this.state = (s == 0) ? 1 : (s & 0x7FFFFFFF)
```

The table entries are applied whether or not the bit already has the wanted value, so the result can still
have fewer than 8 (or more than 24) set bits. Examples [inferred, computed]: 0x5432ACE0 → unchanged (13 bits);
0x7D6 → unchanged (8 bits); 0x7C0 → 0x008017C0; 0x400 → 0x0A801540; 0 → 0x2A801540 (so `SetSeed` never
produces state 1); 0xFFFFFFFF → 0x7FFFEFFF.

Other entry points [known]:

| Function | Rule |
|---|---|
| `ctor_WithSeed(seed)` S 006ec4a0 | `state = seed = 0`, then `SetSeed(seed)` |
| `RestartFromSeed()` S 006ec280 | `state = seed & 0x7FFFFFFF`, or 1 when `seed == 0` (no balancing) |
| `NextInRange(min, max)` S 006ec3a0 | `next() % (max − min + 1) + min`, unsigned modulo; `max − min + 1 == 0` divides by zero |
| `Math_Random_NextUnitFloat()` S 006ec410 | `(float)(next() % 1000001) / 1000000.0`: 0.0 .. 1.0 inclusive, in steps of 10^-6 |

No rejection step anywhere: the modulo bias is part of the behaviour.

**Instances** [known: every caller of `ctor_WithSeed` (19) and `SetSeed` (5) in the image; the purposes are
[inferred] from the names of the functions that use each instance]:

| Instance | Seed | Purpose |
|---|---|---|
| `g_LogicRandom` S 00889b08 | 0x5432ACE0 (static initialiser S 007c07d0) | **the simulation's generator**; [logic-core.md](logic-core.md) §3.3 |
| local in `Game_DistributeChestsForNetworkMatch` S 00775dd0 | 0x5432ACE0, then `SetSeed` with a value derived from the match (`GameSeed`) | chest placement in network matches; [logic-core.md](logic-core.md) §3.5 |
| locals in `FileCrypt_DeriveFileKey` S 006eeac0, `FileCrypt_XorScramble` S 006ee6b0 | from the file name CRC / the key | container key stream; `../asset-formats.md` §1 |
| `ai::terrain::TerrainGenerator +0x0c` S 006b0e60 (member of `S2CG::CMapRenderer`, built by its constructor S 006890f0) | 0x5432ACE0 | noise terrain: drawn from only by `ApplyFaultLines` S 006b1dd0, which `Run` S 006b24f0 and `RunToBuffer` S 006b25a0 call in mode 1. `Run` writes heights through the map's height sink; its only caller is the virtual `CMapRenderer::RunTerrainGenerator` S 00688540, which like `RunTerrainGeneratorToBuffer` S 00688590 is never called (§10 Q5) [known] ([map-editor-devtools.md](map-editor-devtools.md)) |
| `ParticleEmitterParams +0x74` S 004f2d50 | 0x5432ACE0, then `SetSeed(randomSeed)` at the end of the constructor, `randomSeed` = the low 16 bits of the object's first dword as the decompile shows it; `Reseed(offset)` S 004f2c90 = `SetSeed(randomSeed + offset)` | particles |
| heap object of `Lobby::CLobby::StartUp` S 004f8c90 (8 bytes, kept in the lobby context) | 0x5432ACE0 | 3D lobby |
| static S 0088d7c8 (`CCharacterMgr::CreateCharacter` S 00695490) | 0x5432ACE0 | settler visuals |
| `S2CG::SwarmMgr` S 0069ab00 | **the object's own address** | swarms (visual); differs per run |
| static S 0088d9a0 (`S2CG::Projectile` ctor S 006a3720) | 0x7D6 | projectile visuals |
| static S 0088da38 (`S2CG::Building::InitFirePoints` S 006ac510) | 0x5432ACE0 | fire effect positions |
| static S 0088deb4 (`ai::render::CharacterMovement::RandomizeInitialFacing` S 006c53f0) | 0x7C0 | initial facing of figures |
| `ai::gfx::StreetRenderer` S 006c4290 | 0x5432ACE0 | street decoration |
| static S 0088decc (`S2CG::Animal::UpdateLogic` S 006ce2c0) | 0x5432ACE0 | animal visuals |
| static S 00889860 | 0x5432ACE0 (S 007c01a0) | lobby animation graph random node: `AnimRandomNode_Shuffle` S 0051e810, `ai::lobby::AnimRandomNodeState::Init` / `Update` S 0051e9c0 / S 0051ea30 |
| static S 0088d47c | 0x400 (S 007caaf0) | landscape resource particles: `S2CG::CLandscape::SpawnRandomResourceParticle` S 0068ac10, `CollectResourceParticleCandidates` S 0068b220 |
| static S 0088d4ec | 0x5432ACE0 (S 007cab10) | map object instances: `ai::render::MapObjLayer::AddInstance` S 0068dd40, `AddSingleMeshInstance` S 0068f120 |
| static S 0088e118 | 0x5432ACE0 (S 007cb190); `S2CG::ExtendedMeshData::BuildInstancedVertices` S 006dd8e0 re-seeds it per instance with `SetSeed(object address + instance index)`, so the scatter differs per run | instanced mesh scatter; also stepped by `S2CG::ExtendedMeshData::Load` S 006dddc0 |
| static S 0088e120 | 0x5432ACE0 (S 007cb1b0) | random animation player: `ai::anim::RandomAnimPlayer::Shuffle` S 006ddea0 and its constructor and update (S 006ddf79, S 006de000 are the referencing instructions) |

Every static instance is referenced only by its initialiser, its exit-time destructor and the functions named
in its row [known: cross references of S 00889860, S 0088d47c, S 0088d4ec, S 0088e118, S 0088e120]. None of
these functions belongs to a simulation namespace (`NLogic`, `NSettlers`, `NVillage`, ...): they are
`ai::lobby`, `ai::render` and `S2CG` (scene graph) code. None of them writes anything the simulation reads
[known, with the [inferred] limit below]: their callers are render and lobby code only (`CMapRenderer::Update`
S 006888f0, `MapObjLayer::SpawnLandscapeObject` S 00690240, `AnimGraph::CreateStateRandomizer` S 0050f070,
`AnimModel::Update` S 0050ec80, `CharacterAnimation::UpdateLogic` S 006c6590, `AnimationSet::CreateRandomAnimPlayer`
S 006cac90; the two `ExtendedMeshData` functions have no direct caller); in their whole direct call trees the
only simulation function is the reader `NMap::Exploration::IsExplored` S 00542b10, no simulation global is
written (the writes go to CRT, resource-cache, shader and screenshot singletons) and `g_LogicRandom` is not
referenced. The other way round, no function of a simulation namespace calls into `S2CG`, `S2CE`, `ai::render`,
`ai::anim` or `ai::lobby` code directly (the two hits, `ObserverList::Subscribe` S 00458860 and `Notify1`
S 004760c0, are generic observer helpers filed under `ai::lobby`) [known: call graph of every function of
those namespaces]. Not resolved one by one: the indirect calls of the render trees; their objects are render
objects by their types [inferred].

The C runtime's `rand` is a separate source [known: every function of the decompiled image that calls `srand`
or `rand`]:

- seeded in two places: `VillageServerConnection::HandleEnterWorld` S 0046f670 (`srand(Timer_GetCurrentMs())`,
  S 0057b840) and `NComm::EventGameInformation::AssignRandomPlayerIndicesAndTeams` S 00413930
  (`srand(time(NULL))`), plus Lua's `math.randomseed` S 005ca350;
- `AssignRandomPlayerIndicesAndTeams` feeds match set-up [known] S 00413930: on the host, each slot below
  `maxPlayers` without a player index gets `free[rand() % freeCount]`, each without a team gets
  `rand() % maxPlayers`; the result is distributed to the peers ([network-session.md](network-session.md),
  [match-setup-room.md](match-setup-room.md));
- the other 24 callers of `rand` are, by their names [inferred]: lobby and minigame code (S 0043e500,
  S 0046c360, S 0046f670, S 0046f9b0, S 005175d0, S 0051fcd0, S 00524420, S 005248b0), UI (S 004c7f90,
  S 0062b4a0, S 0063f550), audio (S 0056e190, S 0056f880), map editor and debug tools (S 00601750,
  S 006020e0, S 006025d0, S 00602890, S 006029a0, S 00602f20, S 006033d0), the cinematic camera
  (`NSettlers::System::PickRandomCinematicTarget` S 006556a0, which picks one of the local player's settlers
  with `rand() % count` for the camera, and `nGame::Camera::UpdateCinematicMode` S 00786140),
  `S2CG::FarmBuilding::ctor` S 006d59e0 and Lua's `math.random` S 005ca190. What the simulation scripts draw
  from: [logic-core.md](logic-core.md) §3.3.

### 3.8 Math conventions

- **Floats.** All geometry is `f32`. `Fpu_SetDefaultControlWord` S 0057b9b0 forces the x87 control word:
  `_controlfp(0x9001f, 0xffff)` (all exceptions masked, round to nearest), then `_controlfp(0x20000, 0x30000)`
  (24-bit precision) [known for the calls; the meaning of the constants is the runtime's `_MCW_*` / `_PC_24`
  definition]. Its four callers are `CApplicationEx::Initialize` S 004075d0, `CApplicationEx::FrameTick_InGame`
  S 004018e0, `Lobby::CLobby::Update` S 004fb460 and `nGame::System::HandleGameCommand` S 007845a0 [known:
  caller list]; why that matters: [logic-core.md](logic-core.md) §8,
  [app-shell.md](app-shell.md) §8. No fixed-point number type exists in the math library [inferred: every
  `ai::math` function read takes and returns `float`]; the simulation's own integer units (map cells, ticks,
  per-mille factors) are defined by its documents.
- **Angles are radians** in every `ai::math` function read (arguments go straight into the runtime's `sin` /
  `cos`) [known] S 004a8300, S 006e83c0, S 006e90c0. Degrees appear at interfaces: the avatar rotation of the
  lobby wire (`ReadLocationBlock` S 0048f670, `../village-and-character-protocol.md`) and data files, each
  stated by its own document.
- **Matrices** are 4 × 4 `f32` in row-vector (Direct3D) layout; `TransformPoint` S 004a8290 [known]:
  `x' = x·m0 + y·m4 + z·m8 + m12`, `y' = x·m1 + y·m5 + z·m9 + m13`, `z' = x·m2 + y·m6 + z·m10 + m14` (no
  division by w). The projection and view builders are the left-handed Direct3D ones (`PerspectiveFovLH`
  S 006e97e0, `OrthoLH` S 006e8e10, `LookAtLH` S 006e9b70) [inferred from the names and the element layout of
  `RotationYawPitchRoll`; their bodies were not read].
- Elementary rotations (all other elements 0, `m15 = 1`) [known]:

  | Function | Non-trivial elements |
  |---|---|
  | `SetRotationX(a)` S 004ef9a0 | `m0 = 1`, `m5 = cos`, `m6 = −sin`, `m9 = sin`, `m10 = cos` |
  | `SetRotationY(a)` S 004efa20 | `m5 = 1`, `m0 = cos`, `m2 = −sin`, `m8 = sin`, `m10 = cos` |
  | `SetRotationZ(a)` S 004a8300 | `m10 = 1`, `m0 = cos`, `m1 = −sin`, `m4 = sin`, `m5 = cos` |

  With `TransformPoint`, `SetRotationY` equals `D3DXMatrixRotationY`, while `SetRotationX` and `SetRotationZ`
  are the transposes (the opposite sense) of their Direct3D namesakes [inferred by comparing the elements].
- `RotationYawPitchRoll(yaw, pitch, roll)` S 006e90c0 [known], with `cy, sy` of yaw, `cp, sp` of pitch, `cr, sr`
  of roll: `m0 = cr·cy + sr·sp·sy`, `m1 = sr·cp`, `m2 = sr·sp·cy − cr·sy`, `m4 = cr·sp·sy − sr·cy`,
  `m5 = cr·cp`, `m6 = sr·sy + cr·sp·cy`, `m8 = cp·sy`, `m9 = −sp`, `m10 = cp·cy`, `m15 = 1`, rest 0 (the layout
  of `D3DXMatrixRotationYawPitchRoll`). The first stack argument is yaw, the second pitch, the third roll
  [known: disassembly; the sine of the second argument is the value negated into `m9`, the sine of the third
  times the cosine of the second is `m1`].
- **Quaternions** are (x, y, z, w). `FromAxisAngle(axis, angle)` S 006e83c0 [known: disassembly]:
  `h = angle · 0.5` (constant S 007d4a90 = 0.5); `xyz = axis · sin(h)`, `w = cos(h)`; the axis is not
  normalised. `Matrix44::FromQuaternion` S 006e8a80 [known]: `m0 = 1 − 2(yy + zz)`, `m1 = 2(xy + zw)`,
  `m2 = 2(xz − yw)`, `m4 = 2(xy − zw)`, `m5 = 1 − 2(xx + zz)`, `m6 = 2(yz + xw)`, `m8 = 2(xz + yw)`,
  `m9 = 2(yz − xw)`, `m10 = 1 − 2(xx + yy)`, `m15 = 1`, translation 0. `RotateVec3` S 004f3620 computes
  `q · v · conj(q)` with `v` extended by w = 1. `FromEuler(angles)` S 006e8700 takes a pointer to three
  radians [known: disassembly]. With `c0, s0` = cos, sin of `angles[0] / 2`, and likewise `c1, s1`, `c2, s2`:
  `x = c0·c1·s2 + s0·s1·c2`, `y = c0·s1·c2 + s0·c1·s2`, `z = s0·c1·c2 − c0·s1·s2`,
  `w = c0·c1·c2 − s0·s1·s2`. So `angles[0]` alone turns about z, `angles[1]` about y, `angles[2]` about x, and
  the result equals the Hamilton product `qy(angles[1]) · qz(angles[0]) · qx(angles[2])` [inferred, computed
  from the four formulas].
- **Yaw of a direction**: `Math_YawFromDirection(dir)` S 006eece0 [known], reference axis S 00882870 =
  (0, 0, 1): `d = dir · (0,0,1) = dir.z`; `d > 0.99` → 0; `d < −0.99` → −π (−3.1415927); otherwise `acos(d)`
  with the sign of `dir.x` (`+acos(d)` when `dir.x·1 − dir.z·0 > 0`, `−acos(d)` otherwise, so also for
  `dir.x == 0`). The input is not normalised here. `Math_YawBetweenPoints(from, to)`
  S 006eedc0 normalises `to − from` first. Used by figure facing and hit effects (presentation).
- **Rotation about an axis**: `RotationAxis` S 006e8fa0 [known] builds the standard Rodrigues matrix, but the
  engine multiplies row vectors by it, so the rotation runs in the opposite sense to D3DX's
  `D3DXMatrixRotationAxis` for the same angle (the falling tree, [rendering.md](rendering.md) §3.11).
- Approximations of the presentation [known]: `Math_FastSqrt` S 006e8a20 (256-entry table S 007fd118 on the
  float's bit pattern; used by effects, by the sea-route strip, `RouteDecal::BuildFromSpline` S 006e2450,
  [world-objects-rendering.md](world-objects-rendering.md) §3.7, and by `Ray::IntersectSphere` S 006ec570, which
  the ship pick `PickShip` S 00697db0 reaches through `Ship::IntersectRayBoundingSphere` S 006a5020: with `b` the
  ray direction dotted with `origin − centre` and `disc = b² − (|origin − centre|² − r²)`, a `disc ≤ 0` (tangent
  included) is a miss, else `tNear = −b − FastSqrt(disc)`, `tFar = FastSqrt(disc) − b`; the pick keeps the ship
  with the smallest `tNear ≥ 0` whose mesh the ray also crosses. The approximation shifts `tNear` by a fraction
  of the root, so it can only change which of two almost equally distant ships wins, or the `≥ 0` test with the
  eye on the sphere's surface; the other caller is the character pick `CCharacter::RayHitTest` S 00691220), `Math_FastCosLut` S 006e8a50 (256-entry table S 007fcd10), `ai::math::SinTable1024`
  S 004ccb90 (1024 scaled sine entries; that they span one full turn and that the one instance S 00885dc8
  serves `AlphaFanPicture` is [inferred]: the sine argument is lost in the decompile and the user of the
  instance was not read),
  `Math_FloatToIntRound` S 006e89f0 (colour packing). Callers [known: caller lists]: particle quads
  (S 004f43d0, S 004f4860, S 004f1f40), street and route decals (S 006df940, S 006e0e30, S 006e2450), the swarm
  flock update S 007707c0, `ai::math::Ray::IntersectSphere` S 006ec570 and the colour packers S 004a81b0,
  S 004a8380; none is in a simulation namespace. The ray test is called by `S2CG::CCharacter::RayHitTest`
  S 00691220 and `S2CG::Ship::IntersectRayBoundingSphere` S 006a5020 only (scene-graph hit tests of figures
  and ships under the cursor [inferred from the names]).

### 3.9 Timers and clocks

Frame timer [known] S 0057b760..0057b990 (summary; full text [app-shell.md](app-shell.md) §3.4):

- Source: `QueryPerformanceCounter / (QueryPerformanceFrequency / 1000)` in integer milliseconds, or
  `GetTickCount` when no performance counter exists; the low 32 bits are kept.
- `Timer_UpdateFrame` once per frame: `current = source`; `delta = (previous == 0) ? 0 : current − previous`;
  `previous = current`.
- `Timer_GetFrameDeltaSeconds` = `delta / 1000.0` as unsigned (or the constant **0.025** when the never-set
  fixed-step flag is on, §2.11); `Timer_GetFrameDeltaMs` = `delta`; `Timer_GetTotalSeconds` =
  `current / 1000.0`; `Timer_GetCurrentMs` = `current`; `Timer_GetElapsedMsSinceStart` = `current − start`;
  `Timer_GetElapsedSecondsSinceStart` = that / 1000.0.
- `Timer_Reset`: `current = previous = delta = 0`, `start = source`. Called at start-up and from
  `NLogic::System::PostLoad` S 005273d0.

Lobby clock synchronisation [known] S 0057b910, S 004f4d10:

```
Timer_SyncElapsedToServerTick16(serverTick16, maxDriftMs):
    local  = (current - start) & 0xFFFF
    ahead  = (local - serverTick16) & 0xFFFF          # how far the local clock is ahead
    behind = (serverTick16 - local) & 0xFFFF
    if ahead < behind:
        if ahead < maxDriftMs: return false
        start += ahead                                # slow the local clock down
        while current < start: start -= 0x10000       # keep elapsed non-negative
    else:
        if behind < maxDriftMs: return false
        start -= behind
    return true

Net_ExpandWireTick16(tick16) -> 64-bit ms:            # high dword always 0
    now = current - start
    ahead = (tick16 - now) & 0xFFFF;  behind = (now - tick16) & 0xFFFF
    return ahead < behind ? now + ahead : now - behind
```

`Lobby::CLobbyClient::OnWorldTick` S 00503590, the only caller, passes a drift limit of 250 ms (0xFA) [known];
`LobbyComm::AvatarProxy::ReadLocationBlock` S 004824b0 is the only caller of the second
([lobby-world-client.md](lobby-world-client.md)).

`HiResTimer` [known] S 006e9d60, S 006e9d40, S 006e9cf0: `Timer_Tick` sets `frameDelta = (now − lastCounter) ·
secondsPerTick` and adds it to `totalTime`; `Timer_Reset` re-samples and zeroes both. The global instance is
ticked by `S2CG::Scene::UpdateDetailFlagsAndTime` S 0067f6b0 and feeds scene animation time; the stopwatches
serve the hardware benchmark (S 004d3420, S 004d5270).

Which clock drives what [known for the callers named]:

| Consumer | Clock |
|---|---|
| logic ticks | `Timer_GetFrameDeltaSeconds`, accumulated as seconds by `NLogic::System::Update` S 00527070 ([logic-core.md](logic-core.md) §3.1) |
| net ticks, ping, hang detection | `Timer_GetTotalSeconds` / frame delta (S 00410f70, S 00408860; [network-session.md](network-session.md)) |
| UI animation, cursor and caret blink, dialogs | `Timer_GetFrameDeltaMs` / `...Seconds` (S 00492370, S 0049a090, S 00457a00) |
| player message lifetimes | `Timer_GetFrameDeltaSeconds` (`Timer_DecrementByFrameTime` S 005c0250; [players-victory.md](players-victory.md) §3) |
| 3D lobby world, minigame phases | elapsed-since-start clock, re-synchronised to the server tick (S 00503590, S 004715a0) |
| scene effects | `HiResTimer` global |
| log line time stamps | `GetLocalTime` (S 006e5950) |

### 3.10 Logging and assertions

- **Engine log** `Log_Printf(level, fmt, ...)` S 006e5950 [known]: written when `level <= g_LogLevel`; line =
  `- hh:mm:ss - ` + text + LF; one shared 4096-byte buffer; file `Logfile_0.txt` with nine rotated
  predecessors. Full rules: [app-shell.md](app-shell.md) §3.12.
- **`Logger`** (RTTI name `Logger`) [known] S 00417e20, S 004165b0, S 004176a0: a log-file class with
  levels, nested sections (`EnterSection` / `LeaveSection`, S 00418b10 / S 00418c40) and hex dumps
  (S 00418600).
  - `Open(truncate)` runs once per object: it calls the size check, opens the file through a C++ `ofstream`
    (truncating or appending) and writes the banner `---...--- Log begins on <asctime text> ---...---`.
  - The size check `RotateIfTooLarge` S 004165b0: when `maxFileSize >= 0` and the file is larger, the file is
    **deleted**; no backup copy is kept.
  - Line prefix S 004176a0: `dd/mm/yyyy hh:mm:ss - ` (local time), a two-character level tag (1 `> `, 2 `< `,
    4 `F `, 0x10 `D `, 0x12 `I `, 0x14 `W `, 0x18 `E `, 0x20 `! `, −1 `A `, any other value two spaces), then
    `indentDepth` spaces with a bar (`|`, or byte 0xB3 when the box-character flag is set) every `indentStep`
    columns.
  - The NComm layer's instance S 00879a08 is written through the scope guard `ai::ncomm::LogScope` S 0040a410,
    which enters a section with the name its caller passes, at level 4.
  - `LobbyComm::Logger` S 004669e0.. is a second copy of the same design for `LobbyComm.log`
    ([app-shell.md](app-shell.md) §3.12).
  - The NComm instance [known] S 007be6f0 (static initialiser), S 0040a530: built with path `logger.log`,
    `indentDepth` 0, `indentStep` 4, `maxFileSize` −1 (the size check never deletes), `levelMask` 0xFFFFFFFF,
    box characters off. `NComm_Manager::ctor` sets the path to `<log directory>\comm.log` (the directory of
    `NComm::ConnectionSettings`, which `CApplicationEx::Initialize` S 004075d0 copies from the application's
    log path), calls `Open(true)` (truncate) and then sets the mask from `g_LogLevel` S 00882690: 0 → mask 0
    (nothing is written after the banner); 1 → mask `& ~0x16`; 2 → mask `& ~0x12`; 3 → 0xFFFFFFFF; any other
    value leaves it. A message or section is written when `levelMask & level` is not 0 (S 00418250,
    S 00418b10).
- **Debugger output** `Debug_PrintfToDebugger(fmt, ...)` S 005c3b40 [known]: `_vsnprintf_s` of at most 1023
  characters into a 1024-byte stack buffer, then `OutputDebugStringA`; two callers,
  `S2CE::CResourceMgr::DumpDetailedResourceStats` S 004dccb0 and `S2CE::CVertexStream::Lock` S 004e5210. Three
  more functions call `OutputDebugStringA` directly: `Debug_OutputStdString` S 006e89d0 and the web view's
  S 005c7ba0, S 005c7f90 [known: scan of the decompiled image].
- **Assertions.** No assertion function of the game's own is named in the image [known: name index]; failed
  runtime checks surface as the C runtime's invalid-parameter handler, as a log line followed by a deliberate
  fault (e.g. the container checks, [formats-inventory.md](formats-inventory.md) §2.3) or as the crash report
  ([app-shell.md](app-shell.md) §3.12). The only text with `assert` in the image is Lua's (`assert`,
  `assertion failed!`, used by `luaB_assert` S 005cad30) [known: string search].
- **Log call sites carry their source position** [known] S 006e5600 and its 124 calling functions (309 call
  sites): before each `Log_Printf` the code calls a three-argument function with the source file (42 distinct
  strings such as `.\IO\File.cpp`, `.\GameFile.cpp`, `.\LobbyManager.cpp`), the function name (e.g.
  `NBase::gDecryptData`) and the line number (e.g. 0x1af). It stores them in three globals (S 0088e198,
  S 0088e19c, S 0088268c) that nothing reads [known: cross references]. This is the release form of the
  engine's log macro, not an assertion: nothing stops or faults there, and the fault of the container checks is
  separate code after the log call.

### 3.11 Localisation lookup (summary)

Full text: [formats-inventory.md](formats-inventory.md) §3.9, [ingame-ui.md](ingame-ui.md) §3,
[app-shell.md](app-shell.md) §3.6. [known] S 00496070, S 004966d0, S 004963a0, S 00496b80:

- one map `key → text` in the `ai::ui::Localization` singleton, language code at `+0x0c` (default `de`,
  S 00495fe0);
- files: encrypted containers requested as `[data]\language\<lang>\<file>` (S 004955a0; in the install they
  are in `data\game\language\de\`), read through `File_ReadAndDecrypt`; a file that cannot be read is skipped
  silently. 8-bit text, one `key<TAB>value` per line. Example, `ui.txt` of the German install: 1769 lines, CR
  LF line ends, every line two TAB-separated fields, e.g. `!1 Hour` → `1 Stunde` [known: data file];
- line ends [known] S 004966d0: if the text has CR but no LF every CR becomes LF; if it has both, every CR is
  removed; then the text is split at LF and empty lines are skipped;
- comment lines start with `//`, `;` or `#`;
- key = the text before the **first** TAB, value = the text after the **last** TAB (fields in between are
  dropped); a line without TAB has key = value = the whole line; a line with an empty key is skipped;
- the two-character sequence `\n` in a value becomes a line feed (S 004963a0);
- load order `briefings.txt`, `ui.txt`, `credits.txt`, `lobby_ui.txt`, `lobby_items.txt`; a later entry
  replaces an earlier one of the same key;
- `GetText(key)`: empty key → empty string; known key → its text; unknown key → **the key itself, which is
  also inserted into the map**. Keys are compared as exact byte strings (case-sensitive) [inferred: a
  `std::map` keyed by `std::string`]; most UI keys start with `!`.

### 3.12 File system layer (summary)

Full text: [formats-inventory.md](formats-inventory.md) §2.1, §2.2, §3.1; `../asset-formats.md` §1.

- Roots [known]: the game root (working directory), `data\game\` and `data\lobby\` below it, the virtual
  prefix `[data]`, the user folder `<My Documents>\SAdK\`, the cache folder `<Local AppData>\SAdK\`.
- Start-up index [known] S 006e3ca0, S 006ef440, S 006f10e0: one recursive scan of `data\` builds a map
  **lower-case file name (with extension, without folder) → list of directories**. It is never rebuilt.
- Resolution [known] S 006e3fd0, S 006ef8a0, tested in this order: an empty path stays empty; a path ending
  in `\` or `/` is looked up as a directory under `data\game\` and `data\lobby\`; a path containing `:` is used
  as it is; anything else is lower-cased, reduced to the part after its last `\` (after `/` → `\`) and looked
  up in the index. A name the index lacks resolves to the empty string. **The folders of the request are
  ignored** unless the name occurs in several directories; then the first candidate whose last folder name
  occurs in the request wins, and a bare ambiguous name fails ([inferred] for the several-directories case:
  the candidate picker was not read here; [formats-inventory.md](formats-inventory.md) §3.1).
- Reading [known] S 006e6d40, S 006e7770, S 006e6660: `NBase::gReadFileData` returns the whole file;
  `File_ReadAndDecrypt` passes it to `NBase::gDecryptData`, which has no plain-file branch: each failed check
  (magic `sadk`, key CRC, plaintext size, plaintext CRC) logs a line and then writes to address 0, a
  deliberate fault. Which reader a file type uses is fixed by its loader ([formats-inventory.md](formats-inventory.md)
  §3.2). There is no archive format: every asset is a loose file.
- The decrypt step is `NBase::gDecryptData` itself; the mod system redirects file opens and passes plain files
  through at that function (`../../mods/README.md`).

---

## 4. Update order

On program start, before `WinMain` runs [known: dynamic initialisers]:

1. the static section tags are constructed (name copied, CRC computed), the static random generators are seeded
   (§3.7), `SinTable1024` is filled (S 007c0070).

In `CApplicationEx::Initialize` S 004075d0 ([app-shell.md](app-shell.md) §3.3) [known]:

2. in this order: the log directory is set, the x87 control word is set, the file index is built (one scan of
   `data\`), `Timer_Init` and `Timer_Reset` run.

Per frame [known] ([app-shell.md](app-shell.md) §4):

3. `Timer_UpdateFrame` S 0057b810 is the first call after the "graphic device ready" test of
   `FrameTick_InGame` S 004018e0 (and is also called by `FrameTick_Menu` S 00401780); every consumer of the
   frame delta in that frame reads the same value.
4. `Fpu_SetDefaultControlWord` immediately before `NLogic::System::Update`, and only when a logic system
   exists S 004018e0. `Lobby::CLobby::Update` S 004fb460 and `nGame::System::HandleGameCommand` S 007845a0 set
   it again on their own.
5. The global `HiResTimer` is ticked by `S2CG::Scene::UpdateDetailFlagsAndTime` S 0067f6b0 (from
   `S2CG::Scene::Update`), and only when that function's real-time argument is set; on its first use there the
   timer is reset. With the argument clear the scene takes its time from the logic system (`accumulatedTime`,
   `frameDelta`) and the timer is not touched.

Per logic tick: nothing in this document runs by itself. The simulation generator advances only when a
simulation function draws from it ([logic-core.md](logic-core.md) §3.3).

Per net tick [known] S 004089c0, S 00784080: `NComm_Manager::SendEventUserChecksum` asks the game listener for
`ComputeChecksum`, one `CRCStream` pass over the simulation state, unless the manager's mode is 0 (then the
checksum is 0) ([logic-core.md](logic-core.md) §3.6). The same function also runs on network start-up and on
the reconnect paths (callers S 0040a9a0, S 004093a0, S 0040b700, S 0040e560).

On load [known] S 005273d0: `NLogic::System::PostLoad` calls `Timer_Reset` when the frame timer is initialised.

On every menu-system update (`nMenu::System::Update` S 005da500, `LobbyMenu::System::Update` S 0042a860)
[known] S 00496e60: when the language-changed flag is set, the text map is emptied and the five text files are
loaded again ([app-shell.md](app-shell.md) §3.6).

On an inbound lobby payload [known] S 00462760, S 0048fa50: one `BitStream` view; on the village and referee
connections one `LobbyMessage` over it, fields read in the handler's fixed order, then `FinishRead` (§3.2). The
game-slot connection drops the payload (§2.2).

---

## 5. Inputs and outputs

This layer sends and handles no network message of its own. It provides the encodings of:

| Traffic | Encoder | Reference |
|---|---|---|
| LobbyMessage bodies inside NETMSG `SendGameData` (74) / `SendGameDataBundle` (73): village, referee, minigames | the `LobbyMessage` bit packer (§3.2) | `../message-catalog.md`, `../village-and-character-protocol.md` |
| NComm peer-to-peer events and tick packages (TinCat module 0x27d9) | `NComm::MemoryStream` (§3.3) | `../NCOMM_GAME_PROTOCOL.md`, [game-commands.md](game-commands.md), [network-session.md](network-session.md) |
| LAN game records (`ai::network::BCGameInfo::Serialize` / `Deserialize` S 00419330 / S 004194a0) and the map transfer packets (`ai::net::S2TftpSession`, `S2TftpManager`, S 00426860, S 004274b0) | `NComm::MemoryStream` (§3.3) [known: callers of its two constructors] | [lan-and-transport.md](lan-and-transport.md) |
| the character data blocks of the lobby (`LobbyComm::IAvatarDataBlock::ReadFromBuffer` / `WriteToBuffer` S 00486120 / S 004861c0: a borrowed, non-growing stream over the block; a block shorter than 4 bytes is rejected) | `NComm::MemoryStream` (§3.3) [known] | [lobby-client-state.md](lobby-client-state.md), `../village-and-character-protocol.md` §1.4 |
| the lockstep checksum inside event 0x30009 | `NCore::CRCStream` + CRC-32 | [logic-core.md](logic-core.md) §3.6 |
| the match password digest | MD5 | [network-session.md](network-session.md) |
| NETMSG property bags | `tincat3.dll`, not this layer | `../message-catalog.md`, "Property-bag body (msgdefs field types)" |

Files [known: callers of each class's `Open`]:

| Stream | Files | Callers of `Open` |
|---|---|---|
| `FileStreamCrypt` S 007807f0 | saves and maps | `GameFile_Save` S 005aa260, `GameFile_LoadImpl` S 005aaed0, `GameFile_LoadMapInfoCached` S 005aa030 |
| `FileStream` S 0057d140 | `settings.cfg` and `data.cfg` (map states) in the user folder, the `<map>.info` cache, the map editor's copy and paste buffer | S 00578fe0, S 005792c0, S 00579430, S 005aa030, S 006015f0, S 00606050 |
| `DumpStream` S 00780bb0 | the desync dump `<name>.s2dump.txt` | `GameFile_WriteDesyncDump` S 005ab220 only |
| `NBase::File` S 006e6a30 | plain data files (47 callers) and the engine log `Logfile_0.txt` .. | S 006e5620 for the log |
| C++ `ofstream` | `comm.log` (NComm `Logger`, §3.10) | S 00417e20, S 00418250 |
| `LobbyComm::Logger` | `LobbyComm.log` ([app-shell.md](app-shell.md) §3.12) | S 004669e0 |

Operating system services used [known: imports called by the functions read; not a complete import list]:
`CreateFileA`, `ReadFile`, `WriteFile`, `GetFileSize`, `SetFilePointer`, `CloseHandle`, `FindFirstFileA`,
`FindNextFileA`, `FindClose`, `MoveFileA`, `DeleteFileA`, `GetUserNameA`, `QueryPerformanceCounter`,
`QueryPerformanceFrequency`, `GetTickCount` (the frame timer's fallback source, import slot S 007d31b4),
`GetLocalTime`, `MultiByteToWideChar`, `WideCharToMultiByte`, `UuidCreate` (RPCRT4), `OutputDebugStringA`.

---

## 6. Data-driven parameters

Almost nothing here is data-driven; the constants are compiled in.

| Parameter | Source | Example |
|---|---|---|
| language code | `data\game\scripts\menu.cfg`: `menu.setLanguage("de")` [known: data file] | `de` ([app-shell.md](app-shell.md) §3.6) |
| text tables | `data\game\language\<lang>\{briefings,ui,credits,lobby_ui,lobby_items}.txt` [known] S 00496b80; the folder also holds `dialogs.txt` and `info.txt`, which this loader does not name | `lobby_ui.txt`: `!ABORT_BUTTON` → `Abbrechen`; `briefings.txt`: keys `B10_0_1` and `B10_0_1_title` [known: data files] ([formats-inventory.md](formats-inventory.md) §3.9) |
| file index | every file below `data\` | 4453 files in the install, 55 lower-case file names occur more than once [known: listing of the install] ([formats-inventory.md](formats-inventory.md) §3.1) |
| log level | command line: `-log_disabled` / `-log_error` / `-log_warn` / `-log_info` set `g_LogLevel` S 00882690 to 0 / 1 / 2 / 3 [known] S 00403ac0; compiled value 1 [known: data bytes] | it gates the engine log and sets the level mask of `comm.log` (§3.10); [app-shell.md](app-shell.md) §3.2, §3.12 |
| ANSI code page | the Windows system setting (`CP_ACP`, §3.6) | 1252 on a German system [inferred] |

Compiled-in constants of this layer [known at the addresses given in §3]: generator multiplier 16807, modulus
2^31 − 1, default seed 0x5432ACE0, the 32-entry seed bit order; unit-float divisor 1,000,001 / 1,000,000;
`MemoryStream` sizes of `FileStreamCrypt` (0x400, 0x80); PhysX buffer slack 0x1000; fixed frame step 0.025 s
(unused); array growth factor 1.5 with minimum 8; `NBase::File::ReadString` buffer 260 bytes; log buffer 4096
bytes; debugger print buffer 1024 bytes (at most 1023 characters); NComm `Logger` defaults (indent step 4, no
size limit, all levels; §3.10).

---

## 7. Save and load

| State | Persisted | Where |
|---|---|---|
| simulation generator | yes: tag `Logic Random` [0], the initialised flag S 00889b00 through the stream's bool slot, then the generator's 8 raw bytes (`state`, `seed`) [known] S 005389c0, S 00538a20 | [logic-core.md](logic-core.md) §7 |
| `NLogic::Unique` counter | yes | inside `LogicSystem`, [save-format.md](save-format.md) §2.7 |
| `NCore::Unique` ids of player messages | yes, per message: tag `uniqueId` [0], then the 64-bit id [known] S 00780cb0, S 005c0300 | [players-victory.md](players-victory.md) §7 |
| `NCore::Unique` counter S 00897ce8 | no; a load of a current save does not touch it (below) | |
| map `UUID` | yes: tag `Core UUID` [0], bool `bValid`, 16 bytes [known] S 0057ce20, S 0057ce60. `MapInfo::Store` S 00529db0 and `MapInfo::Load` S 0052bd40 also call `Generate`, i.e. make a fresh UUID where none is stored | `MapInfo`, [save-format.md](save-format.md) §3 |
| frame timer | no; `Timer_Reset` at the end of a load (§4) | |
| `HiResTimer`, all other generators | no; left running | |
| text tables, file index | no | rebuilt from the install |

The formats this layer defines for those records are §3.3 (strings), §3.4 (section tag) and §2.6 (ids).

**Message ids across a load** [known] S 005c0390, S 005c2520, S 00780ce0, vftable S 007eb734:
`NPlayer::Messages::Load` clears the list and builds each message with the default constructor (id −1), then
`NPlayer::Message::Load` reads the section version of tag `Message` (current version 2, S 007c6f10):

- version ≥ 2: the id is read by the `NCore::Unique` object's own slot 2 (`Deserialize`: skip the tag, read 8
  bytes). `g_Unique_NextId` is neither read nor written;
- version < 2: an `NLogic::Unique` record is read and its id goes through `ctor_FromId`, the only path that
  raises the counter (to that id, §2.6).

A message with `msgType` 8 is read and then not added to the list.

Consequence [inferred]: the counter is 0 at program start and a load of a current save leaves it alone, so the
messages created after the load take ids from the counter's own sequence, which can repeat ids of loaded
messages. `NPlayer::Messages::FindById` S 005c1890 and `RemoveById` S 005c1ad0 walk the list from the front and
act on the **first** message whose id matches [known]; both are called only by `nMenu::Messages::Update`
S 005f86a0. With a repeated id the HUD therefore finds, and removes, the earlier list entry (the loaded
message) when it means the later one. A remake avoids this by storing the counter or by raising it past every
loaded id.

---

## 8. Determinism notes

Parts of this layer that touch simulation state:

- **The simulation generator.** One instance; its step and seeding (§3.7) must match bit for bit, including the
  missing rejection step in every `% n` reduction.
- **The lockstep checksum.** CRC-32 over the bytes the `CRCStream` receives, with its quirks (1-byte bool, 4
  bytes of a string's buffer, no tags; [logic-core.md](logic-core.md) §3.6). It must match only among peers of
  the same implementation, but a remake that wants to stay comparable with the original must reproduce it.
- **Float arithmetic.** Single precision with the x87 control word of §3.8.
- **Id order.** Containers keyed by `NLogic::Unique` iterate in id order and ids come from one counter
  ([logic-core.md](logic-core.md) §8). `std::map` iteration is key order; the engine arrays keep insertion
  order except where `RemoveAtSwapLast` or a handle pool is used: there the order depends on the removal
  history, which is deterministic as long as the removals are.
- **Save streams.** The byte layout must match exactly to read original saves and maps.

Parts that are presentation or front end only, and why:

- `NCore::BitStream` and the `LobbyMessage` packer: lobby traffic; no match state travels through them
  [known: their only users are the lobby connections].
- Every generator other than `g_LogicRandom` and the chest generator: their callers are renderer, particle,
  3D-lobby and file-crypt functions (§3.7). `SwarmMgr` seeds from a memory address [known] S 0069ab00, which
  already differs between two machines in the original. Still open (§10): whether the users of the five static
  instances write anything the simulation reads, and whether the terrain generator can run at all (its draws
  would change terrain heights, but its two entry points have no direct caller).
- `HiResTimer`, the fast square root and the cosine and sine tables: effect and UI callers only (§3.8).
- The frame timer is wall-clock time. It reaches the simulation in two documented places: the logic tick
  accumulator ([logic-core.md](logic-core.md) §3.1) and player message lifetimes
  ([players-victory.md](players-victory.md) §8).
- C runtime `rand` is one process-wide sequence that no peer shares. It is seeded in three places [known: every
  caller of `srand`]: on entering the village (S 0046f670, frame-timer milliseconds), in the host's random slot
  and team assignment (S 00413930, `time(NULL)`) and by Lua's `math.randomseed` S 005ca350. Its users are not
  lobby code only (list in §3.7): the host's slot and team assignment draws from it, which is safe because the
  result is sent to the peers; Lua's `math.random` S 005ca190 draws from it, so a map script that feeds
  `math.random` into simulation state differs between peers ([lua-runtime.md](lua-runtime.md),
  [logic-core.md](logic-core.md) §3.3); the cinematic camera, `S2CG::FarmBuilding::ctor`, audio, UI and the map
  editor tools are presentation or tooling by their names [inferred].
- Text encoding, localisation, logging, the file index: no simulation state. Text conversion can change a
  **player name** between peers with different code pages, which affects display only [inferred].

---

## 9. Notes for a Godot reimplementation

The remake's simulation is written in C# (Godot .NET) as a plain library without Godot nodes; presentation, UI
and tools use Godot. Maps onto a platform feature:

- byte streams → `BinaryReader` / `BinaryWriter` (little-endian, as the original); write the 4-byte bool, the
  `u32`-length string (raw bytes, no terminator) and the 12-byte section tag by hand;
- CRC-32 → `System.IO.Hashing.Crc32` or a 256-entry table; MD5 → `System.Security.Cryptography.MD5`;
- strings → `string` (Unicode). Decode Windows-1252 at the converter; encode back to 8-bit only where an
  original format or peer needs it;
- UUID → 16 random bytes kept in the stored order; the original uses `UuidCreate`;
- containers → `List<T>`, arrays, `SortedDictionary` / `SortedList`. The enumeration order of a
  `Dictionary<TKey, TValue>` is not defined (in practice insertion order until the first removal): simulation
  code must not iterate one. Where the original iterates a `std::map`, use a sorted container;
- vectors, quaternions, transforms → `Vector3`, `Quaternion`, `Transform3D` for presentation. The originals
  are left-handed, row-vector, single precision; convert at the asset boundary
  ([rendering.md](rendering.md), [animation-models.md](animation-models.md));
- timers → `_process(delta)`, `Time.get_ticks_msec()`; logging → `print` / a log file; localisation →
  `TranslationServer` with the original keys (keep the "missing key shows the key" behaviour);
- file index → a dictionary from lower-case file name to path, built once by the converter over the player's
  install, with the duplicate rule of §3.12.

Must be reproduced exactly:

- the generator of §3.7 as 32-bit unsigned integer arithmetic (`uint` in C#; or compute
  `state * 16807 % 0x7FFFFFFF` in 64-bit integers, which is equal);
- `SetSeed` including its table, for the chest generator and the container key stream;
- the stream encodings of [save-format.md](save-format.md) §2.2 and the section tag of §3.4;
- the `CRCStream` rules, if checksums are to be compared with original peers or dumps;
- the `LobbyMessage` bit packing of §3.2, UTF-8 strings with an 8-bit length, if the remake talks to a lobby
  server that serves original clients;
- single-precision float behaviour wherever a simulation rule uses floats: C# `float` is IEEE single precision
  with round-to-nearest, which matches the x87 control word of §3.8 except where the x87 keeps its wider
  exponent range (overflow, underflow, denormals). Not through GDScript, whose `float` is always 64-bit.
  `Math` / `MathF` functions such as `Sin`, `Cos`, `Atan2` and `Pow` depend on the platform's math library
  (`Sqrt` is correctly rounded and safe): the simulation calls its own implementations ([logic-core.md](logic-core.md) §9).

Should not be reproduced: the unchecked buffers (`ReadString` into 0x800 or 260 bytes, `MemoryStream::Write`
on a fixed buffer, `ReadBits` past the end, `WriteBytes` / `ReadBytes` without limits, the faulting container
reader). A converter or server must bound every length it reads.

A server has to provide: LobbyMessage bodies packed as in §3.2; strings as UTF-8 of at most 255 bytes; zero
padding to the byte boundary; and, only when it sets type word bit 15, 32 more bits after the last field (the
schema checksum; the client reads and discards them, S 0048f530).

A converter has to provide: decrypted and decoded text (Windows-1252 → UTF-8), the file-name index, and the
decoded saves and maps if original files are to be loadable.

---

## 10. Open questions

| # | Question | What would settle it |
|---|---|---|
| 3 | Answered (§3.6): the C++ runtime's locale objects restore the locale they found (`std::_Locinfo` S 006f1938 / S 006f17d9), so the file index and the name keys are lower-cased under "C" and keep an upper-case umlaut | static: the three callers of `_setlocale` S 006f9161 |
| 4 | Answered (§3.7): no. The users of the static generators S 00889860, S 0088d47c, S 0088d4ec, S 0088e118, S 0088e120 are called only from render and lobby code, reach the simulation only through the reader `NMap::Exploration::IsExplored` S 00542b10, write no simulation global and never touch `g_LogicRandom`; no simulation function calls render, animation or lobby code directly [known: call trees and caller lists; the render trees' indirect calls are on render objects, inferred from their types] | — |
| 5 | Answered (§3.7): `S2CG::CMapRenderer::RunTerrainGenerator` S 00688540 and `RunTerrainGeneratorToBuffer` S 00688590 are never called [known]. Their only references are slots `+0x04` / `+0x08` of the `CMapRenderer` vftable S 007f9504 (a byte search of the image finds the two addresses nowhere else); that vftable is installed only by the constructor S 006890f0 and the destructor; the one renderer object lives in `g_pMapRenderer` S 0088cf64 (written only by `CreateInstance` S 00689450, whose return value `Scene::Init` S 006824c0 discards; read only by `GetInstance` S 00688200, `HasInstance` and `DestroyInstance`), none of the 140 call sites of `GetInstance` stores the result outside the stack in the instructions behind the call, and none of the 108 functions holding them makes any indirect call through `+0x04` or `+0x08`; the constructor hands `this` only to `SelectionMarker`, whose one indirect call goes to a render building. Generator-dependent heights do not reach the simulation | — |
| 7 | Bodies of `PerspectiveFovLH`, `OrthoLH`, `LookAtLH`, `Slerp`, `Matrix44` inverse: do they equal the Direct3D reference formulas element for element? | static read of S 006e97e0, S 006e8e10, S 006e9b70, S 006e8830, S 006e9200 |
| 11 | Answered (§3.6): `Str_Utf8ToAnsi` maps a character outside the ANSI code page to a best-fit letter where one exists (`Ő` → `O`, `ł` → `l`), else to `?` (`字`) [live, 2026-10-14] | — |

---

## 11. Function reference

| Address | Name | Role |
|---|---|---|
| 0048f150 / 0057d460 / 00462630 / 0057d450 | `NCore::ByteBuffer::ctor` / `dtor` / `AssignShared` / `GetDataAt` | owned or borrowed byte buffer |
| 00462760 | `LobbyComm::System::DispatchInboundToConnection` | the only place a `BitStream` is built (the vftable's only other reference is the destructor) |
| 0057df40 / 0057da40 | `Bits_WriteUInt8` / `Bits_ReadUInt8` | bit primitive, 8-bit |
| 0057e0b0 / 0057db70 | `Bits_WriteUInt16` / `Bits_ReadUInt16` | bit primitive, 16-bit |
| 0057e220 / 0057dcb0 | `Bits_WriteUInt32` / `Bits_ReadUInt32` | bit primitive, 32-bit |
| 0057d8d0 / 0057ddf0 | `Bits_WriteUInt64` / `Bits_ReadUInt64` | bit primitive, 64-bit |
| 0057d810..0057d8a0 | `Bytes_Swap64/16/32/8` | byte reversal used by the primitive |
| 0057d490 | `Math_BitLength64` | field width of a range-coded value |
| 0057e400..0057e490 | `BitStream::PeekUInt8/16/32/64` | read without moving the cursor |
| 0057e4c0..0057e880 | `BitStream::Write/ReadUInt8..64`, `WriteInt8..64` | typed fields |
| 0057f3a0 / 0057f430 / 0057f4d0 / 0057f570 | `BitStream::ReadInt8/16/32/64` | sign-and-magnitude readers |
| 0057e910..0057eaf0 | `BitStream::Write/ReadUIntInRange`, `Write/ReadIntInRange` | range-coded fields |
| 0057eb90 / 0057ebd0 | `BitStream::WriteBit` / `ReadBit` | one bit |
| 0057ec10 / 0057eca0 / 0057f100 | `BitStream::WriteVarUInt` / `ReadVarUInt` / `PeekVarUInt` | base-128 integers |
| 0057ed10 / 0057ee80 / 0057efd0 / 0057f000 | `BitStream::WriteCString` / `ReadCString` / `WriteStdString` / `ReadStdString` | strings |
| 0057d780 / 0057d7d0 | `BitStream::WriteBytes` / `ReadBytes` | byte-aligned blocks |
| 0057e380 / 0057d730 | `BitStream::AlignWritePos` / `AlignReadPos` | alignment |
| 0057f140..0057f300 | `BitStream::WriteFloat`, `Write/ReadFloat3`, `Write/ReadFloat4` | floats |
| 0057d4c0 / 0057d4d0 | `BitStream::dtor` / `GetBytePos` | destructor; `bitPos / 8` |
| 0057d4e0..0057d720 | `BitStream::SeekByte`, `SeekBit`, `SetLimitsBytes/Bits`, `GetLimitsBytes/Bits`, the limit and remaining-size getters, `SetWritable`, `ClearWritable` | cursor and limits |
| 0048ef70 / 0048f0d0 | `LobbyMessage::WriteBits` / `ReadBits` | the lobby bit packer |
| 0048efe0 / 0048f050 | `LobbyMessage::WriteBits64` / `ReadBits64` | 64-bit fields |
| 0048f4c0 / 0048f530 | `LobbyMessage::Finalize` / `FinishRead` | padding, schema checksum |
| 0048fe20 / 004900a0 | `LobbyMessage::WriteString` / `ReadString` | UTF-8 strings, 8-bit length |
| 0048ef10 | `LobbyMessage_HashFieldName` | CRC-32 of a field name |
| 0048fa50 / 0048fb00 | `LobbyMessage::InitFromWire` / `ctor` | message over a received body / for sending |
| 00581800 / 00581790 | `NCore::Stream::ctor` / `dtor` | stream base |
| 0057d140 / 0057ced0 / 0057cf00 / 0057cf30 | `NCore::FileStream::Open` / `Close` / `Read` / `Write` | plain file stream |
| 0057cfc0 / 0057cf80 / 007804f0 | `FileStream::WriteSectionHeader` / `ReadSectionHeader`, `FileStreamCrypt::BeginReadSection` | section tag record: write; read and return the version; read and discard |
| 007807f0 / 007805d0 | `NCore::FileStreamCrypt::Open` / `Close` | encrypted file stream |
| 0057d270..0057d430 | `NCore::CRCStream::*` | checksum stream |
| 00780960..00780bb0 | `NCore::DumpStream::*` | text dump stream |
| 00412120 / 00412160 | `NComm::MemoryStream::ctor` / `ctor_Buffer` | growing stream / stream over a given buffer (borrowed or copied) |
| 004122f0 / 00412360 / 00412240 | `NComm::MemoryStream::Write` / `Read` / `Seek` | raw bytes |
| 004123a0 / 00412400 | `NComm::MemoryStream::WriteString` / `ReadString` | `u16`-length strings |
| 006e6a30 / 006e6530 / 006e6570 | `NBase::File::Open` / `Read` / `Write` | plain file |
| 006e65d0 / 006e6960 | `NBase::File::WriteString` / `ReadString` | `u32`-length strings |
| 006e6d40 / 006e7770 / 006e6660 | `NBase::gReadFileData` / `File_ReadAndDecrypt` / `NBase::gDecryptData` | whole-file read, container |
| 00510f60 / 00511080 | `MemoryWriteBuffer::ctor` / `storeBuffer` | PhysX write buffer |
| 00757ac0 / 00757b80 | `NXU::MemoryReadBuffer::ctor` / `readBuffer` | PhysX read buffer |
| 005816e0 | `ai::logging::LogCategory::ctor` | section tag object: name, version, name CRC |
| 00663dd0 | `NCore::IStoreable::dtor` | base destructor of the store interface |
| 00780c00 / 00780c20 / 00780c60 / 00780c80 | `NCore::Unique::ctor` / `ctor_FromId` / `AssignNewId` / `Equals` | message ids; `ctor_FromId` is reached only for `Message` sections older than version 2 |
| 005c0390 / 005c2520 / 005c1890 / 005c1ad0 | `NPlayer::Message::Load`, `NPlayer::Messages::Load` / `FindById` / `RemoveById` | how message ids are loaded and looked up (§7) |
| 00780cb0 / 00780ce0 | `NCore::Unique::Serialize` / `Deserialize` | tag `uniqueId` + 64-bit id |
| 0057cde0 / 0057ce00 / 0057ce20 / 0057ce60 / 005a9d00 | `NCore::UUID::ctor` / `Generate` / `Serialize` / `Deserialize` / `Equals` | map identity |
| 005389c0 / 00538a20 / 00538a00 / 00538980 | `LogicRandom_Save` / `Load` / `Checksum` / `SetUp` | save record, checksum input and restart of the simulation generator |
| 00762320 / 00762350 / 00762400 / 007623e0 | `Crc32Acc_ctor` / `Update` / `UpdateDword` / `Reset` | CRC accumulator |
| 00762380 / 007623b0 | `Crc32Acc::Write` / `Read` | accumulator to and from a stream |
| 007627c0 / 00762520 | `crc32` / `crc32_little` | zlib CRC-32 |
| 006ee680 | `FileCrypt_Crc32OfKey` | CRC of the 16-byte file key |
| 0041f140 / 0041f1d0 / 0041f180 | `MD5Hasher_Construct` / `UpdateString` / `GetDigest` | password digest |
| 00428c40 / 00428c70 / 00428d40 | `MD5Init` / `MD5Update` / `MD5Final` | MD5 |
| 00487530 / 00487620 | `Str_AnsiToUtf8` / `Str_Utf8ToAnsi` | code page conversion |
| 00487350 / 00487b20 | `Str_ToLower` / `Str_Tokenize` | string helpers |
| 006ec250 / 006ec0b0 / 006ec200 | `TextTokenizer::ctor` / `GetToken`, `TextLineBuffer::ctor` | `.fnt` text parsing |
| 004d9b40 / 006814a0 / 006c25f0 | `Array16::SetCapacity` / `PtrArray::SetBit` / `RemoveAtSwapLast` | engine arrays |
| 004dedc0 / 004dee50 / 0076b180 | `HandlePool16::Alloc` / `FreeActive` / `HandlePool_Free` | handle pools |
| 006ec350 | `Rng_ParkMillerNext` | generator step |
| 006ec2a0 / 006ec4a0 / 006ec280 | `RandomGenerator::SetSeed` / `ctor_WithSeed` / `RestartFromSeed` | seeding |
| 006ec3a0 / 006ec410 | `RandomGenerator::NextInRange` / `Math_Random_NextUnitFloat` | range and unit float |
| 004a8290 / 004a0990 | `Matrix44::TransformPoint` / `Multiply` | matrix convention |
| 004ef9a0 / 004efa20 / 004a8300 / 006e90c0 | `Matrix44::SetRotationX` / `Y` / `Z` / `RotationYawPitchRoll` | rotations |
| 006e83c0 / 006e8700 / 006e8a80 / 004f3620 | `Quaternion::FromAxisAngle` / `FromEuler`, `Matrix44::FromQuaternion`, `Quaternion::RotateVec3` | quaternions |
| 006e97e0 / 006e8e10 / 006e9b70 / 006e8830 / 006e9200 | `Matrix44::PerspectiveFovLH` / `OrthoLH` / `LookAtLH`, `Quaternion::Slerp`, `Matrix44_InvertInPlace` | named only; bodies not read (§10) |
| 006b0e60 / 006b24f0 / 006b25a0 / 006b1dd0 | `ai::terrain::TerrainGenerator::ctor` / `Run` / `RunToBuffer` / `ApplyFaultLines` | noise terrain; the only user of its generator |
| 006eece0 / 006eedc0 | `Math_YawFromDirection` / `Math_YawBetweenPoints` | yaw against (0, 0, 1) |
| 006e8fa0 | `RotationAxis` | Rodrigues matrix, applied to row vectors |
| 006e8a20 / 006e8a50 / 004ccb90 / 006e89f0 | `Math_FastSqrt` / `Math_FastCosLut` / `SinTable1024::Init` / `Math_FloatToIntRound` | presentation approximations (effects; `Math_FastSqrt` also the sea-route strip and the ship pick) |
| 0057b9b0 | `Fpu_SetDefaultControlWord` | x87 control word: exceptions masked, 24-bit precision |
| 0057b790 / 0057b760 / 0057b990 / 0057b810 | `Timer_Init` / `Timer_QpcMilliseconds` / `Timer_Reset` / `Timer_UpdateFrame` | frame timer |
| 0057b840..0057b8e0 | `Timer_GetCurrentMs`, `GetFrameDeltaSeconds`, `GetFrameDeltaMs`, `GetTotalSeconds`, `GetElapsed*` | timer readers |
| 0057b910 / 004f4d10 | `Timer_SyncElapsedToServerTick16` / `Net_ExpandWireTick16` | lobby clock |
| 006e9de0 / 006e9d60 / 006e9d40 / 006e9db0 / 006e9cf0 | `Timer_GetGlobal` / `Timer_Tick` / `Timer_Reset` / `Timer_CreateStarted` / `Timer_GetElapsedAndRestart` | `HiResTimer` (this `Timer_Reset` shares its name with the frame timer's S 0057b990) |
| 0067f6b0 | `S2CG::Scene::UpdateDetailFlagsAndTime` | the only caller of the `HiResTimer` tick and reset |
| 006e5950 / 006e5620 | `Log_Printf` / `LogFile_ctor` | engine log |
| 006e5600 | `Globals_SetThreeDwords` (the map's name) | stores file, function and line of a log call site; never read |
| 00403ac0 | `CApplicationEx::ParseCommandLine` | the only writer of `g_LogLevel` |
| 00417e20 / 00418250 / 00418b10 / 00418c40 | `Logger::Open` / `LogMessage` / `EnterSection` / `LeaveSection` | NComm log |
| 004165b0 / 004176a0 / 00418600 | `Logger::RotateIfTooLarge` / `FormatLinePrefix` / `LogHexDump` | size check (deletes the file), line prefix, hex dump |
| 007be6f0 / 0040a530 | static initialiser of the NComm `Logger` / `NComm_Manager::ctor` | defaults; `comm.log` path, open, level mask |
| 0040a410 | `ai::ncomm::LogScope::ctor` | scoped log section (level 4) |
| 005c3b40 | `Debug_PrintfToDebugger` | `OutputDebugStringA` |
| 00496070 / 004966d0 / 004963a0 / 00496b80 | `Localization::GetText` / `LoadTextFile` / `SetText` / `LoadAllTextFiles` | text lookup |
| 006e3ca0 / 006e3fd0 / 006ef8a0 | `FileScanHolder::ScanDirectory` / `ResolvePath`, `FileScan::ResolvePath` | file index |
