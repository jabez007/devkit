"""Composition root for built-in commands and project configuration."""

import platform
from pathlib import Path

from devkit import __version__
from devkit.config import load_settings
from devkit.contracts import CommandResult, CommandSpec, Context, JSONObject
from devkit.invocation import CommandService


def doctor(context: Context, arguments: JSONObject) -> CommandResult:
    return CommandResult(
        "success",
        "Foundation is ready",
        {
            "version": __version__,
            "python": platform.python_version(),
            "platform": platform.system(),
            "project_root": str(context.project_root),
        },
    )


def create_service(project: Path, timeout: float | None = None) -> CommandService:
    settings = load_settings(project, timeout)
    return CommandService(settings, (CommandSpec("core.doctor", "Inspect the foundation", doctor),))
