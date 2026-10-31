"""Direct dependency declarations and presence resolution; no runtime or transitive solver."""

import re
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter
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


def analyze_graph(
    findings: list[JSONObject], inventory: dict[str, Path], checkpoint: Callable[[], None]
) -> JSONObject:
    """Report one cycle among inspected manifests, without inferring absent edges.

    Inventory and findings-size limits bound the input. Sorting makes the witness
    repeatable for the same graph and Python runtime; it is not a stable cycle ID.
    """
    graph: dict[str, list[str]] = {
        item["module"]: [] for item in findings if item["dependencies_inspected"]
    }
    excluded = dict.fromkeys(("missing", "unknown", "invalid", "uninspected_target"), 0)
    for item in findings:
        checkpoint()
        for edge in item["dependencies"]:
            checkpoint()
            if edge["status"] != "resolved":
                excluded[edge["status"]] += 1
            elif edge["name"] not in graph:
                excluded["uninspected_target"] += 1
            else:
                graph[item["module"]].append(edge["name"])
    graph = {name: sorted(set(graph[name])) for name in sorted(graph)}
    cycle: list[str] = []
    checkpoint()
    try:
        TopologicalSorter(graph).prepare()
    except CycleError as exc:
        # graphlib reports predecessor -> dependent; callers need depends-on order.
        cycle = list(reversed(exc.args[1]))
    checkpoint()
    return {
        "status": "cycle" if cycle else "no_cycle_observed",
        "scope": "inspected_manifests",
        "node_count": len(graph),
        "edge_count": sum(len(edges) for edges in graph.values()),
        "cycle": cycle,
        "uninspected_modules": sorted(set(inventory) - graph.keys()),
        "excluded_edge_counts": excluded,
    }
