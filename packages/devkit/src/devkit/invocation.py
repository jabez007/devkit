"""One command execution path for Python, the CLI, and future transports."""

import time
from dataclasses import asdict
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

from devkit.config import Settings
from devkit.contracts import CommandResult, CommandSpec, Context, DevkitError, JSONObject
from devkit.discovery import validate_command
from devkit.evidence import redact, source_identity, write_bundle
from devkit.policy import Policy, load_policy
from devkit.schemas import RESULT_SCHEMA, validate


class CommandService:
    def __init__(
        self,
        settings: Settings,
        commands: tuple[CommandSpec, ...],
        policy: Policy | None = None,
        origins: JSONObject | None = None,
    ) -> None:
        self.settings = settings
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
        )

    def execute(
        self,
        command: str,
        arguments: JSONObject | None = None,
        *,
        surface: str = "python",
        cancellation: Event | None = None,
    ) -> JSONObject:
        args = arguments if arguments is not None else {}
        run_id = str(uuid4())
        started = datetime.now(UTC).isoformat()
        context = Context(
            self.settings.project_root,
            run_id,
            time.monotonic() + self.settings.timeout,
            cancellation or Event(),
            self.settings.options,
        )
        try:
            result = self._invoke(command, args, surface, context)
        except DevkitError as exc:
            result = CommandResult("blocked", "Operator policy is unavailable", reason=exc.reason)
        envelope: JSONObject = redact(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "command": command,
                "producer": self.origins.get(
                    command, {"distribution": "devkit", "version": "0.1.0"}
                ),
                "project_root": str(self.settings.project_root),
                "arguments": args,
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
            return CommandResult("blocked", "Command unavailable here", reason="DENIED")
        try:
            validate(arguments, spec.input_schema)
        except Exception:
            return CommandResult("error", "Invalid command arguments", reason="INVALID_INPUT")
        return self._run_handler(spec, arguments, context)

    @staticmethod
    def _run_handler(spec: CommandSpec, args: JSONObject, context: Context) -> CommandResult:
        if context.cancellation.is_set():
            return CommandResult("cancelled", "Cancelled before execution", reason="CANCELLED")
        try:
            result = spec.handler(context, args)
        except KeyboardInterrupt:
            context.cancellation.set()
            return CommandResult("cancelled", "Command interrupted", reason="CANCELLED")
        except Exception:
            return CommandResult("error", "Command handler failed", reason="HANDLER_ERROR")
        if time.monotonic() > context.deadline:
            return CommandResult("error", "Command deadline exceeded", reason="TIMEOUT")
        try:
            validate(asdict(result), RESULT_SCHEMA)
            if result.status == "success":
                validate(result.data, spec.output_schema)
        except Exception:
            return CommandResult("error", "Invalid handler result", reason="INVALID_OUTPUT")
        return result
