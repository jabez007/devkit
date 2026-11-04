"""Native pack brief commands. Task state stays in Beads; brief text stays in artifacts."""

import argparse
import json

from brief_format import BriefError, findings, load
from brief_state import approve, record, resume, show, verify
from native_state import StateError


def lint(args):
    brief, digest, _ = load(args.file, args.task)
    issues = findings(brief)
    return {
        "status": "failed" if issues else "success",
        "reason": "PRESCRIPTIVE_BRIEF" if issues else None,
        "task_id": brief["task_id"],
        "sha256": digest,
        "findings": issues,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "lint", help="Check a bounded behavior brief without changing task state"
    )
    check.add_argument("file")
    check.add_argument("--task", help="Require the explicitly selected bead identity")
    check.set_defaults(handler=lint)
    save = commands.add_parser("record", help="Bind a clean brief to one native workflow")
    save.add_argument("file")
    save.add_argument("--task", required=True)
    save.add_argument("--workflow", required=True)
    save.set_defaults(handler=record)
    view = commands.add_parser("show", help="Review the exact bound brief and its hash")
    view.add_argument("--workflow", required=True)
    view.set_defaults(handler=show)
    human = commands.add_parser("approve", help="Human approval of the exact reviewed hash")
    human.add_argument("--workflow", required=True)
    human.add_argument("--sha256", required=True)
    human.set_defaults(handler=approve)
    approved = commands.add_parser("verify", help="Verify persisted approval for the selected task")
    approved.add_argument("--workflow", required=True)
    approved.add_argument("--task", required=True)
    approved.set_defaults(handler=verify)
    continued = commands.add_parser("resume", help="Find the task's recorded native workflow")
    continued.add_argument("--task", required=True)
    continued.set_defaults(handler=resume)
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (BriefError, StateError) as error:
        blocked = {
            "HUMAN_APPROVAL_REQUIRED",
            "BRIEF_PENDING_APPROVAL",
            "BRIEF_NOT_RECORDED",
            "TASK_STATE_UNAVAILABLE",
        }
        status = "blocked" if error.reason in blocked else "error"
        if error.reason == "PRESCRIPTIVE_BRIEF":
            status = "failed"
        result = {"status": status, "reason": error.reason}
    except OSError:
        result = {"status": "blocked", "reason": "BRIEF_UNAVAILABLE"}
    except (TypeError, ValueError, RecursionError):
        result = {"status": "error", "reason": "INVALID_BRIEF"}
    print(json.dumps(result))
    return {"success": 0, "failed": 1, "blocked": 2, "error": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
