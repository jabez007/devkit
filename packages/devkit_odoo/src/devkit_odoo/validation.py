"""Bounded offline checks; never import addons or evaluate manifest expressions."""

import ast
import time
from pathlib import Path
from typing import cast

from devkit.contracts import Context, DevkitError, JSONObject
from devkit.schemas import validate

from devkit_odoo.dependencies import external_dependencies, module_dependencies

STRINGS: JSONObject = {"type": "array", "items": {"type": "string", "minLength": 1}}
MANIFEST_SCHEMA: JSONObject = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "author": {"type": "string"},
        "license": {"type": "string"},
        "version": {"type": "string", "pattern": r"^(19\.0\.)?[0-9]+\.[0-9]+(\.[0-9]+)?$"},
        "data": STRINGS,
        "demo": STRINGS,
        "installable": {"type": "boolean"},
        "application": {"type": "boolean"},
        "auto_install": {"anyOf": [{"type": "boolean"}, STRINGS]},
    },
}


def contained(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Path must be relative and cannot traverse parents")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Symlink escapes the allowed directory")
    return resolved


def checkpoint(context: Context) -> None:
    if context.cancellation.is_set():
        raise DevkitError("CANCELLED", "Validation cancelled")
    if time.monotonic() > context.deadline:
        raise DevkitError("TIMEOUT", "Validation deadline exceeded")


def read_manifest(module: Path) -> JSONObject:
    path = contained(module, "__manifest__.py")
    with path.open("rb") as stream:
        content = stream.read(262_145)
    if len(content) > 262_144:
        raise ValueError("Manifest exceeds 256 KiB")
    tree = ast.parse(content, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 10_000:
        raise ValueError("Manifest exceeds syntax complexity limit")
    try:
        value = ast.literal_eval(tree)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Manifest expressions must be literal values; code is never executed"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError("Manifest must be a dictionary")
    for field, schema in MANIFEST_SCHEMA["properties"].items():
        if field not in value and field not in MANIFEST_SCHEMA["required"]:
            continue
        try:
            validate(value.get(field), schema)
        except Exception as exc:
            raise ValueError(
                f"Invalid manifest field '{field}'; check its type and Odoo 19 format"
            ) from exc
    return cast(JSONObject, value)


def inspect_module(
    name: str,
    module: Path,
    available: dict[str, Path],
    context: Context,
    policy: JSONObject,
) -> JSONObject:
    result: JSONObject = {
        "module": name,
        "errors": [],
        "unresolved_dependencies": [],
        "checked_files": [],
        "path": module.relative_to(context.project_root).as_posix(),
        "dependencies": [],
        "external_dependencies": [],
    }
    try:
        manifest = read_manifest(module)
    except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
        message = (
            str(exc)
            if isinstance(exc, ValueError) and not isinstance(exc, SyntaxError)
            else "Manifest must contain bounded literal metadata; expressions are not executed"
        )
        result["errors"].append(message[:512])
        return result
    except OSError:
        result["errors"].append("Cannot read __manifest__.py; check file permissions")
        return result
    result["version"] = manifest.get("version", "1.0")
    result["auto_install"] = manifest.get("auto_install", False)
    result["dependencies"] = module_dependencies(
        name, manifest, available, context.project_root, policy
    )
    result["external_dependencies"] = external_dependencies(manifest)
    result["unresolved_dependencies"] = sorted(
        {
            item["name"]
            for item in result["dependencies"]
            if item["status"] in {"missing", "unknown"}
        }
    )
    result["errors"].extend(
        item["message"]
        for item in result["dependencies"] + result["external_dependencies"]
        if item["status"] == "invalid"
    )
    _check_triggers(manifest, result)
    _check_files(module, manifest, context, result)
    return result


def _check_triggers(manifest: JSONObject, result: JSONObject) -> None:
    triggers = manifest.get("auto_install", False)
    dependencies = {edge["name"] for edge in result["dependencies"] if edge["status"] != "invalid"}
    if isinstance(triggers, list) and not set(triggers) <= dependencies:
        result["errors"].append("auto_install triggers must be declared or implicit dependencies")


def _check_files(module: Path, manifest: JSONObject, context: Context, result: JSONObject) -> None:
    for filename in manifest.get("data", []) + manifest.get("demo", []):
        checkpoint(context)
        try:
            path = contained(module, filename)
            if not path.is_file():
                raise ValueError("Missing file")
            result["checked_files"].append(filename)
        except (OSError, ValueError):
            result["errors"].append(f"Missing or unsafe declared file: {filename}")
