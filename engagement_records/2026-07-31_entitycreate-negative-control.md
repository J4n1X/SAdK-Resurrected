# Engagement Record — negative-control EntityCreate, to prove delivery

**Date:** 2026-07-31 · **Status:** PROPOSED, awaiting approval · **Type:** stub wire change (additive
diagnostic frame)

## The question this answers

Two clients were in-world together tonight and both `EntityCreate(1001)` frames went out
(`stub_avatars2.out` 22:29:25 and 22:34:07, 27 B each, on the correct village conns). **No avatar
appeared and the client logged nothing at all.**

That silence is ambiguous, and the rule this project previously used to read it has been retracted
(see `docs/IN_WORLD_PRESENCE.md` § CORRECTION): `HandleEnterWorld` is equally absent from
`LobbyComm.log`, and EnterWorld demonstrably works — **no `Handle*` method is instrumented**. So
"no error" fits both:

- **H1 — delivered, parsed, not rendered.** The handler ran to completion (it logs on *both* failure
  paths, so a silent run is a successful run), registered the AvatarProxy and fired the notify queue
  at `+0x1ac`, but nothing was drawn — most likely no model without the **AvatarStyle** block.
- **H2 — never delivered.** The frame never reached `VillageServerConnection::HandleMessage`.

Static analysis cannot separate them, and has been pushed as far as it goes:

- `HandleMessage@0x00470a90` — binary-search switch, **no pre-switch guard, no state check**; `1000`
  and `0x3e9` sit in the *same* switch block, dispatched identically. If 1000 arrives, 1001 arrives.
- `HandleEntityCreate@0x0046e1d0` — peeks `id` (32 b) then logs `Can't peek AvatarID` on failure;
  `AvatarProxy_ReadDataBlocks` failure logs `Can't read Avatar from stream.` **Both paths log.**
- `LobbyMessage_SelectField@0x0048f490` — **no-op when the names flag is clear**, so our `names=0`
  positional encoding is correct and the id peek would succeed.

⇒ Everything we control checks out. The remaining unknown is purely *did the frame arrive*.

## Proposed action

Send **one additional, deliberately malformed `EntityCreate(1001)`** to a client already in-world —
a body too short to contain the 32-bit id (e.g. 2 bytes) — alongside (not instead of) the correct
spawn frame.

This is a **negative control**, not a workaround: it is designed to *fail loudly*, and its only
purpose is to make the client speak.

| outcome | conclusion | next step |
|---|---|---|
| `Can't peek AvatarID` appears in `LobbyComm.log` | **H2 is dead** — frames ARE delivered and the handler DOES run ⇒ the good frame also parsed, and the fault is purely rendering | enable the AvatarStyle block (`dtblcks \|= 2`, writer already built + tested) |
| still total silence | **H1 is dead** — the frame is not reaching `HandleMessage` at all | investigate the `SendGameData(74)` inbound bridge / routing for 1001 vs 1000 |

Either result kills one hypothesis outright. There is no outcome that leaves us where we are.

## Why this and not TTD

`ttd_calls 0x0046e1d0` would answer the same question directly and is the tool
`docs/IN_WORLD_PRESENCE.md` recommends. But it needs the debugger server running (currently down),
an elevated recording started **before the client's first login** (the `189` one-shot), and the
maintainer has noted a TTD trace is punishingly slow to drive interactively. The negative control
costs one frame and no gameplay time.

## Harness compliance

- **Not faking a result.** Nothing is forced, patched or injected; no success is manufactured. The
  frame is *expected to fail* — that is the entire point.
- **No flag-gating of working behaviour.** The real spawn path is untouched and stays default; this
  adds a diagnostic frame beside it, to be removed once the question is answered.
- **Reversible.** One frame, removed the moment the log is read.
- **Legit wait-state ruled out?** Yes — this does not substitute for something the client is waiting
  for; it is a probe, and the client's own reaction is the measurement.

## Result

*(to be filled in after the run)*
