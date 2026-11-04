"""Run the Odoo gates against one clean commit using operator-selected tools."""

import fnmatch
import json
import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path


class DeliveryError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def environment():
    result = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    return result


def git(project, *args):
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=project,
            env=environment(),
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeliveryError("GIT_UNAVAILABLE") from error
    if result.returncode or len(result.stdout) > 1_000_000:
        raise DeliveryError("GIT_UNAVAILABLE")
    return result.stdout.decode("utf-8").strip()


def commit(project):
    if git(project, "status", "--porcelain=v1", "--untracked-files=all"):
        raise DeliveryError("COMMIT_CHANGES_BEFORE_CHECKS")
    return git(project, "rev-parse", "HEAD")


def validate(job):
    required = {"project", "base_commit", "addons_paths", "runner", "artifacts"}
    if not isinstance(job, dict) or set(job) - required - {"github"} or not required <= set(job):
        raise DeliveryError("INVALID_JOB")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(job["base_commit"])):
        raise DeliveryError("INVALID_JOB")
    for key in ("project", "artifacts"):
        path = Path(job[key])
        if not path.is_absolute() or path.resolve() != path:
            raise DeliveryError("INVALID_JOB")
    project, artifacts = Path(job["project"]), Path(job["artifacts"])
    if not project.is_dir() or artifacts.is_relative_to(project):
        raise DeliveryError("INVALID_JOB")
    _lists(job)
    if "github" in job:
        _github(job["github"])
    git(project, "cat-file", "-e", job["base_commit"] + "^{commit}")
    return job


def _lists(job):
    for key, minimum in (("addons_paths", 1), ("runner", 0)):
        values = job[key]
        if not isinstance(values, list) or not minimum <= len(values) <= 32:
            raise DeliveryError("INVALID_JOB")
        if any(not isinstance(value, str) or not value or len(value) > 4096 for value in values):
            raise DeliveryError("INVALID_JOB")
    for value in job["addons_paths"]:
        if Path(value).is_absolute() or ".." in Path(value).parts:
            raise DeliveryError("INVALID_JOB")


def _github(github):
    if not isinstance(github, dict) or set(github) != {
        "repo",
        "remote",
        "base",
        "head",
        "protected_branches",
    }:
        raise DeliveryError("INVALID_JOB")
    patterns = {
        "repo": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        "remote": r"[A-Za-z0-9][A-Za-z0-9_.-]*",
        "base": r"[A-Za-z0-9][A-Za-z0-9_./-]*",
        "head": r"[A-Za-z0-9][A-Za-z0-9_./-]*",
    }
    if any(not re.fullmatch(pattern, str(github[key])) for key, pattern in patterns.items()):
        raise DeliveryError("INVALID_JOB")
    protected = github["protected_branches"]
    if not isinstance(protected, list) or any(not isinstance(item, str) for item in protected):
        raise DeliveryError("INVALID_JOB")
    if any(
        fnmatch.fnmatchcase(github["head"], pattern)
        for pattern in [github["base"], "main", "master", *protected]
    ):
        raise DeliveryError("PROTECTED_BRANCH")


def save(path, value):
    content = json.dumps(value, ensure_ascii=True, indent=2).encode() + b"\n"
    with path.open("xb") as stream:
        stream.write(content)
    path.chmod(0o400)


def execute(job, directory, name, arguments):
    """Capture bytes in private files, supervise descendants, and bound the JSON read."""
    command = [*job["runner"], *arguments]
    with (
        (directory / (name + ".stdout")).open("xb") as out,
        (directory / (name + ".stderr")).open("xb") as err,
    ):
        try:
            process = subprocess.Popen(
                command,
                cwd=job["project"],
                env=environment(),
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        except OSError as error:
            raise DeliveryError("CHECK_TOOL_UNAVAILABLE") from error
        try:
            code = _wait(process, out, err)
        except BaseException:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise DeliveryError("CHECK_INTERRUPTED") from None
    with (directory / (name + ".stdout")).open("rb") as stream:
        raw = stream.read(1_000_001)
    try:
        result = json.loads(raw) if len(raw) <= 1_000_000 else None
    except ValueError:
        result = None
    envelope = result
    if arguments[0] == "devkit" and isinstance(envelope, dict):
        result = envelope.get("result")
    if not isinstance(result, dict) or result.get("status") not in {
        "success",
        "failed",
        "blocked",
        "denied",
        "error",
        "cancelled",
    }:
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    if (code == 0) != (result["status"] == "success"):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    if (
        arguments[0] == "devkit"
        and result["status"] == "success"
        and not all(
            isinstance(envelope.get(key), str) and envelope[key]
            for key in ("evidence_path", "run_id")
        )
    ):
        raise DeliveryError("MISSING_CHECK_EVIDENCE")
    return {
        "name": name,
        "command": command,
        "exit_code": code,
        "result": result,
        "evidence_path": envelope.get("evidence_path"),
        "run_id": envelope.get("run_id"),
    }


def _wait(process, out, err):
    deadline = time.monotonic() + 600
    while True:
        if (
            time.monotonic() > deadline
            or max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size) > 67_108_864
        ):
            raise DeliveryError("CHECK_CAPTURE_LIMIT")
        try:
            return process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass


def run(job, reference):
    head = commit(job["project"])
    directory = Path(job["artifacts"]) / ("checks-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700, parents=True)
    result = {
        "status": "blocked",
        "reason": None,
        "commit": head,
        "brief": reference,
        "directory": str(directory),
        "checks": [],
    }
    try:
        arguments = {"base_commit": job["base_commit"], "addons_paths": job["addons_paths"]}
        cli = ["devkit", "--project", job["project"], "--json", "run"]
        versions = execute(
            job,
            directory,
            "versions",
            [*cli, "odoo.module.version.check", "--args", json.dumps(arguments)],
        )
        result["checks"].append(versions)
        if versions["result"]["status"] == "success":
            _module_checks(job, directory, cli, versions["result"], result["checks"])
        statuses = [check["result"]["status"] for check in result["checks"]]
        result["status"] = (
            "success"
            if all(status == "success" for status in statuses)
            else ("failed" if "failed" in statuses else "blocked")
        )
        result["reason"] = None if result["status"] == "success" else "CHECKS_NOT_PASSED"
        if commit(job["project"]) != head:
            raise DeliveryError("CHECKED_COMMIT_CHANGED")
    except DeliveryError as error:
        result.update(status="blocked", reason=error.reason)
    save(directory / "results.json", result)
    return result


def _module_checks(job, directory, cli, versions, checks):
    data = versions.get("data", {})
    if not isinstance(data, dict):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    modules = data.get("modules")
    if data.get("inspection_complete") is not True or not isinstance(modules, list):
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    if len(modules) > 128:
        raise DeliveryError("INVALID_CHECK_OUTPUT")
    if not modules:
        raise DeliveryError("NO_CHANGED_ADDONS")
    names = [item.get("module") for item in modules if isinstance(item, dict)]
    if (
        len(names) != len(modules)
        or any(
            not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
            for name in names
        )
        or len(set(names)) != len(names)
    ):
        raise DeliveryError("AMBIGUOUS_ADDON_NAMES")
    for name in names:
        flags = [flag for path in job["addons_paths"] for flag in ("--addons-path", path)]
        static = [
            "devkit-odoo",
            "--project",
            job["project"],
            "--json",
            *flags,
            "--module",
            name,
            "--install-mode",
            "fresh",
        ]
        checks.append(execute(job, directory, "static-" + name, static))
    if any(check["result"]["status"] != "success" for check in checks):
        return
    for name in names:
        arguments = {"module": name, "addons_paths": job["addons_paths"]}
        checks.append(
            execute(
                job,
                directory,
                "runtime-" + name,
                [*cli, "odoo.module.test", "--args", json.dumps(arguments)],
            )
        )
