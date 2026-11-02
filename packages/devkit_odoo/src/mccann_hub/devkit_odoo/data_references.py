"""Literal loader references, with explicit limits on static resolution certainty."""

import re
from collections.abc import Callable

from mccann_hub.devkit.contracts import JSONObject
from mccann_hub.devkit_odoo.models import ModelIndex

CONTAINERS = {"odoo", "openerp", "data"}
OPERATIONS = {"record", "menuitem", "template"}
# Odoo 19 loader tags that call or delete records; neither can define an XML ID.
NON_DEFINING = {"function", "delete"}
# Odoo also generates these IDs from field selections and SQL constraints, which
# this validator does not read, so their absence is never a confirmed defect.
UNREAD_GENERATED = ("selection__", "constraint_")
# Missing from the load sequence on a new database; "update" keeps them unknown.
FRESH_UNDEFINED = {"forward_definition", "demo_only_definition"}
LITERAL_ID = re.compile(r"[\w-]+(?:\.[\w-]+)?")


class LiteralReferences:
    """Collect ordered loader events, ignoring XML embedded inside views/templates."""

    def __init__(self, consume: Callable[[], None]) -> None:
        self.consume = consume
        self.stack: list[JSONObject] = []
        self.events: list[JSONObject] = []

    def start(self, name: str, attrs: dict[str, str], line: int, column: int) -> None:
        parent: JSONObject = (
            self.stack[-1] if self.stack else {"role": "root", "conditional": False}
        )
        role = _role(name, parent["role"])
        frame: JSONObject = {
            "role": role,
            "line": line,
            "column": column,
            "id": attrs.get("id", attrs.get("t-name", "") if role == "template" else ""),
            "conditional": parent["conditional"]
            or bool({"noupdate", "forcecreate", "context", "uid"} & attrs.keys()),
        }
        self.stack.append(frame)
        if role == "ignored":
            if parent["role"] in {"container", "root"}:
                # The tag name decides later whether this operation could define an ID.
                self._emit("barrier", "unsupported_loader_operation", frame, attribute=name)
            return
        self._attributes(role, attrs, frame)

    def _attributes(self, role: str, attrs: dict[str, str], frame: JSONObject) -> None:
        if "context" in attrs:
            self._emit("barrier", "dynamic_context", frame)
        if role == "field":
            self._field(attrs, frame)
        for attribute in {
            "menuitem": ("parent", "action"),
            "template": ("inherit_id", "website_id"),
        }.get(role, ()):
            if attrs.get(attribute):
                self._emit("reference", attrs[attribute], frame, attribute=attribute)
        if role in OPERATIONS and attrs.get("groups"):
            self._emit("barrier", "group_membership", frame)

    def _field(self, attrs: dict[str, str], frame: JSONObject) -> None:
        if "@" in attrs.get("name", ""):
            self._emit("barrier", "translated_field", frame)
        elif attrs.get("search"):
            self._emit("barrier", "dynamic_search", frame)
        elif attrs.get("ref"):
            self._emit("reference", attrs["ref"], frame, attribute="ref")
        elif "eval" in attrs or "file" in attrs:
            self._emit("barrier", "dynamic_field_value", frame)

    def end(self) -> None:
        frame = self.stack.pop()
        if frame["role"] in OPERATIONS and frame["id"]:
            self._emit("definition", frame["id"], frame)

    def _emit(self, kind: str, value: str, frame: JSONObject, *, attribute: str = "id") -> None:
        self.consume()
        self.events.append(
            {
                "kind": kind,
                "value": value[:512],
                "line": frame["line"],
                "column": frame["column"],
                "conditional": frame["conditional"],
                "attribute": attribute,
                "truncated": len(value) > 512,
            }
        )


def _role(name: str, parent: str) -> str:
    if parent in {"root", "container"} and name in CONTAINERS:
        return "container"
    if parent == "container" and name in OPERATIONS:
        return name
    if parent == "record" and name == "field":
        return "field"
    return "ignored"


def _identifier(module: str, event: JSONObject) -> str | None:
    value = event["value"]
    if event["truncated"] or LITERAL_ID.fullmatch(value) is None:
        return None
    return value if "." in value else f"{module}.{value}"


def analyze_references(
    module: str,
    sections: dict[str, JSONObject],
    *,
    fresh: bool,
    models: ModelIndex,
    hooks_define_ids: bool,
) -> None:
    """Resolve literal references; a fresh install marks confirmed absences undefined."""
    inspected = [file for section in sections.values() for file in section["files"]]
    absence_certain = not hooks_define_ids and _all_definitions_visible(inspected, sections)
    files = sorted(
        inspected + sections["xml"]["skipped_files"], key=lambda item: item["load_index"]
    )
    definitions: dict[str, list[JSONObject]] = {}
    for file in inspected:
        for index, event in enumerate(file.get("events", [])):
            name = _identifier(module, event)
            if event["kind"] == "definition" and name and name.startswith(module + "."):
                definitions.setdefault(name, []).append(
                    {**event, "phase": file["phase"], "position": (file["load_index"], index)}
                )
    known: dict[str, JSONObject] = {}
    for file in files:
        if file.get("status") != "valid":
            known.clear()
        counts = sections[file.get("format", "xml")]["reference_counts"]
        rules = {"models": models, "absence_certain": absence_certain, "fresh": fresh}
        _analyze_file(module, file, definitions, known, counts, rules)
    for section in sections.values():
        section["reference_basis"] = "earlier_same_module_literal_definition"


def _analyze_file(
    module: str,
    file: JSONObject,
    definitions: dict[str, list[JSONObject]],
    known: dict[str, JSONObject],
    counts: dict[str, int],
    rules: JSONObject,
) -> None:
    file.update(definitions=[], references=[], unexamined=[])
    for index, event in enumerate(file.pop("events", [])):
        location = {key: file[key] for key in ("path", "phase")}
        location.update({key: event[key] for key in ("line", "column")})
        name = _identifier(module, event)
        if event["kind"] == "barrier":
            known.clear()
            file["unexamined"].append({**location, "reason": event["value"]})
        elif event["kind"] == "definition" and name and name.startswith(module + "."):
            known[name] = {**location, "conditional": event["conditional"]}
            file["definitions"].append(
                {**location, "xml_id": name, "conditional": event["conditional"]}
            )
        else:
            reference = _resolve(
                module,
                name,
                file["phase"],
                definitions,
                known,
                (file["load_index"], index),
                file.get("format", "xml"),
                rules["models"],
            )
            if rules["fresh"] and _undefined_on_new_database(module, reference, rules):
                reference["status"] = "undefined"
            reference.update(location, value=event["value"], attribute=event["attribute"])
            file["references"].append(reference)
            counts[reference["status"]] += 1


def _resolve(
    module: str,
    name: str | None,
    phase: str,
    definitions: dict[str, list[JSONObject]],
    known: dict[str, JSONObject],
    position: tuple[int, int],
    source_format: str,
    models: ModelIndex,
) -> JSONObject:
    result: JSONObject = {"xml_id": name, "status": "unknown", "target": None}
    if name is None:
        reason = "unsupported_literal"
    elif not name.startswith(module + "."):
        reason = "external_module"
    elif name in known:
        reason = (
            "conditional_definition" if known[name]["conditional"] else "earlier_local_definition"
        )
        if not known[name]["conditional"]:
            result.update(
                status="resolved",
                target={k: v for k, v in known[name].items() if k != "conditional"},
            )
    elif name in definitions:
        eligible = [d for d in definitions[name] if phase == "demo" or d["phase"] == "data"]
        if not eligible:
            reason = "demo_only_definition"
        elif all(d["position"] > position for d in eligible):
            reason = "forward_definition"
        else:
            reason = "unverified_effects"
    elif target := models.target(name.removeprefix(module + ".")):
        reason = "orm_generated"
        result.update(status="resolved", target=target)
    else:
        reason = "not_in_scanned_xml" if source_format == "xml" else "not_in_scanned_data"
    result["reason"] = reason
    return result


def _all_definitions_visible(inspected: list[JSONObject], sections: dict[str, JSONObject]) -> bool:
    """False when a skipped, unparsed or blocked file or an unknown loader tag might define IDs."""
    if sections["xml"]["skipped_files"] or any(f["status"] != "valid" for f in inspected):
        return False
    return not any(
        event["kind"] == "barrier"
        and event["value"] == "unsupported_loader_operation"
        and event["attribute"] not in NON_DEFINING
        for file in inspected
        for event in file.get("events", [])
    )


def _undefined_on_new_database(module: str, reference: JSONObject, rules: JSONObject) -> bool:
    reason = reference["reason"]
    if reason in FRESH_UNDEFINED:
        return True
    if reason not in {"not_in_scanned_xml", "not_in_scanned_data"} or not rules["absence_certain"]:
        return False
    local = reference["xml_id"].removeprefix(module + ".")
    if local.startswith(UNREAD_GENERATED):
        return False
    return rules["models"].complete or not local.startswith(("model_", "field_"))
