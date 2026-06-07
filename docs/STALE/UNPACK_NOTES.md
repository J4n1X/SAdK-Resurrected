# SADK.exe SecuROM 7.37 → SADK_glass.exe — unpack notes (research-backed)

Distilled from the s34 unpack-research agent. SADK.exe is **SecuROM v7.37.0014**.

## ★ The big reframe (makes this EASIER)
- SADK's SecuROM is **Disc Authentication, NOT Product Activation** → **no activation server** to satisfy.
  The whole check is LOCAL and patchable offline. (Confirmed: GameCopyWorld lists "SecuROM v7 (v7.37.0014)";
  WineHQ Bug 29290 = "disc authentication failure" only.)
- The `OpenFileMappingA("0A25A3F6E7D13B25951F80DE03F34C3")` we decoded is SecuROM's **local named
  shared-memory trigger/IPC handshake** between the exe and its trigger module — **not** a network license.
  Force the post-trigger disc-check branch to pass → done.
- **7.37 uses thunk/jump-bridge import obfuscation, NOT the full 8.x VM** → imports are recoverable by tracing.
  Our `mov edx,[[ebx+0x28]+8]; xor edx,0xE3062A44; call edx` is the documented **per-import XOR-decrypt thunk**
  (`[ebx+0x28]`=encrypted-addr table, `+8`=slot, `0xE3062A44`=per-thunk key) → handled by the existing
  "SecuROM 7.xx Jump Bridge & Crypted Code Fixer" script.
⇒ This is on the **EASY end** of SecuROM 7.x.

## Three paths (pick per effort vs "standalone glass")
1. **Fastest transparent run (no exe surgery):** drop **SecuROMLoader** `version.dll` (proxy + MinHook) next
   to SADK.exe — defeats the v7 disc auth at runtime, zero exe modification. Functionally transparent tonight.
   → not a standalone .exe, but great for immediate stress-testing. https://github.com/nckstwrt/SecuROMLoader
2. **Reference/sanity only:** a scene **Fixed EXE for SADK v1.0 [GERMAN]** already exists (GameCopyWorld, 2008,
   ~5.7 MB). We won't ship a scene crack, but ~5.7 MB is the **byte-budget sanity check** for our own rebuild.
3. **★ SADK_glass.exe (the /goal): full unpack → standalone clean PE.** Two ways to execute (see below).

## Building SADK_glass.exe
We already have the full decrypted dump (`tools/SADK_dump.bin`, VA-layout) + a Ghidra map → we skip OEP-stub
decryption tracing and go straight to packaging.

### Path 3a — programmatic from our dump (preferred; scriptable, no GUI)
1. Re-align sections: for each section set `PointerToRawData = VirtualAddress`, `SizeOfRawData = mem-aligned
   VirtualSize`; recompute `SizeOfImage`. (PE-from-memory; the dump is already VA-laid-out.)
2. Set `AddressOfEntryPoint = OEP` (real MSVC CRT start — agent a9d6e... is finding it).
3. **IAT reconstruction:** resolve every redirected import thunk to its real API. We have the dispatch family
   decoded (XOR-key thunks); enumerate ALL dispatch sites (agent a9d6e...), resolve each `xor <key>` thunk →
   real API, rebuild a clean import table + IAT, repoint DataDirectory[1]/[12]. (NOTE: re-align ALONE loads in
   IDA but will NOT run — the IAT rebuild is what makes it runnable.)
4. **Patch the disc-check branch** to always-pass (the conditional after the OpenFileMappingA trigger). Bakes in
   P1/P2 as a clean static patch (since in the unpacked image these are ordinary code).
5. Strip/zero the `.securom` overlay + trigger sections. Final size should approach ~5.7 MB (sanity vs path 2).

### Path 3b — classic tools (interactive GUI; fallback if 3a stalls)
Scylla (dump@OEP + IAT autosearch + **Fix Dump**) + x64dbg/OllyDbg + **ScyllaHide** (anti-anti-debug) +
the **SecuROM 7.xx OllyScripts** (OEP finder, **CRC Check Fixer**, **CPUID Fixer**, **Jump Bridge & Crypted
Code Fixer**). Scylla follows simple redirects but will NOT auto-crack the XOR thunks — run the jump-bridge
script first to materialize real addresses, THEN let Scylla snapshot a clean IAT.

## Anti-debug / gotchas (for path 3b or any live work)
- SecuROM `.securom` section is PAGE_GUARD → Memory Map → Full Access before dumping.
- Anti-debug: PEB/NtGlobalFlag, NtQueryInformationProcess, ZwQueryObject handle-count, ThreadHideFromDebugger,
  DRx/HW-bp detection, parent/child GetTickCount watchdog → ScyllaHide (usermode) / TitanHide (kernel);
  oepfind `/1` patches GetTickCount to defeat the timing kill.
- A re-aligned dump w/o IAT rebuild = loads but won't run.

## Tools + sources
- Scylla https://github.com/NtQuery/Scylla · ScyllaHide https://github.com/x64dbg/ScyllaHide · x64dbg
  https://github.com/x64dbg/x64dbg
- **SecuROM 7.xx OllyScripts (the key assets)** https://github.com/dubuqingfeng/ollydbg-script/tree/master/SecuROM
- ★ "Breaking SecuROM 7 – A Dissection" https://lostfilearchives.github.io/08/28/Dissection/
- Synacktiv "developing an unpacker / import-redirection" https://www.synacktiv.com/ressources/unpacking_starforce_synacktiv.pdf
- SecuROMLoader https://github.com/nckstwrt/SecuROMLoader · GameCopyWorld SADK
  https://gamecopyworld.com/games/pc_die_siedler_aufbruch_der_kulturen.shtml · WineHQ 29290
  https://bugs.winehq.org/show_bug.cgi?id=29290 · S2-modders clean-SADK repo
  https://github.com/S2-modders/Settlers-AdK-Patches

---

## ✅ BOOT ACHIEVED (s34) — SADK_glass.exe boots + plays singleplayer
The from-memory rebuild WORKS. Exact recipe that got a running window + singleplayer:
1. `tools/dump_module.py` -> `SADK_dump.bin` (NOW dumps [0x400000, 0x2461000] — the old END=0x2460000
   truncated the last 0x5E8 bytes of `.securom`, which broke the boot; see step 3).
2. `tools/glass_rebuild.py` -> `SADK_glass.exe`: keep all 10 sections, AOEP=0x2F3D41 (genuine MSVC CRT
   entry), zero CheckSum, pad to SizeOfImage 0x20605E8.
3. `tools/glass_fix_data.py` (two splices from the ORIGINAL on-disk SADK.exe, which is decrypted/static):
   - **`.data`** (file 0x47A000, 0x27000): the dump was mid-GAME so `.data` held a stale heap ptr
     (0x22cb7710) in the CRT atexit/destructor list -> CRT init walked it -> kernel32 heap AV. Splice the
     original's pristine `.data` -> resets those globals.
   - **`.securom` tail** (file 0x2060000..0x20605E8, 1512 B): the truncated dump left this as zero-padding,
     but the SecuROM VM `CALL`s code at 0x2460535 -> executed zeros -> AV. Splice the original's real bytes
     (`5b c9 c2 04 00  3e 8b 04 24...` = pop ebx; leave; ret 4; mov eax,[esp]). THIS was the boot-blocker.
4. Run under `tools/glass_debug.py` (launches glass.exe under a debugger, logs every DLL/exception/exit
   NTSTATUS, and applies **P1/P2** = OpenFileMappingA-dispatch JMP + stack-balance NOP via map_dispatch_fix
   at the initial breakpoint). RESULT: window "Die Siedler - Aufbruch der Kulturen" + playable singleplayer.

REMAINING for a TRUE standalone double-click `SADK_glass.exe` (no harness):
- Confirm whether P1/P2 are even needed for SINGLEPLAYER (the OpenFileMappingA dispatch fired at WORLD-ENTRY
  in the original, not at startup) — test glass.exe RAW (no glass_debug). If it boots raw, it's already
  standalone for SP.
- Bake P2 statically (NOP `push eax` @0x01841A9D: 50->90) — trivial file patch.
- P1 (the dead 0x7C81320C dispatch) is runtime-natured; for standalone either repoint the dispatch to the
  real OpenFileMappingA (IAT) or patch the post-trigger disc-check branch to pass. Needed for MULTIPLAYER
  world-entry; maybe not for SP.
- A cleaner future rebuild: re-dump at OEP (pristine .data, no `.data` splice needed) with the fixed dump
  range (no tail splice needed).
