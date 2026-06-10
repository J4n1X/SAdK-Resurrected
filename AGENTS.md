# AGENTS.md — agent entrypoint for `sadk-resurrected`

> **Mandatory:** Before doing any work in this repository, every agent must read
> [`CLAUDE.md`](CLAUDE.md) in full.
>
> **`CLAUDE.md` is the authoritative agent instructions file for this repo.**
> If anything in this file and `CLAUDE.md` ever disagree, **`CLAUDE.md` wins**.

---

## Required startup order for every agent

1. **Read `CLAUDE.md` first. Do not start work before reading it.**
2. Read **`HARNESS.md`** and follow its rules for any RE, debugging, or stub change.
3. Use **`MEMORY.md`** for persistent project context (proven facts + TODOs).
4. Then consult the project docs relevant to the task.

---

## What this file is for now

This file is intentionally short. It exists only as a current pointer so that:
- no agent starts from stale onboarding material,
- all agents converge on the same rules of engagement,
- and the repository has a single authoritative agent brief.

The detailed project guidance that used to live here has been consolidated into
`CLAUDE.md` where it belongs.

---

## Key project pointers

- **Primary agent instructions:** `CLAUDE.md`
- **Binding rules of engagement:** `HARNESS.md`
- **Persistent context (proven facts + TODOs):** `MEMORY.md`
- **Protocol reference:** `docs/LOBBY_PROTOCOL.md`, `docs/SOURCEMAP.md`
- **Quick-start / package overview:** `README.md`

---

## Non-negotiable reminder

If you are an agent reading this file: **stop here and read `CLAUDE.md` now before doing anything else.**