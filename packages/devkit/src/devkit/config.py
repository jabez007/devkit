"""Resolve project settings without accepting repository-supplied grants."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from devkit.contracts import DevkitError, JSONObject
from devkit.schemas import validate

SETTINGS_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600},
        "plugins": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "options": {"type": "object", "additionalProperties": {"type": "object"}},
        "profiles": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
    },
}


def config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devkit"


def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "devkit"


def read_toml(path: Path) -> JSONObject:
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 1_048_576:
            raise ValueError("configuration exceeds size limit")
        return tomllib.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise DevkitError("INVALID_CONFIG", f"Cannot read configuration: {path.name}") from exc


@dataclass(frozen=True)
class Settings:
    project_root: Path
    state_root: Path
    timeout: float
    plugins: tuple[str, ...]
    options: JSONObject
    profiles: dict[str, list[str]]


def load_settings(project: Path, timeout: float | None = None) -> Settings:
    root = project.resolve(strict=True)
    if not root.is_dir():
        raise DevkitError("INVALID_CONFIG", "Project root must be a directory")
    merged: JSONObject = {}
    for path in (config_root() / "settings.toml", root / "devkit.toml"):
        data = read_toml(path)
        try:
            validate(data, SETTINGS_SCHEMA)
        except Exception as exc:
            raise DevkitError("INVALID_CONFIG", f"Invalid settings: {path.name}") from exc
        merged.update(data)
    if timeout is not None:
        merged["timeout"] = timeout
    try:
        validate(merged, SETTINGS_SCHEMA)
    except Exception as exc:
        raise DevkitError("INVALID_CONFIG", "Invalid configuration override") from exc
    return Settings(
        root,
        state_root().resolve(),
        float(merged.get("timeout", 60)),
        tuple(merged.get("plugins", [])),
        merged.get("options", {}),
        merged.get("profiles", {}),
    )
