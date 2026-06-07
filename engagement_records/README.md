# engagement_records/

Completed **Engagement Records** for state-mutating actions against the live SADK game,
its binary, or the wire protocol. See `../HARNESS.md` (the binding rules) and
`../templates/ENGAGEMENT_RECORD.md` (the template to copy).

## Workflow

1. Copy the template:
   ```
   cp templates/ENGAGEMENT_RECORD.md engagement_records/YYYY-MM-DD_<tool>.md
   ```
2. Fill **every** section with binary-grounded, read-only evidence — including the
   mandatory "is the game legitimately WAITING?" wait-state ruling-out.
3. Present it to the user for approval.
4. After the user approves, open the single-shot gate:
   ```
   python tools/harness_gate.py approve <tool> engagement_records/YYYY-MM-DD_<tool>.md
   ```
5. Run the (now-unblocked) injector once.

These records are intentionally **kept in git** — they are the project's audit trail of
*why* each mutation was justified, what its expected read-only-verifiable observable was,
and whether a wait-state was ruled out. The approval **token** (`tools/.engagement_approved`)
is the opposite: a transient local capability, gitignored, single-shot, time-bounded.

A forced/injected result documented here is a **diagnostic observation**, never a reported
"feature works." (HARNESS.md §4.)
