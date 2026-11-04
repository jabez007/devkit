"""Native pack brief commands. Task state stays in Beads; brief text stays in artifacts."""

import argparse
import json

from brief_format import BriefError, findings, load


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
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except BriefError as error:
        result = {"status": "error", "reason": error.reason}
    except OSError:
        result = {"status": "blocked", "reason": "BRIEF_UNAVAILABLE"}
    except (TypeError, ValueError, RecursionError):
        result = {"status": "error", "reason": "INVALID_BRIEF"}
    print(json.dumps(result))
    return {"success": 0, "failed": 1, "blocked": 2, "error": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
