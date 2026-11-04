"""Runtime command contracts with disposable executable adapters."""

import json
import os
import shlex
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from mccann_hub.devkit.app import create_service
from mccann_hub.devkit.contracts import EFFECTS

BACKEND = r"""
import json, os, pathlib, stat, sys, time
root = pathlib.Path(os.environ['FAKE_ODOO_ROOT'])
mode = json.loads((root / '.backend.json').read_text())
tool, *args = sys.argv[1:]
with (root / '.calls.jsonl').open('a') as log:
    log.write(json.dumps([tool, *args]) + '\n')
if tool == 'odoo-bin' and args == ['--version']:
    print(mode.get('version', 'Odoo Server 19.0'))
    sys.exit(0)
if tool == 'psql':
    if mode.get('database_unavailable'):
        sys.exit(2)
    print('0' if mode.get('no_createdb') else '1')
    sys.exit(0)
if tool in ('createdb', 'dropdb'):
    path = root / '.databases' / args[-1]
    if tool == 'createdb':
        if mode.get('create_error'):
            sys.exit(1)
        path.touch(exist_ok=False)
    elif mode.get('cleanup_error'):
        sys.exit(1)
    else:
        path.unlink(missing_ok=True)
    sys.exit(0)
config = pathlib.Path(next(arg.split('=', 1)[1] for arg in args if arg.startswith('--config=')))
assert stat.S_IMODE(config.stat().st_mode) == 0o600
assert not any('synthetic-db-password' in arg for arg in args)
assert os.environ['ODOO_TEST_FAILURE_RETRIES'] == '0'
(root / '.started').touch()
if mode.get('hold'):
    time.sleep(30)
if mode.get('missing_report'):
    sys.exit(0)
if mode.get('fifo_report'):
    os.mkfifo(os.environ['DEVKIT_ODOO_REPORT'])
    sys.exit(0)
tests = mode.get('tests', dict(collected=2, run=2, failed=0, skipped=0))
failures = ([dict(test='sample.Probe.test_failure', output='AssertionError: fixture failed')]
            if tests['failed'] else [])
report = dict(protocol=1, job_token=os.environ['DEVKIT_ODOO_JOB_TOKEN'],
              complete=mode.get('complete', True), tests=tests, failures=failures,
              failures_omitted=0)
report.update(mode.get('report', {}))
pathlib.Path(os.environ['DEVKIT_ODOO_REPORT']).write_text(json.dumps(report))
print('synthetic-db-password' if mode.get('secret_log') else 'native log tail', file=sys.stderr)
sys.exit(mode.get('exit_code', int(bool(tests['failed']))))
"""


@pytest.fixture
def runtime_project(odoo_project, monkeypatch, tmp_path):
    project, module = odoo_project
    (project / "devkit.toml").write_text(
        'plugins=["odoo"]\ntimeout=30\n[options.odoo]\nmodule="example"\n'
    )
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    with config.open("a") as stream:
        for command in ("odoo.runtime.check", "odoo.module.test"):
            stream.write(
                f'\n[commands."{command}"]\nproject={json.dumps(str(project))}\n'
                f'effects={json.dumps(sorted(EFFECTS))}\nsurfaces=["python"]\n'
            )
    executable = tmp_path / "backend.py"
    executable.write_text(BACKEND)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("odoo-bin", "psql", "createdb", "dropdb"):
        path = bin_dir / name
        path.write_text(
            "#!/bin/sh\nexec " + shlex.join([sys.executable, str(executable), name]) + ' "$@"\n'
        )
        path.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_ODOO_ROOT", str(project))
    monkeypatch.setenv("PGPASSWORD", "synthetic-db-password")
    for key in ("PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(key, raising=False)
    (project / ".backend.json").write_text("{}")
    (project / ".databases").mkdir()
    return project


def configure(project, **options):
    (project / ".backend.json").write_text(json.dumps(options))


def execute(project, arguments=None):
    return create_service(project).execute("odoo.module.test", arguments)["result"]


def assert_clean(project, result):
    assert result["data"]["cleanup"]["status"] == "complete", result
    assert result["data"]["database"].startswith("devkit_test_")
    assert list((project / ".databases").iterdir()) == []


def test_runtime_commands_declare_all_effects(runtime_project):
    commands = create_service(runtime_project).commands
    assert commands["odoo.module.test"].effects == EFFECTS
    assert commands["odoo.runtime.check"].effects == EFFECTS


def test_runtime_pass_records_counts_and_cleanup(runtime_project):
    result = execute(runtime_project)
    assert result["status"] == "success", result
    assert result["data"]["tests"] == dict(collected=2, run=2, failed=0, skipped=0)
    assert "native log tail" in result["data"]["log_tail"]
    assert_clean(runtime_project, result)


def test_runtime_failing_test_is_named(runtime_project):
    configure(runtime_project, tests=dict(collected=2, run=2, failed=1, skipped=0))
    result = execute(runtime_project)
    assert (result["status"], result["reason"]) == ("failed", "TEST_FAILED"), result
    assert result["data"]["failures"][0]["test"] == "sample.Probe.test_failure"
    assert "fixture failed" in result["data"]["failures"][0]["output"]
    assert_clean(runtime_project, result)


@pytest.mark.parametrize("collected,skipped", [(0, 0), (2, 2)])
def test_runtime_zero_executed_tests_is_blocked(runtime_project, collected, skipped):
    configure(runtime_project, tests=dict(collected=collected, run=0, failed=0, skipped=skipped))
    result = execute(runtime_project)
    assert (result["status"], result["reason"]) == ("blocked", "NO_TESTS"), result
    assert_clean(runtime_project, result)


@pytest.mark.parametrize(
    "options,status,reason",
    [
        ({"database_unavailable": True}, "blocked", "DATABASE_UNAVAILABLE"),
        ({"no_createdb": True}, "blocked", "DATABASE_PERMISSION"),
        ({"version": "Odoo Server 18.0"}, "blocked", "UNSUPPORTED_ODOO"),
        ({"missing_report": True}, "blocked", "TEST_REPORT_UNAVAILABLE"),
        ({"complete": False}, "blocked", "INCOMPLETE_TEST_REPORT"),
        ({"report": {"job_token": "another-job"}}, "error", "INVALID_TOOL_OUTPUT"),
        ({"report": {"tests": {"collected": True}}}, "error", "INVALID_TOOL_OUTPUT"),
        ({"fifo_report": True}, "error", "INVALID_TOOL_OUTPUT"),
        ({"tests": dict(collected=0, run=1, failed=0, skipped=0)}, "error", "INVALID_TOOL_OUTPUT"),
        ({"exit_code": 1}, "failed", "INSTALL_FAILED"),
        ({"create_error": True}, "error", "DATABASE_CREATE_FAILED"),
        ({"cleanup_error": True}, "error", "CLEANUP_FAILED"),
    ],
)
def test_runtime_failures_never_claim_a_pass(runtime_project, options, status, reason):
    configure(runtime_project, **options)
    result = execute(runtime_project)
    assert (result["status"], result["reason"]) == (status, reason), result
    if reason == "CLEANUP_FAILED":
        assert result["data"]["cleanup"]["status"] == "failed"
        assert (runtime_project / ".databases" / result["data"]["database"]).exists()
    else:
        assert list((runtime_project / ".databases").iterdir()) == []


def test_runtime_prerequisite_check_creates_no_database(runtime_project):
    result = create_service(runtime_project).execute("odoo.runtime.check")["result"]
    assert result["status"] == "success", result
    assert list((runtime_project / ".databases").iterdir()) == []
    tools = {
        json.loads(line)[0] for line in (runtime_project / ".calls.jsonl").read_text().splitlines()
    }
    assert tools == {"odoo-bin", "psql"}


def test_runtime_missing_executable_is_blocked(runtime_project):
    result = execute(runtime_project, {"odoo_bin": "/nonexistent/devkit-odoo"})
    assert (result["status"], result["reason"]) == ("blocked", "MISSING_TOOL"), result
    assert not (runtime_project / ".calls.jsonl").exists()


def test_runtime_partial_grant_denies_before_process_execution(runtime_project):
    policy = Path(os.environ["XDG_CONFIG_HOME"]) / "devkit/policy.toml"
    policy.write_text(policy.read_text().replace(json.dumps(sorted(EFFECTS)), '["read_fs"]'))
    result = execute(runtime_project)
    assert result["status"] == "blocked", result
    assert not (runtime_project / ".calls.jsonl").exists()


@pytest.mark.parametrize("arguments", [{"module": "bad,module"}, {"addons_paths": ["../outside"]}])
def test_runtime_unsafe_selection_never_executes(runtime_project, arguments):
    result = execute(runtime_project, arguments)
    assert result["status"] != "success"
    assert not (runtime_project / ".calls.jsonl").exists()


def test_concurrent_runtime_jobs_own_distinct_databases(runtime_project):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(execute, [runtime_project, runtime_project]))
    assert len({result["data"]["database"] for result in results}) == 2
    for result in results:
        assert result["status"] == "success", result
        assert_clean(runtime_project, result)


@pytest.mark.parametrize("interruption", ["cancel", "timeout"])
def test_runtime_interruption_retains_cleanup_evidence(runtime_project, interruption):
    configure(runtime_project, hold=True)
    service = create_service(runtime_project)
    cancelled = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            service.execute,
            "odoo.module.test",
            cancellation=cancelled,
            _deadline=time.monotonic() + (1.5 if interruption == "timeout" else 20),
        )
        if interruption == "cancel":
            until = time.monotonic() + 10
            while not (runtime_project / ".started").exists() and time.monotonic() < until:
                time.sleep(0.02)
            assert (runtime_project / ".started").exists()
            cancelled.set()
        result = future.result(timeout=20)["result"]
    assert result["reason"] == ("CANCELLED" if interruption == "cancel" else "TIMEOUT"), result
    assert_clean(runtime_project, result)


def test_runtime_evidence_redacts_database_secrets(runtime_project):
    configure(runtime_project, secret_log=True)
    envelope = create_service(runtime_project).execute("odoo.module.test")
    assert envelope["result"]["status"] == "success", envelope["result"]
    assert "synthetic-db-password" not in json.dumps(envelope)
    assert "synthetic-db-password" not in Path(envelope["evidence_path"]).read_text()
