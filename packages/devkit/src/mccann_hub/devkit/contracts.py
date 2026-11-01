"""Data contracts shared by commands and presentation adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Literal

type Status = Literal["success", "failed", "blocked", "error", "cancelled"]
type JSONObject = dict[str, Any]

EFFECTS = frozenset({"read_fs", "write_fs", "execute_process", "network_read", "network_write"})
SURFACES = frozenset({"cli", "python", "mcp"})
EXIT_CODES = {"success": 0, "failed": 1, "blocked": 2, "error": 3, "cancelled": 130}
EMPTY_SCHEMA: JSONObject = {"type": "object", "properties": {}, "additionalProperties": False}


class DevkitError(Exception):
    """A safe diagnostic with a stable machine-readable reason."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CommandResult:
    status: Status
    summary: str
    data: JSONObject = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class Context:
    project_root: Path
    run_id: str
    deadline: float
    cancellation: Event
    settings: JSONObject = field(default_factory=dict)
    surface: str = "python"
    state_root: Path | None = None


@dataclass(frozen=True)
class CommandSpec:
    id: str
    description: str
    handler: Callable[[Context, JSONObject], CommandResult]
    input_schema: JSONObject = field(default_factory=lambda: dict(EMPTY_SCHEMA))
    output_schema: JSONObject = field(default_factory=lambda: {"type": "object"})
    effects: frozenset[str] = frozenset()
    surfaces: frozenset[str] = SURFACES


@dataclass(frozen=True)
class CheckSpec:
    id: str
    command: str
    arguments: JSONObject = field(default_factory=dict)


@dataclass(frozen=True)
class Specialization:
    id: str
    commands: tuple[CommandSpec, ...]
    api_version: str = "1.0"
    checks: tuple[CheckSpec, ...] = ()
    environment_checks: tuple[CheckSpec, ...] = ()
