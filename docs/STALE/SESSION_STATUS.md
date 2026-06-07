# SaDK Lobby Revival — Session Status

## ⭐⭐⭐⭐⭐⭐⭐⭐⭐ s33 (2026-06-05) — ★DRM WORLD-ENTRY CRASH SOLVED★ — past 0x7c81320c, EnterWorld delivered; NEW blocker = type-1000 template not registered (`tincat3!DeserializeProperty 0x100110e6`).

**★★★ THE DRM CRASH IS BEATEN (live, end-to-end).** With both patches applied + `ARM_ENTER_WORLD=True`,
the patched client drove the FULL world-entry: SPIEL STARTEN → UC login (no 0x7c81320c crash) → it opened
a **real separate VillageServerConnection (#3, 127.0.0.1:5479, magic 0x26B6)** → the stub delivered
**`EnterWorld(1000)`** on it (`→ sent EnterWorld(1000) magic=0x26b6 on conn #3 — SetState(VillageEntered=9)
expected`). The 2008 SecuROM derail on Win11 is solved.

**★ NEW, DIFFERENT crash = the s29/s30 template-timing prediction, confirmed.** It now faults at
**`0x100110e6` = `tincat3.dll!PropertyDataConverter::DeserializeProperty` (+6)** — NOT the DRM. The client
RECEIVED `1000` but the **type-1000 (0x3E8) PropertySet template isn't registered** on the village conn yet
(`CreatePropertySet(0x3E8)→NULL→DeserializeProperty NULL-deref`). We pushed `1000` ~2 s after the village
conn opened (its only traffic so far: handshake → one `188`/0x26b6 connection-data frame, `b6 26 bc 00 bc 00
1b 00 00 00 0f 00 00 00`); the 2 s DELAY bet (s30) did NOT register the template.

**⇒ THE NEW BLOCKER = the village-connection LOGIN is unreversed/unanswered.** The stub's `village.handle_frame`
only LOGS village frames; it never answers the `188`. The type-1000 template registers during that village
login exchange (SecuROM-overlay code) — so until the stub completes the village login, pushing `1000` always
NULL-derefs in DeserializeProperty. This is the same protocol-RE shape as the lobby login / token handshake
we already cracked — just on the village (:5479) connection. NOTE: with `ARM_ENTER_WORLD=False` the village
conn is STABLE (3 conns alive + pinging for minutes, no crash) — so the crash is purely the premature `1000`.

**NEXT (next session): reverse the village-connection login.** Capture the full :5479 exchange (the stub
saves `world_*.bin`; `village.handle_frame` hexdumps), reverse what the server must reply to the `188`
connection-data frame so the village login completes + the 1000-template registers, THEN push `EnterWorld`.
Likely needs a village 222/ConnectionData reply + possibly a village token handshake. The DRM/loader/patch
infra (debugger_loader attach-mode + map_dispatch_fix) is DONE and reusable for every future run.

**── s33 earlier (the DRM solve itself): ──**

The s32 crash (`0x7c81320c` at UC-LoggedIn) is **fully decoded + patched**, both fixes verified live (the game
**survives the dispatch — first time ever**).

**★ THE DEAD DISPATCH, DECODED BYTE-FOR-BYTE from the full dump** (`tools/find_dispatch.py` found the lone XOR-key `0xE3062A44` site @ `SADK+0x1441a68`; `find_all_dispatches.py` confirms it's the ONLY real dead-import dispatch — no 3rd lurking):
```
mov edx,[[ebx+0x28]+8] ; xor edx,0xE3062A44   ; EDX = 0x7C81320C (dead WinXP-kernel32 addr)
call $+0x20            ; call-over-data: pushed ret-addr = the embedded name string
db "0A25A3F6E7D13B25951F80DE03F34C3",0
push 0 ; push 2 ; call edx   ; → F(2,0,"0A25...") @ 0x7C81320C  ← CRASH (ret 0x01841a9d)
```
⇒ **F = `OpenFileMappingA(FILE_MAP_WRITE=2, FALSE, "0A25A3F6E7D13B25951F80DE03F34C3")`** — SecuROM re-opening its license shared-memory through a WinXP kernel32 address unmapped on Win7/10/11. Startup VEH resolves the *startup* imports then tears down ⇒ this never-used multiplayer import is unhandled ⇒ AV (the debugger_loader VEH-passing canNOT fix it). Same crash on Win7 — proven by the game's own `Win7dumps/LobbyComm.log` (ends at `"User 1 logged in."`). **the maintainer was right it's not Win7's fault.**

**★ DOMINO 1 — patch the dead target** (`tools/map_dispatch_fix.py`): in the live process, `VirtualAllocEx(0x7C810000,RWX)` + write `JMP` at `0x7C81320C` → the real `OpenFileMappingA` (game kernel32 base via a **32-bit PEB loader walk** — robust cross-bitness; `EnumProcessModulesEx` is flaky on the protected WOW64 target). The crash then MOVES 14 bytes forward, proving the call now resolves.

**★ DOMINO 2 — stack imbalance** (new crash @ `add [ecx],edx` `0x01841aba`): after `push eax`(handle) `@0x01841a9d`, the VM `call`s a wrapper `@0x02460510` that is a **no-op stub** `mov eax,0x5cc; ret` (`b8cc050000c3`) — it does NOT pop its pushed arg, so `pop ecx`@`0x01841ab9` gets the handle and `add [handle],edx` write-faults. (A handle/NULL is non-writable ⇒ creating the 0A25 mapping would NOT help; it's a STACK bug, not a NULL deref.) **Fix: NOP the `push eax`** (50→90) so the stack balances; the continuation then restores the real saved regs. Live `0x02460510` == the dump's stub (verified before patching).

**★ INFRA:** `debugger_loader.py` gained **attach-mode** (`attach <pid>` — hook a running SADK without relaunch) + **exact fault logging** (fixed the 64-bit DEBUG_EVENT union offset: ExceptionCode@`u+4`, ExceptionAddress@`u+20`). `tools/input_server.py` = an **elevated input relay**: UIPI blocks the agent's medium-IL shell from injecting input (SetCursorPos/mouse_event/keybd_event ALL refused) into the requireAdministrator game; the relay runs elevated (one RunAs) + executes FG/MOVE/CLICK/KEY/TYPE from a seq'd relay file (`MOVE` confirmed `ok=1` elevated). Game is requireAdministrator ⇒ loader/relay run elevated; the patch piggybacks.

**NEXT (the live confirmation — needs the maintainer's click; he kept getting pulled to Discord):** loader attached + both patches applied to pid 15624 → drive **LOBBY → login test/test/test → Testler → SPIEL STARTEN**. The dispatch should SURVIVE (fix logic verified). Then flip **`ARM_ENTER_WORLD=True`** + restart the stub so it pushes msg 1000 (EnterWorld, magic 0x26B6, world "world1") → the 3D world renders. Memory: **`world-entry-crash-is-openfilemappinga`**.

---

## ⭐⭐⭐⭐⭐⭐⭐⭐ s32 (2026-06-05) — ★WORLD-ENTRY REACHED (live)★ — crash isolated to a dead indirect CALL in the usercomm-LoggedIn observer fan-out.

**THE 153 FIX WORKS end-to-end at login:** lobby login completes, the game is responsive at char-select for 20+ min.
On **SPIEL STARTEN / BETRETE WELT** the client opens a **usercomm connection** (→ our :7071), token-logs-in
(211/213 → our **153**), **completes login**, and then **CRASHES** ~650 ms later. First time we've ever driven the
client to world-entry.

**Crash fully traced from a live FULL-memory dump** (procdump `-ma`, 1 GB + `tools/parse_crash.py`,
`find_badptr.py`, `read_objs.py`):
- `ACCESS_VIOLATION`, faulting **EIP = EDX = `0x7c81320c` (UNMAPPED)** — a bad indirect CALL through a dead ptr.
- Chain (proven off the faulting stack): `tincat3!FUN_10027080` (LAN recv, `case 0x99` = our 153 → fires LoggedIn)
  → `SADK LobbyManager::OnLoggedIn 0x463910` → `UserCommConnection::OnLoggedIn 0x47ef50`
  → `LobbyBaseConnection::OnLoggedIn 0x48d8b0` → **`NotifyObservers 0x48d7e0`, CALL EAX @`0x48d845`** → `0x7c81320c`.
- The dead pointer is **DETERMINISTIC** (identical across two crashes) and sits in a **SecuROM-overlay data region**
  (`SADK+0xe92xxx`). The observer list is **NOT** at `conn+4` (that field = 5, a count); `NotifyObservers` gets its
  head via `FUN_004798b0` (overlay tail-jump). ⇒ the fan-out walks corrupted/uninitialised memory and calls a dead ptr.
- **The 153 is CORRECT** (the LAN recv machine `FUN_10027080` accepts it + fires LoggedIn); the crash is a client-side
  observer/list problem **exposed** by completing the usercomm login. The s31 ChannelInfo deferral did NOT prevent it.

**Live-debug infra established:** the Ghidra dbgeng debugger WEDGES on a running target (only answers when stopped);
the reliable path is **procdump `-ma` + the `minidump` python lib**. NB: the game writes its OWN minimal dump (stack
only) to `C:\Users\user\Documents\SAdK\dumps\crashdump.dmp`; procdump gives the full heap. Localhost ⇒ the client
runs the **LAN** comm-layer role (recv `FUN_10027080`), not INET (`0x10023460`).

**NEXT:** 3 agents RE'ing in parallel — (A) the observer-list mechanism + corruption cause, (B) usercomm-connection
lifecycle/timing (should it log in at lobby-login not world-entry?), (C) which subsystem's observer is the dead one
(a missing init message?). Then a targeted fix — timing delay, a missing setup message, or routing world-entry via
the **village** connection (`LobbyManager+0x540`, whose LoggedIn `0x46d820` WORKS).

---

## ⭐⭐⭐⭐⭐⭐⭐ s31 (2026-06-05) — ★THE FIX★ The game client has NO 214 handler on UC login — it completes on a **153 (AddResult) ACK**. Token crypto fully reversed + implemented.

7-agent deep static RE of the tincat3 `TokenValidator`/`Authenticator` + the client login state machine.
TWO breakthroughs, both now implemented in the stub.

**★ BREAKTHROUGH 1 — the token CRYPTO is fully reversed + implemented.** Token `cipher` = `IV(16) ||
Twofish-CTR(key, IV, plaintext)` (LibTomCrypt 1.10, LE counter, **NO MAC**) — byte-identical to our
`crypto.py`. Key = the per-connection key at `ConnMgr+0x38`: seeded by the 202 ECDH secret, then
**RESEEDED by the 207 session key** (the 32 B we were discarding; now retained on `conn.session_key`).
Plaintext = `perm_id u32 | u8len+name | u8len+cdkeyHash | u32 | u8len+serverPw | u8len+nonce` (the 212
nonce is the embedded challenge). `crypto.build_token_plaintext/_cipher` added + round-trip verified.
Named: `Authenticator_GenerateToken @0x1002c090`, `DecryptToken @0x1002c430`, +slot/validator funcs.

**★★★ BREAKTHROUGH 2 — THE ACTUAL UNBLOCK. The game (UC-login CLIENT) has NO handler for 214 (`0xd6`).**
Its client recv state machine (`ClientRecvHandler @0x10023460`, jump table `0x10023a30`, index =
wiretype−0x2a) has a bound at `0xAA`; a 214 lands at index `0xAC > 0xAA` → logged **"Invalid
message-type"** and **DROPPED**. After sending **213 SendToken** the client waits for the **`0x99` ACK =
`NETMSG 153 (AddResult)`** with `errorcode==0` → connection **state→8 (AUTHORIZED)** → fires the
**LoggedIn** callback (the thing that never fired). **We were sending a 214 the client cannot parse — the
s22 `213→214` change was the regression that broke world-entry.** The 214/Twofish-CTR path is consumed
ONLY on the SEPARATE secured ROOM-server connection (`RoomServerConn_RecvDispatch @0x1002fc20`, case
`0xd6` → crypto `@0x10027b80` → `OnRecv214 @0x1002a980`, gated by a slot in state==2; accepts a no-crypto
214 iff the server descriptor advertises **no `cipher`**).

**THE FIX (implemented + verified, s31):** `dispatch.py` `_h_send_token` (213) now replies
**`AckResult(153)` errorcode=0** (`conn.status_with_id`), NOT a 214. Verified: 213 → 153, errorcode=0,
id=perm_id, ticket=match (`tools/_verify_213_ack.py`). Token crypto helpers kept for the room-server path.
**Errorcode is a non-issue:** `NETMSG_TYPE_214` has no `errorcode` field (msgdefs.ini) → getter returns
the UCHAR default 0; the 153 ACK carries the real errorcode.

**NEXT (decisive, LIVE — the maintainer or the harness):** run stub + game → does UC login now complete (LoggedIn
fires, no 3 s park/stall, char-select healthy)? If yes → flip `ARM_ENTER_WORLD=True` and push msg 1000 for
world-entry. `tools/game_harness.py` runs this autonomously (RPM `LobbyManager+0x57c` state oracle →
`verdict.json`). Live BP to confirm: `tincat3!ClientRecvHandler 0x10023460` case `0x99` (→ state 8 + LoggedIn).
See **`uc-login-153-ack-not-214`** memory + the s31 commit.

---

## ⭐⭐⭐⭐⭐⭐ s30 (2026-06-05) — ★CORRECTION★ There is NO village magic. msg 1000 rides 0x26B6; the blocker is TEMPLATE-REGISTRATION TIMING.

Second multi-agent **static** RE pass (5 agents: registry/routing, 3× source-quality docs, protocol-gap)
+ live-capture mining. Overturns the long-held "village comm-layer magic hidden in the SecuROM overlay"
assumption. Ghidra now reads like source for ~40 funcs (saved). See **`WORLD_ENTRY_PLAN.md`**.

**★ THE MAGIC HUNT IS OVER — IT WAS A RED HERRING.** The whole client uses ONE TinCat comm layer, magic
**0x26B6**. `LobbyComm_System_Initialize` (0x4640f0) is the ONLY `CreateCommLayer` call in the binary
(verified: thunk 0x48e6b4 has one xref). Lobby + UserComm + Village/World are sub-objects multiplexing
that single layer and its single PropertySet factory `*(*(LobbyManager+0x50)+0x20)`. Proof it carries
village types: tincat3's own 170 decoder uses `CreatePropertySet(0xAA)` on this factory and our 170 works.
Disproof of a separate magic: the overlay's `push 0x62; sub 0x61; pop` is metamorphic DECOY arithmetic
(read it live at 0x1852d68), and ZERO of ~100 captures hold any non-0x26B6/0x0062 magic. So **msg 1000
rides 0x26B6** — same layer as login.

**★ THE REAL BLOCKER = TEMPLATE-REGISTRATION TIMING.** The factory starts EMPTY; tincat3 registers the
221 msgdefs types; the village types **1000-1006 are registered LATE, by SecuROM-overlay code during the
village/world connection setup that runs AFTER char-select** (SADK imports no RegisterPropertySet; it's an
overlay-virtualized call on the same factory). Before that, `cPropertyFactory::CreatePropertySet(0x3E8)`
(tincat3 **0x10013830**, vtable +0x0C) returns NULL → `DeserializeProperty` NULL-derefs → the historical
**s26/s27 crash was pushing 1000 too EARLY** (immediately after 214, before the template existed). NOT a
magic/format bug.

**IMPLEMENTED (s30):** msg 1000 now frames with **0x26B6** (`config.VILLAGE_PAYLOAD_MAGIC=0x26B6`);
`ARM_ENTER_WORLD=True`, `ENTER_WORLD_DELAY=2.0` → push 1000 on a 2 s DELAY after 214 (s26/s27 pushed at
0 s). Byte-verified; codec-golden + smoke tests pass. The delay is the new variable: bet the overlay
registered the templates in those 2 s.

**LIVE log this session:** login + UC conn #2 + token 188/211/213/214 all clean; client then PARKS sending
NO frame (so passive sniffing can never reveal a magic — there isn't one). Confirms entry needs a server
PUSH of 1000.

**NEXT (decisive, the maintainer + live client):** run armed → BETRETE WELT. Enters world? → DONE. Crashes? →
template needed the explicit enter engagement; pin the moment with a live BP on **tincat3!RegisterPropertySet
(0x10013710)** watching msgType 0x3E8-0x3EE (ECX=factory, [ESP+4]=type, [ESP+8]=IPropertySet*), then move
the push to that trigger / lengthen the delay. Win11: run under `tools/debugger_loader.py`.

---

## ⭐⭐⭐⭐⭐ s29 (2026-06-05) — WORLD-ENTRY FLOW FULLY MAPPED (static, multi-agent) + IMPLEMENTED. One blocker: the village magic.

Autonomous multi-agent **static** RE of SADK.exe + tincat3.dll (3 SADK agents + tincat3 by main),
all persisted into Ghidra (renames/prototypes/plate-comments; `save_all_programs` OK). The whole
connect→leave-char-select path is now understood end-to-end and implemented in the stub. See
**`WORLD_ENTRY_PLAN.md`** for the authoritative flow.

**RESOLVED the s26-vs-s28 tension:** leaving character-select is driven **entirely by the server
PUSHING village msg `1000` (EnterWorld)**. The "BETRETE WELT" click sends **zero** network (s28 was
right about that) — it only arms a client-side action, then the client **waits for `1000`** (s26 was
right about the trigger). `HandleEnterWorld 0x46f470` calls `SetState(VillageEntered=9)` as its
**first instruction, before parsing the body** ⇒ one well-framed `1000` (even count=0) enters.

**Topology (resolved):** only TWO sockets ever (7070 lobby + 7071 UC); the client **never dials
:5479**. The village "connection" is a TinCat comm-layer **multiplexed on the UC socket (7071)** with
its own magic. `CreateVillageServerConnection 0x463750` opens NO new socket — it reuses the UC
transport (`conn+0x34` pre-set) and dials the `+0x548` chat handle. ⇒ **push `1000` on the UC conn.**

**msg 1000 schema CONFIRMED** (tincat3 `PropertyDataConverter` 0x100110E0/0x100112B0 + SADK 0x46f470):
`STRING Worldname | u32 ServerPerm | u32 ChatChannelsCount | N×(u32 Zone, u32 ID)`. Property type tags
(from `Property::SetMemBlock 0x10011500`): 1/2/3 = variable (u32 len-prefix + bytes); 4..0xe = fixed
width (8/9=u32). **`ServerPerm` is a fixed u32, NOT a memblock** (the key doubt, settled). Our
`village.py:enter_world()` body is byte-correct (verified).

**THE ONE BLOCKER = the village comm-layer MAGIC.** A socket multiplexes layers by magic (lobby
`0x26B6` @0x464350; chat `0x0062`; village = UNKNOWN). The village `TinCat_CreateCommLayer` call is in
the SecuROM overlay and the magic is **computed at runtime** — NOT a static immediate (verified by
byte-searching the whole image for the `6A 05 68 <imm>` CreateCommLayer shape: only the lobby hit
qualifies). Sending `1000` with `0x26B6` routes it to the lobby layer (no type-1000 template) →
`DeserializeProperty` NULL-derefs → the old s26/s27 crash. So it MUST be captured live.

**IMPLEMENTED (s29), safe-by-default:** `app_payload(...,magic=)` parameterized; `enter_world()`
schema-correct + magic-gated; `dispatch.py` pushes `1000` after `214` **iff `ARM_ENTER_WORLD`**;
`config.py` adds `VILLAGE_PAYLOAD_MAGIC`/`ARM_ENTER_WORLD`/`ENTER_WORLD_WORLDNAME`/`ENTER_WORLD_DELAY`
+ capture procedure; **`connection.py` now PASSIVELY SNIFFS** the village magic (flags any app frame
whose magic != 0x26B6/0x0062). Default = does NOT push `1000` (won't crash the client). Tests pass
(codec-golden 3/3, smoke OK); `enter_world` byte-verified.

**NEXT (decisive, needs the live client — for the maintainer):** run stub + enter lobby + click BETRETE WELT;
watch the log for `⚠ APP-FRAME MAGIC 0x####` → set `config.VILLAGE_PAYLOAD_MAGIC=0x####` +
`ARM_ENTER_WORLD=True` → re-test. Expect `SetState(9)` → 3D world, no crash. (Win11: run under
`tools/debugger_loader.py` as before.)

---

## ⭐⭐⭐⭐ s15 (2026-06-03) — ★SOLVED★ "Suche Server" button is LIVE. Room-assign = 170 `data` blob.

THE MONTHS-LONG BLOCKER IS BROKEN. Live dbgeng trace nailed the full mechanism end to end:

- The village entry's **roomId(+0x30)** + **pending(+0x34)** are NOT from the 170 `room_id` field —
  they are PARSED from the 170's **`data` (MEMBLOCK)** field by the client's update "commit" branch.
- Flow: AddOrUpdate(0x46a000) -> construct(0x53ee4a: defaults roomId=-1/+0x34=1/validity=0) -> tail-jmp
  update(0x130a080). Update copies id/name/port/players and sets **validity(+0x35)=(descriptor.listAction
  (+0x4c)!=0)**. THEN gate @0x130a11a: if `descriptor+0x58 == [0x12f283c](=5)` OR `descriptor+0x54
  (data ptr) != 0` -> **COMMIT branch @0x130a1b4**. Commit builds a reader over `data`
  (0x48f1e0/0x48eb40/0x48ec40 -> DRM thunks) and writes **entry+0x30 = roomId (@0x130a28d)** and
  **entry+0x34 = pending (@0x130a294)**. The fully-set temp is then copied to the heap list entry.
- We were sending **data=NULL** -> descriptor+0x54=0 -> commit SKIPPED -> entry stuck at (-1/pending/invalid).
- **DATA FORMAT (live-derived):** 5 bytes (`[0x12f283c]=5` = expected length) = **roomId as BIG-ENDIAN
  u32** + **1 pending byte**. Proof: sent `E8 03 00 00` -> ECX read `0xE8030000`; flipped to
  `00 00 03 E8` -> ECX read `0x000003E8 = 1000`. ✅
- **FIX** (sadk_lobby/dispatch.py FAKE_VILLAGE): `"data": b"\x00\x00\x03\xe8\x00"` (roomId=1000 BE,
  pending=0). LIVE-CONFIRMED heap entry: roomId=1000, +0x34=0, validity=1 -> IsListReady TRUE ->
  **BUTTON UNGREYED IN-GAME.** ✅✅✅

NEXT FRONTIER (s15 live test): clicking "Suche Server" CRASHES INSTANTLY — with AND without the
debugger attached (so NOT anti-debug; ruled out). Stack trace: SADK overlay 0x01841a9d -> 0x01841a71
(the DRM code-virtualizer; VM saved-context @0x018B0000 holds EFLAGS/return frames; metamorphic stub
@0x18a0028) -> `CALL EDX` where EDX=0x7C81320C. 0x7C81320C is an **XP-era kernel32 address** (WinXP
kernel32 base = 0x7C800000; on Win11 kernel32 is @0x74CC0000). => the village-entry code path is
DRM-VIRTUALIZED and the 2008 protector derails into a stale XP kernel32 pointer on Win11. This is a
PROTECTOR-vs-modern-OS problem, NOT the game's network logic — different/harder beast.
Candidates (fresh session): (1) run SADK.exe on WinXP/Win7 (a VM) where 0x7C8xxxxx is valid kernel32;
(2) RE which kernel32 export 0x7C81320C maps to on XP + whether it's patchable; (3) verify our `data`
blob (only roomId+pending=5B) isn't missing village-entry fields the protected code reads after Enter.
*** The lobby PROTOCOL side (login -> list -> room-assign -> button) is FULLY SOLVED. ***

s15b (live-traced the Enter crash; NOT our packet — proven): EnterVillageAction(0x503da0) ->
CreateVillageServerConnection(0x463750) builds a PRISTINE VillageServerConnection (vtable 0x7dc8d4; all
16 slots valid: +0x14 HandleLoggedIn@0x46d820, +0x18 HandleLoginFailed@0x46d910, +0x24 HandleMessage@
0x470890, +0x3c=0x470b50). EnterVillageAction calls vtable+0x3c = FUN_00470b50 which opens a UserComm
connection (LobbyManager__GetChatServerHandle(this+0x158) + UserCommConnection__OpenCommunication).
Inside that (DRM-virtualized) the VM does `CALL EDX` with EDX=0x7C81320C — a FIXED XP-era kernel32 CODE
address (EXECUTE-fault, identical every run, unrelated to our data 1000/5479). Connection object + chat
handle are well-formed. => the 2008 PROTECTOR calls a dead XP kernel32 import on Win11; not a packet bug.
FIX PATH: run SADK.exe on WinXP/Win7 (a VM) where kernel32 is based at 0x7C800000; then re-test Enter
with the SAME stub. The whole lobby/network side is done.

---

## ⭐⭐⭐ s14 (2026-06-03) — LIVE+STATIC PROOF: entry is born "pending"; the 170 NEVER activates it

DYNAMIC (dbgeng attach pid, BP 0x46a000, runtime base == ghidra base 0x400000 so addrs are 1:1).
Caught a village GameServerInfo construct from our 170 (entry @ heap, vtable 0x7ddfd4):
  +0x04 id=1, name="world1", +0x24 port=5479, +0x28 cur=1, +0x2c max=20  -> ALL copied correctly
  +0x30 nRoomId = 0xFFFFFFFF (-1)   <- NOT set
  +0x34            = 1 (pending)     <- NOT 0
  +0x35 validity   = 0               <- NOT set
Sent the village 170 TWICE -> 2nd took the UPDATE path (thunk_FUN_0137a900 @ 0x4811e0); re-read the
entry: BYTE-IDENTICAL. So 170 insert AND update both leave roomId=-1 / pending=1 / validity=0.
(Descriptor was perfect: room_id=1000 present @ desc+0x3e; the copy just ignores it.)

STATIC PROOF — the readable, deobfuscated GameServerInfo CTOR @ 0x53ee4a HARDCODES the defaults:
  MOV [obj],      0x7ddfd4       ; vtable
  MOV [obj+0x30], 0xFFFFFFFF     ; roomId   = -1
  MOV [obj+0x34], 1              ; pending  = 1   (constant, not from descriptor)
  MOV [obj+0x35], 0              ; validity = 0
  JMP 0x4811e0                   ; tail-call the (obfuscated) update
Copy-ctor @ 0x47e724 propagates ALL fields incl. +0x30/+0x34/+0x35 (vector growth) -> a correct
SOURCE would carry through.

GATES (both require the ACTIVE state; confirmed live + static):
  Button  IsListReady (0x4AD750): some entry w/ nRoomId==1000 & cur*100/max<90% & validity!=0.
  Enter   FUN_00440cf0 / HandleRoomServerDescriptor (0x4409d0): entry w/ +0x34==0 & validity!=0 &
          nRoomId==g_dwSelectedVillageRoomId(1000).
Our entry fails ALL THREE.

ACTIVATE = MISSING + DRM-HIDDEN. HW write-watchpoints on entry+0x30 / +0x34 sat through the whole
idle char-select screen -> ZERO writes. Nothing in the current message flow activates the entry.
The activator is NOT in readable .text (every clean +0x35=1 / +0x34=0 write belongs to OTHER
structs: std::_Tree nil-node @0x78da50, CMiniGamePoker @0x524970, CLobbyClient @0x503xxx). =>
it's in the obfuscated overlay AND fired by a server->client message/event we don't send.

NO working-lobby capture exists to diff (emulator *.bin are single-message samples; real servers
dead). The 170 WIRE FORMAT IS A DEAD END for room/validity — STOP tuning it.
NEXT: trace the obfuscated update 0x4811e0/FUN_0137a900 for a conditional descriptor read (it may
gate roomId on a 170 flag we send wrong); or find the activate handler via the LobbyComm msg dispatch.

---

## ⭐ s13 (2026-06-02) — CORRECTION: our 170 is FLAWLESS; the entry COPY drops RoomId/validity

Live descriptor capture (BP `0x46a036`, EDI = descriptor @ stack 0x0296EDD0) with the
ServerSubtype=2 stub. The `170` deserializes PERFECTLY:
- `+0x00`=ServerId 1, `+0x20`=Port 5479, `+0x28/+0x29`=`04 02` (ServerType 4 / **ServerSubtype 2**),
  `+0x30/+0x32`=MaxPlayers 20 / CurPlayers 1, Name ptr→**"world1"**, Map ptr→**"world1"**,
  and **`+0x3c` (u32) = 0x3E8 = 1000 = our RoomId.** Everything correct.

⇒ The s12 "format misalignment" theory was WRONG. The packet is fine; the "gColworld1" entry
name (s12) was a copy/SSO artifact, not a wire shift. **The real problem: the descriptor →
`GameServerInfo` copy (`thunk_FUN_0136e4f0`, un-analyzed >0x1000000 region) does NOT carry RoomId
or the validity flag into the entry.** entry+0x30 stays at the `-1` default
(`g_dwInvalidVillageServerId`) and entry+0x35 stays 0 — NOT sourced from the descriptor (no
descriptor field is -1/0 in that slot). So a village server's **room assignment + validity come
from a DIFFERENT mechanism**, not the GameServerData RoomId field. (`IsListReady` needs
entry+0x30 == 1000 AND entry+0x35 != 0; `param_1`=1000 confirmed live.)

**NEXT (NOT a packet-format fix):** find how entry+0x30 / entry+0x35 get set for a village server.
Candidates: a separate lobby push (RegisterServer-168 response / a room-assign message), a 2nd
GameServerData carrying a game-in-room, or a different descriptor field the copy reads (that we
send as default). Best tools: disassemble `thunk_FUN_0136e4f0` (the constructor/copy) once it's
create_function'd, or — since the debugger is read-only — find what WRITES entry+0x30 (set a
hardware watch via a small bethington patch, or step the copy). The ServerSubtype=2 list-membership
win STANDS (our server is in the list; only the per-entry RoomId/validity gates remain).

---

## ⭐⭐ s12 FRONTIER (2026-06-02) — VILLAGE LIST NOW POPULATES; 2 entry-field gates left

**BREAKTHROUGH: `ServerSubtype=2` gets our server INTO the village list.** The add fn
`FUN_0046a000` (gate at 0x46a036) requires descriptor `[0x29]==2` (= the ServerSubtype byte,
which was hardcoded 0 at tincat_server.py ~line 1030). Fixed: made it `srv.get('server_subtype',0)`
and set the village entry `'server_subtype': 2`. Confirmed LIVE: the list vector at
`pServerList+0x74/+0x78` now holds 1 entry (begin != end). The months-long "empty list / greyed
button" blocker is BROKEN. (descriptor[0x4c] action must also be !=0; ours is 1, fine.)

**Button STILL greyed — `IsListReady` has 2 more per-entry checks.** Decompiled `FUN_004AD750`
(had to `create_function` it; it's the runtime target of thunk 0x4682d0 / `_DAT_012f161c`).
`IsListReady(this, param_1)` returns true only if SOME entry has ALL of:
  (a) `entry+0x30` (RoomId) == `param_1`,
  (b) capacity `entry+0x28*100/entry+0x2c < 0x5a` (90%),
  (c) `entry+0x35` (validity flag) != 0.
LIVE: `param_1 = 0x3E8 = 1000` (the selected room). Our entry: capacity OK (cur=1/max=20),
but **`entry+0x30` = 0xFFFFFFFF (-1 = g_dwInvalidVillageServerId default)** and **`entry+0x35` = 0**.
Both fail → IsListReady false → button greyed.

**Root cause: 170 FORMAT MISALIGNMENT.** Our wire RoomId (`lobby_id=1000`) and a validity flag
do NOT land in `entry+0x30` / `entry+0x35`. (The descriptor→GameServerInfo copy is in the
un-analyzable >0x1000000 region via `thunk_FUN_0136e4f0`.) The entry's stored name even reads
"gColworld1" (4-byte garbage prefix) — the "old" 170 layout is wrong for the fields after the
player counts (MaxSpec/CurSpec/AiPlayers/RoomId region).

**NEXT (the last mile):** re-trace the descriptor with the current stub (BP `FUN_0046a000` /
0x46a036, EDI = descriptor), map EVERY descriptor byte to our wire fields, find the correct
slots for RoomId + the validity flag, and fix `_make_server_payload_old`. Target: `entry+0x30=1000`,
`entry+0x35!=0` → IsListReady true → "Suche Server" goes live → click → `CreateVillageServerConnection`
dials the village host (:5479, still to be built). Entry struct = `GameServerInfo` (vtable ~0x7ddfd4).

---

## ⭐ s11 FRONTIER (2026-06-02) — entry path fully mapped; 2 concrete blockers left

**`world1` SOLVES the scene-load freeze.** ServerType=4 entry `name='world1'`, `map='world1'`,
`lobby_id=1000` (a REAL local world: `data\lobby\scene\world1.xml`) stops the PhysX infinite-spin.
With `name='Lobby'` (no such world) the client fabricated an empty scene + loaded garbage geo →
freeze. So RoomId=1000 IS the village-entry path; name/map must point at a real world on disk.

**BUT entry still doesn't complete — state parks at GlobalDataLoaded(7).** Live: LobbyManager =
`*(LobbyVillageScreen+0x1f0) - 0x54`; state `+0x57c=7`, chat `+0x548=1`, village-conn obj `+0x540`
allocated-but-unconnected. The room-1000 match (`FUN_004409d0`) only does the `LoadLevel` (scene);
it does NOT advance state or dial the village server.

**The "Suche Server" button is the real entry trigger and it's DEAD (greyed).** Confirmed live:
clicking it / double-click character / etc. fire NONE of the entry BPs (`0x4409d0` match /
`0x463750 CreateVillageServerConnection` / `0x43ab10 OnVillageConnectFailed`). Button greyed
because the village list is empty (IsListReady=`FUN_004AD750` false). Avatar creation SOFTLOCKS
(needs lobby-server avatar support we don't provide) — CPU spike 42→568s.

**⇒ TWO blockers remain to actually enter the village:**
- **(A) Populate the village list** → un-greys the button → click → `EnterVillage`
  (`FUN_00503da0`) → `CreateVillageServerConnection`. Our `170` ServerType=4 entries do NOT land
  in the list; real 170→list dispatch is obscured (jumptables); `FUN_00469470` never fired.
  Suspect a missing GetServers "list-complete" signal (client stuck `LOBBY_LOADING_SERVERS`). ← THE GATE.
- **(B) Build the village server** at the entry's Ip:Port (`127.0.0.1:5479`) — the village/DNG
  realtime protocol — so `CreateVillageServerConnection` succeeds and state goes 7→8→9.

**NEXT:** (A) memory-watchpoint the live list object (grab it from IsListReady's `ecx`) to catch
the REAL writer / prove the 170 never reaches it; restore static Ghidra to recover the 170-dispatch
and `0x4682d0`/`0x012f161c` jumptables. (B) once entry can fire, trace `CreateVillageServerConnection`
for the target + first bytes → build that server. NOTE: binary capture (`sadk_captures/*.bin`) was
0 bytes for one conn — capture path is glitchy; trust the flushed text log.

---

**Date:** 2026-06-02 (session 11 — live debugger)  
**Status:** Login FULLY WORKS live → character-select (the 3D library IS the loaded lobby
world). One true blocker remains: the **village server list never populates**, so the
"Suche Server…" button stays greyed (`!LOBBY_LOADING_SERVERS`). Goal: get our village
server INTO that list.

---

## 🔬 LIVE-DEBUGGER FINDINGS 2026-06-02 (s10) — confirms s3 gate #1, kills the RoomId detour

Live debugger = bethington :8099 (attach SADK PID, sync SADK@0x400000 / tincat3@0x10000000).

**CONFIRMED the blocker = s3 gate #1 (list must populate), NOT gate #2 (RoomId).**
- `UpdateEnterButton` (`FUN_00439e80`) live: mode `+0x1e8==1` ✓, idle `+0x218==1` ✓,
  busy `+0x21c==0` ✓, `IsField98Set`=`FUN_00472040(+0x1ec)` ✓ — ALL pass. The ONLY failing
  gate is **`IsListReady()`** = thunk `0x4682d0` → `(*_DAT_012f161c)()` = **`FUN_004AD750`**
  (runtime-resolved). Its `ecx` = the screen's list `pServerList` (`LobbyVillageScreen+0x1f0`).
  Live: the list is **EMPTY** → IsListReady=false → label `LOBBY_LOADING_SERVERS` ("Suche Server…").
- Global list `DAT_0087e790` (0x0087e790) is ALSO empty (zeros + stray "None"). Our `170`s land
  in NEITHER. NOTE: the `+0x70/0x74/0x78` std::vector model does NOT cleanly hold for these
  objects (layout obscured) — revisit before trusting offsets.

**Our `170` ServerType=4 entries reach the client (deserialize OK, no TinCat error) but never
populate the list.** BPs on `FUN_00469470` (`LobbyComm::ServerList::GameServerDataReceived`)
and `FUN_00468900` (the `cpp:116` / `COMM_LAYER_ERROR_INTERNAL` parse-error site) did **NOT
fire** during a full login that sent ServerType=4. So the 170→list path is NOT those (or the
170 isn't dispatched there). The `cpp:116` error in `LobbyComm.log` was an OLD/stale run.

**RoomId DETOUR — REVERTED, DO NOT REUSE.** Setting ServerType=4 `lobby_id=1000` (== current-room
`g_SelectedVillageRoomId`/`DAT_0087d580`, live=0x3E8) does NOT fix the button (list still empty);
it only matched the "current room" → triggered the LoadLevel path (`FUN_004409d0` → `"LoadLevel"`)
→ **single-thread PhysX infinite-spin freeze** (1 thread @ 400+ CPU-s, 88 idle). Stub back to 9212.

**Debugger infra:** patched `ghidra-mcp/debugger/engine.py::go_nowait` (blocking `base.go()` via
`_submit`) so GUI games run under the debugger. Drive via PowerShell → :8099
(`/debugger/interrupt|registers|sync_modules|continue`, `DELETE /debugger/breakpoint/{id}`).
Reading memory needs the worker free → interrupt first. cdb.exe NOT installed (only DLLs).
Static Ghidra MCP = "No program loaded" while a trace is active.

**NEXT (handlers were guesses that don't fire):** BP `IsListReady` (`FUN_004AD750`) to grab the
authoritative list object live (ecx), then set a **memory watchpoint** on its count/ready field
to catch the REAL writer when a 170 arrives (or prove the 170 never touches it → dispatch/format
issue). Strong suspicion: client waits for a list-COMPLETE signal we don't send (our `_ok` after
the 170s may be wrong), so it stays "LOADING" forever. Restoring static Ghidra (xrefs + recover
the `0x4682d0` and 170-dispatch jumptables) would unblock this fast.

---

## 🔬 DECOMP FINDING 2026-06-01 (s3) — what actually greys the button

Traced from `decomp/sadk/SADK.exe.c` (see `decomp/RENAME_LIST.md` for all addrs/labels).
The 3D lobby world is internally the **VILLAGE** (search `VILLAGE`, not "Suche Server").

**`FUN_00439e80` = `LobbyVillageScreen::UpdateEnterButton`.** It sets the button to:
- `!LOBBY_LOADING_SERVERS` (greyed) while the **village server list isn't ready**
  (predicate behind the unrecovered jump table at `0x4682d0`), or
- `!ENTER_VILLAGE_BUTTON` once the list is ready.
It only becomes *clickable* when ALL hold: screen mode `+0x1e8==1`, not-busy `+0x21c==0`,
idle `+0x218!=0`, sub-object `*(+0x1ec)+0x98 != 0`, **and** the list-ready predicate.

**`FUN_0043ab10` = `OnVillageConnectFailed`** fires `!COULDNOT_CONNECT_TO_VILLAGE` when
`LobbyVillageServerList::FindByRoomId(list, g_SelectedVillageRoomId, -1)` returns **-1** —
i.e. no listed server whose `entry+0x30` (RoomId/LobbyId) matches the selected id
(`DAT_0087d580`).

**⇒ Actionable, server-side (two gates, both ours to feed):**
1. **List must populate.** Button stays "Loading Servers" until the client holds a
   non-empty village server list ⇒ our `GetServers(171)`/`GameServerData(170)` for the
   village (ServerType=4) must deserialize cleanly. If 170 layout is off, the list never
   fills → permanent grey. (Matches old hypothesis #1.)
2. **Selected RoomId must match.** Even when listed, entering needs an entry whose
   RoomId/LobbyId (`entry+0x30`) equals the client's selected `DAT_0087d580`. Mismatch ⇒
   "could not connect to village." (This is the same shape as the DNG **version/LobbyId
   9212 filter** warning — register the village entry with the id the client expects.)

**Next test:** send a byte-perfect ServerType=4 `GameServerData(170)` whose LobbyId/RoomId
matches the client's expected value (try **9212**), watch whether the button text flips
`LOADING_SERVERS → ENTER_VILLAGE`. Confirm the predicate by recovering the `0x4682d0`
jump table in Ghidra (it should be "list count > 0").

Village state machine (`LobbyManager+0x57c`, via `FUN_00462bc0`):
`Authorized → VersionChecked → GlobalDataLoaded → EnteringVillage → VillageEntered`.
The separate village socket is opened by `FUN_00463750 CreateVillageServerConnection`
(`LobbyManager+0x540`).

---

## 🔌 LIVE GHIDRA s4 (2026-06-01) — MCP connected, structs typed, state machine mapped

Connected Claude → Ghidra 12.1 live via **bethington/ghidra-mcp**. Applied directly into
the SADK.exe project (saved):
- **Created** enum `LobbyManagerState` (1 Disconnected … 8 EnteringVillage → 9 VillageEntered
  … 12 ConnectionLost) and structs `LobbyManager` (0x580) + `LobbyVillageScreen` (0x21d) with
  the mapped fields; `__thiscall` prototypes on the 6 village funcs (NB: Ghidra can't retype
  the auto-ECX `this` via API — field map captured in `UpdateEnterButton`'s plate comment).
- **State machine pinned** (state @ `LobbyManager+0x57c`):
  - `LobbyManager::GetState` @ `004626f0`, `LobbyManager::SetState` @ `00462700`
    (**latches** — once state==12 ConnectionLost it won't change).
  - Login sequence sets literals 1→7 in `FUN_00462fe0/004632f0/00463910/00464b90/00464c00…`.
  - **No inline `=8`** anywhere ⇒ EnteringVillage is set via `SetState(8)` with a passed value.
    `FUN_00470f10` checks `state==9` (VillageEntered).
- **Entry trigger found:** `CreateVillageServerConnection` has ONE caller, `FUN_00503da0`
  ("EnterVillage" action). It calls `CreateVillageServerConnection(lobbyManager,
  g_dwInvalidVillageServerId)` → passes **-1**, so the connection uses the *currently selected*
  server (`GetSelectedVillageServer`).
- **Sentinel decoded:** `DAT_007dc51c` = `g_dwInvalidVillageServerId` (= -1). This makes
  `FUN_00468140(serverList)` = `selectedServer(+0x80) != -1` → "**a server is selected**"
  (the 2nd enable condition).
- **Boundary:** `IsListReady @ 0x4682d0` is an unrecovered jumptable thunk (`_DAT_012f161c`
  filled at load time, zero code writes) — needs manual jumptable recovery or a debugger BP.

**Next live thread:** find which caller of `LobbyManager::SetState` passes **8** (EnteringVillage)
— that's the exact client trigger to satisfy. Then confirm the button-enable still reduces to
"valid ServerType=4 list received + a server selected with matching LobbyId."

---

## 🎯 s5 (2026-06-01) — WHAT THE SERVER MUST DO to enter the village (traced live)

Followed the state machine to the trigger. **There are THREE connections, and the 3D
village world is entered over a THIRD one** (separate from lobby:7070 and chat:7071):

1. **Lobby conn** sends a **ServerType=4 `GameServerData(170)`** "village" entry (valid
   Ip/Port, matching LobbyId) → populates `LobbyVillageServerList` → button ungreys once
   `IsListReady` && `HasServerSelected` (selected `!= -1`).
2. Click → **`CreateVillageServerConnection`** opens a **new TinCat connection to that
   entry's Ip/Port** (the *village server*) → `SetState(EnteringVillage=8)` (orphan
   jumptable block @`0x47043c`).
3. **The village server must send village-protocol message `1000` (0x3E8)** →
   `VillageServerConnection::HandleEnterWorld` (@`0046f470`) parses a **named property bag**:
   `Worldname`, `ServerPerm` (~0x20 bytes), `ChatChannelsCount`, then per channel
   `ChatChannelZone` + `ChatChannelID` → `SetState(VillageEntered=9)` → **client loads the
   3D world.**

Village dispatcher = `VillageServerConnection::HandleMessage` @`00470890` (msg type via
`FUN_005025e0`). Other types: 1001-1006 (0x3E9-0x3EE), 0xD8-0xDC, 0xC1C-0xC1E, 0xC80/0xC81,
0xE11/0xE1B/0xE25/0xED7/0xF46/0xF5A. LoggedOut/Disconnected → `SetState(VillageLeft=11)`.

**PATCH PLAN (next):** extend `tincat_server.py` to (a) advertise a ServerType=4 village
entry pointing at a local port, (b) accept a 3rd TinCat connection on that port = the
village server, (c) on the village handshake, send msg **1000** with the property bag above.
Then test in-game: does the client leave character-select and load the village world?

**RESOLVED (s5b):**
- **Wire format of msg 1000** = plain little-endian, positional (NOT a named bag — the
  `"Worldname"` etc. strings are debug labels via `FUN_0048ecd0`, a logger gated on a debug
  flag). Confirmed against emulator `S2Library/Protocol/Serializers.cs`:
  - string = `int32 len` + `len` bytes, **ISO-8859-15**, len INCLUDES a trailing `\0` on write
    (len 0 ⇒ null ⇒ client shows `<UNNAMED>`).
  - int/uint = 4 bytes LE; bool/byte = 1 byte; short/ushort = 2 LE.
  - `HandleEnterWorld` reads: `Worldname:string`, `ServerPerm:u32`, `ChatChannelsCount:u32`,
    then N×(`ChatChannelZone:u32`, `ChatChannelID:u32`). `SetState(VillageEntered=9)` fires on
    RECEIPT (before the body is read), so a well-framed 1000 with count=0 is enough to enter.
- **Handshake EXISTS and gates 1000.** Village conn vtable @`0x7dc8e0`:
  `HandleLoggedIn`@`0046d820`, `HandleLoginFailed`@`0046d910`, `HandleMessage`@`0470890`,
  `HandleLoggedOut`@`0470c20`, `HandleDisconnected`@`0470d90`. So the village conn does a
  TinCat handshake → village LOGIN → LoggedIn, THEN the server sends 1000. Exact login
  exchange not yet reversed — **fastest to discover empirically**: implement the scaffold and
  let the stub LOG what the client sends on the village port (same approach that mapped the
  lobby).

**Village protocol message ids** (decimal): 1000 EnterWorld; 1001-1006 (0x3E9-0x3EE);
216-220 (0xD8-0xDC); 0xC1C-0xC1E, 0xC80/0xC81, 0xE11/0xE1B/0xE25/0xED7/0xF46/0xF5A.

---

## 🧪 s6 (2026-06-01) — VILLAGE SERVER PATCH applied to tincat_server.py (READY TO TEST)

Implemented the "scaffold + log + speculative 1000" village server. The stub already
advertised ServerType=4 @127.0.0.1:**5479** and already listened there; the patch makes
that 3rd connection a **village** connection:
- `village_enter_world()` builder → `app_payload(1000, Worldname:str + ServerPerm:u32 +
  ChatChannelsCount:u32)`. Byte-verified: `b6 26 | e8 03 e8 03 | 0d000000 'SaDK Revival\0' |
  00000000 | 00000000`.
- `Conn(is_village=True)` for the `world` listener: logs EVERY incoming app frame raw
  (`[VILLAGE] ← app frame magic=.. type1=.. type2=..` + hexdump), and ~0.5s after the
  village TinCat handshake sends EnterWorld(1000).
- Framing magic is a GUESS (0x26B6); the logged client frames will confirm/correct it.

**TEST PROTOCOL (Windows box, game + stub together):**
1. `LobbySettings.ini` → `Host = "127.0.0.1"`; `pip install cryptography twofish`;
   `python tincat_server.py` (admin if 7070 needs it).
2. Launch SADK, log in test/test/test, reach character select, try to enter the village.
3. Watch console + `tincat_server.log`:
   - **Does the client open the village conn?** Look for `CONNECTION #N` on the **world**
     listener + `[VILLAGE] handshake done`.
     - **NO village conn** ⇒ the **button is still greyed** — blocker is upstream
       (`IsListReady` predicate / list not ready), NOT the village protocol. That becomes
       the next target (recover the `0x4682d0` jumptable / fix the ServerType=4 entry).
     - **YES** ⇒ read the `[VILLAGE] ← app frame` lines = the client's village LOGIN
       sequence (and the real magic). That's what we implement next.
   - Did our `[VILLAGE] sent EnterWorld (msg 1000)` cause the 3D world to load, an error,
     or a disconnect / `LoginFailed`?
4. Save `sadk_captures/world_*.bin` + `LobbyComm.log` for the next iteration.

---

## 🛠️ s7 (2026-06-01) — ROOT CAUSE found in game logs: 170 rejected by TinCat. Two fixes.

The village patch "changed nothing" because the blocker is UPSTREAM and was there all along.
Game logs (`C:\tmp`) are the ground truth:
- **`commLayer.log`**: `ConnectionReal was unable to deserialize packet 170` (×2) →
  `connectionReal.SendData: Unable to send data`. **TinCat itself rejects our
  GameServerData(170).** ⇒ server list never reaches the game.
- **`LobbyComm.log`**: then `TinCat failed to start connection` (LobbyManager.cpp:907 — the
  2nd/chat connection) and, on entering village, `LobbyVillageServerList.cpp:116 → Interner
  Serverfehler: Datenbankfehler/Verbindungsabbruch`. All downstream of the empty/broken list.

**Why 170 fails (tincat3.dll, reversed):** packets are deserialized by
`PropertyDataConverter::DeserializeProperty` against a fixed per-type SCHEMA — var-len fields
(string/blob) = 4-byte length prefix + bytes; scalars = fixed size. The 170 schema is
**ServerInfoOld** (uint16 player counts + spectators + subtype + roomid + locked_config). Our
default was `GAMESERVERDATA_FORMAT="adk"` (byte counts, no spectators) → stream desyncs → a
later string length overruns → deserialize returns 0 → the logged error. **The emulators'
"adk" layout is wrong for the real client; the s2 switch to "adk" introduced this.**

**FIXES applied to tincat_server.py (syntax-checked, validated vs captured bytes):**
1. `GAMESERVERDATA_FORMAT = "old"` (ServerInfoOld = the real TinCat schema).
2. `GetServers(171)` parse restored to 17 bytes: SendAll, ServerType, LobbyId, **Level,
   GameMode, Hardcore**, Selection, TicketId. (The s2 parse dropped the middle 3 bytes →
   TicketId mis-read as 0x04000000; now reads 4/5 correctly, so we echo the right ticket.)

**RETEST — watch `C:\tmp\commLayer.log` FIRST:** the `unable to deserialize packet 170` lines
should be GONE. If so, the server list should populate → "Suche Server…" should ungrey, the
chat (7071) connection should start (no more "TinCat failed to start connection"), and on
Enter the client should finally dial the village (5479 → our `[VILLAGE]` log fires). If 170
STILL fails to deserialize, the exact ServerInfoOld field sizes need tweaking — next step is
to reverse the type-170 property schema from SADK.exe via the live link.

---

## ✅/🚧 s8 (2026-06-01) — 170 fix CONFIRMED; blocker is now the chat 2nd-connection

Retest after s7 fixes:
- **WIN: the `170` deserialize errors are GONE from `commLayer.log`.** `GAMESERVERDATA_FORMAT="old"`
  (ServerInfoOld) is accepted by the real TinCat DLL. The `171` parse fix also confirmed
  (TicketId now 4/5). So the server-list path is fixed.
- **Remaining blocker (pre-existing, all sessions): the LobbyComm SECOND connection fails to
  start.** `LobbyComm.log`: `LobbyManager.cpp:907 → TinCat failed to start connection` (×2,
  `FUN_00464740` = `LobbyComm::System::LoginFailed`); `commLayer.log`: `connectionReal.SendData:
  Unable to send data`. Our server log shows NO connection ever reaches the 7071 (chat) or 5479
  (village) listeners — only repeated 7070 (lobby) connections that complete login then drop
  ~14s later. So the 2nd connection never even establishes client-side.

**Leading hypothesis:** TinCat refuses/fails to open a SECOND connection to the same IP
(127.0.0.1) from the one client process (s2 already noted it refuses same host:port; this
suggests same-HOST too). That would block chat AND village locally regardless of port.
Confirmed s8: the 7071 listener IS bound (console shows it) and reachable, yet the client
never connects — so the failure is on the client's outbound *start*, not our listener.
NEXT: reverse the tincat3.dll connect path for a same-host/local-port constraint; and TEST by
pointing the chat-server address (our `192` response Ip) at the host LAN IP **192.168.1.134**
instead of 127.0.0.1 (our listeners bind 0.0.0.0, so they still catch it).

> ✅ RELEASE IMPLICATION — RESOLVED (s8): **No same-IP constraint exists.** TinCat's TCP connect
> `NET_Connect` (`tincat3.dll FUN_10033310`) does `socket(AF_INET,SOCK_STREAM)` → `connect()` with
> NO `bind()` to a fixed local port, so 2nd/3rd connections to 127.0.0.1 are fine. (The fixed-port
> `bind` is only on the UDP broadcast/LAN-discovery socket, `FUN_10032e10`.) ⇒ single-box,
> all-127.0.0.1 revival is viable; no LAN-IP/loopback-alias/DLL-shim needed for the 2nd connection.

**So why does the 2nd connection fail?** It fails IMMEDIATELY (same second as 189/192) with
CANNOT_CONNECT. **netstat (s8) confirms:** SADK.exe has ONLY `127.0.0.1:62669→127.0.0.1:7070`
(lobby, ESTABLISHED) + two `→34.149.87.45:443` HTTPS (Google-Cloud; likely telemetry/ranking/
DRM, NOT the lobby). **No chat(7071)/village(5479) socket at all, and nothing in SYN_SENT** —
so the 2nd connection fails so fast it never lingers; on loopback that means either instant
refuse OR (more likely, given no SYN catchable) the connect fails BEFORE a SYN = a bad/empty/
unsplit target address handed to TinCat. We DO send a well-formed `192` (127.0.0.1:7071) and
TinCat accepts it (no "deserialize 192" error), so the game receives a valid Ip/Port — yet the
connect dies pre-SYN. ⇒ the chat-connection-start either ignores our `192` Ip/Port or mangles
it (e.g. treats "host:port" as one hostname).

**CAPTURE (s8, capture.pcapng, loopback) — DECISIVE:** SADK makes exactly ONE loopback SYN:
frame 734 `127.0.0.1:59060→127.0.0.1:7070` (lobby). **No SYN to 7071 or 5479 anywhere.** (Noise:
`→127.0.0.1:28194` poll + `57747↔57748` are other apps.) ⇒ the 2nd connection emits NO packet
= fails BEFORE the TCP connect = **bad/empty target host**, not a refusal.

**REVERSED the connect path (s8):** `FUN_0048d730` = `LobbyComm::BaseConnection::Connect`
(shared base; in 5 connection vtables — village `0x7dc8e0`, plus `0x7dd1bc/0x7dded8/0x7df8d8/
0x7dfafc`, one of which is chat/UC). It reads **host = string at descriptor+4** (`FUN_0048e980`
→ `FUN_00408340(desc+4)`) + port (`FUN_0048e710 & 0xffff`) and calls comm `vtable+0x1c`
(create-connection). Empty host ⇒ async connect dies pre-SYN ⇒ `BaseConnection::LoginFailed`
(line 119) ⇒ `System::LoginFailed` (line 907). **So: the chat connection's descriptor host is
EMPTY when Connect runs.** Bug is in the chat-connection SETUP (builds the descriptor) — it's
not copying the host from our `SendChatServerInfo(192)` Ip (or from wherever the host belongs).

**CHAT CONNECTION IDENTIFIED + REFRAMED (s8):** the chat/2nd connection is
**`LobbyComm::UserCommConnection`** (`LobbyUserCommConnection.cpp`, vtable `0x7dded8`; methods:
Initialize@0x47ed90, LoggedIn@0x47ef50, ReceivedData@0x47f310, ChatChannelListReceived@0x47f400,
JoinChannel@0x47fca0, **OpenCommunication@0x47fb40**, …). Other conn classes: GameServerConnection
(`0x7dfafc`, LobbyGameServerConnection.cpp), VillageServerConnection (`0x7dc8e0`).

Open path: `FUN_00470b50` → `UserCommConnection::OpenCommunication` (`0x47fb40`) → comm
`vtable+0x10`(handle). The handle = `LobbyManager+0x548` (via `FUN_004626c0`).

**KEY:** `LobbyManager+0x548` is set by **`LobbyComm::System::LoggedIn` (`FUN_00463910`)**: when the
MAIN lobby connection logs in, it does `+0x548 = param_2; state = 3 (Authorized)`. So the chat
server handle is whatever the **main-connection login event carries as `param_2`** — it does NOT
come from our `GetChatServer(189)→192` response (that's a red herring for the chat conn). On
failure `System::LoginFailed` resets `+0x548` to sentinel `DAT_007dc528`.

⇒ The chat connect has an empty host because the handle at `+0x548` (from login `param_2`)
resolves to no address. NEXT: determine what `param_2` is (what the comm/`tincat3.dll` LoggedIn
event supplies) and what `comm vtable+0x10`(handle) does with it to get an address — i.e. what
our login flow must provide so the UC connection has a real target. (Our `192` likely isn't the
lever; the login reply / comm server-handle is.)

**`network.ini` (`game/settings/network.ini`) — investigated (user flagged it):**
`FUN_0041f0d0` (`NComm::Manager::StartUpNetwork`, Manager.cpp) parses it via
GetPrivateProfileInt/String into the engine config at `NComm::Manager+0x360`:
- `[Basics] gamePort` (def 5479), `[Broadcast] broadcastPort` (def 6582), reconnector timings.
- **`[Lobby] url`** (string, config+0x2c) default **`"81.3.59.139:8777"`** — the REAL original
  online lobby/master server. This is the **engine/NComm** subsystem, SEPARATE from the
  LobbyComm lobby (`LobbySettings.ini` → 127.0.0.1:7070, which works). User set it to
  `127.0.0.1:7071` = our CHAT port, which is almost certainly the wrong target for NComm.
- **`[Lobby] patchlevel`** (def 0x2a=42) → set 9212. ✓ correct (matches client version filter).
NB: couldn't cheaply pin exactly what NComm connects `url` to (offset +0x38c is reused by many
structs); it's likely a later/matchmaking endpoint, not the current LobbyComm blocker.

---

## 🧩 s9 (2026-06-01, autonomous) — UC/chat connection fully mapped; needs a debugger next

Deep-dived the chat (2nd) connection while user was away. Renamed ~17 funcs + 2 plate
comments into the Ghidra project (saved). Net: the architecture is now fully mapped, and
the remaining unknowns are RUNTIME values — a debugger is the right next tool.

### Connection class map (all in SADK.exe, share LobbyBaseConnection base)
| Class | vtable | source file | role |
|-------|--------|-------------|------|
| `LobbyBaseConnection` | — | LobbyBaseConnection.cpp | base: `Connect`@0x48d730 (→ comm `vtable[0x1c]`(port,ip,x)), `OnLoggedIn`@0x48d8b0, `OnLoginFailed`@0x48d9d0, `OnDisconnected`@0x48dc20 |
| `UserCommConnection` (**chat/UC**) | `0x7dded8` | LobbyUserCommConnection.cpp | `Initialize`@0x47ed90, `OpenCommunication`@0x47fb40, `JoinChannel`@0x47fca0, `On{LoggedIn 0x47ef50, LoginFailed 0x47f040, ReceivedData 0x47f310, ChatChannelListReceived 0x47f400, …}` |
| `GameServerConnection` | `0x7dfafc` | LobbyGameServerConnection.cpp | `OnLoggedIn`@0x48e650 |
| `VillageServerConnection` | `0x7dc8e0` | LobbyVillageServerConnection.cpp | `HandleMessage`@0x470890 (msg 1000=EnterWorld), Handle{LoggedIn 0x46d820, LoginFailed 0x46d910, LoggedOut 0x470c20, Disconnected 0x470d90} |
| (main lobby conn) | `0x7dd1bc` or `0x7df8d8` | — | uses base handlers; the lobby msg dispatch wasn't a clean switch (CStaticController @0x519xxx is UI, not it) |

`LobbyManager` (class `LobbyComm::System`, LobbyManager.cpp): `Login`@0x462fe0, `OnLoggedIn`@
0x463910, `OnLoginFailed`@0x464740, `GetState`@0x4626f0, `SetState`@0x462700, `GetChatServerHandle`
@0x4626c0 (returns +0x548), `CreateVillageServerConnection`@0x463750.

### The chat-connection flow (reconstructed)
1. Main lobby (7070) login completes → comm fires `LobbyManager::OnLoggedIn(connId, param_2)`.
   For the MAIN conn it does `chatServerHandle(+0x548) = param_2; state = Authorized(3)`.
2. UC connection opened by `UserCommConnection::OpenCommunication(0x47fb40)` (triggered via
   `FUN_00470b50`), connecting to the handle `GetChatServerHandle()` (+0x548) through comm
   `vtable[0x10]`(handle).
3. **The chat target = `param_2` from login — NOT our `GetChatServer(192)` reply.** (Our 192
   ServerId=1/Ip/Port is byte-identical to the AdK emulator's `HandleGetChatServer`, so 192
   content is correct and not the blocker.)
4. Capture proved the UC connect emits NO SYN ⇒ the handle resolves to no address ⇒ empty
   target. So either OpenCommunication isn't reached, or `param_2`/the comm handle→address
   resolution yields nothing.

### STATIC CEILING (why I stopped)
`param_2`'s value is set at runtime by the comm; `comm vtable[0x10]`'s handle→address logic is
inside `tincat3.dll` (vtables are data, not in the SADK decompile). Neither is resolvable by
reading SADK.exe statically. The AdK emulator never got chat working either (no reference).

### ⭐ NEXT = DEBUGGER (the ghidra-mcp fork has debugger_* tools; needs game running + user)
Launch/attach SADK.exe under the Ghidra debugger and set breakpoints (see `decomp/DEBUGGER_PLAN.md`):
- **FIRST: `0x464740` `LobbyManager::OnLoginFailed`** — read `param_1` (failed conn id), compare
  to slots `+0x540/+0x544/+0x490/+0x3d8/+0x50`. ⚠️ The post-login failing connection is NOT
  confirmed to be the chat/UC one — after `Authorized(3)` the client also does
  `LoadingGlobalData(6)` (may have its own conn). Identify which connection fails before assuming.
- **`0x463910` `LobbyManager::OnLoggedIn`** — read `param_2` (stack) when the MAIN conn logs
  in. That's the chat handle. Is it null/0, a small id, or a pointer? This is THE value.
- **`0x47fb40` `UserCommConnection::OpenCommunication`** + **`0x470b50`** — are they even hit?
  (If never hit ⇒ the UC open isn't triggered — a logic gate, not an address bug.) If hit,
  read the `param_1` handle + step into comm `vtable[0x10]` (into tincat3.dll) to watch the
  handle→address resolution and where it goes empty.
- **`0x4626c0` `GetChatServerHandle`** returns `+0x548` — confirm the value used.
Then we know exactly what the login must provide (or what extra step triggers the UC open).
Alt (no debugger): open tincat3.dll in Ghidra and reverse `CommLayer::ConnectionManagerINet`
`vtable[0x10]` to learn the handle→address mapping statically.

---

## ⭐ RESUME HERE (read this first — written end of session 2)

**THE GOAL, narrowly:** get the client past the greyed **"Suche Server…"** button and
into the **3D lobby world**. We are stuck *before* entering the world. Everything about
the server browser / host / join / NAT bridge is DOWNSTREAM — ignore it until we're in.

**What changed this session (in `tincat_server.py`) — all UNTESTED, needs the Windows box:**
1. **Chat (UC) second connection implemented.** Port 7071 listener is now flagged
   `is_chat=True`. On TinCat handshake it immediately PUSHES `ChannelInfo` for 2 channels
   (id 1 "System", id 2 "Lobby") — this mirrors `ChatProcessor.HandleInitialReply`, the
   thing the client waits for. Added chat-magic `0x0062` framing + builders
   (`ChannelInfo/ChatReply/CreateChannel/ChannelJoined/StatusReply/ChannelData`),
   `JoinChatChannel(17)` → Joined+StatusReply+ChatUserInfo, `VerifyChatLogin(213)` →
   `StatusWithId(153)` (was wrongly sending 42), fixed 213 parse (`PermId+Cipher+TicketId`).
2. **`GetServers(171)` parser fixed** to AdK layout: `SendAll+ServerType+LobbyId+Selection+TicketId`.
3. **`GameServerData(170)` format toggle** `GAMESERVERDATA_FORMAT` (top of file).
   Default now `"adk"` (byte player-counts) — confirmed correct by BOTH emulators.
   `"old"` = ServerInfoOld (uint16+spectators) = wrong for this client family.

**WHY the button is probably gated on the chat connection:** the captures show the game
DOES dial the second connection but it *failed* — because our 7071 listener was speaking
the lobby protocol and never pushed `ChannelInfo`. The chat connection is AdK-SPECIFIC
(DNG/S2-10th does chat on the main socket and has no second connection). Fix is in place.

**ALSO likely relevant:** the earlier fake `ServerType=4` lobby-world entry test left the
button grey, but it was sent in the WRONG 170 layout (ServerInfoOld). With the `"adk"`
byte-format now default, re-running that test is worthwhile on its own.

**NEXT ACTIONS, in order:**
1. **Run the stub, log in (test/test/test), reach character select.** Watch log for:
   `CONNECTION #2` on `uc` listener → `[CHAT] pushed 2 ChannelInfo on connect` →
   client `LoginChat(211)` → `VerifyChatLogin(213)` → `JoinChatChannel(17)`. Does the chat
   socket now STAY UP (instead of dropping)? Does "Suche Server…" un-grey?
2. If still stuck, capture the new `sadk_captures/uc_*.bin` and `LobbyComm.log`
   (`-log_info -log_path ...`) at the stuck moment.
3. **Decode the REAL captures** (game-independent, do anytime) with the new tool:
   ```
   python decode_lobby_capture.py Settlers-AdK-lobby-emulator\data\tincat_lobby_onlineconnect.bin > capture_dump.txt
   python decode_lobby_capture.py Settlers-AdK-lobby-emulator\data\tincat_localhost.bin >> capture_dump.txt
   ```
   `tincat_lobby_onlineconnect.bin` = real client entering the online lobby (11 framed
   msgs after login, offsets 880–2259 per its `.rehex-meta`). `tincat_localhost.bin` =
   localhost lobby. These show the EXACT entry handshake — decode them to stop guessing.
   (Claude can read `capture_dump.txt` directly; it can't read the raw `.bin` — file tools
   refuse binary and the sandbox VM was broken all session, see infra note below.)

**GHIDRA EXPORT (incoming next session):** a large HTML decompiler export is being added.
HTML is text → analyze with Grep/Read directly (no VM needed). High-value grep targets for
lobby-world entry: `LobbyVillageServerList` (seen in LobbyComm.log), the "Suche Server"
button enable/disable logic, the chat/UC second-connection setup + what it waits on,
`ServerType`==4 handling, the version/`LobbyId` server-list FILTER (the shared "dll hack"
compare site), and consumers of `GetChatServer`/`SendChatServerInfo` and
`ConnectToServer(221)`/`PlayerConnecting(223)`.

**INFRA NOTE (why session 2 couldn't run code):** the bundled Linux sandbox VM failed to
boot all session with `EXDEV: cross-device link not permitted` renaming
`...\Claude\vm_bundles\claudevm.bundle\.wvm-tmp-*\rootfs.vhdx`. Root cause: Claude was
installed such that the vm_bundles path crossed a volume boundary. **Fix = reinstall Claude
to the C: drive** (single volume). After that the VM should boot and Claude can hexdump
binaries + run Python directly again. Project files live in `Downloads\sadk_decoder` and
survive the reinstall; this chat context does not.

**DEAD ENDS (do not retry):** `-localhostmode` is an in-process walk-around test with no
socket to bridge. SADK.exe won't run two instances on one machine. Real 2-player testing
needs two physical machines. (Details in "Next Steps to Try" below.)

---

## UPDATE 2026-06-01 (session 2) — Chat second-connection implemented

**Root-cause finding.** The greyed "Suche Server…" button is gated on the **second
(chat/UC) connection**, which the game *does* dial (confirmed: "dials but fails") but
which our stub answered with the wrong protocol. Three facts from the authoritative
C# emulator (`Settlers-AdK-lobby-emulator/`):

1. The chat connection is a **separate TinCat listener** (emulator: lobby `6800`,
   chat `6802`). A connection there is bound to `ChatProcessor`, not `LobbyProcessor`.
2. **Chat messages use a different wire prefix:** magic `0x0062`, layout
   `Magic(u16)+Type(u16=0)+Id(u16=chatType)` — *not* the lobby `0x26B6+Type1+Type2`.
   (`S2Library/Protocol/ChatPayloads.cs`)
3. **The server must PROACTIVELY push `ChannelInfo` the instant the chat handshake
   completes** (`ChatProcessor.HandleInitialReply` → one per channel). The client
   waits for this. Our stub was purely reactive → the chat socket stalled and dropped.

**What changed in `tincat_server.py` this session:**
- Chat listener (port 7071, label `uc`) now flagged `is_chat=True`; on TinCat
  handshake it immediately pushes `ChannelInfo` for two channels (id 1 "System",
  id 2 "Lobby"), matching `Channels.cs` seed data.
- Added chat-magic (`0x0062`) framing + builders: `ChannelInfo(0)`, `ChatReply(3)`,
  `CreateChannel(7)`, `ChannelJoined(9)`, `StatusReply(11)`, and `ChannelData`.
- `JoinChatChannel(17)` → `ChannelJoined` + `StatusReply` + self `ChatUserInfo`
  (wrapped in `ChatReply`, inner serialized header-less, exactly as `ChatProcessor`).
- `VerifyChatLogin(213)` now replies `StatusWithId(153)` (was wrongly sending `42`);
  fixed `213` parse to `PermId + Cipher + TicketId`.
- Fixed `GetServers(171)` parse to the AdK layout
  `SendAll + ServerType + LobbyId + Selection + TicketId` (TicketId was misaligned).
- `GameServerData(170)`: both layouts now selectable via `GAMESERVERDATA_FORMAT`
  (`"adk"` byte-counts = emulator default, or `"old"` = ServerInfoOld). Default `adk`.

**NEXT TEST (on the Windows box):** start `python tincat_server.py`, log in
(test/test/test), reach character select. Watch the log for:
`CONNECTION #2` on the `uc` listener → `[CHAT] pushed 2 ChannelInfo on connect`
→ client `LoginChat(211)` → `VerifyChatLogin(213)` → `JoinChatChannel(17)`.
If that whole chat handshake completes and the chat socket stays up, check whether
"Suche Server…" un-greys. If the chat socket still drops, capture the new
`sadk_captures/uc_*.bin` and `LobbyComm.log` for the next pass.

---

## What Works

### TinCat3 Protocol — Fully Reversed
- **28-byte frame header:** Magic(4) + From(4) + To(4) + Type(4) + Unknown1(4) + PayloadSize(4) + Checksum(4)
- **Magic:** `0xDABAFBEF` (EF FB BA DA)
- **From client:** `0xEFFFFFEE`, **From server:** `0xEFFFFFCC`
- **Frame types:** 3=HandshakeConnect, 5=HandShakeConnected, 2=ApplicationMessage, 11=Ping
- **Checksum:** CRC32 starting at 0 (NOT 0xFFFFFFFF, NOT inverted)
- **Handshake payload:** 52 bytes — Magic(4) + ConnectionId(4) + Username[32] + Password[8] + Unknown1(4)
  - Machine username is always `"user"` (hardcoded in game)
  - Machine password = serial number, null-padded to 8 bytes
  - Server reply password = `{ 0x2D, 0x00 × 7 }`

### Authentication — Fully Working
- **ECDH key exchange** (secp521r1) implemented in Python using `cryptography` library
- Custom DER format: `SEQUENCE { BITSTRING(7 unused, 0x00), INTEGER(0x41), INTEGER(x), INTEGER(y) }`
- Server generates ephemeral keypair, performs ECDH, hashes with SHA-512, XORs with 32-byte random secret
- Response DER: `SEQUENCE { OID(SHA-512), OCTET_STRING(server_pubkey), OCTET_STRING(xored_secret) }`
- **Credential decryption** (Twofish-CTR) working — blob format: `nameLen(1B) + name + pwdLen(1B) + pwd`
- Successfully decrypted `username='test'`, password raw bytes confirmed

### Post-Login Flow — Mostly Working
All these messages are handled and the game proceeds through them:
| Type | Name | Status |
|------|------|--------|
| 188 | VersionCheck | ✓ → ResultStatusMsg OK |
| 201 | Login (ECDH) | ✓ → LoginReply (202) |
| 204 | LoginUser | ✓ → LoginReplyCipher (207) perm_id=1 |
| 161 | PropertyGet | ✓ → PropertyData (162) + OK |
| 171 | GetServers (×2) | ✓ → GameServerData(170) + OK |
| 105 | RequestMOTD | ✓ → SendMOTD (106) |
| 55  | GetPlayerInfo | ✓ → SendPlayerInfo (60) + OK |
| 189 | GetChatServer | ✓ → SendChatServerInfo (192) |
| 56  | RequestUserBuddyList | ✓ → OK |
| 157 | RequestUserIgnoreList | ✓ → OK |

### Character Selection Screen — Working
- CHARAKTERAUSWAHL screen loads correctly
- Character "Testler" (Level 1, 1000pts) renders in 3D in the townhall library
- Avatar data blob (`NICKNAME_DATA`) from emulator works for AdK

---

## Where We're Stuck

### The "Suche Server..." Button
After login, the character selection screen shows. There's a button to enter the lobby world labeled **"Suche Server..."** (Searching for Server). It is greyed out.

**What we've tried:**
- Sending a fake `GameServerData` (TYPE 170) entry with `ServerType=4` → button still grey
- Multiple field order variations for the payload

**Current hypothesis — three candidates:**
1. **`GameServerData` still serializes wrong.** Even with the corrected field order from `Payloads.cs`, something may not parse on the game side. No CRC or parse error is visible from our side.
2. **The game requires a working second TCP connection.** We respond to `GetChatServer` (TYPE 189) with `127.0.0.1:7070`. The game should open a second TinCat connection for the UC/chat layer. We never see `CONNECTION #2` in our logs — the game may not be opening it (or it opens and fails silently).
3. **The lobby world server must actually be running.** ServerType=4 may correspond to a game instance (port 5479) running the 3D lobby world engine. The game might do a connection probe before enabling the button. This server would be another SADK.exe instance running as a dedicated lobby world host.

### `GameServerData` Correct Field Order (from `Payloads.cs`)
```
ServerId(uint32) Name(str) OwnerId(uint32) Description(str) Ip(str) Port(uint32)
ServerType(byte) LobbyId(uint32) Version(str)
MaxPlayers(byte) CurPlayers(byte) AiPlayers(byte)
Level(byte) GameMode(byte) Hardcore(bool=1B) Map(str) Running(bool=1B)
Data(bytes) TicketId(uint32)
```
Note: MaxPlayers/CurPlayers/AiPlayers are **bytes**, not uint16. No PasswordRequired, no MaxSpectators/CurSpectators, no LockedConfig.

### `RegisterServer` Correct Field Order (from `Payloads.cs`)
```
Name(str) Description(str) Port(uint32) ServerType(byte) LobbyId(uint32)
Version(str) MaxPlayers(byte) AiPlayers(byte) Level(byte) GameMode(byte)
Hardcore(bool) Map(str) AutomaticJoin(bool) Data(bytes) TicketId(uint32)
```
Note: No Ip, no Localip, no Cipher, no ServerSubtype, no RoomId, no LockedConfig.

---

## Key Files

| File | Purpose |
|------|---------|
| `tincat_server.py` | Full stub server — run with `python tincat_server.py` (now incl. chat conn) |
| `decode_lobby_capture.py` | NEW (s2): walks raw TinCat `.bin` captures, labels frames, decodes 170. `python decode_lobby_capture.py <file.bin> [--dng]` |
| `lobby_proxy.py` | Passive traffic capture proxy (older tool) |
| `analyze_capture.py` | Offline binary capture analyzer |
| `LOBBY_PROTOCOL.md` | Full protocol reference (262 message types) |
| `Settlers-AdK-lobby-emulator/` | C# AdK lobby emulator — authoritative field defs (`S2Library/Protocol/Payloads.cs`, `ChatPayloads.cs`; `S2Lobby/src/Core/LobbyProcessor.cs`, `Chat/ChatProcessor.cs`, `Core/Program.cs`) |
| `Settlers-DNG-lobby-emulator/` | NEW (s2): Go emulator for S2-10th predecessor. MOST COMPLETE ref (create/join/launch-lobby work). `src/network/network.go`, `src/packages/packages.go`, `API.md`. Magic 0x27D8. |
| `*/data/*.bin` + `.rehex-meta` | Real captured TinCat traffic (login, lobby connect, 170/171, createGame). Decode with `decode_lobby_capture.py`. |

**Test credentials:** username=`test` / password=`test` / serial=`test`  
**Config:** `data/lobby/config/LobbySettings.ini` → `Host = "127.0.0.1"`  
**Dependencies:** `pip install cryptography twofish`

---

## Architecture Understanding

```
SADK.exe (game client)
    │
    │ TCP port 7070  (TinCat protocol)
    ▼
[Our stub server]  ← tincat_server.py
    │
    │ GetChatServer response → 127.0.0.1:7070
    │ (game should open second connection for UC/chat)
    │
    ▼ (MISSING: second connection never appears in logs)
[UC/Chat server]  ← S2BridgeController? separate service?
    │
    │ TCP port 5479  (game P2P / lobby world)
    ▼
[Lobby world server]  ← another SADK.exe instance? dedicated server?
```

The `-localhostmode` flag runs the lobby world server in-process (no network). For real multiplayer, the lobby world server needs to be a separate process with network access.

> **Correction (2026-06-01 s2):** `-localhostmode` is an internal walk-around-the-lobby
> test only — it exposes no socket and can't be bridged. And SADK.exe won't run two
> instances on one machine, so "host on A / join on B" is impossible locally. Real
> two-player testing requires two separate machines. The lobby world is entered over
> the live lobby+chat connections, not by spinning up a second local game host.

---

## Developer Flags Discovered in SADK.exe

| Flag | Effect |
|------|--------|
| `-localhostmode` | In-process lobby (no network, UI testing only) |
| `-lobbyfast` | Lobby fast mode (effect unclear) |
| `-nolobby` | Skip lobby entirely |
| `-mptest` | Dead code — sets global but nothing reads it |
| `-start <map>` | Auto-start map (requires game session to exist first, crashes without it) |
| `-map <map>` | Sets background/preview map |
| `-net <value>` | Network override (stores string at config+0x8C) |
| `-log_path <path>` | Log file path |
| `-log_info` | Verbose logging |
| `-log_warn` | Warning-level logging |
| `-log_error` | Error-level logging |
| `-log_disabled` | Disable logging |

**Map files:** `data/game/maps/Freegamemaps/MP_2P_*.bin` etc. (not `.s2m`)  
**User map path:** `C:\Users\<user>\Documents\SAdK\maps\*.s2m`

---

## Next Steps to Try

1. **Watch for CONNECTION #2** in server logs after GetChatServer response. If it never appears, the UC connection attempt is failing silently — try different IP formats or port values.

2. **Check if the game does a TCP probe** of port 5479 before enabling the button. Run `netstat -ano` filtered to SADK.exe PID right after the character screen loads.

3. ~~**Try `-localhostmode` + stub server combined.**~~ **ABANDONED (2026-06-01 s2).**
   `-localhostmode` is just an internal "walk around the lobby" test harness — it does
   not expose a network socket we can bridge to. Not a real-multiplayer path.

4. ~~**Run two SADK instances.**~~ **ABANDONED (2026-06-01 s2).** SADK.exe refuses to run
   two instances on the same machine (single-instance lock), so the A-hosts/B-joins
   localhost test is impossible. Real two-player testing needs **two physical machines**
   (or a VM) both pointed at the stub. Defer until the chat connection is solved.

5. **Look at LobbyComm.log during the stuck state.** The log showed `LobbyVillageServerList.cpp:116` in a previous run. Enable logging (`-log_info -log_path`) and see what the log says when the button is stuck.

6. **Check `SelectNickname` (TYPE 72) flow.** When the user clicks on the "Testler" character (not the greyed button), the game might send TYPE 72. Our server handles this. It's possible the flow requires explicit character selection before the button activates.

---

## Emulator Source Reference

**Repo:** https://github.com/S2-modders/Settlers-AdK-lobby-emulator  
**Parent (Sacred 2, more complete):** https://github.com/pnxr/sacred2-lobby-emulator  
**What the emulator has working:** account creation, MOTD  
**What we added:** full login (ECDH + Twofish), character display, server list  
**Local clone:** `C:\Users\user\Downloads\AdK-emulator\`

---

## DNG Emulator Reference (added 2026-06-01 s2) — `Settlers-DNG-lobby-emulator/`

Go reimplementation of the lobby for the **predecessor** (Die Siedler II: Die Nächste
Generation / S2 10th anniversary). Same TinCat 3.0.53 family. **Most complete public
reference we have** — its README marks WORKING: login, MOTD, online status, global chat,
**create new game, join new game, launch new lobby with other players**, host port-check
(direct-connect preferred), and automatic FRP TCP bridge when direct fails.

**Differences from AdK (don't copy bytes, copy the flow):**
- Payload magic is `0x27D8` (DNG) vs `0x26B6` (AdK). Header magic/IDs identical.
- **DNG has NO chat second-connection.** S2-10th does global chat on the *single* main
  connection (`RegObserverGlobalChat 107` → `ChatMessage 2` → `Chat 165`). The separate
  UC/chat server (`GetChatServer 189` → second TinCat connection) is **AdK-specific** —
  which is exactly why our greyed-button work targets the chat connection.

**What it confirms for us:**
- `GameServerData(170)` uses **byte** player counts (ServerType u8, LobbyId u32, Version,
  MaxPlayers/CurPlayers/AiPlayers u8, Level/GameMode u8, Hardcore, Map, Running, Data,
  TicketId) — identical to the AdK emulator. ⇒ our `GAMESERVERDATA_FORMAT="adk"` default
  is right; ServerInfoOld (uint16+spectators) is the wrong layout for this client family.
- `RegObserverServerList(171)` = SendAll, ServerType, RoomId/LobbyId(u32), Selection(u32),
  TicketId — matches our fixed 171 parser.
- Full single-connection lobby flow is in `API.md` (mermaid) — authoritative checklist.

**The shared "see all created games / default filter" blocker — what it actually is:**
`network.go::createGameServerData` carries the comment *"there is an issue with server
entries being listed under 'other versions'"*. The client **filters the server browser by
VERSION/LobbyId**; created games land under "other versions" unless their `Version`/`LobbyId`
exactly match the client's expected patchlevel (AdK = **9212**). The "dll hack" both projects
mention is a **client-side patch that disables this version filter** — it is NOT a
server-side fix. Practical consequence for AdK: even after the button unlocks, register
games with `Version="9212"` / `LobbyId=9212` to land in the default filter, OR apply the
same client-side filter patch.

**Host/join networking (DNG `netbridge/`):** host advertises a port; lobby does an HTTP
`/port/check` direct-connect probe to the host's public IP; if reachable it uses the host IP
directly, otherwise it provisions an FRP reverse-proxy port as a TCP bridge. For local
two-machine testing, direct-connect on the game port is enough; FRP is only for NAT.

---

*Good night. We got further than anyone publicly has on this.*
