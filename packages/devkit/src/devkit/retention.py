"""Operator retention settings and conservative planning over completed run families."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from devkit.config import config_root, read_toml
from devkit.contracts import DevkitError, JSONObject
from devkit.schemas import validate

RETENTION_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "max_age_days": {"type": "number", "minimum": 0, "maximum": 36500},
        "keep_last": {"type": "integer", "minimum": 0, "maximum": 1000000},
    },
}


def load_retention(project: Path, days: float | None, keep: int | None) -> JSONObject:
    path = config_root() / "retention.toml"
    try:
        if path.exists() and (
            path.resolve().is_relative_to(project) or path.stat().st_mode & 0o022
        ):
            raise ValueError("Retention must be controlled by the operator")
        data = read_toml(path)
        validate(data, RETENTION_SCHEMA)
        settings = {"max_age_days": 30, "keep_last": 100, **data}
        settings.update(
            {k: v for k, v in {"max_age_days": days, "keep_last": keep}.items() if v is not None}
        )
        validate(settings, RETENTION_SCHEMA)
        return settings
    except Exception as exc:
        raise DevkitError("INVALID_RETENTION", "Invalid operator retention settings") from exc


def _families(records: JSONObject) -> list[set[str]]:
    graph: dict[str, set[str]] = {key: set() for key in records}
    for run_id, record in records.items():
        for linked in record["links"]:
            graph.setdefault(linked, set()).add(run_id)
            graph[run_id].add(linked)
    remaining = set(graph)
    families = []
    while remaining:
        pending, family = [next(iter(remaining))], set()
        while pending:
            run_id = pending.pop()
            if run_id in remaining:
                remaining.remove(run_id)
                family.add(run_id)
                pending.extend(graph[run_id])
        families.append(family)
    return families


def _newest(records: JSONObject, keep: int) -> set[str]:
    projects: dict[str, list[JSONObject]] = {}
    for record in records.values():
        if record["state"] == "complete":
            projects.setdefault(record["project_root"], []).append(record)
    return {
        run["run_id"]
        for runs in projects.values()
        for run in sorted(
            runs, key=lambda item: (item["finished_at"], item["run_id"]), reverse=True
        )[:keep]
    }


def _protected(
    family: set[str],
    records: JSONObject,
    newest: set[str],
    cutoff: str,
    project: Path | None,
) -> str | None:
    if any(key not in records or records[key]["state"] != "complete" for key in family):
        return "INCOMPLETE_FAMILY"
    members = [records[key] for key in family]
    if project is not None and any(item["project_root"] != str(project) for item in members):
        return "OUTSIDE_PROJECT"
    if any(item["references"] or item["work_item_ref"] for item in members):
        return "REFERENCED"
    if any(item["unmanaged"] for item in members):
        return "UNMANAGED_FILES"
    if family & newest:
        return "KEEP_LAST"
    if any(item["finished_at"] >= cutoff for item in members):
        return "TOO_RECENT"
    return None


def plan_prune(records: JSONObject, settings: JSONObject, project: Path | None) -> JSONObject:
    cutoff = (datetime.now(UTC) - timedelta(days=settings["max_age_days"])).isoformat()
    newest = _newest(records, settings["keep_last"])
    candidates: list[str] = []
    protected: list[JSONObject] = []
    for family in _families(records):
        reason = _protected(family, records, newest, cutoff, project)
        if reason:
            protected.extend(
                {"run_id": key, "reason": reason} for key in sorted(family) if key in records
            )
        else:
            candidates.extend(sorted(family))
    return {"candidates": sorted(candidates), "protected": protected, "settings": settings}
