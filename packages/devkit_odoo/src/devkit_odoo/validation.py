"""Bounded offline checks; never import addons or evaluate manifest expressions."""

import ast
import time
from pathlib import Path
from typing import cast

from devkit.contracts import Context, DevkitError, JSONObject
from devkit.schemas import validate

from devkit_odoo.csv_inspection import CSVInspection
from devkit_odoo.data_references import analyze_references
from devkit_odoo.dependencies import external_dependencies, module_dependencies
from devkit_odoo.xml_inspection import XMLInspection

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
    inspectors: dict[str, XMLInspection | CSVInspection],
) -> JSONObject:
    result: JSONObject = {
        "module": name,
        "errors": [],
        "unresolved_dependencies": [],
        "checked_files": [],
        "path": module.relative_to(context.project_root).as_posix(),
        "dependencies": [],
        "external_dependencies": [],
        **{
            kind: {
                "files": [],
                "complete": False,
                "reference_counts": {"resolved": 0, "unknown": 0},
            }
            for kind in inspectors
        },
    }
    result["xml"]["skipped_files"] = []
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
    _check_files(module, manifest, context, result, inspectors)
    analyze_references(name, {kind: result[kind] for kind in inspectors})
    return result


def _check_triggers(manifest: JSONObject, result: JSONObject) -> None:
    triggers = manifest.get("auto_install", False)
    dependencies = {edge["name"] for edge in result["dependencies"] if edge["status"] != "invalid"}
    if isinstance(triggers, list) and not set(triggers) <= dependencies:
        result["errors"].append("auto_install triggers must be declared or implicit dependencies")


def _check_files(
    module: Path,
    manifest: JSONObject,
    context: Context,
    result: JSONObject,
    inspectors: dict[str, XMLInspection | CSVInspection],
) -> None:
    load_index = 0
    for phase in ("data", "demo"):
        for filename in manifest.get(phase, []):
            entry = {"path": filename, "phase": phase, "load_index": load_index}
            load_index += 1
            _check_file(module, entry, context, result, inspectors)
    for kind in inspectors:
        result[kind]["complete"] = not result["errors"] and all(
            item["status"] == "valid" for item in result[kind]["files"]
        )


def _check_file(
    module: Path,
    entry: JSONObject,
    context: Context,
    result: JSONObject,
    inspectors: dict[str, XMLInspection | CSVInspection],
) -> None:
    filename, phase = entry["path"], entry["phase"]
    checkpoint(context)
    try:
        path = contained(module, filename)
        if not path.is_file():
            raise ValueError("Missing file")
        result["checked_files"].append(filename)
        kind = Path(filename).suffix.lower().lstrip(".")
        if kind in inspectors:
            result[kind]["files"].append(
                {
                    **inspectors[kind].inspect(path, filename, phase),
                    **entry,
                    "format": kind,
                }
            )
        else:
            result["xml"]["skipped_files"].append({**entry, "reason": "non_xml"})
    except (OSError, ValueError, RuntimeError):
        result["errors"].append(f"Missing or unsafe declared file: {filename}")
        result["xml"]["skipped_files"].append({**entry, "reason": "unavailable_file"})
