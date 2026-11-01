"""Bounded Beads 1.3.2 CLI access; no database access or task cache."""

import json
import os
import re
import time
from pathlib import Path
from uuid import UUID

from mccann_hub.devkit.contracts import Context, JSONObject, Status
from mccann_hub.devkit.processes import ProcessResult, run_process

SUPPORTED_VERSION = "1.3.2"
ISSUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class BeadsError(Exception):
    def __init__(self, status: Status, reason: str, message: str) -> None:
        super().__init__(message)
        self.status, self.reason = status, reason


def invalid(message: str = "Beads returned an unexpected JSON response") -> BeadsError:
    return BeadsError("error", "INVALID_TOOL_OUTPUT", message)


def project_id(value: object) -> str:
    if not isinstance(value, str):
        raise invalid("Beads context must include a stable project UUID")
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise invalid("Beads context must include a canonical project UUID")


def issue_id(value: object) -> str:
    if not isinstance(value, str) or not ISSUE_ID.fullmatch(value):
        raise invalid("Beads returned an invalid issue identifier")
    return value


def local_id(reference: str, workspace: JSONObject) -> str:
    parts = reference.split(":")
    if len(parts) != 3 or parts[:2] != ["beads", workspace["project_id"]]:
        raise BeadsError(
            "blocked", "WORKSPACE_MISMATCH", "Use an issue reference from this workspace"
        )
    return issue_id(parts[2])


def items(value: object, scope: str, *, dependencies: bool = False) -> list[JSONObject]:
    if not isinstance(value, list):
        raise invalid()
    result = [_item(row, scope, dependencies) for row in value]
    if len({row["ref"] for row in result}) != len(result):
        raise invalid("Beads returned duplicate issue identifiers")
    return result


def _item(row: object, scope: str, dependency: bool) -> JSONObject:
    if not isinstance(row, dict):
        raise invalid()
    identifier = issue_id(row.get("id"))
    fields = ("title", "status", "issue_type") + (("dependency_type",) if dependency else ())
    if any(not isinstance(row.get(key), str) or not row[key] for key in fields):
        raise invalid()
    priority = row.get("priority")
    if type(priority) is not int or not 0 <= priority <= 4:
        raise invalid()
    description = row.get("description", "")
    if not isinstance(description, str):
        raise invalid()
    optional = {key: row[key] for key in ("assignee", "created_by", "close_reason") if key in row}
    if any(not isinstance(value, str) for value in optional.values()):
        raise invalid()
    return {
        **optional,
        "ref": f"beads:{scope}:{identifier}",
        **{key: row[key] for key in fields},
        "priority": priority,
        "description": description,
    }


class Beads:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.directory = context.project_root / ".beads"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"}
        }
        self.environment.update(BD_DISABLE_METRICS="1", DO_NOT_TRACK="1")
        self.identity: JSONObject | None = None

    def _invoke(self, arguments: list[str]) -> ProcessResult:
        if self.context.cancellation.is_set():
            raise BeadsError("cancelled", "CANCELLED", "Beads inspection cancelled")
        if time.monotonic() >= self.context.deadline:
            raise BeadsError("error", "TIMEOUT", "Beads inspection deadline exceeded")
        return run_process(
            arguments,
            self.context,
            environment=self.environment,
        )

    def query(self, *arguments: str) -> object:
        result = self._invoke(["bd", "--readonly", "--sandbox", "--json", *arguments])
        if result.reason:
            statuses: dict[str, Status] = {"MISSING_TOOL": "blocked", "CANCELLED": "cancelled"}
            status = statuses.get(result.reason, "error")
            raise BeadsError(status, result.reason, "Beads did not run; install bd 1.3.2 on PATH")
        if result.truncated:
            raise BeadsError("error", "OUTPUT_LIMIT", "Beads output exceeded the capture limit")
        if result.returncode:
            raise BeadsError(
                "blocked",
                "BEADS_UNAVAILABLE",
                "Beads could not read this workspace or item; inspect it with bd --readonly",
            )
        try:
            return json.loads(result.stdout)
        except (ValueError, RecursionError) as exc:
            raise invalid() from exc

    def write(self, actor: str, *arguments: str) -> object:
        self.workspace()  # Refuse an identity change before any mutation can run.
        result = self._invoke(["bd", "--sandbox", "--json", f"--actor={actor}", *arguments])
        if result.reason in {"MISSING_TOOL", "PROCESS_ERROR"}:
            raise BeadsError("blocked", result.reason, "Beads write process could not start")
        if result.returncode == 13 and arguments[0] == "update":
            raise BeadsError("blocked", "BEADS_CONFLICT", "Beads update guard no longer matches")
        if result.reason or result.truncated or result.returncode:
            raise BeadsError(
                "error",
                "BEADS_WRITE_UNCERTAIN",
                "Beads write was not confirmed; inspect the item before retrying",
            )
        try:
            return json.loads(result.stdout)
        except (ValueError, RecursionError) as exc:
            raise BeadsError(
                "error",
                "BEADS_WRITE_UNCERTAIN",
                "Beads returned invalid write JSON; inspect the item before retrying",
            ) from exc

    def workspace(self) -> JSONObject:
        from mccann_hub.devkit_beads.workspace import resolve

        self.environment.pop("BEADS_DIR", None)
        main = resolve(self.context.project_root, self._invoke)
        version = self.query("version")
        if not isinstance(version, dict) or version.get("version") != SUPPORTED_VERSION:
            raise BeadsError(
                "blocked", "UNSUPPORTED_BEADS_VERSION", "This adapter requires Beads 1.3.2"
            )
        self.directory = main / ".beads"
        identity = self._validate_workspace(self.query("context"), main)
        if self.identity is not None and self.identity != identity:
            raise BeadsError(
                "blocked", "WORKSPACE_MISMATCH", "Beads workspace changed before execution"
            )
        self.environment["BEADS_DIR"] = str(self.directory)
        if main != self.context.project_root:
            bound = self._validate_workspace(self.query("context"), main)
            if bound != identity:
                raise BeadsError(
                    "blocked", "WORKSPACE_MISMATCH", "Beads binding changed workspace identity"
                )
        self.identity = identity
        return identity

    def _validate_workspace(self, info: object, main: Path) -> JSONObject:
        if not isinstance(info, dict) or info.get("schema_version") != 1:
            raise invalid()
        linked = main != self.context.project_root
        expected = {"backend": "dolt", "dolt_mode": "embedded", "bd_version": SUPPORTED_VERSION}
        if (
            any(info.get(key) != value for key, value in expected.items())
            or info.get("is_redirected") is not False
            or info.get("is_worktree") is not linked
        ):
            raise BeadsError(
                "blocked",
                "UNSUPPORTED_BEADS_WORKSPACE",
                "Use a main or linked Git checkout with embedded Beads; "
                "server modes and redirects are unsupported",
            )
        for key, path in (
            ("beads_dir", self.directory),
            ("repo_root", main),
            ("cwd_repo_root", self.context.project_root),
        ):
            if info.get(key) != str(path):
                raise BeadsError(
                    "blocked", "WORKSPACE_MISMATCH", "Beads selected another workspace"
                )
        return {
            "project_id": project_id(info.get("project_id")),
            "tool_version": SUPPORTED_VERSION,
            "backend": "dolt",
            "mode": "embedded",
            "checkout_root": str(self.context.project_root),
            "workspace_root": str(main),
            "is_worktree": linked,
            "concurrency": "sequential-only",
        }

    def show(self, reference: str, workspace: JSONObject) -> JSONObject:
        identifier = local_id(reference, workspace)
        # Beads 1.3.2 `show` updates last-touched even with --readonly. The
        # supported exact-ID list query avoids that write, including for closed
        # and normally hidden item types. Check identity rather than accepting a
        # prefix match or a truncated result.
        result = items(
            self.query(
                "list",
                "--id",
                identifier,
                "--all",
                "--limit",
                "2",
                "--max-rows",
                "2",
                "--include-infra",
                "--include-gates",
                "--include-templates",
                "--include-ephemeral",
            ),
            workspace["project_id"],
        )
        if not result:
            raise BeadsError(
                "blocked", "BEADS_ITEM_UNAVAILABLE", "No live Beads item matches this reference"
            )
        if len(result) != 1 or result[0]["ref"] != reference:
            raise invalid("Beads did not return the requested issue")
        return result[0]
