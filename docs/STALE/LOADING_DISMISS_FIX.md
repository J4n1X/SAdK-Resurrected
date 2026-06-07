# SADK World-Entry — Loading-Screen Dismiss FIX (s35, 8-agent workflow)

The last wall after world entry: `HandleEnterWorld` runs, the `1006` gate fires, but the loading
screen never hides. Root-caused + fix designed. Addresses are `SADK.exe` @ base `0x400000` (runtime VAs;
SecuROM-encrypted at rest — apply live like P1/P2).

## Root cause (decompiled, re-confirmed on SADK_dump.bin)
`HandleEnterWorld @0x46f470` finalizes by `0x46f685: call 0x46e980` — the **world-entered NotifyObservers**
fan-out (`FUN_0046e980 → FUN_004d6a16 → FUN_0046e987 @0x46e987`), Subject = `VillageServerConnection+0x104`,
arg = the conn. `FUN_0046e987` walks the observer list (head from `FUN_004798b0`, body `jmp [0x12f2038]` into
the SecuROM overlay) and at `0x46e9d8 (ff d0 = call eax)` calls `node->handler = [node+0xC]` with
`ecx=[node+8]`. The node that should point at `nMenu::Game`'s world-entered dismiss handler is registered by
**SecuROM-overlay code** that doesn't run cleanly on Win10/11 → its `node+0xC` holds the dead WinXP
`0x7c81320c`. **P1 maps `0x7c81320c → OpenFileMappingA`, so the walk no longer AVs — but it now calls
`OpenFileMappingA` instead of the real dismiss → loading never hides.** No flag-poll path dismisses it
(verified: `loginAckReceived +0x224` is write-only; screen-swapper `FUN_004f57e0` has no `state==9` branch).

## The fix — code-cave hook on the world-entered notify → drive `nMenu::Game::OnEnter`
Hook **only** `0x46f685` (the *world-entered* notify; leaves the UC-LoggedIn Subject `0x48d7e0` + its P1 page
untouched). Redirect it to a cave that calls **`nMenu::Game::OnEnter @0x5ef110`** (`__thiscall ecx=Game*`)
— the same function the offline/disk-load path uses to hide the `LoadingPanel` + start 3D render. Its tail
(`0x5ef285..0x5ef43c`) does: `"!completed"/1.0` (`pcb=*(panel+0x2A8)`), hide panel (`FUN_0049ffc0`, fade-out
`FUN_004c37c0`), activate scene render (`*(Game+0x7FD0)`), emit `"!START"`. Calling the higher-level OnEnter
runs all the inter-step bookkeeping for free.

```
@0x46f685  orig: e8 f6 f2 ff ff   (call 0x46e980)
           new:  e8 <CAVE-0x46f68a>  (call CAVE)
CAVE (minimal, Win10/11): pushad; pushfd; <resolve Game*→ecx>; test ecx,ecx; jz d; call 0x5ef110; d: popfd; popad; ret 4
```
`ret 4` balances the single pushed `conn` arg (matches `0x46e980`'s `ret 4`). Fail-safe: `jz` → no-op if
`Game*` null (worst case = unchanged frozen loader, never a new crash). Isolated from P1 (the `0x46e9d8`
observer call is a plain `call eax` from a heap field — NOT the shared `0xE3062A44` XOR dispatcher @0x1841a66).

## ⏳ The one open detail (being independently resolved)
The cave needs the **exact `Game*` deref chain** from a stable static global to the live `nMenu::Game*`
(spec left it "resolve live"). Candidate root: scene singleton `[0x890fcc]` (dereffed by the dismiss code at
`0x5ef2e7`). An independent agent is nailing `mov ecx,[0xADDR]; mov ecx,[ecx+OFF]…` + confirming OnEnter is
safe to call directly. **This is the highest risk** (wrong `Game*` → AV inside `0x5ef110`).

## Two test paths
- **(A) LIVE one-shot — no re-drive.** glass is still frozen-loading + alive (village conn pinging, Pong
  keepalive). A one-shot remote thread-call of `OnEnter(ecx=Game*)` (like `force_send2002`) on this session
  should dismiss the current frozen loading. Fastest; pending the reviewer's go + the `Game*` deref.
- **(B) The hook + a fresh world-entry drive** — the permanent fix (`tools/world_dismiss_patch.py`, applied
  by `debugger_loader.py`/`glass_debug.py` after `map_dispatch_fix.apply`). Fires once when
  `HandleEnterWorld` runs.

## Stub side — unchanged (already correct)
EnterWorld(1000) + Pong(0xED7) + WorldLoginAck(1006, **bare-u32** 0xDEADBEEF) stay as-is. WorldTick(1005)
held off for the first drive. **Chat id 11 = fire-and-forget (tincat3 FUN_1000d4f0), no reply needed**, does
NOT gate loading.

## Address table
| What | Addr | Orig | Patched |
|---|---|---|---|
| world-entered notify (hook) | `0x46f685` | `e8 f6 f2 ff ff` | `e8 <CAVE-0x46f68a>` |
| dismiss+render driver | `0x5ef110` | `nMenu::Game::OnEnter` (__thiscall ecx=Game*) | — |
| panel hide | `0x49ffc0` | `FUN_0049ffc0(float,ptr)` | — |
| scene singleton (Game* src) | `[0x890fcc]` | runtime | — |
| fan-out / node call | `0x46e987` / `0x46e9d8` | walks list, `call [node+0xC]` | — (left alone) |
