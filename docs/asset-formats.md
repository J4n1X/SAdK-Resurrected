# Asset formats: encrypted containers and KEX

Two formats cover the game's data files. Both were read from the client's own loaders (Ghidra,
`sadk_noav.exe`) and are implemented by `tools/sadk_crypt.py` and `tools/kex.py`.

| Kind | Files | Recognised by |
|---|---|---|
| Encrypted container | 1,742 files, 530 MB: `.dds` (1,050), `.lua` (355), `.tga` (125), `.xml` (110), `.fx` (59), `.s2m` (33), `.txt`, `.png`, `.inc`, `.cfg` | first 8 bytes `12 18 09 06 "sadk"` — the file extension says nothing |
| KEX scene | 1,639 `.KEX` files, 231 MB | not encrypted; binary scene (meshes, skeletons, animations) |
| Plain | `.ogg`, `.wav`, `.bmp`, `.bin`, `.pfx`, `.npc`, `.fnt`, `.ini`, … | — |

Counts are for the reference install (`~/sadk_game`).

## 1. Encrypted container

The game decrypts these on load (`NBase::gDecryptData` S 006e6660). `[known]` for everything below; live
check: all 1,742 files decrypt and pass all three header checks (2026-10-07).

| Off | Type | Field |
|---|---|---|
| 0x00 | u32 | version `0x06091812` (`Crypto_GetVersionConst` S 006ee670) |
| 0x04 | char[4] | `"sadk"` (`Crypto_GetMagicSadk` S 006ee660) |
| 0x08 | u32 | CRC-32 (zlib) of the plaintext |
| 0x0c | u32 | CRC-32 of the 16-byte file key |
| 0x10 | u32 | plaintext size |
| 0x14 | … | scrambled, LZSS-compressed payload |

**Key** (`FileCrypt_DeriveFileKey` S 006eeac0): start from the base key `bdc28cbd f84b6730 f91b9bb4 f42e82f6`
(little-endian dwords, `Crypto_InitKey128` S 006ee5d0). Unless the file name ends in `.s2m` or `.aav`, XOR its
16 bytes with the low bytes of the first 16 outputs of a Park–Miller generator seeded with CRC-32 of the
**lower-case file name without folders**. So a file only decrypts under its own name (maps excepted).

**Generator** (`RandomGenerator::SetSeed` S 006ec2a0, `Rng_ParkMillerNext` S 006ec350): minimal-standard LCG
(×16807 mod 2³¹−1). The seed is masked to 31 bits and "bit-balanced": with fewer than 8 set bits, the first
`8 − n` bits of the order table at 007fd528 are set; with more than 24, the first `32 − n` are cleared. Table:
`12 23 10 25 8 27 6 29 4 30 1 22 9 13 21 0 17 26 5 15 18 28 11 2 14 3 24 7 19 16 20 31`. Seed 0 becomes state 1.

**Scramble** (`FileCrypt_XorScramble` S 006ee6b0), symmetric, applied to the payload; generator seeded with
CRC-32 of the key:
1. keystream length `(r & 0x7f) + 0x80`, then that many bytes `r & 0xff`; XOR the payload with it, repeating;
2. table length `(r & 0xf) + 0x11` and its bytes; start `r % size`, step `(r & 0x1fff) + 0x2000`; at each
   position `p`: `payload[p] ^= table[(key[p % 16] ^ p) % tableLen]`.

**Compression** (`Lzss_Decode` S 007630a0): Okumura LZSS. 1,024-byte ring filled with spaces, write position
`0x3f0`; flag byte per 8 items, least-significant bit first, 1 = literal byte; a match is two bytes
`[pos & 0xff][(pos >> 4) & 0xf0 | (len − 3)]`, an absolute ring position and a length of 3–18.

The game checks the key CRC, the size and the data CRC, and deliberately crashes on a mismatch.

## 2. KEX scene

A binary scene exported from 3ds Max ("KScene"). The engine loads it wherever the data names a Granny `.gr2`
file: `S2CE::CMesh::Load` S 0076e0d0 and `S2CE::CAnimatedObject::Load` S 0076b4a0 rewrite `.gr2` to `.KEX`.
Meshes are cached as `.mshraw` under `%LOCALAPPDATA%` (`CMesh::IsPackedCacheUpToDate` S 0076cbe0). `[known]`;
live check: all 1,639 files parse to exactly their last byte (2026-10-07).

All values little-endian. `str` = `u32 length` + bytes (no terminator, `KScene_ReadLenPrefixedString` S 0072df40).

**File** (`KFile::Load` S 0072b820)
```
str  name                      e.g. "Terrain.max" or the model name
f32  axisX[3], axisY[3], axisZ[3], origin[3]   source coordinate system
f32  unitScale
u8   meshCount,     then meshCount x Mesh
u8   skeletonCount, then skeletonCount x Skeleton
u8   animationCount, then animationCount x Animation
```

**Mesh** (`KMesh::Load` S 0072c880)
```
str  name, name2
u32  numIndices, numVertices, numStreams, numBoneNames, numMaterials
u32  indices[numIndices]                 triangle list
numStreams x { u8 type; u32 byteSize; u8 data[byteSize] }
str  boneNames[numBoneNames]             skinned meshes
numMaterials x Material
```

Stream types, from their sizes across all 5,332 meshes `[inferred]` (the renderer's vertex-declaration mapping
is not yet read):

| Type | Bytes/vertex | Meaning |
|---|---|---|
| 0 | 12 | position (vec3) — every mesh |
| 1 | 12 | normal (vec3) — every mesh |
| 2 | 12 | rare (1 mesh); tangent? |
| 3 | 4 | vertex colour (RGBA bytes) |
| 4, 5, 6, 7 | 8 | texture coordinate sets 1–4 (vec2) |
| 12 | 16 | bone weights (4 × f32) — only with bone names, always with 13 |
| 13 | 4 | bone indices (4 × u8) |

**Material** (`KMaterialDesc::Load` S 007303a0)
```
str  name, name2
u32  a, b                 a is 0 in all files; b varies (0, 10, 12, 18, 20, 24) [TODO]
u32  count, then count x { str usage; str textureFile }
```
Usages are 3ds Max slots: `DiffuseColor` (7,006), `Opacity`, `Self-Illumination`, `SpecularColor`,
`SpecularLevel`, `Glossiness`, `Bump`, `Reflection`.

**Skeleton** (`KSkeleton::Load` S 0072d290)
```
str  name, name2
u32  boneCount, then per bone:
  str  name
  BoneKey                 local transform
  f32  matrix[16]
  i32  parentIndex        -1 = root
```
**BoneKey** (`KBoneKey_Read` S 0072f1d0): `u32 flags`; bit 0 → vec3 position; bit 1 → quaternion (x, y, z, w);
bit 2 → 3×3 scale matrix.

**Animation** (`KAnimation::Load` S 0072dcf0)
```
str  name, name2
f32  length               seconds
i32  trackCount, keyCount  every track has keyCount evenly spaced keys
per track:
  str  boneName
  u8   hasPosition  (1 -> keyCount x vec3)
  u8   hasRotation  (1 -> keyCount x quat)
  u8   hasScale     (1 -> keyCount x mat3)
```
The loader can bake the scale into the positions (`stripScale`) and drop it.

**Contents of the reference install:** 933 mesh-only, 150 mesh + skeleton (skinned models), 38 skeleton-only,
494 animation-only, 22 mesh + animation (one also with a skeleton), 2 empty.

## Tools

```
python3 tools/sadk_crypt.py decrypt <game>/data <out>    every encrypted file, verified, same folder layout
python3 tools/sadk_crypt.py file <file> [<out>]
python3 tools/kex.py check <dir>                          parse all .KEX, report any that do not end exactly
python3 tools/kex.py info <file.KEX>                      structure as JSON
python3 tools/kex.py split <dir> <out>                    per KEX: scene.json + indices, streams, tracks
```
