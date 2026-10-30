"""Odoo 19 offline manifest validation plugin."""

import time
from pathlib import Path

from devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    JSONObject,
    Specialization,
)
from devkit.schemas import validate

from devkit_odoo.validation import inspect_module, manifests

INPUT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "addons_paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "module": {"type": "string", "pattern": r"^\w{1,256}$"},
        "target_version": {"const": "19.0"},
        "strict_dependencies": {"type": "boolean"},
    },
}


def check(context: Context, arguments: JSONObject) -> CommandResult:
    options = {**context.settings.get("odoo", {}), **arguments}
    try:
        validate(options, INPUT_SCHEMA)
    except Exception:
        return CommandResult("error", "Invalid Odoo configuration", reason="INVALID_CONFIG")
    try:
        available = manifests(context.project_root, options.get("addons_paths", ["addons"]))
    except FileNotFoundError:
        return CommandResult("blocked", "Addon directory unavailable", reason="MISSING_ADDONS")
    except (OSError, ValueError):
        return CommandResult(
            "failed", "Unsafe paths or duplicate addon names", reason="INVALID_ADDONS"
        )
    selected = options.get("module")
    names = [selected] if selected else sorted(available)
    if not names or any(name not in available for name in names):
        return CommandResult("blocked", "No matching addons", reason="MISSING_ADDONS")
    return _inspect(context, names, available, options.get("strict_dependencies", False))


def _inspect(
    context: Context,
    names: list[str],
    available: dict[str, Path],
    strict: bool,
) -> CommandResult:
    findings = []
    for name in names:
        if context.cancellation.is_set():
            return CommandResult("cancelled", "Validation cancelled", reason="CANCELLED")
        if time.monotonic() > context.deadline:
            return CommandResult("error", "Validation deadline exceeded", reason="TIMEOUT")
        findings.append(inspect_module(name, available[name], set(available)))
    data = {
        "target_profile": "19.0",
        "validator_version": "0.1.0",
        "modules": findings,
        "coverage": ["literal manifests", "selected field types", "data/demo file paths"],
        "not_checked": ["runtime", "database", "XML semantics", "assets", "external dependencies"],
    }
    if any(item["errors"] for item in findings):
        return CommandResult("failed", "Static validation found errors", data, "INVALID_MANIFEST")
    if strict and any(item["unresolved_dependencies"] for item in findings):
        return CommandResult(
            "blocked", "Addon dependencies are unresolved", data, "MISSING_DEPENDENCIES"
        )
    return CommandResult("success", "Static validation completed; runtime was not checked", data)


def register() -> Specialization:
    return Specialization(
        "odoo",
        (
            CommandSpec(
                "odoo.module.validate",
                "Validate Odoo addon manifests offline",
                check,
                input_schema=INPUT_SCHEMA,
                effects=frozenset({"read_fs"}),
            ),
        ),
        checks=(CheckSpec("odoo.manifests", "odoo.module.validate"),),
    )
