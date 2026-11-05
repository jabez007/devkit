"""Run the project's installed Vue check tools against one clean commit."""

import uuid
from pathlib import Path

from delivery_common import DeliveryError as DeliveryError
from delivery_common import _github, capture, commit, load_json, save

REQUIRED_TOOLS = ("vitest", "eslint", "vue-tsc")
PLAYWRIGHT_CONFIGS = tuple(
    "playwright.config." + suffix for suffix in ("js", "ts", "mjs", "mts", "cjs", "cts")
)


def _package(project):
    value, _ = load_json(Path(project) / "package.json")
    if not isinstance(value, dict):
        raise DeliveryError("INVALID_VUE_PROJECT")
    dependencies = {}
    for field in ("dependencies", "devDependencies"):
        entries = value.get(field, {})
        if not isinstance(entries, dict):
            raise DeliveryError("INVALID_VUE_PROJECT")
        dependencies.update(entries)
    if not {"vue", *REQUIRED_TOOLS} <= dependencies.keys():
        raise DeliveryError("VUE_DEPENDENCIES_REQUIRED")
    playwright = bool({"@playwright/test", "playwright"} & dependencies.keys())
    configured = any((Path(project) / name).exists() for name in PLAYWRIGHT_CONFIGS)
    if configured and not playwright:
        raise DeliveryError("PLAYWRIGHT_DEPENDENCY_REQUIRED")
    return [*REQUIRED_TOOLS, *(["playwright"] if playwright else [])]


def _tool(project, name):
    path = Path(project) / "node_modules/.bin" / name
    if not path.is_file() or not path.resolve().is_relative_to(project):
        raise DeliveryError("CHECK_TOOL_UNAVAILABLE")
    return str(path)


def validate(job):
    required = {"project", "runner", "artifacts"}
    if not isinstance(job, dict) or not required <= set(job) <= required | {"github"}:
        raise DeliveryError("INVALID_JOB")
    for field in ("project", "artifacts"):
        path = Path(job[field])
        if not path.is_absolute() or path.resolve() != path:
            raise DeliveryError("INVALID_JOB")
    project, artifacts = Path(job["project"]), Path(job["artifacts"])
    if not project.is_dir() or artifacts.is_relative_to(project):
        raise DeliveryError("INVALID_JOB")
    runner = job["runner"]
    if (
        not isinstance(runner, list)
        or len(runner) > 32
        or any(not isinstance(value, str) or not value or len(value) > 4096 for value in runner)
    ):
        raise DeliveryError("INVALID_JOB")
    if "github" in job:
        _github(job["github"])
    for name in _package(project):
        _tool(project, name)
    return job


def _plan(job, directory):
    tools = {name: _tool(job["project"], name) for name in _package(job["project"])}
    commands = {
        "vitest": [
            tools["vitest"],
            "run",
            "--reporter=json",
            "--outputFile",
            str(directory / "vitest.json"),
        ],
        "eslint": [
            tools["eslint"],
            ".",
            "--max-warnings",
            "0",
            "--format",
            "json",
            "--output-file",
            str(directory / "eslint.json"),
        ],
        "vue-tsc": [tools["vue-tsc"], "--noEmit", "--pretty", "false"],
    }
    if "playwright" in tools:
        commands["playwright"] = [tools["playwright"], "test", "--reporter=json"]
    return commands


def _json(path):
    try:
        value, _ = load_json(path, 1_000_000)
        return value
    except (OSError, ValueError, DeliveryError) as error:
        raise DeliveryError("INVALID_CHECK_OUTPUT") from error


def _count(value):
    if type(value) is not int or value < 0:
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    return value


def _vitest(directory, code):
    value = _json(directory / "vitest.json")
    total, failed, skipped = (
        _count(value[key]) for key in ("numTotalTests", "numFailedTests", "numPendingTests")
    )
    passed = _count(value["numPassedTests"])
    if total <= skipped:
        raise DeliveryError("NO_TESTS_EXECUTED")
    if passed + failed + skipped != total or (code == 0) != (value.get("success") is True):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    if code == 0 and failed:
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    return dict(tests=dict(run=total - skipped, failed=failed, skipped=skipped))


def _eslint(directory, code):
    value = _json(directory / "eslint.json")
    if not isinstance(value, list):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    errors = sum(_count(item["errorCount"]) for item in value)
    warnings = sum(_count(item["warningCount"]) for item in value)
    if (code == 0) != (errors + warnings == 0):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    return dict(errors=errors, warnings=warnings)


def _playwright(directory, code):
    value = _json(directory / "playwright.stdout")
    counts = value["stats"]
    passed, failed, flaky, skipped = (
        _count(counts[key]) for key in ("expected", "unexpected", "flaky", "skipped")
    )
    if value.get("errors") or passed + failed + flaky == 0:
        raise DeliveryError("PLAYWRIGHT_INCOMPLETE")
    if code == 0 and failed + flaky:
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    return dict(tests=dict(run=passed + failed + flaky, failed=failed + flaky, skipped=skipped))


def _execute(job, directory, name, arguments):
    code = capture(job, directory, name, arguments)
    semantic = {"vitest": {0, 1}, "eslint": {0, 1}, "vue-tsc": {0, 1, 2}, "playwright": {0, 1}}
    if code not in semantic[name]:
        raise DeliveryError("CHECK_TOOL_FAILED")
    readers = {"vitest": _vitest, "eslint": _eslint, "playwright": _playwright}
    try:
        data = readers[name](directory, code) if name in readers else {}
    except (KeyError, TypeError, AttributeError) as error:
        raise DeliveryError("INVALID_CHECK_OUTPUT") from error
    status = "success" if code == 0 else "failed"
    return dict(
        name=name,
        command=[*job["runner"], *arguments],
        exit_code=code,
        result=dict(
            status=status,
            reason=None if code == 0 else "VALIDATION_FAILED",
            summary=name + (" passed" if code == 0 else " failed"),
            data=data,
        ),
    )


def run(job, reference):
    head = commit(job["project"])
    directory = Path(job["artifacts"]) / ("checks-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700, parents=True)
    result = dict(
        status="blocked",
        reason=None,
        commit=head,
        brief=reference,
        directory=str(directory),
        checks=[],
    )
    try:
        for name, arguments in _plan(job, directory).items():
            check = _execute(job, directory, name, arguments)
            result["checks"].append(check)
            if check["result"]["status"] != "success":
                break
        result["status"] = (
            "success"
            if all(item["result"]["status"] == "success" for item in result["checks"])
            else "failed"
        )
        result["reason"] = None if result["status"] == "success" else "CHECKS_NOT_PASSED"
        if commit(job["project"]) != head:
            raise DeliveryError("CHECKED_COMMIT_CHANGED")
    except DeliveryError as error:
        result.update(status="blocked", reason=error.reason)
    save(directory / "results.json", result)
    return result
