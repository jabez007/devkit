"""CLI parsing and rendering. Operations belong to CommandService."""

import argparse
import json
from pathlib import Path

from devkit import __version__
from devkit.app import create_service
from devkit.contracts import EXIT_CODES, CommandResult, DevkitError, JSONObject


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="devkit")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument("--timeout", type=float)
    result.add_argument("--json", action="store_true")
    sub = result.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    sub.add_parser("commands")
    run = sub.add_parser("run")
    run.add_argument("command")
    run.add_argument("--args", default="{}", help="JSON object")
    return result


def dispatch(args: argparse.Namespace) -> JSONObject:
    service = create_service(args.project, args.timeout)
    if args.action == "commands":
        return {
            "result": {
                "status": "success",
                "summary": "Available commands",
                "data": {"commands": sorted(service.commands)},
                "reason": None,
            }
        }
    arguments = json.loads(args.args) if args.action == "run" else {}
    command = args.command if args.action == "run" else "core.doctor"
    return service.execute(command, arguments, surface="cli")


def main() -> int:
    args = parser().parse_args()
    try:
        envelope = dispatch(args)
    except (DevkitError, OSError, ValueError) as exc:
        from dataclasses import asdict

        envelope = {
            "result": asdict(
                CommandResult(
                    "error",
                    "Invalid configuration or arguments",
                    reason=exc.reason if isinstance(exc, DevkitError) else "INVALID_CONFIG",
                )
            )
        }
    if args.json:
        print(json.dumps(envelope, allow_nan=False))
    else:
        print(f"{envelope['result']['status']}: {envelope['result']['summary']}")
        if envelope.get("evidence_path"):
            print(f"Evidence: {envelope['evidence_path']}")
    return EXIT_CODES[envelope["result"]["status"]]
