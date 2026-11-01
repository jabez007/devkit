"""Odoo 19 offline manifest validation plugin."""

import json
from importlib.metadata import version

from mccann_hub.devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    DevkitError,
    JSONObject,
    Specialization,
)
from mccann_hub.devkit.schemas import validate
from mccann_hub.devkit_odoo.csv_inspection import LIMITS as CSV_LIMITS
from mccann_hub.devkit_odoo.csv_inspection import CSVInspection
from mccann_hub.devkit_odoo.dependencies import analyze_graph
from mccann_hub.devkit_odoo.inventory import Inventory, scan
from mccann_hub.devkit_odoo.validation import checkpoint, inspect_module
from mccann_hub.devkit_odoo.xml_inspection import LIMITS as XML_LIMITS
from mccann_hub.devkit_odoo.xml_inspection import PARSER_VERSION, XMLInspection

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

DATA_FILE_SCHEMA: JSONObject = {
    "type": "object",
    "required": ["files", "complete"],
    "properties": {
        "complete": {"type": "boolean"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "phase", "status", "reason"],
                "properties": {"status": {"enum": ["valid", "invalid", "blocked"]}},
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
        "dependency_graph",
        "not_checked",
        "inspection_complete",
        "xml_counts",
        "xml_reference_counts",
        "csv_counts",
        "csv_reference_counts",
    ],
    "properties": {
        "validation_schema_version": {"const": "1.4"},
        "inventory": {
            "type": "object",
            "required": ["complete", "complete_prefixes", "scan_complete", "paths", "module_count"],
        },
        "modules": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "module",
                    "dependencies",
                    "dependencies_inspected",
                    "errors",
                    "xml",
                    "csv",
                ],
                "properties": {
                    "dependencies_inspected": {"type": "boolean"},
                    "xml": DATA_FILE_SCHEMA,
                    "csv": DATA_FILE_SCHEMA,
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
        "dependency_graph": {
            "type": "object",
            "required": ["status", "scope", "cycle"],
            "properties": {
                "status": {"enum": ["not_checked", "cycle", "no_cycle_observed"]},
                "scope": {"const": "inspected_manifests"},
                "cycle": {"type": "array", "items": {"type": "string"}},
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
        "validation_schema_version": "1.4",
        "target_profile": "19.0",
        "validator_version": version("mccann-hub-devkit-odoo"),
        "modules": [],
        "inventory": inventory.coverage(policy, scan_complete=scanned),
        "inspection_complete": False,
        "coverage": [
            "literal manifests",
            "selected field types",
            "data/demo file paths",
            "direct module dependency presence",
            "dependency cycles among inspected manifests",
            "declared XML syntax",
            "literal XML/CSV reference ordering",
            "flat CSV structure and identifier declarations",
        ],
        "not_checked": [
            "runtime",
            "database",
            "XML runtime semantics and XPath validity",
            "dynamic XML references and embedded view content",
            "CSV runtime fields, conversions and relational cardinality",
            "assets",
            "external dependencies",
            "transitive dependencies",
            "cycles through uninspected manifests or unresolved dependencies",
        ],
        "csv_counts": dict.fromkeys(("valid", "invalid", "blocked"), 0),
        "csv_limits": CSV_LIMITS,
        "csv_reference_counts": {"resolved": 0, "unknown": 0},
        "xml_counts": dict.fromkeys(("valid", "invalid", "blocked"), 0),
        "xml_limits": XML_LIMITS,
        "xml_parser": {"name": "expat", "version": PARSER_VERSION},
        "xml_reference_counts": {"resolved": 0, "unknown": 0},
        "dependency_graph": {"status": "not_checked", "scope": "inspected_manifests", "cycle": []},
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
    try:
        return _inspect(context, names, inventory, data, options.get("strict_dependencies", False))
    except DevkitError as exc:
        return _scan_failure(exc, data)


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
    inspectors: dict[str, XMLInspection | CSVInspection] = {
        "xml": XMLInspection(lambda: checkpoint(context)),
        "csv": CSVInspection(lambda: checkpoint(context)),
    }
    for name in names:
        checkpoint(context)
        finding = inspect_module(
            name,
            inventory.modules[name],
            inventory.modules,
            context,
            data["inventory"],
            inspectors,
        )
        size += len(json.dumps(finding))
        if size > 600000:
            return CommandResult(
                "error",
                "Validation output exceeds limit; select one module with --args",
                data,
                "RESULT_LIMIT",
            )
        data["modules"].append(finding)
        for kind in inspectors:
            for file in finding[kind]["files"]:
                data[f"{kind}_counts"][file["status"]] += 1
            for status, count in finding[kind]["reference_counts"].items():
                data[f"{kind}_reference_counts"][status] += count
        for edge in finding["dependencies"]:
            data["dependency_counts"][edge["status"]] += 1
    data["dependency_graph"] = analyze_graph(
        data["modules"], inventory.modules, lambda: checkpoint(context)
    )
    data["inspection_complete"] = True
    return _outcome(data, strict)


def _summary(data: JSONObject, action: str) -> str:
    counts = ", ".join(f"{count} {status}" for status, count in data["dependency_counts"].items())
    names = ", ".join(item["module"] for item in data["modules"])
    lines = [
        f"Examined {len(data['modules'])} modules; dependencies: {counts}.",
        f"Modules: {names[:500]}",
        "XML files: " + ", ".join(f"{n} {status}" for status, n in data["xml_counts"].items()),
        "CSV files: " + ", ".join(f"{n} {status}" for status, n in data["csv_counts"].items()),
        "CSV references: "
        + ", ".join(f"{n} {status}" for status, n in data["csv_reference_counts"].items()),
        "XML references: "
        + ", ".join(f"{n} {status}" for status, n in data["xml_reference_counts"].items()),
    ]
    graph = data["dependency_graph"]
    lines.append(
        f"Dependency graph: {graph['status'].replace('_', ' ')} among "
        f"{graph['node_count']} inspected manifests; "
        f"{len(graph['uninspected_modules'])} inventory modules uninspected; "
        f"{sum(graph['excluded_edge_counts'].values())} declarations excluded."
    )
    if graph["cycle"]:
        lines.append("Cycle: " + " -> ".join(graph["cycle"])[:500])
    for finding in data["modules"]:
        issues = list(finding["errors"])
        issues.extend(
            f"{file['path']}:{file['line'] or '?'}:{file['column'] or '?'}: {file['message']}"
            for kind in ("xml", "csv")
            for file in finding[kind]["files"]
            if file["status"] != "valid"
        )
        issues.extend(
            f"{file['path']}:{ref['line']}:{ref['column']}: unknown XML ID "
            f"{ref['value']} ({ref['reason']})"
            for kind in ("xml", "csv")
            for file in finding[kind]["files"]
            for ref in file["references"]
            if ref["status"] == "unknown"
        )
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
    invalid = next((kind for kind in ("xml", "csv") if data[f"{kind}_counts"]["invalid"]), None)
    if invalid:
        return CommandResult(
            "failed",
            _summary(data, f"Correct invalid {invalid.upper()} at the reported location."),
            data,
            f"INVALID_{invalid.upper()}",
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
    if data["dependency_graph"]["cycle"]:
        return CommandResult(
            "failed",
            _summary(
                data, "Remove circular depends declarations in the listed __manifest__.py files."
            ),
            data,
            "DEPENDENCY_CYCLE",
        )
    blocked = next(
        (
            file
            for module in data["modules"]
            for kind in ("xml", "csv")
            for file in module[kind]["files"]
            if file["status"] == "blocked"
        ),
        None,
    )
    if blocked:
        return CommandResult(
            "blocked",
            _summary(data, "Data-file inspection is incomplete; review the diagnostics."),
            data,
            blocked["reason"],
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
