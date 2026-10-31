"""Operator grants are external to project-controlled configuration."""

from dataclasses import dataclass, field
from pathlib import Path

from devkit.config import config_root, read_toml
from devkit.contracts import EFFECTS, SURFACES, CommandSpec, DevkitError, JSONObject
from devkit.schemas import validate

POLICY_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "trusted_plugins": {
            "type": "object",
            "additionalProperties": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["version", "wheel", "sha256"],
                        "properties": {
                            "version": {"type": "string"},
                            "wheel": {"type": "string", "pattern": "^/"},
                            "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                        },
                    },
                ],
            },
        },
        "deny": {"type": "array", "items": {"type": "string"}},
        "commands": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "required": ["project", "effects", "surfaces"],
                "properties": {
                    "project": {"type": "string"},
                    "effects": {"type": "array", "items": {"enum": sorted(EFFECTS)}},
                    "surfaces": {"type": "array", "items": {"enum": sorted(SURFACES)}},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class Policy:
    trusted_plugins: JSONObject = field(default_factory=dict)
    commands: JSONObject = field(default_factory=dict)
    deny: tuple[str, ...] = ()

    def trusts(self, name: str, version: str, artifact_sha256: str | None = None) -> bool:
        trust = self.trusted_plugins.get(name)
        if isinstance(trust, str):
            return trust == version
        return bool(trust and trust["version"] == version and trust["sha256"] == artifact_sha256)

    def allows(self, spec: CommandSpec, project: Path, surface: str) -> bool:
        if spec.id in self.deny or surface not in spec.surfaces:
            return False
        if spec.id in {"core.doctor", "core.check"} and surface != "mcp":
            return True
        grant = self.commands.get(spec.id)
        return bool(
            grant
            and Path(grant["project"]).is_absolute()
            and Path(grant["project"]).resolve() == project
            and spec.effects <= set(grant["effects"])
            and surface in grant["surfaces"]
        )


def load_policy(project: Path) -> Policy:
    path = config_root() / "policy.toml"
    if path.exists() and (path.resolve().is_relative_to(project) or path.stat().st_mode & 0o022):
        raise DevkitError(
            "INVALID_POLICY", "Policy must be outside the project and not writable by others"
        )
    data = read_toml(path)
    try:
        validate(data, POLICY_SCHEMA)
    except Exception as exc:
        raise DevkitError("INVALID_POLICY", "Invalid operator policy") from exc
    return Policy(
        data.get("trusted_plugins", {}), data.get("commands", {}), tuple(data.get("deny", []))
    )
