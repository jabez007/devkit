"""Vue delivery gates use installed project tools and preserve the checked commit."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.test_gascity_odoo_checks import git

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "integrations/gascity/base/assets"
ASSETS = ROOT / "integrations/gascity/vue/assets"


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    spec = importlib.util.spec_from_file_location("vue_pack_checks", ASSETS / "checks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def job(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".gitignore").write_text("node_modules/\n")
    (project / "package.json").write_text(
        json.dumps(
            dict(
                dependencies={"vue": "fixture"},
                devDependencies={name: "fixture" for name in ("vitest", "eslint", "vue-tsc")},
            )
        )
    )
    (project / "tracked").write_text("base\n")
    tools = project / "node_modules/.bin"
    tools.mkdir(parents=True)
    control = tmp_path / "control.json"
    control.write_text("{}")
    script = r"""
import json, pathlib, sys
control = pathlib.Path(CONTROL)
mode = json.loads(control.read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with control.with_suffix('.calls').open('a') as stream:
    stream.write(json.dumps(dict(name=name, arguments=args)) + '\n')
red = mode.get('red') == name
code = 1 if red else 0
if mode.get('mutate'):
    pathlib.Path('tracked').write_text('changed during checks')
if name == 'vitest':
    report = dict(success=not red, numTotalTests=0 if mode.get('empty') else 2,
                  numPassedTests=0 if red else 2, numFailedTests=2 if red else 0,
                  numPendingTests=0)
    path = pathlib.Path(args[args.index('--outputFile') + 1])
    path.write_text('invalid' if mode.get('invalid') else json.dumps(report))
elif name == 'eslint':
    code = 2 if mode.get('broken_config') else code
    report = [dict(errorCount=1 if red else 0, warningCount=0, fatalErrorCount=0)]
    pathlib.Path(args[args.index('--output-file') + 1]).write_text(json.dumps(report))
elif name == 'playwright':
    print(json.dumps(dict(stats=dict(expected=0 if red else 1, unexpected=1 if red else 0,
                                    flaky=0, skipped=0), errors=[])))
sys.exit(0 if mode.get('wrong_exit') else code)
"""
    script = script.replace("CONTROL", repr(str(control)))
    for name in ("vitest", "eslint", "vue-tsc", "playwright"):
        path = tools / name
        path.write_text(f"#!{sys.executable}\n" + script)
        path.chmod(0o700)
    git(project, "init", "-q", "--initial-branch=devkit/vue-task")
    git(project, "add", ".")
    git(project, "commit", "-qm", "Vue fixture")
    return dict(project=str(project), artifacts=str(tmp_path / "checks"), runner=[]), control


def run(checks, job, **mode):
    config, control = job
    control.write_text(json.dumps(mode))
    checks.validate(config)
    result = checks.run(config, dict(task_id="task-one", sha256="b" * 64))
    assert json.loads((Path(result["directory"]) / "results.json").read_text()) == result
    path = control.with_suffix(".calls")
    calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return result, calls


def test_all_mandatory_gates_use_local_nonwatch_nonfixing_tools(checks, job):
    result, calls = run(checks, job)
    assert result["status"] == "success", result
    assert [call["name"] for call in calls] == ["vitest", "eslint", "vue-tsc"]
    assert calls[0]["arguments"][0] == "run"
    assert "--noEmit" in calls[2]["arguments"]
    assert all("--fix" not in call["arguments"] for call in calls)
    assert result["checks"][0]["result"]["data"]["tests"] == dict(run=2, failed=0, skipped=0)


def test_declared_playwright_runs_and_reports_counts(checks, job):
    project = Path(job[0]["project"])
    path = project / "package.json"
    package = json.loads(path.read_text())
    package["devDependencies"]["@playwright/test"] = "fixture"
    path.write_text(json.dumps(package))
    git(project, "add", ".")
    git(project, "commit", "-qm", "Project uses Playwright")
    result, calls = run(checks, job)
    assert result["status"] == "success"
    assert [call["name"] for call in calls][-1] == "playwright"
    assert result["checks"][-1]["result"]["data"]["tests"]["run"] == 1


@pytest.mark.parametrize("name", ["vitest", "eslint", "vue-tsc"])
def test_semantic_failure_is_red_and_stops_later_gates(checks, job, name):
    result, calls = run(checks, job, red=name)
    assert result["status"] == "failed", result
    assert calls[-1]["name"] == name


@pytest.mark.parametrize(
    "mode", [dict(empty=True), dict(invalid=True), dict(red="vitest", wrong_exit=True)]
)
def test_missing_tests_or_untrustworthy_reports_cannot_pass(checks, job, mode):
    result, _ = run(checks, job, **mode)
    assert result["status"] == "blocked", result


def test_missing_local_tool_never_downloads_or_uses_a_global_copy(checks, job):
    Path(job[0]["project"], "node_modules/.bin/vue-tsc").unlink()
    with pytest.raises(checks.DeliveryError, match="CHECK_TOOL_UNAVAILABLE"):
        run(checks, job)
    assert not job[1].with_suffix(".calls").exists()


def test_playwright_config_cannot_silently_skip_an_undeclared_suite(checks, job):
    project = Path(job[0]["project"])
    (project / "playwright.config.ts").write_text("export default {}\n")
    with pytest.raises(checks.DeliveryError, match="PLAYWRIGHT_DEPENDENCY_REQUIRED"):
        checks.validate(job[0])


def test_eslint_configuration_failure_is_blocked(checks, job):
    result, calls = run(checks, job, broken_config=True)
    assert result["status"] == "blocked" and calls[-1]["name"] == "eslint"


def test_worktree_change_during_checks_invalidates_the_bundle(checks, job):
    result, _ = run(checks, job, mutate=True)
    assert result["status"] == "blocked"
    assert result["reason"] == "COMMIT_CHANGES_BEFORE_CHECKS"


def test_dirty_worktree_executes_no_tools(checks, job):
    Path(job[0]["project"], "tracked").write_text("dirty")
    with pytest.raises(checks.DeliveryError, match="COMMIT_CHANGES_BEFORE_CHECKS"):
        run(checks, job)
    assert not job[1].with_suffix(".calls").exists()
