"""CLI adapter for operator-only evidence maintenance."""

import argparse
from dataclasses import asdict
from pathlib import Path

from devkit.config import state_root
from devkit.contracts import CommandResult, JSONObject
from devkit.evidence import redact
from devkit.retention import load_retention
from devkit.runs import RunStore


def add_runs_parser(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="operation", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    show = sub.add_parser("show")
    show.add_argument("run_id")
    pin = sub.add_parser("pin")
    unpin = sub.add_parser("unpin")
    for action in (pin, unpin):
        action.add_argument("run_id")
        action.add_argument("--reference", required=True)
    prune = sub.add_parser("prune")
    prune.add_argument("--older-than-days", type=float)
    prune.add_argument("--keep-last", type=int)
    prune.add_argument(
        "--apply", action="store_true", help="Delete eligible evidence; default previews"
    )
    for action in (listing, show, pin, unpin, prune):
        action.add_argument("--all-projects", action="store_true")


def dispatch_runs(args: argparse.Namespace) -> JSONObject:
    root = args.project.resolve()
    project: Path | None = None if args.all_projects else root
    store = RunStore(state_root().resolve())
    if args.operation == "list":
        data = store.list(project, args.limit, args.offset)
    elif args.operation == "show":
        data = store.show(args.run_id, project)
    elif args.operation in {"pin", "unpin"}:
        data = store.reference(
            args.run_id, redact(args.reference), project, remove=args.operation == "unpin"
        )
    else:
        settings = load_retention(root, args.older_than_days, args.keep_last)
        data = store.prune(project, settings, apply=args.apply)
    result = CommandResult("success", f"Evidence {args.operation}", redact(data))
    if data.get("errors"):
        result = CommandResult(
            "error", "Evidence pruning stopped after an error", redact(data), "PRUNE_FAILED"
        )
    return {"result": asdict(result)}
