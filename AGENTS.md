# AGENTS.md — entry point for every coding agent

The instructions for this repository are in **[`CLAUDE.md`](CLAUDE.md)**. They apply to every agent, whatever
tool runs it. Read it in full before doing anything, then **[`HARNESS.md`](HARNESS.md)** (the binding rules) and
**[`MEMORY.md`](MEMORY.md)** (what is established and what is open). If this file and `CLAUDE.md` ever disagree,
`CLAUDE.md` wins.

The rules that are most costly to miss:

- **Understanding is the deliverable.** The project reverse-engineers the 2008 game client and documents it; the
  lobby server, the mods and the coming remake demonstrate that model. Don't make something "work" without an
  evidence-backed reason.
- **Reverse engineering and live debugging go through the Ghidra MCP and the Frida MCP.** Standalone scripts that
  do RE, read or write process memory, trace, inject or patch are forbidden; a new tool needs a stated reason
  (`HARNESS.md` §3).
- **Never map Ghidra's `/SADK.exe`** (a different build): the game exe is `/sadk_noav.exe`.
- **No faked results, no flag-gating, no hacks without permission.** Tag claims honestly: `[PROVEN]` = binary
  address + live evidence; `[known]`, `[inferred]`, `[TODO]` otherwise.
- **Read the client before implementing** server or mod behaviour, and map before writing mod code.
- **Live tests only when the code cannot answer** (`HARNESS.md` §7).
- **Docs state the current model as clean fact**; no session logs or hand-off notes (`HARNESS.md` §8).
- **Public repository:** no real names, e-mail addresses, IPs, host names or home paths in commits; the git
  identity is repo-local (`CLAUDE.md`, "How to work here"). Branch `master`; `lobby/` and `sadkmod/` are
  submodules with their own repositories.
- **Never touch `sadk_players.json` / `sadk_mail.json`**: they are the live players' saves.
