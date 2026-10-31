"""Literal loader references, with explicit limits on static resolution certainty."""

import re
from collections.abc import Callable

from devkit.contracts import JSONObject

CONTAINERS = {"odoo", "openerp", "data"}
OPERATIONS = {"record", "menuitem", "template"}
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
                self._emit("barrier", "unsupported_loader_operation", frame)
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


def analyze_references(module: str, xml: JSONObject) -> None:
    files = sorted(xml["files"] + xml["skipped_files"], key=lambda item: item["load_index"])
    definitions: dict[str, list[JSONObject]] = {}
    for file in xml["files"]:
        for index, event in enumerate(file.get("events", [])):
            name = _identifier(module, event)
            if event["kind"] == "definition" and name and name.startswith(module + "."):
                definitions.setdefault(name, []).append(
                    {**event, "phase": file["phase"], "position": (file["load_index"], index)}
                )
    known: dict[str, JSONObject] = {}
    counts = {"resolved": 0, "unknown": 0}
    for file in files:
        if file.get("status") != "valid":
            known.clear()
        _analyze_file(module, file, definitions, known, counts)
    xml["reference_counts"] = counts
    xml["reference_basis"] = "earlier_same_module_literal_definition"


def _analyze_file(
    module: str,
    file: JSONObject,
    definitions: dict[str, list[JSONObject]],
    known: dict[str, JSONObject],
    counts: dict[str, int],
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
                module, name, file["phase"], definitions, known, (file["load_index"], index)
            )
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
        elif any(d["position"] > position for d in eligible):
            reason = "forward_definition"
        else:
            reason = "unverified_effects"
    else:
        reason = "not_in_scanned_xml"
    result["reason"] = reason
    return result
