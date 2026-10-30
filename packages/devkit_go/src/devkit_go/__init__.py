"""Go test specialization using the system toolchain."""

import json

from devkit.contracts import EFFECTS, CheckSpec, CommandResult, Context, JSONObject, Specialization
from devkit.contracts import CommandSpec as CommandSpec
from devkit.processes import ProcessResult, run_process


def _process_failure(result: ProcessResult) -> CommandResult | None:
    statuses = {"MISSING_TOOL": "blocked", "CANCELLED": "cancelled"}
    if result.reason:
        from typing import cast

        from devkit.contracts import Status

        return CommandResult(
            cast(Status, statuses.get(result.reason, "error")),
            "Go execution did not complete",
            reason=result.reason,
        )
    if result.truncated:
        return CommandResult("error", "Test output exceeded capture limit", reason="OUTPUT_LIMIT")
    return None


def _counts(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    actions = {"pass": "passed", "fail": "failed", "skip": "skipped"}
    for line in output.splitlines():
        event = json.loads(line)
        action = event.get("Action")
        if event.get("Test") and action in actions:
            counts[actions[action]] += 1
    return counts


def test(context: Context, arguments: JSONObject) -> CommandResult:
    version = run_process(["go", "version"], context)
    if error := _process_failure(version):
        return error
    process = run_process(["go", "test", "-json", "-count=1", "./..."], context)
    if error := _process_failure(process):
        return error
    data = {
        "tool_version": version.stdout.strip(),
        "stdout": process.stdout,
        "stderr": process.stderr,
        "exit_code": process.returncode,
    }
    try:
        counts = _counts(process.stdout)
    except (ValueError, AttributeError):
        return CommandResult("error", "Unrecognized Go test output", data, "INVALID_TOOL_OUTPUT")
    data["tests"] = counts
    if process.returncode != 0:
        return CommandResult("failed", "Go tests failed", data, "TEST_FAILED")
    if not counts["passed"] + counts["failed"]:
        return CommandResult("blocked", "No tests executed", data, "NO_TESTS")
    return CommandResult("success", "Go tests passed", data)


def register() -> Specialization:
    return Specialization(
        "go",
        (
            CommandSpec(
                "go.test",
                "Run Go tests without cached results",
                test,
                effects=EFFECTS,
            ),
        ),
        checks=(CheckSpec("go.tests", "go.test"),),
    )
