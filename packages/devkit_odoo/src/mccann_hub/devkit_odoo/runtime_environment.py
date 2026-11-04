"""Runtime prerequisites and private libpq-compatible Odoo configuration."""

import configparser
import getpass
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from mccann_hub.devkit.contracts import CommandResult, Context
from mccann_hub.devkit.processes import ProcessResult, run_process


@dataclass(frozen=True)
class Runtime:
    tools: dict[str, str]
    environment: dict[str, str]
    version: str


def process_failure(process: ProcessResult) -> CommandResult | None:
    if process.reason == "CANCELLED":
        return CommandResult("cancelled", "Odoo execution cancelled", reason="CANCELLED")
    if process.reason == "MISSING_TOOL":
        return CommandResult(
            "blocked", "Required runtime executable is unavailable", reason=process.reason
        )
    if process.reason:
        return CommandResult("error", "Odoo execution did not complete", reason=process.reason)
    if process.truncated:
        return CommandResult(
            "error", "Runtime output exceeded capture limit", reason="OUTPUT_LIMIT"
        )
    return None


def prerequisites(context: Context, executable: str | None) -> Runtime | CommandResult:
    tools = {}
    for name in ("odoo", "psql", "createdb", "dropdb"):
        candidates = [executable] if name == "odoo" and executable else [name]
        if name == "odoo" and executable is None:
            candidates = ["odoo-bin", "odoo"]
        found = next((path for value in candidates if (path := _which(value, context))), None)
        if found is None:
            return CommandResult(
                "blocked", f"Missing runtime executable: {name}", reason="MISSING_TOOL"
            )
        tools[name] = found
    # libpq service files can select a different connection than Odoo's explicit config.
    if os.environ.get("PGSERVICE") or os.environ.get("PGSERVICEFILE"):
        return CommandResult(
            "blocked",
            "Use PGHOST, PGPORT, PGUSER and optional PGPASSWORD instead of a PG service",
            reason="UNSUPPORTED_DATABASE_CONFIG",
        )
    environment = dict(os.environ)
    version = run_process([tools["odoo"], "--version"], context, environment=environment)
    if error := process_failure(version):
        return error
    if version.returncode or re.search(r"\b19\.0(?:\D|$)", version.stdout) is None:
        return CommandResult("blocked", "Odoo 19.0 is required", reason="UNSUPPORTED_ODOO")
    probe = run_process(
        [
            tools["psql"],
            "-X",
            "-A",
            "-t",
            "--no-password",
            "--dbname=postgres",
            "--command="
            "SELECT CASE WHEN rolcreatedb OR rolsuper THEN 1 ELSE 0 END "
            "FROM pg_roles WHERE rolname=current_user",
        ],
        context,
        environment=environment,
    )
    if error := process_failure(probe):
        return error
    if probe.returncode:
        return CommandResult(
            "blocked",
            "PostgreSQL maintenance database is unreachable",
            reason="DATABASE_UNAVAILABLE",
        )
    if probe.stdout.strip() != "1":
        return CommandResult(
            "blocked",
            "PostgreSQL role needs CREATEDB for disposable tests",
            reason="DATABASE_PERMISSION",
        )
    return Runtime(tools, environment, version.stdout.strip()[:256])


def _which(value: str, context: Context) -> str | None:
    if "/" in value and not Path(value).is_absolute():
        value = str(context.project_root / value)
    return shutil.which(value)


def write_config(path: Path, runtime: Runtime) -> None:
    environment = runtime.environment
    config = configparser.ConfigParser(interpolation=None)
    config["options"] = {
        "db_host": environment.get("PGHOST", "False"),
        "db_port": environment.get("PGPORT", "5432"),
        "db_user": environment.get("PGUSER", getpass.getuser()),
        "db_password": environment.get("PGPASSWORD", "False"),
        "db_sslmode": environment.get("PGSSLMODE", "prefer"),
    }
    with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        config.write(stream)
