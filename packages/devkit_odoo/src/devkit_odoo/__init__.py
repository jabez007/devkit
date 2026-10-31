"""Odoo 19 offline manifest validation plugin."""

import json
from importlib.metadata import version

from devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    DevkitError,
    JSONObject,
    Specialization,
)
from devkit.schemas import validate

from devkit_odoo.inventory import Inventory, scan
from devkit_odoo.validation import checkpoint, inspect_module

INPUT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "addons_paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 1024},
            "uniqueItems": True,
        },
        "module": {"type": "string", "pattern": r"^\w{1,256}$"},
        "target_version": {"const": "19.0"},
        "strict_dependencies": {"type": "boolean"},
        "inventory": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "complete": {"type": "boolean"},
                "complete_prefixes": {
                    "type": "array",
                    "maxItems": 32,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": r"^\w{1,256}$"},
                },
            },
        },
    },
}

OUTPUT_SCHEMA: JSONObject = {
    "type": "object",
    "required": [
        "validation_schema_version",
        "modules",
        "inventory",
        "dependency_counts",
        "not_checked",
        "inspection_complete",
    ],
    "properties": {
        "validation_schema_version": {"const": "1.1"},
        "inventory": {
            "type": "object",
            "required": ["complete", "complete_prefixes", "scan_complete", "paths", "module_count"],
        },
        "modules": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["module", "dependencies", "errors"],
                "properties": {
                    "dependencies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "status", "path", "implicit"],
                            "properties": {
                                "status": {"enum": ["resolved", "missing", "unknown", "invalid"]}
                            },
                        },
                    },
                },
            },
        },
        "dependency_counts": {
            "type": "object",
            "required": ["resolved", "missing", "unknown", "invalid"],
        },
        "inspection_complete": {"type": "boolean"},
        "not_checked": {"type": "array", "items": {"type": "string"}},
    },
}


def _data(inventory: Inventory, policy: JSONObject, *, scanned: bool = True) -> JSONObject:
    return {
        "validation_schema_version": "1.1",
        "target_profile": "19.0",
        "validator_version": version("devkit-odoo"),
        "modules": [],
        "inventory": inventory.coverage(policy, scan_complete=scanned),
        "inspection_complete": False,
        "coverage": [
            "literal manifests",
            "selected field types",
            "data/demo file paths",
            "direct module dependency presence",
        ],
        "not_checked": [
            "runtime",
            "database",
            "XML semantics",
            "assets",
            "external dependencies",
            "transitive dependencies",
            "dependency cycles",
        ],
        "dependency_counts": dict.fromkeys(("resolved", "missing", "unknown", "invalid"), 0),
    }


def check(context: Context, arguments: JSONObject) -> CommandResult:
    options = {**context.settings.get("odoo", {}), **arguments}
    try:
        validate(options, INPUT_SCHEMA)
    except Exception:
        return CommandResult(
            "error",
            "Invalid Odoo configuration; check [options.odoo] names, types, "
            "and target_version=19.0",
            reason="INVALID_CONFIG",
        )
    policy = {"complete": False, "complete_prefixes": [], **options.get("inventory", {})}
    inventory = Inventory()
    try:
        scan(context, options.get("addons_paths", ["addons"]), inventory)
    except DevkitError as exc:
        return _scan_failure(exc, _data(inventory, policy, scanned=False))
    selected = options.get("module")
    names = [selected] if selected else sorted(inventory.modules)
    data = _data(inventory, policy)
    if not names or any(name not in inventory.modules for name in names):
        return CommandResult(
            "blocked", "No matching addons; check module and addons_paths", data, "MISSING_ADDONS"
        )
    return _inspect(context, names, inventory, data, options.get("strict_dependencies", False))


def _scan_failure(error: DevkitError, data: JSONObject) -> CommandResult:
    if error.reason == "INVALID_ADDONS":
        return CommandResult("failed", str(error), data, error.reason)
    if error.reason in {"MISSING_ADDONS", "INVENTORY_UNAVAILABLE"}:
        return CommandResult("blocked", str(error), data, error.reason)
    if error.reason == "CANCELLED":
        return CommandResult("cancelled", str(error), data, error.reason)
    return CommandResult("error", str(error), data, error.reason)


def _inspect(
    context: Context,
    names: list[str],
    inventory: Inventory,
    data: JSONObject,
    strict: bool,
) -> CommandResult:
    size = 0
    for name in names:
        try:
            checkpoint(context)
            finding = inspect_module(
                name, inventory.modules[name], inventory.modules, context, data["inventory"]
            )
        except DevkitError as exc:
            return _scan_failure(exc, data)
        size += len(json.dumps(finding))
        if size > 600000:
            return CommandResult(
                "error",
                "Validation output exceeds limit; select one module with --args",
                data,
                "RESULT_LIMIT",
            )
        data["modules"].append(finding)
        for edge in finding["dependencies"]:
            data["dependency_counts"][edge["status"]] += 1
    data["inspection_complete"] = True
    return _outcome(data, strict)


def _summary(data: JSONObject, action: str) -> str:
    counts = ", ".join(f"{count} {status}" for status, count in data["dependency_counts"].items())
    names = ", ".join(item["module"] for item in data["modules"])
    lines = [
        f"Examined {len(data['modules'])} modules; dependencies: {counts}.",
        f"Modules: {names[:500]}",
    ]
    for finding in data["modules"]:
        issues = list(finding["errors"])
        issues.extend(
            f"{edge['status']}: {edge['name']}"
            for edge in finding["dependencies"]
            if edge["status"] in {"missing", "unknown"}
        )
        if issues and len(lines) < 10:
            lines.append(f"{finding['module']}: {'; '.join(issues)[:240]}")
    lines.extend([action, "Not checked: " + ", ".join(data["not_checked"])])
    return "\n".join(lines)[:4096]


def _outcome(data: JSONObject, strict: bool) -> CommandResult:
    counts = data["dependency_counts"]
    if counts["invalid"]:
        return CommandResult(
            "failed",
            _summary(data, "Correct invalid depends declarations in __manifest__.py."),
            data,
            "INVALID_DEPENDENCIES",
        )
    if any(item["errors"] for item in data["modules"]):
        return CommandResult(
            "failed",
            _summary(data, "Correct the reported manifest fields or declared files."),
            data,
            "INVALID_MANIFEST",
        )
    if counts["missing"]:
        return CommandResult(
            "failed",
            _summary(
                data, "Restore missing addons or correct the explicit inventory completeness claim."
            ),
            data,
            "MISSING_DEPENDENCIES",
        )
    if strict and counts["unknown"]:
        return CommandResult(
            "blocked",
            _summary(
                data,
                "Add dependency sources to addons_paths; "
                "incomplete coverage is not a module defect.",
            ),
            data,
            "INCOMPLETE_INVENTORY",
        )
    action = (
        "Static checks passed; unknown dependencies remain unverified."
        if counts["unknown"]
        else "Direct dependency presence verified; runtime compatibility is unverified."
    )
    return CommandResult("success", _summary(data, action), data)


def register() -> Specialization:
    return Specialization(
        "odoo",
        (
            CommandSpec(
                "odoo.module.validate",
                "Validate Odoo addon manifests offline",
                check,
                input_schema=INPUT_SCHEMA,
                output_schema=OUTPUT_SCHEMA,
                effects=frozenset({"read_fs"}),
            ),
        ),
        checks=(CheckSpec("odoo.manifests", "odoo.module.validate"),),
    )
