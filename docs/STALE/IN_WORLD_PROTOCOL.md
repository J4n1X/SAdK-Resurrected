> # ⚠️ CORRECTION — this doc's render-gate model is REFUTED
> The headline claim that **msg 1006 WorldLoginAck (`code==0xDEADBEEF`) is THE loading-screen
> render gate** is **wrong**. On the clean magazine build the 3D world **renders on `SetState(9)`
> from msg 1000 alone** — no 1006 needed (the client never even sent a PingCode in the live test).
> The 1006 / observer-fan-out "wall" and the "1004/1001 observer AV on Win10/11" were **no-CD-build
> artifacts**. All addresses below (`0x46e8b0`, `0x46f470`, …) are **pre-magazine-build** VAs. The
> §3 tincat3 serialization rules + the `SendGameData(74)` envelope are still accurate; the rest is a
> historical record.

# SADK World-Entry Spec: From Loading Screen to Rendered 3D World

*Produced s35 by a 30-agent RE workflow (decompiled every village/world handler + the loading gate +
state machine + the tincat3 PropertyDataConverter, then synthesized). Addresses are `SADK.exe` @ base
`0x400000` unless prefixed `tincat3!`.*

> ⚠️ **CORRECTION (s35 independent review — overrides §2/§3 for msg 1006 & Pong):** the synthesis wrongly
> classified `1006`'s `"code"` (and the Pong `"PongCode"`) as a **32-byte MEMBLOCK**. They are **FIXED u32
> scalars = 4 raw bytes, NO length prefix.** Proof: the tincat3 PropertyDataConverter (ser 0x100112B0)
> emits the 4-byte length prefix ONLY for types ∈ {MEMBLOCK=1,STRING=2,WSTRING=3}; the live capture shows
> the client's own `"code"=0xAFFEDEAD` is exactly 4 wire bytes. `HandleWorldLoginAck`'s `ReadMemBlock(&dst,
> 0x20)` — the `0x20` is the DEST scratch-buffer size, **not** a wire length; the gate compares only the
> first dword to `0xDEADBEEF`. So `world_login_ack_body()` / `pong_body()` = `struct.pack("<I", value)`
> (4 bytes). The EnterWorld(1000) MEMBLOCK fields (ServerPerm/Count/Zone/ID) ARE genuine length-prefixed
> MEMBLOCKs — those were already correct. CAVEAT: the render chain `FUN_0047e94d→0x485820` could NOT be
> corroborated from HandleWorldLoginAck; its real continuation is the UC-predicate finalize @`0x47e920`
> (the likely next wall if the loading screen doesn't dismiss even with the correct gate value).

---

## 1. THE LOADING-SCREEN GATE

**Definitive condition:** the loading screen is dismissed when **`VillageServerConnection::HandleWorldLoginAck`
@ `0x46e8b0` (inbound msg `1006`/`0x3EE`) reads property `"code"` whose first DWORD == `0xDEADBEEF`**,
which sets `loginAckReceived` (`this+0x224`) = 1 and **fires the world-session kick + render/UI transition**.

`HandleWorldLoginAck` is the *only* function in the village connection that reaches the render-transition
trampoline. On `code==0xDEADBEEF` → `this+0x224=1`, then per UC-conn predicate `uc->vtable[+0x2C]`:
- **true branch:** `FUN_00451140(uc+7)` + `FUN_0047e920(uc)` → `FUN_0042da15` → **`FUN_0047e94d`** (sets
  `DAT_0088CFA0=0x18`, `DAT_0088CF8C=0x1FA`, calls **`FUN_00485820` via `DAT_012E4DA0`** = the render/UI
  transition swapping the loading overlay for the 3D view) → world-observer broadcast `FUN_004C79E6`/`FUN_00466E47`.
- **false branch:** resets UC sub-objects + `(*(this+0x34)->vtable[+0x18])()` (world-session kick).

**Nuances that override naive readings:**
- **LobbyManager state does NOT gate rendering.** Tops out at `9` (VillageEntered); `10` = `LeavingVillage`
  (per `GetStateName @0x462bc0`), NOT "WorldLoginSent". Don't chase a state beyond 9.
- **`connState (+0x244)==3` is NOT the gate.** The constructor already sets it to 3. `+0x224` is a
  write-only latch; its consumer is the overlay render path above.
- **`HandleEnterWorld` (1000) alone does NOT render.** Its tail finalize `FUN_0046e980 → FUN_004d6a16 →
  FUN_0046e987` is only an observer broadcast — and is the **s32 AV site** on Win10/11 (stale WinXP-kernel32
  overlay observer head → `CALL 0x7c81320c`).

---

## 2. SERVER → CLIENT SEQUENCE (after EnterWorld 1000)

Client is **purely server-push-driven** after 1000. All msgs ride `SendGameData(74)`:
`Magic(0x26B6) | 74 | 74 | msg_type:u32 | data:MEMBLOCK(int32 len + bytes)`.

| # | msg_type | Trigger | Status |
|---|----------|---------|--------|
| 1 | **1006** `0x3EE` WorldLoginAck | On the client's **first** inbound PingCode (`0x2ED6`) | **REQUIRED — the gate** |
| 2 | **0xED7** `3799` PongCode | On **every** inbound PingCode (`0x2ED6`) | Recommended (keepalive) |
| 3 | **1005** `0x3ED` WorldTick | Periodically after 1006 (~2–4 Hz) | Optional (sim clock) — HOLD test 1 |
| 4 | **1004** `0x3EC` PlayerCreate | After 1006, once | Optional — **HOLD test 1** (AV risk) |
| 5 | **1001** `0x3E9` EntityCreate | After 1006, per object | Optional — HOLD test 1 (AV risk) |

### Bodies (name : type : size : value)
- **1000 EnterWorld:** `Worldname`(STRING,"world1") · `ServerPerm`(MEMBLOCK 32, zero) · `ChatChannelsCount`
  (MEMBLOCK 32, first dword=N, use N=1) · ×N{`ChatChannelZone`(MEMBLOCK 32),`ChatChannelID`(MEMBLOCK 32)}
- **1006 WorldLoginAck (gate):** `code` (MEMBLOCK 32, first dword=`0xDEADBEEF`). Client reads
  `ReadMemBlock(0x20)`, compares first dword only. **Must be a length-prefixed 32-byte MEMBLOCK, not a bare 4 bytes.**
- **0xED7 PongCode:** `PongCode` (MEMBLOCK 32, echo ping token; value never validated).
- **1005 WorldTick:** `tick` (MEMBLOCK **64** — reader `vtable+0x20`, len 0x40; zero clock OK).
- **1004 PlayerCreate:** `id`(MEMBLOCK 32) · `npcdesc`(STRING) · `npctyp`(u8) · 4×hair RGBA(u8) ·
  `bdyprt`(u32)×2 · `actcnt`(MEMBLOCK 8, first byte=N) · N×(MEMBLOCK 8, `actChat` STRING).

---

## 3. SERIALIZATION RULES (definitive — tincat3 PropertyDataConverter)

`tincat3!SerializeProperty 0x100112B0`, `DeserializeProperty 0x100110E0`, Property vftable `0x1004E5AC`.

Body is **POSITIONAL** — no names, no per-field type tag, no count header. Fields concatenated in
template-declared order; the deserializer recovers boundaries from the registered template (village
1000-1006 templates auto-register via the genuine `:5479` village-conn constructor):
- **Variable types** `{MEMBLOCK=1, STRING=2, WSTRING=3}`: **4-byte LE length prefix N** + N bytes (prefix
  overrides template max). STRING: prefix L, bytes + NUL, zero-padded to declared MaxLength. WSTRING:
  prefix=`(chars+1)*2`, UTF-16LE.
- **Fixed scalars** `{U8=4,I8=5,U16=6,I16=7,U32=8,I32=9,FLOAT=0xC,U64=0xA,I64=0xB,DOUBLE=0xD,BOOL=0xE}`:
  raw little-endian, fixed width, **no prefix, no terminator**.
- All integers little-endian; no padding between fields.

**village.py is correct; config.py's old comment was wrong** — `HandleEnterWorld` reads ServerPerm/Count/
Zone/ID via `ReadMemBlock(0x20)` (MEMBLOCK = length-prefixed), Worldname via `ReadString`.

### Body corrections (s35)
| builder | was | correct | why |
|---|---|---|---|
| `enter_world_body()` | MEMBLOCK 0x20 | ✅ no change | reader `ReadMemBlock(0x20)` |
| `world_login_ack_body()` | bare 4-byte | **`bytes_field(deadbeef + 28·\x00)`** (32B MEMBLOCK) | `ReadMemBlock(0x20)`; bare 4B under-runs |
| `pong_body()` | bare 4-byte | `bytes_field((token+32·\x00)[:32])` (32B MEMBLOCK) | `ReadMemBlock(0x20)` |

The **outer** `gamedata_frame` envelope (`msg_type:u32` + `bytes_field(data)`) is verified correct
(matches the client's own outbound 0x27D2 byte-for-byte).

---

## 4. OPEN RISKS (single manual drive)

1. **`code` MEMBLOCK vs bare-4-bytes (HIGHEST).** If the 32-byte MEMBLOCK 1006 still doesn't dismiss,
   fall back to the **bare 4-byte** form — these are the only two candidates. Success = loading vanishes /
   3D view; failure = continued 0x2ED6 PingCode every 30s, no other inbound.
2. **s32 observer AV on Win10/11.** If the client *crashes* right after 1006 instead of stalling — that's
   PROGRESS (the gate fired). Binary-patch the stale observer head next (see BINARY_PATCHES.md). **Do NOT
   send 1004/1001 in drive 1** — same observer fan-out, would conflate AV with a gate failure.
3. **Pong/1006 must reach the wire.** Confirm the 74 dispatch fires (`fields["msg_type"]` populated). Watch
   the log for the "WORLD-LOGIN REQUEST" line (proves 74 decode) + a PingCode-detected line + the 1006 send.
4. **One-shot timing.** 1006 fires on the *first* PingCode (after JoinChannel ran → UC predicate takes the
   finalize branch). If it half-fires (no crash, no render), try delaying 1006 to the **second** PingCode.
5. **Raw vs category-encoded outbound key.** Stub sends raw `1000`/`1006`/`0xED7`; inbound keys are
   category-encoded (`0x2ED6=(0x20<<8)|0xED6`). Raw is almost certainly correct (1000 raw worked). Long-shot.

**Live-verify addresses:** gate `HandleWorldLoginAck 0x46e8b0` (cmp @`0x46e8ea`); render transition
`FUN_0047e94d → FUN_00485820` via `DAT_012E4DA0`; finalize/AV `FUN_0046e987` (crash CALL @`0x46e9d8`);
dispatcher `HandleMessage 0x470890`; WorldTick `0x46f420`; SendWorldReadyAck `0x46bd00`; HandlePongCode `0x46be00`.
