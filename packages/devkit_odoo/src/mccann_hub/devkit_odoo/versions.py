"""Require explicit numeric version increases for every changed addon."""

import os
from pathlib import Path
from typing import cast

from mccann_hub.devkit.contracts import CommandResult, Context, DevkitError, JSONObject, Status
from mccann_hub.devkit.schemas import validate
from mccann_hub.devkit_odoo.inventory import Inventory, scan
from mccann_hub.devkit_odoo.validation import checkpoint, contained, parse_manifest, read_manifest
from mccann_hub.devkit_odoo.version_git import Git

EFFECTS = frozenset({"read_fs", "write_fs", "execute_process"})
INPUT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "base_commit": {"type": "string", "pattern": r"^([a-f0-9]{40}|[a-f0-9]{64})$"},
        "addons_paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 1024},
        },
    },
}
BLOCKED = {
    "MISSING_BASE_COMMIT",
    "MISSING_TOOL",
    "GIT_BASE_UNAVAILABLE",
    "GIT_OUTPUT_LIMIT",
    "UNSUPPORTED_GIT_LAYOUT",
    "BASE_MANIFEST_UNAVAILABLE",
    "MISSING_ADDONS",
    "INVENTORY_UNAVAILABLE",
    "INVENTORY_LIMIT",
}


def _options(context: Context, arguments: JSONObject) -> JSONObject:
    options = {
        "addons_paths": context.settings.get("odoo", {}).get("addons_paths", ["addons"]),
        **arguments,
    }
    if "base_commit" not in options:
        options["base_commit"] = os.environ.get("DEVKIT_BASE_COMMIT")
    if options["base_commit"] is None:
        raise DevkitError(
            "MISSING_BASE_COMMIT", "Supply an exact base_commit or DEVKIT_BASE_COMMIT"
        )
    try:
        validate(options, INPUT_SCHEMA)
    except Exception as error:
        raise DevkitError(
            "INVALID_CONFIG", "Version checks need a full base commit and addons_paths"
        ) from error
    return options


def _inventory(context: Context, paths: list[str]) -> list[Path]:
    roots = []
    for relative in paths:
        try:
            resolved = contained(context.project_root, relative)
        except (ValueError, RuntimeError) as error:
            raise DevkitError("INVALID_ADDONS", "Unsafe addon inventory path") from error
        if resolved != (context.project_root / relative).absolute():
            raise DevkitError("UNSUPPORTED_GIT_LAYOUT", "Use ordinary tracked addon directories")
        roots.append(Path(relative))
    scan(context, paths, Inventory())
    return roots


def _changed_modules(paths: list[Path], roots: list[Path]) -> list[Path]:
    modules = set()
    for path in paths:
        for root in roots:
            if path.is_relative_to(root):
                relative = path.relative_to(root)
                if relative.parts:
                    modules.add(root / relative.parts[0])
    if len(modules) > 128:
        raise DevkitError(
            "INVENTORY_LIMIT", "Narrow version inspection to at most 128 changed addons"
        )
    return sorted(modules)


def _numeric(version: str) -> tuple[int, ...]:
    # Odoo 19 adapt_version prefixes ordinary two/three-part addon versions with its series.
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) <= 3 and not version.startswith("19.0"):
        parts = (19, 0, *parts)
    while parts and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def _before(git: Git, module: Path) -> str | None:
    content = git.manifest(module)
    if content is None:
        return None
    try:
        # Native Odoo supplies 1.0 when the base manifest omits a version.
        return cast(str, parse_manifest(content).get("version", "1.0"))
    except (SyntaxError, ValueError, TypeError, RecursionError) as error:
        raise DevkitError(
            "BASE_MANIFEST_UNAVAILABLE", "Cannot compare the base manifest version"
        ) from error


def _finding(context: Context, git: Git, module: Path) -> JSONObject | None:
    path = context.project_root / module
    if path.is_symlink() or (path / "__manifest__.py").is_symlink() or (path / ".git").exists():
        raise DevkitError(
            "UNSUPPORTED_GIT_LAYOUT", "Version comparison requires ordinary addon files"
        )
    before = _before(git, module)
    present = (path / "__manifest__.py").is_file()
    if not present and before is None:
        return None
    data: JSONObject = {
        "module": module.name,
        "path": module.as_posix(),
        "before": before,
        "after": None,
        "status": "removed" if not present else "invalid",
    }
    if not present:
        return data
    try:
        data["after"] = read_manifest(path).get("version")
        if data["after"] is None:
            return data
        after = _numeric(data["after"])
        data["status"] = (
            "new" if before is None else ("bumped" if after > _numeric(before) else "unchanged")
        )
    except (OSError, SyntaxError, ValueError, TypeError, RecursionError):
        data["status"] = "invalid"
    return data


def check(context: Context, arguments: JSONObject) -> CommandResult:
    data: JSONObject = {
        "base_commit": None,
        "addons_paths": [],
        "inspection_complete": False,
        "modules": [],
    }
    try:
        options = _options(context, arguments)
        data["base_commit"] = options["base_commit"]
        data["addons_paths"] = options["addons_paths"]
        roots = _inventory(context, options["addons_paths"])
        git = Git(context, options["base_commit"])
        for module in _changed_modules(git.changed(), roots):
            checkpoint(context)
            if finding := _finding(context, git, module):
                data["modules"].append(finding)
        data["inspection_complete"] = True
        if any(item["status"] not in {"new", "bumped"} for item in data["modules"]):
            return CommandResult(
                "failed",
                "Changed addons need increased explicit versions; inspect module results",
                data,
                "VERSION_NOT_BUMPED",
            )
        return CommandResult(
            "success", f"Version comparison passed for {len(data['modules'])} changed addons", data
        )
    except DevkitError as error:
        status: Status = "blocked" if error.reason in BLOCKED else "error"
        if error.reason == "CANCELLED":
            status = "cancelled"
        elif error.reason == "INVALID_ADDONS":
            status = "failed"
        return CommandResult(status, str(error), data, error.reason)
