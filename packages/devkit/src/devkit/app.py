"""Composition root for built-in commands and project configuration."""

import platform
from pathlib import Path

from devkit import __version__
from devkit.config import load_settings
from devkit.contracts import CheckSpec, CommandResult, CommandSpec, Context, JSONObject
from devkit.discovery import activate
from devkit.invocation import CommandService
from devkit.policy import load_policy


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


def create_service(
    project: Path,
    timeout: float | None = None,
    *,
    diagnostic: bool = False,
) -> CommandService:
    settings = load_settings(project, timeout)
    commands = [CommandSpec("core.doctor", "Inspect the foundation", doctor)]
    origins: JSONObject = {}
    checks: list[CheckSpec] = []
    environments: list[CheckSpec] = []
    prerequisites: dict[str, tuple[CheckSpec, ...]] = {}
    try:
        plugins = activate(settings.plugins, load_policy(settings.project_root))
        for plugin, candidate in plugins:
            commands.extend(plugin.commands)
            checks.extend(plugin.checks + plugin.environment_checks)
            environments.extend(plugin.environment_checks)
            environment_commands = {check.command for check in plugin.environment_checks}
            prerequisites.update(
                {
                    spec.id: plugin.environment_checks
                    for spec in plugin.commands
                    if spec.id not in environment_commands
                }
            )
            origins.update(
                {
                    spec.id: {"distribution": candidate.distribution, "version": candidate.version}
                    for spec in plugin.commands
                }
            )
    except Exception as exc:
        if not diagnostic:
            raise
        from devkit.contracts import DevkitError

        reason = exc.reason if isinstance(exc, DevkitError) else "INVALID_PLUGIN"

        def broken(context: Context, arguments: JSONObject) -> CommandResult:
            return CommandResult("blocked", "Plugin activation failed", reason=reason)

        commands = [CommandSpec("core.doctor", "Inspect the foundation", broken)]
        checks, environments, prerequisites = [], [], {}
    prerequisites["core.doctor"] = tuple(environments)
    return CommandService(
        settings,
        tuple(commands),
        origins=origins,
        checks=tuple(checks),
        prerequisites=prerequisites,
    )
