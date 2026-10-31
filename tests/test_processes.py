import sys
import time
from pathlib import Path
from threading import Event, Timer

from devkit.contracts import Context
from devkit.processes import OUTPUT_LIMIT, run_process


def context(tmp_path, duration=3):
    return Context(tmp_path, "test", time.monotonic() + duration, Event())


def test_output_is_bounded_and_streams_do_not_deadlock(tmp_path):
    result = run_process(
        [
            sys.executable,
            "-c",
            f'import sys; print("x"*{OUTPUT_LIMIT + 50}); '
            f'print("y"*{OUTPUT_LIMIT + 50}, file=sys.stderr)',
        ],
        context(tmp_path),
    )
    assert result.returncode == 0
    assert result.truncated
    assert len(result.stdout) == len(result.stderr) == OUTPUT_LIMIT


def test_timeout_terminates_child_process(tmp_path):
    script = (
        "import subprocess,time; from pathlib import Path; "
        'p=subprocess.Popen(["sleep","30"]); Path("pid").write_text(str(p.pid)); '
        "time.sleep(30)"
    )
    result = run_process([sys.executable, "-c", script], context(tmp_path, 0.4))
    assert result.reason == "TIMEOUT"
    pid = int((tmp_path / "pid").read_text())
    status = Path(f"/proc/{pid}/stat")
    assert not status.exists() or status.read_text().split()[2] == "Z"


def test_cancellation_and_environment_filter(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    timer = Timer(0.1, ctx.cancellation.set)
    timer.start()
    result = run_process(["sleep", "30"], ctx)
    timer.join()
    assert result.reason == "CANCELLED"
    monkeypatch.setenv("TEST_SECRET", "must-not-inherit")
    result = run_process(
        [sys.executable, "-c", 'import os; print(os.getenv("TEST_SECRET"))'], context(tmp_path)
    )
    assert result.stdout.strip() == "None"
    assert run_process(["/missing/tool"], context(tmp_path)).reason == "MISSING_TOOL"


def test_explicit_environment_replaces_inherited_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GOPROXY", "must-not-inherit")
    result = run_process(
        [
            sys.executable,
            "-c",
            'import os; print(os.getenv("BD_DISABLE_METRICS")); '
            'print(os.getenv("GOPROXY")); print(os.getenv("GOENV"))',
        ],
        context(tmp_path),
        environment={"BD_DISABLE_METRICS": "1"},
    )
    assert result.stdout.splitlines() == ["1", "None", "None"]
