"""Observe Odoo 19's native runner without changing selection or test outcomes."""

import atexit
import json
import os
import re
import tempfile
import traceback
from functools import partial
from pathlib import Path
from typing import Any

FAILURE_LIMIT = 50
OUTPUT_LIMIT = 4096


class Report:
    def __init__(self, path: Path, token: str) -> None:
        if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("Devkit reporting requires an absolute path and a job token")
        # A new private job directory prevents accidental reuse of an old report.
        with path.open("x"):
            path.chmod(0o600)
        self.path = path
        self.pending = 0
        self.interrupted = False
        self.data: dict[str, Any] = {
            "protocol": 1,
            "job_token": token,
            "complete": False,
            "tests": {"collected": 0, "run": 0, "failed": 0, "skipped": 0},
            "failures": [],
            "failures_omitted": 0,
        }
        self.write()

    def write(self) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(self.data, stream)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def failure(self, test: Any, error: Any) -> None:
        if len(self.data["failures"]) >= FAILURE_LIMIT:
            self.data["failures_omitted"] += 1
            return
        output = "".join(traceback.format_exception(*error, limit=20))[-OUTPUT_LIMIT:]
        self.data["failures"].append({"test": str(test.id())[:1024], "output": output})

    def finish(self) -> None:
        self.data["complete"] = self.pending == 0 and not self.interrupted
        self.write()


def _result_type(native_result: Any, report: Report) -> Any:
    # The runtime owns this untyped class; the real container tests verify its interface.
    class RecordedResult(native_result):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._devkit_active: list[Any] = []
            self._devkit_skipped_started = 0

        def startTest(self, test: Any) -> None:
            self._devkit_active.append(test)
            super().startTest(test)

        def stopTest(self, test: Any) -> None:
            super().stopTest(test)
            self._devkit_active.pop()

        def addSkip(self, test: Any, reason: Any) -> None:
            if self._devkit_active and self._devkit_active[-1] is test:
                self._devkit_skipped_started += 1
            super().addSkip(test, reason)

        def addFailure(self, test: Any, error: Any) -> None:
            before = self.failures_count
            super().addFailure(test, error)
            if self.failures_count > before:
                report.failure(test, error)

        def addError(self, test: Any, error: Any) -> None:
            before = self.errors_count
            super().addError(test, error)
            if self.errors_count > before:
                report.failure(test, error)

    return RecordedResult


def _run_suite(report: Report, native: Any, suite: Any, global_report: Any = None) -> Any:
    report.pending += 1
    report.data["tests"]["collected"] += suite.countTestCases()
    result = native(suite, global_report)
    counts = report.data["tests"]
    counts["run"] += result.testsRun - result._devkit_skipped_started
    counts["failed"] += result.failures_count + result.errors_count
    counts["skipped"] += result.skipped
    report.interrupted |= bool(result.shouldStop and result.wasSuccessful())
    report.pending -= 1
    report.write()
    return result


def install() -> None:
    # Odoo is supplied by the selected runtime, not a dependency of the offline wheel.
    from odoo import release  # type: ignore[import-not-found]
    from odoo.tests import loader  # type: ignore[import-not-found]

    if tuple(release.version_info[:2]) != (19, 0):
        raise RuntimeError("Devkit native reporting supports Odoo 19.0")
    report = Report(Path(os.environ["DEVKIT_ODOO_REPORT"]), os.environ["DEVKIT_ODOO_JOB_TOKEN"])
    loader.OdooTestResult = _result_type(loader.OdooTestResult, report)
    loader.run_suite = partial(_run_suite, report, loader.run_suite)
    atexit.register(report.finish)
