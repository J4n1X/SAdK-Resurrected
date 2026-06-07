r"""
harness_gate.py -- the HARD mutation gate for SADK state-mutating tools.

WHY THIS EXISTS
---------------
This project repeatedly OVERSTEPPED: agents force-called game functions / injected
remote threads / patched the live binary "just to see a result" BEFORE the model was
verified -- and sometimes while the game was legitimately WAITING for the genuine
mechanism (the canonical case: forcing nMenuSystem_ActivateScreenById while the game
was simply parked in LobbyManager state 8 waiting for inbound msg 1000). See
../HARNESS.md and ../CLAUDE.md.

Every STATE-MUTATING tool in tools/ (the force_*.py injectors, the live binary
patchers) MUST import this module and call require_approval(...) as the very first
thing in main(), BEFORE it opens the process / allocates / writes / spawns a thread.
If there is no APPROVED, fresh, matching Engagement Record token, this aborts the tool
with a clear message. Read-only RPM probes do NOT import this and stay ungated.

This is a guard, not a cage: it is defeatable by anyone who edits the code (it is the
same Python the tools are written in). Its JOB is to make "jumping the gun" require a
DELIBERATE, LOGGED, USER-DRIVEN act -- never an accident or an agent's unilateral
"let's just try it". The human approval is the real authority; this file makes that
approval a hard precondition for the injector even starting.

HOW THE GATE IS OPENED (the only sanctioned path)
-------------------------------------------------
 1. The agent fills out templates/ENGAGEMENT_RECORD.md into a concrete record file
    (e.g. engagement_records/2026-06-07_force_send2002.md), completing EVERY section
    with binary-grounded evidence -- including the "is the game legitimately WAITING?"
    section that rules out the exact trap above.
 2. The agent presents that record to the USER and asks for explicit approval to run a
    NAMED tool.
 3. ONLY the user (or the agent acting on the user's explicit, in-session "approved:
    run <tool>" instruction) creates/updates the approval token:
        python tools/harness_gate.py approve <tool_name> <record_path> [--ttl-min N]
    e.g.
        python tools/harness_gate.py approve force_send2002 engagement_records/2026-06-07_force_send2002.md
    This writes tools/.engagement_approved (a small JSON) authorizing exactly ONE tool,
    once, until it expires or is consumed.
 4. The injector, on startup, calls require_approval("force_send2002") which validates
    the token (right tool, not expired, record exists) and -- by default -- CONSUMES it
    (single-shot) so a stale approval can't silently authorize a second, different run.

The gate token is intentionally NOT committed (see .gitignore handling below); it is a
local, per-action capability, not project state.

CLI
---
  python tools/harness_gate.py status
        Show the current token (tool, record, who, expiry, consumed?) or "no approval".
  python tools/harness_gate.py approve <tool> <record_path> [--ttl-min N] [--multi]
        Create/replace the approval token for <tool>, referencing <record_path>
        (which MUST exist and be non-trivial). Default TTL = 30 min, single-shot.
        --multi makes it NOT auto-consume (still TTL-bounded) -- use sparingly, e.g. a
        deliberately repeated diagnostic; the default and the safe choice is single-shot.
  python tools/harness_gate.py revoke
        Delete the token (close the gate now).

API (for injectors)
-------------------
  from harness_gate import require_approval
  require_approval("force_send2002")   # call FIRST in main(); aborts (SystemExit) if not approved.
"""
import json
import os
import sys
import time

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
TOKEN_PATH = os.path.join(_THIS_DIR, ".engagement_approved")
HARNESS_DOC = os.path.join(_REPO_ROOT, "HARNESS.md")
TEMPLATE_REL = os.path.join("templates", "ENGAGEMENT_RECORD.md")

DEFAULT_TTL_MIN = 30
# A record must be a real, filled document -- not an empty stub. Cheap heuristic floor.
MIN_RECORD_BYTES = 600


# ----------------------------------------------------------------------------- helpers
def _now():
    return int(time.time())


def _load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    try:
        with open(TOKEN_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001 -- a corrupt token must NOT be treated as approval
        return {"_corrupt": str(e)}


def _save_token(tok):
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(tok, f, indent=2)


def _fmt_ts(ts):
    if not ts:
        return "?"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _resolve_record(record_path):
    """Resolve a record path relative to CWD or repo root; return absolute path or None."""
    cands = [record_path,
             os.path.join(_REPO_ROOT, record_path),
             os.path.join(_THIS_DIR, record_path)]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


# ------------------------------------------------------------------- the enforcement API
def require_approval(tool_name, consume=None):
    """Abort (raise SystemExit) unless a valid, matching, fresh Engagement-Record token exists.

    Call this as the FIRST statement in a state-mutating tool's main(), before opening the
    process / allocating / writing / creating a remote thread.

    tool_name : the canonical name the approval must reference (e.g. "force_send2002").
    consume   : override single-shot behaviour; default = honour the token's own 'multi' flag
                (single-shot unless the approver passed --multi).

    On success, prints a short banner and (for single-shot tokens) consumes the token.
    On failure, prints exactly WHY and how to open the gate, then raises SystemExit(90).
    """
    def _deny(reason, extra=""):
        sys.stderr.write(
            "\n"
            "==================== HARNESS MUTATION GATE: BLOCKED ====================\n"
            f"  tool          : {tool_name}\n"
            f"  reason        : {reason}\n"
            f"{extra}"
            "  This tool performs a STATE-MUTATING action on the live game / binary /\n"
            "  wire protocol. Per HARNESS.md it may NOT run without an APPROVED\n"
            "  Engagement Record for THIS tool.\n"
            "\n"
            "  To proceed (the ONLY sanctioned path):\n"
            f"   1. Fill {TEMPLATE_REL} into a concrete record (every section, with\n"
            "      binary addresses + read-only live evidence). Critically answer:\n"
            "      'Is the game legitimately WAITING for something we should instead\n"
            "       provide through its real mechanism?' -- and rule it out.\n"
            "   2. Get the USER's explicit approval to run this tool.\n"
            "   3. The user (or you on the user's explicit in-session instruction) runs:\n"
            f"        python tools/harness_gate.py approve {tool_name} <record_path>\n"
            "   4. Re-run this tool.\n"
            f"  See {os.path.relpath(HARNESS_DOC, _THIS_DIR)} (repo root HARNESS.md).\n"
            "=======================================================================\n\n"
        )
        raise SystemExit(90)

    tok = _load_token()
    if tok is None:
        _deny("no Engagement Record has been approved (no tools/.engagement_approved token).")
    if "_corrupt" in tok:
        _deny(f"the approval token is unreadable/corrupt ({tok['_corrupt']}); refusing to assume approval.")
    if not tok.get("approved", False):
        _deny("the approval token exists but is not marked approved=true.")

    tok_tool = tok.get("tool")
    if tok_tool != tool_name:
        _deny(f"the approval is for a DIFFERENT tool ('{tok_tool}'), not '{tool_name}'.",
              extra="  (One approval authorizes exactly one named tool. Approve THIS tool explicitly.)\n")

    exp = tok.get("expires_at", 0)
    if exp and _now() > exp:
        _deny(f"the approval EXPIRED at {_fmt_ts(exp)} (now {_fmt_ts(_now())}). Re-approve.")

    if tok.get("consumed", False):
        _deny("this single-shot approval was already CONSUMED by a prior run. Re-approve for another run.")

    rec = tok.get("record")
    rec_abs = _resolve_record(rec) if rec else None
    if not rec_abs:
        _deny(f"the referenced Engagement Record was not found: {rec!r}. "
              "Approval must point at a real, filled record file.")
    try:
        if os.path.getsize(rec_abs) < MIN_RECORD_BYTES:
            _deny(f"the Engagement Record {rec!r} is too small "
                  f"(< {MIN_RECORD_BYTES} bytes) to be a completed record -- fill it out fully.")
    except OSError as e:
        _deny(f"could not stat the Engagement Record {rec!r}: {e}")

    # ---- approved ----
    do_consume = (not tok.get("multi", False)) if consume is None else consume
    sys.stderr.write(
        "\n--------------------- HARNESS MUTATION GATE: APPROVED ---------------------\n"
        f"  tool   : {tool_name}\n"
        f"  record : {rec}\n"
        f"  by     : {tok.get('approved_by', '?')}   at {_fmt_ts(tok.get('approved_at'))}\n"
        f"  expires: {_fmt_ts(exp) if exp else 'no-expiry'}   mode: "
        f"{'MULTI (not consumed)' if tok.get('multi') else 'single-shot'}\n"
        "  Proceeding with the state-mutating action. Verify the expected observable\n"
        "  READ-ONLY afterward; a visibly 'working' FORCED result is NOT a solution.\n"
        "---------------------------------------------------------------------------\n\n"
    )
    if do_consume:
        tok["consumed"] = True
        tok["consumed_at"] = _now()
        try:
            _save_token(tok)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[harness_gate] WARNING: could not mark token consumed: {e}\n")
    return True


# ------------------------------------------------------------------------------ CLI verbs
def _cmd_status(_args):
    tok = _load_token()
    if tok is None:
        print("[harness_gate] NO approval token (gate CLOSED). No state-mutating tool may run.")
        return 0
    if "_corrupt" in tok:
        print(f"[harness_gate] token is CORRUPT: {tok['_corrupt']} (treated as no-approval).")
        return 0
    exp = tok.get("expires_at", 0)
    live = tok.get("approved") and not tok.get("consumed") and (not exp or _now() <= exp)
    print("[harness_gate] approval token:")
    print(f"    tool        : {tok.get('tool')}")
    print(f"    record      : {tok.get('record')}")
    print(f"    approved    : {tok.get('approved')}  by {tok.get('approved_by')} at {_fmt_ts(tok.get('approved_at'))}")
    print(f"    expires_at  : {_fmt_ts(exp) if exp else 'no-expiry'}")
    print(f"    mode        : {'MULTI' if tok.get('multi') else 'single-shot'}")
    print(f"    consumed    : {tok.get('consumed', False)}"
          + (f" at {_fmt_ts(tok.get('consumed_at'))}" if tok.get("consumed") else ""))
    print(f"    => gate is  : {'OPEN for that tool' if live else 'CLOSED (expired/consumed/none)'}")
    return 0


def _cmd_approve(args):
    if len(args) < 2:
        print("usage: harness_gate.py approve <tool> <record_path> [--ttl-min N] [--multi]")
        return 2
    tool = args[0]
    record_path = args[1]
    ttl_min = DEFAULT_TTL_MIN
    multi = False
    rest = args[2:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--multi":
            multi = True
        elif a == "--ttl-min" and i + 1 < len(rest):
            try:
                ttl_min = int(rest[i + 1]); i += 1
            except ValueError:
                print(f"[harness_gate] bad --ttl-min value: {rest[i + 1]!r}"); return 2
        else:
            print(f"[harness_gate] unknown arg: {a!r}"); return 2
        i += 1

    rec_abs = _resolve_record(record_path)
    if not rec_abs:
        print(f"[harness_gate] REFUSED: Engagement Record not found: {record_path!r}")
        print("    Create it from templates/ENGAGEMENT_RECORD.md and fill EVERY section first.")
        return 3
    if os.path.getsize(rec_abs) < MIN_RECORD_BYTES:
        print(f"[harness_gate] REFUSED: {record_path!r} is < {MIN_RECORD_BYTES} bytes "
              "-- that is not a completed Engagement Record. Fill it out.")
        return 3

    who = (os.environ.get("HARNESS_APPROVER")
           or os.environ.get("USERNAME") or os.environ.get("USER") or "unknown")
    now = _now()
    tok = {
        "approved": True,
        "tool": tool,
        "record": os.path.relpath(rec_abs, _REPO_ROOT).replace("\\", "/"),
        "approved_by": who,
        "approved_at": now,
        "expires_at": now + ttl_min * 60,
        "multi": multi,
        "consumed": False,
        "_note": "Created by harness_gate approve. See HARNESS.md. Delete to close the gate.",
    }
    _save_token(tok)
    print("[harness_gate] APPROVED and gate OPENED:")
    print(f"    tool   : {tool}")
    print(f"    record : {tok['record']}")
    print(f"    by     : {who}")
    print(f"    expires: {_fmt_ts(tok['expires_at'])}  ({ttl_min} min)")
    print(f"    mode   : {'MULTI (repeatable until expiry)' if multi else 'single-shot (consumed on first run)'}")
    print(f"    token  : {TOKEN_PATH}")
    print("    Reminder: a forced/injected result is a DIAGNOSTIC, never a reported 'fix'.")
    return 0


def _cmd_revoke(_args):
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
        print(f"[harness_gate] token deleted; gate CLOSED ({TOKEN_PATH}).")
    else:
        print("[harness_gate] no token present; gate already CLOSED.")
    return 0


def main(argv):
    verbs = {"status": _cmd_status, "approve": _cmd_approve, "revoke": _cmd_revoke}
    if not argv or argv[0] not in verbs:
        print(__doc__)
        print("verbs: status | approve <tool> <record> [--ttl-min N] [--multi] | revoke")
        return 0
    return verbs[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
