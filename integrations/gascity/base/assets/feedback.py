"""Native feedback commands; humans answer assumptions, agents record evidence."""

import argparse
import json

from brief_format import BriefError
from feedback_state import answers, begin, friction, questions, show
from native_state import StateError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    start = commands.add_parser("begin")
    start.add_argument("--task", required=True)
    start.add_argument("--workflow", required=True)
    start.add_argument("--branch", required=True)
    start.add_argument("--pr")
    start.set_defaults(handler=begin)
    for name, handler in (
        ("questions", questions),
        ("answers", answers),
        ("friction", friction),
        ("show", show),
    ):
        command = commands.add_parser(name)
        if name != "show":
            command.add_argument("file")
        command.add_argument("--task", required=True)
        command.add_argument("--workflow", required=True)
        command.add_argument("--round", type=int, required=True)
        if name == "friction":
            command.add_argument("--friction-task")
        command.set_defaults(handler=handler)
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (StateError, BriefError) as error:
        result = {"status": "blocked", "reason": error.reason}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result = {"status": "blocked", "reason": "INVALID_FEEDBACK"}
    print(json.dumps(result))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
