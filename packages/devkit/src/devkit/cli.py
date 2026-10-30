"""CLI parsing and rendering. Operations belong to CommandService."""

import argparse
import json
from pathlib import Path

from devkit import __version__
from devkit.app import create_service
from devkit.contracts import EXIT_CODES, CommandResult, DevkitError, JSONObject
from devkit.discovery import discover


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="devkit")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument("--timeout", type=float)
    result.add_argument("--json", action="store_true")
    sub = result.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    sub.add_parser("commands")
    check = sub.add_parser("check")
    check.add_argument("profile")
    plugins = sub.add_parser("plugins")
    plugins.add_argument("operation", choices=["list", "validate"], default="list", nargs="?")
    run = sub.add_parser("run")
    run.add_argument("command")
    run.add_argument("--args", default="{}", help="JSON object")
    return result


def dispatch(args: argparse.Namespace) -> JSONObject:
    if args.action == "plugins" and args.operation == "list":
        return {
            "result": {
                "status": "success",
                "summary": "Installed plugins",
                "data": {
                    "plugins": [
                        {"id": item.id, "distribution": item.distribution, "version": item.version}
                        for item in discover()
                    ]
                },
                "reason": None,
            }
        }
    service = create_service(args.project, args.timeout, diagnostic=args.action == "doctor")
    if args.action == "commands":
        return {
            "result": {
                "status": "success",
                "summary": "Available commands",
                "data": {"commands": sorted(spec.id for spec in service.allowed("cli"))},
                "reason": None,
            }
        }
    arguments = json.loads(args.args) if args.action == "run" else {}
    if not isinstance(arguments, dict):
        raise DevkitError("INVALID_INPUT", "Arguments must be a JSON object")
    command = args.command if args.action == "run" else "core.doctor"
    if args.action == "check":
        command, arguments = "core.check", {"profile": args.profile}
    return service.execute(command, arguments, surface="cli")


def render(envelope: JSONObject, action: str) -> None:
    result = envelope["result"]
    print(f"{result['status']}: {result['summary']}")
    if result.get("reason"):
        print(f"Reason: {result['reason']}")
    for command in result["data"].get("commands", []) if action == "commands" else []:
        print(f"  {command}")
    for plugin in result["data"].get("plugins", []) if action == "plugins" else []:
        print(f"  {plugin['id']} ({plugin['distribution']} {plugin['version']})")
    if envelope.get("evidence_path"):
        print(f"Evidence: {envelope['evidence_path']}")


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
        render(envelope, args.action)
    return EXIT_CODES[envelope["result"]["status"]]
