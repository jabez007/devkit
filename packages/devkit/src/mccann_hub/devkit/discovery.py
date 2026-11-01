"""Discover installed metadata first; load only selected, trusted plugins."""

import re
from dataclasses import dataclass, replace
from importlib.metadata import EntryPoint, entry_points

from mccann_hub.devkit.artifacts import verify_wheel
from mccann_hub.devkit.contracts import EFFECTS, SURFACES, CommandSpec, DevkitError, Specialization
from mccann_hub.devkit.output import capture_output
from mccann_hub.devkit.policy import Policy
from mccann_hub.devkit.schemas import check_schema, validate

GROUP = "mccann_hub.devkit.specializations.v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


@dataclass(frozen=True)
class Candidate:
    id: str
    distribution: str
    version: str
    entry_point: EntryPoint
    artifact_sha256: str | None = None


def discover() -> tuple[Candidate, ...]:
    result = []
    for entry in entry_points(group=GROUP):
        if entry.dist is None:
            raise DevkitError("INVALID_PLUGIN", "Entry point has no distribution metadata")
        name = re.sub(r"[-_.]+", "-", entry.dist.metadata["Name"]).lower()
        result.append(Candidate(entry.name, name, entry.dist.version, entry))
    return tuple(sorted(result, key=lambda item: (item.id, item.distribution, item.version)))


def validate_command(spec: CommandSpec) -> None:
    if not callable(spec.handler):
        raise DevkitError("INVALID_PLUGIN", "Command handler must be callable")
    if not IDENTIFIER.fullmatch(spec.id):
        raise DevkitError("INVALID_PLUGIN", "Command IDs must be namespaced identifiers")
    if not spec.effects <= EFFECTS or not spec.surfaces <= SURFACES:
        raise DevkitError("INVALID_PLUGIN", "Unknown effect or presentation surface")
    check_schema(spec.input_schema)
    check_schema(spec.output_schema)


def _load(candidate: Candidate) -> Specialization:
    try:
        with capture_output() as output:
            plugin = candidate.entry_point.load()()
        if output.getvalue():
            raise ValueError("Plugin registration must not print")
        if not isinstance(plugin, Specialization) or plugin.api_version != "1.0":
            raise ValueError("unsupported plugin contract")
        if plugin.id != candidate.id or plugin.id == "core":
            raise ValueError("invalid namespace")
        for command in plugin.commands:
            validate_command(command)
            if not command.id.startswith(plugin.id + "."):
                raise ValueError("command outside plugin namespace")
        commands = {command.id: command for command in plugin.commands}
        checks = plugin.checks + plugin.environment_checks
        if len({check.id for check in checks}) != len(checks):
            raise ValueError("duplicate checks")
        for check in checks:
            if (
                check.command not in commands
                or not check.id.startswith(plugin.id + ".")
                or not IDENTIFIER.fullmatch(check.id)
            ):
                raise ValueError("invalid check reference")
            validate(check.arguments, commands[check.command].input_schema)
        return plugin
    except Exception as exc:
        raise DevkitError("INVALID_PLUGIN", f"Cannot activate plugin: {candidate.id}") from exc


def activate(
    enabled: tuple[str, ...],
    policy: Policy,
    candidates: tuple[Candidate, ...] | None = None,
) -> tuple[tuple[Specialization, Candidate], ...]:
    available = discover() if candidates is None else candidates
    selected = []
    # Validate the entire selection before any registration code runs.
    for name in enabled:
        matches = [candidate for candidate in available if candidate.id == name]
        if len(matches) != 1:
            raise DevkitError("PLUGIN_SELECTION", f"Expected exactly one installed plugin: {name}")
        candidate = matches[0]
        trust = policy.trusted_plugins.get(candidate.distribution)
        version = trust.get("version") if isinstance(trust, dict) else trust
        if version != candidate.version:
            raise DevkitError("UNTRUSTED_PLUGIN", f"Plugin version is not trusted: {name}")
        if isinstance(trust, dict):
            candidate = replace(
                candidate, artifact_sha256=verify_wheel(candidate.entry_point.dist, trust)
            )
        selected.append(candidate)
    return tuple((_load(candidate), candidate) for candidate in selected)
