"""Direct dependency declarations and presence resolution; no runtime or transitive solver."""

import re
from pathlib import Path
from typing import Any

from devkit.contracts import JSONObject

MODULE_NAME = re.compile(r"\w{1,256}")


def _edge(value: Any, available: dict[str, Path], project: Path, policy: JSONObject) -> JSONObject:
    if not isinstance(value, str) or MODULE_NAME.fullmatch(value) is None:
        return {
            "name": str(value)[:256],
            "status": "invalid",
            "path": None,
            "message": "depends entries must be module identifiers, not paths or dotted names",
        }
    if value in available:
        return {
            "name": value,
            "status": "resolved",
            "path": available[value].relative_to(project).as_posix(),
        }
    complete = policy["complete"] or any(
        value.startswith(prefix) for prefix in policy["complete_prefixes"]
    )
    return {"name": value, "status": "missing" if complete else "unknown", "path": None}


def module_dependencies(
    name: str,
    manifest: JSONObject,
    available: dict[str, Path],
    project: Path,
    policy: JSONObject,
) -> list[JSONObject]:
    declared = manifest.get("depends", [])
    if not isinstance(declared, list):
        return [
            {
                "name": None,
                "status": "invalid",
                "path": None,
                "implicit": False,
                "message": "depends must be a list of module identifiers",
            }
        ]
    implicit = not declared and name != "base"
    # Odoo normalizes an empty depends list to base, except for base itself.
    values = ["base"] if implicit else declared
    edges = [_edge(value, available, project, policy) for value in values]
    for edge in edges:
        edge["implicit"] = implicit
    return edges


def external_dependencies(manifest: JSONObject) -> list[JSONObject]:
    declared = manifest.get("external_dependencies", {})
    if not isinstance(declared, dict):
        return [
            {
                "kind": None,
                "name": None,
                "status": "invalid",
                "message": "external_dependencies must map python/bin to lists of requirements",
            }
        ]
    result = []
    for kind, values in declared.items():
        if kind not in {"python", "bin"} or not isinstance(values, list):
            result.append(
                {
                    "kind": str(kind)[:256],
                    "name": None,
                    "status": "invalid",
                    "message": "external_dependencies supports python/bin lists only",
                }
            )
            continue
        for value in values:
            valid = isinstance(value, str) and bool(value.strip())
            result.append(
                {
                    "kind": kind,
                    "name": str(value)[:1024],
                    "status": "unknown" if valid else "invalid",
                    "message": "Not checked offline"
                    if valid
                    else "External requirement must be a nonempty string",
                }
            )
    return result
