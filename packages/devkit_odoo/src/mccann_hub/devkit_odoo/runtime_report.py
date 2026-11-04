"""Bounded native test reports and conservative command outcomes."""

import json
import os
import stat
from pathlib import Path

from jsonschema import ValidationError
from mccann_hub.devkit.contracts import CommandResult, JSONObject
from mccann_hub.devkit.schemas import validate

COUNT = {"type": "integer", "minimum": 0, "maximum": 10_000_000}
REPORT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "required": ["protocol", "job_token", "complete", "tests", "failures", "failures_omitted"],
    "properties": {
        "protocol": {"const": 1},
        "job_token": {"type": "string"},
        "complete": {"type": "boolean"},
        "tests": {
            "type": "object",
            "additionalProperties": False,
            "required": ["collected", "run", "failed", "skipped"],
            "properties": {name: COUNT for name in ("collected", "run", "failed", "skipped")},
        },
        "failures_omitted": COUNT,
        "failures": {
            "type": "array",
            "maxItems": 50,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["test", "output"],
                "properties": {
                    "test": {"type": "string", "maxLength": 1024},
                    "output": {"type": "string", "maxLength": 4096},
                },
            },
        },
    },
}


def outcome(path: Path, token: str, data: JSONObject) -> CommandResult:
    try:
        raw = _read_report(path)
        report = json.loads(raw)
        validate(report, REPORT_SCHEMA)
        _validate_counts(report, token)
    except FileNotFoundError:
        if data["exit_code"]:
            return CommandResult(
                "failed", "Odoo installation or initialization failed", data, "INSTALL_FAILED"
            )
        return CommandResult(
            "blocked", "Native Odoo test report is unavailable", data, "TEST_REPORT_UNAVAILABLE"
        )
    except (OSError, ValueError, TypeError, RecursionError, ValidationError):
        # JSON Schema validation errors contain input values; never expose them.
        return CommandResult(
            "error", "Invalid native Odoo test report", data, "INVALID_TOOL_OUTPUT"
        )
    data.update({key: report[key] for key in ("tests", "failures", "failures_omitted")})
    return _completed(report, data)


def _read_report(path: Path) -> bytes:
    # A malformed runtime report must not block on a FIFO or follow a substituted symlink.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Report must be a regular file")
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Report exceeds limit")
    return raw


def _validate_counts(report: JSONObject, token: str) -> None:
    counts = report["tests"]
    if report["job_token"] != token or counts["run"] + counts["skipped"] > counts["collected"]:
        raise ValueError("Wrong job identity or inconsistent counts")
    if len(report["failures"]) + report["failures_omitted"] != counts["failed"]:
        raise ValueError("Failure details do not match counts")


def _completed(report: JSONObject, data: JSONObject) -> CommandResult:
    if not report["complete"]:
        return CommandResult(
            "blocked",
            "Odoo stopped before completing test execution",
            data,
            "INCOMPLETE_TEST_REPORT",
        )
    if report["tests"]["failed"]:
        names = ", ".join(item["test"] for item in report["failures"][:10])[:2048]
        return CommandResult("failed", "Odoo tests failed: " + names, data, "TEST_FAILED")
    if data["exit_code"]:
        return CommandResult(
            "failed", "Odoo installation or initialization failed", data, "INSTALL_FAILED"
        )
    if not report["tests"]["run"]:
        return CommandResult("blocked", "No Odoo tests executed", data, "NO_TESTS")
    return CommandResult("success", "Odoo tests passed", data)
