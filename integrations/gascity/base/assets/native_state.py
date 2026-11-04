"""Bounded JSON commands and identity checks for the native Beads task store."""

import json
import os
import re
import subprocess
from pathlib import Path

BEAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


class StateError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _identity(value):
    if not isinstance(value, str) or BEAD_ID.fullmatch(value) is None:
        raise StateError("INVALID_TASK_STATE")
    return value


def _invoke(arguments, timeout):
    binary, city = os.environ.get("GC_BIN", ""), os.environ.get("GC_CITY_PATH", "")
    if not Path(binary).is_absolute() or not Path(city).is_absolute():
        raise StateError("TASK_STATE_UNAVAILABLE")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            [binary, *arguments],
            cwd=city,
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise StateError("TASK_STATE_UNAVAILABLE") from error
    if result.returncode:
        raise StateError("TASK_STATE_UNAVAILABLE")
    if len(result.stdout) > 1_000_000:
        raise StateError("INVALID_TASK_STATE")
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError as error:
        raise StateError("INVALID_TASK_STATE") from error


def _gc(*arguments):
    return _invoke(["--city", os.environ.get("GC_CITY_PATH", ""), "bd", *arguments, "--json"], 30)


def _pack(*arguments):
    # Native pack commands discover the selected city from cwd; leading --city leaks to argv.
    return _invoke(list(arguments), 60)


def _show(identity):
    identity = _identity(identity)
    bead = _gc("show", identity)
    if isinstance(bead, list) and len(bead) == 1:
        bead = bead[0]
    if (
        not isinstance(bead, dict)
        or bead.get("id") != identity
        or not isinstance(bead.get("status"), str)
    ):
        raise StateError("INVALID_TASK_STATE")
    if not isinstance(bead.get("metadata", {}), dict):
        raise StateError("INVALID_TASK_STATE")
    return bead


def _members(workflow):
    result = _gc(
        "list",
        "--all",
        "--include-ephemeral",
        "--include-gates",
        "--limit",
        "256",
        "--metadata-field",
        "gc.root_bead_id=" + _identity(workflow),
    )
    if not isinstance(result, list) or len(result) >= 256:
        raise StateError("INVALID_TASK_STATE")
    if any(
        not isinstance(bead, dict) or not isinstance(bead.get("metadata", {}), dict)
        for bead in result
    ):
        raise StateError("INVALID_TASK_STATE")
    return result


def _update(identity, values):
    arguments = ["update", _identity(identity)]
    for key, value in values.items():
        arguments.extend(["--set-metadata", key + "=" + value])
    _gc(*arguments)
