"""Bounded offline checks; never import addons or evaluate manifest expressions."""

import ast
from pathlib import Path
from typing import cast

from devkit.contracts import JSONObject
from devkit.schemas import validate

STRINGS: JSONObject = {"type": "array", "items": {"type": "string", "minLength": 1}}
MANIFEST_SCHEMA: JSONObject = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "author": {"type": "string"},
        "license": {"type": "string"},
        "version": {"type": "string", "pattern": r"^(19\.0\.)?[0-9]+\.[0-9]+(\.[0-9]+)?$"},
        "depends": STRINGS,
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


def manifests(project: Path, paths: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for relative in paths:
        root = contained(project, relative)
        if not root.is_dir():
            raise FileNotFoundError("Addon directory is unavailable")
        for child in sorted(root.iterdir()):
            if len(result) >= 1000:
                raise ValueError("Addon inventory exceeds 1000 modules")
            manifest = child / "__manifest__.py"
            if not manifest.is_file():
                continue
            if not child.resolve().is_relative_to(project):
                raise ValueError("Addon symlink escapes the project")
            if child.name in result:
                raise ValueError("Duplicate addon name")
            result[child.name] = child.resolve()
    return result


def read_manifest(module: Path) -> JSONObject:
    path = contained(module, "__manifest__.py")
    with path.open("rb") as stream:
        content = stream.read(262_145)
    if len(content) > 262_144:
        raise ValueError("Manifest exceeds 256 KiB")
    tree = ast.parse(content, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 10_000:
        raise ValueError("Manifest exceeds syntax complexity limit")
    value = ast.literal_eval(tree)
    validate(value, MANIFEST_SCHEMA)
    triggers = value.get("auto_install", False)
    if isinstance(triggers, list) and not set(triggers) <= set(value.get("depends", [])):
        raise ValueError("Automatic install triggers must be dependencies")
    return cast(JSONObject, value)


def inspect_module(name: str, module: Path, available: set[str]) -> JSONObject:
    result: JSONObject = {
        "module": name,
        "errors": [],
        "unresolved_dependencies": [],
        "checked_files": [],
    }
    try:
        manifest = read_manifest(module)
    except Exception:
        result["errors"].append("Manifest must contain valid bounded literal metadata")
        return result
    result["version"] = manifest.get("version", "1.0")
    dependencies = manifest.get("depends") or ([] if name == "base" else ["base"])
    result["unresolved_dependencies"] = sorted(set(dependencies) - available)
    for filename in manifest.get("data", []) + manifest.get("demo", []):
        try:
            path = contained(module, filename)
            if not path.is_file():
                raise ValueError("Missing file")
            result["checked_files"].append(filename)
        except (OSError, ValueError):
            result["errors"].append(f"Missing or unsafe declared file: {filename}")
    return result
