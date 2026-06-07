# Engagement Record

| Field | Value |
|---|---|
| Date | 2026-06-07 |
| Author (agent/session) | Claude (s38, no-CD-vs-retail diff + workflow wf_c3d663a3-a42) |
| Tool to be run | `tools/patch_je_file.py apply` |
| Tool category | live-binary-patch (STATIC file patch of a COPY of the unpacked no-CD exe) |
| One-line goal of THIS action | Revert the no-CD crack's sole game-code corruption (inserted `je` @0x503e22) to genuine retail bytes (`90 90`) in a COPY, to test whether it eliminates the `0xC000000D` `_vsnprintf_s` crash. |

---

## 0. Classification check (why this needs the gate)

- [x] This action mutates the binary (creates a patched, runnable exe the user will launch).
- [x] It is NOT achievable by a read-only RPM probe or a Ghidra read (the test requires running the patched build; the patch is a byte write).

---

## 1. The verified model (MODEL BEFORE MUTATION)

- Function patched:
  - `0x503e10` — **EnterVillageAction_Tick** (`FUN_00503e10`, decompile line 177156) — per-frame tick of the EnterVillageAction object (`App/Lobby + 0xc0`). **[PROVEN]** (capstone disasm of both images + decompile, this session).
- The byte patched:
  - **file offset `0x103e22` == image `0x503e22`** (unpacked dump-PE: file offset == RVA, base 0x400000). **[PROVEN]**
- State fields:
  - `action+0xc` — pConn — **[PROVEN]** (disasm: `cmp dword [esi+0xc],0`).
  - `action+0x10` — connection-ready flag — **[PROVEN it is the gated field]**; set ONLY by `FUN_00503650`/`FUN_00503790` (transport/overlay callbacks, no .text callers) — **[PROVEN they are the only setters; HYPOTHESIS what fires them]**.

- The model in prose:

> The ~2013 no-CD crack's **entire game-code footprint** is **2 bytes** at image `0x503e22`. A full-image
> byte-diff of `SADK - NO CD.exe` vs the raw retail dump `tools/SADK_dump.bin` (the genuine working image)
> over `0..0x2060000` finds **exactly one `.text` difference, both bytes at 0x503e22**: retail = `90 90`
> (`nop;nop`), no-CD = `74 18` (`je 0x503e3c`). **[PROVEN].** In retail the proceed-block (`call 0x503900`;
> clear `[+0xc]`,`[+0x10]`) runs whenever `[+0xc]!=0` (the `[+0x10]` compare is inert/NOP'd). The crack's
> inserted `je` re-gates it on `[+0x10]!=0 && [+0xc]!=0`, so when `[+0x10]==0` it **skips the block and never
> clears `[+0xc]`** — a wedged half-initialised EnterVillageAction. **[PROVEN control-flow].** That wedged
> state is the lead suspect for feeding a malformed argument into the logger `FUN_006e5ec0` →
> `_vsnprintf_s` invalid-parameter abort `0xC000000D` @`0x6f36b2`. **[HYPOTHESIS — strong, not traced
> instruction-by-instruction].** The crash site, logger, the `[+0x10]` setters and the caller are all
> **byte-identical** between builds **[PROVEN]**, which proves the crash is a downstream symptom, not a
> patched code site. Reverting `74 18`→`90 90` makes the no-CD `.text` **byte-identical to retail** (a
> simulated revert left 0 residual `.text` diffs) **[PROVEN]** — i.e. it restores the genuine retail logic.

**Independent review:**
- [x] Yes — verdict: **LOGICALLY SOUND**. Workflow `wf_c3d663a3-a42` (4 agents, read-only) independently
  re-derived from the binaries: the `je`@0x503e22 is the **sole** game-code change and the cause of the
  divergent control flow (HIGH confidence); the revert is **correct + necessary**; a simulated revert yields
  0 residual `.text` diffs vs the retail dump. The panel also flagged the sufficiency caveat handled in §3/§5.

---

## 2. Read-only precondition checks

| What | Read-only source | REQUIRED | OBSERVED | OK? |
|---|---|---|---|---|
| no-CD src bytes @0x103e22 | `patch_je_file.py verify` | `7418` (je/crack) | `7418` (je/CRACK) | ✅ |
| retail ref bytes @0x103e22 | python read of `tools/SADK_dump.bin` | `9090` (nop;nop) | `9090` | ✅ |
| patch target is the UNPACKED no-CD | file size / plaintext check | 33.9MB unpacked, plaintext at 0x103e22 | confirmed (packed retail SADK.exe is ciphertext `ce dc` there — NOT our target) | ✅ |
| gate currently closed | `harness_gate.py status` | closed until approved | `NO approval token (gate CLOSED)` | ✅ |

```
[verify] read-only -- nothing modified.  offset 0x103e22 (image 0x503e22)
  src  (no-CD): 7418  (je/CRACK)
  dst  (jefix): (absent)
[harness_gate] NO approval token (gate CLOSED). No state-mutating tool may run.
```

---

## 3. ⛔ Is the game legitimately WAITING?

- Is the relevant subsystem in a wait-for-message/event state?
  - **For the CRASH (this action's scope): NO.** The crash is an *abort* (`_vsnprintf_s` raising
    `0xC000000D`) caused by a corrupted code byte, not a parked wait. It is not a pump-with-no-case or a
    connection blocked awaiting a reply — it is the CRT secure-formatter rejecting a malformed argument that
    the wedged state produced.
- If something is being awaited, can we provide it via the genuine mechanism?
  - **Not applicable to the crash.** The genuine mechanism here is *retail's own byte* (`90 90`), which the
    patch restores. We are not substituting for a missing inbound message.
- ⚠️ **Explicit scope boundary (the related wait-state, OUT of scope):** reaching MP **world-entry** *is* a
  wait-state — `[+0x10]` is set by overlay callbacks (`0x503650`/`0x503790`) fired by inbound messages our
  stub may not yet send; `docs/BINARY_PATCHES.md` **P3** confirms the live flip is a **no-op for world-entry**.
  This record does **NOT** claim to enable world-entry and does **NOT** force past that wait-state. It only
  repairs the crack's corrupted byte to stop the *crash*. The world-entry wait-state is a separate, unaddressed
  problem (protocol/stub completeness, affecting retail too).
- **Ruling-out statement:** "The game is NOT waiting for a message/event we should instead supply, because the
  crash is a corruption-induced CRT abort and this action restores the genuine retail byte — not a forced
  bypass of a pending message. The world-entry wait-state is explicitly out of scope and is not claimed fixed."
- [x] I confirm the game is not in a legitimate wait-state that the real mechanism should satisfy *for the
  crash this action targets*.

---

## 4. Why this is the GENUINE mechanism, not a shortcut

- This is **corruption REPAIR**, the opposite of a forced bypass: `90 90` are literally the bytes genuine
  retail has at `0x503e22` (cite: `tools/SADK_dump.bin` @0x103e22 = `90 90` **[PROVEN]**). We restore the
  original game's code that the crack overwrote; the game then runs its own real EnterVillageAction logic.
- Where the game itself does this: it IS the game (retail) — verified byte-for-byte against the retail dump.
- [x] Honesty clause: this is a candidate **fix** (repair), but its crash-prevention *effect* is a hypothesis.
  The result will be reported exactly as observed — "the `0xC000000D` crash did / did not recur" — and never
  as "MP works" / "world entry works".

---

## 5. Expected observable + how it is verified READ-ONLY afterward

- Precise expected observable:
  - The patched build (`SADK - NO CD - jefix.exe`), run through the same flow that produced dump `4624`
    (loader-less; lobby/enter against the stub), does **NOT** raise the `0xC000000D` `_vsnprintf_s` abort at
    `0x6f36b2`.
- Read-only verification:
  - success: no NEW `%LOCALAPPDATA%\CrashDumps\SADK*.dmp` with code `0xC000000D` @`0x6f36b2`
    (check via `tools/minidump_exc.py`); `tools/probe_watch.py` shows the build surviving past the
    previously-crashing point.
  - failure / no-op: a new dump still shows `0xC000000D` @`0x6f36b2` (the `je`-revert is NOT the crash fix),
    or a *different* crash now dominates (e.g. the separate `0xC0000005` SecuROM AV).
- What would FALSIFY the model:
  - Same crash signature (`0xC000000D` @`0x6f36b2`) persists after the patch ⇒ the wedged-state→logger
    hypothesis is wrong ⇒ `undo` and re-investigate. (A different crash surfacing is a SEPARATE issue, not a
    confirmation.)

---

## 6. Rollback / blast radius / safety

- Threading/contention: **none** — a static file write to a *new copy*; no live-process injection, no remote
  thread, no `VirtualProtect`. The game must be relaunched to load the patched build.
- Blast radius if wrong: 2 bytes in one function (EnterVillageAction_Tick). SP is unaffected (`[+0xc]==0` in
  SP, so the block is inert in both builds — army-verified). Worst case the patched build still crashes the
  same way (no-op) — no worse than today's no-CD.
- Rollback plan: `python tools/patch_je_file.py undo` (deletes the patched copy), or simply delete
  `SADK - NO CD - jefix.exe`. The original `SADK - NO CD.exe` is **never modified**. Complete + trivial.
- Disposable / relaunchable target: **yes** — a copy of the no-CD build; no user data at risk; the genuine
  retail exe and the original no-CD exe are untouched.

---

## 7. Decision

- [x] Sections 1–6 are completed with real, binary-grounded, read-only evidence.
- [x] The game is NOT in a legitimate wait-state we should satisfy via its real mechanism (for the crash scope).
- [x] The expected observable and its read-only verification are defined.
- [x] I will report the result as observed (crash recurs or not), never as a working feature.

**Requested of the user:** approve running `tools/patch_je_file.py apply` once, to create the patched copy
`SADK - NO CD - jefix.exe` (the original no-CD exe and the retail exe are untouched).

> On your explicit "approved: run patch_je_file", the gate is opened with:
> `python tools/harness_gate.py approve patch_je_file engagement_records/2026-06-07_patch_je_file.md`
> then `python tools/patch_je_file.py apply` runs once (single-shot, consumed on run).
