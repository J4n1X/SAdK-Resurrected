# Engagement Record — TTD recording + one delayed EntityCreate to a single in-world client

**Date:** 2026-07-31 (late) · **Status:** PROPOSED, awaiting approval · **Type:** stub wire change
(one-shot diagnostic frame) + TTD recording

## Context — why this test, and why the message side is not the suspect

The avatar render chain is now fully mapped (`docs/IN_WORLD_PRESENCE.md`, commit `37e3658`), and the
maintainer confirmed the **own settler IS visible** — so templates, CLobbyObj construction, scene
attach and the style pipeline all work. Every link from the wire to
`CLobbyClient_UpdateAvatar@0x00503620` is proven live or statically unconditional, IDs are collision-
free (`test`=1, `test2`=2 in both namespaces), and no error path fired. Static analysis cannot go
further: the remaining question is **which of the verified-in-isolation links does not execute at
runtime**, and that is exactly what one TTD trace answers retrospectively (`ttd_calls`).

## Proposed action

1. **TTD-record the local client** (elevated debugger server, recording started before login), through
   lobby login → village entry.
2. **10 s after this client's EnterWorld(1000) push**, if no real second player is in-world, the stub
   sends **one** EntityCreate(1001) for the `test2` player (id=2, name "Siedler", standard
   `_spawn_spot(2)` position, full AvatarStyle block) — produced by the **same code path**
   (`village.send_entity_create` + `_avatar_style`) as a real join; only the *trigger* (timer instead
   of a second login) is synthetic.
3. Stop the recording ~15 s later; all queries run offline against the trace.

If a real second client joins instead (friend / second machine), step 2 is skipped — the real
mutual-spawn frame serves the same purpose and the same queries apply.

## Probe safety (rule adopted 2026-07-31, negative-control ER)

The frame is **well-formed** — byte-identical in shape to the deployed mutual-spawn frame that has
already been sent live twice and parsed cleanly (zero error lines from a per-field logger, no crash).
It varies only in *when* it is sent. No truncated bodies, ever.

## What the trace will be asked (in order, each answer narrows to one function)

| query | if it fired | if it did NOT fire |
|---|---|---|
| `ttd_calls HandleEntityCreate@0x0046e1d0` | delivery confirmed again | transport regression — inspect the frame path |
| `ttd_calls CLobbyClient_UpdateAvatar@0x00503620` | the observer fan-out works; fault is in creation | **the drain/observer link is the wall** — `ttd_memory` on `conn+0xbc` (list head) shows every subscribe/unsubscribe with the writing IP |
| `ttd_calls CLobby_CreateAvatarObjFromProxy@0x004f6de0` / `CLobby_CreateLobbyObj@0x004f6ca0` / `CLobbyObj_Construct@0x00502e60` | object created — fault is placement/visibility, inspect ctor args (template type) | create path bailed — inspect `UpdateAvatar`'s branch (proxy+0x84 discriminator) |

## Harness compliance

- **Not faking a result.** The probe supplies real data via the real message and the real send path;
  the measurement is the client's recorded behaviour, not a forced outcome. Nothing is patched or
  injected into the client.
- **Legit wait-state ruled out?** Yes — the client is not waiting for anything at this point: it is
  fully in-world (state 9, own avatar rendered), and the frame under test is the same one a real
  second player produces.
- **No flag-gating.** The timer probe is a one-shot diagnostic, clearly logged as `[DIAG]`, removed
  after the trace is captured. The real mutual-spawn path is untouched and stays default.
- **Reversible.** One code hunk, deleted after the run.

## Result — RUN 2026-07-31 ≈23:45, trace `avatar_spawn_diag.run`. **ROOT CAUSE FOUND.**

**The timer probe was never needed** — the maintainer ran the second client in a VM, so both spawn
paths were exercised genuinely (present-at-entry + leave/re-enter). Recording attached at the lobby
screen (PID 19184), stopped after both events; trace indexed in 12 s, module base `0x00400000` =
static, so all Ghidra addresses applied verbatim.

The call ladder, verbatim from the trace (all thread 0x3574):

| function | calls | verdict |
|---|---|---|
| `DrainEventQueues@0x0046fde0` | 39 (positive control) | pump runs; first drain has a long span (processed items) |
| `HandleEntityCreate@0x0046e1d0` | **2** | both frames arrived and executed |
| `CLobbyClient_UpdateAvatar@0x00503620` | **2** | the `+0xbc` observer FIRED — the fan-out works |
| `CLobby_CreateAvatarObjFromProxy@0x004f6de0` | 2, ret `0x2cf8e880` / `0x2cf8eba0` | CLobbyObj created, non-null both times |
| `CLobby_FindObjTemplateByName@0x004ffa80` | 3, ret `0xe81b60c` every time | "settler" template resolves; call #1 is the OWN spawn — same template |
| `FUN_00519c10` (0x198 "character" visual) | 2, ret non-null | remote visuals constructed |
| `FUN_0051a1a0` (0xa8 variant) | 1 | the OWN avatar's visual — confirms the own/remote ctor fork |
| `AvatarVisual_RefreshStyleModel@0x00508090` | long-span call `2B316→2B492` inside UpdateAvatar #1 | **the styled 3D model was BUILT** |

**Every stage of the chain worked.** The defect is the *position argument* read at the visual ctors
(`!tt` + `dd poi(esp+8)`):

- OWN avatar: **(-31.24, 2.71, +8.28)** — matches the binary's default-spawn constants
  `DAT_007dd028/2c` on x/y exactly (static z `DAT_007dd06c` is −8.28; observed +8.28).
- REMOTE avatar: **(0.0, 0.0, 6.0)** — precisely our `_spawn_spot(2)` ring position, byte-exact
  through quantise → wire → dequantise → ctor. **The wire pipeline is pass-through-correct.**

⇒ The remote settler has been **fully spawned, modelled and styled** on every test tonight —
standing ~31 units from the village square and ~2.7 units below its ground level, where no player
ever looks. Fix: spawn remote avatars on a ring around the proven square position — see
`engagement_records/2026-08-01_spawn-at-village-square.md`.

Two method notes worth keeping: (1) the positive-control query (`DrainEventQueues`) is what makes a
0-calls answer trustworthy — always pair one with the question call; (2) `ttd_calls` + one `!tt`
travel replaced what would have been another week of static guessing, exactly as
[[ttd-record-once-query-offline]] predicted.
