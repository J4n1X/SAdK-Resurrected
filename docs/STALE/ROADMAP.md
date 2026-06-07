# SAdK Lobby Revival — Roadmap

_Last updated: 2026-06-04_

## Status

| Piece | State |
|---|---|
| Lobby login (ECDH + Twofish), chat, server list, room-assign | ✅ working |
| "Suche Server" / village button (lit + click) | ✅ working |
| Village-enter → **3D lobby world renders** ("Betrete Welt…", avatar visible) | ✅ reached |
| `0x7C81320C` crash on Win11 | ✅ **FIXED** — runs natively on Win11 x64 via `tools/debugger_loader.py` (see Track B) |
| Final world entry (client → `VillageServerConnection`) | ⏳ blocked: need the village comm-layer **magic + msg-1000 schema** (s27) |
| ~~msg-1000 pushed on UC conn after token~~ | ✅ **removed** (s27) — it crashed the client on every login (NULL property-set) |

**Key finding:** on **Win7** the protector resolves its VM-private imports natively — no crash — and the client walks all the way into the rendered lobby world against our stub. On **Win10/11** that same resolution yields a stale dev-machine XP address (`0x7C81320C`) and crashes. So the game is *fully playable today on a Win7 VM*; the Win11 problem is a **separable client-side patch project** (Track B).

---

## Track A — Finish the server (get fully into the world)

Goal: take the client from "Betrete Welt…" into the live 3D world, and round out the lobby.

### Corrected model (s27) — what actually happens
- Two connections exist in normal operation: **lobby (7070)** and **UC/chat (7071)**, both speaking
  the lobby comm-layer magic **0x26B6**. The token handshake **211→212→213→214 is the UC-connection
  login** that fires automatically on *every* login — it is **NOT** a village-enter trigger.
- The 3D village world is a **separate `VillageServerConnection`** (SADK class) that the client opens
  to the Ip/Port advertised in the chosen ServerType=4 GameServerData(170) — we advertise **5479**.
  Village message types (1000+) are registered **only** on that connection.
- Past mistake (now fixed): we pushed EnterWorld(1000) on the UC conn right after 214. That conn has
  no village-type templates → SADK called `tincat3!PropertyDataConverter::DeserializeProperty` with a
  **NULL IPropertySet** → crash (`mov eax,[ebp]`, ebp=0) → client died on every login. Push removed.

### A1 — Capture the real village handshake  ⟵ immediate next  (LIVE)
- Get a stable login (crash fix is in). In-game, **enter the village**. Expect the client to open a
  **new TCP connection to 5479** (the stub's `is_village` listener; currently logs raw frames only).
- From that capture, pin: (a) the **village comm-layer magic** (compare the village `CheckVersion(188)`
  bytes to the known 0x26B6 one — each layer's magic is set by `TinCat_CreateCommLayer`; lobby's
  `0x26B6` is @0x464350, the village layer is built in **SecuROM-overlaid** code so it can't be read
  statically), and (b) whether a token/login exchange precedes EnterWorld on this connection.
- If the client never dials 5479 on "enter", trace what it sends instead (RequestConnectionData 221?).

### A2 — Implement EnterWorld(1000) on the village connection
- Build the msg-1000 body as a TinCat PropertySet (positional values; var-typed props get a u32 LE
  length prefix, fixed props use intrinsic width — see `village.py`). Confirm the schema order/widths
  for Worldname / ServerPerm / ChatChannelsCount / channels (live-inspect the per-type template that
  `HandleEnterWorld` @0x46f470 reads by name). Send it on the 5479 conn → expect `SetState(9)` → world.

### A3 — The full village/world protocol  (the big one)
- After EnterWorld: player spawn, world objects, other players, position sync, in-world chat, list.
  This is the "3D lobby world engine" protocol — the largest remaining chunk, all TinCat property bags.

### A4 — Proper token crypto (replace best-effort 214)
- Current `214` is a best-effort echo (client accepts it for now). For full correctness, build a cryptographically valid cipher.
- The key is almost certainly the **session key issued in msg 207** (currently `os.urandom(32)` then **discarded** — see `dispatch.py:72`). Make it known/stored (keyed by `perm_id`), then build `214` (likely Twofish-CTR, reusing `crypto.py`).
- Refs: `COMM_LAYER_ERROR_CANNOT_CREATE_TOKEN` (token-gen), the working 201–207 login crypto.

### A5 — Polish
- Verify all `RequestX` handlers (buddy 56, ignore 157, MOTD 105, charlist 55, PropertyGet 161).
- Multi-client / multi-user (stub currently assumes the single `test` user).

---

## Track B — Fix the game on Windows 11 (DLL-inject patch; retire the VM)

Goal: run village-enter on **Win11 x64** without the Win7 VM, by fixing the protector's broken VM-import resolution.

> **✅ SOLVED (2026-06-04) — `tools/debugger_loader.py`.** The root cause wasn't import *resolution* — it's **SecuROM 7.x exception-based API dispatch**. SecuROM points its "imports" at deliberately-**unmapped** WinXP-kernel32 addresses (`0x7C81320C`); the call faults; a SecuROM **vectored exception handler (VEH)** catches the access-violation and forwards to the real API. Win10/11's modernized **WOW64 fails to deliver that 32-bit fault to the VEH unless a debugger is attached** → unhandled → crash. **Fix:** a transparent debug loop (`debugger_loader.py`) that passes faults back to the app, forcing delivery to SecuROM's VEH. **Proven standalone on Win11** — full village-enter into the 3D world, no VM, no binary patch, no DLL inject, no SecuROM RE. The B0–B3 notes below are the original (slot-patching) plan — kept for reference, but unnecessary.

### B0 — Root cause (established)
- The protector resolves its **VM-private imports** with its *own* code (not the PE IAT — that's why the game itself launches fine on Win11). On Win7 the resolution is correct; on Win10/11 it returns the stale dev-XP address. Prime suspect: a **WOW64-sensitive resolution** (hand-walking the PEB/loader, or a syscall/transition assumption) that the modernized Win10/11 WOW64 breaks.
- The known dead call: slot **`0x013C5213`** (inside the SADK image, fixed base `0x400000`) holds enc `0x9F871848`; XOR key **`0xE3062A44`** → **`0x7C81320C`** (= XP kernel32 base `0x7C800000` + RVA `0x1320C`). Function `F` returns a **writable pointer**, args `(2, 0, ANSI-name-ptr)`. `F` is **not** a stock SP2/SP3 export → an intermediate hotfix build; identity unknown from static analysis alone.

### B1 — Win7 is the diagnostic key (new advantage)
- On Win7 the slot resolves **correctly**. Inside the Win7 VM (install Python + a `ReadProcessMemory` reader, or a debugger): read slot `0x013C5213`, XOR `0xE3062A44` → `F`'s **Win7 address** → `F`'s Win7 **RVA** → `F`'s **NAME** via Win7 kernel32 exports. **This finally identifies F** — and the same readout identifies every other VM-import.
- Dump **all** the protector's resolved VM-import slots on Win7 (the descriptor table: one entry at `0x013C520B`, function ptr at `+8` = `0x013C5213`). Result: the full **{slot → function name}** map.

### B2 — Compare Win7 (correct) vs Win11 (stale) to understand the resolver
- Same binary, both OSes. Watch/trace the resolver: why `0x7C81320C` on Win11 but the right address on Win7? HW write-watchpoint on the slot **from process startup** — `tools/suspended_launch.py` is drafted for exactly this (CreateProcess SUSPENDED → arm watchpoint pre-unpack → catch the resolver).

### B3 — Build the Win11 fix (injected DLL)
Pick based on B1/B2:
1. **Slot re-resolution DLL** — on inject, walk the VM-import table and rewrite each slot = `enc(current kernel32 addr of that function-by-name)`. Surgical; needs the full slot→name map from B1.
2. **Resolver hook** — hook/fix the protector's resolver to resolve against live kernel32 (most robust if hookable).
3. **XP-kernel32 thunk page** — map a page at `0x7C800000` with `jmp`-thunks `XP_RVA → current function`; catches all stale addresses at once. Needs the dev-build kernel32 RVA map (from the Win7 readout).

**Injection:** a loader that launches `SADK.exe` **suspended** and injects the DLL **before** the protector unpacks/resolves (CreateRemoteThread+LoadLibrary or thread-hijack). `tools/suspended_launch.py` is the starting point.

**Validation:** village-enter on Win11 reaches the same "Betrete Welt…" as Win7.

---

## Tooling already built (`tools/`)
- `drm_addr_patch.py` — external WPM patcher for the dead VM slot (proved the mechanism; NULL/scratch returns are insufficient → the VM consumes the real return value, so we need the real function).
- `pe_exports.py` — dependency-free PE32 export-table parser (XP kernel32 RVA→name; never executes the DLL).
- `dump_rva.py` — raw bytes at a given RVA.
- `suspended_launch.py` — `CreateProcess(SUSPENDED)` harness to arm a watchpoint before the protector runs.

## Quick reference
- Dead slot `0x013C5213`, XOR key `0xE3062A44`, dead addr `0x7C81320C` (XP kernel32 RVA `0x1320C`).
- VM call site ≈ `0x01841A9B` (`call edx`); VM context `ebx` ≈ `0x018Bxxxx`; 2nd (valid) call `0x02460510`.
- Token handshake: `211 → 212(nonce) → 213(SendToken, 352B cipher) → 214(ValidateToken)`.
- Net: stub advertises `192.168.1.134` on `7070/7071/5479`; Win7 VM bridged `192.168.1.143`; client configs `LobbySettings.ini [LobbyServer] Host` **and** `network.ini [Lobby] url` both → `192.168.1.134`.
- XP kernel32 artifacts on host: `Downloads\xp_kernel32.dll` (SP3 5.1.2600.5512), `Downloads\xp_sp2_kernel32.dll` (SP2 5.1.2600.2180).
