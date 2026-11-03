"""Go test specialization using the system toolchain."""

import json
import os
import tempfile
from collections.abc import Iterable

from mccann_hub.devkit.contracts import (
    EFFECTS,
    CheckSpec,
    CommandResult,
    Context,
    JSONObject,
    Specialization,
)
from mccann_hub.devkit.contracts import CommandSpec as CommandSpec
from mccann_hub.devkit.processes import ProcessResult, run_process
from mccann_hub.devkit.schemas import validate

INPUT_SCHEMA: JSONObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "packages": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            # A leading dash would be read as a go test flag such as -exec.
            "items": {"type": "string", "pattern": "^[^-]", "maxLength": 512},
        },
        "run": {"type": "string", "minLength": 1, "maxLength": 1024},
        "tags": {
            "type": "array",
            "maxItems": 64,
            "items": {"type": "string", "pattern": "^[A-Za-z0-9_.]+$", "maxLength": 128},
        },
        "race": {"type": "boolean"},
    },
}


def _process_failure(result: ProcessResult) -> CommandResult | None:
    statuses = {"MISSING_TOOL": "blocked", "CANCELLED": "cancelled"}
    if result.reason:
        from typing import cast

        from mccann_hub.devkit.contracts import Status

        return CommandResult(
            cast(Status, statuses.get(result.reason, "error")),
            "Go execution did not complete",
            reason=result.reason,
        )
    if result.truncated:
        return CommandResult("error", "Test output exceeded capture limit", reason="OUTPUT_LIMIT")
    return None


ACTIONS = {"pass": "passed", "fail": "failed", "skip": "skipped"}
FAILURE_LIMIT = 50
FAILURE_OUTPUT_LIMIT = 4096
SUMMARY_NAMES = 20


class _Report:
    """Counts and failures from go test -json events, read in one pass.

    Output is held only until its test or package finishes, and only the tail of each,
    so memory stays bounded however much a passing suite prints.
    """

    def __init__(self) -> None:
        self.counts = dict.fromkeys(ACTIONS.values(), 0)
        self.failures: list[JSONObject] = []
        self._failure_total = 0
        self._output: dict[tuple[str | None, str | None], str] = {}
        self._packages_with_failed_tests: set[str | None] = set()

    def read(self, lines: Iterable[bytes]) -> None:
        for line in lines:
            self._add(json.loads(line))

    def _add(self, event: JSONObject) -> None:
        action = event.get("Action")
        package, test = event.get("Package"), event.get("Test")
        if action in {"output", "build-output"}:
            # Go 1.24+ reports compiler errors as build-output keyed by ImportPath.
            key = (event.get("ImportPath") or package, test)
            text = self._output.get(key, "") + event.get("Output", "")
            self._output[key] = text[-FAILURE_OUTPUT_LIMIT:]
            return
        if action not in ACTIONS:
            return
        output = self._output.pop((package, test), "")
        if test:
            self.counts[ACTIONS[action]] += 1
            if action == "fail":
                self._packages_with_failed_tests.add(package)
                self._record(package, test, output)
        elif action == "fail" and package not in self._packages_with_failed_tests:
            build = self._output.pop((event.get("FailedBuild"), None), "")
            self._record(package, None, (build + output)[-FAILURE_OUTPUT_LIMIT:])

    def _record(self, package: str | None, test: str | None, output: str) -> None:
        self._failure_total += 1
        if len(self.failures) < FAILURE_LIMIT:
            self.failures.append({"package": package, "test": test, "output": output})

    def summary(self) -> str:
        names = [
            f"{item['package']}.{item['test']}" if item["test"] else f"{item['package']}"
            for item in self.failures
        ]
        if not names:
            return "Go tests failed"
        more = self._failure_total - min(len(names), SUMMARY_NAMES)
        listed = ", ".join(names[:SUMMARY_NAMES]) + (f", and {more} more" if more > 0 else "")
        return f"Go tests failed: {listed}"


def _environment() -> dict[str, str]:
    """Tests get the caller's environment, as with plain go test; DSNs and flags live there.

    GOTOOLCHAIN defaults to local so a go.mod toolchain line cannot trigger a download.
    """
    return {"GOTOOLCHAIN": "local", **os.environ}


def _go_test_argv(options: JSONObject) -> list[str]:
    argv = ["go", "test", "-json", "-count=1"]
    if options.get("race"):
        argv.append("-race")
    if options.get("tags"):
        argv.append("-tags=" + ",".join(options["tags"]))
    if "run" in options:
        argv.append("-run=" + options["run"])
    packages: list[str] = options.get("packages", ["./..."])
    return argv + packages


def test(context: Context, arguments: JSONObject) -> CommandResult:
    options = {**context.settings.get("go", {}), **arguments}
    try:
        validate(options, INPUT_SCHEMA)
    except Exception:
        return CommandResult(
            "error",
            "Invalid Go options; check [options.go] and arguments: packages, run, tags, race",
            reason="INVALID_CONFIG",
        )
    environment = _environment()
    version = run_process(["go", "version"], context, environment=environment)
    if error := _process_failure(version):
        return error
    # go test -json emits an event per output line, so large suites exceed in-memory capture.
    with tempfile.TemporaryFile() as events:
        process = run_process(
            _go_test_argv(options),
            context,
            environment=environment,
            stdout_file=events,
        )
        if error := _process_failure(process):
            return error
        data: JSONObject = {
            "tool_version": version.stdout.strip(),
            "stderr": process.stderr,
            "exit_code": process.returncode,
        }
        events.seek(0)
        report = _Report()
        try:
            report.read(events)
        except (ValueError, AttributeError, TypeError):
            return CommandResult(
                "error", "Unrecognized Go test output", data, "INVALID_TOOL_OUTPUT"
            )
    counts = report.counts
    data["tests"] = counts
    data["failures"] = report.failures
    if process.returncode != 0:
        return CommandResult("failed", report.summary(), data, "TEST_FAILED")
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
                input_schema=INPUT_SCHEMA,
                effects=EFFECTS,
            ),
        ),
        checks=(CheckSpec("go.tests", "go.test"),),
    )
