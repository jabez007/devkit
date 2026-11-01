"""Inspect, reference, and prune local evidence without loading project plugins."""

import fcntl
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from devkit.contracts import DevkitError, JSONObject
from devkit.retention import RETENTION_SCHEMA, plan_prune
from devkit.schemas import RESULT_SCHEMA, validate

MAX_RECORD = 4 * 1024 * 1024
MANAGED_FILES = {"result.json", "references.json"}
INDEX_SCHEMA: JSONObject = {
    "type": "object",
    "required": ["run_id", "schema_version", "project_root", "finished_at", "command", "result"],
    "properties": {
        "run_id": {"type": "string"},
        "schema_version": {"const": "1.0"},
        "project_root": {"type": "string"},
        "finished_at": {"type": "string"},
        "command": {"type": "string", "minLength": 1},
        "result": RESULT_SCHEMA,
        "parent_run_id": {"type": ["string", "null"], "minLength": 1},
        "work_item_ref": {"type": ["string", "null"], "minLength": 1},
    },
}


def valid_run_id(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError("Expected canonical UUID")
    except (ValueError, AttributeError) as exc:
        raise DevkitError("INVALID_RUN_ID", "Run IDs must be canonical UUIDs") from exc
    return value


@contextmanager
def run_lock(state: Path) -> Iterator[Path]:
    """Serialize cooperating evidence writers, reference changes, and pruning on Linux."""
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(state / ".runs.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        runs = state / "runs"
        runs.mkdir(exist_ok=True, mode=0o700)
        if runs.is_symlink() or not runs.is_dir():
            raise OSError("Evidence directory must not be a symlink")
        yield runs
    finally:
        os.close(descriptor)


def _read_json(path: Path) -> Any:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Expected a regular evidence file")
        data = stream.read(MAX_RECORD + 1)
    if len(data) > MAX_RECORD:
        raise ValueError("Evidence exceeds inspection limit")
    value = json.loads(data)
    json.dumps(value, allow_nan=False)
    return value


def _references(run: Path) -> list[str]:
    path = run / "references.json"
    if not path.exists() and not path.is_symlink():
        return []
    data = _read_json(path)
    validate(
        data,
        {
            "type": "object",
            "required": ["references"],
            "additionalProperties": False,
            "properties": {
                "references": {
                    "type": "array",
                    "maxItems": 128,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 512},
                }
            },
        },
    )
    return list(data["references"])


def _links(envelope: JSONObject) -> list[str]:
    links = []
    parent = envelope.get("parent_run_id")
    if parent is not None:
        links.append(valid_run_id(parent))
    result = envelope["result"]
    if envelope["command"] == "core.check" or result.get("reason") == "PREREQUISITE_FAILED":
        links.extend(valid_run_id(item["run_id"]) for item in result["data"].get("checks", []))
    return links


def _record(run: Path) -> JSONObject:
    if run.is_symlink() or not run.is_dir():
        raise ValueError("Expected a real run directory")
    files = set(os.listdir(run))
    base: JSONObject = {
        "run_id": run.name,
        "state": "incomplete",
        "project_root": None,
        "finished_at": None,
        "links": [],
        "references": _references(run),
        "work_item_ref": None,
        "unmanaged": bool(files - MANAGED_FILES),
    }
    if "result.json" not in files:
        return base
    envelope = _read_json(run / "result.json")
    validate(envelope, INDEX_SCHEMA)
    if envelope["run_id"] != run.name:
        raise ValueError("Unsupported or mismatched evidence")
    project = envelope["project_root"]
    if not isinstance(project, str) or not Path(project).is_absolute():
        raise ValueError("Invalid evidence project")
    finished = datetime.fromisoformat(envelope["finished_at"])
    if finished.tzinfo is None:
        raise ValueError("Missing timestamp timezone")
    base.update(
        state="complete",
        project_root=project,
        finished_at=finished.astimezone(UTC).isoformat(),
        command=envelope["command"],
        status=envelope["result"]["status"],
        work_item_ref=envelope.get("work_item_ref"),
        links=_links(envelope),
        envelope=envelope,
    )
    return base


def _inspect(run: Path) -> JSONObject:
    try:
        return _record(run)
    except Exception as exc:
        raise DevkitError("CORRUPT_EVIDENCE", f"Cannot safely inspect run {run.name}") from exc


def _scan(root: Path) -> JSONObject:
    records = {}
    for run in root.iterdir():
        try:
            valid_run_id(run.name)
        except DevkitError:
            continue  # Preserve unknown directories and files; never prune by broad glob.
        records[run.name] = _inspect(run)
    return records


def _selected(root: Path, run_id: str, project: Path | None) -> JSONObject:
    run = root / valid_run_id(run_id)
    if not run.exists() and not run.is_symlink():
        raise DevkitError("RUN_NOT_FOUND", "Evidence run does not exist")
    record = _inspect(run)
    if project is not None and record["project_root"] != str(project):
        raise DevkitError("RUN_NOT_FOUND", "Evidence run is outside the selected project")
    return record


def _save_references(run: Path, references: list[str]) -> None:
    temporary = run / f".references-{uuid4()}.tmp"
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"references": references}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(run / "references.json")
    finally:
        temporary.unlink(missing_ok=True)


def _remove(root: Path, run_id: str) -> None:
    root_fd = os.open(root, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        run_fd = os.open(run_id, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            files = set(os.listdir(run_fd))
            if files - MANAGED_FILES or "result.json" not in files:
                raise OSError("Run contents changed before pruning")
            for name in files:
                if not stat.S_ISREG(os.stat(name, dir_fd=run_fd, follow_symlinks=False).st_mode):
                    raise OSError("Unsafe file in run")
            for name in files:
                os.unlink(name, dir_fd=run_fd)
        finally:
            os.close(run_fd)
        os.rmdir(run_id, dir_fd=root_fd)
    finally:
        os.close(root_fd)


class RunStore:
    def __init__(self, state: Path) -> None:
        self.state = state

    def list(
        self,
        project: Path | None,
        limit: int = 50,
        offset: int = 0,
        *,
        reference: str | None = None,
    ) -> JSONObject:
        if not 1 <= limit <= 1000 or offset < 0:
            raise DevkitError("INVALID_INPUT", "List limit must be 1..1000 and offset nonnegative")
        with run_lock(self.state) as root:
            records = [
                item
                for item in _scan(root).values()
                if (project is None or item["project_root"] == str(project))
                and (
                    reference is None
                    or reference in item["references"]
                    or reference == item["work_item_ref"]
                )
            ]
            records.sort(key=lambda item: (item["finished_at"] or "", item["run_id"]), reverse=True)
            public = [
                {k: v for k, v in item.items() if k not in {"envelope", "links", "unmanaged"}}
                for item in records[offset : offset + limit]
            ]
            return {"runs": public, "total": len(records), "offset": offset}

    def show(self, run_id: str, project: Path | None) -> JSONObject:
        with run_lock(self.state) as root:
            record = _selected(root, run_id, project)
            return {
                "run": record.get("envelope"),
                "state": record["state"],
                "references": record["references"],
            }

    def reference(
        self, run_id: str, reference: str, project: Path | None, *, remove: bool = False
    ) -> JSONObject:
        if not reference.strip() or len(reference) > 512:
            raise DevkitError("INVALID_INPUT", "References must contain 1..512 characters")
        with run_lock(self.state) as root:
            record = _selected(root, run_id, project)
            references = set(record["references"])
            references.discard(reference) if remove else references.add(reference)
            if len(references) > 128:
                raise DevkitError("INVALID_INPUT", "At most 128 references may protect a run")
            _save_references(root / run_id, sorted(references))
            return {"run_id": run_id, "references": sorted(references)}

    def prune(
        self, project: Path | None, settings: JSONObject, *, apply: bool = False
    ) -> JSONObject:
        try:
            validate(settings, {**RETENTION_SCHEMA, "required": ["max_age_days", "keep_last"]})
        except Exception as exc:
            raise DevkitError("INVALID_RETENTION", "Invalid retention settings") from exc
        with run_lock(self.state) as root:
            plan = plan_prune(_scan(root), settings, project)
            plan.update(dry_run=not apply, deleted=[], errors=[])
            if apply:
                for run_id in plan["candidates"]:
                    try:
                        _remove(root, run_id)
                        plan["deleted"].append(run_id)
                    except OSError:
                        plan["errors"].append({"run_id": run_id, "reason": "PRUNE_FAILED"})
                        break  # Never continue deleting a family after an incomplete removal.
            return plan
