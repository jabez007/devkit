"""CLI parsing and rendering. Operations belong to CommandService."""

import argparse
import json
import shlex
from pathlib import Path

from devkit import __version__
from devkit.app import create_service
from devkit.contracts import EXIT_CODES, CommandResult, DevkitError, JSONObject
from devkit.discovery import discover
from devkit.evidence import redact
from devkit.runs_cli import add_runs_parser, dispatch_runs


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="devkit")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument("--timeout", type=float)
    result.add_argument("--json", action="store_true")
    sub = result.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    sub.add_parser("commands")
    add_runs_parser(sub.add_parser("runs"))
    check = sub.add_parser("check")
    check.add_argument("profile")
    plugins = sub.add_parser("plugins")
    plugins.add_argument("operation", choices=["list", "validate"], default="list", nargs="?")
    run = sub.add_parser("run")
    run.add_argument("command")
    run.add_argument("--args", default="{}", help="JSON object")
    return result


def dispatch(args: argparse.Namespace) -> JSONObject:
    if args.action == "runs":
        return dispatch_runs(args)
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
    try:
        arguments = json.loads(args.args) if args.action == "run" else {}
    except json.JSONDecodeError as exc:
        raise DevkitError("INVALID_INPUT", "--args must contain a valid JSON object") from exc
    if not isinstance(arguments, dict):
        raise DevkitError("INVALID_INPUT", "Arguments must be a JSON object")
    command = args.command if args.action == "run" else "core.doctor"
    if args.action == "check":
        command, arguments = "core.check", {"profile": args.profile}
    return service.execute(command, arguments, surface="cli")


def render_checks(envelope: JSONObject, action: str) -> None:
    """Expose existing core aggregate diagnostics without interpreting plugin data."""
    if action not in {"doctor", "check"}:
        return
    for check in envelope["result"]["data"].get("checks", []):
        result = check["result"]
        print(f"  {check['check']}: {result['status']}: {result['summary']}")
        if result.get("reason"):
            print(f"    Reason: {result['reason']}")
        project = shlex.quote(envelope["project_root"])
        print(f"    Inspect: devkit --project {project} runs show {check['run_id']}")


def render(envelope: JSONObject, action: str) -> None:
    result = envelope["result"]
    print(f"{result['status']}: {result['summary']}")
    if result.get("reason"):
        print(f"Reason: {result['reason']}")
    for command in result["data"].get("commands", []) if action == "commands" else []:
        print(f"  {command}")
    for plugin in result["data"].get("plugins", []) if action == "plugins" else []:
        print(f"  {plugin['id']} ({plugin['distribution']} {plugin['version']})")
    render_checks(envelope, action)
    if envelope.get("evidence_path"):
        print(f"Evidence: {envelope['evidence_path']}")
    if action == "runs":
        print(json.dumps(result["data"], indent=2))


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
                    redact(str(exc)[:2048])
                    if isinstance(exc, DevkitError)
                    else "Cannot read project or configuration; check --project and settings files",
                    reason=exc.reason if isinstance(exc, DevkitError) else "INVALID_CONFIG",
                )
            )
        }
    if args.json:
        print(json.dumps(envelope, allow_nan=False))
    else:
        render(envelope, args.action)
    return EXIT_CODES[envelope["result"]["status"]]
