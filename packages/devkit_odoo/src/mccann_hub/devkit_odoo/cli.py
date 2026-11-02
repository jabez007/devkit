"""devkit-odoo: run the offline addon validator directly, for pre-commit hooks and CI.

It reads ``[options.odoo]`` from devkit.toml when present, and flags override those
options. The validator only reads files, so this command skips plugin selection and
operator policy, which exist to gate commands with wider effects.
"""

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from threading import Event
from uuid import uuid4

from mccann_hub.devkit.config import load_settings
from mccann_hub.devkit.contracts import EXIT_CODES, CommandResult, Context, DevkitError, JSONObject
from mccann_hub.devkit_odoo import check


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="devkit-odoo", description="Validate Odoo addons offline."
    )
    result.add_argument("--project", type=Path, default=Path.cwd())
    result.add_argument(
        "--addons-path",
        action="append",
        dest="addons_paths",
        help="Addons directory relative to the project; repeatable (default: addons)",
    )
    result.add_argument("--module", help="Validate one addon")
    result.add_argument(
        "--install-mode",
        choices=["fresh", "update"],
        help="fresh (default) fails references a new database cannot load",
    )
    result.add_argument(
        "--strict-dependencies",
        action="store_true",
        default=None,
        help="Fail when a dependency is not among the scanned addons",
    )
    result.add_argument("--timeout", type=float, help="Seconds (default: 60)")
    result.add_argument("--json", action="store_true", help="Print the result as JSON")
    return result


def validate_addons(args: argparse.Namespace) -> CommandResult:
    try:
        settings = load_settings(args.project, args.timeout)
    except (DevkitError, OSError):
        return CommandResult(
            "error",
            "Cannot read project or devkit.toml; check --project and the file",
            reason="INVALID_CONFIG",
        )
    context = Context(
        settings.project_root,
        str(uuid4()),
        time.monotonic() + settings.timeout,
        Event(),
        settings.options,
        "cli",
    )
    flags = {
        "addons_paths": args.addons_paths,
        "module": args.module,
        "install_mode": args.install_mode,
        "strict_dependencies": args.strict_dependencies,
    }
    arguments: JSONObject = {name: value for name, value in flags.items() if value is not None}
    return check(context, arguments)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    result = validate_addons(args)
    if args.json:
        print(json.dumps(asdict(result), allow_nan=False))
    else:
        reason = f" ({result.reason})" if result.reason else ""
        print(f"{result.status}{reason}\n{result.summary}")
    return EXIT_CODES[result.status]
