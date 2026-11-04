"""Run one Odoo module on an owned database, including bounded interruption cleanup."""

import socket
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

from mccann_hub.devkit.contracts import CommandResult, Context, DevkitError, JSONObject, Status
from mccann_hub.devkit.processes import run_process
from mccann_hub.devkit.schemas import validate
from mccann_hub.devkit_odoo.inventory import Inventory, scan
from mccann_hub.devkit_odoo.runtime_environment import (
    Runtime,
    prerequisites,
    process_failure,
    write_config,
)
from mccann_hub.devkit_odoo.runtime_report import outcome
from mccann_hub.devkit_odoo.validation import contained

EXECUTABLE: JSONObject = {"type": "string", "minLength": 1, "maxLength": 4096}
PREREQUISITE_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"odoo_bin": EXECUTABLE},
}
INPUT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "odoo_bin": EXECUTABLE,
        "module": {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_]{0,127}$"},
        "addons_paths": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 1024},
        },
    },
}
ADDONS = Path(__file__).parent / "_runtime_addons"


def check(context: Context, arguments: JSONObject) -> CommandResult:
    runtime = prerequisites(context, arguments.get("odoo_bin"))
    if isinstance(runtime, CommandResult):
        return runtime
    return CommandResult(
        "success",
        "Odoo 19 and PostgreSQL runtime prerequisites are available",
        {"tool_version": runtime.version},
    )


def _options(context: Context, arguments: JSONObject) -> JSONObject:
    configured = context.settings.get("odoo", {})
    options = {key: configured[key] for key in ("module", "addons_paths") if key in configured}
    options.update(arguments)
    try:
        validate(options, INPUT_SCHEMA)
    except Exception as exc:
        raise DevkitError(
            "INVALID_CONFIG", "Select one Odoo module and contained addons_paths"
        ) from exc
    inventory = Inventory()
    paths = options.get("addons_paths", ["addons"])
    if any("," in path or "\n" in path for path in paths) or "," in str(ADDONS):
        raise DevkitError("INVALID_ADDONS", "Native addons paths cannot contain commas or newlines")
    scan(context, paths, inventory)
    if "devkit_test_reporter" in inventory.modules:
        raise DevkitError("INVALID_ADDONS", "The devkit_test_reporter addon name is reserved")
    if "module" not in options and len(inventory.modules) == 1:
        options["module"] = next(iter(inventory.modules))
    if options.get("module") not in inventory.modules:
        raise DevkitError(
            "MISSING_ADDONS", "Select one available addon with module and addons_paths"
        )
    options["addons_paths"] = [str(contained(context.project_root, path)) for path in paths]
    return options


def test(context: Context, arguments: JSONObject) -> CommandResult:
    try:
        options = _options(context, arguments)
    except DevkitError as exc:
        if exc.reason == "CANCELLED":
            return CommandResult("cancelled", str(exc), reason=exc.reason)
        status: Status = (
            "blocked" if exc.reason in {"MISSING_ADDONS", "INVENTORY_UNAVAILABLE"} else "error"
        )
        return CommandResult(status, str(exc), reason=exc.reason)
    runtime = prerequisites(context, options.get("odoo_bin"))
    if isinstance(runtime, CommandResult):
        return runtime
    token = uuid4().hex
    data: JSONObject = {
        "module": options["module"],
        "tool_version": runtime.version,
        "database": "devkit_test_" + token,
        "tests": None,
        "failures": [],
        "failures_omitted": 0,
        "exit_code": None,
        "log_tail": "",
        "cleanup": {"status": "not_needed"},
    }
    with tempfile.TemporaryDirectory(prefix="devkit-odoo-") as directory:
        job = Path(directory)
        try:
            write_config(job / "odoo.conf", runtime)
        except OSError:
            return CommandResult(
                "error", "Cannot prepare private Odoo configuration", data, "RUNTIME_UNAVAILABLE"
            )
        try:
            result = _run(context, options, runtime, job, token, data)
        except OSError:
            result = CommandResult(
                "error", "Cannot prepare or inspect Odoo runtime files", data, "RUNTIME_UNAVAILABLE"
            )
        finally:
            _cleanup(context, runtime, data)
    return _finalize(context, result, data)


def _run(
    context: Context, options: JSONObject, runtime: Runtime, job: Path, token: str, data: JSONObject
) -> CommandResult:
    # Only this generated database can be dropped, including a partially completed create.
    created = run_process(
        [runtime.tools["createdb"], "--no-password", "--maintenance-db=postgres", data["database"]],
        context,
        environment=runtime.environment,
    )
    if error := process_failure(created):
        return error
    if created.returncode:
        return CommandResult(
            "error", "Cannot create disposable Odoo database", data, "DATABASE_CREATE_FAILED"
        )
    environment = {
        **runtime.environment,
        "ODOO_TEST_FAILURE_RETRIES": "0",
        "DEVKIT_ODOO_REPORT": str(job / "report.json"),
        "DEVKIT_ODOO_JOB_TOKEN": token,
    }
    argv = _argv(runtime, options, job, data["database"])
    with tempfile.TemporaryFile() as log:
        # Constant shell code forwards every argument literally and merges Odoo's native logs.
        process = run_process(
            ["/bin/sh", "-c", 'exec "$@" 2>&1', "devkit-odoo-tests", *argv],
            context,
            environment=environment,
            stdout_file=log,
        )
        log.seek(0, 2)
        log.seek(max(0, log.tell() - 8192))
        data.update(exit_code=process.returncode, log_tail=log.read().decode(errors="replace"))
    if error := process_failure(process):
        return error
    return outcome(job / "report.json", token, data)


def _argv(runtime: Runtime, options: JSONObject, job: Path, database: str) -> list[str]:
    # Separate loopback ports permit concurrent HttpCase jobs without disabling HTTP tests.
    # Odoo performs the final bind. A lost allocation race fails the run rather than passing it.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return [
        runtime.tools["odoo"],
        f"--config={job / 'odoo.conf'}",
        f"--database={database}",
        f"--init={options['module']}",
        "--addons-path=" + ",".join([str(ADDONS), *options["addons_paths"]]),
        "--load=base,web,devkit_test_reporter",
        f"--data-dir={job / 'data'}",
        "--stop-after-init",
        "--workers=0",
        "--max-cron-threads=0",
        "--test-enable",
        f"--test-tags=/{options['module']}",
        "--http-interface=127.0.0.1",
        f"--http-port={port}",
    ]


def _cleanup(context: Context, runtime: Runtime, data: JSONObject) -> None:
    cleanup_context = replace(context, deadline=time.monotonic() + 10, cancellation=Event())
    process = run_process(
        [
            runtime.tools["dropdb"],
            "--no-password",
            "--maintenance-db=postgres",
            "--if-exists",
            "--force",
            data["database"],
        ],
        cleanup_context,
        environment=runtime.environment,
    )
    removed = process.returncode == 0 and not process.reason and not process.truncated
    data["cleanup"] = {"status": "complete" if removed else "failed"}


def _finalize(context: Context, result: CommandResult, data: JSONObject) -> CommandResult:
    if time.monotonic() >= context.deadline:
        return CommandResult(
            "error", "Odoo job deadline exceeded; inspect database cleanup", data, "TIMEOUT"
        )
    if context.cancellation.is_set():
        return CommandResult(
            "cancelled", "Odoo job cancelled; inspect database cleanup", data, "CANCELLED"
        )
    if data["cleanup"]["status"] == "failed":
        return CommandResult(
            "error",
            "Could not remove disposable database; inspect database identity",
            data,
            "CLEANUP_FAILED",
        )
    return CommandResult(result.status, result.summary, data, result.reason)
