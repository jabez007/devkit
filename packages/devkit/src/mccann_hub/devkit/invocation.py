"""One command execution path for Python, the CLI, and future transports."""

import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

from mccann_hub.devkit import __version__
from mccann_hub.devkit.config import Settings
from mccann_hub.devkit.contracts import (
    CheckSpec,
    CommandResult,
    CommandSpec,
    Context,
    DevkitError,
    JSONObject,
)
from mccann_hub.devkit.discovery import validate_command
from mccann_hub.devkit.evidence import redact, source_identity, write_bundle
from mccann_hub.devkit.output import capture_output
from mccann_hub.devkit.policy import Policy, load_policy
from mccann_hub.devkit.schemas import RESULT_SCHEMA, validate


class CommandService:
    def __init__(
        self,
        settings: Settings,
        commands: tuple[CommandSpec, ...],
        policy: Policy | None = None,
        origins: JSONObject | None = None,
        checks: tuple[CheckSpec, ...] = (),
        prerequisites: dict[str, tuple[CheckSpec, ...]] | None = None,
    ) -> None:
        self.settings = settings
        self.checks = {check.id: check for check in checks}
        self.prerequisites = prerequisites or {}
        if len(self.checks) != len(checks):
            raise DevkitError("DUPLICATE_CHECK", "Duplicate check IDs")
        commands = (
            *commands,
            CommandSpec(
                "core.check",
                "Execute a configured check profile",
                self._run_profile,
                input_schema={
                    "type": "object",
                    "required": ["profile"],
                    "properties": {"profile": {"type": "string"}},
                    "additionalProperties": False,
                },
                surfaces=frozenset({"python", "cli"}),
            ),
        )
        self.commands = {spec.id: spec for spec in commands}
        self.policy = policy
        self.origins = origins or {}
        if len(self.commands) != len(commands):
            raise DevkitError("DUPLICATE_COMMAND", "Duplicate command IDs")
        for spec in commands:
            validate_command(spec)

    def allowed(self, surface: str) -> tuple[CommandSpec, ...]:
        policy = self.policy or load_policy(self.settings.project_root)
        return tuple(
            spec
            for spec in self.commands.values()
            if policy.allows(spec, self.settings.project_root, surface)
            and self._producer_trusted(spec.id, policy)
        )

    def _producer_trusted(self, command: str, policy: Policy) -> bool:
        origin = self.origins.get(command)
        return origin is None or policy.trusts(
            origin["distribution"], origin["version"], origin.get("artifact_sha256")
        )

    def execute(
        self,
        command: str,
        arguments: JSONObject | None = None,
        *,
        surface: str = "python",
        cancellation: Event | None = None,
        _deadline: float | None = None,
        _parent_run_id: str | None = None,
    ) -> JSONObject:
        args = arguments if arguments is not None else {}
        run_id = str(uuid4())
        started = datetime.now(UTC).isoformat()
        context = Context(
            self.settings.project_root,
            run_id,
            min(time.monotonic() + self.settings.timeout, _deadline or float("inf")),
            cancellation or Event(),
            self.settings.options,
            surface,
            self.settings.state_root,
        )
        safe_args = _json_arguments(args)
        with capture_output() as output:
            try:
                result = (
                    self._invoke(command, safe_args, surface, context)
                    if safe_args is not None
                    else CommandResult(
                        "error",
                        "Arguments must be a bounded JSON object",
                        reason="INVALID_INPUT",
                    )
                )
            except DevkitError as exc:
                result = CommandResult(
                    "blocked", "Operator policy is unavailable", reason=exc.reason
                )
        envelope: JSONObject = redact(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "parent_run_id": _parent_run_id,
                "command": command,
                "producer": self.origins.get(
                    command, {"distribution": "mccann-hub-devkit", "version": __version__}
                ),
                "project_root": str(self.settings.project_root),
                "arguments": safe_args,
                "diagnostics": output.getvalue(),
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "source": source_identity(self.settings.project_root),
                "result": asdict(result),
                "work_item_ref": None,
            }
        )
        try:
            path = write_bundle(self.settings.state_root, envelope)
            envelope["evidence_path"] = str(path)
        except (OSError, ValueError):
            envelope["observed_result"] = envelope["result"]
            envelope["result"] = asdict(
                CommandResult(
                    "error",
                    "Could not persist required evidence",
                    reason="EVIDENCE_WRITE_FAILED",
                )
            )
            envelope["evidence_path"] = None
        return envelope

    def _invoke(
        self,
        command: str,
        arguments: JSONObject,
        surface: str,
        context: Context,
    ) -> CommandResult:
        spec = self.commands.get(command)
        if spec is None:
            return CommandResult("error", "Unknown command", reason="UNKNOWN_COMMAND")
        if spec not in self.allowed(surface):
            return CommandResult(
                "blocked",
                f"Command {command} is not authorized; check its project, effects and surfaces "
                "in the external policy.toml, and check for revoked plugin trust "
                "or an explicit deny",
                reason="DENIED",
            )
        try:
            validate(arguments, spec.input_schema)
        except Exception:
            return CommandResult("error", "Invalid command arguments", reason="INVALID_INPUT")
        if required := self.prerequisites.get(command):
            prerequisite = self._run_checks(required, context)
            if prerequisite.status != "success":
                return CommandResult(
                    "blocked" if prerequisite.status == "failed" else prerequisite.status,
                    "Prerequisite checks did not succeed",
                    prerequisite.data,
                    "PREREQUISITE_FAILED",
                )
        return self._run_handler(spec, arguments, context)

    def _run_profile(self, context: Context, arguments: JSONObject) -> CommandResult:
        names = self.settings.profiles.get(arguments["profile"])
        if names is None or any(name not in self.checks for name in names):
            return CommandResult("error", "Unknown profile or check ID", reason="INVALID_PROFILE")
        return self._run_checks(tuple(self.checks[name] for name in names), context)

    def _run_checks(self, checks: tuple[CheckSpec, ...], context: Context) -> CommandResult:
        if not checks:
            return CommandResult("blocked", "No required checks selected", reason="NO_CHECKS")
        results = []
        for check in checks:
            envelope = self.execute(
                check.command,
                check.arguments,
                surface=context.surface,
                cancellation=context.cancellation,
                _deadline=context.deadline,
                _parent_run_id=context.run_id,
            )
            results.append(
                {
                    "check": check.id,
                    "result": envelope["result"],
                    "run_id": envelope["run_id"],
                    "evidence_path": envelope["evidence_path"],
                }
            )
        from typing import cast

        from mccann_hub.devkit.contracts import Status

        statuses = {entry["result"]["status"] for entry in results}
        status = next(
            item
            for item in ("cancelled", "error", "failed", "blocked", "success")
            if item in statuses
        )
        return CommandResult(cast(Status, status), "Required check results", {"checks": results})

    @staticmethod
    def _run_handler(spec: CommandSpec, args: JSONObject, context: Context) -> CommandResult:
        if context.cancellation.is_set():
            return CommandResult("cancelled", "Cancelled before execution", reason="CANCELLED")
        if time.monotonic() > context.deadline:
            return CommandResult("error", "Command deadline exceeded", reason="TIMEOUT")
        try:
            result = spec.handler(context, args)
        except KeyboardInterrupt:
            context.cancellation.set()
            return CommandResult("cancelled", "Command interrupted", reason="CANCELLED")
        except Exception:
            return CommandResult("error", "Command handler failed", reason="HANDLER_ERROR")
        if time.monotonic() > context.deadline:
            return CommandResult("error", "Command deadline exceeded", reason="TIMEOUT")
        if context.cancellation.is_set():
            return CommandResult("cancelled", "Command cancelled", reason="CANCELLED")
        try:
            validate(asdict(result), RESULT_SCHEMA)
            if _json_arguments(asdict(result)) is None:
                raise ValueError("Result must be a bounded JSON object")
            if result.status == "success":
                validate(result.data, spec.output_schema)
        except Exception:
            return CommandResult("error", "Invalid handler result", reason="INVALID_OUTPUT")
        return result


def _json_arguments(value: JSONObject) -> JSONObject | None:
    try:
        encoded = json.dumps(value, allow_nan=False)
        decoded = json.loads(encoded)
        if isinstance(decoded, dict) and decoded == value and len(encoded) <= 1_048_576:
            return decoded
    except (ValueError, TypeError, RecursionError):
        pass
    return None
