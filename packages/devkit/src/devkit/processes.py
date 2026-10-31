"""Bounded subprocess execution for trusted project commands on Linux."""

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass

from devkit.contracts import Context

OUTPUT_LIMIT = 262_144
ENVIRONMENT = {
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "GOPATH",
    "GOCACHE",
    "GOMODCACHE",
    "GOPROXY",
    "GOSUMDB",
    "GOPRIVATE",
    "GONOSUMDB",
    "GONOPROXY",
}


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    reason: str | None = None
    truncated: bool = False


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Always kill the group, including descendants after the parent exits."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        time.sleep(0.1)
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def _read_output(selector: selectors.BaseSelector, buffers: dict[str, bytearray]) -> bool:
    truncated = False
    for key, _ in selector.select(timeout=0.05):
        chunk = os.read(key.fd, 65536)
        if not chunk:
            selector.unregister(key.fileobj)
            continue
        buffer = buffers[key.data]
        remaining = OUTPUT_LIMIT - len(buffer)
        buffer.extend(chunk[:remaining])
        truncated |= len(chunk) > remaining
    return truncated


def _collect(process: subprocess.Popen[bytes], context: Context) -> ProcessResult:
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    reason = None
    truncated = False
    with selectors.DefaultSelector() as selector:
        assert process.stdout is not None and process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map() or process.poll() is None:
            if context.cancellation.is_set():
                reason = "CANCELLED"
                break
            if time.monotonic() >= context.deadline:
                reason = "TIMEOUT"
                break
            truncated |= _read_output(selector, buffers)
    returncode = process.poll()
    return ProcessResult(
        returncode if returncode is not None else -1,
        buffers["stdout"].decode(errors="replace"),
        buffers["stderr"].decode(errors="replace"),
        reason,
        truncated,
    )


def run_process(
    argv: list[str], context: Context, *, environment: Mapping[str, str] | None = None
) -> ProcessResult:
    """Run with bounded capture and cancellation; an explicit environment replaces defaults."""
    if environment is None:
        environment = {key: value for key, value in os.environ.items() if key in ENVIRONMENT}
        environment.update(GOENV="off", GOTOOLCHAIN="local")
    try:
        process = subprocess.Popen(
            argv,
            cwd=context.project_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        return ProcessResult(-1, "", "Required executable is unavailable", "MISSING_TOOL")
    except OSError:
        return ProcessResult(-1, "", "Cannot start executable", "PROCESS_ERROR")
    try:
        return _collect(process, context)
    except KeyboardInterrupt:
        context.cancellation.set()
        return ProcessResult(-1, "", "", "CANCELLED")
    finally:
        _terminate(process)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
