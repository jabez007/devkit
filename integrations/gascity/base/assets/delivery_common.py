"""Git identity, protected publication inputs and bounded check captures for stack packs."""

import fnmatch
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import time


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


def capture(job, directory, name, arguments):
    """Capture private output files and supervise the process group within limits."""
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
    return code


def load_json(path, limit=100_000):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise DeliveryError("INVALID_JOB")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise DeliveryError("INVALID_JOB")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()
